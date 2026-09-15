# URA v5.102.1 — Appliance census refresh: fix off-loop thread-safety (v5.102.0 live finding)

**Shipping:** 2026-09-15
**Tier:** 1 (single-site thread-safety fix)
**Card:** APPLIANCE-MGMT-REFINE-1 (v1a live-validation fix-up)

## What this fixes

v5.102.0's live validation surfaced a thread-safety warning that static review and the test suite
missed: `sensor.py:8121`, the `ApplianceCensusSensor` refresh timer, used
`async_schedule_update_ha_state(force_refresh=True)`. `force_refresh` drives the entity-update
machinery, which spawned a task off the event loop and tripped HA's frame guard:

> Detected that custom integration 'universal_room_automation' calls `hass.async_create_task` from a
> thread other than the event loop, which may cause Home Assistant to crash or data to corrupt … at
> sensor.py, line 8121

The census functioned correctly regardless (state = 220), but the warning flags a real off-loop
`async_create_task` and would break in HA 2027.

## The fix

The census sensor computes its state and attributes entirely in the property getters
(`native_value` → `_resolve_cached()` → fresh), so it never needed a forced entity update. Replaced the
`lambda … async_schedule_update_ha_state(True)` with a `@callback` method that calls
`async_write_ha_state()` — in-loop, no task, and it re-reads the (freshly re-resolving) properties.

Why it was missed: the unit tests drive the resolver and the properties directly, not the real
`async_track_time_interval` callback in a running event loop. This was a live-only defect — the exact
class the post-deploy validation step exists to catch.

## Verification
| Check | Result |
|---|---|
| `py_compile` sensor.py | OK |
| appliance tests | **27 passed** |
| Branch discipline | committed on develop (verified) |

### Acceptance criteria — Live (validate post-restart)
- **Live:** no `async_create_task from a thread other than the event loop` frame warning citing
  `sensor.py` (appliance census timer) after restart.
- **Live:** `sensor.ura_appliance_coordinator_appliance_census` continues to update on its 30s interval
  (state tracks record count) with no recorder-oversize WARNING.

## Live Validation — to be completed post-restart
- [ ] No off-loop `async_create_task` frame warning from the census timer
- [ ] Census sensor still updates on interval; state = record count
