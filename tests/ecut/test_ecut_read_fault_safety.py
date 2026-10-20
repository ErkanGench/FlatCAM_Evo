"""A valid fault must survive status draining; persistent loss clears idle outputs."""
from dataclasses import replace

import pytest

from appPlugins.Common.ecut import State
from appPlugins.Common.ecut.ecut_protocol import EcutUsb, EcutUsbError, Cmd
from test_ecut_spindle import pwm_api


def test_status_drain_latches_valid_estop_before_later_safe_report():
    api = pwm_api()
    normal = api.last_rx_frame

    class Reports(EcutUsb):
        def __init__(self):
            self.frames = [replace(normal,status=9), normal]
            self.commands = []

        @property
        def is_open(self):
            return True

        def recv(self,timeout_ms=100):
            return self.frames.pop(0) if self.frames else None

        def cmd(self,opcode,params=b''):
            self.commands.append((opcode,params))

    api._usb = Reports()
    api._drain_rx()
    assert api.state == State.ESTOP
    assert any(opcode == Cmd.STOP for opcode,_ in api._usb.commands)
    assert api.last_rx_frame == normal


def test_persistent_status_failure_clears_idle_gpio_without_pwm_ownership(monkeypatch):
    api = pwm_api()
    api.configure_output('FLOOD',pin=2)
    api.push_config()
    api.flood_on()
    api._spindle_pwm_owned = False
    assert api._usb.outputs == 4

    def failed():
        raise EcutUsbError('Persistent status failure')

    monkeypatch.setattr(api._usb,'poll',failed)
    with pytest.raises(EcutUsbError):
        api.poll()
    assert api.state == State.ERROR
    assert not api._initialized
    assert api._usb.outputs == 0
