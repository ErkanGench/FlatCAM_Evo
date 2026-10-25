"""Extract plugin core (appPlugins/ToolExtract/ExtractGen.py): drills, soldermask and cutout from Gerber data.

Behavior only: Shapely geometry in, ExtractResult / counts out. No Qt, no app.
"""

import pytest
from shapely import LineString, MultiPolygon, Point, Polygon
from shapely.geometry import box

from appPlugins.ToolExtract import ExtractGen as eg

ALL = ('circular', 'oblong', 'square', 'rectangular', 'other')


def flash(x, y, r):
    """Dark circular flash geo element."""
    return {'solid': Point(x, y).buffer(r), 'follow': Point(x, y)}


def circ(size, *xy):
    """C aperture with one dark flash per (x, y)."""
    return {'type': 'C', 'size': size, 'geometry': [flash(x, y, size / 2) for x, y in xy]}


def rect(kind_type, w, h, *xy):
    """R or O aperture with one dark flash per (x, y), centred on each point."""
    geo = [{'solid': box(x - w / 2, y - h / 2, x + w / 2, y + h / 2), 'follow': Point(x, y)} for x, y in xy]
    return {'type': kind_type, 'width': w, 'height': h, 'geometry': geo}


@pytest.mark.parametrize('source, expected', [
    ('board.gbr', 'board_drills'),
    ('board', 'board_drills'),
    ('a.b.gbr', 'a.b_drills'),
])
def test_out_name(source, expected):
    assert eg.out_name(source, 'drills') == expected


@pytest.mark.parametrize('aperture, kind', [
    ({'type': 'C', 'size': 1.0}, 'circular'),
    ({'type': 'O', 'width': 2.0, 'height': 1.0}, 'oblong'),
    ({'type': 'R', 'width': 1.0, 'height': 1.0}, 'square'),
    ({'type': 'R', 'width': 2.0, 'height': 1.0}, 'rectangular'),
    ({'type': 'AM', 'geometry': []}, 'other'),
    ({'type': 'REG', 'size': 0}, 'region'),
])
def test_aperture_kind_by_shape(aperture, kind):
    assert eg.aperture_kind(aperture, 4) == kind


def test_is_square_compares_sides_rounded_to_decimals():
    assert eg.is_square(1.0, 1.00001, 4)
    assert not eg.is_square(1.0, 1.2, 4)


def test_pad_size_of_am_without_geometry_is_none():
    assert eg.pad_size({'type': 'AM', 'geometry': []}) is None
    assert eg.pad_size({'type': 'AM'}) is None


def test_fixed_mode_uses_only_enabled_kinds():
    tools = {
        10: circ(1.0, (0, 0), (2, 0)),              # circular: enabled
        11: rect('R', 1.5, 1.5, (5, 0)),            # square: enabled
        12: rect('R', 2.0, 1.0, (8, 0)),            # rectangular: disabled
        13: rect('O', 2.0, 1.0, (10, 0)),           # oblong: disabled
    }
    res = eg.extract_drills([(tools, None)], 'fixed', ('circular', 'square'), 4, fixed_dia=0.8)
    assert res.error == ''
    assert list(res.tools) == [1]
    assert res.tools[1]['tooldia'] == pytest.approx(0.8)
    assert len(res.tools[1]['drills']) == 3
    assert res.tools[1]['slots'] == []


def test_code_of_disabled_kind_gives_nothing():
    tools = {10: circ(1.0, (0, 0))}
    res = eg.extract_drills([(tools, [10])], 'fixed', ('square',), 4, fixed_dia=0.8)
    assert res.tools == {}
    assert res.error == 'no_apertures'


def test_fixed_zero_diameter_is_bad_diameter():
    tools = {10: circ(1.0, (0, 0))}
    res = eg.extract_drills([(tools, None)], 'fixed', ('circular',), 4, fixed_dia=0.0)
    assert res.error == 'bad_diameter'


def test_ring_mode_skips_pads_that_leave_no_hole():
    tools = {
        10: circ(0.3, (0, 0), (1, 0), (2, 0)),      # 0.3 - 2 * 0.2 <= 0
        11: circ(1.0, (5, 0)),                      # 1.0 - 2 * 0.2 = 0.6
    }
    res = eg.extract_drills([(tools, None)], 'ring', ('circular',), 4, rings={'circular': 0.2})
    assert res.error == ''
    assert res.skipped['non_positive'] == 3
    assert [t['tooldia'] for t in res.tools.values()] == pytest.approx([0.6])
    assert len(res.tools[1]['drills']) == 1


def test_regions_never_give_drills_even_with_other_enabled():
    reg = {'type': 'REG', 'size': 0, 'geometry': [{'solid': box(0, 0, 5, 5)}]}
    tools = {0: reg, 10: circ(1.0, (10, 0))}
    rings = {'circular': 0.2, 'other': 0.2}
    res = eg.extract_drills([(tools, None)], 'ring', ALL, 4, rings=rings)
    assert res.error == ''
    assert sum(len(t['drills']) for t in res.tools.values()) == 1
    assert [t['tooldia'] for t in res.tools.values()] == pytest.approx([0.6])


def test_clear_flashes_give_no_drills():
    clear_only = {'type': 'C', 'size': 1.0,
                  'geometry': [{'clear': Point(0, 0).buffer(0.5), 'follow': Point(0, 0)}]}
    res = eg.extract_drills([({10: clear_only}, None)], 'fixed', ALL, 4, fixed_dia=0.8)
    assert res.tools == {}
    assert res.error == 'no_pads'


def test_duplicate_location_keeps_larger_pad():
    tools = {10: circ(0.8, (3, 3)), 11: circ(1.2, (3, 3))}
    res = eg.extract_drills([(tools, None)], 'prop', ('circular',), 4, factor=1.0)
    assert res.skipped['duplicate'] == 1
    assert list(res.tools) == [1]
    assert res.tools[1]['tooldia'] == pytest.approx(1.2)
    assert len(res.tools[1]['drills']) == 1


def test_tools_numbered_by_diameter_and_equal_rounded_sizes_share_a_tool():
    tools = {
        10: circ(1.0, (0, 0), (2, 0)),
        11: circ(0.5, (1, 0)),
        12: circ(0.7, (4, 0)),
        13: circ(0.500001, (3, 0)),                 # rounds to 0.5 with 4 decimals
    }
    res = eg.extract_drills([(tools, None)], 'prop', ('circular',), 4, factor=1.0)
    assert list(res.tools) == [1, 2, 3]
    assert [t['tooldia'] for t in res.tools.values()] == pytest.approx([0.5, 0.7, 1.0])
    assert [len(t['drills']) for t in res.tools.values()] == [2, 1, 2]


def test_oblong_pads_become_slots_only_with_flag():
    tools = {10: rect('O', 2.0, 1.0, (5, 5))}
    rings = {'oblong': 0.25}                        # dia = 1.0 - 2 * 0.25 = 0.5

    res = eg.extract_drills([(tools, None)], 'ring', ('oblong',), 4, rings=rings, oblong_slots=True)
    assert res.error == ''
    assert res.tools[1]['tooldia'] == pytest.approx(0.5)
    assert res.tools[1]['drills'] == []
    assert len(res.tools[1]['slots']) == 1
    start, stop = res.tools[1]['slots'][0]
    assert (start.x, start.y) == pytest.approx((4.5, 5))
    assert (stop.x, stop.y) == pytest.approx((5.5, 5))

    plain = eg.extract_drills([(tools, None)], 'ring', ('oblong',), 4, rings=rings, oblong_slots=False)
    assert len(plain.tools[1]['drills']) == 1
    assert plain.tools[1]['slots'] == []


def test_two_sources_merge_into_one_result():
    a = {10: circ(1.0, (0, 0))}
    b = {10: circ(0.6, (1, 1))}
    res = eg.extract_drills([(a, None), (b, None)], 'prop', ('circular',), 4, factor=1.0)
    assert res.error == ''
    assert sorted(t['tooldia'] for t in res.tools.values()) == pytest.approx([0.6, 1.0])
    assert sum(len(t['drills']) for t in res.tools.values()) == 2


def test_soldermask_grows_pads_renumbers_codes_and_keeps_source():
    tools = {5: circ(1.0, (0, 0)), 7: circ(0.5, (3, 0))}
    solid5 = tools[5]['geometry'][0]['solid']
    source_area = sum(el['solid'].area for ap in tools.values() for el in ap['geometry'])

    res = eg.extract_soldermask([(tools, None)], ALL, 0.1, 4)

    assert res.error == ''
    assert sorted(res.tools) == [10, 11]
    assert res.tools[10]['size'] == pytest.approx(1.2)
    assert res.tools[11]['size'] == pytest.approx(0.7)
    assert sum(s.area for s in res.solid_geometry) > source_area
    # the source tools dict is untouched
    assert set(tools) == {5, 7}
    assert tools[5]['size'] == pytest.approx(1.0)
    assert tools[7]['size'] == pytest.approx(0.5)
    assert tools[5]['geometry'][0]['solid'] is solid5


def test_soldermask_adds_regions_only_with_flag():
    reg = {'type': 'REG', 'size': 0, 'geometry': [{'solid': box(5, 5, 6, 6)}]}
    tools = {0: reg, 10: circ(1.0, (0, 0))}
    without = eg.extract_soldermask([(tools, None)], ALL, 0.0, 4)
    with_regions = eg.extract_soldermask([(tools, None)], ALL, 0.0, 4, include_regions=True)
    assert len(without.solid_geometry) == 1
    assert len(with_regions.solid_geometry) == 2
    assert with_regions.error == ''


def test_soldermask_without_matching_pads_is_no_pads():
    res = eg.extract_soldermask([({10: circ(1.0, (0, 0))}, None)], ('square',), 0.1, 4)
    assert res.error == 'no_pads'


def test_cutout_rect_outline_is_bounds_grown_by_margin():
    geo = [box(0, 0, 2, 2), box(4, 4, 6, 6)]
    res = eg.extract_cutout(geo, 1.0, 0.5)
    assert res.error == ''
    assert isinstance(res.follow_geometry[0], LineString)
    assert res.follow_geometry[0].bounds == pytest.approx((-1, -1, 7, 7))
    assert len(res.solid_geometry) == 1


def test_cutout_walks_nested_lists_with_multipolygon_and_linestring():
    geo = [MultiPolygon([box(0, 0, 1, 1), box(3, 3, 4, 4)]), [LineString([(0, 5), (6, 5)])]]
    res = eg.extract_cutout(geo, 0.0, 0.2)
    assert res.error == ''
    assert res.follow_geometry[0].bounds == pytest.approx((0, 0, 6, 5))


def test_cutout_convex_triangle_gives_closed_outline():
    tri = Polygon([(0, 0), (4, 0), (0, 3)])
    res = eg.extract_cutout(tri, 0.0, 0.2, shape='convex')
    assert res.error == ''
    assert len(res.follow_geometry[0].coords) == 4


@pytest.mark.parametrize('geometry, margin, thickness, error', [
    ([box(0, 0, 2, 2)], 1.0, 0.0, 'bad_thickness'),
    ([], 1.0, 0.5, 'no_geometry'),
    ([box(0, 0, 2, 2)], -1.5, 0.5, 'empty_shape'),
])
def test_cutout_errors(geometry, margin, thickness, error):
    res = eg.extract_cutout(geometry, margin, thickness)
    assert res.error == error


def test_count_pads_counts_dark_flashes_of_enabled_kinds_only():
    tools = {
        10: {'type': 'C', 'size': 1.0,
             'geometry': [flash(0, 0, 0.5),
                          {'clear': Point(3, 0).buffer(0.5), 'follow': Point(3, 0)}]},   # clear: not counted
        11: circ(1.0, (1, 0), (2, 0)),
        12: rect('R', 1.0, 1.0, (4, 0)),                                                  # square: disabled
    }
    assert eg.count_pads(tools, None, 4, ('circular',)) == 3
    assert eg.count_pads(tools, [11], 4, ('circular',)) == 2
    assert eg.count_pads(tools, None, 4, ('square',)) == 1


# ---- Tcl command: extract ----------------------------------------------------------------------------------------
def _extract_command(**tools):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tclCommands.TclCommandExtract import TclCommandExtract
    from test_tcl_audit_regressions import object_app
    gerber = SimpleNamespace(kind='gerber', multigeo=False, obj_options={'name': 'board.gbr', 'units': 'MM'},
                             tools=tools or {10: circ(1.0, (0, 0), (5, 0))},
                             solid_geometry=[box(-1, -1, 6, 3)])
    app = object_app(None)
    app.collection.get_by_name.side_effect = {'board.gbr': gerber}.get
    app.app_obj = Mock()
    app.options = {}
    app.decimals = 4
    return TclCommandExtract(app), app


def _run_init(app, kind):
    from unittest.mock import Mock
    args, kwargs = app.app_obj.new_object.call_args
    assert args[0] == kind and kwargs['plot'] is False
    new = Mock()
    new.obj_options = {}
    new.create_geometry.return_value = None
    assert args[2](new, app) != 'fail'
    return args[1], new


def test_tcl_extract_drills_makes_an_excellon_with_one_hole_per_pad():
    command, app = _extract_command()
    command.execute({'object': 'board.gbr', 'type': 'drills', 'dia': 0.6}, [])
    name, new = _run_init(app, 'excellon')
    assert name == 'board_extracted'
    assert new.tools[1]['tooldia'] == pytest.approx(0.6)
    assert len(new.tools[1]['drills']) == 2


def test_tcl_extract_soldermask_and_cutout_make_gerbers():
    command, app = _extract_command()
    command.execute({'object': 'board.gbr', 'type': 'soldermask', 'clearance': 0.1}, [])
    name, new = _run_init(app, 'gerber')
    assert name == 'board_esm' and len(new.solid_geometry) == 2
    new.regenerate_source.assert_called_once()
    command.execute({'object': 'board.gbr', 'type': 'cutout', 'margin': 1.0, 'thickness': 0.2, 'outname': 'cut'}, [])
    name, new = _run_init(app, 'gerber')
    assert name == 'cut' and new.solid_geometry[0].bounds == pytest.approx((-2.1, -2.1, 7.1, 4.1))


def test_tcl_extract_bad_input_is_a_tcl_error_and_creates_nothing():
    from test_tcl_audit_regressions import FCShell
    command, app = _extract_command()
    for args in ({'object': 'board.gbr', 'type': 'nope'},
                 {'object': 'missing', 'type': 'drills'},
                 {'object': 'board.gbr', 'type': 'drills', 'dia': 0},
                 {'object': 'board.gbr', 'type': 'cutout', 'thickness': 0},
                 {'object': 'board.gbr', 'type': 'drills', 'kinds': 'triangle'},
                 {'object': 'board.gbr', 'type': 'drills', 'apertures': '99'}):
        with pytest.raises(FCShell.TclErrorException):
            command.execute(args, [])
    app.app_obj.new_object.assert_not_called()
