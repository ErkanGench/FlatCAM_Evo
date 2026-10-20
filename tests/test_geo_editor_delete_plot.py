"""Geometry Editor: shape deletion and full replot."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, Polygon, box

from appEditors.appGeoEditor import AppGeoEditor, DrawToolShape


class FakeCollection:
    """Records clears, plotted shapes and redraws like a ShapeCollection."""

    def __init__(self):
        self.calls = []
        self.data = {}
        self.hidden = set()
        self.last_key = -1

    @property
    def items(self):
        """The shown shapes."""
        return [shape for key, shape in self.data.items() if key not in self.hidden]

    def clear(self, update=False):
        self.calls.append(('clear', update))
        self.data = {}
        self.hidden = set()
        self.last_key = -1

    def _new_key(self, shape):
        self.last_key += 1
        self.data[self.last_key] = shape
        return self.last_key

    def add(self, shape=None, color=None, **kwargs):
        self.calls.append(('add', color))
        return self._new_key(shape)

    def add_copy(self, source, source_key, color=None, face_color=None, linewidth=None):
        if source_key not in source.data:
            return None
        self.calls.append(('copy', color))
        return self._new_key(source.data[source_key])

    def remove(self, key, update=False):
        self.calls.append(('remove', key))
        self.data.pop(key, None)
        self.hidden.discard(key)

    def update_visibility(self, state, indexes=None):
        self.calls.append(('visible', state, len(indexes)))
        if state:
            self.hidden -= set(indexes)
        else:
            self.hidden |= set(indexes)

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
        fcgeometry=SimpleNamespace(drawing_tolerance=0.01), build_ui=Mock(), plot_all=Mock(), plot_changes=Mock())
    editor.get_selected = lambda: editor.selected
    editor.get_draw_color = lambda: AppGeoEditor.get_draw_color(editor)
    editor.color_with_alpha = AppGeoEditor.color_with_alpha
    editor.get_sel_color = lambda: AppGeoEditor.get_sel_color(editor)
    editor.plot_shape = lambda *a, **k: AppGeoEditor.plot_shape(editor, *a, **k)
    editor.delete_shape = lambda s, inserted=(): AppGeoEditor.delete_shape(editor, s, inserted)
    editor.get_render_state = lambda: AppGeoEditor.get_render_state(editor)
    editor.copy_to_selection = lambda entry, color: AppGeoEditor.copy_to_selection(editor, entry, color)
    editor.unplot_entry = lambda entry: AppGeoEditor.unplot_entry(editor, entry)
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


class TestGeoEditorPlotAll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def check(self, editor, shapes_adds, sel_adds):
        AppGeoEditor.plot_all(editor)
        self.assertEqual(editor.shapes.calls[0], ('clear', False))
        self.assertEqual(editor.sel_shapes.calls[0], ('clear', False))
        self.assertEqual(editor.shapes.calls.count(('redraw',)), 1)
        self.assertEqual(editor.sel_shapes.calls.count(('redraw',)), 1)
        self.assertEqual(editor.shapes.calls[-1], ('redraw',))
        self.assertEqual(editor.sel_shapes.calls[-1], ('redraw',))
        self.assertEqual(len(editor.shapes.items), shapes_adds)
        self.assertEqual(len(editor.sel_shapes.items), sel_adds)

    def test_all_selected_clears_drawn_collection(self):
        a, b = line(0), line(1)
        editor = make_editor([a, b], selected=[a, b])
        self.check(editor, 0, 2)

    def test_none_selected_clears_selection_collection(self):
        a, b = line(0), line(1)
        editor = make_editor([a, b])
        self.check(editor, 2, 0)

    def test_empty_storage_clears_both(self):
        editor = make_editor([])
        self.check(editor, 0, 0)

    def test_utility_only_is_plotted(self):
        u = DrawToolShape(box(0, 0, 1, 1))
        editor = make_editor([], utility=[u])
        self.check(editor, 1, 0)

    def test_colors_with_and_without_alpha(self):
        for color in ('#112233', '#11223380'):
            a = line(0)
            editor = make_editor([a], selected=[a])
            editor.app.options['global_draw_color'] = color
            editor.app.options['global_sel_draw_color'] = color
            AppGeoEditor.plot_all(editor)
            self.assertEqual(editor.sel_shapes.calls[1], ('copy', '#112233FF'))


def selection_editor(shapes, selected=()):
    editor = make_editor(shapes, selected=selected)
    editor.plot_all = lambda: AppGeoEditor.plot_all(editor)
    editor.plot_changes = lambda: AppGeoEditor.plot_changes(editor)
    editor.plot_all()
    editor.shapes.calls.clear()
    editor.sel_shapes.calls.clear()
    return editor


class TestGeoEditorPlotSelection(unittest.TestCase):
    """plot_changes() changes only the shapes whose selection changed, without a new triangulation."""

    def test_select_hides_and_copies_only_the_changed_shape(self):
        a, b, c = line(0), line(1), line(2)
        editor = selection_editor([a, b, c])
        editor.selected = [b]
        editor.plot_changes()
        self.assertEqual(editor.shapes.calls, [('visible', False, 1), ('redraw',)])
        self.assertEqual(editor.sel_shapes.calls, [('copy', '#AABBCCFF'), ('redraw',)])
        self.assertEqual(editor.shapes.items, [a.geo, c.geo])
        self.assertEqual(editor.sel_shapes.items, [b.geo])

    def test_deselect_shows_the_shape_again(self):
        a, b = line(0), line(1)
        editor = selection_editor([a, b], selected=[a, b])
        editor.selected = [b]
        editor.plot_changes()
        self.assertEqual(editor.shapes.items, [a.geo])
        self.assertEqual(editor.sel_shapes.items, [b.geo])
        self.assertEqual(editor.shapes.calls, [('visible', True, 1), ('redraw',)])
        self.assertEqual([call[0] for call in editor.sel_shapes.calls], ['remove', 'redraw'])

    def test_many_changes_are_1_visibility_pass_each(self):
        shapes = [line(x) for x in range(6)]
        editor = selection_editor(shapes, selected=shapes[:3])
        editor.selected = shapes[3:]
        editor.plot_changes()
        self.assertEqual(editor.shapes.calls, [('visible', False, 3), ('visible', True, 3), ('redraw',)])
        self.assertEqual([s for s in editor.shapes.items], [s.geo for s in shapes[:3]])
        self.assertNotIn('add', [call[0] for call in editor.sel_shapes.calls])

    def test_copy_not_possible_triangulates(self):
        a, b = line(0), line(1)
        editor = selection_editor([a, b])
        editor.sel_shapes.add_copy = lambda *args, **kwargs: None
        editor.selected = [b]
        editor.plot_changes()
        self.assertEqual(editor.sel_shapes.calls, [('add', '#AABBCCFF'), ('redraw',)])
        self.assertEqual(editor.sel_shapes.items, [b.geo])

    def test_same_selection_draws_nothing(self):
        a, b = line(0), line(1)
        editor = selection_editor([a, b], selected=[a])
        editor.plot_changes()
        self.assertEqual(editor.shapes.calls, [])
        self.assertEqual(editor.sel_shapes.calls, [])

    def test_new_shape_is_the_only_one_triangulated(self):
        a, b, c = line(0), line(1), line(2)
        editor = selection_editor([a, b])
        editor.storage.insert(c)
        editor.selected = [c]
        editor.plot_changes()
        self.assertNotIn(('clear', False), editor.shapes.calls)
        self.assertEqual([call for call in editor.shapes.calls if call[0] == 'add'], [('add', '#112233FF')])
        self.assertEqual(editor.shapes.items, [a.geo, b.geo])
        self.assertEqual(editor.sel_shapes.items, [c.geo])

    def test_changed_geometry_is_plotted_again(self):
        a, b = line(0), line(1)
        editor = selection_editor([a, b], selected=[a])
        a.geo = LineString([(5, 5), (6, 6)])
        editor.plot_changes()
        self.assertNotIn(('clear', False), editor.shapes.calls)
        self.assertEqual(editor.shapes.items, [b.geo])
        self.assertEqual(editor.sel_shapes.items, [a.geo])
        self.assertEqual(len(editor.shapes.data), 2)

    def test_removed_shapes_leave_the_canvas(self):
        a, b, c = line(0), line(1), line(2)
        editor = selection_editor([a, b, c], selected=[b, c])
        AppGeoEditor.delete_shape(editor, [b, c])
        editor.plot_changes()
        self.assertNotIn(('clear', False), editor.shapes.calls)
        self.assertEqual(editor.shapes.items, [a.geo])
        self.assertEqual(editor.sel_shapes.items, [])
        self.assertEqual(len(editor.shapes.data), 1)

    def test_changed_utility_plots_all(self):
        a = line(0)
        editor = selection_editor([a])
        editor.utility.append(line(5))
        editor.plot_changes()
        self.assertEqual(editor.shapes.calls[0], ('clear', False))

    def test_collection_cleared_elsewhere_plots_all(self):
        a, b = line(0), line(1)
        editor = selection_editor([a, b], selected=[a])
        editor.sel_shapes.clear()
        editor.selected = [a, b]
        editor.plot_changes()
        self.assertEqual(editor.shapes.calls[0], ('clear', False))
        self.assertEqual(editor.sel_shapes.items, [a.geo, b.geo])

    def test_invalid_shape_is_never_drawn(self):
        a = line(0)
        bow_tie = DrawToolShape(Polygon([(0, 0), (1, 1), (1, 0), (0, 1)]))
        editor = selection_editor([a, bow_tie])
        editor.selected = [bow_tie]
        editor.plot_changes()
        self.assertEqual(editor.sel_shapes.items, [])
        self.assertEqual(editor.shapes.calls, [])


def tree_editor(shapes):
    """An editor with a real tree, rows like build_ui() makes them: column 0 is str(id(shape))."""
    editor = selection_editor(shapes)
    editor.ui = Mock()
    tw = QtWidgets.QTreeWidget()
    tw.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
    parent = QtWidgets.QTreeWidgetItem(tw, ['Geometry'])
    for shp in shapes:
        QtWidgets.QTreeWidgetItem(parent, [str(id(shp))])
    editor.ui.tw = tw
    editor.tree_handler_runs = 0

    def on_tree_selection():
        editor.tree_handler_runs += 1
        AppGeoEditor.on_tree_selection(editor)

    editor.on_tree_selection = on_tree_selection
    editor.active_tool = None
    tw.itemSelectionChanged.connect(editor.on_tree_selection)
    editor.shapes_by_tree_id = lambda: AppGeoEditor.shapes_by_tree_id(editor)
    editor.sync_tree_selection = lambda: AppGeoEditor.sync_tree_selection(editor)
    editor.update_all_vertex_count = lambda: AppGeoEditor.update_all_vertex_count(editor)
    editor.app.delete_selection_shape = Mock()
    editor.app.options['global_mselect_key'] = 'Control'
    return editor


def tree_selected(editor):
    return sorted(item.text(0) for item in editor.ui.tw.selectedItems())


class TestGeoEditorSelectionTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_sync_selects_the_rows_without_the_tree_handler(self):
        shapes = [line(x) for x in range(5)]
        editor = tree_editor(shapes)
        editor.selected = [shapes[1], shapes[3]]
        editor.sync_tree_selection()
        self.assertEqual(tree_selected(editor), sorted([str(id(shapes[1])), str(id(shapes[3]))]))
        self.assertEqual(editor.tree_handler_runs, 0)
        editor.selected = []
        editor.sync_tree_selection()
        self.assertEqual(tree_selected(editor), [])

    def test_area_selection_plots_once(self):
        shapes = [line(x) for x in range(10)]
        editor = tree_editor(shapes)
        AppGeoEditor.draw_selection_area_handler(editor, (-0.5, -0.5), (3.5, 2), True)
        self.assertEqual(editor.selected, shapes[:4])
        self.assertEqual(tree_selected(editor), sorted(str(id(s)) for s in shapes[:4]))
        self.assertEqual(editor.tree_handler_runs, 0)
        self.assertEqual(editor.sel_shapes.calls.count(('redraw',)), 1)
        self.assertNotIn(('clear', False), editor.shapes.calls)
        editor.ui.geo_all_vertex_entry.set_value.assert_called_with('8')
        editor.ui.geo_vertex_entry.set_value.assert_called_with(8)

    def test_area_selection_touch_type(self):
        shapes = [line(x) for x in range(10)]
        editor = tree_editor(shapes)
        # only touches the shapes 2 and 3
        AppGeoEditor.draw_selection_area_handler(editor, (3.5, 0.5), (1.5, 2), False)
        self.assertEqual(editor.selected, shapes[2:4])

    def test_area_selection_with_the_key_toggles(self):
        shapes = [line(x) for x in range(6)]
        editor = tree_editor(shapes)
        editor.selected = [shapes[0], shapes[1]]
        with unittest.mock.patch.object(QtWidgets.QApplication, 'keyboardModifiers',
                                        return_value=QtCore.Qt.KeyboardModifier.ControlModifier):
            AppGeoEditor.draw_selection_area_handler(editor, (0.5, -0.5), (2.5, 2), True)
        self.assertEqual(editor.selected, [shapes[0], shapes[2]])

    def test_polygon_vertex_count(self):
        square = DrawToolShape(box(0, 0, 1, 1).difference(box(0.25, 0.25, 0.75, 0.75)))
        editor = tree_editor([square, line(5)])
        editor.selected = [square, editor.storage.objects[1]]
        AppGeoEditor.update_all_vertex_count(editor)
        editor.ui.geo_all_vertex_entry.set_value.assert_called_with('12')



def pick_editor(shapes):
    """A tree editor with the click selection: 1 screen pixel is 0.01 plot units, so the pick tolerance is 0.05."""
    editor = tree_editor(shapes)
    editor.canvas = SimpleNamespace(pixel_size=lambda: 0.01)
    editor.interdict_selection = False
    editor.update_ui = Mock()
    editor.app.inform = Mock()
    editor.get_pick_index = lambda: AppGeoEditor.get_pick_index(editor)
    editor.pick_at = lambda point: AppGeoEditor.pick_at(editor, point)
    editor.click_select = lambda point: AppGeoEditor.click_select(editor, point)
    return editor


CONTROL = QtCore.Qt.KeyboardModifier.ControlModifier


class TestGeoEditorClickSelect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_click_on_a_line_selects_it_and_the_row(self):
        shapes = [line(x) for x in range(4)]
        editor = pick_editor(shapes)
        # the middle of the line: far from its vertices, on the line
        self.assertTrue(editor.click_select((1.02, 0.5)))
        self.assertEqual(editor.selected, [shapes[1]])
        self.assertEqual(tree_selected(editor), [str(id(shapes[1]))])
        self.assertEqual(editor.tree_handler_runs, 0)

    def test_click_on_nothing_clears_the_selection(self):
        shapes = [line(x) for x in range(4)]
        editor = pick_editor(shapes)
        editor.click_select((1.0, 0.5))
        editor.click_select((1.5, 0.5))
        self.assertEqual(editor.selected, [])
        self.assertEqual(tree_selected(editor), [])

    def test_click_without_the_key_replaces_the_selection(self):
        shapes = [line(x) for x in range(4)]
        editor = pick_editor(shapes)
        editor.click_select((1.0, 0.5))
        editor.click_select((2.0, 0.5))
        self.assertEqual(editor.selected, [shapes[2]])

    def test_click_with_the_key_adds_and_removes(self):
        shapes = [line(x) for x in range(4)]
        editor = pick_editor(shapes)
        with unittest.mock.patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=CONTROL):
            editor.click_select((1.0, 0.5))
            editor.click_select((3.0, 0.5))
            self.assertEqual(editor.selected, [shapes[1], shapes[3]])
            editor.click_select((1.0, 0.5))
            self.assertEqual(editor.selected, [shapes[3]])

    def test_click_inside_of_nested_polygons_picks_the_smaller(self):
        big = DrawToolShape(box(0, 0, 10, 10))
        small = DrawToolShape(box(4, 4, 6, 6))
        editor = pick_editor([big, small])
        editor.click_select((5, 5))
        self.assertEqual(editor.selected, [small])
        editor.click_select((1, 1))
        self.assertEqual(editor.selected, [big])

    def test_pick_index_is_made_again_after_a_change(self):
        a, b = line(0), line(1)
        editor = pick_editor([a, b])
        tree, __ = editor.get_pick_index()
        self.assertIs(editor.get_pick_index()[0], tree)
        b.geo = LineString([(5, 0), (5, 1)])
        self.assertIsNot(editor.get_pick_index()[0], tree)
        self.assertIs(editor.pick_at((5.01, 0.5)), b)

    def test_no_selection_while_interdicted(self):
        a = line(0)
        editor = pick_editor([a])
        editor.interdict_selection = True
        self.assertFalse(editor.click_select((0, 0.5)))
        self.assertEqual(editor.selected, [])


class TestGeoEditorBuildUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_rows_are_made_again_and_keep_the_selection(self):
        from types import MethodType
        from appGUI.GUIElements import FCTree
        shapes = [line(x) for x in range(5)]
        for shp in shapes:
            shp.data = {'type': 'Line'}
        editor = tree_editor(shapes)
        tw = editor.ui.tw
        tw.addParentEditable = MethodType(FCTree.addParentEditable, tw)
        tw.resize_sig = Mock()
        editor.ui.geo_parent = tw.topLevelItem(0)
        editor.ui.geo_font = None
        editor.selected = [shapes[1], shapes[2]]
        editor.sync_tree_selection()

        AppGeoEditor.delete_shape(editor, [shapes[2]])
        AppGeoEditor.build_ui(editor)
        self.assertEqual(editor.ui.geo_parent.childCount(), 4)
        self.assertEqual(tree_selected(editor), [str(id(shapes[1]))])
        self.assertEqual(editor.tree_handler_runs, 0)


class TestGeoEditorSimplify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def simplify_tool(self, editor):
        from appEditors.appGeoEditor import FCSimplification
        tool = FCSimplification.__new__(FCSimplification)
        tool.draw_app = editor
        tool.simp_tool = Mock()
        return tool

    def test_click_selects_1_time_and_a_click_on_nothing_deselects(self):
        shapes = [line(x) for x in range(4)]
        editor = pick_editor(shapes)
        tool = self.simplify_tool(editor)
        tool.click((1.0, 0.5))
        tool.click((1.0, 0.5))
        self.assertEqual(editor.selected, [shapes[1]])
        self.assertEqual(editor.sel_shapes.items, [shapes[1].geo])
        tool.simp_tool.calculate_coordinates_vertex.assert_called_with([shapes[1].geo])
        tool.click((1.5, 0.5))
        self.assertEqual(editor.selected, [])
        self.assertEqual(editor.sel_shapes.items, [])
        tool.simp_tool.calculate_coordinates_vertex.assert_called_with([])

    def test_area_selection_updates_the_tool(self):
        shapes = [line(x) for x in range(4)]
        editor = pick_editor(shapes)
        editor.active_tool = self.simplify_tool(editor)
        AppGeoEditor.draw_selection_area_handler(editor, (-0.5, -0.5), (1.5, 2), True)
        editor.active_tool.simp_tool.calculate_coordinates_vertex.assert_called_with([shapes[0].geo, shapes[1].geo])

    def test_simplify_replaces_only_the_selected_shapes(self):
        from appEditors.geo_plugins.GeoSimplificationPlugin import SimplificationTool
        from shapely.geometry import Point
        circle = DrawToolShape(Point(5, 5).buffer(2, quad_segs=32))
        others = [line(x) for x in range(3)]
        editor = selection_editor(others + [circle], selected=[circle])
        editor.interdict_selection = False
        editor._collect_shape = lambda shape, to_insert: AppGeoEditor._collect_shape(editor, shape, to_insert)
        editor.build_ui_sig = Mock()
        jobs = []
        editor.app.worker_task = SimpleNamespace(emit=jobs.append)
        editor.app.proc_container = unittest.mock.MagicMock()
        editor.app.inform = Mock()
        tool = SimpleNamespace(app=editor.app, geo_editor=editor, update_ui=Mock(),
                               ui=SimpleNamespace(geo_tol_entry=SimpleNamespace(get_value=lambda: 0.1)))
        tool.calculate_coordinates_vertex = lambda geos: SimplificationTool.calculate_coordinates_vertex(tool, geos)

        SimplificationTool.on_simplification_click(tool)
        jobs[0]['fcn'](*jobs[0]['params'])

        objects = list(editor.storage.get_objects())
        self.assertEqual(len(objects), 4)
        self.assertEqual(objects[:3], others)
        new = objects[3]
        self.assertIsNot(new, circle)
        self.assertLess(len(new.geo.exterior.coords), len(circle.geo.exterior.coords))
        self.assertEqual(editor.selected, [new])
        self.assertNotIn(('clear', False), editor.shapes.calls)
        self.assertEqual(editor.sel_shapes.items, [new.geo])
        self.assertFalse(editor.interdict_selection)
        editor.build_ui_sig.emit.assert_called_once()
        # 1 text update with the coordinates of all the simplified shapes
        tool.update_ui.emit.assert_called_once()

    def test_coordinates_text_is_sent_1_time(self):
        from appEditors.geo_plugins.GeoSimplificationPlugin import SimplificationTool
        tool = SimpleNamespace(update_ui=Mock())
        SimplificationTool.calculate_coordinates_vertex(tool, [line(x).geo for x in range(5)])
        tool.update_ui.emit.assert_called_once()
        self.assertEqual(tool.update_ui.emit.call_args[0][1], 10)


if __name__ == '__main__':
    unittest.main()
