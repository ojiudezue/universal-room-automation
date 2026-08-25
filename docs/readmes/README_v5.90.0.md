# v5.90.0 — HVAC short-cycle anomaly producer (HVAC-ANOMALY-BLIND-1)

**Cards shipped:** `HVAC-ANOMALY-BLIND-1`
**Tier:** 2-DB (shared primitive — `AnomalyDetector` consumed by 6 coordinators; de-suppresses a metric that feeds worst-severity + notifications).
**Branch:** `feature/hvac-shortcycle-producer` @ `d332c3b` (superset of the initial build `1f4d36325`).

## What this ships

The HVAC anomaly detector declared a `short_cycle_rate` metric that was **never produced** — the detector reported "nominal" while blind on it. This wires up the producer end to end:

- **D2 — event-driven producer.** A per-zone short-cycle counter driven by `async_track_state_change_event` on each zone's `climate_entity` (NOT the 5-minute poll — the D0 probe showed the poll cadence would miss the sub-10-min cycles the metric exists to detect). A completed on-cycle shorter than `SHORT_CYCLE_THRESHOLD_S` (600s) increments the per-zone LOCAL-day counter; the daily count is emitted once per zone at the local-day rollover via `record_observation`. Restart-safe: the counter + its date persist via `hvac_zone_state`; the in-flight `on_since` is reset on restart (a truncated cycle is discarded, never counted).
- **D1a — per-metric maturation gate.** `AnomalyDetector` gains `minimum_samples_by_metric`; `short_cycle_rate` matures at `HVAC_SHORT_CYCLE_MIN_SAMPLES=14` (≈2 weeks at 1 obs/day/zone) instead of the global 336, so it can actually fire. Threaded through all four gate read-sites; the top-level scalar `minimum_samples` is preserved for existing dashboards and the per-metric entry now also carries its own gate.
- **D1b — scope-aware surfaces.** The zone-scoped metric is visible per-zone in `get_status_summary` / `get_learning_status` (nested `scopes`), with no create-on-read of phantom house baselines.
- **D1c — filtered clear.** New `clear_active_anomalies_filtered(metric_name=, scope=)`; the zero-arg `clear_active_anomalies` is unchanged.
- **De-suppression.** `short_cycle_rate` removed from `HVAC_SUPPRESSED_FROM_PERSISTENCE`, so a fire now reaches `get_worst_severity()`, the HVAC anomaly sensor, and the notification path.

## Calibration (D0 probe, recorder-event fidelity, 8-day window)

Per-zone daily sub-600s cycle counts: z1 mean 0.62/std 0.86, z2 1.12/1.27, z3 1.38/1.22. Fault-day separation is clean (worst-normal z 1.3–1.6 vs fault(8) z 5.4–8.6), so Option (c) holds with margin. Full analysis: `docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md`.

## Review

Tier-2-DB, three framing-disjoint code reviews (A data-integrity / B async-lifecycle / C test-authority). Findings fixed in one consolidated pass: clear-before-record ordering, the `unavailable`/`unknown` climate-state guard (was a missed deliverable — a WiFi blip would otherwise fabricate a phantom short cycle), the callback double-emit removed (decision-tick is the sole rollover path), the ctor wire-in anchored by a mutation-verified test (C-CRITICAL-1), the de-suppression test re-pointed at the real frozenset, plus the multi-day-gap and detector-None guards. The load-bearing sites are mutation-anchored (each bites its named test). Full-suite name-diff vs develop: **0 new regressions** (61 baseline preserved under the standard order; C's order-matched `comm` diff empty on the superset-parent).

## Acceptance criteria

- **Verify:** the restart guard gates on the persisted `_short_cycles_today_date`, not the RAM-only `_last_daily_reset` — a mid-day restart emits ZERO observations and preserves the counter (`test_short_cycle_producer_midday_restart_does_not_emit_partial_day`).
- **Verify:** an `unavailable`/`unknown` climate state drops `on_since` and never counts a phantom cycle.
- **Verify:** the ctor wires `minimum_samples_by_metric={"short_cycle_rate": 14}` (mutation-anchored).
- **Live (post-restart):** `short_cycle_rate` appears per-zone in the HVAC anomaly detector's learning status with `minimum_samples=14`, `sample_count` starting to accrue (one per local day per zone). It should read NOT-yet-mature for ~14 days, then begin scoring. No spurious ADVISORY/CRITICAL from the metric in the first days.
- **Live (~14 days):** first real scoring; a genuine short-cycling day (≥ the fault threshold) raises the HVAC anomaly sensor's worst severity and fires NM — while normal days stay nominal.

## Post-deploy validation (write-back — TO BE COMPLETED after restart)

_Replace this section with a `Validated <date>` results table once the restarted instance is read: confirm `short_cycle_rate` is registered per-zone at minimum_samples=14, accruing, and not spuriously firing. Note that full scoring only proves out after the 14-day maturation, so the day-0 check is registration + accrual + no-false-fire, not detection._
