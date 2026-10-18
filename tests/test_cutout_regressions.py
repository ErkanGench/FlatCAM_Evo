"""Cutout regressions not covered by the existing outline/golden suite."""

from copy import deepcopy
import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely.affinity import rotate
from shapely.geometry import GeometryCollection, LineString, LinearRing, Point, Polygon, box
from shapely.ops import linemerge, unary_union

from test_cutout_inner_contours import (  # noqa: F401
    BASE, _headless_qt, configure, flat, load_source, make_geometry, make_tool,
)
from appPlugins.ToolCutOut import (
    CutOut, _cutout_intervals, _manual_gap_geometry, _manual_subtract_selected, freeform_cutout_paths,
)


@pytest.fixture
def cutout_app():
    return make_tool()


def _configure(tool, source, rectangular=False, **overrides):
    name = source.obj_options['name']
    tool.test_app.collection.objs[name] = source
    configure(tool, name, dict(BASE, **overrides))
    tool.ui.cutout_shape_cb.set_value(rectangular)
    tool.ui.cutz_entry.set_value(-1.6)
    tool.test_app.created.clear()


def _generate(tool, rectangular=False):
    if rectangular:
        tool.on_rectangular_cutout()
    else:
        tool.on_freeform_cutout()


def _geometry(tool):
    return next(obj for obj in tool.test_app.created.values() if obj.kind == 'geometry')


def _drills(tool):
    return [point for obj in tool.test_app.created.values() if obj.kind == 'excellon'
            for data in obj.tools.values() for point in data['drills']]


def _manual_target(tool, geometry, name='manual'):
    app = tool.test_app
    source = make_geometry(app, name, geometry)
    source.tools = {1: deepcopy(tool.cut_tool_dict)}
    source.plot = Mock()
    source.build_ui = Mock()
    tool.man_cutout_obj = source
    tool.manual_solid_geo = deepcopy(geometry)
    app.collection.objs[name] = source
    tool.ui.man_object_combo = SimpleNamespace(currentText=lambda: name)
    tool.ui.dia.set_value(2.4)
    tool.ui.gapsize.set_value(4.0)
    tool.ui.gaptype_combo.set_value(0)
    tool.ui.cutz_entry.set_value(-1.6)
    app.geo_editor = SimpleNamespace(snap=lambda x, y: (x, y), tool_shape=Mock())
    app.on_mouse_click_over_plot = Mock()
    app.on_mouse_click_release_over_plot = Mock()
    app.on_mouse_move_over_plot = Mock()
    return source


def test_drill_cut_handles_multipart_open_and_closed_paths(cutout_app):
    app = cutout_app.test_app
    for geometry, pitch, expected_x in [
        ([LineString([(0, 0), (10, 0)]), LineString([(20, 0), (30, 0)])], 3.0,
         [0, 3, 6, 9, 10, 20, 23, 26, 29, 30]),
        ([box(0, 0, 4, 4), box(10, 0, 14, 4)], 4.0, [0, 0, 4, 4, 10, 10, 14, 14]),
    ]:
        source = make_geometry(app, 'drill', geometry)
        app.collection.objs['drill'] = source
        cutout_app.ui.drillcut_object_combo = SimpleNamespace(currentText=lambda: 'drill')
        cutout_app.ui.drill_pitch_entry.set_value(pitch)
        cutout_app.ui.drill_dia_entry.set_value(0.5)
        cutout_app.ui.drill_margin_entry.set_value(0.0)
        app.created.clear()
        cutout_app.on_drill_cut_click()
        points = _drills(cutout_app)
        assert sorted(point.x for point in points) == expected_x
        assert len(points) == len({tuple(point.coords)[0] for point in points})


@pytest.mark.parametrize('pitch,diameter', [(0.0, 0.5), (3.0, math.inf)])
def test_invalid_drilling_parameters_create_nothing(cutout_app, pitch, diameter):
    cutout_app.ui.drill_pitch_entry.get_value = Mock(return_value=pitch)
    cutout_app.ui.drill_dia_entry.get_value = Mock(return_value=diameter)
    cutout_app.on_drill_cut_click()
    assert not cutout_app.test_app.created


def test_erased_drill_offset_is_reported(cutout_app):
    app = cutout_app.test_app
    app.collection.objs['drill'] = make_geometry(app, 'drill', [box(0, 0, 1, 1)])
    cutout_app.ui.drillcut_object_combo = SimpleNamespace(currentText=lambda: 'drill')
    cutout_app.ui.drill_margin_entry.get_value = lambda: -10.0
    cutout_app.ui.drill_pitch_entry.set_value(3.0)
    cutout_app.ui.drill_dia_entry.set_value(0.5)
    cutout_app.on_drill_cut_click()
    assert not app.created
    assert any('Could not add drills' in call.args[0] for call in app.inform.emit.call_args_list)


@pytest.mark.parametrize('rectangular,diameter,bite_diameter', [
    (False, 0.0, 0.6), (True, 0.0, 0.6),
    (False, 2.4, 0.0), (True, 2.4, math.nan),
])
def test_invalid_automatic_parameters_do_not_schedule(cutout_app, rectangular, diameter, bite_diameter):
    source = make_geometry(cutout_app.test_app, 'board', box(0, 0, 50, 30))
    _configure(cutout_app, source, rectangular, dia=diameter, gap_type=2)
    cutout_app.ui.mb_dia_entry.get_value = Mock(return_value=bite_diameter)
    cutout_app.test_app.worker_task.emit = Mock()
    _generate(cutout_app, rectangular)
    cutout_app.test_app.worker_task.emit.assert_not_called()
    assert not cutout_app.test_app.created


@pytest.mark.parametrize('inner,diameter,spacing', [
    (False, 0.0, 0.3), (True, math.nan, 0.3),
    (False, 0.6, -0.6), (True, 0.6, math.inf),
])
def test_invalid_mouse_bite_step_fails_before_geometry(inner, diameter, spacing):
    handler = Mock(side_effect=AssertionError('invalid input reached geometry'))
    result = freeform_cutout_paths(
        None, 'single', 2.4, 0.0, '4', 4.0, False, 2, -1.0, diameter, spacing,
        handler, inner_active=inner)
    assert result.failed and result.errors
    handler.assert_not_called()


@pytest.mark.parametrize('rectangular', [False, True])
def test_signed_automatic_cutters_preserve_geometry(cutout_app, rectangular):
    source = load_source(cutout_app.test_app, 'outline_single')
    paths = []
    for diameter in (2.4, -2.4):
        _configure(cutout_app, source, rectangular, dia=diameter)
        _generate(cutout_app, rectangular)
        paths.append(unary_union(flat(_geometry(cutout_app).solid_geometry)))
    assert paths[0].equals(paths[1])


@pytest.mark.parametrize('source_name', ['geo_panel2', 'outline_panel2'])
def test_rectangular_mouse_bites_leave_milling_unchanged(cutout_app, source_name):
    source = load_source(cutout_app.test_app, source_name)
    _configure(cutout_app, source, True, kind='panel')
    _generate(cutout_app, True)
    before = unary_union(flat(_geometry(cutout_app).solid_geometry))
    _configure(cutout_app, source, True, kind='panel', gap_type=2)
    _generate(cutout_app, True)
    assert before.equals(unary_union(flat(_geometry(cutout_app).solid_geometry)))
    assert _drills(cutout_app)


@pytest.mark.parametrize('rectangular', [False, True])
def test_manual_panels_keep_all_paths_and_independent_tools(cutout_app, rectangular):
    template = deepcopy(cutout_app.cut_tool_dict)
    outputs = []
    for name in ('first.gbr', 'second.gbr'):
        source = SimpleNamespace(kind='gerber', obj_options={'name': name},
                                 solid_geometry=[box(0, 0, 40, 25), box(50, 0, 90, 25)])
        _configure(cutout_app, source, rectangular, kind='panel')
        cutout_app.on_manual_geo()
        output = _geometry(cutout_app)
        paths = flat(output.solid_geometry)
        assert len(paths) == 2
        assert all(any(board.contains(path) for board in
                       [box(-2, -2, 42, 27), box(48, -2, 92, 27)]) for path in paths)
        outputs.append(output)
    assert outputs[0].tools[1]['data']['name'] == 'first.gbr_cutout'
    assert outputs[0].tools[1] is not outputs[1].tools[1]
    assert cutout_app.cut_tool_dict == template


@pytest.mark.parametrize('rectangular', [False, True])
def test_queued_generation_keeps_click_time_settings(cutout_app, rectangular):
    app = cutout_app.test_app
    source = make_geometry(app, 'queued', box(0, 0, 50, 30))
    _configure(cutout_app, source, rectangular)
    cutout_app.ui.cutz_entry.set_value(-1.25)
    cutout_app.ui.mpass_cb.set_value(True)
    cutout_app.ui.maxdepth_entry.set_value(0.4)
    cutout_app.cut_tool_dict['data']['marker'] = 'original'
    queued = []
    app.worker_task.emit = queued.append
    _generate(cutout_app, rectangular)
    assert len(queued) == 1 and not app.created
    cutout_app.ui.gapsize.set_value(30.0)
    cutout_app.ui.gaptype_combo.set_value(2)
    cutout_app.ui.cutz_entry.set_value(-9.0)
    cutout_app.ui.mpass_cb.set_value(False)
    cutout_app.ui.maxdepth_entry.set_value(9.0)
    cutout_app.cut_tool_dict['data']['marker'] = 'changed'
    queued[0]['fcn'](*queued[0]['params'])
    output = _geometry(cutout_app)
    expected_length = source.solid_geometry.buffer(0.1).exterior.length - 4 * 6.4
    assert unary_union(flat(output.solid_geometry)).length == pytest.approx(expected_length)
    assert not _drills(cutout_app)
    data = output.tools[1]['data']
    assert (data['marker'], data['tools_mill_cutz'], data['tools_mill_multidepth'],
            data['tools_mill_depthperpass']) == ('original', -1.25, True, 0.4)


def test_manual_sessions_cancel_restore_and_isolate_queued_drills(cutout_app):
    app = cutout_app.test_app
    original = _manual_target(cutout_app, [box(0, 0, 10, 10)])
    app.geo_editor.tool_shape.enabled = False
    cutout_app.ui.dia.set_value(0.0)
    cutout_app.on_manual_gap_click()
    assert app.geo_editor.tool_shape.enabled is False
    cutout_app.ui.dia.set_value(2.4)
    cutout_app.ui.gaptype_combo.set_value(2)
    cutout_app.ui.mb_dia_entry.set_value(0.6)
    cutout_app.ui.mb_spacing_entry.set_value(0.3)
    app.options['global_selection_shape'] = True
    cutout_app.on_manual_gap_click()
    assert app.options['global_selection_shape'] is False
    cutout_app.mb_manual_cuts = [LineString([(0, 0), (10, 0)])]
    cutout_app.on_key_press(SimpleNamespace(key='Escape'))
    assert not cutout_app.mb_manual_cuts
    assert app.options['global_selection_shape'] is True
    cutout_app.on_manual_gap_click()
    cutout_app.mb_manual_cuts = [LineString([(0, 0), (10, 0)])]
    queued = []
    app.worker_task.emit = queued.append
    cutout_app.on_mouse_click_release(SimpleNamespace(pos=(0, 0), button=2))
    assert len(queued) == 1 and not cutout_app.mb_manual_cuts
    _manual_target(cutout_app, [box(100, 0, 110, 10)], name='later')
    cutout_app.ui.gaptype_combo.set_value(2)
    cutout_app.on_manual_gap_click()
    cutout_app.mb_manual_cuts = [LineString([(100, 0), (110, 0)])]
    cutout_app.new_object = Mock(wraps=cutout_app.new_object)
    queued[0]['fcn'](*queued[0]['params'])
    assert _drills(cutout_app) and all(point.x <= 10 for point in _drills(cutout_app))
    assert cutout_app.new_object.call_args.kwargs['source'] is original
    cutout_app.ui.mb_dia_entry.set_value(0.0)
    cutout_app.on_mouse_click_release(SimpleNamespace(pos=(0, 0), button=2))
    assert len(queued) == 1 and not cutout_app.mb_manual_cuts


def test_reset_keeps_one_global_selection_callback(cutout_app):
    app = cutout_app.test_app
    app.collection.get_selected = lambda: []
    cutout_app.on_tool_add = Mock()
    cutout_app.set_tool_ui()
    cutout_app.set_tool_ui()
    assert app.proj_selection_changed.connect.call_count == 1


def test_flatten_preserves_holes_in_nested_collections():
    polygon = Polygon(box(0, 0, 10, 10).exterior, [box(2, 2, 8, 8).exterior])
    line = LineString([(20, 0), (30, 0)])
    paths = CutOut.flatten([GeometryCollection([polygon, line])])
    assert len(paths) == 3
    assert unary_union(paths).equals(unary_union([polygon.exterior, polygon.interiors[0], line]))


RECTANGLE = box(0, 0, 50, 30).exterior
U_SHAPE = Polygon([(0, 0), (50, 0), (50, 30), (35, 30), (35, 10),
                   (15, 10), (15, 30), (0, 30)]).exterior


@pytest.mark.parametrize('mode,path,count', [
    ('LR', LinearRing([(0, 15), (0, 0), (50, 0), (50, 30), (0, 30), (0, 15)]), 2),
    ('TB', rotate(RECTANGLE, 27), 2),
    ('2LR', RECTANGLE, 4),
    ('2TB', LinearRing(list(RECTANGLE.coords)[::-1]), 4),
    ('4', U_SHAPE, 4),
    ('8', rotate(RECTANGLE, 27), 8),
])
def test_automatic_tab_modes_partition_the_contour(mode, path, count):
    cut, gaps = _cutout_intervals(path, 2.4, mode, 6.4)
    gap_union = unary_union(gaps)
    # Joining the seam pieces counts machining tabs rather than Shapely fragments.
    assert len(flat(linemerge(gap_union))) == count
    assert sum(gap.length for gap in gaps) == pytest.approx(count * 6.4)
    assert sum(part.length for part in cut + gaps) == pytest.approx(path.length)
    assert unary_union(cut).intersection(gap_union).length < 1e-7
    assert unary_union(cut + gaps).hausdorff_distance(path) < 1e-7


@pytest.mark.parametrize('mode,length', [('8', 100.0), ('2LR', 10.0)])
def test_impossible_or_touching_tabs_are_rejected(mode, length):
    with pytest.raises(ValueError):
        _cutout_intervals(box(0, 0, 20, 20).exterior, 2.4, mode, length)


@pytest.mark.parametrize('path,click,width', [
    (rotate(LineString([(0, 0), (50, 0)]), 27), (25, 0), 4.0),
    (LineString(list(Point(0, 0).buffer(20, quad_segs=64).exterior.coords)[::-1]), (20, 0), 4.0),
    (LineString([(0, 0), (10, 0), (10, 0.5), (0, 0.5)]), (8, 0), 4.0),
    (Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]).exterior, (10, 2), 21.6),
    (box(0, 0, 10, 10).exterior, (10, 0), 21.6),
])
def test_manual_intervals_preserve_arclength_on_bends_and_seams(path, click, width):
    selected, gap, _ = _manual_gap_geometry(path, click, 2.4, width)
    remaining = _manual_subtract_selected(path, selected, gap, expected_gap_length=width + 2.4)
    assert gap.length == pytest.approx(width + 2.4)
    assert path.length - remaining.length == pytest.approx(width + 2.4)
    assert remaining.difference(path.buffer(1e-7)).length < 1e-7


def test_manual_preview_click_and_swept_web_agree(cutout_app):
    path = rotate(LineString([(0, 0), (50, 0)]), 27)
    neighbor = rotate(LineString([(0, 10), (50, 10)]), 27, origin=(25, 0))
    source = _manual_target(cutout_app, [path, neighbor])
    app = cutout_app.test_app
    app.grid_status = lambda: False
    cutout_app.canvas.translate_coords = lambda point: point
    cutout_app.draw_utility_geometry = Mock()
    cutout_app.ui.dia.set_value(-2.4)
    cutout_app.ui.gapsize.set_value(1000.0)
    assert cutout_app.cutting_geo((25, 0)).is_empty
    cutout_app.ui.gapsize.set_value(4.0)
    cutout_app.on_mouse_move(SimpleNamespace(pos=(25, 0), is_dragging=False))
    preview = cutout_app.draw_utility_geometry.call_args.kwargs['geo']
    assert preview.area == pytest.approx(6.4 * 2.4)
    cutout_app.on_manual_cutout((25, 0))
    remaining = unary_union(flat(source.solid_geometry))
    assert path.length + neighbor.length - remaining.length == pytest.approx(6.4)
    assert neighbor.difference(remaining.buffer(1e-7)).length < 1e-7
    residual = path.difference(remaining.buffer(1.2))
    assert residual.length == pytest.approx(4.0)


@pytest.mark.parametrize('mode,cutz,depth', [
    ('freeform', -1.6, -1.6), ('rectangular', -1.6, math.inf),
    ('manual_start', 0.0, -1.0), ('manual_click', -1.6, 1.0),
])
def test_invalid_thin_depth_does_not_schedule_or_mutate(cutout_app, mode, cutz, depth):
    source = _manual_target(cutout_app, [LineString([(0, 0), (20, 0)])])
    _configure(cutout_app, source, mode == 'rectangular', gap_type=1)
    cutout_app.ui.cutz_entry.get_value = lambda: cutz
    cutout_app.ui.thin_depth_entry.get_value = lambda: depth
    before = deepcopy(source.solid_geometry)
    cutout_app.test_app.worker_task.emit = Mock()
    cutout_app.test_app.geo_editor.tool_shape.enabled = False
    if mode == 'manual_start':
        cutout_app.on_manual_gap_click()
        cutout_app.canvas.graph_event_disconnect.assert_not_called()
    elif mode == 'manual_click':
        cutout_app.on_manual_cutout((10, 0))
    else:
        _generate(cutout_app, mode == 'rectangular')
    assert source.solid_geometry == before
    assert 99 not in source.tools
    assert not cutout_app.test_app.created
    assert cutout_app.test_app.geo_editor.tool_shape.enabled is False
    cutout_app.test_app.worker_task.emit.assert_not_called()


def test_valid_thin_gap_owns_its_tool_and_zero_depth_keeps_a_bridge(cutout_app):
    source = _manual_target(cutout_app, [LineString([(0, 0), (20, 0)])])
    template = deepcopy(cutout_app.cut_tool_dict)
    cutout_app.ui.gaptype_combo.set_value(1)
    cutout_app.ui.thin_depth_entry.set_value(-0.8)
    cutout_app.on_manual_cutout((10, 0))
    assert source.tools[99]['data']['tools_mill_cutz'] == -0.8
    assert source.tools[99] is not source.tools[1]
    assert cutout_app.cut_tool_dict == template
    source = make_geometry(cutout_app.test_app, 'zero_thin', box(0, 0, 50, 30))
    _configure(cutout_app, source, gap_type=1, thin=0.0)
    _generate(cutout_app)
    assert 99 not in _geometry(cutout_app).tools


@pytest.mark.parametrize('rectangular,kind,closed_path,margin', [
    (False, 'single', True, 2.0), (False, 'panel', False, -0.3),
    (True, 'single', True, -0.3),
    (True, 'panel', False, 2.0),
])
def test_mouse_bites_follow_margin_rows_and_keep_spacing(cutout_app, rectangular, kind, closed_path, margin):
    boards = [box(0, 0, 50, 30)] if kind == 'single' else [box(0, 0, 40, 25), box(50, 0, 90, 25)]
    source = make_geometry(cutout_app.test_app, 'margin',
                           [board.exterior if closed_path else board for board in boards])
    _configure(cutout_app, source, rectangular, kind=kind, margin=margin, gap_type=2)
    _generate(cutout_app, rectangular)
    holes = _drills(cutout_app)
    rows = [board.buffer(margin).exterior for board in boards]
    assert holes
    assert max(min(row.distance(point) for row in rows) for point in holes) < 2e-6
    assert len(holes) == 24 * len(boards)
    for row in rows:
        xmin, ymin, xmax, ymax = row.bounds
        centers = [Point(xmin, (ymin + ymax) / 2), Point(xmax, (ymin + ymax) / 2),
                   Point((xmin + xmax) / 2, ymin), Point((xmin + xmax) / 2, ymax)]
        groups = [[] for _ in centers]
        for point in holes:
            if row.distance(point) < 2e-6:
                index = min(range(4), key=lambda index: centers[index].distance(point))
                groups[index].append(point)
        for index, group in enumerate(groups):
            values = sorted(point.y if index < 2 else point.x for point in group)
            assert len(values) == 6
            assert all(b - a == pytest.approx(0.9) for a, b in zip(values, values[1:]))


@pytest.mark.parametrize('inner', [False, True])
def test_mouse_bite_layout_errors_are_returned(inner):
    source = SimpleNamespace(kind='geometry', multigeo=False, solid_geometry=box(0, 0, 50, 30))
    handler = Mock(side_effect=[([RECTANGLE], []), ValueError('mouse-bite layout does not fit')])
    result = freeform_cutout_paths(
        source, 'single', 2.4, 0.1, '4', 4.0, False, 2, -1.0, 0.6, 0.3,
        handler, inner_active=inner)
    assert result.failed
    assert any('mouse-bite layout does not fit' in error for error in result.errors)


@pytest.mark.parametrize('rectangular', [False, True])
def test_impossible_generation_reports_failure_without_output(cutout_app, rectangular):
    source = make_geometry(cutout_app.test_app, 'tiny', box(0, 0, 4, 4))
    _configure(cutout_app, source, rectangular, gaps='8', gapsize=10.0)
    _generate(cutout_app, rectangular)
    assert not cutout_app.test_app.created
    assert any('[ERROR_NOTCL]' in call.args[0]
               for call in cutout_app.test_app.inform.emit.call_args_list)


@pytest.mark.parametrize('source_name', ['geo_single', 'outline_single'])
def test_large_rectangular_margin_keeps_four_tabs(cutout_app, source_name):
    source = load_source(cutout_app.test_app, source_name)
    _configure(cutout_app, source, True, margin=20.0)
    _generate(cutout_app, True)
    paths = flat(_geometry(cutout_app).solid_geometry)
    assert all(not path.is_closed for path in paths)
    assert len(paths) >= 4
