"""Headless NCC regressions and repeatable board-like generation timings.

Timings: .venv/Scripts/python.exe -m pytest tests/test_ncc_followups.py -k benchmark -s
These exercise geometry generation, not application startup, rendering or CNC hardware.
"""
import json
from math import cos, pi
from statistics import median
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from shapely import LineString, MultiPolygon, Point, box
from shapely.affinity import scale
from shapely.ops import unary_union

import camlib
from appPlugins.ToolNCC.NccGen import NccGen


def board():
    copper = unary_union([
        Point(x, y).buffer(0.9, quad_segs=8)
        for x in range(4, 38, 4) for y in range(4, 26, 4)
    ] + [box(3, 13.8, 37, 14.2), box(19.8, 3, 20.2, 27)])
    return box(0, 0, 40, 30), copper


def generator(rest=False, units='MM', offsets=(0, 0, 0), method=0):
    gen = NccGen.__new__(NccGen)
    options = {'tools_ncc_plotting': 'normal', 'tools_ncc_cutz': -0.1,
               'tools_ncc_tools': '(2, 1, 0.5)', 'global_tolerance': 0.005,
               'gerber_buffering': 'full', 'tools_ncc_milling_type': 'cv'}
    app = SimpleNamespace(
        units=units, app_units=units, options=options,
        defaults=SimpleNamespace(get=options.get, factory_defaults=options),
        log=Mock(), inform=Mock(), inform_shell=Mock(), inform_no_echo=Mock(),
        proc_container=Mock(), abort_flag=False,
        dec_format=lambda v, d=4: round(v, d),
    )
    gen.app, gen.decimals, gen.circle_steps, gen.obj_name = app, 6, 32, 'board'
    factor = 1 if units == 'MM' else 1 / 25.4
    tools = [dia * factor for dia in (2, 1, 0.5)]
    gen.ncc_tools = {
        uid: {'tooldia': dia, 'solid_geometry': [], 'data': {
            'tools_ncc_overlap': 20, 'tools_ncc_method': method,
            'tools_ncc_connect': False, 'tools_ncc_contour': True,
            'tools_ncc_offset_choice': bool(offset), 'tools_ncc_offset_value': offset * factor,
        }} for uid, (dia, offset) in enumerate(zip(tools, offsets), 1)
    }
    gen.ui = SimpleNamespace(**{
        name: SimpleNamespace(get_value=lambda v=v: v) for name, v in {
            'order_combo': 0, 'select_method_combo': 0, 'rest_cb': rest,
            'margin_entry': 0, 'rest_margin_entry': 0, 'rest_connect_cb': False,
            'rest_contour_cb': True, 'rest_offset_choice_cb': False,
            'rest_offset_entry': 0, 'milling_type_radio': 'cv',
        }.items()
    })
    boundary, copper = board()
    boundary, copper = [scale(g, xfact=factor, yfact=factor, origin=(0, 0)) for g in (boundary, copper)]
    source = SimpleNamespace(kind='gerber', solid_geometry=list(copper.geoms))
    output = SimpleNamespace(kind='geometry', tools={}, obj_options={})
    geometry = camlib.Geometry.__new__(camlib.Geometry)
    geometry.app = app
    geometry.temp_shapes = Mock()
    geometry.plot_temp_shapes = Mock()

    def new_object(kind, name, worker, **kwargs):
        gen.worker_result = worker(output, app)
        return gen.worker_result

    geometry.new_object = new_object
    gen.parent_tool = geometry
    gen.compute_clipping_region = Mock(return_value=(boundary, 'gerber'))
    gen.apply_margin_to_clipping_region = Mock(return_value=boundary)
    return gen, output, source, tools, boundary, copper


def generate(gen, source, tools, iso=()):
    gen.ncc_handler(source, tools, list(iso), run_threaded=False)


def test_normal_preparation_reused_only_for_equivalent_offsets():
    gen, output, source, tools, _, _ = generator(offsets=(0.1, 0.2, 0.1))
    gen.compute_area_to_clear = Mock(wraps=gen.compute_area_to_clear)
    generate(gen, source, tools)
    assert len(output.tools) == 3
    assert gen.compute_area_to_clear.call_count == 2
    generate(gen, source, tools)
    assert gen.compute_area_to_clear.call_count == 4  # no cross-generation stale cache


def test_normal_isolation_preparation_preserves_output_side_effects():
    gen, output, source, tools, _, copper = generator()
    gen.ncc_tools[4] = {'tooldia': 0.2, 'data': {}, 'solid_geometry': []}
    gen.generate_envelope = Mock(return_value=copper.buffer(0.1))
    gen.poly2rings = lambda p: [p.exterior, *p.interiors]
    generate(gen, source, tools, [0.2])
    assert gen.generate_envelope.call_count == 1
    assert output.tools[4]['solid_geometry']
    assert output.tools[4]['data']['name'] == 'board_ncc'
    assert len(output.tools) == 4


@pytest.mark.parametrize('units', ['MM', 'IN'])
def test_tolerance_is_unit_aware_and_input_features_are_not_simplified(units):
    gen, output, source, tools, boundary, _ = generator(units=units)
    factor = 1 if units == 'MM' else 1 / 25.4
    # A small copper tooth must survive input preparation even with a large display tolerance.
    area = box(0, 0, 4, 4).difference(box(1.999, 1.9, 2.001, 4))
    area = scale(area, xfact=factor, yfact=factor, origin=(0, 0))
    gen.compute_area_to_clear = Mock(return_value=(MultiPolygon([area]), 0))
    gen.clear_polygon_worker = Mock(return_value=[LineString([(factor, factor), (2*factor, factor)])])
    generate(gen, source, tools)
    for call in gen.clear_polygon_worker.call_args_list:
        assert call.kwargs['simplify_tol'] == pytest.approx(0.005 * factor)
        assert call.kwargs['pol'].symmetric_difference(area).area < 1e-15


@pytest.mark.parametrize('units', ['MM', 'IN'])
def test_output_simplification_never_cuts_across_copper(units):
    gen, _, _, _, _, _ = generator(units=units)
    factor = 1 if units == 'MM' else 1 / 25.4
    # The short detour avoids a copper tooth. Douglas-Peucker alone erases it.
    path = LineString([(0, 0), (1, 0), (1, 0.01), (1.01, 0.01), (1.01, 0), (2, 0)])
    path = scale(path, xfact=factor, yfact=factor, origin=(0, 0))
    area = path.buffer(0.001 * factor)
    gen.parent_tool.clear_polygon_shrink = Mock(return_value=SimpleNamespace(
        objects=[path], get_objects=lambda: [path]))
    result = gen.clear_polygon_worker(area, 0.002 * factor, 0, 0.2, False, True, False,
                                      simplify_tol=0.02 * factor)
    assert result[0].equals(path)


def test_milling_selection_follows_table_order_not_click_order():
    from appPlugins.ToolMilling import ToolMilling
    milling = ToolMilling.__new__(ToolMilling)
    tools = {9: {'tooldia': 2}, 2: {'tooldia': 1}, 7: {'tooldia': 0.5}}
    target = SimpleNamespace(tools=tools)
    milling.app = SimpleNamespace(log=Mock(), collection=SimpleNamespace(get_by_name=lambda _: target))
    table = Mock()
    table.selectedItems.return_value = [SimpleNamespace(row=lambda r=r: r) for r in (2, 0, 1, 0)]
    table.item.side_effect = lambda row, col: SimpleNamespace(text=lambda: str(list(tools)[row]))
    milling.ui = SimpleNamespace(object_combo=SimpleNamespace(currentText=lambda: 'board'), tools_table_mill_geo=table)
    milling.sel_tools = {}
    milling.generate_cnc_job_handler = Mock()
    milling.on_generate_cnc_from_geo()
    assert list(milling.sel_tools) == [9, 2, 7]
    # Explicit user reordering of rows remains authoritative, rather than diameter sorting.
    table.item.side_effect = lambda row, col: SimpleNamespace(text=lambda: str([7, 9, 2][row]))
    milling.on_generate_cnc_from_geo()
    assert list(milling.sel_tools) == [7, 9, 2]


def test_envelope_uses_generator_copper_and_radius():
    gen, _, _, _, _, copper = generator()
    gen.solid_geometry = copper
    gen.parent_tool.solid_geometry = []
    gen.parent_tool.geo_steps_per_circle = 32
    for invert in (0, 1):
        envelope = gen.generate_envelope(0.1, invert)
        assert envelope.symmetric_difference(copper.buffer(0.1, quad_segs=32)).area < 1e-10


@pytest.mark.parametrize('explicit_reverse', [False, True])
@pytest.mark.parametrize('from_tcl', [False, True])
def test_rest_order_reaches_multigeometry_cnc_execution(explicit_reverse, from_tcl):
    from appPlugins.ToolMilling import ToolMilling
    from defaults import AppDefaults
    gen, output, source, tools, _, _ = generator(rest=True)
    generate(gen, source, tools)
    defaults = dict(AppDefaults.factory_defaults)
    gen.app.options.update(defaults)
    output.obj_options.update(defaults)
    output.obj_options.update(name='board_ncc', xmin=0, ymin=0, xmax=40, ymax=30)
    for tool in output.tools.values():
        tool['data'].update(defaults)
        tool['data']['tools_mill_tooldia'] = tool['tooldia']
    ordered = dict(reversed(list(output.tools.items()))) if explicit_reverse else dict(output.tools)
    calls = []
    job = SimpleNamespace(kind='cncjob', tools={}, obj_options={}, gc_start='',
                          gcode_parse=Mock(return_value=[]))
    def gcode(uid, storage, **kwargs):
        calls.append((uid, kwargs['is_first'], kwargs['is_last']))
        return 'T%s\n' % uid, ''
    job.geometry_tool_gcode_gen = gcode
    def new_object(kind, name, worker, **kwargs):
        result = worker(job, gen.app)
        assert result != 'fail'
        return job
    milling = SimpleNamespace(app=gen.app, units='MM', decimals=6,
                              target_obj=output, sel_tools=ordered, new_object=new_object)
    result = ToolMilling.generate_cnc_job_handler(
        milling, geo_obj=output, tools_dict=ordered, toolchange=True,
        use_thread=False, plot=False, from_tcl=from_tcl)
    assert result != 'fail'
    assert [uid for uid, _, _ in calls] == list(ordered)
    assert calls[0][1] and calls[-1][2]
    assert list(job.tools) == list(ordered)
    assert job.source_file == ''.join('T%s\n' % uid for uid in ordered)


def test_tcl_rest_isolation_uses_radius():
    gen, output, source, tools, boundary, copper = generator(rest=True)
    gen.ncc_tools[4] = {'tooldia': 0.2, 'data': {}, 'solid_geometry': []}
    gen.generate_envelope = Mock(return_value=copper.buffer(0.1))
    gen.poly2rings = lambda poly: [poly.exterior, *poly.interiors]
    gen.app.app_obj = gen.parent_tool
    gen.parent_tool.flatten_list = lambda paths: [p for group in paths for p in group]
    result = gen.clear_copper_tcl(
        source, ncc_tooldia=tools, iso_tooldia=[0.2], margin=0, has_offset=False, offset=0,
        select_method=1, areas_to_clear_list=[boundary], overlap=0.2, connect=False,
        contour=True, order=2, method=0, rest=True, run_threaded=False,
    )
    assert result != 'fail'
    assert gen.generate_envelope.call_args.args[0] == 0.1
    assert output.tools[4]['solid_geometry']


@pytest.mark.parametrize('milling', ['cv', 'cl'])
def test_gui_and_tcl_isolation_paths_match_on_board(milling):
    outputs = []
    for tcl in (False, True):
        gen, output, source, tools, boundary, _ = generator(rest=True)
        gen.ncc_tools[4] = {'tooldia': 0.2, 'data': {}, 'solid_geometry': []}
        gen.parent_tool.geo_steps_per_circle = 32
        gen.poly2rings = lambda poly: [poly.exterior, *poly.interiors]
        gen.app.options['tools_ncc_milling_type'] = milling
        gen.ui.milling_type_radio.get_value = lambda: milling
        if tcl:
            gen.app.app_obj = gen.parent_tool
            gen.parent_tool.flatten_list = lambda paths: [p for group in paths for p in group]
            result = gen.clear_copper_tcl(
                source, ncc_tooldia=tools, iso_tooldia=[0.2], margin=0, has_offset=False,
                offset=0, select_method=1, areas_to_clear_list=[boundary], overlap=0.2,
                connect=False, contour=True, order=2, method=0, rest=True, run_threaded=False)
            assert result != 'fail'
        else:
            generate(gen, source, tools, [0.2])
        assert output.tools[4]['solid_geometry']
        outputs.append(unary_union(output.tools[4]['solid_geometry']))
    assert outputs[0].symmetric_difference(outputs[1]).length < 1e-9


@pytest.mark.parametrize('method', ['shrink', 'lines', 'seed'])
def test_clearing_throttles_events_and_redraws_but_finishes_plot(method):
    gen, _, _, _, boundary, copper = generator()
    geo = gen.parent_tool
    with patch.object(camlib, 'monotonic', return_value=1), \
            patch.object(camlib.QtWidgets.QApplication, 'processEvents') as events:
        result = getattr(geo, 'clear_polygon_' + method)(
            boundary.difference(copper), 0.5, 32, connect=False, prog_plot=True)
    assert result.objects
    assert geo.temp_shapes.redraw.call_count < 10
    assert events.call_count > 0
    assert geo.temp_shapes.redraw.called
    assert geo.plot_temp_shapes.called


@pytest.mark.parametrize('method', ['shrink', 'lines', 'seed'])
def test_event_processing_is_not_throttled_with_redraws(method):
    gen, _, _, _, _, _ = generator()
    count = 0
    def abort_on_second_event():
        nonlocal count
        count += 1
        if count == 2:
            gen.app.abort_flag = True
    with patch.object(camlib, 'monotonic', return_value=1), \
            patch.object(camlib.QtWidgets.QApplication, 'processEvents', side_effect=abort_on_second_event):
        with pytest.raises(camlib.grace):
            getattr(gen.parent_tool, 'clear_polygon_' + method)(box(0, 0, 20, 10), 0.5, 32, connect=False)
    assert count == 2


@pytest.mark.parametrize('method', ['shrink', 'lines', 'seed'])
@pytest.mark.parametrize('vertical', [False, True])
def test_clearing_cancels_immediately_after_processing_events(method, vertical):
    gen, _, _, _, _, _ = generator()
    geo = gen.parent_tool
    area = box(0, 0, 10, 20) if vertical else box(0, 0, 20, 10)
    def abort():
        gen.app.abort_flag = True
    with patch.object(camlib.QtWidgets.QApplication, 'processEvents', side_effect=abort):
        with pytest.raises(camlib.grace):
            getattr(geo, 'clear_polygon_' + method)(area, 0.5, 32, connect=False)


def legacy_shrink(area, dia, steps=32):
    """Pre-follow-up algorithm retained as a geometric oracle, not production code."""
    q = camlib.circle_quad_segs(steps)
    paths = []
    current = camlib.flatten_shapely_geometry(area.buffer(-dia / 2, quad_segs=q))
    for p in current:
        paths.extend([p.exterior, *p.interiors])
    for p in current:
        while True:
            p = p.buffer(-dia * 0.85, quad_segs=q)
            polygons = [g for g in camlib.flatten_shapely_geometry(p) if g.area > 0]
            if not polygons:
                break
            for g in polygons:
                paths.extend([g.exterior, *g.interiors])
            p = unary_union(polygons)
    return paths


def test_shrink_matches_legacy_swept_geometry():
    gen, _, _, _, boundary, copper = generator()
    area = boundary.difference(copper)
    old = legacy_shrink(area, 0.5)
    new = list(gen.parent_tool.clear_polygon_shrink(area, 0.5, 32, connect=False).get_objects())
    assert len(old) == len(new)
    assert all(a.hausdorff_distance(b) < 1e-9 for a, b in zip(old, new))
    old_sweep = unary_union([p.buffer(0.25) for p in old])
    new_sweep = unary_union([p.buffer(0.25) for p in new])
    assert old_sweep.symmetric_difference(new_sweep).area < 1e-9


def test_shrink_does_not_reunion_single_buffer_component(monkeypatch):
    gen, _, _, _, _, _ = generator()
    monkeypatch.setattr(camlib, 'unary_union', Mock(side_effect=AssertionError('redundant union')))
    assert gen.parent_tool.clear_polygon_shrink(box(0, 0, 40, 30), 0.5, 32, connect=False).objects


def test_board_generation_benchmark():
    report = {}
    overlaps = []
    for rest in (False, True):
        times = []
        for _ in range(3):
            gen, output, source, tools, boundary, copper = generator(rest=rest)
            start = perf_counter()
            generate(gen, source, tools)
            times.append(perf_counter() - start)
            assert output.tools
            if rest:
                diameters = [t['tooldia'] for t in output.tools.values()]
                assert diameters == sorted(diameters, reverse=True)
            else:
                assert len(output.tools) == 3
            swept = unary_union([p.buffer(t['tooldia'] / 2) for t in output.tools.values()
                                 for p in t['solid_geometry']])
            # Round buffers are polygonal approximations. Bound intrusion by their
            # maximum radial error, not an arbitrary aggregate overlap area.
            q = camlib.circle_quad_segs(gen.circle_steps)
            radial_error = max(gen.app.options['global_tolerance'],
                               max(tools) / 2 * (1 / cos(pi / (4 * q)) - 1)) + 1e-7
            overlaps.append((swept.intersection(copper.buffer(-radial_error)).area,
                             swept.difference(boundary.buffer(radial_error)).area))
        report['rest' if rest else 'normal'] = {
            'median_seconds': median(times), 'samples': times,
            'paths': sum(len(t['solid_geometry']) for t in output.tools.values()),
            'swept_area': swept.area, 'copper_overlap': swept.intersection(copper).area,
        }
    print('\nNCC_BOARD_BENCHMARK ' + json.dumps(report))
    assert all(copper_overlap < 1e-8 and outside < 1e-8 for copper_overlap, outside in overlaps)


def test_shared_clearing_benchmark():
    boundary, copper = board()
    area = boundary.difference(copper)
    report = {}
    for method in ('shrink', 'lines', 'seed'):
        gen, _, _, _, _, _ = generator()
        geo = gen.parent_tool
        times = []
        for _ in range(5):
            start = perf_counter()
            paths = getattr(geo, 'clear_polygon_' + method)(area, 0.5, 32, connect=False)
            times.append(perf_counter() - start)
        paths = list(paths.get_objects())
        report[method] = {'median_seconds': median(times), 'paths': len(paths),
                          'length': sum(p.length for p in paths)}
        start = perf_counter()
        with patch.object(camlib.QtWidgets.QApplication, 'processEvents', wraps=camlib.QtWidgets.QApplication.processEvents) as events:
            getattr(geo, 'clear_polygon_' + method)(area, 0.5, 32, connect=False, prog_plot=True)
        report[method].update(progressive_seconds=perf_counter() - start,
                              events=events.call_count, redraws=geo.temp_shapes.redraw.call_count,
                              plot_calls=geo.plot_temp_shapes.call_count)
    print('\nNCC_SHARED_BENCHMARK ' + json.dumps(report))
