# PLANNING: Energy Savings / Avoided-Energy Sensor Unification

**Author:** ura-planner (session 2026-07-26)
**Status:** Plan only — no code changes
**Proposed tier:** **Tier 2-DB** (energy money-math; multiple consumers; cross-coordinator ripple across EC TOU / arbitrage / HVAC ramp-down; new persisted lifetime accumulators). Elevate to **Tier 3** if D1 (peak-avoidance component) is landed in the same cycle as D3 (lifetime persistence) because that touches a shared primitive (rate lookup) consumed by ≥3 sensor families.

---

## Operator decisions — 2026-07-26 (ratified; supersede §6 where they conflict)

1. **Peak-avoidance credit rate = the TOU tier the tick actually fell into** (not the season peak rate) — honest "what it would have cost right then." Season-peak inflates.
2. **Two headline $ metrics, kept distinct** (not merged into one "savings"): (a) **arbitrage savings** and (b) **peak-avoidance savings**. A `total_$` is a derived sum (attribute per epoch), not a separate sensor family.
3. **Track BOTH units:** **kWh avoided** AND **$ saved**, each accumulated across the **3 epochs** (today / billing_cycle / lifetime).
4. **Double-count guard = YES:** on arbitrage-discharged kWh, peak-avoidance credits **only the `(peak_rate − displaced_rate)` delta** so the two components never overlap.

**Resulting canonical family (supersedes the §5 "9 × $" proposal):**
- `kwh_avoided_{today,billing_cycle,lifetime}` — 3 sensors (kWh)
- `savings_arbitrage_{today,billing_cycle,lifetime}` — 3 sensors ($)
- `savings_peak_avoidance_{today,billing_cycle,lifetime}` — 3 sensors ($)
- `total_$` per epoch = arbitrage + peak_avoidance, exposed as an **attribute** (derived), not its own family.
- billing_cycle keyed off `CONF_ENERGY_BILL_CYCLE_DAY` (23); lifetime = RestoreEntity + baseline table.

**Remaining 3 Qs — DEFAULTED 2026-07-26 (orchestrator, operator to override if desired):**
- **Lifetime back-fill:** back-fill `savings_arbitrage_lifetime` from existing `arbitrage_cycles` rows on upgrade; `savings_peak_avoidance_lifetime` and `kwh_avoided_lifetime` start at 0 (no history to reconstruct) with a baseline row snapshotted at cutover (fixes the "prune shrinks lifetime" gap).
- **`predicted_cost_month`:** soft-deprecate — add the `_billing_cycle` sibling, keep `_month` with a deprecation note (no consumer breakage), remove in a later cleanup.
- **HVAC ac_ramp `$` sibling:** defer to a follow-up — `kwh_avoided_{today,billing_cycle,lifetime}` already carries the energy side; the HVAC-specific `$` conversion is additive and non-blocking.
- The peak-rate lookup gets a named `_get_peak_rate()` primitive (promoted from private `_get_displaced_rate`).

**QUEUED (operator go 2026-07-26).** Small polish batch shipped as v5.31.1 (deployed + validated 2026-07-26) — clean base achieved. Build next.

### TIER RE-SCOPE — 2026-07-26 (operator challenge: "why Tier 2-DB when it's just accounting + sensor surface? does material code use it?")

**Verified: the savings sensors are display-only.** §2 I10 (grep-backed) confirms NO coordinator reads arbitrage-savings / cost-today / cost-this-cycle / hvac kwh_avoided for any decision. The outputs are pure surface.

The Tier-2-DB label was driven by three OPTIONAL implementation ingredients, not the accounting:
1. Rewiring the shared rate primitive (`_get_displaced_rate` → `_get_peak_rate`, routing arbitrage through it) — the real cross-coordinator ripple.
2. Hooking `CostTracker.accumulate()` — the shared billing hot-path that also feeds `cost_today` + `predicted_bill`.
3. New DB tables + a 3-sensor rename migration (recorder-history continuity).

**Decision: drop to Tier 2 (two reviews) by scoping the risk out:**
- **DROP D4 (rename migration).** Add the new `energy_savings_*` family ALONGSIDE the existing 3 arbitrage sensors — no rename, no history risk. Rename deferred to a later cosmetic hygiene pass.
- **DON'T rewire arbitrage.** Add `_get_peak_rate` as a NEW standalone read-only helper; leave `_get_displaced_rate` untouched → zero arbitrage regression surface. (Drops the I8/I9 unification from this cycle.)
- **ISOLATE the accumulator.** Peak-avoidance accumulation lives in a separate field wrapped in try/except so a fault can never corrupt `cost_today` / `cost_this_cycle`.
- Remaining DB footprint = one additive `savings_lifetime_baseline` table (ADD TABLE, no reader migration) → low-risk.

Result: additive display sensors + counterfactual + one additive table + dashboard surfacing = **Tier 2**. Captures the full headline benefit (time-shifted-joules + kWh/$ × 3 epochs). The unify/rename/rewire part (high-risk, low-marginal-benefit) parks for a later cosmetic cycle.

### FOUNDATION VERIFICATION — 2026-07-26 (read both primitives from source before ruling)

Operator asked whether the two primitives this cycle builds on are accurate. Verified against source:

**`_get_displaced_rate(season)` (energy.py:3061-3088):** accurate for ARBITRAGE (returns the season's top displaceable tier — summer peak / else mid_peak — live-sourced with static fallback). It is NOT a general "peak rate now" (no time arg). **Consequence:** under ratified decision #1 (credit the tick's ACTUAL tier, not season peak), peak-avoidance needs `get_effective_import_rate(now)` — which already exists and which `accumulate()` already uses. **The `_get_peak_rate` promotion is therefore UNNECESSARY and is dropped.** `_get_displaced_rate` stays untouched; arbitrage regression surface = zero.

**`CostTracker.accumulate()` (energy_billing.py:143-269):** sound for its purpose (net-metered point-sample × interval; W→kW guarded; interval clamps; daily+cycle resets). BUT it reads only GRID NET POWER (`_get_net_power`) — it cannot see solar / battery-discharge / house-load, which is exactly what peak-avoidance (`house_load − grid_import`) needs. **Consequence: D1's "accumulate inside CostTracker" is the WRONG SITE.** The peak-avoidance accumulator moves to the **EC decision cycle** (which already holds `solar_production_w`, `battery_power_w`, load). CostTracker (the billing hot-path feeding cost_today + predicted_bill) is left byte-identical → the "corrupt cost_today" risk = zero.

**Net effect of both findings:** the two risk ingredients that made this feel like 2-DB are gone by siting alone. Remaining risk is purely "is the new number correct" (served-locally clamp, sign, decision-#4 double-count guard) — a formula-correctness risk, not a regression risk. **Confirmed Tier 2.**

**Review framings (Tier 2):** A = peak-avoidance formula correctness + double-count guard vs arbitrage-discharged kWh (signs, kW/W, clamp-at-zero for served_kW, rate-boundary ticks); B = additive-only wiring PROVES byte-identity of the existing arbitrage + cost_today + predicted_bill surfaces (CostTracker & `_get_displaced_rate` untouched) + additive sensor registration (no recorder rejection).

### D1 RE-SITE (supersedes §4 D1)
Peak-avoidance accumulator lives in the **EnergyCoordinator decision cycle**, NOT in `CostTracker.accumulate()`, and uses the existing `get_effective_import_rate(now)` (NOT a new `_get_peak_rate`). Per tick: `served_locally_kW = max(0, house_load_kW − grid_import_kW)` (equivalently `solar + battery_discharge − charge − export`, clamped ≥ 0); `credit_$ = served_locally_kW × Δh × effective_rate_now`. Decision-#4 double-count guard applies on arbitrage-discharged kWh. Accumulate to today/cycle in an isolated field; try/except so a fault cannot touch cost accounting.

**Status: PRIORITIZED by operator (2026-07-26) — ready to promote to a Tier-2-DB build once the 3 deferred Qs are answered.**

---

## Institutional context verified

### Files read end-to-end
- `custom_components/universal_room_automation/domain_coordinators/energy_billing.py` (entire file, 432 lines — `CostTracker`, `_get_effective_rate_kwh`, cycle-reset semantics)
- `custom_components/universal_room_automation/sensor.py:8360-8730, 10250-10478` (EC cost + arbitrage-savings + HVAC ac_kwh_avoided sensors)
- `custom_components/universal_room_automation/aggregation.py:2000-2225, 2470-2570, 3120-3280, 4340-4400` (Predicted*/WholeHouse*/ZoneEnergy* cost sensors, OptimizationPotential)
- `custom_components/universal_room_automation/domain_coordinators/energy.py:3009-3300` (arbitrage cycle accounting, `_account_arbitrage_cycle`, `_refresh_arbitrage_status_cache`, savings formula)
- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py:210-280, 1800-1950` (ac ramp-down impact cache + per-event `kwh_avoided`)

### Design docs consulted
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (skim — confirmed EC owns arbitrage_savings + billing status; CostTracker is the single writer of `cost_today`/`cost_this_cycle`)
- `docs/planning/PLANNING_v4.3.0_arbitrage_hardening.md` — original 3-scope arbitrage_savings intent (today/cycle/total); mentions `test_roi_resets_at_billing_cycle_day`
- `docs/planning/PLANNING_v4.5.12_ac_ramp_observability.md` — the HVAC `kwh_avoided` sensor family provenance and "trend-watching only, not billing-grade" disclaimer
- `docs/planning/PLANNING_v4.6.8_ec_tou_rate_reconciliation.md` — `_get_effective_rate_kwh` helper (EC TOU → static fallback) is the canonical rate lookup for all display cost sensors
- `docs/TECH_DEBT.md` referenced by the AC kwh_avoided sensors (rough-estimate caveat)

### Greps run

| Domain | Existing (REUSE) | Missing (candidate NEW) |
|---|---|---|
| Bill-cycle knob | `CONF_ENERGY_BILL_CYCLE_DAY` = `"energy_bill_cycle_day"` (energy_const.py:260), `DEFAULT_BILL_CYCLE_START_DAY = 23` (energy_const.py:197). Cycle-reset logic: energy_billing.py:274-301 `_check_cycle_reset` + `_get_cycle_start`. **REUSE — do not add a new field.** | None |
| Rate lookup | `_get_effective_rate_kwh(hass, room_entry=None)` → `(rate, source)` (energy_billing.py:28-88). **REUSE for all rate reads.** | Need a **peak-rate lookup** (see energy.py:3080-3088 `_get_displaced_rate(season)` — private to EnergyCoord). Propose promoting/wrapping into a public helper `_get_peak_rate(hass, when=None) -> (rate, source)`. |
| Arbitrage savings | `EnergyArbitrageSavingsTodaySensor` (sensor.py:8567), `…SavingsCycleSensor` (:8629), `…SavingsTotalSensor` (:8681). Data source: `energy.arbitrage_status` dict, backed by DB rollups `query_arbitrage_savings_since()` / `_total()` (database.py:4940-4982), rows written by `save_arbitrage_cycle` (:4903). Formula: `kwh_charged × (displaced_rate − off_peak_rate) × RTE` at `energy.py:3159`. **REUSE the 3-scope shape** — mirror it for the unified sensor family. |
| Peak-avoidance / self-consumption | **NONE.** Grep of sensor.py, aggregation.py, energy*.py, hvac_override.py for `peak_avoid*`, `self_consumption*`, `time_shift*`, `avoided_import*` returns zero hits. The billing accumulator is *net-import-cost only* (energy_billing.py:250-269) — it correctly reflects real bill, but there is **no counterfactual** for "what if there were no solar and no battery, at peak rates." This is the operator's headline gap. **NEW.** |
| Cost today (net, real) | `EnergyCoordCostTodaySensor` → `sensor.ura_energy_cost_today` (sensor.py:8361). Backed by `CostTracker.cost_today` (net = import_cost − export_credit) using TOU-effective rate per accumulation tick. **REUSE — canonical daily net cost.** |
| Cost this cycle (net) | `EnergyCostCycleSensor` → `sensor.ura_energy_cost_this_cycle` (sensor.py:8408). **REUSE — canonical cycle net cost.** |
| Predicted bill | `EnergyPredictedBillSensor` → `sensor.ura_energy_predicted_bill` (sensor.py:8455). Linear extrapolation after 7 days. Attributes already carry `arbitrage_savings_this_cycle`, `arbitrage_savings_projected_cycle_total`, `predicted_bill_without_arbitrage`, `arbitrage_savings_pct` (:8546-8556). **REUSE — extend attrs to include peak-avoidance component when D1 lands.** |
| HVAC kWh avoided | `HVACACKwhAvoidedTodaySensor` → `sensor.ura_hvac_ac_kwh_avoided_today` (sensor.py:10372); `_TotalSensor` → `sensor.ura_hvac_ac_kwh_avoided_total` (RestoreEntity) (:10424). Sums `ac_ramp_events.kwh_avoided` (per-event capped 30-min projection). Unit: kWh (not $). **REUSE — but see "Inconsistencies" §2: no "cycle" scope, and it's kWh not $.** |
| Predicted cost (forecast) | `PredictedCostTodaySensor`/`Week`/`Month` (aggregation.py:2028, 2120, 2186) — forecast-based, **display-only, uses static electricity_rate + delivery + export_rate**, NOT EC TOU. Distinct concept from "savings." **KEEP separate.** |
| Whole-house cost today | `WholeHouseCostTodaySensor` (aggregation.py:2470) — `energy_kwh × effective_rate`, no cycle/lifetime scopes. **KEEP as-is; not a savings sensor.** |
| Zone cost today | `ZoneEnergyCostTodaySensor` (aggregation.py:4346), `ZoneCostPerHourSensor` (:4391). Same pattern as whole-house. **KEEP.** |
| Room-level cost aggregation | `RoomsByCostPerHourSensor` attrs at aggregation.py:3120-3151 (returns `cost_today` per room). Display-only. **KEEP.** |
| OptimizationPotentialSensor | aggregation.py:3212 — "estimated daily savings from eliminating idle waste." Uses attrs `savings_per_day`, `savings_per_month`. **DIFFERENT class of savings** (behavioral, not solar/battery). KEEP; rename attr namespace only if collision after unification. |
| Circuit-level top-cost | `MostExpensiveCircuitSensor` (aggregation.py:3154) — top-N ranked cost_today. **KEEP.** |

### Prior planning docs surveyed
- `PLANNING_v4.3.0_arbitrage_hardening.md` — original savings=today/cycle/total shape and reset test.
- `PLANNING_v4.5.12_ac_ramp_observability.md` — HVAC kwh_avoided sensor family (kWh unit, not $).
- `PLANNING_v4.6.8_ec_tou_rate_reconciliation.md` — canonical `_get_effective_rate_kwh` helper.
- `PLANNING_v4.6.10_setup_telemetry_and_polish.md` — MONETARY/TOTAL vs TOTAL_INCREASING state_class recorder-rejection rules (see also sensor.py:8461-8464 comment). Applies to every new MONETARY sensor in this cycle.
- `docs/plans/ENERGY_COORDINATOR_PLAN.md` — background on billing accumulator design intent.

### Memory bodies pulled
- v4.3.0 arbitrage saga: savings formula optimism-bias caveats (Review M9-C, sensor.py:8605-8615).
- `inclement_arbitrage_wait_floor_gap` — reserve-floor threading through arbitrage; reminder that `_get_displaced_rate` returns *summer peak* or *winter/shoulder mid_peak*, NOT a general "peak rate for now" helper — needs careful promotion.
- v4.5.20 `_DOMAIN` alias fix (sensor.py:8579-context) — any new EC-reading sensor must use `_DOMAIN` alias inside energy.py callers.

---

## 1. Sensor inventory (savings / avoided / cost)

| entity_id | Class location | Formula / method | Unit | Scope | Reset | state_class | Consumers |
|---|---|---|---|---|---|---|---|
| `sensor.ura_energy_cost_today` | sensor.py:8361 `EnergyCoordCostTodaySensor` | `Σ (net_power_kW × Δh × TOU-effective-rate)` from CostTracker; import positive, export credited at export_rate | USD | today | local midnight (energy_billing.py:221) | TOTAL | display + Predicted Bill attrs |
| `sensor.ura_energy_cost_this_cycle` | sensor.py:8408 `EnergyCostCycleSensor` | Same tick accumulator, cycle-scope | USD | billing_cycle | on `bill_cycle_day` (energy_billing.py:274) + DB restore | TOTAL | display |
| `sensor.ura_energy_predicted_bill` | sensor.py:8455 | `daily_rate × total_days_in_cycle + PEC_FIXED_CHARGES["service_availability"]` after 7 days | USD | prediction (cycle) | on cycle reset | (none — MONETARY-only) | display; attrs surface arbitrage counterfactual |
| `sensor.ura_arbitrage_savings_today` | sensor.py:8567 | Sum of `arbitrage_cycles` rows where `timestamp ≥ local_midnight`; per-row `kwh_charged × (displaced_rate − off_peak_rate) × RTE` (energy.py:3159) | USD | today | local midnight (DB WHERE) | TOTAL | display + Predicted Bill attrs |
| `sensor.ura_arbitrage_savings_cycle` | sensor.py:8629 | Same rollup since bill-cycle start | USD | billing_cycle | on cycle reset (DB WHERE) | TOTAL | display + Predicted Bill attrs |
| `sensor.ura_arbitrage_savings_total` | sensor.py:8681 | Since v4.3.0 deploy, all `arbitrage_cycles` rows summed | USD | lifetime | never (DB durable) | TOTAL | display |
| `sensor.ura_hvac_ac_kwh_avoided_today` | sensor.py:10372 | Sum of `ac_ramp_events.kwh_avoided` (per-event `kW_delta × min(30, projection)/60`) since midnight | **kWh** (not $) | today | local midnight (DB WHERE) | TOTAL_INCREASING | display |
| `sensor.ura_hvac_ac_kwh_avoided_total` | sensor.py:10424 | Cumulative since feature enable; RestoreEntity | **kWh** | lifetime | never | TOTAL_INCREASING | display |
| `sensor.ura_whole_house_cost_today` | aggregation.py:2470 | `whole_house_energy × _get_effective_rate_kwh()` (single-rate snapshot, not TOU-tick-accumulated) | USD | today | at midnight via source-sensor reset | TOTAL | display |
| `sensor.ura_predicted_cost_today` / `_week` / `_month` | aggregation.py:2028, 2120, 2186 | `db.predict_energy(period, forecast_temp) × (rate + delivery)` or `× export_rate` if net-export | USD ("$" unit — legacy) | forecast (today/week/month) | cache 15m/1h/6h | MEASUREMENT | display |
| `sensor.ura_zone_<zone>_energy_cost_today` | aggregation.py:4346 | `Σ room energy_today × effective_rate` (single-rate snapshot) | USD | today | at midnight via room-sensor reset | TOTAL | display |
| `sensor.ura_optimization_potential` | aggregation.py:3212 | `Σ vacant-room-power × 24 × rate` — heuristic idle-waste $/day | USD/day | instantaneous rate | live | MEASUREMENT | display; attrs `savings_per_day`, `savings_per_month` |
| `sensor.ura_most_expensive_circuits` | aggregation.py:3154 | Circuit `cumulative_energy_wh/1000 × rate`; top-1 native, top-5 attr | USD | today (circuit accumulator) | on circuit reset | MEASUREMENT | display |

**Attribute-only "savings" fields:**
- `EnergyPredictedBillSensor` (sensor.py:8546-8556): `arbitrage_savings_this_cycle`, `arbitrage_savings_projected_cycle_total`, `predicted_bill_without_arbitrage`, `arbitrage_savings_pct`, `arbitrage_methodology`.
- `EnergyCoordCostTodaySensor.extra_state_attributes` (sensor.py:7043 refs `today.get("savings")` — legacy tag, but the class at :8361 does NOT surface it; verify no live consumer expects it).
- `OptimizationPotentialSensor` attrs (aggregation.py:3269-3275): `savings_per_day`, `savings_per_month` (behavioral savings, unrelated to solar/battery).

---

## 2. Overlaps and inconsistencies

**I1 — No peak-avoidance / self-consumption component (headline gap).**
The billing accumulator (energy_billing.py:250-269) records *real* net-import cost against the TOU-effective import rate. It cannot answer "what would this cost have been if every kWh consumed had come from the grid at peak?" Arbitrage-savings answers a narrower question — the marginal value of charging off-peak — but it does **not** credit solar self-consumption OR battery discharge during peak that came from solar. The operator's "energy value shifted joules" is entirely absent.

**I2 — Unit inconsistency: `hvac_ac_kwh_avoided_*` is kWh, all other "avoided/savings" are USD.** Users mixing them in a dashboard "total saved" tile will silently add kWh to dollars. Either give it a `$`-valued sibling (`ac_ramp_savings_*` = `kWh_avoided × TOU rate at nudge time`) or namespace it clearly.

**I3 — Scope asymmetry.**
- Arbitrage savings: today / cycle / total (3 scopes — matches operator ask). ✓
- HVAC ac_kwh_avoided: today / total only, **no cycle scope**.
- Cost: today / cycle / (predicted_bill acts as extrapolation) — **no lifetime**.
- Predicted cost family: today / week / **month** (calendar month, not billing cycle) — inconsistent with `bill_cycle_day` semantics.

**I4 — Two "cost today" surfaces with different math.**
- `sensor.ura_energy_cost_today` = TOU-tick integrator (billing-grade, from EC CostTracker).
- `sensor.ura_whole_house_cost_today` = single-rate × cumulative energy sensor (snapshot).
They can disagree during peak/off-peak transitions. Neither is wrong for its purpose but the naming does not disclose the distinction.

**I5 — Predicted-cost family uses static rate + delivery + export_rate (aggregation.py:2109-2115), NOT EC TOU tick math.** The other display cost sensors use `_get_effective_rate_kwh` (which routes to EC TOU). The forecast family is one abstraction level below and won't reflect TOU shifts inside the forecast horizon.

**I6 — Predicted cost `_attr_native_unit_of_measurement = "$"` (aggregation.py:2031, 2123, 2189) vs `"USD"` elsewhere.** HA MONETARY prefers ISO codes. Cosmetic but real.

**I7 — Arbitrage-savings `_total` "since v4.3.0 deploy" has no persisted anchor.** If `arbitrage_cycles` rows are ever pruned (retention policy), the lifetime number silently shrinks. Currently no known pruning, but a `lifetime_savings_baseline` snapshot would harden it (Bug Class #22-adjacent).

**I8 — Rate-source drift in savings math.** `_account_arbitrage_cycle` (energy.py:3157-3159) reads `off_peak_rate = self._tou.get_effective_import_rate()` (current-tick rate — may not be off-peak if grid-charging spilled outside window) and `displaced_rate = self._get_displaced_rate(season)` (fixed summer-peak / winter-mid_peak). Mixed authorities. Unification should route both through one helper.

**I9 — `_get_displaced_rate` is private and season-shaped.** No public "current peak rate" for reuse by a peak-avoidance sensor (I1). Any unified savings model needs a first-class rate helper.

**I10 — Decision-consumers vs display.** Grep confirms:
- Arbitrage-savings, cost-today, cost-this-cycle: **display-only + attrs cross-ref**. No coordinator reads them for decisions. **Safe to rename with unique-id preserved via migration.**
- `energy.arbitrage_status` dict is consumed by two sensors AND by predicted-bill attrs — behavior-freeze the dict shape.
- `_impact_cache["kwh_avoided_today"/"_total"]` in hvac_override consumed only by the two D8 sensors — safe.

---

## 3. Proposed unified model

### 3.1 Definition of "energy value saved"

`total_energy_value_saved = arbitrage_component + peak_avoidance_component`

where:

**(a) Arbitrage component** (unchanged shape; formula already at energy.py:3159):
```
arbitrage_savings_$ = Σ_cycles (kwh_charged × (displaced_rate − off_peak_rate) × RTE)
```
- `RTE` = `_ARBITRAGE_RTE` constant (energy.py — the "round-trip efficiency" discount).
- `displaced_rate` = per-season canonical peak/mid_peak from PEC_TOU_RATES.
- `off_peak_rate` = TOU-effective import rate at the time the grid kWh was charged.
- Recorded per cycle in `arbitrage_cycles` table.

**(b) Peak-avoidance / time-shift component** (**NEW**):
For every tick where solar or battery is serving load that would otherwise have been grid-imported, credit the counterfactual dollars:
```
peak_avoidance_$_per_tick =
    served_from_solar_plus_battery_kW × Δh × (peak_rate − effective_rate_now)
```
where:
- `served_from_solar_plus_battery_kW = max(0, solar_production_kW + battery_discharge_kW − battery_charge_kW − grid_export_kW)`
  (i.e. household load served by non-grid sources — equivalently `house_load − grid_import`, clamped to ≥ 0).
- `peak_rate` = current season's peak TOU rate (**not** current-tick rate). New helper `_get_peak_rate(hass, when=None) → (float, source)` (promote/wrap the private `_get_displaced_rate`).
- `effective_rate_now` = `_get_effective_rate_kwh(hass)` (what it actually cost — 0 if all served locally; a lower TOU tier if partially local).
- Accumulate inside `CostTracker.accumulate()` (energy_billing.py:209) — same tick cadence, same divisions of today/cycle. Add a `_peak_avoidance_today` / `_peak_avoidance_cycle` accumulator alongside `_cost_today`.
- Persist to a **new** `peak_avoidance_ticks` table (or extend the midnight snapshot + cycle DB write) so lifetime survives restart.

**Total** (the operator's headline):
```
energy_value_saved_$ = arbitrage_savings_$ + peak_avoidance_$
```

This is a **counterfactual** (what a same-load house with no solar and no battery would have paid at the applicable tier). The methodology attribute must state this plainly, matching the existing arbitrage-savings honesty caveat (sensor.py:8605-8615).

### 3.2 The 3-scope family (canonical names)

For each of the three components — **arbitrage**, **peak_avoidance**, **total** (= sum) — expose the same three scopes:

| Scope | Reset | Persistence |
|---|---|---|
| `..._today` | Local midnight | Midnight snapshot → DB restore on boot (mirror `restore_daily`, energy_billing.py:325) |
| `..._billing_cycle` | `CONF_ENERGY_BILL_CYCLE_DAY` (existing, DEFAULT=23) via `_check_cycle_reset` (energy_billing.py:274) | DB rollup (`update_from_db`, energy_billing.py:303) |
| `..._lifetime` | never | RestoreEntity + DB baseline row (new `savings_lifetime_baseline` table with a single row per component) |

**Naming (proposed):**
- `sensor.ura_energy_savings_arbitrage_today` / `_billing_cycle` / `_lifetime`
- `sensor.ura_energy_savings_peak_avoidance_today` / `_billing_cycle` / `_lifetime` (NEW)
- `sensor.ura_energy_savings_total_today` / `_billing_cycle` / `_lifetime` (NEW — sum)

All USD, MONETARY, state_class TOTAL (per v4.6.10 D6 recorder rule at sensor.py:8461-8464).

### 3.3 Keep / Unify / Rename / Deprecate

| Existing entity | Action | Rationale |
|---|---|---|
| `sensor.ura_arbitrage_savings_today` | **RENAME** → `sensor.ura_energy_savings_arbitrage_today` (unique_id preserved; add `previous_unique_id` migration in `async_setup_entry`) | Naming consistency across 3-component × 3-scope family |
| `sensor.ura_arbitrage_savings_cycle` | **RENAME** → `..._billing_cycle` (spell out — matches `bill_cycle_day` config) | Disambiguate "cycle" vs "billing cycle" vs "arbitrage cycle" (three different "cycles" in this codebase) |
| `sensor.ura_arbitrage_savings_total` | **RENAME** → `..._lifetime` + add DB baseline snapshot | "Total" is ambiguous with "sum-of-components"; "lifetime" is the scope word |
| `sensor.ura_energy_cost_today` | **KEEP** (canonical real-net-cost) | Different concept from savings |
| `sensor.ura_energy_cost_this_cycle` | **KEEP** | Same |
| `sensor.ura_energy_predicted_bill` | **KEEP**; extend attrs to include `peak_avoidance_savings_this_cycle` + `total_savings_this_cycle` + `predicted_bill_without_solar_battery` | Attribute-level counterfactual expansion |
| `sensor.ura_hvac_ac_kwh_avoided_today/_total` | **KEEP**; ADD sibling `_billing_cycle` scope; ADD sibling `$`-valued family `sensor.ura_hvac_ac_ramp_savings_today/_billing_cycle/_lifetime` (kWh × rate at nudge time from the persisted event row) | Fixes I2 (unit) + I3 (scope) without breaking existing kWh sensors. The `$` family CAN be folded into the "total savings" sum in a later cycle (out of scope here — HVAC nudge value is behavioral, not solar/battery). |
| `sensor.ura_whole_house_cost_today` | **KEEP** (different math — snapshot × single rate) | Retain; consider deprecating in favor of `energy_cost_today` in a later hygiene cycle |
| `sensor.ura_predicted_cost_today/_week/_month` | **KEEP**; unit `$` → `USD` (I6); optionally add `_billing_cycle` scope replacing/complementing `_month` | Forecast is a distinct concept; scope alignment is polish |
| `sensor.ura_optimization_potential` (attrs `savings_per_day/_month`) | **KEEP**; namespace attrs → `idle_waste_savings_per_day` etc. | Prevent semantic collision with the new "savings" family |
| `sensor.ura_most_expensive_circuits` | **KEEP** | Ranking display, no overlap |
| `sensor.ura_zone_<zone>_energy_cost_today` | **KEEP** | Different scope (zone) |

### 3.4 Numbers-get-knobs

Every new number, per CLAUDE.md ladder:

| Value | Name | Rung | Why |
|---|---|---|---|
| RTE for arbitrage savings math | `ARBITRAGE_RTE` (already `EnergyCoord._ARBITRAGE_RTE` — energy.py:3159) | **Module constant** (energy_const.py) — promote from class attr | Fitted efficiency assumption; change requires review |
| Peak-avoidance min-served threshold (ignore < X kW to suppress noise floor) | `PEAK_AVOIDANCE_MIN_SERVED_KW` | Module constant (energy_const.py) | Safety/numerics; not operator-tuned |
| Peak-rate lookup helper | `_get_peak_rate(hass, when=None) -> (float, source)` | Module function in energy_billing.py (or energy_tou.py — reviewer decides) | Shared primitive — must have ONE writer |
| Lifetime baseline enable | Implicit at first deploy; no knob | — | Kill switch would be a mis-affordance |
| `CONF_ENERGY_BILL_CYCLE_DAY` | **REUSED** (energy_const.py:260) | Config-flow (existing) | Do not add a new field |

No new number entities in v1 of this cycle (all reset semantics are derived; operator tuning happens at rate-config level).

---

## 4. Deliverables

### D1: Peak-rate helper + peak-avoidance CostTracker component
Extend `CostTracker` (energy_billing.py) with parallel `_peak_avoidance_today`, `_peak_avoidance_cycle` accumulators. Each `accumulate()` tick computes `served_kW × Δh × (peak_rate − effective_rate)` and adds to both scopes. Promote `_get_displaced_rate` (energy.py:3078-3088) into a public `_get_peak_rate(hass, when=None) -> (float, source)`; route arbitrage math through it too (unification of I8/I9).

**Acceptance criteria:**
- **Verify:** During a peak window with solar producing 4 kW and house load 2 kW (all served locally, zero grid import), `_peak_avoidance_today` accumulates at `2 kW × Δh × peak_rate` per tick (grid-import cost was 0, counterfactual would have been full peak).
- **Verify:** During off-peak with battery idle and no solar, `_peak_avoidance_today` accumulates $0 (served_kW = 0 because grid_import = house_load).
- **Sensor:** attribute `peak_avoidance_methodology` present with full formula string.
- **Test:** `test_peak_avoidance_credits_solar_during_peak`, `test_peak_avoidance_zero_at_night_no_battery`, `test_peak_avoidance_partial_battery_supplement`.
- **Live:** With house running on solar mid-day, `sensor.ura_energy_savings_peak_avoidance_today` > 0 within 15 min of peak window start.

### D2: 6 new sensors (peak_avoidance × 3 scopes; total × 3 scopes)
Mirror the existing `EnergyArbitrageSavings*` classes (sensor.py:8567-8730) for peak_avoidance and total. Total = arbitrage + peak_avoidance summed at read time (no separate accumulator — single source of truth).

**Acceptance criteria:**
- **Verify:** `total_today == arbitrage_today + peak_avoidance_today` (within rounding) at any read; assert via a test that instantiates all three and diffs.
- **Sensor:** All 6 sensors register with device `URA: Energy Coordinator`, MONETARY, TOTAL state_class, USD, precision 2. No HA recorder rejection warnings on boot.
- **Test:** `test_total_savings_is_component_sum`, `test_savings_family_scopes_reset_correctly`.
- **Live:** All 9 (3×3) sensors visible + populated within 10 min of restart.

### D3: Lifetime baseline persistence
New DB table `savings_lifetime_baseline` (`component TEXT PK, baseline_usd REAL, first_recorded_iso TEXT`). Written on first-ever accumulate for each component. `..._lifetime` sensors compute `baseline + rollup_since_baseline`. Prevents shrinkage if `arbitrage_cycles` or `peak_avoidance_ticks` ever get pruned (I7).

**Acceptance criteria:**
- **Verify:** After first accumulate, `savings_lifetime_baseline` has one row per component with `baseline_usd = 0` and `first_recorded_iso` set.
- **Verify:** Deleting all rows from `arbitrage_cycles` does NOT drop `..._arbitrage_lifetime` sensor value below `baseline_usd`.
- **Test:** `test_lifetime_baseline_written_once`, `test_lifetime_survives_row_prune`.
- **Live:** Post-restart, `sensor.ura_energy_savings_arbitrage_lifetime` matches pre-restart within $0.01.

### D4: Migration (rename existing 3 arbitrage sensors)
Preserve entity_id continuity — use `async_migrate_entry` + `async_add_entities` with `previous_unique_id` OR entity-registry hook so existing history in HA recorder is retained. Zero user action.

**Acceptance criteria:**
- **Verify:** `sensor.ura_arbitrage_savings_today` history in HA recorder is contiguous under the new entity_id after upgrade.
- **Verify:** No `orphaned entity` warnings in logs at boot.
- **Test:** `test_arbitrage_sensor_rename_migration_preserves_history`.
- **Live:** After deploy + restart, historical graphs in the Energy dashboard span the rename boundary without gaps.

### D5: Extend `EnergyPredictedBillSensor` attrs
Add `peak_avoidance_savings_this_cycle`, `total_savings_this_cycle`, `predicted_bill_without_solar_battery` (= predicted_bill + total_savings_projected_cycle_total). Preserve existing arbitrage-only attrs for consumer compat.

**Acceptance criteria:**
- **Sensor:** All 4 new attrs present + numeric after 7 days in cycle.
- **Test:** `test_predicted_bill_attrs_include_peak_avoidance`.
- **Live:** Attribute visible in Developer Tools → States after restart.

### D6: HVAC ac_kwh_avoided billing-cycle scope + `$` sibling family (deferrable)
Add `sensor.ura_hvac_ac_kwh_avoided_billing_cycle` and `sensor.ura_hvac_ac_ramp_savings_today/_billing_cycle/_lifetime` (`$` = per-event `kwh_avoided × rate_at_event`). Note: this reads pre-persisted per-event rows from `ac_ramp_events` (hvac_override.py:1894-1910) — the event row already carries `kwh_avoided` in `notes`. May require adding a rate column at write time.

**Acceptance criteria:**
- **Verify:** Cycle sensor resets on `bill_cycle_day`.
- **Test:** `test_ac_kwh_avoided_billing_cycle_reset`.
- **Live:** Sensor populated within 24h.

**Deferrable** — file as follow-up if D1–D5 land clean.

### D7: Surface cost + kWh-avoided on dashboards (operator-requested 2026-07-26)
Once the sensor family exists, surface it — the whole point of the cycle is a glanceable savings story.
- **ura-v8 Energy tab:** add the savings family to the Energy Situation / Energy dashboard section — arbitrage $, peak-avoidance $, and total $ per epoch (today / billing_cycle / lifetime), plus kWh-avoided. Fit the existing Material Clean card style (no new controls — status only, per the ura-v8 no-new-controls directive).
- **PWA:** mirror the headline (total $ saved today + lifetime) on the energy surface.

**Acceptance criteria:**
- **Verify:** Energy tab shows the 3-component × 3-epoch savings grid + kWh-avoided, values matching the sensor states.
- **Verify:** PWA energy surface shows total-saved-today + lifetime, matching sensors.
- **Live:** After sensors populate (D2 live), dashboard tiles render non-zero within the same window.

**Sequencing:** D7 runs AFTER D1–D5 land + sensors are live-validated (can't surface a sensor that doesn't exist yet). Dashboard-only, no tier weight of its own.

**DONE 2026-07-26.** ura-v8: "Energy Savings" section on the Energy & EV view (3-component × 3-epoch markdown grid + kWh-avoided row), write-verified, renders live values. PWA: `SavingsCard` on the Energy tab (total today + lifetime + PA/arbitrage components) via `useUraSensorFloat`, tsc clean + tests pass — in the ura-dashboard-pwa working tree, awaiting operator PWA deploy.

---

## 5. Tier-classification justification

Per CLAUDE.md standing policy: elevate regression-prone work to Tier 2-DB (3 framing-disjoint reviews). Triggers hit:
- **Trust-hierarchy ripple:** `_get_effective_rate_kwh` + new `_get_peak_rate` are shared primitives consumed by ≥5 sensor families and by arbitrage decision math.
- **Money-math change:** peak_avoidance component defines a new dollar-valued surface that will be quoted by users.
- **DB schema:** new `savings_lifetime_baseline` table + new `peak_avoidance_ticks` (or extended snapshot) rows.
- **Migration:** 3 sensor renames with recorder-history continuity.

**Review framings:**
- **A — Correctness + formula edge cases:** signs, unit normalization (kW vs W, energy_billing.py:186-189), clamp-at-zero for `served_kW`, negative-savings guard (energy.py:3168), season/rate-boundary rows.
- **B — Migration + cross-coordinator ripple:** `_get_peak_rate` promotion cannot regress arbitrage math (byte-identical result on the same inputs); rename migration preserves entity_id + history; predicted_bill attrs remain backward-compatible for any dashboard reading them.
- **C — DB + persistence + test authority:** new tables + baseline restore; RestoreEntity semantics; behavioral tests use production DDL (not hand-copied); tests exercise `CostTracker.accumulate()` end-to-end, not fixture INSERTs.

Elevate to **Tier 3** if scope is extended to include a fourth (adversarial-completeness) reviewer whose falsifiable invariant is: **"Under any legal solar/battery/grid state, `total_today` equals `arbitrage_today + peak_avoidance_today` and neither component is ever negative."** Recommended if D1+D3 ship together.

---

## 6. Open questions for the operator

1. **Peak-avoidance credit rate — peak only, or tier-shifted?**
   Two interpretations:
   (a) Always credit against the **current-season peak rate** (simplest; matches "what if there were no solar/battery" narrative).
   (b) Credit against the **tier the tick would have fallen into** — e.g. during mid_peak, credit `(mid_peak − 0)`; during off_peak, credit `(off_peak − 0)`. This is "what did we save at each hour."
   The doc assumes (a). (b) is more honest but harder to explain.

2. **Should peak_avoidance include or exclude the arbitrage kWh?**
   The battery discharge during peak in an arbitrage cycle is *both* arbitrage (charged cheap, discharged expensive) *and* peak-avoidance (served load that would have been grid-import). If we sum both components naively, arbitrage-charged kWh get double-credited. Proposal: **peak_avoidance credits only the (peak_rate − displaced_rate) delta on arbitrage-charged kWh** (the off-peak cost still applies; arbitrage already booked the (displaced − off_peak) delta). Total then equals `served_kW × Δh × peak_rate − actual_import_cost`, which is the cleanest counterfactual. **Confirm.**

3. **Lifetime anchor semantics.**
   Should `_lifetime` be "since v5.32.0 deploy" (fresh baseline) or "back-fill from all existing `arbitrage_cycles` rows"? Proposal: back-fill on first boot after upgrade (preserves the ~months of arbitrage history already in DB); peak_avoidance starts at 0.

4. **HVAC ac_ramp_savings $ family — do you want it now (D6), or file as follow-up?**
   The kWh sensors carry a "not billing-grade" caveat; the $ version inherits it. If it goes in-band as part of `total_savings`, that caveat propagates.

5. **`predicted_bill_without_solar_battery` — cycle-projected only, or also today?**
   The existing `predicted_bill_without_arbitrage` is cycle-only. Adding a `today` variant means a fourth sensor family; proposal: **attribute only** (keeps sensor count bounded).

6. **Bill-cycle sensor for predicted_cost family (I3).**
   Replace `predicted_cost_month` with `predicted_cost_billing_cycle`, or add alongside? Prefer add-alongside + soft-deprecate `_month` in the same cycle.

---

## 7. Doc location

Filed at `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_energy_savings_unification.md` (this file).
