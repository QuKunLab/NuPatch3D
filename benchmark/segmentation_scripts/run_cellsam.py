#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Batch CellSAM + u-Segment3D segmentation for a folder of 3D TIF files.

This script is adapted from a single-file CellSAM + u-Segment3D pipeline:
    1. Run official CellSAM 2D segmentation slice-by-slice.
    2. Aggregate 2D labels into 3D instance labels with u-Segment3D indirect method.
    3. Save only the final 3D label TIF files.

Default behavior:
    - Recursively process all .tif/.tiff files under input_folder.
    - Use XY view only by default.
    - Do not save intermediate 2D labels.
    - Preserve relative folder structure in output_folder.
    - Output name: original_stem + "_CellSAM_uSegment3D.tif"

Example:
    python batch_cellsam_usegment3d_folder.py \
        /media/WD4T/lyz32/data/example_seg/confocal \
        /media/WD4T/lyz32/data/example_seg/confocal_cellsam_usegment3d \
        --deepcell_token YOUR_TOKEN \
        --low_contrast_enhancement \
        --cuda_visible_devices 1 \
        --overwrite

If you have already exported the token in shell, you can omit --deepcell_token:
    export DEEPCELL_ACCESS_TOKEN="YOUR_TOKEN"
    python batch_cellsam_usegment3d_folder.py input_folder output_folder
"""

import os
import argparse
from pathlib import Path

import numpy as np
import tifffile
from tqdm import tqdm

from skimage.segmentation import relabel_sequential
from skimage.transform import resize


# These are imported after environment variables are set in init_runtime().
cellsam_pipeline = None
uSegment3D_params = None
uSegment3D = None


# ============================================================
# Runtime initialization
# ============================================================

def init_runtime(deepcell_token=None, cuda_visible_devices=None):
    """
    Set environment variables before importing CellSAM/DeepCell-related modules.
    """
    if cuda_visible_devices is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(cuda_visible_devices)
        print("[INFO] CUDA_VISIBLE_DEVICES =", os.environ["CUDA_VISIBLE_DEVICES"])

    if deepcell_token is not None and deepcell_token.strip() != "":
        os.environ["DEEPCELL_ACCESS_TOKEN"] = deepcell_token.strip()

    if "DEEPCELL_ACCESS_TOKEN" not in os.environ:
        print(
            "[WARN] DEEPCELL_ACCESS_TOKEN is not set. "
            "CellSAM may fail when it tries to download or access model resources."
        )

    global cellsam_pipeline
    global uSegment3D_params
    global uSegment3D

    from cellSAM import cellsam_pipeline as _cellsam_pipeline
    import segment3D.parameters as _uSegment3D_params
    import segment3D.usegment3d as _uSegment3D

    cellsam_pipeline = _cellsam_pipeline
    uSegment3D_params = _uSegment3D_params
    uSegment3D = _uSegment3D

    print("[INFO] CellSAM and u-Segment3D imported successfully.")


# ============================================================
# CellSAM 2D segmentation helpers
# ============================================================

def normalize_to_uint8(img2d):
    """
    Robustly normalize one 2D slice to uint8.
    """
    img = img2d.astype(np.float32)

    finite_mask = np.isfinite(img)
    if not np.any(finite_mask):
        return np.zeros_like(img, dtype=np.uint8)

    vals = img[finite_mask]
    p1, p99 = np.percentile(vals, [1, 99])

    if p99 <= p1:
        return np.zeros_like(img, dtype=np.uint8)

    img = (img - p1) / (p99 - p1)
    img = np.clip(img, 0, 1)
    img[~finite_mask] = 0

    return (img * 255).astype(np.uint8)


def extract_mask_from_cellsam_output(output):
    """
    Support different CellSAM output formats:
        - ndarray
        - tuple/list containing ndarray
        - dict with masks/mask/labels/label/segmentation
    """
    if output is None:
        return None

    if isinstance(output, np.ndarray):
        return output

    if isinstance(output, (tuple, list)):
        for item in output:
            if isinstance(item, np.ndarray) and item.ndim in [2, 3]:
                return item
        return None

    if isinstance(output, dict):
        for key in ["masks", "mask", "labels", "label", "segmentation"]:
            if key in output and isinstance(output[key], np.ndarray):
                return output[key]
        return None

    return None


def call_cellsam_safely(
    img2d_u8,
    slice_name="unknown",
    use_wsi=False,
    low_contrast_enhancement=True,
    gauge_cell_size=False,
):
    """
    Safely call CellSAM.
    Try RGB input first, then grayscale input.
    """
    input_candidates = []

    img_rgb = np.stack([img2d_u8, img2d_u8, img2d_u8], axis=-1)
    img_rgb = np.ascontiguousarray(img_rgb)
    input_candidates.append(("rgb", img_rgb))

    img_gray = np.ascontiguousarray(img2d_u8)
    input_candidates.append(("gray", img_gray))

    last_error = None

    for input_mode, img_input in input_candidates:
        try:
            output = cellsam_pipeline(
                img_input,
                use_wsi=use_wsi,
                low_contrast_enhancement=low_contrast_enhancement,
                gauge_cell_size=gauge_cell_size,
            )

            mask = extract_mask_from_cellsam_output(output)

            if mask is None:
                print(
                    f"[WARN] CellSAM returned None mask at {slice_name}, "
                    f"input_mode={input_mode}"
                )
                continue

            return mask

        except Exception as e:
            last_error = e
            print(
                f"[WARN] CellSAM failed at {slice_name}, "
                f"input_mode={input_mode}: {type(e).__name__}: {e}"
            )

    print(
        f"[WARN] CellSAM failed for all input modes at {slice_name}. "
        f"Use empty mask. Last error: {last_error}"
    )

    return None


def segment_one_2d_slice_cellsam(
    img2d,
    slice_name="unknown",
    use_wsi=False,
    low_contrast_enhancement=True,
    gauge_cell_size=False,
):
    """
    Segment one 2D image using CellSAM.
    Return a 2D instance label mask with 0 as background.
    If CellSAM fails on this slice, return an all-zero mask.
    """
    img2d_u8 = normalize_to_uint8(img2d)

    if img2d_u8.max() == img2d_u8.min():
        return np.zeros_like(img2d_u8, dtype=np.int32)

    mask = call_cellsam_safely(
        img2d_u8,
        slice_name=slice_name,
        use_wsi=use_wsi,
        low_contrast_enhancement=low_contrast_enhancement,
        gauge_cell_size=gauge_cell_size,
    )

    if mask is None:
        return np.zeros(img2d_u8.shape, dtype=np.int32)

    mask = np.asarray(mask)

    if mask.ndim == 3:
        if mask.shape[-1] in [1, 3, 4]:
            mask = mask[..., 0]
        elif mask.shape[0] == 1:
            mask = mask[0]
        else:
            print(
                f"[WARN] Unexpected CellSAM mask shape {mask.shape} "
                f"at {slice_name}, use empty mask."
            )
            return np.zeros(img2d_u8.shape, dtype=np.int32)

    if mask.ndim != 2:
        print(
            f"[WARN] CellSAM mask is not 2D at {slice_name}: "
            f"shape={mask.shape}, use empty mask."
        )
        return np.zeros(img2d_u8.shape, dtype=np.int32)

    if mask.shape != img2d_u8.shape:
        print(
            f"[WARN] CellSAM mask shape mismatch at {slice_name}: "
            f"mask={mask.shape}, image={img2d_u8.shape}. Resize by nearest."
        )
        mask = resize(
            mask,
            img2d_u8.shape,
            order=0,
            preserve_range=True,
            anti_aliasing=False,
        )

    mask = mask.astype(np.int32, copy=False)

    if mask.max() <= 0:
        return np.zeros(img2d_u8.shape, dtype=np.int32)

    mask, _, _ = relabel_sequential(mask)
    return mask.astype(np.int32)


# ============================================================
# Orthoview segmentation
# ============================================================

def segment_xy_view(volume, args):
    """
    volume: (Z, Y, X)
    labels_xy: (Z, Y, X)
    """
    Z, Y, X = volume.shape
    labels_xy = np.zeros((Z, Y, X), dtype=np.int32)

    failed_count = 0
    nonzero_count = 0

    for z in tqdm(range(Z), desc="CellSAM XY slices"):
        img2d = volume[z, :, :]

        if np.max(img2d) == np.min(img2d):
            failed_count += 1
            continue

        mask = segment_one_2d_slice_cellsam(
            img2d,
            slice_name=f"xy z={z}",
            use_wsi=args.use_wsi,
            low_contrast_enhancement=args.low_contrast_enhancement,
            gauge_cell_size=args.gauge_cell_size,
        )

        labels_xy[z] = mask

        if mask.max() > 0:
            nonzero_count += 1
        else:
            failed_count += 1

    print(
        f"[INFO] XY finished: total={Z}, "
        f"nonzero_slices={nonzero_count}, empty_or_failed={failed_count}"
    )

    return labels_xy


def segment_xz_view(volume, args):
    """
    volume: (Z, Y, X)
    labels_xz: (Y, Z, X)
    """
    Z, Y, X = volume.shape
    labels_xz = np.zeros((Y, Z, X), dtype=np.int32)

    failed_count = 0
    nonzero_count = 0

    for y in tqdm(range(Y), desc="CellSAM XZ slices"):
        img2d = volume[:, y, :]

        if np.max(img2d) == np.min(img2d):
            failed_count += 1
            continue

        mask = segment_one_2d_slice_cellsam(
            img2d,
            slice_name=f"xz y={y}",
            use_wsi=args.use_wsi,
            low_contrast_enhancement=args.low_contrast_enhancement,
            gauge_cell_size=args.gauge_cell_size,
        )

        labels_xz[y] = mask

        if mask.max() > 0:
            nonzero_count += 1
        else:
            failed_count += 1

    print(
        f"[INFO] XZ finished: total={Y}, "
        f"nonzero_slices={nonzero_count}, empty_or_failed={failed_count}"
    )

    return labels_xz


def segment_yz_view(volume, args):
    """
    volume: (Z, Y, X)
    labels_yz: (X, Z, Y)
    """
    Z, Y, X = volume.shape
    labels_yz = np.zeros((X, Z, Y), dtype=np.int32)

    failed_count = 0
    nonzero_count = 0

    for x in tqdm(range(X), desc="CellSAM YZ slices"):
        img2d = volume[:, :, x]

        if np.max(img2d) == np.min(img2d):
            failed_count += 1
            continue

        mask = segment_one_2d_slice_cellsam(
            img2d,
            slice_name=f"yz x={x}",
            use_wsi=args.use_wsi,
            low_contrast_enhancement=args.low_contrast_enhancement,
            gauge_cell_size=args.gauge_cell_size,
        )

        labels_yz[x] = mask

        if mask.max() > 0:
            nonzero_count += 1
        else:
            failed_count += 1

    print(
        f"[INFO] YZ finished: total={X}, "
        f"nonzero_slices={nonzero_count}, empty_or_failed={failed_count}"
    )

    return labels_yz


# ============================================================
# u-Segment3D aggregation
# ============================================================

def check_labels_before_usegment3d(labels_xy, labels_xz, labels_yz, volume_shape):
    Z, Y, X = volume_shape

    if isinstance(labels_xy, np.ndarray):
        print("[CHECK] labels_xy:", labels_xy.shape, labels_xy.dtype, "max=", int(labels_xy.max()))
        if labels_xy.shape != (Z, Y, X):
            raise ValueError(f"labels_xy shape should be {(Z, Y, X)}, got {labels_xy.shape}")
    else:
        print("[CHECK] labels_xy: []")

    if isinstance(labels_xz, np.ndarray):
        print("[CHECK] labels_xz:", labels_xz.shape, labels_xz.dtype, "max=", int(labels_xz.max()))
        if labels_xz.shape != (Y, Z, X):
            raise ValueError(f"labels_xz shape should be {(Y, Z, X)}, got {labels_xz.shape}")
    else:
        print("[CHECK] labels_xz: []")

    if isinstance(labels_yz, np.ndarray):
        print("[CHECK] labels_yz:", labels_yz.shape, labels_yz.dtype, "max=", int(labels_yz.max()))
        if labels_yz.shape != (X, Z, Y):
            raise ValueError(f"labels_yz shape should be {(X, Z, Y)}, got {labels_yz.shape}")
    else:
        print("[CHECK] labels_yz: []")


def run_cellsam_usegment3d_one_file(input_tif, output_tif, args):
    """
    Process one 3D TIF and save only the final 3D label result.
    """
    input_tif = Path(input_tif)
    output_tif = Path(output_tif)
    output_tif.parent.mkdir(parents=True, exist_ok=True)

    volume = tifffile.imread(str(input_tif))

    print("[INFO] input:", input_tif)
    print("[INFO] input shape:", volume.shape, "dtype:", volume.dtype)

    if volume.ndim != 3:
        raise ValueError(f"Expected 3D TIF with shape=(Z,Y,X), got {volume.shape}")

    Z, Y, X = volume.shape

    labels_xy = segment_xy_view(volume, args) if args.run_xy else []
    labels_xz = segment_xz_view(volume, args) if args.run_xz else []
    labels_yz = segment_yz_view(volume, args) if args.run_yz else []

    check_labels_before_usegment3d(
        labels_xy=labels_xy,
        labels_xz=labels_xz,
        labels_yz=labels_yz,
        volume_shape=(Z, Y, X),
    )

    max_labels = []
    if isinstance(labels_xy, np.ndarray):
        max_labels.append(int(labels_xy.max()))
    if isinstance(labels_xz, np.ndarray):
        max_labels.append(int(labels_xz.max()))
    if isinstance(labels_yz, np.ndarray):
        max_labels.append(int(labels_yz.max()))

    if len(max_labels) == 0 or max(max_labels) == 0:
        raise RuntimeError(
            "CellSAM did not produce any non-zero 2D labels. "
            "Please check CellSAM model/token/input image/contrast."
        )

    print("[INFO] Running official u-Segment3D indirect aggregation...")

    indirect_params = uSegment3D_params.get_2D_to_3D_aggregation_params()

    indirect_params["postprocess_binary"]["remove_small_objects"] = int(args.min_3d_object_size)
    indirect_params["gradient_descent"]["n_iter"] = int(args.gradient_descent_n_iter)
    indirect_params["gradient_descent"]["do_mp"] = bool(args.use_multiprocessing)
    indirect_params["indirect_method"]["dtform_method"] = args.dtform_method

    segmentation3D, (probability3D, gradients3D) = (
        uSegment3D.aggregate_2D_to_3D_segmentation_indirect_method(
            segmentations=[labels_xy, labels_xz, labels_yz],
            img_xy_shape=(Z, Y, X),
            precomputed_binary=None,
            params=indirect_params,
            savefolder=None,
            basename=None,
        )
    )

    segmentation3D = segmentation3D.astype(np.uint32)

    tifffile.imwrite(
        str(output_tif),
        segmentation3D,
        bigtiff=True,
    )

    print("[SAVED]", output_tif)
    print(
        "[INFO] output shape:",
        segmentation3D.shape,
        "dtype:",
        segmentation3D.dtype,
        "max label:",
        int(segmentation3D.max()),
    )

    return output_tif


# ============================================================
# Batch processing
# ============================================================

def collect_tif_files(input_folder):
    input_folder = Path(input_folder)

    tif_files = sorted([
        p for p in input_folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in [".tif", ".tiff"]
    ])

    skip_keywords = [
        "_cellsam",
        "_usegment3d",
        "_u-segment3d",
        "_labels",
        "_mask",
        "_prob",
        "_semantic",
        "_seg",
    ]

    tif_files = [
        p for p in tif_files
        if not any(k in p.stem.lower() for k in skip_keywords)
    ]

    return tif_files


def batch_process_folder(args):
    input_folder = Path(args.input_folder)
    output_folder = Path(args.output_folder)

    output_folder.mkdir(parents=True, exist_ok=True)

    tif_files = collect_tif_files(input_folder)

    print("=" * 80)
    print("[INFO] input_folder:", input_folder)
    print("[INFO] output_folder:", output_folder)
    print("[INFO] found tif files:", len(tif_files))
    print("[INFO] run_xy:", args.run_xy, "run_xz:", args.run_xz, "run_yz:", args.run_yz)
    print("=" * 80)

    failed = []

    for p in tif_files:
        rel = p.relative_to(input_folder)
        out_rel = rel.with_name(rel.stem + args.suffix + ".tif")
        out_path = output_folder / out_rel

        if out_path.exists() and not args.overwrite:
            print(f"[SKIP] output exists: {out_path}")
            continue

        print("\n" + "=" * 80)
        print("[PROCESS]", p)
        print("[OUTPUT] ", out_path)
        print("=" * 80)

        try:
            run_cellsam_usegment3d_one_file(
                input_tif=p,
                output_tif=out_path,
                args=args,
            )
        except Exception as e:
            print(f"[FAILED] {p}")
            print(f"[ERROR] {type(e).__name__}: {e}")
            failed.append((str(p), type(e).__name__, str(e)))
            continue

    if len(failed) > 0:
        failed_csv = output_folder / "failed_cellsam_usegment3d_files.csv"
        import pandas as pd
        pd.DataFrame(
            failed,
            columns=["input_tif", "error_type", "error_message"]
        ).to_csv(failed_csv, index=False)
        print("[INFO] failed list saved to:", failed_csv)

    print("=" * 80)
    print("[DONE] batch finished.")
    print("[INFO] failed files:", len(failed))
    print("=" * 80)


# ============================================================
# CLI
# ============================================================

def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Batch CellSAM + u-Segment3D segmentation for 3D TIF folders."
    )

    parser.add_argument(
        "input_folder",
        type=str,
        help="Input folder containing 3D .tif/.tiff files. Recursively searched."
    )

    parser.add_argument(
        "output_folder",
        type=str,
        help="Output folder for final 3D segmentation labels."
    )

    parser.add_argument(
        "--deepcell_token",
        type=str,
        default=None,
        help=(
            "DeepCell access token. Prefer setting DEEPCELL_ACCESS_TOKEN in shell. "
            "Do not hard-code tokens in scripts."
        )
    )

    parser.add_argument(
        "--cuda_visible_devices",
        type=str,
        default=None,
        help="Set CUDA_VISIBLE_DEVICES, e.g. 0 or 1."
    )

    parser.add_argument(
        "--run_xy",
        action="store_true",
        default=True,
        help="Run XY view. Default: True."
    )

    parser.add_argument(
        "--no_xy",
        action="store_false",
        dest="run_xy",
        help="Disable XY view."
    )

    parser.add_argument(
        "--run_xz",
        action="store_true",
        default=False,
        help="Run XZ view. Default: False."
    )

    parser.add_argument(
        "--run_yz",
        action="store_true",
        default=False,
        help="Run YZ view. Default: False."
    )

    parser.add_argument(
        "--use_wsi",
        action="store_true",
        default=False,
        help="Pass use_wsi=True to CellSAM."
    )

    parser.add_argument(
        "--low_contrast_enhancement",
        action="store_true",
        default=True,
        help="Pass low_contrast_enhancement=True to CellSAM. Default: True."
    )

    parser.add_argument(
        "--no_low_contrast_enhancement",
        action="store_false",
        dest="low_contrast_enhancement",
        help="Disable CellSAM low_contrast_enhancement."
    )

    parser.add_argument(
        "--gauge_cell_size",
        action="store_true",
        default=False,
        help="Pass gauge_cell_size=True to CellSAM."
    )

    parser.add_argument(
        "--min_3d_object_size",
        type=int,
        default=1000,
        help="u-Segment3D postprocess_binary remove_small_objects. Default: 1000."
    )

    parser.add_argument(
        "--gradient_descent_n_iter",
        type=int,
        default=200,
        help="u-Segment3D gradient descent iterations. Default: 200."
    )

    parser.add_argument(
        "--use_multiprocessing",
        action="store_true",
        default=False,
        help="Use multiprocessing in u-Segment3D gradient descent."
    )

    parser.add_argument(
        "--dtform_method",
        type=str,
        default="cellpose_improve",
        choices=["cellpose_improve", "edt", "fmm", "fmm_skel", "cellpose_skel"],
        help="u-Segment3D distance transform method. Default: cellpose_improve."
    )

    parser.add_argument(
        "--suffix",
        type=str,
        default="_CellSAM",
        help="Output filename suffix. Default: _CellSAM."
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing output files."
    )

    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    init_runtime(
        deepcell_token=args.deepcell_token,
        cuda_visible_devices=args.cuda_visible_devices,
    )

    batch_process_folder(args)


if __name__ == "__main__":
    main()
