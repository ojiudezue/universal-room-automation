# AUDIT v5.108.25 watched set (Wr=3 / U=14) - 2026-11-15 (CST ~14:30)

Read-only. Repro script: `.claude/tmp/wr_repro_v108_25.py` (reads the Samba-mounted `.storage`, registry files mtime 14:21 CST; no token, no HA calls).
Did NOT read the STATE_OF_PLAY docs completely (topic is a stream-health owner, not HVAC/presence tuning); verdict rests on code + registry.

## Verdict: PLAN-COUNT-WRONG in effect, with a latent pre-existing BUG underneath. Nothing is unwatched.

## 1. Wr (3 devices) - real reason
Wr = {Kitchen Panel, Up Hallway Panel, Study a Panel} = the 3 configured `*_panel_person_occupancy` room inputs (offline reproduction: 3 configured camera-device inputs across all room entries; extras contribute 0).
Extras are empty because of the camera manager's area map, not the helper:
- `camera_census.py:1259` `get_person_sensor_for_area` -> `get_cameras_for_area` -> `_cameras_by_area`, built at `camera_census.py:1203-1205` from `resolve_camera_entity`, which sets `area_id=bs_entity.area_id or camera_entry.area_id` (`camera_census.py` ~:660). That is ENTITY-level area only; no device-area fallback.
- Live registry: every one of the 28 person binary_sensors / camera entities on the configured camera lists has `area_id: null` (area lives on the DEVICE, e.g. Master Hallway device area master_hallway, Foyer Fisheye device area foyer). So all 28 land under key `""`; `amap` = `{"": 28}`; no room's `area_id` ever matches. Emulated `rooms with extras = {}`.
- Same result in the pre-foyer-move backup (`core.entity_registry.bak-20261115-foyer`): only 6 unrelated entities carry an entity area. So the foyer move changed nothing here.
- `room_stream_input_entities` (`camera_stream_health.py:934-969`) and `camera_device_for_entity` (:731) behave as designed; `is_room_entry` (:926) is fine. Room tracker uses the same helper (`coordinator.py:2623`, :2857), so rooms also watch only the 3 panels.

## 2. U (14) - reproduced exactly (emulated count 14)
Census interior (12 person sensors on camera devices) + zone cameras, minus Wr (none overlap):
camera_protect_garagehallway_person_detected, family_room_person_detected, family_room_person_occupancy, foyer_fisheye_person_detected, foyer_fisheye_person_occupancy, master_hallway_person_detected, master_hallway_person_occupancy, playroom_person_detected, playroom_person_occupancy_2, stairs_top_person_detected, stairs_top_person_occupancy, upstairs_hall_person_detected, plus zone-only: staircase_person_occupancy, upstairs_hall_person_occupancy_2. (Zone `binary_sensor.garage_a_camera_person_detected` has no device with a camera, so is excluded.)
The foyer is NOT in Wr (device area foyer, entity area null; the Foyer room has no camera inputs). It is in U with everything else.

## 3. Behaviour
- Producer/consumer: plan's §6.2 premise ("room override sensors are watched by rooms") is false in production. `get_person_sensor_for_area(room_area)` has returned [] since the registry has no entity-level areas, so the v3.5.1 room camera override (`coordinator.py:2623` extra_inputs) is itself inert, as is `sensor.py:2837` has_camera and zone `_discover_zone_cameras` (`presence.py:5240`) by area. That is pre-existing, not a 3b regression (I did not verify historic override firing; unknown).
- INV-DEAD-INPUT / INV-DEAD-CAMERA hold as code: every census/zone camera is in U, so the owner's house tracker (`camera_twin_health.py:569-584`, `house_tracker_for`) answers for them; all knobs are True (`const.py:6045,6089,6094,6107`). `_scope_groups` (:668-683) includes all those groups. No camera is watched by nobody among census/zone readers.
- Difference vs plan: house tracker (not rooms) carries 14 entities, i.e. the "named changes" (10 multi-camera override sensors, 7 Protect census entries) are applied via U only; paging for these groups comes from the owner only (no room S1/S2), page_counts 0 so far.
- Plan expected-but-not-true: garage_a, garage_b, doorbell_lite, camera_protect_garagehallway-as-override, reolink patio sensors were counted as room-watched override candidates; they are now in neither Wr nor U unless census/zone-listed. garage_a/b/doorbell_lite/reolink are egress/perimeter-only. I did not verify any consumer reads stream-health for them (grep of `camera_stream_dead` readers shows only coordinator.py, sensor.py, camera_stream_health.py); before 3b nobody watched them either, so no regression, but the plan's "Wr includes garage_a/garage_b" claim is false.
- Does any group page that the plan said would not, or reverse: not observable yet (0 pages). In scope, the plan's U=foyer-only meant the 11 other interior groups would page via room S1; now owner pages them. Plan's reverse (rooms suppress via owner) is moot since rooms watch none.

## 4. The plan's probe
`.claude/tmp/rev35_probe.py` approximates override candidates by `area_of(eid)` = entity area, else DEVICE area (probe lines "def area_of"), giving 23 candidates. Code uses entity-only area. That divergence is the entire discrepancy; the probe also never computed Wr via `camera_device_for_entity` + the real manager map.

## Fix (not applied)
Either (a) make `resolve_camera_entity` (`camera_census.py` ~:660) use `resolve_area_id_for_entity(ent_reg, dev_reg, bs_id)` (entity -> device area; helper already exists in `camera_resolver.py`, used at camera_census.py ~:905), which also revives the room override, has_camera and zone area discovery: a behaviour change touching presence, so Tier 2-DB and a separate card; or (b) accept the plan-count error, correct the README/plan numbers (Wr=3, U=14). Do not do (a) inside the 3b validation.
