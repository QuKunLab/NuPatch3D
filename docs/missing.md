# 七、丢细胞检查

丢失细胞检测用于识别预分割结果中遗漏的真实细胞，即荧光图像中存在明显信号，但对应区域未被赋予任何标签的情况。NuPatch3D 基于分水岭算法，以用户指定的种子点为起点自动生成新的细胞标签。相关功能位于插件面板 <kbd>Missing Cell Detection</kbd> 区域。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image23.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 23. Missing Cell Detection 面板</div>
</div>

完成检测后，需点击 <kbd>Interaction</kbd> 区域中的 <kbd>Commit</kbd> 按钮，或按快捷键 <kbd>Shift</kbd>+<kbd>S</kbd>，将修改结果写回全局 <kbd>Labels</kbd> 图层。否则，新生成的标签仅保存在当前局部编辑区域中，不会同步到全局标签图层。有关提交与保存结果的详细说明，请参阅 [保存结果](save.md)。
## 7.1 放置种子点

点击 <kbd>Select Seed Point</kbd>，若当前不存在种子点图层，NuPatch3D 会自动创建 <kbd>Missing-Cell-Seeds</kbd> 图层（黄色 <kbd>Points</kbd>），并进入点选模式。此时应切换至 2D 视图，在疑似漏检细胞的荧光信号中心放置种子点。每个种子点对应一个待检测的细胞候选区域。支持同时放置多个种子点，NuPatch3D 将依次处理。检测完成后，可通过快捷键 <kbd>Shift</kbd>+<kbd>C</kbd> 删除辅助点和相关图层。

## 7.2 设置参数

### Threshold

<kbd>Threshold</kbd> 为前景检测阈值（默认值：500），数值越高保留较强的荧光信号越强。

若检测结果包含较多噪声，可适当提高该值；若遗漏细胞的信号较弱，可适当降低该值。

### Max Distance

<kbd>Max Distance</kbd> 为分水岭最大生长距离（默认值：10 像素），数值越大新标签向外扩展越远。

对于体积较大的细胞，可适当提高该值；对于密集细胞区域，建议保持较小数值以避免误扩张。

## 7.3 执行检测

确认已在 <kbd>Missing-Cell-Seeds</kbd> 图层中放置至少一个种子点，并根据需要调整 <kbd>Threshold</kbd> 和 <kbd>Max Distance</kbd> 参数。

点击 <kbd>Detect Missing Cell</kbd>，NuPatch3D 将根据种子点位置自动执行分水岭分割，并为检测到的新区域分配新的标签 ID。

通常情况下，每个种子点对应一个新标签。由于分水岭结果可能与真实细胞边界存在偏差，建议在检测完成后进一步使用 [边界修复](boundary.md) 对新标签进行精修。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image24.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 24. 种子点放置示例</div>
</div>

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image25.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 25. 丢失细胞检测结果示例</div>
</div>