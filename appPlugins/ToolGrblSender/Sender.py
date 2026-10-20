# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################

import logging
import math
import random
import time
from pathlib import Path

from PyQt6 import QtWidgets, QtCore, QtGui, sip

import serial
import serial.tools.list_ports

from appTool import AppTool
from appCommon import MachineSafety
from defaults import AppDefaults
from appGUI.GUIElements import (
    VerticalScrollArea, FCFileSaveDialog, FCMessageBox, FCTextAreaLineNumber, RadioSet, FCSpinner)
from camlib import CNCjob, flatten_shapely_geometry

from appPlugins.Common.levelling_core import LevellingCoreMixin
from appPlugins.Common.grbl.grbl_protocol import (
    parse_grbl_status_state, parse_grbl_setting, parse_grbl_active_wcs, grbl_reply_error, probe_timeout_s,
    parse_grbl_status_report, work_position, grbl_report_scale)
from appPlugins.Common.gcode_segment import split_long_moves, parse_toolpath, _words, _g_key
from appPlugins.Common.levelling_interp import build_bilinear_grid
from appPlugins.ToolGrblSender import SenderGen
from appPlugins.Common.grbl.grbl_client import (
    GrblClientMixin, STATUS_POLL, is_controller_banner, stream_lines, validate_stream_lines)
from appPlugins.ToolGrblSender.SenderUI import GrblSenderUI
from appPlugins.ToolGrblSender.SenderSimulation import SimulationDialog, VirtualGrbl
from appPlugins.ToolGrblSender.SenderView3d import SenderView3d, TOOL_COLOR

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


def _qt_deleted(obj):
    """:return: True if obj is a Qt object that Qt has deleted (False for None and for other objects)."""
    if obj is None:
        return False
    try:
        return sip.isdeleted(obj)
    except TypeError:  # not a Qt object
        return False


class GrblConsole(QtWidgets.QWidget):
    """The prepared program, GRBL acknowledgements, and the command console."""

    program_line_selected = QtCore.pyqtSignal(object)

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self._selected_lines = set()
        self._selection_anchor = None
        self._progress_selections = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)
        program_tab = QtWidgets.QWidget()
        program_lay = QtWidgets.QVBoxLayout(program_tab)
        program_lay.setContentsMargins(0, 0, 0, 0)
        program_header = QtWidgets.QHBoxLayout()
        self.program_status = QtWidgets.QLabel()
        self.program_status.setToolTip(_(
            "GRBL acknowledged this line. Buffered moves may still be executing."))
        self.follow_cb = QtWidgets.QCheckBox(_("Follow"))
        self.follow_cb.setChecked(True)
        program_header.addWidget(self.program_status, 1)
        program_header.addWidget(self.follow_cb)
        program_lay.addLayout(program_header)
        self.program_area = FCTextAreaLineNumber(theme=tool.app.options.get('global_theme', 'default'))
        self.program_view = self.program_area.edit
        self.program_view.setReadOnly(True)
        self.program_view.setUndoRedoEnabled(False)
        self.program_view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.program_view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        # Browsing must not replace the stream's line highlight with the text cursor's highlight.
        self.program_view.cursorPositionChanged.disconnect(self.program_view.highlight)
        QtWidgets.QApplication.instance().installEventFilter(self)
        program_lay.addWidget(self.program_area)
        self.tabs.addTab(program_tab, _("Program"))

        console_tab = QtWidgets.QWidget()
        console_lay = QtWidgets.QVBoxLayout(console_tab)
        console_lay.setContentsMargins(0, 0, 0, 0)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        console_lay.addWidget(self.log_view)
        h_lay = QtWidgets.QHBoxLayout()
        self.cmd_entry = QtWidgets.QLineEdit()
        self.cmd_entry.setPlaceholderText(_("Type GRBL command ..."))
        self.send_btn = QtWidgets.QToolButton()
        self.send_btn.setText(_("Send"))
        h_lay.addWidget(self.cmd_entry)
        h_lay.addWidget(self.send_btn)
        console_lay.addLayout(h_lay)
        self.tabs.addTab(console_tab, _("Console"))
        self.cmd_entry.returnPressed.connect(self.on_send)
        self.send_btn.clicked.connect(self.on_send)
        self.follow_cb.toggled.connect(self._follow_program)
        self.program_line_selected.connect(lambda index: self.tool.on_program_line_selected(index))
        self.set_program([])

    def eventFilter(self, obj, event):
        view = self.__dict__.get('program_view')
        if view is None:
            return False
        if event.type() == QtCore.QEvent.Type.MouseButtonPress and self.isVisible() \
                and isinstance(obj, QtWidgets.QWidget) \
                and obj is not self.program_area and not self.program_area.isAncestorOf(obj):
            self.clear_program_selection()
        elif event.type() == QtCore.QEvent.Type.MouseButtonRelease and self.isVisible() \
                and isinstance(obj, QtWidgets.QWidget) \
                and obj is not self.program_area and not self.program_area.isAncestorOf(obj):
            # Controls such as Follow can select the progress line in their click handler.
            QtCore.QTimer.singleShot(0, self.clear_program_selection)
        elif event.type() == QtCore.QEvent.Type.Hide and obj is self:
            self.clear_program_selection()
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease \
                and event.button() == QtCore.Qt.MouseButton.LeftButton and obj is view.viewport():
            QtWidgets.QPlainTextEdit.mouseReleaseEvent(self.program_view, event)
            cursor = view.cursorForPosition(event.position().toPoint())
            index = cursor.blockNumber()
            if index >= self._program_count:
                return True
            modifiers = event.modifiers()
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier and self._selection_anchor is not None:
                first, last = sorted((self._selection_anchor, index))
                self._selected_lines = set(range(first, last + 1))
            elif modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
                self._selected_lines.symmetric_difference_update({index})
                self._selection_anchor = index
            else:
                self._selected_lines = {index}
                self._selection_anchor = index
            if index in self._selected_lines:
                cursor.select(QtGui.QTextCursor.SelectionType.LineUnderCursor)
            self.program_view.setTextCursor(cursor)
            self._highlight_program_selection()
            self.program_line_selected.emit(
                next(iter(self._selected_lines)) if len(self._selected_lines) == 1 else set(self._selected_lines))
            return True
        # Use Qt's read-only handlers instead of the editor's insertion/comment shortcuts.
        if obj is view:
            if event.type() == QtCore.QEvent.Type.KeyPress:
                QtWidgets.QPlainTextEdit.keyPressEvent(obj, event)
                return True
            if event.type() == QtCore.QEvent.Type.ContextMenu:
                QtWidgets.QPlainTextEdit.contextMenuEvent(obj, event)
                return True
        return super().eventFilter(obj, event)

    def clear_program_selection(self):
        self._selected_lines.clear()
        self._selection_anchor = None
        cursor = self.program_view.textCursor()
        cursor.clearSelection()
        self.program_view.setTextCursor(cursor)
        self._highlight_program_selection()
        if self.tool.view3d is not None:
            self.tool.view3d.set_selected_line(None)

    def _highlight_program_selection(self):
        selections = []
        for index in sorted(self._selected_lines):
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.cursor = QtGui.QTextCursor(self.program_view.document().findBlockByNumber(index))
            selection.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
            selection.format.setBackground(self.program_view.palette().highlight())
            selection.format.setForeground(self.program_view.palette().highlightedText())
            selections.append(selection)
        self.program_view.setExtraSelections(selections + self._progress_selections)

    def set_program(self, lines):
        self.clear_program_selection()
        self._program_count = len(lines)
        self.program_view.setPlainText('\n'.join(lines))
        self.update_progress(0)
        self.tabs.setCurrentIndex(0)

    def update_progress(self, done, errors=()):
        self._acknowledged = max(0, min(done, self._program_count))
        self._program_errors = sorted(set(i for i in errors if 0 <= i < self._program_count))
        text = '%s: %d / %d' % (_("Acknowledged line"), self._acknowledged, self._program_count)
        if self._program_errors:
            text += ' | %s: %s' % (_("Errors on the lines"),
                                   ', '.join(str(i + 1) for i in self._program_errors[:20]))
        self.program_status.setText(text)

        selections = []
        acknowledged = self._acknowledged - 1
        indexes = [acknowledged] if acknowledged >= 0 and acknowledged not in self._program_errors else []
        for index in indexes + self._program_errors:
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.cursor = QtGui.QTextCursor(self.program_view.document().findBlockByNumber(index))
            selection.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
            if index in self._program_errors:
                selection.format.setBackground(QtGui.QColor('#c62828'))
                selection.format.setForeground(QtGui.QColor('white'))
            else:
                selection.format.setBackground(self.program_view.palette().highlight())
                selection.format.setForeground(self.program_view.palette().highlightedText())
            selections.append(selection)
        self._progress_selections = selections
        self._highlight_program_selection()
        self._program_line = self._program_errors[-1] if self._program_errors else acknowledged
        if self.tool.__dict__.get('_program_paused') is not True:
            self._follow_program(self.follow_cb.isChecked())

    def _follow_program(self, checked):
        self._selected_lines.clear()
        self._selection_anchor = None
        self._highlight_program_selection()
        if self._program_line >= 0:
            scrollbars = (self.program_view.horizontalScrollBar(), self.program_view.verticalScrollBar())
            positions = [bar.value() for bar in scrollbars]
            cursor = QtGui.QTextCursor(self.program_view.document().findBlockByNumber(self._program_line))
            cursor.select(QtGui.QTextCursor.SelectionType.LineUnderCursor)
            self.program_view.setTextCursor(cursor)
            if checked:
                self.program_view.ensureCursorVisible()
            else:
                for bar, position in zip(scrollbars, positions):
                    bar.setValue(position)

    def on_send(self):
        text = self.cmd_entry.text().strip()
        if not text:
            return
        self.cmd_entry.clear()
        self.tool.send_console_command(text)

    def append(self, text):
        self.log_view.appendPlainText(text)


class GrblStartDialog(QtWidgets.QDialog):
    """Choose a 1-based line in the prepared console program."""

    def __init__(self, line_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Start job"))
        layout = QtWidgets.QVBoxLayout(self)
        self.start_radio = RadioSet([
            {'label': _("Beginning"), 'value': 'beginning'},
            {'label': _("Line"), 'value': 'line'}])
        self.start_radio.setToolTip(_(
            "Select from where the job starts:\n"
            "- Beginning: start from the first line\n"
            "- Line: start from a custom line"))
        layout.addWidget(self.start_radio)
        self.line_entry = FCSpinner()
        self.line_entry.set_range(1, line_count)
        self.line_entry.set_value(1)
        self.line_entry.setToolTip(_("Line number in the GCode program console."))
        layout.addWidget(self.line_entry)
        self.start_radio.activated_custom.connect(
            lambda value: self.line_entry.setVisible(value == 'line'))
        self.start_radio.set_value('beginning')
        self.line_entry.hide()
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


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
        self.start_line = None


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
    # the spindle runs (True) or stopped (False): an accepted M3/M4/M5 line, from a worker
    spindle_state_sig = QtCore.pyqtSignal(bool)
    # how the stream worker ended: 'finished', 'stopped', 'check_passed', ... (see _on_stream_ended)
    stream_ended_sig = QtCore.pyqtSignal(str)
    # a text line for the console, from any thread
    console_line_sig = QtCore.pyqtSignal(str)
    preview_ready_sig = QtCore.pyqtSignal(object)
    probe_finished_sig = QtCore.pyqtSignal(object, object)
    simulation_event_sig = QtCore.pyqtSignal(object, str, object)
    ecut_tool_change_sig = QtCore.pyqtSignal(object, int, object)
    ecut_motion_result_sig = QtCore.pyqtSignal(object)
    ecut_connect_result_sig = QtCore.pyqtSignal(object)

    @property
    def view3d(self):
        """The 3D view, or None. A closed Plot 3D tab deletes the canvas: then the view is gone too."""
        view = self.__dict__.get('_view3d')
        if view is not None and _qt_deleted(getattr(view.canvas, 'native', None)):
            self.__dict__['_view3d'] = None
            return None
        return view

    @view3d.setter
    def view3d(self, view):
        self.__dict__['_view3d'] = view

    @staticmethod
    def _on_plugin_destroyed(stop):
        try:
            stop()
        except Exception:
            log.exception('ToolGrblSender._on_plugin_destroyed() -> the controller did not stop')
        MachineSafety.unregister(stop)

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
        self._preview_generation = 0
        self._probe_start_op = None
        self._plugin_active = False
        self._last_wco = None
        # what the stream worker tells the GUI thread with stream_ended_sig: {'done', 'last_text', 'errors'}
        self._stream_result = {}
        self._simulation = None
        self._controller_state = 'Idle'

        self.ui = GrblSenderUI(layout=self.layout, app=self.app)
        self.ui.spindle_button.setChecked(self.__dict__.get('_spindle_on', False))
        self.pluginName = self.ui.pluginName
        self._continuous_jog = None
        self._continuous_jog_click_button = None
        self._continuous_jog_timer = QtCore.QTimer(self)
        self._continuous_jog_timer.setInterval(50)
        self._continuous_jog_timer.timeout.connect(self._refresh_continuous_jog)
        self._ecut_motion_dialog = None
        self._ecut_motion_port = None
        self._ecut_motion_revision = None
        self._ecut_motion_loading = False
        self._ecut_motion_io_timer = QtCore.QTimer(self)
        self._ecut_motion_io_timer.setInterval(100)
        self._ecut_motion_io_timer.timeout.connect(self._refresh_ecut_motion_io)

        self._al_core_signals_connected = False
        self.connect_signals_at_init()
        self.simulation_event_sig.connect(self._on_simulation_event)
        self._sim_ui_timer = QtCore.QTimer(self)
        self._sim_ui_timer.setInterval(100)
        self._sim_ui_timer.timeout.connect(self._update_sim_button)
        self._sim_ui_timer.start()
        # an idle controller: its status keeps the Spindle button and the position up to date
        self._status_poll_timer = QtCore.QTimer(self)
        self._status_poll_timer.setInterval(1000)
        self._status_poll_timer.timeout.connect(self._poll_idle_status)
        self._status_poll_timer.start()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='', **kwargs)

    def run(self, toggle=True):
        if self.app.plugin_tab_locked is True:
            return
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
                        self.app.ui.notebook.removeTab(found_idx)
                        self.on_plugin_cleanup()

                        # if there are no objects loaded in the app then hide the Notebook widget
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
                        return
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        self._plugin_active = True
        super().run()
        self.set_tool_ui()

        self.app.ui.notebook.setTabText(2, self.pluginName)

        self._reload_console_program(self._target())
        self.show_console_if_wanted()
        self._schedule_3d_preview()

    def connect_signals_at_init(self):
        # the signals of the tool and of the app live as long as the tool;
        # set_tool_ui() calls this method again for each new LevelUI, so
        # connect them only 1 time
        if not getattr(self, '_al_core_signals_connected', False):
            self._al_core_signals_connected = True
            self.grbl_port_closed_sig.connect(self._on_grbl_port_closed)
            self.ecut_tool_change_sig.connect(self._on_ecut_tool_change)
            self.ecut_motion_result_sig.connect(self._on_ecut_motion_result)
            self.ecut_connect_result_sig.connect(self._on_ecut_connect_result)
            self.al_result_ready_sig.connect(self._on_al_result_ready)
            self.build_al_table_sig.connect(self.build_al_table)
            self.show_probing_geo_sig.connect(self._on_show_probing_geo_sig)
            self.stream_progress_sig.connect(self._on_stream_progress)
            self.status_report_sig.connect(self._on_status_report)
            self.spindle_state_sig.connect(self._on_spindle_state)
            self.stream_ended_sig.connect(self._on_stream_ended)
            self.frame_ready_sig.connect(self._on_frame_ready)
            self.console_line_sig.connect(lambda line: self._console().append(line))
            self.preview_ready_sig.connect(self._on_preview_ready)
            self.probe_finished_sig.connect(self._on_probe_finished)
            self.app.collection.rowsInserted.connect(self._select_available_excellon)
            self.app.collection.rowsRemoved.connect(self._select_available_excellon)
            self.app.collection.modelReset.connect(self._select_available_excellon)
            # When object selection on canvas change
            self.app.proj_selection_changed.connect(self.on_object_selection_changed)
            # Cleanup on Graceful exit (CTRL+ALT+X combo key)
            self.app.cleanup.connect(self.on_reset_tool)
            self.app.cleanup.connect(self._grbl_disconnect)
            # the application closes or crashes: stop the motion, the spindle and the outputs, then close the port
            MachineSafety.register(self._grbl_shutdown)
            # a new project deletes the plugins: the deleted plugin stops its controller and leaves the registry
            try:
                self.destroyed.connect(lambda *_args, stop=self._grbl_shutdown: self._on_plugin_destroyed(stop))
            except RuntimeError:
                pass  # the Qt part is not initialized (a test double)
            qt_app = QtWidgets.QApplication.instance()
            if qt_app is not None:
                MachineSafety.connect_quit(qt_app)
                qt_app.aboutToQuit.connect(lambda: self._simulation.close() if self._simulation else None)
        self.ui.level.toggled.connect(self.on_level_changed)
        self._select_available_excellon()

        self.ui.avoid_exc_holes_cb.toggled.connect(self.on_avoid_exc_holes)
        self.ui.avoid_exc_combo.currentIndexChanged.connect(self._update_3d_excellon)

        self.ui.al_mode_radio.activated_custom.connect(self.on_mode_radio)
        self.ui.al_method_radio.activated_custom.connect(self.on_method_radio)
        self.ui.precision_probe_cb.toggled.connect(self.on_precision_probe_changed)
        self.ui.precision_feed_entry.valueChanged.connect(self.on_precision_probe_changed)
        self.ui.precision_retract_entry.valueChanged.connect(self.on_precision_probe_changed)
        self.ui.plot_probing_pts_cb.toggled.connect(self.show_probing_geo)
        self.ui.plot_height_map_cb.toggled.connect(self._update_3d_height_map)
        # GRBL
        self.ui.com_search_button.clicked.connect(self.on_grbl_search_ports)
        self.ui.add_bd_button.clicked.connect(self.on_grbl_add_baudrate)
        self.ui.del_bd_button.clicked.connect(self.on_grbl_delete_baudrate_grbl)
        self.ui.baudrates_list_combo.currentTextChanged.connect(self.on_baudrate_changed)
        self.ui.controller_reset_button.clicked.connect(lambda: self.on_grbl_reset())
        self.ui.com_connect_button.clicked.connect(self.on_grbl_connect)
        self.ui.grbl_send_button.clicked.connect(self.on_grbl_send_command)
        self.ui.grbl_command_entry.returnPressed.connect(self.on_grbl_send_command)
        self.ui.ecut_motion_button.clicked.connect(self.on_ecut_motion_settings)

        # Jog
        for button, direction in ((self.ui.jog_wdg.jog_up_button, 'yplus'),
                                  (self.ui.jog_wdg.jog_down_button, 'yminus'),
                                  (self.ui.jog_wdg.jog_right_button, 'xplus'),
                                  (self.ui.jog_wdg.jog_left_button, 'xminus'),
                                  (self.ui.jog_wdg.jog_z_up_button, 'zplus'),
                                  (self.ui.jog_wdg.jog_z_down_button, 'zminus')):
            button.pressed.connect(lambda button=button, direction=direction:
                                   self._on_jog_pressed(button, direction))
            button.released.connect(self._stop_continuous_jog)
            button.clicked.connect(lambda checked=False, button=button, direction=direction:
                                   self._on_jog_clicked(button, direction))
        self.ui.continuous_jog_cb.toggled.connect(
            lambda checked: None if checked else self._stop_continuous_jog())
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
        self.ui.reset_button.clicked.connect(self.on_reset_tool)

        self.ui.console_cb.toggled.connect(self.on_console_toggled)
        self.ui.fit_view_cb.toggled.connect(self.on_fit_view_toggled)
        self.ui.start_button.clicked.connect(self.on_start)
        self.ui.hold_button.clicked.connect(lambda: self._grbl_realtime(b'!'))
        self.ui.resume_button.clicked.connect(self._on_resume_button)
        self.ui.stop_button.clicked.connect(self.on_stream_stop)
        self.ui.spindle_button.clicked.connect(self.on_spindle_button)
        self.ui.unlock_button.clicked.connect(self.on_unlock)
        self.ui.sim_button.clicked.connect(self.on_simulation)
        self.ui.save_levelled_button.clicked.connect(self.on_save_levelled_gcode)
        self.ui.view3d_button.clicked.connect(self.on_show_3d)
        for (name, text), (btn, byte) in self.ui.ov_buttons.items():
            btn.clicked.connect(lambda checked=False, b=byte: self._grbl_realtime(b))

    def on_reset_tool(self):
        self._probe_start_op = None
        self._clear_probe_data()
        self.set_tool_ui()

    def set_tool_ui(self):
        self._stop_continuous_jog()
        # closing or resetting the tool while adding manual points must give
        # the canvas events back to the app
        if self.__dict__.get('_simulation') is not None:
            self._simulation.close()
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        self._release_manual_mouse_events()

        self.units = self.app.app_units.upper()
        self.al_heights_valid = bool(getattr(self, 'al_heights_valid', False)) and \
            self._height_map_is_complete()
        self.clear_ui(self.layout)
        self.ui = GrblSenderUI(layout=self.layout, app=self.app)
        self.ui.spindle_button.setChecked(self.__dict__.get('_spindle_on', False))
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        mode_blocked = self.ui.al_mode_radio.blockSignals(True)
        method_blocked = self.ui.al_method_radio.blockSignals(True)
        try:
            self._populate_tool_ui()
        finally:
            self.ui.al_method_radio.blockSignals(method_blocked)
            self.ui.al_mode_radio.blockSignals(mode_blocked)
        if self.view3d is not None:
            self._schedule_3d_preview()

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

        self.ui.fit_view_cb.set_value(bool(self.app.options.get(
            "tools_gcode_fit_view", app_defaults.get("tools_gcode_fit_view", True))))
        self.ui.console_cb.set_value(bool(self.app.options.get(
            "tools_grbl_console_visible",
            app_defaults.get("tools_grbl_console_visible", False))))
        self.ui.autolevel_cb.set_value(False)
        self._grbl_set_ui_connected(self._grbl_port_ready())

    def on_object_changed(self):
        # first: a pending levelled Start request is old before the new target is published
        self._invalidate_start_requests()
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        self._probe_start_op = None

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
            self._reload_console_program(None)
            return

        self._reload_console_program(target_obj)

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

        if self.view3d is not None and self._is_supported_target(target_obj):
            self._schedule_3d_preview()

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
        port_list.append('SH-9001 E-Cut USB')
        self.ui.com_list_combo.clear()
        self.ui.com_list_combo.addItems(port_list)
        if muted is not True:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("COM list updated ..."))

    def on_grbl_connect(self):
        if self.__dict__.get('_simulation') is not None:
            return
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

        ecut = port_name == 'SH-9001 E-Cut USB'
        try:
            baudrate = 0 if ecut else int(self.ui.baudrates_list_combo.currentText())
        except ValueError:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a valid baudrate."))
            return

        if ecut:
            # check the board before any connection state changes
            from appPlugins.Common.ecut.ecut_config import EcutBoardConfig
            from appPlugins.Common.ecut.ecut_protocol import find_boards, EcutUsbError
            board = EcutBoardConfig()
            try:
                found = find_boards(board.vid, board.pid)
            except EcutUsbError as err:
                self.app.inform.emit('[ERROR_NOTCL] %s' % str(err))
                return
            if not found:
                self.app.inform.emit('[ERROR_NOTCL] %s' % (
                    _("E-Cut board not found (USB VID %04X, PID %04X). Connect the board and try again.")
                    % (board.vid, board.pid)))
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
        if ecut:
            self._ecut_connect_start(port_name, attempt)
            return

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

    def _ecut_connect_start(self, port_name, attempt):
        """
        Create the E-Cut port in a worker: its start waits for the HID worker and would stop the GUI.
        The result comes back on the GUI thread through ecut_connect_result_sig.
        """
        settings = Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.AppDataLocation)) / 'ecut' / 'grbl_settings.json'

        def create_port():
            port = error = None
            try:
                from appPlugins.Common.ecut.ecut_sender_port import EcutSenderPort
                port = EcutSenderPort(settings_path=settings, timeout=0.1, write_timeout=1.0)
            except Exception as failure:
                error = failure
            finally:
                self.ecut_connect_result_sig.emit((port_name, attempt, port, error))

        self.app.worker_task.emit({'fcn': create_port, 'params': []})

    def _close_ecut_port_async(self, port):
        """Close an E-Cut port that is not used (close() joins the worker and can block)."""
        def close_port():
            try:
                port.close()
            except Exception as err:
                self.app.log.debug("ToolGrblSender._close_ecut_port_async() -> %s" % str(err))

        self.app.worker_task.emit({'fcn': close_port, 'params': []})

    def _on_ecut_connect_result(self, response):
        """GUI thread: finish the E-Cut connection that a worker started."""
        port_name, attempt, port, error = response
        if error is not None:
            if self._grbl_connect_attempt is attempt:
                self.app.log.error("ToolGrblSender._on_ecut_connect_result() -> %s" % str(error))
                self._grbl_close_port(attempt=attempt)
                self.app.inform.emit("[ERROR_NOTCL] %s: %s" % (_("Could not connect to port"), port_name))
            return

        try:
            port.tool_change_callback = lambda tool, connection=port: self.ecut_tool_change_sig.emit(
                connection, tool, connection.tool_change_token)
            with self._grbl_op_lock:
                stale = self._grbl_connect_attempt is not attempt
                if not stale:
                    self.grbl_ser_port = port
                    self._grbl_rx_port = port
                    self._grbl_rx_buffer = b''
                    self._grbl_reply_pending = False
            if stale:
                # a new Connect or a Disconnect came first
                self._close_ecut_port_async(port)
                return

            # The HID adapter has initialized RAM and queued its verified connection banner.
            port.write("\r\n\r\n".encode('utf-8'))
        except (serial.SerialException, OSError, ValueError) as err:
            self.app.log.error("ToolGrblSender._on_ecut_connect_result() -> %s" % str(err))
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
            banner = any(is_controller_banner(text) for text in lines)
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
        self.ui.ecut_motion_button.setVisible(connected and self._ecut_settings_capable(self.grbl_ser_port))
        if not connected:
            self._close_ecut_motion_settings()
        continuous = connected and self._continuous_jog_capable(self.grbl_ser_port)
        self.ui.continuous_jog_cb.setVisible(continuous)
        if not continuous:
            self.ui.continuous_jog_cb.setChecked(False)
            self._stop_continuous_jog()
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
        self._controller_state = 'Idle'
        self._program_paused = False
        self._on_spindle_state(False)
        try:
            self._grbl_set_ui_connected(False)
        except (AttributeError, RuntimeError):
            # the UI can be already deleted when the application ends
            pass

    @staticmethod
    def _ecut_settings_capable(port):
        return all(callable(getattr(port, name, None)) for name in (
            'get_motion_settings', 'save_motion_settings', 'calibration_move',
            'get_io_state', 'set_manual_output'))

    def on_ecut_motion_settings(self):
        port = self.grbl_ser_port
        if not self._ecut_settings_capable(port):
            return
        dialog = self._ecut_motion_dialog
        if dialog is not None and self._ecut_motion_port is port:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return
        if self._ecut_motion_loading:
            return
        self._ecut_motion_loading = True

        def read_settings():
            result = error = None
            try:
                with self._grbl_op_lock:
                    valid = (self.grbl_ser_port is port and self._grbl_connected
                             and not self._grbl_close_pending)
                if not valid:
                    return
                result = port.get_motion_settings()
            except Exception as failure:
                error = str(failure)
            finally:
                self.ecut_motion_result_sig.emit((port, None, 'load', result, error))

        # This is an immutable worker-published snapshot, not a serial transaction.
        self.app.worker_task.emit({'fcn': read_settings, 'params': []})

    def _ecut_settings_task(self, op, dialog, action, args):
        port = op.port
        if dialog is not None:
            dialog.set_busy(True)
            dialog.set_calibration_running(action == 'calibrate')

        def task():
            result = error = None
            try:
                with self._grbl_op_lock:
                    valid = (self._grbl_op is op and self.grbl_ser_port is port
                             and not op.cancel.is_set() and not self._grbl_close_pending)
                if not valid:
                    raise ValueError(_("The controller operation was cancelled."))
                method = getattr(port, {'load': 'get_motion_settings', 'save': 'save_motion_settings',
                                        'calibrate': 'calibration_move', 'output': 'set_manual_output',
                                        'reference': 'reference_axes'}[action])
                result = method(*args)
                if action == 'reference' and {0, 1, 2} <= set(args[0]):
                    with self._grbl_op_lock:
                        # without home switches, a manual machine home of X, Y and Z replaces Home
                        if (self._grbl_recovery == 'needs_home' and not op.cancel.is_set()
                                and op.safety_generation == self._grbl_safety_generation):
                            self._grbl_recovery = None
                if op.cancel.is_set():
                    # the call returned: the board already took effect, so the result is reported
                    self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                        "Stop came after the E-Cut settings were applied; the board has the new settings."))
            except Exception as failure:
                error = str(failure)
            finally:
                self._grbl_release(op)
                self.ecut_motion_result_sig.emit((port, dialog, action, result, error))

        self.app.worker_task.emit({'fcn': task, 'params': []})

    def _ecut_motion_action(self, dialog, action, args):
        if (dialog is not self._ecut_motion_dialog or self.grbl_ser_port is not self._ecut_motion_port
                or not self._grbl_connected):
            dialog.show_error(_("The controller connection changed. Reopen its settings."))
            return
        op = self._grbl_reserve('E-Cut calibration' if action == 'calibrate' else 'E-Cut settings',
                                motion=action == 'calibrate')
        if op is not None:
            self._ecut_settings_task(op, dialog, action, args)
        else:
            dialog.show_error(_("The controller is busy. Wait until it is idle, then try again."))

    def _on_ecut_motion_result(self, response):
        port, dialog, action, result, error = response
        if action == 'load' and self.grbl_ser_port is port:
            self._ecut_motion_loading = False
        if self.grbl_ser_port is not port or not self._grbl_connected or not port.is_open:
            return
        if dialog is not None and dialog is not self._ecut_motion_dialog:
            return
        if error is not None:
            if dialog is not None:
                dialog.set_busy(False)
                dialog.show_error(error)
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s: %s' % (_("E-Cut settings"), error))
            return
        if action == 'load':
            from appPlugins.ToolGrblSender.SenderMotion import EcutMotionDialog
            try:
                dialog = EcutMotionDialog(result, parent=self)
            except (ValueError, TypeError, KeyError, OverflowError) as failure:
                self.app.inform.emit('[WARNING_NOTCL] %s: %s' % (_("Invalid E-Cut settings"), failure))
                return
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._ecut_motion_dialog, self._ecut_motion_port = dialog, port
            self._ecut_motion_revision = result['revision']
            dialog.apply_requested.connect(lambda values: self._ecut_motion_action(dialog, 'save', (values,)))
            dialog.calibration_requested.connect(lambda axis, distance, feed, revision:
                self._ecut_motion_action(dialog, 'calibrate', (axis, distance, feed, revision)))
            dialog.output_requested.connect(lambda pin, active:
                self._ecut_motion_action(dialog, 'output', (pin, active, self._ecut_motion_revision)))
            dialog.stop_requested.connect(self._stop_ecut_calibration)
            dialog.reference_requested.connect(lambda axes: self._ecut_motion_action(dialog, 'reference', (axes,)))
            dialog.finished.connect(lambda _result: self._closed_ecut_motion_settings(dialog))
            dialog.show()
            self._ecut_motion_io_timer.start()
        elif action == 'save':
            try:
                dialog.load_settings(result)
                self._ecut_motion_revision = result['revision']
            except (ValueError, TypeError, KeyError, OverflowError) as failure:
                dialog.show_error(str(failure))
            dialog.set_busy(False)
        elif action == 'calibrate':
            dialog.calibration_finished(result)
        else:
            dialog.set_busy(False)
        self._refresh_ecut_motion_io()

    def _stop_ecut_calibration(self):
        with self._grbl_op_lock:
            op = self._grbl_op
            if op is None or op.name != 'E-Cut calibration':
                return
            op.cancel.set()
        self._grbl_realtime(b'\x85')

    def _refresh_ecut_motion_io(self):
        dialog, port = self._ecut_motion_dialog, self._ecut_motion_port
        if dialog is None:
            self._ecut_motion_io_timer.stop()
            return
        if port is not self.grbl_ser_port or not self._grbl_connected:
            self._close_ecut_motion_settings()
            return
        try:
            state = port.get_io_state()
        except (OSError, ValueError, RuntimeError):
            state = {'connected': False, 'age_s': float('inf'), 'inputs': 0, 'outputs': 0, 'busy': True}
        dialog.update_io(state)

    def _closed_ecut_motion_settings(self, dialog):
        if self._ecut_motion_dialog is dialog:
            self._ecut_motion_io_timer.stop()
            self._ecut_motion_dialog = self._ecut_motion_port = self._ecut_motion_revision = None

    def _close_ecut_motion_settings(self):
        self._ecut_motion_loading = False
        dialog = self.__dict__.get('_ecut_motion_dialog')
        if dialog is not None:
            dialog.set_busy(False)
            dialog.reject()
            self._closed_ecut_motion_settings(dialog)

    def _on_ecut_tool_change(self, port, tool, token):
        def current():
            return (self.grbl_ser_port is port and port.is_open
                    and port.pending_tool_change == tool and port.tool_change_token is token)

        if not current():
            return
        answer = QtWidgets.QMessageBox.question(
            self.app.ui, _("Manual tool change"),
            _("Install tool %d, then confirm to continue. The spindle remains off until a spindle command.") % tool,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel)
        if not current():
            return
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            port.confirm_tool_change(tool, token=token)
        else:
            self.on_grbl_reset()

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

    def on_spindle_button(self, checked):
        """
        The Spindle button: M3 S<RPM> or M5. The button shows the spindle state, so it changes only
        when the controller accepts the command (spindle_state_sig).
        """
        self.ui.spindle_button.setChecked(self.__dict__.get('_spindle_on', False))
        cmd = 'M3 S%d' % self.ui.spindle_rpm_entry.get_value() if checked else 'M5'

        def task(op):
            return self._grbl_transact(op, cmd, timeout=30.0)[1] == 'ok'

        # a start needs a machine that is not in recovery; M5 is always allowed
        self._grbl_start_op('spindle', task, motion=checked)

    def _on_spindle_state(self, running):
        """Slot of spindle_state_sig (GUI thread): the Spindle button follows the spindle."""
        self._spindle_on = bool(running)
        button = getattr(self.__dict__.get('ui'), 'spindle_button', None)
        if button is not None:
            try:
                button.setChecked(self._spindle_on)
            except RuntimeError:
                pass  # the UI was deleted

    def _poll_idle_status(self):
        """
        Timer slot (1 s): read the status of an idle controller, so the Spindle button and the
        position follow changes that the sender did not send (alarm, E-stop, another program).
        Not in recovery: after a reset with the homing lock, GRBL reports Alarm, and a status
        query takes that as a new alarm.
        """
        if (not self.__dict__.get('_plugin_active') or self.__dict__.get('_simulation') is not None
                or not self._grbl_port_ready() or self._grbl_close_pending or self._grbl_op is not None
                or self._grbl_stream_dirty or self._grbl_reset_pending or self._grbl_recovery is not None):
            return

        def task(op):
            line = self._grbl_query_status(op, timeout=0.5)
            report = parse_grbl_status_report(line) if line else None
            if report is not None:
                self.status_report_sig.emit(report)

        # its own thread: in the app worker pool it can wait behind a long job while it holds the port
        self._grbl_start_op(STATUS_POLL, task, own_thread=True)

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

    @staticmethod
    def _continuous_jog_capable(port):
        return all(callable(getattr(port, name, None))
                   for name in ('start_jog', 'refresh_jog', 'stop_jog'))

    def _on_jog_clicked(self, button, direction):
        if self._continuous_jog_click_button is button:
            self._continuous_jog_click_button = None
            return
        self.on_grbl_jog(direction=direction)

    def _on_jog_pressed(self, button, direction):
        self._continuous_jog_click_button = None
        port = self.grbl_ser_port
        if not (self.ui.continuous_jog_cb.isChecked() and self._continuous_jog_capable(port)):
            return
        self._continuous_jog_click_button = button
        if self.ui.check_mode_cb.isChecked():
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Turn off check mode before jogging."))
            return
        op = self._grbl_reserve('continuous jog', motion=True)
        if op is None:
            return
        try:
            feed = self.ui.jog_fr_entry.get_value() * (25.4 if self.units == 'IN' else 1.0)
            port.start_jog('xyz'.index(direction[0]), int(direction.endswith('minus')), feed)
        except (serial.SerialException, OSError, ValueError) as error:
            self._grbl_release(op)
            self.app.inform.emit('[WARNING_NOTCL] %s: %s' % (_("Jog failed"), error))
            return
        self._continuous_jog = (port, button)
        self._continuous_jog_timer.start()

        def wait_for_stop():
            try:
                self._grbl_wait_idle(op)
            except (serial.SerialException, OSError) as error:
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Jog failed"), error))
            finally:
                self._grbl_release(op)

        self.app.worker_task.emit({'fcn': wait_for_stop, 'params': []})

    def _stop_continuous_jog(self):
        active = self.__dict__.get('_continuous_jog')
        if active is None:
            return
        self._continuous_jog = None
        self._continuous_jog_timer.stop()
        active[0].stop_jog()

    def _refresh_continuous_jog(self):
        active = self._continuous_jog
        if active is None:
            return
        port, button = active
        if (self.grbl_ser_port is not port or not self._grbl_connected or not button.isDown()
                or QtWidgets.QApplication.applicationState() != QtCore.Qt.ApplicationState.ApplicationActive
                or not button.window().isActiveWindow()
                or not self.ui.continuous_jog_cb.isChecked() or not port.refresh_jog()):
            self._stop_continuous_jog()

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
        if self.__dict__.get('_simulation') is not None:
            self._simulation.stop()
            return
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

    def on_grbl_reset(self, keep_position=None):
        """
        Soft reset of the controller; a worker then waits for the startup banner.

        :param keep_position: True if no motion ran, so the position is still valid and the
            machine does not need Home. None (the Reset button): found from the current state.
        """
        if self.__dict__.get('_simulation') is not None:
            return
        self._last_wco = None
        with self._grbl_op_lock:
            if keep_position is None:
                op = self._grbl_op
                keep_position = ((op is None or not op.motion) and not self._grbl_stream_dirty
                                 and self._grbl_recovery is None)
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
        # a soft reset stops the spindle
        self._on_spindle_state(False)
        self._grbl_confirm_reset_later(self._grbl_safety_generation, keep_position)

    def _grbl_confirm_reset_later(self, generation, keep_position, tries=40):
        """
        Read the startup banner of a reset when the cancelled operation has freed the port
        (GUI thread; it tries again every 50 ms). Without a confirmation, Home still reads it.
        """
        if self._grbl_safety_generation != generation or not self._grbl_reset_pending:
            return
        if self._grbl_op is not None:
            if tries > 0:
                QtCore.QTimer.singleShot(50, lambda: self._grbl_confirm_reset_later(generation, keep_position, tries - 1))
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s' % self._grbl_recovery_text())
            return

        def task(op):
            if not self._grbl_confirm_reset(op):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("GRBL reset was not confirmed. Press Reset, then Home."))
                return
            state = self._grbl_post_reset_state(op) if keep_position else None
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op) or op.safety_generation != self._grbl_safety_generation:
                    return
                if state == 'Idle':
                    # no motion ran, and a reset in Idle keeps the position
                    self._grbl_recovery = None
                    self.app.inform.emit('[success] %s' % _("Controller reset. The spindle and the outputs are off."))
                    return
            self.app.inform.emit('[WARNING_NOTCL] %s' % self._grbl_recovery_text())

        self._grbl_start_op('reset', task, allow_in_recovery=True)

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

    def _on_resume_button(self):
        """Resume button guard: block cycle-start when recovery is needed or a reset is pending.

        The pause/resume toggle (on_grbl_pause_resume) has the same guard, but the dedicated
        Resume button bypassed it by calling _grbl_realtime directly. After Stop or an error
        the stream is dirty and recovery is latched; sending ~ would restart abandoned motion.
        A healthy Hold->Resume is unaffected: _grbl_recovery is None in that path.

        All safety checks and the write happen in ONE critical section to prevent a worker
        from latching recovery between the check and the write.
        """
        with self._grbl_op_lock:
            # Recovery latched (needs_reset or needs_home): block resume
            if self._grbl_recovery is not None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % self._grbl_recovery_text())
                return
            # Reset in progress: block resume
            if self._grbl_reset_pending:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("A reset is pending. Wait for the banner."))
                return
            # Stream dirty but no healthy active operation: abandoned job, block resume
            if self._grbl_stream_dirty and (self._grbl_op is None or self._grbl_op.cancel.is_set() or self._grbl_op.failed):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("The previous job was abandoned. Press Reset, then Home."))
                return
            written = self._grbl_write_realtime_locked(b'~')
        if not written:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))
            return
        self.app.inform.emit("%s" % _("GRBL resumed."))

    def _select_available_excellon(self, *args):
        combo = self.ui.avoid_exc_combo
        root = self.app.collection.index(1, 0, QtCore.QModelIndex())
        if combo.rootModelIndex() != root:
            combo.setRootModelIndex(root)
        if combo.currentIndex() < 0 and combo.count():
            combo.setCurrentIndex(0)
        self._update_3d_excellon()

    def on_avoid_exc_holes(self, state):
        super().on_avoid_exc_holes(state)
        self.ui.avoid_exc_label.setVisible(bool(state))
        self.ui.avoid_exc_combo.setVisible(bool(state))
        self._update_3d_excellon()

    def _update_3d_excellon(self, *args):
        if self.view3d is None:
            return
        shapes = self.view3d.excellon_shapes
        shapes.clear()
        if self.ui.avoid_exc_holes_cb.get_value():
            try:
                objects = self._avoidance_excellon_objects()
            except ValueError:
                objects = []
            for obj in objects:
                for geo in flatten_shapely_geometry(obj.solid_geometry):
                    shapes.add(shape=geo, color=TOOL_COLOR, layer=0)
        shapes.redraw()

    def _avoidance_excellon_objects(self):
        name = self.ui.avoid_exc_combo.get_value()
        obj = self.app.collection.get_by_name(name) if name else None
        if obj is None or obj.kind != 'excellon':
            raise ValueError(_("Select an Excellon object to avoid its holes."))
        return [obj]

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
        self._queue_probe(False)

    def _queue_probe(self, start_after_probe):
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
        if start_after_probe:
            self._probe_start_op = op
            self.ui.start_button.setDisabled(True)

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
                if start_after_probe:
                    self.probe_finished_sig.emit(op, context)

        self.app.inform.emit('%s' % _("Sending probing GCode to the GRBL controller."))
        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def _on_probe_finished(self, op, context):
        if op is not getattr(self, '_probe_start_op', None):
            self._start_free_button()
            return
        self._probe_start_op = None
        if (op.cancel.is_set() or op.failed or op.safety_generation != self._grbl_safety_generation or
                not self._al_context_current(context) or not self.al_heights_valid or
                self.ui.autolevel_cb.get_value() is not True):
            self._start_free_button()
            return
        self._start_levelled(start_line=1)

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
        if getattr(self, '_probe_start_op', None) is not None:
            return
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        if self.ui.autolevel_cb.get_value() is True:
            choice = 'new'
            if self.al_heights_valid and self._height_map_is_complete():
                context = self._al_capture_context()
                seq = getattr(self, '_start_seq', 0)
                safety_generation = self._grbl_safety_generation
                choice = self._choose_height_map()
                if (not self._al_context_current(context) or seq != getattr(self, '_start_seq', 0) or
                        safety_generation != self._grbl_safety_generation):
                    self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                        "The height map, source object or machine state changed. Press Start again."))
                    return
            if choice == 'existing':
                self._start_levelled()
            elif choice == 'new':
                if self.ui.check_mode_cb.get_value() is True:
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                        "Check mode needs an existing height map. Probe first or turn off check mode."))
                    return
                if not self._is_supported_target(self._target()):
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a CNCJob object."))
                    return
                if not self.build_job():
                    return
                self._console().set_program(self.job_lines)
                target = self._target()
                source = target.source_file
                context = self._al_capture_context()
                generation = self._grbl_safety_generation
                start_line = self._choose_start_line(len(self.job_lines))
                if start_line is None:
                    return
                if (not self._al_context_current(context) or generation != self._grbl_safety_generation or
                        self._target() is not target or target.source_file != source):
                    self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                        "The program or machine state changed while the dialog was open. Press Start again."))
                    return
                if start_line != 1:
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                        "Starting from a line with auto-levelling needs an existing height map. "
                        "Probe first, then use the existing map."))
                    return
                self._queue_probe(True)
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

    def _choose_height_map(self):
        msgbox = FCMessageBox(parent=self.app.ui)
        msgbox.setWindowTitle(_("Height map"))
        msgbox.setText(_("A height map is available. Generate a new map or use the existing one?"))
        msgbox.setIcon(QtWidgets.QMessageBox.Icon.Question)
        new_button = msgbox.addButton(_('Generate New'), QtWidgets.QMessageBox.ButtonRole.YesRole)
        existing_button = msgbox.addButton(_('Use Existing'), QtWidgets.QMessageBox.ButtonRole.NoRole)
        cancel_button = msgbox.addButton(_('Cancel'), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msgbox.setDefaultButton(cancel_button)
        msgbox.exec()
        if msgbox.clickedButton() == new_button:
            return 'new'
        if msgbox.clickedButton() == existing_button:
            return 'existing'
        return 'cancel'

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

    def _start_levelled(self, start_line=None):
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
        req.start_line = start_line

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

    def _choose_start_line(self, line_count):
        dialog = GrblStartDialog(line_count, self.app.ui)
        try:
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return None
            return dialog.line_entry.get_value() if dialog.start_radio.get_value() == 'line' else 1
        finally:
            dialog.deleteLater()

    def _start_stream_worker(self, op, lines, numbers, check_mode, poll_ms, req=None):
        """Start the stream worker under the reserved operation `op` (GUI thread). `req`: a levelled Start."""
        self._console().set_program(lines)
        target = self._target()
        source = target.source_file
        seq = getattr(self, '_start_seq', 0)
        generation = self._grbl_safety_generation
        self.ui.start_button.setDisabled(True)
        start_line = (req.start_line if req is not None and req.start_line is not None
                      else self._choose_start_line(len(lines)))
        with self._grbl_op_lock:
            current = (self._grbl_active_locked(op) and not op.cancel.is_set() and
                       generation == self._grbl_safety_generation and seq == getattr(self, '_start_seq', 0))
        if start_line is None or not current or self._target() is not target or target.source_file != source:
            self._grbl_release(op)
            self._start_free_button()
            if op.cancel.is_set():
                self._stream_result = {}
                self.stream_ended_sig.emit('stopped')
            if start_line is not None:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                    "The program or machine state changed while the dialog was open. Press Start again."))
            return
        restart = None
        if start_line != 1:
            try:
                preamble, resumed = SenderGen.restart_preamble(
                    lines, start_line, getattr(target, 'z_move', None), target.units, target.coords_decimals)
                if validate_stream_lines(preamble + resumed) is not None:
                    raise ValueError(_("The restart preparation exceeds the GRBL line length limit."))
            except ValueError as err:
                self.app.inform.emit('[ERROR_NOTCL] %s' % str(err))
                self._grbl_release(op)
                self._start_free_button()
                return
            restart = (preamble, start_line - 1, resumed)
            self.app.inform.emit('%s: %d' % (_("Starting from program line"), start_line))

        self._program_paused = False
        self._preview_generation = self.__dict__.get('_preview_generation', 0) + 1
        if self.view3d is not None:
            display, indexes, chords = self._display_lines()
            segments = parse_toolpath(display)
            if indexes is not None:
                segments = [(indexes[i], a, b, rapid) for i, a, b, rapid in segments]
            self.view3d.set_toolpath(segments, chords)

        def worker_task():
            how = 'error'
            try:
                how = self._grbl_stream_run(op, lines, numbers, check_mode, poll_ms / 1000.0, req,
                                            restart=restart)
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

    def _grbl_stream_run(self, op, lines, numbers, check_mode, poll_interval, req=None, restart=None):
        """
        The stream worker under 1 operation (a worker thread; it reads no widgets).

        :param numbers:       the line number in the G-code text of each line of `lines`.
        :param check_mode:    True if the user asked for check mode for this job.
        :param poll_interval: seconds between 2 status requests.
        :param req:           the _StartRequest of a levelled Start (phase 2 of A8.3), else None.
        :param restart:       (preamble, zero-based console index, resumed lines), or None for Beginning.
        :return: `how`: 'finished', 'check_passed', 'check_passed_needs_home', 'check_failed',
            'check_exit_failed', 'stopped', 'incomplete', 'rejected' (nothing was sent), 'stale',
            'stale_needs_home' (a stale request: GRBL got no job line), or the name of a failure
            ('port_error', 'timeout', 'error', 'alarm', 'line_too_long', 'unexpected_reset').
            'unexpected_reset' means a Grbl banner was seen mid-stream (controller reset).
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
        preamble, start_index, resumed = restart if restart is not None else ([], 0, lines)
        prefix_count = len(preamble)

        def program_done(done):
            # Preparation commands aren't lines of the displayed program.
            return start_index + done - prefix_count if done > prefix_count else 0

        program = preamble + resumed
        prepare_program = getattr(port, 'prepare_program', None)
        if program and not check_mode and callable(prepare_program):
            try:
                prepare_program(program)
            except (serial.SerialException, OSError, ValueError) as error:
                self._stream_result = {'done': 0, 'last_text': str(error),
                                       'line': numbers[start_index] if start_index < len(numbers) else 1,
                                       'errors': [], 'error_indices': []}
                with self._grbl_op_lock:
                    self._grbl_abort_stream_locked(op, 'error', str(error))
                return 'error'

        res = stream_lines(
            program, write, readline, check_mode=check_mode,
            on_progress=lambda d, t: self.stream_progress_sig.emit(program_done(d), len(lines)),
            on_line=self.console_line_sig.emit,
            poll_status=True, poll_interval=poll_interval,
            on_status=lambda line: self.status_report_sig.emit(parse_grbl_status_report(line)))
        status = res['status']

        def source_number(index):
            index = start_index + max(0, index - prefix_count)
            return numbers[index] if 0 <= index < len(numbers) else index + 1

        failed_index = res['errors'][-1][0] if res['errors'] else res['done']
        self._stream_result = {
            'done': program_done(res['done']),
            'last_text': res['last_text'],
            'line': source_number(res.get('line_index', failed_index)),
            'errors': [source_number(index) for index, _text in res['errors']],
            'error_indices': [start_index + index - prefix_count for index in
                              ([index for index, _text in res['errors']] +
                               ([res['line_index']] if status == 'line_too_long' else []))
                              if index >= prefix_count],
        }
        if res['errors'] and res['errors'][-1][0] < prefix_count:
            self._stream_result['last_text'] = '%s: %s' % (_("Restart preparation"), res['last_text'])

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
        """
        Stop: feed hold now; the stream worker stops writing. Then a soft reset, which also stops
        the spindle. If no motion ran, the position is kept and the machine does not need Home.
        """
        if self.__dict__.get('_simulation') is not None:
            self.on_grbl_stop()
            return
        with self._grbl_op_lock:
            op = self._grbl_op
            idle = (op is None or not op.motion) and not self._grbl_stream_dirty and self._grbl_recovery is None
        self.on_grbl_stop()
        if not self._grbl_port_ready():
            return
        generation = self._grbl_safety_generation
        port = self.grbl_ser_port

        def reset():
            if self._grbl_safety_generation == generation and self.grbl_ser_port is port and self._grbl_port_ready():
                self.on_grbl_reset(keep_position=idle)

        # a moving machine gets time to brake in the feed hold before the reset
        QtCore.QTimer.singleShot(0 if idle else 500, reset)

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

    def on_program_line_selected(self, index):
        """Inspect selected moves while idle or held; running selection follows progress."""
        if self._grbl_op is not None and self.__dict__.get('_program_paused') is not True:
            console = self.app.ui.grbl_console_dock.widget()
            if isinstance(console, GrblConsole):
                console._follow_program(console.follow_cb.isChecked())
            return
        if self.view3d is not None:
            self.view3d.set_selected_line(index)

    def _on_stream_progress(self, done, total):
        self.ui.progress_bar.setValue(int(done * 100 / total) if total else 0)
        console = self.app.ui.grbl_console_dock.widget()
        if isinstance(console, GrblConsole):
            console.update_progress(done)
        if self.view3d is not None:
            # `done` counts stream lines; the segments of the toolpath carry the index of their stream line
            self.view3d.set_accepted(done - 1)
            if self.__dict__.get('_program_paused') is not True:
                self.view3d.set_selected_line(None)

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

    def _simulation_available(self):
        return (self._grbl_op is None and self._probe_start_op is None and
                not self._grbl_close_pending and not self.__dict__.get('_program_paused', False) and
                self._controller_state not in ('Run', 'Hold', 'Door', 'Jog', 'Home') and
                not (self.grbl_ser_port is not None and not self._grbl_connected))

    def _update_sim_button(self):
        self.ui.sim_button.setEnabled(self._simulation is None and self._simulation_available())

    def on_simulation(self):
        if self._simulation is not None or not self._simulation_available():
            return
        self._simulation = SimulationDialog(self)
        self._simulation.show()
        self._update_sim_button()

    def _start_simulation(self):
        dialog = self._simulation
        if dialog is None or dialog.running or not self._simulation_available():
            return
        autolevel = self.ui.autolevel_cb.get_value() is True
        if not (self.build_job() if autolevel else self.build_stream_job()):
            return
        lines = list(self.job_lines)
        if not lines:
            return
        probe_lines = []
        points = ()
        target = self._target()
        controller = VirtualGrbl()
        controller.scale = 25.4 if target.units.upper() == 'IN' else 1.0
        if autolevel:
            if not self.al_voronoi_geo_storage:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Add probe points before simulating auto-levelling."))
                return
            if self._al_data_units != target.units.upper():
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "The units of the CNCJob object and of the height map do not match."))
                return
            inputs = self._al_read_probe_inputs()
            if inputs is None:
                return
            travel_z, depth, feed = inputs
            if travel_z * controller.scale <= 0.25:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "Simulation probe travel Z must be above the 0.25 mm simulated surface."))
                return
            preprocessors = [str(getattr(target, name, '') or '').lower()
                             for name in ('pp_geometry_name', 'pp_excellon_name')]
            if (self._tlo_line(lines) is not None or getattr(target, 'pp_solderpaste_name', None) is not None or
                    any(marker in name for name in preprocessors for marker in ('roland', 'hpgl', 'laser'))):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("This program can not be height-compensated."))
                return
            # ponytail: independent samples model warp; use a spatial surface if smooth warp is needed.
            points = tuple((v['point'].x, v['point'].y, random.uniform(0.0, 0.25) / controller.scale)
                           for v in self.al_voronoi_geo_storage.values())
            if any(not math.isfinite(value) for point in points for value in point):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("The height map contains invalid values."))
                return
            if SenderGen.needs_segmentation(target):
                lines, _count = split_long_moves(
                    lines, float(self.app.options.get("tools_grbl_seg_len", 1.0)),
                    decimals=target.coords_decimals)
            # The leveller keeps interpolation caches on self. Keep simulated data private too.
            cache_names = ('_al_points', '_al_grid', '_al_decimals', '_al_offset_fn')
            caches = {name: self.__dict__[name] for name in cache_names if name in self.__dict__}
            try:
                result = self.autolevell_gcode(
                    SenderGen.job_proxy(target, lines), self.ui.al_method_radio.get_value(),
                    snapshot=(points, target.units.upper(), self._al_grid_tolerance()), strict=True)
            finally:
                for name in cache_names:
                    self.__dict__.pop(name, None)
                self.__dict__.update(caches)
            if result is None:
                return
            lines = [line for line in result['job'].splitlines() if line.strip()]
            if validate_stream_lines(lines) is not None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("The levelled G-code has a line longer than GRBL accepts."))
                return
            probe_lines = ['G20 G90' if controller.scale == 25.4 else 'G21 G90', 'G0 Z%.6f' % travel_z]
            for x, y, height in points:
                controller.probe_heights.append(height * controller.scale)
                probe_lines.extend(['G0 X%.6f Y%.6f' % (x, y), 'G38.2 Z%.6f F%.6f' % (depth, feed),
                                    'G0 Z%.6f' % travel_z])
            probe_lines.append('G0 X0 Y0')
        if probe_lines:
            # Only the simulator knows the contact position. Keep real probe parsing conservative.
            display = list(probe_lines)
            display[0] = 'G90'
            display[1] = 'G0 X0 Y0 Z%.6f' % travel_z
            for i, (_x, _y, height) in enumerate(points):
                display[3 + 3 * i] = 'G1 Z%.6f' % height
            segments = parse_toolpath(display, start=(0, 0, 0))
            # Keep the cutting path visible without accepting it during the probing phase.
            segments.extend((len(probe_lines) + i, a, b, rapid)
                            for i, a, b, rapid in parse_toolpath(lines, start=(0, 0, 0)))
            chords = ()
        else:
            display, indexes, chords = self._display_lines()
            segments = parse_toolpath(display, start=(0, 0, 0))
            if indexes is not None:
                segments = [(indexes[i], a, b, rapid) for i, a, b, rapid in segments]
        dialog.preview = (segments, chords)
        dialog.height_map = None
        dialog.progress = 0
        controller.set_speed(dialog.slider.value())
        dialog.controller = controller
        dialog.units = self._target().units.upper()
        dialog.running = True
        dialog.start_button.setEnabled(False)
        dialog.stop_button.setEnabled(True)
        dialog.pause_button.setEnabled(True)
        dialog.pause_button.setText(_("Pause"))
        self._preview_generation += 1
        self._console().set_program(probe_lines or lines)
        self.ui.progress_bar.setValue(0)
        self.ui.start_button.setEnabled(False)
        self.ui.object_combo.setEnabled(False)
        if self.view3d is not None:
            if probe_lines:
                self.view3d.set_height_map(None)
            self.view3d.set_toolpath(*dialog.preview)
            if self.app.options.get("tools_gcode_fit_view", True):
                self.on_fit_view()

        pending = {}
        console_lines = []
        last_update = time.monotonic()

        def flush(force=False):
            nonlocal last_update
            now = time.monotonic()
            # Keep fast simulations from queuing a redraw and selection update for every line.
            if not force and now - last_update < 0.05:
                return
            if console_lines:
                self.simulation_event_sig.emit(dialog, 'console', '\n'.join(console_lines))
                console_lines.clear()
            for kind, value in pending.items():
                self.simulation_event_sig.emit(dialog, kind, value)
            pending.clear()
            last_update = now

        def event(kind, value):
            if kind == 'console':
                console_lines.append(value)
            else:
                pending[kind] = value
            flush()

        def worker_task():
            result = {'status': 'error', 'done': 0}
            try:
                if probe_lines:
                    result = stream_lines(
                        probe_lines, controller.write, controller.readline, poll_status=True, poll_interval=0.05,
                        stall_timeout=float('inf'),
                        on_progress=lambda done, total: event('progress', (done, total)),
                        on_line=lambda line: event('console', line),
                        on_status=lambda line: event('status', parse_grbl_status_report(line)))
                    if result['status'] != 'finished' or controller.cancel.is_set():
                        if controller.cancel.is_set():
                            result['status'] = 'cancelled'
                        return
                    flush(force=True)
                    self.simulation_event_sig.emit(dialog, 'program', (lines, points))
                # The same character-counting streamer as the physical controller, with private I/O.
                result = stream_lines(
                    lines, controller.write, controller.readline, poll_status=True, poll_interval=0.05,
                    stall_timeout=float('inf'),
                    on_progress=lambda done, total: event('progress', (done, total)),
                    on_line=lambda line: event('console', line),
                    on_status=lambda line: event('status', parse_grbl_status_report(line)))
            except Exception as err:
                self.app.log.error('G-code simulation -> %s' % str(err))
                result['last_text'] = str(err)
            finally:
                event('position', tuple(controller.position))
                flush(force=True)
                self.simulation_event_sig.emit(dialog, 'finished', result)

        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def _on_simulation_event(self, dialog, kind, value):
        if self._simulation is not dialog:
            return
        if kind == 'progress':
            dialog.progress = value[0]
            self._on_stream_progress(*value)
        elif kind == 'console':
            self._console().append(value)
        elif kind == 'program':
            lines, points = value
            dialog.preview = (parse_toolpath(lines, start=(0, 0, 0)), ())
            dialog.height_map = build_bilinear_grid(points, self._al_grid_tolerance())
            dialog.progress = 0
            self._console().set_program(lines)
            self.ui.progress_bar.setValue(0)
            if self.view3d is not None:
                self._update_3d_height_map()
                self.view3d.set_toolpath(*dialog.preview)
        elif kind == 'status' and value is not None:
            self._program_paused = dialog.controller.paused
            self._on_simulation_event(dialog, 'position', value['mpos'])
        elif kind == 'position':
            scale = 1 / 25.4 if dialog.units == 'IN' else 1.0
            pos = tuple(axis * scale for axis in value)
            state = _("Paused") if dialog.controller.paused else _("Running")
            self.ui.status_label.setText(_("Simulation") + ': ' + state +
                                         '   X %.3f  Y %.3f  Z %.3f' % pos)
            if self.view3d is not None:
                self.view3d.set_tool_position(pos)
        elif kind == 'finished':
            dialog.running = False
            dialog.start_button.setEnabled(True)
            dialog.stop_button.setEnabled(False)
            dialog.pause_button.setEnabled(False)
            self._program_paused = False
            self.ui.start_button.setEnabled(True)
            self.ui.object_combo.setEnabled(True)
            status = value['status']
            text = (_("Finished") if status == 'finished' else
                    _("Stopped") if status == 'cancelled' else
                    _("Error") + ': ' + value.get('last_text', status))
            self.ui.status_label.setText(_("Simulation") + ': ' + text)
            if dialog.closing:
                self._close_simulation()

    def _close_simulation(self):
        if self._simulation is None or self._simulation.running:
            return
        self._simulation.deleteLater()
        self._simulation = None
        self._update_3d_height_map()
        self._update_sim_button()

    def _on_status_report(self, report):
        if report is None:
            return
        self._controller_state = report['state'].split(':')[0]
        was_paused = self.__dict__.get('_program_paused') is True
        self._program_paused = report['state'].split(':')[0] in ('Hold', 'Door')
        if was_paused and not self._program_paused and report['state'] == 'Run':
            if self.view3d is not None:
                self.view3d.set_selected_line(None)
            console = self.app.ui.grbl_console_dock.widget()
            if isinstance(console, GrblConsole):
                console._follow_program(console.follow_cb.isChecked())
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
            # the accessory field comes with 'Ov'; without it, no accessory is on
            accessory = report.get('accessory', '')
            self._on_spindle_state('S' in accessory or 'C' in accessory)
        if self.view3d is not None and pos is not None:
            self.view3d.set_tool_position(pos)

    def show_probing_geo(self, state, reset=False):
        if self.view3d is not None and (reset or not state):
            self.view3d.probing_shapes.clear(update=True)
        super().show_probing_geo(state, reset=reset)

    def add_probing_shape(self, **kwargs):
        key = super().add_probing_shape(**kwargs)
        if self.view3d is not None:
            self.view3d.probing_shapes.add(tolerance=self.drawing_tolerance, layer=0, **kwargs)
        return key

    def plot_probing_geo(self, geometry, visibility, custom_color=None):
        super().plot_probing_geo(geometry, visibility, custom_color=custom_color)
        if self.view3d is not None:
            if visibility:
                self.view3d.probing_shapes.redraw()
            else:
                self.view3d.probing_shapes.clear(update=True)

    def _schedule_3d_preview(self):
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        generation = self._preview_generation

        def show_after_load():
            if generation != self._preview_generation:
                return
            self._cleanup_3d_if_inactive()
            if generation == self._preview_generation:
                self.on_show_3d()

        QtCore.QTimer.singleShot(0, show_after_load)

    def on_show_3d(self):
        open_3d_tab = getattr(self.app, 'on_3d_area', None)
        if callable(open_3d_tab):
            open_3d_tab()
        canvas = getattr(self.app, 'plotcanvas3d', None)
        if canvas is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The Plot 3D tab is not available."))
            return
        if self.view3d is None or self.view3d.canvas is not canvas:
            self.view3d = SenderView3d(canvas)
            # the sender view starts in the isometric view; later the camera stays as the user turns it
            canvas.view.camera.set_view('iso')
        dialog = self.__dict__.get('_simulation')
        if dialog is not None and dialog.running:
            self.view3d.set_toolpath(*dialog.preview)
            self.view3d.set_accepted(dialog.progress - 1)
            self._update_3d_height_map()
            scale = 1 / 25.4 if dialog.units == 'IN' else 1.0
            self.view3d.set_tool_position(tuple(value * scale for value in dialog.controller.position))
            if self.app.options.get("tools_gcode_fit_view", True):
                self.on_fit_view()
            return
        self._update_3d_excellon()
        if self.ui.plot_probing_pts_cb.get_value() and self.al_voronoi_geo_storage:
            self.show_probing_geo(True, reset=True)
        else:
            self.view3d.probing_shapes.clear(update=True)
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        generation = self._preview_generation
        target = self._target()
        self._update_3d_height_map()
        if target is None:
            self.view3d.set_toolpath([])
            if self.app.options.get("tools_gcode_fit_view", True):
                canvas.fit_view()
            return
        # Freeze inputs before queuing work. Workers must never read widgets or mutate the stream job.
        source = getattr(target, 'source_file', '') or ''
        units, decimals = target.units, target.coords_decimals
        arc_mode = self.app.options.get("tools_grbl_arc_mode", 'split')
        arc_segment = float(self.app.options.get("tools_grbl_arc_segment", 0.5))
        seg_len = float(self.app.options.get("tools_grbl_seg_len", 1.0))
        segmented = not SenderGen.needs_segmentation(target)
        method = self.ui.al_method_radio.get_value()
        level = self.ui.autolevel_cb.get_value() is True and self.al_heights_valid
        snapshot = self._al_capture_apply_input(target, require_segmented=False) if level else None
        map_generation = self._al_generation
        home_wcs = float(str(self._al_map_frame[0])[1:]) if level and self._al_map_frame else None
        proxy = SenderGen.job_proxy(target, [])
        proxy.obj_options = dict(target.obj_options)
        view = self.view3d
        app = self.app

        def worker_task():
            result = {'generation': generation, 'target': target, 'source': source,
                      'map_generation': map_generation, 'view': view, 'levelled': snapshot is not None}
            try:
                numbered = SenderGen.clean_lines_numbered(source)
                job_lines = [line for _number, line in numbered]
                numbers = [number for number, _line in numbered]
                if snapshot is not None:
                    if self._tlo_line(job_lines) is not None:
                        raise ValueError(_("The program changes the tool length offset. It can not be levelled."))
                    if not segmented:
                        job_lines, _count = split_long_moves(job_lines, seg_len, decimals=decimals)
                    proxy.tools['job']['gcode'] = '\n'.join(job_lines) + '\n'
                    # Interpolation state is per instance; preview and Start must not share it.
                    leveler = LevellingCoreMixin()
                    leveler.app = app
                    leveler._al_arc_segment = lambda obj: arc_segment
                    levelled = leveler.autolevell_gcode(proxy, method, snapshot=snapshot,
                                                       home_wcs=home_wcs, strict=True)
                    if levelled is None:
                        raise ValueError(_("Could not prepare the levelled preview."))
                    job_lines = [line for line in levelled['job'].splitlines() if line.strip()]
                    numbers = []
                elif arc_mode == 'split':
                    job_lines, _count, indexes, unsplit = SenderGen.split_arcs(
                        job_lines, units, arc_segment, decimals=decimals)
                    if unsplit:
                        raise ValueError(_("An arc can not be split for the preview."))
                    numbers = [numbers[i] for i in indexes]
                lines, indexes, chords = job_lines, None, ()
                if snapshot is None and arc_mode != 'split':
                    lines, _count, indexes, chords = SenderGen.split_arcs(
                        job_lines, units, arc_segment, decimals=decimals)
                segments = parse_toolpath(lines)
                if indexes is not None:
                    segments = [(indexes[i], a, b, rapid) for i, a, b, rapid in segments]
                result.update(prepared=SenderView3d.prepare_toolpath(segments, chords),
                              lines=job_lines, numbers=numbers)
            except Exception as err:
                app.log.error("ToolGrblSender.on_show_3d() -> %s" % str(err))
                result['error'] = str(err)
            self.preview_ready_sig.emit(result)

        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def _on_preview_ready(self, result):
        if (self._grbl_op is not None or result['generation'] != self._preview_generation or
                result['view'] is not self.view3d or
                self.view3d is None or self.view3d.canvas is not getattr(self.app, 'plotcanvas3d', None) or
                result['map_generation'] != self._al_generation or self._target() is not result['target'] or
                (getattr(result['target'], 'source_file', '') or '') != result['source']):
            return
        if 'error' in result:
            self.view3d.set_toolpath([])
            self.app.inform.emit('[ERROR_NOTCL] %s' % result['error'])
            return
        self.view3d.set_prepared_toolpath(result['prepared'])
        if self._grbl_op is None and getattr(self, '_probe_start_op', None) is None:
            self.job_lines = result['lines']
            self.job_line_numbers = result['numbers']
            self.job_target_name = result['target'].obj_options['name']
            self.job_map_generation = result['map_generation'] if result['levelled'] else None
            self._console().set_program(self.job_lines)
        self._update_3d_height_map()
        if self.app.options.get("tools_gcode_fit_view", True):
            self.on_fit_view()

    def on_fit_view_toggled(self, checked):
        self.app.options["tools_gcode_fit_view"] = bool(checked)
        self.app.defaults["tools_gcode_fit_view"] = bool(checked)

    def on_fit_view(self):
        if self.view3d is None or not self.view3d._segments:
            return
        canvas = self.view3d.canvas
        canvas.view.camera.set_view('iso')
        canvas.fit_view(points=self.view3d.path.pos, margin=0.1)

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
        if not self.al_voronoi_geo_storage:
            self.view3d.probing_shapes.clear(update=True)
        if not self.ui.plot_height_map_cb.get_value():
            self.view3d.set_height_map(None)
            return
        dialog = self.__dict__.get('_simulation')
        if dialog is not None:
            self.view3d.set_height_map(dialog.height_map)
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
        console = self.app.ui.grbl_console_dock.widget()
        if isinstance(console, GrblConsole):
            console.update_progress(result.get('done', 0), result.get('error_indices', []))
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

    def _reload_console_program(self, target_obj):
        # A running stream keeps its own program and acknowledgement indexes.
        if self.__dict__.get('_simulation') is not None and self._simulation.running:
            return
        if self._grbl_op is not None and self._grbl_op.name == 'stream':
            return
        text = (getattr(target_obj, 'source_file', '') or '') if self._is_supported_target(target_obj) else ''
        self._console().set_program([line for _number, line in SenderGen.clean_lines_numbered(text)])

    def on_console_toggled(self, checked):
        self.app.options["tools_grbl_console_visible"] = bool(checked)
        if checked:
            self.show_console_if_wanted()
        else:
            self.app.ui.grbl_console_dock.hide()

    def show_console_if_wanted(self):
        if self.app.options.get("tools_grbl_console_visible", False):
            console = self._console()
            console.tabs.setCurrentIndex(0)
            self.app.ui.grbl_console_dock.show()
            self.app.ui.grbl_console_dock.raise_()
            console.program_view.setFocus()

    def hide_console(self):
        self.app.ui.grbl_console_dock.hide()

    def send_console_command(self, text):
        self.ui.grbl_command_entry.set_value(text)
        self.on_grbl_send_command()

    def on_plugin_cleanup(self):
        """The plugin closes: stop and disconnect the controller, release the Plot 3D tab, hide the console."""
        if self.__dict__.get('_simulation') is not None:
            self._simulation.close()
        self._grbl_shutdown()
        self._plugin_active = False
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        self._probe_start_op = None
        self._clear_probe_data()
        self.hide_console()
        view = self.view3d
        self.view3d = None
        if view is None or view.canvas is not getattr(self.app, 'plotcanvas3d', None):
            return
        view.clear()
        tabs = self.app.ui.plot_tab_area
        index = tabs.indexOf(self.app.area_3d_tab)
        if index >= 0:
            tabs.closeTab(index)

    def _cleanup_3d_if_inactive(self):
        ui = self.app.ui
        if ui.plugin_scroll_area.widget() is not self or ui.notebook.indexOf(ui.plugin_tab) < 0:
            self.on_plugin_cleanup()

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.Close,
                            QtCore.QEvent.Type.ApplicationDeactivate, QtCore.QEvent.Type.WindowDeactivate):
            self._stop_continuous_jog()
        result = super().event(event)
        if event.type() in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.ParentChange) and \
                getattr(self, '_plugin_active', False):
            # Wait for takeWidget()/removeTab() to finish; hiding a notebook page isn't a close.
            QtCore.QTimer.singleShot(0, self._cleanup_3d_if_inactive)
        return result
