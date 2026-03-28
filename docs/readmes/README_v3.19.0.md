# URA v3.19.0 -- Zone Camera Intelligence

## Overview

Adds face-confirmed arrivals to the HVAC zone intelligence pipeline. When a Frigate (or compatible) camera recognizes a face in a zone's coverage area, the presence coordinator fires a pre-arrival signal that the HVAC coordinator can use for instant pre-conditioning -- no geofence or BLE delay required.

This is purely additive to the existing camera detection pipeline. All failures are graceful. Face recognition is an accelerator, never a requirement.

## Changes

### Face-Confirmed Arrival Pipeline (presence.py)

- **`_get_face_for_camera(camera_entity)`**: Derives the face sensor entity from the camera's binary_sensor entity ID using Frigate naming conventions (`binary_sensor.{name}_person_occupancy` -> `sensor.{name}_last_recognized_face`). Supports three suffix patterns: `_person_occupancy` (Frigate), `_person_detected` (UniFi), `_occupancy` (generic). Returns the recognized face name if fresh (<30s), None on any failure.
- **`_handle_face_arrival(camera_entity, face_name, zone_name)`**: Debounced (60s per person+zone) signal dispatch. Maps face name to HA person entity, updates zone tracker state, increments HVAC zone counter, fires `SIGNAL_PERSON_ARRIVING` with `source="camera_face"`.
- **`_find_person_entity_from_face(face_name)`**: Two-pass person entity lookup: `person.{lowercase_underscored}` then `person.{raw}`. Returns None if no match.
- **Integration in `_handle_camera_change`**: Three conditions gate face lookup: camera detected person (`detected=True`), camera mapped to a zone (`matched_zone_name`), and feature enabled (`_face_recognition_enabled`). Existing detection routing and inference runs unchanged regardless.

### Zone Camera Configuration (config_flow.py, hvac_zones.py, hvac_const.py)

- **Config flow step `zone_cameras`**: New zone configuration menu item. Entity selector for binary_sensor domain with occupancy/motion device classes. Follows the deep-copy pattern from zone_persons.
- **`CONF_ZONE_CAMERAS`**: New constant in hvac_const.py. Stored per-zone in Zone Manager entry.
- **ZoneState dataclass**: New fields `zone_cameras: list[str]` and `camera_face_arrivals_today: int`. Both exposed in zone diagnostic attributes and reset at midnight.
- **Zone discovery**: `zone_cameras` loaded from config, deduplicated on zone merge (same pattern as zone_persons).

### HVAC Camera Zone Map (hvac.py)

- **`_build_camera_zone_map()`**: Builds a camera -> zone reverse map from zone configs for diagnostics. Read-only -- HVAC does not subscribe to camera state changes (that's the presence coordinator's job).
- **`camera_zone_map` attribute**: Exposed in HVAC coordinator's `extra_state_attributes` for dashboard/diagnostic visibility.
- **Pre-arrival source**: `camera_face` added as a source option in the HVAC coordinator config flow (alongside `geofence` and `ble`). Users enable camera_face in the pre-arrival sources dropdown.

### Presence Sensor Visibility (sensor.py)

- **`PresenceHouseStateSensor.extra_state_attributes`**: Zone details now include `last_face_recognized` (face name string) and `last_face_time` (ISO timestamp or null). These are read via `getattr` with safe defaults from the `ZonePresenceTracker`.

### Face Recognition Toggle

- **Integration-level**: `CONF_FACE_RECOGNITION_ENABLED` in the integration config entry (shared with transit_validator). Read during presence coordinator `async_setup`.
- **HVAC-level**: `camera_face` in `pre_arrival_sources` dropdown. Controls whether HVAC acts on camera_face signals.
- Two-layer design: integration toggle controls whether face detection runs at all; HVAC toggle controls whether HVAC reacts to it.

### ZonePresenceTracker State (presence.py)

- New attributes: `_last_face_recognized`, `_last_face_time`, `_face_arrivals_today`
- Exposed in `to_dict()` with proper `.isoformat()` serialization
- Daily reset via `_count_transition()` at midnight (alongside cooldown dict clear)

## Visibility Across Three Layers

1. **Zone Device** (ZoneState): `zone_cameras`, `camera_face_arrivals_today` in zone diagnostic attributes
2. **HVAC Coordinator**: `camera_zone_map` in HVAC `extra_state_attributes`
3. **Presence Coordinator**: `last_face_recognized`, `last_face_time` per zone in `PresenceHouseStateSensor` attributes

## Resilience Design

- **All failure paths return None/gracefully**: `_get_face_for_camera` has 5 explicit None returns + catch-all try/except. `_handle_face_arrival` has outer try/except. HVAC counter update has its own isolated try/except.
- **Feature gating**: Three conditions must all be true before face lookup runs. If any fails, existing camera detection is completely unaffected.
- **Debouncing**: 60s cooldown per person+zone prevents signal storms from camera flapping.
- **Freshness check**: Face recognition data older than 30s is rejected to prevent stale-data arrivals.
- **Restart safe**: Cooldown and counters reset cleanly. Zone cameras rebuild from config entry (source of truth). No persistent state required.

## Constants (hvac_const.py)

- `CONF_ZONE_CAMERAS`: Config key for zone camera entity list
- `FACE_FRESHNESS_SECONDS = 30`: Maximum age of face recognition data
- `FACE_ARRIVAL_COOLDOWN_SECONDS = 60`: Debounce window per person+zone

## Files Changed

- `domain_coordinators/presence.py` -- face arrival pipeline, ZonePresenceTracker state, daily reset
- `domain_coordinators/hvac.py` -- camera zone map, diagnostic attribute
- `domain_coordinators/hvac_zones.py` -- ZoneState fields, zone discovery, daily reset
- `domain_coordinators/hvac_const.py` -- CONF_ZONE_CAMERAS, face timing constants
- `config_flow.py` -- zone_cameras step, camera_face pre-arrival source option
- `sensor.py` -- PresenceHouseStateSensor face attributes
- `strings.json` + `translations/en.json` -- UI labels for zone_cameras
- `quality/tests/test_fan_control_v318.py` -- 11 new tests (TestZoneCameraFaceArrival)

## Test Coverage

- 11 new tests covering: face sensor derivation (3 patterns), freshness (fresh/stale), cooldown (block/allow), face-to-person mapping, camera zone map building, face value filtering (6 invalid values + 1 valid)
- 49 tests passing in test file (38 existing + 11 new)
- 1189 total tests passing across full suite

## 2-Review Protocol

Both adversarial reviews passed clean. 18 checks verified, 0 bugs found. No CRITICAL, HIGH, MEDIUM, or LOW issues. Implementation follows all established URA patterns including datetime serialization, deep-copy zone updates, @callback decoration, and try/except isolation.

Full review document: `docs/reviews/code-review/v3.19.0_zone_camera_intelligence.md`

## Deferred Items

None. All planned deliverables shipped.

## Post-Deploy Setup

1. Enable face recognition in the integration options (Settings -> Integrations -> URA -> Configure)
2. Assign cameras to zones (Settings -> Integrations -> URA -> Zone Manager -> select zone -> Zone Cameras)
3. Optionally enable `camera_face` in HVAC pre-arrival sources (HVAC coordinator options)
4. Ensure Frigate face recognition is configured and producing `sensor.*_last_recognized_face` entities
