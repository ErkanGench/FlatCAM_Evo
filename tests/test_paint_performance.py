"""Geometry-preserving Paint optimizations; run with --benchmark for timings/counts."""
import contextlib
import io
import json
import statistics
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_paint_geometry as paint_cases
from test_paint_geometry import camlib, PaintGen, storage_of
from shapely import MultiPolygon, Polygon, Point, box


def rest_worker(geometry, diameters, method=2, overlap=0.15, connect=False):
    worker = PaintGen.__new__(PaintGen)
    worker.app = geometry.app
    worker.app.inform = Mock()
    worker.units = 'MM'
    worker.decimals = 4
    worker.circle_steps = 64
    worker.parent_tool = geometry
    worker.ui = SimpleNamespace(rest_offset_entry=SimpleNamespace(get_value=lambda: 0))
    worker._cleanup_progressive_plotting = Mock()
    worker._validate_output_geometry = lambda output_obj: bool(output_obj.tools)
    params = SimpleNamespace(
        paint_method=method, prog_plot=False, simplification_value=0,
        output_object_name='benchmark', tools_storage={
            i: {'tooldia': dia, 'solid_geometry': [], 'data': {
                'tools_paint_overlap': overlap * 100, 'tools_paint_connect': connect,
                'tools_paint_contour': True, 'tools_paint_offset': 0}}
            for i, dia in enumerate(diameters, 1)})
    return worker, params


def run_rest(worker, params, polygons, diameters):
    output = SimpleNamespace(tools={}, obj_options={})
    # The legacy worker prints every residual polygon.
    with contextlib.redirect_stdout(io.StringIO()):
        result = worker._generate_rest_paint_worker(
            output, worker.app, params, list(diameters), polygons, None, False)
    assert result != 'fail'
    return [path for tool in output.tools.values() for path in tool['solid_geometry']]


class TestPaintPerformance(unittest.TestCase):
    setUp = paint_cases.TestPaintGeometry.setUp

    def test_two_rest_tools_keep_legacy_residual_coverage_and_paths(self):
        # Preserve both legacy residual calculations for intermediate tools.
        for method in (0, 1, 2):
            with self.subTest(method=method):
                worker, params = rest_worker(self.geometry, [1, 0.4], method=method)
                polygon = self.polygon.buffer(0)
                first = list(worker._process_polygon(
                    polygon, 1, worker._get_tool_params(1, params.tools_storage),
                    params, None).get_objects())
                swept = camlib.unary_union(first).buffer(0.5)
                local_rest = [p for p in camlib.flatten_shapely_geometry(polygon.difference(swept))
                              if p.is_valid and not p.is_empty]
                global_rest = camlib.flatten_shapely_geometry(MultiPolygon([polygon]).difference(swept))
                residual = MultiPolygon([p for p in global_rest if p.is_valid] + local_rest)
                if not residual.is_valid:
                    residual = camlib.unary_union([p for p in global_rest if p.is_valid] + local_rest)
                expected = list(first)
                for part in camlib.flatten_shapely_geometry(residual):
                    if part.buffer(-0.2).is_empty:
                        continue
                    result = worker._process_polygon(
                        part, 0.4, worker._get_tool_params(2, params.tools_storage), params, None)
                    expected.extend(result.get_objects())
                actual = run_rest(worker, params, [self.polygon], [1, 0.4])
                self.assertEqual([p.wkb for p in actual], [p.wkb for p in expected])
                self.assertTrue(camlib.unary_union(actual).equals(camlib.unary_union(expected)))

    def test_rest_rejects_narrow_residuals_without_buffering(self):
        polygons = [self.polygon, box(10, 0, 10.1, 4), box(12, 0, 16, 0.1)]
        original = Polygon.buffer
        narrow_buffers = []

        def measured(polygon, distance, *args, **kwargs):
            if distance == -0.5:
                left, bottom, right, top = polygon.bounds
                if right - left < 1 or top - bottom < 1:
                    narrow_buffers.append(polygon)
                    self.assertTrue(original(polygon, distance).is_empty)
            return original(polygon, distance, *args, **kwargs)

        worker, params = rest_worker(self.geometry, [1])
        with patch.object(Polygon, 'buffer', measured):
            paths = run_rest(worker, params, polygons, [1])
        expected_worker, expected_params = rest_worker(self.geometry, [1])
        expected = run_rest(expected_worker, expected_params, [self.polygon], [1])
        # Unioning extra disjoint polygons can rotate a ring's starting vertex.
        self.assertTrue(camlib.unary_union(paths).equals(camlib.unary_union(expected)))
        self.assertEqual(len(paths), len(expected))
        self.assertEqual(sum(len(p.coords) for p in paths), sum(len(p.coords) for p in expected))
        self.assertEqual(narrow_buffers, [])


def benchmark():
    case = paint_cases.TestPaintGeometry()
    case.setUp()
    geometry = case.geometry
    geometry.app.options = {'global_tolerance': 0.005}
    geometry.app.units = 'MM'
    holes = [Point(x, y).buffer(0.7, quad_segs=16).exterior.coords
             for x in range(3, 29, 3) for y in range(3, 20, 3)]
    board = Polygon(box(0, 0, 30, 21).exterior.coords, holes)

    def measure(name, operation):
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            paths = operation()
            samples.append(time.perf_counter() - start)
        print(json.dumps({'case': name, 'seconds_median': statistics.median(samples),
                          'paths': len(paths), 'segments': sum(len(p.coords) - 1 for p in paths)}))

    for method, handler in enumerate((geometry.clear_polygon_shrink, geometry.clear_polygon_seed,
                                      geometry.clear_polygon_lines)):
        for dia, overlap in ((0.4, 0.15), (0.2, 0.6)):
            label = f'method={method},dia={dia},overlap={overlap}'
            measure('generation,' + label, lambda: list(handler(
                board, dia, 64, overlap=overlap, connect=False).get_objects()))
            raw = list(handler(board, dia, 64, overlap=overlap, connect=False).get_objects())
            measure('connection,' + label, lambda: list(camlib.Geometry.paint_connect(
                storage_of(raw), board, dia, 64).get_objects()))
    for diameters in ([0.4], [0.8, 0.4]):
        def operation():
            worker, params = rest_worker(geometry, diameters)
            return run_rest(worker, params, [board], diameters)
        measure('rest,' + str(diameters), operation)


if __name__ == '__main__':
    import sys
    if '--benchmark' in sys.argv:
        benchmark()
    else:
        import unittest
        unittest.main()
