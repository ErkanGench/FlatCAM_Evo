"""Tests for the Project combobox above the Project tab tree."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6 import QtCore, QtWidgets


class FakeManager(QtCore.QObject):
    projects_changed = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.contexts = [SimpleNamespace(name='Board_A'), SimpleNamespace(name='Board_B')]
        self.active = self.contexts[0]
        self.app = SimpleNamespace(inform=Mock(), f_handlers=SimpleNamespace(on_file_open_project=Mock(),
                                                                                on_file_save_project=Mock()),
                                   resource_location='assets/resources')
        self.busy = False
        self.switch = Mock(side_effect=self._switch)
        self.new = Mock()
        self.rename = Mock(return_value=True)
        self.request_close = Mock()

    def _switch(self, ctx):
        self.active = ctx
        return True

    def names(self):
        return [ctx.name for ctx in self.contexts]

    def is_busy(self):
        return self.busy

    def inform_busy(self):
        self.app.inform.emit('busy')


class TestProjectSelector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make(self):
        from appGUI.ProjectSelector import ProjectSelector
        manager = FakeManager()
        return manager, ProjectSelector(manager)

    def test_combobox_lists_the_projects(self):
        manager, selector = self.make()
        self.assertEqual([selector.combo.itemText(i) for i in range(selector.combo.count())],
                         ['Board_A', 'Board_B'])
        self.assertEqual(selector.combo.currentIndex(), 0)

    def test_activated_switches(self):
        manager, selector = self.make()
        selector.on_activated(1)
        manager.switch.assert_called_once_with(manager.contexts[1])
        self.assertEqual(selector.combo.currentIndex(), 1)

    def test_menu_actions_call_the_manager(self):
        manager, selector = self.make()
        menu = selector.build_menu()
        actions = menu.actions()
        actions[0].trigger()
        manager.new.assert_called_once_with()
        actions[1].trigger()
        manager.app.f_handlers.on_file_open_project.assert_called_once_with()
        actions[2].trigger()
        manager.app.f_handlers.on_file_save_project.assert_called_once_with()
        actions[4].trigger()
        manager.request_close.assert_called_once_with(manager.active)

    def test_rename_uses_the_input_dialog(self):
        manager, selector = self.make()
        with patch.object(QtWidgets.QInputDialog, 'getText', return_value=('Board_C', True)):
            selector.on_rename()
        manager.rename.assert_called_once_with(manager.active, 'Board_C')

if __name__ == '__main__':
    unittest.main()
