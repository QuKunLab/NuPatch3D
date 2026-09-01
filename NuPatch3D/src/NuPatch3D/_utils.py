from datetime import datetime

import numpy as np


def _parse_commit_snapshot_timestamp(entry):
    ts = entry.get("timestamp")
    if ts is None:
        return None
    if not isinstance(ts, str):
        try:
            ts = str(ts)
        except Exception:
            return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def sort_commit_snapshot_entries_by_timestamp(entries):
    """将 CommitSnapshot 日志条按可解析的 timestamp 升序排列；无时间戳的条保持相对顺序并置于末尾。"""
    indexed = list(enumerate(entries))
    with_ts = [(i, e) for i, e in indexed if _parse_commit_snapshot_timestamp(e) is not None]
    without_ts = [(i, e) for i, e in indexed if _parse_commit_snapshot_timestamp(e) is None]
    with_ts.sort(key=lambda ie: _parse_commit_snapshot_timestamp(ie[1]))
    return [e for _, e in with_ts] + [e for _, e in without_ts]


def commit_safe_volume_shape_from_label_data(label_data):
    """若 label data 为单层 3D 体素数组则返回 shape；list/元组（如金字塔多尺度）或非 3D 则返回 None。"""
    if isinstance(label_data, (list, tuple)):
        return None
    arr = np.asarray(label_data)
    if arr.ndim != 3:
        return None
    return tuple(int(x) for x in arr.shape)


def calculate_centers(label_data):
    """
    Calculate arithmetic mean centers for all labels.
    Returns: dict {label_id: (z, y, x)}
    """
    centers = {}
    # Using scipy.ndimage.center_of_mass is equivalent to arithmetic mean of coordinates
    # But to strictly follow "arithmetic mean of all pixel coordinates" manually:
    from scipy.ndimage import center_of_mass
    
    unique_labels = np.unique(label_data)
    unique_labels = unique_labels[unique_labels > 0]
    
    if len(unique_labels) == 0:
        return {}, []

    # center_of_mass returns tuple of floats
    coms = center_of_mass(np.ones_like(label_data), labels=label_data, index=unique_labels)
    
    # Handle single result vs list
    if not isinstance(coms, list) and not isinstance(coms[0], (list, tuple, np.ndarray)):
        coms = [coms]
        
    sorted_labels = sorted(unique_labels)
    for lbl, com in zip(sorted_labels, coms):
        centers[lbl] = com
        
    return centers, sorted_labels

def get_bbox(center, size, shape):
    """
    Calculate slicing bbox given a center (z,y,x), size (cube side), and image shape.
    """
    cz, cy, cx = center
    r = size // 2
    
    z_min = max(0, int(cz - r))
    z_max = min(shape[0], int(cz + r))
    y_min = max(0, int(cy - r))
    y_max = min(shape[1], int(cy + r))
    x_min = max(0, int(cx - r))
    x_max = min(shape[2], int(cx + r))
    
    return (slice(z_min, z_max), slice(y_min, y_max), slice(x_min, x_max))