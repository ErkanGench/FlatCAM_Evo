"""Tests of the Align Objects model: solvers, residuals, inverse and snap."""

import math
import os
import sys
import unittest

import numpy as np
from shapely import Point, LineString, Polygon

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from appPlugins.ToolAlignObjects.AlignGen import (AlignError, build_snap_index, snap, solve_translate, solve_rigid,
                                                  solve_similarity, solve_affine, residuals, invert, apply_matrix)

P = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [2.0, 7.0], [-3.0, 4.0]])


def rot(angle_deg, s=1.0, dx=0.0, dy=0.0):
    t = math.radians(angle_deg)
    c, sn = s * math.cos(t), s * math.sin(t)
    return c, -sn, sn, c, dx, dy


class FakeObj:
    def __init__(self, kind, tools=None, solid_geometry=None, multigeo=False):
        self.kind = kind
        self.tools = tools or {}
        self.solid_geometry = solid_geometry
        self.multigeo = multigeo
        self.excellon_circle_steps = 64


class TestSolvers(unittest.TestCase):

    def assertMatrix(self, got, want, tol=1e-9):
        np.testing.assert_allclose(got, want, atol=tol)

    def test_translate(self):
        m = solve_translate([(1, 2)], [(4, -1)])
        self.assertMatrix(m, (1, 0, 0, 1, 3, -3))

    def test_rigid_angles(self):
        for ang in (0, 45, 90, 180, -179, 179.5, -90):
            want = rot(ang, dx=12.5, dy=-3.25)
            for n in (2, 5):
                with self.subTest(angle=ang, pairs=n):
                    self.assertMatrix(solve_rigid(P[:n], apply_matrix(want, P[:n])), want)

    def test_similarity_scale(self):
        for s in (0.98, 1.02, 2.0):
            want = rot(30, s=s, dx=1, dy=2)
            with self.subTest(scale=s):
                self.assertMatrix(solve_similarity(P, apply_matrix(want, P)), want)
                self.assertMatrix(solve_similarity(P[:2], apply_matrix(want, P[:2])), want)

    def test_affine(self):
        want = (1.01, 0.02, -0.03, 0.97, 5.0, -7.0)
        self.assertMatrix(solve_affine(P, apply_matrix(want, P)), want)
        self.assertMatrix(solve_affine(P[:3], apply_matrix(want, P[:3])), want)

    def test_noise_rms(self):
        rng = np.random.default_rng(1)
        want = rot(17, dx=3, dy=4)
        big = rng.uniform(-50, 50, (200, 2))
        q = apply_matrix(want, big) + rng.normal(0, 0.01, big.shape)
        for solver in (solve_rigid, solve_similarity, solve_affine):
            m = solver(big, q)
            errors, rms = residuals(m, big, q)
            self.assertEqual(len(errors), 200)
            self.assertLess(rms, 0.02)
            self.assertGreater(rms, 0.005)

    def test_degenerate(self):
        same = [(1, 1), (1, 1), (1, 1)]
        with self.assertRaises(AlignError):
            solve_rigid(same, P[:3])
        with self.assertRaises(AlignError):
            solve_similarity(same, P[:3])
        with self.assertRaises(AlignError):
            solve_similarity(P[:3], same)
        with self.assertRaises(AlignError):
            solve_affine([(0, 0), (1, 1), (2, 2), (5, 5)], P[:4])
        with self.assertRaises(AlignError):
            solve_affine(P[:2], P[:2])
        with self.assertRaises(AlignError):
            solve_rigid(P[:1], P[:1])
        with self.assertRaises(AlignError):
            solve_translate([], [])
        with self.assertRaises(AlignError):
            solve_rigid(P[:2], P[:3])

    def test_invert(self):
        for m in (rot(123, s=1.5, dx=4, dy=-9), (1.01, 0.02, -0.03, 0.97, 5.0, -7.0)):
            back = apply_matrix(invert(m), apply_matrix(m, P))
            np.testing.assert_allclose(back, P, atol=1e-9)
        with self.assertRaises(AlignError):
            invert((1, 2, 2, 4, 0, 0))


class TestSnap(unittest.TestCase):

    def gerber(self):
        big = Point(0, 0).buffer(2.0)
        small = Point(0.5, 0).buffer(1.0)
        region = Polygon([(10, 10), (14, 10), (14, 12), (10, 12)])
        return FakeObj('gerber', tools={
            10: {'size': 4.0, 'geometry': [{'solid': big, 'follow': Point(0, 0)}]},
            11: {'size': 2.0, 'geometry': [{'solid': small, 'follow': Point(0.5, 0)}]},
            0: {'type': 'REG', 'geometry': [{'solid': region, 'follow': region.exterior}]},
        })

    def test_overlap_gives_smallest(self):
        idx = build_snap_index(self.gerber())
        self.assertEqual(snap(idx, 0.6, 0.1, 0.1), (0.5, 0.0))
        self.assertEqual(snap(idx, -1.5, 0.0, 0.1), (0.0, 0.0))

    def test_vertex_fallback_and_none(self):
        idx = build_snap_index(self.gerber())
        # a region is not a snap feature, but its vertices are the fallback
        self.assertEqual(snap(idx, 14.05, 12.05, 0.2), (14.0, 12.0))
        self.assertIsNone(snap(idx, 12.0, 11.0, 0.2))
        self.assertIsNone(snap(idx, 50.0, 50.0, 1.0))

    def test_excellon(self):
        exc = FakeObj('excellon', tools={
            1: {'tooldia': 1.0, 'drills': [Point(3, 3)], 'slots': [((10, 0), (14, 0))]},
        })
        idx = build_snap_index(exc)
        self.assertEqual(snap(idx, 3.2, 3.1, 0.1), (3.0, 3.0))
        self.assertEqual(snap(idx, 13.0, 0.2, 0.1), (12.0, 0.0))

    def test_geometry_vertices(self):
        geo = FakeObj('geometry', solid_geometry=[LineString([(0, 0), (5, 5)]), [Point(9, 9)]])
        idx = build_snap_index(geo)
        self.assertEqual(snap(idx, 4.9, 5.1, 0.5), (5.0, 5.0))
        self.assertEqual(snap(idx, 9.1, 9.0, 0.5), (9.0, 9.0))
        self.assertIsNone(snap(idx, 2.5, 2.4, 0.5))

        multi = FakeObj('geometry', multigeo=True, tools={1: {'solid_geometry': [LineString([(1, 1), (2, 1)])]}})
        self.assertEqual(snap(build_snap_index(multi), 2.0, 1.1, 0.5), (2.0, 1.0))

    def test_empty(self):
        idx = build_snap_index(FakeObj('geometry', solid_geometry=[]))
        self.assertIsNone(snap(idx, 0, 0, 10))


if __name__ == '__main__':
    unittest.main()
