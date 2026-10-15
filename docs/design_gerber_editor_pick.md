# Design note F9: Gerber Editor click selection

Status: draft for approval. No code was changed. Implement only after the maintainer approves this note.

Scope: the Select tool of the Gerber Editor (`appEditors/appGerberEditor.py`, class `SelectEditorGrb`) and the code that feeds it.
Out of scope: the drag-rectangle selection (`draw_selection_area_handler`), undo.
In scope (maintainer decision, section 6): the Simplify tool click and the Erase tool click also use `pick_at` (section 2.10).

## 1. Problem

### 1.1 The pick depends on chunk borders

`SelectEditorGrb.selection_worker` (appGerberEditor.py:3361-3404) cuts the shape list of every aperture into chunks of 77 (line 3372). It sends each chunk to the process pool (line 3379).

`check_intersection` (lines 3406-3412) returns only the first shape of its chunk that passes `Point(point).intersects(solid)`. The caller then toggles one shape for each chunk that had a hit (lines 3387-3398).

Result:

- Two overlapping shapes in two different chunks are both selected. Two overlapping shapes in one chunk select only the first one. The outcome depends on where the chunk border falls.
- The order is the storage order. There is no rule such as "smallest shape first".
- The test is `intersects` with the exact click point. There is no tolerance. A trace 0.1 mm wide is about 2 pixels wide at a normal zoom, so it is hard to hit.

### 1.2 The pool path is slow

Every click pickles all shapes and sends them to the workers. The scratch script in section 3 (S3) measured this for 20000 shapes:

- 12.7 MB of pickle data.
- 904 ms median (1130 ms worst) for one pickle/unpickle round trip, before any worker does any work.

The real pool path also waits on `p.get()` for every chunk (lines 3384-3385). The whole job runs inside `app.worker_task` (line 3404), so the result arrives later through signals.

### 1.3 Click versus drag is decided by "any mouse move"

- `on_canvas_move` (appGerberEditor.py:6298-6325) sets `app.selection_type` as soon as `is_dragging == 1` and button 1 is down. There is no distance threshold. A 1-pixel jitter becomes a rectangle selection.
- `on_canvas_click_release` (lines 6091-6100) runs the rectangle path when `selection_type is not None`. Otherwise it calls `click_release((self.pos[0], self.pos[1]))`. The point is the press position.
- In the legacy canvas `is_dragging` is set on every press (`PlotCanvasLegacy.on_mouse_press`, line 1074). It is cleared on release only when the distance is below 0.05 (line 1104).

### 1.4 Grid snap moves the pick point

`on_canvas_click` snaps `self.pos` when the grid is on (lines 5942-5943). Then it snaps a second time when it calls `active_tool.click(snap(...))` (line 5971). `on_canvas_click_release` snaps the release position (lines 6019-6020). With a 2.54 mm grid a click can move up to 1.27 mm. The pick then misses the trace the user pointed at.

### 1.5 Table sync disconnects and reconnects signals by hand

`after_selection` (lines 3414-3450):

- calls `apertures_table.clearSelection()` (line 3419) while both handlers are still connected,
- disconnects `cellPressed` and `selectionModel().selectionChanged` inside `try/except` that only log (lines 3427-3435),
- selects rows,
- connects both again (lines 3446-3447).

If a `disconnect` fails (for example after the model changed), the `connect` at the end adds a second receiver. The handler then fires twice. `SelectEditorGrb.click_release` also calls `clearSelection()` at line 3340 with both handlers connected.

### 1.6 Nearby fact: the transform plugin file is dead code

`appGerberEditor.py:17` imports `TransformEditorTool` from `grb_plugins/GrbTransformationPlugin.py`. The module defines its own `class TransformEditorTool` at line 7224. The later `class` statement replaces the import. `AppGerberEditor.__init__` (line 4160) therefore builds the local class.

The plugin class calls `sel_sha.rotate()`, `.mirror()`, `.skew()`, `.scale()`, `.offset()` and `.buffer()` on `DrawToolShape`. `DrawToolShape` (`grb_plugins/GrbCommon.py:16-68`) has none of these methods. The plugin file is not reachable. This note does not touch it, but section 2.1 lists it so that nobody adds the counter call to dead code only.

## 2. Contracts

### 2.1 Index: lazy STRtree with a revision counter

New members of `AppGerberEditor` (appGerberEditor.py:3985):

| Member | Meaning |
|---|---|
| `self.geometry_revision: int` | Starts at 0. Set in `__init__` next to `self.storage_dict = {}` (line 4014). |
| `touch_geometry()` | `self.geometry_revision += 1`. The only method that every mutation site calls. |
| `self._pick_cache` | `None` or a tuple `(revision, shape_count, tree, refs)`. |
| `get_pick_index()` | Returns `(tree, refs)`. Rebuilds when `_pick_cache` is `None`, when the revision differs, or when the shape count differs (see the guard below). |

`refs` is a list of `(aperture_key, element_index, shape)`. The tree holds the `shape.geo['solid']` objects in the same order. Shapes without a `solid` key, and empty solids, are skipped.

Guard against a missed call site: `get_pick_index` also sums `len(storage['geometry'])` over all apertures (cost: one pass over the apertures) and rebuilds when the sum differs from the cached sum. The guard catches a forgotten add or delete. It cannot catch a forgotten in-place change, so every in-place site must still call `touch_geometry()`.

The tree is thrown away, not edited. Editing is not supported by STRtree.

#### Mutation sites (from a search of `storage_dict`, `['geometry']`, `current_storage`, and `.geo[...] =`)

All lines are in `appEditors/appGerberEditor.py` unless noted. Each site calls `self.touch_geometry()` (or `self.draw_app.touch_geometry()` in a tool class) after its change and before any `plot_all()`.

Add:

| # | Site | Lines | Note |
|---|---|---|---|
| A1 | `add_gerber_shape` | 5900-5929 | Central add for pad, array, track, region, disc, semi-disc, poligonize, copy and move. One call here covers all of them. Utility shapes (line 5926) do not count. |
| A2 | `on_grb_shape_complete` | 5868-5898 | Calls A1. No extra call needed. |
| A3 | `DiscEditorGrb`, `DiscSemiEditorGrb` create `storage_dict[0]` | 2140, 2270 | New aperture 0 record. |
| A4 | `EraserEditorGrb.make`: create or extend `storage_dict[0]` | 3183, 3189 | |
| A5 | `ImportEditorGrb.import_shapes` | 3895-3952 | `+=` on geometry lists and new keys. |
| A6 | `on_aperture_add` | 4559-4630 (stores at 4577, 4598, 4619) | New empty aperture. The tree does not change, but the call keeps the rule simple. |

Delete:

| # | Site | Lines | Note |
|---|---|---|---|
| D1 | `delete_shape` | 6598-6612 | Central delete. `delete_selected` (6583) and `SimplifyEditorGrb.on_simplification_click` (2743-2749) go through it. |
| D2 | `EraserEditorGrb.make`: `storage_dict.pop(storage)` and `geometry.pop(td)` | 3192, 3197 | |
| D3 | `MoveEditorGrb.make`: `current_storage.remove(select_shape)` | 2959 | Followed by A1 through `on_grb_shape_complete`. |
| D4 | `on_aperture_delete` | 4685 | `storage_dict.pop(...)`. |

Replace or re-key:

| # | Site | Lines | Note |
|---|---|---|---|
| R1 | `on_tool_edit`: aperture code edit (re-key) | 4788-4789 | `pop` then assign. |
| R2 | `on_tool_edit`: size edit and dimension edit (`clear()` then `add_gerber_shape`) | 4836-4837, 4886-4887 | A1 also fires. The explicit call is kept for clarity. |
| R3 | `on_tool_edit`: merge into an existing aperture | 4795-4812 | Known defect, unrelated to this note: the loop at line 4799 iterates a dict, and line 4810 passes a list of plain dicts to `add_gerber_shape`, which asserts on type. The path is not reachable today ("TODO" at line 4779). Add the call anyway so the later fix does not forget it. |
| R4 | `AppGerberEditor.on_scale` replaces the geometry list | 6734-6736 | |
| R5 | `GrbBufferPlugin.BufferEditorTool` replaces the geometry list | `grb_plugins/GrbBufferPlugin.py:174-176` | Live plugin (see below). |

In-place change of `shape.geo[...]` (the shape object stays, its solid is replaced):

| # | Site | Lines | Note |
|---|---|---|---|
| T1 | `TransformEditorTool.on_rotate_action` | 8008-8012 | Live class defined at 7224. |
| T2 | `.on_flip` | 8043-8055 | |
| T3 | `.on_skew` | 8086-8090 | |
| T4 | `.on_scale` | 8125-8129 | |
| T5 | `.on_offset` | 8162-8173 | |
| T6 | `.on_buffer_action` | 8199-8217 | |

For T1 to T6, put one `self.draw_app.touch_geometry()` after the loop, before `plot_all()`. Do not call it inside the loop.

Load and reset:

| # | Site | Lines | Note |
|---|---|---|---|
| L1 | `activate_grb_editor` resets `storage_dict` | 5038 | New dict object. |
| L2 | `edit_fcgerber` worker fills `storage_dict` | 5477-5478 | Runs in a worker thread. See Risks. |
| L3 | `clear()` (called by `deactivate_grb_editor`, line 5087) | 5288-5298 | `storage_dict.clear()`. Also set `self._pick_cache = None` so the tree releases its shapes. |
| L4 | `__init__` | 4014 | Initial state. |

Read only (no call): `new_edited_gerber` / `update_fcgerber` (5558-5640, a deepcopy), `draw_selection_area_handler` (6122), `on_markarea` (6753).

#### How plugins reach the counter

The editor plugins in `appEditors/grb_plugins/` hold a `draw_app` reference. Their only way to change geometry is through `draw_app`. The rule: a plugin that changes shapes calls `self.draw_app.touch_geometry()`. This is one method, and it has no arguments.

Result of the search of `grb_plugins/`:

| Plugin file | Writes shapes? | Action |
|---|---|---|
| `GrbBufferPlugin.py` | Yes (lines 174-176) | Add one `self.draw_app.touch_geometry()` after line 176. |
| `GrbTransformationPlugin.py` | Not reachable (shadowed, see 1.6) | None. Mention in the commit message. |
| `GrbPadPlugin.py`, `GrbPadArrayPlugin.py`, `GrbTrackPlugin.py`, `GrberRegionPlugin.py`, `GrbCopyPlugin.py` | No. They only set UI values and call `draw_app.select_tool`. The shapes come from the `*EditorGrb` tools through A1. | None. |
| `GrbSimplificationPlugin.py` | No (reads `draw_app.selected`). The write happens in `SimplifyEditorGrb.on_simplification_click`. | None. |
| `GrbCommon.py` | Defines `DrawToolShape`. | None. |

The Gerber Editor has no undo. This item does not add undo.

### 2.2 Pick runs on the main thread, synchronously

`SelectEditorGrb.click_release` calls a new method `pick_at(point)` and then `after_selection()` directly. Remove:

- `selection_worker`, `check_intersection`, the `selection_triggered` signal and its connect at line 3289,
- the `app.worker_task` hop, the `update_ui_sig` emit (line 3400) and the `plot_object` emit (line 3402). Call `self.draw_app.update_ui()` and `self.after_selection()` in place of them.

Keep `editor_obj.pool`. `edit_fcgerber` still uses it (line 5461).

There is no async result. No "late apply" code is needed.

### 2.3 Hit rule

`pick_at(point)` returns the picked `DrawToolShape` or `None`.

1. `tol = PICK_TOLERANCE_PX * canvas.pixel_size()`. `PICK_TOLERANCE_PX = 5`.
2. `idx, dist = tree.query_nearest(Point(point), max_distance=tol, return_distance=True, all_matches=True)`. A point inside a polygon has distance 0.
3. For each candidate build the key:
   1. `round(dist, 9)` (plot units). The rounding makes equal distances compare equal.
   2. Distance from the point to `shape.geo['follow']`. If `follow` is missing, `None` or empty, use `+inf`. The key then sorts last.
   3. `solid.area`.
   4. `(aperture_rank, element_index)`.
4. Pick the minimum key.

Order of the sort key, as the plan requires: distance, distance to `follow`, area, then `(aperture, element index)`.

### 2.4 Pixel size per canvas

Add `pixel_size()` (plot units per screen pixel) to each canvas class that the editor can use:

| Canvas | File | Formula |
|---|---|---|
| VisPy 2D/3D engine | `appGUI/VisPyCanvas.py` (class `VisPyCanvas`, `translate_coords` at line 128; `PlotCanvas` in `appGUI/PlotCanvas.py:30` inherits it) | `a = translate_coords((0, 0)); b = translate_coords((1, 0)); hypot(b[0]-a[0], b[1]-a[1])`. |
| 3D scene canvas | `appGUI/PlotCanvas3d.py` (`translate_coords` at line 209) | Same formula. |
| Legacy (matplotlib) | `appGUI/PlotCanvasLegacy.py` (`translate_coords` at line 1167 returns the data coordinates unchanged) | `(xmax - xmin) / axes.bbox.width` with `xmin, xmax = self.axes.get_xlim()`. The view keeps the aspect ratio (see `PlotCanvasLegacy` lines 868-897), so one value serves both axes. |

The editor calls `self.canvas.pixel_size()` at pick time. It never caches the value, so a zoom changes the tolerance on the next click.

### 2.5 Aperture order and the empty `follow` rule

Settled in section 3.

### 2.6 Grid snap: Select click only

- In `on_canvas_click` (5931): when `isinstance(self.active_tool, SelectEditorGrb)`, do not call `geo_editor.snap` for `self.pos` and do not snap in the `active_tool.click(...)` call at line 5971.
- In `on_canvas_click_release` (6009): when the active tool is `SelectEditorGrb`, use the raw position (lines 6019-6022).
- In `on_canvas_move` (6242-6243): for `SelectEditorGrb`, do not replace `x, y` with the snapped values, so that the rubber-band rectangle matches what the release will use. The cursor symbol (lines 6246-6260) may still snap. It is only a drawing.
- The same raw-position rule applies to the 2 other pick clicks: `SimplifyEditorGrb.click_release` and the first click of `EraserEditorGrb.click` (the click that picks the eraser shape, when nothing is selected). The second Eraser click (the destination) keeps the snap, because it places geometry.
- Every other tool keeps the snap.
- Put the rule in 1 place: a tool class attribute `uses_raw_pick = True` on `SelectEditorGrb` and `SimplifyEditorGrb`, and a method `EraserEditorGrb.wants_raw_pick()` that returns `True` only while `get_selected()` is empty. The canvas handlers test this, not the class names.

### 2.7 Click versus drag: 5 screen pixels

- Constant `CLICK_DRAG_THRESHOLD_PX = 5`.
- At press, `on_canvas_click` stores `self.press_pos_raw = (x, y)` in plot units (the unsnapped value).
- The distance in pixels is `hypot(dx, dy) / canvas.pixel_size()`. This works on both canvases, because both give plot-unit positions in the handlers and both have `pixel_size()`.
- Move handler (6298-6327): if the button is down and the pixel distance from `press_pos_raw` is below the threshold, set `app.selection_type = None` and call `app.delete_selection_shape()`. Do not draw the rectangle. Otherwise run the existing code.
- Release handler (6091): compute the pixel distance between `press_pos_raw` and the raw release position. If it is below the threshold, treat the event as a click: set `app.selection_type = None` and go to the `click_release` branch. This also covers the case where the pointer moved out and came back. If it is at or above the threshold, run the rectangle path as now.
- The pick point is the press position, as today (line 6100 passes `self.pos`).

### 2.8 Modifiers

No change. `SelectEditorGrb.click` (3319-3337) and `click_release` (3339-3359) keep the `global_mselect_key` logic. The picked shape is toggled: removed from `selected` if it is in it, appended if not. With no modifier and no hit, the selection is empty (as now). With a modifier and no hit, the selection does not change.

### 2.9 Table sync (`after_selection`, line 3414)

Rewrite the body with signal blockers. Remove the manual `disconnect` and `connect` calls (3426-3447).

```
table = self.draw_app.ui.apertures_table
with QtCore.QSignalBlocker(table), QtCore.QSignalBlocker(table.selectionModel()):
    table.clearSelection()
    ...select the rows...
```

Rules:

- Both blockers are active for the whole body, `clearSelection()` included. The `clearSelection()` at line 3340 (in `click_release`) moves into the same blocked region (call it from `after_selection`, or wrap it with the same blockers).
- `table.selectionModel()` is read inside the `with` header after the table is final. If `build_ui` replaces the model between clicks, the blocker still binds to the current model.
- `self.sel_aperture` and `draw_app.last_aperture_selected` keep their meaning.
- `draw_app.plot_all()` stays at the end, after the blockers are released.
- `draw_selection_area_handler` (6148-6194) has the same pattern. It is not changed by this item (see Risks).
- Put the blocked row selection in 1 method, `sync_aperture_rows(apertures)`. `after_selection` and the Eraser pick (section 2.10) both call it.

### 2.10 Simplify and Erase clicks

**Simplify** (`SimplifyEditorGrb.click_release`, 2666-2696). Now it toggles every shape under the point, with no tolerance.
- New: the modifier logic stays as it is. Then `shape = self.draw_app.pick_at(point)`. If `shape` is not `None`, toggle it in `selected`. Then `plot_all()` and `simp_tool.calculate_coords_vertex()`, as now.
- The table `clearSelection()` at 2667 moves into `sync_aperture_rows`.
- Result: 1 click selects 1 shape (the same shape that the Select tool picks). This is a behavior change: today 1 click on overlapping shapes selects all of them.

**Erase** (`EraserEditorGrb.click`, 3096-3127). Now, when nothing is selected, it loops over all shapes with `Point.within`. The last match wins, and the order of the loop decides. It disconnects `cellPressed` by hand and does not block the selection model.
- New: `shape = self.draw_app.pick_at(point)`. If `shape` is not `None`, `selected = [shape]` and `sync_aperture_rows({aperture of shape})`. Remove the manual disconnect and connect (3114-3127).
- `pick_at` returns the aperture key with the shape (`pick_at(point) -> (shape, aperture) | None`), so the caller does not search for it.
- The text "Nothing to ersase." is a typo. Change it to "Nothing to erase." and keep it translatable.

**Defects in `EraserEditorGrb.make` (3144-3200), fixed in the same item** (the pick tests run `make`, so they must give correct storage):
1. Line 3172 reads `follow_data = geo_el.geo['solid']`. It must read `geo_el.geo['follow']`. Today the cut `follow` is a copy of the cut solid, so the follow line becomes a polygon.
2. `intersection_geo_list.append(DrawToolShape(new_geo_el))` runs for every shape with a `solid`, also when the eraser does not touch it. Then `new_geo_el` is `{}`, and an empty shape goes into aperture 0. Append only for a shape in `to_delete`.
3. `intersection_geo_list` is made 1 time before the loop over the apertures, but it is added to `storage_dict[0]` in each pass of that loop (`+=`). So the shapes of the first aperture are added again for each later aperture. Add the list 1 time, after the loop.
4. The loop also runs over `storage_dict[0]` itself while it adds to it. Take the list of keys before the loop (the code does this), and skip the shapes that this run just added.
- After `make`, call `touch_geometry()` (the counter of section 2.1, sites A4 and D2).

## 3. Settled questions

**S1. Empty or missing `follow`.**
Decision: distance to `follow` is `+inf`. The shape sorts last in that key and the next keys (area, then aperture and index) decide.
Reason: a shape without a center line (a region, or a record that has only `solid`) has no better claim than a shape that has one. Raising or using 0 would make regions win every tie. `add_apertures` (5533-5539) and `build_edit_tools` (5523-5524) show that `follow` can be absent.

**S2. Aperture order.**
Decision: one rule. `aperture_rank(key)` is `(0, int(key))` when `key` is an `int`, or a `str` that holds only digits. Otherwise it is `(1, str(key))`.
Reason: the editor mixes key types. `storage_dict[0]` is an `int` (lines 3183, 4577). `on_row_selected` converts table text with `int(...)` (line 5775), so most keys are `int`. Other code compares `str(aper)` with table text (line 3440). A numeric rank keeps 9 before 10. A fixed fallback keeps the sort total, so it never raises `TypeError` when `int` and `str` keys are mixed.

**S3. Timing check on a large board before the synchronous pick is final.**
Decision: synchronous pick is approved for boards up to 20000 shapes, on this measurement. The scratch script is `C:/Users/Marius/AppData/Local/Temp/claude/D--1-Development-1-PROJECTS-FlatCAM-EVO/784fe078-130b-4787-8b4c-3d6eb0785f4f/scratchpad/strtree_timing.py`. It ran with the project `.venv` Python and Shapely 2.2.0.

Data: 20000 synthetic shapes on a 200 mm by 150 mm board. 8000 pads (half 32-gon circles, half rectangles) and 12000 traces (buffered lines, 0.2 mm wide, 1 to 8 mm long, 0/45/90 degrees). Random positions. Median of 7 builds, 500 queries.

| Step | Median | Worst |
|---|---|---|
| STRtree build from an existing array | 7.5 ms | 9.3 ms |
| Full rebuild (walk `storage_dict`, collect solids and refs, sort apertures, build) | 33 to 38 ms | 35 to 49 ms |
| `query_nearest`, `max_distance=0.05`, all matches | 0.077 ms | 1.8 ms (first call) |
| `query_nearest`, `max_distance=1.0` | 0.088 ms | 0.27 ms |
| Whole pick including the sort of the candidates | 0.088 ms | 0.49 ms |
| Old linear `Point.intersects` loop over all shapes (single process, for comparison) | 5.0 ms | 9.2 ms |
| Old pool path: pickle and unpickle of all chunks, one click | 904 ms | 1130 ms (12.7 MB) |

Reading:

- A query is far below one frame (16 ms). The rebuild after an edit (about 40 ms) is below the cost of the `plot_all()` that follows the edit.
- A click after an edit pays one rebuild. A click after a click pays about 0.1 ms.
- The pool path costs about 900 ms per click for the same data, before the workers start.
- The numbers come from a synthetic board. Acceptance test AT-12 repeats the measurement on a real large board from `tests/test_files` and fails the build if one query takes more than 5 ms.

If a later board is 10 times larger, the rebuild is about 0.4 s. In that case move only the rebuild to a worker. The pick would still be synchronous. This is not needed now.

**S4. Where the pick point comes from.**
Decision: the press position, unsnapped (section 2.7).
Reason: this is what `click_release` uses today (line 6100). The user aims at the press position.

**S5. Tolerance value.**
Decision: 5 pixels, the same value as the drag threshold.
Reason: one number to explain. A 2-pixel trace gets a 12-pixel wide hit zone. A second tolerance would make the click-versus-drag rule hard to reason about. The constants are separate names, so a later change is easy.

**S6. Is the drag rectangle also affected by the snap rule?**
Decision: yes for the Select tool (section 2.6).
Reason: otherwise the preview and the result use different corners.

## 4. Acceptance tests

New file: `tests/test_gerber_editor_pick.py`. Use `unittest` (project style) with `QApplication` in offscreen mode, as `tests/test_gerber_editor_clear.py` does. Build the editor with real `AppGerberEditor` and real `SelectEditorGrb`. Build shapes with `DrawToolShape({'solid': ..., 'follow': ...})`. A fake canvas object with `pixel_size()` and `translate_coords()` is allowed, because the canvas is not under test. Drive the production methods `on_canvas_click`, `on_canvas_move`, `on_canvas_click_release`, with small event objects that have `pos`, `button`, `is_dragging`.

| ID | Name | Fixture and check |
|---|---|---|
| AT-1 | `test_thin_trace_hit_inside_tolerance` | Trace 0.1 mm wide. Pixel size 0.05. Click 0.2 mm off the edge (4 px): the trace is selected. Click 0.4 mm off (8 px): nothing is selected. |
| AT-2 | `test_overlap_picks_small_pad` | Big pad radius 1.0 and small pad radius 0.2, both in aperture 10 and 11, centers 0.1 apart. Click inside both, near the small center. Both have distance 0. Expect the small pad. Repeat with the shapes in the opposite storage order. The result must be the same. |
| AT-3 | `test_tie_is_stable` | Two identical pads, apertures 10 and 11. The click picks aperture 10, index 0. Swapping the insertion order of the dict keys does not change the result. |
| AT-4 | `test_chunk_border_independent` | 200 pads in one aperture, with an overlapping pair at indexes 76 and 77. The result does not change when the pair moves to 10 and 11. Exactly one shape is selected. |
| AT-5 | `test_follow_missing_sorts_last` | Two overlapping solids at distance 0. One has `follow`, one has no `follow`. The one with `follow` wins. Both without `follow`: the smaller area wins. |
| AT-6 | `test_aperture_rank_mixed_keys` | Keys `0`, `9`, `10`, `'10'`, `'X1'`. Sorting does not raise. Order is 0, 9, then 10 and '10' (equal rank), then 'X1'. |
| AT-7 | `test_tree_fresh_after_add` | Pick (builds the tree). Add a shape through `on_grb_shape_complete`. Click on it: it is picked. Compare with a brute-force scan. |
| AT-8 | `test_tree_fresh_after_delete` | Pick. `delete_shape`. Click where it was: no hit. Also `delete_selected` and Eraser `make` (storage pop). |
| AT-9 | `test_tree_fresh_after_move` | Select a shape. Run `MoveEditorGrb.make` with a known offset. Click the new place: hit. Click the old place: no hit. |
| AT-10 | `test_tree_fresh_after_transform` | Run each live `TransformEditorTool` action: rotate, flip, skew, scale, offset, buffer, on a selected shape. After each, click the new outline: hit. These are the in-place cases T1 to T6. The test must fail if `touch_geometry()` is removed from one action. |
| AT-11 | `test_tree_fresh_after_plugin_edit` | Run the live `BufferEditorTool` buffer action (R5). Click at a point that is inside only after the buffer: hit. Also `AppGerberEditor.on_scale` (R4) and an aperture size edit (R2). |
| AT-12 | `test_large_board_pick_time` | Load a large Gerber from `tests/test_files` (or build 20000 synthetic shapes if no large file exists). First pick builds the tree. 100 further picks: each below 5 ms (use a median and a generous bound, to avoid a flaky test). |
| AT-13 | `test_revision_counter_sites` | One parametrized test. For every row of the mutation table in section 2.1 (A1, A4, A5, D1, D2, D4, R1, R4, R5, T1 to T6, L1, L3): run the production action and assert that `geometry_revision` increased. |
| AT-14 | `test_count_guard_rebuilds` | Append a shape directly to `storage_dict[10]['geometry']` (a "forgotten" site). The next pick sees the new shape because the count changed. |
| AT-15 | `test_zoom_changes_tolerance` | Same click and same shapes. Pixel size 0.05, trace 0.2 mm away: hit (4 px). Pixel size 0.2 (zoomed out), same distance: hit (1 px). Pixel size 0.01 (zoomed in), same distance: miss (20 px). |
| AT-16 | `test_pixel_size_vispy_and_legacy` | `VisPyCanvas.pixel_size()` with a stub `grid.get_transform` that maps 1 px to 0.05 units. `PlotCanvasLegacy.pixel_size()` with a stub axes (`get_xlim` = (0, 100), `bbox.width` = 1000): 0.1. |
| AT-17 | `test_grid_snap_does_not_change_pick` | Grid on, grid step 2.54. Click 0.05 off a trace: the trace is picked, and the stored press position equals the raw one. Then run the Pad tool with the grid on: the pad center is on the grid (snap kept for draw tools). |
| AT-18 | `test_ctrl_adds` | Set `global_mselect_key` to Control and set the keyboard modifier to Control (patch `QApplication.keyboardModifiers`). Click A then click B: both selected. Click A again: A is removed. |
| AT-19 | `test_three_pixel_move_is_click` | Press, move 3 px (one move event), release. A shape is picked. `app.selection_type` is `None`. No rubber band was drawn (spy on `draw_moving_selection_shape`). |
| AT-20 | `test_six_pixel_move_is_drag` | Press, move 6 px, release. `draw_selection_area_handler` runs once, and `click_release` does not run. |
| AT-21 | `test_move_out_and_back_is_click` | Press, move 20 px, move back to 2 px, release. It is a click. |
| AT-22 | `test_table_sync_no_handler_fires` | Connect spies to the real `cellPressed` and `selectionChanged` slots. Run `after_selection()` with two selected apertures. Spies: 0 calls. Table rows are selected. `receivers` count of each signal is unchanged (still 1). |
| AT-23 | `test_table_handlers_fire_after_sync` | After AT-22, simulate one user row click. `on_row_selected` fires exactly once. `on_table_selection` fires exactly once. |
| AT-24 | `test_table_sync_survives_failed_disconnect` | Run `after_selection()` twice in a row and after `build_ui()`. The receiver count stays 1 (the old code could add receivers). |
| AT-25 | `test_simplify_click_picks_one` | 2 overlapping pads. Simplify tool click inside both: exactly 1 shape selected, the same shape that `SelectEditorGrb` picks. Grid on: the raw point is used. With the multi-select key, a 2nd click adds the 2nd pad. |
| AT-26 | `test_eraser_pick_uses_pick_at` | Nothing selected. Eraser first click 0.2 mm off a thin trace (4 px): the trace is selected and its aperture row is selected. Spies on `cellPressed` and `selectionChanged` handlers: 0 calls. Receiver counts unchanged. |
| AT-27 | `test_eraser_make_keeps_follow` | Erase across a trace that has a `follow` line. The new shapes in aperture 0 have a `follow` that is a line (not a polygon) and lies on the old center line minus the erased part. |
| AT-28 | `test_eraser_make_no_empty_shapes` | 3 apertures, the eraser touches 1 shape of aperture 10 only. Aperture 0 gets exactly the cut parts of that shape. No shape in aperture 0 has an empty `geo`. Shapes of apertures 11 and 12 are not changed. |
| AT-29 | `test_eraser_make_no_copies` | The eraser touches 1 shape in aperture 10 and 1 in aperture 11. Aperture 0 gets exactly 2 new shapes (the 2 cut results), not 3. |
| AT-30 | `test_eraser_second_click_snaps` | Grid on. The first Eraser click is raw. The destination click is snapped to the grid. |

## 5. Risks

- **Missed mutation site.** A forgotten `touch_geometry()` on an in-place change gives a stale pick. The count guard catches add and delete only. Mitigation: AT-13 lists every site by name. Add a code comment at each site. Reviewers should search for `geo['solid'] =` and `['geometry']` in later changes.
- **Worker thread load.** `edit_fcgerber` fills `storage_dict` in a worker thread (line 5478). The pick runs in the main thread. If the user clicks before loading ends, the guard may build a partial tree. The count guard makes the next pick rebuild when the load finishes. The editor UI is not usable before `on_multiprocessing_finished` (line 5545), so the risk is low. Call `touch_geometry()` there too.
- **Stale references.** The tree holds `shape.geo['solid']` objects. Code that replaces the dict entry (T1 to T6) leaves the tree with the old solid. This is why those sites need the call. A rebuild also drops the old objects.
- **Memory.** The tree and `refs` hold one reference per shape. For 20000 shapes this is a few MB. `clear()` sets `_pick_cache = None`.
- **Tolerance on dense boards.** At 5 px, a click near two traces 0.15 mm apart (3 px) has two candidates. The rule picks the nearest. Mitigation: nearest first, so the user can zoom in. No "cycle through candidates" feature is planned.
- **Same-click pad and its trace.** A trace that ends in a pad has distance 0 to both. The `follow` distance decides: the click near the pad center picks the pad, and the click along the trace picks the trace. At the junction the area rule picks the smaller shape (usually the trace). This is the rule in the plan. The tests AT-2 and AT-5 fix the behavior.
- **Simplify behavior change.** 1 click now selects 1 shape, not every shape under the point. A user who wants more than 1 shape uses the multi-select key, as in the Select tool. Put this in the CHANGELOG entry.
- **Eraser storage fix changes output.** After the fixes of section 2.10, aperture 0 holds fewer shapes than before (no empty shapes, no copies). A project that was saved after an erase with the old code keeps its extra shapes. They are harmless copies. No migration.
- **Area selection handler.** `draw_selection_area_handler` (6148, 6194) disconnects `cellPressed` with no argument and reconnects only `on_row_selected`. The same blocker pattern would be safer. Not part of this item.
- **Nearby defect.** `on_table_selection` (5821-5828) appends all shapes again when all rows are selected, with no duplicate check. It can double the entries in `selected`. Not part of this item. The new code does not depend on it.
- **HiDPI.** Pixel positions are logical pixels on both canvases. A 5-pixel rule is therefore the same size on screen on all displays. The VisPy `translate_coords` is the same mapping the handlers already use, so no extra scaling is applied.

## 6. Maintainer decisions

1. Tolerance and click-versus-drag threshold: 5 pixels for both. Approved.
2. The Simplify click and the Erase click use `pick_at` in this item. Approved. Section 2.10 gives the contracts, and AT-25 to AT-30 test them.
