"""Overlay event handoff without a renderer flag or legacy connection IDs."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_distance_event_handoff_and_right_click():
    source = Path(__file__).resolve().parents[1] / 'appPlugins' / 'ToolDistance.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    tool_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Distance')
    names = {'ui_connect', 'ui_disconnect', 'on_mouse_click_release'}
    methods = [node for node in tool_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {'_': lambda text: text}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)

    canvas = Mock()
    canvas.translate_coords.return_value = (4.0, 5.0)
    app = SimpleNamespace(call_source='app', grid_status=lambda: False, inform=Mock(),
                          on_mouse_move_over_plot=Mock(), on_mouse_click_over_plot=Mock(),
                          on_mouse_click_release_over_plot=Mock())
    tool = SimpleNamespace(app=app, canvas=canvas, original_call_source='app',
                           on_mouse_move=Mock(), on_mouse_click_release=Mock(),
                           mouse_is_dragging=False, points=[], on_exit=Mock(),
                           ui=SimpleNamespace(snap_center_cb=SimpleNamespace(get_value=lambda: False),
                                              multipoint_cb=SimpleNamespace(get_value=lambda: False)))
    for _ in range(2):
        namespace['ui_connect'](tool)
        namespace['ui_disconnect'](tool)
    assert canvas.graph_event_connect.call_count == 10
    assert canvas.graph_event_disconnect.call_count == 10
    assert all(len(call.args) == 2 for call in canvas.graph_event_disconnect.call_args_list)
    assert not any(hasattr(tool, name) or hasattr(app, name) for name in ('mm', 'mp', 'mr'))

    event = SimpleNamespace(pos=(40, 50), button=3)
    namespace['on_mouse_click_release'](tool, event)
    tool.on_exit.assert_not_called()
    event.button = 2
    tool.mouse_is_dragging = True
    namespace['on_mouse_click_release'](tool, event)
    tool.on_exit.assert_not_called()
    tool.mouse_is_dragging = False
    namespace['on_mouse_click_release'](tool, event)
    tool.on_exit.assert_called_once_with()
    canvas.translate_coords.assert_called_with(event.pos)
