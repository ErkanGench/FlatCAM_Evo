"""Panel conversion data, using the shared panelization algorithms."""

from copy import deepcopy

from shapely import Polygon

from appParsers import panelize_core


def geometry_from_gerber(tools, solid_geometry, offsets, abort=None, progress=None):
    tools = deepcopy(tools)
    for tid in tools:
        tools[tid]['solid_geometry'] = deepcopy(solid_geometry)
    return panelize_core.panelize_geometry(tools, solid_geometry, True, offsets, abort=abort, progress=progress)


def gerber_from_geometry(tools, solid_geometry, multigeo, offsets, abort=None, progress=None):
    src_tools, src_solid = panelize_core.gerber_tools_from_geometry(tools, solid_geometry, multigeo)
    result_tools, result_solid = panelize_core.panelize_gerber(
        src_tools, src_solid, offsets, abort=abort, progress=progress)
    as_regions = any(not isinstance(rec.get('solid'), Polygon) for rec in result_tools[0]['geometry'])
    return result_tools, result_solid, as_regions
