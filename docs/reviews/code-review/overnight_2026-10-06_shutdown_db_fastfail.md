# Review record — SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1 (overnight 2026-10-06)

Branch `fix/shutdown-db-write-fastfail` (base develop `7df38c09b`; pre-review tag
`pre-review-shutdown-db-fastfail` = `fccd0fad1`; fix-up `822242171`). Tier 2-DB
(touches the shared DB write primitive `database.py _db()` and the write worker).
Not deployed — waits for an operator-timed daytime deploy.

## Problem and mechanism (verified in source)

HA 2026.2.3 `core.py:1102-1106` cancels all background tasks right after the 20 s
stopping stage. URA's write worker is a background task. Writes submitted after that
(census snapshots, arrester nudge-eval, diagnostics) buffered on the queue under the
v5.16.2 no-fail-fast rule and waited up to `DB_WRITE_READY_HARD_CAP_S = 300` s, so
HA's 100 s stop stage and 60 s final-write stage both timed out on every restart
(observed 10-05 19:00 restart).

## Change

1. `_db()`: when the worker is not running AND `hass.is_stopping is True`, raise at
   once instead of buffering. VACUUM / SPAN re-migration stop windows (HA running)
   keep buffering, byte-identical.
2. `log_census()`: skip only when stopping AND the worker is gone (no ERROR noise).
3. Worker loop: on `CancelledError` while a caller holds the connection, fail that
   caller's future so it returns instead of hanging (pre-existing defect found by B).

## Findings

| ID | Sev | Reviewer | Bug class | Finding | Status |
|---|---|---|---|---|---|
| B-MED-1 | MEDIUM (pre-existing) | B | Shutdown hang / unresolved future | Worker cancelled mid-`factory(db)`: `CancelledError` bypassed `except Exception`, the caller's future was never resolved, caller hung in `_db()` finally | FIXED in-cycle (worker `except CancelledError` fails the future, re-raises) + test (e) |
| C-MED-1 | MEDIUM | C | #62 missing anchor | Worker-not-running half of the guard untested (`True or ...` mutation stayed green) | FIXED: tests (d) live worker writes while stopping |
| A-LOW-1 | LOW | A | Over-broad guard | `log_census` skipped even while the worker was alive in the first 20 s of stopping | FIXED (guard matches `_db()`) + test |
| A-LOW-2 / B-LOW-2 | LOW | A, B | Log noise | Other DAOs (~40 ERROR arms, ~55 WARNING) still log one line per write rejected during shutdown; same noise as before, now immediate instead of after 300 s | DEFERRED — needs a dedicated exception subclass across ~95 arms; out of scope for this card |
| B-LOW-1 | LOW | B | Guard scope gap | In HA's close stage (`not_running`) `is_stopping` is False again, so a very late timer write can still queue (bounded by the 30 s close stage) | ACCEPTED — a `not_running` check would also match boot; bounded |
| A-INFO | info | A | Misuse of write path | `coordinator_diagnostics` reads go through `_db()` not `_db_read()` | DEFERRED (residual) |
| B-INFO | info | B | Shutdown persistence | STOP-time baseline save races the worker cancel by design; `hass.async_add_shutdown_job` would run it while the worker is alive | DEFERRED (residual) |
| C-LOW-1 | LOW | C | Weak oracle | test (b) did not read the row back | FIXED (row count assert) |

Verdicts: A = SHIP, B = SHIP (MED pre-existing, fixed anyway), C = FIX-REQUIRED (C-MED-1) → fixed.

## Orchestrator independent verification

Per-site source mutation (scratch edit, restored with `cmp` identical):
- `_db` is_stopping guard → `and False`: fast-fail test hangs (SIGALRM at 30 s).
- `_db` worker-not-running half → `True or ...`: 2 tests fail (live worker writes).
- `log_census` early return removed: no-ERROR anchor fails; worker clause removed: alive-write test fails.
- worker `except CancelledError` branch removed: mid-write cancel test fails (caller hung).
DB test files together: 44 passed.

## Summary

| Severity | Found | Fixed | Deferred/accepted |
|---|---|---|---|
| MEDIUM | 2 | 2 | 0 |
| LOW | 4 | 2 | 2 |
| info | 2 | 0 | 2 |

Bug classes: unresolved future on cancellation (new candidate for QUALITY_CONTEXT —
"cancellation bypasses `except Exception`, leaving a paired future unresolved"),
#62 missing anchor, log noise.
