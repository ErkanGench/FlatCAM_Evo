# Vertex Dragging in the Geometry Editor — Design

Date: 2026-10-21
Status: approved design, not implemented

## Goal

Let the user change the vertices of 1 shape with the mouse in the Geometry Editor:

- Drag a vertex to move it.
- Drag a midpoint grip to insert a vertex.
- Ctrl+click a vertex to remove it.

The numeric "Edit vertices" dialog stays. The Gerber Editor will use the same shared parts later, so the shared
parts contain no Geometry Editor code.

## Decisions

| Topic | Decision |
|---|---|
| Start | In the Select tool (`FCSelect`). No new toolbar button. |
| Scope | 1 selected shape. All rings (exterior and holes). Multipart shapes (`MultiLineString`, `MultiPolygon`). |
| Actions | Move, insert (midpoint grips), remove (Ctrl+click). |
| Invalid result | Live preview in the invalid color. On release, reject and warn. |
| Colors | Red for invalid, orange for grips. If a color is near an editor color, use its opposite color. |
| Code layout | Pure functions in `vertex_ops.py` and 1 helper attribute `VertexGrips`. No mixins. |

## Parts

### `appEditors/vertex_ops.py` (new)

Pure Shapely functions. No Qt, no editor import.

- `vertex_grips(geom)` returns a list of grips. Each grip is `(kind, address, point)`:
  - `kind` is `'vertex'` or `'mid'`.
  - `address` is `(part, ring, index)`. `part` is 0 for a single geometry. `ring` is 0 for the exterior or the
    line, and 1+ for holes. For a `'mid'` grip, `index` is the start vertex of the segment.
  - The closing coordinate of a ring gets no own grip. It is the same point as vertex 0.
- `edit_vertex(geom, action, address, point=None)` returns the new geometry.
  - `action` is `'move'`, `'insert'` or `'remove'`.
  - `'insert'` puts `point` at `index + 1` of the ring. It accepts any point.
  - For a closed ring, a change of vertex 0 also changes the closing coordinate.
  - It keeps the geometry type and all parts and rings that it does not change.
  - It raises `ValueError` with the messages that `apply_vertex_edit` uses now.
- `check_vertex_result(old, new)` raises `ValueError` if the new geometry is empty, not valid or not simple, has a
  zero-length segment, or has too few vertices in a ring (3 for a closed ring, 2 for a line).
- `contrast_color(preferred, used_colors)` returns `preferred` or its opposite color. See "Colors".

### `appEditors/vertex_grips.py` (new)

The class `VertexGrips` holds the grip and drag state. The editor keeps 1 instance as `self.vertex_grips`.

It uses only these editor calls:

- `editor.selected`, `editor.active_tool`
- `editor.apply_vertex_edit(action, address, point, target)`
- `editor.snap(x, y)`, `editor.reject_busy()`
- `editor.app.plotcanvas` (shape collection and pixel size), `editor.app.inform`, `editor.app.options`

Public calls:

- `show(shape)` draws the grips of `shape`. `hide()` removes them and cancels an open drag.
- `press(screen_pos, canvas_pos, modifiers)` returns `True` if a grip took the event.
- `move(screen_pos, canvas_pos)` returns `True` while a drag is open. It updates the live preview.
- `release(screen_pos, canvas_pos)` returns `True` if a grip took the event. It commits or rejects.
- `cancel()` ends an open drag with no change.

`VertexGrips` keeps only x and y of each point. VisPy `translate_coords` returns 4 values (x, y, z, w).

### Changes to `appEditors/appGeoEditor.py`

- `__init__`: `self.vertex_grips = VertexGrips(self)`.
- `on_canvas_click`, `on_canvas_move`, `on_canvas_click_release`: 1 hook at the start of the left-button code.
  If `vertex_grips` returns `True`, the handler returns. If not, the current code runs.
- Right button press and the Esc key: call `vertex_grips.cancel()` before the current code.
- After each selection change, after a tool change and when the editor closes: show the grips if `FCSelect` is
  active and exactly 1 shape is selected. If not, call `hide()`.
- `vertex_edit_target` accepts `MultiLineString` and `MultiPolygon`. It still rejects collections, empty shapes and
  3D coordinates.
- `apply_vertex_edit(action, address, point=None, target=None)` uses `edit_vertex` and `check_vertex_result`. It
  keeps the `@geometry_operation` decorator, so 1 call gives 1 Undo step.
- The Edit vertices dialog gets "Part" and "Ring" fields. The dialog keeps its own rule for insert: the new vertex
  must lie inside the chosen segment.

## Interaction

### When grips show

- `FCSelect` is active and exactly 1 shape is selected.
- The shape has no more than `GRIP_LIMIT` (5000) vertices. If it has more, the status bar tells the user to use
  the Edit vertices dialog, and no grips show.
- Vertex grips are filled squares. Midpoint grips are smaller hollow squares.

### Hit test

- The hit radius is `GRIP_HIT_PX` (6 px). The code changes it to canvas units with the pixel size of the canvas.
- A vertex grip wins over a midpoint grip. The nearest grip wins.
- If no grip is in the radius, the current Select code runs.

### Drag

1. The user presses the left button on a grip. `VertexGrips` keeps the grip, the original geometry and the screen
   point.
2. The drag starts only after `CLICK_DRAG_THRESHOLD_PX` (5 px). A click with no drag does not change the shape.
3. For a midpoint grip, the drag inserts a vertex at `index + 1` and moves it.
4. Each mouse move snaps the point with `editor.snap()`. Corner snap ignores the vertex that is dragged.
5. The preview draws the new geometry. It uses the grip color if `check_vertex_result` passes, and the invalid
   color if not.

### Release

- `VertexGrips` calls `editor.apply_vertex_edit(action, address, point, target=shape)`.
- If the result is valid, the shape changes. 1 drag gives 1 Undo step. The grips show on the new shape.
- If the result is not valid, the shape does not change. The status bar shows the reason.

### Remove

- Ctrl+click on a vertex grip (press and release with no drag) removes the vertex.
- Ctrl+click away from a grip keeps the current toggle behavior of the Select tool.

### Cancel

- Esc or the right button during a drag removes the preview. The shape does not change.

## Colors

`contrast_color(preferred, used_colors)`:

- It compares RGB only and ignores alpha.
- If the distance to any color in `used_colors` is less than `COLOR_CLASH_DIST` (100 of 441), it returns the
  opposite color `(255 - r, 255 - g, 255 - b)` with the alpha of `preferred`. If not, it returns `preferred`.

The used colors are `global_draw_color`, `global_sel_draw_color`, `global_sel_line` and the canvas background of
the current theme.

- Grip color: `contrast_color('#FF8000FF', used)`.
- Invalid color: `contrast_color('#FF0000FF', used + [grip color])`.

With the default colors, the grips are orange and the invalid preview is red.

## Errors

- If `reject_busy` is true at the press, `press` returns `False` and the current Select code runs.
- If the shape changes during the drag (for example Undo with a key), `apply_vertex_edit` fails its `target`
  check. The preview goes away and the status bar shows the warning.
- `hide()` cancels an open drag. The editor calls it when it closes, changes tool or changes the selection.

## Tests

1. `tests/test_vertex_ops.py` (no Qt):
   - Grips for a `LineString`, a `LinearRing`, a `Polygon` with a hole and a `MultiPolygon`.
   - Move, insert and remove for each type. Vertex 0 and the closing coordinate.
   - Each invalid case raises `ValueError`.
   - `contrast_color` with a clash and with no clash.
2. `tests/test_vertex_grips.py` (fake editor):
   - Hit test and the priority of vertex grips over midpoint grips.
   - No change below the drag threshold.
   - Cancel with Esc and with the right button.
   - Ctrl+click remove.
   - An invalid release does not change the shape.
3. Geometry Editor integration, in the style of `tests/test_vispy_only_geo_editor.py`:
   - 1 drag gives 1 Undo step. Undo gives the old shape back.
   - The mock `translate_coords` returns 4 values, as VisPy does.
4. `tests/test_geo_editor_vertices.py` must still pass. Its calls change to the new `address` argument.

## Out of scope

- Grips on more than 1 selected shape.
- Vertex dragging in the Gerber Editor (later, with the same shared parts).
- Preferences for the grip size, the grip limit or the colors.
