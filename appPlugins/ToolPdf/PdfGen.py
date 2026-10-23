"""PDF paint composition and drill detection. No Qt or application state."""

import math

from shapely import Polygon
from shapely.ops import unary_union

from appParsers.feature_access import normalize_polygonal


def _normalize_ap_dict(ap_dict):
    """PDF parser keys are strings; Gerber tools and Excellon layers use integers."""
    return {int(key): value for key, value in ap_dict.items()}


def _paint_elements(ap_dict):
    """Return all geometry elements in painter order, or insertion order if absent."""
    elements = []
    for aperture in ap_dict:
        elements.extend(ap_dict[aperture].get('geometry', []))
    if any('order' in element for element in elements):
        elements.sort(key=lambda element: element.get('order', 0))
    return elements


def _replay_paint_order(ap_dict):
    """Compose cross-aperture solids and clears in paint order."""
    solid = None
    follow = []
    pending_solids = []

    def flush_solids():
        nonlocal solid, pending_solids
        if pending_solids:
            batch = unary_union(pending_solids)
            solid = batch if solid is None else solid.union(batch)
            pending_solids = []

    for element in _paint_elements(ap_dict):
        if 'solid' in element:
            pending_solids.append(element['solid'])
        if 'follow' in element:
            follow.append(element['follow'])
        if 'clear' in element:
            flush_solids()
            if solid is not None:
                solid = solid.difference(element['clear'])
    flush_solids()
    if solid is None:
        solid = Polygon()
    follow_buf = unary_union(follow) if follow else Polygon()
    return solid, follow_buf


def _region_tools(geometry):
    """Store composed regions largest first so islands survive earlier clears."""
    solid = normalize_polygonal(geometry)
    polygons = [solid] if isinstance(solid, Polygon) else list(solid.geoms)
    polygons = [polygon for polygon in polygons if not polygon.is_empty]
    polygons.sort(key=lambda polygon: Polygon(polygon.exterior).area, reverse=True)
    return {0: {'type': 'REG', 'size': 0,
                'geometry': [{'solid': polygon} for polygon in polygons]}}


def _circular_opening(geometry):
    """Return ``((x, y), diameter)`` when the geometry is a true circular opening."""
    if not isinstance(geometry, Polygon) or geometry.is_empty or geometry.interiors:
        return None
    xmin, ymin, xmax, ymax = geometry.bounds
    width = xmax - xmin
    height = ymax - ymin
    if width <= 0 or height <= 0:
        return None
    diameter = (width + height) / 2.0
    if abs(width - height) > diameter * 0.05:
        return None
    circle_area = math.pi * (diameter / 2.0) ** 2
    if circle_area <= 0 or abs(geometry.area - circle_area) > circle_area * 0.05:
        return None
    return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0), diameter


def drill_points(ap_dict, units):
    """Group circular bores by diameter, excluding duplicates and enclosing antipads."""
    clear_geo = [geo_el['clear'] for geo_el in ap_dict.get(0, {}).get('geometry', [])
                 if 'clear' in geo_el]
    all_holes = []
    tolerance = 0.001 if str(units).upper() == 'MM' else 0.0001
    for geo in clear_geo:
        opening = _circular_opening(geo)
        if opening is None:
            continue
        center, dia = opening
        dia = round(dia, 3)
        for idx, (other_center, other_dia) in enumerate(all_holes):
            if math.hypot(center[0] - other_center[0], center[1] - other_center[1]) <= tolerance:
                if dia < other_dia:
                    all_holes[idx] = (center, dia)
                break
        else:
            all_holes.append((center, dia))

    points = {}
    for center, dia in all_holes:
        for other_center, other_dia in all_holes:
            if other_dia >= dia:
                continue
            distance = math.hypot(center[0] - other_center[0], center[1] - other_center[1])
            if distance + other_dia / 2.0 <= dia / 2.0 + tolerance:
                break
        else:
            points.setdefault(dia, []).append(center)
    return points
