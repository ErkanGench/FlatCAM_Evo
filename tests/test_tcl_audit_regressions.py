"""Headless regressions for Tcl validation and command completion contracts."""
import collections
import time
import tkinter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets

from appPlugins.ToolShell import FCShell
from tclCommands.TclCommand import TclCommand, TclCommandSignaled
from tclCommands.TclCommandAddAperture import TclCommandAddAperture
from tclCommands.TclCommandAddPolygon import TclCommandAddPolygon
from tclCommands.TclCommandAddPolyline import TclCommandAddPolyline
from tclCommands.TclCommandAddCircle import TclCommandAddCircle
from tclCommands.TclCommandAddRectangle import TclCommandAddRectangle
from tclCommands.TclCommandSetSys import TclCommandSetSys
from tclCommands.TclCommandSetPath import TclCommandSetPath
from tclCommands.TclCommandGetActive import TclCommandGetActive
from tclCommands.TclCommandSaveProject import TclCommandSaveProject
from tclCommands.TclCommandSaveSys import TclCommandSaveSys
from tclCommands.TclCommandVersion import TclCommandVersion
from tclCommands.TclCommandQuit import TclCommandQuit


class Signals(QtCore.QObject):
    shell_command_finished = QtCore.pyqtSignal(object)
    thread_exception = QtCore.pyqtSignal(object)
    worker_task = QtCore.pyqtSignal(object)


def new_tcl(attempts=5):
    """tkinter.Tcl(), tried again: under the load of the parallel workers Windows can fail the read of init.tcl
    ("couldn't read file ... init.tcl: No error"); the next try reads it."""
    for attempt in range(attempts):
        try:
            return tkinter.Tcl()
        except tkinter.TclError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2)


def make_app():
    app = Signals()
    app.log = Mock()
    # a long default: a busy machine (parallel test workers) delays the queued work; the timeout tests pass -timeout
    app.options = {'global_background_timeout': 5000, 'global_verbose_error_level': 0}
    shell = SimpleNamespace(app=app, tcl=new_tcl(), TclErrorException=FCShell.TclErrorException,
                            open_processing=Mock())
    shell.raise_tcl_error = lambda text: FCShell.raise_tcl_error(shell, text)
    shell.display_tcl_error = lambda error, info: FCShell.display_tcl_error(shell, error, info)
    app.shell = shell
    return app


class Command(TclCommand):
    aliases = ['test_command']
    required = []
    arg_names = collections.OrderedDict()
    option_types = {'number': float, 'dpp': float, 'all': str}

    def execute(self, args, unnamed_args):
        return args.get('number', 'ordinary text')


class BackgroundCommand(TclCommandSignaled, Command):
    def execute(self, args, unnamed_args):
        return args.get('number', 'ordinary text')


@pytest.mark.parametrize('command_name, keys', [
    ('Delete', ('f',)),
    ('CloseProject', ('force',)),
    ('PlotAll', ('plot_status',)),
    ('PlotObjects', ('plot_status',)),
    ('Paint', ('all',)),
    ('CopperClear', ('all',)),
    ('Cncjob', ('dpp', 'toolchangez', 'dwelltime', 'extracut_length', 'startz', 'spindlespeed')),
    ('Drillcncjob', ('dpp', 'toolchangez', 'dwelltime', 'drillz', 'startz', 'endz')),
])
def test_actual_commands_preserve_supported_bare_options(command_name, keys):
    from importlib import import_module

    cls = getattr(import_module('tclCommands.TclCommand' + command_name), 'TclCommand' + command_name)
    command = cls(make_app())
    help_text = command.get_decorated_help()
    usage = next(line for line in help_text.splitlines() if line.startswith('> '))
    for key, value_type in command.option_types.items():
        if key not in command.help['args']:
            continue
        value = '<%s>' % value_type.__name__
        if key in keys:
            value = '[' + value + ']'
        assert '[-%s %s]' % (key, value) in usage
        assert '[-%s %s:' % (key, value) in help_text
    positional = tuple('object' for key in command.required)
    for key in keys:
        args, extra = command.check_args(positional + ('-' + key,))
        assert args[key] is None
        assert extra == []
        args, _ = command.check_args(positional + ('-' + key, '1'))
        assert args[key] == command.option_types[key]('1')
    for key in command.option_types.keys() - set(keys):
        with pytest.raises(FCShell.TclErrorException, match='Missing option value'):
            command.check_args(positional + ('-' + key,))


def test_real_tcl_catch_preserves_literal_error_message():
    app = make_app()
    command = Command(app)
    app.shell.tcl.createcommand('test_command', command.execute_wrapper)
    assert app.shell.tcl.eval('catch {test_command -number} message') == '1'
    assert 'number' in app.shell.tcl.eval('set message')
    text = 'bad [value] $variable; "quoted" \\path\nnext'
    app.shell.tcl.createcommand('bad', lambda: app.shell.display_tcl_error(text, None))
    assert app.shell.tcl.eval('catch {bad} message') == '1'
    assert app.shell.tcl.eval('set message') == text
    assert app.shell.tcl.eval('test_command') == 'ordinary text'


@pytest.fixture
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_timeout_is_error_and_late_completion_cannot_replace_new_output(qt_app):
    app = make_app()
    command = BackgroundCommand(app)
    pending = []
    app.worker_task.connect(pending.append)
    app.shell.tcl.createcommand('background', command.execute_wrapper)
    command.output = 'stale'
    assert app.shell.tcl.eval('catch {background -number 1 -timeout 1} message') == '1'
    assert 'timed out' in app.shell.tcl.eval('set message').lower()
    assert command.output is None
    assert app.receivers(app.shell_command_finished) == 0
    app.worker_task.disconnect(pending.append)

    def dispatch(task):
        QtCore.QTimer.singleShot(0, lambda: pending[0]['fcn'](*pending[0]['params']))
        QtCore.QTimer.singleShot(5, lambda: task['fcn'](*task['params']))

    app.worker_task.connect(dispatch)
    assert command.execute_wrapper('-number', '2') == 2.0
    assert command.output == 2.0


def object_app(obj):
    app = make_app()
    app.collection = Mock()
    app.collection.get_by_name.return_value = obj
    app.collection.get_active.return_value = obj
    app.inform_shell = Mock()
    app.inform = Mock()
    return app


def test_aperture_ids_are_integer_unique_and_start_at_ten():
    obj = SimpleNamespace(kind='gerber', tools={})
    command = TclCommandAddAperture(object_app(obj))
    command.execute({'name': 'g'}, [])
    assert 10 in obj.tools
    command.execute({'name': 'g'}, [])
    assert 11 in obj.tools
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'name': 'g', 'apid': 10}, [])
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'name': 'g', 'type': 'R', 'width': 1, 'height': 0}, [])


@pytest.mark.parametrize('cls,args,extra', [
    (TclCommandAddPolyline, {'name': 'g'}, []),
    (TclCommandAddCircle, {'name': 'g', 'center_x': 0, 'center_y': 0, 'radius': -1}, []),
    (TclCommandAddCircle, {'name': 'g', 'center_x': 0, 'center_y': 0, 'radius': 1}, ['extra']),
    (TclCommandAddRectangle, {'name': 'g', 'x0': 0, 'y0': 0, 'x1': 0, 'y1': 1}, [])])
def test_invalid_shapes_do_not_mutate(cls, args, extra):
    obj = Mock(kind='geometry')
    with pytest.raises(FCShell.TclErrorException):
        cls(object_app(obj)).execute(args, extra)
    obj.add_polygon.assert_not_called()
    obj.add_polyline.assert_not_called()
    obj.add_circle.assert_not_called()


def test_real_worker_validation_exception_becomes_tcl_error_without_excepthook(qt_app):
    class FailingCommand(BackgroundCommand):
        def execute(self, args, unnamed_args):
            self.raise_tcl_error('worker validation failed')

    class Worker(QtCore.QObject):
        @QtCore.pyqtSlot(object)
        def run(self, task):
            task['fcn'](*task['params'])

    app = make_app()
    thread = QtCore.QThread()
    worker = Worker()
    worker.moveToThread(thread)
    thread.finished.connect(worker.deleteLater)
    app.worker_task.connect(worker.run)
    app.shell.tcl.createcommand('background', FailingCommand(app).execute_wrapper)
    thread.start()
    try:
        from unittest.mock import patch
        with patch('sys.excepthook') as hook:
            assert app.shell.tcl.eval('catch {background -timeout 1000} message') == '1'
            assert app.shell.tcl.eval('set message') == 'worker validation failed'
            hook.assert_not_called()
        assert app.receivers(app.shell_command_finished) == 0
    finally:
        thread.quit()
        assert thread.wait(3000)

