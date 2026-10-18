"""Run: .venv/Scripts/python.exe tests/test_axis_label_spacing.py"""

import unittest
from unittest.mock import patch

import numpy as np

from test_plotcanvas3d import CanvasApp, PlotCanvas3d, QtCore, QtWidgets


class TestAxisLabelSpacing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_titles_have_a_small_clear_gap_at_different_font_sizes(self):
        # the first render of each canvas costs about 0.75 s: each unit and each font size is in 1 pair
        for units, font_size in (('MM', 8), ('IN', 16), ('MM', 32)):
            with self.subTest(units=units, font_size=font_size), \
                    patch.object(QtCore, 'QSettings') as settings:
                settings.return_value.contains.side_effect = lambda key: key == 'axis_font_size'
                settings.return_value.value.return_value = font_size
                fcapp = CanvasApp(units)
                canvas = PlotCanvas3d(QtWidgets.QVBoxLayout(fcapp.ui), fcapp)
                self.addCleanup(fcapp.ui.deleteLater)
                self.addCleanup(canvas.close)
                canvas.size = (800, 600)
                canvas.set_grid_size(300, 120)
                canvas.grid.visible = False
                canvas.workspace_line.visible = False
                canvas.xyz_axis.visible = False

                for axis in (canvas.xaxis, canvas.yaxis):
                    canvas.xaxis.visible = axis is canvas.xaxis
                    canvas.yaxis.visible = axis is canvas.yaxis
                    axis._line.visible = False
                    axis._ticks.visible = False
                    axis._text.color = 'blue'
                    axis._axis_label_vis.color = 'red'
                    image = canvas.render()
                    red = (image[:, :, 0] > 128) & (image[:, :, 1:3].max(axis=2) < 80)
                    blue = (image[:, :, 2] > 128) & (image[:, :, :2].max(axis=2) < 80)
                    self.assertTrue(red.any(), 'The axis title must be visible')
                    self.assertTrue(blue.any(), 'The numeric labels must be visible')
                    if axis is canvas.xaxis:
                        gap = np.nonzero(red)[0].min() - np.nonzero(blue)[0].max() - 1
                    else:
                        gap = np.nonzero(blue)[1].min() - np.nonzero(red)[1].max() - 1
                    gap /= canvas.pixel_scale
                    self.assertGreaterEqual(gap, 2)
                    self.assertLessEqual(gap, font_size * canvas.dpi / 72 * 0.75 + 8)


if __name__ == '__main__':
    unittest.main()
