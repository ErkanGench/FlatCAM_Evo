"""Numeric vertex edits replace one contour without losing its history or holes."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtWidgets
from shapely.geometry import LineString, LinearRing, Polygon, MultiLineString, box

from appEditors.appGeoEditor import AppGeoEditor, AppGeoEditorUI, DrawToolShape
from appGUI.GUIElements import FCTree
from tests.test_geo_editor_history import editor_with_history, run_worker


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def vertex_editor(geometry):
    shape = DrawToolShape(geometry)
    shape.data['custom'] = {'label': 'track'}
    editor = editor_with_history([shape], [shape])
    editor.plot_all = lambda: AppGeoEditor.plot_all(editor)
    editor.plot_changes = lambda: AppGeoEditor.plot_changes(editor)
    editor.plot_all()
    editor.apply_vertex_edit = lambda *a, **k: AppGeoEditor.apply_vertex_edit(editor, *a, **k)
    return editor, shape


@pytest.mark.parametrize('action,index,point,expected', [
    ('move', 1, (2, 1), [(0, 0), (2, 1), (4, 0)]),
    ('insert', 0, (1, 0), [(0, 0), (1, 0), (2, 0), (4, 0)]),
])
def test_open_path_edit_is_one_replacement_with_history(action, index, point, expected):
    editor, original = vertex_editor(LineString([(0, 0), (2, 0), (4, 0)]))
    assert editor.apply_vertex_edit(action, index, point) != 'fail'
    replacement, = editor.selected
    assert list(replacement.geo.coords) == expected
    assert replacement.data['custom'] == original.data['custom']
    assert replacement.data['bounds'] == replacement.geo.bounds
    assert editor.storage.nearest(expected[index if index < len(expected) else -1])[1] is replacement
    assert editor.sel_shapes.items == [replacement.geo]
    editor.build_ui_sig.emit.assert_called_once()
    assert editor.undo()
    assert editor.selected == [original]
    assert list(editor.storage.get_objects()) == [original]
    assert editor.sel_shapes.items == [original.geo]
    assert not editor.undo()
    assert editor.redo()
    assert editor.selected == [replacement]
    assert editor.sel_shapes.items == [replacement.geo]


@pytest.mark.parametrize('factory', [Polygon])
@pytest.mark.parametrize('index', [0, 4])
def test_closing_vertex_alias_moves_both_ends(factory, index):
    editor, original = vertex_editor(factory([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]))
    assert editor.apply_vertex_edit('move', index, (-1, -1)) != 'fail'
    geometry = editor.selected[0].geo
    coords = list(geometry.exterior.coords if isinstance(geometry, Polygon) else geometry.coords)
    assert coords[0] == coords[-1] == (-1, -1)
    assert type(geometry) is type(original.geo)
    assert len(coords) == 5


def test_polygon_holes_survive_move_insert_and_remove():
    hole = [(2, 2), (3, 2), (3, 3), (2, 3), (2, 2)]
    editor, original = vertex_editor(Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [hole]))
    for action, index, point in [('move', 0, (-1, -1)), ('insert', 1, (6, 3)), ('remove', 2, None)]:
        assert editor.apply_vertex_edit(action, index, point) != 'fail'
        assert list(editor.selected[0].geo.interiors[0].coords) == hole
    assert len(editor._history_undo) == 3
    for _ in range(3):
        assert editor.undo()
    assert editor.selected == [original]


@pytest.mark.parametrize('factory', [Polygon])
def test_insert_on_closing_segment_and_remove_closing_alias(factory):
    editor, original = vertex_editor(factory([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]))
    assert editor.apply_vertex_edit('insert', 3, (0, 2)) != 'fail'
    assert editor.apply_vertex_edit('remove', 5) != 'fail'
    geometry = editor.selected[0].geo
    coords = list(geometry.exterior.coords if isinstance(geometry, Polygon) else geometry.coords)
    assert coords == [(4, 0), (4, 4), (0, 4), (0, 2), (4, 0)]
    assert geometry.is_valid


@pytest.mark.parametrize('geometry,action,index,point', [
    (LineString([(0, 0), (1, 0)]), 'remove', 0, None),
    (LinearRing([(0, 0), (4, 0), (0, 4)]), 'remove', 0, None),
    (Polygon([(0, 0), (4, 0), (0, 4)]), 'remove', 3, None),
    (LineString([(0, 0), (2, 0), (4, 0)]), 'move', 1, (float('nan'), 0)),
    (LineString([(0, 0), (2, 0)]), 'move', 2, (1, 0)),
    (Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [[(1, 1), (2, 1), (2, 2), (1, 2)]]),
     'move', 0, (4, 4)),
])
def test_invalid_edits_preserve_storage_selection_and_redo(geometry, action, index, point):
    editor, original = vertex_editor(geometry)
    assert editor.apply_vertex_edit(action, index, point) == 'fail'
    assert editor.selected == [original]
    assert list(editor.storage.get_objects()) == [original]
    assert not editor.undo()
    editor.build_ui_sig.emit.assert_not_called()
    assert editor.app.inform.emit.called






def test_replacement_and_replay_update_real_tree_index_and_snap_cache():
    editor, original = vertex_editor(LineString([(0, 0), (2, 0)]))
    tree = FCTree(columns=3, extended_sel=True)
    editor.ui = SimpleNamespace(tw=tree, geo_parent=tree.invisibleRootItem(), geo_font=tree.font())
    editor.sync_tree_selection = lambda: AppGeoEditor.sync_tree_selection(editor)
    editor.build_ui_sig.emit = lambda: AppGeoEditor.build_ui(editor)
    AppGeoEditor.build_ui(editor)
    editor._snap_cache = object()
    assert editor.apply_vertex_edit('move', 0, (10, 10)) != 'fail'
    replacement = editor.selected[0]
    for shape, replay in [(replacement, editor.undo), (original, editor.redo), (replacement, None)]:
        assert tree.topLevelItemCount() == 1
        assert [item.text(0) for item in tree.selectedItems()] == [str(id(shape))]
        assert set(editor.storage.indexes) == {id(shape)}
        assert editor.storage.nearest((10, 10))[1] is shape
        assert editor._snap_cache is None
        if replay:
            assert replay()


def test_rejected_and_unchanged_edits_do_not_clear_redo():
    editor, original = vertex_editor(LineString([(0, 0), (2, 0)]))
    assert editor.apply_vertex_edit('move', 0, (1, 1)) != 'fail'
    assert editor.undo()
    assert editor.apply_vertex_edit('move', 0, (float('nan'), 0)) == 'fail'
    assert editor.apply_vertex_edit('move', 0, (0, 0)) != 'fail'
    assert editor.selected == [original]
    assert not editor.undo()
    assert editor.redo()


@pytest.mark.parametrize('geometry', [LineString([(0, 0, 1), (2, 0, 1)]),
                                    LineString([(0, 0), (1, 0), (1, 1), (0, 1)])])
def test_3d_or_self_crossing_result_is_rejected(geometry):
    editor, original = vertex_editor(geometry)
    assert editor.apply_vertex_edit('move', 0, (0, 2)) == 'fail'
    assert editor.selected == [original]
    assert not editor.undo()


def test_numeric_dialog_loads_index_and_applies_through_real_button(monkeypatch):
    editor, original = vertex_editor(LineString([(0, 0), (2, 0), (4, 0)]))
    editor.decimals = 4
    app = SimpleNamespace(decimals=4, app_units='mm', resource_location='', on_editing_finished=Mock())
    editor.ui = AppGeoEditorUI(app)
    editor.ui.vertex_edit_btn.clicked.connect(lambda: AppGeoEditor.on_edit_vertices(editor))

    def exercise(dialog):
        index = dialog.findChild(QtWidgets.QSpinBox, 'vertex_index')
        x = dialog.findChild(QtWidgets.QLineEdit, 'vertex_x')
        y = dialog.findChild(QtWidgets.QLineEdit, 'vertex_y')
        index.setValue(1)
        assert float(x.text()) == 2 and float(y.text()) == 0
        x.setText('2')
        y.setText('1')
        dialog.findChild(QtWidgets.QPushButton, 'vertex_apply').click()
        assert list(editor.selected[0].geo.coords)[1] == (2, 1)
        x.setText('nan')
        dialog.findChild(QtWidgets.QPushButton, 'vertex_apply').click()
        assert len(editor._history_undo) == 1
        operation = dialog.findChild(QtWidgets.QComboBox)
        operation.setCurrentIndex(1)
        index.setValue(0)
        x.setText('1')
        y.setText('0.5')
        dialog.findChild(QtWidgets.QPushButton, 'vertex_apply').click()
        assert len(editor.selected[0].geo.coords) == 4
        assert index.maximum() == 3
        operation.setCurrentIndex(2)
        assert not x.isEnabled() and not y.isEnabled()
        index.setValue(1)
        dialog.findChild(QtWidgets.QPushButton, 'vertex_apply').click()
        assert len(editor.selected[0].geo.coords) == 3
        assert index.maximum() == 2
        operation.setCurrentIndex(0)
        assert x.isEnabled() and y.isEnabled()
        dialog.reject()
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, 'exec', exercise)
    editor.ui.vertex_edit_btn.click()
    for _ in range(3):
        assert editor.undo()
    assert editor.selected == [original]
