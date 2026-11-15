# AUDIT: G6 Entry webhook automation and the 2026-11-14 guest peak

Probe run Sun 2026-11-15 12:29-12:40 CST (`date`). HA timezone `America/Chicago` (REST `/api/config`, HA 2026.11.1). All times below are CST (UTC-6) unless marked Z. "Yesterday" = 2026-11-14 00:00-24:00 CST (06:00Z to 06:00Z). Read-only; no HA state changed.
Docs read: IDENTITY_FUSION_CAMERAS_MANUAL.md §5.5 (consumer-class doctrine) and kanban card VISION-CROSSING-ANALYSIS-1 (`kanban.data.yaml:34875`, field `protect_alarm_webhook_watch_2026_11_14`). Presence/HVAC STATE_OF_PLAY docs were not needed (no presence or HVAC code analysed); if the findings feed a presence change, they must be read first.

## Answer

- **Peak:** `sensor.universal_room_automation_persons_in_house` = **10 at 16:26:02**, again 16:43:36 and 16:50:23 (HA history). The DB `census_snapshots` (zone `house`) max is 10 at 16:43:35 (4 identified, 6 unidentified; frigate_count 10, unifi_count 0). `sensor.universal_room_automation_unidentified_persons_in_house` peaked at **7** at 16:26:02. `sensor.universal_room_automation_total_persons_on_property` peaked at **14** at 16:43:36.
- **The count is spiky, not sustained.** Persons in house was at or above 5 for a total of 41.6 minutes in the day and at or above 8 for 8.3 minutes (computed from HA history). Individual peaks last 30 s or less before dropping back.
- **GUEST mode** (`sensor.universal_room_automation_house_state`): 06:04:03 to 09:52:07 (3 h 48 m), then 11:35:14 to 22:08:48 (10 h 34 m). Total 14 h 22 m. It was already on before any crowd arrived (see finding 3).
- **G6 path fired: NO.** Zero real webhook triggers on 11-14. The only triggers of `automation.ura_test_capture_protect_alarm_manager_face_webhook` are 03:04:32Z, 03:48:21Z, 03:49:18Z and 03:52:28Z on 11-14 (= 21:04 to 21:52 CST on **11-13**), all operator/Protect "test" payloads (`alarm_id:"TEST"`, `eventId:"testEventId"`, `device:"FAKE_MAC"`). `last_triggered` is still `2026-11-14T03:52:28Z`.

## 1. What "the G6 automation" is

Resolved through `/api/config/automation/config/<id>` and the entity registry, not by name:

| Item | Fact | Source |
|---|---|---|
| HA automation | `automation.ura_test_capture_protect_alarm_manager_face_webhook`, config id 1794625460265, state `on`, mode parallel max 20 | REST states + `/api/config/automation/config/1794625460265` |
| Trigger | webhook id `ura_protect_face_capture_6021c5fcfb24d265ddfca36b`, POST/PUT/GET, `local_only: true` | same |
| Actions | `logbook.log` (name "URA Protect face webhook") and `persistent_notification.create`. **Nothing else.** | same |
| Upstream | Protect Alarm Manager rule "URA G6 Entry", source device MAC `A89C6CB6359C`, condition `face_known` | logbook payload 03:52:28Z. Registry: `binary_sensor.madrone_g6_entry_person_detected` has `unique_id A89C6CB6359C_smart_obj_person`, platform `unifiprotect`, device ff7daafd... |
| URA consumer | **None.** `grep -rn -i -E "ura_kp_face_probe\|alarm.?manager\|ura_protect_face_capture" custom_components` returns no hits. The older probe `ura_kp_face_probe` (id 1786827208839) no longer exists in HA (`/api/config/automation/config/1786827208839` returns "Resource not found"). AUDIT_egress_face_identity_prior_art.md B3 (lines 117-125) records that no URA code consumed it either. | grep, REST |
| Unrelated G6 automation | `automation.g6_doorbell_analysis` (alias "G4 Doorbell Analysis", balloob/ai-camera-analysis blueprint on `binary_sensor.madrone_g6_entry_motion_3` and `camera.madrone_g6_entry`). State `off` since 2026-11-09 00:11Z. Not the webhook; cannot have run on 11-14. | REST states |

So even a real webhook hit would only have written a logbook line and a persistent notification. The "URA code it feeds" does not exist yet; the face path into URA is a design intent (manual §6 row EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D2), not a wired producer.

## 2. Did it run

| Check | Result | Source |
|---|---|---|
| last_triggered | `2026-11-14T03:52:28.074829Z` (11-13 21:52 CST) | `/api/states` |
| Logbook, range 11-13 00:00 CST to 11-15 12:30 CST | 4 triggers, all 03:04Z-03:52Z on 11-14Z (11-13 evening CST); none after | `/api/logbook` filtered on automation entity and logbook name "URA Protect face webhook" |
| Traces | Not obtained: REST has no trace endpoint, the websocket client is not installed here, and `.storage/trace.saved_traces` held no webhook run that I confirmed. Logbook is the substitute; it lists every automation_triggered. | unknown beyond logbook |
| Webhook hits in HA log | journald unreadable over ssh (0 lines returned for the window); no evidence either way | `ssh ha journalctl` |
| URA diagnostics `person_awareness_layer` (entry 01KJEC3FYPYAGBQKZWC94CR8GR) | `f5_sent: {"ble": 2, "geofence": 3}`, no camera or face source, `g3_calls: {}` | `/api/diagnostics/config_entry/...` |
| Diagnostics validity | The counters are in memory. HA last started **22:03:53 CST 11-14** (logbook "Home Assistant started" 04:03:53Z). The counters therefore cover only ~22:04 CST onward, **not the 11-14 day**. A zero face count there proves nothing about the day. | logbook |

Verdict: the G6 webhook path did not fire on 11-14, but the diagnostics counters cannot add evidence for the day.

### Did events exist that it should have caught?

Falsification target: if Protect recognised a known face on G6 Entry on 11-14, the rule should have fired.

- Protect G6 smart-detection event entity `event.front_porch_madrone_g6_entry_smart_detection` (platform unifiprotect, device ff7daafd...) logged **8 `face` events**, all inside the guest peak: 16:08:08, 16:14:57, 16:24:31, 16:39:32, 16:39:40, 16:39:44, 16:40:25, 16:42:32 CST. It also logged 40+ `person` events and many `vehicle` events through the day (HA history).
- The event entity does not say whether a face was known or unknown. Whether any of those 8 were enrolled faces is **unknown** from HA. Frigate (the live name source, per AUDIT_protect_face_name_interfaces) named nobody at G6 in that window (below), which fits unknown guest faces that a `face_known` rule would not match. It does not prove the rule is healthy.
- For Jaya and Oji, who are enrolled in Frigate, Frigate named them on G6 at 12:59:29 (Jaya), 15:12:25 (Jaya), 15:52:52 (Jaya) and 18:59:43 (Oji, then Jaya) per `sensor.madrone_g6_entry_last_recognized_face_2` (platform frigate). Protect logged only `person` events at those moments, no `face` event (12:59:33, 15:12:14 and :22, 15:52:52, 18:59:41/:50). So on those four occasions Protect either did not detect a face or did not label it a face, and no webhook came. This is the closest thing to a discriminating observation: a known resident face at G6 reached Frigate but there is no sign it reached Protect Alarm Manager. Whether Protect has Jaya/Oji enrolled is unknown from data I may read (no Protect login allowed).
- Webhook delivery itself works: the 11-13 21:xx test payloads (FAKE_MAC) arrived through the same webhook id.

Operator-side check remains: look in the Protect event log for a recognised (named) face on G6 Entry at 12:59, 15:12, 15:52 or 18:59 CST on 11-14. If one exists, the rule does not deliver.

## 3. Census and presence data, 11-14 (CST)

### House state (`sensor.universal_room_automation_house_state`, HA history)
sleep to 06:01 waking, 06:02 home_day, **06:04 guest**, 09:52 away, 11:32 arriving, 11:33 home_day, **11:35 guest**, 22:08 home_night, 22:10 sleep.
`sensor.ura_coordinator_manager_house_state` agrees, with two "unknown" blips (14:39:05 and 22:02:22) that coincide with HA restarts.
DB `house_state_log` (UTC): `guest` at 12:03Z with trigger `deferred_retry` and 17:34:59Z, `away` at 15:51:39Z (trigger `census_update`).

### Residents (`person.*`)
Genuine edges: ezinne and jaya not_home 09:51:06, home 11:30:23 / 11:30:25. ziri (not_home all morning) home 13:39:44, not_home 14:24:19, home 15:22:31, not_home 18:33:19. oji_udezue home 16:39:58 (zone `StatZon1` 11:11 blips).
**Restart artefacts, do not read as departures:** oji not_home at 12:49:19 (HA started 12:49:19), oji and ezinne not_home at 22:03:53 (HA started 22:03:53). HA restarted four times: 12:46-12:49, 14:37-14:40, 16:04:45-16:08:46 and 22:00-22:03. The census zero readings at 12:48:08 and 16:06:57 are the same restarts.
`person.jaya` was `home` from 11:30 to end of day (never not_home after).

### Count timeline (persons_in_house, HA history; unidentified from `sensor.universal_room_automation_unidentified_persons_in_house`)
| CST | persons in house | note |
|---|---|---|
| 00:00-08:02 | 2 | residents (ezinne, jaya) |
| 09:51 | 0 | ezinne and jaya leave (away at 09:52) |
| 11:30-11:53 | 2 to 3 | return |
| 12:46 | 4 | 12:48 restart reset |
| 13:40-13:49 | 3 to 4 | ziri home 13:39:44 |
| 15:19-15:23 | 1 to 3 | after 15:22 ziri home |
| 15:30:28 / 15:32:07 | 6 | first sustained surge, back to 3 within a minute |
| 16:06:57 | 0 | HA restart |
| 16:12-16:24 | 3 to 6 | fluctuating |
| **16:25:34 / 16:26:02** | 8, then **10** | first peak; unidentified 7, guests_around 7 |
| 16:26-16:52 | 3 to 10 | flaps every 30 s; 10 again 16:43:36 and 16:50:23 |
| 18:00-18:41 | 4 to 8 | second wave; 8 at 18:30:21 |
| 19:15-19:19 | 3 to 9 | 9 at 19:18:53 |
| 20:56-21:25 | 3 to 8 | 8 at 21:17:27 |
| 22:04 | 1 | restart; after 22:08 home_night, 22:10 sleep |
| 22:21-23:13 | 1 to 3 | flapping around residents |

Hourly maxima (persons_in_house): 15h 6, 16h 10, 18h 8, 19h 9, 21h 8; guests_around: 16h 7, 18h 5, 19h 6, 21h 5.
DB `census_snapshots`, zone `house` (about 45 rows an hour), top rows in UTC: 22:43:35Z total 10 (4 identified: ezinne, jaya, oji_udezue, ziri; 6 unidentified; frigate 10, unifi 0; confidence medium, "close"), 22:50:23Z total 10 (frigate 10, unifi 3, "both_agree"), 22:29:02Z 9, 01:18:56Z (19:18 CST) 9 with 6 unidentified. Zone `property` max 4.

Reading of the count: the peak numbers come from Frigate (frigate_count equals total at every top row); Protect/UniFi corroborated only 0 to 3 of them. The flapping (a rise of several then a fall within 30 s, repeatedly) is characteristic of multiple Frigate person boxes per camera being summed, so **10 is an upper bound on people seen by cameras, not a headcount.** Ground-truth headcount from the operator is the only way to calibrate; none exists in the data.

## 4. What saw the guests

### Cameras around the door and G6
- Protect G6 Entry: person events 12:59, 13:01, 13:02, 15:12 (x2), 15:31, 15:52, then dense 16:07-16:42 (person, vehicle, 8 face events), 17:59, 18:43, 18:59 and sparse into the evening (HA history of `event.front_porch_madrone_g6_entry_smart_detection`).
- Frigate named only residents. `sensor.front_door_aerial_last_recognized_face_2`: Jaya 15:12:26, 18:59:40. `sensor.garage_a_last_recognized_face_2`: Jaya 11:38:59, 14:19:39. `sensor.madrone_g6_entry_last_recognized_face_2`: Jaya 12:59:29, 15:12:25, 15:52:52, Oji and Jaya 18:59:43-45. `sensor.doorbell_lite_last_recognized_face_2`: no name all day. **No guest was ever named** (they are not enrolled), so face attach could not have supplied a guest identity.
- Several face sensors went `unavailable` for ~1 minute around each restart (12:48, 14:39, 16:07, 22:02); events in those gaps are lost to every consumer.

### Egress crossings (`person_entry_exit_events`, UTC converted to CST)
81 rows on 11-14 (46 exit, 35 entry), **22 with a person_id (27%)**: jaya 17, ziri 3, ezinne 1, oji_udezue 1; 59 unidentified. G6 rows 27, of which 9 identified. By hour: 15h 10, 16h 16, 17h 6, 18h 5, 19h 4, 21h 15. Rows with peak_person_count >= 3: 16:20:21, 16:21:33, 16:22:05 (all unidentified exits, count 3, front_door_aerial and G6), 16:31:29 and 16:31:50 (garage_a, count 3), 18:44:03 and 18:44:06 (jaya exit G6 then entry front_door_aerial, count 5), 19:00:21/:35 (jaya, count 4), 21:24:53 (G6 exit, unidentified, count 4). Egress is a crossing record, not a head count.
Timestamp note: this table is UTC (the 15:41Z/15:42Z exits of jaya and ezinne match their 09:51 CST not_home edges).

### URA face-arrival counters
`person_awareness_layer.f5_sent`: ble 2, geofence 3, none from camera or face. Window is since the 22:03 restart only (see section 2).

## 5. Narrative (CST, data-only)

- 00:00-08:00. Two people home (persons_in_house 2, ezinne and jaya). Frigate names Jaya in the family room repeatedly overnight (`sensor.family_room_last_recognized_face_2`). House sleeps until 06:00, `waking` 06:01, `home_day` 06:02. **At 06:04 the house goes to GUEST with only 2 people counted.** The data does not say why: `house_state_log` trigger is `deferred_retry`, and the GUEST design (manual §6 row GUEST-GATE-DOOR-IDENTITY-1) is a night-stay latch over the DB, not instantaneous evidence. A guest staying the night is consistent but unproven here.
- 08:02-09:31. The count blips to 3 (unidentified 1) for under a minute a few times (08:02:36, 08:19:36, 08:20:27, 09:25:07, 09:31:13). Frigate names Oji and Jaya in the family room 08:10.
- 09:51. Ezinne and jaya leave (`person.*` not_home 09:51:06). Count 0, house `away` 09:52, so GUEST ends.
- 11:30-11:35. Ezinne and jaya return (home 11:30:23 and :25); `arriving` 11:32, `home_day` 11:33, **GUEST again 11:35**.
- 12:46-12:49. Count 4 briefly; HA restarts (12:46 to 12:49); oji "not_home" at 12:49:19 is the restart.
- 13:39. Ziri arrives (person home 13:39:44); count 3-4 on and off; ziri leaves 14:24:19, returns 15:22:31.
- 15:30-15:32. First surge: count 4, 6, 3, 4, 3, 5, 6, 3 inside two minutes. Protect G6 sees `person` events 15:31:07 and 15:52:52; Frigate names Jaya at G6 15:12 and 15:52.
- 16:04-16:08. HA restarts (16:04:45 stopped, 16:08:46 started); counts 0 at 16:06:57 then 3.
- 16:08-16:24. Protect G6 logs face events at 16:08:08, 16:14:57 and 16:24:31, plus vehicles at 16:11, 16:18, 16:23 and people. The count rises from 4 to 6 (16:15-16:23). Egress rows from 16:20 show unidentified exits with peak count 3.
- **16:25-16:52. Main peak.** Count 8 at 16:25:34, **10 at 16:26:02** (7 unidentified), and again 10 at 16:43:36 and 16:50:23; flapping between 3 and 10 every 30 s. Protect G6 logs 5 more face events (16:39:32 to 16:42:32), vehicles 16:23:56 and 16:41:34. Oji arrives at 16:39:58. Frigate names nobody new at G6 or the door in this window. The Alarm Manager webhook does not fire.
- 17:00-17:59. Count 3 to 5 (egress 6 rows). No count above 5 recorded between 16:52 and 18:00 in the history output except the steady 4 to 5.
- 18:00-18:41. Second wave: 4 to 8, 8 at 18:30:21; ziri leaves 18:33:19. Egress rows 18:44 show jaya exit G6 and entry front door with peak count 5. Frigate names Oji and Jaya at G6 18:59:43-45. Webhook silent.
- 19:15-19:19. Third wave: 3 to 9 (19:18:53).
- 20:56-21:25. Fourth: 3 to 8 (21:17:27), unidentified up to 3 to 4; 21:24:53 G6 exit with count 4.
- 22:02-22:10. HA restarts again (22:00 to 22:03); oji and ezinne show not_home at 22:03:53 (restart); house goes `home_night` 22:08:48, `sleep` 22:10:48; GUEST ends. Count settles at 1 to 3.
- Where the data is silent: who the guests are (none enrolled, no name ever attached), how many people were really present (count is Frigate-driven and spiky), whether Protect recognised any face as known, why GUEST began at 06:04, and any webhook or face-path activity inside the four restart gaps.

## 6. Key findings

1. **The G6 webhook automation never fired on 11-14 and feeds no URA code.** It only logs and notifies; no URA Python reads the webhook or its event. A working rule would still change no URA behavior today.
2. **Guests peaked at 10 in house (7 unidentified), 14 on property.** At 16:26:02, again 16:43 and 16:50. High count (>=5) lasted ~42 min total in short bursts; counts are Frigate-summed with Protect agreeing on only 0-3, so treat 10 as an upper bound.
3. **GUEST mode ran 14 h 22 m, starting at 06:04 with 2 people home**, and again at 11:35. It is the night-stay latch, not the crowd; the 16:00-21:00 crowd did not drive it. Unverified why it started at 06:04.
4. **HA restarted four times on 11-14 (12:46, 14:37, 16:04, 22:00), including 4 minutes just before the main peak.** This zeroes counts, creates false `person` not_home edges (oji 12:49, oji and ezinne 22:03), blanks the face sensors and resets the diagnostics counters, so the diagnostics `f5_sent` shows nothing about the day.
5. **Faces exist and are not being matched.** Protect logged 8 G6 `face` events during the peak and Frigate named nobody; Frigate named only Jaya and Oji on G6 four times, with no Protect `face` event or webhook alongside. Only 27% of egress crossings carry a person_id. The operator-side Protect log check is the missing falsifier for whether the rule delivers.

Scripts and raw outputs: `/Users/okosisi/Code/universal-room-automation/.claude/tmp/` (hist_probe.py, hist_attr.py, q1.sql, q2.sql, egress.txt, h2.txt, h3.txt, diag.json).
