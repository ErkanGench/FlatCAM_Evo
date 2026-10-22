"""Translate selected straight segments, stretching neighbors or adding endpoint cords."""
import math
import gettext
import builtins
from collections import Counter

from shapely import LineString, Polygon, MultiLineString, MultiPolygon

from appEditors.vertex_ops import SUPPORTED_TYPES, parts_of, rings_of, vertex_grips, check_vertex_result
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def segments_of(geometry):
    """(address, line) for each straight segment; tessellated arcs keep their existing arc grips."""
    parts = parts_of(geometry)
    for kind, address, point in vertex_grips(geometry):
        if kind == 'mid':
            part, ring, index = address
            coords = list(rings_of(parts[part])[ring].coords)
            yield address, LineString(coords[index:index + 2])


def segment_geometries(geometries, selected, offset, cords=False):
    """Replacement geometries for one atomic drag. Addresses refer to the original coordinate lists.

    Shared selected endpoints move once. In cord mode, touching open records form one polyline: only its outer
    extremities get cords. In stretch mode, unselected input geometries sharing moved vertices stretch too.
    """
    if len(offset) != 2 or not all(math.isfinite(value) for value in offset):
        raise ValueError(_('Choose a finite X and Y offset.'))
    dx, dy = offset
    if dx == 0 and dy == 0:
        return {}
    if any(not isinstance(geometry, SUPPORTED_TYPES) or geometry.is_empty or geometry.has_z
           for geometry in geometries.values()):
        raise ValueError(_('Segment dragging supports two-dimensional lines and polygons.'))
    endpoints = Counter()
    for shape, addresses in selected.items():
        if shape not in geometries:
            raise ValueError(_('The selected shape changed. Select it again.'))
        available = dict(segments_of(geometries[shape]))
        for address in addresses:
            if address not in available:
                raise ValueError(_('Choose a valid straight segment.'))
            endpoints.update(tuple(point) for point in available[address].coords)
    results = {}
    for shape, geometry in geometries.items():
        addresses = selected.get(shape, set())
        if cords and not addresses:
            continue
        parts = parts_of(geometry)
        changed = []
        for part_nr, part in enumerate(parts):
            rings = []
            for ring_nr, ring in enumerate(rings_of(part)):
                coords = [tuple(point) for point in ring.coords]
                closed = coords[0] == coords[-1]
                vertices = coords[:-1] if closed else coords
                edges = {address[2] for address in addresses if address[:2] == (part_nr, ring_nr)}
                result = []
                for index, point in enumerate(vertices):
                    moved = (point[0] + dx, point[1] + dy)
                    incoming = (index - 1) % len(vertices) in edges if closed or index > 0 else False
                    outgoing = index in edges
                    if not cords:
                        result.append(moved if point in endpoints else point)
                    elif incoming and outgoing:
                        result.append(moved)
                    elif incoming or outgoing:
                        # Open records meeting at a selected joint share the moved vertex, without an inner cord.
                        joined = not closed and index in (0, len(vertices) - 1) and endpoints[point] > 1
                        result.extend([moved] if joined else ([point, moved] if outgoing else [moved, point]))
                    else:
                        result.append(point)
                if closed:
                    result.append(result[0])
                if any(a == b for a, b in zip(result, result[1:])):
                    raise ValueError(_('The drag would create a zero-length segment.'))
                if result != coords:
                    changed.append((part_nr, ring_nr, 0))
                rings.append(result)
            parts[part_nr] = Polygon(rings[0], rings[1:]) if isinstance(part, Polygon) else type(part)(rings[0])
        if changed:
            result = type(geometry)(parts) if isinstance(geometry, (MultiLineString, MultiPolygon)) else parts[0]
            for address in changed:
                check_vertex_result(result, address)
            results[shape] = result
    return results
