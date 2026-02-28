# Universal Room Automation v3.6.0-c2.6 — Safety Coordinator + Bug Fixes

**Release Date:** 2026-02-28
**Internal Reference:** C2 through C2.6 (Safety Coordinator + deployment fixes)
**Previous Release:** v3.6.0-c1
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c1
**Design Document:** PLANNING_v3.6.0_REVISED.md

---

## Summary

v3.6.0-c2 through c2.6 adds the Safety Coordinator — the second domain coordinator — and includes six iterative bug fix releases that resolved deployment issues discovered in production. This README covers all changes from c2 through c2.6 as a combined milestone.

### What's New

1. **Safety Coordinator** (`domain_coordinators/safety.py`, ~1600 lines) — Priority-100 coordinator for environmental hazard detection and response:
   - 12 hazard types: Smoke, Fire, Water Leak, Flooding, CO, CO2, TVOC, Freeze Risk, Overheat, HVAC Failure, High Humidity, Low Humidity
   - Sensor discovery via entity registry `device_class` + word-boundary regex fallback (c2.6)
   - Room-type-aware humidity thresholds (normal, bathroom, basement) with sustained window enforcement
   - Bidirectional rate-of-change detection (temperature drop/rise, humidity spike)
   - Flooding escalation (multi-sensor or sustained >15min)
   - Alert deduplication with per-severity suppression windows
   - Configurable water shutoff valve and emergency light entities

2. **Per-Coordinator Toggle Switches** (c2.5):
   - `switch.ura_domain_coordinators_enabled` — Master toggle on URA Integration device
   - `switch.ura_presence_coordinator_enabled` — Per-coordinator toggle on Presence device
   - `switch.ura_safety_coordinator_enabled` — Per-coordinator toggle on Safety device
   - House State Override dropdowns gray out when coordinator system is disabled

3. **Coordinator Manager Options Menu** (c2.2):
   - CM config entry now has its own options flow (was incorrectly showing Room menu)
   - Three config steps: Presence Settings, Safety Monitoring, Enable/Disable Coordinators

4. **Zone Presence Fix** (c2.6):
   - Zone trackers now discovered from Zone Manager entry (not just legacy zone entries)
   - Zone presence status sensors no longer show "unknown" for all zones

5. **Safety False Positive Fixes** (c2.6):
   - Sensor discovery uses `device_class` attribute first, word-boundary regex fallback second
   - Eliminated broad substring matching (`"temp" in eid` captured ~533 unrelated sensors)
   - Humidity thresholds raised: normal 60%→70%, basement 55%→65%
   - CO LOW threshold raised: 10→25 ppm (was at WHO safe limit, caused false alarms)
   - Overheat thresholds raised: LOW 95→100°F, MEDIUM 100→105°F, HIGH 110→115°F
   - Sustained humidity hazard fires once per period (not on every state change)

---

## Version History (C2 → C2.6)

| Version | Date | Description |
|---------|------|-------------|
| 3.6.0-c2 | 2026-02-28 | Safety Coordinator: 12 hazard types, sensor discovery, rate-of-change, flooding escalation |
| 3.6.0-c2.1 | 2026-02-28 | Fix zone device identifier mismatch (unnamed device spam), options wipe bug, orphan cleanup |
| 3.6.0-c2.2 | 2026-02-28 | CM options menu (Presence Settings, Safety Monitoring, Coordinator Toggles) |
| 3.6.0-c2.3 | 2026-02-28 | Fix house state "away": add initial inference on startup, seed census count |
| 3.6.0-c2.4 | 2026-02-28 | Fix census signal never dispatched, fix zone configure "zone not found" for ZM-stored zones |
| 3.6.0-c2.5 | 2026-02-28 | Per-coordinator toggle switches, disable dropdowns when off, clean up menus |
| 3.6.0-c2.6 | 2026-02-28 | Fix zone presence "unknown", fix safety false positives, rename zone sensor |

---

## Files Changed

### New Files

| File | Description |
|------|-------------|
| `domain_coordinators/safety.py` | Safety Coordinator: 12 hazard types, sensor discovery, rate-of-change detection, flooding escalation, alert deduplication, emergency response actions (~1600 lines) |

### Modified Files

| File | Changes |
|------|---------|
| `__init__.py` | Register Safety Coordinator with CM. Per-coordinator enable/disable from CM entry options. Orphaned zone device cleanup. Census signal seeding on startup. |
| `switch.py` | Entry type routing. DomainCoordinatorsSwitch (master toggle). CoordinatorEnabledSwitch (per-coordinator). AutomationSwitch, OverrideOccupied/Vacant, ClimateAutomation, CoverAutomation, ManualMode for rooms. |
| `select.py` | House State Override dropdowns: `available` property returns False when coordinator_manager not running. Zone identifier fix (raw name instead of slugified). |
| `sensor.py` | Safety Coordinator sensors: SafetyStatusSensor, ActiveHazardCountSensor, HazardsDetected24hSensor, AlertsSent24hSensor, SafetyAnomalySensor, SafetyComplianceSensor |
| `binary_sensor.py` | Safety binary sensors: SafetyAlertBinarySensor, WaterLeakBinarySensor |
| `aggregation.py` | ZonePresenceStatusSensor renamed to "Zone Presence Status" (from "Presence Status") |
| `config_flow.py` | CM options flow: coordinator_presence, coordinator_safety, coordinator_toggles steps. Zone config fix: `_get_zm_zone_data()` helper. Options wipe fix in domain_coordinators and perimeter_alerts steps. |
| `camera_census.py` | Added SIGNAL_CENSUS_UPDATED dispatch after each census update (was never dispatched before). |
| `domain_coordinators/presence.py` | `_discover_zones()` now reads from Zone Manager entry in addition to legacy zone entries. Initial inference on startup. Census count seeding from census manager or sensor state. |
| `const.py` | Added: CONF_WATER_SHUTOFF_VALVE, CONF_EMERGENCY_LIGHT_ENTITIES, CONF_PRESENCE_ENABLED, CONF_SAFETY_ENABLED, CONF_DOMAIN_COORDINATORS_ENABLED. Version bumps c2→c2.6. |
| `strings.json` | CM options menu steps, coordinator toggle labels, safety monitoring labels. |
| `translations/en.json` | Full translations for CM options flow and domain_coordinators step. |
| `manifest.json` | Version bump to 3.6.0-c2.6 |

---

## Bugs Found and Fixed

### c2.1: Three Live Deployment Bugs

1. **Unnamed device spam** — Zone identifier mismatch between `select.py` (used slugified names like `zone_back_hallway`) and `aggregation.py` (used raw names like `zone_Back Hallway`). Entities created two different devices per zone.
   - **Fix:** Changed `select.py` to use raw zone name, matching aggregation.py.

2. **Options wipe** — `config_flow.py` called `async_update_entry()` to save options, then `async_create_entry(data={})` which overwrites `entry.options` with `{}`. All saved settings (domain_coordinators_enabled, etc.) were wiped on every options flow completion.
   - **Fix:** Pass merged options through `async_create_entry(data={...merged...})`.

3. **Orphaned zone devices** — After migrating zones from separate entries to Zone Manager, old slugified device identifiers left behind "Unnamed device" entries.
   - **Fix:** Added cleanup logic in Zone Manager entry setup.

### c2.3: House State Always "Away"

- **Root cause:** `SIGNAL_CENSUS_UPDATED` was defined in `signals.py` and subscribed to in `presence.py`, but `camera_census.py` never dispatched it. The `_census_count` in PresenceCoordinator stayed 0 forever, so inference always concluded "away".
- **Fix:** Added `async_dispatcher_send(hass, SIGNAL_CENSUS_UPDATED, {...})` in camera_census.py. Added census count seeding from existing state on startup.

### c2.4: Zone Configure Error + Census Dispatch

- **Root cause:** `manage_zones` step set `_selected_zone_name` but `zone_config_menu` looked for `_selected_zone_entry_id` (legacy zone entries removed during migration).
- **Fix:** Added `_get_zm_zone_data()` helper method and updated zone_rooms/zone_media steps.

### c2.6: Zone Presence "Unknown" + Safety False Positives

- **Zone presence:** `_discover_zones()` only searched for `ENTRY_TYPE_ZONE` entries (legacy). Zones now live in `ENTRY_TYPE_ZONE_MANAGER` entry's `zones` dict. Zone trackers were never created.
- **Fix:** `_discover_zones()` now reads from both legacy zone entries and Zone Manager.

- **Safety false positives (3 root causes):**
  1. Substring matching (`"temp" in eid_lower`) captured ~533 sensors including all template sensors
  2. Humidity LOW threshold at 60% for normal rooms fires on normal humidity levels
  3. Sustained humidity hazard re-created on every state change after window expires
- **Fixes:** device_class + word-boundary regex, raised thresholds, one-shot hazard firing.

---

## Tests

- **590 tests pass, 0 failures, 0 regressions**
- Safety coordinator tests in `quality/tests/test_safety_coordinator.py`
- 14 test files total across the integration

---

## How to Deploy

```bash
./scripts/deploy.sh "3.6.0-c2.6" \
  "Fix zone presence unknown, safety false positives, rename zone sensor" \
  "- Fix zone presence 'unknown': discover zones from Zone Manager entry
- Fix safety false positives: device_class + word-boundary sensor discovery
- Raise humidity thresholds (normal: 60->70, basement: 55->65)
- Fire sustained humidity hazard only once per period
- Rename zone presence status sensor to 'Zone Presence Status'"
```

---

## How to Verify It Works

### 1. Safety Coordinator entities appear

After restart, check for new entities on the Safety Coordinator device:

**Sensors:**
- `sensor.ura_safety_status` — Overall safety status (normal/warning/critical)
- `sensor.ura_safety_active_hazard_count` — Number of active hazards
- `sensor.ura_safety_hazards_detected_24h` — Detection count in last 24 hours
- `sensor.ura_safety_alerts_sent_24h` — Alert count in last 24 hours

**Binary sensors:**
- `binary_sensor.ura_safety_alert` — Active safety alert
- `binary_sensor.ura_water_leak` — Water leak detected

### 2. Per-coordinator toggles work

- `switch.ura_domain_coordinators_enabled` on URA Integration device
- `switch.ura_presence_coordinator_enabled` on Presence Coordinator device
- `switch.ura_safety_coordinator_enabled` on Safety Coordinator device
- Turn off domain coordinators toggle → House State Override dropdowns gray out
- Turn off individual coordinator → That coordinator stops processing on next reload

### 3. Zone presence status is not "unknown"

- `sensor.ura_zone_{name}_presence_status` should show `away`, `occupied`, or `sleep` (not `unknown` for zones with rooms that have sensors)

### 4. Safety false positives resolved

- `sensor.ura_safety_active_hazard_count` should be 0 or very low (was 114 before fix)
- `sensor.ura_safety_hazards_detected_24h` should be reasonable (was 2696 before fix)
- Check logs: "Safety: discovered X numeric sensors" — should be much lower than before

### 5. CM options menu works

- Go to Settings → Devices & Services → URA → Coordinator Manager entry → Configure
- Should show: Presence Settings, Safety Monitoring (not the room options menu)

---

## Entity Summary

### Safety Coordinator Device

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.ura_safety_status` | Sensor | Overall safety status |
| `sensor.ura_safety_active_hazard_count` | Sensor | Number of active hazards |
| `sensor.ura_safety_hazards_detected_24h` | Sensor | Detections in 24h |
| `sensor.ura_safety_alerts_sent_24h` | Sensor | Alerts sent in 24h |
| `sensor.ura_safety_anomaly_status` | Sensor | Anomaly detection status |
| `sensor.ura_safety_compliance_rate` | Sensor | Compliance percentage |
| `binary_sensor.ura_safety_alert` | Binary Sensor | Active safety alert |
| `binary_sensor.ura_water_leak` | Binary Sensor | Water leak detected |
| `switch.ura_safety_coordinator_enabled` | Switch | Enable/disable Safety Coordinator |

### URA Integration Device (new entities)

| Entity | Type | Description |
|--------|------|-------------|
| `switch.ura_domain_coordinators_enabled` | Switch | Master toggle for coordinator system |

### Presence Coordinator Device (new entities)

| Entity | Type | Description |
|--------|------|-------------|
| `switch.ura_presence_coordinator_enabled` | Switch | Enable/disable Presence Coordinator |

### Zone Devices (renamed)

| Entity | Type | Change |
|--------|------|--------|
| `sensor.ura_zone_{name}_presence_status` | Sensor | Renamed from "Presence Status" to "Zone Presence Status" |

---

## Architecture Notes

### Safety Coordinator Sensor Discovery (c2.6)

```
For each entity in entity registry:
  1. Check device_class attribute (most reliable)
     - "temperature" → temperature sensor
     - "humidity" → humidity sensor
     - "carbon_monoxide" → CO sensor
     - "smoke" → smoke binary sensor
     - "moisture"/"water" → leak binary sensor
  2. Fallback: word-boundary regex on entity_id
     - \btemperature\b matches "living_room_temperature"
     - Does NOT match "template_sensor_xyz"
     - \bsmoke\b, \bco2\b, \btvoc\b, \bhumidity\b
```

### Humidity Threshold Model

```
Room Type    LOW     MEDIUM    HIGH    Sustained Window
─────────    ───     ──────    ────    ────────────────
Normal       70%     80%       90%     2 hours
Bathroom     80%     85%       90%     4 hours
Basement     65%     75%       85%     2 hours

One-shot firing: hazard created once when sustained window expires.
Cleared when humidity drops below LOW threshold. Next sustained
period creates a new hazard.
```

### Zone Discovery Flow (c2.6)

```
_discover_zones():
  1. Legacy: scan for ENTRY_TYPE_ZONE entries (individual zone config entries)
  2. New: scan for ENTRY_TYPE_ZONE_MANAGER entry → read zones dict
     zones = {
       "Back Hallway": {"zone_rooms": ["Room A", "Room B"], ...},
       "Upstairs": {"zone_rooms": ["Bedroom", "Office"], ...},
     }
  3. Create ZonePresenceTracker per zone (skip duplicates)
```

---

## Codebase Stats (as of c2.6)

| Metric | Value |
|--------|-------|
| Version | 3.6.0-c2.6 |
| Python files | 29 |
| Lines of code | ~28,500 |
| Platform entity classes | 112 (71 sensor, 20 binary_sensor, 8 switch, 6 button, 4 number, 3 select) |
| Domain coordinators | 2 (Presence, Safety) + base framework |
| Test files | 14 |
| Total tests | 590 |
| Config entry types | 5 (Integration, Room, Zone, Zone Manager, Coordinator Manager) |

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1 | C0.1 | Integration page organization |
| 3.6.0-c0.2 | C0.2 | Census graceful degradation fix |
| 3.6.0-c0.3 | C0.3 | Coordinator entity unavailability fix |
| 3.6.0-c0.4 | C0-diag | Coordinator diagnostics framework |
| 3.6.0-c1 | C1 | Presence Coordinator |
| 3.6.0-c2 | C2 | Safety Coordinator |
| 3.6.0-c2.1 | C2.1 | Fix unnamed device spam, options wipe, orphan cleanup |
| 3.6.0-c2.2 | C2.2 | CM options menu |
| 3.6.0-c2.3 | C2.3 | Fix house state "away" — initial inference on startup |
| 3.6.0-c2.4 | C2.4 | Fix census signal dispatch, zone configure error |
| 3.6.0-c2.5 | C2.5 | Per-coordinator toggle switches |
| **3.6.0-c2.6** | **C2.6** | **Fix zone presence "unknown", safety false positives, sensor rename** |
