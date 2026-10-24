"""Small Tcl commands: help, open_gerber argument check and set_sys."""
import os
import sys
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tclCommands.TclCommandHelp as TclCommandHelpModule
from defaults import AppDefaults, AppOptions
from tclCommands.TclCommandHelp import TclCommandHelp
from tclCommands.TclCommandOpenGerber import TclCommandOpenGerber
from tclCommands.TclCommandSetSys import TclCommandSetSys


class ShownText(HTMLParser):
    """The text of an HTML fragment as the shell shows it: the tags are dropped and the entities decoded."""

    def __init__(self, fragment):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(fragment)
        self.close()

    @property
    def text(self):
        return ''.join(self.parts)

    def handle_data(self, data):
        self.parts.append(data)


class TestTclHelp(unittest.TestCase):
    def test_help_without_a_name_lists_commands_and_the_usage_hint(self):
        shell = SimpleNamespace(tcl_commands_storage={'open_gerber': {'description': 'Open a Gerber file.'}},
                                append_raw=mock.Mock())
        command = SimpleNamespace(app=SimpleNamespace(shell=shell, log=mock.Mock()))
        with mock.patch.object(TclCommandHelpModule, '_', lambda text: text, create=True):
            TclCommandHelp.execute(command, {}, [])
        shown = ShownText(shell.append_raw.call_args[0][0]).text
        self.assertIn('Type help <command_name> for usage.', shown)
        self.assertIn('open_gerber', shown.split('Type help')[0])


def test_open_gerber_missing_filename_reports_error_without_crashing():
    command = TclCommandOpenGerber.__new__(TclCommandOpenGerber)
    command.raise_tcl_error = Mock()
    args, unnamed_args = command.check_args(())
    command.execute(args, unnamed_args)
    command.raise_tcl_error.assert_called_once_with("Missing required argument 'filename'.")


def make_set_sys_command():
    defaults = AppDefaults(beta=False)
    options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    app = SimpleNamespace(defaults=defaults, options=options)
    return SimpleNamespace(app=app, raise_tcl_error=Mock()), defaults, options


class TestTclSetSys(unittest.TestCase):
    def test_application_key_goes_to_defaults_and_propagates(self):
        command, defaults, _options = make_set_sys_command()
        with patch.object(AppDefaults, 'propagate_defaults') as propagate:
            TclCommandSetSys.execute(command, {'name': 'global_gridx', 'value': 2.5}, [])
        self.assertEqual(defaults['global_gridx'], 2.5)
        propagate.assert_called_once_with()
        command.raise_tcl_error.assert_not_called()

    def test_project_key_goes_to_project_and_converts_tcl_words(self):
        command, defaults, options = make_set_sys_command()
        before = defaults['units']
        TclCommandSetSys.execute(command, {'name': 'units', 'value': 'in' if before == 'MM' else 'mm'}, [])
        self.assertEqual(options['units'], 'IN' if before == 'MM' else 'MM')
        self.assertEqual(defaults['units'], before)
        command.raise_tcl_error.assert_not_called()

    def test_unknown_key_is_an_error(self):
        command, _defaults, _options = make_set_sys_command()
        TclCommandSetSys.execute(command, {'name': 'no_such_key', 'value': '1'}, [])
        command.raise_tcl_error.assert_called_once()


# ---- check_rules --------------------------------------------------------------------------------------------------
def make_check_rules(tmp_objects):
    from tclCommands.TclCommandCheckRules import TclCommandCheckRules
    from test_tcl_audit_regressions import object_app
    app = object_app(None)
    app.collection.get_by_name.side_effect = tmp_objects.get
    app.app_obj = Mock()
    return TclCommandCheckRules(app), app


def rules_objects():
    from shapely import Point, box
    top = SimpleNamespace(obj_options={'name': 'top.gtl'}, tools={},
                          solid_geometry=[box(0, 0, 1, 1), box(1.1, 0, 2, 1)])
    exc = SimpleNamespace(obj_options={'name': 'drl'}, solid_geometry=[],
                          tools={1: {'tooldia': 0.3, 'drills': [Point(0, 0), Point(1, 0)], 'slots': []}})
    return {'top.gtl': top, 'drl': exc}


def test_check_rules_counts_violations_per_rule():
    command, _app = make_check_rules(rules_objects())
    text = command.execute({'copper_top': 'top.gtl', 'exc_1': 'drl', 'c2c': 0.2, 'dh': 0.5, 'h2h': 0.1}, [])
    lines = text.splitlines()
    assert any('FAILED (1)' in line for line in lines if 'lear' in line and 'Copper' in line)
    assert any('FAILED (2)' in line for line in lines if 'Drill' in line)
    assert any('PASSED' in line for line in lines if 'Hole' in line)
    assert lines[-1].endswith('3')


def test_check_rules_unknown_object_and_no_rule_are_tcl_errors():
    from test_tcl_audit_regressions import FCShell
    command, _app = make_check_rules(rules_objects())
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'copper_top': 'nope', 'c2c': 0.2}, [])
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'copper_top': 'top.gtl'}, [])
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'c2c': 0.2}, [])  # rule enabled without its layer


def test_check_rules_writes_csv_and_a_document_without_plotting(tmp_path):
    import csv
    command, app = make_check_rules(rules_objects())
    path = tmp_path / 'report.csv'
    command.execute({'copper_top': 'top.gtl', 'c2c': 0.2, 'csv': str(path), 'outname': 'drc'}, [])
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    assert rows[0] == ['rule', 'layer', 'x', 'y', 'value', 'limit', 'status']
    assert len(rows) == 2 and rows[1][-1] == 'FAILED' and abs(float(rows[1][4]) - 0.1) < 1e-6
    args, kwargs = app.app_obj.new_object.call_args
    assert args[0] == 'document' and args[1] == 'drc' and kwargs['plot'] is False
    doc = SimpleNamespace()
    args[2](doc, app)
    assert 'FAILED' in doc.source_file


# ---- qrcode -------------------------------------------------------------------------------------------------------
def make_qrcode(units='MM', obj=None):
    from tclCommands.TclCommandQRCode import TclCommandQRCode
    from test_tcl_audit_regressions import object_app
    app = object_app(obj)
    app.app_units = units
    app.app_obj = Mock()
    return TclCommandQRCode(app), app


def qr_gerber():
    from shapely import box
    board = box(-5, -5, 60, 60)
    obj = Mock()
    obj.kind = 'gerber'
    obj.obj_options = {'name': 'board'}
    obj.solid_geometry = [board]
    obj.tools = {0: {'type': 'REG', 'size': 0.0, 'geometry': [{'solid': board, 'follow': board.exterior}]}}
    obj.bounds.return_value = (-5, -5, 60, 60)
    return obj


def test_qrcode_source_cuts_copper_and_adds_the_code():
    from shapely.ops import unary_union
    obj = qr_gerber()
    command, _app = make_qrcode(obj=obj)
    before = unary_union(obj.solid_geometry).area
    command.execute({'name': 'board', 'data': 'hello', 'x': 10, 'y': 10, 'version': 0, 'polarity': 'neg'}, [])
    assert unary_union(obj.solid_geometry).area < before
    assert len(obj.solid_geometry) > 1
    obj.regenerate_source.assert_called_once()


def test_qrcode_inch_project_uses_inch_module_size():
    from shapely.ops import unary_union
    obj = qr_gerber()
    command, _app = make_qrcode('IN', obj)
    # box_size 10 = 1 mm per module = 0.03937 in
    command.execute({'name': 'board', 'data': 'hi', 'x': 0, 'y': 0, 'box_size': 10, 'border': 0, 'version': 1,
                     'anchor': 'bl', 'polarity': 'pos', 'margin': 0.001}, [])
    qr = [g for g in obj.solid_geometry if g.bounds[0] >= -1e-6 and g.bounds[2] < 1]
    width = unary_union(qr).bounds[2]
    assert 21 * 0.03937 * 0.9 < width <= 21 * 0.03937 + 0.0025  # + the 0.001 margin cut


def test_qrcode_overflow_and_bad_input_are_tcl_errors_without_change():
    from test_tcl_audit_regressions import FCShell
    obj = qr_gerber()
    geometry, tools = list(obj.solid_geometry), obj.tools
    command, _app = make_qrcode(obj=obj)
    for args in ({'name': 'board', 'data': 'x' * 500, 'version': 1},
                 {'name': 'board', 'data': 'x', 'rotation': 45},
                 {'name': 'board', 'data': 'x', 'anchor': 'zz'},
                 {'name': 'board', 'data': 'x', 'output': 'nowhere'}):
        with pytest.raises(FCShell.TclErrorException):
            command.execute(args, [])
    assert obj.solid_geometry == geometry and obj.tools is tools
    obj.regenerate_source.assert_not_called()
    command, _app = make_qrcode(obj=None)
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'name': 'nope', 'data': 'x'}, [])
    obj.kind = 'excellon'
    command, _app = make_qrcode(obj=obj)
    with pytest.raises(FCShell.TclErrorException):
        command.execute({'name': 'board', 'data': 'x'}, [])


def test_qrcode_new_object_holds_only_the_code_and_does_not_plot():
    command, app = make_qrcode()
    command.execute({'data': 'hello', 'output': 'new', 'outname': 'qr_label', 'x': 5, 'y': 5, 'version': 1}, [])
    args, kwargs = app.app_obj.new_object.call_args
    assert args[0] == 'gerber' and args[1] == 'qr_label' and kwargs['plot'] is False
    new = Mock()
    new.obj_options = {}
    new.bounds.return_value = (5, 5, 30, 30)
    args[2](new, app)
    assert len(new.solid_geometry) > 1 and 10 in new.tools
    new.regenerate_source.assert_called_once()


@pytest.mark.slow
def test_qrcode_source_insert_is_one_undo_step():
    import sys
    from PyQt6 import QtWidgets
    from shapely import box
    from shapely.ops import unary_union
    import appHandlers.appHistory as appHistory
    from appMain import App
    from test_tcl_audit_regressions import FCShell
    from tclCommands.TclCommandQRCode import TclCommandQRCode
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    fc = App(qapp=qapp, headless=True)
    appHistory.RECORD_IN_HEADLESS = True
    try:
        def init(obj, _app):
            board = box(0, 0, 50, 50)
            obj.solid_geometry = [board]
            obj.tools = {0: {'type': 'REG', 'size': 0.0, 'geometry': [{'solid': board, 'follow': board.exterior}]}}
        obj = fc.app_obj.new_object('gerber', 'board', init, plot=False)
        area = unary_union(obj.solid_geometry).area
        steps = len(fc.history.undo_stack)
        command = TclCommandQRCode(fc)
        command.execute({'name': 'board', 'data': 'hello', 'x': 10, 'y': 10, 'polarity': 'neg'}, [])
        assert unary_union(obj.solid_geometry).area < area
        assert len(fc.history.undo_stack) == steps + 1
        fc.history.undo()
        assert unary_union(obj.solid_geometry).area == pytest.approx(area)
    finally:
        appHistory.RECORD_IN_HEADLESS = False
