# Universal Room Automation v3.6.0.3 — Safety Coordinator Glanceability

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.2
**Minimum HA Version:** 2024.1+

---

## Summary

Makes the Safety Coordinator device page useful at a glance. Adds scoped sensor discovery with global device config flow, 3 new glanceable entities, enriches 2 existing entities with full hazard detail, fixes broken anomaly detectors, adds push updates, and guards legacy alert lights when domain coordinators are active.

---

## Changes

### 1. Scoped Sensor Discovery

**Before:** Safety Coordinator auto-discovered every safety-class entity in the entire HA entity registry — smoke detectors, leak sensors, temperature/humidity sensors, etc. — regardless of whether the user configured them in URA.

**After:** Safety Coordinator monitors sensors from two explicit sources only:
- **URA room sensors** — entities in areas assigned to URA-configured rooms
- **Global safety devices** — entities explicitly added via the Safety Coordinator config flow

Global sensors are mapped back to rooms via HA `area_id`. If a global sensor's area matches a URA room, it's attributed to that room. Sensors appearing in both sources are deduped (room location takes precedence).

### 2. Global Safety Device Config Flow

New EntitySelector fields in **Coordinator Manager → Safety Monitoring** options:
- **Global Smoke/Gas Detectors** — binary sensors with smoke/gas device class
- **Global Water Leak Sensors** — binary sensors with moisture device class
- **Global Air Quality Sensors** — CO, CO₂, VOC sensors
- **Global Temperature Sensors** — for freeze/overheat monitoring
- **Global Humidity Sensors** — for mold risk monitoring

These are for safety devices not configured inside any URA room (e.g., attic smoke detector, water main leak sensor, utility room CO detector).

### 3. Fix Anomaly Detectors (Presence + Safety)

**The bug:** Both `sensor.ura_presence_coordinator_presence_anomaly` and `sensor.ura_safety_coordinator_safety_anomaly` were stuck at `not_configured` despite the c2.9 fix that added AnomalyDetector instantiation.

**Root cause:** AnomalyDetector was instantiated AFTER all discovery/subscription code in `async_setup()`. If any earlier step threw an exception, `async_setup()` exited and `self.anomaly_detector` stayed `None`.

**Fix:**
- Moved AnomalyDetector instantiation to the **top** of `async_setup()` in both coordinators
- Wrapped discovery/subscription in try/except so partial failures don't crash the coordinator
- Anomaly sensors now return `"disabled"` (not `"not_configured"`) when the coordinator is deliberately turned off via its enable switch

### 4. New Glanceable Entities (3)

| Entity | Type | State | Purpose |
|--------|------|-------|---------|
| `sensor.ura_safety_active_hazards` | sensor | Count (0, 1, 2...) | How many things are wrong? Full hazard detail in attributes. |
| `binary_sensor.ura_safety_water_leak` | binary_sensor (moisture) | on/off | Any water leak or flooding? Locations, sensor IDs, flooding status in attributes. |
| `binary_sensor.ura_safety_air_quality` | binary_sensor (problem) | on/off | Any smoke, CO, CO₂, or VOC hazard? Types, locations, worst severity in attributes. |

All three use push updates via dispatcher signal for immediate state changes (not just polling).

### 5. Enriched Existing Entities (2)

**`sensor.ura_safety_status`** — new attributes:
- `scope`: `"clear"` / `"room"` / `"multi_room"` / `"house"` — blast radius at a glance
- `worst_location`: room name of the most severe hazard
- `hazards`: full list of all active hazards with type, severity, location, sensor_id, value, threshold, detected_at, message

**`binary_sensor.ura_safety_alert`** — new attribute:
- `all_hazards`: list of ALL active hazards (not just the worst one), each with hazard_type, location, severity

### 6. Guard Legacy Alert Lights

**The problem:** `SafetyAlertBinarySensor` in aggregation.py independently flashed room alert lights via a side effect in its `is_on` property getter. This ran regardless of whether the Safety Coordinator was active, using hardcoded thresholds (70% humidity, 85°F/55°F) more aggressive than the SC's tuned thresholds.

**Fix:** When domain coordinators are active (`coordinator_manager` exists), `_process_alerts()` returns early. The Safety Coordinator owns alert response. Legacy behavior preserved for users without domain coordinators.

### 7. Entity Category Cleanup

`SafetyDiagnosticsSensor`, `SafetyAnomalySensor`, and `SafetyComplianceSensor` now use `EntityCategory.DIAGNOSTIC`. They are hidden by default in Lovelace entity cards, keeping the device page focused on the prominent safety entities.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | AnomalyDetector to top of async_setup; scoped `_discover_sensors()`; `_collect_global_entities()`; `get_all_hazards_detail()`, `get_water_leak_status()`, `get_air_quality_status()` getters; `_notify_entity_update()` push signal |
| `domain_coordinators/presence.py` | AnomalyDetector to top of async_setup; try/except guard around discovery |
| `domain_coordinators/signals.py` | Add `SIGNAL_SAFETY_ENTITIES_UPDATE` |
| `config_flow.py` | 5 new global sensor EntitySelectors in `async_step_coordinator_safety` |
| `sensor.py` | `SafetyActiveHazardsSensor`; enrich `SafetyStatusSensor` attributes; anomaly "disabled" state; EntityCategory.DIAGNOSTIC; push updates |
| `binary_sensor.py` | `SafetyWaterLeakBinarySensor`, `SafetyAirQualityBinarySensor`; enrich `SafetyAlertBinarySensor`; push updates |
| `aggregation.py` | Guard `_process_alerts()` when coordinator_manager active |
| `const.py` | 5 `CONF_GLOBAL_*` constants; version 3.6.0.3 |
| `strings.json` | Labels for new config flow fields |
| `translations/en.json` | Labels for new config flow fields |
| `manifest.json` | Version 3.6.0.3 |

---

## How to Verify

1. **Config flow:** Coordinator Manager → Configure → Safety Monitoring shows 5 new global sensor selectors
2. **Scoped discovery:** After restart, check logs for "Safety sensor discovery:" showing room + global counts
3. **Anomaly sensors:** With SC enabled, should show `insufficient_data` or `learning` (not `not_configured`). With SC disabled, should show `disabled`.
4. **Active hazards:** `sensor.ura_safety_active_hazards` shows `0` when clear, count + hazard list when active
5. **Water leak:** `binary_sensor.ura_safety_water_leak` off when no leaks, on with location details when active
6. **Air quality:** `binary_sensor.ura_safety_air_quality` off when air clear, on with hazard type details when active
7. **Safety status:** Check attributes — `scope`, `worst_location`, `hazards` list present
8. **Safety alert:** Check attributes — `all_hazards` list present (not just worst)
9. **Legacy lights:** With domain coordinators enabled, aggregation-level alert light flashing should stop
10. **Diagnostic entities:** `safety_diagnostics`, `safety_anomaly`, `safety_compliance` hidden by default in entity cards

---

## Version Mapping

| Version | Description |
|---------|-------------|
| 3.6.0-c0 – c0.4 | Domain coordinator infrastructure + diagnostics |
| 3.6.0-c1 | Presence Coordinator |
| 3.6.0-c2 – c2.9.2 | Safety Coordinator + deployment fixes |
| 3.6.0.1 | Zone presence root cause fix, versioning scheme change |
| 3.6.0.2 | Zone presence BLE bypass + diagnostics |
| **3.6.0.3** | **Safety glanceability, scoped discovery, anomaly fix, legacy light guard** |
