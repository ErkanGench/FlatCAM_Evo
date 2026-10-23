# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 10/25/2019                                         #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea

from appCommon.Common import LoudDict, GracefulException
from camlib import flatten_shapely_geometry
from defaults import AppDefaults
from appPlugins.ToolCopperThieving.CopperThievingGen import (
    copper_fill, robber_bar_data, plating_mask, GridParameterError)
from appPlugins.ToolCopperThieving.CopperThievingUI import ThievingUI

import logging
from copy import deepcopy
import numpy as np
from typing import Iterable

from shapely import Polygon
from shapely.ops import unary_union

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolCopperThieving(AppTool):
    work_finished = QtCore.pyqtSignal()

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.canvas = self.app.plotcanvas

        self.decimals = self.app.decimals
        self.units = self.app.app_units

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = ThievingUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        # Objects involved in Copper thieving
        self.grb_object = None
        self.ref_obj = None
        self.sel_rect = []
        self.sm_object = None

        # store the flattened geometry here:
        self.flat_geometry = []

        # Mouse cursor positions
        self.mouse_is_dragging = False
        self.cursor_pos = (0, 0)
        self.first_click = False

        self.handlers_connected = False

        # Tool properties
        self.clearance_val = None
        self.margin_val = None
        self.geo_steps_per_circle = 128

        # Thieving geometry storage
        self.thief_solid_geometry = []

        # Robber bar geometry storage
        self.robber_geo = None
        self.robber_line = None

        self.rb_thickness = None

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolCopperThieving()")

        if toggle:
            # if the splitter is hidden, display it
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            # if the Tool Tab is hidden display it, else hide it but only if the objectName is the same
            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
            # show the Tab
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
                # focus on Tool Tab
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    # if the Tool Tab is not focused, focus on it
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        # focus on Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        # else remove the Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)

                        # if there are no objects loaded in the app then hide the Notebook widget
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        super().run()

        self.set_tool_ui()

        self.app.ui.notebook.setTabText(2, _("Copper Thieving"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+J', **kwargs)

    def connect_signals_at_init(self):
        # SIGNALS
        self.ui.ref_combo_type.currentIndexChanged.connect(self.on_ref_combo_type_change)
        self.ui.reference_combo.currentIndexChanged.connect(self.on_toggle_reference)
        self.ui.fill_type_combo.currentIndexChanged.connect(self.on_thieving_type)

        self.ui.fill_button.clicked.connect(self.on_add_copper_thieving_click)
        self.ui.rb_button.clicked.connect(self.on_add_robber_bar_click)
        self.ui.ppm_button.clicked.connect(self.on_add_ppm_click)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

        self.work_finished.connect(self.on_new_pattern_plating_object)

    def set_tool_ui(self):
        self.units = self.app.app_units
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.geo_steps_per_circle = int(self.app.options.get(
            "tools_copper_thieving_circle_steps",
            app_defaults.get("tools_copper_thieving_circle_steps", AppDefaults.factory_defaults.get("tools_copper_thieving_circle_steps"))
        ))

        self.clear_ui(self.layout)
        self.ui = ThievingUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.ui.clearance_entry.set_value(float(self.app.options.get(
            "tools_copper_thieving_clearance", app_defaults.get("tools_copper_thieving_clearance", AppDefaults.factory_defaults.get("tools_copper_thieving_clearance")))))
        self.ui.margin_entry.set_value(float(self.app.options.get(
            "tools_copper_thieving_margin", app_defaults.get("tools_copper_thieving_margin", AppDefaults.factory_defaults.get("tools_copper_thieving_margin")))))
        self.ui.reference_combo.set_value(self.app.options.get(
            "tools_copper_thieving_reference", app_defaults.get("tools_copper_thieving_reference", AppDefaults.factory_defaults.get("tools_copper_thieving_reference"))))
        self.ui.bbox_type_radio.set_value(self.app.options.get(
            "tools_copper_thieving_box_type", app_defaults.get("tools_copper_thieving_box_type", AppDefaults.factory_defaults.get("tools_copper_thieving_box_type"))))
        self.ui.fill_type_combo.set_value(self.app.options.get(
            "tools_copper_thieving_fill_type", app_defaults.get("tools_copper_thieving_fill_type", AppDefaults.factory_defaults.get("tools_copper_thieving_fill_type"))))

        self.ui.area_entry.set_value(self.app.options.get(
            "tools_copper_thieving_area", app_defaults.get("tools_copper_thieving_area", AppDefaults.factory_defaults.get("tools_copper_thieving_area"))))
        self.ui.dot_dia_entry.set_value(self.app.options.get(
            "tools_copper_thieving_dots_dia", app_defaults.get("tools_copper_thieving_dots_dia", AppDefaults.factory_defaults.get("tools_copper_thieving_dots_dia"))))
        self.ui.dot_spacing_entry.set_value(self.app.options.get(
            "tools_copper_thieving_dots_spacing", app_defaults.get("tools_copper_thieving_dots_spacing", AppDefaults.factory_defaults.get("tools_copper_thieving_dots_spacing"))))
        self.ui.square_size_entry.set_value(self.app.options.get(
            "tools_copper_thieving_squares_size", app_defaults.get("tools_copper_thieving_squares_size", AppDefaults.factory_defaults.get("tools_copper_thieving_squares_size"))))
        self.ui.squares_spacing_entry.set_value(self.app.options.get(
            "tools_copper_thieving_squares_spacing", app_defaults.get("tools_copper_thieving_squares_spacing", AppDefaults.factory_defaults.get("tools_copper_thieving_squares_spacing"))))
        self.ui.line_size_entry.set_value(self.app.options.get(
            "tools_copper_thieving_lines_size", app_defaults.get("tools_copper_thieving_lines_size", AppDefaults.factory_defaults.get("tools_copper_thieving_lines_size"))))
        self.ui.lines_spacing_entry.set_value(self.app.options.get(
            "tools_copper_thieving_lines_spacing", app_defaults.get("tools_copper_thieving_lines_spacing", AppDefaults.factory_defaults.get("tools_copper_thieving_lines_spacing"))))

        self.ui.rb_margin_entry.set_value(self.app.options.get(
            "tools_copper_thieving_rb_margin", app_defaults.get("tools_copper_thieving_rb_margin", AppDefaults.factory_defaults.get("tools_copper_thieving_rb_margin"))))
        self.ui.rb_thickness_entry.set_value(self.app.options.get(
            "tools_copper_thieving_rb_thickness", app_defaults.get("tools_copper_thieving_rb_thickness", AppDefaults.factory_defaults.get("tools_copper_thieving_rb_thickness"))))
        self.ui.only_pads_cb.set_value(self.app.options.get(
            "tools_copper_thieving_only_apds", app_defaults.get("tools_copper_thieving_only_apds", AppDefaults.factory_defaults.get("tools_copper_thieving_only_apds"))))
        self.ui.clearance_ppm_entry.set_value(self.app.options.get(
            "tools_copper_thieving_mask_clearance", app_defaults.get("tools_copper_thieving_mask_clearance", AppDefaults.factory_defaults.get("tools_copper_thieving_mask_clearance"))))
        self.ui.ppm_choice_combo.set_value(self.app.options.get(
            "tools_copper_thieving_geo_choice", app_defaults.get("tools_copper_thieving_geo_choice", AppDefaults.factory_defaults.get("tools_copper_thieving_geo_choice"))))

        # INIT SECTION
        self.handlers_connected = False
        self.robber_geo = None
        self.robber_line = None
        self.thief_solid_geometry = []

        # SELECT THE CURRENT OBJECT
        obj = self.app.collection.get_active()
        if obj and obj.kind == 'gerber':
            obj_name = obj.obj_options['name']
            self.ui.grb_object_combo.set_value(obj_name)

        if obj is None:
            self.ui.grb_object_combo.setCurrentIndex(0)

    def on_ref_combo_type_change(self):
        obj_type = self.ui.ref_combo_type.currentIndex()
        self.ui.ref_combo.setRootModelIndex(self.app.collection.index(obj_type, 0, QtCore.QModelIndex()))
        self.ui.ref_combo.setCurrentIndex(0)
        self.ui.ref_combo.obj_type = {
            _("Gerber"): "Gerber", _("Excellon"): "Excellon", _("Geometry"): "Geometry"
        }[self.ui.ref_combo_type.get_value()]

    def on_toggle_reference(self):
        ref_val = self.ui.reference_combo.get_value()
        self.ui.set_reference_visibility(ref_val)

        if ref_val == 0:    # "itself"
            self.ui.set_box_visibility(True)
        else:
            if self.ui.fill_type_combo.get_value() == 3:    # 'line'
                self.ui.reference_combo.set_value(0)    # 'itself'
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Lines Grid works only for 'itself' reference ..."))
                return

            self.ui.set_box_visibility(False)

    def on_thieving_type(self, new_index):
        if new_index == 0:     # "solid"
            self.ui.set_fill_visibility(new_index)
            self.app.inform.emit(_("Solid fill selected."))
        elif new_index == 1:   # 'dot'
            self.ui.set_fill_visibility(new_index)
            self.app.inform.emit(_("Dots grid fill selected."))
        elif new_index == 2:   # 'square'
            self.ui.set_fill_visibility(new_index)
            self.app.inform.emit(_("Squares grid fill selected."))
        else:   # 'lines'
            ref_val = self.ui.reference_combo.get_value()
            if ref_val != 0:    # 'itself'
                self.ui.reference_combo.set_value(0)    # 'itself'
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Lines Grid works only for 'itself' reference ..."))

            self.ui.set_fill_visibility(new_index)

    def on_add_robber_bar_click(self):
        rb_margin = self.ui.rb_margin_entry.get_value()
        self.rb_thickness = self.ui.rb_thickness_entry.get_value()

        # get the Gerber object on which the Robber bar will be inserted
        selection_index = self.ui.grb_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.grb_object_combo.rootModelIndex())

        try:
            self.grb_object = model_index.internalPointer().obj
        except Exception as e:
            self.app.log.error("ToolCopperThieving.on_add_robber_bar_click() --> %s" % str(e))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Gerber object loaded ..."))
            return

        self.app.proc_container.update_view_text(' %s' % _("Append geometry"))
        self.robber_line, self.robber_geo, geo_obj, new_apertures, new_follow_geo = robber_bar_data(
            self.grb_object.solid_geometry, self.grb_object.tools, self.grb_object.follow_geometry,
            rb_margin, self.rb_thickness)

        outname = '%s_%s' % (str(self.grb_object.obj_options['name']), 'robber')

        def initialize(grb_obj, app_obj):
            grb_obj.obj_options = LoudDict()
            for opt in self.grb_object.obj_options:
                if opt != 'name':
                    grb_obj.obj_options[opt] = deepcopy(self.grb_object.obj_options[opt])
            grb_obj.obj_options['name'] = outname
            grb_obj.multitool = False
            grb_obj.multigeo = False
            grb_obj.follow = deepcopy(self.grb_object.follow)
            grb_obj.tools = new_apertures
            grb_obj.solid_geometry = geo_obj
            grb_obj.follow_geometry = new_follow_geo
            # Export the composed copper so region holes can't erase source islands.
            grb_obj.export_as_regions = True

            app_obj.proc_container.update_view_text(' %s' % _("Append source file"))
            # update the source file with the new geometry:
            grb_obj.regenerate_source(name=outname)

        ret_val = self.new_object('gerber', outname, initialize, source=self.grb_object, plot=True)
        self.app.proc_container.update_view_text(' %s' % '')
        if ret_val == 'fail':
            self.app.call_source = "app"
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
            return

        self.on_exit()
        self.app.inform.emit('[success] %s' % _("Copper Thieving Tool done."))

    def on_add_copper_thieving_click(self):
        self.app.call_source = "copper_thieving_tool"

        self.clearance_val = self.ui.clearance_entry.get_value()
        self.margin_val = self.ui.margin_entry.get_value()
        reference_method = self.ui.reference_combo.get_value()

        # get the Gerber object on which the Copper thieving will be inserted
        selection_index = self.ui.grb_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.grb_object_combo.rootModelIndex())

        try:
            self.grb_object = model_index.internalPointer().obj
        except Exception as e:
            self.app.log.error("ToolCopperThieving.on_add_copper_thieving_click() --> %s" % str(e))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Gerber object loaded ..."))
            return

        if reference_method == 0:   # 'itself'
            bound_obj_name = self.ui.grb_object_combo.currentText()

            # Get reference object.
            try:
                self.ref_obj = self.app.collection.get_by_name(bound_obj_name)
            except Exception as e:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(e)))
                return "Could not retrieve object: %s" % self.grb_object.obj_options['name']

            self.copper_thieving(
                thieving_obj=self.grb_object,
                c_val=self.clearance_val,
                margin=self.margin_val
            )

        elif reference_method == 1:     # 'area'
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Click the start point of the area."))
            self.connect_event_handlers()

        elif reference_method == 2:     # 'box'
            bound_obj_name = self.ui.ref_combo.currentText()

            # Get reference object.
            try:
                self.ref_obj = self.app.collection.get_by_name(bound_obj_name)
            except Exception:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), bound_obj_name))
                return

            self.copper_thieving(
                thieving_obj=self.grb_object,
                ref_obj=self.ref_obj,
                c_val=self.clearance_val,
                margin=self.margin_val
            )

        # To be called after clicking on the plot.

    def on_mouse_release(self, event):
        event_pos = event.pos
        right_button = 2

        event_pos = self.app.plotcanvas.translate_coords(event_pos)

        # do clear area only for left mouse clicks
        if event.button == 1:
            if self.first_click is False:
                self.first_click = True
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Click the end point of the filling area."))

                self.cursor_pos = event_pos
                if self.app.grid_status() is True:
                    self.cursor_pos = self.app.geo_editor.snap(event_pos[0], event_pos[1])
            else:
                self.app.inform.emit(_("Zone added. Click to start adding next zone or right click to finish."))
                self.app.delete_selection_shape()

                if self.app.grid_status() is True:
                    curr_pos = self.app.geo_editor.snap(event_pos[0], event_pos[1])
                else:
                    curr_pos = (event_pos[0], event_pos[1])

                x0, y0 = self.cursor_pos[0], self.cursor_pos[1]
                x1, y1 = curr_pos[0], curr_pos[1]
                pt1 = (x0, y0)
                pt2 = (x1, y0)
                pt3 = (x1, y1)
                pt4 = (x0, y1)

                new_rectangle = Polygon([pt1, pt2, pt3, pt4])
                self.sel_rect.append(new_rectangle)

                # add a temporary shape on canvas
                self.draw_tool_selection_shape(old_coords=(x0, y0), coords=(x1, y1))
                self.first_click = False
                return

        elif event.button == right_button and self.mouse_is_dragging is False:
            self.first_click = False

            self.delete_tool_selection_shape()
            self.disconnect_event_handlers()

            if len(self.sel_rect) == 0:
                return

            self.sel_rect = unary_union(self.sel_rect)

            if not isinstance(self.sel_rect, Iterable):
                self.sel_rect = [self.sel_rect]

            self.copper_thieving(
                thieving_obj=self.grb_object,
                ref_obj=self.sel_rect,
                c_val=self.clearance_val,
                margin=self.margin_val
            )

    # called on mouse move
    def on_mouse_move(self, event):
        event_pos = event.pos
        event_is_dragging = event.is_dragging

        curr_pos = self.app.plotcanvas.translate_coords(event_pos)

        # detect mouse dragging motion
        if event_is_dragging is True:
            self.mouse_is_dragging = True
        else:
            self.mouse_is_dragging = False

        # update the cursor position
        if self.app.grid_status() is True:
            # Update cursor
            curr_pos = self.app.geo_editor.snap(curr_pos[0], curr_pos[1])

            app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
            self.app.app_cursor.set_data(np.asarray([(curr_pos[0], curr_pos[1])]),
                                         symbol='++', edge_color=self.app.plotcanvas.cursor_color,
                                         edge_width=self.app.options.get(
                                             "global_cursor_width", app_defaults.get("global_cursor_width", AppDefaults.factory_defaults.get("global_cursor_width"))),
                                         size=self.app.options.get(
                                             "global_cursor_size", app_defaults.get("global_cursor_size", AppDefaults.factory_defaults.get("global_cursor_size"))))

        if self.cursor_pos is None:
            self.cursor_pos = (0, 0)

        self.app.dx = curr_pos[0] - float(self.cursor_pos[0])
        self.app.dy = curr_pos[1] - float(self.cursor_pos[1])

        # # update the positions on status bar
        # self.app.ui.position_label.setText("&nbsp;<b>X</b>: %.4f&nbsp;&nbsp;   "
        #                                    "<b>Y</b>: %.4f&nbsp;" % (curr_pos[0], curr_pos[1]))
        # self.app.ui.rel_position_label.setText("<b>Dx</b>: %.4f&nbsp;&nbsp;  <b>Dy</b>: "
        #                                        "%.4f&nbsp;&nbsp;&nbsp;&nbsp;" % (self.app.dx, self.app.dy))
        self.app.ui.update_location_labels(self.app.dx, self.app.dy, curr_pos[0], curr_pos[1])

        # units = self.app.app_units.lower()
        # self.app.plotcanvas.text_hud.text = \
        #     'Dx:\t{:<.4f} [{:s}]\nDy:\t{:<.4f} [{:s}]\n\nX:  \t{:<.4f} [{:s}]\nY:  \t{:<.4f} [{:s}]'.format(
        #         self.app.dx, units, self.app.dy, units, curr_pos[0], units, curr_pos[1], units)
        self.app.plotcanvas.on_update_text_hud(self.app.dx, self.app.dy, curr_pos[0], curr_pos[1])

        # draw the utility geometry
        if self.first_click:
            self.app.draw_moving_selection_shape(old_coords=(self.cursor_pos[0], self.cursor_pos[1]),
                                                 coords=(curr_pos[0], curr_pos[1]))

    def copper_thieving(self, thieving_obj, ref_obj=None, c_val=None, margin=None, run_threaded=True):
        """

        :param thieving_obj:
        :param ref_obj:
        :param c_val:
        :param margin:
        :param run_threaded:
        :return:
        """

        if run_threaded:
            self.app.proc_container.new('%s ...' % _("Thieving"))
        else:
            QtWidgets.QApplication.processEvents()

        self.app.proc_container.view.set_busy('%s ...' % _("Thieving"))

        # #####################################################################
        # ####### Read the parameters #########################################
        # #####################################################################

        self.app.log.debug("Copper Thieving Tool started. Reading parameters.")
        self.app.inform.emit(_("Copper Thieving Tool started. Reading parameters."))
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        ref_selected = self.ui.reference_combo.get_value()
        if c_val is None:
            c_val = float(self.app.options.get(
                "tools_copper_thieving_clearance", app_defaults.get("tools_copper_thieving_clearance", AppDefaults.factory_defaults.get("tools_copper_thieving_clearance"))))
        if margin is None:
            margin = float(self.app.options.get(
                "tools_copper_thieving_margin", app_defaults.get("tools_copper_thieving_margin", AppDefaults.factory_defaults.get("tools_copper_thieving_margin"))))
        min_area = self.ui.area_entry.get_value()

        fill_type = self.ui.fill_type_combo.get_value()
        dot_dia = self.ui.dot_dia_entry.get_value()
        dot_spacing = self.ui.dot_spacing_entry.get_value()
        square_size = self.ui.square_size_entry.get_value()
        square_spacing = self.ui.squares_spacing_entry.get_value()
        line_size = self.ui.line_size_entry.get_value()
        line_spacing = self.ui.lines_spacing_entry.get_value()

        bbox_type = self.ui.bbox_type_radio.get_value()
        source_geometry = deepcopy(self.grb_object.solid_geometry)
        working_ref = thieving_obj if ref_obj is None else ref_obj
        reference_geometry = working_ref if ref_selected == 1 else getattr(working_ref, 'solid_geometry', None)
        reference_kind = getattr(working_ref, 'kind', None)
        target_geometry = source_geometry if thieving_obj is self.grb_object else deepcopy(thieving_obj.solid_geometry)

        def job_thread_thieving(tool_obj):
            self.app.log.debug("Copper Thieving Tool. Preparing isolation polygons.")
            tool_obj.app.inform.emit(_("Copper Thieving Tool. Preparing isolation polygons."))

            def progress(stage, percent):
                if stage == 'Working...':
                    tool_obj.app.log.debug("Copper Thieving Tool. Preparing areas to fill with copper.")
                    tool_obj.app.inform.emit(_("Copper Thieving Tool. Preparing areas to fill with copper."))
                elif stage == 'Create geometry':
                    tool_obj.app.log.debug("Copper Thieving Tool. Finished creating areas to fill with copper.")
                    tool_obj.app.inform.emit(_("Copper Thieving Tool. Appending new geometry and buffering."))
                texts = {
                    'Thieving': _("Thieving"), 'Buffering': _("Buffering"), 'Working...': _("Working..."),
                    'Create geometry': _("Create geometry"), 'Append geometry': _("Append geometry")}
                msg = ' %s' % texts.get(stage, '')
                if percent is not None:
                    msg += ' ... %d%%' % percent
                tool_obj.app.proc_container.update_view_text(msg)

            try:
                tool_obj.thief_solid_geometry, new_solid_geo, new_apertures = copper_fill(
                    source_geometry, tool_obj.grb_object.tools, reference_geometry, reference_kind,
                    ref_selected, bbox_type, c_val, margin, min_area, fill_type, dot_dia, dot_spacing,
                    square_size, square_spacing, line_size, line_spacing, tool_obj.geo_steps_per_circle,
                    abort=lambda: tool_obj.app.abort_flag, progress=progress,
                    target_geometry=target_geometry, line_fill=tool_obj.flat_geometry)
                if fill_type == 3:
                    tool_obj.flat_geometry = tool_obj.thief_solid_geometry
            except GracefulException:
                raise
            except GridParameterError:
                tool_obj.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "Grid size must be positive and spacing must be non-negative."))
                return 'fail'
            except Exception as error:
                if ref_selected != 0 and not isinstance(error, (TypeError, ValueError)):
                    raise
                tool_obj.app.log.error("ToolCopperThieving.copper_thieving() --> %s" % str(error))
                message = _("No object available.") if ref_selected == 0 else \
                    _("The reference object type is not supported.")
                tool_obj.app.inform.emit('[ERROR_NOTCL] %s' % message)
                return 'fail'

            outname = '%s_%s' % (str(self.grb_object.obj_options['name']), 'thief')

            def initialize(grb_obj, app_obj):
                grb_obj.obj_options = LoudDict()
                for opt in self.grb_object.obj_options:
                    if opt != 'name':
                        grb_obj.obj_options[opt] = deepcopy(self.grb_object.obj_options[opt])
                grb_obj.obj_options['name'] = outname
                grb_obj.multitool = False
                grb_obj.multigeo = False
                grb_obj.follow = deepcopy(self.grb_object.follow)
                grb_obj.tools = new_apertures
                grb_obj.solid_geometry = deepcopy(flatten_shapely_geometry(new_solid_geo))
                grb_obj.follow_geometry = deepcopy(self.grb_object.follow_geometry)
                # Export the composed copper so region holes can't erase source islands.
                grb_obj.export_as_regions = True

                app_obj.proc_container.update_view_text(' %s' % _("Append source file"))
                grb_obj.regenerate_source(name=outname)

            ret_val = self.new_object('gerber', outname, initialize, source=thieving_obj,
                                      plot=True, autoselected=False)
            tool_obj.app.proc_container.update_view_text(' %s' % '')
            if ret_val == 'fail':
                self.app.call_source = "app"
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                return

            tool_obj.on_exit()
            tool_obj.app.inform.emit('[success] %s' % _("Copper Thieving Tool done."))

        if run_threaded:
            self.app.worker_task.emit({'fcn': job_thread_thieving, 'params': [self]})
        else:
            job_thread_thieving(self)

    def on_add_ppm_click(self):
        run_threaded = True

        if run_threaded:
            self.app.proc_container.new('%s ...' % _("P-Plating Mask"))
        else:
            QtWidgets.QApplication.processEvents()

        self.app.proc_container.view.set_busy('%s ...' % _("P-Plating Mask"))

        if run_threaded:
            self.app.worker_task.emit({'fcn': self.on_new_pattern_plating_object, 'params': []})
        else:
            self.on_new_pattern_plating_object()

    def on_new_pattern_plating_object(self):
        ppm_clearance = self.ui.clearance_ppm_entry.get_value()
        geo_choice = self.ui.ppm_choice_combo.get_value()
        rb_thickness = self.ui.rb_thickness_entry.get_value()
        only_pads = self.ui.only_pads_cb.get_value()

        # get the Gerber object on which the Copper thieving will be inserted
        selection_index = self.ui.sm_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.sm_object_combo.rootModelIndex())

        try:
            self.sm_object = model_index.internalPointer().obj
        except Exception as e:
            self.app.log.error("ToolCopperThieving.on_add_ppm_click() --> %s" % str(e))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Gerber object loaded ..."))
            return

        self.app.proc_container.update_view_text(' %s' % _("Append PP-M geometry"))

        new_solid_geometry, new_apertures, new_follow_geo, plated_area = plating_mask(
            self.sm_object.solid_geometry, self.sm_object.tools, self.sm_object.follow_geometry,
            self.thief_solid_geometry, self.robber_geo, self.robber_line, ppm_clearance,
            geo_choice, rb_thickness, self.rb_thickness, only_pads)

        # and then set the total plated area value to the GUI element
        # the area is in mm2 when using Metric units, make it in cm2 for Metric units
        if self.units.lower() == 'mm':
            plated_area /= 100
        self.ui.plated_area_entry.set_value(plated_area)

        def obj_init(grb_obj, app_obj):
            grb_obj.obj_options = LoudDict()
            for opt in self.sm_object.obj_options:
                if opt != 'name':
                    grb_obj.obj_options[opt] = deepcopy(self.sm_object.obj_options[opt])
            grb_obj.obj_options['name'] = outname
            grb_obj.multitool = False
            grb_obj.source_file = []
            grb_obj.multigeo = False
            grb_obj.follow = False
            grb_obj.follow_geometry = deepcopy(new_follow_geo)
            grb_obj.tools = deepcopy(new_apertures)
            grb_obj.solid_geometry = deepcopy(flatten_shapely_geometry(new_solid_geometry))

            app_obj.proc_container.update_view_text(' %s' % _("Append source file"))
            # update the source file with the new geometry:
            grb_obj.regenerate_source(name=outname)
            app_obj.proc_container.update_view_text(' %s' % '')

        # Object name
        obj_name, separator, obj_extension = self.sm_object.obj_options['name'].rpartition('.')
        outname = '%s_%s.%s' % (obj_name, 'plating_mask', obj_extension) if separator else \
            '%s_%s' % (obj_extension, 'plating_mask')

        ret_val = self.new_object('gerber', outname, obj_init, source=self.sm_object, autoselected=False)
        if ret_val == 'fail':
            self.app.call_source = "app"
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
            return

        # Register recent file
        self.app.file_opened.emit("gerber", outname)

        self.on_exit()
        self.app.inform.emit('[success] %s' % _("Generating Pattern Plating Mask done."))

    def replot(self, obj, run_thread=True):
        def worker_task():
            with self.app.proc_container.new('%s...' % _("Plotting")):
                obj.plot()
                self.app.app_obj.object_plotted.emit(obj)

        if run_thread:
            self.app.worker_task.emit({'fcn': worker_task, 'params': []})
        else:
            worker_task()

    def on_exit(self, obj=None):
        # plot the objects
        if obj:
            try:
                for ob in obj:
                    self.replot(obj=ob)
            except (AttributeError, TypeError):
                self.replot(obj=obj)
            except Exception:
                return

        # reset the variables
        self.sel_rect = []

        # Mouse cursor positions
        self.mouse_is_dragging = False
        self.cursor_pos = (0, 0)
        self.first_click = False

        # if True it means we exited from tool in the middle of area adding therefore disconnect the events
        if self.handlers_connected is True:
            self.app.delete_selection_shape()

        self.disconnect_event_handlers()

        self.app.call_source = "app"
        self.app.inform.emit('[success] %s' % _("Copper Thieving Tool exit."))

    def connect_event_handlers(self):
        if self.handlers_connected is False:
            self.app.plotcanvas.graph_event_disconnect('mouse_press', self.app.on_mouse_click_over_plot)
            self.app.plotcanvas.graph_event_disconnect('mouse_move', self.app.on_mouse_move_over_plot)
            self.app.plotcanvas.graph_event_disconnect('mouse_release', self.app.on_mouse_click_release_over_plot)

            self.app.plotcanvas.graph_event_connect('mouse_release', self.on_mouse_release)
            self.app.plotcanvas.graph_event_connect('mouse_move', self.on_mouse_move)
            self.handlers_connected = True

    def disconnect_event_handlers(self):
        if self.handlers_connected is True:
            self.app.plotcanvas.graph_event_disconnect('mouse_release', self.on_mouse_release)
            self.app.plotcanvas.graph_event_disconnect('mouse_move', self.on_mouse_move)

            self.app.plotcanvas.graph_event_connect('mouse_press', self.app.on_mouse_click_over_plot)
            self.app.plotcanvas.graph_event_connect('mouse_move', self.app.on_mouse_move_over_plot)
            self.app.plotcanvas.graph_event_connect('mouse_release', self.app.on_mouse_click_release_over_plot)
            self.handlers_connected = False

    def flatten(self, geometry):
        """
        Creates a list of non-iterable linear geometry objects.
        :param geometry: Shapely type or list or list of list of such.

        Results are placed in self.flat_geometry
        """

        # ## If iterable, expand recursively.
        try:
            for geo in geometry:
                if geo is not None:
                    self.flatten(geometry=geo)

        # ## Not iterable, do the actual indexing and add.
        except TypeError:
            self.flat_geometry.append(geometry)

        return self.flat_geometry
