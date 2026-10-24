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
    factory._new_object = lambda *a: AppObject._new_object(factory, *a)
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

