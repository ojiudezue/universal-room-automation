# URA v5.103.58 — device-tree sweep stops reading HA 2026.10's deprecated `config_entries` (131 s boot stall)

Card: URA-DEVICES-CONFIG-ENTRIES-BOOT-STALL-1. Hotfix, Tier 1: one review (SHIP, 2 LOWs fixed in-cycle) plus orchestrator drills. Deploy risk: **LOW**. Same device-tree decisions; only the way the owning entry is read changes. No presence, HVAC, safety or battery behaviour change.

## Why
At the v5.103.57 boot (2026-10-14 08:34 CDT), HA Health Monitor recorded a **131.2 s event-loop stall** at `_devices.py:492 (_is_empty_parent_shell)`, with 10 samples, flagged as a deprecation path. It was followed by 2.6 s repeats. In HA 2026.10.1 `DeviceEntry.config_entries` became a compatibility property (`helpers/device_registry.py:429`) that calls `report_usage`, a call-stack walk, on every read of a non-composite device; it breaks in 2027.10. The device-tree sweep read it once per device. The stall also left the Envoy integration hung in `setup_in_progress`, and reload/disable/enable queued behind it.

## What changed
- New `_device_config_entries(device)` in `_devices.py`. Composite devices return their real multi-owner set, which doesn't trigger a report (`dr.py:435`). Single-owner devices return `{config_entry_id}`, the same set the old property returned (`dr.py:557-561`). Older HA without `config_entry_id` falls back to the old property.
- It's used at both sweep sites: the shell-cleanup sole-owner guard and the stamper's `_is_empty_parent_shell`. The safety guards (exact set equality, CM-owned check) behave identically.
- The diagnostics button lists devices via `dr.async_entries_for_config_entry` instead of reading `config_entries` on every device in the registry (review LOW).

## Tests
- Behavioural anchors for each call site use a device double whose deprecated property raises. Reverting either site turns its own test red, verified per site.
- `test_v5_94_1_shell_cleanup_skips_dual_owned` gets its missing `@pytest.mark.asyncio`. It had been failing on develop without ever running. It now passes.
- The full-suite name-diff vs develop is under Pre-deploy gate.

## Not changed
- Other deprecated registry calls (`__init__.py:5227` devices-as-mapping, `__init__.py:5305` / `entity.py:80` `async_get_device`) are single lookups, not per-device loops. They stay on HA-2027-DEPRECATIONS-URA-1.

## Pre-deploy gate
- Full-suite name-diff of fix branch (7aab1c4e3) vs develop: **CLEAN**, 0 NEW, 1 GONE (`test_v5_94_1_shell_cleanup_skips_dual_owned`, which now actually runs). py_compile clean.

## Live acceptance
- **Live:** HM `loop_stall` samples after boot show no `universal_room_automation/_devices.py` site, and no URA stall over 1 s during boot.
- **Live:** device tree intact: the CM coordinators still nest under the Coordinator Manager, and rooms under Rooms. Spot-check `via_device_id` on 2 coordinators and 2 rooms.
- **Live:** Envoy config entry `loaded`, `sensor.envoy_482543015950_battery` reporting.
- **Live:** 0 URA ERRORs in system_log after boot.

## Validated 2026-10-14 (HA restart 09:05 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| No `_devices.py` stall at boot | **PASS** | HM `markers.loop_lag.stalls` 14:06–14:10Z: no `_devices.py` site, compared with 131.2 s plus 2.6 s repeats at the previous boot. |
| No URA stall > 1 s during boot | **FAIL (residual, fixed on a branch)** | 9.0 s at `entity.py:80 async_added_to_hass` (deprecated `async_get_device`, called once per room entity) and 1.2 s at `camera_resolver.py:698`. The entity.py fix (once per room) is on `fix/entity-area-inherit-lookup` 1fb37b2b9 and ships at the next restart. |
| Device tree intact | **PASS** | `core.device_registry`: 65 URA devices, 0 without a parent. safety/hvac coordinator → coordinator_manager. 47 rooms → Rooms. |
| Envoy loaded and reporting | **PASS** | Entry `loaded`; `sensor.envoy_482543015950_battery` = 6 (09:07), consumption 3.846 kW (09:09). The hung `setup_in_progress` from the previous boot cleared. |
| 0 URA ERRORs | **PASS** | system_log ERROR filter: 0 entries. |
