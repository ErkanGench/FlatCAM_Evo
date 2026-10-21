"""Gerber-local history records affected records, not board snapshots."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import Point, LineString, MultiPolygon, Polygon, box
from shapely.affinity import translate
from shapely.ops import unary_union

from appEditors.appGerberEditor import (AppGerberEditor, CopyEditorGrb, MoveEditorGrb, EraserEditorGrb,
                                       ImportEditorGrb, PoligonizeEditorGrb, TrackEditorGrb)
from appEditors.grb_plugins.GrbBufferPlugin import BufferEditorTool
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appEditors.grb_plugins.GrbTransformationPlugin import queue_transform
from appGUI.MainGUI import MainGUI
from appHandlers.appSignalConnector import AppSignalConnector
from appMain import App
from appParsers.ParseGerber import Gerber
from test_gerber_editor_pick import make_editor, aperture, pad, trace
import test_gerber_editor_pick as pick_cases
from test_editor_save_modes import gerber_stand_in, gerber_storage
from test_gerber_editor_size_simplify import simplify_tool, run_job
from test_gerber_track_bend import editor_for, start, release, track
from test_grb_editor_transform import Host
from test_unify_characterization import app, _headless_qt, make_gerber, NATIVE_GBR  # noqa: F401


def scene():
    first = DrawToolShape({'solid': box(0, 0, 1, 1), 'follow': Point(0.5, 0.5)})
    second = DrawToolShape({'solid': box(10, 0, 11, 1), 'follow': Point(10.5, 0.5)})
    editor = make_editor({10: aperture([first]), 11: aperture([second])})
    editor.history.reset()
    return editor, first, second


def test_delete_is_one_step_and_restores_identity_selection_and_order():
    editor, first, second = scene()
    editor.selected = [first]
    editor.delete_selected()
    assert len(editor.history.undo_stack) == 1
    assert editor.storage_dict[10]['geometry'] == []
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [first]
    assert editor.selected == [first]
    assert list(editor.storage_dict) == [10, 11]
    assert not editor.is_modified
    assert editor.redo()
    assert editor.storage_dict[10]['geometry'] == []
    assert editor.storage_dict[11]['geometry'] == [second]


def test_nested_mutations_group_and_capture_immutable_geometry_values():
    editor, first, second = scene()
    editor.selected = [first]
    old = dict(first.geo)
    with editor.history.operation('Move then copy') as accepted:
        assert accepted
        first.geo['solid'] = translate(first.geo['solid'], xoff=2)
        first.geo['follow'] = translate(first.geo['follow'], xoff=2)
        editor.touch_geometry()
        added = DrawToolShape({'solid': box(5, 5, 6, 6)})
        editor.add_gerber_shape(added, editor.storage_dict[10]['geometry'])
    assert len(editor.history.undo_stack) == 1
    assert editor.history.undo_stack[0]['label'] == 'Move then copy'
    assert editor.undo()
    assert first.geo == old
    assert editor.storage_dict[10]['geometry'] == [first]
    assert editor.redo()
    assert editor.storage_dict[10]['geometry'] == [first, added]
    assert first.geo['follow'].equals(Point(2.5, 0.5))


def test_transaction_rolls_back_geometry_apertures_flags_and_selection_on_exception():
    editor, first, second = scene()
    editor.selected = [first]
    old = dict(first.geo)
    with pytest.raises(ValueError):
        with editor.history.operation('Broken'):
            first.geo['solid'] = box(1, 1, 2, 2)
            editor.storage_dict[10]['geometry'].clear()
            editor.storage_dict[99] = {'type': 'REG', 'size': 0, 'geometry': []}
            editor.loaded_as_regions = True
            editor.selected = []
            raise ValueError('computation failed')
    assert first.geo == old
    assert editor.storage_dict[10]['geometry'] == [first]
    assert list(editor.storage_dict) == [10, 11]
    assert editor.selected == [first]
    assert not getattr(editor, 'loaded_as_regions', False)
    assert editor.history.undo_stack == []


def test_branching_limits_and_non_mutating_selection():
    editor, first, second = scene()
    editor.app.options['global_history_steps'] = 2
    for index in range(3):
        editor.add_gerber_shape(DrawToolShape({'solid': box(index, 3, index + 1, 4)}),
                                editor.storage_dict[10]['geometry'])
    assert len(editor.history.undo_stack) == 2
    assert editor.history.baseline_evicted
    assert editor.undo()
    editor.selected = [second]
    editor.plot_selection()
    assert len(editor.history.redo_stack) == 1
    editor.delete_selected()
    assert editor.history.redo_stack == []
    assert not editor.redo()


def test_aperture_delete_and_add_restore_metadata_as_one_group():
    editor, first, second = scene()
    editor.last_aperture_selected = 10
    with editor.history.operation('Replace aperture'):
        editor.on_aperture_delete(ap_code=[10])
        editor.ui.apsize_entry.set_value(0.5)
        editor.on_aperture_add(12)
    assert 10 not in editor.storage_dict
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [first]
    assert 12 not in editor.storage_dict
    assert editor.last_aperture_selected == 10


def test_retained_delta_does_not_capture_unchanged_board_geometry():
    editor, first, second = scene()
    editor.selected = [first]
    editor.delete_selected()
    delta = editor.history.undo_stack[-1]['apertures']
    assert set(delta) == {10}
    assert second not in editor.history.retained_shapes()


def test_worker_computes_detached_geometry_then_commits_one_step_on_gui():
    editor, first, second = scene()
    editor.selected = [first]
    old = dict(first.geo)

    def compute(shapes):
        shapes[0].geo['solid'] = translate(shapes[0].geo['solid'], xoff=2)
        shapes[0].geo['follow'] = translate(shapes[0].geo['follow'], xoff=2)

    assert editor.submit_geometry('Move', compute) != 'fail'
    assert not editor.undo()
    job = editor.app.worker_task.emit.call_args.args[0]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(job['fcn'], *job['params']).result(timeout=10)
    assert first.geo == old
    QtWidgets.QApplication.processEvents()
    assert first.geo['follow'].equals(Point(2.5, 0.5))
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert first.geo == old


def test_worker_failure_and_cancelled_session_do_not_commit():
    editor, first, second = scene()
    editor.selected = [first]

    def fail(shapes):
        shapes[0].geo['solid'] = box(2, 2, 3, 3)
        raise ValueError('bad')

    editor.submit_geometry('Broken', fail)
    job = editor.app.worker_task.emit.call_args.args[0]
    job['fcn'](*job['params'])
    QtWidgets.QApplication.processEvents()
    assert first.geo['solid'].equals(box(0, 0, 1, 1))
    assert editor.history.undo_stack == []
    editor.submit_geometry('Later', lambda shapes: None)
    job = editor.app.worker_task.emit.call_args.args[0]
    editor.clear()
    job['fcn'](*job['params'])
    QtWidgets.QApplication.processEvents()
    assert editor.storage_dict == {}
    assert editor.history.undo_stack == []


def test_component_diagnostics_are_read_only_and_do_not_mix_solid_and_follow():
    editor, first, second = scene()
    line = LineString([(0, 0), (1, 0)])
    first.geo = {'solid': line.buffer(0.1), 'follow': line}
    second.geo = {'solid': box(3, 3, 4, 4), 'follow': LineString([(1.005, 0), (2, 0)])}
    editor.selected = [first, second]
    revision = editor.geometry_revision
    report = editor.diagnose_selected('follow', 0.01)
    assert len(report['open']) == 2
    assert len(report['near_endpoints']) == 1
    assert report['duplicate'] == []
    solid = editor.diagnose_selected('solid', 0.01)
    assert solid['open'] == []
    assert editor.selected == [first, second]
    assert editor.geometry_revision == revision
    assert editor.history.undo_stack == []
    editor.plot_all.assert_not_called()


@pytest.mark.parametrize('tolerance', [-1, float('nan'), float('inf')])
def test_diagnostics_reject_bad_tolerance_without_history(tolerance):
    editor, first, second = scene()
    editor.selected = [first]
    assert editor.diagnose_selected('solid', tolerance) == 'fail'
    assert editor.history.undo_stack == []


def snapshot(editor):
    return {key: ({name: value for name, value in aperture.items() if name != 'geometry'},
                  [(shape, dict(shape.geo)) for shape in aperture.get('geometry', ())])
            for key, aperture in editor.storage_dict.items()}


@pytest.mark.parametrize('family', ['pad', 'array', 'region', 'disc', 'semidisc', 'track', 'move', 'copy',
                                    'erase', 'polygonize', 'mark_delete', 'buffer', 'scale', 'transform',
                                    'simplify', 'import'])
def test_mutation_family_round_trip_is_one_step(family):
    first, second = pad(0, 0, 1), pad(10, 0, 1)
    editor = make_editor({10: {'type': 'C', 'size': 2.0, 'geometry': [first, second]}})
    editor.gerber_obj = SimpleNamespace(obj_options={'name': 'board'})
    editor.history.reset()
    editor.selected = [first]
    editor.sync_aperture_rows({10})
    editor.is_modified = False
    before = snapshot(editor)
    before_regions = getattr(editor, 'loaded_as_regions', False)
    if family in ('pad', 'array', 'region', 'disc', 'semidisc'):
        geometry = pad(4, 4, 1)
        editor.active_tool = SimpleNamespace(name=family, geometry=geometry)
        shapes = [geometry, pad(6, 4, 1)] if family == 'array' else geometry
        editor.on_grb_shape_complete(editor.storage_dict[10]['geometry'], specific_shape=shapes)
    elif family == 'track':
        tool = TrackEditorGrb.__new__(TrackEditorGrb)
        tool.draw_app, tool.app = editor, editor.app
        tool.points, tool.temp_points, tool.click_shapes = [], [(0, 0), (3, 0), (3, 3)], []
        tool.buf_val, tool.steps_per_circle = 1, 16
        tool.track_tool = SimpleNamespace(length=1)
        editor.snap_x, editor.snap_y = 3, 3
        tool.ui = SimpleNamespace(x_entry=MagicMock(), y_entry=MagicMock())
        tool.click((3, 3))
    elif family in ('move', 'copy'):
        tool = (MoveEditorGrb if family == 'move' else CopyEditorGrb)(editor)
        editor.active_tool = tool
        tool.origin, tool.destination = (0, 0), (0, 5)
        tool.make()
    elif family == 'erase':
        editor = make_editor({10: {'type': 'C', 'size': 0.4, 'geometry': [trace(0, 0, 10, 0, 0.4)]}})
        tool = pick_cases.TestEraserMake().eraser(editor, 5, 0)
        before = snapshot(editor)
        tool.make()
    elif family == 'polygonize':
        tool = PoligonizeEditorGrb(editor)
        tool.make()
    elif family == 'mark_delete':
        editor.geo_to_delete = [first]
        editor.delete_marked_polygons()
    elif family == 'buffer':
        BufferEditorTool.buffer(SimpleNamespace(draw_app=editor, app=editor.app), 0.1, 1)
    elif family == 'scale':
        editor.ui.scale_factor_entry.set_value(1.2)
        editor.on_scale()
    elif family == 'transform':
        Host(editor).on_offset('X', 2)
    elif family == 'simplify':
        simplify_tool(editor).on_simplification_click()
        run_job(editor)
    else:
        tool = SimpleNamespace(draw_app=editor, app=editor.app, sel_storage=[{
            'type': 'REG', 'size': 0, 'geometry': [DrawToolShape({'solid': box(5, 5, 6, 6)})]}])
        ImportEditorGrb.import_shapes(tool)
    after = snapshot(editor)
    after_regions = getattr(editor, 'loaded_as_regions', False)
    assert after != before
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert snapshot(editor) == before
    assert getattr(editor, 'loaded_as_regions', False) == before_regions
    assert editor.redo()
    assert snapshot(editor) == after
    assert getattr(editor, 'loaded_as_regions', False) == after_regions


def test_track_backspace_is_its_own_reversible_committed_action():
    first = trace(0, 0, 3, 0, 0.4)
    editor = make_editor({10: {'type': 'C', 'size': 0.4, 'geometry': [first]}})
    tool = TrackEditorGrb.__new__(TrackEditorGrb)
    tool.draw_app, tool.app = editor, editor.app
    tool.points, tool.temp_points = [(0, 0), (3, 0)], [(0, 0), (3, 0)]
    tool.click_shapes = [(first, editor.storage_dict[10]['geometry'])]
    tool.utility_geometry = lambda data: None
    editor.draw_utility_geometry = MagicMock()
    tool.on_key('Backspace')
    assert editor.storage_dict[10]['geometry'] == []
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [first]


def test_bend_joins_normal_history_and_undo_can_cross_other_edits():
    first = track([(0, 0), (4, 0), (4, 4)])
    editor = editor_for([first])
    editor.history.reset()
    start(editor, (4, 0))
    release(editor, (5, 1))
    moved = editor.storage_dict[10]['geometry'][0]
    assert len(editor.history.undo_stack) == 1
    editor.selected = [moved]
    editor.delete_selected()
    assert len(editor.history.undo_stack) == 2
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [moved]
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [first]
    assert editor.redo()
    assert editor.storage_dict[10]['geometry'] == [moved]


def test_legacy_buffer_keeps_follow_and_records_region_export_requirement():
    first = pad(0, 0, 1)
    editor = make_editor({10: {'type': 'C', 'size': 2, 'geometry': [first]}})
    editor.selected = [first]
    editor.sync_aperture_rows({10})
    follow = first.geo['follow']
    BufferEditorTool.buffer(SimpleNamespace(draw_app=editor, app=editor.app), 0.1, 1)
    assert first.geo['follow'] is follow
    assert editor.loaded_as_regions
    assert editor.undo()
    assert not editor.loaded_as_regions


def test_menu_buffer_does_not_activate_simplification():
    editor, first, second = scene()
    for connection in editor.app.ui.grb_add_buffer_menuitem.triggered.connect.call_args_list:
        connection.args[0]()
    editor.select_tool.assert_called_once_with('buffer')


def test_busy_operations_reject_mutation_save_and_selection():
    editor, first, second = scene()
    editor.selected = [first]
    editor.submit_geometry('Pending', lambda shapes: None)
    assert editor.delete_selected() == 'fail'
    assert editor.on_aperture_add(99) == 'fail'
    assert editor.on_table_selection() == 'fail'
    assert editor.update_fcgerber_in_place() == 'fail'
    assert editor.update_fcgerber() == 'fail'
    assert editor.storage_dict[10]['geometry'] == [first]


@pytest.mark.parametrize('action', ['undo', 'redo', 'shift_redo'])
def test_keyboard_history_routing_and_native_text_undo(action):
    editor, first, second = scene()
    editor.app.call_source = 'grb_editor'
    editor.app.grb_editor = editor
    editor.undo, editor.redo = MagicMock(), MagicMock()
    ctrl = QtCore.Qt.KeyboardModifier.ControlModifier
    modifiers = ctrl | QtCore.Qt.KeyboardModifier.ShiftModifier if action == 'shift_redo' else ctrl
    key = QtCore.Qt.Key.Key_Y if action == 'redo' else QtCore.Qt.Key.Key_Z
    with patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=modifiers), \
            patch.object(MainGUI, 'app_focus_in_text', return_value=False):
        MainGUI.keyPressEvent(SimpleNamespace(app=editor.app), int(key))
    (editor.undo if action == 'undo' else editor.redo).assert_called_once()
    editor.undo.reset_mock()
    editor.redo.reset_mock()
    with patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=modifiers), \
            patch.object(MainGUI, 'app_focus_in_text', return_value=True):
        MainGUI.keyPressEvent(SimpleNamespace(app=editor.app), int(key))
    editor.undo.assert_not_called()
    editor.redo.assert_not_called()


def test_property_component_selector_displays_follow_not_outline():
    editor, first, second = scene()
    first.geo = {'solid': box(0, 0, 5, 2), 'follow': LineString([(0, 0), (3, 0), (3, 4)])}
    editor.selected = [first]
    editor.ui.diagnostics_component.setCurrentIndex(1)
    editor.update_ui()
    assert 'LINESTRING' in editor.ui.geo_coords_entry.toPlainText()
    assert float(editor.ui.geo_vertex_entry.get_value()) == 3
    assert '7.0000' in editor.ui.component_properties.text()
    assert editor.history.undo_stack == []


@pytest.mark.parametrize('column,text', [(1, '12'), (3, '0.5')])
def test_aperture_table_edits_restore_metadata_records_selection_and_aliases(column, text):
    editor, first, second = scene()
    editor.tid2apcode = {1: 10, 2: 11}
    editor.oldapcode_newapcode = {10: 10, 11: 11}
    editor.selected = [first]
    editor.last_aperture_selected = 10
    before = snapshot(editor)
    table = editor.ui.apertures_table
    with QtCore.QSignalBlocker(table):
        table.setItem(0, column, QtWidgets.QTableWidgetItem(text))
        table.setCurrentCell(0, column)
    table.itemChanged.connect(editor.on_tool_edit)
    editor.on_tool_edit()
    after = snapshot(editor)
    assert after != before
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert snapshot(editor) == before
    assert editor.selected == [first]
    assert editor.oldapcode_newapcode == {10: 10, 11: 11}
    assert editor.last_aperture_selected == 10
    assert editor.redo()
    assert snapshot(editor) == after
    if column == 1:
        assert editor.last_aperture_selected == 12
    else:
        assert editor.storage_dict[10]['size'] == 0.5


def test_invalid_buffer_and_failed_nested_action_do_not_leave_partial_edits():
    editor, first, second = scene()
    editor.selected = [first]
    editor.sync_aperture_rows({10})
    before = snapshot(editor)
    result = BufferEditorTool.buffer(SimpleNamespace(draw_app=editor, app=editor.app), float('nan'), 1)
    assert result == 'fail'
    assert snapshot(editor) == before
    assert editor.history.undo_stack == []
    original_storage = editor.storage_dict[10]['geometry']
    with editor.history.operation('Atomic group'):
        editor.delete_selected()
        BufferEditorTool.buffer(SimpleNamespace(draw_app=editor, app=editor.app), float('nan'), 1)
    assert snapshot(editor) == before
    assert editor.storage_dict[10]['geometry'] is original_storage
    assert editor.history.undo_stack == []


def test_memory_budget_retains_one_adjacent_oversize_step_not_a_board_copy():
    editor = make_editor({10: aperture([])})
    editor.app.options['global_history_memory_mb'] = 1
    for cx in (0, 10):
        large = DrawToolShape({'solid': Point(cx, 0).buffer(1, 20000)})
        editor.add_gerber_shape(large, editor.storage_dict[10]['geometry'])
    assert len(editor.history.undo_stack) == 1
    assert editor.history.baseline_evicted
    assert editor.undo()
    assert len(editor.storage_dict[10]['geometry']) == 1
    assert editor.redo()
    assert len(editor.storage_dict[10]['geometry']) == 2


def test_history_limit_reduction_also_bounds_redo_and_timeline_navigation():
    editor, first, second = scene()
    for index in range(3):
        editor.add_gerber_shape(DrawToolShape({'solid': box(index, 2, index + 1, 3)}),
                                editor.storage_dict[10]['geometry'])
    assert editor.history_go_to(0)
    assert len(editor.history.redo_stack) == 3
    editor.app.options['global_history_steps'] = 1
    editor.refresh_history()
    assert len(editor.history.redo_stack) == 1
    assert editor.history_go_to(1)
    assert len(editor.history.undo_stack) == 1
    assert not editor.history_go_to(5)


def test_queued_transform_ui_uses_detached_geometry_and_normal_history():
    editor, first, second = scene()
    editor.selected = [first]
    before = snapshot(editor)
    tool = SimpleNamespace(draw_app=editor, app=editor.app)
    queue_transform(tool, 'offset', ['X', 2])
    job = editor.app.worker_task.emit.call_args.args[0]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(job['fcn'], *job['params']).result(timeout=10)
    assert snapshot(editor) == before
    QtWidgets.QApplication.processEvents()
    assert first.geo['follow'].equals(Point(2.5, 0.5))
    assert editor.undo()
    assert snapshot(editor) == before


def test_stale_worker_revision_releases_busy_state_without_committing():
    editor, first, second = scene()
    editor.selected = [first]
    before = snapshot(editor)
    editor.submit_geometry('Later', lambda shapes: shapes[0].geo.update(solid=box(2, 2, 3, 3)))
    job = editor.app.worker_task.emit.call_args.args[0]
    editor.touch_geometry()
    job['fcn'](*job['params'])
    QtWidgets.QApplication.processEvents()
    assert snapshot(editor) == before
    assert editor.history.pending is None
    assert editor.history.undo_stack == []


@pytest.mark.parametrize('save', ['update_fcgerber', 'update_fcgerber_in_place'])
def test_save_scheduling_failure_releases_editor_reservation(save):
    editor, first, second = scene()
    editor.gerber_obj = SimpleNamespace(obj_options={'name': 'board'})
    editor.gerber_obj_options = {'name': 'board'}
    editor.edited_obj_name = 'board'
    editor.app.worker_task.emit.side_effect = RuntimeError('worker unavailable')
    with pytest.raises(RuntimeError, match='worker unavailable'):
        getattr(editor, save)()
    assert editor.history.pending is None


def test_in_place_save_rejects_result_from_stale_revision():
    editor, first, second = scene()
    editor.gerber_obj = SimpleNamespace(obj_options={'name': 'board'})
    editor.gerber_obj_options = {'name': 'board'}
    editor.update_fcgerber_in_place()
    callback = editor.app.connect_custom_signal.call_args.args[0]
    editor.touch_geometry()
    with patch.object(AppGerberEditor, 'apply_edited_gerber') as apply:
        callback({'obj': object()})
        apply.assert_not_called()
    assert editor.history.pending is None
    assert editor.history.undo_stack == []


def test_busy_editor_exit_is_rejected_before_showing_modal_dialog():
    editor, first, second = scene()
    editor.selected = [first]
    editor.app.call_source = 'grb_editor'
    editor.app.grb_editor = editor
    editor.submit_geometry('Later', lambda shapes: None)
    with patch('appMain.FCMessageBox') as dialog:
        assert App.on_editing_finished(editor.app) == 'fail'
        dialog.assert_not_called()


def test_global_menu_and_toolbar_replay_route_to_the_gerber_editor():
    editor, first, second = scene()
    app = editor.app
    app.call_source = 'grb_editor'
    app.grb_editor = editor
    app.ui.app_focus_in_text.return_value = False
    editor.undo, editor.redo = MagicMock(), MagicMock()
    connector = SimpleNamespace(app=app, ui=app.ui)
    AppSignalConnector.connect_editmenu_signals(connector)
    for action in (app.ui.menuedit_undo, app.ui.undo_btn):
        action.triggered.connect.call_args.args[0]()
    for action in (app.ui.menuedit_redo, app.ui.redo_btn):
        action.triggered.connect.call_args.args[0]()
    assert editor.undo.call_count == 2
    assert editor.redo.call_count == 2


def test_diagnostics_duplicate_missing_empty_and_holes_are_identified_by_aperture():
    editor, first, second = scene()
    first.geo = {'solid': Polygon(box(0, 0, 4, 4).exterior.coords, [box(1, 1, 2, 2).exterior.coords])}
    second.geo = {'solid': first.geo['solid']}
    third = DrawToolShape({'solid': Polygon()})
    editor.storage_dict[11]['geometry'].append(third)
    editor.selected = [first, second, third]
    report = editor.diagnose_selected('solid', 0)
    assert {record[0] for record in report['duplicate']} == {10, 11}
    assert len(report['empty']) == 1
    assert report['open'] == []
    assert len(editor.diagnose_selected('follow', 0)['missing']) == 3
    assert editor.history.undo_stack == []


def test_save_snapshot_is_detached_and_cancelled_callback_cannot_update_source():
    editor, first, second = scene()
    source = SimpleNamespace(obj_options={'name': 'board'})
    editor.gerber_obj = source
    editor.gerber_obj_options = {'name': 'board'}
    editor.update_fcgerber_in_place()
    assert editor.history.pending is not None
    job = editor.app.worker_task.emit.call_args.args[0]
    frozen = job['params'][1][10]['geometry'][0].geo['solid']
    callback = editor.app.connect_custom_signal.call_args.args[0]
    first.geo['solid'] = box(20, 20, 21, 21)
    assert frozen.equals(box(0, 0, 1, 1))
    editor.clear()
    with patch.object(AppGerberEditor, 'apply_edited_gerber') as apply:
        callback({'obj': object()})
        apply.assert_not_called()


def test_load_result_is_gui_committed_and_late_sessions_are_ignored():
    editor, first, second = scene()
    editor.on_multiprocessing_finished = MagicMock()
    pending = editor.history.reserve()
    result = {'pending': pending, 'storage': {12: aperture([pad(4, 4, 1)])}, 'regions': True}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(editor.load_result.emit, result).result(timeout=10)
    assert 12 not in editor.storage_dict
    QtWidgets.QApplication.processEvents()
    assert 12 in editor.storage_dict
    assert editor.loaded_as_regions
    assert editor.history.pending is None
    assert editor.history.undo_stack == []
    pending = editor.history.reserve()
    editor.clear()
    editor.load_result.emit({'pending': pending, 'storage': {13: aperture([])}, 'regions': False})
    assert editor.storage_dict == {}


def test_buffer_undo_redo_save_reparse_preserves_material_and_export_mode(app):

    source = make_gerber(app, NATIVE_GBR, name='board')
    first = DrawToolShape({'solid': Point(4, 4).buffer(1, 16), 'follow': Point(4, 4)})
    editor = make_editor({10: {'type': 'C', 'size': 2, 'geometry': [first]}})
    editor.selected = [first]
    editor.sync_aperture_rows({10})
    BufferEditorTool.buffer(SimpleNamespace(draw_app=editor, app=editor.app), 0.3, 1)
    for mode in ('buffered', 'undo', 'redo'):
        if mode == 'undo':
            assert editor.undo()
        elif mode == 'redo':
            assert editor.redo()
        stand_in = gerber_stand_in(app, source, editor.storage_dict)
        stand_in.loaded_as_regions = getattr(editor, 'loaded_as_regions', False)
        AppGerberEditor.build_edited_gerber(stand_in, 'board', editor.storage_dict)
        result = app.custom_signal.emit.call_args.args[0]
        assert 'error' not in result
        saved = result['obj']
        assert saved.export_as_regions is (mode != 'undo')
        parsed = Gerber(app, steps_per_circle=16)
        assert parsed.parse_lines(saved.source_file.splitlines()) is None
        actual = unary_union(parsed.solid_geometry)
        expected = unary_union([shape.geo['solid'] for aperture in editor.storage_dict.values()
                                for shape in aperture.get('geometry', ())])
        assert actual.hausdorff_distance(expected) < 0.001


def test_missing_component_clears_properties_instead_of_showing_solid():
    editor, first, second = scene()
    editor.selected = [first]
    editor.update_ui()
    editor.ui.diagnostics_component.setCurrentIndex(2)
    editor.update_ui()
    assert editor.ui.geo_coords_entry.toPlainText() == ''
    assert float(editor.ui.geo_vertex_entry.get_value()) == 0
    assert float(editor.ui.area_entry.get_value()) == 0
    assert editor.ui.is_valid_entry.text() == 'None'
    assert editor.history.undo_stack == []


def test_component_properties_count_polygon_holes_and_multipart_geometry():
    editor, first, second = scene()
    polygon = Polygon(box(0, 0, 4, 4).exterior.coords, [box(1, 1, 2, 2).exterior.coords])
    editor.selected = [first]
    for geometry, vertices in ((polygon, 10), (MultiPolygon([polygon, box(5, 5, 6, 6)]), 15)):
        first.geo['solid'] = geometry
        editor.update_ui()
        assert float(editor.ui.geo_vertex_entry.get_value()) == vertices
        assert float(editor.ui.area_entry.get_value()) == geometry.area
        assert editor.ui.geo_coords_entry.toPlainText() == geometry.wkt
    assert editor.history.undo_stack == []


@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancelled', 'stale'])
def test_save_as_new_reserves_worker_and_only_commits_current_success(outcome):
    editor, first, second = scene()
    source = SimpleNamespace(obj_options={'name': 'board'})
    editor.gerber_obj = source
    editor.gerber_obj_options = {'name': 'board'}
    editor.edited_obj_name = 'board'
    editor.deactivate_grb_editor = MagicMock()
    editor.update_fcgerber()
    assert editor.history.pending is not None
    assert editor.delete_selected() == 'fail'
    callback = editor.app.connect_custom_signal.call_args.args[0]
    job = editor.app.worker_task.emit.call_args.args[0]
    with patch.object(AppGerberEditor, 'build_edited_gerber') as build:
        job['fcn'](*job['params'])
        build.assert_called_once()
    if outcome == 'cancelled':
        editor.clear()
    elif outcome == 'stale':
        editor.touch_geometry()
    edited = SimpleNamespace(obj_options={'name': 'board_edit'}, units='MM', int_digits=3, frac_digits=5)
    created = SimpleNamespace(obj_options={})
    def new_object(kind, name, initialize):
        initialize(created, editor.app)
        return created
    editor.app.app_obj.new_object.side_effect = new_object
    with patch.object(AppGerberEditor, 'apply_edited_gerber') as apply:
        callback({'error': 'failed'} if outcome == 'failure' else {'obj': edited})
        if outcome == 'success':
            editor.app.app_obj.new_object.assert_called_once()
            apply.assert_called_once_with(created, edited)
            assert created.obj_options['name'] == 'board_edit'
            assert created.units == 'MM'
            assert created.int_digits == 3 and created.frac_digits == 5
            editor.deactivate_grb_editor.assert_called_once()
        else:
            editor.app.app_obj.new_object.assert_not_called()
            editor.deactivate_grb_editor.assert_not_called()
    assert editor.history.pending is None


def test_save_as_new_detached_build_commits_reparseable_copy_without_changing_source(app):
    source = make_gerber(app, NATIVE_GBR, name='board')
    tools_before, solid_before, source_before = source.tools, source.solid_geometry, source.source_file
    editor = gerber_stand_in(app, source, gerber_storage(source))
    editor.deactivate_grb_editor = MagicMock()
    app.connect_custom_signal = MagicMock()
    app.worker_task = MagicMock()
    created = []

    def new_object(kind, name, initialize):
        obj = type(source)(name, app)
        initialize(obj, app)
        created.append(obj)
        return obj

    app.app_obj.new_object.side_effect = new_object
    AppGerberEditor.update_fcgerber(editor)
    job = app.worker_task.emit.call_args.args[0]
    job['fcn'](*job['params'])
    app.connect_custom_signal.call_args.args[0](app.custom_signal.emit.call_args.args[0])
    assert len(created) == 1
    saved = created[0]
    assert saved.obj_options['name'] == 'board_edit'
    assert saved.history_uid != source.history_uid
    assert source.tools is tools_before and source.solid_geometry is solid_before
    assert source.source_file == source_before
    parsed = Gerber(app, steps_per_circle=16)
    assert parsed.parse_lines(saved.source_file.splitlines()) is None
    assert parsed.solid_geometry
    editor.deactivate_grb_editor.assert_called_once()
