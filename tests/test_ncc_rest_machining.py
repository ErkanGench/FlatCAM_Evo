"""Exercise the GUI rest worker without starting the application or plotting."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString, MultiPolygon, box

from appPlugins.ToolNCC.NccGen import NccGen


def run_rest(area, tools, clear, tcl=False, source=None, rest=True, known=None):
    gen = NccGen.__new__(NccGen)
    defaults = {'tools_ncc_plotting': 'normal', 'tools_ncc_cutz': -0.1, 'tools_ncc_tools': '(4, 1)'}
    app = SimpleNamespace(
        units='MM', app_units='MM', options=defaults, defaults=SimpleNamespace(get=defaults.get, factory_defaults=defaults),
        log=Mock(), inform=Mock(), proc_container=Mock(), abort_flag=False,
        dec_format=lambda value, decimals: round(value, decimals),
    )
    gen.app = app
    gen.decimals = 4
    gen.circle_steps = 32
    gen.obj_name = 'board'
    gen.ncc_tools = {
        uid: {'tooldia': dia, 'data': {'tools_ncc_overlap': 20, 'tools_ncc_method': 0}, 'solid_geometry': []}
        for uid, dia in enumerate(tools if known is None else known, 1)
    }
    gen.ui = SimpleNamespace(**{
        name: SimpleNamespace(get_value=lambda value=value: value)
        for name, value in {
            'order_combo': 0, 'select_method_combo': 0, 'rest_cb': True,
            'margin_entry': 1, 'rest_margin_entry': 3, 'rest_connect_cb': False,
            'rest_contour_cb': True, 'rest_offset_choice_cb': False, 'rest_offset_entry': 0,
        }.items()
    })
    output = SimpleNamespace(kind='geometry', tools={}, obj_options={})
    def new_object(kind, name, worker, **kwargs):
        gen.worker_result = worker(output, app)
        return gen.worker_result

    gen.parent_tool = SimpleNamespace(new_object=new_object)
    gen.compute_clipping_region = Mock(return_value=(area, 'geometry'))
    gen.apply_margin_to_clipping_region = Mock(return_value=area)
    gen.compute_area_to_clear = Mock(return_value=(area, 0))
    gen.clear_polygon_worker = Mock(side_effect=clear)
    if tcl:
        app.app_obj = gen.parent_tool
        gen._compute_area_to_clear_handler = Mock(return_value=area)
        gen.parent_tool.flatten_list = lambda paths: [line for group in paths for line in group]

        def clear_shrink(pol, dia, *args, **kwargs):
            paths = clear(pol=pol, tooldia=round(dia, 4))
            return SimpleNamespace(get_objects=lambda: paths) if paths else None

        gen.parent_tool.clear_polygon_shrink = Mock(side_effect=clear_shrink)
        gen.result = gen.clear_copper_tcl(
            source or SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 1, 1)]),
            ncc_tooldia=tools, iso_tooldia=[], margin=0, has_offset=True, offset=0.1,
            select_method=1, areas_to_clear_list=[box(0, 0, 10, 10)], overlap=0.2,
            connect=False, contour=True, order=0 if not rest else 2, method=0, rest=rest, run_threaded=False,
        )
    else:
        gen.ncc_handler(SimpleNamespace(kind='geometry'), tools, [], run_threaded=False)
    return gen, output


def test_smaller_tool_is_tried_when_largest_cannot_fit():
    gen, output = run_rest(MultiPolygon([box(0, 0, 2, 2)]), [4.0, 1.0],
                           lambda **kw: [LineString([(0.5, 1), (1.5, 1)])])
    assert [call.kwargs['tooldia'] for call in gen.clear_polygon_worker.call_args_list] == [1.0]
    assert output.tools[2]['solid_geometry']


def test_rest_margin_and_exact_swept_area_are_used():
    area = MultiPolygon([box(0, 0, 10, 10)])
    line = LineString([(2, 5), (8, 5)])
    residuals = []

    def clear(**kw):
        if kw['tooldia'] == 2:
            return [line, line]
        residuals.append(kw['pol'])
        return [LineString([(1, 1), (2, 1)])]

    gen, output = run_rest(area, [1.0, 2.0], clear)
    assert gen.apply_margin_to_clipping_region.call_args.kwargs['margin'] == 3
    assert gen.compute_area_to_clear.call_args.kwargs['margin'] == 3
    assert residuals[0].symmetric_difference(area.difference(line.buffer(1))).area < 1e-10
    assert list(output.tools) == [2, 1]


def test_area_failure_does_not_attempt_clearing():
    gen, output = run_rest('fail', [2.0, 1.0], lambda **kw: pytest.fail('unexpected clearing'))
    gen.clear_polygon_worker.assert_not_called()
    assert not output.tools
    assert gen.worker_result == 'fail'


def test_tcl_smaller_tool_receives_only_unswept_stock():
    area = MultiPolygon([box(0, 0, 10, 10)])
    line = LineString([(2, 5), (8, 5)])
    residuals = []

    def clear(**kw):
        if kw['tooldia'] == 2:
            return [line, line]
        residuals.append(kw['pol'])
        return [LineString([(1, 1), (2, 1)])]

    gen, output = run_rest(area, [1.0, 2.0], clear, tcl=True)
    assert residuals[0].symmetric_difference(area.difference(line.buffer((2 - 1e-12) / 2))).area < 1e-10
    assert list(output.tools) == [2, 1]


def test_tcl_skipped_unknown_tool_does_not_change_next_tool_offset():
    area = MultiPolygon([box(0, 0, 10, 10)])
    seen = []

    def run(tools, known):
        seen.append([])

        def clear(**kw):
            seen[-1].append(kw['pol'])
            return [LineString([(1, 1), (2, 1)])]

        run_rest(area, tools, clear, tcl=True, rest=False, known=known)

    run([2.0, 1.0], [2.0, 1.0])
    run([2.0, 0.5, 1.0], [2.0, 1.0])
    assert len(seen[0]) == len(seen[1])
    assert seen[0][-1].symmetric_difference(seen[1][-1]).area < 1e-10


def test_tcl_empty_area_reports_why():
    gen, output = run_rest('fail', [2.0], lambda **kw: None, tcl=True)
    messages = [call.args[0] for call in gen.app.inform.emit.call_args_list]
    assert any(m.startswith('[ERROR_NOTCL]') for m in messages)


def test_tool_without_geometry_is_reported():
    gen, output = run_rest(MultiPolygon([box(0, 0, 10, 10)]), [2.0], lambda **kw: None, tcl=True, rest=False)
    messages = [call.args[0] for call in gen.app.inform.emit.call_args_list]
    assert any(m.startswith('[WARNING_NOTCL]') and 'diameter' in m for m in messages)
