# 四、欠分割

欠分割是指多个独立细胞被错误标记为同一标签。NuPatch3D 提供三种欠分割修复模式：

* <kbd>Plane</kbd>：基于分割平面的手动分割；
* <kbd>Auto</kbd>：基于 GMM 的自动分割；
* <kbd>Manual</kbd>：手动指定细胞中心的 GMM 分割。

三种模式共用同一组 <kbd>Target Labels</kbd>，并可结合 <kbd>Connected Components Split</kbd> 进行后处理。

在插件面板 <kbd>Cell Boundary Refine</kbd> 的 <kbd>Under-segmentation (Split)</kbd> 区域中，通过 <kbd>Mode</kbd> 下拉框选择分割模式。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image9.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 9. Under-segmentation 面板</div>
</div>

标签修复后，需点击 <kbd>Interaction</kbd> 区域中的 <kbd>Commit</kbd> 按钮，或按快捷键 <kbd>Shift</kbd>+<kbd>S</kbd>，将修改结果写回全局 <kbd>Labels</kbd> 图层。否则，修复后的标签仅保存在当前局部编辑区域中，不会同步到全局标签图层。有关提交与保存结果的详细说明，请参阅 [保存结果](save.md)。

## 4.1 Plane 模式（平面分割）

适用于两个细胞可通过单一平面分离的情况。

### 4.1.1 设置目标标签

在 <kbd>Target Labels</kbd> 输入框中输入需要分割的标签编号，多个标签以空格分隔，例如：

```text
114 514
```

### 4.1.2 创建分割平面

点击 <kbd>Draw a Plane</kbd>。

若当前尚未创建平面基准点，NuPatch3D 会创建 <kbd>Plane Label Splitting-Points</kbd> 图层（蓝色点），并自动进入点选模式。此时应切换至 2D 视图，在目标细胞附近单击一次以确定平面中心。

完成后，NuPatch3D 会自动创建：

* <kbd>Plane Label Splitting-Shapes</kbd>：分割平面及法向量；
* <kbd>Plane-Spherical-Axes</kbd>：三维参考坐标轴。

同时，<kbd>X</kbd>、<kbd>Y</kbd>、<kbd>Z</kbd> 和 <kbd>Phi</kbd>、<kbd>Theta</kbd> 参数会自动同步为当前平面位置和方向。

上述辅助图层仅用于交互定位，可通过快捷键 <kbd>Shift</kbd>+<kbd>C</kbd> 一键清理。

### 4.1.3 调整分割平面

通过以下参数调整平面位置和方向：

* <kbd>X</kbd>、<kbd>Y</kbd>、<kbd>Z</kbd>：平面中心坐标；
* <kbd>Phi</kbd>、<kbd>Theta</kbd>：平面法向量方向。

调整过程中，3D 视图会实时更新平面位置，直至其位于目标细胞的分界处。

### 4.1.4 执行分割

点击 <kbd>Split by Plane</kbd>，NuPatch3D会将平面两侧的体素划分为不同标签。完成后，可在 2D 或 3D 视图中检查分割结果。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image10.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 10. 平面构建与调整</div>
</div>

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image11.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 11. 平面分割结果示例</div>
</div>

## 4.2 Auto 模式（GMM 自动分割）

Auto 模式基于高斯混合模型（GMM）自动识别并分离发生欠分割的细胞，适用于细胞边界较为明显且无需人工指定分割位置的场景。

### 4.2.1 设置算法参数

* <kbd>Sampling Rate</kbd>：体素采样比例（默认值：0.3），用于控制参与 GMM 训练的样本数量。数值越小，运行速度越快；数值越大，结果通常越稳定。
* <kbd>Split Dist</kbd>：分割阈值（默认值：10），细胞直径大于该值就执行分割，反之亦然。
* <kbd>Merge Dist</kbd>：合并阈值（默认值：3），两个细胞间距离小于该值就合并，反之亦然。

### 4.2.2 设置目标标签

在 <kbd>Target Labels</kbd> 输入框中输入需要自动分割的标签编号，多个标签以空格分隔。

若留空，则对当前局部编辑区域（Bounding Box）内的所有非零标签执行自动分割。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image12.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 12. Auto 模式面板</div>
</div>

### 4.2.3 执行自动分割

点击 <kbd>Under-segmentation Fix</kbd>，NuPatch3D 将自动完成聚类分析、细胞中心优化和标签重分配，并为新生成的细胞分配唯一标签 ID，确保不与现有标签冲突。分割完成后，细胞中心会自动更新。

<div style="text-align: center; margin: 2em 0;">
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../images/media/image14.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 13. 自动分割前</div>
  </div>
  <div style="display: inline-block; vertical-align: middle; font-size: 2.5em; color: #888; margin: 0 5px;">→</div>
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../images/media/image13.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 14. 自动分割后</div>
  </div>
</div>

## 4.3 Manual 模式（手动指定中心）

Manual 模式适用于自动分割效果不理想的情况。用户可手动指定细胞中心位置，引导 NuPatch3D 完成分割。

### 4.3.1 设置细胞中心

可通过以下两种方式指定细胞中心：

**方式一：手动输入坐标**

在 <kbd>Coords of Centers</kbd> 输入框中输入细胞中心坐标，格式为：

```text
Z,Y,X
```

多个中心坐标以空格分隔，例如：

```text
10,20,30 15,25,35
```

**方式二：交互式选点**

点击 <kbd>Select Coordinates</kbd>，NuPatch3D 会创建 <kbd>GMM-Coordinates</kbd> 图层，并自动进入点选模式。此时应切换至 2D 视图，在目标细胞中心位置依次点击添加标记点。

选点完成后，NuPatch3D 会自动：

* 将坐标同步至 <kbd>Coords of Centers</kbd>；
* 识别对应标签并填入 <kbd>Target Labels</kbd>。

<kbd>GMM-Coordinates</kbd> 仅用于辅助选点，不参与最终分割计算。完成分割后，可通过快捷键 <kbd>Shift</kbd>+<kbd>C</kbd> 删除该辅助图层。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image15.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 15. Manual 模式选点示例</div>
</div>

### 4.3.2 执行分割

点击 <kbd>Under-segmentation Fix</kbd>，NuPatch3D 将以用户指定的中心坐标作为初始细胞中心，对 <kbd>Target Labels</kbd> 执行分割，并自动更新标签结果。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image16.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 16. Manual 模式分割结果示例</div>
</div>

## 4.4 连通域重标号

若同一标签包含多个不连通区域，可点击 <kbd>Connected Components Split</kbd> 进行处理。

NuPatch3D 会对 <kbd>Target Labels</kbd> 中的每个标签执行三维连通域分析，保留最大连通域的原标签，其余连通域自动分配新的标签 ID，从而解决欠分割。