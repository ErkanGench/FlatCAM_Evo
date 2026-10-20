"""Motion tuning through the existing API and E-Cut sender settings channel."""
import pytest

from appPlugins.Common.ecut.ecut_gcode_engine import EcutGcodeEngine, GcodeError
from test_ecut_gcode_engine import engine_api


def test_api_axis_tuning_supports_braking_and_reset_to_acceleration():
    _, api = engine_api()
    api.configure_axis(0, acceleration=4, deceleration=1)
    assert api.config.axes[0].effective_deceleration_mm_s2 == 1
    api.configure_axis(0, deceleration=0)
    assert api.config.axes[0].deceleration_mm_s2 is None
    assert api.config.axes[0].effective_deceleration_mm_s2 == 4


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '1', 10**1000])
def test_api_rejects_invalid_braking_before_mutating_configuration(value):
    _, api = engine_api()
    before = api.config.to_dict()
    with pytest.raises(ValueError):
        api.configure_axis(0, max_velocity=1, deceleration=value)
    assert api.config.to_dict() == before


@pytest.mark.parametrize('axis', range(4))
def test_deceleration_is_a_host_only_setting_and_does_not_write_usb(axis):
    engine, api = engine_api()
    api._usb.events.clear()
    assert engine.execute_line(f'${140+axis}=2.5') == ['ok']
    assert api.config.axes[axis].deceleration_mm_s2 == 2.5
    assert api._usb.events == []
    api._require_motion_allowed()
    assert f'${140+axis}=2.5' in engine.execute_line('$$')
    engine.execute_line(f'${140+axis}=0')
    assert api.config.axes[axis].deceleration_mm_s2 is None
    api._require_motion_allowed()


def test_fourth_axis_velocity_acceleration_and_calibration_are_configurable():
    engine, api = engine_api()
    engine.execute_line('$103=800')
    engine.execute_line('$113=6')
    engine.execute_line('$123=.75')
    engine.execute_line('$143=.2')
    axis = api.config.axes[3]
    assert axis.steps_per_mm == 800
    assert axis.max_velocity_mm_s == pytest.approx(.1)
    assert axis.acceleration_mm_s2 == .75
    assert axis.effective_deceleration_mm_s2 == .2


def test_independent_braking_persists_through_sender_settings(tmp_path):
    _, api = engine_api()
    path = tmp_path / 'gcode_settings.json'
    engine = EcutGcodeEngine(api, settings_path=path)
    engine.execute_line('$140=.75')
    _, replacement = engine_api()
    restored = EcutGcodeEngine(replacement, settings_path=path)
    assert replacement.config.axes[0].deceleration_mm_s2 == .75
    assert restored.settings[140] == .75


def test_host_braking_setting_cannot_hide_an_uninitialized_axis_change():
    engine, api = engine_api()
    api.config.axes[1].steps_per_mm += 1
    engine.execute_line('$140=2')
    with pytest.raises(Exception, match='Configuration changed'):
        api._require_motion_allowed()
