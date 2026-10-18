"""Plugin creation options are applied on successful GUI-thread completion."""

import os
import importlib
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtCore, QtGui, QtWidgets

from appTool import AppTool
from appObjects.AppObject import AppObject
from defaults import AppDefaults


class PluginObjectCreationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.app = SimpleNamespace(
            decimals=4, options={}, defaults=AppDefaults.factory_defaults,
            collection=Mock(), ui=Mock(), log=Mock(), inform=Mock(), worker_task=Mock(),
            all_objects_list=[]
        )
        self.app.ui.notebook.currentWidget.return_value = self.app.ui.plugin_tab
        self.source = SimpleNamespace(obj_options={'name': 'source', 'plot': True}, visible=True)
        self.obj = SimpleNamespace(
            obj_options={'name': 'result'}, kind='geometry', has_plot_colors=False, status_color=None
        )

    def complete(self, hide, switch, source=True):
        self.obj._plugin_creation_context = (self.source if source else None, hide, switch)
        holder = SimpleNamespace(app=self.app)
        AppObject.on_object_created(holder, self.obj, False, False, None, [])

    def test_success_hides_only_primary_source_and_switches_after_selection(self):
        reference = SimpleNamespace(obj_options={'plot': True}, visible=True)
        self.complete(True, True)
        self.assertFalse(self.source.obj_options['plot'])
        self.assertFalse(self.source.visible)
        self.assertTrue(reference.visible)
        self.app.collection.set_active.assert_called_once_with('result')
        self.app.ui.notebook.setCurrentWidget.assert_called_once_with(self.app.ui.properties_tab)

    def test_disabled_options_do_nothing(self):
        self.complete(False, False)
        self.assertTrue(self.source.visible)
        self.assertTrue(self.source.obj_options['plot'])
        self.app.ui.notebook.setCurrentWidget.assert_not_called()

    def test_independent_options_and_no_source(self):
        self.complete(True, False)
        self.assertFalse(self.source.visible)
        self.app.ui.notebook.setCurrentWidget.assert_not_called()
        self.app.collection.reset_mock()
        self.complete(False, True, source=False)
        self.app.collection.set_active.assert_called_once_with('result')
        self.app.ui.notebook.setCurrentWidget.assert_called_once_with(self.app.ui.properties_tab)

    def test_controls_use_preferences_and_survive_switching_plugins(self):
        self.app.options.update(global_object_autohide=False, global_object_autoswitch=True)
        tool = AppTool(self.app)
        tool.ui = SimpleNamespace()
        tool.add_object_creation_controls()
        self.assertFalse(tool.ui.object_autohide_cb.get_value())
        self.assertTrue(tool.ui.object_autoswitch_cb.get_value())
        tool.ui.object_autohide_cb.set_value(True)
        self.app.app_obj = Mock()
        self.app.app_obj.new_object.side_effect = lambda kind, name, init, **kw: init(self.obj, self.app)
        tool.new_object('geometry', 'result', lambda obj, app: None, source=self.source)
        self.app.ui.plugin_scroll_area.setWidget(Mock())
        self.assertEqual(self.obj._plugin_creation_context, (self.source, True, True))

    def test_sourceless_plugin_only_has_autoswitch(self):
        tool = AppTool(self.app)
        tool.ui = SimpleNamespace()
        tool.add_object_creation_controls(has_source=False)
        self.assertFalse(hasattr(tool.ui, 'object_autohide_cb'))
        self.assertTrue(tool.ui.object_autoswitch_cb.get_value())

    def test_failed_initialization_does_not_hide_or_switch(self):
        tool = AppTool(self.app)
        tool.ui = SimpleNamespace()
        tool.add_object_creation_controls()
        self.app.app_obj = Mock()
        self.app.app_obj.new_object.side_effect = lambda kind, name, init, **kw: init(self.obj, self.app)
        self.assertEqual(tool.new_object('geometry', 'bad', lambda obj, app: 'fail',
                                         source=self.source), 'fail')
        self.assertTrue(self.source.visible)
        self.app.ui.notebook.setCurrentWidget.assert_not_called()

    def test_defaults_are_on(self):
        self.assertIs(AppDefaults.factory_defaults['global_object_autohide'], True)
        self.assertIs(AppDefaults.factory_defaults['global_object_autoswitch'], True)

    def test_programmatic_generation_without_controls_keeps_factory_behavior(self):
        tool = AppTool(self.app)
        self.app.app_obj = Mock()
        initialize = Mock()
        tool.new_object('geometry', 'scripted', initialize, source=self.source)
        self.app.app_obj.new_object.assert_called_once_with('geometry', 'scripted', initialize)

    def test_explicit_tcl_generation_keeps_factory_behavior(self):
        tool = AppTool(self.app)
        tool.ui = SimpleNamespace()
        tool.add_object_creation_controls()
        self.app.app_obj = Mock()
        initialize = Mock()
        tool.new_object('geometry', 'scripted', initialize, source=self.source, from_tcl=True)
        self.app.app_obj.new_object.assert_called_once_with('geometry', 'scripted', initialize)

    def test_reset_reloads_preferences_without_duplicating_controls(self):
        tool = AppTool(self.app)
        tool.ui = SimpleNamespace()
        tool.add_object_creation_controls()
        checkbox = tool.ui.object_autohide_cb
        checkbox.set_value(False)
        tool.reset_object_creation_controls()
        self.assertIs(tool.ui.object_autohide_cb, checkbox)
        self.assertTrue(checkbox.get_value())
        self.assertTrue(tool.object_autohide)

    def test_controls_fit_every_generating_plugin_ui(self):
        cases = (
            ('ToolCopperThieving', 'ThievingUI'), ('ToolCutOut', 'CutoutUI'),
            ('ToolDblSided', 'DsidedUI'), ('ToolDrilling', 'DrillingUI'),
            ('ToolEtchCompensation', 'EtchUI'), ('ToolExtract', 'ExtractUI'),
            ('ToolFiducials', 'FidoUI'), ('ToolFilm', 'FilmUI'), ('ToolFollow', 'FollowUI'),
            ('ToolImage', 'ImageUI'), ('ToolInvertGerber', 'InvertUI'), ('ToolIsolation', 'IsoUI'),
            ('ToolLevelling', 'LevelUI'), ('ToolMarkers', 'MarkersUI'), ('ToolMilling', 'MillingUI'),
            ('ToolNCC.NccUI', 'NccUI'), ('ToolPaint.PaintUI', 'PaintUI'),
            ('ToolPanelize', 'PanelizeUI'), ('ToolPcbWizard', 'WizardUI'),
            ('ToolPunchGerber', 'PunchUI'), ('ToolRulesCheck', 'RulesUI'),
            ('ToolSolderPaste', 'SolderUI'), ('ToolSub', 'SubUI')
        )
        for module, name in cases:
            with self.subTest(plugin=module):
                app = MagicMock()
                app.decimals = 4
                app.options = dict(AppDefaults.factory_defaults)
                app.defaults = AppDefaults()
                app.app_units = 'MM'
                app.resource_location = os.path.abspath('assets/resources')
                app.collection = QtGui.QStandardItemModel()
                tool = AppTool(app)
                kwargs = {'name': name} if name in ('DrillingUI', 'MillingUI') else {}
                if name == 'SolderUI':
                    kwargs['solder_class'] = Mock()
                ui_class = getattr(importlib.import_module('appPlugins.' + module), name)
                tool.ui = ui_class(layout=tool.layout, app=app, **kwargs)
                tool.add_object_creation_controls(has_source=name not in (
                    'DsidedUI', 'ImageUI', 'WizardUI', 'RulesUI'))
                self.assertTrue(tool.ui.object_autoswitch_cb.get_value())
                self.assertFalse(tool.ui.object_autoswitch_cb.isHidden())
                if hasattr(tool.ui, 'object_autohide_cb'):
                    self.assertTrue(tool.ui.object_autohide_cb.get_value())
                    self.assertFalse(tool.ui.object_autohide_cb.isHidden())
                tool.deleteLater()

    def test_worker_creation_uses_captured_options_on_gui_thread_only_after_success(self):
        class Result(QtCore.QObject):
            tool_option_prefix = None
            inherits_mill_options = False
            has_plot_colors = False
            status_color = None
            kind = 'geometry'

            def __init__(self, name, app):
                super().__init__()
                self.obj_options = {'name': name}

            def bounds(self):
                return 0, 0, 1, 1

        self.app.options['units'] = 'MM'
        self.app.main_thread = QtCore.QThread.currentThread()
        self.app.on_plots_updated = Mock()
        self.app.inform_shell = Mock()
        self.app.app_obj = AppObject(self.app)
        self.app.collection.append.side_effect = lambda obj: self.assertIs(
            QtCore.QThread.currentThread(), self.app.main_thread)
        tool = AppTool(self.app)
        tool.ui = SimpleNamespace()
        tool.add_object_creation_controls()
        results = []
        with patch('appObjects.AppObject.GeometryObject', Result):
            for failed in (True, False):
                worker = threading.Thread(target=lambda: results.append(tool.new_object(
                    'geometry', 'result', lambda obj, app: 'fail' if failed else None,
                    source=self.source, plot=False, autoselected=False)))
                worker.start()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(self.source.visible)
                if failed:
                    self.assertEqual(results[-1], 'fail')
                    self.qt_app.processEvents()
                    self.app.collection.append.assert_not_called()
                    self.app.ui.notebook.setCurrentWidget.assert_not_called()
            tool.ui.object_autohide_cb.set_value(False)
            tool.ui.object_autoswitch_cb.set_value(False)
            self.qt_app.processEvents()
        self.assertFalse(self.source.visible)
        self.app.collection.set_active.assert_called_once_with('result')
        self.app.ui.notebook.setCurrentWidget.assert_called_once_with(self.app.ui.properties_tab)

    def test_preferences_bindings_placement_and_save_load(self):
        from appGUI.preferences.OptionsGroupUI import OptionsGroupUI
        from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI
        from appGUI.preferences.PreferencesUIManager import PreferencesUIManager

        defaults = AppDefaults(beta=False)
        app = MagicMock()
        app.decimals = 4
        app.resource_location = os.path.abspath('assets/resources')
        app.options = dict(defaults.items())
        with patch.object(OptionsGroupUI, 'app', app):
            group = GeneralGUIPrefGroupUI(app)
        self.addCleanup(group.deleteLater)
        ui = MagicMock()
        ui.app = app
        ui.general_pref_form.general_gui_group = group
        with tempfile.TemporaryDirectory() as path:
            manager = PreferencesUIManager(defaults, path, ui, Mock(), app.options)
            self.addCleanup(manager.deleteLater)
            fields = {key: manager.defaults_form_fields[key] for key in (
                'global_project_autohide', 'global_object_autohide', 'global_object_autoswitch')}
            manager.defaults_form_fields = fields
            parameter_frame = group.custom_titlebar_cb.parentWidget()
            for key, checkbox in fields.items():
                self.assertIs(checkbox.parentWidget(), parameter_frame)
                manager.defaults_write_form_field(key)
                self.assertTrue(checkbox.get_value())
                checkbox.set_value(False)
            manager.defaults_read_form()
            manager.save_defaults(silent=True)
            restored = AppDefaults(beta=False)
            restored.load(os.path.join(path, 'current_defaults.FlatConfig'), inform=Mock())
            for key in fields:
                self.assertIs(restored[key], False)


if __name__ == '__main__':
    unittest.main()
