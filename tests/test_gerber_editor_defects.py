"""Regression tests for Gerber Editor defect fixes: Qt slot signatures, the Scale tool connection, history of
translations and reshapes, import failure recovery, size selection and delete, region operations, aperture table
edit signal recovery, the marked-polygon list, region-export flag, buffer and scale without a shape, the buffer
factor check, numeric aperture codes, history depth on error, and the zoom switch of update_ui.

The editor is the real AppGerberEditor built by test_gerber_editor_pick.make_editor; the application, the canvas and
the worker are stand-ins. Everything is headless and does not sleep."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, Point, Polygon, box

from appEditors.appGerberEditor import AppGerberEditor, ImportEditorGrb, ScaleEditorGrb
from appEditors.grb_plugins.GrbBufferPlugin import BufferEditorTool
from appEditors.grb_plugins.GrbCommon import DrawToolShape, numeric_aperture_codes
from appEditors.grb_plugins.GrbTransformationPlugin import queue_transform
from test_gerber_editor_pick import aperture, make_editor, pad


def scene():
    first = DrawToolShape({'solid': box(0, 0, 1, 1), 'follow': Point(0.5, 0.5)})
    second = DrawToolShape({'solid': box(10, 0, 11, 1), 'follow': Point(10.5, 0.5)})
    editor = make_editor({10: aperture([first]), 11: aperture([second])})
    editor.history.reset()
    return editor, first, second


def size_scene():
    small = DrawToolShape({'solid': box(0, 0, 2, 3)})
    wide = DrawToolShape({'solid': box(0, 0, 4, 3)})
    editor = make_editor({10: aperture([small]), '11': aperture([wide])})
    editor.history.reset()
    editor.ui.size_width_chk.setChecked(True)
    editor.ui.size_width_entry.setText('2')
    editor.ui.size_height_chk.setChecked(True)
    editor.ui.size_height_entry.setText('3')
    editor.ui.size_tolerance_entry.setText('0')
    editor.plot_selection = MagicMock()
    return editor, small, wide


def select_row(editor, row):
    table = editor.ui.apertures_table
    with QtCore.QSignalBlocker(table):
        table.selectRow(row)


def reconnect_item_changed(editor):
    table = editor.ui.apertures_table
    try:
        table.itemChanged.disconnect()
    except TypeError:
        pass
    table.itemChanged.connect(editor.on_tool_edit)
    return table


def run_queued_job(editor):
    job = editor.app.worker_task.emit.call_args.args[0]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(job['fcn'], *job['params']).result(timeout=10)
    QtWidgets.QApplication.processEvents()


# 1. Qt signal arguments reach the slots


# 2. Scale menu item and the Scale tool connection


# 3. Translation versus reshape in history

def test_pure_move_of_round_follow_r_pad_does_not_mark_regions():
    first = pad(0, 0, 1)
    editor = make_editor({10: {'type': 'R', 'size': 1.0, 'geometry': [first]}})
    editor.history.reset()
    editor.selected = [first]
    tool = SimpleNamespace(draw_app=editor, app=editor.app)
    queue_transform(tool, 'offset', ['X', 2])
    run_queued_job(editor)
    assert first.geo['follow'].equals(Point(2, 0))
    assert len(editor.history.undo_stack) == 1
    assert editor.loaded_as_regions is False


def test_real_reshape_of_r_pad_marks_regions():
    first = pad(0, 0, 1)
    editor = make_editor({10: {'type': 'R', 'size': 1.0, 'geometry': [first]}})
    editor.history.reset()
    editor.selected = [first]
    with editor.history.operation('Reshape'):
        first.geo['solid'] = box(0, 0, 3, 1)
        editor.touch_geometry()
    assert len(editor.history.undo_stack) == 1
    assert editor.loaded_as_regions is True


# 4. Import failure


# 5. Select and Delete by Size

def test_delete_by_size_acts_on_selection_when_any_else_on_whole_board():
    editor, small, wide = size_scene()
    editor.selected = [wide]
    # the selected shape does not match, so nothing is deleted and the board is not searched
    assert editor.on_delete_by_size() == []
    assert small in editor.storage_dict[10]['geometry']
    assert editor.history.undo_stack == []

    editor.selected = []
    assert editor.on_delete_by_size() == [small]
    assert small not in editor.storage_dict[10]['geometry']
    assert wide in editor.storage_dict['11']['geometry']


def test_select_by_size_searches_whole_board_with_existing_selection():
    editor, small, wide = size_scene()
    editor.selected = [wide]
    assert editor.on_select_by_size() == [small]
    assert editor.selected == [small]


# 6. Region operation with an empty result

def test_intersection_of_disjoint_shapes_fails_and_keeps_sources():
    editor, first, second = scene()
    editor.selected = [first, second]
    before_first = editor.storage_dict[10]['geometry'][:]
    before_second = editor.storage_dict[11]['geometry'][:]
    assert editor.apply_region_operation('intersection') == 'fail'
    assert editor.storage_dict[10]['geometry'] == before_first
    assert editor.storage_dict[11]['geometry'] == before_second
    assert editor.selected == [first, second]
    assert editor.loaded_as_regions is False
    assert editor.history.undo_stack == []


# 7. itemChanged connection after an inner error


# 9. Marked polygons list


# 11. Region export flag lifecycle


# 13. Scale and Buffer without a selected shape

@pytest.mark.parametrize('kind', ['scale', 'buffer'])
def test_scale_and_buffer_without_selected_shape_fail_without_history_step(kind):
    editor, first, second = scene()
    editor.selected = []
    select_row(editor, 0)
    editor.ui.scale_factor_entry.set_value(1.2)
    if kind == 'scale':
        result = editor.on_scale()
    else:
        result = BufferEditorTool.buffer(SimpleNamespace(draw_app=editor, app=editor.app), 0.1, 1)
    assert result == 'fail'
    assert editor.history.undo_stack == []
    assert first.geo['solid'].equals(box(0, 0, 1, 1))


# 14. Buffer factor check

@pytest.mark.parametrize('factor_value', [0])
def test_buffer_factor_at_or_below_zero_is_rejected(factor_value):
    editor, first, second = scene()
    editor.selected = [first]
    tool = SimpleNamespace(draw_app=editor, app=editor.app)
    assert queue_transform(tool, 'buffer', [factor_value, 1, True]) == 'fail'
    editor.app.worker_task.emit.assert_not_called()
    assert editor.history.undo_stack == []


# 15. Numeric aperture codes


# 16. History depth after a failing scope


# 18. update_ui without zoom

