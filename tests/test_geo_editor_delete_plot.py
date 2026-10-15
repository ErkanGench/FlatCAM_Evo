"""Geometry Editor: shape deletion and full replot."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtWidgets
from shapely.geometry import LineString, box

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape


class FakeCollection:
    """Records clears, plotted shapes and redraws like a ShapeCollection."""

    def __init__(self):
        self.calls = []
        self.items = []

    def clear(self, update=False):
        self.calls.append(('clear', update))
        self.items = []

    def add(self, shape=None, color=None, **kwargs):
        self.calls.append(('add', color))
        self.items.append(shape)
        return len(self.items)

    def redraw(self, *args, **kwargs):
        self.calls.append(('redraw',))


def make_editor(shapes, selected=(), utility=()):
    storage = AppGeoEditor.make_storage()
    for shp in shapes:
        storage.insert(shp)
    app = SimpleNamespace(
        options={'global_draw_color': '#112233FF', 'global_sel_draw_color': '#AABBCCFF', 'global_theme': 'default'},
        defaults=SimpleNamespace(get=lambda k, d=None: d, factory_defaults={}), log=Mock())
    editor = SimpleNamespace(
        app=app, storage=storage, selected=list(selected), utility=list(utility),
        shapes=FakeCollection(), sel_shapes=FakeCollection(),
        fcgeometry=SimpleNamespace(drawing_tolerance=0.01), build_ui=Mock(), plot_all=Mock())
    editor.get_selected = lambda: editor.selected
    editor.get_draw_color = lambda: AppGeoEditor.get_draw_color(editor)
    editor.get_sel_color = lambda: AppGeoEditor.get_sel_color(editor)
    editor.plot_shape = lambda *a, **k: AppGeoEditor.plot_shape(editor, *a, **k)
    editor.delete_shape = lambda s: AppGeoEditor.delete_shape(editor, s)
    return editor


def line(x):
    return DrawToolShape(LineString([(x, 0), (x, 1)]))


class TestGeoEditorDelete(unittest.TestCase):
    def test_delete_selected_removes_every_selected_shape(self):
        a, b, c, d = line(0), line(1), line(2), line(3)
        editor = make_editor([a, b, c, d], selected=[a, b, c], utility=[b])
        sel_list = editor.selected
        editor.sel_shapes.clear = Mock()
        editor.sel_shapes.redraw = Mock()
        AppGeoEditor.delete_selected(editor)
        self.assertEqual(list(editor.storage.get_objects()), [d])
        self.assertEqual(editor.selected, [])
        self.assertEqual(editor.utility, [])
        self.assertIs(editor.selected, sel_list)

    def test_delete_single_shape_not_in_list(self):
        a, b, c = line(0), line(1), line(2)
        editor = make_editor([a, b, c], selected=[a, b], utility=[a, c])
        AppGeoEditor.delete_shape(editor, b)
        self.assertEqual(list(editor.storage.get_objects()), [a, c])
        self.assertEqual(editor.selected, [a])
        self.assertEqual(editor.utility, [a, c])


if __name__ == '__main__':
    unittest.main()
