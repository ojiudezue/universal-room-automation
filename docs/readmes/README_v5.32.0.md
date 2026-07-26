# URA v5.32.0 — Energy Savings Unification (peak-avoidance / time-shifted-joules)

Adds the missing **counterfactual savings** surface: what the house *would* have paid
if every locally-served kWh (solar + battery) had come from the grid at the tick's
actual TOU tier. Purely additive + display-only — **no decision consumer, no
behavior change**. Arbitrage and cost accounting are byte-frozen and guard-tested.

## What ships

### New savings family (9 sensors, 3 components × 3 epochs)
- `sensor.ura_energy_savings_peak_avoidance_{today,billing_cycle,lifetime}` (USD) — NEW counterfactual.
- `sensor.ura_energy_savings_total_{today,billing_cycle,lifetime}` (USD) — arbitrage + peak-avoidance, summed at read time.
- `sensor.ura_energy_kwh_avoided_{today,billing_cycle,lifetime}` (kWh) — energy side across all 3 epochs.
- Existing `sensor.ura_arbitrage_savings_{today,cycle,total}` are **kept unchanged** (additive-only; rename deferred to a later cosmetic pass).
- `EnergyPredictedBillSensor` gains attrs `peak_avoidance_savings_this_cycle`, `total_savings_this_cycle`, `predicted_bill_without_solar_battery` (existing arbitrage attrs preserved).

### Design (operator-ratified 2026-07-26)
- **Credit rate = the TOU tier the tick actually fell into** (`get_effective_import_rate(now)`), NOT season peak. Honest "what it would have cost right then."
- **Two distinct $ metrics** (arbitrage + peak-avoidance); `total` is their sum.
- **Double-count guard:** on arbitrage-discharged kWh, peak-avoidance credits only the `(tier_rate − displaced_rate)` delta so the components never overlap.
- Accumulator lives in the **EnergyCoordinator decision cycle** (has solar/battery/load), wrapped in try/except — a fault can never touch `cost_today`/`predicted_bill`.
- **Lifetime persistence:** delta rolls into a `savings_lifetime_baseline` DB row at local midnight (≤2 writes/day — respects the v5.2.1 write-flood lesson); today/cycle restore on boot via the existing `energy_state` snapshot idiom (mirrors `CostTracker`).

### Foundation-verified before build (money-number discipline)
- `_get_displaced_rate` and `CostTracker.accumulate` are **source byte-identical** to pre-v5.32.0 (confirmed by AST source-diff + in-suite guard tests with inlined SHA constants). The cycle builds *alongside* them, never through them.

## Review provenance
`docs/reviews/code-review/v5.32.0_energy_savings_unification.md` — Tier 2, two framing-disjoint reviews (A = formula correctness/sign/units/double-count; B = persistence/restart/byte-identity/DB/registration). 3 HIGH found + fixed (net-power `None` over-credit; lifetime reset-on-restart; today/cycle reset-on-restart) + 3 MEDIUM. Orchestrator independently re-verified byte-identity via source-diff and re-ran the 17-test suite. Full suite: 26-failure documented baseline, **zero new failures**.

## Live Validation — Acceptance Hypotheses (Shipwatch)

- **H1 — Clean boot.** Zero URA `ERROR` lines post-restart; 41 config entries `loaded`; presence house-state live. Window: 15 min.
- **H2 — All 9 sensors register + populate.** The 9 new entities exist, are numeric (not `unavailable`/`unknown`) within 10 min of restart, MONETARY→USD / ENERGY→kWh, no recorder-rejection warnings. Window: 10 min.
- **H3 — total = arbitrage + peak_avoidance.** `savings_total_today ≈ arbitrage_savings_today + savings_peak_avoidance_today` (within rounding) at any read. Window: 1 h.
- **H4 — Peak-avoidance credits on solar.** During a daytime producing window with load served locally, `savings_peak_avoidance_today` > 0 and climbs; at night with no solar/battery it does not climb. Window: next daylight producing period.
- **H5 — Arbitrage + cost byte-frozen (regression guard).** `arbitrage_savings_{today,cycle,total}` and `cost_today`/`predicted_bill` render the same shape/values as pre-deploy for matching conditions (byte-identity already proven in-suite). Window: 1 h.
- **H6 — Lifetime survives restart.** After the sensor shows a non-zero `savings_peak_avoidance_lifetime`, an HA restart does NOT drop it to $0 (the reviewed defect). Oracle: recorder value across a restart boundary. Window: next restart.
- **H7 — No write-flood.** No surge in DB write-queue depth / no watchdog restart attributable to the new accumulator; baseline writes ≤2/day. Window: 24 h.

### Validated 2026-07-26 (restart ~18:34 CDT)

Actual entity_ids carry the `_energy_coordinator_` prefix and use `_this_cycle` (not `_billing_cycle`).

| # | Result | Observed evidence |
|---|--------|-------------------|
| H1 | **PASS** | Zero URA `ERROR` lines post-restart (error_log search=universal_room_automation). |
| H2 | **PASS** | All 9 register + numeric: `energy_savings_peak_avoidance_{today,this_cycle,lifetime}` (USD/monetary/TOTAL), `energy_savings_total_{...}` (USD/monetary/TOTAL), `energy_kwh_avoided_{...}` (kWh/energy/TOTAL). No recorder-rejection. `peak_avoidance_methodology` attr present with full formula + double-count guard + 0.05 kW noise floor. |
| H3 | **PASS (exact)** | `total = arbitrage + peak_avoidance` at every scope: today `0.0=0.0+0.0`; this_cycle `1.42=1.42+0.0`; lifetime `11.67=11.67+0.0`. |
| H5 | **PASS** | Arbitrage sensors unchanged (`arbitrage_savings_today=0.0`, `_this_cycle=1.42`, `_total=11.67`) — plus in-suite AST byte-identity of `_get_displaced_rate` + `CostTracker.accumulate` (orchestrator source-diff verified). |
| H4 | pending-organic | Peak-avoidance = `0.0` at T+3min (fresh first-boot accumulator, evening, ~0-1 ticks). Prove on next daylight producing window: `energy_savings_peak_avoidance_today` > 0. |
| H6 | pending | Lifetime-survives-restart: PA lifetime is still `0.0` (nothing accrued yet), so provable only after PA accumulates then a restart. |
| H7 | pending | 24 h write-queue / no-watchdog watch (≤2 baseline writes/day). |

H1/H2/H3/H5 confirmed live at restart. H4/H6/H7 handed to **Shipwatch** on their qualifying windows.
</content>
</invoke>
