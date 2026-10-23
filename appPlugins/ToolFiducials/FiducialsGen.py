"""Copper and preview geometry for fiducials."""

import math
from copy import deepcopy

from shapely import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from camlib import flatten_shapely_geometry


def make_square_poly(center_pt, side_size):
    half_s = side_size / 2
    x_center, y_center = center_pt
    pt1 = (x_center - half_s, y_center - half_s)
    pt2 = (x_center + half_s, y_center - half_s)
    pt3 = (x_center + half_s, y_center + half_s)
    pt4 = (x_center - half_s, y_center + half_s)
    return Polygon([pt1, pt2, pt3, pt4, pt1])


def flatten_geometry(geometry):
    result = []
    try:
        for geo in geometry:
            if geo is not None:
                result.extend(flatten_geometry(geo))
    except TypeError:
        result.append(geometry)
    return result


def fiducial_shapes(pt, fid_size, fid_type, line_thickness, steps):
    radius = fid_size / 2.0
    if fid_type == 0:
        return [Point(pt).buffer(radius, steps)]
    x, y = pt[0], pt[1]
    if fid_type == 1:
        return [LineString([(x - radius + line_thickness / 2.0, y),
                            (x + radius - line_thickness / 2.0, y)]),
                LineString([(x, y - radius + line_thickness / 2.0),
                            (x, y + radius - line_thickness / 2.0)])]
    return [make_square_poly((x - fid_size / 4, y + fid_size / 4), fid_size / 2),
            make_square_poly((x + fid_size / 4, y - fid_size / 4), fid_size / 2)]


def fiducial_geometry(points_list, tools, solid_geometry, fid_size, fid_type, line_thickness, steps, decimals):
    new_apertures = deepcopy(tools)
    geo_list = []
    for pt in points_list:
        shapes = fiducial_shapes(pt, fid_size, fid_type, line_thickness, steps)
        if fid_type == 1:
            geo_list.append(shapes)
        else:
            geo_list += shapes

    ap_type = 'C' if fid_type in (0, 1) else 'R'
    ap_size = fid_size if fid_type == 0 else (
        line_thickness if fid_type == 1 else math.sqrt(fid_size**2 + fid_size**2))
    aperture_found = None
    for ap_id, ap_val in tools.items():
        if ap_val['type'] != ap_type:
            continue
        same_size = ap_val['size'] == ap_size if fid_type in (0, 1) else (
            round(ap_val['size'], ndigits=decimals) == round(ap_size, ndigits=decimals))
        if same_size:
            aperture_found = ap_id
            break
    if not aperture_found:
        aperture_found = int(max(tools)) + 1 if tools else 10
        new_apertures[aperture_found] = {'type': ap_type, 'size': ap_size, 'geometry': []}
        if fid_type not in (0, 1):
            new_apertures[aperture_found].update(width=fid_size, height=fid_size)

    solids = [line.buffer(line_thickness / 2.0, steps) for pair in geo_list for line in pair] \
        if fid_type == 1 else geo_list
    for geo in solids:
        new_apertures[aperture_found]['geometry'].append(deepcopy({'follow': geo.centroid, 'solid': geo}))
    flat_geo = flatten_shapely_geometry(solid_geometry)
    s_list = list(flat_geo) if flat_geo else []
    if fid_type == 1:
        s_list += flatten_shapely_geometry(MultiPolygon(solids).buffer(0))
    else:
        s_list += solids
    return new_apertures, unary_union(s_list), geo_list
