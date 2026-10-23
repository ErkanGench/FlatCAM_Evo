"""Finite jog braking and machine bounds after setting a work zero; no hardware."""
import struct

import pytest

from appPlugins.Common.ecut import State
from appPlugins.Common.ecut.ecut_gcode_engine import GcodeError
from test_ecut_gcode_engine import engine_api


def limited_engine():
    engine, api = engine_api()
    for axis in api.config.axes[:3]:
        axis.soft_limits_enabled = True
        axis.soft_limit_negative_mm = 0
        axis.soft_limit_positive_mm = 2
        axis.max_velocity_mm_s = 2
        axis.acceleration_mm_s2 = 1
    api.push_config()
    api._usb.events.clear()
    return engine, api


@pytest.mark.parametrize('axis,reverse', [(0, False), (0, True), (2, True)])
def test_finite_jog_brakes_to_machine_soft_limit_without_crossing_it(axis, reverse, monkeypatch):
    engine, api = limited_engine()
    name = 'XYZ'[axis]
    if reverse:
        engine.execute_line(f'G53 G0 {name}2')
    target = 0 if reverse else 2
    scale = abs(api._axis_scale(axis))
    position = api.position_steps[axis]
    deltas = []
    original = api._usb.send_motion

    def observe_records(records):
        deltas.extend(struct.unpack('>6h', record[4:16])[axis] for record in records)
        original(records)

    monkeypatch.setattr(api._usb, 'send_motion', observe_records)
    assert engine.execute_line(f'$J=G21 G90 {name}{target} F120') == ['ok']
    assert deltas
    for delta in deltas:
        position += delta
        assert 0 <= position <= round(2 * scale)
        assert delta <= 0 if reverse else delta >= 0
    assert position == round(target * scale)
    assert api.position_mm[axis] == pytest.approx(target)
    # Compare windows to tolerate integer step quantization in individual 1 ms records.
    speeds = [abs(delta) for delta in deltas]
    assert sum(speeds[-20:]) / 20 < max(speeds) / 2
    assert api.state == State.IDLE


@pytest.mark.parametrize('zero_command', ['G92 X0', 'G10 L20 P1 X0'])
def test_setting_work_zero_cannot_bypass_machine_soft_limits(zero_command):
    engine, api = limited_engine()
    engine.execute_line('G53 G0 X1')
    before = list(api._usb.positions)
    engine.execute_line(zero_command)
    assert api._usb.positions == before
    api._usb.events.clear()
    with pytest.raises(GcodeError, match='Soft limit'):
        engine.execute_line('$J=G21 G90 X1.1 F120')
    assert api._usb.events == []
    assert api._usb.positions == before


def test_soft_minimum_can_be_configured_at_the_chosen_work_zero():
    engine, api = limited_engine()
    engine.execute_line('G53 G0 X1')
    engine.execute_line('G92 X0')
    api.config.axes[0].soft_limit_negative_mm = 1
    api.push_config()
    api._usb.events.clear()
    with pytest.raises(GcodeError, match='Soft limit'):
        engine.execute_line('$J=G21 G90 X-.1 F120')
    assert api._usb.events == []
    engine.execute_line('$J=G21 G90 X1 F120')
    engine.execute_line('$J=G21 G90 X0 F120')
    assert api.position_mm[0] == pytest.approx(1)
    assert api.state == State.IDLE
