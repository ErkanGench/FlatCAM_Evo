"""
Geometry must draw on the top canvas layer (above the filled Gerber), and keep the visible flag.
"""

import sys
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from shapely.geometry import LineString, MultiLineString

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_obj(plot=True):
    from appObjects.GeometryObject import GeometryObject
    obj = SimpleNamespace(
        obj_options={'plot': plot, 'multicolored': False},
        multigeo=False,
        solid_geometry=MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]),
        random_color=lambda: '#00FF00FF',
        _app_option=lambda name: '#112233FF',
        shapes=mock.Mock(),
        add_shapes_batch=mock.Mock(),
        add_shape=mock.Mock(),
        mark_full_plot=mock.Mock(),
        PLOT_LAYER=GeometryObject.PLOT_LAYER,
    )
    obj._collect_elements = GeometryObject._collect_elements.__get__(obj)
    obj.plot_element = GeometryObject.plot_element.__get__(obj)
    obj.plot = GeometryObject.plot.__get__(obj)
    return obj


class TestGeometryPlotLayer(unittest.TestCase):

    def test_plot_batch_layer(self):
        obj = _make_obj()
        with mock.patch('appObjects.GeometryObject.FlatCAMObj.plot', return_value=True):
            obj.plot()
        batch = obj.add_shapes_batch.call_args[0][0]
        self.assertEqual(len(batch), 2)
        self.assertTrue(all(item['layer'] == 2 for item in batch))
        self.assertIs(obj.add_shapes_batch.call_args[1]['visible'], True)

    def test_plot_visible_false_kept(self):
        obj = _make_obj(plot=True)
        with mock.patch('appObjects.GeometryObject.FlatCAMObj.plot', return_value=True):
            obj.plot(visible=False)
        self.assertIs(obj.add_shapes_batch.call_args[1]['visible'], False)

    def test_plot_visible_none_uses_option(self):
        obj = _make_obj(plot=False)
        with mock.patch('appObjects.GeometryObject.FlatCAMObj.plot', return_value=True):
            obj.plot()
        self.assertIs(obj.add_shapes_batch.call_args[1]['visible'], False)

    def test_plot_element_layer(self):
        obj = _make_obj()
        obj.plot_element(LineString([(0, 0), (1, 1)]))
        self.assertEqual(obj.add_shape.call_args[1]['layer'], 2)

    def test_plot_element_nested(self):
        obj = _make_obj()
        obj.plot_element([MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]), LineString([(5, 5), (6, 6)])],
                         visible=False)
        self.assertEqual(obj.add_shape.call_count, 3)
        for call in obj.add_shape.call_args_list:
            self.assertEqual(call[1]['layer'], 2)
            self.assertIs(call[1]['visible'], False)

    def test_plot_element_visible_none(self):
        obj = _make_obj(plot=False)
        obj.plot_element(MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]))
        for call in obj.add_shape.call_args_list:
            self.assertIs(call[1]['visible'], False)


if __name__ == '__main__':
    unittest.main()
