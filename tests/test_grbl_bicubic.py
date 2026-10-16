#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.Common.levelling_interp import (
    build_bilinear_grid, bicubic_offset, bicubic_supported, bilinear_offset)


def grid_points(fn, n=5, step=10.0):
    return [(i * step, j * step, fn(i * step, j * step)) for i in range(n) for j in range(n)]


class TestBicubic(unittest.TestCase):
    def test_hits_grid_nodes(self):
        g = build_bilinear_grid(grid_points(lambda x, y: 0.01 * x * y))
        self.assertAlmostEqual(bicubic_offset(g, 20.0, 30.0), 0.01 * 20.0 * 30.0, places=9)

    def test_plane_is_exact(self):
        g = build_bilinear_grid(grid_points(lambda x, y: 0.2 * x - 0.1 * y + 1.0))
        self.assertAlmostEqual(bicubic_offset(g, 13.0, 27.0), 0.2 * 13.0 - 0.1 * 27.0 + 1.0, places=9)

    def test_plane_exact_at_border(self):
        g = build_bilinear_grid(grid_points(lambda x, y: x))
        self.assertAlmostEqual(bicubic_offset(g, 2.5, 20.0), 2.5, places=9)
        self.assertAlmostEqual(bicubic_offset(g, 37.5, 20.0), 37.5, places=9)

    def test_clamped_outside(self):
        g = build_bilinear_grid(grid_points(lambda x, y: x + y))
        self.assertAlmostEqual(bicubic_offset(g, -50.0, -50.0), bicubic_offset(g, 0.0, 0.0), places=9)
        self.assertAlmostEqual(bicubic_offset(g, 500.0, 500.0), bicubic_offset(g, 40.0, 40.0), places=9)

    def test_supported_needs_4x4(self):
        self.assertTrue(bicubic_supported(build_bilinear_grid(grid_points(lambda x, y: 0.0, n=4))))
        self.assertFalse(bicubic_supported(build_bilinear_grid(grid_points(lambda x, y: 0.0, n=3))))
        self.assertFalse(bicubic_supported(None))

    def test_nonuniform_not_supported(self):
        xs = [0.0, 1.0, 3.0, 6.0, 10.0]
        ys = [0.0, 10.0, 20.0, 30.0, 40.0]
        grid = [[0.0] * len(xs) for _ in ys]
        self.assertIs(bicubic_supported((xs, ys, grid)), False)

    def test_close_to_bilinear_on_smooth_surface(self):
        g = build_bilinear_grid(grid_points(lambda x, y: 0.001 * (x - 20.0) ** 2))
        self.assertLess(abs(bicubic_offset(g, 15.0, 15.0) - bilinear_offset(g, 15.0, 15.0)), 0.05)


if __name__ == '__main__':
    unittest.main()
