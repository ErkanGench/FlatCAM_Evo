"""Independent acceleration and braking limits for offline motion planning."""
import math

import pytest

from appPlugins.Common.ecut.ecut_config import AxisConfig, EcutBoardConfig, EcutConfigError
from appPlugins.Common.ecut.ecut_planner import LinearMove, plan_linear_path, iter_jog_segments


def config(acceleration=4, deceleration=1):
    cfg = EcutBoardConfig(interpolation_index=0)
    for axis in cfg.axes:
        axis.steps_per_mm = 10000
        axis.max_velocity_mm_s = 2
        axis.acceleration_mm_s2 = acceleration
        axis.deceleration_mm_s2 = deceleration
    return cfg


def move(x, y=None):
    return LinearMove((x, y, None, None, None, None), False, 120)


def test_axis_braking_limit_survives_configuration_roundtrip():
    cfg = config()
    restored = EcutBoardConfig.from_dict(cfg.to_dict())
    assert getattr(restored.axes[0], 'deceleration_mm_s2', None) == 1
    legacy = AxisConfig.from_dict({'acceleration_mm_s2': 7})
    assert getattr(legacy, 'deceleration_mm_s2', 'missing') is None


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True, '1', 10 ** 1000])
def test_invalid_axis_braking_limit_is_refused(value):
    cfg = config(deceleration=value)
    with pytest.raises(EcutConfigError):
        cfg.validate()


def test_long_move_has_independent_ramp_cruise_and_braking_times():
    block = plan_linear_path(config(), (0,) * 6, [move(10)])[0]
    profile = block.segments.profile
    assert profile.t_acc == pytest.approx(.5)
    assert profile.t_cruise == pytest.approx(3.75)
    assert profile.duration == pytest.approx(6.25)
    assert profile.fraction(5.25) * 10 == pytest.approx(9.5)
    assert sum(record[0] for record in block.segments) == 200000


def test_short_move_is_triangular_with_asymmetric_ramps():
    profile = plan_linear_path(config(), (0,) * 6, [move(1)])[0].segments.profile
    assert profile.peak == pytest.approx(math.sqrt(1.6))
    assert profile.t_cruise == pytest.approx(0, abs=1e-12)
    assert profile.duration == pytest.approx(math.sqrt(2.5))
    assert profile.fraction(profile.t_acc) == pytest.approx(.2)


def test_reverse_lookahead_uses_braking_limit_and_forward_uses_acceleration():
    blocks = plan_linear_path(config(), (0,) * 6, [move(.1), move(2), move(2.1)])
    assert blocks[0].exit_speed_mm_s == pytest.approx(math.sqrt(.8))
    assert blocks[-1].entry_speed_mm_s == pytest.approx(math.sqrt(.2))


def test_coordinated_braking_projects_each_axis_limit():
    cfg = config()
    cfg.axes[1].deceleration_mm_s2 = .5
    profile = plan_linear_path(cfg, (0,) * 6, [move(1, 1)])[0].segments.profile
    assert getattr(profile, 'deceleration', None) == pytest.approx(.5 * math.sqrt(2))


def test_omitted_braking_limit_keeps_symmetric_motion_records():
    cfg = config(deceleration=None)
    implicit = plan_linear_path(cfg, (0,) * 6, [move(1), move(2)])
    for axis in cfg.axes:
        axis.deceleration_mm_s2 = axis.acceleration_mm_s2
    explicit = plan_linear_path(cfg, (0,) * 6, [move(1), move(2)])
    assert [tuple(block.segments) for block in implicit] == [tuple(block.segments) for block in explicit]


@pytest.mark.parametrize('direction', [0, 1])
def test_jog_release_uses_configured_braking_distance(direction):
    cfg = config()
    generated = 0
    def held():
        nonlocal generated
        generated += 1
        return generated <= 600
    records = list(iter_jog_segments(cfg, (0,) * 6, 0, direction, 120, held))
    # At 0.6 s the .5 s acceleration has covered .5 mm, then .2 mm cruise.
    # Braking from 2 mm/s at 1 mm/s2 adds 2 mm and takes 2 seconds.
    assert sum(record[0] for record in records) == (54000 if direction == 0 else -54000)
    assert 2599 <= len(records) <= 2601


def test_jog_brakes_early_enough_for_soft_limit():
    cfg = config()
    cfg.axes[0].soft_limits_enabled = True
    cfg.axes[0].soft_limit_positive_mm = 3
    records = list(iter_jog_segments(cfg, (0,) * 6, 0, 0, 120, lambda: True))
    assert 2749 <= len(records) <= 2751
    assert sum(record[0] for record in records) == 60000
    # The last sample may be shorter than 1 ms, shifting this window by one record.
    assert sum(record[0] for record in records[-1000:]) == pytest.approx(10000, abs=21)
