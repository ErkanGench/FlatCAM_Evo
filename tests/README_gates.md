# Test gates

All commands run from the repository root with the project interpreter (`.venv/Scripts/python.exe` on Windows).
Never start the GUI (`flatcam.py`) for a gate. No test needs a display. The gates need `pytest-xdist`
(`.venv/Scripts/python.exe -m pip install pytest-xdist`).

Current suite: **4393 tests in 314 files** (`pytest tests --collect-only -q`). Areas: tcl 307, plugins 38,
objects 113, parsers 528, other 3407. Outcomes of the saved baseline: 4389 passed, 4 skipped (platform skips).

## 1. The 3 commands

| When | Command | Time (8 workers) |
|---|---|---|
| While you work on an area | `.venv/Scripts/python.exe -m pytest tests/test_<area>*.py -q -p no:cacheprovider` | seconds |
| Every commit | `.venv/Scripts/python.exe tests/gates/run_core.py` | about 35 s on a quiet machine, 60 s on a busy one |
| Before a push | `.venv/Scripts/python.exe tests/gates/run_gate.py` | about 1 to 2 minutes |

Also run `.venv/Scripts/python.exe tests/gates/check_gate.py` (identity gate, section 2) when a commit adds, renames or
removes tests.

- `run_core.py` runs every test file except the ones in `tests/gates/slow_files.txt` (section 5) with `run_gate.py
  --targeted`, 8 xdist workers, `--dist loadfile`, and compares the outcomes with `outcome_baseline.json`. A new test file
  is in the core by default.
- `run_gate.py` runs the whole suite and compares it with the baseline (section 3).
- `--workers 0` (both runners) runs 1 serial process. Use it to find a test that leaves a global state for the next
  files (a monkeypatch that is not undone, a timer, a singleton): such a failure shows only in a serial run.
- A test that measures time on the GUI thread fails on a busy machine. Wait for the state (a loop of `qWait(10)` with a
  limit), not for a fixed time, or mark it `@pytest.mark.timing` (runs only with `FLATCAM_TEST_TIMING=1`). A test that
  fails in a full run, passes alone and passes again in the next full run is such a case: fix the wait.
- Hardware tests are opt-in (`@pytest.mark.hardware`, `FLATCAM_TEST_HARDWARE=1`).

## 2. Identity gate (`check_gate.py`)

Collects the node ids, sorts every id into exactly 1 area and compares it with `tests/gates/collected_<area>.txt`.

| Area | Files |
|---|---|
| `tcl` | any test file that imports `tclCommands` (or patches a `tclCommands.` name); evaluated first |
| `plugins` | `test_paint*`, `test_clearing*`, `test_clipper*` |
| `objects` | `test_object_*`, `test_excellon_merge_contract*`, `test_project_file*`, `test_lifecycle*` |
| `parsers` | `test_*parser*`, `test_*import*`, `test_*e2e*`, `test_gerber*`, `test_pdf*` |
| `other` | everything else |

```
.venv/Scripts/python.exe tests/gates/check_gate.py            # gate: exit 1 if a saved id is no longer collected
.venv/Scripts/python.exe tests/gates/check_gate.py --update   # rewrite the saved lists
```

- A **removed** id fails the gate (exit 1). It passes only if the commit message names the removed test and says why.
  Then run `--update` in that commit.
- An **added** id is printed as information. Run `--update` in the commit that adds the test.
- An id that **moved** to another area (the area rules changed) is information, not a failure.
- Exit code 2 means pytest could not collect; fix that first.

## 3. Outcome gate (`run_gate.py`)

Builds a map `test id -> outcome` and compares it with `tests/gates/outcome_baseline.json`. A full compare fails when:
a baseline `passed` test is missing (and not in `removed_tests.txt`), a test fails or errors and did not in the baseline,
a new test does not pass, or a test skips/xfails and did not in the baseline (and is not in `allowed_skips.txt`).
`--targeted <pattern...>` runs only the files that match and compares those ids.

Files in `tests/gates/`:
- `removed_tests.txt`: `<test id>  # <reason>`, tests removed on purpose. Empty since the suite cut (the new baseline
  replaced the old entries). Add a line when a commit deletes a baseline test on purpose.
- `allowed_skips.txt`: `<test id>  # <reason>`, tests that may skip (platform or opt-in). Remove a line when its test
  id no longer exists.
- `selfcheck_run_gate.py`: run it after each change of `run_gate.py`.

## 4. Test budget (warning only)

`tests/gates/test_budget.json` holds `max_tests` (4850) and `max_files` (350): the counts at the suite cut plus 10%.
When the collected counts go over it, `run_gate.py` (full run), `run_core.py` and `check_gate.py` print a `WARNING`
block (counts and limit). The exit code does not change. Fold new tests into topical files; the owner decides whether
to raise `test_budget.json`.

## 5. Slow files and baselines

`tests/gates/slow_files.txt` lists the 30 slowest test files (one path per line, measured seconds as a `# comment`).
`run_core.py` skips them; `run_gate.py` runs them. To rebuild the list: run the full suite with `--junitxml`, sum the
`time` of the test cases per file, and list the slowest files until the rest runs in about 30 to 35 s with 8 workers
(the last measurement summed to about 225 s of test time for the core). `run_core.py --list` prints core and slow files.

Regenerate the baselines in the commit that changes tests, after a full run that passes with no failure:

```
.venv/Scripts/python.exe tests/gates/check_gate.py --update          # identity lists
.venv/Scripts/python.exe tests/gates/run_gate.py --save-on-pass      # outcome baseline (written only if the gate passed)
```

`--save-baseline` writes the baseline without a compare; use it only after the full run passed. If a test fails in the
full run, run it alone; if it fails alone too, fix it first. Never save a baseline with failures.

## 6. Fixtures for the unification tests

`tests/fixtures/unify/` holds the Gerber/Excellon files of the unification tests (`unify_mixed.gbr`, `unify_native.gbr`,
`unify_mixed.drl` and single-feature files). The "2 tools with the same diameter and different data" case lives in Python
(`make_same_diameter_excellon` in `tests/helpers_objects.py`).
