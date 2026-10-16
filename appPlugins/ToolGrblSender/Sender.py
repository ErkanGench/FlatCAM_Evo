# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################

import math

from PyQt6 import QtWidgets, QtCore, QtGui

import serial
import serial.tools.list_ports

from appTool import AppTool
from defaults import AppDefaults
from appGUI.GUIElements import VerticalScrollArea, FCFileSaveDialog, FCMessageBox
from camlib import CNCjob

from appPlugins.Common.levelling_core import LevellingCoreMixin
from appPlugins.Common.grbl_protocol import (
    parse_grbl_status_state, parse_grbl_setting, parse_grbl_active_wcs, grbl_reply_error, probe_timeout_s,
    parse_grbl_status_report, work_position, grbl_report_scale)
from appPlugins.Common.gcode_segment import split_long_moves, parse_toolpath, _words, _g_key
from appPlugins.Common.levelling_interp import build_bilinear_grid
from appPlugins.ToolGrblSender import SenderGen
from appPlugins.ToolGrblSender.SenderGrbl import GrblClientMixin, stream_lines, validate_stream_lines
from appPlugins.ToolGrblSender.SenderUI import GrblSenderUI
from appPlugins.ToolGrblSender.SenderView3d import SenderView3d

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class GrblConsole(QtWidgets.QWidget):
    """The log of the lines sent to GRBL and of its replies, and a command line."""

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        lay.addWidget(self.log_view)
        h_lay = QtWidgets.QHBoxLayout()
        self.cmd_entry = QtWidgets.QLineEdit()
        self.cmd_entry.setPlaceholderText(_("Type GRBL command ..."))
        self.send_btn = QtWidgets.QToolButton()
        self.send_btn.setText(_("Send"))
        h_lay.addWidget(self.cmd_entry)
        h_lay.addWidget(self.send_btn)
        lay.addLayout(h_lay)
        self.cmd_entry.returnPressed.connect(self.on_send)
        self.send_btn.clicked.connect(self.on_send)

    def on_send(self):
        text = self.cmd_entry.text().strip()
        if not text:
            return
        self.cmd_entry.clear()
        self.tool.send_console_command(text)

    def append(self, text):
        self.log_view.appendPlainText(text)


class _StartRequest:
    """1 levelled Start: the live frame result is valid only for this request."""

    def __init__(self, seq, al_ctx, target_obj, map_frame, map_imported, safety_generation, check_mode):
        self.seq = seq                          # value of ToolGrblSender._start_seq at the request
        self.al_ctx = al_ctx                    # _al_capture_context(): map generation, target, units
        self.target_obj = target_obj
        self.map_frame = map_frame              # _al_map_frame at the request
        self.map_imported = map_imported
        self.safety_generation = safety_generation
        self.check_mode = check_mode


class ToolGrblSender(LevellingCoreMixin, GrblClientMixin, CNCjob, AppTool):
    grbl_port_closed_sig = QtCore.pyqtSignal()
    # (request, {'frame': ...} or {'error': ...}) from the frame worker; emitted after the port is released
    frame_ready_sig = QtCore.pyqtSignal(object, object)
    al_result_ready_sig = QtCore.pyqtSignal(object)
    build_al_table_sig = QtCore.pyqtSignal()
    show_probing_geo_sig = QtCore.pyqtSignal(bool, bool)
    # (done_lines, total_lines) from the stream worker
    stream_progress_sig = QtCore.pyqtSignal(int, int)
    # a parsed status report (dict) from a worker
    status_report_sig = QtCore.pyqtSignal(object)
    # how the stream worker ended: 'finished', 'stopped', 'check_passed', ... (see _on_stream_ended)
    stream_ended_sig = QtCore.pyqtSignal(str)
    # a text line for the console, from any thread
    console_line_sig = QtCore.pyqtSignal(str)

    def __init__(self, app):
        self.app = app
        self.decimals = self.app.decimals

        AppTool.__init__(self, app)
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        CNCjob.__init__(
            self,
            steps_per_circle=self.app.options.get(
                "cncjob_steps_per_circle",
                app_defaults.get("cncjob_steps_per_circle", AppDefaults.factory_defaults.get("cncjob_steps_per_circle"))),
            app=app
        )
        self._al_init_state()
        self._grbl_init_state()
        # the GRBL frame (WCS, work offset, report in inches) that the height map is bound to
        self._al_map_frame = None
        self._al_map_imported = False

        # the stream job: the lines that the sender streams, and the height-map
        # generation that they were levelled with (None: not levelled)
        self.job_lines = []
        self.job_map_generation = None
        self.job_target_name = None
        # the line number in the G-code text of each line of job_lines (for the messages)
        self.job_line_numbers = []
        self.view3d = None
        self._last_wco = None
        # what the stream worker tells the GUI thread with stream_ended_sig: {'done', 'last_text', 'errors'}
        self._stream_result = {}

        self.ui = GrblSenderUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

        self._al_core_signals_connected = False
        self.connect_signals_at_init()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='', **kwargs)

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolGrblSender()")

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
                        self.hide_console()

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

        self.app.ui.notebook.setTabText(2, _("GRBL Sender"))

        self.show_console_if_wanted()

    def connect_signals_at_init(self):
        # the signals of the tool and of the app live as long as the tool;
        # set_tool_ui() calls this method again for each new LevelUI, so
        # connect them only 1 time
        if not getattr(self, '_al_core_signals_connected', False):
            self._al_core_signals_connected = True
            self.grbl_port_closed_sig.connect(self._on_grbl_port_closed)
            self.al_result_ready_sig.connect(self._on_al_result_ready)
            self.build_al_table_sig.connect(self.build_al_table)
            self.show_probing_geo_sig.connect(self._on_show_probing_geo_sig)
            self.stream_progress_sig.connect(self._on_stream_progress)
            self.status_report_sig.connect(self._on_status_report)
            self.stream_ended_sig.connect(self._on_stream_ended)
            self.frame_ready_sig.connect(self._on_frame_ready)
            self.console_line_sig.connect(lambda line: self._console().append(line))
            # When object selection on canvas change
            self.app.proj_selection_changed.connect(self.on_object_selection_changed)
            # Cleanup on Graceful exit (CTRL+ALT+X combo key)
            self.app.cleanup.connect(self.set_tool_ui)
            self.app.cleanup.connect(self._grbl_disconnect)
            # close the serial port when the application ends
            qt_app = QtWidgets.QApplication.instance()
            if qt_app is not None:
                qt_app.aboutToQuit.connect(self._grbl_force_close)
        self.ui.level.toggled.connect(self.on_level_changed)

        self.ui.avoid_exc_holes_cb.toggled.connect(self.on_avoid_exc_holes)

        self.ui.al_mode_radio.activated_custom.connect(self.on_mode_radio)
        self.ui.al_method_radio.activated_custom.connect(self.on_method_radio)
        self.ui.precision_probe_cb.toggled.connect(self.on_precision_probe_changed)
        self.ui.precision_feed_entry.valueChanged.connect(self.on_precision_probe_changed)
        self.ui.precision_retract_entry.valueChanged.connect(self.on_precision_probe_changed)
        self.ui.plot_probing_pts_cb.toggled.connect(self.show_probing_geo)
        # GRBL
        self.ui.com_search_button.clicked.connect(self.on_grbl_search_ports)
        self.ui.add_bd_button.clicked.connect(self.on_grbl_add_baudrate)
        self.ui.del_bd_button.clicked.connect(self.on_grbl_delete_baudrate_grbl)
        self.ui.baudrates_list_combo.currentTextChanged.connect(self.on_baudrate_changed)
        self.ui.controller_reset_button.clicked.connect(self.on_grbl_reset)
        self.ui.com_connect_button.clicked.connect(self.on_grbl_connect)
        self.ui.grbl_send_button.clicked.connect(self.on_grbl_send_command)
        self.ui.grbl_command_entry.returnPressed.connect(self.on_grbl_send_command)

        # Jog
        self.ui.jog_wdg.jog_up_button.clicked.connect(lambda: self.on_grbl_jog(direction='yplus'))
        self.ui.jog_wdg.jog_down_button.clicked.connect(lambda: self.on_grbl_jog(direction='yminus'))
        self.ui.jog_wdg.jog_right_button.clicked.connect(lambda: self.on_grbl_jog(direction='xplus'))
        self.ui.jog_wdg.jog_left_button.clicked.connect(lambda: self.on_grbl_jog(direction='xminus'))
        self.ui.jog_wdg.jog_z_up_button.clicked.connect(lambda: self.on_grbl_jog(direction='zplus'))
        self.ui.jog_wdg.jog_z_down_button.clicked.connect(lambda: self.on_grbl_jog(direction='zminus'))
        self.ui.jog_wdg.jog_origin_button.clicked.connect(lambda: self.on_grbl_jog(direction='origin'))

        # Zero
        self.ui.zero_axs_wdg.grbl_zerox_button.clicked.connect(lambda: self.on_grbl_zero(axis='x'))
        self.ui.zero_axs_wdg.grbl_zeroy_button.clicked.connect(lambda: self.on_grbl_zero(axis='y'))
        self.ui.zero_axs_wdg.grbl_zeroz_button.clicked.connect(lambda: self.on_grbl_zero(axis='z'))
        self.ui.zero_axs_wdg.grbl_zero_all_button.clicked.connect(lambda: self.on_grbl_zero(axis='all'))
        self.ui.zero_axs_wdg.grbl_homing_button.clicked.connect(self.on_grbl_homing)

        # Sender
        self.ui.grbl_report_button.clicked.connect(self.on_grbl_report)
        self.ui.grbl_get_param_button.clicked.connect(
            lambda: self.on_grbl_get_parameter(param=self.ui.grbl_parameter_entry.get_value()))
        self.ui.import_heights_button.clicked.connect(self.on_import_height_map)
        self.ui.pause_resume_button.clicked.connect(self.on_grbl_pause_resume)
        self.ui.grbl_get_heightmap_button.clicked.connect(self.on_grbl_autolevel)
        self.ui.stop_probing_button.clicked.connect(self.on_grbl_stop)
        self.ui.grbl_save_height_map_button.clicked.connect(self.on_grbl_heightmap_save)

        # Reset Tool
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

        self.ui.console_cb.toggled.connect(self.on_console_toggled)
        self.ui.start_button.clicked.connect(self.on_start)
        self.ui.hold_button.clicked.connect(lambda: self._grbl_realtime(b'!'))
        self.ui.resume_button.clicked.connect(lambda: self._grbl_realtime(b'~'))
        self.ui.stop_button.clicked.connect(self.on_stream_stop)
        self.ui.unlock_button.clicked.connect(self.on_unlock)
        self.ui.save_levelled_button.clicked.connect(self.on_save_levelled_gcode)
        self.ui.view3d_button.clicked.connect(self.on_show_3d)
        for (name, text), (btn, byte) in self.ui.ov_buttons.items():
            btn.clicked.connect(lambda checked=False, b=byte: self._grbl_realtime(b))

    def set_tool_ui(self):
        # closing or resetting the tool while adding manual points must give
        # the canvas events back to the app
        self._release_manual_mouse_events()

        self.units = self.app.app_units.upper()
        # new probe points carry a placeholder height of 0.0, so a full storage
        # alone does not make a valid map: keep the flag that a probe or an import set
        self.al_heights_valid = bool(getattr(self, 'al_heights_valid', False)) and \
            self._height_map_is_complete()
        self.clear_ui(self.layout)
        self.ui = GrblSenderUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        mode_blocked = self.ui.al_mode_radio.blockSignals(True)
        method_blocked = self.ui.al_method_radio.blockSignals(True)
        try:
            self._populate_tool_ui()
        finally:
            self.ui.al_method_radio.blockSignals(method_blocked)
            self.ui.al_mode_radio.blockSignals(mode_blocked)

    def _populate_tool_ui(self):
        # Both radio groups stay blocked, including the initial to_form().
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        # try to select in the CNCJob combobox the active object
        try:
            selected_obj = self.app.collection.get_active()
            if selected_obj.kind == 'cncjob':
                current_name = selected_obj.obj_options['name']
                self.ui.object_combo.set_value(current_name)
        except Exception:
            pass

        loaded_obj = self.app.collection.get_by_name(self.ui.object_combo.get_value())
        # kept probe data belongs to its owner object; drop it if the tool opens on another object
        if getattr(self, '_al_target_name', None) is not None and (
                self.ui.object_combo.get_value() != self._al_target_name or
                loaded_obj is not getattr(self, '_al_target_obj', None)):
            self._clear_probe_data()
        if loaded_obj and loaded_obj.kind == 'cncjob':
            name = loaded_obj.obj_options['name']
        else:
            name = ''

        # Shapes container for the Voronoi cells in Autolevelling
        self._new_probing_shapes(name)

        self.form_fields.update({
            "tools_al_probe_tip_dia":           self.ui.probe_tip_dia_entry,
            "tools_al_travel_z":                self.ui.ptravelz_entry,
            "tools_al_probe_depth":             self.ui.pdepth_entry,
            "tools_al_probe_fr":                self.ui.feedrate_probe_entry,
            "tools_al_method":                  self.ui.al_method_radio,
            "tools_al_mode":                    self.ui.al_mode_radio,
            "tools_al_avoid_exc_holes_size":    self.ui.avoid_exc_holes_size_entry,
            "tools_al_rows":                    self.ui.al_rows_entry,
            "tools_al_columns":                 self.ui.al_columns_entry,
            "tools_grbl_jog_step":              self.ui.jog_step_entry,
            "tools_grbl_jog_fr":                self.ui.jog_fr_entry,
        })

        # Fill Form fields
        self.to_form()
        self.on_grbl_search_ports(muted=True)
        self._restore_baudrate(app_defaults)

        self.ui.plot_probing_pts_cb.set_value(
            self.app.options.get(
                "tools_al_plot_points",
                app_defaults.get("tools_al_plot_points", AppDefaults.factory_defaults.get("tools_al_plot_points")))
        )
        self.ui.avoid_exc_holes_cb.set_value(
            self.app.options.get(
                "tools_al_avoid_exc_holes",
                app_defaults.get("tools_al_avoid_exc_holes", AppDefaults.factory_defaults.get("tools_al_avoid_exc_holes")))
        )

        self.ui.al_probe_points_table.setRowCount(0)
        self.ui.al_probe_points_table.resizeColumnsToContents()
        self.ui.al_probe_points_table.resizeRowsToContents()
        v_header = self.ui.al_probe_points_table.verticalHeader()
        v_header.hide()
        self.ui.al_probe_points_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        h_header = self.ui.al_probe_points_table.horizontalHeader()
        h_header.setMinimumSectionSize(10)
        h_header.setDefaultSectionSize(70)
        h_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        h_header.resizeSection(0, 20)
        h_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        h_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        self.ui.al_probe_points_table.setMinimumHeight(self.ui.al_probe_points_table.getHeight())
        self.ui.al_probe_points_table.setMaximumHeight(self.ui.al_probe_points_table.getHeight())

        # Set initial UI
        self.ui.al_rows_entry.setDisabled(True)
        self.ui.al_rows_label.setDisabled(True)
        self.ui.al_columns_entry.setDisabled(True)
        self.ui.al_columns_label.setDisabled(True)
        self.ui.al_method_lbl.setDisabled(True)
        self.ui.al_method_radio.set_value('v')
        self.ui.al_method_radio.setDisabled(True)

        # Show/Hide Advanced Options
        app_mode = self.app.options.get(
            "global_app_level",
            app_defaults.get("global_app_level", AppDefaults.factory_defaults.get("global_app_level")))
        self.change_level(app_mode)

        try:
            self.ui.object_combo.currentIndexChanged.disconnect()
        except (AttributeError, TypeError):
            pass
        self.ui.object_combo.currentIndexChanged.connect(self.on_object_changed)

        self.build_tool_ui()

        if self._is_supported_target(loaded_obj):
            self.ui.al_frame.setDisabled(False)
            self._restore_al_radios(loaded_obj)
            self._restore_al_precision(loaded_obj)
        else:
            self.ui.al_frame.setDisabled(True)

        # a retained (probed/imported) height map was preserved above (its
        # validity was already computed at the top of this method); rebuild
        # the table so the kept points show up again
        if self.al_heights_valid:
            self.build_al_table()
            # the slot plots only if 'Plot probing points' is checked
            self._on_show_probing_geo_sig(True, True)

        self.on_avoid_exc_holes(
            self.app.options.get(
                "tools_al_avoid_exc_holes",
                app_defaults.get("tools_al_avoid_exc_holes", AppDefaults.factory_defaults.get("tools_al_avoid_exc_holes")))
        )

        self.ui.console_cb.set_value(bool(self.app.options.get(
            "tools_grbl_console_visible",
            app_defaults.get("tools_grbl_console_visible", False))))
        self.ui.autolevel_cb.set_value(False)
        self._grbl_set_ui_connected(self._grbl_port_ready())

    def on_object_changed(self):
        # first: a pending levelled Start request is old before the new target is published
        self._invalidate_start_requests()

        # the job and its toolpath belong to the old object
        self.job_lines = []
        self.job_line_numbers = []
        self.job_map_generation = None
        if self.view3d is not None:
            self.view3d.set_toolpath([])

        # load the object
        obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            target_obj = self.app.collection.get_by_name(obj_name)
        except Exception:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(obj_name)))
            return

        # probe points, heights and probing G-code belong to 1 object (name and
        # identity); forget them when the user selects a different object
        if obj_name != getattr(self, '_al_target_name', None) or \
                target_obj is not getattr(self, '_al_target_obj', None):
            self._clear_probe_data()

        if self._is_supported_target(target_obj):
            self.ui.al_frame.setDisabled(False)

            # Shapes container for the Voronoi cells in Autolevelling
            self._new_probing_shapes(obj_name)

            self._restore_al_radios(target_obj)
            self._restore_al_precision(target_obj)

            # the new container is empty: draw the kept points again
            if self.al_voronoi_geo_storage:
                self._on_show_probing_geo_sig(True, True)
        else:
            self.ui.al_frame.setDisabled(True)

    @staticmethod
    def _is_supported_target(target_obj):
        """The sender accepts every CNCJob; it segments the G-code itself."""
        return target_obj is not None and getattr(target_obj, 'kind', None) == 'cncjob'

    # the mixin methods on_mode_radio() and on_method_radio() call this name
    _is_supported_al_target = _is_supported_target

    def to_form(self, storage=None):
        if storage is None:
            storage = self.app.options

        for k in self.form_fields:
            for option in storage:
                if option.startswith('tools_al_') or option.startswith('tools_grbl_'):
                    if k == option:
                        try:
                            self.form_fields[k].set_value(storage[option])
                        except Exception:
                            # it may fail for form fields found in the tools tables if there are no rows
                            pass

    def on_grbl_search_ports(self, muted=None):
        port_list = self.on_grbl_list_serial_ports()
        self.ui.com_list_combo.clear()
        self.ui.com_list_combo.addItems(port_list)
        if muted is not True:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("COM list updated ..."))

    def on_grbl_connect(self):
        if self._grbl_op is not None or self._grbl_close_pending:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("GRBL is busy. Wait until the running operation stops."))
            return

        # the Connect button toggles: a click while a port is open closes it
        if self.grbl_ser_port is not None:
            self._grbl_disconnect()
            return

        port_name = self.ui.com_list_combo.currentText()
        if " (" in port_name:
            port_name = port_name.rpartition(" (")[0]

        try:
            baudrate = int(self.ui.baudrates_list_combo.currentText())
        except ValueError:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a valid baudrate."))
            return

        attempt = object()
        with self._grbl_op_lock:
            self._start_seq += 1
            self._grbl_connected = False
            self._grbl_connect_attempt = attempt
        # a new controller session: the WCO and the report units of the old one do not apply
        self._last_wco = None
        self._grbl_report_inches = None
        self._grbl_set_ui_connected(False)
        try:
            port = serial.serial_for_url(port_name, baudrate,
                                                       bytesize=serial.EIGHTBITS,
                                                       parity=serial.PARITY_NONE,
                                                       stopbits=serial.STOPBITS_ONE,
                                                       timeout=0.1,
                                                       write_timeout=1.0,
                                                       xonxoff=False,
                                                       rtscts=False)
            with self._grbl_op_lock:
                if self._grbl_connect_attempt is not attempt:
                    port.close()
                    return
                self.grbl_ser_port = port
                self._grbl_rx_port = port
                self._grbl_rx_buffer = b''
                self._grbl_reply_pending = False

            # Toggle DTR to reset the controller loaded with GRBL (Arduino, ESP32, etc.)
            try:
                port.dtr = False
            except IOError:
                pass

            port.reset_input_buffer()

            try:
                port.dtr = True
            except IOError:
                pass

            # wake up GRBL; a timer reads the answer 1 s later, so the GUI does not stop
            port.write("\r\n\r\n".encode('utf-8'))
        except (serial.SerialException, OSError, ValueError) as err:
            self.app.log.error("ToolLevelling.on_grbl_connect() -> %s" % str(err))
            self._grbl_close_port(attempt=attempt)
            self.app.inform.emit("[ERROR_NOTCL] %s: %s" % (_("Could not connect to port"), port_name))
            return

        QtCore.QTimer.singleShot(1000, lambda: self._grbl_connect_finish(port_name, port, attempt))

    def _grbl_connect_finish(self, port_name, port, attempt):
        """
        Read the GRBL answer to the wake-up lines. Mark the port as connected
        if GRBL answered, else close the port.
        """
        with self._grbl_op_lock:
            if self.grbl_ser_port is not port or self._grbl_connect_attempt is not attempt:
                return
            if port is None or not getattr(port, 'is_open', False):
                return
            safety_generation = self._grbl_safety_generation

        error = None
        try:
            answer = port.readlines()
        except (serial.SerialException, OSError) as err:
            error = err
            answer = []

        connected = False
        with self._grbl_op_lock:
            if self.grbl_ser_port is not port or self._grbl_connect_attempt is not attempt:
                return
            if error is not None:
                self.app.log.error("ToolLevelling._grbl_connect_finish() -> %s" % str(error))
            buffered = self._grbl_rx_buffer if self._grbl_rx_port is port else b''
            # Only complete records are classified. A fragment stays buffered so the
            # transaction reader can finish it, for example the rest of an ALARM line.
            complete, _sep, suffix = (buffered + b''.join(answer)).rpartition(b'\n')
            lines = [text.strip() for text in complete.decode('utf-8', errors='replace').splitlines()]
            alarm = any(text.lower().startswith('alarm:') or parse_grbl_status_state(text) == 'Alarm'
                        for text in lines)
            banner = any(text.lower().startswith('grbl ') for text in lines)
            self._grbl_failure_locked(None, 'handshake', '\n'.join(lines))
            # unclassified old records stay buffered, a classified alarm does not
            self._grbl_rx_buffer = (b'' if alarm else buffered[:buffered.rfind(b'\n') + 1]) + suffix
            self._grbl_rx_port = port
            if banner or any(text.lower() == 'ok' for text in lines):
                self._start_seq += 1
                # Only a startup banner confirms reset; DTR and ok do not.
                if (banner and not alarm and self._grbl_recovery == 'needs_reset'
                        and safety_generation == self._grbl_safety_generation):
                    self._grbl_recovery = 'needs_home'
                    self._grbl_reset_pending = False
                    self._grbl_reply_pending = False
                    self._grbl_rx_buffer = suffix  # drop the classified part, keep the fragment
                self._grbl_connected = True
                self._last_wco = None
                self._grbl_set_ui_connected(True)
                self.app.inform.emit("%s: %s" % (_("Port connected"), port_name))
                if self._grbl_recovery is not None:
                    self.app.inform.emit('[WARNING_NOTCL] %s' % self._grbl_recovery_text())
                connected = True

        if connected:
            # after this slot ended: the read is a new operation, so the port must be free for the caller
            QtCore.QTimer.singleShot(0, self._grbl_read_units_after_connect)
            return

        if self._grbl_close_port(port=port, attempt=attempt):
            self.app.inform.emit("[ERROR_NOTCL] %s: %s" % (_("Could not connect to GRBL on port"), port_name))

    def _grbl_read_report_units(self, op):
        """
        Read $13 (the report units of GRBL) into self._grbl_report_inches: True (inches), False (mm) or
        None (not known). A worker thread, under the operation `op`; no motion.

        :return: the status of the transaction ('ok', 'error', 'timeout', 'cancelled' or 'port_error').
        """
        text, status = self._grbl_transact(op, '$$', timeout=5.0, echo=False)
        value = parse_grbl_setting(text, 13) if status == 'ok' else None
        self._grbl_report_inches = (value == 1.0) if value in (0.0, 1.0) else None
        return status

    def _grbl_read_units_after_connect(self):
        """
        Read $13 after the connect, in a non-motion operation (GUI thread). The connect finish holds no
        operation, so the read is a new one. It is skipped when GRBL can hold lines of an old job: the
        Start reads $13 again.
        """
        if not self._grbl_port_ready() or self._grbl_stream_dirty or self._grbl_reset_pending:
            return
        self._grbl_start_op('units', self._grbl_read_report_units)

    def _grbl_set_ui_connected(self, connected):
        """Show the connection state on the Connect button and on the tabs."""
        color = 'seagreen' if connected else 'red'
        self.ui.com_connect_button.setStyleSheet("QPushButton {background-color: %s;}" % color)
        self.ui.com_connect_button.setText(_("Connected") if connected else _("Disconnected"))
        self.ui.controller_reset_button.setDisabled(not connected)

        for idx in range(self.ui.al_toolbar.count()):
            if self.ui.al_toolbar.tabText(idx) == _("Connect"):
                self.ui.al_toolbar.tabBar.setTabTextColor(idx, QtGui.QColor(color))
            if self.ui.al_toolbar.tabText(idx) in (_("Control"), _("Sender")):
                self.ui.al_toolbar.tabBar.setTabEnabled(idx, connected)

    def _on_grbl_port_closed(self):
        """Slot of grbl_port_closed_sig (GUI thread)."""
        try:
            self._grbl_set_ui_connected(False)
        except (AttributeError, RuntimeError):
            # the UI can be already deleted when the application ends
            pass

    def on_grbl_add_baudrate(self):
        new_bd = str(self.ui.new_baudrate_entry.get_value())
        if int(new_bd) >= 40 and self.ui.baudrates_list_combo.findText(new_bd) == -1:
            self.ui.baudrates_list_combo.addItem(new_bd)
            self.ui.baudrates_list_combo.setCurrentText(new_bd)

    def _restore_baudrate(self, app_defaults):
        """Select the saved baud rate in the combo; a custom rate that is not in the list is added."""
        baudrate = str(self.app.options.get(
            "tools_grbl_baudrate",
            app_defaults.get("tools_grbl_baudrate", AppDefaults.factory_defaults.get("tools_grbl_baudrate"))))
        combo = self.ui.baudrates_list_combo
        if not baudrate.isdigit():
            return
        if combo.findText(baudrate) == -1:
            combo.addItem(baudrate)
        combo.setCurrentText(baudrate)

    def on_baudrate_changed(self, text):
        # keep the selected baud rate, so the next session starts with it
        if text and text.isdigit():
            self.app.options["tools_grbl_baudrate"] = text

    def on_grbl_delete_baudrate_grbl(self):
        current_idx = self.ui.baudrates_list_combo.currentIndex()
        self.ui.baudrates_list_combo.removeItem(current_idx)

    def on_grbl_send_command(self):
        cmd = str(self.ui.grbl_command_entry.get_value() or '').strip()
        if not cmd:
            return

        def task(op):
            return self._grbl_transact(op, cmd, timeout=30.0)[1] == 'ok'

        # a typed command can move the machine, so it needs a machine that is not in recovery
        self._grbl_start_op('command', task, motion=True)

    def on_grbl_report(self):
        def task(op):
            line = self._grbl_query_status(op)
            self.console_line_sig.emit(line if line else _("No answer"))

        self._grbl_start_op('report', task)

    def on_grbl_get_parameter(self, param):
        try:
            number = int(str(param).replace('$', '').strip())
        except ValueError:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not a valid GRBL parameter number."))
            return

        def task(op):
            text, status = self._grbl_transact(op, '$$', timeout=5.0, echo=False)
            value = parse_grbl_setting(text, number) if status == 'ok' else None
            if value is None:
                self.app.inform.emit('[ERROR_NOTCL] %s: $%d' % (_("GRBL did not report the parameter"), number))
                return
            self.console_line_sig.emit("GRBL Parameter: $%d = %s" % (number, str(value)))

        self._grbl_start_op('parameter', task)

    def on_grbl_jog(self, direction=None):
        if direction is None:
            return

        step = self.ui.jog_step_entry.get_value()
        feedrate = self.ui.jog_fr_entry.get_value()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        travelz = float(
            self.app.options.get(
                "tools_grbl_travelz",
                app_defaults.get("tools_grbl_travelz", AppDefaults.factory_defaults.get("tools_grbl_travelz")))
        )
        units_cmd = {'IN': 'G20', 'MM': 'G21'}[self.units]

        axis_words = {
            'xplus': 'X%s' % str(step),
            'xminus': 'X-%s' % str(step),
            'yplus': 'Y%s' % str(step),
            'yminus': 'Y-%s' % str(step),
            'zplus': 'Z%s' % str(step),
            'zminus': 'Z-%s' % str(step),
        }
        if direction == 'origin':
            commands = [
                "$J=G90 %s Z%s F%s" % (units_cmd, str(travelz), str(feedrate)),
                "$J=G90 %s X0.0 Y0.0 F%s" % (units_cmd, str(feedrate)),
            ]
        elif direction in axis_words:
            commands = ["$J=G91 %s %s F%s" % (units_cmd, axis_words[direction], str(feedrate))]
        else:
            return

        def task(op):
            for idx, cmd in enumerate(commands):
                text, status = self._grbl_transact(op, cmd, timeout=10.0, echo=False)
                if status != 'ok':
                    self.app.inform.emit('[ERROR_NOTCL] %s: %s -> %s' % (
                        _("Jog failed"), cmd, grbl_reply_error(text) or status))
                    return False
                if idx < len(commands) - 1 and not self._grbl_wait_idle(op):
                    return False

        self._grbl_start_op('jog', task, motion=True)

    def on_grbl_zero(self, axis):
        axes = {'x': 'X0', 'y': 'Y0', 'z': 'Z0'}.get(axis, 'X0 Y0 Z0')
        # the work offset changes: the next status report that has no WCO must not use the old one
        self._last_wco = None

        def task(op):
            text, status = self._grbl_transact(op, '$G', timeout=5.0, echo=False)
            try:
                if status != 'ok':
                    raise ValueError(status)
                active_wcs = parse_grbl_active_wcs(text)
            except ValueError as err:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (
                    _("Could not read the active work coordinate system"), str(err)))
                return

            # G10 L20 makes the current position 0 in the active work coordinate
            # system (G10 L2 would set the offset to machine 0)
            p_number = int(active_wcs[1:]) - 53
            cmd = 'G10 L20 P%d %s' % (p_number, axes)
            text, status = self._grbl_transact(op, cmd, timeout=5.0, echo=False)
            if status != 'ok':
                self.app.inform.emit('[ERROR_NOTCL] %s: %s -> %s' % (
                    _("Zero failed"), cmd, grbl_reply_error(text) or status))

        # the position is not trusted during recovery
        self._grbl_start_op('zero', task, motion=True)

    def on_grbl_homing(self):
        def task(op):
            with self._grbl_op_lock:
                pending = self._grbl_reset_pending
            if pending and not self._grbl_confirm_reset(op):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("GRBL reset was not confirmed. Press Reset, then Home."))
                return False
            # a home cycle can take a long time; GRBL answers 'ok' at the end
            text, status = self._grbl_transact(op, '$H', timeout=120.0)
            if status == 'ok' and self._grbl_wait_idle(op):
                with self._grbl_op_lock:
                    if not self._grbl_active_locked(op) or op.safety_generation != self._grbl_safety_generation:
                        return False
                    self._grbl_recovery = None
                    self.app.inform.emit('[success] %s' % _("Home cycle finished."))
                return
            if 'alarm' in (text or '').lower() or status in ('timeout', 'port_error'):
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, status, text)
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Home cycle failed"), text or status))

        # A pending-reset home reservation only reads confirmation before permitting $H.
        if self._grbl_start_op('home', task, motion=True, allow_in_recovery=True):
            self.app.inform.emit("%s" % _("GRBL is doing a home cycle."))

    def on_grbl_stop(self):
        """Stop the running operation at once: feed hold, and the machine needs recovery."""
        with self._grbl_op_lock:
            self._start_seq += 1
            self._grbl_safety_generation += 1
            self._grbl_reset_pending = False
            op = self._grbl_op
            if op is not None:
                op.cancel.set()
            written = self._grbl_write_realtime_locked(b'!')
            self._grbl_recovery = 'needs_reset'

        if not written:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))
            return
        self.app.inform.emit('[WARNING_NOTCL] %s %s' % (
            _("Stopped. GRBL is in feed hold."), self._grbl_recovery_text()))

    def on_grbl_reset(self):
        self._last_wco = None
        with self._grbl_op_lock:
            self._start_seq += 1
            self._grbl_safety_generation += 1
            op = self._grbl_op
            if op is not None:
                op.cancel.set()
            # Receive boundary: everything received before the reset byte belongs to the old
            # controller epoch, so an old banner cannot confirm this reset.
            port = self.grbl_ser_port
            self._grbl_rx_buffer = b''
            self._grbl_rx_port = port
            receive_cleared = False
            if port is not None:
                try:
                    port.reset_input_buffer()
                    receive_cleared = True
                except (serial.SerialException, OSError) as err:
                    self.app.log.error("ToolLevelling.on_grbl_reset() -> %s" % str(err))
            written = self._grbl_write_realtime_locked(b'\x18')
            self._grbl_reset_pending = written and receive_cleared
            # The byte request is not proof of reset, even when the machine looked Idle.
            self._grbl_recovery = 'needs_reset'
            if not written:
                self._grbl_write_realtime_locked(b'!')

        if not written:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))
            return
        if not receive_cleared:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                "Could not clear the GRBL receive buffer. Reset was sent, but Home is blocked. Press Reset again."))
            return
        self.app.inform.emit("%s" % _("GRBL software reset was sent."))
        if self._grbl_recovery is not None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % self._grbl_recovery_text())

    def on_grbl_pause_resume(self, checked):
        if self._grbl_op is not None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("An operation runs. Use Stop."))
            return
        if checked is False and self._grbl_recovery is not None:
            # a resume after Stop would continue the held motion
            self.app.inform.emit('[ERROR_NOTCL] %s' % self._grbl_recovery_text())
            return

        with self._grbl_op_lock:
            written = self._grbl_write_realtime_locked(b'~' if checked is False else b'!')
        if not written:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))
            return
        self.app.inform.emit("%s" % (_("GRBL resumed.") if checked is False else _("GRBL paused.")))

    def _al_read_probe_inputs(self):
        """
        Read and check the probing parameters (GUI thread).

        :return: (travel_z, depth, probe_fr), or None (the user was told why).
        """
        try:
            travel_z = float(self.ui.ptravelz_entry.get_value())
            probe_fr = float(self.ui.feedrate_probe_entry.get_value())
            depth = float(self.ui.pdepth_entry.get_value())
        except (TypeError, ValueError):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The probing parameters are not valid numbers."))
            return None
        if not all(math.isfinite(v) for v in (travel_z, probe_fr, depth)):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The probing parameters are not valid numbers."))
            return None
        if depth >= 0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The probe Z depth must be negative."))
            return None
        if probe_fr <= 0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The probe feedrate must be more than zero."))
            return None
        if travel_z <= 0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The probe travel Z must be more than zero."))
            return None
        return travel_z, depth, probe_fr

    def on_grbl_autolevel(self):
        # read every UI value here, in the GUI thread; the worker must not touch widgets
        inputs = self._al_read_probe_inputs()
        if inputs is None:
            return
        travel_z, depth, probe_fr = inputs
        precision = self._al_read_precision_inputs(travel_z, depth, probe_fr)
        if precision is None:
            return
        if not self.al_voronoi_geo_storage:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("There are no probe points. Add probe points first."))
            return

        # reserve first: a refused click must not retire the running probe or a valid map
        op = self._grbl_reserve('probe', motion=True)
        if op is None:
            return
        op.precision_inputs = precision

        context = self._al_capture_context(replacement=True)
        if context is None:
            self._grbl_release(op)
            return

        points = {key: (value['point'].x, value['point'].y) for key, value in self.al_voronoi_geo_storage.items()}
        tol = context.tolerance
        units_cmd = 'G20' if context.units == 'IN' else 'G21'
        probe_timeout = probe_timeout_s(travel_z, depth, probe_fr)


        def worker_task():
            try:
                with self.app.proc_container.new('%s...' % _("Probing")):
                    self._grbl_probe_run(op, context, points, tol, travel_z, depth, probe_fr,
                                         units_cmd, probe_timeout)
            finally:
                self._grbl_release(op)

        self.app.inform.emit('%s' % _("Sending probing GCode to the GRBL controller."))
        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def _al_read_precision_inputs(self, travel_z, depth, probe_fr):
        """Capture optional fine probing parameters before reserving or moving GRBL."""
        if self.ui.precision_probe_cb.get_value() is not True:
            return ()
        try:
            feed = float(self.ui.precision_feed_entry.get_value())
            retract = float(self.ui.precision_retract_entry.get_value())
            valid = all(math.isfinite(v) for v in (feed, retract)) and \
                0.0001 <= feed <= min(probe_fr, 910000.0) and \
                0.0001 <= retract <= travel_z - depth
            # The wire protocol uses four decimal places; never round a limit
            # deeper, a retract above clearance, or a positive feed to zero.
            valid = valid and round(feed, 4) <= probe_fr and round(depth, 4) >= depth and \
                round(travel_z, 4) <= travel_z and round(probe_fr, 4) > 0
        except (TypeError, ValueError):
            valid = False
        if not valid:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                "Precision probing needs a positive fine feed no faster than the coarse feed, "
                "and a positive retract within the depth-to-clearance range. "
                "Use probing limits representable to four decimal places."))
            return None
        return round(feed, 4), round(retract, 4)

    def _restore_al_precision(self, target_obj):
        # Store the calibration's units with the job, not in mutable global options.
        # Legacy jobs start with precision disabled and physical defaults in mm.
        options = target_obj.obj_options
        units = self.app.app_units.upper()
        saved_units = options.get('tools_al_precision_units', 'MM')
        scale = 1.0 if saved_units == units else (25.4 if units == 'MM' else 1.0 / 25.4)
        fields = (
            (self.ui.precision_probe_cb, options.get('tools_al_precision_probe', False) is True),
            (self.ui.precision_feed_entry, options.get('tools_al_precision_feed', 10.0) * scale),
            (self.ui.precision_retract_entry, options.get('tools_al_precision_retract', 0.5) * scale),
        )
        blocked = [(widget, widget.blockSignals(True)) for widget, value in fields]
        try:
            for widget, value in fields:
                widget.set_value(value)
        finally:
            for widget, previous in blocked:
                widget.blockSignals(previous)
        self._update_precision_probe_ui()

    def _update_precision_probe_ui(self):
        enabled = self.ui.precision_probe_cb.get_value() is True
        self.ui.precision_feed_entry.setEnabled(enabled)
        self.ui.precision_retract_entry.setEnabled(enabled)

    def on_precision_probe_changed(self, *args):
        self._update_precision_probe_ui()
        target_obj = self.app.collection.get_by_name(self.ui.object_combo.get_value())
        if self._is_supported_target(target_obj) and getattr(target_obj, 'kind', None) == 'cncjob':
            target_obj.obj_options.update({
                'tools_al_precision_probe': self.ui.precision_probe_cb.get_value() is True,
                'tools_al_precision_feed': self.ui.precision_feed_entry.get_value(),
                'tools_al_precision_retract': self.ui.precision_retract_entry.get_value(),
                'tools_al_precision_units': self.app.app_units.upper(),
            })

    def probing_gcode(self, storage):
        """The sender probes live, so it has no probing G-code file."""
        return ''

    def ui_connect(self):
        self.ui.al_add_button.clicked.connect(self.on_add_al_probepoints)
        self.ui.show_al_table.stateChanged.connect(self.on_show_al_table)

    def ui_disconnect(self):
        try:
            self.ui.al_add_button.clicked.disconnect()
        except (TypeError, AttributeError):
            pass

        try:
            self.ui.show_al_table.stateChanged.disconnect()
        except (TypeError, AttributeError):
            pass

    def reset_fields(self):
        self.al_heights_valid = False
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(3, 0, QtCore.QModelIndex()))

    # ------------------------------------------------------------------
    # LevellingCoreMixin hooks
    # ------------------------------------------------------------------
    def _al_set_buttons_enabled(self, enabled):
        self.ui.grbl_get_heightmap_button.setDisabled(not enabled)
        self.ui.grbl_save_height_map_button.setDisabled(not enabled)

    def _al_result_lock(self):
        return self._grbl_op_lock

    def _al_result_retired(self, result):
        op = result.get('operation')
        return (op is not None and op.cancel.is_set()) or (
                'safety_generation' in result and
                result['safety_generation'] != self._grbl_safety_generation)

    def _al_on_publish_locked(self, result):
        # _on_al_result_ready() holds _grbl_op_lock: the heights and this increment are 1 step
        self._start_seq += 1

    def _invalidate_start_requests(self):
        """Make the pending levelled Start requests old. Never call it with _grbl_op_lock held."""
        with self._grbl_op_lock:
            self._start_seq += 1

    def _start_request_current(self, req):
        """:return: True if nothing changed since the request was made (GUI thread; takes no lock)."""
        return (req.seq == self._start_seq
                and self._al_context_current(req.al_ctx)
                and self._target() is req.target_obj
                and self._grbl_safety_generation == req.safety_generation
                and self._al_map_frame == req.map_frame
                and self._al_map_imported == req.map_imported)

    def _al_on_height_map_ready(self, target_obj, result=None):
        # _on_al_result_ready() calls this hook after it released _grbl_op_lock, so the helper is safe here
        # (the increment under the lock, before the publication, is _al_on_publish_locked)
        self._invalidate_start_requests()
        # the levelled job belongs to the old map; the next Start makes it again
        self.job_map_generation = None
        # bind the map to the GRBL frame of the probe; an imported map has no frame yet
        if result is not None and result.get('kind') == 'probe':
            self._al_map_frame = result.get('frame')
            self._al_map_imported = False
        else:
            self._al_map_frame = None
            self._al_map_imported = True
        self.app.inform.emit('[success] %s' % _("The height map is ready."))
        self._update_3d_height_map()

    @staticmethod
    def _tlo_line(lines):
        """:return: the index of the first line with G43, G43.1 or G49, or None."""
        for index, line in enumerate(lines):
            if any(letter == 'G' and _g_key(value) in ('43.0', '43.1', '49.0') for letter, value in _words(line)):
                return index
        return None

    def _al_arc_segment(self, target_obj):
        """The longest chord of 1 piece of a split arc: a preference of the sender."""
        return float(self.app.options.get("tools_grbl_arc_segment", 0.5))

    # ------------------------------------------------------------------
    # Run control. T16 replaces build_job() with the levelled job and the write callable
    # ------------------------------------------------------------------
    def _target(self):
        return self.app.collection.get_by_name(self.ui.object_combo.get_value())

    def build_job(self):
        """
        Make self.job_lines from the selected CNCJob.

        :return: True if the job has lines, and each line fits in the GRBL receive buffer.
        """
        target = self._target()
        if not self._is_supported_target(target):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a CNCJob object."))
            return False
        text = getattr(target, 'source_file', '') or ''
        if not text.strip():
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The CNCJob has no G-code. Use Update in the CNCJob UI."))
            return False
        numbered = SenderGen.clean_lines_numbered(text)
        lines = [line for _number, line in numbered]
        bad_index = validate_stream_lines(lines)
        if bad_index is not None:
            self.job_lines = []
            self.job_line_numbers = []
            self.app.inform.emit('[ERROR_NOTCL] %s' % (
                _("Line %d of the G-code is longer than GRBL accepts. The job was not made.") %
                numbered[bad_index][0]))
            return False
        self.job_lines = lines
        self.job_line_numbers = [number for number, _line in numbered]
        self.job_target_name = target.obj_options['name']
        self.job_map_generation = None
        return bool(self.job_lines)

    def build_levelled_job(self):
        """
        Make self.job_lines from the selected CNCJob, with the height map applied.
        GUI thread. Steps: clean -> refuse a tool length change -> split long G1
        (only if the job is not segmented) -> level (level_gcode_line also splits
        the arcs; the strict mode refuses the moves that it can not compensate).

        The WCS of the levelling is the one of the bound frame (`_al_map_frame`). A map
        that is not bound yet (an imported map) has none: then the first WCS word of the
        program declares it.

        :return: True if the job has lines.
        """
        if not self.build_job():
            return False
        tlo_index = self._tlo_line(self.job_lines)
        if tlo_index is not None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % (
                _("The program changes the tool length offset (line %d). A levelled job can not do this. "
                  "Remove it, or make a new height map after the change.") % self.job_line_numbers[tlo_index]))
            return False
        target = self._target()
        ctx = self._al_capture_context()
        snapshot = self._al_capture_apply_input(target, units=ctx.units, require_segmented=False)
        if snapshot is None:
            return False
        lines = self.job_lines
        if SenderGen.needs_segmentation(target):
            seg_len = float(self.app.options.get("tools_grbl_seg_len", 1.0))
            lines, count = split_long_moves(lines, seg_len, decimals=target.coords_decimals)
            if count:
                self.app.inform.emit('%s: %d' % (_("Long G1 moves split for the levelling"), count))
        home_wcs = None
        if self._al_map_frame is not None:
            # the frame holds the WCS as GRBL names it ('G54'); the levelling state wants the G number
            home_wcs = float(str(self._al_map_frame[0])[1:])
        proxy = SenderGen.job_proxy(target, lines)
        diagnostics = []
        result = self.autolevell_gcode(proxy, self.ui.al_method_radio.get_value(), snapshot=snapshot,
                                       diagnostics=diagnostics, home_wcs=home_wcs, strict=True)
        if result is None:
            return False
        for warning in diagnostics:
            self.app.inform.emit(warning)
        job_lines = [line for line in result['job'].splitlines() if line.strip()]
        bad_index = validate_stream_lines(job_lines)
        if bad_index is not None:
            self.job_lines = []
            self.job_line_numbers = []
            self.app.inform.emit('[ERROR_NOTCL] %s' % (
                _("Line %d of the levelled G-code is longer than GRBL accepts. The job was not made.") %
                (bad_index + 1)))
            return False
        self.job_lines = job_lines
        # the levelled lines have no 1:1 map to the lines of the G-code text
        self.job_line_numbers = []
        self.job_map_generation = self._al_generation
        return bool(self.job_lines)

    def build_stream_job(self):
        """The job for Start and Save: levelled if 'Level the G-code' is checked."""
        if self.ui.autolevel_cb.get_value() is True:
            return self.build_levelled_job()
        if not self.build_job():
            return False
        if self.app.options.get("tools_grbl_arc_mode", 'split') == 'split':
            target = self._target()
            new_lines, count, source_index, unsplit = SenderGen.split_arcs(
                self.job_lines, target.units, float(self.app.options.get("tools_grbl_arc_segment", 0.5)),
                decimals=target.coords_decimals)
            if unsplit:
                self.app.inform.emit('[ERROR_NOTCL] %s' % (
                    _("This arc can not be split (plane, frame or position not known). Line %d.") %
                    self.job_line_numbers[unsplit[0]]))
                self.job_lines = []
                self.job_line_numbers = []
                return False
            self.job_lines = new_lines
            self.job_line_numbers = [self.job_line_numbers[i] for i in source_index]
            if count:
                self.app.inform.emit('%s: %d' % (_("Arc moves split into line moves"), count))
        return True

    def on_start(self):
        # the WCO of an earlier session or job is not trusted
        self._last_wco = None
        if self.ui.autolevel_cb.get_value() is True:
            # a levelled Start has 2 phases: the live frame is read before the job is made (A8.3)
            self._start_levelled()
            return
        if not self.build_stream_job():
            return
        # The check box is a request for this Start only. Read it 1 time, here, in the GUI thread.
        check_mode = self.ui.check_mode_cb.get_value() is True
        poll_ms = int(self.app.options.get("tools_grbl_status_ms", 200))
        op = self._grbl_reserve('stream', motion=True)
        if op is None:
            return
        self._start_stream_worker(op, list(self.job_lines), list(self.job_line_numbers), check_mode, poll_ms)

    def _start_free_button(self):
        """A levelled Start ended before the stream: the Start button works again (GUI thread)."""
        if self._grbl_op is None:
            self.ui.start_button.setDisabled(False)

    def _confirm_imported_frame(self):
        """
        Ask the user if the machine frame is the one of the imported height map (GUI thread).

        :return: True if the user answered Yes.
        """
        msgbox = FCMessageBox(parent=self.app.ui)
        title = _("Imported height map")
        msgbox.setWindowTitle(title)
        msgbox.setText('<b>%s</b>' % title)
        msgbox.setInformativeText(_(
            "This height map was imported. It has no machine frame. "
            "Is the machine in the same WCS and zero as when the map was made?"))
        msgbox.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        bt_yes = msgbox.addButton(_('Yes'), QtWidgets.QMessageBox.ButtonRole.YesRole)
        bt_no = msgbox.addButton(_('No'), QtWidgets.QMessageBox.ButtonRole.NoRole)
        msgbox.setDefaultButton(bt_no)
        msgbox.exec()
        return msgbox.clickedButton() == bt_yes

    @staticmethod
    def _frames_match(live, bound, tolerance=1e-4):
        """
        :return: True if the 2 frames (active_wcs, offset, report_inches) are the same: the same WCS and
            report units, and each axis of the offset within `tolerance` (machine units).
        """
        if live is None or bound is None:
            return False
        if live[0] != bound[0] or bool(live[2]) != bool(bound[2]) or len(live[1]) != len(bound[1]):
            return False
        return all(abs(a - b) <= tolerance for a, b in zip(live[1], bound[1]))

    def _start_levelled(self):
        """
        Phase 0 of a levelled Start (GUI thread): make the request, ask about an imported map, reserve
        the operation 'frame' and read the live frame in a worker (phase 1). _on_frame_ready() goes on.
        """
        # widget values are read here, before the request
        check_mode = self.ui.check_mode_cb.get_value() is True
        target = self._target()
        if not self._is_supported_target(target):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a CNCJob object."))
            return
        if not self._grbl_port_ready():
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))
            return
        ctx = self._al_capture_context()
        if self._al_capture_apply_input(target, units=ctx.units, require_segmented=False) is None:
            return
        units_cmd = 'G20' if ctx.units == 'IN' else 'G21'

        # each Start adds 1; the sequence number and the safety generation are read in 1 locked section
        with self._grbl_op_lock:
            self._start_seq += 1
            seq = self._start_seq
            safety_generation = self._grbl_safety_generation
        req = _StartRequest(seq, ctx, target, self._al_map_frame, self._al_map_imported,
                            safety_generation, check_mode)

        if req.map_imported:
            if not self._confirm_imported_frame():
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
                return
            if not self._start_request_current(req):
                self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                    "The height map, the object or the machine state changed while the dialog was open. "
                    "Press Start again."))
                return

        op = self._grbl_reserve('frame', motion=False)
        if op is None:
            return

        def worker_task():
            result = {'error': _("The Start failed.")}
            try:
                result = self._grbl_frame_run(op, units_cmd)
            except (serial.SerialException, OSError) as err:
                self.app.log.error("ToolGrblSender._start_levelled() -> %s" % str(err))
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                result = {'error': '%s: %s' % (_("The serial port failed"), str(err))}
            except Exception as err:
                self.app.log.error("ToolGrblSender._start_levelled() -> %s" % str(err))
            finally:
                # the GUI hears about it only after the port is free
                self._grbl_release(op)
                self.frame_ready_sig.emit(req, result)

        self.ui.start_button.setDisabled(True)
        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def _grbl_frame_run(self, op, units_cmd):
        """
        Phase 1 of a levelled Start (a worker thread, operation 'frame', no motion): GRBL must be Idle,
        then read its frame.

        :return: see _grbl_read_live_frame().
        """
        state = parse_grbl_status_state(self._grbl_query_status(op))
        if op.cancel.is_set():
            return {'error': _("The Start was stopped."), 'cancelled': True}
        if state == 'Check':
            return {'error': _("GRBL is in check mode. Send $C in the console, or press Reset.")}
        if state != 'Idle':
            return {'error': '%s: %s.' % (_("GRBL must be Idle to start the job. State"), state or _("no answer"))}
        return self._grbl_read_live_frame(op, units_cmd)

    def _on_frame_ready(self, req, result):
        """
        Slot of frame_ready_sig (GUI thread): phase 1 ended and the port is free. Bind or compare the frame,
        make the levelled job, reserve the operation 'stream' and start phase 2.
        """
        if not self._start_request_current(req):
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                "The Start request is old (the map, the object or the machine state changed). Press Start again."))
            self._start_free_button()
            return
        if 'error' in result:
            self.app.inform.emit('%s %s' % (
                '[WARNING_NOTCL]' if result.get('cancelled') else '[ERROR_NOTCL]', result['error']))
            self._start_free_button()
            return

        frame = result['frame']
        if self._al_map_imported and self._al_map_frame is None:
            # the first Start with this imported map binds it to the live frame
            self._al_map_frame = frame
            req.map_frame = frame
        elif not self._frames_match(frame, self._al_map_frame):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                "The machine frame (WCS or work offset) changed after the height map was made. Probe again."))
            self._start_free_button()
            return

        if not self.build_levelled_job():
            self._start_free_button()
            return
        op = self._grbl_reserve('stream', motion=True)
        if op is None:
            self._start_free_button()
            return
        poll_ms = int(self.app.options.get("tools_grbl_status_ms", 200))
        self._start_stream_worker(op, list(self.job_lines), list(self.job_line_numbers), req.check_mode, poll_ms, req)

    def _start_stream_worker(self, op, lines, numbers, check_mode, poll_ms, req=None):
        """Start the stream worker under the reserved operation `op` (GUI thread). `req`: a levelled Start."""

        def worker_task():
            how = 'error'
            try:
                how = self._grbl_stream_run(op, lines, numbers, check_mode, poll_ms / 1000.0, req)
            except (serial.SerialException, OSError) as err:
                self.app.log.error("ToolGrblSender.on_start() -> %s" % str(err))
                how = self._grbl_stream_crashed(op, 'port_error')
            except Exception as err:
                self.app.log.error("ToolGrblSender.on_start() -> %s" % str(err))
                how = self._grbl_stream_crashed(op, 'error')
            finally:
                # the operation is released after the status map; the GUI hears about it after the release
                self._grbl_release(op)
                self.stream_ended_sig.emit(how)

        self.ui.start_button.setDisabled(True)
        self.ui.progress_bar.setValue(0)
        self.app.inform.emit('%s: %d' % (_("Streaming lines"), len(lines)))
        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def _grbl_stream_crashed(self, op, reason):
        """An exception ended the stream worker: stop the stream. Stop or Reset of the user keep their state."""
        with self._grbl_op_lock:
            if op.cancel.is_set():
                return 'stopped'
            self._grbl_abort_stream_locked(op, reason)
        return reason

    def _grbl_stream_io(self, op, req=None):
        """
        The 2 callables that the pure streamer uses. All port access of the stream goes through them.

        :param req: the _StartRequest of a levelled Start, else None. The write of a levelled Start checks
            the request before the first job line (A8.3 step 4.4): `write.first_job_line_written` is the
            list [bool] of that flag.
        :return: (write, readline)
        """
        first_job_line_written = [False]

        def write(data):
            job_line = data != b'?'
            # the request check, the write and the flag are 1 locked section: an invalidation either gets
            # the lock first (no job line is written) or comes after the first job line (the job runs on)
            with self._grbl_op_lock:
                if op.cancel.is_set():
                    return 'cancelled'
                if not self._grbl_active_locked(op):
                    return 'port_error'
                if req is not None and job_line and not first_job_line_written[0] and req.seq != self._start_seq:
                    return 'stale'
                try:
                    count = op.port.write(data)
                except (serial.SerialException, OSError) as err:
                    self.app.log.error("ToolGrblSender.write() -> %s" % str(err))
                    return 'port_error'
                # a short write is a transport failure, never 'stale'
                if count is not None and count != len(data):
                    return 'port_error'
                if job_line:
                    first_job_line_written[0] = True
                return 'ok'

        write.first_job_line_written = first_job_line_written

        def readline():
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op):
                    return b''
            return op.port.readline()

        return write, readline

    def _grbl_stream_run(self, op, lines, numbers, check_mode, poll_interval, req=None):
        """
        The stream worker under 1 operation (a worker thread; it reads no widgets).

        :param numbers:       the line number in the G-code text of each line of `lines`.
        :param check_mode:    True if the user asked for check mode for this job.
        :param poll_interval: seconds between 2 status requests.
        :param req:           the _StartRequest of a levelled Start (phase 2 of A8.3), else None.
        :return: `how`: 'finished', 'check_passed', 'check_passed_needs_home', 'check_failed',
            'check_exit_failed', 'stopped', 'incomplete', 'rejected' (nothing was sent), 'stale',
            'stale_needs_home' (a stale request: GRBL got no job line), or the name of a failure
            ('port_error', 'timeout', 'error', 'alarm', 'line_too_long').
            It is final: the success values are set only after the commit of A5.3.
        """
        self._stream_result = {}
        port = op.port

        # A8.3 step 4.1: the request must be current when the worker starts
        if req is not None:
            with self._grbl_op_lock:
                stale = op.safety_generation != req.safety_generation or req.seq != self._start_seq
            if stale:
                return self._grbl_stale_cleanup(op, False)

        # 1. GRBL must be Idle
        state = parse_grbl_status_state(self._grbl_query_status(op))
        if state != 'Idle':
            return self._grbl_start_refused(op, state)

        # 2. A5.4 step 2.2: a levelled job compares the live frame ($$, $G, $#) with the bound frame
        #    here. GRBL runs $# only in Idle, so this step comes before $C.
        if req is None:
            # a plain job reads $13 (the report units of the status reports) before $C
            status = self._grbl_read_report_units(op)
            if status == 'cancelled' or op.cancel.is_set():
                return 'stopped'
            if status in ('timeout', 'port_error'):
                with self._grbl_op_lock:
                    self._grbl_abort_stream_locked(op, status)
                return status
        else:
            result = self._grbl_read_live_frame(op, 'G20' if req.al_ctx.units == 'IN' else 'G21')
            if 'error' in result:
                return self._grbl_frame_refused(op, result['error'], result.get('cancelled', False))
            if not self._frames_match(result['frame'], req.map_frame):
                return self._grbl_frame_refused(op, _(
                    "The machine frame (WCS or work offset) changed after the height map was made. Probe again."))

        # The stream epoch is dirty from the first write: until a confirmed completion or the reset
        # banner, GRBL can hold lines (and their ok replies) of this job.
        with self._grbl_op_lock:
            if not self._grbl_active_locked(op):
                return 'stopped' if op.cancel.is_set() else 'incomplete'
            # A8.3 step 4.3: after the last preflight query and before $C
            stale = req is not None and req.seq != self._start_seq
            if not stale:
                self._grbl_stream_dirty = True
        if stale:
            return self._grbl_stale_cleanup(op, False)

        # 3. check mode for this job
        if check_mode:
            how = self._grbl_enter_check_mode(op)
            if how is not None:
                return how

        # old data in the receive buffer is not a reply to the job
        with self._grbl_op_lock:
            text, status = self._grbl_prepare_locked(op, port)
            if status is not None:
                if status == 'cancelled' or op.cancel.is_set():
                    return 'stopped'
                self._grbl_abort_stream_locked(op, status, text)
                return status

        # 4. stream
        write, readline = self._grbl_stream_io(op, req)
        res = stream_lines(
            lines, write, readline, check_mode=check_mode,
            on_progress=lambda d, t: self.stream_progress_sig.emit(d, t),
            on_line=self.console_line_sig.emit,
            poll_status=True, poll_interval=poll_interval,
            on_status=lambda line: self.status_report_sig.emit(parse_grbl_status_report(line)))
        status = res['status']

        def source_number(index):
            return numbers[index] if 0 <= index < len(numbers) else index + 1

        failed_index = res['errors'][-1][0] if res['errors'] else res['done']
        self._stream_result = {
            'done': res['done'],
            'last_text': res['last_text'],
            'line': source_number(res.get('line_index', failed_index)),
            'errors': [source_number(index) for index, _text in res['errors']],
        }

        # the status map of A5.2 step 6
        if status == 'finished':
            return self._grbl_stream_finish(op, res, check_mode)
        if status == 'cancelled':
            return 'stopped'
        if status == 'stale':
            # the levelled Start request is old; GRBL got no job line (A8.3 step 4.5)
            return self._grbl_stale_cleanup(op, check_mode)
        with self._grbl_op_lock:
            if op.cancel.is_set():
                # Stop or Reset already owns the recovery state
                return 'stopped'
            self._grbl_abort_stream_locked(op, status, res['last_text'])
        return status

    def _grbl_frame_refused(self, op, text, cancelled=False):
        """
        The live frame can not start the levelled job. Nothing was written to GRBL, and the stream epoch is
        clean. The user is told why; a failure that the read latched shows its recovery text.

        :return: `how`.
        """
        if cancelled or op.cancel.is_set():
            return 'stopped'
        with self._grbl_op_lock:
            latched = self._grbl_recovery is not None
        if latched:
            text += ' ' + self._grbl_recovery_text()
        self.app.inform.emit('[ERROR_NOTCL] %s' % text)
        return 'rejected'

    def _grbl_stale_cleanup(self, op, check_entered):
        """
        The levelled Start request is old and GRBL got no job line (A8.3). This is not a cancellation and not
        a failure: no recovery state changes here. A `$C` that was sent still needs a confirmed outcome.

        The stream epoch is clean again only through _grbl_commit_success_locked(), after the cleanup, and
        not after a failed exit from check mode.

        :param check_entered: True if the job is in check mode (GRBL is in `Check`).
        :return: `how`: 'stale', 'stale_needs_home', 'check_exit_failed', 'stopped' or 'incomplete'.
        """
        exit_state = None
        if check_entered:
            with self._grbl_op_lock:
                if op.cancel.is_set():
                    return 'stopped'
                if op.failed:
                    return 'incomplete'
            exit_state = self._grbl_exit_check_mode(op)
            if exit_state == 'failed':
                with self._grbl_op_lock:
                    return 'stopped' if op.cancel.is_set() else 'check_exit_failed'
        with self._grbl_op_lock:
            if not self._grbl_commit_success_locked(op):
                # a Stop or a Reset during the cleanup keeps its recovery state
                return 'stopped'
        return 'stale_needs_home' if exit_state == 'alarm' else 'stale'

    def _grbl_start_refused(self, op, state):
        """GRBL is not Idle at the start of the stream worker. Nothing was written to GRBL."""
        if op.cancel.is_set():
            return 'stopped'
        if state is None:
            # the status query failed; it latched the failure where it applies
            with self._grbl_op_lock:
                self._grbl_abort_stream_locked(op, 'timeout')
            return 'timeout'
        if state == 'Check':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                "GRBL is in check mode. Send $C in the console, or press Reset."))
            return 'rejected'
        text = '%s: %s.' % (_("GRBL must be Idle to start the job. State"), state)
        with self._grbl_op_lock:
            latched = self._grbl_recovery is not None
        if latched:
            text += ' ' + self._grbl_recovery_text()
        self.app.inform.emit('[ERROR_NOTCL] %s' % text)
        return 'rejected'

    def _grbl_enter_check_mode(self, op):
        """
        Send $C for this job. GRBL must answer [MSG:Enabled] and then report the state Check.

        :return: None if GRBL is in check mode, else the `how` that ends the job (the abort is done).
        """
        text, status = self._grbl_transact(op, '$C', timeout=5.0)
        if status == 'cancelled':
            return 'stopped'
        if status == 'ok' and '[msg:enabled]' in (text or '').lower():
            state = parse_grbl_status_state(self._grbl_query_status(op))
            if state == 'Check':
                return None
            how = 'check_exit_failed'       # GRBL said Enabled: it can be in check mode
        elif status == 'ok' or status == 'error':
            how = 'error'                   # GRBL refused $C, or answered something else
        else:
            how = 'check_exit_failed'       # no answer: GRBL can be in check mode
        with self._grbl_op_lock:
            if op.cancel.is_set():
                return 'stopped'
            self._grbl_abort_stream_locked(op, status if status in ('timeout', 'port_error') else 'error', text)
        return how

    def _grbl_stream_finish(self, op, res, check_mode):
        """
        The streamer acknowledged all lines. That does not mean that the job is done: wait for Idle
        (normal mode) or leave the check mode (A5.5). `how` is final only here.
        """
        if check_mode:
            # only a complete validation leaves the check mode by $C
            with self._grbl_op_lock:
                if op.cancel.is_set():
                    return 'stopped'
                if op.failed:
                    return 'incomplete'
            exit_state = self._grbl_exit_check_mode(op)
            with self._grbl_op_lock:
                if exit_state == 'failed':
                    return 'check_exit_failed'
                if not self._grbl_commit_success_locked(op):
                    return 'stopped'
                if res['errors']:
                    return 'check_failed'
                return 'check_passed' if exit_state == 'idle' else 'check_passed_needs_home'

        idle = self._grbl_wait_idle(op)
        with self._grbl_op_lock:
            if idle:
                return 'finished' if self._grbl_commit_success_locked(op) else 'stopped'
            if op.cancel.is_set():
                return 'stopped'
            self._grbl_abort_stream_locked(op, 'timeout')
        return 'incomplete'

    def on_stream_stop(self):
        """Stop: feed hold now; the stream worker stops writing. Then GRBL needs Reset and Home."""
        self.on_grbl_stop()

    def on_unlock(self):
        def task(op):
            text, status = self._grbl_transact(op, '$X', timeout=5.0)
            if status != 'ok':
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Unlock failed"), text or status))
        self._grbl_start_op('unlock', task)

    def on_save_levelled_gcode(self):
        # always make the job again: the lines of an earlier Start can be old
        if not self.build_stream_job():
            return
        _filter_ = "G-Code Files (*.nc *.gcode *.cnc *.tap);;All Files (*.*)"
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Save levelled G-code"),
                directory=self.app.get_last_save_folder() + '/' + str(self.job_target_name) + '_levelled',
                ext_filter=_filter_)
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(caption=_("Save levelled G-code"), ext_filter=_filter_)
        if not filename:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Export cancelled ..."))
            return
        try:
            with open(filename, 'w') as f:
                f.write('\n'.join(self.job_lines) + '\n')
        except (FileNotFoundError, PermissionError) as err:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not save the file"), str(err)))
            return
        self.app.inform.emit('[success] %s: %s' % (_("Saved"), filename))

    def _grbl_realtime(self, data):
        with self._grbl_op_lock:
            written = self._grbl_write_realtime_locked(data)
        if not written:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))

    def _on_stream_progress(self, done, total):
        self.ui.progress_bar.setValue(int(done * 100 / total) if total else 0)
        if self.view3d is not None:
            # `done` counts stream lines; the segments of the toolpath carry the index of their stream line
            self.view3d.set_accepted(done - 1)

    def _report_scale(self):
        """
        :return: the factor that changes a position of a status report (the units of GRBL $13) into the
            units of the job, or None if $13 or the job units are not known.
        """
        inches = getattr(self, '_grbl_report_inches', None)
        if inches is None:
            return None
        try:
            units = getattr(self._target(), 'units', None)
        except Exception:
            units = None
        if str(units).upper() not in ('MM', 'IN'):
            units = getattr(self, 'units', None)
        if str(units).upper() not in ('MM', 'IN'):
            return None
        return grbl_report_scale(units, inches)

    def _on_status_report(self, report):
        if report is None:
            return
        if 'wco' in report:
            self._last_wco = report['wco']
        pos = work_position(report, getattr(self, '_last_wco', None))
        text = report['state']
        if pos is not None:
            scale = self._report_scale()
            if scale is None:
                # a position in the wrong units is worse than none
                pos = None
                text += '   %s' % _("position unknown (GRBL $13 not read)")
            else:
                pos = tuple(value * scale for value in pos)
                text += '   X %.3f  Y %.3f  Z %.3f' % pos
        self.ui.status_label.setText(text)
        if 'ov' in report:
            self.ui.ov_values_label.setText('F: %d%%  R: %d%%  S: %d%%' % report['ov'])
        if self.view3d is not None and pos is not None:
            self.view3d.set_tool_position(pos)

    def on_show_3d(self):
        canvas = getattr(self.app, 'plotcanvas3d', None)
        if canvas is None:
            open_3d_tab = getattr(self.app, 'on_3d_area', None)
            if callable(open_3d_tab):
                open_3d_tab()
            canvas = getattr(self.app, 'plotcanvas3d', None)
        if canvas is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The Plot 3D tab is not available."))
            return
        if self.view3d is None or self.view3d.canvas is not canvas:
            self.view3d = SenderView3d(canvas)
        # always make the job again: the lines of an earlier Start or Save can be old
        if not self.build_stream_job():
            self.view3d.set_toolpath([])
            return
        lines, stream_index, chord_lines = self._display_lines()
        segments = parse_toolpath(lines)
        if stream_index is not None:
            segments = [(stream_index[i], a, b, rapid) for i, a, b, rapid in segments]
        self.view3d.set_toolpath(segments, chord_lines)
        self._update_3d_height_map()
        canvas.fit_view()

    def _display_lines(self):
        """
        The lines for the 3D display. In the mode "send" for arcs, the stream holds the arcs: a copy is split
        for the display only, and each display line maps to its stream line.

        :return: (lines, stream_index, chord_lines). stream_index[i] is the stream line index of lines[i]
            (None: lines[i] is the stream line i). chord_lines: the stream line indexes of the arcs that
            could not be split: the display draws their chords in grey.
        """
        if self.ui.autolevel_cb.get_value() is True or self.app.options.get("tools_grbl_arc_mode", 'split') == 'split':
            return self.job_lines, None, ()
        target = self._target()
        lines, _count, source_index, unsplit = SenderGen.split_arcs(
            list(self.job_lines), target.units, float(self.app.options.get("tools_grbl_arc_segment", 0.5)),
            decimals=target.coords_decimals)
        return lines, source_index, unsplit

    def _update_3d_height_map(self):
        if self.view3d is None:
            return
        if not self.al_heights_valid:
            self.view3d.set_height_map(None)
            return
        points = [(v['point'].x, v['point'].y, v['height']) for v in self.al_voronoi_geo_storage.values()]
        self.view3d.set_height_map(build_bilinear_grid(points, self._al_grid_tolerance()))

    def _on_stream_ended(self, how):
        """
        Slot of stream_ended_sig (GUI thread). Only 'finished' and 'check_passed' are a success.

        :param how: see _grbl_stream_run().
        """
        self.ui.start_button.setDisabled(False)
        result = self._stream_result or {}
        errors = result.get('errors', [])
        recovery = (' ' + self._grbl_recovery_text()) if self._grbl_recovery is not None else ''

        if how == 'finished':
            self.ui.progress_bar.setValue(100)
            self.app.inform.emit('[success] %s' % _("The job finished."))
        elif how == 'check_passed':
            self.ui.progress_bar.setValue(100)
            self.app.inform.emit('[success] %s' % _("Check mode: GRBL found no error."))
        elif how == 'check_passed_needs_home':
            self.ui.progress_bar.setValue(100)
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                "Check mode: GRBL found no error. GRBL is in alarm after the reset. Press Home."))
        elif how == 'check_failed':
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (
                _("Check mode: GRBL found errors on the lines"), ', '.join(str(n) for n in errors[:20])))
        elif how == 'check_exit_failed':
            text = _("Could not leave check mode.") + recovery
            if errors:
                text += ' %s: %s' % (_("Errors on the lines"), ', '.join(str(n) for n in errors[:20]))
            self.app.inform.emit('[ERROR_NOTCL] %s' % text)
        elif how == 'rejected':
            # the worker told why; nothing was sent
            pass
        elif how == 'stale':
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                "The Start request is old (the map, the object or the machine state changed). Press Start again."))
        elif how == 'stale_needs_home':
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                "The Start request is old. GRBL is in alarm after it left check mode. "
                "Press Home, then Start again."))
        elif how == 'stopped':
            self.app.inform.emit('[WARNING_NOTCL] %s%s' % (_("The job was stopped."), recovery))
        elif how in ('error', 'alarm'):
            self.app.inform.emit('[ERROR_NOTCL] %s %d: %s.%s' % (
                _("GRBL stopped the job at line"), result.get('line', 0), result.get('last_text', ''), recovery))
        else:
            self.app.inform.emit('[ERROR_NOTCL] %s%s' % (_("The job did not finish."), recovery))

    def _console(self):
        """:return: the GrblConsole in the dock (made at the first call)."""
        dock = self.app.ui.grbl_console_dock
        if not isinstance(dock.widget(), GrblConsole):
            dock.setWidget(GrblConsole(self))
        return dock.widget()

    def on_console_toggled(self, checked):
        self.app.options["tools_grbl_console_visible"] = bool(checked)
        if checked:
            self._console()
            self.app.ui.grbl_console_dock.show()
        else:
            self.app.ui.grbl_console_dock.hide()

    def show_console_if_wanted(self):
        if self.app.options.get("tools_grbl_console_visible", False):
            self._console()
            self.app.ui.grbl_console_dock.show()

    def hide_console(self):
        self.app.ui.grbl_console_dock.hide()

    def send_console_command(self, text):
        self.ui.grbl_command_entry.set_value(text)
        self.on_grbl_send_command()

    def on_plugin_cleanup(self):
        """The Plugin tab closes: hide the console. The option keeps its value."""
        self.hide_console()

    def hideEvent(self, event):
        # another plugin took the Plugin tab, or the tab closed
        self.hide_console()
        super().hideEvent(event)
