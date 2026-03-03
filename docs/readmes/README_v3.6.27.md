# URA v3.6.27 — Music Following Diagnostic Sensors

**Date:** 2026-03-03
**Scope:** sensor.py, music_following.py

## Summary

Adds 4 diagnostic sensors to the Music Following Coordinator device (matching the pattern established by Presence, Safety, and Security coordinators) and fixes a state transition bug in the standalone music_following.py.

## Bug Fix: Health Sensor State Leak

`_on_person_transition` set `self._state = "following"` before `_execute_transfer` checked whether music was actually playing. Early returns (no player found, source not playing, cooldown blocked) didn't reset state, causing `MusicFollowingHealthSensor` to show `"following"` for pure person transitions with no music activity.

**Fix:** Removed premature state assignment. State now only changes to `"transferring"` inside `_execute_transfer` after passing all checks, and to `"following"` only on verified success. The `finally` block resets to `"idle"` unless state is already `"following"` or `"idle"`.

## New Sensors

| Sensor | Entity ID | Type | State |
|--------|-----------|------|-------|
| Music Following Anomaly | `sensor.ura_music_following_anomaly` | DIAGNOSTIC | Anomaly severity from detector |
| Music Following Transfers Today | `sensor.ura_music_following_transfers_today` | Visible/MEASUREMENT | Integer count of transfers |
| Music Following Active Rooms | `sensor.ura_music_following_active_rooms` | Visible | CSV of rooms with media players |
| Music Following Last Transfer | `sensor.ura_music_following_last_transfer` | Visible | Last transfer result |

## Implementation Details

- `_music_following_device_info()` helper added (DRY pattern matching `_safety_device_info()`)
- `MusicFollowingHealthSensor` updated to use shared helper
- Push-updated sensors (transfers, active rooms, last transfer) use `mf.add_diagnostic_listener()`
- Anomaly sensor polls from coordinator manager (same as other anomaly sensors)

## Files Changed

- `custom_components/universal_room_automation/music_following.py` — state transition fix
- `custom_components/universal_room_automation/sensor.py` — 4 new sensor classes, device info helper, registration

## Tests

645/645 passed.
