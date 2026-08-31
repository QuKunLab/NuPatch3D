# Under-segmentation

Under-segmentation refers to multiple independent cells being incorrectly labeled with the same label. NuPatch3D provides three under-segmentation repair modes:

* <kbd>Plane</kbd>: Manual splitting based on a segmentation plane;
* <kbd>Auto</kbd>: Automatic splitting based on GMM;
* <kbd>Manual</kbd>: GMM splitting with manually specified cell centers.

The three modes share the same set of <kbd>Target Labels</kbd>, and can be combined with <kbd>Connected Components Split</kbd> for post-processing.

In the <kbd>Cell Boundary Refine</kbd> region of the plugin panel, select the splitting mode via the <kbd>Mode</kbd> drop-down box in the <kbd>Under-segmentation (Split)</kbd> area.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image9.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 9. Under-segmentation Panel</div>
</div>

After label repair, you must click the <kbd>Commit</kbd> button in the <kbd>Interaction</kbd> region, or press the shortcut <kbd>Shift</kbd>+<kbd>S</kbd>, to write the modified results back to the global <kbd>Labels</kbd> layer. Otherwise, the repaired labels will only be saved in the current local editing region and will not be synchronized to the global label layer. For detailed instructions on committing and saving results, please refer to [Save](save.md).

## 4.1 Plane Mode (Plane Splitting)

Applicable when two cells can be separated by a single plane.

### 4.1.1 Set Target Labels

Enter the label IDs to be split in the <kbd>Target Labels</kbd> input box. Multiple labels are separated by spaces, for example:

```text
114 514
```

### 4.1.2 Create Splitting Plane

Click <kbd>Draw a Plane</kbd>.

If no plane reference point has been created yet, NuPatch3D will create the <kbd>Plane Label Splitting-Points</kbd> layer (blue points) and automatically enter point selection mode. At this point, switch to the 2D view and click once near the target cell to determine the plane center.

After completion, NuPatch3D will automatically create:

* <kbd>Plane Label Splitting-Shapes</kbd>: The splitting plane and normal vector;
* <kbd>Plane-Spherical-Axes</kbd>: 3D reference coordinate axes.

At the same time, the <kbd>X</kbd>, <kbd>Y</kbd>, <kbd>Z</kbd> and <kbd>Phi</kbd>, <kbd>Theta</kbd> parameters will be automatically synchronized to the current plane position and orientation.

The above auxiliary layers are only used for interactive positioning and can be cleaned up with the shortcut <kbd>Shift</kbd>+<kbd>C</kbd>.

### 4.1.3 Adjust the Splitting Plane

Adjust the plane position and orientation via the following parameters:

* <kbd>X</kbd>, <kbd>Y</kbd>, <kbd>Z</kbd>: Plane center coordinates;
* <kbd>Phi</kbd>, <kbd>Theta</kbd>: Plane normal vector direction.

During adjustment, the 3D view will update the plane position in real time until it is located at the boundary between the target cells.

### 4.1.4 Execute Splitting

Click <kbd>Split by Plane</kbd>. NuPatch3D will divide the voxels on both sides of the plane into different labels. After completion, you can check the splitting results in the 2D or 3D view.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image10.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 10. Plane Construction and Adjustment</div>
</div>

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image11.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 11. Plane Splitting Result Example</div>
</div>

## 4.2 Auto Mode (GMM Auto Splitting)

Auto mode automatically identifies and separates under-segmented cells based on the Gaussian Mixture Model (GMM). It is suitable for scenarios where cell boundaries are relatively clear and no manual segmentation position is required.

### 4.2.1 Set Algorithm Parameters

* <kbd>Sampling Rate</kbd>: Voxel sampling ratio (default: 0.3), used to control the number of samples participating in GMM training. The smaller the value, the faster the running speed; the larger the value, the more stable the result usually is.
* <kbd>Split Dist</kbd>: Splitting threshold (default: 10). If the cell diameter is greater than this value, splitting is performed; otherwise, it is not.
* <kbd>Merge Dist</kbd>: Merging threshold (default: 3). If the distance between two cells is less than this value, they are merged; otherwise, they are not.

### 4.2.2 Set Target Labels

Enter the label IDs to be automatically split in the <kbd>Target Labels</kbd> input box. Multiple labels are separated by spaces.

If left blank, automatic splitting will be performed on all non-zero labels within the current local editing region (Bounding Box).

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image12.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 12. Auto Mode Panel</div>
</div>

### 4.2.3 Execute Auto Splitting

Click <kbd>Under-segmentation Fix</kbd>. NuPatch3D will automatically complete cluster analysis, cell center optimization, and label reassignment, and assign unique label IDs to newly generated cells to ensure no conflict with existing labels. After splitting, cell centers will be automatically updated.

<div style="text-align: center; margin: 2em 0;">
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../../images/media/image14.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 13. Before Auto Splitting</div>
  </div>
  <div style="display: inline-block; vertical-align: middle; font-size: 2.5em; color: #888; margin: 0 5px;">→</div>
  <div style="display: inline-block; vertical-align: middle; text-align: center; width: 280px; margin: 0 15px;">
    <img src="../../images/media/image13.png" style="width: 100%; display: block; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);">
    <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 14. After Auto Splitting</div>
  </div>
</div>

## 4.3 Manual Mode (Manually Specify Centers)

Manual mode is suitable for cases where automatic splitting results are not ideal. Users can manually specify cell center positions to guide NuPatch3D in completing the split.

### 4.3.1 Set Cell Centers

Cell centers can be specified in the following two ways:

**Method 1: Manual Coordinate Input**

Enter the cell center coordinates in the <kbd>Coords of Centers</kbd> input box in the format:

```text
Z,Y,X
```

Multiple center coordinates are separated by spaces, for example:

```text
10,20,30 15,25,35
```

**Method 2: Interactive Point Selection**

Click <kbd>Select Coordinates</kbd>. NuPatch3D will create the <kbd>GMM-Coordinates</kbd> layer and automatically enter point selection mode. At this point, switch to the 2D view and click sequentially at the center positions of the target cells to add marker points.

After point selection is completed, NuPatch3D will automatically:

* Synchronize the coordinates to <kbd>Coords of Centers</kbd>;
* Identify the corresponding labels and fill them into <kbd>Target Labels</kbd>.

<kbd>GMM-Coordinates</kbd> is only used for auxiliary point selection and does not participate in the final splitting calculation. After splitting is completed, this auxiliary layer can be deleted via the shortcut <kbd>Shift</kbd>+<kbd>C</kbd>.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image15.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 15. Manual Mode Point Selection Example</div>
</div>

### 4.3.2 Execute Splitting

Click <kbd>Under-segmentation Fix</kbd>. NuPatch3D will use the user-specified center coordinates as initial cell centers to perform splitting on <kbd>Target Labels</kbd>, and automatically update the label results.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image16.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 16. Manual Mode Splitting Result Example</div>
</div>

## 4.4 Connected Components Relabeling

If the same label contains multiple disconnected regions, click <kbd>Connected Components Split</kbd> to process it.

NuPatch3D will perform 3D connected component analysis on each label in <kbd>Target Labels</kbd>, retain the original label for the largest connected component, and automatically assign new label IDs to the remaining connected components, thereby resolving under-segmentation.
