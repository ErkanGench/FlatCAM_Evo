"""Continuous jog ownership, cancellation and lost GUI heartbeat."""
import threading
import time

import pytest
import serial

from appPlugins.Common.ecut import State
from appPlugins.Common.ecut.ecut_sender_port import EcutSenderPort
from test_ecut_sender_port import FakeAPI, FakeEngine, wait_for


class JogAPI(FakeAPI):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.braking = threading.Event()
        self.drained = threading.Event()
        self.release_drain = threading.Event()
        self.jogs = []

    def jog_start(self, axis, direction=0, feed_mm_min=None, *, should_continue=None):
        self.record('jog')
        self.jogs.append((axis, direction, feed_mm_min))
        self.state = State.RUNNING
        self.entered.set()
        while should_continue():
            self._planning_checkpoint()
            time.sleep(0.001)
        self.braking.set()
        while not self.release_drain.is_set():
            self._planning_checkpoint()
            time.sleep(0.001)
        self.state = State.IDLE
        self.drained.set()

    def jog_stop(self):
        self.record('jog_stop')


@pytest.fixture
def jogging_port():
    api = JogAPI()
    engine = FakeEngine(api)
    port = EcutSenderPort(api=api, engine=engine, timeout=0.04)
    port.readline()
    wait_for(lambda: not port._startup_pending and not port._active)
    yield port, api, engine
    api.release_drain.set()
    port.close()


def test_release_before_worker_consumes_start_never_moves(jogging_port):
    port, api, engine = jogging_port
    with port._condition:
        port.start_jog(0, 0, 60)
        port.stop_jog()
    wait_for(lambda: not port.jogging)
    assert not api.jogs
    assert not engine.controls


def test_release_brakes_and_reports_jog_until_measured_idle(jogging_port):
    port, api, engine = jogging_port
    port.start_jog(1, 1, 120)
    assert api.entered.wait(1)
    port.stop_jog()
    assert api.braking.wait(1)
    assert port.jogging
    port.write(b'?')
    assert port.readline().startswith(b'<Jog|')
    with pytest.raises(serial.SerialException):
        port.write(b'G1X1\n')
    with pytest.raises(serial.SerialException):
        port.prepare_program(['G21'])
    api.release_drain.set()
    wait_for(lambda: not port.jogging)
    port.write(b'?')
    assert port.readline().startswith(b'<Idle|')
    assert api.jogs == [(1, 1, 120)]
    assert {ident for _, ident in api.calls} == {port._worker.ident}


def test_missing_gui_heartbeat_brakes_without_another_command(jogging_port):
    port, api, engine = jogging_port
    port.JOG_LEASE_SECONDS = 0.04
    port.start_jog(0, 0, 60)
    assert api.entered.wait(1)
    for _ in range(3):
        time.sleep(0.015)
        assert port.refresh_jog()
        assert not api.braking.is_set()
    assert api.braking.wait(0.2)
    assert not port.refresh_jog()


@pytest.mark.parametrize('control', [b'\x85', b'!', b'!~'])
def test_jog_cancel_and_hold_drain_without_hard_stop_or_resume(jogging_port, control):
    port, api, engine = jogging_port
    port.start_jog(2, 0, 60)
    assert api.entered.wait(1)
    port.write(control)
    assert api.braking.wait(1)
    assert port.jogging
    assert not any(name == 'stop' for name, _ in api.calls)
    assert engine.controls == []
    api.release_drain.set()
    wait_for(lambda: not port.jogging)
    assert len(api.jogs) == 1


@pytest.mark.parametrize('busy', ['check', 'active', 'partial', 'prepared', 'state'])
def test_start_rejects_conflicting_controller_work(jogging_port, busy):
    port, api, engine = jogging_port
    with port._condition:
        if busy == 'check':
            engine.check_mode = True
        elif busy == 'active':
            port._active = True
        elif busy == 'partial':
            port._partial.extend(b'G')
        elif busy == 'prepared':
            port._prepared_job = object()
        else:
            api.state = State.RUNNING
        with pytest.raises(serial.SerialException):
            port.start_jog(0, 0, 60)
        port._active = False
        port._partial.clear()
        port._prepared_job = None
        api.state = State.IDLE
    assert not api.jogs


@pytest.mark.parametrize('axis,direction,feed', [(True, 0, 60), (6, 0, 60), (0, 2, 60),
                                               (0, 0, 0), (0, 0, float('nan'))])
def test_invalid_continuous_request_is_rejected_before_worker(jogging_port, axis, direction, feed):
    port, api, _ = jogging_port
    with pytest.raises(ValueError):
        port.start_jog(axis, direction, feed)
    assert not api.jogs
