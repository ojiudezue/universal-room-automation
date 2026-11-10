# v5.108.6: Lock retry cap, optimizer meta never pages, dead anomaly metrics removed

Cards shipped: `SECURITY-LOCK-SWEEP-RETRY-CAP-1`, `OPTIMIZER-META-NEVER-PAGES-1`, `ANOMALY-METRIC-DISPOSITION-1` (slices a + b).

Built and reviewed overnight 2026-11-04 to 11-08 on `integ/overnight-2026-11-08`, re-based onto v5.108.1 as `integ/overnight-2026-11-10`, and merged into develop on 2026-11-10 after v5.108.5 (no conflicts). Each fix is Tier 1 with one review, plus a merge review for the retry cap. This release folds in the three per-fix drafts (`README_DRAFT_security_lock_retry_cap.md`, `README_DRAFT_optimizer_meta_never_pages.md`, `README_DRAFT_anomaly_undeclare_dead_metrics.md`), which hold the full detail.

## 1. Periodic lock check stops retrying forever (SECURITY-LOCK-SWEEP-RETRY-CAP-1)

**Problem:** the security sweep (`_evaluate_lock_check`) re-sent `lock.lock` / `cover.close_cover` on every interval while a lock stayed unlocked or the garage stayed open, even when the command never took (46 lock commands on 2026-03-11, nearly all followed by `unlocked` again; `docs/planning/AUDIT_security_sweep_and_mopup.md`).

**Fix:** each device gets a retry episode. At most `SECURITY_LOCK_RETRY_CAP` (3) commands, then URA stops and sends one security notice: "<device> did not lock/close after 3 tries". The episode ends only when the device is seen `locked` / `closed`; transient states continue it. A fresh episode starts after `SECURITY_LOCK_RETRY_REARM_S` (24 h). Jammed locks are still never commanded; observation mode counts nothing; never-auto-lock devices skip the cap; episodes are in memory (a restart starts fresh). `sensor.ura_security_coordinator_security_last_lock_sweep` gains `retry_capped`.

Constants (`const.py`, rung 1): `SECURITY_LOCK_RETRY_CAP = 3` (0 = no cap, old behaviour); `SECURITY_LOCK_RETRY_REARM_S = 86400` (0 = never re-arm on time).

Not touched: one-shot lockdown actions from alerts, and the garage lockout regime (`security_lock_regime.py`, v5.108.3), which is a separate path.

Reviews: `docs/reviews/code-review/security_lock_retry_cap_review.md` (FIX-REQUIRED, fixed), `security_lock_retry_cap_merge_onto_v5106_review.md` (SHIP).

## 2. Optimizer "meta" findings never page (OPTIMIZER-META-NEVER-PAGES-1)

**Problem:** every 2-3 days the optimizer's AI layer sent a CRITICAL "URA Optimizer — meta" page to every channel, complaining its own input was truncated. 9 of 9 in the 30 days to 11-04, several between 1 and 2:30 am, none about the house.

**Fix:** `_notify_if_severe` (`optimization.py`) returns before paging for dimension META. Findings are still stored and shown in the digest and dashboards. No new knob.

Review: `docs/reviews/code-review/optimizer_meta_never_pages_review.md` (SHIP).

## 3. Two dead anomaly metrics removed (ANOMALY-METRIC-DISPOSITION-1 a + b)

**Problem:** HVAC `egress_pause_frequency` and Security `entry_anomaly_score` were declared with no producer, so each counted as blind and left an empty `metric_baselines` row.

**Fix:** both undeclared (`hvac_const.py`, `security.py`). The existing orphan prune deletes the two empty rows at first boot. Why delete rather than build: egress pauses are too rare for a z-score baseline, and entry verdicts already feed `alert_trigger_frequency` (`PLANNING_anomaly_detector_blind_metrics.md` §3). Its real defect is carded as `SECURITY-ALERT-TRIGGER-METRIC-SHAPE-1`.

Effect: Security's anomaly sensor has no unwired metrics left. **HVAC's still lists `comfort_deviation_hours` as unwired**, so HVAC stays `partial` until `HVAC-COMFORT-DEVIATION-PRODUCER-1` builds that producer.

Review: `docs/reviews/code-review/anomaly_undeclare_dead_metrics_review.md` (SHIP).

## Tests
- `quality/tests/test_security_lock_retry_cap.py`, `test_sc_lock_exclude.py` (retry cap x never-auto-lock)
- `quality/tests/test_optimizer_meta_never_pages.py`
- `quality/tests/test_anomaly_undeclare_dead_metrics.py`; fixture fix in `test_unload_symmetry_shutdown_db_hygiene.py`
- All mutation-anchored (see the drafts).

## Live validation (prospective)
- **Lock cap:** `sensor.ura_security_coordinator_security_last_lock_sweep` has a `retry_capped` attribute (`[]` normally). On the next failed lock/close: at most 3 URA commands, one "did not lock/close after 3 tries" notice, log `Periodic lock check: retry cap (3) reached`.
- **Meta:** no `notification_log` rows titled `URA Optimizer — meta` after the restart.
- **Anomaly:** `SELECT COUNT(*) FROM metric_baselines WHERE metric_name IN ('egress_pause_frequency','entry_anomaly_score')` = 0; `sensor.ura_security_coordinator_security_anomaly` `metrics_unwired == []` (pre-deploy: `partial`, `["entry_anomaly_score"]`); `sensor.ura_hvac_coordinator_hvac_anomaly` `metrics_unwired == ["comfort_deviation_hours"]` (pre-deploy: also `egress_pause_frequency`); one "Pruning ... orphaned baseline" INFO each for hvac and security.
- **Load:** no URA ERROR after restart.
