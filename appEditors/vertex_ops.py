"""
Vertex edits on Shapely geometry, addressed as (part, ring, index).

No Qt and no editor code: the Geometry Editor uses these functions now, the Gerber Editor later.
part: 0 for a single geometry, else the index in .geoms. ring: 0 for a line or a polygon exterior, 1+ for the holes.
index: the vertex in the full coordinate list of the ring; the closing coordinate of a closed ring is an alias of 0.
Arcs are found from the coordinates (find_arcs). An arc is addressed as (part, ring, start, end): its end vertices.
"""
import math
import gettext
import builtins
from collections import namedtuple

from shapely import LineString, LinearRing, Polygon, MultiLineString, MultiPolygon, Point

import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

SUPPORTED_TYPES = (LineString, LinearRing, Polygon, MultiLineString, MultiPolygon)
# RGB distance (0 - 441) under which 2 colors are too near to tell apart on the canvas
COLOR_CLASH_DIST = 100
ARC_LEN_TOL = 0.02                  # relative difference of 2 segment lengths in 1 arc
ARC_ANGLE_TOL = 0.02                # radians: difference of 2 turn angles in 1 arc
ARC_MAX_TURN = math.radians(30)     # a larger turn at a vertex is a corner, not an arc (a square is not a circle)
ARC_MIN_SEGMENTS = 3
DEFAULT_CIRCLE_STEPS = 32           # the factory value of geometry_circle_steps

Arc = namedtuple('Arc', 'start end middle full')


def parts_of(geom):
    return list(geom.geoms) if isinstance(geom, (MultiLineString, MultiPolygon)) else [geom]


def rings_of(part):
    return [part.exterior, *part.interiors] if isinstance(part, Polygon) else [part]


def _turn(a, b, c):
    """Signed turn angle at b, from the direction a->b to the direction b->c."""
    angle = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(b[1] - a[1], b[0] - a[0])
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _close(a, b, tol):
    return abs(a - b) <= tol * max(abs(a), abs(b))


def circle_center(a, b, c):
    """Center of the circle through 3 points, or None if they are on 1 line."""
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    scale = max(math.dist(a, b), math.dist(b, c), math.dist(a, c))
    if scale == 0 or abs(d) <= 1e-12 * scale * scale:
        return None
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    return ((a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d,
            (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d)


def _sweep(begin, through, end, center):
    """(start angle, signed sweep) of the arc from begin through `through` to end."""
    a0 = math.atan2(begin[1] - center[1], begin[0] - center[0])
    at = (math.atan2(through[1] - center[1], through[0] - center[0]) - a0) % (2 * math.pi)
    a1 = (math.atan2(end[1] - center[1], end[0] - center[0]) - a0) % (2 * math.pi)
    return a0, (a1 if at <= a1 else a1 - 2 * math.pi)


def arc_middle(begin, through, end):
    """The point at the half angle of the arc from begin through `through` to end (the middle of the segment if
    the 3 points are on 1 line)."""
    center = circle_center(begin, through, end)
    if center is None:
        return (begin[0] + end[0]) / 2, (begin[1] + end[1]) / 2
    a0, sweep = _sweep(begin, through, end, center)
    radius = math.dist(center, begin)
    return center[0] + radius * math.cos(a0 + sweep / 2), center[1] + radius * math.sin(a0 + sweep / 2)


def arc_points(begin, through, end, steps):
    """The points of the arc from begin through `through` to end, begin and end included. steps count the full
    circle. 3 points on 1 line give the straight segment [begin, end]. The segment count keeps the arc findable by
    find_arcs: at least ARC_MIN_SEGMENTS, and a turn of at most ARC_MAX_TURN at each vertex."""
    center = circle_center(begin, through, end)
    if center is None:
        return [tuple(begin), tuple(end)]
    a0, sweep = _sweep(begin, through, end, center)
    radius = math.dist(center, begin)
    count = max(ARC_MIN_SEGMENTS, round(steps * abs(sweep) / (2 * math.pi)), math.ceil(abs(sweep) / ARC_MAX_TURN))
    inner = [(center[0] + radius * math.cos(a0 + sweep * i / count),
              center[1] + radius * math.sin(a0 + sweep * i / count)) for i in range(1, count)]
    return [tuple(begin), *inner, tuple(end)]


def find_arcs(vertices, closed):
    """[Arc] of 1 ring: runs of at least ARC_MIN_SEGMENTS segments of equal length with the same turn at each inner
    vertex. vertices has no closing coordinate. In a closed ring an arc can cross vertex 0 (end < start). A closed
    ring that is 1 run is a full circle: [Arc(0, 0, None, True)]."""
    count = len(vertices)
    seg_count = count if closed else count - 1
    if seg_count < ARC_MIN_SEGMENTS:
        return []
    lengths = [math.dist(vertices[i], vertices[(i + 1) % count]) for i in range(seg_count)]
    turns = {}
    for k in range(count if closed else count - 1):
        if closed or k > 0:
            turns[k] = _turn(vertices[k - 1], vertices[k], vertices[(k + 1) % count])

    def inner_ok(k):
        """Vertex k can be an inner vertex of an arc."""
        return (k in turns and 0 < abs(turns[k]) <= ARC_MAX_TURN and
                _close(lengths[k - 1], lengths[k % seg_count], ARC_LEN_TOL))

    start = 0
    if closed:
        # start the scan at a vertex that no arc can pass through
        breaks = [k for k in range(count) if not inner_ok(k)]
        if not breaks:
            if all(abs(turns[k] - turns[0]) <= ARC_ANGLE_TOL for k in range(count)):
                return [Arc(0, 0, None, True)]
            k = next(k for k in range(count) if abs(turns[k] - turns[k - 1]) > ARC_ANGLE_TOL)
            breaks = [k - 1 if abs(turns[(k + 1) % count] - turns[k]) <= ARC_ANGLE_TOL else k]
        start = breaks[0]

    arcs = []
    seg = 0     # segments are counted from `start`
    while seg < seg_count:
        first = (start + seg) % count
        end_seg = seg
        while end_seg + 1 < seg_count:
            k = (start + end_seg + 1) % count   # the vertex between segment end_seg and end_seg + 1
            if not (inner_ok(k) and _close(lengths[k % seg_count], lengths[first % seg_count], ARC_LEN_TOL) and
                    abs(turns[k] - turns[(first + 1) % count]) <= ARC_ANGLE_TOL):
                break
            end_seg += 1
        size = end_seg - seg + 1
        if size >= ARC_MIN_SEGMENTS:
            last = (start + end_seg + 1) % count
            inner = vertices[(first + size // 2) % count]
            arcs.append(Arc(first, last, arc_middle(vertices[first], inner, vertices[last]), False))
            seg = end_seg + 1
        else:
            seg += 1    # a short run: its second segment can still start an arc
    return sorted(arcs)


def ring_skeleton(vertices, closed):
    """(nodes, links): nodes are the vertex indexes outside the arcs, in ring order; links[i] joins nodes[i] to the
    next node and is None (1 straight segment) or the middle point of the arc. A full circle gives ([], [])."""
    arcs = find_arcs(vertices, closed)
    if arcs and arcs[0].full:
        return [], []
    by_start = {arc.start: arc for arc in arcs}
    count = len(vertices)
    inside = set()
    for arc in arcs:
        k = (arc.start + 1) % count
        while k != arc.end:
            inside.add(k)
            k = (k + 1) % count
    first = next(k for k in range(count) if k not in inside)
    nodes, links = [], []
    k = first
    while True:
        nodes.append(k)
        if not closed and k == count - 1:
            return nodes, links
        arc = by_start.get(k)
        nxt = arc.end if arc else (k + 1) % count
        links.append(arc.middle if arc else None)
        if nxt == first:
            return nodes, links
        k = nxt


def expand_skeleton(points, links, closed, steps):
    """The coordinate list of a ring from its node points and links (closing coordinate added if closed)."""
    coords = [tuple(points[0])]
    for i, middle in enumerate(links):
        nxt = points[(i + 1) % len(points)]
        if middle is None:
            coords.append(tuple(nxt))
        else:
            coords.extend(arc_points(points[i], middle, nxt, steps)[1:])
    if closed and coords[-1] != coords[0]:
        coords.append(coords[0])
    return coords


def vertex_grips(geom):
    """[(kind, address, (x, y))]. Outside the arcs: 1 'vertex' grip for each vertex and 1 'mid' grip for each
    segment. An arc: 'arc_end' grips on its 2 end vertices and 1 'arc_mid' grip at its middle point, with the
    address (part, ring, start, end). A full circle: 4 'radius' grips at 0, 90, 180 and 270 degrees."""
    grips = []
    for part_nr, part in enumerate(parts_of(geom)):
        for ring_nr, ring in enumerate(rings_of(part)):
            coords = [tuple(coord[:2]) for coord in ring.coords]
            closed = len(coords) > 1 and coords[0] == coords[-1]
            vertices = coords[:-1] if closed else coords
            nodes, links = ring_skeleton(vertices, closed)
            if not nodes:
                count = len(vertices)
                center = circle_center(vertices[0], vertices[count // 3], vertices[2 * count // 3])
                radius = math.dist(center, vertices[0])
                grips.extend(('radius', (part_nr, ring_nr, 0), (center[0] + radius * dx, center[1] + radius * dy))
                             for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)))
                continue
            arc_ends = set()
            for i, middle in enumerate(links):
                if middle is not None:
                    arc_ends.update((nodes[i], nodes[(i + 1) % len(nodes)]))
            grips.extend(('arc_end' if node in arc_ends else 'vertex', (part_nr, ring_nr, node), vertices[node])
                         for node in nodes)
            for i, middle in enumerate(links):
                a, b = nodes[i], nodes[(i + 1) % len(nodes)]
                if middle is None:
                    pa, pb = vertices[a], vertices[b]
                    grips.append(('mid', (part_nr, ring_nr, a), ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)))
                else:
                    grips.append(('arc_mid', (part_nr, ring_nr, a, b), middle))
    return grips


def vertex_address(geom, index):
    """A plain index edits a single contour; multipart shapes need a (part, ring, index) address."""
    if isinstance(index, tuple):
        return index
    if isinstance(geom, (MultiLineString, MultiPolygon)):
        raise ValueError(_("A plain vertex index edits one LineString, LinearRing or polygon exterior.\n"
                           "Multipart shapes need a part and a ring index."))
    return 0, 0, index


VERTEX_ACTIONS = ('move', 'insert', 'remove')
ARC_ACTIONS = ('arc_end', 'arc_mid', 'arc_flatten', 'arc_radius')


def _arc_ring_edit(vertices, closed, action, address, point, steps):
    """The coordinate list of 1 ring after an arc edit (closing coordinate added if closed)."""
    if action == 'arc_radius':
        arcs = find_arcs(vertices, closed)
        if not arcs or not arcs[0].full:
            raise ValueError(_("The ring is not a full circle."))
        count = len(vertices)
        center = circle_center(vertices[0], vertices[count // 3], vertices[2 * count // 3])
        scale = math.dist(center, point) / math.dist(center, vertices[0])
        coords = [(center[0] + (x - center[0]) * scale, center[1] + (y - center[1]) * scale) for x, y in vertices]
        return coords + [coords[0]]
    nodes, links = ring_skeleton(vertices, closed)
    points = [vertices[node] for node in nodes]
    if action == 'arc_end':
        index = address[2] % len(vertices)
        i = nodes.index(index) if index in nodes else -1
        # the incoming link (i - 1 is the last link of a closed ring for i == 0) and the outgoing link
        touching = [links[j] for j in (i - 1, i) if (closed or j >= 0) and j < len(links)] if i >= 0 else []
        if all(link is None for link in touching):
            raise ValueError(_("The vertex does not end an arc."))
        points[i] = point
    else:
        start, end = address[2], address[3]
        i = nodes.index(start) if start in nodes else -1
        if i < 0 or i >= len(links) or links[i] is None or nodes[(i + 1) % len(nodes)] != end:
            raise ValueError(_("Choose a valid arc."))
        links[i] = None if action == 'arc_flatten' else point
    return expand_skeleton(points, links, closed, steps)


def ring_after_edit(geom, action, address, point=None, on_segment=False, steps=DEFAULT_CIRCLE_STEPS):
    """The full coordinate list of the edited ring. Checks the input, not the result (the preview draws it)."""
    if action not in VERTEX_ACTIONS + ARC_ACTIONS:
        raise ValueError(_("Choose move, insert or remove."))
    if not isinstance(geom, SUPPORTED_TYPES) or geom.is_empty:
        raise ValueError(_("Vertex editing supports LineString, LinearRing, Polygon and their multipart shapes."))
    if geom.has_z:
        raise ValueError(_("Vertex editing supports two-dimensional coordinates only."))
    size = 4 if action in ('arc_mid', 'arc_flatten') else 3
    if len(address) != size or any(type(value) is not int for value in address):
        raise ValueError(_("Choose a valid vertex index."))
    part_nr, ring_nr, index = address[:3]
    parts = parts_of(geom)
    if not 0 <= part_nr < len(parts):
        raise ValueError(_("Choose a valid part index."))
    rings = rings_of(parts[part_nr])
    if not 0 <= ring_nr < len(rings):
        raise ValueError(_("Choose a valid ring index."))
    coords = [tuple(coord) for coord in rings[ring_nr].coords]
    if not 0 <= index < len(coords):
        raise ValueError(_("Choose a valid vertex index."))
    closed = coords[0] == coords[-1]
    if action not in ('remove', 'arc_flatten'):
        if point is None or len(point) != 2:
            raise ValueError(_("Enter numeric X and Y coordinates."))
        point = tuple(float(value) for value in point)
        if not all(math.isfinite(value) for value in point):
            raise ValueError(_("Coordinates must be finite numbers."))
    if action in ARC_ACTIONS:
        return _arc_ring_edit(coords[:-1] if closed else coords, closed, action, address, point, steps)
    if action == 'insert':
        if index >= len(coords) - 1:
            raise ValueError(_("Choose a segment start index, not the final vertex."))
        if on_segment:
            segment = LineString(coords[index:index + 2])
            candidate = Point(point)
            if (point in coords[index:index + 2] or
                    not 0 < segment.project(candidate) < segment.length or
                    segment.distance(candidate) > 1e-9 * max(1.0, segment.length)):
                raise ValueError(_("The new vertex must lie inside the chosen segment."))
    if closed:
        coords.pop()
        if index == len(coords):
            index = 0  # the duplicated closing coordinate is the first vertex
    if action == 'remove':
        if len(coords) <= (3 if closed else 2):
            raise ValueError(_("Removal would leave too few vertices for a valid contour."))
        del coords[index]
    elif action == 'insert':
        coords.insert(index + 1, point)
    else:
        coords[index] = point
    if closed:
        coords.append(coords[0])
    return coords


def edit_vertex(geom, action, address, point=None, on_segment=False, steps=DEFAULT_CIRCLE_STEPS):
    """The new geometry, same type, with only the addressed ring changed."""
    coords = ring_after_edit(geom, action, address, point, on_segment, steps)
    if any(a == b for a, b in zip(coords, coords[1:])):
        raise ValueError(_("The edit would create a zero-length segment."))
    part_nr, ring_nr = address[:2]
    parts = parts_of(geom)
    part = parts[part_nr]
    if isinstance(part, Polygon):
        rings = [list(ring.coords) for ring in rings_of(part)]
        rings[ring_nr] = coords
        new_part = Polygon(rings[0], rings[1:])
    else:
        new_part = type(part)(coords)
    if isinstance(geom, (MultiLineString, MultiPolygon)):
        parts[part_nr] = new_part
        return type(geom)(parts)
    return new_part


def check_vertex_result(geom, address):
    """Raise ValueError if the edited part or ring is not valid. The other parts are not checked."""
    part_nr, ring_nr = address[:2]
    part = parts_of(geom)[part_nr]
    ring = LineString(rings_of(part)[ring_nr].coords)
    coords = list(ring.coords)
    if (geom.is_empty or not part.is_valid or not ring.is_simple or
            (coords[0] == coords[-1] and not Polygon(coords).is_valid) or
            (isinstance(geom, MultiPolygon) and not geom.is_valid)):
        raise ValueError(_("The edit would create invalid geometry."))


def _rgb(color):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def contrast_color(preferred, used_colors):
    """preferred ('#RRGGBBAA'), or its opposite color if it is too near one of used_colors."""
    rgb = _rgb(preferred)
    for used in used_colors:
        try:
            near = math.dist(rgb, _rgb(used)) < COLOR_CLASH_DIST
        except (AttributeError, TypeError, ValueError):
            continue
        if near:
            return '#%02X%02X%02X%s' % (255 - rgb[0], 255 - rgb[1], 255 - rgb[2], preferred[7:9])
    return preferred
