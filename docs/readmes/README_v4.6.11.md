# URA v4.6.11 — D3 Anomaly Persistence + LOW Polish + Dashboard Attribute Adds

**Released:** 2026-05-19
**Tier:** Tier 2-DB (user-escalated for dashboard prep cycle)
**Branch:** `feature/v4.6.11-d3-persistence-and-attrs`

## Summary
First of three Python cycles preparing the URA Dashboard v5.0 for live data wiring. Bundles three deliverables into one cycle:

1. **D1 — CM anomaly persistence wired in.** The metric_baselines table and `AnomalyDetector.load_baselines / save_baselines` already existed; Coordinator Manager was the last detector not hooked into the persistence pattern. CM now loads baselines on `async_start`, saves after every observation (intentional cadence divergence — setup_duration fires once per boot; teardown-only save would lose the observation on crash), and dispatches the resulting AnomalyEvent through `store_event` so the row lands in `anomaly_log` and the activity_logger audit trail.

2. **D2 — LOW carryovers from v4.6.10.** `datetime.utcnow()` → `dt_util.utcnow()` at three call sites in `coordinator_diagnostics.py` (bug class #21). Deprecated asyncio cleanup in v4.6.10's setup-telemetry tests.

3. **D4 — Dashboard attribute adds (Cycle A).** Ten new attributes across existing sensors plus one new `SafetyEventsSummarySensor` entity. All read from authoritative in-memory state — no new DB read paths in `extra_state_attributes`. None-vs-zero handling audited per bug class #7.

## Review ceremony
Three parallel staff-engineer reviewers (Reviewer A: data integrity + DB architecture preservation, Reviewer B: migration correctness + signal chain integrity, Reviewer C: new surfaces + test fixture authority). Findings landed across 2 CRITICAL + 4 HIGH + 6 MEDIUM + 5 LOW. All CRITICAL/HIGH/cheap-MEDIUM/cheap-LOW fixed this cycle (16 of 17 actionable). Deferred items documented in `docs/reviews/code-review/v4.6.11_d3_persistence_and_attrs.md`.

## Notable fixes from review

- **C1 — Listener leak** (`SafetyEventsSummarySensor`): missing `super()` in `async_will_remove_from_hass` was leaking `AggregationEntity._agg_retry_unsub` (bug class #38).
- **C2 — Untracked async task from sync property** (`SafetyEventsSummarySensor.native_value`): refresh tasks now tracked + re-entry-guarded + cancelled in teardown (bug class #19).
- **A.H1/C.H3 — Read through write queue** (`SafetyEventsSummarySensor._refresh_cache`): `_db()` → `_db_read()` so the 60s-cadence SELECT no longer blocks real writes (bug class #26).
- **A.M1 — `active_count` consistency** (`manager.get_summary`): uses `_persisted_active_anomalies()` so suppressed metrics no longer inflate the count beside a "nominal" status.
- **A.M3 — `house_state` in CM anomaly payload**: analytics queries grouping `anomaly_log` by `house_state` now include CM rows.

## Test status
- 0-delta vs baseline `pre-review-v4.6.11` (57 failed, 3318 passed, 14 errors, 2 skipped — all pre-existing).
- 60 of 61 new v4.6.11 tests pass; 1 skip (HA-stack-dependent path).
- v4.6.10 setup-telemetry suite unchanged (38 passed, 0 failed).

## Files touched (build + review fixes)
- `custom_components/universal_room_automation/__init__.py`
- `custom_components/universal_room_automation/aggregation.py`
- `custom_components/universal_room_automation/binary_sensor.py`
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py`
- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `custom_components/universal_room_automation/domain_coordinators/manager.py`
- `custom_components/universal_room_automation/sensor.py`
- `quality/tests/test_v4_6_10_setup_telemetry.py`
- `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py` (new)
- `quality/tests/test_v4_6_11_dashboard_attrs.py` (new)
- `docs/reviews/code-review/v4.6.11_d3_persistence_and_attrs.md` (new)

## Live-validation acceptance
Post-restart, within 30 minutes:
1. `metric_baselines` contains row for `(coordinator_manager, setup_duration_seconds, house)` with `sample_count >= 1`.
2. `sensor.ura_safety_events_summary` loads and returns an int.
3. CM summary sensor `health_status` ∈ `{green, orange, red}`.
4. CM summary sensor `status_per_coordinator` is a dict with `{status, active_anomalies, enabled}` per registered coordinator.
5. Anomaly_log row for `coordinator_manager` (if anomaly fired) populates `house_state` column.

## What's next
- **v4.6.12 — Cycle B aggregator sensors** (ZoneMotionEventCountSensor, HouseSystemDemandSensor, EnergyGridDemandSensor)
- **v4.6.13 — Cycle C coordinator telemetry** (override frequency via compliance_log, success rate via compliance_log)
- **Dashboard v5.0 — D3-D7 live wiring** once Cycle A/B/C sensors land
