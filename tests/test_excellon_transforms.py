"""Excellon scale / offset / mirror / skew / rotate / buffer: the vectorized path must equal per element shapely."""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtWidgets  # noqa: E402
from shapely import Point, LineString, affinity  # noqa: E402

from appHandlers.appHistory import apply_matrix_to_object  # noqa: E402
from appObjects.ExcellonObject import ExcellonObject  # noqa: E402
from test_unify_characterization import make_app  # noqa: E402

_QAPP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

STEPS = 16


def _make(app):
    obj = ExcellonObject('exc', app)
    obj.units = 'MM'
    obj.tools = {
        1: {'tooldia': 0.8, 'drills': [Point(1, 2), Point(3.5, -4), Point(10, 10)], 'slots': [], 'solid_geometry': [],
            'data': {'cutz': -1.7}},
        2: {'tooldia': 1.2, 'drills': [Point(0, 0)], 'slots': [(Point(5, 5), Point(9, 6)), (Point(-2, 3), Point(4, 3))],
            'solid_geometry': [], 'data': {'cutz': -2.0}},
        3: {'tooldia': 2.0, 'drills': [], 'solid_geometry': [], 'data': {}},
    }
    assert obj.create_geometry() is None
    return obj


def _reference(obj, op, tooldia_fn=lambda d: d):
    """What the old code produced: transform each point with shapely.affinity, then a fresh per element buffer."""
    out = {}
    for key, tool in obj.tools.items():
        r = tooldia_fn(tool['tooldia']) / 2.0
        drills = [op(p) for p in tool['drills']]
        slots = [(op(a), op(b)) for a, b in tool.get('slots', [])]
        geo = [p.buffer(r, STEPS) for p in drills] + [LineString([a, b]).buffer(r, STEPS) for a, b in slots]
        out[key] = (drills, slots, geo)
    return out


class ExcellonTransformsTest(unittest.TestCase):
    def setUp(self):
        patcher = patch('appObjects.AppObjectTemplate.ShapeCollection')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = make_app()
        self.obj = _make(self.app)

    def check(self, ref):
        total = []
        for key, (drills, slots, geo) in ref.items():
            tool = self.obj.tools[key]
            self.assertEqual(len(tool['drills']), len(drills))
            for got, want in zip(tool['drills'], drills):
                self.assertTrue(got.equals_exact(want, 1e-9))
            self.assertEqual(len(tool.get('slots', [])), len(slots))
            for got, want in zip(tool.get('slots', []), slots):
                self.assertIs(type(got), tuple)
                self.assertTrue(got[0].equals_exact(want[0], 1e-9) and got[1].equals_exact(want[1], 1e-9))
            self.assertEqual(len(tool['solid_geometry']), len(geo))
            for got, want in zip(tool['solid_geometry'], geo):
                self.assertTrue(got.equals_exact(want, 1e-9))
            total.extend(geo)
        self.assertEqual(len(self.obj.solid_geometry), len(total))
        for got, want in zip(self.obj.solid_geometry, total):
            self.assertTrue(got.equals_exact(want, 1e-9))

    def test_create_geometry_matches_per_element_buffer(self):
        self.check(_reference(self.obj, lambda p: p))

    def test_rotate(self):
        ref = _reference(self.obj, lambda p: affinity.rotate(p, 30, origin=(5, 7)))
        self.obj.rotate(30, (5, 7))
        self.check(ref)

    def test_rotate_default_origin_is_bounds_center(self):
        minx, miny, maxx, maxy = self.obj.bounds()
        orig = ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
        ref = _reference(self.obj, lambda p: affinity.rotate(p, 45, origin=orig))
        self.obj.rotate(45)
        self.check(ref)

    def test_scale_moves_holes_keeps_diameters(self):
        ref = _reference(self.obj, lambda p: affinity.scale(p, 1.5, 0.5, origin=(1, 2)))
        self.obj.scale(1.5, 0.5, (1, 2))
        self.check(ref)
        self.assertEqual([t['tooldia'] for t in self.obj.tools.values()], [0.8, 1.2, 2.0])

    def test_scale_single_factor(self):
        ref = _reference(self.obj, lambda p: affinity.scale(p, 2, 2, origin=(0, 0)))
        self.obj.scale(2)
        self.check(ref)

    def test_skew(self):
        ref = _reference(self.obj, lambda p: affinity.skew(p, 10, 20, origin=(3, 4)))
        self.obj.skew(10, 20, (3, 4))
        self.check(ref)

    def test_mirror(self):
        for axis, (sx, sy) in (('X', (1, -1)), ('Y', (-1, 1))):
            obj = _make(self.app)
            ref = _reference(obj, lambda p: affinity.scale(p, sx, sy, origin=(2, 2)))
            self.obj = obj
            obj.mirror(axis, (2, 2))
            self.check(ref)

    def test_offset(self):
        ref = _reference(self.obj, lambda p: affinity.translate(p, 1.5, -2))
        self.obj.offset((1.5, -2))
        self.check(ref)

    def test_offset_zero_is_noop(self):
        before = [g.wkb for g in self.obj.solid_geometry]
        self.obj.offset((0, 0))
        self.assertEqual([g.wkb for g in self.obj.solid_geometry], before)

    def test_rigid_matrix_replay_keeps_aggregate_and_tools_in_sync(self):
        before = list(self.obj.solid_geometry)
        matrix = (0, -1, 1, 0, 4, 7)
        apply_matrix_to_object(self.obj, matrix)
        for got, original in zip(self.obj.solid_geometry, before):
            self.assertTrue(got.equals_exact(affinity.affine_transform(original, matrix), 1e-9))
        total = [g for tool in self.obj.tools.values() for g in tool['solid_geometry']]
        for aggregate, pertool in zip(self.obj.solid_geometry, total):
            self.assertTrue(aggregate.equals_exact(pertool, 1e-9))

    def test_buffer_distance_and_factor(self):
        ref = _reference(self.obj, lambda p: p, lambda d: d + 0.2)
        self.obj.buffer(0.1, 'round', False)
        self.check(ref)
        self.assertAlmostEqual(self.obj.tools[1]['tooldia'], 1.0)

        obj = _make(self.app)
        self.obj = obj
        ref = _reference(obj, lambda p: p, lambda d: d * 1.5)
        obj.buffer(1.5, 'round', True)
        self.check(ref)

    def test_data_kept(self):
        self.obj.rotate(10, (0, 0))
        self.assertEqual(self.obj.tools[1]['data'], {'cutz': -1.7})
        self.assertEqual(self.obj.tools[2]['data'], {'cutz': -2.0})

    def test_empty_tools(self):
        self.obj.tools = {}
        self.obj.offset((1, 1))
        self.obj.scale(2)
        self.obj.mirror('X', (0, 0))
        self.assertEqual(self.obj.solid_geometry, [])


if __name__ == '__main__':
    unittest.main()
