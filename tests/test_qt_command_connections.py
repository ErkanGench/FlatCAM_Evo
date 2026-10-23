"""Guard bool-emitting Qt signals from silently changing command options."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from appHandlers.appSignalConnector import AppSignalConnector


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
