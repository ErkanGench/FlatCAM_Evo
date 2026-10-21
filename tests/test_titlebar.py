"""Run: .venv/Scripts/python.exe tests/test_titlebar.py"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qt_isolation  # noqa: E402

from PyQt6 import QtCore, QtGui, QtTest, QtWidgets
from appGUI.TitleBar import TitleBar
from appGUI.MainGUI import MainGUI
from defaults import AppDefaults, AppOptions


class TitleWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.close_requests = 0
        self.setMinimumSize(450, 200)
        self.resize(900, 400)
        self.menu = QtWidgets.QMenuBar(self)
        self.file_menu = self.menu.addMenu('File')
        self.open_action = self.file_menu.addAction('Open')
        self.submenu = self.file_menu.addMenu('Recent')
        self.recent_action = self.submenu.addAction('Board')
        self.menu.addMenu('Edit')
        self.notebook_action = QtGui.QAction('Toggle Panel', self)
        self.notebook_action.setCheckable(True)
        self.menu.addAction(self.notebook_action)
        self.title_bar = TitleBar(self, self.menu, self.notebook_action)
        self.setMenuWidget(self.title_bar)
        self.setCentralWidget(QtWidgets.QPushButton('Canvas'))
        self.setWindowTitle('board.FlatPrj')

    def closeEvent(self, event):
        self.close_requests += 1
        event.ignore()


class TestTitleBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = TitleWindow()
        self.bar = self.window.title_bar
        self.window.show()
        self.qapp.processEvents()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.hide)

    def expand(self):
        QtTest.QTest.mouseClick(self.bar.menu_button, QtCore.Qt.MouseButton.LeftButton)
        self.qapp.processEvents()

    def test_existing_actions_and_project_title_are_reused(self):
        self.assertTrue(self.window.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint)
        self.assertIs(self.bar.menu, self.window.menu)
        self.assertNotIn(self.window.notebook_action, self.bar.menu.actions())
        self.assertIs(self.bar.notebook_button.defaultAction(), self.window.notebook_action)
        QtTest.QTest.mouseClick(self.bar.notebook_button, QtCore.Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.notebook_action.isChecked())
        self.assertEqual(self.bar.title_label.text(), 'Project: board.FlatPrj')
        self.assertEqual(self.bar.title_label.toolTip(), 'Project: board.FlatPrj')
        self.assertEqual(self.bar.toolbar.objectName(), 'title_toolbar')
        self.assertEqual(self.bar.toolbar.actions(), [])
        self.window.setWindowTitle('D:/boards/' + 'long-project-name' * 30)
        self.qapp.processEvents()
        self.assertEqual(self.bar.title_label.toolTip(), 'Project: ' + self.window.windowTitle())
        self.assertIn('\u2026', self.bar.title_label.text())

    def test_menu_expands_and_outside_click_or_escape_collapses(self):
        self.assertTrue(self.bar.menu_button.isVisible())
        self.assertFalse(self.bar.menu.isVisible())
        self.expand()
        self.assertFalse(self.bar.menu_button.isVisible())
        self.assertTrue(self.bar.menu.isVisible())
        QtTest.QTest.mouseClick(self.window.centralWidget(), QtCore.Qt.MouseButton.LeftButton)
        self.assertTrue(self.bar.menu_button.isVisible())
        self.expand()
        QtTest.QTest.keyClick(self.bar.menu, QtCore.Qt.Key.Key_Escape)
        self.assertTrue(self.bar.menu_button.isVisible())

    def test_hamburger_has_four_thin_horizontal_strokes(self):
        button = self.bar.menu_button
        image = button.grab().toImage()
        scale = button.devicePixelRatioF()
        strokes = []
        in_stroke = False
        for y in range(image.height()):
            ink = image.pixelColor(image.width() // 2, y) != image.pixelColor(round(3 * scale), y)
            if ink and not in_stroke:
                strokes.append(0)
            if ink:
                strokes[-1] += 1
            in_stroke = ink
        self.assertEqual(len(strokes), 4)
        self.assertTrue(all(height <= 2 * scale for height in strokes))

    def test_project_title_is_centered_while_title_toolbar_stays_right(self):
        self.assertEqual(self.bar.title_label.alignment(), QtCore.Qt.AlignmentFlag.AlignCenter)
        for expanded in (False, True):
            for action_count in (0, 3):
                with self.subTest(expanded=expanded, actions=action_count):
                    self.bar.toolbar.clear()
                    for index in range(action_count):
                        self.bar.toolbar.addAction('Action %d' % index)
                    if expanded:
                        self.bar.expand_menu()
                    else:
                        self.bar.collapse_menu()
                    self.qapp.processEvents()
                    self.qapp.processEvents()
                    self.assertLessEqual(abs(self.bar.title_label.geometry().center().x() -
                                             self.bar.rect().center().x()), 1)
                    self.assertEqual(self.bar.minimize_button.x() - self.bar.toolbar.geometry().right() - 1, 2)
                    if self.bar.title_label.width():
                        self.assertLess(self.bar.title_label.geometry().right(), self.bar.toolbar.x())

    def test_submenus_stay_open_until_action_is_chosen(self):
        self.expand()
        self.window.file_menu.popup(self.bar.menu.mapToGlobal(QtCore.QPoint(0, self.bar.menu.height())))
        self.qapp.processEvents()
        self.window.submenu.popup(self.window.file_menu.mapToGlobal(QtCore.QPoint(100, 0)))
        self.qapp.processEvents()
        QtTest.QTest.mousePress(self.window.submenu, QtCore.Qt.MouseButton.LeftButton,
                                pos=self.window.submenu.actionGeometry(self.window.recent_action).center())
        self.assertTrue(self.bar.menu.isVisible())
        selected = QtTest.QSignalSpy(self.window.recent_action.triggered)
        QtTest.QTest.mouseRelease(self.window.submenu, QtCore.Qt.MouseButton.LeftButton,
                                  pos=self.window.submenu.actionGeometry(self.window.recent_action).center())
        self.qapp.processEvents()
        self.assertEqual(len(selected), 1)
        self.assertTrue(self.bar.menu_button.isVisible())
        self.assertFalse(self.window.file_menu.isVisible())
        self.assertFalse(self.window.submenu.isVisible())

    def test_window_controls_and_system_menu_follow_window_state(self):
        buttons = (self.bar.minimize_button, self.bar.maximize_button, self.bar.close_button)
        for button in buttons:
            self.assertEqual(button.width(), 46)
        for previous, following in zip(buttons, buttons[1:]):
            self.assertEqual(following.geometry().center().x() - previous.geometry().center().x(), 46)
        self.assertFalse(self.bar.restore_action.isEnabled())
        self.assertTrue(self.bar.maximize_action.isEnabled())
        QtTest.QTest.mouseClick(self.bar.maximize_button, QtCore.Qt.MouseButton.LeftButton)
        self.qapp.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.bar.restore_action.isEnabled())
        self.assertFalse(self.bar.maximize_action.isEnabled())
        self.assertTrue(all(not handle.isVisible() for handle in self.bar.resize_handles.values()))
        QtTest.QTest.mouseClick(self.bar.maximize_button, QtCore.Qt.MouseButton.LeftButton)
        self.qapp.processEvents()
        self.assertFalse(self.window.isMaximized())
        self.bar.minimize_action.trigger()
        self.assertTrue(self.window.isMinimized())
        self.bar.restore_action.trigger()
        self.qapp.processEvents()
        self.assertFalse(self.window.isMinimized())
        QtTest.QTest.mouseClick(self.bar.close_button, QtCore.Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.close_requests, 1)
        self.assertTrue(self.window.isVisible())
        self.bar.close_action.trigger()
        self.assertEqual(self.window.close_requests, 2)

    def test_caption_glyphs_follow_the_button_text_palette(self):
        for color in (QtGui.QColor('#2d2d2d'), QtGui.QColor('#efefef')):
            for button in (self.bar.minimize_button, self.bar.maximize_button, self.bar.close_button):
                with self.subTest(color=color.name(), button=button.toolTip()):
                    palette = button.palette()
                    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, color)
                    palette.setColor(QtGui.QPalette.ColorRole.WindowText, color)
                    button.setPalette(palette)
                    image = button.grab().toImage()
                    pixels = sum(image.pixelColor(x, y) == color
                                 for x in range(image.width()) for y in range(image.height()))
                    self.assertGreater(pixels, 4)

    def test_dark_notebook_icon_matches_hamburger_gray(self):
        self.window.notebook_action.setIcon(QtGui.QIcon('assets/resources/notebook32.png'))
        original = self.window.notebook_action.icon().cacheKey()
        palette = self.window.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor('#202124'))
        palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor('#bdbdbd'))
        self.window.setPalette(palette)
        self.qapp.processEvents()
        color = self.bar.menu_button.palette().color(QtGui.QPalette.ColorRole.ButtonText)
        image = self.bar.notebook_button.grab().toImage()
        pixels = sum(image.pixelColor(x, y) == color
                     for x in range(image.width()) for y in range(image.height()))
        self.assertGreater(pixels, 4)
        self.assertEqual(self.window.notebook_action.icon().cacheKey(), original)

    def test_notebook_glyph_matches_hamburger_width_and_lower_edge(self):
        # the application stylesheet changes restyle every widget of the process
        if qt_isolation.run_in_clean_process(self):
            return
        import libs.qdarktheme
        from libs.qdarktheme.themes.dark import stylesheet as dark
        from libs.qdarktheme.themes.light import stylesheet as light
        from appGUI.themes.dark_style_sheet import D_STYLE_SHEET
        from appGUI.themes.light_style_sheet import L_STYLE_SHEET

        dark.STYLE_SHEET = D_STYLE_SHEET
        light.STYLE_SHEET = L_STYLE_SHEET
        self.addCleanup(self.qapp.setStyleSheet, self.qapp.styleSheet())
        self.window.notebook_action.setIcon(QtGui.QIcon('assets/resources/notebook32.png'))
        for theme in ('light', 'dark'):
            with self.subTest(theme=theme):
                self.qapp.setStyleSheet(libs.qdarktheme.load_stylesheet(theme))
                self.qapp.processEvents()
                bounds = []
                for button in (self.bar.menu_button, self.bar.notebook_button):
                    image = button.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32)
                    scale = button.devicePixelRatioF()
                    # 1 NumPy compare for the whole image: QImage.pixelColor() for each pixel took about 28 s
                    bits = image.constBits()
                    bits.setsize(image.sizeInBytes())
                    pixels = np.frombuffer(bits, np.uint32).reshape(image.height(), -1)[:, :image.width()]
                    left = round(4 * scale)
                    # a pixel is part of the glyph when it differs from the background column at x = 3 * scale
                    ys, xs = np.nonzero(pixels[:, left:image.width() - left] != pixels[:, [round(3 * scale)]])
                    xs = xs + left
                    bounds.append(QtCore.QRect(int(xs.min()), int(ys.min()),
                                               int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
                hamburger, notebook = bounds
                self.assertLessEqual(abs(notebook.width() - hamburger.width()), scale)
                self.assertGreaterEqual(notebook.bottom(), hamburger.bottom())

    def test_titlebar_keeps_previous_height_and_enlarged_icons_and_menus(self):
        status = self.window.statusBar()
        status.showMessage('Ready')
        self.qapp.processEvents()
        self.assertEqual(self.bar.height(), 34)
        status.setFixedHeight(24)
        self.qapp.processEvents()
        self.assertEqual(self.bar.height(), 34)
        for button in (self.bar.icon_button, self.bar.notebook_button, self.bar.menu_button,
                       self.bar.minimize_button, self.bar.maximize_button, self.bar.close_button):
            self.assertEqual(button.iconSize(), QtCore.QSize(16, 16))
        self.assertEqual(self.bar.toolbar.iconSize(), QtCore.QSize(16, 16))
        native = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        self.assertAlmostEqual(self.bar.menu.font().pointSizeF(), native.pointSizeF(), delta=0.1)
        for button in (self.bar.icon_button, self.bar.notebook_button, self.bar.menu_button):
            self.assertEqual(button.width(), 32)
        self.expand()
        self.assertEqual(self.bar.height(), 34)
        self.assertGreaterEqual(self.bar.menu.height(), self.bar.menu.fontMetrics().height())

    def test_title_uses_native_system_font_despite_application_font_overrides(self):
        native = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.TitleFont)
        for family in ('Arial', 'Times New Roman'):
            with self.subTest(application_font=family):
                self.window.setStyleSheet('QWidget { font-family: "%s"; font-size: 18pt; }' % family)
                self.qapp.processEvents()
                actual = self.bar.title_label.font()
                self.assertEqual(actual.family(), native.family())
                self.assertAlmostEqual(actual.pointSizeF(), native.pointSizeF(), delta=0.1)

    def test_startup_layout_changes_do_not_cover_resize_handles(self):
        dock = QtWidgets.QDockWidget('Notebook', self.window)
        dock.setWidget(QtWidgets.QLabel('Notebook'))
        self.window.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.window.statusBar().showMessage('Ready')
        self.qapp.processEvents()
        self.qapp.processEvents()
        for edges, handle in self.bar.resize_handles.items():
            with self.subTest(edges=edges):
                self.assertIs(self.window.childAt(handle.geometry().center()), handle)

    def test_windows_rounded_corner_preference(self):
        if sys.platform != 'win32' or self.qapp.platformName() != 'windows':
            self.skipTest('Requires the Windows window manager')
        if sys.getwindowsversion().build < 22000:
            self.skipTest('DWM rounded corners require Windows 11')
        import ctypes
        from ctypes import wintypes

        requests = []
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute

        def record_attribute(handle, attribute, value, size):
            result = set_attribute(handle, attribute, value, size)
            self.assertEqual(result, 0)
            requests.append((attribute, ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32)).contents.value))
            return result

        # DWM's border color is set-only, so verify the real setter's value and HRESULT.
        with patch.object(ctypes.windll.dwmapi, 'DwmSetWindowAttribute', side_effect=record_attribute):
            for index, (show, corner, border) in enumerate((
                    (self.window.showNormal, 2, 0xffffffff),
                    (self.window.showMaximized, 1, 0xfffffffe),
                    (self.window.showNormal, 2, 0xffffffff),
                    (self.window.showFullScreen, 1, 0xfffffffe),
                    (self.window.showNormal, 2, 0xffffffff))):
                with self.subTest(state=show.__name__):
                    requests.clear()
                    show()
                    if index == 0:
                        self.bar.update_native_corners()
                    self.qapp.processEvents()
                    self.assertIn((33, corner), requests)
                    self.assertIn((34, border), requests)
                    value = ctypes.c_uint32()
                    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                        wintypes.HWND(int(self.window.winId())), 33,
                        ctypes.byref(value), ctypes.sizeof(value))
                    self.assertEqual(result, 0)
                    self.assertEqual(value.value, corner)

    def test_drag_and_resize_fallback_and_cursors(self):
        left = QtCore.Qt.MouseButton.LeftButton
        with patch.object(QtGui.QWindow, 'startSystemMove', return_value=False):
            initial = self.window.pos()
            position = self.bar.title_label.geometry().center()
            QtTest.QTest.mousePress(self.bar, left, pos=position)
            QtTest.QTest.mouseMove(self.bar, position + QtCore.QPoint(30, 20))
            QtTest.QTest.mouseRelease(self.bar, left, pos=position)
            self.assertEqual(self.window.pos(), initial + QtCore.QPoint(30, 20))
        expected_cursors = {
            QtCore.Qt.Edge.LeftEdge: QtCore.Qt.CursorShape.SizeHorCursor,
            QtCore.Qt.Edge.TopEdge: QtCore.Qt.CursorShape.SizeVerCursor,
            QtCore.Qt.Edge.TopEdge | QtCore.Qt.Edge.LeftEdge: QtCore.Qt.CursorShape.SizeFDiagCursor,
            QtCore.Qt.Edge.TopEdge | QtCore.Qt.Edge.RightEdge: QtCore.Qt.CursorShape.SizeBDiagCursor,
        }
        self.assertEqual(len(self.bar.resize_handles), 8)
        for edges, cursor in expected_cursors.items():
            self.assertEqual(self.bar.resize_handles[edges].cursor().shape(), cursor)
        with patch.object(QtGui.QWindow, 'startSystemResize', return_value=False):
            for edges, handle in self.bar.resize_handles.items():
                with self.subTest(edges=edges):
                    self.window.setGeometry(100, 100, 900, 400)
                    self.qapp.processEvents()
                    initial = self.window.geometry()
                    position = handle.rect().center()
                    QtTest.QTest.mousePress(handle, left, pos=position)
                    QtTest.QTest.mouseMove(handle, position + QtCore.QPoint(20, 10))
                    QtTest.QTest.mouseRelease(handle, left, pos=position)
                    result = self.window.geometry()
                    if edges & QtCore.Qt.Edge.LeftEdge:
                        self.assertEqual(result.left(), initial.left() + 20)
                        self.assertEqual(result.right(), initial.right())
                    if edges & QtCore.Qt.Edge.RightEdge:
                        self.assertEqual(result.right(), initial.right() + 20)
                    if edges & QtCore.Qt.Edge.TopEdge:
                        self.assertEqual(result.top(), initial.top() + 10)
                        self.assertEqual(result.bottom(), initial.bottom())
                    if edges & QtCore.Qt.Edge.BottomEdge:
                        self.assertEqual(result.bottom(), initial.bottom() + 10)

    def test_native_move_and_resize_are_preferred_when_available(self):
        left = QtCore.Qt.MouseButton.LeftButton
        with patch.object(QtGui.QWindow, 'startSystemMove', return_value=True) as move:
            QtTest.QTest.mouseClick(self.bar, left, pos=self.bar.title_label.geometry().center())
            move.assert_called_once()
            self.assertIsNone(self.bar.move_position)
        for edges, handle in self.bar.resize_handles.items():
            with patch.object(QtGui.QWindow, 'startSystemResize', return_value=True) as resize:
                QtTest.QTest.mouseClick(handle, left, pos=handle.rect().center())
                resize.assert_called_once_with(edges)
                self.assertIsNone(handle.start_position)

    def test_maximized_drag_restores_previous_size_before_native_move(self):
        window = self.window
        original_size = window.size()
        window.showMaximized()
        self.qapp.processEvents()
        position = self.bar.title_label.geometry().center()
        left = QtCore.Qt.MouseButton.LeftButton
        for native in (True, False):
            with self.subTest(native=native):
                window.showMaximized()
                self.qapp.processEvents()
                position = self.bar.title_label.geometry().center()
                with patch.object(QtGui.QWindow, 'startSystemMove', return_value=native) as move:
                    QtTest.QTest.mousePress(self.bar, left, pos=position)
                    self.assertTrue(window.isMaximized())
                    move.assert_not_called()
                    QtTest.QTest.mouseMove(self.bar, position + QtCore.QPoint(30, 20))
                    self.assertFalse(window.isMaximized())
                    self.assertEqual(window.size(), original_size)
                    move.assert_called_once()
                    QtTest.QTest.mouseRelease(self.bar, left)
                self.qapp.processEvents()

                self.assertEqual(window.size(), original_size)

    def test_click_on_maximized_titlebar_does_not_restore_window(self):
        self.window.showMaximized()
        self.qapp.processEvents()
        position = self.bar.title_label.geometry().center()
        with patch.object(QtGui.QWindow, 'startSystemMove', return_value=True) as move:
            QtTest.QTest.mouseClick(self.bar, QtCore.Qt.MouseButton.LeftButton, pos=position)
            self.assertTrue(self.window.isMaximized())
            move.assert_not_called()

    def test_resize_fallback_honors_size_limits(self):
        edge = QtCore.Qt.Edge
        handle = self.bar.resize_handles[edge.TopEdge | edge.LeftEdge]
        window = self.window
        window.setGeometry(100, 100, 900, 400)
        self.qapp.processEvents()
        initial = window.geometry()
        with patch.object(QtGui.QWindow, 'startSystemResize', return_value=False):
            QtTest.QTest.mousePress(handle, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(2, 2))
            QtTest.QTest.mouseMove(handle, QtCore.QPoint(2000, 2000))
            self.assertEqual(window.geometry().bottomRight(), initial.bottomRight())
            self.assertGreaterEqual(window.size().width(), window.minimumSizeHint().width())
            self.assertGreaterEqual(window.size().height(), window.minimumHeight())
            QtTest.QTest.mouseRelease(handle, QtCore.Qt.MouseButton.LeftButton)

    def test_real_menu_bar_click_and_action_selection(self):
        self.expand()
        QtTest.QTest.mouseClick(self.bar.menu, QtCore.Qt.MouseButton.LeftButton,
                                pos=self.bar.menu.actionGeometry(self.window.file_menu.menuAction()).center())
        self.qapp.processEvents()
        self.assertTrue(self.window.file_menu.isVisible())
        self.assertTrue(self.bar.menu.isVisible())
        selected = QtTest.QSignalSpy(self.window.open_action.triggered)
        QtTest.QTest.mouseClick(self.window.file_menu, QtCore.Qt.MouseButton.LeftButton,
                                pos=self.window.file_menu.actionGeometry(self.window.open_action).center())
        self.qapp.processEvents()
        self.assertEqual(len(selected), 1)
        self.assertTrue(self.bar.menu_button.isVisible())

    def test_theme_font_and_narrow_window_layout(self):
        # the application stylesheet changes restyle every widget of the process
        if qt_isolation.run_in_clean_process(self):
            return
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
            for point_size in (9, 12, 16):
                with self.subTest(theme=theme, point_size=point_size):
                    self.window.setStyleSheet('QWidget { font-size: %dpt; }' % point_size)
                    self.window.resize(450, 250)
                    self.window.setWindowTitle('D:/boards/' + 'long-project-name' * 30)
                    self.qapp.processEvents()
                    self.assertGreaterEqual(self.bar.height(), 34)
                    self.assertGreaterEqual(self.bar.title_label.height(),
                                            self.bar.title_label.fontMetrics().tightBoundingRect('Agj').height())
                    for button in (self.bar.icon_button, self.bar.notebook_button, self.bar.menu_button,
                                   self.bar.minimize_button, self.bar.maximize_button, self.bar.close_button):
                        self.assertTrue(self.bar.rect().contains(button.geometry()))
                    self.expand()
                    self.assertTrue(self.bar.menu.isVisible())
                    item = self.bar.menu.actionGeometry(self.bar.menu.actions()[0])
                    center = self.bar.menu.mapTo(self.bar, item.center())
                    self.assertLessEqual(abs(center.y() - self.bar.title_label.geometry().center().y()), 1)
                    self.assertTrue(self.bar.rect().contains(self.bar.close_button.geometry()))
                    self.bar.collapse_menu()

    def test_overflow_popup_is_kept_open_for_menu_navigation(self):
        for name in ('Options', 'View', 'Plugins', 'Scripting', 'Help'):
            self.bar.menu.addMenu(name)
        self.window.resize(450, 250)
        self.expand()
        extension = self.bar.menu.findChild(QtWidgets.QToolButton, 'qt_menubar_ext_button')
        self.assertIsNotNone(extension)
        self.assertTrue(extension.isVisible())
        popup = extension.menu()
        popup.popup(self.bar.menu.mapToGlobal(QtCore.QPoint(0, self.bar.menu.height())))
        self.qapp.processEvents()
        QtTest.QTest.mousePress(popup, QtCore.Qt.MouseButton.LeftButton,
                                pos=popup.actionGeometry(popup.actions()[0]).center())
        self.assertTrue(self.bar.menu.isVisible())
        QtTest.QTest.mouseRelease(popup, QtCore.Qt.MouseButton.LeftButton)
        self.bar.collapse_menu()

    def test_escape_closes_overflow_popup(self):
        for name in ('Options', 'View', 'Plugins', 'Scripting', 'Help'):
            self.bar.menu.addMenu(name)
        self.window.resize(450, 250)
        self.expand()
        extension = self.bar.menu.findChild(QtWidgets.QToolButton, 'qt_menubar_ext_button')
        self.assertIsNotNone(extension)
        popup = extension.menu()
        popup.popup(self.bar.menu.mapToGlobal(QtCore.QPoint(0, self.bar.menu.height())))
        self.qapp.processEvents()
        self.assertTrue(popup.isVisible())
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key.Key_Escape)
        self.assertTrue(self.bar.menu_button.isVisible())
        self.assertFalse(popup.isVisible())

    def test_fullscreen_hides_chrome_and_restores_it(self):
        self.expand()
        self.window.showFullScreen()
        self.qapp.processEvents()
        self.assertFalse(self.bar.isVisible())
        self.assertTrue(all(not handle.isVisible() for handle in self.bar.resize_handles.values()))
        self.window.showNormal()
        self.qapp.processEvents()
        self.assertTrue(self.bar.isVisible())
        self.assertTrue(self.bar.menu_button.isVisible())
        self.assertTrue(all(handle.isVisible() for handle in self.bar.resize_handles.values()))

    def test_main_window_project_titles_have_no_application_prefix(self):
        self.window.app = SimpleNamespace(version='1.2.3')
        MainGUI.set_ui_title(self.window, 'D:/boards/board.FlatPrj')
        self.assertEqual(self.window.windowTitle(), 'FlatCAM Evo 1.2.3')
        self.assertEqual(self.bar.title_label.toolTip(), 'Project: D:/boards/board.FlatPrj')
        MainGUI.set_ui_title(self.window, '')
        self.assertEqual(self.window.windowTitle(), 'FlatCAM Evo 1.2.3')
        self.assertEqual(self.bar.title_label.text(), 'Project: Untitled')
        MainGUI.set_ui_title(self.window, 'other.FlatPrj')
        self.assertEqual(self.window.windowTitle(), 'FlatCAM Evo 1.2.3')
        self.assertEqual(self.bar.title_label.text(), 'Project: other.FlatPrj')

    def test_main_window_installs_titlebar_and_exposes_toolbar(self):
        self.assertTrue(hasattr(MainGUI, 'build_titlebar'))
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        window.menu = QtWidgets.QMenuBar(window)
        window.menu.addMenu('File')
        window.menu_toggle_nb = QtGui.QAction('Notebook', window)
        # MainGUI.__init__ makes the Undo / Redo actions before the title bar
        window.undo_btn = QtGui.QAction('Undo', window)
        window.redo_btn = QtGui.QAction('Redo', window)
        window.app = SimpleNamespace(options={}, defaults=AppDefaults(beta=False))
        MainGUI.build_titlebar(window)
        self.assertIs(window.menuWidget(), window.title_bar)
        self.assertIs(window.title_toolbar, window.title_bar.toolbar)
        # the Undo / Redo buttons are just before the main menu button
        layout = window.title_bar.layout()
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        undo_btn, redo_btn = window.title_bar.history_buttons
        self.assertEqual(widgets.index(undo_btn) + 1, widgets.index(redo_btn))
        self.assertEqual(widgets.index(redo_btn) + 1, widgets.index(window.title_bar.menu_button))
        self.assertIs(undo_btn.defaultAction(), window.undo_btn)

    def test_main_window_can_use_native_titlebar_and_original_menu(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        window.app = SimpleNamespace(options={'global_custom_titlebar': False},
                                     version='1.2.3', beta=False)
        window.menu = QtWidgets.QMenuBar(window)
        window.menu_toggle_nb = window.menu.addAction('Notebook')
        file_menu = window.menu.addMenu('File')
        MainGUI.build_titlebar(window)
        self.assertFalse(window.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint)
        self.assertIsNone(window.title_bar)
        self.assertIsNone(window.title_toolbar)
        self.assertIs(window.menuBar(), window.menu)
        self.assertEqual(window.menu.actions(), [window.menu_toggle_nb, file_menu.menuAction()])
        self.assertFalse(window.findChildren(TitleBar))
        MainGUI.set_ui_title(window, 'board.FlatPrj')
        self.assertIn('FlatCAM Evo 1.2.3', window.windowTitle())
        self.assertNotIn('[2D]', window.windowTitle())
        self.assertNotIn('[3D]', window.windowTitle())
        self.assertIn('board.FlatPrj', window.windowTitle())
        window.app.options['global_graphic_engine'] = '3D'
        MainGUI.set_ui_title(window, '')
        self.assertNotIn('[3D]', window.windowTitle())

    def test_main_window_fullscreen_preserves_geometry_and_maximized_state(self):
        for custom_titlebar in (True, False):
            window = self.window if custom_titlebar else QtWidgets.QMainWindow()
            window.app = SimpleNamespace(qapp=self.qapp, ui=window, options={
                'global_custom_titlebar': custom_titlebar,
                'global_coords_bar_show': True, 'global_delta_coords_bar_show': True,
                'global_grid_bar_show': True, 'global_statusbar_show': True,
            })
            if not custom_titlebar:
                self.addCleanup(window.deleteLater)
                self.addCleanup(window.hide)
                window.menu = QtWidgets.QMenuBar(window)
                window.menu_toggle_nb = window.menu.addAction('Notebook')
                MainGUI.build_titlebar(window)
                window.resize(900, 400)
                window.show()
            window.hidden_toolbars = []
            window.original_window_flags = window.windowFlags()
            for name in ('coords_toolbar', 'delta_coords_toolbar', 'grid_toolbar', 'status_toolbar'):
                toolbar = QtWidgets.QToolBar(name)
                setattr(window, name, toolbar)
                window.statusBar().addWidget(toolbar)
            self.qapp.processEvents()
            original = window.geometry()
            for maximized in (False, True):
                with self.subTest(custom_titlebar=custom_titlebar, maximized=maximized):
                    if maximized:
                        window.showMaximized()
                        self.qapp.processEvents()
                    MainGUI.on_full_screen_toggled(window)
                    self.qapp.processEvents()
                    self.assertTrue(window.isFullScreen())
                    if custom_titlebar:
                        self.assertFalse(self.bar.isVisible())
                    MainGUI.on_full_screen_toggled(window)
                    self.qapp.processEvents()
                    self.assertFalse(window.isFullScreen())
                    self.assertEqual(bool(window.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint),
                                     custom_titlebar)
                    self.assertEqual(window.isMaximized(), maximized)
                    if not maximized:
                        self.assertEqual(window.geometry(), original)
                    else:
                        window.showNormal()
                        self.qapp.processEvents()
                        self.assertEqual(window.geometry(), original)


class TestTitleBarPreferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_preferences(self, path):
        from appGUI.preferences.OptionsGroupUI import OptionsGroupUI
        from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI
        from appGUI.preferences.PreferencesUIManager import PreferencesUIManager

        defaults = AppDefaults(beta=False)
        self.assertIs(defaults.get('global_custom_titlebar'), True)
        app = MagicMock()
        app.decimals = 4
        app.resource_location = 'assets/resources'
        app.options = AppOptions(version='test', baseline=defaults, defaults=defaults)
        with patch.object(OptionsGroupUI, 'app', app):
            group = GeneralGUIPrefGroupUI(app)
        self.addCleanup(group.deleteLater)
        ui = MagicMock()
        ui.app = app
        ui.plot_tab_area.count.return_value = 0
        ui.general_pref_form.general_gui_group = group
        for name in ('notebook', 'axis', 'textbox', 'hud'):
            spinner = getattr(ui.general_pref_form.general_app_set_group, name + '_font_size_spinner')
            spinner.get_value.return_value = 9
        manager = PreferencesUIManager(defaults, path, ui, MagicMock(), app.options)
        self.addCleanup(manager.deleteLater)
        self.assertIs(manager.defaults_form_fields.get('global_custom_titlebar'), group.custom_titlebar_cb)
        manager.defaults_write_form_field('global_custom_titlebar')
        self.assertTrue(group.custom_titlebar_cb.get_value())
        self.assertIn('restart', group.custom_titlebar_cb.toolTip().lower())
        manager.defaults_form_fields = {'global_custom_titlebar': group.custom_titlebar_cb}
        group.appearance_radio.set_value(defaults['global_appearance'])
        group.dark_canvas_cb.set_value(False)
        return manager

    def test_custom_titlebar_preference_defaults_on(self):
        with tempfile.TemporaryDirectory() as path:
            self.make_preferences(path)

    def test_custom_titlebar_changes_persist_and_restart_only_after_confirmation(self):
        for current, requested in ((True, False), (False, True)):
            for accept in (True, False):
                with self.subTest(current=current, requested=requested, accept=accept), \
                        tempfile.TemporaryDirectory() as path:
                    manager = self.make_preferences(path)
                    manager.defaults['global_custom_titlebar'] = current
                    manager.ui.app.options['global_custom_titlebar'] = current
                    checkbox = manager.ui.general_pref_form.general_gui_group.custom_titlebar_cb
                    checkbox.set_value(requested)
                    settings = QtCore.QSettings(os.path.join(path, 'settings.ini'), QtCore.QSettings.Format.IniFormat)
                    settings.setValue('appearance', manager.defaults['global_appearance'])
                    settings.setValue('dark_canvas', False)
                    dialog = MagicMock()
                    yes, cancel = object(), object()
                    dialog.addButton.side_effect = [yes, cancel]
                    dialog.clickedButton.return_value = yes if accept else cancel
                    with patch('appGUI.preferences.PreferencesUIManager.QtCore.QSettings', return_value=settings), \
                            patch('appGUI.preferences.PreferencesUIManager.QSettings', return_value=settings), \
                            patch('appGUI.preferences.PreferencesUIManager.FCMessageBox', return_value=dialog):
                        manager.on_save_button(save_to_file=False)
                    expected = requested if accept else current
                    dialog.exec.assert_called_once()
                    self.assertEqual(checkbox.get_value(), expected)
                    self.assertEqual(manager.defaults['global_custom_titlebar'], expected)
                    self.assertEqual(manager.ui.app.options['global_custom_titlebar'], expected)
                    if accept:
                        manager.ui.app.on_app_restart.assert_called_once()
                        saved = AppDefaults(beta=False)
                        saved.load(os.path.join(path, 'current_defaults.FlatConfig'), inform=MagicMock())
                        self.assertEqual(saved['global_custom_titlebar'], expected)
                    else:
                        manager.ui.app.on_app_restart.assert_not_called()
                    settings.sync()


if __name__ == '__main__':
    unittest.main()
