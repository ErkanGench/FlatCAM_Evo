"""Run: .venv/Scripts/python.exe tests/test_hud_layout.py"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform != 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt6 import QtWidgets
from vispy import app

app.use_app('pyqt6')

from defaults import AppDefaults
from appGUI.PlotCanvas import PlotCanvas
from appGUI.PlotCanvasLegacy import PlotCanvasLegacy


class TestHudLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_canvas(self, dark, font_size):
        options = dict(AppDefaults.factory_defaults)
        options.update(global_hud=False, global_axis=False, global_workspace=False)
        ui = QtWidgets.QWidget()
        ui.hud_label = QtWidgets.QLabel(ui)
        self.addCleanup(ui.deleteLater)
        fcapp = SimpleNamespace(
            options=options, defaults=options, app_units='MM', decimals=4,
            dec_format=lambda value, decimals: round(value, decimals), pool=None,
            pool_recreated=Mock(), cursor_color_3D='#000000',
            ui=ui,
        )
        settings = Mock()
        values = {'theme': 'dark' if dark else 'light', 'dark_canvas': dark, 'hud_font_size': font_size}
        settings.contains.side_effect = lambda key: key in values
        settings.value.side_effect = lambda key, **kwargs: values[key]
        with patch('appGUI.PlotCanvas.QtCore.QSettings', return_value=settings), \
                patch('appGUI.VisPyCanvas.QSettings', return_value=settings):
            canvas = PlotCanvas(fcapp)
            canvas.on_update_text_hud(dx=-1234.5678, dy=0.1, x=123456.789, y=-9)
        self.addCleanup(canvas.close)
        canvas.size = (800, 600)
        canvas.grid.visible = False
        canvas.xaxis.visible = False
        canvas.yaxis.visible = False
        canvas.view.border_color = None
        canvas.on_toggle_hud(state=True, silent=True)
        return canvas

    def test_hud_text_is_visible_and_fits_its_background(self):
        for dark in (False, True):
            for font_size in (8, 16, 24):
                with self.subTest(dark=dark, font_size=font_size):
                    canvas = self.make_canvas(dark, font_size)
                    image = canvas.render()
                    scale = canvas.pixel_scale
                    origin = canvas.view.node_transform(canvas.scene).map((0, 0))[:2]
                    x0, y0 = np.round((origin + 1) * scale).astype(int)
                    x1, y1 = np.round((origin + canvas.view.size - 1) * scale).astype(int)
                    image = image[y0:y1, x0:x1]
                    if dark:
                        text = image[:, :, :3].min(axis=2) > 180
                    else:
                        text = image[:, :, :3].max(axis=2) < 60
                    rows, columns = np.nonzero(text)
                    self.assertGreater(len(rows), 10, 'HUD text must be visible')
                    rows = rows + scale
                    columns = columns + scale
                    left = canvas.rect_hud.center[0] - canvas.rect_hud.width / 2
                    top = canvas.rect_hud.center[1] - canvas.rect_hud.height / 2
                    self.assertGreaterEqual(columns.min() / scale - left, 3)
                    self.assertGreaterEqual(rows.min() / scale - top, 3)
                    self.assertLessEqual((columns.max() + 1) / scale, left + canvas.rect_hud.width - 3)
                    self.assertLessEqual((rows.max() + 1) / scale, top + canvas.rect_hud.height - 3)
                    # A small padding, rather than heuristic spare rows around the content.
                    self.assertLessEqual(canvas.rect_hud.height - (rows.max() - rows.min() + 1) / scale, 24)

    def test_hud_foreground_contrasts_with_the_actual_canvas_background(self):
        canvas = self.make_canvas(True, 8)
        canvas.view.bgcolor = 'white'
        canvas.on_update_text_hud(x=12)
        self.assertLess(canvas.text_hud.color.rgb.max(), 0.5)
        canvas.view.bgcolor = '#202124'
        canvas.on_update_text_hud(x=12)
        self.assertGreater(canvas.text_hud.color.rgb.min(), 0.5)

    def test_coordinate_columns_are_aligned(self):
        canvas = self.make_canvas(True, 8)
        lines = canvas.text_hud.text
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(line.index('[') == lines[0].index('[') for line in lines))

    def test_hud_glyphs_survive_objects_drawn_before_first_use(self):
        from shapely.geometry import box

        reference = self.make_canvas(True, 16)
        reference.on_update_text_hud(dx=-44.0, dy=48.0, x=-44.0, y=48.0)
        reference.render()
        shapes = reference.new_shape_collection()
        shapes.add(shape=box(-1000, -1000, 1000, 1000), color='red', face_color='red', update=True)
        expected = reference.render()[:, :, :3].min(axis=2) > 180
        self.assertGreater(expected.sum(), 100)

        for hud_initially_visible in (False, True):
            with self.subTest(hud_initially_visible=hud_initially_visible):
                canvas = self.make_canvas(True, 16)
                canvas.on_update_text_hud(dx=-44.0, dy=40.0, x=-44.0, y=40.0)
                canvas.on_toggle_hud(state=hud_initially_visible, silent=True)
                canvas.render()
                shapes = canvas.new_shape_collection()
                shapes.add(shape=box(-1000, -1000, 1000, 1000), color='red', face_color='red', update=True)
                canvas.render()
                canvas.on_update_text_hud(dx=-44.0, dy=48.0, x=-44.0, y=48.0)
                canvas.on_toggle_hud(state=True, silent=True)
                self.assertIn('48.0', canvas.text_hud.text[1])
                for frame in range(2):
                    actual = canvas.render()[:, :, :3].min(axis=2) > 180
                    np.testing.assert_array_equal(actual, expected,
                                                  err_msg='Object rendering must not erase HUD glyphs')

    def test_legacy_hud_uses_the_configured_point_size_and_aligned_columns(self):
        canvas = self.make_canvas(True, 8)
        plot = SimpleNamespace(app=canvas.fcapp, rect_hud_color='#80808040', text_hud_color='white')
        settings = Mock()
        settings.contains.return_value = True
        settings.value.return_value = 8
        with patch('appGUI.PlotCanvasLegacy.QtCore.QSettings', return_value=settings):
            hud = PlotCanvasLegacy.Thud(plot)
        self.assertEqual(hud.hud_holder.txt._text.get_fontsize(), 8)
        hud.on_update_text_hud(dx=-123.4, x=123456)
        lines = hud.text.splitlines()
        lines = [line for line in lines if line]
        self.assertTrue(all(line.index('[') == lines[0].index('[') for line in lines))


if __name__ == '__main__':
    unittest.main()
