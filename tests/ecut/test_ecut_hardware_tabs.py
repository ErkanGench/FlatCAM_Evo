"""Hardware pages use snapshots and readback; they never access a controller."""
from copy import deepcopy
import importlib

from PyQt6 import QtCore, QtWidgets
import pytest

from appPlugins.Common.ecut.ecut_config import EcutBoardConfig


@pytest.fixture
def hardware():
    cfg = EcutBoardConfig().to_dict()
    cfg['future_option'] = {'retain': [1, 2]}
    cfg['inputs']['X_HOME'].update(enabled=True, pin=3, polarity=0)
    cfg['inputs']['X_LIMIT_MINUS'].update(enabled=True, pin=3, polarity=0)
    cfg['outputs']['SPINDLE_CW'].update(enabled=True, pin=0)
    return cfg


@pytest.fixture
def tabs(hardware):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    module = importlib.import_module('appPlugins.ToolGcodeSender.SenderEcutIO')
    widget = module.EcutHardwareTabs(hardware)
    yield widget
    widget.close()
    widget.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def fresh(**kwargs):
    state = dict(connected=True, age_s=0.01, inputs=0, outputs=0)
    state.update(kwargs)
    return state


def test_snapshot_preserves_unedited_fields_and_shared_switch_mapping(tabs, hardware):
    assert tabs.values() == hardware
    tabs.input_fields['X_HOME']['polarity'].setCurrentIndex(1)
    result = tabs.values()
    assert result['inputs']['X_HOME']['polarity'] == 1
    assert result['inputs']['X_LIMIT_MINUS']['pin'] == 3
    assert result['future_option'] == {'retain': [1, 2]}
    assert result['axes'] == hardware['axes']
    result['future_option']['retain'].append(3)
    assert hardware['future_option'] == {'retain': [1, 2]}


def test_raw_inputs_and_logical_active_follow_applied_polarity(tabs):
    tabs.update_io(fresh(inputs=8))
    assert tabs.input_leds[3].isChecked()
    assert not tabs.logical_leds['X_HOME'].isChecked()
    tabs.input_fields['X_HOME']['polarity'].setCurrentIndex(1)
    assert not tabs.logical_leds['X_HOME'].isChecked()
    tabs.load_settings(tabs.values())
    assert tabs.logical_leds['X_HOME'].isChecked()
    tabs.update_io(fresh(inputs=0))
    assert not tabs.input_leds[3].isChecked()
    assert not tabs.logical_leds['X_HOME'].isChecked()
    assert tabs.logical_leds['X_LIMIT_MINUS'].isChecked()


def test_manual_click_requests_physical_output_without_optimistic_state(tabs):
    requests = []
    tabs.output_requested.connect(lambda *args: requests.append(args))
    tabs.update_io(fresh())
    tabs.output_buttons[0].click()
    assert requests == [(0, True)]
    assert not tabs.output_buttons[0].isChecked()
    assert 'SPINDLE_CW' in tabs.output_buttons[0].text()
    tabs.update_io(fresh(outputs=1))
    assert tabs.output_buttons[0].isChecked()
    tabs.output_buttons[0].click()
    assert requests[-1] == (0, False)
    assert tabs.output_buttons[0].isChecked()
    tabs.output_buttons[7].click()
    assert requests[-1] == (7, True)


def test_loading_and_polling_never_request_outputs_or_mark_changed(tabs, hardware):
    requests, changes = [], []
    tabs.output_requested.connect(lambda *args: requests.append(args))
    tabs.changed.connect(lambda: changes.append(True))
    tabs.load_settings(deepcopy(hardware))
    tabs.update_io(fresh(outputs=255))
    tabs.update_io(fresh())
    assert requests == [] and changes == []


@pytest.mark.parametrize('state', [dict(connected=False, age_s=0, inputs=0, outputs=0),
                                 dict(connected=True, age_s=0.51, inputs=0, outputs=0),
                                 dict(connected=True, age_s=0, inputs=0, outputs=0, busy=True),
                                 {}])
def test_manual_outputs_require_fresh_idle_connection(tabs, state):
    tabs.update_io(state)
    assert all(not button.isEnabled() for button in tabs.output_buttons)


def test_busy_disables_configuration_but_keeps_actual_io_visible(tabs):
    tabs.update_io(fresh())
    tabs.set_busy(True)
    assert not tabs.input_fields['X_HOME']['enabled'].isEnabled()
    assert all(not button.isEnabled() for button in tabs.output_buttons)
    tabs.update_io(fresh(inputs=65535, outputs=255))
    assert tabs.input_leds[15].isChecked()
    assert tabs.output_buttons[7].isChecked()
    tabs.set_busy(False)
    assert tabs.output_buttons[7].isEnabled()


def test_unsupported_expansion_input_is_preserved_and_refused(tabs, hardware):
    hardware['inputs']['PROBE'].update(enabled=True, pin=20)
    tabs.load_settings(hardware)
    assert 'Unverified' in tabs.input_fields['PROBE']['pin'].currentText()
    with pytest.raises(ValueError, match='PROBE'):
        tabs.values()
    tabs.input_fields['PROBE']['enabled'].setChecked(False)
    assert tabs.values()['inputs']['PROBE']['pin'] == 20


def test_motor_changes_do_not_modify_tuning_or_imply_driver_power(tabs, hardware):
    tabs.axis_fields[0]['enabled'].setChecked(False)
    tabs.axis_fields[0]['step_pin'].setValue(12)
    result = tabs.values()
    assert not result['axes'][0]['enabled']
    assert result['axes'][0]['step_pin'] == 12
    assert result['axes'][0]['steps_per_mm'] == hardware['axes'][0]['steps_per_mm']
    assert 'software' in tabs.motor_note.text().lower()
    assert 'DIP' in tabs.motor_note.text()
    assert 'ENABLE1' in tabs.output_fields


def test_unverified_spindle_mode_is_not_silently_converted(tabs, hardware):
    hardware['spindle']['control'] = 2
    tabs.load_settings(hardware)
    with pytest.raises(ValueError, match='spindle'):
        tabs.values()
    tabs.spindle_fields['control'].setCurrentIndex(1)
    assert tabs.values()['spindle']['control'] == 1


def test_stale_indicator_is_unknown_instead_of_false_healthy(tabs):
    tabs.update_io(fresh(inputs=8))
    tabs.update_io(dict(connected=True, age_s=2, inputs=8, outputs=0))
    assert tabs.input_leds[3].property('io_state') == 'unknown'
    assert tabs.logical_leds['X_HOME'].property('io_state') == 'unknown'


def test_output_role_labels_keep_applied_mapping_until_saved(tabs):
    tabs.update_io(fresh())
    assert 'SPINDLE_CW' in tabs.output_buttons[0].text()
    tabs.output_fields['SPINDLE_CW']['pin'].setCurrentIndex(5)
    assert 'SPINDLE_CW' in tabs.output_buttons[0].text()
    assert 'SPINDLE_CW' not in tabs.output_buttons[5].text()
    tabs.load_settings(tabs.values())
    assert 'SPINDLE_CW' not in tabs.output_buttons[0].text()
    assert 'SPINDLE_CW' in tabs.output_buttons[5].text()


def test_new_enable_assignment_includes_all_output_defaults(tabs, hardware):
    assert 'ENABLE1' not in hardware['outputs']
    tabs.output_fields['ENABLE1']['enabled'].setChecked(True)
    assert tabs.values()['outputs']['ENABLE1'] == dict(enabled=True, pin=0, inverted=False)
    assert 'ENABLE2' not in tabs.values()['outputs']
