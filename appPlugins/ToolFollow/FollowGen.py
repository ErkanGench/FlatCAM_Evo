"""Follow path processing with explicit geometry and selection inputs."""

from copy import deepcopy

from shapely import MultiLineString, Point, line_merge, simplify
from shapely.ops import unary_union

from camlib import flatten_shapely_geometry


def selected_geometry(geometry, selection):
    return unary_union(geometry).intersection(deepcopy(unary_union(selection)))


def follow_geometry(geometry, should_union, should_simplify, simplify_tol, selection=None):
    if selection is not None:
        geometry = selected_geometry(geometry, selection)
    flattened = flatten_shapely_geometry(geometry)
    cleaned = [f for f in flattened if not isinstance(f, Point) and not f.is_empty]
    merged = line_merge(MultiLineString(cleaned))
    if merged and not merged.is_empty:
        flattened = flatten_shapely_geometry(merged)
    result = [g for g in flattened if g and not g.is_empty and g.is_valid and g.geom_type != 'Point']
    if should_simplify and simplify_tol > 0.0:
        result = [simplify(f, tolerance=simplify_tol) for f in result]
    if should_union:
        result = unary_union(result)
    return flattened, result
