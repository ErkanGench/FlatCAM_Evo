"""Tests of the automatic alignment (AlignGen.auto_align) on synthetic boards: holes must fall into pads."""

import math
import os
import sys
import time
import unittest

import numpy as np
from shapely import Point, box

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from appPlugins.ToolAlignObjects.AlignGen import (AlignError, SnapIndex, auto_align, is_ambiguous, apply_matrix,
                                                  invert)


def board(seed=1, vias=60):
    """Pad centers of a board: 3 DIP footprints, 2 rows of headers, random vias. Not symmetric."""
    rng = np.random.default_rng(seed)
    pts = []
    for ox, oy, n in ((5, 5, 8), (30, 8, 14), (12, 40, 4)):
        for i in range(n):
            pts.append((ox + i * 2.54, oy))
            pts.append((ox + i * 2.54, oy + 7.62))
    for i in range(10):
        pts.append((60, 5 + i * 2.54))
    pts.extend(rng.uniform((0, 0), (80, 60), (vias, 2)).tolist())
    return np.array(pts)


def pad_index(centers, size=1.6):
    solids = [box(x - size / 2, y - size / 2, x + size / 2, y + size / 2) for x, y in centers]
    return SnapIndex(solids, centers, np.empty((0, 2)))


def hole_index(centers, dia=0.8):
    return SnapIndex([Point(x, y).buffer(dia / 2) for x, y in centers], centers, np.empty((0, 2)))


def rot(angle_deg, dx, dy, s=1.0):
    t = math.radians(angle_deg)
    return s * math.cos(t), -s * math.sin(t), s * math.sin(t), s * math.cos(t), dx, dy


class TestAutoAlign(unittest.TestCase):

    def check(self, holes, pads, want, **kw):
        """want: the matrix that maps the holes onto the pads."""
        t0 = time.perf_counter()
        res = auto_align(hole_index(holes), pad_index(pads), **kw)
        took = time.perf_counter() - t0
        best = res[0]
        err = np.hypot(*(apply_matrix(best.matrix, holes) - apply_matrix(want, holes)).T)
        self.assertLess(float(err.max()), 0.05, 'max error %.4f' % err.max())
        self.assertLess(took, 5.0)
        return best

    def test_rotations(self):
        pads = board()
        for ang in (0, 37, 90, 180, -123.4):
            with self.subTest(angle=ang):
                m = rot(ang, 15.0, -7.5)
                holes = apply_matrix(invert(m), pads)
                best = self.check(holes, pads, m)
                self.assertEqual(best.matched, len(holes))
                self.assertFalse(best.mirrored)

    def test_mirror(self):
        pads = board()
        m = rot(25, 100.0, 3.0)
        mirrored = (-m[0], m[1], -m[2], m[3], m[4], m[5])    # m after x -> -x
        holes = apply_matrix(invert(mirrored), pads)
        best = self.check(holes, pads, mirrored, allow_mirror=True)
        self.assertTrue(best.mirrored)
        with self.assertRaises(AssertionError):
            self.check(holes, pads, mirrored, allow_mirror=False)

    def test_scale_similarity(self):
        pads = board()
        m = rot(12, 4.0, 9.0, s=1.01)
        holes = apply_matrix(invert(m), pads)
        self.check(holes, pads, m, model='similarity')

    def test_outliers_and_missing_pads(self):
        rng = np.random.default_rng(5)
        pads = board(vias=80)
        m = rot(-71, -20.0, 40.0)
        holes = apply_matrix(invert(m), pads)
        holes = holes[rng.permutation(len(holes))[: int(0.85 * len(holes))]]     # pads with no hole
        extra = rng.uniform(holes.min(axis=0), holes.max(axis=0), (15, 2))        # holes with no pad
        noisy = np.vstack([holes, extra]) + rng.normal(0, 0.02, (len(holes) + 15, 2))
        best = self.check(noisy, pads, m)
        self.assertGreaterEqual(best.matched, len(holes) - 2)
        self.assertLess(best.rms, 0.06)

    def test_large_board_speed(self):
        rng = np.random.default_rng(9)
        pads = np.vstack([board(vias=200)] + [board(seed=s, vias=0) + rng.uniform(0, 300, 2) for s in range(40)])
        m = rot(200, 3.0, 4.0)
        holes = apply_matrix(invert(m), pads)
        self.check(holes, pads, m)

    def test_symmetric_is_ambiguous(self):
        pads = np.array([(0, 0), (50, 0), (50, 30), (0, 30)], dtype=float)
        res = auto_align(hole_index(pads), pad_index(pads))
        self.assertTrue(is_ambiguous(res))
        self.assertGreaterEqual(len(res), 2)

    def test_errors(self):
        with self.assertRaises(AlignError):
            auto_align(hole_index(np.array([(0.0, 0.0)])), pad_index(board()))
        with self.assertRaises(AlignError):
            auto_align(hole_index(board()), SnapIndex([], [], np.empty((0, 2))))

    def test_progress(self):
        seen = []
        pads = board()
        auto_align(hole_index(pads), pad_index(pads), progress=seen.append)
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))


if __name__ == '__main__':
    unittest.main()
