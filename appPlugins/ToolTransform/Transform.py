# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from appHandlers.appHistory import (history_of, object_state, restore_object_state, states_equal,
                                    transform_metadata, SnapshotStep, HistoryManager)
from PyQt6 import QtWidgets, QtCore
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea
from defaults import AppDefaults
from appCommon.SafeEval import safe_eval
from appPlugins.ToolTransform.TransformUI import TransformUI
from appPlugins.ToolTransform.TransformGen import alt_bounds, bounds_center

import logging
from camlib import (affine_rotate_matrix, affine_scale_matrix, affine_skew_matrix, affine_mirror_matrix,
                    affine_translate_matrix)
import numpy as np

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolTransform(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)
        self.decimals = self.app.decimals
        self.ui = TransformUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolTransform()")

        if toggle:
            # if the splitter is hidden, display it
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
            if not found_idx:
                try:
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                except RuntimeError:
                    self.app.ui.plugin_tab = QtWidgets.QWidget()
                    self.app.ui.plugin_tab.setObjectName("plugin_tab")
                    self.app.ui.plugin_tab_layout = QtWidgets.QVBoxLayout(self.app.ui.plugin_tab)
                    self.app.ui.plugin_tab_layout.setContentsMargins(2, 2, 2, 2)
                    self.app.ui.plugin_scroll_area = VerticalScrollArea()
                    self.app.ui.plugin_tab_layout.addWidget(self.app.ui.plugin_scroll_area)
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        super().run()
        self.set_tool_ui()
        self.app.ui.notebook.setTabText(2, _("Transformation"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+T', **kwargs)

    def connect_signals_at_init(self):
        self.ui.ref_combo.currentIndexChanged.connect(self.ui.on_reference_changed)
        self.ui.type_obj_combo.currentIndexChanged.connect(self.on_type_obj_index_changed)
        self.ui.point_button.clicked.connect(self.on_add_coords)
        self.ui.rotate_button.clicked.connect(self.on_rotate)
        self.ui.skewx_button.clicked.connect(self.on_skewx)
        self.ui.skewy_button.clicked.connect(self.on_skewy)
        self.ui.scalex_button.clicked.connect(self.on_scalex)
        self.ui.scaley_button.clicked.connect(self.on_scaley)
        self.ui.offx_button.clicked.connect(self.on_offx)
        self.ui.offy_button.clicked.connect(self.on_offy)
        self.ui.flipx_button.clicked.connect(self.on_flipx)
        self.ui.flipy_button.clicked.connect(self.on_flipy)
        self.ui.buffer_button.clicked.connect(self.on_buffer_by_distance)
        self.ui.buffer_factor_button.clicked.connect(self.on_buffer_by_factor)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = TransformUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        # ## Initialize form
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.ui.ref_combo.set_value(self.app.options.get(
            "tools_transform_reference", app_defaults.get("tools_transform_reference", AppDefaults.factory_defaults.get("tools_transform_reference"))))
        self.ui.type_obj_combo.set_value(self.app.options.get(
            "tools_transform_ref_object", app_defaults.get("tools_transform_ref_object", AppDefaults.factory_defaults.get("tools_transform_ref_object"))))
        self.ui.point_entry.set_value(self.app.options.get(
            "tools_transform_ref_point", app_defaults.get("tools_transform_ref_point", AppDefaults.factory_defaults.get("tools_transform_ref_point"))))
        self.ui.rotate_entry.set_value(self.app.options.get(
            "tools_transform_rotate", app_defaults.get("tools_transform_rotate", AppDefaults.factory_defaults.get("tools_transform_rotate"))))
        self.ui.skewx_entry.set_value(self.app.options.get(
            "tools_transform_skew_x", app_defaults.get("tools_transform_skew_x", AppDefaults.factory_defaults.get("tools_transform_skew_x"))))
        self.ui.skewy_entry.set_value(self.app.options.get(
            "tools_transform_skew_y", app_defaults.get("tools_transform_skew_y", AppDefaults.factory_defaults.get("tools_transform_skew_y"))))
        self.ui.skew_link_cb.set_value(self.app.options.get(
            "tools_transform_skew_link", app_defaults.get("tools_transform_skew_link", AppDefaults.factory_defaults.get("tools_transform_skew_link"))))
        self.ui.scalex_entry.set_value(self.app.options.get(
            "tools_transform_scale_x", app_defaults.get("tools_transform_scale_x", AppDefaults.factory_defaults.get("tools_transform_scale_x"))))
        self.ui.scaley_entry.set_value(self.app.options.get(
            "tools_transform_scale_y", app_defaults.get("tools_transform_scale_y", AppDefaults.factory_defaults.get("tools_transform_scale_y"))))
        self.ui.scale_link_cb.set_value(self.app.options.get(
            "tools_transform_scale_link", app_defaults.get("tools_transform_scale_link", AppDefaults.factory_defaults.get("tools_transform_scale_link"))))
        self.ui.offx_entry.set_value(self.app.options.get(
            "tools_transform_offset_x", app_defaults.get("tools_transform_offset_x", AppDefaults.factory_defaults.get("tools_transform_offset_x"))))
        self.ui.offy_entry.set_value(self.app.options.get(
            "tools_transform_offset_y", app_defaults.get("tools_transform_offset_y", AppDefaults.factory_defaults.get("tools_transform_offset_y"))))
        self.ui.buffer_entry.set_value(self.app.options.get(
            "tools_transform_buffer_dis", app_defaults.get("tools_transform_buffer_dis", AppDefaults.factory_defaults.get("tools_transform_buffer_dis"))))
        self.ui.buffer_factor_entry.set_value(self.app.options.get(
            "tools_transform_buffer_factor", app_defaults.get("tools_transform_buffer_factor", AppDefaults.factory_defaults.get("tools_transform_buffer_factor"))))
        self.ui.buffer_rounded_cb.set_value(self.app.options.get(
            "tools_transform_buffer_corner", app_defaults.get("tools_transform_buffer_corner", AppDefaults.factory_defaults.get("tools_transform_buffer_corner"))))

        self.ui.point_label.hide()
        self.ui.point_entry.hide()
        self.ui.point_button.hide()
        self.ui.type_object_label.hide()
        self.ui.type_obj_combo.hide()
        self.ui.object_combo.hide()

    def on_type_obj_index_changed(self, index):
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(index, 0, QtCore.QModelIndex()))
        self.ui.object_combo.setCurrentIndex(0)
        self.ui.object_combo.obj_type = {
            _("Gerber"): "Gerber", _("Excellon"): "Excellon", _("Geometry"): "Geometry"
        }[self.ui.type_obj_combo.get_value()]

    def on_calculate_reference(self):
        ref_val = self.ui.ref_combo.currentIndex()
        if ref_val == 0:    # "Origin" reference
            return 0, 0
        elif ref_val == 1:  # "Selection" reference
            sel_list = self.app.collection.get_selected()
            if sel_list:
                xmin, ymin, xmax, ymax = self.alt_bounds(obj_list=sel_list)
                if not all(np.isfinite((xmin, ymin, xmax, ymax))):
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _("The selected objects have no geometry."))
                    return "fail"
                return bounds_center((xmin, ymin, xmax, ymax))
            else:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("No object is selected."))
                return "fail"
        elif ref_val == 2:  # "Point" reference
            point_val = self.ui.point_entry.get_value()
            try:
                px, py = safe_eval('{}'.format(point_val))
                return px, py
            except Exception:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Incorrect format for Point value. Needs format X,Y"))
                return "fail"
        else:               # "Object" reference
            obj_name = self.ui.object_combo.get_value()
            ref_obj = self.app.collection.get_by_name(obj_name)
            if ref_obj is None:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Reference object not found"), str(obj_name)))
                return "fail"
            xmin, ymin, xmax, ymax = ref_obj.bounds()
            if not all(np.isfinite((xmin, ymin, xmax, ymax))):
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Reference object has no geometry"), str(obj_name)))
                return "fail"
            return bounds_center((xmin, ymin, xmax, ymax))

    def on_add_coords(self):
        val = self.app.clipboard.text()
        self.ui.point_entry.set_value(val)

    def on_rotate(self):
        value = float(self.ui.rotate_entry.get_value())
        if value == 0:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Rotate transformation can not be done for a value of 0."))
            return
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_rotate_action, 'params': [value, point]})

    def on_flipx(self):
        axis = 'Y'
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_flip, 'params': [axis, point]})

    def on_flipy(self):
        axis = 'X'
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_flip, 'params': [axis, point]})

    def on_skewx(self):
        xvalue = float(self.ui.skewx_entry.get_value())
        if xvalue == 0:
            return
        if self.ui.skew_link_cb.get_value():
            yvalue = xvalue
        else:
            yvalue = 0
        axis = 'X'
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_skew, 'params': [axis, xvalue, yvalue, point]})

    def on_skewy(self):
        xvalue = 0
        yvalue = float(self.ui.skewy_entry.get_value())
        if yvalue == 0:
            return
        axis = 'Y'
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_skew, 'params': [axis, xvalue, yvalue, point]})

    def on_scalex(self):
        xvalue = float(self.ui.scalex_entry.get_value())
        if xvalue == 0 or xvalue == 1:
            self.app.inform.emit('[WARNING_NOTCL] %s' %
                                 _("Scale transformation can not be done for a factor of 0 or 1."))
            return
        if self.ui.scale_link_cb.get_value():
            yvalue = xvalue
        else:
            yvalue = 1
        axis = 'X'
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_scale, 'params': [axis, xvalue, yvalue, point]})

    def on_scaley(self):
        xvalue = 1
        yvalue = float(self.ui.scaley_entry.get_value())
        if yvalue == 0 or yvalue == 1:
            self.app.inform.emit('[WARNING_NOTCL] %s' %
                                 _("Scale transformation can not be done for a factor of 0 or 1."))
            return
        axis = 'Y'
        point = self.on_calculate_reference()
        if point == 'fail':
            return
        self.app.worker_task.emit({'fcn': self.on_scale, 'params': [axis, xvalue, yvalue, point]})

    def on_offx(self):
        value = float(self.ui.offx_entry.get_value())
        if value == 0:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Offset transformation can not be done for a value of 0."))
            return
        axis = 'X'
        self.app.worker_task.emit({'fcn': self.on_offset, 'params': [axis, value]})

    def on_offy(self):
        value = float(self.ui.offy_entry.get_value())
        if value == 0:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Offset transformation can not be done for a value of 0."))
            return
        axis = 'Y'
        self.app.worker_task.emit({'fcn': self.on_offset, 'params': [axis, value]})

    def on_buffer_by_distance(self):
        value = self.ui.buffer_entry.get_value()
        join = 1 if self.ui.buffer_rounded_cb.get_value() else 2
        self.app.worker_task.emit({'fcn': self.on_buffer_action, 'params': [value, join]})

    def on_buffer_by_factor(self):
        value = 1 + self.ui.buffer_factor_entry.get_value() / 100.0
        join = 1 if self.ui.buffer_rounded_cb.get_value() else 2
        factor = True
        self.app.worker_task.emit({'fcn': self.on_buffer_action, 'params': [value, join, factor]})

    def _transform_selected(self, title, cncjob_msg, apply_fn, matrix, meta_fn, done_msg, set_offset=True):
        """
        Runs one affine action on the selected objects (called from a worker thread). Per object: apply_fn(obj) does
        the transform, meta_fn(obj) stores the metadata in obj_options, then locally computed bounds update the
        Offset field. AppObject.on_object_changed computes fresh bounds when its queued signal is delivered.
        A failure on one object is logged and does not stop the others; the failed names are reported at the end.

        :param title:       text for the progress container
        :param cncjob_msg:  message for the CNCJob objects, shown once
        :param apply_fn:    callable(obj) that executes the transform; may return 'fail' (object unchanged)
        :param matrix:      the shapely 6-tuple that apply_fn applies to the geometry; None: not affine, plot() is used
        :param meta_fn:     callable(obj) that updates obj.obj_options
        :param done_msg:    success message
        :param set_offset:  update the Offset field in the Properties tab
        :return:            None
        """
        obj_list = self.app.collection.get_selected()
        if not obj_list:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No object is selected."))
            return

        with self.app.proc_container.new('%s...' % title):
            failed = []
            skipped_cnc = False
            done = 0
            history = history_of(self.app)
            with history.group(title):
                for sel_obj in obj_list:
                    if sel_obj.kind == 'cncjob':
                        skipped_cnc = True
                        continue
                    checkpoint = object_state(sel_obj)
                    before_meta = transform_metadata(sel_obj)
                    group_steps = history._group[1] if isinstance(history, HistoryManager) else None
                    recorded = len(group_steps) if group_steps is not None else 0
                    try:
                        result = apply_fn(sel_obj)
                        if result == 'fail':
                            raise ValueError('Object transformation failed')
                        meta_fn(sel_obj)
                        ToolTransform._after_change(self, sel_obj, matrix, set_offset)
                        if matrix is not None:
                            history_of(self.app).record_matrix(title, [(sel_obj, matrix, before_meta)])
                        else:
                            after = object_state(sel_obj)
                            if not states_equal(checkpoint, after):
                                history.push(SnapshotStep(title, [(sel_obj.history_uid, checkpoint, after)]))
                        done += 1
                    except Exception as e:
                        if group_steps is not None:
                            del group_steps[recorded:]
                        self.app.log.error("ToolTransform.%s --> %s" % (title, str(e)))
                        failed.append(ToolTransform._obj_name(sel_obj))
                        if not states_equal(checkpoint, object_state(sel_obj)):
                            restore_object_state(sel_obj, checkpoint)
                            try:
                                ToolTransform._after_change(self, sel_obj, None, set_offset)
                            except Exception as recovery:
                                self.app.log.error("ToolTransform rollback plot --> %s" % str(recovery))

            if skipped_cnc:
                self.app.inform.emit(cncjob_msg)
            if failed:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s.' % (_("Action was not executed"), ", ".join(failed)))
            elif done:
                self.app.inform.emit(done_msg)

    @staticmethod
    def _obj_name(obj):
        try:
            return str(obj.obj_options['name'])
        except Exception:
            return str(obj)

    def _after_change(self, sel_obj, matrix, set_offset=True):
        """Bounds, notification and plot after a geometry change."""
        try:
            bounds = sel_obj.bounds()
        except Exception:
            bounds = None
        if bounds is not None:
            if set_offset:
                try:
                    sel_obj.set_offset_values(bounds=bounds)
                except AttributeError:
                    pass
                except Exception as e:
                    self.app.log.debug("ToolTransform.set_offset_values() --> %s" % str(e))
        self.app.app_obj.object_changed.emit(sel_obj)
        if matrix is None:
            sel_obj.plot()
        else:
            sel_obj.plot_transformed(matrix)

    def on_rotate_action(self, num, point):
        px, py = point
        matrix = affine_rotate_matrix(-num, (px, py))

        def meta(o):
            o.obj_options['rotate'] = num

        ToolTransform._transform_selected(self,
            _("Rotating"), _("CNCJob objects can't be rotated."),
            lambda o: o.rotate(-num, point=(px, py)), matrix, meta, '[success] %s...' % _('Rotate done'))

    def on_flip(self, axis, point):
        px, py = point
        matrix = affine_mirror_matrix(axis, (px, py))

        def meta(o):
            # The axis is reversed because of the reference.
            key = 'mirror_y' if axis == 'X' else 'mirror_x'
            if key in o.obj_options:
                o.obj_options[key] = not o.obj_options[key]
            else:
                o.obj_options[key] = True

        if axis == 'X':
            msg = '[success] %s...' % _('Flip on Y axis done')
        else:
            msg = '[success] %s...' % _('Flip on X axis done')
        ToolTransform._transform_selected(self,
            _("Flipping"), _("CNCJob objects can't be mirrored/flipped."),
            lambda o: o.mirror(axis, (px, py)), matrix, meta, msg, set_offset=False)

    def on_skew(self, axis, xvalue, yvalue, point):
        if xvalue in [90, 180] or yvalue in [90, 180] or xvalue == yvalue == 0:
            self.app.inform.emit('[WARNING_NOTCL] %s' %
                                 _("Skew transformation can not be done for 0, 90 and 180 degrees."))
            return
        px, py = point
        matrix = affine_skew_matrix(xvalue, yvalue, (px, py))

        def meta(o):
            o.obj_options['skew_x'] = xvalue
            o.obj_options['skew_y'] = yvalue

        ToolTransform._transform_selected(self,
            _("Skewing"), _("CNCJob objects can't be skewed."),
            lambda o: o.skew(xvalue, yvalue, point=(px, py)), matrix, meta,
            '[success] %s %s %s...' % (_('Skew on the'), str(axis), _("axis done")))

    def on_scale(self, axis, xfactor, yfactor, point=None):
        px, py = (0, 0) if point is None else point
        matrix = affine_scale_matrix(xfactor, yfactor, (px, py))

        def meta(o):
            o.obj_options['scale_x'] = xfactor
            o.obj_options['scale_y'] = yfactor

        ToolTransform._transform_selected(self,
            _("Scaling"), _("CNCJob objects can't be scaled."),
            lambda o: o.scale(xfactor, yfactor, point=(px, py)), matrix, meta,
            '[success] %s %s %s...' % (_('Scale on the'), str(axis), _('axis done')))

    def on_offset(self, axis, num):
        vect = (num, 0) if axis == 'X' else (0, num)
        matrix = affine_translate_matrix(vect[0], vect[1])

        def meta(o):
            o.obj_options['offset_x' if axis == 'X' else 'offset_y'] = num

        ToolTransform._transform_selected(self,
            _("Offsetting"), _("CNCJob objects can't be offset."),
            lambda o: o.offset(vect), matrix, meta,
            '[success] %s %s %s...' % (_('Offset on the'), str(axis), _('axis done')))

    def on_buffer_action(self, value, join, factor=None):
        # The buffer is not affine: every object is plotted again.
        def apply(o):
            kind = o.kind.lower()
            if kind == 'gerber':
                if o.buffer(value, join, factor) == 'fail':
                    return 'fail'
                o.regenerate_source()
            elif kind == 'excellon':
                o.buffer(value, join, factor)
                o.regenerate_source()
            elif kind == 'geometry':
                o.buffer(value, join, factor)

        ToolTransform._transform_selected(self,
            _("Buffering"), _("CNCJob objects can't be buffered."),
            apply, None, lambda o: None, '[success] %s...' % _('Buffer done'), set_offset=False)

    @staticmethod
    def alt_bounds(obj_list):
        return alt_bounds(obj_list)
