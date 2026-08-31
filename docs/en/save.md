# Saving Results

## 8.1 Commit Changes

When the editing results in the local <kbd>LabelFix</kbd> layer reach a stage of completion, you can click the <kbd>Commit</kbd> button in the <kbd>Interaction</kbd> region, or press the shortcut <kbd>Shift</kbd>+<kbd>S</kbd> to submit the current changes.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image26.png" style="max-width: 70%; height: auto; border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 26. Interaction Panel</div>
</div>

After clicking the <kbd>Commit</kbd> button, NuPatch3D will perform the following operations:

* Write the current local label data in <kbd>LabelFix</kbd> back to the global <kbd>Labels</kbd> layer;
* Record the current local region's voxel state, coordinate range, time, and layer mapping relationships in the JSON log;
* Save the intermediate operation records before this submission, including brush, eraser, fill, and NuPatch3D repair operations;
* Clear the current cache log and start a new recording cycle;
* Re-extract the local region corresponding to the current <kbd>Label ID</kbd> and refresh the local view.

> **Note**
>
> * The JSON log uses append mode; historical records will not be overwritten.
> * It is recommended to execute <kbd>Commit</kbd> promptly after completing a valid edit to save the results of the current stage.

## 8.2 Export Refined Cell Labels

Click <kbd>Export Label</kbd> in the <kbd>Interaction</kbd> region to export the current refined label layer in TIFF format. By default, the exported file name will append the `_refined` suffix to the original file name, and the save directory will be consistent with the directory where the current JSON log file is located. If the target file already exists, the system will pop up a confirmation dialog asking whether to overwrite the original file.

In addition to using <kbd>Export Label</kbd>, you can also save label results in the following ways:

* <kbd>Ctrl</kbd>+<kbd>S</kbd> (or <kbd>⌘</kbd>+<kbd>S</kbd> on macOS);
* napari menu bar <kbd>File</kbd> → <kbd>Save Selected Layers</kbd>.
