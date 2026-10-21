"""Corner (bend) modes of the Geometry Editor Path/Polygon tools and the function shared with the Gerber Editor."""
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, LinearRing

from appEditors.appGeoEditor import AppGeoEditor, FCPath, FCPolygon, bend_corner_point
from appEditors.appGerberEditor import RegionEditorGrb, TrackEditorGrb
from appEditors.editor_corner import corner_point, next_bend_mode, bend_mode_message, BEND_MODE_FREE
from tests.test_geo_editor_input import input_tool, dispatch


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(autouse=True)
def no_modifier(monkeypatch):
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.NoModifier))


def corner(mode, old, new):
    return corner_point(mode, old, new)


# ---------------------------------------------------------------------------------------------------------------------
# the shared function
# ---------------------------------------------------------------------------------------------------------------------
# (mode, new point) -> corner, starting from (0, 0); every quadrant (left/right, up/down), X-major and Y-major moves
SHARED = [
    # mode 1: 45 degrees, the diagonal part is last
    (1, (5, 2), (3, 0)), (1, (-5, 2), (-3, 0)), (1, (5, -2), (3, 0)), (1, (-5, -2), (-3, 0)),
    (1, (2, 5), (0, 3)), (1, (-2, 5), (0, 3)), (1, (2, -5), (0, -3)), (1, (-2, -5), (0, -3)),
    # mode 2: reverse 45 degrees, the diagonal part is first
    (2, (5, 2), (2, 2)), (2, (-5, 2), (-2, 2)), (2, (5, -2), (2, -2)), (2, (-5, -2), (-2, -2)),
    (2, (2, 5), (2, 2)), (2, (-2, 5), (-2, 2)), (2, (2, -5), (2, -2)), (2, (-2, -5), (-2, -2)),
    # mode 3: 90 degrees, horizontal first
    (3, (5, 2), (5, 0)), (3, (-5, 2), (-5, 0)), (3, (5, -2), (5, 0)), (3, (-2, -5), (-2, 0)),
    # mode 4: reverse 90 degrees, vertical first
    (4, (5, 2), (0, 2)), (4, (-5, 2), (0, 2)), (4, (5, -2), (0, -2)), (4, (-2, -5), (0, -5)),
    # mode 5: free angle, no corner
    (5, (5, 2), None), (5, (-2, -5), None),
    # a pure diagonal needs no corner in the 45 degrees modes
    (1, (3, 3), None), (2, (-3, 3), None),
]


@pytest.mark.parametrize('mode, new, expected', SHARED)
def test_shared_corner_all_modes_and_directions(mode, new, expected):
    assert corner(mode, (0, 0), new) == expected


def test_shared_corner_uses_the_origin():
    # 5 x 2 from (1, 1) -> 45 degrees corner 3 units from the start
    assert corner_point(1, (1.0, 1.0), (6.0, 3.0)) == (4.0, 1.0)
    assert corner_point(2, (1.0, 1.0), (6.0, 3.0)) == (3.0, 3.0)


def test_mode_cycle_forward_and_backward():
    forward = [1]
    for _i in range(5):
        forward.append(next_bend_mode(forward[-1], True))
    assert forward == [1, 2, 3, 4, 5, 1]
    backward = [1]
    for _i in range(5):
        backward.append(next_bend_mode(backward[-1], False))
    assert backward == [1, 5, 4, 3, 2, 1]
    assert next_bend_mode(99, True) == 1 and next_bend_mode(99, False) == 1


def test_mode_messages_are_distinct():
    messages = {bend_mode_message(mode) for mode in range(1, 6)}
    assert len(messages) == 5
    assert all('Corner Mode' in text for text in messages)


# ---------------------------------------------------------------------------------------------------------------------
# Gerber tools keep the same points (golden values recorded before the corner math was moved to the shared function)
# ---------------------------------------------------------------------------------------------------------------------
def grb_ui(snap=True):
    return SimpleNamespace(grid_snap_btn=SimpleNamespace(isChecked=lambda: snap),
                           grid_gap_x_entry=SimpleNamespace(get_value=lambda: 1.0),
                           grid_gap_y_entry=SimpleNamespace(get_value=lambda: 1.0))


def grb_tool(cls, mode, points, snap=True):
    tool = cls.__new__(cls)
    tool.dont_execute = False
    tool.draw_app = SimpleNamespace(bend_mode=mode, app=SimpleNamespace(ui=grb_ui(snap)))
    tool.points = list(points)
    tool.steps_per_circle = 8
    tool.buf_val = 0.001
    tool.gridx_size = tool.gridy_size = 1.0
    tool.temp_points = []
    tool.inter_point = None
    return tool


REGION_FIRST = {
    (1, (5.0, 2.0)): [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)],
    (1, (-2.0, 5.0)): [(0.0, 0.0), (0.0, 3.0), (-2.0, 5.0)],
    (1, (-2.0, -5.0)): [(0.0, 0.0), (0.0, -3.0), (-2.0, -5.0)],
    (2, (5.0, 2.0)): [(0.0, 0.0), (2.0, 2.0), (5.0, 2.0)],
    (2, (-2.0, 5.0)): [(0.0, 0.0), (-2.0, 2.0), (-2.0, 5.0)],
    (3, (5.0, 2.0)): [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)],
    (3, (-2.0, -5.0)): [(0.0, 0.0), (-2.0, 0.0), (-2.0, -5.0)],
    (4, (5.0, 2.0)): [(0.0, 0.0), (0.0, 2.0), (5.0, 2.0)],
    (4, (-5.0, -2.0)): [(0.0, 0.0), (0.0, -2.0), (-5.0, -2.0)],
    (5, (5.0, 2.0)): [(0.0, 0.0), (5.0, 2.0)],
    (1, (3.0, 3.0)): [(0.0, 0.0), (3.0, 3.0)],
}


@pytest.mark.parametrize('key', list(REGION_FIRST))
def test_gerber_region_first_segment_unchanged(key):
    mode, target = key
    tool = grb_tool(RegionEditorGrb, mode, [(0.0, 0.0)])
    tool.utility_geometry(data=target)
    assert tool.temp_points == REGION_FIRST[key]


REGION_NEXT = {
    (1, (5.0, 2.0)): [(10.0, 10.0), (0.0, 0.0), (3.0, 0.0), (5.0, 2.0)],
    (1, (-2.0, 5.0)): [(10.0, 10.0), (0.0, 0.0), (0.0, 3.0), (-2.0, 5.0)],
    (2, (-2.0, -5.0)): [(10.0, 10.0), (0.0, 0.0), (-2.0, -2.0), (-2.0, -5.0)],
    (3, (-5.0, -2.0)): [(10.0, 10.0), (0.0, 0.0), (-5.0, 0.0), (-5.0, -2.0)],
    (4, (-2.0, 5.0)): [(10.0, 10.0), (0.0, 0.0), (0.0, 5.0), (-2.0, 5.0)],
    (5, (5.0, 2.0)): [(10.0, 10.0), (0.0, 0.0), (5.0, 2.0)],
}


@pytest.mark.parametrize('key', list(REGION_NEXT))
def test_gerber_region_next_segment_unchanged(key):
    mode, target = key
    tool = grb_tool(RegionEditorGrb, mode, [(10.0, 10.0), (0.0, 0.0)])
    tool.utility_geometry(data=target)
    assert tool.temp_points == REGION_NEXT[key]


def test_gerber_region_click_adds_corner_and_point():
    tool = grb_tool(RegionEditorGrb, 1, [(0.0, 0.0)])
    tool.utility_geometry(data=(5.0, 2.0))
    tool.draw_app.in_action = False
    tool.reg_tool = SimpleNamespace(length=0)
    tool.ui = SimpleNamespace(x_entry=Mock(), y_entry=Mock())
    tool.draw_app.last_length = 0
    tool.draw_app.snap_x = tool.draw_app.snap_y = 0.0
    tool.draw_app.app.inform = Mock()
    tool.click((5.0, 2.0))
    assert tool.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]


TRACK = {
    (1, (5.0, 2.0)): [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)],
    (1, (-2.0, 5.0)): [(0.0, 0.0), (0.0, 3.0), (-2.0, 5.0)],
    (2, (-5.0, -2.0)): [(0.0, 0.0), (-2.0, -2.0), (-5.0, -2.0)],
    (3, (5.0, 2.0)): [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)],
    (3, (0.0, 4.0)): [(0.0, 0.0), (0.0, 4.0)],      # no zero-length corner on an aligned segment
    (4, (-2.0, 5.0)): [(0.0, 0.0), (0.0, 5.0), (-2.0, 5.0)],
    (5, (5.0, 2.0)): [(0.0, 0.0), (5.0, 2.0)],
}


@pytest.mark.parametrize('key', list(TRACK))
def test_gerber_track_unchanged(key):
    mode, target = key
    tool = grb_tool(TrackEditorGrb, mode, [(0.0, 0.0)])
    tool.utility_geometry(data=target)
    assert tool.temp_points == TRACK[key]


def test_gerber_corner_modes_work_without_grid_snap():
    tool = grb_tool(RegionEditorGrb, 1, [(0.0, 0.0)], snap=False)
    tool.utility_geometry(data=(5.0, 2.0))
    assert tool.temp_points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]
    tool = grb_tool(TrackEditorGrb, 1, [(0.0, 0.0)], snap=False)
    tool.utility_geometry(data=(5.0, 2.0))
    assert tool.temp_points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]


# ---------------------------------------------------------------------------------------------------------------------
# Geometry Editor Path
# ---------------------------------------------------------------------------------------------------------------------
def path_tool(mode=5, points=()):
    editor, tool, panel, original = input_tool(FCPath, points=points)
    editor.bend_mode = mode
    tool.points = list(points)
    tool.set_bend_cursor = Mock()
    return editor, tool


def click_all(tool, *clicks):
    for point in clicks:
        tool.click(point)


def test_editor_default_corner_mode_is_free_angle():
    # the attribute is created by AppGeoEditor.__init__; check the default without building the whole editor
    assert 'self.bend_mode = BEND_MODE_FREE' in inspect.getsource(AppGeoEditor.__init__)
    assert BEND_MODE_FREE == 5
    # a tool on an editor without the attribute behaves as the free angle mode
    assert bend_corner_point(SimpleNamespace(), (0.0, 0.0), (5.0, 2.0)) is None


def test_path_default_free_angle_is_unchanged():
    editor, tool = path_tool(5, points=())
    click_all(tool, (0.0, 0.0), (5.0, 2.0), (7.0, 9.0))
    assert tool.points == [(0.0, 0.0), (5.0, 2.0), (7.0, 9.0)]
    assert bend_corner_point(editor, (0.0, 0.0), (5.0, 2.0)) is None
    preview = tool.utility_geometry(data=(8.0, 9.0)).geo
    assert list(preview.coords) == [(0.0, 0.0), (5.0, 2.0), (7.0, 9.0), (8.0, 9.0)]


def test_path_mode_1_click_adds_corner_and_point():
    editor, tool = path_tool(1)
    click_all(tool, (0.0, 0.0), (5.0, 2.0))
    assert tool.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]
    click_all(tool, (5.0, 8.0))   # vertical move: no corner
    assert tool.points[-1] == (5.0, 8.0) and len(tool.points) == 4
    click_all(tool, (9.0, 10.0))  # 45 degrees mode again
    assert tool.points[-3:] == [(5.0, 8.0), (7.0, 8.0), (9.0, 10.0)]


def test_path_mode_3_click_adds_corner_and_point():
    editor, tool = path_tool(3)
    click_all(tool, (0.0, 0.0), (5.0, 2.0), (1.0, 6.0))
    assert tool.points == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0), (1.0, 2.0), (1.0, 6.0)]


@pytest.mark.parametrize('mode, expected', [
    (2, [(0.0, 0.0), (2.0, 2.0), (5.0, 2.0)]),
    (4, [(0.0, 0.0), (0.0, 2.0), (5.0, 2.0)]),
])
def test_path_modes_2_and_4(mode, expected):
    editor, tool = path_tool(mode)
    click_all(tool, (0.0, 0.0), (5.0, 2.0))
    assert tool.points == expected


def test_path_preview_shows_corner_without_changing_points():
    editor, tool = path_tool(3, points=[(0.0, 0.0)])
    preview = tool.utility_geometry(data=(5.0, 2.0)).geo
    assert list(preview.coords) == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)]
    assert tool.points == [(0.0, 0.0)]


def test_path_no_corner_when_aligned_or_without_distance():
    editor, tool = path_tool(3)
    click_all(tool, (0.0, 0.0), (5.0, 0.0), (5.0, 4.0))
    assert tool.points == [(0.0, 0.0), (5.0, 0.0), (5.0, 4.0)]
    assert bend_corner_point(editor, (0.0, 0.0), (0.0, 0.0)) is None


@pytest.mark.parametrize('mode', [1, 2, 3, 4, 5])
def test_path_backspace_removes_the_corner_with_its_point(mode):
    editor, tool = path_tool(mode)
    click_all(tool, (0.0, 0.0), (5.0, 2.0), (1.0, 7.0))
    tool_points_full = list(tool.points)
    assert len(tool_points_full) in (3, 5)
    response = tool.on_key('Backspace')
    assert response
    assert tool.points == tool_points_full[:len(tool.points)]
    assert tool.points[-1] == (5.0, 2.0)
    tool.on_key('Backspace')
    assert tool.points == [(0.0, 0.0)]
    tool.on_key('Backspace')
    assert tool.points == []


def test_path_backspace_after_mixed_modes():
    editor, tool = path_tool(3)
    click_all(tool, (0.0, 0.0), (5.0, 2.0))
    editor.bend_mode = 5
    click_all(tool, (8.0, 9.0))
    editor.bend_mode = 4
    click_all(tool, (10.0, 12.0))
    assert tool.points == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0), (8.0, 9.0), (8.0, 12.0), (10.0, 12.0)]
    tool.on_key('Backspace')
    assert tool.points == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0), (8.0, 9.0)]
    tool.on_key('Backspace')
    assert tool.points == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)]


def test_path_made_geometry_has_the_corner_points():
    editor, tool = path_tool(3)
    click_all(tool, (0.0, 0.0), (5.0, 2.0))
    assert tool.make() != 'fail'
    assert list(tool.geometry.geo.coords) == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)]


def test_path_t_cycles_forward_and_r_backward():
    editor, tool = path_tool(5)
    seen = []
    for _i in range(5):
        seen.append((tool.on_key('T'), editor.bend_mode))
    assert [mode for _msg, mode in seen] == [1, 2, 3, 4, 5]
    assert all('Corner Mode %d' % mode in msg for msg, mode in seen)
    seen = []
    for _i in range(5):
        seen.append((tool.on_key('R'), editor.bend_mode))
    assert [mode for _msg, mode in seen] == [4, 3, 2, 1, 5]
    assert all('Corner Mode %d' % mode in msg for msg, mode in seen)
    assert tool.on_key(QtCore.Qt.Key.Key_T) and editor.bend_mode == 1
    assert tool.on_key(QtCore.Qt.Key.Key_R) and editor.bend_mode == 5
    assert tool.set_bend_cursor.call_count == 12


def test_path_mode_change_refreshes_the_preview():
    editor, tool = path_tool(5, points=[(0.0, 0.0)])
    editor.snap_x, editor.snap_y = 5.0, 2.0
    tool.on_key('T')
    editor.tool_shape.clear.assert_called()
    shape = editor.draw_utility_geometry.call_args.kwargs['geo']
    assert list(shape.geo.coords) == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]


@pytest.mark.parametrize('key, expected', [('T', 1), ('R', 4)])
def test_t_and_r_inside_the_path_tool_do_not_start_other_tools(key, expected, monkeypatch):
    editor, tool = path_tool(5, points=[(0.0, 0.0)])
    dispatch(editor, key, monkeypatch)
    assert editor.bend_mode == expected
    editor.select_tool.assert_not_called()   # T would select the Text tool, R the Rectangle tool


def test_mode_is_kept_for_the_editor_session():
    editor, tool = path_tool(5)
    tool.on_key('T')
    editor, second, _panel, _original = input_tool(FCPath, points=())
    editor.bend_mode = 1
    second.set_bend_cursor = Mock()
    click_all(second, (0.0, 0.0), (5.0, 2.0))
    assert second.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0)]


# ---------------------------------------------------------------------------------------------------------------------
# Geometry Editor Polygon
# ---------------------------------------------------------------------------------------------------------------------
def polygon_tool(mode=5, points=()):
    editor, path, _panel, _original = input_tool(FCPath, points=points)
    editor.bend_mode = mode
    tool = FCPolygon.__new__(FCPolygon)
    tool.draw_app, tool.app, tool.name, tool.points = editor, editor.app, 'polygon', list(points)
    tool.complete, tool.geometry, tool.new_segment, tool.cursor_data_control = False, None, True, True
    tool.plugin_name = 'Polygon'
    tool.draw_cursor_data = Mock()
    tool.polygon_tool = SimpleNamespace(length=0.0)
    return editor, tool


def test_polygon_default_free_angle_is_unchanged():
    editor, tool = polygon_tool(5)
    click_all(tool, (0.0, 0.0), (5.0, 2.0), (1.0, 7.0))
    assert tool.points == [(0.0, 0.0), (5.0, 2.0), (1.0, 7.0)]


def test_polygon_mode_3_preview_and_click():
    editor, tool = polygon_tool(3)
    click_all(tool, (0.0, 0.0))
    preview = tool.utility_geometry(data=(5.0, 2.0)).geo
    assert isinstance(preview, LineString)
    assert list(preview.coords) == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)]
    click_all(tool, (5.0, 2.0))
    assert tool.points == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0)]
    ring = tool.utility_geometry(data=(1.0, 6.0)).geo
    assert isinstance(ring, LinearRing)
    assert list(ring.coords)[:-1] == [(0.0, 0.0), (5.0, 0.0), (5.0, 2.0), (1.0, 2.0), (1.0, 6.0)]


def test_polygon_mode_1_make_keeps_the_corner_points():
    editor, tool = polygon_tool(1)
    click_all(tool, (0.0, 0.0), (5.0, 2.0), (5.0, 8.0))
    assert tool.points == [(0.0, 0.0), (3.0, 0.0), (5.0, 2.0), (5.0, 8.0)]
    tool.draw_cursor_data = Mock()
    tool.make()
    assert list(tool.geometry.geo.coords)[:-1] == tool.points


@pytest.mark.parametrize('mode', [1, 2, 3, 4, 5])
def test_polygon_backspace_removes_the_corner_with_its_point(mode):
    editor, tool = polygon_tool(mode)
    click_all(tool, (0.0, 0.0), (5.0, 2.0), (1.0, 7.0))
    assert tool.on_key('Backspace')
    assert tool.points[-1] == (5.0, 2.0)
    tool.on_key('Backspace')
    assert tool.points == [(0.0, 0.0)]


def test_polygon_t_and_r_cycle():
    editor, tool = polygon_tool(5)
    assert [(tool.on_key('T'), editor.bend_mode)[1] for _i in range(3)] == [1, 2, 3]
    assert [(tool.on_key('R'), editor.bend_mode)[1] for _i in range(4)] == [2, 1, 5, 4]
    assert 'Corner Mode 5' in tool.on_key(QtCore.Qt.Key.Key_T)
    assert editor.bend_mode == 5
