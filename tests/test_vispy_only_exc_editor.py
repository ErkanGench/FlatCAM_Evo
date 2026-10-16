"""GPU-free checks of the Excellon editor's VisPy callback lifecycle."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_vispy_only_exc_editor_lifecycle():
    source = (Path(__file__).parents[1] / 'appEditors' / 'appExcEditor.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    def method(class_name, name):
        node = next(node for node in classes[class_name].body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<editor method>', 'exec'), namespace)
        return namespace[name]

    callbacks = {}
    canvas = SimpleNamespace(
        graph_event_connect=lambda event, callback: callbacks.setdefault(event, []).append(callback),
        graph_event_disconnect=lambda event, callback: callbacks[event].remove(callback)
    )
    app = SimpleNamespace(
        plotcanvas=canvas,
        collection=SimpleNamespace(view=SimpleNamespace(clicked=Mock()), on_mouse_down=Mock()),
        ui=SimpleNamespace(**{name: SimpleNamespace(triggered=Mock()) for name in (
            'popmenu_copy', 'popmenu_delete', 'popmenu_move', 'drill', 'drill_array')}),
        jump_signal=Mock(),
        **{name: Mock() for name in ('on_mouse_click_over_plot', 'on_mouse_move_over_plot',
                                    'on_mouse_click_release_over_plot', 'on_mouse_double_click_over_plot',
                                    'on_copy_command', 'on_delete', 'obj_move')}
    )
    editor = SimpleNamespace(app=app, canvas=canvas, **{name: Mock() for name in (
        'on_canvas_click', 'on_canvas_move', 'on_exc_click_release', 'exc_copy_drills',
        'on_delete_btn', 'exc_move_drills', 'exc_add_drill', 'exc_add_drill_array')})
    app_callbacks = dict(zip(('mouse_press', 'mouse_move', 'mouse_release', 'mouse_double_click'), (
        app.on_mouse_click_over_plot, app.on_mouse_move_over_plot,
        app.on_mouse_click_release_over_plot, app.on_mouse_double_click_over_plot)))
    for event, callback in app_callbacks.items():
        canvas.graph_event_connect(event, callback)
    for _ in range(3):
        method('AppExcEditor', 'connect_canvas_event_handlers')(editor)
        assert callbacks == {'mouse_press': [editor.on_canvas_click], 'mouse_move': [editor.on_canvas_move],
                             'mouse_release': [editor.on_exc_click_release], 'mouse_double_click': []}
        method('AppExcEditor', 'disconnect_canvas_event_handlers')(editor)
        assert callbacks == {event: [callback] for event, callback in app_callbacks.items()}
        assert not any(hasattr(owner, name) for owner in (app, editor) for name in ('mm', 'mp', 'mr', 'mdc', 'kp'))

    canvas.text_cursor = SimpleNamespace(parent=object())
    canvas.view = SimpleNamespace(camera=SimpleNamespace(zoom_callback=Mock()))
    draw_app = SimpleNamespace(app=app, selected=[], ui=Mock(), plot_all=Mock(), snap_x=1, snap_y=2)
    for name in ('DrillAdd', 'DrillArray', 'SlotAdd', 'SlotArray', 'ResizeEditorExc', 'CopyEditorExc'):
        tool = SimpleNamespace(draw_app=draw_app, cursor_data_control=True, copy_tool=Mock())
        canvas.text_cursor.parent = object()
        method(name, 'draw_cursor_data')(tool, delete=True)
        assert canvas.text_cursor.parent is None
        assert canvas.view.camera.zoom_callback() is None
        canvas.text_cursor.parent = object()
        method(name, 'clean_up')(tool)
        assert canvas.text_cursor.parent is None
        assert canvas.view.camera.zoom_callback() is None

    assert not any(isinstance(node, ast.Attribute) and node.attr in (
        'use_3d_engine', 'xdata', 'ydata') for node in ast.walk(tree))
    assert 'PlotCanvasLegacy' not in source
