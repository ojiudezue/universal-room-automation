# PHONE-LEFT-BEHIND-CAMERA-LEG-1 — phone-left-behind shows real person sightings (DRAFT)

Version: TBD at deploy (patch). Branch `feature/phone-left-behind-camera`. Plan
`docs/planning/PLANNING_phone_left_behind_camera_leg.md` rev 2. Operator ruling A (2026-11-13): the
camera leg is DISPLAY ONLY.

## What changed

- **D1 — phone-left-behind attributes.** `binary_sensor.universal_room_automation_<person>_phone_left_behind`
  now shows the person's newest sighting from the person-sighting store
  (`PresenceCoordinator.get_last_person_sighting`), keyed by `person_coordinator.tracked_person_entity_id`:
  `camera_leg: display_only`, `last_camera_sighting_at` (static between sightings), `last_sighting_source`, `last_sighting_camera`, `last_sighting_room`,
  `last_sighting_census_veto`. The verdict (`on` / `off`) is unchanged: step 4 no longer reads a camera
  store and returns what it returned on every live tick before (the old store never held a name).
  The attribute `phone_left_behind_hours` is removed.
- **D2 — likely-next-room.** `sensor.<person>_likely_next_room` `camera_last_seen` / `camera_last_room` /
  `transit_camera_validated` read the same store (window `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` = 4 h).
  The window is applied when the attributes are read, not only at the sensor's update (review B2).
  The sensor is disabled by default.
- **D3 — legacy store.** `TransitValidator` stores every camera sighting as `unidentified`; the named
  branch, `get_last_camera_sighting` and `TRANSIT_PHONE_LEFT_BEHIND_HOURS` are deleted. Path validation
  is unchanged for the only history live data produces.

## Knobs

| Knob | Value | Rung | Off |
|---|---|---|---|
| `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` | 14400 | 1 (const.py) | `<= 0` = never shown |

## Live validation (prospective; replace with a `Validated <date>` table after restart)

| # | Check | Pass looks like | Different failure looks like |
|---|---|---|---|
| L1 | Jaya flag attributes after a family-room face | `last_camera_sighting_at` set, `last_sighting_camera` set, `camera_leg: display_only` on `binary_sensor.universal_room_automation_jaya_phone_left_behind` | null while `sensor.ura_presence_house_state` `face_sighting_last` names Jaya = key or wiring miss |
| L2 | Verdict ignores sightings | at least one `on` row (arrival or restart tick) whose `last_camera_sighting_at` is under 1 h old; if none occurs, in-suite only (`test_fresh_sighting_does_not_change_verdict`) | every `on` row lacks a recent sighting while that person has recent sightings = sightings leaking into the verdict |
| L3 | No recorder churn | between sightings and verdict changes the four flags write no new state rows | a row every 15 min or every ~30 s = a moving attribute is back |
| L4 | Transit path validation unchanged | activity-log `path_method` mix similar to the day before, `path_confirmed` present | `path_confirmed` gone = D3 broke unidentified reads |
| L5 | No URA ERROR at boot or on poll | system_log clean of `binary_sensor` / `transit_validator` / `sensor` errors | |

## Not done / deviations from the plan

- **`hours_since_camera_sighting` dropped (plan M2 deviation; review A-M1 / B1).** The plan put it in
  `_unrecorded_attributes` to stop churn. That set only strips the attribute from the recorded blob; HA still
  writes a state row whenever any attribute changes (`homeassistant/core.py` `same_attr` compare). The first
  build stepped it to 15 min, which still wrote up to 96 rows/day/person, and all four sensors are enabled live
  (about 384 rows/day). The fix-up removes the attribute and its quantum constant;
  `last_camera_sighting_at` (static between sightings) carries the same information. Pinned by
  `test_attributes_static_between_polls_no_age`.
- **Accepted A-L1 (verdict identity holds for every reachable input).** Develop's step 4 differed only for a
  camera entity carrying a `person_id` / `face_id` / `label` attribute equal to the person's title-cased
  display name with face recognition on; measured 0 of 102 person entities, so unreachable in this house. A
  future integration that sets such a label would have flipped develop's verdict; this branch never does.
- **Accepted A-L2.** The verdict oracle in `test_phone_left_behind_camera_leg.py` shares that assumption (it
  forces the legacy leg None), so it cannot catch A-L1. Noted in the test docstring.
- **Review B2 fixed.** NextRoom applies the 4 h window at attribute-read time (one dict get), so an aged
  sighting no longer stays shown until the next update.
- D3 drills on deleting the named read / rule 1 are not meaningful (dead branches with no input); INV-3 is
  covered by the hand-derived golden replay instead.
- `test_pathalpha_d2c_d3_observability.py` and `test_v4714_1_forgotten_phone_hotfix.py` fail to collect on
  develop already (import errors unrelated to this change); their source-grep anchors still match the edited
  class.
