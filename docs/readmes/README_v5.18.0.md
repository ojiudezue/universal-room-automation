# URA v5.18.0 — Consumption Estimator v1 (Shadow) + Projection Unification + Storm-Precharge Exempt-Bounded

**Date:** 2026-07-16
**Tier:** 3 (two Tier-3 cycles + one reviewed carry-over) — review records:
`docs/reviews/code-review/r1_consumption_estimator_tier3.md`,
`docs/reviews/code-review/r7_projection_unification_tier3.md`,
`docs/reviews/code-review/v5_17_6_storm_precharge_exempt_bounded.md`
**Commits:** `cfcd7573` (v5.17.6 carry-over), `db1fcf5e`+`799854e5` (R1), `ec60f1e2`+`a305928b` (R7)

## What ships

### 1. Storm precharge: exempt from blind freeze, bounded (behavioral — operator-ratified)
Inclement storm precharge may now proceed on degraded (cloud-fallback) telemetry
if the SOC reading is <30 min fresh, instead of being refused outright while
blind. Closes v5.17.5 D-HIGH-2: a storm window arriving during a telemetry
outage could previously leave the battery under-charged going into the outage.
The 30-min freshness bound only refuses corpses (verified in review).

### 2. R1 — Consumption estimator v1, SHADOW MODE (inert by proof)
- New estimator: base temperature/season regression (fit on 2025 EV-free era;
  CDD/HDD base 65°F + season offsets) + single EV term 18.58 kWh/day gated on
  `EV_ERA_START=2026-03-01`. Constants: `CONSUMPTION_REGRESSION_V1`
  (energy_const.py, rung-1 reviewed constant; re-fit requires review).
- Holdout (2026-05-01..07-15): MAE 16.06 kWh (invariant ≤20 PASS). Replaces-in-
  shadow the day-of-week estimator measured at R²=−1.55 live (B0 probe).
- `CONF_R1_ESTIMATOR_SHADOW_ONLY=True`: every decision consumer (battery
  strategy, DPM, pre-cool, EVSE, sensors) still reads the LEGACY value —
  proven by Review D across the full consumer enumeration. v1 is recorded to
  `energy_daily.predicted_consumption_source` (additive column) + shadow attrs.
- Reproducible offline fit: `scripts/energy/fit_consumption_regression.py` +
  `data/energy_fit/` (byte-identical re-run verified by Review A).
- R2-flip prerequisite (named, in constant docstring): reset/exempt
  `_adjustment_factor` before flipping shadow off (D-MED-1).

### 3. R7 — Projection unification (inert by proof)
- 5 SOC-at-boundary projection sites (rung-0, rung-1 counterfactual, rung-1
  entry, attain entry, attain hold-current) unified behind
  `EnergyProjector.project_soc_at_boundary` (new energy_projector.py).
- Byte-identical outputs proven: exact-equality parity tests vs independent
  reimplementations of pre-R7 source; hand-verification of all 5 sites by two
  reviewers; zero full-suite delta. Attain sites deliberately consume the
  UNCLAMPED value (faithful to pre-R7); rung sites the clamped (v5.17.4).
- Kill switch `R7_USE_UNIFIED_PROJECTOR` (module constant): flip False →
  verbatim inline fallbacks at all 5 sites (M8 mutation-verified green).
- AST-based singleton guard across ALL domain_coordinators (fix-up): a second
  projection implementation in any coordinator now fails CI, including renamed
  spellings (self-tested against two executed evasions).

## Review outcome summary
Both Tier-3 cycles: A/B/D SHIP on first pass; C (mutation execution)
FIX-FIRST both times — R1: self-referential arithmetic tests + silent-NULL DAO
marker (2 HIGH, fixed); R7: cosmetic singleton guard + unpinned raw-vs-clamped
attain wiring (2 HIGH, fixed). 18 mutations executed RED across both cycles;
orchestrator independently re-executed one mutation per cycle (both RED,
restores byte-identical).

## Live Validation — Validated 2026-07-16 (restart 17:10 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, zero URA ERRORs | PASS | error_log filtered `universal_room_automation` level=ERROR → 0 lines at 17:16 (6 min post-boot). All boot WARNINGs known-transient classes (sensor-unavailable holds, camera census warm-up). |
| No `energy_projector`/`energy_forecast` errors | PASS | Zero log hits for either module. |
| Battery strategy sensor live with sane attrs | PASS | `sensor.ura_energy_coordinator_battery_strategy` updated 17:13: `target_day_class=good`, `peak_buffer_target=80`. Projection attrs null — as-expected during PEAK (ladder only runs in charge windows; identical pre-R7). Populated-projection check deferred to tomorrow's ~11:00 window (Shipwatch H2). |
| Peak hold behavior intact (I-AH1/freeze family) | PASS | Reserve 79 vs Envoy SOC 83 at 17:13 — freeze-at-SOC tracking through peak, same behavior as pre-deploy trace. |
| v5.17.5 degraded-decide exercised organically | PASS (bonus) | Boot log 17:10:52: "SOC primary+LKG unavailable — using cloud fallback 85.5%" — degraded tick decided normally while Envoy warmed up; no blind freeze. |
| v5.17.6 storm precharge | as-expected (dormant) | No active NWS alert; inclement attrs present (`inclement_reserve_floor=10`), no regression. Code path awaits a real storm window. |
| R1 shadow marker in `energy_daily` | PENDING (by design) | Row written at daily rollover; NOT-NULL `predicted_consumption_source` check due within 48h (2026-07-18). |

Boot-only transients dismissed: strategy sensor state `unknown` for first
minutes while attrs populate (pre-existing pattern); Envoy entity
registry-known-no-state warning (device recovering; EC degraded gracefully
per design).

**14-day R1 shadow clock started 2026-07-16.** R2 build gated on observed
shadow MAE + the 48h marker check + D-MED-1 (`_adjustment_factor` reset)
prerequisite.
