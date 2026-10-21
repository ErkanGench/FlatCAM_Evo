"""Headless regressions for Tcl validation and command completion contracts."""
import collections
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


def make_app():
    app = Signals()
    app.log = Mock()
    # a long default: a busy machine (parallel test workers) delays the queued work; the timeout tests pass -timeout
    app.options = {'global_background_timeout': 5000, 'global_verbose_error_level': 0}
    shell = SimpleNamespace(app=app, tcl=tkinter.Tcl(), TclErrorException=FCShell.TclErrorException,
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


@pytest.mark.parametrize('argv', [('-number',), ('-number', 'nan'), ('-timeout', 'abc'),
                                  ('-timeout', '10'), ('-unknown', '1')])
def test_validation_raises_before_execution(argv):
    app = make_app()
    with pytest.raises(FCShell.TclErrorException):
        Command(app).check_args(argv)


def test_optional_default_and_flag_values_remain_supported():
    class FlagCommand(Command):
        valueless_options = frozenset({'dpp', 'all'})

    args, _ = FlagCommand(make_app()).check_args(('-dpp', '-all'))
    assert args == {'dpp': None, 'all': None}


def test_valueless_permission_is_metadata_driven_and_isolated():
    class FlagCommand(Command):
        valueless_options = frozenset({'number'})

    assert FlagCommand(make_app()).check_args(('-number',)) == ({'number': None}, [])
    for key in ('number', 'dpp', 'all'):
        with pytest.raises(FCShell.TclErrorException, match='Missing option value'):
            Command(make_app()).check_args(('-' + key,))
    assert Command(make_app()).check_args(('-dpp', '0.5')) == ({'dpp': 0.5}, [])


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


@pytest.mark.parametrize('command_name, key, terms', [
    ('PlotAll', 'plot_status', ('bare', 'True', 'omitted')),
    ('PlotObjects', 'plot_status', ('bare', 'True', 'omitted')),
    ('Paint', 'all', ('ignored', '-single', '-box', 'default')),
    ('Cncjob', 'extracut_length', ('bare', '0.0')),
    ('Cncjob', 'startz', ('bare', 'None')),
    ('Cncjob', 'spindlespeed', ('bare', 'None', 'las_power')),
    ('Cncjob', 'dwelltime', ('bare', 'tools_mill_dwelltime', 'omitted', 'tools_mill_dwell')),
    ('Drillcncjob', 'dpp', ('bare', 'absolute', 'tools_drill_depthperpass')),
    ('Drillcncjob', 'startz', ('bare', 'tools_drill_startz', 'tools_drill_travelz')),
    ('Drillcncjob', 'dwelltime', ('bare', 'tools_drill_dwelltime', 'omitted', 'tools_drill_dwell')),
])
def test_bare_option_help_describes_current_defaults(command_name, key, terms):
    from importlib import import_module

    cls = getattr(import_module('tclCommands.TclCommand' + command_name), 'TclCommand' + command_name)
    description = cls.help['args'][key].lower()
    for term in terms:
        assert term.lower() in description


def test_required_option_cannot_be_made_valueless_by_metadata():
    class RequiredCommand(Command):
        required = ['number']
        valueless_options = frozenset({'number'})

    with pytest.raises(FCShell.TclErrorException, match='Missing required argument'):
        RequiredCommand(make_app()).check_args(('-number',))


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


def test_background_completion_is_owned_and_connections_are_released(qt_app):
    app = make_app()
    command = BackgroundCommand(app)
    baseline = app.receivers(app.shell_command_finished)

    def dispatch(task):
        QtCore.QTimer.singleShot(0, lambda: app.shell_command_finished.emit(object()))
        QtCore.QTimer.singleShot(5, lambda: task['fcn'](*task['params']))

    app.worker_task.connect(dispatch)
    for value in ('1', '2'):
        assert command.execute_wrapper('-number', value) == float(value)
        assert app.receivers(app.shell_command_finished) == baseline
        assert app.receivers(app.thread_exception) == 0


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


def test_polygon_coordinates_create_geometry_and_report_failure():
    obj = Mock(kind='geometry')
    obj.add_polygon.return_value = None
    command = TclCommandAddPolygon(object_app(obj))
    command.execute({'name': 'g'}, ['0', '0', '1', '0', '0', '1'])
    assert obj.add_polygon.call_count == 1
    with pytest.raises((FCShell.TclErrorException, ValueError, SyntaxError)):
        command.execute({'name': 'g', 'p_coords': 'broken'}, [])
    obj.add_polygon.return_value = 'fail'
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'name': 'g'}, ['0', '0', '1', '0', '0', '1'])


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


def test_settings_keep_boolean_and_numeric_types():
    app = make_app()
    app.options.update({'enabled': True, 'speed': 1.5, 'count': 3, 'text': 'hello'})
    app.defaults = Mock()
    command = TclCommandSetSys(app)
    for name, value in [('enabled', '0'), ('speed', '2.5'), ('count', '4'), ('text', 'false')]:
        command.execute({'name': name, 'value': value}, [])
    assert app.options['enabled'] is False
    assert app.options['speed'] == 2.5
    assert app.options['count'] == 4
    assert app.options['text'] == 'false'


def test_set_path_is_tcl_argument_safe_and_updates_after_success(tmp_path):
    app = object_app(None)
    path = tmp_path / 'nested space' / '[literal] $value'
    previous = app.shell.tcl.call('pwd')
    try:
        TclCommandSetPath(app).execute({'path': str(path), 'create': 'yes'}, [])
        assert path.is_dir()
        assert app.options['global_tcl_path'] == str(path).replace('\\', '/')
    finally:
        app.shell.tcl.call('cd', previous)


def test_active_name_and_current_version_are_returned_without_network():
    app = object_app(SimpleNamespace(obj_options={'name': 'active'}))
    app.version = '9.7'
    app.version_check = Mock()
    assert TclCommandGetActive(app).execute({}, []) == 'active'
    assert '9.7' in TclCommandVersion(app).execute({}, [])
    app.version_check.assert_not_called()


def test_persistence_results_and_quit_errors_are_not_discarded():
    app = make_app()
    app.f_handlers = Mock()
    app.f_handlers.save_project.return_value = False
    assert TclCommandSaveProject(app).execute({'filename': 'project'}, []) is False
    app.preferencesUiManager = Mock()
    TclCommandSaveSys(app).execute({}, [])
    app.preferencesUiManager.save_defaults.assert_called_once_with()
    app.quit_application = Mock(side_effect=RuntimeError('cleanup failed'))
    # Never run the old os._exit fallback in this process.
    from unittest.mock import patch
    with patch('os._exit') as exit_process:
        with pytest.raises(RuntimeError, match='cleanup failed'):
            TclCommandQuit(app).execute({}, [])
        exit_process.assert_not_called()


def test_registered_aliases_keep_their_command_boundary():
    app = make_app()
    app.shell.tcl_commands_storage = {}
    FCShell.setup_shell(app.shell)
    assert len(app.shell.tcl_commands_storage) == 106
    commands = {id(entry['fcn'].__self__) for entry in app.shell.tcl_commands_storage.values()}
    assert len(commands) == 78
    for command in ('add_circle', 'set_sys', 'save_project', 'cncjob'):
        assert app.shell.tcl.eval('catch {%s -unknown_option 1} msg' % command) == '1'
        assert 'Unknown parameter' in app.shell.tcl.eval('set msg')


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


def test_duplicate_drill_is_still_text_for_python_but_an_error_for_tcl(qt_app):
    from shapely import Point
    from tclCommands.TclCommandAddDrill import TclCommandAddDrill
    obj = SimpleNamespace(kind='excellon', tools={7: {'tooldia': 1, 'drills': [Point(0, 0)]}})
    app = object_app(obj)
    app.decimals = 4
    app.dec_format = lambda value, decimals: round(value, decimals)
    command = TclCommandAddDrill(app)
    assert 'already' in command.execute({'name': 'e', 'dia': 1}, [])
    app.worker_task.connect(lambda task: task['fcn'](*task['params']))
    app.shell.tcl.createcommand('add_drill', command.execute_wrapper)
    assert app.shell.tcl.eval('catch {add_drill e -dia 1} msg') == '1'
    assert 'already' in app.shell.tcl.eval('set msg')
