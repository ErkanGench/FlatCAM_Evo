#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.Common.gcode_segment import split_long_moves, _words


class TestSplitLongMoves(unittest.TestCase):
    def test_long_g1_is_split(self):
        lines = ['G90', 'G0 X0 Y0 Z1', 'G1 Z-0.1 F100', 'G1 X10 Y0']
        out, count = split_long_moves(lines, 2.5)
        self.assertEqual(count, 1)
        self.assertEqual(len(out), 3 + 4)
        self.assertEqual(out[:3], lines[:3])
        self.assertEqual(out[-1], 'G1 X10.0000 Y0.0000 Z-0.1000')

    def test_short_g1_unchanged(self):
        lines = ['G0 X0 Y0 Z-0.1', 'G1 X1 Y0']
        out, count = split_long_moves(lines, 2)
        self.assertEqual(out, lines)
        self.assertEqual(count, 0)

    def test_g0_unchanged(self):
        lines = ['G0 X0 Y0 Z1', 'G0 X100']
        out, count = split_long_moves(lines, 2)
        self.assertEqual(out, lines)
        self.assertEqual(count, 0)

    def test_g91_unchanged(self):
        lines = ['G90', 'G1 X0 Y0 Z0', 'G91', 'G1 X50']
        out, count = split_long_moves(lines, 2)
        self.assertEqual(out, lines)
        self.assertEqual(count, 0)

    def test_unknown_start_unchanged(self):
        out, count = split_long_moves(['G1 X50 Y0'], 2)
        self.assertEqual(out, ['G1 X50 Y0'])
        self.assertEqual(count, 0)

    def test_feed_on_first_piece_only(self):
        out, count = split_long_moves(['G0 X0 Y0 Z0', 'G1 X10 F300'], 2)
        pieces = out[1:]
        self.assertEqual(count, 1)
        self.assertEqual(len(pieces), 5)
        self.assertTrue(pieces[0].endswith('F300.00'))
        for piece in pieces[1:]:
            self.assertNotIn('F', piece)

    def test_other_words_unchanged(self):
        lines = ['G0 X0 Y0 Z0', 'G1 X50 S1000']
        out, count = split_long_moves(lines, 2)
        self.assertEqual(out, lines)
        self.assertEqual(count, 0)

    def test_bad_max_len(self):
        with self.assertRaises(ValueError):
            split_long_moves(['G1 X1'], 0)


class TestSplitStateRules(unittest.TestCase):
    """The state rules of A6, the same as level_gcode_line()."""

    def _unchanged(self, lines, max_len=2):
        out, count = split_long_moves(lines, max_len)
        self.assertEqual(out, lines)
        self.assertEqual(count, 0)

    def test_words_keep_decimal_g(self):
        self.assertEqual(_words('G38.2 Z-5 F10'), [('G', 38.2), ('Z', -5.0), ('F', 10.0)])
        self.assertEqual(_words('g59.1'), [('G', 59.1)])

    def test_same_block_g90_kept(self):
        # the G90 in the block of the move is the distance mode of the move
        lines = ['G90 G0 X0 Y0 Z0', 'G91', 'G90 G1 X10 Y0 F100']
        out, count = split_long_moves(lines, 2.5)
        self.assertEqual(count, 1)
        self.assertEqual(out[:2], lines[:2])
        pieces = out[2:]
        self.assertEqual(len(pieces), 4)
        # the non-motion G words stay on the first piece; the others start with G1
        self.assertEqual(pieces[0], 'G90 G1 X2.5000 Y0.0000 Z0.0000 F100.00')
        self.assertTrue(all(p.startswith('G1 ') for p in pieces[1:]))

    def test_probe_makes_position_unknown(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G38.2 Z-5 F10', 'G1 X10 Y0 F100'])
        # the axis word of the probe does not make Z known; a later absolute move does, axis by axis
        lines = ['G0 X0 Y0 Z0', 'G38.2 Z-5 F10', 'G1 X10 Y0 F100', 'G1 X20 Y0 Z-1', 'G1 X30 Y0']
        out, count = split_long_moves(lines, 5)
        self.assertEqual(out[:3], lines[:3])
        self.assertEqual(out[3], lines[3])
        self.assertEqual(count, 1)
        self.assertEqual(len(out), 4 + 2)

    def test_tlo_makes_z_unknown(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G43.1 Z1', 'G1 X10 Y0 F100'])
        self._unchanged(['G0 X0 Y0 Z0', 'G49', 'G1 X10 Y0 F100'])

    def test_g53_makes_position_unknown(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G53 G0 Z0', 'G1 X10 Y0 F100'])

    def test_wcs_change_makes_position_unknown(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G55', 'G1 X10 Y0 F100'])
        self._unchanged(['G0 X0 Y0 Z0', 'G59.1', 'G1 X10 Y0 F100'])

    def test_units_change_makes_position_unknown(self):
        self._unchanged(['G21', 'G0 X0 Y0 Z0', 'G20', 'G1 X10 Y0 F100'])
        # the same units again keep the position
        out, count = split_long_moves(['G21', 'G0 X0 Y0 Z0', 'G21', 'G1 X10 Y0 F100'], 5)
        self.assertEqual(count, 1)

    def test_inverse_time_not_split(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G93', 'G1 X10 Y0 F100'])
        # G94 allows the split again
        out, count = split_long_moves(['G0 X0 Y0 Z0', 'G93', 'G1 X10 Y0 F100', 'G94', 'G1 X20 Y0'], 5)
        self.assertEqual(count, 1)
        self.assertEqual(len(out), 4 + 2)

    def test_unknown_g_makes_position_unknown(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G12 I5', 'G1 X10 Y0 F100'])

    def test_modal_g1_without_word_split(self):
        lines = ['G1 X0 Y0 Z0 F100', 'X50']
        out, count = split_long_moves(lines, 10)
        self.assertEqual(count, 1)
        self.assertEqual(out[0], lines[0])
        self.assertEqual(len(out), 1 + 5)
        self.assertEqual(out[-1], 'G1 X50.0000 Y0.0000 Z0.0000')

    def test_inherited_g91_not_split(self):
        self._unchanged(['G0 X0 Y0 Z0', 'G91', 'G1 X10 F100'])

    def test_other_g_words_in_block_not_split(self):
        # only G1, G17, G90 and G94 are allowed in the block of a split move
        self._unchanged(['G0 X0 Y0 Z0', 'G18 G1 X10 Y0 F100'])
        self._unchanged(['G0 X0 Y0 Z0', 'G61 G1 X10 Y0 F100'])

    def test_program_end_and_dollar_lines(self):
        self._unchanged(['G0 X0 Y0 Z0', 'M30', 'G1 X10 Y0 F100'])
        self._unchanged(['G0 X0 Y0 Z0', '$H', 'G1 X10 Y0 F100'])

    def test_axis_word_of_unknown_block_not_known(self):
        # G92 names X and Y: they are not known after it, even if G1 is the modal mode
        self._unchanged(['G1 X0 Y0 Z0 F100', 'G92 X0 Y0', 'G1 X10 Y0'])
        self._unchanged(['G1 X0 Y0 Z0 F100', 'G92 X0 Y0', 'G1 X10 Y0', 'G1 X20 Y0'])


if __name__ == '__main__':
    unittest.main()
