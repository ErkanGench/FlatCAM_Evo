"""Run: .venv/Scripts/python.exe tests/test_coordinate_toolbars.py"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtCore, QtGui, QtWidgets
from appGUI.MainGUI import MainGUI
from appGUI.GUIElements import AppInfoBar, FCCheckBox, FCEntry, FCEntry2, FCLabel, FlatCAMActivityView


class ToolbarWindow(QtWidgets.QMainWindow):
    build_infobar_context_menu = MainGUI.build_infobar_context_menu
    toggle_coords = MainGUI.toggle_coords
    toggle_delta_coords = MainGUI.toggle_delta_coords
    toggle_gridbar = MainGUI.toggle_gridbar
    toggle_statusbar = MainGUI.toggle_statusbar

    def __init__(self):
        super().__init__()
        self.app = SimpleNamespace(options={
            'global_coords_bar_show': True, 'global_delta_coords_bar_show': True,
            'global_grid_bar_show': True, 'global_statusbar_show': True,
        })
        self.infobar = self.statusBar()
        for name in ('coords_toolbar', 'delta_coords_toolbar', 'grid_toolbar', 'status_toolbar'):
            toolbar = QtWidgets.QToolBar(name)
            toolbar.addWidget(QtWidgets.QLabel('coordinates'))
            setattr(self, name, toolbar)
            self.infobar.addWidget(toolbar)
        self.plot_tab_area = QtWidgets.QTabWidget()
        self.plot_tab = QtWidgets.QWidget()
        self.plot_tab_area.addTab(self.plot_tab, 'Plot Area')
        self.plot_tab_area.addTab(QtWidgets.QWidget(), 'Preferences')
        self.setCentralWidget(self.plot_tab_area)
        self.build_infobar_context_menu()


class TestCoordinateToolbars(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_window(self):
        window = ToolbarWindow()
        self.addCleanup(window.close)
        window.show()
        self.qapp.processEvents()
        return window

    def test_plot_tab_restores_preferences_without_requiring_a_toggle(self):
        window = self.make_window()
        self.assertTrue(hasattr(MainGUI, 'on_plot_area_tab_changed'))
        window.plot_tab_area.currentChanged.connect(lambda index: MainGUI.on_plot_area_tab_changed(window))
        window.plot_tab_area.setCurrentIndex(1)
        self.assertFalse(window.coords_toolbar.isVisible())
        self.assertFalse(window.delta_coords_toolbar.isVisible())
        window.plot_tab_area.setCurrentIndex(0)
        self.assertTrue(window.coords_toolbar.isVisible())
        self.assertTrue(window.delta_coords_toolbar.isVisible())
        window.toggle_delta_coords(False)
        window.plot_tab_area.setCurrentIndex(1)
        window.plot_tab_area.setCurrentIndex(0)
        self.assertTrue(window.coords_toolbar.isVisible())
        self.assertFalse(window.delta_coords_toolbar.isVisible())

    def test_startup_restoration_and_non_plot_tabs_keep_saved_preferences(self):
        window = self.make_window()
        window.coords_toolbar.hide()
        window.delta_coords_toolbar.hide()
        MainGUI.on_plot_area_tab_changed(window)
        self.assertTrue(window.coords_toolbar.isVisible())
        self.assertTrue(window.delta_coords_toolbar.isVisible())
        window.plot_tab_area.setCurrentIndex(1)
        window.toggle_coords(True)
        window.toggle_delta_coords(True)
        self.assertFalse(window.coords_toolbar.isVisible())
        self.assertFalse(window.delta_coords_toolbar.isVisible())
        self.assertTrue(window.app.options['global_coords_bar_show'])
        self.assertTrue(window.app.options['global_delta_coords_bar_show'])

if __name__ == '__main__':
    unittest.main()
