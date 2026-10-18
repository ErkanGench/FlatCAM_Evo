#!/usr/bin/env python
"""Restart uses the preceding program position, never the selected move's endpoint."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import MagicMock

from appPlugins.ToolGrblSender import SenderGen


PROGRAM = ['G21', 'G90', 'G17', 'G54', 'F100', 'M3 S12000', 'G0 Z3',
           'G0 X1 Y2', 'G1 Z-0.2', 'G2 X5 Y2 I2 J0', 'M5', 'M2']


class TestRestartPreamble(unittest.TestCase):

    def preamble(self, lines=PROGRAM, start=10, travel=3, units='MM'):
        self.assertTrue(callable(getattr(SenderGen, 'restart_preamble', None)),
                        'SenderGen needs a state-aware restart preamble')
        return SenderGen.restart_preamble(lines, start, travel, units)[0]

    def test_clearance_xy_spindle_plunge_then_restore_arc_mode(self):
        result = self.preamble()
        lift = result.index('G0 Z3.0000')
        xy = result.index('G0 X1.0000 Y2.0000')
        spindle = result.index('M3 S12000.0000')
        plunge = result.index('G1 Z-0.2000 F100.0000')
        self.assertLess(lift, xy)
        self.assertLess(xy, spindle)
        self.assertLess(spindle, plunge)
        self.assertEqual(result[-1], 'G1')
        self.assertNotIn(PROGRAM[9], result)
        self.assertNotIn('M2', result)

    def test_incremental_and_implicit_moves_reconstruct_the_preceding_position(self):
        lines = PROGRAM[:9] + ['G91', 'G1 X2 Y3 Z-0.1', 'X1', 'X2']
        result = self.preamble(lines, len(lines))
        self.assertIn('G0 X4.0000 Y5.0000', result)
        self.assertIn('G1 Z-0.3000 F100.0000', result)
        self.assertEqual(result[-2:], ['G91', 'G1'])

    def test_modal_arc_is_restored_after_the_synthetic_linear_plunge(self):
        result = self.preamble(PROGRAM[:10] + ['X1 Y2 I-2 J0'], 11)
        self.assertIn('G0 X5.0000 Y2.0000', result)
        self.assertNotIn('G2', result)

    def test_beginning_does_not_require_a_position_or_travel_height(self):
        self.assertEqual(self.preamble(['G1 X1'], 1, None), [])

    def test_unknown_position_and_side_effects_are_refused(self):
        cases = [(['G21', 'G90', 'G1 X1', 'G1 X2'], 4),
                 (PROGRAM[:9] + ['G92 X0', 'G1 X2'], 11),
                 (PROGRAM[:9] + ['G38.2 Z-3 F50', 'G1 X2'], 11),
                 (PROGRAM[:9] + ['M6 T2', 'G1 X2'], 11),
                 (PROGRAM[:9] + ['M2', 'G1 X2'], 11),
                 (PROGRAM[:9] + ['$H', 'G1 X2'], 11)]
        for lines, start in cases:
            with self.subTest(lines=lines):
                with self.assertRaises(ValueError):
                    self.preamble(lines, start)

    def test_invalid_range_height_and_nonfinite_values_are_refused(self):
        for start, travel in ((0, 3), (13, 3), (10, float('nan')), (10, -1)):
            with self.subTest(start=start, travel=travel):
                with self.assertRaises(ValueError):
                    self.preamble(start=start, travel=travel)

    def test_spindle_and_coolant_use_final_state_without_replaying_stops(self):
        lines = PROGRAM[:9] + ['M5', 'M3 S9000', 'M8', 'M9', 'M7', 'G1 X2']
        result = self.preamble(lines, len(lines))
        self.assertEqual([s for s in result if s.startswith('M3')], ['M3 S9000.0000'])
        self.assertNotIn('M8', result)
        self.assertIn('M7', result)

    def test_units_change_converts_travel_height_and_modal_feed(self):
        lines = PROGRAM[:9] + ['G20', 'G0 X1 Y2 Z0.1', 'G1 X2']
        result = self.preamble(lines, len(lines), 25.4)
        self.assertIn('G20', result)
        self.assertIn('G0 Z1.0000', result)
        self.assertIn('G1 Z0.1000 F3.9370', result)

    def test_undeclared_work_frame_and_tool_offset_are_left_intact(self):
        lines = [s for s in PROGRAM if s != 'G54']
        result = self.preamble(lines, 9)
        self.assertNotIn('G54', result)
        self.assertNotIn('G49', result)

    def test_tool_length_offset_is_converted_to_the_active_units(self):
        lines = PROGRAM[:9] + ['G43.1 Z25.4', 'G20', 'G0 X1 Y2 Z0.1', 'G1 X2']
        result = self.preamble(lines, len(lines), 25.4)
        self.assertIn('G43.1 Z1.0000', result)

    def test_first_cut_can_supply_its_own_feed_when_no_reentry_plunge_is_needed(self):
        lines = ['G21', 'G90', 'M3 S12000', 'G0 X1 Y2 Z3', 'G1 Z-0.2 F100']
        result = self.preamble(lines, len(lines))
        self.assertIn('G0 X1.0000 Y2.0000', result)
        self.assertFalse(any(s.startswith('G1 Z') for s in result))
        self.assertEqual(result[-1], 'G0')


class TestStartDialog(unittest.TestCase):

    def test_default_bounds_tooltip_and_line_visibility(self):
        from PyQt6 import QtWidgets
        from appPlugins.ToolGrblSender import Sender
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertTrue(hasattr(Sender, 'GrblStartDialog'), 'Start needs a Beginning/Line dialog')
        dialog = Sender.GrblStartDialog(123)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.start_radio.get_value(), 'beginning')
        self.assertTrue(dialog.line_entry.isHidden())
        self.assertEqual(dialog.line_entry.minimum(), 1)
        self.assertEqual(dialog.line_entry.maximum(), 123)
        self.assertEqual(dialog.start_radio.toolTip(),
                         'Select from where the job starts:\n'
                         '- Beginning: start from the first line\n'
                         '- Line: start from a custom line')
        dialog.start_radio.set_value('line')
        self.assertFalse(dialog.line_entry.isHidden())
        dialog.line_entry.set_value(200)
        self.assertEqual(dialog.line_entry.get_value(), 123)
        self.assertIsNotNone(app)

    def test_ok_and_cancel_return_the_selected_line_or_none(self):
        from PyQt6 import QtCore, QtWidgets
        from appPlugins.ToolGrblSender.Sender import ToolGrblSender
        from tests.grbl_stream_helpers import CheckFake, make_stream_tool
        tool = make_stream_tool(CheckFake())
        tool.app.ui = QtWidgets.QMainWindow()
        self.addCleanup(tool.app.ui.deleteLater)
        for choice, expected in (('beginning', 1), ('line', 7), ('cancel', None)):
            def finish(choice=choice):
                dialog = QtWidgets.QApplication.activeModalWidget()
                if choice == 'cancel':
                    dialog.reject()
                else:
                    dialog.start_radio.set_value(choice)
                    dialog.line_entry.set_value(7)
                    dialog.accept()

            QtCore.QTimer.singleShot(0, finish)
            self.assertEqual(ToolGrblSender._choose_start_line(tool, 10), expected)


class TestSenderRestart(unittest.TestCase):

    def make_tool(self, start=10, check_mode=False):
        from tests.grbl_stream_helpers import CheckFake, make_stream_tool
        fake = CheckFake()
        tool = make_stream_tool(fake, '\n'.join(PROGRAM), check_mode=check_mode)
        tool.app.options['tools_grbl_arc_mode'] = 'send'
        tool._target().z_move = 3
        tool._choose_start_line = MagicMock(return_value=start)
        return tool, fake

    def test_restart_streams_preamble_and_selected_arc_with_original_console_numbering(self):
        from PyQt6 import QtWidgets
        from appPlugins.ToolGrblSender.Sender import GrblConsole
        tool, fake = self.make_tool()
        dock = QtWidgets.QDockWidget()
        console = GrblConsole(tool)
        dock.setWidget(console)
        self.addCleanup(dock.deleteLater)
        tool.app.ui.grbl_console_dock = dock
        tool.stream_progress_sig.emit.side_effect = tool._on_stream_progress
        tool.on_start()
        commands = fake.commands()
        self.assertNotIn('G0 X1 Y2', commands)
        self.assertIn('G0 X1.0000 Y2.0000', commands)
        self.assertLess(commands.index('G1 Z-0.2000 F100.0000'), commands.index(PROGRAM[9]))
        self.assertEqual(commands.count(PROGRAM[9]), 1)
        self.assertEqual(console.program_view.toPlainText().splitlines(), PROGRAM)
        self.assertEqual(tool._stream_result['done'], len(PROGRAM))
        self.assertEqual(console._acknowledged, len(PROGRAM))

    def test_cancel_releases_the_reserved_operation_without_writing(self):
        tool, fake = self.make_tool(None)
        tool.on_start()
        self.assertEqual(fake.written, [])
        self.assertIsNone(tool._grbl_op)
        tool.app.worker_task.emit.assert_not_called()

    def test_source_edit_while_dialog_is_open_drops_the_request(self):
        tool, fake = self.make_tool()

        def choose(count):
            tool._target().source_file += '\nG0 X99'
            return 10

        tool._choose_start_line.side_effect = choose
        tool.on_start()
        self.assertEqual(fake.written, [])
        self.assertIsNone(tool._grbl_op)

    def test_unknown_position_refuses_restart_without_writing(self):
        tool, fake = self.make_tool(3)
        tool.on_start()
        self.assertEqual(fake.written, [])
        self.assertIsNone(tool._grbl_op)

    def test_cancel_precedes_automatic_probing(self):
        tool, fake = self.make_tool(None)
        tool.ui.autolevel_cb.get_value.return_value = True
        tool.al_heights_valid = False
        tool._queue_probe = MagicMock()
        tool.on_start()
        tool._queue_probe.assert_not_called()
        self.assertEqual(fake.written, [])

    def test_restart_error_highlights_the_selected_console_row(self):
        tool, fake = self.make_tool()
        fake.replies['G2 X'] = ['error:20']
        tool.on_start()
        self.assertEqual(tool._stream_result['error_indices'], [9])
        self.assertEqual(tool._stream_result['line'], 10)

    def test_arc_mode_is_attached_to_the_first_inherited_move_not_sent_alone(self):
        from tests.grbl_stream_helpers import ended_how
        for tail, expected in ((['X1 Y2 I-2 J0'], 'G2 X1 Y2 I-2 J0'),
                               (['F80', 'X1 Y2 I-2 J0'], 'G2 X1 Y2 I-2 J0'),
                               (['F80', 'G1 X8', 'X9'], 'G1 X8')):
            with self.subTest(tail=tail):
                tool, fake = self.make_tool(11)
                tool._target().source_file = '\n'.join(PROGRAM[:10] + tail + ['M2'])
                answer = fake._answer

                def grbl_answer(command, answer=answer):
                    if command in ('G2', 'G3'):
                        fake._send('error:26')
                    else:
                        answer(command)

                fake._answer = grbl_answer
                tool.on_start()
                self.assertEqual(ended_how(tool), 'finished')
                self.assertIn(expected, fake.commands())
                self.assertNotIn('G2', fake.commands())

    def test_check_mode_checks_the_restart_sequence(self):
        from tests.grbl_stream_helpers import ended_how
        tool, fake = self.make_tool(check_mode=True)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'check_passed')
        commands = fake.commands()
        self.assertIn('G0 X1.0000 Y2.0000', commands)
        self.assertLess(commands.index('$C'), commands.index('G0 Z3.0000'))

    def test_levelled_restart_uses_the_preceding_compensated_z(self):
        from tests.grbl_stream_helpers import CheckFake, make_levelled_stream_tool, ended_how
        tool, target = make_levelled_stream_tool(CheckFake())
        target.z_move = 3
        tool._choose_start_line = MagicMock(return_value=10)
        tool.on_start()
        self.assertEqual(ended_how(tool), 'finished')
        expected, _resumed = SenderGen.restart_preamble(tool.job_lines, 10, 3, target.units)
        commands = tool.grbl_ser_port.commands()
        self.assertIn(next(s for s in expected if s.startswith('G1 Z')), commands)
        self.assertNotIn(tool.job_lines[7], commands)


if __name__ == '__main__':
    unittest.main()
