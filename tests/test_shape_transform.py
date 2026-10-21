#!/usr/bin/env python
"""
Tests for ShapeCollectionVisual.transform_keys(): the plot of a transformed object is made by mapping the stored
vertex arrays, with the same result as a new triangulation of the transformed geometry.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, LineString

from appGUI.VisPyVisuals import ShapeCollectionVisual, ShapeGroup

OPTS = {"global_graphic_engine_3d_no_mp": True, "global_backface_culling": True}


def new_collection():
    return ShapeCollectionVisual(linewidth=1, layers=3, pool=None, fcoptions=OPTS)


def sample_shapes():
    holed = Polygon([(0, 0), (10, 0), (10, 8), (0, 8)], [[(2, 2), (4, 2), (4, 4), (2, 4)]])
    tri = Polygon([(12, 1), (15, 1), (13, 5)])
    line = LineString([(0, 0), (3, 4), (6, 1)])
    return [holed, tri, line]


def to_affine(matrix, geo):
    return affinity.affine_transform(geo, matrix)


def sorted_pts(arr):
    arr = np.round(np.asarray(arr, dtype=np.float64), 3)
    return arr[np.lexsort((arr[:, 1], arr[:, 0]))]


def tri_area_signed(verts, tris):
    t = tris.reshape(-1, 3)
    p0, p1, p2 = verts[t[:, 0]], verts[t[:, 1]], verts[t[:, 2]]
    cross = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])
    return cross / 2.0


class TestTransformKeys(unittest.TestCase):
    def setUp(self):
        # the merge of the buffers into the GL visuals needs a canvas; only the stored arrays are tested here
        p = patch.object(ShapeCollectionVisual, '_ShapeCollectionVisual__update')
        p.start()
        self.addCleanup(p.stop)

    MATRICES = {
        'rotate': (0.0, -1.0, 1.0, 0.0, 0.0, 0.0),
        'rotate30': (np.cos(0.5236), -np.sin(0.5236), np.sin(0.5236), np.cos(0.5236), 3.0, -2.0),
        'mirror_x': (1.0, 0.0, 0.0, -1.0, 0.0, 20.0),
        'mirror_y': (-1.0, 0.0, 0.0, 1.0, 20.0, 0.0),
        'skew': (1.0, 0.5, 0.2, 1.0, 0.0, 0.0),
        'scale': (2.0, 0.0, 0.0, 3.0, 0.0, 0.0),
        'offset': (1.0, 0.0, 0.0, 1.0, 100.0, -50.0),
    }

    def build(self):
        c = new_collection()
        keys = c.add_batch([{'shape': s, 'color': 'red', 'face_color': 'blue'} for s in sample_shapes()])
        c.redraw([])
        return c, keys

    def test_matches_fresh_triangulation(self):
        for name, m in self.MATRICES.items():
            with self.subTest(name):
                c, keys = self.build()
                self.assertTrue(c.transform_keys(keys, m))

                ref = new_collection()
                rkeys = ref.add_batch([{'shape': to_affine(m, s), 'color': 'red', 'face_color': 'blue'}
                                       for s in sample_shapes()])
                ref.redraw([])

                for k, rk, shape in zip(keys, rkeys, sample_shapes()):
                    d, r = c.data[k], ref.data[rk]
                    self.assertEqual(d['line_pts'].dtype, np.float32)
                    self.assertEqual(d['line_pts'].shape, r['line_pts'].shape)
                    np.testing.assert_allclose(sorted_pts(d['line_pts']), sorted_pts(r['line_pts']), atol=2e-3)
                    if len(r['mesh_vertices']):
                        np.testing.assert_allclose(sorted_pts(d['mesh_vertices']), sorted_pts(r['mesh_vertices']),
                                                   atol=2e-3)
                        area = to_affine(m, shape).area
                        areas = tri_area_signed(d['mesh_vertices'].astype(np.float64), d['mesh_tris'])
                        ref_areas = tri_area_signed(r['mesh_vertices'].astype(np.float64), r['mesh_tris'])
                        # the winding is the same as that of a fresh triangulation: all the same sign
                        self.assertEqual(np.sign(areas.sum()), np.sign(ref_areas.sum()))
                        self.assertTrue(np.all(np.sign(areas) == np.sign(areas.sum())))
                        self.assertAlmostEqual(abs(areas.sum()), area, delta=1e-3 * max(1.0, area))
                    # colors are kept
                    self.assertEqual(d['mesh_colors'].shape, r['mesh_colors'].shape)
                    np.testing.assert_array_equal(d['line_colors'], r['line_colors'])

    def test_shared_arrays_untouched(self):
        c, keys = self.build()
        copy_key = c.add_copy(c, keys[0], color='green', face_color='yellow')
        before = {f: c.data[copy_key][f].copy() for f in ('line_pts', 'mesh_vertices', 'mesh_tris')}
        self.assertTrue(c.transform_keys(keys, self.MATRICES['mirror_x']))
        for f, arr in before.items():
            np.testing.assert_array_equal(c.data[copy_key][f], arr)
        self.assertFalse(np.array_equal(c.data[keys[0]]['line_pts'], before['line_pts']))

    def test_pending_pool_results_are_collected(self):
        class Res:
            def __init__(self, d):
                self.d = d

            def wait(self):
                pass

            def get(self):
                return self.d

        class Pool:
            def map_async(self, fn, items):
                return Res([fn(i) for i in items])

        c = ShapeCollectionVisual(linewidth=1, layers=3, pool=Pool(),
                                  fcoptions={"global_graphic_engine_3d_no_mp": False, "global_backface_culling": True})
        keys = c.add_batch([{'shape': s, 'color': 'red', 'face_color': 'blue'} for s in sample_shapes()])
        self.assertTrue(c.transform_keys(keys, self.MATRICES['offset']))
        self.assertGreater(len(c.data[keys[0]]['mesh_vertices']), 0)
        self.assertGreater(c.data[keys[0]]['line_pts'][:, 0].min(), 99.0)

    def test_untriangulated_returns_false(self):
        c = new_collection()
        keys = c.add_batch([{'shape': sample_shapes()[0], 'color': 'red', 'face_color': 'blue'}])
        c.data[keys[0]]['geometry'] = sample_shapes()[0]        # still to be processed
        self.assertFalse(c.transform_keys(keys, self.MATRICES['offset']))

    def test_group_transform(self):
        c = new_collection()
        g = ShapeGroup(c)
        other = c.add_batch([{'shape': sample_shapes()[1], 'color': 'red', 'face_color': 'blue'}])
        keys = g.add_batch([{'shape': sample_shapes()[1], 'color': 'red', 'face_color': 'blue'}])
        before = c.data[other[0]]['line_pts'].copy()
        self.assertTrue(g.transform(self.MATRICES['offset']))
        np.testing.assert_array_equal(c.data[other[0]]['line_pts'], before)
        self.assertGreater(c.data[keys[0]]['line_pts'][:, 0].min(), 99.0)

    def test_benchmark(self):
        n = 20000
        shapes = [Polygon([(i % 200, i // 200), (i % 200 + 0.8, i // 200), (i % 200 + 0.8, i // 200 + 0.8),
                           (i % 200, i // 200 + 0.8)]) for i in range(n)]
        c = new_collection()
        keys = c.add_batch([{'shape': s, 'color': 'red', 'face_color': 'blue'} for s in shapes])
        c.redraw([])

        t0 = time.perf_counter()
        self.assertTrue(c.transform_keys(keys, self.MATRICES['mirror_x']))
        t_fast = time.perf_counter() - t0

        t0 = time.perf_counter()
        c.clear()
        c.add_batch([{'shape': to_affine(self.MATRICES['mirror_x'], s), 'color': 'red', 'face_color': 'blue'}
                     for s in shapes])
        c.redraw([])
        t_full = time.perf_counter() - t0
        print("\n[bench] %d polygons: transform_keys %.3f s, clear+add_batch+redraw %.3f s (x%.0f)" %
              (n, t_fast, t_full, t_full / max(t_fast, 1e-9)))


if __name__ == '__main__':
    unittest.main()
