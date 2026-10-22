"""GPU-free checks for the Geometry Editor's VisPy callback lifecycle."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_vispy_only_geo_editor_lifecycle():
    source = (Path(__file__).resolve().parents[1] / 'appEditors' / 'appGeoEditor.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.Attribute) and node.attr in
                   {'use_3d_engine', 'xdata', 'ydata', 'mp', 'mm', 'mr', 'mdc', 'kp'}
                   for node in ast.walk(tree))
    assert 'ShapeCollectionLegacy' not in source

    editor_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AppGeoEditor')
    methods: list[ast.stmt] = [node for node in editor_class.body if isinstance(node, ast.FunctionDef) and
               node.name in {'connect_canvas_event_handlers', 'disconnect_canvas_event_handlers'}]
    namespace = {}
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<geo lifecycle>', 'exec'), namespace)

    callbacks = {}

    def connect(event_name, callback):
        handlers = callbacks.setdefault(event_name, [])
        if callback not in handlers:
            handlers.append(callback)

    def disconnect(event_name, callback):
        handlers = callbacks.setdefault(event_name, [])
        if callback in handlers:
            handlers.remove(callback)

    canvas = SimpleNamespace(graph_event_connect=connect, graph_event_disconnect=disconnect)
    ui_names = ('popmenu_copy', 'popmenu_delete', 'popmenu_move', 'draw_line', 'draw_rect', 'draw_circle',
                'draw_poly', 'draw_arc', 'draw_text', 'draw_simplification', 'draw_buffer', 'draw_paint',
                'draw_eraser', 'draw_union', 'draw_intersect', 'draw_substract', 'draw_substract_alt',
                'draw_cut', 'draw_transform', 'draw_move', 'draw_polygonize')
    app = SimpleNamespace(plotcanvas=canvas, ui=SimpleNamespace(**{name: Mock() for name in ui_names}),
                          jump_signal=Mock(), on_copy_command=Mock(), on_delete=Mock(), obj_move=Mock())
    editor = SimpleNamespace(app=app, canvas=canvas)
    for name in ('on_canvas_click', 'on_canvas_move', 'on_canvas_click_release', 'select_tool', 'on_delete_btn',
                 'draw_tool_path', 'draw_tool_rectangle', 'union', 'intersection', 'subtract', 'subtract_2',
                 'cutpath', 'on_move', 'polygonize'):
        setattr(editor, name, Mock())
    app_handlers = {}
    editor_handlers = dict(zip(('mouse_press', 'mouse_move', 'mouse_release'),
                               (editor.on_canvas_click, editor.on_canvas_move, editor.on_canvas_click_release)))
    for event_name, name in (('mouse_press', 'on_mouse_click_over_plot'),
                             ('mouse_move', 'on_mouse_move_over_plot'),
                             ('mouse_release', 'on_mouse_click_release_over_plot'),
                             ('mouse_double_click', 'on_mouse_double_click_over_plot')):
        callback = Mock()
        setattr(app, name, callback)
        app_handlers[event_name] = callback
        connect(event_name, callback)

    for _ in range(3):
        namespace['connect_canvas_event_handlers'](editor)
        assert callbacks == {name: [editor_handlers[name]] if name in editor_handlers else []
                             for name in app_handlers}
        namespace['disconnect_canvas_event_handlers'](editor)
        assert callbacks == {name: [callback] for name, callback in app_handlers.items()}
    assert not any(name in vars(app) or name in vars(editor) for name in ('mp', 'mm', 'mr', 'mdc', 'kp'))
