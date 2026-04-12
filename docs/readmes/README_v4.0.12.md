# v4.0.12 — Envoy Auto-Derive Config

**Date:** 2026-04-12

## Summary

One entity picker in the Energy Coordinator config flow auto-derives all 13 Envoy entity IDs from the serial number. Eliminates hardcoded old serial (202428004328) across Energy, HVAC, billing, and forecast coordinators. Future Envoy hardware replacements require changing a single config field.

## Problem

The Envoy gateway was physically replaced (serial 202428004328 -> 482543015950). 14 Envoy entity IDs were hardcoded with the old serial across `energy.py`, `energy_forecast.py`, `energy_billing.py`, and `hvac_predict.py`. All old entities showed "unavailable" — Energy and HVAC coordinators were blind.

## Changes

### D1: Serial extraction + entity derivation (`energy_const.py`)
- Added `CONF_ENERGY_ENVOY_ENTITY` config key + 8 new CONF keys for previously hardcoded entities
- Added `extract_envoy_serial()` — regex extracts serial from any Envoy entity ID
- Added `derive_envoy_config()` — returns 13 CONF_ENERGY_* keys mapped to derived entity IDs
- Removed unused `DEFAULT_PRODUCTION_TODAY_ENTITY`

### D2: Auto-derive wiring (`__init__.py`)
- Moved `energy_entity_config` build + auto-derive logic BEFORE Energy-enabled guard (prevents `UnboundLocalError` when Energy disabled + HVAC enabled)
- Passes `net_power_entity` to HVACCoordinator from the shared entity config

### D3: Resolved entity attributes (`energy.py`)
- 8 resolved entity instance attributes replace bare `DEFAULT_*` constants in `hass.states.get()` calls
- Expanded `_build_entity_map` with `grid_consumption` and `battery_capacity` keys
- CostTracker now receives `net_power_entity` and `solar_entity` (was using hardcoded defaults)
- DailyEnergyPredictor now receives `battery_soc_entity`

### D4: Forecast entity wiring (`energy_forecast.py`)
- Added `battery_capacity_entity` parameter, replacing bare `DEFAULT_BATTERY_CAPACITY_ENTITY`

### D5: HVAC predictor fix (`hvac_predict.py` + `hvac.py`)
- Replaced hardcoded entity string with configurable `net_power_entity` parameter
- Removed the only direct hardcoded serial in runtime code outside `energy_const.py`

### D6: Dead constant cleanup (`energy_billing.py`)
- Removed `DEFAULT_GRID_IMPORT_ENERGY` and `DEFAULT_GRID_EXPORT_ENERGY` (never referenced)

### D7: Config flow (`config_flow.py` + `strings.json`)
- Added Envoy entity picker as first field in Energy Coordinator config step

## Review Findings Fixed
- **CRITICAL**: `energy_entity_config` scoped inside Energy-enabled guard caused crash when Energy disabled + HVAC enabled
- **HIGH**: CostTracker not receiving resolved entities — billing would silently break on serial change
- **MEDIUM**: DailyEnergyPredictor missing `battery_soc_entity` — degraded predictions on serial change
- **MEDIUM**: Enpower exclusion undocumented in `derive_envoy_config` docstring

## Files Modified (10)
- `domain_coordinators/energy_const.py`
- `domain_coordinators/energy.py`
- `domain_coordinators/energy_forecast.py`
- `domain_coordinators/energy_billing.py`
- `domain_coordinators/hvac_predict.py`
- `domain_coordinators/hvac.py`
- `__init__.py`
- `config_flow.py`
- `strings.json`
- `quality/tests/test_envoy_auto_derive.py` (14 tests)

## Tests
- 14 new tests: serial extraction, derivation, auto-derive wiring, explicit override, backward compat, HVAC predictor
- Full suite: 1682 passed (67 pre-existing failures unchanged)
