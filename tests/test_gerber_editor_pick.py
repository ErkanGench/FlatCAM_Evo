"""Gerber Editor click selection (design note F9): the pick index, the hit rule, the click versus drag rule, the table
sync and the Simplify and Erase clicks. The editor, the Select tool, the Simplify tool and the Eraser tool are the real
classes; the application and the canvas are stand-ins. Everything is headless."""

import os
import statistics
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, Point, Polygon, box

from appEditors import appGerberEditor as module
from appEditors.appGerberEditor import (
    AppGerberEditor, CopyEditorGrb, EraserEditorGrb, ImportEditorGrb, MoveEditorGrb, SelectEditorGrb, SimplifyEditorGrb,
    aperture_rank,
)
from appEditors.grb_plugins.GrbBufferPlugin import BufferEditorTool
from appEditors.grb_plugins.GrbCommon import DrawToolShape, ShapeToolEditorGrb
from appEditors.grb_plugins.GrbTransformationPlugin import queue_transform

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'resources')
GRID = 2.54
CONTROL = QtCore.Qt.KeyboardModifier.ControlModifier
NO_MOD = QtCore.Qt.KeyboardModifier.NoModifier

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeCanvas:
    """Only what the editor asks the canvas for."""

    def __init__(self, pixel=0.05):
        self.pixel = pixel
        self.graph_event_connect = MagicMock()
        self.graph_event_disconnect = MagicMock()

    def pixel_size(self):
        return self.pixel

    @staticmethod
    def translate_coords(pos):
        return pos[0], pos[1]


def snap(x, y):
    return round(x / GRID) * GRID, round(y / GRID) * GRID


def trace(x0, y0, x1, y1, width=0.1, with_follow=True):
    line = LineString([(x0, y0), (x1, y1)])
    geo = {'solid': line.buffer(width / 2, cap_style='flat')}
    if with_follow:
        geo['follow'] = line
    return DrawToolShape(geo)


def pad(cx, cy, radius, with_follow=True):
    geo = {'solid': Point(cx, cy).buffer(radius, 32)}
    if with_follow:
        geo['follow'] = Point(cx, cy)
    return DrawToolShape(geo)


def aperture(shapes, kind='C'):
    return {'type': kind, 'size': 0.1, 'geometry': list(shapes)}


def make_editor(storage=None, pixel=0.05, grid=False):
    app = MagicMock()
    app.options = {'global_mselect_key': 'Control', 'gerber_circle_steps_mode': 'fixed',
                   'gerber_circle_steps': 64}
    app.decimals = 4
    app.app_units = 'MM'
    app.resource_location = ASSETS
    app.selection_type = None
    app.grid_on = grid
    app.grid_status = lambda: app.grid_on
    app.geo_editor.snap = snap
    app.plotcanvas = MagicMock()

    calls = {'row': 0, 'sel': 0}
    original_row = AppGerberEditor.on_row_selected
    original_sel = AppGerberEditor.on_table_selection

    def row_spy(self, row, col):
        calls['row'] += 1
        return original_row(self, row, col)

    def sel_spy(self, *args):
        calls['sel'] += 1
        return original_sel(self)

    with patch.object(AppGerberEditor, 'on_row_selected', row_spy), \
            patch.object(AppGerberEditor, 'on_table_selection', sel_spy), \
            patch('appEditors.appGerberEditor.ShapeCollection', create=True):
        editor = AppGerberEditor(app)

    editor.calls = calls
    editor.canvas = FakeCanvas(pixel)
    editor.plot_all = MagicMock()
    editor.build_ui = MagicMock()
    editor.select_tool = MagicMock()
    set_storage(editor, storage or {})
    return editor


def set_storage(editor, storage):
    editor.storage_dict = storage
    editor.touch_geometry()
    table = editor.ui.apertures_table
    with QtCore.QSignalBlocker(table):
        table.setRowCount(len(storage))
        for row, key in enumerate(storage):
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(key)))


def run_transform(tool, kind, params):
    """The Transformation plugin path of the UI (queue_transform), with the worker job run on the spot."""
    if queue_transform(tool, kind, params) == 'fail':
        return 'fail'
    job = tool.app.worker_task.emit.call_args.args[0]
    job['fcn'](*job['params'])
    QtWidgets.QApplication.processEvents()


def make_select(editor):
    tool = SelectEditorGrb(editor)
    editor.active_tool = tool
    return tool


def event(x, y, button=1, dragging=0):
    return SimpleNamespace(pos=(x, y), button=button, is_dragging=dragging)


def press(editor, x, y):
    editor.on_canvas_click(event(x, y))


def move(editor, x, y):
    editor.on_canvas_move(event(x, y, dragging=1))


def release(editor, x, y):
    editor.on_canvas_click_release(event(x, y))


def click(editor, x, y):
    press(editor, x, y)
    release(editor, x, y)


def modifiers(value):
    return patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=value)


class PickCase(unittest.TestCase):
    def tearDown(self):
        # nothing is kept between the tests
        pass


class TestHitRule(PickCase):
    def test_thin_trace_hit_inside_tolerance(self):
        trc = trace(0, 0, 10, 0)
        ed = make_editor({10: aperture([trc])})
        make_select(ed)
        click(ed, 5, 0.25)          # 0.2 off the edge: 4 px
        self.assertEqual(ed.selected, [trc])
        click(ed, 5, 0.45)          # 0.4 off the edge: 8 px
        self.assertEqual(ed.selected, [])

    def test_overlap_picks_small_pad(self):
        for order in ((10, 11), (11, 10)):
            big, small = pad(0, 0, 1.0), pad(0.1, 0, 0.2)
            ed = make_editor({order[0]: aperture([big]), order[1]: aperture([small])})
            make_select(ed)
            click(ed, 0.1, 0.05)
            self.assertEqual(ed.selected, [small], order)


    def test_tie_is_stable(self):
        for keys in ((10, 11), (11, 10)):
            first, second = pad(0, 0, 1.0), pad(0, 0, 1.0)
            storage = {}
            for key in keys:
                storage[key] = aperture([first if key == 10 else second])
            ed = make_editor(storage)
            make_select(ed)
            click(ed, 0.2, 0.1)
            self.assertEqual(len(ed.selected), 1)
            self.assertIs(ed.selected[0], first, keys)


    def test_zoom_changes_tolerance(self):
        trc = trace(0, 0, 10, 0)
        for pixel, expected in ((0.05, True), (0.2, True), (0.01, False)):
            ed = make_editor({10: aperture([trc])}, pixel=pixel)
            make_select(ed)
            click(ed, 5, 0.25)
            self.assertEqual(ed.selected == [trc], expected, pixel)


class TestIndexFreshness(PickCase):
    def setUp(self):
        self.a = pad(0, 0, 1.0)
        self.b = pad(10, 0, 1.0)
        self.ed = make_editor({10: aperture([self.a, self.b])}, pixel=0.01)
        make_select(self.ed)
        self.assertIsNotNone(self.ed.pick_at((0, 0)))

    def brute(self, point):
        return [shape for shape in sum((v['geometry'] for v in self.ed.storage_dict.values()), [])
                if shape.geo['solid'].intersects(Point(point))]


    def test_tree_fresh_after_delete(self):
        self.ed.delete_shape(self.a)
        self.assertIsNone(self.ed.pick_at((0, 0)))
        self.assertEqual(self.brute((0, 0)), [])
        self.assertIsNotNone(self.ed.pick_at((10, 0)))

        self.ed.selected = [self.b]
        self.ed.delete_selected()
        self.assertIsNone(self.ed.pick_at((10, 0)))


    def test_tree_fresh_after_transform(self):
        tool = SimpleNamespace(draw_app=self.ed, app=self.ed.app)

        def moved(action):
            new_ed = make_editor({10: aperture([pad(0, 0, 1.0)])}, pixel=0.01)
            shape = new_ed.storage_dict[10]['geometry'][0]
            make_select(new_ed)
            new_ed.selected = [shape]
            new_ed.pick_at((0, 0))                  # the tree is built
            tool.draw_app = new_ed
            tool.app = new_ed.app
            old_solid = shape.geo["solid"]
            action(shape)
            self.assertFalse(shape.geo["solid"].equals(old_solid))
            new_point = shape.geo['solid'].representative_point()
            self.assertIs(new_ed.pick_at((new_point.x, new_point.y))[0], shape)
            return new_ed

        actions = {
            'rotate': lambda s: run_transform(tool, 'rotate', [90, (5, 0)]),
            'buffer': lambda s: run_transform(tool, 'buffer', [3, 1]),
        }
        for name, action in actions.items():
            with self.subTest(name):
                new_ed = moved(action)
                self.assertGreater(new_ed.geometry_revision, 0)


class TestModifiers(PickCase):
    def test_ctrl_adds(self):
        a, b = pad(0, 0, 1.0), pad(10, 0, 1.0)
        ed = make_editor({10: aperture([a, b])})
        make_select(ed)
        with modifiers(CONTROL):
            click(ed, 0, 0)
            click(ed, 10, 0)
            self.assertEqual(ed.selected, [a, b])
            click(ed, 0, 0)
            self.assertEqual(ed.selected, [b])
        click(ed, 0, 0)
        self.assertEqual(ed.selected, [a])


class TestOverlapAndCycle(PickCase):
    def test_small_shape_wins_even_when_the_big_center_is_nearer(self):
        # the small pad covers the center of the big pad; the click is nearer to the big center
        big, small = pad(0, 0, 3.0), pad(0.8, 0, 1.0)
        ed = make_editor({10: aperture([big]), 11: aperture([small])})
        make_select(ed)
        click(ed, 0.2, 0)
        self.assertEqual(ed.selected, [small])

    def test_repeated_click_cycles_through_the_shapes(self):
        big, mid, small = pad(0, 0, 3.0), pad(0, 0, 2.0), pad(0, 0, 1.0)
        ed = make_editor({10: aperture([big, mid, small])})
        make_select(ed)
        order = []
        for __ in range(4):
            click(ed, 0.1, 0.1)
            self.assertEqual(len(ed.selected), 1)
            order.append(ed.selected[0])
        # small first (smallest area), then mid, then big, then small again
        self.assertEqual(order, [small, mid, big, small])
        ed.app.inform.emit.assert_called_with(
            'Shape 1 / 3. Click again at the same place to select the next one.')


class TestClickOrDrag(PickCase):
    def setUp(self):
        self.shape = pad(0, 0, 1.0)
        self.ed = make_editor({10: aperture([self.shape])})
        self.tool = make_select(self.ed)
        self.ed.draw_selection_area_handler = MagicMock()
        self.release_spy = MagicMock(side_effect=self.tool.click_release)
        self.tool.click_release = self.release_spy

    def test_three_pixel_move_is_click(self):
        press(self.ed, 0, 0)
        move(self.ed, 0.15, 0)
        self.assertIsNone(self.ed.app.selection_type)
        release(self.ed, 0.15, 0)
        self.assertEqual(self.ed.selected, [self.shape])
        self.assertIsNone(self.ed.app.selection_type)
        self.ed.app.draw_moving_selection_shape.assert_not_called()
        self.ed.draw_selection_area_handler.assert_not_called()

    def test_six_pixel_move_on_empty_canvas_is_area_drag(self):
        # Starting on a shape now moves it; an area selection starts on empty canvas.
        press(self.ed, 2, 0)
        move(self.ed, 2.3, 0)
        release(self.ed, 2.3, 0)
        self.ed.draw_selection_area_handler.assert_called_once()
        self.release_spy.assert_not_called()


class TestBulkSelection(PickCase):
    def setUp(self):
        self.a = DrawToolShape({'solid': box(0, 0, 1, 1)})
        self.b = DrawToolShape({'solid': box(1, 0, 3, 1)})
        self.far = DrawToolShape({'solid': box(10, 0, 11, 1)})
        self.ed = make_editor({11: aperture([self.far]), 10: aperture([self.a, self.b])})
        make_select(self.ed)
        self.ed.plot_selection = MagicMock()

    def test_rectangle_contains_and_intersects(self):
        self.ed.draw_selection_area_handler((-0.5, -0.5), (2, 2), True)
        self.assertEqual(self.ed.selected, [self.a])
        self.ed.selected = []
        self.ed.draw_selection_area_handler((2, 2), (-0.5, -0.5), False)
        self.assertEqual(self.ed.selected, [self.a, self.b])
        self.assertEqual(self.ed.calls, {'row': 0, 'sel': 0})
        self.ed.plot_all.assert_not_called()
        self.assertEqual(float(self.ed.ui.area_entry.get_value()), 3)

    def test_rectangle_preserves_storage_order_and_toggles(self):
        self.ed.draw_selection_area_handler((-1, -1), (12, 2), True)
        self.assertEqual(self.ed.selected, [self.far, self.a, self.b])
        self.ed.selected = [self.b, self.far]
        self.ed.key = 'Control'
        self.ed.draw_selection_area_handler((-0.5, -0.5), (2, 2), False)
        self.assertEqual(self.ed.selected, [self.far, self.a])
        rows = self.ed.ui.apertures_table.selectionModel().selectedRows()
        self.assertEqual(sorted(row.row() for row in rows), [0, 1])


class TestEraserMake(PickCase):
    def eraser(self, ed, cx, cy, size=1.0):
        shape = DrawToolShape({'solid': box(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)})
        ed.selected = [shape]
        tool = EraserEditorGrb(ed)
        tool.origin = (cx, cy)
        tool.destination = (cx, cy)
        ed.active_tool = tool
        return tool

    def test_eraser_make_keeps_follow(self):
        trc = trace(0, 0, 10, 0, 0.4)
        ed = make_editor({10: aperture([trc])})
        self.eraser(ed, 5, 0).make()
        shapes = ed.storage_dict[0]['geometry']
        self.assertEqual(len(shapes), 1)
        follow = shapes[0].geo['follow']
        self.assertIn(follow.geom_type, ('LineString', 'MultiLineString'))
        self.assertAlmostEqual(follow.length, 9.0, places=3)
        self.assertTrue(follow.within(LineString([(0, 0), (10, 0)]).buffer(1e-6)))


class TestEditorOperations(PickCase):


    def test_repeated_buffer_preserves_live_selection_and_unselected_shapes(self):
        selected, other = pad(0, 0, 1), pad(10, 0, 1)
        ed = make_editor({10: aperture([selected, other])})
        ed.selected = [selected]
        ed.sync_aperture_rows({10})
        plugin = SimpleNamespace(app=ed.app, draw_app=ed)
        BufferEditorTool.buffer(plugin, 1, 'round')
        job = ed.app.worker_task.emit.call_args.args[0]
        job['fcn'](*job['params'])
        QtWidgets.QApplication.processEvents()
        first_area = ed.storage_dict[10]['geometry'][0].geo['solid'].area
        BufferEditorTool.buffer(plugin, 1, 'round')
        job = ed.app.worker_task.emit.call_args.args[0]
        job['fcn'](*job['params'])
        QtWidgets.QApplication.processEvents()
        self.assertIn(ed.selected[0], ed.storage_dict[10]['geometry'])
        self.assertGreater(ed.storage_dict[10]['geometry'][0].geo['solid'].area, first_area)
        self.assertIs(ed.storage_dict[10]['geometry'][1], other)
        self.assertAlmostEqual(other.geo['solid'].area, pad(10, 0, 1).geo['solid'].area)

    def test_scale_resolves_aperture_keys_and_scales_each_row_once(self):
        for key in (10, '10'):
            with self.subTest(key=key):
                shape = pad(0, 0, 1)
                ed = make_editor({key: aperture([shape])})
                ed.selected = [shape]
                ed.sync_aperture_rows({key})
                table = ed.ui.apertures_table
                with QtCore.QSignalBlocker(table):
                    table.setItem(0, 2, QtWidgets.QTableWidgetItem('C'))
                    table.selectRow(0)
                ed.ui.scale_factor_entry.set_value(2)
                area = shape.geo['solid'].area
                ed.on_scale()
                job = ed.app.worker_task.emit.call_args.args[0]
                job['fcn'](*job['params'])
                QtWidgets.QApplication.processEvents()
                scaled = ed.storage_dict[key]['geometry'][0]
                self.assertAlmostEqual(scaled.geo['solid'].area, area * 4)
                self.assertIn(ed.selected[0], ed.storage_dict[key]['geometry'])
                ed.app.log.error.assert_not_called()

    def test_total_erasure_replots_even_without_surviving_fragments(self):
        ed = make_editor({10: aperture([pad(0, 0, 0.1)])})
        TestEraserMake().eraser(ed, 0, 0, 2).make()
        self.assertEqual(sum(len(v['geometry']) for v in ed.storage_dict.values()), 0)
        ed.plot_all.assert_called_once()

    def test_import_merges_only_matching_aperture_types(self):
        for existing_type, imported_type in (('R', 'O'), ('O', 'R'), ('R', 'R'), ('O', 'O')):
            with self.subTest(existing=existing_type, imported=imported_type):
                draw_app = MagicMock()
                draw_app.storage_dict = {
                    10: {'type': existing_type, 'size': 2.2, 'width': 2, 'height': 1, 'geometry': []}
                }
                imported = pad(5, 5, 1)
                tool = SimpleNamespace(app=draw_app.app, draw_app=draw_app, sel_storage=[{
                    'type': imported_type, 'size': 2.2, 'width': 2, 'height': 1, 'geometry': [imported]
                }])
                ImportEditorGrb.import_shapes(tool)
                destination = 10 if existing_type == imported_type else 11
                self.assertEqual(draw_app.storage_dict[destination]['type'], imported_type)
                self.assertIn(imported, draw_app.storage_dict[destination]['geometry'])


if __name__ == '__main__':
    unittest.main()
