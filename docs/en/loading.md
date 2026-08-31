# Basic Operations

All editing operations in NuPatch3D are performed within a local region (Bounding Box) to reduce interference from surrounding cells on the target cell (specified by the <kbd>Label ID</kbd> input box).

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image6.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 6. Cell Bounding Box Extraction Panel</div>
</div>

## 3.1 Calculate Cell Centers

In the <kbd>Cell Bounding Box Extraction</kbd> module of the plugin panel, click <kbd>Calculate Cell Centers</kbd>. NuPatch3D will calculate the center coordinates of all non-zero labels in the <kbd>Label Layer</kbd> and build a label index.

At the same time, NuPatch3D will automatically initialize <kbd>Box Size</kbd> to twice the nucleus diameter to ensure that the cropped region fully contains the target cell while minimizing interference from irrelevant neighborhoods.

## 3.2 Set Target Cell Label and Crop Region Size

The label ID of the target cell can be directly modified through the <kbd>Label ID</kbd> input box, or switched sequentially via the <kbd>Previous</kbd> and <kbd>Next</kbd> buttons.

To improve switching efficiency, NuPatch3D provides the following shortcuts:

* <kbd>A</kbd>: Switch to the previous label;
* <kbd>D</kbd>: Switch to the next label.

In addition, the side length of the cropping cube (unit: pixels) can be manually adjusted through the <kbd>Box Size</kbd> input box.

## 3.3 Extract Local Editing Region

After clicking <kbd>Extract Bounding Box</kbd>, the plugin will simultaneously crop a cubic region centered on the target cell with a side length of <kbd>Box Size</kbd> (default is twice the target cell diameter) from the <kbd>Image Layer</kbd> and <kbd>Label Layer</kbd>, and generate the following two layers in napari:

* `<ImageName>-Crop`: Local original image (type <kbd>Image</kbd>), serving as the reference image for subsequent editing;
* `<ImageName>-LabelFix`: Local label image (type <kbd>Labels</kbd>), on which all refinement operations are performed.

After extraction, the plugin will automatically uncheck <kbd>Global View</kbd>, hide the global layers, and retain only the local <kbd>Crop</kbd> and <kbd>LabelFix</kbd> layers. At this point, you can use napari's basic view functions to rotate, zoom, and browse slices of the local region to evaluate segmentation quality.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image7.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 7. Effect After Extracting the Local Editing Region</div>
</div>

## 3.4 View Label Filtering

Enter the label IDs to be displayed in the <kbd>View Labels</kbd> input box (multiple labels separated by spaces), and then click <kbd>Apply</kbd>.

After execution, the plugin will automatically enable <kbd>Focus</kbd> mode, displaying only the specified labels while hiding the rest.

If <kbd>Focus</kbd> is checked and <kbd>View Labels</kbd> is empty, only the target cell corresponding to the current <kbd>Label ID</kbd> is displayed by default.

<kbd>Focus</kbd> is an independent display switch:

* When checked: only focused labels are displayed;
* When unchecked: all labels are restored.

You can quickly switch between the focused view and full display via the shortcut <kbd>F</kbd>.

In addition, the shortcut <kbd>Shift</kbd>+<kbd>R</kbd> can toggle between "display all labels" and "display only labels specified by View Labels", which has the same effect as clicking the <kbd>Apply</kbd> button.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image8.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 8. Interface After View Label Filtering</div>
</div>

## 3.5 Global View Toggle

If you need to compare with global data during editing, check the <kbd>Global View</kbd> checkbox in the <kbd>NuPatch3D Settings</kbd> region.

When enabled, the global <kbd>Image</kbd> and <kbd>Labels</kbd> layers will reappear in the napari viewer. When unchecked, only the local <kbd>Crop</kbd> and <kbd>LabelFix</kbd> layers are displayed.

## 3.6 Clean Up Auxiliary Layers

After performing Plane splitting, Manual point selection, Missing Cell Detection, and other operations, auxiliary layers may remain in the napari <kbd>Layers</kbd> panel, such as:

* <kbd>Plane Label Splitting-Points</kbd>
* <kbd>Plane Label Splitting-Shapes</kbd>
* <kbd>Plane-Spherical-Axes</kbd>
* <kbd>GMM-Coordinates</kbd>
* <kbd>Missing-Cell-Seeds</kbd>

For the purposes of these auxiliary layers, please refer to [Under-segmentation](under.md).

Click the <kbd>Remove Aux Layer</kbd> button in the <kbd>Settings</kbd> region at the top of the plugin, or use the shortcut <kbd>Shift</kbd>+<kbd>C</kbd>, to delete all auxiliary layers created by NuPatch3D with one click, and automatically switch focus back to the current editing layer to avoid affecting subsequent operations.

All editing operations—whether plugin algorithm fixes or napari native annotations—are managed within a unified undo/redo stack and cached in real time to the memory log. Users can revert to any historical state at any time, or submitstage-by-stage results to the global original data and export it as TIFF or serialize the JSON log for complete restoration.
