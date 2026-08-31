# NuPatch3D概述
**NuPatch3D** 是一款用于细胞核分割结果后处理的 **[napari](https://napari.org/)** 插件，旨在修复 Cellpose 等细胞核分割算法产生的常见错误，包括欠分割、过分割、细胞核漏检和边界错误等。NuPatch3D 提供局部区域提取、目标细胞突出显示、编辑日志自动保存、撤销与重做等功能，帮助用户高效、准确地修复分割结果，实现全流程可追溯的编辑与质量控制。此外，NuPatch3D 与 napari 原生标注工具无缝兼容，支持画笔、橡皮擦和填充等操作，使用户能够对分割结果进行体素级精修。


<div style="text-align: center; margin: 2em 0;">
  <div id="bili-wrap" style="position: relative; width: 80%; max-width: 800px; margin: 0 auto; aspect-ratio: 16/9; background: #000;">
    <!-- 自定义封面 -->
    <img id="bili-poster" src="images/media/image4.png" 
         style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; cursor: pointer; z-index: 1;" 
         onclick="loadBili()">
    <!-- 播放按钮 -->
    <div onclick="loadBili()" 
         style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); 
                width: 64px; height: 64px; background: rgba(0,0,0,0.6); border-radius: 50%; 
                cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 2;">
      <svg viewBox="0 0 24 24" width="32" height="32" fill="white"><polygon points="8,5 8,19 19,12"></polygon></svg>
    </div>
  </div>
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">NuPatch3D 视频教程</div>
</div>

<script>
function loadBili() {
  var wrap = document.getElementById('bili-wrap');
  wrap.innerHTML = '<iframe src="//player.bilibili.com/player.html?isOutside=true&aid=117162563930849&bvid=BV13v8Z68EYK&cid=41298560322&p=1" ' +
    'scrolling="no" border="0" frameborder="no" framespacing="0" allowfullscreen="true" ' +
    'style="position: absolute; inset: 0; width: 100%; height: 100%; border: none;"></iframe>';
}
</script>