"""Paint output tolerance is stored in mm and converted once for inch geometry."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from test_paint_performance import rest_worker
from test_paint_geometry import PaintGen, storage_of
from defaults import AppDefaults, AppOptions
from shapely import LineString, box


class TestPaintSimplification(unittest.TestCase):
    def test_normal_and_rest_use_configured_tolerance_in_geometry_units(self):
        for units, scale in (('MM', 1), ('IN', 1 / 25.4)):
            for tolerance in (0, 0.001, 0.02):
                for rest in (False, True):
                    with self.subTest(units=units, tolerance=tolerance, rest=rest):
                        app = SimpleNamespace(abort_flag=False, log=Mock(), inform=Mock(),
                                              proc_container=Mock(), units=units,
                                              options={'tools_paint_simplification': tolerance})
                        worker, initial = rest_worker(SimpleNamespace(app=app), [scale])
                        worker.obj_name = 'paint'
                        worker.paint_tools = initial.tools_storage
                        params = worker._create_params(0, 2, rest, 'paint', None, False)
                        self.assertAlmostEqual(params.simplification_value, tolerance * scale)
                        path = LineString([(scale, scale), (2 * scale, 1.01 * scale),
                                           (3 * scale, scale)])
                        worker._process_polygon = Mock(side_effect=lambda *args: storage_of([path]))
                        output = SimpleNamespace(tools={}, obj_options={})
                        generate = worker._generate_rest_paint_worker if rest else worker._generate_paint_worker
                        result = generate(output, app, params, [scale], [box(0, 0, 6 * scale, 6 * scale)],
                                          None, False)
                        self.assertNotEqual(result, 'fail')
                        actual = output.tools[1]['solid_geometry'][0]
                        expected = path.simplify(tolerance * scale) if tolerance else path
                        self.assertEqual(actual.wkb, expected.wkb)
                        self.assertEqual(len(actual.coords), 2 if tolerance == 0.02 else 3)

if __name__ == '__main__':
    unittest.main()
