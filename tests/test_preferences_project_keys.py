"""The Preferences form shows and saves the project keys of the active project."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


if __name__ == '__main__':
    unittest.main()
