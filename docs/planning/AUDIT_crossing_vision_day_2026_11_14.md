# AUDIT: crossing vision, one day (2026-11-14, America/Chicago)

Read-only probe, written 2026-11-15 ~13:55 CST (DST ended 11-01, so the zone is CST, not CDT). Not committed. Data: `.claude/tmp/vision_report_1114.json`.
Read first: manual §5.5 (consumer map, doctrine), `PLANNING_crossing_vision.md` (all), `PLANNING_census_deconfliction.md` (§3.2 ladder, §3.3 function, CD1-CD3, `view_for_class`).
Sources: URA DB (`ssh ha`, `mode=ro`) `memory_episodes` types `crossing_vision_shadow` (73 rows on 11-14, 12:59:22-21:54:39), `crossing_vision_ledger` (46), `egress_identity_outcome` (101), plus `person_entry_exit_events`, `census_snapshots`, `house_state_log`; HA REST `/api/history/period` and `/api/states`. Timestamp handling: `memory_episodes.started_at` mixes UTC and -06:00, `person_entry_exit_events` and `house_state_log` are naive UTC, `census_snapshots` is +00:00; all parsed with `datetime.fromisoformat` and converted to local. Deployed code equals the repo for `crossing_vision.py`, `census_*`, `sensor.py`, `switch.py` (`cmp` vs the Samba mount, v5.108.24).

## Answer

- **Vision counted people at 41 of 73 crossings** (41 ok, 25 clustered into a primary, 4 error, 1 blank, 2 no_frigate_event). On ok rows vision equalled the camera peak 33/41 (case A); 6 camera-higher (C), 2 vision-higher (B). Vision totals (ok rows only): **9 in, 46 out, net -37**. Same 41 rows by camera peak: 9 in / 51 out.
- **Vision contributes to NO displayed or acting census number.** The ledger never left `unknown` (48 rows, all `kind=term, reason=unknown, applied=false`, no anchor ever). Two display sensors read the awareness view; they equal the trust sensors on all 473 one-minute samples from 16:07 (0 mismatches), and the F-LEAD constant is False, so a known ledger could not move them either. The 11-14 "guest 10" is interior camera bodies, not door crossings.
- **Vision in minus out does not reproduce the guest story**, and neither do the camera peaks or the crossing counts; all four instruments net negative. See section 2.

## 1. Definitions (from code)

Outcomes (`crossing_vision.py:69-79`, set in `parse_vision_response` :150-236, `_on_egress_event` :614-726, `_fire_request` :790-940):
- **ok**: parsed JSON, max per-frame count >= 1; `people_count` = people_total clamped to [peak, peak x frames] (:225-234). Counted in the accuracy numerator.
- **blank**: all frame counts 0 or absent; `people_count` None, never 0 (INV-BLANK, :225-227).
- **error**: llmvision service call raised or request build failed (`perimeter_enrichment.py:431, 452-457` -> `crossing_vision.py:916-917`). **timeout**/**unparseable**/**refused** are separate classes (none on 11-14).
- **clustered**: a request for the same door group exists within `CROSSING_VISION_CLUSTER_S` (60 s), or the matched Frigate event was already analysed (:666-690, join :728-760). No call; the row carries `primary_crossing_key`; the primary's count stands for the cluster.
- **no_frigate_event**: no person event on the door-group cameras within +/-`CROSSING_VISION_EVENT_MATCH_S` (10 s) (:675-678). No call.
- (not seen) skipped_cap / skipped_busy (:697-702), no_clip_url (:880).
- Blank cells in the table below mean the field is None (clustered/no-event/error/blank rows have no vision count).

Agreement cases (`agreement_case`, `crossing_vision.py:133-141`, constants :87-90): **A** vision == camera peak; **B** vision > camera; **C** camera > vision; **D** either side missing (None). Every non-ok row is D by construction.

Crossing key = shadow `source_ref` = `egress_identity_outcome.source_ref` (exact join). `person_entry_exit_events` has no key: linked one-to-one by same camera + direction, first pairing rows whose timestamp lags the crossing by 45.0 s (the usual resolution delay), then nearest within 120 s. All 73 rows linked and `peak_person_count` equals the shadow `camera_peak_count` on all 73 (INV-ADDITIVE holds live). `person_id` shown = bus value from the shadow row, else the pee value. Cameras are resolved through the entity registry (platform + device name); the same physical door is two registry devices (Frigate and UniFi Protect), so the door group (live `door_groups`) is the physical-door key.

## 1a. Per-crossing table (73 rows, local time)

| time | camera (registry device, platform) | door group | dir | outcome | vision | cam peak | case | egress crossing key (camera@time) / pee id / outcome row | person_id |
|---|---|---|---|---|---|---|---|---|---|
| 12:59:22 | Madrone G6 Entry (frigate) | front | exit | ok | 1 | 1 | A | s.madrone_g6_entry_person_count@12:59:22 / pee 9046 / attached | jaya |
| 13:00:16 | Front Door Aerial (frigate) | front | entry | clustered (member of 12:59:22) |  | 1 | D | bs.front_door_aerial_person_occupancy_2@13:00:16 / pee 9047 / attached | jaya |
| 13:01:06 | Madrone G6 Entry (unifiprotect) | front | entry | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@13:01:06 / pee 9048 / no_leg | - |
| 13:02:00 | Front Door Aerial (frigate) | front | exit | clustered (member of 13:01:06) |  | 1 | D | bs.front_door_aerial_person_occupancy_2@13:02:00 / pee 9049 / no_leg | - |
| 13:02:27 | Madrone G6 Entry (unifiprotect) | front | entry | no_frigate_event |  | 1 | D | bs.madrone_g6_entry_person_detected@13:02:27 / pee 9050 / no_leg | - |
| 13:40:36 | Garage A (frigate) | garage_a | entry | ok | 1 | 1 | A | s.garage_a_person_count@13:40:36 / pee 9051 / attached_ble | ziri |
| 14:17:23 | Garage A (frigate) | garage_a | exit | ok | 1 | 1 | A | s.garage_a_person_count@14:17:23 / pee 9052 / no_leg | - |
| 14:17:54 | Garage A (unifiprotect) | garage_a | entry | clustered (member of 14:17:23) |  | 1 | D | bs.garage_a_person_detected@14:17:54 / pee 9053 / no_leg | - |
| 14:18:39 | Garage A (unifiprotect) | garage_a | exit | ok | 1 | 2 | C | bs.garage_a_person_detected@14:18:39 / pee 9054 / no_leg | ziri |
| 14:19:04 | Garage A (unifiprotect) | garage_a | entry | clustered (member of 14:18:39) |  | 2 | D | bs.garage_a_person_detected@14:19:04 / pee 9055 / attached | jaya |
| 14:26:25 | Garage A (frigate) | garage_a | exit | ok | 1 | 1 | A | s.garage_a_person_count@14:26:25 / pee 9056 / no_leg | - |
| 14:27:01 | Garage A (frigate) | garage_a | entry | clustered (member of 14:26:25) |  | 1 | D | s.garage_a_person_count@14:27:01 / pee 9057 / no_leg | - |
| 14:27:51 | Garage A (frigate) | garage_a | exit | ok | 1 | 2 | C | s.garage_a_person_count@14:27:51 / pee 9058 / no_leg | - |
| 14:28:19 | Garage A (frigate) | garage_a | entry | clustered (member of 14:27:51) |  | 2 | D | s.garage_a_person_count@14:28:19 / pee 9059 / no_leg | - |
| 15:12:14 | Madrone G6 Entry (unifiprotect) | front | entry | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@15:12:14 / pee 9060 / attached | jaya |
| 15:23:04 | Doorbell Lite (frigate) | garage_a | exit | ok | 1 | 1 | A | bs.doorbell_lite_person_occupancy_2@15:23:04 / pee 9061 / no_leg | - |
| 15:23:35 | Garage Doorbell Lite (unifiprotect) | garage_a | exit | clustered (member of 15:23:04) |  | 1 | D | bs.doorbell_lite_person_detected@15:23:35 / pee 9062 / no_leg | - |
| 15:23:59 | Garage Doorbell Lite (unifiprotect) | garage_a | entry | clustered (member of 15:23:04) |  | 1 | D | bs.doorbell_lite_person_detected@15:23:59 / pee 9063 / abstain | - |
| 15:24:28 | Garage A (unifiprotect) | garage_a | exit | ok | 1 | 2 | C | bs.garage_a_person_detected@15:24:28 / pee 9064 / no_leg | - |
| 15:25:03 | Garage A (unifiprotect) | garage_a | entry | clustered (member of 15:24:28) |  | 2 | D | bs.garage_a_person_detected@15:25:03 / pee 9065 / abstain | - |
| 15:25:50 | Doorbell Lite (frigate) | garage_a | exit | ok | 1 | 1 | A | bs.doorbell_lite_person_occupancy_2@15:25:50 / pee 9066 / no_leg | - |
| 15:31:04 | Front Door Aerial (frigate) | front | entry | ok | 1 | 1 | A | bs.front_door_aerial_person_occupancy_2@15:31:04 / pee 9067 / no_leg | - |
| 15:31:15 | Madrone G6 Entry (frigate) | front | exit | clustered (member of 15:31:04) |  | 1 | D | s.madrone_g6_entry_person_count@15:31:15 / pee 9068 / no_leg | - |
| 15:52:52 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@15:52:52 / pee 9069 / attached | jaya |
| 16:08:03 | Front Door Aerial (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.front_door_aerial_person_detected@16:08:03 / pee 9070 / no_leg | - |
| 16:08:21 | Front Door Aerial (unifiprotect) | front | entry | clustered (member of 16:08:03) |  | 1 | D | bs.front_door_aerial_person_detected@16:08:21 / pee 9071 / no_leg | - |
| 16:14:56 | Front Door Aerial (unifiprotect) | front | exit | ok | 1 | 2 | C | bs.front_door_aerial_person_detected@16:14:56 / pee 9072 / attached | jaya |
| 16:14:58 | Madrone G6 Entry (unifiprotect) | front | entry | clustered (member of 16:14:56) |  | 2 | D | bs.madrone_g6_entry_person_detected@16:14:58 / pee 9073 / attached | jaya |
| 16:15:30 | Madrone G6 Entry (unifiprotect) | front | exit | clustered (member of 16:14:56) |  | 2 | D | bs.madrone_g6_entry_person_detected@16:15:30 / pee 9074 / attached | jaya |
| 16:16:11 | Front Door Aerial (unifiprotect) | front | exit | error |  | 2 | D | bs.front_door_aerial_person_detected@16:16:11 / pee 9075 / no_leg | - |
| 16:16:28 | Madrone G6 Entry (frigate) | front | entry | clustered (member of 16:16:11) |  | 2 | D | s.madrone_g6_entry_person_count@16:16:28 / pee 9076 / no_leg | - |
| 16:19:36 | Front Door Aerial (frigate) | front | exit | blank |  | 3 | D | s.front_door_aerial_person_count@16:19:36 / pee 9077 / no_leg | - |
| 16:20:48 | Front Door Aerial (frigate) | front | exit | error |  | 3 | D | s.front_door_aerial_person_count@16:20:48 / pee 9078 / no_leg | - |
| 16:21:20 | Madrone G6 Entry (unifiprotect) | front | exit | clustered (member of 16:20:48) |  | 3 | D | bs.madrone_g6_entry_person_detected@16:21:20 / pee 9079 / no_leg | - |
| 16:23:52 | Madrone G6 Entry (unifiprotect) | front | entry | error |  | 1 | D | bs.madrone_g6_entry_person_detected@16:23:52 / pee 9080 / no_leg | - |
| 16:24:35 | Front Door Aerial (frigate) | front | exit | clustered (member of 16:23:52) |  | 1 | D | s.front_door_aerial_person_count@16:24:35 / pee 9081 / no_leg | - |
| 16:30:44 | Garage A (unifiprotect) | garage_a | exit | ok | 2 | 3 | C | bs.garage_a_person_detected@16:30:44 / pee 9082 / no_leg | - |
| 16:31:05 | Garage A (unifiprotect) | garage_a | entry | clustered (member of 16:30:44) |  | 3 | D | bs.garage_a_person_detected@16:31:05 / pee 9083 / no_leg | - |
| 16:39:28 | Front Door Aerial (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.front_door_aerial_person_detected@16:39:28 / pee 9084 / attached | jaya |
| 16:41:01 | Doorbell Lite (frigate) | garage_a | entry | ok | 1 | 1 | A | bs.doorbell_lite_person_occupancy_2@16:41:01 / pee 9085 / attached_ble | oji_udezue |
| 17:05:07 | Doorbell Lite (frigate) | garage_a | entry | no_frigate_event |  | 1 | D | bs.doorbell_lite_person_occupancy_2@17:05:07 / pee 9086 / no_leg | - |
| 17:11:19 | Front Door Aerial (unifiprotect) | front | entry | error |  | 1 | D | bs.front_door_aerial_person_detected@17:11:19 / pee 9087 / no_leg | - |
| 17:30:13 | Doorbell Lite (frigate) | garage_a | exit | ok | 1 | 1 | A | bs.doorbell_lite_person_occupancy_2@17:30:13 / pee 9088 / no_leg | - |
| 17:30:43 | Garage Doorbell Lite (unifiprotect) | garage_a | entry | clustered (member of 17:30:13) |  | 1 | D | bs.doorbell_lite_person_detected@17:30:43 / pee 9089 / no_leg | - |
| 17:31:26 | Garage A (unifiprotect) | garage_a | exit | ok | 1 | 1 | A | bs.garage_a_person_detected@17:31:26 / pee 9090 / no_leg | - |
| 17:31:49 | Garage A (unifiprotect) | garage_a | entry | clustered (member of 17:31:26) |  | 1 | D | bs.garage_a_person_detected@17:31:49 / pee 9091 / no_leg | - |
| 17:59:51 | Front Door Aerial (frigate) | front | entry | ok | 1 | 1 | A | s.front_door_aerial_person_count@17:59:51 / pee 9092 / no_leg | - |
| 18:27:00 | Garage A (frigate) | garage_a | exit | ok | 1 | 1 | A | bs.garage_a_person_occupancy_2@18:27:00 / pee 9093 / no_leg | ziri |
| 18:43:18 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 6 | 5 | B | bs.madrone_g6_entry_person_detected@18:43:18 / pee 9094 / attached | jaya |
| 18:43:21 | Front Door Aerial (unifiprotect) | front | entry | clustered (member of 18:43:18) |  | 5 | D | bs.front_door_aerial_person_detected@18:43:21 / pee 9095 / attached | jaya |
| 18:52:54 | Doorbell Lite (frigate) | garage_a | exit | ok | 1 | 1 | A | bs.doorbell_lite_person_occupancy_2@18:52:54 / pee 9096 / no_leg | - |
| 18:59:36 | Front Door Aerial (unifiprotect) | front | exit | ok | 4 | 4 | A | bs.front_door_aerial_person_detected@18:59:36 / pee 9097 / attached | jaya |
| 18:59:50 | Madrone G6 Entry (unifiprotect) | front | entry | clustered (member of 18:59:36) |  | 4 | D | bs.madrone_g6_entry_person_detected@18:59:50 / pee 9098 / attached | jaya |
| 19:42:11 | Madrone G6 Entry (unifiprotect) | front | entry | ok | 2 | 2 | A | bs.madrone_g6_entry_person_detected@19:42:11 / pee 9099 / no_leg | - |
| 19:45:29 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@19:45:29 / pee 9100 / no_leg | - |
| 20:34:47 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@20:34:47 / pee 9101 / no_leg | - |
| 20:44:20 | Madrone G6 Entry (frigate) | front | exit | ok | 1 | 1 | A | s.madrone_g6_entry_person_count@20:44:20 / pee 9102 / no_leg | - |
| 20:57:38 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@20:57:38 / pee 9103 / no_leg | - |
| 21:03:34 | Madrone G6 Entry (frigate) | front | exit | ok | 2 | 2 | A | s.madrone_g6_entry_person_count@21:03:34 / pee 9104 / attached | jaya |
| 21:03:35 | Madrone G6 Entry (unifiprotect) | front | entry | clustered (member of 21:03:34) |  | 2 | D | bs.madrone_g6_entry_person_detected@21:03:35 / pee 9105 / attached | jaya |
| 21:12:33 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@21:12:33 / pee 9106 / no_leg | - |
| 21:15:44 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@21:15:44 / pee 9107 / no_leg | - |
| 21:20:42 | Front Door Aerial (frigate) | front | entry | ok | 1 | 1 | A | s.front_door_aerial_person_count@21:20:42 / pee 9108 / no_leg | - |
| 21:24:08 | Madrone G6 Entry (frigate) | front | exit | ok | 2 | 4 | C | s.madrone_g6_entry_person_count@21:24:08 / pee 9109 / no_leg | - |
| 21:28:01 | Madrone G6 Entry (frigate) | front | exit | ok | 2 | 1 | B | s.madrone_g6_entry_person_count@21:28:01 / pee 9110 / no_leg | - |
| 21:42:22 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@21:42:22 / pee 9111 / no_leg | - |
| 21:42:39 | Madrone G6 Entry (unifiprotect) | front | entry | clustered (member of 21:42:22) |  | 1 | D | bs.madrone_g6_entry_person_detected@21:42:39 / pee 9112 / no_leg | - |
| 21:43:06 | Front Door Aerial (frigate) | front | exit | clustered (member of 21:42:22) |  | 1 | D | s.front_door_aerial_person_count@21:43:06 / pee 9113 / no_leg | - |
| 21:43:40 | Madrone G6 Entry (unifiprotect) | front | exit | ok | 1 | 1 | A | bs.madrone_g6_entry_person_detected@21:43:40 / pee 9114 / no_leg | - |
| 21:50:21 | Garage A (frigate) | garage_a | exit | ok | 1 | 1 | A | bs.garage_a_person_occupancy_2@21:50:21 / pee 9115 / no_leg | - |
| 21:51:19 | Garage A (unifiprotect) | garage_a | entry | clustered (member of 21:50:21) |  | 1 | D | bs.garage_a_person_detected@21:51:19 / pee 9116 / no_leg | - |
| 21:51:42 | Garage A (unifiprotect) | garage_a | exit | ok | 1 | 1 | A | bs.garage_a_person_detected@21:51:42 / pee 9117 / no_leg | - |
| 21:54:39 | Garage A (unifiprotect) | garage_a | exit | ok | 2 | 2 | A | bs.garage_a_person_detected@21:54:39 / pee 9118 / no_leg | - |

## 2. Totals

Each cell is `in/out`. Vision = ok rows only (primaries). Camera peak = `camera_peak_count` summed over all 73 rows (a clustered member's peak is counted again). Crossings = number of egress crossings (73). Ledger-effective = the 46 term rows (16:08-21:55 only; a term carries the vision count when `term_source=vision`, else the camera fallback).

By hour:

| hour | vision (ok rows) | camera peak (all rows) | egress crossings | ledger-effective |
|---|---|---|---|---|
| 12:00 | 0/1 | 0/1 | 0/1 | 0/0 |
| 13:00 | 2/0 | 4/1 | 4/1 | 0/0 |
| 14:00 | 0/4 | 6/6 | 4/4 | 0/0 |
| 15:00 | 2/4 | 5/7 | 4/6 | 0/0 |
| 16:00 | 1/5 | 10/21 | 6/10 | 10/15 |
| 17:00 | 1/2 | 5/2 | 5/2 | 5/2 |
| 18:00 | 0/12 | 9/11 | 2/4 | 9/11 |
| 19:00 | 2/1 | 2/1 | 1/1 | 2/1 |
| 20:00 | 0/3 | 0/3 | 0/3 | 0/3 |
| 21:00 | 1/14 | 5/16 | 4/11 | 5/14 |
| **total** | **9/46 (net -37)** | **46/69 (net -23)** | **30/43 (net -13)** | **31/46 (net -15)** |

By physical door (door group):

| door | vision | camera peak | crossings | ledger-effective |
|---|---|---|---|---|
| front | 7/29 | 28/47 | 17/27 | 23/36 |
| garage_a | 2/17 | 18/22 | 13/16 | 8/10 |

By registry camera device (egress camera): crossings, vision in/out, camera-peak in/out, outcomes.

| camera | crossings | vision | cam peak | outcomes |
|---|---|---|---|---|
| Madrone G6 Entry (frigate) | 7 (1 in / 6 out) | 0/8 | 2/10 | {'ok': 5, 'clustered': 2} |
| Front Door Aerial (frigate) | 9 (4 in / 5 out) | 3/0 | 4/9 | {'clustered': 4, 'ok': 3, 'blank': 1, 'error': 1} |
| Madrone G6 Entry (unifiprotect) | 20 (9 in / 11 out) | 4/14 | 15/18 | {'ok': 12, 'no_frigate_event': 1, 'clustered': 6, 'error': 1} |
| Garage A (frigate) | 8 (3 in / 5 out) | 1/5 | 4/6 | {'ok': 6, 'clustered': 2} |
| Garage A (unifiprotect) | 12 (6 in / 6 out) | 0/8 | 10/11 | {'clustered': 6, 'ok': 6} |
| Doorbell Lite (frigate) | 6 (2 in / 4 out) | 1/4 | 2/4 | {'ok': 5, 'no_frigate_event': 1} |
| Garage Doorbell Lite (unifiprotect) | 3 (2 in / 1 out) | 0/0 | 2/1 | {'clustered': 3} |
| Front Door Aerial (unifiprotect) | 8 (3 in / 5 out) | 0/7 | 7/10 | {'ok': 4, 'clustered': 2, 'error': 2} |

Egress context: 101 `egress_identity_outcome` rows on 11-14: 81 non-ambiguous (35 entry, 46 exit; peak sum 55/74; 8 before the shadow switch came on at 12:48:34) and 20 `direction_ambiguous`. Shadow rows = 73 = the 81 minus the 8 pre-switch; no non-ambiguous crossing after switch-on lacks a row. Identity: 17 of 73 shadow rows carry a bus `person_id` (egress outcome rows: 15 attached, 2 attached_ble, 54 no_leg, 2 abstain); 19 pee rows carry one (2 backfilled later, 14:18:39 and 18:27:00 ziri).

Vision call latency on ok rows: p50 9.7 s, p90 18.6 s, max 38.7 s (n=41).

### 2a. Reconciliation against the guest-count story

No ground-truth guest count exists for 11-14 (no operator label). This compares instruments.

Census side (verified): `sensor.universal_room_automation_persons_in_house` history hit 10 at 16:26:02, 16:43:36 and 16:50:23. `census_snapshots` (zone house) max total 10 on 11-14: 16:43:35 and 16:50:23 are 4 identified + 6 unidentified, `frigate_count` 10, `unifi_count` 0 and 3 (confidence medium/high, agreement close/both_agree). So the peak is interior-camera bodies. Other highs: 16:29:02 total 9; 18:36 total 8; 19:18:56 total 9 (3 + 6, frigate 9).

| window | census | door crossings in/out | ledger-effective in/out | vision (ok) in/out |
|---|---|---|---|---|
| 16:08-16:55 | 3 -> 10 -> 6 | 6 / 10 | 10 / 15 | 1 / 5 |
| 18:00-18:45 | 4 -> 8 -> 3 | 1 / 2 | 5 / 6 | 0 / 7 |
| 19:15-19:25 | 3 -> 9 -> 3 | 0 / 0 | 0 / 0 | 0 / 0 |
| 16:08-22:00 | 3 .. 10 .. 1-3 | 18 / 31 | 31 / 46 | 5 / 37 |

Where they disagree:
1. **Sign.** Every instrument nets negative (vision -37, camera peak -23, crossings -13, ledger-effective -15). With 1-3 people in the house at both ends of the day, that is only possible if entries were missed or directions were wrong.
2. **No arrival burst.** Census goes 3 -> 10 in 18 minutes from 16:08; the crossings in that span (camera terms) are +6 in against -12 out. The door tally contains no +7.
3. **19:18 census rise with zero door crossings** (19:15-19:25).
4. **18:43:18**: vision says 6 people left (camera 5, case B), about 6 minutes after the census had already fallen 8 -> 3 (18:37).
5. **Direction pairs.** 21 of the 25 clustered rows are the opposite direction to their primary and carry an identical camera peak (an exit then an entry, or the reverse, 1-60 s apart). Vision's own description of the 16:14:56 "exit" is "one person walks toward the door". Whether this is the tracker mislabelling one pass or real out-and-back is not established here; each pair becomes +n and -n in the ledger.
6. **Skipped ambiguous crossings** (20 on the day, 10 after the ledger started) carry no direction and no term (section 6).

Inference (not a replay): had the ledger been anchored at L = R near 3 at 16:08, exits exceeding entries by 15 would have clamped L at 0 repeatedly, so `guest_vis = max(0, L - R)` would have read ~0 through the party where the census read 6. The P2-D6 dark-ledger replay is the instrument that would settle this; it was not run.

Vision counting itself is not the failure: the 8 ok-row disagreements are 6 camera-higher (4 of the 6 are camera 2 vs vision 1 on people walking past) and 2 vision-higher (18:43:18, 21:28:01). The weak link is the direction stream and coverage, not the head count on a matched clip.

## 3. Errors

| time | event camera | direction | cam peak | latency | ledger term |
|---|---|---|---|---|---|
| 16:16:11 | madrone_g6_entry | exit | 2 | 2.13 s | camera n=2 |
| 16:20:48 | front_door_aerial | exit | 3 | 2.15 s | camera n=3 |
| 16:23:52 | madrone_g6_entry | entry | 1 | 2.25 s | camera n=1 |
| 17:11:19 | front_door_aerial | entry | 1 | 2.30 s | camera n=1 |
| blank 16:19:36 | front_door_aerial | exit | 3 | 5.13 s | camera n=3 (frame_counts [0], desc "No people are visible.") |

- All four errors returned in ~2.1-2.3 s (ok calls take 9.7 s median), the signature of a service call that raised at once. The row stores no error text. **Cause: unknown.** The raising path logs at INFO only (`perimeter_enrichment.py:452-457`), and HA logs are not retained on the box (`/config/home-assistant.log*` empty, no `journalctl`), so the message cannot be recovered.
- **Retry: none.** `crossing_vision.py` has no retry; each of the 73 crossing keys has exactly one row; the matched event is stamped `analysed_by` at schedule time (:710) so a later crossing on the same event clusters instead of re-calling. 3 of the 4 errors fall within 18 minutes of the 16:06:48 restart (16:16-16:24); the 4th is 17:11; none in the 23 calls after 17:11. A transient service condition is plausible and unproven.
- The blank (16:19:36) is a genuine-looking miss: the camera peak says 3 people; the sampled frames showed none. One of 46 calls.
- 2 `no_frigate_event` (13:02:27 Madrone G6 Entry entry; 17:05:07 Doorbell Lite entry): no call. Their ledger term, where one existed (17:05:07), is the camera fallback.
- Error rate: 4/46 calls = 8.7% (trip-wire `crossing_vision_errors` threshold 25% of >=8 calls, `PLANNING_crossing_vision.md` §6): did not page.

## 4. Ledger

- 46 `crossing_vision_ledger` rows on 11-14 from 16:08:03 to 21:54:39, plus 2 on 11-15 (13:34). All are `kind=term`, `reason=unknown`, `applied=false`, `l_before/l_after/residue` null. Terms: exits 20 vision (27 people) + 8 camera (19); entries 4 vision (5) + 14 camera (26). Zero anchor, lift or reconcile rows exist in the table, ever.
- **State over the day: unknown, boot to 22:02:18, then unknown again** (HA restarted at 22:02:18, RAM ledger lost). Live now: `crossing_ledger` = `{state: unknown, unknown_reason: boot, L: null, last_anchor: null}`.
- **Known L on 11-14: never.** Unknown reasons: `unknown` on every row; `boot` live.
- **Last empty-house anchor before 11-14: none exists.** The ledger code went live at the 16:06:48 restart (first row 16:08:03). The last genuinely empty house was AWAY 09:51:39-11:31:57 CST on 11-14 (`house_state_log`; `census_snapshots` total 0 from 09:52:09 to 11:29:14), before the ledger existed. From 16:06 to 22:02 the house state was guest and census total was >= 1, so there was no empty window to anchor on (the anchor needs 900 s of zero bodies, no held Tier-1 input and no entry term, plan P2-D2 step 2).
- **Live blockers now (13:50 CST 11-15)**: house AWAY since 13:43:29, yet `crossing_ledger.held` lists mediaroom matter occupancy (on continuously since at least 06:00), mediaroom meross presence_motion (flapping) and upguestroom hobeian presence_2 (on/off all morning). Held inputs block the anchor by design (plan :218-228), so the ledger may stay unknown through this empty window. `crossing_ledger_anchor_zero` (LOW, 172800 s) is the page for that.
- The plan's own sweep measured about 4 empty episodes a week at 900 s (`AUDIT_ledger_checkpoint_window_sweep_2026_11_14.md`, quoted at `PLANNING_crossing_vision.md:243-245`), so anchors are rare by design; each needs a clean Tier-1 set, and today's held set is the thing to look at.

## 5. Census contribution

**Plainly: no. Vision is not contributing to any displayed or acting census number today.**

Readers of the awareness view (F2-A):
- Only `sensor.ura_census_people_around` / `sensor.ura_census_guests_around` (`sensor.py:4195-4290`, via `presence.get_house_census(cls="display")` :4224). Nothing reads them: no reference in integration code (grep), `automations.yaml`, or lovelace storage on the mount.

Readers of the trust view (F2-T): `aggregation.py:6679,6708`; `sensor.py:5342,5357`; `binary_sensor.py:1953,2001`; `binary_sensor.py:2220,2270` (phone-left-behind, `cls="house_state"`, which `view_for_class` maps to trust because `house_state` is not in `CROSSING_VISION_CONSUMER_CLASSES = {display}`, `const.py:6641`; `census_view.py:58-80`). Presence/AWAY reads the `SIGNAL_CENSUS_UPDATED` payload, which carries no awareness keys.

Producer chain: `camera_census.py:6829 _compute_awareness` -> `:6880 _ledger_tick` -> `crossing_vision.py:1080 census_tick` -> `deconflict_house` (`census_deconflict.py:77-121`). Rule: ledger unknown -> `guest_vis` None -> case D, `aware = guest_cam`. Even with a known ledger, `CROSSING_VISION_AWARENESS_VISION_LEADS = False` (`const.py:6685`) forces `aware_guests == guest_cam` in cases A-C.

`switch.ura_crossing_vision_census_authority` (on since 16:06:48 11-14; "Vision Assisted Census", `switch.py:1103`): it only chooses which view the display class reads (`census_view.py:75-78`). It changes no live entity value; awareness == trust either way.

Live evidence, 11-14 recorder history, trust vs awareness (1-minute grid 16:07-24:00, 473 samples): **0 mismatches** for total (`persons_in_house` vs `ura_census_people_around`) and for guests (`unidentified_persons_in_house` vs `ura_census_guests_around`); both hit 10 at 16:26:02, 16:43:36, 16:50:23 in the same second. The awareness sensors enter the recorder at 16:06:57. Selected points (HH:MM identified / trust total / trust guests / aware total / aware guests), full change list in the JSON:

| time | identified | trust total | trust guests | aware total | aware guests |
|---|---|---|---|---|---|
| 16:08 | 3 | 3 | 0 | 3 | 0 |
| 16:16 | 3 | 5 | 2 | 5 | 2 |
| 16:26 | 3 | 8 (10 at 16:26:02) | 5 | 8 | 5 |
| 16:29 | 3 | 9 | 6 | 9 | 6 |
| 16:43 | 4 | 6 (10 at 16:43:36) | 2 | 6 | 2 |
| 16:50 | 4 | 7 (10 at 16:50:23) | 3 | 7 | 3 |
| 18:36 | 3 | 8 | 5 | 8 | 5 |
| 19:19 | 3 | 9 | 6 | 9 | 6 |

The awareness sensors' attributes (`count_provenance`, `aware_agreement`, `vision_status`, `ledger_state`) are unrecorded (`sensor.py:4210`), so no case/provenance history exists for 11-14. Live now: `count_provenance camera`, `aware_agreement single_source`, `vision_status unknown_ledger`, `ledger_state unknown`.

Next promotion step and gate (`PLANNING_census_deconfliction.md` §3.2): the active set is `{display}` (rung 1) and the value flip F-LEAD (rung 0, `CROSSING_VISION_AWARENESS_VISION_LEADS`) is the first step that makes the awareness view differ from trust; notification (F-NOTIFY, legal, inactive) is the first class promotion. F-LEAD gate: bars a, b, d, e (drift residue 0 on >=80% of >=10 anchors; arrivals >=90% matched; false guest <=2%; ledger known >=90% of the time) AND >=100 graded crossings over >=7 days incl >=10 with a non-resident, exact >=95% overall / >=90% night per door, vision wins >=80% of B/C disagreements, false guest <=2%, healthy >=95%, then the operator Tier-3 checkpoint. Measured today against that gate: known share 0%, anchors 0 (need 10), graded crossings 0 (grading is P2-D10, no `crossing_vision_grade` rows), no arrival-record rows (`crossing_vision_arrival` has 0 rows, P2-D9 not live). The only comparison available, vision vs camera peak on matched clips, is 33/41 = 80.5% and is not graded truth.

## 6. Skipped crossings

20 egress crossings on 11-14 were `direction_ambiguous` (7 before the shadow switch at 12:48:34, 13 after; 10 after the ledger started at 16:08). By device: Doorbell Lite (Frigate) 6, Garage A (Frigate) 4, Madrone G6 Entry (UniFi) 3, Front Door Aerial (UniFi) 3, Madrone G6 Entry (Frigate) 2, Garage A (UniFi) 1, Garage Doorbell Lite (UniFi) 1. Hours (local): 07 1, 08 1, 09 1, 11 4, 12 1, 13 1, 15 1, 16 2, 17 1, 19 1, 20 3, 21 3. Vision-covered non-ambiguous crossings had no other skip: no skipped_cap, no skipped_busy, no row without a call-path outcome.

Skip condition: `crossing_vision.py:617-618`, `if direction not in ("entry", "exit"): return` inside `_on_egress_event` (:614). The skip is silent: no row, no counter, no ledger term (so ambiguous crossings are an uncounted blind spot in every table above).

Plan: INV-SCOPE "never an ambiguous crossing" (`PLANNING_crossing_vision.md:69-70`), INV-ADDITIVE "Ambiguous: bus key None, no row, no sample" (:72-73), P2-D2 step 3 "`ambiguous` no term" (:253), "Vision direction never used" (:252), non-goal "vision direction" (:489). The plan states the rule and does not give a separate reason; the evident one (inference, not quoted) is that a ledger term needs a validator direction to add or subtract, and vision must not supply direction.

## Falsification and limits

- "Awareness differs from trust somewhere" would disprove the no-contribution claim: searched the 473-sample grid and the change lists; none. "A ledger row with `l_after` non-null" would disprove "never known": 0 of 48.
- The pee link is nearest-match (no shared key); person_id columns drawn from the bus where present. The pee link is a heuristic (unique key absent); counts of egress crossings come from the exact-key `egress_identity_outcome` join, not from pee.
- Sums of `camera_peak` over all rows count clustered members again; the "same 41 ok rows" total is the like-for-like comparison with vision.
- Cause of the 4 errors, mechanism of the direction pairs, and any ground-truth guest count are unknown.

Files: `/Users/okosisi/Code/universal-room-automation/.claude/tmp/vision_report_1114.json`, scripts `/Users/okosisi/Code/universal-room-automation/.claude/tmp/vbuild.py`, `vfinal.py`, `vextra.py`, `vseries.py`, `vwrite.py`, `vmd.py`.
