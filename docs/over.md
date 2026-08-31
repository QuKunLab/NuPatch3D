# 五、过分割

过分割是指同一细胞被错误分割为多个独立标签。NuPatch3D 提供标签合并功能，可将多个标签合并为一个标签，也可直接删除不存在的细胞的标签。 相关操作位于插件面板 <kbd>Cell Boundary Refine</kbd> 的 <kbd>Over-segmentation (Merge)</kbd> 区域。

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../images/media/image17.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 17. 过分割合并面板</div>
</div>

<div style="text-align: center; margin: 2em 0;">
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../images/media/image19.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 18. 合并前示例</div>
  </div>
  <div style="display: inline-block; vertical-align: middle; font-size: 2.5em; color: #888; margin: 0 5px;">→</div>
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../images/media/image18.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">图 19. 合并后示例</div>
  </div>
</div>

标签合并后，需点击 <kbd>Interaction</kbd> 区域中的 <kbd>Commit</kbd> 按钮，或按快捷键 <kbd>Shift</kbd>+<kbd>S</kbd>，将修改结果写回全局 <kbd>Labels</kbd> 图层。否则，修复后的标签仅保存在当前局部编辑区域中，不会同步到全局标签图层。有关提交与保存结果的详细说明，请参阅 [保存结果](save.md)。

## 5.1 多标签合并

在 <kbd>Label IDs to Merge</kbd> 输入框中输入需要合并的标签编号，多个标签以空格分隔，例如：

```text
10 12 15
```
点击 <kbd>Label Merge</kbd> 后，NuPatch3D 会将所有选中标签合并为同一个标签，并保留其中数值最小的标签 ID。

## 5.2 删除不存在的细胞标签

若 <kbd>Label IDs to Merge</kbd> 中仅输入一个非零标签编号，例如：

```text
10
```

点击 <kbd>Label Merge</kbd> 后，NuPatch3D 会将该标签对应的所有体素置为背景（标签值 0），相当于从分割结果中删除该区域。

