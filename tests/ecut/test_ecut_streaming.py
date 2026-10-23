"""Flow control follows the plugin's refill gate, without intermediate drains."""
from dataclasses import replace

import pytest

from appPlugins.Common.ecut import EcutError, EcutBoardConfig
from test_ecut_spindle import pwm_api


def test_long_path_drains_only_at_final_target(monkeypatch):
    api = pwm_api()
    waits = []
    monkeypatch.setattr(api, '_wait_for_motion', lambda timeout: waits.append(tuple(api.position_steps)))
    api._submit_segments([(1,0,0,0,0,0)]*80)
    assert waits == [(80,0,0,0,0,0)]


def test_no_motion_sent_until_fresh_fifo_exceeds_native_threshold(monkeypatch):
    api = pwm_api()
    original = api.poll
    samples = []
    values = iter([6000,7000,7001])

    def poll():
        free = next(values, 12000)
        if free <= 7000:
            assert not any(event[0]=='motion' for event in api._usb.events)
        samples.append(free)
        return replace(original(), field_790=free)

    monkeypatch.setattr(api, 'poll', poll)
    api._submit_segments([(1,0,0,0,0,0)]*8)
    assert samples[:3] == [6000,7000,7001]


def test_absent_status_refuses_before_motion_submission(monkeypatch):
    api = pwm_api()
    monkeypatch.setattr(api, 'poll', lambda: None)
    with pytest.raises(EcutError, match='FIFO|status'):
        api._submit_segments([(1,0,0,0,0,0)]*8)
    assert not any(event[0]=='motion' for event in api._usb.events)


def test_junction_deviation_configuration_roundtrips():
    cfg = EcutBoardConfig()
    cfg.junction_deviation_mm = .025
    assert EcutBoardConfig.from_dict(cfg.to_dict()).junction_deviation_mm == .025


@pytest.mark.parametrize('value', [-1, float('nan'), True, '0.01'])
def test_invalid_junction_deviation_refuses_before_writes(value):
    api = pwm_api()
    api.config.junction_deviation_mm = value
    with pytest.raises(EcutError):
        api.run_gcode(['G1 X1 F600', 'Y1'])
    assert api._usb.events == []


def test_zero_corner_tolerance_reaches_stop_at_each_corner(monkeypatch):
    counts = []
    for tolerance in (0, .1):
        api = pwm_api()
        api.config.junction_deviation_mm = tolerance
        api.push_config()
        api._usb.events.clear()
        monkeypatch.setattr(api, '_submit_segments', lambda segments: counts.append(len(segments)))
        api.run_gcode(['G1 X1 F600', 'Y1'])
    assert counts[0] > counts[1]

def test_fifo_wait_budget_excludes_long_hold_before_space_arrives(monkeypatch):
    from types import SimpleNamespace
    from appPlugins.Common.ecut import State, ecut_controller

    api = pwm_api()
    api._running = True
    api._set_state(State.RUNNING)
    frame = api.last_rx_frame
    elapsed = [0.0]
    samples = []
    clock = SimpleNamespace(monotonic=lambda: elapsed[0],
                            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    monkeypatch.setattr(ecut_controller, 'time', clock)

    def poll():
        if not samples:
            # A status callback can hold and resume within one poll operation.
            api._set_state(State.PAUSED)
            elapsed[0] += 1.0
            api._set_state(State.RUNNING)
            free = 7000
        else:
            free = 7001
        samples.append(free)
        return replace(frame, field_790=free)

    monkeypatch.setattr(api, 'poll', poll)
    assert api._wait_for_stream_space(True)
    assert samples == [7000, 7001]


def test_compile_program_can_be_cancelled_without_finishing_the_file():
    from appPlugins.Common.ecut.ecut_controller import compile_program

    class Cancelled(BaseException):
        pass

    def checkpoint():
        raise Cancelled()

    with pytest.raises(Cancelled):
        compile_program(['G1 X1 F600']*100, checkpoint=checkpoint)


def test_api_preflight_services_cancellation_before_any_output():
    api = pwm_api()

    class Cancelled(BaseException):
        pass

    def checkpoint():
        raise Cancelled()

    api._planning_checkpoint = checkpoint
    with pytest.raises(Cancelled):
        api.run_gcode(['M3 S6000','G1 X1 F600'])
    assert api._usb.events == []
