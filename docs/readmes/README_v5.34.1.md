# URA v5.34.1 — Forecast temp via get_forecasts (fixes deprecated attribute)

Hotfix. HA removed the `weather.forecast` **state attribute** (2024.4); forecasts now
come from the `weather.get_forecasts` **service**. The predicted-energy/cost family read
the dead attribute, so:
- `predicted_energy_tomorrow` / `_cost_tomorrow` (v5.34.0) read `unknown` (null forecast temp).
- The existing `predicted_energy/cost_{today,week,month}` + heating/cooling-need sensors
  silently fell back to **current** temp — functional but not a real forecast.

## Fix
- New cached `AggregationEntity._refresh_forecast_cache()` fetches the daily forecast via
  `weather.get_forecasts` (type=daily) for the configured `CONF_WEATHER_ENTITY`, cached on
  `hass.data` with a **15-min TTL** (matches the prediction cache) — at most one service
  call per 15 min across all 10 predicted sensors (verified behaviorally + at source).
- Unified `_get_forecast_temp(day_offset=0, field="temperature")`: `0`→today's high,
  `1`→tomorrow's high. Fallback chain: `forecast[day_offset]` → `forecast[0]` → current
  `attributes.temperature` → None. Never `unknown` when a current temp exists.
- Removed the last deprecated-attribute read (`PredictedHeatingNeedSensor`, now uses
  `field="templow"`).

## Behavioral change (intended correction)
today/week/month predicted values now use **real forecast highs** instead of current temp —
a repair of the pre-existing silent degradation. Values will shift accordingly.

## Review
Tier 1: build + orchestrator verification (10 new tests pass — service-shape, empty/raise
fallback, cache-reuse one-call-per-TTL, source-level assertion that all 10 sensors call
refresh; existing predicted_energy_tomorrow tests green; full suite = known ordering-
pollution baseline, zero new failures). Display-only, no decision consumer.

## Live Validation
- **H1 — clean boot, no URA errors.**
- **H2 — tomorrow sensors populate.** `predicted_energy_tomorrow` / `_cost_tomorrow` become
  numeric (no longer `unknown`); `forecast_temp_tomorrow` attr = tomorrow's real high
  (~98°F per the live daily forecast). Window: 15 min (cache warm).
- **H3 — real forecast, not current temp.** `forecast_temp_tomorrow` (98) ≠ current temp
  (89); today/week/month values shift vs the pre-fix current-temp basis. Window: 15 min.
</content>
