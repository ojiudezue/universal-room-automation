# v3.6.33 — Transit Detection Pipeline Fix

## Summary

Fixed two bugs causing `persons_entered_today` and `persons_exited_today` to be
permanently 0 since they were added. The transit detection pipeline now initializes
correctly and resolves sensors across multiple camera platforms (Frigate + UniFi).

## Bug 1: Init Ordering (Critical)

`EgressDirectionTracker.async_init()` reads `hass.data[DOMAIN]["camera_manager"]`
during initialization — but `camera_manager` wasn't stored in `hass.data` until
~40 lines AFTER the egress tracker init ran. Result: `async_init()` returned early,
subscribed to zero sensors, and no egress events ever fired.

**Fix:** Moved camera_manager + census initialization block to run BEFORE transit
validator and egress tracker initialization in `__init__.py`.

## Bug 2: Single-Platform Resolution

Even with init fixed, transit detection only found Frigate `_person_occupancy`
sensors. Each physical camera also has a separate UniFi device with
`_person_detected` sensors that fire as often or more (doorbell: 80 UniFi vs
57 Frigate events/week). These were invisible to transit detection.

Additionally, Frigate `sensor.*_person_count` (0→1 transitions) provides
high-confidence entry detection but was unused.

**Fix:** Added cross-platform sensor resolution that:
- Resolves camera.* entities to sensors across ALL platforms by stem matching
- Subscribes to `sensor.*_person_count` for 0→N transition detection
- Deduplicates when Frigate + UniFi fire for same physical camera within 5s
- Boosts confidence to 0.9 when 2+ platforms agree on direction

## Files Changed

| File | Change |
|------|--------|
| `__init__.py` | Reordered camera_manager init before transit validator |
| `camera_census.py` | Added `resolve_cross_platform_sensors()`, `_extract_camera_stem()`, transit helpers on PersonCensus |
| `transit_validator.py` | Cross-platform subscription, person_count callback, stem dedup, multi-platform confidence |
| `const.py` | VERSION → 3.6.33 |

## Verification

1. All existing tests pass
2. After restart, HA logs should show:
   - `"EgressDirectionTracker initialized: N egress sensors, M egress count sensors, K interior sensors"` with N > 0
   - `"Cross-platform resolution found N additional sensors"` with N > 0
3. Walk past egress camera → `sensor.universal_room_automation_persons_entered_today` increments
4. Census sensors unaffected — still uses single-platform resolution path
