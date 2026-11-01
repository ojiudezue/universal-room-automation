# v5.103.87: daily solar forecast restored, regime next-room check made real, work log at ship

Cards: EC-PREDICTOR-SOLCAST-UNWIRED-1, REGIME-NEXT-ROOM-ACCURACY-JSON-COMPARE-1, WORKLOG-APPEND-AT-SHIP-1. Tier 1 each, one review each (SHIP). Deploy risk: LOW (one constructor argument pair, two SQL expressions, deploy tooling).

## Changes
1. **Solcast into the daily predictor** (`energy.py` ~731). `DEFAULT_SOLCAST_TODAY/REMAINING_ENTITY` became `None` in 36b08ba78, and `DailyEnergyPredictor` was built without the Solcast kwargs, so it had no solar source since 10-13: the daily energy forecast was blank and `battery_full_time` reported `missing_input=solcast`. It now gets `ec.get(CONF_ENERGY_SOLCAST_TODAY_ENTITY / _REMAINING_ENTITY)`, the same keys BatteryStrategy reads.
2. **Regime next-room accuracy-drop** (`regime_detector.py`). `next_room` rows store `predicted_value` as JSON (`{"top": ...}`); both hit-count queries compared the raw JSON to `actual_value`, so hits were always 0 and the check could never fire. They now compare `json_extract(predicted_value,'$.top')`, guarded by `json_valid()` so legacy plain-string rows compare verbatim.
3. **Work log at ship** (`scripts/worklog_ship.py`, `deploy.sh` step 4b). Each deploy appends one index line to `docs/planning/WORKLOG_<YYYY-MM>_session.md`; idempotent per version, warn-only.

## Tests
`test_ec_predictor_solcast_wired.py`, `test_regime_next_room_json_compare.py`, `test_worklog_ship.py`. Full suite on merged develop before deploy.

## Live acceptance criteria (prospective)
- **Live:** within one decision cycle of restart, `sensor.ura_energy_coordinator_energy_forecast_today` is numeric, and `battery_full_time` no longer reports `missing_input=solcast`.
- **Live:** the regime check fires only in the weekly digest; none expected now (top-1 is above the usual-room baseline per v5.103.85). In-suite proof: a JSON row whose `top` equals `actual_value` counts as a hit.
- **Live:** this deploy appends a `v5.103.87` line under "Release index" in `WORKLOG_2026-10_session.md`.
- **Discriminator:** under the old wiring the forecast stays `unknown`/blank; a different failure (Solcast itself stale) would show a number that disagrees with `sensor.solcast_pv_forecast_forecast_today`.

## Validated 2026-11-01 (retrospective)

Evaluated once on 2026-11-01 (v5.103.93 loaded; read-only; times UTC).

| Criterion | Result | Evidence |
|---|---|---|
| `energy_forecast_today` numeric | PASS | `sensor.ura_energy_coordinator_energy_forecast_today` = -42.0 (11-01 15:12:56), `predicted_production_kwh` 83.3826. |
| `battery_full_time` no longer `missing_input=solcast` | PASS (new gap seen) | attrs `battery_full_time: null`, `basis: unavailable`, `missing_input: soc` (not solcast). A separate missing SOC input is a different issue; worth a look if not already carded. |
| Forecast agrees with Solcast (discriminator) | PASS | `sensor.solcast_pv_forecast_forecast_today` = 83.3826, identical to `predicted_production_kwh`. |
| Regime next-room check fires only in the weekly digest; none expected | PASS (weak) | `regime_event_notification_log` 0 rows, `regime_weekly_digest_queue` 0 rows. Absence only; the JSON-compare behaviour is proven in-suite. |
| Deploy appends `v5.103.87` under "Release index" | PASS | `docs/planning/WORKLOG_2026-10_session.md:241`: "2026-10-24 07:04 **v5.103.87** ...". |
