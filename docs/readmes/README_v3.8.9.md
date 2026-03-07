# v3.8.9 — Sparse BLE Hardening

## Summary
Hardens BLE-enhanced room occupancy (v3.8.8) for sparse BLE homes. Rooms
that use a shared scanner from an adjacent area (Tier 2 / `CONF_SCANNER_AREAS`)
now require recent motion/mmWave confirmation before BLE can drive occupancy.
This prevents adjacent rooms from falsely showing occupied when a shared scanner
picks up a person who is actually in a different room.

## Changes

### BLE Tier Classification (`person_coordinator.py`)
- New `is_room_direct_ble(room_name)` method — returns True for Tier 1 rooms
  (own scanner via `CONF_AREA_ID`, no `CONF_SCANNER_AREAS`), False for Tier 2
- Classification is cached in `_direct_ble_rooms` set, built during
  `_build_scanner_room_map()` — zero per-cycle cost

### Conditional BLE Override (`coordinator.py`)
- **Tier 1 (direct BLE)**: BLE alone can override vacancy — unchanged from v3.8.8
- **Tier 2 (shared scanner)**: BLE only overrides vacancy if motion/mmWave was
  detected within `2 × occupancy_timeout` seconds. Without recent motion
  confirmation, BLE persons still populate `ble_persons` attribute but do not
  drive occupancy
- Consolidated person_coordinator lookup — eliminated redundant dict access and
  `get_persons_in_room` call when BLE override is denied

### Attribute Behavior
- `ble_persons` is always populated regardless of tier or occupancy state — for
  diagnostic visibility
- `occupancy_source` distinguishes: `"ble"` (BLE driving occupancy) vs
  `"none"` (BLE present but not driving, Tier 2 without motion confirmation)

## Files Changed
- `person_coordinator.py` — `is_room_direct_ble()`, `_direct_ble_rooms` cache
- `coordinator.py` — Tier-aware BLE override, consolidated lookup
- `const.py` — version bump to 3.8.9
