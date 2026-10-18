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

    def test_context_menu_toggles_grid(self):
        canvas = self.make_canvas()
        self.assertTrue(hasattr(canvas, 'context_menu'), 'The 3D canvas needs a context menu')
        action = canvas.context_menu.actions()[0]
        self.assertEqual(action.text(), _('Toggle Grid'))
        for visible in (False, True):
            action.trigger()
            self.assertEqual(canvas.grid.visible, visible)
            self.assertEqual(canvas.grid_lines_enabled, visible)

    def test_context_menu_fits_sender_view(self):
        canvas = self.make_canvas()
        fit = Mock()
        canvas.fcapp.grbl_sender_tool = SimpleNamespace(on_fit_view=fit, view3d=SimpleNamespace(canvas=canvas))
        actions = canvas.context_menu.actions()
        self.assertEqual([action.text() for action in actions], [_('Toggle Grid'), _('Fit View')])
        actions[1].trigger()
        fit.assert_called_once_with()

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

    def test_sender_context_fit_keeps_full_scene_zoom_out_limit(self):
        from appPlugins.ToolGrblSender.Sender import ToolGrblSender
        from appPlugins.ToolGrblSender.SenderView3d import SenderView3d

        canvas = self.make_canvas()
        view = SenderView3d(canvas)
        sender = SimpleNamespace(view3d=view)
        sender.on_fit_view = lambda: ToolGrblSender.on_fit_view(sender)
        canvas.fcapp.grbl_sender_tool = sender
        camera = canvas.view.camera
        for start, end in (((180, 180, -1), (220, 220, -1)), ((0, 0, 0), (600, 500, 80))):
            with self.subTest(start=start, end=end):
                view.set_toolpath([(0, start, end, False)])
                camera.set_view('iso')
                canvas.fit_view()
                scene_limit = camera.maximum_scene_size
                canvas.context_menu.actions()[1].trigger()
                fitted_scale = camera.scale_factor
                self.assertAlmostEqual(camera.maximum_scene_size, max(scene_limit, fitted_scale))
                camera.zoom(1e6)
                self.assertAlmostEqual(camera.scale_factor, max(scene_limit, fitted_scale))
                if fitted_scale < scene_limit:
                    self.assertGreater(camera.scale_factor, fitted_scale)

    def test_context_menu_custom_actions_and_replacement(self):
        canvas = self.make_canvas()
        self.assertTrue(hasattr(canvas, 'add_context_menu_action'), 'The menu needs an action helper')
        callback = Mock()
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtGui.QColor('red'))
        icon = QtGui.QIcon(pixmap)
        for supplied_icon in (None, icon):
            action = canvas.add_context_menu_action('Custom', callback, icon=supplied_icon)
            self.assertIn(action, canvas.context_menu.actions())
            self.assertEqual(action.icon().isNull(), supplied_icon is None)
            if supplied_icon is not None:
                self.assertEqual(action.icon().cacheKey(), icon.cacheKey())
            action.trigger()
        self.assertEqual(callback.call_count, 2)
        replacement = QtWidgets.QMenu(canvas.native)
        canvas.set_context_menu(replacement)
        action = canvas.add_context_menu_action('Replacement', callback)
        self.assertEqual(replacement.actions(), [action])
        with patch.object(replacement, 'popup') as popup:
            canvas.show_context_menu(QtCore.QPoint(20, 30))
            popup.assert_called_once_with(canvas.native.mapToGlobal(QtCore.QPoint(20, 30)))

    def test_context_menu_factory_can_be_overridden(self):
        menu = QtWidgets.QMenu()
        self.addCleanup(menu.deleteLater)
        with patch.object(PlotCanvas3d, 'create_context_menu', return_value=menu) as create:
            canvas = self.make_canvas()
        create.assert_called_once_with()
        self.assertIs(canvas.context_menu, menu)

    def test_context_menu_opens_only_on_right_click(self):
        from vispy.app import MouseEvent

        canvas = self.make_canvas()
        with patch.object(canvas.context_menu, 'popup') as popup:
            for button, dragging in ((1, False), (2, True), (2, False)):
                press = MouseEvent('mouse_press', pos=(40, 50), button=button)
                previous = MouseEvent('mouse_move', pos=(80, 90), press_event=press) if dragging else None
                canvas.events.mouse_release(
                    pos=(40, 50), button=button, press_event=press, last_event=previous
                )
                if button == 2 and not dragging:
                    popup.assert_called_once_with(canvas.native.mapToGlobal(QtCore.QPoint(40, 50)))
                else:
                    popup.assert_not_called()

    def test_fit_view_with_empty_sender_lines(self):
        from appPlugins.ToolGrblSender.SenderView3d import SenderView3d

        canvas = self.make_canvas()
        workspace_corners = canvas._scene_corners()
        sender = SenderView3d(canvas)
        sender.set_toolpath([(0, (-100, 0, 0), (600, 500, 80), False)])
        canvas.fit_view()
        corners = canvas._scene_corners()
        np.testing.assert_allclose(corners.min(axis=0), (-100, 0, 0))
        np.testing.assert_allclose(corners.max(axis=0), (600, 500, 80))
        self.assertTrue(np.isfinite(canvas.view.camera.center).all())

        sender.set_accepted(0)
        canvas.fit_view()
        sender.set_toolpath([])
        canvas.fit_view()
        corners = canvas._scene_corners()
        np.testing.assert_allclose(corners, workspace_corners)

    def test_grid_does_not_occlude_sender_cutting_moves(self):
        from appPlugins.ToolGrblSender.SenderView3d import SenderView3d

        canvas = self.make_canvas()
        sender = SenderView3d(canvas)
        points = [(120, 120, -1), (280, 120, -1), (280, 280, -1), (120, 280, -1), (120, 120, -1)]
        sender.set_toolpath([(i, a, b, False) for i, (a, b) in enumerate(zip(points, points[1:]))])
        for view in ('top', 'bottom', 'iso'):
            with self.subTest(view=view):
                canvas.view.camera.set_view(view)
                canvas.fit_view()
                counts = []
                for visible in (False, True):
                    canvas.grid.visible = visible
                    image = canvas.render()[:, :, :3].astype(float)
                    blue = (image[:, :, 2] > 1.5 * image[:, :, 0]) & \
                           (image[:, :, 2] > 1.3 * image[:, :, 1])
                    counts.append(np.count_nonzero(blue))
                self.assertGreater(counts[0], 100)
                self.assertGreaterEqual(counts[1], 0.9 * counts[0],
                                        'The grid must not hide the negative-Z toolpath')

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

    def test_zoom_in_stops_at_one_third_of_ten_millimetres(self):
        for units, limit in (('MM', 10 / 3), ('IN', 10 / 25.4 / 3)):
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
