# Design note F10: Cutout, slots inside the board outline

Status: draft for approval. No code was changed. Implement only after the maintainer approves this note.

Scope: the "Any" (freeform) cutout of `appPlugins/ToolCutOut.py`, method `CutOut.on_freeform_cutout` (lines 671-970) and `any_cutout_handler` (972-1066).
Out of scope: the "Rectangular" cutout (`on_rectangular_cutout`, 1068 on), the manual gaps, the drill-cut and the Tcl commands `TclCommandCutout.py` and `TclCommandGeoCutout.py`. They keep their own code.

## 1. Problem

A board outline file often holds more than the outer edge. It can hold internal cutouts: a connector window, a slot, a round hole bigger than the drill range.

The freeform cutout cuts only around the outside, or only along the interior of one ring. It never cuts an internal contour on purpose.

What the code does now (`ToolCutOut.py`):

| Case | Lines | Gerber source | Geometry source |
|---|---|---|---|
| Source geometry | 743-751 | `gerber_cutout_geometry` (44-54): `fused_solid(obj)`, or its convex hull | `solid_geometry`, or the first tool of a multi-geo object |
| Single, collapse | 753-760, 768-770 | A `MultiPolygon` becomes its bounding box (`box`) | A `MultiPolygon` or `MultiLineString` becomes its bounding box |
| Single, margin >= 0 | 761-763, 773-777 | `buffer(margin + r).exterior` (`r` = cutter radius) | `buffer(margin).exterior` (no `r`) |
| Single, margin < 0 | 764-766, 778-782 | `buffer(-margin + r).interiors` | `buffer(1e-7).exterior.buffer(-margin).interiors` |
| Panel | 797-833 | Same formulas, applied to each part of `flatten_shapely_geometry(object_geo)`. Margin < 0 passes the whole `interiors` sequence to the gap code. | Same |
| Mouse bites | 846-892 | Same idea with `mb_dia / 2` in place of `r` | Single: no margin at all (lines 867-868). Panel: no buffer (lines 875-884). |
| Gaps and thin gaps | 972-1066 | `any_cutout_handler` cuts bridge boxes out of the path and returns the removed pieces | Same |

Consequences:

1. A hole inside a filled outline polygon is never cut. The user draws the slot by hand with another tool.
2. A slot drawn as its own closed outline inside the board is treated as another board in Panel mode (it gets a cut on the outside of the slot, which is inside the board material: wrong side) or is lost in Single mode (the bounding box swallows it).
3. The mouse-bite code uses a different offset from the main cut for a negative margin and for Geometry sources (lines 858-862, 867-868, 875-884). The main cut and the bites can be on different lines. This is an existing difference. The new path removes it by construction. The old path is not touched (section 2.1).

A hole in fused copper is often a clearance, not a slot. So the tool must not guess. A copper layer must never produce a slot cut.

## 2. Contracts

### 2.1 Switch and default

Two controls in the "Cutout" plugin UI (`CutoutUI`, `ToolCutOut.py:2263`), in the parameter frame next to "Convex Shape" (`convex_box_cb`, line 2435):

| Control | Name | Persistence | Default |
|---|---|---|---|
| Check box "Source is board outline" | `is_outline_cb` | Not saved. Reset to off whenever the user changes the object, the type (Gerber/Geometry) or the kind, and when the plugin opens (`set_tool_ui`, line 242). | Off |
| Check box "Cut inside contours" | `inner_cb` | Saved in the preferences as `tools_cutout_inner` (new key in `defaults.py` near line 561, mapped in `appGUI/preferences/PreferencesUIManager.py:490`, and in the Cutout preferences group). Not added to the Tools DB (`appDatabase.py`), because it is a property of the source file and not of the tool. | Off |
| Check box "Gaps on inner contours" | `inner_gaps_cb` | Saved as `tools_cutout_inner_gaps`. | Off |

Effective switch: `inner_active = is_outline_cb and inner_cb`. The controls are enabled as follows:

- `inner_cb` is enabled only when `is_outline_cb` is checked and the shape check box (`cutout_shape_cb`) is on "Any" (not "Rectangular").
- `inner_gaps_cb` is enabled only when `inner_active` is true.

When `inner_active` is false, `on_freeform_cutout` runs the existing code, unchanged, line for line. The old branch is not refactored and not "cleaned up". This guarantees that the default output stays the same (see the regression fixtures in section 4).

The option applies only to `on_freeform_cutout`. The "Rectangular" shape ignores it.

### 2.2 New code layout

To make the output testable without a running application, the change is made in two commits.

Commit 1 (no behavior change): move the geometry part of `job_thread` (lines 728-892: the choice of source geometry, the Single/Panel loops, the gaps, the mouse bites and the holes) into a module-level function in `ToolCutOut.py`:

```
def freeform_cutout_paths(cutout_obj, kind, cut_dia, margin, gaps, gapsize,
                          convex_box, gap_type, thin_entry, mb_dia, mb_spacing,
                          handler) -> CutoutResult
```

`handler` is the bound `CutOut.any_cutout_handler`. `CutoutResult` has the fields `solid_geo`, `gaps_solid_geo`, `holes` (list of mouse-bite points), `warnings` (list of strings) and `failed` (bool). `job_thread` calls the function and then runs the unchanged `geo_init` / `excellon_init` (lines 894-961). The function returns exactly what the old code computed. The `inform.emit` calls on failure stay in `job_thread`, driven by `failed` and `warnings`.

Commit 2 (the feature): add the new path inside `freeform_cutout_paths` and the three new functions below.

### 2.3 One function for the contour list

```
def outline_contours(source_geo, convex_box, kind) -> list[Contour]
```

`Contour` is a small named tuple: `ring` (the part that defines the contour: a `Polygon`), `depth` (int), `side` (`'outer'` or `'inner'`), `index` (order in the input, for a stable sort).

Main cuts, thin gaps and mouse bites all call `outline_contours` once per run and use the same list. No other code decides what a contour is.

The board area is built from the source records, not from the fused solid. This follows the 2 ways that CAD tools write an outline file (S9): closed contours drawn with an aperture (KiCad Edge.Cuts, Altium "profile as tracks"), or filled regions with cutouts (Altium "profile as contours").

Construction (`ContourSource` = the list of filled loops with their stroke width `w`):

1. **Stroked records** (Gerber, every aperture except the `REG` aperture 0): take the `follow` lines. `polygonize` them (after `linemerge` and `unary_union`, with a 1e-6 snap of the end points) into closed loops. Each loop gives `Polygon(loop)` with `w` = the aperture size. The band of the stroke (the fused solid) is not used, so the hole of a stroked ring never becomes a contour. A `follow` line that does not close is dropped with the warning "open path ignored".
2. **Region records** (Gerber aperture 0, type `REG`, clear polarity applied as in the parser): each region solid, with its holes, gives itself with `w = 0`.
3. **Geometry source**: a `Polygon` (with its holes) gives itself, `w = 0`. A closed `LineString` or `LinearRing` gives `Polygon(ring)`, `w = 0`. An open line is dropped with the same warning.
4. **Board area** `A` = the even-odd combination (successive `symmetric_difference`) of all items of steps 1 to 3. A point is board material when it is inside an odd number of contours. This is the usual fill rule for nested outline contours: board, slot, island in the slot, and so on.
5. **Contours**: every exterior ring of every part of `A` is a contour with side `'outer'`. Every interior ring of every part of `A` is a contour with side `'inner'` (a slot or a cutout).
6. **Depth**: for each ring, the number of other rings whose filled shape contains it (test with `representative_point`, see Risks). Even depth is outer, odd depth is inner. Step 5 and step 6 agree by construction. The depth is kept for the cut order (S6).
7. **Stroke width per contour**: `w` of the loop that made the ring (the nearest loop centerline within 1e-6). `w = 0` for a region or Geometry ring.

Result: a stroked slot ring inside a stroked board ring is a cutout. A hole inside a filled region of a file marked as an outline is also a cutout. A clearance in copper is a cutout only if the user marks a copper file as an outline, which the UI tells them not to do (S5).

### 2.4 Offsets with a signed margin

```
def offset_contours(contours, margin, radius, source_kind) -> list[list[LineString]]
```

One list of paths per contour, in the order of `contours`. `radius` is `abs(cut_dia) / 2` for the main cut, and `mb_dia / 2` for the mouse bites. A caller passes its own radius. `source_kind` is `'gerber'` or `'geometry'`. For Geometry the radius is ignored (as in the old code, which adds no cutter radius for Geometry).

Positive margin moves the path away from the board material on both outer and inner contours. Negative margin moves the path into the board material.

Each contour ring `R` has a stroke width `w` (section 2.3, step 7). Let `e = w / 2 + r` for a Gerber source and `e = 0` for a Geometry source (Geometry adds no cutter radius, as now). The offset distance `d`, measured away from the board material, is:

- margin `m >= 0`: `d = m + e` (the cutter is outside the stroke, on the waste side),
- margin `m < 0`: `d = m - e` (the cutter is inside the stroke, in the board material).

The path is:

| Side | Path |
|---|---|
| outer | `Polygon(R).buffer(d).exterior` (the board is inside `R`, so "away from material" is outward) |
| inner | `Polygon(R).buffer(-d).exterior` (the board is outside `R`, so "away from material" is inward, into the slot) |

A result that is a `MultiPolygon` gives 1 path per part (S3). An empty result drops the contour (S3).

Why the outer row equals the old formulas: for a round aperture, the outer edge of the stroke band is `Polygon(loop).buffer(w/2)`, so `band.buffer(m + r).exterior` equals `Polygon(R).buffer(w/2 + m + r).exterior`. The same holds for the inside edge and `m < 0`. For a region (`w = 0`) it is the old formula. A test pins the equality (CO-6). For a rectangle aperture the corners differ by less than the corner radius of the band. CO-6 uses a round aperture, and CO-6b checks a rectangle aperture against a tolerance of `w / 2`. The inner row is the mirror image.

Every result goes through `flatten_shapely_geometry`. Empty results are dropped (section 3, S3).

### 2.5 Gaps, thin gaps and mouse bites

After the offsets, each contour goes through `handler(path, abs(cut_dia), gaps, gapsize, margin)` (the existing `any_cutout_handler`), the way Panel mode already works part by part:

- outer contours: always, with the user's gap choice,
- inner contours: only when `inner_gaps_cb` is checked. Otherwise the path goes to the result without a call to the handler, and it contributes nothing to the thin-gap list or the bites.

Thin gaps (`gap_type == 1 and thin_entry != 0`) and mouse bites (`gap_type == 2`) use the second return value of the handler, as now. Mouse bites call `offset_contours` again with `radius = mb_dia / 2` on the same contour list. Then they call the handler with `gapsize - abs(cut_dia) / 2`, as in line 848.

The gap size and the position of gap boxes come from the bounds of each contour (`any_cutout_handler` uses `recursive_bounds` of the path, lines 977-981). A gap on a slot is therefore centered on that slot.

### 2.6 Order of cuts

`solid_geo` lists the contours by `depth` from deepest to shallowest, and by `index` inside one depth. Reason in S6.

### 2.7 Single/Panel, convex hull, Gerber/Geometry

These choices stay as they are now, with the rules in section 3 for the cases that the option creates. Cutter-radius rules stay: Gerber adds `r`, Geometry does not.

## 3. Settled questions

**S1. What does the convex hull do to marked inner contours?**
Decision: nothing. The hull is applied only to outer contours. Inner contours (and the islands at even depth 2 or more) keep their own shape.
In Single mode: if the check box "Convex Shape" is on, the hull is `unary_union([parts at depth 0]).convex_hull`. It replaces the depth-0 parts as one outer contour. In Panel mode: each depth-0 part is replaced by its own hull.
Reason: a hull of a slot would fill the slot, and a hull of a part would cover the slot's area, so slots would be lost if the hull ran on the whole fused copper before the tree. The tree is built from the un-hulled geometry (section 2.3, step 1). The hull applies afterwards and only to the contours that the user wants as a convex outer cut.
This differs from the old order for Gerber (`gerber_cutout_geometry` hulls first). The old order stays for `inner_active == False`.

**S2. Do gaps and mouse bites apply to slots by default?**
Decision: no. The check box "Gaps on inner contours" is off by default. When the user turns it on, gaps, thin gaps and mouse bites apply to the inner contours with the same settings as the outer ones.
Reason: gaps (bridges) keep the board attached to the surrounding stock. A slot has no stock around it, and the piece inside the slot is waste. A bridge there would keep the waste in place. Some users want that for large internal windows, so the choice exists. A new option is needed because the user must be able to ask for it without changing the outer settings.

**S3. What happens when compensation closes a narrow slot, or splits a contour?**
Decision:
- Closed: if the offset path of an inner contour is empty, drop the contour. Add one warning to the result: `"N inner contours were skipped: the slot is narrower than the cutter plus margin."` The run continues. The warning goes through `app.inform.emit('[WARNING_NOTCL] ...')` once, after the run.
- Split: if a buffer returns a `MultiPolygon` (one contour becomes two or more), keep every part. Each part is a path. The gap code runs per path. The depth and side stay the same as those of the source contour. The old Geometry Panel code reports "Failed" in this case (lines 816-820). The new path does not.
- If all contours of the run are dropped, the result is empty and the run fails as now (line 835-838).
Reason: a missing slot should not fail the whole cutout, but the user must know. A split is a valid result of a negative offset.

**S4. How does Single mode handle more than one disjoint outer contour?**
Decision: Single keeps its meaning of "one PCB outline". If there is more than one depth-0 part, the outer contour is the bounding box of all of them, as the old code does for a `MultiPolygon` (lines 758-760, 768-770), and the tool adds the warning `"Single mode with several outlines: using one bounding box. Use Panel to cut each board."`.
All inner contours are still cut, and so are islands (even depth 2 or more). The slots of every board are inside the bounding box, so they stay valid.
Reason: this keeps the Single/Panel contract and makes the choice visible. Silent switching to Panel would change the word "Single" without telling the user.

**S5. What is "marked as outline"?**
Decision: the check box `is_outline_cb` (section 2.1), set by the user for each run. It is not stored, so a stale setting cannot turn a copper layer into slots. Its tooltip says: "Check only for a board outline (profile, Edge.Cuts, GKO/GM1) file. Every hole and every inner closed contour in it is cut as a cutout."
Optional help, not a guess: if the Gerber file has the X2 attribute `%TF.FileFunction,Profile*%`, the check box is checked when the object is selected. The user can uncheck it. Without that attribute the check box starts off.
Today `Gerber.parse_file` removes every `%TF.` line before parsing (`appParsers/ParseGerber.py:464-470`), so the attribute is lost. Change: before that removal, read the first `%TF.FileFunction,...*%` line and store its value list (for example `['Profile', 'NP']`) in `obj_options['file_function']`. `obj_options` is saved in the project, so a reopened project keeps it. An empty list when there is no attribute. This is a separate small commit, with its own test (CO-8d covers the use).
Reason: the plan forbids guessing. File names are not reliable. The X2 attribute is an explicit statement in the file.

**S6. Why this cut order?**
Decision (maintainer approved): deepest contours first, outer contours of depth 0 last. For the same depth, input order. The order is fixed. There is no option.
Reason: this is the usual routing practice. The board stays held by the stock while the inside is cut, so it cannot move. If the outer cut ran first, the board would hang only on its gaps, and the inner cuts would push it. Islands (depth 2) are cut before the slot around them, so the island is cut while it is still held. An option would only let the user choose a worse order.
The merge step `linemerge(solid_geo)` (line 841) runs on a list in this order, as now.

**S7. Which reference line for the margin of a Gerber outline drawn with lines?**
Decision: as in the old code. The stroke belongs to the board. Outer contours use the outside edge of the stroke for margin >= 0 and the inside edge for margin < 0. Inner contours use the inside edge of the slot ring for margin >= 0 and the outside edge for margin < 0 (section 2.4, `e = w/2 + r`).
Reason: this keeps outer results identical to the old results, and the inner rows are the mirror image.
Note: many board houses take the center line of the outline stroke as the board edge. A user who wants that sets the margin to `-w/2`. No new option.

**S9. Does a hole inside a filled region count as a cutout? (maintainer question)**
Decision: yes, when the file is marked as an outline. No, when it is not marked (the option is then off, section 2.1).
Reason:
- CAD tools write internal cutouts in 2 ways. KiCad has only the Edge.Cuts layer for the board edge and every cutout, and each one must be its own closed contour. Altium writes the board profile as a closed path and adds 1 polygon for each board cutout, or it writes the profile as tracks. So a file can hold cutouts as separate closed strokes or as holes and clear areas in filled regions. Both mean the same thing: no board material there.
- The old reason for "no" was the stroked ring: its fused band has a hole that is the board itself. Section 2.3 removes that problem at the source. It uses the center lines of strokes and never the band. So the rule "a hole in the board area is a cutout" is safe for both kinds of outline file.
- The even-odd rule (section 2.3, step 4) gives the same result for both kinds: board, cutout, island, cutout in the island, and so on.
- Copper safety stays with the mark (S5). A copper file is never marked by the tool itself, except through the explicit X2 Profile attribute.

**S8. Rectangular cutout.**
Decision: the option is disabled when "Rectangular" is selected, and `on_rectangular_cutout` is not changed.
Reason: that mode cuts the bounding box. It has no contours.

## 4. Acceptance tests

New files:

- `tests/test_cutout_inner_contours.py` (pure functions and the production job),
- `tests/fixtures/cutout/` (small Gerber files, section below) and `tests/fixtures/cutout/golden_*.json` (output of the old code).

Regression fixtures, recorded **before any code change** (commit 0 of the implementation, with only tests and fixtures):

Run the current `on_freeform_cutout` on each fixture with the option absent. Save `solid_geo`, `gaps_solid_geo` and `holes` as WKT, with coordinates rounded to 6 decimals, in `golden_<name>.json`. The tests of commit 1 and commit 2 must reproduce these files exactly (WKT equality after rounding, or `symmetric_difference.area < 1e-9`).

Gerber fixtures (`tests/fixtures/cutout/`, all in mm, 0.2 mm stroke where lines are used):

| File | Content |
|---|---|
| `outline_single.gbr` | Closed ring 50 x 30, drawn with one aperture. |
| `outline_slot.gbr` | Same ring plus one closed slot ring 10 x 3 inside it. |
| `outline_island_slot.gbr` | Ring 50 x 30, slot ring 20 x 12, small ring 4 x 4 inside the slot (island). |
| `outline_panel2.gbr` | Two rings 40 x 25, 10 mm apart, the second with a slot ring 8 x 3. |
| `copper_clearance.gbr` | A filled region 40 x 25 with a rectangular hole 6 x 6 (a clearance). |
| `outline_region_cutout.gbr` | Board drawn as 1 filled region 50 x 30 (G36/G37) with a clear-polarity region 10 x 3 inside it (`%LPC*%`), the way a profile written as contours holds a cutout. |
| `outline_region_x2.gbr` | `outline_region_cutout.gbr` with the attribute `%TF.FileFunction,Profile,NP*%`. |
| `outline_rect_aperture.gbr` | `outline_slot.gbr` drawn with a 0.2 mm rectangle aperture. |
| `outline_narrow_slot.gbr` | Ring 30 x 20 plus a slot ring 4 x 1.0 (inside width 0.6 mm). |

Geometry inputs (`Geometry` objects built in memory with `shapely`, as `tests/test_geometry_plot_layer.py` does): `geo_single` (a closed polygon), `geo_slot` (the polygon plus an inner closed polygon), `geo_panel2`.

The production path: tests run `CutOut.on_freeform_cutout` on the headless application fixture (`app` from `tests/test_unify_characterization.py`, as `tests/test_fused_solid_cutout.py` does). They patch `app.worker_task.emit` so that it calls `fcn(*params)` inline, and then read the created object `<name>_cutout` from `app.collection`. Pure-function tests call `outline_contours`, `offset_contours` and `freeform_cutout_paths` directly.

| ID | Test name | Fixture and check |
|---|---|---|
| CO-1 | `test_off_single_gerber_matches_golden` | `outline_single.gbr`, kind Single, margin 0.1, tool 2.4, gaps `4`. Equals `golden_single_gerber.json`. |
| CO-2 | `test_off_panel_gerber_matches_golden` | `outline_panel2.gbr`, kind Panel. Equals golden. |
| CO-3 | `test_off_single_and_panel_geometry_match_golden` | `geo_single`, `geo_panel2`. Equals golden for both kinds. |
| CO-4 | `test_off_negative_margin_matches_golden` | `outline_single.gbr`, margin -0.3, Single and Panel. Equals golden. |
| CO-5 | `test_off_gaps_thin_and_bites_match_golden` | `outline_single.gbr` with gap type Thin gaps and then Mouse bites (`holes` list). Equals golden. |
| CO-6 | `test_outer_offset_equals_old_formula` | For margin 0.1 and -0.3 and for Gerber and Geometry: `offset_contours` on the single outer part equals the old expression (copied into the test as a pinned legacy helper, like `legacy_cutout_geo` in `tests/test_fused_solid_cutout.py`). |
| CO-7 | `test_option_on_without_outline_mark_is_legacy` | `outline_slot.gbr`, `inner_cb` on, `is_outline_cb` off. Output equals the old output for the same file (no slot cut). |
| CO-6b | `test_outer_offset_rect_aperture_close_to_old` | `outline_rect_aperture.gbr`: the outer path is within `w / 2` of the old path (Hausdorff distance). |
| CO-8 | `test_copper_with_clearance_gives_no_slot` | `copper_clearance.gbr`, option on, file NOT marked. Output equals the old output. No path lies inside the 6 x 6 hole. |
| CO-8b | `test_region_hole_is_cutout_when_marked` | `outline_region_cutout.gbr`, marked, option on. 2 contours: outer and 1 inner. The inner path is inside the 10 x 3 cutout at distance `m + r` from its edge. |
| CO-8c | `test_stroked_ring_hole_is_not_a_cutout` | `outline_single.gbr`, marked, option on. Exactly 1 contour (outer). No path inside the board. This is the stroked-band case of S9. |
| CO-8d | `test_x2_profile_attribute_checks_the_mark` | Select `outline_region_x2.gbr`: `is_outline_cb` is checked. Select `outline_region_cutout.gbr` (no attribute): it is off. Select `copper_clearance.gbr`: it is off. |
| CO-8e | `test_even_odd_board_slot_island_slot` | 4 nested stroked rings. Sides: outer, inner, outer, inner. Depths 0 to 3. Order: depth 3, 2, 1, 0. |
| CO-9 | `test_outline_with_slot` | `outline_slot.gbr`, Single, option on, marked. Two paths: the outer path outside the ring, and one slot path inside the slot opening. Distance from the slot path to the stroke inner edge is `margin + r`, within 1e-6. |
| CO-10 | `test_panel_of_two_boards` | `outline_panel2.gbr`, Panel, marked. Three contours: two outer, one inner. The inner path lies inside board 2 only. |
| CO-11 | `test_island_in_slot` | `outline_island_slot.gbr`. Depths 0, 1, 2. Sides outer, inner, outer. Cut order is island, slot, board (S6). |
| CO-12 | `test_negative_margin_moves_into_board` | `outline_slot.gbr`, margin -0.3. The outer path is inside the board (inside edge of the stroke minus 0.3 and `r`). The slot path is outside the slot ring in the board material. |
| CO-13 | `test_single_with_two_outer_uses_bbox` | `outline_panel2.gbr`, Single, marked. One outer path equal to the bounding-box path. The slot of board 2 is still cut. The warning text of S4 is in `result.warnings`. |
| CO-14 | `test_single_vs_panel_differ_only_in_outer` | The same file in Single and in Panel (one board): equal output. |
| CO-15 | `test_gerber_adds_radius_geometry_does_not` | `outline_slot.gbr` and `geo_slot`, same margin. Inner path distance to the slot edge is `m + r` for Gerber and `m` for Geometry. |
| CO-16 | `test_gaps_not_on_slots_by_default` | `outline_slot.gbr`, gaps `4`, `inner_gaps_cb` off. The slot path is one closed ring (no gap). The outer path has 4 gaps. |
| CO-17 | `test_gaps_on_slot_when_enabled` | `inner_gaps_cb` on. The slot path is split by 4 gaps. The gap pieces are centered on the slot center. |
| CO-18 | `test_thin_gaps_and_mouse_bites_on_slot` | Gap type Thin gaps: `gaps_solid_geo` has pieces on the slot. Gap type Mouse bites: `holes` has points on the slot path at spacing `mb_dia + mb_spacing`, when `inner_gaps_cb` is on, and none when it is off. |
| CO-19 | `test_one_contour_list_for_all_outputs` | Spy on `outline_contours`. In a run with a main cut, thin gaps and mouse bites, it is called once. The bites use the same contour objects. |
| CO-20 | `test_narrow_slot_is_skipped_with_warning` | `outline_narrow_slot.gbr`, tool 2.4. The slot is dropped, the outer cut is present, the warning of S3 is in the result. |
| CO-21 | `test_contour_split_keeps_all_parts` | A dumbbell-shaped slot and a negative margin that splits it. Two paths. No exception. |
| CO-22 | `test_convex_hull_only_outer` | `outline_slot.gbr` with an L-shaped outer ring and "Convex Shape" on. The outer path is the hull. The slot path equals the path without the hull. |
| CO-23 | `test_open_path_in_geometry_is_ignored` | A `Geometry` with a closed polygon and an open line. One contour, one warning. |
| CO-24 | `test_rectangular_ignores_option` | Rectangular shape with the option on. Output equals the output with the option off. |
| CO-25 | `test_option_defaults_and_ui_state` | `tools_cutout_inner` and `tools_cutout_inner_gaps` are `False` in `AppDefaults.factory_defaults`. `inner_cb` is disabled while `is_outline_cb` is off. Changing the source object resets `is_outline_cb`. |
| CO-26 | `test_does_not_mutate_source_object` | After any run the source object's `solid_geometry` is the same object and has the same WKT (the old Gerber helper mutated it; see `tests/test_fused_solid_cutout.py::test_does_not_mutate_the_object`). |

## 5. Risks

- **Moving `job_thread` code (commit 1) can change output by accident.** The golden fixtures (CO-1 to CO-5) are recorded first and must pass unchanged after commit 1. If a golden file changes, commit 1 is wrong.
- **Old and new paths are two copies of similar code.** This is intended: the old path must not change. A later cleanup can merge them after the golden tests are in place for a release.
- **Stroke center lines that do not close.** CAD exports can leave a small gap between segments. Step 1 of section 2.3 snaps end points within 1e-6 only. A larger gap gives an open line, which is dropped with a warning. Then the board or the slot is missing. Mitigation: the warning names the aperture and the gap position. A larger snap tolerance is not added, because it can join lines that must stay apart.
- **No inner contour found.** When `inner_active` is on and the result has zero inner contours, show the warning "No inner contour found. Is this a board outline file?".
- **Two board rings that overlap.** A Panel with overlapping boards fuses into one part. This is the same as today.
- **Numeric edge of `contains`.** A slot ring that touches the board ring exactly is not "contained". Use `Polygon(P.exterior).representative_point()` inside the shell of `Q` with a tolerance of 1e-9, not `contains` on the full polygons, to avoid boundary noise. CO-11 includes a case with a shared point.
- **`gap` boxes use the bounds of the path.** On a very small slot, a gap box that is larger than the slot removes the whole path. The handler returns an empty list. Treat an empty result for an inner contour as a skipped contour (S3).
- **Cut order and `linemerge`.** `linemerge` can join lines of different contours that share an end point and change the order. It does so today for Panel. The golden tests pin the old order. For the new path, CO-11 checks the order after the merge.
- **Tools DB.** The option is not stored in the Tools DB. A tool loaded from the DB leaves the check boxes as they are.
- **Existing mouse-bite mismatch (section 1, point 3).** The old path still has it. The new path does not. A release note should say this.

## 6. Maintainer decisions

1. A hole inside a filled region of a file marked as an outline is a cutout (S9). Contours come from stroke center lines and region records with the even-odd rule (section 2.3), so the hole of a stroked band never becomes a cutout.
2. Cut order: deepest first, board outline last. Fixed, no option (S6).
3. Gaps and mouse bites on inner contours: off by default, with the check box "Gaps on inner contours" (S2).
