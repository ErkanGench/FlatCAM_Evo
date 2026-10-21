"""Editors: the Move (and the Gerber Copy) translate the selection in 1 batch and plot 1 time."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from shapely.geometry import LineString, Point, box

from appEditors.appGeoEditor import AppGeoEditor, FCMove, DrawToolShape as GeoShape
from appEditors.appExcEditor import MoveEditorExc
from appEditors.appGerberEditor import MoveEditorGrb, CopyEditorGrb
from appEditors.grb_plugins.GrbCommon import DrawToolShape as GrbShape


def counting_app():
    return SimpleNamespace(inform=Mock(), jump_signal=Mock(), proc_container=MagicMock())


def grb_tool(cls, storage_dict, selected, apertures, dx=2.0, dy=-1.0):
    tool = cls.__new__(cls)
    tool.origin = (0.0, 0.0)
    tool.destination = (dx, dy)
    tool.selected_apertures = apertures
    tool.draw_app = SimpleNamespace(
        storage_dict=storage_dict, selected=selected, get_selected=lambda: selected,
        touch_geometry=Mock(), delete_utility_geometry=Mock(), tool_shape=Mock(), plot_all=Mock(),
        build_ui=Mock(), app=counting_app())
    return tool


class TestGerberEditorMove(unittest.TestCase):

    def setUp(self):
        self.pad = GrbShape({'solid': box(0, 0, 1, 1), 'follow': Point(0.5, 0.5)})
        self.track = GrbShape({'solid': LineString([(0, 0), (3, 0)]).buffer(0.1),
                               'follow': LineString([(0, 0), (3, 0)]), 'clear': box(1, -0.05, 1.1, 0.05)})
        self.other = GrbShape({'solid': box(5, 5, 6, 6)})
        self.storage = {'10': {'geometry': [self.pad, self.other]}, '11': {'geometry': [self.track]}}

    def test_move_translates_every_key_and_removes_the_source(self):
        selected = [self.pad, self.track]
        tool = grb_tool(MoveEditorGrb, self.storage, selected, ['10', '11'])
        tool.make()

        ap10 = self.storage['10']['geometry']
        self.assertIs(ap10[0], self.other)
        self.assertEqual(ap10[1].geo['solid'].bounds, (2.0, -1.0, 3.0, 0.0))
        self.assertEqual(ap10[1].geo['follow'].coords[0], (2.5, -0.5))
        ap11 = self.storage['11']['geometry']
        self.assertEqual(len(ap11), 1)
        self.assertEqual(set(ap11[0].geo), {'solid', 'follow', 'clear'})
        self.assertEqual(ap11[0].geo['clear'].bounds, (3.0, -1.05, 3.1, -0.95))
        self.assertEqual(selected, [])
        tool.draw_app.plot_all.assert_called_once()
        tool.draw_app.touch_geometry.assert_called_once()

    def test_storage_list_object_is_kept(self):
        ap10 = self.storage['10']['geometry']
        grb_tool(MoveEditorGrb, self.storage, [self.pad], ['10']).make()
        self.assertIs(self.storage['10']['geometry'], ap10)

    def test_copy_keeps_the_source(self):
        selected = [self.pad]
        tool = grb_tool(CopyEditorGrb, self.storage, selected, ['10'])
        tool.make()
        ap10 = self.storage['10']['geometry']
        self.assertEqual(len(ap10), 3)
        self.assertIs(ap10[0], self.pad)
        self.assertEqual(ap10[2].geo['solid'].bounds, (2.0, -1.0, 3.0, 0.0))
        tool.draw_app.plot_all.assert_called_once()

    def test_zero_move_changes_nothing(self):
        selected = [self.pad]
        tool = grb_tool(MoveEditorGrb, self.storage, selected, ['10'], dx=0.0, dy=0.0)
        tool.make()
        self.assertEqual(self.storage['10']['geometry'], [self.pad, self.other])
        tool.draw_app.touch_geometry.assert_not_called()
        tool.draw_app.plot_all.assert_called_once()

    def test_utility_geometry_is_translated(self):
        selected = [self.pad, self.track]
        tool = grb_tool(MoveEditorGrb, self.storage, selected, ['10', '11'])
        tool.sel_limit = 10
        util = tool.utility_geometry(data=(1.0, 1.0))
        self.assertEqual(util.geo[0]['solid'].bounds, (1.0, 1.0, 2.0, 2.0))
        self.assertEqual(self.pad.geo['solid'].bounds, (0.0, 0.0, 1.0, 1.0))


class TestExcellonEditorMove(unittest.TestCase):

    def test_move_translates_and_replots_once(self):
        drill = GeoShape(Point(1, 1).buffer(0.2))
        slot = GeoShape(LineString([(0, 0), (2, 0)]).buffer(0.3))
        other = GeoShape(Point(9, 9).buffer(0.2))
        storage_1, storage_2 = AppGeoEditor.make_storage(), AppGeoEditor.make_storage()
        for shp in (drill, other):
            storage_1.insert(shp)
        storage_2.insert(slot)
        selected = [drill, slot]

        tool = MoveEditorExc.__new__(MoveEditorExc)
        tool.origin, tool.destination = (0.0, 0.0), (1.0, 2.0)
        tool.selected_dia_list = [0.4, 0.6]
        tool.draw_app = SimpleNamespace(
            storage_dict={0.4: storage_1, 0.6: storage_2}, selected=selected, get_selected=lambda: selected,
            add_exc_shape=lambda shp, storage: storage.insert(shp), delete_utility_geometry=Mock(),
            tool_shape=Mock(), replot=Mock(), build_ui=Mock(), app=counting_app())
        tool.make()

        objs_1 = list(storage_1.get_objects())
        self.assertEqual(len(objs_1), 2)
        self.assertIn(other, objs_1)
        moved = [shp for shp in objs_1 if shp is not other][0]
        self.assertAlmostEqual(moved.geo.centroid.x, 2.0)
        self.assertAlmostEqual(moved.geo.centroid.y, 3.0)
        self.assertAlmostEqual(list(storage_2.get_objects())[0].geo.centroid.x, 2.0)
        self.assertEqual(selected, [])
        tool.draw_app.replot.assert_called_once()


class TestGeometryEditorMove(unittest.TestCase):

    def test_move_prepares_without_mutation_then_commits_once(self):
        a, b, c = GeoShape(box(0, 0, 1, 1)), GeoShape(LineString([(0, 0), (1, 1)])), GeoShape(box(5, 5, 6, 6))
        storage = AppGeoEditor.make_storage()
        for shp in (a, b, c):
            storage.insert(shp)
        editor = SimpleNamespace(storage=storage, selected=[a, b], utility=[b], plot_all=Mock(), build_ui=Mock(),
                                 sel_shapes=Mock(), app=counting_app())
        editor.get_selected = lambda: editor.selected
        editor.delete_shape = lambda shapes: AppGeoEditor.delete_shape(editor, shapes)

        tool = FCMove.__new__(FCMove)
        tool.draw_app = editor
        tool.origin, tool.destination = (0.0, 0.0), (3.0, 0.0)
        tool.draw_cursor_data = Mock()
        tool.make()

        self.assertEqual([shp.geo.bounds for shp in tool.geometry], [(3.0, 0.0, 4.0, 1.0), (3.0, 0.0, 4.0, 1.0)])
        self.assertEqual(list(storage.get_objects()), [a, b, c])
        self.assertEqual(editor.selected, [a, b])
        self.assertEqual(editor.utility, [b])
        editor.plot_all.assert_not_called()      # on_shape_complete() plots after the new shapes are added
        self.assertTrue(tool.complete)
        editor.active_tool = tool
        editor.app.options = {'geometry_editor_milling_type': 'cv'}
        editor.app.defaults = SimpleNamespace(get=lambda k, d=None: d, factory_defaults={})
        editor.app.log = Mock()
        editor.build_ui_sig = Mock()
        editor.tool_shape = Mock()
        editor.plot_changes = Mock()
        editor._collect_shape = lambda shp, acc: AppGeoEditor._collect_shape(editor, shp, acc)
        editor.delete_utility_geometry = lambda: AppGeoEditor.delete_utility_geometry(editor)
        AppGeoEditor.on_shape_complete(editor)
        self.assertEqual(set(storage.get_objects()), {c, *tool.geometry})
        self.assertEqual(editor.selected, tool.geometry)
        self.assertEqual(editor.utility, [])
        editor.plot_changes.assert_called_once()
        self.assertTrue(AppGeoEditor.undo(editor))
        self.assertEqual(set(storage.get_objects()), {a, b, c})
        self.assertEqual(editor.selected, [a, b])


class TestClimbMillingDirection(unittest.TestCase):
    """With the 'cl' milling type only a new drawn shape is reversed; a moved shape keeps its direction."""

    def complete(self, tool_cls):
        line = LineString([(0, 0), (1, 0), (2, 1)])
        tool = tool_cls.__new__(tool_cls)
        tool.geometry = [GeoShape(line)]
        app = SimpleNamespace(options={'geometry_editor_milling_type': 'cl'}, log=Mock(),
                              defaults=SimpleNamespace(get=lambda k, d=None: d, factory_defaults={}))
        editor = SimpleNamespace(app=app, active_tool=tool, add_shape=Mock(), delete_utility_geometry=Mock(),
                                 tool_shape=Mock(), plot_changes=Mock(), selected=[])
        AppGeoEditor.on_shape_complete(editor)
        return list(editor.add_shape.call_args[0][0][0].geo.coords)

    def test_drawn_shape_is_reversed(self):
        from appEditors.appGeoEditor import FCPath
        self.assertEqual(self.complete(FCPath), [(2, 1), (1, 0), (0, 0)])

    def test_moved_copied_and_exploded_shapes_keep_the_direction(self):
        from appEditors.appGeoEditor import FCCopy, FCExplode
        for tool_cls in (FCMove, FCCopy, FCExplode):
            self.assertEqual(self.complete(tool_cls), [(0, 0), (1, 0), (2, 1)], tool_cls.__name__)


class TestStorageReplace(unittest.TestCase):

    def make_storage(self, n):
        storage = AppGeoEditor.make_storage()
        shapes = [GeoShape(box(i, 0, i + 0.5, 0.5)) for i in range(n)]
        for shp in shapes:
            storage.insert(shp)
        return storage, shapes

    def check_index(self, storage, expected):
        self.assertEqual(set(map(id, storage.get_objects())), set(map(id, expected)))
        for shp in expected:
            x, y = shp.geo.exterior.coords[0]
            __, found = storage.nearest((x, y))
            self.assertIs(found, shp)

    def test_few_changes_use_the_incremental_path(self):
        storage, shapes = self.make_storage(400)
        new = GeoShape(box(1000, 0, 1001, 1))
        storage.replace(removed=[shapes[3]], inserted=[new])
        self.assertIs(storage.objects[3], None)       # incremental: the slot is only cleared
        self.check_index(storage, shapes[:3] + shapes[4:] + [new])

    def test_many_changes_rebuild_the_index(self):
        storage, shapes = self.make_storage(50)
        new = [GeoShape(box(i + 0.25, 5, i + 0.75, 6)) for i in range(30)]
        storage.replace(removed=shapes[:30], inserted=new)
        self.assertNotIn(None, storage.objects)       # rebuilt: the list is compacted
        self.check_index(storage, shapes[30:] + new)
        # the rebuilt storage still removes and inserts 1 object
        storage.remove(new[0])
        storage.insert(shapes[0])
        self.check_index(storage, shapes[30:] + new[1:] + [shapes[0]])

    def test_remove_everything(self):
        storage, shapes = self.make_storage(5)
        storage.replace(removed=shapes)
        self.assertEqual(list(storage.get_objects()), [])
        with self.assertRaises(StopIteration):
            storage.nearest((0, 0))

    def test_geo_add_shape_inserts_in_1_batch_and_builds_the_ui_once(self):
        storage = AppGeoEditor.make_storage()
        editor = SimpleNamespace(storage=storage, utility=[], selected=[], build_ui_sig=Mock(), app=counting_app())
        editor._collect_shape = lambda shp, acc: AppGeoEditor._collect_shape(editor, shp, acc)
        shapes = [GeoShape(box(i, 0, i + 0.5, 0.5)) for i in range(10)] + [GeoShape(Point(0, 0))]
        AppGeoEditor.add_shape(editor, shapes)
        self.assertEqual(len(list(storage.get_objects())), 10)     # the Point is not stored, as before
        editor.build_ui_sig.emit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
