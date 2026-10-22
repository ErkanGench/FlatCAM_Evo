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


@pytest.mark.parametrize('rectangular', [False, True])
def test_signed_automatic_cutters_preserve_geometry(cutout_app, rectangular):
    source = load_source(cutout_app.test_app, 'outline_single')
    paths = []
    for diameter in (2.4, -2.4):
        _configure(cutout_app, source, rectangular, dia=diameter)
        _generate(cutout_app, rectangular)
        paths.append(unary_union(flat(_geometry(cutout_app).solid_geometry)))
    assert paths[0].equals(paths[1])


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

