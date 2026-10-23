"""Explicit-input drill, soldermask and cutout extraction."""

from copy import deepcopy

from shapely import MultiPolygon, Point, Polygon, box


def fixed_drills(gerber_tools, sel_tools, drill_dia, decimals, circular, oblong, square, rectangular, other):
    tools = {1: {'tooldia': drill_dia, 'drills': [], 'slots': []}}
    for apid, aperture in gerber_tools.items():
        if apid not in sel_tools:
            continue
        ap_type = aperture['type']
        if ap_type == 'C' and circular is False:
            continue
        elif ap_type == 'O' and oblong is False:
            continue
        elif ap_type == 'R':
            if round(float(aperture['width']), decimals) == round(float(aperture['height']), decimals):
                if square is False:
                    continue
            elif rectangular is False:
                continue
        elif ap_type not in ['C', 'R', 'O'] and other is False:
            continue
        for geo_el in aperture['geometry']:
            if 'follow' in geo_el and isinstance(geo_el['follow'], Point):
                tools[1]['drills'].append(geo_el['follow'])
                tools[1].setdefault('solid_geometry', []).append(geo_el['follow'])
    return tools if tools[1].get('solid_geometry') else None


def sized_drills(gerber_tools, sel_tools, mode, decimals, dec_format, allowed, values):
    circular, oblong, square, rectangular, other = allowed
    tools = {}
    for apid, aperture in gerber_tools.items():
        if apid not in sel_tools:
            continue
        ap_type = aperture['type']
        size = None
        ring_index = 4
        if ap_type == 'C' and circular:
            size = float(aperture['size'])
            ring_index = 0
        elif ap_type == 'O' and oblong:
            size = min(float(aperture['width']), float(aperture['height']))
            ring_index = 1
        elif ap_type == 'R':
            width, height = float(aperture['width']), float(aperture['height'])
            if abs(dec_format(width, decimals) - dec_format(height, decimals)) < 10 ** -decimals:
                if square:
                    size = height
                    ring_index = 2
            elif rectangular:
                size = min(width, height)
                ring_index = 3
        elif other:
            try:
                size = float(aperture['size'])
            except KeyError:
                if ap_type == 'AM':
                    x0, y0, x1, y1 = aperture['geometry'][0]['solid'].bounds
                    size = min(x1 - x0, y1 - y0)
        if size is None:
            continue
        dia = size - 2 * values[ring_index] if mode == 'ring' else size * values
        tool_in_drills = False
        for tool, tool_val in tools.items():
            if abs(dec_format(tool_val['tooldia']) - dec_format(dia, decimals)) < 10 ** -decimals:
                tool_in_drills = tool
        if tool_in_drills is False:
            tool_in_drills = max([int(t) for t in tools]) + 1 if tools else 1
        for geo_el in aperture['geometry']:
            if 'follow' in geo_el and isinstance(geo_el['follow'], Point):
                if tool_in_drills not in tools:
                    tools[tool_in_drills] = {'tooldia': dia, 'drills': [], 'slots': []}
                tools[tool_in_drills]['drills'].append(geo_el['follow'])
                tools[tool_in_drills].setdefault('solid_geometry', []).append(geo_el['follow'])
    return tools or None


def soldermask(gerber_tools, selected, allowed_apertures, square, rect, clearance, decimals):
    apertures = {apid: deepcopy(gerber_tools[apid]) for apid in selected}
    solids, follows = [], []
    for apid, aperture in gerber_tools.items():
        if apid not in selected:
            continue
        ap_type = aperture['type']
        if ap_type not in allowed_apertures:
            apertures.pop(apid, None)
            continue
        if ap_type == 'R':
            if round(float(aperture['width']), decimals) == round(float(aperture['height']), decimals):
                if square is False:
                    apertures.pop(apid, None)
                    continue
            elif rect is False:
                apertures.pop(apid, None)
                continue
        if 'geometry' in aperture:
            records = []
            for geo_el in aperture['geometry']:
                if 'follow' in geo_el and isinstance(geo_el['follow'], Point) and (
                        'clear' not in geo_el or not geo_el['clear']):
                    follows.append(geo_el['follow'])
                    if 'solid' in geo_el:
                        solid = geo_el['solid'].buffer(clearance)
                        records.append(deepcopy({'solid': solid, 'follow': geo_el['follow']}))
                        solids.append(solid)
            apertures[apid]['geometry'] = deepcopy(records)
    has_geometry = False
    for apid in list(apertures):
        if 'geometry' in apertures[apid]:
            if apertures[apid]['geometry']:
                has_geometry = True
            else:
                apertures.pop(apid, None)
    return (apertures, solids, follows) if has_geometry else None


def cutout(solid_geometry, margin, thickness):
    geometry = MultiPolygon(solid_geometry) if isinstance(solid_geometry, list) else solid_geometry
    if not isinstance(geometry, (MultiPolygon, Polygon)):
        return None
    follow = box(*geometry.bounds).buffer(margin).exterior
    solid = follow.buffer(thickness / 2.0)
    if not solid.is_valid or solid.is_empty:
        return None
    apertures = {10: {'type': 'C', 'size': thickness,
                      'geometry': [{'solid': deepcopy(solid), 'follow': deepcopy(follow)}]}}
    return apertures, solid, follow
