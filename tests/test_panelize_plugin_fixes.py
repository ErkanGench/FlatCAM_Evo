"""Bug fixes of the Panelize plugin (Stage 5), headless (driver: test_panelize_plugin.run_plugin)."""

from io import StringIO

import ezdxf
import pytest
from types import SimpleNamespace
from unittest.mock import Mock
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, box

from appHandlers.appEdit import appEditor
from appObjects.GeometryObject import GeometryObject
from appPlugins.ToolPanelize import Panelize
from appTool import AppTool
from tests.helpers_objects import (  # noqa: F401,E402
    app, _headless_qt, make_excellon, make_gerber, polygon_union, reparse_gerber,
)
from test_panelize_plugin import Value, run_plugin


# ---------------------------------------------------------------------------------------------------------------
# messages printed the object (None) instead of its name
# ---------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------
# the source Excellon got empty 'drills' / 'slots' keys
# ---------------------------------------------------------------------------------------------------------------

def test_source_excellon_without_slots_or_drills_keys_is_not_changed(app):
    src = make_excellon(app, name='e')
    for tool in src.tools.values():
        del tool['slots']
    del src.tools[2]['drills']
    keys_before = {tid: sorted(tool) for tid, tool in src.tools.items()}
    created, _ = run_plugin(app, src)
    assert {tid: sorted(tool) for tid, tool in src.tools.items()} == keys_before
    # the panel still has both keys everywhere
    assert all('drills' in t and 'slots' in t for t in created['e_panelized'].tools.values())


# ---------------------------------------------------------------------------------------------------------------
# 'Done' was shown before the worker ran
# ---------------------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------
# the dead tool-table block of the Gerber -> Geometry panel
# ---------------------------------------------------------------------------------------------------------------

def test_gerber_to_geometry_panel_result_is_the_translated_copper_only(app):
    # The panel gets the tool table of the Geometry (like convert_any2geo); every tool holds the translated copper.
    src = make_gerber(app, name='g')
    created, _ = run_plugin(app, src, panel_type='geometry', rows=2, cols=2)
    pan = created['g_panelized']
    src_area = polygon_union(src.solid_geometry).area
    assert pan.multigeo is True
    assert pan.tools
    for tool in pan.tools.values():
        assert polygon_union(tool['solid_geometry']).area == pytest.approx(4 * src_area)
    assert polygon_union(pan.solid_geometry).area == pytest.approx(4 * src_area)
    assert all(not isinstance(g, (list, tuple)) for g in pan.solid_geometry)
    assert all(not isinstance(g, (list, tuple)) for tool in pan.tools.values() for g in tool['solid_geometry'])


def test_gerber_to_geometry_panel_has_tools_options_and_source(app):
    src = make_gerber(app, name='g')
    created, _ = run_plugin(app, src, panel_type='geometry', rows=1, cols=2)
    pan = created['g_panelized']
    assert pan.tools
    for tool in pan.tools.values():
        assert 'tooldia' in tool and isinstance(tool['data'], dict) and tool['data']
    first = pan.tools[min(pan.tools)]['tooldia']
    assert pan.obj_options['tools_mill_tooldia'] == first
    # a Geometry keeps its source as DXF text
    assert pan.source_file and len(ezdxf.read(StringIO(pan.source_file)).modelspace()) > 0


# ---------------------------------------------------------------------------------------------------------------
# Geometry -> Gerber panel keeps its tools and a source file
# ---------------------------------------------------------------------------------------------------------------

def make_poly_geometry(app, multigeo):
    """A Geometry made of polygons only: 3 elements."""
    src = GeometryObject('src', app)
    src.multigeo = multigeo
    src.units = 'MM'
    polys = [box(0, 0, 4, 4), box(6, 0, 8, 2), box(10, 0, 12, 2)]
    src.solid_geometry = list(polys)
    if multigeo:
        src.tools = {1: {'tooldia': 1.0, 'data': {}, 'solid_geometry': polys[:2]},
                     2: {'tooldia': 2.0, 'data': {}, 'solid_geometry': polys[2:]}}
    else:
        src.tools = {1: {'tooldia': 1.0, 'data': {}, 'solid_geometry': []}}
    return src


@pytest.mark.parametrize('multigeo', [False, True], ids=['single-geo', 'multigeo'])
def test_geometry_to_gerber_panel_keeps_the_records_and_has_a_source(app, multigeo):
    src = make_poly_geometry(app, multigeo)
    created, _ = run_plugin(app, src, panel_type='gerber', rows=2, cols=2)
    pan = created['src_panelized']
    assert pan.tools[0]['type'] == 'REG'
    records = pan.tools[0]['geometry']
    assert len(records) == 4 * 3
    assert polygon_union([r['solid'] for r in records]).symmetric_difference(
        polygon_union(pan.solid_geometry)).area < 1e-6
    assert pan.multigeo is True and pan.multitool is False and pan.follow is False
    assert pan.export_as_regions is False
    assert isinstance(pan.source_file, str) and pan.source_file.strip()


def test_geometry_to_gerber_panel_with_a_line_exports_as_regions(app, tmp_path):
    src = make_poly_geometry(app, False)
    src.solid_geometry = [box(0, 0, 4, 4), LineString([(6, 0), (9, 3)])]
    created, _ = run_plugin(app, src, panel_type='gerber', rows=1, cols=2)
    pan = created['src_panelized']
    assert pan.export_as_regions is True
    assert isinstance(pan.source_file, str) and pan.source_file.strip()
    again = reparse_gerber(app, pan.source_file, tmp_path)
    assert polygon_union(again.solid_geometry).area == pytest.approx(2 * 16)


def test_constraint_smaller_than_one_board_does_not_schedule_a_panel(app):
    src = make_gerber(app, name='g')
    before = []
    created, informs = run_plugin(app, src, constrain=(0.001, 0.001), before=before)
    assert not created
    app.collection.promise.assert_not_called()
    assert any('[ERROR_NOTCL]' in text for text in before)
    assert not any('successfully' in text for text in informs)


def test_worker_exception_clears_promise_and_reports_error(app):
    src = make_gerber(app, name='g')
    app.collection.promises = set()
    app.collection.promise.side_effect = app.collection.promises.add
    created, informs = run_plugin(app, src, fail_job=True)
    assert not created
    assert not app.collection.promises
    assert any('[ERROR_NOTCL]' in text for text in informs)

