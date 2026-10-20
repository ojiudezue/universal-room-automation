# DB-SIZE-GROWTH-1 (365-day room-history retention): Review A

Framing: data integrity and DB architecture preservation.
Branch `feature/db-retention-365` @ `c9564f286`, base `f86375283` (merge-base verified; three-dot diff).

## Verdict: SHIP

No CRITICAL/HIGH/MEDIUM findings. Two LOW notes.

## Invariant checks

| Check | Result | Evidence |
|---|---|---|
| Producer timestamp format, env/energy/occupancy | PASS | `database.py:2770,2785,2808` use `datetime.utcnow().isoformat()`. Live DB (immutable read): 100% of rows have `T` at position 11, length 19 to 26, naive UTC. env 2,608,068 rows, energy 2,611,265, occupancy 2,305,356. |
| Producer timestamp format, room_transitions | PASS | `database.py:4045-4053` binds a tz-aware local `datetime`. Live: 374,019 rows, all `YYYY-MM-DD HH:MM:SS.ffffff-0X:00` (length 32, space separator). The cutoff uses `dt_util.now()` local date (`database.py:5226`), so it is the same clock. |
| No row younger than 365 d deleted | PASS | Cutoff is a date-only `YYYY-MM-DD` = (today in the table's clock − 365 d). A row is deleted only if `timestamp < cutoff 00:00`, so its age is at least 365 d plus the time elapsed today. Rows ON the cutoff date sort above the 10-char prefix in both the `T` and space formats, so they are kept. DST offset changes do not matter because both the comparison and the stored values use the local wall date. |
| Single writer, bounded batches | PASS | Every DELETE goes through `self._db()` (the write queue) at `database.py:5254`. Each batch is at most 1000 rows, with a 0.1 s yield between batches and a cap of 100 batches per table per night (`const.py:2103`). This is the same shape as the existing `cleanup_person_data` (`database.py:3947`). One batch per queue item means no long transaction. |
| Write-flood risk (2026-06-09 incident) | PASS | Steady state is about 7k rows/day/table for 50 rooms, roughly 7 to 13 batches. The first prune is a no-op until 2026-11-19 because the oldest live row is 2025-11-19, so there is no backlog burst. The worst case after that is 100 queue items per table per night. |
| Index coverage of the DELETE predicate | PASS (LOW-1) | EXPLAIN on live schema: outer `SEARCH ... USING INTEGER PRIMARY KEY`; inner `SCAN ... USING COVERING INDEX idx_*_room_time` / `idx_transitions_person`. No table scan, but it is an index scan rather than a range seek, because `timestamp` is not the leading column. Measured: LIMIT-1000 subquery 0.00-0.01 s when matches exist; full no-match scan of room_transitions 1.5 s over Samba (cold, remote). Locally on HA it will be lower. |
| Existing readers unaffected | PASS | Grepped all `FROM <4 tables>` readers (18 sites) and every `days=` literal of 100 or more: none. The longest look-back is 90 d. `get_*transitions(days=None)` now reads at most about 1 year (docstring at `database.py:7349`). |
| No other deleter on these tables | PASS | The only `DELETE FROM` on these tables is the new site. The pre-existing `RETENTION_*` constants (`const.py:2085-2092`) are not consumed by any prune. |
| Nightly op list de-dup (both paths) | PASS | `__init__.py` primary and deferred closures both call `run_nightly_cleanup` (`nightly_maintenance.py:72`). The op list is byte-identical to the old 20 entries plus `room_history` inserted before `incremental_vacuum`. The rotating index stays modulo the new n=21, so an existing stored index of 20 or below is safe. |
| Kill switch | PASS | `retention_days <= 0` returns before any query (`database.py:5242`). |

## Findings

- **LOW-1: index is not a seek** (`database.py:5257`, existing schema `database.py:861,845,878,1007`). Each batch's subquery scans the covering index, and the final under-full batch scans the whole index (about 2.6M entries) while it holds the single writer. Measured cost is sub-second locally and it runs at 02:30, so this is acceptable. Fix only if prune latency shows up in write-queue depth: add a `(timestamp)` index. Bug class: none, performance.
- **LOW-2: env-local test caveat.** `test_blind_window_evse_guard.py::test_EC_manual_row_2_5_documents_final_semantics` reads `docs/` and fails only in a code-only extract. Not a branch defect.

## Process note

During this review, Reviewer C's mutation drill was live in the shared worktree: `database.py:5269` had `asyncio.sleep(0.1)` replaced by `pass`, and `quality/_drillC_retention.py` plus `test_db_retention_nightly_callsites.py` were untracked. To avoid testing a mutant, Review A ran its tests against a clean `git archive c9564f286` extract: 219 passed, plus the LOW-2 environment-only failure. Review A did not touch the drill files.

## Stats

| Severity | Found | Fix required |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 2 | 0 |
