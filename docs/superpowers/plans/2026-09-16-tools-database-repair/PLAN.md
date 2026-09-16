# Tools Database Repair Implementation Plan

> **For agentic workers:** Use `executing-plans` or `subagent-driven-development` when execution is authorized. Assign the tickets below to `sex-luna` individually. Steps use checkbox syntax. This handoff is a plan, not authorization to commit or repair the user's live database.

**Goal:** Restore reliable Tools Database editing, persistence, and consumption by Milling, Drilling, Isolation, Paint, NCC, and Cutout; preserve recoverable existing records.

**Architecture:** Keep the existing JSON/FlatDB format, `ToolsDB2` editor, App facade, and plugin controllers. Put the small shared normalization/read/write functions in the existing `appDatabase.py`. Keep matching algorithms local to the plugins. Don't create a database service, new framework, or new persistence backend.

**Tech stack:** Python, PyQt6, simplejson, unittest, existing `.venv`.

---

## 1. Evaluation and evidence

### What was verified

Evaluation date: 2026-09-16. Git HEAD: `4303c4ae`. The working tree already contains a substantial uncommitted App/handler refactor. Findings refer to that working tree, not just HEAD. Runtime checks used `.venv\Scripts\python.exe` (Python 3.14.3), real Qt editor widgets, real consumer methods, and disposable JSON files. No production code was changed during this evaluation.

The adjacent `regression_checks.py` contains 12 unittest methods. Baseline command:

```powershell
.\.venv\Scripts\python.exe docs/superpowers/plans/2026-09-16-tools-database-repair/regression_checks.py
```

Observed baseline: **12 tests run, 16 failing assertions/subtests, 2 errors**. The counts include subtests; they aren't 18 separate test methods. Milling numeric lookup passed. Isolation's subcase of the automatic lookup test passed. Thus, this isn't evidence that every plugin's lookup is independently broken. Shared editor/persistence failures affect records used across the tools.

### Defect inventory

Line numbers are navigation hints. Match the named method before editing because the working tree is changing.

| ID | Evidence | Impact | Ticket |
|---|---|---|---|
| F01 | `ToolDrilling.replace_tools:1213`, `ToolPaint.on_tool_add:982`, `ToolNcc.on_tool_add:1369`, `CutOut.on_tool_add:487` compare integer targets with translated strings; runtime reproduced all four | Database tools skipped, defaults used or drilling parameters left unchanged | DB-05 |
| F02 | `appDatabase.py:296,347,364` use text-returning `FCComboBox` for three integer options; `defaults.py:452-455`; runtime reproduced | Shape/job/offset display resets and invalid persisted types | DB-02 |
| F03 | `ToolsDB2.update_storage:2491,2506` writes job to `data.job` and custom offset to the record root; runtime reproduced | Edits appear to work but consumers read old values | DB-03 |
| F04 | `appDatabase.py:1151-1157` uses gap codes `b/bt/mb`, whereas defaults and Cutout expect `0/1/2`; runtime reproduced | Gap selection cannot round-trip and Cutout modes are misinterpreted | DB-02 |
| F05 | `ToolsDB2.build_db_ui:1761-1794` renders row numbers as IDs and assumes key `'1'`; runtime reproduced with keys `'7','42'` | Opening valid sparse-ID JSON raises `KeyError`; edits/copy/request may target wrong record | DB-04 |
| F06 | `ToolsDB2.on_tool_add:1979-1993` omits drilling dwelltime; runtime reproduced | New records lack a displayed drilling parameter | DB-03 |
| F07 | `AppUIActions.on_tools_database:895-899` returns for an existing tab without rebinding callback; runtime reproduced | Tool selection goes to the previous plugin | DB-07 |
| F08 | `CutOut.on_cutout_tool_add_from_db_executed:585-591` shallow-updates a nested record then modifies it; runtime reproduced | Selecting a tool mutates the editor's database record | DB-06 |
| F09 | `on_save_db_btn_click:2273`, `on_save_changes:1624`, `MainGUI.py:3080` clear dirty state before save; runtime reproduced button failure | Failed saves appear clean; close may lose edits | DB-08/09 |
| F10 | `on_save_tools_db:2204-2268` nests disk I/O under a matching tab title; runtime reproduced with removed tab | Save can silently do nothing | DB-08 |
| F11 | Save/export truncate destination before serialization completes; source-confirmed, failure-injection test required | Interrupted/failed writes can damage the file | DB-08 |
| F12 | `on_save_tools_db:2211-2257` compares targets to strings; its initial General check also makes the non-General branches unreachable | Cleanup never does what its comment claims; fixing the condition alone would delete useful settings | DB-08: remove pruning |
| F13 | Setup/import and six consumers parse JSON without structural validation; source-confirmed | A syntactically valid wrong shape crashes later; import replaces state before validation | DB-01 |
| F14 | Automatic lookup drops `tools_mill_*` from ISO/Paint/NCC/Cutout records, whereas picker insertion retains them; source-confirmed | Database cutting/feed settings depend on how the tool was selected | DB-06 |
| F15 | Paint reads offset before checking whether a record matches; source-confirmed | A later unrelated record supplies another tool's offset | DB-06 |
| F16 | `update_storage:2448` asserts sender type before checking for `None`; multi-selection rollback assumes every field is under `data` and isn't signal-blocked; source-confirmed | Programmatic calls can assert; rejected name/diameter edits can raise or re-enter | DB-03 |
| F17 | Close handler reports save success and deletes editor without checking result; cancel and plugin callbacks directly remove tabs; source-confirmed | Failed save/discard flow loses recovery opportunity | DB-09 |
| F18 | Startup `appMain.py:731-737` treats every `IOError` as missing file | Permission failures may trigger an inappropriate create/truncate attempt | DB-08 |

### Limits of the evaluation

The user's actual versioned `.FlatDB` wasn't supplied or inspected. This establishes application defects, not the exact contents or recoverability of that file. Unknown legacy translations, truncated JSON, and cross-version file selection need DB-11's explicit diagnostic/recovery gate. No assertion is made that old data can always be reconstructed.

Other plugins, such as SolderPaste, have their own tool tables. The six consumers above are the database-path consumers identified in this evaluation; don't add database integration to unrelated tools.

## 2. Fixed decisions: Luna must not redesign these

1. Canonical target IDs remain `0=General, 1=Milling, 2=Drilling, 3=Isolation, 4=Paint, 5=NCC, 6=Cutout`.
2. Canonical shape IDs remain `C1,C2,C3,C4,B,V,L -> 0..6`. Job IDs remain `Roughing,Finishing,Isolation,Polishing -> 0..3`. Offset IDs remain `Path,In,Out,Custom -> 0..3`. Cutout gap IDs remain `Bridge,Thin,M-Bites -> 0..2`.
3. Only `name` and `tooldia` are editable record-root fields. All mapped tool options live in `record['data']`.
4. Preserve IDs; don't renumber on sort or deletion. Allocate `max(existing numeric IDs, default=0)+1`.
5. Preserve unrelated/unknown settings. Remove the dead save-time pruning block instead of making it destructive.
6. Automatic matching remains target-specific. General remains accepted by explicit picker selection. Don't silently broaden auto-match to General or invent precedence between exact and tolerance matches.
7. Preserve the existing inclusive tolerance rule. Multiple matches still cancel without partial insertion. Test zero/one/multiple matches and both tolerance boundaries.
8. For ISO/Paint/NCC/Cutout, copy the plugin's own prefix plus `tools_mill_` and non-`tools_` metadata. Drilling copies `tools_drill_`; Milling copies `tools_mill_`. Use deep copies.
9. Known legacy labels are normalized in memory at read/import boundaries. Opening a file must never rewrite it. Unknown labels fail with record/key context rather than becoming General.
10. No auto-restoration, arbitrary JSON salvage, cross-version file replacement, or deletion of unrecognized fields.
11. UI/default additions use the current options; existing values always take precedence except the two explicitly identified erroneous edit aliases described in DB-01.
12. Serial execution is the default: many tickets share `appDatabase.py`. Don't dispatch two agents to that file at once.

## 3. File ownership and execution order

| Ticket | Priority | Files owned | Depends on |
|---|---|---|---|
| DB-00 | P0 | This directory's regression scaffold | none |
| DB-01 | P0 | `appDatabase.py` normalization/read functions and setup/import; six consumer read blocks | DB-00 |
| DB-02 | P0 | `appDatabase.py` enum widgets and V calculation | DB-01 |
| DB-03 | P1 | `appDatabase.py` edit dispatch and new-record defaults | DB-02 |
| DB-04 | P1 | `appDatabase.py` tree identity/selection/CRUD | DB-03 |
| DB-05 | P0 | Four consumers' target comparisons | DB-01 |
| DB-06 | P1 | Six consumers' matching/copy paths | DB-05 |
| DB-07 | P1 | `appHandlers/appUIActions.py` database opening/picker routing | DB-04 |
| DB-08 | P0 | `appDatabase.py` write/save/export, `appMain.py` missing-file creation, `appGUI/MainGUI.py` save shortcut | DB-04 |
| DB-09 | P0 | `appDatabase.py` close/request, `appHandlers/appUIActions.py`, `appGUI/GUIElements.py`, five picker callbacks | DB-06/07/08 |
| DB-10 | P1 | Focused permanent tests + integration checks | DB-09 |
| DB-11 | P0 before live recovery | A user-selected database COPY and recovery report | DB-10; actual file available |

Suggested serial queue: **00 → 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11**. DB-05 can run alongside DB-02/03/04 only after DB-01 has completed and no consumer edits overlap. Parallelism isn't required.

## 4. Common worker contract

Paste this with the full assigned ticket, sections 1–2, and the adjacent test scaffold into each Luna dispatch:

```text
Implement only ticket DB-XX from the tools database repair plan.
Use sex-luna. Work in the current approved workspace. Don't commit.
The workspace has existing user edits, including an App handler extraction.
Don't revert, format, or stage unrelated changes. Don't edit a live FlatDB file.
Resolve the jCode repo, plan the turn, and inspect the named symbols.
Check blast radius before changing production files. Use apply_patch.
Use .venv/Scripts/python.exe. Keep the existing architecture and style.
Run the ticket's existing failing check before changing production code.
Implement the specified contract; don't weaken assertions to make them pass.
If the code differs from the ticket or a design decision is missing, stop and
report the precise mismatch to the orchestrator rather than inventing behavior.
Report changed files, checks run, before/after outcomes, and remaining blockers.
Don't claim the whole database is fixed from a single ticket's passing test.
```

The orchestrator supplies the actual ticket ID, not the literal placeholder. A worker may extend its ticket's tests. It must not mark unrelated baseline failures as its own regressions. Each handoff must list any new failure outside the ticket scope.

## DB-00 — Establish the executable baseline

**Owner:** Luna verification worker. **Files:** `regression_checks.py` in this directory. **No production edits.**

- [ ] Run the full baseline command above. Preserve the reported method/subtest outcomes in the execution report.
- [ ] Confirm `ConsumerChecks.test_milling_numeric_target_baseline` passes. Confirm Isolation's numeric-target subcase passes.
- [ ] Confirm the sparse-ID error is `KeyError: '1'`, not a fixture/import problem.
- [ ] Retain the offscreen Qt application, temporary database fixture, real `ToolsDB2`, and Qt-slot exception capture.

**Done when:** Baseline matches this report, or the orchestrator has reviewed differences caused by intervening user edits. An environment/import failure isn't evidence of a database defect.

## DB-01 — Normalize and validate database reads transactionally

**Files:** `appDatabase.py`; read/parse blocks in `ToolMilling.py`, `ToolDrilling.py`, `ToolIsolation.py`, `ToolPaint/Paint.py`, `ToolNCC/Ncc.py`, `ToolCutOut.py`. **Methods:** `setup_db_ui`, `on_import_tools_db_file`, five `on_tool_add` methods, `on_tool_db_load`.

**Problem:** Integer/string schema drift is accepted into mutable state and fails later. Legacy records also retain edits in the wrong keys.

- [ ] Add three module-level functions in `appDatabase.py`: `normalize_tools_database(records, defaults)`, `load_tools_database(filename, defaults)`, and internal `_database_enum(value, labels, field)`. Keep UI classes in place.
- [ ] Implement the normalization contract below. Return a deep copy. Include the record ID in errors. Never mutate the input or write a file.

```python
def _database_enum(value, labels, field):
    if type(value) is int and 0 <= value < len(labels):
        return value
    if isinstance(value, str):
        for index, label in enumerate(labels):
            if value in (label, _(label), str(index)):
                return index
    raise ValueError('%s: unsupported value %r' % (field, value))


def load_tools_database(filename, defaults):
    with open(filename, encoding='utf-8-sig') as stream:
        return normalize_tools_database(json.load(stream), defaults)
```

Normalization operations, in this exact order:

1. Require a dictionary at the root. `{}` is valid.
2. Deep-copy input. Require each ID to be a positive decimal string in canonical form (`str(int(key)) == key`). Reject `'01'`, booleans, negative IDs, and zero; don't silently merge IDs.
3. Require each record to be a dict with string `name`, finite numeric `tooldia`, and dict `data`. Reject bool as a number. Preserve existing signed/zero diameter semantics here; consumer input checks remain separate.
4. Require `data.tool_target`. Normalize it using section 2's labels. Missing/unknown targets are errors.
5. Recover known misplaced edits: if `data.job` exists, normalize it as a job and assign to `data.tools_mill_job_type`, then remove `data.job`. If record-root `tools_mill_offset_value` exists, validate numeric/finite and move into `data.tools_mill_offset_value`. **These aliases take precedence** because the faulty editor wrote user edits there while leaving the old canonical value behind. Surface a migration notice; DB-11 preserves originals before saving.
6. Fill missing `tools_mill_`, `tools_drill_`, `tools_iso_`, `tools_paint_`, `tools_ncc_`, `tools_cutout_` values from the supplied current options using `setdefault` and `deepcopy`. Don't fill from any previously selected UI record.
7. Normalize the three milling enums using section 2. Normalize gap strings `b/bt/mb` explicitly to `0/1/2`; accept canonical integers and known label strings. Don't use truthiness: `0` is valid.
8. Set missing `tol_min`/`tol_max` to `0.0`. Require finite numeric bounds, `0 <= min <= max`. For legacy numeric strings, convert only diameter/tolerances/custom offset with `float`; reject conversion failures and non-finite values. Don't coerce arbitrary booleans or unknown option types.
9. Validate numeric values for known numeric defaults when they are present: reject dict/list/non-finite numbers rather than letting a widget swallow an error. Permit `None` only where the corresponding default permits it. Preserve string-valued expressions and coordinate options as strings. Reject malformed types with `record ID + option name` rather than silently resetting.
10. Retain all unknown record/data keys unchanged. Return the new mapping.

Example core validation to reuse:

```python
def finite_number(value, field):
    if isinstance(value, bool):
        raise ValueError('%s: boolean is not a number' % field)
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError('%s: expected a number' % field) from error
    if not math.isfinite(number):
        raise ValueError('%s: expected a finite number' % field)
    return number
```

- [ ] Replace each JSON read block with `load_tools_database(filename, self.app.options)`. Catch `OSError`, `ValueError`, and `TypeError` at the existing user-facing boundary. Log the actual error. Keep existing default-tool fallback where it already exists. Ensure every early return restores blocked/disconnected UI signals.
- [ ] In setup/import, assign `self.db_tool_dict = candidate` only after complete validation. Import also resets stale selection to `None`, rebuilds, and explicitly calls `on_tools_db_edited()`. On failure, keep existing data, selection, and dirty status unchanged.
- [ ] Initialize `self._db_load_valid = False` in `ToolsDB2.__init__` before `setup_db_ui()`. Set it to `True` only after a successful validated load/import. On initial load failure, disable Save/Export/request; keep Import available for recovery. Save/export/request must also check this flag when called programmatically. A failed parse must not expose an empty writable replacement of the damaged file. A rejected later import must preserve the previous flag and working state.
- [ ] Add schema checks to the scaffold using this pattern:

```python
def test_normalization_preserves_input_and_repairs_aliases(self):
    from appDatabase import normalize_tools_database
    source = {'7': record(4)}
    source['7']['data']['tool_target'] = 'Paint'
    source['7']['data']['job'] = 'Finishing'
    source['7']['tools_mill_offset_value'] = 0.75
    source['7']['data']['tools_cutout_gap_type'] = 'mb'
    source['7']['vendor_note'] = {'keep': True}
    before = deepcopy(source)
    result = normalize_tools_database(source, self.app.options)
    self.assertEqual(before, source)
    self.assertEqual(4, result['7']['data']['tool_target'])
    self.assertEqual(1, result['7']['data']['tools_mill_job_type'])
    self.assertEqual(0.75, result['7']['data']['tools_mill_offset_value'])
    self.assertEqual(2, result['7']['data']['tools_cutout_gap_type'])
    self.assertEqual({'keep': True}, result['7']['vendor_note'])
```

**Validation matrix:** empty map; IDs `7/42`; all seven numeric targets; English labels; active-language labels; invalid root `[]`; missing `data`; unknown target; invalid number; NaN; inverted bounds; unknown keys; partial record with missing optional fields; malformed JSON; UTF-8 name; UTF-8 BOM. For each rejected import, compare state and original file bytes before/after.

**Done when:** Every reader shares the same accepted schema; rejected input doesn't mutate state; optional missing fields no longer inherit from another selected tool. This ticket doesn't change matching rules.

## DB-02 — Repair enum widgets and keep V-tool calculation working

**File:** `appDatabase.py`. **Anchors:** `ToolsDB2UI.__init__`, `ToolsDB2.on_calculate_tooldia`.

- [ ] Run `EditorChecks.test_numeric_milling_dropdowns_roundtrip` and `test_cutout_gap_type_roundtrip` first.
- [ ] Change these constructors only:

```python
self.mill_shape_combo = FCComboBox2()
self.job_type_combo = FCComboBox2()
self.mill_tooloffset_type_combo = FCComboBox2()
```

- [ ] Keep the existing radio widget and labels; change only its values:

```python
{'label': _('Bridge'), 'value': 0},
{'label': _('Thin'), 'value': 1},
{'label': 'M-Bites', 'value': 2}
```

- [ ] Update the V condition from `'V'` to `5`. Preserve the diameter formula. Do not change `FCComboBox` globally.
- [ ] Add a V regression: set shape to `5`, tip diameter `0.2`, tip angle `60`, cut depth `-0.1`; invoke calculation and expect `0.3155` at four decimals. Repeat with positive `0.1`. Set shape to `0`, change depth, and assert diameter remains unchanged.
- [ ] Save/reload nonzero enum values and verify integers survive. Switching between two records must restore each record's selections without setting dirty.

**Command:** baseline command plus `EditorChecks.test_numeric_milling_dropdowns_roundtrip EditorChecks.test_cutout_gap_type_roundtrip` as unittest arguments.

**Done when:** Four option families round-trip canonically and the V calculation still runs.

## DB-03 — Repair field dispatch, edit guards, and defaults

**File:** `appDatabase.py`. **Anchors:** `update_storage`, `on_tool_add`, `on_list_item_edited`.

- [ ] Run canonical-key and new-dwelltime scaffold checks first.
- [ ] Reuse the existing `name2option` mapping instead of maintaining the divergent long field-name switch. Keep the existing dirty notification and selection rejection behavior.
- [ ] Move `wdg is None` handling before the type assertion. Treat button/action invocations as dirty notifications. Ignore an unmapped sender safely. Only write if the current ID exists and exactly one record is selected.
- [ ] Resolve the destination from the option name; use the same destination for rollback and write:

```python
option = self.name2option.get(wdg.objectName())
if option is None or tool_id not in self.db_tool_dict:
    return
tool = self.db_tool_dict[tool_id]
storage = tool if option in ('name', 'tooldia') else tool['data']
if len(self.ui.tree_widget.selectedItems()) != 1:
    with QtCore.QSignalBlocker(wdg):
        wdg.set_value(storage[option])
    return
value = wdg.get_value()
if storage.get(option) != value:
    storage[option] = value
    self.on_tools_db_edited()
```

Retain the current multi-selection warning before the rollback return. No-op edits shouldn't set dirty. Tree rename must select/update the row that generated `itemChanged`; don't route a noncurrent row's rename into the current row's form.

- [ ] Add `tools_drill_dwelltime` to `on_tool_add` defaults. Keep new-record defaults otherwise consistent with the existing explicit mapping.
- [ ] Replace the numeric suffix extraction for `new_tool_...` with a guarded integer parse of names beginning with that prefix. A user name such as `new_tool_custom` must not prevent adding another record.
- [ ] Call `on_tools_db_edited()` explicitly after successful add/copy/delete/import instead of relying on a Qt sender existing when these methods call `update_storage()` directly. DB-04 owns ID allocation and selection changes.
- [ ] Add checks for `sender=None`, zero selected rows, two selected rows, rejected name/diameter edits, no recursion during rollback, and one emitted edit notification per real change.

**Done when:** All mapped fields use canonical locations; programmatic CRUD doesn't assert; multi-selection rejection is non-destructive; new records include drilling dwelltime.

## DB-04 — Preserve database identity across tree operations

**File:** `appDatabase.py`. **Anchors:** `build_db_ui`, `on_list_selection_change`, `on_sort_target`, `on_sort_dia`, `on_tool_add`, `on_tool_copy`, `on_tool_delete`, `on_tool_requested_from_app`.

- [ ] Run `EditorChecks.test_sparse_ids_render_actual_keys` first.
- [ ] Use the actual dictionary key in column 0:

```python
title=[str(toolid), t_name, op_name, str(dia)]
```

- [ ] On rebuild, retain the selected ID if present; otherwise select the first actual key. Empty database sets `current_toolid=None`, clears selection, and disables parameter groups. Never assume `'1'` exists.

```python
selected_id = str(self.current_toolid)
if selected_id not in self.db_tool_dict:
    selected_id = next(iter(self.db_tool_dict), None)
self.current_toolid = int(selected_id) if selected_id is not None else None
```

- [ ] Populate tree and set selected row while tree signals are blocked. Then populate the form once with update signals disconnected. Restore connections in `finally`; don't allow a previous row's values to overwrite the new row.
- [ ] Guard `current is None` in `on_list_selection_change`.
- [ ] Allocate add/copy IDs with `max((int(key) for key in self.db_tool_dict), default=0) + 1`. For multiple copies increment once per inserted copy. Do nothing on empty copy/delete selection.
- [ ] Sorting reorders key/value pairs and retains original keys. Deleting removes selected keys and retains all remaining keys. Preserve the selected tool where possible; otherwise choose the first remaining tool.
- [ ] Rebuild tests with IDs `7,42`, copy `7` to `43`, delete `42`, sort by diameter/target, save/reload, then request `43`. Assert callback receives `43`'s values, not row number 2's guessed record.
- [ ] Add empty → add → delete last → add checks; importing fewer records after selecting a high ID must not raise.

**Done when:** Identity is stable and no CRUD/sort/load action reads a fabricated row-number key.

## DB-05 — Restore numeric target matching in four consumers

**Files:** `appPlugins/ToolDrilling.py`, `appPlugins/ToolPaint/Paint.py`, `appPlugins/ToolNCC/Ncc.py`, `appPlugins/ToolCutOut.py`.

- [ ] Run `ConsumerChecks.test_numeric_targets_automatic_lookup` and `test_drilling_numeric_target_updates_parameters` first.
- [ ] Replace only the four comparisons:

```python
# ToolDrilling.replace_tools
if targeted_tool != 2:
    continue
# ToolPaint.on_tool_add
if db_tool_val['data']['tool_target'] != 4:
    continue
# ToolNcc.on_tool_add
if db_tool_val['data']['tool_target'] != 5:
    continue
# CutOut.on_tool_add
if db_tool_val['data']['tool_target'] != 6:
    continue
```

- [ ] Move target rejection before accessing fields only relevant to that target. Leave Milling `1` and Isolation `3` unchanged.
- [ ] In Cutout's no-match branch, pass the requested diameter: `self.on_tool_default_add(dia=tool_dia)`.
- [ ] Run the same lookup after changing the translator to return a prefixed label. Numeric matching must be identical.
- [ ] Retain warnings/default fallback for no match, and cancellation for multiple matches.

**Done when:** All six target-specific numeric lookup paths are covered. General behavior remains as specified in section 2.

## DB-06 — Preserve matched parameters and isolate copies

**Files:** `ToolIsolation.py`, `ToolPaint/Paint.py`, `ToolNCC/Ncc.py`, `ToolCutOut.py`; retain Milling/Drilling baseline coverage. **Anchors:** both exact/tolerance copy branches in `on_tool_add`; Cutout callback; Paint offset assignment.

- [ ] Run the Cutout mutation check first.
- [ ] In each exact and tolerance branch, use the accepted prefix pair. For Paint, for example:

```python
for key, value in db_tool_val['data'].items():
    if not key.startswith('tools_') or key.startswith(('tools_paint_', 'tools_mill_')):
        new_tools_dict[key] = deepcopy(value)
```

Use `tools_iso_`, `tools_ncc_`, or `tools_cutout_` for the respective file. Keep defaults for absent values, then override with the matched record. Don't copy settings from nonmatching records.

- [ ] Paint: remove offset reads before the target/match checks. After exactly one match, read offsets from `new_tools_dict['tools_mill_offset_type']` and `['tools_mill_offset_value']`. Preserve the existing top-level Paint offset fields, now populated from the selected tool.
- [ ] Cutout: construct an independent nested record rather than `tool_from_db.update(tool)` aliasing `data`:

```python
tool_from_db = deepcopy(tool)
data = deepcopy(self.default_data)
data.update(deepcopy(tool['data']))
tool_from_db['data'] = data
```

Keep its existing mappings from milling cut depth/multidepth/depthperpass to Cutout's corresponding UI parameters.

- [ ] In `ToolsDB2.on_tool_requested_from_app`, deliver `deepcopy(record)` to callbacks as a second boundary against consumer mutation. This one-line editor edit must be coordinated with DB-04/09, never concurrent.
- [ ] Add records where a matching Paint tool has offset `3/0.75` followed by a nonmatching Milling tool with `0/0.0`; inserted Paint must retain `3/0.75`.
- [ ] For each of ISO/Paint/NCC/Cutout, set database milling feedrate to `321`, while defaults are `99`; both exact and tolerance insertion must retain `321`. Use a unrelated drilling feedrate sentinel and assert it doesn't replace plugin defaults.
- [ ] Test `min == requested`, `max == requested`, no match, and overlapping matches. On ambiguous match compare entire destination state before/after; it must be unchanged.

**Done when:** Exact and tolerance selection retain the same applicable machining parameters as explicit picker selection; consumer mutation cannot change editor records.

## DB-07 — Rebind a reused picker to its current caller

**File:** `appHandlers/appUIActions.py`. **Anchor:** `AppUIActions.on_tools_database`. Preserve `App.on_tools_database` facade.

- [ ] Run `ConsumerChecks.test_existing_picker_rebinds_callback` first.
- [ ] Resolve the callback before the existing-tab early return. Use a conditional chain, not an eager dictionary that requires every plugin to be initialized:

```python
if source == 'app':
    callback = self.on_geometry_tool_add_from_db_executed
elif source == 'ncc':
    callback = self.app.ncclear_tool.on_ncc_tool_add_from_db_executed
elif source == 'paint':
    callback = self.app.paint_tool.on_paint_tool_add_from_db_executed
elif source == 'iso':
    callback = self.app.isolation_tool.on_iso_tool_add_from_db_executed
elif source == 'cutout':
    callback = self.app.cutout_tool.on_cutout_tool_add_from_db_executed
else:
    self.log.error('Unknown Tools Database source: %s', source)
    return 'fail'
```

- [ ] For an existing tab: assign `on_tool_request=callback`, focus it, and return success. Do this before checking disk access so already-loaded edits remain usable if the backing file becomes unavailable.
- [ ] For a new tab: construct `ToolsDB2(..., callback_on_tool_request=callback)` once. Check `self.app.tools_db_tab._db_load_valid` before enabling picker mode. On failed initial load, show the recovery-capable editor with Import enabled but return `'fail'` to plugin callers so their click handlers don't enable request controls. Manager users can then import a valid copy.
- [ ] Source `app` resets `ok_to_add=False`, shows `buttons_frame`, and hides picker Add/Cancel. Existing plugin click handlers can continue enabling picker mode immediately after this call.
- [ ] Add callback routing checks for `app → Paint → NCC → Isolation → Cutout → app`, always reusing one tab and retaining unsaved records. Check unknown source returns `'fail'` without replacing the tab.

**Done when:** The latest caller owns the picker callback; opening the manager doesn't leave stale selection mode active.

## DB-08 — Atomic writes and truthful dirty state

**Files:** `appDatabase.py`, `appGUI/MainGUI.py` save shortcut branch, `appMain.py` database-file initialization only.

- [ ] Run both save checks first. Add an injected serialization failure and compare destination bytes before/after.
- [ ] Add a module-level atomic writer using Qt's existing atomic file API. No new dependency:

```python
def write_tools_database(filename, records):
    payload = json.dumps(records, default=to_dict, indent=2, ensure_ascii=False).encode('utf-8')
    output = QtCore.QSaveFile(str(filename))
    output.setDirectWriteFallback(False)
    if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    try:
        if output.write(payload) != len(payload):
            raise OSError(output.errorString())
        if not output.commit():
            raise OSError(output.errorString())
    except Exception:
        output.cancelWriting()
        raise
```

- [ ] `on_save_tools_db` validates/normalizes the current mapping, calls the writer regardless of tab visibility, and returns `True` only on success. Catch exceptions, emit the existing error message with logged detail, and return `False`. Don't clear dirty or reset colors on failure.
- [ ] Only after a successful commit: install the normalized mapping, set `tools_db_changed_flag=False`, restore tab/button appearance, and emit success (unless silent).
- [ ] Remove the entire dead target-pruning block. General and plugin-specific records retain all stored settings.
- [ ] Button, context-menu save, and Ctrl+S delegate to save without pre-clearing the flag. Export uses the same writer and returns success/failure; successful export does **not** clear the active database's dirty flag.
- [ ] Replace startup's `except IOError` with `except FileNotFoundError` for database creation. Use exclusive creation (`'x'`) and handle a creation race with `FileExistsError`. Other access failures are logged/reported, not treated as an empty database.
- [ ] Update scaffold's failure injection from `patch('builtins.open', ...)` to `patch('appDatabase.write_tools_database', side_effect=OSError('injected failure'))`; Qt file I/O doesn't use Python's `open`. Keep a separate writer-level test with a fake `QSaveFile` whose write/commit fail, and one real-temp-file success test.
- [ ] Confirm serializer failure occurs before any destination open. Confirm commit failure preserves old bytes. Test non-ASCII tool names and saving without a visible tab.

**Done when:** A failure leaves original bytes and dirty state intact; every save caller gets a truthful result; export is equally protected.

## DB-09 — Make close/request lifecycle respect failed saves

**Files:** `appDatabase.py`; `appHandlers/appUIActions.py`; `appGUI/GUIElements.py::FCDetachableTab2.closeTab`; picker callbacks in Isolation/Paint/NCC/Cutout and `on_geometry_tool_add_from_db_executed`.

**Reason this ticket is serial:** It coordinates Qt tab removal with persistence and callback side effects. Implement exactly this lifecycle rather than adding scattered dirty-flag resets.

- [ ] Add `ToolsDB2.confirm_close()` returning bool. If clean, return `True`. Otherwise show Save/Discard/Cancel. Save returns the result of `on_save_tools_db()`. Discard returns `True` without writing. Cancel returns `False`. Don't delete or remove the widget inside this method.
- [ ] In `FCDetachableTab2.closeTab`, acquire the widget once and honor the optional close confirmation **before** emitting the existing closed signal:

```python
widget = self.widget(currentIndex)
confirm_close = getattr(widget, 'confirm_close', None)
if callable(confirm_close) and not confirm_close():
    return
tab_name = widget.objectName()
self.tab_closed_signal.emit(tab_name, currentIndex)
if self._auto_remove_closed_tab:
    super().removeTab(currentIndex)
```

All other tabs retain their existing signal/removal order because they don't implement this method. Use the existing `_auto_remove_closed_tab` behavior.

- [ ] In the database branch of `AppUIActions.on_plot_area_tab_closed`, remove its duplicate prompt and unconditional success message. It now performs only accepted-close cleanup: disconnect signals, clear dirty state, schedule widget deletion. Don't run the old save path again.
- [ ] `ToolsDB2.on_cancel_tool` asks the tab container to close the database by its index; it no longer directly deletes/removes it. Emit cancellation only when closure was accepted. Don't treat the button itself as unconditional permission to discard edits.
- [ ] Picker callbacks stop closing/removing the database themselves. They validate and insert, returning `'fail'` on rejection and their normal result on success. The geometry callback must propagate insertion failure instead of emitting unconditional success.
- [ ] `on_tool_requested_from_app` snapshots selected records with deep copies. Check selection/empty state first. If dirty, call `confirm_close` before inserting; save failure/cancel prevents insertion. Dispatch all selected records through the snapshot so rebuilding/removing widgets can't invalidate iteration. Stop on a reported failure and keep the database open. Don't promise rollback of previously successful insertions in a multi-select batch; report that partial outcome accurately.
- [ ] Initialize `self._close_preapproved = False` in `ToolsDB2.__init__`. After successful dispatch, set it to `True` and close once. At the start of `confirm_close`, consume this flag (reset to `False` and return `True`) to avoid a second prompt. Also reset it in the request method's `finally` block. On insertion failure leave it `False` and keep dirty edits. A Save choice that already committed successfully remains clean, even if insertion later fails.
- [ ] Test Save-success, Save-failure, Discard, Cancel through tab X, picker Cancel, and successful tool request. For failed saves assert the tab still exists, signals remain connected, original bytes remain intact, and no success message was emitted. Test duplicate/rejected selection stays open. Test two selected records dispatch from a snapshot.

**Done when:** Every database close route has one decision point, failed saves keep the editable state alive, and callback iteration doesn't operate on a removed tab.

## DB-10 — Permanent regression suite and all-tool smoke matrix

**Files:** create `tests/test_tools_database.py` by promoting the scaffold and ticket tests; keep this plan as evidence. Change scaffold root calculation to `Path(__file__).resolve().parents[1]` after moving it under `tests/`.

- [ ] Consolidate only the focused tests developed in DB-01–09. Keep unittest and Qt offscreen. Use real widgets for signal/lifecycle checks, with lightweight App doubles. Don't launch the full CAM engine for field-mapping tests.
- [ ] Run:

```powershell
.\.venv\Scripts\python.exe tests/test_tools_database.py
.\.venv\Scripts\python.exe tests/test_app_handler_characterization.py
.\.venv\Scripts\python.exe tests/test_app_refactor_integration.py
```

If existing handler tests characterize the faulty save/close behavior, update only assertions directly superseded by this plan and explain each change. Existing unrelated failures must be reported separately, not hidden.

- [ ] Perform the following manual matrix using a temporary user-data location or a backed-up test profile. Never generate CNC code for real equipment from an unverified test fixture.

| Route | Fixture | Required observations |
|---|---|---|
| Manager | General and each target | Open, edit nondefault values, save, close, reopen, exact values retained |
| Milling | Geometry object + target 1 | Automatic and picker add retain feedrate, shape, job, custom offset |
| Drilling | Excellon + target 2 | Exact/tolerance replacement retains holes and applies drilling values including dwelltime |
| Isolation | Gerber + target 3 | Automatic/picker agree on isolation settings and milling parameters |
| Paint | target 4 | Automatic/picker agree; unrelated trailing record cannot change offset |
| NCC | target 5 | Automatic/picker agree on operation, overlap, and milling parameters |
| Cutout | target 6 | All three gap types work; cutting parameters transfer; DB record unchanged by selection |
| Reused picker | manager → multiple plugins | Current caller receives selections exactly once |
| Persistence error | unwritable destination/injected commit failure | Dirty state retained, close cancelled, old file readable |
| Import | invalid root, partial legacy, sparse IDs | Invalid input rejected transactionally; accepted legacy normalized and editable |
| Units/language | MM and IN profiles; second UI language | No implicit unit conversion introduced; canonical IDs independent of labels |

- [ ] Assert no unexpected Qt slot exceptions in all widget tests. Run each ticket's new tests once after integration; repeat only after changes or a failure.

**Done when:** All focused tests pass, relevant handler checks pass or have documented unrelated baseline failures, and the smoke matrix has recorded outcomes. A passing scaffold alone isn't sufficient for final acceptance.

## DB-11 — Recover the actual database using a copy

**Input gate:** Obtain the actual file path returned by `app.tools_database_path()` and a byte-for-byte copy. Record application version, units, UI language, and the visible symptom/traceback. Don't infer the path from a different profile or replace the live file merely because a versioned file is empty.

- [ ] Hash the copy and retain an untouched backup. Work only on that copy.
- [ ] Parse JSON. If parsing fails, report the exact error location and available backups; stop automatic recovery. Don't invent missing machining parameters or repair truncated JSON heuristically.
- [ ] Run DB-01 normalization against the copy using the recorded profile defaults. Report per-record changed keys, legacy aliases, missing fields filled from defaults, and unknown labels. Clearly label filled defaults as defaults, not recovered original values.
- [ ] If unknown translated labels remain, show the exact labels and ask the orchestrator/user for their mapping. Add only confirmed mappings with tests; don't map an unfamiliar string to General.
- [ ] Export to a new filename using DB-08. Verify load → save → reload equality, record IDs, names, diameters, and machining values. Compare source/repaired record counts, but don't treat equal counts as proof of correctness.
- [ ] Have the user review the migration report, especially alias conflicts and default-filled feed/depth settings. Only replace the live database when explicitly approved, retaining the original backup.

**Done when:** The actual failure is reproduced on the copy, known repairs pass the full suite, and the user has a verified repaired copy plus an unchanged original. If the file is unrecoverably truncated without a backup, report that rather than claiming code fixes restored its contents.

## 5. Completion checklist for the orchestrator

- [ ] Every F01–F18 entry has a ticket result and a check or explicit remaining gate.
- [ ] All six consumers use normalized reads and have exercised exact/tolerance behavior.
- [ ] Known passing Milling/Isolation baseline behavior stays passing.
- [ ] No production file outside ticket ownership changed without review.
- [ ] Existing App/handler user changes remain intact.
- [ ] No live database was overwritten by tests or by opening the editor.
- [ ] The final report distinguishes repaired application behavior from recovered user data.
- [ ] Commits/PRs occur only on explicit user request.
