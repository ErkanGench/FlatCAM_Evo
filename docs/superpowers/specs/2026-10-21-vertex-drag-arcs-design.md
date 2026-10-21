# Arc Grips and Grid Pick for Vertex Dragging — Design

**Date:** 2026-10-21
**Builds on:** `docs/superpowers/specs/2026-10-21-vertex-drag-design.md` (vertex grips, done, not committed)

## Problem

1. A rounded corner (for example the Rectangle tool with round corners, `GeoRectanglePlugin.py`, a `buffer` with
   `JOIN_STYLE.round`) is many short segments in storage. The Select tool shows 1 grip for each of these vertices and
   1 midpoint grip for each segment. The user must see and drag 1 arc, not many segments.
2. With the grid on, the cursor marker sits on a grid point. A vertex that is not on the grid can be outside the hit
   radius of the raw cursor when the user aims the marker at it.

## Decisions

- The editor finds the arcs from the coordinates. Nothing goes into storage. This works for every shape (editor
  tools, buffers, DXF, SVG and Gerber imports) and after move, rotate and scale.
- An arc drag is a 3-point arc: begin, middle, end.
- Explode and the Edit vertices dialog do not change. They still work on the real vertices.

## 1. Arc detection

New function `vertex_ops.find_arcs(coords, closed)` (no Qt, no editor).

- Input: the 2D coordinates of 1 ring or 1 line. For a closed ring, the last point (equal to the first) is not in
  the list.
- An arc is a run of consecutive vertices where:
  - all segment lengths are equal within a relative tolerance (`ARC_LEN_TOL = 0.02`, 2 %), and
  - the turn angle at each inner vertex is the same within `ARC_ANGLE_TOL = 0.02` rad, has the same sign, and is
    not 0 (a straight run is not an arc).
- A run must have at least `ARC_MIN_SEGMENTS = 3` segments. Shorter runs stay plain vertices.
- The center and the radius come from the circle through the begin vertex, the vertex at index
  `start + (count // 2)` and the end vertex of the run. The middle point of the arc is the point on the circle at
  the half angle of the arc (it is not always a vertex).
- 2 arcs can share a vertex (an S-curve): the end of 1 arc is the begin of the next.
- In a closed ring, a run that crosses the start point of the ring is 1 arc.
- If all the vertices of a closed ring are 1 run, the ring is a full circle.
- Result: a list of `Arc(start, end, center, radius, full)` for the ring. `start` and `end` are vertex indexes. For
  a run across the ring start, `end < start`.

## 2. Grips

`vertex_ops.vertex_grips(geom)` uses `find_arcs` on each ring.

- Outside the arcs, the grips do not change: 1 `vertex` grip for each vertex and 1 `mid` grip for each segment.
- An arc gives:
  - its begin and end vertices as normal `vertex` grips (they are real vertices that the straight segments share),
  - 1 `arc_mid` grip at the middle point of the arc, drawn with a different form (a diamond) in the same color.
- The vertices inside an arc get no grips. The segments inside an arc get no `mid` grips.
- A full circle gives 4 `radius` grips at 0, 90, 180 and 270 degrees from the center, and no other grips.
- The address of an arc grip is `(part, ring, start, end)`. Vertex grips keep `(part, ring, index)`.

## 3. Drag

All arc edits use the same path as vertex edits: `AppGeoEditor.apply_vertex_edit` with a new action `'arc'`, so
1 drag is still 1 Undo step and the result check is the same.

New function `vertex_ops.edit_arc(geom, address, grip, point, steps)` returns the edited geometry.

- `arc_mid` grip: the new arc goes through the begin vertex, the cursor and the end vertex.
- Begin or end `vertex` grip of an arc: that end moves to the cursor. The new arc goes through the moved end, the
  old middle point of the arc and the other end. The straight segment next to the moved end follows, because it
  shares the vertex. If the vertex is the end of 2 arcs (an S-curve), both arcs are recalculated.
- `radius` grip of a full circle: the circle keeps its center; the new radius is the distance from the center to
  the cursor.
- The new arc gets `max(2, round(steps * sweep / 360))` segments. `steps` is the `geometry_circle_steps`
  preference of the editor; the app steps count the full circle.
- If the 3 points are on 1 line (or 2 are equal), the arc becomes 1 straight segment.
- Ctrl+click on the `arc_mid` grip replaces the arc with 1 straight segment from begin to end. Ctrl+click on the
  begin or end vertex grip of an arc removes the vertex as now; the arc vertices next to it stay.
- The preview during the drag shows the full new ring, red if the result is not valid, as now.

## 4. Grip pick with the grid on

`VertexGrips.hit(point)`:

- Grid off: no change. The pick radius is `GRIP_HIT_PX` pixels.
- Grid on (`app.grid_status()`): the pick radius is the larger of `GRIP_HIT_PX` pixels and 1 grid step. The grid
  step is the larger of the X and Y grid gaps (`global_gridx`, `global_gridy` of the editor options).
- The order does not change: vertex grips (and the arc begin and end grips) first, then the nearest grip to the raw
  cursor, then the lower address. `arc_mid` and `radius` grips rank with the vertex grips; `mid` grips rank last.
- The drag after the pick does not change: grid snap and corner snap still apply.

## 5. Not changed

- Explode still gives the short segments.
- The Edit vertices dialog still shows and edits all the real vertices.
- Shapes with more than `GRIP_LIMIT` vertices still get no grips. The limit counts the real vertices.

## 6. Tests

- `tests/test_vertex_ops.py`:
  - `find_arcs` on a rectangle with 4 round corners (4 arcs), a buffer of a line (2 arcs), a full circle, an arc
    across the ring start, an S-curve (2 arcs that share a vertex), a plain polygon (no arcs), a run of 2 equal
    segments (no arc) and a straight run of equal segments (no arc).
  - `vertex_grips` on a rounded rectangle: 8 vertex grips, 4 straight `mid` grips, 4 `arc_mid` grips.
  - `edit_arc` for the `arc_mid` drag, the begin drag, the end drag, the S-curve drag, the full circle radius
    drag, the collinear case and the Ctrl+click straight segment.
- `tests/test_vertex_grips.py`: the pick with the grid on and off, and the order of the grips.
- `tests/test_geo_editor_vertex_drag.py`: 1 arc drag through `apply_vertex_edit` is 1 Undo step.
