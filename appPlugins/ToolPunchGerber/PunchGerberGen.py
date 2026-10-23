from copy import deepcopy

from shapely import Point, MultiPolygon
from shapely.ops import unary_union


def punch_geometry(solid_geometry, tools, selected_apertures, method, value, decimals, enabled,
                   manual_pads=None, drill_geometry=None, drill_tools=None):
    """Punch pads and return independent solid geometry and exportable clear aperture records."""
    source = MultiPolygon(solid_geometry) if isinstance(solid_geometry, list) else solid_geometry
    apertures = deepcopy(tools)
    new_apid = max(int(apid) for apid in apertures)
    holes = {}

    def add_clear(size, point):
        if size not in holes:
            holes[size] = {'type': 'C', 'size': size, 'geometry': []}
        holes[size]['geometry'].append(deepcopy({'clear': point}))

    if method == 'exc':
        cutter = MultiPolygon(drill_geometry)
        selected_pads = []
        if manual_pads is not None:
            cutters = []
            for pad in manual_pads:
                record = tools[pad['apid']]['geometry'][pad['idx']]
                selected_pads.append(record['solid'])
                for geo in cutter.geoms:
                    if geo.within(record['solid']) and isinstance(record['follow'], Point):
                        cutters.append(geo)
            cutter = MultiPolygon(cutters)
        target, unaffected = [], []
        for apid, aperture in tools.items():
            for record in aperture.get('geometry', []):
                if 'solid' in record:
                    (target if apid in selected_apertures else unaffected).append(record['solid'])
        punched = MultiPolygon(target).buffer(0).difference(cutter)
        punched = unary_union(list(punched.geoms) + unaffected if hasattr(punched, 'geoms') else
                              [punched] + unaffected)
        for apid, aperture in apertures.items():
            if manual_pads is None and apid not in selected_apertures:
                continue
            for record in aperture['geometry']:
                if 'solid' in record and isinstance(record['follow'], Point):
                    for drill in drill_tools.values():
                        for point in drill.get('drills', []):
                            if manual_pads is None:
                                if point.within(record['solid']):
                                    add_clear(drill['tooldia'], point)
                            else:
                                for pad in selected_pads:
                                    if point.within(record['solid']) and point.within(pad):
                                        add_clear(drill['tooldia'], point)
    else:
        punched = source
        fixed_holes = []
        for apid, aperture in tools.items():
            ap_type = aperture['type']
            if manual_pads is None:
                if apid not in selected_apertures:
                    continue
                records = [record for record in aperture['geometry']
                           if 'follow' in record and isinstance(record['follow'], Point)]
            else:
                records = [aperture['geometry'][pad['idx']] for pad in manual_pads if pad['apid'] == apid]
            if not records:
                continue

            if ap_type == 'C':
                category = 0
            elif ap_type == 'O':
                category = 1
            elif ap_type == 'R':
                category = 2 if round(float(aperture['width']), decimals) == \
                    round(float(aperture['height']), decimals) else 3
            else:
                category = 4
            if method != 'fixed' and ap_type in ('C', 'O') and not enabled[category] and not (
                    manual_pads is not None and method == 'ring' and ap_type == 'C'):
                category = 4
            # Manual fixed-size selection was already filtered on the canvas. Manual ring circular pads
            # likewise keep the legacy selection semantics even if the checkbox subsequently changes.
            if not (manual_pads is not None and (method == 'fixed' or (method == 'ring' and ap_type == 'C'))):
                if not enabled[category]:
                    continue

            if method == 'fixed':
                dia = value
                if manual_pads is not None:
                    too_large = 'size' in aperture and dia >= float(aperture['size'])
                elif ap_type == 'R':
                    too_large = dia >= float(aperture['width']) or dia >= float(aperture['height'])
                else:
                    too_large = dia >= float(aperture['size'])
                if too_large:
                    raise ValueError('size')
            else:
                if category in (1, 2, 3):
                    size = float(aperture['height']) if category == 2 else \
                        min(float(aperture['width']), float(aperture['height']))
                else:
                    try:
                        size = float(aperture['size'])
                    except KeyError:
                        if ap_type != 'AM':
                            raise
                        x0, y0, x1, y1 = aperture['geometry'][0]['solid'].bounds
                        size = min(x1 - x0, y1 - y0)
                dia = size - 2 * value[category] if method == 'ring' else size * value
            cutters = MultiPolygon([record['follow'].buffer(dia / 2) for record in records])
            if method == 'fixed':
                fixed_holes.extend(cutters.geoms)
            elif not cutters.is_empty:
                punched = punched.difference(cutters)
                for record in aperture['geometry']:
                    if 'solid' in record and isinstance(record['follow'], Point):
                        for geo in cutters.geoms:
                            if geo.within(record['solid']):
                                add_clear(dia, geo.centroid)
        if method == 'fixed':
            cutter = MultiPolygon(fixed_holes)
            punched = source.difference(cutter)
            if punched == source:
                raise ValueError('unchanged')
            for aperture in apertures.values():
                for record in aperture['geometry']:
                    if 'solid' in record and isinstance(record['follow'], Point):
                        for geo in cutter.geoms:
                            if geo.within(record['solid']):
                                add_clear(value, geo.centroid)
    for aperture in holes.values():
        new_apid += 1
        apertures[new_apid] = deepcopy(aperture)
    return punched, apertures
