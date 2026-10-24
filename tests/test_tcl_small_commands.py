"""Small Tcl commands: help, open_gerber argument check and set_sys."""
import os
import sys
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tclCommands.TclCommandHelp as TclCommandHelpModule
from defaults import AppDefaults, AppOptions
from tclCommands.TclCommandHelp import TclCommandHelp
from tclCommands.TclCommandOpenGerber import TclCommandOpenGerber
from tclCommands.TclCommandSetSys import TclCommandSetSys


class ShownText(HTMLParser):
    """The text of an HTML fragment as the shell shows it: the tags are dropped and the entities decoded."""

    def __init__(self, fragment):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(fragment)
        self.close()

    @property
    def text(self):
        return ''.join(self.parts)

    def handle_data(self, data):
        self.parts.append(data)


class TestTclHelp(unittest.TestCase):
    def test_help_without_a_name_lists_commands_and_the_usage_hint(self):
        shell = SimpleNamespace(tcl_commands_storage={'open_gerber': {'description': 'Open a Gerber file.'}},
                                append_raw=mock.Mock())
        command = SimpleNamespace(app=SimpleNamespace(shell=shell, log=mock.Mock()))
        with mock.patch.object(TclCommandHelpModule, '_', lambda text: text, create=True):
            TclCommandHelp.execute(command, {}, [])
        shown = ShownText(shell.append_raw.call_args[0][0]).text
        self.assertIn('Type help <command_name> for usage.', shown)
        self.assertIn('open_gerber', shown.split('Type help')[0])


def test_open_gerber_missing_filename_reports_error_without_crashing():
    command = TclCommandOpenGerber.__new__(TclCommandOpenGerber)
    command.raise_tcl_error = Mock()
    args, unnamed_args = command.check_args(())
    command.execute(args, unnamed_args)
    command.raise_tcl_error.assert_called_once_with("Missing required argument 'filename'.")


def make_set_sys_command():
    defaults = AppDefaults(beta=False)
    options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    app = SimpleNamespace(defaults=defaults, options=options)
    return SimpleNamespace(app=app, raise_tcl_error=Mock()), defaults, options


class TestTclSetSys(unittest.TestCase):
    def test_application_key_goes_to_defaults_and_propagates(self):
        command, defaults, _options = make_set_sys_command()
        with patch.object(AppDefaults, 'propagate_defaults') as propagate:
            TclCommandSetSys.execute(command, {'name': 'global_gridx', 'value': 2.5}, [])
        self.assertEqual(defaults['global_gridx'], 2.5)
        propagate.assert_called_once_with()
        command.raise_tcl_error.assert_not_called()

    def test_project_key_goes_to_project_and_converts_tcl_words(self):
        command, defaults, options = make_set_sys_command()
        before = defaults['units']
        TclCommandSetSys.execute(command, {'name': 'units', 'value': 'in' if before == 'MM' else 'mm'}, [])
        self.assertEqual(options['units'], 'IN' if before == 'MM' else 'MM')
        self.assertEqual(defaults['units'], before)
        command.raise_tcl_error.assert_not_called()

    def test_unknown_key_is_an_error(self):
        command, _defaults, _options = make_set_sys_command()
        TclCommandSetSys.execute(command, {'name': 'no_such_key', 'value': '1'}, [])
        command.raise_tcl_error.assert_called_once()


# ---- check_rules --------------------------------------------------------------------------------------------------
def make_check_rules(tmp_objects):
    from tclCommands.TclCommandCheckRules import TclCommandCheckRules
    from test_tcl_audit_regressions import object_app
    app = object_app(None)
    app.collection.get_by_name.side_effect = tmp_objects.get
    app.app_obj = Mock()
    return TclCommandCheckRules(app), app


def rules_objects():
    from shapely import Point, box
    top = SimpleNamespace(obj_options={'name': 'top.gtl'}, tools={},
                          solid_geometry=[box(0, 0, 1, 1), box(1.1, 0, 2, 1)])
    exc = SimpleNamespace(obj_options={'name': 'drl'}, solid_geometry=[],
                          tools={1: {'tooldia': 0.3, 'drills': [Point(0, 0), Point(1, 0)], 'slots': []}})
    return {'top.gtl': top, 'drl': exc}


def test_check_rules_counts_violations_per_rule():
    command, _app = make_check_rules(rules_objects())
    text = command.execute({'copper_top': 'top.gtl', 'exc_1': 'drl', 'c2c': 0.2, 'dh': 0.5, 'h2h': 0.1}, [])
    lines = text.splitlines()
    assert any('FAILED (1)' in line for line in lines if 'lear' in line and 'Copper' in line)
    assert any('FAILED (2)' in line for line in lines if 'Drill' in line)
    assert any('PASSED' in line for line in lines if 'Hole' in line)
    assert lines[-1].endswith('3')


def test_check_rules_unknown_object_and_no_rule_are_tcl_errors():
    from test_tcl_audit_regressions import FCShell
    command, _app = make_check_rules(rules_objects())
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'copper_top': 'nope', 'c2c': 0.2}, [])
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'copper_top': 'top.gtl'}, [])
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'c2c': 0.2}, [])  # rule enabled without its layer


def test_check_rules_writes_csv_and_a_document_without_plotting(tmp_path):
    import csv
    command, app = make_check_rules(rules_objects())
    path = tmp_path / 'report.csv'
    command.execute({'copper_top': 'top.gtl', 'c2c': 0.2, 'csv': str(path), 'outname': 'drc'}, [])
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    assert rows[0] == ['rule', 'layer', 'x', 'y', 'value', 'limit', 'status']
    assert len(rows) == 2 and rows[1][-1] == 'FAILED' and abs(float(rows[1][4]) - 0.1) < 1e-6
    args, kwargs = app.app_obj.new_object.call_args
    assert args[0] == 'document' and args[1] == 'drc' and kwargs['plot'] is False
    doc = SimpleNamespace()
    args[2](doc, app)
    assert 'FAILED' in doc.source_file
