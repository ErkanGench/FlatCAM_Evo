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
    app.options = {'global_mselect_key': 'Control', 'gerber_circle_steps': 16}
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

    def test_overlap_without_follow_picks_small_area(self):
        for order in ((10, 11), (11, 10)):
            big, small = pad(0, 0, 1.0, False), pad(0.1, 0, 0.2, False)
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

    def test_chunk_border_independent(self):
        results = []
        for first_index in (76, 10):
            shapes = [pad(i * 5.0, 100.0, 0.5) for i in range(200)]
            big, small = pad(1000, 0, 1.0), pad(1000.1, 0, 0.3)
            shapes[first_index], shapes[first_index + 1] = big, small
            ed = make_editor({10: aperture(shapes)})
            make_select(ed)
            click(ed, 1000.1, 0.05)
            self.assertEqual(len(ed.selected), 1)
            results.append(ed.selected[0] is small)
        self.assertEqual(results, [True, True])

    def test_follow_missing_sorts_last(self):
        # same area: the 'follow' distance decides, and a missing 'follow' sorts last
        with_follow = pad(0, 0, 1.0, True)
        without = pad(0, 0, 1.0, False)
        ed = make_editor({10: aperture([without]), 11: aperture([with_follow])})
        make_select(ed)
        click(ed, 0.1, 0.1)
        self.assertEqual(ed.selected, [with_follow])

        big, small = pad(0, 0, 1.0, False), pad(0, 0, 0.5, False)
        ed = make_editor({10: aperture([big]), 11: aperture([small])})
        make_select(ed)
        click(ed, 0.1, 0.1)
        self.assertEqual(ed.selected, [small])

    def test_aperture_rank_mixed_keys(self):
        keys = ['X1', '10', 10, 9, 0]
        self.assertEqual(sorted(keys, key=aperture_rank), [0, 9, '10', 10, 'X1'])
        self.assertEqual(aperture_rank('10'), aperture_rank(10))
        shapes = {key: pad(i * 10.0, 0, 1.0) for i, key in enumerate([0, 9, 10, 'X1'])}
        storage = {key: aperture([shape]) for key, shape in shapes.items()}
        storage['10'] = aperture([pad(100, 0, 1.0)])
        ed = make_editor(storage)
        make_select(ed)
        tree, refs = ed.get_pick_index()
        self.assertEqual([ref[0] for ref in refs][:2], [0, 9])
        self.assertEqual([ref[0] for ref in refs][-1], 'X1')
        click(ed, 100, 0)
        self.assertEqual(len(ed.selected), 1)

    def test_zoom_changes_tolerance(self):
        trc = trace(0, 0, 10, 0)
        for pixel, expected in ((0.05, True), (0.2, True), (0.01, False)):
            ed = make_editor({10: aperture([trc])}, pixel=pixel)
            make_select(ed)
            click(ed, 5, 0.25)
            self.assertEqual(ed.selected == [trc], expected, pixel)

    def test_zoom_after_the_first_pick_is_not_cached(self):
        trc = trace(0, 0, 10, 0)
        ed = make_editor({10: aperture([trc])}, pixel=0.05)
        make_select(ed)
        self.assertIsNotNone(ed.pick_at((5, 0.25)))
        ed.canvas.pixel = 0.01
        self.assertIsNone(ed.pick_at((5, 0.25)))


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

    def test_tree_fresh_after_add(self):
        new = pad(20, 0, 1.0)
        self.ed.on_grb_shape_complete(self.ed.storage_dict[10]['geometry'], specific_shape=new)
        hit = self.ed.pick_at((20, 0))
        self.assertIs(hit[0], new)
        self.assertEqual(self.brute((20, 0)), [new])

    def test_tree_fresh_after_delete(self):
        self.ed.delete_shape(self.a)
        self.assertIsNone(self.ed.pick_at((0, 0)))
        self.assertEqual(self.brute((0, 0)), [])
        self.assertIsNotNone(self.ed.pick_at((10, 0)))

        self.ed.selected = [self.b]
        self.ed.delete_selected()
        self.assertIsNone(self.ed.pick_at((10, 0)))

    def test_tree_fresh_after_eraser_storage_pop(self):
        eraser = DrawToolShape({'solid': box(-2, -2, 2, 2), 'follow': Point(0, 0)})
        self.ed.selected = [eraser]
        tool = EraserEditorGrb(self.ed)
        tool.origin = (0, 0)
        tool.destination = (0, 0)
        self.ed.active_tool = tool
        self.ed.storage_dict[11] = aperture([pad(0.5, 0.5, 0.2)])
        self.ed.touch_geometry()
        self.assertIsNotNone(self.ed.pick_at((0.5, 0.5)))
        tool.make()
        self.assertNotIn(11, self.ed.storage_dict)
        self.assertIsNone(self.ed.pick_at((0.5, 0.5)))

    def test_tree_fresh_after_move(self):
        self.ed.selected = [self.a]
        self.ed.sync_aperture_rows({10})
        tool = MoveEditorGrb(self.ed)
        self.ed.active_tool = tool
        tool.origin = (0, 0)
        tool.destination = (50, 0)
        tool.make()
        self.assertIsNotNone(self.ed.pick_at((50, 0)))
        self.assertIsNone(self.ed.pick_at((0, 0)))

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
            'flip': lambda s: run_transform(tool, 'flip', ['Y', (5, 0)]),
            'skew': lambda s: run_transform(tool, 'skew', ['X', 30, 0, (0, 5)]),
            'scale': lambda s: run_transform(tool, 'scale', ['X', 6, 1, (0, 0)]),
            'offset': lambda s: run_transform(tool, 'offset', ['X', 30]),
            'buffer': lambda s: run_transform(tool, 'buffer', [3, 1]),
        }
        for name, action in actions.items():
            with self.subTest(name):
                new_ed = moved(action)
                self.assertGreater(new_ed.geometry_revision, 0)

    def test_tree_fresh_after_plugin_edit(self):
        # the buffer plugin
        ed = make_editor({10: aperture([trace(0, 0, 10, 0)])}, pixel=0.01)
        make_select(ed)
        trc = ed.storage_dict[10]['geometry'][0]
        ed.selected = [trc]
        ed.sync_aperture_rows({10})
        self.assertIsNone(ed.pick_at((5, 0.5)))
        plugin = SimpleNamespace(app=ed.app, draw_app=ed)
        BufferEditorTool.buffer(plugin, 1.0, 1)
        self.assertIsNotNone(ed.pick_at((5, 0.5)))

        # the scale of the selected apertures (the table holds the aperture code as text)
        ed = make_editor({'10': aperture([pad(0, 0, 1.0)])}, pixel=0.01)
        make_select(ed)
        shape = ed.storage_dict['10']['geometry'][0]
        ed.selected = [shape]
        ed.sync_aperture_rows({'10'})
        self.assertIsNone(ed.pick_at((1.5, 0)))
        ed.ui.scale_factor_entry.set_value(2.0)
        ed.on_scale()
        self.assertIsNotNone(ed.pick_at((1.5, 0)))

        # the size edit of an aperture
        ed = make_editor({10: aperture([pad(0, 0, 1.0)])}, pixel=0.01)
        make_select(ed)
        ed.tid2apcode = {1: 10}
        ed.oldapcode_newapcode = {10: 10}
        table = ed.ui.apertures_table
        table.setColumnCount(5)
        table.setItem(0, 3, QtWidgets.QTableWidgetItem('4.0'))
        table.itemChanged.connect(ed.on_tool_edit)
        table.setCurrentCell(0, 3)
        self.assertIsNone(ed.pick_at((1.5, 0)))
        ed.on_tool_edit()
        self.assertIsNotNone(ed.pick_at((1.5, 0)))

    def test_count_guard_rebuilds(self):
        extra = pad(30, 0, 1.0)
        self.ed.storage_dict[10]['geometry'].append(extra)           # a forgotten call site
        self.assertIs(self.ed.pick_at((30, 0))[0], extra)


class TestRevisionCounter(PickCase):
    def check(self, name, editor, action):
        before = editor.geometry_revision
        action()
        self.assertGreater(editor.geometry_revision, before, name)

    def test_revision_counter_sites(self):
        shape = pad(0, 0, 1.0)

        def editor():
            ed = make_editor({10: aperture([pad(0, 0, 1.0)]), 11: aperture([pad(5, 0, 1.0)])})
            make_select(ed)
            return ed

        # A1
        ed = editor()
        self.check('A1', ed, lambda: ed.add_gerber_shape(shape, ed.storage_dict[10]['geometry']))

        # A4 and D2: the eraser
        ed = editor()
        ed.selected = [DrawToolShape({'solid': box(-2, -2, 2, 2)})]
        tool = EraserEditorGrb(ed)
        tool.origin = (0, 0)
        tool.destination = (0, 0)
        self.check('A4', ed, tool.make)

        # A5
        ed = editor()
        ed.build_ui_sig.disconnect()
        ns = SimpleNamespace(draw_app=ed, sel_storage=[aperture([pad(9, 9, 1.0)])], app=ed.app)
        self.check('A5', ed, lambda: ImportEditorGrb.import_shapes(ns))

        # D1
        ed = editor()
        victim = ed.storage_dict[10]['geometry'][0]
        self.check('D1', ed, lambda: ed.delete_shape(victim))

        # D4
        ed = editor()
        ed.ui.apertures_table.selectRow(0)
        self.check('D4', ed, lambda: ed.on_aperture_delete(ap_code=[10]))

        # R1: the aperture code edit
        ed = editor()
        ed.tid2apcode = {1: 10, 2: 11}
        ed.oldapcode_newapcode = {10: 10, 11: 11}
        table = ed.ui.apertures_table
        table.setItem(0, 1, QtWidgets.QTableWidgetItem('12'))
        table.itemChanged.connect(ed.on_tool_edit)
        table.setCurrentCell(0, 1)
        self.check('R1', ed, ed.on_tool_edit)

        # R4
        ed = make_editor({'10': aperture([pad(0, 0, 1.0)])})
        ed.selected = [ed.storage_dict['10']['geometry'][0]]
        ed.sync_aperture_rows({'10'})
        ed.ui.scale_factor_entry.set_value(2.0)
        self.check('R4', ed, ed.on_scale)

        # R5
        ed = editor()
        ed.selected = [ed.storage_dict[10]['geometry'][0]]
        ed.sync_aperture_rows({10})
        plugin = SimpleNamespace(app=ed.app, draw_app=ed)
        self.check('R5', ed, lambda: BufferEditorTool.buffer(plugin, 0.5, 1))

        # T1 to T6
        tool = SimpleNamespace()
        calls = {
            'T1': lambda: run_transform(tool, 'rotate', [10, (0, 0)]),
            'T2': lambda: run_transform(tool, 'flip', ['X', (0, 0)]),
            'T3': lambda: run_transform(tool, 'skew', ['X', 10, 0, (0, 0)]),
            'T4': lambda: run_transform(tool, 'scale', ['X', 2, 2, (0, 0)]),
            'T5': lambda: run_transform(tool, 'offset', ['X', 1]),
            'T6': lambda: run_transform(tool, 'buffer', [0.5, 1]),
        }
        for name, call in calls.items():
            ed = editor()
            ed.selected = [ed.storage_dict[10]['geometry'][0]]
            tool.draw_app, tool.app = ed, ed.app
            self.check(name, ed, call)

        # L3
        ed = editor()
        ed.shapes = MagicMock()
        ed.tool_shape = MagicMock()
        ed.ma_annotation = MagicMock()
        self.check('L3', ed, ed.clear)
        self.assertIsNone(ed._pick_cache)

        # L1
        ed = editor()
        try:
            self.check('L1', ed, ed.activate_grb_editor)
        except Exception as err:        # the activation touches parts of the application that are stand-ins
            if ed.geometry_revision == 0:
                raise
            self.assertTrue(err is not None)


@pytest.mark.slow
class TestPerformance(PickCase):
    def test_large_board_pick_time(self):
        shapes = []
        for i in range(8000):
            shapes.append(pad((i % 100) * 2.0, (i // 100) * 2.0, 0.4))
        traces = [trace((i % 100) * 2.0, (i // 100) * 1.0, (i % 100) * 2.0 + 3, (i // 100) * 1.0 + 1, 0.2)
                  for i in range(12000)]
        ed = make_editor({10: aperture(shapes), 11: aperture(traces)})
        make_select(ed)
        self.assertIsNotNone(ed.pick_at((0, 0)))
        times = []
        for i in range(100):
            start = time.perf_counter()
            ed.pick_at(((i % 100) * 2.0 + 0.1, 0.1))
            times.append(time.perf_counter() - start)
        self.assertLess(statistics.median(times), 0.005)


class TestPixelSize(PickCase):
    def test_pixel_size_vispy(self):
        from appGUI.PlotCanvas3d import PlotCanvas3d
        from appGUI.VisPyCanvas import VisPyCanvas

        class Transform:
            @staticmethod
            def map(pos):
                return (pos[0] * 0.05, pos[1] * 0.05)

        for cls in (VisPyCanvas, PlotCanvas3d):
            stub = SimpleNamespace(grid=SimpleNamespace(get_transform=lambda *a: Transform()))
            stub.translate_coords = lambda pos, stub=stub, cls=cls: cls.translate_coords(stub, pos)
            self.assertAlmostEqual(cls.pixel_size(stub), 0.05)


class TestCanvasOwnership(PickCase):
    def test_semidisc_exit_and_reentry_disconnect_shortcut(self):
        from PyQt6.QtGui import QAction

        ed = make_editor()
        action = QAction('Semidisc')
        ed.app.ui.grb_draw_semidisc = action
        ed.on_add_semidisc = MagicMock()
        for cycle in range(3):
            ed.connect_canvas_event_handlers()
            action.trigger()
            self.assertEqual(ed.on_add_semidisc.call_count, cycle + 1)
            ed.disconnect_canvas_event_handlers()
            action.trigger()
            self.assertEqual(ed.on_add_semidisc.call_count, cycle + 1)

    def test_editor_import_exit_and_reentry_restore_callbacks_once(self):
        ed = make_editor()
        callbacks = {}

        def connect(name, callback):
            handlers = callbacks.setdefault(name, [])
            self.assertNotIn(callback, handlers)
            handlers.append(callback)

        def disconnect(name, callback):
            callbacks[name].remove(callback)

        ed.canvas.graph_event_connect = connect
        ed.canvas.graph_event_disconnect = disconnect
        app_handlers = {
            'mouse_press': ed.app.on_mouse_click_over_plot,
            'mouse_move': ed.app.on_mouse_move_over_plot,
            'mouse_release': ed.app.on_mouse_click_release_over_plot,
            'mouse_double_click': ed.app.on_mouse_double_click_over_plot,
        }
        for name, callback in app_handlers.items():
            connect(name, callback)
        tool = ImportEditorGrb.__new__(ImportEditorGrb)
        tool.app, tool.draw_app, tool.canvas = ed.app, ed, ed.canvas
        tool._canvas_connected = False
        ed.toolbar_old_state = False
        for exit_path in ('switch', 'escape', 'exit'):
            ed.connect_canvas_event_handlers()
            ed.active_tool = tool
            tool.grid_status_memory = True
            ed.app.ui.grid_snap_btn.trigger.reset_mock()
            tool.import_connect()
            tool.import_connect()
            self.assertEqual(callbacks['mouse_press'], [tool.on_mouse_click])
            if exit_path == 'escape':
                tool.clean_up()
                tool.clean_up()
            if exit_path == 'exit':
                ed.deactivate_grb_editor()
            else:
                AppGerberEditor.select_tool(ed, 'select')
                self.assertEqual(callbacks['mouse_press'], [ed.on_canvas_click])
                ed.disconnect_canvas_event_handlers()
            self.assertEqual(callbacks, {name: [callback] for name, callback in app_handlers.items()})
            ed.app.ui.grid_snap_btn.trigger.assert_called_once_with()
        self.assertIsNone(ed.app.plotcanvas.text_cursor.parent)
        ed.app.tool_shapes.clear.assert_called_with(update=True)
        for name in ('mp', 'mm', 'mr', 'mdc', 'kp'):
            self.assertNotIn(name, ed.app.__dict__)


class TestSnap(PickCase):
    def test_grid_snap_does_not_change_pick(self):
        trc = trace(0, 1.0, 10, 1.0)
        ed = make_editor({10: aperture([trc])}, grid=True)
        make_select(ed)
        press(ed, 5.0, 1.1)             # 0.05 off the edge; the snapped point would be (5.08, 0.0)
        self.assertEqual(ed.press_pos_raw, (5.0, 1.1))
        self.assertEqual(ed.pos, (5.0, 1.1))
        release(ed, 5.0, 1.1)
        self.assertEqual(ed.selected, [trc])

        # the draw tools keep the snap
        seen = []

        class Recorder(ShapeToolEditorGrb):
            def click(self, point):
                seen.append(point)

        recorder = Recorder(ed)
        recorder.name = 'recorder'
        ed.active_tool = recorder
        press(ed, 1.1, 1.3)
        self.assertEqual(seen, [snap(1.1, 1.3)])

    def test_rubber_band_uses_raw_position_for_select(self):
        ed = make_editor({10: aperture([pad(0, 0, 1.0)])}, grid=True)
        make_select(ed)
        press(ed, 1.1, 1.3)
        move(ed, 4.1, 4.3)
        end = ed.app.draw_moving_selection_shape.call_args[0][1]
        self.assertEqual(tuple(end), (4.1, 4.3))


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

    def test_equal_stacked_shapes_are_all_reachable(self):
        a, b = pad(0, 0, 1.0), pad(0, 0, 1.0)
        ed = make_editor({10: aperture([a]), 11: aperture([b])})
        make_select(ed)
        click(ed, 0, 0)
        first = ed.selected[0]
        click(ed, 0, 0)
        self.assertEqual(len(ed.selected), 1)
        self.assertIsNot(ed.selected[0], first)
        self.assertEqual({id(first), id(ed.selected[0])}, {id(a), id(b)})

    def test_cycle_restarts_after_a_click_elsewhere(self):
        big, small, other = pad(0, 0, 3.0), pad(0, 0, 1.0), pad(20, 0, 1.0)
        ed = make_editor({10: aperture([big, small, other])})
        make_select(ed)
        click(ed, 0, 0)
        click(ed, 20, 0)
        click(ed, 0, 0)
        self.assertEqual(ed.selected, [small])

    def test_cycle_restarts_when_the_click_moves_5_px(self):
        big, small = pad(0, 0, 3.0), pad(0, 0, 1.0)
        ed = make_editor({10: aperture([big, small])}, pixel=0.05)
        make_select(ed)
        click(ed, 0, 0)
        click(ed, 0.3, 0)   # 6 px away, still inside both pads
        self.assertEqual(ed.selected, [small])
        click(ed, 0.35, 0)  # 1 px from the last click: next one
        self.assertEqual(ed.selected, [big])

    def test_cycle_restarts_after_a_storage_change(self):
        big, small = pad(0, 0, 3.0), pad(0, 0, 1.0)
        ed = make_editor({10: aperture([big, small])})
        make_select(ed)
        click(ed, 0, 0)
        ed.touch_geometry()
        click(ed, 0, 0)
        self.assertEqual(ed.selected, [small])

    def test_cycle_with_the_multi_select_key_replaces_only_the_last_pick(self):
        big, small, other = pad(0, 0, 3.0), pad(0, 0, 1.0), pad(20, 0, 1.0)
        ed = make_editor({10: aperture([big, small, other])})
        make_select(ed)
        with modifiers(CONTROL):
            click(ed, 20, 0)
            click(ed, 0, 0)
            self.assertEqual(ed.selected, [other, small])
            click(ed, 0, 0)
            self.assertEqual(ed.selected, [other, big])

    def test_single_candidate_toggles_as_before(self):
        a = pad(0, 0, 1.0)
        ed = make_editor({10: aperture([a])})
        make_select(ed)
        with modifiers(CONTROL):
            click(ed, 0, 0)
            self.assertEqual(ed.selected, [a])
            click(ed, 0, 0)
            self.assertEqual(ed.selected, [])


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

    def test_six_pixel_move_is_drag(self):
        press(self.ed, 0, 0)
        move(self.ed, 0.3, 0)
        release(self.ed, 0.3, 0)
        self.ed.draw_selection_area_handler.assert_called_once()
        self.release_spy.assert_not_called()

    def test_move_out_and_back_is_click(self):
        press(self.ed, 0, 0)
        move(self.ed, 1.0, 0)
        self.assertIsNotNone(self.ed.app.selection_type)
        move(self.ed, 0.1, 0)
        release(self.ed, 0.1, 0)
        self.ed.draw_selection_area_handler.assert_not_called()
        self.release_spy.assert_called_once()
        self.assertEqual(self.ed.selected, [self.shape])


class TestTableSync(PickCase):
    def setUp(self):
        self.a, self.b = pad(0, 0, 1.0), pad(10, 0, 1.0)
        self.ed = make_editor({10: aperture([self.a]), 11: aperture([self.b])})
        self.tool = make_select(self.ed)
        self.table = self.ed.ui.apertures_table
        self.ed.calls.update(row=0, sel=0)

    def selected_rows(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows())

    def test_table_sync_no_handler_fires(self):
        receivers = self.ed.ui.apertures_table.receivers(self.table.cellPressed)
        self.ed.selected = [self.a, self.b]
        self.tool.after_selection()
        self.assertEqual(self.ed.calls, {'row': 0, 'sel': 0})
        self.assertEqual(self.selected_rows(), [0, 1])
        self.assertEqual(self.table.receivers(self.table.cellPressed), receivers)

    def test_table_handlers_fire_after_sync(self):
        self.ed.selected = [self.a]
        self.tool.after_selection()
        self.assertEqual(self.ed.calls, {'row': 0, 'sel': 0})
        self.table.cellPressed.emit(1, 1)
        self.assertEqual(self.ed.calls['row'], 1)
        self.table.selectRow(1)
        self.assertEqual(self.ed.calls['sel'], 1)

    def test_table_sync_survives_repeats(self):
        receivers = self.table.receivers(self.table.cellPressed)
        self.ed.selected = [self.a, self.b]
        self.tool.after_selection()
        self.tool.after_selection()
        self.assertEqual(self.table.receivers(self.table.cellPressed), receivers)
        self.assertEqual(self.ed.calls, {'row': 0, 'sel': 0})
        self.table.cellPressed.emit(0, 1)
        self.assertEqual(self.ed.calls['row'], 1)       # one receiver, not two

    def test_table_sync_after_build_ui(self):
        for value in self.ed.storage_dict.values():
            value['size'] = 0.5
        self.ed.gerber_obj = MagicMock()
        self.ed.gerber_obj.obj_options = {'name': 'x'}
        AppGerberEditor.build_ui(self.ed)
        receivers = self.table.receivers(self.table.cellPressed)
        self.ed.selected = [self.a, self.b]
        self.tool.after_selection()
        self.tool.after_selection()
        AppGerberEditor.build_ui(self.ed)
        self.assertEqual(self.table.receivers(self.table.cellPressed), receivers)


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

    def test_rectangle_uses_warm_index_without_storage_scan(self):
        class NoScan(list):
            def __iter__(self):
                raise AssertionError('Rectangle selection scanned geometry storage')

        self.ed.get_pick_index()
        for storage in self.ed.storage_dict.values():
            storage['geometry'] = NoScan(storage['geometry'])
        self.ed.draw_selection_area_handler((-0.5, -0.5), (2, 2), True)
        self.assertEqual(self.ed.selected, [self.a])

    def test_rectangle_avoids_selected_list_membership_scans(self):
        class NoMembershipScan(list):
            def __contains__(self, item):
                raise AssertionError('Rectangle selection searched the selection list')

        self.ed.selected = NoMembershipScan([self.far])
        self.ed.draw_selection_area_handler((-0.5, -0.5), (2, 2), False)
        self.assertEqual(self.ed.selected, [self.far, self.a, self.b])

    def test_empty_rectangle_clears_stale_aperture_rows(self):
        self.ed.draw_selection_area_handler((-1, -1), (12, 2), True)
        self.ed.selected = []
        self.ed.draw_selection_area_handler((100, 100), (101, 101), True)
        self.assertEqual(self.ed.selected, [])
        self.assertEqual(self.ed.ui.apertures_table.selectionModel().selectedRows(), [])

    def test_table_selection_does_not_duplicate_existing_shapes(self):
        with modifiers(CONTROL):
            self.ed.on_row_selected(1, 1)
            self.ed.on_row_selected(1, 1)
        self.assertEqual(self.ed.selected, [self.a, self.b])
        table = self.ed.ui.apertures_table
        with QtCore.QSignalBlocker(table), QtCore.QSignalBlocker(table.selectionModel()):
            table.selectAll()
        self.ed.on_table_selection()
        self.ed.on_table_selection()
        self.assertEqual(self.ed.selected, [self.a, self.b, self.far])
        self.ed.plot_all.assert_not_called()


class TestSelectionRendering(PickCase):
    def setUp(self):
        from appGUI.VisPyVisuals import ShapeCollectionVisual

        gl_state = patch('appGUI.VisPyVisuals.set_state')
        gl_state.start()
        self.addCleanup(gl_state.stop)
        self.a, self.b = pad(0, 0, 1.0), pad(10, 0, 1.0)
        self.ed = make_editor({10: aperture([self.a]), 11: aperture([self.b])})
        self.tool = make_select(self.ed)
        self.ed.get_draw_color = lambda: '#123456FF'
        self.ed.get_sel_color = lambda: '#ABCDEF'
        self.ed.shapes = ShapeCollectionVisual(layers=1, fcoptions={})
        self.ed.plot_all = MagicMock(side_effect=lambda: AppGerberEditor.plot_all(self.ed))
        self.ed.plot_all()
        self.keys = list(self.ed.shapes.data)
        self.ed.plot_all.reset_mock()

    def test_clicks_reuse_geometry_buffers_and_restore_colors(self):
        buffers = [self.ed.shapes.data[key]['mesh_vertices'] for key in self.keys]
        with patch('appGUI.VisPyVisuals._update_shape_buffers',
                   side_effect=AssertionError('Selection rebuilt geometry')):
            with modifiers(NO_MOD):
                click(self.ed, 0, 0)
                self.assertEqual(self.ed.shapes.data[self.keys[0]]['face_color'], '#ABCDEFAF')
                click(self.ed, 10, 0)
                self.assertEqual(self.ed.shapes.data[self.keys[0]]['face_color'], '#123456AF')
                self.assertEqual(self.ed.shapes.data[self.keys[1]]['face_color'], '#ABCDEFAF')
                click(self.ed, 100, 100)
                self.assertEqual(self.ed.shapes.data[self.keys[1]]['face_color'], '#123456AF')
        self.ed.plot_all.assert_not_called()
        for key, vertices in zip(self.keys, buffers):
            self.assertIs(self.ed.shapes.data[key]['mesh_vertices'], vertices)

    def test_multiselect_toggles_only_changed_colors(self):
        with modifiers(CONTROL):
            click(self.ed, 0, 0)
            click(self.ed, 10, 0)
            click(self.ed, 0, 0)
        self.assertEqual(self.ed.selected, [self.b])
        self.assertEqual(self.ed.shapes.data[self.keys[0]]['face_color'], '#123456AF')
        self.assertEqual(self.ed.shapes.data[self.keys[1]]['face_color'], '#ABCDEFAF')
        self.ed.plot_all.assert_not_called()

    def test_geometry_edit_rebuilds_rendering_before_highlight(self):
        self.a.geo['solid'] = box(-2, -2, 2, 2)
        self.ed.touch_geometry()
        with modifiers(NO_MOD):
            click(self.ed, 0, 0)
        self.ed.plot_all.assert_called_once()
        self.assertEqual(self.ed.shapes.data[self.keys[0]]['mesh_vertices'][:, 0].max(), 2)
        self.assertEqual(self.ed.shapes.data[self.keys[0]]['face_color'], '#ABCDEFAF')

    def test_aperture_sync_uses_cached_ownership_after_edit(self):
        class NoMembershipScan(list):
            def __contains__(self, item):
                raise AssertionError('Selection scanned aperture geometry')

        self.ed.storage_dict[10]['geometry'] = NoMembershipScan([self.a])
        self.ed.get_pick_index()
        self.ed.selected = [self.a]
        self.tool.after_selection()
        self.assertEqual(self.tool.sel_aperture, {10})
        self.ed.storage_dict[10]['geometry'].clear()
        self.ed.storage_dict[11]['geometry'].append(self.a)
        self.ed.touch_geometry()
        self.tool.after_selection()
        self.assertEqual(self.tool.sel_aperture, {11})

    def test_rectangle_and_table_selection_reuse_geometry_buffers(self):
        with patch('appGUI.VisPyVisuals._update_shape_buffers',
                   side_effect=AssertionError('Bulk selection rebuilt geometry')):
            self.ed.draw_selection_area_handler((-2, -2), (12, 2), True)
            self.assertEqual(self.ed.selected, [self.a, self.b])
            with modifiers(NO_MOD):
                self.ed.on_row_selected(0, 1)
            self.assertEqual(self.ed.shapes.data[self.keys[1]]['face_color'], '#123456AF')
            table = self.ed.ui.apertures_table
            with QtCore.QSignalBlocker(table), QtCore.QSignalBlocker(table.selectionModel()):
                table.selectAll()
            self.ed.on_table_selection()
            for key in self.keys:
                self.assertEqual(self.ed.shapes.data[key]['face_color'], '#ABCDEFAF')
        self.ed.plot_all.assert_not_called()


class TestSimplifyClick(PickCase):
    def make_tool(self, ed):
        tool = SimplifyEditorGrb.__new__(SimplifyEditorGrb)
        tool.draw_app = ed
        tool.simp_tool = MagicMock()
        tool.name = 'simplify'
        tool.complete = False
        tool.points = []
        tool.geometry = None
        ed.active_tool = tool
        return tool

    def test_simplify_click_picks_one(self):
        a, b = pad(0, 0, 1.0), pad(1.5, 0, 1.0)
        ed = make_editor({10: aperture([a]), 11: aperture([b])}, grid=True)
        self.make_tool(ed)
        click(ed, 0.75, 0.0)            # inside both
        self.assertEqual(len(ed.selected), 1)
        picked = ed.selected[0]
        self.assertIs(picked, ed.pick_at((0.75, 0.0))[0])
        # the Select tool picks the same shape
        select_ed = make_editor({10: aperture([a]), 11: aperture([b])}, grid=True)
        make_select(select_ed)
        click(select_ed, 0.75, 0.0)
        self.assertEqual(select_ed.selected, [picked])

        other_only = (2.2, 0.0) if picked is a else (-0.9, 0.0)
        with modifiers(CONTROL):
            click(ed, *other_only)
        self.assertEqual(len(ed.selected), 2)


class TestEraserClick(PickCase):
    def test_eraser_pick_uses_pick_at(self):
        trc = trace(0, 0, 10, 0)
        ed = make_editor({10: aperture([trc]), 11: aperture([pad(50, 50, 1.0)])})
        tool = EraserEditorGrb(ed)
        ed.active_tool = tool
        table = ed.ui.apertures_table
        receivers = table.receivers(table.cellPressed)
        ed.calls.update(row=0, sel=0)
        tool.click((5, 0.25))
        self.assertEqual(ed.selected, [trc])
        self.assertEqual(sorted(i.row() for i in table.selectionModel().selectedRows()), [0])
        self.assertEqual(ed.calls, {'row': 0, 'sel': 0})
        self.assertEqual(table.receivers(table.cellPressed), receivers)
        self.assertEqual(tool.origin, (5, 0.25))

    def test_eraser_nothing_to_erase(self):
        ed = make_editor({10: aperture([trace(0, 0, 10, 0)])})
        tool = EraserEditorGrb(ed)
        self.assertIsNotNone(tool.click((5, 5)))
        self.assertIsNone(tool.origin)

    def test_eraser_second_click_snaps(self):
        trc = trace(0, 1.0, 10, 1.0)
        ed = make_editor({10: aperture([trc])}, grid=True)
        tool = EraserEditorGrb(ed)
        ed.active_tool = tool
        press(ed, 5.0, 1.1)
        self.assertEqual(ed.selected, [trc])
        self.assertEqual(tool.origin, (5.0, 1.1))
        with patch.object(EraserEditorGrb, 'make'):
            press(ed, 6.0, 1.3)
        self.assertEqual(tool.destination, snap(6.0, 1.3))


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

    def test_eraser_make_no_empty_shapes(self):
        touched = trace(0, 0, 10, 0, 0.4)
        far = trace(0, 20, 10, 20, 0.4)
        a, b = pad(30, 30, 1.0), pad(40, 40, 1.0)
        ed = make_editor({10: aperture([touched, far]), 11: aperture([a]), 12: aperture([b])})
        self.eraser(ed, 5, 0).make()
        aperture0 = ed.storage_dict[0]['geometry']
        self.assertEqual(len(aperture0), 1)
        for shape in aperture0:
            self.assertTrue(shape.geo)
            self.assertFalse(shape.geo['solid'].is_empty)
        self.assertEqual(ed.storage_dict[10]['geometry'], [far])
        self.assertEqual(ed.storage_dict[11]['geometry'], [a])
        self.assertEqual(ed.storage_dict[12]['geometry'], [b])

    def test_eraser_make_no_copies(self):
        one = trace(0, 0, 10, 0, 0.4)
        two = trace(0, 0.1, 10, 0.1, 0.4)
        other = trace(0, 20, 10, 20, 0.4)
        ed = make_editor({10: aperture([one, other]), 11: aperture([two])})
        self.eraser(ed, 5, 0).make()
        self.assertEqual(len(ed.storage_dict[0]['geometry']), 2)
        self.assertEqual(ed.storage_dict[10]['geometry'], [other])


class TestEditorOperations(PickCase):
    def test_copy_batch_replots_once(self):
        shapes = [pad(x * 3, 0, 1) for x in range(30)]
        ed = make_editor({10: aperture(shapes)})
        ed.selected = list(shapes)
        ed.sync_aperture_rows({10})
        tool = CopyEditorGrb(ed)
        ed.active_tool = tool
        tool.origin = (0, 0)
        tool.destination = (0, 10)
        tool.make()
        self.assertEqual(len(ed.storage_dict[10]['geometry']), 60)
        self.assertEqual(ed.selected, [])
        self.assertTrue(ed.storage_dict[10]['geometry'][30].geo['solid'].equals(pad(0, 10, 1).geo['solid']))
        ed.plot_all.assert_called_once()

    def test_bulk_delete_filters_storage_without_per_shape_searches(self):
        class NoMembershipScan(list):
            def __contains__(self, item):
                raise AssertionError('Bulk deletion must not search the geometry list for every shape')

        shapes = [pad(x * 3, 0, 1) for x in range(100)]
        keep = pad(0, 10, 1)
        ed = make_editor({10: aperture(shapes + [keep]), 11: aperture([shapes[0]])})
        ed.storage_dict[10]['geometry'] = NoMembershipScan(shapes + [keep])
        utility = module.DrawToolUtilityShape({'solid': box(0, 0, 1, 1)})
        ed.utility = [utility]
        ed.selected = list(reversed(shapes)) + [utility]
        revision = ed.geometry_revision
        ed.delete_selected()
        self.assertEqual(ed.storage_dict[10]['geometry'], [keep])
        self.assertEqual(ed.storage_dict[11]['geometry'], [])
        self.assertEqual(ed.utility, [])
        self.assertEqual(ed.selected, [])
        self.assertTrue(ed.is_modified)
        self.assertEqual(ed.geometry_revision, revision + 1)

    def test_repeated_buffer_preserves_live_selection_and_unselected_shapes(self):
        selected, other = pad(0, 0, 1), pad(10, 0, 1)
        ed = make_editor({10: aperture([selected, other])})
        ed.selected = [selected]
        ed.sync_aperture_rows({10})
        plugin = SimpleNamespace(app=ed.app, draw_app=ed)
        BufferEditorTool.buffer(plugin, 1, 'round')
        first_area = ed.storage_dict[10]['geometry'][0].geo['solid'].area
        BufferEditorTool.buffer(plugin, 1, 'round')
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

    def test_zoom_fit_uses_bounds_without_union(self):
        ed = make_editor({10: aperture([
            DrawToolShape({'solid': box(10, 20, 12, 22)}),
            DrawToolShape({'solid': box(14, 25, 17, 29)}),
            DrawToolShape({'solid': Polygon()}),
            DrawToolShape({'follow': Point(100, 100)})
        ])})
        with patch.object(module, 'unary_union', side_effect=AssertionError('Zoom Fit must not union geometry')):
            ed.on_zoom_fit()
        rect = ed.app.plotcanvas.fit_view.call_args.kwargs['rect']
        self.assertEqual((rect.left, rect.bottom, rect.right, rect.top), (10, 20, 17, 29))

    def test_zoom_fit_empty_board_does_not_change_view(self):
        ed = make_editor()
        ed.on_zoom_fit()
        ed.app.plotcanvas.fit_view.assert_not_called()


if __name__ == '__main__':
    unittest.main()
