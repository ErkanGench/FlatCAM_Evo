"""Application text is translated at its literal definition, before formatting or display."""

import ast
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6 import QtWidgets
from appDatabase import normalize_tools_database
from defaults import AppDefaults


class TranslationLiteralChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_gettext_arguments_are_literal_strings(self):
        problems = []
        for name in ('appDatabase.py', 'appGUI/preferences/OptionUI.py',
                     'appGUI/preferences/general/GeneralAppSettingsGroupUI.py',
                     'appParsers/ParseGerber.py', 'appPlugins/ToolGrblSender/SenderMotion.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_':
                    if (len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or
                            not isinstance(node.args[0].value, str)):
                        problems.append('%s:%d' % (name, node.lineno))
        self.assertEqual([], problems)

    def test_preferences_labels_and_tooltips_are_extractable(self):
        path = ROOT / 'appGUI/preferences/general/GeneralAppSettingsGroupUI.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        marked = {node.args[0].value for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_'
                  and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)}
        self.assertIn('Multiple Selection', marked)
        self.assertIn('This sets the font size for canvas axis.', marked)
        unmarked = [(keyword.arg, keyword.value.lineno) for node in ast.walk(tree)
                    if isinstance(node, ast.Call) for keyword in node.keywords
                    if keyword.arg in ('label_text', 'label_tooltip')
                    and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)]
        self.assertEqual([], unmarked)

    def test_widgets_display_supplied_translations_unchanged(self):
        options = importlib.import_module('appGUI.preferences.OptionUI')
        with patch.object(options, '_', side_effect=AssertionError('Text was translated twice'), create=True):
            for option_class in (options.LineEntryOptionUI, options.TextAreaOptionUI,
                                 options.CheckboxOptionUI, options.FullWidthButtonOptionUI):
                with self.subTest(widget=option_class.__name__):
                    option = option_class('test', 'Translated label', 'Translated tooltip')
                    widget = getattr(option, 'label_widget', option.get_field())
                    self.addCleanup(widget.deleteLater)
                    self.addCleanup(option.get_field().deleteLater)
                    self.assertIn('Translated label', widget.text())
                    self.assertEqual('Translated tooltip', widget.toolTip())
                    if isinstance(option, options.TextAreaOptionUI):
                        self.assertEqual('Translated tooltip', option.get_field().placeholderText())
            heading = options.HeadingOptionUI('Translated heading').build_heading_widget()
            self.addCleanup(heading.deleteLater)
            self.assertEqual('Translated heading', heading.text())

    def test_preferences_translate_at_the_call_site(self):
        preferences = importlib.import_module('appGUI.preferences.general.GeneralAppSettingsGroupUI')
        holder = SimpleNamespace(decimals=4, pagesize={'A4': (210, 297)})
        with patch.object(preferences, '_', side_effect=lambda text: 'Translated ' + text, create=True):
            options = preferences.GeneralAppSettingsGroupUI.build_options(holder)
        for option in options:
            if hasattr(option, 'label_text'):
                self.assertTrue(option.label_text.startswith('Translated '))
            if getattr(option, 'label_tooltip', None) is not None:
                self.assertTrue(option.label_tooltip.startswith('Translated '))
            if option.get_field() is not None:
                self.addCleanup(option.get_field().deleteLater)
            if hasattr(option, 'label_widget'):
                self.addCleanup(option.label_widget.deleteLater)
        workspace = next(option for option in options if option.option == 'global_workspaceT')
        self.assertEqual('A4', workspace.get_field().currentText())

    def test_database_accepts_canonical_and_translated_legacy_labels(self):
        defaults = AppDefaults.factory_defaults
        for translated in (False, True):
            with self.subTest(translated=translated):
                labels = {'tool_target': 'Milling', 'tools_mill_job_type': 'Finishing',
                          'tools_mill_offset_type': 'Out', 'tools_cutout_gap_type': 'Bridge'}
                data = {key: 'Translated ' + value if translated else value for key, value in labels.items()}
                data['tools_mill_tool_shape'] = 'C1'
                source = {'1': {'name': 'fixture', 'tooldia': 1.0, 'data': data}}
                with patch('appDatabase._', side_effect=lambda text: 'Translated ' + text, create=True):
                    result = normalize_tools_database(source, defaults)['1']['data']
                for key, expected in (('tool_target', 1), ('tools_mill_job_type', 1),
                                      ('tools_mill_offset_type', 2), ('tools_cutout_gap_type', 0),
                                      ('tools_mill_tool_shape', 0)):
                    self.assertEqual(expected, result[key])
                self.assertEqual(data, source['1']['data'])

    def test_gerber_message_is_translated_before_formatting(self):
        parser_module = importlib.import_module('appParsers.ParseGerber')
        text = ('Gerber implementation format not supported. Undefined aperture at line: %s. '
                'Report to developers.')
        messages = []
        parser = SimpleNamespace(tools={}, app=SimpleNamespace(inform=SimpleNamespace(emit=messages.append)))
        with patch.object(parser_module, '_', side_effect=lambda message: {
                text: 'Translated undefined aperture at line %s.'}.get(message, message), create=True):
            parser_module.Gerber._handle_region_start(
                parser, [[0.0, 0.0], [1.0, 0.0]], None, [], [], 4, 12, None)
        self.assertEqual(['[ERROR] Translated undefined aperture at line 12.'], messages)


if __name__ == '__main__':
    unittest.main()
