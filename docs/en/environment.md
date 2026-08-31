# Installation & Setup

## 2.1 System and Hardware Requirements

* **Operating System**: Windows 10 or macOS 26 (Tahoe) and above
* **Hardware**: Intel or AMD processor, 16 GB RAM or more

The above configurations are verified environments; other hardware platforms are generally also supported.

## 2.2 Installing NuPatch3D

NuPatch3D is a plugin developed based on [napari](https://napari.org/). It is currently adapted for napari 0.6. Other napari versions may have compatibility issues.

At present, NuPatch3D is only available via GitHub source installation. Follow the steps below:

```bash
# 1. Create a Conda environment
conda create -n napari-env python=3.11

# 2. Activate the environment
conda activate napari-env

# 3. Install napari
pip install "napari[all]"

# 4. Clone the repository
git clone https://github.com/Hagibis2019/NuPatch3D.git
cd NuPatch3D

# 5. Install NuPatch3D
pip install .
```

## 2.3 Uninstallation

To uninstall the plugin, run the following command in the corresponding environment:

```bash
pip uninstall NuPatch3D
```

## 2.4 Launching NuPatch3D

Click the menu bar <kbd>Plugins</kbd> → <kbd>NuPatch3D (NuPatch-3D)</kbd>. The NuPatch3D plugin panel will automatically dock on the right side of the napari window.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image2.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 4. Launching the NuPatch3D Plugin</div>
</div>

## 2.5 Confirming Layer Mapping

After the plugin is launched, the <kbd>Label Layer</kbd> and <kbd>Image Layer (Reference)</kbd> drop-down boxes in the <kbd>Cell Bounding Box Extraction</kbd> region will automatically detect available layers in the current napari viewer. Please confirm that:

* <kbd>Label Layer</kbd> corresponds to the pre-segmented label layer (type <kbd>Labels</kbd>);
* <kbd>Image Layer (Reference)</kbd> corresponds to the original fluorescence image layer (type <kbd>Image</kbd>).

If multiple layers of the same type are loaded (e.g., multiple label images), please manually select the target layer to be edited from the drop-down box.

> **Tip**
>
> If <kbd>Label Layer</kbd> fails to automatically recognize the label layer, please first confirm whether the segmentation result is loaded as a <kbd>Labels</kbd> type layer. If the current layer is displayed as <kbd>Image</kbd> type, you can select the layer in the layer list, right-click and choose **Convert to Labels** (or reload the label image as a Labels layer), and then re-select or switch the target label layer.

## 2.6 Configuring the Plugin Environment

Before starting editing, it is recommended to complete the following settings in the <kbd>NuPatch-3D Settings</kbd> region (Figure 5):

* **Panel Layout**: If the NuPatch3D control panel is not displayed on the right side of the napari main window, click <kbd>Dock Right</kbd> to fix it to the right side of the window.
* **Font Size**: Adjust the font size of the NuPatch3D control panel in real time through the <kbd>Font Size</kbd> input box.
* **JSON Log Path**: Click <kbd>Select JSON Save Path</kbd> to specify the save location for the operation log. This file is used to record the editing history and is an important basis for achieving traceability and recovery of the annotation process. The default file name is the same as the current <kbd>Image Layer</kbd>. Please complete this setting before starting annotation and keep the path unchanged during the annotation process. After setting, the <kbd>Current JSON Path</kbd> text box will display the currently effective absolute path.

<div style="text-align: center; margin: 1.5em 0;">
  <img src="../../images/media/image3.png" style="max-width: 70%; height: auto; display: block; margin: 0 auto;">
  <div style="color: #666; font-size: 0.9em; margin-top: 0.5em;">Figure 5. NuPatch3D Basic Settings Panel</div>
</div>
