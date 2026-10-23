"""Geometry calculations for the subtraction plugin. No application or Qt state."""

from copy import deepcopy

from shapely import LineString, Polygon, MultiPolygon, MultiLineString
from shapely.ops import unary_union


def aperture_intersection(apid, target_geo, sub_geometry):
    """Return the aperture id, surviving records and modified records."""
    unafected_geo = []
    affected_geo = []

    for target_geo_obj in target_geo:
        solid_is_modified = False
        destination_geo_obj = {}
        if "solid" in target_geo_obj:
            diff = []
            target_solid = target_geo_obj["solid"]
            for sub_solid_geo in sub_geometry["solid"]:
                if target_solid.intersects(sub_solid_geo) or target_solid.contains(sub_solid_geo):
                    target_solid = target_solid.difference(sub_solid_geo)
            if not target_solid.is_empty:
                diff.append(target_solid)
                solid_is_modified = True
                target_solid = unary_union(diff)
            destination_geo_obj["solid"] = deepcopy(target_solid)

        clear_is_modified = False
        if "clear" in target_geo_obj:
            clear_diff = []
            target_clear = target_geo_obj["clear"]
            for sub_clear_geo in sub_geometry["clear"]:
                if target_clear.intersects(sub_clear_geo) or target_clear.contains(sub_clear_geo):
                    target_clear = target_clear.difference(sub_clear_geo)
            if not target_clear.is_empty:
                clear_diff.append(target_clear)
                clear_is_modified = True
                target_clear = unary_union(clear_diff)
            destination_geo_obj["clear"] = deepcopy(target_clear)

        if solid_is_modified or clear_is_modified:
            affected_geo.append(deepcopy(destination_geo_obj))
        else:
            unafected_geo.append(deepcopy(destination_geo_obj))

    return apid, unafected_geo, affected_geo


def poly2rings(poly):
    return [poly.exterior] + [interior for interior in poly.interiors]


def gerber_geometry(tools, output):
    """Populate the destination apertures and return their solid and follow geometry."""
    if 0 not in tools:
        tools[0] = {}
        tools[0]['type'] = 'REG'
        tools[0]['size'] = 0.0
        tools[0]['geometry'] = []

    for apid in list(tools.keys()):
        # output is a tuple in the format (apid, surviving_geo, modified_geo)
        for t in output:
            new_apid = t[0]
            if apid == new_apid:
                surving_geo = t[1]
                modified_geo = t[2]
                if surving_geo:
                    tools[apid]['geometry'] += deepcopy(surving_geo)
                if modified_geo:
                    tools[0]['geometry'] += modified_geo

        if not tools[apid]['geometry']:
            tools.pop(apid, None)

    if 0 in tools and not tools[0]['geometry']:
        tools.pop(0, None)

    poly_buff = []
    follow_buff = []
    for ap in tools:
        for elem in tools[ap]['geometry']:
            if 'solid' in elem:
                solid_geo = elem['solid']
                poly_buff.append(solid_geo)
            if 'follow' in elem:
                follow_buff.append(elem['follow'])

    work_poly_buff = MultiPolygon(poly_buff)
    try:
        poly_buff = work_poly_buff.buffer(0.0000001)
    except ValueError:
        pass
    try:
        poly_buff = poly_buff.buffer(-0.0000001)
    except ValueError:
        pass
    return deepcopy(poly_buff), deepcopy(follow_buff)


def subtract_geometry(geo, sub_union, close_paths):
    new_geometry = []
    # resulting paths are closed resulting into Polygons
    if close_paths:
        new_geo = (unary_union(geo)).difference(sub_union)
        if new_geo:
            if not new_geo.is_empty:
                new_geometry.append(new_geo)
    # resulting paths are unclosed resulting in a multitude of rings
    else:
        try:
            for geo_elem in geo:
                if isinstance(geo_elem, Polygon):
                    for ring in poly2rings(geo_elem):
                        new_geo = ring.difference(sub_union)
                        if new_geo and not new_geo.is_empty:
                            new_geometry.append(new_geo)
                elif isinstance(geo_elem, MultiPolygon):
                    for poly in geo_elem.geoms:
                        for ring in poly2rings(poly):
                            new_geo = ring.difference(sub_union)
                            if new_geo and not new_geo.is_empty:
                                new_geometry.append(new_geo)
                elif isinstance(geo_elem, LineString):
                    new_geo = geo_elem.difference(sub_union)
                    if new_geo:
                        if not new_geo.is_empty:
                            new_geometry.append(new_geo)
                elif isinstance(geo_elem, MultiLineString):
                    for line_elem in geo_elem.geoms:
                        new_geo = line_elem.difference(sub_union)
                        if new_geo and not new_geo.is_empty:
                            new_geometry.append(new_geo)
        except TypeError:
            if isinstance(geo, Polygon):
                for ring in poly2rings(geo):
                    new_geo = ring.difference(sub_union)
                    if new_geo:
                        if not new_geo.is_empty:
                            new_geometry.append(new_geo)
            elif isinstance(geo, LineString):
                new_geo = geo.difference(sub_union)
                if new_geo and not new_geo.is_empty:
                    new_geometry.append(new_geo)
            elif isinstance(geo, MultiLineString):
                for line_elem in geo.geoms:
                    new_geo = line_elem.difference(sub_union)
                    if new_geo and not new_geo.is_empty:
                        new_geometry.append(new_geo)
    return new_geometry
