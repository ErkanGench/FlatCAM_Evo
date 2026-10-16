#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from types import SimpleNamespace

from appPlugins.ToolGrblSender import SenderGen


class TestCleanLines(unittest.TestCase):
    def test_removes_comments(self):
        self.assertEqual(SenderGen.clean_lines('G1 X1 (cut)\n; note\nG0 Z5 ;up\n%\n\n'), ['G1 X1', 'G0 Z5'])

    def test_keeps_order(self):
        self.assertEqual(SenderGen.clean_lines('G0 X1\nG1 X2\nG1 X3\n'), ['G0 X1', 'G1 X2', 'G1 X3'])

    def test_numbered_keeps_source_line(self):
        self.assertEqual(SenderGen.clean_lines_numbered('(a)\nG0 X1\n\n; c\nG1 X2\n'), [(2, 'G0 X1'), (5, 'G1 X2')])


class TestNeedsSegmentation(unittest.TestCase):
    def test_flag_true(self):
        self.assertFalse(SenderGen.needs_segmentation(SimpleNamespace(is_segmented_gcode=True)))

    def test_flag_false_or_missing(self):
        self.assertTrue(SenderGen.needs_segmentation(SimpleNamespace(is_segmented_gcode=False)))
        self.assertTrue(SenderGen.needs_segmentation(SimpleNamespace()))


class TestSplitArcs(unittest.TestCase):
    def test_arc_split_keeps_z(self):
        lines = ['G90', 'G21', 'G0 X0 Y0 Z-0.1', 'G2 X10 Y0 I5 J0']
        out, count, source_index, unsplit = SenderGen.split_arcs(lines, 'MM', 1.0)
        self.assertGreater(len(out), 5)
        self.assertEqual(count, 1)
        self.assertEqual(unsplit, [])
        new_lines = [line for line in out if line.startswith('G1')]
        self.assertTrue(new_lines)
        self.assertTrue(all('Z-0.1' in line for line in new_lines))
        # the first 3 lines are the source lines; every new line comes from the arc line
        self.assertEqual(source_index[:3], [0, 1, 2])
        self.assertEqual(set(source_index[3:]), {3})
        self.assertEqual(len(source_index), len(out))

    def test_no_arcs(self):
        lines = ['G90', 'G21', 'G0 X0 Y0 Z5', 'G1 X10 Y0 Z-1 F100']
        out, count, source_index, unsplit = SenderGen.split_arcs(lines, 'MM', 1.0)
        self.assertEqual(out, lines)
        self.assertEqual(count, 0)
        self.assertEqual(source_index, list(range(len(lines))))
        self.assertEqual(unsplit, [])

    def test_modal_arc_split(self):
        # the second arc line is a bare modal line (no G word)
        lines = ['G0 X0 Y0 Z0', 'G2 X10 Y0 I5 J0 F100', 'X20 Y0 I5 J0']
        out, count, source_index, unsplit = SenderGen.split_arcs(lines, 'MM', 1.0)
        self.assertEqual(count, 2)
        self.assertEqual(unsplit, [])
        self.assertNotIn('X20 Y0 I5 J0', out)
        self.assertEqual(set(source_index), {0, 1, 2})

    def test_unsplit_modal_arc(self):
        # The parser (level_gcode_line) does not split an arc in the G18 plane: it counts both
        # arc lines (the 2nd is modal) in state['arcs'], and leaves them as they are. So both
        # source indexes are in `unsplit`, the count is 0 and the output is the source list.
        lines = ['G18', 'G0 X0 Y0 Z0', 'G2 X10 Z0 I5 K0', 'X20 Z0 I5 K0']
        out, count, source_index, unsplit = SenderGen.split_arcs(lines, 'MM', 1.0)
        self.assertEqual(unsplit, [2, 3])
        self.assertEqual(count, 0)
        self.assertEqual(out, lines)
        self.assertEqual(source_index, [0, 1, 2, 3])


if __name__ == '__main__':
    unittest.main()
