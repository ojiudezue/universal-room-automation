# URA v4.6.11 — D3 Anomaly Persistence + LOW Polish + Dashboard Attribute Adds

**Released:** 2026-05-19
**Tier:** Tier 2-DB (user-escalated dashboard prep)

## Summary
First of three Python cycles preparing the URA Dashboard v5.0 for live data. CM hooked into existing `metric_baselines` persistence, anomaly events flow through `store_event` + activity_logger. 10 sensor attributes added for dashboard prep. New `SafetyEventsSummarySensor` entity. Three carryover `datetime.utcnow()` fixes.

## Review ceremony
3x parallel reviewers. 2 CRITICAL + 4 HIGH + 6 MEDIUM + 5 LOW. 16 of 17 actionable fixed this cycle. See `docs/reviews/code-review/v4.6.11_d3_persistence_and_attrs.md`.

## Notable fixes
- C1: SafetyEventsSummarySensor teardown missing super() (#38)
- C2: untracked async task from sync property (#19)
- A.H1/C.H3: `_db()` → `_db_read()` (#26)
- A.M3: house_state added to CM anomaly payload

## Tests
0-delta vs baseline (57 failed, 3318 passed — all pre-existing). 60 of 61 new v4.6.11 tests pass.
