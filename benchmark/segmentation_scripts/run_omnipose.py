# omnipose.py
from cellpose_omni import models, core
from skimage import io
import numpy as np
import os
import argparse
from glob import glob

def find_best_axes(dimensions):
    """
    找到最适合作为空间维度(X,Y)的两个轴，使得宽高比最接近1:1
    
    参数:
    dimensions (tuple): 三维数组的形状 (d1, d2, d3)
    
    返回:
    tuple: (z_axis, y_axis, x_axis) 最适合作为Z,Y,X的轴索引

    """
    # 计算所有可能的二维组合的宽高比
    ratios = []
    combinations = [(0, 1), (0, 2), (1, 2)]
    
    for i, j in combinations:
        dim1, dim2 = dimensions[i], dimensions[j]
        ratio = min(dim1, dim2) / max(dim1, dim2)
        ratios.append((ratio, i, j))
    
    # 选择宽高比最接近1的组合作为空间维度
    best_ratio, best_i, best_j = max(ratios, key=lambda x: x[0])
    
    # 剩下的轴作为Z轴
    z_axis = [k for k in range(3) if k != best_i and k != best_j][0]
    
    # 确保较大的维度作为X轴，较小的作为Y轴
    if dimensions[best_i] > dimensions[best_j]:
        x_axis, y_axis = best_i, best_j
    else:
        x_axis, y_axis = best_j, best_i
    
    return (z_axis, y_axis, x_axis)

def check_and_transpose_image(img_3D):
    """
    检查图像宽高比并在需要时转置
    
    参数:
    img_3D (numpy.ndarray): 输入的3D图像
    
    返回:
    tuple: (处理后的图像, 转置顺序, 原始形状, 是否进行了转置)
    """
    original_shape = img_3D.shape
    print(f"原始形状: {original_shape}")
    
    # 检查当前宽高比
    aspect_ratio = original_shape[2] / original_shape[1]  # X/Y
    print(f"当前宽高比: {aspect_ratio:.2f}")
    
    # 如果宽高比在合理范围内，直接返回
    if 0.5 <= aspect_ratio <= 2.0:
        print("宽高比在合理范围内，无需转置")
        return img_3D, [0, 1, 2], original_shape, False
    else:  # 尝试转置 
        print("宽高比不在合理范围内，尝试转置...")

        # 找到最佳轴配置
        z_axis, y_axis, x_axis = find_best_axes(original_shape)
        print(f"最佳轴配置: Z轴={z_axis}, Y轴={y_axis}, X轴={x_axis}")

        # 计算新形状和宽高比
        new_shape = (original_shape[z_axis], original_shape[y_axis], original_shape[x_axis])
        new_aspect_ratio = new_shape[2] / new_shape[1]  # X/Y
        print(f"新形状: {new_shape}, 宽高比: {new_aspect_ratio:.2f}")

        # 检查转置后的宽高比是否合理
        if 0.5 <= new_aspect_ratio <= 2.0:
            # 执行转置
            transpose_order = [z_axis, y_axis, x_axis]
            transposed_data = np.transpose(img_3D, transpose_order)
            print("转置成功，宽高比已调整到合理范围")
            return transposed_data, transpose_order, original_shape, True
        else:
            print("转置后宽高比仍不在合理范围内")
            return None, None, original_shape, False

def inverse_transpose(masks, transpose_order, original_shape):
    """
    将转置后的分割结果转置回原始形状
    
    参数:
    masks (numpy.ndarray): 转置后的分割结果
    transpose_order (list): 原始转置顺序
    original_shape (tuple): 原始图像形状
    
    返回:
    numpy.ndarray: 转置回原始形状的分割结果
    """
    # 计算逆转置顺序
    inv_transpose_order = [transpose_order.index(0), 
                          transpose_order.index(1), 
                          transpose_order.index(2)]
    
    # 执行逆转置
    original_masks = np.transpose(masks, inv_transpose_order)
    
    # 确保形状与原始图像一致
    assert original_masks.shape == original_shape, "逆转置后形状不匹配"
    
    return original_masks

def run_omnipose_on_folder(input_dir, output_dir):
    if not core.use_gpu():
        raise ImportError("No GPU access, change your runtime or check CUDA setup.")
    
    model_name = 'plant_omni'
    model = models.CellposeModel(gpu=True, model_type=model_name, diam_mean=0, net_avg=False, nclasses=3, dim=3, nchan=1, omni=1)
    
    # 创建输出子文件夹
    save_dir = os.path.join(output_dir, 'omnipose')
    os.makedirs(save_dir, exist_ok=True)

    tif_files = glob(os.path.join(input_dir, '*.tif'))
    
    for tif_path in tif_files:
        print(f"Processing {tif_path}...")
        img_3D = io.imread(tif_path)
        
        # 检查并在需要时转置图像
        processed_img, transpose_order, original_shape, was_transposed = check_and_transpose_image(img_3D)
        
        if processed_img is None:  # 无法通过转置获得合适的宽高比，生成错误文件
            base_name = os.path.basename(tif_path)
            name_wo_ext = os.path.splitext(base_name)[0]
            err_path = os.path.join(save_dir, f"{name_wo_ext}.err")
            with open(err_path, 'w') as f:
                f.write(f"图像{base_name}长宽比不符合要求，可能导致模型推理失败，建议单独进行额外处理。")
            
            print(f"已生成错误文件: {err_path}")
            continue
        
        # masks, flows, _ = model.eval(img_3D,
        #                              mask_threshold=0,
        #                              net_avg=False,
        #                              transparency=True,
        #                              flow_threshold=0.,
        #                              omni=True,
        #                              resample=False,
        #                              diam_threshold=12,
        #                              niter=10,
        #                              flow_factor=10) 
        # 
        # base_name = os.path.basename(tif_path)
        # name_wo_ext = os.path.splitext(base_name)[0]
        # out_name = f"{name_wo_ext}_omnipose.tif"
        # out_path = os.path.join(save_dir, out_name)
        # io.imsave(out_path, masks.astype(np.int32))
        
        try:
            # 模型预测
            masks, flows, _ = model.eval(img_3D,
                                     mask_threshold=0,
                                     net_avg=False,
                                     transparency=True,
                                     flow_threshold=0.,
                                     omni=True,
                                     resample=False,
                                     diam_threshold=12,
                                     niter=10,
                                     flow_factor=10)
            
            # 如果图像被转置过，需要将结果转置回原始形状
            if was_transposed:
                print("将分割结果转置回原始形状...")
                masks = inverse_transpose(masks, transpose_order, original_shape)
            
            # 保存结果
            base_name = os.path.basename(tif_path)
            name_wo_ext = os.path.splitext(base_name)[0]
            out_name = f"{name_wo_ext}_omnipose.tif"
            out_path = os.path.join(save_dir, out_name)
            io.imsave(out_path, masks.astype(np.int32))
            print(f"分割结果已保存: {out_path}")
            
        except Exception as e:
            print(f"处理图像时发生错误: {str(e)}")
            # 生成错误文件
            base_name = os.path.basename(tif_path)
            name_wo_ext = os.path.splitext(base_name)[0]
            err_path = os.path.join(save_dir, f"{name_wo_ext}.err")
            
            with open(err_path, 'w') as f:
                f.write(f"图像{base_name}处理失败: {str(e)}")
            
            print(f"已生成错误文件: {err_path}")
    
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch run Omnipose 3D segmentation on a folder of TIFs.")
    parser.add_argument('--input', required=True, help="Path to input folder containing .tif files")
    parser.add_argument('--output', required=True, help="Path to output folder")

    args = parser.parse_args()
    run_omnipose_on_folder(args.input, args.output)
