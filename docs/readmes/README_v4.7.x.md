# URA v4.7.x — Weather Provider Manager + Apparent-Temp Primitive (Cycle A)

**Released:** TBD (deploy-time stamping fills version)
**Tier:** Tier 2-DB (user-invoked — new feature with cross-coordinator surface area)

## Summary

Cycle A of Dynamic Preset Management. Replaces single-provider weather reliance with a ranked-list manager (up to 3 providers in priority order). Adds failover, staleness detection, and divergence flagging. Exposes an apparent-temperature primitive as a first-class concept for EC and future Dynamic Preset Override (Cycle B).

## What ships in Cycle A

### New module: `domain_coordinators/weather_manager.py`

`WeatherProviderManager` — singleton per integration entry at `hass.data[DOMAIN]["weather_manager"]`.

- Supports Primary / Secondary / Tertiary ranked weather providers
- State-change-driven health re-evaluation (no polling timers)
- Staleness detection: entity last_changed older than `CONF_WEATHER_STALENESS_MAX_HOURS` (default 6h) → STALE
- Failover: first healthy provider in priority list becomes active; INFO log on transition; `SIGNAL_WEATHER_PROVIDER_CHANGED` dispatched
- Divergence detection: when ≥2 healthy providers differ by ≥ `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` (default 5°F), divergence binary sensor flips ON + WARNING log + `SIGNAL_WEATHER_DIVERGENCE_DETECTED`
- Apparent-temp probe: reads `apparent_temperature` (Met.no, Pirate Weather, OWM) or `temperature_feels_like` (NWS legacy) from `weather.get_forecasts` response; falls back to raw temperature with `apparent_confidence = "fallback_raw"` flag
- Divergence uses median value as authoritative when multiple providers disagree

Public API:
- `async get_today_forecast() -> WeatherForecast | None`
- `current_apparent_temp() -> tuple[float | None, float]`
- `baseline_delta_for_zone(zone_id, preset) -> float | None`

### New sensors (3 entities on URA: Energy Coordinator device)

| Entity | State | Purpose |
|---|---|---|
| `sensor.ura_weather_active_provider` | active entity_id / `none` / `all_stale` | Which provider is serving forecasts |
| `sensor.ura_weather_apparent_forecast_high` | float °F | Today's apparent high from active provider |
| `binary_sensor.ura_weather_divergence` | on/off | Providers disagree beyond threshold |

### Config-flow additions (CM → Energy step)

Three new fields added to the existing Energy step alongside `CONF_ENERGY_WEATHER_ENTITY` (Primary):

- **Secondary weather provider** (`CONF_ENERGY_WEATHER_FALLBACK_1`) — entity_id, optional
- **Tertiary weather provider** (`CONF_ENERGY_WEATHER_FALLBACK_2`) — entity_id, optional
- **Weather staleness limit** (`CONF_WEATHER_STALENESS_MAX_HOURS`) — slider 1-24h, default 6h
- **Divergence threshold** (`CONF_WEATHER_DIVERGENCE_THRESHOLD_F`) — slider 1-20°F, default 5°F

### Migration of existing weather consumers (A4)

- `energy.py:_update_forecast_temps()` — routes through `WeatherProviderManager.get_today_forecast()` when available; falls back to legacy direct-service-call path
- `energy.py:_get_active_weather_entity()` — new helper; EC's weather reads (DB logging, external conditions) use the manager's active provider
- `signals.py:EnergyConstraint` — `apparent_forecast_high_temp: float | None = None` added additively alongside existing `forecast_high_temp` (Bug #37 — back-compat preserved)

## Bug class compliance

All 12 bug classes from the plan's compliance matrix addressed. Key highlights:
- **#5 (startup race):** `get_today_forecast()` returns None until first healthy probe
- **#38 (unsub):** all `async_track_state_change_event` handles captured in `_unsub_handles`; cleaned in `async_teardown()`
- **#42 (lambda):** `_handle_provider_state_change` is a `@callback`-decorated bound method; `async_create_task` takes a named coroutine

## Live validation checklist (Review D)

1. `sensor.ura_weather_active_provider` → shows a `weather.*` entity_id within 60s of restart
2. `sensor.ura_weather_apparent_forecast_high` → shows a numeric value matching active provider's apparent_temperature
3. `binary_sensor.ura_weather_divergence` → `off` when only one provider; `on` when second provider added with intentionally different forecast
4. Disable primary weather entity in HA UI → active sensor flips to secondary within 5s + INFO log appears
5. `EnergyConstraint` payload includes `apparent_forecast_high_temp` field (check HA developer tools → dispatcher events)
6. Zero new "untracked task" or "frame-helper" warnings in 1h post-restart

## Cycle B dependency

Cycle B (Dynamic Preset Override Source) is a separate future cycle. It depends on Cycle A being live and stable for at least one release cycle before starting. Do not build Cycle B until:
1. This Cycle A live validation passes
2. Guest Mode Phase 1's `OverrideEngine` is shipped and stable
