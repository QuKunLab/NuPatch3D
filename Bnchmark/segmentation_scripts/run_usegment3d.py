#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch u-Segment3D anisotropic XY workflow based on the official tutorial:
    tutorials/anisotropic/segment_epithelial_organoid_2D_stacks.py

This version:
  - Processes all 3D TIF/TIFF files under an input folder recursively.
  - Removes all visualization and intermediate saving.
  - Saves only final 3D instance label TIF files to an output folder.
  - Uses Cellpose 2D on XY slices, then u-Segment3D indirect aggregation with [labels_xy, [], []].

Example:
    python batch_usegment3d_epithelial_organoid_xy.py \
        /media/WD4T/lyz32/data/hyl/example_seg \
        /media/WD4T/lyz32/data/hyl/example_seg_usegment3d_xy \
        --cuda_visible_devices 1 \
        --overwrite
"""

import os
import gc
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile
from tqdm import tqdm

import scipy.ndimage as ndimage
import skimage.filters as skfilters
import skimage.restoration as skrestoration
from skimage.transform import resize
from skimage.segmentation import relabel_sequential

import segment3D.parameters as uSegment3D_params
import segment3D.usegment3d as uSegment3D
import segment3D.filters as uSegment3D_filters
import segment3D.watershed as uSegment3D_watershed
import segment3D.flows as uSegment3D_flows

from cellpose import models
import cellpose.utils


# ============================================================
# Utilities
# ============================================================

def mkdir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def collect_tif_files(input_folder, output_folder=None):
    input_folder = Path(input_folder).resolve()
    output_folder = Path(output_folder).resolve() if output_folder is not None else None

    tif_files = []
    for p in input_folder.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in [".tif", ".tiff"]:
            continue

        p_resolved = p.resolve()

        # If output_folder is inside input_folder, do not process outputs again.
        if output_folder is not None:
            try:
                p_resolved.relative_to(output_folder)
                continue
            except ValueError:
                pass

        stem_l = p.stem.lower()
        skip_tokens = [
            "_usegment3d", "_u-segment3d", "_labels", "_label",
            "_mask", "_prob", "_semantic", "_seg", "_raw2d"
        ]
        if any(tok in stem_l for tok in skip_tokens):
            continue

        tif_files.append(p)

    return sorted(tif_files)


def read_3d_tif(path):
    img = tifffile.imread(str(path))
    img = np.asarray(img)

    # Remove singleton dimensions if present.
    img = np.squeeze(img)

    if img.ndim != 3:
        raise ValueError(f"Expected a 3D TIF with shape (Z,Y,X), got shape={img.shape}")

    return img


def make_psf(psf_size=15, sigma=1.0):
    psf = np.zeros((psf_size, psf_size), dtype=np.float32)
    psf[psf_size // 2, psf_size // 2] = 1.0
    psf = ndimage.gaussian_filter(psf, sigma=sigma) ** 2.0
    psf = psf / float(np.sum(psf))
    return psf.astype(np.float32)


def preprocess_volume(
    img,
    resize_factor=0.5,
    do_background_correction=True,
):
    """
    Follow the official anisotropic epithelial organoid tutorial:
      1. normalize
      2. downsample XY by factor
      3. slice-wise background correction
      4. normalize again
    """
    img_preprocess = uSegment3D_filters.normalize(img, clip=True)

    if resize_factor is not None and float(resize_factor) != 1.0:
        factor = float(resize_factor)
        img_preprocess = np.array([
            ndimage.zoom(imm, zoom=[factor, factor], order=1, mode="reflect")
            for imm in img_preprocess
        ])

    if do_background_correction:
        corrected = []
        global_mean = np.nanmean(img_preprocess)
        for im_ch in img_preprocess:
            sigma = max(1, int(im_ch.shape[1] // 4))
            bg = ndimage.gaussian_filter(im_ch, sigma=sigma) + 1.0
            corrected.append((global_mean / bg) * im_ch)
        img_preprocess = np.asarray(corrected, dtype=np.float32)
        img_preprocess = uSegment3D_filters.normalize(img_preprocess, clip=True)

    return img_preprocess.astype(np.float32)


def safe_multiotsu_threshold(prob, n_levels=3, level=-1, min_prob_thresh=0.1):
    try:
        threshs = skfilters.threshold_multiotsu(prob, int(n_levels))
        prob_thresh = threshs[int(level)]
        prob_thresh = int(prob_thresh * 10) / 10.0
        prob_thresh = max(prob_thresh, float(min_prob_thresh))
        return float(prob_thresh)
    except Exception:
        return float(min_prob_thresh)


def post_size_filter_labels(label_volume, min_size=0):
    label_volume = np.asarray(label_volume).astype(np.uint32)
    if min_size is None or int(min_size) <= 0 or int(label_volume.max()) == 0:
        label_volume, _, _ = relabel_sequential(label_volume.astype(np.int32))
        return label_volume.astype(np.uint32)

    max_label = int(label_volume.max())
    counts = np.bincount(label_volume.ravel().astype(np.int64), minlength=max_label + 1)
    remove_ids = np.where(counts < int(min_size))[0]
    remove_ids = remove_ids[remove_ids != 0]

    if len(remove_ids) > 0:
        mask = np.isin(label_volume, remove_ids)
        label_volume[mask] = 0

    label_volume, _, _ = relabel_sequential(label_volume.astype(np.int32))
    return label_volume.astype(np.uint32)


def restore_label_shape_nearest(label_volume, target_shape):
    if tuple(label_volume.shape) == tuple(target_shape):
        out = label_volume.astype(np.uint32)
    else:
        out = resize(
            label_volume,
            output_shape=tuple(target_shape),
            order=0,
            preserve_range=True,
            anti_aliasing=False,
        )
        out = np.rint(out).astype(np.uint32)

    out, _, _ = relabel_sequential(out.astype(np.int32))
    return out.astype(np.uint32)


# ============================================================
# Cellpose 2D XY segmentation following the official tutorial
# ============================================================

def segment_xy_stack_with_cellpose(
    img_preprocess,
    model,
    cellpose_channels=(0, 0),
    model_invert=False,
    use_deconvolution=True,
    psf_size=15,
    psf_sigma=1.0,
    aggregation_params=None,
    postprocess_2d_params=None,
):
    if aggregation_params is None:
        aggregation_params = uSegment3D_params.get_2D_to_3D_aggregation_params()
    if postprocess_2d_params is None:
        postprocess_2d_params = uSegment3D_params.get_postprocess_segmentation_params()

    psf = make_psf(psf_size=psf_size, sigma=psf_sigma)

    all_masks_stack = []

    for z in tqdm(range(len(img_preprocess)), desc="Cellpose 2D XY slices"):
        im_slice = img_preprocess[z].copy()

        if np.max(im_slice) <= np.min(im_slice):
            all_masks_stack.append(np.zeros_like(im_slice, dtype=np.uint16))
            continue

        if use_deconvolution:
            try:
                im_slice = skrestoration.unsupervised_wiener(im_slice, psf)[0]
                im_slice = np.clip(im_slice, 0, 1)
            except Exception as e:
                print(f"[WARN] deconvolution failed at z={z}: {type(e).__name__}: {e}")
                im_slice = np.clip(im_slice, 0, 1)

        masks, flows, styles, best_diam = model.eval(
            im_slice,
            diameter=None,
            channels=list(cellpose_channels),
            invert=bool(model_invert),
        )

        all_probs = flows[2]
        all_flows = flows[1]

        all_probs = np.clip(all_probs, -88.72, 88.72)
        all_probs = 1.0 / (1.0 + np.exp(-all_probs))

        all_flows = np.array([
            ndimage.gaussian_filter(all_flows[ch_no], sigma=1)
            for ch_no in range(len(all_flows))
        ])
        all_flows = all_flows / (np.linalg.norm(all_flows, axis=0)[None, ...] + 1e-20)

        prob_thresh = safe_multiotsu_threshold(
            all_probs,
            n_levels=aggregation_params["combine_cell_probs"]["threshold_n_levels"],
            level=aggregation_params["combine_cell_probs"]["threshold_level"],
            min_prob_thresh=aggregation_params["combine_cell_probs"]["min_prob_thresh"],
        )

        binary = all_probs >= prob_thresh

        if not np.any(binary):
            cell_seg = np.zeros_like(binary, dtype=np.uint16)
            all_masks_stack.append(cell_seg)
            continue

        cell_seg_original, cell_seg_connected, tracks, votes_grid_acc = (
            uSegment3D_watershed.gradient_watershed2D_binary(
                binary,
                gradient_img=all_flows.transpose(1, 2, 0),
                momenta=aggregation_params["gradient_descent"]["momenta"],
                gradient_decay=aggregation_params["gradient_descent"]["gradient_decay"],
                n_iter=aggregation_params["gradient_descent"]["n_iter"],
            )
        )

        try:
            cell_seg_original, _, _ = uSegment3D_flows.remove_bad_flow_masks_2D(
                cell_seg_original,
                flow=all_flows,
                flow_threshold=postprocess_2d_params["flow_consistency"]["flow_threshold"],
                dtform_method=postprocess_2d_params["flow_consistency"]["dtform_method"],
                fixed_point_percentile=postprocess_2d_params["flow_consistency"]["edt_fixed_point_percentile"],
                n_processes=postprocess_2d_params["flow_consistency"]["n_cpu"],
                power_dist=postprocess_2d_params["flow_consistency"]["power_dist"],
                alpha=aggregation_params["combine_cell_gradients"]["alpha"],
                filter_scale=aggregation_params["combine_cell_gradients"]["ksize"],
            )
        except Exception as e:
            print(f"[WARN] remove_bad_flow_masks_2D failed at z={z}: {type(e).__name__}: {e}")

        cell_seg_original = cellpose.utils.fill_holes_and_remove_small_masks(
            cell_seg_original,
            min_size=postprocess_2d_params["size_filters"]["min_size"],
        )

        cell_seg_original, _, _ = relabel_sequential(cell_seg_original.astype(np.int32))
        all_masks_stack.append(cell_seg_original.astype(np.uint16))

    labels_xy = np.asarray(all_masks_stack)
    return labels_xy.astype(np.uint16)


# ============================================================
# u-Segment3D aggregation and postprocessing
# ============================================================

def aggregate_xy_labels_to_3d(labels_xy, img_shape, args, aggregation_params_for_post):
    indirect_params = uSegment3D_params.get_2D_to_3D_aggregation_params()

    indirect_params["indirect_method"]["smooth_sigma"] = args.indirect_smooth_sigma
    indirect_params["combine_cell_probs"]["ksize"] = args.indirect_prob_ksize
    indirect_params["combine_cell_probs"]["alpha"] = args.indirect_prob_alpha
    indirect_params["combine_cell_probs"]["smooth_sigma"] = args.indirect_prob_smooth_sigma

    indirect_params["indirect_method"]["dtform_method"] = args.dtform_method
    indirect_params["indirect_method"]["edt_fixed_point_percentile"] = args.edt_fixed_point_percentile

    indirect_params["gradient_descent"]["n_iter"] = args.indirect_n_iter
    indirect_params["gradient_descent"]["gradient_decay"] = args.indirect_gradient_decay
    indirect_params["gradient_descent"]["momenta"] = args.indirect_momenta
    indirect_params["combine_cell_probs"]["threshold_n_levels"] = args.indirect_threshold_n_levels
    indirect_params["combine_cell_probs"]["threshold_level"] = args.indirect_threshold_level
    indirect_params["combine_cell_probs"]["min_prob_thresh"] = args.indirect_min_prob_thresh

    segmentation3D, (probability3D, gradients3D) = (
        uSegment3D.aggregate_2D_to_3D_segmentation_indirect_method(
            segmentations=[labels_xy, [], []],
            img_xy_shape=tuple(img_shape),
            precomputed_binary=None,
            params=indirect_params,
            savefolder=None,
            basename=None,
        )
    )

    if args.skip_3d_postprocess:
        segmentation3D_filt = segmentation3D
    else:
        postprocess_params = uSegment3D_params.get_postprocess_segmentation_params()
        postprocess_params["size_filters"]["min_size"] = args.min_size_3d
        postprocess_params["size_filters"]["do_stats_filter"] = True
        postprocess_params["do_flow_remove"] = True
        postprocess_params["flow_consistency"]["flow_threshold"] = args.flow_threshold_3d

        try:
            segmentation3D_filt, flow_consistency_intermediates = (
                uSegment3D.postprocess_3D_cell_segmentation(
                    segmentation3D,
                    aggregation_params=aggregation_params_for_post,
                    postprocess_params=postprocess_params,
                    cell_gradients=gradients3D,
                    savefolder=None,
                    basename=None,
                )
            )
        except Exception as e:
            print(f"[WARN] official 3D postprocess failed: {type(e).__name__}: {e}")
            print("[WARN] fallback to simple 3D size filtering.")
            segmentation3D_filt = post_size_filter_labels(segmentation3D, min_size=args.min_size_3d)

    segmentation3D_filt = post_size_filter_labels(segmentation3D_filt, min_size=args.min_size_3d)
    return segmentation3D_filt.astype(np.uint32)


# ============================================================
# Per-volume and batch processing
# ============================================================

def process_one_tif(input_tif, output_tif, model, cellpose_channels, args):
    input_tif = Path(input_tif)
    output_tif = Path(output_tif)
    mkdir(output_tif.parent)

    print("\n" + "=" * 80)
    print("[PROCESS]", input_tif)
    print("[OUTPUT] ", output_tif)
    print("=" * 80)

    img = read_3d_tif(input_tif)
    original_shape = img.shape
    print("[INFO] input shape:", img.shape, "dtype:", img.dtype)

    img_preprocess = preprocess_volume(
        img,
        resize_factor=args.resize_factor,
        do_background_correction=not args.no_background_correction,
    )
    print("[INFO] preprocessed shape:", img_preprocess.shape)

    aggregation_params = uSegment3D_params.get_2D_to_3D_aggregation_params()
    aggregation_params["gradient_descent"]["n_iter"] = args.cellpose2d_n_iter
    aggregation_params["gradient_descent"]["gradient_decay"] = args.cellpose2d_gradient_decay
    aggregation_params["gradient_descent"]["momenta"] = args.cellpose2d_momenta
    aggregation_params["combine_cell_probs"]["threshold_n_levels"] = args.cellpose2d_threshold_n_levels
    aggregation_params["combine_cell_probs"]["threshold_level"] = args.cellpose2d_threshold_level
    aggregation_params["combine_cell_probs"]["min_prob_thresh"] = args.cellpose2d_min_prob_thresh

    postprocess_2d_params = uSegment3D_params.get_postprocess_segmentation_params()
    postprocess_2d_params["size_filters"]["min_size"] = args.min_size_2d
    postprocess_2d_params["flow_consistency"]["flow_threshold"] = args.flow_threshold_2d

    labels_xy = segment_xy_stack_with_cellpose(
        img_preprocess=img_preprocess,
        model=model,
        cellpose_channels=cellpose_channels,
        model_invert=args.model_invert,
        use_deconvolution=not args.no_deconvolution,
        psf_size=args.psf_size,
        psf_sigma=args.psf_sigma,
        aggregation_params=aggregation_params,
        postprocess_2d_params=postprocess_2d_params,
    )

    print("[INFO] labels_xy shape:", labels_xy.shape, "max label per stack:", int(labels_xy.max()))

    segmentation3D_filt = aggregate_xy_labels_to_3d(
        labels_xy=labels_xy,
        img_shape=img_preprocess.shape,
        args=args,
        aggregation_params_for_post=aggregation_params,
    )

    if args.restore_original_shape:
        segmentation3D_filt = restore_label_shape_nearest(segmentation3D_filt, original_shape)
        print("[INFO] restored output shape:", segmentation3D_filt.shape)

    tifffile.imwrite(str(output_tif), segmentation3D_filt.astype(np.uint32), bigtiff=True)

    print("[SAVED]", output_tif)
    print("[INFO] output shape:", segmentation3D_filt.shape)
    print("[INFO] max label:", int(segmentation3D_filt.max()))

    del img, img_preprocess, labels_xy, segmentation3D_filt
    gc.collect()


def run_batch(args):
    if args.cuda_visible_devices is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.cuda_visible_devices)
        print("[INFO] CUDA_VISIBLE_DEVICES =", os.environ["CUDA_VISIBLE_DEVICES"])

    input_folder = Path(args.input_folder).resolve()
    output_folder = Path(args.output_folder).resolve()
    mkdir(output_folder)

    tif_files = collect_tif_files(input_folder, output_folder)

    print("=" * 80)
    print("[INFO] input_folder:", input_folder)
    print("[INFO] output_folder:", output_folder)
    print("[INFO] found tif files:", len(tif_files))
    print("[INFO] model:", args.cellpose_modelname)
    print("[INFO] resize_factor:", args.resize_factor)
    print("=" * 80)

    if args.cellpose_channels == "grayscale":
        cellpose_channels = (0, 0)
    elif args.cellpose_channels == "cyto_nuclei":
        cellpose_channels = (2, 1)
    else:
        vals = [int(v) for v in args.cellpose_channels.split(",")]
        if len(vals) != 2:
            raise ValueError("cellpose_channels must be grayscale, cyto_nuclei, or two integers like 0,0")
        cellpose_channels = tuple(vals)

    model = models.Cellpose(
        model_type=args.cellpose_modelname,
        gpu=bool(args.gpu),
    )

    failed = []

    for p in tqdm(tif_files, desc="Batch volumes"):
        rel = p.relative_to(input_folder)
        out_rel = rel.with_name(rel.stem + args.suffix + ".tif")
        out_path = output_folder / out_rel

        if out_path.exists() and not args.overwrite:
            print("[SKIP] exists:", out_path)
            continue

        try:
            process_one_tif(p, out_path, model, cellpose_channels, args)
        except Exception as e:
            print("[FAILED]", p)
            print("[ERROR]", type(e).__name__, e)
            failed.append({
                "input_tif": str(p),
                "error_type": type(e).__name__,
                "error_message": str(e),
            })
            continue

    if len(failed) > 0:
        failed_csv = output_folder / "failed_usegment3d_xy_files.csv"
        pd.DataFrame(failed).to_csv(failed_csv, index=False)
        print("[INFO] failed list saved to:", failed_csv)

    print("=" * 80)
    print("[DONE]")
    print("[INFO] failed files:", len(failed))
    print("=" * 80)


# ============================================================
# CLI
# ============================================================

def build_argparser():
    parser = argparse.ArgumentParser(
        description="Batch version of u-Segment3D anisotropic epithelial organoid XY tutorial."
    )

    parser.add_argument("input_folder", type=str, help="Input folder containing 3D TIF/TIFF files.")
    parser.add_argument("output_folder", type=str, help="Output folder for final 3D label TIF files.")

    parser.add_argument("--cuda_visible_devices", type=str, default=None, help="Set CUDA_VISIBLE_DEVICES, e.g. 0 or 1.")
    parser.add_argument("--gpu", action="store_true", help="Use Cellpose GPU mode.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    parser.add_argument("--suffix", type=str, default="_usegment3d", help="Output filename suffix.")

    parser.add_argument("--cellpose_modelname", type=str, default="cyto3", help="Cellpose model name, e.g. cyto, cyto3, nuclei.")
    parser.add_argument("--cellpose_channels", type=str, default="grayscale", help="grayscale, cyto_nuclei, or two integers like 0,0.")
    parser.add_argument("--model_invert", action="store_true", help="Pass invert=True to Cellpose.")

    parser.add_argument("--resize_factor", type=float, default=0.5, help="XY resize factor before segmentation. Official tutorial default: 0.5.")
    parser.add_argument("--restore_original_shape", action="store_true", default=True, help="Restore final labels to original input shape by nearest-neighbor resize.")
    parser.add_argument("--no_restore_original_shape", dest="restore_original_shape", action="store_false", help="Save labels at preprocessed/downsampled shape.")
    parser.add_argument("--no_background_correction", action="store_true", help="Disable slice-wise background correction.")
    parser.add_argument("--no_deconvolution", action="store_true", help="Disable slice-wise unsupervised Wiener deconvolution.")
    parser.add_argument("--psf_size", type=int, default=15, help="Synthetic PSF size for deconvolution.")
    parser.add_argument("--psf_sigma", type=float, default=1.0, help="Synthetic PSF Gaussian sigma.")

    parser.add_argument("--min_size_2d", type=int, default=15, help="Minimum 2D object size.")
    parser.add_argument("--flow_threshold_2d", type=float, default=1.0, help="2D flow consistency threshold.")
    parser.add_argument("--cellpose2d_n_iter", type=int, default=100, help="2D gradient watershed iterations.")
    parser.add_argument("--cellpose2d_gradient_decay", type=float, default=0.05, help="2D gradient decay.")
    parser.add_argument("--cellpose2d_momenta", type=float, default=0.98, help="2D momenta.")
    parser.add_argument("--cellpose2d_threshold_n_levels", type=int, default=3, help="2D multi-Otsu levels.")
    parser.add_argument("--cellpose2d_threshold_level", type=int, default=-1, help="2D multi-Otsu selected level.")
    parser.add_argument("--cellpose2d_min_prob_thresh", type=float, default=0.1, help="2D minimum probability threshold.")

    parser.add_argument("--dtform_method", type=str, default="cellpose_improve", help="Distance transform method for indirect aggregation.")
    parser.add_argument("--edt_fixed_point_percentile", type=float, default=0.01, help="EDT fixed point percentile.")
    parser.add_argument("--indirect_smooth_sigma", type=float, default=1.0, help="Indirect method smooth_sigma.")
    parser.add_argument("--indirect_prob_ksize", type=int, default=1, help="Indirect combine_cell_probs ksize.")
    parser.add_argument("--indirect_prob_alpha", type=float, default=0.5, help="Indirect combine_cell_probs alpha.")
    parser.add_argument("--indirect_prob_smooth_sigma", type=float, default=1.0, help="Indirect combine_cell_probs smooth_sigma.")
    parser.add_argument("--indirect_n_iter", type=int, default=250, help="Indirect aggregation gradient descent iterations.")
    parser.add_argument("--indirect_gradient_decay", type=float, default=0.01, help="Indirect aggregation gradient decay.")
    parser.add_argument("--indirect_momenta", type=float, default=0.98, help="Indirect aggregation momenta.")
    parser.add_argument("--indirect_threshold_n_levels", type=int, default=2, help="Indirect multi-Otsu levels.")
    parser.add_argument("--indirect_threshold_level", type=int, default=-1, help="Indirect selected threshold level.")
    parser.add_argument("--indirect_min_prob_thresh", type=float, default=0.1, help="Indirect minimum probability threshold.")

    parser.add_argument("--min_size_3d", type=int, default=200, help="Minimum 3D object size.")
    parser.add_argument("--flow_threshold_3d", type=float, default=1.0, help="3D flow consistency threshold.")
    parser.add_argument("--skip_3d_postprocess", action="store_true", help="Skip official 3D postprocessing and only do size filtering.")

    return parser


def main():
    parser = build_argparser()
    args = parser.parse_args()
    run_batch(args)


if __name__ == "__main__":
    main()
