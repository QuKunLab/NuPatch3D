# 四、细胞邻域提取（Cell Bounding Box Extraction）

插件所有精修操作均围绕局部邻域（Bounding
Box）展开。用户从全局标签中指定目标细胞，裁剪出包含该细胞的局部立方体，后续的分裂、合并、边界修复与手动修正均在此局部区域内完成，避免误改全局其他细胞。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image6.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 6 Cell Bounding Box Extraction面板</div>
</div>

## 4.1 计算细胞中心

在插件面板 Cell Bounding Box Extraction 控制模块，点击 Calculate Cell Centers。插件将为全局标签图中所有非零标签计算三维空间中心坐标，并建立标签索引。

计算完成后，插件会自动根据当前 Label ID 对应细胞的实际直径，并将每个细胞的 Box Size 初始化设置为其直径的 2 倍，以确保裁剪区域既能完整包裹目标细胞，又不过度包含无关邻域。

## 4.2 设定目标标签与裁剪尺寸

在 Label ID 输入框中填入需要编辑的目标标签编号，或通过 Previous / Next 按钮按标签中心列表顺序前后切换。插件支持键盘快捷键快速导航：按 A 键切换到上一个标签，按 D 键切换到下一个标签。可在 Box Size 数值框手动调整裁剪立方体的边长（单位：像素）。

## 4.3 提取局部编辑区域

点击 Extract Bounding Box，插件从全局标签与原始图像中同步裁剪出以目标细胞为中心的局部区域，并在 napari 中生成两个新图层：

• 原图片名-Crop：局部原始图像（Image 类型），作为后续修改的主要参考图像；

• 原图片名-LabelFix：局部可编辑标签（Labels 类型），所有后续精修操作均在此图层上进行。

提取完成后，插件会自动取消 Global View 勾选，将原始全局图层从视图中移除，仅保留局部 LabelFix 与 Crop 图层，防止全局其他细胞干扰局部编辑。此时可利用 napari 基础视图功能旋转、缩放或逐层浏览该局部区域，确认分割质量。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image7.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 7 提取细胞邻域后软件界面</div>
</div>

## 4.4 视图标签过滤

View Labels 输入框中填写需要保留显示的标签编号（以空格分隔），点击 Apply
生效。Apply 执行后会自动激活 Focus 模式：此时仅保留 View Labels
中指定的标签可见，其余标签隐藏；若 View Labels 留空，则默认仅当前 Label
ID 指定的标签可见。

Focus
复选框是一个独立的显示开关------取消勾选即恢复显示全部标签，再次勾选则回到聚焦状态。按快捷键
F
可在聚焦与全部显示之间快速切换，便于在局部分析与整体观察之间灵活跳转。此外，按
Shift + R 可在\"显示全部标签\"与\"仅 View Labels 指定标签\"之间切换，与
Apply 按钮效果等价

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image8.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 8 视图标签过滤后软件界面</div>
</div>

## 4.5 全局视图切换

如需在编辑过程中随时对照全局原始数据，可勾选插件顶部 Settings 区域的
Global View 复选框，原始全局 Image 与 Labels 图层将重新显示于 napari
视图中。再次取消勾选则恢复仅显示局部 LabelFix 与 Crop 图层。

## 4.6 手动修正与原生标注工具

提取局部 LabelFix 图层后，用户可使用 napari 原生的 画笔（Paint）、橡皮擦（Erase）、颜料桶（Fill） 等标注工具对分割结果进行手动微调。这些原生操作与CellReine-3D的算法修复功能完全兼容，可交替使用：例如，先用橡皮擦擦除粘连的两细胞之间的错误桥连体素，将其变为非连通状态，再执行 Connected Components Split（Section 5.4）实现精确分离；或在边界遗漏处用画笔补全细胞轮廓，再执行 Boundary Fix（第七章）进行密度约束的平滑重建。

所有原生标注操作均被纳入插件统一的 Undo / Redo 栈（Section 9.1）与 Commit 提交流（Section 9.2），并完整记录于 JSON 操作日志（Section 9.4）中，可实现体素级回溯与复原。napari 原生标注工具的具体使用方法详见 napari 官方文档。