#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import gc
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile as tiff

from scipy.spatial import cKDTree
from scipy import ndimage as ndi
from skimage.measure import regionprops_table


def log(msg):
    print(msg, flush=True)


def get_spacing_from_filename(fname):
    if "left" in fname or "right" in fname:
        return (1, 0.1625, 0.1625)
    return (1, 0.415, 0.415)


def safe_nanmean(x):
    x = np.asarray(x, dtype=float)
    if x.size == 0 or np.all(np.isnan(x)):
        return np.nan
    return float(np.nanmean(x))


def load_label_image(label_path):
    log(f"[1] Loading label: {label_path}")
    labels = tiff.imread(label_path)
    log(f"    label shape={labels.shape}, dtype={labels.dtype}, max={np.max(labels)}")
    if labels.ndim != 3:
        raise ValueError(f"Label image must be 3D, got {labels.shape}")
    return labels.astype(np.int32, copy=False)


def load_raw_image(raw_path, labels_shape):
    log(f"[2] Loading raw: {raw_path}")
    raw = tiff.imread(raw_path)
    log(f"    raw shape={raw.shape}, dtype={raw.dtype}")
    if raw.shape != labels_shape:
        raise ValueError(f"Shape mismatch: raw={raw.shape}, labels={labels_shape}")
    return raw.astype(np.float32, copy=False)


def extract_regionprops(labels):
    log("[3] Computing regionprops_table")
    props = regionprops_table(labels, properties=["label", "area", "centroid", "bbox"])
    props_df = pd.DataFrame(props)
    log(f"    num_labels={len(props_df)}")
    return props_df


def compute_density_features_from_props(
    labels,
    props_df,
    spacing,
    dilation_connectivity=1,
    nearest_pad_factor=3.0,
    min_pad_vox=8,
):
    """
    Density features based on label masks instead of centroid distance.

    1. neighbor_count_2r:
       For each label, dilate its mask by approximately 2 * equivalent_radius.
       Count how many other labels appear inside the dilated region.

    2. nearest_neighbor_distance:
       For each label, compute the minimum physical distance from this label's
       voxels to any other label's voxels using EDT within a local crop.
    """

    log("[4] Computing density features by mask dilation / boundary distance")

    label_ids = props_df["label"].to_numpy().astype(np.int32)

    voxel_volume = spacing[0] * spacing[1] * spacing[2]
    volumes = props_df["area"].to_numpy() * voxel_volume
    radii = ((3.0 * volumes) / (4.0 * np.pi)) ** (1.0 / 3.0)

    mean_spacing = float(np.mean(spacing))

    neighbor_count_2r = np.zeros(len(label_ids), dtype=np.int32)
    nearest_neighbor_distance = np.full(len(label_ids), np.nan, dtype=float)

    # 形态学结构元：connectivity=1 为 6邻域，更保守；connectivity=2/3 更宽
    structure = ndi.generate_binary_structure(rank=3, connectivity=dilation_connectivity)

    for i, label_id in enumerate(label_ids):
        if i % 100 == 0:
            log(f"    density mask feature {i}/{len(label_ids)} label={label_id}")

        bbox = (
            int(props_df.loc[i, "bbox-0"]),
            int(props_df.loc[i, "bbox-1"]),
            int(props_df.loc[i, "bbox-2"]),
            int(props_df.loc[i, "bbox-3"]),
            int(props_df.loc[i, "bbox-4"]),
            int(props_df.loc[i, "bbox-5"]),
        )

        z0, y0, x0, z1, y1, x1 = bbox

        # =========================================================
        # 1. neighbor_count within 2 radius by morphological dilation
        # =========================================================
        radius_phys = float(radii[i])
        dilate_radius_phys = 2.0 * radius_phys

        # 把物理半径换算成 dilation iterations
        # 注意：这不是严格球形半径，而是形态学膨胀步数
        dilate_iter = max(1, int(np.ceil(dilate_radius_phys / mean_spacing)))

        pad_vox = dilate_iter + 2

        zz0 = max(0, z0 - pad_vox)
        yy0 = max(0, y0 - pad_vox)
        xx0 = max(0, x0 - pad_vox)
        zz1 = min(labels.shape[0], z1 + pad_vox)
        yy1 = min(labels.shape[1], y1 + pad_vox)
        xx1 = min(labels.shape[2], x1 + pad_vox)

        labels_crop = labels[zz0:zz1, yy0:yy1, xx0:xx1]
        cell_mask = labels_crop == label_id

        if not np.any(cell_mask):
            neighbor_count_2r[i] = 0
        else:
            dilated_mask = ndi.binary_dilation(
                cell_mask,
                structure=structure,
                iterations=dilate_iter
            )

            neighbor_labels = np.unique(labels_crop[dilated_mask])
            neighbor_labels = neighbor_labels[
                (neighbor_labels != 0) &
                (neighbor_labels != label_id)
            ]

            neighbor_count_2r[i] = len(neighbor_labels)

        # =========================================================
        # 2. nearest neighbor distance by minimum mask-to-mask distance
        # =========================================================
        nearest_pad_phys = max(nearest_pad_factor * radius_phys, 2.0 * mean_spacing)
        nearest_pad_vox = max(min_pad_vox, int(np.ceil(nearest_pad_phys / mean_spacing)))

        zz0 = max(0, z0 - nearest_pad_vox)
        yy0 = max(0, y0 - nearest_pad_vox)
        xx0 = max(0, x0 - nearest_pad_vox)
        zz1 = min(labels.shape[0], z1 + nearest_pad_vox)
        yy1 = min(labels.shape[1], y1 + nearest_pad_vox)
        xx1 = min(labels.shape[2], x1 + nearest_pad_vox)

        labels_crop = labels[zz0:zz1, yy0:yy1, xx0:xx1]
        cell_mask = labels_crop == label_id
        other_mask = (labels_crop != 0) & (labels_crop != label_id)

        if np.any(cell_mask) and np.any(other_mask):
            # distance_transform_edt(~other_mask) 表示每个点到最近 other label 的距离
            dist_to_other = ndi.distance_transform_edt(
                ~other_mask,
                sampling=spacing
            )

            # 用当前 label 内部所有点到其他 label 的最小距离
            nearest_neighbor_distance[i] = float(np.min(dist_to_other[cell_mask]))
        else:
            nearest_neighbor_distance[i] = np.nan

        del labels_crop, cell_mask

    log("    mask-based density features done")

    return {
        "label_ids": label_ids,
        "volumes": volumes,
        "radii": radii,
        "neighbor_count_2r": neighbor_count_2r,
        "nearest_neighbor_distance": nearest_neighbor_distance,
    }


def compute_foreground_mean(raw, labels, label_ids):
    log("[5] Computing foreground mean intensity")
    fg_mean = ndi.mean(raw, labels=labels, index=label_ids)
    fg_mean = np.asarray(fg_mean, dtype=float)
    log("    foreground mean done")
    return fg_mean


def compute_global_contrast(raw, labels, fg_mean):
    log("[6] Computing global contrast")
    bg_mask = labels == 0
    if not np.any(bg_mask):
        log("    no global background")
        return np.nan, np.full_like(fg_mean, np.nan, dtype=float)
    global_bg_mean = float(np.mean(raw[bg_mask]))
    global_ratio = fg_mean / (global_bg_mean + 1e-8)
    log(f"    global_bg_mean={global_bg_mean}")
    return global_bg_mean, global_ratio


def compute_local_background_bbox_edt(raw, labels, label_id, bbox, radius_phys, spacing):
    z0, y0, x0, z1, y1, x1 = bbox
    mean_spacing = float(np.mean(spacing))
    pad_vox = max(2, int(np.ceil(radius_phys / mean_spacing)) + 2)

    zz0 = max(0, z0 - pad_vox)
    yy0 = max(0, y0 - pad_vox)
    xx0 = max(0, x0 - pad_vox)
    zz1 = min(labels.shape[0], z1 + pad_vox)
    yy1 = min(labels.shape[1], y1 + pad_vox)
    xx1 = min(labels.shape[2], x1 + pad_vox)

    labels_crop = labels[zz0:zz1, yy0:yy1, xx0:xx1]
    raw_crop = raw[zz0:zz1, yy0:yy1, xx0:xx1]
    cell_mask = labels_crop == label_id
    if not np.any(cell_mask):
        return np.nan

    distance_to_cell = ndi.distance_transform_edt(~cell_mask, sampling=spacing)
    local_bg_mask = (labels_crop == 0) & (~cell_mask) & (distance_to_cell <= radius_phys)
    if not np.any(local_bg_mask):
        return np.nan
    return float(np.mean(raw_crop[local_bg_mask]))


def compute_local_contrast_bbox_edt(raw, labels, props_df, label_ids, radii, fg_mean, spacing, local_bg_radius_factor=1.0):
    log("[7] Computing local contrast by bbox EDT")
    local_bg_mean = np.full(len(label_ids), np.nan, dtype=float)
    for i, label_id in enumerate(label_ids):
        if i % 100 == 0:
            log(f"    local EDT {i}/{len(label_ids)} label={label_id}")
        bbox = (
            int(props_df.loc[i, "bbox-0"]), int(props_df.loc[i, "bbox-1"]), int(props_df.loc[i, "bbox-2"]),
            int(props_df.loc[i, "bbox-3"]), int(props_df.loc[i, "bbox-4"]), int(props_df.loc[i, "bbox-5"]),
        )
        radius_phys = local_bg_radius_factor * radii[i]
        local_bg_mean[i] = compute_local_background_bbox_edt(raw, labels, int(label_id), bbox, radius_phys, spacing)
    local_ratio = fg_mean / (local_bg_mean + 1e-8)
    log("    local contrast done")
    return local_bg_mean, local_ratio


def intensity_entropy(values, bins=64):
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.nan
    hist, _ = np.histogram(values, bins=bins)
    hist = hist.astype(float)
    hist = hist[hist > 0]
    if hist.size == 0:
        return np.nan
    p = hist / hist.sum()
    return float(-np.sum(p * np.log2(p + 1e-12)))


def compute_radius1_inner_outer_ratio_edt(raw, labels, label_id, bbox, radius_phys, spacing, max_crop_voxels=5_000_000):
    z0, y0, x0, z1, y1, x1 = bbox
    mean_spacing = float(np.mean(spacing))
    pad_vox = max(2, int(np.ceil(radius_phys / mean_spacing)) + 2)

    zz0 = max(0, z0 - pad_vox)
    yy0 = max(0, y0 - pad_vox)
    xx0 = max(0, x0 - pad_vox)
    zz1 = min(labels.shape[0], z1 + pad_vox)
    yy1 = min(labels.shape[1], y1 + pad_vox)
    xx1 = min(labels.shape[2], x1 + pad_vox)

    crop_shape = (zz1 - zz0, yy1 - yy0, xx1 - xx0)
    crop_voxels = crop_shape[0] * crop_shape[1] * crop_shape[2]
    if crop_voxels > max_crop_voxels:
        log(f"      skip radius1 label={label_id}, crop_shape={crop_shape}, crop_voxels={crop_voxels}")
        return np.nan

    labels_crop = labels[zz0:zz1, yy0:yy1, xx0:xx1]
    raw_crop = raw[zz0:zz1, yy0:yy1, xx0:xx1]
    cell_mask = labels_crop == label_id
    if not np.any(cell_mask):
        return np.nan

    inner_mean = float(np.mean(raw_crop[cell_mask]))
    dist_to_cell = ndi.distance_transform_edt(~cell_mask, sampling=spacing)
    outer_mask = (labels_crop == 0) & (~cell_mask) & (dist_to_cell <= radius_phys)
    if not np.any(outer_mask):
        return np.nan
    outer_mean = float(np.mean(raw_crop[outer_mask]))
    return inner_mean / (outer_mean + 1e-8)


def compute_inner_gradient_bbox_light(raw, labels, label_id, bbox, spacing):
    z0, y0, x0, z1, y1, x1 = bbox
    if (z1 - z0) < 3 or (y1 - y0) < 3 or (x1 - x0) < 3:
        return np.nan, np.nan

    raw_crop = raw[z0:z1, y0:y1, x0:x1].astype(np.float32, copy=False)
    labels_crop = labels[z0:z1, y0:y1, x0:x1]
    mask = labels_crop == label_id
    inner_mask = mask[1:-1, 1:-1, 1:-1]
    if not np.any(inner_mask):
        return np.nan, np.nan

    dz = (raw_crop[2:, 1:-1, 1:-1] - raw_crop[:-2, 1:-1, 1:-1]) / (2.0 * spacing[0])
    dy = (raw_crop[1:-1, 2:, 1:-1] - raw_crop[1:-1, :-2, 1:-1]) / (2.0 * spacing[1])
    dx = (raw_crop[1:-1, 1:-1, 2:] - raw_crop[1:-1, 1:-1, :-2]) / (2.0 * spacing[2])
    grad_mag = np.sqrt(dx * dx + dy * dy + dz * dz)
    gvals = grad_mag[inner_mask]
    if gvals.size == 0:
        return np.nan, np.nan
    return float(np.mean(gvals)), float(np.std(gvals))


def compute_internal_variation_features_bbox_only(raw, labels, props_df, label_ids, radii, spacing, entropy_bins=64, print_every=50):
    log("[8] Computing internal variation features - bbox only")
    radius1_ratio = np.full(len(label_ids), np.nan, dtype=float)
    inner_std = np.full(len(label_ids), np.nan, dtype=float)
    inner_cv = np.full(len(label_ids), np.nan, dtype=float)
    inner_entropy = np.full(len(label_ids), np.nan, dtype=float)
    inner_grad_mean = np.full(len(label_ids), np.nan, dtype=float)
    inner_grad_std = np.full(len(label_ids), np.nan, dtype=float)

    for i, label_id in enumerate(label_ids):
        bbox = (
            int(props_df.loc[i, "bbox-0"]), int(props_df.loc[i, "bbox-1"]), int(props_df.loc[i, "bbox-2"]),
            int(props_df.loc[i, "bbox-3"]), int(props_df.loc[i, "bbox-4"]), int(props_df.loc[i, "bbox-5"]),
        )
        z0, y0, x0, z1, y1, x1 = bbox
        bbox_shape = (z1 - z0, y1 - y0, x1 - x0)
        bbox_voxels = bbox_shape[0] * bbox_shape[1] * bbox_shape[2]
        if i % print_every == 0:
            log(f"    internal bbox {i}/{len(label_ids)} label={label_id}, bbox_shape={bbox_shape}, bbox_voxels={bbox_voxels}")

        radius_phys = radii[i]
        if i < 20 or i % 50 == 0:
            log(f"      before radius1 label={label_id}, radius_phys={radius_phys:.3f}")
        radius1_ratio[i] = compute_radius1_inner_outer_ratio_edt(raw, labels, int(label_id), bbox, radius_phys, spacing)
        if i < 20 or i % 50 == 0:
            log(f"      after radius1 label={label_id}")

        labels_crop = labels[z0:z1, y0:y1, x0:x1]
        raw_crop = raw[z0:z1, y0:y1, x0:x1]
        cell_mask_crop = labels_crop == label_id
        if np.any(cell_mask_crop):
            values = raw_crop[cell_mask_crop].astype(np.float32)
            mu = float(np.mean(values))
            sigma = float(np.std(values))
            inner_std[i] = sigma
            inner_cv[i] = sigma / (mu + 1e-8)
            inner_entropy[i] = intensity_entropy(values, bins=entropy_bins)

        log(f"      before gradient label={label_id}")
        g_mean, g_std = compute_inner_gradient_bbox_light(raw, labels, int(label_id), bbox, spacing)
        log(f"      after gradient label={label_id}")
        inner_grad_mean[i] = g_mean
        inner_grad_std[i] = g_std
        del labels_crop, raw_crop, cell_mask_crop

    log("    internal variation features done")
    return {
        "radius1_ratio": radius1_ratio,
        "inner_std": inner_std,
        "inner_cv": inner_cv,
        "inner_entropy": inner_entropy,
        "inner_grad_mean": inner_grad_mean,
        "inner_grad_std": inner_grad_std,
    }


def summarize_image_features(fname, label_path, raw_path, spacing, density, fg_mean=None, global_bg_mean=np.nan, global_ratio=None, local_bg_mean=None, local_ratio=None, internal=None):
    row = {
        "label_file": fname,
        "label_path": label_path,
        "raw_path": raw_path if raw_path is not None else "",
        "num_cells": int(len(density["label_ids"])),
        "spacing_z": spacing[0],
        "spacing_y": spacing[1],
        "spacing_x": spacing[2],
        "mean_cell_volume": safe_nanmean(density["volumes"]),
        "mean_equivalent_radius": safe_nanmean(density["radii"]),
        "mean_neighbor_count_within_2radius": safe_nanmean(density["neighbor_count_2r"]),
        "mean_nearest_neighbor_distance": safe_nanmean(density["nearest_neighbor_distance"]),
    }
    if fg_mean is not None:
        row["mean_foreground_intensity"] = safe_nanmean(fg_mean)
        row["global_background_mean_intensity"] = global_bg_mean
        row["mean_global_contrast_ratio"] = safe_nanmean(global_ratio)
        row["mean_local_background_intensity"] = safe_nanmean(local_bg_mean)
        row["mean_local_contrast_ratio"] = safe_nanmean(local_ratio)
    if internal is not None:
        row["mean_radius1_inner_outer_intensity_ratio"] = safe_nanmean(internal["radius1_ratio"])
        row["mean_inner_intensity_std"] = safe_nanmean(internal["inner_std"])
        row["mean_inner_intensity_cv"] = safe_nanmean(internal["inner_cv"])
        row["mean_inner_intensity_entropy"] = safe_nanmean(internal["inner_entropy"])
        row["mean_inner_gradient_mean"] = safe_nanmean(internal["inner_grad_mean"])
        row["mean_inner_gradient_std"] = safe_nanmean(internal["inner_grad_std"])
    return row


def collect_raw_files(raw_folder):
    raw_folder = Path(raw_folder)
    return sorted([
        p for p in raw_folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in [".tif", ".tiff"]
        and "_labels" not in p.name.lower()
    ])


def collect_label_files(label_folder):
    label_folder = Path(label_folder)
    return sorted([
        p for p in label_folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in [".tif", ".tiff"]
        and "_labels" in p.name.lower()
    ])


def find_label_for_raw(raw_path, label_files):
    """
    raw: ABC.tif
    labels accepted examples:
        ABC_labels.tif
        ABC_labels_refined.tif
        ABC_cellpose_labels.tif

    Rule:
        label stem starts with raw stem, and label filename contains '_labels'.
    """
    raw_path = Path(raw_path)
    raw_stem = raw_path.stem.lower()
    candidates = []
    for label_path in label_files:
        label_stem = label_path.stem.lower()
        label_name = label_path.name.lower()
        if label_stem.startswith(raw_stem) and "_labels" in label_name:
            candidates.append(label_path)
    if len(candidates) == 0:
        return None
    exact = [p for p in candidates if p.stem.lower() == raw_stem + "_labels"]
    if len(exact) > 0:
        return exact[0]
    candidates = sorted(candidates, key=lambda p: len(p.name))
    if len(candidates) > 1:
        log(f"[WARN] Multiple label candidates for raw {raw_path.name}, use {candidates[0].name}")
        for c in candidates:
            log(f"       candidate: {c}")
    return candidates[0]


def process_density_contrast_by_raw(raw_folder, label_folder=None, output_csv="image_level_density_contrast_debug.csv", local_bg_radius_factor=1.0, entropy_bins=64):
    raw_folder = Path(raw_folder)
    label_folder = raw_folder if label_folder is None else Path(label_folder)

    raw_files = collect_raw_files(raw_folder)
    label_files = collect_label_files(label_folder)
    image_rows = []

    log("=" * 80)
    log(f"[INFO] raw_folder:   {raw_folder}")
    log(f"[INFO] label_folder: {label_folder}")
    log(f"[INFO] raw files found:   {len(raw_files)}")
    log(f"[INFO] label files found: {len(label_files)}")
    log("=" * 80)

    for raw_path in raw_files:
        raw_path = Path(raw_path)
        label_path = find_label_for_raw(raw_path, label_files)
        log("=" * 80)
        log(f"START raw file: {raw_path}")

        if label_path is None:
            log(f"[WARN] No matched label found for raw: {raw_path.name}")
            continue

        log(f"matched label: {label_path}")
        raw = None
        labels = None
        try:
            spacing = get_spacing_from_filename(raw_path.name)
            labels = load_label_image(str(label_path))
            props_df = extract_regionprops(labels)
            if len(props_df) == 0:
                log("No labels found.")
                del labels
                gc.collect()
                continue

            density = compute_density_features_from_props(
                labels=labels,
                props_df=props_df,
                spacing=spacing,
                dilation_connectivity=1
            )
            raw = load_raw_image(str(raw_path), labels.shape)
            fg_mean = compute_foreground_mean(raw, labels, density["label_ids"])
            global_bg_mean, global_ratio = compute_global_contrast(raw, labels, fg_mean)
            local_bg_mean, local_ratio = compute_local_contrast_bbox_edt(raw, labels, props_df, density["label_ids"], density["radii"], fg_mean, spacing, local_bg_radius_factor)
            internal = compute_internal_variation_features_bbox_only(raw, labels, props_df, density["label_ids"], density["radii"], spacing, entropy_bins, print_every=50)

            row = summarize_image_features(
                fname=label_path.name,
                label_path=str(label_path),
                raw_path=str(raw_path),
                spacing=spacing,
                density=density,
                fg_mean=fg_mean,
                global_bg_mean=global_bg_mean,
                global_ratio=global_ratio,
                local_bg_mean=local_bg_mean,
                local_ratio=local_ratio,
                internal=internal,
            )
            row["raw_file"] = raw_path.name
            row["raw_rel_path"] = str(raw_path.relative_to(raw_folder))
            row["label_rel_path"] = str(label_path.relative_to(label_folder))
            image_rows.append(row)

            del raw, labels
            gc.collect()
            log(f"FINISHED raw file: {raw_path}")
        except Exception as e:
            log(f"FAILED raw file: {raw_path}")
            log(f"matched label: {label_path}")
            log(f"ERROR: {type(e).__name__}: {e}")
            if raw is not None:
                del raw
            if labels is not None:
                del labels
            gc.collect()

    result = pd.DataFrame(image_rows)
    front_cols = [
        "raw_file", "label_file", "raw_rel_path", "label_rel_path",
        "raw_path", "label_path", "num_cells",
        "spacing_z", "spacing_y", "spacing_x",
    ]
    if len(result) > 0:
        other_cols = [c for c in result.columns if c not in front_cols]
        result = result.reindex(columns=front_cols + other_cols)
    result.to_csv(output_csv, index=False)
    log(f"\nSaved to: {output_csv}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compute image-level 3D density and intensity contrast features from raw TIF images and matched _labels TIF files."
    )
    parser.add_argument("raw_folder", type=str, help="Folder containing raw tif/tiff images. Recursive search.")
    parser.add_argument("--label_folder", type=str, default=None, help="Folder containing _labels tif/tiff images. If omitted, use raw_folder.")
    parser.add_argument("--output_csv", type=str, default="image_level_density_contrast_debug.csv", help="Output CSV path.")
    parser.add_argument("--local_bg_radius_factor", type=float, default=1.0, help="Radius factor for local background calculation.")
    parser.add_argument("--entropy_bins", type=int, default=64, help="Number of bins for intensity entropy.")
    args = parser.parse_args()

    process_density_contrast_by_raw(
        raw_folder=args.raw_folder,
        label_folder=args.label_folder,
        output_csv=args.output_csv,
        local_bg_radius_factor=args.local_bg_radius_factor,
        entropy_bins=args.entropy_bins,
    )


if __name__ == "__main__":
    main()
