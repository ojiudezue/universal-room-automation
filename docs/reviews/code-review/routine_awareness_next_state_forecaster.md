# Code Review — Routine-Awareness Next-State Forecaster

**Branch:** `feature/routine-next-state-forecaster` (a69dfc9 build → 0d9fba9 fix-up)
**Plan:** `docs/planning/PLANNING_routine_awareness_next_state_forecaster.md`
**Protocol:** Tier 2 — two framing-disjoint reviews + independent validation + main-session spot-checks.
**Pre-review tag:** `pre-review-routine-forecaster`
**Date:** 2026-06-09/10

## Review framings

- **A — Model correctness + edge cases + vocabulary collapse** (1 CRITICAL, 1 HIGH, 2 MEDIUM, 2 LOW)
- **B — Lifecycle + DB-read budget + boot/restart resilience + subscription hygiene** (3 MEDIUM, 3 LOW)

Disjoint framings converged independently on exactly one finding (the LIMIT
direction) and otherwise surfaced non-overlapping defects — the framing split
worked as intended.

## Findings ledger

| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| A-1 | CRITICAL | `house_state_log` stamps are naive UTC; `_parse_ts` routed them through `dt_util.as_utc` (naive=local) → every aggregation cell shifted by the local UTC offset (21:00 CDT trained the 02:00 bin); cascade masked it with confident-but-wrong coarse cells. Test stub encoded naive=UTC (opposite of HA), so the suite could not catch it. | #7 wrong data source + test-stub semantics drift | FIXED (0d9fba9) — naive stamps get `tzinfo=timezone.utc` attached BEFORE any conversion (as_utc naive branch never engages — verified writer at database.py:1996 + parser end-to-end in main session); stub corrected to real HA semantics; regression test (02:00Z → evening bin) added |
| A-2 / B-2 | HIGH | `fetch_house_state_log_since` `ORDER BY timestamp ASC LIMIT 5000` keeps the OLDEST rows on overflow — one flap storm freezes the model on stale data permanently | #7 | FIXED — DESC + reverse-in-Python; newest-kept test added |
| A-M1 | MEDIUM | Self-loop rows (away→away restart artifacts) inflate cell denominators, deflating real-prediction confidence | Model correctness | FIXED — skipped in refresh walk + incremental update; 2 tests |
| A-M2 | MEDIUM | Restart-spanning dwell attributed HA downtime to the prior state, inflating ETA medians | Model correctness | FIXED — ETA samples >12h dropped (`ROUTINE_FORECAST_MAX_DWELL_SECONDS=43200`); count still increments; test added |
| B-1 | MEDIUM | Startup DB refresh ran inside `async_setup` during the cold-boot window (plan said defer past boot-settle; post-incident discipline) | Boot-storm discipline (v4.7.21 lineage) | FIXED — idempotent `async_trigger_initial_refresh()` scheduled on settle release, interval-tick backstop; 2 tests |
| B-3 | MEDIUM | Re-entrant `async_setup` unconditionally overwrote `_routine_forecaster`, orphaning the prior instance's timer + dispatcher sub (double reads/increments) | #19 untracked background tasks / reload race | FIXED — prior instance shut down + cleared before re-create; test added |
| B-4 | LOW | Function-local `from datetime import timezone` | #34 watch-list | FIXED — hoisted module-level |
| A-L1 / B-L5 | LOW | Transitions arriving during a refresh's DB await are lost on the swap | Self-heals next hourly refresh | ACCEPTED — documented |
| A-L2 | LOW | Cross-source `_last_row_ts` mixed shifted/true timestamps | Falls out of A-1 | RESOLVED by A-1 fix |
| B-L6 | LOW | Boot-settle suppresses signal increments during cold boot | By design (output also gated) | ACCEPTED |

## Verified clean (both reviewers + main session)

Zero new DB writes (read-only `_db_read` SELECT, indexed by `idx_house_state_timestamp`);
#50-immune (unsubs on dedicated attrs, never in `_unsub_listeners`); teardown ordering +
idempotent shutdown; build-new-then-swap aggregation (atomic on loop); vocab table
exhaustive over all 9 HouseState members, outputs ⊆ `_NextStateVocab`; second-place
rule terminates, all-same-vocab → honest unknown; ETA from pre-collapse argmax
histogram per plan; confidence clamped and from the cell actually used; guest/vacation
passthrough + aggregation exclusion; settle gate read live per-call (#14); signal
payload keys match dispatch; PWA contract keys unchanged.

## Summary statistics

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| CRITICAL | 1 | 1 | 0 |
| HIGH | 1 (dedup of 2 reports) | 1 | 0 |
| MEDIUM | 4 | 4 | 0 |
| LOW | 5 | 1 | 3 (1 resolved by A-1) |

**Suite:** 5459 passed / 44 failed / 14 errors / 29 skipped — +27 cycle tests total,
zero new failures, suite-minus-new-file at exact pre-existing baseline (pollution
check clean).

## QUALITY_CONTEXT.md recommendations

1. **Naive-timestamp discipline:** `database.py` writers using `datetime.utcnow().isoformat()`
   produce naive stamps that CANNOT be safely round-tripped through `dt_util.as_utc`
   (naive=local in HA). Any reader of URA DB timestamps must attach UTC explicitly.
   Candidate bug-class note under #7 — there are other `utcnow().isoformat()` writers
   in database.py; readers elsewhere should be audited opportunistically.
2. **Test-stub fidelity:** a stub of an HA util must mirror HA's actual semantics
   (the A-1 stub encoded the inverse and certified the bug). When stubbing
   `dt_util`, copy the naive-handling branch faithfully.
