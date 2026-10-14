# UNLOAD-SYMMETRY-TASK-HYGIENE-1 — Review C (test authority via real per-site source mutation)

- Branch `feature/unload-symmetry` @ 53cbe0742; diff base `c93265887~1` (66a8fb6a9, plan commit) — verified via `git log`.
- Method: one production-source mutation at a time (Python write → pytest → write original back in `finally`),
  `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, all `__pycache__` cleared before every run.
- Test set (subset, serial): test_db_write_worker_boot_race, test_unload_symmetry_shutdown_db_hygiene,
  test_anomaly_baseline_periodic_save, test_setup_unload_symmetry, test_coordinator_diagnostics,
  test_unload_symmetry_task_hygiene.
- Baseline: 4 failures are PRE-EXISTING at `c93265887~1` (verified in a separate base worktree) and excluded from the
  RED signal: `test_no_untracked_async_create_task_in_init`, `test_coordinator_enabled_keys_mapping`,
  `test_room_name_desync_retry_{registers_on_unload_when_loaded,cancels_inline_when_not_loaded}`.
- Tests drive production code (real `UniversalRoomDatabase` on a tmp SQLite, real `DecisionLogger` /
  `ComplianceTracker` / `AnomalyDetector`, real `CoordinatorManager` wiring); no copied logic found.
- Tree restored after every drill; `git status` clean at end.

## Mutation table

| # | Site (file:line) | Mutation | Result | Test(s) that went RED |
|---|---|---|---|---|
| M1 | database.py:559 write-path raise | `DBShuttingDown` → `RuntimeError` | RED | test_db_fast_fails_with_db_shutting_down_subclass, test_db_shutting_down_logs_debug_not_error_in_dao |
| M2 | database.py:~482 `_drain_pending_futures` exc_cls | always `RuntimeError` | RED | test_drain_pending_futures_shutdown_raises_dbshuttingdown, test_flush_leftover_at_ha_stop_is_db_shutting_down |
| M3a | database.py:466 flush leftover `is_shutdown=` | force `False` | RED | test_flush_leftover_at_ha_stop_is_db_shutting_down |
| M3b | database.py:466 (B-LOW-1 non-shutdown) | force `True` | RED | test_flush_leftover_outside_shutdown_stays_plain_runtime_error |
| M4a | database.py:373 mid-write cancel (A-L1/B-LOW-3) | always `RuntimeError` | **GREEN** | — |
| M4b | database.py:373 mid-write cancel | always `DBShuttingDown` | **GREEN** | — |
| M5 | database.py:~428 flush-budget WARNING→DEBUG demote | `if False:` | **GREEN** | — |
| M6 | database.py:496 drained-count WARNING→DEBUG demote | `if False:` | **GREEN** | — |
| M7 | coordinator_diagnostics.py:~1743 prune `except Exception` (A-L2) | narrow to `ZeroDivisionError` (failure propagates, disables saves) | RED | test_load_baselines_prune_failure_keeps_saves_enabled |
| M8.0–8.6 | coordinator_diagnostics.py:327/369/761/803/836/1648/1687 `_db_read()` | each individually → `_db()` | RED ×7 | test_diagnostics_reads_increment_reads_not_writes (all 7) + _survive_worker_stopped (0–5) / _prune_failure_keeps_saves_enabled (6) |
| M9a | coordinator_diagnostics.py:303 `log_decision` `except DBShuttingDown` | arm removed | RED | test_db_shutting_down_logs_debug_not_error_in_dao |
| M9b | coordinator_diagnostics.py:1736 prune `except DBShuttingDown` | arm removed | **GREEN** | — |
| M9c | coordinator_diagnostics.py:1830 `save_baselines` `except DBShuttingDown` | arm removed | **GREEN** | — |
| M9d | coordinator_diagnostics.py:1927 `store_outcome` `except DBShuttingDown` | arm removed | **GREEN** | — |
| M10a | manager.py:566 `async_add_shutdown_job(HassJob(...))` | revert to `bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, ...)` | RED | TestD2ShutdownJobWiring::test_shutdown_job_invoked_zero_arg_the_way_core_does + 5 others |
| M10b | manager.py on_stop handler signature | `(self)` → `(self, _event)` | RED | TestD2ShutdownJobWiring::test_handler_signature_is_zero_arg, ::test_shutdown_job_invoked_zero_arg_the_way_core_does + 3 |
| M10c | manager.py:72 `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S` | 15 → 30 | RED | TestD2ShutdownJobWiring::test_timeout_constant_fits_inside_stage_1_budget |

17 of 24 drills RED; 7 GREEN = untested sites.

## Findings

- **C-M1 MEDIUM — mid-write-cancel classification untested** (database.py:367-379). Fix-up 12bd021d2 claims A-L1/B-LOW-3
  ("mid-write cancel at HA stop → DBShuttingDown") with tests, but BOTH directions of the mutation (always RuntimeError,
  always DBShuttingDown) leave the suite green. A regression would either put ERROR noise back at every restart, or
  route a genuine non-shutdown cancel (unload/reload/VACUUM) to DEBUG and hide lost writes. Class: hollow test anchor (#62)
  / claimed-fix-without-oracle. Need: cancel the worker while a factory is awaiting, with `is_stopping` True and False,
  and assert the in-flight future's exception class.
- **C-M2 MEDIUM — `save_baselines` `except DBShuttingDown` arm untested** (coordinator_diagnostics.py:1830). This is the
  write that runs at shutdown (D2 path); removing the arm falls through to `_LOGGER.error` with no red test. Same for
  `store_outcome` (:1927) and the orphan-prune arm (:1736) — LOW each. Only `log_decision` (:303) is anchored. Class #53
  one-missed-site (test side): M9a's test covers one of four parallel arms. Need: per-DAO test driving the call with a
  stopped worker + `is_stopping=True` and asserting no ERROR record.
- **C-L1 LOW — log demotions untested** (database.py:~428 flush budget, :496 drained count). Both are pure log-level
  routing; disabling them is GREEN. Acceptable risk but cheap to anchor with caplog.
- **C-M3 MEDIUM — hermeticity fixture breaks a sibling test under reordering.** `_hermetic_db_modules`
  (test_unload_symmetry_shutdown_db_hygiene.py:44-82) pops and re-imports `database` in `sys.modules` and does not restore
  the original module object. Running this file BEFORE test_db_write_worker_boot_race.py makes
  `test_mutation_remove_buffering_makes_test_red` fail with `ImportError: module ...database not in sys.modules`
  (`importlib.reload` on the stale `ura_db` object, boot_race:235/261). Repro:
  `pytest quality/tests/test_unload_symmetry_shutdown_db_hygiene.py quality/tests/test_db_write_worker_boot_race.py`
  → 1 failed. Alphabetical full-suite order hides it today; `-p randomly`, `-k`, or a file rename exposes it. The fixture
  does not hide production behavior (it re-imports real source; mutations were seen through it), but it leaks module
  identity state across files. Fix: save the original `sys.modules` entries and restore them on teardown.
  Note the boot_race self-mutating test restores database.py in `finally`, and the tree stayed clean.

## Verdict: FIX-REQUIRED

Must-fix before ship: C-M1 (anchor the mid-write-cancel classification both ways), C-M2 (anchor `save_baselines`;
ideally all 4 DBShuttingDown arms), C-M3 (restore `sys.modules` on fixture teardown). C-L1 optional (fix-LOWs-in-cycle).
Production logic itself was not found wrong — every finding is a test-authority gap.

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 3 |
| LOW | 1 |

Bug classes: #62 hollow/missing anchor (C-M1, C-L1), #53 one-missed-site on the test side (C-M2), test hermeticity /
order-dependence (C-M3).
