#!/usr/bin/env python
"""The abort of a GRBL stream and the stream epoch (A5.2, A5.3)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

import serial

from tests.test_levelling_audit import FakeGrbl, emitted
from tests.grbl_stream_helpers import make_stream_tool, ended_how, has_success, gcode


class RaisingGrbl(FakeGrbl):
    """The port raises a SerialException from the `fail_at`-th write on."""

    def __init__(self, fail_at, **kwargs):
        super().__init__(**kwargs)
        self.fail_at = fail_at
        self.count = 0

    def write(self, data):
        self.count += 1
        if self.count >= self.fail_at:
            raise serial.SerialException('gone')
        super().write(data)


def job_lines_written(fake):
    return [text for text in fake.commands() if text.startswith('G1')]


class TestStreamAbort(unittest.TestCase):
    def _error_run(self):
        # line 0 of 10 gets error:20; 5 lines (23 bytes each) are in flight
        fake = FakeGrbl(replies={'G1 X00': ['error:20']})
        tool = make_stream_tool(fake)
        tool.on_start()
        return tool, fake

    def test_normal_job_finishes(self):
        fake = FakeGrbl()
        tool = make_stream_tool(fake)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'finished')
        self.assertEqual(len(job_lines_written(fake)), 10)
        self.assertTrue(has_success(tool))
        self.assertFalse(tool._grbl_stream_dirty)
        self.assertIsNone(tool._grbl_recovery)
        self.assertIsNone(tool._grbl_op)
        self.assertIsNotNone(tool._grbl_reserve('stream', motion=True))

    def test_error_latches(self):
        tool, fake = self._error_run()
        self.assertEqual(ended_how(tool), 'error')
        self.assertEqual(len(job_lines_written(fake)), 5)
        self.assertIn(b'!', fake.written)
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertTrue(tool._grbl_stream_dirty)
        self.assertIsNone(tool._grbl_op)
        self.assertIsNone(tool._grbl_reserve('stream', motion=True))
        self.assertFalse(has_success(tool))

    def test_port_exception_latches(self):
        # write 1 is the status query, writes 2 and 3 are job lines, write 4 raises
        fake = RaisingGrbl(4)
        tool = make_stream_tool(fake)
        at_release = {}
        real_release = tool._grbl_release

        def release(op):
            at_release['recovery'] = tool._grbl_recovery
            at_release['failed'] = op.failed
            real_release(op)
        tool._grbl_release = release
        tool.on_start()
        self.assertEqual(ended_how(tool), 'port_error')
        self.assertEqual(at_release, {'recovery': 'needs_reset', 'failed': True})
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertIsNone(tool._grbl_reserve('stream', motion=True))
        self.assertFalse(has_success(tool))

    def test_old_ok_not_consumed(self):
        tool, fake = self._error_run()
        self.assertGreaterEqual(len(fake.rx), 3)       # the ok of the lines in flight are still there
        before = list(fake.written)
        self.assertIsNone(tool._grbl_reserve('param'))
        self.assertEqual(fake.written, before)
        self.assertTrue(any('lines of the stopped job' in text for text in emitted(tool)))

    def test_reset_clears_dirty(self):
        tool, fake = self._error_run()
        self.assertTrue(tool._grbl_stream_dirty)
        tool.on_grbl_reset()
        # the reset worker (inline here) reads the banner that the fake sends for the reset byte
        self.assertFalse(tool._grbl_stream_dirty)
        self.assertFalse(tool._grbl_reset_pending)
        self.assertEqual(tool._grbl_recovery, 'needs_home')

    def test_reset_during_final_wait_kept(self):
        fake = FakeGrbl()
        tool = make_stream_tool(fake)
        state = {'all_acknowledged': False, 'reset': False}
        tool.stream_progress_sig.emit.side_effect = lambda done, total: state.update(
            all_acknowledged=(done == total))
        real_query = tool._grbl_query_status

        def query(op, *args, **kwargs):
            # the final wait for Idle: the user presses Reset here
            if state['all_acknowledged'] and not state['reset']:
                state['reset'] = True
                state['generation'] = tool._grbl_safety_generation + 1
                tool.on_grbl_reset()
            return real_query(op, *args, **kwargs)
        tool._grbl_query_status = query
        tool.on_start()
        self.assertTrue(state['reset'])
        self.assertEqual(ended_how(tool), 'stopped')
        self.assertTrue(tool._grbl_reset_pending)
        self.assertEqual(tool._grbl_safety_generation, state['generation'])
        self.assertTrue(tool._grbl_stream_dirty)
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertFalse(has_success(tool))

    def test_reset_after_idle_wait(self):
        fake = FakeGrbl()
        tool = make_stream_tool(fake)
        state = {}

        def wait_idle(op):
            state['generation'] = tool._grbl_safety_generation + 1
            tool.on_grbl_reset()
            return True
        tool._grbl_wait_idle = wait_idle
        tool.on_start()
        self.assertEqual(ended_how(tool), 'stopped')
        self.assertFalse(has_success(tool))
        self.assertTrue(tool._grbl_reset_pending)
        self.assertTrue(tool._grbl_stream_dirty)
        self.assertEqual(tool._grbl_safety_generation, state['generation'])
        self.assertEqual(tool._grbl_recovery, 'needs_reset')


if __name__ == '__main__':
    unittest.main()
