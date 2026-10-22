"""Selection, factory and multipart output contracts for clearing and cutout commands."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely import box
from shapely.ops import unary_union

from tclCommands.TclCommandCopperClear import TclCommandCopperClear
from tclCommands.TclCommandCutout import TclCommandCutout
from tclCommands.TclCommandGeoCutout import TclCommandGeoCutout
from tclCommands.TclCommandPanelize import TclCommandPanelize
from test_tcl_audit_generation import factory_app
from test_tcl_audit_regressions import FCShell, qt_app


def test_ncc_dispatches_integer_method_and_order_and_propagates_failure():
    obj = SimpleNamespace(kind='gerber', decimals=4)
    app = factory_app(obj)
    app.ncclear_tool = Mock()
    app.ncclear_tool.gen.clear_copper_tcl.return_value = 'fail'
    app.dec_format = lambda value, decimals: round(value, decimals)
    command = TclCommandCopperClear(app)
    assert command.execute({'name': 'g', 'all': None, 'order': 'rev', 'connect': 'yes'}, []) == 'fail'
    kwargs = app.ncclear_tool.gen.clear_copper_tcl.call_args.kwargs
    assert kwargs['order'] == 2
    assert isinstance(kwargs['method'], int)
    assert kwargs['connect'] is True


def test_cutout_keeps_all_input_components():
    source = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 2, 2).exterior,
                                                              box(10, 0, 12, 2).exterior],
                             bounds=lambda: (0, 0, 12, 2))
    app = factory_app(source)
    app.cutout_tool = Mock()
    app.cutout_tool.any_cutout_handler.side_effect = lambda geo, *args: ([geo], [])
    output = SimpleNamespace(obj_options={})
    app.app_obj.new_object.side_effect = lambda kind, name, init, **kw: init(output, app)
    TclCommandCutout(app).execute({'name': 'g', 'dia': 1, 'gaps': 'none'}, [])
    assert unary_union(output.solid_geometry).bounds == (0, 0, 12, 2)


def test_geoc_gap_names_are_case_insensitive_and_center_is_not_offset_by_margin():
    source = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 10, 10).exterior],
                             obj_options={}, bounds=lambda: (0, 0, 10, 10))
    app = factory_app(source)
    app.disable_plots = Mock()
    outputs = []

    def create(kind, name, init, **kwargs):
        output = SimpleNamespace(obj_options={})
        init(output, app)
        outputs.append(output)

    app.app_obj.new_object.side_effect = create
    command = TclCommandGeoCutout(app)
    for gap in ('tb', 'TB'):
        command.execute({'name': 'g', 'dia': 1, 'margin': 0, 'gapsize': 1, 'gaps': gap}, [])
    first, second = (unary_union(o.solid_geometry) for o in outputs)
    assert first.equals(second)
    assert first.length < source.solid_geometry[0].length


def test_panelize_factory_failure_is_not_announced_as_done():
    obj = SimpleNamespace(kind='geometry', bounds=lambda: (0, 0, 1, 1))
    app = factory_app(obj)
    app.abort_flag = False
    app.app_obj.new_object.return_value = 'fail'
    result = TclCommandPanelize(app).execute({'name': 'g', 'rows': 2}, [])
    assert result == 'fail'
    assert not any('[success]' in str(call) for call in app.inform.emit.call_args_list)

