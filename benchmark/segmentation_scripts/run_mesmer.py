#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Batch Mesmer 2D + Z-overlap stitching for 3D TIF volumes.

Input:
    A folder containing many 3D TIF/TIFF files.

Output:
    Only final stitched 3D label TIF files are saved to output_folder.

Notes:
    - Mesmer itself is applied slice-by-slice in 2D.
    - 3D labels are produced by overlap-based stitching across z-slices.
    - For single-channel input, the same image can be duplicated as the membrane channel.

Example:
    python batch_mesmer_3d_folder.py \
        /media/WD4T/lyz32/data/example_seg \
        /media/WD4T/lyz32/data/example_seg_mesmer \
        --cuda_visible_devices 1 \
        --image_mpp 0.5 \
        --compartment nuclear
"""

import os
import argparse


def _parse_pre_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cuda_visible_devices", type=str, default=None)
    args, _ = parser.parse_known_args()
    return args


_pre_args = _parse_pre_args()
if _pre_args.cuda_visible_devices is not None:
    os.environ["CUDA_VISIBLE_DEVICES"] = _pre_args.cuda_visible_devices

# Avoid TensorFlow allocating all GPU memory at once.
os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"

from pathlib import Path
import gc

import numpy as np
import pandas as pd
import tifffile
from tqdm import tqdm

from skimage.segmentation import relabel_sequential

import tensorflow as tf
from deepcell.applications import Mesmer


OUTPUT_DTYPE = np.uint32


def setup_tensorflow_memory_growth():
    gpus = tf.config.list_physical_devices("GPU")
    if len(gpus) == 0:
        print("[INFO] TensorFlow GPU not found, using CPU.", flush=True)
        return

    for gpu in gpus:
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except Exception as e:
            print("[WARNING] Could not set memory growth:", e, flush=True)

    print("[INFO] TensorFlow GPUs:", gpus, flush=True)


def normalize_slice_to_float32(img2d, p_low=1, p_high=99.8):
    img = img2d.astype(np.float32, copy=False)

    finite_mask = np.isfinite(img)
    if not np.any(finite_mask):
        return np.zeros_like(img, dtype=np.float32)

    vals = img[finite_mask]
    lo, hi = np.percentile(vals, [p_low, p_high])

    if hi <= lo:
        return np.zeros_like(img, dtype=np.float32)

    out = (img - lo) / (hi - lo)
    out = np.clip(out, 0, 1)
    out[~finite_mask] = 0

    return out.astype(np.float32)


def make_mesmer_input_single_channel(img2d, duplicate_to_membrane=True):
    """
    Convert one 2D slice to Mesmer input with shape (1, H, W, 2).
    channel 0: nuclear
    channel 1: membrane/cytoplasm
    """
    nuc = normalize_slice_to_float32(img2d)

    if duplicate_to_membrane:
        mem = nuc.copy()
    else:
        mem = np.zeros_like(nuc, dtype=np.float32)

    x = np.stack([nuc, mem], axis=-1)
    x = x[None, ...]
    return x.astype(np.float32)


def make_mesmer_input_two_channel(nuc2d, mem2d):
    nuc = normalize_slice_to_float32(nuc2d)
    mem = normalize_slice_to_float32(mem2d)

    x = np.stack([nuc, mem], axis=-1)
    x = x[None, ...]
    return x.astype(np.float32)


def parse_mesmer_output(pred, compartment="nuclear"):
    """
    Compatible with multiple Mesmer output formats:
        ndarray: (1,H,W,1)
        ndarray: (1,H,W)
        ndarray: (H,W)
        dict: {"nuclear": ..., "whole-cell": ...}
    """
    if isinstance(pred, dict):
        if compartment in pred:
            pred = pred[compartment]
        elif "nuclear" in pred:
            pred = pred["nuclear"]
        elif "whole-cell" in pred:
            pred = pred["whole-cell"]
        else:
            raise ValueError(f"Unknown Mesmer dict output keys: {list(pred.keys())}")

    pred = np.asarray(pred)

    if pred.ndim == 4:
        label2d = pred[0, ..., 0]
    elif pred.ndim == 3:
        label2d = pred[0]
    elif pred.ndim == 2:
        label2d = pred
    else:
        raise ValueError(f"Unexpected Mesmer output shape: {pred.shape}")

    label2d = label2d.astype(np.int32, copy=False)
    label2d, _, _ = relabel_sequential(label2d)

    return label2d.astype(np.uint32)


def predict_one_slice_mesmer(app, x, image_mpp=0.5, compartment="nuclear"):
    """
    Compatible with slightly different deepcell versions.
    """
    try:
        pred = app.predict(
            x,
            image_mpp=image_mpp,
            compartment=compartment,
            batch_size=1,
        )
    except TypeError:
        pred = app.predict(
            x,
            image_mpp=image_mpp,
            compartment=compartment,
        )

    label2d = parse_mesmer_output(pred, compartment=compartment)
    return label2d


class ZOverlapStitcher:
    def __init__(
        self,
        iou_threshold=0.05,
        overlap_threshold=0.25,
        max_z_gap=1,
        one_to_one_matching=True,
    ):
        self.iou_threshold = float(iou_threshold)
        self.overlap_threshold = float(overlap_threshold)
        self.max_z_gap = int(max_z_gap)
        self.one_to_one_matching = bool(one_to_one_matching)
        self.next_label = 1
        self.recent_slices = []

    @staticmethod
    def _area_bincount(label2d):
        max_label = int(label2d.max())
        if max_label == 0:
            return np.zeros(1, dtype=np.int64)
        return np.bincount(label2d.ravel().astype(np.int64), minlength=max_label + 1)

    def _collect_candidates_from_previous_slice(
        self,
        local2d,
        local_area,
        prev2d,
        prev_area,
        gap,
    ):
        candidates = []

        if local2d.max() == 0 or prev2d.max() == 0:
            return candidates

        mask = (local2d > 0) & (prev2d > 0)
        if not np.any(mask):
            return candidates

        local_vals = local2d[mask].astype(np.int64)
        prev_vals = prev2d[mask].astype(np.int64)

        factor = int(prev2d.max()) + 1
        codes = local_vals * factor + prev_vals
        uniq, counts = np.unique(codes, return_counts=True)

        for code, inter in zip(uniq, counts):
            local_id = int(code // factor)
            prev_id = int(code % factor)

            if local_id == 0 or prev_id == 0:
                continue

            curr_a = int(local_area[local_id])
            prev_a = int(prev_area[prev_id])

            if curr_a <= 0 or prev_a <= 0:
                continue

            union = curr_a + prev_a - int(inter)
            iou = float(inter) / max(union, 1)
            overlap_curr = float(inter) / max(curr_a, 1)

            if (iou >= self.iou_threshold) or (overlap_curr >= self.overlap_threshold):
                gap_penalty = 0.90 ** max(gap - 1, 0)
                score = max(iou, overlap_curr) * gap_penalty
                candidates.append((score, local_id, prev_id, iou, overlap_curr, gap))

        return candidates

    def add_slice(self, local2d, z_index=None):
        local2d = np.asarray(local2d).astype(np.int32, copy=False)
        local2d, _, _ = relabel_sequential(local2d)
        local2d = local2d.astype(np.uint32, copy=False)
        local_max = int(local2d.max())

        if local_max == 0:
            global2d = np.zeros_like(local2d, dtype=np.uint32)
            self._push_recent_slice(global2d, z_index)
            return global2d

        local_area = self._area_bincount(local2d)
        all_candidates = []

        for gap, item in enumerate(reversed(self.recent_slices), start=1):
            if gap > self.max_z_gap:
                break

            candidates = self._collect_candidates_from_previous_slice(
                local2d=local2d,
                local_area=local_area,
                prev2d=item["label"],
                prev_area=item["area"],
                gap=gap,
            )
            all_candidates.extend(candidates)

        all_candidates.sort(key=lambda x: x[0], reverse=True)

        local_to_global = {}
        used_prev_global = set()

        for score, local_id, prev_global_id, iou, overlap_curr, gap in all_candidates:
            if local_id in local_to_global:
                continue
            if self.one_to_one_matching and prev_global_id in used_prev_global:
                continue
            local_to_global[local_id] = prev_global_id
            used_prev_global.add(prev_global_id)

        for local_id in range(1, local_max + 1):
            if local_id not in local_to_global:
                local_to_global[local_id] = self.next_label
                self.next_label += 1

        lut = np.zeros(local_max + 1, dtype=np.uint32)
        for local_id, global_id in local_to_global.items():
            lut[int(local_id)] = int(global_id)

        global2d = lut[local2d]
        self._push_recent_slice(global2d, z_index)
        return global2d.astype(np.uint32)

    def _push_recent_slice(self, global2d, z_index=None):
        area = self._area_bincount(global2d)
        self.recent_slices.append(
            {
                "z": z_index,
                "label": global2d.astype(np.uint32, copy=False),
                "area": area,
            }
        )

        if len(self.recent_slices) > self.max_z_gap:
            self.recent_slices = self.recent_slices[-self.max_z_gap:]


def remove_small_3d_instances(label_volume, min_volume=0, min_slices=1):
    label_volume = np.asarray(label_volume).astype(np.uint32, copy=False)

    max_label = int(label_volume.max())
    if max_label == 0:
        return label_volume

    remove_ids = set()

    if min_volume is not None and min_volume > 0:
        counts = np.bincount(label_volume.ravel().astype(np.int64), minlength=max_label + 1)
        small_ids = np.where(counts < min_volume)[0]
        for idx in small_ids:
            if idx != 0:
                remove_ids.add(int(idx))

    if min_slices is not None and min_slices > 1:
        ids = np.unique(label_volume)
        ids = ids[ids > 0]
        for idx in ids:
            z_presence = np.any(label_volume == idx, axis=(1, 2))
            n_slices = int(np.count_nonzero(z_presence))
            if n_slices < min_slices:
                remove_ids.add(int(idx))

    if len(remove_ids) > 0:
        print("[INFO] removing small 3D instances:", len(remove_ids), flush=True)
        remove_mask = np.isin(label_volume, list(remove_ids))
        label_volume = label_volume.copy()
        label_volume[remove_mask] = 0

    label_volume, _, _ = relabel_sequential(label_volume.astype(np.int32, copy=False))
    return label_volume.astype(np.uint32)


def run_mesmer_2d_with_z_overlap_stitching(
    app,
    nuclear_tif,
    output_tif,
    membrane_tif=None,
    image_mpp=0.5,
    compartment="nuclear",
    duplicate_single_channel_to_membrane=True,
    iou_threshold=0.05,
    overlap_threshold=0.25,
    max_z_gap=1,
    one_to_one_matching=True,
    min_volume_3d=30,
    min_slices_3d=1,
):
    nuclear_tif = Path(nuclear_tif)
    output_tif = Path(output_tif)
    output_tif.parent.mkdir(parents=True, exist_ok=True)

    print("[INFO] loading nuclear volume:", nuclear_tif, flush=True)
    nuc_vol = tifffile.imread(str(nuclear_tif))
    print("[INFO] nuclear shape:", nuc_vol.shape, "dtype:", nuc_vol.dtype, flush=True)

    if nuc_vol.ndim != 3:
        raise ValueError(f"nuclear_tif must be a 3D TIF with shape=(Z,Y,X), got {nuc_vol.shape}")

    if membrane_tif is not None:
        membrane_tif = Path(membrane_tif)
        print("[INFO] loading membrane volume:", membrane_tif, flush=True)
        mem_vol = tifffile.imread(str(membrane_tif))
        print("[INFO] membrane shape:", mem_vol.shape, "dtype:", mem_vol.dtype, flush=True)

        if mem_vol.ndim != 3:
            raise ValueError(f"membrane_tif must be a 3D TIF with shape=(Z,Y,X), got {mem_vol.shape}")
        if mem_vol.shape != nuc_vol.shape:
            raise ValueError(f"shape mismatch: nuclear={nuc_vol.shape}, membrane={mem_vol.shape}")
    else:
        mem_vol = None

    Z, Y, X = nuc_vol.shape

    stitcher = ZOverlapStitcher(
        iou_threshold=iou_threshold,
        overlap_threshold=overlap_threshold,
        max_z_gap=max_z_gap,
        one_to_one_matching=one_to_one_matching,
    )

    stitched_stack = np.zeros((Z, Y, X), dtype=np.uint32)

    for z in tqdm(range(Z), desc=f"Mesmer {nuclear_tif.name}"):
        nuc2d = nuc_vol[z]

        if mem_vol is None:
            if nuc2d.max() <= nuc2d.min():
                local2d = np.zeros((Y, X), dtype=np.uint32)
            else:
                x = make_mesmer_input_single_channel(
                    nuc2d,
                    duplicate_to_membrane=duplicate_single_channel_to_membrane,
                )
                local2d = predict_one_slice_mesmer(
                    app=app,
                    x=x,
                    image_mpp=image_mpp,
                    compartment=compartment,
                )
        else:
            mem2d = mem_vol[z]
            if nuc2d.max() <= nuc2d.min() and mem2d.max() <= mem2d.min():
                local2d = np.zeros((Y, X), dtype=np.uint32)
            else:
                x = make_mesmer_input_two_channel(nuc2d, mem2d)
                local2d = predict_one_slice_mesmer(
                    app=app,
                    x=x,
                    image_mpp=image_mpp,
                    compartment=compartment,
                )

        global2d = stitcher.add_slice(local2d=local2d, z_index=z)
        stitched_stack[z] = global2d.astype(np.uint32, copy=False)
        gc.collect()

    print("[INFO] max label before 3D filtering:", int(stitched_stack.max()), flush=True)

    stitched_stack = remove_small_3d_instances(
        stitched_stack,
        min_volume=min_volume_3d,
        min_slices=min_slices_3d,
    )

    stitched_stack = stitched_stack.astype(OUTPUT_DTYPE, copy=False)

    tifffile.imwrite(str(output_tif), stitched_stack, bigtiff=True)

    print("[SAVED stitched 3D labels]", output_tif, flush=True)
    print("[INFO] output shape:", stitched_stack.shape, flush=True)
    print("[INFO] max label:", int(stitched_stack.max()), flush=True)

    del nuc_vol
    if mem_vol is not None:
        del mem_vol
    gc.collect()

    return stitched_stack


def collect_tif_files(input_folder, skip_patterns=True):
    input_folder = Path(input_folder)
    files = sorted(
        p for p in input_folder.rglob("*")
        if p.is_file() and p.suffix.lower() in [".tif", ".tiff"]
    )

    if skip_patterns:
        files = [
            p for p in files
            if "_mesmer" not in p.stem.lower()
            and "_labels" not in p.stem.lower()
            and "_mask" not in p.stem.lower()
            and "_raw2d" not in p.stem.lower()
        ]

    return files


def find_matching_membrane_tif(nuclear_path, nuclear_folder, membrane_folder):
    if membrane_folder is None:
        return None

    nuclear_path = Path(nuclear_path)
    nuclear_folder = Path(nuclear_folder)
    membrane_folder = Path(membrane_folder)

    rel = nuclear_path.relative_to(nuclear_folder)
    candidate = membrane_folder / rel

    if candidate.exists():
        return candidate

    # Try extensions with the same stem.
    for ext in [".tif", ".tiff", ".TIF", ".TIFF"]:
        candidate = membrane_folder / rel.with_suffix(ext)
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"No matching membrane file found for {nuclear_path} under {membrane_folder}")


def batch_run_mesmer_folder(
    input_folder,
    output_folder,
    membrane_folder=None,
    image_mpp=0.5,
    compartment="nuclear",
    duplicate_single_channel_to_membrane=True,
    iou_threshold=0.05,
    overlap_threshold=0.25,
    max_z_gap=1,
    one_to_one_matching=True,
    min_volume_3d=30,
    min_slices_3d=1,
    suffix="_mesmer",
    overwrite=False,
):
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)
    membrane_folder = Path(membrane_folder) if membrane_folder is not None else None

    output_folder.mkdir(parents=True, exist_ok=True)

    nuclear_files = collect_tif_files(input_folder, skip_patterns=True)

    print("=" * 80, flush=True)
    print("[INFO] input_folder:", input_folder, flush=True)
    print("[INFO] output_folder:", output_folder, flush=True)
    print("[INFO] membrane_folder:", membrane_folder, flush=True)
    print("[INFO] found tif files:", len(nuclear_files), flush=True)
    print("[INFO] image_mpp:", image_mpp, flush=True)
    print("[INFO] compartment:", compartment, flush=True)
    print("=" * 80, flush=True)

    print("[INFO] loading Mesmer model once for the whole batch...", flush=True)
    app = Mesmer()
    print("[INFO] Mesmer model loaded.", flush=True)

    failed = []

    for nuclear_path in tqdm(nuclear_files, desc="Batch Mesmer"):
        rel = nuclear_path.relative_to(input_folder)
        out_rel = rel.with_name(rel.stem + suffix + ".tif")
        output_tif = output_folder / out_rel

        if output_tif.exists() and not overwrite:
            print(f"[SKIP] output exists: {output_tif}", flush=True)
            continue

        print("\n" + "=" * 80, flush=True)
        print("[PROCESS]", nuclear_path, flush=True)
        print("[OUTPUT] ", output_tif, flush=True)
        print("=" * 80, flush=True)

        try:
            membrane_tif = find_matching_membrane_tif(
                nuclear_path=nuclear_path,
                nuclear_folder=input_folder,
                membrane_folder=membrane_folder,
            )

            run_mesmer_2d_with_z_overlap_stitching(
                app=app,
                nuclear_tif=nuclear_path,
                membrane_tif=membrane_tif,
                output_tif=output_tif,
                image_mpp=image_mpp,
                compartment=compartment,
                duplicate_single_channel_to_membrane=duplicate_single_channel_to_membrane,
                iou_threshold=iou_threshold,
                overlap_threshold=overlap_threshold,
                max_z_gap=max_z_gap,
                one_to_one_matching=one_to_one_matching,
                min_volume_3d=min_volume_3d,
                min_slices_3d=min_slices_3d,
            )

        except Exception as e:
            print(f"[FAILED] {nuclear_path}", flush=True)
            print(f"[ERROR] {type(e).__name__}: {e}", flush=True)
            failed.append((str(nuclear_path), type(e).__name__, str(e)))
            continue

    if len(failed) > 0:
        failed_csv = output_folder / "failed_mesmer_files.csv"
        pd.DataFrame(
            failed,
            columns=["input_tif", "error_type", "error_message"],
        ).to_csv(failed_csv, index=False)
        print("[INFO] failed list saved to:", failed_csv, flush=True)

    print("=" * 80, flush=True)
    print("[DONE] Batch Mesmer finished.", flush=True)
    print("[INFO] failed files:", len(failed), flush=True)
    print("=" * 80, flush=True)


def str2bool(v):
    if isinstance(v, bool):
        return v
    v = str(v).lower()
    if v in ["yes", "true", "t", "1", "y"]:
        return True
    if v in ["no", "false", "f", "0", "n"]:
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")


def main():
    parser = argparse.ArgumentParser(
        description="Batch Mesmer slice-wise 2D segmentation plus z-overlap stitching for 3D TIF volumes."
    )

    parser.add_argument(
        "input_folder",
        type=str,
        help="Folder containing nuclear 3D tif/tiff files. Searched recursively.",
    )

    parser.add_argument(
        "output_folder",
        type=str,
        help="Folder to save final Mesmer 3D label tif files.",
    )

    parser.add_argument(
        "--membrane_folder",
        type=str,
        default=None,
        help="Optional folder containing matching membrane 3D tif files with the same relative paths.",
    )

    parser.add_argument(
        "--cuda_visible_devices",
        type=str,
        default=None,
        help="Set CUDA_VISIBLE_DEVICES before TensorFlow import, e.g. 0 or 1.",
    )

    parser.add_argument(
        "--image_mpp",
        type=float,
        default=0.5,
        help="Image resolution in microns per pixel for Mesmer. Default: 0.5.",
    )

    parser.add_argument(
        "--compartment",
        type=str,
        default="nuclear",
        choices=["nuclear", "whole-cell"],
        help="Mesmer compartment. Default: nuclear.",
    )

    parser.add_argument(
        "--duplicate_single_channel_to_membrane",
        type=str2bool,
        default=True,
        help="For single-channel input, duplicate nuclear channel as membrane channel. Default: True.",
    )

    parser.add_argument("--iou_threshold", type=float, default=0.05)
    parser.add_argument("--overlap_threshold", type=float, default=0.25)
    parser.add_argument("--max_z_gap", type=int, default=1)

    parser.add_argument(
        "--allow_many_to_one",
        action="store_true",
        help="Allow multiple current-slice objects to match the same previous global object.",
    )

    parser.add_argument("--min_volume_3d", type=int, default=30)
    parser.add_argument("--min_slices_3d", type=int, default=1)
    parser.add_argument("--suffix", type=str, default="_mesmer")
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    setup_tensorflow_memory_growth()

    batch_run_mesmer_folder(
        input_folder=args.input_folder,
        output_folder=args.output_folder,
        membrane_folder=args.membrane_folder,
        image_mpp=args.image_mpp,
        compartment=args.compartment,
        duplicate_single_channel_to_membrane=args.duplicate_single_channel_to_membrane,
        iou_threshold=args.iou_threshold,
        overlap_threshold=args.overlap_threshold,
        max_z_gap=args.max_z_gap,
        one_to_one_matching=not args.allow_many_to_one,
        min_volume_3d=args.min_volume_3d,
        min_slices_3d=args.min_slices_3d,
        suffix=args.suffix,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
