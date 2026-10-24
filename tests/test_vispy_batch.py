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
        line_colors = self.target.layer_visuals(0)[1][0]._color
        mesh_colors = self.target.layer_visuals(0)[0][0].mesh_data.get_face_colors()
        self.assertEqual(line_colors.dtype.name, 'float32')
        self.assertEqual(line_colors.shape, (len(dst['line_pts']), 4))
        np.testing.assert_array_equal(line_colors, np.tile([1.0, 0.0, 0.0, 1.0], (len(dst['line_pts']), 1)))
        self.assertEqual(mesh_colors.shape, (len(dst['mesh_tris']) // 3, 4))
        self.assertTrue(np.all(mesh_colors[:, :3] == (0.0, 1.0, 0.0)))
        # the source keeps its own colors
        self.source.redraw([])
        np.testing.assert_allclose(self.source.layer_visuals(0)[1][0]._color[0], (0x11 / 255, 0x22 / 255, 0x33 / 255, 1.0))

    def test_line_copy_has_no_mesh(self):
        key = self.source.add(shape=LineString([(0, 0), (1, 1), (2, 0)]), color='#112233FF', layer=0)
        copy_key = self.target.add_copy(self.source, key, color='#FF0000FF', face_color='#FF000050')
        dst = self.target.data[copy_key]
        self.target.redraw([])
        self.assertEqual(self.target.layer_visuals(0)[0], [])
        self.assertEqual(len(self.target.layer_visuals(0)[1][0]._color), len(dst['line_pts']))

    def test_two_shapes_get_their_own_color_per_vertex(self):
        collection = self.source
        line = LineString([(0, 0), (1, 1), (2, 0)])
        square = Polygon([(5, 0), (6, 0), (6, 1), (5, 1)])
        collection.add(shape=line, color='#FF0000FF', layer=0)
        collection.add(shape=square, color='#0000FFFF', face_color='#00FF00FF', layer=0)
        collection.redraw([])
        colors = collection.layer_visuals(0)[1][0]._color
        n_line = 4
        self.assertEqual(colors.dtype.name, 'float32')
        self.assertEqual(colors.shape, (n_line + 8, 4))
        self.assertTrue(np.all(colors[:n_line] == (1.0, 0.0, 0.0, 1.0)))
        self.assertTrue(np.all(colors[n_line:] == (0.0, 0.0, 1.0, 1.0)))
        mesh_colors = collection.layer_visuals(0)[0][0].mesh_data.get_face_colors()
        self.assertEqual(len(mesh_colors), 2)
        self.assertTrue(np.all(mesh_colors == (0.0, 1.0, 0.0, 1.0)))

    def test_update_color_changes_the_painted_shapes(self):
        collection = self.source
        k0 = collection.add(shape=LineString([(0, 0), (1, 1)]), color='#FF0000FF', layer=0)
        collection.add(shape=LineString([(2, 0), (3, 1)]), color='#FF0000FF', layer=0)
        collection.redraw([])
        collection.update_color(new_line_color='#0000FFFF', indexes=[k0])
        collection.redraw([])
        colors = collection.layer_visuals(0)[1][0]._color
        self.assertTrue(np.all(colors[:2] == (0.0, 0.0, 1.0, 1.0)))
        self.assertTrue(np.all(colors[2:] == (1.0, 0.0, 0.0, 1.0)))

class TestGroupBuckets(unittest.TestCase):
    """Every ShapeGroup has its own visuals: a change of one group does not upload the other groups."""

    def setUp(self):
        from appGUI.VisPyVisuals import ShapeCollectionVisual, ShapeGroup
        options = {"global_graphic_engine_3d_no_mp": True, "global_backface_culling": True}
        self.collection = ShapeCollectionVisual(linewidth=1, layers=3, pool=None, fcoptions=options)
        patcher = patch('appGUI.VisPyVisuals.set_state')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.groups = [ShapeGroup(self.collection) for _ in range(3)]
        for i, group in enumerate(self.groups):
            self.plot(group, i)
        self.collection.redraw([])

    @staticmethod
    def plot(group, x):
        group.add_batch([{'shape': Polygon([(x, 0), (x + 1, 0), (x + 1, 1), (x, 1)]), 'color': '#FF0000FF',
                          'face_color': '#00FF00FF', 'layer': layer} for layer in (0, 1)])

    def count_set_data(self):
        """Count the set_data() calls per visual from now on."""
        from vispy.visuals import MeshVisual, LineVisual
        calls = {}
        for cls in (MeshVisual, LineVisual):
            original = cls.set_data

            def wrapper(visual, *args, _original=original, **kwargs):
                calls[visual] = calls.get(visual, 0) + 1
                return _original(visual, *args, **kwargs)

            patcher = patch.object(cls, 'set_data', wrapper)
            patcher.start()
            self.addCleanup(patcher.stop)
        return calls

    def test_change_of_one_group_uploads_only_this_group(self):
        calls = self.count_set_data()
        untouched = [v for layer in (0, 1) for vs in self.collection.layer_visuals(layer) for v in vs]
        self.groups[1].clear()
        self.plot(self.groups[1], 1)
        self.collection.redraw([])
        # only the new visuals of the group (mesh and line of two layers) get data
        self.assertEqual(len(calls), 4)
        self.assertEqual(len([v for v in untouched if v in calls]), 0)
        uploads = sum(calls.values())
        self.collection.redraw([])
        self.assertEqual(sum(calls.values()), uploads)      # nothing is dirty: no upload

    def test_layers_hold_the_shapes_of_all_groups_and_the_replotted_group_draws_last(self):
        self.groups[0].clear()
        self.plot(self.groups[0], 0)
        self.collection.redraw([])
        for layer in (0, 1):
            lines = self.collection.layer_visuals(layer)[1]
            self.assertEqual(len(lines), 3)
            xs = [v._pos[0][0] for v in lines]
            self.assertEqual(xs, [1, 2, 0])                  # group 0 was plotted again: last
        self.assertEqual(self.collection.layer_visuals(2), ([], []))

        # draw order of the scene: layer 0 (meshes, lines), layer 1, then the top overlay
        order = [(v in self.collection.layer_visuals(0)[0] + self.collection.layer_visuals(0)[1],
                  v in self.collection.layer_visuals(1)[0] + self.collection.layer_visuals(1)[1])
                 for v in self.collection._subvisuals]
        self.assertEqual(order, [(True, False)] * 6 + [(False, True)] * 6 + [(False, False)] * 2)
        self.assertEqual(self.collection._subvisuals[-2:], [self.collection._top_mesh, self.collection._top_line])

    def test_empty_group_removes_its_visuals(self):
        count = len(self.collection._subvisuals)
        self.groups[2].clear()
        self.collection.redraw([])
        self.assertEqual(len(self.collection._subvisuals), count - 4)

    def test_top_group_leaves_its_layers_and_goes_to_the_overlay(self):
        self.groups[1].move_to_top()
        self.assertEqual(len(self.collection.layer_visuals(0)[1]), 2)
        self.assertEqual(len(self.collection._top_line._pos), 16)       # two squares
        self.groups[1].clear()
        self.collection.redraw([])
        self.assertFalse(self.collection._top_line.visible)

    def test_color_change_affects_only_the_given_shapes(self):
        keys = self.groups[0]._indexes
        other = self.collection.layer_visuals(0)[1][1]
        before = other._color
        self.groups[0].redraw(update_colors=('#0000FFFF', '#FFFFFFFF'))
        first = self.collection.layer_visuals(0)[1][0]
        self.assertTrue(np.all(first._color == (1.0, 1.0, 1.0, 1.0)))
        self.assertIs(other._color, before)
        self.assertTrue(np.all(self.collection.layer_visuals(0)[0][0].mesh_data.get_face_colors() == (0, 0, 1, 1)))
        self.assertEqual(self.collection.data[keys[0]]['color'], '#FFFFFFFF')
        self.assertEqual(self.collection.data[self.groups[1]._indexes[0]]['color'], '#FF0000FF')


if __name__ == '__main__':
    unittest.main()
