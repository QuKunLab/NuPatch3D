# Boundary Fix

Boundary refinement is used to correct deviations between pre-segmented labels and the true cell nucleus contours, such as boundary over-expansion intruding into the background, or boundary shrinkage causing missing cell regions. NuPatch3D re-estimates the cell boundary based on local image intensity information, and generates smooth, connected cell masks through morphological post-processing. The relevant functions are located in the <kbd>Boundary Fix</kbd> region of the <kbd>Cell Boundary Refine</kbd> plugin panel.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image20.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 20. Boundary Fix Panel</div>
</div>

After refinement is completed, you must click the <kbd>Commit</kbd> button in the <kbd>Interaction</kbd> region, or press the shortcut <kbd>Shift</kbd>+<kbd>S</kbd>, to write the modified results back to the global <kbd>Labels</kbd> layer. Otherwise, the repaired labels will only be saved in the current local editing region and will not be synchronized to the global label layer. For detailed instructions on committing and saving results, please refer to [Save](save.md).

## 6.1 Set Parameters

### Percentile

<kbd>Percentile</kbd> controls the intensity threshold during boundary refinement (default: 35).

* Higher values retain fewer bright regions, causing the boundary to tend toward shrinkage;
* Lower values retain larger regions, causing the boundary to tend toward expansion.

In general:

* If the label intrudes into the background region, appropriately increase this value;
* If the label misses the true cell edge, appropriately decrease this value.

### Scaling

<kbd>Scaling</kbd> is the scaling coefficient for the boundary search range (default: 1.00).

* Greater than 1.00: Expands the search range;
* Less than 1.00: Shrinks the search range.

### Use Hull

<kbd>Use Hull</kbd> controls whether to enable the 3D convex hull constraint (enabled by default).

* Checked: Searches for the boundary only near the convex hull of the original label;
* Unchecked: Searches for the boundary within the cell's Bounding Box.

For regularly shaped cells, it is recommended to keep this enabled; if the cell shape is complex or the convex hull constraint performs poorly, try disabling it.

## 6.2 Execute Refinement

Confirm that the label ID to be refined has been entered in <kbd>Label ID</kbd> (multiple labels are not supported).

Adjust as needed: <kbd>Percentile</kbd>; <kbd>Scaling</kbd>; <kbd>Use Hull</kbd>. Then click <kbd>Boundary Fix</kbd>.

NuPatch3D will recalculate the target cell boundary based on the local original image, and automatically update the label results in the <kbd>LabelFix</kbd> layer. The refinement process only affects the target label and its surrounding background region, and will not overwrite neighboring cells.

After refinement is completed, it is recommended to check the boundary fit with the fluorescence signal in the 2D or 3D view. If the result is not ideal, adjust the parameters and execute <kbd>Boundary Fix</kbd> again.

Boundary refinement is usually used in conjunction with napari's brush, eraser, and other tools to achieve more precise results. See [Basic Operations](napari.md) for details.

<div style="text-align: center; margin: 2em 0;">
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../../images/media/image22.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 21. Before Boundary Fix</div>
  </div>
  <div style="display: inline-block; vertical-align: middle; font-size: 2.5em; color: #888; margin: 0 5px;">→</div>
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../../images/media/image21.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 22. After Boundary Fix (combined with brush refinement)</div>
  </div>
</div>
