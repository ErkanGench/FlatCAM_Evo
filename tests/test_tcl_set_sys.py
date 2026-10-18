"""The Tcl command set_sys writes the value and propagates the defaults."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from defaults import AppDefaults, AppOptions
from tclCommands.TclCommandSetSys import TclCommandSetSys


def make_command():
    defaults = AppDefaults(beta=False)
    options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    app = SimpleNamespace(defaults=defaults, options=options)
    return SimpleNamespace(app=app, raise_tcl_error=Mock()), defaults, options


class TestTclSetSys(unittest.TestCase):
    def test_application_key_goes_to_defaults_and_propagates(self):
        command, defaults, _options = make_command()
        with patch.object(AppDefaults, 'propagate_defaults') as propagate:
            TclCommandSetSys.execute(command, {'name': 'global_gridx', 'value': 2.5}, [])
        self.assertEqual(defaults['global_gridx'], 2.5)
        propagate.assert_called_once_with()
        command.raise_tcl_error.assert_not_called()

    def test_project_key_goes_to_project_and_converts_tcl_words(self):
        command, defaults, options = make_command()
        before = defaults['units']
        TclCommandSetSys.execute(command, {'name': 'units', 'value': 'in' if before == 'MM' else 'mm'}, [])
        self.assertEqual(options['units'], 'IN' if before == 'MM' else 'MM')
        self.assertEqual(defaults['units'], before)
        command.raise_tcl_error.assert_not_called()

    def test_unknown_key_is_an_error(self):
        command, _defaults, _options = make_command()
        TclCommandSetSys.execute(command, {'name': 'no_such_key', 'value': '1'}, [])
        command.raise_tcl_error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
