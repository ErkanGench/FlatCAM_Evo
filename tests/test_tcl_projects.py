"""Tcl commands for the projects of the Project tab."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class TclError(Exception):
    pass


def make_app():
    first = SimpleNamespace(name='Board_A')
    second = SimpleNamespace(name='Board_B')
    contexts = [first, second]
    projects = SimpleNamespace(
        active=first, names=Mock(return_value=['Board_A', 'Board_B']),
        get_by_name=Mock(side_effect=lambda name: next((c for c in contexts if c.name == name), None)),
        switch=Mock(return_value=True), close=Mock(return_value=True), is_dirty=Mock(return_value=False))

    def raise_tcl_error(text):
        raise TclError(text)

    return SimpleNamespace(log=Mock(), projects=projects, shell=SimpleNamespace(raise_tcl_error=raise_tcl_error))


class TestListProjects(unittest.TestCase):
    def test_lists_the_names(self):
        from tclCommands.TclCommandListProjects import TclCommandListProjects
        app = make_app()
        self.assertEqual(TclCommandListProjects(app).execute({}, []), 'Board_A\nBoard_B')

class TestSelectProject(unittest.TestCase):
    def test_switches_by_name(self):
        from tclCommands.TclCommandSelectProject import TclCommandSelectProject
        app = make_app()
        TclCommandSelectProject(app).execute({'name': 'Board_B'}, [])
        app.projects.switch.assert_called_once_with(app.projects.get_by_name('Board_B'))

    def test_unknown_name_is_an_error(self):
        from tclCommands.TclCommandSelectProject import TclCommandSelectProject
        app = make_app()
        with self.assertRaises(TclError):
            TclCommandSelectProject(app).execute({'name': 'Missing'}, [])
        app.projects.switch.assert_not_called()

class TestCloseProject(unittest.TestCase):
    def test_closes_the_active_project_by_default(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        TclCommandCloseProject(app).execute({}, [])
        app.projects.close.assert_called_once_with(app.projects.active, force=True)

    def test_closes_by_name(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        TclCommandCloseProject(app).execute({'name': 'Board_B'}, [])
        app.projects.close.assert_called_once_with(app.projects.get_by_name('Board_B'), force=True)

    def test_dirty_project_without_force_is_an_error(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        app.projects.is_dirty.return_value = True
        with self.assertRaises(TclError):
            TclCommandCloseProject(app).execute({}, [])
        app.projects.close.assert_not_called()

    def test_dirty_project_with_force_closes(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        app.projects.is_dirty.return_value = True
        for value in ('1', 'True', 'true', None):
            app.projects.close.reset_mock()
            TclCommandCloseProject(app).execute({'force': value}, [])
            app.projects.close.assert_called_once_with(app.projects.active, force=True)

if __name__ == '__main__':
    unittest.main()
