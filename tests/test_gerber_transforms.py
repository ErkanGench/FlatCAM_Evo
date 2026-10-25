"""Gerber.rotate / scale / skew / mirror / offset use one vectorized affine call; compare with shapely.affinity."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shapely
import shapely.affinity as affinity
from shapely.geometry.base import BaseGeometry

from appParsers.ParseGerber import Gerber
from test_gerber_parser import MockApp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = [os.path.join(ROOT, 'tests', 'fixtures', 'altium', 'Gerber', 'I2C_level_shifter.GTL')]

OPS = {
    'rotate': (lambda g: g.rotate(30, [5, 7]), lambda o: affinity.rotate(o, 30, origin=(5, 7))),
    'scale': (lambda g: g.scale(1.5, 0.5, (1, 2)), lambda o: affinity.scale(o, 1.5, 0.5, origin=(1, 2))),
    'skew': (lambda g: g.skew(10, 20, [3, 4]), lambda o: affinity.skew(o, 10, 20, origin=(3, 4))),
    'mirrorX': (lambda g: g.mirror('X', [2, 2]), lambda o: affinity.scale(o, 1.0, -1.0, origin=(2, 2))),
    'mirrorY': (lambda g: g.mirror('Y', [2, 2]), lambda o: affinity.scale(o, -1.0, 1.0, origin=(2, 2))),
    'offset': (lambda g: g.offset((1.5, -2)), lambda o: affinity.translate(o, 1.5, -2)),
}


def load(path):
    g = Gerber(MockApp())
    g.parse_file(path)
    return g


def ref_map(obj, fn):
    if isinstance(obj, list):
        return [ref_map(x, fn) for x in obj]
    if isinstance(obj, BaseGeometry):
        return fn(obj)
    return obj


def check_same(tc, got, ref):
    if isinstance(ref, list):
        tc.assertIsInstance(got, list)
        tc.assertEqual(len(got), len(ref))
        for a, b in zip(got, ref):
            check_same(tc, a, b)
    elif isinstance(ref, BaseGeometry):
        tc.assertIs(type(got), type(ref))
        tc.assertEqual(got.is_empty, ref.is_empty)
        if not ref.is_empty:
            tc.assertTrue(shapely.equals_exact(got, ref, tolerance=1e-9), (got.wkt[:80], ref.wkt[:80]))
    else:
        tc.assertEqual(got, ref)


def all_structures(g):
    yield g.solid_geometry
    yield g.follow_geometry
    for tool in g.tools.values():
        for el in tool.get('geometry', []):
            for k in ('solid', 'follow', 'clear'):
                if k in el:
                    yield el[k]


class TestGerberTransforms(unittest.TestCase):
    def test_equivalence_with_shapely_affinity(self):
        for path in SAMPLES:
            parsed = load(path)
            for name, (op, ref) in OPS.items():
                with self.subTest(sample=os.path.basename(path), op=name):
                    g = copy.deepcopy(parsed)
                    expected = [ref_map(s, ref) for s in all_structures(g)]
                    self.assertIsNone(op(g))
                    for got, exp in zip(all_structures(g), expected):
                        check_same(self, got, exp)

    def test_container_types_preserved(self):
        g = load(SAMPLES[0])
        before = [type(s) for s in all_structures(g)]
        g.rotate(30, [5, 7])
        self.assertEqual([type(s) for s in all_structures(g)], before)


if __name__ == '__main__':
    unittest.main()
