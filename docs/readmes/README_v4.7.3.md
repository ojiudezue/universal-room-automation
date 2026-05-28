# URA v4.7.3 — Baseline Preset Editor + DPM Number Entity Migration

**Release date:** 2026-05-28
**Tier:** Tier 1 (single adversarial review pass)
**Scope:** D1 new config-flow step, D2 PresetManager override logic, D3 24 CONF/DEFAULT constants, D4 DPM number entity migration

**Trigger:**
- v4.7.2 closed the DPM/Guest Mode UI gaps for master toggles but left two DPM number entities orphaned on the wrong (Energy Coordinator) device.
- House-wide seasonal baselines (`SEASONAL_DEFAULTS`) were hardcoded with no UI surface to edit them.

---

## Headline Changes

### D1 — Baseline Preset Editor form step

A new **Baseline Presets (Seasonal)** step is now reachable via:
Settings → Devices & Services → URA Coordinator Manager → Configure → HVAC → Baseline Presets (Seasonal)

The form renders 24 numeric inputs organized as 12 rows (3 seasons × 4 presets), each row showing a cool_high and heat_low field. Fields are prefilled with the current `SEASONAL_DEFAULTS` values for fresh installs, or with previously saved values for users who have already configured them.

- **Validation:** Each row's cooling setpoint must be at least 3°F above the heating setpoint. Form rejects save with an intelligible error if any row fails.
- **Seasons:** Summer (Jun–Sep), Shoulder (Mar–May, Oct–Nov), Winter (Dec–Feb)
- **Presets:** Home, Sleep, Away, Vacation

### D2 — PresetManager.get_seasonal_setpoints() prefers overrides

`hvac_preset.py:get_seasonal_setpoints()` now checks CM `entry.options` for per-CONF overrides before falling back to `SEASONAL_DEFAULTS`. Per-CONF granularity — editing only one field does not silently override the other 23. Existing users with no saved overrides see zero behaviour change.

Changes take effect at the next 5-minute HVAC decision cycle (no new dispatcher signal).

### D3 — 24 new CONF keys + DEFAULT constants

24 new `CONF_HVAC_BASELINE_<SEASON>_<PRESET>_<DIM>` string constants and matching `DEFAULT_HVAC_BASELINE_*` integer constants added to `hvac_const.py`. All DEFAULT values mirror the existing `SEASONAL_DEFAULTS` hardcoded values for backward compatibility.

A module-level `_BASELINE_CONF_MAP` dict maps `(season, preset)` tuples to `(conf_cool_key, conf_heat_key)` pairs for O(1) lookup on every HVAC decision cycle.

### D4 — DPM Number Entities migrated to HVAC Coordinator device

Two number entities that were incorrectly associated with the Energy Coordinator device have been moved to the HVAC Coordinator device where they belong (DPM is an HVAC feature):

| Entity | Old device | New device | Unique ID | New label |
|---|---|---|---|---|
| `DynamicPresetDwellMinutesNumber` | URA: Energy Coordinator | URA: HVAC Coordinator | `{DOMAIN}_energy_dynamic_preset_dwell_minutes` (unchanged) | `03 · Dynamic Preset Dwell (minutes)` |
| `DynamicPresetHysteresisFNumber` | URA: Energy Coordinator | URA: HVAC Coordinator | `{DOMAIN}_energy_dynamic_preset_hysteresis_f` (unchanged) | `04 · Dynamic Preset Hysteresis (°F)` |

The `__init__.py` v4.7.2 D2 migration helper was refactored from single-entity inline code into a loop over `_HVAC_DEVICE_MIGRATIONS` — a list of 3 `(platform, unique_id)` tuples covering the D2 switch plus both D4 numbers. Entity lookup uses `async_get_entity_id(platform, DOMAIN, unique_id)` — the HA-correct pattern verified live on 2026-05-28.

**Numeric prefix audit:** HVAC Coordinator device now shows entities in sort order:
- `01 ·` Custom Preset Ranges (HVACGuestModeActuationSwitch, v4.7.2 D3)
- `02 ·` Dynamic Preset Auto-Adjust (HVACDynamicPresetSwitch, v4.7.2 D2)
- `03 ·` Dynamic Preset Dwell (minutes) (DynamicPresetDwellMinutesNumber, v4.7.3 D4)
- `04 ·` Dynamic Preset Hysteresis (°F) (DynamicPresetHysteresisFNumber, v4.7.3 D4)

No prefix collision with existing entities.

---

## TL;DR

v4.7.3 gives the house-wide HVAC temperature baselines a proper config UI (previously hardcoded), makes `get_seasonal_setpoints()` respect those saved values at runtime, and moves the two remaining DPM knobs to the right device card. All four changes are tightly scoped; no new entities, no schema changes, no new dispatcher signals.

---

## What's Changed

### Modified files

| File | What changed |
|---|---|
| `config_flow.py` | Added `"hvac_baseline_presets"` to `coordinator_hvac` menu; added `async_step_hvac_baseline_presets()` form step (~140 LoC). |
| `domain_coordinators/hvac_const.py` | Added 24 `CONF_HVAC_BASELINE_*` constants, 24 `DEFAULT_HVAC_BASELINE_*` constants, `BASELINE_MIN_DEADBAND = 3`. |
| `domain_coordinators/hvac_preset.py` | Added `_BASELINE_CONF_MAP` module constant; extended `get_seasonal_setpoints()` to prefer CM entry.options overrides (~45 LoC). |
| `number.py` | `DynamicPresetDwellMinutesNumber`: changed `DeviceInfo.identifiers` to `hvac_coordinator`, renamed to `"03 · Dynamic Preset Dwell (minutes)"`. `DynamicPresetHysteresisFNumber`: same migration, renamed to `"04 · Dynamic Preset Hysteresis (°F)"`. |
| `__init__.py` | Refactored v4.7.2 D2 inline migration helper into `_HVAC_DEVICE_MIGRATIONS` loop covering 3 entities. |
| `strings.json` | Added `hvac_baseline_presets` menu option + form step (title, 24 data labels, 24 data_descriptions, error key `baseline_preset_invalid_deadband`). |
| `translations/en.json` | Mirror of strings.json additions. |

### New files

| File | What it covers |
|---|---|
| `quality/tests/test_v473_baseline_preset_editor.py` | D1/D2/D3 tests: form step existence, menu registration, 24-field schema, deadband validation, save path, strings/translations parity, D3 source contract (every CONF has DEFAULT), D2 fallback semantics and per-CONF granularity. |
| `quality/tests/test_v473_dpm_number_migration.py` | D4 tests: device identifiers, unique_id preservation, numeric prefix labels, migration helper loop covers all 3 entities, `async_get_entity_id` pattern used. |

---

## Bug Class Compliance

| Class | Coverage |
|---|---|
| #2 Config Storage Pattern | D1 uses `async_create_entry` with `{**self._config_entry.options, **user_input}` merge. |
| #14 Config Snapshot Staleness | D2 reads from `entry.options` on every `get_seasonal_setpoints` call (per-decision-cycle, no stale cache). |
| #32 Form Field With No Runtime Reader | D3 source-contract test asserts every `CONF_HVAC_BASELINE_*` has a `DEFAULT_HVAC_BASELINE_*` and is read by `get_seasonal_setpoints`. |
| #44 Test Ordering | D2 runtime assertions written as source-grep tests (ordering-safe); module-level HA mock setup present for the constants import tests. |

---

## Live Validation Checklist

1. Settings → Devices → URA Coordinator Manager → Configure → HVAC → see "Baseline Presets (Seasonal)" as third menu option.
2. Open the step — all 24 fields visible, prefilled with current SEASONAL_DEFAULTS values.
3. Edit one field (e.g., Summer Home cool_high 77 → 76), save, reopen — value persists.
4. Within ≤5 min, `sensor.ura_hvac_zone_<zone>_active_preset_range_high` reflects the change for home preset in summer.
5. Settings → Devices → URA HVAC Coordinator — see `03 · Dynamic Preset Dwell (minutes)` and `04 · Dynamic Preset Hysteresis (°F)` entries on the device page (no longer on Energy Coordinator).
6. Zero new HA-core ERRORs in `ha_get_logs(source="system_service", slug="core", search="universal_room_automation")`.
