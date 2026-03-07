# v3.8.8 — BLE-Enhanced Room Occupancy

## Summary
Adds BLE/Bermuda person tracking as a room occupancy source. When person_coordinator
knows a tracked person is in a room via BLE, that room counts as occupied even after
motion/mmWave sensors time out. This bridges the gap where BLE data previously only
fed house/zone census but not individual room occupancy.

## Changes

### New: BLE Occupancy Override (`coordinator.py`)
- After motion/mmWave timeout AND camera override, checks `person_coordinator.get_persons_in_room()`
- If BLE-tracked persons are present, room stays occupied with `occupancy_source: "ble"`
- Respects 4-hour failsafe — BLE cannot hold a room occupied indefinitely
- BLE persons always populated in data dict (even when motion is the primary source)

### New: Occupancy Source Tracking
- `STATE_OCCUPANCY_SOURCE` tracks what's driving occupancy: `motion`, `mmwave`, `occupancy_sensor`, `timeout`, `camera`, `ble`, `grace_hold`, `failsafe`, `none`
- `STATE_BLE_PERSONS` lists tracked persons in the room via BLE

### Sensor Changes
- `binary_sensor.*_occupied` now exposes:
  - `occupancy_source` — always present, shows current driver
  - `ble_persons` — always present (empty list when no BLE persons)

### Bug Fixes (from 2 independent reviews)
- **CRITICAL: Failsafe bypass** — BLE/camera overrides could defeat the 4-hour failsafe
  when `_became_occupied_time` was cleared by timeout expiry. Fixed: both overrides now
  always restore `_became_occupied_time` when it's `None`
- **Camera override also lacked failsafe timer** (pre-existing) — fixed alongside BLE
- **Failsafe now sets `occupancy_source: "failsafe"`** instead of leaving stale source
- **DB occupancy log trigger** — now uses `STATE_OCCUPANCY_SOURCE` instead of
  hardcoded motion/presence ternary (correctly logs BLE/camera triggers)
- **`ble_persons` always present** — prevents template errors from flickering attribute

## Files Changed
- `coordinator.py` — BLE override, occupancy source tracking, failsafe fixes
- `binary_sensor.py` — `occupancy_source` and `ble_persons` attributes
- `const.py` — `STATE_BLE_PERSONS`, `STATE_OCCUPANCY_SOURCE`, version bump
