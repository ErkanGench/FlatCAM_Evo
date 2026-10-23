"""Geometry generation of the plugins, headless (offscreen Qt, MagicMock app)."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6 import QtWidgets  # noqa: E402
from PyQt6.QtCore import QStringListModel  # noqa: E402
from shapely import GeometryCollection, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from appParsers.ParseGerber import Gerber  # noqa: E402
from appObjects.GerberObject import GerberObject
from appPlugins.ToolCopperThieving.CopperThievingGen import copper_fill, plating_mask, robber_bar_data
from appPlugins.ToolCopperThieving import ToolCopperThieving
from tests.helpers_objects import make_app, export_gerber_text

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make_tool_app():
    app = MagicMock()
    app.decimals = 4
    app.app_units = "MM"
    app.collection = QStringListModel()
    app.resource_location = "assets/resources"
    app.options = {}
    app.defaults = {}
    return app


@pytest.mark.parametrize("source_kind", ["polygon", "collection"])
def test_plating_mask_accepts_shapely_source(source_kind):
    pad = box(0, 0, 2, 2)
    source = pad if source_kind == "polygon" else GeometryCollection([pad])
    solid, tools, follows, area = plating_mask(source, {}, [], [], None, None, 0, 3, 1, None, False)
    assert solid.equals(pad)
    assert area == pytest.approx(4)


def test_plating_mask_only_pads_excludes_trace_aperture_records():
    pad = Point(0, 0).buffer(1)
    trace = box(4, 0, 6, 2)
    tools = {10: {'type': 'C', 'size': 2, 'geometry': [
        {'solid': pad, 'follow': Point(0, 0)}, {'solid': trace, 'follow': trace.exterior}]}}
    solid, apertures, follows, area = plating_mask([pad, trace], tools, [Point(0, 0), trace.exterior], [], [], [],
                                                  0, 3, 1, None, True)
    assert solid.equals(pad)
    assert unary_union([record['solid'] for aperture in apertures.values()
                        for record in aperture.get('geometry', [])]).equals(pad)
    assert len(tools[10]['geometry']) == 2
    assert len(follows) == 1 and follows[0].equals(Point(0, 0))


def test_plating_mask_robber_with_no_source_apertures():
    line = box(0, 0, 10, 10).exterior
    robber = line.buffer(0.5)
    solid, apertures, follows, area = plating_mask([], {}, [], [], [robber], [line],
                                                  0.2, 2, 3, 1, False)
    assert solid.equals(robber.buffer(0.2))
    aperture = next(iter(apertures.values()))
    assert aperture['geometry'][0]['solid'].equals(solid)
    assert len(follows) == 1 and follows[0].equals(line)
    assert area == pytest.approx(solid.area)


@pytest.mark.parametrize("fill_type", [1, 2, 3])
def test_copper_grid_rejects_zero_size(fill_type):
    checks = iter([False, False, True])
    with pytest.raises(ValueError, match="positive"):
        copper_fill([box(0, 0, 2, 2)], {}, None, None, 0, 'rect', 0.2, 1, 0,
                    fill_type, 0, 0, 0, 0, 0, 0, 32, abort=lambda: next(checks, True))


def test_copper_thieving_zero_grid_reports_parameter_and_creates_nothing():
    source = SimpleNamespace(obj_options={'name': 'board'}, solid_geometry=[box(0, 0, 2, 2)], tools={})
    app = MagicMock()
    app.abort_flag = False
    ui = MagicMock()
    for name, value in [('reference_combo', 0), ('bbox_type_radio', 'rect'), ('area_entry', 0),
                        ('fill_type_combo', 1), ('dot_dia_entry', 0), ('dot_spacing_entry', 1),
                        ('square_size_entry', 1), ('squares_spacing_entry', 1),
                        ('line_size_entry', 1), ('lines_spacing_entry', 1)]:
        getattr(ui, name).get_value.return_value = value
    created = []
    tool = SimpleNamespace(app=app, ui=ui, grb_object=source, geo_steps_per_circle=32, flat_geometry=[],
                           new_object=lambda *a, **kw: created.append(a), on_exit=lambda: None)
    ToolCopperThieving.copper_thieving(tool, source, c_val=0.5, margin=1, run_threaded=False)
    messages = [call.args[0] for call in app.inform.emit.call_args_list]
    assert any(m.startswith('[ERROR_NOTCL]') and 'Grid size' in m for m in messages)
    assert not any('No object available' in m for m in messages)
    assert created == []


def test_copper_line_grid_respects_clearance_and_does_not_reuse_old_fill():
    source = box(0, 0, 4, 4)
    old_fill = box(50, 50, 51, 51)
    fill, merged, tools = copper_fill([source], {}, None, None, 0, 'rect', 0.5, 0.1, 0,
                                      3, 1, 1, 1, 1, 2, 1, 32, line_fill=[old_fill])
    added = unary_union(fill)
    assert added.intersection(source.buffer(0.5, quad_segs=8)).area < 1e-9
    assert added.intersection(old_fill).is_empty


@pytest.mark.parametrize("reference_kind", ['geometry', 'excellon'])
def test_copper_square_grid_covers_reference_outside_source_extent(reference_kind):
    reference = box(10, 10, 14, 14)
    fill, merged, tools = copper_fill([box(0, 0, 1, 1)], {}, [reference], reference_kind,
                                      2, 'rect', 0.2, 0, 0, 2, 1, 1, 1, 1, 1, 1, 32)
    assert len(fill) == 4
    assert unary_union(fill).area == pytest.approx(4)
    assert all(poly.within(reference) for poly in fill)


@pytest.mark.parametrize("box_type", ['rect', 'min'])
def test_copper_self_boundary_does_not_depend_on_source_container(box_type):
    source = Polygon([(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)])
    results = []
    for geometry in [source, [source], MultiPolygon([source]), GeometryCollection([source])]:
        fill, merged, tools = copper_fill(geometry, {}, None, None, 0, box_type, 0.2, 1, 0,
                                          0, 1, 1, 1, 1, 1, 1, 32)
        results.append(unary_union(fill))
    assert all(geometry.equals(results[0]) for geometry in results[1:])


def test_copper_dot_grid_larger_than_boundary_is_empty():
    fill, merged, tools = copper_fill([box(0, 0, 1, 1)], {}, None, None, 0, 'rect', 0.2, 1, 0,
                                      1, 10, 1, 1, 1, 1, 1, 32)
    assert fill == []
    assert merged.symmetric_difference(box(0, 0, 1, 1)).area < 1e-12


def test_copper_line_grid_with_empty_source_returns_empty_geometry():
    fill, merged, tools = copper_fill([], {}, None, None, 0, 'rect', 0.2, 1, 0,
                                      3, 1, 1, 1, 1, 1, 1, 32)
    assert fill == []
    assert merged.is_empty


def test_plating_clearance_export_records_describe_actual_openings():
    pad = Point(0, 0).buffer(1)
    tools = {10: {'type': 'C', 'size': 2, 'geometry': [{'solid': pad, 'follow': Point(0, 0)}]}}
    solid, apertures, follows, area = plating_mask([pad], tools, [Point(0, 0)], [], [], [],
                                                  0.25, 3, 1, None, False)
    exported = []
    for apid, aperture in apertures.items():
        for record in aperture.get('geometry', []):
            exported.append(record['solid'] if apid == 0 else
                            record['follow'].buffer(aperture['size'] / 2))
    assert unary_union(exported).symmetric_difference(solid).area < 1e-9
    assert tools[10]['size'] == 2
    assert area == pytest.approx(solid.area)
    app = make_app()
    code = GerberObject.export_gerber(SimpleNamespace(app=app, tools=apertures), 4, 6)
    parsed = Gerber(app)
    parsed.parse_lines(['%FSLAX46Y46*%', '%MOMM*%', '%ADD10C,2*%', 'D10*', 'G01*'] +
                       code.splitlines() + ['M02*'])
    assert unary_union(parsed.solid_geometry).symmetric_difference(solid).area < 1e-5


@pytest.mark.parametrize("clearance, choice", [(0.1, 1), (0, 1), (-0.1, 1),
                                               (0, 0), (0.1, 2), (0, 3)])
def test_plating_export_preserves_nested_openings(clearance, choice):
    center = Point(5, 5)
    pad = center.buffer(2)
    # Thin enclosing rings have less copper area than the islands they enclose.
    source_ring = box(2, 2, 8, 8).difference(box(2.25, 2.25, 7.75, 7.75))
    thieving = box(0, 0, 10, 10).difference(box(0.25, 0.25, 9.75, 9.75))
    robber_line = box(-1, -1, 11, 11).exterior
    robber = robber_line.buffer(0.15)
    tools = {10: {'type': 'C', 'size': 4, 'geometry': [{'solid': pad, 'follow': center}]},
             20: {'type': 'P', 'size': 0, 'geometry': [
                 {'solid': source_ring, 'follow': source_ring.exterior}]}}
    solid, apertures, follows, area = plating_mask(
        [pad, source_ring], tools, [center, source_ring.exterior], [thieving], robber, robber_line,
        clearance, choice, 0.3, 0.3, False)
    expected = [pad.buffer(clearance), source_ring.buffer(clearance)]
    if choice in (0, 1):
        expected.append(thieving.buffer(clearance))
    if choice in (0, 2):
        expected.append(robber.buffer(clearance))
    expected = unary_union(expected)
    assert solid.symmetric_difference(expected).area < 1e-9
    assert area == pytest.approx(expected.area)
    assert len(tools[10]['geometry']) == len(tools[20]['geometry']) == 1
    app = make_app()
    code = GerberObject.export_gerber(SimpleNamespace(app=app, tools=apertures), 4, 6)
    definitions = [f'%ADD{apid}C,{aperture["size"]}*%' for apid, aperture in apertures.items()
                   if apid and aperture['type'] == 'C']
    parsed = Gerber(app)
    parsed.parse_lines(['%FSLAX46Y46*%', '%MOMM*%', '%ADD99C,0.01*%'] + definitions +
                       ['D99*', 'G01*'] + code.splitlines() + ['M02*'])
    assert unary_union(parsed.solid_geometry).symmetric_difference(expected).area < 1e-5


def test_plating_export_keeps_pad_inside_buffered_thieving_hole():
    center = Point(5, 5)
    pad = center.buffer(1)
    thieving = box(0, 0, 10, 10).difference(pad.buffer(0.5))
    tools = {2: {'type': 'C', 'size': 2, 'geometry': [{'solid': pad, 'follow': center}]}}
    solid, apertures, follows, area = plating_mask(
        pad, tools, [center], thieving, None, None, 0.1, 1, 1, None, True)
    expected = unary_union([pad.buffer(0.1), thieving.buffer(0.1)])
    assert solid.equals(expected)
    assert area == pytest.approx(expected.area)
    assert len(follows) == 1 and follows[0].equals(center)
    app = make_app()
    code = GerberObject.export_gerber(SimpleNamespace(app=app, tools=apertures), 4, 6)
    parsed = Gerber(app)
    parsed.parse_lines(['%FSLAX46Y46*%', '%MOMM*%', '%ADD10C,2*%', 'D10*', 'G01*'] +
                       code.splitlines() + ['M02*'])
    assert unary_union(parsed.solid_geometry).symmetric_difference(expected).area < 1e-5


def test_robber_bar_preserves_collection_source_and_single_follow():
    source = box(0, 0, 4, 4)
    follow = source.exterior
    line, bar, solid, tools, follows = robber_bar_data(GeometryCollection([source]), {}, follow, 1, 0.5)
    assert solid.equals(unary_union([source, bar]))
    assert len(follows) == 2
    assert follows[0].equals(follow)


def test_copper_generation_export_preserves_source_region_islands(qapp):
    pad = box(4, 4, 6, 6)
    ring = box(2, 2, 8, 8).difference(box(2.1, 2.1, 7.9, 7.9))
    source = SimpleNamespace(obj_options={'name': 'board'}, solid_geometry=[pad, ring],
                             tools={0: {'type': 'REG', 'size': 0, 'geometry': [
                                 {'solid': poly, 'follow': poly.exterior} for poly in [pad, ring]]}},
                             follow_geometry=[pad.exterior, ring.exterior], follow=False)
    export_app = make_app()
    app = MagicMock()
    app.abort_flag = False
    app.collection.index.return_value.internalPointer.return_value.obj = source
    ui = MagicMock()
    for name, value in [('reference_combo', 0), ('bbox_type_radio', 'rect'), ('area_entry', 0),
                        ('fill_type_combo', 0), ('rb_margin_entry', 1), ('rb_thickness_entry', 0.5)]:
        getattr(ui, name).get_value.return_value = value
    outputs = []

    def new_object(kind, name, initialize, **kwargs):
        obj = SimpleNamespace(app=export_app, export_as_regions=False)
        obj.export_gerber = lambda *args, **kw: GerberObject.export_gerber(obj, *args, **kw)
        obj.regenerate_source = lambda **kw: outputs.append((obj, export_gerber_text(export_app, obj)))
        initialize(obj, app)

    tool = SimpleNamespace(app=app, ui=ui, grb_object=source, geo_steps_per_circle=32,
                           flat_geometry=[], new_object=new_object, on_exit=lambda: None)
    for clearance in (0.5, 0):
        ToolCopperThieving.copper_thieving(tool, source, c_val=clearance, margin=2, run_threaded=False)
    ToolCopperThieving.on_add_robber_bar_click(tool)
    assert len(outputs) == 3
    differences = []
    for obj, code in outputs:
        parsed = Gerber(export_app)
        parsed.parse_lines(code.splitlines())
        actual = unary_union(parsed.solid_geometry)
        expected = unary_union(obj.solid_geometry)
        differences.append(actual.symmetric_difference(expected).area)
        assert obj.tools[0]['geometry'][0]['solid'].equals(pad)
    assert len(source.tools[0]['geometry']) == 2
    assert source.solid_geometry == [pad, ring]
    assert differences == pytest.approx([0, 0, 0], abs=1e-5)


def test_plating_negative_clearance_can_split_thieving_openings():
    thieving = unary_union([box(0, 0, 2, 2), box(3, 0, 5, 2), box(1, 0.8, 4, 1.2)])
    expected = thieving.buffer(-0.3)
    solid, tools, follows, area = plating_mask([], {}, [], [thieving], [], [], -0.3, 1, 1, None, False)
    assert isinstance(solid, MultiPolygon)
    assert solid.equals(expected)
    assert unary_union([record['solid'] for record in tools[0]['geometry']]).equals(expected)
    assert area == pytest.approx(expected.area)


def test_plating_eroded_robber_does_not_export_negative_aperture():
    line = box(0, 0, 10, 10).exterior
    robber = line.buffer(0.5)
    solid, tools, follows, area = plating_mask([], {}, [], [], robber, line, -1, 2, 1, 1, False)
    assert solid.is_empty and area == 0
    assert all(aperture['size'] >= 0 for aperture in tools.values())
    assert not follows


def test_copper_area_selection_uses_world_coordinates_once():
    app = MagicMock()
    app.grid_status.return_value = False
    app.plotcanvas.translate_coords.side_effect = lambda pos: (pos[0] / 10, pos[1] / 10)
    tool = SimpleNamespace(app=app, first_click=False, cursor_pos=None)
    ToolCopperThieving.on_mouse_release(tool, SimpleNamespace(button=1, pos=(100, 200)))
    assert tool.cursor_pos == (10, 20)


@pytest.mark.parametrize("source_name, output_name", [('board', 'board_plating_mask'),
                                                      ('board.gbr', 'board_plating_mask.gbr')])
def test_plating_controller_preserves_source_name_and_metric_area(source_name, output_name):
    source = SimpleNamespace(obj_options={'name': source_name}, solid_geometry=[box(0, 0, 10, 10)],
                             tools={}, follow_geometry=[])
    app = MagicMock()
    app.collection.index.return_value.internalPointer.return_value.obj = source
    ui = MagicMock()
    ui.clearance_ppm_entry.get_value.return_value = 0
    ui.ppm_choice_combo.get_value.return_value = 3
    ui.rb_thickness_entry.get_value.return_value = 1
    ui.only_pads_cb.get_value.return_value = False
    outputs = []

    def new_object(kind, name, initialize, **kwargs):
        obj = SimpleNamespace(regenerate_source=MagicMock())
        initialize(obj, app)
        outputs.append(obj)

    tool = SimpleNamespace(app=app, ui=ui, units='MM', thief_solid_geometry=[], robber_geo=None,
                           robber_line=None, rb_thickness=None, new_object=new_object, on_exit=lambda: None)
    ToolCopperThieving.on_new_pattern_plating_object(tool)
    assert outputs[0].obj_options['name'] == output_name
    assert outputs[0].solid_geometry[0].equals(source.solid_geometry[0])
    assert ui.plated_area_entry.set_value.call_args.args == (1.0,)
