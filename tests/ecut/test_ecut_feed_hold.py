"""Feed hold brakes along the planned path and resumes it; no board is needed."""
import math

from appPlugins.Common.ecut.ecut_config import EcutBoardConfig
from appPlugins.Common.ecut.ecut_controller import _HoldableRecords
from appPlugins.Common.ecut.ecut_planner import LinearMove, iter_path_segments, plan_linear_path


def make_path(config, target=(20.0, 10.0), feed=1200.0):
    blocks = plan_linear_path(config, (0,) * 6, [LinearMove((target[0], target[1], None, None, None, None), False, feed)])
    return iter_path_segments(blocks, junction_deviation_mm=config.junction_deviation_mm)


def speeds(records, config):
    scale = config.axes[0].steps_per_mm * config.interpolation_factor
    return [math.hypot(r[0] / scale, r[1] / scale) * 1000 for r in records]


def test_without_hold_the_planned_records_pass_unchanged():
    config = EcutBoardConfig()
    path = make_path(config)
    records = _HoldableRecords(path, config, lambda: False)
    out = []
    while not records.done:
        out.extend(records.take(4))
    assert out == list(path)


def test_hold_brakes_at_the_deceleration_limit_and_resume_completes_the_path():
    config = EcutBoardConfig()
    for axis in config.axes:
        axis.acceleration_mm_s2 = 200.0
    path = make_path(config)
    total = [sum(r[i] for r in path) for i in range(6)]
    state = {'held': False}
    records = _HoldableRecords(path, config, lambda: state['held'])
    out = []
    out.extend(records.take(len(path) // 2))
    hold_at = len(out)
    state['held'] = True
    while not records.stopped:
        chunk = records.take(4)
        assert chunk or records.stopped
        out.extend(chunk)
    braking = len(out) - hold_at
    assert records.take(4) == []  # held and stopped: nothing to send
    state['held'] = False
    while not records.done:
        out.extend(records.take(4))
    assert [sum(r[i] for r in out) for i in range(6)] == total
    v = speeds(out, config)
    cruise = v[hold_at - 1]
    # about cruise / deceleration of braking time; the limit along the path is the axis limit / direction
    limit = min(200.0 * math.hypot(2, 1) / 2, 200.0 * math.hypot(2, 1) / 1)
    assert abs(braking - cruise / limit * 1000) <= 3
    changes = [abs(b - a) * 1000 for a, b in zip(v, v[1:])]
    # rounding to whole counts adds about 1 count per record of noise
    noise = 2 / (config.axes[0].steps_per_mm * config.interpolation_factor) * 1000 * 1000
    assert max(changes[hold_at - 1:]) <= max(changes[:hold_at - 1]) + noise
    assert all(max(abs(c) for c in r) <= 32767 for r in out)


def test_hold_at_a_stopped_point_stops_at_once():
    config = EcutBoardConfig()
    path = make_path(config)
    records = _HoldableRecords(path, config, lambda: True)
    # the path starts at rest: a hold before the first record sends nothing
    assert records.take(4) == []
    assert records.stopped
