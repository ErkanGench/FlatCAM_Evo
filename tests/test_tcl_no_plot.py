"""A Tcl command makes no plot: every new_object() call in tclCommands passes plot=False. Only plot_all and
plot_objects draw, and in headless mode they draw nothing."""

import ast
import os
from types import SimpleNamespace
from unittest.mock import Mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TCL_DIR = os.path.join(REPO, 'tclCommands')


def _new_object_calls_without_plot_false():
    offenders = []
    for name in sorted(os.listdir(TCL_DIR)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(TCL_DIR, name)
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'new_object':
                plot = [kw for kw in node.keywords if kw.arg == 'plot']
                if not (plot and isinstance(plot[0].value, ast.Constant) and plot[0].value.value is False):
                    offenders.append('%s:%d' % (name, node.lineno))
    return offenders


def test_every_new_object_call_of_a_tcl_command_passes_plot_false():
    assert _new_object_calls_without_plot_false() == []


def test_plot_all_draws_nothing_in_headless_mode():
    from tclCommands.TclCommandPlotAll import TclCommandPlotAll
    app = SimpleNamespace(headless=True, plot_all=Mock(), inform=Mock())
    command = TclCommandPlotAll.__new__(TclCommandPlotAll)
    command.app = app
    command.execute({}, [])
    app.plot_all.assert_not_called()
    app.inform.emit.assert_called_once()


def test_plot_objects_draws_nothing_in_headless_mode():
    from tclCommands.TclCommandPlotObjects import TclCommandPlotObjects
    obj = Mock()
    app = SimpleNamespace(headless=True, inform=Mock(), collection=Mock(get_by_name=Mock(return_value=obj)))
    command = TclCommandPlotObjects.__new__(TclCommandPlotObjects)
    command.app = app
    command.execute({}, ['a'])
    obj.plot.assert_not_called()
    app.inform.emit.assert_called_once()
