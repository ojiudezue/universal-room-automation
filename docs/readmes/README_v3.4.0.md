# Universal Room Automation v3.4.0 — Camera Integration & Dual-Zone Person Census

**Release Date:** 2026-02-23
**Internal Reference:** Cycle 3 / PLANNING_v3.5.0_CYCLE_3.md v1.4
**Previous Release:** v3.3.5.9
**Minimum HA Version:** 2024.1+

---

## Summary

v3.4.0 adds camera platform integration and a dual-zone person census engine. The integration now discovers Frigate and UniFi Protect camera entities, cross-validates person detection between platforms, and cross-correlates camera face recognition with BLE IRK phone tracking to produce a house-wide person census.

### What's New

**Camera Platform Integration**
- Automatic discovery of Frigate and UniFi Protect camera entities via the HA entity registry
- Frigate: reads `binary_sensor.*_person_occupancy` and `sensor.*_person_count`
- UniFi Protect: reads `binary_sensor.*_person_detected`
- Cross-validation: when both platforms monitor the same room, counts are compared for confidence scoring

**Dual-Zone Person Census**
- **House census** (interior): counts people inside the house using interior room cameras + BLE tracking. Distinguishes identified persons (face or BLE) from unidentified guests (camera sees someone BLE can't account for).
- **Property census** (exterior): counts people on the property but outside the house using egress and perimeter cameras.
- Census confidence scoring: high (platforms agree + BLE confirms), medium (partial agreement), low (disagreement or single source), none (no data)

**Three-Tier Camera Configuration**
- **Room-level** (`camera_person_entities`): Interior cameras assigned per room in the sensor config step. These feed room occupancy and the house census.
- **Integration-level** (`egress_cameras`): Door cameras (doorbells, door-mounted). Track entry/exit boundary. Do NOT feed room occupancy (avoids delivery/solicitor noise).
- **Integration-level** (`perimeter_cameras`): Yard, fence, and exterior cameras. Security detection only.

**New Entities (8 enabled, 4 disabled by default)**

| Entity | Type | Default | Description |
|--------|------|---------|-------------|
| `sensor.ura_persons_in_house` | sensor | enabled | Total persons inside the house |
| `sensor.ura_identified_persons_in_house` | sensor | enabled | Count of known persons (face or BLE identified) |
| `sensor.ura_unidentified_persons_in_house` | sensor | enabled | Count of unidentified persons (guests) |
| `sensor.ura_persons_on_property` | sensor | enabled | Persons outside on property |
| `sensor.ura_total_persons_on_property` | sensor | enabled | House + property combined total |
| `binary_sensor.ura_unexpected_person_detected` | binary_sensor | enabled | On when unidentified persons detected and all BLE persons accounted for |
| `binary_sensor.{room}_camera_person_detected` | binary_sensor | enabled | Per-room camera person detection |
| `sensor.{zone}_person_count` | sensor | enabled | Per-zone person count |
| `sensor.ura_census_confidence` | sensor | disabled | Diagnostic: current census confidence level |
| `sensor.{zone}_identified_persons` | sensor | disabled | Per-zone identified person list |
| `sensor.{room}_camera_person_count` | sensor | disabled | Per-room camera person count (noisy) |
| `sensor.ura_census_validation_age` | sensor | disabled | Diagnostic: seconds since last census update |

**Census Database**
- Census snapshots logged every 30 seconds to `census_snapshots` table
- 90-day automatic retention with cleanup

**Graceful Degradation**
- No cameras configured = v3.3.x behavior. All existing functionality is preserved.
- Census entities still appear but report BLE-only data with low confidence.
- No errors or degraded performance when cameras are absent.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `camera_census.py` | **Created** | CameraIntegrationManager + PersonCensus engine (~430 lines) |
| `const.py` | Modified | 14 new constants (camera config, platform IDs, confidence levels) |
| `sensor.py` | Modified | 7 census sensor classes + base class |
| `binary_sensor.py` | Modified | CameraPersonDetectedSensor (per-room) + URAUnexpectedPersonSensor |
| `config_flow.py` | Modified | Camera entity selectors in room sensor step + integration options |
| `database.py` | Modified | census_snapshots table + log/query/cleanup methods |
| `__init__.py` | Modified | Camera manager + census initialization in setup sequence |

---

## How to Deploy

### From source (development)

```bash
# Stamp the version and deploy
./scripts/deploy.sh "3.4.0" "Camera integration and dual-zone person census" "- Dual-platform camera discovery (Frigate + UniFi Protect)
- Cross-validation between platforms for person counting
- Person identification: face recognition + BLE IRK cross-correlation
- Dual-zone census: house (interior) + property (exterior)
- Three-tier camera config: room interior, egress, perimeter
- 8 census entities (enabled) + 4 diagnostic entities (disabled)
- Census snapshot database with 90-day retention
- Full graceful degradation when cameras not configured"
```

### HACS update

After the GitHub release is published, HACS will detect v3.4.0 as an available update. Update through the HACS UI and restart Home Assistant.

### Manual install

1. Download the release zip from GitHub
2. Extract to `custom_components/universal_room_automation/`
3. Restart Home Assistant

---

## How to Verify It Works

### 1. Integration loads without cameras

If you have no cameras configured, verify the integration starts normally:

- Check **Settings > Devices & Services > Universal Room Automation** — integration should load without errors
- Check **Developer Tools > States** — search for `sensor.ura_persons_in_house`. It should exist and show BLE-tracked person count with `confidence: low`
- Existing room automation (motion, mmWave, BLE occupancy) should work identically to v3.3.5.9

### 2. Configure interior cameras (room-level)

1. Go to **Settings > Devices & Services > Universal Room Automation**
2. Click **Configure** on a room entry (e.g., Living Room)
3. In the **Sensors** step, find the new **Camera Person Entities** field
4. Select the camera person detection entities for that room:
   - Frigate: `binary_sensor.living_room_person_occupancy`
   - UniFi Protect: `binary_sensor.living_room_person_detected`
5. Save

**Verify:** `binary_sensor.living_room_camera_person_detected` should appear and reflect camera state.

### 3. Configure egress and perimeter cameras (integration-level)

1. Go to **Settings > Devices & Services > Universal Room Automation**
2. Click **Configure** on the main integration entry
3. Select **Camera Census** from the menu
4. Add egress cameras (doorbells/door cams) and perimeter cameras (yard/fence cams)
5. Save

**Verify:** `sensor.ura_persons_on_property` should reflect exterior detections.

### 4. Verify census sensors

In **Developer Tools > States**, check:

| Entity | Expected behavior |
|--------|------------------|
| `sensor.ura_persons_in_house` | Shows total interior count. Attributes include `identified_count`, `unidentified_count`, `confidence` |
| `sensor.ura_identified_persons_in_house` | Shows count of known persons. `person_list` attribute has JSON array of person IDs |
| `sensor.ura_unidentified_persons_in_house` | Shows guest count (camera sees more than BLE can identify) |
| `sensor.ura_persons_on_property` | Shows exterior person count from egress + perimeter cameras |
| `sensor.ura_total_persons_on_property` | Sum of house + property |
| `binary_sensor.ura_unexpected_person_detected` | On when unidentified > 0 |

### 5. Verify cross-validation (dual-platform users)

If you run both Frigate and UniFi Protect on the same cameras:

1. Have someone stand in a room with both camera platforms configured
2. Check `sensor.ura_persons_in_house` attributes:
   - `frigate_count` and `unifi_count` should both show > 0
   - `source_agreement` should be `both_agree`
   - `confidence` should be `high`

### 6. Verify graceful degradation

1. Remove all camera entities from a room's config
2. Room automation should continue working with motion + mmWave + BLE only
3. Census sensors should still report BLE-only data

### 7. Check logs

In **Settings > System > Logs**, search for `universal_room_automation`:

- On startup: `Camera discovery complete: X Frigate, Y UniFi Protect entities found`
- Every 30s: `Census complete: house=N (identified=X, unidentified=Y, confidence=Z), property=M, total=T`
- No errors related to camera discovery or census calculation

---

## Version Mapping

External HACS versions are sequential. Internal plan document names reflect the original feature planning order:

| External Version | Cycle | Internal Plan Reference | Feature |
|-----------------|-------|------------------------|---------|
| 3.3.5.8 | Cycle 1 | — | Bug fixes + occupancy resiliency |
| 3.3.5.9 | Cycle 2 | — | Safe service calls + HVAC zone presets |
| **3.4.0** | **Cycle 3** | **PLANNING_v3.5.0_CYCLE_3.md** | **Camera census (this release)** |
| 3.4.1 | Cycle 4 | PLANNING_v3.5.1_CYCLE_4.md | Camera-BLE fusion + perimeter alerting |
| 3.5.0 | Cycle 5 | PLANNING_v3.4.0_CYCLE_5.md | AI custom automation rules |
| 3.5.1 | Cycle 6 | PLANNING_v3.5.2_CYCLE_6.md | Transit validation + warehoused sensors |

---

## Known Limitations

- **Face recognition entities not yet wired:** The `face_persons` field in census results is currently empty. Face recognition entity patterns vary by Frigate/UniFi version and will be connected in v3.4.1 (Cycle 4).
- **Property census is coarse:** Exterior person count uses active-camera-count as a proxy (1 active camera = 1 person). No numeric person counting on perimeter cameras. This improves in v3.5.1 (Cycle 6) with egress directional tracking.
- **No automation triggers from census:** Census data is read-only sensors in this release. Person-specific automation triggers arrive in v3.5.0 (Cycle 5).
- **Census update interval is 30 seconds:** Not real-time. Sensor-driven state changes (camera binary_sensor on/off) are immediate per-room, but the aggregated census recalculates on a 30-second interval.
