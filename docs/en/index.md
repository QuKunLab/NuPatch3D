# NuPatch3D Overview

**NuPatch3D** is a **[napari](https://napari.org/)** plugin designed for post-processing cell nucleus segmentation results. It targets common errors produced by algorithms such as Cellpose, including under-segmentation, over-segmentation, missing nuclei, and boundary inaccuracies. NuPatch3D provides local region extraction, target cell highlighting, automatic editing log saving, undo/redo functionality, and more—enabling users to efficiently and accurately refine segmentation results while maintaining full traceability throughout the editing and quality-control workflow. Furthermore, NuPatch3D seamlessly integrates with napari's native annotation tools, supporting brush, eraser, and fill operations for voxel-level manual refinement.


<div style="text-align: center; margin: 2em 0;">
  <div id="video-wrap" style="position: relative; width: 80%; max-width: 800px; margin: 0 auto; aspect-ratio: 16/9; background: #000;">
    <img id="video-poster" src="https://img.youtube.com/vi/HgknF05EYHs/0.jpg" 
         style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; cursor: pointer; z-index: 1;" 
         onclick="loadVideo()">
    <div onclick="loadVideo()" 
         style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); 
                width: 64px; height: 64px; background: rgba(0,0,0,0.6); border-radius: 50%; 
                cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 2;">
      <svg viewBox="0 0 24 24" width="32" height="32" fill="white"><polygon points="8,5 8,19 19,12"></polygon></svg>
    </div>
  </div>
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">NuPatch3D Video Tutorial</div>
</div>

<script>
function loadVideo() {
  var wrap = document.getElementById('video-wrap');
  wrap.innerHTML = '<iframe src="https://www.youtube.com/embed/HgknF05EYHs?autoplay=1&rel=0" ' +
    'frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" ' +
    'allowfullscreen ' +
    'style="position: absolute; inset: 0; width: 100%; height: 100%; border: none;"></iframe>';
}
</script>
