"""Gerber Editor Transformation plugin actions (rotate, flip, skew, scale, offset, buffer): batch results against the
old per-shape shapely.affinity algorithm, the plot count, the selection and the pick index. The editor is the real
class; the application and the shape collection are stand-ins. Everything is headless."""

import os
import time
import statistics
import unittest
from unittest.mock import MagicMock, patch

from PyQt6 import QtWidgets

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from shapely.affinity import rotate, scale, skew, translate
from shapely.geometry import Point

from appEditors import appGerberEditor
from appEditors.appGerberEditor import AppGerberEditor
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appEditors.grb_plugins import GrbTransformationPlugin
from appEditors.grb_plugins.GrbTransformationPlugin import TransformEditorTool, queue_transform, selection_bounds
from test_gerber_editor_pick import aperture, make_editor, pad, trace

KEYS = ('solid', 'follow', 'clear')


class FakeShapes:
    """Stand-in of the shape collection: records the calls."""

    def __init__(self, transform_ok=True):
        self.last_key = 0
        self.added = []
        self.removed = []
        self.transformed = []
        self.redraws = 0
        self.transform_ok = transform_ok

    def add(self, **kwargs):
        self.last_key += 1
        self.added.append((self.last_key, kwargs))
        return self.last_key

    def remove(self, key, update=False):
        self.removed.append(key)

    def clear(self, update=False):
        pass

    def redraw(self, *args, **kwargs):
        self.redraws += 1

    def transform_keys(self, keys, matrix, update=True):
        self.transformed.append((list(keys), tuple(matrix)))
        return self.transform_ok


class Host:
    """Stand-in of the tool: the path the UI uses (queue_transform -> history job -> result applied on the GUI
    thread), run synchronously on the real editor and a fake app."""

    def __init__(self, draw_app):
        self.app = draw_app.app
        self.draw_app = draw_app
        self.messages = []
        self.app.inform.emit.side_effect = self.messages.append

    def run(self, kind, params):
        if queue_transform(self, kind, params) == 'fail':
            return 'fail'
        job = self.app.worker_task.emit.call_args.args[0]
        job['fcn'](*job['params'])
        QtWidgets.QApplication.processEvents()

    def on_rotate_action(self, val, point):
        return self.run('rotate', [val, point])

    def on_flip(self, axis, point):
        return self.run('flip', [axis, point])

    def on_skew(self, axis, xval, yval, point):
        return self.run('skew', [axis, xval, yval, point])

    def on_scale(self, axis, xfactor, yfactor, point):
        return self.run('scale', [axis, xfactor, yfactor, point])

    def on_offset(self, axis, num):
        return self.run('offset', [axis, num])

    def on_buffer_action(self, value, join, factor=None):
        return self.run('buffer', [value, join] if factor is None else [value, join, factor])


def full_shape(cx, cy):
    geo = {'solid': Point(cx, cy).buffer(0.5, 8), 'follow': Point(cx, cy), 'clear': Point(cx, cy).buffer(0.7, 8)}
    return DrawToolShape(geo)


def build(count=5, real_plot=False, transform_ok=True):
    shapes = [full_shape(i * 2.0, (i % 3) * 1.5) for i in range(count)]
    shapes.append(trace(-3, -1, 4, 2))
    editor = make_editor({10: aperture(shapes[:3]), 11: aperture(shapes[3:])})
    editor.app.options.update({'global_draw_color': '#0000FFFF', 'global_sel_draw_color': '#FF0000FF',
                               'global_theme': 'default'})
    editor.shapes = FakeShapes(transform_ok)
    editor.tolerance = None
    editor.plot_count = 0
    if real_plot:
        real = AppGerberEditor.plot_all.__get__(editor)

        def counted():
            editor.plot_count += 1
            real()
        editor.plot_all = counted
    else:
        def counted():
            editor.plot_count += 1
        editor.plot_all = counted
    editor.selected = list(shapes[:4]) + [shapes[-1]]
    host = Host(editor)
    return host, editor, shapes


def snapshot(shapes):
    return [{k: v for k, v in s.geo.items()} for s in shapes]


def reference(shapes_geo, fn):
    return [{k: fn(v) for k, v in geo.items() if k in KEYS} for geo in shapes_geo]


def same_geo(test, a, b):
    test.assertEqual(a.geom_type, b.geom_type)
    test.assertTrue(np.allclose(np.asarray(a.bounds), np.asarray(b.bounds), atol=1e-9))
    test.assertTrue(np.allclose(np.array(a.exterior.coords if hasattr(a, 'exterior') else a.coords),
                                np.array(b.exterior.coords if hasattr(b, 'exterior') else b.coords), atol=1e-9))


class TransformCase(unittest.TestCase):
    def check(self, action, ref_fn, selected_only=True):
        host, editor, shapes = build()
        before = snapshot(shapes)
        selected = list(editor.selected)
        action(host)
        sel_ids = {id(s) for s in selected}
        for shape, old in zip(shapes, before):
            if id(shape) in sel_ids:
                for key, expected in reference([old], ref_fn)[0].items():
                    same_geo(self, shape.geo[key], expected)
            else:
                for key, value in old.items():
                    self.assertIs(shape.geo[key], value)
        self.assertEqual(editor.plot_count, 1)
        self.assertEqual(editor.selected, selected)
        self.assertEqual(host.messages, [])
        return host, editor, shapes

    def test_rotate(self):
        self.check(lambda h: h.on_rotate_action(33.0, (1.5, -2.0)), lambda g: rotate(g, -33.0, origin=(1.5, -2.0)))

    def test_flip_x_and_y(self):
        self.check(lambda h: h.on_flip('X', (1.0, 2.0)), lambda g: scale(g, 1, -1, origin=(1.0, 2.0)))
        self.check(lambda h: h.on_flip('Y', (1.0, 2.0)), lambda g: scale(g, -1, 1, origin=(1.0, 2.0)))

    def test_skew(self):
        self.check(lambda h: h.on_skew('X', 12.0, 5.0, (0.5, 0.5)), lambda g: skew(g, 12.0, 5.0, origin=(0.5, 0.5)))

    def test_scale(self):
        self.check(lambda h: h.on_scale('X', 1.7, 0.6, (2.0, 1.0)), lambda g: scale(g, 1.7, 0.6, origin=(2.0, 1.0)))

    def test_offset(self):
        self.check(lambda h: h.on_offset('X', 3.25), lambda g: translate(g, 3.25, 0))
        self.check(lambda h: h.on_offset('Y', -1.5), lambda g: translate(g, 0, -1.5))

    def test_buffer_distance(self):
        host, editor, shapes = build()
        before = snapshot(shapes)
        selected = list(editor.selected)
        host.on_buffer_action(0.2, 'round')
        for shape, old in zip(shapes, before):
            if shape in selected:
                same_geo(self, shape.geo['solid'], old['solid'].buffer(0.2, quad_segs=16, join_style='round'))
                self.assertIs(shape.geo['follow'], old['follow'])
                if 'clear' in old:
                    same_geo(self, shape.geo['clear'], old['clear'].buffer(0.2, quad_segs=16, join_style='round'))
        self.assertEqual(editor.plot_count, 1)
        self.assertEqual(editor.selected, selected)
        self.assertEqual(host.messages, [])

    def test_buffer_mitre_int_join(self):
        host, editor, shapes = build()
        old = shapes[0].geo['solid']
        host.on_buffer_action(0.2, 2)
        same_geo(self, shapes[0].geo['solid'], old.buffer(0.2, quad_segs=16, join_style=2))

    def test_buffer_factor(self):
        host, editor, shapes = build()
        before = snapshot(shapes)
        host.on_buffer_action(1.3, 'round', True)
        for shape, old in zip(shapes, before):
            if shape in editor.selected:
                for key in old:
                    center = old['solid'].bounds
                    origin = ((center[0] + center[2]) / 2, (center[1] + center[3]) / 2)
                    same_geo(self, shape.geo[key], scale(old[key], 1.3, 1.3, origin=origin))
        self.assertEqual(editor.plot_count, 1)

    def test_no_selection(self):
        host, editor, shapes = build()
        editor.selected = []
        host.on_rotate_action(10.0, (0, 0))
        self.assertEqual(editor.plot_count, 0)
        self.assertEqual(len(host.messages), 1)
        self.assertTrue(host.messages[0].startswith('[WARNING_NOTCL]'))

    def test_error_message(self):
        host, editor, shapes = build()
        with patch.object(GrbTransformationPlugin, 'affine_selection', side_effect=ValueError('boom')):
            host.on_offset('X', 1.0)
        self.assertEqual(len(host.messages), 1)
        self.assertTrue(host.messages[0].startswith('[ERROR_NOTCL]'))
        self.assertIn('boom', host.messages[0])

    def test_duplicate_selection_transformed_once(self):
        host, editor, shapes = build()
        editor.selected = [shapes[0], shapes[0]]
        old = shapes[0].geo['solid']
        host.on_offset('X', 1.0)
        same_geo(self, shapes[0].geo['solid'], translate(old, 1.0, 0))

    def test_selection_bounds(self):
        host, editor, shapes = build()
        bounds = selection_bounds(editor.selected)
        xs = [s.geo['solid'].bounds for s in editor.selected]
        self.assertEqual(bounds, (min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs),
                                  max(b[3] for b in xs)))
        self.assertIsNone(selection_bounds([]))

    def test_modified_and_pick_index(self):
        host, editor, shapes = build()
        editor.is_modified = False
        tree_before = editor.get_pick_index()
        revision = editor.geometry_revision
        host.on_offset('X', 100.0)
        self.assertTrue(editor.is_modified)
        self.assertGreater(editor.geometry_revision, revision)
        tree, refs = editor.get_pick_index()
        self.assertIsNot(tree, tree_before[0])
        moved = [ref[2] for ref in refs]
        self.assertIn(shapes[0], moved)
        hit = tree.query(Point(100.0, 0.0).buffer(0.1))
        self.assertTrue(len(hit) >= 1)


class TestIncrementalPlot(unittest.TestCase):
    def test_affine_maps_the_plotted_buffers(self):
        host, editor, shapes = build(real_plot=True)
        editor.plot_all()
        self.assertEqual(editor.plot_count, 1)
        keys = [i for s in editor.selected for i in editor._rendered_shapes.get(s, ())]
        host.on_rotate_action(20.0, (0, 0))
        self.assertEqual(editor.plot_count, 1)          # no new plot_all
        self.assertEqual(len(editor.shapes.transformed), 1)
        self.assertEqual(sorted(editor.shapes.transformed[0][0]), sorted(keys))
        self.assertEqual(editor._render_state[0], editor.geometry_revision)
        # a second action stays incremental
        host.on_offset('Y', 1.0)
        self.assertEqual(editor.plot_count, 1)
        self.assertEqual(len(editor.shapes.transformed), 2)

    def test_affine_falls_back_to_replotting_the_shapes(self):
        host, editor, shapes = build(real_plot=True, transform_ok=False)
        editor.plot_all()
        added = len(editor.shapes.added)
        n_sel = len(editor.selected)
        host.on_offset('X', 2.0)
        self.assertEqual(editor.plot_count, 1)
        self.assertEqual(len(editor.shapes.added) - added, n_sel)
        self.assertEqual(len(editor.shapes.removed), n_sel)
        for shape in editor.selected:
            self.assertEqual(len(editor._rendered_shapes[shape]), 1)

    def test_buffer_replots_only_the_selection(self):
        host, editor, shapes = build(real_plot=True)
        editor.plot_all()
        added = len(editor.shapes.added)
        n_sel = len(editor.selected)
        host.on_buffer_action(0.1, 'round')
        self.assertEqual(editor.plot_count, 1)
        self.assertEqual(len(editor.shapes.added) - added, n_sel)
        self.assertEqual(len(editor.shapes.removed), n_sel)

    def test_out_of_sync_does_one_plot_all(self):
        host, editor, shapes = build(real_plot=True)
        host.on_offset('X', 2.0)
        self.assertEqual(editor.plot_count, 1)
        self.assertEqual(editor.shapes.transformed, [])


class TestBenchmark(unittest.TestCase):
    def test_2000_pads(self):
        count = 2000
        pads = [pad(i * 0.1, (i % 40) * 0.1, 0.03) for i in range(count)]
        for p in pads:
            p.geo['clear'] = p.geo['solid'].buffer(0.01)

        def per_shape(shapes, matrix):
            for shape in shapes:
                for key in KEYS:
                    shape.geo[key] = rotate(shape.geo[key], -30, origin=(5, 2))

        algorithms = (per_shape, GrbTransformationPlugin.affine_selection)
        timings = [[], []]
        # Compare identical history, export validation and UI work, not a bare
        # coordinate loop against a complete editor action. Alternate run order.
        for repetition in range(5):
            for index in ((0, 1) if repetition % 2 == 0 else (1, 0)):
                records = [DrawToolShape(dict(p.geo)) for p in pads]
                editor = make_editor({10: aperture(records)})
                editor.loaded_as_regions = False
                editor.selected = list(records)
                editor.plot_transformed = MagicMock()
                host = Host(editor)
                with patch.object(GrbTransformationPlugin, 'affine_selection', algorithms[index]):
                    start = time.perf_counter()
                    host.on_rotate_action(30, (5, 2))
                    timings[index].append(time.perf_counter() - start)
                self.assertEqual(len(editor.history.undo_stack), 1)
                self.assertEqual(len(editor.history.undo_stack[0]['apertures'][10][4]), count)
                self.assertEqual(editor.selected, records)
                self.assertEqual(editor.ui.features_table.rowCount(), count)
                self.assertFalse(editor.loaded_as_regions)
                same_geo(self, records[0].geo['solid'], rotate(pads[0].geo['solid'], -30, origin=(5, 2)))
                editor.deleteLater()
        old_time, new_time = (statistics.median(values) for values in timings)

        print('\n2000 pads rotate (5-run medians, identical transaction/UI): old per-shape %.1f ms, batch %.1f ms (x%.1f)' %
              (old_time * 1e3, new_time * 1e3, old_time / new_time))
        self.assertLess(new_time, old_time)


class SingleClassCase(unittest.TestCase):
    def test_editor_uses_the_plugin_class(self):
        self.assertIs(appGerberEditor.TransformEditorTool, GrbTransformationPlugin.TransformEditorTool)

    def test_no_mixin_in_the_plugin_module(self):
        names = [n for n in vars(GrbTransformationPlugin) if 'Mixin' in n]
        self.assertEqual(names, [])
        self.assertFalse([c for c in TransformEditorTool.__mro__ if 'Mixin' in c.__name__])


if __name__ == '__main__':
    unittest.main()
