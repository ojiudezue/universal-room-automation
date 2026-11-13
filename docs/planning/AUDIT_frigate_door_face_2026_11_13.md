# AUDIT: Frigate door-camera face recognition (FRIGATE-DOOR-FACE-TUNING-1)

Probe 2026-11-13 02:40-03:00 CST. Read-only, not committed. Hand-off for the homelab session: homelab applies final Frigate changes.
Presence/identity docs read: AUDIT_face_production_after_nov_fixes.md and AUDIT_egress_history_labels_2026_11_13.md in full; IDENTITY manual only by grep (Protect/enrolment section, lines ~225-250). The full manual and PRESENCE state-of-play were NOT read completely.

## Answer
Door-camera face misses are mostly a geometry and distance problem, not a threshold problem. The recognizer already scores 0.90-1.0 on whatever it names, so a lower threshold buys nothing visible. On three of four door cameras the person is either tiny (G6 entry street traffic), top-down (garage A, front door aerial), or wide-angle and far (doorbell). Recognition rises sharply only when the person box fills more of the frame. Training-image gaps per person could NOT be read (needs `/api/faces`, which needs a Frigate login; not used).

## Sources and limits
- Frigate event JSON `fr_events.json` (620 person events, 2026-10-30 to 11-12, 4 door cameras), extracted earlier by another session from Frigate 2 (v0.18.2). I did not log in to Frigate. Fields used: `sub_label`, `data.sub_label_score`, `data.box`, `data.snapshot_area`, duration.
- HA REST (192.168.13.13:8123) for live frames and snapshots via the Frigate proxy (`/api/camera_proxy/...`, `/api/frigate/frigate-f2/notifications/<id>/snapshot.jpg`). HA recorder history (8 days) for the face sensors.
- Frigate F2 live config: NOT readable. `/Users/okosisi/ha-config/www/frigate.yml` and `frigate_cameras.yml` are dated 2026-01 (Frigate 1 era, builder points at 192.168.13.16, face `model_size: small`). Treat them as stale hints only. The earlier audit (line 21) reports F2 `face_recognition` on, `recognition_threshold` 0.85 (read via login by that session; I did not re-verify).
- Detect resolution/fps on F2: UNKNOWN. Stale file says detect 640x360 fps 5 (garage, aerial), 640x853 (doorbell), 352x480 (G6 entry). Snapshot frames imply native stream sizes: doorbell 1920x2560, garage A and aerial 1280x720, G6 entry 720x960 (live frames via proxy, file type check).
- Recorder face-sensor counts (below) are far lower than the Frigate event counts because only state changes are written; use the event table for rates.

## Per door camera (Frigate events, 14 days)
| camera | person events | named | names | score min / median | median box height named vs unnamed | median person box px (named / unnamed) |
|---|---|---|---|---|---|---|
| doorbell_lite | 215 | 55 (26%) | Jaya 29, Oji 14, Ezinne 7, Ojini 4, Ziri 1 | 0.82 / 0.995 | 0.56 vs 0.19 | 265k / 22k (of 4.9M frame) |
| garage_a | 139 | 41 (29%) | Jaya 25, Oji 13, Ojini 3 | 0.90 / 1.0 | 0.35 vs ~0.30 | 31.8k / 32.5k (of 0.92M) |
| madrone_g6_entry | 209 | 20 (10%) | Oji 12, Jaya 5, Ezinne 1, Ziri 1, Ojini 1 | 0.91 / 0.995 | 0.54 vs 0.02 | 129k / 171 px |
| front_door_aerial | 57 | 8 (14%) | Jaya 4, Ojini 2, Oji 2 | 0.94 / 1.0 | 0.29 vs ~0.28 | 38.5k / 33.9k |

Named rate by person box height (events / named):
- doorbell_lite: <0.1: 78/0; 0.1-0.2: 32/7; 0.2-0.3: 27/9; 0.3-0.45: 16/6; 0.45-0.7: 34/16; >0.7: 28/17.
- garage_a: <0.2: 12/0; 0.2-0.3: 58/15; 0.3-0.45: 53/21; 0.45-0.7: 14/5.
- madrone_g6_entry: <0.1: 148/0 (71% of its events); 0.3-0.45: 18/3; 0.45-0.7: 35/14; >0.7: 3/3.
- front_door_aerial: 0.2-0.3: 26/4; 0.3-0.45: 20/4; others 0.

Reading:
- G6 entry: 148 of 209 events are tiny boxes (<10% frame height, median 171 px), almost certainly street/distance detections that can never yield a face. Among usable boxes (>0.3 height) the named rate is 17/56 = 30%. The headline 10% is mostly noise events, not a recognizer failure.
- Doorbell: 78 events (36%) are tiny boxes and never named; above 0.45 height the rate is ~53%. Recognition tracks how close the person gets.
- Garage A and aerial: boxes are similar for named and unnamed (~32k px at 720p, person ~215 px tall), so face size/pose rather than person size is the limit. Live frames show why: garage A is a near top-down ceiling view (roof of the parked car dominates); the aerial is a straight-down view of the entry path; faces are mostly foreshortened. Median time on camera is 13-20 s, so it is not a dwell problem.
- Scores: every named score is 0.82-1.0 (one doorbell Ziri at 0.82; next lowest 0.90). The matcher gives high confidence even to wrong names (Ojini false on 10/10 at 0.91-1.0; the 11-12 07:23 Oji at 0.9 while Oji was in NZ). Score cannot separate right from wrong. Frigate does not expose below-threshold attempts in events, so near-miss distribution (the 0.6-0.8 band the card asked about) is UNKNOWN from this data; only the training-side change (below) can fix wrong names.

## Camera angle notes (live frames via HA proxy, 2026-11-13 02:44 CST, night/IR)
- garage_a (camera.garage_a_2): 1280x720 overhead view of the car roof and the floor; people appear from above. Poor for faces.
- front_door_aerial: 1280x720 steep top-down onto path and doormat; same limitation.
- madrone_g6_entry: 720x960 portrait fisheye at the porch pillar, facing the doormat and lawn; face-height close approach works (box >0.45), but street traffic produces the tiny-box events.
- doorbell_lite: 1920x2560 portrait, wide-angle looking along the driveway and garage face; close approach to the button gives big boxes (works), driveway walking is far and oblique.

## Misrecognition evidence (from AUDIT_egress_history_labels_2026_11_13.md)
- Ojini (operator: absent from the house over a month; purged from Frigate, not Protect): 10 Frigate events on the 4 door cameras (scores 0.91-1.0), 34 live-sensor changes across 12 cameras 11-05..11-08, last 11-09 00:24:48. Where evidence exists the faces are Oji (likely 2, weak 3) or Jaya (likely 2, weak 1), 3 unresolved. Silent since the purge. Her Protect enrolment is unobserved.
- Jaya/Ezinne: 11-11 08:25 front door and 08:26 garage A named Jaya (0.954 / 0.988), while Ezinne's `person` flips home at -9 s / 0 s and Jaya's three trackers stay away until 16:29; likely Ezinne. 11-07 12:38 garage A Jaya 0.92 with URA `ezinne` exit +45 s; 11-06 09:01 and 11-08 16:40 also contested. These are the Jaya-for-Ezinne confusion; Ezinne is named only 8 times in 14 days across all four cameras (7 on the doorbell), versus Jaya 63.
- Oji: 11-12 07:23 garage A named Oji (0.9) while he is in NZ (decisive false). Oji group C (9 clusters with tracker away) unresolved by the operator.
- Rates (labels audit section 4): tracked residents 1/30 = 3.3% to 6/30 = 20% depending on contested Jaya flips; pooled with Ojini 11/40 = 27.5% [16.1, 42.8]. Score does not discriminate.
- Ziri: 2 door events (0.82, 0.97), both while his phone was away; lean false; 1 doorbell recorder event in the last 8 days.

## Proposed Frigate changes (hand-off to homelab; ordered by expected effect)
1. Read-only first: from the Frigate host, `GET /api/faces` (image count per person: Jaya, Oji, Ezinne, Ziri, Ojini) and F2 `GET /api/config` for `face_recognition` (`model_size`, `recognition_threshold`, `min_area`, `unknown_score`, `detection_threshold`, `min_faces`), and per-camera `detect` width/height/fps. This closes the unknowns above. UNKNOWN today: training count per person.
2. Training gaps (highest probable value). Ezinne is named 8 times versus Jaya 63, and Jaya gets the Ezinne arrivals; add 10-20 varied crops for Ezinne from door-angle events (doorbell 0.45+ height, G6 entry close approach, garage A overhead, day and IR night). Add door-angle crops for Jaya at the same angles so the two separate. Add door-angle crops for Ziri (only 2 door events in 14 days, both unverified). Retrain by correcting mislabeled events in the Frigate UI (Recent/Train) rather than bulk upload, because Frigate trains from live-camera crops.
3. Ojini: confirm her gallery in Frigate is actually empty (the purge is inferred from the live sensor going quiet 11-09, not read from config), and purge or rename her Protect enrolment if Protect still names her (not observable from HA). Wrong names at 0.91-1.0 on residents are a gallery contamination signature; delete any Ojini-tagged crops that are actually Oji or Jaya.
4. Recognition model size: stale config says `small`. If F2 is still `small`, try `large` (needs GPU; Frigate docs gate `large` on a GPU/accelerator, verify before applying). Expected to help close-up similar-faces confusion (Jaya/Ezinne/Ojini/Oji) more than yield.
5. Do NOT lower `recognition_threshold` (0.85) on this evidence: named scores are already 0.9-1.0, wrong names score the same, and a lower threshold would raise false names (each wrong name at a door is a mis-unlock or mis-arrival candidate). Revisit only if step 1 shows many attempts logged between 0.6-0.8 (not visible to me).
6. Camera geometry (largest structural lever for garage A and the aerial): both are top-down, so faces rarely present. Options: a second angled camera at head height covering the garage door approach and the front step; for the doorbell, the close-to-button approach is already the best capture (~53% named at box >0.45). Operator/homelab decision; hardware.
7. Detect resolution: if F2 detect is 640x360 (as the stale file says) the detector-input person at distance is small; face recognition uses the full-resolution snapshot frame per 0.17+ docs (UNVERIFIED by me) so detect resolution may not limit faces. Check this claim in Frigate docs before changing detect width/height, since raising it costs Coral/GPU load.
8. G6 entry noise: 71% of its person events are tiny boxes. A `min_area` on `objects.filters.person` (or a motion mask over the street portion of the frame) would cut noise events without losing faces (named events there are all >0.3 height). Number to start from: min_area around 3000 px at the detect frame for this camera; derive from the real detect frame once step 1 gives it (my px values are in the snapshot frame, not the detect frame). This improves event hygiene and the recognized-rate metric, not recognition itself.

## Housekeeping findings
- `/Users/okosisi/ha-config/www/frigate.yml` and `frigate_cameras.yml`: the first contains plaintext MQTT and camera passwords (I saw them while grepping; values intentionally not copied here, and exposure in my terminal output was incidental). Files under `/config/www` are served by HA at `/local/`; recommend the operator/homelab remove or rotate and relocate. Not touched.
- Data cross-check: recorder counts (garage 5 named state changes, doorbell 14, G6 6, aerial 4 over 8 days) are not comparable to event counts, and the card's 36/33/16/7 come from the recorder-sensor audit; the event table here gives 41/55/20/8 over 14 days.

## Falsification
- "Distance/angle, not threshold, is the limit": disproved if step 1 shows many logged attempts between 0.6 and 0.85 on door cameras, or if unnamed doorbell events with box >0.45 height are mostly front-facing; I did not view unnamed close-up snapshots (the one sampled unnamed doorbell event 404'd), so close-up unnamed cases are the cheapest next check.
- "Ezinne under-trained": supported only by the low Ezinne count and the 11-11 08:25 mislabel; the gallery counts are UNKNOWN.

## Files
- Scratch data: `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/` (`fr_events.json`, live_*.jpg, snap_*_named.jpg).
