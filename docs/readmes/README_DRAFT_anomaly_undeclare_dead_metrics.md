# README DRAFT: Undeclare two dead anomaly metrics (ANOMALY-METRIC-DISPOSITION-1, slices a + b)

Branch `fix/anomaly-undeclare-dead-metrics`. Tier 1. Not deployed. Version number goes on at deploy time.

## Problem

Two anomaly metrics were declared but had no producer:

- HVAC `egress_pause_frequency` was reserved in v4.7.8 (fix-up C-M1). The producer was never built, and egress pauses are too rare to form a z-score baseline.
- Security `entry_anomaly_score` has been declared since v3.6.0 with no producer. The entry verdicts it would have scored already feed `alert_trigger_frequency`.

Since v5.103.25, a declared metric with no data counts as blind (`not_wired`). Both coordinators' anomaly sensors therefore read `partial` with no way out. Each metric also left a phantom `metric_baselines` row (`sample_count = 0`, `last_updated` NULL). See `docs/planning/PLANNING_anomaly_detector_blind_metrics.md` §3, which recommends "undeclare; the orphan prune cleans the row".

## Fix

- `hvac_const.py`: `egress_pause_frequency` is removed from `HVAC_METRICS`, `HVAC_SUPPRESSED_FROM_PERSISTENCE` and `HVAC_UNWIRED_METRICS`. `comfort_deviation_hours` stays declared as unwired; its producer card is HVAC-COMFORT-DEVIATION-PRODUCER-1.
- `security.py`: `entry_anomaly_score` is removed from `SECURITY_METRICS`. `SECURITY_SUPPRESSED_FROM_PERSISTENCE` and `SECURITY_UNWIRED_METRICS` stay defined, now empty, because the Security ctor and the meta-tests import them. The METRIC AUDIT docstring is updated.
- There is no DB code change. The existing orphan prune in `AnomalyDetector.load_baselines` (`coordinator_diagnostics.py:1660-1749`) skips rows whose metric is not in `metric_names` and deletes them in one batched DELETE. HVAC (`hvac.py:1842`) and Security (`security.py:795`) both call it at setup, so the first boot removes the two phantom rows.

## Tests

- New `quality/tests/test_anomaly_undeclare_dead_metrics.py`, 6 tests:
  - the names are absent from the declarations;
  - a real `AnomalyDetector` built from each coordinator's declared constants over a real `UniversalRoomDatabase` prunes the removed metric's seeded row and keeps a live metric's row;
  - coverage, blind map and `metrics_unwired` no longer name the removed metrics.
- Updated `test_anomaly_coverage_ctor_wiring.py`: the security probe metric is now `alert_trigger_frequency`, and the expected declarations are updated.
- Removed two source-grep tests whose subject no longer exists. Each file carries a comment pointing at the replacement:
  - `test_v465_observability_gap.py::test_security_metrics_entry_anomaly_score_suppressed`
  - `test_v478_egress_window.py::test_v478_fixup_C_M1_egress_pause_frequency_in_suppressed_set`
- Mutation drill:
  - Re-adding `egress_pause_frequency` to `HVAC_METRICS` turns 3 named HVAC tests RED.
  - Re-adding `entry_anomaly_score` to `SECURITY_METRICS` turns 3 named Security tests RED.
  - Both files were restored afterwards and `git status` was clean.

## Live acceptance (after restart)

- The Security anomaly sensor (`sensor.ura_security_coordinator_*` anomaly) no longer lists `entry_anomaly_score` in `metrics`, `metrics_blind` or `metrics_unwired` (`metrics_unwired == []`). Expected state: `nominal`, with `alert_trigger_frequency` annotated in `metrics_constant`, unless a persisted non-LOW severity exists.
- In `sensor.ura_hvac_coordinator_hvac_anomaly`, `metrics_unwired == ["comfort_deviation_hours"]` and `metrics_blind` has `comfort_deviation_hours: not_wired`. `egress_pause_frequency` appears nowhere.
- DB: `SELECT COUNT(*) FROM metric_baselines WHERE metric_name IN ('egress_pause_frequency','entry_anomaly_score')` returns 0.
- Log: one INFO "Pruning N orphaned baseline row(s)" each for hvac and security on the first boot, and no ERROR/WARNING lines from the anomaly detector.
