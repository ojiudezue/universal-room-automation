# PLANNING v4.7.x — Advanced Energy Management (Forecaster-First)

**Status:** Scoped, not started
**Tier:** Tier 2 feature cycle (three sub-cycles: v4.7.0 → v4.7.1 → v4.7.2)
**Predecessor:** v4.6.2 (Routine Awareness)
**Supersedes:** `PLANNING_v4.6.x_winter_morning_peak_strategy.md` (winter mornings absorbed into the unified forecaster-first plan)
**Recall hint:** "Resume Advanced Energy Mgt v4.7.x — Forecaster-First"

---

## TL;DR

**Don't build a new optimizer. Build a better load forecast.**

URA already runs a sophisticated forecast-driven energy optimizer (`BatteryStrategy.determine_mode()`) that writes to Enphase reserve_soc + charge_from_grid every 5 minutes. The "universal heuristic" instinct is already implemented as a priority chain with per-season + per-TOU-period awareness. The actual gap is that the drain target branches on tomorrow's SOLAR forecast but apparently not tomorrow's LOAD forecast — and even the solar branching uses a 4-bin coarse table.

The right cycle: a URA-native, weather-aware LightGBM load forecaster trained on the rich `energy_history` + `external_conditions` data URA already collects, then wired into a continuous (non-bucketed) drain-target calculation feeding the existing optimizer.

3 sub-cycles total. ~600 LOC across all three. No external optimizer vendored. Sized for community-deployable value.

---

## Origin & journey

This planning doc came out of a long arc that started "broad" and narrowed to "specific" as research data closed off paths. Captured here so the false starts and corrections don't have to be re-traveled.

### Step 1 — Original framing: "universal heuristic + Bayesian load forecaster"

The user opened by sketching three seasonal strategies (summer / winter / shoulder) and asking whether a single universal heuristic could subsume the seasonal modes if it had TOU + weather + Bayesian-correlated load forecast. The mental model was a forward-looking optimizer that runs continuously, no explicit "modes."

I initially sketched it as a 24h MILP-MPC stack — receding horizon, 15-min buckets, per-bucket decisions on battery charge/discharge, with seasonal "safety nets" only when forecasts are noisy. This framing carried for a while before being invalidated.

### Step 2 — Quantification: the headroom is small

Analyzed user's Enphase Custom Report (310 days, 2025) with PEC 2026 rates. Key numbers:

- **TOU rate switch alone (no automation):** **+$142/yr** vs flat (8.2% reduction). Locked in by enrollment.
- **Residual TOU premium after rate switch (mid-peak + peak above off-peak):** **~$92/yr**
- **Peak-rate exposure:** **2.21% of grid imports** (user's <5% intuition validated; actual closer to 2%)
- **Combined mid-peak + peak exposure:** **12.6% of grid imports**
- **Where the $92 lives:** **79% in summer evenings 17–20h**; 14% in winter mornings 5–8h; 7% elsewhere
- **Self-consumption ratio:** 63% — the battery + solar already do enormous work
- **Estimated URA current capture:** ~$34/yr (37% of residual) via AC Nudge + Solar Cover + Pre-Arrival + Fan Control + Arbitrage + EVSE control
- **Structural floor (physics-unavoidable):** ~$45/yr (battery empty by evening, intrinsically un-shiftable loads)
- **Pure-software headroom (gap between current and floor):** **~$13/yr**

This dramatically reframed the ROI calculation. $13/yr of personal-savings headroom doesn't justify a multi-cycle build by itself.

**Archive of this analysis:** `data/enphase/ANALYSIS_2026-05-13_TOU_Peak_Exposure.md` + `data/enphase/reports/2026-05-13_Energy_Report.pdf` (both gitignored — data is private).

### Step 3 — Reframing: "build it for others"

User clarified the strategic motivation isn't $13/yr in their own house. It's that URA might go community-deployable in the future, and a universal heuristic + load forecaster is the foundational engine that adapts URA to households with different climates, rate plans, battery sizes, EVs, etc. The personal-savings ROI is the wrong framing. The reusable building block (load forecaster) is the actual deliverable.

### Step 4 — External research: "don't reinvent the wheel"

Spawned research agent to survey the HEMS optimization landscape. Output preserved at `docs/planning/RESEARCH_2026-05-13_HEMS_optimization_landscape.md`. Key findings:

- **emhass core** (`optimization.py`, 3,247 LOC) is MILP via CVXPY + HiGHS solver, MIT licensed. Mature, battle-tested. ~60% of the repo is deployment cruft (web server, MQTT, config flow, container).
- **emhass's load forecaster does NOT use weather** — just AR lags + calendar features. This is its gap.
- **MPC literature** consensus: deterministic MILP-MPC, 24h horizon, 15-min step, re-solve every 15min absorbing forecast error. Typical reported savings 15-35% vs no optimization.
- **RL** is research-grade, not production. MPC beats RL in field trials. Skip.
- **Load forecasting state-of-practice:** LightGBM/XGBoost with weather + calendar exogenous features. Bayesian inference is used for uncertainty quantification on top of a point forecast, not as the point forecaster itself.

Initial recommendation: vendor `emhass/optimization.py` + replace its load forecaster with weather-aware LightGBM.

### Step 5 — Coupling-layer recon: the real architecture

User pushed back: "What's the coupling layer to Enphase? The prediction cycle is pretty short in a way that might be useless to the coupling layer."

Read `docs/ENERGY_MANAGEMENT_EXPLAINER.md` (the codicil-derived definitive doc) + relevant code:

- **Enphase coupling is Tier 2 reserve_soc**, not direct kW commands:
  - `number.enpower_482348004678_reserve_battery_level` — primary lever (the SOC floor)
  - `switch.enpower_482348004678_charge_from_grid` — secondary lever (storm prep + overnight arb)
  - Mode is locked to `self_consumption` per the codicil. Savings mode is prohibited because it surrenders battery control to Enphase's own (unreliable) optimizer.
- **URA already has a sophisticated optimizer** at this abstraction:
  - `BatteryStrategy.determine_mode()` runs every 5 minutes
  - Priority chain: Envoy-unavailable → grid-disconnect → storm-forecast → peak → mid-peak → off-peak
  - Per-season tables (summer / shoulder / winter) for the off-peak SOC drain target
  - SOC-conditional drain branches on **tomorrow's solar** forecast (Solcast): excellent / good / moderate / poor → drain-to-10% / 15% / 20% / 30%
  - Storm pre-charge via `charge_from_grid`
  - Coordinated EVSE on/off, Pool VSF speed, Smart plugs as secondary loads on same cycle

**Key conclusions from coupling-layer recon:**

1. **A 24h × 96-bucket MILP-MPC is overkill.** The output to Enphase is one number (reserve_soc). Only the "next-hour reserve_soc" line of a 96-bucket plan would ever be used. The MILP machinery exists to optimize across many buckets when you control each bucket directly — that's not our world.
2. **emhass is the wrong tool.** Its MILP optimizer is for kW-bucket scheduling. Our coupling layer is "set a floor every 5 min." 100-200 LOC of Python is the right size, not 3,247 LOC of vendored MILP.
3. **URA's existing architecture IS the universal heuristic.** Priority chain + per-season + per-TOU-period + forecast-driven. The "universal" promise was already fulfilled. The "build a universal heuristic" framing was redundant.
4. **15-min re-solve cadence is overkill** for a reserve_soc control surface that's slow by nature. Hourly or 2-hour load forecast horizons are sufficient.

### Step 6 — The actual gap

What URA's current optimizer is missing:

- **Tomorrow's LOAD forecast** (currently only branches on tomorrow's SOLAR)
- **Continuous drain-target calculation** (currently 4-bin lookup)
- **Confidence-weighted safety margin** (no uncertainty model)
- **Weather-aware load prediction** (URA collects weather features but doesn't predict load from them yet)

The deliverable that addresses all of these: **a weather-aware LightGBM load forecaster** trained on URA's existing `energy_history` + `external_conditions` tables.

### Step 7 — Data audit

What URA already collects (the training corpus is largely already built):

`external_conditions` table (~15-min, 90-day retention):
- outside_temp, outside_humidity
- weather_condition (categorical: "sunny", "cloudy", etc.)
- solar_production (live kW)
- forecast_high, forecast_low (today's projected)
- occupied_room_count, occupied_zone_count

`energy_history` table (15-min, 180-day retention — the ML-ready dataset):
- timestamp
- solar_production, solar_export, grid_import, grid_import_2
- battery_level
- **whole_house_energy** (the target variable)
- rooms_energy_total
- outside_temp, outside_humidity
- house_avg_temp, house_avg_humidity
- temp_delta_outside, humidity_delta_outside (pre-computed deltas)
- rooms_occupied
- day_of_week, hour_of_day, is_weekend
- tou_period (added v4.6.1)

**What's missing from state-of-the-art weather features:**
- Cloud cover %
- Wind speed
- Precipitation
- Multi-hour-ahead weather forecast vector (only today's high/low currently stored)
- Solar irradiance / DNI ground truth (currently inferred from solar_production)

These are all available via HA weather entities (Met.no, Open-Meteo, OpenWeatherMap) as state attributes — just not currently extracted into the URA tables.

---

## The plan

### v4.7.0 — Weather feature expansion (small, additive, forward-only)

**Goal:** Extend `external_conditions` + `energy_history` to log cloud cover, wind speed, precipitation, and a multi-hour weather forecast vector.

**Why first:** Forward-only data collection. No backfill. Lets the forecaster training corpus enrich while v4.7.0 is in soak. Cheap to ship; sets up v4.7.1.

**Scope:**
- Idempotent ALTER TABLE ADD COLUMN migrations on both tables (~6 new columns each)
- Update `_log_external_conditions_snapshot` to extract cloud / wind / precip / forecast-vector from the configured `weather_entity` attributes
- ~150-200 prod LOC + ~40 test LOC
- Tier 1 (additive, low risk)

**Deferred decisions:**
- Whether to store the full 24h forecast vector per snapshot (huge) or just key future points (4h, 8h, 24h)
- Whether to also pull Solcast irradiance forecast for direct DNI feature

### v4.7.1 — Weather-aware LightGBM load forecaster (Tier 2)

**Goal:** New prediction surface `predict_load(horizon_hours)` returning `(mean_load_kw, uncertainty)` per future bucket, trained on URA's data.

**Algorithm:** LightGBM via `skforecast.ForecasterRecursive`. Features:
- Calendar (hour, day-of-week, is_weekend, tou_period, season)
- Indoor state (house_avg_temp, house_avg_humidity, rooms_occupied)
- Outdoor weather (temp, humidity, cloud, wind, precip — pulled from v4.7.0's data)
- Multi-hour forecast vector (where we're going)
- Lags (load 1h ago, 24h ago, 7d ago — standard AR features)

**Output:** Per-horizon load prediction. Scored every prediction via v4.6.0 accuracy-pipeline pattern (write predicted vs actual to `prediction_results` with new `prediction_type='load_forecast'`).

**Scope:**
- New `domain_coordinators/load_forecaster.py`
- New `prediction_results` rows with `prediction_type='load_forecast'`
- New accuracy sensors on CM device (per-horizon Brier + hit rate)
- Trained on first boot using whatever historical data is available; retrained nightly
- ~400 prod LOC + ~150 test LOC
- Tier 2 (2 independent reviews + soak)

**Acceptance criteria:**
- After 7 days of operation: median absolute percent error (MAPE) < 15% for 1h-ahead, < 25% for 6h-ahead
- Sensor `sensor.ura_coordinator_manager_load_forecast_accuracy` shows non-null values within 24h of deploy
- LightGBM model is retrained nightly via existing nightly task infra (Bug Class #19 — `entry.async_create_background_task`)

### v4.7.2 — Wire forecaster into BatteryStrategy (small, plus shadow mode)

**Goal:** Replace the 4-bin solar-only drain target lookup with a continuous calculation using both forecasted solar AND forecasted load over the next 4-6 hours.

**Conceptual formula:**
```
target_reserve_soc = max(
    reserve_floor_min,
    (forecast_load_next_6h - forecast_solar_next_6h - cheap_off_peak_kwh_remaining)
    / battery_capacity_kwh
    + confidence_margin
)
```

Where `confidence_margin` widens when load forecast uncertainty is high (LightGBM gives this for free via per-prediction variance).

**Scope:**
- New method `BatteryStrategy._compute_continuous_drain_target()` reads the v4.7.1 forecaster
- Shadow mode: compute both the old (bucketed) and new (continuous) targets; log both; ACT on the old one. 7-14 day data collection.
- Cutover via Number entity or boolean (URA Mirror Pattern) — user opts in when shadow data shows the new target is consistently better
- ~150 prod LOC + ~80 test LOC
- Tier 1 (small change to existing optimizer; behind feature gate)

**Acceptance criteria:**
- Shadow data shows new target deviates from old target in measurable ways (not just noise)
- After cutover, observed grid imports during peak/mid-peak hours don't INCREASE
- Sensor `sensor.ura_coordinator_manager_drain_target_active` exposes which strategy is live

---

## Out of scope

- **Vendoring emhass.** Not needed; the existing optimizer is correctly shaped for our coupling layer.
- **MILP-MPC at 15-min granularity.** Coupling layer is reserve_soc — overkill.
- **Reinforcement learning.** Research-grade, not production. Sample efficiency is years.
- **Stochastic MPC.** 5-20× compute cost; marginal benefit at our residual headroom.
- **Tier 3 direct kW Enphase control.** Codicil prohibits; would need installer-level Envoy API access; not happening.
- **EV-specific optimizer.** EVs are just controllable loads under existing EVSE switch coordination. No separate stack.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| LightGBM model overfits early (insufficient training data) | MEDIUM | v4.7.0 forward-collection during 4-6 week training-data buildup before v4.7.1 ships; baseline against existing optimizer first |
| Weather forecast quality degrades during Texas winter intermittent-sun events | MEDIUM | Confidence-weighted margin widens safety floor when uncertainty is high |
| Forecaster regression breaks existing optimizer | HIGH | Shadow mode in v4.7.2 — never actually act on forecaster output until validated |
| Bug Class #19 (untracked task) — nightly retraining task | MEDIUM | Use `entry.async_create_background_task`; pattern-pinned in tests |
| Bug Class #34 (function-local imports) — LightGBM is a heavy dep | LOW | Function-local; lazy load inside `predict_load` first call |
| Adding LightGBM dep to URA's runtime | MEDIUM | Decide HACS vs add-on packaging in v4.7.0 |

---

## References

External research:
- `docs/planning/RESEARCH_2026-05-13_HEMS_optimization_landscape.md` — agent-produced literature review with citations (emhass, MPC, RL, LightGBM)

Codicil + existing architecture:
- `docs/ENERGY_MANAGEMENT_EXPLAINER.md` — the definitive codicil-derived doc on URA energy mgmt (BatteryStrategy, control surfaces, per-season tables)
- `docs/plans/TOU.md` — PEC 2026 Interconnect TOU rate schedule
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — `PEC_TOU_RATES` + `PEC_FIXED_CHARGES`
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — `BatteryStrategy.determine_mode()` (the current optimizer)
- `custom_components/universal_room_automation/domain_coordinators/energy_forecast.py` — current Solcast / weather entity integration
- `custom_components/universal_room_automation/database.py:407+` — `external_conditions` schema
- `custom_components/universal_room_automation/database.py` — `energy_history` schema (search "CREATE TABLE IF NOT EXISTS energy_history")

User-specific analysis (gitignored):
- `data/enphase/enphase_custom_report_2026-05-13.xlsx` — 310-day, 15-min Enphase Custom Report
- `data/enphase/ANALYSIS_2026-05-13_TOU_Peak_Exposure.md` — text analysis with the $142 unlocked / $92 residual / $34 URA captures breakdown
- `data/enphase/reports/2026-05-13_Energy_Report.pdf` — 6-page visualization report with surprising-energy-facts section
- `data/enphase/build_energy_report.py` — reproducible build script (re-run anytime with fresh Enphase data)

Related URA planning:
- `docs/planning/PLANNING_v4.6.x_winter_morning_peak_strategy.md` — original winter-mornings-specific plan, superseded by this doc
- `docs/PLANNING_FUTURE_ENERGY_SAVINGS_MODE.md` — explored savings-mode arbitrage; documented why we don't switch out of self_consumption
- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` — original energy coordinator design

---

## Decision gates (before committing v4.7.0)

1. **Confirm `BatteryStrategy.determine_mode()` does NOT currently consume a load forecast.** Spot-check the code; if it actually does have one (just less sophisticated), the v4.7.1 framing changes.
2. **Decide LightGBM packaging.** HACS deps via `manifest.json`'s `requirements` field is the cleanest path; verify HACS allows packages of this size. Alternative: optional add-on with shadow-mode-only first.
3. **User decision on community-deployability framing.** If URA stays single-tenant, the $13/yr personal headroom doesn't justify three sub-cycles; revisit scope.
4. **Final Tier classification.** v4.7.1 is the only one needing Tier 2; v4.7.0 + v4.7.2 are Tier 1. Confirm.

---

## Recall hint

To pick up this thread in a future session: **"Resume Advanced Energy Mgt v4.7.x — Forecaster-First"**

That phrase routes to this planning doc + the research memo + the user-specific data analysis. All four artifacts are sufficient to reconstitute the full context.
