"""
camlib.Geometry / GeometryObject / CNCjob transforms (scale, mirror, rotate, skew): the vectorized versions give the
same coordinates as the shapely.affinity reference and keep the container shape.
"""

import os
import sys
import unittest
from types import SimpleNamespace

import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appObjects.GeometryObject import GeometryObject
from camlib import CNCjob, Geometry
from tests.helpers_objects import make_app_0b as make_app  # noqa: F401,E402


def sample():
    return [box(0, 0, 2, 3), None,
            [Polygon([(1, 1), (4, 1), (4, 5)]), [LineString([(0, 0, 1), (3, 4, 2)]), Point(2, 2)]],
            MultiPolygon([box(5, 5, 6, 6), box(7, 7, 9, 9)]),
            LineString([(0, 0, 5), (1, 1, 6), (2, 0, 7)])]


def reference(obj, fn, any_iterable):
    if type(obj) is list or (any_iterable and isinstance(obj, tuple)):
        return [reference(g, fn, any_iterable) for g in obj]
    if obj is None:
        return None
    return fn(obj)


def same(test, a, b):
    if isinstance(a, list):
        test.assertIsInstance(b, list)
        test.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            same(test, x, y)
    elif a is None:
        test.assertIsNone(b)
    else:
        test.assertEqual(type(a), type(b))
        test.assertEqual(shapely.has_z(a), shapely.has_z(b))
        test.assertTrue(shapely.equals_exact(a, b, tolerance=1e-9), (a.wkt, b.wkt))
        if shapely.has_z(a):
            test.assertEqual(shapely.get_coordinates(a, include_z=True).tolist().__len__(),
                             shapely.get_coordinates(b, include_z=True).tolist().__len__())
            for ca, cb in zip(shapely.get_coordinates(a, include_z=True), shapely.get_coordinates(b, include_z=True)):
                test.assertAlmostEqual(ca[2], cb[2], places=9)


def build(multigeo):
    geo = Geometry(make_app())
    geo.kind, geo.multigeo = 'geometry', multigeo
    geo.solid_geometry = sample()
    if multigeo:
        geo.tools = {1: {'solid_geometry': sample(), 'data': {}}, 2: {'solid_geometry': box(1, 1, 3, 3)},
                     3: {'solid_geometry': []}}
    return geo


OPS = {
    'rotate': (lambda g: g.rotate(30, (5, 7)), lambda s: affinity.rotate(s, 30, origin=(5, 7)), True),
    'skew': (lambda g: g.skew(10, 20, (3, 4)), lambda s: affinity.skew(s, 10, 20, origin=(3, 4)), True),
    'mirror_x': (lambda g: g.mirror('X', (2, 2)), lambda s: affinity.scale(s, 1, -1, origin=(2, 2)), False),
    'mirror_y': (lambda g: g.mirror('Y', (2, 2)), lambda s: affinity.scale(s, -1, 1, origin=(2, 2)), False),
    'obj_scale': (lambda g: GeometryObject.scale(g, 1.5, 0.5, (1, 2)),
                  lambda s: affinity.scale(s, 1.5, 0.5, origin=(1, 2)), False),
}


class TestGeometryTransforms(unittest.TestCase):

    def test_single_and_multigeo_match_shapely(self):
        for name, (op, ref, any_it) in OPS.items():
            for multigeo in (False, True):
                with self.subTest(op=name, multigeo=multigeo):
                    geo = build(multigeo)
                    op(geo)
                    same(self, reference(sample(), ref, any_it), geo.solid_geometry if not multigeo
                         else geo.tools[1]['solid_geometry'])
                    if multigeo:
                        same(self, ref(box(1, 1, 3, 3)), geo.tools[2]['solid_geometry'])
                        self.assertEqual(geo.tools[3]['solid_geometry'], [])
                        self.assertEqual(geo.tools[1]['data'], {})

    def test_multigeo_transforms_main_solid_geometry_too(self):
        geo = build(True)
        before = geo.solid_geometry
        geo.rotate(30, (0, 0))
        same(self, reference(before, lambda g: affinity.rotate(g, 30, origin=(0, 0)), True),
             geo.solid_geometry)

    def test_single_geometry_stays_single(self):
        geo = build(False)
        geo.solid_geometry = MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)])
        geo.rotate(45, (1, 1))
        self.assertIsInstance(geo.solid_geometry, MultiPolygon)
        same(self, affinity.rotate(MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)]), 45, origin=(1, 1)),
             geo.solid_geometry)

    def test_none_stays_none(self):
        geo = build(False)
        geo.solid_geometry = None
        geo.mirror('X', (0, 0))
        self.assertIsNone(geo.solid_geometry)

    def test_scale_by_one_is_a_noop(self):
        geo = build(False)
        before = geo.solid_geometry
        GeometryObject.scale(geo, 1, 1)
        self.assertIs(geo.solid_geometry, before)

    def test_cncjob_transforms(self):
        for name, method, ref in (
                ('rotate', lambda j: CNCjob.rotate(j, 30, (5, 7)), lambda s: affinity.rotate(s, 30, origin=(5, 7))),
                ('skew', lambda j: CNCjob.skew(j, 10, 20, (3, 4)),
                 lambda s: affinity.skew(s, 10, 20, origin=(3, 4))),
                ('mirror', lambda j: CNCjob.mirror(j, 'Y', (2, 2)),
                 lambda s: affinity.scale(s, -1, 1, origin=(2, 2)))):
            with self.subTest(op=name):
                geoms = [LineString([(0, 0), (3, 4)]), box(1, 1, 2, 2), Point(2, 2)]
                job = SimpleNamespace(
                    app=make_app(), gcode_parsed=[{'geom': g, 'kind': ['C', 'F']} for g in geoms],
                    create_geometry=lambda: None, _affine_gcode_parsed=CNCjob._affine_gcode_parsed)
                method(job)
                for d, g in zip(job.gcode_parsed, geoms):
                    same(self, ref(g), d['geom'])
                    self.assertEqual(d['kind'], ['C', 'F'])


if __name__ == '__main__':
    unittest.main()
