# URA Backlog — As of v4.0.4 (Apr 9, 2026)

## Bugs (fix first)

1. **Config flow save timeout** — Options persist to disk but `async_reload` from options flow update listener times out. Manual reload works. Blocks ALL config changes.
   - Investigate: `_async_update_listener` uses `await async_reload` — try `hass.async_create_task` to decouple from options flow context.
   - Workaround: manually reload entry after save.

2. **Energy TOU blocking I/O** — `energy_tou.py:68` synchronous `filepath.read_text()` on event loop. HA 2026.x flags this.
   - Fix: `await hass.async_add_executor_job(filepath.read_text)`

3. **5 disabled HA automations use deprecated mireds** — Need `color_temp` → `color_temp_kelvin` migration when re-enabled. Tracked since v3.9.6.

## Bayesian Remaining

4. **B3: Pre-emptive Actions** — High-confidence Bayesian predictions trigger room preparation (lights, HVAC pre-conditioning). Configurable confidence threshold. Integration with HVAC pre-arrival and chained automations.

5. **B4: Energy Integration** — Occupancy-weighted consumption prediction. Extend DailyEnergyPredictor with predicted occupancy patterns. Improve forecast accuracy and battery strategy.

## Optimization Coordinator (5 phases)

6. **Phase 1: Room Health Score** (~400 lines) — 6 dimensions per room. Dedicated sensor per room + NM alerts for critical degradation.
7. **Phase 2: Zone + House Health + Daily Digest** (~400 lines) — Aggregate scores. House summary sensor. Morning digest via NM.
8. **Phase 3: Prediction Validation + Weekly Report** (~300 lines) — Track Bayesian accuracy. Flag degradation. Weekly NM report.
9. **Phase 4: Rule-Based Optimization** (~300 lines) — Tier 1 deterministic rules. Built-in goals: energy, comfort, security.
10. **Phase 5: LLM-Assisted + Agentic Mode** (~500 lines) — Tier 2 Claude API batch analysis. User goals. Autonomous config adjustments.

## Deferred Entities (from DEFERRED_TO_BAYESIAN.md)

| Entity | Status | Target |
|--------|--------|--------|
| WeekdayMorningOccupancyProbSensor | DONE (B1) | v4.0.0 |
| WeekendEveningOccupancyProbSensor | DONE (B1) | v4.0.0 |
| OccupancyPatternDetectedSensor | DONE (B1) | v4.0.0 |
| OccupancyPercentageTodaySensor | DONE (B2) | v4.0.2 |
| TimeOccupiedTodaySensor | DONE (B2) | v4.0.2 |
| TimeUncomfortableTodaySensor | DONE (B2) | v4.0.2 |
| AvgTimeToComfortSensor | DONE (B2) | v4.0.2 |
| OccupancyAnomalyBinarySensor | DONE (B2) | v4.0.2 |
| ClearDatabaseButton | DONE (B1) | v4.0.0 |
| EnergyWasteIdleSensor | Deferred | B4 or Optimizer P1 |
| MostExpensiveDeviceSensor | Deferred | B4 |
| OptimizationPotentialSensor | Deferred | Optimizer P4 |
| EnergyCostPerOccupiedHourSensor | Deferred | B4 |
| EnergyAnomalyBinarySensor | Deferred | B4 or Optimizer |
| OptimizeNowButton | Deferred | Optimizer P4 |
| SIGNAL_COMFORT_REQUEST | Deferred | B3 |

## Other Tracked Items

- **Jaya + Ziri bedrooms** — need motion sensors added via config flow (options saved, blocked by bug #1)
- **BlueBubbles webhook** — BB server webhook for inbound iMessage (operational setup, not code)
- **Dashboard v3 polish** — built, not deployed
- **Diagnostic logging downgrade** — person coordinator WARNING → DEBUG after stabilization

## Recommended Priority

1. Config flow save fix (unblocks everything)
2. B3 pre-emptive actions
3. B4 energy integration
4. Optimizer Phase 1
