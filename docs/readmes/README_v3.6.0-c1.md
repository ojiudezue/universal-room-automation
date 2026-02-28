# Universal Room Automation v3.6.0-c1 — Presence Coordinator

**Release Date:** 2026-02-28
**Internal Reference:** C1 (Presence Coordinator)
**Previous Release:** v3.6.0-c0.4
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c0.4
**Design Document:** PLANNING_v3.6.0_REVISED.md

---

## Summary

v3.6.0-c1 adds the Presence Coordinator — the first domain coordinator in the v3.6.0 coordinator architecture. It provides house-level state inference, zone-level presence tracking, and user-facing override controls via select entities.

### What's New

1. **`domain_coordinators/presence.py`** — New module (~490 lines) with three core classes:
   - **PresenceCoordinator** — Priority-60 coordinator that subscribes to census signals and room occupancy sensors, runs periodic 60-second inference for time-based transitions, manages zone trackers, and exposes house state override get/set
   - **StateInferenceEngine** — Rules-based house state inference: census=0 → AWAY, arrival detection → ARRIVING, time-of-day HOME variants (day/evening/night), configurable sleep hours → SLEEP, waking detection with confidence scoring
   - **ZonePresenceTracker** — Per-zone 4-state model (away/occupied/sleep/unknown) with 3-tier signal support (room sensors > zone cameras > BLE), override with auto-resume (clears AWAY override when presence detected), sleep mode propagation from house state

2. **House State on Three Devices** — House state sensor and override select on:
   - **URA Integration device** — `sensor.ura_integration_house_state` + `select.ura_house_state_override`
   - **Coordinator Manager device** — `sensor.ura_house_state` (existing) + `select.ura_cm_house_state_override`
   - **Presence Coordinator device** — `sensor.ura_presence_house_state` + confidence, anomaly, compliance sensors

3. **Binary Sensors** — On the Presence Coordinator device:
   - `binary_sensor.ura_house_occupied` — On when house is not AWAY/VACATION
   - `binary_sensor.ura_house_sleeping` — On when house state is SLEEP
   - `binary_sensor.ura_guest_mode` — On when house state is GUEST

4. **Select Entities** — Dashboard-controllable overrides:
   - House state override selects (on URA + CM devices) — 10 options: auto + 9 house states
   - Zone presence mode select (on zone devices) — 5 options: auto, away, occupied, sleep, unknown

5. **Zone Presence Model**:
   - 4 states: `away`, `occupied`, `sleep`, `unknown`
   - `unknown` for zones with no sensors (graceful degradation)
   - Override hierarchy: coordinator auto-derives → house override propagates down → zone override stays local → auto-resume on contradicting presence
   - Sleep mode propagation: house SLEEP sets all zones to sleep (unless manually overridden)

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `domain_coordinators/presence.py` | **New** | PresenceCoordinator, StateInferenceEngine, ZonePresenceTracker, ZonePresenceMode. 3-tier signal support (room sensors, cameras, BLE). Entity registry area_id-based discovery. Camera timeout. Unavailability guards. |
| `sensor.py` | Modified | Added IntegrationHouseStateSensor, PresenceHouseStateSensor (with extra_state_attributes), HouseStateConfidenceSensor (0.0-1.0), PresenceAnomalySensor (with insufficient_data), PresenceComplianceSensor (reads from compliance tracker) |
| `binary_sensor.py` | Modified | Added HouseOccupiedBinarySensor, HouseSleepingBinarySensor, GuestModeBinarySensor on Presence device |
| `select.py` | Modified | Added entry type routing, IntegrationHouseStateOverrideSelect, CMHouseStateOverrideSelect, PresenceHouseStateOverrideSelect, ZonePresenceModeSelect (created from Zone Manager entry) |
| `aggregation.py` | Modified | Added ZonePresenceStatusSensor per zone (created from Zone Manager entry) |
| `__init__.py` | Modified | Register PresenceCoordinator, add Platform.SELECT to INTEGRATION_PLATFORMS |
| `const.py` | Modified | Added presence constants (sleep hours, zone modes, override options). Version bump to 3.6.0-c1. |
| `manifest.json` | Modified | Version bump to 3.6.0-c1 |

---

## Tests

- **52 new tests** in `quality/tests/test_presence_coordinator.py`
- Tests cover: StateInferenceEngine (12), ZonePresenceTracker (13), PresenceCoordinator (6), Constants (4), ZonePresenceMode (2), Camera signals (6), BLE signals (3), Multi-tier interaction (3), Unavailability guards (3)
- **Full suite: 478 tests pass, 0 failures, 0 regressions**
- Code review (27 issues found): 10 critical fixed, 3 minor fixed, 8 deferred to future cycles, 6 acknowledged as aspirational

---

## How to Deploy

```bash
./scripts/deploy.sh "3.6.0-c1" "Add Presence Coordinator with house state inference and zone tracking" \
  "- PresenceCoordinator: house state inference, zone presence tracking
- StateInferenceEngine: time-based transitions, sleep hours, confidence scoring
- ZonePresenceTracker: 4-state model (away/occupied/sleep/unknown), auto-resume
- House state sensor + override select on 3 devices (URA, CM, Presence)
- Binary sensors: house occupied, sleeping, guest mode
- Zone presence mode select entities
- 37 new tests, 463 total passing"
```

---

## How to Verify It Works

### 1. New entities appear

After restart, check for new entities:

**Sensors:**
- `sensor.ura_integration_house_state` (on URA device)
- `sensor.ura_presence_house_state` (on Presence device)
- `sensor.ura_presence_house_state_confidence` (on Presence device)
- `sensor.ura_presence_anomaly_status` (on Presence device)
- `sensor.ura_presence_compliance_rate` (on Presence device)

**Binary sensors:**
- `binary_sensor.ura_house_occupied` (on Presence device)
- `binary_sensor.ura_house_sleeping` (on Presence device)
- `binary_sensor.ura_guest_mode` (on Presence device)

**Selects:**
- `select.ura_house_state_override` (on URA device)
- `select.ura_cm_house_state_override` (on CM device)

### 2. House state transitions work

- With nobody home: state should be `away`
- When someone arrives: should transition through `arriving` → `home_day`/`home_evening`
- During configured sleep hours with people home: should transition to `sleep`

### 3. Override selects work

- Select "guest" from the house state override dropdown
- Verify `sensor.ura_house_state` and both integration/presence house state sensors show "guest"
- Select "auto" to clear the override
- Verify state returns to auto-derived value

### 4. No regressions

- All existing room automation continues working
- All existing coordinator manager entities remain functional
- Integration page shows Presence Coordinator device under CM

---

## Entity Summary

| Entity | Device | Type | Description |
|--------|--------|------|-------------|
| `sensor.ura_integration_house_state` | URA Integration | Sensor | House state (duplicate for convenience) |
| `select.ura_house_state_override` | URA Integration | Select | House state override control |
| `sensor.ura_presence_house_state` | Presence Coordinator | Sensor | House state from Presence |
| `sensor.ura_presence_house_state_confidence` | Presence Coordinator | Sensor | Inference confidence (0-100%) |
| `sensor.ura_presence_anomaly_status` | Presence Coordinator | Sensor | Anomaly detection status |
| `sensor.ura_presence_compliance_rate` | Presence Coordinator | Sensor | Compliance rate percentage |
| `binary_sensor.ura_house_occupied` | Presence Coordinator | Binary Sensor | House is occupied |
| `binary_sensor.ura_house_sleeping` | Presence Coordinator | Binary Sensor | House is in sleep mode |
| `binary_sensor.ura_guest_mode` | Presence Coordinator | Binary Sensor | Guest mode active |
| `select.ura_cm_house_state_override` | Coordinator Manager | Select | House state override (CM) |
| `select.ura_{zone}_presence_mode` | Zone device | Select | Zone presence mode override |

---

## Architecture Notes

### House State Override Flow

```
User selects "guest" on any house state override select
  → _HouseStateOverrideSelectBase.async_select_option()
    → PresenceCoordinator.set_house_state_override("guest")
      → HouseStateMachine.set_override(HouseState.GUEST)
      → All zone trackers: propagate_house_state("guest")
    → All house state sensors update on next poll
```

### Zone Presence Signal Tiers

1. **Room sensors** (highest confidence): mmWave, PIR motion, occupancy binary sensors
2. **Zone cameras** (medium confidence): Person/motion detection with timeout
3. **Bermuda BLE** (lowest confidence): BLE distance tracking

Zones with no sensors report `unknown` — never report false `away`.

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1 | C0.1 | Integration page organization |
| 3.6.0-c0.2 | C0.2 | Census graceful degradation fix |
| 3.6.0-c0.3 | C0.3 | Coordinator entity unavailability fix |
| 3.6.0-c0.4 | C0-diag | Coordinator diagnostics framework |
| **3.6.0-c1** | **C1** | **Presence Coordinator** |
