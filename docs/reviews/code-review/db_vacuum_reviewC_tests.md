# Tier 2-DB Review C — Test Authority + WAL/auto_vacuum Ordering + No-Regression

**Branch:** `feature/db-incremental-vacuum` @ `c733acdb`
**Framing C:** Test fixture authority; WAL/auto_vacuum-ordering correctness; no full-suite regression.
**Reviewer:** Reviewer C (3-framing-disjoint Tier 2-DB).
**Date:** 2026-06-19

## Lead verdict (the three load-bearing invariants)

| Invariant | Genuinely tested? | Evidence |
|---|---|---|
| **WAL-ordering gotcha** (auto_vacuum MUST precede `journal_mode=WAL`) | **NO — not directly** | No test reverses the pragma order. `test_reclaims_when_incremental` (test:206) only asserts a fresh `initialize()` DB yields mode 2; it does not assert that WAL-first yields mode 0. A refactor that reorders the two pragmas in `database.py:363-365` / `:92-94` would NOT be caught by name. See **C-HIGH-1**. |
| **File actually shrinks** | **YES** | `test_converts_and_shrinks_and_backs_up` (test:248) captures `size_before = os.path.getsize(...)` (test:262) and asserts `os.path.getsize(db.db_file) < size_before` (test:277) on a temp DB with real bloat (4000×4KB insert→delete, helper:157). Real before/after on a real file. |
| **Supervised VACUUM NOT scheduled** | **YES (literal-string strong; intent weaker)** | `test_supervised_vacuum_not_in_nightly_schedule` (test:380) asserts `'"vacuum_full_supervised"' not in src` and `"vacuum_full_supervised," not in src`. Confirmed absent from both `_cleanup_ops` lists in `__init__.py`. Solid. |

## Test authority — do tests drive real code?

**YES.** `TestIncrementalVacuum` and `TestVacuumFullSupervised` instantiate a real `UniversalRoomDatabase` (`_make_db`, test:128) over a temp-file SQLite DB, start the real single-writer worker (`_with_worker`, test:175), and call the real DAO methods. The executor-job shim runs the real `shutil.copy2` backup. A revert of the feature would fail these: `incremental_vacuum`/`vacuum_full_supervised` would not exist → ImportError/AttributeError. Verified live: **16/16 pass in 0.63s.**

Button tests (test:331-372) are source-grep, not runtime — explicitly justified by the same idiom as `test_v462_d5_acknowledge_button.py` (importing `button.py` pulls the full coordinator chain). Acceptable, but they prove *text*, not *behavior* (C-LOW-1).

## Findings

### C-HIGH-1 — WAL-ordering invariant is undertested (the headline gotcha)
The builder's central correctness claim — "auto_vacuum MUST be declared before `journal_mode=WAL` or WAL silently locks auto_vacuum=0" (`database.py:355-363`, `:83-94`) — has **no dedicated regression test**. The brief's requirement #2 (auto_vacuum-first→2; WAL-first→0) is not met. `test_reclaims_when_incremental` incidentally depends on correct ordering but asserts only the positive case; a future refactor reordering the pragmas could regress production silently while keeping tests green (the fresh-file path *might* still flip to 0, but nothing documents/guards the failure mode).
**Fix:** add a test that opens two temp DBs — one applying `auto_vacuum=INCREMENTAL` then `WAL`, one applying `WAL` then `auto_vacuum=INCREMENTAL` — and asserts the first reads `PRAGMA auto_vacuum == 2` and the second `== 0`. This pins the gotcha to a named assertion.

### C-HIGH-2 — Nightly membership test cannot see the broken mirror (real defect under it)
`__init__.py` has TWO nightly schedules: `_cleanup_ops` (primary, line 1159) and `_cleanup_ops_d` (deferred-startup path, line 1278, scheduled at 2:30 AM via `_nightly_maintenance_deferred`, line 1331). The deferred list explicitly documents itself as mirroring the primary ("mirror primary path", :1289/:1292). **`incremental_vacuum` was added ONLY to the primary list, not the deferred mirror.** On any boot that takes the deferred branch (the activity-logger DB-race path), nightly reclamation never runs.
`test_incremental_vacuum_in_nightly_ops` (test:374) uses a bare substring check, which passes on the single primary occurrence and is structurally blind to the missing mirror.
**Fix (code):** add `("incremental_vacuum", "incremental_vacuum", {})` to `_cleanup_ops_d`. **Fix (test):** assert the tuple appears in *both* lists (or assert `src.count(...) == 2`).

### C-MEDIUM-1 — Concurrent-run guard test proves the read, not the set/clear
`test_concurrent_run_guard` (test:281) manually sets `db._vacuum_in_progress = True` then asserts `already_running`. It proves the guard *reads* the flag but never proves a real in-flight `vacuum_full_supervised()` *sets* it (or that `finally` clears it). A bug where the flag is never set would pass this test.
**Fix:** in the happy-path shrink test, assert `db._vacuum_in_progress is False` after completion (cheap), and/or race two real calls.

### C-LOW-1 — Button press path is grep-only
`async_press` (`button.py:1380`), its `_running` re-entrancy guard, and the persistent-notification on failure are never executed in tests. Documented trade-off; acceptable. Note for future: a thin runtime test with the DAO mocked would cover the guard + notification branch.

### C-LOW-2 — `_create_bloat` masks a real WAL-visibility subtlety
The helper runs `PRAGMA wal_checkpoint(TRUNCATE)` (helper:171) so freed pages reach the freelist visible to the worker's separate connection. This is correct for the *test*, but it means the tests never exercise the production timing where the nightly `incremental_vacuum` runs against a freelist populated by other connections without an explicit checkpoint. Low risk (nightly runs after prunes that commit), but the tests don't prove cross-connection freelist visibility in the un-checkpointed case.

## incremental_vacuum coverage (brief #3) — adequate
- no-op when not incremental → 0: `test_noop_when_auto_vacuum_not_incremental` (test:184), real NONE-mode DB. PASS.
- reclaims when incremental: `test_reclaims_when_incremental` (test:206). PASS.
- page cap enforced: `test_bounded_page_count` (test:223) asserts `0 < reclaimed <= cap`. PASS — and matches real clamp at `database.py:6827`.
- runs through worker `_db()` path: `test_runs_through_worker_path` (test:236) greps the method body for `self._db()` and absence of `_db_read()`. Source-grep (acceptable as a path-guard).

## No-regression (brief #6)
Full suite in detached worktree `.claude/worktrees/dbrev-C` (removed after): **35 failed, 6000 passed, 28 skipped, 14 errors.** Exactly matches stated baseline (35 failed + 14 errors). **Zero new failures introduced.** Worktree cleaned up; no ops on main checkout.

## Verdict
**Tests genuinely drive real code and the file-shrink + not-scheduled invariants are real.** Two gaps block a clean pass: the headline **WAL-ordering gotcha is not pinned by any test (C-HIGH-1)**, and the **nightly-membership test masks an actual broken-mirror defect — `incremental_vacuum` is absent from the deferred-startup schedule (C-HIGH-2)**. Fix C-HIGH-2 in code (one-line) plus its test, add the C-HIGH-1 ordering test, and address C-MEDIUM-1. Then re-pass.
