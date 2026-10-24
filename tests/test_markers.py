import pytest
from shapely import LineString

from appPlugins.ToolMarkers.MarkersGen import (
    create_marker_geometry, drill_locations, geometry_marker_data, gerber_marker_data)


def _manual(pt=(10.0, 20.0), thickness=0.2, length=1.0, mode=1):
    return create_marker_geometry({'manual': [pt]}, 'c', thickness, length, mode, 0, 0)


@pytest.mark.parametrize("existing", [False, True])
def test_gerber_buffer_uses_quarter_steps(existing):
    marker = [LineString([(0, 0), (1, 0)])]
    tools = {10: {'type': 'C', 'size': 0.2, 'geometry': []}} if existing else {}
    aps, _, _ = gerber_marker_data(tools, None, [], marker, 0.2, 16)
    ap = next(iter(v for v in aps.values() if v['geometry']))
    expected = marker[0].buffer(0.1, quad_segs=4).exterior.coords
    assert len(ap['geometry'][0]['solid'].exterior.coords) == len(expected)


def test_gerber_non_list_follow_geometry():
    marker = [LineString([(0, 0), (1, 0)])]
    _, _, follow = gerber_marker_data({}, None, LineString([(5, 5), (6, 5)]), marker, 0.2, 16)
    assert len(follow) == 2


def test_geometry_non_list_existing_gets_flat_list():
    old = LineString([(0, 0), (1, 1)])
    marker = _manual()
    tools = {1: {'tooldia': 0.2, 'data': {}, 'solid_geometry': old}}
    new_tools, _ = geometry_marker_data(tools, None, marker, 0.2, {})
    geos = new_tools[1]['solid_geometry']
    assert isinstance(geos, list) and len(geos) == 3
    assert all(isinstance(g, LineString) for g in geos)


def test_geometry_other_empty_tools_survive():
    tools = {1: {'tooldia': 0.5, 'data': {}, 'solid_geometry': []}}
    new_tools, _ = geometry_marker_data(tools, None, _manual(), 0.2, {})
    assert 1 in new_tools and len(new_tools) == 2


def test_manual_cross_centered_on_click():
    h, v = _manual((10.0, 20.0))
    assert h.intersection(v).coords[0] == (10.0, 20.0)
    drill = drill_locations((0, 0, 1, 1), (0, 0, 0, 0), {'manual': [(10.0, 20.0)]}, 0.2, 0, 0)
    assert (drill[0].x, drill[0].y) == (10.0, 20.0)


@pytest.mark.parametrize("thickness,length", [(0, 1.0), (0.2, 0), (-0.1, 1.0)])
def test_non_positive_size_fails(thickness, length):
    assert _manual(thickness=thickness, length=length) == 'fail'
