# Arc day validation, 2026-11-16 08:00 to 2026-11-17 08:07 CST (v5.108.34)

Read-only. Run at 2026-11-17 08:06 CST. Read first: ARC map section 4a, READMEs 5.108.27-.34 pending rows, vibememo 333-334. I did not re-read manual 5.5 in full (used the F1-F5 summary in CLAUDE.md). Sources: URA DB (`ssh ha` sqlite, ro), `memory_episodes`, `person_entry_exit_events` (UTC naive; converted), `notification_log` (UTC), REST states, CM diagnostics (`/api/diagnostics/config_entry/01KJEC3F...`, interior_vision block), system_log WS (newest 50 only). Helpers: `.claude/tmp/arcday_probe*.py`, `arcday_wslog.py`.

## Part 1: crossings

Source of truth: `egress_identity_outcome` episodes (one per crossing, ids 19001-19447), joined to `crossing_vision_shadow` by crossing_ts. 54 crossings.

| Door (camera group) | entry | exit | ambiguous | total |
|---|---|---|---|---|
| doorbell_lite | 6 | 4 | 24 | 34 |
| garage_a | 3 | 6 | 1 | 10 |
| madrone_g6_entry | 0 | 0 | 10 | 10 |
| Total | 9 | 10 | 35 | 54 |

- Ambiguous 35/54 = 65%. 26 of those 35 are one burst 09:25-10:41 on 11-16 (ids 19014-19220): a person walking the yard (about 150 HIGH perimeter companion pages 09:00-10:59, "Person track" chains across g5_bullet, sonoffwindow, utilities_ptz, madrone_g6_entry). Outside the burst: 9 ambiguous / 28 = 32%.
- Identity attach on the 19 directional crossings: attached 2, attached_ble_face_corroborated 1, ble_face_disagree_ble_wins 2 = 5 (26%). Others: vetoed 6 (all candidate jaya, person_state not_home, so the veto is correct but BLE keeps proposing her), no_leg 5, abstain 3. The `person_entry_exit_events` table shows person_id on 9 of its 19 window rows (47%). The two counts disagree on some rows (e.g. outcome 19426 07:41:40 vetoed jaya, table row 9147 07:42 ezinne exit; outcome 19250 12:23 no_leg, table 9133 ezinne). Cause unknown; the table may back-fill later.
- Vision (shadow): 19 rows: ok 12, blank 3, no_frigate_event 3, error 1. Model calls = 16 (ok+blank+error) vs cap 93 (`number.ura_notification_manager_crossing_vision_daily_calls`); 11-16 from 08:00: 10, 11-17: 6. One error: 11-17 06:33:47 id 19404, "Error processing video ...clip.mp4" (latency 2.3 s; Frigate clip fetch, the NVR-down morning). Shadow rows store the validator direction plus count and description; the model returns no separate direction.
- Vision was never called on an ambiguous crossing (0 of 35): VISION-AMBIGUOUS-CROSSINGS-1 is not live, as expected.
- Ledger: 19 `crossing_vision_ledger` terms, all `applied=false, reason=unknown`, `person` null, `l_before` null, even though `switch.ura_crossing_vision_census_authority` is on. The reason text carries no information. Candidate card.
- F1 edges (`person_arrival`/`person_departure`): arrivals 08:44 ezinne, 12:40 oji, 12:41 ezinne, 16:25 oji, 16:26 jaya; departures 12:31 oji, 12:32 ezinne, 15:01 oji, 05:22 jaya (sleep), 06:42 oji. Every arrival edge led its entry crossing by 1-3 minutes (geofence/BLE-led, F5), so no crossing produced an edge. Departures: 12:31/12:32 follow the 12:23-12:25 exits; 06:42 follows the 06:33 exit (vision error); 15:01 oji and 05:22 jaya have no door crossing at all.
- Contradictions: (1) 07:58:03 "entry" ezinne (id 19437, ble_face_disagree_ble_wins) while vision says "person walks away from the parked SUV, which then drives off", and the 07:37-08:06 SUV sequence flips exit, entry, exit, entry, exit within 30 min. Direction at this door looks unreliable. Ezinne is `home` now. (2) Same-event duplicates across sensors: 07:37:42/07:37:52, 08:06:04/08:06:07, 17:22:52/17:23:14, 12:23/12:25. (3) No "in with nobody home after" case found.
- Overnight 17:36 to 06:33: zero crossings. Frigate lost 6 cameras 22:15 (NVR down, twin covering) and 4 panel cameras were dead 22:00-06:28 (rows 27838-27882).
- Transit flood (vibememo 333): not a door crossing. It is `transit.path_implausible` anomalies: 161, 212, 184, 296 per day on 11-13 to 11-16, 7 so far 11-17 (anomaly_log). Cause: the validator flags a room move whenever any hallway camera fired and none saw the move, with no coverage check. Fix ANOMALY-FLOOD-ROWS-1 is built to review, not deployed.

## Part 2: pending organic criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| a | .34 boot-settle: two distinct stuck kinds at a fresh-day boot both paged | NOT YET | No boot since 11-16 15:32; no stuck NM in the 21:32Z+60 s window (first stuck row after restart is 27798, 15:48). Needs a fresh-day boot. |
| b | Evening exterior_person budget page | NOT YET (in progress) | CRITICAL exterior_person page 07:58:05 today (rows 27908-27917), repeat_1 row 27918 (08:03), repeat_2 row 27923 (08:08), house home_day. No CRITICAL page between 07:08 11-16 and now, so the 6 h budget had reset by design. Cap row `repeat_capped_home` due about 08:58. Re-query then. This is a morning page, not evening, but it exercises the 11-repeat-then-cap path. |
| c | MS600 bit-only tick; 4 h motion-class run | NOT YET (unproven) | No MS600 evidence anywhere. Living Room `max_active_failsafe` 240 min at 19:33 (row 27830, "PIR signal stale") is a possible S1-1 candidate; I did not read `automation_health.stuck_sensors` across it, so unknown. |
| d | Arrival engine `Arrival decision` lines | CONSISTENT WITH NONE | `person_profiles` absent from every URA config entry (data and options) in `.storage/core.config_entries`; 0 `arrival%` memory_episodes. The line is INFO (`music_following.py:1105`), outside the readable WARNING+ log, so absence in log is unverifiable. |
| e | Interior ship 2 describe | PARTIAL | Diagnostics: describe_requests 1, describe_unresolved 1, descriptions 0, describe_no_camera 0, calls_today 0, dewarped 0 (no call). The 'family room' refusal is correct by code: `_describe_target` (`person_sighting.py:1023-1042`) matches URA room names only, and no URA room is named Family Room (rooms include Living Room, Media, Foyer; camera.family_room exists but is not a room). Product gap, card: no alias from camera/area name to room. Records: 7 live, 7 groups (Foyer + Living Room dewarp-capable, 1 no_still_source), record_builds 5967, path_records 1 (3 `interior_path` episodes 13:05-16:30 CST 11-16), tick_errors 0. |
| f | New URA WARNING/ERROR | No ERROR; 5 WARNING worth cards | See below. |

f) system_log (newest 50 deduped, so a window-limited read, not exhaustive):
- `music_following.py:3720` Media "picked media_player.appletvmediaroom", 283 occurrences.
- `music_following.py:3687` Master Bedroom `media_player.master_bedroom_sonos_2` not found, 68 occurrences. Related: all 7 `music_follow_decision` episodes on 11-16 are `verify_failed`.
- `aggregation.py:1124` coverage rating delta -78% out of band, 7 occurrences.
- `coordinator.py:5776` Media Room Closet energy sensors unavailable, 17 occurrences.
- Also seen: weather divergence 4 F; `_dutycycle_notify` Jaya Bedroom (notify-only).

## Anything broken
1. Direction at the garage/doorbell SUV door is unreliable (07:37-08:06 flips; 07:58 "entry" is a departure by vision text).
2. 26 ambiguous rows from one yard-walker; the ambiguous rate is dominated by non-door activity.
3. Ledger terms 19/19 not applied with reason "unknown".
4. Music follow 7/7 verify_failed, plus two media-player resolution warnings.
5. Outcome-episode slug vs table person_id disagree on some rows.
