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
    assert command.execute({'name': 'g', 'all': None, 'order': 'rev', 'method': 'seed', 'connect': 'yes'}, []) == 'fail'
    kwargs = app.ncclear_tool.gen.clear_copper_tcl.call_args.kwargs
    assert kwargs['order'] == 2
    assert kwargs['method'] == 1
    assert kwargs['connect'] is True


def _ncc_run(args, source_kind='gerber', other=None):
    objects = {'g': SimpleNamespace(kind=source_kind, decimals=4)}
    objects.update(other or {})
    app = factory_app(objects['g'])
    app.collection.get_by_name.side_effect = lambda n: objects.get(n)
    app.ncclear_tool = Mock()
    app.ncclear_tool.gen.clear_copper_tcl.return_value = None
    app.dec_format = lambda value, decimals: round(value, decimals)
    TclCommandCopperClear(app).execute(dict({'name': 'g'}, **args), [])
    return app.ncclear_tool.gen.clear_copper_tcl.call_args.kwargs


@pytest.mark.parametrize('rest,expected', [('1', 'g_ncc_rm'), ('0', 'g_ncc')])
def test_ncc_default_output_name_marks_rest_machining(rest, expected):
    assert _ncc_run({'all': None, 'rest': rest})['outname'] == expected


def test_ncc_unset_options_are_left_to_the_preferences_and_offset_flag_follows_the_argument():
    kwargs = _ncc_run({'all': None})
    for key in ('margin', 'has_offset', 'offset', 'overlap', 'connect', 'contour', 'order', 'method', 'rest',
                'final_cleanup', 'milling_type', 'simplification', 'iso_tooldia', 'exclusion_areas'):
        assert kwargs[key] is None
    assert kwargs['plot'] is False
    kwargs = _ncc_run({'all': None, 'offset': 0.2})
    assert (kwargs['has_offset'], kwargs['offset']) == (True, 0.2)


def test_ncc_new_options_reach_the_generator():
    kwargs = _ncc_run({'all': None, 'iso_tooldia': '0.2,0.1', 'milling_type': 'cv', 'final_cleanup': '1',
                       'simplification': 0.02, 'method': 'combo', 'plot': '1'})
    assert kwargs['iso_tooldia'] == [0.2, 0.1]
    # the isolation paths need tool entries of their own
    iso = sorted(t['tooldia'] for t in kwargs['tools_storage'].values() if t['data']['tools_ncc_operation'] == 'iso')
    assert iso == [0.1, 0.2]
    assert kwargs['milling_type'] == 'cv'
    assert kwargs['final_cleanup'] is True
    assert kwargs['simplification'] == 0.02
    assert kwargs['method'] == 3
    assert kwargs['plot'] is True


def test_ncc_area_and_exclude_become_polygons():
    square = box(0, 0, 1, 1)
    other = {'keep': SimpleNamespace(kind='geometry', solid_geometry=[square, box(5, 5, 6, 6)])}
    kwargs = _ncc_run({'area': '0,0,10,5', 'exclude': 'keep'}, other=other)
    assert kwargs['select_method'] == 1
    assert kwargs['areas_to_clear_list'][0].bounds == (0, 0, 10, 5)
    assert len(kwargs['exclusion_areas']) == 2


@pytest.mark.parametrize('args,kind', [
    ({'all': None, 'area': '0,0,1,1'}, 'gerber'),
    ({'area': '1,1,0,0'}, 'gerber'),
    ({'all': None, 'iso_tooldia': '0.2'}, 'geometry'),
    ({'all': None, 'milling_type': 'cv'}, 'gerber'),
    ({'all': None, 'milling_type': 'xx', 'iso_tooldia': '0.2'}, 'gerber'),
    ({'all': None, 'exclude': 'lines'}, 'gerber'),
    ({'all': None, 'tooldia': '0.2', 'iso_tooldia': '0.2'}, 'gerber'),
])
def test_ncc_rejects_inconsistent_new_options(args, kind):
    other = {'lines': SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 1, 1).exterior])}
    with pytest.raises(FCShell.TclErrorException):
        _ncc_run(args, source_kind=kind, other=other)


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



def paint_command(units='MM', **options):
    from tclCommands.TclCommandPaint import TclCommandPaint
    obj = SimpleNamespace(kind='geometry', decimals=4)
    app = factory_app(obj)
    app.app_units = units
    app.decimals = 4
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.options.update(options)
    app.paint_tool = SimpleNamespace(gen=Mock())
    return TclCommandPaint(app), app, app.paint_tool.gen


def test_paint_passes_rest_options_explicitly_and_converts_simplification_to_inches():
    command, app, gen = paint_command(units='IN', tools_paint_rest_offset=0.2, tools_paint_simplification=0.254)
    gen.paint_poly_all.return_value = None
    command.execute({'name': 'g', 'tooldia': '0.5', 'final_cleanup': '1'}, [])
    kwargs = gen.paint_poly_all.call_args.kwargs
    assert kwargs['rest'] is False and kwargs['rest_offset'] == 0.2 and kwargs['simplification'] == pytest.approx(0.01)
    assert kwargs['tools_storage'][1]['data']['tools_paint_final_cleanup'] is True
    command.execute({'name': 'g', 'rest': 'yes', 'rest_offset': 0.1, 'simplification': 0.0}, [])
    kwargs = gen.paint_poly_all.call_args.kwargs
    assert kwargs['rest'] is True and kwargs['rest_offset'] == 0.1 and kwargs['simplification'] == 0.0
    assert kwargs['tools_storage'][1]['data']['tools_paint_final_cleanup'] is False


def test_paint_ref_box_and_area_select_the_painted_polygons():
    command, app, gen = paint_command()
    command.execute({'name': 'g', 'ref': 'r'}, [])
    command.execute({'name': 'g', 'box': 'r'}, [])
    assert gen.paint_poly_ref.call_count == 2
    assert gen.paint_poly_ref.call_args.kwargs['sel_obj'] is app.collection.get_by_name.return_value
    command.execute({'name': 'g', 'area': '0,1,4,3'}, [])
    assert gen.paint_poly_area_worker.call_args.kwargs['areas_to_paint'].bounds == (0, 1, 4, 3)
    assert gen.paint_poly_area_worker.call_args.kwargs['plot'] is False
    for args in ({'single': '1,1', 'area': '0,0,1,1'}, {'ref': 'r', 'box': 'r'}, {'area': '0,0,1'},
                 {'area': '0,0,0,5'}, {'single': '1'}, {'single': 'x'}):
        with pytest.raises(FCShell.TclErrorException):
            command.execute(dict(args, name='g'), [])


def test_paint_reports_bad_values_and_failures_to_the_script():
    command, app, gen = paint_command()
    for args in ({'method': 'zigzag'}, {'overlap': 100.0}, {'overlap': -1.0}, {'rest_offset': float('nan')},
                 {'offset': float('inf')}, {'simplification': -0.1}):
        with pytest.raises(FCShell.TclErrorException):
            command.execute(dict(args, name='g'), [])
    for method, extra in (('paint_poly_all', {}), ('paint_poly', {'single': '1,1'}),
                          ('paint_poly_ref', {'ref': 'r'}), ('paint_poly_area_worker', {'area': '0,0,1,1'})):
        getattr(gen, method).return_value = 'fail'
        with pytest.raises(FCShell.TclErrorException):
            command.execute(dict(extra, name='g'), [])


def test_paint_drops_duplicate_tool_diameters_keeping_the_order():
    command, app, gen = paint_command()
    command.execute({'name': 'g', 'tooldia': '0.5,0.2,0.50001,0.5'}, [])
    tools = gen.paint_poly_all.call_args.kwargs['tools_storage']
    assert [tool['tooldia'] for tool in tools.values()] == [0.5, 0.2]
