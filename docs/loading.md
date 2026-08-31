# 三、NuPatch3D 的基本操作

NuPatch3D 的所有编辑操作均围绕局部区域（Bounding Box）开展，以减少周围细胞对目标细胞（ <kbd>Label ID</kbd> 输入框中的编号）的干扰。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image6.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 6. Cell Bounding Box Extraction 面板</div>
</div>

## 3.1 计算细胞中心

在插件面板的 <kbd>Cell Bounding Box Extraction</kbd> 模块中，点击 <kbd>Calculate Cell Centers</kbd>。NuPatch3D 将计算 <kbd>Label Layer</kbd> 中所有非零标签的中心坐标，并建立标签索引。

同时，NuPatch3D 会自动将 <kbd>Box Size</kbd> 初始化为细胞核直径的 2 倍，以确保裁剪区域既能完整包含目标细胞，又尽可能减少无关邻域的干扰。

## 3.2 设定目标细胞标签与裁剪区域大小

目标细胞的标签编号可通过 <kbd>Label ID</kbd> 输入框直接修改，也可通过 <kbd>Previous</kbd> 和 <kbd>Next</kbd> 按钮按标签编号顺序切换。

为提高切换效率，NuPatch3D 提供以下快捷键：

* <kbd>A</kbd>：切换到上一个标签；
* <kbd>D</kbd>：切换到下一个标签。

此外，可通过 <kbd>Box Size</kbd> 输入框手动调整裁剪立方体的边长（单位：像素）。

## 3.3 提取局部编辑区域

点击 <kbd>Extract Bounding Box</kbd> 后，插件将从 <kbd>Image Layer</kbd> 和 <kbd>Label Layer</kbd> 中同步裁剪出以目标细胞为中心、边长为 <kbd>Box Size</kbd>（默认值为目标细胞直径的 2 倍）的立方体区域，并在 napari 中生成以下两个图层：

* <code>原图名-Crop</code>：局部原始图像（<kbd>Image</kbd> 类型），作为后续编辑的参考图像；
* <code>原图名-LabelFix</code>：局部标签图像（<kbd>Labels</kbd> 类型），所有精修操作均在该图层上完成。

提取完成后，插件会自动取消勾选 <kbd>Global View</kbd>，隐藏全局图层，仅保留局部 <kbd>Crop</kbd> 和 <kbd>LabelFix</kbd> 图层。此时可利用 napari 的基础视图功能对局部区域进行旋转、缩放和切片浏览，以评估分割质量。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image7.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 7. 提取局部编辑区域后的效果</div>
</div>

## 3.4 视图标签过滤

在 <kbd>View Labels</kbd> 输入框中输入需要显示的标签编号（多个标签以空格分隔），然后点击 <kbd>Apply</kbd>。

执行后，插件会自动启用 <kbd>Focus</kbd> 模式，仅显示指定标签，其余标签将被隐藏。

若勾选 <kbd>Focus</kbd> 且 <kbd>View Labels</kbd> 为空，则默认仅显示当前 <kbd>Label ID</kbd> 对应的目标细胞。

<kbd>Focus</kbd> 是独立的显示开关：

* 勾选时，仅显示聚焦标签；
* 取消勾选时，恢复显示全部标签。

可通过快捷键 <kbd>F</kbd> 在聚焦视图与全部显示之间快速切换。

此外，快捷键 <kbd>Shift</kbd>+<kbd>R</kbd> 可在“显示全部标签”和“仅显示 View Labels 指定标签”之间切换，其效果与点击 <kbd>Apply</kbd> 按钮相同。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image8.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 8. 视图标签过滤后的界面</div>
</div>

## 3.5 全局视图切换

如需在编辑过程中对照全局数据，可勾选 <kbd>NuPatch3D Settings</kbd> 区域中的 <kbd>Global View</kbd> 复选框。

启用后，全局 <kbd>Image</kbd> 和 <kbd>Labels</kbd> 图层将重新显示在 napari 视图中。取消勾选后，则恢复仅显示局部 <kbd>Crop</kbd> 和 <kbd>LabelFix</kbd> 图层。

## 3.6 清理辅助图层

在执行 Plane 分割、Manual 选点、Missing Cell Detection等操作后，napari 的 <kbd>Layers</kbd> 面板中可能残留辅助图层，例如：

* <kbd>Plane Label Splitting-Points</kbd>
* <kbd>Plane Label Splitting-Shapes</kbd>
* <kbd>Plane-Spherical-Axes</kbd>
* <kbd>GMM-Coordinates</kbd>
* <kbd>Missing-Cell-Seeds</kbd>

有关这些辅助图层的用途，请参阅 [欠分割](under.md)。

点击插件顶部 <kbd>Settings</kbd> 区域中的 <kbd>Remove Aux Layer</kbd> 按钮，或使用快捷键 <kbd>Shift</kbd>+<kbd>C</kbd>，即可一键删除所有由 NuPatch3D 创建的辅助图层，并自动将焦点切换回当前编辑图层，避免影响后续操作。

所有编辑操作——无论是插件算法修复还是 napari 原生标注——均纳入统一的撤销与重做栈中管理，并实时缓存于内存日志。用户可随时回退到任意历史状态，或将阶段性成果提交回全局原始数据，导出为 TIFF 或序列化 JSON 日志以备完整复原。



