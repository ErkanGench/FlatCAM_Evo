"""The Preferences form shows and saves the project keys of the active project, and the values it keeps valid."""
import builtins
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtCore, QtWidgets

from appGUI.preferences.OptionsGroupUI import OptionsGroupUI
from appGUI.preferences.PreferencesUIManager import PreferencesUIManager
from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI
from appHandlers.appUIActions import AppUIActions
from defaults import AppDefaults, AppOptions


class Field:
    def __init__(self, value=None):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


def make_manager():
    defaults = AppDefaults(beta=False)
    options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    manager = PreferencesUIManager.__new__(PreferencesUIManager)
    QtCore.QObject.__init__(manager)
    manager.defaults = defaults
    manager.ui = SimpleNamespace(app=SimpleNamespace(options=options, log=Mock()))
    manager.preferences_changed_flag = False
    manager.defaults_form_fields = {
        'gerber_bboxmargin': Field(), 'gerber_bboxrounded': Field(), 'global_gridx': Field()}
    return manager, defaults, options


def make_group(group_class):
    """A real Preferences group on a mock App; the options write the application keys to the defaults."""
    defaults = AppDefaults(beta=False)
    app = MagicMock(decimals=4, resource_location='assets/resources')
    app.defaults = defaults
    app.options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    with patch.object(OptionsGroupUI, 'app', app):
        group = group_class(app)
    group.app = app     # the handlers read OptionsGroupUI.app, which the App sets
    return group, app, defaults


class TestPreferencesProjectKeys(unittest.TestCase):
    def test_form_shows_project_value_for_project_key(self):
        manager, defaults, options = make_manager()
        defaults['gerber_bboxmargin'] = 0.1
        options['gerber_bboxmargin'] = 0.5
        defaults['global_gridx'] = 2.0
        manager.defaults_write_form()
        self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.5)
        self.assertEqual(manager.defaults_form_fields['global_gridx'].value, 2.0)

    def test_change_of_options_writes_the_project_value(self):
        manager, defaults, options = make_manager()
        defaults['gerber_bboxmargin'] = 0.1
        options['gerber_bboxmargin'] = 0.5
        manager.defaults_write_form_field('gerber_bboxmargin')
        self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.5)

    def test_read_form_writes_only_changed_project_keys(self):
        manager, defaults, options = make_manager()
        defaults['gerber_bboxmargin'] = 0.1
        defaults['gerber_bboxrounded'] = False
        options['gerber_bboxmargin'] = 0.5
        options['gerber_bboxrounded'] = True
        fields = manager.defaults_form_fields
        fields['gerber_bboxmargin'].value = 0.7
        fields['gerber_bboxrounded'].value = True
        fields['global_gridx'].value = 2.5
        manager.defaults_read_form()
        self.assertEqual(options['gerber_bboxmargin'], 0.7)
        self.assertEqual(defaults['gerber_bboxmargin'], 0.7)
        self.assertIs(options['gerber_bboxrounded'], True)
        self.assertIs(defaults['gerber_bboxrounded'], False)
        self.assertEqual(defaults['global_gridx'], 2.5)

    def test_show_writes_the_form_when_there_are_no_edits(self):
        manager, _defaults, options = make_manager()
        options['gerber_bboxmargin'] = 0.5
        with patch.object(PreferencesUIManager, 'init_preferences_gui'), \
                patch.object(PreferencesUIManager, 'pref_connect'), \
                patch.object(PreferencesUIManager, '_PreferencesUIManager__init_color_pickers'):
            manager.show_preferences_gui()
            self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.5)
            manager.defaults_form_fields['gerber_bboxmargin'].value = 0.9
            manager.preferences_changed_flag = True
            manager.show_preferences_gui()
        self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.9)


class TestPreferencesClose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_closing_with_the_toggle_asks_and_drops_unsaved_edits(self):
        manager, defaults, _options = make_manager()
        manager.ui = MagicMock(app=manager.ui.app)
        manager.ui.app.resource_location = 'assets/resources'
        manager.ui.pref_tab_area.count.return_value = 0
        manager.ignore_tab_close_event = False
        manager.inform = Mock()
        defaults['global_gridx'] = 2.0
        tabs = QtWidgets.QTabWidget()
        self.addCleanup(tabs.deleteLater)
        tabs.addTab(QtWidgets.QWidget(), builtins._('Preferences'))
        actions = SimpleNamespace(ui=SimpleNamespace(plot_tab_area=tabs, pref_status_label=Mock()), log=Mock(),
                                  app=SimpleNamespace(preferencesUiManager=manager))
        manager.defaults_form_fields['global_gridx'].value = 9.0    # edited, not saved
        manager.preferences_changed_flag = True
        dialog = MagicMock()
        dialog.addButton.side_effect = [object(), object()]    # 'Yes', 'No'; the answer is not 'Yes'
        with patch('appGUI.preferences.PreferencesUIManager.FCMessageBox', return_value=dialog), \
                patch.object(PreferencesUIManager, 'init_preferences_gui'), \
                patch.object(PreferencesUIManager, 'pref_connect'), \
                patch.object(PreferencesUIManager, '_PreferencesUIManager__init_color_pickers'):
            AppUIActions.on_toggle_preferences(actions)
            dialog.exec.assert_called_once()
            self.assertEqual(tabs.count(), 0)
            manager.show_preferences_gui()    # opened again
        self.assertEqual(manager.defaults_form_fields['global_gridx'].value, 2.0)


class TestPreferencesColors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_colours_without_a_readable_alpha_do_not_stop_the_preferences(self):
        manager, defaults, _options = make_manager()
        manager.ui = MagicMock(app=manager.ui.app)
        defaults['gerber_plot_fill'] = '#FF0000'    # typed with 6 digits and saved
        defaults['excellon_plot_fill'] = '#FF00'
        defaults['global_sel_fill'] = 'bf'
        manager._PreferencesUIManager__init_color_pickers()
        ui = manager.ui
        ui.gerber_pref_form.gerber_gen_group.gerber_alpha_entry.set_value.assert_called_once_with(255)
        ui.excellon_pref_form.excellon_gen_group.excellon_alpha_entry.set_value.assert_called_once_with(0xBF)
        ui.general_pref_form.general_gui_group.left_right_alpha_entry.set_value.assert_called_once_with(0xBF)

    def test_save_keeps_the_alpha_of_a_colour(self):
        manager, defaults, _options = make_manager()
        defaults['gerber_plot_fill'] = '#BBF26880'
        manager.defaults_form_fields = {
            'gerber_plot_fill': Field('#FF0000'), 'excellon_plot_fill': Field('#FF00'),
            'global_sel_line': Field('#00FF0040'), 'global_draw_color': Field('#FF0000')}
        manager.defaults_read_form()
        self.assertEqual(defaults['gerber_plot_fill'], '#FF000080')
        self.assertEqual(defaults['excellon_plot_fill'], defaults.factory_defaults['excellon_plot_fill'])
        self.assertEqual(defaults['global_sel_line'], '#00FF0040')
        self.assertEqual(defaults['global_draw_color'], '#FF0000')

    def test_selection_fill_colour_keeps_the_colour_and_its_alpha(self):
        group, app, _defaults = make_group(GeneralGUIPrefGroupUI)
        self.addCleanup(group.deleteLater)
        group.sf_color_entry.set_value('#112233FF')    # as the colour dialog sets it
        group.sf_color_entry.editingFinished.emit()
        self.assertEqual(app.options['global_sel_fill'], '#112233bf')

    def test_opening_keeps_the_right_to_left_selection_alpha(self):
        group, app, defaults = make_group(GeneralGUIPrefGroupUI)
        self.addCleanup(group.deleteLater)
        manager = make_manager()[0]
        manager.defaults = defaults
        manager.ui = MagicMock(app=app)
        manager.ui.general_pref_form.general_gui_group = group
        defaults['global_alt_sel_fill'] = '#BBF26840'
        defaults['global_alt_sel_line'] = '#006E2040'
        manager._PreferencesUIManager__init_color_pickers()
        self.assertEqual(group.right_left_alpha_entry.get_value(), 0x40)
        self.assertEqual(app.options['global_alt_sel_fill'], '#BBF26840')
        self.assertEqual(app.options['global_alt_sel_line'], '#006E2040')


if __name__ == '__main__':
    unittest.main()
