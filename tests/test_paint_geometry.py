"""Run: python tests/test_paint_geometry.py"""
import math
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_saved_argv = sys.argv
sys.argv = [sys.argv[0]]
try:
    import camlib
    from appPlugins.ToolNCC.NccGen import NccGen
    from appPlugins.ToolPaint.PaintGen import PaintGen
    from shapely import LineString, LinearRing, Point, Polygon, box
finally:
    sys.argv = _saved_argv


def storage_of(paths):
    storage = camlib.AppRTreeStorage()
    storage.get_points = lambda go: [go.coords[0], go.coords[-1]]
    for path in paths:
        storage.insert(path)
    return storage


class TestPaintGeometry(unittest.TestCase):
    def setUp(self):
        self.geometry = camlib.Geometry.__new__(camlib.Geometry)
        self.geometry.app = SimpleNamespace(abort_flag=False, log=Mock(), inform_no_echo=Mock(),
                                            proc_container=Mock())
        self.polygon = Polygon(box(0, 0, 6, 6).exterior.coords,
                               [box(2, 2, 4, 4).exterior.coords])

    def test_shrink_uses_configured_circle_accuracy_for_cumulative_offsets(self):
        from test_shrink_offsets import inset_layers, layer_paths
        for steps in (1, 16, 17, 64):
            with self.subTest(steps=steps):
                paths = list(camlib.Geometry.clear_polygon_shrink(
                    self.geometry, self.polygon, 1, steps, connect=False).get_objects())
                expected = layer_paths(inset_layers(self.polygon, 1, 0.15, steps, True, bounded=True))
                self.assertEqual(len(paths), len(expected))
                self.assertTrue(all(a.equals_exact(b, 1e-12) for a, b in zip(paths, expected)))

    def test_trace_filling_uses_full_circle_steps(self):
        line = LineString([(1, 3), (5, 3)])
        paths = list(camlib.Geometry.fill_with_lines(
            self.geometry, line, 2, 0.5, 64, connect=False).get_objects())
        expected = line.buffer(1, quad_segs=16).buffer(-0.25, quad_segs=16)
        rings = [path for path in paths if isinstance(path, LinearRing)]
        self.assertEqual(len(rings), 1)
        self.assertTrue(rings[0].equals_exact(expected.exterior, 1e-12))

    def test_connect_reverses_nearest_end_and_lifts_for_long_walk(self):
        paths = [LineString([(1, 1), (2, 1)]), LineString([(4, 1), (3, 1)]),
                 LineString([(8, 1), (9, 1)])]
        result = camlib.Geometry.paint_connect(storage_of(paths), box(0, 0, 10, 3), 0.2, 64, max_walk=2)
        self.assertEqual([list(path.coords) for path in result.get_objects()],
                         [[(1, 1), (2, 1), (3, 1), (4, 1)], [(8, 1), (9, 1)]])

    def test_connect_lifts_at_a_hole(self):
        boundary = Polygon(box(0, 0, 8, 3).exterior.coords,
                           [box(2.5, 0.5, 3.5, 1.5).exterior.coords])
        paths = [LineString([(1, 1), (2, 1)]), LineString([(5, 1), (6, 1)])]
        result = camlib.Geometry.paint_connect(storage_of(paths), boundary, 0.2, 64)
        self.assertEqual([list(path.coords) for path in result.get_objects()],
                         [list(path.coords) for path in paths])

    def test_paint_and_ncc_dispatch_to_the_same_clearing_paths(self):
        worker = SimpleNamespace(app=self.geometry.app, parent_tool=self.geometry, circle_steps=64)
        for method in (0, 1, 2):
            for connect in (False, True):
                with self.subTest(method=method, connect=connect):
                    painted = PaintGen.paint_polygon_worker(
                        worker, self.polygon, 1, method, 0.15, connect, True, False, None)
                    cleared = NccGen.clear_polygon_worker(
                        worker, self.polygon, 1, method, 0.15, connect, True, False)
                    self.assertIsNotNone(painted)
                    self.assertIsNotNone(cleared)
                    self.assertEqual([list(path.coords) for path in painted.get_objects()],
                                     [list(path.coords) for path in cleared])
        self.geometry.app.log.error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
