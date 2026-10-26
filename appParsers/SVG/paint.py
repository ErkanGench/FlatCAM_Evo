"""Turns polylines into Shapely geometries: fill rules, strokes and clean-up."""
import logging
import math

import numpy as np
import shapely
from shapely import STRtree
from shapely.affinity import affine_transform
from shapely.geometry import LineString, MultiLineString, Polygon

from .document import parse_length
from .flatten import quad_segs
from .style import fill_active, is_zero, stroke_paint_active
from .transform import mean_scale

log = logging.getLogger('base')

_CAP = {'butt': 'flat', 'round': 'round', 'square': 'square'}
_JOIN = {'miter': 'mitre', 'round': 'round', 'bevel': 'bevel', 'miter-clip': 'mitre', 'arcs': 'mitre'}
_CHUNK = 4_000_000


def _xf(pts, a, t):
    return pts @ a.T + t


def _affine_list(m):
    return [m[0, 0], m[0, 1], m[1, 0], m[1, 1], m[0, 2], m[1, 2]]


def _polygon(ring):
    try:
        return Polygon(ring)
    except (ValueError, shapely.errors.ShapelyError):
        return None


def _signed_area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _winding(points, rings):
    """Winding numbers of points w.r.t. all rings (non-zero rule)."""
    closed = [np.vstack((r, r[:1])) for r in rings]
    p0 = np.concatenate([c[:-1] for c in closed])
    p1 = np.concatenate([c[1:] for c in closed])
    x0, y0, x1, y1 = p0[:, 0], p0[:, 1], p1[:, 0], p1[:, 1]
    out = np.zeros(len(points), dtype=np.int64)
    step = max(1, _CHUNK // max(len(x0), 1))
    for s in range(0, len(points), step):
        px = points[s:s + step, 0][:, None]
        py = points[s:s + step, 1][:, None]
        left = (x1 - x0) * (py - y0) - (px - x0) * (y1 - y0)
        up = (y0 <= py) & (y1 > py) & (left > 0)
        down = (y1 <= py) & (y0 > py) & (left < 0)
        out[s:s + step] = up.sum(axis=1) - down.sum(axis=1)
    return out


def _fill_general(rings, rule):
    """Exact fill of arbitrary (self-intersecting, overlapping) rings via noding and polygonize."""
    lines = [shapely.linestrings(np.vstack((r, r[:1]))) for r in rings if len(r) >= 3]
    if not lines:
        return []
    noded = shapely.node(shapely.multilinestrings(lines))
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(noded)))
    if len(faces) == 0:
        return []
    reps = shapely.get_coordinates(shapely.point_on_surface(faces))
    wn = _winding(reps, rings)
    keep = (wn != 0) if rule == 'nonzero' else (wn % 2 != 0)
    chosen = faces[keep]
    if len(chosen) == 0:
        return []
    return list(shapely.get_parts(shapely.union_all(chosen)))


def _fill_nested(polys, rings, rule):
    """Fill for non-overlapping rings (disjoint or nested); None when rings overlap."""
    tree = STRtree(polys)
    if tree.query(polys, predicate='overlaps').shape[1] > 0:
        return None
    signs = np.array([1 if _signed_area(r) >= 0 else -1 for r in rings])
    if rule != 'nonzero':
        signs = np.ones(len(rings), dtype=np.int64)
    pairs = tree.query(polys, predicate='within')
    mask = pairs[0] != pairs[1]
    inner, outer = pairs[0][mask], pairs[1][mask]
    w = signs.astype(np.int64).copy()
    np.add.at(w, inner, signs[outer])
    if rule == 'nonzero':
        eff = (w != 0) != ((w - signs) != 0)
    else:
        eff = (w % 2 == 1) != ((w - 1) % 2 == 1)
    eff_idx = np.flatnonzero(eff)
    if len(eff_idx) == 0:
        return []
    areas = np.array([p.area for p in polys])
    parents = {}
    depth = {int(i): 0 for i in eff_idx}
    for i, o in zip(inner.tolist(), outer.tolist()):
        if eff[i] and eff[o]:
            depth[i] += 1
            best = parents.get(i)
            if best is None or areas[o] < areas[best]:
                parents[i] = o
    holes = {}
    for i, d in depth.items():
        if d % 2 == 1 and i in parents:
            holes.setdefault(parents[i], []).append(rings[i])
    result = []
    for i, d in depth.items():
        if d % 2 == 0:
            result.append(Polygon(rings[i], holes.get(i, [])))
    return result


def fill_polygons(rings, rule='nonzero'):
    """
    :param rings: list of (N,2) arrays, implicitly closed
    :param rule: 'nonzero' or 'evenodd'
    :return: list of valid Polygons
    """
    candidates, rings, polys = rings_in(rings), [], []
    for r in candidates:
        p = _polygon(r)
        if p is not None:
            rings.append(r)
            polys.append(p)
    if not polys:
        return []
    if len(polys) == 1:
        if polys[0].is_valid:
            return [polys[0]] if polys[0].area > 0 else []
        return _fill_general(rings, rule)
    if shapely.is_valid(np.array(polys, dtype=object)).all():
        res = _fill_nested(polys, rings, rule)
        if res is not None:
            return res
    return _fill_general(rings, rule)


def rings_in(rings):
    """Yield rings with at least 3 points."""
    return [r for r in rings if len(r) >= 3]


def _dedupe(pts):
    keep = np.concatenate(([True], np.any(pts[1:] != pts[:-1], axis=1)))
    return pts[keep]


def _lines(polylines, a=None, t=None):
    lines = []
    for pts, closed in polylines:
        if a is not None:
            pts = _xf(pts, a, t)
        pts = _dedupe(pts)
        if closed and len(pts) > 1 and (pts[0] != pts[-1]).any():
            pts = np.vstack((pts, pts[:1]))
        if len(pts) >= 2:
            lines.append(shapely.linestrings(pts))
    return lines


def _buffer(lines, half, style, quad):
    geom = lines[0] if len(lines) == 1 else MultiLineString(lines)
    try:
        limit = max(1.0, float(style['stroke-miterlimit']))
    except ValueError:
        limit = 4.0
    return geom.buffer(half, quad_segs=max(1, int(quad)),
                       cap_style=_CAP.get(style['stroke-linecap'], 'flat'),
                       join_style=_JOIN.get(style['stroke-linejoin'], 'mitre'), mitre_limit=limit)


def stroke_width(style, vp, font_size):
    """
    :return: stroke width in user units (0 when the stroke is off)
    """
    if not stroke_paint_active(style):
        return 0.0
    ref = math.sqrt((vp[0] ** 2 + vp[1] ** 2) / 2.0)
    w = parse_length(style['stroke-width'], ref, font_size)
    return 1.0 if w is None else max(w, 0.0)


def explode(geom, out):
    """Append the simple parts (Polygon / LineString) of a geometry to out."""
    if geom is None or geom.is_empty:
        return
    tid = shapely.get_type_id(geom)
    if tid in (1, 2, 3):
        out.append(geom)
    elif tid >= 4:
        for part in shapely.get_parts(geom):
            explode(part, out)


def finish(geoms, polygons_only):
    """
    :param geoms: iterable of geometries
    :param polygons_only: drop everything that is not a Polygon
    :return: flat list of valid non-empty simple geometries
    """
    flat = []
    for g in geoms:
        explode(g, flat)
    out = []
    for g in flat:
        tid = shapely.get_type_id(g)
        if tid == 3:
            if not g.is_valid:
                fixed = []
                explode(shapely.make_valid(g), fixed)
                out.extend(p for p in fixed if shapely.get_type_id(p) == 3 and p.area > 0)
            elif g.area > 0:
                out.append(g)
        elif tid in (1, 2) and not polygons_only:
            out.append(g)
    return out


def batchable(gerber, closed, fill_on, stroke_on, width):
    """
    :return: True when a single ring only needs its plain fill (no stroke geometry, no lines)
    """
    if gerber:
        return fill_on and width <= 0
    return closed and (fill_on or stroke_on)


def single_ring(polylines, gerber, fill_on, stroke_on, width):
    """
    :param polylines: list of (points, closed) in user space
    :param gerber: True for polygon-only output
    :param fill_on: the fill paints
    :param stroke_on: the stroke paint is set (ignoring width)
    :param width: stroke width in user units (0 when off)
    :return: the ring points when the element is exactly one plain fill ring that can be batched, else None
    """
    if len(polylines) != 1:
        return None
    pts, closed = polylines[0]
    if len(pts) < 3:
        return None
    if not batchable(gerber, closed, fill_on, stroke_on, width):
        return None
    if len(pts) == 3 and pts[0, 0] == pts[2, 0] and pts[0, 1] == pts[2, 1]:
        return None
    return pts


def element_geometries(polylines, style, own, m, gerber, vp, font_size, resolution, ns_scale=1.0):
    """
    :param polylines: list of (points, closed) in user space
    :param style: computed style
    :param own: properties specified on the element
    :param m: 3x3 user -> output matrix
    :param gerber: True for polygon-only output
    :param vp: viewport size
    :param font_size: current font size
    :param resolution: segments per quarter circle (int), or a function: radius in output units -> segments
    :param ns_scale: user -> output scale used for non-scaling strokes
    :return: list of Shapely geometries in output space
    """
    a, t = m[:2, :2], m[:2, 2]
    rule = 'evenodd' if style['fill-rule'] == 'evenodd' else 'nonzero'
    fill_on = fill_active(style)
    if not gerber:
        if not (fill_on or stroke_paint_active(style)):
            return []
        rings = [_xf(p, a, t) for p, c in polylines if c and len(p) >= 3]
        geoms = fill_polygons(rings, rule)
        rest = [(p, c) for p, c in polylines if not (c and len(p) >= 3)]
        geoms.extend(_lines(rest, a, t))
        return finish(geoms, False)
    parts = []
    if fill_on:
        parts.extend(fill_polygons([_xf(p, a, t) for p, c in polylines if len(p) >= 3], rule))
    width = stroke_width(style, vp, font_size)
    if width > 0:
        g = _stroke(polylines, width, style, own, m, resolution, ns_scale)
        if g is not None:
            parts.append(g)
    if len(parts) > 1:
        parts = [shapely.union_all(parts)]
    return finish(parts, True)


def _stroke(polylines, width, style, own, m, resolution, ns_scale):
    a, t = m[:2, :2], m[:2, 2]
    if own.get('vector-effect') == 'non-scaling-stroke':
        lines = _lines(polylines, a, t)
        half = width * ns_scale / 2.0
        return _buffer(lines, half, style, quad_segs(resolution, half)) if lines else None
    lines = _lines(polylines)
    if not lines:
        return None
    half = width / 2.0
    return affine_transform(_buffer(lines, half, style, quad_segs(resolution, half * mean_scale(m))), _affine_list(m))


def area_geometries(geom, style, own, m, gerber, vp, font_size, resolution, ns_scale=1.0):
    """
    Paint an already built polygonal geometry (text glyphs) given in user space.

    :return: list of geometries in output space
    """
    fill_on = fill_active(style)
    parts = []
    if fill_on:
        parts.append(affine_transform(geom, _affine_list(m)))
    elif gerber and stroke_width(style, vp, font_size) > 0:
        lines = [shapely.linestrings(np.asarray(r.coords)) for p in shapely.get_parts(geom)
                 for r in [p.exterior, *p.interiors]]
        half = stroke_width(style, vp, font_size) / 2.0
        if lines:
            parts.append(affine_transform(
                _buffer(lines, half, style, quad_segs(resolution, half * mean_scale(m))), _affine_list(m)))
    elif not gerber and stroke_paint_active(style):
        parts.append(affine_transform(geom, _affine_list(m)))
    return finish(parts, gerber)
