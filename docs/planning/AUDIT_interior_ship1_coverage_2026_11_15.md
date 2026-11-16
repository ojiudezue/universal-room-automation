# AUDIT: interior vision ship 1 coverage (v5.108.28), 2026-11-15 22:5x CDT

Question: Playroom and Family Room cameras are in `camera_person_entities` but have no record in `sensor.ura_interior_awareness`. Why?

## Answer

Neither is missing. Playroom resolves to the URA room **Game Room** and Family Room resolves to the URA room **Living Room**. Both rooms are among the 7 covered. The 12 configured camera entities collapse into exactly 7 groups, one per covered room. No room is dropped by any of the four drop reasons.

There is no URA room named Playroom and no URA room named Family Room. Those are camera/device names; the HA areas are `game_room` and `living_room`.

## Method (registry lookups only, read-only)

- Config: `.storage/core.config_entries`, integration entry, key `camera_person_entities` (12 camera entities), plus room entries (`room_name`, `area_id`, `room_type`).
- Area: `_ensure_interior_groups` uses `resolve_area_id_for_entity` (entity area, then device area), then `PresenceCoordinator._room_area_ids` (`person_sighting.py:347-354`). For all 12 cameras and their person sensors the entity has no area of its own and the device area decides.
- Grouping: ran the real `camera_stream_health.pure_twin_groups` / `camera_device_for_entity` / `twin_pair_for_device` (`camera_stream_health.py:731,849,865`) against the live `.storage` registries. `CAMERA_STREAM_DEAD_TWIN_RULE` = True. Scripts: `.claude/tmp/intcov_probe*.py`, `intcov_groups.py`.
- Drop logic read at `person_sighting.py:1040-1084`; excluded types = bedroom, bathroom (`const.py:3516`).
- Not verified live: the sensor's `rooms` attribute is unrecorded (`sensor.py:4301`) and not in restore_state, so the 7-room list is the operator's report, not re-read by me. The 7 groups below reproduce it exactly.

## Per camera

| camera entity | platform | resolved person sensor | area (source) | URA room (room_type) | group key (min device id) | drop reason |
|---|---|---|---|---|---|---|
| camera.playroom | frigate | binary_sensor.playroom_person_occupancy_2 | game_room (device) | Game Room (common_area) | 12391404... | none; group member |
| camera.playroom_high_resolution_channel | unifiprotect | binary_sensor.playroom_person_detected | game_room (device) | Game Room | 12391404... (twin of above) | none; same group |
| camera.family_room | frigate | binary_sensor.family_room_person_occupancy | living_room (device) | Living Room (common_area) | 62f7b21e... | none; group member |
| camera.family_room_high_resolution_channel | unifiprotect | binary_sensor.family_room_person_detected | living_room (device) | Living Room | 62f7b21e... (twin) | none; same group |
| camera.master_hallway (+ _high_resolution_channel) | frigate / protect | binary_sensor.master_hallway_person_occupancy / _detected | master_hallway (device) | Master Hallway (hallway) | 01dfad50... | none |
| camera.foyer_fisheye (+ _high_resolution_channel) | frigate / protect | binary_sensor.foyer_fisheye_person_occupancy / _detected | foyer (device) | Foyer (hallway) | f095ee1a... | none |
| camera.stairs_top_2 (+ stairs_top_high_resolution_channel) | frigate / protect | binary_sensor.stairs_top_person_occupancy / _detected | stairs (device) | Staircase (hallway) | 74f1d0a0... | none |
| camera.upstairs_hall_high_resolution_channel | protect | binary_sensor.upstairs_hall_person_detected | upstairs_hallway (device) | Upstairs Hallway (hallway) | b063bbf5... (paired with b75c48d2...) | none |
| camera.staircase_high_resolution_channel | protect | binary_sensor.camera_protect_garagehallway_person_detected | garage_hallway (device) | Garage Hallway (hallway) | 43f04c97... (single, no twin) | none |

Result: 7 groups = Master Hallway, Game Room, Garage Hallway, Living Room, Staircase, Upstairs Hallway, Foyer. This matches the observed sensor. `groups_sharing_room`: 0 (each room has exactly one group because the Frigate and Protect devices pair as twins). `no_room`: 0. `excluded_room_type`: 0. `no_camera_device`: 0.

Falsifier checked: if Playroom/Family Room were truly dropped, the groups would have areas with no URA room or a bedroom/bathroom type. They do not (game_room and living_room both map to common_area rooms).

## Verdict

| missing room | verdict | note |
|---|---|---|
| Playroom (+ high-res) | expected by design, not actually missing | Camera is in HA area `game_room`, which is URA room Game Room. Covered. Playroom is not a URA room. |
| Family Room (+ high-res) | expected by design, not actually missing | Camera is in HA area `living_room`, which is URA room Living Room. Covered. Family Room is not a URA room. |

Not "groups_sharing_room": the Frigate and Protect devices of each camera pair into ONE group via the twin rule, so the room is covered by a single group, not displaced by a second one. (Had the twin rule been off, the second group would have been counted as `groups_sharing_room`, but the room would still have a record.)

## Side observations (not defects in scope)

- Naming trap: `camera.staircase_high_resolution_channel` is the Protect garage-hallway camera (its person sensor is `..._garagehallway_person_detected`, device area `garage_hallway`), so it feeds Garage Hallway, not Staircase. The Staircase record comes from the `stairs_top` cameras. Config is correct; the name is misleading.
- Upstairs Hallway: the Protect camera pairs with device b75c48d2..., which is not in the configured list (a Frigate twin not itself listed). Not a problem for coverage.
- Config-gap note: nothing to change. If the operator wants the display label to read "Playroom" or "Family Room", that is a room/area naming change, not a coverage setting.
