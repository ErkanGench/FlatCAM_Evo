"""appIO follows the multiple projects rules: New, Open, Save and Save As."""

import os
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from PyQt6 import QtCore, QtWidgets

from appHandlers.appHistory import HistoryManager, HistoryStep
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
            project_filename=None, resource_location='assets/resources',
            app_obj=SimpleNamespace(load_batches=set()), projects=self.projects,
            file_opened=Mock(), file_saved=Mock(), should_we_save=True,
            get_last_save_folder=Mock(return_value=self.directory.name))
        self.io = appIO(self.app)

    def path(self, name):
        return os.path.join(self.directory.name, name)


class TestNewAndOpen(AppIOTestBase):
    def test_reset_clears_only_active_history_in_both_branches(self):
        for keep_scripts in (False, True):
            app = MagicMock()
            app.headless = False
            app.call_source = 'app'
            app.collection.get_list.return_value = []
            app.history = HistoryManager(app, app.collection)
            app.history.push(HistoryStep())
            inactive, _unused = __import__('test_app_history').manager()
            inactive.push(HistoryStep())
            io = appIO(app)
            io.on_file_new_project(cli=True, use_thread=True, keep_scripts=keep_scripts)
            self.assertFalse(app.history.can_undo())
            self.assertTrue(inactive.can_undo())
            app.history_changed.emit.assert_called_with('', '')

    def test_cancelled_editor_shutdown_preserves_history_and_objects(self):
        app = MagicMock()
        app.call_source = 'geo_editor'
        app.on_editing_finished.return_value = 'fail'
        io = appIO(app)
        self.assertEqual(io.on_file_new_project(), 'fail')
        app.history.clear.assert_not_called()
        app.collection.delete_all.assert_not_called()
        app.collection.delete_by_name.assert_not_called()

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


class TestSave(AppIOTestBase):
    def run_queued_save(self, ok):
        """Run the queued save task with a save_project() that returns ok."""
        from unittest.mock import patch
        task = self.tasks[-1]
        with patch.object(appIO, 'save_project', return_value=ok):
            task['fcn'](*task['params'])

    def test_save_after_rename_writes_the_new_file(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')

        self.io.on_file_save_project()

        self.assertEqual(self.tasks[-1]['params'][0], self.path('Board_B.FlatPrj'))
        # the file name does not change before the save ends; the save blocks the exit
        self.assertEqual(self.app.project_filename, self.path('Board_A.FlatPrj'))
        self.assertTrue(self.app.save_in_progress)
        self.projects.adopt_filename.assert_not_called()
        self.app.file_saved.emit.assert_not_called()

        self.run_queued_save(True)

        self.assertEqual(self.app.project_filename, self.path('Board_B.FlatPrj'))
        self.projects.adopt_filename.assert_called_once_with(self.path('Board_B.FlatPrj'))
        self.assertFalse(self.app.should_we_save)
        self.app.file_saved.emit.assert_called_once_with('project', self.path('Board_B.FlatPrj'))

    def test_failed_save_keeps_the_old_state(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')

        self.io.on_file_save_project()
        self.run_queued_save(False)

        self.assertEqual(self.app.project_filename, self.path('Board_A.FlatPrj'))
        self.projects.adopt_filename.assert_not_called()
        self.assertTrue(self.app.should_we_save)
        self.app.file_saved.emit.assert_not_called()

    def test_change_during_the_save_keeps_the_project_dirty(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        # the user deletes an object while the worker writes the earlier state
        self.app.should_we_save = True

        self.run_queued_save(True)

        self.assertTrue(self.app.should_we_save)
        self.app.file_saved.emit.assert_called_once_with('project', self.path('Board_A.FlatPrj'))

    def test_second_save_is_refused_while_the_first_is_running(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        self.io.on_file_save_project()
        self.assertEqual(len(self.tasks), 1)
        self.assertTrue(self.app.project_save_pending)

        self.run_queued_save(True)

        self.assertFalse(self.app.project_save_pending)
        self.io.on_file_save_project()
        self.assertEqual(len(self.tasks), 2)

    def test_save_stays_pending_until_the_gui_completion(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        # the worker ends with a failure, but its completion signal is not delivered yet
        self.io.project_save_done.disconnect(self.io._on_project_save_done)
        self.run_queued_save(False)
        self.assertTrue(self.app.project_save_pending)
        self.assertFalse(self.app.should_we_save)

        # the completion arrives on the GUI thread
        self.io._on_project_save_done(self.path('Board_A.FlatPrj'), False, False, True)

        self.assertFalse(self.app.project_save_pending)
        self.assertTrue(self.app.should_we_save)

    def test_save_that_raises_reports_a_failure(self):
        from unittest.mock import patch
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        task = self.tasks[-1]
        with patch.object(appIO, 'save_project', side_effect=RuntimeError('boom')):
            task['fcn'](*task['params'])

        self.assertTrue(self.app.should_we_save)
        self.assertFalse(self.app.save_in_progress)
        self.app.file_saved.emit.assert_not_called()

    def test_save_after_rename_asks_before_overwrite(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        with open(self.path('Board_B.FlatPrj'), 'w') as stream:
            stream.write('x')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')
        self.projects.ask_yes_no.return_value = False

        self.io.on_file_save_project()

        self.assertEqual(self.tasks, [])
        self.assertEqual(self.app.project_filename, self.path('Board_A.FlatPrj'))

    def test_save_with_same_name_writes_the_same_file(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        self.assertEqual(self.tasks[-1]['params'][0], self.path('Board_A.FlatPrj'))
        self.projects.ask_yes_no.assert_not_called()

    def test_save_as_suggests_the_project_name(self):
        from unittest.mock import patch
        self.projects.active = SimpleNamespace(name='Board_A')
        chosen = self.path('Chosen.FlatPrj')
        with patch('appHandlers.appIO.FCFileSaveDialog.get_saved_filename',
                   return_value=(chosen, '')) as dialog:
            self.io.on_file_save_project_as()
        self.assertEqual(dialog.call_args.kwargs['directory'], '%s/%s' % (self.directory.name, 'Board_A'))
        self.assertIsNone(self.app.project_filename)

        self.run_queued_save(True)

        self.assertEqual(self.app.project_filename, chosen)
        self.projects.adopt_filename.assert_called_once_with(chosen)
        self.assertFalse(self.app.should_we_save)

    def test_failed_save_as_keeps_the_old_state(self):
        from unittest.mock import patch
        self.projects.active = SimpleNamespace(name='Board_A')
        with patch('appHandlers.appIO.FCFileSaveDialog.get_saved_filename',
                   return_value=(self.path('Chosen.FlatPrj'), '')):
            self.io.on_file_save_project_as()

        self.run_queued_save(False)

        self.assertIsNone(self.app.project_filename)
        self.projects.adopt_filename.assert_not_called()
        self.assertTrue(self.app.should_we_save)
        self.app.file_saved.emit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
