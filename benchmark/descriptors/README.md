## Input Format

- **Labels:** 3D TIFFs in ZYX order, with background `0` and positive integer instance IDs. The converter reads TIFFs directly from `<root_dir>/<batch>/labels/` for the configured batches.
- **Raw images:** required only for density/intensity features; must have the same shape and spatial alignment as their labels. Use matching names such as `sample.tif` and `sample_labels.tif`. Raw and label folders are searched recursively.
- **Voxel spacing:** configure `BATCH_SPACING_UM` in the converter and `get_spacing_from_filename()` in the density script separately. Point clouds are exported as XYZ coordinates in nm; density-script distances use μm and volumes use μm³.

## Usage

Install Python dependencies:

```bash
pip install numpy pandas scipy tifffile scikit-image
```

**1. Convert labels to ECLiPSE point clouds.** Set `root_dir`, `output_dir`, and the batch list in the converter, then run:

```bash
python "convert_labels_to_eclipse_mat.py"
```

**2. Extract shape descriptors.** Install ECLiPSE with `CalcDescriptors3D_noImageProps`. Set `eclipse_dir` and `input_root` (the converter's output directory), and adjust `batches` if needed. Run in MATLAB or from the terminal:

```bash
matlab -batch "eclipse_batch_run"
```

This saves cell-level descriptors and per-image summaries under `input_root`. Existing converted files and completed descriptor results are skipped by default; use the scripts' force flags to recompute them.

**3. Extract density/intensity features.** This step runs independently of ECLiPSE:

```bash
python density_contrast_by_raw.py /path/to/raw_images \
  --label_folder /path/to/labels \
  --output_csv image_level_density_contrast.csv \
  --local_bg_radius_factor 1.0 \
  --entropy_bins 64
```

The output contains one row per successfully processed image. Omit `--label_folder` if labels are stored with the raw images.
