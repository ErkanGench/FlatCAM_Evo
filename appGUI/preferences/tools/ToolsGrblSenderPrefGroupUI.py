
from PyQt6 import QtWidgets

from appGUI.GUIElements import FCDoubleSpinner, FCSpinner, RadioSet, FCLabel, FCComboBox, GLay, FCFrame, FCCheckBox
from appGUI.preferences.OptionsGroupUI import OptionsGroupUI

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ToolsGrblSenderPrefGroupUI(OptionsGroupUI):
    def __init__(self, app, parent=None):
        super(ToolsGrblSenderPrefGroupUI, self).__init__(self, parent=parent)

        self.setTitle(str(_("GRBL Sender Plugin")))
        self.decimals = app.decimals
        self.options = app.options

        self.grbl_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.grbl_label.setToolTip(
            _("Send the CNC Code to a GRBL controller.")
        )
        self.layout.addWidget(self.grbl_label)

        # #############################################################################################################
        # Parameters Frame
        # #############################################################################################################
        par_frame = FCFrame()
        self.layout.addWidget(par_frame)

        par_grid = GLay(v_spacing=5, h_spacing=3)
        par_frame.setLayout(par_grid)

        # JOG Step
        self.jog_step_label = FCLabel('%s:' % _("Step"))
        self.jog_step_label.setToolTip(
            _("Each jog action will move the axes with this value.")
        )

        self.jog_step_entry = FCDoubleSpinner()
        self.jog_step_entry.set_precision(self.decimals)
        self.jog_step_entry.set_range(0, 910000.0000)

        par_grid.addWidget(self.jog_step_label, 0, 0)
        par_grid.addWidget(self.jog_step_entry, 0, 1)

        # JOG Feedrate
        self.jog_fr_label = FCLabel('%s:' % _("Feedrate"))
        self.jog_fr_label.setToolTip(
            _("Feedrate when jogging.")
        )

        self.jog_fr_entry = FCDoubleSpinner()
        self.jog_fr_entry.set_precision(self.decimals)
        self.jog_fr_entry.set_range(0, 910000.0000)

        par_grid.addWidget(self.jog_fr_label, 2, 0)
        par_grid.addWidget(self.jog_fr_entry, 2, 1)

        # JOG Travel Z
        self.jog_travelz_label = FCLabel('%s:' % _("Travel Z"))
        self.jog_travelz_label.setToolTip(
            _("Safe height (Z) distance when jogging to origin.")
        )

        self.jog_travelz_entry = FCDoubleSpinner()
        self.jog_travelz_entry.set_precision(self.decimals)
        self.jog_travelz_entry.set_range(0, 910000.0000)

        par_grid.addWidget(self.jog_travelz_label, 4, 0)
        par_grid.addWidget(self.jog_travelz_entry, 4, 1)

        # Baud rate
        self.baudrate_label = FCLabel('%s:' % _("Baud rate"))
        self.baudrate_label.setToolTip(
            _("The baud rate that is selected for the serial connection.")
        )

        self.baudrate_combo = FCComboBox()
        self.baudrate_combo.addItems(
            ['9600', '19200', '38400', '57600', '115200', '230400', '460800', '500000', '576000', '921600', '1000000',
             '1152000', '1500000', '2000000'])

        par_grid.addWidget(self.baudrate_label, 6, 0)
        par_grid.addWidget(self.baudrate_combo, 6, 1)

        # Arc mode
        self.arc_mode_label = FCLabel('%s:' % _("Arcs"))
        self.arc_mode_label.setToolTip(
            _("Split: the sender splits G2/G3 arcs into G1 lines.\n"
              "Send: the sender sends G2/G3 to GRBL.\n"
              "With autolevelling on, arcs are always split.")
        )

        self.arc_mode_radio = RadioSet(
            [
                {'label': _('Split'), 'value': 'split'},
                {'label': _('Send'), 'value': 'send'}
            ])
        self.arc_mode_radio.setToolTip(self.arc_mode_label.toolTip())

        par_grid.addWidget(self.arc_mode_label, 8, 0)
        par_grid.addWidget(self.arc_mode_radio, 8, 1)

        # Arc segment
        self.arc_segment_label = FCLabel('%s:' % _("Arc segment"))
        self.arc_segment_label.setToolTip(
            _("The length of the G1 lines that replace an arc.")
        )

        self.arc_segment_entry = FCDoubleSpinner()
        self.arc_segment_entry.set_precision(self.decimals)
        self.arc_segment_entry.set_range(0.001, 100.0000)

        par_grid.addWidget(self.arc_segment_label, 10, 0)
        par_grid.addWidget(self.arc_segment_entry, 10, 1)

        # Segment length
        self.seg_len_label = FCLabel('%s:' % _("Segment length"))
        self.seg_len_label.setToolTip(
            _("Longest G1 line when the G-code is not segmented.\n"
              "Used only with autolevelling.")
        )

        self.seg_len_entry = FCDoubleSpinner()
        self.seg_len_entry.set_precision(self.decimals)
        self.seg_len_entry.set_range(0.001, 1000.0000)
        self.seg_len_entry.setToolTip(self.seg_len_label.toolTip())

        par_grid.addWidget(self.seg_len_label, 12, 0)
        par_grid.addWidget(self.seg_len_entry, 12, 1)

        # Status interval
        self.status_ms_label = FCLabel('%s:' % _("Status interval (ms)"))
        self.status_ms_label.setToolTip(
            _("How often the sender asks GRBL for a status report.")
        )

        self.status_ms_entry = FCSpinner()
        self.status_ms_entry.set_range(50, 2000)

        par_grid.addWidget(self.status_ms_label, 14, 0)
        par_grid.addWidget(self.status_ms_entry, 14, 1)

        self.layout.addStretch(1)
