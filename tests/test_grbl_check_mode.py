#!/usr/bin/env python
"""Check mode for 1 job, and the exit from it (A5.4, A5.5)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from tests.test_levelling_audit import emitted
from tests.grbl_stream_helpers import make_stream_tool, make_levelled_stream_tool, ended_how, has_success, CheckFake


def fast_timeouts(tool):
    """The exit from check mode waits for the banner and the status: shorten the waits (< 1 s)."""
    real_confirm = tool._grbl_confirm_reset
    real_state = tool._grbl_post_reset_state
    tool._grbl_confirm_reset = lambda op: real_confirm(op, timeout=0.3)
    tool._grbl_post_reset_state = lambda op: real_state(op, timeout=0.3)


def record_exit(tool):
    """Record the results of _grbl_exit_check_mode()."""
    results = []
    real_exit = tool._grbl_exit_check_mode

    def exit_check_mode(op):
        results.append(real_exit(op))
        return results[-1]
    tool._grbl_exit_check_mode = exit_check_mode
    return results


def exit_tool(fake):
    """A tool with an operation that has just finished a validation in check mode."""
    tool = make_stream_tool(fake)
    fast_timeouts(tool)
    op = tool._grbl_reserve('stream', motion=True)
    tool._grbl_stream_dirty = True
    return tool, op


class TestExitCheckMode(unittest.TestCase):
    def test_exit_separate_replies(self):
        fake = CheckFake(in_check=True)
        tool, op = exit_tool(fake)
        self.assertEqual(tool._grbl_exit_check_mode(op), 'idle')
        self.assertIsNone(tool._grbl_recovery)
        self.assertFalse(op.failed)
        tool._grbl_release(op)
        self.assertIsNotNone(tool._grbl_reserve('stream', motion=True))

    def test_exit_one_chunk(self):
        fake = CheckFake(in_check=True)
        fake.one_chunk = True
        tool, op = exit_tool(fake)
        self.assertEqual(tool._grbl_exit_check_mode(op), 'idle')
        self.assertIsNone(tool._grbl_recovery)
        tool._grbl_release(op)
        self.assertIsNotNone(tool._grbl_reserve('stream', motion=True))

    def test_exit_alarm(self):
        fake = CheckFake(in_check=True)
        fake.after_exit_state = 'Alarm'      # the real _grbl_post_reset_state reads <Alarm|...>
        tool, op = exit_tool(fake)
        self.assertEqual(tool._grbl_exit_check_mode(op), 'alarm')
        self.assertEqual(tool._grbl_recovery, 'needs_home')
        self.assertFalse(op.failed)
        tool._grbl_release(op)
        self.assertIsNone(tool._grbl_reserve('stream', motion=True))
        self.assertIsNotNone(tool._grbl_reserve('home', motion=True, allow_in_recovery=True))

    def test_exit_real_alarm_line(self):
        fake = CheckFake(in_check=True, replies={'?': ['ALARM:1']})
        tool, op = exit_tool(fake)
        self.assertEqual(tool._grbl_exit_check_mode(op), 'failed')
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertTrue(op.failed)

    def test_exit_no_banner(self):
        fake = CheckFake()
        fake.exit_lines = ['[MSG:Disabled]', 'ok']
        tool = make_stream_tool(fake, check_mode=True)
        fast_timeouts(tool)
        results = record_exit(tool)
        tool.on_start()
        self.assertEqual(results, ['failed'])
        self.assertEqual(ended_how(tool), 'check_exit_failed')
        self.assertFalse(has_success(tool))
        self.assertIn('needs_reset', (tool._grbl_recovery,))

    def test_exit_no_status(self):
        fake = CheckFake()
        fake.mute_status_after_exit = True
        tool = make_stream_tool(fake, check_mode=True)
        fast_timeouts(tool)
        results = record_exit(tool)
        tool.on_start()
        self.assertEqual(results, ['failed'])
        self.assertEqual(ended_how(tool), 'check_exit_failed')
        self.assertFalse(has_success(tool))
        self.assertIsNotNone(tool._grbl_recovery)

    def test_exit_cancelled(self):
        fake = CheckFake()
        tool = make_stream_tool(fake, check_mode=True)
        fast_timeouts(tool)
        results = record_exit(tool)
        stop = {}

        def hook():
            # the user presses Stop while the worker waits for the banner
            if fake.exiting and 'generation' not in stop:
                stop['generation'] = tool._grbl_safety_generation + 1
                tool.on_grbl_stop()
        fake.read_hook = hook
        tool.on_start()
        self.assertEqual(results, ['failed'])
        self.assertNotEqual(ended_how(tool), 'check_passed')
        self.assertFalse(has_success(tool))
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertEqual(tool._grbl_safety_generation, stop['generation'])
        self.assertFalse(tool._grbl_reset_pending)
        self.assertTrue(tool._grbl_stream_dirty)


class TestCheckModeJob(unittest.TestCase):
    def test_check_passed(self):
        fake = CheckFake()
        tool = make_stream_tool(fake, check_mode=True)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'check_passed')
        self.assertTrue(any('[success]' in t and 'no error' in t for t in emitted(tool)))
        self.assertFalse(fake.in_check)
        self.assertIsNone(tool._grbl_recovery)
        self.assertFalse(tool._grbl_stream_dirty)
        self.assertEqual(fake.commands().count('$C'), 2)         # enter and exit

    def test_check_passed_needs_home(self):
        fake = CheckFake()
        fake.after_exit_state = 'Alarm'
        tool = make_stream_tool(fake, check_mode=True)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'check_passed_needs_home')
        self.assertFalse(has_success(tool))
        self.assertTrue(any('[WARNING_NOTCL]' in t and 'Press Home' in t for t in emitted(tool)))
        self.assertEqual(tool._grbl_recovery, 'needs_home')

    def test_stop_during_check_stream(self):
        fake = CheckFake()
        tool = make_stream_tool(fake, check_mode=True)
        stop = {}

        def hook():
            if 'done' not in stop and sum(1 for t in fake.commands() if t.startswith('G1')) >= 3:
                stop['done'] = True
                tool.on_grbl_stop()
        fake.read_hook = hook
        tool.on_start()
        self.assertTrue(stop)
        self.assertEqual(ended_how(tool), 'stopped')
        commands = fake.commands()
        self.assertEqual(commands.count('$C'), 1)                 # no $C after the Stop
        self.assertIn(b'!', fake.written)
        self.assertTrue(fake.in_check)
        self.assertFalse(has_success(tool))
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertTrue(tool._grbl_stream_dirty)

    def test_check_errors_no_success(self):
        fake = CheckFake(replies={'G1 X01': ['error:20']})
        tool = make_stream_tool(fake, source='G1 X00.000 Y0.000 F100\nG1 X01.000 Y0.000 F100\nG1 X02.000 Y0.000 F100\n',
                                check_mode=True)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'check_failed')
        self.assertFalse(has_success(tool))
        self.assertEqual(tool._stream_result['errors'], [2])
        self.assertTrue(any('[ERROR_NOTCL]' in t and '2' in t for t in emitted(tool)))
        self.assertIsNone(tool._grbl_recovery)
        self.assertFalse(fake.in_check)

    def test_enter_rejected_in_check(self):
        fake = CheckFake(in_check=True)
        tool = make_stream_tool(fake, check_mode=True)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'rejected')
        self.assertFalse([t for t in fake.commands() if t.startswith('G1')])
        self.assertNotIn('$C', fake.commands())
        self.assertTrue(any('GRBL is in check mode' in t for t in emitted(tool)))
        self.assertFalse(has_success(tool))
        self.assertFalse(tool._grbl_stream_dirty)
        self.assertIsNone(tool._grbl_recovery)
        self.assertIsNone(tool._grbl_op)

    def test_levelled_check_order(self):
        # GRBL refuses $# in Check: a levelled check-mode Start must read the frame before $C
        class NoHashInCheck(CheckFake):
            def _answer(self, cmd):
                if cmd == '$#' and self.in_check:
                    self._send('error:8')
                    return
                super()._answer(cmd)

        fake = NoHashInCheck()
        tool, _target = make_levelled_stream_tool(fake, check_mode=True)
        tool.on_start()
        commands = fake.commands()
        first_check = commands.index('$C')
        self.assertTrue([i for i, c in enumerate(commands) if c == '$#'])
        self.assertTrue(all(i < first_check for i, c in enumerate(commands) if c == '$#'))
        self.assertEqual(commands.count('$#'), 2)               # phase 1 and phase 2
        self.assertEqual(commands.count('$C'), 2)               # enter and exit
        self.assertEqual(len([c for c in commands if c.startswith('G01 X')]), 4)   # the job streamed
        self.assertEqual(ended_how(tool), 'check_passed')
        self.assertFalse(fake.in_check)


if __name__ == '__main__':
    unittest.main()
