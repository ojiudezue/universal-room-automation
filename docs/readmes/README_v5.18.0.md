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

## Live Validation (prospective — to be replaced with Validated table post-restart)
- **Live:** HA restarts clean; all 40 rooms set up; zero URA ERROR logs
  referencing `energy_projector`, `energy_forecast`, or `predicted_consumption`.
- **Live:** `sensor.ura_energy_coordinator_battery_strategy` still carries
  rung/attain projection attrs (`arb_projection_rung0/1`,
  `attain_projected_soc_at_boundary`) with plausible (≤100 display) values.
- **Live (R1 shadow):** within 48h, at least one `energy_daily` row has
  `predicted_consumption_source` NOT NULL (expected `legacy_dow` while shadow
  on, `v1_regression` in the shadow attrs).
- **Live (v5.17.6):** no storm precharge expected (no alert active); code-path
  dormant — criterion is absence of regression in inclement attrs on
  `sensor.ura_energy_coordinator_battery_strategy`.
- **Live (R7):** first arbitrage/attain tick post-restart produces a decision
  with reason string carrying a projection value — confirms primitive wired.
- **14-day shadow clock starts at this deploy** for R1; R2 build is gated on
  the observed shadow MAE.
