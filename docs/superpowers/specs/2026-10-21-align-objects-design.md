# Align Objects — upgrade design

Date: 2026-10-21. Branch: 1.0.

## Goal

Make the Align Objects plugin fast, correct and more capable:

- Fix the click and rotation defects.
- Snap clicks through a spatial index, not a Python loop over all features.
- Apply one affine matrix one time per alignment.
- Accept Gerber, Excellon and Geometry objects.
- Add a 2-point mode with uniform scale and a best-fit mode for 3 or more point pairs.
- Show markers for the clicked points. Add one Undo step.

## Defects in the current code (`appPlugins/ToolAlignObjects.py`)

1. `on_mouse_click_release` scans all features for each click. Overlapping features add more than 1 point for 1 click.
2. `align_rotate` uses `math.atan`. A rotation near 180° gives a wrong angle.
3. `align_rotate` skips the rotation if only the X values or only the Y values of START and DESTINATION are equal (`or`).
4. `except Exception: pass` hides a division by zero when `dxd == 0` or `dxs == 0`.
5. Translate and rotate do 2 passes over the geometry. `plot_all()` plots all objects.

## Structure (MVC, as ToolPaint and ToolNCC)

The single file `appPlugins/ToolAlignObjects.py` is replaced by the folder `appPlugins/ToolAlignObjects/`:

| File | Part | Content |
|---|---|---|
| `__init__.py` | — | empty |
| `Align.py` | controller | `AlignObjects(AppTool)`: signals, mouse and key events, state, markers, apply, Undo |
| `AlignUI.py` | view | `AlignUI`: widgets and layout |
| `AlignGen.py` | model | pure functions: snap index, snap, solvers, residuals, inverse. No Qt imports. |

`appPlugins/__init__.py:13` changes to `from appPlugins.ToolAlignObjects.Align import AlignObjects`. No other module imports the class.

## Model — `AlignGen.py`

All matrices are the Shapely 6-tuple `(a, b, d, e, xoff, yoff)`: `x' = a*x + b*y + xoff`, `y' = d*x + e*y + yoff`.

### Snap index

`build_snap_index(obj) -> SnapIndex`

- Gerber: the solids of the dark flashes (`rec.polarity == 'dark'` and `rec.follow` is a `Point`) from `iter_features(obj)`, plus the vertices of all solids.
- Excellon: the solids of all drills and slots from `iter_features(obj)`, plus their vertices.
- Geometry: no feature solids. Only the vertices of the solid geometry of all tools (for a multigeo object) or of `solid_geometry`.
- The solids go in a `shapely.STRtree`. The centers (centroids) and areas go in NumPy arrays that use the same order. The vertices go in an `(N, 2)` NumPy array.

`snap(index, x, y, tol) -> (x, y) | None`

1. The function queries the STRtree with `predicate='contains'` for the click point. If one or more solids hold the point, it returns the center of the solid with the smallest area. So 1 click always gives at most 1 point.
2. If not, it finds the nearest vertex with a vectorized distance. If that distance is `<= tol`, it returns the vertex.
3. If not, it returns `None`.

The controller gives `tol` in data units: 10 px divided by the current canvas scale.

### Solvers

The inputs `P` (START points) and `Q` (DESTINATION points) are `(N, 2)` arrays. Each solver returns a matrix or raises `AlignError` with a message for the user.

| Function | Pairs | Model |
|---|---|---|
| `solve_translate(P, Q)` | 1 | `Q[0] - P[0]` |
| `solve_rigid(P, Q)` | ≥ 2 | Kabsch/Umeyama without scale; reflection is not allowed; angle from `atan2` |
| `solve_similarity(P, Q)` | ≥ 2 | Umeyama with uniform scale |
| `solve_affine(P, Q)` | ≥ 3 | `numpy.linalg.lstsq` on the 6 parameters |

Degenerate inputs raise `AlignError`:

- Rigid and similarity: all START points are at the same position (variance of P is about 0).
- Similarity: the scale is `<= 0` or not finite.
- Affine: fewer than 3 pairs, or the START points are on one line (rank of the centered P is less than 2), or the determinant `a*e - b*d` is about 0.

For exactly 2 pairs, rigid gives the same angle as the old 2-point mode (now always correct). The old mode put START 1 exactly on DESTINATION 1. The least-squares fit splits a difference in pair length between the 2 pairs, so neither pair has all the error.

`residuals(matrix, P, Q) -> (errors, rms)`: the distance from the transformed P to Q for each pair, and the root mean square value.

`invert(matrix) -> matrix`: the inverse affine matrix. It raises `AlignError` if the determinant is about 0.

## View — `AlignUI.py`

The current widgets stay: the object type and combo box for the aligned object and for the aligner object. The changes:

- The object type radio buttons get a third value: `geo` (Geometry). Index in the collection: Gerber 0, Excellon 1, Geometry 2 (check the order in `ObjectCollection` during the implementation).
- The mode radio buttons (`a_type_radio`) have 4 values:
  - `sp`: 1 point (translate)
  - `dp`: 2 points (rigid)
  - `dps`: 2 points + scale (similarity)
  - `fit`: best fit
- A `fit_model` combo box (Rigid, Similarity, Affine) shows only in `fit` mode. Default: Rigid.
- A table of the point pairs: columns `#`, START X/Y, DESTINATION X/Y, Error. The table fills while the user clicks.
- Buttons: "Align Object" (start the pick), "Apply" (only in `fit` mode, enabled when there are enough pairs), "Undo" (enabled after an alignment), "Reset Tool".
- A label shows RMS and the maximum error after a fit.

## Controller — `Align.py`

### Pick workflow

1. "Align Object" reads the 2 objects. It builds 2 snap indexes (aligned and aligner). It turns off grid snap and keeps its old state. It connects the mouse and key events. It sets the highlight color on the aligned object.
2. The user clicks pairs in turn: START on the aligned object, then DESTINATION on the aligner object. The highlight color moves to the object that the next click must hit. A click that snaps to nothing shows a warning and adds no point.
3. Keys during the pick:
   - Backspace removes the last point.
   - Enter is the same as "Apply" in `fit` mode.
   - Esc cancels. A right click (with no drag) also cancels.
4. End of the pick:
   - `sp`: after 1 pair.
   - `dp`, `dps`: after 2 pairs.
   - `fit`: on Enter or "Apply". It needs at least 2 pairs for Rigid and Similarity, and 3 pairs for Affine.
5. The controller calls the solver. If it raises `AlignError`, the controller shows the message and keeps the points, so the user can add or remove a point. It does not apply a matrix.

### Apply

- The controller applies the matrix one time to the aligned object, with the same matrix path that `ToolTransform` uses (`camlib.affine_geometry`, `affine_geometry_many`, `Geometry._affine_solid_geometry` and the Gerber and Excellon equivalents). Find the correct entry point for each object type during the implementation. If one type has no matrix entry point, add a small function that does it. Do not add a mixin.
- After the apply, it updates `obj_options['xmin'|'ymin'|'xmax'|'ymax']` from `obj.bounds()`. It plots only the aligned object, not `plot_all()`.
- It shows the residuals in the table and RMS / maximum error in the label and the status bar.
- It keeps `(aligned_obj, matrix)` as the Undo state.

### Undo

"Undo" applies `invert(matrix)` to the same object through the same apply path. Then it clears the Undo state and disables the button. If the object is no longer in the collection, the controller clears the Undo state and shows a warning.

### Markers

- A temporary shape collection from `self.app.plotcanvas.new_shape_collection(layers=1)`, as in `ToolDistance`.
- A START point is a small cross in one color. A DESTINATION point is a small circle in a different color. A line joins each pair. The marker size is in pixels and comes from the canvas scale.
- Backspace removes the marker of the last point. Cancel, the end of the alignment and `set_tool_ui` clear all markers.

### Clean-up

`disconnect_cal_events` restores grid snap, the app mouse handler and the colors of the 2 objects. It disconnects the key handler and clears the markers. The colors are always restored, also on cancel and on a solver error that ends the pick.

## Preferences

- `tools_align_objects_align_type` keeps its key. The values `sp` and `dp` keep their meaning. The new values are `dps` and `fit`.
- New key `tools_align_objects_fit_model`, default `'rigid'`. Values: `rigid`, `similarity`, `affine`.
- If a stored value is not known, the controller uses the factory default.

## Tests — `tests/test_align_objects.py` (unittest)

1. Solvers round trip:
   - A known matrix makes Q from P. The solver must find the same matrix (tolerance 1e-9).
   - Angles: 0°, 90°, 180°, −179°, 45°.
   - Uniform scale 0.98 and 1.02 for similarity.
   - X/Y scale and skew for affine.
2. Noise: with small random noise on Q, the RMS from `residuals` is about the noise level.
3. Degenerate inputs raise `AlignError`: same START points, collinear points for affine, too few pairs.
4. `invert`: `invert(m)` after `m` gives the identity.
5. Snap:
   - 2 overlapping pads give 1 point (the center of the smaller pad).
   - A click near a vertex but in no feature gives the vertex.
   - A click far from all gives `None`.
   - A Geometry object snaps to vertices.
6. Controller (headless, as the other plugin tests): align a small Gerber to a small Excellon in `dp` mode. Check the bounds after the apply. Check that Undo gives the original bounds.

## Automatic mode (added 2026-10-21)

Mode `auto`. The user clicks "Find". The tool finds the matrix that puts the most START centers (holes or pads of the aligned object) inside the features of the aligner object. No scipy: NumPy and the Shapely `STRtree` only.

`AlignGen.auto_align(src_index, dst_index, model, allow_mirror, max_results, progress) -> list[AutoResult]`:

1. The current position (identity) is always a candidate.
2. Rotation candidates: a histogram of the angle differences between the nearest-neighbor vectors of the 2 sets (0.5° bins). It keeps 4 peaks, and each peak is also tested + 180°.
3. Translation candidates: for each rotation, a vote of the offsets from a sample of 50 START centers to all aligner centers. The cell size is the median pad radius. It keeps 3 peaks.
4. ICP refine: pair each center with the nearest aligner center within 2 radii, solve, repeat 5 times. The first 2 steps are rigid. The other steps use the selected model.
5. Score: the number of START centers inside an aligner solid. If the scores are equal, the smaller RMS wins, then the smaller move.
6. Distinct candidates only (the bounding box corners differ by more than 1 radius). `is_ambiguous(results)` is true if the second score is at least 95 % of the best score.

"Allow mirror" also tests the START set mirrored (x → -x), for a bottom layer. The search runs in a worker. The result reaches the GUI thread through the signal `auto_finished(token, results, error)`. "Next candidate" cycles the results. "Apply" applies the current candidate with Undo.

New preference key: `tools_align_objects_allow_mirror`, default `False`.

## Out of scope

- An app-level Undo system.
- More than one aligned object in one alignment.
- A preferences panel for the new keys (no panel exists for the current key).
