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

    def test_context_action_tracks_actual_toolbar_visibility(self):
        window = self.make_window()
        for toolbar in (window.coords_toolbar, window.delta_coords_toolbar):
            self.assertIn(toolbar.toggleViewAction(), window.infobar.actions())
            toolbar.hide()
            self.assertFalse(toolbar.toggleViewAction().isChecked())
            toolbar.toggleViewAction().trigger()
            self.assertTrue(toolbar.isVisible())

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

    def test_compact_infobar_preserves_text_and_grid_controls(self):
        import libs.qdarktheme
        from libs.qdarktheme.themes.dark import stylesheet as dark
        from libs.qdarktheme.themes.light import stylesheet as light
        from appGUI.themes.dark_style_sheet import D_STYLE_SHEET
        from appGUI.themes.light_style_sheet import L_STYLE_SHEET

        dark.STYLE_SHEET = D_STYLE_SHEET
        light.STYLE_SHEET = L_STYLE_SHEET
        self.addCleanup(self.qapp.setStyleSheet, self.qapp.styleSheet())
        for theme in ('light', 'dark'):
            self.qapp.setStyleSheet(libs.qdarktheme.load_stylesheet(theme))
            for point_size in (0, 12, 16):
                with self.subTest(theme=theme, point_size=point_size):
                    window = ToolbarWindow()
                    self.addCleanup(window.close)
                    window.resize(2400, 300)
                    if point_size:
                        window.setStyleSheet('QWidget { font-size: %dpt; }' % point_size)
                    window.app.resource_location = 'assets/resources'
                    window.fcinfo = AppInfoBar(app=window.app)
                    window.infobar.insertWidget(0, window.fcinfo, 1)
                    window.units_label = FCLabel('[mm]')
                    window.units_label.setMargin(2)
                    window.infobar.addWidget(window.units_label)
                    window.activity_view = FlatCAMActivityView(
                        'assets/resources', 'Ball green', lambda: None)
                    window.infobar.addWidget(window.activity_view)
                    window.grid_toolbar.addAction(QtGui.QIcon('assets/resources/grid18.png'), 'Grid')
                    window.grid_toolbar.addWidget(FCCheckBox())
                    status_icon = FCLabel()
                    status_icon.setPixmap(QtGui.QPixmap('assets/resources/axis18.png'))
                    window.status_toolbar.addWidget(status_icon)
                    entries = [FCEntry2(), FCEntry2(), FCEntry()]
                    for entry in entries:
                        entry.setMaximumWidth(70)
                        entry.set_value(0.1234)
                        window.grid_toolbar.addWidget(entry)
                    window.grid_toolbar.setMaximumHeight(24)
                    window.status_toolbar.setMaximumHeight(24)
                    window.ensurePolished()
                    QtCore.QCoreApplication.sendEvent(
                        window.infobar, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
                    old_height = window.infobar.sizeHint().height()
                    fonts = [entry.font() for entry in entries]
                    MainGUI.compact_infobar(window)
                    window.show()
                    self.qapp.processEvents()
                    self.assertEqual(window.infobar.height(), max(
                        round(old_height * 0.75), window.infobar.minimumSizeHint().height()))
                    for entry, original_font in zip(entries, fonts):
                        self.assertEqual(entry.font(), original_font)
                        self.assertEqual(entry.maximumWidth(), 70)
                        self.assertEqual(entry.get_value(), '0.1234')
                        option = QtWidgets.QStyleOptionFrame()
                        entry.initStyleOption(option)
                        contents = entry.style().subElementRect(
                            QtWidgets.QStyle.SubElement.SE_LineEditContents, option, entry)
                        self.assertGreaterEqual(contents.height(), entry.fontMetrics().height())
                        position = entry.mapTo(window.infobar, QtCore.QPoint(0, 0))
                        self.assertGreaterEqual(position.y(), 0)
                        self.assertLessEqual(position.y() + entry.height(), window.infobar.height())
                    window.close()


if __name__ == '__main__':
    unittest.main()
