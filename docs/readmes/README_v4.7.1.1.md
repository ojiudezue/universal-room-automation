# v4.7.1.1 — Translations Hotfix

**Type:** Hotfix (strings-only, no Python changes)
**Base:** v4.7.1

## Problem

v4.7.0 and v4.7.1 shipped with 20+ new CONF keys, a new `zone_dynamic_preset` menu option, and new WPM weather config fields — all without translation entries. HA's frontend hides menu options whose labels are missing, making the Dynamic Preset configuration step unreachable from the UI.

## What Was Labeled

### 1. `zone_config_menu` menu option
- `zone_dynamic_preset` — "🌤️ Dynamic Preset (Weather-Driven)"

### 2. `zone_dynamic_preset` step (20 fields)
New form step with title, description, and full `data` + `data_description` for all per-zone bucket fields:
- `zone_dynamic_preset_enabled` — enable toggle
- `zone_dynamic_preset_offset` — zone bias offset (0–3°F)
- `zone_dynamic_preset_reset_offset_guest` — reset offset under guest mode
- `zone_dynamic_preset_sleep_enabled` — apply to sleep preset
- 8 home-preset bucket fields (cool/mild/hot/extreme × low/high)
- 8 sleep-preset bucket fields (cool/mild/hot/extreme × low/high)

### 3. WPM weather fields in `coordinator_energy` step (4 fields)
- `energy_weather_fallback_1` — Secondary/Fallback 1 weather entity
- `energy_weather_fallback_2` — Tertiary/Fallback 2 weather entity
- `weather_staleness_max_hours` — staleness limit slider (1–24h)
- `weather_divergence_threshold_f` — divergence threshold slider (1–20°F)

### 4. Validation error messages (6 new)
- `dynamic_preset_bucket_required_cool/mild/hot/extreme` — all 4 buckets required
- `dynamic_preset_range_invalid` — deadband violation
- `dynamic_preset_sleep_below_floor` — sleep high below 74°F floor

## Files Changed
- `custom_components/universal_room_automation/strings.json`
- `custom_components/universal_room_automation/translations/en.json`

## No Python Changes
All changes are strings only. No behavior was modified.
