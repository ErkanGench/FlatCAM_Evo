"""Run: .venv/Scripts/python.exe tests/test_jump_to.py"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

if sys.platform != 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from vispy import app
from vispy.geometry import Rect

app.use_app('pyqt6')

from appGUI.VisPyCanvas import VisPyCanvas
from appGUI.PlotCanvas import PlotCanvas
from appHandlers.appObjectOps import AppObjectOps


class TestJumpTo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_handler(self):
        canvas = VisPyCanvas()
        self.addCleanup(canvas.close)
        canvas.size = (800, 600)
        canvas.unfreeze()
        canvas.shape_collection = Mock()
        canvas.fit_center = PlotCanvas.fit_center.__get__(canvas)
        canvas.on_update_text_hud = Mock()
        ui = QtWidgets.QWidget()
        self.addCleanup(ui.deleteLater)
        setattr(ui, 'update_location_labels', Mock())
        fcapp = SimpleNamespace(
            log=Mock(), inform=Mock(), defaults=Mock(), options={}, ui=ui,
            plotcanvas=canvas, clipboard=SimpleNamespace(text=lambda: ''), resource_location='',
            mouse_pos=[12.3456789, -8.7654321], rel_point1=(1, 2),
            jump_signal=Mock(), locate_signal=Mock(), grid_status=lambda: False,
        )
        return fcapp, AppObjectOps(fcapp)

    def test_jump_updates_exact_position_before_notifying_tools(self):
        fcapp, handler = self.make_handler()
        target = (17.123456789, -3.987654321)
        positions = []
        fcapp.jump_signal.emit.side_effect = lambda loc: positions.append(tuple(fcapp.mouse_pos))
        with patch.object(QtGui.QCursor, 'setPos') as set_pos:
            self.assertEqual(handler.on_jump_to(custom_location=target), target)
        self.assertEqual(positions, [target])
        self.assertEqual(tuple(fcapp.mouse_pos), target)
        screen = fcapp.plotcanvas.translate_coords_2(target)
        expected = fcapp.plotcanvas.native.mapToGlobal(QtCore.QPoint(round(screen[0]), round(screen[1])))
        set_pos.assert_called_once_with(expected.x(), expected.y())

    def test_relative_reference_is_captured_before_dialog(self):
        fcapp, handler = self.make_handler()
        start = tuple(fcapp.mouse_pos)

        def dialog(**kwargs):
            # Moving to the dialog must not move the relative reference.
            fcapp.mouse_pos[:] = [90, 80]
            return SimpleNamespace(ok=True, location='0.125, -0.25', reference='rel')

        with patch('appGUI.GUIElements.DialogBoxRadio', side_effect=dialog), \
                patch.object(QtGui.QCursor, 'setPos'):
            target = handler.on_jump_to()
        self.assertEqual(target, (start[0] + 0.125, start[1] - 0.25))

    def test_locate_updates_position_for_the_next_relative_jump(self):
        fcapp, handler = self.make_handler()
        obj = SimpleNamespace(bounds=lambda: (1.125, 2.25, 8, 9))
        dialog = SimpleNamespace(ok=True, location_point='bl')
        with patch('appGUI.GUIElements.DialogBoxChoice', return_value=dialog), \
                patch.object(QtGui.QCursor, 'setPos'):
            target = handler.on_locate(obj, fit_center=False)
        self.assertEqual(tuple(fcapp.mouse_pos), target)

    def test_canvas_pixel_roundtrip_after_pan_zoom_and_resize(self):
        fcapp, _ = self.make_handler()
        canvas = fcapp.plotcanvas
        for size, rect, target in (
                ((800, 600), (-20, -20, 40, 40), (3.123456, -8.765432)),
                ((1200, 400), (120, -80, 0.4, 0.4), (120.123456, -79.765432)),
                ((400, 900), (-900, 200, 600, 600), (-743.23456, 359.12345))):
            with self.subTest(size=size, rect=rect):
                canvas.size = size
                canvas.view.camera.rect = Rect(*rect)
                screen = canvas.translate_coords_2(target)
                np.testing.assert_allclose(canvas.translate_coords(screen[:2])[:2], target, atol=1e-8)
                # The OS cursor has integer logical pixels: half a pixel is the unavoidable limit.
                pixel = np.round(screen[:2])
                np.testing.assert_array_less(np.abs(screen[:2] - pixel), 0.500001)
                np.testing.assert_allclose(canvas.translate_coords_2(canvas.translate_coords(pixel)[:2])[:2],
                                           pixel, atol=1e-5)

if __name__ == '__main__':
    unittest.main()
