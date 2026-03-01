# MINIPLAN v3.6.0.3 — Safety Coordinator Glanceability

**Version:** 3.6.0.3
**Scope:** Scoped sensor discovery, global device config flow, glanceable entities, anomaly fix
**Effort:** 3-4 hours
**Dependencies:** v3.6.0.2 deployed
**Builder Model:** Opus 4.6

---

## Objective

Open the Safety Coordinator device page and instantly understand:
- **How many** things are wrong (`active_hazards`)
- **Any water problem** at a glance (`water_leak` binary)
- **Any air problem** at a glance (`air_quality` binary)
- **How bad** and **where** (enriched `safety_status` with scope, location, full hazard list)

Plus: fix broken anomaly detectors, and shift from "vacuum all safety entities in HA" to "monitor what's configured in URA."

---

## Part 1: Scoped Sensor Discovery + Global Device Config Flow

### The Change

**Before (current):** `_discover_sensors()` iterates the ENTIRE HA entity registry, classifies every entity by `device_class` (smoke, moisture, temperature, humidity, CO, CO2, TVOC). Every matching entity in HA gets monitored regardless of whether the user configured it in URA.

**After:** Safety Coordinator monitors sensors from TWO explicit sources:
1. **URA room-configured sensors** — entities already assigned to URA rooms via room config entries. Scoped by `area_id` matching to room config.
2. **Global safety devices** — entities explicitly added in the Safety Coordinator config flow. For devices that don't belong to any URA room (e.g., water main leak sensor in a utility chase, whole-house CO detector, attic smoke detector).

### Room Attribution for Global Sensors

Global sensors are not roomless just because they aren't configured inside a URA room. They still have physical locations. The coordinator resolves location using:

1. **HA area_id** — if the global sensor has an area assignment in HA, AND that area matches a URA room, attribute it to that room. This is the common case: the sensor exists in HA with the right area, the user just didn't add it to the URA room config.
2. **User-specified location** — the config flow allows an optional room/label per global sensor (see schema below).
3. **Fallback** — `_location_from_entity_id()` as today, producing a best-guess room name.

### Deduplication

A sensor could appear in both a URA room config AND the global config flow. Dedup by entity_id using a `set`. Room-discovered location takes precedence over global config location (the room config is more specific).

### Config Flow Changes

Extend `async_step_coordinator_safety` with new fields:

```python
# New constants in const.py
CONF_GLOBAL_SMOKE_SENSORS: Final = "global_smoke_sensors"
CONF_GLOBAL_LEAK_SENSORS: Final = "global_leak_sensors"
CONF_GLOBAL_AQ_SENSORS: Final = "global_aq_sensors"
CONF_GLOBAL_TEMP_SENSORS: Final = "global_temp_sensors"
CONF_GLOBAL_HUMIDITY_SENSORS: Final = "global_humidity_sensors"

# In config_flow.py async_step_coordinator_safety:
vol.Optional(CONF_GLOBAL_SMOKE_SENSORS, default=current_smoke):
    EntitySelector(EntitySelectorConfig(
        domain="binary_sensor",
        device_class=["smoke", "gas"],
        multiple=True,
    )),
vol.Optional(CONF_GLOBAL_LEAK_SENSORS, default=current_leak):
    EntitySelector(EntitySelectorConfig(
        domain="binary_sensor",
        device_class=["moisture"],
        multiple=True,
    )),
vol.Optional(CONF_GLOBAL_AQ_SENSORS, default=current_aq):
    EntitySelector(EntitySelectorConfig(
        domain="sensor",
        device_class=["carbon_monoxide", "carbon_dioxide",
                      "volatile_organic_compounds"],
        multiple=True,
    )),
vol.Optional(CONF_GLOBAL_TEMP_SENSORS, default=current_temp):
    EntitySelector(EntitySelectorConfig(
        domain="sensor",
        device_class=["temperature"],
        multiple=True,
    )),
vol.Optional(CONF_GLOBAL_HUMIDITY_SENSORS, default=current_humidity):
    EntitySelector(EntitySelectorConfig(
        domain="sensor",
        device_class=["humidity"],
        multiple=True,
    )),
```

Storage: in the Coordinator Manager config entry `options` (changeable via options flow without recreating entry).

### Modified `_discover_sensors()`

Replace the current "iterate all entities" approach:

```python
def _discover_sensors(self) -> None:
    """Discover safety sensors from URA rooms + global config."""
    ent_reg = er.async_get(self.hass)
    area_to_room = self._build_area_room_lookup()

    # Source 1: URA room-configured entities
    # Iterate room config entries, collect safety-class entities by area_id
    seen_entity_ids: set[str] = set()
    for room_name, area_id in self._room_area_ids.items():
        room_type = self._room_types.get(room_name, "normal")
        for entity in ent_reg.entities.values():
            if getattr(entity, "area_id", None) == area_id:
                self._classify_entity(entity.entity_id, entity, area_to_room)
                seen_entity_ids.add(entity.entity_id)

    # Source 2: Global config flow entities
    cm_options = self._get_cm_options()
    global_entities = self._collect_global_entities(cm_options)
    for entity_id in global_entities:
        if entity_id in seen_entity_ids:
            continue  # Room-discovered takes precedence
        entity = ent_reg.entities.get(entity_id)
        if entity:
            self._classify_entity(entity_id, entity, area_to_room)
```

---

## Part 2: Fix Anomaly Detectors (Presence + Safety)

### Root Cause

In both `presence.py` and `safety.py`, `AnomalyDetector` instantiation is placed AFTER all discovery/subscription code in `async_setup()`. If any earlier step throws, `async_setup()` exits and `self.anomaly_detector` stays `None`. Sensors return "not_configured".

### Fix

1. Move `AnomalyDetector` instantiation to the **top** of `async_setup()` in both coordinators
2. Wrap `load_baselines()` in try/except (non-fatal)
3. Add top-level try/except guard around discovery block so partial failures don't prevent the coordinator from functioning
4. When coordinator is disabled (switch=off), anomaly sensor shows "disabled" instead of "not_configured"

### Files
- `domain_coordinators/presence.py` — move AnomalyDetector init, add guard
- `domain_coordinators/safety.py` — move AnomalyDetector init, add guard
- `sensor.py` — anomaly sensor returns "disabled" when coordinator switch is off

---

## Part 3: New Glanceable Entities (4 additions)

### Entity 1: `sensor.ura_safety_active_hazards`

**Purpose:** How many things are wrong right now?

| Property | Value |
|----------|-------|
| State | Count of active hazards: 0, 1, 2, 3... |
| `state_class` | `SensorStateClass.MEASUREMENT` |
| Icon | `mdi:alert-octagon` (0 hazards: `mdi:shield-check`) |
| Entity category | None (prominent on device page) |

**Attributes:**
```yaml
hazards:
  - hazard_type: "smoke"
    severity: "critical"
    location: "Kitchen"
    sensor_id: "binary_sensor.kitchen_smoke"
    value: "on"
    threshold: null
    detected_at: "2026-03-01T10:00:00+00:00"
    message: "Smoke detected in Kitchen"
  - hazard_type: "water_leak"
    severity: "high"
    location: "Basement"
    sensor_id: "binary_sensor.basement_leak"
    value: "on"
    threshold: null
    detected_at: "2026-03-01T10:01:30+00:00"
    message: "Water leak detected in Basement"
```

**Implementation:** `get_all_hazards_detail()` method on SafetyCoordinator — reformats `_active_hazards` dict. Enums serialized as `.value`, datetimes as `.isoformat()`. Capped at 20 entries sorted by severity descending.

**Data source:** Existing `_active_hazards` dict — no new coordinator state needed.

---

### Entity 2: `binary_sensor.ura_safety_water_leak`

**Purpose:** Any water problem? Glanceable yes/no.

| Property | Value |
|----------|-------|
| State | on if any WATER_LEAK or FLOODING hazard active |
| Device class | `BinarySensorDeviceClass.MOISTURE` |
| Icon | `mdi:water-alert` |
| Entity category | None (prominent) |

**Attributes:**
```yaml
locations: ["Basement", "Laundry Room"]
sensor_ids: ["binary_sensor.basement_leak", "binary_sensor.laundry_leak"]
sensor_count: 2
flooding_escalated: false
first_detected: "2026-03-01T10:01:30+00:00"
```

**Implementation:** `get_water_leak_status()` method — filters `_active_hazards` by type, reads `_leak_start_times` for `first_detected` (earliest), reads `_active_leak_sensors` for sensor list, checks for any FLOODING type for `flooding_escalated`.

**Data source:** Existing `_active_hazards`, `_leak_start_times`, `_active_leak_sensors` — no new state needed.

---

### Entity 3: `binary_sensor.ura_safety_air_quality`

**Purpose:** Any air problem? Glanceable yes/no.

| Property | Value |
|----------|-------|
| State | on if any SMOKE, CARBON_MONOXIDE, HIGH_CO2, or HIGH_TVOC hazard active |
| Device class | `BinarySensorDeviceClass.PROBLEM` |
| Icon | `mdi:air-filter` |
| Entity category | None (prominent) |

**Attributes:**
```yaml
hazard_types: ["smoke", "high_co2"]
locations: ["Kitchen", "Garage"]
sensor_ids: ["binary_sensor.kitchen_smoke", "sensor.garage_co2"]
worst_severity: "critical"
```

**Implementation:** `get_air_quality_status()` method — filters `_active_hazards` by AQ hazard types, extracts locations, picks worst severity.

**Data source:** Existing `_active_hazards` — no new state needed.

---

### Entity 4: Enriched `sensor.ura_safety_status` (existing entity)

**Purpose:** Already shows severity word. Add scope and detail so you know WHERE without clicking into another entity.

**New attributes added to existing:**
```yaml
# Existing attributes (unchanged)
active_hazards: 2
sensors_monitored: 15
last_check: "2026-03-01T10:05:00+00:00"

# New attributes
scope: "room"          # "clear" / "room" / "multi_room" / "house"
worst_location: "Kitchen"
hazards:               # Full list (same format as active_hazards entity)
  - hazard_type: "smoke"
    severity: "critical"
    location: "Kitchen"
    ...
```

**Scope logic:**
- `"clear"` — 0 active hazards
- `"room"` — all hazards in a single room
- `"multi_room"` — hazards in 2+ rooms
- `"house"` — hazards spanning 3+ rooms OR any CRITICAL severity

---

### Entity 5: Enriched `binary_sensor.ura_safety_alert` (existing entity)

**New attribute:**
```yaml
# Existing (unchanged)
hazard_type: "smoke"
location: "Kitchen"
severity: "critical"
active_count: 2

# New
all_hazards:
  - hazard_type: "smoke"
    location: "Kitchen"
    severity: "critical"
  - hazard_type: "water_leak"
    location: "Basement"
    severity: "high"
```

---

## Part 4: Push Updates for Safety Entities

Safety entities currently use polling. For safety-critical state changes, switch to push:

1. Add `SIGNAL_SAFETY_ENTITIES_UPDATE` to `signals.py`
2. SafetyCoordinator fires this signal in `_respond_to_hazard()` and `_clear_hazard()`
3. All safety sensor/binary_sensor entities subscribe via `async_dispatcher_connect` and call `async_write_ha_state()` on signal
4. Entities still have `@property` for polling as fallback

---

## Part 5: Entity Category Cleanup

| Entity | Category | Visibility |
|--------|----------|------------|
| safety_status | None | Prominent |
| safety_alert | None | Prominent |
| **active_hazards** (new) | None | Prominent |
| **water_leak** (new) | None | Prominent |
| **air_quality** (new) | None | Prominent |
| safety_diagnostics | DIAGNOSTIC | Hidden by default |
| safety_anomaly | DIAGNOSTIC | Hidden by default |
| safety_compliance | DIAGNOSTIC | Hidden by default |

---

## Part 6: Guard Legacy Alert Lights When Domain Coordinators Active

### The Problem

`SafetyAlertBinarySensor` in `aggregation.py` (line 792) has a **side effect in a property getter**: every time HA polls `is_on`, if any room has temp >85F/<55F or humidity >70%/<25%, it fires `_process_alerts()` which flashes that room's `CONF_ALERT_LIGHTS`. This runs independently of the Safety Coordinator — it doesn't check `CONF_DOMAIN_COORDINATORS_ENABLED`.

When the SC is active, safety light response is its responsibility via `CONF_EMERGENCY_LIGHT_ENTITIES`. The aggregation sensor should not independently flash lights.

Additionally, the hardcoded thresholds (70% humidity, 85F/55F temp) are much more aggressive than the SC's tuned thresholds (which use room-type awareness and sustained windows). This can cause spurious flashing on normal conditions.

### The Fix

In `SafetyAlertBinarySensor._process_alerts()`, add a guard at the top:

```python
async def _process_alerts(self, alerts: list[dict]) -> None:
    # When domain coordinators are active, Safety Coordinator owns alert response
    if self.hass.data.get(DOMAIN, {}).get("coordinator_manager") is not None:
        return
    # ... existing legacy alert logic
```

This preserves the legacy behavior for users who haven't enabled domain coordinators while preventing double-response when the SC is handling it.

### Why not remove the side effect entirely?

The `is_on` property getter should not have side effects — this is a design flaw. However, removing it entirely would break the legacy alert path for users without domain coordinators. The guard is the minimal safe fix. Full cleanup (moving to event-driven alerts) is deferred to the alert harmonization cycle.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | Move AnomalyDetector to top of async_setup(); rewrite `_discover_sensors()` for scoped discovery; add `get_all_hazards_detail()`, `get_water_leak_status()`, `get_air_quality_status()` methods; add `_notify_entity_update()` that fires dispatcher signal; add `_collect_global_entities()` |
| `domain_coordinators/presence.py` | Move AnomalyDetector to top of async_setup(); add try/except guard around discovery block |
| `domain_coordinators/signals.py` | Add `SIGNAL_SAFETY_ENTITIES_UPDATE` |
| `config_flow.py` | Extend `async_step_coordinator_safety` with 5 global sensor EntitySelectors |
| `const.py` | Add `CONF_GLOBAL_SMOKE_SENSORS`, `CONF_GLOBAL_LEAK_SENSORS`, `CONF_GLOBAL_AQ_SENSORS`, `CONF_GLOBAL_TEMP_SENSORS`, `CONF_GLOBAL_HUMIDITY_SENSORS`; version 3.6.0.3 |
| `sensor.py` | Add `SafetyActiveHazardsSensor` class; enrich `SafetyStatusSensor` attributes; anomaly sensor "disabled" state; dispatcher subscription for push updates; entity_category on diagnostic sensors |
| `binary_sensor.py` | Add `SafetyWaterLeakBinarySensor`, `SafetyAirQualityBinarySensor` classes; enrich `SafetyAlertBinarySensor` attributes; dispatcher subscription for push updates; entity_category on diagnostic sensors |
| `aggregation.py` | Guard `_process_alerts()` when domain coordinators active |
| `strings.json` | Labels for new config flow fields |
| `translations/en.json` | Labels for new config flow fields |
| `manifest.json` | Version 3.6.0.3 |

**Estimated:** ~280 new lines, ~110 modified lines

---

## Verification

- [ ] Config flow shows global safety device selectors (smoke, leak, AQ, temp, humidity)
- [ ] Safety Coordinator discovers ONLY sensors from URA rooms + global config (not all HA entities)
- [ ] Global sensor with HA area_id matching a URA room is attributed to that room
- [ ] Sensor in both room config AND global config is deduped (room location wins)
- [ ] Anomaly sensors show "insufficient_data" or "learning" (not "not_configured") when coordinator enabled
- [ ] Anomaly sensors show "disabled" when coordinator switch is off
- [ ] `sensor.ura_safety_active_hazards` shows count of active hazards, `hazards` list attribute populated
- [ ] `binary_sensor.ura_safety_water_leak` on when leak active, attributes include locations and sensor_ids
- [ ] `binary_sensor.ura_safety_air_quality` on when AQ hazard active, `worst_severity` attribute correct
- [ ] `sensor.ura_safety_status` has `scope`, `worst_location`, `hazards` attributes
- [ ] `binary_sensor.ura_safety_alert` has `all_hazards` list attribute
- [ ] Hazard datetime serialized as ISO string, enums as string values
- [ ] Attribute hazard list capped at 20 entries sorted by severity
- [ ] Safety entities update via push on hazard state change
- [ ] Diagnostic entities use EntityCategory.DIAGNOSTIC
- [ ] 10+ new tests passing
- [ ] All existing tests still pass
- [ ] Legacy `_process_alerts` in aggregation is skipped when coordinator_manager exists
- [ ] Legacy `_process_alerts` still fires when domain coordinators are NOT enabled

---

## Part 7: Adaptive Rate-of-Change Detection (v3.6.0.10)

Building on the Safety Coordinator infrastructure from this plan, v3.6.0.10 replaced fixed rate-of-change thresholds with per-sensor adaptive baselines.

### Problem
Fixed rate thresholds (-5.0/+5.0/+10.0°F per 30min) produce false HVAC failure alerts because sensor noise varies dramatically between devices. A noisy in-wall outlet sensor has ±7°F/30min noise, while a thermostat has ±0.5°F/30min.

### Solution
- **Full 30-min window** (MIN_WINDOW_SECONDS = 1800): no extrapolation, actual delta over actual 30 minutes
- **Per-sensor MetricBaseline** from coordinator_diagnostics.py (Welford's online algorithm)
- **During learning** (< 60 samples): 2x generous fixed thresholds to avoid false positives
- **Once baseline active**: z-score detection. 3σ → MEDIUM, 4σ → HIGH, 5σ → CRITICAL
- **Persistence**: baselines saved to SQLite via metric_baselines table (coordinator_id="safety_rate")
- **Periodic save**: every 30 minutes to prevent data loss

### Files Changed
- `domain_coordinators/safety.py`: RateOfChangeDetector rewritten with adaptive baselines, SafetyCoordinator gains load/save/periodic-save for rate baselines

---

## Part 8: Presence Hardening (v3.6.0.11)

Building on the Presence Coordinator from C1, v3.6.0.11 hardens zone presence detection with fallback mechanisms and geofence improvements.

### Problem

Zone presence remains fragile: missing HA area assignments, area registry naming mismatches, geofence triggers only on AWAY transitions, and long AWAY hysteresis (300s) cause slow detection recovery. When a room is marked UNKNOWN despite occupancy, the Presence Coordinator can't reliably emit house state changes.

### Solution

**Device area_id fallback in room sensor discovery:**
- Room sensor discovery first checks entity `area_id` against room config
- If no match, fallback to device `area_id` via `device_entities()`
- Catches sensors with mismatched entity/device area assignments

**Area registry name matching fallback in room area map:**
- `_build_area_room_lookup()` now tries both:
  1. Exact `area_id` match (current approach)
  2. Fuzzy name match on HA area registry (if ID lookup fails)
- Example: room config `area_id = "kitchen_main"` but HA registry has `area_name = "Kitchen"` → match via case-insensitive name comparison
- Prevents unmapped rooms when area ID is stale

**Geofence triggers from any state (not just AWAY):**
- Currently geofence only triggers transition FROM AWAY to HOME
- Now geofence triggers on:
  - AWAY → HOME (current)
  - HOME → AWAY (departure detection on exit)
  - SLEEP ↔ HOME (bedtime / wake detection)
  - Any state with geofence distance < threshold
- Improves responsiveness to state changes

**AWAY hysteresis reduced 300→30s:**
- Faster AWAY detection after short departures (errands, brief trips outside)
- Still protected by 30s window against zigzag due to BLE noise
- Matched to Home Assistant's geofence convergence time

**Deferred retry on blocked transitions:**
- Some state transitions are blocked (e.g., AWAY→SLEEP blocked when occupants in house)
- When blocked, enqueue retry timer (30s) instead of failing silently
- Retries blocked transition until it's allowed or timeout expires
- Improves recovery when transient conditions prevent state change

### Files
- `domain_coordinators/presence.py` — device area_id fallback, area registry name matching fallback, geofence trigger expansion, reduced AWAY hysteresis, deferred retry logic
- `domain_coordinators/house_state.py` — state transition gate updates to support deferred retry
- `const.py` — new constants for fallback thresholds, retry timeout
- `manifest.json` — version 3.6.0.11

**Estimated:** ~80 new lines, ~50 modified lines, 5+ new tests

---

## NOT in scope (deferred)

- Zone presence fix (separate investigation)
- `sensor.ura_safety_affected_rooms` with zone attribution (depends on zone presence fix)
- `sensor.ura_safety_active_responses` (needs response-tracking state management)
- `sensor.ura_safety_recommendations` (needs recommendation engine)
- Full alert light harmonization (remove side effect from property getter, event-driven approach)
