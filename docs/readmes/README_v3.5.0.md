# Universal Room Automation v3.5.0 — Camera Occupancy Extension, Zone Aggregation & Perimeter Alerting

**Release Date:** 2026-02-24
**Internal Reference:** Cycle 4 Slim / PLANNING_v3.5.1_CYCLE_4_SLIM.md v1.0
**Previous Release:** v3.4.6
**Minimum HA Version:** 2024.1+
**Depends on:** v3.4.0+ camera census foundation

---

## Summary

v3.5.0 builds on the camera integration foundation from v3.4.0 to make camera data actionable in three areas: keeping rooms occupied when cameras still see people after motion timeout, surfacing per-zone person identity and guest count sensors, and alerting when an unaccounted-for person is detected on the perimeter during configurable overnight hours.

### What's New

**Camera Extends Room Occupancy**
- When motion sensors and mmWave time out but a camera in the room's area still detects a person, the room stays marked occupied
- Prevents lights from turning off while someone is sitting still in a camera-monitored area
- Implemented as a lightweight override at the end of the existing occupancy timeout block in the coordinator — no changes to normal motion/mmWave logic
- Requires cameras to be area-assigned in the integration-level camera config (v3.4.0+)

**Zone Person Aggregation**
- Two new zone-level sensors, both disabled by default:
  - `sensor.{zone}_identified_persons` — lists BLE-tracked persons currently located in rooms belonging to the zone, by name
  - `sensor.{zone}_guest_count` — estimates unidentified persons in the zone using house-level census data (camera total minus BLE-identified count)
- Zone sensors read from the existing `PersonCensus` engine in `camera_census.py` — no duplicate counting system

**Unexpected Person Detection (upgraded from stub)**
- `binary_sensor.ura_unexpected_person_detected` was a placeholder in v3.4.0. It is now real logic.
- Fires when the house-level camera person total exceeds the number of actively BLE-tracked persons
- Attributes include `camera_total`, `ble_total`, and `guest_count` for use in automations
- Uses `BinarySensorDeviceClass.PROBLEM` so it surfaces naturally in the HA problem dashboard

**Perimeter Intruder Alerting**
- New `PerimeterAlertManager` monitors perimeter cameras during configurable alert hours (default 11 PM – 5 AM)
- Sends a notification when a person is detected on a perimeter camera and no recent egress crossing has been recorded (2-minute egress suppression window prevents false alerts from residents leaving)
- 5-minute cooldown per camera prevents alert storms from a single detection event
- Notification service and target are fully configurable — any HA notify service works
- `sensor.ura_perimeter_alert_status` diagnostic sensor tracks last alert time (disabled by default)

**New Config Flow Step — Perimeter Alerting**
- Integration options menu includes a new "Perimeter Alerting" step
- Configurable fields: alert hours start (0–23), alert hours end (0–23, wraps overnight), notification service (e.g., `notify.mobile_app_john`), notification target (optional)

**New Entities (2 enabled, 3 disabled by default)**

| Entity | Type | Default | Description |
|--------|------|---------|-------------|
| `binary_sensor.ura_unexpected_person_detected` | binary_sensor | enabled | On when cameras see more persons than BLE can account for (upgraded from stub) |
| `sensor.{zone}_identified_persons` | sensor | disabled | BLE-tracked persons in the zone, by name |
| `sensor.{zone}_guest_count` | sensor | disabled | Estimated unidentified persons in the zone |
| `sensor.ura_perimeter_alert_status` | sensor | disabled | Diagnostic: timestamp of last perimeter alert |

Note: `binary_sensor.ura_unexpected_person_detected` existed as a stub in v3.4.0. The entity ID does not change — only the logic behind it.

**Graceful Degradation**
- All features degrade cleanly when cameras or BLE are not configured. See the Graceful Degradation section for the full scenario table.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `perimeter_alert.py` | **Created** | PerimeterAlertManager: alert hours, egress suppression, per-camera cooldown, notify dispatch (~331 lines) |
| `coordinator.py` | Modified | Camera-extends-occupancy block after existing timeout logic (~20 lines) |
| `camera_census.py` | Modified | `get_cameras_for_area()` and `get_person_sensor()` helper methods for coordinator integration (~30 lines) |
| `aggregation.py` | Modified | ZoneIdentifiedPersonsSensor, ZoneGuestCountSensor, UnexpectedPersonBinarySensor real logic (~120 lines) |
| `binary_sensor.py` | Modified | UnexpectedPersonBinarySensor wired to census + person_coordinator |
| `sensor.py` | Modified | PerimeterAlertStatusSensor (~40 lines) |
| `__init__.py` | Modified | PerimeterAlertManager setup and teardown wiring (~15 lines) |
| `config_flow.py` | Modified | Perimeter alerting options step: alert hours, notify service, notify target (~30 lines) |
| `strings.json` | Modified | UI labels for all new perimeter alerting config fields (~15 lines) |
| `translations/en.json` | Modified | Synced from strings.json |
| `const.py` | Modified | Perimeter alert constants, zone sensor keys (~15 lines) |

---

## How to Deploy

### From source (development)

```bash
# Stamp the version and deploy
./scripts/deploy.sh "3.5.0" "Camera occupancy extension, zone aggregation and perimeter alerting" "- Camera extends room occupancy: stays occupied when camera still sees person after motion timeout
- Zone identified persons sensor: lists BLE-tracked persons by name per zone (disabled by default)
- Zone guest count sensor: camera total minus BLE count per zone (disabled by default)
- Unexpected person binary sensor upgraded from stub to real census-backed logic
- Perimeter intruder alerting: configurable hours, egress suppression, per-camera cooldown
- Perimeter alert status diagnostic sensor (disabled by default)
- New config flow step for perimeter alerting options
- Full graceful degradation when cameras or BLE not configured"
```

### HACS update

After the GitHub release is published, HACS will detect v3.5.0 as an available update. Update through the HACS UI and restart Home Assistant.

### Manual install

1. Download the release zip from GitHub
2. Extract to `custom_components/universal_room_automation/`
3. Restart Home Assistant

---

## How to Verify It Works

### 1. Integration loads without cameras

If you have no cameras configured, verify the integration starts normally:

- Check **Settings > Devices & Services > Universal Room Automation** — integration should load without errors
- Existing room automation (motion, mmWave, BLE occupancy) should work identically to v3.4.6
- `binary_sensor.ura_unexpected_person_detected` should exist and remain off
- No errors in logs related to camera manager, census, or perimeter alerting

### 2. Verify camera extends room occupancy

1. Configure a room with at least one area-assigned interior camera (set up in v3.4.0+)
2. Enter the room and trigger motion, then sit still until the motion sensor times out
3. While the camera still detects a person, the room should remain occupied
4. Check **Developer Tools > States** for the room occupancy entity — it should remain `on`
5. Leave the camera's field of view — the room should vacate normally after the timeout

**Check logs:** Search for `universal_room_automation` in **Settings > System > Logs**. You should see:
```
Room {name}: Camera {entity_id} overrides vacancy — person detected
```

### 3. Enable and verify zone aggregation sensors

Zone aggregation sensors are disabled by default. To enable them:

1. Go to **Settings > Devices & Services > Universal Room Automation**
2. Click the integration entry to expand entities
3. Find `sensor.{zone}_identified_persons` and `sensor.{zone}_guest_count` for your zone
4. Click each entity and toggle **Enable**
5. Restart or wait for the next update cycle

**Verify identified persons:**

| Entity | Expected behavior |
|--------|------------------|
| `sensor.{zone}_identified_persons` | State shows comma-separated BLE-tracked person names currently in zone rooms (e.g., `john, sarah`). State is `none` when zone is empty. Attributes include `persons` (list), `count` (int), `zone` (name). |
| `sensor.{zone}_guest_count` | State shows integer guest estimate. Attributes include `camera_total` and `ble_count` for debugging. Shows `0` when no cameras or BLE absent. |

### 4. Verify unexpected person detection

1. In **Developer Tools > States**, find `binary_sensor.ura_unexpected_person_detected`
2. The entity should be off when all persons in the house are BLE-tracked
3. To test: if you have cameras configured and a visitor arrives (no BLE device), the sensor should turn on
4. Check attributes: `camera_total`, `ble_total`, `guest_count` should all be populated

Simulated test (if you don't have a visitor handy): temporarily disable a person's BLE device from the URA person config while they remain in a camera-monitored area. The sensor should fire within one update cycle.

### 5. Configure and verify perimeter alerting

1. Go to **Settings > Devices & Services > Universal Room Automation**
2. Click **Configure** on the main integration entry
3. Select **Perimeter Alerting** from the options menu
4. Set alert hours (e.g., start: 23, end: 5 for 11 PM to 5 AM)
5. Enter your notification service (e.g., `notify.mobile_app_john`)
6. Optionally set a notification target
7. Save

**Verify alerting behavior:**

To test during non-overnight hours, temporarily set the alert hours to include the current hour.

- Trigger a perimeter camera detection (have someone walk in front of a perimeter camera)
- If no egress camera fired in the last 2 minutes, a notification should arrive
- Trigger again within 5 minutes — no second notification should fire (cooldown active)
- Trigger an egress camera first, then the perimeter camera within 2 minutes — no alert (egress suppression)

**Verify egress suppression:** Walk out through a door monitored by an egress camera, then walk back into the yard past a perimeter camera. No alert should fire because the egress crossing was recorded.

**Check the diagnostic sensor:**

Enable `sensor.ura_perimeter_alert_status` and verify it shows the timestamp of the last alert that fired.

**Check logs:**

```
PerimeterAlertManager: Person detected on {camera_entity_id} — alert sent
PerimeterAlertManager: Person detected on {camera_entity_id} — cooldown active, suppressed
PerimeterAlertManager: Person detected on {camera_entity_id} — egress suppression active, suppressed
PerimeterAlertManager: Person detected on {camera_entity_id} — outside alert hours, suppressed
```

### 6. Verify graceful degradation

See the Graceful Degradation section below for the full scenario table. Key checks:

- Remove all cameras from the integration config — integration loads, occupancy extension skips silently, zone sensors return empty/zero, unexpected person stays off, perimeter alerting does nothing
- Remove all BLE persons — zone identified persons shows empty, guest count equals camera total
- Set no notification service in perimeter alerting config — manager logs a warning on detection but does not crash

---

## Graceful Degradation

All v3.5.0 features degrade cleanly. No errors or degraded performance when optional components are absent.

| Scenario | Behavior |
|---|---|
| No cameras configured | Camera occupancy extension skips entirely. Zone sensors use BLE-only data. Unexpected person sensor stays off. PerimeterAlertManager.async_setup() returns immediately. |
| No BLE persons tracked | Zone identified persons shows empty / `none`. Zone guest count equals camera total. Unexpected person sensor fires if any camera sees anyone. |
| No perimeter cameras configured | PerimeterAlertManager finds no cameras to monitor and exits setup silently. No entities are affected. |
| No notification service configured | Manager logs a warning when a detection would have triggered an alert. No crash, no alert sent. |
| Camera entity unavailable | Skipped in occupancy override check. Room vacates on the normal motion/mmWave timeout. |
| person_coordinator absent | Zone identified persons and zone guest count return empty/zero. Unexpected person sensor stays off. |
| Census data absent or stale | Zone guest count and unexpected person sensor return 0 / off. |
| Alert hours exclude current time | No alert sent. Manager logs suppression reason at debug level. |
| All features absent (no cameras, no BLE) | Integration behaves identically to v3.3.x baseline. All pre-existing room automation continues normally. |

---

## Version Mapping

External HACS versions are sequential. Internal plan document names reflect the original feature planning order:

| External Version | Cycle | Internal Plan Reference | Feature |
|-----------------|-------|------------------------|---------|
| 3.3.5.8 | Cycle 1 | — | Bug fixes + occupancy resiliency |
| 3.3.5.9 | Cycle 2 | — | Safe service calls + HVAC zone presets |
| 3.4.0 | Cycle 3 | PLANNING_v3.5.0_CYCLE_3.md | Camera census foundation |
| 3.4.1 – 3.4.6 | Cycle 3 patches | — | Camera config at integration level + stability |
| **3.5.0** | **Cycle 4 Slim** | **PLANNING_v3.5.1_CYCLE_4_SLIM.md** | **Camera occupancy extension, zone aggregation, perimeter alerting (this release)** |
| 3.5.1 | Cycle 5 | PLANNING_v3.4.0_CYCLE_5.md | AI custom automation rules |
| 3.5.2 | Cycle 6 | PLANNING_v3.5.2_CYCLE_6.md | Transit validation + warehoused sensors |

---

## Known Limitations

- **Zone guest count is house-level, not zone-level:** The `sensor.{zone}_guest_count` sensor uses the house-wide camera-minus-BLE delta rather than a per-zone camera count. If guests are concentrated in one zone, the count on other zones will be inflated. Per-zone camera attribution is deferred to a future cycle.
- **Perimeter alerting is notification-only:** The `PerimeterAlertManager` sends notifications but does not yet trigger HA automations or update a persistent threat level. A `SecurityCoordinator` with richer trigger support is planned for v3.6.0.
- **Camera occupancy extension requires area assignment:** The coordinator looks up cameras by area. Cameras that are configured but not assigned to an HA area will not extend occupancy for any room. Ensure area assignment is complete in the integration camera config.
- **Unexpected person sensor has a ~30-second lag:** The house-level census recalculates on a 30-second interval. The unexpected person sensor reflects the last census result, not real-time camera state. Per-room real-time detection remains available via `binary_sensor.{room}_camera_person_detected` (from v3.4.0).
- **Per-room guest detection is deferred:** Room-level `room_identified_persons`, `room_guest_count`, and `room_total_persons` state keys were scoped out of this cycle. The full design is preserved in `PLANNING_v3.5.1_CYCLE_4.md` and can be implemented when real-world testing shows the need.
