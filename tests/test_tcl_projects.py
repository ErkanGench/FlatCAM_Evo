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

class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot, connection_type=None):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


def make_open_app(result, delay=0.0):
    import threading
    app = make_app()
    app.options = {}
    app.defaults = {}
    signal = FakeSignal()

    def open_project(filename, **kwargs):
        # the load ends later, on another thread
        threading.Timer(delay, lambda: signal.emit(*result)).start()
        return True

    app.f_handlers = SimpleNamespace(project_load_done=signal, open_project=open_project)
    return app, signal


class TestOpenProject(unittest.TestCase):
    def run_open(self, result, delay=0.05):
        from tclCommands.TclCommandOpenProject import TclCommandOpenProject
        app, signal = make_open_app(result, delay)
        out = TclCommandOpenProject(app).execute({'filename': 'a.FlatPrj'}, [])
        self.assertEqual(signal.slots, [])
        return out

    def test_waits_for_the_load(self):
        import time
        start = time.time()
        self.run_open((True, 'a.FlatPrj', []), delay=0.2)
        self.assertGreaterEqual(time.time() - start, 0.15)

    def test_failed_load_error_has_the_reason(self):
        from tclCommands.TclCommandOpenProject import TclCommandOpenProject
        app, _signal = make_open_app((False, 'a.FlatPrj', []), 0.01)
        app.f_handlers.last_load_error = 'File no longer available.'
        with self.assertRaises(TclError) as ctx:
            TclCommandOpenProject(app).execute({'filename': 'a.FlatPrj'}, [])
        self.assertIn('File no longer available.', str(ctx.exception))

    def test_partial_load_names_the_skipped_objects(self):
        out = self.run_open((True, 'a.FlatPrj', ['Bad_1', 'Bad_2']))
        self.assertIn('Bad_1', str(out))
        self.assertIn('Bad_2', str(out))


if __name__ == '__main__':
    unittest.main()
