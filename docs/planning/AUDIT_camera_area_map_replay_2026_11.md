# AUDIT: camera area map replay (D0 of ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1)

Date 2026-11-15 (probe run 16:49 CST; the host and the house are on CST, UTC-6, since DST ended 2026-11-01, so every time
below is CST). Author ura-prober, read-only. Plan: `docs/planning/PLANNING_camera_area_map_device_fallback.md` rev 2
(aca84b15 on develop). Probe: `scripts/probes/camera_area_map_replay.py`.

Read before writing, completely: the plan (D0 (a)-(h), §7 gates, §8 Q list), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`
(all 1,149 lines), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/planning/AUDIT_v5_108_25_watched_set_2026_11_15.md`. The
HVAC state-of-play doc was read for §1-§3 only (the HVAC-extra columns in (c) use its §3.1 hold tables); the rest of that doc was
not read and nothing here asserts HVAC behaviour beyond those tables.

## How it was run, and what was touched

- `ssh ha python3 - < scripts/probes/camera_area_map_replay.py`, on the HA host. It reads `/config/.storage/core.{entity,device,area}_registry`
  and `core.config_entries` (only the integration option keys `camera_person_entities`, `egress_cameras`, `perimeter_cameras`,
  `census_*`, `tracked_persons`, and room / zone structure are used; nothing from config-entry data is printed), the recorder DB
  (`file:...?mode=ro`) and the URA DB (`mode=ro`). No HA service call, no write, no Bermuda diagnostics.
- Six read-only REST GETs with the keychain token (captured in a shell variable, never printed) to confirm live state at
  16:5x CST: `sensor.zone_{entertainment,upstairs,master_suite,back_hallway}_presence_status` all read `cameras = {}` and
  `signal_tiers.camera_sensors = false`; `sensor.universal_room_automation_persons_in_house` attributes
  `area_raw_max_pre_cancel = {}` and `stuck_cameras = []`; house state `away` since 2026-11-15 15:47:30 CST (21:47:30 UTC).
  These agree with the recorder-derived picture (the camera tier and the census per-area terms are inert today).
- Window: the last 7 days, 11-08 16:49 to 11-15 16:49 CST (the recorder starts 11-08 04:12 CST). Census samples = the 7,514
  `census_snapshots` rows (`zone='house'`) in the window, one every ~80 s on average, so one sample is about 1.3 minutes.
- Q6 was answered after the first commit: 11-14 high-water mark **14 to 15 people**, no time; census peak 10 at 16:26 and 16:43; busy about 16:00-19:00. It is evaluated as oracle (4) in (d) ("Oracle (4)" table).

## Verdicts (the answer first)

| Question | Verdict | Evidence (details in the sections below) |
|---|---|---|
| Probe matches the code? | **YES**. Old rule reproduces **Wr 3 / U 14** exactly; today's `unidentified_count` replays equal to the recorded rows on **7,495 / 7,514 samples = 99.75%** (gate >= 99%) | (a) self-check; (d) self-check. On the 787 samples where either side is > 0 the match is 768 / 787 = 97.6%; the raw Frigate / binary dedup totals match the recorded `frigate_count` / `unifi_count` on 99.99% / 100.00% |
| KEEP/CORRECT census gate (zero contradicted minutes on sources 1-3) | **FAILS, narrowly: 1 contradicted sample (11-12 09:54:26 CST, about 1.3 min) of the 6 samples where D4-CORRECT would read 0 while today reads > 0; (ii) per-area max contributes 0 crossings, 0 contradicted.** The plan's rule is threshold 0, no tolerance, so the plan outcome is **D4-KEEP** | (d) contradicted-zero table. The one contradicted sample is flagged only by oracle (2) because **Ezinne's own door entry** sat in the prior 2 h; she is the resident BLE-located in the Living Room whose body the cancel removed. Under a refinement (an entry explained by the resident who is BLE-located in the camera area does not count) contradicted = 0, but that refinement is not the plan's rule and is reported separately, not used for the verdict |
| Q6 / 11-14 party peak under every semantics (truth 14-15) | **Every semantics peaks at 10: recorded 10, today replayed 10, (ii) 10, (iii) CORRECT 10, (iv) 10, raw camera total 10 in all four. Each is 4 below 14 and 5 below 15.** Today already undercounts by 4-5; CORRECT does not widen the gap at the peak (peak equal), and lowers the person total on only 1 of 151 samples in 16:00-19:00 | (d) Oracle (4) table. So the feared extra loss on a real crowd is not observed, and neither is any gain from removing double counts on that day. Gate with oracle (4): the sole contradicted sample on sources 1-3 stands, no new contradiction from the crowd; verdict stays **D4-KEEP** |
| Is D4-CORRECT worth taking even if the gate passed? | **No (marginal-benefit decomposition).** Per-area max changes nothing on this house; BLE cancel changes `unidentified_count` on 9 of 7,514 samples in 7 days (8 lower, 1 higher through hold/decay path dependence), 6 of them crossing to 0, all Living Room / Ezinne | (d) variant table. The camera body total never changes (delta 0 on all 7,514 samples) |
| INV-CENSUS-DOWN (plan D0 discriminating criterion) | **Holds as stated over an evidence state: 0 violations in 155,980 evaluation instants for (ii) and (iii), for both `camera_unrecognized` and the raw camera total.** The plan's literal criterion "ANY sample with after > before" **is tripped by 1 sample** through the stateful hold/decay machine: 11-12 10:31:26, variant (iii) reads 2 where today reads 1 | (d). Mechanism: today's raw reading rose to 3 and reset the 15 s sustain timer, so `_apply_hold_decay` kept the lower peak (1); the variant's smaller reading (2) sustained and promoted sooner. The variant counts fewer bodies (2 vs 3) at that instant; the output is higher only through the hold path. Under the literal criterion this says "stop and re-plan D4", which is consistent with the KEEP outcome |
| Per-room hold recommendation under Q1 | **No room qualifies on ship day: recommended ON = none** | (c) Q1 table. Every camera room has 53% to 100% of its would-be-created minutes unsupported (no BLE person in the room and no Tier-1 sensor on within +-120 s), or created < 30 min, or an exterior-role camera, or is muted. The rule's thresholds are the probe's (stated in the report) because the plan gives none |
| Q5: does the zone tier move WAKING? | **No movement in 7 mornings.** All 7 SLEEP -> WAKING edges fired 06:00:14 to 06:00:52 CST (11-09 06:00:20, 11-10 06:00:24, 11-11 06:00:15, 11-12 06:00:49, 11-13 06:00:14, 11-14 06:00:52, 11-15 06:00:17). Non-camera raw occupancy is already sustained at 06:00 because the sleepers hold their rooms, so the 90 s sustained gate is not the limiter; the 06:00 sleep-hour gate is. The camera tier cannot move WAKING earlier than that clock gate | (e) WAKING table. SLEEP held only by a camera limb: **0 min house-wide** (decisive for nobody-home / path beta); per zone (display and HVAC night tail only): Entertainment 69.5 min over 3 nights (11-09 0.7, 11-13 33.9, 11-14 34.9), Master Suite 21.2 min, Back Hallway 6.1 min, Upstairs 0.0 min |
| Family Room patio through glass | **Family-room camera person on, or count > 0: 3,255.6 min in 7 days. With the Living Room's three Tier-1 sensors quiet and no BLE person in the room: 1,694.6 min (1,493.8 min while the sun was up, 200.9 min dark). Of those, with the room itself reading vacant (what a hold would CREATE): 1,080.2 min. While the house was AWAY: 2.0 min** | (f). Most of it lands in home_day (1,468.2 min) |

## Surprises (read these)

1. **Exterior cameras reach rooms through the full map.** The area map is not role-filtered; only the plan's zone tier is (D3a'). After D1:
   Garage A gets `doorbell_lite_person_occupancy_2` (egress) and `garage_a_person_occupancy_2` (egress), Garage B gets
   `garage_b_person_occupancy` (perimeter), the Patio room gets `reolinkstudybporchptz_person_occupancy_2` (perimeter). They are in the room
   hold lookup, in each room's stream-health watch set, and take **Wr from 3 to 19 devices** (4 of them exterior). Garage A's would-be hold
   created 86.8 min in 7 days, 88% unsupported, **58.7 min of it while the house was AWAY**. D2's default-off gate protects the hold; it does
   not stop new room S1/S2 pages for four exterior camera devices. Recommend a role filter on the room lookup too, or never opting Garage A / B / Patio in.
2. **Per-area max has zero effect on this house.** No area holds two distinct physical interior cameras (the Frigate + Protect pair of one camera
   collapses; each area has one physical camera), so D4's per-area max is inert here and the hidden-second-person table is empty. The only census
   term that acts is BLE cancel (9 samples).
3. **D3c is needed, with data.** Without it the camera tier would have delayed 3 of the 8 nobody-home AWAY edges (157 s, 170 s, 284 s), all held
   by `family_room_person_occupancy`. Path alpha is immune by construction (it reads no zone), yet the camera tier was occupied at 7 of the 10 alpha
   edges, in runs of 243 s up to 19,607 s (5.4 h; 11-12 07:34, the family-room camera `on` for hours with the room quiet).
4. **Four camera-tier runs started while the house was AWAY** (counterfactual ARRIVING): 3 were followed by a real arrival within 10 min (11-12 16:43,
   11-13 17:04, 11-13 17:18) and 1 was a phantom (11-09 18:03, 305 s). D3c keeps these at zero by design.
5. **The stuck-camera discount is a real hazard, and it never touches `unidentified_count`.** 33 `camera_stuck` NMs exist since 08-23, **0 inside the
   window** (latest 10-30 03:00 CST). Under the NEW area 15 of the 33 would have discounted (9 `master_hallway_person_occupancy`, 6
   `family_room_person_occupancy`), 8 of them in `sleep` / `home_night`. The discount feeds only the raw camera total (`camera_census.py:2105`).
6. **Camera person edges are loud.** Registered interior cameras would fire `_run_inference("camera_detection")` 429 to 3,918 times per day
   (11-14, the party, is 3,918; 11-13 is 2,372).
7. Garage Hallway and Staircase rooms have their Automation switch OFF live (`switch.garage_hallway_automation`, `switch.staircase_automation`); a
   hold there would still create occupancy and stamp HVAC evidence without actuating lights. Garage Hallway is also muted (`disable_camera_presence`).

## Model limits (so nothing here is over-read)

- The identified-people term of the census clamp is taken from the recorded `census_snapshots.identified_count` (and
  `sensor.universal_room_automation_identified_persons_in_house` between rows); BLE / face / egress-face identity is not replayed.
- BLE-by-area uses the recorded `sensor.universal_room_automation_<p>_location`; the recorder does not hold `tracking_status`, so the
  STALE / LOST exclusion of `_ble_home_by_area` is not modelled (it can only make the cancel slightly more permissive in the replay).
- Non-camera zone occupancy uses the recorded room `binary_sensor.<room>_occupied` plus BLE-in-zone; calibration against the recorded
  zone mode is 85% to 99% coverage (table in (e)).
- W1 twin collapse is re-implemented as device area + device name + NVR-platform admissibility (`frigate_object_name_pairs` cannot be imported on
  the host). It only matters for the hidden-second-person table, which is empty either way.
- The census hold/decay machine is replayed at every input change plus a 5 s grid and at each row's exact timestamp.
- In (c) the extra-hold upper bound adds the room timeout after each camera-held stretch; the code block itself does not refresh `_last_motion_time`,
  so the lower bound is the created minutes alone. The Q1 thresholds (>= 30 created min, <= 10% unsupported) are the probe's, not the plan's.
- (h) uses the URA DB (`person_visits`, `environmental_data`) for the 33 historical NMs because the recorder window holds none; that is a weaker
  oracle than BLE + room sensors at the instant.

## Falsifiers run

| Claim | Observation that would disprove it | Result |
|---|---|---|
| Probe reproduces production | Wr / U old != 3 / 14, or today's replay < 99% | 3 / 14 and 99.75%: not disproved |
| Camera tier and per-area terms are inert today | live zone `cameras != {}` or `area_raw_max_pre_cancel != {}` | both empty at 16:5x CST: not disproved |
| INV-CENSUS-DOWN over evidence states | any instant with variant `camera_unrecognized` or camera total above today's | 0 of 155,980: not disproved. The stateful sample is the one named above |
| WAKING is clock-gated | any morning where the actual edge is later than 06:01 or the non-camera model is not sustained at 06:00 | 7 of 7 mornings within 06:00:14 to 06:00:52: not disproved |
| Per-area max is inert | an area with two physical interior cameras | none: not disproved |

---

## (a) The rebuilt map

Window: 11-08 16:51 to 11-15 16:51 CST (7 days; recorder holds 11-08 04:12 onward). Probe run 11-15 16:51:41. Rule: `old` = `bs_entity.area_id or camera_entry.area_id` (`camera_census.py:680`); `new` = `resolve_area_id_for_entity(bs) or resolve_area_id_for_entity(camera)` (`camera_resolver.py:474`, entity area else device area).

Configured lists (integration entry): interior `camera_person_entities` = 12, `egress_cameras` = 4, `perimeter_cameras` = 12 camera.* entities. Roles below are resolved per registry DEVICE of each configured camera.* entity; no name is used.

### Self-check: the old rule must reproduce Wr 3 / U 14 (`AUDIT_v5_108_25_watched_set_2026_11_15.md`)

- Old-rule area map keys: `{"''": 28}` (audit: `{'': 28}`).
- Rooms with camera extras under the old rule: 0.
- **Wr (old rule) = 3, U (old rule) = 14** -> PASS (3 / 14)
- Wr devices (old): Kitchen Panel, Study a Panel, Up Hallway Panel
- U entities (old, 14): camera_protect_garagehallway_person_detected, family_room_person_detected, family_room_person_occupancy, foyer_fisheye_person_detected, foyer_fisheye_person_occupancy, master_hallway_person_detected, master_hallway_person_occupancy, playroom_person_detected, playroom_person_occupancy_2, staircase_person_occupancy, stairs_top_person_detected, stairs_top_person_occupancy, upstairs_hall_person_detected, upstairs_hall_person_occupancy_2

### Per-camera table (every person sensor reached by the configured lists)

| person sensor | platform | role | device | entity area | device area | OLD area | NEW area | URA room on NEW area | zone | room Automation switch (live) | disable_camera_presence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `doorbell_lite_person_occupancy_2` | frigate | egress | Doorbell Lite | - | Garage A | - | Garage A | Garage A | - | Garage A=on | Garage A:ok |
| `front_door_aerial_person_occupancy_2` | frigate | egress | Front Door Aerial | - | Front Porch | - | Front Porch | - | - | - | - |
| `garage_a_person_occupancy_2` | frigate | egress | Garage A | - | Garage A | - | Garage A | Garage A | - | Garage A=on | Garage A:ok |
| `madrone_g6_entry_person_occupancy_2` | frigate | egress | Madrone G6 Entry | - | Front Porch | - | Front Porch | - | - | - | - |
| `camera_protect_garagehallway_person_detected` | unifiprotect | interior | Camera_Protect_GarageHallway | - | Garage Hallway | - | Garage Hallway | Garage Hallway | Back Hallway | Garage Hallway=on | Garage Hallway:mute |
| `family_room_person_detected` | unifiprotect | interior | Family Room | - | Living Room | - | Living Room | Living Room | Entertainment | Living Room=on | Living Room:ok |
| `family_room_person_occupancy` | frigate | interior | Family Room | - | Living Room | - | Living Room | Living Room | Entertainment | Living Room=on | Living Room:ok |
| `foyer_fisheye_person_detected` | unifiprotect | interior | Foyer Fisheye | - | Foyer | - | Foyer | Foyer | Entertainment | Foyer=on | Foyer:ok |
| `foyer_fisheye_person_occupancy` | frigate | interior | Foyer Fisheye | - | Foyer | - | Foyer | Foyer | Entertainment | Foyer=on | Foyer:ok |
| `master_hallway_person_detected` | unifiprotect | interior | Master Hallway | - | Master Hallway | - | Master Hallway | Master Hallway | Master Suite | Master Hallway=on | Master Hallway:ok |
| `master_hallway_person_occupancy` | frigate | interior | Master Hallway | - | Master Hallway | - | Master Hallway | Master Hallway | Master Suite | Master Hallway=on | Master Hallway:ok |
| `playroom_person_detected` | unifiprotect | interior | Playroom | - | Game Room | - | Game Room | Game Room | Upstairs | Game Room=on | Game Room:ok |
| `playroom_person_occupancy_2` | frigate | interior | Playroom | - | Game Room | - | Game Room | Game Room | Upstairs | Game Room=on | Game Room:ok |
| `stairs_top_person_detected` | unifiprotect | interior | Stairs - top | - | Stairs | - | Stairs | Staircase | Back Hallway | Staircase=on | Staircase:ok |
| `stairs_top_person_occupancy` | frigate | interior | Stairs Top | - | Stairs | - | Stairs | Staircase | Back Hallway | Staircase=on | Staircase:ok |
| `upstairs_hall_person_detected` | unifiprotect | interior | Upstairs Hall | - | Upstairs Hallway | - | Upstairs Hallway | Upstairs Hallway | Upstairs | Upstairs Hallway=on | Upstairs Hallway:ok |
| `armcrest_person_occupancy_2` | frigate | perimeter | ArmCrest | - | Pool | - | Pool | - | - | - | - |
| `back_yard_person_occupancy_2` | frigate | perimeter | Back Yard | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |
| `front_side_ptz_person_occupancy_2` | frigate | perimeter | Front Side PTZ | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |
| `g5_bullet_person_occupancy_2` | frigate | perimeter | G5 Bullet | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |
| `garage_b_person_occupancy` | frigate | perimeter | Garage B | - | Garage B | - | Garage B | Garage B | - | Garage B=on | Garage B:ok |
| `hot_tub_person_occupancy_2` | frigate | perimeter | Hot Tub | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |
| `madroneptultra_person_occupancy` | frigate | perimeter | MadronePTUltra | - | - | - | - | - | - | - | - |
| `pool_equipment_person_occupancy_2` | frigate | perimeter | Pool Equipment | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |
| `rear_ptz_person_detected` | unifiprotect | perimeter | Rear PTZ | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |
| `reolinkstudybporchptz_person_occupancy_2` | frigate | perimeter | ReolinkStudyBPorchPTZ | - | Patio | - | Patio | Patio | Outside | Patio=on | Patio:ok |
| `sonoffwindow_person_occupancy` | frigate | perimeter | SonoffWindow | - | - | - | - | - | - | - | - |
| `utilities_ptz_person_detected` | unifiprotect | perimeter | Utilities PTZ | - | Outside Perimeter | - | Outside Perimeter | - | - | - | - |

Full-scan output (no lists configured; `camera_census.py:1130-1200`): 556 sensors (every `frigate`-platform binary sensor plus name-suffix matches, so it includes non-person Frigate sensors); area keys by ENTITY area only: {"''": 552, 'receiving_room': 1, 'master_bedroom': 1, 'game_room': 1, 'ziri_bedroom': 1}. Under the NEW rule full-scan would still read entity area only (the plan changes `:1163/:1191` to the resolver, which would key them by device area; not live because lists are configured).

Legacy cross-platform fire-axe path (`:975-1030`, taken only when `CENSUS_USE_NEW_RESOLVER` is False): 46 sibling entities found, areas (entity area or the base info's area) = {"''": 46}; the live path `:919` uses `resolve_area_id_for_entity` already and so equals the NEW column for any entity it returns.

NEW map: 26 person sensors keyed under 13 real areas, 2 under `''` (device without area).

Cameras whose NEW area has **no URA room** (the room hold and the zone tier never see them; they only change the census area key and Wr/U): `madrone_g6_entry_person_occupancy_2` (Front Porch), `front_door_aerial_person_occupancy_2` (Front Porch), `rear_ptz_person_detected` (Outside Perimeter), `utilities_ptz_person_detected` (Outside Perimeter), `front_side_ptz_person_occupancy_2` (Outside Perimeter), `armcrest_person_occupancy_2` (Pool), `hot_tub_person_occupancy_2` (Outside Perimeter), `pool_equipment_person_occupancy_2` (Outside Perimeter), `g5_bullet_person_occupancy_2` (Outside Perimeter), `back_yard_person_occupancy_2` (Outside Perimeter), `madroneptultra_person_occupancy` (-), `sonoffwindow_person_occupancy` (-).

## (b) Zones that gain cameras, with roles

Zone camera tier = `presence._discover_zone_cameras` (`presence.py:5192`): area -> zone via the room's `CONF_AREA_ID`, rooms with `disable_camera_presence` skipped. Plan D3a' admits only cameras whose configured `camera.*` device is on the interior list and on neither egress nor perimeter. Role = union of the lists the device's configured camera.* entities are on.

| zone | person sensor | device | device area (mount) | room | role | admitted by D3a' |
|---|---|---|---|---|---|---|
| Back Hallway | `stairs_top_person_detected` | Stairs - top | Stairs | Staircase | interior | **YES** |
| Back Hallway | `stairs_top_person_occupancy` | Stairs Top | Stairs | Staircase | interior | **YES** |
| Entertainment | `family_room_person_occupancy` | Family Room | Living Room | Living Room | interior | **YES** |
| Entertainment | `family_room_person_detected` | Family Room | Living Room | Living Room | interior | **YES** |
| Entertainment | `foyer_fisheye_person_occupancy` | Foyer Fisheye | Foyer | Foyer | interior | **YES** |
| Entertainment | `foyer_fisheye_person_detected` | Foyer Fisheye | Foyer | Foyer | interior | **YES** |
| Master Suite | `master_hallway_person_occupancy` | Master Hallway | Master Hallway | Master Hallway | interior | **YES** |
| Master Suite | `master_hallway_person_detected` | Master Hallway | Master Hallway | Master Hallway | interior | **YES** |
| Outside | `reolinkstudybporchptz_person_occupancy_2` | ReolinkStudyBPorchPTZ | Patio | Patio | perimeter | no (role) |
| Upstairs | `playroom_person_detected` | Playroom | Game Room | Game Room | interior | **YES** |
| Upstairs | `playroom_person_occupancy_2` | Playroom | Game Room | Game Room | interior | **YES** |
| Upstairs | `upstairs_hall_person_detected` | Upstairs Hall | Upstairs Hallway | Upstairs Hallway | interior | **YES** |

Zone tier registrations: old rule 0; new rule without role filter 12; new rule with D3a' 11 (boot INFO "Subscribed to N zone camera entities" should read 11).

Egress/perimeter cameras the role filter keeps OUT of the zone tier (they still enter the room hold lookup and Wr, because `get_person_sensor_for_area` reads the full map): `reolinkstudybporchptz_person_occupancy_2` (perimeter, Patio).

Rooms on a camera area that are opted out (`disable_camera_presence` True): Garage Hallway.

## (c) 7-day room-hold replay

Model (code: `coordinator.py:4491`): the v3.5.1 block runs when the room reads vacant and a camera person sensor in the room's area reads `on`; it sets occupied, `occupancy_source=camera`, and stamps HVAC evidence. Base occupancy = the recorded `binary_sensor.<room>_occupied` (no camera sensor is in any room's extras today, so it IS the no-camera room). **Created minutes** = camera `on` while the room reads vacant. **Extra hold (upper bound)** adds the room's occupancy timeout after each camera-held stretch ends (the plan's "+ room occupancy timeout"; the code block itself does not refresh `_last_motion_time`, so the lower bound is the created minutes alone). **HVAC extra** = minutes `hvac_occupied` would be added using the room-type evidence hold (`const.py:1788` day table in home_day/evening, night table in sleep/waking, legacy tail elsewhere; hallways 0). "Supported" = a BLE person located in that room or a configured Tier-1 sensor on within +-120 s; unsupported minutes are the leak.

Entities resolved per camera room by registry unique_id (`<entry_id>_occupied`, `_automation`, `hvac_occupied`): Living Room: `living_room_occupied` / `living_room_living_room_hvac_occupied` / `living_room_automation`; Patio: `patio_occupied` / `patio_patio_hvac_occupied` / `patio_automation`; Garage A: `garage_a_occupied` / `garage_a_garage_a_hvac_occupied` / `garage_a_automation`; Game Room: `game_room_occupied` / `game_room_game_room_hvac_occupied` / `game_room_automation`; Garage Hallway: `garage_hallway_occupied` / `garage_hallway_garage_hallway_hvac_occupied` / `garage_hallway_automation`; Garage B: `garage_b_occupied` / `garage_b_garage_b_hvac_occupied` / `garage_b_automation`; Upstairs Hallway: `upstairs_hallway_occupied` / `upstairs_hallway_upstairs_hallway_hvac_occupied` / `upstairs_hallway_automation`; Master Hallway: `master_hallway_master_hallway_occupied` / `master_hallway_master_hallway_hvac_occupied` / `master_hallway_automation`; Foyer: `foyer_foyer_occupied` / `foyer_foyer_hvac_occupied` / `foyer_automation`; Staircase: `staircase_occupied` / `staircase_hvac_occupied` / `staircase_automation`

| room | camera sensors in its area | zone | type | camera presence | camera-on min | created min | episodes | extra hold min (upper, +timeout tail) | HVAC extra occupied min | unsupported created min | unsupported % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Living Room | `family_room_person_occupancy`, `family_room_person_detected` | Entertainment | common_area | ok | 3255.4 | 1123.5 | 184 | 158.1 | 1351.0 | 966.1 | 86% |
| Game Room | `playroom_person_detected`, `playroom_person_occupancy_2` | Upstairs | common_area | ok | 261.6 | 114.4 | 83 | 77.4 | 199.2 | 61.0 | 53% |
| Garage A | `doorbell_lite_person_occupancy_2`, `garage_a_person_occupancy_2` | - | garage | ok | 151.8 | 86.8 | 74 | 216.8 | 183.8 | 76.0 | 88% |
| Patio | `reolinkstudybporchptz_person_occupancy_2` | Outside | common_area | ok | 3.7 | 0.8 | 4 | 6.5 | 11.1 | 0.3 | 31% |
| Garage B | `garage_b_person_occupancy` | - | garage | ok | 1.1 | 0.9 | 3 | 15.0 | 5.9 | 0.9 | 100% |
| Garage Hallway | `camera_protect_garagehallway_person_detected` | Back Hallway | hallway | mute | 164.2 | 38.2 | 187 | 350.6 | 0.0 | 25.6 | 67% |
| Upstairs Hallway | `upstairs_hall_person_detected` | Upstairs | hallway | ok | 44.3 | 0.1 | 8 | 0.0 | 0.0 | 0.0 | 0% |
| Master Hallway | `master_hallway_person_occupancy`, `master_hallway_person_detected` | Master Suite | hallway | ok | 458.7 | 180.8 | 452 | 553.5 | 0.0 | 138.7 | 77% |
| Foyer | `foyer_fisheye_person_occupancy`, `foyer_fisheye_person_detected` | Entertainment | hallway | ok | 253.9 | 126.8 | 364 | 1342.6 | 0.0 | 114.9 | 91% |
| Staircase | `stairs_top_person_detected`, `stairs_top_person_occupancy` | Back Hallway | hallway | ok | 66.2 | 23.9 | 43 | 36.4 | 0.0 | 18.9 | 79% |

Created minutes split by house state (minutes) and night (22:00-06:00 local):

| room | created min by house state | of which night |
|---|---|---|
| Living Room | arriving 3.1, away 2.0, guest 3.7, home_day 1012.5, home_evening 60.7, home_night 1.8, sleep 39.9 | 40.1 |
| Patio | home_day 0.8 | 0.0 |
| Garage A | arriving 1.4, away 58.7, guest 7.7, home_day 18.0, home_evening 0.9, sleep 0.1 | 0.1 |
| Game Room | arriving 1.0, away 0.5, guest 21.6, home_day 35.5, home_evening 0.2, home_night 0.2, sleep 55.3 | 55.3 |
| Garage Hallway | arriving 1.1, away 0.1, guest 12.3, home_day 12.8, home_evening 3.7, home_night 4.3, sleep 3.7 | 3.7 |
| Garage B | guest 0.2, home_evening 0.7 | 0.0 |
| Upstairs Hallway | guest 0.0, home_day 0.1 | 0.0 |
| Master Hallway | arriving 2.9, away 1.5, guest 67.5, home_day 62.9, home_evening 20.5, home_night 15.7, sleep 9.6 | 9.6 |
| Foyer | away 0.1, guest 22.2, home_day 49.0, home_evening 26.9, home_night 19.3, sleep 9.4 | 9.4 |
| Staircase | arriving 0.0, guest 0.7, home_day 18.6, home_evening 2.1, home_night 1.2, sleep 1.2 | 1.2 |

### Per-room hold recommendation under the plan's Q1 rule

Q1 text (plan §8): *"None until D0 (c)/(f) is shown; then only rooms whose cameras watch only that room (no glass, no doorway into another area) and where D0 shows held minutes that match real presence."* Operationalised here so it is falsifiable (thresholds are this probe's, not the plan's, and are stated so the operator can change them): ON only if ALL of: room not muted; every camera in the area is interior-role (no egress/perimeter device); >= 30 created minutes in 7 days (the hold does something); unsupported share of created minutes <= 10% (held minutes agree with BLE-in-room or a Tier-1 sensor +-120 s); no documented glass/doorway hazard (Living Room: patio through glass, card CENSUS-PATIO-THROUGH-GLASS-1, `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.2 pool-overhead trap has no room today).

| room | hold on ship day? | why | created min | unsupported | 11-14 (party) created / unsupported min | room Automation switch (live) |
|---|---|---|---|---|---|---|
| Living Room | off | unsupported 86% > 10%; hazard: patio through glass (CENSUS-PATIO-THROUGH-GLASS-1, config fix pending) | 1123.5 | 86% | 34.1 / 24.8 | on |
| Patio | off | exterior-role camera in the area (perimeter); created 0.8 min < 30; unsupported 31% > 10% | 0.8 | 31% | 0.0 / 0.0 | on |
| Garage A | off | exterior-role camera in the area (egress); unsupported 88% > 10% | 86.8 | 88% | 8.2 / 3.8 | on |
| Game Room | off | unsupported 53% > 10% | 114.4 | 53% | 21.7 / 20.0 | on |
| Garage Hallway | off | muted (disable_camera_presence); unsupported 67% > 10% | 38.2 | 67% | 14.6 / 9.5 | on |
| Garage B | off | exterior-role camera in the area (perimeter); created 0.9 min < 30; unsupported 100% > 10% | 0.9 | 100% | 0.2 / 0.2 | on |
| Upstairs Hallway | off | created 0.1 min < 30 | 0.1 | 0% | 0.0 / 0.0 | on |
| Master Hallway | off | unsupported 77% > 10% | 180.8 | 77% | 69.1 / 52.3 | on |
| Foyer | off | unsupported 91% > 10% | 126.8 | 91% | 23.0 / 19.6 | on |
| Staircase | off | created 23.9 min < 30; unsupported 79% > 10% | 23.9 | 79% | 1.7 / 0.2 | on |

**Rooms recommended ON under this reading: none.**

## (d) Census replay under the four semantics

Interior census set (resolved by registry from the interior list): 12 person sensors; Frigate with a count sensor 5 (feed `unidentified_count`), Frigate binary-only 0, other platforms 7 (feed only the raw camera total). Options read: census_hold_interior 180 s, census_ble_cancel_enabled True, cross-validation True, divergence downgrade True.

### Self-check: today's semantics replayed against the recorded rows

Samples = every `census_snapshots` row (`zone='house'`) in the window (7514 rows; one per ~60-90 s). Replay = variant (i) (null areas), evaluated at every input change plus a 5 s grid and at each row's exact timestamp, with the real hold/decay machine (`camera_census.py:6064`, hold 180 s, sustain 15 s), the clamp against the recorded `identified_persons_in_house` (identity inputs are not replayed: BLE/face/egress-face are folded in by that recorded value), BLE-by-area from the recorded `sensor.universal_room_automation_<p>_location`, face freshness from the recorded face sensors.

- `unidentified_count` replay equals recorded on **7495 / 7514 samples = 99.75%** (gate: >= 99%) -> **PASS**.
- Restricted to the 787 samples where either side is > 0 (idle minutes dominate the all-sample rate): 768 / 787 = 97.6%.
- Raw dedup totals: Frigate total equals recorded `frigate_count` on 99.99% of samples, binary-platform total equals recorded `unifi_count` on 100.00%.

First mismatches (CST, recorded unid, replay unid, replay camera_unrecognized, replay pre-cancel, replay identified, recorded identified):

| t | rec unid | replay unid | camera_unrec | pre_cancel | replay ident | rec ident |
|---|---|---|---|---|---|---|
| 11-09 08:50:18 | 0 | 2 | 3 | 3 | 1 | 1 |
| 11-09 12:11:27 | 0 | 1 | 2 | 2 | 1 | 1 |
| 11-10 13:11:50 | 1 | 2 | 4 | 4 | 1 | 1 |
| 11-10 14:25:22 | 0 | 1 | 2 | 2 | 1 | 1 |
| 11-11 10:43:32 | 1 | 2 | 3 | 3 | 1 | 1 |
| 11-11 15:11:09 | 0 | 1 | 2 | 2 | 1 | 1 |
| 11-13 13:13:02 | 0 | 1 | 2 | 2 | 1 | 1 |
| 11-13 13:24:32 | 3 | 2 | 4 | 4 | 1 | 1 |
| 11-13 13:34:32 | 1 | 2 | 8 | 8 | 1 | 1 |
| 11-13 13:54:02 | 2 | 1 | 3 | 3 | 1 | 1 |
| 11-13 14:05:33 | 0 | 1 | 2 | 2 | 1 | 1 |
| 11-13 22:50:50 | 0 | 1 | 3 | 3 | 2 | 2 |

### Variant comparison (per census sample; 11-14 is the party)

| day | samples | unid>0 today | (ii) differs | (iii) differs | (iv) differs | (ii) crosses to 0 | (iii) crosses to 0 |
|---|---|---|---|---|---|---|---|
| 11-08 | 326 | 0 | 0 | 0 | 0 | 0 | 0 |
| 11-09 | 1058 | 60 | 0 | 0 | 0 | 0 | 0 |
| 11-10 | 1050 | 60 | 0 | 0 | 0 | 0 | 0 |
| 11-11 | 1061 | 220 | 0 | 6 | 6 | 0 | 5 |
| 11-12 | 1052 | 243 | 0 | 2 | 2 | 0 | 1 |
| 11-13 | 1089 | 112 | 0 | 0 | 0 | 0 | 0 |
| 11-14 | 1119 | 89 | 0 | 1 | 1 | 0 | 0 |
| 11-15 | 759 | 3 | 0 | 0 | 0 | 0 | 0 |

Delta distribution (variant minus today, over all samples): (ii): {0: 7514}; (iii): {-1: 8, 0: 7505, 1: 1}; (iv): {-1: 8, 0: 7505, 1: 1}

**INV-CENSUS-DOWN check (plan D0 discriminating criterion).** The invariant is stated over an evidence STATE S (before the stateful hold/decay machine), so it is tested two ways. (A) Stateless: at each of the 155976 evaluation instants (every input change + 5 s grid), variant (ii)/(iii) `camera_unrecognized`/pre-cancel vs today's: violations (ii) 0, (iii) 0; raw camera body total violations (ii) 0, (iii) 0. (B) Through the hold/decay machine, per census sample: samples where the variant's `unidentified_count` exceeds today's: (ii) 0, (iii) 1, (iv) 1; camera total exceeds: (ii) 0, (iii) 0, (iv) 0.

**Stateless INV-CENSUS-DOWN holds on this window (0 violations): per-area max and BLE cancel never raised the evidence-state count or the body total.**

Samples where the stateful `unidentified_count` exceeded today's (hold/decay path dependence, NOT a count of more bodies):

| t | variant | today unid | variant unid | today camera_unrec | variant camera_unrec | today pre_cancel | variant pre_cancel | recorded unid |
|---|---|---|---|---|---|---|---|---|
| 11-12 10:31:26 | V2 | 1 | 2 | 3 | 2 | 3 | 3 | 1 |
| 11-12 10:31:26 | V3 | 1 | 2 | 3 | 2 | 3 | 3 | 1 |

Camera body total (raw census, `_cross_validate_platforms`) delta (iii) minus today: {0: 7514}.

### 11-14 (the party) hour by hour

| hour (CST) | samples | recorded unid max | recorded unid>0 samples | replay (i) max | (ii) max | (ii) >0 samples | (iii) max | (iii) >0 samples | (iv) max | identified (recorded) max | camera total today max | camera total (iii) max |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 00:00 | 46 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 |
| 01:00 | 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 |
| 02:00 | 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 03:00 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 04:00 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 05:00 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 |
| 06:00 | 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 07:00 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 08:00 | 47 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 3 | 3 |
| 09:00 | 47 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 | 2 |
| 10:00 | 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 11:00 | 46 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 2 | 2 |
| 12:00 | 44 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 3 | 4 | 4 |
| 13:00 | 51 | 1 | 3 | 2 | 2 | 4 | 2 | 4 | 2 | 3 | 6 | 6 |
| 14:00 | 46 | 1 | 3 | 1 | 1 | 3 | 1 | 3 | 1 | 3 | 3 | 3 |
| 15:00 | 53 | 2 | 1 | 2 | 2 | 1 | 2 | 1 | 2 | 3 | 5 | 5 |
| 16:00 | 47 | 6 | 25 | 7 | 7 | 25 | 7 | 25 | 7 | 4 | 10 | 10 |
| 17:00 | 52 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 4 | 4 |
| 18:00 | 52 | 4 | 10 | 4 | 4 | 10 | 4 | 10 | 4 | 4 | 8 | 8 |
| 19:00 | 53 | 6 | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 3 | 9 | 9 |
| 20:00 | 46 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 3 | 4 | 4 |
| 21:00 | 51 | 2 | 5 | 2 | 2 | 5 | 2 | 5 | 2 | 3 | 5 | 5 |
| 22:00 | 41 | 1 | 24 | 1 | 1 | 24 | 1 | 24 | 1 | 3 | 2 | 2 |
| 23:00 | 45 | 1 | 7 | 1 | 1 | 8 | 1 | 8 | 1 | 1 | 2 | 2 |

### Oracle (4): 11-14 head count (Q6 answered by the operator)

Ground truth: party high-water mark **14 to 15 people**, no time given; recorded census peak 10 at 16:26 and 16:43; busy window about 16:00 to 19:00. Peak of each quantity over the whole of 11-14 (CST), person total = identified + unidentified:

| semantics | 11-14 peak | at (CST) | short of 14 | short of 15 |
|---|---|---|---|---|
| recorded `total_persons` | 10 | 11-14 16:43:35 | 4 | 5 |
| (i) today, replayed | 10 | 11-14 16:15:30 | 4 | 5 |
| (ii) device areas, per-area max | 10 | 11-14 16:15:30 | 4 | 5 |
| (iii) + BLE cancel (CORRECT) | 10 | 11-14 16:15:30 | 4 | 5 |
| (iv) + stuck discount | 10 | 11-14 16:15:30 | 4 | 5 |
| raw camera body total (i) | 10 | 11-14 16:15:30 | 4 | 5 |
| raw camera body total (ii) | 10 | 11-14 16:15:30 | 4 | 5 |
| raw camera body total (iii) | 10 | 11-14 16:15:30 | 4 | 5 |
| raw camera body total (iv) | 10 | 11-14 16:15:30 | 4 | 5 |

Within 16:00-19:00 (151 samples) CORRECT (iii) reads a lower person total than today on 1 samples.

Reading: today's summing census already sits 4-5 below the operator's count at the peak; any semantics that can only lower the count (per-area max, BLE cancel) cannot close that gap. Whether CORRECT's removed double counts outweigh a lost real person is read from the table above: compare the (iii) peak with today's.

### Contradicted-zero table (the D4 gate input)

Population: every sample where variant (ii) or (iii) reads `unidentified_count` 0 while (i) read > 0 (the minutes the change would remove). Oracles per plan D0 (d): **(1)** a `person.*` whose trust state (recorded `person.<x>` state; the BLE-overrule refinement of `person_state_for_trust` is not recorded) is `home` with no BLE room in the camera's area and no fresh face; **(2)** a door-crossing entry in the prior 2 h with no later exit (`person_entry_exit_events`); **(3)** a Tier-1 sensor `on` in the camera's area with no BLE person there; **(4)** 11-14 operator head counts: **PENDING (Q6 unanswered), source not evaluated**. A minute is CONTRADICTED if any of (1)-(3) holds.

| variant | samples crossing to 0 | CONTRADICTED samples | by oracle (1)/(2)/(3) | oracle (4) party counts |
|---|---|---|---|---|
| (ii) device areas | 0 | 0 | - | PENDING (Q6) |
| (iii) + BLE cancel | 6 | 1 | {'(2)': 1} | PENDING (Q6) |

Every crossing sample (CST; BLE-located residents at that instant; oracle flags):

| t | variant | camera areas > 0 | today unid | identified | BLE located | (1) | (2) | (3) | detail |
|---|---|---|---|---|---|---|---|---|---|
| 11-11 11:37:23 | V2 | Living Room | 1 | 1 | ezinne@Living Room |  |  |  |  |
| 11-11 13:19:11 | V2 | Living Room | 1 | 1 | ezinne@Living Room |  |  |  |  |
| 11-11 13:57:37 | V2 | Living Room | 1 | 1 | ezinne@Living Room |  |  |  |  |
| 11-11 14:10:16 | V2 | Living Room | 1 | 1 | ezinne@Living Room |  |  |  |  |
| 11-11 15:11:09 | V2 | Living Room | 1 | 1 | ezinne@Living Room |  |  |  |  |
| 11-12 09:54:26 | V2 | Living Room | 1 | 1 | ezinne@Living Room |  | (2) |  | entry:ezinne |

Oracle (2) refinement (reported separately, NOT the plan's rule): an entry whose `person_id` is the resident who is BLE-located in the camera area is explained by that resident, not an uncounted person. Contradicted samples whose only flag was such an explained entry: (ii) 0, (iii) 1.

Gate reading (sources 1-3): crossing minutes total = 6; contradicted = 0 (ii) + 1 (iii). -> **contradicted > 0: the hard gate FAILS on sources 1-3 (threshold 0, no tolerance) => D4-KEEP.**

### Hidden-second-person table (area max below the sum across DIFFERENT physical cameras)

Interior census sensors grouped by area (NEW rule) and physical camera (W1 twin collapse approximated by registry device area + device name + NVR-platform check, see header). Areas with >= 2 distinct physical interior cameras: **none**.

Physical cameras per area: Foyer = 1 (foyer_fisheye_person_detected, foyer_fisheye_person_occupancy); Game Room = 1 (playroom_person_detected, playroom_person_occupancy_2); Garage Hallway = 1 (camera_protect_garagehallway_person_detected); Living Room = 1 (family_room_person_detected, family_room_person_occupancy); Master Hallway = 1 (master_hallway_person_detected, master_hallway_person_occupancy); Stairs = 1 (stairs_top_person_detected, stairs_top_person_occupancy); Upstairs Hallway = 1 (upstairs_hall_person_detected)

Result: with the NEW map no area holds two distinct physical interior cameras, so per-area max can only collapse a camera's own two NVR legs (Frigate + Protect twins). The residual that does exist is within one camera (its own count), which per-area max does not change. Table empty.

W1 twin groups used (device names): Back Yard + Back Yard; Family Room + Family Room; Foyer Fisheye + Foyer Fisheye; Front Door Aerial + Front Door Aerial; Front Side PTZ + Front Side PTZ; G5 Bullet + G5 Bullet; Garage A + Garage A; Garage B + Garage B; Hot Tub + Hot tub; Madrone G6 Entry + Madrone G6 Entry; Master Hallway + Master Hallway; Playroom + Playroom; Pool Equipment + Pool Equipment ; Rear PTZ + Rear PTZ; Stairs - top + Stairs Top; Upstairs Hall + Upstairs Hall; Utilities PTZ + Utilities PTZ

## (e) Zone tier house-state replay (camera-INCLUSIVE counterfactual)

Model: `ZonePresenceTracker._any_camera_occupied` (`presence.py:819`): a registered camera holds its zone while detecting or within 300 s of its last `on`; S2 "dead input holds": a sensor `unavailable` longer than the 120 s grace keeps its last reading for up to 900 s from the first unavailable, then reads off. Non-camera zone occupancy = any room of the zone occupied (recorded `binary_sensor.<room>_occupied`, which already includes BLE extension) OR a BLE person located in a room of the zone. Cameras registered = D3a' set (interior role only) in non-opted-out rooms.

Calibration of the non-camera zone model against the recorded `sensor.zone_<z>_presence_status` (cameras are not registered today, so the recorded mode IS the camera-free mode; SLEEP excluded because the mode is pinned):

| zone | recorded occupied min | model non-camera min | overlap min | recorded covered by model |
|---|---|---|---|---|
| Back Hallway | 2314.7 | 2754.4 | 2218.0 | 96% |
| Entertainment | 2306.4 | 3357.0 | 2247.4 | 97% |
| Master Suite | 3698.9 | 4215.9 | 3659.5 | 99% |
| Upstairs | 2332.5 | 2238.8 | 1988.8 | 85% |

### Minutes a zone reads occupied ONLY because of a camera (timeout 300 s + dead-hold included)

| zone | registered cameras | camera-tier min | camera-ONLY min | camera-ONLY by house state | of which night |
|---|---|---|---|---|---|
| Back Hallway | `stairs_top_person_detected`, `stairs_top_person_occupancy` | 417.2 | 6.7 | guest 0.1, home_day 0.6, sleep 6.1 | 6.1 |
| Entertainment | `family_room_person_occupancy`, `family_room_person_detected`, `foyer_fisheye_person_occupancy`, `foyer_fisheye_person_detected` | 4348.4 | 1162.3 | arriving 3.1, away 17.3, guest 10.1, home_day 949.3, home_evening 109.6, home_night 3.4, sleep 69.5 | 70.0 |
| Master Suite | `master_hallway_person_occupancy`, `master_hallway_person_detected` | 1835.7 | 383.9 | arriving 2.5, away 9.3, guest 100.1, home_day 102.4, home_evening 87.1, home_night 61.4, sleep 21.2 | 21.2 |
| Outside | - | 0.0 | 0.0 | - | 0.0 |
| Upstairs | `playroom_person_detected`, `playroom_person_occupancy_2`, `upstairs_hall_person_detected` | 709.9 | 0.7 | guest 0.3, home_day 0.2, home_evening 0.2, sleep 0.0 | 0.0 |

### AWAY edges split by `veto_path` / `last_away_branch` (recorded attributes on `sensor.ura_presence_coordinator_presence_house_state`), with the delay the camera-INCLUSIVE tier would add

`veto_path` is the engine's current value and resets after the edge (many rows read `none`); `last_away_branch` is the value AT the inference edge and is used as the split key; the attribute row is accepted only if its `last_away_at` is within 120 s of the edge. Path semantics (code): nobody-home reads `any_zone_occupied_for_empty`; path beta (`lost_admitted*`) reads `any_indoor_zone_occupied`; path alpha (`active`) reads no zone (`presence.py:1227-1232`, ledger #12), so its delay is 0 by construction (column 'delay applied'); column 'camera run remaining' shows how long a camera-tier run covered the instant, for information. Cameras: D3a' set, indoor zones.

| AWAY edge (CST) | from | veto_path (attr) | last_away_branch | attr row matches edge | camera run remaining s | delay applied s | cameras holding at the edge |
|---|---|---|---|---|---|---|---|
| 11-09 07:33:10 | home_day | none | active | yes | 0 | 0 | - |
| 11-09 17:16:39 | home_day | nobody_home | nobody_home | yes | 0 | 0 | - |
| 11-10 18:03:48 | home_evening | none | nobody_home | yes | 0 | 0 | - |
| 11-11 07:29:26 | home_day | none | active | yes | 0 | 0 | - |
| 11-11 17:14:57 | home_day | nobody_home | nobody_home | yes | 284 | 284 | family_room_person_occupancy |
| 11-11 18:43:58 | home_evening | nobody_home | nobody_home | yes | 0 | 0 | - |
| 11-12 07:34:50 | home_day | none | active | yes | 19607 | 0 | family_room_person_occupancy |
| 11-12 10:55:27 | home_day | active | active | yes | 7570 | 0 | family_room_person_occupancy |
| 11-12 12:58:48 | home_day | nobody_home | nobody_home | yes | 170 | 170 | family_room_person_occupancy |
| 11-12 15:54:22 | home_day | nobody_home | nobody_home | yes | 157 | 157 | family_room_person_occupancy |
| 11-13 08:36:45 | home_day | nobody_home | nobody_home | yes | 0 | 0 | - |
| 11-13 14:54:37 | home_day | none | active | yes | 925 | 0 | playroom_person_occupancy_2 |
| 11-13 15:05:04 | home_day | active | active | yes | 298 | 0 | playroom_person_occupancy_2 |
| 11-13 17:07:37 | home_day | active | active | yes | 243 | 0 | master_hallway_person_occupancy |
| 11-13 17:21:38 | home_day | active | active | yes | 1354 | 0 | master_hallway_person_occupancy |
| 11-13 17:39:36 | home_day | active | active | yes | 276 | 0 | master_hallway_person_occupancy |
| 11-14 09:51:39 | guest | none | nobody_home | yes | 0 | 0 | - |
| 11-15 13:43:29 | home_day | active | active | yes | 0 | 0 | - |

| split key (last_away_branch) | edges | edges delayed by camera tier | max delay s | edges over the 1200 s bound |
|---|---|---|---|---|
| active | 10 | 0 | 0 | 0 |
| nobody_home | 8 | 3 | 284 | 0 |

Corrected bound (plan HIGH 1): 300 s camera timeout + up to 900 s stream-dead hold = 1200 s PER CAMERA SENSOR in a healthy-or-dead-but-recovering state. A sensor that stays `on` (stuck or real) holds without limit, which is why the observed maximum below can exceed the bound: observed max delay applied 284 s.

### Would-be ARRIVING edges while AWAY (camera-inclusive counterfactual; D3c keeps these at zero)

| camera-tier run starts while house AWAY (CST) | run length s | real arrival followed |
|---|---|---|
| 11-09 18:03:01 | 305 | no (phantom) |
| 11-12 16:43:07 | 10486 | yes (house left AWAY within 10 min) |
| 11-13 17:04:18 | 443 | yes (house left AWAY within 10 min) |
| 11-13 17:18:16 | 1556 | yes (house left AWAY within 10 min) |

### WAKING edges (SLEEP -> WAKING) moved earlier by the camera tier

Model: after `sleep_end_hour` 06:00 local the sustained gate needs `any_zone_raw_occupied` for 90 s (`presence.py:202`, `:7767`). cf0 = first sustained run of the non-camera model after 06:00 (calibration: should sit just before the actual edge); cf1 = same with the camera tier OR-ed in. An edge is camera-moved only if cf1 is earlier than cf0 by > 30 s.

| actual WAKING edge | model cf0 (no camera) | model cf1 (with camera) | moved earlier s | camera-moved? | was someone up? (+-5 min of cf1) |
|---|---|---|---|---|---|
| 11-09 06:00:20 | 11-09 06:00:00 | 11-09 06:00:00 | 0 | no | - |
| 11-10 06:00:24 | 11-10 06:00:00 | 11-10 06:00:00 | 0 | no | - |
| 11-11 06:00:15 | 11-11 06:00:00 | 11-11 06:00:00 | 0 | no | - |
| 11-12 06:00:49 | 11-12 06:00:00 | 11-12 06:00:00 | 0 | no | - |
| 11-13 06:00:14 | 11-13 06:00:00 | 11-13 06:00:00 | 0 | no | - |
| 11-14 06:00:52 | 11-14 06:00:00 | 11-14 06:00:00 | 0 | no | - |
| 11-15 06:00:17 | 11-15 06:00:00 | 11-15 06:00:00 | 0 | no | - |

### SLEEP held by `_zone_night_raw` through a camera limb

House-wide (decisive for nobody-home / path beta, which need ANY indoor zone occupied): minutes during house SLEEP where the camera tier is the only occupied input of EVERY indoor zone that is occupied: **0.0 min over 0 nights** (none).

Per zone (display / HVAC night tail only; the zone reads occupied through SLEEP only because of a camera):

| zone | camera-only SLEEP min | nights | per night (min) |
|---|---|---|---|
| Back Hallway | 6.1 | 2 | 11-11: 5.2, 11-14: 0.9 |
| Entertainment | 69.5 | 3 | 11-09: 0.7, 11-13: 33.9, 11-14: 34.9 |
| Master Suite | 21.2 | 5 | 11-08: 0.0, 11-11: 3.1, 11-12: 0.0, 11-13: 16.4, 11-14: 1.6 |
| Upstairs | 0.0 | 1 | 11-13: 0.0 |

`camera_detection` inference triggers per day (state edges on registered sensors): 11-08: 425, 11-09: 619, 11-10: 651, 11-11: 522, 11-12: 813, 11-13: 2372, 11-14: 3918, 11-15: 1048.

## (f) Family Room patio through glass (CENSUS-PATIO-THROUGH-GLASS-1)

Family-room camera devices (device area `living_room`, registry): Family Room, Family Room. Person sensors: `family_room_person_occupancy`, `family_room_person_detected`; count sensors: `family_room_person_count`. Room(s) on that area: Living Room (room_cameras fusion picks: Living Room: ['camera.family_room']).

Room sensors considered quiet = 3 configured Tier-1 sensors (`mmwave_temp_lux_hum_zigbee_livingroom_presence, screek_human_sensor_l13_2412s_presence, mmwave_lux_temp_hum_zigbee_livingroom_presence`) all off and no BLE person located in `Living Room`.

| measure | total min | by house state (min) | house AWAY min | sun up min | dark min |
|---|---|---|---|---|---|
| camera person on OR count > 0 | 3255.6 | arriving 3.8, away 2.0, guest 397.6, home_day 2260.1, home_evening 331.8, home_night 82.0, sleep 178.3 | 2.0 | 2490.5 | 765.1 |
| ... while room's own sensors quiet AND no BLE person in room | 1694.6 | arriving 3.5, away 2.0, guest 35.5, home_day 1468.2, home_evening 107.8, home_night 7.1, sleep 70.4 | 2.0 | 1493.8 | 200.9 |
| ... and the room itself reads vacant (what a hold would CREATE) | 1080.2 | arriving 3.1, away 2.0, guest 3.1, home_day 976.0, home_evening 60.1, home_night 1.6, sleep 34.3 | 2.0 | 983.9 | 96.4 |

Reading: the quiet-room row is the upper bound of patio leak into the room hold and (via the same sensors) the census; the AWAY column is the same minutes while no resident is home, i.e. a body the room sensors and BLE cannot corroborate.

## (g) 3b Wr / U changes

Definitions: Wr = devices of every enabled room's configured motion/presence/occupancy inputs plus the camera manager's area lookup (`camera_stream_health.room_stream_input_entities`, `camera_twin_health.py:~520`); U = (census interior person sensors UNION zone-tier registered cameras UNION `zone_cameras` picks) whose camera device is not in Wr.

| | Wr (devices) | U (entities) |
|---|---|---|
| OLD (self-checked) | 3 | 14 |
| NEW (D1 + D3a' zone registrations) | 19 | 2 |

NEW Wr devices: Camera_Protect_GarageHallway, Doorbell Lite, Family Room, Family Room, Foyer Fisheye, Foyer Fisheye, Garage A, Garage B, Kitchen Panel, Master Hallway, Master Hallway, Playroom, Playroom, ReolinkStudyBPorchPTZ, Stairs - top, Stairs Top, Study a Panel, Up Hallway Panel, Upstairs Hall.

NEW U (2): `staircase_person_occupancy`, `upstairs_hall_person_occupancy_2`.

| room that gains the input | input | camera device |
|---|---|---|
| Foyer | foyer_fisheye_person_detected | Foyer Fisheye |
| Foyer | foyer_fisheye_person_occupancy | Foyer Fisheye |
| Game Room | playroom_person_detected | Playroom |
| Game Room | playroom_person_occupancy_2 | Playroom |
| Garage A | doorbell_lite_person_occupancy_2 | Doorbell Lite |
| Garage A | garage_a_person_occupancy_2 | Garage A |
| Garage B | garage_b_person_occupancy | Garage B |
| Garage Hallway | camera_protect_garagehallway_person_detected | Camera_Protect_GarageHallway |
| Living Room | family_room_person_detected | Family Room |
| Living Room | family_room_person_occupancy | Family Room |
| Master Hallway | master_hallway_person_detected | Master Hallway |
| Master Hallway | master_hallway_person_occupancy | Master Hallway |
| Patio | reolinkstudybporchptz_person_occupancy_2 | ReolinkStudyBPorchPTZ |
| Staircase | stairs_top_person_detected | Stairs - top |
| Staircase | stairs_top_person_occupancy | Stairs Top |
| Upstairs Hallway | upstairs_hall_person_detected | Upstairs Hall |

Entities leaving U (owner pages become room pages): `camera_protect_garagehallway_person_detected`, `family_room_person_detected`, `family_room_person_occupancy`, `foyer_fisheye_person_detected`, `foyer_fisheye_person_occupancy`, `master_hallway_person_detected`, `master_hallway_person_occupancy`, `playroom_person_detected`, `playroom_person_occupancy_2`, `stairs_top_person_detected`, `stairs_top_person_occupancy`, `upstairs_hall_person_detected`.

Entities joining U: none.

Rooms whose stream-health watch set gains extras (the room hold lookup, full map incl. egress/perimeter roles):

| room | extras |
|---|---|
| Living Room | `family_room_person_occupancy`, `family_room_person_detected` |
| Patio | `reolinkstudybporchptz_person_occupancy_2` |
| Garage A | `doorbell_lite_person_occupancy_2`, `garage_a_person_occupancy_2` |
| Game Room | `playroom_person_detected`, `playroom_person_occupancy_2` |
| Garage Hallway | `camera_protect_garagehallway_person_detected` |
| Garage B | `garage_b_person_occupancy` |
| Upstairs Hallway | `upstairs_hall_person_detected` |
| Master Hallway | `master_hallway_person_occupancy`, `master_hallway_person_detected` |
| Foyer | `foyer_fisheye_person_occupancy`, `foyer_fisheye_person_detected` |
| Staircase | `stairs_top_person_detected`, `stairs_top_person_occupancy` |

## (h) Stuck-camera discount check

Code: `_watchdog_stuck_cameras` (`camera_census.py:2959`): discount only when `area_id` is set, the area has a URA room, the stuck window (unchanged 3 h or never-zero 6 h) is exceeded and no corroborator (BLE in area, or a room of the area with motion/presence/occupied) is present. The discount feeds only `_calculate_house_census` (`:2105`, the raw camera total), NOT `_get_unrecognized_camera_count`, so it can lower the camera body total / ledger input but never `unidentified_count` (grep `_watchdog_discounted_cameras`: set at `:1510/:1818/:2982/:3144`, read only at `:2105`).

`camera_stuck` NMs in the URA DB (`anomaly_log`, metric `camera_stuck`): 33 total since 08-23 18:40, **0 inside the 7-day window** (latest 10-30 03:00). The recorder window therefore holds no stuck NM; the check below uses the URA DB's own history for every NM (BLE = `person_visits` open at the NM instant, room signal = `environmental_data.occupied` 5-min samples +-5 min), which is a weaker oracle than the recorder, and the house state at that instant from `house_state_log`.

| NM time (CST) | recorder | camera | rule | NEW area | room(s) | house state at NM | BLE (person_visits) | room signal (environmental_data) | verdict under NEW area |
|---|---|---|---|---|---|---|---|---|---|
| 08-23 18:40:36 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | guest | 0 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 09-09 13:05:51 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_day | 0 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 09-09 13:06:51 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_day | 0 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 09-10 12:03:59 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_day | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-10 23:00:16 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | sleep | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-14 15:57:52 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_day | 0 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 09-14 15:58:23 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_day | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-20 20:54:32 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_night | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-20 20:54:33 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_night | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-20 23:00:19 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | sleep | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-23 09:21:27 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_day | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-23 23:00:24 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | sleep | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-24 23:00:12 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | sleep | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-25 08:25:44 | older | `family_room_person_occupancy` | never_zero | Living Room | Living Room | home_day | 0 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 09-29 13:23:41 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_day | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 09-29 13:24:33 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_day | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 10-01 18:18:33 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_evening | 0 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 10-01 18:18:33 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_evening | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 10-01 23:00:23 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | sleep | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 10-01 23:00:23 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | sleep | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 10-15 15:03:34 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | home_day | 3 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-23 13:23:04 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_day | 10 open visit(s) | room occupied (+-5 min): yes | corroborated -> NOT discounted |
| 10-25 02:51:12 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-25 22:24:17 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-25 23:00:17 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-27 01:47:47 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-27 23:00:03 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-28 15:07:07 | older | `family_room_person_occupancy` | never_zero | Living Room | Living Room | home_day | 10 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-28 15:36:53 | older | `family_room_person_occupancy` | unchanged | Living Room | Living Room | home_day | 10 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-28 23:47:02 | older | `playroom_person_occupancy_2` | never_zero | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-28 23:57:02 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |
| 10-29 11:47:13 | older | `master_hallway_person_occupancy` | unchanged | Master Hallway | Master Hallway | home_day | 0 open visit(s) | room occupied (+-5 min): no | uncorroborated -> WOULD DISCOUNT |
| 10-30 03:00:56 | older | `playroom_person_occupancy_2` | unchanged | Game Room | Game Room | sleep | 4 open visit(s) | room occupied (+-5 min): no | corroborated -> NOT discounted |

Tally of the 33 NMs under the NEW area: {'corroborated': 18, 'WOULD DISCOUNT': 15}.

The 15 would-discount rows by house state at the NM instant: {'home_day': 6, 'sleep': 6, 'home_night': 2, 'home_evening': 1}; by camera: {'`master_hallway_person_occupancy`': 9, '`family_room_person_occupancy`': 6}. Still-guest reading: rows in `sleep` / `home_night` are the ones a motionless person on a motion-class-only room could explain (Rule 1, `SENSOR_FLEET_CLASSES.md`); rows in `home_day`/`home_evening` with no BLE and no room signal are more likely a real stuck stream.

Today every stuck row has `area_id=None` -> `notify_only_reason: no_area_id` (the discount has never applied, so these 33 stuck cameras were never removed from any count). Window replica of the watchdog over the recorded count sensors (3 h unchanged / 6 h never-zero, corroboration = BLE in the area or a room of the area occupied): eligible-and-uncorroborated discount instants per camera: none.

Camera-total samples where the stuck discount changed the value (iv vs iii): 0 of 7514. The discount feeds only the raw camera total (`:2105`), never `unidentified_count`.

---
Probe self-checks: Wr/U old = 3/14 (PASS); (d)(i) unidentified match = 99.75% (PASS).

## Plan Completion Tracking (D0 scope)

- Done: (a)-(h), self-checks, gate verdicts incl. oracle (4) after Q6 was answered.
- Not done: exact `frigate_object_name_pairs` twin collapse (not importable on the host); approximated and disclosed; no verdict depends on it.
- Caveat on oracle (4): the operator gave a peak without a time, so only peaks are comparable, not an hourly head count.
