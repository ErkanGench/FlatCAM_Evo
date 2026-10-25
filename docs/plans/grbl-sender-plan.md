# GRBL Sender plan: complete plan (revision 6 + original tickets)

This file has 2 parts:

- **Part 1: Amendments (revision 6).** The changes after 7 audits.
- **Part 2: Original ticket plan (T01-T19).** The original text, unchanged.

Where Part 1 says nothing, Part 2 stays valid. If the 2 parts conflict, Part 1 wins. Step 0 (A0) copies this whole file to `docs/plans/grbl-sender-plan.md`.

---

# Part 1: Amendments (revision 6)

## Context

The ticket plan "GRBL Sender plugin, and a Levelling tool without GRBL" (T01-T19, Part 2) had 7 audits. They found motion-safety defects, startup blockers and gate defects. The 7th audit found no blocking defect, only 1 wording point (now fixed in A8.3). The user decisions of Part 2 do not change.

Facts that I checked at commit `9a6602c0`:

- `_grbl_failure_locked` (`appPlugins/ToolLevelling.py:2307`) does nothing for a cancelled, failed or replaced operation. It latches recovery only for alarm, `probe_failed` and uncertain motion. It does nothing for `error`.
- `_grbl_active_locked` (`:2299`) is False for a cancelled or failed operation.
- `_grbl_wait_idle` (`:2417`) returns a bool. It fails on the state `Check`.
- `connect_signals_at_init` connects `apply_autolevel_sig` to `self.apply_autolevel` (`:376`).
- `_grbl_reserve` (`:2232`) blocks only **motion** operations during recovery. `tests/test_levelling_audit.py:615-619` expects this.
- `_grbl_transact` (`:2454`) refuses while `_grbl_reset_pending` is True. After an `ok`, `_grbl_prepare_locked` consumes the data in the port buffer.
- `_grbl_confirm_reset` (`:2696`) needs `_grbl_reset_pending`, the same safety generation and an active operation. It ignores lines before the `Grbl ` banner. On the banner, it sets `_grbl_recovery = 'needs_home'`.
- `_grbl_query_status` (`:2534`) can return None (cancel, timeout). It sends the report text to `_grbl_failure_locked`, so `<Alarm|...>` sets `'needs_reset'`, `op.failed` and a new safety generation (reproduced by the 4th audit with `FakeGrbl`).
- `_grbl_wait_idle` checks the operation under the lock, but that check ends when it returns.
- `_al_context_current` (`ToolLevelling.py:1771`) checks the map generation, the target and the units of an asynchronous result.
- `new_levelling_state` (`appPlugins/levelling_interp.py:463`) starts with `home_wcs = None`. The first WCS word of the program declares the frame of the map. The state counts the moves that were not compensated: `arcs`, `relative`, `unparsed`, `unknown`, `frame`, `cutter`, `cycles`, and `arcs_split` for split arcs. `autolevell_gcode` (`ToolLevelling.py:1631-1700`) only warns about these counts.
- Stock GRBL 1.1 runs `$#` only in Idle or Alarm (`system_execute_line()`, `grbl/system.c`). It sends `ok` for `G4` after the planner is empty and the dwell ends (`mc_dwell()`, `grbl/motion_control.c`).
- `tests/` has nested test files (`tests/updater/test_ticket*.py`).

User decision: an imported height map has no GRBL frame. At each levelled Start with an imported map, a dialog asks the user to confirm the frame (A8).

---

## A0. Gate script and outcome baseline (replaces the count rule of R4)

Do this before T01. Commit it with T01.

1. Copy this whole file (Part 1 and Part 2) to `docs/plans/grbl-sender-plan.md`.
2. Make `tests/gates/run_gate.py` with 2 modes:
   - **Full** (no file argument): runs pytest discovery on the folder `tests` (all sub-folders).
   - **Targeted** (`--targeted` and file patterns): expands the patterns with the Python `glob` module (`recursive=True`). No shell expansion.
3. In both modes the script runs `pytest.main([..., '-q', '-p', 'no:cacheprovider', '--continue-on-collection-errors', '--junitxml', <tmp file>])` and then:
   - **Exit code check.** Return code 0 or 1: continue. Return codes 2 (interrupted), 3 (internal error), 4 (usage error) and 5 (no tests collected): print the code and exit 1.
   - **Report check.** The JUnit file must exist and parse. It must have at least 1 test case. The count of test cases must equal the `tests` attribute of the `testsuite`. Else exit 1.
   - **Outcome map.** Make `test id -> outcome` with these outcomes: `passed`, `failed`, `error`, `skipped`, `xfailed`, `collect_error`. A collection error has the id `<file>::<collection>`.
   - In targeted mode, a pattern that matches no file: exit 1.
4. `--save-baseline` (full mode only) writes the map to `tests/gates/outcome_baseline.json`.
5. **Full compare** fails (exit 1) if:
   - a baseline `passed` test is missing or does not pass, and it is not in `tests/gates/removed_tests.txt`;
   - a test that is not in the baseline does not pass;
   - a test has `failed`, `error` or `collect_error`, and it did not have the same outcome in the baseline;
   - a test is `skipped` or `xfailed`, it was not so in the baseline, and it is not in `tests/gates/allowed_skips.txt`.
6. **Targeted compare** uses only the collected ids. It does not treat a baseline id that it did not collect as removed. The other rules of step 5 apply to the collected ids.
7. The script prints each change of outcome. Each line of the 2 text files is `<test id>  # <reason>`.
8. Make `tests/gates/selfcheck_run_gate.py` (no `test_` prefix, so pytest does not collect it). It runs `run_gate.py` in a subprocess and checks a non-zero exit for:
   - `--targeted "tests/no_such_file_*.py"`;
   - `--targeted <tmp file with a syntax error>` (the temp file is in a temp folder).
   Run it 1 time in Step 0, and after each change of `run_gate.py`.
9. Run `run_gate.py --save-baseline` 1 time. If the baseline has `collect_error`, `failed` or `error` entries, tell the user before T01. Commit the JSON file.
10. The gate of each ticket:
    ```
    .venv/Scripts/python.exe tests/gates/run_gate.py
    .venv/Scripts/python.exe tests/gates/check_gate.py
    ```
    During the work of a ticket, use `--targeted` for fast runs. The commit needs the full gate.
11. A ticket that deletes a test on purpose adds its id to `removed_tests.txt` with the reason. New tests must pass.

The T08 and T09 commands for `tests/test_defaults*.py` and `tests/test_appmain*.py` become `run_gate.py --targeted "tests/test_defaults*.py"` (and the same for the other pattern).

## A2. T05: bicubic

1. In `bicubic_offset`, make the missing neighbour by linear extrapolation, so a plane stays exact:
   - before the first node: `2 * v[0] - v[1]`; after the last node: `2 * v[n-1] - v[n-2]`. Same rule on rows.
   - Write a helper `_neighbours(values, i)` that returns `(p0, p1, p2, p3)` with this rule.
2. `bicubic_supported(grid_data, rel_tol=1e-6)` returns True only if each axis has at least 4 values **and** equal spacing: `abs(step - mean_step) <= rel_tol * mean_step` for each step.
3. In `_al_prepare_interp`, the fallback message for `'c'` is `_("Bicubic needs a grid of at least 4 x 4 points with equal spacing. Using bilinear levelling.")`
4. New tests in `tests/test_grbl_bicubic.py`:
   - `test_plane_exact_at_border`: `z = x`, spacing 10, `x = 2.5` and `x = 37.5` give the exact value (`places=9`).
   - `test_nonuniform_not_supported`: X values `[0, 1, 3, 6, 10]` give `bicubic_supported(...) is False`.

## A3. T07: the sender must construct

1. Do not copy the signal `apply_autolevel_sig` and its connect line.
2. Search the copied methods for names that only `ToolLevelling` has (`apply_autolevel`, `on_controller_change`, `al_controller_combo`, `h_gcode_button`, `view_h_gcode_button`, `probing_gcode_text`). Remove each signal connection to them. For any other use, stop (R5).
3. Add `tests/test_grbl_sender_construct.py`. Use the real `QApplication` (pattern of `tests/test_levelling_audit.py:22`) and the real `__init__`:
   - `app = MagicMock()` with `decimals = 4`, `options = dict(AppDefaults.factory_defaults)`, `defaults = options`, `resource_location = 'assets/resources'`, `app_units = 'MM'`.
   - `test_construct`: `ToolGrblSender(app)` does not raise.
   - `test_populate`: `tool._populate_tool_ui()` does not raise.
4. This test file replaces the smoke check of T07 step 9.

## A4. T12: the streamer

`stream_lines` stays pure (no Qt, no app). New signature:

```python
GRBL_RX_BUFFER = 127
GRBL_MAX_LINE = 80          # LINE_BUFFER_SIZE of GRBL 1.1, with the line end

def stream_lines(lines, write, readline, rx_size=GRBL_RX_BUFFER, check_mode=False,
                 on_progress=None, on_line=None, poll_status=False, poll_interval=0.2,
                 on_status=None, clock=time.monotonic, stall_timeout=30.0):
```

1. **Write boundary.** `write(data)` is a callable from the caller. It returns `'ok'`, `'cancelled'`, `'port_error'` or `'stale'`. The streamer never touches the port. On `'cancelled'`, `'port_error'` or `'stale'`, return that status and write nothing more. The streamer calls `write` for each line and for each `?`.
2. **Line size.** Before the first write, check each encoded line (with `\n`). If a line is longer than `min(rx_size, GRBL_MAX_LINE)`, return `'line_too_long'` with `'line_index'`, and write nothing. Also export `validate_stream_lines(lines, rx_size=GRBL_RX_BUFFER)`: the first bad index or None.
3. **Fill condition:** `if used + len(data) > rx_size: break`.
4. **Stall timeout.** Keep `last_progress`. Only these events refresh it:
   - an `ok` or `error:N`;
   - a status report with the state `Hold`, `Door`, `Jog` or `Home`;
   - a status report with the state `Run` and a position that is not the same as in the last report.
   If lines are in flight and `clock() > deadline`, return `'timeout'`. Normally `deadline = last_progress + stall_timeout`.
5. **Dwell.** Add `dwell_seconds(line)`: the `P` value of a `G4` line, else 0.
   - With `poll_status=True`: when the oldest line in flight is a `G4` and a status report shows `Idle`, set `deadline = clock() + dwell_seconds + stall_timeout` 1 time for that line.
   - With `poll_status=False`: when a `G4` becomes the oldest line in flight, set `deadline = clock() + dwell_seconds + stall_timeout` 1 time for that line.
   - The docstring says: without polling, the streamer does not see motion, so a long move can time out. The sender always passes `poll_status=True`.
6. **Error.** At the first `error:N` (not check mode), return `'error'` at once. In check mode, collect each error and continue.
7. A `readline` exception (`serial.SerialException`, `OSError`) gives `'port_error'`.
8. The result dict: `status`, `done`, `errors` (list of `(line index, text)`), `last_text`, `in_flight`, and `line_index` for `'line_too_long'`.

Tests in `tests/test_grbl_stream.py` (the fake port gives `write` and `readline` callables):
- the 8 tests of the original T12, changed to the new signature (`test_stop_request`: `write` returns `'cancelled'` after 3 calls; the status is `'cancelled'`);
- `test_long_line_rejected`, `test_status_does_not_refresh_stall`, `test_moving_run_refreshes_stall`;
- `test_long_dwell_polled`: `G4 P60`, `stall_timeout=30`, `poll_status=True`, a fake clock, `<Idle|...>` reports for 70 s, then `ok`: `'finished'`;
- `test_long_dwell_not_polled`: the same with `poll_status=False` and no status reports: `ok` at 70 s gives `'finished'`; no `ok` until 100 s gives `'timeout'`;
- `test_port_error_after_writes`: `write` returns `'port_error'` at the 4th call: `'port_error'`;
- `test_error_reports_in_flight`: an error at line 2 of 10 short lines: `in_flight >= 1`.

## A5. T13: run control

### A5.1 The write and read callables

The worker of `on_start` builds:

```python
def write(data):
    with self._grbl_op_lock:
        if op.cancel.is_set():
            return 'cancelled'
        if not self._grbl_active_locked(op):
            return 'port_error'
        try:
            count = op.port.write(data)
        except (serial.SerialException, OSError) as err:
            self.app.log.error("ToolGrblSender.write() -> %s" % str(err))
            return 'port_error'
        return 'ok' if count is None or count == len(data) else 'port_error'
```

`readline` reads `op.port.readline()` only while `_grbl_active_locked(op)` is True. Else it returns `b''`.

### A5.2 The stream epoch and the abort

GRBL parses each line of its receive buffer on its own. After an `error:N` or a Stop, the lines in flight still get `ok`. A later transaction must never take such an `ok` as its own reply.

1. Add `self._grbl_stream_dirty = False` to `_grbl_init_state`.
2. The worker sets it to True under the lock **before** the first write of a stream.
3. Only 2 events set it to False:
   - the job ends with a confirmed completion (A5.3);
   - `_grbl_confirm_reset` sees the banner. Add `self._grbl_stream_dirty = False` next to `self._grbl_reset_pending = False` in the copy in `SenderGrbl.py`.
4. In the copy of `_grbl_reserve` in `SenderGrbl.py`, add this check before the motion check:
   ```python
            if self._grbl_stream_dirty and not (name == 'home' and allow_in_recovery):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "GRBL can still have lines of the stopped job. Press Reset, then Home."))
                return None
   ```
   Reset and Stop are real-time bytes under the lock, not operations, so they still work. The rule for other recovery states does not change, so `tests/test_levelling_audit.py:615-619` stays valid.
5. Add to `GrblClientMixin`:
   ```python
   def _grbl_abort_stream_locked(self, op, reason, text=''):
       """
       A stream of `op` failed with lines in GRBL: hold, latch recovery. Caller holds the lock.
       It does nothing if `op` is cancelled, failed or replaced, or if a newer safety epoch
       exists (a Stop or a Reset of the user owns the recovery state then).
       """
   ```
   The steps, in this order:
   1. `if self._grbl_op is not op or op.cancel.is_set() or op.failed or op.safety_generation != self._grbl_safety_generation: return False`
   2. `self._grbl_failure_locked(op, reason, text)`. If `op.failed` is now True, return True (that call latched).
   3. Write `b'!'` through `op.port` (catch the port exceptions and log them). Set `_grbl_recovery = 'needs_reset'`, `_grbl_reset_pending = False`, `_grbl_safety_generation += 1`, `op.failed = True`. Return True.
   It never changes `_grbl_stream_dirty`.
6. The worker maps the streamer status. "Cancelled" means `op.cancel.is_set()`: then Stop or Reset already owns the recovery state.

   | Result | Worker action | `how` |
   |---|---|---|
   | `finished` | completion (A5.3) | see A5.3 |
   | `cancelled` | nothing | `stopped` |
   | `stale` (0 job lines written) | A8.3 step 4.5 | `stale` |
   | `port_error`, `timeout`, `error`, `alarm`, `line_too_long` | if `op.cancel.is_set()`: nothing, `how = 'stopped'`; else `_grbl_abort_stream_locked(op, ...)` | the result name |

   The worker releases the operation only after this step.

Tests in `tests/test_grbl_stream_abort.py` (fake GRBL in the style of `tests/test_levelling_audit.py`):
- `test_error_latches`: `error:20` on line 1 of 10, 5 lines in flight. Then `b'!'` is written, `_grbl_recovery == 'needs_reset'`, and `_grbl_reserve('stream', motion=True)` returns None.
- `test_port_exception_latches`: the port raises `SerialException` at the 4th write. Recovery is latched before the release. A motion reserve returns None.
- `test_old_ok_not_consumed`: after an error with 3 `ok` in the fake, `_grbl_reserve('param')` returns None, and the fake got no new line.
- `test_reset_clears_dirty`: Reset, then a fake banner through `_grbl_confirm_reset`: `_grbl_stream_dirty` is False.
- `test_reset_during_final_wait_kept`: all lines acknowledged, the user presses Reset during `_grbl_wait_idle`. After the worker ends, `_grbl_reset_pending` is True and `_grbl_safety_generation` has the value that Reset set.

### A5.3 Completion

`how` is final only after all steps of this section, also the exit from check mode.

- Streamer `'finished'` means "all lines acknowledged". It does not mean "the job is done".
- **Commit of a success.** Add to `GrblClientMixin`:
  ```python
  def _grbl_commit_success_locked(self, op):
      """
      Make a success final. Caller holds the lock.

      :return: True if `op` still owns the port, is not cancelled or failed, and no newer
          safety epoch exists. Then the stream epoch is clean.
      """
      if (self._grbl_op is not op or op.cancel.is_set() or op.failed
              or op.safety_generation != self._grbl_safety_generation):
          return False
      self._grbl_stream_dirty = False
      return True
  ```
  Each success (`finished`, `check_passed`, `check_passed_needs_home`, and `check_failed` after a good exit) is final only if this call returns True in the same critical section that sets `how`. If it returns False, `how = 'stopped'`, and the worker changes no recovery state.
- **Normal mode:** `ok = self._grbl_wait_idle(op)`.
  - True: under the lock, `how = 'finished' if self._grbl_commit_success_locked(op) else 'stopped'`.
  - False and `op.cancel.is_set()`: `how = 'stopped'`.
  - False otherwise: `_grbl_abort_stream_locked(op, 'timeout')`, `how = 'incomplete'`.
- Test `test_reset_after_idle_wait` in `tests/test_grbl_stream_abort.py`: patch `_grbl_wait_idle` so that it calls `on_grbl_reset()` and then returns True. Expect `how == 'stopped'`, no `[success]`, `_grbl_reset_pending` is True, `_grbl_stream_dirty` is True, and the safety generation is the value of the Reset.
- **Check mode:** see A5.4 and A5.5.
- `_on_stream_ended`:

  | `how` | Message |
  |---|---|
  | `finished` | `[success]` `_("The job finished.")` |
  | `check_passed` | `[success]` `_("Check mode: GRBL found no error.")` |
  | `check_passed_needs_home` | `[WARNING_NOTCL]` `_("Check mode: GRBL found no error. GRBL is in alarm after the reset. Press Home.")` |
  | `check_failed` | `[ERROR_NOTCL]` the list of source line numbers (first 20) |
  | `check_exit_failed` | `[ERROR_NOTCL]` `_("Could not leave check mode.")`, the recovery text, and the error lines if there are any |
  | `stopped`, `incomplete`, other | `[ERROR_NOTCL]` or `[WARNING_NOTCL]` with the recovery text |

  Only `finished` and `check_passed` give `[success]`.

### A5.4 Check mode for 1 job

The checkbox is a request for the next Start. It is not the controller state. The sender sends no `$C` when the user clicks the checkbox.

1. Delete `on_check_mode` and its connect line.
2. `on_start` reads the checkbox 1 time, in the GUI thread. The stream worker does these steps under 1 operation, in this order:
   1. Query the status. It must be `Idle`. If it is `Check`, stop: `_("GRBL is in check mode. Send $C in the console, or press Reset.")`.
   2. If the job is levelled: compare the live frame with the bound frame (A8 step 5). GRBL runs `$#` only in Idle, so this step comes before `$C`.
   3. If check mode was requested: send `$C` with `_grbl_transact`. Confirm `[MSG:Enabled]` in the reply and the status `Check`. Else `_grbl_abort_stream_locked(op, 'error')`, `how = 'check_exit_failed'` if GRBL can be in Check, and do not stream.
   4. Stream.
   5. If check mode was on, see A5.5.
3. Do not keep a check-mode state flag.

### A5.5 The end of a check-mode job

**Only a completed validation leaves check mode by `$C`.** A validation is complete if the streamer result is `'finished'`, `op.cancel` is not set, and `op.failed` is False. Errors that the streamer collected do not make it incomplete.

- Validation complete: call `_grbl_exit_check_mode(op)`.
  - It returns `'idle'`: `how = 'check_failed'` if there are errors, else `'check_passed'`.
  - It returns `'alarm'`: `how = 'check_failed'` if there are errors, else `'check_passed_needs_home'`.
  - It returns `'failed'`: `how = 'check_exit_failed'`.
- Validation not complete (Stop, Reset, alarm, port error, timeout): do **not** send `$C`. Do not clear `op.cancel` or `op.failed`. The A5.2 table gives `how`. GRBL stays in Check until the Reset of the recovery path. A Reset ends check mode.

`_grbl_exit_check_mode(self, op)` in `GrblClientMixin` returns `'idle'`, `'alarm'` or `'failed'`:

1. Under the lock:
   - if `not self._grbl_active_locked(op)`: return `'failed'`;
   - `self._grbl_begin_reset_epoch_locked(op.port)`: the receive boundary of `on_grbl_reset` (`ToolLevelling.py:2790-2800`): `_grbl_rx_buffer = b''`, `_grbl_rx_port = port`, `port.reset_input_buffer()`. If `reset_input_buffer` raises, `_grbl_failure_locked(op, 'port_error')` and return `'failed'`;
   - `_grbl_safety_generation += 1`, then `op.safety_generation = self._grbl_safety_generation`;
   - `_grbl_reset_pending = True`, `_grbl_recovery = 'needs_reset'`, `_grbl_reply_pending = False`;
   - write `b'$C\n'` to `op.port`. On an exception: `_grbl_failure_locked(op, 'port_error')`, return `'failed'`.
2. `if not self._grbl_confirm_reset(op): return 'failed'`. It ignores `[MSG:Disabled]` and `ok` (they come before the banner) and sets `'needs_home'` on the banner.
3. `state = self._grbl_post_reset_state(op)` (see below). Then, under the lock:
   - if `self._grbl_op is not op`, `op.cancel.is_set()`, `op.failed`, or `op.safety_generation != self._grbl_safety_generation`: return `'failed'`;
   - `'Idle'`: set `_grbl_recovery = None`, return `'idle'`. Check mode made no motion, and GRBL keeps its position at a reset in Idle;
   - `'Alarm'`: keep `_grbl_recovery = 'needs_home'` (set by `_grbl_confirm_reset`), return `'alarm'`;
   - None or any other state: `_grbl_failure_locked(op, 'probe_invalid')`, return `'failed'`.
   The caller then commits with `_grbl_commit_success_locked` (A5.3).

**`_grbl_post_reset_state(self, op, timeout=2.0)`** (new, in `GrblClientMixin`). Do not use `_grbl_query_status` here. It sends the status report text to `_grbl_failure_locked`, which treats `<Alarm|...>` as a new alarm: it sets `'needs_reset'`, `op.failed` and a new safety generation. After a confirmed reset with the homing lock, `Alarm` is the expected state, not a new failure.
- Write `b'?'` under the lock, with the same checks as `_grbl_query_status` (active operation, port), but without the `_grbl_reset_pending` check (it is already False after the banner).
- Read lines until the first line that starts with `<`, or the timeout. Return `parse_grbl_status_state(line)`.
- A line `ALARM:N` (a real alarm event) before the status line: call `_grbl_failure_locked(op, 'error', line)` and return None.
- `[MSG:...]` lines (for example `[MSG:'$H'|'$X' to unlock]`) are ignored.
- Do not pass the status line to `_grbl_failure_locked`.
- Timeout or port error: as `_grbl_query_status` does (`_grbl_failure_locked(op, 'timeout' or 'port_error')`), return None.
- Do not change `_grbl_query_status`. Global alarm handling stays the same.

Use `_grbl_begin_reset_epoch_locked` and `_grbl_post_reset_state` only in `_grbl_exit_check_mode`. Do not change the copy of `on_grbl_reset`.

Tests in `tests/test_grbl_check_mode.py`:
- `test_exit_separate_replies`: `[MSG:Disabled]`, `ok`, `Grbl 1.1h ['$' for help]` in 3 `readline` calls, then `<Idle|...>`. Result `'idle'`, `_grbl_recovery is None`, and a motion reserve gives an operation.
- `test_exit_one_chunk`: the same 3 lines in 1 chunk. Same result.
- `test_exit_alarm`: `<Alarm|MPos:0.000,0.000,0.000|FS:0,0>` after the banner, with the **real** `_grbl_post_reset_state` and the `FakeGrbl` of `tests/test_levelling_audit.py` (no mock of the status method). Check: the result is `'alarm'`; `_grbl_recovery == 'needs_home'`; `op.failed` is False; after the release, `_grbl_reserve('stream', motion=True)` returns None, and `_grbl_reserve('home', motion=True, allow_in_recovery=True)` gives an operation.
- `test_exit_real_alarm_line`: the fake sends `ALARM:1` after the banner. Result `'failed'`, `_grbl_recovery == 'needs_reset'`.
- `test_exit_no_banner`: no banner before the timeout. Result `'failed'`, `how == 'check_exit_failed'`, no `[success]`.
- `test_exit_no_status`: banner, then no status reply. Result `'failed'`, no `[success]`.
- `test_exit_cancelled`: the user presses Stop during the exit. Result `'failed'`, no `[success]`, and the Stop recovery state is kept.
- `test_stop_during_check_stream`: Stop while lines stream in check mode. No `$C` is written after the Stop, no `[success]`, and `_grbl_recovery == 'needs_reset'`.
- `test_check_errors_no_success`: replies `ok`, `error:20`, `ok`, then exit `'idle'`. `how == 'check_failed'`, no `[success]`.
- `test_enter_rejected_in_check`: the status before Start is `Check`. Nothing is streamed.
- `test_levelled_check_order`: a fake that refuses `$#` in `Check`. A levelled check-mode Start reads `$#` before `$C`, and the job streams.

### A5.6 Job rebuild

`on_save_levelled_gcode` and `on_show_3d` always call `build_stream_job()`. They never reuse `self.job_lines`. `build_job` calls `validate_stream_lines` and stops with the line number of the first long line.

## A6. T15: the G1 splitter, position rules

Read the state rules of `level_gcode_line` (`appPlugins/levelling_interp.py:1091-1465`) first. Use the same rules where the 2 differ. The splitter must use these rules at least.

1. **Allowed blocks.** Only split a block whose G words are in `{1, 17, 90, 94}`, or a block with no G word in the modal motion G1. The **effective** distance mode after the G words of the block must be a confirmed G90 (not G91, not unknown). An inherited G91 stops the split. The first piece starts with the non-motion G words of the block, in their order. The other pieces start with `G1`.
2. **G words and their effect:**

   | G word | Effect |
   |---|---|
   | 0, 1, 2, 3 | motion mode |
   | 80 | motion mode unknown |
   | 4, 17, 18, 19, 40, 61, 64, 94 | no effect on the position |
   | 90, 91 | distance mode |
   | 93 | no split until the next 94 |
   | 20, 21 | if the units change: X, Y, Z unknown |
   | 43.1, 49 | Z unknown |
   | 38.2, 38.3, 38.4, 38.5 | X, Y, Z unknown, motion mode unknown |
   | 10, 28, 30, 53, 54-59, 59.1-59.3, 92, 92.1 | X, Y, Z unknown |
   | any other G | X, Y, Z unknown, motion mode unknown |

3. `M2` and `M30`: X, Y, Z unknown, motion mode unknown, G90 and G94. A line that starts with `$`: X, Y, Z unknown, motion mode unknown.
4. Axis words in a block that makes a position unknown do not make it known. Only a later absolute `G0`-`G3` move makes an axis known again, axis by axis.
5. `_words` keeps decimal G numbers. Compare G numbers as rounded strings (`'%.1f'`).

New tests in `tests/test_grbl_segment.py`: `test_same_block_g90_kept`, `test_probe_makes_position_unknown` (`G38.2`), `test_tlo_makes_z_unknown` (`G43.1`, `G49`), `test_g53_makes_position_unknown`, `test_wcs_change_makes_position_unknown`, `test_units_change_makes_position_unknown`, `test_inverse_time_not_split`, `test_unknown_g_makes_position_unknown`, `test_modal_g1_without_word_split` (`G1 X0 Y0 Z0 F100` then `X50`), `test_inherited_g91_not_split` (`['G0 X0 Y0 Z0', 'G91', 'G1 X10 F100']`, `max_len=2`: the output is the same list).

## A7. T16: arcs (modal-aware)

`split_arcs` uses the **state counters** of `level_gcode_line`, not the G words of the line. So a bare modal arc line (`X20 Y0 I5 J0` after `G2`) is found.

1. `split_arcs(lines, units, arc_segment, decimals=4)` returns `(new_lines, count, source_index, unsplit)`:
   - For each line, keep a copy of `state['arcs_split']` and `state['arcs']`. Call `level_gcode_line` with a 0 offset.
   - If `arcs_split` grew: output the generated lines (the arc pieces). Each output line maps to the source line in `source_index`.
   - If `arcs` grew: the line is an arc that was not split. Add the source index to `unsplit`, and output the source line.
   - Else: output the source line.
2. **Strict outcome.** If `unsplit` is not empty, stop the preparation: `_("This arc can not be split (plane, frame or position not known). Line %d.")` with the first source line number. This applies when the mode is "split" and when autolevel is on.
3. The levelled path (A8) has the same rule through its strict mode.
4. In `ToolGrblSender`, override `_al_arc_segment(self, target_obj)` to return `float(self.app.options.get("tools_grbl_arc_segment", 0.5))`.
5. Tests in `tests/test_grbl_sender_gen.py`:
   - `test_no_arcs`: the output is the same list, `count == 0`, `source_index == list(range(n))`, `unsplit == []`.
   - `test_modal_arc_split`: `['G0 X0 Y0 Z0', 'G2 X10 Y0 I5 J0 F100', 'X20 Y0 I5 J0']`. Both arc lines are split (`count == 2`). The output has no line that is only `X20 Y0 I5 J0`.
   - `test_unsplit_modal_arc`: `['G18', 'G0 X0 Y0 Z0', 'G2 X10 Z0 I5 K0', 'X20 Z0 I5 K0']`. If the parser does not split G18 arcs, `unsplit` has the indexes of the 2 arc lines. (Read the result of the parser first and set the expected list from the parser rules. Do not change the parser.)

## A8. T16: frame bound height map and job

### A8.1 The bound frame

1. In `_grbl_probe_run`, put `'frame': (active_wcs, offset, report_inches)` in the probe result.
2. Change the hook to `_al_on_height_map_ready(self, target_obj, result=None)`. `_on_al_result_ready` passes `result`. `ToolLevelling` and the default hook of `LevellingCoreMixin` ignore `result`.
3. The sender keeps `self._al_map_frame` and `self._al_map_imported`:
   - a probe result: `_al_map_frame = result['frame']`, `_al_map_imported = False`;
   - an import: `_al_map_frame = None`, `_al_map_imported = True`;
   - `_clear_probe_data`: `None` and `False`.

### A8.2 The transformation is bound to the frame

1. Add the keyword `home_wcs=None` to `new_levelling_state`. If it is not None, set `state['home_wcs']` and `state['wcs']` to it. Use the same value type as `_WCS_G_CODES` (read it first). The existing callers pass nothing, so their behaviour does not change.
2. Add the keywords `home_wcs=None` and `strict=False` to `autolevell_gcode`. Pass `home_wcs` to `new_levelling_state`. With `strict=True`, if any of `arcs`, `relative`, `unparsed`, `unknown`, `frame`, `cutter` or `cycles` is more than 0, emit 1 `[ERROR_NOTCL]` that lists each count, and return None. `ToolLevelling` calls it without these keywords, so its behaviour does not change.
3. Then:
   - a program that starts with `G55` while the map is bound to `G54` gives `frame > 0`, and the preparation stops;
   - a `G92` or `G10 L20` in the program (the parser sets `shifted`) followed by cutting moves gives `frame > 0`, and the preparation stops.
4. **Tool length offset.** The bound frame holds the combined Z offset with the tool length offset (`parse_grbl_work_offset`, `levelling_interp.py:268-336`). The parser makes Z unknown after `G43.1` or `G49`, but a later absolute move makes Z known again, and compensation goes on (the 5th audit reproduced it: all counters 0). So `build_levelled_job` scans the cleaned lines **before** `autolevell_gcode`: if a line has `G43`, `G43.1` or `G49` (use `gcode_segment._words` and the rounded-string compare of A6 step 5), stop the preparation: `_("The program changes the tool length offset (line %d). A levelled job can not do this. Remove it, or make a new height map after the change.")`. This check is only in the sender. The general levelling parser does not change.

### A8.3 The order of a levelled Start

The live frame must be bound **before** the job is made. So a levelled Start has 2 phases. 1 request context goes through both phases.

**The request context.** Add to `Sender.py`:

```python
class _StartRequest:
    """1 levelled Start: the live frame result is valid only for this request."""

    def __init__(self, seq, al_ctx, target_obj, map_frame, map_imported, safety_generation, check_mode):
        self.seq = seq                          # value of ToolGcodeSender._start_seq at the request
        self.al_ctx = al_ctx                    # _al_capture_context(): map generation, target, units
        self.target_obj = target_obj
        self.map_frame = map_frame              # _al_map_frame at the request
        self.map_imported = map_imported
        self.safety_generation = safety_generation
        self.check_mode = check_mode
```

- `self._start_seq = 0` in `__init__`. Each Start adds 1. These events also add 1, so a pending request becomes stale: `on_object_changed`, `_clear_probe_data`, the start of a probe or of an import (`_al_capture_context(replacement=True)`), `_al_on_height_map_ready`, Stop, Reset, connect and port close. The worker threads compare only `req.seq` with `self._start_seq`. The other checks run in the GUI thread.
- **Synchronization rule.** `_start_seq` changes only under `self._grbl_op_lock`:
  - Add `_invalidate_start_requests(self)`: `with self._grbl_op_lock: self._start_seq += 1`.
  - Each event of the list above calls it **before** it publishes the new state (new target, new map, cleared map). Example: in `on_object_changed`, the call is the first line.
  - `_grbl_op_lock` is a `threading.Lock` (`ToolLevelling.py:232`), not re-entrant. Some events already hold it. There, add `self._start_seq += 1` inside the locked section, and do not call the helper:
    - Stop, Reset and port close (their own locked sections);
    - `_al_on_height_map_ready`: `_on_al_result_ready` calls it inside `with self._al_result_lock():`, and the sender returns `_grbl_op_lock` from that hook.
  - For each other event, check that no caller holds the lock before you add the helper call. Each event test runs with a time limit of 2 s, so a deadlock fails the test.
  - The Start makes the request under the lock: `req.seq` and `req.safety_generation` are read in 1 locked section. Widget values are read in the GUI thread before that section.
  - The first-job-line check (A8.3 step 4.4) and the write are in 1 locked section. So the order is defined: if the invalidation gets the lock first, no job line is written; if the first write gets the lock first, the job has started, and the post-start rule applies.
- `_start_request_current(req)` returns True only if all are True:
  - `req.seq == self._start_seq`;
  - `self._al_context_current(req.al_ctx)` (map generation, target, units);
  - `self._target() is req.target_obj`;
  - `self._grbl_safety_generation == req.safety_generation`;
  - `self._al_map_frame == req.map_frame` and `self._al_map_imported == req.map_imported`.
- The map generation rule of the existing code stays: a replacement (probe or import) changes `_al_generation` when it **starts** (`_al_capture_context(replacement=True)`, `ToolLevelling.py:1749-1769`). Its result is accepted only for the context that it captured (`_on_al_result_ready`, `:1785-1840`). The publication of probe heights does not change the generation again, and it must not. The `_start_seq` increments above cover the publication.

**The phases:**

1. **GUI thread.** Add 1 to `_start_seq`. Make the `_StartRequest` **before** any dialog. If `_al_map_imported` is True: show the yes/no dialog `_("This height map was imported. It has no machine frame. Is the machine in the same WCS and zero as when the map was made?")`. The dialog shows at each Start with an imported map.
   - On No: stop.
   - On Yes: if `not self._start_request_current(req)`, drop the request. Tell the user `_("The height map, the object or the machine state changed while the dialog was open. Press Start again.")`. Reserve nothing. A new map needs its own confirmation at the next Start.
2. **Phase 1, worker, operation `'frame'` (non-motion).** Query the status: it must be `Idle`. Read `$G`, `$#` and `$13`, as `_grbl_probe_run` does (`ToolLevelling.py:3287-3302`). The worker calls `_grbl_release(op)` in its `finally` block. It emits `frame_ready_sig(req, live_frame_or_error)` **after** `_grbl_release(op)` returns, never before. So the port is free when the GUI continuation runs.
3. **GUI thread, `_on_frame_ready(req, result)`.**
   - If `not self._start_request_current(req)`: drop the result. Tell the user `_("The Start request is old (the map, the object or the machine state changed). Press Start again.")`. Bind nothing, build nothing, stream nothing.
   - imported map and `_al_map_frame is None`: `_al_map_frame = live frame` (the binding). Set `req.map_frame` to the same value.
   - else: units, G90/G94, WCS and offset (tolerance `1e-4` in machine units) must match `_al_map_frame`. Else stop: `_("The machine frame (WCS or work offset) changed after the height map was made. Probe again.")`
   - Make the job: `build_levelled_job()` calls `autolevell_gcode(..., home_wcs=<WCS of _al_map_frame>, strict=True)`.
   - Reserve the operation `'stream'`. If the reserve fails (busy, recovery), stop with its message. No retry.
4. **Phase 2, worker, operation `'stream'`.** The request is valid until the **first job write**. After that write, the job is bound to the machine, and a request event does not stop it (Stop does).
   1. At the start of the worker, under the lock: `op.safety_generation == req.safety_generation` and `req.seq == self._start_seq`. Else `how = 'stale'`.
   2. A5.4 step 2.2 reads the live frame again and compares it with `req.map_frame`.
   3. After the last preflight query and before `$C`, check `req.seq == self._start_seq` again under the lock. Else `how = 'stale'`.
   4. The `write` callable of A5.1 gets a request check, only for job lines (not for `b'?'`) and only while no job line was written. All steps are in 1 locked section, in this order:
      ```python
      def write(data):
          job_line = data != b'?'
          with self._grbl_op_lock:
              if op.cancel.is_set():
                  return 'cancelled'
              if not self._grbl_active_locked(op):
                  return 'port_error'
              # 1. request check: only before the first full job line
              if job_line and not first_job_line_written[0] and req.seq != self._start_seq:
                  return 'stale'
              # 2. write
              try:
                  count = op.port.write(data)
              except (serial.SerialException, OSError) as err:
                  self.app.log.error("ToolGrblSender.write() -> %s" % str(err))
                  return 'port_error'
              # 3. a short write is a transport failure, never 'stale'
              if count is not None and count != len(data):
                  return 'port_error'
              # 4. only after a full job line
              if job_line:
                  first_job_line_written[0] = True
              return 'ok'
      ```
      This replaces the `write` of A5.1 for the sender. A failed first write gives `'port_error'` and the abort path of A5.2.
   5. The streamer returns the status `'stale'` on a `'stale'` write (add it to A4 step 1). At that time GRBL got no job line.

   **`how = 'stale'`** is not a cancellation and not a failure. The worker does not call `_grbl_abort_stream_locked`, and it changes no recovery state. GRBL got no job line, but a `$C` that was sent still needs a confirmed outcome. The cleanup of a stale request:

   | Cleanup | `how` | Message |
   |---|---|---|
   | Check mode was not entered | `stale` | `_("The Start request is old (the map, the object or the machine state changed). Press Start again.")` |
   | `_grbl_exit_check_mode(op)` returns `'idle'` | `stale` | the same |
   | `_grbl_exit_check_mode(op)` returns `'alarm'` | `stale_needs_home` | `[WARNING_NOTCL]` `_("The Start request is old. GRBL is in alarm after it left check mode. Press Home, then Start again.")` |
   | `_grbl_exit_check_mode(op)` returns `'failed'` | `check_exit_failed` | as in A5.3, with the recovery text |
   | the operation is cancelled during the cleanup | `stopped` | the recovery text |

   **When `_grbl_stream_dirty` goes back to False for a stale request:** only in the rows "Check mode was not entered", `'idle'` and `'alarm'`, and only through `_grbl_commit_success_locked(op)` under the lock, **after** the cleanup. Do not do this commit after `'failed'`. If the commit returns False (Stop or Reset during the cleanup), `how = 'stopped'`, and the newer Stop or Reset keeps its recovery state.

### A8.4 Tests in `tests/test_grbl_frame.py`

- the same frame streams;
- `G55` on the controller after a `G54` probe: refused in phase 1;
- a changed work offset: refused;
- an imported map with "No": nothing is read and nothing streams;
- an imported map with "Yes": the first Start binds the frame; a 2nd Start with another offset is refused;
- a `G54` map with a program header `G55`: `build_levelled_job` returns False;
- a program with `G92 X0 Y0` in the middle followed by `G1` cutting moves: `build_levelled_job` returns False;
- `ToolLevelling.autolevell_gcode` without the new keywords gives the same text as before (1 existing journey case);
- `test_map_replaced_during_frame`: import map B while phase 1 runs for map A. The frame result is dropped: no binding, no job, no stream;
- `test_target_changed_during_frame`: change the CNCJob in the combo while phase 1 runs. Same result;
- `test_frame_signal_after_release`: a fake signal records `self._grbl_op` at the emit. It is None, and the stream reserve in `_on_frame_ready` gives an operation;
- `test_map_replaced_during_dialog`: the dialog stub runs a queued import of map B, then answers Yes. No frame operation is reserved, nothing is bound, nothing streams;
- `test_map_changed_during_final_frame_query`: the fake runs a map change while it answers the last `$#` of phase 2. The fake gets 0 job lines, and `how == 'stale'`;
- `test_target_changed_before_first_write`: change the target after the frame compare and before the first job write. The fake gets 0 job lines, `how == 'stale'`, and `_grbl_recovery` does not change;
- `test_invalidation_wins_lock`: the test holds `_grbl_op_lock`, starts the first job write in a thread, calls `_start_seq += 1` while it holds the lock, then releases it. The write returns `'stale'`, and the fake got 0 job lines;
- `test_first_write_wins_lock`: the fake `write` blocks on a `threading.Event` while the worker holds the lock. A 2nd thread calls `_invalidate_start_requests()`, and it blocks. The test sets the event. The first job line is written, the flag is True, and then `_start_seq` changes. Later job lines are written (post-start rule);
- `test_short_first_write`: the fake returns a short count for the first job line. The result is `'port_error'`, recovery is latched (`'needs_reset'`), and `first_job_line_written[0]` is False;
- `test_stale_after_check_alarm`: invalidate the request after `$C` was confirmed and before the first job line. `_grbl_exit_check_mode` gets a real `<Alarm|...>` after the banner. The fake got 0 job lines, `_grbl_recovery == 'needs_home'`, `how == 'stale_needs_home'`, and the message says Home;
- `test_tlo_change_refused`: a map probed with a TLO of 1.5 (in the fake `$#` reply), then the program `G90 G21 G54` / `G0 X0 Y0 Z5` / `G49` / `G0 X0 Y0 Z5` / `G1 X10 Y0 Z0`. `build_levelled_job` returns False. The same with `G43.1 Z2` in place of `G49`.

## A9. T18 and T19: the 3D view

1. **Accepted, not done.** Rename `DONE_COLOR` to `ACCEPTED_COLOR` and `set_done` to `set_accepted`. The docstring says "the lines that GRBL accepted". The tool marker shows the real position.
2. **Report units.** At Start and at connect, read `$13` with `parse_grbl_setting`. Keep `self._grbl_report_inches`. In `_on_status_report`, multiply each position by `grbl_report_scale(job_units, self._grbl_report_inches)`.
3. **WCO cache.** Set `self._last_wco = None` at Start, Zero, Reset, connect and port close.
4. **Toolpath frame.** `parse_toolpath(lines, start=None)` uses the rules of A6 steps 2-5. With an unknown position, it makes no segment until all 3 axes are known.
5. **Arcs in "send" mode.** For the display only, run `split_arcs` on a copy. Map each segment to its stream line with `source_index`. Lines in `unsplit` are drawn as chords in a dashed or grey style.
6. **Old visuals.** `on_show_3d` always rebuilds the job (A5.6). `_update_3d_height_map` calls `self.view3d.set_height_map(None)` when `al_heights_valid` is False. `on_object_changed` clears `job_lines` and the toolpath.
7. Tests in `tests/test_grbl_toolpath.py`: the 4 original tests (with `start=(0, 0, 0)`), plus `test_unknown_start_no_segment`, `test_g92_then_unknown` and `test_probe_then_unknown`.

## A10. Small changes

- T13 manual check: also test Stop while the buffer fills, and an `error` line in a job of 50 lines.
- T17: no change.

---

## Where each change goes

| Change | Ticket |
|---|---|
| A0 | before T01, committed with T01 |
| A2 | T05 |
| A3; A5.2 steps 1, 3 (`_grbl_confirm_reset` line) and 4 in the copies in `SenderGrbl.py` | T07 |
| A4 | T12 |
| A5.1, A5.2 steps 2, 5, 6, A5.3-A5.6 (with `_grbl_commit_success_locked`, `_grbl_exit_check_mode`, `_grbl_post_reset_state`) | T13 |
| A8.3 (`_StartRequest`, `frame_ready_sig`, the 2 phases) | T16 |
| A6 | T15 |
| A7, A8 | T16 |
| A9 | T18, T19 |

The ticket order T01-T19 does not change.

## Verification

1. Step 0: `selfcheck_run_gate.py` passes, and the baseline is saved.
2. Each ticket: the full gate of A0 step 10 exits with 0.
3. New test files: `test_grbl_sender_construct.py`, `test_grbl_stream.py`, `test_grbl_stream_abort.py`, `test_grbl_check_mode.py`, `test_grbl_segment.py`, `test_grbl_sender_gen.py`, `test_grbl_frame.py`, `test_grbl_toolpath.py`, `test_grbl_bicubic.py`, `test_grbl_protocol.py`. The full gate collects them.
4. Manual check in the app (the user): the list of the original "Final check", plus:
   - Check mode: check the box, Start, see `Check mode: GRBL found no error.` After the job, GRBL is Idle and not in check mode.
   - A job with a bad line in check mode: an error with the line number, no success text.
   - Stop during a job: Start and the parameter read are refused until Reset and Home.
   - Probe in G54, switch to G55, levelled Start: the sender refuses.
   - Import a height map, levelled Start: the dialog shows at each Start.

---
---

# Part 2: Original ticket plan (T01-T19)

# GRBL Sender plugin, and a Levelling tool without GRBL: ticket plan

## Context

`appPlugins/ToolLevelling.py` (4485 lines) does 2 jobs now. It makes height maps for MACH3, MACH4 and LinuxCNC, and it has a full GRBL serial client. The user wants a GRBL G-code sender (like Candle or bCNC, without the CAD part) inside FlatCAM EVO, with autolevelling in it.

These are the user's decisions. Do not change them.

- Levelling keeps MACH3, MACH4 and LinuxCNC only. All GRBL code goes to a new plugin, **GRBL Sender**.
- The sender does autolevelling, with the same probe methods as Levelling (grid, Voronoi, manual points, avoid Excellon holes), plus a new **bicubic** method.
- The first release of the sender has:
  - streaming with character counting, and run control;
  - jog, zero and a console;
  - overrides and check mode (`$C`);
  - autolevelling.
- Output is stream only. The source CNCJob does not change. "Save levelled G-code" writes a file.
- If `CNCjob.is_segmented_gcode` is True, use the G-code as it is. If it is False, segment the G1 moves.
- Arcs: a preference selects "send G2/G3" or "split into G1". With autolevel on, arcs are always split.
- Visualizer: the Plot 3D tab (`appGUI/PlotCanvas3d.py`). The user now adds a grid size from a Preferences value (the bed size). Use `set_grid_size()`.
- Console: an `FCDock` like the Tcl Shell. It docks on the right and is hidden by default. When the tool closes, the dock hides. A checkbox in the Tool tab sets its visibility, and the app keeps that value.
- All other controls go in the Tool tab of the left notebook.
- A CNCJob combo preselects the active CNCJob and lets the user pick another job.
- A "GRBL Sender" button in the CNCJob UI goes between "Levelling" and "Save / Review".
- Shared files go to the new folder `appPlugins/Common/`.
- Commit `e6f5eb27` (2026-10-16) removed the Legacy 2D graphic engine (Matplotlib). VisPy is the only canvas now. `app.use_3d_engine`, `ShapeCollectionLegacy`, `mpl_key_event` and the handler references `kp`/`mm`/`mr` do not exist any more. The line numbers in this plan are from after that commit.

Do not copy code from Candle. Candle is GPL-3.0 and FlatCAM EVO is MIT.

### 2 design details that follow from the code

1. **The GRBL code moves with the same method names.** The tests build the tool with `ToolLevelling.__new__` and set more than 30 `_grbl_*` attributes directly (`tests/test_levelling_audit.py:34-83`). So the GRBL methods move unchanged into a mixin class `GrblClientMixin`, and the non-GRBL methods move unchanged into `LevellingCoreMixin`. Then the about 470 GRBL tests port by changing the test factory only.
2. **The test files keep their names.** The identity gate (`tests/gates/check_gate.py`) fails when a test id goes away. A test id is `file::Class::test`, so the file names stay the same. New tests go into new files.

---

## Rules for every ticket (read these first)

R1. Run all commands from the repository root `D:\1.Development\1.PROJECTS\FlatCAM_EVO`. Use the interpreter `.venv/Scripts/python.exe`. Never start `flatcam.py` for a test.

R2. **Move code, do not rewrite it.** When a ticket says "move method X", cut the full method, from the `def` line to the last line before the next `def` at the same indentation. Paste it without changes, unless the ticket names a change.

R3. Each ticket ends with 1 commit on the branch `1.0`.
- Message format: `<type>(<scope>): <text>`. Examples: `refactor(levelling): ...`, `feat(grbl-sender): ...`, `test(grbl-sender): ...`.
- Do not add a `Co-Authored-By` line or any Claude attribution.
- Do not push.

R4. The test gate for each ticket. Run these 3 commands in this order:
```
.venv/Scripts/python.exe -m pytest tests/test_levelling.py tests/test_levelling_apply_regressions.py tests/test_levelling_arc_g91.py tests/test_levelling_arc_g91_sim.py tests/test_levelling_audit.py tests/test_levelling_connection_regressions.py tests/test_levelling_controller_regressions.py tests/test_levelling_e2e.py tests/test_levelling_frame.py tests/test_levelling_g53_regressions.py tests/test_levelling_journey.py tests/test_levelling_lifecycle_regressions.py tests/test_levelling_precision.py tests/test_levelling_result_regressions.py tests/test_levelling_safety_regressions.py tests/test_levelling_tool.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/test_grbl_*.py -q -p no:cacheprovider        (only after T09 makes the first file)
.venv/Scripts/python.exe tests/gates/check_gate.py
```
- Before the first ticket, run the first command 1 time and write down the number of passed tests. This is the **baseline**.
- After each ticket, the count of passed tests must be at least the baseline. If a ticket deletes a test on purpose, the count can be lower by that number.
- `check_gate.py` must exit with 0. If a ticket adds tests, run `.venv/Scripts/python.exe tests/gates/check_gate.py --update` in the same commit.
- If a ticket deletes a test on purpose, the commit message must name each deleted test id and say why. Then run `--update`.

(Part 1, A0 replaces the count rule and the commands of R4.)

R5. **If a step does not work as the ticket says, stop.** Report the ticket number, the step, the command and the full error text. Do not guess a fix, and do not change test assertions unless the ticket says so.

R6. Before you delete or rename a symbol, run the jcode tool `check_delete_safe` or `check_rename_safe` on it. Before you move a file, run `find_importers` on it.

R7. Write comments and messages in the style of the code around them. Each user-visible string goes through `_()`.

R8. Ticket order. Each ticket needs the tickets before it, except where the ticket says otherwise. Do not start a ticket while the gate of the ticket before it fails.

R9. VisPy is the only canvas. New code and moved code must not use `use_3d_engine`, `ShapeCollectionLegacy`, `PlotCanvasLegacy`, `matplotlib`, `mpl_key_event`, `event.xdata`/`event.ydata`, or the handler references `self.kp`, `self.mm`, `self.mr`, `self.app.kp`, `self.app.mp`, `self.app.mr`. The tests `tests/test_vispy_only_*.py` check some plugins for these names.

R10. The line numbers in the tickets are from commit `9a6602c0`. If a line number does not show the code that the ticket quotes, find the quoted code with a search, and use its line. If you cannot find the quoted code, stop (R5).

---

## Target layout (after all tickets)

```
appPlugins/Common/__init__.py              (empty)
appPlugins/Common/levelling_interp.py      moved from appPlugins/levelling_interp.py, without the GRBL parsers
                                           + bicubic_offset() (T05)
appPlugins/Common/grbl_protocol.py         the GRBL parsers (moved), + parse_grbl_status_report() (T12)
appPlugins/Common/gcode_segment.py         split_long_moves(), parse_toolpath() (T15, T18)
appPlugins/Common/levelling_core.py        LevellingCoreMixin, _AlContext, _iter_polygons, VORONOI_ENABLED,
                                           MAX_AVOID_TRIES
appPlugins/Common/levelling_ui.py          build_probe_points_ui()
appPlugins/ToolLevelling.py                ToolLevelling(LevellingCoreMixin, CNCjob, AppTool) + LevelUI
appPlugins/ToolGrblSender/__init__.py      (empty)
appPlugins/ToolGrblSender/SenderGrbl.py    GrblClientMixin, _GrblOperation, _GrblProbeAbort
appPlugins/ToolGrblSender/Sender.py        ToolGrblSender(LevellingCoreMixin, GrblClientMixin, CNCjob, AppTool)
appPlugins/ToolGrblSender/SenderUI.py      GrblSenderUI
appPlugins/ToolGrblSender/SenderGen.py     SenderGen (job preparation)
appPlugins/ToolGrblSender/SenderView3d.py  SenderView3d (3D visuals)
appGUI/preferences/tools/ToolsGrblSenderPrefGroupUI.py
tests/test_grbl_protocol.py, tests/test_grbl_bicubic.py, tests/test_grbl_segment.py,
tests/test_grbl_stream.py, tests/test_grbl_sender_gen.py, tests/test_grbl_toolpath.py
```

---

## Phase A: Shared folder and modules

### T01: Make `appPlugins/Common/` and move `levelling_interp.py`

Files: `appPlugins/levelling_interp.py`, `appPlugins/ToolLevelling.py`, 8 test files.

1. Make the empty file `appPlugins/Common/__init__.py`.
2. Move the file with git, so the history stays:
   `git mv appPlugins/levelling_interp.py appPlugins/Common/levelling_interp.py`
3. In `appPlugins/ToolLevelling.py:56`, change `from appPlugins.levelling_interp import (` to `from appPlugins.Common.levelling_interp import (`.
4. In the tests, change the old import path to the new path. These are the only 2 patterns:
   - `from appPlugins.levelling_interp import` becomes `from appPlugins.Common.levelling_interp import`
   - `from appPlugins import levelling_interp as li` becomes `from appPlugins.Common import levelling_interp as li`

   The files are `test_levelling.py`, `test_levelling_arc_g91.py`, `test_levelling_arc_g91_sim.py`, `test_levelling_audit.py`, `test_levelling_frame.py`, `test_levelling_g53_regressions.py`, `test_levelling_journey.py` and `test_levelling_tool.py`. To find any line that you missed, run:
   `grep -rn "appPlugins.levelling_interp\|appPlugins import levelling_interp" --include=*.py . | grep -v .worktrees`
   The result must be empty.
5. `docs/benchmark_shapely_clipper2.py:152` imports `test_levelling_journey`, not the module. Do not change it.
6. Run the gate (R4).

Commit: `refactor(levelling): move levelling_interp into appPlugins/Common`

### T02: Move the GRBL parsers to `appPlugins/Common/grbl_protocol.py`

1. Make `appPlugins/Common/grbl_protocol.py` with this header:
```python
# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/15/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
Pure parsers for the replies of a GRBL 1.1 controller.

No Qt imports, no app imports - standard library only, so these functions
can be unit tested without the GUI stack.
"""

import math
import re
```
2. Move these 9 functions from `appPlugins/Common/levelling_interp.py` into `grbl_protocol.py`, in this order. Also move each module constant that only these functions use:
   - `_PRB_RE` (line 210) and `parse_grbl_probe_output` (213)
   - `_ACTIVE_WCS_RE` (256), `_OFFSET_RE` (257), `parse_grbl_active_wcs` (260) and `parse_grbl_work_offset` (268)
   - `_GRBL_ERROR_RE` (1468), `_SETTING_RE` (1469), `_STATUS_RE` (1470) and `_GC_RE` (1471)
   - `grbl_reply_error` (1474), `probe_timeout_s` (1487), `grbl_report_scale` (1504), `parse_grbl_setting` (1519), `parse_grbl_status_state` (1533) and `grbl_modes_confirmed` (1545)

   Before you move a constant, search `levelling_interp.py` for its name. If another function in `levelling_interp.py` still uses it, copy the constant and do not move it.
3. If a moved function calls a helper that stays in `levelling_interp.py`, add `from appPlugins.Common.levelling_interp import <helper>` at the top of `grbl_protocol.py`.
4. In `appPlugins/ToolLevelling.py:56-74`, split the import. The names `parse_grbl_probe_output`, `parse_grbl_active_wcs`, `parse_grbl_work_offset`, `grbl_reply_error`, `probe_timeout_s`, `grbl_report_scale`, `parse_grbl_setting`, `parse_grbl_status_state` and `grbl_modes_confirmed` now come from `appPlugins.Common.grbl_protocol`.
5. Tests:
   - In each test file that imports 1 of the 9 names from `levelling_interp`, import it from `appPlugins.Common.grbl_protocol`.
   - Where a test uses `li.<name>` for 1 of these 9 names (`li.grbl_modes_confirmed`, `li.grbl_reply_error`, `li.grbl_report_scale`, `li.parse_grbl_setting`, `li.parse_grbl_status_state`, `li.probe_timeout_s`), add `from appPlugins.Common import grbl_protocol as gp` after the `li` import, and change `li.<name>` to `gp.<name>`.
   - Find the uses with `grep -rnE "li\.(parse_grbl_|grbl_|probe_timeout_s)" tests`.
   - Do not change `patch('appPlugins.ToolLevelling.probe_timeout_s', ...)`. ToolLevelling still imports that name, so the patch still works.
6. Run the gate.

Commit: `refactor(levelling): move the GRBL reply parsers into appPlugins/Common/grbl_protocol.py`

### T03: Delete the dead modules `appCommon/bilinear.py` and `appCommon/bilinearInterpolator.py`

1. Run `find_importers` (jcode) on both files. If the result shows an importer, stop (R5).
2. `git rm appCommon/bilinear.py appCommon/bilinearInterpolator.py`
3. Run `grep -rn "bilinearInterpolator\|appCommon.bilinear\|from appCommon import bilinear" --include=*.py . | grep -v .worktrees`. The result must be empty.
4. Run the gate.

Commit: `chore: delete the unused bilinear modules of appCommon`

---

## Phase B: `LevellingCoreMixin` (ToolLevelling still has GRBL)

### T04: Make `LevellingCoreMixin` and move the shared methods into it

Files: new `appPlugins/Common/levelling_core.py`, `appPlugins/ToolLevelling.py`.

1. Make `appPlugins/Common/levelling_core.py` with this skeleton:
```python
# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/15/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
The probe points, the height map and the levelling of G-code, shared by the
Levelling Plugin (MACH3, MACH4, LinuxCNC) and the GRBL Sender Plugin.

The class that uses LevellingCoreMixin must have: self.app, self.ui (with the
widgets made by build_probe_points_ui()), self.units, self.decimals,
self.drawing_tolerance (from CNCjob), and the 4 hooks at the end of the class.
"""

import contextlib
import math
import random
from copy import deepcopy

from PyQt6 import QtWidgets, QtCore, QtGui
from shapely import Point, MultiPoint, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.affinity import translate
import numpy as np

import gettext
import appTranslation as fcTranslate
import builtins

from appObjects.AppObjectTemplate import ObjectDeleted
from appGUI.VisPyVisuals import ShapeCollection
from appGUI.GUIElements import FCFileSaveDialog
from defaults import AppDefaults

from appPlugins.Common.levelling_interp import (
    build_bilinear_grid,
    bilinear_offset,
    nearest_offset,
    match_nearest_point,
    match_tolerance,
    new_levelling_state,
    level_gcode_line,
    parse_height_map_line,
)

try:
    from shapely.ops import voronoi_diagram
    VORONOI_ENABLED = True
except Exception:
    VORONOI_ENABLED = False

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

# maximum number of steps per direction when moving a probe point away from an Excellon hole
MAX_AVOID_TRIES = 10000


# <- paste _iter_polygons here (ToolLevelling.py:112-131)

# <- paste class _AlContext here (ToolLevelling.py:149-161)


class LevellingCoreMixin:

    def _al_init_state(self):
        """Set the probe-point state. Call it from __init__ of the tool."""
        # <- the body is in step 3

    # <- paste the methods of step 2 here, in the order of the table

    # ------------------------------------------------------------------
    # hooks: each tool that uses this mixin overrides these 4 methods
    # ------------------------------------------------------------------
    def _al_set_buttons_enabled(self, enabled):
        """Enable the buttons that need probe points. `enabled` is True if the table has rows."""
        pass

    def _al_result_lock(self):
        """The lock that _on_al_result_ready() holds while it publishes a result."""
        return contextlib.nullcontext()

    def _al_result_retired(self, result):
        """:return: True if the operation that made `result` was stopped or replaced."""
        return False

    def _al_on_height_map_ready(self, target_obj):
        """Called after a probe or an import gave a complete and valid height map."""
        pass
```
   - Line 50 of `ToolLevelling.py` is `from appGUI.VisPyVisuals import *`. The mixin needs only `ShapeCollection`, so it imports that name only.
   - The moved methods have no Legacy code any more (commit `e6f5eb27` removed it). If you see `use_3d_engine` or `ShapeCollectionLegacy` in a moved method, stop (R5): the file is not at the expected commit.
   - `np` comes into `ToolLevelling.py` through that star import. The mixin imports `numpy as np` itself.

2. Move these methods from `class ToolLevelling` into `class LevellingCoreMixin`, unchanged (R2), in this order:

   | Method | Line now in ToolLevelling.py |
   |---|---|
   | `_new_probing_shapes` | 581 |
   | `_clear_probe_data` | 632 |
   | `_height_map_is_complete` | 659 |
   | `on_object_selection_changed` | 664 |
   | `change_level`, `on_level_changed` | 682, 696 |
   | `build_tool_ui`, `build_al_table` | 737, 744 |
   | `on_add_al_probepoints`, `check_point_over_excellon`, `on_add_grid_points`, `on_add_manual_points` | 809-1003 |
   | `_on_show_probing_geo_sig`, `show_probing_geo`, `_generate_bilinear_heatmap`, `plot_probing_geo`, `add_probing_shape` | 1004-1205 |
   | `generate_voronoi_geometry` and the commented `generate_voronoi_geometry_2` block | 1206-1285 |
   | `generate_bilinear_geometry`, `_release_manual_mouse_events`, `_finish_manual_points` | 1286-1347 |
   | `on_mouse_move`, `on_mouse_click_release`, `on_key_press` | 1348-1463 |
   | `_al_grid_tolerance`, `_al_match_tolerance`, `autolevell_gcode_line`, `_al_capture_apply_input`, `_al_prepare_interp`, `autolevell_gcode`, `_al_arc_segment`, `autolevell_bilinear`, `autolevell_voronoi` | 1464-1744 |
   | `_al_bump_generation`, `_al_capture_context`, `_al_context_current`, `_on_al_result_ready` | 1745-1841 |
   | `on_show_al_table`, `on_mode_radio`, `_restore_al_radios` | 1842-1877 |
   | `_update_mode_radio_ui`, `on_avoid_exc_holes`, `on_method_radio`, `_update_method_radio_ui` | 1915-1966 |
   | `on_import_height_map`, `import_height_map` | 3064-3172 |
   | `on_grbl_heightmap_save` | 3491-3533 |

   Also move the module function `_iter_polygons` (112-131) and the class `_AlContext` (149-161) to the places in the skeleton. Delete them from `ToolLevelling.py`. Also delete the `VORONOI_ENABLED` try block, the comment above `MAX_AVOID_TRIES` and `MAX_AVOID_TRIES` (95-109) from `ToolLevelling.py`. Keep the `fcTranslate.apply_language('strings')` block and `log = ...` that are between them. Add this import to `ToolLevelling.py`:
   `from appPlugins.Common.levelling_core import LevellingCoreMixin, _AlContext, _iter_polygons, VORONOI_ENABLED, MAX_AVOID_TRIES`
   Some tests patch or read these names through `appPlugins.ToolLevelling`, so this import must stay.

3. Make `_al_init_state()`. In `ToolLevelling.__init__`, these blocks set the probe-point state. Cut them out of `__init__` and paste them into the body of `_al_init_state()`, in the same order:
   - lines 206-216: `form_fields`, `first_click`, `cursor_pos`, `mouse_is_dragging`, `mouse_events_connected`;
   - line 219: `probing_gcode_text`;
   - lines 223-229: `al_heights_valid`, `_al_apply_running`;
   - lines 248-285: `_al_generation`, `_al_data_units`, `_al_target_name`, `_al_target_obj`, `al_voronoi_geo_storage`, `al_bilinear_geo_storage`, `_al_points`, `_al_grid`, `_al_offset_fn`, `_al_decimals`;
   - line 287: `solid_geo`;
   - line 290: `probing_shapes`;
   - lines 294-298: `old_selection_state`. This block uses `app_defaults`, so start the body of `_al_init_state()` with this line:
     `app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults`

   In `ToolLevelling.__init__`, at the place of the first cut block (after `CNCjob.__init__(...)`), add the call `self._al_init_state()`. The GRBL lines (220-221, 231-246, 288) stay in `ToolLevelling.__init__` in this ticket.

4. Put the hooks in place inside the moved methods. These are the only changes to moved code:
   - **In `build_al_table`**, replace the last 10 lines (the `if self.ui.al_probe_points_table.model().rowCount(): ... else: ...` block that enables `grbl_get_heightmap_button`, `grbl_save_height_map_button`, `h_gcode_button` and `view_h_gcode_button`) with:
     `self._al_set_buttons_enabled(bool(self.ui.al_probe_points_table.model().rowCount()))`
   - **In `_on_al_result_ready`**:
     - replace `with self._grbl_op_lock:` with `with self._al_result_lock():`;
     - replace the 5 lines that start with `op = result.get('operation')` and end with `return` (old lines 1800-1804) with:
       ```python
                   if self._al_result_retired(result):
                       return
       ```
     - replace the last line `self.apply_autolevel(target_obj=result['context'].target_obj)` with:
       `self._al_on_height_map_ready(result['context'].target_obj)`
   - **In `_al_capture_apply_input`**, add the keyword argument `require_segmented=True`. Change the first test to:
     ```python
             if target_obj is None or (require_segmented and target_obj.is_segmented_gcode is not True):
     ```

5. In `ToolLevelling.py`, change the class line to `class ToolLevelling(LevellingCoreMixin, CNCjob, AppTool):`. Add the 4 hooks after `reset_fields` (they keep the GRBL behavior until T10):
```python
    # ------------------------------------------------------------------
    # LevellingCoreMixin hooks
    # ------------------------------------------------------------------
    def _al_set_buttons_enabled(self, enabled):
        self.ui.grbl_get_heightmap_button.setDisabled(not enabled)
        self.ui.grbl_save_height_map_button.setDisabled(not enabled)
        self.ui.h_gcode_button.setDisabled(not enabled)
        self.ui.view_h_gcode_button.setDisabled(not enabled)

    def _al_result_lock(self):
        return self._grbl_op_lock

    def _al_result_retired(self, result):
        op = result.get('operation')
        return (op is not None and op.cancel.is_set()) or (
                'safety_generation' in result and
                result['safety_generation'] != self._grbl_safety_generation)

    def _al_on_height_map_ready(self, target_obj):
        self.apply_autolevel(target_obj=target_obj)
```

6. Remove the imports that `ToolLevelling.py` no longer uses. Run `.venv/Scripts/python.exe -m pyflakes appPlugins/ToolLevelling.py appPlugins/Common/levelling_core.py`. If pyflakes is not installed, run `.venv/Scripts/python.exe -m pip install pyflakes` first.
   - Fix each "imported but unused" line.
   - Fix each "undefined name" line by adding the import that the moved code needs.
   - Do not change other pyflakes lines.

7. Test patch paths. These tests patch names at module level, and after the move the names live in `levelling_core`. Change only these targets:
   - `'appPlugins.ToolLevelling.ShapeCollection'` → `'appPlugins.Common.levelling_core.ShapeCollection'`
   - `'appPlugins.ToolLevelling.build_bilinear_grid'` → `'appPlugins.Common.levelling_core.build_bilinear_grid'`
   - `'appPlugins.ToolLevelling.QtWidgets.QFileDialog.getOpenFileName'`: no change. QtWidgets is the same module object.
   - `'appPlugins.ToolLevelling.FCFileSaveDialog.get_saved_filename'`: no change. It patches the class attribute, which is the same class.
   - `tl_module.box`: this test patches `box` for the grid code, which is now in `levelling_core`. Change `tl_module.box` to `lc_module.box`, and add `import appPlugins.Common.levelling_core as lc_module` to the imports of that test file.
   - `patch.object(tl_module, 'new_levelling_state', ...)`, or `tl_module.new_levelling_state`: change `tl_module` to `lc_module` in the same way.
8. Run the gate. All tests must pass with no other test change. If a test fails, stop (R5).

Commit: `refactor(levelling): move the probe-point model into LevellingCoreMixin`

### T05: Add the bicubic method

(Part 1, A2 changes the border rule, `bicubic_supported` and the fallback message.)

Files: `appPlugins/Common/levelling_interp.py`, `appPlugins/Common/levelling_core.py`, `appPlugins/ToolLevelling.py` (LevelUI), `appGUI/preferences/tools/ToolsLevelPrefGroupUI.py`, new `tests/test_grbl_bicubic.py`.

1. Add this function to `levelling_interp.py`, after `bilinear_offset`:
```python
def _catmull_rom(p0, p1, p2, p3, t):
    """Catmull-Rom spline value between p1 (t=0) and p2 (t=1)."""
    return p1 + 0.5 * t * (p2 - p0 + t * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3 +
                                          t * (3.0 * (p1 - p2) + p3 - p0)))


def bicubic_offset(grid_data, x, y):
    """
    Compute the bicubic (Catmull-Rom) interpolated height offset at (x, y)
    using a grid built by build_bilinear_grid.

    x and y are clamped into the grid's range, so the spline parameter is
    always in [0, 1] and the value is never extrapolated. At the border of
    the grid the missing neighbour is the border value itself.

    :param grid_data: tuple (xs, ys, grid) as returned by build_bilinear_grid.
        It must have at least 4 values on each axis (see bicubic_supported()).
    :param x: query X coordinate.
    :param y: query Y coordinate.
    :return: interpolated height offset (float).
    """
    xs, ys, grid = grid_data

    x = min(max(x, xs[0]), xs[-1])
    y = min(max(y, ys[0]), ys[-1])

    i = bisect.bisect_right(xs, x) - 1
    i = min(max(i, 0), len(xs) - 2)
    j = bisect.bisect_right(ys, y) - 1
    j = min(max(j, 0), len(ys) - 2)

    tx = 0.0 if xs[i + 1] == xs[i] else (x - xs[i]) / (xs[i + 1] - xs[i])
    ty = 0.0 if ys[j + 1] == ys[j] else (y - ys[j]) / (ys[j + 1] - ys[j])

    def col(index):
        return min(max(index, 0), len(xs) - 1)

    def row(index):
        return min(max(index, 0), len(ys) - 1)

    rows = []
    for dj in (-1, 0, 1, 2):
        r = grid[row(j + dj)]
        rows.append(_catmull_rom(r[col(i - 1)], r[col(i)], r[col(i + 1)], r[col(i + 2)], tx))
    return _catmull_rom(rows[0], rows[1], rows[2], rows[3], ty)


def bicubic_supported(grid_data):
    """:return: True if the grid has at least 4 values on each axis."""
    return grid_data is not None and len(grid_data[0]) >= 4 and len(grid_data[1]) >= 4
```
2. In `levelling_core.py`:
   - add `bicubic_offset` and `bicubic_supported` to the import from `levelling_interp`;
   - add this method after `autolevell_bilinear`:
     ```python
         def autolevell_bicubic(self, x, y):
             return bicubic_offset(self._al_grid, x, y)
     ```
3. In `_al_prepare_interp` (levelling_core.py), replace the block `if al_method == 'b': ... else: self._al_offset_fn = self.autolevell_voronoi` with:
```python
        if al_method in ('b', 'c'):
            self._al_grid = build_bilinear_grid(points, tol)
            if self._al_grid is None:
                self.app.inform.emit(
                    '[WARNING_NOTCL] %s' %
                    _("Probe points do not form a regular grid. Using nearest-point levelling.")
                )
                self._al_offset_fn = self.autolevell_voronoi
            elif al_method == 'c' and not bicubic_supported(self._al_grid):
                self.app.inform.emit(
                    '[WARNING_NOTCL] %s' %
                    _("Bicubic needs at least 4 rows and 4 columns. Using bilinear levelling.")
                )
                self._al_offset_fn = self.autolevell_bilinear
            elif al_method == 'c':
                self._al_offset_fn = self.autolevell_bicubic
            else:
                self._al_offset_fn = self.autolevell_bilinear
        else:
            self._al_offset_fn = self.autolevell_voronoi
```
4. Change these method checks in `levelling_core.py`. Find each one with the search text in the left column:

   | Search text (in method) | Change to |
   |---|---|
   | `elif al_method == 'b':` (in `show_probing_geo`) | `elif al_method in ('b', 'c'):` |
   | `if al_method == 'b' and self._al_grid is not None:` (in `autolevell_gcode`) | `if al_method in ('b', 'c') and self._al_grid is not None:` |
   | `if method in ('v', 'b'):` (in `on_mode_radio`) | `if method in ('v', 'b', 'c'):` |
   | `method = method if method in ('v', 'b') and mode != 'manual' else 'v'` (in `_restore_al_radios`) | `method = method if method in ('v', 'b', 'c') and mode != 'manual' else 'v'` |
   | `if val not in ('v', 'b'):` (in `on_method_radio`) | `if val not in ('v', 'b', 'c'):` |
   | `if val == 'b':` (in `_update_method_radio_ui`) | `if val in ('b', 'c'):` |

   The checks `if al_method == 'v': ... else:` stay the same, because `'c'` uses the bilinear storage like `'b'`.
5. In the `RadioSet` of `al_method_radio` (LevelUI in `ToolLevelling.py:3927`, and `ToolsLevelPrefGroupUI.py`), add a 3rd item after Bilinear: `{'label': _('Bicubic'), 'value': 'c'}`. Add this line to the tooltip text: `"- Bicubic: smooth surface through the grid. Needs at least 4 rows and 4 columns.\n"`.
6. Make `tests/test_grbl_bicubic.py`:
```python
#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.Common.levelling_interp import (
    build_bilinear_grid, bicubic_offset, bicubic_supported, bilinear_offset)


def grid_points(fn, n=5, step=10.0):
    return [(i * step, j * step, fn(i * step, j * step)) for i in range(n) for j in range(n)]


class TestBicubic(unittest.TestCase):
    def test_hits_grid_nodes(self):
        g = build_bilinear_grid(grid_points(lambda x, y: 0.01 * x * y))
        self.assertAlmostEqual(bicubic_offset(g, 20.0, 30.0), 0.01 * 20.0 * 30.0, places=9)

    def test_plane_is_exact(self):
        g = build_bilinear_grid(grid_points(lambda x, y: 0.2 * x - 0.1 * y + 1.0))
        self.assertAlmostEqual(bicubic_offset(g, 13.0, 27.0), 0.2 * 13.0 - 0.1 * 27.0 + 1.0, places=9)

    def test_clamped_outside(self):
        g = build_bilinear_grid(grid_points(lambda x, y: x + y))
        self.assertAlmostEqual(bicubic_offset(g, -50.0, -50.0), bicubic_offset(g, 0.0, 0.0), places=9)
        self.assertAlmostEqual(bicubic_offset(g, 500.0, 500.0), bicubic_offset(g, 40.0, 40.0), places=9)

    def test_supported_needs_4x4(self):
        self.assertTrue(bicubic_supported(build_bilinear_grid(grid_points(lambda x, y: 0.0, n=4))))
        self.assertFalse(bicubic_supported(build_bilinear_grid(grid_points(lambda x, y: 0.0, n=3))))
        self.assertFalse(bicubic_supported(None))

    def test_close_to_bilinear_on_smooth_surface(self):
        g = build_bilinear_grid(grid_points(lambda x, y: 0.001 * (x - 20.0) ** 2))
        self.assertLess(abs(bicubic_offset(g, 15.0, 15.0) - bilinear_offset(g, 15.0, 15.0)), 0.05)


if __name__ == '__main__':
    unittest.main()
```
7. Run the gate. Run `check_gate.py --update`, because this ticket adds tests.

Commit: `feat(levelling): add the bicubic height-map method`

---

## Phase C: The GRBL Sender plugin

### T06: Shared probe-points UI builder

Files: new `appPlugins/Common/levelling_ui.py`, `appPlugins/ToolLevelling.py` (LevelUI).

1. Make `appPlugins/Common/levelling_ui.py`:
```python
# (same file header as in T02, with the docstring below)
"""The probe-point widgets, shared by the Levelling and the GRBL Sender UIs."""

from PyQt6 import QtWidgets, QtCore, QtGui

from appGUI.GUIElements import (
    FCLabel, FCButton, FCFrame, GLay, FCCheckBox, RadioSet, FCDoubleSpinner, FCSpinner, FCTable)

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def build_probe_points_ui(ui, app, parent_box):
    """
    Make the probe-point widgets as attributes of `ui` and add them to
    `parent_box` (a QVBoxLayout). After the call `ui` has: al_frame, al_box,
    al_title, show_al_table, al_probe_points_table, plot_probing_pts_cb,
    avoid_exc_holes_cb, avoid_exc_holes_size_label, avoid_exc_holes_size_entry,
    probe_gc_label, probe_tip_dia_entry, ptravelz_entry, pdepth_entry,
    feedrate_probe_entry, al_mode_radio, al_method_lbl, al_method_radio,
    al_columns_entry, al_columns_label, al_rows_entry, al_rows_label,
    al_add_button, import_heights_button, tool_grid, param_grid.

    :param ui:         the UI object (LevelUI or GrblSenderUI); it needs ui.decimals.
    :param app:        the App.
    :param parent_box: the layout that gets al_frame.
    """
    # <- body: see step 2
```
2. Make the body of `build_probe_points_ui` from `LevelUI.__init__`:
   - Cut lines 3761-3962 (from `# Autolevelling` to `self.al_box.addWidget(self.al_add_button)`) and paste them into the body.
   - Replace every `self.` with `ui.` in the pasted text.
   - Change `self.tools_box.addWidget(self.al_frame)` (now `ui.tools_box.addWidget(ui.al_frame)`) to `parent_box.addWidget(ui.al_frame)`.
   - Change `ui.decimals` in the pasted text only where it was `self.decimals`. `ui` has `decimals`.
   - The pasted text makes the local variables `grid0`, `tt_frame`, `tool_grid`, `tp_frame` and `param_grid`. Keep them local, but after the pasted text add `ui.tool_grid = tool_grid` and `ui.param_grid = param_grid`.
3. Also move the import button: cut LevelUI lines 4356-4363 (`self.import_heights_button = ...` to `self.al_box.addWidget(self.import_heights_button)`). Paste them at the end of the body with `self.` replaced by `ui.`.
4. At the end of the body, add the 2 checkbox handlers that were in LevelUI (4387-4388, 4407-4411):
```python
    def on_plot_points_changed(state):
        app.options["tools_al_plot_points"] = False if not state else True

    def on_avoid_exc_holes_changed(state):
        app.options["tools_al_avoid_exc_holes"] = False if not state else True

    ui.plot_probing_pts_cb.stateChanged.connect(on_plot_points_changed)
    ui.avoid_exc_holes_cb.stateChanged.connect(on_avoid_exc_holes_changed)
```
   In `LevelUI`, delete the 2 connect lines (4387-4388). Keep the methods `on_plot_points_changed` and `on_avoid_exc_holes_changed` in LevelUI, because a test can call them.
5. In `LevelUI.__init__`, at the place of the cut lines (after `self.tools_box.addWidget(self.object_combo)`), add:
   `build_probe_points_ui(self, self.app, self.tools_box)`
   and the import `from appPlugins.Common.levelling_ui import build_probe_points_ui`.
6. The rest of `LevelUI` (the controller frame from line 3964, the GRBL frame and `height_lay`) still uses `self.al_box`. That attribute now exists on `self` through `ui.al_box`, so these lines stay.
7. At the end of `LevelUI.__init__`, change `GLay.set_common_column_size([tool_grid, param_grid], 0)` to `GLay.set_common_column_size([self.tool_grid, self.param_grid], 0)`.
8. Run pyflakes on both files (as in T04 step 6). Run the gate.

Commit: `refactor(levelling): build the probe-point widgets in appPlugins/Common/levelling_ui.py`

### T07: Make the sender package with the GRBL code

(Part 1, A3 and A5.2 change this ticket.)

This ticket copies the GRBL code into the new package. ToolLevelling keeps its own copy until T10, so the app works between the tickets.

Files: new `appPlugins/ToolGrblSender/__init__.py` (empty), `SenderGrbl.py`, `Sender.py`, `SenderUI.py`.

1. **`SenderGrbl.py`** is the transport: the methods that do not read `self.ui`. The skeleton:
```python
# (file header as in T02)
"""
The GRBL serial client of the GRBL Sender Plugin: 1 operation owns the port at
a time, every reply is classified, and an uncertain motion latches recovery.

The class that uses GrblClientMixin must have self.app and must call
self._grbl_init_state() in __init__. It must also have the hook
_grbl_set_ui_connected(connected) and the signal grbl_port_closed_sig.
"""

import time
import threading

import serial
import serial.tools.list_ports

import gettext
import appTranslation as fcTranslate
import builtins

from appPlugins.Common.grbl_protocol import (
    parse_grbl_probe_output,
    parse_grbl_active_wcs,
    parse_grbl_work_offset,
    grbl_reply_error,
    probe_timeout_s,
    grbl_report_scale,
    parse_grbl_setting,
    parse_grbl_status_state,
    grbl_modes_confirmed,
)
from appPlugins.Common.levelling_interp import match_nearest_point

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


# <- copy class _GrblProbeAbort (ToolLevelling.py:134-146)
# <- copy class _GrblOperation (ToolLevelling.py:164-180)


class GrblClientMixin:

    def _grbl_init_state(self):
        # <- copy ToolLevelling.__init__ lines 220-221 (grbl_probe_result, grbl_work_offset),
        #    231-246 (the serial session state) and 288 (grbl_ser_port)
        pass

    # <- copy the transport methods of step 2
```
2. Copy these methods from `ToolLevelling` into `GrblClientMixin`, unchanged (R2):
   - `on_grbl_list_serial_ports` (1995-2003, with `@staticmethod`)
   - `_grbl_close_port`, `_grbl_disconnect`, `_grbl_force_close` (2153-2210)
   - `_grbl_port_ready`, `_grbl_recovery_text`, `_grbl_reserve`, `_grbl_release`, `_grbl_start_op` (2222-2297)
   - `_grbl_active_locked`, `_grbl_failure_locked`, `_grbl_read_more_locked`, `_grbl_prepare_locked`, `_grbl_wait_idle`, `_grbl_write_realtime_locked`, `_grbl_transact`, `_grbl_query_status` (2299-2585)
   - `_grbl_confirm_reset` (2696-2740)
   - `_grbl_probe_run`, `_al_check_probe_reply`, `_grbl_hold_for_recovery`, `_grbl_retract`, `_grbl_handle_abort` (3267-3489)
   - `_connect_finish` is not in this list, because it calls `_grbl_set_ui_connected`. It goes to `Sender.py`.

   Do not delete anything from `ToolLevelling.py` in this ticket.
3. **`SenderUI.py`**: class `GrblSenderUI`. It has the same widget names as LevelUI, so the copied handlers work without changes. The skeleton:
```python
# (file header as in T02)

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt

from appGUI.GUIElements import (
    FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, FCJog, FCDoubleSpinner, FCSpinner,
    FCDetachableTab, FCZeroAxes, FCSliderWithDoubleSpinner, FCEntry, RotatedToolButton, FCProgressBar)
from appPlugins.Common.levelling_ui import build_probe_points_ui

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class GrblSenderUI:
    pluginName = _("GRBL Sender")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        # <- (a) tools_frame, tools_box, title_box, title label, self.level:
        #        copy LevelUI lines 3707-3736; the title tooltip is _("Send G-code to a GRBL controller.")
        # <- (b) the CNCJob combo: copy LevelUI lines 3738-3754;
        #        obj_combo_label text: _("CNCJob"); tooltip: _("The CNCJob object to send.")
        # <- (c) the "Show console" checkbox:
        #        self.console_cb = FCCheckBox(_("Show console"))
        #        self.console_cb.setToolTip(_("Show or hide the GRBL console dock."))
        #        self.tools_box.addWidget(self.console_cb)
        # <- (d) the GRBL toolbar with 3 tabs: copy LevelUI lines 4024-4330
        #        (al_toolbar, the Connect, Control and Sender tabs and their contents);
        #        change self.grbl_box.addWidget(self.al_toolbar) to self.tools_box.addWidget(self.al_toolbar)
        # <- (e) the run controls, see step 4
        # <- (f) the autolevel group:
        #        self.al_group_label = FCLabel('%s' % _("Autolevelling"), color='blue', bold=True)
        #        self.tools_box.addWidget(self.al_group_label)
        #        self.autolevel_cb = FCCheckBox(_("Level the G-code"))
        #        self.autolevel_cb.setToolTip(_("Apply the height map to the G-code before streaming."))
        #        self.tools_box.addWidget(self.autolevel_cb)
        #        build_probe_points_ui(self, self.app, self.tools_box)
        #        then copy the precision-probing widgets, LevelUI lines 3995-4019, with
        #        self.grbl_box replaced by self.al_box
        # <- (g) self.tools_box.addStretch(1) and the Reset button: copy LevelUI lines 4373-4381
        # <- (h) GLay.set_common_column_size([self.tool_grid, self.param_grid], 0)

    # <- copy LevelUI.confirmation_message and confirmation_message_int (4390-4405)
```
   - The Sender tab of (d) has the button `grbl_get_heightmap_button` with the text "Apply AutoLevelling". Change its text to `_("Probe")` and its tooltip to `_("Probe the points and make the height map.")`.
   - `FCProgressBar`: run `grep -n "class FCProgressBar" appGUI/GUIElements.py`. If the class does not exist, use `QtWidgets.QProgressBar` and remove `FCProgressBar` from the import.
4. Add the run controls (e) under the toolbar:
```python
        self.run_label = FCLabel('%s' % _("Job"), color='green', bold=True)
        self.tools_box.addWidget(self.run_label)
        run_frame = FCFrame()
        self.tools_box.addWidget(run_frame)
        run_grid = GLay(v_spacing=5, h_spacing=3)
        run_frame.setLayout(run_grid)

        self.start_button = FCButton(_("Start"), bold=True)
        self.start_button.setToolTip(_("Stream the G-code of the selected CNCJob to GRBL."))
        self.hold_button = FCButton(_("Hold"))
        self.hold_button.setToolTip(_("Feed hold. Resume continues the job."))
        self.resume_button = FCButton(_("Resume"))
        self.stop_button = FCButton(_("Stop"))
        self.stop_button.setStyleSheet("QPushButton {background-color: red; color: white;}")
        self.stop_button.setToolTip(_("Stop the job: feed hold, then a soft reset."))
        run_grid.addWidget(self.start_button, 0, 0)
        run_grid.addWidget(self.hold_button, 0, 1)
        run_grid.addWidget(self.resume_button, 0, 2)
        run_grid.addWidget(self.stop_button, 0, 3)

        self.unlock_button = FCButton(_("Unlock"))
        self.unlock_button.setToolTip(_("Send $X: clear the alarm lock."))
        self.check_mode_cb = FCCheckBox(_("Check mode"))
        self.check_mode_cb.setToolTip(_("Send $C: GRBL reads the G-code but does not move."))
        run_grid.addWidget(self.unlock_button, 1, 0, 1, 2)
        run_grid.addWidget(self.check_mode_cb, 1, 2, 1, 2)

        self.progress_bar = FCProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        run_grid.addWidget(self.progress_bar, 2, 0, 1, 4)
        self.status_label = FCLabel(_("Idle"))
        run_grid.addWidget(self.status_label, 3, 0, 1, 4)

        # overrides: name, real-time byte
        self.ov_label = FCLabel('%s' % _("Overrides"), bold=True)
        run_grid.addWidget(self.ov_label, 4, 0, 1, 4)
        self.ov_buttons = {}
        ov_rows = [
            (_("Feed"), [('-10', b'\x92'), ('-1', b'\x94'), ('100%', b'\x90'), ('+1', b'\x93'), ('+10', b'\x91')]),
            (_("Rapid"), [('25%', b'\x97'), ('50%', b'\x96'), ('100%', b'\x95')]),
            (_("Spindle"), [('-10', b'\x9b'), ('-1', b'\x9d'), ('100%', b'\x99'), ('+1', b'\x9c'), ('+10', b'\x9a')]),
        ]
        for row_idx, (name, items) in enumerate(ov_rows, start=5):
            run_grid.addWidget(FCLabel('%s:' % name), row_idx, 0)
            h_lay = QtWidgets.QHBoxLayout()
            for text, byte in items:
                btn = QtWidgets.QToolButton()
                btn.setText(text)
                h_lay.addWidget(btn)
                self.ov_buttons[(name, text)] = (btn, byte)
            run_grid.addLayout(h_lay, row_idx, 1, 1, 3)
        self.ov_values_label = FCLabel('F: 100%  R: 100%  S: 100%')
        run_grid.addWidget(self.ov_values_label, 8, 0, 1, 4)

        self.save_levelled_button = FCButton(_("Save levelled G-code"))
        self.save_levelled_button.setIcon(QtGui.QIcon(self.app.resource_location + '/save_as.png'))
        self.save_levelled_button.setToolTip(_("Save the G-code that the sender streams, after the levelling."))
        run_grid.addWidget(self.save_levelled_button, 9, 0, 1, 4)
```
   These are the GRBL 1.1 real-time override bytes: feed `0x90` 100%, `0x91` +10, `0x92` -10, `0x93` +1, `0x94` -1; rapid `0x95` 100%, `0x96` 50%, `0x97` 25%; spindle `0x99` 100%, `0x9A` +10, `0x9B` -10, `0x9C` +1, `0x9D` -1.

5. **`Sender.py`**: class `ToolGrblSender`. The skeleton:
```python
# (file header as in T02)

import sys
import math
from io import StringIO

from PyQt6 import QtWidgets, QtCore, QtGui

import serial
import serial.tools.list_ports

from appTool import AppTool
from defaults import AppDefaults
from appGUI.GUIElements import VerticalScrollArea, FCFileSaveDialog
from camlib import CNCjob

from appPlugins.Common.levelling_core import LevellingCoreMixin
from appPlugins.Common.grbl_protocol import (
    parse_grbl_status_state, parse_grbl_setting, parse_grbl_active_wcs, grbl_reply_error, probe_timeout_s)
from appPlugins.ToolGrblSender.SenderGrbl import GrblClientMixin, _GrblOperation, _GrblProbeAbort
from appPlugins.ToolGrblSender.SenderUI import GrblSenderUI

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ToolGrblSender(LevellingCoreMixin, GrblClientMixin, CNCjob, AppTool):
    grbl_port_closed_sig = QtCore.pyqtSignal()
    al_result_ready_sig = QtCore.pyqtSignal(object)
    build_al_table_sig = QtCore.pyqtSignal()
    apply_autolevel_sig = QtCore.pyqtSignal()
    show_probing_geo_sig = QtCore.pyqtSignal(bool, bool)
    # (done_lines, total_lines) from the stream worker
    stream_progress_sig = QtCore.pyqtSignal(int, int)
    # a parsed status report (dict) from a worker
    status_report_sig = QtCore.pyqtSignal(object)
    # 'finished', 'stopped' or 'error' from the stream worker
    stream_ended_sig = QtCore.pyqtSignal(str)

    def __init__(self, app):
        self.app = app
        self.decimals = self.app.decimals

        AppTool.__init__(self, app)
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        CNCjob.__init__(
            self,
            steps_per_circle=self.app.options.get(
                "cncjob_steps_per_circle",
                app_defaults.get("cncjob_steps_per_circle", AppDefaults.factory_defaults.get("cncjob_steps_per_circle"))),
            app=app
        )
        self._al_init_state()
        self._grbl_init_state()

        # the stream job: the lines that the sender streams, and the height-map
        # generation that they were levelled with (None: not levelled)
        self.job_lines = []
        self.job_map_generation = None
        self.job_target_name = None
        self.view3d = None

        self.ui = GrblSenderUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

        self._al_core_signals_connected = False
        self.connect_signals_at_init()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='', **kwargs)

    # <- run(): copy ToolLevelling.run (312-365). Change "ToolLevelling()" to "ToolGcodeSender()"
    #    and _("Levelling") to _("GRBL Sender"). At the end add: self.show_console_if_wanted()

    # <- connect_signals_at_init(): see step 6
    # <- set_tool_ui(): copy ToolLevelling.set_tool_ui (438-459), with LevelUI replaced by GcodeSenderUI
    # <- _populate_tool_ui(): see step 7
    # <- on_object_changed(): copy ToolLevelling.on_object_changed (599-630), with
    #    self._is_supported_al_target(target_obj) replaced by self._is_supported_target(target_obj)

    @staticmethod
    def _is_supported_target(target_obj):
        """The sender accepts every CNCJob; it segments the G-code itself."""
        return target_obj is not None and getattr(target_obj, 'kind', None) == 'cncjob'

    # the mixin methods on_mode_radio() and on_method_radio() call this name
    _is_supported_al_target = _is_supported_target

    # <- copy from ToolLevelling, unchanged (R2): on_grbl_search_ports, on_grbl_connect,
    #    _grbl_connect_finish, _grbl_set_ui_connected, _on_grbl_port_closed, on_grbl_add_baudrate,
    #    on_grbl_delete_baudrate_grbl, on_grbl_send_command, on_grbl_report, on_grbl_get_parameter,
    #    on_grbl_jog, on_grbl_zero, on_grbl_homing, on_grbl_stop, on_grbl_reset, on_grbl_pause_resume,
    #    _al_read_probe_inputs, on_grbl_autolevel, _al_read_precision_inputs,
    #    _restore_al_precision, _update_precision_probe_ui, on_precision_probe_changed
    #    In each copied method that has self._is_supported_al_target, change it to self._is_supported_target.

    def probing_gcode(self, storage):
        """The sender probes live, so it has no probing G-code file."""
        return ''

    # <- copy ui_connect, ui_disconnect from ToolLevelling (3679-3692)

    def reset_fields(self):
        self.al_heights_valid = False
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(3, 0, QtCore.QModelIndex()))

    # ------------------------------------------------------------------
    # LevellingCoreMixin hooks
    # ------------------------------------------------------------------
    def _al_set_buttons_enabled(self, enabled):
        self.ui.grbl_get_heightmap_button.setDisabled(not enabled)
        self.ui.grbl_save_height_map_button.setDisabled(not enabled)

    def _al_result_lock(self):
        return self._grbl_op_lock

    def _al_result_retired(self, result):
        op = result.get('operation')
        return (op is not None and op.cancel.is_set()) or (
                'safety_generation' in result and
                result['safety_generation'] != self._grbl_safety_generation)

    def _al_on_height_map_ready(self, target_obj):
        # the levelled job belongs to the old map; T16 makes it again before the next Start
        self.job_map_generation = None
        self.app.inform.emit('[success] %s' % _("The height map is ready."))

    # <- console methods: T08
```
   (Part 1, A3: do not copy `apply_autolevel_sig`.)
6. `connect_signals_at_init()` of the sender. Copy `ToolLevelling.connect_signals_at_init` (367-436). Then make these changes:
   - delete the lines of `self.ui.al_controller_combo` and `self.ui.view_h_gcode_button`/`h_gcode_button` (there are no such widgets in the sender);
   - keep the precision, GRBL, Jog, Zero and Sender lines;
   - in the block that runs 1 time (`if not getattr(self, '_al_core_signals_connected', False):`), also connect:
     ```python
             self.stream_progress_sig.connect(self._on_stream_progress)
             self.status_report_sig.connect(self._on_status_report)
             self.stream_ended_sig.connect(self._on_stream_ended)
     ```
   - at the end, add:
     ```python
         self.ui.console_cb.toggled.connect(self.on_console_toggled)
         self.ui.start_button.clicked.connect(self.on_start)
         self.ui.hold_button.clicked.connect(lambda: self._grbl_realtime(b'!'))
         self.ui.resume_button.clicked.connect(lambda: self._grbl_realtime(b'~'))
         self.ui.stop_button.clicked.connect(self.on_stream_stop)
         self.ui.unlock_button.clicked.connect(self.on_unlock)
         self.ui.check_mode_cb.toggled.connect(self.on_check_mode)
         self.ui.save_levelled_button.clicked.connect(self.on_save_levelled_gcode)
         for (name, text), (btn, byte) in self.ui.ov_buttons.items():
             btn.clicked.connect(lambda checked=False, b=byte: self._grbl_realtime(b))
     ```
     (Part 1, A5.4: the check-mode checkbox has no handler.)
   - Until T13 and T16 add them, add stub methods so the connections work:
     ```python
         def on_start(self):
             self.app.inform.emit('[WARNING_NOTCL] %s' % _("Not available yet."))
         on_stream_stop = on_unlock = on_save_levelled_gcode = on_start

         def on_check_mode(self, checked):
             self.on_start()

         def _grbl_realtime(self, data):
             with self._grbl_op_lock:
                 written = self._grbl_write_realtime_locked(data)
             if not written:
                 self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))

         def _on_stream_progress(self, done, total):
             pass

         def _on_status_report(self, report):
             pass

         def _on_stream_ended(self, how):
             pass
     ```
7. `_populate_tool_ui()` of the sender. Copy `ToolLevelling._populate_tool_ui` (461-579). Then make these changes:
   - In `self.form_fields.update({...})`, delete the line of `"tools_al_controller"`. Change `"tools_al_grbl_jog_step"` to `"tools_grbl_jog_step"` and `"tools_al_grbl_jog_fr"` to `"tools_grbl_jog_fr"`.
   - Delete the line `self.on_controller_change_alter_ui()`. At its place, add `self.on_grbl_search_ports(muted=True)`.
   - Replace `if self._is_supported_al_target(loaded_obj):` with `if self._is_supported_target(loaded_obj):`. In that branch, delete the line `self.on_controller_change()`.
   - At the end, add:
     ```python
         self.ui.console_cb.set_value(bool(self.app.options.get(
             "tools_grbl_console_visible",
             app_defaults.get("tools_grbl_console_visible", False))))
         self.ui.autolevel_cb.set_value(False)
         self._grbl_set_ui_connected(self._grbl_port_ready())
     ```
8. The sender `to_form()`. Copy `ToolLevelling.to_form` (795-807), and change the test `if option.startswith('tools_al_'):` to `if option.startswith('tools_al_') or option.startswith('tools_grbl_'):`.
9. Do not install the sender in the app in this ticket. Make sure that the module loads:
   `.venv/Scripts/python.exe -c "import appMain; from appPlugins.ToolGrblSender.Sender import ToolGrblSender; print('ok')"`
   It must print `ok`. Run the gate. (Part 1, A3 replaces this check with `tests/test_grbl_sender_construct.py`.)

Commit: `feat(grbl-sender): add the GRBL Sender plugin package`

### T08: Console dock, defaults and preferences

Files: `appGUI/MainGUI.py`, `appPlugins/ToolGrblSender/Sender.py`, `defaults.py`, new `appGUI/preferences/tools/ToolsGrblSenderPrefGroupUI.py`, `appGUI/preferences/tools/PluginsEngravingPreferencesUI.py`, `appGUI/preferences/PreferencesUIManager.py`.

1. **Defaults.** In `defaults.py`, after the line `"tools_al_grbl_travelz": 15.0,` (line 529), add:
```python
        # GRBL Sender Plugin
        "tools_grbl_jog_step": 5,
        "tools_grbl_jog_fr": 1500,
        "tools_grbl_travelz": 15.0,
        "tools_grbl_baudrate": '115200',
        "tools_grbl_console_visible": False,
        "tools_grbl_arc_mode": 'split',
        "tools_grbl_arc_segment": 0.5,
        "tools_grbl_seg_len": 1.0,
        "tools_grbl_status_ms": 200,
```
2. **Console dock.** In `appGUI/MainGUI.py`, after the shell dock block (after line 1504, `self.addDockWidget(... self.shell_dock)`), add:
```python
        # ####################### GRBL Console DOCK ##############################
        self.grbl_console_dock = FCDock(_("GRBL Console"), close_callback=self.on_grbl_console_closed)
        self.grbl_console_dock.setWindowIcon(QtGui.QIcon(self.app.resource_location + '/app24.png'))
        self.grbl_console_dock.setObjectName('GrblConsole_DockWidget')
        self.grbl_console_dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)
        self.grbl_console_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                           QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                                           QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.grbl_console_dock)
        self.grbl_console_dock.hide()
```
   Add this method after `toggle_shell_ui` (MainGUI.py:2975):
```python
    def on_grbl_console_closed(self):
        """The user closed the GRBL console dock with its own button."""
        self.grbl_console_dock.hide()
        try:
            self.app.options["tools_grbl_console_visible"] = False
            self.app.grbl_sender_tool.ui.console_cb.set_value(False)
        except AttributeError:
            pass
```
   - `restoreState` (MainGUI.py:2102) can show the dock again at start. Add this line after the `restoreState` line: `self.grbl_console_dock.hide()`
3. **Console widget.** In `Sender.py`, add this class above `class ToolGrblSender`:
```python
class GrblConsole(QtWidgets.QWidget):
    """The log of the lines sent to GRBL and of its replies, and a command line."""

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        lay.addWidget(self.log_view)
        h_lay = QtWidgets.QHBoxLayout()
        self.cmd_entry = QtWidgets.QLineEdit()
        self.cmd_entry.setPlaceholderText(_("Type GRBL command ..."))
        self.send_btn = QtWidgets.QToolButton()
        self.send_btn.setText(_("Send"))
        h_lay.addWidget(self.cmd_entry)
        h_lay.addWidget(self.send_btn)
        lay.addLayout(h_lay)
        self.cmd_entry.returnPressed.connect(self.on_send)
        self.send_btn.clicked.connect(self.on_send)

    def on_send(self):
        text = self.cmd_entry.text().strip()
        if not text:
            return
        self.cmd_entry.clear()
        self.tool.send_console_command(text)

    def append(self, text):
        self.log_view.appendPlainText(text)
```
4. In `ToolGrblSender`, add a signal and these methods:
```python
    # a text line for the console, from any thread
    console_line_sig = QtCore.pyqtSignal(str)

    def _console(self):
        """:return: the GrblConsole in the dock (made at the first call)."""
        dock = self.app.ui.grbl_console_dock
        if not isinstance(dock.widget(), GrblConsole):
            dock.setWidget(GrblConsole(self))
        return dock.widget()

    def on_console_toggled(self, checked):
        self.app.options["tools_grbl_console_visible"] = bool(checked)
        if checked:
            self._console()
            self.app.ui.grbl_console_dock.show()
        else:
            self.app.ui.grbl_console_dock.hide()

    def show_console_if_wanted(self):
        if self.app.options.get("tools_grbl_console_visible", False):
            self._console()
            self.app.ui.grbl_console_dock.show()

    def hide_console(self):
        self.app.ui.grbl_console_dock.hide()

    def send_console_command(self, text):
        self.ui.grbl_command_entry.set_value(text)
        self.on_grbl_send_command()

    def on_plugin_cleanup(self):
        """The Plugin tab closes: hide the console. The option keeps its value."""
        self.hide_console()

    def hideEvent(self, event):
        # another plugin took the Plugin tab, or the tab closed
        self.hide_console()
        super().hideEvent(event)
```
   - In the 1-time block of `connect_signals_at_init`, add `self.console_line_sig.connect(lambda line: self._console().append(line))`.
   - In `run()`, in the branch that removes the tab (`self.app.ui.notebook.removeTab(2)`), add `self.hide_console()` after that line.
5. **Send the TX and RX lines to the console.** In the copied methods of `Sender.py` and of `SenderGrbl.py`:
   - replace each `self.app.inform_shell[str, bool].emit(<x>, False)` with `self.console_line_sig.emit(<x>)`;
   - replace each `self.app.inform_shell.emit(<x>)` with `self.console_line_sig.emit(<x>)`;
   - in `Sender.py`, delete each `self.app.ui.shell_dock.show()` line.

   These are the only changes to the copied GRBL code in this ticket. The tests set `inform_shell` to a MagicMock, so T09 adds a MagicMock `console_line_sig` to the test factory.
6. **Preferences group.** Make `appGUI/preferences/tools/ToolsGrblSenderPrefGroupUI.py` in the pattern of `ToolsLevelPrefGroupUI.py`:
   - Use the same imports, plus `FCCheckBox`.
   - The class is `ToolsGrblSenderPrefGroupUI(OptionsGroupUI)`, and the title is `_("GRBL Sender Plugin")`.
   - Make these widgets, each with a label in column 0 and the widget in column 1 of `par_grid`:

     | Attribute | Widget | Label | Range / items |
     |---|---|---|---|
     | `jog_step_entry` | FCDoubleSpinner | Step | 0 - 910000 |
     | `jog_fr_entry` | FCDoubleSpinner | Feedrate | 0 - 910000 |
     | `jog_travelz_entry` | FCDoubleSpinner | Travel Z | 0 - 910000 |
     | `baudrate_combo` | FCComboBox | Baud rate | the 14 rates of LevelUI line 4102 |
     | `arc_mode_radio` | RadioSet | Arcs | `[{'label': _('Split'), 'value': 'split'}, {'label': _('Send'), 'value': 'send'}]` |
     | `arc_segment_entry` | FCDoubleSpinner | Arc segment | 0.001 - 100 |
     | `seg_len_entry` | FCDoubleSpinner | Segment length | 0.001 - 1000 |
     | `status_ms_entry` | FCSpinner | Status interval (ms) | 50 - 2000 |

   - The tooltip of `arc_mode_radio`: `_("Split: the sender splits G2/G3 arcs into G1 lines.\nSend: the sender sends G2/G3 to GRBL.\nWith autolevelling on, arcs are always split.")`
   - The tooltip of `seg_len_entry`: `_("Longest G1 line when the G-code is not segmented.\nUsed only with autolevelling.")`
7. In `PluginsEngravingPreferencesUI.py`:
   - import the class;
   - after `self.tools_level_group = ...`, add `self.tools_grbl_group = ToolsGrblSenderPrefGroupUI(app=app)` and `self.tools_grbl_group.setMinimumWidth(250)`;
   - after `self.vlay3.addWidget(self.tools_level_group)`, add `self.vlay3.addWidget(self.tools_grbl_group)`.
8. In `PreferencesUIManager.py`, after line 416 (`"tools_al_grbl_travelz": ...`), add:
```python
            # GRBL Sender Plugin
            "tools_grbl_jog_step":       self.ui.plugin_eng_pref_form.tools_grbl_group.jog_step_entry,
            "tools_grbl_jog_fr":         self.ui.plugin_eng_pref_form.tools_grbl_group.jog_fr_entry,
            "tools_grbl_travelz":        self.ui.plugin_eng_pref_form.tools_grbl_group.jog_travelz_entry,
            "tools_grbl_baudrate":       self.ui.plugin_eng_pref_form.tools_grbl_group.baudrate_combo,
            "tools_grbl_arc_mode":       self.ui.plugin_eng_pref_form.tools_grbl_group.arc_mode_radio,
            "tools_grbl_arc_segment":    self.ui.plugin_eng_pref_form.tools_grbl_group.arc_segment_entry,
            "tools_grbl_seg_len":        self.ui.plugin_eng_pref_form.tools_grbl_group.seg_len_entry,
            "tools_grbl_status_ms":      self.ui.plugin_eng_pref_form.tools_grbl_group.status_ms_entry,
```
9. In the copied `on_grbl_jog` (Sender.py), change the key `"tools_al_grbl_travelz"` to `"tools_grbl_travelz"` (3 times on 1 statement).
10. Run the gate. Run `.venv/Scripts/python.exe -m pytest tests/test_defaults*.py -q -p no:cacheprovider` too, because those tests can check the keys of `defaults.py`. If a defaults test fails because of the new keys, read the test. If it lists the keys of each group, add the new keys to its list. Otherwise stop (R5). (Part 1, A0: run it as `run_gate.py --targeted "tests/test_defaults*.py"`.)

Commit: `feat(grbl-sender): add the GRBL console dock and the preferences`

### T09: Install the sender in the app, and add the CNCJob button

Files: `appPlugins/__init__.py`, `appMain.py`, `appGUI/ObjectUI.py`, `appObjects/CNCJobObject.py`, `appHandlers/appUIActions.py`.

1. In `appPlugins/__init__.py`, after `from appPlugins.ToolLevelling import ToolLevelling`, add `from appPlugins.ToolGrblSender.Sender import ToolGrblSender`.
2. In `appMain.py`:
   - after line 507 `self.levelling_tool = None`, add `self.grbl_sender_tool = None`;
   - after the 3 lines of `self.levelling_tool = ToolLevelling(self)` ... (1830-1832), add:
     ```python
             self.grbl_sender_tool = ToolGrblSender(self)
             self.grbl_sender_tool.install(icon=QtGui.QIcon(self.resource_location + '/level32.png'),
                                           pos=self.ui.menu_plugins, before=self.sub_tool.menuAction, separator=True)
     ```
   - in the list `self.app_plugins`, after `self.levelling_tool,`, add `self.grbl_sender_tool,`;
   - make sure that `ToolGrblSender` is imported where `ToolLevelling` is imported in `appMain.py`. Run `grep -n "ToolLevelling" appMain.py` to find the import line, and add the name in the same way.
3. In `appGUI/ObjectUI.py`, after line 1427 (`self.custom_box.addWidget(self.autolevel_button)`), add:
```python
        # GRBL Sender - streams the G-code to a GRBL controller, with optional autolevelling
        self.grbl_sender_button = FCButton(_('GRBL Sender'), bold=True)
        self.grbl_sender_button.setIcon(QtGui.QIcon(self.app.resource_location + '/level32.png'))
        self.grbl_sender_button.setToolTip(
            _("Send the CNC Code to a GRBL controller.")
        )
        self.custom_box.addWidget(self.grbl_sender_button)
```
4. In `appObjects/CNCJobObject.py`, after line 574 (`self.ui.autolevel_button.clicked.connect(...)`), add:
   `self.ui.grbl_sender_button.clicked.connect(lambda: self.app.grbl_sender_tool.run(toggle=True))`
5. No toolbar button. Commit `e6f5eb27` removed the Levelling button from the Plugins toolbar, so the GRBL Sender has no toolbar button either. The user opens it from the Plugins menu or from the CNCJob UI.
6. In `appHandlers/appUIActions.py`, find the `try` block that runs `self.app.levelling_tool.probing_shapes.clear(update=True)` (line 1153; there is also a commented copy at line 1128, do not use it). After that block, add the same block for `self.app.grbl_sender_tool.probing_shapes`.
7. Run the gate. Also run `.venv/Scripts/python.exe -m pytest tests/test_appmain*.py tests/test_app_refactor*.py -q -p no:cacheprovider`. If a test counts `app_plugins` or the menu actions, and fails only because of the new plugin, change the expected number by 1. Otherwise stop (R5). (Part 1, A0: run it with `run_gate.py --targeted`.)

Commit: `feat(grbl-sender): install the plugin and add the GRBL Sender button to the CNCJob UI`

### T10: Remove GRBL from the Levelling tool, and move the GRBL tests to the sender

Files: `appPlugins/ToolLevelling.py`, `appGUI/preferences/tools/ToolsLevelPrefGroupUI.py`, `appGUI/preferences/PreferencesUIManager.py`, `appObjects/CNCJobObject.py`, `defaults.py`, 11 test files.

1. **In `ToolLevelling.py`, delete:**
   - `class _GrblProbeAbort`, `class _GrblOperation`, `import serial`, `import serial.tools.list_ports`, `import threading` (if pyflakes then says that it is unused), `import time` (the same rule);
   - the signal `grbl_port_closed_sig`;
   - in `__init__`, the GRBL lines (the line numbers of T04 step 3: 220-221, 231-246, 288; after T04 they moved, so find them by their text: `self.grbl_probe_result`, `self.grbl_work_offset`, the block from `# serial session` to `self._grbl_reset_pending = False`, and `self.grbl_ser_port = None`);
   - in `connect_signals_at_init`:
     - the lines `self.grbl_port_closed_sig.connect(...)`, `self.app.cleanup.connect(self._grbl_disconnect)` and the 3 lines of `qt_app ... aboutToQuit.connect(self._grbl_force_close)`;
     - the lines of `precision_probe_cb`, `precision_feed_entry` and `precision_retract_entry`;
     - all lines from `# GRBL` to the line before `self.ui.view_h_gcode_button.clicked.connect`;
     - the lines of `pause_resume_button`, `grbl_get_heightmap_button`, `stop_probing_button` and `grbl_save_height_map_button`;
   - in `_populate_tool_ui`:
     - the 2 `form_fields` lines of `tools_al_grbl_jog_step` and `tools_al_grbl_jog_fr`;
     - the line `self._restore_al_precision(loaded_obj)`;
   - in `on_object_changed`, the line `self._restore_al_precision(target_obj)`;
   - all the methods that T07 copied to the sender: every `on_grbl_*` method and every `_grbl_*` method, plus `_al_read_probe_inputs`, `_al_read_precision_inputs`, `_al_check_probe_reply`, `_restore_al_precision`, `_update_precision_probe_ui` and `on_precision_probe_changed`;
   - `on_grbl_heightmap_save` now comes from the mixin, so ToolLevelling has no own copy.
2. **In `ToolLevelling.py`, change:**
   - `on_controller_change_alter_ui` becomes:
     ```python
         def on_controller_change_alter_ui(self):
             self.ui.h_gcode_button.show()
             self.ui.view_h_gcode_button.show()
             self.ui.import_heights_button.show()
     ```
   - in `probing_gcode`, delete the 3 lines of `elif controller == 'GRBL':`;
   - the hooks at the end of the class become:
     ```python
         def _al_set_buttons_enabled(self, enabled):
             self.ui.h_gcode_button.setDisabled(not enabled)
             self.ui.view_h_gcode_button.setDisabled(not enabled)

         def _al_on_height_map_ready(self, target_obj):
             self.apply_autolevel(target_obj=target_obj)
     ```
     Delete the overrides `_al_result_lock` and `_al_result_retired`, so ToolLevelling uses the defaults of the mixin.
   - In `LevelUI`:
     - change `self.al_controller_combo.addItems(["MACH3", "MACH4", "LinuxCNC", "GRBL"])` to `self.al_controller_combo.addItems(["MACH3", "MACH4", "LinuxCNC"])`;
     - delete the block from the comment line `# ########################## GRBL frame ####...` to the line `self.grbl_frame.hide()` and the comment line after it. Before T06 this was lines 3984-4333. Find the block by its text, because T06 moved it.
3. **Migration of the old `GRBL` value.** In `ToolLevelling._populate_tool_ui`, before `self.to_form()`, add:
```python
        if self.app.options.get("tools_al_controller") == 'GRBL':
            self.app.options["tools_al_controller"] = 'MACH3'
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                "The Levelling Plugin no longer has GRBL. Use the GRBL Sender Plugin."))
```
   In `ToolsLevelPrefGroupUI.py`:
   - change the `al_controller_combo` items to `["MACH3", "MACH4", "LinuxCNC"]`;
   - delete the widgets `jog_step_*`, `jog_fr_*` and `jog_travelz_*` (from `# JOG Step` to before `self.layout.addStretch(1)`).

   In `PreferencesUIManager.py`, delete the 3 lines `"tools_al_grbl_jog_step"`, `"tools_al_grbl_jog_fr"` and `"tools_al_grbl_travelz"`.

   In `appObjects/CNCJobObject.py:114-115`, delete the 2 lines `"tools_al_grbl_jog_step"` and `"tools_al_grbl_jog_fr"`.

   In `defaults.py`, delete the 3 keys `tools_al_grbl_jog_step`, `tools_al_grbl_jog_fr` and `tools_al_grbl_travelz`.

   Run `grep -rn "tools_al_grbl_" --include=*.py . | grep -v .worktrees | grep -v "^./tests"`. The result must be empty.
4. **Move the GRBL tests to the sender.** The test files keep their names (gate ids). Only the factories and the patch targets change.
   - In `tests/test_levelling_audit.py`:
     - add `from appPlugins.ToolGrblSender.Sender import ToolGrblSender` and `import appPlugins.ToolGrblSender.SenderGrbl as sg_module`;
     - change the factory to `def make_audit_tool(units='MM', storage=None, heights_valid=False, cls=None):`, and its first line to:
       `tool = (cls or ToolGrblSender).__new__(cls or ToolGrblSender)`
     - add these 3 lines to the factory: `tool.console_line_sig = MagicMock()`, `tool.job_map_generation = None` and `tool.view3d = None`.
   - In `tests/test_levelling_tool.py`: change `make_tool` in the same way, but keep `ToolLevelling` as the default class: `def make_tool(units='MM', storage=None, heights_valid=True, cls=None):` and `tool = (cls or ToolLevelling).__new__(cls or ToolLevelling)`. Add the same 3 lines.
   - **Patch targets:**

     | Old target | New target |
     |---|---|
     | `appPlugins.ToolLevelling.serial.*` | `appPlugins.ToolGrblSender.SenderGrbl.serial.*` |
     | `appPlugins.ToolLevelling.time.sleep`, `.time.monotonic` | `appPlugins.ToolGrblSender.SenderGrbl.time.sleep`, `.time.monotonic` |
     | `appPlugins.ToolLevelling.QtCore.QTimer.singleShot` | `appPlugins.ToolGrblSender.Sender.QtCore.QTimer.singleShot` |
     | `appPlugins.ToolLevelling.probe_timeout_s` | `appPlugins.ToolGrblSender.Sender.probe_timeout_s` |
     | `tl_module.serial` | `sg_module.serial` |
     | `tl_module.QtCore.QTimer` | `appPlugins.ToolGrblSender.Sender.QtCore.QTimer`, as a string patch |
     | `appPlugins.ToolLevelling.LevelUI` (only in a test that uses a sender) | `appPlugins.ToolGrblSender.Sender.GrblSenderUI` |

   - **The fix loop.** Run the gate. For each failing test, use the first rule that matches:
     - **(a)** `AttributeError` on a ToolLevelling-only name (`probing_gcode` text checks, `apply_autolevel`, `on_controller_change`, `on_controller_change_alter_ui`, `on_save_probing_gcode`, `on_edit_probing_gcode`, `al_controller_combo`, `_is_supported_al_target`): in that test, change the factory call to pass `cls=ToolLevelling`.
     - **(b)** `AttributeError` on a GRBL name (`_grbl_*`, `on_grbl_*`, `grbl_ser_port`, `_al_read_precision_inputs`, `_restore_al_precision`, `on_precision_probe_changed`, `console_line_sig`) in a test that uses `make_tool`: in that test, pass `cls=ToolGrblSender`. Import the class at the top of the file.
     - **(c)** The test checks that a probe or an import makes a `_levelled` object (it checks `apply_autolevel`, `app_obj.new_object`, or `outname`) and the tool is a `ToolGrblSender`: pass `cls=ToolLevelling` if the test does not use the port. If the test uses the port (`FakeGrbl`, `grbl_ser_port`), change the check to `tool._al_on_height_map_ready` and patch that method with a MagicMock before the action. Example: `tool._al_on_height_map_ready = MagicMock()` ... `tool._al_on_height_map_ready.assert_called_once_with(target)`.
     - **(d)** The test checks that `inform_shell` got a line: change `tool.app.inform_shell` to `tool.console_line_sig` in that check. The argument is the text only (no `False`).
     - **(e)** The test checks that the GRBL option, the GRBL frame or the GRBL jog keys exist in the Levelling tool (`'GRBL'` in the controller combo, `grbl_frame.show()`, `tools_al_grbl_*`): delete the test. Add its id to the list for the commit message.
     - **(f)** Any other failure: stop and report (R5).

     The other GRBL test files use the helpers of `test_levelling_audit.py`, so most of them need only the patch targets. These files are `test_levelling_safety_regressions.py`, `test_levelling_connection_regressions.py`, `test_levelling_e2e.py`, `test_levelling_precision.py`, `test_levelling_result_regressions.py`, `test_levelling_controller_regressions.py` and `test_levelling_lifecycle_regressions.py`. `test_levelling_journey.py` and `test_levelling_apply_regressions.py` use `make_tool`.
5. The gate must pass. Run `check_gate.py`. If tests were deleted by rule (e), run `--update`, and list each deleted id with the reason "the Levelling Plugin no longer has GRBL" in the commit message. (Part 1, A0: also add each deleted id to `tests/gates/removed_tests.txt`.)

Commit: `refactor(levelling): remove GRBL from the Levelling Plugin; the GRBL tests now test the GRBL Sender`

---

## Phase D: Streaming

### T11: Add the status-report parser

Files: `appPlugins/Common/grbl_protocol.py`, new `tests/test_grbl_protocol.py`.

1. Add to `grbl_protocol.py`:
```python
def parse_grbl_status_report(line):
    """
    Parse a GRBL 1.1 status report, for example
    '<Run|MPos:1.000,2.000,-0.500|FS:500,10000|Ov:100,100,100|WCO:0.000,0.000,0.000>'.

    :param line: 1 line of text.
    :return: dict with 'state' (str), and if they are in the report: 'mpos' and
        'wpos' (tuples of 3 floats), 'wco' (tuple of 3 floats), 'feed' and
        'spindle' (floats), 'ov' (tuple of 3 ints: feed, rapid, spindle),
        'buffer' (tuple of 2 ints: planner blocks, RX bytes available),
        'line' (int); None if `line` is not a status report.
    """
    text = (line or '').strip()
    if not (text.startswith('<') and text.endswith('>')):
        return None
    fields = text[1:-1].split('|')
    if not fields or not fields[0]:
        return None
    report = {'state': fields[0].split(':')[0]}

    def floats(value, count):
        parts = value.split(',')
        if len(parts) != count:
            raise ValueError(value)
        result = tuple(float(p) for p in parts)
        if not all(math.isfinite(v) for v in result):
            raise ValueError(value)
        return result

    try:
        for field in fields[1:]:
            key, _sep, value = field.partition(':')
            if key == 'MPos':
                report['mpos'] = floats(value, 3)
            elif key == 'WPos':
                report['wpos'] = floats(value, 3)
            elif key == 'WCO':
                report['wco'] = floats(value, 3)
            elif key == 'FS':
                report['feed'], report['spindle'] = floats(value, 2)
            elif key == 'F':
                report['feed'] = floats(value, 1)[0]
            elif key == 'Ov':
                report['ov'] = tuple(int(v) for v in floats(value, 3))
            elif key == 'Bf':
                report['buffer'] = tuple(int(v) for v in floats(value, 2))
            elif key == 'Ln':
                report['line'] = int(value)
    except ValueError:
        return None
    return report


def work_position(report, last_wco=None):
    """
    :param report:   a dict from parse_grbl_status_report().
    :param last_wco: the last WCO seen (GRBL sends WCO only in some reports).
    :return: (x, y, z) work position, or None if it can not be computed.
    """
    if report is None:
        return None
    if 'wpos' in report:
        return report['wpos']
    wco = report.get('wco', last_wco)
    if 'mpos' in report and wco is not None:
        return tuple(m - o for m, o in zip(report['mpos'], wco))
    return None
```
2. Make `tests/test_grbl_protocol.py` with these tests (use the header of `tests/test_grbl_bicubic.py`):
   - `test_run_mpos_fs_ov`: the example line of the docstring gives state `'Run'`, `mpos == (1.0, 2.0, -0.5)`, `feed == 500.0`, `spindle == 10000.0` and `ov == (100, 100, 100)`.
   - `test_idle_wpos`: `'<Idle|WPos:0.000,0.000,0.000|FS:0,0>'` gives state `'Idle'` and `wpos == (0.0, 0.0, 0.0)`.
   - `test_hold_substate`: `'<Hold:0|MPos:0,0,0>'` gives state `'Hold'`.
   - `test_not_a_report`: `'ok'`, `''`, `None` and `'<Idle|MPos:1,2>'` give `None`.
   - `test_work_position_from_wco`: report `{'mpos': (10.0, 10.0, 0.0)}` with `last_wco=(1.0, 2.0, 3.0)` gives `(9.0, 8.0, -3.0)`.
   - `test_work_position_unknown`: `work_position({'mpos': (1, 2, 3)})` gives `None`.
3. Run the gate. Run `check_gate.py --update`.

Commit: `feat(grbl-sender): parse the GRBL status report`

### T12: Character-counting streamer

(Part 1, A4 replaces the signature and the rules of `stream_lines`, and adds tests. The code below is the original version.)

Files: `appPlugins/ToolGrblSender/SenderGrbl.py`, new `tests/test_grbl_stream.py`.

1. Add to `SenderGrbl.py`, at module level:
```python
# the size of the GRBL serial receive buffer (GRBL 1.1 on an ATmega328P)
GRBL_RX_BUFFER = 127


def stream_lines(port, lines, rx_size=GRBL_RX_BUFFER, check_mode=False, on_progress=None,
                 on_line=None, should_stop=None, poll_status=None, poll_interval=0.2,
                 on_status=None, clock=time.monotonic, idle_timeout=30.0):
    """
    Send `lines` to GRBL with the character-counting protocol: a new line
    is written only while the bytes of the lines in flight (each line + '\\n')
    fit in the GRBL receive buffer. Each 'ok' or 'error:N' frees the oldest
    line. Runs in a worker thread; it reads no widgets.

    :param port:         an open serial port (or a fake with write/readline).
    :param lines:        list of str, no line ends, no empty lines.
    :param rx_size:      the receive buffer size of GRBL.
    :param check_mode:   True in $C mode: an error does not stop the stream, it is counted.
    :param on_progress:  callable(done, total), after each acknowledged line.
    :param on_line:      callable(text), for each line written and each reply read.
    :param should_stop:  callable() -> bool; True stops the stream (no more writes).
    :param poll_status:  True to send '?' every poll_interval s.
    :param on_status:    callable(text), for each status report line.
    :param idle_timeout: seconds without any reply while lines are in flight -> 'timeout'.
    :return: dict: 'status' ('finished', 'stopped', 'error', 'alarm', 'timeout' or
        'port_error'), 'done' (acknowledged lines), 'errors' (list of
        (line index, reply text)), 'last_text' (the last reply line).
    """
    total = len(lines)
    in_flight = []          # (line index, byte count) of the lines written but not acknowledged
    used = 0
    sent = 0
    done = 0
    errors = []
    buf = b''
    last_text = ''
    last_reply = clock()
    next_poll = clock()

    def result(status):
        return {'status': status, 'done': done, 'errors': errors, 'last_text': last_text}

    while done < total:
        if should_stop is not None and should_stop():
            return result('stopped')

        # write while the next line fits
        while sent < total:
            data = (lines[sent] + '\n').encode('utf-8')
            if used + len(data) > rx_size and in_flight:
                break
            try:
                port.write(data)
            except (serial.SerialException, OSError):
                return result('port_error')
            in_flight.append((sent, len(data)))
            used += len(data)
            if on_line is not None:
                on_line(lines[sent])
            sent += 1

        if poll_status and clock() >= next_poll:
            try:
                port.write(b'?')
            except (serial.SerialException, OSError):
                return result('port_error')
            next_poll = clock() + poll_interval

        try:
            chunk = port.readline()
        except (serial.SerialException, OSError):
            return result('port_error')
        if not chunk:
            if in_flight and clock() - last_reply > idle_timeout:
                return result('timeout')
            continue
        buf += chunk
        while b'\n' in buf:
            raw, buf = buf.split(b'\n', 1)
            text = raw.decode('utf-8', errors='replace').strip()
            if not text:
                continue
            last_reply = clock()
            if text.startswith('<'):
                if on_status is not None:
                    on_status(text)
                continue
            last_text = text
            if on_line is not None:
                on_line(text)
            lowered = text.lower()
            if lowered.startswith('alarm:'):
                return result('alarm')
            if lowered == 'ok' or lowered.startswith('error:'):
                if not in_flight:
                    continue
                index, size = in_flight.pop(0)
                used -= size
                done += 1
                if lowered.startswith('error:'):
                    errors.append((index, text))
                    if not check_mode:
                        return result('error')
                if on_progress is not None:
                    on_progress(done, total)
    return result('finished')
```
2. Make `tests/test_grbl_stream.py`. It needs a fake port that answers like GRBL. It has a receive buffer and acknowledges only the lines that GRBL "ran":
```python
#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.ToolGrblSender.SenderGrbl import stream_lines


class FakeStreamPort:
    """Each written line gets 'ok' after 1 readline(); the receive buffer must never overflow."""

    def __init__(self, rx_size=127, errors=None, alarm_at=None):
        self.rx_size = rx_size
        self.pending = []           # byte counts in the GRBL buffer
        self.replies = []
        self.written = []
        self.max_used = 0
        self.errors = errors or {}  # line index -> 'error:N'
        self.alarm_at = alarm_at
        self.count = 0
        self.status_sent = False

    def write(self, data):
        if data == b'?':
            # answer the first '?' only; more answers would keep readline() busy for ever
            if not self.status_sent:
                self.status_sent = True
                self.replies.append(b'<Run|MPos:0.000,0.000,0.000|FS:0,0>\r\n')
            return
        self.written.append(data)
        self.pending.append(len(data))
        used = sum(self.pending)
        self.max_used = max(self.max_used, used)
        assert used <= self.rx_size, "GRBL receive buffer overflow"

    def readline(self):
        if self.replies:
            return self.replies.pop(0)
        if not self.pending:
            return b''
        self.pending.pop(0)
        index = self.count
        self.count += 1
        if self.alarm_at == index:
            return b'ALARM:1\r\n'
        return (self.errors.get(index, 'ok') + '\r\n').encode()


class TestStream(unittest.TestCase):
    def test_all_lines_sent_in_order(self):
        lines = ['G1 X%d Y%d F100' % (i, i) for i in range(200)]
        port = FakeStreamPort()
        res = stream_lines(port, lines)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(res['done'], 200)
        self.assertEqual([d.decode().strip() for d in port.written], lines)

    def test_buffer_never_overflows_and_is_used(self):
        lines = ['G1 X%d.123456 Y%d.654321 F1000' % (i, i) for i in range(100)]
        port = FakeStreamPort()
        stream_lines(port, lines)
        self.assertLessEqual(port.max_used, 127)
        self.assertGreater(port.max_used, 60)

    def test_error_stops(self):
        port = FakeStreamPort(errors={5: 'error:20'})
        res = stream_lines(port, ['G1 X%d' % i for i in range(20)])
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['errors'], [(5, 'error:20')])

    def test_check_mode_counts_errors(self):
        port = FakeStreamPort(errors={2: 'error:20', 7: 'error:33'})
        res = stream_lines(port, ['G1 X%d' % i for i in range(10)], check_mode=True)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual([e[0] for e in res['errors']], [2, 7])

    def test_alarm_stops(self):
        port = FakeStreamPort(alarm_at=3)
        res = stream_lines(port, ['G1 X%d' % i for i in range(10)])
        self.assertEqual(res['status'], 'alarm')

    def test_stop_request(self):
        calls = {'n': 0}

        def should_stop():
            calls['n'] += 1
            return calls['n'] > 3

        res = stream_lines(FakeStreamPort(), ['G1 X%d' % i for i in range(500)], should_stop=should_stop)
        self.assertEqual(res['status'], 'stopped')

    def test_progress_and_status(self):
        progress, status = [], []
        stream_lines(FakeStreamPort(), ['G1 X1', 'G1 X2'], on_progress=lambda d, t: progress.append((d, t)),
                     poll_status=True, poll_interval=0.0, on_status=status.append)
        self.assertEqual(progress[-1], (2, 2))
        self.assertTrue(status)

    def test_timeout(self):
        class Silent(FakeStreamPort):
            def readline(self):
                return b''
        ticks = iter(range(0, 1000, 10))
        res = stream_lines(Silent(), ['G1 X1'], clock=lambda: next(ticks), idle_timeout=30.0)
        self.assertEqual(res['status'], 'timeout')


if __name__ == '__main__':
    unittest.main()
```
3. Run the gate. Run `check_gate.py --update`.

Commit: `feat(grbl-sender): add the character-counting streamer`

### T13: Run control in the sender (stream without levelling)

(Part 1, A5 changes this ticket: write and read callables, stream epoch, abort, completion, check mode for 1 job, job rebuild. The code below is the original version.)

Files: `appPlugins/ToolGrblSender/Sender.py`, new `appPlugins/ToolGrblSender/SenderGen.py`.

1. Make `SenderGen.py` (pure functions; T16 adds the levelling):
```python
# (file header as in T02)
"""Job preparation of the GRBL Sender: the lines that are streamed."""

import re

_COMMENT_PAREN_RE = re.compile(r'\([^)]*\)')


def clean_lines(text):
    """
    Make the stream lines out of G-code text: remove the comments ('(...)' and
    ';...'), the '%' lines and the empty lines; strip the spaces.

    :param text: G-code text.
    :return: list of str.
    """
    result = []
    for raw in (text or '').splitlines():
        line = _COMMENT_PAREN_RE.sub('', raw)
        line = line.split(';', 1)[0].strip()
        if not line or line == '%':
            continue
        result.append(line)
    return result
```
2. In `Sender.py`, delete the stubs of T07 step 6 (`on_start`, `on_stream_stop`, `on_unlock`, `on_check_mode`, `on_save_levelled_gcode`, `_on_stream_progress`, `_on_status_report`, `_on_stream_ended`). Add these methods. `_grbl_realtime` stays.
```python
    def _target(self):
        return self.app.collection.get_by_name(self.ui.object_combo.get_value())

    def build_job(self):
        """
        Make self.job_lines from the selected CNCJob.

        :return: True if the job has lines.
        """
        target = self._target()
        if not self._is_supported_target(target):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a CNCJob object."))
            return False
        text = getattr(target, 'source_file', '') or ''
        if not text.strip():
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The CNCJob has no G-code. Use Update in the CNCJob UI."))
            return False
        self.job_lines = SenderGen.clean_lines(text)
        self.job_target_name = target.obj_options['name']
        self.job_map_generation = None
        return bool(self.job_lines)

    def on_start(self):
        if not self.build_job():
            return
        op = self._grbl_reserve('stream', motion=True)
        if op is None:
            return
        lines = list(self.job_lines)
        check_mode = self.ui.check_mode_cb.get_value() is True
        poll_ms = int(self.app.options.get("tools_grbl_status_ms", 200))
        self._stream_stop = False

        def worker_task():
            how = 'error'
            try:
                with self._grbl_op_lock:
                    port = self.grbl_ser_port
                    text, status = self._grbl_prepare_locked(op, port)
                    if status is not None:
                        return
                res = stream_lines(
                    port, lines, check_mode=check_mode,
                    on_progress=lambda d, t: self.stream_progress_sig.emit(d, t),
                    on_line=self.console_line_sig.emit,
                    should_stop=lambda: self._stream_stop or op.cancel.is_set(),
                    poll_status=True, poll_interval=poll_ms / 1000.0,
                    on_status=lambda line: self.status_report_sig.emit(parse_grbl_status_report(line)))
                how = res['status']
                if how == 'finished' and res['errors']:
                    self.app.inform.emit('[WARNING_NOTCL] %s: %s' % (
                        _("Check mode found errors on the lines"),
                        ', '.join(str(i + 1) for i, _t in res['errors'][:20])))
                elif how in ('error', 'alarm'):
                    with self._grbl_op_lock:
                        self._grbl_failure_locked(op, 'error', res['last_text'])
                    self.app.inform.emit('[ERROR_NOTCL] %s %d: %s' % (
                        _("GRBL stopped the job at line"), res['done'] + 1, res['last_text']))
                elif how in ('timeout', 'port_error'):
                    with self._grbl_op_lock:
                        self._grbl_failure_locked(op, how)
                if how == 'finished':
                    self._grbl_wait_idle(op)
            except (serial.SerialException, OSError) as err:
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                self.app.log.error("ToolGrblSender.on_start() -> %s" % str(err))
                how = 'port_error'
            finally:
                self._grbl_release(op)
                self.stream_ended_sig.emit(how)

        self.ui.start_button.setDisabled(True)
        self.app.inform.emit('%s: %d' % (_("Streaming lines"), len(lines)))
        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def on_stream_stop(self):
        """Stop: feed hold now; the worker stops writing. Then GRBL needs Reset and Home."""
        self._stream_stop = True
        self.on_grbl_stop()

    def on_unlock(self):
        def task(op):
            text, status = self._grbl_transact(op, '$X', timeout=5.0)
            if status != 'ok':
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Unlock failed"), text or status))
        self._grbl_start_op('unlock', task)

    def on_check_mode(self, checked):
        # $C toggles the check mode of GRBL; GRBL answers with a [MSG:Enabled] or [MSG:Disabled] line
        def task(op):
            text, status = self._grbl_transact(op, '$C', timeout=5.0)
            if status != 'ok':
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Check mode failed"), text or status))
        self._grbl_start_op('check', task)

    def _on_stream_progress(self, done, total):
        self.ui.progress_bar.setValue(int(done * 100 / total) if total else 0)

    def _on_status_report(self, report):
        if report is None:
            return
        if 'wco' in report:
            self._last_wco = report['wco']
        pos = work_position(report, getattr(self, '_last_wco', None))
        text = report['state']
        if pos is not None:
            text += '   X %.3f  Y %.3f  Z %.3f' % pos
        self.ui.status_label.setText(text)
        if 'ov' in report:
            self.ui.ov_values_label.setText('F: %d%%  R: %d%%  S: %d%%' % report['ov'])
        if self.view3d is not None and pos is not None:
            self.view3d.set_tool_position(pos)

    def _on_stream_ended(self, how):
        self.ui.start_button.setDisabled(False)
        if how == 'finished':
            self.ui.progress_bar.setValue(100)
            self.app.inform.emit('[success] %s' % _("The job finished."))
        elif how == 'stopped':
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("The job was stopped."))

    def on_save_levelled_gcode(self):
        if not self.job_lines and not self.build_job():
            return
        # <- T16 replaces build_job() with build_levelled_job() when autolevelling is on
        _filter_ = "G-Code Files (*.nc *.gcode *.cnc *.tap);;All Files (*.*)"
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Save levelled G-code"),
                directory=self.app.get_last_save_folder() + '/' + str(self.job_target_name) + '_levelled',
                ext_filter=_filter_)
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(caption=_("Save levelled G-code"), ext_filter=_filter_)
        if not filename:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Export cancelled ..."))
            return
        try:
            with open(filename, 'w') as f:
                f.write('\n'.join(self.job_lines) + '\n')
        except (FileNotFoundError, PermissionError) as err:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not save the file"), str(err)))
            return
        self.app.inform.emit('[success] %s: %s' % (_("Saved"), filename))
```
   Add these imports to `Sender.py`:
   - `from appPlugins.ToolGrblSender import SenderGen`
   - `from appPlugins.ToolGrblSender.SenderGrbl import stream_lines`
   - `from appPlugins.Common.grbl_protocol import parse_grbl_status_report, work_position`

   In `__init__`, add `self._stream_stop = False` and `self._last_wco = None`.
3. Make `tests/test_grbl_sender_gen.py` with 1 class `TestCleanLines`:
   - `test_removes_comments`: `clean_lines('G1 X1 (cut)\n; note\nG0 Z5 ;up\n%\n\n')` gives `['G1 X1', 'G0 Z5']`.
   - `test_keeps_order`: 3 lines in, the same 3 lines out.
4. Run the gate. Run `check_gate.py --update`.
5. **Manual check** (the user does this, or the agent if a GRBL board or a GRBL simulator is connected): Open a CNCJob, click "GRBL Sender", connect, then click Start. The progress bar moves, and the console shows the lines.

Commit: `feat(grbl-sender): stream the G-code with run control, overrides and check mode`

---

## Phase E: Autolevelled stream

### T14: Snake probe order for grid points

Files: `appPlugins/Common/levelling_core.py`.

1. In `on_add_grid_points` (levelling_core.py), the code builds the list `points` row by row, with X always increasing. After the 2 nested loops end (after `new_y += dy`, before `pt_id = 0`), add:
```python
        # snake order: reverse every 2nd row, so the probe moves to the next point
        # of the row and does not go back across the board
        row_values = sorted({p[1] for p in points})
        snake = []
        for row_idx, y_val in enumerate(row_values):
            row_pts = [p for p in points if p[1] == y_val]
            row_pts.sort(key=lambda p: p[0], reverse=bool(row_idx % 2))
            snake.extend(row_pts)
        points = snake
```
2. Run the gate. If a test fails because it expects the old order of the probe points, stop and report it (R5). Do not change the test.

Commit: `feat(levelling): probe the grid in snake order`

### T15: G1 splitter

(Part 1, A6 changes the position rules and adds tests.)

Files: new `appPlugins/Common/gcode_segment.py`, new `tests/test_grbl_segment.py`.

1. Make `gcode_segment.py`:
```python
# (file header as in T02)
"""
Pure G-code helpers of the GRBL Sender: split long G1 moves, and make the
3D toolpath with the line index of each segment.

No Qt imports, no app imports - standard library only.
"""

import math
import re

_WORD_RE = re.compile(r'([A-Z])\s*([+\-]?(?:\d+\.?\d*|\.\d+))')


def _words(line):
    return [(m.group(1), float(m.group(2))) for m in _WORD_RE.finditer(line.upper())]


def _fmt(value, decimals):
    text = '%.*f' % (decimals, value)
    return '0.' + '0' * decimals if text.startswith('-') and float(text) == 0.0 else text


def split_long_moves(lines, max_len, decimals=4):
    """
    Split each absolute G1 move with X or Y that is longer than `max_len`
    into equal G1 moves, so a height map can level the cut between its ends.

    The modal state is tracked: G0/G1/G2/G3, G90/G91, X/Y/Z. A line is
    left unchanged if it is not a G1 move, if the mode is G91, if the start
    point is not known, or if it has other words than G, X, Y, Z, F, N.
    The feed word stays on the first piece only (it is modal).

    :param lines:    list of str (clean lines, see SenderGen.clean_lines()).
    :param max_len:  the longest XY length of 1 piece (> 0).
    :param decimals: decimals of the new X/Y/Z words.
    :return: (new_lines, count of split moves)
    """
    if not max_len > 0:
        raise ValueError("max_len must be > 0")
    pos = {'X': None, 'Y': None, 'Z': None}
    motion = None
    absolute = True
    out = []
    split_count = 0
    for line in lines:
        words = _words(line)
        g_codes = [v for k, v in words if k == 'G']
        for g in g_codes:
            if g in (0.0, 1.0, 2.0, 3.0):
                motion = g
            elif g == 90.0:
                absolute = True
            elif g == 91.0:
                absolute = False
        axes = {k: v for k, v in words if k in 'XYZ'}
        letters = {k for k, _v in words}
        start = dict(pos)
        # update the position
        if axes:
            if absolute:
                pos.update(axes)
            else:
                for k, v in axes.items():
                    pos[k] = None if pos[k] is None else pos[k] + v
        can_split = (
            motion == 1.0 and absolute and ('X' in axes or 'Y' in axes) and
            letters <= set('GXYZFN') and all(g in (1.0, 90.0) for g in g_codes) and
            None not in (start['X'], start['Y'], start['Z']) and
            None not in (pos['X'], pos['Y'], pos['Z'])
        )
        if not can_split:
            out.append(line)
            continue
        length = math.hypot(pos['X'] - start['X'], pos['Y'] - start['Y'])
        pieces = int(math.ceil(length / max_len - 1e-9))
        if pieces <= 1:
            out.append(line)
            continue
        feed = [v for k, v in words if k == 'F']
        for n in range(1, pieces + 1):
            t = n / pieces
            x = start['X'] + (pos['X'] - start['X']) * t
            y = start['Y'] + (pos['Y'] - start['Y']) * t
            z = start['Z'] + (pos['Z'] - start['Z']) * t
            piece = 'G1 X%s Y%s Z%s' % (_fmt(x, decimals), _fmt(y, decimals), _fmt(z, decimals))
            if n == 1 and feed:
                piece += ' F%s' % _fmt(feed[0], 2)
            out.append(piece)
        split_count += 1
    return out, split_count
```
2. Make `tests/test_grbl_segment.py` with these tests:
   - `test_long_g1_is_split`: lines `['G90', 'G0 X0 Y0 Z1', 'G1 Z-0.1 F100', 'G1 X10 Y0']` and `max_len=2.5` give 4 pieces for the last line. The last piece is `'G1 X10.0000 Y0.0000 Z-0.1000'`, and the count is 1.
   - `test_short_g1_unchanged`: `'G1 X1 Y0'` from (0, 0, -0.1) with `max_len=2` stays the same line.
   - `test_g0_unchanged`: a long `G0 X100` stays 1 line.
   - `test_g91_unchanged`: after `G91`, a long `G1 X50` stays 1 line.
   - `test_unknown_start_unchanged`: `['G1 X50 Y0']` with no move before it stays 1 line.
   - `test_feed_on_first_piece_only`: lines `['G0 X0 Y0 Z0', 'G1 X10 F300']` with `max_len=2` give 5 pieces. Only the first piece ends with `F300.00`.
   - `test_other_words_unchanged`: `'G1 X50 S1000'` stays 1 line (`S` is not in the list).
   - `test_bad_max_len`: `max_len=0` raises `ValueError`.
3. Run the gate. Run `check_gate.py --update`.

Commit: `feat(grbl-sender): split long G1 moves for autolevelling`

### T16: Make the levelled job

(Part 1, A7 and A8 change this ticket: modal-aware arc split, strict levelling, frame binding, the 2-phase Start, tool length offset check.)

Files: `appPlugins/ToolGrblSender/SenderGen.py`, `appPlugins/ToolGrblSender/Sender.py`, `tests/test_grbl_sender_gen.py`.

1. Add to `SenderGen.py`:
```python
from types import SimpleNamespace

from appPlugins.Common.gcode_segment import split_long_moves
from appPlugins.Common.levelling_interp import new_levelling_state, level_gcode_line


def needs_segmentation(target_obj):
    """:return: True if the G-code of the CNCJob was not made with segmented lines."""
    return getattr(target_obj, 'is_segmented_gcode', False) is not True


def split_arcs(lines, units, arc_segment, decimals=4):
    """
    Split the G2/G3 arcs into G1 lines without a height change: level_gcode_line()
    with a 0 offset splits the arcs and keeps every Z.

    :return: (new_lines, count of split arcs)
    """
    state = new_levelling_state(arc_segment=arc_segment, units=units)
    out = []
    for line in lines:
        out.extend(level_gcode_line(line, state, lambda x, y: 0.0, decimals).split('\n'))
    return out, state['arcs_split']


def job_proxy(target_obj, lines):
    """
    A stand-in for the CNCJob that LevellingCoreMixin.autolevell_gcode() can level:
    1 tool with the stream text.
    """
    return SimpleNamespace(
        tools={'job': {'gcode': '\n'.join(lines) + '\n'}},
        units=target_obj.units,
        coords_decimals=target_obj.coords_decimals,
        seg_x=getattr(target_obj, 'seg_x', 0) or 0,
        seg_y=getattr(target_obj, 'seg_y', 0) or 0,
        obj_options=target_obj.obj_options,
    )
```
2. In `Sender.py`, add `build_levelled_job()` and change `on_start` and `on_save_levelled_gcode`:
```python
    def build_levelled_job(self):
        """
        Make self.job_lines from the selected CNCJob, with the height map applied.
        GUI thread. Steps: clean -> split long G1 (only if the job is not
        segmented) -> level (level_gcode_line also splits the arcs).

        :return: True if the job has lines.
        """
        if not self.build_job():
            return False
        target = self._target()
        ctx = self._al_capture_context()
        snapshot = self._al_capture_apply_input(target, units=ctx.units, require_segmented=False)
        if snapshot is None:
            return False
        lines = self.job_lines
        if SenderGen.needs_segmentation(target):
            seg_len = float(self.app.options.get("tools_grbl_seg_len", 1.0))
            lines, count = split_long_moves(lines, seg_len, decimals=target.coords_decimals)
            if count:
                self.app.inform.emit('%s: %d' % (_("Long G1 moves split for the levelling"), count))
        proxy = SenderGen.job_proxy(target, lines)
        diagnostics = []
        result = self.autolevell_gcode(proxy, self.ui.al_method_radio.get_value(),
                                       snapshot=snapshot, diagnostics=diagnostics)
        if result is None:
            return False
        for warning in diagnostics:
            self.app.inform.emit(warning)
        self.job_lines = [line for line in result['job'].splitlines() if line.strip()]
        self.job_map_generation = self._al_generation
        return True

    def build_stream_job(self):
        """The job for Start and Save: levelled if 'Level the G-code' is checked."""
        if self.ui.autolevel_cb.get_value() is True:
            return self.build_levelled_job()
        if not self.build_job():
            return False
        if self.app.options.get("tools_grbl_arc_mode", 'split') == 'split':
            target = self._target()
            self.job_lines, count = SenderGen.split_arcs(
                self.job_lines, target.units, float(self.app.options.get("tools_grbl_arc_segment", 0.5)),
                decimals=target.coords_decimals)
            if count:
                self.app.inform.emit('%s: %d' % (_("Arc moves split into line moves"), count))
        return True
```
   - In `on_start`, change the first line `if not self.build_job():` to `if not self.build_stream_job():`.
   - In `on_save_levelled_gcode`, change the first line to `if not self.build_stream_job():`, and delete the T13 comment line under it.
   - Add the import `from appPlugins.Common.gcode_segment import split_long_moves`.
   - With autolevel on, `level_gcode_line` splits the arcs (T05 did not change this), so the rule "always split with autolevel" holds with no more code.
3. **Frame check before a levelled start.** In `on_start`, after `lines = list(self.job_lines)`, add:
```python
        levelled = self.ui.autolevel_cb.get_value() is True
```
   In `worker_task`, after the `with self._grbl_op_lock:` block that calls `_grbl_prepare_locked`, add:
```python
                if levelled:
                    text, status = self._grbl_transact(op, '$G', timeout=5.0, echo=False)
                    units_cmd = 'G20' if str(self._al_data_units).upper() == 'IN' else 'G21'
                    if status != 'ok' or not grbl_modes_confirmed(text, units_cmd):
                        self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                            "GRBL is not in the units of the height map, or not in G90/G94. "
                            "The levelled job was not started."))
                        how = 'error'
                        return
```
   Add `grbl_modes_confirmed` to the `grbl_protocol` import of `Sender.py`.
4. Add to `tests/test_grbl_sender_gen.py`:
   - `TestNeedsSegmentation.test_flag_true`: `SimpleNamespace(is_segmented_gcode=True)` gives False.
   - `TestNeedsSegmentation.test_flag_false_or_missing`: `is_segmented_gcode=False` gives True, and an object with no flag gives True.
   - `TestSplitArcs.test_arc_split_keeps_z`: `['G90', 'G21', 'G0 X0 Y0 Z-0.1', 'G2 X10 Y0 I5 J0']` with `units='MM'` and `arc_segment=1.0` gives more than 5 lines. Every new `G1` line has `Z-0.1` (check with `'Z-0.1' in line`), and the count is 1.
   - `TestSplitArcs.test_no_arcs`: lines with no G2/G3 come back the same, and the count is 0.
5. Run the gate. Run `check_gate.py --update`.

Commit: `feat(grbl-sender): stream levelled G-code; segment it when the job is not segmented`

---

## Phase F: 3D visualizer

### T17: Precondition, and keep the 3D canvas on the app

**Before this ticket**, run `git status --short appGUI/PlotCanvas3d.py appHandlers/appUIActions.py`. If either file shows `M`, stop. The user changes these files now (the grid size from the bed size). Report this, and wait until the user commits the work.

Files: `appHandlers/appUIActions.py`, `appMain.py`.

1. In `appMain.py`, after `self.area_3d_tab = QtWidgets.QWidget()` (line 1136), add `self.plotcanvas3d = None`.
2. In `appHandlers/appUIActions.py`, in `on_3d_area` (line 994), after the line `plotcanvas3d = PlotCanvas3d(plot_container_3d, self.app)` (line 1009, inside the `try`), add `self.app.plotcanvas3d = plotcanvas3d`.
   - At the start of `on_3d_area`, after the line `from appGUI.PlotCanvas3d import PlotCanvas3d`, add:
     ```python
             if getattr(self.app, 'plotcanvas3d', None) is not None:
                 self.ui.plot_tab_area.setCurrentWidget(self.app.area_3d_tab)
                 return
     ```
     The tab is then not made 2 times.
3. In the close branch `elif tab_obj_name == "3D_area_tab":` (appUIActions.py:1101), add `self.app.plotcanvas3d = None` as the first line of the branch.
4. Run `.venv/Scripts/python.exe -m pytest tests/test_plotcanvas3d.py tests/test_view_cube.py -q -p no:cacheprovider` and the gate.

Commit: `refactor(3d): keep the Plot 3D canvas on the app`

### T18: Toolpath with line index

(Part 1, A9 changes the position rules and adds tests.)

Files: `appPlugins/Common/gcode_segment.py`, new `tests/test_grbl_toolpath.py`.

1. Add to `gcode_segment.py`:
```python
def parse_toolpath(lines, start=(0.0, 0.0, 0.0)):
    """
    The 3D toolpath of stream lines: 1 straight segment for each G0/G1 line
    that moves. Arcs must be split before (SenderGen.split_arcs()); a G2/G3
    line gives 1 straight segment from its start to its end point.

    :param lines: list of str.
    :param start: the start position.
    :return: list of (line_index, (x0, y0, z0), (x1, y1, z1), rapid) where
        rapid is True for G0.
    """
    pos = list(start)
    motion = 0.0
    absolute = True
    segments = []
    for index, line in enumerate(lines):
        words = _words(line)
        for k, v in words:
            if k == 'G':
                if v in (0.0, 1.0, 2.0, 3.0):
                    motion = v
                elif v == 90.0:
                    absolute = True
                elif v == 91.0:
                    absolute = False
        axes = {k: v for k, v in words if k in 'XYZ'}
        if not axes or any(k == 'G' and v in (28.0, 30.0, 53.0, 92.0, 10.0) for k, v in words):
            continue
        new = list(pos)
        for i, axis in enumerate('XYZ'):
            if axis in axes:
                new[i] = axes[axis] if absolute else pos[i] + axes[axis]
        if new != pos:
            segments.append((index, tuple(pos), tuple(new), motion == 0.0))
        pos = new
    return segments
```
2. Make `tests/test_grbl_toolpath.py`:
   - `test_basic`: `['G0 X1 Y1', 'G1 Z-1', 'G1 X2']` gives 3 segments with line indexes 0, 1 and 2. The rapid flags are True, False and False. The last end point is `(2.0, 1.0, -1.0)`.
   - `test_relative`: `['G91', 'G1 X1', 'G1 X1']` ends at `(2.0, 0.0, 0.0)`.
   - `test_no_move_no_segment`: `['G1 X0']` from the start (0, 0, 0) gives an empty list.
   - `test_skips_g28_g92`: `['G92 X5', 'G28 X0']` gives an empty list.
3. Run the gate. Run `check_gate.py --update`.

Commit: `feat(grbl-sender): make the 3D toolpath with the line index`

### T19: `SenderView3d`

(Part 1, A9 changes this ticket: accepted color, report units, WCO cache, arcs in send mode, old visuals.)

Files: new `appPlugins/ToolGrblSender/SenderView3d.py`, `appPlugins/ToolGrblSender/Sender.py`.

1. Make `SenderView3d.py`:
```python
# (file header as in T02)
"""The visuals of the GRBL Sender in the Plot 3D tab: toolpath, done path, tool marker, height map."""

import numpy as np
from vispy import scene
from vispy.color import Colormap

RAPID_COLOR = (0.55, 0.55, 0.55, 0.6)
CUT_COLOR = (0.10, 0.45, 0.90, 1.0)
DONE_COLOR = (0.10, 0.70, 0.30, 1.0)
TOOL_COLOR = (0.90, 0.10, 0.10, 1.0)


class SenderView3d:
    def __init__(self, canvas):
        """:param canvas: the PlotCanvas3d of app.plotcanvas3d."""
        self.canvas = canvas
        parent = canvas.view.scene
        self.path = scene.visuals.Line(parent=parent, connect='segments', width=1.5, method='gl')
        self.done = scene.visuals.Line(parent=parent, connect='segments', width=2.5, method='gl')
        self.tool = scene.visuals.Markers(parent=parent)
        self.mesh = None
        self.z_scale = 10.0
        self._segments = []

    def set_toolpath(self, segments):
        """:param segments: the list of gcode_segment.parse_toolpath()."""
        self._segments = segments
        if not segments:
            self.path.set_data(pos=np.zeros((0, 3)))
            return
        pos = np.array([p for _i, a, b, _r in segments for p in (a, b)], dtype=np.float32)
        colors = np.array([c for _i, _a, _b, r in segments for c in ((RAPID_COLOR,) * 2 if r else (CUT_COLOR,) * 2)],
                          dtype=np.float32)
        self.path.set_data(pos=pos, color=colors)
        self.set_done(-1)

    def set_done(self, last_line_index):
        """Draw the segments of the lines up to and including `last_line_index` in the done color."""
        done = [s for s in self._segments if s[0] <= last_line_index]
        if not done:
            self.done.set_data(pos=np.zeros((0, 3), dtype=np.float32))
            return
        pos = np.array([p for _i, a, b, _r in done for p in (a, b)], dtype=np.float32)
        self.done.set_data(pos=pos, color=DONE_COLOR)

    def set_tool_position(self, xyz):
        self.tool.set_data(pos=np.array([xyz], dtype=np.float32), face_color=TOOL_COLOR, size=10)

    def set_height_map(self, grid_data, z_scale=None):
        """
        :param grid_data: (xs, ys, grid) of build_bilinear_grid(), or None to remove the mesh.
        :param z_scale:   the factor of the height for the display.
        """
        if z_scale is not None:
            self.z_scale = z_scale
        if self.mesh is not None:
            self.mesh.parent = None
            self.mesh = None
        if grid_data is None:
            return
        xs, ys, grid = grid_data
        vertices = np.array([(x, y, grid[j][i] * self.z_scale)
                             for j, y in enumerate(ys) for i, x in enumerate(xs)], dtype=np.float32)
        faces = []
        nx = len(xs)
        for j in range(len(ys) - 1):
            for i in range(nx - 1):
                a = j * nx + i
                faces.append((a, a + 1, a + nx))
                faces.append((a + 1, a + nx + 1, a + nx))
        z = vertices[:, 2]
        span = float(z.max() - z.min()) or 1.0
        cmap = Colormap([(0.13, 0.27, 0.65), (0.19, 0.72, 0.47), (0.84, 0.19, 0.15)])
        colors = cmap.map((z - z.min()) / span)
        self.mesh = scene.visuals.Mesh(vertices=vertices, faces=np.array(faces, dtype=np.uint32),
                                       vertex_colors=colors, parent=self.canvas.view.scene)
        self.mesh.opacity = 0.7

    def clear(self):
        for visual in (self.path, self.done, self.tool):
            visual.parent = None
        self.set_height_map(None)
```
2. In `Sender.py`:
   - Add a button to `GrblSenderUI` (in step (e) of T07, after `save_levelled_button`):
     ```python
             self.view3d_button = FCButton(_("Show in Plot 3D"))
             self.view3d_button.setToolTip(_("Show the toolpath, the tool and the height map in the Plot 3D tab."))
             run_grid.addWidget(self.view3d_button, 10, 0, 1, 4)
     ```
   - Connect it in `connect_signals_at_init`: `self.ui.view3d_button.clicked.connect(self.on_show_3d)`.
   - Add these methods:
```python
    def on_show_3d(self):
        if getattr(self.app, 'plotcanvas3d', None) is None:
            self.app.on_3d_area()
        canvas = getattr(self.app, 'plotcanvas3d', None)
        if canvas is None:
            return
        if self.view3d is None or self.view3d.canvas is not canvas:
            self.view3d = SenderView3d(canvas)
        if not self.job_lines and not self.build_stream_job():
            return
        self.view3d.set_toolpath(parse_toolpath(self.job_lines))
        self._update_3d_height_map()
        canvas.fit_view()

    def _update_3d_height_map(self):
        if self.view3d is None or not self.al_heights_valid:
            return
        points = [(v['point'].x, v['point'].y, v['height']) for v in self.al_voronoi_geo_storage.values()]
        self.view3d.set_height_map(build_bilinear_grid(points, self._al_grid_tolerance()))
```
   - In `_al_on_height_map_ready`, add `self._update_3d_height_map()` as the last line.
   - In `on_start`, change the `on_progress` lambda so that the 3D view gets the line index too:
     `on_progress=lambda d, t: self.stream_progress_sig.emit(d, t),` stays, and in `_on_stream_progress` add:
     ```python
             if self.view3d is not None:
                 self.view3d.set_done(done - 1)
     ```
   - Add these imports: `from appPlugins.ToolGrblSender.SenderView3d import SenderView3d`, `from appPlugins.Common.gcode_segment import parse_toolpath`, and `from appPlugins.Common.levelling_interp import build_bilinear_grid`.
   - When a job is levelled, the toolpath is the levelled path. When the height map changes, the user clicks "Show in Plot 3D" again.
3. **Bed size.** Do not add a bed-size field. The grid size of the 3D canvas comes from the Preferences value that the user adds to `PlotCanvas3d`. If `PlotCanvas3d` has a method `set_grid_size`, the sender does not call it. The canvas sets the size itself.
4. Run `.venv/Scripts/python.exe -c "import appMain; import appPlugins.ToolGrblSender.SenderView3d; print('ok')"`. It must print `ok`. Run the gate and `tests/test_plotcanvas3d.py`.

Commit: `feat(grbl-sender): show the toolpath, the tool and the height map in the Plot 3D tab`

---

## Final check (after T19)

(Part 1, A0 replaces step 1 with the full gate.)

1. Run the full suite 1 time: `.venv/Scripts/python.exe -m pytest tests -q -rA -p no:cacheprovider`. Every test passes, except the tests that the README of the gates marks as xfail.
2. Run `.venv/Scripts/python.exe tests/gates/check_gate.py`. It exits with 0.
3. Manual check in the app (the user does this):
   - Open a CNCJob. Click "GRBL Sender" in the CNCJob UI. The combo shows that job.
   - Check "Show console": the dock opens on the right. Close the Plugin tab: the dock hides. Open the sender again: the dock shows again. Restart the app: the checkbox keeps its value.
   - Open Levelling: the controller list has MACH3, MACH4 and LinuxCNC only. "Save Probing GCode" for MACH3 gives the same text as before T01.
   - With a GRBL board, or with GRBL connected through `loop://` for a dry test: connect, jog, zero, probe a 4×4 grid with "Bicubic", check "Level the G-code", Start in check mode, then Start. Watch the progress, the overrides and the tool marker in Plot 3D.
