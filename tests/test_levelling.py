#!/usr/bin/env python
"""
Unit tests for the autolevelling interpolation and parsing helpers.

Run: python tests/test_levelling.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.levelling_interp import (
    build_bilinear_grid,
    bilinear_offset,
    nearest_offset,
    _group_values,
)


def plane(x, y):
    return 0.01 * x - 0.02 * y + 0.1


class TestBilinear(unittest.TestCase):
    def setUp(self):
        xs = [0, 10, 20]
        ys = [0, 5, 10]
        points = []
        for x in xs:
            for y in ys:
                points.append((x, y, plane(x, y)))
        # shuffle deterministically
        self.points = [
            points[4], points[0], points[7], points[1], points[8],
            points[2], points[5], points[3], points[6],
        ]
        self.grid = build_bilinear_grid(self.points)
        self.assertIsNotNone(self.grid)

    def test_corners(self):
        for x, y in [(0, 0), (20, 0), (0, 10), (20, 10)]:
            self.assertAlmostEqual(
                bilinear_offset(self.grid, x, y), plane(x, y), places=9
            )

    def test_edge_midpoints(self):
        for x, y in [(10, 0), (10, 10), (0, 5), (20, 5)]:
            self.assertAlmostEqual(
                bilinear_offset(self.grid, x, y), plane(x, y), places=9
            )

    def test_center(self):
        self.assertAlmostEqual(
            bilinear_offset(self.grid, 10, 5), plane(10, 5), places=9
        )

    def test_arbitrary_inside_point(self):
        self.assertAlmostEqual(
            bilinear_offset(self.grid, 13.3, 7.1), plane(13.3, 7.1), places=9
        )

    def test_clamp_low(self):
        val = bilinear_offset(self.grid, -5, 5)
        expected = bilinear_offset(self.grid, 0, 5)
        self.assertAlmostEqual(val, expected, places=9)

    def test_clamp_high(self):
        val = bilinear_offset(self.grid, 25, 12)
        expected = bilinear_offset(self.grid, 20, 10)
        self.assertAlmostEqual(val, expected, places=9)


class TestGridDetection(unittest.TestCase):
    def setUp(self):
        self.xs = [0, 10, 20]
        self.ys = [0, 5, 10]

    def _points(self):
        points = []
        for x in self.xs:
            for y in self.ys:
                points.append((x, y, plane(x, y)))
        return points

    def test_off_grid_point_returns_none(self):
        points = self._points()
        # move one point off-grid in X
        x, y, z = points[0]
        points[0] = (10.3 if x == 0 else x, y, z)
        result = build_bilinear_grid(points)
        self.assertIsNone(result)

    def test_missing_point_returns_none(self):
        points = self._points()
        points.pop()
        result = build_bilinear_grid(points)
        self.assertIsNone(result)

    def test_noise_still_builds_grid(self):
        points = self._points()
        noisy = [(x + 1e-9, y - 1e-9, z) for (x, y, z) in points]
        result = build_bilinear_grid(noisy)
        self.assertIsNotNone(result)
        xs, ys, grid = result
        self.assertEqual(len(xs), 3)
        self.assertEqual(len(ys), 3)

    def test_single_row_returns_none(self):
        points = [(x, 0, plane(x, 0)) for x in self.xs]
        result = build_bilinear_grid(points)
        self.assertIsNone(result)

    def test_single_column_returns_none(self):
        points = [(0, y, plane(0, y)) for y in self.ys]
        result = build_bilinear_grid(points)
        self.assertIsNone(result)

    def test_duplicate_cell_returns_none(self):
        points = self._points()
        # add an extra point that snaps to an already-filled cell
        points.append((points[0][0], points[0][1], points[0][2]))
        result = build_bilinear_grid(points)
        self.assertIsNone(result)


class TestGroupValues(unittest.TestCase):
    def test_no_chaining_across_tol_span(self):
        # 0, 0.4e-6, 0.8e-6, 1.2e-6 with tol=1e-6: each consecutive pair
        # is within tol of its neighbor, but the span from 0 to 1.2e-6
        # exceeds tol, so this must NOT collapse into a single group.
        # Anchoring to the first value of the group (not the previous
        # value) gives 2 groups: {0, 0.4e-6, 0.8e-6} and {1.2e-6}.
        groups = _group_values([0, 0.4e-6, 0.8e-6, 1.2e-6], 1e-6)
        self.assertEqual(len(groups), 2)


class TestNearest(unittest.TestCase):
    def setUp(self):
        self.points = [
            (0, 0, 1.0),
            (10, 0, 2.0),
            (0, 10, 3.0),
            (10, 10, 4.0),
            (5, 5, 5.0),
        ]

    def test_query_on_point(self):
        self.assertEqual(nearest_offset(self.points, 10, 0), 2.0)

    def test_query_near_point(self):
        self.assertEqual(nearest_offset(self.points, 9.9, 0.1), 2.0)

    def test_query_equidistant_returns_first(self):
        # (0,0) and (10,0) are both distance 5 from (5, 0), and both
        # come before the closer (5,5) point... use a point equidistant
        # between (0,0) and (10,0) but excluding (5,5) by using y offset
        # that keeps (0,0) and (10,0) tied and closer than others.
        points = [
            (0, 0, 1.0),
            (10, 0, 2.0),
        ]
        result = nearest_offset(points, 5, 0)
        self.assertEqual(result, 1.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            nearest_offset([], 0, 0)


if __name__ == '__main__':
    unittest.main()
