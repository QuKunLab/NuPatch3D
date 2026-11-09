# stardist.py
from stardist.models import StarDist3D
from csbdeep.utils import normalize
from skimage import io
from scipy.ndimage import zoom
import os
import argparse
from glob import glob
import numpy as np
import tensorflow as tf

def run_stardist_on_folder(input_dir, output_dir):
    print("GPU available:", tf.config.list_physical_devices('GPU'))
    
    model_path = '/public/home/sa23229001/project/3DCell/scripts/stardist/models'
    model = StarDist3D(None, name='python_3D_demo', basedir=model_path)

    # 创建输出子文件夹
    save_dir = os.path.join(output_dir, 'stardist')
    os.makedirs(save_dir, exist_ok=True)

    tif_files = glob(os.path.join(input_dir, '*.tif'))

    for tif_path in tif_files:
        print(f"Processing {tif_path}...")
        img_3D = io.imread(tif_path)
        original_shape = img_3D.shape
        scale_factors = (1/.137, 1.0, 1.0)
        img_3D = zoom(img_3D, zoom=scale_factors, order=1)
        labels, _ = model.predict_instances(normalize(img_3D))

        # Restore the original voxel grid without interpolating instance IDs.
        restore_factors = tuple(
            original / predicted
            for original, predicted in zip(original_shape, labels.shape)
        )
        labels = zoom(labels, zoom=restore_factors, order=0, prefilter=False)
        if labels.shape != original_shape:
            raise ValueError(
                f"Restored label shape {labels.shape} does not match "
                f"input shape {original_shape} for {tif_path}"
            )

        base_name = os.path.basename(tif_path)
        name_wo_ext = os.path.splitext(base_name)[0]
        out_name = f"{name_wo_ext}_stardist.tif"
        out_path = os.path.join(save_dir, out_name)
        io.imsave(out_path, labels.astype(np.int32))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch run Stardist 3D segmentation on a folder of TIFs.")
    parser.add_argument('--input', required=True, help="Path to input folder containing .tif files")
    parser.add_argument('--output', required=True, help="Path to output folder")

    args = parser.parse_args()
    run_stardist_on_folder(args.input, args.output)
