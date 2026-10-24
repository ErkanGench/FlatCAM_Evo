#!/usr/bin/env python
"""
Automated tests for VisPy batch processing optimizations (Phase 2).

Tests cover:
1. add_batch() functionality
2. Synchronous add() behavior
3. Backface culling configuration
4. redraw() batch result collection
5. _collect_elements() method
6. Edge cases (empty batches, missing fc_options, etc.)

Run: python tests/test_vispy_batch.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import numpy as np
from unittest.mock import patch
from shapely.geometry import Polygon, LineString, MultiPolygon


class TestShapeCollectionVisualBatch(unittest.TestCase):
    """Tests for ShapeCollectionVisual batch processing."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Import after path setup
        from appGUI.VisPyVisuals import ShapeCollectionVisual, _update_shape_buffers
        self.ShapeCollectionVisual = ShapeCollectionVisual
        self._update_shape_buffers = _update_shape_buffers
        
        # Mock fc_options with all required keys
        self.default_fc_options = {
            "global_graphic_engine_3d_no_mp": False,
            "global_backface_culling": True,
        }
    
    def test_add_batch_single_shape(self):
        """Test add_batch() with a single shape."""
        collection = self.ShapeCollectionVisual(
            linewidth=1,
            layers=3,
            pool=None,
            fcoptions=self.default_fc_options
        )
        
        shapes_data = [{
            'shape': Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            'color': 'red',
            'face_color': 'blue'
        }]
        
        result = collection.add_batch(shapes_data, visible=True)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(len(collection.data), 1)
        self.assertIn(result[0], collection.data)
        self.assertEqual(collection.data[result[0]]['color'], 'red')
        self.assertEqual(collection.data[result[0]]['face_color'], 'blue')
        self.assertTrue(collection.data[result[0]]['visible'])
    
    def test_add_batch_per_shape_layer_override(self):
        """Test add_batch() allows per-shape layer override."""
        collection = self.ShapeCollectionVisual(
            linewidth=1,
            layers=3,
            pool=None,
            fcoptions=self.default_fc_options
        )
        
        shapes_data = [
            {'shape': Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), 'layer': 1},
            {'shape': Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]), 'layer': 2},
        ]
        
        result = collection.add_batch(shapes_data, layer=0)

        # Per-shape layer should override default
        self.assertEqual(collection.data[result[0]]['layer'], 1)
        self.assertEqual(collection.data[result[1]]['layer'], 2)
    
class TestCollectElements(unittest.TestCase):
    """Tests for GeometryObject._collect_elements() method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from appObjects.GeometryObject import GeometryObject
        # Can't fully instantiate without app, so we'll test the method directly
        self.GeometryObject = GeometryObject
    
    def test_collect_elements_single_polygon(self):
        """Test _collect_elements with a single Polygon."""
        from appObjects.GeometryObject import GeometryObject
        
        # Create a mock object with just the method we need
        class MockGeo:
            pass
        
        mock_geo = MockGeo()
        mock_geo._collect_elements = GeometryObject._collect_elements.__get__(mock_geo, GeometryObject)
        
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        result = mock_geo._collect_elements(poly, color='red')
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['shape'], poly)
        self.assertEqual(result[0]['color'], 'red')
        self.assertEqual(result[0]['layer'], GeometryObject.PLOT_LAYER)
    
    def test_collect_elements_multi_polygon(self):
        """Test _collect_elements with a MultiPolygon."""
        from appObjects.GeometryObject import GeometryObject
        
        class MockGeo:
            pass
        
        mock_geo = MockGeo()
        mock_geo._collect_elements = GeometryObject._collect_elements.__get__(mock_geo, GeometryObject)
        
        poly1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        poly2 = Polygon([(2, 0), (3, 0), (3, 1), (2, 1)])
        multi = MultiPolygon([poly1, poly2])
        
        result = mock_geo._collect_elements(multi, color='blue')
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['color'], 'blue')
        self.assertEqual(result[1]['color'], 'blue')
    
class TestAddCopy(unittest.TestCase):
    """add_copy() reuses the position buffers of a shape and makes new color buffers."""

    def setUp(self):
        from appGUI.VisPyVisuals import ShapeCollectionVisual
        options = {"global_graphic_engine_3d_no_mp": True, "global_backface_culling": True}
        self.source = ShapeCollectionVisual(linewidth=1, layers=1, pool=None, fcoptions=options)
        self.target = ShapeCollectionVisual(linewidth=1, layers=1, pool=None, fcoptions=options)
        # no GL canvas in the tests
        patcher = patch('appGUI.VisPyVisuals.set_state')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_polygon_copy_shares_positions_and_has_new_colors(self):
        poly = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)], [[(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]])
        key = self.source.add(shape=poly, color='#112233FF', face_color='#11223350', layer=0)
        copy_key = self.target.add_copy(self.source, key, color='#FF0000FF', face_color='#00FF0050', linewidth=3)

        src, dst = self.source.data[key], self.target.data[copy_key]
        for name in ('line_pts', 'mesh_vertices', 'mesh_tris'):
            self.assertIs(dst[name], src[name])
        self.assertGreater(len(dst['mesh_tris']), 0)
        self.assertTrue(dst['visible'])
        self.assertEqual(self.target._line_width, 3)
        self.assertTrue(self.target._dirty)
        self.target.redraw([])
        line_colors = self.target._lines[0]._color
        mesh_colors = self.target._meshes[0].mesh_data.get_face_colors()
        self.assertEqual(line_colors.dtype.name, 'float32')
        self.assertEqual(line_colors.shape, (len(dst['line_pts']), 4))
        np.testing.assert_array_equal(line_colors, np.tile([1.0, 0.0, 0.0, 1.0], (len(dst['line_pts']), 1)))
        self.assertEqual(mesh_colors.shape, (len(dst['mesh_tris']) // 3, 4))
        self.assertTrue(np.all(mesh_colors[:, :3] == (0.0, 1.0, 0.0)))
        # the source keeps its own colors
        self.source.redraw([])
        np.testing.assert_allclose(self.source._lines[0]._color[0], (0x11 / 255, 0x22 / 255, 0x33 / 255, 1.0))

    def test_line_copy_has_no_mesh(self):
        key = self.source.add(shape=LineString([(0, 0), (1, 1), (2, 0)]), color='#112233FF', layer=0)
        copy_key = self.target.add_copy(self.source, key, color='#FF0000FF', face_color='#FF000050')
        dst = self.target.data[copy_key]
        self.target.redraw([])
        self.assertFalse(self.target._meshes[0].visible)
        self.assertEqual(len(self.target._lines[0]._color), len(dst['line_pts']))

    def test_two_shapes_get_their_own_color_per_vertex(self):
        collection = self.source
        line = LineString([(0, 0), (1, 1), (2, 0)])
        square = Polygon([(5, 0), (6, 0), (6, 1), (5, 1)])
        collection.add(shape=line, color='#FF0000FF', layer=0)
        collection.add(shape=square, color='#0000FFFF', face_color='#00FF00FF', layer=0)
        collection.redraw([])
        colors = collection._lines[0]._color
        n_line = 4
        self.assertEqual(colors.dtype.name, 'float32')
        self.assertEqual(colors.shape, (n_line + 8, 4))
        self.assertTrue(np.all(colors[:n_line] == (1.0, 0.0, 0.0, 1.0)))
        self.assertTrue(np.all(colors[n_line:] == (0.0, 0.0, 1.0, 1.0)))
        mesh_colors = collection._meshes[0].mesh_data.get_face_colors()
        self.assertEqual(len(mesh_colors), 2)
        self.assertTrue(np.all(mesh_colors == (0.0, 1.0, 0.0, 1.0)))

    def test_update_color_changes_the_painted_shapes(self):
        collection = self.source
        k0 = collection.add(shape=LineString([(0, 0), (1, 1)]), color='#FF0000FF', layer=0)
        collection.add(shape=LineString([(2, 0), (3, 1)]), color='#FF0000FF', layer=0)
        collection.redraw([])
        collection.update_color(new_line_color='#0000FFFF', indexes=[k0])
        collection.redraw([])
        colors = collection._lines[0]._color
        self.assertTrue(np.all(colors[:2] == (0.0, 0.0, 1.0, 1.0)))
        self.assertTrue(np.all(colors[2:] == (1.0, 0.0, 0.0, 1.0)))

class TestDeferredRedraw(unittest.TestCase):
    """A deferred collection joins a burst of redraws into few rebuilds."""

    def setUp(self):
        from appGUI.VisPyVisuals import ShapeCollectionVisual
        options = {"global_graphic_engine_3d_no_mp": True, "global_backface_culling": True}
        self.collection = ShapeCollectionVisual(linewidth=1, layers=1, pool=None, fcoptions=options, deferred=True)
        self.rebuilds = 0
        patcher = patch('appGUI.VisPyVisuals.set_state', side_effect=self._count)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _count(self, **kwargs):
        self.rebuilds += 1

    def _burst(self, count):
        from appGUI.VisPyVisuals import ShapeGroup
        for i in range(count):
            group = ShapeGroup(self.collection)
            group.add(shape=Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)]), color='#112233FF',
                      face_color='#11223350', layer=0)
            group.redraw()

    def test_burst_gives_final_buffers_and_fewer_rebuilds(self):
        self._burst(20)
        self.collection.flush()
        self.assertEqual(len(self.collection._meshes[0].mesh_data.get_vertices()), 20 * 4)
        self.assertEqual(len(self.collection._lines[0]._pos), 20 * 8)
        self.assertLess(self.rebuilds, 20)

    def test_redraw_alone_is_applied_by_the_updater(self):
        import time
        self._burst(3)
        deadline = time.monotonic() + 3
        while self.collection._dirty and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.collection._dirty)
        self.assertEqual(len(self.collection._meshes[0].mesh_data.get_vertices()), 12)

    def test_flush_applies_at_once(self):
        self._burst(2)
        self.collection.flush()
        self.assertFalse(self.collection._dirty)
        self.assertEqual(len(self.collection._meshes[0].mesh_data.get_vertices()), 8)

    def test_update_colors_is_synchronous(self):
        self._burst(2)
        self.collection.flush()
        keys = list(self.collection.data)
        self.collection.redraw(keys, update_colors=('#00FF00FF', '#0000FFFF'))
        colors = self.collection._lines[0]._color
        self.assertTrue(np.all(colors == (0.0, 0.0, 1.0, 1.0)))


if __name__ == '__main__':
    unittest.main()
