# Review record — EC-EV-TOGGLE-TRIPWIRE-1 (branch feature/ec-ev-toggle-tripwire)

Overnight autonomous pass 2026-10-05. Tier 1-2 (alert-only, no actuation change) -> two framing-disjoint reviews +
orchestrator verification. Stacked on feature/ec-degraded-data-p1 (unshipped). Build d0d12ad25, fix-up 2300126d8.

| # | Sev | Reviewer | Finding | Bug class | Status |
|---|---|---|---|---|---|
| A-MED-1 / B-LOW-1 | MEDIUM | A + B (converged) | Anomaly latch keyed on LOCAL date, `_maybe_fire_nm` latch keyed on UTC date for the same surface -> a late-evening trip silently suppresses the next local day's NM | Day-boundary-blind latch (clock mismatch between two latches) | FIXED 2300126d8 (`date_key` param, latch from `as_local(now)`) |
| A-MED-2 | MEDIUM | A | Day-rollover test reset both latches by hand -> stayed green with the latch deleted or swapped to UTC | Hollow test anchor (#62) | FIXED (rollover via injected `now` only; exact-repro test; drills RED) |
| A-LOW-1 / B-LOW-3 | LOW | A + B | NM routed with battery metadata (`hazard_type=envoy_write_verification`, `location=battery`) | Mis-scoped metadata | FIXED (optional params, defaults byte-identical) |
| A-LOW-2 | LOW | A | `on_n = sum(1 for _ in arr)` misnamed; jargon in message | Clarity | FIXED |
| A-LOW-3 | LOW | A | No test that dedupe precedes the counter | Untested invariant | FIXED (`test_i_repeated_same_action_counts_once`) |
| B-LOW-2 | LOW | B | In-memory latches reset per restart -> a real flip-flop across N restarts in a day can page N times | Restart-reset state | ACCEPTED (bounded; documented on the constant) |

Cleared by B: always on the event loop (sync tap called after `await services.async_call`), no await between
append and latch set (no double alert), restart alone cannot trip (needs 3 transitions in the window), write
volume negligible, no collision with the battery write-churn latch.

Orchestrator verification: diff read; 11/11 pass; own call-neuter drill on the energy.py wire-in -> 2 tests RED,
restored, porcelain clean.

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 2 | 2 | 0 |
| LOW | 4 | 3 | 1 |

Bug-class frequency: day-boundary clock mismatch 1 (converged by both framings); hollow test 1.
QUALITY_CONTEXT candidate: "two latches for one event on different clocks (local vs UTC)" as a named sub-pattern
of day-boundary bugs — recurs wherever a new caller reuses a UTC-latched helper for an operator-facing day.
