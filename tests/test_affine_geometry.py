import os
import sys
import time
import unittest

import pytest
import shapely.affinity as affinity
from shapely.geometry import (Point, LineString, LinearRing, Polygon, MultiPolygon, MultiLineString,
                              GeometryCollection, MultiPoint)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import camlib  # noqa: E402
from camlib import (affine_geometry, affine_geometry_many, affine_rotate_matrix, affine_scale_matrix,  # noqa: E402
                    affine_skew_matrix, affine_mirror_matrix, affine_translate_matrix, map_geometry)

ORIGIN = (3.5, -2.25)

CASES = [
    ('rotate', lambda g: affinity.rotate(g, 37.0, origin=ORIGIN), affine_rotate_matrix(37.0, ORIGIN)),
    ('rotate90', lambda g: affinity.rotate(g, 90.0, origin=ORIGIN), affine_rotate_matrix(90.0, ORIGIN)),
    ('scale', lambda g: affinity.scale(g, 1.7, 0.4, origin=ORIGIN), affine_scale_matrix(1.7, 0.4, ORIGIN)),
    ('skew', lambda g: affinity.skew(g, 12.0, -7.0, origin=ORIGIN), affine_skew_matrix(12.0, -7.0, ORIGIN)),
    ('mirror_x', lambda g: affinity.scale(g, 1.0, -1.0, origin=ORIGIN), affine_mirror_matrix('X', ORIGIN)),
    ('mirror_y', lambda g: affinity.scale(g, -1.0, 1.0, origin=ORIGIN), affine_mirror_matrix('Y', ORIGIN)),
    ('translate', lambda g: affinity.translate(g, 4.0, -9.5), affine_translate_matrix(4.0, -9.5)),
]


def make_geoms():
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (4, 2), (4, 4), (2, 4)]])
    return {
        'point': Point(1, 2),
        'line': LineString([(0, 0), (1, 1), (5, 2)]),
        'ring': LinearRing([(0, 0), (1, 0), (1, 1), (0, 0)]),
        'poly_holes': poly,
        'multipoly': MultiPolygon([poly, Polygon([(20, 20), (21, 20), (21, 21)])]),
        'multiline': MultiLineString([[(0, 0), (1, 1)], [(5, 5), (6, 7)]]),
        'multipoint': MultiPoint([(0, 0), (3, 4)]),
        'collection': GeometryCollection([Point(1, 1), LineString([(0, 0), (2, 2)]), poly]),
        'line3d': LineString([(0, 0, 5), (1, 1, 6), (5, 2, 7)]),
        'empty': Polygon(),
    }


class TestAffineGeometry(unittest.TestCase):

    def assert_same(self, got, exp):
        if exp is None:
            self.assertIsNone(got)
            return
        if isinstance(exp, list):
            self.assertIsInstance(got, list)
            self.assertEqual(len(got), len(exp))
            for g, e in zip(got, exp):
                self.assert_same(g, e)
            return
        if not hasattr(exp, 'geom_type'):
            self.assertIs(got, exp)
            return
        self.assertEqual(got.geom_type, exp.geom_type)
        self.assertEqual(got.has_z, exp.has_z)
        if exp.is_empty:
            self.assertTrue(got.is_empty)
        else:
            self.assertTrue(got.equals_exact(exp, 1e-9), '%s != %s' % (got.wkt, exp.wkt))
            if exp.has_z:
                self.assertEqual(got.wkt.count(' '), exp.wkt.count(' '))

    def test_single_geometries(self):
        for name, ref, matrix in CASES:
            for gname, g in make_geoms().items():
                with self.subTest(op=name, geom=gname):
                    self.assert_same(affine_geometry(g, matrix), ref(g))

    def test_z_is_kept(self):
        g = LineString([(0, 0, 5), (1, 1, 6), (5, 2, 7)])
        out = affine_geometry(g, affine_rotate_matrix(30, ORIGIN))
        self.assertTrue(out.has_z)
        self.assertEqual([c[2] for c in out.coords], [5, 6, 7])

    def test_mixed_2d_3d_list_order(self):
        geoms = [Point(1, 1), LineString([(0, 0, 1), (1, 1, 2)]), Point(2, 2)]
        m = affine_scale_matrix(2, 3, ORIGIN)
        out = affine_geometry(geoms, m)
        self.assert_same(out, [affinity.scale(g, 2, 3, origin=ORIGIN) for g in geoms])

    def test_none_and_non_geometry(self):
        m = affine_translate_matrix(1, 1)
        self.assertIsNone(affine_geometry(None, m))
        self.assertEqual(affine_geometry(5, m), 5)
        self.assertEqual(affine_geometry('x', m), 'x')
        self.assertEqual(affine_geometry([], m), [])

    def test_nested_and_mixed_lists(self):
        g = make_geoms()
        obj = [g['poly_holes'], [g['line'], None, [g['point'], g['multipoly']]], None, 7, g['collection'], []]
        for name, ref, matrix in CASES:
            with self.subTest(op=name):
                self.assert_same(affine_geometry(obj, matrix), map_geometry(obj, ref))

    def test_identity_returns_same_object(self):
        g = Point(1, 2)
        self.assertIs(affine_geometry(g, (1, 0, 0, 1, 0, 0)), g)
        lst = [g]
        self.assertIs(affine_geometry(lst, (1, 0, 0, 1, 0, 0)), lst)

    def test_input_not_modified(self):
        p = Polygon([(0, 0), (1, 0), (1, 1)])
        wkt = p.wkt
        affine_geometry([p], affine_rotate_matrix(45, ORIGIN))
        self.assertEqual(p.wkt, wkt)

    def test_any_iterable(self):
        g = make_geoms()
        out = affine_geometry((g['point'], [g['line']]), affine_translate_matrix(1, 2), any_iterable=True)
        self.assertIsInstance(out, list)
        self.assert_same(out, [affinity.translate(g['point'], 1, 2), [affinity.translate(g['line'], 1, 2)]])
        # without any_iterable a tuple is not walked
        tup = (g['point'],)
        self.assertIs(affine_geometry(tup, affine_translate_matrix(1, 2)), tup)

    def test_many(self):
        g = make_geoms()
        structs = [g['poly_holes'], [g['line'], [g['point']]], None, [g['line3d']]]
        m = affine_skew_matrix(5, 9, ORIGIN)
        out = affine_geometry_many(structs, m)
        self.assertEqual(len(out), 4)
        for o, s in zip(out, structs):
            self.assert_same(o, map_geometry(s, lambda x: affinity.skew(x, 5, 9, origin=ORIGIN)))

    def test_mirror_axis_convention(self):
        # axis "X": Y is flipped, axis "Y": X is flipped (same as Gerber.mirror / Geometry.mirror)
        p = Point(2, 3)
        self.assertEqual(tuple(affine_geometry(p, affine_mirror_matrix('X', (0, 0))).coords[0]), (2, -3))
        self.assertEqual(tuple(affine_geometry(p, affine_mirror_matrix('Y', (0, 0))).coords[0]), (-2, 3))


@pytest.mark.slow
class TestAffineBenchmark(unittest.TestCase):

    def test_benchmark(self):
        polys = [Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)], [[(i + .2, .2), (i + .4, .2), (i + .4, .4)]])
                 for i in range(20000)]
        o = (5.0, 5.0)
        t0 = time.perf_counter()
        old = map_geometry(polys, lambda g: affinity.rotate(g, 33.0, origin=o))
        t1 = time.perf_counter()
        new = affine_geometry(polys, affine_rotate_matrix(33.0, o))
        t2 = time.perf_counter()
        print('\nrotate 20000 polygons: map_geometry+affinity %.3fs, affine_geometry %.3fs (x%.1f)'
              % (t1 - t0, t2 - t1, (t1 - t0) / max(t2 - t1, 1e-9)))
        self.assertTrue(old[123].equals_exact(new[123], 1e-9))


if __name__ == '__main__':
    unittest.main()
