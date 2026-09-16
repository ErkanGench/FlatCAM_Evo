#!/usr/bin/env python
"""
Unit tests for the ToolLevelling methods that apply the probed height map
to a CNCJob's G-code (Task B of the autolevelling feature).

Run: python tests/test_levelling_tool.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6 import QtWidgets

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from shapely import Point

from appPlugins.ToolLevelling import ToolLevelling


def plane(x, y):
    return 0.01 * x - 0.02 * y + 0.1


def make_tool(units='MM', storage=None, heights_valid=True):
    tool = ToolLevelling.__new__(ToolLevelling)
    tool.app = MagicMock()
    tool.app.decimals = 4
    tool.app.inform = MagicMock()
    tool.app.log = MagicMock()
    tool.app.proc_container = MagicMock()
    tool.ui = MagicMock()
    tool.units = units
    tool.al_voronoi_geo_storage = storage if storage is not None else {}
    tool.al_heights_valid = heights_valid
    tool.grbl_probe_result = ''
    tool.grbl_work_offset = (0.0, 0.0, 0.0)
    tool.build_al_table_sig = MagicMock()
    tool.apply_autolevel_sig = MagicMock()
    tool._al_apply_running = False
    tool.app.collection = MagicMock()
    tool.app.app_obj = MagicMock()
    tool.app.worker_task = MagicMock()
    return tool


def make_storage_grid(xs, ys):
    storage = {}
    idx = 0
    for x in xs:
        for y in ys:
            storage[idx] = {
                'point': Point(x, y),
                'geo': None,
                'height': plane(x, y),
            }
            idx += 1
    return storage


GCODE_SAMPLE = (
    "G21\n"
    "G90\n"
    "G0 Z2.0000\n"
    "G0 X0.0000 Y0.0000\n"
    "G1 Z-0.1000 F100\n"
    "G1 X10.0000 Y5.0000\n"
    "G1 X20.0000 Y10.0000\n"
    "G0 Z2.0000\n"
)


class TestAutolevellGcodeBilinear(unittest.TestCase):
    def setUp(self):
        self.storage = make_storage_grid([0, 10, 20], [0, 5, 10])
        self.tool = make_tool(storage=self.storage)
        self.target = SimpleNamespace(
            source_file=GCODE_SAMPLE,
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )

    def test_g1_lines_get_height_compensated(self):
        result = self.tool.autolevell_gcode(self.target, 'b')
        self.assertIsNotNone(result)
        lines = result.splitlines()

        # G0 lines are untouched
        self.assertEqual(lines[2], "G0 Z2.0000")
        self.assertEqual(lines[3], "G0 X0.0000 Y0.0000")

        # first G1: Z-0.1 at (0, 0)
        expected_z0 = -0.1 + plane(0.0, 0.0)
        self.assertEqual(lines[4], "G1 Z{0:.4f} F100".format(expected_z0))

        # second G1: modal Z carried from -0.1, moved to (10, 5)
        expected_z1 = -0.1 + plane(10.0, 5.0)
        self.assertEqual(lines[5], "G1 X10.0000 Y5.0000 Z{0:.4f}".format(expected_z1))

        # third G1: (20, 10)
        expected_z2 = -0.1 + plane(20.0, 10.0)
        self.assertEqual(lines[6], "G1 X20.0000 Y10.0000 Z{0:.4f}".format(expected_z2))

    def test_source_file_not_mutated(self):
        original = self.target.source_file
        self.tool.autolevell_gcode(self.target, 'b')
        self.assertEqual(self.target.source_file, original)

    def test_trailing_newline_preserved(self):
        result = self.tool.autolevell_gcode(self.target, 'b')
        self.assertTrue(self.target.source_file.endswith('\n'))
        self.assertTrue(result.endswith('\n'))

    def test_does_not_read_ui_widgets(self):
        # al_method is now passed in explicitly; autolevell_gcode() and the
        # methods it calls must not read self.ui at all.
        self.tool.ui = None
        result = self.tool.autolevell_gcode(self.target, 'b')
        self.assertIsNotNone(result)


class TestAutolevellGcodeIrregularGrid(unittest.TestCase):
    def test_irregular_grid_falls_back_to_nearest_with_warning(self):
        storage = {
            0: {'point': Point(0, 0), 'geo': None, 'height': 1.0},
            1: {'point': Point(10, 0), 'geo': None, 'height': 2.0},
            2: {'point': Point(5, 10), 'geo': None, 'height': 3.0},
        }
        tool = make_tool(storage=storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z-0.1\n",
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNotNone(result)

        warning_calls = [
            c for c in tool.app.inform.emit.call_args_list
            if '[WARNING_NOTCL]' in c.args[0]
        ]
        self.assertEqual(len(warning_calls), 1)

        expected_z = -0.1 + 1.0  # nearest to (0, 0) is height 1.0
        self.assertEqual(result.strip(), "G1 X0 Y0 Z{0:.4f}".format(expected_z))


class TestAutolevellGcodeVoronoi(unittest.TestCase):
    def test_voronoi_mode_uses_nearest(self):
        storage = {
            0: {'point': Point(0, 0), 'geo': None, 'height': 1.0},
            1: {'point': Point(20, 0), 'geo': None, 'height': 5.0},
        }
        tool = make_tool(storage=storage)
        target = SimpleNamespace(
            source_file="G1 X1 Y0 Z-0.2\n",
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )
        result = tool.autolevell_gcode(target, 'v')
        expected_z = -0.2 + 1.0
        self.assertEqual(result.strip(), "G1 X1 Y0 Z{0:.4f}".format(expected_z))


class TestAutolevellGcodeErrors(unittest.TestCase):
    def setUp(self):
        self.storage = make_storage_grid([0, 10], [0, 10])

    def test_not_segmented_returns_none_and_errors(self):
        tool = make_tool(storage=self.storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=False,
            coords_decimals=4, units='MM',
        )
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNone(result)
        tool.app.inform.emit.assert_called()
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])

    def test_none_target_returns_none(self):
        tool = make_tool(storage=self.storage)
        self.assertIsNone(tool.autolevell_gcode(None, 'b'))

    def test_empty_storage_returns_none(self):
        tool = make_tool(storage={}, heights_valid=False)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='MM',
        )
        self.assertIsNone(tool.autolevell_gcode(target, 'b'))

    def test_heights_not_valid_returns_none(self):
        # storage has entries (with placeholder 'height': 0.0, as created
        # when probe points are added) but they were never actually probed
        tool = make_tool(storage=self.storage, heights_valid=False)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='MM',
        )
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNone(result)
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])

    def test_heights_valid_allows_run(self):
        tool = make_tool(storage=self.storage, heights_valid=True)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='MM',
        )
        self.assertIsNotNone(tool.autolevell_gcode(target, 'b'))

    def test_units_mismatch_returns_none(self):
        tool = make_tool(units='MM', storage=self.storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='IN',
        )
        self.assertIsNone(tool.autolevell_gcode(target, 'b'))


class TestAutolevellGcodeArcWarning(unittest.TestCase):
    def test_arc_move_triggers_warning(self):
        storage = make_storage_grid([0, 10], [0, 10])
        tool = make_tool(storage=storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z-0.1\nG2 X5 Y5 I2.5 J0 Z-0.1\n",
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNotNone(result)
        warning_calls = [
            c for c in tool.app.inform.emit.call_args_list
            if '[WARNING_NOTCL]' in c.args[0]
        ]
        self.assertTrue(any('1' in c.args[0] for c in warning_calls))


class TestParseGrblProbeResult(unittest.TestCase):
    def test_matches_points_and_sets_heights(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
            'b': {'point': Point(10.0, 0.0), 'geo': None, 'height': None},
        }
        tool = make_tool(storage=storage, heights_valid=False)
        tool.grbl_work_offset = (-100.0, -50.0, -20.0)
        # machine coords = work coords + offset
        tool.grbl_probe_result = (
            "[PRB:-100.000,-50.000,-20.500:1]\n"
            "ok\n"
            "[PRB:-90.000,-50.000,-20.700:1]\n"
            "ok\n"
        )
        ok = tool.parse_grbl_probe_result()
        self.assertTrue(ok)
        self.assertAlmostEqual(storage['a']['height'], -0.5)
        self.assertAlmostEqual(storage['b']['height'], -0.7)
        tool.build_al_table_sig.emit.assert_called_once()
        self.assertTrue(tool.al_heights_valid)

    def test_step_quantization_still_matches(self):
        # probe echoes X/Y with a 0.0125mm step-quantization offset from
        # the exact storage coordinate; must still match given the 10mm
        # spacing between the 2 stored points (tolerance = 0.5mm cap).
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
            'b': {'point': Point(10.0, 0.0), 'geo': None, 'height': None},
        }
        tool = make_tool(storage=storage, heights_valid=False)
        tool.grbl_work_offset = (0.0, 0.0, 0.0)
        tool.grbl_probe_result = (
            "[PRB:0.0125,0.0000,-0.500:1]\n"
            "[PRB:9.9875,0.0000,-0.700:1]\n"
        )
        ok = tool.parse_grbl_probe_result()
        self.assertTrue(ok)
        self.assertAlmostEqual(storage['a']['height'], -0.5)
        self.assertAlmostEqual(storage['b']['height'], -0.7)

    def test_failed_probe_returns_false(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
        }
        tool = make_tool(storage=storage, heights_valid=False)
        tool.grbl_probe_result = "[PRB:-100.000,-50.000,-20.500:0]\n"
        self.assertFalse(tool.parse_grbl_probe_result())
        tool.app.inform.emit.assert_called()
        self.assertFalse(tool.al_heights_valid)

    def test_unmatched_point_returns_false(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
        }
        tool = make_tool(storage=storage, heights_valid=False)
        tool.grbl_work_offset = (0.0, 0.0, 0.0)
        # far away from any storage point
        tool.grbl_probe_result = "[PRB:500.000,500.000,-20.500:1]\n"
        self.assertFalse(tool.parse_grbl_probe_result())
        self.assertFalse(tool.al_heights_valid)


class TestSendGrblCommand(unittest.TestCase):
    def test_decodes_bytes_and_joins_lines(self):
        tool = make_tool()
        tool.app.inform_shell = MagicMock()
        tool.grbl_ser_port = MagicMock()
        tool.grbl_ser_port.readlines.return_value = [
            b'[PRB:1.000,2.000,-0.500:1]\r\n',
            b'ok\r\n',
        ]
        result = tool.send_grbl_command(command='G38.2 Z-1 F50')
        self.assertIsInstance(result, str)
        self.assertIn('PRB:1.000,2.000,-0.500:1', result)
        self.assertIn('ok', result.lower())


class TestImportHeightMap(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_mach3_comma_format_empty_storage_creates_points(self):
        path = self._write('mach3.txt', "0.0,0.0,-0.010\n10.0,0.0,-0.020\n")
        tool = make_tool(storage={}, heights_valid=False)
        tool.import_height_map(path)

        self.assertTrue(tool.al_heights_valid)
        self.assertEqual(len(tool.al_voronoi_geo_storage), 2)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['point'].x, 0.0)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['height'], -0.010)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[2]['point'].x, 10.0)
        tool.build_al_table_sig.emit.assert_called_once()
        tool.apply_autolevel_sig.emit.assert_called_once()

    def test_mach4_same_comma_format(self):
        path = self._write('mach4.txt', "1.0, 2.0, -0.05\n2.0, 2.0, -0.03\n")
        tool = make_tool(storage={}, heights_valid=False)
        tool.import_height_map(path)

        self.assertTrue(tool.al_heights_valid)
        self.assertEqual(len(tool.al_voronoi_geo_storage), 2)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['height'], -0.05)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[2]['height'], -0.03)

    def test_linuxcnc_space_9_columns(self):
        path = self._write(
            'linuxcnc.txt',
            "0.0 0.0 -0.010 0 0 0 0 0 0\n10.0 0.0 -0.020 0 0 0 0 0 0\n"
        )
        tool = make_tool(storage={}, heights_valid=False)
        tool.import_height_map(path)

        self.assertTrue(tool.al_heights_valid)
        self.assertEqual(len(tool.al_voronoi_geo_storage), 2)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['point'].y, 0.0)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[2]['point'].x, 10.0)

    def test_blank_lines_and_bare_newline_are_skipped(self):
        path = self._write('blank.txt', "0.0,0.0,-0.01\n\n\n10.0,0.0,-0.02\n")
        tool = make_tool(storage={}, heights_valid=False)
        tool.import_height_map(path)

        self.assertTrue(tool.al_heights_valid)
        self.assertEqual(len(tool.al_voronoi_geo_storage), 2)

    def test_one_invalid_row_is_skipped_and_logged(self):
        path = self._write('invalid.txt', "0.0,0.0,-0.01\nnot,a,row\n10.0,0.0,-0.02\n")
        tool = make_tool(storage={}, heights_valid=False)
        tool.import_height_map(path)

        self.assertTrue(tool.al_heights_valid)
        self.assertEqual(len(tool.al_voronoi_geo_storage), 2)
        tool.app.log.debug.assert_called()

    def test_rows_out_of_order_match_correct_storage_points(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
            'b': {'point': Point(10.0, 0.0), 'geo': None, 'height': None},
        }
        # rows given in reverse order relative to storage keys
        path = self._write('reorder.txt', "10.0,0.0,-0.02\n0.0,0.0,-0.01\n")
        tool = make_tool(storage=storage, heights_valid=False)
        tool.import_height_map(path)

        self.assertTrue(tool.al_heights_valid)
        self.assertAlmostEqual(storage['a']['height'], -0.01)
        self.assertAlmostEqual(storage['b']['height'], -0.02)

    def test_zero_valid_rows_errors_and_does_not_apply(self):
        path = self._write('empty.txt', "\n\n   \n")
        tool = make_tool(storage={}, heights_valid=False)
        tool.import_height_map(path)

        self.assertFalse(tool.al_heights_valid)
        tool.apply_autolevel_sig.emit.assert_not_called()
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])

    def test_storage_point_without_matching_row_errors_and_does_not_apply(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
            'b': {'point': Point(10.0, 0.0), 'geo': None, 'height': None},
        }
        # only 1 row: point 'b' has no match
        path = self._write('missing.txt', "0.0,0.0,-0.01\n")
        tool = make_tool(storage=storage, heights_valid=False)
        tool.import_height_map(path)

        self.assertFalse(tool.al_heights_valid)
        tool.apply_autolevel_sig.emit.assert_not_called()
        error_calls = [
            c for c in tool.app.inform.emit.call_args_list
            if '[ERROR_NOTCL]' in c.args[0]
        ]
        self.assertTrue(error_calls)


class FakeNewCNCJob:
    """Minimal stand-in for a newly created CNCJobObject, enough for
    apply_autolevel()'s obj_init callback to run against."""

    def __init__(self):
        self.obj_options = {}
        self.tools = {}
        self.units = None
        self.multitool = None
        self.used_tools = None
        self.gc_start = None
        self.prepend_snippet = None
        self.append_snippet = None
        self.is_segmented_gcode = None
        self.gcode = ''
        self.gcode_parsed = None
        self.geometry_created = False

    def gcode_parse(self, tool_data=None):
        self.gcode_parsed = list(self.gcode.splitlines())
        return self.gcode_parsed

    def create_geometry(self):
        self.geometry_created = True


def make_apply_target(tools_gcode_by_key):
    return SimpleNamespace(
        kind='cncjob',
        obj_options={'name': 'job1', 'type': 'Geometry'},
        units='MM',
        multitool=True,
        used_tools=list(tools_gcode_by_key.keys()),
        gc_start='G21\nG90\n',
        prepend_snippet='',
        append_snippet='',
        is_segmented_gcode=True,
        coords_decimals=4,
        tools={
            key: {'gcode': text, 'gcode_parsed': [], 'data': {}, 'tooldia': 1.0}
            for key, text in tools_gcode_by_key.items()
        },
    )


class TestApplyAutolevel(unittest.TestCase):
    def setUp(self):
        self.storage = make_storage_grid([0, 10, 20], [0, 5, 10])

    def test_busy_guard(self):
        tool = make_tool(storage=self.storage)
        tool._al_apply_running = True
        tool.apply_autolevel()

        tool.app.inform.emit.assert_called()
        self.assertIn('[WARNING_NOTCL]', tool.app.inform.emit.call_args.args[0])
        tool.app.worker_task.emit.assert_not_called()

    def test_non_cncjob_target_errors(self):
        tool = make_tool(storage=self.storage)
        tool.app.collection.get_by_name.return_value = SimpleNamespace(kind='geometry')
        tool.ui.al_method_radio.get_value.return_value = 'b'

        tool.apply_autolevel()

        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])
        tool.app.worker_task.emit.assert_not_called()

    def test_none_target_errors(self):
        tool = make_tool(storage=self.storage)
        tool.app.collection.get_by_name.return_value = None
        tool.ui.al_method_radio.get_value.return_value = 'b'

        tool.apply_autolevel()

        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])
        tool.app.worker_task.emit.assert_not_called()

    def _run_worker(self, tool, target, new_obj_factory=FakeNewCNCJob):
        """Trigger apply_autolevel(), capture the emitted worker_task, run
        it synchronously against a fake new object, and return that
        object (or None if new_object was never called)."""
        tool.app.collection.get_by_name.return_value = target
        tool.ui.al_method_radio.get_value.return_value = 'b'

        captured = {}

        def fake_new_object(kind, name, obj_init, *args, **kwargs):
            captured['kind'] = kind
            captured['name'] = name
            new_obj = new_obj_factory()
            obj_init(new_obj, tool.app)
            captured['new_obj'] = new_obj
            return 'success'

        tool.app.app_obj.new_object.side_effect = fake_new_object

        tool.apply_autolevel()
        self.assertTrue(tool._al_apply_running)

        worker_dict = tool.app.worker_task.emit.call_args.args[0]
        worker_dict['fcn']()

        return captured

    def test_new_object_called_with_levelled_name_and_levels_gcode(self):
        original_gcode = "G0 Z2.0000\nG0 X0.0000 Y0.0000\nG1 Z-0.1000 F100\n"
        target = make_apply_target({1: original_gcode})
        tool = make_tool(storage=self.storage)

        captured = self._run_worker(tool, target)

        self.assertEqual(captured['kind'], 'cncjob')
        self.assertEqual(captured['name'], 'job1_levelled')

        new_obj = captured['new_obj']
        levelled_lines = new_obj.tools[1]['gcode'].splitlines()
        # G0 lines are untouched
        self.assertEqual(levelled_lines[0], "G0 Z2.0000")
        self.assertEqual(levelled_lines[1], "G0 X0.0000 Y0.0000")
        # G1 line got height-compensated (no longer the flat -0.1000)
        self.assertNotEqual(levelled_lines[2], "G1 Z-0.1000 F100")
        self.assertTrue(new_obj.geometry_created)

        self.assertFalse(tool._al_apply_running)
        self.assertIn('[success]', tool.app.inform.emit.call_args.args[0])

    def test_source_object_gcode_unchanged(self):
        original_gcode = "G0 Z2.0000\nG1 X0 Y0 Z-0.1\n"
        target = make_apply_target({1: original_gcode})
        tool = make_tool(storage=self.storage)

        self._run_worker(tool, target)

        self.assertEqual(target.tools[1]['gcode'], original_gcode)

    def test_success_message_only_after_object_created(self):
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        tool = make_tool(storage=self.storage)

        self._run_worker(tool, target)

        success_calls = [
            c for c in tool.app.inform.emit.call_args_list if '[success]' in c.args[0]
        ]
        self.assertEqual(len(success_calls), 1)

    def test_new_object_fail_emits_error_not_success(self):
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        tool = make_tool(storage=self.storage)
        tool.app.collection.get_by_name.return_value = target
        tool.ui.al_method_radio.get_value.return_value = 'b'
        tool.app.app_obj.new_object.return_value = 'fail'

        tool.apply_autolevel()
        worker_dict = tool.app.worker_task.emit.call_args.args[0]
        worker_dict['fcn']()

        self.assertFalse(any('[success]' in c.args[0] for c in tool.app.inform.emit.call_args_list))
        self.assertTrue(any('[ERROR_NOTCL]' in c.args[0] for c in tool.app.inform.emit.call_args_list))
        self.assertFalse(tool._al_apply_running)

    def test_busy_flag_cleared_after_exception_in_worker(self):
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        tool = make_tool(storage=self.storage)
        tool.app.collection.get_by_name.return_value = target
        tool.ui.al_method_radio.get_value.return_value = 'b'
        tool.autolevell_gcode_tools = MagicMock(side_effect=RuntimeError('boom'))

        tool.apply_autolevel()
        worker_dict = tool.app.worker_task.emit.call_args.args[0]

        with self.assertRaises(RuntimeError):
            worker_dict['fcn']()

        self.assertFalse(tool._al_apply_running)


if __name__ == '__main__':
    unittest.main()
