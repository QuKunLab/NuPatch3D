#!/bin/bash
# run_swinunetr.sh
source /public/home/sa23229001/.bashrc
conda activate cellprofiler

INPUT_DIR="/public/home/sa23229001/project/3DCell/data/"
OUTPUT_DIR="/public/home/sa23229001/project/3DCell/data/results/cellprofiler"

cellprofiler -c -r -p 3DNucleiPipelineComputeConsumingFinal.cppipe -o $OUTPUT_DIR -i $INPUT_DIR
