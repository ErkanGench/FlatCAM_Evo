"""GPU-free checks for manufacturing plugin event retirement."""

import ast
import math
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtGui
from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box


def test_cutout_mouse_move_uses_vispy_position():
    source = (Path(__file__).parents[1] / 'appPlugins' / 'ToolCutOut.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == 'on_mouse_move')
    namespace = dict(math=math, rotate=rotate, Polygon=Polygon,
                     MultiPolygon=MultiPolygon, MultiLineString=MultiLineString)
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'ToolCutOut', 'exec'), namespace)
    event = namedtuple('VispyEvent', 'pos is_dragging')(('10', '20'), True)
    cut_geo = box(2, 3, 6, 7)
    tool = SimpleNamespace(
        app=Mock(), canvas=Mock(), cutting_geo=Mock(return_value=cut_geo),
        man_cutout_obj=SimpleNamespace(solid_geometry=[LineString([(3, 4), (5, 6)])]),
        draw_utility_geometry=Mock())
    tool.canvas.translate_coords.return_value = ('3.4', '4.6')
    tool.app.grid_status.return_value = True
    tool.app.geo_editor.snap.return_value = (4, 5)

    namespace['on_mouse_move'](tool, event)

    tool.app.on_mouse_move_over_plot.assert_called_once_with(event=event)
    tool.canvas.translate_coords.assert_called_once_with((10.0, 20.0))
    tool.app.geo_editor.snap.assert_called_once_with(3.4, 4.6)
    assert (tool.x_pos, tool.y_pos) == (4, 5)
    assert tool.mouse_is_dragging is True
    tool.cutting_geo.assert_called_once_with(pos=(4, 5))
    tool.app.geo_editor.tool_shape.clear.assert_called_once_with(update=True)
    # the gaps are cut by distance along the contour, so the preview is the gap shape itself (no rotation)
    tool.draw_utility_geometry.assert_called_once_with(geo=cut_geo)
    assert event.pos == ('10', '20')


@pytest.mark.parametrize('plugin', ['ToolCutOut', 'ToolDrilling', 'ToolFollow', 'ToolIsolation',
                                  'ToolMilling', 'ToolPunchGerber'])
def test_supported_keys_without_legacy_backend(plugin):
    source = (Path(__file__).parents[1] / 'appPlugins' / (plugin + '.py')).read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert 'use_3d_engine' not in source
    assert 'mpl_key_event' not in source
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == 'on_key_press')
    namespace = {'QtCore': QtCore, 'QtGui': QtGui, '_': lambda text: text}
    exec(compile(ast.Module(body=[method], type_ignores=[]), plugin, 'exec'), namespace)
    tool = SimpleNamespace(points=[(1, 2)], poly_drawn=True,
                           delete_moving_selection_shape=Mock(), delete_tool_selection_shape=Mock())
    for event in (int(QtCore.Qt.Key.Key_A),
                  QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_A,
                                  QtCore.Qt.KeyboardModifier.NoModifier),
                  SimpleNamespace(key='A')):
        namespace['on_key_press'](tool, event)
    if plugin in ('ToolDrilling', 'ToolMilling'):
        for event in (int(QtCore.Qt.Key.Key_Escape),
                      QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape,
                                      QtCore.Qt.KeyboardModifier.NoModifier),
                      SimpleNamespace(key='Escape')):
            namespace['on_key_press'](tool, event)
            assert tool.points == []
            assert tool.poly_drawn is False
        assert tool.delete_moving_selection_shape.call_count == 3
        assert tool.delete_tool_selection_shape.call_count == 3
    else:
        tool.app = Mock(options={})
        tool.ui = Mock()
        tool.ui.big_cursor_cb.get_value.return_value = False
        tool.on_key_press = Mock()
        tool.on_mouse_move = Mock()
        tool.on_mouse_release = Mock()
        tool.on_mouse_click_release = Mock()
        tool.on_poly_mouse_click_release = Mock()
        tool.on_single_poly_mouse_release = Mock()
        tool.clear_aperture_marking = Mock()
        tool.poly_dict = {1: 'preview'}
        tool.sel_rect = [(0, 0)]
        tool.old_selection_state = True
        tool.old_selection_status = True
        tool.grid_status_memory = True
        tool.area_sel_disconnect_flag = plugin == 'ToolFollow'
        tool.poly_sel_disconnect_flag = plugin in ('ToolIsolation', 'ToolPunchGerber')
        tool.mouse_events_connected = True
        tool.mb_manual_cuts = ['cut']
        namespace['on_key_press'](tool, SimpleNamespace(key='Escape'))
        if plugin == 'ToolCutOut':
            assert tool.mb_manual_cuts == []
        assert tool.app.plotcanvas.graph_event_disconnect.call_count >= 2
        if plugin in ('ToolIsolation', 'ToolPunchGerber'):
            tool.app.ui.grid_snap_btn.trigger.assert_called_once_with()
            assert tool.poly_sel_disconnect_flag is False
        if plugin == 'ToolFollow':
            assert tool.area_sel_disconnect_flag is False
        calls = list(tool.app.plotcanvas.mock_calls)
        namespace['on_key_press'](tool, SimpleNamespace(key='Escape'))
        assert tool.app.plotcanvas.mock_calls == calls
        if plugin in ('ToolIsolation', 'ToolPunchGerber'):
            tool.app.ui.grid_snap_btn.trigger.assert_called_once_with()
