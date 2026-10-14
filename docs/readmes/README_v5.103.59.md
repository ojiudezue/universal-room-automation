# URA v5.103.59: remove two remaining boot stalls (room area lookup, camera identifier scan)

Cards: URA-DEVICES-CONFIG-ENTRIES-BOOT-STALL-1 residuals (HA-2027-DEPRECATIONS-URA-1 related). Hotfix, Tier 1: one review covering both branches (`docs/reviews/code-review/v5.103.59_boot_stall_fixes.md`, both SHIP; 1 LOW fixed in-cycle). Deploy risk: **LOW**. No presence, HVAC, safety, energy or battery behaviour change.

## Why
After v5.103.58 removed the 131 s `_devices.py` stall, HA Health Monitor still showed two URA stalls at the 2026-10-14 09:05 boot:
- **9.0 s at `entity.py:80`**: every room entity's `async_added_to_hass` called `dr.async_get_device`, which in HA 2026.10 runs a `report_usage` call-stack walk per call. About 50 entities per room repeated a lookup that only needs to succeed once.
- **1.2 s at `camera_resolver.py:698`**: rung 3 (identifier overlap) walked every device in the registry on every `resolve_capabilities` call.

## What changed
- `entity.py`: the room area-inherit lookup runs once per room coordinator (`_ura_area_inherit_done`). The flag is set only once the room device is found, so if the first entity arrives before the device exists, the next entity retries. An operator-set area is still never overwritten. Accepted narrowing (review): inheritance now runs once per coordinator lifetime, so an area the operator clears is re-inherited only after the next room reload.
- `camera_resolver.py`: a `(integration, key) -> device_ids` index is built once in `_build_indices`, alongside the existing MAC index. Matches are applied in registry order (`_device_order`), so the result is identical to the old loop. Index lifetime is the same as the existing MAC index: camera_census rebuilds its resolver on device/entity-registry updates, and every other call site builds a fresh resolver, so new cameras are picked up.
- `quality/tests/test_d3_area_inherit.py`: its 3 behavioural tests had been erroring because the registry stub never reached `homeassistant.helpers.device_registry`. They now run. Added: once-per-room lookup, and missing-device-then-retry.

## Tests
- Drills, all red as expected: removing the flag check or the flag set reddens `test_device_lookup_runs_once_per_room_not_per_entity`; latching the flag before the device check reddens `test_missing_device_on_first_entity_is_retried_by_next`; emptying the identifier-index lookup reddens `test_rung_identifiers_overlap_pulls_in_sibling_device`.
- Full-suite name-diff: see Pre-deploy gate.

## Bundled operator config action (same restart)
- EC option `energy_solar_follow_grid_fallback_entity` re-pointed from the retired `sensor.envoy_stream_grid_power` to `sensor.envoy_482543015950_current_net_power_consumption` (same sign as the primary Vue meter; kW converted by `energy_pool.py:4888`). This also live-tests the v5.103.57 EC options save.

## Pre-deploy gate
- Full-suite name-diff of develop 2c15723e6 vs 4ca767e56: **CLEAN**, 0 NEW; 3 GONE (the revived d3 area-inherit tests now pass). 119 failed / 14781 passed vs 122 / 14776. py_compile clean.

## Live acceptance
- **Live:** HM loop-stall samples after boot show no `entity.py` or `camera_resolver.py` site.
- **Live:** room devices keep their areas (spot-check 3 rooms in the device registry).
- **Live:** camera census sensors populated as before the restart.
- **Live:** Envoy entry `loaded` and `sensor.envoy_482543015950_battery` reporting, with time-to-healthy compared against the morning's three restarts; reload if it hangs.
- **Live:** EC fallback option holds the new entity after restart; 0 URA ERRORs.
