"""
Freeform cutout (``CutOut.on_freeform_cutout``): golden files of the output of the code before the F10 change, and
the F10 tests (inner contours of a board outline).

The golden tests run the production path on a headless ``CutOut`` and compare ``solid_geo``, ``gaps_solid_geo`` and the
mouse-bite ``holes`` with ``tests/fixtures/cutout/golden_<name>.json`` (WKT, 6 decimals).
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import shapely
from PyQt6 import QtGui, QtWidgets
from shapely.geometry import Polygon, box

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_unify_characterization import _headless_qt, make_app, make_gerber  # noqa: F401,E402

FIX = Path(__file__).parent / 'fixtures' / 'cutout'


# ---------------------------------------------------------------------------------------------------------------
# headless harness
# ---------------------------------------------------------------------------------------------------------------

class _Collection(QtGui.QStandardItemModel):
    """Stands in for ObjectCollection: the combo boxes need a real model, the tool needs a few methods."""

    def __init__(self):
        super().__init__()
        self.objs = {}

    def get_by_name(self, name):
        return self.objs[name]

    def promise(self, name):
        pass


def make_geometry(app, name, geos):
    from appObjects.GeometryObject import GeometryObject
    obj = GeometryObject(name, app)
    obj.solid_geometry = geos
    obj.multigeo = False
    return obj


def geometry_sources(app):
    return {
        'geo_single': make_geometry(app, 'geo_single', Polygon([(0, 0), (50, 0), (50, 30), (0, 30)])),
        'geo_slot': make_geometry(app, 'geo_slot', [box(0, 0, 50, 30), box(20, 13.5, 30, 16.5)]),
        'geo_panel2': make_geometry(app, 'geo_panel2', [box(0, 0, 40, 25), box(50, 0, 90, 25)]),
    }


def load_source(app, name):
    if name.startswith('geo_'):
        return geometry_sources(app)[name]
    return make_gerber(app, str(FIX / (name + '.gbr')), name=name + '.gbr')


def make_tool():
    from appPlugins.ToolCutOut import CutOut
    app = make_app()
    app.collection = _Collection()
    app.resource_location = 'res'
    app.plotcanvas = Mock()
    app.proj_selection_changed = Mock()
    app.worker_task = SimpleNamespace(emit=lambda d: d['fcn'](*d['params']))
    app.created = {}
    app.app = app
    app.f_handlers = Mock()

    def new_object(kind, name, init, autoselected=False):
        if kind == 'geometry':
            from appObjects.GeometryObject import GeometryObject
            obj = GeometryObject(name, app)
        else:
            from appObjects.ExcellonObject import ExcellonObject
            obj = ExcellonObject(name, app)
        ret = init(obj, app)
        if ret == 'fail':
            return 'fail'
        app.created[name] = obj
        return None

    app.app_obj = SimpleNamespace(new_object=new_object)
    with patch('appObjects.AppObjectTemplate.ShapeCollection'):
        tool = CutOut(app)
    tool.cut_tool_dict = {'tooldia': 2.4, 'data': {}, 'solid_geometry': []}
    tool.test_app = app
    return tool


@pytest.fixture
def cutout_app():
    return make_tool()


# the defaults of the plugin: tool 2.4, margin 0.1, 4 gaps of 4 mm, thin gap depth -1.0, bites 0.6 / 0.3
BASE = dict(dia=2.4, margin=0.1, gaps='4', gapsize=4.0, gap_type=0, thin=-1.0, mb_dia=0.6, mb_spacing=0.3,
            convex=False, kind='single')

# name: (source, overrides)
CASES = {
    'single_gerber': ('outline_single', {}),
    'panel_gerber': ('outline_panel2', {'kind': 'panel'}),
    'single_geometry': ('geo_single', {}),
    'panel_geometry': ('geo_panel2', {'kind': 'panel'}),
    'geo_panel2_single': ('geo_panel2', {}),
    'neg_single_gerber': ('outline_single', {'margin': -0.3}),
    'neg_panel_gerber': ('outline_single', {'margin': -0.3, 'kind': 'panel'}),
    'neg_single_geometry': ('geo_single', {'margin': -0.3}),
    'neg_panel_geometry': ('geo_single', {'margin': -0.3, 'kind': 'panel'}),
    'thin_gaps_gerber': ('outline_single', {'gap_type': 1}),
    'mouse_bites_gerber': ('outline_single', {'gap_type': 2}),
    'mouse_bites_panel_gerber': ('outline_panel2', {'gap_type': 2, 'kind': 'panel'}),
    'mouse_bites_geometry': ('geo_single', {'gap_type': 2}),
    'slot_single': ('outline_slot', {}),
    'slot_panel': ('outline_slot', {'kind': 'panel'}),
    'island_slot_single': ('outline_island_slot', {}),
    'panel2_single': ('outline_panel2', {}),
    'clearance_single': ('copper_clearance', {}),
    'clearance_panel': ('copper_clearance', {'kind': 'panel'}),
    'region_cutout_single': ('outline_region_cutout', {}),
    'region_cutout_panel': ('outline_region_cutout', {'kind': 'panel'}),
    'rect_aperture_single': ('outline_rect_aperture', {}),
    'narrow_slot_single': ('outline_narrow_slot', {}),
    'slot_convex': ('outline_slot', {'convex': True}),
    'geo_slot_single': ('geo_slot', {}),
    'no_gaps_gerber': ('outline_single', {'gaps': 'None'}),
}


def configure(tool, name, params):
    """Put the plugin controls to the values of ``params``."""
    ui = tool.ui
    ui.obj_combo = SimpleNamespace(currentText=lambda: name)
    ui.dia.set_value(params['dia'])
    ui.margin.set_value(params['margin'])
    ui.gaps.set_value(params['gaps'])
    ui.gapsize.set_value(params['gapsize'])
    ui.gaptype_combo.set_value(params['gap_type'])
    ui.thin_depth_entry.set_value(params['thin'])
    ui.mb_dia_entry.set_value(params['mb_dia'])
    ui.mb_spacing_entry.set_value(params['mb_spacing'])
    ui.convex_box_cb.set_value(params['convex'])
    ui.obj_kind_combo.set_value(params['kind'])


def flat(geo):
    if geo is None:
        return []
    if isinstance(geo, (list, tuple)):
        out = []
        for g in geo:
            out.extend(flat(g))
        return out
    if hasattr(geo, 'geoms'):
        return list(geo.geoms)
    return [geo]


def wkt(geo):
    return shapely.to_wkt(geo, rounding_precision=6, trim=False)


def run_case(tool, source_name, overrides, after_configure=None):
    """Run the production freeform cutout. Returns solid_geo / gaps_solid_geo / holes as lists of rounded WKT."""
    app = tool.test_app
    obj = load_source(app, source_name)
    app.collection.objs[obj.obj_options['name']] = obj
    params = dict(BASE)
    params.update(overrides)
    configure(tool, obj.obj_options['name'], params)
    if after_configure:
        after_configure(tool)
    app.created.clear()
    tool.on_freeform_cutout()
    out = {'solid_geo': [], 'gaps_solid_geo': [], 'holes': []}
    for name, created in app.created.items():
        if name.endswith('_cutout'):
            tools = created.tools
            out['solid_geo'] = [wkt(g) for g in flat(tools[1]['solid_geometry'])]
            if 99 in tools:
                out['gaps_solid_geo'] = [wkt(g) for g in flat(tools[99]['solid_geometry'])]
        else:
            drills = [d for t in created.tools.values() for d in t['drills']]
            out['holes'] = [wkt(d) for d in drills]
    return out


def golden_path(case):
    return FIX / ('golden_%s.json' % case)


def load_golden(case):
    return json.loads(golden_path(case).read_text())


def check_golden(tool, case):
    source, overrides = CASES[case]
    got = run_case(tool, source, overrides)
    assert got == load_golden(case), case


# ---------------------------------------------------------------------------------------------------------------
# the output of the code before the change (the option is absent)
# ---------------------------------------------------------------------------------------------------------------

def test_off_single_gerber_matches_golden(cutout_app):
    for case in ('single_gerber', 'slot_single', 'island_slot_single', 'clearance_single', 'region_cutout_single',
                 'narrow_slot_single', 'rect_aperture_single', 'no_gaps_gerber'):
        check_golden(cutout_app, case)


def test_off_panel_gerber_matches_golden(cutout_app):
    for case in ('panel_gerber', 'panel2_single', 'slot_panel', 'clearance_panel', 'region_cutout_panel'):
        check_golden(cutout_app, case)


def test_off_single_and_panel_geometry_match_golden(cutout_app):
    for case in ('single_geometry', 'panel_geometry', 'geo_panel2_single', 'geo_slot_single'):
        check_golden(cutout_app, case)


def test_off_negative_margin_matches_golden(cutout_app):
    for case in ('neg_single_gerber', 'neg_panel_gerber', 'neg_single_geometry', 'neg_panel_geometry'):
        check_golden(cutout_app, case)


def test_off_gaps_thin_and_bites_match_golden(cutout_app):
    for case in ('thin_gaps_gerber', 'mouse_bites_gerber', 'mouse_bites_panel_gerber',
                 'mouse_bites_geometry', 'slot_convex'):
        check_golden(cutout_app, case)


# ---------------------------------------------------------------------------------------------------------------
# the inner contours (F10)
# ---------------------------------------------------------------------------------------------------------------

from shapely.geometry import LineString  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

import appPlugins.ToolCutOut as cutout_module  # noqa: E402
from appPlugins.ToolCutOut import freeform_cutout_paths, offset_contours, outline_contours  # noqa: E402

NO_GAPS = {'gaps': 'None'}
# a small slot needs a small tool and small gaps
SMALL = {'dia': 0.8, 'margin': 0.0, 'gapsize': 1.0}


def new_paths(tool, source, inner_gaps=False, obj=None, **overrides):
    """freeform_cutout_paths with the option on, on a fixture (or on ``obj``)."""
    p = dict(BASE)
    p.update(overrides)
    if obj is None:
        obj = load_source(tool.test_app, source)
    return freeform_cutout_paths(
        obj, p['kind'], p['dia'], p['margin'], p['gaps'], p['gapsize'], p['convex'], p['gap_type'], p['thin'],
        p['mb_dia'], p['mb_spacing'], tool.any_cutout_handler, inner_active=True, inner_gaps=inner_gaps)


def old_paths(tool, source, **overrides):
    p = dict(BASE)
    p.update(overrides)
    obj = load_source(tool.test_app, source)
    return freeform_cutout_paths(
        obj, p['kind'], p['dia'], p['margin'], p['gaps'], p['gapsize'], p['convex'], p['gap_type'], p['thin'],
        p['mb_dia'], p['mb_spacing'], tool.any_cutout_handler)


def bounds(geo):
    return tuple(round(v, 6) for v in geo.bounds)


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def mark_inner(tool, gaps=False):
    tool.ui.is_outline_cb.set_value(True)
    tool.ui.inner_cb.set_value(True)
    tool.ui.inner_gaps_cb.set_value(gaps)


def legacy_gerber_path(obj, margin, radius):
    """The old expression for a Gerber (band of the fused copper, one board)."""
    from appParsers.feature_access import fused_solid
    band = fused_solid(obj)
    if margin >= 0:
        return band.buffer(margin + radius).exterior
    return unary_union(band.buffer(-margin + radius).interiors)


def legacy_geometry_path(poly, margin):
    if margin >= 0:
        return poly.buffer(margin).exterior
    return unary_union(poly.buffer(1e-7).exterior.buffer(-margin).interiors)


@pytest.mark.parametrize('margin', [0.1, -0.3])
def test_outer_offset_equals_old_formula(cutout_app, margin):
    app = cutout_app.test_app
    grb = load_source(app, 'outline_single')
    contour = outline_contours(grb, False, 'single')
    assert len(contour) == 1
    new = offset_contours(contour, margin, 1.2, 'gerber')[0][0]
    old = legacy_gerber_path(grb, margin, 1.2)
    assert new.hausdorff_distance(old) < 3e-3      # corner arcs are polygons of a different resolution

    geo = geometry_sources(app)['geo_single']
    contour = outline_contours(geo.solid_geometry, False, 'single')
    new = offset_contours(contour, margin, 1.2, 'geometry')[0][0]
    old = legacy_geometry_path(geo.solid_geometry, margin)
    assert new.hausdorff_distance(old) < 1e-5


def test_outer_offset_rect_aperture_close_to_old(cutout_app):
    # the fixture uses an oblong 0.2 x 0.2 aperture: the parser keeps no center line for a rectangle aperture draw
    new = new_paths(cutout_app, 'outline_rect_aperture', **NO_GAPS)
    old = old_paths(cutout_app, 'outline_rect_aperture', **NO_GAPS)
    outer_new = max(flat(new.solid_geo), key=lambda g: g.length)
    outer_old = max(flat(old.solid_geo), key=lambda g: g.length)
    assert outer_new.hausdorff_distance(outer_old) < 0.2 / 2


def test_option_on_without_outline_mark_is_legacy(cutout_app):
    got = run_case(cutout_app, 'outline_slot', {}, after_configure=lambda t: t.ui.inner_cb.set_value(True))
    assert got == load_golden('slot_single')


def test_copper_with_clearance_gives_no_slot(cutout_app):
    got = run_case(cutout_app, 'copper_clearance', {}, after_configure=lambda t: t.ui.inner_cb.set_value(True))
    assert got == load_golden('clearance_single')
    hole = box(17, 9.5, 23, 15.5)
    assert not any(shapely.from_wkt(w).intersects(hole) for w in got['solid_geo'])


def test_region_hole_is_cutout_when_marked(cutout_app):
    grb = load_source(cutout_app.test_app, 'outline_region_cutout')
    contours = outline_contours(grb, False, 'single')
    assert [(c.side, c.depth) for c in contours] == [('inner', 1), ('outer', 0)]
    res = new_paths(cutout_app, None, obj=grb, **NO_GAPS)
    inner = [g for g in flat(res.solid_geo) if box(20, 13.5, 30, 16.5).contains(g)]
    assert len(inner) == 1
    # w = 0: the path is at margin + r = 1.3 from the edge of the cutout
    assert close(bounds(inner[0]), (21.3, 14.8, 28.7, 15.2))


def test_stroked_ring_hole_is_not_a_cutout(cutout_app):
    contours = outline_contours(load_source(cutout_app.test_app, 'outline_single'), False, 'single')
    assert [(c.side, c.depth) for c in contours] == [('outer', 0)]
    res = new_paths(cutout_app, 'outline_single', **NO_GAPS)
    assert len(flat(res.solid_geo)) == 1
    assert not box(0, 0, 50, 30).contains(flat(res.solid_geo)[0])      # the path is outside the board


def test_x2_profile_attribute_checks_the_mark(cutout_app):
    app = cutout_app.test_app
    for name in ('outline_region_x2', 'outline_region_cutout', 'copper_clearance'):
        app.collection.objs[name] = load_source(app, name)
    cutout_app.apply_outline_mark('outline_region_x2')
    assert cutout_app.ui.is_outline_cb.get_value() is True
    cutout_app.apply_outline_mark('outline_region_cutout')
    assert cutout_app.ui.is_outline_cb.get_value() is False
    cutout_app.apply_outline_mark('copper_clearance')
    assert cutout_app.ui.is_outline_cb.get_value() is False


def test_even_odd_board_slot_island_slot(cutout_app):
    contours = outline_contours(load_source(cutout_app.test_app, 'outline_nested4'), False, 'panel')
    assert [c.depth for c in contours] == [3, 2, 1, 0]
    assert [c.side for c in sorted(contours, key=lambda c: c.depth)] == ['outer', 'inner', 'outer', 'inner']


def test_outline_with_slot(cutout_app):
    res = new_paths(cutout_app, 'outline_slot', **NO_GAPS)
    paths = flat(res.solid_geo)
    assert len(paths) == 2
    slot = min(paths, key=lambda g: g.length)
    outer = max(paths, key=lambda g: g.length)
    # outside edge of the stroke 0.1, margin 0.1, radius 1.2
    assert close(bounds(outer), (-1.4, -1.4, 51.4, 31.4))
    # inside edge of the slot stroke at (20.1, 13.6)-(29.9, 16.4), moved by margin + r into the slot
    assert close(bounds(slot), (21.4, 14.9, 28.6, 15.1))


def test_panel_of_two_boards(cutout_app):
    grb = load_source(cutout_app.test_app, 'outline_panel2')
    contours = outline_contours(grb, False, 'panel')
    assert sorted(c.side for c in contours) == ['inner', 'outer', 'outer']
    inner = [c for c in contours if c.side == 'inner'][0]
    assert inner.ring.bounds[0] >= 50 and inner.ring.bounds[2] <= 90
    res = new_paths(cutout_app, None, obj=grb, kind='panel', **NO_GAPS)
    assert len(flat(res.solid_geo)) == 3


def test_island_in_slot(cutout_app):
    grb = load_source(cutout_app.test_app, 'outline_island_slot')
    contours = outline_contours(grb, False, 'single')
    assert sorted((c.depth, c.side) for c in contours) == [(0, 'outer'), (1, 'inner'), (2, 'outer')]
    res = new_paths(cutout_app, None, obj=grb, **NO_GAPS)
    paths = flat(res.solid_geo)
    # the island first, the board last, also after the merge
    assert [round(Polygon(p).area) for p in paths] == sorted(round(Polygon(p).area) for p in paths)


def test_shared_point_between_slot_and_board(cutout_app):
    board = box(0, 0, 10, 10)
    slot = Polygon([(0, 5), (3, 3), (3, 7)])         # one vertex on the edge of the board
    geo = make_geometry(cutout_app.test_app, 'g', [board, slot])
    contours = outline_contours(geo.solid_geometry, False, 'panel')
    assert sorted((c.depth, c.side) for c in contours) == [(0, 'outer'), (1, 'inner')]


def test_negative_margin_moves_into_board(cutout_app):
    res = new_paths(cutout_app, 'outline_slot', margin=-0.3, **NO_GAPS)
    paths = flat(res.solid_geo)
    slot = min(paths, key=lambda g: g.length)
    outer = max(paths, key=lambda g: g.length)
    # 0.3 + 0.1 (half the stroke) + 1.2 (radius) = 1.6
    assert close(bounds(outer), (1.6, 1.6, 48.4, 28.4))
    assert close(bounds(slot), (18.4, 11.9, 31.6, 18.1))


def test_single_with_two_outer_uses_bbox(cutout_app):
    res = new_paths(cutout_app, 'outline_panel2', **NO_GAPS)
    assert any('Single mode with several outlines' in w for w in res.warnings)
    paths = flat(res.solid_geo)
    assert len(paths) == 2
    outer = max(paths, key=lambda g: g.length)
    assert close(bounds(outer), (-1.4, -1.4, 91.4, 26.4))
    slot = min(paths, key=lambda g: g.length)
    assert box(66, 11, 74, 14).contains(slot)


def test_single_vs_panel_differ_only_in_outer(cutout_app):
    single = new_paths(cutout_app, 'outline_slot', kind='single')
    panel = new_paths(cutout_app, 'outline_slot', kind='panel')
    assert [wkt(g) for g in flat(single.solid_geo)] == [wkt(g) for g in flat(panel.solid_geo)]
    assert not single.warnings and not panel.warnings


def test_gerber_adds_radius_geometry_does_not(cutout_app):
    grb = new_paths(cutout_app, 'outline_slot', **NO_GAPS)
    geo = new_paths(cutout_app, 'geo_slot', **NO_GAPS)
    g_slot = min(flat(grb.solid_geo), key=lambda g: g.length)
    s_slot = min(flat(geo.solid_geo), key=lambda g: g.length)
    assert close(bounds(g_slot), (21.4, 14.9, 28.6, 15.1))              # edge 20.1 + (m + r) = 1.3
    assert close(bounds(s_slot), (20.1, 13.6, 29.9, 16.4))              # m only


def _slot_pieces(res, region=box(20, 13.5, 30, 16.5)):
    return [g for g in flat(res.solid_geo) if region.contains(g)]


def test_gaps_not_on_slots_by_default(cutout_app):
    res = new_paths(cutout_app, 'outline_slot', gaps='4')
    slot = _slot_pieces(res)
    assert len(slot) == 1 and slot[0].is_closed
    outer = [g for g in flat(res.solid_geo) if not box(20, 13.5, 30, 16.5).contains(g)]
    assert len(outer) == 4


def test_gaps_on_slot_when_enabled(cutout_app):
    res = new_paths(cutout_app, 'outline_slot', inner_gaps=True, gaps='4', gap_type=1, **SMALL)
    slot = _slot_pieces(res)
    assert len(slot) == 4 and not any(g.is_closed for g in slot)
    pieces = [g for g in flat(res.gaps_solid_geo) if box(20, 13.5, 30, 16.5).contains(g)]
    assert len(pieces) == 4
    cx = unary_union(pieces).bounds
    assert abs((cx[0] + cx[2]) / 2 - 25) < 1e-6 and abs((cx[1] + cx[3]) / 2 - 15) < 1e-6


def test_thin_gaps_and_mouse_bites_on_slot(cutout_app):
    slot_box = box(20, 13.5, 30, 16.5)
    for inner_gaps in (False, True):
        thin = new_paths(cutout_app, 'outline_slot', inner_gaps=inner_gaps, gap_type=1, **SMALL)
        on_slot = [g for g in flat(thin.gaps_solid_geo) if slot_box.contains(g)]
        assert bool(on_slot) is inner_gaps
        bites = new_paths(cutout_app, 'outline_slot', inner_gaps=inner_gaps, gap_type=2, mb_dia=0.3, mb_spacing=0.2,
                          **SMALL)
        on_slot = [h for h in bites.holes if slot_box.contains(h)]
        assert bool(on_slot) is inner_gaps
        if inner_gaps:
            contours = [c for c in outline_contours(load_source(cutout_app.test_app, 'outline_slot'), False,
                                                    'single') if c.side == 'inner']
            path = offset_contours(contours, 0.0, 0.15, 'gerber')[0][0]
            assert all(path.distance(h) < 1e-6 for h in on_slot)


def test_one_contour_list_for_all_outputs(cutout_app):
    calls = []
    offsets = []
    real_contours, real_offset = cutout_module.outline_contours, cutout_module.offset_contours

    def spy_contours(*args, **kwargs):
        calls.append(1)
        return real_contours(*args, **kwargs)

    def spy_offset(contours, *args, **kwargs):
        offsets.append(list(contours))
        return real_offset(contours, *args, **kwargs)

    with patch.object(cutout_module, 'outline_contours', spy_contours), \
            patch.object(cutout_module, 'offset_contours', spy_offset):
        new_paths(cutout_app, 'outline_slot', inner_gaps=True, gap_type=2, **SMALL)
    assert len(calls) == 1
    assert len(offsets) == 2
    assert all(any(c is d for d in offsets[0]) for c in offsets[1])


def test_narrow_slot_is_skipped_with_warning(cutout_app):
    res = new_paths(cutout_app, 'outline_narrow_slot')
    assert not res.failed
    assert any('1 inner contours were skipped' in w for w in res.warnings)
    assert len(flat(res.solid_geo)) >= 1
    assert not any(box(13, 9.5, 17, 10.5).contains(g) for g in flat(res.solid_geo))


def test_contour_split_keeps_all_parts(cutout_app):
    board = box(0, 0, 50, 30)
    dumbbell = unary_union([box(10, 12, 16, 18), box(24, 12, 30, 18), box(16, 14.5, 24, 15.5)])
    geo = make_geometry(cutout_app.test_app, 'dumb', [board, dumbbell])
    res = new_paths(cutout_app, None, obj=geo, inner_gaps=True, margin=0.8, gaps='None')
    inner = [g for g in flat(res.solid_geo) if board.buffer(-2).contains(g)]
    assert len(inner) == 2         # the offset into the slot removes the 1 mm neck


def test_convex_hull_only_outer(cutout_app):
    hull = new_paths(cutout_app, 'outline_l_slot', convex=True, **NO_GAPS)
    plain = new_paths(cutout_app, 'outline_l_slot', **NO_GAPS)
    slot_box = box(5, 8, 20, 14)
    h_slot = [g for g in flat(hull.solid_geo) if slot_box.contains(g)]
    p_slot = [g for g in flat(plain.solid_geo) if slot_box.contains(g)]
    assert len(h_slot) == 1 and wkt(h_slot[0]) == wkt(p_slot[0])
    h_out = [g for g in flat(hull.solid_geo) if not slot_box.contains(g)][0]
    p_out = [g for g in flat(plain.solid_geo) if not slot_box.contains(g)][0]
    ring = Polygon([(0, 0), (50, 0), (50, 15), (25, 30), (0, 30)])
    assert Polygon(h_out).area > Polygon(p_out).area
    assert h_out.hausdorff_distance(ring.buffer(1.4).exterior) < 1e-3


def test_open_path_in_geometry_is_ignored(cutout_app):
    warnings = []
    contours = outline_contours([box(0, 0, 10, 10), LineString([(20, 0), (30, 5)])], False, 'single', warnings)
    assert len(contours) == 1
    assert warnings == ['open path ignored']


def test_rectangular_ignores_option(cutout_app):
    tool = cutout_app
    tool.ui.cutout_shape_cb.set_value(True)
    mark_inner(tool)
    assert tool.inner_active() is False
    assert tool.ui.inner_cb.isEnabled() is False
    tool.ui.cutout_shape_cb.set_value(False)
    assert tool.inner_active() is True


def test_option_defaults_and_ui_state(cutout_app):
    from defaults import AppDefaults
    assert AppDefaults.factory_defaults['tools_cutout_inner'] is False
    assert AppDefaults.factory_defaults['tools_cutout_inner_gaps'] is False
    tool = cutout_app
    tool.update_inner_state()
    assert tool.ui.inner_cb.isEnabled() is False
    assert tool.ui.inner_gaps_cb.isEnabled() is False
    tool.ui.is_outline_cb.set_value(True)
    assert tool.ui.inner_cb.isEnabled() is True
    assert tool.ui.inner_gaps_cb.isEnabled() is False
    tool.ui.inner_cb.set_value(True)
    assert tool.ui.inner_gaps_cb.isEnabled() is True
    app = tool.test_app
    app.collection.objs['other'] = load_source(app, 'outline_single')
    tool.apply_outline_mark('other')                  # a new source object
    assert tool.ui.is_outline_cb.get_value() is False
    tool.ui.is_outline_cb.set_value(True)
    tool.reset_outline_mark()
    assert tool.ui.is_outline_cb.get_value() is False


def test_does_not_mutate_source_object(cutout_app):
    obj = load_source(cutout_app.test_app, 'outline_island_slot')
    before = obj.solid_geometry
    before_wkt = [wkt(g) for g in flat(before)]
    new_paths(cutout_app, None, obj=obj, inner_gaps=True, gap_type=2)
    assert obj.solid_geometry is before
    assert [wkt(g) for g in flat(obj.solid_geometry)] == before_wkt


def test_production_run_with_option_on(cutout_app):
    got = run_case(cutout_app, 'outline_slot', {}, after_configure=mark_inner)
    assert got['solid_geo'] and got['solid_geo'] != load_golden('slot_single')['solid_geo']
    assert any(box(20, 13.5, 30, 16.5).contains(shapely.from_wkt(w)) for w in got['solid_geo'])


def test_production_run_reports_warnings(cutout_app):
    run_case(cutout_app, 'outline_narrow_slot', {}, after_configure=mark_inner)
    texts = [str(c.args[0]) for c in cutout_app.test_app.inform.emit.call_args_list]
    assert any('[WARNING_NOTCL]' in t and 'inner contours were skipped' in t for t in texts)


def test_ring_without_center_line_never_becomes_a_cutout():
    # a ring drawn with a rectangle aperture: the parser keeps no center line for it, only the band
    band = box(0, 0, 50, 30).difference(box(0.2, 0.2, 49.8, 29.8))
    grb = SimpleNamespace(kind='gerber', tools={
        11: {'type': 'R', 'size': 0.2, 'geometry': [{'solid': band, 'follow': band.representative_point()}]}
    })
    warnings = []
    # a real object composes its copper into this same band
    with patch('appPlugins.ToolCutOut.fused_solid', return_value=band):
        contours = outline_contours(grb, False, 'single', warnings)
    # the hole of the band is the board: it must not be read as a cutout
    assert all(c.side != 'inner' for c in contours)
    assert contours == []
    assert any('without a center line' in w and '11' in w for w in warnings)


def test_off_mouse_bites_negative_margin_single_gerber(cutout_app):
    # it raised TypeError: the bites used buffer(margin - r).exterior, the main cut the inside edge
    got = run_case(cutout_app, 'outline_single', {'gap_type': 2, 'margin': -0.3})
    assert got['solid_geo'] and got['holes']
    # the board ring is 50 x 30 with a 0.2 stroke: its inside edge is 0.1 in; the bites are 0.3 + 0.3 further in
    for hole in (shapely.from_wkt(w) for w in got['holes']):
        x, y = hole.x, hole.y
        assert min(abs(x - 0.7), abs(x - 49.3), abs(y - 0.7), abs(y - 29.3)) < 0.01


def test_region_island_after_clear_cutout_is_kept():
    # dark board, then a clear cutout, then a dark island inside the cutout: the file order decides
    grb = SimpleNamespace(kind='gerber', tools={0: {'type': 'REG', 'size': 0.0, 'geometry': [
        {'solid': box(0, 0, 50, 30)},
        {'clear': box(15, 9, 35, 21)},
        {'solid': box(23, 13, 27, 17)},
    ]}})
    contours = outline_contours(grb, False, 'single')
    assert sorted((c.depth, c.side) for c in contours) == [(0, 'outer'), (1, 'inner'), (2, 'outer')]
