# v5.91.0 — EVSE solar-following amp modulation (EVSE-SOLAR-FOLLOW-AMPS-1)

**Cards shipped:** `EVSE-SOLAR-FOLLOW-AMPS-1`
**Tier:** 3 (threads a value through the EVSE peer-precedence system; cost-AND-safety impacting — a wrong amp target over-draws the house battery or the service).
**Branch:** `feature/evse-solar-follow-amps` @ `ace443da3` → merged to develop.

## What this ships

EV charging on excess solar was **binary** — 48 A (11.5 kW) or off — so when a cloud cut production the car kept pulling 48 A and yanked the difference out of the house battery (the yo-yo). This adds a `SolarFollowController` that modulates each of the two L2 chargers' `current_limit` between **6 A and 48 A** to track measured export, inside a solar session the existing excess-solar trigger already opened. **Amps only** — it never starts or stops a charge and never coordinates with DP (scope-fenced).

- **Sizing (INV-SF-4):** `S = -grid_W + Σ drawing-bay power`, parked floor netted before dividing, per-EVSE clamp [6,48], deadband, conservative-down/cautious-up.
- **Grid signal:** Emporia mains PRIMARY, Envoy net-consumption CT FALLBACK — either-or, no agreement gate. **INV-SF-10 freshness:** a source whose `last_reported` age exceeds `SOLAR_FOLLOW_GRID_FRESH_S` (180 s) is treated as unavailable; a stale PRIMARY hands off to the FALLBACK; both stale → blind (stop). `last_reported`, not `last_updated` (minute-average sensors re-emit unchanged values).
- **Observability:** four solar-follow attributes on `sensor.ura_energy_coordinator_ev_charging_status`, plus `solar_follow_below_dp_l1_threshold` (pure-read cross-reference so a DP `l1_only` no-drain is diagnosable) and `solar_follow_grid_source`.
- **Operator knob:** `ExcessSolarConfirmNumber` ("Excess Solar Confirm", up-confirm ticks). All other numbers are rung-1 module constants.

## Review

Tier-3, **four framing-disjoint reviews** (A local-correctness / B async-lifecycle-race / C test-authority-via-mutation / D adversarial-completeness). All four returned FIX-REQUIRED. 15 code defects fixed across two fix-up rounds — including the convergent (flagged ×3) pop-`_original_amps`-before-write, the D-HIGH-4 **money leak** (unbounded STALE_POWER hold pinning 11.5 kW of peak-tariff import → now bounded by `SOLAR_FOLLOW_STALE_HOLD_MAX_TICKS=5`), the `_boot_reconcile` cluster (missing peer guard / one-shot latch / disabled-path bypass), and tick reentrancy. ~26 load-bearing sites are mutation-anchored (+37 tests, 20→57). Orchestrator independent verification: re-grepped every write-site peer guard; personally drilled CF-5 (money-leak bound), E1 (wire-in call — now call-neuter-detectable, the recurring failure genuinely closed), CF-1; full-suite name-diff **0 new failures**. Full record: `docs/reviews/code-review/v5.91.0_solar_follow_consolidated.md`.

`SOLAR_FOLLOW_GRID_FRESH_S = 180` (operator decision): tighter than the initial 300 because a false-demote is a benign handoff to the fresher Envoy fallback, while too-high sizes on stale data (the D-HIGH-4 harm). 180 = 1.5× Emporia p90 (120 s).

## Acceptance criteria

### Provable day-0 (post-restart, likely at night — feature dormant)
- **Verify:** `sensor.ura_energy_coordinator_ev_charging_status` publishes the six solar-follow attributes (`solar_follow_surplus_kw`, `_original_amps`, `_state`, `_blind_since`, `_grid_source`, `_below_dp_l1_threshold`).
- **Verify:** with no active excess-solar session (SOC below threshold / night), the controller writes nothing and no bay's `current_limit` is touched (INV-SF-1 non-perturbation).
- **Verify:** zero new URA `ERROR` logs in the first 15 min.

### Organic (needs a sunny day + an active excess-solar EV session)
- **Live:** during an excess-solar session, the `number.*_current_limit` entity's own recorder history shows the commanded limit tracking surplus (steps between 6 and 48 A), never exceeding 48.
- **Live:** on a cloud transient the house battery no longer absorbs the full 11.5 kW swing (battery-power excursion shrinks vs the pre-cycle binary behavior).
- **Live:** after a >10 h restart with a previously throttled bay, its limit reads 48 A (boot reconciliation).

## Post-deploy validation — (to be written back after restart)
