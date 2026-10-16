# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/15/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""Tests of parse_toolpath(), the 3D toolpath with the line index."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appPlugins.Common.gcode_segment import parse_toolpath


class ParseToolpathTest(unittest.TestCase):

    def test_basic(self):
        segs = parse_toolpath(['G0 X1 Y1', 'G1 Z-1', 'G1 X2'], start=(0, 0, 0))
        self.assertEqual([s[0] for s in segs], [0, 1, 2])
        self.assertEqual([s[3] for s in segs], [True, False, False])
        self.assertEqual(segs[-1][2], (2.0, 1.0, -1.0))

    def test_relative(self):
        segs = parse_toolpath(['G91', 'G1 X1', 'G1 X1'], start=(0, 0, 0))
        self.assertEqual(segs[-1][2], (2.0, 0.0, 0.0))

    def test_no_move_no_segment(self):
        self.assertEqual(parse_toolpath(['G1 X0'], start=(0, 0, 0)), [])

    def test_skips_g28_g92(self):
        self.assertEqual(parse_toolpath(['G92 X5', 'G28 X0'], start=(0, 0, 0)), [])

    def test_unknown_start_no_segment(self):
        self.assertEqual(parse_toolpath(['G1 X5 F100', 'G1 Y5', 'G1 X9']), [])

    def test_segments_start_after_all_axes_known(self):
        segs = parse_toolpath(['G1 X5 F100', 'G1 Y5', 'G1 Z2', 'G1 X9'])
        self.assertEqual([s[0] for s in segs], [3])
        self.assertEqual(segs[0][1:3], ((5.0, 5.0, 2.0), (9.0, 5.0, 2.0)))

    def test_g92_then_unknown(self):
        segs = parse_toolpath(['G1 X1 Y1 Z1', 'G92 X0', 'G1 X5'], start=(0, 0, 0))
        self.assertEqual([s[0] for s in segs], [0])

    def test_probe_then_unknown(self):
        segs = parse_toolpath(['G38.2 Z-5 F10', 'G1 X5', 'G1 Y5'], start=(0, 0, 0))
        self.assertEqual(segs, [])

    def test_arc_is_chord(self):
        segs = parse_toolpath(['G2 X2 Y0 I1 J0'], start=(0, 0, 0))
        self.assertEqual(segs, [(0, (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), False)])


if __name__ == '__main__':
    unittest.main()
