"""Guard bool-emitting Qt signals from silently changing command options.

This is a bounded source lint, not a Qt type checker: it resolves same-class
methods and known threading/fit command names across facades. It also protects
the editor transform_tool.run entrypoints. Dynamic aliases, partials and arbitrary
optional filename/silent parameters require manual review.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from appHandlers.appSignalConnector import AppSignalConnector


OPTION_PARAMETERS = {'use_thread', 'fit_view'}


def optional_command_parameter(function):
    args = function.args.posonlyargs + function.args.args
    index = 1 if args and args[0].arg in ('self', 'cls') else 0
    if len(args) <= index:
        # Keyword-only options alone are not an explicit Qt no-argument slot.
        return next((arg.arg for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults)
                     if arg.arg in OPTION_PARAMETERS and default is not None), None)
    if index < len(args) - len(function.args.defaults):
        return None
    return args[index].arg


def no_argument_slot(function):
    slots = [item for item in function.decorator_list if isinstance(item, ast.Call) and
             ((isinstance(item.func, ast.Attribute) and item.func.attr in ('pyqtSlot', 'Slot')) or
              (isinstance(item.func, ast.Name) and item.func.id in ('pyqtSlot', 'Slot')))]
    return bool(slots) and all(not item.args for item in slots)


def unsafe_connections(source, protected):
    findings = []

    class Connections(ast.NodeVisitor):
        methods = {}

        def visit_ClassDef(self, node):
            previous = self.methods
            self.methods = {item.name: item for item in node.body if isinstance(item, ast.FunctionDef)}
            self.generic_visit(node)
            self.methods = previous

        def command_parameter(self, receiver):
            if isinstance(receiver, ast.Name):
                return protected.get(receiver.id)
            if not isinstance(receiver, ast.Attribute):
                return None
            if isinstance(receiver.value, ast.Name) and receiver.value.id == 'self':
                function = self.methods.get(receiver.attr)
                if function is not None:
                    parameter = optional_command_parameter(function)
                    return parameter if parameter in OPTION_PARAMETERS and not no_argument_slot(function) else None
            if receiver.attr == 'run' and isinstance(receiver.value, ast.Attribute) and \
                    receiver.value.attr == 'transform_tool':
                return 'toggle'
            return protected.get(receiver.attr)

        def visit_Call(self, node):
            if not isinstance(node.func, ast.Attribute) or node.func.attr != 'connect' or not node.args:
                return self.generic_visit(node)
            signal = node.func.value
            if isinstance(signal, ast.Subscript):
                signal = signal.value
            if not isinstance(signal, ast.Attribute) or signal.attr not in ('triggered', 'clicked'):
                return self.generic_visit(node)
            receiver = node.args[0]
            parameter = self.command_parameter(receiver)
            if parameter is not None:
                findings.append((node.lineno, ast.unparse(receiver), parameter))
            elif isinstance(receiver, ast.Lambda):
                args = receiver.args.posonlyargs + receiver.args.args
                if args:
                    payload = args[0].arg
                    for call in ast.walk(receiver.body):
                        if not isinstance(call, ast.Call):
                            continue
                        parameter = self.command_parameter(call.func)
                        if parameter is None:
                            continue
                        forwarded = bool(call.args and isinstance(call.args[0], ast.Name) and
                                         call.args[0].id == payload)
                        forwarded = forwarded or any(keyword.arg == parameter and
                                                     isinstance(keyword.value, ast.Name) and
                                                     keyword.value.id == payload for keyword in call.keywords)
                        captured_receiver = any(isinstance(item, ast.Name) and item.id == payload
                                                for item in ast.walk(call.func))
                        if captured_receiver or forwarded:
                            findings.append((node.lineno, ast.unparse(receiver), parameter))
                            break
            self.generic_visit(node)

    Connections().visit(source if isinstance(source, ast.AST) else ast.parse(source))
    return findings


def audit_sources(sources):
    # each file is parsed 1 time: the same tree gives the protected names and the connections
    trees = {path: ast.parse(source) for path, source in sources.items()}
    protected = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                parameter = optional_command_parameter(node)
                if parameter in OPTION_PARAMETERS and not no_argument_slot(node):
                    protected[node.name] = parameter
    # only a file with a triggered or clicked signal can hold a finding
    return [(path, line, receiver, parameter) for path, tree in trees.items()
            if 'triggered' in sources[path] or 'clicked' in sources[path]
            for line, receiver, parameter in unsafe_connections(tree, protected)]


def test_repository_command_connections_discard_checked_payload():
    root = Path(__file__).resolve().parents[1]
    paths = set(root.glob('*.py'))
    for directory in ('appHandlers', 'appGUI', 'appObjects', 'appEditors', 'appPlugins'):
        paths.update((root / directory).rglob('*.py'))
    assert root / 'appMain.py' in paths
    assert root / 'appEditors' / 'appGeoEditor.py' in paths
    sources = {path.relative_to(root).as_posix(): path.read_text(encoding='utf-8-sig') for path in sorted(paths)}
    findings = audit_sources(sources)
    assert findings == [], '\n'.join('%s:%s: %s receives Qt bool as %s' % item for item in findings)


@pytest.fixture(scope='module')
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.parametrize('signal_type', ['action', 'button'])
@pytest.mark.parametrize('receiver_kind', ['adapter', 'slot'])
def test_discard_adapter_keeps_command_default_and_checked_receiver_gets_state(qt_app, signal_type, receiver_kind):
    calls, states = [], []

    def command(use_thread=True):
        calls.append(use_thread)

    class Commands(QtCore.QObject):
        @QtCore.pyqtSlot()
        def command(self, use_thread=True):
            calls.append(use_thread)

    commands = Commands()
    sender = QtGui.QAction('Command') if signal_type == 'action' else QtWidgets.QPushButton('Command')
    sender.setCheckable(True)
    signal = sender.triggered if signal_type == 'action' else sender.clicked
    if receiver_kind == 'slot':
        signal.connect(commands.command)
    else:
        signal.connect(lambda: command())
    signal.connect(states.append)
    invoke = sender.trigger if signal_type == 'action' else sender.click
    invoke()
    invoke()
    assert calls == [True, True]
    assert states == [True, False]


@pytest.mark.parametrize('registration, action_name', [
    ('connect_editmenu_signals', 'menuedit_center_in_origin'),
    ('connect_menuview_signals', 'menuview_replot'),
    ('connect_canvas_context_signals', 'replot'),
    ('connect_toolbar_signals', 'replot_btn'),
])
def test_real_registered_actions_keep_command_defaults(qt_app, registration, action_name):
    app = Mock()
    action = QtGui.QAction('Command')
    setattr(app.ui, action_name, action)
    app.ui.pop_menucolor.actions.return_value = []
    calls = []

    def plot_all(fit_view=True, muted=False, use_thread=True):
        calls.append((fit_view, use_thread))

    def on_custom_origin(use_thread=True):
        calls.append((True, use_thread))

    app.plot_all = plot_all
    app.edit_class.on_custom_origin = on_custom_origin
    connector = AppSignalConnector(app)
    getattr(connector, registration)()
    action.trigger()
    assert calls == [(True, True)]


@pytest.mark.parametrize('filename, action_name', [
    ('appGeoEditor.py', 'geo_transform_menuitem'),
    ('appGerberEditor.py', 'grb_transform_menuitem'),
])
def test_real_editor_registration_keeps_transform_toggle_default(qt_app, filename, action_name):
    path = Path(__file__).resolve().parents[1] / 'appEditors' / filename
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    signal = 'self.app.ui.%s.triggered' % action_name
    connections = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                   isinstance(node.func, ast.Attribute) and node.func.attr == 'connect' and
                   ast.unparse(node.func.value) == signal]
    assert len(connections) == 1
    # Execute the actual connection expression without constructing either
    # complete editor/canvas. The sender and signal delivery are real Qt.
    registration = ast.Module(body=[ast.Expr(value=connections[0])], type_ignores=[])
    action = QtGui.QAction('Transform')
    calls = []

    def run(toggle=True):
        calls.append(toggle)

    receiver = SimpleNamespace(app=SimpleNamespace(ui=SimpleNamespace(**{action_name: action})),
                               transform_tool=SimpleNamespace(run=run))
    exec(compile(ast.fix_missing_locations(registration), str(path), 'exec'), {'self': receiver})
    action.trigger()
    assert calls == [True]
