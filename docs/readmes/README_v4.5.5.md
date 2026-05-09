# v4.5.5 — person_coordinator None-data guard (1-line hotfix)

**Date:** 2026-05-08
**Type:** Tier 1 hotfix (one line + 2 regression tests)
**Predecessor:** v4.5.4
**Reproducer:** v4.5.4 post-restart logs surfaced one ERROR:
`person_coordinator.py:881 — Error calculating confidence for Ezinne in Study B: argument of type 'NoneType' is not a container or iterable`

## Summary

`_calculate_confidence` at `person_coordinator.py:865` had:

```python
if person_name in self.data and closest_area_distance is not None:
```

while every other `self.data` access site in the same file (lines 937, 943, 949, 984, 1000, etc.) is guarded with `if not self.data or person_name not in self.data:`. A single missing guard.

`DataUpdateCoordinator.data` is `None` before the first successful refresh, so during boot `person_name in None` raises `TypeError`. The function's broad `except Exception` caught it, logged the error, and returned `0.5` (medium confidence fallback) — so person tracking kept working but a single ERROR appeared on every restart, polluting the log and losing one tick of `closest_distance` tracking for the affected person/room.

## Fix

```python
# Before
if person_name in self.data and closest_area_distance is not None:
# After
if self.data and person_name in self.data and closest_area_distance is not None:
```

Matches the established guard pattern at the 6+ other access sites in the same file. v4.5.5 ships not restarted live yet — picked up at the next HA restart (per user direction).

## Tests

2 new regression tests in `quality/tests/test_v455_person_coord_none_data.py`:
- `test_calculate_confidence_guards_self_data` — AST-grep over the `_calculate_confidence` function body; every `person_name in self.data` access must have a `self.data and` / `not self.data` guard on the same line.
- `test_other_access_sites_already_guarded` — sanity check that the established `if not self.data or person_name not in self.data:` pattern is still in the file (catches drift from the reference pattern).

**Test count progression:**
- v4.5.4: 1954 tests, 0 isolated failures across 52 files
- **v4.5.5: 1956** (+2), 0 isolated failures across 53 files

## What this DOES NOT do

- Doesn't bundle anything else (deferred from v4.5.4 cycle: stuck-sensor surfacing, music_following / comfort coordinator placeholders, person-tracking architecture audit).
- Doesn't address the chattering Kitchen mmWave sensor (`binary_sensor.mmwave_lux_wifi_esphome_kitchen_presence` firing 27s phantom pulses every few minutes) — that's a hardware-tuning issue (sensitivity = 100, max), not URA code. Surfacing UI for chattering / stuck sensors is a separate roadmap item.
- Doesn't restart HA. Per user direction, the next restart picks up v4.5.5.

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- **No HA restart in this cycle** — fix lands at the next restart for any other reason
