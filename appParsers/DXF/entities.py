"""
Per-entity converters: ezdxf entity -> list of Shapely geometries (WCS, 2D).
Every converter takes the entity and an ImportContext (text mode, flattening tolerance).
"""
import logging
import math

from ezdxf import path as ezpath
from shapely.geometry import LineString, Point, Polygon
from shapely.validation import make_valid

from . import text
from .context import is_circle_ellipse
from .curves import path_to_rings, rings_to_polygons

log = logging.getLogger('base')

POINT_RADIUS = 0.01


def _valid_polygons(points):
    """
    :param points:  corner coordinates
    :return:        list with the polygon(s) built from them (empty if degenerate)
    """
    poly = Polygon(points)
    if not poly.is_valid:
        poly = make_valid(poly)
    return [g for g in getattr(poly, 'geoms', [poly]) if g.geom_type == 'Polygon' and g.area > 0]


def convert_point(entity, ctx):
    """
    :param entity:      POINT
    :param ctx:         ImportContext
    :return:            small filled disk
    """
    loc = entity.dxf.location
    return [Point(loc.x, loc.y).buffer(POINT_RADIUS, max(1, math.ceil(ctx.circle_steps(POINT_RADIUS) / 4)))]


def convert_line(entity, ctx):
    """
    :param entity:      LINE
    :param ctx:         ImportContext
    :return:            LineString, nothing for zero-length lines
    """
    a, b = entity.dxf.start, entity.dxf.end
    if (a.x, a.y) == (b.x, b.y):
        return []
    return [LineString([(a.x, a.y), (b.x, b.y)])]


def convert_circle(entity, ctx):
    """
    :param entity:      CIRCLE
    :param ctx:         ImportContext
    :return:            filled disk, honouring OCS
    """
    if entity.dxftype() == 'CIRCLE':
        radius = entity.dxf.radius
    else:
        radius = entity.dxf.major_axis.magnitude
    # a circle is 4 Bezier pieces
    pieces = max(1, math.ceil(ctx.circle_steps(radius) / 4))
    rings = path_to_rings(ezpath.make_path(entity), pieces, ctx.tolerance)
    return _valid_polygons(rings[0]) if rings and len(rings[0]) >= 4 else []


def convert_curve(entity, ctx):
    """
    ARC, ELLIPSE, SPLINE, LWPOLYLINE, POLYLINE; closed shapes stay closed-ring LineStrings.
    An ELLIPSE that is a scaled CIRCLE from a block stays a filled disk.

    :param entity:      curve-like entity
    :param ctx:         ImportContext
    :return:            list of LineStrings (a Polygon for a scaled circle)
    """
    if is_circle_ellipse(entity):
        return convert_circle(entity, ctx)
    lines = [LineString(r) for r in path_to_rings(ezpath.make_path(entity), tolerance=ctx.tolerance)]
    return [ln for ln in lines if ln.length > 0]


def convert_solid(entity, ctx):
    """
    SOLID/TRACE store their corners in the order 0,1,3,2; ezdxf wcs_vertices() already
    returns them in outline order (and applies the OCS).

    :param entity:      SOLID or TRACE
    :param ctx:         ImportContext
    :return:            list with a Polygon
    """
    v = [(p.x, p.y) for p in entity.wcs_vertices()]
    if len(v) == 4 and v[2] == v[3]:
        v.pop()
    return _valid_polygons(v) if len(v) >= 3 else []


def convert_face(entity, ctx):
    """
    :param entity:      3DFACE
    :param ctx:         ImportContext
    :return:            list with a Polygon
    """
    v = [(p.x, p.y) for p in entity.wcs_vertices()]
    if len(v) == 4 and v[2] == v[3]:
        v.pop()
    return _valid_polygons(v) if len(v) >= 3 else []


def convert_hatch(entity, ctx):
    """
    The boundary paths are combined with the even-odd rule: nested boundaries are holes,
    an island inside a hole is filled again.

    :param entity:      HATCH
    :param ctx:         ImportContext
    :return:            list of Polygons
    """
    return rings_to_polygons(path_to_rings(ezpath.make_path(entity), tolerance=ctx.tolerance))


def convert_text(entity, ctx):
    """
    :param entity:      TEXT, ATTRIB or MTEXT
    :param ctx:         ImportContext
    :return:            glyph geometry
    """
    return text.text_entity_to_shapes(entity, ctx.text_mode, ctx.tolerance)


# dxftype -> converter. INSERT is handled in blocks.py / reader.py (it needs recursion).
# ATTDEF is not listed on purpose: it is a template, the ATTRIB values are drawn instead.
CONVERTERS = {
    'POINT': convert_point,
    'LINE': convert_line,
    'CIRCLE': convert_circle,
    'ARC': convert_curve,
    'ELLIPSE': convert_curve,
    'SPLINE': convert_curve,
    'LWPOLYLINE': convert_curve,
    'POLYLINE': convert_curve,
    'SOLID': convert_solid,
    'TRACE': convert_solid,
    '3DFACE': convert_face,
    'HATCH': convert_hatch,
    'TEXT': convert_text,
    'ATTRIB': convert_text,
    'MTEXT': convert_text,
}


def convert_entity(entity, ctx):
    """
    Convert one entity; never raises. Invisible entities and entities on hidden layers
    give nothing.

    :param entity:      any non-INSERT ezdxf entity
    :param ctx:         ImportContext
    :return:            list of non-empty valid Shapely geometries
    """
    func = CONVERTERS.get(entity.dxftype())
    if func is None:
        return []
    try:
        if not ctx.is_visible(entity):
            return []
        return [g for g in func(entity, ctx) if g is not None and not g.is_empty and g.is_valid]
    except Exception as err:
        log.debug("DXF %s skipped: %s" % (entity.dxftype(), str(err)))
        return []
