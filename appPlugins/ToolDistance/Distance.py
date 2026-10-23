# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea
from camlib import AppRTreeStorage
from appParsers.feature_access import iter_features
from appEditors.appGeoEditor import DrawToolShape
from defaults import AppDefaults
from appPlugins.ToolDistance.DistanceUI import DistanceUI
from appPlugins.ToolDistance.DistanceGen import (
    point_distance, point_deltas, measurement_angle, app_snap_centers, closest_center, exc_snap_position)

import logging
from copy import copy
import numpy as np

from shapely import Point, LineString

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class Distance(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.decimals = self.app.decimals

        self.canvas = self.app.plotcanvas
        self.units = self.app.app_units.lower()

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = DistanceUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

        # store here the first click and second click of the measurement process
        self.points = []

        self.active = False
        self.clicked_meas = None
        self.meas_line = None

        self.original_call_source = 'app'

        # monitor if the tool was used
        self.tool_done = False

        # holds the key for the last plotted utility shape
        self.last_shape = None

        self.total_distance = 0.0

        # store the grid status here
        self.grid_status_memory = False

        # store here if the snap button was clicked
        self.snap_toggled = None

        self.mouse_is_dragging = False

        # store here the cursor color
        self.cursor_color_memory = None
        # store the current cursor type to be restored after manual geo
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.old_cursor_type = self.app.options.get(
            "global_cursor_type",
            app_defaults.get("global_cursor_type", AppDefaults.factory_defaults.get("global_cursor_type")))

        # VisPy visuals
        self.sel_shapes = self.app.plotcanvas.new_shape_collection(layers=1)

        # Signals
        self.ui.measure_btn.clicked.connect(self.on_start_measuring)
        self.ui.multipoint_cb.stateChanged.connect(self.on_multipoint_measurement_changed)
        self.ui.big_cursor_cb.stateChanged.connect(self.on_cursor_change)

    def run(self, toggle=False):

        if self.app.plugin_tab_locked is True:
            return

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

                        if self.active:
                            self.on_exit()
                        return
            except AttributeError:
                pass

            super().run()
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.old_cursor_type = self.app.options.get(
            "global_cursor_type",
            app_defaults.get("global_cursor_type", AppDefaults.factory_defaults.get("global_cursor_type")))

        self.on_start_measuring() if self.active is False else self.on_exit()

    def init_plugin(self):
        self.points[:] = []
        self.tool_done = False
        self.last_shape = None
        self.total_distance = 0.0

        self.clicked_meas = 0
        self.original_call_source = copy(self.app.call_source)
        self.units = self.app.app_units.lower()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Ctrl+M', **kwargs)

    def set_tool_ui(self):
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

        self.app.ui.notebook.setTabText(2, _("Distance"))

        # Remove anything else in the appGUI
        self.app.ui.plugin_scroll_area.takeWidget()

        # Put ourselves in the appGUI
        self.app.ui.plugin_scroll_area.setWidget(self)

        # Switch notebook to tool page
        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
        self.units = self.app.app_units.lower()

        self.app.command_active = "Distance"
        self.tool_done = False
        self.grid_status_memory = True if self.app.ui.grid_snap_btn.isChecked() else False

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.ui.snap_center_cb.set_value(self.app.options.get(
            'tools_dist_snap_center',
            app_defaults.get('tools_dist_snap_center', AppDefaults.factory_defaults.get('tools_dist_snap_center'))))
        self.ui.big_cursor_cb.set_value(self.app.options.get(
            'tools_dist_big_cursor',
            app_defaults.get('tools_dist_big_cursor', AppDefaults.factory_defaults.get('tools_dist_big_cursor'))))

        snap_center = self.app.options.get(
            'tools_dist_snap_center',
            app_defaults.get('tools_dist_snap_center', AppDefaults.factory_defaults.get('tools_dist_snap_center')))
        self.on_snap_toggled(snap_center)

        try:
            self.ui.snap_center_cb.toggled.disconnect()
        except (AttributeError, TypeError):
            pass
        self.ui.snap_center_cb.toggled.connect(self.on_snap_toggled)

        # this is a hack; seems that triggering the grid will make the visuals better
        # trigger it twice to return to the original state
        self.app.ui.grid_snap_btn.trigger()
        self.app.ui.grid_snap_btn.trigger()

        # initial view of the layout
        self.initial_view()

        self.cursor_color_memory = self.app.plotcanvas.cursor_color
        if self.ui.big_cursor_cb.get_value():
            self.app.on_cursor_type(val="big", control_cursor=True)
            self.app.app_cursor.enabled = True

        self.app.call_source = 'measurement'

    def initial_view(self):
        self.display_start((0.0, 0.0))
        self.display_end((0.0, 0.0))
        DistanceUI.reset_results(self.ui, self.decimals)

    def on_snap_toggled(self, state):
        self.app.options['tools_dist_snap_center'] = state
        if state:
            # disengage the grid snapping since it will be hard to find the drills or pads on grid
            if self.app.ui.grid_snap_btn.isChecked():
                self.app.ui.grid_snap_btn.trigger()

    def on_start_measuring(self):
        # ENABLE the Measuring TOOL
        self.active = True

        # disable the measuring button
        self.ui.measure_btn.setDisabled(True)
        self.ui.measure_btn.setText('%s...' % _("Working"))

        self.init_plugin()
        self.ui_connect()
        self.set_tool_ui()

        self.app.inform.emit(_("MEASURING: Click on the Start point ..."))

    def ui_connect(self):
        # we can connect the app mouse events to the measurement tool
        # NEVER DISCONNECT THOSE before connecting some other handlers; it breaks something in VisPy
        self.canvas.graph_event_connect('mouse_move', self.on_mouse_move)
        self.canvas.graph_event_connect('mouse_release', self.on_mouse_click_release)

        # we disconnect the mouse/key handlers from wherever the measurement tool was called
        if self.app.call_source == 'app':
            self.canvas.graph_event_disconnect('mouse_move', self.app.on_mouse_move_over_plot)
            self.canvas.graph_event_disconnect('mouse_press', self.app.on_mouse_click_over_plot)
            self.canvas.graph_event_disconnect('mouse_release', self.app.on_mouse_click_release_over_plot)

        elif self.app.call_source == 'geo_editor':
            self.canvas.graph_event_disconnect('mouse_move', self.app.geo_editor.on_canvas_move)
            self.canvas.graph_event_disconnect('mouse_press', self.app.geo_editor.on_canvas_click)
            self.canvas.graph_event_disconnect('mouse_release', self.app.geo_editor.on_canvas_click_release)

        elif self.app.call_source == 'exc_editor':
            self.canvas.graph_event_disconnect('mouse_move', self.app.exc_editor.on_canvas_move)
            self.canvas.graph_event_disconnect('mouse_press', self.app.exc_editor.on_canvas_click)
            self.canvas.graph_event_disconnect('mouse_release', self.app.exc_editor.on_exc_click_release)

        elif self.app.call_source == 'grb_editor':
            self.canvas.graph_event_disconnect('mouse_move', self.app.grb_editor.on_canvas_move)
            self.canvas.graph_event_disconnect('mouse_press', self.app.grb_editor.on_canvas_click)
            self.canvas.graph_event_disconnect('mouse_release', self.app.grb_editor.on_canvas_click_release)

    def ui_disconnect(self):
        if self.original_call_source == 'app':
            self.canvas.graph_event_connect('mouse_move', self.app.on_mouse_move_over_plot)
            self.canvas.graph_event_connect('mouse_press', self.app.on_mouse_click_over_plot)
            self.canvas.graph_event_connect('mouse_release', self.app.on_mouse_click_release_over_plot)

        elif self.original_call_source == 'geo_editor':
            self.canvas.graph_event_connect('mouse_move', self.app.geo_editor.on_canvas_move)
            self.canvas.graph_event_connect('mouse_press', self.app.geo_editor.on_canvas_click)
            self.canvas.graph_event_connect('mouse_release', self.app.geo_editor.on_canvas_click_release)

        elif self.original_call_source == 'exc_editor':
            self.canvas.graph_event_connect('mouse_move', self.app.exc_editor.on_canvas_move)
            self.canvas.graph_event_connect('mouse_press', self.app.exc_editor.on_canvas_click)
            self.canvas.graph_event_connect('mouse_release', self.app.exc_editor.on_exc_click_release)

        elif self.original_call_source == 'grb_editor':
            self.canvas.graph_event_connect('mouse_move', self.app.grb_editor.on_canvas_move)
            self.canvas.graph_event_connect('mouse_press', self.app.grb_editor.on_canvas_click)
            self.canvas.graph_event_connect('mouse_release', self.app.grb_editor.on_canvas_click_release)

        # disconnect the mouse/key events from functions of measurement tool
        self.canvas.graph_event_disconnect('mouse_move', self.on_mouse_move)
        self.canvas.graph_event_disconnect('mouse_release', self.on_mouse_click_release)

    def on_exit(self):
        # DISABLE the Measuring TOOL
        self.active = False
        self.points = []
        self.last_shape = None
        self.total_distance = 0.0

        # enable the measuring button
        self.ui.measure_btn.setDisabled(False)
        self.ui.measure_btn.setText(_("Measure"))

        self.app.call_source = copy(self.original_call_source)

        self.ui_disconnect()

        self.app.command_active = None

        # delete the measuring line
        self.delete_all_shapes()

        # restore cursor
        self.app.on_cursor_type(val=self.old_cursor_type, control_cursor=False)
        if self.cursor_color_memory is not None:
            self.app.plotcanvas.cursor_color = self.cursor_color_memory

        # restore the grid status
        if self.app.ui.grid_snap_btn.isChecked() != self.grid_status_memory:
            self.app.ui.grid_snap_btn.trigger()

        if self.tool_done is False:
            self.tool_done = True
            self.app.inform.emit('%s' % _("Done."))

    def calculate_distance(self, pos):
        multipoint = self.ui.multipoint_cb.get_value()

        if multipoint is False:
            if len(self.points) == 1:
                self.ui.start_entry.set_value("(%.*f, %.*f)" % (self.decimals, pos[0], self.decimals, pos[1]))
                self.app.inform.emit(_("Click on the DESTINATION point ..."))
                return

            if len(self.points) == 2:
                self.ui.stop_entry.set_value("(%.*f, %.*f)" % (self.decimals, pos[0], self.decimals, pos[1]))

                d = point_distance(self.points[1], self.points[0])
                self.ui.total_distance_entry.set_value('%.*f' % (self.decimals, abs(d)))

                self.app.ui.update_location_labels(pos[0], pos[1], pos[0], pos[1])

                self.tool_done = True
                self.on_exit()
                self.app.inform.emit("[success] %s" % _("Done."))
        else:
            # update utility geometry
            if not self.points:
                self.add_utility_shape(pos)
            else:
                # update utility geometry
                # delete last shape and redd it correctly when using the snap and multipoint
                self.delete_utility_shape(self.last_shape)
                try:
                    self.add_utility_shape(start_pos=self.points[-2], end_pos=self.points[-1])
                except IndexError:
                    pass
                self.add_utility_shape(start_pos=self.points[-1], end_pos=pos)

            if len(self.points) == 1:
                # update start point
                self.ui.start_entry.set_value("(%.*f, %.*f)" % (self.decimals, pos[0], self.decimals, pos[1]))
            elif len(self.points) > 1:
                # update the distance
                self.total_distance += self.update_distance(pos, self.points[-2])
            else:
                self.total_distance += self.update_distance(pos)
            self.display_distance(self.total_distance)
            self.app.inform.emit('%s' % _("Click to add next point or right click to finish."))

    def snap_handler(self, pos):
        current_pt = Point(pos)
        shapes_storage = self.make_storage()

        if self.original_call_source == 'exc_editor':
            for storage in self.app.exc_editor.storage_dict:
                __, st_closest_shape = self.app.exc_editor.storage_dict[storage].nearest(pos)
                shapes_storage.insert(st_closest_shape)

            __, closest_shape = shapes_storage.nearest(pos)

            pos = exc_snap_position(closest_shape.geo, pos)

        elif self.original_call_source == 'grb_editor':
            clicked_pads = []
            for storage in self.app.grb_editor.storage_dict:
                try:
                    for shape_stored in self.app.grb_editor.storage_dict[storage]['geometry']:
                        if 'solid' in shape_stored.geo:
                            geometric_data = shape_stored.geo['solid']
                            if current_pt.within(geometric_data):
                                if isinstance(shape_stored.geo['follow'], Point):
                                    clicked_pads.append(shape_stored.geo['follow'])
                except KeyError:
                    pass

            if len(clicked_pads) > 1:
                self.tool_done = True
                self.on_exit()
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Pads overlapped. Aborting."))
                return

            if clicked_pads:
                pos = (clicked_pads[0].x, clicked_pads[0].y)

        elif self.original_call_source == 'app':
            loaded_obj_list = self.app.collection.get_list()
            snapable_obj_list = [o for o in loaded_obj_list if o.kind == 'excellon' or o.kind == 'gerber']
            if not snapable_obj_list:
                return pos

            clicked_geo = []
            for obj in snapable_obj_list:
                clicked_geo.extend(app_snap_centers(obj.kind, iter_features(obj), current_pt))

            if clicked_geo:
                # search for 'pad within pad' or 'drill within drill' situation and choose the closest geo center
                closest_pt = closest_center(clicked_geo, current_pt)
                # snap to the closest geometry in the clicked_geo list
                pos = (closest_pt.x, closest_pt.y)
            else:
                return pos
        else:
            return pos

        self.app.on_jump_to(custom_location=pos, fit_center=False)
        # Update cursor
        self.app.app_cursor.enabled = True
        if self.ui.big_cursor_cb.get_value():
            self.app.on_cursor_type(val="big", control_cursor=True)

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.app.app_cursor.set_data(np.asarray([(pos[0], pos[1])]),
                                     symbol='++', edge_color=self.app.plotcanvas.cursor_color,
                                     edge_width=self.app.options.get(
                                         "global_cursor_width",
                                         app_defaults.get("global_cursor_width",
                                                          AppDefaults.factory_defaults.get("global_cursor_width"))),
                                     size=self.app.options.get(
                                         "global_cursor_size",
                                         app_defaults.get("global_cursor_size",
                                                          AppDefaults.factory_defaults.get("global_cursor_size"))))
        return pos

    def on_multipoint_measurement_changed(self, val):
        DistanceUI.on_multipoint_measurement_changed(self.ui, val)

    def on_cursor_change(self, val):
        if val:
            self.app.options['tools_dist_big_cursor'] = True
            self.app.on_cursor_type(val="big", control_cursor=True)
        else:
            self.app.options['tools_dist_big_cursor'] = False
            self.app.on_cursor_type(val="small", control_cursor=True)

    def update_position_info(self, pos_canvas):
        big_cursor_state = self.ui.big_cursor_cb.get_value()
        grid_snap_state = self.app.grid_status()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        if big_cursor_state is False:
            if grid_snap_state:
                pos = self.app.geo_editor.snap(pos_canvas[0], pos_canvas[1])
                # Update cursor
                self.app.app_cursor.set_data(np.asarray([(pos[0], pos[1])]),
                                             symbol='++', edge_color=self.app.plotcanvas.cursor_color,
                                             edge_width=self.app.options.get(
                                                 "global_cursor_width",
                                                 app_defaults.get("global_cursor_width",
                                                                  AppDefaults.factory_defaults.get("global_cursor_width"))),
                                             size=self.app.options.get(
                                                 "global_cursor_size",
                                                 app_defaults.get("global_cursor_size",
                                                                  AppDefaults.factory_defaults.get("global_cursor_size"))))
            else:
                pos = (pos_canvas[0], pos_canvas[1])
        else:
            if grid_snap_state:
                pos = self.app.geo_editor.snap(pos_canvas[0], pos_canvas[1])
            else:
                if self.app.app_cursor.enabled is False:
                    self.app.app_cursor.enabled = True
                pos = (pos_canvas[0], pos_canvas[1])
            # Update cursor
            self.app.app_cursor.set_data(np.asarray([(pos[0], pos[1])]),
                                         symbol='++', edge_color=self.app.plotcanvas.cursor_color,
                                         edge_width=self.app.options.get(
                                             "global_cursor_width",
                                             app_defaults.get("global_cursor_width",
                                                              AppDefaults.factory_defaults.get("global_cursor_width"))),
                                         size=self.app.options.get(
                                             "global_cursor_size",
                                             app_defaults.get("global_cursor_size",
                                                              AppDefaults.factory_defaults.get("global_cursor_size"))))

        return pos

    def on_mouse_click_release(self, event):
        # mouse click releases will be accepted only if the left button is clicked
        # this is necessary because right mouse click or middle mouse click
        # are used for panning on the canvas
        # log.debug("Distance Tool --> mouse click release")

        snap_enabled = self.ui.snap_center_cb.get_value()
        multipoint = self.ui.multipoint_cb.get_value()

        event_pos = event.pos
        right_button = 2
        event_is_dragging = self.mouse_is_dragging

        pos_canvas = self.canvas.translate_coords(event_pos)
        if snap_enabled is False:
            # if GRID is active we need to get the snapped positions
            if self.app.grid_status():
                pos = self.app.geo_editor.snap(pos_canvas[0], pos_canvas[1])
            else:
                pos = pos_canvas[0], pos_canvas[1]
        else:
            pos = self.snap_handler(pos=(pos_canvas[0], pos_canvas[1]))

        if event.button == 1:
            # Reset here the relative coordinates so there is a new reference on the click position
            if len(self.points) == 1:
                self.app.ui.update_location_labels(0.0, 0.0, pos[0], pos[1])

            self.points.append(pos)
            self.calculate_distance(pos=pos)
        elif event.button == right_button and event_is_dragging is False:
            if multipoint is False:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
            else:
                # update end point
                try:
                    end_val = self.update_end_point(self.points[-1])
                except IndexError:
                    end_val = self.update_end_point((0.0, 0.0))
                self.display_end(end_val)
                self.app.inform.emit("[success] %s" % _("Done."))
            self.on_exit()

    def on_mouse_move(self, event):
        multipoint = self.ui.multipoint_cb.get_value()

        try:  # May fail in case mouse not within axes
            event_pos = event.pos
            self.mouse_is_dragging = event.is_dragging

            try:
                x = float(event_pos[0])
                y = float(event_pos[1])
            except TypeError:
                return
            pos_canvas = self.app.plotcanvas.translate_coords((x, y))

            # update position info
            pos = self.update_position_info(pos_canvas)

            # ------------------------------------------------------------
            # Update Status Bar location labels
            # ------------------------------------------------------------
            dx = pos[0]
            dy = pos[1]
            if len(self.points) == 1:
                dx = pos[0] - float(self.points[0][0])
                dy = pos[1] - float(self.points[0][1])
            elif len(self.points) == 2:
                dx = float(self.points[1][0]) - float(self.points[0][0])
                dy = float(self.points[1][1]) - float(self.points[0][1])
            self.app.ui.update_location_labels(dx=dx, dy=dy, x=pos[0], y=pos[1])

            # self.app.ui.update_location_labels(dx=None, dy=None, x=pos[0], y=pos[1])
            self.app.plotcanvas.on_update_text_hud(dx, dy, pos[0], pos[1])

        except Exception as e:
            self.app.log.error("Distance.on_mouse_move() position --> %s" % str(e))
            self.app.ui.update_location_labels(dx=None, dy=None, x=None, y=None)
            self.app.plotcanvas.on_update_text_hud('0.0', '0.0', '0.0', '0.0')
            return

        try:
            if multipoint is False:
                if len(self.points) == 1:
                    # update utility geometry
                    self.sel_shapes.clear()
                    self.add_utility_shape(start_pos=pos)
                    # update angle
                    angle_val = self.update_angle(dx=dx, dy=dy)
                    self.display_angle(angle_val)
                    # update end_point
                    end_val = self.update_end_point(pos=pos)
                    self.display_end(end_val)
                    # update deltas
                    deltax, deltay = self.update_deltas(pos=pos)
                    self.display_deltas(deltax, deltay)
                    # update distance
                    dist_val = self.update_distance(pos=pos)
                    self.display_distance(dist_val)
            else:
                # update utility geometry
                if self.points:
                    if self.last_shape is not None:
                        self.sel_shapes.remove(self.last_shape, update=False)
                    self.add_utility_shape(start_pos=self.points[-1], end_pos=pos)
                    self.display_distance(self.total_distance + self.update_distance(pos, prev_pos=self.points[-1]))
                else:
                    self.delete_utility_shape(self.last_shape)
        except Exception as e:
            self.app.log.error("Distance.on_mouse_move() update --> %s" % str(e))
            self.app.ui.update_location_labels(None, None, None, None)

    def update_angle(self, dx, dy):
        try:
            angle = measurement_angle(dx, dy)
        except Exception as e:
            self.app.log.error("Distance.update_angle() -> %s" % str(e))
            return None
        return angle

    def display_angle(self, val):
        DistanceUI.display_angle(self.ui, val, self.app.dec_format, self.decimals)

    def display_start(self, val):
        DistanceUI.display_start(self.ui, val)

    def update_end_point(self, pos):
        # update the end point value
        return DistanceUI.format_point(pos, self.app.dec_format, self.decimals)

    def display_end(self, val):
        DistanceUI.display_end(self.ui, val)

    def update_deltas(self, pos):
        return point_deltas(pos, self.points[0])

    def display_deltas(self, dx, dy):
        DistanceUI.display_deltas(self.ui, dx, dy, self.app.dec_format, self.decimals)

    def update_distance(self, pos, prev_pos=None):
        if prev_pos is None:
            prev_pos = self.points[0]
        return point_distance(pos, prev_pos)

    def display_distance(self, val):
        DistanceUI.display_distance(self.ui, val, self.decimals)

    def add_utility_shape(self, start_pos, end_pos=None):
        # draw the new shape of the utility geometry
        if end_pos is None:
            meas_line = LineString([start_pos, self.points[0]])
        else:
            meas_line = LineString([start_pos, end_pos])

        self.last_shape = DistanceUI.add_utility_shape(self.sel_shapes, meas_line)

    def delete_all_shapes(self):
        self.sel_shapes.clear()
        self.sel_shapes.redraw()

    def delete_utility_shape(self, shape):
        if shape is not None:
            self.sel_shapes.remove(shape, update=True)

    @staticmethod
    def make_storage():
        # ## Shape storage.
        storage = AppRTreeStorage()
        storage.get_points = DrawToolShape.get_pts

        return storage

    def on_plugin_cleanup(self):
        self.on_exit()
