# AUDIT: per-phone Bermuda room accuracy in Foyer, Study B, Media Room (wall-panel scanners era)

Run 2026-11-15 ~02:15 CST, read-only. Card WALLPANEL-TOUCH-WITNESS-1. Read first, completely: `docs/architecture/SENSOR_FLEET_CLASSES.md`; `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (header/pipeline, section 3 BLE in full, section 10 ledger grep'd for Bermuda/scanner claims; the middle sections 4-9 skimmed by heading only, not line by line, so "completely" is NOT met for that doc). Nothing in the ledgers was re-asserted.

## Verdict (one line per room)
- **Foyer: UNMEASURABLE.** Only 10 single-occupant minutes where a phone's area = Foyer (<60). The room has no presence-radar-class input (only a ZV motion-class sensor), so truth is weaker even where data exists.
- **Study B: MIXED.** Precision 96% (218/227 min), recall 38% (218/578 min). Area = Study B is trustworthy; area is often something else (Master Bedroom) while the radar says someone is there.
- **Media Room: UNMEASURABLE.** 1 single-occupant minute with area = Media Room.

## Headline limits (these ARE findings)
1. **Window is 8 days, not 14.** HA `recorder: purge_keep_days: 7` (`/config/configuration.yaml`); `states` spans 2026-11-07 04:12 UTC (=11-06 22:12 CST) to now. Everything is after the ~10-20 panel go-live the brief names, so panel-active date is not visible from here and no before/after comparison is possible. I did not verify which Bermuda scanners are the panels (scanner devices are not in the Bermuda-owned device list; only the 4 phones + global device are).
2. **Single-occupant minutes exist for one person only.** Strict rule: person.* of all four residents in {home, not_home, StatZon1} and exactly one `home`. Result: ezinne 2421 min, jaya 194, oji 56, ziri 27. Oji is away ~11-09 on, Ziri/Jaya mostly co-home, so Ezinne is the only real subject. Ezinne in Foyer: 10 min; Media Room: 1 min; Study B: 227 min.
3. "Single resident home" is by `person.*` state (GPS/tracker composite). It does not exclude unlisted guests, pets, or a resident whose person reads not_home while physically home.

## Entities resolved (registry, not names)
- Person to phone: `.storage/person` device_trackers; the one `bermuda`-platform tracker per person in `.storage/core.entity_registry` (platform bermuda): oji `device_tracker.iphone_oji_bermuda_tracker` (device 435615c6), ezinne `…ezinne_iphone_bermuda_tracker` (97398998), jaya `…iphone_jaya_bermuda_tracker` (89b8e4c4), ziri `…iphone_ziri_bermuda_tracker` (ff7cce21). Area sensors = registry platform `bermuda`, same device_id, unique_id = `<uid>` (not `_area_last_seen` / `_switch_diagnostic`): `sensor.iphone_oji_area`, `sensor.ezinne_iphone_area`, `sensor.iphone_jaya_area`, `sensor.iphone_ziri_area`. Area state strings equal HA area names ("Foyer", "Study B", "Media Room"; the separate area "Entry Way" never appears as a value).
- Room inputs from URA entries in `.storage/core.config_entries` (domain universal_room_automation):
  - **Study B** (entry 01KDRGWK…): `presence_sensors` = `binary_sensor.mmwave_lux_wifi_esphome_studyb_presence` (platform esphome; the HLK-LD2410 radar per SENSOR_FLEET_CLASSES, presence-radar class). Truth = this radar (strong). URA `binary_sensor.study_b_occupied` also reported.
  - **Media** (entry 01KNDX9D…): `presence_sensors` = `binary_sensor.mmwave_motion_lux_matter_wifi_mediaroom_occupancy` (platform matter; Meross MS600 Matter half, the still-person holder per SENSOR_FLEET_CLASSES). Also `motion_sensors` = meross_lan `…_sensor_presence_motion` (motion-class, not used as truth). URA `binary_sensor.media_room_occupied` also reported. (Separate entry "Media Room Closet" is a different room, PIR only; excluded.)
  - **Foyer** (entry 01M2CDXA…): `presence_sensors` = [] ; `motion_sensors` = `binary_sensor.occupancy_lux_temp_humidity_hobeian_entry_presence` (mqtt Hobeian, motion-class family per SENSOR_FLEET_CLASSES rule 1/3, hence NOT presence-radar). So no presence-radar-class input; truth = URA `binary_sensor.foyer_foyer_occupied` = weaker, motion-derived.
- Falsifier inputs, Master Bedroom `presence_sensors`: `binary_sensor.screek_human_sensor_l13_b38b24_presence`, `…mmwave_temp_hum_lux_zigbee_masterbedroom_presence`, `…switch_mmwave_inovelli_occupancy`.

## Method / queries
`ssh ha "sqlite3 -readonly /config/home-assistant_v2.db"`: (1) `select metadata_id, entity_id from states_meta where entity_id in (...)`; (2) `select m.entity_id, s.last_updated_ts, s.state from states s join states_meta m using(metadata_id) where s.metadata_id in (...) order by s.last_updated_ts` for 4 person.*, 4 area sensors, 6 room sensors (+3 Master radars). Row counts bounded (25k). Analysis offline in Python: each series forward-filled to a 1-minute grid (state at end of minute), single-occupant minutes selected as above. Per room X and truth T (radar, else URA occupied): precision = area=X AND T on / area=X; recall = area=X AND T on / T on; wrong-area = area when T on and area != X. Scripts at `/tmp/probe_q/an.py` (scratch, not in repo).

## Per-room table (single-occupant minutes; Ezinne only has data; all numbers minutes)
| Room | Truth | min area=X | min truth on | Precision | Recall | Area when truth on but area != X (top 3) |
|---|---|---|---|---|---|---|
| Foyer | URA foyer_foyer_occupied (weak, motion-class) | 10 | 207 | 2/10 (n<60) | 2/207 (n<60) | Master Bedroom 73, Study B 34, Study A 31 |
| Study B | LD2410 radar (strong) | 227 | 578 | **218/227 = 96%** | **218/578 = 38%** | Master Bedroom 350, Study A 5, Oji Vanity 1 |
| Study B | URA study_b_occupied | 227 | 650 | 226/227 = 99.6% | 226/650 = 35% | Master Bedroom 380, Study A 15, Kitchen 11 |
| Media | Matter MS600 radar (strong) | 1 | 4 | 0/1 (n<60) | 0/4 (n<60) | Master Bedroom 4 |
| Media | URA media_room_occupied | 1 | 14 | 0/1 (n<60) | 0/14 (n<60) | Master Bedroom 14 |

When area = X but truth is off: Study B 8 min radar off + 1 unavailable of 227 (the rest of the "wrong" are all radar-on). Foyer 8 of 10 off.

## Study B recall gap: phone says Master Bedroom while Study B radar is on
Falsification attempt on "Bermuda is wrong": while Ezinne is the only resident home, 546 min have area = Master Bedroom; in 350 of them (64%) the Study B radar is on, and the three Master Bedroom radars are on in only 188 of the 546 (34%) (75 of the 350 Study-B-on minutes). So the Master Bedroom area reading is mostly NOT corroborated by Master radars, and Study B radar-on episodes show the area flapping Study B / Master Bedroom within one episode (e.g. 11-10 07:49-10:02 CST 134 min: Study B 100, Master Bedroom 34; 11-13 12:00-13:00 61 min all Master Bedroom). Two readings fit equally: Bermuda mis-picks Master Bedroom for a phone in Study B, or the phone sits in Master Bedroom while she is in Study B (phone-left-behind class). This data cannot separate them. Either way, the phone area is a poor recall witness for Study B. Note the other possibility (Study B radar false-on) is weakened, not ruled out, by the Master radars being off for 66% of those minutes.

## Secondary view (all minutes, any of the 4 phones; confounded by unlisted people/pets/other residents with radar-on)
| Room | Truth | min any phone area=X | min truth on | Precision | Recall |
|---|---|---|---|---|---|
| Foyer | URA occupied (weak) | 55 | 789 | 30/55 = 55% | 30/789 = 4% |
| Study B | radar | 242 | 587 | 218/242 = 90% | 37% |
| Media | radar | 114 | 403 | 61/114 = 54% | 15% |
| Media | URA occupied | 114 | 445 | 81/114 = 71% | 18% |
Media precision of 54% with a still-person radar and recall 15%: suggestive that Media Room area is a weak signal, but unproven under the single-occupant method (n too small, and multi-occupant confounds).

## Caveats
- n: Study B is the only room above 60 single-occupant minutes, from one person over ~8 days (episodes 11-09..11-13); not generalisable to other phones/panels.
- Minute resolution; radar-on lag/latch vs area-switch lag not modelled; per-episode alignment ignored.
- Foyer truth is motion-class and has high on-time (207 min) from passers-by, so recall there would be low even with a perfect phone.
- Panel scanner identity and go-live date unverified from registry here. Per the brief, panels live ~10-20; the 7-day recorder cannot show earlier behaviour.
- No Bermuda diagnostics called; no HA state changed.

## What would change these verdicts
Foyer/Media need >=60 single-occupant minutes with the phone in the room: a deliberate walk-in test or longer retention (long-term states are not kept per entity at minute grain). Study B recall would be resolved by checking where the phone physically is during a Study B radar-on episode.
