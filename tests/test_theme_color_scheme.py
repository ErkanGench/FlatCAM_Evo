"""
The 'default' and 'light' themes use colors made for a light window and 'dark' colors made for a dark one: Qt's color
scheme has to follow the theme, not the operating system.
"""

import os

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from types import SimpleNamespace

import appMain
from appGUI.MainGUI import MainGUI

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

needs_color_scheme = pytest.mark.skipif(not hasattr(QtGui.QStyleHints, 'setColorScheme'),
                                        reason="Qt before 6.8 cannot set the color scheme")


@pytest.fixture(scope='module')
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def restore_scheme(qapp):
    yield
    if hasattr(qapp.styleHints(), 'unsetColorScheme'):
        qapp.styleHints().unsetColorScheme()


class RecordingHints:
    def __init__(self):
        self.calls = []

    def setColorScheme(self, scheme):
        self.calls.append(scheme)


class TestApplyColorScheme:
    @pytest.mark.parametrize('theme,scheme', [
        ('default', 'Light'),
        ('light', 'Light'),
        ('dark', 'Dark'),
    ])
    def test_the_scheme_asked_for_follows_the_theme(self, theme, scheme):
        hints = RecordingHints()
        app = SimpleNamespace(qapp=SimpleNamespace(styleHints=lambda: hints))
        appMain.App._apply_color_scheme(app, theme)
        assert hints.calls == [getattr(QtCore.Qt.ColorScheme, scheme)]

    @needs_color_scheme
    def test_light_themes_give_a_light_window_palette(self, qapp, restore_scheme):
        # the plot canvas uses QPalette().color(Window) as its border color together with black ticks
        appMain.App._apply_color_scheme(SimpleNamespace(qapp=qapp), 'light')
        if qapp.styleHints().colorScheme() == QtCore.Qt.ColorScheme.Unknown:
            pytest.skip("this Qt platform plugin ignores setColorScheme (offscreen)")
        assert QtGui.QPalette().color(QtGui.QPalette.ColorRole.Window).lightness() >= 128

    @needs_color_scheme
    def test_dark_theme_gives_a_dark_window_palette(self, qapp, restore_scheme):
        appMain.App._apply_color_scheme(SimpleNamespace(qapp=qapp), 'dark')
        if qapp.styleHints().colorScheme() == QtCore.Qt.ColorScheme.Unknown:
            pytest.skip("this Qt platform plugin ignores setColorScheme (offscreen)")
        assert QtGui.QPalette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128


class TestOldQt:
    def test_nothing_happens_without_set_color_scheme(self):
        class Hints:
            pass

        app = SimpleNamespace(qapp=SimpleNamespace(styleHints=lambda: Hints()))
        appMain.App._apply_color_scheme(app, 'dark')


class TestPreferencesTabText:
    @staticmethod
    def _gui(qapp, style_sheet):
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(QtWidgets.QWidget(), 'General')
        tabs.addTab(QtWidgets.QWidget(), 'Gerber')
        gui = SimpleNamespace(
            app=SimpleNamespace(qapp=SimpleNamespace(styleSheet=lambda: style_sheet)),
            pref_tab_area=tabs,
            set_pref_tab_area_tab_default_text_color=lambda: None,
        )
        return gui, tabs

    def test_selected_tab_is_green_when_a_stylesheet_is_used(self, qapp):
        gui, tabs = self._gui(qapp, 'QWidget { }')
        MainGUI.on_pref_tabbar_clicked(gui, 0)
        assert tabs.tabBar().tabTextColor(0) == QtGui.QColor('green')

    def test_selected_tab_uses_the_highlighted_text_color_in_the_default_theme(self, qapp):
        # no stylesheet: the selected tab is drawn with the system highlight, green on it was unreadable
        gui, tabs = self._gui(qapp, '')
        MainGUI.on_pref_tabbar_clicked(gui, 1)
        assert tabs.tabBar().tabTextColor(1) == tabs.palette().color(QtGui.QPalette.ColorRole.HighlightedText)

    def test_an_explicit_color_is_kept(self, qapp):
        gui, tabs = self._gui(qapp, '')
        MainGUI.on_pref_tabbar_clicked(gui, 0, QtGui.QColor('red'))
        assert tabs.tabBar().tabTextColor(0) == QtGui.QColor('red')
