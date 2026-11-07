# cellpose-sam.py
import os
import argparse
from glob import glob
from cellpose import models, core, io
import numpy as np

def run_cellpose_on_folder(input_dir, output_dir):
    if not core.use_gpu():
        raise ImportError("No GPU access, change your runtime or check CUDA setup.")
    model_path = '/public/home/sa23229001/project/3DCell/scripts/cellpose-sam/models/cpsam'
    model = models.CellposeModel(gpu=True, pretrained_model=model_path)

    # 创建输出子文件夹
    save_dir = os.path.join(output_dir, 'cellpose-sam')
    os.makedirs(save_dir, exist_ok=True)

    tif_files = glob(os.path.join(input_dir, '*.tif'))

    for tif_path in tif_files:
        print(f"Processing {tif_path}...")
        img_3D = io.imread(tif_path)

        masks, flows, _ = model.eval(img_3D, z_axis=0,
                                      batch_size=32,
                                      do_3D=True,
                                      flow3D_smooth=1)

        base_name = os.path.basename(tif_path)
        name_wo_ext = os.path.splitext(base_name)[0]
        out_name = f"{name_wo_ext}_cellpose-sam.tif"
        out_path = os.path.join(save_dir, out_name)
        io.imsave(out_path, masks.astype(np.int32))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch run Cellpose-SAM 3D segmentation on a folder of TIFs.")
    parser.add_argument('--input', required=True, help="Path to input folder containing .tif files")
    parser.add_argument('--output', required=True, help="Path to output folder")

    args = parser.parse_args()
    run_cellpose_on_folder(args.input, args.output)

