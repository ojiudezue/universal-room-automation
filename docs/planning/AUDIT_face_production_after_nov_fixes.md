# AUDIT: did the November face fixes increase face output?

Probe 2026-11-12 ~19:00 CDT, read-only (HA recorder + URA DB via `ssh ha sqlite3 -readonly`, live sensor via REST).

## Answer
The fixes changed plumbing, not face output. Frigate produces the faces; URA cannot raise that. Recognition counts did not rise after the deploys, and egress `person_id` attach did not move (43% before, 40% after). The measurable gains are in URA's reading of faces (17 skipped `_2` cameras now read; 13 cameras device-derived), not in volume.

## Limits (cannot be measured as asked)
- Recorder history starts 2026-11-05 04:12 CDT (purge), so per-day face counts before the 11-08/11-09 deploys cover only 11-05..11-08. Nothing exists for 10-29..11-04. No longer face-sensor history in the URA DB (`census_snapshots` has no face column).
- A `*_last_recognized_face` state row is written only on a state or attribute change. A repeat of the same name is not counted, so these are lower bounds on recognitions.
- `Unknown` rows include ~28 per camera of boot/restart restore noise (every camera shows 26-35 "unknown" incl. the dead ones), so the named-vs-unknown split is only reliable for named.
- URA DB timestamps are UTC (the days below are UTC dates); recorder days are CDT.

## Deploy dates (git log, CDT)
- v5.107.1 face-source registry discovery: merged 11-08 23:33 (v5.107.6 arc release 11-09 02:44).
- v5.108.1 Frigate MQTT direct + face bridge on runtime prefix: 11-09 16:39.

## 1. Frigate named recognitions per day (CDT, recorder; named = Jaya/Oji/Ezinne/Ojini/Ziri)
| day | named | unknown-ish | note |
|---|---|---|---|
| 11-05 | 112 | 110 | before |
| 11-06 | 101 | 126 | before |
| 11-07 | 63 | 230 | before |
| 11-08 | 256 | 370 | before (deploy at 23:33); 99 Jaya + 95 Oji busy day |
| 11-09 | 66 | 148 | deploys |
| 11-10 | 81 | 190 | after |
| 11-11 | 110 | 300 total | after |
| 11-12 | 66 | 233 | after |
Before (11-05..08): mean 133/day. After (11-09..12): mean 81/day. Oji dropped from 58-95/day to 2-4/day from 11-09 (operator is away; NZ travel per memory), which explains the fall. Jaya (the person at home) before 11-05..08: 13/26/16/99; after: 47/65/82/56. Per-name by day is in the recorder query; Ezinne 8-12/day after vs 2-11 before. Conclusion: tracks who is home, no step change at the deploys.

Per camera, 11-05..12 named (top): family_room_2 419, master_hallway_2 126, kitchen_panel 47, upstairs_hall_2 38, garage_a_2 36, doorbell_lite_2 33, staircase_2 28, playroom_2 25, study_a_panel 18, stairs_top_2 17, madrone_g6_entry_2 16, g5_bullet_2 15. Zero named on 9 cameras (armcrest, armcrestash41b, back_yard, madrone_g6_entry_package, madroneptultra, reolinkpatio, reolinkstudybporchptz, sonoffwindow, + near zero utilities_ptz 1).

## 4. Interior vs exterior (11-05..12, 855 named)
Interior (family_room, master_hall, kitchen/study/up_hallway panels, upstairs_hall, staircase, playroom, stairs_top, foyer_fisheye): 724 (84.7%). Exterior (garage, doorbell, G6 entry, G5, front door aerial, PTZs, pool, hot tub): 131 (15.3%). Front door cameras (doorbell_lite 33, g6_entry 16, front_door_aerial 7) are the door-identity sources; they are thin.

## 2. Downstream
- Census `house` zone daily mean identified_count (URA DB, UTC days): 10-22..28 1.2-2.8; 11-01..04 1.6-2.3; 11-05..08 1.3-2.2; 11-09..12 1.35-1.5. Confounded by who is home and BLE; no step at the deploys. Unidentified rose slightly 11-11/12 (0.21/0.23).
- Egress `person_entry_exit_events` (person_id non-empty / total, UTC): 10-29..11-08 68/158 = 43%; 11-09..11-12 18/45 = 40% (day by day 11-08 13/25, 11-09 5/7, 11-10 1/3, 11-11 5/10, 11-12 7/25). Live sensor `egress_identity_attach_rate_24h` 0.077, abstain 0.23, ambiguity 0.23 (small sample). Not improved.
- Live `sensor.universal_room_automation_persons_in_house` (2026-11-13 00:56 UTC): `face_producer_health` live, `face_recognized_persons` [jaya], `face_source_registry_hits` 15, `pattern_fallbacks` 0, `device_derived_reads` 13, `skipped_person_sensors` 0, `skipped_cameras` [], `face_lookup_missing_count` 28, `frigate_face_msg_seen_count` 192 / `face_count` 191 / dropped 21 / retained 0 (since last restart). No `face_recognized_count` attribute exists on this sensor; `face_recognized_persons` is the equivalent.

## 3. Diagnosis: detection vs recognition vs plumbing
- Plumbing: was the real defect (17 `_2` cameras skipped, bridge on dead prefix). Now fixed: skipped_cameras empty, bridge ingesting (191 face messages). This is a fix to reading, which is invisible in Frigate-side counts.
- Recognition/detection: low and concentrated. 85% of named faces come from interior cameras; exterior and door cameras yield ~15% and 9 cameras none. This is the Frigate side (matcher/training/camera angle), and unchanged by any URA release. That is what caps egress attach at ~40%.
- Not busy work for correctness (consumers now see faces they were blind to), but it did not increase face volume; the next gains are Frigate-side (door camera recognition, training) not more URA discovery.

## Falsifier
A rise in named/day or egress attach rate starting 11-09 would contradict this; neither is present. A longer history (pre-11-05) was not available to rule out a lower earlier baseline for the plumbing fix on census reads.
