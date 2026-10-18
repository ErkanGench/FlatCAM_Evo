"""Calibration controls shared by the solder-paste plugin and Preferences."""
from PyQt6 import QtWidgets, QtCore

from appGUI.GUIElements import FCLabel, FCComboBox, FCDoubleSpinner, FCCheckBox, GLay
from appCommon.solderpaste import CONTROLLERS, PREFIX
from defaults import AppDefaults

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class SolderPasteSettings(QtWidgets.QTabWidget):
    changed = QtCore.pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.fields = {}
        self.labels = {}
        groups = (
            (_('Hardware'), (
                ('controller', _('Controller'), CONTROLLERS, _('Select the controller dialect.')),
                ('drive', _('Syringe drive'), ('Motor', 'Stepper'), _('Motor uses M3/M4 and S; Stepper uses a dedicated extrusion axis.')),
                ('axis', _('Extrusion axis'), ('A', 'B', 'C', 'E'), _('A/B/C for CNC controllers. Marlin needs linear E. Stock GRBL has no extra axis.')),
                ('axis_mode', _('Axis units'), ('Rotary', 'Linear'), _('Rotary: degrees of motor rotation. Linear: millimetres of plunger motion (job units in the code).')),
                ('mach3_dwell', _('Mach3 dwell units'), ('Seconds', 'Milliseconds'), _('Match the Mach3 G04 dwell configuration. UI times are always seconds.')),
                ('grbl_mode', _('GRBL mode'), ('Spindle', 'Laser'), _('Select the actual $32 setting. Paste dispensing requires Spindle ($32=0).')),
                ('marlin_cold', _('Marlin cold extrusion'), None, _('Confirm firmware permits cold extrusion and E steps/mm are calibrated for the syringe. No heater is enabled.')),
            )),
            (_('Quantity'), (
                ('volume_mode', _('Dose calculation'), ('Thickness', 'Fixed volume', 'Legacy'), _('Thickness × pad area, fixed microlitres per pad, or the old uncalibrated cycle.')),
                ('thickness', _('Paste thickness'), ' mm', _('Target wet paste thickness. Physical millimetres, independent of project units.')),
                ('volume', _('Volume per pad'), ' uL', _('One microlitre equals one cubic millimetre. Raster strokes share this pad dose.')),
                ('flow_rate', _('Measured flow'), ' uL/s', _('Measure delivered volume / seconds at Forward speed for this nozzle and paste. Zero means not calibrated.')),
                ('calibration', _('Dose correction'), ' x', _('Commanded dose multiplier. Increase if measured delivery is below the target.')),
                ('syringe_dia', _('Syringe internal diameter'), ' mm', _('Physical bore diameter used to convert volume into plunger travel.')),
                ('pitch', _('Screw pitch'), ' mm/rev', _('Plunger movement per screw revolution. Used for a rotary motor axis.')),
                ('gear_ratio', _('Motor turns / screw turn'), ' x', _('Gear reduction: motor revolutions required for one screw revolution.')),
                ('plunger_feed', _('Maximum plunger speed'), ' mm/min', _('Physical plunger speed limit for stepper dispensing and retraction.')),
            )),
            (_('Placement'), (
                ('placement', _('Pad placement'), ('Auto', 'Line', 'Raster', 'Dot'), _('Auto fills wide pads with raster strokes and uses dots when a line cannot fit.')),
                ('overlap', _('Raster overlap'), ' %', _('Overlap between adjacent nozzle-width strokes. Higher values produce more strokes.')),
                ('dot_dia', _('Dot footprint'), '', _('Measured deposited dot diameter, in project units. A dot must fit inside the pad.')),
            )),
            (_('Cycle'), (
                ('prime', _('Prime volume'), ' uL', _('Volume delivered at the start of each line, deducted from its dose. Leave zero unless needed.')),
                ('retract', _('Plunger retract'), ' mm', _('Stepper anti-drip retraction in physical plunger millimetres; recovered at the next pad.')),
                ('z_rise', _('Slow Z approach'), None, _('Approach via Z Start at Z Dispense feed. The motor stays off until Dispense Z. Disabled for a faster normal cycle.')),
            )),
        )
        grids = []
        for title, specifications in groups:
            page = QtWidgets.QWidget()
            grid = GLay(v_spacing=5, h_spacing=3)
            page.setLayout(grid)
            grids.append(grid)
            for row, (name, text, choices, tip) in enumerate(specifications):
                label = FCLabel(text + ':')
                label.setToolTip(tip)
                if isinstance(choices, tuple):
                    widget = FCComboBox()
                    widget.addItems(choices)
                elif choices is None:
                    widget = FCCheckBox()
                else:
                    widget = FCDoubleSpinner(suffix=choices)
                    widget.set_precision(max(app.decimals, 6))
                    widget.set_range(0.0, 1000000.0)
                    widget.setSingleStep(0.01)
                widget.setToolTip(tip)
                key = PREFIX + name
                widget.set_value(app.options.get(key, AppDefaults.factory_defaults[key]))
                self.fields[key] = widget
                self.labels[name] = label
                grid.addWidget(label, row, 0)
                grid.addWidget(widget, row, 1)
                if isinstance(widget, FCComboBox):
                    widget.currentIndexChanged.connect(lambda: self.changed.emit())
                elif isinstance(widget, FCCheckBox):
                    widget.toggled.connect(lambda: self.changed.emit())
                else:
                    widget.editingFinished.connect(self.changed.emit)
            grid.setRowStretch(len(specifications), 1)
            self.addTab(page, title)
        self.changed.connect(self.refresh)
        self.notice = FCLabel('')
        self.notice.setWordWrap(True)
        grids[0].addWidget(self.notice, 7, 0, 1, 2)
        self.refresh()

    def bind_cycle_controls(self, ui):
        self.cycle_ui = ui
        ui.speedfwd_label.setText(_('Motor forward speed') + ':')
        ui.speedrev_label.setText(_('Motor reverse speed') + ':')
        ui.dwellfwd_label.setText(_('Legacy prime time (s)') + ':')
        ui.dwellrev_label.setText(_('Reverse time (s)') + ':')
        self.refresh()

    def refresh(self):
        value = lambda name: self.fields[PREFIX + name].get_value()
        legacy = value('volume_mode') == 'Legacy'
        motor = value('drive') == 'Motor'
        controller = value('controller')
        enabled = {
            'controller': not legacy, 'drive': not legacy,
            'axis': not legacy and not motor,
            'axis_mode': not legacy and not motor,
            'mach3_dwell': controller == 'Mach3',
            'grbl_mode': not legacy and controller == 'GRBL',
            'marlin_cold': not legacy and not motor and controller == 'Marlin',
            'thickness': value('volume_mode') == 'Thickness',
            'volume': value('volume_mode') == 'Fixed volume',
            'flow_rate': not legacy and motor,
            'calibration': not legacy,
            'syringe_dia': not legacy and not motor,
            'pitch': not legacy and not motor and value('axis_mode') == 'Rotary',
            'gear_ratio': not legacy and not motor and value('axis_mode') == 'Rotary',
            'plunger_feed': not legacy and not motor,
            'placement': not legacy,
            'overlap': not legacy and value('placement') in ('Auto', 'Raster'),
            'dot_dia': not legacy and value('placement') in ('Auto', 'Dot'),
            'prime': not legacy, 'retract': not legacy and not motor, 'z_rise': not legacy,
        }
        for name, state in enabled.items():
            self.fields[PREFIX + name].setEnabled(state)
            self.labels[name].setEnabled(state)
        if controller == 'GRBL':
            self.notice.setText(_('Stock GRBL supports the spindle motor only. Configure $32=0 and select Spindle mode.'))
        elif controller == 'Marlin' and not motor:
            self.notice.setText(_('Select E / Linear. Configure cold extrusion and E steps per plunger millimetre in firmware.'))
        elif motor and not legacy:
            self.notice.setText(_('Enter the measured flow at the selected forward speed for each nozzle. No flow is assumed.'))
        else:
            self.notice.setText(_('Use a dedicated motor axis. Rotary uses screw pitch and gear ratio; linear uses plunger travel.'))
        if hasattr(self, 'cycle_ui'):
            states = {'z_start_entry': legacy or value('z_rise'), 'z_start_label': legacy or value('z_rise'),
                      'z_stop_entry': legacy, 'z_stop_label': legacy,
                      'frz_dispense_entry': legacy or value('z_rise'),
                      'frz_dispense_label': legacy or value('z_rise'),
                      'dwellfwd_entry': legacy, 'dwellfwd_label': legacy,
                      'speedfwd_entry': legacy or motor, 'speedfwd_label': legacy or motor,
                      'speedrev_entry': legacy or motor, 'speedrev_label': legacy or motor,
                      'dwellrev_entry': legacy or motor, 'dwellrev_label': legacy or motor,
                      'pp_combo': legacy}
            for name, state in states.items():
                getattr(self.cycle_ui, name).setEnabled(state)
