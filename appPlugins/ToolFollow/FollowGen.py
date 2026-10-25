"""Core of the Follow plugin: turns the follow paths of a Gerber into milling paths. Qt free, never mutates its inputs.

Data facts this module relies on (checked in appParsers/ParseGerber.py):
 - Gerber.follow_geometry is a list of LineStrings, but a Gerber made by the DXF import holds the solid geometry
   (Polygon / MultiPolygon) there, so every input goes through paths_of().
 - Gerber.tools = {apid: {'type', 'size', 'geometry': [{'solid'|'clear', 'follow'}...]}}. A region lives in aperture 0
   (size 0.0) and a flash has a Point as 'follow'.
"""

from copy import deepcopy

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry
from shapely import LineString, STRtree, line_merge
from shapely.ops import unary_union

_POINT, _LINESTRING, _LINEARRING, _POLYGON = 0, 1, 2, 3


def _obj_array(geoms):
    arr = np.empty(len(geoms), dtype=object)
    for i, g in enumerate(geoms):
        arr[i] = g
    return arr


def _collect(geometry, out):
    if geometry is None:
        return
    if isinstance(geometry, (list, tuple, set)):
        for g in geometry:
            _collect(g, out)
    elif isinstance(geometry, np.ndarray):
        for g in geometry.ravel().tolist():
            _collect(g, out)
    elif isinstance(geometry, BaseGeometry):
        out.append(geometry)


def paths_of(geometry):
    """The non-empty lines of a geometry, a nested list of geometries or None. Polygons give their rings."""
    found = []
    _collect(geometry, found)
    if not found:
        return []
    arr = _obj_array(found)
    while True:
        arr = arr[~shapely.is_empty(arr)]
        if arr.size == 0:
            return []
        ids = shapely.get_type_id(arr)
        multi = ids > _POLYGON
        if not multi.any():
            break
        arr = np.concatenate([arr[~multi], shapely.get_parts(arr[multi])])
    ids = shapely.get_type_id(arr)
    out = [LineString(g.coords) if t == _LINEARRING else g
           for g, t in zip(arr[ids <= _LINEARRING].tolist(), ids[ids <= _LINEARRING].tolist()) if t != _POINT]
    polys = arr[ids == _POLYGON]
    if polys.size:
        out.extend(LineString(r.coords) for r in shapely.get_rings(polys).tolist() if not r.is_empty)
    return out


def select_paths(paths, selection):
    """The part of the paths inside the selection polygons: inside kept, crossing clipped, outside dropped."""
    if not selection:
        return list(paths)
    paths = list(paths)
    if not paths:
        return []
    area = unary_union([p for p in selection if p is not None and not p.is_empty])
    if area.is_empty:
        return []
    shapely.prepare(area)
    arr = _obj_array(paths)
    hits = np.unique(STRtree(arr).query(area, predicate='intersects'))
    if hits.size == 0:
        return []
    cand = arr[hits]
    inside = shapely.contains(area, cand)
    out = cand[inside].tolist()
    crossing = cand[~inside]
    if crossing.size:
        out.extend(paths_of(shapely.intersection(crossing, area).tolist()))
    return out


def clean_paths(paths, union, simplify, tolerance, merge=True):
    """Union (nodes the lines) -> merge (joins them again) -> simplify. Returns new objects."""
    result = [p for p in paths if p is not None and not p.is_empty]
    if not result:
        return []
    if union:
        result = paths_of(unary_union(result))
    if merge and result:
        result = paths_of(line_merge(shapely.multilinestrings(result)))
    if simplify and tolerance > 0.0 and result:
        simplified = shapely.simplify(_obj_array(result), tolerance)
        result = [g for g in simplified.tolist() if not g.is_empty]
    return result


def aperture_paths(gerber_tools, apertures=None):
    """{aperture id: paths} from the 'follow' of every record of the aperture. apertures=None means all."""
    wanted = None if apertures is None else {str(a) for a in apertures}
    out = {}
    for ap, tool in gerber_tools.items():
        if wanted is not None and str(ap) not in wanted:
            continue
        found = []
        for record in tool.get('geometry', []):
            found.extend(paths_of(record.get('follow')))
        if found:
            out[ap] = found
    return out


def tool_dias(value):
    """The diameters > 0 of a float, int, '0.1, 0.2' string or a list / tuple of them."""
    if isinstance(value, str):
        items = [s for s in value.replace(';', ',').split(',') if s.strip()]
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        items = [value]
    dias = []
    for item in items:
        if item is None or (isinstance(item, str) and not item.strip()):
            continue
        dia = float(item)
        if dia > 0.0:
            dias.append(dia)
    if not dias:
        raise ValueError("No tool diameter greater than 0.")
    return dias


def geometry_data(options, name):
    """The tool data of a Follow geometry: 'geometry_*' keys without the prefix, 'tools_mill_*' keys and the name."""
    data = {}
    for key, val in options.items():
        if key.startswith('geometry_'):
            data[key[len('geometry_'):]] = val
        elif key.startswith('tools_mill_'):
            data[key] = val
    data['name'] = name
    return data


def _process(paths, params):
    selection = params.get('selection')
    if selection:
        paths = select_paths(paths, selection)
    return clean_paths(paths, params.get('union', False), params.get('simplify', False),
                       params.get('tolerance', 0.0), params.get('merge', True))


def _size_of(tool):
    try:
        return float(tool.get('size', 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


class FollowSource:
    """What a job reads of a Gerber: its follow paths and the size and follow paths of its apertures."""

    def __init__(self, follow_geometry, tools):
        self.follow_geometry = follow_geometry
        self.tools = tools


def snapshot(source):
    """A copy of what follow_groups() reads, taken in the GUI thread so a job never reads a live object."""
    tools = {}
    for ap, tool in (getattr(source, 'tools', None) or {}).items():
        tools[ap] = {'size': tool.get('size', 0.0), 'type': tool.get('type', ''),
                     'geometry': [{'follow': record.get('follow')} for record in tool.get('geometry', [])]}
    follow = getattr(source, 'follow_geometry', None)
    return FollowSource(list(follow) if isinstance(follow, (list, tuple)) else follow, tools)


def follow_groups(source, params, check_abort=None):
    """[(tooldia, paths)] for the source. See the aperture filter and dia_mode keys of params.
    A source without aperture follow data (DXF import) is followed from follow_geometry in the aperture mode too."""
    tooldia = float(params.get('tooldia', 0.0))
    apertures = params.get('apertures')
    aperture_mode = params.get('dia_mode', 'default') == 'aperture'
    raw = {}
    per_ap = {}
    if apertures is not None or aperture_mode:
        per_ap = aperture_paths(source.tools, apertures)
    if apertures is None and not per_ap:
        raw[tooldia] = paths_of(source.follow_geometry)
    else:
        for ap, found in per_ap.items():
            dia = _size_of(source.tools[ap]) if aperture_mode else 0.0
            dia = round(dia, 6) if dia > 0.0 else tooldia
            raw.setdefault(dia, []).extend(found)
    groups = []
    for dia in sorted(raw):
        if check_abort is not None:
            check_abort()
        cleaned = _process(raw[dia], params)
        if cleaned:
            groups.append((dia, cleaned))
    return groups


def follow_tools(groups, data, decimals):
    """The tools dict of a Follow Geometry object, one tool per group."""
    tools = {}
    for n, (dia, lines) in enumerate(groups, start=1):
        tool_data = deepcopy(data)
        tool_data['tools_mill_tooldia'] = dia
        tools[n] = {
            'tooldia': round(dia, decimals),
            'offset': 'Path',
            'offset_value': 0.0,
            'type': 'Rough',
            'tool_type': 'C1',
            'data': tool_data,
            'solid_geometry': lines,
        }
    return tools
