# 修复Windows上MKL的KMeans内存泄漏问题
# 在导入sklearn之前设置OMP_NUM_THREADS环境变量，避免KMeans内存泄漏导致的卡顿
import os
if 'OMP_NUM_THREADS' not in os.environ:
    os.environ['OMP_NUM_THREADS'] = '2'

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import KNeighborsClassifier
from sklearn.decomposition import PCA
from scipy.spatial import KDTree, ConvexHull, Delaunay
from skimage import measure
from skimage.measure import label
from skimage.morphology import (
    remove_small_holes, remove_small_objects,
    binary_closing, binary_dilation, binary_erosion, ball
)
import math
from scipy.ndimage import uniform_filter, distance_transform_edt
import torch
import torch.nn as nn
import torch.nn.functional as F
from tqdm import tqdm

# ==========================================
# 1. GMM Under-segmentation Fix
# ==========================================

def merge_closest_points_kdtree(points, threshold):
    points = points.tolist()
    while True:
        if len(points) < 2:
            break
        kdtree = KDTree(points)
        distances, indices = kdtree.query(points, k=2)
        # indices[:, 1] is the nearest neighbor (index 0 is self)
        # Handle case where k=2 returns less if points are few, though check above handles <2
        if distances.shape[1] < 2:
            break
            
        min_dist = np.min(distances[:, 1])
        if min_dist > threshold:
            break
        
        min_index = np.argmin(distances[:, 1])
        i, j = min_index, indices[min_index, 1]
        
        # Merge logic
        new_point = (np.array(points[i]) + np.array(points[j])) / 2
        points[i] = new_point.tolist()
        # Remove the one with larger index first to avoid shifting
        idx_to_remove = max(i, j)
        points.pop(idx_to_remove)
        if i != idx_to_remove: # Should be covered, but safety check
             pass # points[i] is already updated
    
    return np.array(points)

def split_point_cloud_based_on_major_axis(points, labels, threshold):
    unique_labels = np.unique(labels)
    new_centers_list = []

    for label in unique_labels:
        class_points = points[labels == label]
        if len(class_points) == 0: continue
        center = np.mean(class_points, axis=0)
        
        if class_points.shape[0] < 10:
            new_centers_list.append(list(center))
            continue

        centered_points = class_points - center
        pca = PCA(n_components=min(3, class_points.shape[0]))
        pca.fit(centered_points)
        
        # PCA components might be less than 3 if points are planar/linear
        if len(pca.explained_variance_) > 0:
            major_axis = pca.components_[0]
            major_length = np.sqrt(pca.explained_variance_[0])
            
            if major_length > threshold:
                shift_distance = major_length / 4
                new_center_1 = center + shift_distance * major_axis
                new_center_2 = center - shift_distance * major_axis
                new_centers_list.append(list(new_center_1))
                new_centers_list.append(list(new_center_2))
            else:
                new_centers_list.append(list(center))
        else:
            new_centers_list.append(list(center))

    return new_centers_list

def merge_by_gaussian(X, mean_new, merge_threshold=8):
    stop_loop = False
    while stop_loop is False:
        num_gaussian_old = mean_new.shape[0]
        if num_gaussian_old == 0: break
        
        gmm = GaussianMixture(n_components=num_gaussian_old, 
                            covariance_type='full', means_init=mean_new, weights_init=None)
        try:
            gmm.fit(X)
        except ValueError:
            # Fallback if GMM fails (e.g. too few points)
            return np.zeros(X.shape[0], dtype=int), mean_new, None

        mean_new = merge_closest_points_kdtree(gmm.means_, threshold=merge_threshold)
        num_gaussian = mean_new.shape[0]
        stop_loop = (num_gaussian == num_gaussian_old)

    label_new = gmm.predict(X)
    return label_new, gmm.means_, gmm.covariances_

def split_gaussian(X, label, split_threshold=20):
    new_centers_dict = split_point_cloud_based_on_major_axis(X, label, split_threshold)
    if not new_centers_dict:
        return label, None, None
        
    gmm = GaussianMixture(n_components=len(new_centers_dict), 
                            covariance_type='full', 
                            means_init=new_centers_dict, weights_init=None)
    gmm.fit(X)
    label_new = gmm.predict(X)
    return label_new, gmm.means_, gmm.covariances_

def sample_points_by_label(points, labels, ratio=0.2, random_seed=42):
    if random_seed is not None:
        np.random.seed(random_seed)
    unique_labels = np.unique(labels)
    sampled_points = []
    sampled_labels = []

    for lbl in unique_labels:
        idx = np.where(labels == lbl)[0]
        if len(idx) == 0: continue
        sample_size = max(1, int(len(idx) * ratio)) # Ensure at least 1 point
        sampled_idx = np.random.choice(idx, size=sample_size, replace=False)
        sampled_points.append(points[sampled_idx])
        sampled_labels.append(labels[sampled_idx])

    if not sampled_points:
        return np.array([]), np.array([])
    return np.vstack(sampled_points), np.hstack(sampled_labels)

def run_gmm_fix(
    label_img,
    merge_thresh,
    split_thresh,
    sampling_ratio,
    manual_centers=None,
    start_new_id=None,
    target_labels=None,
):
    """
    GMM 修复入口函数。

    参数
    ----
    label_img : np.ndarray
        局部 label 图 (bbox 内)。
    merge_thresh : float
        GMM 高斯合并阈值。
    split_thresh : float
        GMM 基于主轴长度的分裂阈值。
    sampling_ratio : float
        采样比例。
    manual_centers : list[[z,y,x]] or None
        手动模式下的初始中心。
    start_new_id : int or None
        新标签 ID 的起始值，用于避免与原图中其他区域 label 冲突。
    target_labels : list[int] or None
        仅对这些 label 做重分割，其余 label 不修改，仅作为参考。
    """
    cell_label = label_img.copy()

    # # 所有非背景像素位置
    # positions_tuple_all = np.where(cell_label > 0)
    # 这显然不行，不是target_labels的区域绝对不能修改也不能采样
    
    # Update 1207：根据 target_labels 确定采样区域
    if target_labels is not None:
        target_labels = np.array(target_labels, dtype=label_img.dtype)
        # 严格只从 target_labels 对应的区域采样
        mask_target = np.isin(cell_label, target_labels)
        positions_tuple_all = np.where(mask_target)
    else:
        # 所有非背景像素位置
        positions_tuple_all = np.where(cell_label > 0)
        
    if len(positions_tuple_all[0]) == 0:
        return cell_label

    positions_all = np.stack(positions_tuple_all, axis=-1)
    label_original_all = cell_label[positions_tuple_all]

    # 采样：按原始标签分层采样
    sampled_positions, positions_labels = sample_points_by_label(
        positions_all, label_original_all, ratio=sampling_ratio
    )
    if len(sampled_positions) == 0:
        return cell_label

    # --- GMM / 聚类 ---
    if manual_centers is not None and len(manual_centers) > 0:
        # 手动模式
        centroids = np.array(manual_centers)
        gmm = GaussianMixture(
            n_components=len(centroids),
            covariance_type="full",
            means_init=centroids,
            weights_init=None,
        )
        gmm.fit(sampled_positions)
        label_temp = gmm.predict(sampled_positions)  #0..K-1
    else:
        df = pd.DataFrame(
            sampled_positions, columns=[f"x{i}" for i in range(sampled_positions.shape[1])]
        )
        df["label"] = positions_labels
        centroids = df.groupby("label").mean().values

        # 合并
        label_temp, centor, _ = merge_by_gaussian(
            sampled_positions, centroids, merge_threshold=merge_thresh
        )
        # 分裂
        label_temp, centor, _ = split_gaussian(
            sampled_positions, label_temp, split_threshold=split_thresh
        )

    # --- 映射：簇索引 -> 真实 label ID（兼顾 merge / split） ---
    if start_new_id is None:
        start_new_id = np.max(label_img) + 1

    unique_clusters = np.unique(label_temp)
    cluster_info = []
    for cluster_idx in unique_clusters:
        mask = label_temp == cluster_idx
        original_ids_in_cluster = positions_labels[mask]
        original_ids_in_cluster = original_ids_in_cluster[original_ids_in_cluster > 0]

        target_id = start_new_id
        if len(original_ids_in_cluster) > 0:
            target_id = np.min(original_ids_in_cluster)

        cluster_info.append(
            {"cluster_idx": cluster_idx, "target_id": target_id, "count": np.sum(mask)}
        )

    # 解决“多个簇想继承同一个原始 ID”的冲突
    cluster_info.sort(key=lambda x: x["count"], reverse=True)

    final_mapping = {}
    assigned_ids = set()
    current_new_id = start_new_id

    for info in cluster_info:
        c_idx = info["cluster_idx"]
        t_id = info["target_id"]
        if t_id in assigned_ids:
            final_mapping[c_idx] = current_new_id
            current_new_id += 1
        else:
            final_mapping[c_idx] = t_id
            if t_id < start_new_id:
                assigned_ids.add(t_id)
            else:
                current_new_id = max(current_new_id, t_id + 1)

    mapped_labels = np.array([final_mapping[l] for l in label_temp])

    # --- 训练 KNN ---
    # 修复：不使用n_jobs=-1，避免多进程内存泄漏
    knn = KNeighborsClassifier(n_neighbors=5, weights="distance", n_jobs=1)
    knn.fit(sampled_positions, mapped_labels)

    try:
        # --- 仅对指定 target_labels 区域进行重写 ---
        if target_labels is None:
            # 原行为：所有非零像素都重写
            y_pred_all = knn.predict(positions_all)
            cell_label[positions_tuple_all] = y_pred_all
        else:
            target_labels = np.array(target_labels, dtype=label_img.dtype)
            mask_target = np.isin(cell_label, target_labels)
            positions_tuple_t = np.where(mask_target)
            if len(positions_tuple_t[0]) == 0:
                return cell_label

            positions_t = np.stack(positions_tuple_t, axis=-1)
            y_pred_t = knn.predict(positions_t)
            cell_label[positions_tuple_t] = y_pred_t
    finally:
        # 显式删除KNN对象，释放内存
        del knn

    return cell_label


def split_target_labels_by_connected_components(
    label_img,
    target_labels,
    start_new_id=None,
):
    """
    仅针对 target_labels 执行连通域分析并重标号。

    规则：
    - 非 target labels 与背景 0 保持不变；
    - 每个 target label 若有多个连通域，保留最大连通域为原标签；
      其余连通域按递增新 ID 赋值，避免冲突。

    返回
    ----
    new_label_img : np.ndarray
        重标号后的标签图。
    stats : dict
        统计信息，包含总新增标签数与每个目标标签的连通域信息。
    """
    cell_label = label_img.copy()

    if target_labels is None:
        return cell_label, {"total_new_labels": 0, "per_label": {}}

    target_labels = [int(v) for v in target_labels if int(v) != 0]
    if len(target_labels) == 0:
        return cell_label, {"total_new_labels": 0, "per_label": {}}

    if start_new_id is None:
        start_new_id = int(np.max(cell_label)) + 1

    next_id = int(start_new_id)
    total_new_labels = 0
    per_label = {}

    for old_label in target_labels:
        mask = (cell_label == old_label)
        voxel_count = int(np.count_nonzero(mask))
        if voxel_count == 0:
            per_label[old_label] = {
                "num_components": 0,
                "new_labels_created": 0,
                "kept_label": int(old_label),
                "created_labels": [],
            }
            continue

        labeled_mask, num_components = label(mask, return_num=True)
        num_components = int(num_components)

        if num_components <= 1:
            per_label[old_label] = {
                "num_components": num_components,
                "new_labels_created": 0,
                "kept_label": int(old_label),
                "created_labels": [],
            }
            continue

        # 保留最大连通域为原标签，其他连通域依次分配新标签。
        # 例如：原始标签为 1，全局最大标签为 100，若共有 3 个连通域，
        # 则结果应为 1, 101, 102。
        component_ids, counts = np.unique(
            labeled_mask[labeled_mask > 0], return_counts=True
        )

        # 稳定选择“保留原标签”的连通域：
        # 1) 优先体素数最大的；
        # 2) 若体素数相同，优先 component id 更小的，保证结果稳定。
        order = np.lexsort((component_ids, -counts))
        sorted_component_ids = component_ids[order]
        keep_component = int(sorted_component_ids[0])
        created_labels = []

        for comp_id in sorted_component_ids:
            comp_id = int(comp_id)
            if comp_id == keep_component:
                continue
            comp_mask = (labeled_mask == comp_id)
            cell_label[comp_mask] = next_id
            created_labels.append(int(next_id))
            next_id += 1
            total_new_labels += 1

        per_label[old_label] = {
            "num_components": num_components,
            "new_labels_created": len(created_labels),
            "kept_label": int(old_label),
            "created_labels": created_labels,
        }

    stats = {
        "total_new_labels": int(total_new_labels),
        "start_new_id": int(start_new_id),
        "next_available_id": int(next_id),
        "per_label": per_label,
    }
    return cell_label, stats

# ==========================================
# 2. Boundary Fix - Speed (Morphology)
# ==========================================


def _allowed_growth_mask(volume_ref, target_label, bbox):
    """
    bbox 内允许 target_label 占据的区域：
    - 原 target_label 区域
    - 背景区域（0）
    其它细胞区域一律禁止侵入。
    """
    crop = volume_ref[bbox]
    return np.logical_or(crop == 0, crop == target_label)


def extract_label_volume(
    label_volume,
    density_volume,
    target_label,
    percentile,
    box_scaling: float = 1.0,
    use_hull: bool = True,
    blocking_volume=None,
):
    """
    从 label_volume 中提取 target_label 的区域，在可选 3D 凸包 ROI 内做阈值与后处理。
    若提供 blocking_volume，则 target_label 只能在：
    - 原 target 区域
    - 背景区域（0）
    内扩张，禁止覆盖其它细胞。
    """
    coords = np.where(label_volume == target_label)
    if len(coords[0]) == 0:
        print('len(coords[0]) == 0')
        return None

    # ---- 1) 计算 bbox，并按 box_scaling 缩放后裁剪至体数据范围 ----
    zmin, ymin, xmin = np.min(coords, axis=1)
    zmax, ymax, xmax = np.max(coords, axis=1) + 1

    dz = zmax - zmin
    dy = ymax - ymin
    dx = xmax - xmin
    zc = 0.5 * (zmax + zmin)
    yc = 0.5 * (ymax + ymin)
    xc = 0.5 * (xmax + xmin)

    xmin = math.floor(xc - 0.5 * box_scaling * dx)
    xmax = math.ceil(xc + 0.5 * box_scaling * dx)
    ymin = math.floor(yc - 0.5 * box_scaling * dy)
    ymax = math.ceil(yc + 0.5 * box_scaling * dy)
    zmin = math.floor(zc - 0.5 * box_scaling * dz)
    zmax = math.ceil(zc + 0.5 * box_scaling * dz)

    Z, Y, X = label_volume.shape
    zmin = max(0, zmin)
    ymin = max(0, ymin)
    xmin = max(0, xmin)
    zmax = min(Z, zmax)
    ymax = min(Y, ymax)
    xmax = min(X, xmax)
    if not (zmin < zmax and ymin < ymax and xmin < xmax):
        print('Invalid bbox after scaling/clipping.')
        return None

    bbox = (slice(zmin, zmax), slice(ymin, ymax), slice(xmin, xmax))
    crop_density = density_volume[bbox]
    volume_ref = blocking_volume if blocking_volume is not None else label_volume
    allowed_mask = _allowed_growth_mask(volume_ref, target_label, bbox)

    # ---- 2) ROI：凸包掩膜（或退化为整个 bbox）----
    if use_hull:
        zi, yi, xi = coords
        inside_bbox = (
            (zi >= zmin) & (zi < zmax) &
            (yi >= ymin) & (yi < ymax) &
            (xi >= xmin) & (xi < xmax)
        )
        if not np.any(inside_bbox):
            print("No target_label voxels inside scaled bbox.")
            return None

        pts = np.stack([xi[inside_bbox], yi[inside_bbox], zi[inside_bbox]], axis=1)

        hull_mask = None
        if pts.shape[0] >= 4:
            try:
                hull = ConvexHull(pts)
                hull_verts = pts[hull.vertices]
                delaunay = Delaunay(hull_verts)

                zz, yy, xx = np.mgrid[zmin:zmax, ymin:ymax, xmin:xmax]
                grid_pts = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1)
                inside = delaunay.find_simplex(grid_pts) >= 0
                hull_mask = inside.reshape((zmax - zmin, ymax - ymin, xmax - xmin))
            except Exception as e:
                print(f"ConvexHull failed: {e}; fallback to bbox.")
                hull_mask = None

        if hull_mask is None:
            hull_mask = np.ones_like(crop_density, dtype=bool)
            use_hull_effective = False
        else:
            use_hull_effective = True
    else:
        hull_mask = np.ones_like(crop_density, dtype=bool)
        use_hull_effective = False

    # ---- 2.1) 按 box_scaling 对“凸包掩膜”做等比例膨胀/腐蚀（仅当确实使用了凸包）----
    if use_hull_effective and (box_scaling != 1.0):
        nz, ny, nx = hull_mask.shape
        r = abs(box_scaling - 1.0) * min(nz, ny, nx) / 2.0
        r_vox = max(1, int(round(r)))

        if box_scaling > 1.0:
            dist_out = distance_transform_edt(~hull_mask)
            hull_mask = np.logical_or(hull_mask, dist_out <= r_vox)
        else:
            dist_in = distance_transform_edt(hull_mask)
            hull_mask = dist_in > r_vox

    # ---- 3) 仅在 ROI（hull_mask）与允许扩张区域内做阈值筛选 ----
    roi_mask = np.logical_and(hull_mask, allowed_mask)
    valid_vals = crop_density[np.logical_and(roi_mask, crop_density > 0)]

    for p in [percentile, 50, 25]:
        try:
            if valid_vals.size == 0:
                raise ValueError("No positive voxels inside ROI.")

            thresh = np.percentile(valid_vals, p) * 0.9
            binary_mask = np.logical_and(crop_density > thresh, roi_mask)

            labeled_mask = label(binary_mask)
            if labeled_mask.max() == 0:
                continue

            counts = np.bincount(labeled_mask.ravel())
            counts[0] = 0
            if counts.sum() == 0:
                continue

            max_region = np.argmax(counts)
            region_mask = (labeled_mask == max_region)

            selem = ball(2)
            region_mask = binary_closing(region_mask, selem)
            region_mask = binary_dilation(region_mask, selem)
            region_mask = binary_erosion(region_mask, selem)
            region_mask = remove_small_holes(region_mask, area_threshold=100)
            region_mask = remove_small_objects(region_mask, min_size=100)

            # 二次裁剪回 allowed_mask，并只保留最大连通域，防止跨到其它细胞上
            region_mask = np.logical_and(region_mask, allowed_mask)
            labeled_region = label(region_mask)
            if labeled_region.max() == 0:
                continue
            counts_region = np.bincount(labeled_region.ravel())
            counts_region[0] = 0
            if counts_region.sum() == 0:
                continue
            region_mask = labeled_region == np.argmax(counts_region)

            label_volume_new = label_volume.copy()
            label_volume_new[label_volume_new == target_label] = 0
            ing = label_volume_new[bbox]
            ing[np.logical_and(region_mask, ing == 0)] = target_label
            label_volume_new[bbox] = ing

            return bbox, label_volume_new
        except Exception:
            continue

    print('No fit percentile')
    return None


def run_boundary_fix_fast(
    label_vol,
    density_vol,
    filter_size: int = 3,
    percentile: float = 80,
    target_labels=None,
    box_scaling: float = 1.0,
    use_hull: bool = True,
    blocking_volume=None,
):

    print(f"[INFO] Loaded label shape: {label_vol.shape}, density shape: {density_vol.shape}")

    # 均值滤波
    print(f"[INFO] Applying uniform filter with size = {filter_size}")
    smoothed_density = uniform_filter(density_vol.astype(np.float32), size=filter_size)

    if target_labels is None or len(target_labels) == 0:
        raise ValueError(
            "run_boundary_fix_fast: target_labels 必须为非空列表；"
            "不再支持 None 表示「修复体数据中所有标签」，以避免误改未选中的实例。"
        )

    blocking_ref = np.asarray(blocking_volume).copy() if blocking_volume is not None else np.asarray(label_vol).copy()

    for i, label_id in enumerate(target_labels):
        result = extract_label_volume(
            label_vol,
            smoothed_density,
            label_id,
            percentile,
            box_scaling=box_scaling,
            use_hull=use_hull,
            blocking_volume=blocking_ref,
        )
        if result is not None:
            bbox, label_vol = result
            blocking_ref = np.asarray(label_vol).copy()
        else:
            print("extract_label_volume function occured errors!")

    return label_vol

# ==========================================
# 3. Boundary Fix - Accuracy (LocalNet)
# ==========================================

def embedding(coord, freq):
    if freq <= 0:
        return coord
    output = []
    freq_bands = 2. ** torch.linspace(0., freq - 1, steps=freq)
    for freq in freq_bands:
        output.append(torch.sin(freq * coord))
        output.append(torch.cos(freq * coord))
    return torch.cat(output, dim=-1)  # B*N*embed_input

# Local Neural Net
class LocalNet(nn.Module):
    def __init__(self, in_features, hidden_features, hidden_layers, freq=5, noise_std=0.01):
        super().__init__()
        embed_input = 2*in_features*freq if freq > 0 else in_features  # not use fourier positional encode if freq<=0
        skip_layer = hidden_layers // 2     # skip connection
        self.option = (freq, skip_layer, noise_std)
        self.net = nn.ModuleList([nn.Linear(embed_input, hidden_features)]
                                 + [nn.Linear(hidden_features, hidden_features) if i != skip_layer
                                    else nn.Linear(hidden_features + embed_input, hidden_features)
                                    for i in range(1, hidden_layers)])
        self.density = nn.Linear(hidden_features, 1)  # output occupancy value

    def set_noise(self, coord):
        if self.option[2] > 0 and self.training:
            return coord + torch.randn_like(coord) * self.option[2]
        else:
            return coord

    def forward(self, coord):
        embed_input = embedding(coord, self.option[0])
        h = embed_input
        for i, net in enumerate(self.net):
            h = F.relu(net(h))
            if i == self.option[1]-1:
                h = torch.cat([embed_input, h], -1)
        density = torch.abs(self.set_noise(self.density(h)))  # B*N*1
        return density

#          用局部 LocalNet 绘制指定尺寸密度场
def drawing_local(localnet, bbox_shape, device="cuda", chunk=500000):
    """
    bbox_shape = (dz, dy, dx)
    生成 density volume (dz, dy, dx)，中心对齐
    """
    dz, dy, dx = bbox_shape
    localnet.eval().to(device)

    try:
        # 物理坐标全部用 [-1,1] 归一化
        z = torch.linspace(-1, 1, dz, device=device)
        y = torch.linspace(-1, 1, dy, device=device)
        x = torch.linspace(-1, 1, dx, device=device)

        zz, yy, xx = torch.meshgrid(z, y, x, indexing='ij')
        coords = torch.stack([xx, yy, zz], dim=-1).reshape(-1, 3)

        density = torch.zeros(coords.shape[0], device=device)

        with torch.no_grad():
            for start in range(0, coords.shape[0], chunk):
                end = start + chunk
                batch = coords[start:end]
                density[start:end] = localnet(batch).squeeze()

        result = density.reshape(dz, dy, dx).cpu().numpy()
    finally:
        # 显式释放GPU张量，清理CUDA缓存
        if 'z' in locals():
            del z, y, x, zz, yy, xx, coords, density
        if device == "cuda":
            torch.cuda.empty_cache()  # 清理CUDA缓存
    
    return result

def train_localnet(local_patch, iters=200, device="cuda"):
    """
    local_patch: (dz, dy, dx) 归一化 0~1
    """
    dz, dy, dx = local_patch.shape

    # 构造 LocalNet
    net = LocalNet(in_features=3, hidden_features=128, hidden_layers=4, freq=4).to(device)
    optim = torch.optim.Adam(net.parameters(), lr=1e-3)

    # 构建训练坐标
    z = torch.linspace(-1, 1, dz, device=device)
    y = torch.linspace(-1, 1, dy, device=device)
    x = torch.linspace(-1, 1, dx, device=device)
    zz, yy, xx = torch.meshgrid(z, y, x, indexing="ij")
    coords = torch.stack([xx, yy, zz], dim=-1).reshape(-1, 3)
    print(coords.shape)

    gt = torch.tensor(local_patch.reshape(-1), dtype=torch.float32, device=device)

    # 随机抽样（避免 OOM）
    N = coords.shape[0]
    sample_N = min(200000, N)

    try:
        for _ in tqdm(range(iters), desc="Training LocalNet"):
            idx = torch.randint(0, N, (sample_N,), device=device)
            pred = net(coords[idx]).squeeze()
            loss = F.l1_loss(pred, gt[idx])

            optim.zero_grad()
            loss.backward()
            optim.step()
    finally:
        # 显式释放训练张量和优化器，清理CUDA缓存
        del z, y, x, zz, yy, xx, coords, gt, optim
        if device == "cuda":
            torch.cuda.empty_cache()  # 清理CUDA缓存

    return net

#         提取 label 的 bbox + 局部 LocalNet 重建
def process_single_label(label_vol, img_vol, target_label, percentile, device="cuda",box_scaling=1.0):
    """
    label_vol: 原 labels
    img_vol: 用于训练的密度/亮度图像 (假定同分辨率)
    target_label: 当前 label id
    """

    # -------- 提取 bounding box ---------
    coords = np.where(label_vol == target_label)
    if len(coords[0]) == 0:
        return None

    zmin, ymin, xmin = np.min(coords, axis=1)
    zmax, ymax, xmax = np.max(coords, axis=1) + 1

    if box_scaling>1:
        dz = zmax - zmin
        dy = ymax - ymin
        dx = xmax - xmin
        zmedian = 0.5*(zmax + zmin)
        ymedian = 0.5*(ymax + ymin)
        xmedian = 0.5*(xmax + xmin)
        xmin = math.floor(xmedian - 0.5*box_scaling*dx)
        xmax = math.ceil(xmedian + 0.5*box_scaling*dx)
        ymin = math.floor(ymedian - 0.5*box_scaling*dy)
        ymax = math.ceil(ymedian + 0.5*box_scaling*dy)
        zmin = math.floor(zmedian - 0.5*box_scaling*dz)
        zmax = math.ceil(zmedian + 0.5*box_scaling*dz)

    bbox = (slice(zmin, zmax), slice(ymin, ymax), slice(xmin, xmax))

    local_patch = img_vol[bbox].astype(np.float32)
    if local_patch.max() > 0:
        local_patch = local_patch / local_patch.max()

    net = None
    try:
        # -------- 局部训练 LocalNet --------
        net = train_localnet(local_patch, iters=300, device=device)

        # -------- 生成局部密度场 --------
        pred_density = drawing_local(net, local_patch.shape, device=device)

        # -------- 阈值 → 等值面 → 形态学修正 --------
        thresh = np.percentile(pred_density[pred_density > 0], percentile) * 0.9
        mask = pred_density > thresh

        # 后处理
        se = ball(3)
        mask = binary_closing(mask, se)
        mask = binary_dilation(mask, se)
        mask = binary_erosion(mask, se)
        mask = remove_small_objects(mask, 50)
        mask = remove_small_holes(mask, 100)

        label_volume_new = label_vol.copy()
        label_volume_new[label_volume_new==target_label] = 0
        ing = label_volume_new[bbox]
        ing[np.logical_and(mask.astype(np.uint16), ing==0)] = target_label
        label_volume_new[bbox] = ing

        return bbox, label_volume_new
    finally:
        # 显式删除网络模型，清理CUDA缓存
        if net is not None:
            del net
        if device == "cuda":
            torch.cuda.empty_cache()  # 清理CUDA缓存

def run_boundary_fix_accurate(label_vol, img_vol,target_label, percentile, box_scaling=1.0):

    device = "cuda" if torch.cuda.is_available() else "cpu"
    output = np.zeros_like(label_vol, dtype=np.uint16)

    try:
        for i, lab in enumerate(target_label):
            result = process_single_label(label_vol, img_vol, lab, percentile, device=device, box_scaling=box_scaling)
            if result is not None:
                bbox, label_vol = result
            else:
               print("extract_label_volume function occured errors!")
            
            # 每次迭代后清理CUDA缓存，防止内存累积
            if device == "cuda":
                torch.cuda.empty_cache()
    finally:
        # 最终清理CUDA缓存
        if device == "cuda":
            torch.cuda.empty_cache()

    return label_vol  