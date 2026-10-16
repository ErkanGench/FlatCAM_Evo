"""Run: .venv/Scripts/python.exe tests/test_theme_blue.py"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtGui, QtWidgets
from appGUI.GUIElements import AppInfoBar, FCLabel
from appGUI.MainGUI import MainGUI, ShortcutsTab


class TestThemeBlue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.theme = 'dark'
        ui = SimpleNamespace(app=None, theme_safe_colors=MainGUI.theme_safe_colors)
        mapper = MainGUI.theme_safe_color.__get__(ui)
        color_patch = patch.object(FCLabel, 'patching_text_color', mapper)
        color_patch.start()
        self.addCleanup(color_patch.stop)
        theme_patch = patch('appGUI.MainGUI._database_option', side_effect=lambda *args: self.theme)
        theme_patch.start()
        self.addCleanup(theme_patch.stop)

    def assert_text_color(self, text, word, expected):
        document = QtGui.QTextDocument()
        document.setHtml(text)
        cursor = document.find(word)
        self.assertFalse(cursor.isNull())
        self.assertEqual(cursor.charFormat().foreground().color().name(), expected)

    def test_status_bar_selection_message(self):
        bar = AppInfoBar(app=SimpleNamespace(resource_location='assets/resources'))
        self.addCleanup(bar.close)
        bar.set_status('<span style="color:blue;">CNCJob</span> selected', level='selected')
        self.assert_text_color(bar.text.text(), 'CNCJob', '#66b3ff')

    def test_inline_blue_forms_and_updates(self):
        label = FCLabel()
        for color in ('blue', 'BLUE', '#0000FF', '#0000ff', '#00f'):
            for text in ('<font color="%s">Tool</font>', '<span style="color:%s;">Tool</span>'):
                with self.subTest(color=color, text=text):
                    label.setText(text % color)
                    self.assert_text_color(label.text(), 'Tool', '#66b3ff')
        label = FCLabel('Parameters', color='blue')
        self.assert_text_color(label.text(), 'Parameters', '#66b3ff')
        label.color = '#0000ff'
        self.assert_text_color(label.text(), 'Parameters', '#66b3ff')

    def test_light_theme_preserves_original_colors(self):
        for theme in ('light', 'default'):
            self.theme = theme
            text = '<font color="#0000FF">Tool</font>'
            self.assertEqual(FCLabel(text).text(), text)

    def test_plain_text_backgrounds_and_other_colors_are_preserved(self):
        for text in ('blue #0000ff color: blue', '<span style="background-color:blue; color:red;">blue</span>',
                     '<font color="#0000ffff">Tool</font>'):
            self.assertEqual(FCLabel(text).text(), text)

    def test_shortcut_heading_uses_readable_blue(self):
        original = self.qapp.palette()
        self.addCleanup(self.qapp.setPalette, original)
        for background, expected in (('#202124', '#66b3ff'), ('#ffffff', '#0000ff')):
            palette = QtGui.QPalette(original)
            palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(background))
            self.qapp.setPalette(palette)
            tab = ShortcutsTab()
            self.addCleanup(tab.close)
            self.assert_text_color(tab.sh_editor.toHtml(), 'GEOMETRY EDITOR', expected)


if __name__ == '__main__':
    unittest.main()
