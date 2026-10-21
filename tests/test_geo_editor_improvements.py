"""Geometry picking uses screen intent; affine replacements retain ready render buffers."""
from types import SimpleNamespace
from unittest.mock import Mock
from copy import deepcopy
import pickle

import numpy as np
import pytest
from PyQt6 import QtCore, QtWidgets
from shapely import LineString, Polygon, box

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape, FCSelect, FCMove
from appGUI.VisPyVisuals import ShapeCollectionVisual
from tests.test_geo_editor_delete_plot import pick_editor
from tests.test_geo_editor_history import editor_with_history, interactive_move_editor, run_worker


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_overlap_cycles_and_preserves_unrelated_multiselection(monkeypatch):
    big, small, other = [DrawToolShape(geo) for geo in (box(0, 0, 10, 10), box(4, 4, 6, 6), box(20, 0, 21, 1))]
    editor = pick_editor([big, small, other])
    editor.selected = [other]
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        lambda: QtCore.Qt.KeyboardModifier.ControlModifier)
    editor.click_select((5, 5))
    assert editor.selected == [other, small]
    editor.click_select((5.01, 5))
    assert editor.selected == [other, big]
    editor.click_select((5, 5))
    assert editor.selected == [other, small]
    assert '2' in str(editor.app.inform.emit.call_args_list)
    # Moving farther than five pixels resets even when the same polygons overlap.
    editor.click_select((5.2, 5))
    assert editor.selected == [other]


def test_cycle_resets_on_mutation_and_equal_distance_order_is_stable():
    shapes = [DrawToolShape(LineString([(0, 0), (10, 0)])) for _ in range(3)]
    editor = pick_editor(shapes)
    editor.click_select((5, 0))
    assert editor.selected == [shapes[0]]
    editor.click_select((5, 0))
    assert editor.selected == [shapes[1]]
    shapes[2].geo = LineString([(0, 1), (10, 1)])
    editor.click_select((5, 0))
    assert editor.selected == [shapes[0]]


def test_unchanged_pick_does_not_scan_storage_and_direct_geometry_edits_invalidate():
    shape = DrawToolShape(LineString([(0, 0), (1, 0)]))
    editor = pick_editor([shape])
    first, _ = editor.get_pick_index()
    editor.storage.get_objects = Mock(wraps=editor.storage.get_objects)
    assert editor.get_pick_index()[0] is first
    editor.storage.get_objects.assert_not_called()
    shape.offset((10, 0))
    assert editor.get_pick_index()[0] is not first
    assert editor.pick_at((10.5, 0)) is shape
    assert editor.pick_at((0.5, 0)) is None


def test_pick_cache_tracks_same_count_storage_replacement_history_worker_and_rollback():
    a, b = [DrawToolShape(LineString([(x, 0), (x + 1, 0)])) for x in (0, 10)]
    editor = editor_with_history([a], [a])
    editor.canvas = SimpleNamespace(pixel_size=lambda: 0.01)
    editor.get_pick_index = lambda: AppGeoEditor.get_pick_index(editor)
    first, _ = editor.get_pick_index()
    editor.replace_shapes([a], [b], [b])
    assert editor.get_pick_index()[1] == [b]
    assert editor.undo()
    assert editor.get_pick_index()[1] == [a]
    assert editor.redo()
    assert editor.get_pick_index()[1] == [b]
    with pytest.raises(ValueError):
        with editor.history_operation():
            editor.replace_shapes([b], [a])
            assert editor.get_pick_index()[1] == [a]
            raise ValueError('rollback')
    assert editor.get_pick_index()[1] == [b]
    editor.submit_worker(lambda: editor.replace_shapes([b], [a]), [])
    run_worker(editor)
    assert editor.get_pick_index()[1] == [a]
    assert editor.get_pick_index()[0] is not first
    editor.storage = AppGeoEditor.make_storage()
    assert editor.get_pick_index() == (None, [])


def canvas_editor():
    editor, _, _ = interactive_move_editor()
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: (pos[0] / 100, pos[1] / 100))
    editor.snap = Mock(return_value=(0, 0))
    editor.app.grid_status = lambda: True
    editor.app.delete_selection_shape = Mock()
    editor.draw_selection_area_handler = Mock()
    editor.app.selection_type = None
    tool = FCSelect.__new__(FCSelect)
    tool.draw_app, tool.name = editor, 'select'
    tool.click_release = Mock()
    editor.active_tool = tool
    return editor


@pytest.mark.parametrize('delta,marquee', [(3, False), (5, True), (20, True), (-20, True)])
def test_raw_selection_and_screen_drag_threshold(delta, marquee):
    editor = canvas_editor()
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    assert editor.pos == (0.23, 0.37)
    # A canvas can report dragging even for tiny movement.
    editor.app.selection_type = delta >= 0
    AppGeoEditor.on_canvas_click_release(editor, SimpleNamespace(pos=(23 + delta, 37), button=1))
    if marquee:
        editor.draw_selection_area_handler.assert_called_once_with(
            (0.23, 0.37), ((23 + delta) / 100, 0.37), delta >= 0)
        editor.active_tool.click_release.assert_not_called()
    else:
        editor.active_tool.click_release.assert_called_once_with((0.23, 0.37))
        editor.draw_selection_area_handler.assert_not_called()


@pytest.mark.parametrize('name,attrs,raw', [
    ('select', {}, True), ('simplification', {}, True), ('split', {}, False),
    ('move', {'has_selection': False}, True), ('move', {'has_selection': True}, False),
    ('copy', {'has_selection': False}, True), ('copy', {'has_selection': True}, False),
    ('eraser', {}, True), ('path', {}, False), ('rectangle', {}, False),
])
def test_raw_pick_policy_is_stage_specific(name, attrs, raw):
    editor = SimpleNamespace(active_tool=SimpleNamespace(name=name, **attrs), selected=[])
    assert AppGeoEditor._tool_wants_raw_pick(editor) is raw
    if name == 'eraser':
        editor.selected = [object()]
        assert not AppGeoEditor._tool_wants_raw_pick(editor)


def render_editor(monkeypatch):
    monkeypatch.setattr(ShapeCollectionVisual, '_ShapeCollectionVisual__update', lambda self: None)
    shape = DrawToolShape(Polygon([(0, 0), (4, 0), (4, 3), (0, 3)], [[(1, 1), (2, 1), (2, 2), (1, 2)]]))
    editor = editor_with_history([shape], [shape])
    options = {'global_graphic_engine_3d_no_mp': True, 'global_backface_culling': True}
    editor.shapes = ShapeCollectionVisual(layers=3, fcoptions=options)
    editor.sel_shapes = ShapeCollectionVisual(layers=3, fcoptions=options)
    editor.plot_all = lambda: AppGeoEditor.plot_all(editor)
    editor.plot_changes = lambda: AppGeoEditor.plot_changes(editor)
    editor.plot_all()
    editor.plot_shape = Mock(wraps=editor.plot_shape)
    return editor, shape


@pytest.mark.parametrize('method,args,kwargs', [
    ('offset', ((10, -5),), {}), ('rotate', (30,), {'point': (1, 2)}),
    ('scale', (2, 3), {'point': (1, 2)}), ('skew', (20, 10), {'point': (1, 2)}),
    ('mirror', ('X', (1, 2)), {}),
])
def test_affine_reuses_both_buffers_and_replays_replacement_history(monkeypatch, method, args, kwargs):
    editor, source = render_editor(monkeypatch)
    key = editor._rendered[id(source)][3][0]
    selection_key = editor._rendered[id(source)][4][0]
    original = editor.shapes.data[key]['line_pts'].copy()
    AppGeoEditor.transform_shapes(editor, method, *args, **kwargs)
    replacement = editor.selected[0]
    assert replacement is not source
    assert editor._rendered[id(replacement)][3] == [key]
    assert editor._rendered[id(replacement)][4] == [selection_key]
    editor.plot_shape.assert_not_called()
    np.testing.assert_allclose(editor.shapes.data[key]['line_pts'],
                               editor.sel_shapes.data[selection_key]['line_pts'])
    expected = np.asarray([point for ring in (replacement.geo.exterior, *replacement.geo.interiors)
                           for point in ring.coords])
    np.testing.assert_allclose(np.unique(np.round(editor.shapes.data[key]['line_pts'], 4), axis=0),
                               np.unique(np.round(expected, 4), axis=0), atol=1e-4)
    assert editor.undo()
    assert editor.selected == [source]
    np.testing.assert_allclose(editor.shapes.data[key]['line_pts'], original, atol=2e-6)
    assert editor.redo()
    assert editor.selected == [replacement]
    editor.plot_shape.assert_not_called()


def test_interactive_move_records_affine_provenance(monkeypatch):
    editor, source = render_editor(monkeypatch)
    key = editor._rendered[id(source)][3][0]
    tool = FCMove.__new__(FCMove)
    tool.draw_app, tool.origin, tool.destination = editor, (0, 0), (3, 2)
    tool.draw_cursor_data = Mock()
    editor.active_tool = tool
    editor.app.jump_signal = Mock()
    editor.app.options['geometry_editor_milling_type'] = 'cv'
    editor.delete_utility_geometry = Mock()
    tool.make()
    editor.on_shape_complete()
    assert editor._rendered[id(editor.selected[0])][3] == [key]
    editor.plot_shape.assert_not_called()


@pytest.mark.parametrize('failure', ['unavailable', 'not_ready', 'selection_failure', 'singular', 'stale'])
def test_affine_fallback_is_safe(monkeypatch, failure):
    editor, source = render_editor(monkeypatch)
    if failure == 'unavailable':
        monkeypatch.setattr(editor.shapes, 'transform_keys', None)
    elif failure == 'not_ready':
        monkeypatch.setattr(editor.shapes, 'transform_keys', lambda *a, **k: False)
    elif failure == 'selection_failure':
        monkeypatch.setattr(editor.sel_shapes, 'transform_keys', lambda *a, **k: False)
    elif failure == 'stale':
        source.geo = box(10, 10, 11, 11)
    elif failure == 'singular':
        source.geo = LineString([(0, 0), (1, 1)])
        editor.plot_all()
        editor.plot_shape.reset_mock()
    AppGeoEditor.transform_shapes(editor, 'scale', 0 if failure == 'singular' else 2, 1, point=(0, 0))
    assert editor.plot_shape.called
    assert id(source) not in editor._rendered
    assert len(editor.shapes.data) == len(editor.sel_shapes.data)


def test_move_shape_pick_keeps_reference_location_snapped():
    editor = canvas_editor()
    editor.selected = []
    editor.app.jump_signal = Mock()
    tool = FCMove.__new__(FCMove)
    tool.draw_app, tool.storage, tool.name = editor, editor.storage, 'move'
    tool.has_selection, tool.origin, tool.complete = False, None, False
    tool.selection_bbox = Mock()
    editor.active_tool = tool
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    assert tool.has_selection
    assert tool.origin == (0, 0)


def test_selection_move_preview_uses_raw_marquee_and_ignores_small_drag():
    editor = canvas_editor()
    editor.app.app_cursor = Mock()
    editor.app.plotcanvas = SimpleNamespace(cursor_color='black', on_update_text_hud=Mock())
    editor.app.ui.update_location_labels = Mock()
    editor.app.draw_moving_selection_shape = Mock()
    editor.update_utility_geometry = Mock()
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    AppGeoEditor.on_canvas_move(editor, SimpleNamespace(pos=(26, 37), button=1, is_dragging=True))
    editor.app.draw_moving_selection_shape.assert_not_called()
    assert editor.app.selection_type is None
    AppGeoEditor.on_canvas_move(editor, SimpleNamespace(pos=(3, 57), button=1, is_dragging=True))
    assert editor.app.draw_moving_selection_shape.call_args.args[:2] == ((0.23, 0.37), (0.03, 0.57))
    assert editor.app.selection_type is False


def test_selection_marquee_uses_only_x_and_y_of_the_vispy_coords():
    # VisPy translate_coords() gives (x, y, z, w); the marquee and the area pick need (x, y)
    editor = canvas_editor()
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: np.array([pos[0] / 100, pos[1] / 100, 0.0, 1.0]))
    editor.app.app_cursor = Mock()
    editor.app.plotcanvas = SimpleNamespace(cursor_color='black', on_update_text_hud=Mock())
    editor.app.ui.update_location_labels = Mock()
    editor.app.draw_moving_selection_shape = Mock()
    editor.update_utility_geometry = Mock()
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    AppGeoEditor.on_canvas_move(editor, SimpleNamespace(pos=(3, 57), button=1, is_dragging=True))
    start, end = editor.app.draw_moving_selection_shape.call_args.args[:2]
    assert len(start) == 2 and len(end) == 2
    AppGeoEditor.on_canvas_click_release(editor, SimpleNamespace(pos=(3, 57), button=1))
    start, end, __ = editor.draw_selection_area_handler.call_args.args
    assert len(start) == 2 and len(end) == 2


@pytest.mark.parametrize('name,attrs,selected,raw', [
    ('simplification', {}, False, True), ('split', {}, True, False),
    ('copy', {'has_selection': False}, False, True), ('copy', {'has_selection': True}, True, False),
    ('eraser', {}, False, True), ('eraser', {}, True, False), ('path', {}, False, False),
])
def test_canvas_dispatch_keeps_raw_picks_separate_from_placement(name, attrs, selected, raw):
    editor = canvas_editor()
    editor.selected = editor.selected if selected else []
    editor.active_tool = SimpleNamespace(name=name, click=Mock(), **attrs)
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    editor.active_tool.click.assert_called_once_with((0.23, 0.37) if raw else (0, 0))


@pytest.mark.parametrize('name', ['circle', 'rectangle'])
def test_shift_shape_edit_picks_raw_instead_of_copying_coordinates(name, monkeypatch):
    editor = canvas_editor()
    editor.active_tool = SimpleNamespace(name=name, click=Mock())
    editor.app.clipboard = Mock()
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        lambda: QtCore.Qt.KeyboardModifier.ShiftModifier)
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    editor.active_tool.click.assert_called_once_with((0.23, 0.37))
    editor.app.clipboard.setText.assert_not_called()


def test_storage_revision_covers_direct_insert_remove_and_bulk_replace_without_serializing_owners():
    shapes = [DrawToolShape(LineString([(x, 0), (x, 1)])) for x in range(20)]
    editor = pick_editor(shapes)
    tree = editor.get_pick_index()[0]
    editor.storage.remove(shapes[0])
    assert editor.get_pick_index()[0] is not tree
    editor.storage.insert(shapes[0])
    editor.storage.replace(removed=shapes, inserted=shapes)
    tree = editor.get_pick_index()[0]
    revision = editor.storage.revision
    for clone in (deepcopy(shapes[0]), pickle.loads(pickle.dumps(shapes[0]))):
        clone.offset((100, 0))
    assert editor.storage.revision == revision
    assert editor.get_pick_index()[0] is tree
    shapes[0].offset((100, 0))
    assert editor.get_pick_index()[0] is not tree


def test_affine_reuse_follows_selection_changes_and_multistep_history(monkeypatch):
    editor, source = render_editor(monkeypatch)
    editor.selected = []
    editor.plot_changes()
    key = editor._rendered[id(source)][3][0]
    editor.selected = [source]  # model selection can change before the next plot
    AppGeoEditor.transform_shapes(editor, 'offset', (10, 0))
    first = editor.selected[0]
    AppGeoEditor.transform_shapes(editor, 'rotate', 90, point=(0, 0))
    second = editor.selected[0]
    assert editor._rendered[id(second)][3] == [key]
    assert editor.undo() and editor.selected == [first]
    assert editor.undo() and editor.selected == [source]
    assert editor.redo() and editor.redo()
    assert editor._rendered[id(second)][3] == [key]
    editor.selected = []
    editor.plot_changes()
    assert editor._rendered[id(second)][4] == []
    assert editor.shapes.data[key]['visible']
    editor.plot_shape.assert_not_called()
