# 3D Instance Segmentation Evaluation

Script: [`evaluate_3d_segmentation_parallel.py`](./evaluate_3d_segmentation_parallel.py)

## Matching Rules

For ground-truth instance $G_i$ and predicted instance $P_j$, define:

$$
O_{ij}=|G_i\cap P_j|,\qquad GR_{ij}=O_{ij}/|G_i|,\qquad PR_{ij}=O_{ij}/|P_j|.
$$

Default thresholds: matching $t=0.5$, tolerance $\epsilon=0.1$, and under-segmentation $u=0.5$.

- **One-to-one match (TP):** $GR_{ij}>t$, $PR_{ij}>t$, $\sum_{k\ne j}GR_{ik}<\epsilon$, and $\sum_{k\ne i}PR_{kj}<\epsilon$.
- **Over-segmentation (OS):** a GT overlaps multiple predictions, and the sum of their GT coverage fractions, excluding the largest, exceeds $\epsilon$.
- **Under-segmentation (US):** a prediction covers more than $u$ of each of at least two GT instances. All affected GT instances are counted, with duplicates removed.
- **False negative (FN):** $GR_{ij}<t$ for every prediction $j$.
- **False positive (FP):** $GR_{ij}<t$ for every GT $i$. This uses **GT coverage**, not prediction coverage; extra OS fragments are not automatically FP.

These categories are evaluated independently and may overlap. Rule-based comparisons use strict inequalities. The separate IoU50 matching uses an inclusive threshold on the computed IoU.

## Metric Definitions

Let $N_G$ and $N_P$ be the numbers of GT and predicted instances.

| Metric | Definition |
| --- | --- |
| `FR` | Foreground intersection voxel count divided by GT foreground voxel count; foreground detection rate, not false discovery rate. |
| `OSR` | Number of over-segmented GT instances / $N_G$. |
| `USR` | Number of under-segmented GT instances / $N_G$. |
| `MNR` | Number of rule-based FN instances / $N_G$. |
| `FPR` | Number of rule-based FP instances / $N_P$. |
| `IoU` | Mean intersection-over-union over rule-based one-to-one pairs. |
| `HD` | Mean symmetric Hausdorff distance over rule-based pairs, in μm. |
| `NSD` | Mean fraction of surface points within the distance tolerance of the opposite surface, over rule-based pairs; default tolerance: 1 μm. |
| `ARI` | Adjusted Rand Index computed only on voxels where both GT and prediction are foreground. |
| `AP_RuleBased` | $TP/(TP+FP+FN)$ using the rule-based counts above. |
| `AP_IoU50` | $TP/(TP+FP+FN)$ after one-to-one Hungarian assignment, prioritizing the number of IoU ≥ 0.5 matches, then total assigned IoU; $FP=N_P-TP$, $FN=N_G-TP$. |

HD and NSD use physical surface-voxel coordinates; NSD is point-count weighted. Undefined metrics are stored as `NaN`. The AP fields are instance matching scores, not precision–recall curve integrals. IoU50 and ARI include numerical stabilization terms, which can affect threshold-boundary or degenerate cases.

## Input Format

Provide spatially aligned **3D instance-label TIFFs in ZYX order**, with background `0` and positive integer instance IDs. GT and prediction IDs need not agree. Raw microscopy images are not required.

- **GT:** recursively discovered as `<image>_labels.tif` or `<image>_labels.tiff`.
- **Predictions:** `<image>_<method>.tif` / `<image>_<alias>.tif`, or `<method-or-alias>/<image>.tif`; `.tiff` is also supported.
- Method names and aliases are configured in the script's `METHODS` dictionary. Matching ignores case and non-alphanumeric characters but requires an exact normalized name. Missing predictions are skipped; multiple matching files raise an error.
- Shape mismatches are cropped from index zero to the common minimum size along each axis and recorded in the output. No registration or resampling is performed.

Set the physical voxel spacing in the script before evaluation:

```python
SPACING = (1.0, 0.137, 0.137)  # Z, Y, X in μm
```

Spacing is not read automatically from TIFF metadata. Physical volumes are reported in μm³.

## Usage

Install dependencies:

```bash
pip install numpy pandas scipy tifffile
```

Run:

```bash
python evaluate_3d_segmentation_parallel.py \
  --gt-dir /path/to/ground_truth \
  --pred-root /path/to/predictions \
  --output results/metrics.csv \
  --match-threshold 0.5 \
  --tolerance 0.1 \
  --underseg-threshold 0.5 \
  --nsd-tolerance-um 1.0 \
  --workers 4
```

Only `--gt-dir` and `--pred-root` are required. `--workers 0` selects up to eight processes automatically; `--workers 1` runs sequentially. Output contains one row per available image–method combination, including metrics, counts, relabeled instance IDs, voxel counts, physical volumes, and any cropping warning.
