"""Split one open path at a projected click, in one committed operation."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtWidgets
from shapely.geometry import LineString, LinearRing, MultiLineString, Polygon

from appEditors import appGeoEditor as geo
from appGUI.GUIElements import FCTree
from tests.test_geo_editor_history import run_worker
from tests.test_geo_editor_vertices import vertex_editor


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def split_editor(geometry=None):
    editor, original = vertex_editor(geometry if geometry is not None else
                                     LineString([(0, 0), (2, 0), (4, 2)]))
    editor.multigeo_tool = 7
    original.data['tool'] = 7
    editor.apply_path_split = lambda *a, **k: geo.AppGeoEditor.apply_path_split(editor, *a, **k)
    return editor, original


@pytest.mark.parametrize('point', [(2, 0), (1, 0), (3, 1), (1, 0.05), (1, 0.1)])
@pytest.mark.parametrize('reverse', [False, True])
def test_split_conserves_length_direction_metadata_and_replays(point, reverse):
    coords = [(0, 0), (2, 0), (4, 2)]
    editor, original = split_editor(LineString(coords[::-1] if reverse else coords))
    editor.storage.replace = Mock(wraps=editor.storage.replace)
    editor._snap_cache = object()
    assert editor.apply_path_split(point, 0.1) != 'fail'
    a, b = editor.selected
    assert a.geo.length > 0 and b.geo.length > 0
    assert a.geo.length + b.geo.length == pytest.approx(original.geo.length)
    assert a.geo.coords[0] == original.geo.coords[0]
    assert b.geo.coords[-1] == original.geo.coords[-1]
    assert a.geo.coords[-1] == b.geo.coords[0]
    assert original.geo.distance(geo.Point(a.geo.coords[-1])) < 1e-12
    for shape in (a, b):
        assert shape.data['custom'] == original.data['custom']
        assert shape.data['tool'] == 7
        assert shape.data['bounds'] == shape.geo.bounds
        assert shape.data is not original.data
    assert editor.multigeo_tool == 7
    assert editor._snap_cache is None
    assert set(editor.storage.indexes) == {id(a), id(b)}
    assert editor.storage.nearest(a.geo.coords[0])[1] is a
    assert editor.sel_shapes.items == [a.geo, b.geo]
    editor.storage.replace.assert_called_once()
    assert len(editor._history_undo) == 1
    assert editor.undo()
    assert editor.selected == [original]
    assert list(editor.storage.get_objects()) == [original]
    assert editor.sel_shapes.items == [original.geo]
    assert not editor.undo()
    assert editor.redo()
    assert editor.selected == [a, b]
    assert editor.sel_shapes.items == [a.geo, b.geo]


@pytest.mark.parametrize('point,tolerance', [
    ((0, 0), 0.1), ((4, 0), 0.1), ((0.05, 0), 0.1), ((3.95, 0), 0.1),
    ((-1, 0), 0.1), ((5, 0), 0.1), ((2, 0.101), 0.1),
    ((2, float('nan')), 0.1), ((float('inf'), 0), 0.1),
    (('bad', 0), 0.1), ((2,), 0.1), ((2, 0), -1), ((2, 0), float('nan')),
    ((2, 0), float('inf')), ((2, 0), 'bad'),
])
def test_rejection_preserves_original_selection_render_cache_and_redo(point, tolerance):
    editor, original = split_editor(LineString([(0, 0), (4, 0)]))
    assert editor.apply_path_split((2, 0), 0.1) != 'fail'
    assert editor.undo()
    redo = list(editor._history_redo)
    cache = editor._snap_cache = object()
    editor.build_ui_sig.emit.reset_mock()
    assert editor.apply_path_split(point, tolerance) == 'fail'
    assert list(editor.storage.get_objects()) == [original]
    assert editor.selected == [original]
    assert editor.sel_shapes.items == [original.geo]
    assert editor._snap_cache is cache
    assert editor._history_redo == redo
    editor.build_ui_sig.emit.assert_not_called()
    assert editor.app.inform.emit.called
    assert editor.redo()


@pytest.mark.parametrize('geometry', [
    LinearRing([(0, 0), (4, 0), (0, 4)]),
    LineString([(0, 0), (4, 0), (0, 4), (0, 0)]),
    Polygon([(0, 0), (4, 0), (0, 4)]),
    MultiLineString([[(0, 0), (4, 0)], [(4, 0), (6, 0)]]),
    LineString([(0, 0, 1), (4, 0, 1)]),
])
def test_unsupported_shapes_explain_open_linestring_scope(geometry):
    editor, original = split_editor(geometry)
    assert editor.apply_path_split((2, 0), 0.1) == 'fail'
    assert 'open' in str(editor.app.inform.emit.call_args).lower()
    assert 'LineString' in str(editor.app.inform.emit.call_args)
    assert editor.selected == [original]
    assert not editor.undo()


@pytest.mark.parametrize('selection', [[], [0, 0]])
def test_exactly_one_stored_selection_required(selection):
    editor, original = split_editor()
    editor.selected = [original for _ in selection]
    assert editor.apply_path_split((1, 0), 0.1) == 'fail'
    assert 'one' in str(editor.app.inform.emit.call_args).lower()
    assert list(editor.storage.get_objects()) == [original]
    assert not editor.undo()


def test_zero_tolerance_accepts_exact_interior_and_rejects_offpath():
    editor, original = split_editor()
    assert editor.apply_path_split((1, 0.001), 0) == 'fail'
    assert editor.apply_path_split((1, 0), 0) != 'fail'


def interactive_editor():
    editor, original = split_editor(LineString([(0, 0), (4, 0)]))
    editor.decimals = 4
    editor.app.decimals = 4
    editor.app.app_units = 'mm'
    editor.app.resource_location = ''
    editor.app.on_editing_finished = Mock()
    editor.ui = geo.AppGeoEditorUI(editor.app)
    editor.select_tool = Mock()
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: pos)
    editor.app.grid_status = lambda: False
    editor.app.ui = SimpleNamespace(rel_position_label=Mock())
    editor.snap = Mock(return_value=(2, 0.05))
    editor.active_tool = geo.FCSplit(editor)
    return editor, original


def test_canvas_uses_snapped_click_and_explicit_units_tolerance():
    editor, original = interactive_editor()
    editor.ui.split_tolerance_entry.setText('0.1')
    assert geo.AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(9, 9), button=1)) != 'fail'
    assert len(editor.selected) == 2
    assert editor.selected[0].geo.coords[-1] == (2, 0)
    editor.snap.assert_called_once_with(9, 9)
    editor.select_tool.assert_called_once_with('select')


@pytest.mark.parametrize('change', ['busy', 'session', 'selection', 'other_selection', 'removed'])
def test_tool_rejects_busy_or_stale_targets_without_consuming(change):
    editor, original = interactive_editor()
    tool = editor.active_tool
    if change == 'busy':
        editor.submit_worker(Mock(), [])
    elif change == 'session':
        editor.reset_history()
    elif change == 'selection':
        editor.selected = []
    elif change == 'other_selection':
        other = geo.DrawToolShape(LineString([(0, 0), (8, 0)]))
        editor.storage.insert(other)
        editor.selected = [other]
    else:
        editor.storage.remove(original)
    assert tool.click((2, 0)) == 'fail'
    editor.select_tool.assert_not_called()
    assert not editor.undo()
    if change == 'busy':
        run_worker(editor)
        assert tool.click((2, 0)) != 'fail'
        assert len(editor._history_undo) == 1


def test_rejected_click_allows_retry_and_cancel_creates_no_history():
    editor, original = interactive_editor()
    tool = editor.active_tool
    assert tool.click((0, 0)) == 'fail'
    assert editor.selected == [original]
    assert tool.click((2, 0)) != 'fail'
    assert editor.undo()
    editor.active_tool = geo.FCSplit(editor)
    editor.app.ui.popMenu = SimpleNamespace(mouse_is_panning=False)
    editor.delete_utility_geometry = lambda: geo.AppGeoEditor.delete_utility_geometry(editor)
    geo.AppGeoEditor.on_canvas_click_release(editor, SimpleNamespace(pos=(2, 0), button=2))
    editor.select_tool.assert_called_with('select')
    assert editor.active_tool.complete
    assert not editor.undo()
    assert editor.redo()


def test_split_and_replay_synchronize_tree_index_and_render():
    editor, original = split_editor()
    tree = FCTree(columns=3, extended_sel=True)
    editor.ui = SimpleNamespace(tw=tree, geo_parent=tree.invisibleRootItem(), geo_font=tree.font())
    editor.sync_tree_selection = lambda: geo.AppGeoEditor.sync_tree_selection(editor)
    editor.build_ui_sig.emit = lambda: geo.AppGeoEditor.build_ui(editor)
    geo.AppGeoEditor.build_ui(editor)
    assert editor.apply_path_split((1, 0), 0.1) != 'fail'
    pieces = list(editor.selected)
    for selected, replay in [(pieces, editor.undo), ([original], editor.redo), (pieces, None)]:
        assert tree.topLevelItemCount() == len(selected)
        assert {item.text(0) for item in tree.selectedItems()} == {str(id(s)) for s in selected}
        assert set(editor.storage.indexes) == {id(s) for s in selected}
        assert editor._snap_cache is None
        if replay:
            assert replay()


def test_discoverable_button_activates_registered_split_tool():
    editor, original = interactive_editor()
    editor.app.ui = Mock()
    editor.tools = {}
    editor.make_callback = geo.AppGeoEditor.make_callback.__get__(editor)
    editor.on_tool_select = geo.AppGeoEditor.on_tool_select.__get__(editor)
    editor.select_tool = geo.AppGeoEditor.select_tool.__get__(editor)
    geo.AppGeoEditor.connect_geo_toolbar_signals(editor)
    editor.active_tool = None
    assert editor.ui.split_btn.text() == 'Split path'
    assert 'current units' in editor.ui.split_tolerance_entry.toolTip()
    editor.ui.split_btn.click()
    assert isinstance(editor.active_tool, geo.FCSplit)
    assert editor.active_tool.target is original
    assert editor.tools['split']['button'].isChecked()
    assert not editor.undo()
