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
