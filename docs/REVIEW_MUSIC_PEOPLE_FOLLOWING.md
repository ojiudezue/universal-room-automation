# Music & People-Following — Review Findings

**Date:** 2026-03-02
**Reviewer:** ura-reviewer (opus)
**Scope:** music_following.py, person_coordinator.py, transitions.py, camera_census.py, coordinator.py

## P0 — Must Fix

1. **No transition debouncing** (transitions.py:259-279) — BLE boundary flickering fires high-confidence transitions every update cycle. No minimum dwell time, no ping-pong suppression. Combined with #2, causes continuous speaker bouncing.

2. **No music transfer cooldown** (music_following.py:141-230) — Every transition immediately triggers transfer. At room boundaries, music bounces between speakers continuously. Single worst UX failure mode.

3. **Source volume faded but never restored** (music_following.py:561-570) — Source player volume set to 10% during transfer, never saved or restored. Speaker stays at 10% permanently.

4. **Room occupant substring matching false positives** (person_coordinator.py:838-845) — `room_lower in location_lower` means "den" matches "garden", "master" matches both "master_bedroom" and "master_bathroom". Causes incorrect room assignments.

5. **Tests are placeholder assertions** (test_person_tracking.py) — ~25 of 30 test methods are `assert True # Placeholder`. No tests for MusicFollowing or TransitionDetector.

## P1 — Should Fix

6. **Bermuda sensor discovery hardcoded to iPhone** (person_coordinator.py:492-529) — 8 hardcoded patterns like `sensor.{name}_iphone_area`. Samsung, Pixel, Apple Watch all fail. Need configurable `bermuda_area_sensor` field.

7. **`@callback` on async methods** (transitions.py:94, 342) — Same as automation finding. Handlers never execute.

8. **Speaker group grows forever** (music_following.py:580-630) — `media_player.join` without `unjoin`. Walk through 5 rooms = all 5 speakers grouped.

9. **No concurrency protection on transfers** (music_following.py:486-578) — Two rapid transitions run `_transfer_media` concurrently, reading mid-transfer state.

10. **Distance threshold hardcoded in feet** (person_coordinator.py:605) — `distance_ft < 5.0`. Metric Bermuda = 5.0 meters = 16.4 feet. Make configurable.

11. **Camera override has no staleness check** (coordinator.py:569-591) — Stuck Frigate person sensor = room never becomes vacant. Bypasses 4-hour failsafe.

12. **Auto-enables disabled Bermuda entities** (person_coordinator.py:686-717) — URA re-enables user-disabled sensors every cycle. No opt-out.

## P2 — Nice to Have

13. Scanner-to-room map rebuilds every cycle — should cache
14. Hallway detection only checks English "hallway"/"corridor"
15. Sonos arbitrarily preferred in area discovery
16. Media position not offset for transfer delay
17. No Private BLE Device integration awareness
18. Cross-platform generic transfer fails silently for many media types
