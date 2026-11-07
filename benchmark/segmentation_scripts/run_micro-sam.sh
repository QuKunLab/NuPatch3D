#!/bin/bash
# run_micro-sam.sh
source /public/home/sa23229001/.bashrc
conda activate micro-sam

INPUT_DIR="/public/home/sa23229001/project/3DCell/data/"
OUTPUT_DIR="/public/home/sa23229001/project/3DCell/data/results/micro-sam"

MODEL_TYPE="vit_b_lm"
NDIM=3

mkdir -p "$OUTPUT_DIR"

echo "============================================================"
echo "INPUT_DIR:  $INPUT_DIR"
echo "OUTPUT_DIR: $OUTPUT_DIR"
echo "MODEL_TYPE: $MODEL_TYPE"
echo "NDIM:       $NDIM"
echo "============================================================"

find "$INPUT_DIR" -type f \( -iname "*.tif" -o -iname "*.tiff" \) -print0 | \
while IFS= read -r -d '' INPUT_PATH; do

    # 相对路径，保持多级文件夹结构
    REL_PATH="${INPUT_PATH#$INPUT_DIR/}"
    REL_DIR="$(dirname "$REL_PATH")"
    FILE_NAME="$(basename "$INPUT_PATH")"

    # 去掉扩展名
    BASE_NAME="${FILE_NAME%.*}"

    # 输出路径：原文件名 + _micro-sam.tif
    OUT_DIR="${OUTPUT_DIR}/${REL_DIR}"
    OUTPUT_PATH="${OUT_DIR}/${BASE_NAME}_micro-sam.tif"

    mkdir -p "$OUT_DIR"

    echo "------------------------------------------------------------"
    echo "[INPUT]  $INPUT_PATH"
    echo "[OUTPUT] $OUTPUT_PATH"

    micro_sam.automatic_segmentation \
        --input_path "$INPUT_PATH" \
        --output_path "$OUTPUT_PATH" \
        --model_type "$MODEL_TYPE" \
        --ndim "$NDIM"

    STATUS=$?

    if [ $STATUS -ne 0 ]; then
        echo "[ERROR] Failed: $INPUT_PATH"
        continue
    fi

    echo "[DONE] $OUTPUT_PATH"

done

echo "============================================================"
echo "All files processed."
echo "============================================================"
