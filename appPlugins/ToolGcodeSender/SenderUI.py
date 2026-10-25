# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt

from appGUI.GUIElements import (
    FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, FCJog, FCDoubleSpinner, FCSpinner,
    FCDetachableTab, FCZeroAxes, FCSliderWithDoubleSpinner, FCEntry, RotatedToolButton)
from appPlugins.Common.levelling_ui import build_probe_points_ui

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class GcodeSenderUI:
    pluginName = _("GCode sender")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        self.title_box = QtWidgets.QHBoxLayout()
        self.tools_box.addLayout(self.title_box)

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("Send G-code to a GRBL controller.")
        )

        self.title_box.addWidget(title_label)

        # App Level label
        self.level = QtWidgets.QToolButton()
        self.level.setToolTip(
            _(
                "Beginner Mode - many parameters are hidden.\n"
                "Advanced Mode - full control.\n"
                "Permanent change is done in 'Preferences' menu."
            )
        )
        # self.level.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.level.setCheckable(True)
        self.title_box.addWidget(self.level)

        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("The CNCJob object to send.")
        )

        self.console_cb = FCCheckBox(_("Show console"))
        self.console_cb.setToolTip(_("Show or hide the GCode Console dock."))

        self.fit_view_cb = FCCheckBox(_("Fit View"))
        self.fit_view_cb.setToolTip(_("Fit the GCode bounds in isometric view after loading the source object."))

        obj_hlay = QtWidgets.QHBoxLayout()
        obj_hlay.addWidget(self.obj_combo_label)
        obj_hlay.addStretch()
        obj_hlay.addWidget(self.fit_view_cb)
        obj_hlay.addWidget(self.console_cb)
        self.tools_box.addLayout(obj_hlay)

        self.source_frame = QtWidgets.QFrame()
        source_box = QtWidgets.QVBoxLayout(self.source_frame)
        source_box.setContentsMargins(0, 0, 0, 0)
        self.tools_box.addWidget(self.source_frame)

        # #############################################################################################################
        # ################################ The object to be Auto-levelled ##############################################
        # #############################################################################################################
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(3, 0, QtCore.QModelIndex()))
        # self.object_combo.setCurrentIndex(1)
        self.object_combo.is_last = True

        source_box.addWidget(self.object_combo)

        self.al_toolbar = FCDetachableTab(protect=True)
        self.al_toolbar.setTabsClosable(False)
        self.al_toolbar.useOldIndex(True)
        self.al_toolbar.set_detachable(val=False)
        source_box.addWidget(self.al_toolbar)

        # GRBL Connect TAB
        self.gr_conn_tab = QtWidgets.QWidget()
        self.gr_conn_tab.setObjectName("connect_tab")
        self.gr_conn_tab_layout = QtWidgets.QVBoxLayout(self.gr_conn_tab)
        self.gr_conn_tab_layout.setContentsMargins(2, 2, 2, 2)
        # self.gr_conn_scroll_area = VerticalScrollArea()
        # self.gr_conn_tab_layout.addWidget(self.gr_conn_scroll_area)
        self.al_toolbar.addTab(self.gr_conn_tab, _("Connect"))

        # GRBL Control TAB
        self.gr_ctrl_tab = QtWidgets.QWidget()
        self.gr_ctrl_tab.setObjectName("connect_tab")
        self.gr_ctrl_tab_layout = QtWidgets.QVBoxLayout(self.gr_ctrl_tab)
        self.gr_ctrl_tab_layout.setContentsMargins(2, 2, 2, 2)

        # self.gr_ctrl_scroll_area = VerticalScrollArea()
        # self.gr_ctrl_tab_layout.addWidget(self.gr_ctrl_scroll_area)
        self.al_toolbar.addTab(self.gr_ctrl_tab, _("Control"))

        # GRBL Sender TAB
        self.gr_send_tab = QtWidgets.QWidget()
        self.gr_send_tab.setObjectName("connect_tab")
        self.gr_send_tab_layout = QtWidgets.QVBoxLayout(self.gr_send_tab)
        self.gr_send_tab_layout.setContentsMargins(2, 2, 2, 2)

        # self.gr_send_scroll_area = VerticalScrollArea()
        # self.gr_send_tab_layout.addWidget(self.gr_send_scroll_area)
        self.al_toolbar.addTab(self.gr_send_tab, _("Sender"))

        for idx in range(self.al_toolbar.count()):
            if self.al_toolbar.tabText(idx) == _("Connect"):
                self.al_toolbar.tabBar.setTabTextColor(idx, QtGui.QColor('red'))
            if self.al_toolbar.tabText(idx) == _("Control"):
                self.al_toolbar.tabBar.setTabEnabled(idx, False)
            if self.al_toolbar.tabText(idx) == _("Sender"):
                self.al_toolbar.tabBar.setTabEnabled(idx, False)
        # #############################################################################################################

        # #############################################################################################################
        # GRBL CONNECT
        # #############################################################################################################
        self.connect_frame = FCFrame()
        self.gr_conn_tab_layout.addWidget(self.connect_frame)

        grbl_conn_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 1, 0])
        self.connect_frame.setLayout(grbl_conn_grid)

        # COM list
        self.com_list_label = FCLabel('%s:' % _("COM list"))
        self.com_list_label.setToolTip(
            _("Lists the available serial ports.")
        )

        self.com_list_combo = FCComboBox()
        self.com_search_button = FCButton(_("Search"))
        self.com_search_button.setToolTip(
            _("Search for the available serial ports.")
        )
        grbl_conn_grid.addWidget(self.com_list_label, 2, 0)
        grbl_conn_grid.addWidget(self.com_list_combo, 2, 1)
        grbl_conn_grid.addWidget(self.com_search_button, 2, 2)

        # BAUDRATES list
        self.baudrates_list_label = FCLabel('%s:' % _("Baud rates"))
        self.baudrates_list_label.setToolTip(
            _("Lists the available serial ports.")
        )

        self.baudrates_list_combo = FCComboBox()
        cb_model = QtCore.QStringListModel()
        self.baudrates_list_combo.setModel(cb_model)
        self.baudrates_list_combo.addItems(
            ['9600', '19200', '38400', '57600', '115200', '230400', '460800', '500000', '576000', '921600', '1000000',
             '1152000', '1500000', '2000000'])
        self.baudrates_list_combo.setCurrentText('115200')

        grbl_conn_grid.addWidget(self.baudrates_list_label, 4, 0)
        grbl_conn_grid.addWidget(self.baudrates_list_combo, 4, 1)

        # New baudrate
        self.new_bd_label = FCLabel('%s:' % _("New"))
        self.new_bd_label.setToolTip(
            _("New, custom baudrate.")
        )

        self.new_baudrate_entry = FCSpinner()
        self.new_baudrate_entry.set_range(40, 9999999)

        self.add_bd_button = FCButton(_("Add"))
        self.add_bd_button.setToolTip(
            _("Add the specified custom baudrate to the list.")
        )
        grbl_conn_grid.addWidget(self.new_bd_label, 6, 0)
        grbl_conn_grid.addWidget(self.new_baudrate_entry, 6, 1)
        grbl_conn_grid.addWidget(self.add_bd_button, 6, 2)

        self.del_bd_button = FCButton(_("Delete selected baudrate"))
        grbl_conn_grid.addWidget(self.del_bd_button, 8, 0, 1, 3)

        ctrl_h_lay = QtWidgets.QHBoxLayout()
        self.controller_reset_button = FCButton(_("Reset"))
        self.controller_reset_button.setToolTip(
            _("Software reset of the controller.")
        )
        self.controller_reset_button.setDisabled(True)
        ctrl_h_lay.addWidget(self.controller_reset_button)

        self.com_connect_button = FCButton()
        self.com_connect_button.setText(_("Disconnected"))
        self.com_connect_button.setToolTip(
            _("Connect to the selected port with the selected baud rate.")
        )
        self.com_connect_button.setStyleSheet("QPushButton {background-color: red;}")
        ctrl_h_lay.addWidget(self.com_connect_button)

        grbl_conn_grid.addWidget(FCLabel(""), 9, 0, 1, 3)
        grbl_conn_grid.setRowStretch(9, 1)
        grbl_conn_grid.addLayout(ctrl_h_lay, 10, 0, 1, 3)

        # #############################################################################################################
        # GRBL CONTROL
        # #############################################################################################################
        self.ctrl_grbl_frame = FCFrame()
        self.gr_ctrl_tab_layout.addWidget(self.ctrl_grbl_frame)
        grbl_ctrl_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 1, 0])
        self.ctrl_grbl_frame.setLayout(grbl_ctrl_grid)

        self.ctrl_grbl_frame2 = FCFrame()
        self.gr_ctrl_tab_layout.addWidget(self.ctrl_grbl_frame2)
        grbl_ctrl2_grid = GLay(v_spacing=5, h_spacing=3)
        self.ctrl_grbl_frame2.setLayout(grbl_ctrl2_grid)

        self.gr_ctrl_tab_layout.addStretch(1)

        jog_title_label = FCLabel(_("Jog"), bold=True)

        zero_title_label = FCLabel(_("Zero Axes"), bold=True)
        # zero_title_label.setStyleSheet("""
        #                         FCLabel
        #                         {
        #                             font-weight: bold;
        #                         }
        #                         """)

        grbl_ctrl_grid.addWidget(jog_title_label, 0, 0)
        grbl_ctrl_grid.addWidget(zero_title_label, 0, 2)

        self.jog_wdg = FCJog(self.app)
        self.jog_wdg.setStyleSheet("""
                            FCJog
                            {
                                border: 1px solid lightgray;
                                border-radius: 5px;
                            }
                            """)

        self.zero_axs_wdg = FCZeroAxes(self.app)
        self.zero_axs_wdg.setStyleSheet("""
                            FCZeroAxes
                            {
                                border: 1px solid lightgray;
                                border-radius: 5px
                            }
                            """)
        grbl_ctrl_grid.addWidget(self.jog_wdg, 2, 0)
        grbl_ctrl_grid.addWidget(self.zero_axs_wdg, 2, 2)

        self.pause_resume_button = RotatedToolButton()
        self.pause_resume_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum,
                                               QtWidgets.QSizePolicy.Policy.Expanding)
        self.pause_resume_button.setText(_("Pause/Resume"))
        self.pause_resume_button.setCheckable(True)
        self.pause_resume_button.setStyleSheet("""
                            RotatedToolButton:checked
                            {
                                background-color: red;
                                color: white;
                                border: none;
                            }
                            """)

        pause_frame = QtWidgets.QFrame()
        pause_frame.setContentsMargins(0, 0, 0, 0)
        pause_frame.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        pause_h_lay = QtWidgets.QHBoxLayout()
        pause_h_lay.setContentsMargins(0, 0, 0, 0)

        pause_h_lay.addWidget(self.pause_resume_button)
        pause_frame.setLayout(pause_h_lay)
        grbl_ctrl_grid.addWidget(pause_frame, 2, 1)

        # JOG Step
        self.jog_step_label = FCLabel('%s:' % _("Step"))
        self.jog_step_label.setToolTip(
            _("Each jog action will move the axes with this value.")
        )

        self.jog_step_entry = FCSliderWithDoubleSpinner()
        self.jog_step_entry.set_precision(self.decimals)
        self.jog_step_entry.setSingleStep(0.1)
        self.jog_step_entry.set_range(0, 500)

        grbl_ctrl2_grid.addWidget(self.jog_step_label, 0, 0)
        grbl_ctrl2_grid.addWidget(self.jog_step_entry, 0, 1)

        # JOG Feedrate
        self.jog_fr_label = FCLabel('%s:' % _("Feedrate"))
        self.jog_fr_label.setToolTip(
            _("Feedrate when jogging.")
        )

        self.jog_fr_entry = FCSliderWithDoubleSpinner()
        self.jog_fr_entry.set_precision(self.decimals)
        self.jog_fr_entry.setSingleStep(10)
        self.jog_fr_entry.set_range(0, 10000)

        grbl_ctrl2_grid.addWidget(self.jog_fr_label, 1, 0)
        grbl_ctrl2_grid.addWidget(self.jog_fr_entry, 1, 1)

        self.continuous_jog_cb = FCCheckBox(_("Continuous"))
        self.continuous_jog_cb.setToolTip(_("Hold a jog arrow to move. Release it to brake to a stop."))
        self.continuous_jog_cb.setChecked(False)
        self.continuous_jog_cb.hide()
        grbl_ctrl2_grid.addWidget(self.continuous_jog_cb, 2, 0, 1, 2)

        self.ecut_motion_button = FCButton(_("E-Cut settings"))
        self.ecut_motion_button.setToolTip(_("Motion, motor calibration, spindle and input/output settings."))
        self.ecut_motion_button.hide()
        grbl_ctrl2_grid.addWidget(self.ecut_motion_button, 3, 0, 1, 2)

        # #############################################################################################################
        # GRBL SENDER
        # #############################################################################################################
        self.sender_frame = FCFrame()
        self.gr_send_tab_layout.addWidget(self.sender_frame)

        grbl_send_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[1, 0])
        self.sender_frame.setLayout(grbl_send_grid)

        # Send CUSTOM COMMAND
        self.grbl_command_label = FCLabel('%s:' % _("Send Command"))
        self.grbl_command_label.setToolTip(
            _("Send a custom command to GRBL.")
        )
        grbl_send_grid.addWidget(self.grbl_command_label, 2, 0, 1, 2)

        self.grbl_command_entry = FCEntry()
        self.grbl_command_entry.setPlaceholderText(_("Type GRBL command ..."))

        self.grbl_send_button = QtWidgets.QToolButton()
        self.grbl_send_button.setText(_("Send"))
        self.grbl_send_button.setToolTip(
            _("Send a custom command to GRBL.")
        )
        grbl_send_grid.addWidget(self.grbl_command_entry, 4, 0)
        grbl_send_grid.addWidget(self.grbl_send_button, 4, 1)

        # Get Parameter
        self.grbl_get_param_label = FCLabel('%s:' % _("Get Config parameter"))
        self.grbl_get_param_label.setToolTip(
            _("A GRBL configuration parameter.")
        )
        grbl_send_grid.addWidget(self.grbl_get_param_label, 6, 0, 1, 2)

        self.grbl_parameter_entry = FCEntry()
        self.grbl_parameter_entry.setPlaceholderText(_("Type GRBL parameter ..."))

        self.grbl_get_param_button = QtWidgets.QToolButton()
        self.grbl_get_param_button.setText(_("Get"))
        self.grbl_get_param_button.setToolTip(
            _("Get the value of a specified GRBL parameter.")
        )
        grbl_send_grid.addWidget(self.grbl_parameter_entry, 8, 0)
        grbl_send_grid.addWidget(self.grbl_get_param_button, 8, 1)

        grbl_send_grid.setRowStretch(9, 1)

        # GET Report
        self.grbl_report_button = FCButton(_("Get Report"))
        self.grbl_report_button.setToolTip(
            _("Print in shell the GRBL report.")
        )
        grbl_send_grid.addWidget(self.grbl_report_button, 10, 0, 1, 2)

        hm_lay = QtWidgets.QHBoxLayout()
        # GET HEIGHT MAP
        self.grbl_get_heightmap_button = FCButton(_("Probe"))
        self.grbl_get_heightmap_button.setToolTip(
            _("Probe the points and make the height map.")
        )
        hm_lay.addWidget(self.grbl_get_heightmap_button, stretch=1)

        # STOP
        self.stop_probing_button = FCButton(_("Stop"))
        self.stop_probing_button.setToolTip(
            _("Stop the running GRBL operation now.\n"
              "GRBL goes into feed hold.\n"
              "Press Reset, then Home, before more motion.")
        )
        self.stop_probing_button.setStyleSheet("QPushButton {background-color: red; color: white;}")
        hm_lay.addWidget(self.stop_probing_button)

        self.grbl_save_height_map_button = QtWidgets.QToolButton()
        self.grbl_save_height_map_button.setIcon(QtGui.QIcon(self.app.resource_location + '/save_as.png'))
        self.grbl_save_height_map_button.setToolTip(
            _("Will save the GRBL height map.")
        )
        hm_lay.addWidget(self.grbl_save_height_map_button, stretch=0, alignment=Qt.AlignmentFlag.AlignRight)

        grbl_send_grid.addLayout(hm_lay, 12, 0, 1, 2)

        self.run_label = FCLabel('%s' % _("Job"), color='green', bold=True)
        self.tools_box.addWidget(self.run_label)
        run_frame = FCFrame()
        self.tools_box.addWidget(run_frame)
        run_grid = GLay(v_spacing=5, h_spacing=3)
        run_frame.setLayout(run_grid)

        self.start_button = FCButton(_("Start"), bold=True)
        self.start_button.setToolTip(_("Stream the G-code of the selected CNCJob to GRBL."))
        self.hold_button = FCButton(_("Hold"))
        self.hold_button.setToolTip(_("Feed hold. Resume continues the job."))
        self.resume_button = FCButton(_("Resume"))
        self.stop_button = FCButton(_("Stop"))
        self.stop_button.setStyleSheet("QPushButton {background-color: red; color: white;}")
        self.stop_button.setToolTip(_("Stop the job: feed hold, then a soft reset."))
        run_grid.addWidget(self.start_button, 0, 0)
        run_grid.addWidget(self.hold_button, 0, 1)
        run_grid.addWidget(self.resume_button, 0, 2)
        run_grid.addWidget(self.stop_button, 0, 3)

        self.unlock_button = FCButton(_("Unlock"))
        self.unlock_button.setToolTip(_("Send $X: clear the alarm lock."))
        self.sim_button = FCButton(_("Sim"))
        self.sim_button.setToolTip(_("Run the program with a virtual controller."))
        self.check_mode_cb = FCCheckBox(_("Check mode"))
        self.check_mode_cb.setToolTip(_("GRBL reads the G-code of the next Start but does not move (check mode for 1 job)."))
        run_grid.addWidget(self.unlock_button, 1, 0)
        run_grid.addWidget(self.sim_button, 1, 1)
        run_grid.addWidget(self.check_mode_cb, 1, 2, 1, 2)

        # the button shows the spindle state: it also changes when a command or a job starts or stops the spindle
        self.spindle_button = FCButton(_("Spindle"))
        self.spindle_button.setCheckable(True)
        self.spindle_button.setToolTip(_("Start the spindle clockwise (M3) with the RPM value, or stop it (M5).\n"
                                         "The button is ON while the spindle runs."))
        self.spindle_button.setStyleSheet("QPushButton:checked {background-color: green; color: white;}")
        self.spindle_rpm_entry = FCSpinner()
        self.spindle_rpm_entry.set_range(0, 100000)
        self.spindle_rpm_entry.set_step(1000)
        self.spindle_rpm_entry.set_value(10000)
        # no suffix: FCSpinner reads only the number from the text, so a ' RPM' suffix gives 0
        self.spindle_rpm_entry.setToolTip(_("The spindle speed for the Spindle button."))
        run_grid.addWidget(self.spindle_button, 2, 0, 1, 2)
        # the RPM field and its label share 2 columns: in 1 column the field was too narrow for its digits
        rpm_lay = QtWidgets.QHBoxLayout()
        rpm_lay.addWidget(self.spindle_rpm_entry, stretch=1)
        rpm_lay.addWidget(FCLabel(_("RPM")))
        run_grid.addLayout(rpm_lay, 2, 2, 1, 2)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        run_grid.addWidget(self.progress_bar, 3, 0, 1, 4)
        self.status_label = FCLabel(_("Idle"))
        run_grid.addWidget(self.status_label, 4, 0, 1, 4)

        # overrides: name, real-time byte
        self.ov_label = FCLabel('%s' % _("Overrides"), bold=True)
        run_grid.addWidget(self.ov_label, 5, 0, 1, 4)
        self.ov_buttons = {}
        ov_rows = [
            (_("Feed"), [('-10', b'\x92'), ('-1', b'\x94'), ('100%', b'\x90'), ('+1', b'\x93'), ('+10', b'\x91')]),
            (_("Rapid"), [('25%', b'\x97'), ('50%', b'\x96'), ('100%', b'\x95')]),
            (_("Spindle"), [('-10', b'\x9b'), ('-1', b'\x9d'), ('100%', b'\x99'), ('+1', b'\x9c'), ('+10', b'\x9a')]),
        ]
        for row_idx, (name, items) in enumerate(ov_rows, start=6):
            run_grid.addWidget(FCLabel('%s:' % name), row_idx, 0)
            h_lay = QtWidgets.QHBoxLayout()
            for text, byte in items:
                btn = QtWidgets.QToolButton()
                btn.setText(text)
                h_lay.addWidget(btn)
                self.ov_buttons[(name, text)] = (btn, byte)
            run_grid.addLayout(h_lay, row_idx, 1, 1, 3)
        self.ov_values_label = FCLabel('F: 100%  R: 100%  S: 100%')
        run_grid.addWidget(self.ov_values_label, 9, 0, 1, 4)

        self.save_levelled_button = FCButton(_("Save levelled G-code"))
        self.save_levelled_button.setIcon(QtGui.QIcon(self.app.resource_location + '/save_as.png'))
        self.save_levelled_button.setToolTip(_("Save the G-code that the sender streams, after the levelling."))
        run_grid.addWidget(self.save_levelled_button, 10, 0, 1, 4)

        self.view3d_button = FCButton(_("Show in Plot 3D"))
        self.view3d_button.setToolTip(_("Show the toolpath, the tool and the height map in the Plot 3D tab."))
        run_grid.addWidget(self.view3d_button, 11, 0, 1, 4)

        self.al_group_label = FCLabel('%s' % _("Autolevelling"), color='blue', bold=True)
        self.tools_box.addWidget(self.al_group_label)
        self.autolevel_frame = QtWidgets.QFrame()
        autolevel_box = QtWidgets.QVBoxLayout(self.autolevel_frame)
        autolevel_box.setContentsMargins(0, 0, 0, 0)
        self.tools_box.addWidget(self.autolevel_frame)
        self.autolevel_cb = FCCheckBox(_("Level the G-code"))
        self.autolevel_cb.setToolTip(_("Apply the height map to the G-code before streaming."))
        autolevel_box.addWidget(self.autolevel_cb)
        build_probe_points_ui(self, self.app, autolevel_box)
        self.tool_grid.removeWidget(self.plot_probing_pts_cb)
        self.tool_grid.addWidget(self.plot_probing_pts_cb, 2, 0)
        self.plot_height_map_cb = FCCheckBox(_("Plot height map"))
        self.plot_height_map_cb.setToolTip(_(
            "Show or hide the generated height-map surface in Plot 3D.\n"
            "This also applies to simulated height maps.\n"
            "Hiding the surface doesn't affect levelling."))
        self.plot_height_map_cb.setChecked(True)
        self.tool_grid.addWidget(self.plot_height_map_cb, 2, 1)
        self.avoid_exc_label = FCLabel('%s:' % _("Excellon Object"))
        self.avoid_exc_label.setToolTip(_("Avoid holes from this Excellon object when adding probe points."))
        self.avoid_exc_combo = FCComboBox()
        self.avoid_exc_combo.setModel(self.app.collection)
        self.avoid_exc_combo.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        self.avoid_exc_combo.setCurrentIndex(0)
        self.avoid_exc_combo.obj_type = "Excellon"
        self.tool_grid.addWidget(self.avoid_exc_holes_size_label, 8, 0)
        self.tool_grid.addWidget(self.avoid_exc_holes_size_entry, 8, 1)
        self.tool_grid.addWidget(self.avoid_exc_label, 5, 0, 1, 2)
        self.tool_grid.addWidget(self.avoid_exc_combo, 6, 0, 1, 2)
        self.avoid_exc_label.hide()
        self.avoid_exc_combo.hide()
        self.al_frame.setVisible(self.autolevel_cb.isChecked())
        self.autolevel_cb.toggled.connect(self.al_frame.setVisible)

        self.precision_probe_cb = FCCheckBox(_("Precision probing (two touches)"))
        self.precision_probe_cb.setToolTip(_(
            "GRBL only: retract after the coarse touch and probe again at the fine feed. "
            "Only the second measurement is used."))
        self.precision_probe_cb.set_value(False)
        self.al_box.addWidget(self.precision_probe_cb)
        precision_grid = GLay(v_spacing=5, h_spacing=3)
        self.al_box.addLayout(precision_grid)
        precision_grid.addWidget(FCLabel('%s:' % _("Fine probe feedrate")), 0, 0)
        self.precision_feed_entry = FCDoubleSpinner()
        self.precision_feed_entry.set_precision(max(self.decimals, 4))
        self.precision_feed_entry.set_range(0.0001, 910000.0)
        self.precision_feed_entry.set_value(10.0 if app.app_units.upper() == 'MM' else 10.0 / 25.4)
        self.precision_feed_entry.setEnabled(False)
        precision_grid.addWidget(self.precision_feed_entry, 0, 1)
        precision_grid.addWidget(FCLabel('%s:' % _("Precision retract")), 1, 0)
        self.precision_retract_entry = FCDoubleSpinner()
        self.precision_retract_entry.set_precision(max(self.decimals, 4))
        self.precision_retract_entry.set_range(0.0001, 910000.0)
        self.precision_retract_entry.setToolTip(_(
            "Distance above the coarse contact, in current units. "
            "Must release the probe without exceeding Probe Z travel."))
        self.precision_retract_entry.set_value(0.5 if app.app_units.upper() == 'MM' else 0.5 / 25.4)
        self.precision_retract_entry.setEnabled(False)
        precision_grid.addWidget(self.precision_retract_entry, 1, 1)

        self.tools_box.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.tools_box.addWidget(self.reset_button)

        GLay.set_common_column_size([self.tool_grid, self.param_grid], 0)

        def toggle_section(collapsed, label, frame, color):
            frame.setHidden(collapsed)
            label.color = 'gray' if collapsed else color

        for label, frame in ((self.obj_combo_label, self.source_frame),
                             (self.run_label, run_frame),
                             (self.al_group_label, self.autolevel_frame)):
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.clicked.connect(
                lambda collapsed, label=label, frame=frame, color=label.color:
                toggle_section(collapsed, label, frame, color)
            )

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' % (_("Edited value is out of range"),
                                                                                  self.decimals,
                                                                                  minval,
                                                                                  self.decimals,
                                                                                  maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)
