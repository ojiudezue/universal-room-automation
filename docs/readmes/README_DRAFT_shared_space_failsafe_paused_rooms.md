# DRAFT: shared-space night failsafe runs in paused rooms

Card: SHARED-SPACE-AUTO-OFF-FAILSAFE-1, option A. Branch `fix/shared-space-failsafe-paused-rooms`. Not yet deployed.

## What changed

The once-a-night, vacancy-gated shared-space failsafe (v5.103.101) was called only inside the room's master-automation branch in `coordinator.py` `_async_update_data`. A room with `switch.<room>_automation` OFF never ran it, so Kitchen (paused on purpose for daytime occupancy automation) kept its overhead light on all night.

The call now sits at the post-block unconditional site next to the humidity safety cap, the same hoist precedent as FIX A / D-HIGH-1. It runs once per periodic tick whether the master switch is on or off.

The failsafe body (`automation.check_scheduled_auto_off`) is unchanged: shared-space only, auto-off hour to cutoff window, at most once per night, no sweep while occupied, boot-settle gate, manual-on holds respected.

Gates kept at the new call site:
- First refresh after restart (skip-first): never acts.
- ManualMode ON: no failsafe. This is the "hands off this room" switch, distinct from the master pause, so it stays as a conservative gate.
- Override occupied / vacant: already applied to `data[STATE_OCCUPIED]` before the call.

## Tests

`quality/tests/test_shared_space_failsafe_paused_rooms.py` drives the real `UniversalRoomCoordinator._async_update_data`:
paused + vacant gets called with vacant, paused + occupied gets called with occupied, unpaused gets exactly one call per tick, skip-first and ManualMode get no call, and with the real body a paused vacant room in the window is swept while a paused occupied room is not.

## Live acceptance criteria

- **Live:** on the first night after deploy, with `switch.kitchen_automation` OFF and Kitchen vacant at some tick between the auto-off hour and 05:00, `ura_activity_log` has a row with `action='shared_space_auto_off'`, `room='Kitchen'`, at or after the auto-off hour. The Kitchen overhead is off by morning.
- **Live (negative):** a Kitchen tick that is occupied all through the window produces no such row. A different failure (for example, the failsafe still gated) shows no row on a night when Kitchen was vacant.
- **Live:** shared-space rooms with automation ON still produce at most one `shared_space_auto_off` row per night.
