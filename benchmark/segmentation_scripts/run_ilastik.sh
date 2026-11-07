#!/usr/bin/env bash
set -u

# ============================================================
# Batch ilastik: Pixel Classification + Object Classification
#
# Pipeline:
#   raw 3D tif
#   -> Pixel Classification: export Probabilities
#   -> Object Classification [Raw Data + Pixel Prediction Map]:
#      export Object Identities
#
# Output default:
#   final 3D instance labels as HDF5:
#       output_dir/.../sample_ilastik_OC.h5/exported_data
#
# Usage:
#   chmod +x run_ilastik_PC_OC_batch.sh
#   ./run_ilastik_PC_OC_batch.sh
# ============================================================


# =========================
# Change these paths
# =========================

INPUT_DIR="/media/WD4T/lyz32/data/"
OUTPUT_DIR="/media/WD4T/lyz32/results/ilastik"

PC_PROJECT="./PC.ilp"
OC_PROJECT="./OC.ilp"

# If ilastik is in PATH, use:
# ILASTIK="ilastik"
# If you use the downloaded Linux package, use something like:
# ILASTIK="/home/yourname/ilastik-1.4.1-Linux/run_ilastik.sh"
ILASTIK="./ilastik-1.4.1-Linux/run_ilastik.sh"

# Raw 3D TIF is assumed to be shape (Z,Y,X)
RAW_INPUT_AXES="zyx"

# Output suffix
SUFFIX="_ilastik"

# 1 = overwrite existing final output, 0 = skip existing output
OVERWRITE=0

# 1 = keep intermediate PC probability maps, 0 = remove them after OC finishes
KEEP_PROBABILITIES=0

# 1 = export object feature/classification table, 0 = do not export table
EXPORT_TABLE=0

# Final output format:
#   "compressed hdf5" is safest for 3D.
#   "multipage tiff" can also work if your ilastik build supports it.
FINAL_OUTPUT_FORMAT="multipage tiff"


# =========================
# Internal paths
# =========================

PROB_DIR="${OUTPUT_DIR}/_pixel_probabilities"
LOG_DIR="${OUTPUT_DIR}/_logs"
TABLE_DIR="${OUTPUT_DIR}/_object_tables"
TMP_DIR="${OUTPUT_DIR}/_tmp_probabilities"

mkdir -p "$OUTPUT_DIR" "$PROB_DIR" "$LOG_DIR" "$TABLE_DIR" "$TMP_DIR"


# =========================
# Checks
# =========================

if [[ ! -d "$INPUT_DIR" ]]; then
    echo "[ERROR] INPUT_DIR does not exist: $INPUT_DIR"
    exit 1
fi

if [[ ! -f "$PC_PROJECT" ]]; then
    echo "[ERROR] PC_PROJECT does not exist: $PC_PROJECT"
    exit 1
fi

if [[ ! -f "$OC_PROJECT" ]]; then
    echo "[ERROR] OC_PROJECT does not exist: $OC_PROJECT"
    exit 1
fi

if [[ "$ILASTIK" != "ilastik" && ! -x "$ILASTIK" ]]; then
    echo "[ERROR] ILASTIK is not executable: $ILASTIK"
    echo "        Set ILASTIK to /path/to/run_ilastik.sh or to ilastik if it is in PATH."
    exit 1
fi


# =========================
# Summary CSV
# =========================

SUMMARY_CSV="${OUTPUT_DIR}/ilastik_PC_OC_summary.csv"
echo "input_tif,probability_h5,output_label,table_csv,status,error" > "$SUMMARY_CSV"


# =========================
# Batch
# =========================

find "$INPUT_DIR" -type f \( -iname "*.tif" -o -iname "*.tiff" \) -print0 | \
while IFS= read -r -d '' RAW_TIF; do

    FILE_NAME="$(basename "$RAW_TIF")"
    STEM="${FILE_NAME%.*}"
    LOWER_STEM="$(echo "$STEM" | tr '[:upper:]' '[:lower:]')"

    # Skip result-like files
    if [[ "$LOWER_STEM" == *"_labels"* ]] || \
       [[ "$LOWER_STEM" == *"_label"* ]] || \
       [[ "$LOWER_STEM" == *"_mask"* ]] || \
       [[ "$LOWER_STEM" == *"_prob"* ]] || \
       [[ "$LOWER_STEM" == *"_object"* ]] || \
       [[ "$LOWER_STEM" == *"_identity"* ]] || \
       [[ "$LOWER_STEM" == *"_ilastik"* ]] || \
       [[ "$LOWER_STEM" == *"_seg"* ]]; then
        echo "[SKIP result-like file] $RAW_TIF"
        continue
    fi

    REL_PATH="${RAW_TIF#$INPUT_DIR/}"
    REL_DIR="$(dirname "$REL_PATH")"

    if [[ "$REL_DIR" == "." ]]; then
        OUT_DIR="$OUTPUT_DIR"
        PROB_SUBDIR="$PROB_DIR"
        LOG_SUBDIR="$LOG_DIR"
        TABLE_SUBDIR="$TABLE_DIR"
        TMP_SUBDIR="$TMP_DIR"
    else
        OUT_DIR="${OUTPUT_DIR}/${REL_DIR}"
        PROB_SUBDIR="${PROB_DIR}/${REL_DIR}"
        LOG_SUBDIR="${LOG_DIR}/${REL_DIR}"
        TABLE_SUBDIR="${TABLE_DIR}/${REL_DIR}"
        TMP_SUBDIR="${TMP_DIR}/${REL_DIR}"
    fi

    mkdir -p "$OUT_DIR" "$PROB_SUBDIR" "$LOG_SUBDIR" "$TABLE_SUBDIR" "$TMP_SUBDIR"

    # Pixel probability is saved as HDF5 because it is 4D: z,y,x,c
    if [[ "$KEEP_PROBABILITIES" -eq 1 ]]; then
        PROB_H5="${PROB_SUBDIR}/${STEM}_Probabilities.h5"
    else
        PROB_H5="${TMP_SUBDIR}/${STEM}_Probabilities.h5"
    fi

    # Dataset path inside the probability HDF5
    PROB_DATASET_PATH="${PROB_H5}/exported_data"

    # Final output
    if [[ "$FINAL_OUTPUT_FORMAT" == "compressed hdf5" || "$FINAL_OUTPUT_FORMAT" == "hdf5" ]]; then
        LABEL_OUT="${OUT_DIR}/${STEM}${SUFFIX}.h5"
        LABEL_DATASET_PATH="${LABEL_OUT}/exported_data"
    elif [[ "$FINAL_OUTPUT_FORMAT" == "multipage tiff" ]]; then
        LABEL_OUT="${OUT_DIR}/${STEM}${SUFFIX}.tiff"
        LABEL_DATASET_PATH="$LABEL_OUT"
    else
        echo "[ERROR] Unsupported FINAL_OUTPUT_FORMAT: $FINAL_OUTPUT_FORMAT"
        exit 1
    fi

    if [[ "$EXPORT_TABLE" -eq 1 ]]; then
        TABLE_OUT="${TABLE_SUBDIR}/${STEM}_object_features.csv"
    else
        TABLE_OUT=""
    fi

    PC_LOG="${LOG_SUBDIR}/${STEM}_PC.log"
    OC_LOG="${LOG_SUBDIR}/${STEM}_OC.log"

    if [[ -f "$LABEL_OUT" && "$OVERWRITE" -ne 1 ]]; then
        echo "[SKIP existing] $LABEL_OUT"
        echo "\"$RAW_TIF\",\"$PROB_H5\",\"$LABEL_OUT\",\"$TABLE_OUT\",\"skipped\",\"\"" >> "$SUMMARY_CSV"
        continue
    fi

    echo "============================================================"
    echo "[PROCESS] $RAW_TIF"
    echo "[PC PROB] $PROB_DATASET_PATH"
    echo "[OC OUT]  $LABEL_DATASET_PATH"
    echo "============================================================"


    # ------------------------------------------------------------
    # Step 1: Pixel Classification -> Probabilities
    # ------------------------------------------------------------

    echo "[STEP 1] Pixel Classification -> Probabilities"

    "$ILASTIK" \
        --headless \
        --readonly \
        --project="$PC_PROJECT" \
        --export_source="Probabilities" \
        --output_format="compressed hdf5" \
        --output_filename_format="$PROB_H5" \
        --output_internal_path="exported_data" \
        --export_dtype=float32 \
        --input_axes="$RAW_INPUT_AXES" \
        "$RAW_TIF" \
        > "$PC_LOG" 2>&1

    STATUS=$?
    if [[ "$STATUS" -ne 0 ]]; then
        echo "[FAILED] Pixel Classification failed: $RAW_TIF"
        echo "[LOG] $PC_LOG"
        echo "\"$RAW_TIF\",\"$PROB_H5\",\"$LABEL_OUT\",\"$TABLE_OUT\",\"failed\",\"Pixel Classification failed\"" >> "$SUMMARY_CSV"
        continue
    fi

    if [[ ! -f "$PROB_H5" ]]; then
        echo "[FAILED] Probability HDF5 not found: $PROB_H5"
        echo "\"$RAW_TIF\",\"$PROB_H5\",\"$LABEL_OUT\",\"$TABLE_OUT\",\"failed\",\"Probability HDF5 not found\"" >> "$SUMMARY_CSV"
        continue
    fi


    # ------------------------------------------------------------
    # Step 2: Object Classification -> Object Identities
    # ------------------------------------------------------------

    echo "[STEP 2] Object Classification -> Object Identities"

    if [[ "$EXPORT_TABLE" -eq 1 ]]; then
        "$ILASTIK" \
            --headless \
            --readonly \
            --project="$OC_PROJECT" \
            --export_source="Object Identities" \
            --output_format="$FINAL_OUTPUT_FORMAT" \
            --output_filename_format="$LABEL_OUT" \
            --output_internal_path="exported_data" \
            --export_dtype=uint32 \
            --raw_data "$RAW_TIF" \
            --prediction_maps "$PROB_DATASET_PATH" \
            --table_filename="$TABLE_OUT" \
            > "$OC_LOG" 2>&1
    else
        "$ILASTIK" \
            --headless \
            --readonly \
            --project="$OC_PROJECT" \
            --export_source="Object Identities" \
            --output_format="$FINAL_OUTPUT_FORMAT" \
            --output_filename_format="$LABEL_OUT" \
            --output_internal_path="exported_data" \
            --export_dtype=uint32 \
            --raw_data "$RAW_TIF" \
            --prediction_maps "$PROB_DATASET_PATH" \
            > "$OC_LOG" 2>&1
    fi

    STATUS=$?
    if [[ "$STATUS" -ne 0 ]]; then
        echo "[FAILED] Object Classification failed: $RAW_TIF"
        echo "[LOG] $OC_LOG"
        echo "\"$RAW_TIF\",\"$PROB_H5\",\"$LABEL_OUT\",\"$TABLE_OUT\",\"failed\",\"Object Classification failed\"" >> "$SUMMARY_CSV"
        continue
    fi

    if [[ ! -f "$LABEL_OUT" ]]; then
        echo "[FAILED] Final label output not found: $LABEL_OUT"
        echo "\"$RAW_TIF\",\"$PROB_H5\",\"$LABEL_OUT\",\"$TABLE_OUT\",\"failed\",\"Final label output not found\"" >> "$SUMMARY_CSV"
        continue
    fi

    echo "[SAVED] $LABEL_DATASET_PATH"
    echo "\"$RAW_TIF\",\"$PROB_H5\",\"$LABEL_OUT\",\"$TABLE_OUT\",\"ok\",\"\"" >> "$SUMMARY_CSV"

    if [[ "$KEEP_PROBABILITIES" -ne 1 ]]; then
        rm -f "$PROB_H5"
    fi

done

if [[ "$KEEP_PROBABILITIES" -ne 1 ]]; then
    rm -rf "$TMP_DIR"
fi

echo "============================================================"
echo "[DONE] Batch finished."
echo "[SUMMARY] $SUMMARY_CSV"
echo "============================================================"
