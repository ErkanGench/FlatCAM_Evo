"""Read-only USB status recovery never replays an ambiguous hardware write."""

from collections import deque
import errno
from types import SimpleNamespace

import pytest

from appPlugins.Common.ecut import EcutAPI, EcutUsb, EcutUsbError, State, Cmd
from appPlugins.Common.ecut.ecut_protocol import encode_motion_record
from test_ecut_verified import report


class Device:
    def __init__(self, reads=(), default=(), write_error=None, written=None):
        self.reads = deque(reads)
        self.default = default
        self.read_calls = []
        self.writes = []
        self.write_error = write_error
        self.written = written

    def read(self, size, timeout_ms):
        self.read_calls.append((size, timeout_ms))
        result = self.reads.popleft() if self.reads else self.default
        if isinstance(result, Exception):
            raise result
        return list(result)

    def write(self, packet):
        self.writes.append(packet)
        if self.write_error:
            raise self.write_error
        return len(packet) if self.written is None else self.written


def damaged(positions=(999999,) * 6):
    data = bytearray(report(positions))
    data[10] ^= 1
    return bytes(data)


def usb_with(device):
    usb = EcutUsb()
    usb._dev = device
    return usb


def test_corrupted_status_recovers_only_by_reading_a_fresh_valid_frame():
    device = Device([damaged(), report((1, 2, 3, 4, 5, 6))])
    usb = usb_with(device)
    assert usb.poll().axis_positions == (1, 2, 3, 4, 5, 6)
    assert len(device.read_calls) == 2
    assert device.writes == []
    assert usb.read_errors == 1
    assert usb.read_recoveries == 1


def test_intermittent_read_exception_recovers_and_retries_without_read_timeout():
    device = Device([OSError(errno.EIO, 'temporary read error'), report()])
    usb = usb_with(device)
    assert usb.recv(timeout_ms=25).crc_valid
    assert [timeout for _, timeout in device.read_calls] == [25, 0]
    assert device.writes == []
    assert usb.read_errors == 1
    assert usb.read_recoveries == 1


@pytest.mark.parametrize('failure', [damaged(), OSError(errno.EIO, 'temporary read error')])
def test_exhausted_read_recovery_raises_after_three_attempts(failure):
    device = Device(default=failure)
    usb = usb_with(device)
    with pytest.raises(EcutUsbError):
        usb.poll()
    assert len(device.read_calls) == 3
    assert usb.read_errors == 3
    assert usb.read_recoveries == 0
    assert not device.writes


@pytest.mark.parametrize('failure', [damaged(), OSError(errno.EIO, 'temporary read error')])
def test_empty_reads_after_a_bad_read_do_not_hide_the_pending_failure(failure):
    device = Device([failure, (), ()])
    usb = usb_with(device)
    with pytest.raises(EcutUsbError):
        usb.poll()
    assert len(device.read_calls) == 3
    assert not device.writes


def test_normal_empty_poll_is_still_immediate_and_returns_none():
    device = Device()
    usb = usb_with(device)
    assert usb.poll() is None
    assert device.read_calls == [(65, 0)]
    assert not device.writes


@pytest.mark.parametrize('code', [errno.ENODEV, errno.ENXIO, errno.EBADF])
def test_known_disconnection_is_fatal_without_retry_or_reconnect(code):
    device = Device([OSError(code, 'device disconnected'), report()])
    usb = usb_with(device)
    with pytest.raises(EcutUsbError):
        usb.poll()
    assert len(device.read_calls) == 1
    assert not device.writes


def test_bad_frame_never_updates_controller_position_or_calls_receiver():
    expected = (100, 200, 300, 400, 500, 600)
    api = EcutAPI()
    api._usb = usb_with(Device([damaged(), report(expected)]))
    api._state = State.IDLE
    observed = []
    api.on_rx_frame(observed.append)
    assert api.poll().axis_positions == expected
    assert api._last_rx.axis_positions == expected
    assert [frame.axis_positions for frame in observed] == [expected]


def test_recovered_fault_frame_is_published_without_reading_past_it():
    device = Device([damaged(), report(status=9), report(status=1)])
    usb = usb_with(device)
    assert usb.poll().estop_active
    assert len(device.read_calls) == 2
    assert len(device.reads) == 1


@pytest.mark.parametrize('operation', ['motion', 'stop'])
@pytest.mark.parametrize('failure', ['exception', 'short'])
def test_ambiguous_write_failure_is_never_replayed(operation, failure):
    device = Device(write_error=OSError(errno.EIO, 'ambiguous write') if failure == 'exception' else None,
                    written=5 if failure == 'short' else None)
    usb = usb_with(device)
    with pytest.raises(EcutUsbError):
        if operation == 'motion':
            usb.send_motion([encode_motion_record(0, [1, 0, 0, 0, 0, 0])])
        else:
            usb.cmd(Cmd.STOP)
    assert len(device.writes) == 1
    assert device.read_calls == []


@pytest.mark.parametrize('code', [6, 1167])
def test_windows_disconnected_handle_is_fatal_without_retry(code):
    error = OSError('Windows handle disconnected')
    error.winerror = code
    device = Device([error, report()])
    with pytest.raises(EcutUsbError):
        usb_with(device).poll()
    assert len(device.read_calls) == 1


def test_recovery_deadline_prevents_starting_a_late_retry(monkeypatch):
    from appPlugins.Common.ecut import ecut_protocol
    clock = iter([0.0, 0.051])
    waits = []
    monkeypatch.setattr(ecut_protocol, 'time', SimpleNamespace(
        monotonic=lambda: next(clock), sleep=waits.append))
    device = Device([damaged(), report()])
    with pytest.raises(EcutUsbError):
        usb_with(device).poll()
    assert len(device.read_calls) == 1
    assert waits == []


def test_empty_poll_never_waits_for_a_retry(monkeypatch):
    from appPlugins.Common.ecut import ecut_protocol
    waits = []
    monkeypatch.setattr(ecut_protocol, 'time', SimpleNamespace(
        monotonic=lambda: 0.0, sleep=waits.append))
    assert usb_with(Device()).poll() is None
    assert waits == []


def test_malformed_report_recovers_without_publishing_bad_position():
    device = Device([bytes(12), report((1,) * 6)])
    assert usb_with(device).poll().axis_positions == (1,) * 6
    assert len(device.read_calls) == 2


def test_exhausted_corruption_keeps_the_last_valid_controller_frame():
    from appPlugins.Common.ecut import decode_rx_report
    previous = decode_rx_report(report((123,) * 6))
    api = EcutAPI()
    api._usb = usb_with(Device(default=damaged()))
    api._state = State.IDLE
    api._last_rx = previous
    observed = []
    api.on_rx_frame(observed.append)
    with pytest.raises(EcutUsbError):
        api.poll()
    assert api._last_rx is previous
    assert observed == []


def test_valid_status_arriving_after_the_recovery_deadline_is_not_published(monkeypatch):
    from appPlugins.Common.ecut import ecut_protocol
    clock = iter([0.0, 0.001, 0.006, 0.100])
    monkeypatch.setattr(ecut_protocol, 'time', SimpleNamespace(
        monotonic=lambda: next(clock), sleep=lambda seconds: None))
    device = Device([damaged(), report()])
    usb = usb_with(device)
    with pytest.raises(EcutUsbError):
        usb.poll()
    assert len(device.read_calls) == 2
    assert usb.read_recoveries == 0


@pytest.mark.parametrize('failure', [damaged(), OSError(errno.EIO, 'temporary read error')])
def test_recovered_estop_status_latches_controller_and_healthy_status_cannot_clear_it(failure):
    from appPlugins.Common.ecut import EcutError
    device = Device([failure, report(status=9), report(status=1)])
    api = EcutAPI()
    api._usb = usb_with(device)
    api._state = State.RUNNING
    api._initialized = True
    api._running = True
    observed = []
    api.on_rx_frame(observed.append)
    assert api.poll().estop_active
    assert api.state == State.ESTOP
    assert len(device.read_calls) == 2
    assert len(observed) == 1 and observed[0].estop_active
    assert api.poll().estop_active is False
    assert api.state == State.ESTOP
    writes = len(device.writes)
    with pytest.raises(EcutError, match='Motion refused'):
        api._require_motion_allowed()
    assert len(device.writes) == writes
    assert all(packet[1] in (Cmd.ESTOP, Cmd.SET_OUTPUTS) for packet in device.writes)
