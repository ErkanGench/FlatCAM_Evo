# Review fixes RF-01 through RF-06

## Scope and established contracts

This record covers the six localized review-fix tickets executed against the
current working tree. `PLAN.md` and `LUNA-HANDOFF.md` were reviewed first.
The plan's DB-01 through DB-09 work remains the established baseline. DB-10
and DB-11 remain deferred and were not changed. The existing App, handler, and
database refactor changes were already uncommitted and were preserved.

No live FlatDB file was opened or overwritten. No manual GUI testing, real
data recovery, dependency change, commit, or unrelated refactor was performed.

## RF-01 — Consistent `addTab` failure result

**Disposition:** completed.

**Root cause confirmation:** `AppUIActions.on_tools_database` already logged
the `addTab` exception, but the exception branch used a bare `return`. That
returned `None`, unlike the existing construction and invalid-load failure
paths, which return `'fail'`.

**Changed paths:**

- `appHandlers/appUIActions.py`
- `tests/test_tools_database.py`

The branch now returns explicit `'fail'`. Logging, the existing exception
boundary, and the construction flow are unchanged. The regression test forces
`addTab` to raise, verifies `'fail'`, verifies no tab was inserted, and
verifies the coordinate toolbars were not advanced into the success path.

**Before:**

```text
.\.venv\Scripts\python.exe tests/test_tools_database.py ConsumerChecks.test_new_database_add_tab_failure_returns_fail_without_picker_success
FAIL: AssertionError: 'fail' != None
```

**After:**

```text
.\.venv\Scripts\python.exe tests/test_tools_database.py ConsumerChecks.test_new_database_add_tab_failure_returns_fail_without_picker_success
Ran 1 test ... OK
```

The existing normal opening and invalid-load recovery checks also passed in
the final 50-test Tools Database run.

## RF-02 — Forward the facade callback result

**Disposition:** completed.

**Root cause confirmation:** `App.on_geometry_tool_add_from_db_executed` called
`self.ui_actions.on_geometry_tool_add_from_db_executed(tool)` but discarded its
return value. The callback remains directly bound by
`AppUIActions.on_tools_database`; no routing was added.

**Changed paths:**

- `appMain.py`
- `tests/test_appmain_refactored.py`
- `tests/test_app_refactor_integration.py`

The facade now returns the delegated result with the same signature and
argument. Characterization covers both `True` and `'fail'` and verifies the
same tool object is forwarded. The facade return manifest was updated for the
newly characterized return contract.

**Before:**

```text
.\.venv\Scripts\python.exe tests/test_appmain_refactored.py
Ran 30 tests ...
Failures: 2
Both failures: expected True/'fail', got None.
```

**After:**

```text
.\.venv\Scripts\python.exe tests/test_appmain_refactored.py
Tests run: 30
Failures: 0
Errors: 0
ALL TESTS PASSED

.\.venv\Scripts\python.exe tests/test_app_refactor_integration.py
Ran 5 tests ... OK
```

## RF-03 — Save button state independent of tab docking

**Disposition:** completed.

**Root cause confirmation:** After a successful write, dirty state was reset
before the button stylesheet was restored. The stylesheet reset was nested
inside the loop that finds a visible `Tools Database` tab. A detached editor
or an editor with no visible tab therefore saved successfully but retained
the red button style.

**Changed paths:**

- `appDatabase.py`
- `tests/test_tools_database.py`

The editor's existing `restore_stylesheet()` call now runs immediately after a
successful write, independently of tab discovery. Tab text color remains
conditional. Failed write behavior still exits before either reset, and the
regression test keeps both the dirty flag and dirty stylesheet assertion.

**Before:**

```text
.\.venv\Scripts\python.exe tests/test_tools_database.py EditorChecks.test_failed_save_keeps_dirty_flag_and_bytes EditorChecks.test_save_without_visible_tab_writes_database
Ran 2 tests ...
FAIL: expected default stylesheet '', got '.FCButton{color: red;}'
```

**After:**

```text
.\.venv\Scripts\python.exe tests/test_tools_database.py EditorChecks.test_failed_save_keeps_dirty_flag_and_bytes EditorChecks.test_save_without_visible_tab_writes_database
Ran 2 tests ... OK
```

The final Tools Database run retained the failure-path assertions and passed
all 50 tests.

## RF-04 — Notify when New Project retains a vetoed tab

**Disposition:** completed.

**Root cause confirmation:** `on_file_new_project` ignored the result of each
`closeTab` call. `FCDetachableTab2.closeTab` returns explicit `False` when
`confirm_close()` vetoes closure, while legacy successful tab implementations
may return `None`. Ignoring the distinction made a retained tab silent.

**Changed paths:**

- `appHandlers/appIO.py`
- `tests/test_lifecycle_initialization.py`

The reverse iteration and project-reset flow are unchanged. The loop now
collects only results where `closeTab(...) is False`, resolves the actual tab
label, and emits one translated warning after the loop. A single retained
Tools Database message names the tab. Multiple vetoes use an aggregated
generic count. `True` and legacy `None` do not warn. The tab is not force-
closed, the reset is not aborted, and existing save prompts remain owned by
the tab/editor lifecycle.

**Before:**

```text
.\.venv\Scripts\python.exe -m unittest tests.test_lifecycle_initialization.TestNewProjectTabClosure.test_new_project_reports_explicit_tab_close_veto_and_continues -v
FAIL: AssertionError: 1 != 0
No retained-tab warning was emitted.
```

**After:**

```text
.\.venv\Scripts\python.exe -m unittest tests.test_lifecycle_initialization.TestNewProjectTabClosure -v
Ran 2 tests ... OK
```

The explicit `False` case verified one warning and continued project setup.
The `True` and `None` cases verified no spurious warning.

## RF-05 — Remove dead `App.mp_zc` state

**Disposition:** completed.

**Root cause confirmation:** Repository-wide jCode reference analysis found
only two `self.mp_zc = None` assignments in `appMain.py` (the state setup and
GUI setup). There were no live consumers, tests, or shutdown/reset references
to `App.mp_zc`. The active state is `AppObjectOps._mp_zc`, with its ownership
and connect/disconnect behavior at `appHandlers/appObjectOps.py` unchanged.

**Changed path:**

- `appMain.py`

Only the two obsolete assignments were removed. No field was renamed and no
multiprocessing or pool behavior changed. No tautological source-string test
was added.

**Before:**

```text
jCode check_references("self.mp_zc")
appMain.py:430, appMain.py:1078
```

**After:**

Relevant handler, facade, and lifecycle checks passed in the final focused
runs:

```text
.\.venv\Scripts\python.exe tests/test_app_handler_characterization.py
Ran 12 tests ... OK

.\.venv\Scripts\python.exe tests/test_appmain_refactored.py
Tests run: 30
Failures: 0
Errors: 0

.\.venv\Scripts\python.exe tests/test_lifecycle_initialization.py
Tests run: 13
Failures: 0
Errors: 0
Skipped: 2
```

## RF-06 — Make early `AppLifecycle` construction explicit

**Disposition:** completed with localized documentation and runtime coverage.

**Root cause confirmation:** This was a maintenance-risk observation, not a
startup defect. `App._setup_defaults_and_preferences` constructs
`AppLifecycle` before `_setup_gui`. The constructor reads only `log`,
`inform`, `defaults`, and `options`; it does not eagerly access `ui`,
`collection`, or `plotcanvas`.

**Changed paths:**

- `appHandlers/appLifecycle.py`
- `tests/test_lifecycle_initialization.py`

The constructor docstring now records the early-construction boundary and
forbids eager access to the late-initialized UI, collection, and plotcanvas.
A runtime test constructs the handler with only the four early dependencies
and confirms those late attributes are absent.

**Before:**

```text
.\.venv\Scripts\python.exe -m unittest tests.test_lifecycle_initialization.TestAppLifecycleCaching.test_lifecycle_constructs_with_early_app_state -v
Ran 1 test ... OK
```

The invariant already held before the documentation change; the test is
intentionally a characterization of the valid contract rather than a test of
a startup bug.

**After:**

```text
.\.venv\Scripts\python.exe -m unittest tests.test_lifecycle_initialization.TestAppLifecycleCaching.test_lifecycle_constructs_with_early_app_state -v
Ran 1 test ... OK
```

## Final focused verification

All requested focused suites passed after the changes:

```text
.\.venv\Scripts\python.exe tests/test_tools_database.py                 50 tests, OK
.\.venv\Scripts\python.exe tests/test_app_handler_characterization.py   12 tests, OK
.\.venv\Scripts\python.exe tests/test_app_refactor_characterization.py  26 tests, OK
.\.venv\Scripts\python.exe tests/test_app_refactor_integration.py        5 tests, OK
.\.venv\Scripts\python.exe tests/test_appmain.py                         11 tests, OK
.\.venv\Scripts\python.exe tests/test_appmain_refactored.py              30 tests, OK
.\.venv\Scripts\python.exe tests/test_lifecycle_initialization.py        13 tests, 2 skipped, OK
.\.venv\Scripts\python.exe -m pytest tests/test_shutdown_message_filter.py tests/test_worker_stack_shutdown.py -q
                                                                          7 passed, 10 dependency deprecation warnings
.\.venv\Scripts\python.exe -m py_compile appHandlers/appUIActions.py appMain.py appDatabase.py appHandlers/appIO.py appHandlers/appLifecycle.py
                                                                          exit 0, no output
git diff --check                                                       exit 0, no output
```

The direct script invocation of `test_shutdown_message_filter.py` and
`test_worker_stack_shutdown.py` was also attempted before the final run and
failed during test import with `ModuleNotFoundError` because the direct script
path did not add the repository root. This was an invocation/path issue, not a
production failure. Running the same tests through the repository-root pytest
invocation passed. No test or production workaround was added.

## Preserved exclusions

- `set_grid` sender behavior was not changed.
- Duplicate Tools Database close prompts were not restored.
- Existing copy-operation logging and tray-menu script handling were not changed.
- Duplicate `_setup_startup` signal wiring was not restored.
- Detached-window X remains reattach-only with dirty state intact.
- DB-10 and DB-11 deferred statuses in `PLAN.md` were not changed.

No unresolved blockers remain for RF-01 through RF-06. No manual GUI testing
or live data recovery is claimed.
