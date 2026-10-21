# Arc Grips and Grid Pick for Vertex Dragging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The vertex grips show 1 arc (begin, middle, end) for a rounded corner or any other arc, not its many short
segments. With the grid on, a press takes the nearest grip within 1 grid step.

**Architecture:** Pure functions in `appEditors/vertex_ops.py` find the arcs from the coordinates and build a
"skeleton" of each ring: the vertices outside the arcs (nodes) and, between 2 nodes, a straight segment or an arc
(its middle point). Arc edits change the skeleton and expand it again to coordinates. `apply_vertex_edit` gets the
new actions, so the history and the result check stay the same. `VertexGrips` maps the new grip kinds to the new
actions and changes the hit test.

**Tech Stack:** Python 3.11+, PyQt6, Shapely 2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-vertex-drag-arcs-design.md`

---

## Rules for the worker

- Run Python only with the venv, from PowerShell: `.venv\Scripts\python.exe -m pytest ...`. Git Bash cannot start
  the venv Python, and the system Python has no `rasterio`.
- **Do not commit.** The files hold other uncommitted work of the user. The user commits at the end.
- Do not add mixins. Do not add `Co-Authored-By` lines anywhere.
- Run only the tests that each task names. The full suite is slow.
- Do not pipe a heredoc into `python -`. It hangs. Write a script file if you need one.

## Deviations from the spec (decided while planning)

1. Grip kinds: the begin and end vertices of an arc have the kind `'arc_end'` (drawn as the normal filled square),
   not `'vertex'`. So `VertexGrips` knows that a drag of that vertex must recalculate the arc.
2. Actions: not 1 action `'arc'`, but 4 actions: `'arc_end'` (address `(part, ring, index)`), `'arc_mid'` and
   `'arc_flatten'` (address `(part, ring, start, end)`), `'arc_radius'` (address `(part, ring, 0)`).
3. `find_arcs` returns `Arc(start, end, middle, full)`. `middle` is the point at the half angle of the arc. The
   center and the radius are not stored; `circle_center` gives them when needed.
4. A new arc gets `max(3, round(steps * sweep / 360), ceil(sweep / 30 degrees))` segments, not
   `max(2, round(steps * sweep / 360))`. With fewer than 3 segments, or with a turn larger than `ARC_MAX_TURN` at a
   vertex, `find_arcs` does not find the arc again after the edit.
5. `ARC_MAX_TURN = 30` degrees: a larger turn at a vertex is a corner. Without this limit, a square or a hexagon is
   a full circle.
6. The radius drag scales the ring around the center. It keeps the vertex count.

## File map

| File | Status | Responsibility |
|---|---|---|
| `appEditors/vertex_ops.py` | modify | arc detection, skeleton, arc edits, grips with arcs |
| `appEditors/vertex_grips.py` | modify | grip kinds to actions, diamond grips, grid pick, circle steps |
| `appEditors/appGeoEditor.py` | modify | `apply_vertex_edit` passes the circle steps |
| `tests/test_vertex_ops.py` | modify | arc detection and arc edit tests |
| `tests/test_vertex_grips.py` | modify | arc grips, grid pick |
| `tests/test_geo_editor_vertex_drag.py` | modify | arc edit through the real editor and history |
| `CHANGELOG.md` | modify | 2 lines in the "Geometry Editor - vertex grips" section |

Order: Task 1, then Task 2. Tasks 3 and 4 can run at the same time (different files). Task 5 is last.

---

### Task 1: Arc detection and skeleton in `vertex_ops.py`

**Files:**
- Modify: `appEditors/vertex_ops.py` (new constants and functions only; no existing function changes)
- Test: `tests/test_vertex_ops.py` (append)

- [ ] **Step 1: Write the failing tests**

Change the import block at the top of `tests/test_vertex_ops.py` to:

```python
"""Pure vertex edits addressed as (part, ring, index). No Qt."""
import math

import pytest
from shapely import BufferJoinStyle
from shapely.geometry import LineString, LinearRing, Point, Polygon, MultiLineString, MultiPolygon, box

from appEditors.vertex_ops import (vertex_grips, vertex_address, ring_after_edit, edit_vertex, check_vertex_result,
                                   contrast_color, circle_center, arc_middle, arc_points, find_arcs, ring_skeleton,
                                   expand_skeleton)
```

Append to the end of `tests/test_vertex_ops.py`:

```python
ROUNDED = box(1, 1, 9, 5).buffer(1, join_style=BufferJoinStyle.round)   # 4 corner arcs of radius 1
CORNERS = [(1, 1), (9, 1), (9, 5), (1, 5)]


def ring_vertices(ring):
    coords = [tuple(coord) for coord in ring.coords]
    return coords[:-1] if coords[0] == coords[-1] else coords


def s_curve():
    """An open line: 1 straight segment, 2 quarter arcs that share the vertex (1, 1), 1 straight segment."""
    half = math.sqrt(0.5)
    first = arc_points((0, 0), (1 - half, half), (1, 1), 64)
    second = arc_points((1, 1), (1 + half, 2 - half), (2, 2), 64)
    return [(-3, 0)] + first + second[1:] + [(2, 5)]


def test_circle_center_and_collinear_points():
    assert circle_center((1, 0), (0, 1), (-1, 0)) == pytest.approx((0, 0))
    assert circle_center((0, 0), (1, 0), (2, 0)) is None


def test_arc_middle_is_at_the_half_angle():
    through = (math.cos(0.3), math.sin(0.3))
    assert arc_middle((1, 0), through, (0, 1)) == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
    assert arc_middle((0, 0), (1, 0), (2, 0)) == (1, 0)   # on 1 line: the middle of the segment


def test_arc_points_follow_the_circle_steps():
    points = arc_points((1, 0), (math.sqrt(0.5), math.sqrt(0.5)), (0, 1), 32)
    assert len(points) == 9   # a quarter of 32 steps
    assert points[0] == (1, 0) and points[-1] == (0, 1)
    assert all(math.dist(point, (0, 0)) == pytest.approx(1) for point in points)
    assert len(arc_points((1, 0), (math.cos(0.05), math.sin(0.05)), (math.cos(0.1), math.sin(0.1)), 32)) == 4
    assert len(arc_points((1, 0), (0, 1), (-1, 0), 4)) == 7   # 4 steps: 2 segments, but at most 30 degrees each
    assert arc_points((0, 0), (1, 0), (2, 0), 32) == [(0, 0), (2, 0)]


def test_find_arcs_rounded_rectangle_has_4_corner_arcs():
    vertices = ring_vertices(ROUNDED.exterior)
    arcs = find_arcs(vertices, True)
    assert len(arcs) == 4 and not any(arc.full for arc in arcs)
    for arc in arcs:
        center = circle_center(vertices[arc.start], arc.middle, vertices[arc.end])
        assert math.dist(center, vertices[arc.start]) == pytest.approx(1)
        assert min(math.dist(center, corner) for corner in CORNERS) == pytest.approx(0, abs=1e-9)


def test_find_arcs_line_buffer_has_2_end_arcs():
    assert len(find_arcs(ring_vertices(LineString([(0, 0), (10, 0)]).buffer(1).exterior), True)) == 2


def test_find_arcs_full_circle():
    arcs = find_arcs(ring_vertices(Point(0, 0).buffer(2).exterior), True)
    assert len(arcs) == 1 and arcs[0].full


def test_find_arcs_arc_across_the_ring_start():
    vertices = ring_vertices(ROUNDED.exterior)
    first = find_arcs(vertices, True)[0]
    middle = (first.start + first.end) // 2
    rotated = vertices[middle:] + vertices[:middle]   # vertex 0 is now inside an arc
    arcs = find_arcs(rotated, True)
    assert len(arcs) == 4
    assert sum(1 for arc in arcs if arc.end < arc.start) == 1


def test_find_arcs_s_curve_arcs_share_a_vertex():
    vertices = s_curve()
    arcs = find_arcs(vertices, False)
    assert len(arcs) == 2
    assert arcs[0].end == arcs[1].start
    assert vertices[arcs[0].end] == (1, 1)


@pytest.mark.parametrize('vertices,closed', [
    ([(0, 0), (1, 0), (1, 1), (0, 1)], True),                       # a square: 90 degree corners
    ([(0, 0), (4, 0), (5, 2), (3, 5), (0, 3)], True),               # a plain polygon
    ([(0, 0), (1, 0), (1.99, 0.14)], False),                        # only 2 equal segments
    ([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)], False),              # a straight run of equal segments
])
def test_find_arcs_finds_no_arc(vertices, closed):
    assert find_arcs(vertices, closed) == []


def test_skeleton_round_trip_of_a_rounded_rectangle():
    vertices = ring_vertices(ROUNDED.exterior)
    nodes, links = ring_skeleton(vertices, True)
    assert len(nodes) == 8 and len(links) == 8
    assert sum(1 for link in links if link is not None) == 4
    rebuilt = expand_skeleton([vertices[node] for node in nodes], links, True, 64)
    assert rebuilt[0] == rebuilt[-1]
    assert Polygon(rebuilt).symmetric_difference(ROUNDED).area < 1e-9


def test_skeleton_of_an_open_s_curve_and_of_a_full_circle():
    vertices = s_curve()
    nodes, links = ring_skeleton(vertices, False)
    assert nodes == [0, 1, 17, 33, 34]
    assert [link is None for link in links] == [True, False, False, True]
    assert ring_skeleton(ring_vertices(Point(0, 0).buffer(2).exterior), True) == ([], [])
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py -q`
Expected: the collection fails with `ImportError: cannot import name 'circle_center'`.

- [ ] **Step 3: Write the code**

In `appEditors/vertex_ops.py`, change the import line `import math` block to add `namedtuple`:

```python
import math
import gettext
import builtins
from collections import namedtuple
```

After the line `COLOR_CLASH_DIST = 100`, add:

```python
ARC_LEN_TOL = 0.02                  # relative difference of 2 segment lengths in 1 arc
ARC_ANGLE_TOL = 0.02                # radians: difference of 2 turn angles in 1 arc
ARC_MAX_TURN = math.radians(30)     # a larger turn at a vertex is a corner, not an arc (a square is not a circle)
ARC_MIN_SEGMENTS = 3
DEFAULT_CIRCLE_STEPS = 32           # the factory value of geometry_circle_steps

Arc = namedtuple('Arc', 'start end middle full')
```

After the function `rings_of`, add:

```python
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
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py -q`
Expected: all pass (the 30 old tests and the new ones).

---

### Task 2: Arc grips and arc edits in `vertex_ops.py`

**Files:**
- Modify: `appEditors/vertex_ops.py` (`vertex_grips`, `ring_after_edit`, `edit_vertex`, `check_vertex_result`, the
  module docstring; new function `_arc_ring_edit`)
- Test: `tests/test_vertex_ops.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/test_vertex_ops.py`:

```python
def grips_of(geometry, kind):
    return [(address, point) for k, address, point in vertex_grips(geometry) if k == kind]


def on_some_arc(ring, point, closed=True):
    """True if point is on the circle of 1 of the arcs of ring. A point on the circle is not always on the chords."""
    vertices = ring_vertices(ring)
    for arc in find_arcs(vertices, closed):
        center = circle_center(vertices[arc.start], arc.middle, vertices[arc.end])
        if abs(math.dist(center, point) - math.dist(center, vertices[arc.start])) < 1e-9:
            return True
    return False


def test_grips_of_a_rounded_rectangle():
    assert len(grips_of(ROUNDED, 'arc_end')) == 8
    assert grips_of(ROUNDED, 'vertex') == []
    assert len(grips_of(ROUNDED, 'mid')) == 4
    arc_mids = grips_of(ROUNDED, 'arc_mid')
    assert len(arc_mids) == 4 and all(len(address) == 4 for address, __ in arc_mids)
    assert all(on_some_arc(ROUNDED.exterior, point) for __, point in arc_mids)


def test_grips_of_a_full_circle():
    radius_grips = grips_of(Point(0, 0).buffer(2), 'radius')
    assert [address for address, __ in radius_grips] == [(0, 0, 0)] * 4
    assert [value for __, point in radius_grips for value in point] == pytest.approx([2, 0, 0, 2, -2, 0, 0, -2])
    assert len(vertex_grips(Point(0, 0).buffer(2))) == 4


def test_arc_mid_bends_the_arc_through_the_cursor():
    address, middle = grips_of(ROUNDED, 'arc_mid')[0]
    cursor = (middle[0] - 0.3, middle[1] - 0.3)
    result = edit_vertex(ROUNDED, 'arc_mid', address, cursor, steps=64)
    check_vertex_result(result, address)
    assert on_some_arc(result.exterior, cursor)
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 4


def test_arc_end_moves_the_end_and_keeps_the_middle():
    (address, point), = [(a, p) for a, p in grips_of(ROUNDED, 'arc_end') if p == (1.0, 0.0)]
    middle = arc_middle((1, 0), (1 - math.sqrt(0.5), 1 - math.sqrt(0.5)), (0, 1))
    result = edit_vertex(ROUNDED, 'arc_end', address, (1.3, 0), steps=64)
    check_vertex_result(result, address)
    assert (1.3, 0) in list(result.exterior.coords)
    assert on_some_arc(result.exterior, middle)
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 4


def test_arc_end_on_a_shared_vertex_changes_both_arcs():
    line = LineString(s_curve())
    result = edit_vertex(line, 'arc_end', (0, 0, 17), (1.2, 1), steps=64)
    arcs = find_arcs(list(result.coords), False)
    assert len(arcs) == 2 and arcs[0].end == arcs[1].start
    assert result.coords[arcs[0].end] == (1.2, 1)


def test_arc_flatten_makes_a_straight_segment():
    address, __ = grips_of(ROUNDED, 'arc_mid')[0]
    vertices = ring_vertices(ROUNDED.exterior)
    begin, end = vertices[address[2]], vertices[address[3]]
    result = edit_vertex(ROUNDED, 'arc_flatten', address)
    coords = list(result.exterior.coords)
    assert any(pair in ((begin, end), (end, begin)) for pair in zip(coords, coords[1:]))
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 3


def test_arc_mid_on_the_chord_makes_a_straight_segment():
    address, __ = grips_of(ROUNDED, 'arc_mid')[0]
    vertices = ring_vertices(ROUNDED.exterior)
    begin, end = vertices[address[2]], vertices[address[3]]
    chord_middle = ((begin[0] + end[0]) / 2, (begin[1] + end[1]) / 2)
    result = edit_vertex(ROUNDED, 'arc_mid', address, chord_middle, steps=64)
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 3


def test_arc_radius_scales_a_full_circle():
    circle = Point(1, 1).buffer(2)
    result = edit_vertex(circle, 'arc_radius', (0, 0, 0), (4, 1))
    assert len(result.exterior.coords) == len(circle.exterior.coords)
    assert all(math.dist(coord, (1, 1)) == pytest.approx(3) for coord in result.exterior.coords)


@pytest.mark.parametrize('geometry,action,address,point', [
    (box(0, 0, 4, 4), 'arc_end', (0, 0, 1), (5, 0)),               # not the end of an arc
    (ROUNDED, 'arc_mid', (0, 0, 1, 2), (0, 0)),                     # not an arc
    (ROUNDED, 'arc_mid', (0, 0, 1), (0, 0)),                        # an arc address has 4 values
    (box(0, 0, 4, 4), 'arc_radius', (0, 0, 0), (5, 0)),             # not a full circle
    (ROUNDED, 'arc_mid', (0, 0, 1, 17), None),                      # no point
])
def test_bad_arc_edits_raise(geometry, action, address, point):
    with pytest.raises(ValueError):
        edit_vertex(geometry, action, address, point)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py -q`
Expected: the new tests fail (`edit_vertex() got an unexpected keyword argument 'steps'`, wrong grip kinds).

- [ ] **Step 3: Change the module docstring**

Replace the module docstring at the top of `appEditors/vertex_ops.py` with:

```python
"""
Vertex edits on Shapely geometry, addressed as (part, ring, index).

No Qt and no editor code: the Geometry Editor uses these functions now, the Gerber Editor later.
part: 0 for a single geometry, else the index in .geoms. ring: 0 for a line or a polygon exterior, 1+ for the holes.
index: the vertex in the full coordinate list of the ring; the closing coordinate of a closed ring is an alias of 0.
Arcs are found from the coordinates (find_arcs). An arc is addressed as (part, ring, start, end): its end vertices.
"""
```

- [ ] **Step 4: Replace `vertex_grips`**

```python
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
```

- [ ] **Step 5: Add `_arc_ring_edit` and change `ring_after_edit`**

Before `def ring_after_edit`, add:

```python
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
```

In `ring_after_edit`, change the signature, the action check, the address check and the point check, and send
the arc actions to `_arc_ring_edit`. The new start of the function, down to the `if action == 'insert':` line, is:

```python
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
```

The rest of `ring_after_edit` (from `if action == 'insert':` to the end) does not change.

- [ ] **Step 6: Change `edit_vertex` and `check_vertex_result`**

In `edit_vertex`, change the signature, the call and the address unpack:

```python
def edit_vertex(geom, action, address, point=None, on_segment=False, steps=DEFAULT_CIRCLE_STEPS):
    """The new geometry, same type, with only the addressed ring changed."""
    coords = ring_after_edit(geom, action, address, point, on_segment, steps)
    if any(a == b for a, b in zip(coords, coords[1:])):
        raise ValueError(_("The edit would create a zero-length segment."))
    part_nr, ring_nr = address[:2]
```

The rest of `edit_vertex` does not change.

In `check_vertex_result`, replace the line `part_nr, ring_nr, __ = address` with:

```python
    part_nr, ring_nr = address[:2]
```

- [ ] **Step 7: Run the tests and see them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py tests/test_vertex_grips.py tests/test_geo_editor_vertex_drag.py tests/test_geo_editor_vertices.py -q`
Expected: all pass. The old tests of the other 3 files must still pass: their shapes have no arcs.

---

### Task 3: `apply_vertex_edit` passes the circle steps

**Files:**
- Modify: `appEditors/appGeoEditor.py` (the `vertex_ops` import near line 41, `apply_vertex_edit` near line 985)
- Test: `tests/test_geo_editor_vertex_drag.py` (append)

This task can run at the same time as Task 4. Do not touch `appEditors/vertex_grips.py` or
`tests/test_vertex_grips.py`.

- [ ] **Step 1: Write the failing test**

In `tests/test_geo_editor_vertex_drag.py`, add `import math` before `from types import SimpleNamespace`, and change
the shapely imports to:

```python
from shapely import BufferJoinStyle
from shapely.geometry import MultiPolygon, Polygon, box
```

Append to the end of the file:

```python
ROUNDED = box(1, 1, 9, 5).buffer(1, join_style=BufferJoinStyle.round)


def on_some_arc(ring, point):
    """True if point is on the circle of 1 of the arcs of the closed ring."""
    from appEditors.vertex_ops import circle_center, find_arcs
    vertices = list(ring.coords)[:-1]
    for arc in find_arcs(vertices, True):
        center = circle_center(vertices[arc.start], arc.middle, vertices[arc.end])
        if abs(math.dist(center, point) - math.dist(center, vertices[arc.start])) < 1e-9:
            return True
    return False


def test_arc_bend_is_one_undo_step_and_uses_the_circle_steps():
    from appEditors.vertex_ops import vertex_grips
    editor, original = vertex_editor(ROUNDED)
    editor.app.options['geometry_circle_steps'] = 8
    kind, address, middle = next(grip for grip in vertex_grips(ROUNDED) if grip[0] == 'arc_mid')
    cursor = (middle[0] - 0.2, middle[1] - 0.2)
    assert editor.apply_vertex_edit('arc_mid', address, cursor, on_segment=False) != 'fail'
    result = editor.selected[0].geo
    assert on_some_arc(result.exterior, cursor)
    assert len(result.exterior.coords) < len(ROUNDED.exterior.coords)   # 8 steps: the bent arc has few segments
    assert len(editor._history_undo) == 1
    assert editor.undo()
    assert editor.selected == [original]
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py -q -k arc_bend`
Expected: FAIL on the coordinate count (the default 32 steps give more segments than 8 steps).

- [ ] **Step 3: Write the code**

In `appEditors/appGeoEditor.py`, add `DEFAULT_CIRCLE_STEPS` to the `from appEditors.vertex_ops import (...)` list.

In `apply_vertex_edit`, replace the line

```python
            result_geo = edit_vertex(geometry, action, address, point, on_segment=on_segment)
```

with

```python
            steps = self.app.options.get('geometry_circle_steps', DEFAULT_CIRCLE_STEPS)
            result_geo = edit_vertex(geometry, action, address, point, on_segment=on_segment, steps=steps)
```

Change the docstring of `apply_vertex_edit` to:

```python
        """
        Validate a complete replacement before touching storage or recording history.

        :param action:      'move', 'insert', 'remove' or an arc action of vertex_ops.ARC_ACTIONS
        :param index:       a vertex index of a single contour, or a (part, ring, index) / (part, ring, start, end)
                            address
        :param on_segment:  True (the dialog): an inserted vertex must lie inside the chosen segment
        """
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py tests/test_geo_editor_vertices.py -q`
Expected: all pass.

---

### Task 4: `VertexGrips`: arc grips and the grid pick

**Files:**
- Modify: `appEditors/vertex_grips.py`
- Test: `tests/test_vertex_grips.py` (append)

This task can run at the same time as Task 3. Do not touch `appEditors/appGeoEditor.py` or
`tests/test_geo_editor_vertex_drag.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_vertex_grips.py`, change the shapely import to:

```python
from shapely import BufferJoinStyle
from shapely.geometry import LineString, MultiPolygon, Point, box
```

Append to the end of the file:

```python
ROUNDED = box(1, 1, 9, 5).buffer(1, join_style=BufferJoinStyle.round)


def grip_of(grips, kind):
    return next(grip for grip in grips.grips if grip[0] == kind)


def test_arc_grips_replace_the_inner_vertex_grips():
    grips, editor, shape = make_grips(ROUNDED)
    kinds = [grip[0] for grip in grips.grips]
    assert kinds.count('arc_end') == 8 and kinds.count('arc_mid') == 4 and kinds.count('mid') == 4
    assert len(grips.collection().items) == 16


def test_drag_of_an_arc_middle_bends_the_arc():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, middle = grip_of(grips, 'arc_mid')
    cursor = (middle[0] - 0.2, middle[1] - 0.2)
    assert drag(grips, middle, cursor)
    editor.apply_vertex_edit.assert_called_once_with('arc_mid', address, cursor, target=shape, on_segment=False)


def test_drag_of_an_arc_end_moves_the_end():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, point = grip_of(grips, 'arc_end')
    cursor = (point[0] + 0.25, point[1] - 0.25)
    assert drag(grips, point, cursor)
    editor.apply_vertex_edit.assert_called_once_with('arc_end', address, cursor, target=shape, on_segment=False)


def test_ctrl_click_on_an_arc_middle_flattens_the_arc():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, middle = grip_of(grips, 'arc_mid')
    assert grips.press((0, 0), middle, CTRL)
    assert grips.release((0, 0), middle)
    editor.apply_vertex_edit.assert_called_once_with('arc_flatten', address, target=shape)


def test_ctrl_click_on_an_arc_end_removes_the_vertex():
    grips, editor, shape = make_grips(ROUNDED)
    kind, address, point = grip_of(grips, 'arc_end')
    assert grips.press((0, 0), point, CTRL)
    assert grips.release((0, 0), point)
    editor.apply_vertex_edit.assert_called_once_with('remove', address, target=shape)


def test_full_circle_radius_drag():
    grips, editor, shape = make_grips(Point(0, 0).buffer(2))
    assert [grip[0] for grip in grips.grips] == ['radius'] * 4
    kind, address, point = grips.grips[0]
    assert drag(grips, point, (3, 0))
    editor.apply_vertex_edit.assert_called_once_with('arc_radius', address, (3.0, 0.0), target=shape,
                                                     on_segment=False)


def test_ctrl_click_on_a_radius_grip_does_nothing():
    grips, editor, shape = make_grips(Point(0, 0).buffer(2))
    kind, address, point = grips.grips[0]
    assert grips.press((0, 0), point, CTRL)
    assert grips.release((0, 0), point)
    editor.apply_vertex_edit.assert_not_called()


def test_preview_of_an_arc_bend_uses_the_circle_steps():
    grips, editor, shape = make_grips(ROUNDED)
    editor.app.options['geometry_circle_steps'] = 8
    kind, address, middle = grip_of(grips, 'arc_mid')
    assert grips.press((0, 0), middle, NO_MOD)
    grips.move((20, 0), (middle[0] - 0.2, middle[1] - 0.2))
    preview = editor.tool_shape.items[-1][0]
    assert len(preview.coords) < len(ROUNDED.exterior.coords)


def test_grid_on_picks_the_nearest_grip_within_1_grid_step():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=True)
    editor.editor_options = {'global_gridx': 0.5, 'global_gridy': 0.25}
    assert grips.hit((0.3, 0.2)) == ('vertex', (0, 0, 0), (0, 0))  # 0.36 away: outside 6 px, inside 1 grid step
    assert grips.hit((0.5, 1.0)) is None


def test_grid_off_keeps_the_pixel_hit_radius():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=False)
    editor.editor_options = {'global_gridx': 0.5, 'global_gridy': 0.25}
    assert grips.hit((0.3, 0.2)) is None
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_grips.py -q`
Expected: the new tests fail. The tests that need Task 2 (`arc_end`, `arc_mid`, `radius` kinds) fail only if Task 2
is not done; Task 2 must be done before this task.

- [ ] **Step 3: Change the imports and constants**

In `appEditors/vertex_grips.py`, change the imports to:

```python
from PyQt6 import QtCore
import shapely
from shapely import LineString, Polygon, box
from shapely.errors import GEOSException

from appEditors.vertex_ops import SUPPORTED_TYPES, DEFAULT_CIRCLE_STEPS, vertex_grips, ring_after_edit, \
    edit_vertex, check_vertex_result, contrast_color
```

After the line `INVALID_COLOR = '#FF0000FF'`, add:

```python
# the edit action of a drag and of a Ctrl+click, for each grip kind (no entry: the Ctrl+click does nothing)
DRAG_ACTIONS = {'vertex': 'move', 'mid': 'insert', 'arc_end': 'arc_end', 'arc_mid': 'arc_mid',
                'radius': 'arc_radius'}
CLICK_ACTIONS = {'vertex': 'remove', 'arc_end': 'remove', 'arc_mid': 'arc_flatten'}
```

Change the first paragraph of the module docstring to:

```python
"""
Grips on the vertices of 1 selected shape: drag a vertex grip to move the vertex, drag a midpoint grip to insert a
vertex, Ctrl+click a vertex grip to remove the vertex. An arc has 3 grips: drag its middle grip to bend it, drag an
end grip to move that end, Ctrl+click the middle grip to make it a straight segment. A full circle has 4 radius grips.
```

The rest of the docstring does not change.

- [ ] **Step 4: Add `steps` and `grid_step`**

In the class `VertexGrips`, after the method `pixel`, add:

```python
    def steps(self):
        return self.editor.app.options.get('geometry_circle_steps', DEFAULT_CIRCLE_STEPS)

    def grid_step(self):
        """The larger grid gap of the editor, or 0."""
        try:
            options = self.editor.editor_options
            return max(abs(float(options['global_gridx'])), abs(float(options['global_gridy'])))
        except (AttributeError, KeyError, TypeError, ValueError):
            return 0.0
```

- [ ] **Step 5: Change the vertex limit in `show`**

In `show`, replace the line

```python
        if sum(1 for grip in grips if grip[0] == 'vertex') > GRIP_LIMIT:
```

with

```python
        if shapely.get_num_coordinates(geo) > GRIP_LIMIT:
```

and move the line `grips = vertex_grips(geo)` after this check (the arc search is not needed for a shape that
gets no grips). The new middle of `show` is:

```python
        if shapely.get_num_coordinates(geo) > GRIP_LIMIT:
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' %
                                        _("The shape has too many vertices for grips. Use Edit vertices."))
            return
        self.shape, self.grips = shape, vertex_grips(geo)
```

- [ ] **Step 6: Replace `draw`**

```python
    def draw(self):
        collection = self.collection()
        collection.clear(update=False)
        self._pixel = pixel = self.pixel()
        color = self.colors()[0]
        for kind, __, (x, y) in self.grips:
            half = GRIP_SIZE_PX * pixel * (0.6 if kind == 'mid' else 1.0)
            if kind in ('vertex', 'arc_end'):
                square = box(x - half, y - half, x + half, y + half)
                collection.add(shape=square, color=color, face_color=color, update=False, layer=0, tolerance=None)
            elif kind == 'mid':
                square = box(x - half, y - half, x + half, y + half)
                collection.add(shape=square.exterior, color=color, update=False, layer=0, tolerance=None)
            else:
                diamond = Polygon([(x - half, y), (x, y - half), (x + half, y), (x, y + half)])
                if kind == 'radius':
                    collection.add(shape=diamond, color=color, face_color=color, update=False, layer=0,
                                   tolerance=None)
                else:
                    collection.add(shape=diamond.exterior, color=color, update=False, layer=0, tolerance=None)
        collection.redraw()
```

- [ ] **Step 7: Replace `hit`**

```python
    def hit(self, point):
        """(kind, address, grip point) of the grip under point, or None. With the grid on, the pick radius is at
        least 1 grid step. Midpoint grips last, then the nearest grip, then the lower address (2 parts that touch
        at 1 vertex)."""
        radius = GRIP_HIT_PX * self.pixel()
        if self.editor.app.grid_status():
            radius = max(radius, self.grid_step())
        best = None
        for kind, address, grip in self.grips:
            dist = math.dist(point, grip)
            if dist > radius:
                continue
            rank = (kind == 'mid', dist, address)
            if best is None or rank < best[0]:
                best = (rank, kind, address, grip)
        return None if best is None else best[1:]
```

- [ ] **Step 8: Change `target`, `move`, `preview` and `release`**

In `target`, replace

```python
        if kind == 'vertex' and snapped == start and getattr(editor, 'active_snap_type', None) == 'corner':
```

with

```python
        if kind in ('vertex', 'arc_end') and snapped == start and \
                getattr(editor, 'active_snap_type', None) == 'corner':
```

In `move`, replace

```python
        action = 'insert' if kind == 'mid' else 'move'
```

with

```python
        action = DRAG_ACTIONS[kind]
```

In `preview`, replace

```python
            coords = ring_after_edit(geo, action, address, point)
```

with

```python
            coords = ring_after_edit(geo, action, address, point, steps=self.steps())
```

and replace

```python
            check_vertex_result(edit_vertex(geo, action, address, point), address)
```

with

```python
            check_vertex_result(edit_vertex(geo, action, address, point, steps=self.steps()), address)
```

In `release`, replace

```python
            if ctrl and kind == 'vertex':
                self.editor.apply_vertex_edit('remove', address, target=shape)
```

with

```python
            if ctrl and kind in CLICK_ACTIONS:
                self.editor.apply_vertex_edit(CLICK_ACTIONS[kind], address, target=shape)
```

Change the docstring of `release` to:

```python
        """True if a grip took the release. A drag commits; a Ctrl+click removes a vertex or flattens an arc."""
```

- [ ] **Step 9: Run the tests and see them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_grips.py tests/test_vertex_ops.py -q`
Expected: all pass.

---

### Task 5: End-to-end test, changelog and final check

**Files:**
- Modify: `tests/test_geo_editor_vertex_drag.py` (append), `CHANGELOG.md`

- [ ] **Step 1: Write the end-to-end test**

Append to the end of `tests/test_geo_editor_vertex_drag.py` (Task 3 already added `ROUNDED`, `on_some_arc` and
the imports):

```python
def test_arc_middle_drag_through_the_real_editor_is_one_undo_step():
    editor, original = drag_editor(ROUNDED)
    grips = editor.vertex_grips
    kind, address, middle = next(grip for grip in grips.grips if grip[0] == 'arc_mid')
    cursor = (middle[0] - 0.2, middle[1] - 0.2)
    assert grips.press((0, 0), middle, QtCore.Qt.KeyboardModifier.NoModifier)
    grips.move((20, 0), cursor)
    assert grips.release((20, 0), cursor)
    assert on_some_arc(editor.selected[0].geo.exterior, cursor)
    assert len(editor._history_undo) == 1
    assert grips.shape is editor.selected[0]
    assert sum(1 for grip in grips.grips if grip[0] == 'arc_mid') == 4   # the bent corner is still 1 arc
    assert editor.undo()
    assert editor.selected == [original]
```

- [ ] **Step 2: Run the test**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py -q`
Expected: all pass.

- [ ] **Step 3: Add the changelog lines**

In `CHANGELOG.md`, in the section "Geometry Editor - vertex grips:" under `21.10.2026`, add these 2 lines after the
line that starts with `- Edit vertices dialog: new Part and Ring fields`:

```markdown
- rounded corners and other arcs (found from the vertices: at least 3 equal segments with the same turn) show 3 grips: begin, middle (a diamond) and end, and no grips on their inner vertices; drag the middle grip to bend the arc; drag the begin or end grip to move that end (the arc stays through its middle point); Ctrl+click the middle grip to make the arc a straight segment; a full circle shows 4 radius grips; a new arc uses the "Circle steps" of the Geometry preferences; Explode and Edit vertices still use all the vertices
- with the grid on, a press takes the nearest grip within 1 grid step, so a vertex that is not on the grid can be picked with the snapped cursor
```

- [ ] **Step 4: Run the targeted tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py tests/test_vertex_grips.py tests/test_geo_editor_vertex_drag.py tests/test_geo_editor_vertices.py tests/test_geo_editor_improvements.py tests/test_geo_editor_snapping.py tests/test_vispy_only_geo_editor.py tests/test_geo_editor_history.py -q`
Expected: all pass. Report the exact pass count.

- [ ] **Step 5: Report to the user (no commit)**

Report the changed files and the test result. List these manual GUI checks:

1. Draw a rectangle with round corners. Select it. Each corner shows 2 square grips and 1 diamond. No grips show on
   the inner vertices of the corners.
2. Drag a diamond. The corner bends through the cursor. Ctrl+Z gives the old corner.
3. Drag a square grip at the end of a corner arc. The end moves and the arc follows.
4. Ctrl+click a diamond. The corner becomes a straight segment.
5. Draw a circle. Select it. 4 filled diamonds show. Drag 1 of them. The radius changes.
6. Explode the rounded rectangle. The result has all the short segments.
7. Turn the grid on with a large gap (for example 1 mm). Aim the cursor marker at a vertex that is not on the grid.
   Press and drag. The vertex moves.
