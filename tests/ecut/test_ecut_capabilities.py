"""Configuration and IO regressions from the plugin's packet builders."""
import struct

import pytest

from appPlugins.Common.ecut import EcutAPI, EcutBoardConfig, EcutError, SignalPolarity
from test_ecut_verified import Board, report
from appPlugins.Common.ecut import decode_rx_report


class IoBoard(Board):
    def __init__(self):
        super().__init__()
        self.outputs = 0
    def cmd(self, opcode, params=b''):
        super().cmd(opcode, params)
        if int(opcode) == 0xaf:
            mask, value = struct.unpack_from('>II', params, 4)
            self.outputs = (self.outputs & ~mask) | (value & mask)
    def poll(self):
        return decode_rx_report(report(tuple(self.positions), outputs=self.outputs))


def test_configuration_encodes_other_calibrations_and_smoothing():
    api = EcutAPI()
    api.config.interpolation_index = 3
    api.config.axes[0].steps_per_mm = 400
    api.config.axes[1].steps_per_mm = 200
    api.config.axes[2].steps_per_mm = 1600
    api.config.spindle.delay_between_pulse_and_dir_us = 25
    packets = api.encode_config()
    packet = next(packets[n:n+65] for n in range(0, len(packets), 65) if packets[n+1] == 0x9f)
    assert struct.unpack_from('>3i', packet, 6) == (400, 200, 1600)
    assert struct.unpack_from('>H', packet, 34) == (25,)
    assert struct.unpack_from('>I', packet, 36) == (0x00f02007,)
    assert packet[40:64] == bytes(24)  # no copied offsets from an unrelated Mach3 job


def test_limit_and_home_can_share_a_physical_input():
    api = EcutAPI()
    api.configure_input('X_LIMIT_MINUS', pin=3, polarity=SignalPolarity.ACTIVE_HIGH)
    api.configure_input('X_HOME', pin=3, polarity=SignalPolarity.ACTIVE_HIGH)
    api.configure_input('PROBE', pin=5, polarity=SignalPolarity.ACTIVE_HIGH)
    packets = api.encode_config()
    packet = next(packets[n:n+65] for n in range(0, len(packets), 65) if packets[n+1] == 0xa2)
    assert struct.unpack_from('>I', packet, 6) == (0x00400006,)
    assert packet[41:44] == bytes([3, 3, 0])  # reversed native group: signal2,1,0


def test_mpg_config_inversion_bits_follow_native_sdk_field_offsets():
    api = EcutAPI()
    api.config.axes[0].step_active_low = True
    api.config.axes[1].dir_active_low = True
    packets = api.encode_config()
    packet = next(packets[n:n+65] for n in range(0, len(packets), 65) if packets[n+1] == 0x9b)
    # FUN_100129a0: DirNegate at Engine+2805d => low bits;
    # StepNegate at Engine+2805c => high bits (AxisInfo SDK layout).
    assert struct.unpack_from('>H', packet, 34)[0] == 0x0102


def test_output_mask_preserves_unrelated_outputs_and_accepts_motion():
    api = EcutAPI()
    api._usb = IoBoard()
    api.configure_output('OUTPUT_0', pin=3)
    api.configure_output('OUTPUT_1', pin=5)
    api.push_config()
    api.set_output('OUTPUT_0', True)
    api.set_output('OUTPUT_1', True)
    assert api.read_output('OUTPUT_0') and api.read_output('OUTPUT_1')
    assert api._usb.outputs == 0x28
    api.run_gcode(['G91', 'G1 X0.001 F60', 'G1 X-0.001'])
    assert api._usb.outputs == 0x28
    api.set_output('OUTPUT_0', False)
    assert api._usb.outputs == 0x20
    api.stop()
    assert api._usb.outputs == 0


def test_input_negative_pin_is_refused_before_usb():
    api = EcutAPI()
    with pytest.raises((ValueError, EcutError)):
        api.configure_input('PROBE', pin=-1)


def test_initialization_snapshot_detects_changed_calibration():
    api = EcutAPI()
    api._usb = IoBoard()
    api.push_config()
    api.config.axes[0].steps_per_mm = 400
    before = len(api._usb.commands)
    with pytest.raises(EcutError, match='configuration|initializ'):
        api.jog_step(0, 0.001)
    assert len(api._usb.commands) == before


def test_configuration_roundtrip_keeps_routing_and_shared_inputs():
    config = EcutBoardConfig()
    config.step_functions = [6, 1, 2, 3, 4, 5, 0, 7]
    config.axes[1].step_active_low = True
    config.inputs['X_HOME'].enabled = True
    config.inputs['X_HOME'].pin = 4
    config.inputs['X_LIMIT_MINUS'].enabled = True
    config.inputs['X_LIMIT_MINUS'].pin = 4
    loaded = EcutBoardConfig.from_dict(config.to_dict())
    assert loaded.step_functions == [6, 1, 2, 3, 4, 5, 0, 7]
    assert loaded.axes[1].step_active_low
    assert loaded.inputs['X_HOME'].pin == loaded.inputs['X_LIMIT_MINUS'].pin


def test_inverted_output_is_inactive_after_initialization_and_stop():
    api = EcutAPI()
    api._usb = IoBoard()
    api.configure_output('OUTPUT_0', pin=2, inverted=True)
    api.push_config()
    assert not api.read_output('OUTPUT_0') and api._usb.outputs == 4
    api.set_output('OUTPUT_0', True)
    assert api.read_output('OUTPUT_0') and api._usb.outputs == 0
    api.stop()
    assert not api.read_output('OUTPUT_0') and api._usb.outputs == 4


def test_configured_limit_input_stops_and_latches_before_more_motion():
    from appPlugins.Common.ecut import State, ecut_crc60
    api = EcutAPI()
    api._usb = IoBoard()
    api.configure_input('X_LIMIT_PLUS', pin=2, polarity=SignalPolarity.ACTIVE_HIGH)
    api.push_config()
    data = bytearray(report(tuple(api.position_steps)))
    struct.pack_into('>H', data, 31, 4)
    struct.pack_into('>I', data, 61, ecut_crc60(data[1:61]))
    api._usb.poll = lambda: decode_rx_report(data)
    api.poll()
    assert api.state == State.ESTOP
    with pytest.raises(EcutError):
        api.jog_step(0, .001)


def test_soft_limit_rejection_sends_no_motion_packets():
    api = EcutAPI()
    api._usb = IoBoard()
    api.config.axes[0].soft_limits_enabled = True
    api.config.axes[0].soft_limit_negative_mm = -1
    api.config.axes[0].soft_limit_positive_mm = 1
    api.push_config()
    before = api._usb.positions[:]
    with pytest.raises(EcutError, match='[Ss]oft limit'):
        # farther outside the window than the start: refused (a move back inside is allowed)
        api.run_gcode(['G90', 'G1 X-30 F60'])
    assert api._usb.positions == before


def test_outputs_work_when_firmware_replaces_whole_bitmap():
    class FullBitmapBoard(IoBoard):
        def cmd(self, opcode, params=b''):
            super().cmd(opcode, params)
            if int(opcode) == 0xaf:
                self.outputs = int.from_bytes(params[8:12], 'big')
    api = EcutAPI()
    api._usb = FullBitmapBoard()
    api.configure_output('OUTPUT_0', pin=0)
    api.configure_output('OUTPUT_1', pin=15)
    api.push_config()
    api.set_output('OUTPUT_0', True)
    api.set_output('OUTPUT_1', True)
    assert api.read_output('OUTPUT_0') and api.read_output('OUTPUT_1')
    assert api._usb.outputs == 0x8001
