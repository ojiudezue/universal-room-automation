# AUDIT: perimeter silence after v5.108.20 restart (read-only, 2026-11-13 20:57 CST / 2026-11-14 02:57Z)

VERDICT: WORKING-AS-DESIGNED for the silence (pre-existing 120 s egress suppression). v5.108.20's NEW code paths were NOT exercised, so they are unverified live (not broken, not proven).

## Path each detection took
- Perimeter handler order (perimeter_alert.py:1358-1655): egress suppression (:1370-1387) -> cooldown (:1405) -> in-flight (:1446) -> severity -> gates (:1626-1637, where the new gate rows are written via _record_gate) -> dispatch (notification_log row). Nothing before the egress check logs a row; a gate row or an alert exists only past the egress check.
- Egress cameras (core.config_entries, URA entry `egress_cameras`): madrone_g6_entry, doorbell_lite, front_door_aerial, garage_a_2. Any "on" edge of an egress sensor stamps a GLOBAL egress time (:938-951); a perimeter person edge within EGRESS_SUPPRESSION_WINDOW_SECONDS=120 (:301) is dropped with _record_suppression (:1381).
- Live evidence: sensor.ura_security_coordinator_outside_open_tracks_diagnostic attr suppressions_by_camera = g5_bullet egress_suppression at 19:44:38.72 CST (01:44:38Z), seconds_since_egress 0.1; garage_b egress_suppression 01:45:07.9Z, 22.7 s (stamp = doorbell_lite occupancy_2 on at 01:44:45.238Z). gate_decisions_by_camera = {} and burst_demotions_by_camera = {} (no gate ever ran); sensor.universal_room_automation_last_perimeter_alert last_alert_time None (no dispatch since restart).
- leg_firing_by_camera: g5_bullet frigate2=8, protect=4 = exactly the 8 occupancy_2 + 4 detected on-edges, so every edge passed boot-settle and the listener is alive (engine subscribed, _on_perimeter_event ran, :4343-4412).
- Recorder history (REST /api/history, 00:51Z-02:57Z), every g5_bullet on-edge had an egress-camera (doorbell_lite / garage_a) on-edge within the prior 120 s:
  01:23:23.7 (garage_a 01:23:19.9, doorbell 01:23:20.8); 01:35:35.5/36.8 (garage_a 01:35:32.4, doorbell 01:35:34.4); 01:37:55 (doorbell 01:37:16.8); 01:38:39 (doorbell 01:38:08.5); 01:40:11 (doorbell 01:39:06.9); 01:40:56-58 (doorbell 01:40:55.8); 01:41:41-42 (garage_a 01:40:58.6, doorbell 01:40:55.8 = within 50 s); 01:44:36/38 (doorbell 01:43:47.5, garage_a 01:44:38.6).
  The doorbell_lite/garage_a stamps roll continuously 01:20-01:45Z (the 01:19Z arrival walking in via garage/front), keeping the 120 s window permanently re-armed.
- No cooldown/in-flight involvement possible: _last_alert is empty after restart (last_alert_time None). The Frigate 'rear_ptz' etc. had no edges post-restart in the recorder.

## Silence vs baseline
- notification_log exterior_person count at 00-02Z: 11-10 00h:8; 11-11 00h:5, 01h:5; 11-12 00h:4, 01h:1, 02h:2; 11-13 00h:2, 02h:4; 11-14 00h:13 (all <=00:27Z). Evening 00-03Z windows are normally single digits per hour with gaps; a 2 h gap after an arrival with active garage/doorbell cameras is within range. (The "100+/day" is mostly daytime/burst.)
- memory_episodes since 00:51Z: only actuation_conflict, away_transition_blocked, person_arrival (01:19:13Z). Zero perimeter_gate_decision rows is expected: _record_gate (the only writer, :4646) is downstream of the egress check.

## Does v5.108.20 touch the suppression path?
`git diff v5.108.19 v5.108.20 -- custom_components | grep EGRESS_SUPPRESSION|_last_egress|_on_perimeter_event|COOLDOWN` = empty. Diff changes are only: gate-row writer (_persist_gate_decision, fire-and-forget try/except, called inside _record_gate), daylight-only single-source demote, D1b egress-identity night branch, VLM location prompt, teardown latch. None sits before the egress check, none can raise out of the handler (all wrapped).

## Falsification
- Would show BROKEN: a post-restart perimeter edge with NO egress stamp in the prior 120 s that produced no row. None found: all 12 g5_bullet edges have a stamp (above). rear_ptz/back_yard/hot_tub/etc. had zero edges.
- Would show persistence bug: a gate row attempt failing. Cannot be tested: no gate ran.

## Gaps (UNVERIFIED)
- HA logs unreachable: `ssh ha` has no journalctl, `ha core logs` returned 401, docker denied; /api/error_log not tried per memory (404). So no log line for perimeter_alert errors since 00:51Z; only absence of the symptoms the code would produce.
- Only the LAST suppression per camera is stored (_last_suppression is overwritten), so earlier per-edge reasons are inferred from timing, not recorded.
- New v5.108.20 code (daylight demote, night D1b, gate-row insert, VLM location) has had zero live executions since install; INV-ROW remains unproven live. First real test: next perimeter edge with no egress edge in the prior 120 s (note vlm_gate select is 'off', single_source_demote ON, zone_agreement OFF, egress_known_xcorr ON).
- Design observation (pre-existing, card-worthy, not this cycle): a global egress stamp from doorbell_lite/garage_a mutes ALL perimeter cameras for 120 s, so an arrival/driveway scene that keeps those cameras firing mutes the driveway camera continuously (here ~25 min). No identity (known resident) check in that path.
