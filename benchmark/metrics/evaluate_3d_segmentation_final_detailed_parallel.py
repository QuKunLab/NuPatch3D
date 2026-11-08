#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Final rule-based 3D instance segmentation benchmark evaluator.

Optimized implementation:
    - exact same metric/classification definitions
    - prediction files indexed once
    - vectorized overlap/matching reductions
    - surface maps precomputed once per label image
    - GT surface/KD-tree data reused across methods
    - process-level parallelism across GT images

============================================================
Definitions
============================================================

Let:

    G_i = ground-truth instance i
    P_j = prediction instance j

    O_ij = |G_i ∩ P_j|

    GR_ij = |G_i ∩ P_j| / |G_i|
    PR_ij = |G_i ∩ P_j| / |P_j|


============================================================
1. One-to-one match
============================================================

G_i <-> P_j if:

    GR_ij > match_threshold

AND

    PR_ij > match_threshold

AND

    sum_{k != j} GR_ik < tolerance

AND

    sum_{k != i} PR_kj < tolerance


============================================================
2. One-to-multiple: over-segmentation
============================================================

For G_i:

    consider ALL predictions satisfying:

        |G_i ∩ P_j| > 0

If there are more than one prediction:

    I_j = |G_i ∩ P_j| / |G_i|

Sort:

    I_1 >= I_2 >= ... >= I_k

If:

    sum_{j > 1} I_j > tolerance

then G_i is counted as one over-segmented GT.


============================================================
3. Multiple-to-one: under-segmentation
============================================================

For prediction P_j:

    find all GT instances satisfying:

        |G_i ∩ P_j| / |G_i| > underseg_threshold

If more than one GT satisfies this condition:

    P_j is an under-segmenting prediction

and ALL corresponding GT instances are counted as US.

Therefore:

    USR = US_GT_Count / GT_Instance_Count

NOTE:
    underseg_threshold is independent from match_threshold.


============================================================
4. False negative
============================================================

G_i is FN if:

    for ALL predictions P_j:

        |G_i ∩ P_j| / |G_i| < match_threshold


============================================================
5. False positive
============================================================

P_j is FP if:

    for ALL GT instances G_i:

        |G_i ∩ P_j| / |G_i| < match_threshold

IMPORTANT:
    FP is calculated directly from this mathematical definition.

    OS extra fragments are NOT automatically forced to become FP.
    Whether an OS fragment is FP depends on whether it satisfies
    the FP definition above.


============================================================
6. Rates
============================================================

    OSR = OS_GT_Count / GT_Instance_Count

    USR = US_GT_Count / GT_Instance_Count

    FNR = FN_GT_Count / GT_Instance_Count

    FPR = FP_Pred_Count / Pred_Instance_Count


============================================================
7. AP definitions
============================================================

AP_RuleBased:

    TP = number of one-to-one matches defined above
    FP = rule-based FP
    FN = rule-based FN

    AP_RuleBased = TP / (TP + FP + FN)


AP_IoU50:

    Build GT-Pred IoU matrix.

    Find one-to-one instance matching at:

        IoU >= 0.5

    The assignment maximizes the number of valid IoU>=0.5
    matches first, and IoU second.

    Then:

        AP_IoU50 =
            IoU50_TP /
            (IoU50_TP + IoU50_FP + IoU50_FN)


============================================================
8. Other metrics
============================================================

    FDR
    IoU
    HD
    NSD
    ARI

IoU / HD / NSD are calculated on rule-based one-to-one pairs.


============================================================
9. Physical resolution
============================================================

    Z = 1.0 um
    Y = 0.137 um
    X = 0.137 um

Voxel volume:

    1.0 * 0.137 * 0.137
    = 0.018769 um^3


============================================================
Important boundary behavior
============================================================

The mathematical inequalities are implemented strictly:

    one-to-one:
        > threshold
        < tolerance

    OS:
        secondary sum > tolerance

    US:
        > underseg_threshold

    FN / FP:
        < match_threshold

Therefore a value exactly equal to the threshold is not included
in either > threshold or < threshold categories.

For AP_IoU50 only:

    IoU >= 0.5

is used, following the conventional IoU threshold interpretation.
"""

import argparse
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile

from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment


# ============================================================
# Methods
# ============================================================

METHODS = {
    "Cellpose-SAM": "cellpose-SAM",
    "StarDist-3D": "stardist",
    "PlantSeg": "plantseg",
    "Cellpose": "cellpose",
    "u-Segment3D": "u-sagment3D",
    "CellSAM": "cellSAM",
    "Omnipose": "omnipose",
    "MedSAM": "medsam",
    "Swin-UNETR": "SwinUNetR",
    "uSAM": "micro-sam",
    "3D U-Net": "3dunet",
    "Ilastik": "ilastik",
    "CellProfiler": "CellProfiler",
    "Med-SA": "med-sa",
    "Mesmer": "mesmer",
    "Cellpose-2D": "cellpose-2D",
    "CellSeg3D": "cellseg3d",
}


# ============================================================
# Physical resolution
# ============================================================

# z, y, x
SPACING = (
    1.0,
    0.137,
    0.137
)

VOXEL_VOLUME_UM3 = float(
    np.prod(SPACING)
)

# Fixed AP IoU threshold requested by user
AP_IOU_THRESHOLD = 0.5


# ============================================================
# Basic utilities
# ============================================================

def norm(x):
    """
    Normalize names for file matching.
    """

    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(x).lower()
    )


def iter_tiff_files(root):
    """
    Recursively list both .tif and .tiff files.
    Extension matching is case-insensitive.
    """
    return sorted(
        p
        for p in Path(root).rglob("*")
        if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}
    )


def list_gt(root):
    """
    Treat *_labels.tif and *_labels.tiff as GT.
    """
    return sorted(
        p
        for p in iter_tiff_files(root)
        if p.stem.lower().endswith("_labels")
    )


def find_prediction(root, image, method, alias):
    """
    Find one prediction file using exact method matching.

    Flat shared-directory format:
        <image>_<method>.tif
        <image>_<method>.tiff
        <image>_<alias>.tif
        <image>_<alias>.tiff

    Exact normalized stem matching prevents:
        Cellpose -> Cellpose-SAM
        Cellpose -> Cellpose-2D

    The older method-folder/image.tif(f) layout is also supported.
    Multiple exact candidates raise an error.
    """

    image_n = norm(image)
    method_n = norm(method)
    alias_n = norm(alias)

    expected_flat_stems = {
        norm(f"{image}_{method}"),
        norm(f"{image}_{alias}"),
    }

    candidates = []

    for p in iter_tiff_files(root):
        stem_n = norm(p.stem)

        # Shared root/tree: exact whole-stem match only.
        if stem_n in expected_flat_stems:
            candidates.append(p)
            continue

        # Backward compatibility: method_folder/image.tif(f)
        if stem_n == image_n:
            parent_parts_n = [norm(x) for x in p.parent.parts]
            if method_n in parent_parts_n or alias_n in parent_parts_n:
                candidates.append(p)

    candidates = sorted(set(candidates))

    if len(candidates) == 0:
        return None

    if len(candidates) > 1:
        candidate_text = "\n".join(
            f"    - {p}"
            for p in candidates
        )

        raise RuntimeError(
            "\nMultiple prediction files matched exactly.\n"
            f"Image  : {image}\n"
            f"Method : {method}\n"
            f"Alias  : {alias}\n"
            "Candidates:\n"
            f"{candidate_text}\n"
            "Please keep only one prediction file for this "
            "image-method combination."
        )

    return candidates[0]


def build_prediction_index(root):
    """
    Scan the prediction tree exactly once.

    The original implementation recursively scanned every prediction file
    for every image-method pair.  For >500 images x >10 methods that becomes
    a very large amount of filesystem work.  This index preserves the exact
    filename matching rules while making lookup O(1) for the shared-root
    layout.
    """
    by_stem = {}

    for p in iter_tiff_files(root):
        stem_n = norm(p.stem)
        parent_parts_n = frozenset(norm(x) for x in p.parent.parts)
        by_stem.setdefault(stem_n, []).append((p, parent_parts_n))

    for entries in by_stem.values():
        entries.sort(key=lambda x: str(x[0]))

    return by_stem


def find_prediction_indexed(index, image, method, alias):
    """Exact equivalent of find_prediction(), using a prebuilt index."""
    image_n = norm(image)
    method_n = norm(method)
    alias_n = norm(alias)

    expected_flat_stems = {
        norm(f'{image}_{method}'),
        norm(f'{image}_{alias}'),
    }

    candidates = set()

    # Shared directory / tree: exact whole-stem matching.
    for stem_n in expected_flat_stems:
        for p, _ in index.get(stem_n, []):
            candidates.add(p)

    # Backward-compatible method_folder/image.tif(f) layout.
    for p, parent_parts_n in index.get(image_n, []):
        if method_n in parent_parts_n or alias_n in parent_parts_n:
            candidates.add(p)

    candidates = sorted(candidates)

    if len(candidates) == 0:
        return None

    if len(candidates) > 1:
        candidate_text = '\n'.join(f'    - {p}' for p in candidates)
        raise RuntimeError(
            '\nMultiple prediction files matched exactly.\n'
            f'Image  : {image}\n'
            f'Method : {method}\n'
            f'Alias  : {alias}\n'
            'Candidates:\n'
            f'{candidate_text}\n'
            'Please keep only one prediction file for this image-method combination.'
        )

    return candidates[0]


def read_label(path):
    """
    Read a label image and relabel all positive labels to 1..N.

    This is mathematically identical to the original implementation,
    but avoids one full-volume comparison per instance label.
    np.unique returns positive labels in ascending order, exactly matching
    the original relabeling order.
    """
    x = np.squeeze(tifffile.imread(path))
    out = np.zeros(x.shape, dtype=np.int32)

    positive = x > 0
    if not np.any(positive):
        return out

    _, inverse = np.unique(x[positive], return_inverse=True)
    out[positive] = inverse.astype(np.int32, copy=False) + 1
    return out


# ============================================================
# Instance information
# ============================================================

def areas(x):
    """
    Voxel count for each instance.

    Returned index is zero-based:

        output[i] = volume of label i+1
    """

    return np.bincount(
        x.ravel(),
        minlength=int(x.max()) + 1
    )[1:]


def overlap_matrix(gt, pred):
    """
    GT x Prediction overlap matrix.

    Same counts as the original np.add.at implementation, but uses one
    encoded bincount, which is substantially faster for large 3D arrays.
    """
    n_gt = int(gt.max())
    n_pred = int(pred.max())

    if n_gt == 0 or n_pred == 0:
        return np.zeros((n_gt, n_pred), dtype=np.int64)

    gt_flat = gt.ravel()
    pred_flat = pred.ravel()
    mask = (gt_flat > 0) & (pred_flat > 0)

    if not np.any(mask):
        return np.zeros((n_gt, n_pred), dtype=np.int64)

    gi = gt_flat[mask].astype(np.int64, copy=False) - 1
    pj = pred_flat[mask].astype(np.int64, copy=False) - 1
    encoded = gi * np.int64(n_pred) + pj

    counts = np.bincount(
        encoded,
        minlength=n_gt * n_pred
    )
    return counts.reshape(n_gt, n_pred).astype(np.int64, copy=False)


def overlap_ratios(
    ov,
    ga,
    pa
):
    """
    Calculate:

        GR[i,j]
            = overlap / GT volume

        PR[i,j]
            = overlap / Prediction volume
    """

    n_gt = len(
        ga
    )

    n_pred = len(
        pa
    )

    if (
        n_gt == 0
        or
        n_pred == 0
    ):

        gr = np.zeros(
            (
                n_gt,
                n_pred
            ),
            dtype=float
        )

        pr = np.zeros(
            (
                n_gt,
                n_pred
            ),
            dtype=float
        )

        return (
            gr,
            pr
        )

    # --------------------------------------------------------
    # overlap / GT
    # --------------------------------------------------------

    gr = (
        ov
        /
        np.maximum(
            ga[:, None],
            1
        )
    )

    # --------------------------------------------------------
    # overlap / Prediction
    # --------------------------------------------------------

    pr = (
        ov
        /
        np.maximum(
            pa[None, :],
            1
        )
    )

    return (
        gr,
        pr
    )


def sum_area(
    area_array,
    ids
):
    """
    Sum instance volumes for a set/list of zero-based IDs.
    """

    ids = list(
        ids
    )

    if len(ids) == 0:
        return 0

    ids = np.asarray(
        ids,
        dtype=int
    )

    return int(
        np.sum(
            area_array[ids]
        )
    )


def voxels_to_um3(
    n_voxels
):
    """
    Convert voxel count to physical volume.
    """

    return (
        float(n_voxels)
        *
        VOXEL_VOLUME_UM3
    )


def ids_to_string(
    ids
):
    """
    Convert zero-based internal instance IDs into a readable
    one-based string.

    Example:

        {0, 2, 5}

    becomes:

        "1;3;6"

    NOTE:
        These are relabeled IDs produced by read_label(),
        not necessarily the original TIFF label values.
    """

    ids = sorted(
        set(ids)
    )

    return ";".join(
        str(i + 1)
        for i in ids
    )


# ============================================================
# Rule-based instance classification
# ============================================================

def match_instances(
    gt,
    pred,
    match_threshold=0.5,
    tolerance=0.1,
    underseg_threshold=0.5,
    gt_areas=None,
    pred_areas=None,
):
    """
    Perform the exact same rule-based classifications as the detailed
    evaluator, with vectorized/precomputed reductions for speed.

    No metric definition is changed.
    """
    ov = overlap_matrix(gt, pred)
    ga = areas(gt) if gt_areas is None else gt_areas
    pa = areas(pred) if pred_areas is None else pred_areas
    gr, pr = overlap_ratios(ov, ga, pa)

    n_gt = len(ga)
    n_pred = len(pa)

    # ========================================================
    # 1. ONE-TO-ONE
    # Exact conditions:
    #   GR_ij > threshold
    #   PR_ij > threshold
    #   sum_{k!=j} GR_ik < tolerance
    #   sum_{k!=i} PR_kj < tolerance
    # ========================================================
    if n_gt > 0 and n_pred > 0:
        # The original code recomputed these sums for every (i,j).
        # Precomputing them does not alter their values or definitions.
        gr_row_sum = np.sum(gr, axis=1)
        pr_col_sum = np.sum(pr, axis=0)

        one_mask = (
            (gr > match_threshold)
            & (pr > match_threshold)
            & ((gr_row_sum[:, None] - gr) < tolerance)
            & ((pr_col_sum[None, :] - pr) < tolerance)
        )

        one = [
            (int(i), int(j))
            for i, j in np.argwhere(one_mask)
        ]
    else:
        one = []

    # ========================================================
    # 2. OVER-SEGMENTATION
    # Keep the original definition exactly: every overlap > 0 is a
    # candidate; sort GR values; sum all except the largest.
    # ========================================================
    over_gt_ids = set()
    over_gt_to_pred = {}

    for i in range(n_gt):
        pred_ids = np.flatnonzero(ov[i, :] > 0).tolist()
        if len(pred_ids) <= 1:
            continue

        sorted_values = sorted(
            (float(gr[i, j]) for j in pred_ids),
            reverse=True,
        )
        secondary_sum = float(np.sum(sorted_values[1:]))

        if secondary_sum > tolerance:
            over_gt_ids.add(i)
            over_gt_to_pred[i] = pred_ids

    # ========================================================
    # 3. UNDER-SEGMENTATION
    # Exact definition: GR > independent underseg threshold.
    # ========================================================
    under_pred_to_gt = {}
    under_gt_ids = set()

    for j in range(n_pred):
        gt_ids = np.flatnonzero(
            gr[:, j] > underseg_threshold
        ).tolist()

        if len(gt_ids) > 1:
            under_pred_to_gt[j] = gt_ids
            under_gt_ids.update(gt_ids)

    under_pred_ids = set(under_pred_to_gt.keys())

    # ========================================================
    # 4. FALSE NEGATIVE
    # Exact definition: all GR_i,* < match_threshold.
    # np.all on an empty prediction axis is True, matching the explicit
    # empty-prediction branch in the original code.
    # ========================================================
    fn_gt_ids = set(
        int(i)
        for i in np.flatnonzero(
            np.all(gr < match_threshold, axis=1)
        )
    )

    # ========================================================
    # 5. FALSE POSITIVE
    # Exact definition: all GR_*,j < match_threshold.
    # np.all on an empty GT axis is True, matching the original code.
    # ========================================================
    fp_pred_ids = set(
        int(j)
        for j in np.flatnonzero(
            np.all(gr < match_threshold, axis=0)
        )
    )

    return {
        'ov': ov,
        'ga': ga,
        'pa': pa,
        'gr': gr,
        'pr': pr,
        'one': one,
        'over_gt_ids': over_gt_ids,
        'over_gt_to_pred': over_gt_to_pred,
        'under_pred_ids': under_pred_ids,
        'under_pred_to_gt': under_pred_to_gt,
        'under_gt_ids': under_gt_ids,
        'fn_gt_ids': fn_gt_ids,
        'fp_pred_ids': fp_pred_ids,
    }


# ============================================================
# FDR
# ============================================================

def fdr_from_overlap(ov, ga):
    """
    Same FDR as the original implementation:
        foreground intersection / GT foreground volume.
    """
    gt_total = int(np.sum(ga))
    if gt_total == 0:
        return np.nan
    return float(np.sum(ov) / gt_total)


# ============================================================
# Rule-based pair IoU
# ============================================================

def iou_metric_from_overlap(ov, ga, pa, pairs):
    """
    Mean IoU for rule-based one-to-one pairs.

    Uses the already computed overlap matrix and instance areas instead of
    rescanning the complete 3D volume for every matched pair.
    """
    if len(pairs) == 0:
        return np.nan

    values = []
    for i, j in pairs:
        inter = int(ov[i, j])
        union = int(ga[i]) + int(pa[j]) - inter
        if union > 0:
            values.append(inter / union)

    return float(np.mean(values)) if values else np.nan


# ============================================================
# Surface
# ============================================================

def build_surface_point_groups(labels):
    """
    Precompute physical surface coordinates for every instance in one pass.

    This is exactly equivalent to repeatedly evaluating:
        mask & (~ndi.binary_erosion(mask))
    with scipy's default connectivity-1 structure, but avoids one erosion
    and one full-volume scan per matched instance.

    Returns a list where groups[i] contains the physical (z,y,x) surface
    coordinates for label i+1.
    """
    n_labels = int(labels.max())
    if n_labels == 0:
        return []

    structure = ndi.generate_binary_structure(labels.ndim, 1)

    # A label voxel is interior iff every voxel selected by the same
    # connectivity-1 footprint has exactly the same label.  Both min and
    # max are needed because neighboring labels can be numerically smaller
    # or larger.
    local_min = ndi.minimum_filter(
        labels,
        footprint=structure,
        mode='constant',
        cval=0,
    )
    local_max = ndi.maximum_filter(
        labels,
        footprint=structure,
        mode='constant',
        cval=0,
    )

    foreground = labels > 0
    interior = foreground & (local_min == labels) & (local_max == labels)
    surface_mask = foreground & (~interior)

    if not np.any(surface_mask):
        return [np.empty((0, labels.ndim), dtype=np.float64) for _ in range(n_labels)]

    ids = labels[surface_mask].astype(np.int64, copy=False) - 1
    coords = np.argwhere(surface_mask).astype(np.float64, copy=False)

    spacing = np.asarray(SPACING, dtype=np.float64)
    if labels.ndim != len(spacing):
        raise ValueError(
            f'SPACING has {len(spacing)} dimensions but label image has '
            f'{labels.ndim} dimensions.'
        )
    coords *= spacing

    # Stable sort preserves the same row-major coordinate order within each
    # label as np.argwhere(surface(labels == id)) in the original code.
    order = np.argsort(ids, kind='stable')
    ids_sorted = ids[order]
    coords_sorted = coords[order]

    bounds = np.searchsorted(
        ids_sorted,
        np.arange(n_labels + 1),
        side='left',
    )

    return [
        coords_sorted[bounds[i]:bounds[i + 1]]
        for i in range(n_labels)
    ]


# ============================================================
# HD + NSD
# ============================================================

def hd_nsd_from_surface_groups(
    gt_surface_groups,
    pred_surface_groups,
    pairs,
    tol=1.0,
    gt_tree_cache=None,
):
    """
    Same HD and NSD definitions as the original implementation.

    Surface coordinates are precomputed once per label image.  GT KD-trees
    may be cached and reused across all methods for the same GT image.
    """
    hd_values = []
    nsd_values = []

    if gt_tree_cache is None:
        gt_tree_cache = {}

    for i, j in pairs:
        a = gt_surface_groups[i]
        b = pred_surface_groups[j]

        if len(a) == 0 or len(b) == 0:
            continue

        tree_a = gt_tree_cache.get(i)
        if tree_a is None:
            tree_a = cKDTree(a)
            gt_tree_cache[i] = tree_a

        tree_b = cKDTree(b)

        # Keep one thread per process to avoid nested oversubscription when
        # the outer image loop is parallelized with multiple processes.
        da = tree_b.query(a, workers=1)[0]
        db = tree_a.query(b, workers=1)[0]

        hd_values.append(
            max(float(da.max()), float(db.max()))
        )

        nsd_values.append(
            float(
                (np.sum(da <= tol) + np.sum(db <= tol))
                / (len(da) + len(db))
            )
        )

    hd_value = float(np.mean(hd_values)) if hd_values else np.nan
    nsd_value = float(np.mean(nsd_values)) if nsd_values else np.nan
    return hd_value, nsd_value


# ============================================================
# ARI
# ============================================================

def ari_from_overlap(ov):
    """
    Same ARI as the original evaluator.

    The original pandas.crosstab on voxels where GT>0 and Pred>0 is exactly
    the already-computed overlap contingency matrix, so no voxel rescan or
    DataFrame construction is necessary.
    """
    table = ov.astype(np.float64, copy=False)
    n = float(np.sum(table))
    if n < 2:
        return np.nan

    def c2(x):
        return np.sum(x * (x - 1) / 2)

    a = c2(table)
    b = c2(np.sum(table, axis=1))
    c = c2(np.sum(table, axis=0))
    total_pairs = n * (n - 1) / 2
    expected = b * c / total_pairs
    denominator = 0.5 * (b + c) - expected

    return float((a - expected) / (denominator + 1e-12))


# ============================================================
# Rule-based AP
# ============================================================

def rule_based_ap_details(
    one,
    fp_pred_ids,
    fn_gt_ids
):
    """
    AP calculated directly from the user's rule-based
    TP / FP / FN definitions.

    TP:
        number of one-to-one matches

    FP:
        number of rule-based FP predictions

    FN:
        number of rule-based FN GTs

    AP:
        TP / (TP + FP + FN)
    """

    tp = int(
        len(
            one
        )
    )

    fp = int(
        len(
            fp_pred_ids
        )
    )

    fn = int(
        len(
            fn_gt_ids
        )
    )

    denominator = (
        tp
        +
        fp
        +
        fn
    )

    if denominator == 0:

        ap_value = np.nan

    else:

        ap_value = (
            tp
            /
            denominator
        )

    return (
        float(ap_value)
        if not np.isnan(ap_value)
        else np.nan,
        tp,
        fp,
        fn
    )


# ============================================================
# IoU-based AP
# ============================================================

def iou_ap_details(
    ov,
    ga,
    pa,
    threshold=0.5
):
    """
    AP based purely on instance IoU threshold.

    A GT-Pred pair is valid if:

        IoU >= threshold

    One-to-one assignment is performed such that:

        1. number of valid matches is maximized first
        2. IoU is maximized second

    This is preferable to simply applying Hungarian assignment
    to -IoU, because maximizing total IoU alone can sometimes
    produce fewer threshold-valid TP pairs.

    Returns:

        AP
        TP
        FP
        FN
        mean IoU of matched TP pairs
    """

    n_gt = len(
        ga
    )

    n_pred = len(
        pa
    )

    # ========================================================
    # Empty cases
    # ========================================================

    if (
        n_gt == 0
        and
        n_pred == 0
    ):

        return (
            np.nan,
            0,
            0,
            0,
            np.nan
        )

    if n_gt == 0:

        return (
            0.0,
            0,
            n_pred,
            0,
            np.nan
        )

    if n_pred == 0:

        return (
            0.0,
            0,
            0,
            n_gt,
            np.nan
        )

    # ========================================================
    # IoU matrix
    # ========================================================

    union = (
        ga[:, None]
        +
        pa[None, :]
        -
        ov
    )

    iou = (
        ov
        /
        (
            union
            +
            1e-12
        )
    )

    # ========================================================
    # Valid IoU matches
    # ========================================================

    valid = (
        iou
        >=
        threshold
    )

    # ========================================================
    # Hungarian assignment
    #
    # We want:
    #
    # 1. maximize number of valid pairs
    # 2. among equal-cardinality solutions, maximize IoU
    #
    # Each valid pair contributes ~1.
    #
    # The IoU bonus across ALL selected pairs is guaranteed to
    # be < 0.5, so gaining one valid pair is always more
    # important than any possible IoU bonus difference.
    # ========================================================

    n_possible_matches = min(
        n_gt,
        n_pred
    )

    bonus_scale = (
        2.0
        *
        max(
            n_possible_matches,
            1
        )
    )

    score = (
        valid.astype(float)
        +
        iou
        /
        bonus_scale
    )

    row_ind, col_ind = (
        linear_sum_assignment(
            -score
        )
    )

    # ========================================================
    # Count TP
    # ========================================================

    matched_valid = valid[
        row_ind,
        col_ind
    ]

    tp = int(
        np.sum(
            matched_valid
        )
    )

    fp = int(
        n_pred
        -
        tp
    )

    fn = int(
        n_gt
        -
        tp
    )

    denominator = (
        tp
        +
        fp
        +
        fn
    )

    if denominator == 0:

        ap_value = np.nan

    else:

        ap_value = (
            tp
            /
            denominator
        )

    # ========================================================
    # Mean IoU among TP pairs
    # ========================================================

    if tp > 0:

        matched_iou = iou[
            row_ind[
                matched_valid
            ],
            col_ind[
                matched_valid
            ]
        ]

        mean_matched_iou = float(
            np.mean(
                matched_iou
            )
        )

    else:

        mean_matched_iou = np.nan

    return (
        float(ap_value)
        if not np.isnan(ap_value)
        else np.nan,
        tp,
        fp,
        fn,
        mean_matched_iou
    )


# ============================================================
# Voxel-level confusion matrix
# ============================================================

def voxel_confusion(
    gt,
    pred
):
    """
    Foreground/background voxel confusion.

    Positive:
        instance label > 0

    Negative:
        background = 0
    """

    gt_fg = (
        gt > 0
    )

    pred_fg = (
        pred > 0
    )

    tp = int(
        np.sum(
            gt_fg
            &
            pred_fg
        )
    )

    tn = int(
        np.sum(
            (~gt_fg)
            &
            (~pred_fg)
        )
    )

    fp = int(
        np.sum(
            (~gt_fg)
            &
            pred_fg
        )
    )

    fn = int(
        np.sum(
            gt_fg
            &
            (~pred_fg)
        )
    )

    return (
        tp,
        tn,
        fp,
        fn
    )


# ============================================================
# Safe ratio
# ============================================================

def safe_rate(
    numerator,
    denominator
):
    """
    Return NaN when denominator == 0.
    """

    if denominator == 0:
        return np.nan

    return (
        float(numerator)
        /
        float(denominator)
    )


# ============================================================
# Intermediate statistics
# ============================================================

def collect_intermediate_statistics(
    gt,
    pred,
    result
):
    """
    Collect instance counts, voxel counts and physical volumes
    for all rule-based categories.
    """

    ov = result[
        "ov"
    ]

    ga = result[
        "ga"
    ]

    pa = result[
        "pa"
    ]

    gr = result[
        "gr"
    ]

    one = result[
        "one"
    ]

    over_gt_ids = result[
        "over_gt_ids"
    ]

    over_gt_to_pred = result[
        "over_gt_to_pred"
    ]

    under_pred_ids = result[
        "under_pred_ids"
    ]

    under_pred_to_gt = result[
        "under_pred_to_gt"
    ]

    under_gt_ids = result[
        "under_gt_ids"
    ]

    fn_gt_ids = result[
        "fn_gt_ids"
    ]

    fp_pred_ids = result[
        "fp_pred_ids"
    ]

    n_gt = len(
        ga
    )

    n_pred = len(
        pa
    )

    # ========================================================
    # Image / foreground
    # ========================================================

    total_voxels = int(
        gt.size
    )

    gt_total_voxels = int(
        np.sum(
            ga
        )
    )

    pred_total_voxels = int(
        np.sum(
            pa
        )
    )

    # ========================================================
    # One-to-one pair information
    # ========================================================

    pair_gt_ids = {
        i
        for i, _ in one
    }

    pair_pred_ids = {
        j
        for _, j in one
    }

    pair_gt_voxels = sum_area(
        ga,
        pair_gt_ids
    )

    pair_pred_voxels = sum_area(
        pa,
        pair_pred_ids
    )

    pair_intersection_voxels = int(
        sum(
            int(
                ov[i, j]
            )
            for i, j in one
        )
    )

    pair_union_voxels = int(
        sum(
            int(
                ga[i]
                +
                pa[j]
                -
                ov[i, j]
            )
            for i, j in one
        )
    )

    # ========================================================
    # Over-segmentation details
    # ========================================================

    os_pred_ids = set()

    os_main_pred_ids = set()

    os_extra_pred_ids = set()

    os_extra_relation_count = 0

    for i, pred_ids in over_gt_to_pred.items():

        os_pred_ids.update(
            pred_ids
        )

        # ----------------------------------------------------
        # Main fragment = prediction with largest GR
        # ----------------------------------------------------

        main_pred = max(
            pred_ids,
            key=lambda j:
            gr[i, j]
        )

        os_main_pred_ids.add(
            main_pred
        )

        for j in pred_ids:

            if j != main_pred:

                os_extra_pred_ids.add(
                    j
                )

                os_extra_relation_count += 1

    os_gt_voxels = sum_area(
        ga,
        over_gt_ids
    )

    os_pred_voxels = sum_area(
        pa,
        os_pred_ids
    )

    os_main_pred_voxels = sum_area(
        pa,
        os_main_pred_ids
    )

    os_extra_pred_voxels = sum_area(
        pa,
        os_extra_pred_ids
    )

    os_overlap_voxels = int(
        sum(
            int(
                ov[i, j]
            )
            for i, pred_ids
            in over_gt_to_pred.items()
            for j in pred_ids
        )
    )

    # ========================================================
    # Under-segmentation details
    # ========================================================

    us_gt_relation_count = int(
        sum(
            len(gt_ids)
            for gt_ids
            in under_pred_to_gt.values()
        )
    )

    us_extra_gt_relation_count = int(
        sum(
            max(
                len(gt_ids) - 1,
                0
            )
            for gt_ids
            in under_pred_to_gt.values()
        )
    )

    us_gt_voxels = sum_area(
        ga,
        under_gt_ids
    )

    us_pred_voxels = sum_area(
        pa,
        under_pred_ids
    )

    us_overlap_voxels = int(
        sum(
            int(
                ov[i, j]
            )
            for j, gt_ids
            in under_pred_to_gt.items()
            for i in gt_ids
        )
    )

    # ========================================================
    # FN / FP
    # ========================================================

    fn_gt_voxels = sum_area(
        ga,
        fn_gt_ids
    )

    fp_pred_voxels = sum_area(
        pa,
        fp_pred_ids
    )

    # ========================================================
    # Voxel TP / TN / FP / FN
    # ========================================================
    # Derived exactly from the overlap matrix and foreground volumes.
    # This avoids another full-volume scan.

    voxel_tp = int(np.sum(ov))
    voxel_fn = int(gt_total_voxels - voxel_tp)
    voxel_fp = int(pred_total_voxels - voxel_tp)
    voxel_tn = int(total_voxels - voxel_tp - voxel_fn - voxel_fp)

    # ========================================================
    # Mean instance volumes
    # ========================================================

    if n_gt > 0:

        gt_mean_voxels = float(
            np.mean(
                ga
            )
        )

    else:

        gt_mean_voxels = np.nan

    if n_pred > 0:

        pred_mean_voxels = float(
            np.mean(
                pa
            )
        )

    else:

        pred_mean_voxels = np.nan

    # ========================================================
    # Build output
    # ========================================================

    stats = {

        # ====================================================
        # Image
        # ====================================================

        "Image_Voxel_Count":
            total_voxels,

        "Voxel_Volume_um3":
            VOXEL_VOLUME_UM3,

        "Image_Physical_Volume_um3":
            voxels_to_um3(
                total_voxels
            ),

        # ====================================================
        # Total instance counts
        # ====================================================

        "GT_Instance_Count":
            n_gt,

        "Pred_Instance_Count":
            n_pred,

        # ====================================================
        # Pair / TP
        # ====================================================

        "Pair_Count":
            len(one),

        "OneToOne_TP_Count":
            len(one),

        "Pair_GT_Relabeled_IDs":
            ids_to_string(
                pair_gt_ids
            ),

        "Pair_Pred_Relabeled_IDs":
            ids_to_string(
                pair_pred_ids
            ),

        # ====================================================
        # OS counts
        # ====================================================

        "OS_GT_Count":
            len(
                over_gt_ids
            ),

        "OS_GT_Relabeled_IDs":
            ids_to_string(
                over_gt_ids
            ),

        "OS_Pred_Fragment_Count":
            len(
                os_pred_ids
            ),

        "OS_Pred_Relabeled_IDs":
            ids_to_string(
                os_pred_ids
            ),

        "OS_Main_Pred_Count":
            len(
                os_main_pred_ids
            ),

        "OS_Main_Pred_Relabeled_IDs":
            ids_to_string(
                os_main_pred_ids
            ),

        "OS_Extra_Pred_Count":
            len(
                os_extra_pred_ids
            ),

        "OS_Extra_Pred_Relabeled_IDs":
            ids_to_string(
                os_extra_pred_ids
            ),

        "OS_Extra_Fragment_Relation_Count":
            os_extra_relation_count,

        # ====================================================
        # US counts
        # ====================================================

        "US_GT_Count":
            len(
                under_gt_ids
            ),

        "US_GT_Relabeled_IDs":
            ids_to_string(
                under_gt_ids
            ),

        "US_Pred_Count":
            len(
                under_pred_ids
            ),

        "US_Pred_Relabeled_IDs":
            ids_to_string(
                under_pred_ids
            ),

        "US_GT_Relation_Count":
            us_gt_relation_count,

        "US_Extra_GT_Relation_Count":
            us_extra_gt_relation_count,

        # ====================================================
        # FN
        # ====================================================

        "FN_GT_Count":
            len(
                fn_gt_ids
            ),

        "FN_GT_Relabeled_IDs":
            ids_to_string(
                fn_gt_ids
            ),

        # ====================================================
        # FP
        # ====================================================

        "FP_Pred_Count":
            len(
                fp_pred_ids
            ),

        "FP_Pred_Relabeled_IDs":
            ids_to_string(
                fp_pred_ids
            ),

        # ====================================================
        # Total foreground voxel counts
        # ====================================================

        "GT_Foreground_Voxel_Count":
            gt_total_voxels,

        "Pred_Foreground_Voxel_Count":
            pred_total_voxels,

        "GT_Mean_Instance_Voxel_Count":
            gt_mean_voxels,

        "Pred_Mean_Instance_Voxel_Count":
            pred_mean_voxels,

        # ====================================================
        # Pair voxels
        # ====================================================

        "Pair_GT_Voxel_Count":
            pair_gt_voxels,

        "Pair_Pred_Voxel_Count":
            pair_pred_voxels,

        "Pair_Intersection_Voxel_Count":
            pair_intersection_voxels,

        "Pair_Union_Voxel_Count":
            pair_union_voxels,

        # ====================================================
        # OS voxels
        # ====================================================

        "OS_GT_Voxel_Count":
            os_gt_voxels,

        "OS_Pred_Voxel_Count":
            os_pred_voxels,

        "OS_Main_Pred_Voxel_Count":
            os_main_pred_voxels,

        "OS_Extra_Pred_Voxel_Count":
            os_extra_pred_voxels,

        "OS_Overlap_Voxel_Count":
            os_overlap_voxels,

        # ====================================================
        # US voxels
        # ====================================================

        "US_GT_Voxel_Count":
            us_gt_voxels,

        "US_Pred_Voxel_Count":
            us_pred_voxels,

        "US_Overlap_Voxel_Count":
            us_overlap_voxels,

        # ====================================================
        # FN / FP voxels
        # ====================================================

        "FN_GT_Voxel_Count":
            fn_gt_voxels,

        "FP_Pred_Voxel_Count":
            fp_pred_voxels,

        # ====================================================
        # Voxel confusion counts
        # ====================================================

        "Voxel_TP_Count":
            voxel_tp,

        "Voxel_TN_Count":
            voxel_tn,

        "Voxel_FP_Count":
            voxel_fp,

        "Voxel_FN_Count":
            voxel_fn,

        # ====================================================
        # GT / Pred physical volume
        # ====================================================

        "GT_Foreground_Volume_um3":
            voxels_to_um3(
                gt_total_voxels
            ),

        "Pred_Foreground_Volume_um3":
            voxels_to_um3(
                pred_total_voxels
            ),

        "GT_Mean_Instance_Volume_um3":
            (
                voxels_to_um3(
                    gt_mean_voxels
                )
                if not np.isnan(
                    gt_mean_voxels
                )
                else np.nan
            ),

        "Pred_Mean_Instance_Volume_um3":
            (
                voxels_to_um3(
                    pred_mean_voxels
                )
                if not np.isnan(
                    pred_mean_voxels
                )
                else np.nan
            ),

        # ====================================================
        # Pair physical volume
        # ====================================================

        "Pair_GT_Volume_um3":
            voxels_to_um3(
                pair_gt_voxels
            ),

        "Pair_Pred_Volume_um3":
            voxels_to_um3(
                pair_pred_voxels
            ),

        "Pair_Intersection_Volume_um3":
            voxels_to_um3(
                pair_intersection_voxels
            ),

        "Pair_Union_Volume_um3":
            voxels_to_um3(
                pair_union_voxels
            ),

        # ====================================================
        # OS physical volume
        # ====================================================

        "OS_GT_Volume_um3":
            voxels_to_um3(
                os_gt_voxels
            ),

        "OS_Pred_Volume_um3":
            voxels_to_um3(
                os_pred_voxels
            ),

        "OS_Main_Pred_Volume_um3":
            voxels_to_um3(
                os_main_pred_voxels
            ),

        "OS_Extra_Pred_Volume_um3":
            voxels_to_um3(
                os_extra_pred_voxels
            ),

        "OS_Overlap_Volume_um3":
            voxels_to_um3(
                os_overlap_voxels
            ),

        # ====================================================
        # US physical volume
        # ====================================================

        "US_GT_Volume_um3":
            voxels_to_um3(
                us_gt_voxels
            ),

        "US_Pred_Volume_um3":
            voxels_to_um3(
                us_pred_voxels
            ),

        "US_Overlap_Volume_um3":
            voxels_to_um3(
                us_overlap_voxels
            ),

        # ====================================================
        # FN / FP physical volume
        # ====================================================

        "FN_GT_Volume_um3":
            voxels_to_um3(
                fn_gt_voxels
            ),

        "FP_Pred_Volume_um3":
            voxels_to_um3(
                fp_pred_voxels
            ),

        # ====================================================
        # Voxel confusion physical volume
        # ====================================================

        "Voxel_TP_Volume_um3":
            voxels_to_um3(
                voxel_tp
            ),

        "Voxel_TN_Volume_um3":
            voxels_to_um3(
                voxel_tn
            ),

        "Voxel_FP_Volume_um3":
            voxels_to_um3(
                voxel_fp
            ),

        "Voxel_FN_Volume_um3":
            voxels_to_um3(
                voxel_fn
            ),
    }

    return stats


# ============================================================
# Shape alignment helpers
# ============================================================

def _relabel_array_sequential(x):
    """
    Relabel positive instance IDs in an in-memory label array to 1..N.

    This is used only after automatic cropping.  Cropping can completely
    remove edge instances and therefore leave gaps in the already-relabeled
    IDs.  Re-labeling the cropped arrays keeps the instance accounting
    identical to evaluating the cropped label volumes directly.
    """
    x = np.asarray(x)
    out = np.zeros(x.shape, dtype=np.int32)

    positive = x > 0
    if not np.any(positive):
        return out

    _, inverse = np.unique(x[positive], return_inverse=True)
    out[positive] = inverse.astype(np.int32, copy=False) + 1
    return out


def crop_to_common_shape(gt, pred, image, method):
    """
    Align GT and prediction by cropping from index 0 to the common minimum
    size in every dimension when their shapes differ.

    Example
    -------
    GT   : (62, 1048, 1048)
    Pred : (62, 1049, 1049)

    Evaluation uses:
        gt[:, :1048, :1048]
        pred[:, :1048, :1048]

    More generally, if another dimension also differs, both arrays are
    cropped to min(GT_size, Pred_size) along that dimension as well.

    Metric definitions are not changed; only the common spatial field of
    view is evaluated.
    """
    original_gt_shape = tuple(gt.shape)
    original_pred_shape = tuple(pred.shape)

    if original_gt_shape == original_pred_shape:
        return (
            gt,
            pred,
            '',
            False,
            original_gt_shape,
            original_pred_shape,
            original_gt_shape,
        )

    if gt.ndim != pred.ndim:
        raise ValueError(
            '\nGT and prediction have different numbers of dimensions; '
            'automatic cropping is unsafe.\n'
            f'Image      : {image}\n'
            f'Method     : {method}\n'
            f'GT shape   : {original_gt_shape}\n'
            f'Pred shape : {original_pred_shape}\n'
        )

    common_shape = tuple(
        min(g, p)
        for g, p in zip(original_gt_shape, original_pred_shape)
    )
    crop_slices = tuple(slice(0, size) for size in common_shape)

    # Re-label after cropping because an edge crop may remove an entire
    # instance, leaving non-contiguous IDs in the in-memory label arrays.
    gt_crop = _relabel_array_sequential(gt[crop_slices])
    pred_crop = _relabel_array_sequential(pred[crop_slices])

    warning_message = (
        f'Shape mismatch: GT {original_gt_shape}, Pred {original_pred_shape}; '
        f'both cropped to {common_shape} before metric calculation.'
    )

    return (
        gt_crop,
        pred_crop,
        warning_message,
        True,
        original_gt_shape,
        original_pred_shape,
        common_shape,
    )


def shape_to_string(shape):
    """Convert a shape tuple to a compact CSV-friendly string."""
    return 'x'.join(str(v) for v in shape)


# ============================================================
# Main
# ============================================================

def _evaluate_method_for_image(
    image,
    gt_path,
    gt,
    gt_areas,
    method,
    pred_path,
    match_threshold,
    tolerance,
    underseg_threshold,
    nsd_tolerance_um,
    gt_surface_state,
):
    """Evaluate one GT/prediction pair without changing metric definitions."""
    pred = read_label(pred_path)

    (
        gt_eval,
        pred_eval,
        shape_warning,
        was_cropped,
        original_gt_shape,
        original_pred_shape,
        evaluated_shape,
    ) = crop_to_common_shape(
        gt=gt,
        pred=pred,
        image=image,
        method=method,
    )

    if was_cropped:
        # The image-level GT caches were built for the original GT shape.
        # After cropping, recompute only the shape-dependent GT data.
        gt_for_eval = gt_eval
        gt_areas_for_eval = areas(gt_for_eval)
        gt_surface_state_for_eval = {
            'groups': None,
            'tree_cache': {},
        }
    else:
        gt_for_eval = gt
        gt_areas_for_eval = gt_areas
        gt_surface_state_for_eval = gt_surface_state

    pred = pred_eval
    pred_areas = areas(pred)

    result = match_instances(
        gt=gt_for_eval,
        pred=pred,
        match_threshold=match_threshold,
        tolerance=tolerance,
        underseg_threshold=underseg_threshold,
        gt_areas=gt_areas_for_eval,
        pred_areas=pred_areas,
    )

    one = result['one']
    over_gt_ids = result['over_gt_ids']
    under_gt_ids = result['under_gt_ids']
    under_pred_ids = result['under_pred_ids']
    fn_gt_ids = result['fn_gt_ids']
    fp_pred_ids = result['fp_pred_ids']
    ga = result['ga']
    pa = result['pa']
    ov = result['ov']

    n_gt = len(ga)
    n_pred = len(pa)

    osr = safe_rate(len(over_gt_ids), n_gt)
    usr = safe_rate(len(under_gt_ids), n_gt)
    fnr = safe_rate(len(fn_gt_ids), n_gt)
    fpr = safe_rate(len(fp_pred_ids), n_pred)

    mean_iou = iou_metric_from_overlap(ov, ga, pa, one)

    # Surface extraction is expensive, so compute it only when there is at
    # least one rule-based one-to-one pair.  GT surfaces are computed once
    # and reused across every method for this image.
    if one:
        if gt_surface_state_for_eval['groups'] is None:
            gt_surface_state_for_eval['groups'] = build_surface_point_groups(gt_for_eval)

        pred_surface_groups = build_surface_point_groups(pred)
        hd, nsd = hd_nsd_from_surface_groups(
            gt_surface_groups=gt_surface_state_for_eval['groups'],
            pred_surface_groups=pred_surface_groups,
            pairs=one,
            tol=nsd_tolerance_um,
            gt_tree_cache=gt_surface_state_for_eval['tree_cache'],
        )
    else:
        hd = np.nan
        nsd = np.nan

    ap_rule, rule_tp, rule_fp, rule_fn = rule_based_ap_details(
        one=one,
        fp_pred_ids=fp_pred_ids,
        fn_gt_ids=fn_gt_ids,
    )

    (
        ap_iou50,
        iou50_tp,
        iou50_fp,
        iou50_fn,
        iou50_mean_iou,
    ) = iou_ap_details(
        ov=ov,
        ga=ga,
        pa=pa,
        threshold=AP_IOU_THRESHOLD,
    )

    intermediate = collect_intermediate_statistics(
        gt=gt_for_eval,
        pred=pred,
        result=result,
    )

    row = {
        'Image': image,
        'Method': method,
        'GT_Path': str(gt_path),
        'Pred_Path': str(pred_path),
        'Warning': shape_warning,
        'Was_Cropped': was_cropped,
        'Original_GT_Shape': shape_to_string(original_gt_shape),
        'Original_Pred_Shape': shape_to_string(original_pred_shape),
        'Evaluated_Shape': shape_to_string(evaluated_shape),
        'Match_Threshold': match_threshold,
        'Tolerance': tolerance,
        'Underseg_Threshold': underseg_threshold,
        'AP_IoU_Threshold': AP_IOU_THRESHOLD,
        'NSD_Tolerance_um': nsd_tolerance_um,
        'Spacing_Z_um': SPACING[0],
        'Spacing_Y_um': SPACING[1],
        'Spacing_X_um': SPACING[2],
        'FDR': fdr_from_overlap(ov, ga),
        'OSR': osr,
        'USR': usr,
        'FNR': fnr,
        'FPR': fpr,
        'IoU': mean_iou,
        'HD': hd,
        'NSD': nsd,
        'ARI': ari_from_overlap(ov),
        'AP_RuleBased': ap_rule,
        'Rule_TP_Count': rule_tp,
        'Rule_FP_Count': rule_fp,
        'Rule_FN_Count': rule_fn,
        'AP_IoU50': ap_iou50,
        'IoU50_TP_Count': iou50_tp,
        'IoU50_FP_Count': iou50_fp,
        'IoU50_FN_Count': iou50_fn,
        'IoU50_Matched_Mean_IoU': iou50_mean_iou,
    }
    row.update(intermediate)

    summary = (
        f'{method}: GT={n_gt}, Pred={n_pred}, TP(pair)={rule_tp}, '
        f'OS_GT={len(over_gt_ids)}, US_GT={len(under_gt_ids)}, '
        f'US_Pred={len(under_pred_ids)}, FN={rule_fn}, FP={rule_fp}, '
        f'AP_rule={ap_rule:.4f}' if not np.isnan(ap_rule)
        else
        f'{method}: GT={n_gt}, Pred={n_pred}, TP(pair)={rule_tp}, '
        f'OS_GT={len(over_gt_ids)}, US_GT={len(under_gt_ids)}, '
        f'US_Pred={len(under_pred_ids)}, FN={rule_fn}, FP={rule_fp}, '
        'AP_rule=nan'
    )

    return row, summary, shape_warning


def _process_image_job(job):
    """
    Worker unit = one GT image plus all available methods.

    This is intentionally image-level rather than image-method-level so the
    GT volume, GT areas, and GT surface/KD-tree data are reused across all
    methods for the same image.
    """
    (
        image_index,
        image,
        gt_path_str,
        method_items,
        match_threshold,
        tolerance,
        underseg_threshold,
        nsd_tolerance_um,
    ) = job

    gt_path = Path(gt_path_str)
    gt = read_label(gt_path)
    gt_areas = areas(gt)

    gt_surface_state = {
        'groups': None,
        'tree_cache': {},
    }

    rows = []
    summaries = []
    warnings = []

    for method, pred_path_str in method_items:
        row, summary, shape_warning = _evaluate_method_for_image(
            image=image,
            gt_path=gt_path,
            gt=gt,
            gt_areas=gt_areas,
            method=method,
            pred_path=Path(pred_path_str),
            match_threshold=match_threshold,
            tolerance=tolerance,
            underseg_threshold=underseg_threshold,
            nsd_tolerance_um=nsd_tolerance_um,
            gt_surface_state=gt_surface_state,
        )
        rows.append(row)
        summaries.append(summary)
        if shape_warning:
            warnings.append(f'{method}: {shape_warning}')

    return image_index, image, rows, summaries, warnings


def _resolve_worker_count(requested):
    if requested > 0:
        return requested

    cpu_count = os.cpu_count() or 1
    # Conservative automatic setting: enough parallelism for a large server
    # without multiplying the memory footprint by every logical CPU.
    return max(1, min(8, cpu_count // 2 if cpu_count > 1 else 1))


def main():
    parser = argparse.ArgumentParser(
        description='Rule-based 3D instance segmentation evaluator.'
    )

    parser.add_argument(
        '--gt-dir',
        required=True,
        help='Directory containing *_labels.tif or *_labels.tiff GT files.',
    )
    parser.add_argument(
        '--pred-root',
        required=True,
        help='Root directory containing prediction files.',
    )
    parser.add_argument(
        '--output',
        default='metrics.csv',
        help='Output CSV path.',
    )
    parser.add_argument(
        '--match-threshold',
        type=float,
        default=0.5,
        help='Threshold for one-to-one matching and FN/FP. Default = 0.5.',
    )
    parser.add_argument(
        '--tolerance',
        type=float,
        default=0.1,
        help='Tolerance for one-to-one residual overlap and over-segmentation. Default = 0.1.',
    )
    parser.add_argument(
        '--underseg-threshold',
        type=float,
        default=0.5,
        help='Independent under-segmentation threshold. US uses overlap / GT volume. Default = 0.5.',
    )
    parser.add_argument(
        '--nsd-tolerance-um',
        type=float,
        default=1.0,
        help='NSD surface tolerance in micrometers. Default = 1.0.',
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=0,
        help=(
            'Number of parallel image workers. 0 = automatic conservative '
            'choice (up to 8). Use 1 for fully sequential execution.'
        ),
    )
    parser.add_argument(
        '--chunksize',
        type=int,
        default=1,
        help='ProcessPool map chunksize. Default = 1.',
    )

    args = parser.parse_args()

    if not 0 <= args.match_threshold <= 1:
        raise ValueError('--match-threshold must be between 0 and 1.')
    if not 0 <= args.underseg_threshold <= 1:
        raise ValueError('--underseg-threshold must be between 0 and 1.')
    if not 0 <= args.tolerance <= 1:
        raise ValueError('--tolerance must be between 0 and 1.')
    if args.nsd_tolerance_um < 0:
        raise ValueError('--nsd-tolerance-um must be >= 0.')
    if args.workers < 0:
        raise ValueError('--workers must be >= 0.')
    if args.chunksize < 1:
        raise ValueError('--chunksize must be >= 1.')

    workers = _resolve_worker_count(args.workers)
    start_time = time.perf_counter()

    print('\n============================================================')
    print('3D instance segmentation evaluation - optimized parallel')
    print('============================================================')
    print(f'Match threshold      : {args.match_threshold}')
    print(f'Tolerance            : {args.tolerance}')
    print(f'Underseg threshold   : {args.underseg_threshold}')
    print(f'AP IoU threshold     : {AP_IOU_THRESHOLD}')
    print(f'NSD tolerance (um)   : {args.nsd_tolerance_um}')
    print(f'Spacing (z,y,x) um   : {SPACING}')
    print(f'Voxel volume (um^3)  : {VOXEL_VOLUME_UM3}')
    print(f'Workers              : {workers}')
    print(f'Chunksize            : {args.chunksize}')
    print('============================================================\n')

    gt_paths = list_gt(args.gt_dir)
    print(f'Found {len(gt_paths)} GT files.')

    # ========================================================
    # Scan prediction filesystem ONCE and resolve all exact matches.
    # ========================================================
    print('Indexing prediction files once...')
    index_start = time.perf_counter()
    prediction_index = build_prediction_index(args.pred_root)
    print(
        f'Prediction index built in {time.perf_counter() - index_start:.2f} s '
        f'({sum(len(v) for v in prediction_index.values())} TIFF files).'
    )

    jobs = []
    total_pairs = 0
    total_missing = 0

    for image_index, gt_path in enumerate(gt_paths):
        image = gt_path.stem[:-7]
        method_items = []

        for method, alias in METHODS.items():
            pred_path = find_prediction_indexed(
                prediction_index,
                image,
                method,
                alias,
            )

            if pred_path is None:
                total_missing += 1
                continue

            method_items.append((method, str(pred_path)))
            total_pairs += 1

        jobs.append((
            image_index,
            image,
            str(gt_path),
            method_items,
            args.match_threshold,
            args.tolerance,
            args.underseg_threshold,
            args.nsd_tolerance_um,
        ))

    # Index is no longer needed in parent once jobs have exact paths.
    del prediction_index

    print(f'Resolved {total_pairs} image-method evaluations.')
    print(f'Missing image-method combinations: {total_missing}.')

    rows = []

    # ========================================================
    # Parallelize across GT images.
    # executor.map preserves input order, so CSV order remains deterministic.
    # ========================================================
    if workers == 1:
        iterator = map(_process_image_job, jobs)
        for done, (image_index, image, image_rows, summaries, warnings) in enumerate(iterator, start=1):
            rows.extend(image_rows)
            print(f'[{done}/{len(jobs)}] {image}: {len(image_rows)} methods done')
            for warning in warnings:
                print(f'  [WARNING] {warning}')
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            iterator = executor.map(
                _process_image_job,
                jobs,
                chunksize=args.chunksize,
            )
            for done, (image_index, image, image_rows, summaries, warnings) in enumerate(iterator, start=1):
                rows.extend(image_rows)
                print(f'[{done}/{len(jobs)}] {image}: {len(image_rows)} methods done')
                for warning in warnings:
                    print(f'  [WARNING] {warning}')

    df = pd.DataFrame(rows)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    elapsed = time.perf_counter() - start_time

    print('\n============================================================')
    print('Finished.')
    print(f'Total result rows : {len(df)}')
    print(f'Elapsed time      : {elapsed:.2f} s ({elapsed / 60:.2f} min)')
    print(f'Saved to          : {output_path}')
    print('============================================================')


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    main()