# v4.7.0.1 — WPM Cleanup Hotfix (4 polish items from Cycle A post-review backlog)

**Date:** 2026-05-28 CDT
**Type:** Tier 1 polish hotfix (single review)
**Predecessor:** v4.7.0 (WeatherProviderManager foundation + EV TOU hardening)

Addresses 4 small items carried over from the v4.7.0 Cycle A reviewer post-review backlog. No behavior changes — all fixes are dead-code removal, public-API hygiene, or test honesty.

## Fix 1 — Delete dead `update_options()` (A5 + B10)

`WeatherProviderManager.update_options()` was never called. The CM options-update listener (`_async_update_listener`) does a full config-entry reload, not an in-place update. The dead method also carried a misleading Bug #14 reference in its docstring.

Deleted from `weather_manager.py:~173`.

## Fix 2 — Add public `divergence_threshold_f` property (4th-pass minor note)

`binary_sensor.WeatherDivergenceBinarySensor.extra_state_attributes` was calling `mgr._divergence_threshold_f()` (private method) directly. Public-API convention requires an accessor property for cross-module reads.

Added `@property divergence_threshold_f` to `WeatherProviderManager` that wraps `_divergence_threshold_f()`. Updated `binary_sensor.py` to call the property. The private method remains intact (it has internal callers).

## Fix 3 — Add `priority_rank_for(entity_id)` + wire to `WeatherActiveProviderSensor` (M3)

`WeatherActiveProviderSensor.extra_state_attributes` returned a hardcoded `"priority_rank": 0`. This was always wrong for any active provider that was not the primary.

Added `WeatherProviderManager.priority_rank_for(entity_id)` — returns 0-indexed rank of `entity_id` in the configured provider list (primary=0, fallback_1=1, fallback_2=2), or `None` if not present.

Updated `sensor.py` to compute the real rank for `mgr.active_provider`. When `active_provider` is `None`, the attribute is `None`.

## Fix 4 — Rename test class for honesty (B9)

`quality/tests/test_v47x_weather_manager.py::TestNoDirectWeatherStateReads` was a line-grep, not an AST walk. The name implied a more comprehensive check than it performs.

Renamed to `TestNoLiteralWeatherStateReads`. Updated docstring to state clearly: "Line-grep for literal `states.get('weather.*')` patterns; does not catch variable-based reads."

## Files changed

**Production code:**
- `custom_components/universal_room_automation/domain_coordinators/weather_manager.py` — removed `update_options()` method; added `divergence_threshold_f` property + `priority_rank_for()` method
- `custom_components/universal_room_automation/binary_sensor.py` — `mgr._divergence_threshold_f()` → `mgr.divergence_threshold_f`
- `custom_components/universal_room_automation/sensor.py` — hardcoded `"priority_rank": 0` → `mgr.priority_rank_for(active)`

**Tests:**
- `quality/tests/test_v47x_weather_manager.py` — renamed `TestNoDirectWeatherStateReads` → `TestNoLiteralWeatherStateReads`; updated docstring; added 11 new tests across 4 fix-verification classes

## Test count

- v4.7.0: 65 passing in `test_v47x_weather_manager.py`
- **v4.7.0.1: 76 passing** (+11 new tests)
- Both orderings pass 116/116: `test_v47x_ev_tou_hardening.py test_v47x_weather_manager.py` AND reverse

## Deliberately NOT in scope

The following items remain in `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` §H Post-Review Backlog and are deferred to Cycle B or a separate refactor cycle:

- **B4 (`_refresh_all_providers` split):** Requires a caller audit before any split is safe. Cycle B work.
- **M2 / A9 (DeviceInfo refactor):** All 3 new WPM sensors carry inline `DeviceInfo` instead of using the shared `_energy_device_info()` helper. Too broad for a polish hotfix — touching sensor constructors risks RestoreEntity hydration regressions.
- **B11 (private `_cached_*` reads in sensors):** `sensor.py` reads `mgr._provider_highs` directly in `WeatherDivergenceBinarySensor`. Style-only; consistent with existing URA sensor patterns. Acceptable until a broader private-accessor audit runs.
