"""Explicit-data isolation geometry algorithms. No application or widget state lives here."""

from typing import Iterable
import math

import numpy as np
import shapely
from shapely import LineString, MultiLineString, Polygon, MultiPolygon, Point, LinearRing
from shapely.ops import unary_union

from camlib import flatten_shapely_geometry, milling_orient, polygon_gap_pairs, clip_paths_to_area, \
    pass_covers_area, isolation_leftover_paths, circle_quad_segs


def pass_offset(tooldia, nr_pass, overlap, negative_dia=None, denominator=2.0000001):
    """Overlap is a fraction; the rest strategy retains its original 2.0 denominator."""
    offset = tooldia * ((2 * nr_pass + 1) / denominator) - (nr_pass * overlap * tooldia)
    return -offset if negative_dia else offset


def quad_segs_of(circle_steps):
    """Shapely quad_segs of a circle step count (the app counts the steps of the whole circle)."""
    return circle_quad_segs(circle_steps)


def v_effective_diameter(data):
    """Effective diameter: tip + 2 * |cut_z| * tan(angle / 2); None for an angle outside (0, 180), a negative tip
    or a diameter that is not positive."""
    try:
        tip = float(data['tools_mill_vtipdia'])
        angle = float(data['tools_mill_vtipangle'])
        cut_z = abs(float(data['tools_mill_cutz']))
        if not 0 < angle < 180 or tip < 0:
            return None
        dia = tip + (2 * cut_z * math.tan(math.radians(angle / 2)))
    except (KeyError, TypeError, ValueError):
        return None
    return dia if math.isfinite(dia) and dia > 0 else None


def aperture_geometry(aperture_storage, abort=None):
    total_geo = []
    for ap in list(aperture_storage.keys()):
        if 'geometry' in aperture_storage[ap]:
            for geo_el in aperture_storage[ap]['geometry']:
                if abort is not None:
                    abort()
                if 'solid' in geo_el and geo_el['solid'] is not None and geo_el['solid'].is_valid:
                    total_geo.append(geo_el['solid'])
    # Measure the same geometry as Optimal; a positive buffer changes the rounded gap.
    # (unary_union: a solid can be a MultiPolygon)
    return flatten_shapely_geometry(unary_union(total_geo).buffer(0))


def safe_tooldia(geometry, decimals):
    """The largest tool that fits between the polygons, truncated for the rounding of the distances.

    Without a gap to measure (fewer than 2 polygons) no tool is safe: the result is not positive, like for touching
    polygons, and the callers report 'Could not find a safe tool diameter'.
    """
    gaps = polygon_gap_pairs(geometry, decimals)
    if not gaps:
        return -10 ** -decimals
    return min(gaps) - 10 ** -decimals


def poly2rings(poly):
    return [poly.exterior] + [interior for interior in poly.interiors]


def combined_passes(pass_envelopes, offsets, tooldia, circle_steps, invert, clear_leftovers=False, boundary=None):
    """Collect lazy pass geometry, stopping at the boundary without requesting unused passes."""
    solid_geo = []
    envelopes = []
    leftover_geo = []
    prev_geo = None
    passes_made = 0 if boundary is not None else len(offsets)
    for nr_pass, iso_geo in enumerate(pass_envelopes):
        if iso_geo == 'fail':
            continue
        if clear_leftovers:
            if prev_geo is not None:
                leftover_geo += isolation_leftover_paths(prev_geo, iso_geo, tooldia / 2.0,
                                                         quad_segs_of(circle_steps), invert=invert)
            prev_geo = iso_geo

        if boundary is not None:
            clipped = clip_paths_to_area(iso_geo, boundary)
            if not clipped:
                # Disconnected areas can still be reached by a later pass.
                if isinstance(boundary, MultiPolygon) and not (
                        offsets[nr_pass] > 0 and pass_covers_area(iso_geo, boundary)):
                    continue
                break
            passes_made = nr_pass + 1
            envelopes.extend(flatten_shapely_geometry(iso_geo))
            solid_geo.extend(clipped)
            continue
        solid_geo.extend(flatten_shapely_geometry(iso_geo))
    return solid_geo, envelopes, leftover_geo, passes_made


def pad_passes(pads, envelope_geo, tooldia, first_pass, passes, overlap, circle_steps, negative_dia=None):
    solid_geo_union = unary_union(envelope_geo)
    pad_geo = []
    pad_array = np.empty(len(pads), dtype=object)
    pad_array[:] = list(pads)
    quad_segs = quad_segs_of(circle_steps)
    for nr_pass in range(first_pass, passes + first_pass):
        iso_offset = pass_offset(tooldia, nr_pass, overlap, negative_dia)
        pad_pass_geo = shapely.buffer(pad_array, iso_offset, quad_segs=quad_segs)
        pad_geo.append(unary_union(pad_pass_geo).difference(solid_geo_union))
    return pad_geo


def poly2ext(poly):
    return [poly.exterior]


def poly2ints(poly):
    return [interior for interior in poly.interiors]


def _paths_of(geo):
    """The rings of the polygons and the lines of a geometry, in order."""
    paths = []
    for geo_elem in flatten_shapely_geometry(geo):
        if isinstance(geo_elem, Polygon):
            paths += poly2rings(geo_elem)
        elif isinstance(geo_elem, LineString):
            paths.append(geo_elem)
    path_array = np.empty(len(paths), dtype=object)
    path_array[:] = paths
    return path_array


def _paths_touching(path_array, mask):
    """Boolean flags of the paths that intersect the mask (an index query with the mask as the prepared side)."""
    touching = np.zeros(len(path_array), dtype=bool)
    if len(path_array) and not mask.is_empty:
        touching[shapely.STRtree(path_array).query(mask, predicate='intersects')] = True
    return touching


def area_subtraction(geo, subtraction_geo):
    paths = _paths_of(geo)
    sub_union = unary_union(subtraction_geo)
    touching = _paths_touching(paths, sub_union)
    # a path that does not touch the mask is kept as it is
    result = paths.copy()
    result[touching] = shapely.difference(paths[touching], sub_union)
    return [new_geo for new_geo in result if not new_geo.is_empty]


def area_intersection(geo, intersection_geo):
    paths = _paths_of(geo)
    intersect_union = unary_union(intersection_geo)
    touching = _paths_touching(paths, intersect_union)
    # a path that does not touch the mask has no common part with it
    return [new_geo for new_geo in shapely.intersection(paths[touching], intersect_union) if not new_geo.is_empty]


def orient_envelope(geom_shp, invert, debug, error):
    if isinstance(geom_shp, str):
        # 'fail' of the envelope: not a geometry to iterate
        return geom_shp
    if isinstance(geom_shp, (MultiPolygon, MultiLineString)):
        geom = geom_shp.geoms
    else:
        geom = geom_shp

    if invert:
        try:
            pl = []
            for p in geom:
                if p is not None:
                    if isinstance(p, Polygon):
                        pl.append(milling_orient(p, conventional=True))
                    elif isinstance(p, LinearRing):
                        pl.append(Polygon(p.coords[::-1]))
            geom = MultiPolygon(pl)
        except TypeError:
            if isinstance(geom, Polygon) and geom is not None:
                geom = milling_orient(geom, conventional=True)
            elif isinstance(geom, LinearRing) and geom is not None:
                geom = Polygon(geom.coords[::-1])
            else:
                debug("ToolIsolation.generate_envelope() Error --> Unexpected Geometry %s" % type(geom))
        except Exception as e:
            error("ToolIsolation.generate_envelope() Error --> %s" % str(e))
            return 'fail'
    return geom


def generate_rest_geometry(geometry, tooldia, passes, overlap, invert, env_iso_type=2, negative_dia=None,
                           forced_rest=False, prog_plot="normal", prog_plot_handler=None, plot=False,
                           error_handler=None):
    """Return ordered isolation paths and polygons left for the next tool.

    Overlap is a fraction. Plot/error callbacks carry notifications only, not controller state.
    """
    isolated_geo = []
    not_isolated_geo = []
    work_geo = []

    # a Polygon, a MultiPolygon or a (nested) list of them
    geometry = [geo for geo in flatten_shapely_geometry(geometry) if isinstance(geo, Polygon)]
    geo_len = len(geometry)
    if geo_len == 0:
        return isolated_geo, not_isolated_geo
    geo_array = np.empty(geo_len, dtype=object)
    geo_array[:] = geometry
    # Sparse passes use bulk queries; dense passes stop at the first collision instead of collecting every pair.
    geo_indexes = np.arange(geo_len)
    geo_tree = None
    pass_offsets = []
    pass_intersects = []
    first_pass_iso = [None] * geo_len
    abandoned = np.zeros(geo_len, dtype=bool)
    for nr_pass in range(passes):
        iso_offset = pass_offset(tooldia, nr_pass, overlap, negative_dia, denominator=2.0)

        buf_chek = iso_offset * 1.99999
        # (quad_segs=16: as geo.buffer())
        check_geo = shapely.buffer(geo_array[geo_indexes], buf_chek, quad_segs=16)
        check_tree = shapely.STRtree(check_geo)
        intersect_flags = np.zeros(geo_len, dtype=bool)
        # ponytail: cap each bulk query at 65536 possible pairs (or one query polygon for a larger index).
        # A missed dense cluster can cost extra queries, but cannot create a quadratic temporary array.
        batch_size = max(1, 65536 // max(1, len(check_geo)))
        sample_indexes = np.linspace(0, geo_len, min(16, batch_size, geo_len), endpoint=False, dtype=int)
        other_idx, check_idx = check_tree.query(geo_array[sample_indexes], predicate='intersects')
        check_idx = geo_indexes[check_idx]
        intersect_flags[check_idx[check_idx != sample_indexes[other_idx]]] = True

        if len(check_idx) > 8 * len(sample_indexes):
            if geo_tree is None:
                geo_tree = shapely.STRtree(geo_array)
            # Keep collisions already found by the sample; only unresolved check buffers need a search.
            for check_pos in np.flatnonzero(~intersect_flags[geo_indexes]):
                idx = geo_indexes[check_pos]
                check = check_geo[check_pos]
                for other_idx in geo_tree.query(check):
                    if other_idx != idx and check.intersects(geo_array[other_idx]):
                        intersect_flags[idx] = True
                        break
        else:
            query_mask = np.ones(geo_len, dtype=bool)
            query_mask[sample_indexes] = False
            query_indexes = np.flatnonzero(query_mask)
            # The index holds check buffers and the original polygons are the prepared queries, so a large
            # ground pour is prepared once per query rather than walked for every nearby check buffer.
            for start in range(0, len(query_indexes), batch_size):
                batch = query_indexes[start:start + batch_size]
                other_idx, check_idx = check_tree.query(geo_array[batch], predicate='intersects')
                check_idx = geo_indexes[check_idx]
                intersect_flags[check_idx[check_idx != batch[other_idx]]] = True
        pass_offsets.append(iso_offset)
        pass_intersects.append(intersect_flags)

        if nr_pass != 0:
            continue

        # if we had an intersection do nothing, else the geo is isolated in the first pass
        free_indexes = np.flatnonzero(~intersect_flags)
        free_buffers = shapely.buffer(geo_array[free_indexes], iso_offset, quad_segs=16)
        for idx, temp_geo in zip(free_indexes.tolist(), free_buffers):
            geo = geometry[idx]
            first_pass_iso[idx] = temp_geo
            # Check interiors on the first pass only; abandon polygons whose holes cannot be isolated.
            if forced_rest is False:
                len_interiors = len(geo.interiors)
                if len_interiors >= 1:
                    total_poly_len = 1 + len_interiors
                    if isinstance(temp_geo, Polygon):
                        temp_geo_len = len([1] + list(temp_geo.interiors))
                        if total_poly_len != temp_geo_len:
                            abandoned[idx] = True
                    else:
                        try:
                            temp_geo_len = len(temp_geo)
                            if total_poly_len != temp_geo_len:
                                abandoned[idx] = True
                        except TypeError:
                            abandoned[idx] = True

        # the next passes are tested only for the geos that are not abandoned
        geo_indexes = np.flatnonzero(~abandoned)

    # the later passes of the polygons that are not abandoned and have no neighbor in the pass, buffered in bulk
    later_pass_iso = [None]
    for nr_pass in range(1, passes):
        idxs = np.flatnonzero(~pass_intersects[nr_pass] & ~abandoned)
        buffered = shapely.buffer(geo_array[idxs], pass_offsets[nr_pass], quad_segs=16)
        later_pass_iso.append(dict(zip(idxs.tolist(), buffered)))

    for idx, geo in enumerate(geometry):
        good_pass_iso = []
        if not abandoned[idx]:
            for nr_pass in range(passes):
                if not pass_intersects[nr_pass][idx]:
                    temp_geo = first_pass_iso[idx] if nr_pass == 0 else later_pass_iso[nr_pass][idx]
                    good_pass_iso.append(temp_geo)
                    if plot and prog_plot == 'progressive':
                        prog_plot_handler(temp_geo)

        if good_pass_iso:
            work_geo += good_pass_iso
        else:
            not_isolated_geo.append(geo)

    work_geo_shp = flatten_shapely_geometry(work_geo)
    if invert:
        try:
            is_polygon = [isinstance(p, Polygon) for p in work_geo_shp]
            polygons = np.empty(sum(is_polygon), dtype=object)
            polygons[:] = [p for p in work_geo_shp if isinstance(p, Polygon)]
            oriented = iter(shapely.orient_polygons(polygons, exterior_cw=False))
            pl = []
            for p, polygon in zip(work_geo_shp, is_polygon):
                if polygon:
                    pl.append(next(oriented))
                elif isinstance(p, LinearRing):
                    pl.append(Polygon(p.coords[::-1]))
            work_geo_shp = MultiPolygon(pl)
        except Exception as e:
            if error_handler is not None:
                error_handler("ToolIsolation.generate_rest_geometry() Error --> %s" % str(e))
            return 'fail', 'fail'

    actual_geo = flatten_shapely_geometry(work_geo_shp)
    if env_iso_type == 0:
        for geo in actual_geo:
            isolated_geo.append(geo.exterior)
    elif env_iso_type == 1:
        for geo in actual_geo:
            isolated_geo += [interior for interior in geo.interiors]
    else:
        for geo in actual_geo:
            isolated_geo += [geo.exterior] + [interior for interior in geo.interiors]
    return isolated_geo, not_isolated_geo


def get_selected_interior(poly: Polygon, point: tuple) -> [Polygon, None]:
    try:
        ints = [Polygon(x) for x in poly.interiors]
    except AttributeError:
        return None
    for poly in ints:
        if poly.contains(Point(point)):
            return poly
    return None


def find_polygon_ignore_interiors(point, geoset):
    """Find the first containing polygon, treating its holes as filled."""
    try:
        for sub_geo in geoset:
            p = find_polygon_ignore_interiors(point, geoset=sub_geo)
            if p is not None:
                return p
    except TypeError:
        try:
            if isinstance(geoset, LinearRing):
                geoset = Polygon(geoset)
            poly_ext = Polygon(geoset.exterior)
            if poly_ext.contains(Point(point)):
                return geoset
        except AttributeError:
            return None
    return None


def flatten_list(obj_list):
    for item in obj_list:
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            yield from flatten_list(item)
        else:
            yield item
