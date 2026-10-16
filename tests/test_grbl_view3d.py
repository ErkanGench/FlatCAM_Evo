# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/17/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""Tests of SenderView3d and of the Plot 3D part of the GRBL Sender (T19, A9)."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from vispy import scene

from tests.test_levelling_audit import FakeGrbl, make_audit_tool, sg_module
from tests.grbl_stream_helpers import make_stream_tool, make_storage, CheckFake
from appPlugins.Common.levelling_interp import build_bilinear_grid
from appPlugins.ToolGrblSender import SenderView3d as view3d_module
from appPlugins.ToolGrblSender.SenderView3d import SenderView3d, ACCEPTED_COLOR, CHORD_COLOR, CUT_COLOR


def fake_canvas():
    """A stand-in for the PlotCanvas3d: a real vispy scene node (no GL context needed) and fit_view()."""
    return SimpleNamespace(view=SimpleNamespace(scene=scene.Node()), fit_view=MagicMock())


SEGMENTS = [
    (0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), True),
    (1, (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), False),
    (2, (1.0, 1.0, 0.0), (0.0, 1.0, 0.0), False),
]


class SenderView3dTest(unittest.TestCase):

    def test_set_toolpath(self):
        view = SenderView3d(fake_canvas())
        view.set_toolpath(SEGMENTS)
        self.assertEqual(view.path.pos.dtype, np.float32)
        self.assertEqual(view.path.pos.shape, (6, 3))
        self.assertEqual(view.path.color.shape, (6, 4))
        self.assertEqual(tuple(view.path.color[2]), CUT_COLOR)

    def test_empty_toolpath_is_float32(self):
        view = SenderView3d(fake_canvas())
        view.set_toolpath(SEGMENTS)
        view.set_toolpath([])
        self.assertEqual(view.path.pos.dtype, np.float32)
        self.assertEqual(view.path.pos.shape, (0, 3))
        self.assertEqual(view.accepted.pos.shape, (0, 3))

    def test_chord_lines_are_grey(self):
        view = SenderView3d(fake_canvas())
        view.set_toolpath(SEGMENTS, chord_lines={2})
        self.assertEqual(tuple(view.path.color[4]), CHORD_COLOR)
        self.assertEqual(tuple(view.path.color[2]), CUT_COLOR)

    def test_set_accepted(self):
        view = SenderView3d(fake_canvas())
        view.set_toolpath(SEGMENTS)
        self.assertEqual(view.accepted.pos.shape, (0, 3))
        view.set_accepted(1)
        self.assertEqual(view.accepted.pos.dtype, np.float32)
        self.assertEqual(view.accepted.pos.shape, (4, 3))
        self.assertEqual(tuple(view.accepted.color), ACCEPTED_COLOR)
        view.set_accepted(-1)
        self.assertEqual(view.accepted.pos.shape, (0, 3))
        self.assertFalse(hasattr(view, 'set_done'))

    def test_tool_position(self):
        view = SenderView3d(fake_canvas())
        view.set_tool_position((1.0, 2.0, 3.0))
        self.assertEqual(view.tool._data['a_position'].dtype, np.float32)
        self.assertEqual(tuple(view.tool._data['a_position'][0]), (1.0, 2.0, 3.0))

    def test_height_map_faces(self):
        canvas = fake_canvas()
        view = SenderView3d(canvas)
        points = [(v['point'].x, v['point'].y, v['height']) for v in make_storage().values()]
        xs, ys, grid = build_bilinear_grid(points, 1e-3)
        view.set_height_map((xs, ys, grid), z_scale=5.0)
        self.assertIs(view.mesh.parent, canvas.view.scene)
        self.assertEqual(view.mesh.mesh_data.n_faces, 2 * (len(xs) - 1) * (len(ys) - 1))
        self.assertEqual(view.mesh.mesh_data.get_vertices().dtype, np.float32)
        self.assertAlmostEqual(float(view.mesh.mesh_data.get_vertices()[:, 2].max()), 5.0 * 0.3, places=5)
        old = view.mesh
        view.set_height_map(None)
        self.assertIsNone(view.mesh)
        self.assertIsNone(old.parent)

    def test_clear_twice(self):
        canvas = fake_canvas()
        view = SenderView3d(canvas)
        view.set_toolpath(SEGMENTS)
        view.clear()
        view.clear()
        self.assertIsNone(view.path.parent)
        self.assertIsNone(view.accepted.parent)
        self.assertIsNone(view.tool.parent)

    def test_module_has_no_done_names(self):
        self.assertFalse(hasattr(view3d_module, 'DONE_COLOR'))
        self.assertTrue(hasattr(view3d_module, 'ACCEPTED_COLOR'))


def status_tool(units='MM', inches=None):
    tool = make_audit_tool(units)
    tool._last_wco = None
    tool._grbl_report_inches = inches
    tool.job_lines = []
    tool.job_line_numbers = []
    tool.view3d = MagicMock()
    target = SimpleNamespace(kind='cncjob', units=units, source_file='', obj_options={'name': 'job'},
                             coords_decimals=4)
    tool.app.collection.get_by_name.return_value = target
    return tool


def wpos_report(x, y, z):
    return {'state': 'Run', 'wpos': (x, y, z)}


class ReportUnitsTest(unittest.TestCase):

    def test_inches_report_mm_job(self):
        tool = status_tool('MM', True)
        tool._on_status_report(wpos_report(1.0, 2.0, 3.0))
        pos = tool.view3d.set_tool_position.call_args.args[0]
        self.assertAlmostEqual(pos[0], 25.4)
        self.assertAlmostEqual(pos[1], 50.8)
        self.assertAlmostEqual(pos[2], 76.2)
        self.assertIn('X 25.400', tool.ui.status_label.setText.call_args.args[0])

    def test_mm_report_inch_job(self):
        tool = status_tool('IN', False)
        tool._on_status_report(wpos_report(25.4, 0.0, 0.0))
        pos = tool.view3d.set_tool_position.call_args.args[0]
        self.assertAlmostEqual(pos[0], 1.0)

    def test_same_units_no_scale(self):
        tool = status_tool('MM', False)
        tool._on_status_report(wpos_report(1.0, 2.0, 3.0))
        self.assertEqual(tuple(tool.view3d.set_tool_position.call_args.args[0]), (1.0, 2.0, 3.0))

    def test_mpos_minus_wco_then_scaled(self):
        tool = status_tool('MM', True)
        tool._on_status_report({'state': 'Idle', 'mpos': (3.0, 3.0, 3.0), 'wco': (1.0, 1.0, 1.0)})
        pos = tool.view3d.set_tool_position.call_args.args[0]
        self.assertAlmostEqual(pos[0], 2.0 * 25.4)

    def test_unknown_setting_shows_no_position(self):
        tool = status_tool('MM', None)
        tool._on_status_report(wpos_report(1.0, 2.0, 3.0))
        tool.view3d.set_tool_position.assert_not_called()
        text = tool.ui.status_label.setText.call_args.args[0]
        self.assertNotIn('X ', text)
        self.assertIn('unknown', text)

    def test_unit_read_sets_state(self):
        for report_inches, expected in ((True, True), (False, False)):
            tool = make_stream_tool(FakeGrbl(report_inches=report_inches))
            tool.on_start()
            self.assertEqual(tool._grbl_report_inches, expected)
        fake = FakeGrbl(has_report_setting=False)
        tool = make_stream_tool(fake)
        tool._grbl_report_inches = True
        tool.on_start()
        self.assertIsNone(tool._grbl_report_inches)
        self.assertIn('$$', fake.commands())


class StartReadsReportUnitsTest(unittest.TestCase):

    def test_plain_start_reads_13_before_c(self):
        fake = CheckFake(report_inches=True)
        tool = make_stream_tool(fake, check_mode=True)
        tool.on_start()
        commands = fake.commands()
        self.assertIn('$$', commands)
        self.assertIn('$C', commands)
        self.assertLess(commands.index('$$'), commands.index('$C'))
        self.assertIs(tool._grbl_report_inches, True)
        self.assertIsNone(tool._grbl_op)

    def test_levelled_phase_reads_13(self):
        from tests.grbl_stream_helpers import make_levelled_stream_tool
        fake = CheckFake(report_inches=True)
        tool, _target = make_levelled_stream_tool(fake)
        tool.on_start()
        self.assertIs(tool._grbl_report_inches, True)


class ConnectReadsReportUnitsTest(unittest.TestCase):

    def test_connect_finish_reads_13_in_a_non_motion_operation(self):
        fake = FakeGrbl(report_inches=True)
        fake.rx.append(b'ok\r\n')
        fake.readlines = lambda: [b'ok\r\n']
        tool = make_audit_tool()
        tool.app.worker_task.emit.side_effect = lambda task: task['fcn']()
        attempt = object()
        tool.grbl_ser_port = fake
        tool._grbl_connect_attempt = attempt
        tool._last_wco = (1.0, 1.0, 1.0)
        tool._grbl_report_inches = None
        fake.rx.clear()
        timers = []
        with patch('appPlugins.ToolGrblSender.Sender.QtCore.QTimer.singleShot',
                   side_effect=lambda delay, callback: timers.append((delay, callback))):
            tool._grbl_connect_finish('COM3', fake, attempt)
        self.assertTrue(tool._grbl_connected)
        self.assertIsNone(tool._last_wco)
        self.assertEqual(len(timers), 1)
        self.assertIsNone(tool._grbl_op)
        timers[0][1]()
        self.assertIn('$$', fake.commands())
        self.assertIs(tool._grbl_report_inches, True)
        self.assertIsNone(tool._grbl_op)

    def test_connect_read_is_skipped_when_dirty(self):
        tool = make_audit_tool()
        tool.grbl_ser_port = FakeGrbl()
        tool._grbl_connected = True
        tool._grbl_stream_dirty = True
        tool._grbl_read_units_after_connect()
        tool.app.worker_task.emit.assert_not_called()
        self.assertIsNone(tool._grbl_op)


class WcoResetTest(unittest.TestCase):
    OLD = (1.0, 2.0, 3.0)

    def test_start(self):
        tool = status_tool()
        tool._last_wco = self.OLD
        tool.build_stream_job = MagicMock(return_value=False)
        tool.ui.autolevel_cb.get_value.return_value = False
        tool.on_start()
        self.assertIsNone(tool._last_wco)

    def test_start_levelled(self):
        tool = status_tool()
        tool._last_wco = self.OLD
        tool._start_levelled = MagicMock()
        tool.ui.autolevel_cb.get_value.return_value = True
        tool.on_start()
        self.assertIsNone(tool._last_wco)

    def test_zero(self):
        tool = status_tool()
        tool._last_wco = self.OLD
        tool._grbl_start_op = MagicMock()
        tool.on_grbl_zero('x')
        self.assertIsNone(tool._last_wco)

    def test_reset(self):
        tool = status_tool()
        tool._last_wco = self.OLD
        tool.on_grbl_reset()
        self.assertIsNone(tool._last_wco)

    def test_connect_click(self):
        tool = status_tool()
        tool._last_wco = self.OLD
        tool._grbl_report_inches = True
        tool.ui.com_list_combo.currentText.return_value = 'COM3'
        tool.ui.baudrates_list_combo.currentText.return_value = '115200'
        with patch.object(sg_module.serial, 'serial_for_url', side_effect=OSError('no port')):
            tool.on_grbl_connect()
        self.assertIsNone(tool._last_wco)
        self.assertIsNone(tool._grbl_report_inches)

    def test_connect_finish(self):
        fake = FakeGrbl()
        tool = status_tool()
        attempt = object()
        tool.grbl_ser_port = fake
        tool._grbl_connect_attempt = attempt
        tool._last_wco = self.OLD
        fake.readlines = lambda: [b'ok\r\n']
        with patch('appPlugins.ToolGrblSender.Sender.QtCore.QTimer.singleShot'):
            tool._grbl_connect_finish('COM3', fake, attempt)
        self.assertIsNone(tool._last_wco)

    def test_port_close(self):
        tool = status_tool()
        tool.grbl_ser_port = FakeGrbl()
        tool._grbl_connected = True
        tool._last_wco = self.OLD
        tool._grbl_report_inches = False
        tool._grbl_close_port()
        self.assertIsNone(tool._last_wco)
        self.assertIsNone(tool._grbl_report_inches)


class StaleVisualsTest(unittest.TestCase):

    def test_object_changed_clears_job_and_toolpath(self):
        tool = status_tool()
        tool.job_lines = ['G0 X1']
        tool.job_line_numbers = [1]
        tool.job_map_generation = 3
        other = SimpleNamespace(kind='geometry')
        tool.app.collection.get_by_name.return_value = other
        tool._al_target_name = 'job'
        tool._al_target_obj = other
        tool.ui.object_combo.currentText.return_value = 'job'
        tool.on_object_changed()
        self.assertEqual(tool.job_lines, [])
        self.assertEqual(tool.job_line_numbers, [])
        self.assertIsNone(tool.job_map_generation)
        tool.view3d.set_toolpath.assert_called_once_with([])

    def test_object_changed_without_view(self):
        tool = status_tool()
        tool.view3d = None
        tool.job_lines = ['G0 X1']
        other = SimpleNamespace(kind='geometry')
        tool.app.collection.get_by_name.return_value = other
        tool._al_target_name = 'job'
        tool._al_target_obj = other
        tool.ui.object_combo.currentText.return_value = 'job'
        tool.on_object_changed()
        self.assertEqual(tool.job_lines, [])

    def test_invalid_heights_remove_the_mesh(self):
        tool = status_tool()
        tool.al_heights_valid = False
        tool._update_3d_height_map()
        tool.view3d.set_height_map.assert_called_once_with(None)

    def test_valid_heights_make_the_mesh(self):
        tool = status_tool()
        tool.al_voronoi_geo_storage = make_storage()
        tool.al_heights_valid = True
        tool._update_3d_height_map()
        grid_data = tool.view3d.set_height_map.call_args.args[0]
        self.assertEqual(len(grid_data[0]), 3)
        self.assertEqual(len(grid_data[1]), 3)

    def test_no_view_no_error(self):
        tool = status_tool()
        tool.view3d = None
        tool._update_3d_height_map()


ARC_JOB = ['G21', 'G90', 'G18', 'G0 X0 Y0 Z0', 'G2 X10 Z0 I5 K0 F100', 'X20 Z0 I5 K0', 'G17', 'G1 X30',
           'G1 X40']
SPLIT_ARC_JOB = ['G21', 'G90', 'G0 X0 Y0 Z0', 'G2 X10 Y0 I5 J0 F100', 'G1 X12 Y0']


def show_tool(lines, arc_mode):
    tool = make_stream_tool(FakeGrbl(), source='\n'.join(lines) + '\n')
    tool.app.options = {'tools_grbl_arc_mode': arc_mode, 'tools_grbl_arc_segment': 2.0}
    tool.ui.autolevel_cb.get_value.return_value = False
    tool.ui.object_combo.get_value.return_value = 'job'
    tool.app.plotcanvas3d = fake_canvas()
    tool.app.collection.get_by_name.return_value.source_file = '\n'.join(lines) + '\n'
    return tool


class ShowIn3dTest(unittest.TestCase):

    def test_send_mode_unsplit_lines_are_grey_chords(self):
        tool = show_tool(ARC_JOB, 'send')
        tool.on_show_3d()
        view = tool.view3d
        # the stream keeps the arcs
        self.assertEqual(tool.job_lines, ARC_JOB)
        segments = view._segments
        # the 2 arcs of the G18 plane are not split: 1 chord each, in grey
        self.assertEqual([s[0] for s in segments if s[0] in (4, 5)], [4, 5])
        colors = {s[0]: tuple(view.path.color[2 * i]) for i, s in enumerate(segments)}
        self.assertEqual(colors[4], CHORD_COLOR)
        self.assertEqual(colors[5], CHORD_COLOR)
        self.assertEqual(colors[7], CUT_COLOR)
        self.assertEqual(view.path.pos.dtype, np.float32)
        tool.app.plotcanvas3d.fit_view.assert_called_once()

    def test_send_mode_split_arc_maps_to_its_stream_line(self):
        tool = show_tool(SPLIT_ARC_JOB, 'send')
        tool.on_show_3d()
        view = tool.view3d
        indexes = [s[0] for s in view._segments]
        # the arc (stream line 3) is drawn with many pieces; the pieces carry the stream line index
        self.assertGreater(indexes.count(3), 2)
        self.assertEqual(indexes[-1], 4)
        self.assertEqual(set(indexes), {3, 4})
        for color_index in range(0, len(view._segments)):
            self.assertNotEqual(tuple(view.path.color[2 * color_index]), CHORD_COLOR)
        # accepted: done counts stream lines
        tool._on_stream_progress(4, 5)
        self.assertEqual(view.accepted.pos.shape[0], 2 * indexes.count(3))
        tool._on_stream_progress(5, 5)
        self.assertEqual(view.accepted.pos.shape[0], 2 * len(indexes))

    def test_split_mode_uses_the_stream_lines(self):
        tool = show_tool(SPLIT_ARC_JOB, 'split')
        tool.on_show_3d()
        self.assertNotEqual(tool.job_lines, SPLIT_ARC_JOB)
        self.assertEqual(tool.view3d._segments[-1][0], len(tool.job_lines) - 1)

    def test_show_rebuilds_the_job(self):
        tool = show_tool(SPLIT_ARC_JOB, 'send')
        tool.job_lines = ['G0 X99']
        tool.on_show_3d()
        self.assertEqual(tool.job_lines, SPLIT_ARC_JOB)

    def test_failed_build_clears_the_toolpath(self):
        tool = show_tool(SPLIT_ARC_JOB, 'send')
        tool.on_show_3d()
        self.assertTrue(tool.view3d._segments)
        tool.build_stream_job = MagicMock(return_value=False)
        tool.on_show_3d()
        self.assertEqual(tool.view3d._segments, [])

    def test_opens_the_3d_tab_if_needed(self):
        tool = show_tool(SPLIT_ARC_JOB, 'send')
        canvas = tool.app.plotcanvas3d
        tool.app.plotcanvas3d = None

        def open_tab():
            tool.app.plotcanvas3d = canvas
        tool.app.on_3d_area.side_effect = open_tab
        tool.on_show_3d()
        tool.app.on_3d_area.assert_called_once()
        self.assertIs(tool.view3d.canvas, canvas)

    def test_no_canvas_no_view(self):
        tool = show_tool(SPLIT_ARC_JOB, 'send')
        tool.app.plotcanvas3d = None
        tool.on_show_3d()
        self.assertIsNone(tool.view3d)

    def test_height_map_hook_updates_the_mesh(self):
        tool = show_tool(SPLIT_ARC_JOB, 'send')
        tool.on_show_3d()
        tool.al_voronoi_geo_storage = make_storage()
        tool.al_heights_valid = True
        tool._al_on_height_map_ready(None, {'kind': 'probe', 'frame': ('G54', (0.0, 0.0, 0.0), False)})
        self.assertIsNotNone(tool.view3d.mesh)
        tool.al_heights_valid = False
        tool._update_3d_height_map()
        self.assertIsNone(tool.view3d.mesh)


if __name__ == '__main__':
    unittest.main()
