"""Run: .venv/Scripts/python.exe tests/test_canvas_dpi.py"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

if sys.platform != 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtWidgets
from vispy import app

app.use_app('pyqt6')

from appGUI.VisPyCanvas import VisPyCanvas
from appGUI.PlotCanvas3d import PlotCanvas3d
from appGUI.VisPyVisuals import TextCollection


class TestCanvasDpi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_grid_and_annotations_use_logical_dpi_in_both_views(self):
        with patch('vispy.app.canvas.get_dpi', return_value=240), \
                patch.object(QtWidgets.QWidget, 'logicalDpiY', return_value=96):
            for mode in ('area', '3d'):
                with self.subTest(mode=mode):
                    if mode == 'area':
                        canvas = VisPyCanvas()
                        grid_text = canvas.xaxis.axis._text
                    else:
                        ui = QtWidgets.QWidget()
                        self.addCleanup(ui.deleteLater)
                        fcapp = SimpleNamespace(
                            ui=ui, pool=None, app_units='MM', pool_recreated=Mock(),
                            options={'global_cursor_color_enabled': False},
                        )
                        canvas = PlotCanvas3d(QtWidgets.QVBoxLayout(ui), fcapp)
                        grid_text = canvas.xaxis._text
                    self.addCleanup(canvas.close)
                    self.assertEqual(canvas.dpi, 96)

                    grid_text.font_size = 8
                    annotation = TextCollection(parent=canvas.view.scene)
                    annotation.add(['1'], [(50, 50)], font_size=8)
                    canvas.render()

                    for visual in (grid_text, annotation):
                        self.assertEqual(visual.transforms.dpi, 96)
                        self.assertAlmostEqual(visual.shared_program['u_npix'], 8 * 96 / 72)


if __name__ == '__main__':
    unittest.main()
