# AUDIT: crossing pipeline (F3 -> ring -> crossing-vision) after v5.108.24

Probe run Sun 2026-11-15 12:50-13:00 CST. Read-only. Scripts: .claude/tmp/egress_probe_two.py, egress_reg_probe.py, egress_truth_probe.py, egress_base_probe.py, egress_anom_probe.py, ha_probe_rest.sh.
Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md and IDENTITY_FUSION_CAMERAS_MANUAL.md were NOT read end to end (about 2250 lines). I read the code paths directly and did not rely on either doc. This is a disclosed gap.

## VERDICT: QUIET (not broken)
No entry/exit crossing reached the crossing-vision producer after 00:04 CST, because no person was on any egress camera and no exterior door moved. The only three crossings since restart were all `direction_ambiguous`, which the producer ignores by design. v5.108.24 changed none of the code on that path.

## 1. Ground truth since restart 22:03:53 CST (recorder /config/home-assistant_v2.db, registry-resolved)
Egress cameras come from the integration entry's `egress_cameras` (camera.madrone_g6_entry, camera.doorbell_lite, camera.front_door_aerial, camera.garage_a_2). Their legs were resolved by registry device_id: Protect `binary_sensor.<stem>_person_detected` and Frigate `_2` `person_occupancy` / `person_count`.
- Person-on-camera events, any egress leg: only 00:00:59 to 00:04:02 CST on 11-15, on garage_a and doorbell_lite.
  - doorbell_lite_person_occupancy_2: on 00:00:59-00:01:07 and 00:01:33-00:01:52.
  - garage_a_person_occupancy_2: on 00:01:02-00:04:02.
  - Protect doorbell_lite_person_detected: on 00:01:00-00:01:13 and 00:01:30-00:01:47.
  - Protect garage_a_person_detected: on 00:01:05-00:01:47 and 00:02:21-00:03:04.
- front_door_aerial and madrone_g6_entry: zero state changes on every person leg since restart.
- Door hardware: `cover.konnected_f0f5bd523b00_garage_door` opened 00:00:30 and closed 00:03:00. The garage-hallway contact opened 23:07:56 and the patio-hallway contact opened 00:04:23. No other door contact moved. The front-entry lock status, unifi_access door_1467, and the Protect garage B and kitchen contacts have no state changes.
- person.*: oji home 00:00:24, ezinne home 00:00:15, ziri not_home, jaya home (all at the restart, 22:03:53, then no further change). This is the arrival that explains the 00:00-00:04 camera and garage-door activity. Oji flapped home/not_home at 23:30:09.
- `sensor.universal_room_automation_persons_entered_today` / `_exited_today` = 0 (last_reset 00:00 CST), consistent with no resolved entry/exit.
- Nothing on any egress camera after 00:04:02, so there is no "door opened with a person present and no row written" case.

## 2. Producer state
- `/api/error_log` returns 404 on this HA, as memory predicted. The log scan for ERROR/WARNING is **UNKNOWN (not performed)**; the journald window is about 2 minutes. Substitute evidence:
  - CM diagnostics `person_awareness_layer` (REST /api/diagnostics/config_entry/01KJEC3FYPYAGBQKZWC94CR8GR, 12:5x CST): g1_subscribers=1, crossing_store_failed=0, crossing_record_aged_out=0, g3_calls={} (no G3 writer in 3a, expected), move_unresolved_person=0, edges_truncated=0, ring_sizes = {binary_sensor.doorbell_lite_person_detected:1, binary_sensor.garage_a_person_detected:1, sensor.doorbell_lite_person_count:1}.
    - Those three ring entries match the three outcome rows below, so `_record_crossing` and the D3 ring work live.
  - `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` attributes: `crossing_vision_today` all zeros (calls, no_event, clustered, errors, skipped_*), `crossing_vision_last` null. This means no entry/exit event reached the producer today, and no error.
  - anomaly_log since 04:03Z: 173 rows. The only transit/egress-keyed rows are `transit.path_implausible` (severity 1), which is a different mechanism.
- Switches `switch.ura_crossing_vision_shadow` and `..._census_authority` are `on` now (last_changed 04:02:18Z, the boot restore).

## 3. Code path (git diff 06e88508 bc758799)
- crossing_vision.py trigger is UNCHANGED: `self.hass.bus.async_listen(EGRESS_EVENT, self._on_egress_event)` (crossing_vision.py:380-382, EGRESS_EVENT="ura_person_egress_event" at :65), plus the Frigate ingress consumer (:384-388). `_on_egress_event` (:612) returns early unless direction is `entry` or `exit`.
- The only 3a change in that file is the F1 departure feed. The raw `SIGNAL_RESIDENCY_EVENT` connect became `subscribe_person_edges(self.hass, self._on_residency_event, kinds=EDGE_KINDS)` (:420-427). EDGE_KINDS={arrival, departure} (residency.py, the only two KIND_ constants, lines 32-33), so it is the same record set as before. It is registered in `async_setup`, and g1_subscribers=1 confirms it. The handler only acts on departure (:1205-1215). This feed drives the ledger reconcile, not the vision call.
- transit_validator.py diff is additive only: the crossing ring, G2/G3 helpers, `door_*` accessors, and `_count_layer_event(... "crossing_store_failed")` inside an existing except. No change to direction resolution (~:2401) or the EGRESS_EVENT fire sites.
- A ring append failure cannot block the event: the append sits in `_record_crossing`, and the counter is 0.

## 4. The three egress_identity_outcome rows
| ts CST | camera | outcome |
|---|---|---|
| 00:00:59.80 | sensor.doorbell_lite_person_count | direction_ambiguous |
| 00:01:30.04 | binary_sensor.doorbell_lite_person_detected | direction_ambiguous |
| 00:02:21.24 | binary_sensor.garage_a_person_detected | direction_ambiguous |
All three carry direction "ambiguous", agreement "disagree", slug null. Per `_on_egress_event` (crossing_vision.py:616-618) a non-entry/exit direction returns before any scheduling. So no vision call was scheduled, and no shadow or ledger row is written for them. `direction_ambiguous` means no interior-neighbour camera event matched in the window (transit_validator.py ~:2401 onward). That logic is untouched by 3a.
Baseline: `direction_ambiguous` was 42 of 79 outcome rows on 11-13 and 20 of 101 on 11-14, so 3 of 3 is not out of character. Last pre-restart rows 11-14 21:42-21:55 were no_leg / ambiguous, with 8 `crossing_vision_shadow` rows from the same evening.

## 5. Other observations (not 3a regressions, flagged for the caller)
- Ledger state: `crossing_ledger.state="unknown"`, `unknown_reason="boot"`, L=null, last_anchor=null, ~14.8 h after restart. The anchor has not passed since boot. Five held inputs are listed: the media room mmWave (x2), study A, the upstairs guest room and the master bath. While the ledger is unknown, `note_departure` returns None (crossing_ledger.py:549) and no ledger or reconcile rows are written. That explains the zero `crossing_vision_ledger` rows by itself, independent of crossings. Whether this is normal after boot with Jaya home is unknown (UNKNOWN: no pre-3a boot comparison done). It is worth a card if anchors normally pass within hours.
- Also unknown: the ~2-min log window means any single WARNING from the restart itself is unseen.

## Falsifier
BROKEN would need a camera person-on event or a door opening with a person present after 00:04 CST with no outcome row. I queried every egress leg and every exterior contact I could resolve and found none. The one gap in that check: the Z-Wave deadbolt `home_access_keyed_touchscreen_deadbolt` has no states_meta row, so it is unchecked.
