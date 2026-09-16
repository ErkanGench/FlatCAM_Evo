# Luna execution handoff

## Start here

Read `PLAN.md` sections 1–4. The numbered ticket sections in that file are the authoritative work orders. `regression_checks.py` is runnable against the current tree and deliberately fails on the identified defects.

The requested deliverable for this session was evaluation and planning. Start production edits only in an execution session authorized by the user.

## Dispatch queue

Use `sex-luna` for one row at a time. Send the complete ticket text, not just its title. Include the common worker contract from `PLAN.md` and the referenced scaffold tests.

| Order | Dispatch description | Ticket to include | First check |
|---|---|---|---|
| 1 | Establish tools database baseline | DB-00 | full scaffold |
| 2 | Normalize database records safely | DB-01 | add/run normalization and rejected-import tests |
| 3 | Repair database enum widgets | DB-02 | `EditorChecks.test_numeric_milling_dropdowns_roundtrip`, `EditorChecks.test_cutout_gap_type_roundtrip` |
| 4 | Repair database edit storage | DB-03 | `EditorChecks.test_job_and_offset_write_canonical_keys`, `EditorChecks.test_new_tool_has_drill_dwelltime` |
| 5 | Preserve database record identity | DB-04 | `EditorChecks.test_sparse_ids_render_actual_keys` |
| 6 | Restore plugin target matching | DB-05 | `ConsumerChecks.test_numeric_targets_automatic_lookup`, `ConsumerChecks.test_drilling_numeric_target_updates_parameters` |
| 7 | Preserve selected machining parameters | DB-06 | `ConsumerChecks.test_cutout_picker_does_not_mutate_database_record` plus ticket cases |
| 8 | Rebind database picker callbacks | DB-07 | `ConsumerChecks.test_existing_picker_rebinds_callback` |
| 9 | Protect writes and dirty state | DB-08 | `EditorChecks.test_failed_save_keeps_dirty_flag_and_bytes`, `EditorChecks.test_save_without_visible_tab_writes_database` |
| 10 | Protect close and request lifecycle | DB-09 | ticket Save/Discard/Cancel matrix |
| 11 | Verify all database consumers | DB-10 | full promoted test suite + handler integration |
| 12 | Recover supplied database copy | DB-11 | stop until actual file copy/profile context available |

Full command prefix for a targeted existing test:

```powershell
.\.venv\Scripts\python.exe docs/superpowers/plans/2026-09-16-tools-database-repair/regression_checks.py
```

Append the class/method name(s) from the table. Example:

```powershell
.\.venv\Scripts\python.exe docs/superpowers/plans/2026-09-16-tools-database-repair/regression_checks.py ConsumerChecks.test_existing_picker_rebinds_callback
```

## Review each return before dispatching the next worker

1. Inspect the actual diff; confirm file ownership and preserve the pre-existing uncommitted refactor.
2. Require before/after execution of the named failing test. A worker must explain any fixture/import error separately from application failures.
3. Require ticket-specific additional cases. The initial scaffold intentionally isn't full acceptance coverage.
4. Check the shared contracts: integer enums, canonical data keys, deep copies, stable IDs, no load-time writes, dirty cleared only after successful save or accepted discard.
5. Record completed checks in the ticket. Don't mark DB-11 complete because code tests pass.

## Decisions already made

- No database framework or storage format replacement.
- No new matching algorithm or automatic General fallback.
- Legacy aliases can be normalized; unknown translations require confirmation.
- Persistence uses `QSaveFile` without direct-write fallback.
- The editor owns picker closure; callbacks own insertion.
- Partial multi-selection insertion is reported, not presented as atomic rollback.
- No worker commits, rewrites the user's live database, or resets existing changes.

## Stop conditions

- The named methods have changed enough that a ticket no longer matches: report the mismatch and ask the orchestrator to revise it.
- A normalization conflict can't be resolved by the explicitly documented alias rules: retain the input and report it.
- User data is malformed/truncated: retain the original and report recovery limits.
- A test requires the user's real database or hardware: replace it with a temporary fixture or escalate.
- More than the stated localized edits are needed: stop rather than introducing an architectural refactor.

## Required worker response

```text
Ticket: actual assigned ID
Files changed: exact paths
Before: exact command and failing assertion/error
After: exact command and result
Additional cases: cases actually executed
Outside-scope failures: observed failures with their baseline status
Blockers: concrete unresolved dependency, if any
```

Don't substitute a generic “done” for this response. The next worker gets the accepted result plus its own full ticket.
