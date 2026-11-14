# DRAFT: Camera input stream health S2 (zone tier, fan readers, census)

Card: CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1. Plan: `docs/planning/PLANNING_camera_input_stream_health.md` S2.
Tier 2-DB (regression-prone: zone occupancy feeds house state; census feeds AWAY / GUEST). Version: set at release.

## What changed

S1 stopped a dead camera's frozen input from holding its ROOM. S2 makes the readers outside the room follow the same
answer, through the same getter:

| Reader | Before | After |
|---|---|---|
| Zone substrate (`OccupancySubstrate`, the zone tracker's Tier-1 view) | a frozen panel `on` held the zone until the 4 h stuck rule | the input counts as off from the first room tick past the 120 s grace; the room tick tells the substrate when an input flips dead or live (`recheck_entities`) |
| Zone camera tier (`ZonePresenceTracker._any_camera_occupied`) | a frozen detection held the zone | a camera entity reported dead is skipped |
| `_zone_night_rooms` (switch-off live limb) | counted the frozen `on` | skips it |
| Presence fan-interference gate (`_room_radar_sole_capable`) | the frozen panel made the room radar-sole | dropped from the live on-set |
| Comfort-fan AWAY veto (`fan_veto`, motion leg + legacy camera leg) | a frozen camera-derived `on` was trusted presence | not trusted |
| Census interior counts (both branches) + unrecognised (guest) count | the frozen count was counted | the camera is a MISSING term (as if unavailable), never a zero |
| Fan pause-recheck | already followed the room (S1) | unchanged (pinned by a test) |

New public getter for later consumers (NVR witness W2 / W6b): `camera_stream_health.camera_stream_dead(hass,
camera_entity)` → True (confirmed dead) / False (watched, live) / None (no room watches that camera; unknown).

No new entity, no new knob, no DB change. Kill switch `CAMERA_INPUT_STREAM_HEALTH_ENABLED` False = every reader
byte-identical to develop (the getter answers False, the discharge never fires).

## Not covered (carded / reported)

- The room-tier fused `binary_sensor.<room>_camera_person_detected` (CONF_ROOM_CAMERAS fusion), which fan_veto's preferred
  camera leg reads.
- Census face reads and the stuck-camera watchdog.
- `camera_stream_dead` returns None for cameras that no room input watches (perimeter ring cameras), so W6b cannot bridge
  them until they are watched.

## Acceptance (prospective)

- **Test:** `quality/tests/test_camera_stream_health_s2.py` (23 tests; 25 single-site source mutations each turned a
  named test red).
- **Live (organic, next panel outage):** within about 2.5 min of the panel camera going `unavailable`, the panel room's
  zone stops being held by the panel input (zone presence select / `binary_sensor` zone occupancy no longer follows the
  frozen `on`); `sensor.universal_room_automation_persons_in_house` stops counting that camera's frozen body.
- **Live (now):** no change while the panels stream (the substrate kinds and census counts match develop).

## Validated

Pending deploy.
