# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 1/24/2020                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCCheckBox
from appPlugins.ToolPunchGerber.PunchGerberUI import PunchUI
from appPlugins.ToolPunchGerber.PunchGerberGen import punch_geometry

import logging
from copy import deepcopy
from shapely import Point
import gettext
import appTranslation as fcTranslate
import builtins
from camlib import Geometry
from defaults import AppDefaults
from appParsers.feature_access import iter_features

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolPunchGerber(Geometry, AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        Geometry.__init__(self, geo_steps_per_circle=self.app.options.get(
            "geometry_circle_steps", app_defaults.get("geometry_circle_steps", AppDefaults.factory_defaults.get(
                "geometry_circle_steps"))), app=app)
        self.app = app
        self.decimals = self.app.decimals
        self.units = self.app.app_units
        self.old_name = ''
        self.grb_obj = None
        self.grid_status_memory = False
        self.poly_sel_disconnect_flag = False
        self.poly_dict = {}
        self.manual_pads = []
        self.old_selection_status = None
        self.ui = PunchUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def on_object_combo_changed(self):
        punch_plugin_found = False
        for idx in range(self.app.ui.notebook.count()):
            if self.app.ui.notebook.tabText(idx) == _("Punch Gerber"):
                punch_plugin_found = True
                break
        if punch_plugin_found is False:
            return
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            grb_obj = model_index.internalPointer().obj
        except Exception:
            return
        if self.old_name != '':
            old_obj = self.app.collection.get_by_name(self.old_name)
            if old_obj:
                old_obj.clear_plot_apertures()
                old_obj.mark_shapes.enabled = False
        if grb_obj:
            grb_obj.mark_shapes.enabled = True
            for ap_code in grb_obj.tools:
                grb_obj.mark_shapes_storage[ap_code] = []
            self.old_name = grb_obj.obj_options['name']
        self.build_tool_ui()

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolPunchGerber()")
        if toggle:
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
        self.build_tool_ui()
        self.on_object_combo_changed()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+H', **kwargs)

    def connect_signals_at_init(self):
        self.ui.level.toggled.connect(self.on_level_changed)
        self.ui.method_punch.activated_custom.connect(self.on_method)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)
        self.ui.punch_object_button.clicked.connect(self.on_punch_object_click)
        self.ui.circular_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.oblong_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.square_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.rectangular_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.other_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.gerber_object_combo.currentIndexChanged.connect(self.on_object_combo_changed)
        self.ui.punch_type_radio.activated_custom.connect(self.on_punch_type)
        self.ui.sel_all_btn.clicked.connect(self.on_manual_sel_all)
        self.ui.clear_all_btn.clicked.connect(self.on_manual_clear_all)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = PunchUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()
        self.reset_fields()
        self.ui_disconnect()
        self.ui_connect()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.ui.method_punch.set_value(self.app.options.get(
            "tools_punch_hole_type", app_defaults.get("tools_punch_hole_type", AppDefaults.factory_defaults.get(
                "tools_punch_hole_type"))))
        self.ui.select_all_cb.set_value(False)
        self.ui.dia_entry.set_value(float(self.app.options.get(
            "tools_punch_hole_fixed_dia", app_defaults.get("tools_punch_hole_fixed_dia", AppDefaults.factory_defaults.get(
                "tools_punch_hole_fixed_dia")))))
        self.ui.circular_ring_entry.set_value(float(self.app.options.get(
            "tools_punch_circular_ring", app_defaults.get("tools_punch_circular_ring", AppDefaults.factory_defaults.get(
                "tools_punch_circular_ring")))))
        self.ui.oblong_ring_entry.set_value(float(self.app.options.get(
            "tools_punch_oblong_ring", app_defaults.get("tools_punch_oblong_ring", AppDefaults.factory_defaults.get(
                "tools_punch_oblong_ring")))))
        self.ui.square_ring_entry.set_value(float(self.app.options.get(
            "tools_punch_square_ring", app_defaults.get("tools_punch_square_ring", AppDefaults.factory_defaults.get(
                "tools_punch_square_ring")))))
        self.ui.rectangular_ring_entry.set_value(float(self.app.options.get(
            "tools_punch_rectangular_ring", app_defaults.get("tools_punch_rectangular_ring", AppDefaults.factory_defaults.get(
                "tools_punch_rectangular_ring")))))
        self.ui.other_ring_entry.set_value(float(self.app.options.get(
            "tools_punch_others_ring", app_defaults.get("tools_punch_others_ring", AppDefaults.factory_defaults.get(
                "tools_punch_others_ring")))))
        self.ui.circular_cb.set_value(self.app.options.get(
            "tools_punch_circular", app_defaults.get("tools_punch_circular", AppDefaults.factory_defaults.get(
                "tools_punch_circular"))))
        self.ui.oblong_cb.set_value(self.app.options.get(
            "tools_punch_oblong", app_defaults.get("tools_punch_oblong", AppDefaults.factory_defaults.get(
                "tools_punch_oblong"))))
        self.ui.square_cb.set_value(self.app.options.get(
            "tools_punch_square", app_defaults.get("tools_punch_square", AppDefaults.factory_defaults.get(
                "tools_punch_square"))))
        self.ui.rectangular_cb.set_value(self.app.options.get(
            "tools_punch_rectangular", app_defaults.get("tools_punch_rectangular", AppDefaults.factory_defaults.get(
                "tools_punch_rectangular"))))
        self.ui.other_cb.set_value(self.app.options.get(
            "tools_punch_others", app_defaults.get("tools_punch_others", AppDefaults.factory_defaults.get(
                "tools_punch_others"))))
        self.ui.factor_entry.set_value(float(self.app.options.get(
            "tools_punch_hole_prop_factor", app_defaults.get("tools_punch_hole_prop_factor", AppDefaults.factory_defaults.get(
                "tools_punch_hole_prop_factor")))))
        self.ui.punch_type_radio.set_value("a")
        self.old_selection_status = None
        self.manual_pads = []
        obj = self.app.collection.get_active()
        if obj:
            if obj.kind == 'gerber':
                self.ui.gerber_object_combo.set_value(obj.obj_options['name'])
        else:
            available_gerber_list = [o for o in self.app.collection.get_list() if o.kind == 'gerber']
            if available_gerber_list:
                self.ui.gerber_object_combo.set_value(available_gerber_list[0].obj_options['name'])
        app_mode = self.app.options.get(
            "global_app_level", app_defaults.get("global_app_level", AppDefaults.factory_defaults.get("global_app_level")))
        self.change_level(app_mode)
        self.app.ui.notebook.setTabText(2, _("Punch Gerber"))

    def build_tool_ui(self):
        self.ui_disconnect()
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            obj = model_index.internalPointer().obj
            sorted_apertures = sorted(int(k) for k in obj.tools.keys())
        except Exception:
            obj = None
            sorted_apertures = []
        self.ui.build_apertures_table(obj.tools if sorted_apertures else {}, sorted_apertures)
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            grb_obj = model_index.internalPointer().obj
        except Exception:
            self.ui_connect()
            return
        grb_obj.clear_plot_apertures()
        self.ui_connect()

    def change_level(self, level):
        self.ui.level.setChecked(level == 'a')
        self.on_level_changed(self.ui.level.isChecked())

    def on_level_changed(self, checked):
        self.ui.on_level_changed(checked)

    def on_select_all(self, state):
        self.ui_disconnect()
        self.ui.circular_cb.setChecked(bool(state))
        self.ui.oblong_cb.setChecked(bool(state))
        self.ui.square_cb.setChecked(bool(state))
        self.ui.rectangular_cb.setChecked(bool(state))
        self.ui.other_cb.setChecked(bool(state))
        if not state:
            selection_index = self.ui.gerber_object_combo.currentIndex()
            model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
            try:
                grb_obj = model_index.internalPointer().obj
            except Exception:
                return
            grb_obj.clear_plot_apertures()
        self.ui_connect()

    def on_method(self, val):
        self.ui.on_method(val)

    def on_punch_type(self, val):
        self.ui.on_punch_type(val)

    def ui_connect(self):
        self.ui.select_all_cb.stateChanged.connect(self.on_select_all)
        for row in range(self.ui.apertures_table.rowCount()):
            try:
                wdg = self.ui.apertures_table.cellWidget(row, 3)
                assert isinstance(wdg, FCCheckBox)
                wdg.clicked.disconnect()
            except (TypeError, AttributeError):
                pass
            wdg = self.ui.apertures_table.cellWidget(row, 3)
            assert isinstance(wdg, FCCheckBox)
            wdg.clicked.connect(self.on_mark_cb_click_table)

    def ui_disconnect(self):
        try:
            self.ui.select_all_cb.stateChanged.disconnect()
        except (AttributeError, TypeError):
            pass
        for row in range(self.ui.apertures_table.rowCount()):
            try:
                wdg = self.ui.apertures_table.cellWidget(row, 3)
                assert isinstance(wdg, FCCheckBox)
                wdg.clicked.disconnect()
            except (TypeError, AttributeError):
                pass

    def on_punch_object_click(self):
        punch_type = self.ui.punch_type_radio.get_value()
        punch_method = self.ui.method_punch.get_value()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            self.grb_obj = model_index.internalPointer().obj
        except Exception:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No object is selected."))
            return
        if self.grb_obj is None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No object is selected."))
            return
        name = self.grb_obj.obj_options['name'].rpartition('.')[0]
        if name == '':
            name = self.grb_obj.obj_options['name']
        outname = name + "_punched"
        if punch_type == 'a':
            if punch_method == 'exc':
                self.on_excellon_method(self.grb_obj, outname)
            elif punch_method == 'fixed':
                self.on_fixed_method(self.grb_obj, outname)
            elif punch_method == 'ring':
                self.on_ring_method(self.grb_obj, outname)
            elif punch_method == 'prop':
                self.on_proportional_method(self.grb_obj, outname)
            self.clear_aperture_marking()
        else:
            if punch_method == 'exc':
                selection_index = self.ui.exc_combo.currentIndex()
                model_index = self.app.collection.index(selection_index, 0, self.ui.exc_combo.rootModelIndex())
                try:
                    model_index.internalPointer().obj
                except Exception:
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _("There is no Excellon object loaded ..."))
                    return
            if self.app.ui.grid_snap_btn.isChecked():
                self.grid_status_memory = True
                self.app.ui.grid_snap_btn.trigger()
            else:
                self.grid_status_memory = False
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Click on a pad to select it."))
            self.app.plotcanvas.graph_event_connect('mouse_release', self.on_single_poly_mouse_release)
            self.app.plotcanvas.graph_event_connect('key_press', self.on_key_press)
            self.app.plotcanvas.graph_event_disconnect('mouse_release', self.app.on_mouse_click_release_over_plot)
            self.app.plotcanvas.graph_event_disconnect('mouse_press', self.app.on_mouse_click_over_plot)
            self.poly_sel_disconnect_flag = True
            self.app.ui.notebook.setDisabled(True)
            self.old_selection_status = deepcopy(self.app.options.get(
                'global_selection_shape', app_defaults.get('global_selection_shape', AppDefaults.factory_defaults.get(
                    'global_selection_shape'))))
            self.app.options['global_selection_shape'] = False

    def _generate_punched_object(self, grb_obj, outname, method, manual=False):
        exc_obj = None
        if method == 'exc':
            selection_index = self.ui.exc_combo.currentIndex()
            model_index = self.app.collection.index(selection_index, 0, self.ui.exc_combo.rootModelIndex())
            try:
                exc_obj = model_index.internalPointer().obj
            except Exception:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Excellon object loaded ..."))
                return
            value = None
        elif method == 'fixed':
            value = float(self.ui.dia_entry.get_value())
            if value == 0.0:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("The value of the fixed diameter is 0.0. Aborting."))
                return 'fail'
        elif method == 'ring':
            value = (self.ui.circular_ring_entry.get_value(), self.ui.oblong_ring_entry.get_value(),
                     self.ui.square_ring_entry.get_value(), self.ui.rectangular_ring_entry.get_value(),
                     self.ui.other_ring_entry.get_value())
        else:
            value = self.ui.factor_entry.get_value() / 100.0
        selected = [int(it.text()) for it in self.ui.apertures_table.selectedItems()]
        enabled = (self.ui.circular_cb.get_value(), self.ui.oblong_cb.get_value(), self.ui.square_cb.get_value(),
                   self.ui.rectangular_cb.get_value(), self.ui.other_cb.get_value())
        new_options = {}
        for opt in grb_obj.obj_options:
            new_options[opt] = deepcopy(grb_obj.obj_options[opt])
        try:
            solid, apertures = punch_geometry(
                grb_obj.solid_geometry, grb_obj.tools, selected, method, value, self.decimals, enabled,
                manual_pads=self.manual_pads if manual else None,
                drill_geometry=exc_obj.solid_geometry if exc_obj is not None else None,
                drill_tools=exc_obj.tools if exc_obj is not None else None)
        except ValueError as error:
            if method != 'fixed':
                raise
            if str(error) == 'unchanged':
                self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                    "Failed. The new object geometry is the same as the one in the source object geometry..."))
            elif str(error) == 'size':
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "Failed. Punch hole size is bigger than some of the apertures in the Gerber object."))
            else:
                raise
            return 'fail'

        def init_func(new_obj, app_obj):
            new_obj.obj_options.update(new_options)
            new_obj.obj_options['name'] = outname
            new_obj.fill_color = deepcopy(grb_obj.fill_color)
            new_obj.outline_color = deepcopy(grb_obj.outline_color)
            new_obj.tools = deepcopy(apertures)
            new_obj.solid_geometry = deepcopy(solid)
            new_obj.regenerate_source(name=outname)

        self.new_object('gerber', outname, init_func, source=grb_obj, autoselected=False)

    def on_excellon_method(self, grb_obj, outname):
        return self._generate_punched_object(grb_obj, outname, 'exc')

    def on_excellon_manual_method(self, outname):
        return self._generate_punched_object(self.grb_obj, outname, 'exc', manual=True)

    def on_fixed_method(self, grb_obj, outname):
        return self._generate_punched_object(grb_obj, outname, 'fixed')

    def on_fixed_manual_method(self, outname):
        return self._generate_punched_object(self.grb_obj, outname, 'fixed', manual=True)

    def on_ring_method(self, grb_obj, outname):
        return self._generate_punched_object(grb_obj, outname, 'ring')

    def on_ring_manual_method(self, outname):
        return self._generate_punched_object(self.grb_obj, outname, 'ring', manual=True)

    def on_proportional_method(self, grb_obj, outname):
        return self._generate_punched_object(grb_obj, outname, 'prop')

    def on_proportional_manual_method(self, outname):
        return self._generate_punched_object(self.grb_obj, outname, 'prop', manual=True)

    def find_pad(self, point):
        pt = Point(point) if type(point) is tuple else point
        results = []
        sel_apid = []
        for it in self.ui.apertures_table.selectedItems():
            sel_apid.append(int(it.text()))
        for rec in iter_features(self.grb_obj):
            if rec.item_key in sel_apid and rec.polarity == 'dark' and isinstance(rec.follow, Point):
                if pt.within(rec.solid):
                    results.append({'apid': rec.item_key, 'idx': rec.feature_index})
        return results

    def on_manual_punch(self):
        punch_method = self.ui.method_punch.get_value()
        name = self.grb_obj.obj_options['name'].rpartition('.')[0]
        if name == '':
            name = self.grb_obj.obj_options['name']
        outname = name + "_punched"
        if punch_method == 'exc':
            self.on_excellon_manual_method(outname)
        elif punch_method == 'fixed':
            self.on_fixed_manual_method(outname)
        elif punch_method == 'ring':
            self.on_ring_manual_method(outname)
        elif punch_method == 'prop':
            self.on_proportional_manual_method(outname)

    def on_single_poly_mouse_release(self, event):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        event_pos = event.pos
        right_button = 2
        event_is_dragging = self.app.event_is_dragging
        try:
            x = float(event_pos[0])
            y = float(event_pos[1])
        except TypeError:
            return
        event_pos = (x, y)
        curr_pos = self.app.plotcanvas.translate_coords(event_pos)
        if event.button == 1:
            pads = self.find_pad(point=(curr_pos[0], curr_pos[1]))

            def test_pad(a, b):
                return True if a['apid'] == b['apid'] and a['idx'] == b['idx'] else False

            if self.manual_pads:
                tmp_lst = deepcopy(self.manual_pads)
                tmp_pads = deepcopy(pads)
                for old_pad in self.manual_pads:
                    for pad in pads:
                        if test_pad(old_pad, pad):
                            tmp_lst.remove(old_pad)
                            tmp_pads.remove(pad)
                self.manual_pads = [x for x in tmp_lst if x is not None] + tmp_pads
            else:
                self.manual_pads += pads
            if self.manual_pads:
                for el in pads:
                    apid = el['apid']
                    idx = el['idx']
                    clicked_poly = self.grb_obj.tools[apid]['geometry'][idx]['solid']
                    if clicked_poly not in self.poly_dict.values():
                        shape_id = self.app.tool_shapes.add(
                            tolerance=self.grb_obj.drawing_tolerance, layer=0, shape=clicked_poly,
                            color=self.app.options.get(
                                'global_sel_draw_color', app_defaults.get('global_sel_draw_color', AppDefaults.factory_defaults.get(
                                    'global_sel_draw_color'))) + 'FF',
                            face_color=self.app.options.get(
                                'global_sel_draw_color', app_defaults.get('global_sel_draw_color', AppDefaults.factory_defaults.get(
                                    'global_sel_draw_color'))) + 'FF', visible=True)
                        self.poly_dict[shape_id] = clicked_poly
                        self.app.inform.emit(
                            '%s: %d. %s' % (_("Added pad"), int(len(self.poly_dict)),
                                            _("Click to add next pad or right click to start.")))
                    else:
                        try:
                            for k, v in list(self.poly_dict.items()):
                                if v == clicked_poly:
                                    self.app.tool_shapes.remove(k)
                                    self.poly_dict.pop(k)
                                    break
                        except TypeError:
                            return
                        self.app.inform.emit(
                            '%s. %s' % (_("Removed pad"),
                                        _("Click to add/remove next pad or right click to start.")))
                    self.app.tool_shapes.redraw()
            else:
                self.app.inform.emit(_("No pad detected under click position."))
        elif event.button == right_button and event_is_dragging is False:
            if self.grid_status_memory is True:
                self.app.ui.grid_snap_btn.trigger()
            self.app.plotcanvas.graph_event_disconnect('mouse_release', self.on_single_poly_mouse_release)
            self.app.plotcanvas.graph_event_disconnect('key_press', self.on_key_press)
            self.app.plotcanvas.graph_event_connect('mouse_press', self.app.on_mouse_click_over_plot)
            self.app.plotcanvas.graph_event_connect('mouse_release', self.app.on_mouse_click_release_over_plot)
            self.poly_sel_disconnect_flag = False
            self.app.options['global_selection_shape'] = self.old_selection_status
            self.app.tool_shapes.clear(update=True)
            self.on_manual_punch()
            self.clear_aperture_marking()
            self.app.ui.notebook.setDisabled(False)
            self.manual_pads = []
            if self.poly_dict:
                self.poly_dict.clear()
            else:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("List of single polygons is empty. Aborting."))

    def on_key_press(self, event):
        if type(event) is int:
            key = event
        elif type(event) == QtGui.QKeyEvent:
            key = event.key()
        else:
            key = event.key
        if key == QtCore.Qt.Key.Key_Escape or key == 'Escape':
            if self.poly_sel_disconnect_flag is True:
                try:
                    if self.grid_status_memory is True:
                        self.app.ui.grid_snap_btn.trigger()
                    self.app.plotcanvas.graph_event_disconnect('mouse_release', self.on_single_poly_mouse_release)
                    self.app.plotcanvas.graph_event_disconnect('key_press', self.on_key_press)
                    self.app.tool_shapes.clear(update=True)
                except Exception as e:
                    self.app.log.error("ToolPaint.on_key_press() _2 --> %s" % str(e))
                self.app.plotcanvas.graph_event_connect('mouse_release', self.app.on_mouse_click_release_over_plot)
                self.app.plotcanvas.graph_event_connect('mouse_press', self.app.on_mouse_click_over_plot)
                self.poly_sel_disconnect_flag = False
                if self.old_selection_status is not None:
                    self.app.options['global_selection_shape'] = self.old_selection_status
            self.app.ui.notebook.setDisabled(False)
            self.poly_dict.clear()
            self.clear_aperture_marking()
            self.delete_moving_selection_shape()
            self.delete_tool_selection_shape()

    def on_mark_cb_click_table(self):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        try:
            cw = self.sender()
            cw_index = self.ui.apertures_table.indexAt(cw.pos())
            cw_row = cw_index.row()
        except AttributeError:
            cw_row = 0
        except TypeError:
            return
        try:
            aperture = int(self.ui.apertures_table.item(cw_row, 0).text())
        except AttributeError:
            return
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            grb_obj = model_index.internalPointer().obj
        except Exception:
            return
        wdg = self.ui.apertures_table.cellWidget(cw_row, 3)
        assert isinstance(wdg, FCCheckBox)
        if wdg.isChecked():
            color = self.app.options.get(
                'global_sel_draw_color', app_defaults.get('global_sel_draw_color', AppDefaults.factory_defaults.get(
                    'global_sel_draw_color')))
            color = (color + 'AA') if len(color) == 7 else (color[:-2] + 'AA')
            grb_obj.plot_aperture(color=color, marked_aperture=aperture, visible=True, run_thread=True)
        else:
            grb_obj.clear_plot_apertures(aperture=aperture)

    def on_manual_sel_all(self):
        if self.ui.punch_type_radio.get_value() != 'm':
            return
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            self.grb_obj = model_index.internalPointer().obj
        except Exception:
            return
        sel_apid = []
        for it in self.ui.apertures_table.selectedItems():
            sel_apid.append(int(it.text()))
        self.manual_pads = []
        for apid, apid_value in self.grb_obj.tools.items():
            if apid in sel_apid:
                for idx, elem in enumerate(apid_value['geometry']):
                    if 'follow' in elem and isinstance(elem['follow'], Point):
                        if 'solid' in elem:
                            sol_geo = elem['solid']
                            if sol_geo not in self.poly_dict.values():
                                self.manual_pads.append({'apid': apid, 'idx': idx})
                                sel_color_pref = self.app.options.get(
                                    'global_sel_draw_color', app_defaults.get('global_sel_draw_color', AppDefaults.factory_defaults.get(
                                        'global_sel_draw_color')))
                                sel_color = sel_color_pref + 'FF' if len(sel_color_pref) == 7 else sel_color_pref
                                shape_id = self.app.tool_shapes.add(
                                    tolerance=self.grb_obj.drawing_tolerance, layer=0, shape=sol_geo,
                                    color=sel_color, face_color=sel_color, visible=True)
                                self.poly_dict[shape_id] = sol_geo
        self.app.tool_shapes.redraw()
        self.app.inform.emit(_("All selectable pads are selected."))

    def on_manual_clear_all(self):
        if self.ui.punch_type_radio.get_value() != 'm':
            return
        try:
            for k in list(self.poly_dict.keys()):
                self.app.tool_shapes.remove(k)
            self.poly_dict.clear()
        except TypeError:
            return
        self.manual_pads = []
        self.poly_dict.clear()
        self.app.tool_shapes.redraw()
        self.app.inform.emit(_("Selection cleared."))

    def clear_aperture_marking(self):
        for row in range(self.ui.apertures_table.rowCount()):
            wdg = self.ui.apertures_table.cellWidget(row, 3)
            assert isinstance(wdg, FCCheckBox)
            wdg.set_value(False)

    def on_plugin_cleanup(self):
        self.reset_fields()

    def reset_fields(self):
        self.ui.gerber_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.ui.exc_combo.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        self.clear_aperture_marking()
        self.ui_disconnect()
