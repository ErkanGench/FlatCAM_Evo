"""Final Paint: residual targets may overlap old passes, cutter sweeps may not escape."""
import json
import statistics
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from shapely import LineString, Point, Polygon, box, buffer, linestrings
from shapely.affinity import scale
from shapely.ops import unary_union

import test_paint_geometry as paint_cases
from test_paint_geometry import camlib, storage_of
from test_paint_performance import rest_worker
from test_shrink_offsets import cutter_sweep, board


def setup(diameters=(0.5,), enabled=True, units='MM'):
    case = paint_cases.TestPaintGeometry()
    case.setUp()
    worker, params = rest_worker(case.geometry, diameters)
    worker.app.units = units
    worker.app.options = {'global_tolerance': 0.005}
    params.tool_ordering = 1
    for tool in params.tools_storage.values():
        tool['data']['tools_paint_final_cleanup'] = enabled
    return worker, params


def generate(worker, params, domain, rest):
    output = SimpleNamespace(tools={}, obj_options={})
    handler = worker._generate_rest_paint_worker if rest else worker._generate_paint_worker
    assert handler(output, worker.app, params,
                   [t['tooldia'] for t in params.tools_storage.values()], [domain], None, False) != 'fail'
    return output


@pytest.mark.parametrize('rest', [False, True])
def test_final_paint_recrosses_old_passes_after_simplification(rest):
    worker, params = setup()
    domain = box(0, 0, 10, 6)
    ordinary = [LineString([(x, 0.25), (x, 5.75)]) for x in
                (0.25, 0.7, 1.15, 1.6, 2.05, 2.5, 2.95, 3.4, 3.85, 4.3, 4.75,
                 5.35, 5.8, 6.25, 6.7, 7.15, 7.6, 8.05, 8.5, 8.95, 9.4, 9.75)]
    worker._process_polygon = Mock(return_value=storage_of(ordinary))
    output = generate(worker, params, domain, rest)
    tool = output.tools[1]
    assert tool['paint_cleanup_start'] == len(ordinary)
    assert tool['solid_geometry'][:len(ordinary)] == ordinary
    target = box(5.01, 1, 5.09, 5)
    before = cutter_sweep(ordinary, 0.25)
    after = cutter_sweep(tool['solid_geometry'], 0.25)
    assert target.difference(before).area > 0.3
    assert target.difference(after).area < 0.01
    assert after.difference(domain).area < 1e-10
    assert unary_union(tool['solid_geometry']).equals(unary_union(output.solid_geometry))


@pytest.mark.parametrize('rest', [False, True])
@pytest.mark.parametrize('units', ['MM', 'IN'])
@pytest.mark.parametrize('offset', [-0.2, 0, 0.1])
def test_final_paint_physical_safety_holes_concavity_selection_and_islands(rest, units, offset):
    factor = 1 if units == 'MM' else 1 / 25.4
    worker, params = setup((0.5 * factor,), units=units)
    worker.circle_steps = 4
    params.simplification_value = 0.1 * factor
    domain = unary_union([box(0, 0, 5, 5).difference(Point(2.5, 2.5).buffer(0.7)),
                          box(8, 0, 13, 5).difference(box(10, 2, 14, 6))])
    domain = scale(domain, xfact=factor, yfact=factor, origin=(0, 0))
    params.tools_storage[1]['data']['tools_paint_offset'] = offset * factor
    worker.ui.rest_offset_entry.get_value = lambda: offset * factor
    worker._process_polygon = Mock(return_value=storage_of([]))
    output = generate(worker, params, domain, rest)
    paths = output.tools[1]['solid_geometry']
    assert output.tools[1]['paint_cleanup_start'] == 0
    allowed = domain.intersection(domain.buffer(-offset * factor))
    swept = cutter_sweep(paths, 0.25 * factor)
    assert swept.difference(allowed).area < 1e-10 * factor**2
    assert swept.area > factor**2


@pytest.mark.parametrize('rest', [False, True])
def test_smallest_enabled_selected_tool_without_ordinary_output_runs_last(rest):
    worker, params = setup((0.8, 0.5, 0.2, 0.1))
    params.tools_storage[3]['data']['tools_paint_final_cleanup'] = False
    # Tool 3 is disabled; tool 4 is enabled but not selected. Its stale geometry
    # must not participate in coverage or appear in this generation's output.
    params.tools_storage[4]['solid_geometry'] = [box(0, 0, 10, 10).exterior]
    worker._process_polygon = Mock(return_value=storage_of([]))
    output = SimpleNamespace(tools={}, obj_options={})
    handler = worker._generate_rest_paint_worker if rest else worker._generate_paint_worker
    assert handler(output, worker.app, params, [0.8, 0.5, 0.2], [box(0, 0, 5, 5)], None, False) != 'fail'
    assert list(output.tools) == [2]
    assert output.tools[2]['paint_cleanup_start'] == 0


@pytest.mark.parametrize('rest', [False, True])
def test_cleanup_tool_moves_after_other_tools_ordinary_paths(rest):
    worker, params = setup((0.5, 0.8))
    ordinary = LineString([(1, 1), (4, 1)])
    worker._process_polygon = Mock(side_effect=lambda pol, dia, *args:
                                   storage_of([ordinary] if dia == 0.8 else []))
    output = generate(worker, params, box(0, 0, 5, 5), rest)
    assert list(output.tools) == [2, 1]
    assert list(params.tools_storage) == [2, 1]
    assert output.tools[2]['solid_geometry'] == [ordinary]
    assert output.tools[1]['paint_cleanup_start'] == 0


def test_disabled_cleanup_avoids_coverage_and_clears_stale_flags():
    worker, params = setup(enabled=False)
    params.tools_storage[1]['paint_cleanup_start'] = 0
    with patch('appPlugins.ToolPaint.PaintGen.residual_cleanup',
               side_effect=AssertionError('disabled coverage')):
        output = generate(worker, params, box(0, 0, 5, 5), False)
    assert 'paint_cleanup_start' not in output.tools[1]
    assert not hasattr(output, 'paint_cleanup_residual')


def test_final_paint_uses_rounded_diameter_selection():
    worker, params = setup((0.0197,))
    output = SimpleNamespace(tools={}, obj_options={})
    worker.final_cleanup(output, params, [0.5 / 25.4], [box(0, 0, 0.2, 0.2)])
    assert output.tools[1]['paint_cleanup_start'] == 0


def test_final_paint_coverage_uses_segment_capsules_and_each_tool_radius():
    import numpy as np
    worker, params = setup()
    worker.app.options['global_tolerance'] = 100  # No useful cleanup at this precision.
    path = LineString([(x, 2 + 0.001 * np.sin(x * 150)) for x in np.linspace(1, 9, 2000)])
    other = LineString([(1, 4), (9, 4)])
    output = SimpleNamespace(tools={1: {'tooldia': 0.5, 'solid_geometry': [path]},
                                    2: {'tooldia': 0.8, 'solid_geometry': [other]}})
    domain = box(0, 0, 10, 5)
    worker.final_cleanup(output, params, [0.5], [domain])
    capsules = []
    for p, radius in ((path, 0.25), (other, 0.4)):
        coords = list(p.coords)
        capsules.extend(buffer(linestrings([[a, b] for a, b in zip(coords, coords[1:])]),
                               radius, quad_segs=max(16, camlib.circle_quad_segs(worker.circle_steps))))
    expected = domain.difference(unary_union(capsules))
    assert output.paint_cleanup_residual.symmetric_difference(expected).area < 1e-10


def test_unreachable_domain_and_abort():
    worker, params = setup()
    output = SimpleNamespace(tools={}, obj_options={})
    domain = box(0, 0, 0.2, 4)
    worker.final_cleanup(output, params, [0.5], [domain])
    assert output.tools == {}
    assert output.paint_cleanup_residual.equals(domain)
    worker.app.abort_flag = True
    with pytest.raises(camlib.grace):
        worker.final_cleanup(output, params, [0.5], [box(0, 0, 5, 5)])
    worker.app.abort_flag = False
    with patch.object(camlib.QtWidgets.QApplication, 'processEvents',
                      side_effect=lambda: setattr(worker.app, 'abort_flag', True)):
        with pytest.raises(camlib.grace):
            worker.final_cleanup(output, params, [0.5], [box(0, 0, 5, 5)])


def test_physical_candidate_safety_uses_distance_not_rebuffering_paths():
    worker, _ = setup()
    candidate = LineString([(1, 1), (4, 1)])
    with patch.object(LineString, 'buffer', side_effect=AssertionError('whole-path safety buffer')):
        paths, _ = camlib.residual_cleanup(
            worker.app, box(0, 0, 5, 5), 0.5, 64, [],
            lambda pol, dia: [candidate], physical=True)
    assert paths


def test_physical_cleanup_batches_target_dilation_without_changing_the_domain():
    worker, _ = setup()
    domain = box(0, 0, 5, 5)
    ordinary = [LineString([(x, 0.25), (x, 4.75)]) for x in (0.25, 1, 2, 3, 4, 4.75)]
    with patch.object(camlib.shapely, 'buffer', wraps=camlib.shapely.buffer) as buffered:
        paths, _ = camlib.residual_cleanup(
            worker.app, domain, 0.5, 64,
            [{'tooldia': 0.5, 'solid_geometry': ordinary}], lambda pol, dia: [], physical=True)
    batches = [call for call in buffered.call_args_list
               if isinstance(call.args[0], list) and len(call.args[0]) > 1
               and all(isinstance(part, Polygon) for part in call.args[0])]
    assert len(batches) == 1  # Reach only: boundary passes finish this residual.
    for call in batches:
        parts, distance = call.args
        actual = unary_union(buffer(parts, distance, **call.kwargs))
        reference = unary_union(parts).buffer(distance, **call.kwargs)
        assert actual.symmetric_difference(reference).area < 1e-8
    assert paths
    assert cutter_sweep(paths, 0.25).difference(domain).area < 1e-10


def test_cleanup_rejects_simplified_chord_across_a_hole():
    worker, _ = setup()
    domain = box(0, 0, 5, 5).difference(box(2, 2, 3, 3))
    path = LineString([(1, 2.5), (1, 3.5), (4, 3.5), (4, 2.5)])
    unsafe = LineString([(1, 2.5), (4, 2.5)])
    with patch.object(LineString, 'simplify', return_value=unsafe):
        paths, _ = camlib.residual_cleanup(
            worker.app, domain, 0.5, 4, [], lambda pol, dia: [path], physical=True)
    assert any(p.equals(path) for p in paths)
    assert not any(p.equals(unsafe) for p in paths)
    assert cutter_sweep(paths, 0.25).difference(domain).area < 1e-10


def test_pruning_a_fully_covered_simplification_retries_the_productive_original():
    worker, _ = setup()
    previous = LineString([(1, 2), (9, 2)])
    original = LineString([(1, 2), (2, 2.004), (8, 2.004), (9, 2)])
    assert original.simplify(0.005).equals(previous)
    paths, _ = camlib.residual_cleanup(
        worker.app, box(0, 0, 10, 5), 0.5, 64,
        [{'tooldia': 0.5, 'solid_geometry': [previous]}],
        lambda pol, dia: [original], physical=True, boundary_first=False)
    assert any(path.equals(original) for path in paths)
    gain = cutter_sweep([original], 0.25).difference(cutter_sweep([previous], 0.25)).area
    assert gain > 0.005 * 0.5


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('curved', [False, True])
def test_cleanup_trims_covered_ends_without_splitting_or_losing_side_coverage(reverse, curved):
    import numpy as np
    domain = box(0, 0, 12, 5)
    previous = LineString([(1, 2.5), (7, 2.5)])
    coords = [(x, 2.5 + (0.2 * np.sin(x) if curved else 0)) for x in range(1, 11)]
    candidate = LineString(coords[::-1] if reverse else coords)
    ordinary_sweep = cutter_sweep([previous], 1)
    stock = camlib.flatten_shapely_geometry(domain.difference(ordinary_sweep))
    trimmed, _ = camlib.trim_covered_ends(candidate, 0.5, stock, camlib.shapely.STRtree(stock))
    assert trimmed is not None
    paths = [trimmed]
    assert paths[0].length < candidate.length - 3
    assert len(paths[0].coords) < len(candidate.coords)
    # Only an end was removed. The retained coordinates are original vertices,
    # not replacement chords, and no extra cutting run was introduced.
    assert all(tuple(point) in list(candidate.coords) for point in paths[0].coords)
    expected = ordinary_sweep.union(cutter_sweep([candidate], 0.5))
    actual = ordinary_sweep.union(cutter_sweep(paths, 0.5))
    assert expected.difference(actual).area < 1e-10
    assert cutter_sweep(paths, 0.5).difference(domain).area < 1e-10


def test_cleanup_opens_one_covered_ring_gap_without_adding_lifts():
    domain = box(0, 0, 10, 6)
    previous = [LineString([(x, 1), (x, 4)]) for x in (2, 3, 4)]
    candidate = LineString([(2, 1), (3, 1), (4, 1), (8, 1), (8, 4),
                            (4, 4), (3, 4), (2, 4), (2, 1)])
    stock = camlib.flatten_shapely_geometry(domain.difference(cutter_sweep(previous, 1)))
    trimmed, _ = camlib.trim_covered_ends(candidate, 0.5, stock, camlib.shapely.STRtree(stock))
    assert trimmed is not None
    paths = [trimmed]
    assert not paths[0].is_closed
    assert paths[0].length < candidate.length - 3
    expected = cutter_sweep(previous, 1).union(cutter_sweep([candidate], 0.5))
    actual = cutter_sweep(previous, 1).union(cutter_sweep(paths, 0.5))
    assert expected.difference(actual).area < 1e-10


def test_cleanup_keeps_productive_centerline_inside_an_old_cutter_footprint():
    previous = LineString([(1, 2), (9, 2)])
    candidate = LineString([(x, 2.4) for x in range(1, 10)])
    assert previous.buffer(0.5).covers(candidate)
    stock = camlib.flatten_shapely_geometry(box(0, 0, 10, 5).difference(cutter_sweep([previous], 0.5)))
    trimmed, _ = camlib.trim_covered_ends(candidate, 0.5, stock, camlib.shapely.STRtree(stock))
    assert trimmed is not None
    paths = [trimmed]
    assert paths[0].equals(candidate)
    target = box(2, 2.51, 8, 2.85)
    assert target.difference(cutter_sweep(paths, 0.5)).area < 1e-10


def test_cleanup_trims_overlap_with_an_earlier_cleanup_pass():
    previous = LineString([(1, 2.5), (3, 2.5)])
    first = LineString([(x, 2.5) for x in range(1, 9)])
    second = LineString([(x, 2.5) for x in range(1, 11)])
    stock = camlib.flatten_shapely_geometry(box(0, 0, 12, 5).difference(cutter_sweep([previous], 1)))
    tree = camlib.shapely.STRtree(stock)
    first_trimmed, _ = camlib.trim_covered_ends(first, 0.5, stock, tree)
    assert first_trimmed is not None
    swept = cutter_sweep([first_trimmed], 0.5)
    for i in tree.query(swept):
        stock[i] = stock[i].difference(swept)
    second_trimmed, _ = camlib.trim_covered_ends(second, 0.5, stock, tree)
    assert second_trimmed is not None
    paths = [first_trimmed, second_trimmed]
    assert paths[1].length < 4
    expected = cutter_sweep([previous], 1).union(cutter_sweep([first, second], 0.5))
    actual = cutter_sweep([previous], 1).union(cutter_sweep(paths, 0.5))
    assert expected.difference(actual).area < 1e-10


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('previous_radius', [0.25, 0.5, 1])
def test_exact_collinear_overlap_respects_direction_and_cutter_diameter(reverse, previous_radius):
    previous = LineString([(1, 2.5), (7, 2.5)])
    coords = [(x, 2.5) for x in range(1, 11)]
    candidate = LineString(coords[::-1] if reverse else coords)
    ordinary = cutter_sweep([previous], previous_radius)
    stock = camlib.flatten_shapely_geometry(box(0, 0, 12, 5).difference(ordinary))
    trimmed, _ = camlib.trim_covered_ends(
        candidate, 0.5, stock, camlib.shapely.STRtree(stock),
        covered=(camlib.shapely.STRtree([previous]), [previous_radius]))
    assert trimmed is not None
    if previous_radius < 0.5:
        assert trimmed.equals(candidate)  # The wider new cutter still cuts at both sides.
    else:
        assert trimmed.length < candidate.length - 3
    expected = ordinary.union(cutter_sweep([candidate], 0.5))
    actual = ordinary.union(cutter_sweep([trimmed], 0.5))
    assert expected.difference(actual).area < 1e-10


def test_pruning_keeps_internal_connectors_in_one_cutting_run():
    candidate = LineString([(x, 0) for x in range(5)])
    stock = [box(0.2, 0.1, 0.8, 0.2), box(3.2, 0.1, 3.8, 0.2)]
    trimmed, _ = camlib.trim_covered_ends(candidate, 0.25, stock, camlib.shapely.STRtree(stock))
    assert trimmed is not None
    assert list(trimmed.coords) == list(candidate.coords)


def test_pruning_reuses_only_stock_reaching_segments_without_splitting_the_cut():
    candidate = LineString([(x, 0) for x in range(5)])
    stock = [box(0.2, 0.1, 0.5, 0.2), box(3.5, 0.1, 3.8, 0.2)]
    trimmed, productive = camlib.trim_covered_ends(
        candidate, 0.25, stock, camlib.shapely.STRtree(stock))
    assert list(trimmed.coords) == list(candidate.coords)
    assert len(productive) == 2  # The internal connector remains a cut, not another lift.
    remaining_full = unary_union(stock).difference(cutter_sweep([trimmed], 0.25))
    remaining_productive = unary_union(stock).difference(cutter_sweep(productive, 0.25))
    assert remaining_full.symmetric_difference(remaining_productive).area < 1e-10


@pytest.mark.parametrize('previous_radius', [0.25, 0.5])
def test_cached_stock_updates_match_complete_stored_sweeps_with_holes_and_islands(previous_radius):
    worker, _ = setup()
    domain = unary_union([box(0, 0, 10, 6).difference(Point(4, 3).buffer(0.7)), box(12, 0, 16, 4)])
    previous = [LineString([(1, 1), (9, 1)]), LineString([(13, 2), (15, 2)])]
    paths, residual = camlib.residual_cleanup(
        worker.app, domain, 0.5, 64, [{'tooldia': 2 * previous_radius, 'solid_geometry': previous}],
        lambda pol, dia: [], physical=True)
    assert paths
    capsules = []
    for path, radius in [(p, previous_radius) for p in previous] + [(p, 0.25) for p in paths]:
        coords = list(path.coords)
        capsules.extend(buffer(linestrings([[a, b] for a, b in zip(coords, coords[1:])]),
                               radius, quad_segs=16))
    expected = domain.difference(unary_union(capsules))
    assert residual.symmetric_difference(expected).area < 1e-8
    assert cutter_sweep(paths, 0.25).difference(domain).area < 1e-10


def rapid_length(paths):
    return sum(Point(a.coords[-1]).distance(Point(b.coords[0])) for a, b in zip(paths, paths[1:]))


def test_cleanup_ordering_reduces_rapids_without_reversing_or_changing_endpoints():
    paths = [LineString([(0, 0), (0, 1)]), LineString([(10, 1), (10, 2)]),
             LineString([(1, 1), (1, 2)]), LineString([(2, 1), (2, 2)]),
             LineString([(11, 1), (11, 2)])]
    ordered = camlib.order_cleanup_paths(paths)
    assert ordered[0] is paths[0] and ordered[-1] is paths[-1]
    assert {id(path) for path in ordered} == {id(path) for path in paths}
    assert rapid_length(ordered) < rapid_length(paths)
    assert sum(p.length for p in ordered) == sum(p.length for p in paths)


def test_cleanup_ordering_rejects_a_longer_greedy_route():
    paths = [LineString([(0, 1), (0, 0)]), LineString([(2, 0), (0, 0)]),
             LineString([(1, 0), (100, 0)]), LineString([(101, 0), (101, 1)])]
    # Greedy would visit the nearer start at x=1 first, leaving a long return
    # from x=100 to x=2 and then to x=101. Preserve the existing short route.
    assert camlib.order_cleanup_paths(paths) is paths


def test_cleanup_ordering_processes_cancellation():
    worker, _ = setup()
    paths = [LineString([(x, 0), (x, 1)]) for x in range(6)]
    with patch.object(camlib.QtWidgets.QApplication, 'processEvents',
                      side_effect=lambda: setattr(worker.app, 'abort_flag', True)):
        with pytest.raises(camlib.grace):
            camlib.order_cleanup_paths(paths, app=worker.app)


def test_cleanup_batches_stock_differences_for_gain_and_update():
    worker, _ = setup()
    candidate = LineString([(1, 1), (4, 1)])
    with patch.object(camlib.shapely, 'difference', wraps=camlib.shapely.difference) as difference:
        paths, _ = camlib.residual_cleanup(
            worker.app, box(0, 0, 5, 5), 0.5, 64, [],
            lambda pol, dia: [candidate], physical=True)
    batches = [call for call in difference.call_args_list if isinstance(call.args[0], list)]
    assert batches
    assert paths
    assert cutter_sweep(paths, 0.25).difference(box(0, 0, 5, 5)).area < 1e-10


def test_residual_boundaries_clear_a_sliver_without_constructing_a_workspace():
    worker, _ = setup()
    domain = box(0, 0, 10, 6)
    ordinary = [LineString([(x, 0.25), (x, 5.75)]) for x in
                (0.25, 0.7, 1.15, 1.6, 2.05, 2.5, 2.95, 3.4, 3.85, 4.3, 4.75,
                 5.35, 5.8, 6.25, 6.7, 7.15, 7.6, 8.05, 8.5, 8.95, 9.4, 9.75)]
    ordinary.extend(LineString([(0.25, y), (9.75, y)]) for y in (0.25, 5.75))
    generate_paths = Mock(side_effect=AssertionError('unneeded workspace painting'))
    paths, _ = camlib.residual_cleanup(
        worker.app, domain, 0.5, 64, [{'tooldia': 0.5, 'solid_geometry': ordinary}],
        generate_paths, physical=True)
    assert paths
    generate_paths.assert_not_called()
    swept = cutter_sweep(paths, 0.25)
    assert box(5.01, 1, 5.09, 5).difference(swept).area < 0.01
    assert swept.difference(domain).area < 1e-10


@pytest.mark.slow
def test_connected_cleanup_preserves_grouped_workspace_coverage():
    worker, params = setup((0.4,))
    params.paint_method = 0
    params.simplification_value = 0.01
    params.tools_storage[1]['data']['tools_paint_connect'] = True
    output = generate(worker, params, board(), False)
    paths = output.tools[1]['solid_geometry']
    # Connected workspace passes group useful gains differently from separate
    # boundary passes. Preserve the original independent physical coverage.
    assert board().difference(cutter_sweep(paths, 0.2)).area <= 0.18374186693529831 + 1e-6


@pytest.mark.parametrize('method', [0, 1, 2, 3, 4])
def test_cleanup_methods_and_connected_paths_preserve_the_whole_cutter(method):
    worker, params = setup()
    params.paint_method = method
    params.tools_storage[1]['data']['tools_paint_connect'] = True
    worker._process_polygon = Mock(return_value=storage_of([]))
    domain = box(0, 0, 5, 5).difference(Point(2.5, 2.5).buffer(0.7))
    output = generate(worker, params, domain, False)
    paths = output.tools[1]['solid_geometry']
    assert paths
    assert cutter_sweep(paths, 0.25).difference(domain).area < 1e-10


def test_cleanup_mm_in_residual_equivalence():
    normalized = []
    for units, factor in (('MM', 1), ('IN', 1 / 25.4)):
        worker, params = setup((0.5 * factor,), units=units)
        domain = scale(box(0, 0, 5, 4), xfact=factor, yfact=factor, origin=(0, 0))
        output = SimpleNamespace(tools={})
        worker.final_cleanup(output, params, [0.5 * factor], [domain])
        normalized.append(scale(output.paint_cleanup_residual,
                                xfact=1 / factor, yfact=1 / factor, origin=(0, 0)))
    assert normalized[0].symmetric_difference(normalized[1]).area < 1e-8


def test_tiny_reachable_sliver_does_not_add_useless_travel():
    worker, params = setup()
    domain = box(0, 0, 5, 5)
    ordinary = [LineString([(x, 0.25), (x, 4.75)])
                for x in (0.25, 0.75, 1.25, 1.75, 2.25, 2.75001, 3.25, 3.75, 4.25, 4.75)]
    ordinary.extend(LineString([(0.25, y), (4.75, y)]) for y in (0.25, 4.75))
    output = SimpleNamespace(tools={1: dict(params.tools_storage[1], solid_geometry=ordinary)})
    worker.final_cleanup(output, params, [0.5], [domain])
    assert 'paint_cleanup_start' not in output.tools[1]
    assert not output.paint_cleanup_residual.is_empty


def factory(worker):
    outputs = []

    def create(kind, name, initialize, **kwargs):
        output = SimpleNamespace(tools={}, obj_options={})
        result = initialize(output, worker.app)
        outputs.append(output)
        return 'fail' if result == 'fail' else output

    worker.parent_tool.new_object = create
    return outputs


@pytest.mark.parametrize('rest', [False, True])
def test_programmatic_paint_handler_keeps_cleanup_without_ordinary_paths(rest):
    worker, params = setup()
    worker._process_polygon = Mock(return_value=storage_of([]))
    outputs = factory(worker)
    source = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 5, 5)])
    assert worker.paint_handler(source, source.solid_geometry, tooldia='0.5', order=0,
                                method=2, rest=rest, outname='final', tools_storage=params.tools_storage,
                                run_threaded=False) != 'fail'
    assert outputs[0].tools[1]['paint_cleanup_start'] == 0


def test_area_selection_cleanup_does_not_expand_to_source_board():
    worker, params = setup()
    worker.ui.rest_cb = SimpleNamespace(get_value=lambda: False)
    worker._process_polygon = Mock(return_value=storage_of([]))
    outputs = factory(worker)
    source = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 10, 10)])
    selection = box(2, 2, 5, 5)
    worker.paint_poly_area_worker(source, selection, tooldia='0.5', order=0, method=2,
                                  outname='selected', tools_storage=params.tools_storage,
                                  run_threaded=False)
    paths = outputs[0].tools[1]['solid_geometry']
    assert paths
    assert cutter_sweep(paths, 0.25).difference(selection).area < 1e-10


def test_tcl_paint_passes_preference_into_real_generation():
    from tclCommands.TclCommandPaint import TclCommandPaint
    from test_tcl_audit_generation import factory_app
    worker, _ = setup()
    source = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 5, 5)], decimals=4)
    app = factory_app(source)
    app.units = 'MM'
    app.abort_flag = False
    app.decimals = 4
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.options['tools_paint_final_cleanup'] = True
    app.paint_tool = SimpleNamespace(gen=worker)
    worker.app = app
    worker.parent_tool.app = app
    worker.ui.rest_cb = SimpleNamespace(get_value=lambda: False)
    worker._process_polygon = Mock(return_value=storage_of([]))
    outputs = factory(worker)
    assert TclCommandPaint(app).execute({'name': 'board', 'tooldia': '0.5', 'method': 'lines'}, []) != 'fail'
    assert outputs[0].tools[1]['paint_cleanup_start'] == 0


def test_final_paint_cnc_preserves_sequence_and_no_resimplification():
    from defaults import AppDefaults
    from test_unify_regressions_0b import make_app
    job = camlib.CNCjob(make_app())
    job.obj_options = {'name': 'paint'}
    job.doformat = Mock(return_value='')
    job.create_gcode_single_pass = Mock(return_value='cut\n')
    data = dict(AppDefaults.factory_defaults)
    data.update(tools_mill_tooldia=0.5, tools_mill_offset_value=0,
                tools_mill_optimization_type='R', tools_mill_multidepth=False)
    paths = [LineString([(10, 0), (12, 0)]), LineString([(0, 0), (1, 0)]),
             LineString([(0, 0), (0, 1)])]
    tools = {1: {'data': data, 'solid_geometry': paths, 'paint_cleanup_start': 1}}
    assert job.geometry_tool_gcode_gen(1, tools, (0, 0), (0, 0), 0.1) != 'fail'
    calls = job.create_gcode_single_pass.call_args_list
    assert [call.args[0] for call in calls] == paths
    assert all(call.args[4] == 0 for call in calls)


@pytest.mark.slow
def test_final_paint_synthetic_board_benchmark():
    measurements = []
    for enabled in (False, True):
        samples = []
        for _ in range(3):
            worker, params = setup((0.4,), enabled=enabled)
            params.paint_method = 0
            params.simplification_value = 0.01
            start = time.perf_counter()
            output = generate(worker, params, board(), False)
            samples.append(time.perf_counter() - start)
        paths = output.tools[1]['solid_geometry']
        sweep = cutter_sweep(paths, 0.2)
        cleanup = paths[output.tools[1].get('paint_cleanup_start', len(paths)):]
        cleanup_sweep = cutter_sweep(cleanup, 0.2) if cleanup else Polygon()
        measurements.append({'enabled': enabled, 'median_seconds': statistics.median(samples),
                             'paths': len(paths), 'segments': sum(len(p.coords) - 1 for p in paths),
                             'cut_length_mm': sum(p.length for p in paths),
                             'between_path_lifts': max(0, len(paths) - 1),
                             'rapid_xy_from_origin_mm': Point(0, 0).distance(Point(paths[0].coords[0])) +
                             rapid_length(paths),
                             'unpainted_area_mm2': board().difference(sweep).area,
                             'outside_area_mm2': sweep.difference(board()).area,
                             'cleanup_outside_area_mm2': cleanup_sweep.difference(board()).area})
    assert measurements[1]['unpainted_area_mm2'] < measurements[0]['unpainted_area_mm2']
    # Independent physical-sweep result before the dilation optimization.
    # Permit numerical overlay noise, not a loss of previously achieved coverage.
    assert measurements[1]['unpainted_area_mm2'] <= 0.2679678659881805 + 1e-6
    # Preserve the tighter pre-pruning physical coverage too. Cutting metrics
    # describe the final stored paths, not intermediate unsimplified candidates.
    assert measurements[1]['unpainted_area_mm2'] <= 0.26794681628096123 + 1e-6
    assert measurements[1]['paths'] <= 376
    assert measurements[1]['segments'] < 10635
    assert measurements[1]['cut_length_mm'] < 2038.3127146843954
    assert measurements[1]['rapid_xy_from_origin_mm'] < 1722.665335701939
    assert measurements[1]['outside_area_mm2'] <= measurements[0]['outside_area_mm2'] + 1e-8
    assert measurements[1]['cleanup_outside_area_mm2'] < 1e-10
    print('FINAL_PAINT_SYNTHETIC_BENCHMARK ' + json.dumps(measurements))
