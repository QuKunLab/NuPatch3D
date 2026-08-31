# 八、保存结果

## 8.1 提交更改（Commit）

当局部 <kbd>LabelFix</kbd> 图层中的编辑结果达到阶段性完成状态时，可点击 <kbd>Interaction</kbd> 区域中的 <kbd>Commit</kbd> 按钮，或按快捷键 <kbd>Shift</kbd>+<kbd>S</kbd> 提交当前更改。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image26.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 26. Interaction 面板</div>
</div>

点击<kbd>Commit</kbd> 按钮后，NuPatch3D 将执行以下操作：

* 将当前 <kbd>LabelFix</kbd> 中的局部标签数据写回全局 <kbd>Labels</kbd> 图层；
* 在 JSON 日志中记录当前局部区域的体素状态、坐标范围、时间和图层映射关系；
* 保存本次提交前的中间操作记录，包括画笔、橡皮擦、填充以及NuPatch3D的修复操作；
* 清空当前缓存日志，并开始新的记录周期；
* 重新提取当前 <kbd>Label ID</kbd> 对应的局部区域，刷新局部视图。

> **注意**
>
> * JSON 日志采用追加写入模式，历史记录不会被覆盖。
> * 建议在完成一次有效编辑后及时执行 <kbd>Commit</kbd>，以保存当前阶段的结果。

## 8.2 导出修复后的细胞标签
点击 <kbd>Interaction</kbd> 区域中的 <kbd>Export Label</kbd>，可将当前修复后的标签图层导出为 TIFF 格式。默认情况下，导出文件名会在原始文件名后追加 `_refined` 后缀，保存目录与当前 JSON 日志文件所在目录一致。若目标文件已存在，系统会弹出确认对话框，询问是否覆盖原文件。

除使用 <kbd>Export Label</kbd> 外，也可通过以下方式保存标签结果：

* <kbd>Ctrl</kbd>+<kbd>S</kbd>（或 macOS 上的 <kbd>⌘</kbd>+<kbd>S</kbd>）；
* napari 菜单栏 <kbd>File</kbd> → <kbd>Save Selected Layers</kbd>。

