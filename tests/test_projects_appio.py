"""appIO follows the multiple projects rules: New, Open, Save and Save As."""

import os
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtCore, QtWidgets

from appHandlers.appIO import appIO
from defaults import AppOptions


class ProjectSignals(QtCore.QObject):
    new_project = QtCore.pyqtSignal()
    restore = QtCore.pyqtSignal(object, str, bool, bool, bool, bool)
    objects = QtCore.pyqtSignal(object, str, bool, bool)


class Defaults(dict):
    # on_file_save_project_as() reads app.defaults.factory_defaults
    factory_defaults = {}


class AppIOTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.window = QtWidgets.QWidget()
        self.addCleanup(self.window.close)
        self.window.set_ui_title = Mock()
        self.signals = ProjectSignals()
        self.tasks = []
        self.projects = Mock()
        defaults = Defaults()
        self.app = SimpleNamespace(
            log=Mock(), inform=Mock(), splash=Mock(), defaults=defaults, app_units='MM',
            options=AppOptions(version='test', baseline={}, defaults=defaults), preferencesUiManager=Mock(),
            ui=self.window, new_project_signal=self.signals.new_project,
            restore_project=self.signals.restore, restore_project_objects_sig=self.signals.objects,
            worker_task=SimpleNamespace(emit=self.tasks.append),
            proc_container=SimpleNamespace(new=lambda text: nullcontext()),
            block_autosave=False, project_filename=None, resource_location='assets/resources',
            app_obj=SimpleNamespace(load_batches=set()), projects=self.projects,
            file_opened=Mock(), file_saved=Mock(), should_we_save=True,
            get_last_save_folder=Mock(return_value=self.directory.name))
        self.io = appIO(self.app)

    def path(self, name):
        return os.path.join(self.directory.name, name)


class TestNewAndOpen(AppIOTestBase):
    def test_file_new_adds_a_project(self):
        self.io.on_file_new_project = Mock()
        self.io.on_file_new_click()
        self.projects.new.assert_called_once_with()
        self.io.on_file_new_project.assert_not_called()

    def test_gui_open_stops_when_prepare_open_refuses(self):
        filename = self.path('Board.FlatPrj')
        with open(filename, 'w') as stream:
            stream.write('{}')
        self.projects.prepare_open.return_value = False

        self.io._open_project(filename, False, True, False, False)

        self.projects.prepare_open.assert_called_once_with(filename)
        self.assertFalse(self.app.block_autosave)
        self.assertEqual(self.tasks, [])

    def test_tcl_open_does_not_call_prepare_open(self):
        filename = self.path('Board.FlatPrj')
        with open(filename, 'w') as stream:
            stream.write('{}')
        self.io._open_project(filename, False, False, True, True)
        self.projects.prepare_open.assert_not_called()

    def test_restore_adopts_the_filename(self):
        self.io.on_file_new_project = Mock()
        proj_dict = {'objs': [], 'options': {}}
        self.io._restore_project_handler(proj_dict, self.path('Board.FlatPrj'), True, True, True, True)
        self.projects.adopt_filename.assert_called_once_with(self.path('Board.FlatPrj'))


if __name__ == '__main__':
    unittest.main()
