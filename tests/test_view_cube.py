"""Run: .venv/Scripts/python.exe tests/test_view_cube.py"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets, QtTest

import test_plotcanvas3d as canvas_tests
from appGUI import VisPyCanvas as plot_module


class TestViewCube(unittest.TestCase):
    make_canvas = canvas_tests.TestPlotCanvas3d.make_canvas

    normals = {
        'top': (0, 0, 1), 'bottom': (0, 0, -1),
        'left': (-1, 0, 0), 'right': (1, 0, 0),
        'front': (0, -1, 0), 'back': (0, 1, 0),
    }

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def assert_view(self, camera, name):
        points = camera.transform.map([(0, 0, 0, 1), (0, 0, 1, 1)])
        normal = points[1, :3] / points[1, 3] - points[0, :3] / points[0, 3]
        normal /= np.linalg.norm(normal)
        np.testing.assert_allclose(normal, self.normals[name], atol=1e-6)

    def test_six_views_keep_pan_and_zoom(self):
        camera = self.make_canvas().view.camera
        self.assertTrue(hasattr(camera, 'set_view'), 'Camera needs six named views')
        camera.zoom(0.5, (70, 90, 0))
        center, scale = camera.center, camera.scale_factor
        for name in self.normals:
            with self.subTest(view=name):
                camera.set_view(name)
                self.assert_view(camera, name)
                np.testing.assert_allclose(camera.center, center)
                self.assertEqual(camera.scale_factor, scale)

    def test_face_click_selects_the_visible_face(self):
        canvas = self.make_canvas()
        self.assertTrue(hasattr(canvas, 'view_cube'), 'Canvas needs a navigation cube')
        camera, cube = canvas.view.camera, canvas.view_cube
        camera.viewbox_mouse_event(canvas_tests.TestPlotCanvas3d.mouse_event(
            'mouse_move', (460, 340), (400, 300), (1,)
        ))
        camera.viewbox_mouse_event(canvas_tests.TestPlotCanvas3d.mouse_event('mouse_release'))
        state = camera.get_state()
        faces = cube._project_faces()
        self.assertGreaterEqual(len(faces), 2)
        for name, polygon in faces:
            with self.subTest(view=name):
                camera.set_state(state)
                point = sum((polygon[i] for i in range(polygon.size())), QtCore.QPointF()) / polygon.size()
                QtTest.QTest.mouseClick(cube, QtCore.Qt.MouseButton.LeftButton, pos=point.toPoint())
                self.assert_view(camera, name)
                self.assertEqual(camera.scale_factor, state['scale_factor'])
                np.testing.assert_allclose(camera.center, state['center'])

    def test_cube_drag_rotates_both_views_about_the_resized_grid_center(self):
        for units in ('MM', 'IN'):
            with self.subTest(units=units):
                canvas = self.make_canvas(units=units)
                camera, cube = canvas.view.camera, canvas.view_cube
                canvas.set_grid_size(300, 150)
                camera.set_view('iso')
                camera.zoom(0.6, (0, 0, 0))
                center = (*np.asarray(canvas.workspace_size) / 2, 0)
                projected = camera._scene_transform.map(center)
                screen = projected[:2] / projected[3]
                scale = camera.scale_factor
                image = cube.grab().toImage()
                rotation = camera._get_rotation_tr().copy()
                polygon = cube._project_faces()[0][1]
                start = (sum((polygon[i] for i in range(polygon.size())), QtCore.QPointF()) /
                         polygon.size()).toPoint()
                QtTest.QTest.mousePress(cube, QtCore.Qt.MouseButton.LeftButton, pos=start)
                # Pressing must not snap to a face before the drag begins.
                np.testing.assert_allclose(camera._get_rotation_tr(), rotation)
                for end in (start + QtCore.QPoint(25, 15), QtCore.QPoint(cube.width() + 20, -10),
                            cube.rect().center()):
                    event = QtGui.QMouseEvent(
                        QtCore.QEvent.Type.MouseMove, QtCore.QPointF(end),
                        QtCore.QPointF(cube.mapToGlobal(end)), QtCore.Qt.MouseButton.NoButton,
                        QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier
                    )
                    with patch.object(cube, 'update', wraps=cube.update) as update:
                        QtWidgets.QApplication.sendEvent(cube, event)
                        update.assert_called()
                    self.assertFalse(np.allclose(camera._get_rotation_tr(), rotation))
                    projected = camera._scene_transform.map(center)
                    np.testing.assert_allclose(projected[:2] / projected[3], screen, atol=1e-5)
                    self.assertEqual(camera.scale_factor, scale)
                rotation = camera._get_rotation_tr().copy()
                self.assertIsNotNone(cube._face_at(QtCore.QPointF(end)))
                QtTest.QTest.mouseRelease(cube, QtCore.Qt.MouseButton.LeftButton, pos=end)
                np.testing.assert_allclose(camera._get_rotation_tr(), rotation)
                self.assertNotEqual(cube.grab().toImage(), image)
                # A subsequent canvas drag must still use its own mouse-down point.
                anchor = (*np.asarray(canvas.workspace_size) * (0.2, 0.7), 0)
                projected = camera._scene_transform.map(anchor)
                start = projected[:2] / projected[3]
                camera.viewbox_mouse_event(canvas_tests.TestPlotCanvas3d.mouse_event(
                    'mouse_move', start + (30, 20), start, (1,)
                ))
                projected = camera._scene_transform.map(anchor)
                np.testing.assert_allclose(projected[:2] / projected[3], start, atol=1e-5)
                camera.viewbox_mouse_event(canvas_tests.TestPlotCanvas3d.mouse_event('mouse_release'))

    def test_iso_action_has_equal_axis_projection_and_keeps_pan_zoom(self):
        canvas = self.make_canvas()
        actions = {action.data(): action for action in canvas.view_cube.menu.actions()}
        self.assertIn('iso', actions)
        camera = canvas.view.camera
        camera.zoom(0.5, (70, 90, 0))
        center, scale = camera.center, camera.scale_factor
        actions['iso'].trigger()
        points = camera.transform.map([(0, 0, 0, 1), (0, 0, 1, 1)])
        normal = points[1, :3] / points[1, 3] - points[0, :3] / points[0, 3]
        normal /= np.linalg.norm(normal)
        np.testing.assert_allclose(normal, np.array((1, -1, 1)) / np.sqrt(3), atol=1e-6)
        points = camera._scene_transform.map(np.vstack((np.zeros(3), np.eye(3))))
        screen = points[:, :2] / points[:, 3:]
        lengths = np.linalg.norm(screen[1:] - screen[0], axis=1)
        np.testing.assert_allclose(lengths, lengths[0], rtol=1e-5)
        np.testing.assert_allclose(camera.center, center)
        self.assertEqual(camera.scale_factor, scale)

    def test_fit_action_includes_transformed_content_and_keeps_orientation(self):
        from vispy import scene

        canvas = self.make_canvas()
        actions = {action.data(): action for action in canvas.view_cube.menu.actions()}
        self.assertIn('fit', actions)
        line = scene.Line(pos=np.array([(-100, 50, -30), (700, 650, 200)]), parent=canvas.view.scene)
        line.transform = scene.STTransform(translate=(80, 20, 10))
        camera = canvas.view.camera
        actions['iso'].trigger()
        camera.zoom(0.2, (1000, -300, 0))
        rotation = camera._get_rotation_tr().copy()
        actions['fit'].trigger()
        np.testing.assert_allclose(camera._get_rotation_tr(), rotation)
        points = np.array([
            (0, 0, 0), (400, 0, 0), (0, 400, 0), (400, 400, 0), (0, 0, 40),
            (-20, 70, -20), (780, 670, 210),
        ])
        projected = camera._scene_transform.map(points)
        screen = projected[:, :2] / projected[:, 3:]
        self.assertGreaterEqual(screen[:, 0].min(), canvas.axis_padding - 1e-3)
        self.assertGreaterEqual(screen[:, 1].min(), 20 - 1e-3)
        self.assertLessEqual(screen[:, 0].max(), 800 - 20 + 1e-3)
        self.assertLessEqual(screen[:, 1].max(), 600 - canvas.axis_padding + 1e-3)
        self.assertEqual(camera.scale_factor, camera.maximum_scene_size)

if __name__ == '__main__':
    unittest.main()
