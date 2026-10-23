"""Spindle wire fixtures verified against unloaded SH-9001 DAC measurements."""
import struct
import time

import pytest

from appPlugins.Common.ecut import EcutBoardConfig, EcutError, SpindleControl
from appPlugins.Common.ecut import ecut_protocol
from appPlugins.Common.ecut import EcutAPI, EcutUsbError, State
from test_ecut_capabilities import IoBoard


def test_pwm_builder_matches_the_measured_half_scale_packet():
    builder = getattr(ecut_protocol, 'build_spindle_pwm_packet', None)
    assert callable(builder), 'Verified B0 PWM packet builder is missing'
    # Capture 31: 4.974 V; all step-drive and unused bytes zero.
    expected = bytes.fromhex(
        '00b0000000010000000000000000000000000000000000000000000000000000'
        '03e801f40000000000000000000000000000000000000000000000000000000000')
    assert builder(1000, 500) == expected


def test_raw_pwm_period_survives_configuration_roundtrip():
    config = EcutBoardConfig()
    config.spindle.pwm_period_counts = 2048
    restored = EcutBoardConfig.from_dict(config.to_dict())
    assert restored.spindle.to_dict().get('pwm_period_counts') == 2048


@pytest.mark.parametrize('field,value', [
    ('pwm_period_counts', 0), ('pwm_period_counts', 65536),
    ('pwm_period_counts', True), ('speed_rpm_min', -1),
    ('speed_rpm_max', 0), ('speed_rpm_max', float('nan')),
    ('dwell_on_seconds', -1), ('dwell_off_seconds', float('inf')),
    ('pulses_per_revolution', -1), ('pwm_frequency_hz', 2500),
])
def test_invalid_or_unverified_spindle_settings_are_rejected(field, value):
    config = EcutBoardConfig()
    config.spindle.control = SpindleControl.PWM
    setattr(config.spindle, field, value)
    with pytest.raises(EcutError):
        config.validate()


class SpindleBoard(IoBoard):
    def __init__(self):
        super().__init__()
        self.positions = [0] * 6
        self.events = []

    def cmd(self, opcode, params=b''):
        self.events.append(('cmd', int(opcode), bytes(params)))
        super().cmd(opcode, params)

    def send_motion(self, records):
        self.events.append(('motion',))
        super().send_motion(records)

    def close(self):
        self.is_open = False


def pwm_api():
    api = EcutAPI()
    api._usb = SpindleBoard()
    api._state = State.IDLE
    api.configure_spindle(SpindleControl.PWM, rpm_max=24000)
    for name, pin in [('SPINDLE_CW', 0), ('SPINDLE_CCW', 1)]:
        api.config.outputs[name].enabled = True
        api.config.outputs[name].pin = pin
    api.push_config()
    api._usb.commands.clear()
    api._usb.events.clear()
    return api


def pwm_values(api):
    return [struct.unpack_from('>H', params, 32)[0]
            for opcode, params in api._usb.commands if opcode == 0xb0]


def output_values(api):
    return [struct.unpack_from('>I', params, 8)[0]
            for opcode, params in api._usb.commands if opcode == 0xaf]


def test_start_uses_calibrated_duty_and_mapped_run_output():
    api = pwm_api()
    api.spindle_on_cw(6000)
    assert pwm_values(api)[-1] == 250
    assert api._usb.outputs == 1


def test_speed_word_is_pending_while_spindle_is_off():
    api = pwm_api()
    api.spindle_speed(6000)
    assert api._usb.commands == []
    api.spindle_on_cw(6000)
    api.spindle_speed(12000)
    assert pwm_values(api)[-1] == 500


def test_zero_speed_clears_run_and_dac_and_can_resume_selected_direction():
    api = pwm_api()
    api.spindle_on_cw(6000)
    api.spindle_speed(0)
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 0
    api.spindle_speed(12000)
    assert pwm_values(api)[-1] == 500
    assert api._usb.outputs == 1


def test_direction_reversal_breaks_old_run_output_before_new_one():
    api = pwm_api()
    api.spindle_on_cw(6000)
    api._usb.commands.clear()
    api.spindle_on_ccw(12000)
    values = output_values(api)
    assert 0 in values and values[-1] == 2
    assert 3 not in values


def test_spindle_off_preserves_coolant():
    api = pwm_api()
    api.config.outputs['FLOOD'].enabled = True
    api.config.outputs['FLOOD'].pin = 2
    api.push_config()
    api.flood_on()
    api.spindle_on_cw(6000)
    api.spindle_off()
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 4


@pytest.mark.parametrize('operation', ['stop', 'estop', 'reset', 'disconnect'])
def test_shutdown_paths_zero_the_dac_and_run_output(operation):
    api = pwm_api()
    api.spindle_on_cw(6000)
    api._usb.commands.clear()
    getattr(api, operation)()
    assert pwm_values(api)[-1] == 0
    assert output_values(api)[-1] == 0


def test_stop_uses_previous_polarity_even_if_configuration_is_mutated():
    api = pwm_api()
    api.spindle_on_cw(6000)
    api.config.outputs['SPINDLE_CW'].inverted = True
    api.config.spindle.pwm_period_counts = 0
    api.stop()
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 0


def test_stop_still_attempts_dac_and_run_off_if_motion_stop_write_fails():
    api = pwm_api()
    api.spindle_on_cw(6000)
    api._usb.commands.clear()
    original = api._usb.cmd

    def fail_stop(opcode, params=b''):
        original(opcode, params)
        if int(opcode) == 0xc8:
            raise EcutUsbError('injected stop failure')

    api._usb.cmd = fail_stop
    with pytest.raises(EcutError):
        api.stop()
    assert pwm_values(api)[-1] == 0
    assert output_values(api)[-1] == 0
    assert api.state == State.ERROR


def test_failed_run_activation_clears_dac_before_returning_error():
    api = pwm_api()
    original = api._usb.cmd

    def fail_active_output(opcode, params=b''):
        if int(opcode) == 0xaf and struct.unpack_from('>I', params, 8)[0] == 1:
            raise EcutUsbError('injected output failure')
        original(opcode, params)

    api._usb.cmd = fail_active_output
    with pytest.raises(EcutError):
        api.spindle_on_cw(6000)
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 0
    assert api.state == State.ERROR


@pytest.mark.parametrize('rpm', [-1, 24001, float('nan')])
def test_invalid_rpm_is_rejected_before_any_writes(rpm):
    api = pwm_api()
    with pytest.raises(EcutError):
        api.spindle_on_cw(rpm)
    assert api._usb.commands == []


@pytest.mark.parametrize('lines', [
    ['S6000', 'M3', 'S12000', 'M5', 'M30'],
    ['M3 S6000', 'M3 S12000', 'M5', 'M30'],
])
def test_gcode_spindle_words_execute_verified_packets(lines):
    api = pwm_api()
    api.run_gcode(lines)
    values = pwm_values(api)
    assert 250 in values and 500 in values and values[-1] == 0
    assert api._usb.outputs == 0


@pytest.mark.parametrize('line', ['M3 S25000', 'M3 M4 S6000', 'S1000 S2000'])
def test_invalid_spindle_program_is_rejected_before_earlier_motion(line):
    api = pwm_api()
    with pytest.raises(EcutError):
        api.run_gcode(['G0 X1', line])
    assert api._usb.events == []


def test_unconfigured_reverse_is_rejected_before_any_program_writes():
    api = pwm_api()
    api.config.outputs['SPINDLE_CCW'].enabled = False
    api.push_config()
    api._usb.events.clear()
    with pytest.raises(EcutError):
        api.run_gcode(['G0 X1', 'M4 S6000'])
    assert api._usb.events == []


def test_spindle_is_started_before_motion_in_the_same_block():
    api = pwm_api()
    api.run_gcode(['G0 X0.01 M3 S6000', 'M30'])
    events = api._usb.events
    on = next(i for i, item in enumerate(events) if item[:2] == ('cmd', 0xb0)
              and struct.unpack_from('>H', item[2], 32)[0] == 250)
    motion = next(i for i, item in enumerate(events) if item[0] == 'motion')
    assert on < motion


def test_step_dir_spindle_is_refused_before_initialization_writes():
    api = pwm_api()
    api.config.spindle.control = SpindleControl.STEP_DIR
    with pytest.raises(EcutError):
        api.push_config()
    assert api._usb.commands == []


def test_spindle_run_pin_cannot_be_held_by_an_enabled_alias():
    api = pwm_api()
    api.config.outputs['OUTPUT_0'].enabled = True
    api.config.outputs['OUTPUT_0'].pin = 0
    with pytest.raises(EcutError):
        api.push_config()
    assert api._usb.commands == []


def test_inverted_run_output_and_minimum_rpm_are_respected():
    api = pwm_api()
    api.config.outputs['SPINDLE_CW'].inverted = True
    api.config.spindle.speed_rpm_min = 3000
    api.push_config()
    assert api._usb.outputs == 1
    api.spindle_on_cw(6000)
    assert api._usb.outputs == 0
    api.spindle_off()
    assert api._usb.outputs == 1
    before = len(api._usb.commands)
    with pytest.raises(EcutError):
        api.spindle_on_cw(2999)
    assert len(api._usb.commands) == before


def test_status_loss_before_start_forces_all_outputs_off():
    api = pwm_api()
    api._wait_for_rx = lambda timeout: None
    with pytest.raises(EcutError):
        api.spindle_on_cw(6000)
    assert not any(pwm_values(api))
    assert api._usb.outputs == 0
    assert api.state == State.ERROR


def test_native_estop_status_clears_running_spindle():
    from test_ecut_verified import report
    from appPlugins.Common.ecut import decode_rx_report
    api = pwm_api()
    api.spindle_on_cw(6000)
    api._usb.poll = lambda: decode_rx_report(report(tuple(api._usb.positions), status=9, outputs=1))
    api.poll()
    assert api.state == State.ESTOP
    assert pwm_values(api)[-1] == 0
    assert output_values(api)[-1] == 0


def test_interlock_during_run_readback_cannot_return_success():
    from test_ecut_verified import report
    from appPlugins.Common.ecut import decode_rx_report
    api = pwm_api()
    original = api._usb.poll
    api._usb.poll = lambda: (decode_rx_report(report(tuple(api._usb.positions), status=9, outputs=1))
                            if api._usb.outputs == 1 else original())
    with pytest.raises(EcutError):
        api.spindle_on_cw(6000)
    assert api.state == State.ESTOP
    assert pwm_values(api)[-1] == 0
    assert output_values(api)[-1] == 0


def test_estop_during_dwell_aborts_and_clears_spindle():
    api = pwm_api()
    api.config.spindle.dwell_on_seconds = 0.1
    api.push_config()
    original = api._wait_for_rx

    def status_with_estop(timeout):
        if api._usb.outputs == 1:
            api.estop()
        return original(timeout)

    api._wait_for_rx = status_with_estop
    with pytest.raises(EcutError):
        api.spindle_on_cw(6000)
    assert api.state == State.ESTOP
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 0


def test_short_dwell_accepts_status_at_the_normal_report_interval():
    api = pwm_api()
    api.config.spindle.dwell_on_seconds = 0.005
    api.push_config()
    original = api._usb.poll
    next_report = time.monotonic()

    def periodic_status():
        nonlocal next_report
        if time.monotonic() < next_report:
            return None
        next_report = time.monotonic() + 0.01
        return original()

    api._usb.poll = periodic_status
    api.spindle_on_cw(6000)
    assert api._usb.outputs == 1
    assert api.state == State.IDLE


def test_poll_transport_fault_clears_a_running_spindle():
    api = pwm_api()
    api.spindle_on_cw(6000)

    def failed_status():
        raise EcutUsbError('injected CRC/transport failure')

    api._usb.poll = failed_status
    with pytest.raises(EcutError):
        api.poll()
    assert api.state == State.ERROR
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 0


def test_load_config_cannot_replace_an_open_transport(tmp_path):
    api = pwm_api()
    api.spindle_on_cw(6000)
    transport = api._usb
    with pytest.raises(EcutError, match='disconnect'):
        api.load_config(tmp_path / 'not_read_while_connected.json')
    assert api._usb is transport


def test_connect_cannot_replace_an_open_transport():
    api = pwm_api()
    with pytest.raises(EcutError, match='connected'):
        api.connect()


@pytest.mark.parametrize('program', [False, True])
def test_feed_hold_arriving_during_startup_clears_spindle(program):
    from test_ecut_verified import report
    from appPlugins.Common.ecut import decode_rx_report, ecut_crc60, SignalPolarity
    api = pwm_api()
    api.configure_input('FEED_HOLD', pin=2, polarity=SignalPolarity.ACTIVE_HIGH, debounce_ms=0)
    api.push_config()

    def hold_after_run_assertion():
        raw = bytearray(report(tuple(api._usb.positions), outputs=api._usb.outputs))
        struct.pack_into('>H', raw, 31, 4 if api._usb.outputs == 1 else 0)
        struct.pack_into('>I', raw, 61, ecut_crc60(raw[1:61]))
        return decode_rx_report(raw)

    api._usb.poll = hold_after_run_assertion
    with pytest.raises(EcutError):
        if program:
            api.run_gcode(['M3 S6000'])
        else:
            api.spindle_on_cw(6000)
    assert pwm_values(api)[-1] == 0
    assert api._usb.outputs == 0
