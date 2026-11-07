# cellseg3d.py
import os
import argparse
from glob import glob
from skimage import io
import napari_cellseg3d
from tifffile import imread
from pathlib import Path
from napari_cellseg3d.dev_scripts import remote_inference as cs3d
from napari_cellseg3d.utils import LOGGER as logger
from napari_cellseg3d.config import ModelInfo
import torch
import numpy as np
import logging
logger.setLevel(logging.INFO)

def run_cellseg3d_on_folder(input_dir, output_dir):
    if not torch.cuda.is_available():
      print('You do not have GPU access.')
      print('Did you change your runtime?')
      print('If the runtime setting is correct then Google did not allocate a GPU for your session')
      print('Expect slow performance. To access GPU try reconnecting later')

    else:
      print('You have GPU access')

    inference_config = cs3d.CONFIG
    post_process_config = cs3d.PostProcessConfig()
    #import pyclesperanto_prototype as cle
    #cle.select_device("cupy")
    
    model_selection = "WNet3D" #@param ["SwinUNetR", "WNet3D", "SegResNet"]
    print(f"Selected model: {model_selection}")
    model_info = ModelInfo(
        name=model_selection,
        model_input_size=64 if model_selection == "SegResNet" else [64,64,64],
        num_classes=2,
    )
    inference_config.model_info = model_info

    # 创建输出子文件夹
    save_dir = os.path.join(output_dir, 'cellseg3d')
    os.makedirs(save_dir, exist_ok=True)

    tif_files = glob(os.path.join(input_dir, '*.tif'))

    for tif_path in tif_files:
        print(f"Processing {tif_path}...")
        img_3D = io.imread(tif_path)

        result = cs3d.inference_on_images(
            img_3D,
            config=inference_config,
        )
        
        if model_selection == "WNet3D":
           result[0].semantic_segmentation = result[0].semantic_segmentation[1]

        instance_segmentation,stats = cs3d.post_processing(
            result[0].semantic_segmentation,
            config=post_process_config,
        )

        base_name = os.path.basename(tif_path)
        name_wo_ext = os.path.splitext(base_name)[0]
        out_name = f"{name_wo_ext}_cellseg3d.tif"
        out_path = os.path.join(save_dir, out_name)
        io.imsave(out_path, instance_segmentation.astype(np.int32))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch run CellSeg3D 3D segmentation on a folder of TIFs.")
    parser.add_argument('--input', required=True, help="Path to input folder containing .tif files")
    parser.add_argument('--output', required=True, help="Path to output folder")

    args = parser.parse_args()
    run_cellseg3d_on_folder(args.input, args.output)
