# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 11/21/2019                                         #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea
from appCommon.Common import LoudDict
from appPlugins.ToolFiducials.FiducialsGen import fiducial_geometry, fiducial_shapes, flatten_geometry
from appPlugins.ToolFiducials.FiducialsUI import FidoUI

import logging
from copy import deepcopy
from shapely import box, Point

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolFiducials(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.canvas = self.app.plotcanvas

        self.cursor_color_memory = None
        # store the current cursor type to be restored after manual geo
        self.old_cursor_type = self.app.options.get(
            "global_cursor_type",
            self.app.defaults.get("global_cursor_type", self.app.defaults.factory_defaults.get("global_cursor_type"))
        )

        self.decimals = self.app.decimals
        self.units = ''

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = FidoUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName

        # Objects involved in Copper thieving
        self.grb_object = None
        self.sm_object = None

        self.copper_obj_set = set()
        self.sm_obj_set = set()

        # store the flattened geometry here:
        self.flat_geometry = []

        # Mouse cursor positions
        self.cursor_pos = (0, 0)
        self.first_click = False

        self.mode_method = False

        # Tool properties
        self.fid_dia = None
        self.sm_opening_dia = None

        self.margin_val = None
        self.sec_position = None

        self.grb_steps_per_circle = self.app.options.get(
            "gerber_circle_steps",
            self.app.defaults.get("gerber_circle_steps", self.app.defaults.factory_defaults.get("gerber_circle_steps"))
        )

        self.click_points = []

        self.handlers_connected = False
        # storage for temporary shapes when adding manual markers
        self.temp_shapes = self.app.sel_shapes

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolFiducials()")

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

        self.app.ui.notebook.setTabText(2, _("Fiducials"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+F', **kwargs)

    def connect_signals_at_init(self):
        # #############################################################################
        # ############################ SIGNALS ########################################
        # #############################################################################
        self.ui.level.toggled.connect(self.on_level_changed)
        self.ui.add_cfid_button.clicked.connect(self.add_fiducials)
        self.ui.add_sm_opening_button.clicked.connect(self.add_soldermask_opening)

        self.ui.fid_type_combo.currentIndexChanged.connect(self.on_fiducial_type)
        self.ui.pos_radio.activated_custom.connect(self.on_second_point)
        self.ui.mode_radio.activated_custom.connect(self.on_method_change)

        self.ui.big_cursor_cb.stateChanged.connect(self.on_cursor_change)

        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    def set_tool_ui(self):
        self.units = self.app.app_units

        self.clear_ui(self.layout)
        self.ui = FidoUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.ui.fid_size_entry.set_value(self.app.options.get(
            "tools_fiducials_dia",
            self.app.defaults.get("tools_fiducials_dia", self.app.defaults.factory_defaults.get("tools_fiducials_dia"))
        ))
        self.ui.margin_entry.set_value(float(self.app.options.get(
            "tools_fiducials_margin",
            self.app.defaults.get("tools_fiducials_margin", self.app.defaults.factory_defaults.get("tools_fiducials_margin"))
        )))
        self.ui.mode_radio.set_value(self.app.options.get(
            "tools_fiducials_mode",
            self.app.defaults.get("tools_fiducials_mode", self.app.defaults.factory_defaults.get("tools_fiducials_mode"))
        ))
        self.ui.pos_radio.set_value(self.app.options.get(
            "tools_fiducials_second_pos",
            self.app.defaults.get("tools_fiducials_second_pos", self.app.defaults.factory_defaults.get("tools_fiducials_second_pos"))
        ))
        self.ui.fid_type_combo.set_value(self.app.options.get(
            "tools_fiducials_type",
            self.app.defaults.get("tools_fiducials_type", self.app.defaults.factory_defaults.get("tools_fiducials_type"))
        ))
        # needed so the visibility of some objects will be updated
        self.on_fiducial_type(val=self.ui.fid_type_combo.get_value())
        self.ui.line_thickness_entry.set_value(float(self.app.options.get(
            "tools_fiducials_line_thickness",
            self.app.defaults.get("tools_fiducials_line_thickness",
                                  self.app.defaults.factory_defaults.get("tools_fiducials_line_thickness"))
        )))

        self.click_points = []
        self.ui.bottom_left_coords_entry.set_value('')
        self.ui.top_right_coords_entry.set_value('')
        self.ui.sec_points_coords_entry.set_value('')

        self.copper_obj_set = set()
        self.sm_obj_set = set()

        # Show/Hide Advanced Options
        app_mode = self.app.options.get(
            "global_app_level",
            self.app.defaults.get("global_app_level", self.app.defaults.factory_defaults.get("global_app_level"))
        )
        self.change_level(app_mode)

        # SELECT THE CURRENT OBJECT
        obj = self.app.collection.get_active()
        if obj and obj.kind == 'gerber':
            obj_name = obj.obj_options['name']
            self.ui.grb_object_combo.set_value(obj_name)

        if obj is None:
            self.ui.grb_object_combo.setCurrentIndex(0)

        self.ui.big_cursor_cb.set_value(self.app.options.get(
            "tools_fiducials_big_cursor",
            self.app.defaults.get("tools_fiducials_big_cursor",
                                  self.app.defaults.factory_defaults.get("tools_fiducials_big_cursor"))
        ))

        # set cursor
        self.old_cursor_type = self.app.options.get(
            "global_cursor_type",
            self.app.defaults.get("global_cursor_type", self.app.defaults.factory_defaults.get("global_cursor_type"))
        )

    def change_level(self, level):
        """

        :param level:   application level: either 'b' or 'a'
        :type level:    str
        :return:
        """

        if level == 'a':
            self.ui.level.setChecked(True)
        else:
            self.ui.level.setChecked(False)
        self.on_level_changed(self.ui.level.isChecked())

    def on_level_changed(self, checked):
        FidoUI.set_level(self.ui, checked)

    def on_second_point(self, val):
        FidoUI.set_second_point(self.ui, val)

    def on_method_change(self, val):
        """
        Make sure that on method change we disconnect the event handlers and reset the points storage

        :param val:     value of the Radio button which trigger this method
        :return:        None
        """
        self.click_points = []

        if val == 'auto':
            try:
                self.disconnect_event_handlers()
            except TypeError:
                pass

            self.ui.big_cursor_cb.hide()
        else:
            self.ui.big_cursor_cb.show()

    def on_cursor_change(self, val):
        if val:
            self.app.options['tools_fiducials_big_cursor'] = True
        else:
            self.app.options['tools_fiducials_big_cursor'] = False

    def on_fiducial_type(self, val):
        FidoUI.set_fiducial_type(self.ui, val)

    def add_fiducials(self):
        self.app.call_source = "fiducials_tool"
        self.app.ui.notebook.setDisabled(True)

        self.mode_method = self.ui.mode_radio.get_value()
        self.margin_val = self.ui.margin_entry.get_value()
        self.sec_position = self.ui.pos_radio.get_value()
        fid_type = self.ui.fid_type_combo.get_value()

        self.click_points = []

        # get the Gerber object on which the Fiducial will be inserted
        selection_index = self.ui.grb_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.grb_object_combo.rootModelIndex())

        try:
            self.grb_object = model_index.internalPointer().obj
        except Exception as e:
            self.app.log.error("ToolFiducials.execute() --> %s" % str(e))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Gerber object loaded ..."))
            self.app.ui.notebook.setDisabled(False)
            self.app.call_source = "app"
            return

        self.copper_obj_set.add(self.grb_object.obj_options['name'])

        if self.mode_method == 'auto':
            xmin, ymin, xmax, ymax = self.grb_object.bounds()
            bbox = box(xmin, ymin, xmax, ymax)
            buf_bbox = bbox.buffer(self.margin_val, self.grb_steps_per_circle, join_style="mitre")
            x0, y0, x1, y1 = buf_bbox.bounds

            self.click_points.append(
                (
                    float('%.*f' % (self.decimals, x0)),
                    float('%.*f' % (self.decimals, y0))
                )
            )
            self.ui.bottom_left_coords_entry.set_value('(%.*f, %.*f)' % (self.decimals, x0, self.decimals, y0))

            self.click_points.append(
                (
                    float('%.*f' % (self.decimals, x1)),
                    float('%.*f' % (self.decimals, y1))
                )
            )
            self.ui.top_right_coords_entry.set_value('(%.*f, %.*f)' % (self.decimals, x1, self.decimals, y1))

            if self.sec_position == 'up':
                self.click_points.append(
                    (
                        float('%.*f' % (self.decimals, x0)),
                        float('%.*f' % (self.decimals, y1))
                    )
                )
                self.ui.sec_points_coords_entry.set_value('(%.*f, %.*f)' % (self.decimals, x0, self.decimals, y1))
            elif self.sec_position == 'down':
                self.click_points.append(
                    (
                        float('%.*f' % (self.decimals, x1)),
                        float('%.*f' % (self.decimals, y0))
                    )
                )
                self.ui.sec_points_coords_entry.set_value('(%.*f, %.*f)' % (self.decimals, x1, self.decimals, y0))

            ret_val = self.add_fiducials_geo(self.click_points, g_obj=self.grb_object, fid_type=fid_type)
            self.app.call_source = "app"
            if ret_val == 'fail':
                self.app.call_source = "app"
                self.app.ui.notebook.setDisabled(False)
                self.disconnect_event_handlers()
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                return

            self.on_exit()
        else:
            self.app.inform.emit(_("Click to add first Fiducial. Bottom Left..."))
            self.ui.bottom_left_coords_entry.set_value('')
            self.ui.top_right_coords_entry.set_value('')
            self.ui.sec_points_coords_entry.set_value('')

            if self.ui.big_cursor_cb.get_value():
                self.app.on_cursor_type(val="big", control_cursor=True)
                self.cursor_color_memory = self.app.plotcanvas.cursor_color
                self.app.plotcanvas.cursor_color = '#000000FF'
                self.app.app_cursor.enabled = True
            else:
                self.app.on_cursor_type(val="small", control_cursor=True)
                self.app.plotcanvas.cursor_color = self.cursor_color_memory

            self.connect_event_handlers()

        # To be called after clicking on the plot.

    def add_fiducials_geo(self, points_list, g_obj, fid_size=None, fid_type=None, line_size=None):
        """
        Add geometry to the solid_geometry of the copper Gerber object

        :param points_list:     list of coordinates for the fiducials
        :param g_obj:           the Gerber object where to add the geometry
        :param fid_size:        the overall size of the fiducial or fiducial opening depending on the g_obj type
        :param fid_type:        the type of fiducial: circular, cross, chess
        :param line_size:       the line thickenss when the fiducial type is cross
        :return:
        """
        fid_size = self.ui.fid_size_entry.get_value() if fid_size is None else fid_size
        fid_type = 0 if fid_type is None else fid_type  # default is 'circular' <=> 0
        if fid_type == "circular":
            fid_type = 0
        line_thickness = self.ui.line_thickness_entry.get_value() if line_size is None else line_size

        new_apertures, solid_geometry, geo_list = fiducial_geometry(
            points_list, g_obj.tools, g_obj.solid_geometry, fid_size, fid_type, line_thickness,
            self.grb_steps_per_circle, self.decimals)

        outname = '%s_%s' % (str(g_obj.obj_options['name']), 'fid')

        def initialize(grb_obj, app_obj):
            grb_obj.obj_options = LoudDict()
            for opt in g_obj.obj_options:
                if opt != 'name':
                    grb_obj.obj_options[opt] = deepcopy(g_obj.obj_options[opt])
            grb_obj.obj_options['name'] = outname
            grb_obj.multitool = False
            grb_obj.multigeo = False
            grb_obj.follow = deepcopy(g_obj.follow)
            grb_obj.tools = new_apertures
            grb_obj.solid_geometry = solid_geometry
            grb_obj.follow_geometry = deepcopy(g_obj.follow_geometry) + geo_list

            grb_obj.regenerate_source(name=outname)

        ret = self.new_object('gerber', outname, initialize, source=g_obj, plot=True)

        return ret

    def add_soldermask_opening(self):
        sm_opening_dia = self.ui.fid_size_entry.get_value() * 2.0

        # get the Gerber object on which the Fiducial will be inserted
        selection_index = self.ui.grb_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.grb_object_combo.rootModelIndex())

        try:
            self.sm_object = model_index.internalPointer().obj
        except Exception as e:
            self.app.log.error("ToolFiducials.add_soldermask_opening() --> %s" % str(e))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Gerber object loaded ..."))
            return

        self.sm_obj_set.add(self.sm_object.obj_options['name'])
        ret_val = self.add_fiducials_geo(
            self.click_points, g_obj=self.sm_object, fid_size=sm_opening_dia, fid_type='circular')
        self.app.call_source = "app"
        if ret_val == 'fail':
            self.app.call_source = "app"
            self.app.ui.notebook.setDisabled(False)
            self.disconnect_event_handlers()
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
            return

        self.on_exit()

    def on_mouse_release(self, event):
        event_pos = event.pos
        right_button = 2

        if event.button == 1:
            pos_canvas = self.canvas.translate_coords(event_pos)
            if self.app.grid_status():
                pos = self.app.geo_editor.snap(pos_canvas[0], pos_canvas[1])
            else:
                pos = (pos_canvas[0], pos_canvas[1])
            click_pt = Point([pos[0], pos[1]])

            self.click_points.append(
                (
                    float('%.*f' % (self.decimals, click_pt.x)),
                    float('%.*f' % (self.decimals, click_pt.y))
                )
            )
            self.check_points()
            self.draw_utility_geometry(pos=pos)
        elif event.button == right_button and self.app.event_is_dragging is False:
            self.on_exit(cancelled=True)

    def check_points(self):
        fid_type = self.ui.fid_type_combo.get_value()

        if len(self.click_points) == 1:
            self.ui.bottom_left_coords_entry.set_value(self.click_points[0])
            self.app.inform.emit(_("Click to add the last fiducial. Top Right..."))

        if self.sec_position != 'no':
            if len(self.click_points) == 2:
                self.ui.top_right_coords_entry.set_value(self.click_points[1])
                self.app.inform.emit(_("Click to add the second fiducial. Top Left or Bottom Right..."))
            elif len(self.click_points) == 3:
                self.ui.sec_points_coords_entry.set_value(self.click_points[2])
                self.app.inform.emit('[success] %s' % _("Done."))

                ret_val = self.add_fiducials_geo(self.click_points, g_obj=self.grb_object, fid_type=fid_type)
                self.app.call_source = "app"

                if ret_val == 'fail':
                    self.app.call_source = "app"
                    self.app.ui.notebook.setDisabled(False)
                    self.disconnect_event_handlers()
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                    return
                self.on_exit()
        else:
            if len(self.click_points) == 2:
                self.ui.top_right_coords_entry.set_value(self.click_points[1])
                self.app.inform.emit('[success] %s' % _("Done."))

                ret_val = self.add_fiducials_geo(self.click_points, g_obj=self.grb_object, fid_type=fid_type)
                self.app.call_source = "app"

                if ret_val == 'fail':
                    self.app.call_source = "app"
                    self.app.ui.notebook.setDisabled(False)
                    self.disconnect_event_handlers()
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                    return
                self.on_exit()

    def on_mouse_move(self, event):
        pass

    def replot(self, obj, run_thread=True):
        def worker_task():
            with self.app.proc_container.new('%s ...' % _("Plotting")):
                obj.plot()
                self.app.app_obj.object_plotted.emit(obj)

        if run_thread:
            self.app.worker_task.emit({'fcn': worker_task, 'params': []})
        else:
            worker_task()

    def connect_event_handlers(self):
        if self.handlers_connected is False:
            self.app.plotcanvas.graph_event_disconnect('mouse_press', self.app.on_mouse_click_over_plot)
            self.app.plotcanvas.graph_event_disconnect('mouse_release', self.app.on_mouse_click_release_over_plot)

            self.app.plotcanvas.graph_event_connect('mouse_release', self.on_mouse_release)

            self.handlers_connected = True

    def disconnect_event_handlers(self):
        if self.handlers_connected is True:
            self.app.plotcanvas.graph_event_disconnect('mouse_release', self.on_mouse_release)

            self.app.plotcanvas.graph_event_connect('mouse_press', self.app.on_mouse_click_over_plot)

            self.app.plotcanvas.graph_event_connect('mouse_release', self.app.on_mouse_click_release_over_plot)
            self.handlers_connected = False

    def flatten(self, geometry):
        """
        Creates a list of non-iterable linear geometry objects.
        :param geometry: Shapely type or list or list of list of such.

        Results are placed in self.flat_geometry
        """

        self.flat_geometry.extend(flatten_geometry(geometry))
        return self.flat_geometry

    def on_exit(self, cancelled=None):
        # restore cursor
        self.app.on_cursor_type(val=self.old_cursor_type, control_cursor=False)
        self.app.plotcanvas.cursor_color = self.cursor_color_memory

        self.clear_utility_geometry()

        # plot the object
        for ob_name in self.copper_obj_set:
            try:
                copper_obj = self.app.collection.get_by_name(name=ob_name)
                if len(self.copper_obj_set) > 1:
                    self.replot(obj=copper_obj, run_thread=False)
                else:
                    self.replot(obj=copper_obj)
            except (AttributeError, TypeError):
                continue

            # update the bounding box values
            try:
                a, b, c, d = copper_obj.bounds()
                copper_obj.obj_options['xmin'] = a
                copper_obj.obj_options['ymin'] = b
                copper_obj.obj_options['xmax'] = c
                copper_obj.obj_options['ymax'] = d
            except Exception as e:
                self.app.log.error("ToolFiducials.on_exit() copper_obj bounds error --> %s" % str(e))

        for ob_name in self.sm_obj_set:
            try:
                sm_obj = self.app.collection.get_by_name(name=ob_name)
                if len(self.sm_obj_set) > 1:
                    self.replot(obj=sm_obj, run_thread=False)
                else:
                    self.replot(obj=sm_obj)
            except (AttributeError, TypeError):
                continue

            # update the bounding box values
            try:
                a, b, c, d = sm_obj.bounds()
                sm_obj.obj_options['xmin'] = a
                sm_obj.obj_options['ymin'] = b
                sm_obj.obj_options['xmax'] = c
                sm_obj.obj_options['ymax'] = d
            except Exception as e:
                self.app.log.error("ToolFiducials.on_exit() sm_obj bounds error --> %s" % str(e))

        # Mouse cursor positions
        self.cursor_pos = (0, 0)
        self.first_click = False

        self.disconnect_event_handlers()

        self.app.call_source = "app"
        self.app.ui.notebook.setDisabled(False)

        if cancelled is True:
            self.app.delete_selection_shape()
            self.disconnect_event_handlers()
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled by user request."))
            return

        self.app.inform.emit('[success] %s' % _("Fiducials Tool exit."))

    def draw_utility_geometry(self, pos):
        fid_type = self.ui.fid_type_combo.get_value()
        line_thickness = self.ui.line_thickness_entry.get_value()
        fid_size = self.ui.fid_size_entry.get_value()
        pt = pos[0], pos[1]     # we ensure that this works in case the pt tuple is a return from Vispy (4 members)
        geo_list = fiducial_shapes(pt, fid_size, fid_type, line_thickness, self.grb_steps_per_circle)

        outline = '#0000FFAF'
        for util_geo in geo_list:
            self.temp_shapes.add(util_geo, color=outline, update=True, layer=0, tolerance=None)

        self.temp_shapes.redraw()

    def clear_utility_geometry(self):
        self.temp_shapes.clear(update=True)
        self.temp_shapes.redraw()

    def on_plugin_cleanup(self):
        self.on_exit()
