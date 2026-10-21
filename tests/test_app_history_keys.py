"""Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y drive the app history from MainGUI.keyPressEvent."""
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtCore, QtWidgets

from appGUI.MainGUI import MainGUI

CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
SHIFT = QtCore.Qt.KeyboardModifier.ShiftModifier


def press(key, modifiers, source='app', in_text=False):
    gui = MagicMock()
    gui.app.call_source = source
    gui.app.history = Mock()
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

    def test_str_keys(self):
        self.assertEqual(press('Z', CTRL).app.history.undo.call_count, 1)
        self.assertEqual(press('Y', CTRL).app.history.redo.call_count, 1)

    def test_text_focus_blocks(self):
        gui = press(QtCore.Qt.Key.Key_Z, CTRL, in_text=True)
        gui.app.history.undo.assert_not_called()
        gui.app.history.redo.assert_not_called()

    def test_other_call_source(self):
        gui = press(QtCore.Qt.Key.Key_Z, CTRL, source='geo_editor')
        gui.app.history.undo.assert_not_called()
        gui.app.history.redo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
