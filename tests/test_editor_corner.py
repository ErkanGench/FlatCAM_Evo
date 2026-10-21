import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore

from appEditors.appGerberEditor import RegionEditorGrb, TrackEditorGrb
from appEditors.editor_corner import corner_point


# ---------------------------------------------------------------------------------------------------------------------
# corner_point
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('mode, new, expected', [
    # mode 1: straight part first, 45 degrees part last
    (1, (5.0, 2.0), (3.0, 0.0)),
    (1, (-5.0, 2.0), (-3.0, 0.0)),
    (1, (2.0, 5.0), (0.0, 3.0)),
    (1, (2.0, -5.0), (0.0, -3.0)),
    (1, (-2.0, -5.0), (0.0, -3.0)),
    # mode 2: 45 degrees part first
    (2, (5.0, 2.0), (2.0, 2.0)),
    (2, (-5.0, 2.0), (-2.0, 2.0)),
    (2, (2.0, -5.0), (2.0, -2.0)),
    (2, (-2.0, -5.0), (-2.0, -2.0)),
    # modes 3 and 4
    (3, (5.0, 2.0), (5.0, 0.0)),
    (3, (-5.0, -2.0), (-5.0, 0.0)),
    (4, (5.0, 2.0), (0.0, 2.0)),
    (4, (-5.0, -2.0), (0.0, -2.0)),
])
def test_corner_point_all_modes_and_directions(mode, new, expected):
    assert corner_point(mode, (0.0, 0.0), new) == pytest.approx(expected)


def test_corner_point_free_mode_has_no_corner():
    assert corner_point(5, (0.0, 0.0), (5.0, 2.0)) is None


@pytest.mark.parametrize('mode', [1, 2])
@pytest.mark.parametrize('new', [(3.0, 3.0), (-3.0, 3.0), (3.0, -3.0), (-3.0, -3.0)])
def test_corner_point_exact_diagonal_has_no_corner(mode, new):
    assert corner_point(mode, (0.0, 0.0), new) is None


@pytest.mark.parametrize('mode', [1, 2, 3, 4])
@pytest.mark.parametrize('new', [(5.0, 0.0), (-5.0, 0.0), (0.0, 5.0), (0.0, -5.0), (0.0, 0.0)])
def test_corner_point_aligned_segment_has_no_corner(mode, new):
    assert corner_point(mode, (1.0, 1.0), (1.0 + new[0], 1.0 + new[1])) is None


def test_corner_point_off_grid_points_are_exact_45_and_90():
    old = (0.3, -0.7)
    new = (4.123, 2.456)
    c1 = corner_point(1, old, new)
    assert c1[1] == pytest.approx(old[1])
    assert abs(new[0] - c1[0]) == pytest.approx(abs(new[1] - c1[1]))      # the last part is exactly 45 degrees
    c2 = corner_point(2, old, new)
    assert abs(c2[0] - old[0]) == pytest.approx(abs(c2[1] - old[1]))      # the first part is exactly 45 degrees
    assert c2[0] == pytest.approx(new[0]) or c2[1] == pytest.approx(new[1])
    assert corner_point(3, old, new) == pytest.approx((new[0], old[1]))
    assert corner_point(4, old, new) == pytest.approx((old[0], new[1]))


def test_corner_point_equal_to_an_endpoint_is_dropped():
    assert corner_point(3, (0.0, 0.0), (0.0, 4.0)) is None
    assert corner_point(4, (0.0, 0.0), (4.0, 0.0)) is None
    assert corner_point(3, (0.0, 0.0), (4.0, 0.0)) is None
    assert corner_point(1, (0.0, 0.0), (4.0, 1e-12)) is None


# ---------------------------------------------------------------------------------------------------------------------
# Gerber Region and Track
# ---------------------------------------------------------------------------------------------------------------------
def grb_tool(cls, mode, points, snap=True):
    tool = cls.__new__(cls)
    tool.dont_execute = False
    ui = SimpleNamespace(grid_snap_btn=SimpleNamespace(isChecked=lambda: snap),
                         grid_gap_x_entry=SimpleNamespace(get_value=lambda: 1.0),
                         grid_gap_y_entry=SimpleNamespace(get_value=lambda: 1.0))
    tool.draw_app = SimpleNamespace(bend_mode=mode, app=SimpleNamespace(ui=ui, inform=Mock()),
                                    in_action=False, last_length=0, snap_x=0.0, snap_y=0.0,
                                    tool_shape=Mock(), draw_utility_geometry=Mock())
    tool.points = list(points)
    tool.steps_per_circle = 8
    tool.buf_val = 0.001
    tool.gridx_size = tool.gridy_size = 1.0
    tool.temp_points = []
    tool.inter_point = None
    if cls is RegionEditorGrb:
        tool.reg_tool = SimpleNamespace(length=0)
        tool.ui = SimpleNamespace(x_entry=Mock(), y_entry=Mock())
    return tool


def region_click(tool, target):
    tool.utility_geometry(data=target)
    tool.click(target)


@pytest.mark.parametrize('mode', [1, 2])
def test_region_diagonal_gives_no_extra_vertex(mode):
    tool = grb_tool(RegionEditorGrb, mode, [(0.0, 0.0)])
    # a stale corner from a previous mouse position must not survive
    tool.utility_geometry(data=(5.0, 2.0))
    assert tool.inter_point is not None
    tool.utility_geometry(data=(3.0, 3.0))
    assert tool.inter_point is None
    assert tool.temp_points == [(0.0, 0.0), (3.0, 3.0)]
    tool.click((3.0, 3.0))
    assert tool.points == [(0.0, 0.0), (3.0, 3.0)]


@pytest.mark.parametrize('snap', [True, False])
def test_region_aligned_segment_has_no_duplicate_vertex(snap):
    tool = grb_tool(RegionEditorGrb, 1, [(0.0, 0.0)], snap=snap)
    region_click(tool, (4.0, 0.0))
    assert tool.points == [(0.0, 0.0), (4.0, 0.0)]
    tool = grb_tool(RegionEditorGrb, 3, [(0.0, 0.0)], snap=snap)
    region_click(tool, (0.0, 4.0))
    assert tool.points == [(0.0, 0.0), (0.0, 4.0)]


def test_region_free_mode_with_snap_off_adds_only_the_point():
    tool = grb_tool(RegionEditorGrb, 5, [(0.0, 0.0)], snap=False)
    region_click(tool, (4.3, 1.1))
    assert tool.points == [(0.0, 0.0), (4.3, 1.1)]


def test_region_modes_work_without_grid_snap_on_off_grid_points():
    tool = grb_tool(RegionEditorGrb, 1, [(0.25, 0.25)], snap=False)
    region_click(tool, (4.5, 2.125))
    assert tool.points[0] == (0.25, 0.25)
    assert len(tool.points) == 3
    corner = tool.points[1]
    assert corner[1] == pytest.approx(0.25)
    assert abs(4.5 - corner[0]) == pytest.approx(abs(2.125 - corner[1]))


def test_region_backspace_pops_exactly_what_the_click_added():
    tool = grb_tool(RegionEditorGrb, 1, [])
    tool.click((0.0, 0.0))                       # 1 point
    region_click(tool, (5.0, 2.0))               # corner + point
    region_click(tool, (8.0, 2.0))               # aligned: 1 point
    region_click(tool, (10.0, 4.0))              # diagonal from (8, 2): 1 point
    assert tool.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0), (8.0, 2.0), (10.0, 4.0)]
    assert tool.click_sizes == [1, 2, 1, 1]
    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert tool.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0), (8.0, 2.0)]
    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert tool.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]
    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert tool.points == [(0.0, 0.0)]


def test_region_backspace_in_free_mode_pops_one():
    tool = grb_tool(RegionEditorGrb, 5, [])
    tool.click((0.0, 0.0))
    region_click(tool, (5.0, 2.0))
    region_click(tool, (7.0, 6.0))
    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert tool.points == [(0.0, 0.0), (5.0, 2.0)]


def test_region_start_message_uses_the_current_mode():
    src = inspect.getsource(RegionEditorGrb.__init__)
    assert 'bend_mode_message(self.draw_app.bend_mode)' in src
    assert "Corner Mode 1" not in src


def test_region_t_and_r_cycle_with_the_shared_messages():
    tool = grb_tool(RegionEditorGrb, 1, [(0.0, 0.0)])
    msg = tool.on_key('T')
    assert tool.draw_app.bend_mode == 2 and 'Mode 2' in msg
    msg = tool.on_key('R')
    assert tool.draw_app.bend_mode == 1 and 'Mode 1' in msg
    msg = tool.on_key('R')
    assert tool.draw_app.bend_mode == 5 and 'Mode 5' in msg


@pytest.mark.parametrize('mode, target', [(3, (0.0, 4.0)), (4, (4.0, 0.0)), (3, (4.0, 0.0)), (1, (4.0, 0.0)),
                                          (2, (0.0, 4.0))])
def test_track_no_zero_length_corner(mode, target):
    tool = grb_tool(TrackEditorGrb, mode, [(0.0, 0.0)])
    tool.utility_geometry(data=target)
    assert tool.temp_points == [(0.0, 0.0), target]


def test_track_diagonal_has_no_corner():
    tool = grb_tool(TrackEditorGrb, 1, [(0.0, 0.0)])
    tool.utility_geometry(data=(3.0, 3.0))
    assert tool.temp_points == [(0.0, 0.0), (3.0, 3.0)]


@pytest.mark.parametrize('mode, expected', [(1, (3.0, 0.0)), (2, (2.0, 2.0)), (3, (5.0, 0.0)), (4, (0.0, 2.0))])
def test_track_modes_work_with_snap_off(mode, expected):
    tool = grb_tool(TrackEditorGrb, mode, [(0.0, 0.0)], snap=False)
    tool.utility_geometry(data=(5.0, 2.0))
    assert tool.temp_points == [(0.0, 0.0), expected, (5.0, 2.0)]


def test_track_modes_use_the_real_deltas_off_grid():
    tool = grb_tool(TrackEditorGrb, 1, [(0.3, 0.3)], snap=True)
    tool.utility_geometry(data=(4.7, 2.2))
    corner = tool.temp_points[1]
    assert corner[1] == pytest.approx(0.3)
    assert abs(4.7 - corner[0]) == pytest.approx(abs(2.2 - corner[1]))


def track_tool_with_storage(mode):
    tool = grb_tool(TrackEditorGrb, mode, [])
    storage = []
    tool.draw_app.storage_dict = {10: {'geometry': storage}}
    tool.draw_app.last_aperture_selected = 10
    tool.draw_app.add_gerber_shape = lambda shape, store: store.append(shape)
    tool.draw_app.plot_all = Mock()
    tool.track_tool = SimpleNamespace(length=0)
    tool.ui = SimpleNamespace(x_entry=Mock(), y_entry=Mock())
    tool.click_shapes = []
    return tool, storage


def track_click(tool, target):
    tool.utility_geometry(data=target)
    tool.click(target)


def test_track_backspace_removes_the_last_point_and_its_segment():
    tool, storage = track_tool_with_storage(1)
    track_click(tool, (0.0, 0.0))
    track_click(tool, (5.0, 2.0))
    track_click(tool, (8.0, 2.0))
    assert len(storage) == 3
    kept = storage[:2]

    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert tool.points == [(0.0, 0.0), (5.0, 2.0)]
    assert storage == kept

    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert tool.points == [] and storage == [] and tool.temp_points == []
    # nothing left to remove: no error
    tool.on_key(QtCore.Qt.Key.Key_Backspace)
    assert storage == []
