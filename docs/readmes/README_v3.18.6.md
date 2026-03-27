# URA v3.18.6 -- BLE Pre-Arrival Detection

## Overview
Adds Bluetooth Low Energy (BLE) as a second pre-arrival trigger source alongside geofence. When a tracked person has been away (LOST status) for 15+ minutes and a BLE beacon detects them re-entering the home, the HVAC coordinator pre-conditions their preferred zones before they physically arrive at the thermostat. Includes a runtime toggle switch, a diagnostic sensor, and a config flow source selector.

## Changes

### BLE Pre-Arrival Detection (person_coordinator.py)
- **Away detection**: Tracks `_person_lost_since` timestamp when a person's Bermuda tracking status transitions to LOST. After 15 minutes of continuous LOST status, the person is marked as `_person_was_away`.
- **Re-entry trigger**: When a BLE-tracked person who was genuinely away is detected in a room, fires `SIGNAL_PERSON_ARRIVING` with `source: "ble"`. The 15-minute minimum prevents false triggers from quick trips (gardening, checking mail).
- **Entity resolution**: `_find_person_entity()` maps BLE person names (from Bermuda sensors) to HA person entities. Tries standard slug format first (`person.oji`), then raw name.

### Source Filter (domain_coordinators/hvac.py)
- **`_pre_arrival_sources`**: List of enabled trigger sources, configurable via config flow. Default: `["geofence", "ble"]`.
- **Source gating in `_handle_person_arriving`**: Checks incoming signal's `source` field against enabled list. Signals without a source (legacy geofence) are allowed through for backward compatibility.
- **Trigger tracking**: `_pre_arrival_triggers_today` counter, `_last_pre_arrival_time/source/person` for diagnostics. Counter resets at midnight in the daily reset cycle.

### Pre-Arrival Toggle Switch (switch.py)
- **Entity**: `switch.ura_hvac_pre_arrival` (Config category)
- **Device**: URA: HVAC Coordinator
- **Behavior**: When OFF, both geofence and BLE pre-arrival signals are ignored. Syncs state to person_coordinator so BLE detection respects the toggle.
- **Persistence**: `RestoreEntity` -- survives HA restarts.

### Pre-Arrival Diagnostic Sensor (sensor.py)
- **Entity**: `sensor.ura_hvac_pre_arrival_status` (Diagnostic category)
- **States**: `idle` | `active` | `disabled` | `unavailable`
- **Attributes**: enabled, sources, active_zones, active_persons, last_trigger_time, last_trigger_source, last_trigger_person, triggers_today, person_zone_map

### Config Flow (config_flow.py)
- **Pre-arrival sources selector**: Multi-select list in the HVAC coordinator options step. Options: "Geofence (Phone GPS)" and "BLE (Bluetooth Proximity)".

### Constants (domain_coordinators/hvac_const.py)
- `CONF_PRE_ARRIVAL_SOURCES`: Config key for source list
- `DEFAULT_PRE_ARRIVAL_SOURCES`: `["geofence", "ble"]`

### Translations
- strings.json and translations/en.json: Labels and descriptions for `pre_arrival_sources` field.

## Review Fixes
- **R1-1 (MEDIUM)**: Fixed raw datetime object in `HVACPreArrivalDiagnosticSensor.extra_state_attributes`. Applied `.isoformat()` conversion to match the pattern used in the HVAC coordinator's own attributes. Without this fix, the sensor could cause JSON serialization errors in HA history/recorder.

## Test Coverage
- 6 new tests in `TestBLEPreArrival` class (test_fan_control_v318.py):
  - 15-min away guard triggers correctly
  - Quick trip (5 min) does not trigger
  - Source filter blocks disabled sources
  - Source filter allows enabled sources
  - Duplicate zone deduplication
  - Toggle off blocks all sources
- 38 tests in file, 1178 total passing

## Files Changed
- `person_coordinator.py` -- BLE away/present detection, _find_person_entity, signal dispatch
- `domain_coordinators/hvac_const.py` -- CONF_PRE_ARRIVAL_SOURCES, DEFAULT_PRE_ARRIVAL_SOURCES
- `domain_coordinators/hvac.py` -- source filter, pre_arrival_enabled property, trigger tracking, daily counter, attrs
- `switch.py` -- HVACPreArrivalSwitch (RestoreEntity)
- `sensor.py` -- HVACPreArrivalDiagnosticSensor + isoformat fix
- `config_flow.py` -- pre_arrival_sources multi-select in coordinator_hvac step
- `strings.json` + `translations/en.json` -- labels for pre_arrival_sources

## Deferred Items
- **Person entity format edge cases**: `_find_person_entity` handles two name formats. If Bermuda uses a format that doesn't match either (e.g., email-based), it returns None and the signal is silently dropped. Monitor in production.
- **Config-driven min_away_minutes**: Currently hardcoded to 15 minutes. Could be made configurable in a future version if users need different thresholds.
- **_person_lost_since cleanup**: Dict is not pruned when tracked persons are removed. Negligible for typical household sizes.
