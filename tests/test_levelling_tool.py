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
import threading
import re
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, mock_open, patch

from PyQt6 import QtWidgets

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from shapely import Point, box
from shapely.ops import unary_union

from appPlugins.ToolLevelling import ToolLevelling
from appPlugins.ToolGrblSender.Sender import ToolGrblSender
from appPlugins.Common.grbl.grbl_protocol import parse_grbl_probe_output
from appPlugins.Common.levelling_interp import parse_height_map_line


def plane(x, y):
    return 0.01 * x - 0.02 * y + 0.1


def make_tool(units='MM', storage=None, heights_valid=True, cls=None):
    tool = (cls or ToolLevelling).__new__(cls or ToolLevelling)
    tool.app = MagicMock()
    tool.app.decimals = 4
    tool.app.inform = MagicMock()
    tool.app.log = MagicMock()
    tool.app.proc_container = MagicMock()
    tool.app.app_units = units
    tool.ui = MagicMock()
    tool.ui.plot_probing_pts_cb.get_value.return_value = False
    tool.units = units
    tool.al_voronoi_geo_storage = storage if storage is not None else {}
    tool._al_data_units = units if tool.al_voronoi_geo_storage else None
    tool.al_heights_valid = heights_valid
    tool.grbl_probe_result = ''
    tool.grbl_work_offset = (0.0, 0.0, 0.0)
    tool.build_al_table_sig = MagicMock()
    tool.apply_autolevel_sig = MagicMock()
    tool.show_probing_geo_sig = MagicMock()
    tool._al_apply_running = False
    tool.mouse_events_connected = False
    tool.app.collection = MagicMock()
    tool.app.app_obj = MagicMock()
    tool.app.worker_task = MagicMock()
    tool._al_generation = 0
    tool._grbl_op_lock = threading.Lock()
    tool._al_target_name = None
    tool._al_target_obj = None
    # publish results at once (the worker runs inline in these tests)
    tool.al_result_ready_sig = MagicMock()
    tool.al_result_ready_sig.emit.side_effect = lambda result: tool._on_al_result_ready(result)
    tool.console_line_sig = MagicMock()
    tool.job_map_generation = None
    tool.view3d = None
    tool._grbl_stream_dirty = False
    tool.stream_progress_sig = MagicMock()
    tool.status_report_sig = MagicMock()
    tool.spindle_state_sig = MagicMock()
    tool.stream_ended_sig = MagicMock()
    return tool


def make_tool_target(tools_gcode_by_key, **overrides):
    """A minimal SimpleNamespace target for autolevell_gcode() (the
    per-tool API): tools_gcode_by_key maps tooluid -> raw gcode text."""
    kwargs = dict(
        is_segmented_gcode=True,
        coords_decimals=4,
        units='MM',
        tools={
            key: {'gcode': text, 'data': {}}
            for key, text in tools_gcode_by_key.items()
        },
    )
    kwargs.update(overrides)
    return SimpleNamespace(**kwargs)


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


class TestHeightMapCoverage(unittest.TestCase):
    @staticmethod
    def warnings(tool):
        return [call.args[0] for call in tool.app.inform.emit.call_args_list
                if 'outside the measured height map' in call.args[0]]

    def test_bilinear_warns_once_across_tools_without_changing_clamped_values(self):
        tool = make_tool(storage=make_storage_grid([0, 10], [0, 10]))
        target = make_tool_target({1: 'G21 G90\nG1 X20 Y0 Z-1\n',
                                   2: 'G1 X30 Y0\nG1 X40 Y0\n'})
        result = tool.autolevell_gcode(target, 'b')
        self.assertIn('Z-0.8000', result[1])
        self.assertEqual(result[2], 'G1 X30 Y0 Z-0.8000\nG1 X40 Y0 Z-0.8000\n')
        warnings = self.warnings(tool)
        self.assertEqual(len(warnings), 1)
        self.assertIn(': 3.', warnings[0])
        self.assertIn('reprobe', warnings[0])

    def test_in_map_boundaries_and_rounding_tolerance_do_not_warn(self):
        for method in ('b', 'v'):
            with self.subTest(method=method):
                tool = make_tool(storage=make_storage_grid([0, 10], [0, 10]))
                target = make_tool_target({1: 'G21 G90\nG1 X0 Y0 Z-1\nG1 X10 Y10\n'
                                             'G1 X10.0005 Y5\n'})
                self.assertIsNotNone(tool.autolevell_gcode(target, method))
                self.assertEqual(self.warnings(tool), [])

    def test_scattered_footprint_is_hull_not_bounding_rectangle(self):
        for method in ('v', 'b'):
            with self.subTest(method=method):
                storage = make_storage_grid([0, 10], [0, 10])
                storage.pop(3)
                tool = make_tool(storage=storage)
                result = tool.autolevell_gcode(make_tool_target({
                    1: 'G21 G90\nG1 X2 Y2 Z-1\nG1 X5 Y5\n'
                       'G1 X5.0002 Y5.0002\nG1 X8 Y9\n'}), method)
                self.assertIn('G1 X8 Y9 Z-1.1000', result[1])
                self.assertEqual(len(self.warnings(tool)), 1)
                self.assertIn(': 1.', self.warnings(tool)[0])

    def test_single_and_collinear_samples_have_only_point_or_line_coverage(self):
        for xs, inside, outside in (([0], 'X0 Y0', 'X0.01 Y0'),
                                    ([0, 10], 'X5 Y0.0005', 'X5 Y0.01')):
            with self.subTest(xs=xs):
                tool = make_tool(storage=make_storage_grid(xs, [0]))
                tool.autolevell_gcode(make_tool_target({
                    1: 'G21 G90\nG1 %s Z-1\nG1 %s\n' % (inside, outside)}), 'v')
                self.assertEqual(len(self.warnings(tool)), 1)
                self.assertIn(': 1.', self.warnings(tool)[0])

    def test_rapids_comments_unknown_positions_and_frame_skips_do_not_warn(self):
        for text in ('G21 G90\nG0 X20 Y20 Z5\n(comment G1 X30 Y30)\nG0 Z10\n',
                     'G21 G90\nG1 X20 Z-1\n',
                     'G21 G90 G54\nG0 X0 Y0 Z5\nG55\nG1 X20 Y20 Z-1\n',
                     'G21 G90 G54\nG0 X0 Y0 Z5\nG20\nG1 X20 Y20 Z-1\n'):
            with self.subTest(text=text):
                tool = make_tool(storage=make_storage_grid([0, 10], [0, 10]))
                self.assertEqual(tool.autolevell_gcode(make_tool_target({1: text}), 'b')[1], text)
                self.assertEqual(self.warnings(tool), [])

    def test_arc_interior_samples_outside_map_warn_even_with_in_map_endpoints(self):
        tool = make_tool(storage=make_storage_grid([0, 10], [0, 10]))
        result = tool.autolevell_gcode(make_tool_target({
            1: 'G21 G90 G17\nG0 X0 Y0 Z5\nG1 Z-1\nG3 X10 Y0 I5 J0\n'}), 'b')
        self.assertGreater(result[1].count('G1 X'), 2)
        self.assertEqual(len(self.warnings(tool)), 1)
        outside_samples = len(re.findall(r'G1 X[\d.-]+ Y-\d', result[1]))
        self.assertIn(': %d.' % outside_samples, self.warnings(tool)[0])

    def test_relative_compensation_counts_and_no_evidence_leaks_to_next_call(self):
        tool = make_tool(storage=make_storage_grid([0, 10], [0, 10]))
        tool.autolevell_gcode(make_tool_target({
            1: 'G21 G90\nG0 X0 Y0 Z5\nG1 Z-1\nG91\nG1 X20\n'}), 'b')
        self.assertEqual(len(self.warnings(tool)), 1)
        self.assertIn(': 1.', self.warnings(tool)[0])
        tool.app.inform.emit.reset_mock()
        tool.autolevell_bilinear(100, 100)
        tool.autolevell_gcode(make_tool_target({1: 'G21 G90\nG1 X5 Y5 Z-1\n'}), 'b')
        self.assertEqual(self.warnings(tool), [])


class RecordingShapeCollection:
    def __init__(self):
        self.shapes = []
        self.redraw_count = 0
        self.clear_count = 0

    def add(self, **kwargs):
        self.shapes.append(kwargs)
        return len(self.shapes)

    def redraw(self):
        self.redraw_count += 1

    def clear(self, update=False):
        self.clear_count += 1
        self.shapes.clear()


def make_overlay_tool(heights_valid=True):
    storage = {
        0: {'point': Point(0.0, 0.0), 'geo': None, 'height': 0.0},
        1: {'point': Point(10.0, 0.0), 'geo': None, 'height': 1.0},
        2: {'point': Point(0.0, 10.0), 'geo': None, 'height': 2.0},
        3: {'point': Point(10.0, 10.0), 'geo': None, 'height': 3.0},
    }
    tool = make_tool(storage=storage, heights_valid=heights_valid)
    tool.al_bilinear_geo_storage = [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (0.0, 10.0, 0.0),
        (10.0, 10.0, 0.0),
    ]
    tool.ui.al_method_radio.get_value.return_value = 'b'
    tool.ui.plot_probing_pts_cb.get_value.return_value = True
    tool.ui.probe_tip_dia_entry.get_value.return_value = 0.2
    tool.probing_shapes = RecordingShapeCollection()
    tool.drawing_tolerance = 0.01
    return tool


class TestBilinearOverlay(unittest.TestCase):
    def test_generates_bounded_transparent_bands(self):
        tool = make_overlay_tool()

        tool.show_probing_geo(state=True, reset=True)
        bands = [
            (item['shape'], item['color'])
            for item in tool.probing_shapes.shapes
            if item['color'] != '#000000FF'
        ]

        self.assertGreater(len(bands), 1)
        self.assertLessEqual(len(bands), 8)
        bounds = box(0.0, 0.0, 10.0, 10.0)
        union = unary_union([geometry for geometry, _color in bands])
        for geometry, color in bands:
            self.assertFalse(geometry.is_empty)
            self.assertTrue(bounds.buffer(1e-9).covers(geometry))
            self.assertRegex(color, r'^#[0-9A-Fa-f]{8}$')
            self.assertNotIn(color[-2:].upper(), ('00', 'FF'))
        self.assertTrue(union.buffer(1e-9).covers(bounds))

    def test_flat_heights_use_one_bounded_transparent_band(self):
        tool = make_overlay_tool()
        for value in tool.al_voronoi_geo_storage.values():
            value['height'] = 0.25

        tool.show_probing_geo(state=True, reset=True)
        bands = [
            (item['shape'], item['color'])
            for item in tool.probing_shapes.shapes
            if item['color'] != '#000000FF'
        ]

        self.assertEqual(len(bands), 1)
        geometry, color = bands[0]
        self.assertFalse(geometry.is_empty)
        self.assertTrue(box(0.0, 0.0, 10.0, 10.0).buffer(1e-9).covers(geometry))
        self.assertRegex(color, r'^#[0-9A-Fa-f]{8}$')
        self.assertNotIn(color[-2:].upper(), ('00', 'FF'))


    def test_invalid_heights_show_only_probe_markers(self):
        tool = make_overlay_tool(heights_valid=False)

        tool.show_probing_geo(state=True, reset=True)

        self.assertTrue(tool.probing_shapes.shapes)
        self.assertTrue(all(item['color'] == '#000000FF' for item in tool.probing_shapes.shapes))

    def test_invalid_heights_draw_cell_areas_when_present(self):
        tool = make_overlay_tool(heights_valid=False)
        cells = {
            0: box(-1.0, -1.0, 5.0, 5.0),
            1: box(5.0, -1.0, 11.0, 5.0),
            2: box(-1.0, 5.0, 5.0, 11.0),
            3: box(5.0, 5.0, 11.0, 11.0),
        }
        for key, cell in cells.items():
            tool.al_voronoi_geo_storage[key]['geo'] = cell

        tool.show_probing_geo(state=True, reset=True)

        cell_items = [
            item for item in tool.probing_shapes.shapes
            if not isinstance(item['face_color'], str)
        ]
        self.assertEqual(len(cell_items), 4)
        for cell in cells.values():
            self.assertTrue(any(
                item['shape'].symmetric_difference(cell).area < 1e-4
                for item in cell_items
            ))
        self.assertTrue(all(item['color'] == '#000000FF' for item in cell_items))
        for item in cell_items:
            color = item['face_color']
            self.assertEqual(color.shape, (4,))
            self.assertTrue(all(0.0 <= channel <= 1.0 for channel in color))
            self.assertEqual(color[3], 0.5)

    def test_valid_heights_draw_cell_outlines_under_heatmap(self):
        tool = make_overlay_tool()
        for key, value in tool.al_voronoi_geo_storage.items():
            point = value['point']
            value['geo'] = box(point.x - 5.0, point.y - 5.0, point.x + 5.0, point.y + 5.0)

        tool.show_probing_geo(state=True, reset=True)

        outline_items = [
            item for item in tool.probing_shapes.shapes
            if item['face_color'] == '#00000000'
        ]
        self.assertEqual(len(outline_items), 4)
        self.assertTrue(all(item['color'] == '#000000FF' for item in outline_items))

    def test_generate_bilinear_geometry_assigns_a_cell_to_every_point(self):
        tool = make_overlay_tool(heights_valid=False)
        tool.solid_geo = box(0.0, 0.0, 10.0, 10.0)
        pts = [
            (value['point'].x, value['point'].y, 0.0)
            for value in tool.al_voronoi_geo_storage.values()
        ]

        tool.generate_bilinear_geometry(pts=pts)

        self.assertEqual(tool.al_bilinear_geo_storage, pts)
        cells = []
        for value in tool.al_voronoi_geo_storage.values():
            self.assertIsNotNone(value['geo'])
            self.assertTrue(value['geo'].covers(value['point']))
            cells.append(value['geo'])
        for idx, cell in enumerate(cells):
            for other in cells[idx + 1:]:
                self.assertLess(cell.intersection(other).area, 1e-9)
        envelope = tool.solid_geo.envelope.buffer(1)
        self.assertAlmostEqual(unary_union(cells).area, envelope.area, places=6)

    def test_non_finite_heights_show_only_probe_markers(self):
        for invalid_height in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(invalid_height=invalid_height):
                tool = make_overlay_tool()
                tool.al_voronoi_geo_storage[1]['height'] = invalid_height

                tool.show_probing_geo(state=True, reset=True)

                self.assertTrue(tool.probing_shapes.shapes)
                self.assertTrue(all(
                    item['color'] == '#000000FF'
                    for item in tool.probing_shapes.shapes
                ))



class TestFiniteLevellingInput(unittest.TestCase):
    def test_non_finite_height_map_rows_are_invalid(self):
        for row in ('0.0,0.0,nan', '0.0,0.0,inf', '0.0,0.0,-inf'):
            with self.subTest(row=row):
                self.assertIsNone(parse_height_map_line(row))

    def test_non_finite_grbl_probe_values_are_rejected(self):
        for row in (
                '[PRB:nan,0.0,0.0:1]',
                '[PRB:0.0,inf,0.0:1]',
                '[PRB:0.0,0.0,-inf:1]'
        ):
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    parse_grbl_probe_output(row)


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
        self.target = make_tool_target({1: GCODE_SAMPLE})

    def test_g1_lines_get_height_compensated(self):
        result = self.tool.autolevell_gcode(self.target, 'b')
        self.assertIsNotNone(result)
        lines = result[1].splitlines()

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

    def test_source_tool_gcode_not_mutated(self):
        original = self.target.tools[1]['gcode']
        self.tool.autolevell_gcode(self.target, 'b')
        self.assertEqual(self.target.tools[1]['gcode'], original)

    def test_trailing_newline_preserved(self):
        result = self.tool.autolevell_gcode(self.target, 'b')
        self.assertTrue(self.target.tools[1]['gcode'].endswith('\n'))
        self.assertTrue(result[1].endswith('\n'))



class TestAutolevellGcodeIrregularGrid(unittest.TestCase):
    def test_irregular_grid_falls_back_to_nearest_with_warning(self):
        storage = {
            0: {'point': Point(0, 0), 'geo': None, 'height': 1.0},
            1: {'point': Point(10, 0), 'geo': None, 'height': 2.0},
            2: {'point': Point(5, 10), 'geo': None, 'height': 3.0},
        }
        tool = make_tool(storage=storage)
        target = make_tool_target({1: "G1 X0 Y0 Z-0.1\n"})
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNotNone(result)

        warning_calls = [
            c for c in tool.app.inform.emit.call_args_list
            if '[WARNING_NOTCL]' in c.args[0]
        ]
        self.assertEqual(len(warning_calls), 1)

        expected_z = -0.1 + 1.0  # nearest to (0, 0) is height 1.0
        self.assertEqual(result[1].strip(), "G1 X0 Y0 Z{0:.4f}".format(expected_z))


class TestAutolevellGcodeVoronoi(unittest.TestCase):
    def test_voronoi_mode_uses_nearest(self):
        storage = {
            0: {'point': Point(0, 0), 'geo': None, 'height': 1.0},
            1: {'point': Point(20, 0), 'geo': None, 'height': 5.0},
        }
        tool = make_tool(storage=storage)
        target = make_tool_target({1: "G1 X1 Y0 Z-0.2\n"})
        result = tool.autolevell_gcode(target, 'v')
        expected_z = -0.2 + 1.0
        self.assertEqual(result[1].strip(), "G1 X1 Y0 Z{0:.4f}".format(expected_z))


class TestAutolevellGcodeErrors(unittest.TestCase):
    def setUp(self):
        self.storage = make_storage_grid([0, 10], [0, 10])

    def test_not_segmented_returns_none_and_errors(self):
        tool = make_tool(storage=self.storage)
        target = make_tool_target({1: "G1 X0 Y0 Z0\n"}, is_segmented_gcode=False)
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNone(result)
        tool.app.inform.emit.assert_called()
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])

    def test_none_target_returns_none(self):
        tool = make_tool(storage=self.storage)
        self.assertIsNone(tool.autolevell_gcode(None, 'b'))

    def test_empty_storage_returns_none(self):
        tool = make_tool(storage={}, heights_valid=False)
        target = make_tool_target({1: "G1 X0 Y0 Z0\n"})
        self.assertIsNone(tool.autolevell_gcode(target, 'b'))

    def test_heights_not_valid_returns_none(self):
        # storage has entries (with placeholder 'height': 0.0, as created
        # when probe points are added) but they were never actually probed
        tool = make_tool(storage=self.storage, heights_valid=False)
        target = make_tool_target({1: "G1 X0 Y0 Z0\n"})
        result = tool.autolevell_gcode(target, 'b')
        self.assertIsNone(result)
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])


    def test_units_mismatch_returns_none(self):
        tool = make_tool(units='MM', storage=self.storage)
        target = make_tool_target({1: "G1 X0 Y0 Z0\n"}, units='IN')
        self.assertIsNone(tool.autolevell_gcode(target, 'b'))


class TestSendGrblCommand(unittest.TestCase):
    @staticmethod
    def _send(tool, command, echo=True):
        """What a typed command does: one reserved transaction, then the wait for Idle."""
        op = tool._grbl_reserve('command', motion=True)
        if op is None:
            return ''
        try:
            text, status = tool._grbl_transact(op, command, timeout=30.0, echo=echo)
            if status == 'ok':
                tool._grbl_wait_idle(op)
            return text
        finally:
            tool._grbl_release(op)

    def _tool(self, replies=None):
        tool = make_tool(cls=ToolGrblSender)
        tool.app.inform_shell = MagicMock()
        tool._grbl_connected = True
        tool._grbl_op_lock = threading.Lock()
        tool._grbl_op = None
        tool._grbl_recovery = None
        tool._grbl_close_pending = False
        tool._grbl_safety_generation = 0
        tool._grbl_rx_port = None
        tool._grbl_rx_buffer = b''
        tool._grbl_reply_pending = False
        tool._grbl_reset_pending = False
        port = MagicMock()
        port.is_open = True
        port.in_waiting = 0
        queue = []

        def write(data):
            self.assertIsInstance(data, bytes)
            if data == b'?':
                self.assertIsNotNone(tool._grbl_op)
                self.assertTrue(tool._grbl_op.motion)
                queue.append(b'<Idle|MPos:0,0,0|FS:0,0>\r\n')
            elif data not in (b'!', b'\x18'):
                queue.extend([b'ok\r\n'] if replies is None else replies)
            return len(data)

        port.write.side_effect = write
        port.readline.side_effect = lambda: queue.pop(0) if queue else b''
        tool.grbl_ser_port = port
        return tool, port

    def test_decodes_bytes_and_joins_lines(self):
        tool, port = self._tool([
            b'[PRB:1.000,2.000,-0.500:1]\r\n',
            b'ok\r\n',
        ])
        result = self._send(tool, 'G38.2 Z-1 F50')
        self.assertIsInstance(result, str)
        self.assertIn('PRB:1.000,2.000,-0.500:1', result)
        self.assertIn('ok', result.lower())
        self.assertEqual(result, '[PRB:1.000,2.000,-0.500:1]\nok')
        self.assertEqual([c.args[0] for c in port.write.call_args_list], [b'G38.2 Z-1 F50\n', b'?'])
        port.readlines.assert_not_called()
        self.assertIsNone(tool._grbl_op)
        self.assertIsNone(tool._grbl_recovery)


    def test_no_answer_requires_recovery(self):
        tool, port = self._tool([])
        with patch('appPlugins.Common.grbl.grbl_client.time.monotonic', side_effect=[0.0, 0.01, 31.0]):
            result = self._send(tool, 'G0 X1')
        self.assertEqual(result, '')
        port.readline.assert_called_once()
        self.assertEqual([c.args[0] for c in port.write.call_args_list], [b'G0 X1\n', b'!'])
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertIsNone(tool._grbl_op)

    def test_echo_includes_command_and_decoded_reply(self):
        tool, port = self._tool()
        self._send(tool, 'G0 X1')
        self.assertEqual(tool.console_line_sig.emit.call_args_list,
                         [call('G0 X1'), call('Answer:             OK')])

    def test_echo_false_suppresses_command_and_reply(self):
        tool, port = self._tool()
        self.assertEqual(self._send(tool, 'G0 X1', echo=False), 'ok')
        tool.console_line_sig.emit.assert_not_called()
        self.assertEqual([c.args[0] for c in port.write.call_args_list], [b'G0 X1\n', b'?'])


class TestToolUiState(unittest.TestCase):
    @staticmethod
    def _run_set_tool_ui(storage, loaded_obj=None):
        tool = ToolLevelling.__new__(ToolLevelling)
        tool.app = MagicMock()
        tool.app.app_units = 'MM'
        tool.app.options = {
            'global_app_level': 'a',
            'tools_al_plot_points': False,
            'tools_al_avoid_exc_holes': False,
            'tools_al_method': 'v',
        }
        tool.app.collection.get_active.return_value = None
        tool.app.collection.get_by_name.return_value = loaded_obj
        tool.app.plotcanvas.view.scene = MagicMock()
        tool.app.pool = MagicMock()
        tool.layout = MagicMock()
        tool.form_fields = {}
        tool.al_voronoi_geo_storage = storage
        tool.al_bilinear_geo_storage = {}
        tool.al_heights_valid = True
        tool.probing_gcode_text = ''
        tool.probing_gcode = MagicMock(return_value='')
        tool.clear_ui = MagicMock()
        tool.connect_signals_at_init = MagicMock()
        tool.to_form = MagicMock()
        tool.on_controller_change_alter_ui = MagicMock()
        tool.change_level = MagicMock()
        tool.build_tool_ui = MagicMock()
        tool.on_avoid_exc_holes = MagicMock()
        tool.mouse_events_connected = False
        tool.probing_shapes = None
        tool._al_target_name = None
        tool._al_target_obj = None
        tool._al_generation = 0

        ui = MagicMock()
        ui.al_mode_radio.blockSignals.return_value = False
        ui.al_method_radio.blockSignals.return_value = False
        with patch('appPlugins.ToolLevelling.LevelUI', return_value=ui), \
                patch('appPlugins.Common.levelling_core.ShapeCollection'):
            tool.set_tool_ui()
        return tool

    def test_complete_retained_storage_remains_valid(self):
        storage = {
            'a': {'point': Point(0.0, 0.0), 'height': 0.1},
            'b': {'point': Point(1.0, 0.0), 'height': -0.2},
        }
        tool = self._run_set_tool_ui(storage)
        self.assertTrue(tool.al_heights_valid)
        self.assertIs(tool.al_voronoi_geo_storage, storage)

    def test_empty_or_partial_retained_storage_is_invalid(self):
        for storage in (
                {},
                {'a': {'point': Point(0.0, 0.0), 'height': None}},
                {'a': {'point': Point(0.0, 0.0)}}
        ):
            with self.subTest(storage=storage):
                self.assertFalse(self._run_set_tool_ui(storage).al_heights_valid)

    def test_selecting_supported_target_preserves_retained_storage(self):
        # regression: set_tool_ui() used to call on_mode_radio() (directly,
        # and indirectly via al_mode_radio.set_value() -> toggled ->
        # activated_custom) when a supported CNCJob target is selected in
        # object_combo, which unconditionally wiped al_voronoi_geo_storage
        # and al_heights_valid - destroying a probed/imported height map
        # just from re-opening the tool.
        storage = {
            'a': {'point': Point(0.0, 0.0), 'height': 0.1},
            'b': {'point': Point(1.0, 0.0), 'height': -0.2},
        }
        loaded_obj = SimpleNamespace(
            kind='geometry',
            is_segmented_gcode=True,
            obj_options={
                'type': 'Geometry',
                'tools_al_mode': 'grid',
                'tools_al_method': 'v',
            },
        )
        tool = self._run_set_tool_ui(storage, loaded_obj=loaded_obj)

        self.assertIs(tool.al_voronoi_geo_storage, storage)
        self.assertEqual(len(tool.al_voronoi_geo_storage), 2)
        self.assertTrue(tool.al_heights_valid)
        # al_mode_radio.set_value() must not be left with signals blocked
        tool.ui.al_mode_radio.blockSignals.assert_any_call(True)
        tool.ui.al_mode_radio.blockSignals.assert_any_call(False)
        self.assertEqual(tool.ui.al_mode_radio.blockSignals.call_args_list[-1].args, (False,))



class TestLevellingTargetSelection(unittest.TestCase):
    def test_segmented_geometry_and_excellon_are_enabled(self):
        for target_type in ('Geometry', 'Excellon'):
            with self.subTest(target_type=target_type):
                tool = make_tool()
                tool.ui.object_combo.currentText.return_value = 'job'
                tool.app.collection.get_by_name.return_value = SimpleNamespace(
                    is_segmented_gcode=True,
                    obj_options={'type': target_type},
                )
                tool.probing_shapes = None
                with patch('appPlugins.Common.levelling_core.ShapeCollection'):
                    tool.on_object_changed()
                tool.ui.al_frame.setDisabled.assert_called_once_with(False)

    def test_non_segmented_remains_disabled(self):
        tool = make_tool()
        tool.ui.object_combo.currentText.return_value = 'job'
        tool.app.collection.get_by_name.return_value = SimpleNamespace(
            is_segmented_gcode=False,
            obj_options={'type': 'Excellon'},
        )
        tool.probing_shapes = None
        tool._al_target_name = None
        tool._al_target_obj = None
        tool._al_generation = 0
        tool.on_object_changed()
        tool.ui.al_frame.setDisabled.assert_called_once_with(True)


class TestHeightmapSave(unittest.TestCase):
    def _save(self, storage, heights_valid=True):
        tool = make_tool(storage=storage, heights_valid=heights_valid)
        tool.grbl_probe_result = 'ok\n[PRB:raw protocol]\n'
        tool.app.options = {'cncjob_line_ending': False}
        tool.app.get_last_save_folder.return_value = 'C:/tmp'
        output_file = mock_open()
        with patch(
                'appPlugins.ToolLevelling.FCFileSaveDialog.get_saved_filename',
                return_value=('C:/tmp/map.txt', '')
        ) as dialog, patch('builtins.open', output_file):
            tool.on_grbl_heightmap_save()
        return tool, dialog, output_file

    def test_saves_normalized_rows_in_storage_order(self):
        storage = {
            'first': {'point': Point(1.0, 2.0), 'height': -0.1},
            'second': {'point': Point(3.5, 4.25), 'height': 0.2},
        }
        _, _, output_file = self._save(storage)
        written = ''.join(call.args[0] for call in output_file().write.call_args_list)
        self.assertEqual(written, '1.0,2.0,-0.1\n3.5,4.25,0.2\n')
        self.assertNotIn('[PRB:', written)
        self.assertNotIn('ok', written)

    def test_incomplete_map_does_not_open_save_dialog_or_file(self):
        for storage, heights_valid in (
                ({}, True),
                ({'a': {'point': Point(0.0, 0.0), 'height': 0.1}}, False),
                ({'a': {'point': Point(0.0, 0.0), 'height': None}}, True),
        ):
            with self.subTest(storage=storage, heights_valid=heights_valid):
                tool, dialog, output_file = self._save(storage, heights_valid)
                dialog.assert_not_called()
                output_file.assert_not_called()
                self.assertTrue(any(
                    '[ERROR_NOTCL]' in call.args[0]
                    for call in tool.app.inform.emit.call_args_list
                ))


class TestImportHeightMap(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir.name, name)
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_records_data_units_without_mutating_self_units(self):
        # An empty-storage import captures the project's units for its new
        # points. Worker parsing must not rewrite the tool's shared units.
        path = self._write('units.txt', "0.0,0.0,-0.01\n10.0,0.0,-0.02\n")
        tool = make_tool(units='IN', storage={}, heights_valid=False)
        tool.app.app_units = 'MM'
        tool.import_height_map(path)

        self.assertEqual(tool.units, 'IN')
        self.assertEqual(tool._al_data_units, 'MM')
        self.assertTrue(tool.al_heights_valid)

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
        tool.apply_autolevel_sig.emit.assert_not_called()


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
        self.solid_geometry = None
        self.pp_geometry_name = None
        self.pp_excellon_name = None
        self.pp_solderpaste_name = None
        self.exc_tools = None

    def gcode_parse(self, tool_data=None):
        return list(self.gcode.splitlines())

    def create_geometry(self):
        # mirrors camlib.CNCjob.create_geometry(): builds solid_geometry
        # from self.gcode_parsed (must already hold every tool's geometry,
        # not just the last tool processed)
        self.geometry_created = True
        self.solid_geometry = list(self.gcode_parsed) if self.gcode_parsed else []


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

    def _set_owner(self, tool, target):
        tool._al_target_name = target.obj_options['name']
        tool._al_target_obj = target
        tool._al_data_units = target.units.upper()
        tool.app.collection.get_by_name.return_value = target

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


    def test_units_mismatch_against_fresh_app_units_errors_and_creates_nothing(self):
        # target and self.units (stale) both say 'MM', but the app's *current*
        # units are 'IN'; AppObject.new_object() converts the new object's
        # units right after obj_init() runs (and CNCJobObject.convert_units()
        # does not scale G-code), so validating against a stale self.units
        # would let a units-mismatched height map through silently
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        target.units = 'MM'
        tool = make_tool(units='MM', storage=self.storage)
        self._set_owner(tool, target)
        tool.app.app_units = 'IN'
        tool.app.collection.get_by_name.return_value = target
        tool.ui.al_method_radio.get_value.return_value = 'b'

        tool.apply_autolevel()
        tool.app.worker_task.emit.assert_not_called()

        tool.app.app_obj.new_object.assert_not_called()
        self.assertTrue(any('[ERROR_NOTCL]' in c.args[0] for c in tool.app.inform.emit.call_args_list))
        self.assertFalse(tool._al_apply_running)

    def _run_worker(self, tool, target, new_obj_factory=FakeNewCNCJob):
        """Trigger apply_autolevel(), capture the emitted worker_task, run
        it synchronously against a fake new object, and return that
        object (or None if new_object was never called)."""
        self._set_owner(tool, target)
        tool.ui.al_method_radio.get_value.return_value = 'b'

        captured = {}

        def fake_new_object(kind, name, obj_init, *args, **kwargs):
            captured['kind'] = kind
            captured['name'] = name
            new_obj = new_obj_factory()
            if obj_init(new_obj, tool.app) == 'fail':
                return 'fail'
            captured['new_obj'] = new_obj
            return 'success'

        tool.app.app_obj.new_object.side_effect = fake_new_object

        tool.apply_autolevel()
        self.assertTrue(tool._al_apply_running)

        worker_dict = tool.app.worker_task.emit.call_args.args[0]
        worker_dict['fcn']()

        return captured

    def test_coverage_warning_published_only_by_current_gui_result(self):
        for change in ('none', 'generation', 'target', 'units'):
            with self.subTest(change=change):
                tool = make_tool(storage=self.storage)
                target = make_apply_target({1: 'G21 G90\nG1 X30 Y0 Z-1\nG1 X40 Y0\n'})
                pending = []
                tool.al_result_ready_sig.emit.side_effect = pending.append
                captured = self._run_worker(tool, target)
                self.assertIn('new_obj', captured)
                self.assertEqual(TestHeightMapCoverage.warnings(tool), [])
                self.assertEqual(len(pending), 1)
                if change == 'generation':
                    tool._al_bump_generation()
                elif change == 'target':
                    tool._al_target_obj = make_apply_target({1: ''})
                elif change == 'units':
                    target.units = 'IN'
                tool._on_al_result_ready(pending[0])
                self.assertEqual(len(TestHeightMapCoverage.warnings(tool)),
                                 1 if change == 'none' else 0)
                tool.build_al_table_sig.emit.assert_not_called()

    def test_coverage_uses_captured_map_without_worker_widget_reads(self):
        tool = make_tool(storage=self.storage)
        target = make_apply_target({1: 'G21 G90\nG1 X30 Y0 Z-1\n'})
        self._set_owner(tool, target)
        tool.ui.al_method_radio.get_value.return_value = 'b'
        tool.apply_autolevel()
        worker = tool.app.worker_task.emit.call_args.args[0]['fcn']
        tool.al_voronoi_geo_storage = make_storage_grid([0, 100], [0, 100])
        tool.ui = None
        tool.app.app_obj.new_object.return_value = 'success'
        worker()
        self.assertEqual(len(TestHeightMapCoverage.warnings(tool)), 1)

    def test_stale_apply_does_not_publish_coverage_warning(self):
        tool = make_tool(storage=self.storage)
        target = make_apply_target({1: 'G21 G90\nG1 X30 Y0 Z-1\n'})
        self._set_owner(tool, target)
        tool.ui.al_method_radio.get_value.return_value = 'b'
        tool.apply_autolevel()
        worker = tool.app.worker_task.emit.call_args.args[0]['fcn']
        tool._al_target_obj = make_apply_target({1: ''})
        worker()
        self.assertEqual(TestHeightMapCoverage.warnings(tool), [])
        tool.app.app_obj.new_object.assert_not_called()
        tool.al_result_ready_sig.emit.assert_not_called()

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


    def test_new_object_fail_emits_error_not_success(self):
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        tool = make_tool(storage=self.storage)
        self._set_owner(tool, target)
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
        self._set_owner(tool, target)
        tool.ui.al_method_radio.get_value.return_value = 'b'
        tool.autolevell_gcode = MagicMock(side_effect=RuntimeError('boom'))

        tool.apply_autolevel()
        worker_dict = tool.app.worker_task.emit.call_args.args[0]

        with self.assertRaises(RuntimeError):
            worker_dict['fcn']()

        self.assertFalse(tool._al_apply_running)

    def test_gcode_parsed_and_solid_geometry_include_all_tools(self):
        # regression: gcode_parse() only ever sets self.gcode_parsed from
        # self.gcode, so calling it once per tool and keeping only the
        # last call's result would silently drop every tool but the last
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n", 2: "G1 X5 Y5 Z-0.2\n"})
        tool = make_tool(storage=self.storage)

        captured = self._run_worker(tool, target)
        new_obj = captured['new_obj']

        self.assertEqual(len(new_obj.gcode_parsed), 2)
        self.assertEqual(len(new_obj.solid_geometry), 2)
        self.assertIn(new_obj.tools[1]['gcode'], new_obj.gcode)
        self.assertIn(new_obj.tools[2]['gcode'], new_obj.gcode)

    def test_apply_against_real_cncjob_preserves_all_tools_geometry(self):
        from test_levelling_journey import make_real_cncjob

        target = make_apply_target({
            1: 'G21\nG90\nG0 X0 Y0 Z2\nG1 Z-0.1\nG1 X5 Y0\n',
            2: 'G1 X10 Y0\n',
        })
        tool = make_tool(storage=self.storage)
        captured = self._run_worker(tool, target, new_obj_factory=make_real_cncjob)
        obj = captured['new_obj']

        self.assertNotEqual(obj.tools[1]['gcode'], target.tools[1]['gcode'])
        self.assertIn('Z0.1000', obj.tools[2]['gcode'])
        self.assertTrue(obj.tools[1]['gcode_parsed'])
        self.assertTrue(obj.tools[2]['gcode_parsed'])
        self.assertEqual(len(obj.gcode_parsed), sum(
            len(value['gcode_parsed']) for value in obj.tools.values()))
        self.assertTrue(obj.solid_geometry)
        self.assertEqual(obj.used_tools, target.used_tools)


    def test_pp_names_and_exc_tools_are_copied(self):
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        target.pp_geometry_name = 'default'
        target.pp_excellon_name = 'default'
        target.pp_solderpaste_name = None
        target.exc_tools = {1: {'tooldia': 1.0, 'drills': []}}
        tool = make_tool(storage=self.storage)

        captured = self._run_worker(tool, target)
        new_obj = captured['new_obj']

        self.assertEqual(new_obj.pp_geometry_name, 'default')
        self.assertEqual(new_obj.pp_excellon_name, 'default')
        self.assertIsNone(new_obj.pp_solderpaste_name)
        self.assertEqual(new_obj.exc_tools, {1: {'tooldia': 1.0, 'drills': []}})
        self.assertIsNot(new_obj.exc_tools, target.exc_tools)

    def test_apply_stops_for_unsupported_preprocessor(self):
        target = make_apply_target({1: "G1 X0 Y0 Z-0.1\n"})
        target.pp_geometry_name = 'Roland_test'
        tool = make_tool(storage=self.storage)
        self._set_owner(tool, target)
        tool.ui.al_method_radio.get_value.return_value = 'b'

        tool.apply_autolevel()
        tool.app.worker_task.emit.assert_not_called()

        tool.app.app_obj.new_object.assert_not_called()
        self.assertFalse(tool._al_apply_running)


class TestAutolevellGcodeToolsOrderAndDialects(unittest.TestCase):
    def setUp(self):
        # 4-point flat (height 0 everywhere) bilinear grid: offset_fn is
        # always exactly 0, so a levelled line's Z is exactly the modal Z
        # tracked in `state` - which makes it easy to tell which tool ran
        # first.
        self.flat_storage = {
            0: {'point': Point(0, 0), 'geo': None, 'height': 0.0},
            1: {'point': Point(10, 0), 'geo': None, 'height': 0.0},
            2: {'point': Point(0, 10), 'geo': None, 'height': 0.0},
            3: {'point': Point(10, 10), 'geo': None, 'height': 0.0},
        }

    def test_tools_are_processed_in_dict_order_not_sorted(self):
        # tool 9 sets modal Z to -0.3; tool 3 (numerically smaller key,
        # but inserted 2nd) has no Z word of its own, so its levelled Z
        # depends on whichever tool ran right before it
        target = SimpleNamespace(
            is_segmented_gcode=True, coords_decimals=4, units='MM',
            tools={
                9: {'gcode': "G1 Z-0.3000 F100\n", 'data': {}},
                3: {'gcode': "G1 X0 Y0\n", 'data': {}},
            },
        )
        tool = make_tool(storage=self.flat_storage)

        result = tool.autolevell_gcode(target, 'b')

        self.assertIsNotNone(result)
        # if tool 3 had run first (sorted order), its Z would be 0.0000
        self.assertIn("Z-0.3000", result[3])

    def test_roland_preprocessor_rejected(self):
        target = SimpleNamespace(
            is_segmented_gcode=True, coords_decimals=4, units='MM',
            pp_geometry_name='Roland_GRBL', pp_excellon_name='default', pp_solderpaste_name=None,
            tools={1: {'gcode': "G1 X0 Y0 Z-0.1\n", 'data': {}}},
        )
        tool = make_tool(storage=self.flat_storage)

        result = tool.autolevell_gcode(target, 'b')

        self.assertIsNone(result)
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])
        self.assertIn('Roland_GRBL', tool.app.inform.emit.call_args.args[0])

    def test_hpgl_preprocessor_rejected_case_insensitive(self):
        target = SimpleNamespace(
            is_segmented_gcode=True, coords_decimals=4, units='MM',
            pp_geometry_name='default', pp_excellon_name='HPGL2', pp_solderpaste_name=None,
            tools={1: {'gcode': "G1 X0 Y0 Z-0.1\n", 'data': {}}},
        )
        tool = make_tool(storage=self.flat_storage)

        result = tool.autolevell_gcode(target, 'b')

        self.assertIsNone(result)
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])


    def test_solderpaste_preprocessor_rejected(self):
        target = SimpleNamespace(
            is_segmented_gcode=True, coords_decimals=4, units='MM',
            pp_geometry_name='default', pp_excellon_name='default', pp_solderpaste_name='Paste_1',
            tools={1: {'gcode': "G1 X0 Y0 Z-0.1\n", 'data': {}}},
        )
        tool = make_tool(storage=self.flat_storage)

        result = tool.autolevell_gcode(target, 'b')

        self.assertIsNone(result)
        self.assertIn('[ERROR_NOTCL]', tool.app.inform.emit.call_args.args[0])
        self.assertIn('Paste_1', tool.app.inform.emit.call_args.args[0])

    def test_default_preprocessor_names_are_allowed(self):
        target = SimpleNamespace(
            is_segmented_gcode=True, coords_decimals=4, units='MM',
            pp_geometry_name='default', pp_excellon_name='default', pp_solderpaste_name=None,
            tools={1: {'gcode': "G1 X0 Y0 Z-0.1\n", 'data': {}}},
        )
        tool = make_tool(storage=self.flat_storage)

        result = tool.autolevell_gcode(target, 'b')

        self.assertIsNotNone(result)



if __name__ == '__main__':
    unittest.main()
