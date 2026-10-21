# Geometry Editor CAD Improvements — Execution Plan

> **For agentic workers:** Use the subagent-driven-development workflow. The parent authors and saves this plan before dispatching `sex-sol` agents. Execute one ticket at a time where files overlap. No commits unless the user requests them.

**Goal:** Make the existing geometry editor a dependable precision drafting and contour-editing tool through small, independently verifiable tickets.

**Architecture:** Retain AppGeoEditor, its tool plugins, Shapely geometry, current storage/index, and the existing canvas. Reuse the existing DXF source/export path. Persistent analytic CAD entities and a constraint solver are separate architectural decisions, not implicit parts of this incremental execution.

**Tech stack:** Python, PyQt6, Shapely, existing ezdxf, existing test infrastructure, `.venv/Scripts/python.exe`.

## Scope and execution rules

- Preserve existing selection, multigeometry tool ownership, units, and project compatibility.
- Before each edit, inspect callers and blast radius through jCodeMunch. Read the current target immediately before patching it.
- Each ticket follows: reproduce/characterize; add a focused regression; run it; implement the smallest change; run the ticket and relevant existing checks; update this document with evidence.
- No new dependencies, global editor rewrite, constraint solver, or unsolicited file-format migration.
- Don't mistake construction-point Backspace for committed-operation undo.
- Tests must exercise behavior or geometry, rather than merely check that particular source strings exist.
- Use existing headless test helpers. Set `QT_QPA_PLATFORM=offscreen` when creating Qt widgets.
- If an implementation needs a major architecture change, stop that ticket and record the narrow decision required. Continue independent executable tickets.
- Agents report exact files, commands, results, pre-existing changes, and remaining problems. The parent reviews the diff and verifies before marking complete.

## Baseline established by the parent

- Working tree was clean before planning.
- `.venv/Scripts/python.exe` and the requested plan directory exist.
- Editor operations and shapes live in `appEditors/appGeoEditor.py`; parameter panels live in `appEditors/geo_plugins/`.
- `AppGeoEditor.snap` currently combines stored-vertex snapping and grid snapping.
- Window/crossing selection and numeric path length input already exist and must remain intact.
- Circle/arc creation currently produces sampled Shapely paths. Editor commit writes geometry rather than persistent analytic entity definitions.
- `GeometryObject.source_exporter = 'export_dxf'` already exists. `GeometryObject.export_dxf()` emits polylines from current geometry.
- `tests/test_stage4_regenerate_source.py::test_geometry_stores_the_dxf_export` already checks that source regeneration stores DXF output. Verify serialization and edit-finish routing before adding any new source storage.

## Ticket status

| Ticket | Outcome | Dependencies | Status |
| --- | --- | --- | --- |
| GEO-01 | Characterize history, edit lifecycle, shortcuts, and DXF source | None | Complete (investigation and headless characterization; GUI not exercised) |
| GEO-02 | Transaction-based committed-operation undo/redo | GEO-01 | Complete — reviewer approved; 59 history tests |
| GEO-03 | Reliable cancellation and numeric input boundaries | GEO-01 | Complete — reviewer approved per GEO-04 handoff |
| GEO-04 | Midpoint/nearest snaps and consistent acquisition | GEO-01 | Complete — reviewer approved per GEO-05 handoff |
| GEO-05 | Numeric vertex editing | GEO-02 | Complete — reviewer approved per GEO-06 handoff |
| GEO-06 | Split paths at a selected point | GEO-02, GEO-04 | Complete — reviewer approved per GEO-07 handoff |
| GEO-07 | Join selected open paths with explicit tolerance | GEO-02 | Complete — reviewer approved per GEO-09 handoff |
| GEO-08 | Non-destructive contour diagnostics | GEO-01 | Complete — reviewer approved per GEO-09 handoff |
| GEO-09 | Keep editable DXF source synchronized after editor save | GEO-01 | Complete — fresh reviewer approved per GEO-10 dispatch |
| GEO-10 | Integration regression and delivery review | GEO-02 through GEO-09 | Complete — fresh final reviewer approved automated delivery; unrelated application-history checks not green |

### Final parent acceptance

A fresh independent `sex-sol` final reviewer approved GEO-10 after reproducing the full focused geometry/editor/source/DXF suite: **526 passed**. The reviewer also independently reproduced the unrelated application-history integration failures: standalone history passed 17 tests; combined refactor/history execution had 2 failures and 17 setup errors. This approval doesn't claim a fully green repository or completed manual GUI validation. No commits were created. All fresh-agent requests after the user's fresh-agent instruction used new sessions.

## GEO-01 — Characterize integration points

**Scope:** Establish the real application routes before changing shared editor behavior. This is an investigation and regression ticket, not authorization to restructure the editor.

**Files:** `appEditors/appGeoEditor.py`, `appObjects/GeometryObject.py`, `appObjects/AppObjectTemplate.py`, `appHandlers/appIO.py`, actual keyboard/edit-finish handlers located by symbol references; existing `tests/test_geo_editor_*.py`, `tests/test_stage4_regenerate_source.py`.

- [x] Trace add/delete/replace/transform/boolean/tool-complete mutations and asynchronous completion. Identify the smallest common history integration points.
- [x] Locate keyboard dispatch and existing undo/redo support. Document text-entry focus handling and canvas backends.
- [x] Trace edit enter/save/cancel, source regeneration, project serialization, and DXF reimport.
- [x] Run existing editor and source tests; record exact baseline commands and results below.
- [x] Add a short integration map and identify genuine architectural blockers before implementing dependent tickets.

**Acceptance:** Every later ticket has confirmed target symbols and runnable verification. Existing DXF storage is reused if sound. Missing routing details are resolved here rather than guessed in implementation.

## GEO-02 — Undo/redo complete editing operations

**Files:** `appEditors/appGeoEditor.py`, confirmed keyboard handler from GEO-01, `tests/test_geo_editor_history.py` (new); an existing history module only if one is found.

- [x] Add behavioral tests: add/delete/move undo and redo; a multi-shape boolean is one step; new edit clears redo; cancelled preview creates no history.
- [x] Reuse an existing history stack, or use Qt's existing undo facilities where compatible. Record inserted/removed/replaced committed shapes with selection restoration; do not record rendering or utility previews. Existing geometry editor has no stack; current worker-thread commits aren't compatible with GUI-thread QUndoStack ownership, so use editor-local delta lists under the same operation lock.
- [x] Route all confirmed committed geometry mutation paths through the transaction boundary. Account for workers completing an operation and avoid nested duplicate entries.
- [x] Connect Ctrl+Z and Ctrl+Y/Ctrl+Shift+Z without stealing shortcuts from focused text inputs. Reset history at edit session boundaries.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py` plus existing delete/copy/move/editor performance regressions identified in GEO-01.

**Acceptance:** Undo/redo restores geometry, storage indices, tree/selection, and plot consistently. Whole operations are atomic. Imported pre-existing geometry isn't an undoable drawing action. No cross-session history.

## GEO-03 — Cancellation and numeric input boundaries

**Files:** `appEditors/appGeoEditor.py` (`FCPath.on_key`, drawing-tool cleanup and completion), relevant geo tool plugins and actual key dispatch; `tests/test_geo_editor_input.py` (new).

- [x] Characterize Enter/Escape/Backspace and tool-switch behavior for path, circle, rectangle, move, and copy.
- [x] Add tests for Enter before the first point, zero-length input, invalid/non-finite numeric input, and Escape after partial construction.
- [x] Fix confirmed failures locally. Cancellation removes previews and temporary signal connections but leaves committed geometry untouched. Backspace only removes construction points.
- [x] Preserve existing coordinate jump and valid numeric length behavior. Ensure error messages describe what the user must correct.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_input.py` and affected existing tool tests.

**Acceptance:** Invalid or incomplete input doesn't raise an unhandled exception or commit malformed geometry. Switching/cancelling a tool leaves a usable editor.

## GEO-04 — Improve snapping without inventing curve semantics

**Files:** `appEditors/appGeoEditor.py` (`snap` and motion/preview route), existing geometry preference UI/defaults only where a setting is needed; `tests/test_geo_editor_snapping.py` (new).

- [x] Preserve existing grid and corner behavior with regression tests, including grid spacing zero and empty storage.
- [x] Add explicit midpoint and nearest-on-segment candidates for existing line/polyline geometry. Keep these modes opt-in and use the existing UI style.
- [x] Use canvas conversion for screen-space candidate acquisition where supported. Keep an explicit compatibility fallback for contexts without a live canvas and preserve existing snap-distance preferences.
- [x] Provide active snap feedback and deterministic priority/tie handling. Don't label polygonized curve samples as exact analytic centers or tangencies.
- [x] Test midpoint, projection onto a segment, zoom-consistent acquisition, competing candidates, disabled modes, and empty geometry.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_snapping.py` plus existing snapping/canvas tests.

**Acceptance:** New modes are discoverable and predictable, share the snap path used by drawing tools, and don't degrade large-import responsiveness through full scans on every mouse event.

## GEO-05 — Numeric vertex editing

**Files:** `appEditors/appGeoEditor.py` selection/property UI and geometry replacement; `tests/test_geo_editor_vertices.py` (new). A geo plugin file is permitted only if it matches the established plugin pattern.

- [x] Add a small vertex-edit action for one selected LineString/LinearRing or polygon exterior, using indexed vertex selection and numeric X/Y fields.
- [x] Implement move vertex, insert vertex on the selected segment, and remove vertex. Preserve ring closure and polygon holes.
- [x] Reject removal below minimum valid point count and explain unsupported multipart/ambiguous selection rather than silently flattening it.
- [x] Commit one history operation per applied edit and rebuild affected index/render entries.
- [x] Test open paths, closing-vertex synchronization, polygon holes, invalid edits, and undo/redo.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_vertices.py tests/test_geo_editor_history.py`.

**Acceptance:** Users can accurately revise an existing contour without redrawing it. On-canvas drag grips are follow-up work, not a prerequisite for this ticket.

## GEO-06 — Split an open path

**Files:** `appEditors/appGeoEditor.py` tool/action registration and replacement path; `tests/test_geo_editor_split.py` (new).

- [x] Expose split for one selected open path and a snapped/projected click point.
- [x] Use existing Shapely operations to split at the projected distance. Reject endpoint splits and out-of-tolerance clicks without modifying the original.
- [x] Replace the source with two nonzero-length paths in one history operation. Preserve applicable metadata and tool ownership.
- [x] Test interior vertex/segment splits, endpoint rejection, tolerance, and undo/redo.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_split.py tests/test_geo_editor_history.py`.

**Acceptance:** A path can be broken into two editable pieces without losing or duplicating length. Polygon/ring breaking and interactive trim/extend remain separate follow-ups.

## GEO-07 — Join open paths with explicit tolerance

**Files:** `appEditors/appGeoEditor.py`, established parameter panel location if needed; `tests/test_geo_editor_join.py` (new).

- [x] Add a join action for selected open line paths with a visible tolerance in current units.
- [x] Join exact shared endpoints using existing Shapely merging. For near endpoints, make the chosen connection policy explicit and deterministic. Do not move unrelated interior vertices.
- [x] Reject or report branching/ambiguous combinations rather than guessing an order. Keep disjoint components distinguishable.
- [x] Commit replacements atomically and preserve undo/redo.
- [x] Test reversed directions, exact/near endpoints, over-tolerance gaps, branching, and undo/redo.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_join.py tests/test_geo_editor_history.py`.

**Acceptance:** Users can repair a known small gap without hidden global cleanup or unintended contour connections.

## GEO-08 — Non-destructive contour diagnostics

**Files:** `appEditors/appGeoEditor.py` selected-geometry information/action UI; `tests/test_geo_editor_diagnostics.py` (new).

- [x] Add a selected-geometry check for empty/zero-length paths, duplicate paths independent of direction, invalid/self-intersecting geometry, and open contour endpoints.
- [x] Report counts and identify affected shapes through existing selection/tree feedback. Use an explicit tolerance when identifying near-coincident endpoints.
- [x] Keep diagnostics read-only. Don't auto-close paths, drop duplicates, or repair geometry on inspection.
- [x] Test intentional open paths, closed contours, reversed duplicates, zero length, self-intersection, and nearby but separate endpoints.
- [x] Run the diagnostic tests (exact commands and results below).

**Acceptance:** Problems are discoverable without geometry changes. An open path is reported as an open path, not automatically classified as an error.

## GEO-09 — Editable DXF source lifecycle

**Decision:** Reuse geometry objects' existing DXF source mechanism as an editable interchange snapshot. DXF output of sampled paths doesn't restore exact circles/arcs. Do not replace the project model or treat generated DXF as a second automatically authoritative geometry store.

**Files:** `appEditors/appGeoEditor.py` (`update_editor_geometry` or confirmed edit-finish owner), `appObjects/GeometryObject.py`, `appObjects/AppObjectTemplate.py`, `appHandlers/appIO.py` only if required; `tests/test_geo_editor_source.py` (new), `tests/test_stage4_regenerate_source.py`.

- [x] Verify whether edit save already regenerates the source. If it does, retain it and add regression coverage rather than duplicate regeneration.
- [x] Ensure successful editor save produces a DXF source snapshot of the committed geometry through existing regeneration/export methods.
- [x] Verify source persistence and reopening/export using real ezdxf output, including mm/inch units, closed paths, holes, and multigeometry objects.
- [x] Ensure failed DXF generation preserves the previous source and reports failure without silently replacing good source with a partial document. Preserve the committed geometry and explain a stale snapshot.
- [x] Verify existing import/reimport path for externally edited DXF. Document the user workflow and any missing explicit replace/import action as a follow-up rather than overwrite tool assignments implicitly.
- [x] Run `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py` plus existing DXF parser tests identified in GEO-01.

**Acceptance:** Saved geometry has a usable DXF interchange source through established project mechanisms. No claim of exact analytic entity round trips is made for sampled source geometry.

## GEO-10 — Integration and final review

**Files:** affected tests and this plan; production fixes only for regressions introduced by these tickets.

- [x] Run all new geometry-editor ticket tests together with existing geometry-editor, move/copy, rendering/index, source regeneration, and relevant DXF tests.
- [x] Exercise or explicitly report unverified GUI checks: draw, cancel, undo, redo, numeric vertex edit, split/join, snapping at two zoom levels, save/reopen, DXF export/reimport.
- [x] Check units and selected multigeometry tool behavior across the full sequence (automated save/restore/export/reimport and deferred selected-tool checks; live GUI sequence unverified).
- [x] Review `git diff --check`, diff statistics, and changed files. Preserve unrelated changes.
- [x] Reindex edited production files and update this plan's status/evidence for every ticket.

**Acceptance:** No completion claim without observed verification. Record any GUI checks that cannot be performed in the available environment.

## Follow-up backlog requiring separate detailed design

These are deliberate roadmap items, not claims of delivered functionality:

1. Exact persistent LINE/CIRCLE/ARC/polyline entities, stable IDs, serialization migration, and source-of-truth rules for DXF-backed editing. Decide behavior after booleans or nonuniform scaling before implementation.
2. Full on-canvas grips and stretch selection after numeric vertex editing is proven.
3. Interactive trim/extend, true-radius fillets, and chamfers with explicit edge selection and tolerance rules.
4. Complete precision input across tools: absolute/relative coordinates, length/angle, axis locks, and safe unit-aware expressions.
5. Exact center/intersection/perpendicular/tangent snaps, using analytic entity support where necessary.
6. Measurement overlays and persistent non-driving dimensions; associative dimensions need stable entity references.
7. Construction geometry, groups/layers, visibility/locking, and explicit exclusion from machining output.
8. Persistent sketch constraints and solver integration only after a separate approval.

## Execution evidence

The parent will append per-ticket implementation, verification, and blocker notes here after delegation. No implementation has been dispatched when this plan is first saved.

### GEO-10 — final integration evidence (2026-10-21)

**Review status:** GEO-01 through GEO-09 are independently reviewed/approved according to the fresh execution dispatch. This supersedes historical pending-review labels below, including the post-Tools-DB GEO-09 fix. GEO-10 execution doesn't self-approve its final review. No production/test changes, nested agents or commits were made during this integration pass; only this plan was updated. Concurrent application history/UUID/rename and alignment changes were preserved.

**Observed checks (current workspace, Python 3.14.3):**

1. `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_history.py tests/test_geo_editor_input.py tests/test_geo_editor_snapping.py tests/test_geo_editor_vertices.py tests/test_geo_editor_split.py tests/test_geo_editor_join.py tests/test_geo_editor_diagnostics.py tests/test_geo_editor_source.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_editor_move_batch.py tests/test_rtree_storage_ties.py tests/test_geometry_plot_layer.py tests/test_vispy_batch.py tests/test_vispy_only_geo_editor.py tests/test_stage4_regenerate_source.py tests/test_dxf_import.py tests/test_dxf_without_matplotlib.py -v -ra` — **526 passed in 30.18 s**, no reported skips/warnings. Includes the real 100,000-path heartbeat/progress regression and post-Tools-DB pending-DXF quit regression. The MM/IN source cases verify selected-tool commit without modifying the other tool, queued completion, project serialization/restore, DXF units/closed paths/holes, disk export and explicit reimport as a new object. These are automated boundaries, not a claimed live desktop journey.
2. `.venv\Scripts\python.exe -m pytest tests/test_project_file.py tests/test_project_save_wkt.py tests/test_project_load_cleanup.py tests/test_projects_appio.py tests/test_projects_manager.py tests/test_project_context.py tests/test_unify_characterization.py tests/test_unify_regressions_0b.py tests/test_app_handler_characterization.py tests/test_app_refactor_characterization.py tests/test_app_refactor_integration.py tests/test_app_history.py tests/test_app_history_app.py tests/test_app_history_keys.py tests/test_lifecycle_initialization.py tests/test_shutdown_routing.py tests/test_worker_stack_shutdown.py tests/test_shutdown_message_filter.py tests/test_tools_database.py -v -ra` — **402 passed, 4 failed, 17 setup errors, 3 skipped, 249 subtests passed, 7 warnings in 20.46 s**. Attribution below; this isn't a clean broad-suite result.
3. `.venv\Scripts\python.exe -m pytest tests/test_app_history_app.py -v -ra` — **17 passed, 40 Shapely deprecation warnings in 6.65 s** in a fresh process.
4. `.venv\Scripts\python.exe -m pytest tests/test_app_refactor_integration.py tests/test_app_history_app.py -q -ra` — **4 passed, 2 failed, 17 setup errors, 175 subtests passed in 8.09 s**. Reproduces the Qt slot contamination without any geometry-editor ticket test running.
5. `.venv\Scripts\python.exe -m pytest tests/test_project_file.py tests/test_project_save_wkt.py tests/test_project_load_cleanup.py tests/test_projects_appio.py tests/test_projects_manager.py tests/test_project_context.py tests/test_unify_characterization.py tests/test_unify_regressions_0b.py tests/test_app_handler_characterization.py tests/test_app_history.py tests/test_app_history_keys.py tests/test_lifecycle_initialization.py tests/test_shutdown_routing.py tests/test_worker_stack_shutdown.py tests/test_shutdown_message_filter.py tests/test_tools_database.py -q -ra` — **375 passed, 3 skipped, 53 subtests passed, 7 warnings in 9.31 s**. This separate run isolates the identified unrelated characterization/startup failures; it doesn't erase result 2. Skips: both Zstandard backends unavailable (one), full Qt context required (two). Warnings: six Shapely `resolution` deprecations and one unraisable `OSError('disk full')` from the intentional `FailingClose` fixture in `test_unify_characterization.py:670`.

6. `.venv\Scripts\python.exe -m pytest tests/test_stage4_copy_from.py tests/test_stage4_shared_methods.py tests/test_pick_consumers.py tests/test_shape_collection_layer_check.py tests/test_tool_distance_snap.py tests/test_coordinate_toolbars.py tests/test_jump_to.py tests/test_move_tool.py -q -ra` — **220 passed, 9 subtests passed in 5.70 s**, no reported skips/warnings.

**Failure attribution / follow-up for application-history owner:** Two characterization failures use `base_app()` without the newly required `history`; origin raises at `appObjectOps.py:396`, rotation catches the same missing dependency before calling `rotate`. The facade manifest omits new `delete_objects_now`; controlled startup's `StrictUI` lacks `on_history_changed` required by the concurrent history signal wiring. The startup test patches decorated `App.info` while constructing a QObject; subsequent real App construction fails `inform[str].connect(self.info)` with `No such slot App::info(QString)`. The minimal two-file reproduction plus the standalone 17-pass history run establish process-order contamination, not a GEO-09 pending-save failure. These unrelated tests/production changes weren't rewritten. No task-caused regression was found.

**Diff/index:** Entry status/stat recorded extensive existing modifications/untracked files, including this parent-authored plan and staged deletion of the old alignment module. `rtk git diff --check` passed; source-attributed history diffs explain the failures above. Targeted jCodeMunch `index_folder` refresh of the 17 GEO production files (editor and six geo plugins; MainGUI; preference manager/general settings/defaults; appIO/lifecycle/projects; App; base/geometry object) returned `src/Beta`, **No changes detected**: their stored content was already current. No source edits were necessary.

**Manual checklist — all UNVERIFIED (no live desktop tool):**

- [ ] On the real canvas draw path/circle/rectangle; test Enter before a point, numeric input, Backspace, Escape and tool switching; inspect preview cleanup.
- [ ] Use Ctrl+Z/Ctrl+Y/Ctrl+Shift+Z on committed edits; confirm text widgets retain native undo and tree/selection/rendering agree.
- [ ] Open numeric vertex editing; move/insert/remove; split and join using visible units/tolerance; undo/redo each result and inspect diagnostics.
- [ ] Exercise midpoint/nearest feedback at two zoom levels on the actual OpenGL canvas; confirm disabled/master-switch behavior and large-scene responsiveness.
- [ ] In MM and IN select one multigeometry tool, edit/save, reopen the project, export DXF and import it as a new object; visually verify other tool assignments, holes and closure.
- [ ] Observe Working and responsive UI during large DXF save; try project switch/save/new/quit and Tools DB confirmation while pending; verify native close/OS shutdown behavior only after completion.

**Limits:** Sampled DXF polylines aren't exact analytic arcs/circles. Automated render/index tests don't certify OpenGL display, native dialogs, OS shortcuts or desktop shutdown. Broad application characterization remains non-green as attributed above; fresh final GEO-10 review remains outstanding.

### GEO-09 — post-Tools-DB shutdown recheck (2026-10-21; pending re-review)

**Remaining review blocker:** The initial quit guard ran before Tools DB confirmation, but that confirmation can process GUI events and start a deferred geometry save. `quit_application` now rechecks immediately after successful `_confirm_tools_database`, before defaults update/save, UI hide, editor disconnection or platform shutdown. A pending save returns False with the existing geometry-save warning. No other shutdown behavior or scope changed.

**Regression:** `test_quit_rechecks_geometry_save_started_during_tools_database_confirmation` exercises the real quit and Tools DB confirmation methods. The database's confirmation callback runs a nested Qt event loop that starts `App.on_editing_finished` and receives `pending`. The regression asserts no defaults update/save, hide, editor deactivation/disconnection, canvas disconnection or early post-edit signal. It then runs the queued real DXF generation on a thread and delivers queued GUI completion, verifies the exported path, and checks that save finishes exactly once without the rejected quit later hiding/disconnecting the UI.

**Observed verification:**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py -k quit_rechecks -v` — initial **1 failed** at the protective hide assertion, reproducing the missing post-modal guard; after the five-line localized fix **1 passed**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_shutdown_routing.py tests/test_lifecycle_initialization.py tests/test_tools_database.py -q -rs` — **116 passed, 2 skipped, 38 subtests passed in 28.65 s**. Both skips require full GUI context; no warnings or failures.
- `.venv\Scripts\python.exe -m py_compile appHandlers/appLifecycle.py tests/test_geo_editor_source.py` and `rtk git diff --check` — **passed**. Reviewed the lifecycle diff against its pre-existing guards; this follow-up adds only the post-confirmation recheck.

**Preservation/limits:** Only `appHandlers/appLifecycle.py`, the existing source/lifecycle regression file and this evidence were edited. All concurrent workspace changes remain intact. No agents, commits, new shutdown framework or unrelated fixes. Independent re-review remains pending.

### GEO-09 — deferred DXF save review fix (2026-10-21; pending re-review)

**Review finding:** Synchronous real DXF regeneration blocked the GUI for roughly 5.5 seconds on 100,000 two-point paths; the old mocked-export timings didn't exercise that work. The progress container's 50 ms timer couldn't display Working during the blocked call. The initial implementation evidence below is historical; this section supersedes its synchronous save-route description.

**Implementation and ordering:** The actual `App.on_editing_finished` Save branch supplies a continuation to `update_editor_geometry`. Geometry, selected multigeometry tool updates and bounds still commit on the GUI thread under the existing history-access gate. The exporter then runs once through the existing `worker_task` queue. `regenerate_source(store=False)` is backward-compatible and returns the generated text without mutating `source_file`. The worker reads the reserved committed model, uses existing export/log/signal paths, and never invokes widget methods or changes the owning object's source. `source_save_done` is explicitly connected to the editor's QObject slot with `QueuedConnection`.

The App caller returns `pending`, without restoring toolbars/tabs, rebuilding/plotting the object, reporting saved success, or emitting `post_edit_sig`. A captured object/session/token identifies completion; the currently active selection isn't used to choose the destination. The GUI completion slot applies complete DXF text (or preserves the previous source and warns stale on failure), deactivates, and runs the existing App save-finalization continuation exactly once. A retained process entry stays alive through queued completion; its `done()` runs in a GUI-side finally block. Submission failure also preserves committed geometry/previous source and completes once with a stale-snapshot warning. Obsolete callbacks don't publish or close a different session. Direct non-GUI callers without a continuation retain the existing synchronous API.

**Pending/race rules:** A separate pending-save reservation covers queued work, running generation, and the interval after worker exit but before GUI completion. Existing busy/history/reset/deactivation gates reject edits, duplicate Save, Discard, new editor sessions and queued-operation cancellation during this interval. Selection feedback is interdicted until completion. Project switching already refuses an open editor; `call_source` remains `geo_editor` until normal post-edit finalization. New-project/cleanup rejection remains intact. Explicit project restore also rejects pending saves, including the Tcl path that bypasses ordinary new-project cleanup; it rechecks after the legacy-project modal. Project save queuing and direct `save_project` refuse to serialize new geometry with a pending old source. Conversely, a queued/running project save rejects geometry commit before any mutation. Both final-save and direct-quit routes refuse shutdown while the snapshot is pending; they don't disconnect the completion receiver or terminate its worker.

**Regression evidence:** `tests/test_geo_editor_source.py` now has 26 cases. The real 100,000-path regression uses the existing Worker on a QThread, real ezdxf generation/serialization, a 50 ms GUI heartbeat and the real `FCVisibleProcessContainer` coalescing timer. Only editor rendering/dialog setup and the activity view are stubbed. It checks that Save returns pending with old source/no teardown, heartbeat gaps stay below one second, Working reaches the activity view on the GUI thread, completion/deactivation run on the GUI thread, all 100,000 entities survive reparsing, and the progress entry is released. Smaller tests exercise worker exit before queued delivery, failure at document/entity/text stages, unexpected exceptions, queue rejection, stale session/editor callbacks, original-object ownership after selection changes, pending project persistence in both directions, duplicate cleanup/new-project/restore/shutdown rejection, and deferred mm/inch multigeometry project round trips without changing the other tool. Existing synchronous assumptions in the actual-caller history tests were updated to wait for completion without removing their busy-rejection/order assertions.

**Observed commands/results:**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py -k "100000 or without_storing" -v -s` — initial **2 failed**, reproducing synchronous completion and missing non-storing API, in **5.84 s**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py -k "pending_save_guards or persistence_already" -q` — initial **7 failed**, reproducing missing pending ownership/guards.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py -k "100000 or without_storing or pending_save_guards or persistence_already" -v -s` — **9 passed**; real DXF **0.153 s return / 6.271 s total / 98 heartbeat ticks**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_geo_editor_save.py tests/test_geo_editor_history.py tests/test_projects_appio.py tests/test_projects_manager.py tests/test_shutdown_routing.py tests/test_lifecycle_initialization.py tests/test_app_handler_characterization.py -q` — **224 passed, 2 skipped, 4 subtests passed**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_geo_editor_save.py tests/test_geo_editor_history.py tests/test_geo_editor_diagnostics.py tests/test_geo_editor_join.py tests/test_geo_editor_split.py tests/test_geo_editor_vertices.py tests/test_geo_editor_input.py tests/test_geo_editor_snapping.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_copy.py tests/test_geo_editor_performance.py tests/test_editor_move_batch.py tests/test_dxf_import.py tests/test_dxf_without_matplotlib.py tests/test_project_file.py tests/test_project_save_wkt.py tests/test_unify_characterization.py tests/test_stage4_copy_from.py tests/test_stage4_shared_methods.py tests/test_projects_appio.py tests/test_projects_manager.py tests/test_shutdown_routing.py tests/test_lifecycle_initialization.py tests/test_app_handler_characterization.py tests/test_app_refactor_characterization.py tests/test_app_refactor_integration.py -q -rs` — **891 passed, 3 skipped, 212 subtests passed in 21.86 s**. Skips require both Zstandard backends or a full GUI context. The existing intentional disk-full finalization warning recurred; nothing was suppressed.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py -k 100000 -v -s` — dedicated real-export check **passed**, **0.174 s return / 6.395 s total / 100 heartbeat ticks**.

**Latest workspace verification after concurrent project-history changes:** A later rerun aborted with Windows exit `-1073740791` in project-restore completion. The new concurrent `appIO.restore_project_objects.finished` calls `app.history.clear()`; the shared headless `make_app` fixture lacked that new dependency. Adding `history=Mock()` to that test fixture restored the real project round trips without changing or bypassing production history code. A focused reproduction of `test_pending_save_guards_and_gui_owned_completion[False]` then passed.

- The full 28-file command above, repeated after that fixture adaptation, produced **885 passed, 7 failed, 3 skipped, 206 subtests passed**. These are concurrent application-history integration failures, not GEO09 failures: old rename test doubles lack the new history/collection API; signal-connector/StrictUI doubles lack `history_changed`/`on_history_changed`; two method manifests lack the new `delete_objects_now`; the nested invocation-ledger test repeats those failures. Those unrelated handlers/tests weren't changed by this fix. The earlier 891-pass result is historical, not a claim that this latest broad workspace run passed.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_geo_editor_save.py tests/test_geo_editor_history.py tests/test_geo_editor_diagnostics.py tests/test_geo_editor_join.py tests/test_geo_editor_split.py tests/test_geo_editor_vertices.py tests/test_geo_editor_input.py tests/test_geo_editor_snapping.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_copy.py tests/test_geo_editor_performance.py tests/test_editor_move_batch.py tests/test_dxf_import.py tests/test_dxf_without_matplotlib.py tests/test_project_file.py tests/test_project_save_wkt.py tests/test_unify_characterization.py tests/test_stage4_copy_from.py tests/test_stage4_shared_methods.py tests/test_projects_appio.py tests/test_projects_manager.py tests/test_shutdown_routing.py tests/test_lifecycle_initialization.py -q -rs` — **849 passed, 3 skipped, 8 subtests passed**, exit 0. Existing intentional disk-full finalization warning; no GEO09 failure.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py -v -s` — **41 passed**, exit 0; latest real 100,000-path measurement **0.159 s return / 11.011 s total / 172 heartbeat ticks** under concurrent workspace load. The heartbeat/progress/thread-ownership checks passed without mocking generation.
- `.venv\Scripts\python.exe -m py_compile appEditors/appGeoEditor.py appMain.py appObjects/AppObjectTemplate.py appHandlers/appIO.py appHandlers/appLifecycle.py tests/test_geo_editor_source.py tests/test_geo_editor_history.py tests/test_unify_characterization.py` and `rtk git diff --check` — **passed**. Reviewed the localized hunks while preserving concurrent changes; refreshed the eight Python indexes and this plan's documentation index.

**Preservation/limits:** No agents, commits, frameworks, format migration, or analytic-entity work. All previous modifications were preserved, including additional concurrent project-history/UUID work appearing in App and FlatCAMObj during this fix. No live OpenGL/manual GUI exercise. Synchronous geometry copying and final GUI rebuild/plot remain on the GUI thread; the measured long DXF generation/serialization is deferred. Project save/close requests made while pending are rejected with a retry message, not silently auto-replayed. Independent re-review remains pending.

### GEO-09 — DXF interchange snapshot (initial implementation; superseded save routing above)

**Approval/scope:** GEO-02 through GEO-08 are reviewed and approved per the user's GEO-09 handoff. This supersedes the historical pending-review notes below for GEO-07/08. GEO-09 only; no agents, commits, analytic entity model, tool reassignment, or architectural rewrite. All pre-existing source/persistence and other concurrent edits were inspected and preserved.

**Confirmed save route:** `App.on_editing_finished` rejects a busy geometry editor before cleanup/dialog and checks again after the modal dialog. It returns immediately when `update_editor_geometry` rejects Save. The accepted update reserves the existing history gate, copies edited shapes and the selected multigeometry tool geometry/diameter, updates bounds, and then deactivates. Neither this route nor the update previously regenerated source. Regeneration now runs once inside that accepted update, after geometry commit and before deactivation, through the existing `FlatCAMObj.regenerate_source` and `GeometryObject.source_exporter = 'export_dxf'`. `App.on_editing_finished` itself and the shared regeneration method weren't changed.

**Snapshot/failure contract:** `GeometryObject.export_dxf` still returns a real ezdxf Drawing for disk export, but returns None after any caught generation error instead of returning the partially populated document. Closed paths and polygon exterior/interior rings set the DXF closed flag. `appIO.export_dxf` rejects None before any file write or success signal. Its synchronous local-use branch serializes the complete Drawing with `StringIO` and returns DXF text. A failed entity generation or text serialization therefore reaches the existing regeneration failure guard, which retains the old source. Editor save warns explicitly that geometry was saved but the DXF snapshot is stale. An unexpected regeneration exception is logged and also warns; it doesn't roll back committed geometry or turn Save into Discard.

**Persistence:** Initialize and serialize the existing `source_file`, like other source-bearing objects; no second field or authoritative store. A geometry-local `from_dict` default accepts older projects without that field. Imported SVG/DXF text remains in the same field until a successful regeneration. Geometry and per-tool geometry remain authoritative. The old GEO-01 `source_file not in to_dict()` characterization now asserts the desired text persistence. The existing real `save_project`/JSON `dict2obj`/`restore_project_objects` helper now constructs GeometryObject too. Tests verify new geometry and the retained old snapshot both survive project save/restore after regeneration failure. No format migration or major serialization redesign was necessary.

**External-edit workflow and replacement semantics:** Save edits, select the Geometry object, and use File → Export DXF (or `export_dxf name filename`). Edit that file in an external CAD application, then use File → Import DXF as Geometry. The existing `appIO.import_dxf` calls `new_object` with a new name and reads the imported DXF text into its source field; it doesn't watch the file or replace the original object. Repeated import is another new object, not automatic replacement. Verify the imported paths/units, then explicitly select/reconfigure the new object's machining tools and remove the old object only when desired. Editing the text shown by View Source isn't geometry reimport. DXF export combines multigeometry paths without encoding tool ownership or machining settings, so importing it cannot implicitly recover or overwrite those assignments. Polygon holes return as separate closed paths; sampled arcs remain polylines. An explicit replace/reimport action with defined tool-mapping policy is a follow-up, not part of GEO-09.

**Observed verification:**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py -q` — initial **14 failed, 13 passed**: missing refresh/persistence, raw Drawing, partial-document and serialization failure contracts reproduced.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_geo_editor_save.py tests/test_geo_editor_history.py -q` — **90 passed** after implementation and fixing the newly extended project helper's missing GeometryObject import. The intermediate run had 4 restore-harness failures and 86 passes; no production persistence workaround was added.
- `.venv\Scripts\python.exe -m pytest tests/test_dxf_import.py tests/test_dxf_without_matplotlib.py tests/test_project_file.py tests/test_project_save_wkt.py tests/test_unify_characterization.py tests/test_stage4_copy_from.py tests/test_stage4_shared_methods.py tests/test_geo_editor_performance.py -q` — **309 passed, 1 skipped, 6 subtests passed**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_geo_editor_save.py tests/test_geo_editor_history.py tests/test_dxf_import.py tests/test_dxf_without_matplotlib.py tests/test_project_file.py tests/test_project_save_wkt.py tests/test_unify_characterization.py tests/test_stage4_copy_from.py tests/test_stage4_shared_methods.py tests/test_geo_editor_performance.py -q` — **399 passed, 1 skipped, 6 subtests passed** after adding actual import-handler and post-failure project persistence assertions. One warning comes from the existing deliberate `FailingClose.close()` disk-full test during finalization; no tests or warnings were suppressed.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_dxf_import.py tests/test_dxf_without_matplotlib.py -q -rs` — **56 passed** without warnings.
- `.venv\Scripts\python.exe -m pytest tests/test_project_file.py tests/test_project_save_wkt.py tests/test_unify_characterization.py tests/test_stage4_copy_from.py tests/test_stage4_shared_methods.py tests/test_geo_editor_performance.py -q -rs` — **280 passed, 1 skipped, 6 subtests passed**; skip is `test_project_file.py:54`, requiring both Zstandard backends. The existing disk-full finalization warning recurred.
- `.venv\Scripts\python.exe -m py_compile appEditors/appGeoEditor.py appObjects/GeometryObject.py appHandlers/appIO.py tests/test_geo_editor_source.py tests/test_stage4_regenerate_source.py tests/test_geo_editor_save.py tests/test_unify_characterization.py` and `rtk git diff --check` — passed. Reviewed changed hunks against the gathered pre-existing content and refreshed the seven edited Python indexes.

**Limits:** Headless real Qt/ezdxf and real project serialization/restore, with the existing test factory replacing GUI object creation and rendering. No live OpenGL/manual dialog interaction. No exact analytic circle/arc recovery, DXF tool-assignment round trip, new replace action, or GEO-10 implementation. Independent review remains pending.

### GEO-08 — selected contour diagnostics (2026-10-21; independent review pending)

**Scope:** GEO-08 only. Added `diagnose_selected` and an explicit Inspect selected geometry button in the existing Coordinates panel. No agents, commits, new dependencies, repairs, geometry replacements, plot changes or history operations. Existing concurrent changes remain intact.

**Policy:** Counts are affected wrapper counts per category, not exclusive categories. Recursively inspect selected list/multipart components and polygon rings. Empty geometry and zero-length paths are separate categories; invalidity or non-simplicity identifies invalid/self-intersecting geometry. Shapely-normalized path coordinates detect duplicates independently of direction (not arbitrary resegmentation). Open nonzero paths and their endpoint coordinates are informational, not errors. Near endpoint pairs include exact coincidences and same-path endpoint gaps within the explicit finite non-negative tolerance, default `0.01` current units; zero means exact coincidence. No endpoint welding, closing, duplicate removal or repair. STRtree limits endpoint comparisons; no diagnostic work runs on mouse motion. The existing nonblocking history lock rejects queued/running worker conflicts without cancelling them.

**Feedback:** A selectable plain-text snapshot reports category counts, affected shape IDs, open endpoint coordinates and near-pair identities. Existing tree Type-column tooltips identify categories without changing names or selection. The snapshot explicitly requests rerunning after edits/selection changes. It isn't a persistent automatically updated validation layer.

**Observed verification:** The first test invocation stopped at widget construction because the new test omitted the existing QApplication fixture; importing that fixture corrected test setup. The next invocation produced 11 expected failures for the missing diagnostic API/UI. After implementation:

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_diagnostics.py -v` — **11 passed in 0.28s**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_diagnostics.py tests/test_geo_editor_join.py tests/test_geo_editor_split.py tests/test_geo_editor_vertices.py tests/test_geo_editor_history.py tests/test_geo_editor_input.py tests/test_geo_editor_snapping.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_copy.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_editor_move_batch.py -q` — **422 passed in 4.04s**. Normal conftest/imports were used, not bypassed. The external alignment import blocker wasn't present on these runs; its file wasn't edited by GEO-08.

- `.venv\Scripts\python.exe -m py_compile appEditors/appGeoEditor.py tests/test_geo_editor_diagnostics.py` and `rtk git diff --check` — passed. Reviewed the diagnostic additions against the gathered pre-existing editor baseline; only the editor, diagnostic test file and this plan were edited for GEO-08. Production/test indexes were refreshed.

**Limits:** Real Qt widgets with existing headless render helpers, not a live OpenGL/manual GUI session. Diagnostics are selected-only snapshots. Zero-length paths aren't assigned meaningful open endpoints. Duplicate detection compares normalized coordinate paths, not geometric equivalence after arbitrary vertex insertion. GEO-09/10 remain untouched.

### GEO-07 — join open paths (2026-10-21; static review clean, external test blocker history)

**Independent review handoff:** User reports static review found no defects, but independent test execution was blocked by unrelated concurrent `appPlugins/ToolAlignObjects/AlignUI.py:146` (unterminated string). That file must not be edited as part of GEO-08. During GEO-08, normal test imports succeeded and all join/history tests passed as part of the 422-case suite above. This retry doesn't claim a new independent review or retroactively turn the blocked attempt into a pass.

**Scope:** GEO-07 only. GEO-02 through GEO-06 are reviewer-approved per the user's handoff. No nested agents, commits, new dependencies or architectural changes.

**Implementation/policy:** The existing Coordinates panel exposes Join paths and a visible Join tolerance labeled in current units (default `0.01`). Zero accepts exact endpoints only. A selected endpoint must have exactly one other selected-path endpoint within tolerance; multiple candidates reject the whole operation, with no nearest-candidate or transitive-cluster guessing. STRtree limits endpoint candidate lookup. Near pairs receive straight bridge segments, not endpoint welding: all source endpoints and interior vertices remain unchanged. Shapely `linemerge` handles exact/bridged chains and closed output. Direction is Shapely's merge direction, not a machining-direction guarantee. Disjoint components become separate selected wrappers; isolated paths keep their original wrapper.

All replacements are prepared before committing. Only simple, valid, finite, nonempty 2D open LineStrings are supported as inputs. Output must be a valid simple LineString per joined component; intersecting/branching output components are rejected. Expected output length is the sum of source lengths plus bridge lengths, checked before commit. Feedback reports component count and added bridge length in current units. Compatible metadata is copied with fresh bounds; any non-bounds metadata conflict within a joining component (including tool/owner keys) rejects the operation rather than losing information. The editor's existing single multigeometry tool context is unchanged. One `replace_shapes` call inside `geometry_operation` handles history, selection, index and snap-cache invalidation, followed by tree/render refresh. Busy rejection uses the existing gate.

**Verification:** Initial `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_join.py -q` — 22 expected failures for the missing API/UI. The next run exposed selection-list aliasing in the new test helper and a decimal floating-point boundary test; the helper now snapshots originals and the inclusive boundary uses exactly representable `0.125`. Production uses strict model-space distance, with no hidden tolerance expansion.

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_join.py tests/test_geo_editor_history.py tests/test_geo_editor_split.py tests/test_geo_editor_vertices.py tests/test_geo_editor_snapping.py tests/test_geo_editor_input.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py -q` — final **390 passed in 2.36s** (including real-tree replay, stale selection and later-component atomic rejection checks).
- `.venv\Scripts\python.exe -m pytest -q tests/test_geo_editor_join.py tests/test_geo_editor_history.py` — final **87 passed in 0.89s**; 28 join cases.
- `.venv\Scripts\python.exe -m py_compile appEditors/appGeoEditor.py tests/test_geo_editor_join.py` and `rtk git diff --check` — passed.

**Limits/preservation:** Real Qt widgets with headless render helpers, not a live OpenGL/physical GUI session. No polygon/ring/multipart input joining, self-closing a single path, interior snapping, unselected-path cleanup, or later-ticket work. Conservative metadata conflicts require separate operations. All pre-existing modifications/untracked work and the staged deletion of `appPlugins/ToolAlignObjects.py` are preserved. Only the editor, new join tests and this plan are changed for GEO-07. Independent review remains pending.

### GEO-06 — split an open path (2026-10-21; approved per GEO-07 handoff)

**Scope:** GEO-06 only. GEO-02 through GEO-05 are approved per the user's handoff. GEO-05's approval supersedes its historical pending-review notes below. No agents, commits, new dependencies or architectural changes.

**Implementation:** The Coordinates section exposes a checkable Split path action/tool and a separate Split tolerance field labeled with the application's current units. The default is explicitly `0.01` current units, not a reinterpretation of either snap radius preference. The tooltip defines tolerance as maximum snapped-click distance from the path and excluded distance along the path from either endpoint. Zero requires an exact interior click. Existing canvas dispatch supplies the snapped point; `apply_path_split` projects it to a distance and calls Shapely `substring` twice, preserving source direction and length.

Only one selected stored 2D open LineString is accepted. Rings (including closed LineStrings), polygons, multipart/collections, invalid geometry, non-finite coordinates/tolerance and negative tolerance are rejected with feedback. Endpoint/near-endpoint and off-path clicks leave geometry, selection, rendering, snap cache, history and redo untouched. The tool captures source identity and history session so changed selection, removed targets and prior sessions cannot split an unrelated shape. Busy rejection uses the existing history gate and allows retry. Escape/right-click/tool-switch cleanup needs no temporary signals or geometry.

Both results receive the source wrapper metadata with fresh bounds. Current multigeometry tool ownership is unchanged. One existing `replace_shapes` call commits source-to-two-results atomically inside `geometry_operation`, selects both pieces, invalidates snap cache, refreshes the tree and incrementally plots. Undo/redo restore the original/results and their selection. The liveness guard checks the storage object slot as well as its identity index because direct `storage.remove` retains an index entry; no shared storage behavior was changed.

**Behavioral evidence:** `tests/test_geo_editor_split.py` has 42 cases covering interior vertex/segment splits, projected clicks and inclusive tolerance boundary, reversed paths, length conservation, metadata/bounds/tool ownership, one replacement/history entry, endpoint/near-endpoint/off-path/invalid rejection with redo preservation, unsupported shapes, zero tolerance, busy retry, stale selection/session/removal, actual snapped canvas dispatch, real Qt action/button activation, right-click cancellation, real tree selection/index/cache updates and render replay.

**Observed verification (workspace PowerShell; Qt tests use `$env:QT_QPA_PLATFORM='offscreen'`):**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_split.py -q --tb=short` — initial **38 failed**, as expected because the split API/tool didn't exist. The first red run also exposed a test-helper missing `app.decimals`; that setup was corrected before implementation and the red run repeated.
- An intermediate verification was blocked by concurrent `ToolAlignObjects` package work (`AlignObjects` import unavailable). No unrelated code was changed. Once that concurrent import became available, tests ran normally.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_split.py -v --tb=short` — **41 passed, 1 failed**; the removed-target regression exposed the retained storage index entry. The localized liveness guard was corrected.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_split.py tests/test_geo_editor_history.py tests/test_geo_editor_vertices.py tests/test_geo_editor_snapping.py tests/test_geo_editor_input.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py -q --tb=short` — final **366 passed in 2.21s**.
- `.venv\Scripts\python.exe -m pytest -q tests/test_geo_editor_split.py tests/test_geo_editor_history.py` — **101 passed in 0.67s**.
- `.venv\Scripts\python.exe -m py_compile appEditors/appGeoEditor.py tests/test_geo_editor_split.py` and `rtk git diff --check` — passed.

**Limits/preservation:** Headless tests use real Qt widgets/tree and the existing fake canvas/render collections; no live OpenGL or physical GUI smoke test was performed. No polygon/ring breaking, trim/extend, join, later tickets, or source/save architecture changes. The 27 initially modified files and 13 untracked files (including this plan) were preserved, as was additional concurrent alignment/picking work appearing during execution. Only `appEditors/appGeoEditor.py`, `tests/test_geo_editor_split.py` and this plan were edited for GEO-06. Independent review remains pending; no architectural blocker remains.

### GEO-05 — numeric vertex editing (2026-10-21; approved per GEO-06 handoff)

**Scope:** GEO-05 only. GEO-04 is reviewer-approved per the user's handoff; this supersedes its historical pending-review notes below. No nested agents, commits, new dependencies, architecture split, or later-ticket implementation.

**Implementation:** The existing Coordinates section has an Edit vertices action. Its compact modal dialog provides a zero-based vertex/segment index, numeric X/Y, Move/Insert/Remove, Apply and Close. Index changes load the actual coordinate without display rounding. Each successful Apply refreshes the dialog's target/index range; Close/Escape doesn't undo earlier applied edits. The duplicated closing coordinate aliases vertex 0 for move/removal. Insertion uses the segment from index to index + 1, including the last unique ring vertex's closing segment; the duplicated terminal coordinate has no outgoing segment.

`vertex_edit_target` requires exactly one stored 2D LineString/LinearRing or Polygon, rejects stale targets, and explains unsupported multipart/collections rather than flattening them. `apply_vertex_edit` constructs and validates first, preserves geometry type, closure, polygon interior rings and wrapper metadata, then uses one existing `replace_shapes` call inside one `history_operation`. It emits one tree refresh and uses incremental plotting. Minimum vertex counts, finite numeric X/Y, index bounds, zero-length segments, self-intersection and invalid polygon/hole relationships are checked before mutation. Insert coordinates must lie strictly inside the selected segment (distance tolerance `1e-9 * max(1, segment length)` in model units). Busy operations are rejected through the existing nonblocking history gate. Rejected and unchanged edits don't consume history or clear redo.

**Behavioral evidence:** Added `tests/test_geo_editor_vertices.py` with 37 cases: open move/insert/remove, first/closing aliases across all three geometry types, closing-segment insertion, polygon-hole retention, invalid numeric/index/segment/topology edits, minimum-count rejection, multipart/ambiguous selection feedback, stale-target/busy rejection, metadata, real tree identities, spatial index replacement, snap-cache invalidation, incremental render output, one-step undo/redo and redo preservation. A real Qt action/dialog test changes index and coordinates, uses Apply for all three operations, and checks invalid-input rejection and range refresh.

**Observed verification (PowerShell, workspace root):**

- Initial `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertices.py -q` — **33 failed** because the GEO-05 method/action didn't exist. The same command after implementation — **33 passed in 0.18s**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertices.py tests/test_geo_editor_history.py tests/test_geo_editor_input.py tests/test_geo_editor_snapping.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_copy.py tests/test_geo_editor_save.py tests/test_geo_editor_performance.py tests/test_editor_move_batch.py tests/test_localized_geometry_fixes.py -q` — final **348 passed, 3 subtests passed in 2.89s**. An intermediate added self-crossing test used a noncrossing input; its coordinates were corrected without changing production behavior.
- `rtk git diff --check` — passed. Reviewed the GEO-05 additions against the pre-existing history/input/snapping baseline. Only `appGeoEditor.py`, the new vertex tests and this plan were edited by GEO-05.

**Limits/preservation:** Tests use existing headless geometry/render helpers and real Qt widgets, not a live OpenGL or OS-keystroke session. On-canvas dragging, multipart/component editing, hole-vertex editing and 3D coordinates remain outside this ticket. Existing session loading may already represent imported polygon rings separately; this ticket doesn't change that architecture. All 27 pre-existing modified files and 12 untracked files, including this plan and GEO-02/03/04 tests, were preserved. Approval remains with the independent reviewer; no architectural blocker was found.

### GEO-01 — confirmed integration map (2026-10-21)

**Scope delivered:** investigation and behavioral characterization only. No production files changed, no commits, no subagents. Later-ticket checkboxes remain untouched.

#### Mutation and completion boundaries

- `AppGeoEditor.add_shape` (1077) recursively validates/wraps via `_collect_shape` (1101), batches committed shapes into `storage.replace(inserted=...)`, and emits `build_ui_sig`. Utility shapes go to `utility`, not storage; Point/invalid/empty geometry is filtered. Loading an edit session uses this same method and must not create history.
- `delete_shape` (1650) removes identities from utility/selection and calls `storage.replace(removed=..., inserted=...)`. `delete_selected`/`on_delete_btn` are the user deletion routes. `transform_shapes` (1707) creates replacement wrappers, copies metadata, transforms, replaces once, restores replacement selection, then rebuilds/plots. `GeoTransformationPlugin.TransformationTool` routes rotate/mirror/skew/scale/offset/buffer through it.
- `union`, `intersection`, `intersection_2`, `subtract`, `subtract_2`, and `cutpath` enqueue worker closures. The storage mutation occurs **inside the worker**, not when the toolbar/shortcut returns. Results use `_collect_shape` and `delete_shape(..., inserted=...)`; `subtract_2` and `cutpath` preserve cutting tools. `intersection` preserves nonintersecting tools and clears selection. `on_change_orientation` also performs replacement inside a worker. `SimplificationTool.on_simplification_click` replaces in a worker; buffer plugin operations add results in workers. Rendering/tree signals aren't reliable operation-start or transaction boundaries.
- `on_canvas_click` calls the active tool's `click`, then `on_shape_complete` for completed `FCShapeTool`s. Enter in `MainGUI.keyPressEvent` and right-click in `on_canvas_click_release` can call `make` then `on_shape_complete`. Completion may reverse drawing direction, calls `add_shape`, clears previews, and plots. `FCMove.make` deletes originals **before** completion inserts replacements; copy/array inserts on completion. `FCExplode.make` is an important bypass: it directly calls `storage.remove` then calls `on_shape_complete` itself. `FCEraser.make` directly replaces affected shapes and preserves replacement selection. Do not double-record nested completion.
- **Smallest coherent history seam for GEO-02:** editor-owned committed replacement around add/delete/transform, with explicit whole-operation grouping spanning move/explode's delete-plus-add and tool completion. Route explode's direct remove through that seam. Start/finish asynchronous operations at their actual worker commit, serialize history application with that commit, and suppress session import/replay. No single current callback covers all operations atomically. Keep utility previews/rendering out; restore selection/tree/index/render state together. This is localized editor work, not a reason to redesign shared storage or the application.

#### Keyboard, focus, and canvas reality

- The actual dispatcher is `appGUI/MainGUI.py::MainGUI.keyPressEvent` (3015), not an editor `keyPressEvent`. `App.on_plotcanvas_setup` connects VisPy `key_press` to it (4124); `ObjectCollection` also forwards integer keys. It ignores native `QKeyEvent` input and auto-repeat, reads Qt modifiers, and handles VisPy events using `event.native`/`event.key`.
- Its `call_source == 'geo_editor'` branch (3537) owns Ctrl+S save, Enter finish, Escape cleanup/select, Delete, and tool shortcuts. The no-modifier route subsequently forwards keys to `active_tool.on_key` (3722) when Select isn't checked. Enter therefore has both global completion logic and tool numeric-input logic: GEO-03 must test their ordering, not just call `FCPath.on_key` in isolation. Backspace in `FCPath.on_key` removes construction points, not committed edits. No committed geometry undo/redo is wired in this branch or `AppGeoEditor`; plain Y is flip-Y, not redo.
- There is **no geometry-branch text-focus guard**. Existing `focusWidget()` checks in this dispatcher are for project-list up/down navigation in app mode. Qt line/spin/text widgets normally consume their native editing keys; new history shortcuts must explicitly preserve that ownership rather than add a window-wide shortcut that steals text undo. Test focused line edits, spinbox child editors, and multiline editors as well as canvas keys.
- This checkout's active editor is VisPy-only: `App.on_plotcanvas_setup` constructs `PlotCanvas`, or `NullCanvas` headlessly; no legacy Matplotlib editor routing is selected here. `AppGeoEditor.connect_canvas_event_handlers` swaps mouse handlers only; the central key handler remains connected. `PlotCanvas3d` is also VisPy, in a separate viewing tab (`appUIActions.on_3d_area`); its application mouse/key connections are commented out. It isn't a second geometry editing backend. Don't invent legacy backend branches or claim live 3D editing verification. Headless tests use fake collections/NullCanvas, not an OpenGL smoke test.

#### Edit and DXF lifecycle

- `App.on_editing_start` checks the active object and selected MultiGeo tool, then calls `edit_geometry(..., multigeo_tool=id)` and sets `call_source`. `edit_geometry` hides the original, activates the editor, and queues loading. Loading flattens/filters geometry; polygon exteriors and holes become separate ring shapes; it batch-adds and builds the UI. History reset must wait for this load to complete and must reject stale worker completion after exit/session replacement.
- `App.on_editing_finished` owns the Yes/No/Cancel dialog. Yes calls `update_editor_geometry` synchronously, then reads bounds/builds UI/plots and reports success. No deactivates without copying editor storage back and replots the original. Dialog Cancel returns without exiting; `force_cancel` means offer a Cancel button, not automatic discard. Cleanup exit deactivates rather than saving. `update_editor_geometry` merges MultiLineStrings, flattens, updates the selected tool's geometry/diameter and `solid_geometry`, updates bounds, and deactivates. Existing save tests assert geometry is available before deactivation.
- **Confirmed GEO-09 gap:** neither the geometry Yes branch nor `update_editor_geometry` regenerates DXF source. Use `FlatCAMObj.regenerate_source` with `GeometryObject.source_exporter = 'export_dxf'`, not a second source store. It calls `appIO.export_dxf(local_use=obj, use_thread=False)` and preserves the old value on `None`/`'fail'`. Local use returns an ezdxf Drawing, not DXF text; disk export uses `Drawing.saveas`.
- `GeometryObject.export_dxf` creates an ezdxf document, declares mm/inch units from app units, and emits LWPOLYLINEs for paths/exteriors/holes, gathering all tool geometry for MultiGeo. Repeated endpoint coordinates close the exported contour geometrically; the implementation doesn't explicitly set the entity closed flag. Sampled circles/arcs remain sampled polylines, never analytic circles. **Failure gap:** its catch logs and returns `dwg`, which can already be partially populated; the regeneration wrapper can accept that partial document as success. GEO-09 must make this failure observable before replacing good source.
- Project save is `appIO.save_project`: `obj.to_dict()` -> `geometry_wkt_cache`/`project_json_default` -> atomic `save_project_file`. `Geometry.to_dict` serializes `ser_attrs`; geometry's inherited list contains units/solid/follow/tools and `GeometryObject` adds options/kind/multigeo/colors, **not source_file**. `FlatCAMObj.from_dict` restores listed attributes; `dict2obj` restores WKT/ApertureMacro, not ezdxf documents. Thus geometry survives project reopen but the DXF source snapshot currently doesn't. The new real-export test proves omission rather than assuming Drawing is JSON serializable. GEO-09 needs a localized representation/conversion for the existing source attribute, not a second authoritative geometry store or a wholesale project migration.
- External-edit workflow: export DXF through the existing exporter, edit externally, then import DXF. `appIO.import_dxf` creates a **new** Geometry object through the factory, calls `Geometry.import_dxf_as_geo`, and reads original file **text** into `source_file`; it doesn't replace the original object's tools. Explicit in-place reimport/tool-assignment reconciliation is follow-up, not authorized here. `tests/test_dxf_import.py` covers the real parser path.

#### Confirmed later-ticket targets and checks

All commands below use `.venv/Scripts/python.exe -m pytest -q` with `QT_QPA_PLATFORM=offscreen`; proposed new test filenames are already assigned in their tickets, not present baseline tests.

| Ticket | Confirmed implementation seams | Runnable baseline / required next regression |
| --- | --- | --- |
| GEO-02 | AppGeoEditor add/delete/transform/completion, FCMove/FCExplode, worker closures, activate/deactivate/load; MainGUI.keyPressEvent | Existing copy/delete_plot/performance/save tests; add test_geo_editor_history.py as specified |
| GEO-03 | MainGUI geometry Enter/Escape dispatch; FCPath/FCCircle/FCRectangle/FCMove/FCCopy on_key, make and clean_up; on_tool_select | Existing copy/save tests; add test_geo_editor_input.py with dispatcher-level ordering checks |
| GEO-04 | snap, on_canvas_click/on_canvas_move/on_canvas_click_release, get_pick_index/pick_at, DrawToolShape.get_pts | Existing delete_plot/performance tests; add test_geo_editor_snapping.py including empty/headless and live-canvas conversion doubles |
| GEO-05 | update_ui/on_tree_selection/shapes_by_tree_id, AppGeoEditorUI, _collect_shape/delete_shape and GEO-02 transaction | Existing selection/replacement tests in delete_plot; add test_geo_editor_vertices.py |
| GEO-06 | tool registration in AppGeoEditor.__init__/on_tool_select, FCShapeTool click/completion pattern, snap and replacement seam | Existing copy/delete_plot; add test_geo_editor_split.py and history checks |
| GEO-07 | AppGeoEditorUI action/parameter pattern, get_selected, _collect_shape/delete_shape and GEO-02 transaction | Existing delete_plot/save; add test_geo_editor_join.py |
| GEO-08 | update_ui existing validity/simple/ring/coordinate fields, AppGeoEditorUI, get_selected/sync_tree_selection | Existing delete_plot selection tests; add test_geo_editor_diagnostics.py proving no storage mutation |
| GEO-09 | App.on_editing_finished geometry Yes branch or synchronous update_editor_geometry; FlatCAMObj.regenerate_source; GeometryObject.export_dxf/ser_attrs; Geometry.to_dict/FlatCAMObj.from_dict; appIO import/export/save_project | test_geo_editor_save.py, test_stage4_regenerate_source.py, test_dxf_import.py; add test_geo_editor_source.py for lifecycle/failure/persistence |

#### Verification evidence and limits

Executed in PowerShell from the workspace root:

1. `$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_stage4_regenerate_source.py` — **90 passed in 0.58s**, before changes.
2. `$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest -q tests/test_dxf_import.py` — **28 passed in 0.26s**, before changes.
3. `$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest -q tests/test_stage4_regenerate_source.py` — **15 passed in 0.49s**, including four added real-DXF cases (mm/inch x single/multigeometry), exterior/hole/open-path coordinates, units, disk reopen, no local-use save signal, and current project-source omission.
4. `$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_stage4_regenerate_source.py tests/test_dxf_import.py` — **122 passed in 0.86s**, final combined verification. `rtk git diff --check` passed; the test diff contains only two imports and the four-case characterization. This previously untracked plan was reviewed against its pre-edit contents; only GEO-01 status/checklists and this evidence section changed.

No live GUI/OpenGL session, keyboard focus interaction, or interactive edit/project reopen was exercised. Routing and asynchronous hazards above are source-confirmed, not claims that a thread-race test passed. Later tickets must add their behavioral tests before claiming those fixes.

**Blockers/approval:** No architectural blocker to GEO-02 through GEO-09's localized scope was found. Source persistence and partial-DXF failure are real existing gaps for GEO-09, not reasons to skip it. Analytic entity persistence, a solver, legacy backend resurrection, and automatic in-place external reimport remain outside scope and would need separate approval. No approval is needed merely to group editor operations or serialize the existing source snapshot locally.

**Pre-existing work observed at execution:** modified `appGUI/VisPyVisuals.py`, `appObjects/AppObjectTemplate.py`, `appObjects/GeometryObject.py`, `appParsers/ParseExcellon.py`, `appParsers/ParseGerber.py`, `camlib.py`; untracked `tests/test_affine_geometry.py`, `tests/test_shape_transform.py`, and this parent-authored plan. These were present before GEO-01 edits and preserved. The parent's earlier clean-tree statement isn't a claim that this implementer's starting tree was still clean.

The final status also showed untracked `tests/test_excellon_transforms.py`, `tests/test_geometry_transforms.py`, and `tests/test_gerber_transforms.py` appearing during execution. They weren't created, edited, or removed by GEO-01; concurrent unrelated work wasn't reverted.

### GEO-02 — committed-operation history (2026-10-21)

**Historical first submission:** Approval was withheld after review reproduced numeric Apply grouping and worker/save lifecycle defects despite the 172-test pass below. The review-fix evidence following this section supersedes its worker-wait policy and coverage limits.

**Implementation:** `AppGeoEditor.replace_shapes` records committed insert/remove deltas. `history_operation` groups nested changes and captures before/after selection; undo/redo reuse storage replacement, tree signals and incremental plotting. The retained wrappers preserve geometry, metadata and identity-based tree references without scene snapshots. New committed edits invalidate redo. Utility shapes never enter history. Activate/deactivate/clear reset history; the existing initial-load worker runs with recording disabled.

Move and explode now defer removal until `on_shape_complete`, which commits delete-plus-add together. Move copies source metadata. Transforms and eraser replacements capture their final selection in the same operation. Boolean/orientation workers and buffer/paint/simplification/transformation plugins use `submit_worker`: one worker execution is one operation, serialized against replay/reset. Session/revision/selection checks reject obsolete queued jobs. The existing selection guard is restored in `finally`, including worker failure. No new dependencies or shared storage changes.

**Keyboard:** Actual `MainGUI.keyPressEvent` geometry branch handles Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z for integer and VisPy-style keys. Line edits, spinbox child editors and multiline text inputs retain shortcut ownership. Plain tool shortcuts and the existing native-QKeyEvent handling remain unchanged.

**Tests:** Added `tests/test_geo_editor_history.py`. Existing test doubles in `test_geo_editor_delete_plot.py`, `test_editor_move_batch.py` and `test_localized_geometry_fixes.py` gained the required editor state/worker method. The move batching regression now asserts no premature deletion, then actual completion, one plot, undo, and restored selection; geometry assertions weren't removed. New checks cover all six boolean operations, move/explode/eraser atomicity, redo invalidation, previews, suppressed loading, reset, metadata, nearest-point index restoration, real FCTree row/selection restoration, incremental render updates, stale queued jobs, a running-worker/reset interleaving, rollback, and actual MainGUI dispatch with real Qt input-widget ownership guards.

**Observed verification (PowerShell, workspace root):**

- Initial `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py` failed in all three initial cases because the history API didn't exist. Later focused failures exposed missing clear/eraser grouping and worker selection guards; those were fixed before the final runs.
- `$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py` — **30 passed in 0.14s**.
- `$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_stage4_regenerate_source.py tests/test_dxf_import.py tests/test_editor_move_batch.py tests/test_localized_geometry_fixes.py` — **172 passed, 3 subtests passed in 1.31s**.
- `rtk git diff --check` — passed. Task-only diff reviewed; no commits or nested delegation.

**Limits/concerns:** No live OpenGL/interactive GUI session was exercised. Keyboard tests call the actual dispatcher with integer/VisPy-style inputs and controlled Qt modifiers/focus; they aren't OS-level keystroke tests. Existing workers still perform their existing rendering/UI work on their existing execution path. The local lock serializes whole worker execution, so undo/session reset can wait for a long-running worker; a GUI-thread compute/result-dispatch redesign isn't part of this ticket. Running-worker/reset serialization is tested; real interactive save-during-computation remains a GUI integration check for the parent.

**Preserved pre-existing work:** modified `appGUI/VisPyVisuals.py`, `appObjects/AppObject.py`, `appObjects/AppObjectTemplate.py`, `appObjects/ExcellonObject.py`, `appObjects/GeometryObject.py`, `appParsers/ParseExcellon.py`, `appParsers/ParseGerber.py`, `appPlugins/ToolTransform.py`, `camlib.py`, `flatcam.py`, and GEO-01's `tests/test_stage4_regenerate_source.py`; untracked transform/bounds tests and this parent-authored plan. Only GEO-02 status/checklists and this appended evidence were changed in the plan. Parent review remains pending; no architectural blocker was found.

### GEO-02 — review fixes (2026-10-21; approval pending)

All three review blockers were reproduced before fixes. No later ticket, agent dispatch or commit was started.

1. **Numeric replacement:** Circle/Rectangle `on_execute` now groups the complete Apply action. Geometry is constructed and validated before removal. Modification uses one `replace_shapes` call with replacement selection and one tree update, rather than delete-selected followed by an independent add. Tests call the actual panel handlers and verify one storage replacement, one-step undo/redo, original metadata/selection restoration, replacement selection, and no mutation/history for zero dimensions.
2. **Nonblocking policy:** One geometry job reserves the editor from submission through completion. GUI mutation/history/submission/save entry points use nonblocking `history_access` and return failure with a wait-and-retry warning while a job is pending/running. Running jobs aren't interrupted or waited for by reset/deactivate/clear; these calls reject immediately. Reset/deactivation may invalidate a queued, not-yet-running job. Job tokens prevent obsolete closures from mutating a reset session or clearing a newer job's busy reservation. The worker still owns the operation lock internally during its existing compute/commit path; no GUI entry waits on that lock. `history_operation` now yields an acceptance flag, which production callers must check before executing their bodies.
3. **Save/caller policy:** `update_editor_geometry` reserves an idle editor before any storage snapshot, returns `'fail'` without changing the object when busy, and holds the reservation through successful transfer/deactivation. `App.on_editing_finished` rejects busy entry before cleanup/dialog, rechecks after the modal dialog, and honors updater failure before toolbar/tab teardown, success messages or `post_edit_sig`. `App.on_editing_start` rejects a busy session switch. New Project now honors failed editor exit; project restore honors failed New Project instead of loading options/objects after rejection.

**Actual Qt event-loop evidence:** New tests execute the GUI actions from `QTimer.singleShot` while a background worker is held at a controlled compute barrier. A separate 10 ms QTimer must keep firing before that worker is released. A background watchdog prevents a failing implementation from hanging the test. This replaces the previous separate-reset-thread test, which couldn't detect GUI-thread blocking. The save test verifies no storage read or persisted-object change during rejection, no success/post-edit/deactivation, successful retry through the real `App.on_editing_finished` after worker completion, and no late mutation from replaying the obsolete worker closure. Actual deactivation of a queued job also rejects its later execution.

**Observed verification (PowerShell, workspace root; `QT_QPA_PLATFORM=offscreen`):**

- `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py -k 'numeric_apply or running_worker'` initially failed all four selected cases against the first submission; the two timer cases required the watchdog to unblock the old implementation.
- `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py` — **40 passed in 0.43s**.
- `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_stage4_regenerate_source.py tests/test_dxf_import.py tests/test_editor_move_batch.py tests/test_localized_geometry_fixes.py tests/test_stage5_editor_helpers.py tests/test_project_load_cleanup.py tests/test_projects_appio.py` — **240 passed, 10 subtests passed in 2.22s**.
- `rtk git diff --check` — passed. Existing geometry/index/render performance regressions remain included. No full-scene history snapshots or unconditional render rebuilds were introduced.

**Limits:** Busy actions aren't automatically retried; users receive feedback and retry once the job finishes. Running jobs aren't forcibly cancelled. Existing worker rendering/UI access remains on its existing execution path; this ticket doesn't redesign worker dispatch. Qt event-loop responsiveness and the save/exit rejection policy are now exercised, but live OpenGL/OS-keystroke interaction isn't. Approval remains with the parent reviewer.

**Preservation:** All prior user/GEO-01/first-submission changes were retained, including the concurrently modified `CHANGELOG.md` observed at review-fix start. Review-fix edits are limited to `appGeoEditor.py`, the Circle/Rectangle panels, `appMain.py`, two failure-propagation checks in `appHandlers/appIO.py`, focused history tests, and this plan.

### GEO-02 — interactive caller rejection fixes (2026-10-21; approval pending)

**Review blocker:** The previous busy gate rejected storage commits, but interactive callers still consumed tool state and reported success. This pass changes only `appGeoEditor.py`, `MainGUI.py`, `GeoPaintPlugin.py`, the focused history tests, and this evidence/status entry.

- Canvas dispatch and MainGUI's Enter completion branches check busy state before invoking tool `click`/`make`. Click, make and completion failures return `'fail'` before tool switching or success reporting. Right-click rejection also leaves the current action intact rather than cancelling/clearing it.
- Move's direct click/make and numeric Enter paths reject busy actions before consuming origin, destination or points. Move preparation no longer clears origin/cursor data or emits success: those steps occur after successful committed replacement in `on_shape_complete`. Failed completion retains the prepared move for retry. Completion also propagates failed add/replacement results before clearing previews.
- `PaintOptionsTool.paint` returns submission status, and `on_paint` keeps the Paint tool active when submission is rejected. Accepted submission retains the existing switch-to-selection behavior.
- Added caller-level tests using the actual canvas handlers, actual Move methods, actual MainGUI dispatcher with integer/VisPy-style Enter inputs, and actual Paint panel/submission handlers. Checks cover busy pre-dispatch rejection, failed completion propagation, retained operation state, no false success/tool switch, successful Move retry/undo, and accepted Paint submission.

**Observed verification:** All commands used `$env:QT_QPA_PLATFORM='offscreen'` from the workspace root. Initial caller-focused verification produced **17 failures and 1 pass** before the fixes; the passing case was accepted Paint submission. A direct Move-click regression additionally caught destination consumption before the busy guard.

- `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py` — **59 passed in 0.51s**.
- `.venv/Scripts/python.exe -m pytest -q tests/test_geo_editor_history.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_performance.py tests/test_geo_editor_save.py tests/test_stage4_regenerate_source.py tests/test_dxf_import.py tests/test_editor_move_batch.py tests/test_localized_geometry_fixes.py tests/test_stage5_editor_helpers.py tests/test_project_load_cleanup.py tests/test_projects_appio.py` — **259 passed, 10 subtests passed in 2.41s**.
- `rtk git diff --check` — passed. No agent dispatch, commit, next-ticket work, full-scene history copy or new unconditional render rebuild.

An intermediate run encountered a concurrent Gerber `TransformActionsMixin` import mismatch during collection. No Gerber/user files were changed to resolve it; later reruns passed after that concurrent work settled. All pre-existing changes remain intact. Live OpenGL/OS input remains unverified. GEO-02 is now reviewer-approved per the parent's GEO-03 handoff (59 history tests); this supersedes the historical approval-pending notes above.

### GEO-03 — construction input boundaries (2026-10-21; pending independent review)

**Scope:** GEO-03 only. No agents, commits, new dependencies, shared key framework, storage redesign, or later-ticket work. Changed `appEditors/appGeoEditor.py`, `appGUI/MainGUI.py`, `appEditors/geo_plugins/GeoCirclePlugin.py`, `appEditors/geo_plugins/GeoRectanglePlugin.py`, new `tests/test_geo_editor_input.py`, and this plan. Prior GEO-02 and concurrent USER changes were retained.

**Characterization and fixes:**

- The actual MainGUI dispatcher attempted circle `.x`/`.y` and move/copy `.width` properties that don't exist. Enter now routes the five tools to their numeric handlers exactly once, except the existing zero-field path completion route. Enter before any construction/reference point is rejected without synthesizing a first point or consuming the tool. GEO-02's busy gate remains before dispatch.
- Path/move/copy numeric projection checks first/reference point, finite nonzero length, finite nonzero cursor direction, and finite projected coordinates before appending or jumping. Move/copy use their actual origin, including the selection-acquisition route where `points` can be empty. Invalid input retains construction and committed storage/history and tells users which value or direction to correct.
- Canvas numeric length typing appends raw field text, not an intermediate evaluated value. Existing `NumericalEvalEntry` still evaluates expressions. Integer/string key tests cover `2*5`, fractional `0.05`, and intermediate-zero `2-2+5`; no evaluator or unit semantics were changed.
- Circle Enter validates positive finite radii and finite center/angle, then constructs from those values rather than stale/absent preview geometry. Rectangle Enter validates and projects finite nonzero dimensions, preserving its click-to-complete behavior. Circle/rectangle parameter-panel Add/Apply validates before geometry generation or committed replacement. Their completion clicks regenerate at the actual clicked point and reject degenerate/nonfinite construction; path completion requires two distinct finite points.
- Switching away from the five tools clears utility previews, construction points, in-action state, cursor/HUD state, jump callbacks and temporary plugin button callbacks. Cleanup hides the old parameter frame without recursively selecting another tool. Committed shapes and selection are retained. Escape uses that same switch cleanup. Backspace only backtracks path construction points; the other four tools retain their existing no-op behavior. Coordinate jump remains available in all five tools.

**Behavioral evidence:** `test_geo_editor_input.py` exercises real tool methods, actual MainGUI integer/string Enter dispatch, real Qt button disconnection and numerical widgets, committed storage geometry, undo behavior, stale previews, and busy rejection. The first run reproduced **78 failures / 16 passes** before production fixes. Added expression/current-click checks then exposed **12 failures / 102 passes**. Fractional input checks exposed **6 failures / 12 passes / 108 deselected** before correcting first-keystroke handling.

**Observed verification:**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_input.py tests/test_geo_editor_history.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_save.py tests/test_geo_editor_performance.py tests/test_editor_move_batch.py tests/test_localized_geometry_fixes.py tests/plugins/test_geometry_base_plugins.py -q --tb=short` — **287 passed, 3 subtests passed in 2.19s**, including all **59 history tests**. Existing circle/rectangle Apply coverage is in the history suite; selection/plugin coverage also runs in the performance suite.
- `.venv\Scripts\python.exe -m pytest -q tests/test_geo_editor_input.py` — **126 passed in 0.53s**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_history.py -v --tb=short` — **59 passed in 0.54s**.
- `rtk git diff --check` — passed. Production diff reviewed alongside the pre-existing GEO-02 edits; only the five input tools, their switch/dispatch boundaries, and the two numeric panel guards were changed by GEO-03. Edited production/test files and this plan were reindexed.
- Final `rtk git diff --check` later reported concurrent trailing whitespace in unrelated `appPlugins/ToolMilling.py:2155`; that USER file was left untouched. `rtk git diff --check -- appEditors/appGeoEditor.py appGUI/MainGUI.py appEditors/geo_plugins/GeoCirclePlugin.py appEditors/geo_plugins/GeoRectanglePlugin.py` passed with no output.

**Concurrent work:** The starting tree already had 27 modified and 10 untracked files, including the target editor/GUI/panels, GEO-02 tests, and this plan. None were discarded. During GEO-03, unrelated changes appeared in `appPlugins/ToolMilling.py`, `tests/test_milling_cutz_zero.py`, and `tests/test_milling_target_settings.py`, with further changes in `CHANGELOG.md` and `appObjects/GeometryObject.py`; these files weren't edited by GEO-03.

**Review status/limits:** Implementation verification is complete; GEO-03 remains pending independent review. Tests use the existing headless editor helpers and real Qt widgets, not a live OpenGL session or OS-level keystrokes. No architectural blocker was found. The existing tool-owned jump-signal disconnection convention is retained rather than redesigned.

### GEO-03 — ellipse construction-center review fix (2026-10-21; pending independent review)

**Confirmed regression:** With radius linking disabled, clicking center `(0, 0)` then major-axis point `(3, 4)` left the preview centered at `(0, 0)` but overwrote the panel's center fields with `(3, 4)`. Enter reconstructed from those fields and committed a translated ellipse. The original input helper's constant getters and mock setters hid that state change.

**Localized fix:** `FCCircle.click` now fills the X/Y center fields from the first construction point, not the latest perimeter point. The production change is two lines; Enter reconstruction, preview geometry, numeric validation, busy rejection and history APIs remain unchanged.

**Regression evidence:** Added a real-widget test using `FCDoubleSpinner` center/radius/angle fields, an unchecked Qt linking checkbox, and the actual Circle panel radius properties. It clicks the center and major axis, then invokes Enter through MainGUI. All four cases (origin/translated centers and string/integer Enter) failed before the fix, showing committed centers `(3, 4)` and `(13, -3)` instead of `(0, 0)` and `(10, -7)`. They now verify preview/commit center and sampled contour agreement, center-field/construction consistency, unchanged source geometry, and one-step undo.

**Observed verification:**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_input.py -k ellipse_major_axis -v --tb=short` — before fix: **4 failed, 126 deselected**; after fix: **4 passed, 126 deselected in 0.15s**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_input.py tests/test_geo_editor_history.py tests/test_geo_editor_copy.py tests/test_geo_editor_delete_plot.py tests/test_geo_editor_save.py tests/test_geo_editor_performance.py tests/test_editor_move_batch.py tests/test_localized_geometry_fixes.py tests/plugins/test_geometry_base_plugins.py -q --tb=short` — **291 passed, 3 subtests passed in 2.75s**, including **130 input cases** and all **59 history tests**.

Only `appEditors/appGeoEditor.py`, `tests/test_geo_editor_input.py`, and this evidence were changed for the review fix. All prior/concurrent work was preserved. No agents or commits; GEO-03 still awaits independent review. Live OpenGL/OS-level input remains unverified.

### GEO-04 — midpoint/segment snapping (2026-10-21; evidence pending independent review)

**Approval update:** GEO-02 and GEO-03 are reviewer-approved per the user's GEO-04 handoff. This supersedes the historical pending-review notes above. No later ticket was started.

**Implementation:** Only `appEditors/appGeoEditor.py`, new `tests/test_geo_editor_snapping.py`, and this plan changed for GEO-04. Existing editor-panel FCCheckBox/FCDoubleSpinner/FCLabel controls expose opt-in midpoint and nearest-on-segment snapping, a separate 8-logical-pixel acquisition radius, and active snap type. Both modes require the existing grid master switch and are limited to `call_source == 'geo_editor'`; global consumers don't acquire editor geometry accidentally. LineString/LinearRing segments and MultiLineString parts are supported. Polygonized paths remain straight segments; no exact circle center or tangent is inferred.

**Compatibility and priority:** All `geo_editor.snap` call sites were searched, including appHandlers/appCanvasEvents.py and appHandlers/appObjectOps.py, appCommon, both other editors, MainGUI, PlotCanvas and plugins. The two-argument signature and coordinate-pair return are unchanged. Corner acquisition retains `global_snap_max` in model units. New modes use existing `translate_coords_2`/`translate_coords` to query the pixel-radius neighborhood and validate candidate distance in screen pixels. Missing/unavailable/nonfinite canvas conversion explicitly falls back to `global_snap_max` in model units, described in the UI tooltip and active feedback. Closest model-space candidate wins; exact distance ties favor corner, midpoint, segment, then grid. New same-type ties use coordinate order; existing corner-index insertion-order tie behavior is retained.

**Index/history:** A lazy segment STRtree is reused without any full-scene comparison/scan on warm mouse events. Committed replacement, reset, rollback, and undo/redo invalidate it; storage identity also guards session replacement. A nonblocking acquisition of the existing history lock protects cache publication against concurrent worker mutation. When a worker owns the lock, new geometry snaps are temporarily unavailable rather than blocking or reading half-mutated storage. Utility previews aren't indexed.

**Observed verification (workspace root):**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_snapping.py -q` — initial **13 failed, 3 passed** on absent snapping/UI behavior; after implementation **16 passed in 0.14s**. Added worker-lock and 5,000-path warm-query regressions then produced **1 failed, 17 passed** before the cache publication guard.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_snapping.py tests/test_geo_editor_input.py tests/test_geo_editor_history.py tests/test_geo_editor_performance.py tests/test_geo_editor_delete_plot.py tests/test_editor_move_batch.py tests/test_rtree_storage_ties.py tests/test_panelize_snapping.py tests/test_tool_distance_snap.py tests/test_gerber_editor_pick.py tests/test_vispy_only_geo_editor.py tests/test_vispy_only_manufacturing_events.py tests/test_canvas_dpi.py tests/test_grid_zoom.py -q` — final **407 passed, 28 subtests passed in 18.57s**, including all 18 new snapping cases, 130 input cases and 59 history cases.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_snapping.py -q` — final standalone **18 passed in 0.66s**. `rtk git diff --check` passed. Reviewed the editor diff against the pre-existing GEO02/03 work and the new test/plan patches; no unrelated source changes or deletions. Edited code/tests were reindexed through `src/Beta` and this plan through the documentation index.

**Limits:** Headless geometry tests, real Qt panel widgets and canvas conversion doubles were exercised; no live OpenGL/interactive visual review or OS-level input was performed. First acquisition after a mutation lazily rebuilds the segment index in O(number of segments); warm moves query only spatial candidates (verified with 5,000 paths and a scene-scan trap). Modes and pixel radius are editor-local, not new persisted global preferences. Existing grid/corner preference semantics and master switch are retained. Independent review remains pending; no architectural blocker, nested agents or commits.

**Preservation:** Starting status contained 27 modified and 10 untracked files, including the target editor, this parent-authored plan, and prior GEO02/03 tests. Those changes were retained. No concurrent USER source/test file outside the GEO04 targets was edited.

### GEO-04 — master-switch dispatch review fix (2026-10-21; review pending)

**Reproduced blocker:** Motion only calls `snap()` when `app.grid_status()` is true, but click dispatch calls it unconditionally before the active tool receives its point. The new acquisition branch checked editor context and mode flags without checking that master switch. With either new mode enabled and master off, motion preview received `(5, 0.02)` but the actual FCPath click stored `(5, 0)`.

**Localized fix:** The midpoint/nearest-segment acquisition branch now also requires `self.app.grid_status()`. The legacy corner and grid branches, snap signature, click/motion handlers, preference semantics, cache invalidation and candidate priority remain unchanged. The snapping test helper explicitly supplies an enabled master for direct acquisition tests; its grid-rounding option remains independently controllable.

**Behavioral regressions:** Four parametrized cases execute the real `AppGeoEditor.on_canvas_move`, `AppGeoEditor.on_canvas_click`, shared `snap`, and `FCPath.click` with both modes and master disabled/enabled. They check preview/cursor coordinates, mouse state, stored construction points, active snap type and no new candidate-cache acquisition with the master disabled. The preview/render boundaries use recording doubles; dispatch and construction-point acceptance are real. A fifth case verifies that direct legacy corner/grid snapping still works independently of the new master gate.

**Observed verification (workspace root):**

- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_snapping.py -k 'motion_and_click_dispatch or master_gate' -v` — before fix: **3 failed, 2 passed, 18 deselected**. Both master-off dispatch cases reproduced raw-preview/snapped-click disagreement; the legacy-isolation case also failed because the new segment snap interfered. Both master-on cases already passed.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_snapping.py -v` — after fix: **23 passed in 0.68s**.
- `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_snapping.py tests/test_geo_editor_input.py tests/test_geo_editor_history.py tests/test_geo_editor_performance.py tests/test_geo_editor_delete_plot.py tests/test_editor_move_batch.py tests/test_rtree_storage_ties.py tests/test_panelize_snapping.py tests/test_tool_distance_snap.py tests/test_gerber_editor_pick.py tests/test_vispy_only_geo_editor.py tests/test_vispy_only_manufacturing_events.py tests/test_canvas_dpi.py tests/test_grid_zoom.py -q` — **412 passed, 28 subtests passed in 20.04s**.

**Scope/limits:** Only `appEditors/appGeoEditor.py`, `tests/test_geo_editor_snapping.py`, and this evidence changed for the review fix. All pre-existing/concurrent USER changes remain intact. No agents, commits, later-ticket work or architectural changes. Live OpenGL/OS-level input remains unverified; independent review remains pending.
