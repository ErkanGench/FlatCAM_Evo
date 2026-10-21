"""VertexGrips with a fake editor: display, hit test, drag threshold, preview, commit call, cancel."""
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtCore
from shapely import BufferJoinStyle
from shapely.geometry import LineString, MultiPolygon, Point, box

from appEditors.vertex_grips import VertexGrips, GRIP_COLOR, INVALID_COLOR

NO_MOD = QtCore.Qt.KeyboardModifier.NoModifier
CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
PIXEL = 0.01  # canvas units for each screen pixel: the hit radius is 0.06


class FakeCollection:
    def __init__(self):
        self.items = []
        self.enabled = True

    def add(self, shape=None, **kwargs):
        self.items.append((shape, kwargs))
        return len(self.items)

    def clear(self, update=False):
        self.items = []

    def redraw(self):
        pass


def make_grips(geometry, grid=False, snap=None, busy=False):
    shape = SimpleNamespace(geo=geometry)
    app = SimpleNamespace(grid_status=lambda: grid, inform=SimpleNamespace(emit=Mock()),
                          options={'global_sel_line': '#0000ffbf'},
                          plotcanvas=SimpleNamespace(new_shape_collection=lambda layers: FakeCollection()))
    editor = SimpleNamespace(selected=[shape], active_tool=SimpleNamespace(name='select'), app=app,
                             apply_vertex_edit=Mock(return_value=None), reject_busy=lambda: busy,
                             snap=snap or (lambda x, y: (x, y)), active_snap_type=None,
                             canvas=SimpleNamespace(pixel_size=lambda: PIXEL), tool_shape=FakeCollection(),
                             get_draw_color=lambda: '#00000080', get_sel_color=lambda: '#0000FF80')
    grips = VertexGrips(editor)
    grips.sync()
    return grips, editor, shape


def drag(grips, start, end):
    """Press at the canvas point start, move 20 px, release at the canvas point end."""
    assert grips.press((0, 0), start, NO_MOD)
    grips.move((20, 0), end)
    return grips.release((20, 0), end)


def test_sync_shows_grips_for_one_selected_shape_in_select_tool_only():
    grips, editor, shape = make_grips(LineString([(0, 0), (1, 0), (2, 0)]))
    assert grips.shape is shape
    assert len(grips.collection().items) == 5  # 3 vertices + 2 midpoints
    editor.active_tool = SimpleNamespace(name='move')
    grips.sync()
    assert grips.shape is None and grips.collection().items == []
    editor.active_tool = SimpleNamespace(name='select')
    editor.selected = [shape, SimpleNamespace(geo=LineString([(5, 5), (6, 6)]))]
    grips.sync()
    assert grips.shape is None


def test_too_many_vertices_shows_no_grips_and_tells_the_user(monkeypatch):
    monkeypatch.setattr('appEditors.vertex_grips.GRIP_LIMIT', 2)
    grips, editor, shape = make_grips(LineString([(0, 0), (1, 0), (2, 0)]))
    assert grips.shape is None
    editor.app.inform.emit.assert_called_once()
    grips.sync()
    editor.app.inform.emit.assert_called_once()  # no repeat for the same shape


def test_vertex_grip_wins_over_a_nearer_midpoint_grip():
    grips, editor, shape = make_grips(LineString([(0, 0), (0.08, 0)]))
    assert grips.hit((0.03, 0)) == ('vertex', (0, 0, 0), (0, 0))
    assert grips.hit((1, 1)) is None


def test_tie_at_a_touch_point_takes_the_lower_address():
    grips, editor, shape = make_grips(MultiPolygon([box(0, 0, 1, 1), box(1, 1, 2, 2)]))
    kind, address, point = grips.hit((1, 1))
    assert kind == 'vertex' and address[0] == 0 and point == (1, 1)


def test_click_below_the_drag_threshold_changes_nothing():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert grips.press((0, 0), (0, 0), NO_MOD)
    assert grips.move((3, 0), (0.03, 0))
    assert grips.release((3, 0), (0.03, 0))
    editor.apply_vertex_edit.assert_not_called()


def test_drag_of_a_vertex_commits_one_move():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert drag(grips, (2, 0), (2, 1))
    editor.apply_vertex_edit.assert_called_once_with('move', (0, 0, 1), (2.0, 1.0), target=shape,
                                                     on_segment=False)
    assert editor.tool_shape.items == []


def test_drag_of_a_midpoint_inserts_a_vertex():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert drag(grips, (1, 0), (1, 1))
    editor.apply_vertex_edit.assert_called_once_with('insert', (0, 0, 0), (1.0, 1.0), target=shape,
                                                     on_segment=False)


def test_ctrl_click_removes_a_vertex():
    grips, editor, shape = make_grips(LineString([(0, 0), (1, 0), (2, 0)]))
    assert grips.press((0, 0), (1, 0), CTRL)
    assert grips.release((0, 0), (1, 0))
    editor.apply_vertex_edit.assert_called_once_with('remove', (0, 0, 1), target=shape)


def test_cancel_drops_the_drag():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert grips.press((0, 0), (2, 0), NO_MOD)
    grips.move((20, 0), (2, 1))
    assert editor.tool_shape.items
    grips.cancel()
    assert editor.tool_shape.items == []
    assert not grips.release((20, 0), (2, 1))
    editor.apply_vertex_edit.assert_not_called()


def test_preview_color_shows_an_invalid_result():
    grips, editor, shape = make_grips(box(0, 0, 4, 4))
    assert grips.press((0, 0), (4, 0), NO_MOD)
    grips.move((20, 0), (5, 0))
    assert editor.tool_shape.items[-1][1]['color'] == GRIP_COLOR
    grips.move((40, 0), (4, 4))  # onto the next vertex: zero-length segment
    assert editor.tool_shape.items[-1][1]['color'] == INVALID_COLOR


def test_corner_snap_ignores_the_dragged_vertex():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=True, snap=lambda x, y: (2, 0))
    editor.active_snap_type = 'corner'
    assert drag(grips, (2, 0), (2.03, 0.04))
    assert editor.apply_vertex_edit.call_args.args[2] == (2.03, 0.04)


def test_grid_snap_applies_during_the_drag():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=True, snap=lambda x, y: (3, 1))
    editor.active_snap_type = 'grid'
    assert drag(grips, (2, 0), (2.9, 1.1))
    assert editor.apply_vertex_edit.call_args.args[2] == (3, 1)


def test_busy_editor_does_not_take_the_press():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), busy=True)
    assert not grips.press((0, 0), (2, 0), NO_MOD)


def test_four_value_canvas_points_are_cut_to_x_and_y():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert grips.press((0, 0, 0, 1), (2, 0, 0, 1), NO_MOD)
    grips.move((20, 0, 0, 1), (2, 1, 0, 1))
    assert grips.release((20, 0, 0, 1), (2, 1, 0, 1))
    assert editor.apply_vertex_edit.call_args.args[2] == (2.0, 1.0)


ROUNDED = box(1, 1, 9, 5).buffer(1, join_style=BufferJoinStyle.round)


def grip_of(grips, kind):
    return next(grip for grip in grips.grips if grip[0] == kind)


def test_arc_grips_replace_the_inner_vertex_grips():
    grips, editor, shape = make_grips(ROUNDED)
    kinds = [grip[0] for grip in grips.grips]
    assert kinds.count('arc_end') == 8 and kinds.count('arc_mid') == 4 and kinds.count('mid') == 4
    assert len(grips.collection().items) == 16


def test_drag_of_an_arc_middle_bends_the_arc():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, middle = grip_of(grips, 'arc_mid')
    cursor = (middle[0] - 0.2, middle[1] - 0.2)
    assert drag(grips, middle, cursor)
    editor.apply_vertex_edit.assert_called_once_with('arc_mid', address, cursor, target=shape, on_segment=False)


def test_drag_of_an_arc_end_moves_the_end():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, point = grip_of(grips, 'arc_end')
    cursor = (point[0] + 0.25, point[1] - 0.25)
    assert drag(grips, point, cursor)
    editor.apply_vertex_edit.assert_called_once_with('arc_end', address, cursor, target=shape, on_segment=False)


def test_ctrl_click_on_an_arc_middle_flattens_the_arc():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, middle = grip_of(grips, 'arc_mid')
    assert grips.press((0, 0), middle, CTRL)
    assert grips.release((0, 0), middle)
    editor.apply_vertex_edit.assert_called_once_with('arc_flatten', address, target=shape)


def test_ctrl_click_on_an_arc_end_removes_the_vertex():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, point = grip_of(grips, 'arc_end')
    assert grips.press((0, 0), point, CTRL)
    assert grips.release((0, 0), point)
    editor.apply_vertex_edit.assert_called_once_with('remove', address, target=shape)


def test_full_circle_radius_drag():
    grips, editor, shape = make_grips(Point(0, 0).buffer(2))
    assert [grip[0] for grip in grips.grips] == ['radius'] * 4
    kind, address, point = grips.grips[0]
    assert drag(grips, point, (3, 0))
    editor.apply_vertex_edit.assert_called_once_with('arc_radius', address, (3.0, 0.0), target=shape,
                                                     on_segment=False)


def test_ctrl_click_on_a_radius_grip_does_nothing():
    grips, editor, shape = make_grips(Point(0, 0).buffer(2))
    kind, address, point = grips.grips[0]
    assert grips.press((0, 0), point, CTRL)
    assert grips.release((0, 0), point)
    editor.apply_vertex_edit.assert_not_called()


def test_preview_of_an_arc_bend_uses_the_circle_steps():
    grips, editor, shape = make_grips(ROUNDED)
    editor.app.options['geometry_circle_steps'] = 8
    kind, address, middle = grip_of(grips, 'arc_mid')
    assert grips.press((0, 0), middle, NO_MOD)
    grips.move((20, 0), (middle[0] - 0.2, middle[1] - 0.2))
    preview = editor.tool_shape.items[-1][0]
    assert len(preview.coords) < len(ROUNDED.exterior.coords)


def test_grid_on_picks_the_nearest_grip_within_1_grid_step():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=True)
    editor.editor_options = {'global_gridx': 0.5, 'global_gridy': 0.25}
    assert grips.hit((0.3, 0.2)) == ('vertex', (0, 0, 0), (0, 0))  # 0.36 away: outside 6 px, inside 1 grid step
    assert grips.hit((0.5, 1.0)) is None


def test_grid_off_keeps_the_pixel_hit_radius():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=False)
    editor.editor_options = {'global_gridx': 0.5, 'global_gridy': 0.25}
    assert grips.hit((0.3, 0.2)) is None
