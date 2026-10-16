"""GPU-free checks for Paint/NCC controller cancellation ownership."""

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PyQt6 import QtCore, QtGui
from vispy.util.keys import ESCAPE


def load_method(plugin, name):
    source = (Path(__file__).parents[1] / 'appPlugins' / (plugin + '.py')).read_text(encoding='utf-8')
    method = next(node for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'QtCore': QtCore, 'QtGui': QtGui, '_': lambda text: text, 'deepcopy': deepcopy}
    exec(compile(ast.Module(body=[method], type_ignores=[]), plugin, 'exec'), namespace)
    return namespace[name]


@pytest.mark.parametrize('plugin,selection', [('ToolPaint/Paint', 'area'),
                                              ('ToolPaint/Paint', 'poly'),
                                              ('ToolNCC/Ncc', 'area')])
@pytest.mark.parametrize('event_form', ['integer', 'qt', 'vispy'])
@pytest.mark.parametrize('grid_enabled', [False, True])
def test_escape_releases_selection_once_and_allows_reentry(plugin, selection, event_form, grid_enabled):
    callback = load_method(plugin, 'on_key_press')
    activate = load_method(plugin + 'Gen', 'on_ncc_click' if plugin == 'ToolNCC/Ncc' else
                           '_paint_poly_single' if selection == 'poly' else '_paint_poly_area')
    event = {'integer': int(QtCore.Qt.Key.Key_Escape),
             'qt': QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape,
                                  QtCore.Qt.KeyboardModifier.NoModifier),
             'vispy': SimpleNamespace(key=ESCAPE)}[event_form]
    tool = SimpleNamespace(
        app=Mock(), area_sel_disconnect_flag=False, poly_sel_disconnect_flag=False,
        grid_status_memory=None, points=[(1, 2)], poly_drawn=True, poly_dict={1: 'preview'},
        on_mouse_release=Mock(), on_mouse_move=Mock(), on_key_press=Mock(),
        on_single_poly_mouse_release=Mock(), delete_moving_selection_shape=Mock(),
        delete_tool_selection_shape=Mock())
    generator = SimpleNamespace(app=tool.app, parent_tool=tool, ui=Mock(), ncc_tools={},
                                paint_obj=object(), tooldia_list=[0.5])
    generator.ui.valid_cb.get_value.return_value = False
    generator.ui.select_method_combo.get_value.return_value = 1
    generator.ui.tools_table.selectedItems.return_value = [Mock(row=lambda: 0)]
    generator.ui.tools_table.item.return_value.text.return_value = '0.5'
    tool.app.options = {'geometry_circle_steps': 64, 'gerber_circle_steps': 64,
                        'tools_ncc_plotting': 'normal'}
    generator.decimals = 4
    grid = tool.app.ui.grid_snap_btn
    grid.isChecked.return_value = grid_enabled
    grid.trigger.side_effect = lambda: setattr(grid.isChecked, 'return_value', not grid.isChecked())
    canvas = tool.app.plotcanvas
    flag = selection + '_sel_disconnect_flag'
    disconnects = [call('mouse_release', tool.on_mouse_release),
                   call('mouse_move', tool.on_mouse_move), call('key_press', tool.on_key_press)]
    connects = [call('mouse_press', tool.app.on_mouse_click_over_plot),
                call('mouse_move', tool.app.on_mouse_move_over_plot),
                call('mouse_release', tool.app.on_mouse_click_release_over_plot)]
    if selection == 'poly':
        disconnects = [call('mouse_release', tool.on_single_poly_mouse_release),
                       call('key_press', tool.on_key_press)]
        connects = [connects[2], connects[0]]

    callback(tool, event)
    canvas.graph_event_connect.assert_not_called()
    canvas.graph_event_disconnect.assert_not_called()
    tool.app.ui.grid_snap_btn.trigger.assert_not_called()
    tool.app.ui.notebook.setDisabled.assert_not_called()

    for activation in range(2):
        activate(generator)
        assert getattr(tool, flag) is True
        if selection == 'poly':
            assert tool.grid_status_memory is grid_enabled
            assert tool.paint_obj is generator.paint_obj
            assert tool.tooldia_list is generator.tooldia_list
            assert grid.isChecked() is False
        else:
            assert grid.isChecked() is grid_enabled
            tool.app.ui.notebook.setDisabled.assert_called_with(True)
        canvas.graph_event_connect.reset_mock()
        canvas.graph_event_disconnect.reset_mock()
        tool.app.ui.notebook.setDisabled.reset_mock()
        tool.points = [(1, 2)]
        tool.poly_drawn = True
        tool.poly_dict = {1: 'preview'}
        callback(tool, event)
        assert getattr(tool, flag) is False
        assert canvas.graph_event_disconnect.call_args_list == disconnects
        assert canvas.graph_event_connect.call_args_list == connects
        assert tool.app.ui.notebook.setDisabled.call_args_list == [call(False)]
        expected_toggles = 2 * (activation + 1) if grid_enabled and selection == 'poly' else 0
        assert tool.app.ui.grid_snap_btn.trigger.call_count == expected_toggles
        assert grid.isChecked() is grid_enabled
        assert tool.points == []
        assert tool.poly_drawn is False
        if plugin == 'ToolPaint/Paint':
            assert tool.poly_dict == {}
        tool.delete_moving_selection_shape.assert_called_with()
        tool.delete_tool_selection_shape.assert_called_with()
        if selection == 'poly' or plugin == 'ToolNCC/Ncc':
            assert tool.app.tool_shapes.clear.call_args_list == [call(update=True)] * (activation + 1)

        calls = list(tool.app.mock_calls)
        callback(tool, event)
        assert tool.app.mock_calls == calls


@pytest.mark.parametrize('grid_enabled', [False, True])
def test_paint_polygon_completion_uses_activation_state(grid_enabled):
    activate = load_method('ToolPaint/PaintGen', '_paint_poly_single')
    complete = load_method('ToolPaint/Paint', 'on_single_poly_mouse_release')
    cancel = load_method('ToolPaint/Paint', 'on_key_press')
    tool = SimpleNamespace(app=Mock(), gen=Mock(), poly_dict={1: 'polygon'},
                           area_sel_disconnect_flag=False, poly_sel_disconnect_flag=False,
                           grid_status_memory=None, points=[], poly_drawn=False,
                           on_single_poly_mouse_release=Mock(), on_key_press=Mock(),
                           delete_moving_selection_shape=Mock(), delete_tool_selection_shape=Mock())
    generator = SimpleNamespace(app=tool.app, parent_tool=tool, paint_obj=object(), tooldia_list=[0.5])
    tool.app.event_is_dragging = False
    tool.app.plotcanvas.translate_coords.return_value = (1, 2)
    grid = tool.app.ui.grid_snap_btn
    grid.isChecked.return_value = grid_enabled
    grid.trigger.side_effect = lambda: setattr(grid.isChecked, 'return_value', not grid.isChecked())

    activate(generator)
    assert tool.poly_sel_disconnect_flag is True
    complete(tool, SimpleNamespace(pos=(1, 2), button=2))
    assert tool.poly_sel_disconnect_flag is False
    assert grid.isChecked() is grid_enabled
    assert grid.trigger.call_count == (2 if grid_enabled else 0)
    tool.gen.paint_poly.assert_called_once_with(generator.paint_obj, inside_pt=(1, 2),
                                                poly_list=['polygon'], tooldia=generator.tooldia_list)
    assert tool.poly_dict == {}
    tool.app.tool_shapes.clear.assert_called_once_with(update=True)
    calls = list(tool.app.mock_calls)
    cancel(tool, int(QtCore.Qt.Key.Key_Escape))
    assert tool.app.mock_calls == calls
