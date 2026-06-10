# Code Review — Prediction-Sensor Kill-List

**Branch:** `feature/prediction-sensor-kill-list` (f59f414 build → 590de17/961c263/fcadab6 fix-ups)
**Protocol:** Tier 2 (2 disjoint reviews). **Date:** 2026-06-10

## What shipped
- `PeakOccupancyTimeSensor` deleted (~37 rooms; superseded 1:1 by `bayesian_occupancy_pattern`).
- `NextOccupancyInSensor` deleted (~50k recorder writes/day of per-minute countdown churn; info now derived client-side).
- `NextOccupancyTimeSensor` refit: `device_class=timestamp`, tz-aware native_value, writes only when timestamp/confidence/availability changes.
- Registry orphan cleanup (one-shot, v4.7.22 precedent) for both removed unique_id families.
- Legacy pattern-learner model UNTOUCHED (model swap = future cycle).

## Findings ledger
| ID | Sev | Finding | Status |
|---|---|---|---|
| A-H1 / B-B1 | HIGH | Only-on-change override was the sole state writer → availability flips (refresh failing with retained data) never reached the state machine; stale timestamp shown available indefinitely, recovery unsignaled | FIXED (961c263) — availability in the change tuple (3rd sentinel) + flip/recovery regression test |
| A-M1 / B-B2 | MEDIUM | `_normalize` naive branch stamped UTC and its docstring fabricated the `as_utc` convention (naive=local in HA) — dormant (sole producer tz-aware) but the exact forecaster-cycle bug class | FIXED — naive routed through `dt_util.as_utc` (naive=local); test installs a faithful as_utc stand-in when the suite mock lacks it, with wall-clock proof (fcadab6) |
| A-M2 / B-B3 | MEDIUM | Behavioral tests skip standalone (run+pass in every full-suite run — the protocol gate; bare-instance technique is order-immune, coverage is order-dependent) | ACCEPTED — documented; full-suite is the gate |
| A-L3 | LOW | Confidence attr double-scaled — DAO returns 0-100, attr multiplied ×100 → "8000%" | FIXED (961c263) |
| B-L4 | LOW | `UTC = timezone.utc` wedged in the import block | ACCEPTED (other users in file; naive branch no longer uses it) |
| A-L1 / B-L5 | LOW | coordinator.py still computes the dead STATE_NEXT_OCCUPANCY_IN / PEAK values each cycle; const keys orphaned | DEFERRED — model-swap cycle sweep |
| A-L2 / B-L6 | LOW | Stale-named pure-math test; unused test imports | imports FIXED; stale name ACCEPTED |

**Verified clean (reviewers):** cleanup unique_id pattern matches entity.py:30 (removal actually hits); one-shot flag reload-loop-safe (#46) and idempotent on flag-write failure; live producer tz-aware local (no live countdown bug); zero in-repo consumers of removed entities; identical-value writes do hit recorder (suppression = real savings — live-validate); LTS clean (no state_class on any of the three).

## Statistics
HIGH 1/1 fixed · MEDIUM 2 (1 fixed, 1 accepted) · LOW 5 (2 fixed, 3 accepted/deferred). Suite: 5521/44/14/29 — baseline-exact, zero new failures; behavioral tests pass in-suite, skip solo (never fail).
