#!/usr/bin/env python
"""
Tests of the frame bound height map and of the levelled job of the GRBL Sender (T16a):
the frame in the probe result, the hook that binds it, the home WCS and the strict mode of
the levelling, the tool length offset check and the levelled job.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from shapely import Point

from test_levelling_audit import make_audit_tool
from test_levelling_tool import make_tool
from appPlugins.ToolGrblSender.Sender import ToolGrblSender
from appPlugins.ToolGrblSender import SenderGen

FRAME = ('G54', (0.0, 0.0, 0.0), False)

# a segmented job with comments, a header and cutting moves inside the map (0..10)
JOB = (
    "(FlatCAM Gcode Generator)\nG21\nG90\nG94\nF300.0000\nM03 S10000\n"
    "G00 Z2.0000 (start)\nG00 X1.0000 Y1.0000\nG01 Z-0.1000 F300.0000\n"
    "G01 X3.0000 Y1.0000\nG01 X5.0000 Y2.0000\nG01 X7.0000 Y4.0000\nG01 X9.0000 Y6.0000\n"
    "G00 Z2.0000\nG00 X0.0000 Y0.0000\nM05\nM2\n"
)


def make_storage():
    """3 x 3 grid over 0..10 with a plane and a bump in the middle."""
    storage = {}
    idx = 0
    for x in (0.0, 5.0, 10.0):
        for y in (0.0, 5.0, 10.0):
            height = 0.01 * x + 0.02 * y + (0.05 if (x, y) == (5.0, 5.0) else 0.0)
            storage[idx] = {'point': Point(x, y), 'geo': None, 'height': height}
            idx += 1
    return storage


def make_job_target(text, segmented=True):
    return SimpleNamespace(
        kind='cncjob', source_file=text, units='MM', coords_decimals=4, obj_options={'name': 'job'},
        tools={1: {'gcode': text, 'data': {}}}, is_segmented_gcode=segmented,
        pp_geometry_name='default', pp_excellon_name='default', pp_solderpaste_name=None,
        seg_x=0, seg_y=0)


def make_sender(text, frame=FRAME, method='b', segmented=True):
    target = make_job_target(text, segmented)
    tool = make_audit_tool(units='MM', storage=make_storage(), heights_valid=True, cls=ToolGrblSender)
    tool._al_map_frame = frame
    tool._al_map_imported = frame is None
    tool.ui.autolevel_cb.get_value.return_value = True
    tool.ui.al_method_radio.get_value.return_value = method
    tool.ui.object_combo.get_value.return_value = 'job'
    tool.app.collection.get_by_name.return_value = target
    tool.app.options = {}
    return tool, target


def messages(tool, tag):
    return [call.args[0] for call in tool.app.inform.emit.call_args_list if tag in call.args[0]]


class TestBoundFrameHook(unittest.TestCase):
    def test_probe_result_binds_the_frame(self):
        tool, target = make_sender(JOB, frame=None)
        frame = ('G55', (1.0, 2.0, 3.0), True)
        tool._al_on_height_map_ready(target, {'kind': 'probe', 'frame': frame})
        self.assertEqual(tool._al_map_frame, frame)
        self.assertFalse(tool._al_map_imported)

    def test_import_clears_the_frame(self):
        for kind in ('import', 'import_points'):
            tool, target = make_sender(JOB)
            tool._al_on_height_map_ready(target, {'kind': kind})
            self.assertIsNone(tool._al_map_frame)
            self.assertTrue(tool._al_map_imported)

    def test_clear_probe_data(self):
        tool, _target = make_sender(JOB)
        tool._al_map_imported = True
        tool._clear_probe_data()
        self.assertIsNone(tool._al_map_frame)
        self.assertFalse(tool._al_map_imported)

    def test_on_al_result_ready_passes_the_result(self):
        # the whole path: the result of the probe reaches the hook with its frame
        tool, _target = make_sender(JOB, frame=None)
        ctx = tool._al_capture_context()
        heights = {key: 0.1 for key in tool.al_voronoi_geo_storage}
        frame = ('G56', (0.5, 0.5, 0.5), False)
        tool._on_al_result_ready({'kind': 'probe', 'context': ctx, 'heights': heights, 'frame': frame})
        self.assertEqual(tool._al_map_frame, frame)
        self.assertFalse(tool._al_map_imported)

    def test_tool_levelling_hook_ignores_the_result(self):
        tool = make_tool(units='MM', storage=make_storage())
        tool.apply_autolevel = MagicMock()
        target = object()
        tool._al_on_height_map_ready(target, {'kind': 'probe', 'frame': FRAME})
        tool.apply_autolevel.assert_called_once_with(target_obj=target)


class TestBuildLevelledJobFrame(unittest.TestCase):
    def test_same_frame_builds(self):
        tool, _target = make_sender("G90 G21 G54\nG0 X0 Y0 Z5\nG1 Z0 F100\nG1 X10 Y0\n")
        self.assertTrue(tool.build_levelled_job())
        self.assertEqual(messages(tool, '[ERROR_NOTCL]'), [])
        self.assertEqual(tool.job_map_generation, tool._al_generation)

    def test_g54_map_with_g55_header_refused(self):
        tool, _target = make_sender("G90 G21 G55\nG0 X0 Y0 Z5\nG1 Z0 F100\nG1 X10 Y0\n")
        self.assertFalse(tool.build_levelled_job())
        self.assertEqual(len(messages(tool, '[ERROR_NOTCL]')), 1)

    def test_g92_in_the_middle_refused(self):
        tool, _target = make_sender(
            "G90 G21 G54\nG0 X0 Y0 Z5\nG1 Z0 F100\nG1 X5 Y0\nG92 X0 Y0\nG1 X10 Y0\nG1 X10 Y5\n")
        self.assertFalse(tool.build_levelled_job())
        self.assertEqual(len(messages(tool, '[ERROR_NOTCL]')), 1)

    def test_unbound_map_does_not_guess_the_wcs(self):
        # an imported map that is not bound yet: the first WCS word of the program declares it
        tool, _target = make_sender("G90 G21 G55\nG0 X0 Y0 Z5\nG1 Z0 F100\nG1 X10 Y0\n", frame=None)
        self.assertTrue(tool.build_levelled_job())
        self.assertEqual(messages(tool, '[ERROR_NOTCL]'), [])


class TestStrictMode(unittest.TestCase):
    def test_unsplit_arc_refused(self):
        tool, _target = make_sender("G90 G21 G54\nG18\nG0 X0 Y0 Z0\nG2 X10 Z0 I5 K0\n")
        self.assertFalse(tool.build_levelled_job())
        self.assertEqual(len(messages(tool, '[ERROR_NOTCL]')), 1)

    def test_relative_move_refused(self):
        tool, _target = make_sender("G90 G21 G54\nG91\nG1 X5 Y0 Z-1 F100\n")
        self.assertFalse(tool.build_levelled_job())
        self.assertEqual(len(messages(tool, '[ERROR_NOTCL]')), 1)

    def test_tool_levelling_stays_lenient(self):
        # without the strict keyword, the same program only warns (a relative move at an unknown position)
        tool = make_tool(units='MM', storage=make_storage())
        target = make_job_target("G90 G21\nG91\nG1 X5 Y0 Z-1 F100\n")
        self.assertIsNotNone(tool.autolevell_gcode(target, 'b'))
        self.assertEqual(messages(tool, '[ERROR_NOTCL]'), [])
        self.assertEqual(len(messages(tool, '[WARNING_NOTCL]')), 1)


class TestTloChangeRefused(unittest.TestCase):
    def check(self, tlo_line):
        # a map probed with a TLO of 1.5; the program changes the tool length offset
        frame = ('G54', (0.0, 0.0, -1.5), False)
        text = "G90 G21 G54\nG0 X0 Y0 Z5\n%s\nG0 X0 Y0 Z5\nG1 X10 Y0 Z0\n" % tlo_line
        tool, _target = make_sender(text, frame=frame)
        self.assertFalse(tool.build_levelled_job())
        errors = messages(tool, '[ERROR_NOTCL]')
        self.assertEqual(len(errors), 1)
        self.assertIn('tool length offset', errors[0])
        self.assertIn('line 3', errors[0])

    def test_tlo_change_refused(self):
        self.check('G49')
        self.check('G43.1 Z2')

    def test_g43_refused(self):
        self.check('G43 H1')


class TestNoNewKeywords(unittest.TestCase):
    # computed once with the code at commit 7be1b53c (before the new keywords)
    EXPECTED = (
        "(FlatCAM Gcode Generator)\n"
        "G21\n"
        "G90\n"
        "G94\n"
        "F300.0000\n"
        "M03 S10000\n"
        "G00 Z2.0000 (start)\n"
        "G00 X1.0000 Y1.0000\n"
        "G01 Z-0.0680 F300.0000\n"
        "G01 X3.0000 Y1.0000 Z-0.0440\n"
        "G01 X5.0000 Y2.0000 Z0.0100\n"
        "G01 X7.0000 Y4.0000 Z0.0740\n"
        "G01 X9.0000 Y6.0000 Z0.1180\n"
        "G00 Z2.0000\n"
        "G00 X0.0000 Y0.0000\n"
        "M05\n"
        "M2\n"
    )

    def test_autolevell_gcode_without_keywords_unchanged(self):
        tool = make_tool(units='MM', storage=make_storage())
        result = tool.autolevell_gcode(make_job_target(JOB), 'b')
        self.assertEqual(result[1], self.EXPECTED)


class TestSenderMatchesLevellingTool(unittest.TestCase):
    def check(self, method):
        # The sender cleans the comments and the empty lines; ToolLevelling keeps them. After the
        # same cleaning every line (motion and modal) is the same.
        tool_lvl = make_tool(units='MM', storage=make_storage())
        expected_text = tool_lvl.autolevell_gcode(make_job_target(JOB), method)[1]
        expected = SenderGen.clean_lines(expected_text)

        sender, _target = make_sender(JOB, method=method)
        self.assertTrue(sender.build_levelled_job())
        self.assertEqual(sender.job_lines, expected)
        # the levelling really changed the cutting moves
        self.assertNotEqual(sender.job_lines, SenderGen.clean_lines(JOB))
        cutting = [line for line in sender.job_lines if line.startswith('G01 X')]
        self.assertEqual(len(cutting), 4)
        self.assertTrue(all('Z' in line for line in cutting))

    def test_sender_levelled_job_matches_levelling_tool(self):
        self.check('b')
        self.check('v')


class TestStreamJobArcs(unittest.TestCase):
    @staticmethod
    def make(text):
        tool, _target = make_sender(text)
        tool.ui.autolevel_cb.get_value.return_value = False
        return tool

    def test_arc_split_keeps_the_line_numbers(self):
        tool = self.make("(c)\nG21 G90\nG0 X0 Y0 Z0\nG2 X10 Y0 I5 J0 F100\nG0 Z5\n")
        self.assertTrue(tool.build_stream_job())
        self.assertGreater(len(tool.job_lines), 5)
        self.assertEqual(len(tool.job_line_numbers), len(tool.job_lines))
        self.assertEqual(tool.job_line_numbers[0], 2)
        self.assertEqual(tool.job_line_numbers[-1], 5)
        self.assertEqual(tool.job_lines[-1], 'G0 Z5')

    def test_unsplit_arc_refused(self):
        tool = self.make("(c)\nG18\nG0 X0 Y0 Z0\nG2 X10 Z0 I5 K0\n")
        self.assertFalse(tool.build_stream_job())
        errors = messages(tool, '[ERROR_NOTCL]')
        self.assertEqual(len(errors), 1)
        self.assertIn('Line 4', errors[0])


class TestStartRefusesLevelled(unittest.TestCase):
    def test_levelled_start_not_available_yet(self):
        # T16b replaces this refusal with the 2 phases of a levelled Start
        tool, _target = make_sender(JOB)
        tool._grbl_reserve = MagicMock()
        tool.build_stream_job = MagicMock()
        tool.on_start()
        tool._grbl_reserve.assert_not_called()
        tool.build_stream_job.assert_not_called()
        self.assertEqual(len(messages(tool, '[WARNING_NOTCL]')), 1)


if __name__ == '__main__':
    unittest.main()
