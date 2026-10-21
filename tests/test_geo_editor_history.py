"""Committed editor operations, not previews, own history entries."""
from contextlib import nullcontext
from threading import Event, Thread, Timer
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from shapely.geometry import LineString, box

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape, DrawToolUtilityShape, FCMove, FCExplode, FCEraser, FCShapeTool
from appGUI.MainGUI import MainGUI
from appGUI.GUIElements import FCTree
from appEditors.geo_plugins.GeoCirclePlugin import CircleEditorTool
from appEditors.geo_plugins.GeoRectanglePlugin import RectangleEditorTool
from appEditors.geo_plugins.GeoPaintPlugin import PaintOptionsTool
from appMain import App
from appHandlers.appHistory import DEFAULT_STEPS, HistoryManager
from appHandlers.appIO import appIO
from appHandlers.appSignalConnector import AppSignalConnector
from tests.test_geo_editor_save import geometry_object
from tests.test_geo_editor_delete_plot import make_editor


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def editor_with_history(shapes=(), selected=()):
    editor = make_editor(shapes, selected)
    for name in ('add_shape', '_collect_shape', 'delete_shape', 'undo', 'redo', 'reset_history',
                 'history_operation', 'replace_shapes', 'submit_worker', 'on_shape_complete'):
        setattr(editor, name, getattr(AppGeoEditor, name).__get__(editor))
    editor.build_ui_sig = SimpleNamespace(emit=Mock())
    editor.tool_shape = SimpleNamespace(clear=Mock(), redraw=Mock())
    editor.app.inform = SimpleNamespace(emit=Mock())
    editor.app.proc_container = SimpleNamespace(new=lambda *a: nullcontext())
    editor.app.worker_task = SimpleNamespace(emit=Mock())
    editor.reset_history()
    return editor


def run_worker(editor):
    job = editor.app.worker_task.emit.call_args.args[0]
    return job['fcn'](*job['params'])


def interactive_move_editor():
    original = DrawToolShape(LineString([(0, 0), (1, 0)]))
    editor = editor_with_history([original], [original])
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: pos)
    editor.snap = lambda x, y: (x, y)
    editor.x, editor.y = 3, 2
    editor.in_action = True
    editor.select_tool = Mock()
    editor.delete_utility_geometry = lambda: AppGeoEditor.delete_utility_geometry(editor)
    editor.app.grid_status = lambda: False
    editor.app.ui = SimpleNamespace(rel_position_label=Mock(), popMenu=SimpleNamespace(mouse_is_panning=False))
    editor.app.jump_signal = Mock()
    editor.app.mouse_pos, editor.app.on_jump_to = (3, 2), Mock()
    editor.app.geo_editor = editor
    editor.app.options['geometry_editor_milling_type'] = 'cv'
    tool = FCMove.__new__(FCMove)
    tool.draw_app, tool.storage, tool.name = editor, editor.storage, 'move'
    tool.origin, tool.destination = (0, 0), (3, 2)
    tool.has_selection, tool.complete = True, False
    tool.geometry, tool.points = [], [(0, 0)]
    tool.draw_cursor_data = Mock()
    tool.move_tool = SimpleNamespace(length=0, width=0)
    editor.active_tool = tool
    return editor, tool, original


def assert_no_success(editor):
    assert not any('[success]' in str(call) for call in editor.app.inform.emit.call_args_list)


def test_busy_move_canvas_preserves_operation_then_retry_commits():
    editor, tool, original = interactive_move_editor()
    editor.submit_worker(Mock(), [])
    event = SimpleNamespace(pos=(3, 2), button=1)
    assert AppGeoEditor.on_canvas_click(editor, event) == 'fail'
    assert tool.origin == (0, 0) and not tool.complete and tool.geometry == []
    assert tool.points == [(0, 0)]
    assert list(editor.storage.get_objects()) == [original]
    tool.draw_cursor_data.assert_not_called()
    editor.select_tool.assert_not_called()
    assert_no_success(editor)
    run_worker(editor)
    assert AppGeoEditor.on_canvas_click(editor, event) != 'fail'
    assert editor.selected[0].geo.bounds == (3, 2, 4, 2)
    assert tool.origin is None
    editor.select_tool.assert_called_once_with('select')
    assert editor.undo()
    assert list(editor.storage.get_objects()) == [original]


@pytest.mark.parametrize('route', ['canvas', 'right_click', 'numeric_enter', 'make', 'click'])
def test_move_rejection_does_not_clear_origin_or_report_success(route):
    editor, tool, original = interactive_move_editor()
    if route in ('make', 'numeric_enter', 'click'):
        editor.submit_worker(Mock(), [])
    else:
        editor.on_shape_complete = Mock(return_value='fail')
    if route == 'canvas':
        result = AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(3, 2), button=1))
    elif route == 'right_click':
        result = AppGeoEditor.on_canvas_click_release(editor, SimpleNamespace(pos=(3, 2), button=2))
    elif route == 'numeric_enter':
        tool.move_tool.length = 3
        result = tool.on_key('Enter')
    elif route == 'click':
        result = tool.click((9, 9))
    else:
        result = tool.make()
    assert result == 'fail'
    assert tool.origin == (0, 0)
    assert tool.destination == (3, 2)
    assert list(editor.storage.get_objects()) == [original]
    tool.draw_cursor_data.assert_not_called()
    editor.select_tool.assert_not_called()
    assert_no_success(editor)


@pytest.mark.parametrize('busy', [True, False])
def test_busy_or_rejected_right_click_does_not_consume_tool(busy):
    editor, tool, original = interactive_move_editor()
    tool.click, tool.make = Mock(), Mock(side_effect=lambda: setattr(tool, 'complete', True))
    editor.on_shape_complete = Mock(return_value='fail')
    if busy:
        editor.submit_worker(Mock(), [])
    assert AppGeoEditor.on_canvas_click_release(editor, SimpleNamespace(pos=(3, 2), button=2)) == 'fail'
    if busy:
        tool.click.assert_not_called()
        tool.make.assert_not_called()
        editor.on_shape_complete.assert_not_called()
        assert not tool.complete
    assert tool.origin == (0, 0)
    editor.select_tool.assert_not_called()
    assert_no_success(editor)


@pytest.mark.parametrize('busy', [True, False])
@pytest.mark.parametrize('name', ['rotate', 'path'])
@pytest.mark.parametrize('key', ['Enter', int(QtCore.Qt.Key.Key_Return)])
def test_main_gui_enter_preserves_tool_on_busy_or_completion_rejection(monkeypatch, busy, name, key):
    editor = editor_with_history()
    tool = FCShapeTool.__new__(FCShapeTool)
    tool.name, tool.complete = name, False
    tool.path_tool = SimpleNamespace(length=0)
    tool.click = Mock()
    tool.make = Mock(side_effect=lambda: setattr(tool, 'complete', True))
    tool.on_key = Mock()
    editor.active_tool = tool
    editor.x, editor.y = 2, 3
    editor.snap = lambda x, y: (x, y)
    editor.on_shape_complete, editor.select_tool = Mock(return_value='fail'), Mock()
    editor.app.call_source, editor.app.geo_editor, editor.app.collection = 'geo_editor', editor, Mock()
    gui = SimpleNamespace(app=editor.app, geo_select_btn=SimpleNamespace(isChecked=lambda: True))
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.NoModifier))
    if busy:
        editor.submit_worker(Mock(), [])
    event = key if isinstance(key, int) else SimpleNamespace(key=key, native=SimpleNamespace())
    assert MainGUI.keyPressEvent(gui, event) == 'fail'
    if busy:
        tool.click.assert_not_called()
        tool.make.assert_not_called()
        editor.on_shape_complete.assert_not_called()
        assert not tool.complete
    tool.on_key.assert_not_called()
    editor.select_tool.assert_not_called()
    assert_no_success(editor)


@pytest.mark.parametrize('policy', ['busy', 'submission_rejected', 'accepted'])
def test_paint_caller_keeps_tool_on_rejected_submission(policy):
    editor = editor_with_history([DrawToolShape(box(0, 0, 1, 1))])
    editor.selected = list(editor.storage.get_objects())
    editor.select_tool = Mock()
    values = dict(painttooldia_entry=0.2, paintoverlap_entry=10.0, paintmargin_entry=0.0,
                  paintmethod_combo='Lines', paintcontour_cb=False, pathconnect_cb=False)
    ui = SimpleNamespace(**{name: SimpleNamespace(get_value=lambda v=value: v)
                            for name, value in values.items()})
    tool = SimpleNamespace(app=editor.app, fcdraw=editor, ui=ui)
    tool.paint = lambda *args, **kwargs: PaintOptionsTool.paint(tool, *args, **kwargs)
    if policy == 'busy':
        editor.submit_worker(Mock(), [])
        editor.app.worker_task.emit.reset_mock()
    elif policy == 'submission_rejected':
        editor.submit_worker = Mock(return_value='fail')
    result = PaintOptionsTool.on_paint(tool)
    if policy != 'accepted':
        assert result == 'fail'
        editor.select_tool.assert_not_called()
        editor.app.worker_task.emit.assert_not_called()
    else:
        assert result != 'fail'
        editor.select_tool.assert_called_once_with('select')
        editor.app.worker_task.emit.assert_called_once()
    assert_no_success(editor)


def test_add_delete_redo_invalidation_and_metadata():
    editor = editor_with_history()
    shape = DrawToolShape(LineString([(0, 0), (1, 0)]))
    shape.data['custom'] = {'name': 'original'}
    editor.add_shape(shape)
    assert editor.undo()
    assert not list(editor.storage.get_objects())
    assert editor.redo()
    editor.selected = [shape]
    editor.delete_shape(shape)
    assert editor.undo()
    assert editor.selected == [shape]
    assert shape.data['custom'] == {'name': 'original'}
    assert editor.storage.nearest((0, 0))[1] is shape
    editor.add_shape(DrawToolShape(box(3, 3, 4, 4)))
    assert not editor.redo()


def test_editor_and_application_histories_are_independent():
    editor = editor_with_history()
    app = editor.app
    # the app history checkpoints the object (object_state) before undo, so the stand-in needs its state attributes
    obj = SimpleNamespace(history_uid='project-object', name='Renamed', kind='geometry',
                          ser_attrs=['obj_options'], obj_options={'name': 'Renamed'})
    collection = SimpleNamespace(get_list=lambda: [obj],
                                 rename_object=lambda target, name: setattr(target, 'name', name))
    app.call_source, app.headless, app.projects = 'app', False, None
    app.history_changed = SimpleNamespace(emit=Mock())
    app.history = HistoryManager(app, collection)
    app.history.record_rename(obj, 'Original', 'Renamed')
    project_step = app.history.undo_stack[0]
    assert editor._history_undo is not app.history.undo_stack
    assert editor._history_redo is not app.history.redo_stack

    # A direct subtool commit and a worker subtool commit use the same editor stack.
    editor.active_tool = SimpleNamespace(name='circle')
    editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
    editor.active_tool = SimpleNamespace(name='buffer')
    editor.submit_worker(lambda: editor.add_shape(DrawToolShape(box(2, 0, 3, 1))), [])
    run_worker(editor)
    assert AppGeoEditor.history_labels(editor) == ['Circle', 'buffer']
    assert app.history.undo_stack == [project_step]
    assert not app.history.redo_stack

    assert editor.undo()
    editor_undo, editor_redo = list(editor._history_undo), list(editor._history_redo)
    app.call_source = 'geo_editor'
    assert not app.history.undo()
    assert app.history.undo_stack == [project_step]
    app.call_source = 'app'
    assert app.history.undo()
    assert obj.name == 'Original'
    assert editor._history_undo == editor_undo
    assert editor._history_redo == editor_redo
    assert app.history.redo()
    assert obj.name == 'Renamed'
    assert editor._history_undo == editor_undo
    assert editor._history_redo == editor_redo

    editor.reset_history()
    assert app.history.undo_stack == [project_step]
    assert not app.history.redo_stack
    editor.add_shape(DrawToolShape(box(4, 0, 5, 1)))
    editor_step = editor._history_undo[0]
    app.history.clear()
    assert editor._history_undo == [editor_step]
    assert editor.undo()


@pytest.mark.parametrize('value, expected', [(None, 100), ('invalid', 100), (0, 1), ('3', 3)])
def test_editor_depth_uses_main_application_default_and_option(value, expected):
    editor = editor_with_history()
    assert DEFAULT_STEPS == 100
    if value is not None:
        editor.app.options['global_history_steps'] = value
    assert AppGeoEditor.history_limits(editor)[0] == expected
    assert AppGeoEditor.history_limits(editor) == HistoryManager(editor.app, None).limits()


@pytest.mark.parametrize('route', ['redo', 'jump'])
def test_changed_depth_is_enforced_on_redo(route):
    editor = editor_with_history()
    for index in range(4):
        editor.add_shape(DrawToolShape(box(index, 0, index + 1, 1)))
    assert AppGeoEditor.history_go_to(editor, 0)
    editor.app.options['global_history_steps'] = 2
    if route == 'jump':
        assert AppGeoEditor.history_go_to(editor, 4)
    else:
        for _ in range(4):
            assert editor.redo()
            assert len(editor._history_undo) <= 2
    assert len(editor._history_undo) == 2
    assert len(list(editor.storage.get_objects())) == 4


def test_changed_memory_limit_discards_farthest_redo_first():
    editor = editor_with_history()
    for index in range(3):
        editor.add_shape(DrawToolShape(LineString([(i, index) for i in range(23000)])))
    assert AppGeoEditor.history_go_to(editor, 0)
    editor.app.options['global_history_memory_mb'] = 1
    assert editor.redo()
    assert len(editor._history_redo) == 1
    assert editor.redo()
    assert not editor.redo()
    assert len(list(editor.storage.get_objects())) == 2


def test_common_history_uses_application_limits_and_navigation():
    editor = editor_with_history()
    editor.app.options['global_history_steps'] = 3
    assert AppGeoEditor.history_limits(editor) == HistoryManager(editor.app, None).limits()
    for index in range(5):
        with editor.history_operation(label='Shape %d' % index):
            editor.add_shape(DrawToolShape(box(index, 0, index + 1, 1)))
    assert len(editor._history_undo) == 3
    assert AppGeoEditor.history_labels(editor) == ['Shape 2', 'Shape 3', 'Shape 4']
    assert AppGeoEditor.history_go_to(editor, 0)
    assert len(list(editor.storage.get_objects())) == 2
    assert AppGeoEditor.history_go_to(editor, 2)
    assert len(list(editor.storage.get_objects())) == 4
    editor.add_shape(DrawToolShape(box(9, 0, 10, 1)))
    assert not editor._history_redo
    assert len(editor._history_undo) == 3


def test_history_navigation_rejects_busy_and_nested_edits_share_entry():
    editor = editor_with_history()
    with editor.history_operation(label='Grouped'):
        editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
        editor.add_shape(DrawToolShape(box(2, 0, 3, 1)))
    assert AppGeoEditor.history_labels(editor) == ['Grouped']
    editor.submit_worker(Mock(), [])
    assert not AppGeoEditor.history_go_to(editor, 0)
    assert len(list(editor.storage.get_objects())) == 2
    run_worker(editor)
    assert AppGeoEditor.history_go_to(editor, 0)
    assert not list(editor.storage.get_objects())


def test_history_widgets_show_chronological_states_and_next_actions():
    editor = editor_with_history()
    editor.app.call_source = 'geo_editor'
    editor.app.ui = SimpleNamespace(on_history_changed=Mock())
    editor.ui = SimpleNamespace()
    editor.ui.history_positions = QtWidgets.QComboBox()
    editor.ui.history_undo = QtWidgets.QPushButton()
    editor.ui.history_redo = QtWidgets.QPushButton()
    for label in ('Circle', 'Buffer'):
        with editor.history_operation(label=label):
            editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
    editor.undo()
    AppGeoEditor.refresh_history(editor)
    combo = editor.ui.history_positions
    assert [combo.itemText(i) for i in range(combo.count())] == ['Initial state', 'Circle', 'Buffer']
    assert combo.currentIndex() == 1
    assert editor.ui.history_undo.text() == 'Undo Circle'
    assert editor.ui.history_redo.text() == 'Redo Buffer'
    editor.app.ui.on_history_changed.assert_called_with('Circle', 'Buffer')


def test_shared_actions_route_to_editor_without_touching_project_or_text():
    app, ui = MagicMock(), MagicMock()
    app.call_source = 'geo_editor'
    ui.app_focus_in_text.return_value = False
    actions = [QtGui.QAction(None) for _ in range(4)]
    ui.menuedit_undo, ui.menuedit_redo, ui.undo_btn, ui.redo_btn = actions
    AppSignalConnector.connect_editmenu_signals(SimpleNamespace(app=app, ui=ui))
    actions[0].trigger()
    actions[3].trigger()
    app.geo_editor.undo.assert_called_once()
    app.geo_editor.redo.assert_called_once()
    app.history.undo.assert_not_called()
    ui.app_focus_in_text.return_value = True
    actions[0].trigger()
    app.geo_editor.undo.assert_called_once()
    ui.app_focus_in_text.return_value = False
    app.call_source = 'app'
    actions[0].trigger()
    app.history.undo.assert_called_once()


def test_common_history_memory_budget_keeps_latest_oversized_operation():
    editor = editor_with_history()
    editor.app.options['global_history_memory_mb'] = 1
    for index in range(3):
        editor.add_shape(DrawToolShape(LineString([(i, index) for i in range(70000)])))
    assert len(editor._history_undo) == 1
    shapes = list(editor.storage.get_objects())
    assert editor.undo()
    assert len(list(editor.storage.get_objects())) == 2
    assert editor.redo()
    assert list(editor.storage.get_objects()) == shapes
    assert editor.undo()
    assert editor.redo()


@pytest.mark.parametrize('redo', [False, True])
def test_reduced_memory_preserves_immediate_reverse_of_oversized_replay(redo):
    editor = editor_with_history()
    shapes = [DrawToolShape(LineString([(i, index) for i in range(70000)])) for index in range(3)]
    for shape in shapes:
        editor.add_shape(shape)
    if redo:
        assert AppGeoEditor.history_go_to(editor, 0)
    editor.app.options['global_history_memory_mb'] = 1
    action, reverse = (editor.redo, editor.undo) if redo else (editor.undo, editor.redo)
    before = set(editor.storage.get_objects())
    assert action()
    assert len(editor._history_undo) + len(editor._history_redo) == 1
    assert reverse()
    assert set(editor.storage.get_objects()) == before
    assert action()


def test_reduced_depth_jump_targets_retained_baseline_without_partial_failure():
    editor = editor_with_history()
    for index in range(4):
        editor.add_shape(DrawToolShape(box(index, 0, index + 1, 1)))
    shapes = list(editor.storage.get_objects())
    editor.app.options['global_history_steps'] = 2
    assert AppGeoEditor.history_go_to(editor, 0)
    assert set(editor.storage.get_objects()) == set(shapes[:2])
    assert AppGeoEditor.history_go_to(editor, 2)
    assert set(editor.storage.get_objects()) == set(shapes)


def test_reduced_memory_jump_rejects_evicted_target_before_changing_geometry():
    editor = editor_with_history()
    for index in range(3):
        editor.add_shape(DrawToolShape(LineString([(i, index) for i in range(23000)])))
    assert AppGeoEditor.history_go_to(editor, 0)
    editor.app.options['global_history_memory_mb'] = 1
    assert not AppGeoEditor.history_go_to(editor, 3)
    assert not list(editor.storage.get_objects())
    assert AppGeoEditor.history_go_to(editor, 2)
    assert len(list(editor.storage.get_objects())) == 2


@pytest.mark.parametrize('lower_after', [False, True])
def test_history_widgets_label_evicted_baseline_and_reset_new_session(lower_after):
    editor = editor_with_history()
    editor.app.call_source = 'geo_editor'
    editor.app.ui = SimpleNamespace(on_history_changed=Mock())
    editor.ui = SimpleNamespace(history_positions=QtWidgets.QComboBox(),
                                history_undo=QtWidgets.QPushButton(), history_redo=QtWidgets.QPushButton())
    if not lower_after:
        editor.app.options['global_history_steps'] = 3
    for index in range(5):
        with editor.history_operation(label='Shape %d' % index):
            editor.add_shape(DrawToolShape(box(index, 0, index + 1, 1)))
    editor.app.options['global_history_steps'] = 3
    AppGeoEditor.refresh_history(editor)
    combo = editor.ui.history_positions
    assert [combo.itemText(i) for i in range(combo.count())] == [
        'Oldest retained state', 'Shape 2', 'Shape 3', 'Shape 4']
    assert combo.currentIndex() == 3
    assert AppGeoEditor.history_go_to(editor, 0)
    assert len(list(editor.storage.get_objects())) == 2
    AppGeoEditor.refresh_history(editor)
    assert combo.currentIndex() == 0
    assert combo.itemText(0) == 'Oldest retained state'
    editor.reset_history()
    AppGeoEditor.refresh_history(editor)
    assert combo.count() == 1
    assert combo.itemText(0) == 'Initial state'


def test_move_completion_restores_metadata_selection_and_index():
    original = DrawToolShape(LineString([(0, 0), (2, 0)]))
    original.data['custom'] = {'label': 'track'}
    editor = editor_with_history([original], [original])
    tool = FCMove.__new__(FCMove)
    tool.draw_app = editor
    tool.origin, tool.destination = (0, 0), (4, 3)
    tool.draw_cursor_data = Mock()
    editor.app.jump_signal = SimpleNamespace(disconnect=Mock())
    editor.app.options['geometry_editor_milling_type'] = 'cl'
    editor.active_tool = tool
    editor.delete_utility_geometry = lambda: AppGeoEditor.delete_utility_geometry(editor)
    tool.make()
    assert list(editor.storage.get_objects()) == [original]
    assert not editor.undo()
    AppGeoEditor.on_shape_complete(editor)
    moved = tool.geometry[0]
    assert moved.data['custom'] == original.data['custom']
    assert editor.selected == [moved]
    assert editor.storage.nearest((4, 3))[1] is moved
    assert editor.undo()
    assert list(editor.storage.get_objects()) == [original]
    assert editor.selected == [original]
    assert not editor.undo()
    assert editor.redo()
    assert list(editor.storage.get_objects()) == [moved]
    assert editor.selected == [moved]


@pytest.mark.parametrize('operation', ['union', 'intersection', 'intersection_2', 'subtract', 'subtract_2', 'cutpath'])
def test_boolean_variants_undo_and_redo_as_one_operation(operation):
    a, b = DrawToolShape(box(0, 0, 2, 2).exterior), DrawToolShape(box(1, 1, 3, 3).exterior)
    editor = editor_with_history([a, b], [a, b])
    editor.flatten = lambda geo: AppGeoEditor.flatten(editor, geo)
    getattr(AppGeoEditor, operation)(editor)
    run_worker(editor)
    result = list(editor.storage.get_objects())
    result_selection = list(editor.selected)
    assert editor.undo()
    assert set(editor.storage.get_objects()) == {a, b}
    assert editor.selected == [a, b]
    assert not editor.undo()
    assert editor.redo()
    assert list(editor.storage.get_objects()) == result
    assert editor.selected == result_selection


def test_queued_worker_rejects_edits_until_reset_and_load_has_no_entry():
    editor = editor_with_history()
    called = Mock()
    editor.submit_worker(called, [])
    job = editor.app.worker_task.emit.call_args.args[0]
    assert editor.add_shape(DrawToolShape(box(0, 0, 1, 1))) == 'fail'
    assert not list(editor.storage.get_objects())
    editor.reset_history()
    job['fcn'](*job['params'])
    called.assert_not_called()
    editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
    editor.submit_worker(called, [])
    job = editor.app.worker_task.emit.call_args.args[0]
    assert not editor.undo()
    assert len(list(editor.storage.get_objects())) == 1
    editor.reset_history()
    job['fcn'](*job['params'])
    called.assert_not_called()
    editor = editor_with_history()
    editor.submit_worker(editor.add_shape, [DrawToolShape(box(2, 2, 3, 3))], record=False)
    run_worker(editor)
    assert len(list(editor.storage.get_objects())) == 1
    assert not editor.undo()


def test_transform_and_replay_plot_only_changed_shapes():
    shapes = [DrawToolShape(LineString([(x, 0), (x, 1)])) for x in range(100)]
    editor = editor_with_history(shapes, [shapes[0]])
    editor.plot_all = lambda: AppGeoEditor.plot_all(editor)
    editor.plot_changes = lambda: AppGeoEditor.plot_changes(editor)
    editor.plot_all()
    editor.shapes.calls.clear()
    editor.sel_shapes.calls.clear()
    AppGeoEditor.transform_shapes(editor, 'offset', (200, 0))
    assert len(editor._history_undo) == 1
    assert editor.undo()
    assert editor.redo()
    assert not any(call[0] == 'clear' for call in editor.shapes.calls + editor.sel_shapes.calls)
    assert len([call for call in editor.shapes.calls if call[0] == 'add']) <= 3
    assert editor.build_ui_sig.emit.call_count == 3


def test_clear_resets_history_and_rejects_old_worker():
    editor = editor_with_history()
    editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
    called = Mock()
    editor.submit_worker(called, [])
    AppGeoEditor.clear(editor)
    run_worker(editor)
    called.assert_not_called()
    assert not editor.undo()
    assert not editor.redo()


def test_eraser_restores_replacement_selection_on_redo():
    original = DrawToolShape(box(0, 0, 5, 5))
    editor = editor_with_history([original], [original])
    editor.get_pick_index = lambda: AppGeoEditor.get_pick_index(editor)
    editor.delete_utility_geometry = lambda: AppGeoEditor.delete_utility_geometry(editor)
    editor.app.jump_signal = SimpleNamespace(disconnect=Mock())
    tool = FCEraser.__new__(FCEraser)
    tool.draw_app = editor
    tool.destination = (0, 0)
    tool.utility_geometry = lambda **kwargs: SimpleNamespace(geo=[box(-1, -1, 2, 6)])
    tool.make()
    replacement = list(editor.selected)
    assert replacement and replacement != [original]
    assert editor.undo()
    assert editor.selected == [original]
    assert editor.redo()
    assert editor.selected == replacement


def test_explode_is_one_delete_plus_add_operation():
    originals = [DrawToolShape(box(x, 0, x + 1, 1).exterior) for x in (0, 3)]
    originals[0].data['custom'] = 'first ring'
    editor = editor_with_history(originals, originals)
    editor.app.options['geometry_editor_milling_type'] = 'cl'
    editor.delete_utility_geometry = lambda: AppGeoEditor.delete_utility_geometry(editor)
    tool = FCExplode.__new__(FCExplode)
    tool.draw_app = editor
    editor.active_tool = tool
    tool.make()
    segments = list(editor.storage.get_objects())
    assert len(segments) == 8
    assert editor.undo()
    assert set(editor.storage.get_objects()) == set(originals)
    assert editor.selected == originals
    assert originals[0].data['custom'] == 'first ring'
    assert not editor.undo()
    assert editor.redo()
    assert set(editor.storage.get_objects()) == set(segments)
    assert editor.selected == segments


def test_replay_restores_real_tree_rows_and_selection():
    shape = DrawToolShape(box(0, 0, 1, 1).exterior)
    editor = editor_with_history([shape], [shape])
    tree = FCTree(columns=3, extended_sel=True)
    editor.ui = SimpleNamespace(tw=tree, geo_parent=tree.invisibleRootItem(), geo_font=QtGui.QFont())
    editor.shapes_by_tree_id = lambda: AppGeoEditor.shapes_by_tree_id(editor)
    editor.sync_tree_selection = lambda: AppGeoEditor.sync_tree_selection(editor)
    editor.build_ui_sig.emit = lambda: AppGeoEditor.build_ui(editor)
    editor.build_ui_sig.emit()
    assert [item.text(0) for item in tree.selectedItems()] == [str(id(shape))]
    editor.delete_shape(shape)
    editor.build_ui_sig.emit()
    assert tree.topLevelItemCount() == 0
    assert editor.undo()
    assert tree.topLevelItemCount() == 1
    assert [item.text(0) for item in tree.selectedItems()] == [str(id(shape))]
    assert editor.redo()
    assert tree.topLevelItemCount() == 0
    assert not tree.selectedItems()


def test_running_worker_rejects_gui_actions_without_blocking_qt_timers():
    editor = editor_with_history()
    started, release = Event(), Event()
    errors = []
    results = []

    def mutation():
        started.set()
        assert release.wait(4)
        editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))

    def run():
        try:
            run_worker(editor)
        except Exception as err:
            errors.append(err)

    def gui_actions():
        actions = [editor.undo, editor.redo, editor.reset_history,
                   lambda: editor.submit_worker(Mock(), []),
                   lambda: editor.add_shape(DrawToolShape(box(2, 2, 3, 3))),
                   lambda: AppGeoEditor.deactivate(editor),
                   lambda: AppGeoEditor.clear(editor)]
        for action in actions:
            try:
                results.append((action(), not release.is_set()))
            except Exception as err:
                errors.append(err)

    editor.submit_worker(mutation, [])
    worker = Thread(target=run)
    worker.start()
    assert started.wait(5)
    loop = QtCore.QEventLoop()
    watchdog = Timer(2, release.set)
    watchdog.start()
    QtCore.QTimer.singleShot(0, gui_actions)
    QtCore.QTimer.singleShot(120, loop.quit)
    try:
        loop.exec()
    finally:
        release.set()
        watchdog.cancel()
        worker.join(5)
    assert not worker.is_alive()
    assert not errors
    # every GUI action returned at once, while the worker still ran: the GUI thread is not blocked
    assert len(results) == 7
    assert all(value in (False, 'fail') and running for value, running in results)
    assert len(list(editor.storage.get_objects())) == 1
    assert editor.app.inform.emit.call_count >= 7
    assert editor.undo()


@pytest.mark.parametrize('tool_class', [CircleEditorTool, RectangleEditorTool])
@pytest.mark.parametrize('valid', [True, False])
def test_numeric_apply_replaces_geometry_and_selection_in_one_step(tool_class, valid):
    original = DrawToolShape(box(0, 0, 1, 1).exterior)
    original.data['custom'] = {'label': 'original'}
    editor = editor_with_history([original], [original])
    editor.delete_selected = lambda: AppGeoEditor.delete_selected(editor)
    editor.storage.replace = Mock(wraps=editor.storage.replace)
    values = dict(x_entry=5, y_entry=6, radius_x_entry=2 if valid else 0, radius_y_entry=2, angle_entry=0,
                  anchor_radio='c', corner_radio='s', radius_entry=0, length_entry=4 if valid else 0, width_entry=2)
    ui = SimpleNamespace(**{name: SimpleNamespace(get_value=lambda v=value: v)
                            for name, value in values.items()})
    ui.radius_link_btn = SimpleNamespace(isChecked=lambda: True)
    tool = SimpleNamespace(draw_app=editor, app=editor.app, ui=ui, mode='change')
    tool.on_add = lambda: tool_class.on_add(tool)
    tool_class.on_execute(tool)
    replacements = list(editor.storage.get_objects())
    if not valid:
        assert replacements == [original]
        assert editor.selected == [original]
        editor.storage.replace.assert_not_called()
        assert not editor.undo()
        return
    assert replacements and original not in replacements
    editor.storage.replace.assert_called_once()
    assert editor.selected == replacements
    assert editor.undo()
    assert list(editor.storage.get_objects()) == [original]
    assert editor.selected == [original]
    assert original.data['custom'] == {'label': 'original'}
    assert not editor.undo()
    assert editor.redo()
    assert list(editor.storage.get_objects()) == replacements
    assert editor.selected == replacements


def test_running_worker_save_is_rejected_before_snapshot_and_app_success(monkeypatch):
    editor = editor_with_history()
    obj = geometry_object()
    obj.kind = 'geometry'
    obj.bounds = lambda **kwargs: (2, 2, 3, 3)
    obj.build_ui, obj.plot = Mock(), Mock()
    persisted = list(obj.solid_geometry)
    editor.ui = SimpleNamespace(tooldia_entry=SimpleNamespace(get_value=lambda: 0.5))
    editor.multigeo_tool = None
    editor.storage.get_objects = Mock(wraps=editor.storage.get_objects)
    editor.deactivate = Mock(side_effect=lambda: editor.reset_history())
    editor.update_editor_geometry = lambda value, **kwargs: AppGeoEditor.update_editor_geometry(editor, value, **kwargs)
    editor.app.geo_editor, editor.app.call_source = editor, 'geo_editor'
    editor.app.proc_container = SimpleNamespace(new=lambda *args: MagicMock())
    editor.source_save_done = SimpleNamespace(emit=lambda result: AppGeoEditor.on_source_save_done(editor, result))
    ui = Mock()
    ui.notebook.count.return_value = 0
    app = SimpleNamespace(call_source='geo_editor', geo_editor=editor, defaults=Mock(),
                          collection=SimpleNamespace(get_active=lambda: obj), ui=ui,
                          plotcanvas=Mock(), resource_location='', old_state_of_tools_toolbar=False,
                          inform=editor.app.inform, log=Mock(), post_edit_sig=Mock(), _history_edit_saved=Mock())
    dialog = Mock()
    dialog.clickedButton.return_value = dialog.addButton.return_value
    monkeypatch.setattr('appMain.FCMessageBox', Mock(return_value=dialog))
    started, release = Event(), Event()
    errors, results, ticks = [], [], []

    def mutation():
        started.set()
        assert release.wait(4)
        editor.add_shape(DrawToolShape(box(2, 2, 3, 3).exterior))

    def work():
        try:
            run_worker(editor)
        except Exception as err:
            errors.append(err)

    def save():
        try:
            results.append(AppGeoEditor.update_editor_geometry(editor, obj))
            results.append(App.on_editing_finished(app))
            results.append(App.on_editing_finished(app, cleanup=True))
            results.append(App.on_editing_start(app))
            results.append(not release.is_set())
        except Exception as err:
            errors.append(err)

    editor.submit_worker(mutation, [])
    worker = Thread(target=work)
    worker.start()
    assert started.wait(5)
    loop = QtCore.QEventLoop()
    heartbeat = QtCore.QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(not release.is_set()))
    heartbeat.start(10)
    watchdog = Timer(2, release.set)
    watchdog.start()
    QtCore.QTimer.singleShot(0, save)
    QtCore.QTimer.singleShot(120, loop.quit)
    try:
        loop.exec()
    finally:
        heartbeat.stop()
        release.set()
        watchdog.cancel()
        worker.join(5)
    assert not errors and not worker.is_alive()
    assert results == ['fail', 'fail', 'fail', 'fail', True]
    assert any(ticks)
    assert obj.solid_geometry == persisted
    obj.build_ui.assert_not_called()
    obj.plot.assert_not_called()
    app.post_edit_sig.emit.assert_not_called()
    editor.deactivate.assert_not_called()
    editor.storage.get_objects.assert_not_called()
    assert not any('[success]' in str(call) for call in app.inform.emit.call_args_list)
    assert App.on_editing_finished(app) == 'pending'
    assert obj.solid_geometry == [shape.geo for shape in editor.storage.get_objects()]
    assert obj.solid_geometry != persisted
    editor.deactivate.assert_not_called()
    app.post_edit_sig.emit.assert_not_called()
    run_worker(editor)  # this test's fake emitter delivers completion on the calling GUI thread
    editor.deactivate.assert_called_once()
    app.post_edit_sig.emit.assert_called_once()
    saved = list(obj.solid_geometry)
    run_worker(editor)  # replaying a finished/obsolete closure must not commit after accepted save
    assert obj.solid_geometry == saved
    assert [shape.geo for shape in editor.storage.get_objects()] == saved
    assert not editor.undo()


def test_new_project_does_not_replace_editor_after_busy_exit_rejection():
    editor = editor_with_history()
    editor.submit_worker(Mock(), [])
    app = SimpleNamespace(call_source='geo_editor', geo_editor=editor, defaults=Mock())
    app.on_editing_finished = lambda **kwargs: App.on_editing_finished(app, **kwargs)
    app.collection = Mock()
    handler = SimpleNamespace(app=app, log=Mock())
    assert appIO.on_file_new_project(handler) == 'fail'
    assert app.geo_editor is editor
    app.collection.get_list.assert_not_called()


def test_project_restore_honors_rejected_editor_exit():
    app = SimpleNamespace(options=Mock())
    handler = SimpleNamespace(app=app, on_file_new_project=Mock(return_value='fail'))
    assert appIO._restore_project_handler(handler, {'objs': [], 'options': {}},
                                          'unused.FlatPrj', False, False, False, False) is False
    app.options.load_project.assert_not_called()


def test_app_stops_on_rejected_save_even_after_dialog(monkeypatch):
    obj = geometry_object()
    obj.kind = 'geometry'
    editor = editor_with_history()
    editor.update_editor_geometry = Mock(return_value='fail')
    ui = Mock()
    dialog = Mock()
    dialog.clickedButton.return_value = dialog.addButton.return_value
    monkeypatch.setattr('appMain.FCMessageBox', Mock(return_value=dialog))
    app = SimpleNamespace(call_source='geo_editor', geo_editor=editor, defaults=Mock(),
                          collection=SimpleNamespace(get_active=lambda: obj), ui=ui,
                          plotcanvas=Mock(), resource_location='', post_edit_sig=Mock())
    assert App.on_editing_finished(app) == 'fail'
    editor.update_editor_geometry.assert_called_once()
    assert editor.update_editor_geometry.call_args.args == (obj,)
    assert callable(editor.update_editor_geometry.call_args.kwargs['on_complete'])
    ui.toolbarplugins.show.assert_not_called()
    ui.plugin_scroll_area.takeWidget.assert_not_called()
    app.post_edit_sig.emit.assert_not_called()


def test_accepted_deactivation_invalidates_queued_job_without_later_mutation():
    original = DrawToolShape(box(0, 0, 1, 1))
    editor = editor_with_history([original], [original])
    editor.app.ui, editor.app.plotcanvas = Mock(), Mock()
    editor.app.history = Mock()
    editor.ui, editor.fcgeometry, editor.item_selected, editor.clear_tree_sig = Mock(), Mock(), Mock(), Mock()
    editor.toolbar_old_state = False
    editor.disconnect_canvas_event_handlers = Mock()
    editor.make_storage = AppGeoEditor.make_storage
    editor.clear = lambda: AppGeoEditor.clear(editor)
    editor.on_tree_geo_click, editor.on_tree_selection = Mock(), Mock()
    called = Mock(side_effect=lambda: editor.add_shape(DrawToolShape(box(2, 2, 3, 3))))
    editor.submit_worker(called, [])
    job = editor.app.worker_task.emit.call_args.args[0]
    assert AppGeoEditor.deactivate(editor) != 'fail'
    assert not list(editor.storage.get_objects())
    job['fcn'](*job['params'])
    called.assert_not_called()
    assert not list(editor.storage.get_objects())
    assert not editor.undo()


def test_obsolete_queued_job_does_not_release_a_new_jobs_reservation():
    editor = editor_with_history()
    old, new = Mock(), Mock()
    editor.submit_worker(old, [])
    obsolete = editor.app.worker_task.emit.call_args.args[0]
    editor.reset_history()
    editor.submit_worker(new, [])
    obsolete['fcn'](*obsolete['params'])
    assert AppGeoEditor.reject_busy(editor)
    old.assert_not_called()
    run_worker(editor)
    new.assert_called_once()
    assert not AppGeoEditor.reject_busy(editor)


def test_failed_operation_rolls_back_without_clearing_redo():
    editor = editor_with_history()
    editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
    editor.undo()
    with pytest.raises(ValueError, match='cancel operation'):
        with editor.history_operation():
            editor.add_shape(DrawToolShape(box(2, 2, 3, 3)))
            raise ValueError('cancel operation')
    assert not list(editor.storage.get_objects())
    assert not editor.undo()
    assert editor.redo()


def test_queued_worker_does_not_retarget_a_changed_selection():
    shapes = [DrawToolShape(box(x, 0, x + 1, 1)) for x in (0, 3)]
    editor = editor_with_history(shapes, [shapes[0]])
    called = Mock()
    editor.submit_worker(called, [])
    editor.selected[:] = [shapes[1]]
    run_worker(editor)
    called.assert_not_called()


def test_worker_failure_releases_selection_guard_and_rolls_back():
    editor = editor_with_history()
    editor.interdict_selection = False

    def fail():
        assert editor.interdict_selection
        editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
        raise ValueError('failed worker')

    editor.submit_worker(fail, [])
    with pytest.raises(ValueError, match='failed worker'):
        run_worker(editor)
    assert not editor.interdict_selection
    assert not list(editor.storage.get_objects())
    assert not editor.undo()


@pytest.mark.parametrize('key, shift', [(int(QtCore.Qt.Key.Key_Z), False), ('Z', False),
                                        (int(QtCore.Qt.Key.Key_Y), False), ('Y', False),
                                        (int(QtCore.Qt.Key.Key_Z), True), ('Z', True)])
def test_actual_main_gui_history_dispatch(monkeypatch, key, shift):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    modifiers = QtCore.Qt.KeyboardModifier.ControlModifier
    if shift:
        modifiers |= QtCore.Qt.KeyboardModifier.ShiftModifier
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers', staticmethod(lambda: modifiers))
    monkeypatch.setattr(QtWidgets.QApplication, 'focusWidget', staticmethod(lambda: None))
    editor = SimpleNamespace(undo=Mock(), redo=Mock())
    gui = SimpleNamespace(app=SimpleNamespace(call_source='geo_editor', geo_editor=editor,
                                             collection=Mock()))
    event = key if isinstance(key, int) else SimpleNamespace(key=key, native=SimpleNamespace())
    MainGUI.keyPressEvent(gui, event)
    expected = editor.redo if shift or key in (QtCore.Qt.Key.Key_Y, 'Y') else editor.undo
    expected.assert_called_once()
    assert app is not None


@pytest.mark.parametrize('widget_type', [QtWidgets.QLineEdit, QtWidgets.QSpinBox,
                                       QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit])
def test_history_shortcuts_leave_text_widgets_in_control(monkeypatch, widget_type):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = widget_type()
    focus = widget.lineEdit() if isinstance(widget, QtWidgets.QAbstractSpinBox) else widget
    monkeypatch.setattr(QtWidgets.QApplication, 'focusWidget', staticmethod(lambda: focus))
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.ControlModifier))
    editor = SimpleNamespace(undo=Mock(), redo=Mock())
    gui = SimpleNamespace(app=SimpleNamespace(call_source='geo_editor', geo_editor=editor,
                                             collection=Mock()))
    MainGUI.keyPressEvent(gui, SimpleNamespace(key='Z', native=SimpleNamespace()))
    MainGUI.keyPressEvent(gui, QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Z,
                                            QtCore.Qt.KeyboardModifier.ControlModifier))
    editor.undo.assert_not_called()
    editor.redo.assert_not_called()
    assert app is not None


def test_boolean_worker_is_one_step_and_stale_worker_is_rejected():
    a, b = DrawToolShape(box(0, 0, 2, 2)), DrawToolShape(box(1, 1, 3, 3))
    editor = editor_with_history([a, b], [a, b])
    AppGeoEditor.union(editor)
    job = editor.app.worker_task.emit.call_args.args[0]
    job['fcn'](*job['params'])
    assert len(list(editor.storage.get_objects())) == 1
    assert editor.undo()
    assert set(editor.storage.get_objects()) == {a, b}
    assert editor.selected == [a, b]
    assert not editor.undo()
    AppGeoEditor.union(editor)
    job = editor.app.worker_task.emit.call_args.args[0]
    editor.reset_history()
    job['fcn'](*job['params'])
    assert set(editor.storage.get_objects()) == {a, b}
    assert not editor.undo()


def test_preview_and_load_are_not_history_and_reset_clears_redo():
    editor = editor_with_history()
    editor.add_shape(DrawToolUtilityShape(box(0, 0, 1, 1)))
    AppGeoEditor.delete_utility_geometry(editor)
    assert not editor.undo()
    with editor.history_operation(record=False):
        editor.add_shape(DrawToolShape(box(0, 0, 1, 1)))
    assert not editor.undo()
    editor.add_shape(DrawToolShape(box(2, 2, 3, 3)))
    assert editor.undo()
    editor.reset_history()
    assert not editor.redo()
