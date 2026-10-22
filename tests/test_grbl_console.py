#!/usr/bin/env python
"""Program display in the sender dock follows GRBL acknowledgements, not execution."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6 import QtGui, QtWidgets

from appPlugins.ToolGrblSender.Sender import GrblConsole
from tests.grbl_stream_helpers import CheckFake, make_stream_tool, make_levelled_stream_tool


_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class TestGrblConsole(unittest.TestCase):

    def make_console(self, tool=None):
        if tool is None:
            tool = MagicMock()
            tool.app.options = {}
        console = GrblConsole(tool)
        self.addCleanup(console.deleteLater)
        self.addCleanup(console.close)
        return console

    def selected_lines(self, console):
        return [s.cursor.blockNumber() for s in console.program_view.extraSelections()]

    def attach_console(self, tool):
        dock = QtWidgets.QDockWidget()
        self.addCleanup(dock.deleteLater)
        tool.app.ui.grbl_console_dock = dock
        console = self.make_console(tool)
        dock.setWidget(console)
        tool.stream_progress_sig.emit.side_effect = tool._on_stream_progress
        tool.console_line_sig.emit.side_effect = console.append
        return console

    def test_program_and_console_tabs_keep_commands_and_log_separate(self):
        console = self.make_console()
        self.assertEqual([console.tabs.tabText(i) for i in range(console.tabs.count())],
                         ['Program', 'Console'])
        console.set_program(['G21', 'G1 X2'])
        console.append('ok')
        self.assertTrue(console.program_view.isReadOnly())
        self.assertEqual(console.program_view.toPlainText(), 'G21\nG1 X2')
        self.assertEqual(console.log_view.toPlainText(), 'ok')
        self.assertIs(console.program_area.number_bar.edit, console.program_view)
        console.cmd_entry.setText('  $G  ')
        console.send_btn.click()
        console.tool.send_console_command.assert_called_once_with('$G')

    def test_progress_highlights_acknowledged_line_and_follow_can_be_disabled(self):
        console = self.make_console()
        console.resize(600, 250)
        console.show()
        console.set_program(['G1 X%d' % i for i in range(1000)])
        _qapp.processEvents()
        console.follow_cb.setChecked(False)
        cursor = console.program_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        console.program_view.setTextCursor(cursor)
        scroll = console.program_view.verticalScrollBar().value()

        console.update_progress(800)
        self.assertEqual(self.selected_lines(console), [799])
        self.assertIn('800 / 1000', console.program_status.text())
        self.assertEqual(console.program_view.textCursor().blockNumber(), 799)
        self.assertEqual(console.program_view.textCursor().selectedText(), 'G1 X799')
        self.assertEqual(console.program_view.verticalScrollBar().value(), scroll)

        console.follow_cb.setChecked(True)
        self.assertEqual(console.program_view.textCursor().blockNumber(), 799)
        self.assertEqual(console.program_view.textCursor().selectedText(), 'G1 X799')
        self.assertGreater(console.program_view.verticalScrollBar().value(), scroll)


    def test_click_selects_whole_line_and_progress_advances_selection(self):
        from PyQt6 import QtCore, QtTest

        console = self.make_console()
        lines = ['G21', 'G90', 'G1 X2', 'M2']
        console.set_program(lines)
        console.resize(600, 250)
        console.show()
        _qapp.processEvents()
        for index in (2, 0, 3):
            cursor = QtGui.QTextCursor(console.program_view.document().findBlockByNumber(index))
            point = console.program_view.cursorRect(cursor).center() + QtCore.QPoint(2, 0)
            QtTest.QTest.mouseClick(console.program_view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                   pos=point)
            self.assertEqual(console.program_view.textCursor().selectedText(), lines[index])
            console.tool.on_program_line_selected.assert_called_with(index)
        for done in (1, 2, 3, 4):
            console.update_progress(done)
            self.assertEqual(console.program_view.textCursor().selectedText(), lines[done - 1])
        console.update_progress(3, [1])
        self.assertIn(1, self.selected_lines(console))
        self.assertEqual(console.program_view.extraSelections()[-1].format.background().color(),
                         QtGui.QColor('#c62828'))
        console.set_program(['G90'])
        self.assertFalse(console.program_view.textCursor().hasSelection())

    def test_ctrl_and_shift_selection_flash_all_selected_moves(self):
        import numpy as np
        from PyQt6 import QtCore, QtTest
        from tests.test_grbl_view3d import show_tool, SPLIT_ARC_JOB

        tool = show_tool(SPLIT_ARC_JOB, 'send')
        console = self.attach_console(tool)
        tool._console = MagicMock(return_value=console)
        tool.on_show_3d()
        self.addCleanup(tool.view3d.clear)
        dock = tool.app.ui.grbl_console_dock
        dock.resize(600, 300)
        dock.show()
        _qapp.processEvents()

        def click(index, expected, modifier=QtCore.Qt.KeyboardModifier.NoModifier):
            cursor = QtGui.QTextCursor(console.program_view.document().findBlockByNumber(index))
            point = console.program_view.cursorRect(cursor).center() + QtCore.QPoint(2, 0)
            QtTest.QTest.mouseClick(console.program_view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                   modifier, pos=point)
            self.assertEqual(set(self.selected_lines(console)), expected)
            points = [p for i, a, b, rapid in tool.view3d._segments if i in expected for p in (a, b)]
            np.testing.assert_allclose(tool.view3d.selected.pos, np.array(points).reshape(-1, 3), atol=1e-6)
            self.assertEqual(tool.view3d._selection_timer.isActive(), bool(points))

        ctrl = QtCore.Qt.KeyboardModifier.ControlModifier
        shift = QtCore.Qt.KeyboardModifier.ShiftModifier
        click(3, {3})
        click(4, {3, 4}, ctrl)
        tool.view3d._flash_selection()
        self.assertFalse(tool.view3d.selected.visible)
        click(3, {4}, ctrl)
        self.assertTrue(tool.view3d.selected.visible)
        click(4, {3, 4}, shift)
        click(1, {1, 2, 3}, shift)
        click(4, {4})
        click(4, set(), ctrl)
        click(0, {0})
        click(4, {0, 1, 2, 3, 4}, shift)
        console.clear_program_selection()
        self.assertEqual(self.selected_lines(console), [])
        self.assertFalse(tool.view3d._selection_timer.isActive())

        tool._program_paused = True
        click(3, {3})
        click(4, {3, 4}, ctrl)
        console.update_progress(1, [1])
        self.assertEqual(set(self.selected_lines(console)), {0, 1, 3, 4})
        self.assertEqual(console.program_view.extraSelections()[-1].format.background().color(),
                         QtGui.QColor('#c62828'))
        tool._on_status_report({'state': 'Run'})
        self.assertEqual(set(self.selected_lines(console)), {0, 1})
        self.assertFalse(tool.view3d._selection_timer.isActive())
        console.set_program(['G90'])
        self.assertEqual(self.selected_lines(console), [])

    def test_preview_console_and_manual_plot_selection_share_prepared_lines(self):
        import numpy as np
        from tests.test_grbl_view3d import show_tool, SPLIT_ARC_JOB

        for mode in ('send', 'split'):
            with self.subTest(mode=mode):
                tool = show_tool(SPLIT_ARC_JOB, mode)
                console = self.attach_console(tool)
                tool._console = MagicMock(return_value=console)
                tool.on_show_3d()
                self.assertEqual(console.program_view.toPlainText().splitlines(), tool.job_lines)
                index = tool.view3d._segments[0][0]
                console.program_line_selected.emit(index)
                expected = [p for i, a, b, rapid in tool.view3d._segments if i == index for p in (a, b)]
                np.testing.assert_allclose(tool.view3d.selected.pos, expected)
                console.program_line_selected.emit(len(tool.job_lines) - 1)
                self.assertEqual(tool.view3d.selected.pos.shape, (2, 3))
                console.program_line_selected.emit(0)
                self.assertEqual(tool.view3d.selected.pos.shape, (0, 3))

    def test_paused_selection_preserves_green_progress_and_resume_clears_red(self):
        from tests.test_grbl_view3d import show_tool, SPLIT_ARC_JOB

        tool = show_tool(SPLIT_ARC_JOB, 'send')
        console = self.attach_console(tool)
        tool._console = MagicMock(return_value=console)
        tool.on_show_3d()
        op = tool._grbl_reserve('stream', motion=True)
        self.addCleanup(tool._grbl_release, op)
        tool._on_status_report({'state': 'Run'})
        tool._on_stream_progress(4, 5)
        console.program_line_selected.emit(4)
        self.assertEqual(tool.view3d.selected.pos.shape, (0, 3))
        self.assertEqual(console.program_view.textCursor().blockNumber(), 3)
        tool._on_status_report({'state': 'Hold:0'})
        console.program_line_selected.emit(4)
        self.assertEqual(tool.view3d.selected.pos.shape, (2, 3))
        accepted = tool.view3d.accepted.pos.copy()
        console.program_line_selected.emit(3)
        self.assertGreater(tool.view3d.selected.pos.shape[0], 2)
        tool._on_preview_ready(tool.preview_ready_sig.emit.call_args.args[0])
        self.assertEqual(tool.view3d.selected.pos.shape, accepted.shape)
        self.assertEqual(tool.view3d.accepted.pos.shape, accepted.shape)
        tool._on_stream_progress(5, 5)
        self.assertEqual(tool.view3d.selected.pos.shape, accepted.shape)
        self.assertEqual(tuple(tool.view3d.accepted.color), (0.1, 0.7, 0.3, 1.0))
        tool._on_status_report({'state': 'Run'})
        self.assertEqual(tool.view3d.selected.pos.shape, (0, 3))
        self.assertEqual(console.program_view.textCursor().blockNumber(), 4)

    def test_start_rebuilds_plot_from_stream_program_and_clears_manual_selection(self):
        from appPlugins.Common.gcode_segment import parse_toolpath
        from tests.test_grbl_view3d import show_tool, SPLIT_ARC_JOB

        tool = show_tool(SPLIT_ARC_JOB, 'split')
        console = self.attach_console(tool)
        tool._console = MagicMock(return_value=console)
        tool.on_show_3d()
        tool.view3d.set_toolpath([(0, (100, 100, 0), (200, 200, 0), False)])
        tool.view3d.set_selected_line(0)
        tool._program_paused = True
        tool.on_start()
        self.assertEqual(tool.view3d._segments, parse_toolpath(tool.job_lines))
        self.assertEqual(tool.view3d.selected.pos.shape, (0, 3))
        self.assertFalse(tool._program_paused)
        self.assertEqual(console.program_view.toPlainText().splitlines(), tool.job_lines)

    def test_program_stays_read_only_with_editor_shortcuts(self):
        from PyQt6 import QtCore, QtTest

        console = self.make_console()
        console.set_program(['G21', 'G1 X2'])
        console.program_view.selectAll()
        QtTest.QTest.keyClicks(console.program_view, '(edited)')
        QtTest.QTest.keyClick(console.program_view, QtCore.Qt.Key.Key_Slash,
                             QtCore.Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(console.program_view.toPlainText(), 'G21\nG1 X2')

    def test_outside_click_clears_manual_selection_and_flashing(self):
        from PyQt6 import QtCore, QtTest
        from tests.test_grbl_view3d import show_tool, SPLIT_ARC_JOB

        tool = show_tool(SPLIT_ARC_JOB, 'send')
        console = self.attach_console(tool)
        tool._console = MagicMock(return_value=console)
        tool.on_show_3d()
        self.addCleanup(tool.view3d.clear)
        dock = tool.app.ui.grbl_console_dock
        dock.resize(600, 300)
        dock.show()
        outside = QtWidgets.QLabel('Outside the program')
        self.addCleanup(outside.deleteLater)
        _qapp.processEvents()
        index = tool.view3d._segments[0][0]
        for paused in (False, True):
            tool._program_paused = paused
            tool._on_stream_progress(4, len(tool.job_lines))
            for target in (console.follow_cb, outside):
                cursor = QtGui.QTextCursor(console.program_view.document().findBlockByNumber(index))
                point = console.program_view.cursorRect(cursor).center() + QtCore.QPoint(2, 0)
                QtTest.QTest.mouseClick(console.program_view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                       pos=point)
                self.assertTrue(console.program_view.textCursor().hasSelection())
                self.assertGreater(tool.view3d.selected.pos.size, 0)
                accepted = tool.view3d.accepted.pos.copy()
                QtTest.QTest.mouseClick(target, QtCore.Qt.MouseButton.LeftButton)
                _qapp.processEvents()
                self.assertFalse(console.program_view.textCursor().hasSelection())
                self.assertEqual(tool.view3d.selected.pos.shape, (0, 3))
                self.assertFalse(tool.view3d._selection_timer.isActive())
                self.assertEqual(tool.view3d.accepted.pos.tolist(), accepted.tolist())

        console.program_line_selected.emit(index)
        dock.hide()
        self.assertFalse(tool.view3d._selection_timer.isActive())

    def test_new_program_clears_progress_and_errors_but_keeps_log(self):
        console = self.make_console()
        console.append('error:20')
        console.set_program(['G21', 'G1 X1'])
        console.update_progress(2, [1])
        self.assertIn(1, self.selected_lines(console))
        console.set_program(['G90'])
        self.assertEqual(self.selected_lines(console), [])
        self.assertIn('0 / 1', console.program_status.text())
        self.assertEqual(console.log_view.toPlainText(), 'error:20')

    def test_stream_loads_prepared_lines_before_worker_and_tracks_replies(self):
        tool = make_stream_tool(CheckFake(), source='(header)\nG21\nG90\nG1 X2\nM2\n')
        console = self.attach_console(tool)
        run_worker = tool.app.worker_task.emit.side_effect

        def worker(task):
            self.assertEqual(console.program_view.toPlainText().splitlines(), tool.job_lines)
            self.assertEqual(self.selected_lines(console), [])
            run_worker(task)

        tool.app.worker_task.emit.side_effect = worker
        tool.on_start()
        self.assertEqual(self.selected_lines(console), [len(tool.job_lines) - 1])
        self.assertIn('4 / 4', console.program_status.text())
        self.assertIn('ok', console.log_view.toPlainText())

    def test_source_changes_reload_program_and_clear_missing_source(self):
        from tests.test_grbl_frame import patch_object_changed

        tool = make_stream_tool(CheckFake())
        patch_object_changed(tool)
        console = self.attach_console(tool)
        for source, expected in (('(header)\nG21\nG1 X3\n', ['G21', 'G1 X3']),
                                 ('G90\nG1 X8\n', ['G90', 'G1 X8']), ('', []), (None, [])):
            with self.subTest(source=source):
                target = SimpleNamespace(kind='cncjob', source_file=source, obj_options={'name': 'job'})
                tool.app.collection.get_by_name.return_value = target if source is not None else None
                console.tabs.setCurrentIndex(1)
                tool.on_object_changed()
                self.assertEqual(console.program_view.toPlainText().splitlines(), expected)
                self.assertEqual(console.tabs.currentIndex(), 0)
                self.assertEqual(self.selected_lines(console), [])

    def test_show_console_selects_program_and_focuses_gcode(self):
        tool = make_stream_tool(CheckFake())
        console = self.attach_console(tool)
        console.tabs.setCurrentIndex(1)
        tool.on_console_toggled(True)
        self.assertEqual(console.tabs.currentIndex(), 0)
        self.assertIs(tool.app.ui.grbl_console_dock.focusWidget(), console.program_view)

    def test_source_change_does_not_replace_a_running_stream_display(self):
        from tests.test_grbl_frame import patch_object_changed

        tool = make_stream_tool(CheckFake())
        patch_object_changed(tool)
        console = self.attach_console(tool)
        console.set_program(['G21', 'G1 X2'])
        console.update_progress(1)
        op = tool._grbl_reserve('stream', motion=True)
        self.assertIsNotNone(op)
        self.addCleanup(tool._grbl_release, op)
        tool.on_object_changed()
        self.assertEqual(console.program_view.toPlainText(), 'G21\nG1 X2')
        self.assertEqual(self.selected_lines(console), [0])

    def test_levelled_program_displays_transformed_lines(self):
        tool, target = make_levelled_stream_tool(CheckFake())
        console = self.attach_console(tool)
        tool.on_start()
        self.assertEqual(console.program_view.toPlainText().splitlines(), tool.job_lines)
        self.assertNotEqual(console.program_view.toPlainText(), target.source_file.strip())
        self.assertEqual(self.selected_lines(console), [len(tool.job_lines) - 1])

    def test_errors_highlight_stream_rows_instead_of_source_line_numbers(self):
        for check_mode in (False, True):
            with self.subTest(check_mode=check_mode):
                fake = CheckFake(replies={'G1': ['error:20']})
                tool = make_stream_tool(fake, source='(header)\nG21\nG90\nG1 X1\nG1 X2\nM2\n',
                                        check_mode=check_mode)
                console = self.attach_console(tool)
                tool.on_start()
                rows = self.selected_lines(console)
                error_rows = [s.cursor.blockNumber() for s in console.program_view.extraSelections()
                              if s.format.background().color() == QtGui.QColor('#c62828')]
                self.assertEqual(error_rows, [2, 3] if check_mode else [2])
                self.assertIn(2, rows)
                self.assertIn('error:20', console.log_view.toPlainText())


if __name__ == '__main__':
    unittest.main()
