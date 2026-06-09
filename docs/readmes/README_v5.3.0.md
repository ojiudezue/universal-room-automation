# URA v5.3.0 — Optimization Coordinator Phase 4 (Prediction-Validation) + Bayesian room-surface cleanup

**Release date:** 2026-06-09
**Tier:** Tier 2-DB (new house-level dimension reading prediction-accuracy substrate) + a hygiene removal.
**Builds on:** v5.2.2 (write-flood remediation, live-validated). Optimizer still ships **L1 Shadow** (no actuation).

## Headline Changes

### Phase 4 — Prediction-Validation pillar (read-only)
- New **house-level `PREDICTION_ACCURACY` dimension** (`_evaluate_prediction_accuracy_dimension`) — strictly READS existing accuracy surfaces, no new learner, no reimplemented math:
  - Next-room top-1 hit-rate + Brier (from `prediction_results`, mirroring `HouseNextRoomAccuracySensor`) — the audited-SAFE primary surface.
  - `BayesianPredictor.get_accuracy_stats()` occupancy Brier — the PROVISIONAL surface (handled as possibly-empty; never flags off missing data).
  - `quality_report` data-quality %.
- Flags **advisory** findings (proposed_action=None) when prediction quality degrades past sane floors (top-1 < 35%, Brier > 0.30, data-quality < 80%). **House-level only** — not per-room (keeps cycle row-count low; the incident lesson).
- **False-alarm guards:** an under-learned gate (≥50 samples required) and a learning-suppressed gate (guest-mode pauses learning) prevent drift alarms during warm-up or suppression. Confidence scales with sample volume.
- `DailyEnergyPredictor` accuracy **deferred** — no clean in-process hit-rate/Brier surface today; not fabricated.
- The evaluator's findings flow through the **shared batched persist** (v5.2.2) — the write-volume regression test still passes with the new dimension active.

### Bayesian room-surface cleanup (operator-approved kill-list: "remove 2 only")
- Removed two dead per-room single-time-bin sensors: `BayesianWeekdayMorningProbSensor` (`*_bayesian_weekday_morning_prob`) and `BayesianWeekendEveningProbSensor` (`*_bayesian_weekend_evening_prob`). They were hardcoded single-bin sensors superseded by the kept forecast/pattern sensors, **disabled-by-default DIAGNOSTIC with no `SensorStateClass` → zero LTS history lost.** The `BayesianPredictor` engine + the kept accuracy/quality/next-room sensors are untouched. Audit confirmed the engine is healthy (97% data quality, 48 belief cells, 35 rooms).

## Validation
- 96/96 optimizer tests pass (6 new Phase-4 tests). Full suite 5383 passed / 44 failed / 14 errors (baseline parity).

## Live Validation (Review D) — post-restart
- **Verify:** no write-queue saturation (the v5.2.2 invariant holds — zero `DB write worker did not process within 35s`).
- **Verify:** the `prediction_accuracy` dimension reads the Bayesian surfaces without error; emits a house-level advisory only when accuracy is genuinely degraded with enough samples (no false alarm during boot warm-up).
- **Verify:** the two removed Bayesian sensors are gone; the kept ones (`bayesian_data_quality`, `house_next_room_accuracy`, `*_likely_next_room`, occupancy_anomaly) still report.
- **Verify:** optimizer `mode=shadow`; no `optimization` errors.

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |
