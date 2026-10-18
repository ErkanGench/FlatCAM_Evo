"""Command API contracts: explicit failure stays failure, None success stays success."""
import importlib
from unittest.mock import Mock

import pytest

from test_tcl_audit_generation import factory_app
from test_tcl_audit_regressions import FCShell


@pytest.mark.parametrize('suffix,handler,args', [
    ('ExportDXF', 'export_dxf', {'name': 'g', 'filename': 'out'}),
    ('ExportExcellon', 'export_excellon', {'name': 'e', 'filename': 'out'}),
    ('ExportGerber', 'export_gerber', {'name': 'g', 'filename': 'out'}),
    ('ExportSVG', 'export_svg', {'name': 'g', 'filename': 'out'}),
    ('OpenGerber', 'open_gerber', {'filename': 'in'}),
    ('OpenExcellon', 'open_excellon', {'filename': 'in'}),
    ('OpenGCode', 'open_gcode', {'filename': 'in'}),
    ('OpenProject', 'open_project', {'filename': 'in'})])
def test_handler_explicit_failure_is_not_discarded(suffix, handler, args):
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    app = factory_app(None)
    app.f_handlers = Mock()
    getattr(app.f_handlers, handler).return_value = 'fail'
    assert cls(app).execute(dict(args), []) == 'fail'
    getattr(app.f_handlers, handler).return_value = None
    assert cls(app).execute(dict(args), []) is None


@pytest.mark.parametrize('suffix,args', [('AddDrill', {'name': 'e', 'dia': 0}),
                                        ('AddSlot', {'name': 'e', 'dia': -1, 'startx': 0, 'starty': 0,
                                                     'stopx': 1, 'stopy': 1})])
def test_drill_and_slot_diameters_are_positive(suffix, args):
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    app = factory_app(Mock(kind='excellon', tools={}))
    with pytest.raises(FCShell.TclErrorException):
        cls(app).execute(args, [])


@pytest.mark.parametrize('suffix,args', [('Bounds', {}), ('Options', {'name': 'missing'}),
                                        ('Buffer', {'name': 'missing', 'dist': 1})])
def test_missing_objects_have_command_errors_not_attribute_or_key_errors(suffix, args):
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    with pytest.raises(FCShell.TclErrorException):
        cls(factory_app(None)).execute(args, [])


def test_buffer_unknown_join_does_not_mutate_object():
    from tclCommands.TclCommandBuffer import TclCommandBuffer
    obj = Mock(kind='geometry', obj_options={})
    with pytest.raises(FCShell.TclErrorException):
        TclCommandBuffer(factory_app(obj)).execute({'name': 'g', 'dist': 1, 'join': 'typo'}, [])
    obj.buffer.assert_not_called()


def test_get_sys_false_is_a_value_not_an_operation_failure():
    from tclCommands.TclCommandGetSys import TclCommandGetSys
    app = factory_app(None)
    app.options['example_bool'] = False
    app.shell.tcl.createcommand('get_sys', TclCommandGetSys(app).execute_wrapper)
    assert app.shell.tcl.eval('catch {get_sys example_bool} value') == '0'
    assert app.shell.tcl.eval('set value') == '0'


def test_export_gcode_accepts_both_documented_options_and_legacy_positionals():
    from tclCommands.TclCommandExportGcode import TclCommandExportGcode
    app = factory_app(Mock(kind='cncjob'))
    app.collection.has_promises.return_value = False
    cmd = TclCommandExportGcode(app)
    options, extra = cmd.check_args(('job', '-preamble', 'G0', '-postamble', 'M2'))
    positional, _ = cmd.check_args(('job', 'G0', 'M2'))
    assert options == positional
    cmd.execute(options, extra)
    app.collection.get_by_name.return_value.get_gcode.assert_called_once_with(preamble='G0', postamble='M2')


def test_write_gcode_propagates_explicit_failure():
    from tclCommands.TclCommandWriteGCode import TclCommandWriteGCode
    obj = Mock(kind='cncjob')
    obj.export_gcode.return_value = 'fail'
    app = factory_app(obj)
    assert TclCommandWriteGCode(app).execute({'name': 'job', 'filename': 'output'}, []) == 'fail'


@pytest.mark.parametrize('suffix,method,kind', [('NewGeometry', 'new_geometry_object', 'geometry'),
                                              ('NewExcellon', 'new_excellon_object', 'excellon'),
                                              ('NewGerber', 'new_gerber_object', 'gerber')])
def test_new_object_commands_propagate_factory_failure(suffix, method, kind):
    from appObjects.AppObject import AppObject
    from types import SimpleNamespace
    factory = SimpleNamespace(new_object=Mock(return_value='fail'))
    app = factory_app(None)
    app.app_obj = SimpleNamespace(**{method: lambda **kw: getattr(AppObject, method)(factory, **kw)})
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    assert cls(app).execute({'name': 'output'}, []) == 'fail'


def test_saving_defaults_reports_write_failure():
    from appGUI.preferences.PreferencesUIManager import PreferencesUIManager
    from types import SimpleNamespace
    defaults = Mock()
    defaults.write.side_effect = OSError('disk full')
    manager = SimpleNamespace(defaults=defaults, ui=Mock(), inform=Mock(), data_path='unused')
    assert PreferencesUIManager.save_defaults(manager) is False


@pytest.mark.parametrize('suffix', ['JoinGeometry', 'JoinExcellon'])
def test_join_rejects_wrong_source_kind_before_factory(suffix):
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    app = factory_app(Mock(kind='cncjob'))
    assert cls(app).execute({}, ['a', 'b']) == 'fail'
    app.app_obj.new_object.assert_not_called()


def test_new_and_plot_all_accept_tcl_boolean_words_without_nested_workers():
    from tclCommands.TclCommandNew import TclCommandNew
    from tclCommands.TclCommandPlotAll import TclCommandPlotAll
    app = factory_app(None)
    app.f_handlers = Mock()
    app.plot_all = Mock()
    app.collection.get_list.return_value = []
    TclCommandNew(app).execute({'reset': 'off', 'keep_scripts': 'yes'}, [])
    app.f_handlers.on_file_new_project.assert_called_once_with(cli=True, reset_tcl=False, keep_scripts=True)
    TclCommandPlotAll(app).execute({'use_thread': 'yes', 'plot_status': 'off'}, [])
    app.plot_all.assert_called_once_with(use_thread=False)


@pytest.mark.parametrize('method', ['open_gerber', 'open_excellon', 'open_gcode'])
def test_real_open_handlers_report_missing_tcl_input(method, tmp_path):
    from appHandlers.appIO import appIO
    from types import SimpleNamespace
    app = factory_app(None)
    app.defaults = {}
    app.options['global_tcl_path'] = str(tmp_path)
    handler = SimpleNamespace(app=app, log=app.log, inform=app.inform)
    assert getattr(appIO, method)(handler, 'missing-input-file', from_tcl=True) == 'fail'
    app.file_opened.emit.assert_not_called()


def test_open_gerber_default_path_uses_input_basename_not_custom_output_name(tmp_path):
    from appHandlers.appIO import appIO
    from appObjects.GerberObject import GerberObject
    from types import SimpleNamespace
    app = factory_app(None)
    app.defaults = {}
    app.options['global_tcl_path'] = str(tmp_path)
    input_file = tmp_path / 'drawing.gbr'
    input_file.write_text('placeholder', encoding='utf-8')
    gerber = Mock(spec=GerberObject)
    gerber.parse_file.return_value = None
    gerber.is_empty.return_value = False

    def create(kind, name, initialize, **kwargs):
        assert name == 'custom_output'
        return initialize(gerber, app)

    app.app_obj.new_object.side_effect = create
    handler = SimpleNamespace(app=app, log=app.log, inform=app.inform)
    appIO.open_gerber(handler, 'drawing.gbr', outname='custom_output', from_tcl=True)
    assert gerber.parse_file.call_args.args[0].replace('\\', '/') == str(input_file).replace('\\', '/')


@pytest.mark.parametrize('suffix,alias', [('ListPP', 'list_pp'), ('ListSys', 'list_sys')])
def test_list_commands_return_native_tcl_lists(suffix, alias):
    app = factory_app(None)
    app.options = {'first name': 1, 'second{value}': 2}
    app.preprocessors = {'first name': None, 'second{value}': None}
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    app.shell.tcl.createcommand(alias, cls(app).execute_wrapper)
    result = app.shell.tcl.eval(alias)
    assert app.shell.tcl.splitlist(result) == ('first name', 'second{value}')


def test_object_factory_rejects_initializer_false_without_publishing():
    from appObjects.AppObject import AppObject
    from types import SimpleNamespace
    from unittest.mock import patch
    app = factory_app(None)
    app.main_thread = None
    obj = SimpleNamespace(units='MM', obj_options={}, tool_option_prefix='', inherits_mill_options=False,
                           bounds=Mock(return_value=(0, 0, 1, 1)), moveToThread=Mock())
    factory = SimpleNamespace(app=app, _app_option=app.options.get, object_created=Mock(),
                               load_context=SimpleNamespace(batch=None))
    with patch('appObjects.AppObject.GeometryObject', return_value=obj):
        assert AppObject.new_object(factory, 'geometry', 'out', lambda *_: False, plot=False) == 'fail'
    factory.object_created.emit.assert_not_called()


def test_set_active_reports_selection_failure_as_tcl_error():
    from tclCommands.TclCommandSetActive import TclCommandSetActive
    app = factory_app(None)
    app.collection.set_active.side_effect = ValueError('missing object')
    app.shell.tcl.createcommand('set_active', TclCommandSetActive(app).execute_wrapper)
    assert app.shell.tcl.eval('catch {set_active missing} msg') == '1'
    assert 'missing object' in app.shell.tcl.eval('set msg')


def test_set_sys_does_not_treat_arbitrary_string_contents_as_enum_types():
    from tclCommands.TclCommandSetSys import TclCommandSetSys
    app = factory_app(None)
    app.defaults = Mock()
    app.options['text_setting'] = 'L'
    TclCommandSetSys(app).execute({'name': 'text_setting', 'value': 'new text'}, [])
    assert app.options['text_setting'] == 'new text'


@pytest.mark.parametrize('suffix,alias', [('GetNames', 'get_names'), ('GetPath', 'get_path'),
                                        ('ListProjects', 'list_projects')])
def test_text_queries_can_return_a_literal_fail_name(suffix, alias):
    app = factory_app(None)
    app.collection.get_names.return_value = ['fail']
    app.options['global_tcl_path'] = 'fail'
    app.projects = Mock()
    app.projects.names.return_value = ['fail']
    app.shell.append_output = Mock()
    cls = getattr(importlib.import_module('tclCommands.TclCommand' + suffix), 'TclCommand' + suffix)
    app.shell.tcl.createcommand(alias, cls(app).execute_wrapper)
    assert app.shell.tcl.eval('catch {%s} msg' % alias) == '0'
    assert app.shell.tcl.eval('set msg') == 'fail'
