import napari
import numpy as np
from qtpy.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QComboBox, QPushButton, QSpinBox, QSlider, 
                            QLineEdit, QGroupBox, QMessageBox, QScrollArea, QCheckBox,
                            QSizePolicy, QDockWidget, QInputDialog)
from qtpy.QtWidgets import QFileDialog
from qtpy.QtWidgets import QShortcut
from qtpy.QtGui import QKeySequence
from qtpy.QtCore import Qt, QTimer, QSignalBlocker
from collections import deque
from napari.utils.notifications import show_info, show_error
from scipy.ndimage import center_of_mass, distance_transform_edt
from skimage.segmentation import watershed
import json
import os
import shutil
from datetime import datetime
from contextlib import ExitStack
from qtpy.QtWidgets import QSpinBox, QDoubleSpinBox, QHBoxLayout, QLabel
import traceback
import re
import importlib
import sys
import weakref
import copy
import tifffile

from ._utils import (
    calculate_centers,
    get_bbox,
    sort_commit_snapshot_entries_by_timestamp,
    commit_safe_volume_shape_from_label_data,
)
from ._processing import (
    run_gmm_fix,
    run_boundary_fix_fast,
    split_target_labels_by_connected_components,
)


def _tight_labeled_control_row(
    outer: QHBoxLayout,
    label_text: str,
    control,
    *,
    min_control_w: int = 56,
    max_control_w: int = 240,
    outer_stretch: int = 1,
):
    """ + /"""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label_text)
    lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    control.setMinimumWidth(min_control_w)
    control.setMaximumWidth(max_control_w)
    row.addWidget(lab)
    row.addWidget(control, 1)
    outer.addLayout(row, outer_stretch)
def _patch_vispy_error_handling():
    """vispyOpenGL"""
    try:
        import vispy.util.event as vispy_event
        _original_invoke_callback = vispy_event.EventEmitter._invoke_callback
        
        def _patched_invoke_callback(self, cb, event):
            """OpenGL"""
            try:
                return _original_invoke_callback(self, cb, event)
            except OSError as e:
                if "access violation" in str(e).lower() or "0x000000000000000C" in str(e):
                    return
                raise
        
        vispy_event.EventEmitter._invoke_callback = _patched_invoke_callback
    except (ImportError, AttributeError):
        pass
_patch_vispy_error_handling()

class NuPatch3DWidget(QWidget):
    _instances = []
    _instance_refs = []
    
    @classmethod
    def get_instance(cls):
        """widgetPython"""
        cls._instance_refs = [ref for ref in cls._instance_refs if ref() is not None]
        if cls._instance_refs:
            return cls._instance_refs[-1]()
        return None
    
    def __init__(self, napari_viewer):
        super().__init__()
        self.viewer = napari_viewer
        self._weak_ref = weakref.ref(self)
        NuPatch3DWidget._instance_refs.append(self._weak_ref)
        NuPatch3DWidget._instances.append(self)
        self._event_connections = []
        self._points_layer_connections = []
        self.device_pixel_ratio = self.devicePixelRatioF()
        if self.device_pixel_ratio == 0:
            self.device_pixel_ratio = 1.0

        self.ui_scale_multiplier = 1.0
        self.scale_factor = self.device_pixel_ratio * self.ui_scale_multiplier
        
        self.ui_constants_multiplier = 1.0
        self.ui_constants = {
            'button_height_base': 5.5 * self.ui_constants_multiplier,
            'font_size_base': 4 * self.ui_constants_multiplier,
            'groupbox_font_size_base': 5 * self.ui_constants_multiplier,
            'groupbox_margin_base': 1 * self.ui_constants_multiplier,
            'groupbox_padding_base': 1 * self.ui_constants_multiplier,
            'button_padding_h_base': 1.5 * self.ui_constants_multiplier,
            'button_padding_v_base': 1 * self.ui_constants_multiplier,
            'input_min_width_base': 10 * self.ui_constants_multiplier,
            'spinbox_min_width_base': 30 * self.ui_constants_multiplier,
            'combobox_min_width_base': 10 * self.ui_constants_multiplier,
            'input_min_height_base': 5 * self.ui_constants_multiplier,
            'spinbox_min_height_base': 5 * self.ui_constants_multiplier,
            'combobox_min_height_base': 5 * self.ui_constants_multiplier,
        }
        self._default_ui_constants = copy.deepcopy(self.ui_constants)

        self.centers = {} # {label: (z,y,x)}
        self.sorted_labels = []
        self.current_bbox = None
        
        # Layer Names References
        self.original_label_layer_name = None
        self.original_image_layer_name = None
        self.fix_label_layer_name = None
        self.fix_image_layer_name = None
        
        # Undo/Redo Stacks: Stores tuples (label_data_copy, metadata)
        self.undo_stack = deque(maxlen=10)
        self.redo_stack = deque(maxlen=10)
        
        self.edit_log = []
        self.redo_log_stack = []
        self.json_file_path = os.path.abspath("NuPatch3D_edit_log.json")
        self._json_path_user_locked = False
        self.bbox_translate_offset = None
        self._show_original_image_enabled = True
        self._detached_original_layers = {}
        self._known_label_layer_names = set()
        self._known_image_layer_names = set()
        self.view_labels_filter_enabled = False
        self._focus_filter_enabled = False
        self._suspend_label_data_events = False
        self._bbox_commit_use_target_mask = False
        self._bbox_commit_target_ids = []
        self._extract_preserve_target_edits = False
        self.gmm_points_layer = None
        self.gmm_points_layer_name = "GMM-Coordinates"
        self.missing_cell_points_layer = None
        self.missing_cell_points_layer_name = "Missing-Cell-Seeds"
        self.plane_split_points_layer = None
        self.plane_split_points_layer_name = "Plane Label Splitting-Points"
        self.plane_split_points_connection = None
        self.plane_split_shapes_layer = None
        self.plane_split_shapes_layer_name = "Plane Label Splitting-Shapes"
        self.plane_center_point = None
        self.plane_phi = 90.0
        self.plane_theta = 0.0
        self.plane_normal = self.spherical_to_normal(self.plane_phi, self.plane_theta).astype(float)
        self.plane_axis_shapes_layer = None
        self.plane_axis_shapes_layer_name = "Plane-Spherical-Axes"
        self.plane_has_initial_point = False
        self.label_layer_data_connection = None
        self._label_prev_data = None
        
        self.init_ui()
        self._pending_state_dirty = False
        self._save_state_timer = QTimer(self)
        self._save_state_timer.setSingleShot(True)
        self._save_state_timer.setInterval(120)
        self._save_state_timer.timeout.connect(self._flush_pending_save_state)
        self._masked_view_cache = None
        self.shortcut_reload_scale = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        self.shortcut_reload_scale.activated.connect(self.reload_scaling)
        
    def update_ui_constant(self, key, value):
        """
        UI
        
        :
            key: str,  'font_size_base', 'button_height_base' 
            value: float/int, 
        """
        if key in self.ui_constants:
            self.ui_constants[key] = value
            show_info(f"Updated {key} = {value}")
        else:
            show_error(f"Unknown constant name: {key}")
    
    def reload_scaling(self):
        """"""
        try:
            import sys
            current_module = sys.modules.get('NuPatch3D._widget')
            if current_module and hasattr(current_module, '__file__'):
                widget_file_path = current_module.__file__
                if widget_file_path and os.path.exists(widget_file_path):
                    with open(widget_file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    constants_to_update = [
                        'font_size_base', 'button_height_base',
                        'groupbox_font_size_base', 'groupbox_margin_base', 'groupbox_padding_base',
                        'button_padding_h_base', 'button_padding_v_base',
                        'input_min_width_base', 'spinbox_min_width_base', 'combobox_min_width_base',
                        'input_min_height_base', 'spinbox_min_height_base', 'combobox_min_height_base',
                    ]
                    
                    for key in constants_to_update:
                        pattern = rf"['\"]{key}['\"]\s*:\s*(\d+\.?\d*)"
                        match = re.search(pattern, content)
                        if match:
                            new_value = float(match.group(1))
                            old_value = self.ui_constants.get(key)
                            if old_value != new_value:
                                self.ui_constants[key] = new_value
        except Exception as e:
            show_error(f"Failed to read source file constants: {e}")
        self.scale_factor = self.device_pixel_ratio * self.ui_scale_multiplier
        self._refresh_stylesheet()

        show_info(f"UI scaling reapplied: scale_factor = {self.scale_factor:.2f}")

    def _refresh_stylesheet(self):
        """/"""
        self.setStyleSheet("")
        self._apply_scaling()
        for widget in self.findChildren(QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.update()

    def set_global_font_size(self, point_size: int):
        """ SpinBox """
        try:
            current_font_size = max(1, int(self.ui_constants['font_size_base'] * self.scale_factor))
            if current_font_size <= 0:
                current_font_size = 1
            ratio = point_size / float(current_font_size)
            self.ui_constants['font_size_base'] *= ratio
            self.ui_constants['groupbox_font_size_base'] *= ratio
            self._refresh_stylesheet()
        except Exception as e:
            show_error(f"Failed to adjust font size: {e}")

    def _find_plugin_qdockwidget(self):
        """
         QDockWidget napari  QtViewerDockWidget
         dock napari remove_dock_widget
         QDockWidget
        """
        p = self.parentWidget()
        while p is not None:
            if isinstance(p, QDockWidget):
                return p
            p = p.parentWidget()
        mw = getattr(self.viewer.window, "_qt_window", None)
        if mw is None:
            return None
        for dw in mw.findChildren(QDockWidget):
            inner = dw.widget()
            if inner is None:
                continue
            if inner is self or inner.isAncestorOf(self):
                return dw
        return None

    def _dock_plugin_to_right(self):
        """ napari """
        try:
            dock = self._find_plugin_qdockwidget()
            if dock is not None:
                mw = self.viewer.window._qt_window
                dock.setFloating(False)
                mw.addDockWidget(Qt.RightDockWidgetArea, dock)
                dock.show()
                dock.raise_()
                return
            if self.parentWidget() is None:
                self.viewer.window.add_dock_widget(
                    self, area="right", name="NuPatch3D"
                )
            else:
                show_error("Plugin dock widget not found, cannot dock to the right.")
        except Exception as e:
            show_error(f"Dock to right failed: {e}")

    def reset_plugin_to_defaults(self):
        """
        / viewer 
        bbox LabelFix Crop
        """
        fix_lbl = getattr(self, "fix_label_layer_name", None)
        fix_img = getattr(self, "fix_image_layer_name", None)
        for _nm in list(self._detached_original_layers.keys()):
            self._attach_detached_layer(_nm)

        if hasattr(self, "_points_layer_connections"):
            for conn in list(self._points_layer_connections):
                try:
                    conn.disconnect()
                except (RuntimeError, TypeError, AttributeError):
                    pass
            self._points_layer_connections.clear()

        self.remove_aux_layers_under(quiet=True)
        self.remove_aux_layers_missing(quiet=True)

        if getattr(self, "label_layer_data_connection", None) is not None:
            try:
                self.label_layer_data_connection.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
            self.label_layer_data_connection = None
        self._label_prev_data = None

        if getattr(self, "plane_split_points_connection", None) is not None:
            try:
                self.plane_split_points_connection.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
            self.plane_split_points_connection = None

        for name in (fix_lbl, fix_img):
            if name and name in self.viewer.layers:
                try:
                    self.viewer.layers.remove(name)
                except Exception:
                    pass

        if hasattr(self, "_hide_non_target_debounce_timer"):
            self._hide_non_target_debounce_timer.stop()
        if hasattr(self, "_view_labels_debounce_timer"):
            self._view_labels_debounce_timer.stop()
        if hasattr(self, "_save_state_timer"):
            self._save_state_timer.stop()
            self._pending_state_dirty = False
        plane_update_timer = getattr(self, "_plane_update_timer", None)
        if plane_update_timer is not None:
            plane_update_timer.stop()

        if hasattr(self, "_view_labels_full_data"):
            delattr(self, "_view_labels_full_data")
        if hasattr(self, "_commit_count"):
            self._commit_count = 0

        self.ui_constants = copy.deepcopy(self._default_ui_constants)
        self.ui_scale_multiplier = 1.0
        self.ui_constants_multiplier = 1.0
        self.scale_factor = self.device_pixel_ratio * self.ui_scale_multiplier

        widgets_to_block = [
            self.spin_global_font,
            self.combo_split_mode,
            self.txt_sample_r,
            self.txt_manual_coords,
            self.txt_split_th,
            self.txt_merge_th,
            self.txt_plane_x,
            self.txt_plane_y,
            self.txt_plane_z,
            self.txt_phi,
            self.txt_theta,
            self.txt_plane_target_labels,
            self.txt_gmm_target_labels,
            self.txt_merge_labels,
            self.txt_boundary_percentile,
            self.txt_boundary_radius,
            self.txt_watershed_threshold,
            self.txt_watershed_distance,
            self.txt_label_id,
            self.txt_size,
        ]
        with ExitStack() as stack:
            for w in widgets_to_block:
                stack.enter_context(QSignalBlocker(w))

            self.combo_split_mode.setCurrentText("Auto")
            self.txt_sample_r.setValue(0.3)
            self.txt_manual_coords.clear()
            self.txt_split_th.setValue(10)
            self.txt_merge_th.setValue(3)
            self.txt_plane_x.setRange(0, 10000)
            self.txt_plane_y.setRange(0, 10000)
            self.txt_plane_z.setRange(0, 10000)
            self.txt_plane_x.setValue(0)
            self.txt_plane_y.setValue(0)
            self.txt_plane_z.setValue(0)
            self.txt_phi.setValue(90)
            self.txt_theta.setValue(0)
            self.txt_plane_target_labels.clear()
            self.txt_gmm_target_labels.clear()
            self.txt_merge_labels.clear()
            self.txt_boundary_percentile.setValue(35)
            self.txt_boundary_radius.setValue(1.0)
            self.txt_watershed_threshold.setValue(9)
            self.txt_watershed_distance.setValue(10)
            self.txt_label_id.setText("1")
            self.txt_size.setValue(50)
            if hasattr(self, "txt_view_labels"):
                self.txt_view_labels.clear()
            if hasattr(self, "chk_show_original_image"):
                self.chk_show_original_image.setChecked(True)
            fs = max(1, int(self.ui_constants["font_size_base"] * self.scale_factor))
            self.spin_global_font.setValue(fs)

        self.json_file_path = os.path.abspath("NuPatch3D_edit_log.json")
        self._json_path_user_locked = False

        self.centers = {}
        self.sorted_labels = []
        self.current_bbox = None
        self.original_label_layer_name = None
        self.original_image_layer_name = None
        self.fix_label_layer_name = None
        self.fix_image_layer_name = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.edit_log.clear()
        self.redo_log_stack.clear()
        self.bbox_translate_offset = None
        self._bbox_commit_use_target_mask = False
        self._bbox_commit_target_ids = []
        self._extract_preserve_target_edits = False
        self._focus_filter_enabled = False
        self._suspend_label_data_events = False

        self.gmm_points_layer = None
        self.missing_cell_points_layer = None
        self.plane_split_points_layer = None
        self.plane_split_shapes_layer = None
        self.plane_axis_shapes_layer = None
        self.plane_center_point = None
        self.plane_phi = 90.0
        self.plane_theta = 0.0
        self.plane_normal = self.spherical_to_normal(self.plane_phi, self.plane_theta).astype(float)
        self.plane_has_initial_point = False

        self.toggle_manual_input(self.combo_split_mode.currentText())
        self._refresh_stylesheet()
        self.refresh_layers()
        self._focus_stack_top_if_no_active_layer()
        self._update_json_path_display()
        show_info("Plugin fully reset (parameters, internal state, and bbox/auxiliary layers cleared).")


    def _get_original_layer_by_name(self, name):
        """ viewer  detached """
        if not name:
            return None
        if name in self.viewer.layers:
            return self.viewer.layers[name]
        layer = self._detached_original_layers.get(name)
        if layer is not None:
            return layer
        for lyr in self._detached_original_layers.values():
            if getattr(lyr, "name", None) == name:
                return lyr
        return None

    def _attach_detached_layer(self, name):
        """ napari viewer"""
        if not name or name not in self._detached_original_layers:
            return None
        layer = self._detached_original_layers.pop(name)
        try:
            self.viewer.layers.append(layer)
        except Exception:
            try:
                self.viewer.add_layer(layer)
            except Exception:
                self._detached_original_layers[name] = layer
                return None
        return layer

    def _detach_layer_from_viewer(self, name):
        """ napari  layer list """
        if not name or name not in self.viewer.layers:
            return
        try:
            layer = self.viewer.layers[name]
            self._detached_original_layers[name] = layer
            self.viewer.layers.remove(name)
        except Exception:
            pass


    def _get_preferred_global_layer_names(self):
        """
         Global View  label/image 
        -  original_*_layer_namebbox/commit 
        - 
        """
        label_name = getattr(self, "original_label_layer_name", None) or (
            self.layer_combo.currentText() if hasattr(self, "layer_combo") else None
        )
        image_name = getattr(self, "original_image_layer_name", None) or (
            self.image_combo.currentText() if hasattr(self, "image_combo") else None
        )
        return label_name, image_name

    def _ensure_global_label_before_image(self):
        """
         Global View  layer list  label layer  image layer 
        napari  layer list 
            index(label) > index(image)
         movemove  remove+append
        """
        label_name, image_name = self._get_preferred_global_layer_names()
        if not label_name or not image_name:
            return
        if label_name not in self.viewer.layers or image_name not in self.viewer.layers:
            return

        try:
            names = [layer.name for layer in self.viewer.layers]
            label_idx = names.index(label_name)
            image_idx = names.index(image_name)
            if label_idx > image_idx:
                return

            try:
                self.viewer.layers.move(label_idx, image_idx + 1)
            except Exception:
                try:
                    label_layer = self.viewer.layers[label_name]
                    self.viewer.layers.remove(label_name)
                    self.viewer.layers.append(label_layer)
                except Exception:
                    pass
        except Exception:
            pass

    def _schedule_global_layer_order_check(self):
        """
         label/image 
        
        - 
        -  Global View  napari /
        """
        def _apply():
            self._ensure_global_label_before_image()

        for ms in (0, 30, 120):
            QTimer.singleShot(ms, _apply)

    def _apply_original_layer_presence(self):
        """
         Show Original  viewer 
        -  viewer  label/image  layer list 
        -  viewer/ label layer  image layer 
        """
        label_name, image_name = self._get_preferred_global_layer_names()

        if self._show_original_image_enabled:
            self._attach_detached_layer(image_name)
            self._attach_detached_layer(label_name)

            if image_name and image_name in self.viewer.layers:
                try:
                    self.viewer.layers[image_name].visible = True
                except Exception:
                    pass
            if label_name and label_name in self.viewer.layers:
                try:
                    self.viewer.layers[label_name].visible = True
                    self.viewer.layers.selection.active = self.viewer.layers[label_name]
                except Exception:
                    pass

            self._schedule_global_layer_order_check()

            try:
                self.viewer.reset_view()
            except Exception:
                pass
        else:
            self._detach_layer_from_viewer(label_name)
            self._detach_layer_from_viewer(image_name)
            self._center_view_on_current_bbox_layer(delayed=True)

    def _set_show_original_image(self, checked: bool):
        self._show_original_image_enabled = bool(checked)
        if self._show_original_image_enabled:
            self._remove_bbox_layers_for_show_original()
        self._apply_original_layer_presence()

    def _reset_show_original_image_checkbox(self):
        """
         Next / Previous / Extract Bounding Box  Global View
         viewer  bbox 
        """
        self._show_original_image_enabled = False
        if hasattr(self, "chk_show_original_image") and self.chk_show_original_image is not None:
            try:
                self.chk_show_original_image.blockSignals(True)
                self.chk_show_original_image.setChecked(False)
            finally:
                self.chk_show_original_image.blockSignals(False)
        self._apply_original_layer_presence()

    def _on_show_original_image_checkbox_changed(self, state):
        self._set_show_original_image(state == Qt.Checked)
        if state == Qt.Checked:
            self._schedule_global_layer_order_check()

    def _auto_enable_show_original_after_import(self):
        """
        “ label layer  image layer” Global View
         refresh_layersbbox Next/Previous 
        """
        try:
            current_label_names = {
                l.name for l in self.viewer.layers
                if isinstance(l, napari.layers.Labels)
            }
            current_image_names = {
                l.name for l in self.viewer.layers
                if isinstance(l, napari.layers.Image)
            }
        except Exception:
            return

        old_label_names = set(getattr(self, "_known_label_layer_names", set()))
        old_image_names = set(getattr(self, "_known_image_layer_names", set()))

        new_label_names = current_label_names - old_label_names
        new_image_names = current_image_names - old_image_names
        self._known_label_layer_names = set(current_label_names)
        self._known_image_layer_names = set(current_image_names)

        has_new_import = bool(new_label_names or new_image_names)
        if not has_new_import:
            return

        if hasattr(self, "chk_show_original_image") and self.chk_show_original_image is not None:
            try:
                self.chk_show_original_image.blockSignals(True)
                self.chk_show_original_image.setChecked(True)
            finally:
                self.chk_show_original_image.blockSignals(False)

        self._show_original_image_enabled = True
        self._apply_original_layer_presence()

    def _center_view_on_current_bbox_layer(self, delayed: bool = False):
        """
         bbox  3D 
         bbox 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        
        if self.viewer.dims.ndisplay == 2:
            return

        def _apply_once():
            if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
                return
            try:
                layer = self.viewer.layers[self.fix_label_layer_name]
                if not isinstance(layer, napari.layers.Labels):
                    return

                try:
                    self.viewer.layers.selection.active = layer
                except Exception:
                    pass

                try:
                    shape = np.asarray(layer.data.shape, dtype=float)
                    if shape.size == 0:
                        return
                    center_zyx = np.maximum((shape - 1.0) / 2.0, 0.0)
                except Exception:
                    return

                try:
                    for ax in list(getattr(self.viewer.dims, "not_displayed", ())):
                        if ax < len(center_zyx):
                            self.viewer.dims.set_point(ax, float(center_zyx[ax]))
                except Exception:
                    pass

                try:
                    displayed = list(getattr(self.viewer.dims, "displayed", range(len(center_zyx))))
                    cam_center = tuple(float(center_zyx[ax]) for ax in displayed if ax < len(center_zyx))
                    self.viewer.camera.center = cam_center
                except Exception:
                    try:
                        self.viewer.camera.center = tuple(float(v) for v in center_zyx)
                    except Exception:
                        pass

                try:
                    layer.refresh()
                except Exception:
                    pass
            except Exception:
                pass

        _apply_once()
        if delayed:
            for ms in (0, 30, 120):
                QTimer.singleShot(ms, _apply_once)


    def _remove_bbox_layers_for_show_original(self):
        """
        Show Original  bbox  Crop/LabelFix 
         label/image  bbox 
        """
        for name_attr in ("fix_label_layer_name", "fix_image_layer_name"):
            name = getattr(self, name_attr, None)
            if name and name in self.viewer.layers:
                try:
                    self.viewer.layers.remove(name)
                except Exception:
                    pass

    def _save_current_label_layer_as_file(self):
        """
         label layer
         label layer LabelFix
         TIFF 

        1.  JSON 
        2. _refined
        3. 
        """
        target_layer = None
        target_name = None

        if self.original_label_layer_name:
            target_layer = self._get_original_layer_by_name(self.original_label_layer_name)
            target_name = self.original_label_layer_name

        if target_layer is None and self.fix_label_layer_name and self.fix_label_layer_name in self.viewer.layers:
            target_layer = self.viewer.layers[self.fix_label_layer_name]
            target_name = self.fix_label_layer_name

        if target_layer is None:
            show_error("No label layer available to save.")
            return
        base_name = self._sanitize_filename(target_name)

        if base_name.lower().endswith("_refined"):
            suggested_name = base_name
        else:
            suggested_name = f"{base_name}_refined"

        suggested_filename = f"{suggested_name}.tif"
        try:
            json_dir = os.path.dirname(os.path.abspath(self.json_file_path)) if self.json_file_path else os.getcwd()
            if not json_dir:
                json_dir = os.getcwd()
        except Exception:
            json_dir = os.getcwd()

        suggested_path = os.path.join(json_dir, suggested_filename)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Modified Label Layer",
            suggested_path,
            "TIFF (*.tif *.tiff);;All Files (*)"
        )
        if not file_path:
            return

        try:
            tifffile.imwrite(file_path, np.asarray(target_layer.data).astype(np.int32))
            show_info(f"Saved to: {file_path}")
        except Exception as e:
            show_error(f"Save failed: {e}")

    def _sanitize_filename(self, name):
        """Windows"""
        if not name:
            return "NuPatch3D"
        sanitized = re.sub(r'[<>:"/\\|?*]+', "_", str(name)).strip()
        return sanitized or "NuPatch3D"

    @staticmethod
    def _json_numpy_default(o):
        """ json.dump(..., default=...)  numpy /"""
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    @staticmethod
    def _log_entry_params_dict(entry):
        """ params null  dict  dict"""
        p = entry.get("params")
        return p if isinstance(p, dict) else {}

    def _build_json_path_for_image_layer(self, image_layer_name, base_dir=None):
        """JSON <image_layer_name>.json"""
        safe_stem = self._sanitize_filename(image_layer_name)
        filename = f"{safe_stem}.json"
        if base_dir is None:
            return os.path.abspath(filename)
        return os.path.abspath(os.path.join(base_dir, filename))

    def _update_json_path_display(self):
        """UIJSON"""
        if hasattr(self, "txt_json_current_path") and self.txt_json_current_path is not None:
            self.txt_json_current_path.setText(os.path.abspath(self.json_file_path))

    def closeEvent(self, event):
        """Widget"""
        for _nm in list(self._detached_original_layers.keys()):
            self._attach_detached_layer(_nm)
        if hasattr(self, '_event_connections'):
            for connection in self._event_connections:
                try:
                    connection.disconnect()
                except (RuntimeError, TypeError, AttributeError):
                    pass
            self._event_connections.clear()
        if hasattr(self, '_points_layer_connections'):
            for connection in self._points_layer_connections:
                try:
                    connection.disconnect()
                except (RuntimeError, TypeError, AttributeError):
                    pass
            self._points_layer_connections.clear()
        if hasattr(self, '_weak_ref'):
            try:
                NuPatch3DWidget._instance_refs = [
                    ref for ref in NuPatch3DWidget._instance_refs 
                    if ref() is not self and ref() is not None
                ]
            except:
                pass
        try:
            if self in NuPatch3DWidget._instances:
                NuPatch3DWidget._instances.remove(self)
        except:
            pass
        self.gmm_points_layer = None
        self.missing_cell_points_layer = None
        if hasattr(self, 'plane_split_points_connection') and self.plane_split_points_connection is not None:
            try:
                self.plane_split_points_connection.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
            self.plane_split_points_connection = None
        self.plane_split_points_layer = None
        self.plane_split_shapes_layer = None
        self.plane_axis_shapes_layer = None
        if hasattr(self, 'label_layer_data_connection') and self.label_layer_data_connection is not None:
            try:
                self.label_layer_data_connection.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
            self.label_layer_data_connection = None
        self._label_prev_data = None
        
        if hasattr(self, '_save_state_timer') and self._save_state_timer is not None:
            try:
                self._save_state_timer.stop()
            except Exception:
                pass
        super().closeEvent(event)

    def _apply_scaling(self):
        """DPI"""
        button_height = int(self.ui_constants['button_height_base'] * self.scale_factor)
        font_size = max(1, int(self.ui_constants['font_size_base'] * self.scale_factor))
        groupbox_font_size = max(1, int(self.ui_constants['groupbox_font_size_base'] * self.scale_factor))
        groupbox_margin = int(self.ui_constants['groupbox_margin_base'] * self.scale_factor)
        groupbox_padding = int(self.ui_constants['groupbox_padding_base'] * self.scale_factor)
        button_padding_horizontal = int(self.ui_constants['button_padding_h_base'] * self.scale_factor)
        button_padding_vertical = int(self.ui_constants['button_padding_v_base'] * self.scale_factor)
        input_min_width = int(self.ui_constants['input_min_width_base'] * self.scale_factor)
        spinbox_min_width = int(self.ui_constants['spinbox_min_width_base'] * self.scale_factor)
        combobox_min_width = int(self.ui_constants['combobox_min_width_base'] * self.scale_factor)
        input_min_height = int(self.ui_constants['input_min_height_base'] * self.scale_factor)
        spinbox_min_height = int(self.ui_constants['spinbox_min_height_base'] * self.scale_factor)
        combobox_min_height = int(self.ui_constants['combobox_min_height_base'] * self.scale_factor)
        
        style = f"""
            QPushButton {{
                min-height: {button_height}px;
                font-size: {font_size}pt;
                padding: {button_padding_vertical}px {button_padding_horizontal}px;
            }}
            QLineEdit {{
                min-height: {input_min_height}px;
                min-width: {input_min_width}px;
                font-size: {font_size}pt;
            }}
            QSpinBox, QDoubleSpinBox {{
                min-height: {spinbox_min_height}px;
                min-width: {spinbox_min_width}px;
                font-size: {font_size}pt;
            }}
            QComboBox {{
                min-height: {combobox_min_height}px;
                min-width: {combobox_min_width}px;
                font-size: {font_size}pt;
            }}
            QGroupBox {{
                font-size: {groupbox_font_size}pt;
                font-weight: bold;
                margin-top: {groupbox_margin}px;
                margin-bottom: {groupbox_margin}px;
                padding-top: {groupbox_padding}px;
                padding-bottom: {groupbox_padding}px;
            }}
            QLabel, QCheckBox {{
                font-size: {font_size}pt;
            }}
        """
        self.setStyleSheet(style)
    
    def init_ui(self):
        # --- New Layout Structure for Scrollbar ---
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content_widget = QWidget()
        layout = QVBoxLayout()
        content_widget.setLayout(layout)
        
        # --- NuPatch3D Settings ---
        group_settings = QGroupBox("NuPatch-3D Settings")
        layout_settings = QVBoxLayout()
        self.label_font_size = QLabel("Font Size:")
        self.spin_global_font = QSpinBox()
        self.spin_global_font.setRange(1, 100)
        current_font_size = max(1, int(self.ui_constants["font_size_base"] * self.scale_factor))
        self.spin_global_font.setValue(current_font_size)
        self.spin_global_font.setSuffix(" pt")
        self.spin_global_font.setToolTip("Adjust the overall font size of this plugin interface.")
        self.spin_global_font.valueChanged.connect(self.set_global_font_size)

        # self.btn_reset_plugin = QPushButton("Reset")
        # self.btn_reset_plugin.setToolTip(
        # )
        # self.btn_reset_plugin.clicked.connect(self.reset_plugin_to_defaults)
        # self.btn_reset_plugin.setMinimumWidth(90)

        self.btn_dock_right = QPushButton("Dock Right")
        self.btn_dock_right.setToolTip("Move this plugin panel to dock on the right side of the napari main window.")
        self.btn_dock_right.clicked.connect(self._dock_plugin_to_right)
        self.btn_dock_right.setMinimumWidth(90)

        self.chk_show_original_image = QCheckBox("Global View")
        self.chk_show_original_image.setChecked(True)
        self.chk_show_original_image.setToolTip("When checked, re-display the original global label/image layers in napari; when unchecked, remove them from the layer list, keeping only the bbox layers.")
        self.chk_show_original_image.stateChanged.connect(self._on_show_original_image_checkbox_changed)
        self.btn_remove_aux_layer_global = QPushButton("Remove Aux Layer")
        self.btn_remove_aux_layer_global.setToolTip("Delete all auxiliary layers created by any mode, and focus on the current active layer or the top layer in the stack.")
        self.btn_remove_aux_layer_global.clicked.connect(self.remove_all_aux_layers)
        self.btn_remove_aux_layer_global.setMinimumWidth(130)
        self.btn_set_json_path = QPushButton("Select JSON Save Path")
        self.btn_set_json_path.setToolTip("Select the save path for the operation log JSON file.")
        self.btn_set_json_path.clicked.connect(self.set_json_save_path)
        self.btn_set_json_path.setMinimumWidth(160)
        self.btn_apply_json_log = QPushButton("Apply JSON Log")
        self.btn_apply_json_log.setToolTip(
            "Select and apply a JSON generated by this plugin: write voxels back to the original label layer according to Commit snapshots. "
            "Voxel-level restore depends on Commit after each edit; intermediate entries such as brush/algorithm alone will not individually restore the global volume."
        )
        self.btn_apply_json_log.clicked.connect(self.apply_json_log_to_current_labels)
        self.btn_apply_json_log.setMinimumWidth(160)
        row1 = QHBoxLayout()
        row1.addWidget(self.label_font_size)
        row1.addWidget(self.spin_global_font)
        # row1.addWidget(self.btn_reset_plugin)
        row1.addWidget(self.btn_dock_right)
        row1.addWidget(self.chk_show_original_image)
        row1.addStretch(1)
        row2 = QHBoxLayout()
        row2.addWidget(self.btn_remove_aux_layer_global)
        row2.addWidget(self.btn_set_json_path)
        row2.addWidget(self.btn_apply_json_log)
        row2.addStretch(1)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Current JSON Path:"))
        self.txt_json_current_path = QLineEdit()
        self.txt_json_current_path.setReadOnly(True)
        self.txt_json_current_path.setText(self.json_file_path)
        self.txt_json_current_path.setToolTip("Absolute path of the current JSON log file.")
        row3.addWidget(self.txt_json_current_path, 1)

        layout_settings.addLayout(row1)
        layout_settings.addLayout(row2)
        layout_settings.addLayout(row3)
        group_settings.setLayout(layout_settings)
        layout.addWidget(group_settings)

        # --- 1. Cell Neighborhood Extraction ---
        group_extract = QGroupBox("Cell Bounding Box Extraction")
        layout_extract = QVBoxLayout()
        
        # Label Layer Selection
        self.layer_combo = QComboBox()
        layout_extract.addWidget(QLabel("Label Layer:"))
        layout_extract.addWidget(self.layer_combo)

        # Image Layer Selection (New)
        self.image_combo = QComboBox()
        layout_extract.addWidget(QLabel("Image Layer (Reference):"))
        layout_extract.addWidget(self.image_combo)
        
        # Calculate Centers
        self.btn_calc_centers = QPushButton("Calculate Cell Centers")
        self.btn_calc_centers.setToolTip("Calculate center coordinates for all cells.")
        self.btn_calc_centers.clicked.connect(self.calculate_centers_action)
        nav_layout = QHBoxLayout()
        self.txt_label_id = QLineEdit("1")
        self.txt_label_id.setAlignment(Qt.AlignCenter)
        self.btn_prev = QPushButton("Previous")
        self.btn_prev.setToolTip("Switch to the previous label.")
        self.btn_next = QPushButton("Next")
        self.btn_next.setToolTip("Switch to the next label.")
        # self.btn_select = QPushButton("select")

        nav_layout.addWidget(QLabel("Label ID:"))
        nav_layout.addWidget(self.txt_label_id)
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.btn_next)
        nav_layout.addSpacing(10)
        self.txt_size = QSpinBox()
        self.txt_size.setRange(10, 10000)
        self.txt_size.setValue(50)
        self.txt_size.setSingleStep(10)
        self.txt_size.setAlignment(Qt.AlignCenter)
        _tight_labeled_control_row(
            nav_layout,
            "Box Size:",
            self.txt_size,
            min_control_w=72,
            max_control_w=160,
            outer_stretch=0,
        )

        layout_extract.addLayout(nav_layout)
        view_layout = QHBoxLayout()
        self.txt_view_labels = QLineEdit()
        self.txt_view_labels.setPlaceholderText("View Labels (e.g. 1 2 5)")
        self.txt_view_labels.setToolTip(
            "View Labels: restrict the label IDs displayed and editable within the bbox; "
            "separate multiple labels with spaces. Leave empty to display all labels."
        )
        self._view_labels_debounce_timer = QTimer(self)
        self._view_labels_debounce_timer.setSingleShot(True)
        self._view_labels_debounce_timer.setInterval(100)
        self._view_labels_debounce_timer.timeout.connect(self._apply_view_labels_from_text)

        self.btn_apply_view_labels = QPushButton("Apply")
        self.btn_apply_view_labels.setToolTip(
            "Refresh the current bbox visualization based on the View Labels input. Clicking with empty input restores display of all labels."
        )
        self.btn_apply_view_labels.clicked.connect(self._apply_view_labels_from_button)
        self.txt_view_labels.returnPressed.connect(self._apply_view_labels_from_button)

        self.chk_hide_non_target_labels = QCheckBox("Focus")
        self.chk_hide_non_target_labels.setChecked(False)
        self.chk_hide_non_target_labels.setToolTip(
            "When checked, only the current target label is displayed by default; when unchecked, all labels are displayed by default."
        )

        view_layout.addWidget(QLabel("View Labels:"))
        view_layout.addWidget(self.txt_view_labels, 1)
        view_layout.addWidget(self.btn_apply_view_labels)
        view_layout.addWidget(self.chk_hide_non_target_labels)
        layout_extract.addLayout(view_layout)

        
        # size_layout.addWidget(QLabel("Box Size (px):"))
        # size_layout.addWidget(self.txt_size)
        # layout_extract.addLayout(size_layout)
        
        # Extract Button
        self.btn_extract = QPushButton("Extract Bounding Box")
        self.btn_extract.setToolTip("Extract Bounding Box based on the current Label ID and Box Size.")
        self.btn_extract.clicked.connect(self.extract_bounding_box)
        
        # Calculate Centers and Extract Bounding Box buttons in one row
        button_row_extract = QHBoxLayout()
        button_row_extract.addWidget(self.btn_calc_centers)
        button_row_extract.addWidget(self.btn_extract)
        layout_extract.addLayout(button_row_extract)
        # self.btn_toggle_center = QPushButton("Toggle Rotation Center")
        # self.btn_toggle_center.clicked.connect(self.toggle_rotation_center)
        # layout_extract.addWidget(self.btn_toggle_center)
        
        group_extract.setLayout(layout_extract)
        layout.addWidget(group_extract)

        # --- 2. Segmentation Fixes ---
        group_fix = QGroupBox("Cell Boundary Refine")
        layout_fix = QVBoxLayout()
        
        # 2.1 Under-segmentation
        subgroup_under = QGroupBox("Under-segmentation (Split)")
        layout_under = QVBoxLayout()
        mode_layout = QHBoxLayout()
        self.combo_split_mode = QComboBox()
        self.combo_split_mode.addItems(["Plane", "Manual", "Auto"])
        self.combo_split_mode.currentTextChanged.connect(self.toggle_manual_input)
        self.combo_split_mode.setEditable(True)
        self.combo_split_mode.lineEdit().setReadOnly(True)
        self.combo_split_mode.lineEdit().setAlignment(Qt.AlignCenter)

        mode_layout.addWidget(QLabel("Mode:"))
        self.combo_split_mode.setMinimumWidth(80)
        mode_layout.addWidget(self.combo_split_mode, 1)
        self.txt_sample_r = QDoubleSpinBox()
        self.txt_sample_r.setRange(0.01, 1.0)
        self.txt_sample_r.setDecimals(2)
        self.txt_sample_r.setValue(0.3)
        self.txt_sample_r.setSingleStep(0.1)
        self.txt_sample_r.setAlignment(Qt.AlignCenter)
        sampling_rate_label = QLabel("Sampling Rate:")
        sampling_row = QHBoxLayout()
        sampling_row.setContentsMargins(0, 0, 0, 0)
        sampling_rate_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.txt_sample_r.setMinimumWidth(64)
        self.txt_sample_r.setMaximumWidth(240)
        sampling_row.addWidget(sampling_rate_label)
        sampling_row.addWidget(self.txt_sample_r, 1)
        mode_layout.addLayout(sampling_row, 1)
        self.sampling_rate_label = sampling_rate_label

        layout_under.addLayout(mode_layout)
        coords_widget = QWidget()
        coords_layout = QHBoxLayout(coords_widget)
        coords_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_manual_coords = QLineEdit()
        self.txt_manual_coords.setPlaceholderText("Z_1,Y_1,X_1 Z_2,Y_2,X_2 ...")

        coords_layout.addWidget(QLabel("Coords of Centers:"))
        coords_layout.addWidget(self.txt_manual_coords)
        self.btn_select_coords = QPushButton("Select Coordinates")
        self.btn_select_coords.setToolTip("Interactively select GMM center coordinate points on the 2D plane.")
        self.btn_select_coords.clicked.connect(self.select_coordinates)

        coords_layout.addWidget(self.btn_select_coords)
        self.coords_widget = coords_widget
        layout_under.addWidget(coords_widget)
        param_widget = QWidget()
        param_layout = QHBoxLayout(param_widget)
        param_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_split_th = QSpinBox()
        self.txt_split_th.setRange(1, 1000)
        self.txt_split_th.setValue(10)
        self.txt_split_th.setSingleStep(1)
        self.txt_split_th.setAlignment(Qt.AlignCenter)
        self.txt_merge_th = QSpinBox()
        self.txt_merge_th.setRange(1, 1000)
        self.txt_merge_th.setValue(3)
        self.txt_merge_th.setSingleStep(1)
        self.txt_merge_th.setAlignment(Qt.AlignCenter)

        _tight_labeled_control_row(param_layout, "Split Dist:", self.txt_split_th)
        param_layout.addSpacing(12)
        _tight_labeled_control_row(param_layout, "Merge Dist:", self.txt_merge_th)

        self.param_widget = param_widget
        layout_under.addWidget(param_widget)
        plane_widget = QWidget()
        plane_layout = QVBoxLayout(plane_widget)
        plane_layout.setContentsMargins(0, 0, 0, 0)
        position_layout = QHBoxLayout()
        position_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_plane_x = QSpinBox()
        self.txt_plane_x.setRange(0, 10000)
        self.txt_plane_x.setValue(0)
        self.txt_plane_x.setSingleStep(1)
        self.txt_plane_x.setAlignment(Qt.AlignCenter)
        self.txt_plane_x.valueChanged.connect(self._on_plane_coord_changed)
        _tight_labeled_control_row(
            position_layout, "X(Red):", self.txt_plane_x, min_control_w=64, max_control_w=240
        )
        position_layout.addSpacing(8)
        self.txt_plane_y = QSpinBox()
        self.txt_plane_y.setRange(0, 10000)
        self.txt_plane_y.setValue(0)
        self.txt_plane_y.setSingleStep(1)
        self.txt_plane_y.setAlignment(Qt.AlignCenter)
        self.txt_plane_y.valueChanged.connect(self._on_plane_coord_changed)
        _tight_labeled_control_row(
            position_layout, "Y(Green):", self.txt_plane_y, min_control_w=64, max_control_w=240
        )
        position_layout.addSpacing(8)
        self.txt_plane_z = QSpinBox()
        self.txt_plane_z.setRange(0, 10000)
        self.txt_plane_z.setValue(0)
        self.txt_plane_z.setSingleStep(1)
        self.txt_plane_z.setAlignment(Qt.AlignCenter)
        self.txt_plane_z.valueChanged.connect(self._on_plane_coord_changed)
        _tight_labeled_control_row(
            position_layout, "Z(Blue):", self.txt_plane_z, min_control_w=64, max_control_w=240
        )

        plane_layout.addLayout(position_layout)
        angle_layout = QHBoxLayout()
        angle_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_phi = QSpinBox()
        self.txt_phi.setRange(-180, 180)  # φ: -180° ~ 180°
        self.txt_phi.setValue(90)
        self.txt_phi.setSingleStep(1)
        self.txt_phi.setAlignment(Qt.AlignCenter)
        self.txt_phi.valueChanged.connect(self._on_text_phi_changed)
        _tight_labeled_control_row(angle_layout, "Phi:", self.txt_phi, min_control_w=56, max_control_w=240)
        angle_layout.addSpacing(12)
        self.txt_theta = QSpinBox()
        self.txt_theta.setRange(-360, 360)  # θ: -360° ~ 360°
        self.txt_theta.setValue(0)
        self.txt_theta.setSingleStep(1)
        self.txt_theta.setAlignment(Qt.AlignCenter)
        self.txt_theta.valueChanged.connect(self._on_text_theta_changed)
        _tight_labeled_control_row(angle_layout, "Theta:", self.txt_theta, min_control_w=56, max_control_w=240)

        plane_layout.addLayout(angle_layout)
        plane_buttons_layout = QHBoxLayout()
        self.btn_draw_plane = QPushButton("Draw a Plane")
        self.btn_draw_plane.setToolTip("Click to select a point on the 2D plane to set the initial plane position, then fine-tune via the GUI on the right.")
        self.btn_draw_plane.clicked.connect(self.draw_plane)
        
        self.btn_split_by_plane = QPushButton("Split by Plane")
        self.btn_split_by_plane.setToolTip("Split labels according to the drawn plane.")
        self.btn_split_by_plane.clicked.connect(self.split_by_plane)
        
        plane_buttons_layout.addWidget(self.btn_draw_plane)
        plane_buttons_layout.addWidget(self.btn_split_by_plane)
        plane_layout.addLayout(plane_buttons_layout)
        plane_target_layout = QHBoxLayout()
        self.txt_plane_target_labels = QLineEdit()
        self.txt_plane_target_labels.setPlaceholderText("Labels to edit (e.g. 114 514 191)")
        plane_target_layout.addWidget(QLabel("Target Labels:"))
        plane_target_layout.addWidget(self.txt_plane_target_labels, 1)
        plane_layout.addLayout(plane_target_layout)
        
        self.plane_widget = plane_widget
        layout_under.addWidget(plane_widget)
        target_widget = QWidget()
        target_layout = QHBoxLayout(target_widget)
        target_layout.setContentsMargins(0, 0, 0, 0)

        self.txt_gmm_target_labels = QLineEdit()
        self.txt_gmm_target_labels.setPlaceholderText("Labels to edit (e.g. 114 514 191)")

        self.btn_fix_under = QPushButton("Under-segmentation Fix")
        self.btn_fix_under.setToolTip("Use the GMM algorithm to fix under-segmented cells.")
        self.btn_fix_under.clicked.connect(self.fix_under_segmentation)

        target_layout.addWidget(QLabel("Target Labels:"))
        target_layout.addWidget(self.txt_gmm_target_labels, 1)
        target_layout.addWidget(self.btn_fix_under)

        self.target_widget = target_widget
        layout_under.addWidget(target_widget)
        cc_widget = QWidget()
        cc_layout = QHBoxLayout(cc_widget)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_split_cc = QPushButton("Connected Components Split")
        self.btn_split_cc.setToolTip("Perform connected component analysis only on Target Labels, and assign different labels to different connected components.")
        self.btn_split_cc.clicked.connect(self.split_target_labels_by_components)
        cc_layout.addWidget(self.btn_split_cc)
        self.cc_widget = cc_widget
        layout_under.addWidget(cc_widget)

        subgroup_under.setLayout(layout_under)
        layout_fix.addWidget(subgroup_under)
        self.toggle_manual_input(self.combo_split_mode.currentText())

        
        # 2.2 Over-segmentation
        subgroup_over = QGroupBox("Over-segmentation (Merge)")
        layout_over = QVBoxLayout()
        merge_layout = QHBoxLayout()
        self.txt_merge_labels = QLineEdit()
        self.txt_merge_labels.setPlaceholderText("Label IDs to merge (e.g. 10 12 15)")
        self.btn_fix_over = QPushButton("Label Merge")
        self.btn_fix_over.setToolTip(
            "Multiple labels: merge into the smallest ID. Single label: erase and merge into background 0."
        )
        self.btn_fix_over.clicked.connect(self.fix_over_segmentation)
        
        merge_layout.addWidget(self.txt_merge_labels, 1)
        merge_layout.addWidget(self.btn_fix_over)
        layout_over.addLayout(merge_layout)
        
        subgroup_over.setLayout(layout_over)
        layout_fix.addWidget(subgroup_over)
        
        # 2.3 Boundary Fix
        subgroup_bound = QGroupBox("Boundary Fix")
        layout_bound = QVBoxLayout()
        param_layout = QHBoxLayout()
        param_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_boundary_percentile = QSpinBox()
        self.txt_boundary_percentile.setRange(0, 100)
        self.txt_boundary_percentile.setValue(35)
        self.txt_boundary_percentile.setSingleStep(5)
        self.txt_boundary_percentile.setAlignment(Qt.AlignCenter)
        # self.txt_boundary_percentile.setSuffix("%")
        self.txt_boundary_radius = QDoubleSpinBox()
        self.txt_boundary_radius.setRange(0.1, 10.0)
        self.txt_boundary_radius.setDecimals(2)
        self.txt_boundary_radius.setValue(1.0)
        self.txt_boundary_radius.setSingleStep(0.1)
        self.txt_boundary_radius.setAlignment(Qt.AlignCenter)

        _tight_labeled_control_row(param_layout, "Percentile:", self.txt_boundary_percentile)
        param_layout.addSpacing(12)
        _tight_labeled_control_row(
            param_layout,
            "Scaling:",
            self.txt_boundary_radius,
            min_control_w=72,
        )
        param_layout.addSpacing(12)
        self.chk_boundary_use_hull = QCheckBox("Use Hull")
        self.chk_boundary_use_hull.setChecked(True)
        param_layout.addWidget(self.chk_boundary_use_hull)

        layout_bound.addLayout(param_layout)

        self.btn_fix_bound = QPushButton("Boundary Fix")
        self.btn_fix_bound.setToolTip("Repair cell boundaries based on image density.")
        self.btn_fix_bound.clicked.connect(self.fix_boundary)
        layout_bound.addWidget(self.btn_fix_bound)
        subgroup_bound.setLayout(layout_bound)
        layout_fix.addWidget(subgroup_bound)
        
        group_fix.setLayout(layout_fix)
        layout.addWidget(group_fix)
        
        
        # --- 3. Missing Cell Detection --- Update 1215
        group_missing = QGroupBox("Missing Cell Detection")
        layout_missing = QVBoxLayout()
        param_layout = QHBoxLayout()
        param_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_select_seed = QPushButton("Select Seed Point")
        self.btn_select_seed.setToolTip("Interactively select seed points for missing cells on the 2D plane.")
        self.btn_select_seed.clicked.connect(self.select_missing_cell_seed)
        self.txt_watershed_threshold = QSpinBox()
        self.txt_watershed_threshold.setRange(1, 10000)
        self.txt_watershed_threshold.setValue(500)
        self.txt_watershed_threshold.setSingleStep(10)
        self.txt_watershed_threshold.setAlignment(Qt.AlignCenter)
        self.txt_watershed_distance = QSpinBox()
        self.txt_watershed_distance.setRange(1, 1000)
        self.txt_watershed_distance.setValue(10)
        self.txt_watershed_distance.setSingleStep(1)
        self.txt_watershed_distance.setAlignment(Qt.AlignCenter)

        _tight_labeled_control_row(
            param_layout, "Threshold:", self.txt_watershed_threshold, min_control_w=48, max_control_w=200
        )
        param_layout.addSpacing(12)
        _tight_labeled_control_row(
            param_layout, "Max Distance:", self.txt_watershed_distance, min_control_w=48, max_control_w=200
        )

        layout_missing.addLayout(param_layout)
        self.btn_watershed = QPushButton("Detect Missing Cell")
        self.btn_watershed.setToolTip("Use the watershed algorithm to identify missing cells.")
        self.btn_watershed.clicked.connect(self.detect_missing_cell)
        button_row_missing = QHBoxLayout()
        button_row_missing.addWidget(self.btn_select_seed)
        button_row_missing.addWidget(self.btn_watershed)
        layout_missing.addLayout(button_row_missing)
        
        group_missing.setLayout(layout_missing)
        layout.addWidget(group_missing)
        
        # --- 4. Interaction ---
        group_interact = QGroupBox("Interaction")
        layout_interact = QVBoxLayout()
        button_row1 = QHBoxLayout()
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setToolTip("Undo the last operation (shortcut: Shift+Z)")
        self.btn_undo.clicked.connect(self.undo_action)
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.setToolTip("Redo the last undone operation (shortcut: Shift+B)")
        self.btn_redo.clicked.connect(self.redo_action)
        self.btn_commit = QPushButton("Commit")
        self.btn_save_label = QPushButton("Export Label")
        self.btn_save_label.setToolTip("Export the current label layer as a TIFF file.")
        self.btn_save_label.clicked.connect(self._save_current_label_layer_as_file)
        self.btn_commit.setToolTip("Commit all changes to the original layer (shortcut: Shift+S)")
        self.btn_commit.clicked.connect(self.commit_action)
        shortcut_undo = QShortcut(QKeySequence("Shift+Z"), self)
        shortcut_undo.activated.connect(self.undo_action)
        shortcut_redo = QShortcut(QKeySequence("Shift+B"), self)
        shortcut_redo.activated.connect(self.redo_action)
        shortcut_commit = QShortcut(QKeySequence("Shift+S"), self)
        shortcut_commit.activated.connect(self.commit_action)
        
        button_row1.addWidget(self.btn_undo)
        button_row1.addWidget(self.btn_redo)
        button_row1.addWidget(self.btn_commit)
        button_row1.addWidget(self.btn_save_label)
        layout_interact.addLayout(button_row1)

        group_interact.setLayout(layout_interact)
        layout.addWidget(group_interact)
        
        layout.addStretch()

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        
        # Connect Signals
        self.setup_connections()
        self._event_connections = [
            self.viewer.layers.events.inserted.connect(self.refresh_layers),
            self.viewer.layers.events.removed.connect(self.refresh_layers),
        ]
        
        # Initial refresh
        self.refresh_layers()
        self._apply_scaling()
    def toggle_manual_input(self, text):
        is_manual = text == "Manual"
        is_plane = text == "Plane"
        is_auto = text == "Auto"
        self.coords_widget.setVisible(is_manual)
        self.param_widget.setVisible(is_auto)
        self.plane_widget.setVisible(is_plane)
        if hasattr(self, 'sampling_rate_label'):
            self.sampling_rate_label.setVisible(not is_plane)
            self.txt_sample_r.setVisible(not is_plane)
        if hasattr(self, 'target_widget'):
            self.target_widget.setVisible(not is_plane)
        if hasattr(self, 'btn_remove_aux_layer_under'):
            self.btn_remove_aux_layer_under.setVisible(is_manual or is_plane)
        if is_plane:
            self.combo_split_mode.setMaximumWidth(1919810)
        else:
            pass

    def setup_connections(self):
        # self.txt_label_id.textChanged.connect(lambda t: self.sync_input(t, self.slider_label_id))
        # self.slider_label_id.valueChanged.connect(lambda v: self.txt_label_id.setText(str(v)))
        self.txt_label_id.textChanged.connect(self._debounced_apply_hide_non_target)
        self.btn_prev.clicked.connect(self.prev_label)
        self.btn_next.clicked.connect(self.next_label)
        # self.btn_select.clicked.connect(self.select_label)
        shortcut_prev = QShortcut(QKeySequence("A"), self)
        shortcut_prev.activated.connect(self.prev_label)
        shortcut_next = QShortcut(QKeySequence("D"), self)
        shortcut_next.activated.connect(self.next_label)
        shortcut_view_labels_toggle = QShortcut(QKeySequence("Shift+R"), self)
        shortcut_view_labels_toggle.activated.connect(self._toggle_view_labels_filter)
        shortcut_hide_non_target = QShortcut(QKeySequence("F"), self)
        shortcut_hide_non_target.activated.connect(self._toggle_hide_non_target_labels_shortcut)
        shortcut_remove_aux_layer = QShortcut(QKeySequence("Shift+C"), self)
        shortcut_remove_aux_layer.activated.connect(self.remove_all_aux_layers)

        if hasattr(self, "chk_hide_non_target_labels"):
            self.chk_hide_non_target_labels.stateChanged.connect(self._on_hide_non_target_checkbox_changed)

    def sync_input(self, text, slider):
        if not text.isdigit(): return
        val = int(text)
        if val != slider.value():
            slider.setValue(val)

    def refresh_layers(self, event=None):
        # Refresh Label Layers
        curr_lbl = self.layer_combo.currentText()
        self.layer_combo.clear()
        lbl_items = [l.name for l in self.viewer.layers if isinstance(l, napari.layers.Labels)]
        lbl_items += [name for name, layer in self._detached_original_layers.items() if isinstance(layer, napari.layers.Labels) and name not in lbl_items]
        self.layer_combo.addItems(lbl_items)
        if curr_lbl in lbl_items:
            self.layer_combo.setCurrentText(curr_lbl)

        # Refresh Image Layers
        curr_img = self.image_combo.currentText()
        self.image_combo.clear()
        img_items = [l.name for l in self.viewer.layers if isinstance(l, napari.layers.Image)]
        img_items += [name for name, layer in self._detached_original_layers.items() if isinstance(layer, napari.layers.Image) and name not in img_items]
        self.image_combo.addItems(img_items)
        if curr_img in img_items:
            self.image_combo.setCurrentText(curr_img)

        # self._auto_enable_show_original_after_import()
        self._schedule_global_layer_order_check()
    def select_coordinates(self):
        """
        Points2DGMM
        naparisplit
        """
        if not self.fix_label_layer_name:
            show_error("Please extract a bounding box first.")
            return
        if self.viewer.dims.ndisplay == 3:
            show_error("napari does not support point picking in 3D. Please switch to 2D mode (click the 2D button) before selecting points.")
            return
        if self.gmm_points_layer_name in self.viewer.layers:
            self.gmm_points_layer = self.viewer.layers[self.gmm_points_layer_name]
            self.viewer.layers.selection.active = self.gmm_points_layer
            show_info("Points layer activated. You can add, delete, or drag GMM center coordinate points on different 2D planes.")
        else:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
            layer_shape = label_layer.data.shape  # (z, y, x)
            self.gmm_points_layer = self.viewer.add_points(
                ndim=3,
                name=self.gmm_points_layer_name,
                size=1,
                face_color='white',
                border_color='red',
            )
            points_data_connection = self.gmm_points_layer.events.data.connect(self._sync_points_to_textbox)
            self._points_layer_connections.append(points_data_connection)
            self.viewer.layers.selection.active = self.gmm_points_layer
            self.gmm_points_layer.mode = 'add'
            
            show_info("Points layer created. You can add, delete, or drag GMM center coordinate points on different 2D planes.")
    
    def _sync_points_to_textbox(self, event=None):
        """
        PointsCoordsTarget Labels

        1. PointsCoordsZ,Y,X;Z,Y,X;...
        2. label
        3. Target Labels
        """
        if self.gmm_points_layer is None or self.gmm_points_layer_name not in self.viewer.layers:
            return
        
        points_data = self.gmm_points_layer.data
        
        if len(points_data) == 0:
            self.txt_manual_coords.setText("")
            self.txt_gmm_target_labels.setText("")
            return
        coord_strings = []
        labels_found = set()
        label_layer = None
        if self.fix_label_layer_name and self.fix_label_layer_name in self.viewer.layers:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
        
        for point in points_data:
            z, y, x = int(round(point[0])), int(round(point[1])), int(round(point[2]))
            coord_strings.append(f"{z},{y},{x}")
            if label_layer is not None:
                try:
                    label_shape = label_layer.data.shape
                    if (0 <= z < label_shape[0] and 
                        0 <= y < label_shape[1] and 
                        0 <= x < label_shape[2]):
                        label_value = int(label_layer.data[z, y, x])
                        if label_value > 0:
                            labels_found.add(label_value)
                except (IndexError, ValueError) as e:
                    continue
        coords_text = " ".join(coord_strings)
        self.txt_manual_coords.setText(coords_text)
        if labels_found:
            labels_sorted = sorted(labels_found)
            labels_text = " ".join(str(label) for label in labels_sorted)
            self.txt_gmm_target_labels.setText(labels_text)
        else:
            self.txt_gmm_target_labels.setText("")

    # --- Logic Implementation ---
    def _get_next_available_label(self):
        """
         + 1

        -  label layer
        -  Global View  _detached_original_layers
          “ label + 1”
        -  fix layer
        """
        global_layer = None
        if self.original_label_layer_name:
            global_layer = self._get_original_layer_by_name(self.original_label_layer_name)

        if global_layer is not None:
            return int(np.max(np.asarray(global_layer.data))) + 1
        elif self.fix_label_layer_name and self.fix_label_layer_name in self.viewer.layers:
            return int(np.max(np.asarray(self.viewer.layers[self.fix_label_layer_name].data))) + 1
        else:
            return 1

    def calculate_centers_action(self):
        layer_name = self.layer_combo.currentText()
        if not layer_name: return
        layer = self._get_original_layer_by_name(layer_name)
        
        show_info("Calculating centers...")
        self.centers, self.sorted_labels = calculate_centers(layer.data)
        lbl = int(self.txt_label_id.text())
        self._update_box_size_from_cell_diameter(lbl)
        # if self.sorted_labels:
        #     max_lbl = self.sorted_labels[-1]
        #     min_dim = min(layer.data.shape)
            
        show_info(f"Calculated centers for {len(self.sorted_labels)} cells.")
    def _update_centers_for_new_labels(self, old_labels_set):
        """
        
        :
            old_labels_set: set
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return

        layer = self.viewer.layers[self.fix_label_layer_name]
        current_labels = set(np.unique(layer.data))
        current_labels.discard(0)
        new_labels = current_labels - old_labels_set

        if len(new_labels) == 0:
            return
        from scipy.ndimage import center_of_mass
        new_labels_array = np.array(list(new_labels))
        coms = center_of_mass(np.ones_like(layer.data), labels=layer.data, index=new_labels_array)
        if not isinstance(coms, list):
            if len(new_labels_array) == 1:
                coms = [coms]
            else:
                coms = list(coms)
        new_labels_added = False
        for lbl, com in zip(new_labels_array, coms):
            lbl_int = int(lbl)
            if lbl_int not in self.centers:
                new_labels_added = True
            self.centers[lbl_int] = tuple(com)
        if new_labels_added:
            self.sorted_labels = sorted(self.centers.keys())

        show_info(f"Updated centers for {len(new_labels)} new cell(s).")
    
    def _update_centers_for_affected_labels(self, old_labels_set):
        """
        
        :
            old_labels_set: set
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return

        layer = self.viewer.layers[self.fix_label_layer_name]
        current_labels = set(np.unique(layer.data))
        current_labels.discard(0)
        new_labels = current_labels - old_labels_set
        affected_labels = current_labels & old_labels_set
        removed_labels = old_labels_set - current_labels
        labels_to_update = new_labels | affected_labels

        if len(labels_to_update) == 0 and len(removed_labels) == 0:
            return

        from scipy.ndimage import center_of_mass
        if len(labels_to_update) > 0:
            labels_array = np.array(list(labels_to_update))
            coms = center_of_mass(np.ones_like(layer.data), labels=layer.data, index=labels_array)
            if not isinstance(coms, list):
                if len(labels_array) == 1:
                    coms = [coms]
                else:
                    coms = list(coms)
            new_labels_added = False
            for lbl, com in zip(labels_array, coms):
                lbl_int = int(lbl)
                if lbl_int not in self.centers:
                    new_labels_added = True
                self.centers[lbl_int] = tuple(com)
        else:
            new_labels_added = False
        centers_keys_to_remove = []
        for lbl in removed_labels:
            lbl_int = int(lbl)
            if lbl_int in self.centers:
                centers_keys_to_remove.append(lbl_int)
        
        for k in centers_keys_to_remove:
            del self.centers[k]
        if new_labels_added or centers_keys_to_remove:
            self.sorted_labels = sorted(self.centers.keys())

        update_count = len(labels_to_update)
        remove_count = len(centers_keys_to_remove)
        if update_count > 0 or remove_count > 0:
            msg_parts = []
            if update_count > 0:
                msg_parts.append(f"Updated centers for {update_count} label(s)")
            if remove_count > 0:
                msg_parts.append(f"Removed centers for {remove_count} deleted label(s)")
            show_info("; ".join(msg_parts) + ".")
    def _update_box_size_from_cell_diameter(self, target_label):
        """
        box_size2
        """
        lbl_layer_name = self.layer_combo.currentText()
        if not lbl_layer_name:
            return False
        
        try:
            lbl_layer = self._get_original_layer_by_name(lbl_layer_name)
            coords = np.where(lbl_layer.data == target_label)
            if len(coords[0]) > 0:
                dz = np.ptp(coords[0]) + 1
                dy = np.ptp(coords[1]) + 1
                dx = np.ptp(coords[2]) + 1
                cell_diameter = max(dz, dy, dx)
                box_size = int(cell_diameter * 2)
                self.txt_size.setValue(box_size)
                return True
        except Exception as e:
            print(f"Failed to update box size from cell diameter: {e}")
        return False
    
    def _clear_view_labels_for_navigation(self):
        """ Next / Previous  View Labels View Labels """
        if hasattr(self, "txt_view_labels") and self.txt_view_labels is not None:
            try:
                self.txt_view_labels.blockSignals(True)
                self.txt_view_labels.clear()
            finally:
                self.txt_view_labels.blockSignals(False)
        self.view_labels_filter_enabled = False

    def _schedule_save_state(self):
        """ undo """
        if not hasattr(self, '_save_state_timer') or self._save_state_timer is None:
            self._schedule_save_state()
            return
        self._pending_state_dirty = True
        self._save_state_timer.start()

    def _flush_pending_save_state(self):
        if not getattr(self, '_pending_state_dirty', False):
            return
        self._pending_state_dirty = False
        self.save_state()

    def next_label(self):
        try:
            self._flush_pending_save_state()
            self._clear_view_labels_for_navigation()
            self._reset_show_original_image_checkbox()
            curr = int(self.txt_label_id.text())
            if not self.centers:
                show_error("Please calculate centers first.")
                return
            
            all_labels = sorted(self.centers.keys())
            curr_idx = None
            for i, lbl in enumerate(all_labels):
                if lbl >= curr:
                    curr_idx = i
                    break
            
            if curr_idx is None:
                for lbl in all_labels:
                    if lbl > curr:
                        self.txt_label_id.setText(str(lbl))
                        self._update_box_size_from_cell_diameter(lbl)
                        self.extract_bounding_box()
                        return
                show_error(f"No label greater than {curr} found.")
                return
            
            if curr_idx < len(all_labels) - 1:
                nxt = all_labels[curr_idx + 1]
                self.txt_label_id.setText(str(nxt))
                self._update_box_size_from_cell_diameter(nxt)
                self.extract_bounding_box()
            else:
                show_error(f"Label {curr} is the last label.")
        except ValueError:
            pass
    def prev_label(self):
        try:
            self._flush_pending_save_state()
            self._clear_view_labels_for_navigation()
            self._reset_show_original_image_checkbox()
            curr = int(self.txt_label_id.text())
            if not self.centers:
                show_error("No labels available. Please calculate centers first.")
                return
            
            all_labels = sorted(self.centers.keys())
            curr_idx = None
            for i, lbl in enumerate(all_labels):
                if lbl >= curr:
                    curr_idx = i
                    break
            
            if curr_idx is None:
                for lbl in reversed(all_labels):
                    if lbl < curr:
                        self.txt_label_id.setText(str(lbl))
                        self._update_box_size_from_cell_diameter(lbl)
                        self.extract_bounding_box()
                        return
                show_error(f"No label less than {curr} found.")
                return
            
            if curr_idx > 0:
                prev = all_labels[curr_idx - 1]
                self.txt_label_id.setText(str(prev))
                self._update_box_size_from_cell_diameter(prev)
                self.extract_bounding_box()
            else:
                show_error(f"Label {curr} is the first label.")
        except ValueError:
            pass

    @staticmethod
    def _parse_label_list_text(raw: str) -> list[int]:
        """ ID /"""
        if not raw or not str(raw).strip():
            return []
        return [int(x) for x in str(raw).split() if x.strip()]

    def _bbox_target_ids_for_hide_mode(self):
        """ bbox  /  View Labels """
        raw = self.txt_view_labels.text().strip() if hasattr(self, "txt_view_labels") else ""
        if not raw:
            return []
        ids = self._parse_label_list_text(raw)
        ids = [x for x in ids if x != 0]
        return ids

    def _view_labels_enabled(self) -> bool:
        """ View Labels  ID"""
        ids = self._bbox_target_ids_for_hide_mode()
        return len(ids) > 0

    def _get_active_visibility_ids(self) -> list[int]:
        """Focus  View Labels"""
        if getattr(self, "_focus_filter_enabled", False):
            return self._get_focus_target_ids()
        if getattr(self, "view_labels_filter_enabled", False):
            return self._bbox_target_ids_for_hide_mode()
        return []

    def _compose_masked_view_from_full(self, full_data, ids: list[int]):
        """ masked """
        full = np.asarray(full_data)
        ids = tuple(int(v) for v in ids if int(v) != 0)
        if not ids:
            return full.copy()
        cache = getattr(self, '_masked_view_cache', None)
        if cache is not None:
            c_shape, c_dtype, c_ids, c_src_ptr, c_out = cache
            if c_shape == full.shape and c_dtype == full.dtype and c_ids == ids and c_src_ptr == full.__array_interface__.get('data', (None,))[0]:
                return c_out.copy()
        mask = np.isin(full, ids)
        out = np.where(mask, full, np.zeros_like(full))
        self._masked_view_cache = (full.shape, full.dtype, ids, full.__array_interface__.get('data', (None,))[0], out)
        return out.copy()

    def _set_fix_label_data_silently(self, data, *, update_full: bool = False):
        """ LabelFix  data-change  Undo/Redo"""
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        layer = self.viewer.layers[self.fix_label_layer_name]
        arr = np.asarray(data)
        prev_suspend = getattr(self, "_suspend_label_data_events", False)
        self._suspend_label_data_events = True
        try:
            changed = True
            try:
                old = np.asarray(layer.data)
                changed = old.shape != arr.shape or not np.array_equal(old, arr)
            except Exception:
                changed = True
            if changed:
                try:
                    layer.data = np.array(arr, copy=True)
                except Exception:
                    layer.data[...] = arr
                layer.refresh()
            if update_full:
                self._view_labels_full_data = np.array(arr, copy=True)
            self._label_prev_data = np.asarray(layer.data).copy()
        finally:
            self._suspend_label_data_events = prev_suspend

    def _sync_current_fix_layer_to_full_cache(self):
        """
         LabelFix “” _view_labels_full_data

         napari // layer.data
         layer.events.data commit/ Focus 
         commit “”

        ----
        np.ndarray | None
             None
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return None

        layer = self.viewer.layers[self.fix_label_layer_name]
        if not isinstance(layer, napari.layers.Labels):
            return None

        try:
            current = np.asarray(layer.data).copy()
        except Exception:
            return None

        full_before = getattr(self, "_view_labels_full_data", None)
        if full_before is None or np.asarray(full_before).shape != current.shape:
            full_before = current.copy()
        else:
            full_before = np.asarray(full_before).copy()

        active_ids = self._get_active_visibility_ids()
        if active_ids:
            editable_mask = np.logical_or(full_before == 0, np.isin(full_before, active_ids))
            full_after = full_before.copy()
            full_after[editable_mask] = current[editable_mask]
        else:
            full_after = current.copy()

        self._view_labels_full_data = full_after.copy()
        return full_after

    def _apply_view_labels_visibility(self, ids: list[int]) -> None:
        """
        Focus / View Labels “ + masked ”
        - _view_labels_full_data 
        - layer.data 
         Focus  target 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        layer = self.viewer.layers[self.fix_label_layer_name]
        if not isinstance(layer, napari.layers.Labels):
            return

        full = self._sync_current_fix_layer_to_full_cache()
        if full is None or np.asarray(full).shape != np.asarray(layer.data).shape:
            full = np.asarray(layer.data).copy()
            self._view_labels_full_data = full.copy()

        display = self._compose_masked_view_from_full(full, ids)
        self._set_fix_label_data_silently(display, update_full=False)

    def _can_reextract_bbox(self):
        lbl_layer_name = self.layer_combo.currentText()
        if not lbl_layer_name or lbl_layer_name not in self.viewer.layers:
            return False
        try:
            tid = int(self.txt_label_id.text().strip())
        except ValueError:
            return False
        return tid in self.centers

    @staticmethod
    def _bbox_slices_equal(a, b):
        if a is None or b is None:
            return False
        if len(a) != len(b):
            return False
        for s1, s2 in zip(a, b):
            if s1.start != s2.start or s1.stop != s2.stop or s1.step != s2.step:
                return False
        return True

    def _read_bbox_crop_from_fix_layer(self, fix_name, bbox_slices, translate_offset):
        """LabelFix  bbox """
        if not fix_name or fix_name not in self.viewer.layers:
            return None
        return np.asarray(self.viewer.layers[fix_name].data).copy()

    def _merge_reextract_crop_preserve_targets(self, new_crop, old_local, g_full, target_ids):
        """
         target 
        g_full  bbox target_ids  targetID 
        """
        if old_local is None or new_crop.shape != old_local.shape or g_full.shape != new_crop.shape:
            return new_crop
        T = list(target_ids)
        if not T:
            return new_crop
        result = np.asarray(new_crop).copy()
        m_keep = np.isin(old_local, T)
        result[m_keep] = old_local[m_keep]
        m_erase = (old_local == 0) & np.isin(g_full, T)
        result[m_erase] = 0
        m_split = (old_local > 0) & (~np.isin(old_local, T)) & (np.isin(g_full, T))
        result[m_split] = old_local[m_split]
        return result

    def _get_focus_target_ids(self) -> list[int]:
        """
        Focus/F 
        - View Labels  View Labels
        - View Labels  Label ID
        """
        try:
            view_ids = self._bbox_target_ids_for_hide_mode()
        except Exception:
            view_ids = []

        if view_ids:
            return view_ids

        try:
            curr = int(self.txt_label_id.text().strip())
            if curr != 0:
                return [curr]
        except (ValueError, TypeError):
            pass

        return []

    def _toggle_hide_non_target_labels_shortcut(self):
        """
         F
        - View Labels  View Labels 
        - View Labels  Label ID
        - 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return

        ids = self._get_focus_target_ids()
        if not ids:
            show_error("Neither View Labels nor Label ID has a valid label.")
            return

        enabled = getattr(self, "_focus_filter_enabled", False)

        if enabled:
            self._apply_view_labels_visibility([])
            self._focus_filter_enabled = False
            if hasattr(self, "chk_hide_non_target_labels"):
                self.chk_hide_non_target_labels.blockSignals(True)
                self.chk_hide_non_target_labels.setChecked(False)
                self.chk_hide_non_target_labels.blockSignals(False)
        else:
            self._apply_view_labels_visibility(ids)
            self._focus_filter_enabled = True
            if hasattr(self, "chk_hide_non_target_labels"):
                self.chk_hide_non_target_labels.blockSignals(True)
                self.chk_hide_non_target_labels.setChecked(True)
                self.chk_hide_non_target_labels.blockSignals(False)

    def _on_hide_non_target_checkbox_changed(self, state):
        """
        Focus  View Labels 
        -  F 
        - 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return

        if state == Qt.Checked:
            ids = self._get_focus_target_ids()
            if not ids:
                show_error("Neither View Labels nor Label ID has a valid label.")
                self.chk_hide_non_target_labels.blockSignals(True)
                self.chk_hide_non_target_labels.setChecked(False)
                self.chk_hide_non_target_labels.blockSignals(False)
                self._focus_filter_enabled = False
                return

            self._apply_view_labels_visibility(ids)
            self._focus_filter_enabled = True
        else:
            self._apply_view_labels_visibility([])
            self._focus_filter_enabled = False
            self.view_labels_filter_enabled = False

    def _on_view_labels_text_changed_debounced(self, _text: str):
        """
        View Labels “ Apply ”
        
        """
        return

    def _apply_view_labels_from_button(self):
        """ View Labels  bbox  Focus """
        raw = self.txt_view_labels.text().strip() if hasattr(self, "txt_view_labels") else ""
        self.view_labels_filter_enabled = bool(raw)
        if hasattr(self, "_view_labels_debounce_timer"):
            self._view_labels_debounce_timer.stop()

        if hasattr(self, "chk_hide_non_target_labels"):
            self.chk_hide_non_target_labels.blockSignals(True)
            self.chk_hide_non_target_labels.setChecked(True)
            self.chk_hide_non_target_labels.blockSignals(False)

        self._focus_filter_enabled = True
        self._apply_view_labels_from_text(force_focus=True)

    def _apply_view_labels_from_text(self, force_focus: bool = False):
        """ View Labels  bbox force_focus=True  Focus """
        ids = self._bbox_target_ids_for_hide_mode()
        if force_focus:
            if not ids:
                ids = self._get_focus_target_ids()
            self._apply_view_labels_visibility(ids)
            return
        self._apply_view_labels_visibility(ids)

    def _toggle_view_labels_filter(self):
        """
         Ctrl+R View Labels 
        -  View Labels 
        -  target label View Labels 
        """
        self.view_labels_filter_enabled = not getattr(self, "view_labels_filter_enabled", False)
        if self.view_labels_filter_enabled:
            self._apply_view_labels_from_text()
        else:
            self._apply_view_labels_visibility([])

    def _on_debounced_hide_non_target_timeout(self):
        """Label ID  Label ID """
        return

    def _apply_hide_non_target_colormap(self, state):
        """
         -LabelFix  colormap  target 
         target  use_selection target 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        layer = self.viewer.layers[self.fix_label_layer_name]
        if not isinstance(layer, napari.layers.Labels):
            return
        view_ids = self._bbox_target_ids_for_hide_mode()
        try:
            if view_ids and len(view_ids) == 1:
                target_label = int(view_ids[0])
            else:
                target_label = int(self.txt_label_id.text().strip())
        except (ValueError, TypeError):
            return
        try:
            col = getattr(layer, 'colormap', None)
            use_selection_attr = getattr(col, 'use_selection', None)
            copy_fn = getattr(col, 'model_copy', None) or getattr(col, 'copy', None)
            if col is not None and use_selection_attr is not None and copy_fn is not None:
                if state == Qt.Checked:
                    if col.use_selection is True and getattr(col, 'selection', None) == target_label:
                        return
                else:
                    if col.use_selection is False:
                        return
                if state == Qt.Checked:
                    layer.colormap = copy_fn(update={'use_selection': True, 'selection': target_label})
                else:
                    layer.colormap = copy_fn(update={'use_selection': False})
                layer.refresh()
            else:
                if hasattr(col, 'use_selection'):
                    col.use_selection = (state == Qt.Checked)
                    if state == Qt.Checked and hasattr(col, 'selection'):
                        col.selection = target_label
                    layer.refresh()
                else:
                    data = layer.data
                    unique = np.unique(data)
                    unique = unique[unique != 0]
                    transparent = np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32)
                    color = dict(layer.color) if getattr(layer, 'color', None) else {}
                    for lid in unique:
                        if int(lid) != target_label:
                            color[int(lid)] = transparent
                    if state == Qt.Checked:
                        layer.color = color
                    else:
                        layer.color = {}
                    layer.refresh()
        except Exception as e:
            show_error(f"Hide Non-Target Labels application failed: {e}")

    def _debounced_apply_hide_non_target(self):
        """
        Label ID 
        -  View Labels
        -  Focus 
        """
        if (
            getattr(self, "_focus_filter_enabled", False)
            and self.fix_label_layer_name
            and self.fix_label_layer_name in self.viewer.layers
        ):
            ids = self._get_focus_target_ids()
            if ids:
                self._apply_view_labels_visibility(ids)
        if hasattr(self, '_hide_non_target_debounce_timer'):
            self._hide_non_target_debounce_timer.stop()
            self._hide_non_target_debounce_timer.start(350)

    def _apply_hide_non_target_if_checked(self):
        """extract / restore  Focus / View Labels """
        self._apply_view_labels_visibility(self._get_active_visibility_ids())

    def extract_bounding_box(self):
        self._flush_pending_save_state()
        self._reset_show_original_image_checkbox()
        try:
            val = int(self.txt_label_id.text())
        except ValueError:
            val = self.sorted_labels[0] if self.sorted_labels else 0
            self.txt_label_id.setText(str(val))

        lbl_layer_name = self.layer_combo.currentText()
        img_layer_name = self.image_combo.currentText()
        if not lbl_layer_name:
            return

        try:
            target_label = int(self.txt_label_id.text())
        except ValueError:
            show_error("Invalid label ID.")
            return

        if target_label not in self.centers:
            show_error(f"Label {target_label} center not found. Please calculate centers first.")
            return

        try:
            box_size = int(self.txt_size.value())
        except ValueError:
            show_error("Invalid box size.")
            return

        center = self.centers[target_label]
        lbl_layer = self._get_original_layer_by_name(lbl_layer_name)

        bbox = get_bbox(center, box_size, lbl_layer.data.shape)
        preserve_edits = getattr(self, '_extract_preserve_target_edits', False)
        self._extract_preserve_target_edits = False
        prev_bbox = self.current_bbox
        prev_translate = self.bbox_translate_offset
        self.current_bbox = bbox
        self.original_label_layer_name = lbl_layer_name
        self.original_image_layer_name = img_layer_name

        if not getattr(self, "_json_path_user_locked", False):
            if img_layer_name:
                self.json_file_path = self._build_json_path_for_image_layer(img_layer_name)
            else:
                self.json_file_path = os.path.abspath("NuPatch3D_edit_log.json")
        self._update_json_path_display()

        original_img_layer = None
        crop_img = None
        if img_layer_name:
            img_layer = self._get_original_layer_by_name(img_layer_name)
            original_img_layer = img_layer
            try:
                crop_img = np.asarray(img_layer.data[bbox]).copy()
                self.fix_image_layer_name = f"{img_layer_name}-Crop"
            except Exception as e:
                show_error(f"Failed to crop image: {e}")
                self.fix_image_layer_name = None
                crop_img = None
        else:
            self.fix_image_layer_name = None

        G_full = np.asarray(lbl_layer.data[bbox]).copy()
        crop_lbl = G_full.copy()
        self._view_labels_full_data = G_full.copy()

        view_ids = self._bbox_target_ids_for_hide_mode()
        if view_ids:
            self._bbox_commit_use_target_mask = True
            self._bbox_commit_target_ids = list(view_ids)
        else:
            self._bbox_commit_use_target_mask = False
            self._bbox_commit_target_ids = []

        T_merge = view_ids or [target_label]
        if preserve_edits and self.fix_label_layer_name and self.fix_label_layer_name in self.viewer.layers:
            if self._bbox_slices_equal(prev_bbox, bbox):
                old_local = self._read_bbox_crop_from_fix_layer(self.fix_label_layer_name, prev_bbox, prev_translate)
                if old_local is not None and old_local.shape == crop_lbl.shape:
                    crop_lbl = self._merge_reextract_crop_preserve_targets(crop_lbl, old_local, G_full, T_merge)

        self.fix_label_layer_name = f"{lbl_layer_name}-LabelFix"
        self.bbox_translate_offset = None

        try:
            if crop_img is not None and self.fix_image_layer_name:
                contrast_limits = getattr(original_img_layer, 'contrast_limits', None) if original_img_layer is not None else None
                if self.fix_image_layer_name in self.viewer.layers:
                    img_fix_layer = self.viewer.layers[self.fix_image_layer_name]
                    img_fix_layer.data = np.asarray(crop_img).copy()
                    if contrast_limits is not None:
                        img_fix_layer.contrast_limits = contrast_limits
                    img_fix_layer.refresh()
                else:
                    img_fix_layer = self.viewer.add_image(np.asarray(crop_img).copy(), name=self.fix_image_layer_name)
                    if contrast_limits is not None:
                        img_fix_layer.contrast_limits = contrast_limits

            if self.fix_label_layer_name in self.viewer.layers:
                label_layer = self.viewer.layers[self.fix_label_layer_name]
                label_layer.data = np.asarray(crop_lbl).copy()
                label_layer.refresh()
            else:
                label_layer = self.viewer.add_labels(np.asarray(crop_lbl).copy(), name=self.fix_label_layer_name)
        except Exception as e:
            show_error(f"Failed to create bbox layers: {e}")
            return

        self.undo_stack.clear()
        self.redo_stack.clear()
        self.edit_log.clear()
        self._pending_state_dirty = False
        self.save_state()
        self._setup_fix_label_layer_logging()

        if self.fix_label_layer_name and self.fix_label_layer_name in self.viewer.layers:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
            bbox_shape = label_layer.data.shape
            center_z = bbox_shape[0] // 2
            center_y = bbox_shape[1] // 2
            center_x = bbox_shape[2] // 2
            self.plane_center_point = np.array([center_z, center_y, center_x], dtype=float)
            if hasattr(self, 'txt_plane_z'):
                self.txt_plane_z.setRange(0, bbox_shape[0] - 1)
                self.txt_plane_y.setRange(0, bbox_shape[1] - 1)
                self.txt_plane_x.setRange(0, bbox_shape[2] - 1)
                self.txt_plane_z.blockSignals(True)
                self.txt_plane_y.blockSignals(True)
                self.txt_plane_x.blockSignals(True)
                self.txt_plane_z.setValue(center_z)
                self.txt_plane_y.setValue(center_y)
                self.txt_plane_x.setValue(center_x)
                self.txt_plane_z.blockSignals(False)
                self.txt_plane_y.blockSignals(False)
                self.txt_plane_x.blockSignals(False)

        try:
            current_label = int(self.txt_label_id.text())
            self.txt_gmm_target_labels.setText(str(current_label))
            if hasattr(self, 'txt_plane_target_labels'):
                self.txt_plane_target_labels.setText(str(current_label))
            self.txt_merge_labels.setText(str(current_label))
        except ValueError:
            pass

        self._apply_hide_non_target_if_checked()
        self._apply_original_layer_presence()
        self._center_view_on_current_bbox_layer(delayed=True)
    # def toggle_rotation_center(self):
    #     """
    #     """
    #     if self.current_bbox is None or self.fix_label_layer_name is None:
    #         show_error("Please extract a bounding box first.")
    #         return
    #     if self.bbox_camera_center is None:
    #         try:
    #             if self.fix_label_layer_name in self.viewer.layers:
    #                 crop = self.viewer.layers[self.fix_label_layer_name].data
    #                 shape = np.array(crop.shape, dtype=float)
    #                 self.bbox_camera_center = (shape / 2.0)[::-1]
    #         except Exception as e:
    #             show_error(f"Failed to compute bbox center: {e}")
    #             return
    #         try:
    #             self.default_camera_center = np.array(self.viewer.camera.center, dtype=float)
    #             # print(f"Preserving default camera center: {self.default_camera_center}")
    #         except Exception:
    #             self.default_camera_center = None
    #             self.viewer.camera.center = self.bbox_camera_center
    #             print(f"Switch to bbox camera center-manual: {self.bbox_camera_center}")
    #         try:
    #             if self.default_camera_center is not None:
    #                 self.viewer.camera.center = self.default_camera_center
    #                 print(f"Switch to default camera center-manual: {self.default_camera_center}")
    #         except Exception as e:
    #             self.default_camera_center = None

    #         self.rotation_center_on_bbox = False
    #     else:
    #         show_error("This should never happen, come on!")
    #         return
# endregion

    def _setup_fix_label_layer_logging(self):
        """
         fix_label_layer  napari data /
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            self._label_prev_data = None
            return
        
        layer = self.viewer.layers[self.fix_label_layer_name]
        if hasattr(self, 'label_layer_data_connection') and self.label_layer_data_connection is not None:
            try:
                self.label_layer_data_connection.disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
            self.label_layer_data_connection = None
        try:
            self._label_prev_data = np.asarray(layer.data).copy()
        except Exception:
            self._label_prev_data = None
        
        try:
            self.label_layer_data_connection = layer.events.data.connect(
                self._on_fix_labels_data_changed
            )
        except Exception:
            self.label_layer_data_connection = None

    def _on_fix_labels_data_changed(self, event=None):
        """
         napari Labels / JSON
         Focus / View Labels  masked 
         _view_labels_full_data
        -  target labels
        -  0 
         napari 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            self._label_prev_data = None
            return

        layer = self.viewer.layers[self.fix_label_layer_name]

        if getattr(self, "_suspend_label_data_events", False):
            try:
                self._label_prev_data = np.asarray(layer.data).copy()
            except Exception:
                self._label_prev_data = None
            return

        try:
            current = np.asarray(layer.data).copy()
        except Exception:
            return

        full_before = getattr(self, "_view_labels_full_data", None)
        if full_before is None or np.asarray(full_before).shape != current.shape:
            full_before = current.copy()
            self._view_labels_full_data = full_before.copy()
        else:
            full_before = np.asarray(full_before).copy()

        if self._label_prev_data is None or self._label_prev_data.shape != current.shape:
            self._label_prev_data = current.copy()
            if not self._get_active_visibility_ids():
                self._view_labels_full_data = current.copy()
            return

        diff_mask = current != self._label_prev_data
        if not np.any(diff_mask):
            return

        active_ids = self._get_active_visibility_ids()
        if active_ids:
            editable_mask = np.logical_or(full_before == 0, np.isin(full_before, active_ids))
            applied_mask = np.logical_and(diff_mask, editable_mask)
            full_after = full_before.copy()
            if np.any(applied_mask):
                full_after[applied_mask] = current[applied_mask]
            display_after = self._compose_masked_view_from_full(full_after, active_ids)
        else:
            applied_mask = diff_mask
            full_after = current.copy()
            display_after = current.copy()

        if not np.any(applied_mask):
            self._set_fix_label_data_silently(self._compose_masked_view_from_full(full_before, active_ids), update_full=False)
            return

        try:
            coords = np.where(applied_mask)
            coords_arr = np.stack(coords, axis=1)
            z_min, y_min, x_min = coords_arr.min(axis=0)
            z_max, y_max, x_max = coords_arr.max(axis=0) + 1
            num_changed = int(applied_mask.sum())
        except Exception:
            z_min = y_min = x_min = 0
            z_max, y_max, x_max = current.shape
            num_changed = int(applied_mask.sum())

        try:
            changed_labels = np.unique(full_after[applied_mask])
            changed_labels = [int(x) for x in changed_labels if int(x) != 0]
        except Exception:
            changed_labels = []

        mode = getattr(layer, "mode", None)
        selected_label = getattr(layer, "selected_label", None)
        brush_size = getattr(layer, "brush_size", None)

        def _to_int_or_none(v):
            if isinstance(v, (int, np.integer)):
                return int(v)
            return None

        def _to_float_or_none(v):
            if isinstance(v, (int, float, np.integer, np.floating)):
                return float(v)
            return None

        normalized_mode = str(mode) if mode is not None else None
        normalized_selected_label = _to_int_or_none(selected_label)
        normalized_brush_size = _to_float_or_none(brush_size)

        algorithm = "NapariLabelsEdit"
        if normalized_mode is not None:
            m = normalized_mode.lower()
            if "paint" in m:
                algorithm = "NapariPaint"
            elif "fill" in m:
                algorithm = "NapariFill"
            elif "erase" in m:
                algorithm = "NapariErase"

        params = {
            "napari_mode": normalized_mode,
            "selected_label": normalized_selected_label,
            "brush_size": normalized_brush_size,
            "num_changed_voxels": num_changed,
            "changed_bbox": [
                [int(z_min), int(z_max)],
                [int(y_min), int(y_max)],
                [int(x_min), int(x_max)],
            ],
            "visibility_filter_active": bool(active_ids),
            "visibility_target_ids": [int(v) for v in active_ids],
        }

        self._view_labels_full_data = full_after.copy()

        timestamp = datetime.now()
        self.log_edit(
            algorithm=algorithm,
            label_ids=changed_labels,
            params=params,
            timestamp=timestamp,
        )

        self.save_state()

        if active_ids:
            if not np.array_equal(display_after, current):
                self._set_fix_label_data_silently(display_after, update_full=False)
            else:
                self._label_prev_data = current.copy()
                layer.refresh()
        else:
            self._label_prev_data = current.copy()

    def save_state(self):
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        layer = self.viewer.layers[self.fix_label_layer_name]
        full = self._sync_current_fix_layer_to_full_cache()
        if full is None or np.asarray(full).shape != np.asarray(layer.data).shape:
            full = getattr(self, "_view_labels_full_data", None)
            if full is None or np.asarray(full).shape != np.asarray(layer.data).shape:
                full = np.asarray(layer.data).copy()
                self._view_labels_full_data = full.copy()
        data = np.asarray(full).copy()
        if self.undo_stack and np.array_equal(self.undo_stack[-1], data):
            return
        self.undo_stack.append(data)
        self.redo_stack.clear()

    def restore_state(self, data):
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        full = np.asarray(data).copy()
        self._view_labels_full_data = full.copy()
        display = self._compose_masked_view_from_full(full, self._get_active_visibility_ids())
        self._set_fix_label_data_silently(display, update_full=False)
        self._center_view_on_current_bbox_layer(delayed=True)

    def undo_action(self):
        self._flush_pending_save_state()
        if len(self.undo_stack) > 1:
            current = self.undo_stack.pop()
            self.redo_stack.append(current)
            prev = self.undo_stack[-1]
            self.restore_state(prev)
            if self.edit_log:
                temp_log = self.edit_log.pop()
                self.redo_log_stack.append(temp_log)
        else:
            show_info("Nothing to undo.")

    def redo_action(self):
        self._flush_pending_save_state()
        if self.redo_stack:
            data = self.redo_stack.pop()
            self.undo_stack.append(data)
            self.restore_state(data)
            if self.redo_log_stack:
                temp_log = self.redo_log_stack.pop()
                self.edit_log.append(temp_log)
        else:
            show_info("Nothing to redo.")
    def set_json_save_path(self):
        """JSON"""
        img_layer_name = self.image_combo.currentText() if hasattr(self, "image_combo") else ""
        suggested_path = self._build_json_path_for_image_layer(img_layer_name) if img_layer_name else self.json_file_path
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select JSON Save Location",
            suggested_path,
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            selected_dir = os.path.dirname(os.path.abspath(file_path))
            self.json_file_path = self._build_json_path_for_image_layer(img_layer_name, selected_dir)
            self._json_path_user_locked = True
            self._update_json_path_display()
            show_info(f"JSON file will be saved to: {self.json_file_path}")

    def _write_labels_layer_bbox_patch(self, label_layer, sub_slices, patch):
        """ patch  Labels  bbox  layer.data napari """
        base = np.asarray(label_layer.data, copy=True)
        base[sub_slices] = patch
        try:
            label_layer.data = np.array(base, copy=True)
        except Exception:
            label_layer.data[sub_slices] = patch
        try:
            label_layer.refresh()
        except Exception:
            pass
        try:
            label_layer.events.data()
        except Exception:
            pass

    def _sync_fix_layer_from_global_after_json_apply(self):
        """JSON  bbox  LabelFix  _view_labels_full_data"""
        g = self._get_original_layer_by_name(self.original_label_layer_name)
        self._sync_fix_layer_from_global_after_json_apply_for_layer(g)

    def _sync_fix_layer_from_global_after_json_apply_for_layer(self, g):
        """
         Labels  g  current_bbox  LabelFix
         Apply JSON  JSON  original_label_layer_name 
        """
        if not self.fix_label_layer_name or self.fix_label_layer_name not in self.viewer.layers:
            return
        if not self.current_bbox:
            return
        if g is None or not isinstance(g, napari.layers.Labels):
            return
        try:
            crop = np.asarray(g.data[self.current_bbox]).copy()
        except Exception:
            return
        self._view_labels_full_data = crop.copy()
        display = self._compose_masked_view_from_full(
            self._view_labels_full_data, self._get_active_visibility_ids()
        )
        self._set_fix_label_data_silently(display, update_full=False)

    def _iter_labels_layers_for_json_apply(self):
        """viewer  detached  Labels """
        seen = set()
        for layer in self.viewer.layers:
            if isinstance(layer, napari.layers.Labels):
                i = id(layer)
                if i not in seen:
                    seen.add(i)
                    yield layer
        for layer in self._detached_original_layers.values():
            if isinstance(layer, napari.layers.Labels):
                i = id(layer)
                if i not in seen:
                    seen.add(i)
                    yield layer

    def _layer_compatible_with_json_snapshot(
        self, label_layer, sub_slices, final_labels, expected_shape_tuple
    ):
        """ Labels  bbox shape """
        if not isinstance(label_layer, napari.layers.Labels):
            return False
        try:
            layer_arr = label_layer.data
            arr = np.asarray(layer_arr)
            if expected_shape_tuple is not None:
                if arr.shape != expected_shape_tuple:
                    return False
            ndim = int(arr.ndim)
            if len(sub_slices) != ndim:
                return False
            dtype = arr.dtype
            patch = np.asarray(final_labels, dtype=dtype)
            sub = arr[sub_slices]
            return patch.shape == sub.shape
        except Exception:
            return False

    def _pick_labels_layer_for_json_snapshot(
        self, recorded_name, sub_slices, final_labels, expected_shape_tuple
    ):
        """
         bbox/ label_data_shape
         None
        """
        candidates = []
        for lyr in self._iter_labels_layers_for_json_apply():
            if self._layer_compatible_with_json_snapshot(
                lyr, sub_slices, final_labels, expected_shape_tuple
            ):
                candidates.append(lyr)
        if not candidates:
            show_error(
                f"Original label layer '{recorded_name}' not found, and no other Labels layer matches the snapshot's bbox/shape."
            )
            return None
        if len(candidates) == 1:
            show_info(
                f"Applied snapshot using label layer '{candidates[0].name}' (recorded as '{recorded_name}' in JSON)."
            )
            return candidates[0]
        names = [lyr.name for lyr in candidates]
        choice, ok = QInputDialog.getItem(
            self,
            "Select Label Layer",
            f"'{recorded_name}' not found. The following Labels layers match the snapshot data, please select the layer to write to:",
            names,
            0,
            False,
        )
        if not ok:
            show_info("JSON application cancelled.")
            return None
        return candidates[names.index(choice)]

    def apply_json_log_to_current_labels(self):
        """
         JSON CommitSnapshot  bbox 
        
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select NuPatch3D JSON Log File",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                log_data = json.load(f)
        except Exception as e:
            show_error(f"Failed to read JSON log: {e}")
            return

        if not isinstance(log_data, list) or not log_data:
            show_error("JSON log file format is incorrect or empty.")
            return

        snapshot_entries = []
        for e in log_data:
            if not isinstance(e, dict) or e.get("algorithm") != "CommitSnapshot":
                continue
            if e.get("bbox") is None:
                continue
            params_e = self._log_entry_params_dict(e)
            if params_e.get("final_labels") is None:
                continue
            snapshot_entries.append(e)
        if not snapshot_entries:
            show_error(
                "The selected JSON contains no CommitSnapshot voxel data (legacy logs cannot perform voxel-level restore)."
                "Voxel-level restore depends on clicking Commit after each edit within the bbox; intermediate entries such as brush/algorithm alone will not be written back to the global volume."
                "Please use the current version to re-Commit and generate a JSON with snapshots."
            )
            return

        snapshot_entries = sort_commit_snapshot_entries_by_timestamp(snapshot_entries)

        validated = []
        for entry in snapshot_entries:
            name = entry.get("original_label_layer_name")
            if not name:
                show_error("JSON snapshot missing original_label_layer_name, cannot locate the original label layer.")
                return

            bbox_info = entry["bbox"]
            try:
                sub_slices = tuple(
                    slice(int(pair[0]), int(pair[1])) for pair in bbox_info
                )
            except (TypeError, ValueError, IndexError):
                show_error("Invalid bbox format in JSON log.")
                return

            final_labels = self._log_entry_params_dict(entry).get("final_labels")
            exp_shape_raw = entry.get("label_data_shape")
            exp_shape_t = None
            if exp_shape_raw is not None:
                try:
                    exp_shape_t = tuple(int(x) for x in exp_shape_raw)
                except (TypeError, ValueError):
                    show_error("Invalid label_data_shape format in JSON snapshot.")
                    return

            label_layer = self._get_original_layer_by_name(name)
            if label_layer is None:
                label_layer = self._pick_labels_layer_for_json_snapshot(
                    name, sub_slices, final_labels, exp_shape_t
                )
                if label_layer is None:
                    return
            elif not isinstance(label_layer, napari.layers.Labels):
                show_error(f"Layer '{name}' is not a Labels type, cannot apply JSON snapshot.")
                return
            elif not self._layer_compatible_with_json_snapshot(
                label_layer, sub_slices, final_labels, exp_shape_t
            ):
                show_error(
                    f"Layer '{name}' is incompatible with the JSON snapshot (dimension, bbox region shape"
                    f"{' or label_data_shape' if exp_shape_t is not None else ''} mismatch)."
                )
                return

            try:
                layer_arr = label_layer.data
                dtype = np.asarray(layer_arr).dtype
                arr = np.asarray(final_labels)
                if arr.dtype.kind == "f":
                    patch_i64 = np.rint(arr).astype(np.int64)
                else:
                    patch_i64 = np.asarray(arr, dtype=np.int64)
                if patch_i64.size and np.issubdtype(dtype, np.integer):
                    mv = int(patch_i64.max())
                    ii = np.iinfo(dtype)
                    if mv > ii.max:
                        show_error(
                            f"Maximum label ID ({mv}) in JSON snapshot exceeds the representable range of target layer '{label_layer.name}'"
                            f" dtype {dtype} (max {ii.max})."
                        )
                        return
                exp_max = entry.get("max_label_id")
                if exp_max is not None and patch_i64.size:
                    try:
                        exp_max_i = int(exp_max)
                    except (TypeError, ValueError):
                        exp_max_i = None
                    if exp_max_i is not None and int(patch_i64.max()) != exp_max_i:
                        show_info(
                            f"Note: JSON snapshot max_label_id ({exp_max_i}) differs from voxel maximum ({int(patch_i64.max())}),"
                            "continuing to write (this field is for integrity reference only)."
                        )
                patch = patch_i64.astype(dtype, copy=False)
            except Exception as e:
                show_error(f"Failed to parse label data from JSON: {e}")
                return

            validated.append((label_layer, label_layer.name, sub_slices, patch, name))

        for label_layer, layer_name, sub_slices, patch, _rec in validated:
            try:
                self._write_labels_layer_bbox_patch(label_layer, sub_slices, patch)
            except Exception as e:
                show_error(f"Error applying JSON snapshot to layer '{layer_name}': {e}")
                return

        applied_sub_slices_by_layer_id = {}
        for label_layer, _, sub_slices, _, _ in validated:
            applied_sub_slices_by_layer_id.setdefault(id(label_layer), []).append(sub_slices)

        synced_global_ids = set()
        fix_nm = getattr(self, "fix_label_layer_name", None)
        fix_suffix = "-LabelFix"

        def _sync_fix_if_applicable(global_layer):
            if (
                global_layer is None
                or not isinstance(global_layer, napari.layers.Labels)
                or not self.current_bbox
            ):
                return False
            if id(global_layer) in synced_global_ids:
                return False
            if not fix_nm or fix_nm not in self.viewer.layers:
                return False
            if not (fix_nm.endswith(fix_suffix) and fix_nm == f"{global_layer.name}{fix_suffix}"):
                return False
            subs = applied_sub_slices_by_layer_id.get(id(global_layer), [])
            if not any(self._bbox_slices_equal(sl, self.current_bbox) for sl in subs):
                return False
            self._sync_fix_layer_from_global_after_json_apply_for_layer(global_layer)
            synced_global_ids.add(id(global_layer))
            return True

        seen_written = set()
        for label_layer, _, _, _, _ in validated:
            lid = id(label_layer)
            if lid in seen_written:
                continue
            seen_written.add(lid)
            _sync_fix_if_applicable(label_layer)

        if self.original_label_layer_name and self.current_bbox:
            for label_layer, _, _, _, rec_name in validated:
                if rec_name == self.original_label_layer_name:
                    _sync_fix_if_applicable(label_layer)
                    break

        if (
            fix_nm
            and fix_nm.endswith(fix_suffix)
            and fix_nm in self.viewer.layers
            and self.current_bbox
        ):
            fix_base = fix_nm[: -len(fix_suffix)]
            wrote_fix_target = False
            bbox_matches_current = False
            for label_layer, _, _, _, rec_name in validated:
                if label_layer.name != fix_base and rec_name != fix_base:
                    continue
                wrote_fix_target = True
                if any(
                    self._bbox_slices_equal(sl, self.current_bbox)
                    for sl in applied_sub_slices_by_layer_id.get(id(label_layer), [])
                ):
                    bbox_matches_current = True
                    break
            if wrote_fix_target and not bbox_matches_current:
                show_info(
                    "Written back to global label layer, but current crop bbox differs from the JSON snapshot bbox; LabelFix was not auto-refreshed;"
                    "Please re-Extract to synchronize the local view."
                )

        self.save_state()
        show_info(f"Applied {len(validated)} Commit snapshots to label layer(s) in order.")

    # log_edit function
    def log_edit(self, algorithm, label_ids, params, timestamp=None):
        """
         JSON 
        - label_ids: list[int] label ["ALL_NONZERO"]
        - algorithm: str"GMM" / "BoundaryFix-Fast" / "BoundaryFix-Accurate" / "Merge" 
        - params: dict
        """
        entry = {
            "algorithm": algorithm,
            "label_ids": label_ids,
            "params": params,
            "fix_label_layer_name": self.fix_label_layer_name,
            "fix_image_layer_name": self.fix_image_layer_name,
            "original_label_layer_name": self.original_label_layer_name,
            "original_image_layer_name": self.original_image_layer_name,
            "bbox": None,
            "timestamp": (timestamp or datetime.now()).isoformat(),
        }
        if self.current_bbox is not None:
            entry["bbox"] = [
                [s.start, s.stop] if isinstance(s, slice) else list(s)
                for s in self.current_bbox
            ]

        self.edit_log.append(entry)
        # try:
        #     with open("qulab_edit_log.json", "w", encoding="utf-8") as f:
        #         json.dump(self.edit_log, f, ensure_ascii=False, indent=2)
        # except Exception as e:
        #     print(f"Failed to write edit log: {e}")
    
    
    def fix_under_segmentation(self):
        start_time = datetime.now()
        if not self.fix_label_layer_name: return
        is_manual = self.combo_split_mode.currentText() == "Manual"
        try:
            sr = float(self.txt_sample_r.text())
            if not is_manual:
                mt = 3.0
                st = 10.0
            else:
                mt = float(self.txt_merge_th.text())
                st = float(self.txt_split_th.text())
        except ValueError:
            show_error("Invalid GMM parameters.")
            return

        manual_centers = None
        if self.combo_split_mode.currentText() == "Manual":
            raw = self.txt_manual_coords.text()
            try:
                normalized = raw.replace(";", " ")
                parts = [p.strip() for p in normalized.split() if p.strip()]
                manual_centers = []
                
                for p in parts:
                    coords = [int(c) for c in p.split(',')]
                    if len(coords) != 3: raise ValueError
                    # manual_centers.append([coords[2], coords[1], coords[0]])
                    manual_centers.append([coords[0], coords[1], coords[2]])
                
            except Exception:
                show_error("Invalid coordinates format. Use Z,Y,X groups separated by spaces.")
                return
        target_labels = None
        raw_lbls = self.txt_gmm_target_labels.text().strip()
        if raw_lbls:
            try:
                target_labels = self._parse_label_list_text(raw_lbls)
                target_labels = [x for x in target_labels if x != 0]
                if len(target_labels) == 0:
                    target_labels = None
            except Exception:
                show_error("Invalid target label list. Use e.g. 4 19")
                return

        layer = self.viewer.layers[self.fix_label_layer_name]
        # next_id = None
        # if self.original_label_layer_name:
        #     global_data = self.viewer.layers[self.original_label_layer_name].data
        #     next_id = global_data.max() + 1
        # else:
        #     next_id = layer.data.max() + 1
        old_labels = set(np.unique(layer.data))
        old_labels.discard(0)
        next_id = self._get_next_available_label()
        new_data = run_gmm_fix(
            layer.data,
            mt,
            st,
            sr,
            manual_centers,
            start_new_id=next_id,
            target_labels=target_labels,
        )
        
        layer.data = new_data
        self.save_state()
        self._update_centers_for_affected_labels(old_labels)
        params = {
            "sampling_ratio": sr,
        }
        if is_manual:
            params["manual_centers"] = manual_centers
        else:
            params["merge_thresh"] = mt
            params["split_thresh"] = st

        self.log_edit(
            algorithm="GMM",
            label_ids=target_labels if target_labels is not None else ["ALL_NONZERO"],
            params=params,
            timestamp=start_time,
        )        
        show_info("GMM Fix applied.")

    def split_target_labels_by_components(self):
        start_time = datetime.now()
        if not self.fix_label_layer_name:
            return

        current_mode = self.combo_split_mode.currentText() if hasattr(self, "combo_split_mode") else "Auto"
        if current_mode == "Plane":
            raw_lbls = self.txt_plane_target_labels.text().strip()
        else:
            raw_lbls = self.txt_gmm_target_labels.text().strip()

        if not raw_lbls:
            show_error("Please set Target Labels first.")
            return

        try:
            target_labels = self._parse_label_list_text(raw_lbls)
            target_labels = [x for x in target_labels if x != 0]
        except Exception:
            show_error("Invalid target label list. Please use format: 4 19")
            return

        if len(target_labels) == 0:
            show_error("Target Labels cannot be empty and cannot contain only 0.")
            return

        layer = self.viewer.layers[self.fix_label_layer_name]
        old_labels = set(np.unique(layer.data))
        old_labels.discard(0)
        next_id = self._get_next_available_label()

        new_data, cc_stats = split_target_labels_by_connected_components(
            layer.data,
            target_labels=target_labels,
            start_new_id=next_id,
        )

        layer.data = new_data
        self.save_state()
        self._update_centers_for_affected_labels(old_labels)

        total_new_labels = int(cc_stats.get("total_new_labels", 0))
        per_label_stats = cc_stats.get("per_label", {})
        component_counts = {
            str(k): int(v.get("num_components", 0))
            for k, v in per_label_stats.items()
        }

        self.log_edit(
            algorithm="ConnectedComponentsSplit",
            label_ids=target_labels,
            params={
                "mode": current_mode,
                "start_new_id": int(next_id),
                "total_new_labels": total_new_labels,
                "component_counts": component_counts,
            },
            timestamp=start_time,
        )

        show_info(
            f"Connected components relabeling complete: processed {len(target_labels)} target label(s), added {total_new_labels} new label(s)."
        )

    def fix_over_segmentation(self):
        start_time = datetime.now()
        if not self.fix_label_layer_name: return
        
        raw = self.txt_merge_labels.text()
        try:
            labels_to_merge = self._parse_label_list_text(raw)
            if not labels_to_merge:
                return
        except Exception:
            show_error(f"Illegal label detected: {raw}")
            return

        if 0 in labels_to_merge:
            show_error("Invalid label value")
            return

        layer = self.viewer.layers[self.fix_label_layer_name]
        old_labels = set(np.unique(layer.data))
        old_labels.discard(0)

        data = layer.data.copy()
        if len(labels_to_merge) == 1:
            only = labels_to_merge[0]
            data[data == only] = 0
            layer.data = data
            self.save_state()
            self._update_centers_for_affected_labels(old_labels)
            self.log_edit(
                algorithm="Merge",
                label_ids=labels_to_merge,
                params={
                    "target_value": 0,
                    "erase_to_background": True,
                },
                timestamp=start_time,
            )

            show_info(f"Label {only} erased and merged into background 0.")
        else:
            target_val = min(labels_to_merge)
            mask = np.isin(data, labels_to_merge)
            data[mask] = target_val
            layer.data = data
            self.save_state()
            self._update_centers_for_affected_labels(old_labels)

            self.log_edit(
                algorithm="Merge",
                label_ids=labels_to_merge,
                params={
                    "target_value": target_val,
                },
                timestamp=start_time,
            )

            show_info(f"Merged labels {labels_to_merge} into {target_val}.")

    def fix_boundary(self):
        start_time = datetime.now()
        if not self.fix_label_layer_name:
            return
        label_layer = self.viewer.layers[self.fix_label_layer_name]
        density_crop = None
        if self.fix_image_layer_name and self.fix_image_layer_name in self.viewer.layers:
            density_crop = self.viewer.layers[self.fix_image_layer_name].data
            print(" density_crop = self.viewer.layers[self.fix_image_layer_name].data")
        elif self.original_image_layer_name and self.current_bbox:
            density_crop = self.viewer.layers[self.original_image_layer_name].data[self.current_bbox]

        if density_crop is None:
            show_error("No image data available for boundary fix.")
            return

        try:
            full_label_data = np.asarray(getattr(self, "_view_labels_full_data", label_layer.data)).copy()
            if full_label_data.shape != np.asarray(label_layer.data).shape:
                full_label_data = np.asarray(label_layer.data).copy()
        except Exception:
            full_label_data = np.asarray(label_layer.data).copy()

        try:
            p = float(self.txt_boundary_percentile.text())
            r = float(self.txt_boundary_radius.text())
        except ValueError:
            show_error("Invalid percentile or box scaling for boundary fix.")
            return
        use_hull = self.chk_boundary_use_hull.isChecked()
        raw_id = self.txt_label_id.text().strip()
        try:
            target_labels = self._parse_label_list_text(raw_id)
            target_labels = [x for x in target_labels if x != 0]
        except Exception:
            show_error("Invalid label ID. Please enter integers separated by spaces (e.g., 4 19).")
            return
        if len(target_labels) == 0:
            show_error("Boundary fix requires at least one non-zero label ID (Label ID cannot be empty).")
            return
        target_labels = list(dict.fromkeys(target_labels))

        show_info(
            f"Running Boundary Fix (Speed, percentile={p}, box scaling={r}, use_hull={use_hull}, target_labels={target_labels})..."
        )

        print(density_crop.shape, full_label_data.shape)
        new_data = run_boundary_fix_fast(
            full_label_data,
            density_crop,
            filter_size=3,
            percentile=p,
            target_labels=target_labels,
            box_scaling=r,
            use_hull=use_hull,
            blocking_volume=full_label_data,
        )

        self._view_labels_full_data = np.asarray(new_data, np.int32).copy()
        display = self._compose_masked_view_from_full(self._view_labels_full_data, self._get_active_visibility_ids())
        self._set_fix_label_data_silently(display, update_full=False)
        label_layer.events.data()

        self.save_state()

        self.log_edit(
            algorithm="BoundaryFix-Speed",
            label_ids=list(target_labels),
            params={
                "percentile": p,
                "box_scaling": r,
                "use_hull": use_hull,
                "target_labels": target_labels,
                "visibility_filter_active": bool(self._get_active_visibility_ids()),
            },
            timestamp=start_time,
        )

        show_info("Boundary Fix applied.")




    @staticmethod
    def _json_dumps_compact(obj):
        """ JSON """
        return json.dumps(
            obj,
            ensure_ascii=False,
            separators=(",", ":"),
            default=NuPatch3DWidget._json_numpy_default,
        )

    @staticmethod
    def _append_entries_to_json_array(path, entries):
        """
         O()  entries  JSON  Commit
         json.load +  json.dump 

        - 
        -  seek  ] 
        -  / 
        """
        payload = [NuPatch3DWidget._json_dumps_compact(e) for e in entries]
        if not payload:
            return

        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        if (not os.path.exists(path)) or os.path.getsize(path) == 0:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write('[\n')
                f.write(',\n'.join(payload))
                f.write('\n]')
            return

        ws = b' \t\r\n'
        with open(path, 'r+b') as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            if end <= 0:
                raise ValueError(f'Existing JSON "{path}" is empty, cannot safely append.')

            pos = end - 1
            last_non_ws = None
            while pos >= 0:
                f.seek(pos)
                ch = f.read(1)
                if ch not in ws:
                    last_non_ws = (pos, ch)
                    break
                pos -= 1
            if last_non_ws is None or last_non_ws[1] != b']':
                raise ValueError(f'Existing JSON "{path}" top level is not an array format or missing ] at the end.')
            close_bracket_pos = last_non_ws[0]

            pos = 0
            first_non_ws = None
            while pos < end:
                f.seek(pos)
                ch = f.read(1)
                if ch not in ws:
                    first_non_ws = (pos, ch)
                    break
                pos += 1
            if first_non_ws is None or first_non_ws[1] != b'[':
                raise ValueError(f'Existing JSON "{path}" top level is not an array format or missing [ at the beginning.')

            pos = close_bracket_pos - 1
            prev_non_ws = None
            while pos >= 0:
                f.seek(pos)
                ch = f.read(1)
                if ch not in ws:
                    prev_non_ws = ch
                    break
                pos -= 1
            is_empty = (prev_non_ws == b'[')

            f.seek(close_bracket_pos)
            f.truncate()
            if is_empty:
                f.write(b'\n')
                f.write(',\n'.join(payload).encode('utf-8'))
                f.write(b'\n]')
            else:
                f.write(b',\n')
                f.write(',\n'.join(payload).encode('utf-8'))
                f.write(b'\n]')


    def commit_action(self):
        self._flush_pending_save_state()
        if not self.fix_label_layer_name or not self.current_bbox:
            return
        if not self.original_label_layer_name:
            return

        synced_full = self._sync_current_fix_layer_to_full_cache()
        local_data_full = synced_full if synced_full is not None else getattr(self, '_view_labels_full_data', None)
        if local_data_full is None or np.asarray(local_data_full).shape != np.asarray(self.viewer.layers[self.fix_label_layer_name].data).shape:
            local_data_full = self.viewer.layers[self.fix_label_layer_name].data
        local_data = np.asarray(local_data_full)

        global_layer = self._get_original_layer_by_name(self.original_label_layer_name)
        if global_layer is None:
            show_error("Original label layer not found.")
            return

        commit_vol_shape = commit_safe_volume_shape_from_label_data(global_layer.data)
        if commit_vol_shape is None:
            show_error(
                "Original label layer data must be a single-level voxel array (e.g., numpy ndarray); multi-scale list formats are not supported."
                "Cannot safely Commit and write JSON label_data_shape, aborted."
            )
            return

        commit_target_ids = []
        try:
            active_ids = self._get_active_visibility_ids()
            if active_ids:
                commit_target_ids = [int(v) for v in active_ids if int(v) != 0]
        except Exception:
            commit_target_ids = []

        if (not commit_target_ids) and getattr(self, '_bbox_commit_use_target_mask', False) and self._bbox_commit_target_ids:
            commit_target_ids = [int(v) for v in self._bbox_commit_target_ids if int(v) != 0]

        gdtype = np.asarray(global_layer.data).dtype
        if commit_target_ids:
            G = np.asarray(global_layer.data[self.current_bbox]).copy()
            L = local_data
            if G.shape == L.shape:
                tset = list(commit_target_ids)
                out = G.copy()
                editable = np.logical_or(np.isin(G, tset), G == 0)
                out[editable] = L[editable]
                out_patch = np.asarray(out, dtype=gdtype)
            else:
                out_patch = np.asarray(L, dtype=gdtype)
        else:
            out_patch = np.asarray(local_data, dtype=gdtype)

        self._write_labels_layer_bbox_patch(global_layer, self.current_bbox, out_patch)
        self._apply_original_layer_presence()
        written_crop = np.asarray(out_patch, copy=True)

        affected_labels = np.unique(written_crop)
        affected_labels = affected_labels[affected_labels > 0]
        offset = np.array([s.start for s in self.current_bbox])

        new_labels_added = False
        for lbl in affected_labels:
            mask = (written_crop == lbl)
            if np.any(mask):
                local_center = center_of_mass(mask)
                global_center = tuple(np.array(local_center) + offset)
                if lbl not in self.centers:
                    new_labels_added = True
                self.centers[lbl] = global_center

        if not hasattr(self, '_commit_count'):
            self._commit_count = 0
        self._commit_count += 1

        should_cleanup = (self._commit_count % 10 == 0) or (len(self.centers) > 5000)
        centers_keys_to_remove = []
        if should_cleanup:
            global_all_labels = set(np.unique(global_layer.data))
            global_all_labels.discard(0)
            centers_keys_to_remove = [k for k in self.centers.keys() if k not in global_all_labels]
            for k in centers_keys_to_remove:
                del self.centers[k]
        if new_labels_added or centers_keys_to_remove:
            self.sorted_labels = sorted(self.centers.keys())

        _wc_i64 = np.asarray(written_crop, dtype=np.int64)
        snapshot_entry = {
            "algorithm": "CommitSnapshot",
            "label_ids": [],
            "params": {
                "final_labels": _wc_i64.tolist(),
            },
            "fix_label_layer_name": self.fix_label_layer_name,
            "fix_image_layer_name": self.fix_image_layer_name,
            "original_label_layer_name": self.original_label_layer_name,
            "original_image_layer_name": self.original_image_layer_name,
            "max_label_id": int(_wc_i64.max()) if _wc_i64.size else 0,
            "label_data_shape": [int(x) for x in commit_vol_shape],
            "bbox": [
                [s.start, s.stop] if isinstance(s, slice) else list(s)
                for s in self.current_bbox
            ],
            "timestamp": datetime.now().isoformat(),
        }
        entries_for_file = list(self.edit_log) + [snapshot_entry]

        try:
            path = os.path.abspath(self.json_file_path)
            self.json_file_path = path
            try:
                self._append_entries_to_json_array(path, entries_for_file)
            except (ValueError, OSError, UnicodeError) as e:
                bak_msg = ""
                if os.path.exists(path):
                    bak = f"{path}.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
                    try:
                        shutil.copy2(path, bak)
                        bak_msg = f" Original file backed up to: {bak}"
                    except Exception:
                        bak_msg = " (Auto-backup failed, please do not delete the original file.)"
                raise RuntimeError(
                    f"Cannot append to existing JSON log ({e}), write aborted to avoid losing history. {bak_msg}"
                    f" Please fix or delete the file, or change the 'JSON Save Path' and Commit again."
                )
            show_info(f"Operation log saved to: {path}")
            self.edit_log.clear()
        except Exception as e:
            show_error(
                f"Failed to save operation log: {e}\n"
                "Global labels have been written to the in-memory layer, but this Commit snapshot was not saved to JSON;"
                "Please check the path and permissions, then Commit again, or correct the 'JSON Save Path'."
            )

        self.extract_bounding_box()
        show_info("Changes committed.")

    def select_missing_cell_seed(self):
        """
        Points
        """
        if not self.fix_label_layer_name:
            show_error("Please extract a bounding box first.")
            return
        if self.viewer.dims.ndisplay == 3:
            show_error("napari does not support point picking in 3D. Please switch to 2D mode (click the 2D button) before selecting points.")
            return
        if self.missing_cell_points_layer_name in self.viewer.layers:
            self.missing_cell_points_layer = self.viewer.layers[self.missing_cell_points_layer_name]
            self.viewer.layers.selection.active = self.missing_cell_points_layer
            show_info("Points layer activated. You can add seed points on different 2D planes.")
        else:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
            self.missing_cell_points_layer = self.viewer.add_points(
                ndim=3,
                name=self.missing_cell_points_layer_name,
                size=1,
                face_color='yellow',
                border_color='red',
            )
            self.viewer.layers.selection.active = self.missing_cell_points_layer
            self.missing_cell_points_layer.mode = 'add'
            show_info("Points layer created. You can add seed points on different 2D planes to mark missing cells.")
    def detect_missing_cell(self):
        """
        
        watershed.py
        """
        if not self.fix_label_layer_name:
            show_error("Please extract a bounding box first.")
            return
        if (self.missing_cell_points_layer is None or 
            self.missing_cell_points_layer_name not in self.viewer.layers or
            len(self.missing_cell_points_layer.data) == 0):
            show_error("Please select at least one seed point first.")
            return
        if not self.fix_image_layer_name or self.fix_image_layer_name not in self.viewer.layers:
            show_error("Please extract a bounding box containing image data first.")
            return
        
        raw_image = self.viewer.layers[self.fix_image_layer_name].data
        label_image = self.viewer.layers[self.fix_label_layer_name].data
        old_labels = set(np.unique(label_image))
        old_labels.discard(0)
        try:
            threshold = float(self.txt_watershed_threshold.text())
            max_distance = float(self.txt_watershed_distance.text())
        except ValueError:
            show_error("Invalid parameter value.")
            return
        seed_points = self.missing_cell_points_layer.data
        if len(seed_points) == 0:
            show_error("Please select at least one seed point first.")
            return
        self.save_state()
        next_id = self._get_next_available_label()
        for seed_point in seed_points:
            seed_coord = tuple(int(round(coord)) for coord in seed_point)
            if (seed_coord[0] < 0 or seed_coord[0] >= raw_image.shape[0] or
                seed_coord[1] < 0 or seed_coord[1] >= raw_image.shape[1] or
                seed_coord[2] < 0 or seed_coord[2] >= raw_image.shape[2]):
                show_error(f"Seed point coordinate {seed_coord} is out of image bounds.")
                continue
            markers = np.zeros_like(raw_image, dtype=np.int32)
            markers[seed_coord] = 1
            valid_data_mask = raw_image > 0
            threshold_mask = raw_image > threshold
            markers[np.logical_and(valid_data_mask, ~threshold_mask)] = 2
            distance = distance_transform_edt(markers == 1)
            distance_mask = np.logical_and(distance < max_distance, valid_data_mask)
            if not np.any(distance_mask):
                show_error(f"Distance mask for seed point {seed_coord} is empty. Please increase the Max Distance parameter.")
                continue
            labels_ws = watershed(-distance, markers, mask=distance_mask)
            new_region = (labels_ws == 1)
            if np.any(new_region):
                label_image[new_region] = next_id
                next_id += 1
            else:
                show_info(f"Seed point {seed_coord} failed to generate a new cell region. Please check parameter settings.")
        self.viewer.layers[self.fix_label_layer_name].data = label_image
        self.viewer.layers[self.fix_label_layer_name].refresh()
        self._update_centers_for_affected_labels(old_labels)
        start_time = datetime.now()
        self.log_edit(
            algorithm="Watershed-MissingCell",
            label_ids=["NEW"],
            params={
                "threshold": threshold,
                "max_distance": max_distance,
                "seed_points": seed_points.tolist() if hasattr(seed_points, 'tolist') else seed_points,
            },
            timestamp=start_time,
        )
        
        show_info(f"Identified and added {len(seed_points)} missing cell(s).")
    
    def _focus_stack_top_if_no_active_layer(self):
        """napari """
        layers = self.viewer.layers
        if len(layers) == 0:
            return
        active = layers.selection.active
        if active is None or active not in layers:
            layers.selection.active = layers[-1]
    
    def remove_aux_layers_missing(self, *, quiet: bool = False):
        """
        Missing Cell Detection
        """
        removed_count = 0
        try:
            if self.missing_cell_points_layer_name in self.viewer.layers:
                self.viewer.layers.remove(self.missing_cell_points_layer_name)
                self.missing_cell_points_layer = None
                removed_count += 1
        except Exception as e:
            show_error(f"Error deleting auxiliary layers: {e}")
        
        if not quiet:
            if removed_count > 0:
                show_info(f"Deleted {removed_count} Missing Cell Detection auxiliary layer(s).")
            else:
                show_info("No auxiliary layers found to delete.")
        self._focus_stack_top_if_no_active_layer()

    def remove_all_aux_layers(self):
        """
        GMM ManualPlaneMissing Cell Detection
        
        """
        self.remove_aux_layers_under(quiet=True)
        self.remove_aux_layers_missing(quiet=True)
        self._focus_stack_top_if_no_active_layer()

        show_info("All auxiliary layers from all modes have been removed.")
    
    def spherical_to_normal(self, phi_deg, theta_deg):
        """
         plane_normal 
         φ≈0°/180°  sin(φ)=0  θ 
        
        :
            phi_deg: float, z0-360
            theta_deg: float, xy0-360
        
        :
            normal: np.array,  (z, y, x)
        """
        phi = np.deg2rad(phi_deg)
        theta = np.deg2rad(theta_deg)
        # x = sin(φ) * cos(θ)
        # y = sin(φ) * sin(θ)
        # z = cos(φ)
        normal = np.array([
            np.cos(phi),  # z
            np.sin(phi) * np.sin(theta),  # y
            np.sin(phi) * np.cos(theta),  # x
        ])
        norm = np.linalg.norm(normal)
        if norm > 1e-10:
            normal = normal / norm
        
        return normal
    
    # def _current_view_slice_normal_zyx(self):
    #     """
    #     """
    #     dims = self.viewer.dims
    #     fallback = np.array([1.0, 0.0, 0.0], dtype=float)
    #     if getattr(dims, "ndisplay", 3) != 2:
    #         return fallback
    #     nd = tuple(getattr(dims, "not_displayed", ()))
    #     spatial = [
    #         int(a)
    #         for a in nd
    #         if isinstance(a, (int, np.integer)) and 0 <= int(a) < 3
    #     ]
    #     if len(spatial) >= 1:
    #         v = np.zeros(3, dtype=float)
    #         v[spatial[0]] = 1.0
    #         return v
    #     try:
    #         order = tuple(int(x) for x in dims.order)
    #         ndisp = int(dims.ndisplay)
    #         shown = set(order[-ndisp:])
    #         for ax in range(min(3, int(dims.ndim))):
    #             if ax not in shown:
    #                 v = np.zeros(3, dtype=float)
    #                 v[ax] = 1.0
    #                 return v
    #     except Exception:
    #         pass
    #     return fallback
    def _hidden_axis_index_for_2d_view(self):
        """
         2D 0=z,1=y,2=x None
        """
        dims = self.viewer.dims
        if getattr(dims, "ndisplay", 3) != 2:
            return None
        nd = tuple(getattr(dims, "not_displayed", ()))
        spatial = [
            int(a)
            for a in nd
            if isinstance(a, (int, np.integer)) and 0 <= int(a) < 3
        ]
        if len(spatial) >= 1:
            return spatial[0]
        try:
            order = tuple(int(x) for x in dims.order)
            ndisp = int(dims.ndisplay)
            shown = set(order[-ndisp:])
            for ax in range(min(3, int(dims.ndim))):
                if ax not in shown:
                    return ax
        except Exception:
            pass
        return None

    def _current_view_slice_normal_zyx(self):
        """
         2D  (z,y,x) 
        /
        """
        fallback = np.array([1.0, 0.0, 0.0], dtype=float)
        hid = self._hidden_axis_index_for_2d_view()
        if hid is None:
            return fallback
        v = np.zeros(3, dtype=float)
        v[hid] = 1.0
        return v

    def _get_plane_density_image_zyx(self):
        """ fix_boundary  bbox """
        if self.fix_image_layer_name and self.fix_image_layer_name in self.viewer.layers:
            return np.asarray(self.viewer.layers[self.fix_image_layer_name].data)
        if self.original_image_layer_name and self.current_bbox:
            name = self.original_image_layer_name
            if name in self.viewer.layers:
                return np.asarray(self.viewer.layers[name].data[self.current_bbox])
        return None

    @staticmethod
    def _mean_symmetric_bands_1d(line, c, p, q, min_pixels=4):
        """
         c  [c+p,c+q]  [c-q,c-p]
         None
        """
        line = np.asarray(line, dtype=float)
        n = line.size
        chunks = []
        for lo, hi in ((c + p, c + q), (c - q, c - p)):
            lo = max(0, int(lo))
            hi = min(n - 1, int(hi))
            if lo <= hi:
                chunks.append(line[lo : hi + 1])
        if not chunks:
            return None
        allv = np.concatenate(chunks)
        if allv.size < min_pixels:
            return None
        return float(np.mean(allv))

    def _plane_normal_from_brightness_bands(self, p=3, q=12, tie_eps=0.08, min_band_pixels=4):
        """
         2D  (z,y,x)  vis0  vis1 None
        Dh vis0 vis1 Dv vis1 vis0Dh>Dv  n=e_vis1 n=e_vis0
        """
        hid = self._hidden_axis_index_for_2d_view()
        if hid is None or self.plane_center_point is None:
            return None
        if p >= q:
            p, q = 3, 12
        vol = self._get_plane_density_image_zyx()
        if vol is None or getattr(vol, "ndim", 0) != 3:
            return None
        dims = self.viewer.dims
        step = int(round(float(dims.current_step[hid])))
        shp = vol.shape
        if not (0 <= step < shp[hid]):
            return None
        idx3 = [slice(None), slice(None), slice(None)]
        idx3[hid] = step
        sl = np.asarray(vol[tuple(idx3)], dtype=float)
        vis = [a for a in (0, 1, 2) if a != hid]
        vis0, vis1 = vis[0], vis[1]
        pc = np.asarray(self.plane_center_point, dtype=float)
        i0 = int(round(float(pc[vis0])))
        i1 = int(round(float(pc[vis1])))
        if not (0 <= i0 < sl.shape[0] and 0 <= i1 < sl.shape[1]):
            return None
        dh = self._mean_symmetric_bands_1d(sl[i0, :], i1, p, q, min_band_pixels)
        dv = self._mean_symmetric_bands_1d(sl[:, i1], i0, p, q, min_band_pixels)
        if dh is None or dv is None:
            return None
        m = max(abs(dh), abs(dv), 1e-12)
        if abs(dh - dv) <= tie_eps * m:
            return None
        n = np.zeros(3, dtype=float)
        if dh > dv:
            n[vis1] = 1.0
        else:
            n[vis0] = 1.0
        return n


    @staticmethod
    def _unit_normal_perpendicular_to(n_view):
        """ (z,y,x)  n_view """
        n_view = np.asarray(n_view, dtype=float)
        nv = np.linalg.norm(n_view)
        if nv < 1e-15:
            return np.array([0.0, 0.0, 1.0], dtype=float)
        n_view = n_view / nv
        for ref in (
            np.array([1.0, 0.0, 0.0], dtype=float),
            np.array([0.0, 1.0, 0.0], dtype=float),
            np.array([0.0, 0.0, 1.0], dtype=float),
        ):
            c = np.cross(n_view, ref)
            nc = np.linalg.norm(c)
            if nc > 1e-10:
                return c / nc
        return np.array([0.0, 0.0, 1.0], dtype=float)
    
    @staticmethod
    def _normal_zyx_to_spherical_deg(n):
        """ (z,y,x)  spherical_to_normal  φθ0–360"""
        n = np.asarray(n, dtype=float)
        nn = np.linalg.norm(n)
        if nn < 1e-15:
            return 90.0, 0.0
        nz, ny, nx = (n / nn)[0], (n / nn)[1], (n / nn)[2]
        rho = float(np.hypot(ny, nx))
        phi_deg = float(np.rad2deg(np.arctan2(rho, nz)) % 360.0)
        if rho < 1e-14:
            theta_deg = 0.0
        else:
            theta_deg = float(np.rad2deg(np.arctan2(ny, nx)) % 360.0)
        return phi_deg, theta_deg

    def _apply_default_plane_normal_perpendicular_to_view(self):
        """ 2D """
        n_slice = self._current_view_slice_normal_zyx()
        n_band = self._plane_normal_from_brightness_bands()
        if n_band is not None:
            nb = float(np.linalg.norm(n_band))
            if nb > 1e-15:
                self.plane_normal = (n_band / nb).astype(float)
            else:
                self.plane_normal = self._unit_normal_perpendicular_to(n_slice).astype(float)
        else:
            self.plane_normal = self._unit_normal_perpendicular_to(n_slice).astype(float)
        self.plane_phi, self.plane_theta = self._normal_zyx_to_spherical_deg(self.plane_normal)
        if hasattr(self, "txt_phi") and hasattr(self, "txt_theta"):
            self.txt_phi.blockSignals(True)
            self.txt_theta.blockSignals(True)
            self.txt_phi.setValue(int(round(self.plane_phi)) % 360)
            self.txt_theta.setValue(int(round(self.plane_theta)) % 360)
            self.txt_phi.blockSignals(False)
            self.txt_theta.blockSignals(False)
            self.plane_phi = float(self.txt_phi.value())
            self.plane_theta = float(self.txt_theta.value())
            self.plane_normal = self.spherical_to_normal(
                self.plane_phi, self.plane_theta
            ).astype(float)

    # def _apply_default_plane_normal_perpendicular_to_view(self):
    #     n_slice = self._current_view_slice_normal_zyx()
    #     self.plane_normal = self._unit_normal_perpendicular_to(n_slice).astype(float)
    #     self.plane_phi, self.plane_theta = self._normal_zyx_to_spherical_deg(self.plane_normal)
    #     if hasattr(self, "txt_phi") and hasattr(self, "txt_theta"):
    #         self.txt_phi.blockSignals(True)
    #         self.txt_theta.blockSignals(True)
    #         self.txt_phi.setValue(int(round(self.plane_phi)) % 360)
    #         self.txt_theta.setValue(int(round(self.plane_theta)) % 360)
    #         self.txt_phi.blockSignals(False)
    #         self.txt_theta.blockSignals(False)
    #         self.plane_phi = float(self.txt_phi.value())
    #         self.plane_theta = float(self.txt_theta.value())
    #         self.plane_normal = self.spherical_to_normal(
    #             self.plane_phi, self.plane_theta
    #         ).astype(float)
    
    @staticmethod
    def _wrap_spinbox_angle_delta_deg(new_abs_deg, old_abs_deg):
        """ SpinBox  (-180, 180]"""
        d = float(new_abs_deg) - float(old_abs_deg)
        while d > 180.0:
            d -= 360.0
        while d < -180.0:
            d += 360.0
        return d
    
    @staticmethod
    def _rodrigues_rotate_vector(v, axis, angle_rad):
        """Rodrigues  v  axis  angle_rad"""
        v = np.asarray(v, dtype=float)
        axis = np.asarray(axis, dtype=float)
        an = np.linalg.norm(axis)
        if an < 1e-15:
            return v.copy()
        k = axis / an
        cos_t = np.cos(angle_rad)
        sin_t = np.sin(angle_rad)
        return (
            v * cos_t
            + np.cross(k, v) * sin_t
            + k * np.dot(k, v) * (1.0 - cos_t)
        )
    
    def _rotate_plane_normal_delta_phi(self, n, dphi_deg):
        """
        φ  e_z × n  ∂n/∂φ  n ∥ ±e_z  Y 
        e_z  napari  z  (1,0,0)
        """
        n = np.asarray(n, dtype=float)
        dphi = np.deg2rad(float(dphi_deg))
        ez = np.array([1.0, 0.0, 0.0], dtype=float)
        k = np.cross(ez, n)
        kn = np.linalg.norm(k)
        if kn < 1e-10:
            k = np.array([0.0, 1.0, 0.0], dtype=float)
        else:
            k = k / kn
        return self._rodrigues_rotate_vector(n, k, dphi)
    
    def _rotate_plane_normal_delta_theta(self, n, dtheta_deg):
        """
        θ  z  e_z  n  ±e_z  X 
         φ  Y  trackball
        """
        n = np.asarray(n, dtype=float)
        dtheta = np.deg2rad(float(dtheta_deg))
        ez = np.array([1.0, 0.0, 0.0], dtype=float)
        if abs(np.dot(n, ez)) >= 0.9999 * (np.linalg.norm(n) + 1e-15):
            axis = np.array([0.0, 0.0, 1.0], dtype=float)
        else:
            axis = ez
        return self._rodrigues_rotate_vector(n, axis, dtheta)
    
    def _get_plane_unit_normal(self):
        """ (z, y, x)"""
        n = np.asarray(self.plane_normal, dtype=float)
        nn = np.linalg.norm(n)
        if nn < 1e-15:
            return np.array([1.0, 0.0, 0.0], dtype=float)
        return n / nn
    
    def _on_plane_coord_changed(self):
        """
        QSpinBoxvalueChanged
        SpinBox
        """
        if not self.fix_label_layer_name:
            return
        
        try:
            x = self.txt_plane_x.value()
            y = self.txt_plane_y.value()
            z = self.txt_plane_z.value()
            self.plane_center_point = np.array([z, y, x], dtype=float)
            if (self.plane_split_points_layer is not None and 
                self.plane_split_points_layer_name in self.viewer.layers and
                len(self.plane_split_points_layer.data) > 0):
                if (self.plane_split_points_connection is not None and 
                    hasattr(self.plane_split_points_connection, 'disconnect')):
                    try:
                        self.plane_split_points_connection.disconnect()
                    except (RuntimeError, TypeError, AttributeError):
                        pass
                self.plane_split_points_layer.data[0] = np.array([z, y, x])
                self.plane_split_points_connection = self.plane_split_points_layer.events.data.connect(
                    self._on_plane_point_changed
                )
            self._update_plane_display()
        except (ValueError, KeyError):
            pass
    
    def _on_text_phi_changed(self):
        """
        phi SpinBoxQSpinBoxvalueChanged
         Rodrigues  plane_normal θ 
        """
        value = float(self.txt_phi.value())
        dphi = self._wrap_spinbox_angle_delta_deg(value, self.plane_phi)
        self.plane_normal = self._rotate_plane_normal_delta_phi(self._get_plane_unit_normal(), dphi)
        self.plane_phi = value
        self._update_plane_display()
    
    def _on_text_theta_changed(self):
        """
        theta SpinBoxQSpinBoxvalueChanged
         φ  e_z  z 
        """
        value = float(self.txt_theta.value())
        dtheta = self._wrap_spinbox_angle_delta_deg(value, self.plane_theta)
        self.plane_normal = self._rotate_plane_normal_delta_theta(self._get_plane_unit_normal(), dtheta)
        self.plane_theta = value
        self._update_plane_display()
    
    def _update_plane_display(self):
        """

        """
        if self.plane_center_point is not None:
            if not hasattr(self, '_plane_update_timer'):
                self._plane_update_timer = QTimer()
                self._plane_update_timer.setSingleShot(True)
                self._plane_update_timer.timeout.connect(self._do_update_plane_display)
            self._plane_update_timer.stop()
            self._plane_update_timer.start(50)
    
    def _do_update_plane_display(self):
        """
        
        """
        if self.plane_center_point is not None:
            if self.plane_has_initial_point:
                self._do_draw_plane()
                self.draw_spherical_axes()
    
    def draw_spherical_axes(self):
        """
        3D
        XYZ
        """
        if not self.fix_label_layer_name:
            return
        if self.plane_center_point is None:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
            bbox_shape = label_layer.data.shape  # (z, y, x)
            center_z = bbox_shape[0] // 2
            center_y = bbox_shape[1] // 2
            center_x = bbox_shape[2] // 2
            self.plane_center_point = np.array([center_z, center_y, center_x], dtype=float)
        
        label_layer = self.viewer.layers[self.fix_label_layer_name]
        bbox_shape = label_layer.data.shape  # (z, y, x)
        bbox_size = np.array(bbox_shape)
        axis_length = min(bbox_size) * 0.3
        center = self.plane_center_point
        normal = self._get_plane_unit_normal()
        shapes_to_add = []
        shape_types = []
        edge_colors = []
        
        def _make_dashed_segments(start, end, n_segments=16, duty_cycle=0.5):
            """3D"""
            start = np.asarray(start, dtype=float)
            end = np.asarray(end, dtype=float)
            vec = end - start
            total_len = np.linalg.norm(vec)
            if total_len == 0 or n_segments <= 0:
                return [np.array([start, end], dtype=float)]
            step = vec / n_segments
            segments = []
            for i in range(n_segments):
                if (i % 2) == 0:
                    s = start + i * step
                    e = start + (i + 1) * step
                    segments.append(np.array([s, e], dtype=float))
            return segments
        x_axis_end = center + axis_length * np.array([0, 0, 1])  # (z, y, x)
        for seg in _make_dashed_segments(center, x_axis_end):
            shapes_to_add.append(seg)
            shape_types.append('line')
            edge_colors.append('red')
        y_axis_end = center + axis_length * np.array([0, 1, 0])  # (z, y, x)
        for seg in _make_dashed_segments(center, y_axis_end):
            shapes_to_add.append(seg)
            shape_types.append('line')
            edge_colors.append('green')
        z_axis_end = center + axis_length * np.array([1, 0, 0])  # (z, y, x)
        for seg in _make_dashed_segments(center, z_axis_end):
            shapes_to_add.append(seg)
            shape_types.append('line')
            edge_colors.append('blue')
        normal_end = center + axis_length * normal
        shapes_to_add.append(np.array([center, normal_end]))
        shape_types.append('line')
        edge_colors.append('yellow')
        if self.plane_axis_shapes_layer_name in self.viewer.layers:
            try:
                self.viewer.layers.remove(self.plane_axis_shapes_layer_name)
            except:
                pass
        self.plane_axis_shapes_layer = self.viewer.add_shapes(
            shapes_to_add,
            shape_type=shape_types,
            ndim=3,
            name=self.plane_axis_shapes_layer_name,
            blending='additive',
        )
        self.plane_axis_shapes_layer.edge_color = edge_colors
        self.plane_axis_shapes_layer.face_color = ['transparent'] * len(edge_colors)
        if len(edge_colors) > 0:
            rgb_count = len(edge_colors) - 1
            edge_widths = [0.8] * rgb_count + [1.5]
            self.plane_axis_shapes_layer.edge_width = edge_widths
        self.plane_axis_shapes_layer.edge_style = 'solid'
        try:
            self.plane_axis_shapes_layer.refresh()
        except (OSError, RuntimeError) as e:
            if "access violation" in str(e).lower() or "0x000000000000000C" in str(e):
                pass
            else:
                raise
    
    def draw_plane(self):
        """
        Points
        
        """
        if not self.fix_label_layer_name:
            show_error("Please extract a bounding box first.")
            return
        if not self.plane_has_initial_point:
            if self.viewer.dims.ndisplay == 3:
                show_error("napari does not support point picking in 3D. Please switch to 2D mode (click the 2D button) before selecting points.")
                return
            if self.plane_split_points_layer_name in self.viewer.layers:
                self.plane_split_points_layer = self.viewer.layers[self.plane_split_points_layer_name]
                self.viewer.layers.selection.active = self.plane_split_points_layer
                if self.plane_split_points_connection is None or not hasattr(self.plane_split_points_connection, 'disconnect'):
                    self.plane_split_points_connection = self.plane_split_points_layer.events.data.connect(
                        self._on_plane_point_changed
                    )
                if len(self.plane_split_points_layer.data) >= 1:
                    self.plane_split_points_layer.mode = 'select'
                    if len(self.plane_split_points_layer.data) > 0:
                        self._update_plane_point_from_points_layer()
                else:
                    self.plane_split_points_layer.mode = 'add'
                show_info("Points layer activated. Please select a point on the 2D plane as the plane passing point.")
            else:
                label_layer = self.viewer.layers[self.fix_label_layer_name]
                self.plane_split_points_layer = self.viewer.add_points(
                    ndim=3,
                    name=self.plane_split_points_layer_name,
                    size=3,
                    face_color='blue',
                    border_color='red',
                )
                self.plane_split_points_connection = self.plane_split_points_layer.events.data.connect(
                    self._on_plane_point_changed
                )
                self.viewer.layers.selection.active = self.plane_split_points_layer
                self.plane_split_points_layer.mode = 'add'
                show_info("Points layer created. Please select a point on the 2D plane as the plane passing point.")
            return
        self._do_draw_plane()
    
    def _update_plane_point_from_points_layer(self):
        """
        PointsSpinBox
        """
        if (self.plane_split_points_layer is not None and 
            len(self.plane_split_points_layer.data) > 0):
            first_2d_pick = not self.plane_has_initial_point
            point = np.array(self.plane_split_points_layer.data[0])  # (z, y, x)
            z, y, x = int(round(point[0])), int(round(point[1])), int(round(point[2]))
            self.plane_center_point = np.array([z, y, x], dtype=float)
            if first_2d_pick:
                self._apply_default_plane_normal_perpendicular_to_view()
            self.plane_has_initial_point = True
            if hasattr(self, 'txt_plane_z'):
                self.txt_plane_z.blockSignals(True)
                self.txt_plane_y.blockSignals(True)
                self.txt_plane_x.blockSignals(True)
                self.txt_plane_z.setValue(z)
                self.txt_plane_y.setValue(y)
                self.txt_plane_x.setValue(x)
                self.txt_plane_z.blockSignals(False)
                self.txt_plane_y.blockSignals(False)
                self.txt_plane_x.blockSignals(False)
            self._do_draw_plane()
            self.draw_spherical_axes()
    
    def _on_plane_point_changed(self, event=None):
        """
        Points
        """
        self._update_plane_point_from_points_layer()
    
    def _do_draw_plane(self):
        """
        
        """
        if self.plane_center_point is None:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
            bbox_shape = label_layer.data.shape  # (z, y, x)
            center_z = bbox_shape[0] // 2
            center_y = bbox_shape[1] // 2
            center_x = bbox_shape[2] // 2
            self.plane_center_point = np.array([center_z, center_y, center_x], dtype=float)
            if hasattr(self, 'txt_plane_z'):
                self.txt_plane_z.blockSignals(True)
                self.txt_plane_y.blockSignals(True)
                self.txt_plane_x.blockSignals(True)
                self.txt_plane_z.setValue(center_z)
                self.txt_plane_y.setValue(center_y)
                self.txt_plane_x.setValue(center_x)
                self.txt_plane_z.blockSignals(False)
                self.txt_plane_y.blockSignals(False)
                self.txt_plane_x.blockSignals(False)
        if not self.current_bbox or not self.fix_label_layer_name:
            show_error("Unable to retrieve bounding box information.")
            return
        
        label_layer = self.viewer.layers[self.fix_label_layer_name]
        bbox_shape = label_layer.data.shape  # (z, y, x)
        bbox_size = np.array(bbox_shape)
        plane_center = self.plane_center_point.copy()
        
        vec_normalized = self._get_plane_unit_normal()
        shapes_to_add = []
        shape_types = []
        axis_length = min(bbox_size) * 0.3
        normal_end = plane_center + axis_length * vec_normalized
        arrow_points = np.array([plane_center, normal_end])
        shapes_to_add.append(arrow_points)
        shape_types.append('line')
        if abs(vec_normalized[0]) < 0.9:
            v1 = np.array([1, 0, 0])
        else:
            v1 = np.array([0, 1, 0])
        v1 = v1 - np.dot(v1, vec_normalized) * vec_normalized
        v1 = v1 / (np.linalg.norm(v1) + 1e-10)
        v2 = np.cross(vec_normalized, v1)
        v2 = v2 / (np.linalg.norm(v2) + 1e-10)
        plane_size = min(bbox_size) * 0.2
        corners = [
            plane_center + plane_size * (-v1 - v2),
            plane_center + plane_size * (v1 - v2),
            plane_center + plane_size * (v1 + v2),
            plane_center + plane_size * (-v1 + v2),
        ]
        for i in range(len(corners)):
            corners[i] = np.clip(corners[i], 0, bbox_size - 1)
        plane_rectangle = np.array(corners)
        shapes_to_add.append(plane_rectangle)
        shape_types.append('rectangle')
        if self.plane_split_shapes_layer_name in self.viewer.layers:
            try:
                self.viewer.layers.remove(self.plane_split_shapes_layer_name)
            except:
                pass
        self.plane_split_shapes_layer = self.viewer.add_shapes(
            shapes_to_add,
            shape_type=shape_types,
            ndim=3,
            name=self.plane_split_shapes_layer_name,
            blending='translucent',
            opacity=1.0,
            edge_width=[1, 1],
        )
        _plane_gray = [0.28, 0.28, 0.28, 1.0]
        self.plane_split_shapes_layer.edge_color = ['yellow', _plane_gray]
        self.plane_split_shapes_layer.face_color = ['transparent', [0.28, 0.28, 0.28, 1.0]]
        try:
            self.plane_split_shapes_layer.refresh()
        except (OSError, RuntimeError) as e:
            if "access violation" in str(e).lower() or "0x000000000000000C" in str(e):
                pass
            else:
                raise
    
    def split_by_plane(self):
        """
        bboxφθ
        """
        if not self.fix_label_layer_name:
            show_error("Please extract a bounding box first.")
            return
        if self.plane_center_point is None:
            label_layer = self.viewer.layers[self.fix_label_layer_name]
            bbox_shape = label_layer.data.shape  # (z, y, x)
            center_z = bbox_shape[0] // 2
            center_y = bbox_shape[1] // 2
            center_x = bbox_shape[2] // 2
            self.plane_center_point = np.array([center_z, center_y, center_x], dtype=float)
            if hasattr(self, 'txt_plane_z'):
                self.txt_plane_z.blockSignals(True)
                self.txt_plane_y.blockSignals(True)
                self.txt_plane_x.blockSignals(True)
                self.txt_plane_z.setValue(center_z)
                self.txt_plane_y.setValue(center_y)
                self.txt_plane_x.setValue(center_x)
                self.txt_plane_z.blockSignals(False)
                self.txt_plane_y.blockSignals(False)
                self.txt_plane_x.blockSignals(False)
        plane_center = self.plane_center_point.copy()
        
        normal = self._get_plane_unit_normal()
        target_labels = None
        raw_lbls = self.txt_plane_target_labels.text().strip()
        if raw_lbls:
            try:
                target_labels = self._parse_label_list_text(raw_lbls)
                target_labels = [x for x in target_labels if x != 0]
                if len(target_labels) == 0:
                    target_labels = None
            except Exception:
                show_error("Invalid target label list. Please use format: 4 19")
                return
        else:
            show_error("Please set Target Labels first.")
            return
        label_layer = self.viewer.layers[self.fix_label_layer_name]
        label_data = label_layer.data.copy()
        if not self.current_bbox:
            show_error("Please extract a bounding box first.")
            return
        coords_all = []
        for target_label in target_labels:
            coords = np.where(label_data == target_label)
            coords_all.append(coords)
        
        if len(coords_all) == 0:
            show_info("No pixels found for the target label.")
            return
        z_coords = np.concatenate([coords[0] for coords in coords_all])
        y_coords = np.concatenate([coords[1] for coords in coords_all])
        x_coords = np.concatenate([coords[2] for coords in coords_all])
        points = np.stack([z_coords, y_coords, x_coords], axis=1)  # (N, 3)
        distances = np.dot(points - plane_center, normal)
        above_mask = distances >= 0
        
        if not np.any(above_mask):
            show_info("No points above the plane, no split needed.")
            return
        next_id = self._get_next_available_label()
        above_z = z_coords[above_mask]
        above_y = y_coords[above_mask]
        above_x = x_coords[above_mask]
        label_data[above_z, above_y, above_x] = next_id
        label_layer.data = label_data
        label_layer.refresh()
        self.save_state()
        start_time = datetime.now()
        self.log_edit(
            algorithm="Plane-Label-Split",
            label_ids=target_labels,
            params={
                "plane_center": plane_center.tolist(),
                "phi": self.plane_phi,
                "theta": self.plane_theta,
                "plane_normal": self._get_plane_unit_normal().tolist(),
                "normal": normal.tolist(),
                "new_label": int(next_id),
            },
            timestamp=start_time,
        )
        
        show_info(f"Plane split complete. New label {next_id} created.")
    
    def remove_aux_layers_under(self, *, quiet: bool = False):
        """
        GMM ManualPlane
        """
        removed_count = 0
        try:
            if self.gmm_points_layer_name in self.viewer.layers:
                self.viewer.layers.remove(self.gmm_points_layer_name)
                self.gmm_points_layer = None
                removed_count += 1
            if self.plane_split_points_layer_name in self.viewer.layers:
                if self.plane_split_points_connection is not None:
                    try:
                        self.plane_split_points_connection.disconnect()
                    except:
                        pass
                    self.plane_split_points_connection = None
                self.viewer.layers.remove(self.plane_split_points_layer_name)
                self.plane_split_points_layer = None
                self.plane_has_initial_point = False
                removed_count += 1
            if self.plane_split_shapes_layer_name in self.viewer.layers:
                self.viewer.layers.remove(self.plane_split_shapes_layer_name)
                self.plane_split_shapes_layer = None
                removed_count += 1
            if self.plane_axis_shapes_layer_name in self.viewer.layers:
                self.viewer.layers.remove(self.plane_axis_shapes_layer_name)
                self.plane_axis_shapes_layer = None
                removed_count += 1
        except Exception as e:
            show_error(f"Error deleting auxiliary layers: {e}")
        
        if not quiet:
            if removed_count > 0:
                show_info(f"Deleted {removed_count} Under-segmentation auxiliary layer(s).")
            else:
                show_info("No auxiliary layers found to delete.")
        self._focus_stack_top_if_no_active_layer()