# v5.103.92: House sensor correctness fixes

Card: HOUSE-SENSOR-CORRECTNESS-1. Source: `docs/planning/AUDIT_house_sensors_correctness_2026_10_25.md`. Tier 2, three framing-disjoint reviews (A correctness, B lifecycle/ripple, C mutation), all findings fixed. Deploy risk LOW-MEDIUM: one value (consumption forecast factor) feeds the EV drain-precedence house-load estimate on `max_span_r1` installs.

## Energy (fix/house-energy-correctness)
- **Consumption forecast factor no longer pinned at 1.3.** The factor recomputes each day's error from predicted vs actual (ignores the stored percent), skips pairs outside 10–240 kWh (removes the 743/1,144/1,204 kWh poisoned predictions), and caps each error at ±60% (`FACTOR_PCT_ERROR_CLAMP`, `energy_forecast.py`). Restart-safe. Effect: predicted consumption drops ~23% toward actual. On `max_span_r1` installs this lowers `base_kw` in `_dp_house_load_kw` (intended). This house now uses `live_span` (operator, 10-26).
- **Whole-house cost today** shows the Energy Coordinator's `cost_today` (~$4.75), not lifetime counter × rate ($1,978).
- **Predicted cost** no longer adds delivery twice when the TOU rate already includes it.
- **Predicted energy** excludes today's partial day and the current partial week/month from its history.

## Diagnostics (fix/house-diagnostics-correctness)
- **Tripped-breaker anomalies:** a circuit at ≤5 W counts as tripped only if its learned baseline says it almost never idles (mean − 2σ > 5 W, ≥60 samples; `TRIPPED_BREAKER_EXPECTED_ON_SIGMA`). Critical circuits (name contains fridge/freezer/sump/well/pump) bypass that gate with their own measured idle windows (`TRIPPED_BREAKER_CRITICAL_IDLE_S`: fridge/freezer 1800 s, pumps 9000 s). Simulated on the last 7 days: 583 false CRITICAL rows → 0. Real-trip alert delay: fridge/freezer ≤35 min, pumps ≤155 min.
- **Next-state ETA** = median remaining time among past stays longer than the time already elapsed (was total median).
- **Safety diagnostics** `sensors_available` counts live-available configured sensors (was the total).

## Rooms (fix/scanner-areas-own-area)
- A room's own area is stripped from **BLE Scanner Areas** on save and ignored at runtime. The 12 live rooms that listed it were cleaned by config on 10-26.
- UI text: scanner areas label/description rewritten; **Adjacent rooms** now has a label and description (it showed the raw key).

## Config changes made 10-26 (not code)
- `select.ura_energy_coordinator_dp_house_load_source` → `live_span`.
- Recorder: un-excluded `sensor.universal_room_automation_predicted_energy_today`, `..._whole_house_energy_today`, `..._whole_house_power` (excluded by mistake 10-20). Effective at this restart.

## Known limits / deferred
- An always-on but highly variable circuit outside the critical name list can no longer raise tripped_breaker (review A). Critical windows rest on one week of data.
- Deferred: TOU-blended predicted cost; a better energy history source (daily import wrong 4 of 8 days, 20–29% under-read); tomorrow-forecast model; purge of the old 583 anomaly rows.

## Reviews and tests
A: scanner FIX-REQUIRED (decorator misplaced, fixed 7a690736f + test), energy/diagnostics SHIP. B: diagnostics M1 (cycling critical loads would never alert) fixed with the critical list + measured windows; energy SHIP; three branches merge clean. C: 54 sites, 45 RED; real gaps filled with tests (fb687c048, 72ef7159a, d03237106). Full-suite name-diff first showed 8 order-dependent failures (old test files leaking a frozen dt_util clock, re-imported NM/safety modules, re-installed HA stubs); test-only fixes 9ee08a7e7, 847db5db3. Final run on 65ed79536: 18,510 passed, 0 failed.

## Live acceptance criteria (prospective)
- No ERROR from universal_room_automation after restart.
- `sensor.universal_room_automation_whole_house_cost_today` within a few cents of the Energy Coordinator cost today.
- Energy coordinator forecast adjustment factor < 1.3; forecasted consumption within ~25% of recent actual (115–135 kWh/day).
- No new `tripped_breaker` CRITICAL rows for idle circuits in the first hours.
- Safety diagnostics `sensors_available` < total while known-dead sensors are dead.
- The three un-excluded sensors write new recorder rows.
