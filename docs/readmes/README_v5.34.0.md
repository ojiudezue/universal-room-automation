# URA v5.34.0 — Predicted energy/cost tomorrow (forecast sensors)

Additive, display-only. Adds a tomorrow-scope to the existing predicted-forecast family
so a "predicted situation tomorrow" dashboard tile has a real consumption forecast to pair
with the Solcast solar forecast.

## What ships
- `sensor.universal_room_automation_predicted_energy_tomorrow` (kWh, ENERGY) — whole-house
  consumption forecast for tomorrow. Adds a native `"tomorrow"` period to
  `db.predict_energy` (mirrors the existing `"day"` branch but keys the similar-days lookup
  on **tomorrow's** weekday and uses **tomorrow's** forecast high — `forecast[1]` from the
  weather entity, via new `_get_forecast_temp_tomorrow`). `raw_net_kwh` (signed) +
  `forecast_temp_tomorrow` attrs.
- `sensor.universal_room_automation_predicted_cost_tomorrow` ($, USD) — trivial rate mirror
  of `predicted_cost_today` (signed; negative = net export credit).

## Safety
- Purely additive: `predict_energy` gains a `"tomorrow"` branch; the existing `"day"/"week"/
  "month"` branches are byte-behavior unchanged (regression guard
  `test_predict_energy_day_still_uses_today_weekday`). No decision consumer — display only.
- Reuses the canonical rate/export/forecast-temp helpers (byte-identical to the today
  siblings).

## Review
Tier 1: build + orchestrator verification (4 new tests pass; 7 existing predict-path tests
green — no regression to the shared `predict_energy`; full suite = known ordering-pollution
baseline, zero new failures).

## Live Validation
- **H1 — clean boot, no URA errors.**
- **H2 — sensors register + numeric.** `predicted_energy_tomorrow` (kWh) and
  `predicted_cost_tomorrow` ($) exist, numeric, `forecast_temp_tomorrow` attr set from the
  weather entity's day-2 forecast. Window: 15 min (after the 15-min prediction cache warms).
- **H3 — tomorrow ≠ today.** `predicted_energy_tomorrow` uses tomorrow's weekday/temp — its
  value differs from `predicted_energy_today` when tomorrow's forecast temp differs. Window: 1 h.
</content>
