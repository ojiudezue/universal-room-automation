# PLANNING v4.6.x — Winter Morning Mid-Peak Battery Strategy

**Date:** 2026-05-12
**Type:** Design cycle — option selection required before Tier 2 implementation
**Predecessor:** v4.5.0 Battery Strategy Redesign (arbitrage + EV mutual-exclusion)
**Status:** OPEN — option choice (A/B/C/D) + Enphase-native-TOU investigation pending

## Problem Statement

Winter household pattern (observed in user-provided Enphase Custom Report 2026-05-12):

- Battery fully discharges every night by ~03:00 in winter
- **Enphase TOU mid-peak window is 05:00–09:00** at elevated rate vs. off-peak (00:00–05:00)
- Result: ~8.5 kWh of grid import lands at mid-peak rate every winter morning
- Workaround under v4.5.0 arbitrage rules: hold `reserve_soc` artificially high overnight → costs evening discharge headroom + reduces solar-bank capacity during cool months

The arbitrage engine optimizes within a 24-hour rolling window but doesn't have a seasonal awareness of "the night-to-morning grid-import shape is the cost driver, not the daytime arb cycle."

## Data Reference

User-provided file: `dbb9a71d-5700967_custom_report.xlsx` (Enphase Custom Report, last 30 days winter)

Key observations from analysis:
- Battery hits SOC floor (typically `reserve_soc` ~10-15%) between 02:00–04:00
- Grid import 05:00–09:00 averaging ~2.1 kWh/hr during weekday occupancy ramp
- House load 05:00–09:00 dominated by: heat pump morning recovery + EV trickle (if scheduled) + kitchen/bathroom appliances
- Solar production doesn't meaningfully cover load until ~09:30–10:00 in winter

## Design Options

Four strategies on the table. **No option chosen yet** — this doc is the menu.

### Option A: Seasonal `reserve_soc` bump

- Detect winter season (month-based or HDD-based) and apply higher `reserve_soc` (e.g., 35-40%)
- Simplest implementation: 1-2 dynamic-floor lines + season detector
- **Tradeoff:** Costs evening discharge headroom across all winter nights, even nights when morning load is forecast low. Blunt instrument.

### Option B: Forecast-aware nightly hold

- Compute target morning SOC from forecast(load 05-09) + forecast(solar 05-09)
- Set `reserve_soc` per-night so battery has just enough at 05:00 to cover 05-09 grid import
- **Tradeoff:** Requires accurate 12hr-ahead load + solar forecasting. URA has Solcast for solar; load forecast is rougher. Complex but adaptive.
- **Risk:** Forecast miss → either over-reserves (leaves money on the table during evening peak) or under-reserves (still imports at mid-peak)

### Option C: Active off-peak grid charging

- Charge battery from grid during 00:00–05:00 off-peak window, target ~80-90% SOC by 05:00
- Battery then discharges through 05-09 mid-peak window, displacing grid import
- **Tradeoff:** Battery cycle wear (1 extra full cycle/night = ~365 cycles/year on top of solar arb cycling). Off-peak buy + mid-peak avoidance spread = ~$0.10/kWh saved on ~8 kWh = $0.80/night = $240/winter quarter. Net positive only if cycle-cost < arb spread.
- **Question:** Does Enphase API support scheduled grid-charge command? If yes, low integration cost.

### Option D: Two-target SOC state machine

- Two daily SOC targets: `morning_target` (05:00) and `evening_target` (16:00)
- Battery management state machine drives toward whichever target is next
- Subsumes Option B (per-night morning target) + handles evening peak separately
- **Tradeoff:** Most complex. Requires re-architecting parts of `energy.py` arbitrage logic to support multi-target optimization. ~2-3 cycle build.

### Side-track: Enphase native TOU schedule

Before building any of A-D, investigate whether **Enphase Enlighten** has a native "TOU import-shifting" mode. If yes:
- URA cedes morning-peak coverage to Enphase's TOU profile
- URA arbitrage continues to run for solar-side optimization (afternoon shift)
- Zero new URA code; just Enphase web-UI configuration + verify it doesn't fight URA's arbitrage signals

**This is the lowest-effort path if it exists.** Should be the first investigation step.

## Acceptance Criteria (provisional — final criteria depend on option chosen)

### For all options
- **Verify:** Battery SOC at 05:00 sufficient to cover 05-09 grid load (target: <2 kWh grid import 05-09 weekday avg)
- **Sensor:** New `sensor.ura_energy_morning_peak_grid_import` showing daily 05-09 grid-import kWh
- **Sensor:** New `sensor.ura_energy_morning_peak_strategy_savings` showing weekly $ saved vs. baseline (no-strategy month)
- **Live:** After 7 days, weekly 05-09 grid-import kWh should drop ≥50% from current ~10 kWh/day baseline

### Option-specific
- **A:** `number.ura_energy_winter_reserve_soc_floor` setting honored when winter detector fires; logbook shows floor change at season boundary
- **B:** `sensor.ura_energy_forecast_morning_load_5_9` populated nightly; reserve_soc adjusts visibly per forecast
- **C:** `switch.ura_energy_offpeak_grid_charge` controls scheduled charge; battery SOC ramps 00:00–05:00 when on
- **D:** State machine debug sensor exposes current target + transitions

## Open Questions

1. **Enphase TOU mode** — does the API or Enlighten UI expose this? Investigation first.
2. **Battery cycle accounting** — what's the current battery cycle count? Manufacturer's rated cycles? Option C only pays if remaining cycles > 365 × planned-deployment-years.
3. **EV charging interaction** — EV trickle-charge schedule during 00-05 off-peak overlap with Option C grid-charging would compete for grid headroom. Mutex required.
4. **Texas grid event signals** — if ERCOT issues a conservation alert, the strategy should pause grid charging. Existing URA hook?
5. **Solar bank interaction** — currently arbitrage holds some SOC for solar-bank refilling. Morning-peak strategy must not stomp solar-bank logic.

## Sequence

1. **Investigation phase** (no code, ~1-2 hours)
   - Read Enphase API docs for TOU schedule support
   - Check battery cycle count + rated cycles
   - Verify EV charge schedule current behavior
   - Read `energy.py` arbitrage code for solar-bank reservation logic
2. **Option selection** (user decision)
3. **Implementation cycle** — Tier 2 feature, separate planning doc per chosen option

## Non-goals for this cycle

- Summer afternoon peak strategy (different problem; existing arbitrage handles solar-shift correctly)
- EV charging scheduler redesign (separate planning doc: `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md`)
- Whole-house demand response (separate, future)

## References

- `dbb9a71d-5700967_custom_report.xlsx` — Enphase 30-day winter data (user upload)
- `docs/planning/PLANNING_v4.5.0_battery_strategy_redesign.md` — v4.5.0 arbitrage rules baseline
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — arbitrage decision cycle (lines ~1500-1800)
- BACKLOG: "Winter morning peak strategy" entry to be filed against this doc

## Next Step

User chooses: **investigate Enphase TOU first?** Or commit to A/B/C/D directly?
