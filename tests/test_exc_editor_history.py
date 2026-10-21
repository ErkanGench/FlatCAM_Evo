"""Excellon-local transactions retain changed wrappers, not deep board snapshots."""

from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace
from unittest.mock import Mock
from unittest.mock import MagicMock, patch

import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.affinity import rotate, translate

from appEditors.appExcEditor import (AppExcEditor, AppExcEditorUI, MoveEditorExc, ResizeEditorExc,
                                     DrillArray, SlotArray)
from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape
from appEditors.exc_plugins.ExcHistory import ExcellonHistory
from appGUI.MainGUI import MainGUI
from PyQt6 import QtCore, QtWidgets


def drill(x=0):
    return DrawToolShape(MultiLineString([[(x - 0.5, 0), (x + 0.5, 0)], [(x, -0.5), (x, 0.5)]]))


def scene():
    first, second = drill(), DrawToolShape(LineString([(4, 0), (6, 1)]).buffer(0.5))
    storage = AppGeoEditor.make_storage()
    storage.insert_many([first, second])
    editor = SimpleNamespace(
        storage_dict={1.0: storage}, selected=[first], utility=[], current_storage=storage,
        points_edit={1.0: [(0, 0)]}, slot_points_edit={1.0: [((4, 0), (6, 1))]},
        olddia_newdia={1.0: 1.0}, tool2tooldia={1: 1.0}, last_tool_selected=1,
        is_modified=False, decimals=4, active_tool=None, in_action=False, tool_shape=Mock(),
        build_ui=Mock(), replot=Mock(), select_tool=Mock(),
        app=SimpleNamespace(options={}, inform=Mock(), log=Mock(), jump_signal=Mock()),
        history_changed=Mock())
    for name in ('_collect_exc_shape', 'add_exc_shape', 'delete_shape', 'delete_selected',
                 'get_selected', 'undo', 'redo', 'resize_features', 'refresh_feature_table',
                 'feature_filter_values', 'filter_features', 'sync_tool_rows'):
        setattr(editor, name, MethodType(getattr(AppExcEditor, name), editor))
    editor.make_storage = AppGeoEditor.make_storage
    editor.history = ExcellonHistory(editor)
    return editor, first, second


def test_delete_group_restores_wrapper_selection_counts_and_dirty_state():
    editor, first, second = scene()
    editor.selected = [first, second]
    editor.delete_selected()
    assert list(editor.storage_dict[1.0].get_objects()) == []
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    assert editor.selected == [first, second]
    assert editor.points_edit == {1.0: [(0, 0)]}
    assert not editor.is_modified
    assert editor.redo()
    assert list(editor.storage_dict[1.0].get_objects()) == []
    assert editor.is_modified


def test_nested_add_and_geometry_change_are_one_delta_and_branch():
    editor, first, second = scene()
    old = first.geo
    added = drill(9)
    with editor.history.operation('Move and add') as accepted:
        assert accepted
        first.geo = translate(first.geo, xoff=2)
        editor.add_exc_shape(added, editor.storage_dict[1.0])
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert first.geo is old
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    editor.add_exc_shape(drill(12), editor.storage_dict[1.0])
    assert not editor.redo()
    assert editor.history.redo_stack == []


def test_exception_rolls_back_tools_counters_geometry_and_order():
    editor, first, second = scene()
    old = first.geo
    with pytest.raises(ValueError):
        with editor.history.operation('Broken'):
            first.geo = translate(first.geo, xoff=8)
            editor.storage_dict.pop(1.0)
            editor.storage_dict[2.0] = AppGeoEditor.make_storage()
            editor.points_edit.clear()
            editor.olddia_newdia.clear()
            editor.selected.clear()
            raise ValueError('failed calculation')
    assert list(editor.storage_dict) == [1.0]
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    assert first.geo is old
    assert editor.points_edit == {1.0: [(0, 0)]}
    assert editor.selected == [first]
    assert not editor.history.undo_stack


def test_noop_does_not_dirty_or_clear_redo_and_step_limits_apply():
    editor, first, second = scene()
    editor.app.options['global_history_steps'] = 2
    for x in range(3):
        editor.add_exc_shape(drill(x + 10), editor.storage_dict[1.0])
    assert len(editor.history.undo_stack) == 2
    assert editor.history.baseline_evicted
    assert editor.undo()
    with editor.history.operation('Selection only'):
        editor.selected = [second]
    assert len(editor.history.redo_stack) == 1


def test_move_handler_is_one_undoable_operation():
    editor, first, second = scene()
    editor.delete_utility_geometry = Mock()
    tool = MoveEditorExc.__new__(MoveEditorExc)
    tool.draw_app = editor
    tool.origin, tool.destination = (0, 0), (2, 3)
    tool.selected_dia_list = [1.0]
    tool.make()
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    assert editor.selected == [first]


def test_background_mutation_is_rejected_and_reset_discards_session_history():
    editor, first, second = scene()
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(editor.delete_selected).result() == 'fail'
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    editor.delete_selected()
    editor.history.reset()
    assert not editor.undo()


def test_unchanged_board_records_are_not_retained_in_delta():
    editor, first, second = scene()
    editor.delete_selected()
    step = editor.history.undo_stack[0]
    assert second not in editor.history.retained_shapes()
    assert first in editor.history.retained_shapes()
    assert 'snapshot' not in step


@pytest.mark.parametrize('key,shift,redo', [('Z', False, False), ('Z', True, True), ('Y', False, True)])
def test_editor_shortcuts_are_local_and_preserve_text_undo(key, shift, redo):
    gui = MagicMock()
    gui.app.call_source = 'exc_editor'
    event = Mock()
    event.key = key
    event.native.isAutoRepeat.return_value = False
    event.isAutoRepeat.return_value = False
    modifiers = QtCore.Qt.KeyboardModifier.ControlModifier
    if shift:
        modifiers |= QtCore.Qt.KeyboardModifier.ShiftModifier
    with patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=modifiers), \
            patch.object(MainGUI, 'app_focus_in_text', return_value=False):
        MainGUI.keyPressEvent(gui, event)
    (gui.app.exc_editor.redo if redo else gui.app.exc_editor.undo).assert_called_once()
    gui.app.history.undo.assert_not_called()
    gui.app.history.redo.assert_not_called()
    gui.app.exc_editor.reset_mock()
    with patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=modifiers), \
            patch.object(MainGUI, 'app_focus_in_text', return_value=True):
        MainGUI.keyPressEvent(gui, event)
    gui.app.exc_editor.undo.assert_not_called()
    gui.app.exc_editor.redo.assert_not_called()


def test_diagnostics_are_read_only_and_do_not_report_open_drill_crosses():
    editor, first, second = scene()
    editor.storage_dict[1.0].insert(drill(0.00001))
    report = AppExcEditor.diagnose_features(editor, selected_only=False, tolerance=0.001)
    assert report['drills'] == 2
    assert report['slots'] == 1
    assert len(report['duplicate']) == 1
    assert not report['invalid']
    assert not report['degenerate']
    assert not editor.history.undo_stack
    assert not editor.is_modified
    assert editor.selected == [first]
    selected = AppExcEditor.diagnose_features(editor, selected_only=True, tolerance=0.001)
    assert selected['drills'] == 1
    assert selected['slots'] == 0


@pytest.mark.parametrize('tolerance', [-1, float('nan'), float('inf'), 'bad'])
def test_diagnostics_reject_bad_tolerance_without_changing_editor(tolerance):
    editor, first, second = scene()
    assert AppExcEditor.diagnose_features(editor, tolerance=tolerance) == 'fail'
    assert not editor.is_modified
    assert editor.selected == [first]


def test_slot_inspection_reports_centerline_length_orientation_and_endpoints():
    editor, first, second = scene()
    second.exc_slot = ((4.0, 0.0), (6.0, 1.0))
    second.exc_slot_geometry = second.geo
    editor.selected = [second]
    report = AppExcEditor.diagnose_features(editor, selected_only=True, tolerance=0.001)
    record = report['features'][0]
    assert record['type'] == 'slot'
    assert record['endpoints'] == ((4.0, 0.0), (6.0, 1.0))
    assert record['length'] == pytest.approx(5 ** 0.5)
    assert record['orientation'] == pytest.approx(26.565051177)
    assert not record['inferred']


def test_diagnostics_identify_empty_invalid_and_zero_length_slot():
    editor, first, second = scene()
    storage = editor.storage_dict[1.0]
    empty = DrawToolShape(Polygon())
    invalid = DrawToolShape(Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    zero = DrawToolShape(Point(20, 20).buffer(0.5))
    zero.exc_slot = ((20, 20), (20, 20))
    zero.exc_slot_geometry = zero.geo
    # Empty values can't enter the R-tree. Inspection must still cope with legacy/corrupt entries.
    editor.storage_dict[1.0] = SimpleNamespace(get_objects=lambda: [first, second, empty, invalid, zero])
    report = AppExcEditor.diagnose_features(editor, tolerance=0.001)
    assert [record['shape'] for record in report['empty']] == [empty]
    assert [record['shape'] for record in report['invalid']] == [invalid]
    assert [record['shape'] for record in report['degenerate']] == [zero]


@pytest.mark.parametrize('diameter', [-1, float('nan'), float('inf')])
def test_invalid_tool_add_is_atomic(diameter):
    editor, first, second = scene()
    editor.ui = SimpleNamespace(addtool_entry=Mock(), tools_table_exc=MagicMock())
    editor.units = 'MM'
    editor.ui.addtool_entry.get_value.return_value = diameter
    AppExcEditor.on_tool_add(editor)
    assert list(editor.storage_dict) == [1.0]
    assert not editor.is_modified
    assert not editor.history.undo_stack


def test_same_diameter_tool_edit_is_a_noop_before_signal_disconnect():
    editor, first, second = scene()
    editor.ui = SimpleNamespace(tools_table_exc=MagicMock())
    editor.ui.tools_table_exc.currentItem().text.return_value = '1.0'
    editor.ui.tools_table_exc.currentRow.return_value = 0
    # A same-diameter change must not enter the loop that appends to its own source storage.
    with patch.object(editor.storage_dict[1.0], 'get_objects', side_effect=AssertionError('must not resize')):
        # Suspend capture to check the handler validation independently of history enumeration.
        editor.history.suspended = True
        AppExcEditor.on_tool_edit(editor, Mock())
    editor.ui.tools_table_exc.itemChanged.disconnect.assert_not_called()
    assert not editor.is_modified


def test_invalid_selected_resize_is_atomic_before_signal_disconnect():
    editor, first, second = scene()
    editor.ui = SimpleNamespace(tools_table_exc=MagicMock())
    tool = ResizeEditorExc.__new__(ResizeEditorExc)
    tool.draw_app = editor
    tool.ui = SimpleNamespace(res_dia_entry=Mock())
    tool.ui.res_dia_entry.get_value.return_value = float('nan')
    assert tool.make() == 'fail'
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    editor.ui.tools_table_exc.itemChanged.disconnect.assert_not_called()
    assert not editor.is_modified


def test_selected_resize_preserves_native_slot_endpoints_and_unselected_drill():
    editor, first, second = scene()
    second.exc_slot = ((4.0, 0.0), (6.0, 1.0))
    second.exc_slot_geometry = second.geo
    editor.selected = [second]
    editor.resize_features = MethodType(AppExcEditor.resize_features, editor)
    tool = ResizeEditorExc.__new__(ResizeEditorExc)
    tool.draw_app = editor
    tool.ui = SimpleNamespace(res_dia_entry=Mock())
    tool.ui.res_dia_entry.get_value.return_value = 2.0
    tool.make()
    assert list(editor.storage_dict[1.0].get_objects()) == [first]
    resized = list(editor.storage_dict[2.0].get_objects())[0]
    assert resized.exc_slot == second.exc_slot
    assert resized.geo.equals(LineString(second.exc_slot).buffer(1.0))
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert list(editor.storage_dict) == [1.0]
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    assert editor.selected == [second]
    assert editor.redo()
    assert list(editor.storage_dict[2.0].get_objects()) == [resized]


def test_resize_rejects_arbitrary_polygon_without_partially_moving_drills():
    editor, first, second = scene()
    second.geo = box(4, 0, 7, 3)
    editor.selected = [first, second]
    assert AppExcEditor.resize_features(editor, editor.selected, 2.0) == 'fail'
    assert list(editor.storage_dict) == [1.0]
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    assert not editor.history.undo_stack
    assert not editor.is_modified


def test_tool_edit_resizes_all_features_atomically_and_is_one_history_step():
    editor, first, second = scene()
    editor.ui = SimpleNamespace(tools_table_exc=MagicMock())
    editor.ui.tools_table_exc.currentItem().text.return_value = '2.0'
    editor.ui.tools_table_exc.currentRow.return_value = 0
    second.exc_slot = ((4.0, 0.0), (6.0, 1.0))
    second.exc_slot_geometry = second.geo
    AppExcEditor.on_tool_edit(editor, Mock())
    assert list(editor.storage_dict) == [2.0]
    assert len(list(editor.storage_dict[2.0].get_objects())) == 2
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    assert editor.tool2tooldia == {1: 1.0}


def test_tool_add_delete_and_slot_conversion_restore_counts_and_selection():
    editor, first, second = scene()
    editor.ui = SimpleNamespace(addtool_entry=Mock(), tools_table_exc=MagicMock())
    editor.units, editor.decimals, editor.dec_format = 'MM', 4, lambda value: round(value, 4)
    editor.selected = [second]
    AppExcEditor.on_tool_delete(editor, dia=1.0)
    assert editor.selected == []
    assert not editor.slot_points_edit
    assert editor.undo()
    assert editor.selected == [second]
    AppExcEditor.on_tool_add(editor, tooldia=2.0)
    assert list(editor.storage_dict) == [1.0, 2.0]
    assert editor.undo()
    item = Mock()
    item.row.return_value = 0
    editor.ui.tools_table_exc.selectedItems.return_value = [item]
    editor.ui.tools_table_exc.item().text.return_value = '1.0'
    AppExcEditor.on_slots_conversion(editor)
    assert all(isinstance(shape.geo, MultiLineString) for shape in editor.storage_dict[1.0].get_objects())
    assert all(shape in set(editor.storage_dict[1.0].get_objects()) for shape in editor.selected)
    assert len(editor.points_edit[1.0]) == 2
    assert editor.slot_points_edit[1.0] == []
    assert editor.undo()
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]


def test_real_properties_controls_drive_history_and_read_only_inspection():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor, first, second = scene()
    editor.decimals = 4
    editor.ui = AppExcEditorUI(SimpleNamespace(decimals=4, app_units='MM', resource_location='assets/resources'))
    editor.undo_action = editor.ui.undo_button
    editor.redo_action = editor.ui.redo_button
    editor.ui.undo_button.clicked.connect(lambda: editor.undo())
    editor.ui.redo_button.clicked.connect(lambda: editor.redo())
    editor.diagnose_features = MethodType(AppExcEditor.diagnose_features, editor)
    editor.on_diagnostics = MethodType(AppExcEditor.on_diagnostics, editor)
    editor.ui.diagnostics_button.clicked.connect(lambda: editor.on_diagnostics())
    editor.delete_selected()
    AppExcEditor.update_history_ui(editor)
    assert editor.ui.undo_button.isEnabled()
    assert editor.ui.history_list.count() == 2  # Initial state plus the deletion.
    editor.ui.undo_button.click()
    assert list(editor.storage_dict[1.0].get_objects()) == [first, second]
    editor.ui.diagnostics_selected.setChecked(True)
    editor.ui.diagnostics_button.click()
    assert editor.ui.diagnostics_result.isReadOnly()
    assert 'Drills: 1' in editor.ui.diagnostics_result.toPlainText()
    assert not editor.history.undo_stack
    assert not editor.is_modified
    editor.ui.exc_edit_widget.deleteLater()
    application.processEvents()


def test_native_slot_and_rotated_drill_save_extraction_preserve_coordinates():
    editor, first, second = scene()
    first.geo = rotate(first.geo, 37, origin=(0, 0))
    second.exc_slot = ((4.0, 0.0), (6.0, 1.0))
    second.exc_slot_geometry = second.geo
    editor._save_excellon_in_place = Mock()
    source = SimpleNamespace(geo_steps_per_circle=64, obj_options={'name': 'original'}, tools={'sentinel': 1})
    AppExcEditor.update_fcexcellon(editor, source, in_place=True)
    tools = editor.new_tools
    assert len(tools) == 1
    assert tools[1]['drills'][0].distance(first.geo.centroid) < 1e-12
    assert tuple(tools[1]['slots'][0][0].coords[0]) == second.exc_slot[0]
    assert tuple(tools[1]['slots'][0][1].coords[0]) == second.exc_slot[1]
    assert source.tools == {'sentinel': 1}


def test_selection_row_sync_blocks_signals_and_does_not_select_other_features():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor, first, second = scene()
    editor.ui = SimpleNamespace(tools_table_exc=QtWidgets.QTableWidget(3, 4))
    editor.ui.tools_table_exc.setItem(0, 1, QtWidgets.QTableWidgetItem('1.0'))
    changed = Mock()
    editor.ui.tools_table_exc.selectionModel().selectionChanged.connect(changed)
    AppExcEditor.sync_tool_rows(editor)
    assert [index.row() for index in editor.ui.tools_table_exc.selectionModel().selectedRows()] == [0]
    assert editor.selected == [first]
    changed.assert_not_called()
    editor.ui.tools_table_exc.deleteLater()
    application.processEvents()


def test_rejected_resize_does_not_rebuild_unchanged_indexes():
    editor, first, second = scene()
    with patch.object(editor.storage_dict[1.0], 'replace', wraps=editor.storage_dict[1.0].replace) as replace:
        assert editor.resize_features(editor.selected, -1) == 'fail'
    replace.assert_not_called()
    editor.build_ui.assert_not_called()


@pytest.mark.parametrize('cls,prefix,counter', [(DrillArray, 'drill', 'points_edit'),
                                               (SlotArray, 'slot', 'slot_points_edit')])
def test_invalid_circular_array_does_not_change_feature_counts(cls, prefix, counter):
    editor, first, second = scene()
    tool = cls.__new__(cls)
    tool.draw_app = editor
    tool.selected_dia = 1.0
    tool.points = (0, 0)
    setattr(tool, prefix + '_array', 'circular')
    setattr(tool, prefix + '_array_size', 10)
    setattr(tool, prefix + '_angle', 40)
    tool.origin, tool.destination = (0, 0), (1, 0)
    before = {key: list(values) for key, values in getattr(editor, counter).items()}
    assert tool.make() == 'fail'
    assert getattr(editor, counter) == before
    assert not editor.history.undo_stack
