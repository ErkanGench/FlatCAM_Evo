"""Selection-tool segment stretching, rubber-band cords and atomic editor commits."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore
from shapely.geometry import LineString, Polygon, MultiLineString, box

from appEditors.segment_ops import segment_geometries
from appEditors.appGeoEditor import AppGeoEditor
from tests.test_geo_editor_vertex_drag import drag_editor
from tests.test_gerber_editor_vertices import track_editor, region_editor
from tests.test_vertex_grips import FakeCollection
from tests.test_gerber_editor_pick import make_editor, make_select, aperture, pad, event, modifiers
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appGUI.MainGUI import MainGUI

CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
SHIFT_ONLY = QtCore.Qt.KeyboardModifier.ShiftModifier
STRETCH = CTRL | QtCore.Qt.KeyboardModifier.ShiftModifier
CORDS = CTRL | QtCore.Qt.KeyboardModifier.AltModifier
NONE = QtCore.Qt.KeyboardModifier.NoModifier


def test_shift_moves_shared_vertices_once_and_stretches_neighbors():
    line = LineString([(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)])
    result = segment_geometries({'line': line}, {'line': {(0, 0, 1), (0, 0, 2)}}, (0, 2))
    assert list(result['line'].coords) == [(0, 0), (2, 2), (4, 2), (6, 2), (8, 0)]


def test_alt_connected_polyline_gets_cords_only_at_outer_extremities():
    line = LineString([(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)])
    result = segment_geometries({'line': line}, {'line': {(0, 0, 1), (0, 0, 2)}}, (0, 2), cords=True)
    assert list(result['line'].coords) == [(0, 0), (2, 0), (2, 2), (4, 2), (6, 2), (6, 0), (8, 0)]


def test_alt_disconnected_groups_each_get_their_own_cords():
    line = LineString([(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)])
    result = segment_geometries({'line': line}, {'line': {(0, 0, 1), (0, 0, 3)}}, (0, 2), cords=True)
    assert list(result['line'].coords) == [
        (0, 0), (2, 0), (2, 2), (4, 2), (4, 0), (6, 0), (6, 2), (8, 2), (8, 0), (10, 0)]


def test_alt_joined_records_do_not_get_internal_cords():
    geometries = {'a': LineString([(0, 0), (2, 0)]), 'b': LineString([(2, 0), (4, 0)])}
    result = segment_geometries(geometries, {key: {(0, 0, 0)} for key in geometries}, (0, 2), cords=True)
    assert list(result['a'].coords) == [(0, 0), (0, 2), (2, 2)]
    assert list(result['b'].coords) == [(2, 2), (4, 2), (4, 0)]


def test_shift_stretches_a_neighboring_record_at_the_shared_endpoint():
    geometries = {'a': LineString([(0, 0), (2, 0)]), 'b': LineString([(2, 0), (4, 0)])}
    result = segment_geometries(geometries, {'a': {(0, 0, 0)}}, (0, 2))
    assert list(result['b'].coords) == [(2, 2), (4, 0)]


def test_alt_closed_ring_wraparound_is_one_group_and_preserves_holes():
    polygon = Polygon([(0, 0), (8, 0), (8, 8), (0, 8)], [[(3, 3), (4, 3), (4, 4), (3, 4)]])
    result = segment_geometries({'p': polygon}, {'p': {(0, 0, 3), (0, 0, 0)}}, (-1, -1), cords=True)['p']
    assert list(result.exterior.coords) == [(-1, -1), (7, -1), (8, 0), (8, 8), (0, 8), (-1, 7), (-1, -1)]
    assert list(result.interiors[0].coords) == list(polygon.interiors[0].coords)


def test_alt_multipart_groups_remain_separate():
    geometry = MultiLineString([[(0, 0), (4, 0)], [(10, 0), (14, 0)]])
    result = segment_geometries({'m': geometry}, {'m': {(0, 0, 0), (1, 0, 0)}}, (0, 2), cords=True)['m']
    assert list(result.geoms[0].coords) == [(0, 0), (0, 2), (4, 2), (4, 0)]
    assert list(result.geoms[1].coords) == [(10, 0), (10, 2), (14, 2), (14, 0)]


def test_invalid_result_is_rejected_and_zero_offset_is_a_noop():
    line = LineString([(0, 0), (2, 0), (2, 2), (0, 2)])
    selected = {'l': {(0, 0, 1)}}
    with pytest.raises(ValueError):
        segment_geometries({'l': line}, selected, (-2, 0))
    assert segment_geometries({'l': line}, selected, (0, 0), cords=True) == {}
    with pytest.raises(ValueError):
        segment_geometries({'l': line}, selected, (float('nan'), 0))


def geo_drag(geometry):
    editor, original = drag_editor(geometry)
    editor.apply_selection_drag = lambda *a, **k: AppGeoEditor.apply_selection_drag(editor, *a, **k)
    editor.get_pick_index = lambda: AppGeoEditor.get_pick_index(editor)
    editor.pick_candidates = lambda point: AppGeoEditor.pick_candidates(editor, point)
    return editor, original


@pytest.mark.parametrize('modifier,expected', [
    (STRETCH, [(0, 0), (2, 2), (6, 2), (8, 0)]),
    (CORDS, [(0, 0), (2, 0), (2, 2), (6, 2), (6, 0), (8, 0)]),
    (NONE, [(0, 2), (2, 2), (6, 2), (8, 2)]),
])
def test_geo_direct_drag_commits_once_and_undo_redo_restore(modifier, expected):
    editor, original = geo_drag(LineString([(0, 0), (2, 0), (6, 0), (8, 0)]))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (3, 0), modifier)
    assert grips.move((20, 0), (3, 2))
    assert editor.selected == [original]
    assert grips.release((20, 0), (3, 2))
    assert list(editor.selected[0].geo.coords) == expected
    assert len(editor._history_undo) == 1
    assert editor.undo() and editor.selected == [original]
    assert editor.redo() and list(editor.selected[0].geo.coords) == expected


def test_ctrl_alt_click_accumulates_segments_then_drags_them_as_one_polyline():
    editor, original = geo_drag(LineString([(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]))
    grips = editor.vertex_grips
    for point in ((3, 0), (5, 0)):
        assert grips.press((0, 0), point, CORDS)
        assert grips.release((0, 0), point)
    assert not editor._history_undo
    assert grips.press((0, 0), (3, 0), CORDS)
    grips.release((20, 0), (3, 2))
    assert list(editor.selected[0].geo.coords) == [(0, 0), (2, 0), (2, 2), (4, 2), (6, 2), (6, 0), (8, 0)]
    assert len(editor._history_undo) == 1


def test_cancel_and_tool_change_do_not_commit_segment_drags():
    editor, original = geo_drag(LineString([(0, 0), (4, 0)]))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (1, 0), CORDS)
    grips.move((20, 0), (1, 2))
    grips.cancel()
    assert not grips.release((20, 0), (1, 2))
    assert editor.selected == [original] and not editor._history_undo
    editor.active_tool.name = 'move'
    assert not grips.press((0, 0), (1, 0), STRETCH)


@pytest.mark.parametrize('modifier', [STRETCH, CORDS])
def test_gerber_trace_drag_preserves_width_and_one_undo_step(modifier):
    editor, original = track_editor(LineString([(0, 0), (4, 0), (8, 0), (12, 0)]))
    editor.tool_shape = FakeCollection()
    grips = editor.vertex_grips
    grips.sync()
    assert grips.press((0, 0), (5, 0), modifier)
    grips.release((20, 0), (5, 2))
    result = editor.selected[0]
    assert result is not original
    assert result.geo['solid'].equals_exact(result.geo['follow'].buffer(0.2, 16), 1e-9)
    assert len(editor.history.undo_stack) == 1
    assert editor.undo() and editor.selected == [original]
    assert editor.redo()


def test_gerber_region_drag_keeps_solid_and_follow_consistent():
    editor, original = region_editor(box(0, 0, 10, 10))
    editor.tool_shape = FakeCollection()
    grips = editor.vertex_grips
    grips.sync()
    assert grips.press((0, 0), (10, 3), CORDS)
    grips.release((20, 0), (12, 3))
    result = editor.selected[0]
    assert result.geo['solid'].bounds == (0, 0, 12, 10)
    assert list(result.geo['solid'].exterior.coords) == list(result.geo['follow'].coords)
    assert len(editor.history.undo_stack) == 1


def test_segment_highlight_is_visible_on_press_without_a_geometry_change():
    editor, original = geo_drag(LineString([(0, 0), (4, 0), (8, 0)]))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (1, 0), CORDS)
    assert len(grips.segment_drag._collection.items) == 1
    assert list(grips.segment_drag._collection.items[0][0].coords) == [(0, 0), (4, 0)]
    grips.release((0, 0), (1, 0))
    assert editor.selected == [original] and not editor._history_undo


def test_grid_snaps_the_displacement_without_a_jump_at_the_press():
    editor, original = geo_drag(LineString([(0, 0), (4, 0)]))
    editor.app.grid_status = lambda: True
    editor.editor_options = {'global_gridx': 0.1, 'global_gridy': 0.1}
    editor.snap = lambda x, y: (round(x), round(y))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (1.2, 0), CORDS)
    grips.release((20, 0), (1.3, 1.7))
    assert list(editor.selected[0].geo.coords) == [(0, 0), (0, 2), (4, 2), (4, 0)]


def test_external_geometry_change_during_drag_prevents_commit():
    editor, original = geo_drag(LineString([(0, 0), (4, 0)]))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (1, 0), CORDS)
    original.geo = LineString([(0, 0), (5, 0)])
    grips.release((20, 0), (1, 2))
    assert editor.selected == [original] and not editor._history_undo
    assert list(original.geo.coords) == [(0, 0), (5, 0)]


def test_gerber_segment_selection_of_separate_records_drags_as_one_polyline():
    first = LineString([(0, 0), (4, 0)])
    second = LineString([(4, 0), (8, 0)])
    shapes = [DrawToolShape({'follow': line, 'solid': line.buffer(0.2, 16)}) for line in (first, second)]
    editor = make_editor({10: {'type': 'C', 'size': 0.4, 'geometry': shapes[:]}})
    editor.history.reset()
    make_select(editor)
    editor.tool_shape = FakeCollection()
    grips = editor.vertex_grips
    for point in ((1, 0), (5, 0)):
        assert grips.press((0, 0), point, CORDS)
        grips.release((0, 0), point)
    assert len(grips.segment_drag.selected) == 2
    assert grips.press((0, 0), (1, 0), CORDS)
    grips.release((20, 0), (1, 2))
    a, b = editor.selected
    assert list(a.geo['follow'].coords) == [(0, 0), (0, 2), (4, 2)]
    assert list(b.geo['follow'].coords) == [(4, 2), (8, 2), (8, 0)]
    assert len(editor.history.undo_stack) == 1
    assert editor.undo() and editor.selected == shapes


def test_gerber_plain_drag_moves_a_flash_and_keeps_flash_semantics():
    shape = pad(0, 0, 1)
    editor = make_editor({10: {'type': 'C', 'size': 2, 'geometry': [shape]}})
    editor.history.reset()
    make_select(editor)
    editor.tool_shape = FakeCollection()
    grips = editor.vertex_grips
    assert grips.press((0, 0), (0, 0), NONE)
    grips.release((20, 0), (3, 2))
    result = editor.selected[0]
    assert tuple(result.geo['follow'].coords[0]) == (3, 2)
    assert result in editor.history.translated_shapes
    assert editor.undo() and editor.selected == [shape]


def test_gerber_canvas_ctrl_shift_drag_is_not_copied_to_clipboard_or_area_selected():
    editor, original = track_editor(LineString([(0, 0), (4, 0), (8, 0)]))
    editor.tool_shape = FakeCollection()
    with modifiers(STRETCH):
        editor.on_canvas_click(event(1, 0))
        editor.on_canvas_move(event(1, 6, dragging=1))
        editor.on_canvas_click_release(event(1, 6))
    assert list(editor.selected[0].geo['follow'].coords) == [(0, 6), (4, 6), (8, 0)]
    editor.app.clipboard.setText.assert_not_called()
    editor.app.draw_moving_selection_shape.assert_not_called()


def test_gerber_ctrl_shift_drag_stretches_an_unselected_neighbor_record_in_the_same_undo_step():
    lines = [LineString([(0, 0), (4, 0)]), LineString([(4, 0), (8, 0)])]
    shapes = [DrawToolShape({'follow': line, 'solid': line.buffer(0.2, 16)}) for line in lines]
    editor = make_editor({10: {'type': 'C', 'size': 0.4, 'geometry': shapes[:]}})
    editor.history.reset()
    make_select(editor)
    editor.tool_shape = FakeCollection()
    editor.selected = [shapes[0]]
    grips = editor.vertex_grips
    grips.sync()
    assert grips.press((0, 0), (1, 0), STRETCH)
    grips.release((20, 0), (1, 2))
    a, b = editor.storage_dict[10]['geometry']
    assert list(a.geo['follow'].coords) == [(0, 2), (4, 2)]
    assert list(b.geo['follow'].coords) == [(4, 2), (8, 0)]
    assert editor.selected == [a]
    assert len(editor.history.undo_stack) == 1
    assert editor.undo() and editor.storage_dict[10]['geometry'] == shapes


def test_accumulated_disconnected_segment_groups_move_together_with_independent_cords():
    editor, original = geo_drag(LineString([(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)]))
    grips = editor.vertex_grips
    for point in ((3, 0), (7, 0)):
        assert grips.press((0, 0), point, CORDS)
        grips.release((0, 0), point)
    assert grips.press((0, 0), (3, 0), CORDS)
    grips.release((20, 0), (3, 2))
    assert list(editor.selected[0].geo.coords) == [
        (0, 0), (2, 0), (2, 2), (4, 2), (4, 0), (6, 0), (6, 2), (8, 2), (8, 0), (10, 0)]
    assert len(editor._history_undo) == 1


def test_invalid_drag_preview_is_red_and_release_preserves_geometry_and_history():
    editor, original = geo_drag(LineString([(0, 0), (2, 0), (2, 2), (0, 2)]))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (2, 0.5), STRETCH)
    grips.move((20, 0), (0, 0.5))
    assert editor.tool_shape.items[-1][1]['color'] == grips.colors()[1]
    grips.release((20, 0), (0, 0.5))
    assert editor.selected == [original] and not editor._history_undo


def test_ctrl_clicking_empty_canvas_keeps_additive_object_selection_available():
    editor, original = geo_drag(LineString([(0, 0), (4, 0)]))
    assert not editor.vertex_grips.press((0, 0), (20, 20), CTRL)
    assert editor.selected == [original]


@pytest.mark.parametrize('modifier', [CTRL, SHIFT_ONLY, QtCore.Qt.KeyboardModifier.AltModifier])
def test_single_modifier_click_on_a_segment_stays_with_the_editor(modifier):
    # Ctrl+click toggles the shape selection and Shift+click copies the coordinates: the editor does both.
    editor, original = geo_drag(LineString([(0, 0), (4, 0), (8, 0)]))
    grips = editor.vertex_grips
    assert not grips.press((0, 0), (1, 0), modifier)
    assert grips.segment_drag.pressed is None and not grips.segment_drag.selected
    assert editor.selected == [original]


def test_ctrl_click_on_a_midpoint_grip_stays_with_the_editor():
    editor, original = geo_drag(LineString([(0, 0), (4, 0), (8, 0)]))
    grips = editor.vertex_grips
    grips.sync()
    assert not grips.press((0, 0), (2, 0), CTRL)
    assert grips.pressed is None


def test_segment_click_toggles_the_segment_and_keeps_the_shape_selected():
    editor, original = geo_drag(LineString([(0, 0), (4, 0), (8, 0)]))
    grips = editor.vertex_grips
    for point in ((1, 0), (5, 0)):
        assert grips.press((0, 0), point, STRETCH)
        grips.release((0, 0), point)
    assert grips.segment_drag.selected == {original: {(0, 0, 0), (0, 0, 1)}}
    assert grips.press((0, 0), (1, 0), CORDS)
    grips.release((0, 0), (1, 0))
    assert grips.segment_drag.selected == {original: {(0, 0, 1)}}
    assert editor.selected == [original] and not editor._history_undo


@pytest.mark.parametrize('modifier,expected', [
    (STRETCH, [(0, 0), (2, 2), (6, 2), (8, 0)]),
    (CORDS, [(0, 0), (2, 0), (2, 2), (6, 2), (6, 0), (8, 0)]),
])
def test_segment_drag_wins_over_a_vertex_grip_with_the_grid_on(modifier, expected):
    # With the grid on, a vertex grip catches 1 grid step around the vertex: the segment gesture must win.
    editor, original = geo_drag(LineString([(0, 0), (2, 0), (6, 0), (8, 0)]))
    editor.app.grid_status = lambda: True
    editor.snap = lambda x, y: (round(x), round(y))
    grips = editor.vertex_grips
    grips.grid_step = lambda: 1.0
    grips.sync()
    assert grips.press((0, 0), (2.4, 0), modifier)
    assert grips.pressed is None
    grips.release((20, 0), (2.4, 2))
    assert list(editor.selected[0].geo.coords) == expected


@pytest.mark.parametrize('source', ['geo_editor', 'grb_editor'])
@pytest.mark.parametrize('modifier', [STRETCH, CORDS])
def test_escape_cancels_a_drag_while_the_modifier_is_still_held(source, modifier):
    if source == 'geo_editor':
        editor, original = geo_drag(LineString([(0, 0), (4, 0), (8, 0)]))
        editor.app.collection = Mock()
    else:
        editor, original = track_editor(LineString([(0, 0), (4, 0), (8, 0)]))
        editor.tool_shape = FakeCollection()
    editor.app.call_source = source
    setattr(editor.app, source, editor)
    grips = editor.vertex_grips
    assert grips.press((0, 0), (1, 0), modifier)
    grips.move((20, 0), (1, 2))
    with modifiers(modifier):
        MainGUI.keyPressEvent(SimpleNamespace(app=editor.app), int(QtCore.Qt.Key.Key_Escape))
    assert not grips.release((20, 0), (1, 2))
    assert editor.selected == [original]
