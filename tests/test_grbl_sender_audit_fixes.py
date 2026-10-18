#!/usr/bin/env python
"""Regressions for GRBL recovery, controller resets, map visuals and the outcome gate."""
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.grbl_stream_helpers import (
    CheckFake, FakeGrbl, ended_how, gcode, has_success, make_stream_tool, make_levelled_stream_tool,
)
from tests.test_grbl_sender_construct import make_app
from appPlugins.ToolGrblSender.Sender import ToolGrblSender
from appPlugins.ToolGrblSender.SenderGrbl import stream_lines
from tests.gates.run_gate import check_junit, run_pytest


class TestResumeBypass(unittest.TestCase):
    @staticmethod
    def make_button_tool():
        tool = ToolGrblSender(make_app())
        fake = FakeGrbl()
        tool.grbl_ser_port = fake
        tool._grbl_connected = True
        return tool, fake

    def test_resume_blocked_after_stop(self):
        tool, fake = self.make_button_tool()
        tool._grbl_stream_dirty = True
        tool.on_grbl_stop()
        tool.ui.resume_button.click()
        self.assertEqual(fake.written, [b'!'])

    def test_resume_blocked_pending_reset(self):
        tool, fake = self.make_button_tool()
        tool._grbl_reset_pending = True
        tool.ui.resume_button.click()
        self.assertEqual(fake.written, [])

    def test_healthy_active_hold_resume(self):
        tool, fake = self.make_button_tool()
        self.assertIsNotNone(tool._grbl_reserve('stream', motion=True))
        tool._grbl_stream_dirty = True
        tool.ui.hold_button.click()
        tool.ui.resume_button.click()
        self.assertEqual(fake.written, [b'!', b'~'])

    def test_resume_blocked_after_stream_failure(self):
        tool, fake = self.make_button_tool()
        op = tool._grbl_reserve('stream', motion=True)
        tool._grbl_stream_dirty = True
        with tool._grbl_op_lock:
            tool._grbl_abort_stream_locked(op, 'error')
        tool.ui.resume_button.click()
        self.assertNotIn(b'~', fake.written)

    def test_resume_blocked_for_abandoned_dirty_stream(self):
        tool, fake = self.make_button_tool()
        tool._grbl_stream_dirty = True
        tool.ui.resume_button.click()
        self.assertEqual(fake.written, [])

    def test_resume_contention_worker_wins_lock(self):
        fake = FakeGrbl()
        tool = make_stream_tool(fake)
        lock = tool._grbl_op_lock
        attempting = threading.Event()
        finished = threading.Event()

        class AnnouncedLock:
            def __enter__(self):
                attempting.set()
                lock.acquire()

            def __exit__(self, *_args):
                lock.release()

        tool._grbl_op_lock = AnnouncedLock()

        def resume():
            tool._on_resume_button()
            finished.set()

        thread = threading.Thread(target=resume, daemon=True)
        with lock:
            thread.start()
            self.assertTrue(attempting.wait(2.0))
            self.assertFalse(finished.is_set())
            tool._grbl_recovery = 'needs_reset'
        thread.join(2.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(finished.is_set())
        self.assertNotIn(b'~', fake.written)


class ResetDuringCheckFake(CheckFake):
    def __init__(self):
        super().__init__()
        self.g1_count = 0
        self.banner_seen = False
        self.writes_after_banner = []

    def _answer(self, cmd):
        if cmd.startswith('G1 '):
            self.g1_count += 1
            if self.g1_count == 3:
                self.rx.clear()
                self.in_check = False
                self.state = 'Idle'
                self._send("Grbl 1.1h ['$' for help]")
            if self.banner_seen:
                self.writes_after_banner.append(cmd)
        super()._answer(cmd)

    def readline(self):
        chunk = super().readline()
        if chunk.startswith(b'Grbl '):
            self.banner_seen = True
        return chunk


class TestUnexpectedReset(unittest.TestCase):
    def test_unexpected_reset_full_worker(self):
        fake = ResetDuringCheckFake()
        tool = make_stream_tool(fake, source=gcode(20), check_mode=True)

        def short_timeout(*args, **kwargs):
            return stream_lines(*args, **kwargs, stall_timeout=0.02)

        with patch('appPlugins.ToolGrblSender.Sender.stream_lines', side_effect=short_timeout):
            tool.on_start()
        self.assertTrue(fake.banner_seen)
        self.assertEqual(fake.writes_after_banner, [])
        self.assertEqual(ended_how(tool), 'unexpected_reset')
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertTrue(tool._grbl_stream_dirty)
        self.assertFalse(has_success(tool))

    def test_fragmented_banner_stops_normal_stream(self):
        chunks = iter([b'Gr', b"bl 1.1h ['$' for help]\r\n"])
        writes = []

        def write(data):
            writes.append(data)
            return 'ok'

        result = stream_lines(['G1 X1 F100', 'G1 X2 F100'], write, lambda: next(chunks), rx_size=12)
        self.assertEqual(result['status'], 'unexpected_reset')
        self.assertEqual(writes, [b'G1 X1 F100\n'])

    def test_expected_check_exit_still_succeeds(self):
        tool = make_stream_tool(CheckFake(), check_mode=True)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'check_passed')
        self.assertIsNone(tool._grbl_recovery)
        self.assertFalse(tool._grbl_stream_dirty)

    def test_reset_after_check_preflight_prevents_first_job_write(self):
        class ResetAfterCheckReport(CheckFake):
            def _answer(self, cmd):
                was_check = self.in_check
                super()._answer(cmd)
                if cmd == '?' and was_check:
                    self.in_check = False
                    self.state = 'Idle'
                    self._send("Grbl 1.1h ['$' for help]")

        fake = ResetAfterCheckReport()
        tool = make_stream_tool(fake, check_mode=True)
        tool.on_start()
        self.assertFalse(any(cmd.startswith('G1 ') for cmd in fake.commands()))
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertTrue(tool._grbl_stream_dirty)
        self.assertFalse(has_success(tool))

    def test_reset_during_final_idle_query_is_not_success(self):
        class ResetAtCompletion(FakeGrbl):
            def _answer(self, cmd):
                if cmd == '?' and any(line.startswith('G1 ') for line in self.commands()):
                    self._send("Grbl 1.1h ['$' for help]")
                super()._answer(cmd)

        tool = make_stream_tool(ResetAtCompletion(), source='G1 X1 F100\n')
        tool.on_start()
        self.assertNotEqual(ended_how(tool), 'finished')
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertTrue(tool._grbl_stream_dirty)
        self.assertFalse(has_success(tool))


class TestStaleHeightMesh(unittest.TestCase):
    @staticmethod
    def make_display_tool():
        tool, _target = make_levelled_stream_tool(FakeGrbl())
        canvas = MagicMock()
        tool.app.plotcanvas3d = canvas
        tool.view3d = SimpleNamespace(canvas=canvas, set_height_map=MagicMock(), set_toolpath=MagicMock(),
                                      probing_shapes=MagicMock())
        tool._update_3d_height_map()
        tool.view3d.set_height_map.reset_mock()
        return tool

    def test_clear_probe_data_clears_mesh(self):
        tool = self.make_display_tool()
        tool._clear_probe_data()
        self.assertFalse(tool.al_heights_valid)
        tool.view3d.set_height_map.assert_called_once_with(None)

    def test_on_show_3d_failed_build_clears_mesh(self):
        tool = self.make_display_tool()
        tool.al_heights_valid = False
        tool.app.collection.get_by_name.return_value = None
        tool.on_show_3d()
        tool.view3d.set_toolpath.assert_called_once_with([])
        tool.view3d.set_height_map.assert_called_once_with(None)

    def test_replacement_start_clears_mesh(self):
        tool = self.make_display_tool()
        self.assertIsNotNone(tool._al_capture_context(replacement=True))
        self.assertFalse(tool.al_heights_valid)
        tool.view3d.set_height_map.assert_called_once_with(None)


class TestGateIntegrity(unittest.TestCase):
    def check_report(self, text, subtest_count=0):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'report.xml')
            with open(path, 'w', encoding='utf-8') as report:
                report.write(text)
            return check_junit(path, subtest_count=subtest_count)

    @staticmethod
    def report(declared, cases=1):
        return ('<testsuite tests="%d">' % declared +
                ''.join('<testcase name="case%d" />' % i for i in range(cases)) + '</testsuite>')

    def test_unexplained_missing_cases_rejected(self):
        for declared in (2, 100):
            with self.subTest(declared=declared):
                error, _counts = self.check_report(self.report(declared))
                self.assertIsNotNone(error)

    def test_exact_passed_subtest_count_accepted(self):
        error, counts = self.check_report(self.report(101), subtest_count=100)
        self.assertIsNone(error)
        self.assertEqual(counts, {'passed': 1})

    def test_wrong_subtest_count_rejected(self):
        error, _counts = self.check_report(self.report(101), subtest_count=99)
        self.assertIsNotNone(error)

    def test_extra_cases_rejected(self):
        error, _counts = self.check_report(self.report(1, cases=2))
        self.assertIsNotNone(error)

    def test_malformed_xml_rejected(self):
        error, _counts = self.check_report('<not valid xml<<<')
        self.assertIsNotNone(error)

    def test_actual_pytest_passed_failed_and_skipped_subtests(self):
        source = '''import unittest

class TestSubtests(unittest.TestCase):
    def test_passed(self):
        for i in range(100):
            with self.subTest(i=i):
                self.assertTrue(True)

    def test_failed(self):
        with self.subTest(i=0):
            self.assertTrue(False)

    def test_skipped_subtest(self):
        with self.subTest(i=0):
            self.skipTest('subtest skip')

    @unittest.skip('setup skip')
    def test_skipped(self):
        pass
'''
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'test_subtests.py')
            with open(path, 'w', encoding='utf-8') as test_file:
                test_file.write(source)
            code, outcomes, error, _counts = run_pytest([path])
        self.assertEqual(code, 1)
        self.assertIsNone(error)
        self.assertEqual(next(v for k, v in outcomes.items() if k.endswith('::test_failed')), 'failed')
        self.assertEqual(next(v for k, v in outcomes.items() if k.endswith('::test_passed')), 'passed')
        self.assertEqual(next(v for k, v in outcomes.items() if k.endswith('::test_skipped')), 'skipped')


if __name__ == '__main__':
    unittest.main()
