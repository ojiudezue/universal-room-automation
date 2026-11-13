# PHONE-LEFT-BEHIND-CAMERA-LEG-1 — phone-left-behind shows real person sightings (DRAFT)

Version: TBD at deploy (patch). Branch `feature/phone-left-behind-camera`. Plan
`docs/planning/PLANNING_phone_left_behind_camera_leg.md` rev 2. Operator ruling A (2026-11-13): the
camera leg is DISPLAY ONLY.

## What changed

- **D1 — phone-left-behind attributes.** `binary_sensor.universal_room_automation_<person>_phone_left_behind`
  now shows the person's newest sighting from the person-sighting store
  (`PresenceCoordinator.get_last_person_sighting`), keyed by `person_coordinator.tracked_person_entity_id`:
  `camera_leg: display_only`, `last_camera_sighting_at`, `hours_since_camera_sighting` (stepped to 15 min,
  unrecorded), `last_sighting_source`, `last_sighting_camera`, `last_sighting_room`,
  `last_sighting_census_veto`. The verdict (`on` / `off`) is unchanged: step 4 no longer reads a camera
  store and returns what it returned on every live tick before (the old store never held a name).
  The attribute `phone_left_behind_hours` is removed.
- **D2 — likely-next-room.** `sensor.<person>_likely_next_room` `camera_last_seen` / `camera_last_room` /
  `transit_camera_validated` read the same store (window `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` = 4 h).
  The sensor is disabled by default.
- **D3 — legacy store.** `TransitValidator` stores every camera sighting as `unidentified`; the named
  branch, `get_last_camera_sighting` and `TRANSIT_PHONE_LEFT_BEHIND_HOURS` are deleted. Path validation
  is unchanged for the only history live data produces.

## Knobs

| Knob | Value | Rung | Off |
|---|---|---|---|
| `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` | 14400 | 1 (const.py) | `<= 0` = never shown |
| `PHONE_LEFT_BEHIND_SIGHTING_AGE_QUANTUM_S` | 900 | 1 (const.py) | `<= 0` = unstepped (a state row per poll) |

## Live validation (prospective; replace with a `Validated <date>` table after restart)

| # | Check | Pass looks like | Different failure looks like |
|---|---|---|---|
| L1 | Jaya flag attributes after a family-room face | `last_camera_sighting_at` set, `last_sighting_camera` set, `camera_leg: display_only` on `binary_sensor.universal_room_automation_jaya_phone_left_behind` | null while `sensor.ura_presence_house_state` `face_sighting_last` names Jaya = key or wiring miss |
| L2 | Verdict ignores sightings | at least one `on` row (arrival or restart tick) whose `last_camera_sighting_at` is under 1 h old; if none occurs, in-suite only (`test_fresh_sighting_does_not_change_verdict`) | every `on` row lacks a recent sighting while that person has recent sightings = sightings leaking into the verdict |
| L3 | No recorder churn | state rows for the four flags grow at most once per 15 min per person between sightings | a row every ~30 s = the stepped age is not stepped |
| L4 | Transit path validation unchanged | activity-log `path_method` mix similar to the day before, `path_confirmed` present | `path_confirmed` gone = D3 broke unidentified reads |
| L5 | No URA ERROR at boot or on poll | system_log clean of `binary_sensor` / `transit_validator` / `sensor` errors | |

## Not done / deviations from the plan

- **M2 mechanism corrected.** The plan put `hours_since_camera_sighting` in `_unrecorded_attributes` to stop
  churn. That set only strips the attribute from the recorded blob; HA still writes a state row whenever any
  attribute changes (`homeassistant/core.py` `same_attr` compare; same note at `binary_sensor.py` HVAC
  Occupied). The value is therefore also stepped to a 900 s quantum (new rung-1 constant), and kept in the
  unrecorded set as the plan asked.
- D3 drills on deleting the named read / rule 1 are not meaningful (dead branches with no input); INV-3 is
  covered by the hand-derived golden replay instead.
- `test_pathalpha_d2c_d3_observability.py` and `test_v4714_1_forgotten_phone_hotfix.py` fail to collect on
  develop already (import errors unrelated to this change); their source-grep anchors still match the edited
  class.
