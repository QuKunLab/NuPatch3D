# 八、保存与修复

所有编辑操作——无论是插件算法修复还是 napari 原生标注——均纳入统一的撤销与重做栈中管理，并实时缓存于内存日志。用户可随时回退到任意历史状态，或将阶段性成果提交回全局原始数据，导出为 TIFF 或序列化 JSON 日志以备完整复原。

在插件面板 <kbd>Interaction</kbd> 区域操作。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image26.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 26 Interaction 面板</div>
</div>

## 8.1 撤销与重做（Undo / Redo）

点击 <kbd>Undo</kbd> 按钮或按快捷键 <kbd>Shift</kbd>+<kbd>Z</kbd>，撤销上一步操作，标签数据恢复到修改前的状态，同时操作日志同步回退。点击 <kbd>Redo</kbd> 按钮或按快捷键 <kbd>Shift</kbd>+<kbd>B</kbd>，恢复刚刚撤销的操作。撤销与重做栈深度为 10 步，涵盖算法修复、手动涂抹等全部修改类型。

## 8.2 提交更改（Commit）

当局部 <kbd>LabelFix</kbd> 中的编辑达到可保存的阶段性成果时，点击 <kbd>Commit</kbd> 按钮或按快捷键 <kbd>Shift</kbd>+<kbd>S</kbd>。插件执行以下动作：

- 将当前 <kbd>LabelFix</kbd> 中的局部标签数据按 <code>current bounding box</code> 位置写回全局原始 <kbd>Labels</kbd> 图层；
- 自动生成一条 <code>CommitSnapshot</code> 条目，记录该时刻 <code>bounding box</code> 内完整的体素状态、坐标范围、时间及图层映射关系；
- 将本次会话以来缓存的所有中间操作日志（含原生画笔、橡皮擦、颜料桶事件及算法修复记录）与该 Commit 快照一并追加写入 JSON 日志文件；
- 清空内存中的缓存日志，开始新的记录周期；
- 自动重新提取当前 <kbd>Label ID</kbd> 的 <code>bounding box</code>，刷新局部视图以继续下一轮编辑。

**注意**：

- JSON 日志采用追加写入模式，历史记录不会覆盖。
- 每进行一步正确的操作，务必进行 Commit 以保存此次操作。

## 8.3 导出标签（Export Label）

点击 <kbd>Export Label</kbd>，可将当前修改后的标签图层导出为 TIFF 格式。导出时优先保存全局原始标签图层（若已 Commit 写回）。文件名默认在原始图层名后追加 `_refined`，保存目录与当前 JSON 路径所在目录一致；若文件已存在，会弹窗询问是否覆盖。当然也可用 <kbd>Ctrl</kbd>+<kbd>S</kbd> 或 napari 原生的 <kbd>File</kbd> → <kbd>Save Selected Layers</kbd> 实现。

## 8.4 应用 JSON 日志（Apply JSON Log）

当遇到程序异常退出、标签数据意外丢失，或需要完整复现此前的精修流程时，只需利用原始图像与初始预分割标签，配合 JSON 日志即可重建全部工作。点击 <kbd>Apply JSON Log</kbd>，选择本插件生成的 JSON 日志文件。插件按时间戳顺序解析其中所有 <code>CommitSnapshot</code> 条目，校验 <code>bounding box</code> 形状与目标图层兼容性后，将每条快照的体素级标签数据精确写回对应的全局 <kbd>Labels</kbd> 图层。若 JSON 中记录的原图层名与当前 napari 中的图层名不一致，插件会自动按 <code>bounding box</code> 形状与体素维度匹配候选图层，或弹窗供用户手动选择。
