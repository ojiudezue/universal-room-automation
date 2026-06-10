# Code Review — B4 Live-Health Repairs

**Branch:** `feature/b4-live-health` (8484844 build → 5e6caf5 fix-up)
**Protocol:** Tier 2 (2 disjoint reviews). **Date:** 2026-06-10

## Root causes (build)
- (a) `energy_grid_demand` permanently unavailable: `available` gated on the never-enabled EV Grid Import Cap option → no path to availability on this install. Fixed: gate dropped; unknown + `unconfigured_reason` attr instead.
- (b) Occupancy-weighted switch persistence: VERIFIED SOUND (RestoreEntity replay + ready-signal + retry timers); 2026-06-09 flip = one-off; locked with round-trip tests.
- (c) `predicted_energy_today` negative: `db.predict_energy` legitimately returns net (import − export); consumer-facing sensor clamped ≥0 with signed `raw_net_kwh` attr; cost sensors stay signed (export credit).
- (d) 3 orphaned DB circuit baselines: SKIPPED (no bounded-prune DAO; no new DB machinery for cosmetics).

## Findings ledger
| ID | Sev | Finding | Status |
|---|---|---|---|
| B-H1 | HIGH | OLD mirror tests (test_v4_6_12_aggregator_sensors.py:607-621) still locked the PRE-fix availability contract via a hand-copied stub — suite documented two contradictory contracts | FIXED (5e6caf5) — stub + tests realigned, drift pointer comment added |
| A-H1 / B-M1 | HIGH/MED | New round-trip tests were hand-rolled mirrors, not production-path | FIXED — drive real `_ec_switch_factory` restore logic (AST-extract + exec of production source + bare instance; sys.modules isolation fixture) |
| A-M1 / B-M2 | MEDIUM | Clamp asymmetry: Week/Month stayed signed while Today clamped — new dashboard contradiction | FIXED — clamp + `raw_net_kwh` across the family |
| A-M2 / B-L2 | MEDIUM | Exception-guard + branch-order divergence between native_value and attrs on grid-demand | FIXED — aligned |
| A-L1 | LOW | Dead `energy_coordinator_unavailable` reason branch | FIXED — removed |
| A-L3 | LOW | Docstring line-number citation | FIXED — symbol reference |
| B-L1 | LOW | Relative open() cwd assumption in test | ACCEPTED |

**Verified clean:** zero in-repo consumers of either entity's state; recorder-safe unknown (no stats spam; state_class kept); clamp consistent across state/value/display attrs; no new timers/subscriptions/DB writes.

## Statistics
HIGH 2/2 fixed · MEDIUM 3/3 fixed · LOW 4 (2 fixed, 2 accepted). Suite: 5529/44/14/29 — baseline +17, zero new failures.

## QUALITY_CONTEXT note
Mirror-test drift (a stub copying production logic, then production changes) produced two green suites asserting OPPOSITE contracts — reinforce: stubs of production bodies must carry a drift pointer and be updated in the same diff that changes the production body.
