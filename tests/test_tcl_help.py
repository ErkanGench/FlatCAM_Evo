"""The Tcl command help without a name lists the commands and ends with a usage hint; the shell shows it as HTML."""
import os
import sys
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tclCommands.TclCommandHelp as TclCommandHelpModule
from tclCommands.TclCommandHelp import TclCommandHelp


class ShownText(HTMLParser):
    """The text of an HTML fragment as the shell shows it: the tags are dropped and the entities decoded."""

    def __init__(self, fragment):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(fragment)
        self.close()

    def handle_data(self, data):
        self.parts.append(data)

    @property
    def text(self):
        return ''.join(self.parts)


class TestTclHelp(unittest.TestCase):
    def test_usage_hint_shows_the_argument_name(self):
        shell = SimpleNamespace(tcl_commands_storage={'open_gerber': {'description': 'Open a Gerber file.'}},
                                append_raw=mock.Mock())
        command = SimpleNamespace(app=SimpleNamespace(shell=shell, log=mock.Mock()))
        # English, whatever language the Preferences of this computer have
        with mock.patch.object(TclCommandHelpModule, '_', lambda text: text, create=True):
            TclCommandHelp.execute(command, {}, [])
        shown = ShownText(shell.append_raw.call_args[0][0]).text
        self.assertIn('Type help <command_name> for usage.', shown)
        self.assertIn('Example: help open_gerber', shown)
        self.assertIn('open_gerber', shown.split('Type help')[0])


if __name__ == '__main__':
    unittest.main()
