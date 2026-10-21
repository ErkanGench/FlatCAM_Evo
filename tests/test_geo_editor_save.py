"""Geometry Editor: the save of the edited shapes into the Geometry object, and the load into the editor."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from shapely.geometry import LineString, MultiLineString

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape


def save_editor(geos, tooldia=0.5, multigeo_tool=None):
    storage = AppGeoEditor.make_storage()
    storage.replace(inserted=[DrawToolShape(geo) for geo in geos])
    editor = SimpleNamespace(
        storage=storage, multigeo_tool=multigeo_tool,
        app=SimpleNamespace(proc_container=MagicMock(), inform=Mock()),
        ui=SimpleNamespace(tooldia_entry=SimpleNamespace(get_value=lambda: tooldia)))
    editor.deactivate = Mock()
    return editor


def geometry_object(tooldia=0.5, tools=None):
    obj = SimpleNamespace(solid_geometry=[LineString([(9, 9), (10, 10)])], tools=tools or {},
                          obj_options={'tools_mill_tooldia': tooldia}, regenerate_source=Mock(return_value=True))
    obj.bounds = lambda: (0.0, 0.0, 2.0, 1.0)
    return obj


class TestGeoEditorSave(unittest.TestCase):
    def test_object_has_the_new_geometry_before_the_editor_ends(self):
        a, b = LineString([(0, 0), (1, 0)]), LineString([(0, 1), (2, 1)])
        editor = save_editor([a, b])
        obj = geometry_object()
        seen = []
        editor.deactivate.side_effect = lambda: seen.append(list(obj.solid_geometry))

        AppGeoEditor.update_editor_geometry(editor, obj)

        # the copy is done in the call (no worker thread), then the editor is deactivated 1 time
        self.assertEqual(obj.solid_geometry, [a, b])
        self.assertEqual(seen, [[a, b]])
        self.assertEqual((obj.obj_options['xmin'], obj.obj_options['ymax']), (0.0, 1.0))
        obj.regenerate_source.assert_called_once_with()
        editor.app.inform.emit.assert_called_once()

    def test_multilinestring_is_merged(self):
        multi = MultiLineString([[(0, 0), (1, 0)], [(1, 0), (1, 1)]])
        editor = save_editor([multi])
        obj = geometry_object()
        AppGeoEditor.update_editor_geometry(editor, obj)
        self.assertEqual(len(obj.solid_geometry), 1)
        self.assertEqual(obj.solid_geometry[0].geom_type, 'LineString')
        self.assertEqual(len(obj.solid_geometry[0].coords), 3)

    def test_new_tool_diameter(self):
        editor = save_editor([LineString([(0, 0), (1, 0)])], tooldia=0.8)
        obj = geometry_object(tooldia=0.5)
        AppGeoEditor.update_editor_geometry(editor, obj)
        self.assertEqual(obj.obj_options['tools_mill_tooldia'], 0.8)

    def test_multigeo_tool_gets_the_geometry(self):
        a = LineString([(0, 0), (1, 0)])
        tools = {1: {'tooldia': 0.5, 'data': {'tools_mill_tooldia': 0.5}, 'solid_geometry': []}}
        editor = save_editor([a], tooldia=0.6, multigeo_tool=1)
        obj = geometry_object(tools=tools)
        AppGeoEditor.update_editor_geometry(editor, obj)
        self.assertEqual(tools[1]['solid_geometry'], [a])
        self.assertEqual(tools[1]['tooldia'], 0.6)
        self.assertEqual(tools[1]['data']['tools_mill_tooldia'], 0.6)
        self.assertIsNone(editor.multigeo_tool)


if __name__ == '__main__':
    unittest.main()
