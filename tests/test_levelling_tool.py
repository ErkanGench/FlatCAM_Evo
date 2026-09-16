#!/usr/bin/env python
"""
Unit tests for the ToolLevelling methods that apply the probed height map
to a CNCJob's G-code (Task B of the autolevelling feature).

Run: python tests/test_levelling_tool.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6 import QtWidgets

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from shapely import Point

from appPlugins.ToolLevelling import ToolLevelling


def plane(x, y):
    return 0.01 * x - 0.02 * y + 0.1


def make_tool(method='b', units='MM', storage=None):
    tool = ToolLevelling.__new__(ToolLevelling)
    tool.app = MagicMock()
    tool.app.decimals = 4
    tool.app.inform = MagicMock()
    tool.app.log = MagicMock()
    tool.app.proc_container = MagicMock()
    tool.ui = MagicMock()
    tool.ui.al_method_radio.get_value.return_value = method
    tool.units = units
    tool.al_voronoi_geo_storage = storage if storage is not None else {}
    tool.grbl_probe_result = ''
    tool.grbl_work_offset = (0.0, 0.0, 0.0)
    tool.build_al_table_sig = MagicMock()
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
        self.tool = make_tool(method='b', storage=self.storage)
        self.target = SimpleNamespace(
            source_file=GCODE_SAMPLE,
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )

    def test_g1_lines_get_height_compensated(self):
        result = self.tool.autolevell_gcode(self.target)
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
        self.tool.autolevell_gcode(self.target)
        self.assertEqual(self.target.source_file, original)

    def test_trailing_newline_preserved(self):
        result = self.tool.autolevell_gcode(self.target)
        self.assertTrue(self.target.source_file.endswith('\n'))
        self.assertTrue(result.endswith('\n'))


class TestAutolevellGcodeIrregularGrid(unittest.TestCase):
    def test_irregular_grid_falls_back_to_nearest_with_warning(self):
        storage = {
            0: {'point': Point(0, 0), 'geo': None, 'height': 1.0},
            1: {'point': Point(10, 0), 'geo': None, 'height': 2.0},
            2: {'point': Point(5, 10), 'geo': None, 'height': 3.0},
        }
        tool = make_tool(method='b', storage=storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z-0.1\n",
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )
        result = tool.autolevell_gcode(target)
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
        tool = make_tool(method='v', storage=storage)
        target = SimpleNamespace(
            source_file="G1 X1 Y0 Z-0.2\n",
            is_segmented_gcode=True,
            coords_decimals=4,
            units='MM',
        )
        result = tool.autolevell_gcode(target)
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
        result = tool.autolevell_gcode(target)
        self.assertIsNone(result)
        tool.app.inform.emit.assert_called()
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])

    def test_none_target_returns_none(self):
        tool = make_tool(storage=self.storage)
        self.assertIsNone(tool.autolevell_gcode(None))

    def test_empty_storage_returns_none(self):
        tool = make_tool(storage={})
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='MM',
        )
        self.assertIsNone(tool.autolevell_gcode(target))

    def test_missing_height_returns_none(self):
        storage = {0: {'point': Point(0, 0), 'geo': None}}
        tool = make_tool(storage=storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='MM',
        )
        self.assertIsNone(tool.autolevell_gcode(target))

    def test_units_mismatch_returns_none(self):
        tool = make_tool(units='MM', storage=self.storage)
        target = SimpleNamespace(
            source_file="G1 X0 Y0 Z0\n", is_segmented_gcode=True,
            coords_decimals=4, units='IN',
        )
        self.assertIsNone(tool.autolevell_gcode(target))


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
        result = tool.autolevell_gcode(target)
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
        tool = make_tool(storage=storage)
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

    def test_failed_probe_returns_false(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
        }
        tool = make_tool(storage=storage)
        tool.grbl_probe_result = "[PRB:-100.000,-50.000,-20.500:0]\n"
        self.assertFalse(tool.parse_grbl_probe_result())
        tool.app.inform.emit.assert_called()

    def test_unmatched_point_returns_false(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'geo': None, 'height': None},
        }
        tool = make_tool(storage=storage)
        tool.grbl_work_offset = (0.0, 0.0, 0.0)
        # far away from any storage point
        tool.grbl_probe_result = "[PRB:500.000,500.000,-20.500:1]\n"
        self.assertFalse(tool.parse_grbl_probe_result())


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


if __name__ == '__main__':
    unittest.main()
