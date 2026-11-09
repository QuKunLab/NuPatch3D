clear; clc;

% ============================================================
% Paths
% ============================================================

% 修改成你的 ECLiPSE 代码目录
eclipse_dir = "/home/liyuanzhe/lyz32/ECLiPSE";

% 修改成你的 Python 转换输出目录
input_root = "/media/WD20T/lyz32/eclipse_pointcloud_mat_surface_500_fps";

% 是否跳过已经写入最终 summary 的文件
SKIP_EXISTING_IN_SUMMARY = true;

% 如果想强制全部重算，改成 true
FORCE_RECOMPUTE = false;

if ~isfolder(eclipse_dir)
    error("ECLiPSE folder not found: %s", eclipse_dir);
end

if ~isfolder(input_root)
    error("Input folder not found: %s", input_root);
end

addpath(genpath(eclipse_dir));

batches = ["batch1", "batch2", "batch3"];

% ============================================================
% Existing output paths
% ============================================================

cell_out = fullfile(input_root, "all_batches_eclipse_descriptors_cell_level.csv");
file_out = fullfile(input_root, "all_batches_eclipse_descriptors_file_summary.csv");
mat_out = fullfile(input_root, "all_batches_eclipse_descriptors_summary.mat");

% ============================================================
% Load existing outputs if available
% ============================================================

AllCellLevel = table;
AllFileLevel = table;

fprintf("Starting ECLiPSE batch descriptor extraction...\n");
fprintf("ECLiPSE dir: %s\n", eclipse_dir);
fprintf("Input root : %s\n", input_root);
fprintf("Skip existing in summary: %d\n", SKIP_EXISTING_IN_SUMMARY);
fprintf("Force recompute: %d\n", FORCE_RECOMPUTE);

if SKIP_EXISTING_IN_SUMMARY && ~FORCE_RECOMPUTE
    if isfile(cell_out)
        fprintf("\n[LOAD EXISTING] Cell-level summary:\n%s\n", cell_out);
        AllCellLevel = read_csv_strict(cell_out);
        fprintf("Existing cell-level rows: %d\n", height(AllCellLevel));
    else
        fprintf("\n[INFO] Existing cell-level summary not found. Start from empty.\n");
    end

    if isfile(file_out)
        fprintf("\n[LOAD EXISTING] File-level summary:\n%s\n", file_out);
        AllFileLevel = read_csv_strict(file_out);
        fprintf("Existing file-level rows: %d\n", height(AllFileLevel));
    else
        fprintf("\n[INFO] Existing file-level summary not found. Start from empty.\n");
    end
end

% ============================================================
% Build processed file key set
% ============================================================

ProcessedKeys = strings(0, 1);

if SKIP_EXISTING_IN_SUMMARY && ~FORCE_RECOMPUTE && height(AllFileLevel) > 0
    if any(strcmp(AllFileLevel.Properties.VariableNames, "source_path"))
        ProcessedKeys = string(AllFileLevel.("source_path"));
    elseif any(strcmp(AllFileLevel.Properties.VariableNames, "source_file"))
        ProcessedKeys = string(AllFileLevel.("source_file"));
    else
        warning("Existing file-level summary has no source_path or source_file. Cannot skip existing files reliably.");
        ProcessedKeys = strings(0, 1);
    end

    ProcessedKeys = unique(ProcessedKeys);
    ProcessedKeys = ProcessedKeys(strlength(ProcessedKeys) > 0);

    fprintf("\nExisting processed file keys: %d\n", numel(ProcessedKeys));
end

% ============================================================
% Run batches
% ============================================================

n_skipped_existing = 0;
n_new_computed = 0;
n_missing_skipped = 0;
n_failed = 0;

for b = 1:numel(batches)
    batch = batches(b);

    manifest_file = fullfile(input_root, batch, batch + "_manifest.csv");

    fprintf("\n========================================\n");
    fprintf("Batch: %s\n", batch);
    fprintf("Reading manifest: %s\n", manifest_file);

    if ~isfile(manifest_file)
        error("Manifest file not found: %s", manifest_file);
    end

    Manifest = read_csv_strict(manifest_file);

    fprintf("Manifest columns:\n");
    disp(Manifest.Properties.VariableNames);

    if ~any(strcmp(Manifest.Properties.VariableNames, "mat_file"))
        error("Column mat_file not found in manifest. Available columns are: %s", ...
            strjoin(string(Manifest.Properties.VariableNames), ", "));
    end

    if ~any(strcmp(Manifest.Properties.VariableNames, "metadata_csv"))
        error("Column metadata_csv not found in manifest. Available columns are: %s", ...
            strjoin(string(Manifest.Properties.VariableNames), ", "));
    end

    n_files = height(Manifest);
    fprintf("Number of files in manifest: %d\n", n_files);

    for i = 1:n_files
        mat_file = string(Manifest.("mat_file")(i));
        metadata_csv = string(Manifest.("metadata_csv")(i));

        fprintf("\n----------------------------------------\n");
        fprintf("[%d/%d] Processing:\n%s\n", i, n_files, mat_file);

        % ====================================================
        % Skip empty manifest rows, e.g. no_valid_objects
        % ====================================================
        if strlength(mat_file) == 0 || strlength(metadata_csv) == 0
            fprintf("[SKIP] Empty mat_file or metadata_csv in manifest row %d.\n", i);
            n_missing_skipped = n_missing_skipped + 1;
            continue;
        end

        if ~isfile(mat_file)
            warning("MAT file not found, skip: %s", mat_file);
            n_missing_skipped = n_missing_skipped + 1;
            continue;
        end

        if ~isfile(metadata_csv)
            warning("Metadata CSV not found, skip: %s", metadata_csv);
            n_missing_skipped = n_missing_skipped + 1;
            continue;
        end

        % ====================================================
        % Determine source key before heavy descriptor computation
        % Prefer manifest source_label_path/source_label_file.
        % If not available, read metadata.
        % ====================================================
        source_key = "";

        if any(strcmp(Manifest.Properties.VariableNames, "source_label_path"))
            source_key = string(Manifest.("source_label_path")(i));
        elseif any(strcmp(Manifest.Properties.VariableNames, "source_label_file"))
            source_key = string(Manifest.("source_label_file")(i));
        else
            TempMetadata = read_csv_strict(metadata_csv);

            if height(TempMetadata) > 0 && any(strcmp(TempMetadata.Properties.VariableNames, "source_path"))
                source_key = string(TempMetadata.("source_path")(1));
            elseif height(TempMetadata) > 0 && any(strcmp(TempMetadata.Properties.VariableNames, "source_file"))
                source_key = string(TempMetadata.("source_file")(1));
            end
        end

        % ====================================================
        % Skip files already present in final summary
        % ====================================================
        if SKIP_EXISTING_IN_SUMMARY && ~FORCE_RECOMPUTE && strlength(source_key) > 0
            if any(ProcessedKeys == source_key)
                fprintf("[SKIP EXISTING SUMMARY] Already computed:\n%s\n", source_key);
                n_skipped_existing = n_skipped_existing + 1;
                continue;
            end
        end

        % ====================================================
        % Load point clouds
        % ====================================================
        S = load(mat_file);

        if ~isfield(S, "PointClouds")
            warning("PointClouds variable not found, skip: %s", mat_file);
            n_failed = n_failed + 1;
            continue;
        end

        PointClouds = S.PointClouds;

        fprintf("Number of objects: %d\n", numel(PointClouds));

        Metadata = read_csv_strict(metadata_csv);

        if height(Metadata) ~= numel(PointClouds)
            warning( ...
                "Metadata rows (%d) != PointClouds objects (%d) for file: %s", ...
                height(Metadata), numel(PointClouds), mat_file ...
            );
        end

        % ====================================================
        % Run ECLiPSE descriptors
        % One row = one label / cell
        % ====================================================
        try
            Descriptors = CalcDescriptors3D_noImageProps(PointClouds);
        catch ME
            warning("Descriptor calculation failed for file: %s", mat_file);
            warning("Reason: %s", ME.message);
            n_failed = n_failed + 1;
            continue;
        end

        % ====================================================
        % Cell-level result
        % Same format as your original code:
        % CellLevel = [Metadata Descriptors] + batch
        % ====================================================
        CellLevel = [Metadata Descriptors];

        CellLevel.batch = repmat(batch, height(CellLevel), 1);

        AllCellLevel = [AllCellLevel; CellLevel];

        % ====================================================
        % File-level summary
        % Same format as your original code
        % ====================================================
        descriptorVars = Descriptors.Properties.VariableNames;

        FileRow = table;
        FileRow.batch = batch;

        if any(strcmp(Metadata.Properties.VariableNames, "source_file"))
            FileRow.source_file = string(Metadata.("source_file")(1));
        elseif any(strcmp(Manifest.Properties.VariableNames, "source_label_file"))
            FileRow.source_file = string(Manifest.("source_label_file")(i));
        else
            FileRow.source_file = missing;
        end

        if any(strcmp(Metadata.Properties.VariableNames, "source_path"))
            FileRow.source_path = string(Metadata.("source_path")(1));
        elseif any(strcmp(Manifest.Properties.VariableNames, "source_label_path"))
            FileRow.source_path = string(Manifest.("source_label_path")(i));
        else
            FileRow.source_path = missing;
        end

        FileRow.n_cells = height(Metadata);

        for k = 1:numel(descriptorVars)
            varName = descriptorVars{k};
            values = Descriptors.(varName);

            FileRow.(strcat("mean_", varName)) = mean(values, "omitnan");
            FileRow.(strcat("median_", varName)) = median(values, "omitnan");
            FileRow.(strcat("std_", varName)) = std(values, "omitnan");
        end

        AllFileLevel = [AllFileLevel; FileRow];

        % Add this file to processed keys so duplicate manifest rows in same run are skipped
        if strlength(FileRow.source_path) > 0
            ProcessedKeys(end + 1, 1) = string(FileRow.source_path);
        elseif strlength(FileRow.source_file) > 0
            ProcessedKeys(end + 1, 1) = string(FileRow.source_file);
        end
        ProcessedKeys = unique(ProcessedKeys);

        n_new_computed = n_new_computed + 1;

        fprintf("Finished file: %s\n", mat_file);
    end
end

% ============================================================
% Save outputs
% Same output paths and same output format as original code
% ============================================================

fprintf("\n========================================\n");
fprintf("Saving outputs...\n");

% Optional: backup old outputs before overwriting
if isfile(cell_out)
    backup_cell_out = fullfile(input_root, "all_batches_eclipse_descriptors_cell_level.previous.csv");
    copyfile(cell_out, backup_cell_out);
    fprintf("[BACKUP] Previous cell-level result:\n%s\n", backup_cell_out);
end

if isfile(file_out)
    backup_file_out = fullfile(input_root, "all_batches_eclipse_descriptors_file_summary.previous.csv");
    copyfile(file_out, backup_file_out);
    fprintf("[BACKUP] Previous file-level result:\n%s\n", backup_file_out);
end

if isfile(mat_out)
    backup_mat_out = fullfile(input_root, "all_batches_eclipse_descriptors_summary.previous.mat");
    copyfile(mat_out, backup_mat_out);
    fprintf("[BACKUP] Previous MAT summary:\n%s\n", backup_mat_out);
end

writetable(AllCellLevel, cell_out);
writetable(AllFileLevel, file_out);

save(mat_out, "AllCellLevel", "AllFileLevel", "-v7.3");

fprintf("Done.\n");
fprintf("Saved cell-level result:\n%s\n", cell_out);
fprintf("Saved file-level result:\n%s\n", file_out);
fprintf("Saved MAT summary:\n%s\n", mat_out);

fprintf("\n========================================\n");
fprintf("Run summary:\n");
fprintf("Newly computed files: %d\n", n_new_computed);
fprintf("Skipped existing files: %d\n", n_skipped_existing);
fprintf("Skipped missing/empty files: %d\n", n_missing_skipped);
fprintf("Failed files: %d\n", n_failed);
fprintf("Final cell-level rows: %d\n", height(AllCellLevel));
fprintf("Final file-level rows: %d\n", height(AllFileLevel));

% ============================================================
% Helper function
% ============================================================

function T = read_csv_strict(csv_file)
    % 强制 MATLAB 按标准 CSV 读取
    % 避免 MATLAB 自动把 "/" 或其他字符误判为分隔符

    T = readtable( ...
        csv_file, ...
        "FileType", "text", ...
        "Delimiter", ",", ...
        "ReadVariableNames", true, ...
        "VariableNamingRule", "preserve" ...
    );
end