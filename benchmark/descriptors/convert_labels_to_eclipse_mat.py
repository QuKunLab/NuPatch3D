import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import tifffile as tiff
from scipy.io import savemat
from scipy import ndimage as ndi
from scipy.spatial import cKDTree


# ============================================================
# Batch-specific voxel size
# Unit: micrometer
# Order: (z, y, x)
# ============================================================

BATCH_SPACING_UM = {
    "batch1": (1.0, 0.415, 0.415),
    "batch2": (1.0, 0.1377, 0.1377),
    "batch3": (1.0, 0.1625, 0.1625),
}


# ============================================================
# Main parameters
# ============================================================

# 每个 object 至少需要多少点，太小的 object 跳过
MIN_POINTS = 10

# 是否使用 voxel center 坐标
USE_VOXEL_CENTER = True

# 是否只使用 surface voxel points
USE_SURFACE_POINTS = True

# 每个 object 最多保留多少点
MAX_POINTS_PER_OBJECT = 500

# 采样点之间的最小距离，单位 nm
# 这里表示任意采样点到其最近采样点的距离需要 > MIN_SAMPLE_DISTANCE_NM
MIN_SAMPLE_DISTANCE_NM = 300.0

# 下采样方式：
# "uniform_step": 确定性规则抽样，速度最快
# "random": 随机抽样，但固定 seed
# "fps": farthest point sampling
# "fps_min_dist": FPS + 最小点间距约束
DOWNSAMPLE_MODE = "fps_min_dist"

# 是否跳过已经生成过的点云文件
# 判断标准：对应 .mat 和 metadata.csv 同时存在
SKIP_EXISTING = True

# 是否强制重新生成所有文件
# True 时会忽略 SKIP_EXISTING
FORCE_REGENERATE = False


# ============================================================
# Utility functions
# ============================================================

def safe_filename(name: str) -> str:
    """
    Convert filename to a filesystem-safe base name.
    """
    name = Path(name).stem
    name = re.sub(r"[^\w\-.]+", "_", name)
    return name


def get_batch_spacing_um(batch_name: str):
    """
    Return spacing in um with order (z, y, x).
    """
    if batch_name not in BATCH_SPACING_UM:
        raise ValueError(
            f"Unknown batch: {batch_name}. "
            f"Expected one of {list(BATCH_SPACING_UM.keys())}"
        )
    return BATCH_SPACING_UM[batch_name]


def is_tif_file(path: Path) -> bool:
    """
    Return True if path is a TIF/TIFF file.
    """
    return path.name.lower().endswith((".tif", ".tiff"))


def existing_output_is_valid(output_mat: Path, output_csv: Path) -> bool:
    """
    Check whether a label TIF has already been converted.

    A file is treated as already converted only when both files exist:
        xxx_eclipse_pointclouds.mat
        xxx_eclipse_pointclouds_metadata.csv
    """
    return output_mat.exists() and output_csv.exists()


def count_objects_from_existing_metadata(output_csv: Path) -> int:
    """
    Count objects from an existing metadata csv.

    If reading fails, return -1.
    """
    try:
        meta = pd.read_csv(output_csv)
        return int(len(meta))
    except Exception:
        return -1


def extract_surface_mask(cell_mask: np.ndarray) -> np.ndarray:
    """
    Extract surface voxels from a binary 3D object mask.

    Surface voxel is defined as:
        cell_mask & (~binary_erosion(cell_mask))

    If the object is too thin or erosion fails, fallback to full cell_mask.
    """
    if cell_mask.ndim != 3:
        return cell_mask

    if not np.any(cell_mask):
        return cell_mask

    structure = np.ones((3, 3, 3), dtype=bool)

    try:
        eroded = ndi.binary_erosion(
            cell_mask,
            structure=structure,
            border_value=0
        )

        surface_mask = cell_mask & (~eroded)

        if not np.any(surface_mask):
            return cell_mask

        return surface_mask

    except Exception:
        return cell_mask


def farthest_point_sampling(
    coords_nm: np.ndarray,
    max_points: int,
    start_mode: str = "centroid",
) -> np.ndarray:
    """
    Farthest Point Sampling (FPS) for 3D point clouds.

    This implementation does not build a full N x N distance matrix.
    Complexity is O(N * max_points).

    Parameters
    ----------
    coords_nm:
        N x 3 point cloud, columns = [x_nm, y_nm, z_nm].
    max_points:
        Number of sampled points.
    start_mode:
        "centroid": start from point farthest from centroid.
        "first": start from first point.

    Returns
    -------
    sampled_coords:
        max_points x 3 sampled point cloud.
    """
    coords = np.asarray(coords_nm, dtype=np.float64)
    n_points = coords.shape[0]

    if n_points <= max_points:
        return coords

    selected_idx = np.empty(max_points, dtype=np.int64)

    if start_mode == "centroid":
        centroid = coords.mean(axis=0)
        dist2_to_centroid = np.sum((coords - centroid) ** 2, axis=1)
        first_idx = int(np.argmax(dist2_to_centroid))
    elif start_mode == "first":
        first_idx = 0
    else:
        raise ValueError(f"Unknown start_mode: {start_mode}")

    selected_idx[0] = first_idx

    # min_dist2[j] = squared distance from point j to nearest selected point
    min_dist2 = np.sum((coords - coords[first_idx]) ** 2, axis=1)

    for i in range(1, max_points):
        next_idx = int(np.argmax(min_dist2))
        selected_idx[i] = next_idx

        dist2_to_new = np.sum((coords - coords[next_idx]) ** 2, axis=1)
        min_dist2 = np.minimum(min_dist2, dist2_to_new)

    return coords[selected_idx]


def farthest_point_sampling_min_distance(
    coords_nm: np.ndarray,
    max_points: int,
    min_distance_nm: float,
    start_mode: str = "centroid",
) -> np.ndarray:
    """
    Farthest Point Sampling with a minimum pairwise distance constraint.

    The sampled points satisfy:
        nearest-neighbor distance > min_distance_nm

    Parameters
    ----------
    coords_nm:
        N x 3 point cloud, columns = [x_nm, y_nm, z_nm].
    max_points:
        Maximum number of sampled points.
    min_distance_nm:
        Minimum allowed distance between sampled points, in nm.
    start_mode:
        "centroid": start from point farthest from centroid.
        "first": start from first point.

    Returns
    -------
    sampled_coords:
        M x 3 sampled point cloud, where M <= max_points.
    """
    coords = np.asarray(coords_nm, dtype=np.float64)
    n_points = coords.shape[0]

    if n_points == 0:
        return coords

    if max_points is None:
        max_points_eff = n_points
    else:
        max_points_eff = min(int(max_points), n_points)

    min_dist2_threshold = float(min_distance_nm) ** 2

    selected_idx = []

    if start_mode == "centroid":
        centroid = coords.mean(axis=0)
        dist2_to_centroid = np.sum((coords - centroid) ** 2, axis=1)
        first_idx = int(np.argmax(dist2_to_centroid))
    elif start_mode == "first":
        first_idx = 0
    else:
        raise ValueError(f"Unknown start_mode: {start_mode}")

    selected_idx.append(first_idx)

    # min_dist2[j] = squared distance from point j to nearest selected point
    min_dist2 = np.sum((coords - coords[first_idx]) ** 2, axis=1)

    while len(selected_idx) < max_points_eff:
        next_idx = int(np.argmax(min_dist2))
        best_dist2 = float(min_dist2[next_idx])

        # 严格要求距离 > min_distance_nm
        if best_dist2 <= min_dist2_threshold:
            break

        selected_idx.append(next_idx)

        dist2_to_new = np.sum((coords - coords[next_idx]) ** 2, axis=1)
        min_dist2 = np.minimum(min_dist2, dist2_to_new)

    return coords[np.array(selected_idx, dtype=np.int64)]


def check_nearest_neighbor_distance(coords_nm: np.ndarray):
    """
    Compute nearest-neighbor distance statistics for sampled point cloud.

    Returns
    -------
    dict with min / mean / median / std NN distance in nm and um.
    """
    coords_nm = np.asarray(coords_nm, dtype=np.float64)

    if coords_nm.ndim != 2 or coords_nm.shape[1] != 3 or coords_nm.shape[0] < 2:
        return {
            "actual_min_nn_dist_nm": np.nan,
            "actual_mean_nn_dist_nm": np.nan,
            "actual_median_nn_dist_nm": np.nan,
            "actual_std_nn_dist_nm": np.nan,
            "actual_min_nn_dist_um": np.nan,
            "actual_mean_nn_dist_um": np.nan,
            "actual_median_nn_dist_um": np.nan,
            "actual_std_nn_dist_um": np.nan,
        }

    tree = cKDTree(coords_nm)

    # k=2: 第一个最近邻是点自身，距离为 0；第二个才是真正最近点
    dists, _ = tree.query(coords_nm, k=2)

    nn = dists[:, 1]

    min_nm = float(np.min(nn))
    mean_nm = float(np.mean(nn))
    median_nm = float(np.median(nn))
    std_nm = float(np.std(nn))

    return {
        "actual_min_nn_dist_nm": min_nm,
        "actual_mean_nn_dist_nm": mean_nm,
        "actual_median_nn_dist_nm": median_nm,
        "actual_std_nn_dist_nm": std_nm,
        "actual_min_nn_dist_um": min_nm / 1000.0,
        "actual_mean_nn_dist_um": mean_nm / 1000.0,
        "actual_median_nn_dist_um": median_nm / 1000.0,
        "actual_std_nn_dist_um": std_nm / 1000.0,
    }


def downsample_points(
    coords_nm: np.ndarray,
    max_points: Optional[int],
    label_id: int,
    mode: str = "uniform_step",
    min_distance_nm: Optional[float] = None,
) -> np.ndarray:
    """
    Downsample point cloud.

    Parameters
    ----------
    coords_nm:
        N x 3 array, columns are [x_nm, y_nm, z_nm].
    max_points:
        Maximum number of points per object.
    label_id:
        Used as random seed if mode == "random".
    mode:
        "uniform_step", "random", "fps", or "fps_min_dist".
    min_distance_nm:
        Minimum distance constraint in nm, only used by "fps_min_dist".

    Returns
    -------
    coords_nm_downsampled:
        M x 3 array.
    """
    if coords_nm.shape[0] == 0:
        return coords_nm

    n = coords_nm.shape[0]

    if mode == "uniform_step":
        if max_points is None or n <= max_points:
            return coords_nm

        step = int(np.ceil(n / max_points))
        coords_ds = coords_nm[::step]

        if coords_ds.shape[0] > max_points:
            coords_ds = coords_ds[:max_points]

        return coords_ds

    elif mode == "random":
        if max_points is None or n <= max_points:
            return coords_nm

        rng = np.random.default_rng(seed=int(label_id))
        keep_idx = rng.choice(n, size=max_points, replace=False)
        keep_idx = np.sort(keep_idx)
        return coords_nm[keep_idx]

    elif mode == "fps":
        if max_points is None or n <= max_points:
            return coords_nm

        return farthest_point_sampling(
            coords_nm=coords_nm,
            max_points=max_points,
            start_mode="centroid",
        )

    elif mode == "fps_min_dist":
        if min_distance_nm is None:
            raise ValueError("min_distance_nm must be provided when mode='fps_min_dist'.")

        if max_points is None:
            max_points = n

        return farthest_point_sampling_min_distance(
            coords_nm=coords_nm,
            max_points=max_points,
            min_distance_nm=min_distance_nm,
            start_mode="centroid",
        )

    else:
        raise ValueError(
            f"Unknown downsample mode: {mode}. "
            f"Expected one of: 'uniform_step', 'random', 'fps', 'fps_min_dist'."
        )


# ============================================================
# Core conversion
# ============================================================

def label_image_to_pointclouds(
    label_path,
    spacing_um,
    min_points=10,
    use_voxel_center=True,
    use_surface_points=True,
    max_points_per_object=500,
    downsample_mode="fps_min_dist",
    min_sample_distance_nm=500.0,
):
    """
    Convert one 3D label image into multiple ECLiPSE-compatible point clouds.

    Parameters
    ----------
    label_path:
        Path to 3D label TIF.
    spacing_um:
        Voxel size in micrometer, order = (z, y, x).
    min_points:
        Skip objects with fewer points than this threshold.
    use_voxel_center:
        If True, use voxel center coordinate: (index + 0.5) * spacing.
        If False, use voxel corner coordinate: index * spacing.
    use_surface_points:
        If True, extract only surface voxels from each object.
    max_points_per_object:
        Maximum number of points per label object after surface extraction.
    downsample_mode:
        "uniform_step", "random", "fps", or "fps_min_dist".
    min_sample_distance_nm:
        Minimum nearest-neighbor distance constraint after sampling, in nm.

    Returns
    -------
    pointclouds:
        list of N_i x 3 arrays, columns = [x_nm, y_nm, z_nm].
    metadata_rows:
        list of dictionaries, one row per object.
    """
    label_path = Path(label_path)

    labels = tiff.imread(label_path)

    if labels.ndim != 3:
        print(f"[SKIP] Non-3D label image: {label_path}, shape={labels.shape}")
        return [], []

    labels = labels.astype(np.int64, copy=False)

    z_um, y_um, x_um = spacing_um
    z_nm = z_um * 1000.0
    y_nm = y_um * 1000.0
    x_nm = x_um * 1000.0

    max_label = int(labels.max())
    if max_label <= 0:
        print(f"[SKIP] No foreground labels: {label_path}")
        return [], []

    # find_objects returns one bounding box per label ID.
    # This avoids scanning the whole volume for every label.
    objects = ndi.find_objects(labels)

    pointclouds = []
    metadata_rows = []

    for label_id, slc in enumerate(objects, start=1):
        if slc is None:
            continue

        z_slice, y_slice, x_slice = slc
        crop = labels[slc]

        cell_mask = crop == label_id
        n_voxels_original = int(np.sum(cell_mask))

        if n_voxels_original < min_points:
            continue

        if use_surface_points:
            point_mask = extract_surface_mask(cell_mask)
        else:
            point_mask = cell_mask

        n_points_before_downsample = int(np.sum(point_mask))

        if n_points_before_downsample < min_points:
            continue

        local_z, local_y, local_x = np.nonzero(point_mask)

        # Convert local crop coordinates to global voxel indices.
        global_z = local_z + z_slice.start
        global_y = local_y + y_slice.start
        global_x = local_x + x_slice.start

        if use_voxel_center:
            global_z = global_z.astype(np.float64) + 0.5
            global_y = global_y.astype(np.float64) + 0.5
            global_x = global_x.astype(np.float64) + 0.5
        else:
            global_z = global_z.astype(np.float64)
            global_y = global_y.astype(np.float64)
            global_x = global_x.astype(np.float64)

        # ECLiPSE expects columns [x, y, z] in nm.
        coords_nm = np.column_stack([
            global_x * x_nm,
            global_y * y_nm,
            global_z * z_nm,
        ]).astype(np.float64)

        coords_nm = downsample_points(
            coords_nm=coords_nm,
            max_points=max_points_per_object,
            label_id=label_id,
            mode=downsample_mode,
            min_distance_nm=min_sample_distance_nm,
        )

        n_points_used = int(coords_nm.shape[0])

        if n_points_used < min_points:
            continue

        nn_stats = check_nearest_neighbor_distance(coords_nm)

        pointclouds.append(coords_nm)

        metadata_row = {
            "source_file": label_path.name,
            "source_path": str(label_path),
            "label_id": int(label_id),

            # 原始体素数量，仍然代表 label 的真实 mask 大小
            "n_voxels": int(n_voxels_original),

            # 表面点数量，即下采样前的点数
            "n_surface_points": int(n_points_before_downsample),

            # 真正送入 ECLiPSE 的点数
            "n_points_used": int(n_points_used),

            "used_surface_points": bool(use_surface_points),
            "downsampled": bool(n_points_used < n_points_before_downsample),

            "max_points_per_object": (
                int(max_points_per_object)
                if max_points_per_object is not None
                else -1
            ),
            "min_sample_distance_nm": float(min_sample_distance_nm),
            "min_sample_distance_um": float(min_sample_distance_nm) / 1000.0,
            "downsample_mode": str(downsample_mode),

            "spacing_z_um": float(z_um),
            "spacing_y_um": float(y_um),
            "spacing_x_um": float(x_um),

            "spacing_z_nm": float(z_nm),
            "spacing_y_nm": float(y_nm),
            "spacing_x_nm": float(x_nm),

            "bbox_z_min": int(z_slice.start),
            "bbox_z_max": int(z_slice.stop),
            "bbox_y_min": int(y_slice.start),
            "bbox_y_max": int(y_slice.stop),
            "bbox_x_min": int(x_slice.start),
            "bbox_x_max": int(x_slice.stop),
        }

        metadata_row.update(nn_stats)
        metadata_rows.append(metadata_row)

    return pointclouds, metadata_rows


def save_one_image_pointclouds_to_mat(
    pointclouds,
    metadata_rows,
    output_mat,
    output_metadata_csv,
    batch_name,
    spacing_um,
):
    """
    Save one label TIF's point clouds into one ECLiPSE-compatible .mat file.

    MATLAB variables:
        PointClouds:
            N x 1 cell array.
            PointClouds{i}: n_i x 3 double matrix, [x_nm, y_nm, z_nm].
        BatchName:
            batch name.
        ScaleXYZ_nm:
            [x_nm, y_nm, z_nm].
    """
    output_mat = Path(output_mat)
    output_metadata_csv = Path(output_metadata_csv)

    output_mat.parent.mkdir(parents=True, exist_ok=True)
    output_metadata_csv.parent.mkdir(parents=True, exist_ok=True)

    n = len(pointclouds)

    pointcloud_cell = np.empty((n, 1), dtype=object)

    for i, pc in enumerate(pointclouds):
        pointcloud_cell[i, 0] = pc

    metadata_df = pd.DataFrame(metadata_rows)

    if len(metadata_df) > 0:
        metadata_df.insert(
            0,
            "matlab_object_index",
            np.arange(1, len(metadata_df) + 1)
        )

    z_um, y_um, x_um = spacing_um

    scale_xyz_nm = np.array([
        x_um * 1000.0,
        y_um * 1000.0,
        z_um * 1000.0,
    ], dtype=np.float64)

    savemat(
        output_mat,
        {
            "PointClouds": pointcloud_cell,
            "BatchName": str(batch_name),
            "ScaleXYZ_nm": scale_xyz_nm,
        },
        do_compression=True,
    )

    metadata_df.to_csv(output_metadata_csv, index=False)

    print(f"[SAVE] {output_mat}")
    print(f"[SAVE] {output_metadata_csv}")
    print(f"       objects: {n}")

    if len(metadata_df) > 0:
        print(
            f"       total points used: {metadata_df['n_points_used'].sum()} | "
            f"max/object: {metadata_df['n_points_used'].max()} | "
            f"median/object: {metadata_df['n_points_used'].median():.1f} | "
            f"min actual NN dist nm: {metadata_df['actual_min_nn_dist_nm'].min():.2f}"
        )


def convert_one_batch_per_image(
    root_dir,
    batch_name,
    output_dir,
    min_points=10,
    use_voxel_center=True,
    use_surface_points=True,
    max_points_per_object=500,
    downsample_mode="fps_min_dist",
    min_sample_distance_nm=500.0,
    skip_existing=True,
    force_regenerate=False,
):
    """
    Convert all label TIF files in one batch's labels folder.

    If skip_existing=True:
        If both output .mat and metadata.csv already exist, skip this label file.

    If force_regenerate=True:
        Always regenerate outputs, even if they already exist.
    """
    root_dir = Path(root_dir)
    output_dir = Path(output_dir)

    labels_dir = root_dir / batch_name / "labels"
    batch_out_dir = output_dir / batch_name
    batch_out_dir.mkdir(parents=True, exist_ok=True)

    if not labels_dir.exists():
        raise FileNotFoundError(f"Labels folder not found: {labels_dir}")

    spacing_um = get_batch_spacing_um(batch_name)

    label_files = sorted([
        p for p in labels_dir.iterdir()
        if is_tif_file(p)
    ])

    print("=" * 80)
    print(f"Batch: {batch_name}")
    print(f"Labels dir: {labels_dir}")
    print(f"Output dir: {batch_out_dir}")
    print(f"Spacing um (z,y,x): {spacing_um}")
    print(f"Use surface points: {use_surface_points}")
    print(f"Max points/object: {max_points_per_object}")
    print(f"Min sample distance nm: {min_sample_distance_nm}")
    print(f"Downsample mode: {downsample_mode}")
    print(f"Skip existing: {skip_existing}")
    print(f"Force regenerate: {force_regenerate}")
    print(f"Found label TIF files: {len(label_files)}")

    manifest_rows = []

    n_skipped_existing = 0
    n_generated = 0
    n_no_valid = 0

    for label_path in label_files:
        print("\n" + "-" * 80)
        print(f"[PROCESS] {label_path.name}")

        base = safe_filename(label_path.name)

        output_mat = batch_out_dir / f"{base}_eclipse_pointclouds.mat"
        output_csv = batch_out_dir / f"{base}_eclipse_pointclouds_metadata.csv"

        print(f"Expected MAT: {output_mat}")
        print(f"Expected CSV: {output_csv}")

        # ------------------------------------------------------------
        # Skip already converted files BEFORE reading the TIF
        # ------------------------------------------------------------
        if skip_existing and (not force_regenerate):
            mat_exists = output_mat.exists()
            csv_exists = output_csv.exists()

            print(f"MAT exists: {mat_exists}")
            print(f"CSV exists: {csv_exists}")

            if mat_exists and csv_exists:
                n_objects_existing = count_objects_from_existing_metadata(output_csv)

                print(f"[SKIP EXISTING] {label_path.name}")
                print(f"                objects: {n_objects_existing}")

                manifest_rows.append({
                    "batch": batch_name,
                    "source_label_file": label_path.name,
                    "source_label_path": str(label_path),
                    "mat_file": str(output_mat),
                    "metadata_csv": str(output_csv),
                    "n_objects": int(n_objects_existing),

                    # 保持 status = ok，避免后续 eclipse_batch_run 只筛选 ok 时漏掉旧文件
                    "status": "ok",

                    # action 额外记录本次运行到底做了什么
                    "action": "skipped_existing",
                })

                n_skipped_existing += 1
                continue

        # ------------------------------------------------------------
        # Generate new point cloud files
        # ------------------------------------------------------------
        pointclouds, metadata_rows = label_image_to_pointclouds(
            label_path=label_path,
            spacing_um=spacing_um,
            min_points=min_points,
            use_voxel_center=use_voxel_center,
            use_surface_points=use_surface_points,
            max_points_per_object=max_points_per_object,
            downsample_mode=downsample_mode,
            min_sample_distance_nm=min_sample_distance_nm,
        )

        if len(pointclouds) == 0:
            print("          no valid objects, skip save")

            manifest_rows.append({
                "batch": batch_name,
                "source_label_file": label_path.name,
                "source_label_path": str(label_path),
                "mat_file": "",
                "metadata_csv": "",
                "n_objects": 0,
                "status": "no_valid_objects",
                "action": "no_valid_objects",
            })

            n_no_valid += 1
            continue

        save_one_image_pointclouds_to_mat(
            pointclouds=pointclouds,
            metadata_rows=metadata_rows,
            output_mat=output_mat,
            output_metadata_csv=output_csv,
            batch_name=batch_name,
            spacing_um=spacing_um,
        )

        manifest_rows.append({
            "batch": batch_name,
            "source_label_file": label_path.name,
            "source_label_path": str(label_path),
            "mat_file": str(output_mat),
            "metadata_csv": str(output_csv),
            "n_objects": len(pointclouds),
            "status": "ok",
            "action": "generated",
        })

        n_generated += 1

    manifest = pd.DataFrame(manifest_rows)
    manifest_path = batch_out_dir / f"{batch_name}_manifest.csv"

    # 备份旧 manifest，避免覆盖丢失
    if manifest_path.exists():
        backup_path = batch_out_dir / f"{batch_name}_manifest.previous.csv"
        manifest_path.replace(backup_path)
        print(f"[BACKUP] previous manifest -> {backup_path}")

    manifest.to_csv(manifest_path, index=False)

    print("\n" + "=" * 80)
    print(f"[SAVE] manifest: {manifest_path}")
    print(f"Batch {batch_name} done.")
    print(f"Total label files: {len(label_files)}")
    print(f"Generated new files: {n_generated}")
    print(f"Skipped existing files: {n_skipped_existing}")
    print(f"No valid object files: {n_no_valid}")
    print(f"Manifest rows: {len(manifest)}")


def convert_all_batches_per_image(
    root_dir,
    output_dir,
    batches=("batch1", "batch2", "batch3"),
    min_points=10,
    use_voxel_center=True,
    use_surface_points=True,
    max_points_per_object=500,
    downsample_mode="fps_min_dist",
    min_sample_distance_nm=500.0,
    skip_existing=True,
    force_regenerate=False,
):
    """
    Convert all batches.
    """
    for batch_name in batches:
        convert_one_batch_per_image(
            root_dir=root_dir,
            batch_name=batch_name,
            output_dir=output_dir,
            min_points=min_points,
            use_voxel_center=use_voxel_center,
            use_surface_points=use_surface_points,
            max_points_per_object=max_points_per_object,
            downsample_mode=downsample_mode,
            min_sample_distance_nm=min_sample_distance_nm,
            skip_existing=skip_existing,
            force_regenerate=force_regenerate,
        )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    # ========================================================
    # 修改这里
    # ========================================================

    # 你的原始数据根目录：
    # root_dir/
    #     batch1/images
    #     batch1/labels
    #     batch2/images
    #     batch2/labels
    #     batch3/images
    #     batch3/labels
    root_dir = "/media/WD20T/lyz32/annotated_data_confocal"

    # 输出目录
    # 必须和你之前生成点云的 output_dir 一致，这样才能跳过已有文件
    output_dir = "/media/WD20T/lyz32/eclipse_pointcloud_mat_surface_500_fps"

    convert_all_batches_per_image(
        root_dir=root_dir,
        output_dir=output_dir,
        batches=("batch1", "batch2", "batch3"),
        min_points=MIN_POINTS,
        use_voxel_center=USE_VOXEL_CENTER,
        use_surface_points=USE_SURFACE_POINTS,
        max_points_per_object=MAX_POINTS_PER_OBJECT,
        downsample_mode=DOWNSAMPLE_MODE,
        min_sample_distance_nm=MIN_SAMPLE_DISTANCE_NM,
        skip_existing=SKIP_EXISTING,
        force_regenerate=FORCE_REGENERATE,
    )