# PLANNING v3.19.0 — Zone Camera Intelligence: Face-Confirmed Arrivals

**Version:** v3.19.0
**Date:** 2026-03-27
**Status:** Draft — Reviewed by Staff PM
**Parent plans:** PLANNING_v3.17.0_HVAC_ZONE_INTELLIGENCE.md, v3.18.x hardening
**Depends on:** v3.18.6 (BLE pre-arrival, person-to-zone mapping)
**Estimated effort:** 2 deliverables, ~6-8 hours total
**Priority:** MEDIUM — enhances zone arrival reaction speed

---

## OVERVIEW

Zone cameras provide face recognition that enables instant person identification — faster than BLE (which needs 15-min away timer) and more reliable than geofence (which needs the HA Companion App). When a zone camera recognizes a face, we can immediately fire pre-arrival for that person's zones.

### Scope: Arrival-Only (PM Review Decision)

v3.19.0 focuses ONLY on **face-confirmed arrival**. Accelerated vacancy via face-confirmed departure was removed — it's under-designed (how does a zone camera know someone left the zone vs. left the room?) and the 2-min grace was too aggressive. Deferred to v3.20+.

### What Already Exists (CRITICAL — Do Not Rebuild)

The codebase already has extensive zone camera infrastructure:

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| **Presence Coordinator zone camera discovery** | DONE | presence.py:896-944 | Auto-discovers cameras via area_id→zone mapping |
| **ZoneTracker camera state tracking** | DONE | presence.py:105-106, 211-230 | Per-camera `_camera_occupied`, `_camera_last_seen`, timeout-based occupancy |
| **Camera state change handler** | DONE | presence.py:1096-1124 | `_handle_camera_change()` routes events to zone trackers |
| **Camera → room mapping via HA area_id** | DONE | transit_validator.py:418-424 | Entity registry lookup |
| **TransitValidator camera sightings** | DONE | transit_validator.py:437-450 | Records per-person sightings with face_id |
| **Frigate face recognition reading** | DONE | camera_census.py:1295-1323 | `_get_face_recognized_persons()` |
| **CONF_FACE_RECOGNITION_ENABLED** | DONE | const.py:795, config_flow.py:1902 | House-level toggle in Integration config |
| **Face ID from camera attributes** | DONE | transit_validator.py:430-435 | Reads `person_id`/`face_id`/`label` from attrs |
| **Pre-arrival signal + handler** | DONE | signals.py:22, hvac.py:873 | `SIGNAL_PERSON_ARRIVING` with source filter |
| **Pre-arrival toggle + diagnostic sensor** | DONE | switch.py, sensor.py | v3.18.6 |
| **Person-to-zone mapping** | DONE | hvac_zones.py, hvac.py | v3.18.5 |

**Key insight:** We do NOT need to add zone camera discovery, camera event subscription, or camera state tracking. The Presence Coordinator already does all of this. We only need to:
1. Add face recognition lookup to the existing `_handle_camera_change` path
2. Fire `SIGNAL_PERSON_ARRIVING` when a face is recognized in a zone camera
3. Add zone camera config to Zone Manager for explicit user control (vs auto-discovery)

---

## RISK ASSESSMENT

| Risk | Mitigation |
|---|---|
| Duplicate camera subscriptions (presence + HVAC) | DO NOT subscribe in HVAC — use presence coordinator's existing subscription |
| Face recognition stale data triggers | Check `last_changed` on face sensor (< 30s freshness) |
| Camera fires frequently (person walks by) | Debounce per-person per-zone: 60s cooldown after firing pre-arrival |
| Triple pre-arrival from geofence + BLE + camera | `_pre_arrival_zones.add()` is idempotent (set) — no duplicate actions |
| Regression: camera detection breaks zone occupancy | We ADD face lookup to existing handler, don't change detection logic |
| Missing @callback on new handlers | Only modifying existing @callback-decorated handlers — verified |

### Wider Code Path Implications

| Existing System | Interaction | Risk |
|---|---|---|
| **TransitValidator** (`_on_camera_state_change`) | Already subscribed to same camera entities. Our change is in Presence Coordinator, not TransitValidator. Two independent subscribers — no conflict. | NONE |
| **Camera Census** (`_get_face_recognized_persons`) | House-level face rec. We READ face sensors the same way. No state mutation. | NONE |
| **HVAC decision cycle** | Triggered by `SIGNAL_PERSON_ARRIVING`. Already handles concurrent triggers via lock + set. | NONE |
| **Music Following** (transition detection) | Uses TransitionDetector + TransitValidator. Unaffected — we don't touch transitions. | NONE |
| **Presence inference engine** | `_run_inference("camera_detection")` already called on camera change. We add face lookup BEFORE inference — no change to inference input. | LOW — verify face lookup doesn't slow down the callback |

---

## DELIVERABLES

| # | Deliverable | Scope | Effort |
|---|-------------|-------|--------|
| D1 | Zone camera config in Zone Manager + face-confirmed arrival signal | Config flow, face lookup in existing camera handler, SIGNAL_PERSON_ARRIVING | ~5 hrs |
| D2 | Diagnostic visibility + source config | Zone status attrs, HVAC attrs, "camera_face" source option, INFO logging | ~2 hrs |

---

## D1: Zone Camera Config + Face-Confirmed Arrival

### Config Flow: Zone Cameras

**Zone Manager → zone_config_menu → "Zone Cameras"**

New step `async_step_zone_cameras`:
- Multi-select entity selector for `binary_sensor` domain with device_class `occupancy` or `motion`
- Stores as `CONF_ZONE_CAMERAS: list[str]` per zone
- Labels: clear description that these supplement auto-discovery, giving explicit user control

```python
vol.Optional(
    CONF_ZONE_CAMERAS,
    default=current_cameras,
): selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="binary_sensor",
        device_class=["occupancy", "motion"],
        multiple=True,
    )
),
```

**Labels:**
- Menu: "📷 Zone Cameras"
- Title: "Zone Cameras"
- Description: "Select person detection cameras in this zone's shared spaces. Cameras already auto-discovered via room area assignments will appear here. Add additional cameras that cover zone common areas (hallways, living spaces). Face recognition from these cameras enables instant pre-arrival conditioning."
- Data description: "Camera person-detection sensors (e.g., Frigate person_occupancy, UniFi person_detected). When a recognized face is seen by these cameras, pre-arrival conditioning starts immediately — no 15-minute BLE wait required."

### ZoneState + Discovery

**File:** `hvac_zones.py`

```python
zone_cameras: list[str] = field(default_factory=list)
```

Read from zone config in `async_discover_zones()`.
Expose in `get_zone_status_attrs()`.

### Face Recognition in Existing Camera Handler

**File:** `presence.py` — modify `_handle_camera_change()` (line 1096)

This is the key change. AFTER the existing camera detection routing (line 1120-1121), add face recognition lookup:

```python
@callback
def _handle_camera_change(self, event: Any) -> None:
    # ... existing detection routing (lines 1103-1122) ...

    # v3.19.0: Face-confirmed arrival — check face recognition
    if detected and self._face_recognition_enabled:
        face_name = self._get_face_for_camera(entity_id)
        if face_name:
            self._handle_face_arrival(entity_id, face_name, zone_name)

    self.hass.async_create_task(self._run_inference("camera_detection"))
```

New helper methods on PresenceCoordinator:

```python
def _get_face_for_camera(self, camera_entity: str) -> str | None:
    """Get recognized face from Frigate face sensor for this camera.

    Uses device registry to find sibling face sensor on same device.
    Returns face name if fresh (< 30s), None otherwise.
    """
    # Use device registry (not string manipulation) per PM review
    ent_reg = er_helper.async_get(self.hass)
    camera_entry = ent_reg.async_get(camera_entity)
    if not camera_entry or not camera_entry.device_id:
        return None

    # Find sensor.*_last_recognized_face on same device
    for entity in er_helper.async_entries_for_device(ent_reg, camera_entry.device_id):
        if (entity.domain == "sensor" and
            entity.entity_id.endswith("_last_recognized_face")):
            state = self.hass.states.get(entity.entity_id)
            if not state or state.state in ("unknown", "unavailable", "", "none", "no_match"):
                return None
            # Freshness check: face rec must be recent
            if state.last_changed and (dt_util.utcnow() - state.last_changed).total_seconds() > 30:
                return None
            return state.state.strip()
    return None

@callback
def _handle_face_arrival(self, camera_entity: str, face_name: str, zone_name: str) -> None:
    """Fire pre-arrival signal for face-recognized person.

    Debounce: 60s cooldown per person per zone.
    """
    person_entity = self._find_person_entity(face_name)
    if not person_entity:
        return

    # Debounce: skip if same person triggered recently
    key = f"{person_entity}:{zone_name}"
    now = dt_util.utcnow()
    last = self._face_arrival_cooldown.get(key)
    if last and (now - last).total_seconds() < 60:
        return
    self._face_arrival_cooldown[key] = now

    async_dispatcher_send(
        self.hass,
        SIGNAL_PERSON_ARRIVING,
        {"person_entity": person_entity, "source": "camera_face"},
    )
    _LOGGER.info(
        "Camera face arrival: %s recognized in zone %s via %s",
        face_name, zone_name, camera_entity,
    )
```

### State on PresenceCoordinator

```python
self._face_arrival_cooldown: dict[str, datetime] = {}  # "person:zone" → last trigger time
```

### Respect Existing Settings

- `CONF_FACE_RECOGNITION_ENABLED` (Integration entry): Must be True for face lookup to activate. Already checked in TransitValidator — add same check here.
- `CONF_PRE_ARRIVAL_SOURCES` (HVAC config): Must include "camera_face". Source filter already in `_handle_person_arriving`.
- Pre-arrival toggle (`switch.ura_hvac_pre_arrival`): Already gates `_handle_person_arriving`.

### Constants

**File:** `hvac_const.py`
```python
CONF_ZONE_CAMERAS: Final = "zone_cameras"
FACE_FRESHNESS_SECONDS: Final = 30
FACE_ARRIVAL_COOLDOWN_SECONDS: Final = 60
```

---

## D2: Diagnostic Visibility + Source Config + Counters

### Visibility Architecture

Users look at three places for zone information. Each gets camera face data at the right level of detail:

#### Layer 1: Zone Devices (Zone Manager) — "What's happening in this zone?"

**`sensor.zone_{name}_presence_status`** (already exists on each zone device)

This sensor's `extra_state_attributes` calls `ZoneTracker.to_dict()`. Currently shows camera detecting state + last_seen per camera. v3.19.0 extends `to_dict()` with face recognition:

**File:** `presence.py` — `ZoneTracker.to_dict()` (line ~271)

Add to the returned dict:
```python
"last_face_recognized": self._last_face_recognized,  # e.g., "oji"
"last_face_time": self._last_face_time.isoformat() if self._last_face_time else None,
"face_arrivals_today": self._face_arrivals_today,
```

New state on ZoneTracker:
```python
self._last_face_recognized: str = ""
self._last_face_time: datetime | None = None
self._face_arrivals_today: int = 0
```

Updated by `_handle_face_arrival()` when a face triggers pre-arrival for this zone.

**Result:** Zone device shows:
```yaml
sensor.zone_entertainment_presence_status:
  state: occupied
  attributes:
    mode: occupied
    signal_tiers:
      room_sensors: true
      camera_sensors: true
      ble_sensors: true
    cameras:
      binary_sensor.hallway_person_occupancy:
        detecting: true
        last_seen: "2026-03-27T..."
    last_face_recognized: "oji"          # NEW
    last_face_time: "2026-03-27T..."     # NEW
    face_arrivals_today: 2               # NEW
    ble_occupied: true
    last_activity: "2026-03-27T..."
```

#### Layer 2: HVAC Coordinator Device — "How is HVAC using zone cameras?"

**`sensor.ura_hvac_coordinator_zone_X_status`** (already exists per zone)

**File:** `hvac_zones.py` — `get_zone_status_attrs()`

Add:
```python
"zone_cameras": zone.zone_cameras,
"camera_face_arrivals_today": zone.camera_face_arrivals_today,
```

New field on ZoneState:
```python
camera_face_arrivals_today: int = 0
```

Incremented by the face arrival handler when a person triggers pre-arrival for this zone. Reset at midnight alongside other daily counters.

**`sensor.ura_hvac_pre_arrival_status`** (v3.18.6, already exists)

Already shows `last_trigger_source`, `last_trigger_person`, `triggers_today`. Camera face triggers automatically appear with `source="camera_face"`. No changes needed.

**HVAC coordinator main sensor attrs:**

Add:
```python
"camera_zone_map": self._camera_zone_map,
```

#### Layer 3: Presence Coordinator Device — "What does the presence system see?"

**`sensor.ura_presence_house_state`** (already exists)

**File:** `sensor.py` — `PresenceHouseStateSensor.extra_state_attributes`

Currently shows `{zone: mode}` (one string per zone). Expand to show signal health + face activity:

```python
"zones": {
    name: {
        "mode": tracker.mode,
        "signal_tiers": {
            "room_sensors": tracker._has_room_sensors,
            "camera_sensors": tracker._has_camera_sensors,
            "ble_sensors": tracker._has_ble_sensors,
        },
        "cameras_active": sum(1 for v in tracker._camera_occupied.values() if v),
        "last_face_recognized": tracker._last_face_recognized,
        "last_face_time": tracker._last_face_time.isoformat() if tracker._last_face_time else None,
    }
    for name, tracker in presence.zone_trackers.items()
}
```

### Pre-Arrival Source Config Update

**File:** `config_flow.py` — `async_step_coordinator_hvac`

Add "Camera Face Recognition" to the pre-arrival sources multi-select:
```python
{"label": "Camera Face Recognition", "value": "camera_face"},
```

### INFO-Level Logging

Every face-confirmed arrival logs at INFO level (visible in standard HA logs without debug mode):
```
Camera face arrival: oji recognized in zone Entertainment via binary_sensor.hallway_person_occupancy
```

### Anonymous Detection: Diagnostic Only

Camera person detection WITHOUT face recognition sets zone camera state for diagnostic purposes only. No behavioral changes — this is explicitly a "diagnostic attribute, not an action trigger." Anonymous detection already contributes to zone occupancy via the existing `update_camera_detection()` path in presence.py.

### Daily Counter Reset

`ZoneTracker._face_arrivals_today` and `ZoneState.camera_face_arrivals_today` both reset at midnight. Add to existing midnight reset paths in presence.py and hvac.py.

### Labels (strings.json + translations/en.json)

Zone config menu: `"zone_cameras": "📷 Zone Cameras"`

Zone cameras step:
```json
"zone_cameras": {
  "title": "Zone Cameras",
  "description": "Select person detection cameras in this zone's shared spaces. Face recognition from these cameras enables instant pre-arrival conditioning — no 15-minute BLE wait required.",
  "data": {
    "zone_cameras": "Person Detection Cameras"
  },
  "data_description": {
    "zone_cameras": "Camera person-detection sensors (Frigate person_occupancy, UniFi person_detected). Cameras are also auto-discovered from room area assignments."
  }
}
```

HVAC coordinator sources:
```json
"pre_arrival_sources": add "Camera Face Recognition" option
```

---

## RESTART RESILIENCE & RECOVERY

| State | Source of Truth | On URA Restart | On HA Restart | Persistence Needed? |
|---|---|---|---|---|
| Zone camera assignments (`CONF_ZONE_CAMERAS`) | Config entry | Survives | Survives | NO — config entries are durable |
| Auto-discovered zone cameras | `_discover_zone_cameras()` in presence.py | Re-discovered at setup | Re-discovered at setup | NO — rebuilt from live entity registry |
| Camera detection state (`_camera_occupied`) | Live sensor events | Rebuilt on first camera event | Rebuilt on first camera event | NO — transient, rebuilds in seconds |
| Face arrival cooldown (`_face_arrival_cooldown`) | In-memory dict | Lost | Lost | NO — 60s debounce, worst case is one duplicate trigger |
| Daily face arrival counters | In-memory on ZoneTracker + ZoneState | Lost (resets to 0) | Lost (resets to 0) | NO — cosmetic counter, not actionable |
| Pre-arrival zones | `_zone_state_store` (Store, v3.18.2) | Restored with 4h staleness guard | Restored with 4h staleness guard | ALREADY DONE |
| Person-zone map | Zone config → cache → DB fallback (v3.18.5) | Rebuilt + fallback chain | Same | ALREADY DONE |
| Camera-zone map | Built from zone config at startup | Rebuilt from config | Rebuilt from config | NO — derived from config |
| Face recognition enabled | Config entry (`CONF_FACE_RECOGNITION_ENABLED`) | Survives | Survives | NO — config entry |
| Pre-arrival sources | Config entry (`CONF_PRE_ARRIVAL_SOURCES`) | Survives | Survives | NO — config entry |
| Pre-arrival toggle state | RestoreEntity switch | Restored | Restored | ALREADY DONE |

**Summary:** No new persistence needed. All configuration survives restarts via config entries. All runtime state either rebuilds automatically from live data or has existing Store-backed persistence (v3.18.2/v3.18.5). The only transient losses (cooldown dict, daily counters) are cosmetic — no functional harm.

**Recovery timeline after restart:**
- T+0s: Config loaded, zone cameras read from config entries
- T+1-3s: Presence coordinator setup → `_discover_zone_cameras()` runs → camera subscriptions active
- T+5-30s: First camera events arrive → detection state rebuilt
- T+30s: First face recognition opportunity (if person detected by camera)

---

## FILE CHANGES SUMMARY

| File | Changes |
|------|---------|
| `hvac_const.py` | `CONF_ZONE_CAMERAS`, `FACE_FRESHNESS_SECONDS`, `FACE_ARRIVAL_COOLDOWN_SECONDS` |
| `hvac_zones.py` | `zone_cameras` + `camera_face_arrivals_today` on ZoneState; read in discovery; expose in status attrs; midnight reset |
| `presence.py` | `_get_face_for_camera()`, `_handle_face_arrival()`, cooldown dict, face state on ZoneTracker (`_last_face_recognized`, `_last_face_time`, `_face_arrivals_today`), extend `to_dict()`, extend `_handle_camera_change()` |
| `hvac.py` | `_build_camera_zone_map()` (diagnostic); expose `camera_zone_map` in attrs |
| `config_flow.py` | `async_step_zone_cameras` in zone_config_menu; "camera_face" in pre-arrival sources |
| `sensor.py` | Expand `PresenceHouseStateSensor.extra_state_attributes` with signal tiers + face data per zone |
| `aggregation.py` | No changes — `ZonePresenceStatusSensor` already calls `tracker.to_dict()` which we extend |
| `strings.json` | Zone cameras labels/descriptions |
| `translations/en.json` | Same |

### Files NOT Changed (Verified — No Duplication)

| File | Why NOT Changed |
|------|-----------------|
| `camera_census.py` | House-level census stays independent. We READ face sensors the same way — no duplication. |
| `transit_validator.py` | Already tracks camera sightings independently. We don't subscribe in HVAC — presence coordinator already does. |
| `person_coordinator.py` | BLE tracking stays independent. Camera face arrival is a separate trigger source. |
| `switch.py` | No new toggle — existing pre-arrival toggle + source filter provides control. |
| `aggregation.py` | `ZonePresenceStatusSensor` already exposes `tracker.to_dict()` — we extend the dict, not the sensor. |

---

## WHAT IS NOT IN THIS PLAN (DEFERRED)

| Item | Why | Track Where |
|------|-----|-------------|
| Accelerated vacancy via face-confirmed departure | Under-designed: zone camera sees nobody ≠ person left the zone. 2-min grace too aggressive. | v3.20+ with proper design |
| Zone-level person counting from cameras | Complex dedup, low incremental value over BLE | v3.20+ if needed |
| Camera-confirmed house AWAY transition | Would couple zone cameras to inference engine | v3.20+ |
| Pet-specific zone automation | Frigate detects pets but no actions defined | Needs design |
| Anonymous camera detection → behavioral changes | Cross-validation logic undefined. Diagnostic only for now. | v3.20+ |

---

## RESTART RESILIENCE

| State | Persisted? | Recovery |
|---|---|---|
| Zone camera assignments (`CONF_ZONE_CAMERAS`) | Config entry | Survives restart |
| Camera zone map | Rebuilt from config on startup | No persistence needed |
| Face arrival cooldown | Transient (dict) | Acceptable — cooldown resets on restart, worst case is one duplicate trigger |
| Auto-discovered zone cameras | Re-discovered by presence coordinator on startup | No persistence needed |

---

## TEST PLAN

~12-15 tests:
1. D1: Zone camera config read, face sensor discovery via device registry, face freshness guard (fresh=OK, stale=skip), cooldown dedup (second trigger within 60s skipped), person entity mapping from face name, SIGNAL_PERSON_ARRIVING fired with source="camera_face", face rec disabled globally → no trigger
2. D2: Zone status sensor shows zone_cameras, "camera_face" in source filter, INFO log on face arrival

---

## REVIEW PROTOCOL

Mandatory 2-review adversarial before deploy:
- Review 1 (Core A): @callback decorators, None handling in device registry lookup, face sensor freshness, cooldown dict cleanup
- Review 2 (Core B): No duplicate camera subscriptions (presence only), no race with inference engine, signal handler thread safety, restart resilience

Document in `docs/reviews/code-review/v3.19.0_zone_camera_intelligence.md`.

---

## ROLLBACK PLAN

- `CONF_ZONE_CAMERAS` defaults to `[]` — no explicit cameras configured, auto-discovery still works
- "camera_face" not in source filter → face arrivals ignored by HVAC
- Face recognition disabled globally (`CONF_FACE_RECOGNITION_ENABLED=False`) → face lookup skipped
- All changes to `_handle_camera_change` are additive (face lookup AFTER existing logic) — removing them restores original behavior
- No existing behavior modified — purely additive
