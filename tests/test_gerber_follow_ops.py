"""Native Gerber FOLLOW operations and selected-only circular flash resizing."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely import LineString, Point
from shapely.ops import unary_union

from appEditors.appGerberEditor import AppGerberEditor
from appEditors.grb_plugins import GrbFollowPlugin as module
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appEditors.grb_plugins.GrbTrackBend import sweep_parameters
from appParsers.ParseGerber import Gerber
from test_editor_save_modes import gerber_stand_in
from test_gerber_editor_pick import make_editor
from test_unify_characterization import app, _headless_qt, make_gerber, NATIVE_GBR  # noqa: F401


def track(coords, width=2):
    follow = LineString(coords)
    return DrawToolShape({'follow': follow, 'solid': follow.buffer(width / 2, 16)})


def flash(x, diameter=2):
    follow = Point(x, 4)
    return DrawToolShape({'follow': follow, 'solid': follow.buffer(diameter / 2, 16)})


def editor_for(shapes):
    editor = make_editor({10: {'type': 'C', 'size': 2, 'geometry': shapes}})
    editor.loaded_as_regions = False
    editor.selected = list(shapes)
    return editor


def footprint(editor):
    return unary_union([shape.geo['solid'] for aperture in editor.storage_dict.values()
                        for shape in aperture['geometry']])


def test_split_keeps_width_ownership_order_selection_and_one_history_step():
    first, path, last = flash(-5), track([(0, 0), (10, 0), (10, 10)]), flash(20)
    editor = editor_for([first, path, last])
    editor.selected = [path]
    before, revision = footprint(editor), editor.geometry_revision
    assert editor.apply_path_split((5, 0.001), 0.01) != 'fail'
    pieces = editor.selected
    assert len(pieces) == 2
    assert list(pieces[0].geo['follow'].coords) == [(0, 0), (5, 0)]
    assert list(pieces[1].geo['follow'].coords) == [(5, 0), (10, 0), (10, 10)]
    assert editor.storage_dict[10]['geometry'] == [first, *pieces, last]
    assert editor.storage_dict[10]['size'] == 2
    assert footprint(editor).symmetric_difference(before).area < 1e-10
    assert not editor.loaded_as_regions
    assert editor.geometry_revision == revision + 1
    assert len(editor.history.undo_stack) == 1
    editor.plot_all.assert_called_once()
    assert editor.undo()
    assert editor.selected == [path]
    assert editor.storage_dict[10]['geometry'] == [first, path, last]
    assert editor.redo()
    assert editor.selected == pieces


def test_join_reversed_records_preserves_material_and_unrelated_order():
    a, b = track([(0, 0), (5, 0)]), track([(10, 0), (5, 0)])
    unrelated = flash(30)
    editor = editor_for([a, unrelated, b])
    editor.selected = [b, a]
    before = footprint(editor)
    assert editor.apply_path_join(0) != 'fail'
    result = editor.selected[0]
    assert result.geo['follow'].equals(LineString([(0, 0), (5, 0), (10, 0)]))
    assert result.geo['solid'].equals(unary_union([a.geo['solid'], b.geo['solid']]))
    assert editor.storage_dict[10]['geometry'] == [result, unrelated]
    assert footprint(editor).equals(before)
    assert not editor.loaded_as_regions
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [a, unrelated, b]
    assert editor.selected == [b, a]
    assert editor.redo()


@pytest.mark.parametrize('kind', ['branch', 'interior_branch', 'mixed', 'clear', 'modified', 'gap', 'overlap', 'alias'])
def test_join_rejects_incompatible_records_without_mutation(kind):
    a, b = track([(0, 0), (5, 0)]), track([(5, 0), (10, 0)])
    editor = editor_for([a, b])
    if kind == 'branch':
        editor.storage_dict[10]['geometry'].append(track([(5, 0), (5, 5)]))
    elif kind == 'interior_branch':
        editor.storage_dict[10]['geometry'].append(track([(2, 0), (2, 5)]))
    elif kind == 'mixed':
        editor.storage_dict[10]['geometry'].remove(b)
        editor.storage_dict[11] = {'type': 'C', 'size': 2, 'geometry': [b]}
    elif kind == 'clear':
        b.geo['clear'] = Point(5, 0).buffer(0.1)
    elif kind == 'modified':
        b.geo['solid'] = b.geo['solid'].buffer(0.1)
    elif kind == 'gap':
        b.geo.update(track([(5.001, 0), (10, 0)]).geo)
    elif kind == 'overlap':
        b.geo.update(track([(5, 0), (2, 0)]).geo)
    else:
        editor.storage_dict[11] = {'type': 'C', 'size': 2, 'geometry': [a]}
    original = {key: list(value['geometry']) for key, value in editor.storage_dict.items()}
    revision = editor.geometry_revision
    assert editor.apply_path_join(0.01) == 'fail'
    assert {key: value['geometry'] for key, value in editor.storage_dict.items()} == original
    assert editor.selected == [a, b]
    assert editor.geometry_revision == revision
    assert not editor.history.undo_stack
    editor.plot_all.assert_not_called()


@pytest.mark.parametrize('point,tolerance', [((0, 0), 0), ((20, 0), 0.01), ((5, 2), 0.01),
                                           ((float('nan'), 0), 1), ((5, 0), -1), ((5, 0), float('inf'))])
def test_invalid_split_is_atomic(point, tolerance):
    path = track([(0, 0), (10, 0)])
    editor = editor_for([path])
    revision = editor.geometry_revision
    assert editor.apply_path_split(point, tolerance) == 'fail'
    assert editor.selected == [path]
    assert editor.storage_dict[10]['geometry'] == [path]
    assert editor.geometry_revision == revision
    assert not editor.history.undo_stack


def test_split_tool_wiring_uses_click_and_rejects_stale_session():
    path = track([(0, 0), (10, 0)])
    editor = editor_for([path])
    editor.select_tool.reset_mock()
    editor.ui.split_action.trigger()
    editor.select_tool.assert_called_once_with('split')
    tool = editor.tools_gerber['split']['constructor'](editor)
    editor.history.reset()
    assert tool.click((5, 0)) == 'fail'
    assert not editor.history.undo_stack
    tool = editor.tools_gerber['split']['constructor'](editor)
    tool.click((5, 0))
    assert len(editor.selected) == 2
    editor.ui.join_tolerance_entry.setText('0')
    editor.ui.join_btn.click()
    assert len(editor.selected) == 1
    assert len(editor.history.undo_stack) == 2


def test_selected_flash_resize_reuses_matching_metadata_without_touching_shared_aperture():
    a, b, line = flash(0), flash(5), track([(0, 0), (10, 0)])
    editor = editor_for([a, b, line])
    editor.storage_dict[10]['tag'] = {'net': 'GND'}
    editor.storage_dict['11'] = {'type': 'C', 'size': 4, 'tag': {'net': 'GND'}, 'geometry': []}
    editor.selected = [a, line]
    editor.ui.resize_circles_entry.set_value(4)
    editor.ui.resize_circles_btn.click()
    resized = editor.selected[0]
    assert editor.selected[1] is line
    assert editor.storage_dict[10]['geometry'] == [b, line]
    assert editor.storage_dict['11']['geometry'] == [resized]
    assert resized.geo['follow'].equals(a.geo['follow'])
    assert resized.geo['solid'].equals(Point(0, 4).buffer(2, 16))
    assert editor.storage_dict[10]['size'] == 2
    assert len(editor.history.undo_stack) == 1
    assert not editor.loaded_as_regions
    assert editor.undo()
    assert editor.selected == [a, line]
    assert editor.storage_dict[10]['geometry'] == [a, b, line]
    assert editor.storage_dict['11']['geometry'] == []
    assert editor.redo()


def test_resize_creates_aperture_and_undo_removes_it():
    a, b = flash(0), flash(5)
    editor = editor_for([a, b])
    editor.selected = [a]
    editor.storage_dict[10]['tag'] = 'keep'
    assert editor.apply_resize_circles(3) != 'fail'
    assert list(editor.storage_dict) == [10, 11]
    assert editor.storage_dict[11]['tag'] == 'keep'
    assert editor.storage_dict[10]['geometry'] == [b]
    assert editor.undo()
    assert list(editor.storage_dict) == [10]
    assert editor.redo()
    assert editor.storage_dict[11]['size'] == 3


@pytest.mark.parametrize('diameter', [0, -1, float('nan'), float('inf'), 'bad'])
def test_invalid_diameter_does_not_mutate(diameter):
    a = flash(0)
    editor = editor_for([a])
    assert editor.apply_resize_circles(diameter) == 'fail'
    assert editor.storage_dict[10]['geometry'] == [a]
    assert not editor.history.undo_stack


@pytest.mark.parametrize('kind', ['hole', 'macro', 'clear', 'modified'])
def test_unsupported_flash_does_not_mutate(kind):
    a = flash(0)
    editor = editor_for([a])
    if kind == 'hole':
        a.geo['solid'] = a.geo['solid'].difference(Point(0, 4).buffer(0.1))
    elif kind == 'macro':
        editor.storage_dict[10]['type'] = 'AM'
    elif kind == 'clear':
        a.geo['clear'] = Point(0, 4).buffer(0.1)
    else:
        a.geo['solid'] = a.geo['solid'].buffer(0.1)
    assert editor.apply_resize_circles(3) == 'fail'
    assert editor.storage_dict[10]['geometry'] == [a]
    assert not editor.history.undo_stack


@pytest.mark.parametrize('operation,args', [('apply_path_split', ((5, 0), 0)),
                                         ('apply_path_join', (0,)), ('apply_resize_circles', (3,))])
def test_operations_guard_pending_worker_and_non_gui_thread(operation, args):
    a, b = track([(0, 0), (5, 0)]), track([(5, 0), (10, 0)])
    editor = editor_for([a, b])
    original = list(editor.storage_dict[10]['geometry'])
    editor.history.pending = object()
    assert getattr(editor, operation)(*args) == 'fail'
    editor.history.pending = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(getattr(editor, operation), *args).result() == 'fail'
    assert editor.storage_dict[10]['geometry'] == original
    assert not editor.history.undo_stack


@pytest.mark.parametrize('operation', ['split', 'join', 'resize'])
def test_native_save_reparse_after_operation_undo_redo(app, operation):

    source = make_gerber(app, NATIVE_GBR, name='board')
    if operation == 'split':
        editor = editor_for([track([(0, 0), (10, 0)])])
        assert editor.apply_path_split((5, 0), 0) != 'fail'
    elif operation == 'join':
        editor = editor_for([track([(0, 0), (5, 0)]), track([(10, 0), (5, 0)])])
        assert editor.apply_path_join(0) != 'fail'
    else:
        editor = editor_for([flash(0), flash(5)])
        editor.selected = [editor.selected[0]]
        assert editor.apply_resize_circles(4) != 'fail'
    for mode in ('edited', 'undo', 'redo'):
        if mode == 'undo':
            assert editor.undo()
        elif mode == 'redo':
            assert editor.redo()
        assert not editor.loaded_as_regions
        stand_in = gerber_stand_in(app, source, editor.storage_dict)
        stand_in.loaded_as_regions = False
        AppGerberEditor.build_edited_gerber(stand_in, 'board', editor.storage_dict)
        result = app.custom_signal.emit.call_args.args[0]
        assert 'error' not in result
        assert 'G36' not in result['obj'].source_file
        parsed = Gerber(app, steps_per_circle=16)
        assert parsed.parse_lines(result['obj'].source_file.splitlines()) is None
        assert unary_union(parsed.solid_geometry).hausdorff_distance(footprint(editor)) < 0.002


def test_joined_record_can_be_split_and_bend_validated_again():

    editor = editor_for([track([(0, 0), (5, 0)]), track([(10, 0), (5, 0)])])
    assert editor.apply_path_join(0) != 'fail'
    assert sweep_parameters(editor, editor.storage_dict[10], editor.selected[0]) == (1, 16)
    assert editor.apply_path_split((7, 0), 0) != 'fail'


def test_real_split_canvas_press_release_keeps_both_pieces_selected(monkeypatch):
    path = track([(0, 0), (10, 0)])
    editor = editor_for([path])
    editor.select_tool = AppGerberEditor.select_tool.__get__(editor)
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.NoModifier))
    editor.ui.split_btn.click()
    assert editor.active_tool.name == 'split'
    event = SimpleNamespace(pos=(5, 0), button=1, is_dragging=False)
    editor.on_canvas_click(event)
    pieces = list(editor.selected)
    assert len(pieces) == 2
    editor.on_canvas_click_release(event)
    assert editor.selected == pieces
    assert editor.active_tool.name == 'select'
    editor.plot_all.assert_called_once()


@pytest.mark.parametrize('change', ['revision', 'state', 'selection'])
def test_split_tool_rejects_changed_scene(change):
    path = track([(0, 0), (10, 0)])
    editor = editor_for([path])
    tool = editor.tools_gerber['split']['constructor'](editor)
    if change == 'revision':
        editor.touch_geometry()
    elif change == 'state':
        editor.storage_dict[10]['geometry'].append(flash(20))
    else:
        editor.selected = [flash(20)]
    assert tool.click((5, 0)) == 'fail'
    assert not editor.history.undo_stack


def test_branch_split_rejected_and_unselected_flash_remains_untouched():
    path, branch, pad = track([(0, 0), (10, 0)]), track([(5, 0), (5, 5)]), flash(5)
    editor = editor_for([path, branch, pad])
    editor.selected = [path]
    assert editor.apply_path_split((2, 0), 0) == 'fail'
    assert editor.storage_dict[10]['geometry'] == [path, branch, pad]
    assert not editor.history.undo_stack


def test_resize_multiple_sources_preserves_metadata_and_existing_target_order():
    a, b, existing = flash(0), flash(5, 3), flash(10, 4)
    editor = editor_for([a])
    editor.storage_dict['11'] = {'type': 'C', 'size': 3, 'geometry': [b]}
    editor.storage_dict[12] = {'type': 'C', 'size': 4, 'geometry': [existing]}
    editor.selected = [b, a, existing]
    revision = editor.geometry_revision
    assert editor.apply_resize_circles(4) != 'fail'
    assert editor.storage_dict[12]['geometry'] == [existing, *editor.selected[:2]]
    assert editor.selected[-1] is existing
    assert editor.geometry_revision == revision + 1
    editor.plot_all.assert_called_once()
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [a]
    assert editor.storage_dict['11']['geometry'] == [b]
    assert editor.storage_dict[12]['geometry'] == [existing]


def test_resize_rejects_whole_batch_if_later_flash_is_unsupported():
    a, b = flash(0), flash(5)
    editor = editor_for([a, b])
    b.geo['solid'] = b.geo['solid'].difference(Point(5, 4).buffer(0.1))
    revision = editor.geometry_revision
    assert editor.apply_resize_circles(4) == 'fail'
    assert list(editor.storage_dict) == [10]
    assert editor.storage_dict[10]['geometry'] == [a, b]
    assert editor.geometry_revision == revision
    assert not editor.history.undo_stack


def test_join_independent_components_keeps_selected_unjoined_record():
    a, b = track([(0, 0), (5, 0)]), track([(5, 0), (10, 0)])
    c, d = track([(0, 10), (5, 10)]), track([(10, 10), (5, 10)])
    isolated = track([(20, 20), (30, 20)])
    editor = editor_for([a, b, isolated, c, d])
    assert editor.apply_path_join(0) != 'fail'
    assert len(editor.selected) == 3
    assert editor.selected[1] is isolated
    assert len(editor.history.undo_stack) == 1


@pytest.mark.parametrize('reuse', [False, True])
def test_real_aperture_ui_rebuild_preserves_feature_selection_and_mixed_key_ownership(reuse):
    a, b = flash(0), flash(5)
    editor = editor_for([a, b])
    editor.gerber_obj = SimpleNamespace(obj_options={'name': 'board'}, steps_per_circle=16)
    if reuse:
        editor.storage_dict['11'] = {'type': 'C', 'size': 4, 'geometry': []}
    editor.build_ui = AppGerberEditor.build_ui.__get__(editor)
    editor.selected = [a]
    assert editor.apply_resize_circles(4) != 'fail'
    resized = editor.selected[0]
    assert editor.selected == [resized]
    assert editor.ui.apertures_table.rowCount() == 2
    assert len(editor.ui.features_table.selectionModel().selectedRows()) == 1
    assert editor.undo()
    assert editor.selected == [a]
    assert editor.redo()
    assert editor.selected == [resized]


@pytest.mark.parametrize('operation', ['apply_path_split', 'apply_path_join'])
def test_follow_rechecks_revision_after_sweep_computation(monkeypatch, operation):

    a, b = track([(0, 0), (5, 0)]), track([(5, 0), (10, 0)])
    editor = editor_for([a, b])
    if operation == 'apply_path_split':
        editor.selected = [a]
    original = module.sweep_parameters

    def changed(*args):
        result = original(*args)
        editor.touch_geometry()
        return result

    monkeypatch.setattr(module, 'sweep_parameters', changed)
    args = ((2, 0), 0) if operation == 'apply_path_split' else (0,)
    assert getattr(editor, operation)(*args) == 'fail'
    assert editor.storage_dict[10]['geometry'] == [a, b]
    assert not editor.history.undo_stack


def test_split_rejects_overlapping_records_even_when_the_follow_instance_is_shared():
    a = track([(0, 0), (10, 0)])
    duplicate = DrawToolShape(dict(a.geo))
    editor = editor_for([a, duplicate])
    editor.selected = [a]
    assert editor.apply_path_split((5, 0), 0) == 'fail'
    assert editor.storage_dict[10]['geometry'] == [a, duplicate]
    assert not editor.history.undo_stack
