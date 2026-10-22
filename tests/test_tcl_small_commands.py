"""Small Tcl commands: help, open_gerber argument check and set_sys."""
import os
import sys
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock, patch

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
