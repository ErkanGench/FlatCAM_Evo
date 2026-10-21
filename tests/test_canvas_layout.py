"""Run: .venv/Scripts/python.exe tests/test_canvas_layout.py"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if sys.platform != 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6 import QtWidgets
from vispy import app

app.use_app('pyqt6')

from vispy.app.backends._pyqt6 import CanvasBackendDesktop
from vispy.scene.widgets import Grid
from vispy.visuals.axis import Ticker

from appGUI.VisPyCanvas import VisPyCanvas
from appGUI.VisPyPatches import apply_patches

PATCH_ABSENT = object()


class TestCanvasLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        # apply_patches() changes VisPy classes for the whole process; keep the originals so that the later tests
        # (the 3D view cube needs the Grid layout update on draw) see VisPy as it was
        cls.patched = [(owner, name, vars(owner).get(name, PATCH_ABSENT)) for owner, name in (
            (Grid, '_prepare_draw'), (Grid, '_update_clipper'), (Ticker, '_get_tick_frac_labels'),
            (CanvasBackendDesktop, 'keyPressEvent'), (CanvasBackendDesktop, 'keyReleaseEvent'))]
        apply_patches()

    @classmethod
    def tearDownClass(cls):
        for owner, name, original in cls.patched:
            if original is PATCH_ABSENT:
                delattr(owner, name)
            else:
                setattr(owner, name, original)

    def test_axis_spacing_follows_font_and_stays_fixed_on_resize(self):
        for font_size in (6, 9, 18):
            with self.subTest(font_size=font_size):
                settings = SimpleNamespace(
                    contains=lambda key: key == 'axis_font_size',
                    value=lambda *args, **kwargs: font_size,
                )
                with patch('appGUI.VisPyCanvas.QSettings', return_value=settings):
                    canvas = VisPyCanvas()
                self.addCleanup(canvas.close)
                for size in ((800, 600), (1200, 750)):
                    canvas.size = size
                    self.qapp.processEvents()
                    canvas.central_widget.size = size
                    canvas.grid_widget._update_child_widget_dim()
                    image = canvas.render()
                    view_right = canvas.view.pos[0] + canvas.view.size[0]
                    self.assertAlmostEqual(canvas.central_widget.size[0] - view_right, 8)
                    axis = canvas.xaxis.axis
                    self.assertEqual(axis._text.rotation, 0)
                    self.assertEqual(axis._text.anchors, ['center', 'bottom'])
                    # Measure the rendered labels, not the formula used to size the row.
                    scale = image.shape[0] / canvas.central_widget.size[1]
                    start = int((canvas.xaxis.pos[1] + axis.major_tick_length + 1) * scale)
                    left = int((canvas.xaxis.pos[0] + 20) * scale)
                    right = int((canvas.central_widget.size[0] - 20) * scale)
                    background = image[-1, image.shape[1] // 2, :3].astype(int)
                    pixels = image[start:, left:right, :3].astype(int)
                    rows = np.flatnonzero(np.max(np.abs(pixels - background), axis=(1, 2)) > 30)
                    self.assertTrue(len(rows), 'The horizontal labels must be visible')
                    gap = (image.shape[0] - 1 - (start + rows[-1])) / scale
                    self.assertGreaterEqual(gap, 2)
                    self.assertLessEqual(gap, 6)


if __name__ == '__main__':
    unittest.main()
