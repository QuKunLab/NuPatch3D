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

These categories are evaluated independently and may overlap. Rule-based comparisons use strict inequalities.

## Metric Definitions

Let $N_G$ and $N_P$ be the numbers of GT and predicted instances.

| Metric | Definition |
| --- | --- |
| `FR` | Foreground intersection voxel count divided by GT foreground voxel count; foreground detection rate, not false discovery rate. |
| `OSR` | Number of over-segmented GT instances / $N_G$. |
| `USR` | Number of under-segmented GT instances / $N_G$. |
| `MNR` | Number of rule-based FN instances / $N_G$. |
| `IoU` | Mean intersection-over-union over rule-based one-to-one pairs. |
| `AP` | $TP/(TP+FP+FN)$ using the rule-based counts above. |

Undefined metrics are stored as `NaN`. `AP` is the rule-based instance matching score $TP/(TP+FP+FN)$, not a precision–recall curve integral. The six reported metrics are `FR`, `IoU`, `OSR`, `USR`, `MNR`, and `AP`; counts and physical volumes are auxiliary statistics.

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
pip install numpy pandas tifffile
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
  --workers 4
```

Only `--gt-dir` and `--pred-root` are required. `--workers 0` selects up to eight processes automatically; `--workers 1` runs sequentially. Output contains one row per available image–method combination, including metrics, counts, relabeled instance IDs, voxel counts, physical volumes, and any cropping warning.
