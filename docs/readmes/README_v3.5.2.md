# Universal Room Automation v3.5.2 — Transit Validation & Warehoused Sensors

**Release Date:** 2026-02-25
**Internal Reference:** Cycle 6 / PLANNING_v3.5.2_CYCLE_6.md v1.0
**Previous Release:** v3.5.1
**Minimum HA Version:** 2024.1+
**Depends on:** v3.5.1 (consistent sensor naming, zone aggregation, perimeter alerting)

---

## Summary

v3.5.2 is the final camera intelligence cycle before v3.6.0 domain coordinators. It adds two major capabilities: **transit path validation** that enriches room-to-room transitions with camera checkpoint data, and **six warehoused sensors** originally deferred from Cycle 3. A new `transit_validator.py` module validates transitions without replacing the existing `TransitionDetector` — camera data is additive and all features degrade gracefully when cameras are absent.

### What's New

**Transit Path Validation**
- New `TransitValidator` class validates room transitions using shared-space camera checkpoint data (hallways, foyers, stairs)
- When BLE says a person moved from room A to room B, the validator checks whether any shared-space camera saw movement in the checkpoint window
- Path confidence is adjusted: +0.10 for confirmed paths, -0.15 when cameras are active but saw nothing, 0.00 when no camera data exists
- Validation results are persisted to the `room_transitions` database table via two new columns (`validation_method`, `checkpoint_rooms`)
- Multi-person transit handling: when two people transit simultaneously, sightings are correlated by face ID (if available) then by timing proximity

**Identity Validation (Face Recognition)**
- Separate from path validation — identity confirmation does not affect transition confidence
- Controlled by new `CONF_FACE_RECOGNITION_ENABLED` toggle (default: `False`)
- When enabled, camera face recognition data confirms or contradicts BLE identity
- Status values: `confirmed`, `unidentified`, `mismatch`, `unavailable`
- When disabled, always returns `unavailable` — no face matching attempted

**Egress Direction Tracking**
- New `EgressDirectionTracker` correlates egress camera events with interior near-door cameras to determine entry vs exit direction
- Logic: egress fires then interior fires within 45s = entry; interior fires then egress fires within 30s = exit; neither = ambiguous
- Fires `ura_person_egress_event` on the HA event bus with direction, confidence, and camera metadata
- Ambiguous events are recorded but do not increment entry/exit count sensors
- Confirmed events are persisted to the new `person_entry_exit_events` database table

**Warehoused Sensors (6 sensors from Cycle 3)**
- `sensor.ura_persons_entered_today` — confirmed entry count via egress cameras, resets at midnight, restores from DB on HA restart
- `sensor.ura_persons_exited_today` — confirmed exit count, same midnight reset and DB restore behavior
- `sensor.ura_last_person_entry` — timestamp of most recent confirmed entry (does not reset at midnight)
- `sensor.ura_last_person_exit` — timestamp of most recent confirmed exit
- `binary_sensor.ura_census_mismatch` — turns on when camera count and BLE count diverge by 2+ persons for 10+ minutes
- `sensor.ura_unidentified_persons` — house-level count of camera-visible persons that BLE cannot identify

**Phone-Left-Behind Diagnostic**
- `binary_sensor.{person_id}_phone_left_behind` — disabled by default (diagnostic entity)
- Turns on when BLE says person is home but no camera has seen them in 4+ hours
- Suppressed during sleep hours (22:00–07:00)
- Best-effort signal — false positives expected in homes with limited camera coverage in private rooms

**PersonLikelyNextRoomSensor Enhancement**
- Existing `sensor.{person_id}_likely_next_room` gains three new attributes:
  - `camera_last_seen` — timestamp of the person's most recent camera sighting
  - `camera_last_room` — room where the person was last seen by camera
  - `transit_camera_validated` — boolean indicating whether camera data supports the prediction

---

## New Entities

### Enabled by Default

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.ura_persons_entered_today` | sensor | Confirmed entry count today (resets midnight, restores from DB) |
| `sensor.ura_persons_exited_today` | sensor | Confirmed exit count today (resets midnight, restores from DB) |
| `sensor.ura_last_person_entry` | sensor (timestamp) | Most recent confirmed entry timestamp |
| `sensor.ura_last_person_exit` | sensor (timestamp) | Most recent confirmed exit timestamp |
| `binary_sensor.ura_census_mismatch` | binary_sensor (problem) | On when camera vs BLE count diverges 2+ for 10+ min |
| `sensor.ura_unidentified_persons` | sensor | House-level unidentified persons (camera total minus BLE identified) |

### Disabled by Default (Diagnostic)

| Entity | Type | Description |
|--------|------|-------------|
| `binary_sensor.{person_id}_phone_left_behind` | binary_sensor (problem) | BLE home but no camera sighting in 4+ hours |

### Modified Entities

| Entity | Change |
|--------|--------|
| `sensor.{person_id}_likely_next_room` | New attributes: `camera_last_seen`, `camera_last_room`, `transit_camera_validated` |

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `transit_validator.py` | **Created** | TransitValidator + EgressDirectionTracker + TransitValidationResult dataclass (~678 lines) |
| `__init__.py` | Modified | Initialize TransitValidator and EgressDirectionTracker, wire into TransitionDetector (~38 lines) |
| `binary_sensor.py` | Modified | CensusMismatchSensor + PersonPhoneLeftBehindSensor (~209 lines) |
| `sensor.py` | Modified | 4 entry/exit sensors + UnidentifiedPersonsSensor + PersonLikelyNextRoomSensor enrichment (~346 lines) |
| `database.py` | Modified | New person_entry_exit_events table, update_transition_validation(), log_entry_exit_event(), get_entry_exit_events_since(), PRAGMA-based migration for room_transitions columns (~125 lines) |
| `transitions.py` | Modified | Wire in TransitValidator, set_transit_validator(), _update_transition_confidence() (~47 lines) |
| `const.py` | Modified | Transit validation, egress direction, census mismatch, and face recognition constants (~20 lines) |
| `config_flow.py` | Modified | CONF_FACE_RECOGNITION_ENABLED toggle (~7 lines) |
| `strings.json` | Modified | UI labels for face recognition config (~6 lines) |
| `translations/en.json` | Modified | Synced from strings.json (~6 lines) |

---

## How to Deploy

### From source (development)

```bash
./scripts/deploy.sh "3.5.2" "Transit validation and warehoused sensors" "- TransitValidator: path validation via shared-space cameras (no per-room topology required)
- EgressDirectionTracker: egress + interior camera correlation for entry/exit direction
- TransitValidationResult: path and identity validation as separate concerns
- CONF_FACE_RECOGNITION_ENABLED: toggle for identity validation (default False)
- sensor.ura_persons_entered_today / exited_today with midnight reset + DB restore on startup
- sensor.ura_last_person_entry / last_person_exit (timestamp sensors)
- binary_sensor.ura_census_mismatch (camera vs BLE count divergence, 10-min sustain)
- sensor.ura_unidentified_persons (house-level; per-zone deferred)
- binary_sensor.{person}_phone_left_behind (diagnostic, disabled by default)
- PersonLikelyNextRoomSensor enriched with camera validation attributes
- person_entry_exit_events database table + PRAGMA-based migration for room_transitions"
```

### HACS update

After the GitHub release is published, HACS will detect v3.5.2 as an available update. Update through the HACS UI and restart Home Assistant.

### Manual install

1. Download the release zip from GitHub
2. Extract to `custom_components/universal_room_automation/`
3. Restart Home Assistant

---

## How to Verify It Works

### 1. Integration loads without cameras

If you have no cameras configured, verify the integration starts normally:

- Check **Settings > Devices & Services > Universal Room Automation** — integration should load without errors
- All existing room automation (motion, mmWave, BLE occupancy) should work identically to v3.5.1
- New sensors should exist but show 0 / `None` / off
- `binary_sensor.ura_census_mismatch` should remain off
- `sensor.{person}_likely_next_room` should show `transit_camera_validated: false`
- No errors in logs related to transit validation or egress tracking

### 2. Verify transit path validation

Requires at least one shared-space camera (hallway, foyer, staircase):

1. Walk from one room to another through a camera-monitored hallway
2. BLE should detect the transition (existing behavior)
3. Check the `room_transitions` database table — the row should have `validation_method` populated
4. If the hallway camera fired during transit: `validation_method: "path_confirmed"`, confidence boosted by +0.10
5. If the hallway camera was active but didn't fire: `validation_method: "path_implausible"`, confidence reduced by -0.15

**Check logs:**
```
TransitValidator initialized: subscribed to N camera entities, face_recognition_enabled=False
Camera sighting recorded: entity=binary_sensor.hallway_person, person=unidentified, room=Hallway
```

### 3. Verify egress direction tracking

Requires egress cameras (front door, garage) and interior near-door cameras (foyer, garage hallway):

1. Walk in through the front door — egress camera fires, then foyer camera fires
2. After 45 seconds, direction should resolve as "entry"
3. Check `sensor.ura_persons_entered_today` — should increment by 1
4. Check `sensor.ura_last_person_entry` — should show current timestamp

Walk out through the front door — foyer camera fires first, then egress camera:
1. Direction should resolve as "exit"
2. `sensor.ura_persons_exited_today` increments
3. `sensor.ura_last_person_exit` updates

**Check logs:**
```
Egress direction resolved: camera=binary_sensor.front_door_person, direction=entry, confidence=0.80
```

### 4. Verify midnight reset and DB restore

1. Note the current entry/exit counts
2. Wait for midnight (or temporarily adjust system time for testing)
3. `sensor.ura_persons_entered_today` and `sensor.ura_persons_exited_today` should reset to 0
4. `sensor.ura_last_person_entry` and `sensor.ura_last_person_exit` should retain their values (no reset)

For DB restore testing:
1. Record some entry/exit events
2. Restart Home Assistant
3. Count sensors should restore today's totals from the database (not start at 0)

### 5. Verify census mismatch detection

1. Find `binary_sensor.ura_census_mismatch` in **Developer Tools > States**
2. Sensor should be off when camera count and BLE count are within 1 person of each other
3. To test: if cameras see 4 persons but only 2 BLE devices are home, wait 10 minutes — sensor should turn on
4. Check attributes: `camera_count`, `ble_count`, `mismatch_since`, `threshold`, `duration_minutes`

### 6. Verify unidentified persons sensor

1. Find `sensor.ura_unidentified_persons` in **Developer Tools > States**
2. Value = camera total minus BLE identified count (minimum 0)
3. Attributes show `camera_total`, `ble_identified`, `data_scope: "house_level"`
4. If no cameras configured, value should be `None`

### 7. Verify phone-left-behind diagnostic (optional)

This sensor is disabled by default. To test:

1. Enable `binary_sensor.{person}_phone_left_behind` in the entity registry
2. Sensor turns on when: BLE says person is home AND no camera sighting in 4+ hours AND outside sleep hours
3. Suppressed during sleep hours (22:00–07:00)
4. Resets immediately when any camera sees the person again

### 8. Verify face recognition toggle (optional)

1. Go to **Settings > Devices & Services > Universal Room Automation > Configure**
2. Find the face recognition toggle — default is off
3. When off: `identity_status` on all transit validations is `"unavailable"`
4. When on: transit validation uses face data from camera attributes (`person_id`, `face_id`, `label`)

### 9. Verify database migration

For existing installations upgrading from v3.5.1:

1. Restart Home Assistant after updating
2. Check logs for migration messages — PRAGMA check should add `validation_method` and `checkpoint_rooms` columns to `room_transitions`
3. New `person_entry_exit_events` table should be created
4. No errors on second restart (columns already exist, PRAGMA check skips ALTER)

---

## Graceful Degradation

All v3.5.2 features degrade cleanly. No errors or degraded performance when optional components are absent.

| Scenario | Behavior |
|---|---|
| No cameras configured | TransitValidator subscribes to 0 entities. All transit validations return `no_camera_data` with 0.0 confidence delta. EgressDirectionTracker skips initialization. Entry/exit sensors stay at 0. Census mismatch stays off. Unidentified persons returns None. |
| No egress cameras | EgressDirectionTracker has no cameras to monitor. No `ura_person_egress_event` events fire. Entry/exit count and timestamp sensors remain at 0/None. Transit path validation still works with interior cameras. |
| No BLE persons tracked | Census mismatch: BLE count = 0, so mismatch fires if cameras see 2+ persons for 10+ min. Unidentified persons = camera total. Phone-left-behind returns None (no person_coordinator data). |
| Face recognition disabled (default) | Identity validation always returns `"unavailable"`. Path validation still operates normally. No face matching logic executes. |
| Face recognition enabled but no face data | Identity validation returns `"unavailable"` (same as disabled). Graceful fallback — no errors. |
| Camera entity unavailable | Skipped in sighting collection. Path validation treats it as no data (0.0 delta). |
| Database unavailable | Transit validation works but results are not persisted. Entry/exit events not logged. Count sensors start at 0 (no DB restore). Logged as error, non-fatal. |
| person_coordinator absent | Census mismatch returns None. Phone-left-behind returns None. Unidentified persons returns None. |
| HA restart mid-day | Entry/exit count sensors restore from DB using `_restoring` flag to prevent double-counting. |
| All features absent (no cameras, no BLE) | Integration behaves identically to v3.5.1 baseline. All pre-existing room automation continues normally. |

---

## Version Mapping

| External Version | Cycle | Internal Plan Reference | Feature |
|-----------------|-------|------------------------|---------|
| 3.3.5.8 | Cycle 1 | — | Bug fixes + occupancy resiliency |
| 3.3.5.9 | Cycle 2 | — | Safe service calls + HVAC zone presets |
| 3.4.0 | Cycle 3 | PLANNING_v3.5.0_CYCLE_3.md | Camera census foundation |
| 3.4.1 – 3.4.6 | Cycle 3 patches | — | Camera config at integration level + stability |
| 3.5.0 | Cycle 4 Slim | PLANNING_v3.5.1_CYCLE_4_SLIM.md | Camera occupancy extension, zone aggregation, perimeter alerting |
| 3.5.1 | Cycle 5 | PLANNING_v3.4.0_CYCLE_5.md | Consistent sensor naming |
| **3.5.2** | **Cycle 6** | **PLANNING_v3.5.2_CYCLE_6.md** | **Transit validation + warehoused sensors (this release)** |

---

## Known Limitations

- **Zone-level unidentified count deferred:** `sensor.ura_unidentified_persons` is house-level only. Per-zone camera data does not exist in the current architecture. Per-zone unidentified count will ship when per-zone camera attribution is available (post-v3.5.2).
- **Egress direction uses all interior cameras:** Without explicit adjacency mapping, `EgressDirectionTracker` checks all interior cameras for direction correlation. This is conservative — it may produce false entry/exit determinations if unrelated interior cameras fire within the window. In practice, only foyer/hallway cameras near doors typically fire during egress events.
- **Entry/exit counts are camera-only:** Count sensors require egress cameras to be configured. BLE-only installations will see 0 counts permanently. The sensors do not count BLE arrivals/departures.
- **Phone-left-behind is noisy:** The diagnostic sensor will false-positive for anyone who spends extended time in a private room without camera coverage (bedroom, home office). It is disabled by default and intended for diagnostic use only.
- **Census mismatch has a 10-minute delay:** By design, the mismatch sensor requires sustained divergence before turning on. Brief discrepancies (e.g., someone walking between camera zones) will not trigger it.
- **Face recognition depends on camera integration:** Identity validation requires the camera integration (Frigate or UniFi Protect) to expose face/person data in entity attributes. Not all camera setups provide this data.
- **Multi-person transit correlation is best-effort:** When multiple people transit simultaneously and camera sightings can't be face-matched, attribution is by timing proximity. This may occasionally assign a sighting to the wrong transition.
