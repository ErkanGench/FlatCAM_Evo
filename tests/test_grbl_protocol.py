#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.Common.grbl.grbl_protocol import parse_grbl_status_report, work_position


class TestStatusReport(unittest.TestCase):
    def test_run_mpos_fs_ov(self):
        rep = parse_grbl_status_report(
            '<Run|MPos:1.000,2.000,-0.500|FS:500,10000|Ov:100,100,100|WCO:0.000,0.000,0.000>')
        self.assertEqual(rep['state'], 'Run')
        self.assertEqual(rep['mpos'], (1.0, 2.0, -0.5))
        self.assertEqual(rep['feed'], 500.0)
        self.assertEqual(rep['spindle'], 10000.0)
        self.assertEqual(rep['ov'], (100, 100, 100))

    def test_idle_wpos(self):
        rep = parse_grbl_status_report('<Idle|WPos:0.000,0.000,0.000|FS:0,0>')
        self.assertEqual(rep['state'], 'Idle')
        self.assertEqual(rep['wpos'], (0.0, 0.0, 0.0))

    def test_hold_substate(self):
        self.assertEqual(parse_grbl_status_report('<Hold:0|MPos:0,0,0>')['state'], 'Hold')

    def test_not_a_report(self):
        for text in ('ok', '', None, '<Idle|MPos:1,2>'):
            self.assertIsNone(parse_grbl_status_report(text))

    def test_work_position_from_wco(self):
        self.assertEqual(work_position({'mpos': (10.0, 10.0, 0.0)}, last_wco=(1.0, 2.0, 3.0)),
                         (9.0, 8.0, -3.0))

    def test_work_position_unknown(self):
        self.assertIsNone(work_position({'mpos': (1, 2, 3)}))


# ---- merged from test_grbl_bicubic.py ----
import sys
import os

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


# ---- merged from test_grbl_toolpath.py ----
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


# ---- merged from test_grbl_sender_gen.py ----
import sys
import os

import unittest
from types import SimpleNamespace

from appPlugins.ToolGrblSender import SenderGen


class TestCleanLines(unittest.TestCase):
    def test_removes_comments(self):
        self.assertEqual(SenderGen.clean_lines('G1 X1 (cut)\n; note\nG0 Z5 ;up\n%\n\n'), ['G1 X1', 'G0 Z5'])


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


# ---- merged from test_grbl_segment.py ----
import sys
import os

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


# ---- merged from test_grbl_stream.py ----
import sys
import os

import unittest

import serial

from appPlugins.Common.grbl.grbl_client import (
    stream_lines, validate_stream_lines, dwell_seconds, GRBL_RX_BUFFER, GRBL_MAX_LINE)


class FakeStreamPort:
    """Each written line gets 'ok' after 1 readline(); the receive buffer must never overflow."""

    def __init__(self, rx_size=127, errors=None, alarm_at=None):
        self.rx_size = rx_size
        self.pending = []           # byte counts in the GRBL buffer
        self.replies = []
        self.written = []
        self.polls = 0
        self.max_used = 0
        self.errors = errors or {}  # line index -> 'error:N'
        self.alarm_at = alarm_at
        self.count = 0
        self.status_sent = False

    def write(self, data):
        if data == b'?':
            self.polls += 1
            # answer the first '?' only; more answers would keep readline() busy for ever
            if not self.status_sent:
                self.status_sent = True
                self.replies.append(b'<Run|MPos:0.000,0.000,0.000|FS:0,0>\r\n')
            return 'ok'
        self.written.append(data)
        self.pending.append(len(data))
        used = sum(self.pending)
        self.max_used = max(self.max_used, used)
        assert used <= self.rx_size, "GRBL receive buffer overflow"
        return 'ok'

    def readline(self):
        if self.replies:
            return self.replies.pop(0)
        if not self.pending:
            return b''
        self.pending.pop(0)
        index = self.count
        self.count += 1
        if self.alarm_at == index:
            return b'ALARM:1\r\n'
        return (self.errors.get(index, 'ok') + '\r\n').encode()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TimedPort(FakeStreamPort):
    """
    A GRBL fake with a fake clock. Each readline() advances the clock by `step` s, so no test sleeps.
    The oldest line gets 'ok' when the clock reaches `ack_at` (never if None). Each '?' is answered with
    report(now). A test that never times out fails at `limit` s instead of looping for ever.
    """

    def __init__(self, clock, ack_at=None, report=None, step=1.0, limit=1000.0, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.ack_at = ack_at
        self.report = report
        self.step = step
        self.limit = limit
        self.queue = []

    def write(self, data):
        if data == b'?':
            self.polls += 1
            if self.report is not None:
                self.queue.append((self.report(self.clock.now) + '\r\n').encode())
            return 'ok'
        return super().write(data)

    def readline(self):
        self.clock.now += self.step
        assert self.clock.now <= self.limit, "the streamer did not time out"
        if self.ack_at is not None and self.clock.now >= self.ack_at and self.pending:
            self.pending.pop(0)
            return b'ok\r\n'
        if self.queue:
            return self.queue.pop(0)
        return b''


def run(port, lines, **kwargs):
    return stream_lines(lines, port.write, port.readline, **kwargs)


class TestStream(unittest.TestCase):
    def test_all_lines_sent_in_order(self):
        lines = ['G1 X%d Y%d F100' % (i, i) for i in range(200)]
        port = FakeStreamPort()
        res = run(port, lines)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(res['done'], 200)
        self.assertEqual(res['in_flight'], 0)
        self.assertEqual([d.decode().strip() for d in port.written], lines)

    def test_buffer_never_overflows_and_is_used(self):
        lines = ['G1 X%d.123456 Y%d.654321 F1000' % (i, i) for i in range(100)]
        port = FakeStreamPort()
        run(port, lines)
        self.assertLessEqual(port.max_used, 127)
        self.assertGreater(port.max_used, 60)

    def test_buffer_fills_to_the_last_byte(self):
        # 2 lines of 10 bytes fit in 20 bytes: the fill condition is 'used + len > rx_size'
        port = FakeStreamPort(rx_size=20)
        res = run(port, ['G1 X1 Y12'] * 6, rx_size=20)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(port.max_used, 20)

    def test_error_stops(self):
        port = FakeStreamPort(errors={5: 'error:20', 8: 'error:33'})
        res = run(port, ['G1 X%d' % i for i in range(20)])
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['errors'], [(5, 'error:20')])

    def test_check_mode_counts_errors(self):
        port = FakeStreamPort(errors={2: 'error:20', 7: 'error:33'})
        res = run(port, ['G1 X%d' % i for i in range(10)], check_mode=True)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual([e[0] for e in res['errors']], [2, 7])

    def test_alarm_stops(self):
        port = FakeStreamPort(alarm_at=3)
        res = run(port, ['G1 X%d' % i for i in range(10)])
        self.assertEqual(res['status'], 'alarm')

    def test_stop_request(self):
        port = FakeStreamPort()
        calls = []

        def write(data):
            calls.append(data)
            if len(calls) > 3:
                return 'cancelled'
            return port.write(data)

        res = stream_lines(['G1 X%d' % i for i in range(500)], write, port.readline)
        self.assertEqual(res['status'], 'cancelled')
        # nothing is written after the status 'cancelled'
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(port.written), 3)

    def test_stale_at_the_first_write(self):
        calls = []

        def write(data):
            calls.append(data)
            return 'stale'

        def readline():
            raise AssertionError("nothing was written, so nothing is read")

        res = stream_lines(['G1 X1', 'G1 X2'], write, readline, poll_status=True)
        self.assertEqual(res['status'], 'stale')
        self.assertEqual(res['done'], 0)
        self.assertEqual(res['in_flight'], 0)
        self.assertEqual(len(calls), 1)

    def test_port_error_after_writes(self):
        port = FakeStreamPort()
        calls = []

        def write(data):
            calls.append(data)
            if len(calls) == 4:
                return 'port_error'
            return port.write(data)

        res = stream_lines(['G1 X%d' % i for i in range(20)], write, port.readline)
        self.assertEqual(res['status'], 'port_error')
        self.assertEqual(len(calls), 4)
        self.assertEqual(res['in_flight'], 3)

    def test_port_error_on_poll_write(self):
        port = FakeStreamPort()

        def write(data):
            return 'port_error' if data == b'?' else port.write(data)

        res = stream_lines(['G1 X1'], write, port.readline, poll_status=True)
        self.assertEqual(res['status'], 'port_error')

    def test_readline_exception_is_port_error(self):
        port = FakeStreamPort()

        def readline():
            raise serial.SerialException("device lost")

        self.assertEqual(stream_lines(['G1 X1'], port.write, readline)['status'], 'port_error')

        def readline_os():
            raise OSError("device lost")

        self.assertEqual(stream_lines(['G1 X1'], port.write, readline_os)['status'], 'port_error')

    def test_progress_and_status(self):
        progress, status = [], []
        port = FakeStreamPort()
        run(port, ['G1 X1', 'G1 X2'], on_progress=lambda d, t: progress.append((d, t)),
            poll_status=True, poll_interval=0.0, on_status=status.append)
        self.assertEqual(progress[-1], (2, 2))
        self.assertTrue(status)
        self.assertGreaterEqual(port.polls, 1)

    def test_on_line_has_job_lines_and_replies_only(self):
        seen = []
        port = FakeStreamPort()
        run(port, ['G1 X1', 'G1 X2'], on_line=seen.append, poll_status=True, poll_interval=0.0)
        self.assertEqual(seen.count('G1 X1'), 1)
        self.assertEqual(seen.count('G1 X2'), 1)
        self.assertEqual(seen.count('ok'), 2)
        self.assertEqual(len(seen), 4)

    def test_long_line_rejected(self):
        lines = ['G1 X%d' % i for i in range(10)]
        lines[5] = 'G1 X1 ' + 'Y' * 80
        port = FakeStreamPort()
        res = run(port, lines)
        self.assertEqual(res['status'], 'line_too_long')
        self.assertEqual(res['line_index'], 5)
        # the check is before the first write
        self.assertEqual(port.written, [])
        self.assertEqual(port.polls, 0)

    def test_line_limit_counts_the_line_end(self):
        port = FakeStreamPort()
        self.assertEqual(run(port, ['G' * 79])['status'], 'finished')
        self.assertEqual(run(FakeStreamPort(), ['G' * 80])['status'], 'line_too_long')

    def test_validate_stream_lines(self):
        self.assertIsNone(validate_stream_lines(['G1 X1', 'G' * 79]))
        self.assertEqual(validate_stream_lines(['G1 X1', 'G' * 80, 'G' * 90]), 1)
        # the limit is min(rx_size, GRBL_MAX_LINE)
        self.assertEqual(validate_stream_lines(['G1 X1 Y1'], rx_size=8), 0)
        self.assertIsNone(validate_stream_lines(['G1 X1 Y1'], rx_size=9))
        self.assertEqual(validate_stream_lines(['G' * 80], rx_size=500), 0)
        # encoded bytes, not characters
        self.assertEqual(validate_stream_lines(['(' + '\u00e9' * 40 + ')']), 0)
        self.assertEqual((GRBL_RX_BUFFER, GRBL_MAX_LINE), (127, 80))

    def test_dwell_seconds(self):
        self.assertEqual(dwell_seconds('G4 P60'), 60.0)
        self.assertEqual(dwell_seconds('G04 P0.5'), 0.5)
        self.assertEqual(dwell_seconds('g4p2.5 (wait)'), 2.5)
        self.assertEqual(dwell_seconds('G4'), 0.0)
        self.assertEqual(dwell_seconds('G1 X1 P60'), 0.0)
        self.assertEqual(dwell_seconds('G41 P60'), 0.0)
        self.assertEqual(dwell_seconds('M3 S1000'), 0.0)
        self.assertEqual(dwell_seconds('(G4 P60)'), 0.0)

    def test_timeout(self):
        clock = FakeClock()
        port = TimedPort(clock)
        res = run(port, ['G1 X1'], clock=clock, stall_timeout=30.0)
        self.assertEqual(res['status'], 'timeout')
        self.assertEqual(res['in_flight'], 1)
        self.assertGreater(clock.now, 30.0)
        self.assertLessEqual(clock.now, 32.0)

    def test_status_does_not_refresh_stall(self):
        # an Idle report and an unchanged Run report are not progress
        for report in (lambda now: '<Idle|MPos:0.000,0.000,0.000|FS:0,0>',
                       lambda now: '<Run|MPos:5.000,0.000,0.000|FS:500,0>'):
            clock = FakeClock()
            port = TimedPort(clock, report=report)
            res = run(port, ['G1 X1'], clock=clock, stall_timeout=30.0, poll_status=True)
            self.assertEqual(res['status'], 'timeout')
            self.assertLessEqual(clock.now, 33.0)

    def test_moving_run_refreshes_stall(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=100.0, report=lambda now: '<Run|MPos:%.3f,0.000,0.000|FS:500,0>' % now)
        res = run(port, ['G1 X500'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'finished')


    def test_hold_refreshes_stall(self):
        for state in ('Hold:0', 'Door:1', 'Jog', 'Home'):
            clock = FakeClock()
            port = TimedPort(clock, ack_at=100.0, report=lambda now, s=state: '<%s|MPos:0.000,0.000,0.000>' % s)
            res = run(port, ['G1 X1'], clock=clock, stall_timeout=30.0, poll_status=True)
            self.assertEqual(res['status'], 'finished', state)

    def test_long_dwell_polled(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=70.0, report=lambda now: '<Idle|MPos:0.000,0.000,0.000|FS:0,0>')
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'finished')

    def test_dwell_extension_is_set_once_when_polled(self):
        clock = FakeClock()
        port = TimedPort(clock, report=lambda now: '<Idle|MPos:0.000,0.000,0.000|FS:0,0>')
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'timeout')
        self.assertGreater(clock.now, 90.0)
        self.assertLessEqual(clock.now, 93.0)

    def test_long_dwell_not_polled(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=70.0)
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=False)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(port.polls, 0)
        clock = FakeClock()
        port = TimedPort(clock, ack_at=100.0)
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=False)
        self.assertEqual(res['status'], 'timeout')
        self.assertGreater(clock.now, 90.0)
        self.assertLessEqual(clock.now, 92.0)

    def test_dwell_starts_when_the_g4_is_the_oldest_line(self):
        # not polled: line 0 is acknowledged at 20 s, then the G4 gets its 60 s from that time
        clock = FakeClock()

        class Port(TimedPort):
            def readline(self):
                self.clock.now += self.step
                assert self.clock.now <= self.limit, "the streamer did not time out"
                if self.pending and self.clock.now in (20.0, 100.0):
                    self.pending.pop(0)
                    return b'ok\r\n'
                return b''

        res = run(Port(clock), ['G1 X1', 'G4 P60'], clock=clock, stall_timeout=30.0, poll_status=False)
        self.assertEqual(res['status'], 'finished')


if __name__ == '__main__':
    unittest.main()
