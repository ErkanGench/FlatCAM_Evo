"""The Preferences form shows and saves the project keys of the active project, and the values it keeps valid."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtCore

from appGUI.preferences.PreferencesUIManager import PreferencesUIManager
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


class TestPreferencesColors(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
