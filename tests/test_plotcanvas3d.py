"""Finite 3D workspace and camera interaction checks.

Run: .venv/Scripts/python.exe tests/test_plotcanvas3d.py
"""

import os
import sys
import unittest
from itertools import product
from types import SimpleNamespace
from unittest.mock import Mock, patch

if sys.platform != 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from vispy import app

app.use_app('pyqt6')

from appGUI.PlotCanvas3d import PlotCanvas3d


class CanvasApp(QtCore.QObject):
    pool_recreated = QtCore.pyqtSignal(object)

    def __init__(self, units='MM', custom_cursor=True):
        super().__init__()
        self.ui = QtWidgets.QWidget()
        self.pool = None
        self.app_units = units
        self.options = {
            'global_cursor_color_enabled': custom_cursor,
            'global_cursor_color': '#FF0000',
        }


class TestPlotCanvas3d(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_canvas(self, units='MM', custom_cursor=True):
        fcapp = CanvasApp(units, custom_cursor)
        layout = QtWidgets.QVBoxLayout(fcapp.ui)
        canvas = PlotCanvas3d(layout, fcapp)
        self.addCleanup(fcapp.ui.deleteLater)
        self.addCleanup(canvas.close)
        canvas.size = (800, 600)
        canvas.central_widget.size = (800, 600)
        canvas.view.size = (800, 600)
        canvas.fit_view()
        return canvas

    @staticmethod
    def mouse_event(kind, pos=(400, 300), start=None, buttons=(), delta=(0, 0), modifiers=()):
        pos = np.array(pos, dtype=float)
        press = None if start is None else SimpleNamespace(pos=np.array(start, dtype=float))
        mouse = SimpleNamespace(pos=pos, press_event=press, modifiers=modifiers)
        return SimpleNamespace(
            type=kind, pos=pos, mouse_event=mouse, press_event=press,
            buttons=buttons, delta=delta, handled=False,
        )

    def test_grid_is_bounded_and_fitted(self):
        canvas = self.make_canvas()
        self.assertTrue(hasattr(canvas, 'grid'), 'The 3D view must create its grid')
        np.testing.assert_allclose(canvas.grid.grid_bounds, (0, 400, 0, 400))
        self.assertTrue(np.isfinite(canvas.view.camera.center).all())
        self.assertGreater(canvas.view.camera.scale_factor, 400)
        self.assertEqual(canvas.view.camera.maximum_scene_size, canvas.view.camera.scale_factor)

    def test_fit_toolpath_bounds_with_canvas_padding(self):
        canvas = self.make_canvas()
        points = np.array(list(product((1000, 1020), (2000, 2010), (-3, 7))))
        canvas.view.camera.set_view('iso')
        canvas.fit_view(points=points, margin=0.1)
        projected = canvas.view.camera._scene_transform.map(points)
        screen = projected[:, :2] / projected[:, 3:]
        width, height = canvas.view.size
        self.assertGreaterEqual(screen[:, 0].min(), width * 0.1 - 1e-3)
        self.assertLessEqual(screen[:, 0].max(), width * 0.9 + 1e-3)
        self.assertGreaterEqual(screen[:, 1].min(), height * 0.1 - 1e-3)
        self.assertLessEqual(screen[:, 1].max(), height * 0.9 + 1e-3)
        self.assertTrue(np.any(np.isclose(np.ptp(screen, axis=0), (width * 0.8, height * 0.8))))

    def test_grid_size_changes_live_in_millimetres(self):
        for units, scale in (('MM', 1), ('IN', 1 / 25.4)):
            with self.subTest(units=units):
                canvas = self.make_canvas(units=units)
                self.assertTrue(hasattr(canvas, 'set_grid_size'), 'The grid needs a live size setter')
                np.testing.assert_allclose(canvas.get_grid_size(), (400, 400))
                grid = canvas.grid
                canvas.view.camera.set_view('iso')
                rotation = canvas.view.camera._get_rotation_tr().copy()
                canvas.set_grid_size(200)
                np.testing.assert_allclose(canvas.get_grid_size(), (200, 200))
                self.assertIs(canvas.grid, grid)
                size = 200 * scale
                np.testing.assert_allclose(grid.grid_bounds, (0, size, 0, size))
                np.testing.assert_allclose(canvas.workspace_line.bounds(0), (0, size))
                np.testing.assert_allclose(canvas.workspace_line.bounds(1), (0, size))
                np.testing.assert_allclose(canvas.xaxis.domain, (0, size))
                np.testing.assert_allclose(canvas.yaxis.domain, (0, size))
                np.testing.assert_allclose(canvas.xyz_axis.transform.scale[:3], (size / 10,) * 3)
                np.testing.assert_allclose(canvas.view.camera._get_rotation_tr(), rotation)

    def test_rectangular_grid_updates_both_axes_and_fits(self):
        for units, scale in (('MM', 1), ('IN', 1 / 25.4)):
            with self.subTest(units=units):
                canvas = self.make_canvas(units=units)
                canvas.set_grid_size(300, 150)
                np.testing.assert_allclose(canvas.get_grid_size(), (300, 150))
                np.testing.assert_allclose(canvas.grid.grid_bounds, (0, 300 * scale, 0, 150 * scale))
                np.testing.assert_allclose(canvas.workspace_line.bounds(0), (0, 300 * scale))
                np.testing.assert_allclose(canvas.workspace_line.bounds(1), (0, 150 * scale))
                np.testing.assert_allclose(canvas.xaxis.domain, (0, 300 * scale))
                np.testing.assert_allclose(canvas.yaxis.domain, (0, 150 * scale))
                points = canvas.view.camera._scene_transform.map(np.array([
                    (0, 0, 0), (300 * scale, 0, 0), (0, 150 * scale, 0), (300 * scale, 150 * scale, 0)
                ]))
                screen = points[:, :2] / points[:, 3:]
                self.assertGreaterEqual(screen[:, 0].min(), canvas.axis_padding - 1e-3)
                self.assertGreaterEqual(screen[:, 1].min(), 20 - 1e-3)
                self.assertLessEqual(screen[:, 0].max(), 800 - 20 + 1e-3)
                self.assertLessEqual(screen[:, 1].max(), 600 - canvas.axis_padding + 1e-3)
                canvas.set_grid_size(250)
                np.testing.assert_allclose(canvas.get_grid_size(), (250, 250))

    def test_wheel_matches_2d_and_keeps_the_cursor_anchor(self):
        canvas = self.make_canvas()
        camera = canvas.view.camera
        scale = camera.scale_factor
        center = camera.center
        point = np.array((250, 150, 0, 1), dtype=float)
        projected = camera._scene_transform.map(point)
        pos = projected[:2] / projected[3]
        event = self.mouse_event('mouse_wheel', pos=pos, delta=(0, 1))
        camera.viewbox_mouse_event(event)
        self.assertAlmostEqual(camera.scale_factor / scale, (1 + camera.zoom_factor) ** -30)
        after = camera._scene_transform.map(point)
        np.testing.assert_allclose(after[:2] / after[3], pos, atol=1e-5)
        self.assertTrue(event.handled)
        camera.viewbox_mouse_event(self.mouse_event('mouse_wheel', pos=pos, delta=(0, -1)))
        self.assertAlmostEqual(camera.scale_factor, scale)
        np.testing.assert_allclose(camera.center, center, atol=1e-5)

    def test_initial_view_is_top_down_and_fills_height_with_label_space(self):
        canvas = self.make_canvas()
        camera = canvas.view.camera
        points = np.array([(0, 0, 0, 1), (400, 0, 0, 1), (0, 400, 0, 1), (400, 400, 0, 1)])
        projected = camera._scene_transform.map(points)
        screen = projected[:, :2] / projected[:, 3:]
        self.assertGreater(screen[1, 0], screen[0, 0])
        self.assertLess(screen[2, 1], screen[0, 1])
        self.assertAlmostEqual(screen[1, 1], screen[0, 1])
        self.assertAlmostEqual(screen[2, 0], screen[0, 0])
        self.assertAlmostEqual(screen[1, 0] - screen[0, 0], screen[0, 1] - screen[2, 1], places=3)
        self.assertGreaterEqual(screen[:, 0].min(), canvas.axis_padding - 1e-3)
        self.assertGreaterEqual(screen[:, 1].min(), 20 - 1e-3)
        self.assertLessEqual(screen[:, 0].max(), 800 - 20 + 1e-3)
        self.assertLessEqual(screen[:, 1].max(), 600 - canvas.axis_padding + 1e-3)
        self.assertAlmostEqual(screen[0, 1] - screen[2, 1], 600 - canvas.axis_padding - 20, places=3)

    def test_zoom_in_stops_at_one_third_of_ten_millimetres(self):
        for units, limit in (('MM', 10 / 3), ('IN', 10 / 25.4 / 3)):
            with self.subTest(units=units):
                camera = self.make_canvas(units=units).view.camera
                camera.zoom(1e-6)
                self.assertAlmostEqual(camera.scale_factor, limit)
                camera.zoom(2)
                self.assertAlmostEqual(camera.scale_factor, limit * 2)

    def test_drag_tilts_in_screen_direction_from_any_start(self):
        canvas = self.make_canvas()
        camera = canvas.view.camera
        initial = camera.get_state()
        points = np.array([(200, 200, 0, 1), (200, 200, 40, 1)])
        for start in ((100, 100), (400, 300), (700, 500)):
            for dx, dy in ((-40, 0), (40, 0), (0, -40), (0, 40)):
                with self.subTest(start=start, delta=(dx, dy)):
                    camera.set_state(initial)
                    camera.viewbox_mouse_event(self.mouse_event('mouse_release'))
                    camera.viewbox_mouse_event(self.mouse_event(
                        'mouse_move', (start[0] + dx, start[1] + dy), start, (1,)
                    ))
                    projected = camera._scene_transform.map(points)
                    normal = projected[1, :2] / projected[1, 3] - projected[0, :2] / projected[0, 3]
                    self.assertGreater(np.dot(normal, (dx, dy)), 0)
                    self.assertAlmostEqual(normal[1 if dx else 0], 0, places=5)

if __name__ == '__main__':
    unittest.main()
