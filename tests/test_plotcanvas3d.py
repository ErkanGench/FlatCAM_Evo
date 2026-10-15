"""Finite 3D workspace and camera interaction checks.

Run: .venv/Scripts/python.exe tests/test_plotcanvas3d.py
"""

import os
import sys
import unittest
from types import SimpleNamespace

if sys.platform != 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6 import QtCore, QtWidgets
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

    def test_workspace_keeps_its_physical_size_in_inches(self):
        canvas = self.make_canvas(units='IN')
        self.assertTrue(hasattr(canvas, 'grid'))
        np.testing.assert_allclose(canvas.grid.grid_bounds, (0, 400 / 25.4, 0, 400 / 25.4))

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

    def test_invalid_grid_size_keeps_existing_grid(self):
        canvas = self.make_canvas()
        self.assertTrue(hasattr(canvas, 'set_grid_size'), 'The grid needs a live size setter')
        for value in (0, -10, float('inf'), float('nan'), 'invalid'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canvas.set_grid_size(value)
                np.testing.assert_allclose(canvas.get_grid_size(), (400, 400))
                np.testing.assert_allclose(canvas.grid.grid_bounds, (0, 400, 0, 400))

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

    def test_invalid_y_does_not_partially_resize_grid(self):
        canvas = self.make_canvas()
        for value in (0, -10, float('inf'), float('nan'), 'invalid'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canvas.set_grid_size(300, value)
                np.testing.assert_allclose(canvas.get_grid_size(), (400, 400))
                np.testing.assert_allclose(canvas.grid.grid_bounds, (0, 400, 0, 400))

    def test_default_cursor_color_opens(self):
        canvas = self.make_canvas(custom_cursor=False)
        self.assertTrue(hasattr(canvas, 'grid'))

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

    def test_zoom_in_stops_at_ten_millimetres(self):
        for units, limit in (('MM', 10), ('IN', 10 / 25.4)):
            with self.subTest(units=units):
                camera = self.make_canvas(units=units).view.camera
                camera.zoom(1e-6)
                self.assertAlmostEqual(camera.scale_factor, limit)
                camera.zoom(2)
                self.assertAlmostEqual(camera.scale_factor, limit * 2)

    def test_resize_refits_initial_view_and_preserves_user_zoom(self):
        canvas = self.make_canvas()
        camera = canvas.view.camera
        old_scale = camera.scale_factor
        canvas.view.size = (1000, 800)
        self.assertLess(camera.scale_factor, old_scale)
        self.assertEqual(camera.scale_factor, camera.maximum_scene_size)
        camera.zoom(0.5)
        center = camera.center
        canvas.view.size = (900, 700)
        self.assertAlmostEqual(camera.scale_factor / camera.maximum_scene_size, 0.5)
        np.testing.assert_allclose(camera.center, center)

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

    def test_rotation_keeps_the_mouse_down_grid_point_fixed(self):
        camera = self.make_canvas().view.camera
        camera.zoom(0.7, (100, 100, 0))
        for point in ((80, 110, 0, 1), (300, 280, 0, 1)):
            projected = camera._scene_transform.map(point)
            start = projected[:2] / projected[3]
            for delta in ((40, 20), (60, -30), (-20, 10)):
                camera.viewbox_mouse_event(self.mouse_event(
                    'mouse_move', start + delta, start, (1,)
                ))
                after = camera._scene_transform.map(point)
                np.testing.assert_allclose(after[:2] / after[3], start, atol=1e-3)
            camera.viewbox_mouse_event(self.mouse_event('mouse_release'))

    def test_zoom_is_bounded_without_moving_at_the_limit(self):
        camera = self.make_canvas().view.camera
        scale = camera.scale_factor
        center = camera.center
        camera.zoom(2, (0, 0, 0))
        self.assertEqual(camera.scale_factor, scale)
        np.testing.assert_allclose(camera.center, center)

    def test_wheel_and_shift_drag_respect_zoom_limits(self):
        from vispy.util import keys

        camera = self.make_canvas().view.camera
        camera.pan_button_setting = 3
        camera.viewbox_mouse_event(self.mouse_event(
            'mouse_move', (400, 100), (400, 300), (3,), modifiers=(keys.SHIFT,)
        ))
        self.assertLess(camera.scale_factor, camera.maximum_scene_size)
        self.assertEqual(camera.fov, 0)
        camera.viewbox_mouse_event(self.mouse_event('mouse_release'))
        camera.viewbox_mouse_event(self.mouse_event('mouse_wheel', delta=(0, 100)))
        self.assertEqual(camera.scale_factor, camera.minimum_scene_size)
        camera.viewbox_mouse_event(self.mouse_event('mouse_wheel', delta=(0, -100)))
        self.assertEqual(camera.scale_factor, camera.maximum_scene_size)
        camera.zoom(1e-9)
        self.assertEqual(camera.scale_factor, camera.minimum_scene_size)
        center = camera.center
        camera.zoom(0.5, (0, 0, 0))
        self.assertEqual(camera.scale_factor, camera.minimum_scene_size)
        np.testing.assert_allclose(camera.center, center)

    def test_configured_pan_button_and_rotation_keep_grid_fixed(self):
        canvas = self.make_canvas()
        camera = canvas.view.camera
        for button in (2, 3):
            camera.pan_button_setting = button
            center = camera.center
            camera.viewbox_mouse_event(self.mouse_event('mouse_move', (430, 320), (400, 300), (button,)))
            self.assertFalse(np.allclose(camera.center, center))
            camera.viewbox_mouse_event(self.mouse_event('mouse_release'))
        rotation = camera._get_rotation_tr().copy()
        camera.viewbox_mouse_event(self.mouse_event('mouse_move', (400, 300), (400, 300), (1,)))
        camera.viewbox_mouse_event(self.mouse_event('mouse_move', (440, 330), (400, 300), (1,)))
        self.assertFalse(np.allclose(camera._get_rotation_tr(), rotation))
        self.assertTrue(hasattr(canvas, 'grid'))
        np.testing.assert_allclose(canvas.grid.grid_bounds, (0, 400, 0, 400))


if __name__ == '__main__':
    unittest.main()
