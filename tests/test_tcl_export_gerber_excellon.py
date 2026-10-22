"""export_gerber and export_excellon (Tcl) raised TypeError: the commands passed name= to handlers whose parameter is
obj_name. The tests run the real export into a file and read it back with FlatCAM's own parsers."""

from unittest.mock import Mock

import pytest

from appHandlers.appIO import appIO
from appObjects.ExcellonObject import ExcellonObject
from appObjects.GerberObject import GerberObject
from tclCommands.TclCommandExportExcellon import TclCommandExportExcellon
from tclCommands.TclCommandExportGerber import TclCommandExportGerber

from tests.helpers_objects import app, _headless_qt, make_excellon, make_gerber  # noqa: F401,E402


def run_export(command_class, app, source, *argv):
    app.f_handlers = appIO(app)
    app.collection.get_by_name = Mock(side_effect=lambda n: source if n == source.obj_options['name'] else None)
    cmd = command_class(app)
    args, unnamed = cmd.check_args(tuple(argv))
    return cmd.execute(args, unnamed)


def test_export_gerber_writes_a_file_that_parses_back(app, tmp_path):
    source = make_gerber(app, name='g')
    target = tmp_path / 'out.gbr'

    run_export(TclCommandExportGerber, app, source, 'g', str(target))

    assert target.exists() and target.stat().st_size > 0
    again = GerberObject('again', app)
    assert again.parse_file(str(target)) is None
    assert again.solid_geometry
    for got, want in zip(again.bounds(), source.bounds()):
        assert got == pytest.approx(want, abs=1e-3)


def test_export_excellon_writes_a_file_that_parses_back(app, tmp_path):
    source = make_excellon(app, name='e')
    target = tmp_path / 'out.drl'

    run_export(TclCommandExportExcellon, app, source, 'e', str(target))

    assert target.exists() and target.stat().st_size > 0
    again = ExcellonObject('again', app)
    assert again.parse_file(str(target)) is None
    assert again.create_geometry() is None
    assert sorted(t['tooldia'] for t in again.tools.values()) == sorted(t['tooldia'] for t in source.tools.values())


@pytest.mark.parametrize('command_class, handler', [(TclCommandExportGerber, 'export_gerber'),
                                                    (TclCommandExportExcellon, 'export_excellon')])
def test_the_handler_gets_the_object_name_as_obj_name(app, tmp_path, command_class, handler):
    # an absolute name of the platform: '/tmp/x' has no drive on Windows and is completed with one
    target = str(tmp_path / 'x')
    app.f_handlers = Mock()
    cmd = command_class(app)
    args, unnamed = cmd.check_args(('my_object', target))

    cmd.execute(args, unnamed)

    getattr(app.f_handlers, handler).assert_called_once_with(use_thread=False, obj_name='my_object',
                                                             filename=target)
