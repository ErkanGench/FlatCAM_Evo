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


class TestProjectManagerLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_new_adds_a_unique_project_and_activates_it(self):
        app, manager = make_manager()
        ctx = manager.new()
        self.assertEqual(manager.names(), ['Project_1', 'Project_2'])
        self.assertIs(manager.active, ctx)
        self.assertIs(app.collection, ctx.collection)

    def test_new_is_refused_while_busy(self):
        app, manager = make_manager()
        app.save_in_progress = True
        self.assertIsNone(manager.new())
        self.assertEqual(manager.names(), ['Project_1'])

    def test_rename(self):
        app, manager = make_manager()
        manager.new()
        self.assertTrue(manager.rename(manager.active, ' Board_B '))
        self.assertEqual(manager.active.name, 'Board_B')
        app.ui.set_ui_title.assert_called_with(name='Board_B')

    def test_rename_refuses_a_used_name(self):
        app, manager = make_manager()
        manager.new()
        self.assertFalse(manager.rename(manager.active, 'Project_1'))
        self.assertEqual(manager.active.name, 'Project_2')

    def test_rename_refuses_a_name_that_is_not_valid(self):
        app, manager = make_manager()
        self.assertFalse(manager.rename(manager.active, 'a/b'))
        self.assertFalse(manager.rename(manager.active, ''))

    def test_is_dirty_needs_changes_and_objects(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        self.assertFalse(manager.is_dirty(manager.active))
        app.should_we_save = True
        self.assertTrue(manager.is_dirty(manager.active))
        self.assertEqual(manager.dirty_contexts(), [manager.active])

    def test_saved_project_with_all_objects_deleted_is_dirty(self):
        # the deletion of all the objects of a saved project is a change that must be saved
        app, manager = make_manager()
        app.should_we_save = True
        self.assertFalse(manager.is_dirty(manager.active))
        app.project_filename = os.path.join('folder', 'Project_1.FlatPrj')
        self.assertTrue(manager.is_dirty(manager.active))
        # so the GUI close asks and the Tcl close needs -force
        self.assertFalse(manager.close(manager.active))
        self.assertTrue(manager.close(manager.active, force=True))

    def test_close_inactive_project(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.new()
        self.assertTrue(manager.close(first))
        self.assertEqual(manager.names(), ['Project_2'])
        self.assertIs(manager.active, second)
        self.assertEqual(manager.stack.count(), 1)

    def test_close_active_project_activates_the_previous_one(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.new()
        self.assertTrue(manager.close(second))
        self.assertIs(manager.active, first)
        self.assertEqual(manager.names(), ['Project_1'])

    def test_close_last_project_leaves_one_empty_project(self):
        app, manager = make_manager()
        first = manager.active
        self.assertTrue(manager.close(first))
        self.assertEqual(len(manager.contexts), 1)
        self.assertIsNot(manager.active, first)
        self.assertEqual(manager.active.name, 'Project_2')

    def test_close_refuses_a_dirty_project_without_force(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.should_we_save = True
        self.assertFalse(manager.close(manager.active))
        self.assertTrue(manager.close(manager.active, force=True))

    def test_save_target_without_file(self):
        app, manager = make_manager()
        self.assertIsNone(manager.save_target())

    def test_save_target_same_name(self):
        app, manager = make_manager()
        path = os.path.join('folder', 'Project_1.FlatPrj')
        app.project_filename = path
        self.assertEqual(manager.save_target(), path)

    def test_save_target_after_rename(self):
        app, manager = make_manager()
        app.project_filename = os.path.join('folder', 'Project_1.FlatPrj')
        manager.rename(manager.active, 'Board_B')
        self.assertEqual(manager.save_target(), os.path.join('folder', 'Board_B.FlatPrj'))

    def test_adopt_filename_renames_the_active_project(self):
        app, manager = make_manager()
        manager.new()
        manager.rename(manager.active, 'Board')
        manager.switch(manager.contexts[0])
        manager.adopt_filename(os.path.join('folder', 'Board.FlatPrj'))
        self.assertEqual(manager.active.name, 'Board_1')
        self.assertEqual(manager.active.filename, os.path.join('folder', 'Board.FlatPrj'))

    def test_find_by_filename_uses_the_live_filename(self):
        app, manager = make_manager()
        app.project_filename = os.path.join('folder', 'Board.FlatPrj')
        self.assertIs(manager.find_by_filename(os.path.join('folder', '.', 'Board.FlatPrj')), manager.active)
        self.assertIsNone(manager.find_by_filename(os.path.join('folder', 'Other.FlatPrj')))


def make_object(kind='gerber', with_ui=True):
    obj = SimpleNamespace(kind=kind, clear=Mock(), mark_shapes=Mock(), _full_plot_sig=(1, 2, 3),
                          ui=QtWidgets.QWidget() if with_ui else None, ui_type=Mock(return_value='new-ui'),
                          set_ui=Mock(), build_ui=Mock())
    return obj


class TestProjectManagerVisuals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make(self, objects):
        from appHandlers.appProjects import ProjectManager
        app = make_app(FakeCollection(objects))
        app.setup_default_properties_tab = Mock()
        app.init_tools = Mock()
        app.plot_all = Mock()
        app.plotcanvas = SimpleNamespace(redraw=Mock(), view=SimpleNamespace(camera=SimpleNamespace(rect=None)))
        app.preferencesUiManager = Mock()
        app.on_defaults2options = Mock()
        manager = ProjectManager(app, collection_factory=FakeCollection)
        return app, manager

    def test_reset_options_copies_the_project_keys_from_the_defaults(self):
        app, manager = self.make([])
        manager.reset_options()
        app.on_defaults2options.assert_called_once_with()

    def test_deactivate_releases_shapes_and_keeps_the_ui(self):
        gerber = make_object('gerber')
        script = make_object('script')
        app, manager = self.make([gerber, script])
        gerber_ui = gerber.ui

        manager.deactivate(manager.active)

        gerber.clear.assert_called_once_with(update=False)
        gerber.mark_shapes.clear.assert_called_once_with(update=False)
        self.assertIsNone(gerber._full_plot_sig)
        # the Properties UI stays; set_ui() is not safe to run again
        self.assertIs(gerber.ui, gerber_ui)
        # Script and Document objects have no shapes
        script.clear.assert_not_called()
        self.assertIsNotNone(script.ui)
        app.setup_default_properties_tab.assert_called_once_with()
        app.plotcanvas.redraw.assert_called_once_with()

    def test_activate_plots_and_does_not_rebuild_the_ui(self):
        gerber = make_object('gerber')
        app, manager = self.make([gerber])
        manager.active.view_rect = 'saved-rect'

        manager.activate(manager.active)

        gerber.ui_type.assert_not_called()
        gerber.set_ui.assert_not_called()
        gerber.build_ui.assert_not_called()
        app.init_tools.assert_called_once_with(init_tcl=False)
        app.plot_all.assert_called_once_with(fit_view=False)
        self.assertEqual(app.plotcanvas.view.camera.rect, 'saved-rect')
        # the Preferences form shows the project keys of the new active project
        app.preferencesUiManager.defaults_write_form.assert_called_once_with()

    def test_activate_of_an_empty_project_does_not_plot(self):
        app, manager = self.make([])
        manager.activate(manager.active)
        app.plot_all.assert_not_called()
        app.init_tools.assert_called_once_with(init_tcl=False)

    def test_activate_does_not_build_a_missing_ui(self):
        # an object without a UI is left as it is; set_ui() runs only when the object is made
        gerber = make_object('gerber', with_ui=False)
        app, manager = self.make([gerber])
        manager.activate(manager.active)
        gerber.set_ui.assert_not_called()

    def test_before_switch_clears_the_canvas_helpers(self):
        app, manager = self.make([])
        app.call_source = 'app'
        app.tool_shapes = Mock()
        app.hover_shapes = Mock()
        app.exc_areas = Mock()
        app.delete_selection_shape = Mock()

        manager.before_switch()

        app.tool_shapes.clear.assert_called_once_with(update=True)
        app.hover_shapes.clear.assert_called_once_with(update=True)
        app.exc_areas.clear_shapes.assert_called_once_with()
        app.delete_selection_shape.assert_called_once_with()

    def test_before_switch_never_closes_an_editor(self):
        # a switch is refused while an editor is open (is_busy); before_switch must not drop editor changes
        app, manager = self.make([])
        app.call_source = 'app'
        app.on_editing_finished = Mock()
        app.tool_shapes = None
        app.hover_shapes = None
        app.exc_areas = None
        app.delete_selection_shape = Mock()
        manager.before_switch()
        app.on_editing_finished.assert_not_called()


if __name__ == '__main__':
    unittest.main()
