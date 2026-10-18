"""Tests for the multiple projects feature: ProjectManager and the handlers that read app.collection."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtWidgets


class FakeCollection:
    def __init__(self, objects=None):
        self.view = QtWidgets.QWidget()
        self.objects = list(objects or [])

    def get_list(self):
        return list(self.objects)

    def has_promises(self):
        return False

    def has_plot_promises(self):
        return False


class TestHandlersReadLiveCollection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_plot_manager_reads_app_collection(self):
        from appHandlers.appPlotManager import AppPlotManager
        app = SimpleNamespace(log=Mock(), inform=Mock(), options={}, collection=FakeCollection(),
                              worker_task=Mock(), plotcanvas=Mock(), clear_pool=Mock(), app_obj=Mock(),
                              defaults={}, proc_container=Mock())
        manager = AppPlotManager(app)
        second = FakeCollection()
        app.collection = second
        self.assertIs(manager.collection, second)

    def test_edit_handler_reads_app_collection(self):
        from appHandlers.appEdit import appEditor
        app = SimpleNamespace(log=Mock(), inform=Mock(), splash=Mock(), worker_task=Mock(), options={},
                              app_units='MM', defaults={}, collection=FakeCollection(), app_obj=Mock(),
                              decimals=4)
        handler = appEditor(app)
        second = FakeCollection()
        app.collection = second
        self.assertIs(handler.collection, second)


def make_app(collection=None):
    from defaults import AppOptions
    # a merged AppOptions, as in the App: it stores the project keys and sends the other keys to "defaults"
    defaults = {'units': 'MM', 'global_gridx': 1.0}
    return SimpleNamespace(
        collection=collection or FakeCollection(), defaults=defaults,
        options=AppOptions(version='test', baseline=defaults, defaults=defaults), project_filename=None,
        should_we_save=False, all_objects_list=[], inform=Mock(), log=Mock(),
        ui=SimpleNamespace(set_ui_title=Mock()),
        proc_container=SimpleNamespace(get_procs_count=Mock(return_value=0)),
        workers=SimpleNamespace(pending_count=Mock(return_value=0)), call_source='app',
        save_in_progress=False, app_obj=SimpleNamespace(load_batches=set()), plotcanvas=None)


def make_manager(app=None):
    from appHandlers.appProjects import ProjectManager
    app = app or make_app()
    manager = ProjectManager(app, collection_factory=FakeCollection)
    manager.before_switch = Mock()
    manager.deactivate = Mock()
    manager.activate = Mock()
    manager.reset_options = Mock()
    return app, manager


class TestProjectManagerCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_first_project_wraps_the_existing_collection(self):
        app, manager = make_manager()
        self.assertEqual(manager.names(), ['Project_1'])
        self.assertIs(manager.active.collection, app.collection)
        self.assertIs(manager.stack.currentWidget(), app.collection.view)

    def test_get_by_name(self):
        app, manager = make_manager()
        self.assertIs(manager.get_by_name('Project_1'), manager.active)
        self.assertIsNone(manager.get_by_name('Missing'))

    def test_switch_swaps_the_app_state(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.options = {'units': 'IN'}
        second.filename = 'b.FlatPrj'
        second.should_we_save = True
        app.project_filename = 'a.FlatPrj'
        app.should_we_save = False

        self.assertTrue(manager.switch(second))

        self.assertIs(manager.active, second)
        self.assertIs(app.collection, second.collection)
        self.assertEqual(app.options['units'], 'IN')
        self.assertEqual(app.project_filename, 'b.FlatPrj')
        self.assertTrue(app.should_we_save)
        self.assertEqual(app.all_objects_list, [])
        self.assertIs(manager.stack.currentWidget(), second.collection.view)
        # the old state is written back to the old context; only the project keys are kept
        self.assertEqual(first.options, {'units': 'MM'})
        self.assertEqual(first.filename, 'a.FlatPrj')
        self.assertFalse(first.should_we_save)
        manager.deactivate.assert_called_once_with(first)
        manager.activate.assert_called_once_with(second)
        app.ui.set_ui_title.assert_called_with(name='Board_B')

    def test_switch_back_restores_the_first_state(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        manager.switch(second)
        app.options['units'] = 'IN'
        manager.switch(first)
        self.assertEqual(app.options['units'], 'MM')
        self.assertIs(app.collection, first.collection)

    def test_switch_does_not_change_the_application_settings(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.options = {'units': 'IN', 'global_gridx': 9.0}
        manager.switch(second)
        app.options['global_gridx'] = 2.0
        manager.switch(first)
        # an application key is not part of a project: it keeps the last value and is not saved in the context
        self.assertEqual(app.options['global_gridx'], 2.0)
        self.assertEqual(app.defaults['global_gridx'], 2.0)
        self.assertNotIn('global_gridx', second.options)

    def test_switch_without_options_resets_options(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        manager.switch(second)
        manager.reset_options.assert_called_once_with()

    def test_switch_without_visuals(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        manager.switch(second, visuals=False)
        manager.before_switch.assert_not_called()
        manager.deactivate.assert_not_called()
        manager.activate.assert_not_called()
        self.assertIs(app.collection, second.collection)

    def test_switch_without_visuals_keeps_the_saved_views(self):
        # on exit the app saves inactive projects with visuals=False; the canvas keeps the view of the first project
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.view_rect = 'view-B'
        manager._get_view_rect = Mock(return_value='view-A')
        manager.switch(second, visuals=False)
        manager.switch(first, visuals=False)
        self.assertEqual(second.view_rect, 'view-B')
        self.assertEqual(first.view_rect, 'view-A')
        self.assertIs(manager.displayed, first)

    def test_visual_switch_releases_the_displayed_project(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        third = manager.add_context('Board_C')
        manager.switch(second, visuals=False)
        manager.switch(third)
        # the canvas showed the first project, so its shapes are released, not the ones of the second project
        manager.deactivate.assert_called_once_with(first)
        self.assertIs(manager.displayed, third)

    def test_switch_to_active_does_nothing(self):
        app, manager = make_manager()
        self.assertTrue(manager.switch(manager.active))
        manager.deactivate.assert_not_called()

    def test_switch_is_refused_while_busy(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        app.proc_container.get_procs_count.return_value = 1
        self.assertFalse(manager.switch(second))
        self.assertIsNot(manager.active, second)
        app.inform.emit.assert_called()

    def test_is_busy_sources(self):
        app, manager = make_manager()
        self.assertFalse(manager.is_busy())
        app.save_in_progress = True
        self.assertTrue(manager.is_busy())
        app.save_in_progress = False
        # a File -> Save that the GUI has not completed yet (Task 10)
        app.project_save_pending = True
        self.assertTrue(manager.is_busy())
        app.project_save_pending = False
        app.app_obj.load_batches.add(object())
        self.assertTrue(manager.is_busy())
        app.app_obj.load_batches.clear()
        # a task that is queued but not started yet (for example the parse of a project or a plot)
        app.workers.pending_count.return_value = 1
        self.assertTrue(manager.is_busy())

    def test_switch_is_refused_while_an_editor_is_open(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        app.call_source = 'geo_editor'
        self.assertTrue(manager.is_busy())
        self.assertFalse(manager.switch(second))
        self.assertIsNot(manager.active, second)
        self.assertIn('Close the editor first', app.inform.emit.call_args[0][0])

    def test_worker_stack_pending_count(self):
        from appWorkerStack import WorkerStack
        stack = WorkerStack(workers_number=1)
        try:
            self.assertEqual(stack.pending_count(), 0)
            stack._deferred_tasks.append(object())
            self.assertEqual(stack.pending_count(), 1)
        finally:
            stack._deferred_tasks.clear()
            stack.quit()

    def test_projects_changed_is_emitted_on_switch(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        listener = Mock()
        manager.projects_changed.connect(listener)
        manager.switch(second)
        listener.assert_called()


if __name__ == '__main__':
    unittest.main()
