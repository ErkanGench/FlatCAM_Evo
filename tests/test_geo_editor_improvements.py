"""Geometry picking uses screen intent; affine replacements retain ready render buffers."""
from types import SimpleNamespace
from unittest.mock import Mock
from copy import deepcopy
import pickle

import numpy as np
import pytest
from PyQt6 import QtCore, QtWidgets
from shapely import LineString, Polygon, box

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape, FCSelect, FCMove
from appGUI.VisPyVisuals import ShapeCollectionVisual
from tests.test_geo_editor_delete_plot import pick_editor
from tests.test_geo_editor_history import editor_with_history, interactive_move_editor, run_worker


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_overlap_cycles_and_preserves_unrelated_multiselection(monkeypatch):
    big, small, other = [DrawToolShape(geo) for geo in (box(0, 0, 10, 10), box(4, 4, 6, 6), box(20, 0, 21, 1))]
    editor = pick_editor([big, small, other])
    editor.selected = [other]
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        lambda: QtCore.Qt.KeyboardModifier.ControlModifier)
    editor.click_select((5, 5))
    assert editor.selected == [other, small]
    editor.click_select((5.01, 5))
    assert editor.selected == [other, big]
    editor.click_select((5, 5))
    assert editor.selected == [other, small]
    assert '2' in str(editor.app.inform.emit.call_args_list)
    # Moving farther than five pixels resets even when the same polygons overlap.
    editor.click_select((5.2, 5))
    assert editor.selected == [other]








def canvas_editor():
    editor, _, _ = interactive_move_editor()
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: (pos[0] / 100, pos[1] / 100))
    editor.snap = Mock(return_value=(0, 0))
    editor.app.grid_status = lambda: True
    editor.app.delete_selection_shape = Mock()
    editor.draw_selection_area_handler = Mock()
    editor.app.selection_type = None
    tool = FCSelect.__new__(FCSelect)
    tool.draw_app, tool.name = editor, 'select'
    tool.click_release = Mock()
    editor.active_tool = tool
    return editor






def render_editor(monkeypatch):
    monkeypatch.setattr(ShapeCollectionVisual, '_ShapeCollectionVisual__update', lambda self: None)
    shape = DrawToolShape(Polygon([(0, 0), (4, 0), (4, 3), (0, 3)], [[(1, 1), (2, 1), (2, 2), (1, 2)]]))
    editor = editor_with_history([shape], [shape])
    options = {'global_graphic_engine_3d_no_mp': True, 'global_backface_culling': True}
    editor.shapes = ShapeCollectionVisual(layers=3, fcoptions=options)
    editor.sel_shapes = ShapeCollectionVisual(layers=3, fcoptions=options)
    editor.plot_all = lambda: AppGeoEditor.plot_all(editor)
    editor.plot_changes = lambda: AppGeoEditor.plot_changes(editor)
    editor.plot_all()
    editor.plot_shape = Mock(wraps=editor.plot_shape)
    return editor, shape


@pytest.mark.parametrize('method,args,kwargs', [
    ('offset', ((10, -5),), {}), ('rotate', (30,), {'point': (1, 2)}),
    ('scale', (2, 3), {'point': (1, 2)}), ('skew', (20, 10), {'point': (1, 2)}),
    ('mirror', ('X', (1, 2)), {}),
])
def test_affine_reuses_both_buffers_and_replays_replacement_history(monkeypatch, method, args, kwargs):
    editor, source = render_editor(monkeypatch)
    key = editor._rendered[id(source)][3][0]
    selection_key = editor._rendered[id(source)][4][0]
    original = editor.shapes.data[key]['line_pts'].copy()
    AppGeoEditor.transform_shapes(editor, method, *args, **kwargs)
    replacement = editor.selected[0]
    assert replacement is not source
    assert editor._rendered[id(replacement)][3] == [key]
    assert editor._rendered[id(replacement)][4] == [selection_key]
    editor.plot_shape.assert_not_called()
    np.testing.assert_allclose(editor.shapes.data[key]['line_pts'],
                               editor.sel_shapes.data[selection_key]['line_pts'])
    expected = np.asarray([point for ring in (replacement.geo.exterior, *replacement.geo.interiors)
                           for point in ring.coords])
    np.testing.assert_allclose(np.unique(np.round(editor.shapes.data[key]['line_pts'], 4), axis=0),
                               np.unique(np.round(expected, 4), axis=0), atol=1e-4)
    assert editor.undo()
    assert editor.selected == [source]
    np.testing.assert_allclose(editor.shapes.data[key]['line_pts'], original, atol=2e-6)
    assert editor.redo()
    assert editor.selected == [replacement]
    editor.plot_shape.assert_not_called()


def test_interactive_move_records_affine_provenance(monkeypatch):
    editor, source = render_editor(monkeypatch)
    key = editor._rendered[id(source)][3][0]
    tool = FCMove.__new__(FCMove)
    tool.draw_app, tool.origin, tool.destination = editor, (0, 0), (3, 2)
    tool.draw_cursor_data = Mock()
    editor.active_tool = tool
    editor.app.jump_signal = Mock()
    editor.app.options['geometry_editor_milling_type'] = 'cv'
    editor.delete_utility_geometry = Mock()
    tool.make()
    editor.on_shape_complete()
    assert editor._rendered[id(editor.selected[0])][3] == [key]
    editor.plot_shape.assert_not_called()




def test_move_shape_pick_keeps_reference_location_snapped():
    editor = canvas_editor()
    editor.selected = []
    editor.app.jump_signal = Mock()
    tool = FCMove.__new__(FCMove)
    tool.draw_app, tool.storage, tool.name = editor, editor.storage, 'move'
    tool.has_selection, tool.origin, tool.complete = False, None, False
    tool.selection_bbox = Mock()
    editor.active_tool = tool
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    assert tool.has_selection
    assert tool.origin == (0, 0)


def test_selection_move_preview_uses_raw_marquee_and_ignores_small_drag():
    editor = canvas_editor()
    editor.app.app_cursor = Mock()
    editor.app.plotcanvas = SimpleNamespace(cursor_color='black', on_update_text_hud=Mock())
    editor.app.ui.update_location_labels = Mock()
    editor.app.draw_moving_selection_shape = Mock()
    editor.update_utility_geometry = Mock()
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    AppGeoEditor.on_canvas_move(editor, SimpleNamespace(pos=(26, 37), button=1, is_dragging=True))
    editor.app.draw_moving_selection_shape.assert_not_called()
    assert editor.app.selection_type is None
    AppGeoEditor.on_canvas_move(editor, SimpleNamespace(pos=(3, 57), button=1, is_dragging=True))
    assert editor.app.draw_moving_selection_shape.call_args.args[:2] == ((0.23, 0.37), (0.03, 0.57))
    assert editor.app.selection_type is False


def test_selection_marquee_uses_only_x_and_y_of_the_vispy_coords():
    # VisPy translate_coords() gives (x, y, z, w); the marquee and the area pick need (x, y)
    editor = canvas_editor()
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: np.array([pos[0] / 100, pos[1] / 100, 0.0, 1.0]))
    editor.app.app_cursor = Mock()
    editor.app.plotcanvas = SimpleNamespace(cursor_color='black', on_update_text_hud=Mock())
    editor.app.ui.update_location_labels = Mock()
    editor.app.draw_moving_selection_shape = Mock()
    editor.update_utility_geometry = Mock()
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    AppGeoEditor.on_canvas_move(editor, SimpleNamespace(pos=(3, 57), button=1, is_dragging=True))
    start, end = editor.app.draw_moving_selection_shape.call_args.args[:2]
    assert len(start) == 2 and len(end) == 2
    AppGeoEditor.on_canvas_click_release(editor, SimpleNamespace(pos=(3, 57), button=1))
    start, end, __ = editor.draw_selection_area_handler.call_args.args
    assert len(start) == 2 and len(end) == 2




@pytest.mark.parametrize('name', ['circle', 'rectangle'])
def test_shift_shape_edit_picks_raw_instead_of_copying_coordinates(name, monkeypatch):
    editor = canvas_editor()
    editor.active_tool = SimpleNamespace(name=name, click=Mock())
    editor.app.clipboard = Mock()
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        lambda: QtCore.Qt.KeyboardModifier.ShiftModifier)
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(23, 37), button=1))
    editor.active_tool.click.assert_called_once_with((0.23, 0.37))
    editor.app.clipboard.setText.assert_not_called()




def test_affine_reuse_follows_selection_changes_and_multistep_history(monkeypatch):
    editor, source = render_editor(monkeypatch)
    editor.selected = []
    editor.plot_changes()
    key = editor._rendered[id(source)][3][0]
    editor.selected = [source]  # model selection can change before the next plot
    AppGeoEditor.transform_shapes(editor, 'offset', (10, 0))
    first = editor.selected[0]
    AppGeoEditor.transform_shapes(editor, 'rotate', 90, point=(0, 0))
    second = editor.selected[0]
    assert editor._rendered[id(second)][3] == [key]
    assert editor.undo() and editor.selected == [first]
    assert editor.undo() and editor.selected == [source]
    assert editor.redo() and editor.redo()
    assert editor._rendered[id(second)][3] == [key]
    editor.selected = []
    editor.plot_changes()
    assert editor._rendered[id(second)][4] == []
    assert editor.shapes.data[key]['visible']
    editor.plot_shape.assert_not_called()
