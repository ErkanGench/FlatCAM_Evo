"""GEO-03: construction input must not mutate committed geometry on rejection."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, box

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape, DrawToolUtilityShape, FCPath, FCCircle, FCRectangle, FCMove, FCCopy
from appEditors.geo_plugins.GeoCirclePlugin import CircleEditorTool
from appEditors.geo_plugins.GeoPathPlugin import PathEditorTool
from appEditors.geo_plugins.GeoCopyPlugin import CopyEditorTool
from appEditors.geo_plugins.GeoRectanglePlugin import RectangleEditorTool
from appGUI.GUIElements import FCDoubleSpinner, NumericalEvalEntry
from appGUI.MainGUI import MainGUI
from tests.test_geo_editor_history import editor_with_history, run_worker


TOOLS = [FCPath, FCCircle, FCRectangle, FCMove, FCCopy]
NAMES = dict(zip(TOOLS, ['path', 'circle', 'rectangle', 'move', 'copy']))


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def value(number):
    return SimpleNamespace(get_value=lambda: number, set_value=Mock())


def input_tool(cls, points=((0.0, 0.0),), length=5.0):
    original = DrawToolShape(LineString([(0, 0), (1, 0)]))
    editor = editor_with_history([original], [original])
    editor.app.mouse_pos, editor.app.on_jump_to = (3.0, 4.0), Mock()
    editor.app.jump_signal = Mock()
    editor.app.plotcanvas = SimpleNamespace(text_cursor=SimpleNamespace(parent=object()),
                                          view=SimpleNamespace(camera=SimpleNamespace(zoom_callback=Mock())))
    editor.app.ui = SimpleNamespace(notebook=Mock())
    editor.app.call_source, editor.app.geo_editor, editor.app.collection = 'geo_editor', editor, Mock()
    editor.app.options['geometry_editor_milling_type'] = 'cv'
    editor.x, editor.y = editor.app.mouse_pos
    editor.snap_x, editor.snap_y = editor.app.mouse_pos
    editor.snap = lambda x, y: (x, y)
    editor.in_action = bool(points)
    editor.delete_utility_geometry = lambda: AppGeoEditor.delete_utility_geometry(editor)
    editor.draw_utility_geometry = Mock()
    editor.select_tool = Mock()
    tool = cls.__new__(cls)
    tool.draw_app, tool.app, tool.storage = editor, editor.app, editor.storage
    tool.name, tool.points, tool.complete = NAMES[cls], list(points), False
    tool.geometry, tool.util_geo = None, None
    tool.new_segment, tool.cursor_data_control = False, True
    tool.draw_cursor_data = Mock()
    tool.origin = points[0] if points else None
    tool.destination, tool.has_selection, tool.sel_limit = None, True, 30
    tool.steps_per_circ = 16
    ui = SimpleNamespace(x_entry=value(0.0), y_entry=value(0.0), angle_entry=value(0.0),
                         radius_link_btn=SimpleNamespace(isChecked=lambda: True),
                         radius_x_entry=value(length), radius_y_entry=value(length),
                         mode_radio=value('n'), corner_radio=value('s'), radius_entry=value(0.0),
                         add_button=QtWidgets.QPushButton(), clear_btn=QtWidgets.QPushButton(),
                         path_tool_frame=QtWidgets.QWidget(), copy_frame=QtWidgets.QWidget(),
                         circle_frame=QtWidgets.QWidget(), rect_frame=QtWidgets.QWidget())
    panel = SimpleNamespace(length=length, width=length, radius_x=length, radius_y=length, ui=ui,
                            on_tab_close=Mock(), disconnect_signals=Mock())
    setattr(tool, {'path': 'path_tool', 'circle': 'circle_tool', 'rectangle': 'rect_tool',
                   'move': 'move_tool', 'copy': 'copy_tool'}[tool.name], panel)
    tool.ui = ui
    editor.active_tool = tool
    return editor, tool, panel, original


def dispatch(editor, key, monkeypatch):
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.NoModifier))
    gui = SimpleNamespace(app=editor.app, geo_select_btn=SimpleNamespace(isChecked=lambda: False))
    event = key if isinstance(key, int) else SimpleNamespace(key=key, native=SimpleNamespace())
    return MainGUI.keyPressEvent(gui, event)


def assert_uncommitted(editor, tool, original):
    assert list(editor.storage.get_objects()) == [original]
    assert original.geo.equals_exact(LineString([(0, 0), (1, 0)]), 0)
    assert not tool.complete
    assert not editor.undo()


@pytest.mark.parametrize('cls', TOOLS)
@pytest.mark.parametrize('key', ['Enter', int(QtCore.Qt.Key.Key_Return), int(QtCore.Qt.Key.Key_Enter)])
def test_enter_before_first_point_is_actionable_and_non_destructive(cls, key, monkeypatch):
    editor, tool, panel, original = input_tool(cls, points=())
    dispatch(editor, key, monkeypatch)
    assert_uncommitted(editor, tool, original)
    assert tool.points == []
    assert 'point' in str(editor.app.inform.emit.call_args).lower() or \
           'reference' in str(editor.app.inform.emit.call_args).lower()
    editor.app.on_jump_to.assert_not_called()
    editor.select_tool.assert_not_called()


@pytest.mark.parametrize('cls', TOOLS)
@pytest.mark.parametrize('number', [None, 'invalid', float('nan'), float('inf'), -float('inf')])
def test_invalid_numeric_input_keeps_construction_and_history(cls, number, monkeypatch):
    editor, tool, panel, original = input_tool(cls, length=number)
    dispatch(editor, 'Enter', monkeypatch)
    assert_uncommitted(editor, tool, original)
    assert tool.points == [(0.0, 0.0)]
    editor.app.on_jump_to.assert_not_called()
    editor.select_tool.assert_not_called()
    assert 'finite' in str(editor.app.inform.emit.call_args).lower()


@pytest.mark.parametrize('cls', TOOLS)
def test_zero_numeric_length_is_safe_and_actionable(cls):
    editor, tool, panel, original = input_tool(cls, length=0.0)
    response = tool.on_key('Enter')
    assert_uncommitted(editor, tool, original)
    assert response and ('nonzero' in response.lower() or 'positive' in response.lower())
    editor.app.on_jump_to.assert_not_called()


@pytest.mark.parametrize('cls', [FCPath, FCMove, FCCopy])
@pytest.mark.parametrize('mouse', [(0.0, 0.0), (float('inf'), 1.0), (float('nan'), 1.0)])
def test_projection_requires_finite_nonzero_direction(cls, mouse):
    editor, tool, panel, original = input_tool(cls)
    editor.app.mouse_pos = mouse
    response = tool.on_key('Enter')
    assert response
    assert_uncommitted(editor, tool, original)
    assert tool.points == [(0.0, 0.0)]
    editor.app.on_jump_to.assert_not_called()


@pytest.mark.parametrize('cls', [FCPath, FCMove, FCCopy])
def test_valid_numeric_projection_and_coordinate_jump(cls, monkeypatch):
    editor, tool, panel, original = input_tool(cls, length=10.0)
    # Path has no width and move/copy use Path/CopyEditorTool, which have no width property.
    del panel.width
    dispatch(editor, 'Enter', monkeypatch)
    editor.app.on_jump_to.assert_called_once_with(custom_location=(6.0, 8.0), fit_center=False)
    if cls is FCPath:
        assert tool.points[-1] == (6.0, 8.0)
        assert_uncommitted(editor, tool, original)
    else:
        assert editor.selected[0].geo.bounds == (6.0, 8.0, 7.0, 8.0) if cls is FCMove else \
            len(list(editor.storage.get_objects())) == 2
        assert editor.undo()
        assert list(editor.storage.get_objects()) == [original]


@pytest.mark.parametrize('cls', TOOLS)
def test_coordinate_jump_is_preserved(cls, monkeypatch):
    editor, tool, panel, original = input_tool(cls)
    dispatch(editor, 'J', monkeypatch)
    editor.app.on_jump_to.assert_called_once_with()
    assert_uncommitted(editor, tool, original)


@pytest.mark.parametrize('cls', TOOLS)
def test_backspace_only_removes_construction_points(cls, monkeypatch):
    editor, tool, panel, original = input_tool(cls)
    dispatch(editor, 'Backspace', monkeypatch)
    assert_uncommitted(editor, tool, original)
    assert tool.points == ([] if cls is FCPath else [(0.0, 0.0)])
    if cls is FCPath:
        assert not editor.in_action


@pytest.mark.parametrize('cls', TOOLS)
@pytest.mark.parametrize('route', ['escape', 'switch'])
def test_cancel_or_switch_cleans_preview_and_connections_without_committing(cls, route, monkeypatch):
    editor, tool, panel, original = input_tool(cls)
    editor.utility = [DrawToolUtilityShape(box(0, 0, 3, 4))]
    stale_callback = Mock()
    panel.ui.add_button.clicked.connect(stale_callback)
    panel.ui.clear_btn.clicked.connect(stale_callback)
    if cls in (FCPath, FCMove, FCCopy):
        disconnect = CopyEditorTool.disconnect_signals if cls is FCCopy else PathEditorTool.disconnect_signals
        panel.disconnect_signals = lambda: disconnect(panel)
    editor.tools = {}
    for name in ['select', 'path']:
        button = QtWidgets.QPushButton()
        button.setCheckable(True)
        editor.tools[name] = dict(button=button, constructor=lambda e: SimpleNamespace(name='select'))
    editor.on_tool_select = lambda name: AppGeoEditor.on_tool_select(editor, name)
    editor.select_tool = lambda name: AppGeoEditor.select_tool(editor, name)
    if route == 'escape':
        dispatch(editor, 'Escape', monkeypatch)
    else:
        editor.select_tool('select')
    assert list(editor.storage.get_objects()) == [original]
    assert not editor.undo()
    assert editor.active_tool.name == 'select'
    assert not editor.in_action
    editor.tool_shape.clear.assert_called()
    editor.app.jump_signal.disconnect.assert_called()
    assert editor.app.plotcanvas.text_cursor.parent is None
    assert tool.points == []
    assert editor.selected == [original]
    assert not editor.utility
    button = panel.ui.add_button if cls in (FCCircle, FCRectangle) else panel.ui.clear_btn
    button.click()
    stale_callback.assert_not_called()


@pytest.mark.parametrize('cls', [FCCircle, FCRectangle])
def test_enter_completion_without_preview_does_not_use_stale_geometry(cls, monkeypatch):
    editor, tool, panel, original = input_tool(cls)
    tool.util_geo = box(100, 100, 101, 101)
    dispatch(editor, 'Enter', monkeypatch)
    if cls is FCCircle:
        added = [s for s in editor.storage.get_objects() if s is not original]
        assert len(added) == 1
        assert added[0].geo.bounds == (-5.0, -5.0, 5.0, 5.0)
        assert editor.undo()
    else:
        editor.app.on_jump_to.assert_called_once_with(custom_location=(5.0, 5.0), fit_center=False)
        assert_uncommitted(editor, tool, original)


@pytest.mark.parametrize('center', [(0.0, 0.0), (10.0, -7.0)])
@pytest.mark.parametrize('key', ['Enter', int(QtCore.Qt.Key.Key_Return)])
def test_ellipse_major_axis_click_then_enter_keeps_preview_center(center, key, monkeypatch):
    editor, tool, panel, original = input_tool(FCCircle, points=())
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.NoModifier))
    for name in ('x_entry', 'y_entry', 'radius_x_entry', 'radius_y_entry', 'angle_entry'):
        entry = FCDoubleSpinner()
        entry.setRange(-1000000.0, 1000000.0)
        entry.setDecimals(12)
        setattr(panel.ui, name, entry)
    panel.ui.radius_link_btn = QtWidgets.QCheckBox()
    panel.ui.radius_link_btn.setChecked(False)

    class CirclePanel:
        radius_x = CircleEditorTool.radius_x
        radius_y = CircleEditorTool.radius_y

    numeric_panel = CirclePanel()
    numeric_panel.ui = panel.ui
    tool.circle_tool = numeric_panel
    tool.click(center)
    tool.click((center[0] + 3.0, center[1] + 4.0))
    preview = tool.util_geo
    assert (preview.centroid.x, preview.centroid.y) == pytest.approx(center)
    assert not tool.complete

    dispatch(editor, key, monkeypatch)
    added = [shape for shape in editor.storage.get_objects() if shape is not original]
    assert len(added) == 1
    committed = added[0].geo
    assert (committed.centroid.x, committed.centroid.y) == pytest.approx(center)
    assert committed.equals_exact(preview.exterior, 1e-9)
    assert (panel.ui.x_entry.get_value(), panel.ui.y_entry.get_value()) == center
    assert tool.points[0] == center
    assert original in editor.storage.get_objects()
    assert editor.undo()
    assert list(editor.storage.get_objects()) == [original]
    assert not editor.undo()


@pytest.mark.parametrize('cls', TOOLS)
def test_busy_enter_retains_construction_until_retry(cls, monkeypatch):
    editor, tool, panel, original = input_tool(cls)
    editor.submit_worker(Mock(), [])
    assert dispatch(editor, 'Enter', monkeypatch) == 'fail'
    assert tool.points == [(0.0, 0.0)]
    assert not tool.complete
    assert list(editor.storage.get_objects()) == [original]
    editor.app.on_jump_to.assert_not_called()
    run_worker(editor)


@pytest.mark.parametrize('cls', [CircleEditorTool, RectangleEditorTool])
@pytest.mark.parametrize('number', [None, 'invalid', float('nan'), float('inf'), 0.0])
def test_plugin_numeric_boundary_does_not_commit_malformed_geometry(cls, number):
    editor, tool, panel, original = input_tool(FCCircle)
    panel.ui.anchor_radio, panel.ui.corner_radio = value('c'), value('s')
    panel.ui.radius_entry = value(0.0)
    panel.ui.radius_x_entry, panel.ui.radius_y_entry = value(number), value(2.0)
    panel.ui.length_entry, panel.ui.width_entry = value(number), value(2.0)
    plugin = SimpleNamespace(app=editor.app, draw_app=editor, ui=panel.ui, mode='add')
    cls.on_add(plugin)
    assert_uncommitted(editor, tool, original)
    assert 'finite' in str(editor.app.inform.emit.call_args).lower()


@pytest.mark.parametrize('cls', TOOLS)
def test_direct_enter_before_first_point_is_safe(cls):
    editor, tool, panel, original = input_tool(cls, points=())
    response = tool.on_key('Enter')
    assert response and ('point' in response.lower() or 'reference' in response.lower())
    assert_uncommitted(editor, tool, original)


@pytest.mark.parametrize('cls', [FCCircle, FCRectangle])
def test_numeric_key_before_first_point_is_safe(cls):
    editor, tool, panel, original = input_tool(cls, points=())
    assert tool.on_key(QtCore.Qt.Key.Key_5)
    assert_uncommitted(editor, tool, original)


@pytest.mark.parametrize('cls', [FCPath, FCMove, FCCopy])
@pytest.mark.parametrize('qt_keys', [False, True])
@pytest.mark.parametrize('text, expected', [('2*5', 10.0), ('0.05', 0.05), ('2-2+5', 5.0)])
def test_numeric_expression_keys_use_existing_evaluator(cls, qt_keys, text, expected):
    editor, tool, panel, original = input_tool(cls, length=0.0)
    tool.new_segment = True
    panel.ui.project_line_entry = NumericalEvalEntry()
    panel.ui.project_line_entry.set_value(0.0)

    class LengthPanel:
        length = PathEditorTool.length

    numeric_panel = LengthPanel()
    numeric_panel.ui = panel.ui
    setattr(tool, {'path': 'path_tool', 'move': 'move_tool', 'copy': 'copy_tool'}[tool.name], numeric_panel)
    for char in text:
        tool.on_key(ord(char) if qt_keys else char)
    assert numeric_panel.length == expected
    tool.on_key('Enter')
    location = editor.app.on_jump_to.call_args.kwargs['custom_location']
    assert location == pytest.approx((0.6 * expected, 0.8 * expected))


@pytest.mark.parametrize('cls', [FCCircle, FCRectangle])
@pytest.mark.parametrize('point', [(0.0, 0.0), (float('nan'), 3.0)])
def test_invalid_completion_click_is_non_destructive(cls, point):
    editor, tool, panel, original = input_tool(cls)
    assert tool.click(point) == 'fail'
    assert_uncommitted(editor, tool, original)
    assert tool.points == [(0.0, 0.0)]


@pytest.mark.parametrize('cls', [FCCircle, FCRectangle])
def test_completion_click_without_mouse_move_builds_at_current_point(cls):
    editor, tool, panel, original = input_tool(cls)
    tool.util_geo = box(100, 100, 101, 101)
    tool.click((3.0, 4.0))
    editor.on_shape_complete()
    added = [s for s in editor.storage.get_objects() if s is not original]
    assert len(added) == 1
    assert added[0].geo.bounds == ((-5.0, -5.0, 5.0, 5.0) if cls is FCCircle else (0.0, 0.0, 3.0, 4.0))
    assert editor.undo()


def test_zero_length_path_enter_cannot_commit_degenerate_geometry(monkeypatch):
    editor, tool, panel, original = input_tool(FCPath, length=0.0)
    editor.x, editor.y = (0.0, 0.0)
    assert dispatch(editor, 'Enter', monkeypatch) == 'fail'
    assert_uncommitted(editor, tool, original)
    editor.select_tool.assert_not_called()
