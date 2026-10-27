"""Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y drive the app history from MainGUI.keyPressEvent; the view and editor keys."""
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from appGUI.MainGUI import MainGUI

CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
SHIFT = QtCore.Qt.KeyboardModifier.ShiftModifier
NO_MODIFIER = QtCore.Qt.KeyboardModifier.NoModifier


def press(key, modifiers, source='app', in_text=False, options=None):
    gui = MagicMock()
    gui.app.call_source = source
    gui.app.history = Mock()
    if options is not None:
        gui.app.options = options
    gui.app_focus_in_text = lambda: in_text
    event = Mock()
    event.native.isAutoRepeat.return_value = False
    event.isAutoRepeat.return_value = False
    event.key = key
    with patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=modifiers):
        MainGUI.keyPressEvent(gui, event)
    return gui


class TestAppHistoryKeys(unittest.TestCase):
    def test_ctrl_z_undo(self):
        gui = press(QtCore.Qt.Key.Key_Z, CTRL)
        gui.app.history.undo.assert_called_once()
        gui.app.history.redo.assert_not_called()

    def test_ctrl_shift_z_redo(self):
        gui = press(QtCore.Qt.Key.Key_Z, CTRL | SHIFT)
        gui.app.history.redo.assert_called_once()
        gui.app.history.undo.assert_not_called()

    def test_ctrl_y_redo(self):
        gui = press(QtCore.Qt.Key.Key_Y, CTRL)
        gui.app.history.redo.assert_called_once()
        gui.app.history.undo.assert_not_called()

    def test_text_focus_blocks(self):
        gui = press(QtCore.Qt.Key.Key_Z, CTRL, in_text=True)
        gui.app.history.undo.assert_not_called()
        gui.app.history.redo.assert_not_called()


class TestViewKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        class Window(QtWidgets.QMainWindow):
            eventFilter = MainGUI.eventFilter
            app_focus_in_text = staticmethod(MainGUI.app_focus_in_text)

        self.window = Window()
        self.window.app = MagicMock()
        self.window.app.options = {'global_toggle_tooltips': True}
        self.target = QtWidgets.QPushButton('Canvas / editor / plugin')
        self.window.setCentralWidget(self.target)
        self.actions = {}
        for key, name in (('G', 'grid_lines'), ('A', 'axis'), ('H', 'hud'), ('W', 'workspace')):
            action = QtGui.QAction(name, self.window)
            action.setCheckable(True)
            setattr(self.window, 'menuview_toggle_' + name, action)
            self.actions[key] = action
        self.qapp.installEventFilter(self.window)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
        self.addCleanup(self.qapp.removeEventFilter, self.window)
        self.window.show()
        self.window.activateWindow()
        self.target.setFocus()
        self.qapp.processEvents()

    def test_view_toggles_work_once_outside_text_inputs(self):
        self.window.app.call_source = 'geo_editor'
        for key, action in self.actions.items():
            with self.subTest(key=key):
                before = action.isChecked()
                QtTest.QTest.keyClick(self.target, getattr(QtCore.Qt.Key, 'Key_' + key), SHIFT)
                self.assertEqual(action.isChecked(), not before)
                event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress,
                                       getattr(QtCore.Qt.Key, 'Key_' + key), SHIFT, key, True)
                self.qapp.sendEvent(self.target, event)
                self.assertEqual(action.isChecked(), not before)


class TestEditorKeys(unittest.TestCase):
    def test_minus_zooms_out_and_equal_zooms_in_in_the_editors_as_on_the_main_canvas(self):
        # plotcanvas.zoom(factor): a factor above 1 zooms out, below 1 zooms in
        for source in ('app', 'geo_editor', 'grb_editor', 'exc_editor'):
            factors = []
            for key in (QtCore.Qt.Key.Key_Minus, QtCore.Qt.Key.Key_Equal):
                gui = press(key, NO_MODIFIER, source, options={'global_zoom_ratio': 1.5})
                factors.append(gui.app.plotcanvas.zoom.call_args.args[0])
            self.assertEqual(factors, [1.5, 1 / 1.5], source)


if __name__ == '__main__':
    unittest.main()
