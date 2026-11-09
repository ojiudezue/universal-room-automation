# AUDIT: guest-mode split, D0 measurement probe

**Plan:** `docs/planning/PLANNING_guest_mode_split_2026_11.md` rev 2 (commit e4aba26d), section D0 and 5.0. Plan review 1: `docs/reviews/code-review/guest_split_plan_review_1.md`.
**Run:** prober (Sonnet 5.5), read-only, 2026-11-09 02:14-02:50 CST (`date`: Mon Nov 9 02:14:43 CST 2026; recorder `NOW` = 1794212327 = 2026-11-09 08:18:47Z). Not committed. No HA state changed.
**Read first:** the plan sections 0-5 and D0, plan review 1 in full, `docs/planning/AUDIT_guest_mode_fp_2026_10_17.md`. The HVAC and presence state-of-play docs were NOT re-read for this probe (no HVAC or presence code is proposed or changed here; the probe only reads recorded data and the gate code at `presence.py:5998-6070`, `:6586-6670`). Memory read: `project_operator_travel_2026_10_15.md`.

## VERDICT

**D0 GATE: STOP-PAGE-OPERATOR** (both stop-clause legs are triggered or conditionally triggered; details in section 7).

Short answer:
1. The camera leg almost never co-occurs with a real guest-room entry. Of the 35 GUEST entries in the proposed stay (09-27 to 10-17), the new rule room AND (camera OR WiFi) keeps **0 at L=30 min, 1 at L=60, 2 at L=120 and 2 at L=240**, covering **1 of 16 entry-days (6 percent)** against the 80 percent bar. With the WiFi leg off (it must be, section 4) the rule removes 33-35 of 35 stay entries.
2. Outside the stay there is almost nothing to remove: **zero GUEST entries from 10-18 to 11-08 (22 days)**, and only a 4-entry cluster 09-16 to 09-18 (cluster B, label pending) plus two entries on 09-10 itself (the v5.79.0 deploy day; two more on 09-09 precede it). So false room-only entries outside known visits are about zero (0 definite; at most 4 if cluster B is not a visit, and 3 of those 4 would have been kept at L=240 by the camera leg).
3. The WiFi leg cannot be turned on: in the last 7 days (no guest home) the production `wifi_guest_floor` is at least 1 for 14.5-23.2 h of every day, and the per-device replay finds sustained "new" devices on every day at S=10 and S=30 min (6 of 7 days at S=60 and S=120). Several are resident devices that no filter links (section 4.4).
4. Recommendation under the plan's own stop clause: **ship D2 (`visitors_present`) only; park D3 with the revival trigger "a room-alone GUEST entry on a day the operator confirms no guest".** The operator decides.

## 0. Sources, windows, limits (actual oldest rows)

| Source | Access | Oldest row used | Newest | Note |
|---|---|---|---|---|
| URA DB `house_state_log` | `ssh ha`, sqlite `mode=ro` on `/config/universal_room_automation/data/universal_room_automation.db` (live file, no copy made) | 2026-03-12T05:20:40Z (8,587 rows) | 2026-11-09T04:00:11Z | timestamps are naive UTC (10-17 21:06:39 matches the 10-17 audit's 21:06Z). Local date = UTC-5 to 11-01 07:00Z, UTC-6 after |
| URA DB `occupancy_events` | same | 2025-11-20 | 2026-11-08 | GB1 = entry `01KE2CP30H1251F10K5R1YJRCC`, GB2 = `01KCYSBVA2RMB5C3F1Z90F9X72` (from `.storage/core.config_entries`, read-only) |
| URA DB `census_snapshots` | same | 2026-08-10T08:30Z (zone `house`, 97,948 rows; gaps: 65,723 <=90 s, 32,012 <=300 s, 212 <=1800 s) | 2026-11-09 | zone `house` is the Path A feed (`camera_census.py:1854` `house_result.unidentified_count`) |
| URA DB `person_entry_exit_events` | same | 2026-03-04 | 2026-11-09T00:13Z | used for blank-person crossings only |
| URA DB `unknown_devices` | same | 0 rows (confirmed again) | | no use as Q0 evidence |
| HA recorder `home-assistant_v2.db` | `ssh ha`, `mode=ro`, 10.5 GB | window start 2026-11-01 ~23:23 CST (7 days + 3 h) | 2026-11-09 02:18 CST | WiFi questions only; no October WiFi history exists |
| Scripts | `scratchpad/d0e.py` (house-state, rooms, Path A), `q1.py`+`an2.py` (recorder device trackers), `q2.py`+`an3.py` (`wifi_guest_floor`), `q3.py` (scanner, resident locations), `an1.py`, `tables.py` | | | all in `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad`. The plan names `scripts/probes/guest_split_d0.py`; I did not write into the repo (read-only brief). A 70 MB raw recorder extract was deleted after analysis |

Method notes (limits that bear on the conclusions):
- **Room leg** = raw `occupancy_events` entry/exit pairs on GB1/GB2. A GUEST entry is matched to the room run whose age at the entry is closest to 30 min (the table in section 2 gives the matched run's age at each entry). This is the same structure as `_guest_room_gate_armed` (first_seen + 30 min); it does not replay the known-person (BLE) cancel, so it can only over-count room runs, not entries.
- **Every GUEST row in `house_state_log` since 08-25 has confidence 0.9.** `presence.py:6645-6650` gives 0.9 only for room-without-Path-A and 0.95 for room+Path A on the entry tick. So at the instant of entry the camera leg was never armed on any of the 104 runs since 08-25. This is an independent confirmation of the replay below.
- **Path A replay** (`presence.py:5998-6070`): census `house` rows with `unidentified_count>0` and confidence rank >= medium (live `guest_mode_require_confidence`=medium, `guest_mode_persistence_seconds`=300), continuous (row hold capped 300 s, gaps >120 s split), "fires" from run-start+300 s to run-end, counted only if the house state at run-start+300 s is home_day/evening/night (Path A is not evaluated in other states, `presence.py:6575-6609`). The latch test: cam is true at time t if t is within [fire start, fire end + L].
- **Restarts:** the replay uses `house_state_log`/`census_snapshots`, which survive restarts; the recorder window had 11 HA starts (11-02 06:57 CST to 11-08 13:54 CST).
- **Not replayed:** the hold rule (room OR wifi) and the known-person cancel are not simulated; counts are of entries.

## 1. Q0: the October stay (for operator confirmation)

Evidence per day is in section 6. The proposed dates, with the evidence for each edge:

| Item | Proposed | Evidence (source) |
|---|---|---|
| **Stay start** | **2026-09-27 (primary), possibly 09-25** | Guest-room occupancy is below 70 min/day on every day 09-19 to 09-24 (0-33 min) and is 12 min on 09-26, then 149 min on 09-25 (one 33-min GB2 run, one 8-min GUEST entry at 11:01 CDT) and **247-730 min/day on every day from 09-27 to 10-17 except 10-14 and 10-15** (section 6; `occupancy_events`). First stay-day GUEST entry: 09-27 13:14 CDT (`house_state_log`), 44 min |
| **Stay end** | **2026-10-17 (evening)** | Last GUEST entry 10-17 16:06 CDT (46 min); last GB2 runs 10-17 (three runs ending 16:47, 18:13 and 18:52 CDT); 10-18 has 39 min and 10-19 14 min of guest-room occupancy, then near zero to 11-08. The 10-17 audit found the house empty indoors 06:50-15:12 CDT and the guest-candidate phone off WiFi |
| **Gap inside the stay** | 10-14 and 10-15 | 0 and 48 guest-room minutes and 0 GUEST entries, **although** memory `project_operator_travel_2026_10_15.md` records a guest at home with Jaya from the morning of 10-14. So the room leg does not even see this guest on those two days (where she slept is unknown; sensor outage not excluded: I did not check GB sensor availability) |
| Length | 21 days (09-27 to 10-17), 23 if 09-25 | Fits "3-4 weeks" at the short end only |
| **Alternative / earlier cluster B** | 09-15 to 09-19 | GB2 occupied 929 min on 09-15 (one 15-hour run 09-15 17:36 to 09-16 08:58 CDT, no GUEST entry), then 9 and 5 Path A fires on 09-16 and 09-17 (among the highest pre-stay days), 4 GUEST entries 09-16 to 09-18, then a quiet 09-19 to 09-24. Looks like a separate short visit, or the start of the stay with the guest away 09-19 to 09-26. **Operator to say which** |
| Not found | after 10-18 | zero GUEST entries 10-18 to 11-08 (22 days); one 37-min GB1 run on 10-23 16:21 CST that did not enter GUEST |

**Q0 questions for the operator:** (1) Start 09-27, 09-25, or 09-15? (2) End 10-17? (3) Was the guest in the house on 10-14 and 10-15, and where did she sleep? (4) Was 09-15 to 09-19 a visit (cluster B)?

GB2 scanner (plan section 1.3): **no evidence it existed on any measured day.** Live config still has GB2 `scanner_areas: ['guest_bedroom_2_closet']`; in the last 7 days no resident's `sensor.universal_room_automation_<name>_location` was ever "Guest Bedroom 2" (Jaya: Guest Bedroom 1 x9, Guest Bedroom 2 Bathroom x16; Ziri: GB1 x5, GB2 Bathroom x4; Ezinne: GB2 Bathroom x1; recorder, 11-02 to 11-09) and the device registry has no BLE scanner/proxy device in an area named Guest Bedroom 2 (Shelly relays only). The FP numbers below therefore all predate the scanner.

## 2. Q2: every GUEST entry, 09-09 to 10-17 (and none after)

Count of GUEST *runs* in `house_state_log` since 08-25: 104. Since the v5.79.0 fix (09-10): 44 runs listed below (the first four straddle the 09-09/09-10 deploy day and are labelled boundary). **No run after 10-17.** Columns: local time of entry, length, house state before->after, room leg (room and its occupied age at entry), my provisional label by operator-confirmed dates (all "real/FP" cells blank for the operator), and whether the camera leg was true at entry for latch L = 30/60/120/240 min.

| entry (local) | min | states | room leg | label by date | cam@30/60/120/240 | real / FP (operator) |
|---|---|---|---|---|---|---|
| 09-09 19:31 | 25 | home_evening->arriving | GB2 (30 min) | boundary (v5.79.0 day) | -/-/-/- | |
| 09-09 21:02 | 120 | home_night->arriving | GB2 (121 min) | boundary (v5.79.0 day) | -/-/-/- | |
| 09-10 14:17 | 109 | home_day->away | GB2 (30 min) | boundary (v5.79.0 day) | -/-/-/- | |
| 09-10 16:13 | 13 | home_day->home_day | GB2 (147 min) | boundary (v5.79.0 day) | -/-/-/- | |
| 09-16 20:50 | 9 | home_evening->home_night | GB2 (30 min) | cluster B (?) | -/-/-/Y | |
| 09-16 21:25 | 6 | home_night->home_night | GB2 (30 min) | cluster B (?) | -/-/-/Y | |
| 09-17 17:25 | 5 | home_day->home_day | GB2 (30 min) | cluster B (?) | -/-/-/Y | |
| 09-18 18:06 | 46 | home_evening->home_evening | GB2 (30 min) | cluster B (?) | -/-/-/- | |
| 09-25 11:01 | 8 | home_day->home_day | GB2 (30 min) | stay (edge) | -/-/Y/Y | |
| 09-27 13:14 | 44 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 09-28 08:00 | 9 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 09-29 09:29 | 48 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 09-29 21:25 | 159 | home_night->home_night | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 09-30 06:03 | 50 | home_day->home_day | GB2 (47 min) | stay (primary) | -/-/-/- | |
| 09-30 07:22 | 29 | home_day->arriving | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 09-30 10:15 | 22 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 10-02 06:03 | 13 | home_day->home_day | GB2 (36 min) | stay (primary) | -/-/-/- | |
| 10-02 06:47 | 73 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 10-02 08:37 | 34 | home_day->home_day | GB2 (34 min) | stay (primary) | -/-/-/- | |
| 10-04 06:03 | 101 | home_day->home_day | GB1 (12 min) | stay (primary) | -/-/-/- | |
| 10-04 07:48 | 15 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-04 08:49 | 26 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 10-05 08:35 | 10 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-05 15:03 | 12 | home_day->home_day | GB1 (31 min) | stay (primary) | -/-/-/- | |
| 10-05 21:55 | 14 | home_night->home_night | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-06 06:55 | 18 | home_day->home_day | GB1 (31 min) | stay (primary) | -/-/-/- | |
| 10-06 08:15 | 12 | home_day->away | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-06 09:04 | 6 | home_day->home_day | GB2 (4 min) | stay (primary) | -/-/-/- | |
| 10-06 09:30 | 44 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 10-08 17:08 | 6 | home_day->home_day | GB1 (30 min) | stay (primary) | -/Y/Y/Y | |
| 10-08 17:51 | 22 | home_day->home_evening | GB1 (35 min) | stay (primary) | -/-/Y/Y | |
| 10-09 06:36 | 7 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-09 07:18 | 38 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-09 09:06 | 32 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-09 10:06 | 49 | home_day->home_day | GB1 (90 min) | stay (primary) | -/-/-/- | |
| 10-10 06:03 | 8 | home_day->home_day | GB1 (37 min) | stay (primary) | -/-/-/- | |
| 10-10 08:00 | 15 | home_day->home_day | GB2 (31 min) | stay (primary) | -/-/-/- | |
| 10-10 09:10 | 6 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 10-11 08:42 | 38 | home_day->home_day | GB1 (31 min) | stay (primary) | -/-/-/- | |
| 10-12 07:55 | 67 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-12 09:35 | 11 | home_day->home_day | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-13 06:59 | 11 | home_day->away | GB1 (30 min) | stay (primary) | -/-/-/- | |
| 10-16 07:00 | 16 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |
| 10-17 16:06 | 46 | home_day->home_day | GB2 (30 min) | stay (primary) | -/-/-/- | |

Summary by segment (entries / entry-days):

| Segment | Entries | Entry-days | Note |
|---|---|---|---|
| Boundary 09-09 to 09-10 (v5.79.0 day) | 4 | 2 | pre-fix day; not counted as post-fix FPs |
| Cluster B 09-16 to 09-18 | 4 | 3 | label pending |
| Stay edge 09-25 to 09-26 | 1 | 1 | 09-25 11:01, 8 min |
| **Stay primary 09-27 to 10-17** | **35** | **16** | room-run age at entry is 30-37 min for 30 of 35; outliers 47, 90 (re-arm after a quiet break) and 12 and 4 min (run-matching imprecision: the live `first_seen` can predate my raw occupancy pair) |
| Post-stay 10-18 to 11-08 | **0** | 0 | 22 days |

Room runs >=30 min (raw pairs) and whether a GUEST entry occurred in them: pre-stay 09-10 to 09-24: 6 runs, 5 with an entry; **stay: 67 runs, 33 with an entry**, 34 without (BLE-known occupant, house not in HOME_*, or run while already GUEST); **post-stay 10-18 to 11-08: 1 run (GB1 10-23 16:21 CST, 37 min), 0 entries.** In the last 7 days Jaya was located in Guest Bedroom 1 nine times and produced no GUEST (BLE cancel works for GB1).

The 104-run total since 08-25 includes the pre-v5.79.0 population (08-25 to 09-10: 60 runs, `deferred_retry`/`occupancy_change`/`periodic` triggers, all conf 0.9) that GUEST-FP-RESIDUALS-1 measured collapsing after 09-10. Those are not used as evidence here.

## 3. Q3: replay of the new rule (room AND (cam OR wifi)), WiFi off

"Kept" = the camera leg was true at entry for latch L. WiFi cannot rescue recall (section 4). Entry-day is kept if at least one entry that day survives.

| Segment | Entries | L=30 kept | L=60 kept | L=120 kept | L=240 kept | Entry-days kept @60 / @120 / @240 | GUEST minutes kept @240 |
|---|---|---|---|---|---|---|---|
| **Stay primary 09-27..10-17** | 35 | 0 | 1 | 2 | 2 | 1/16 / 1/16 / 1/16 | 28 of 1113 |
| Stay wide 09-25..10-17 | 36 | 0 | 1 | 3 | 3 | 1/17 / 2/17 / 2/17 | 36 of 1121 |
| Cluster B 09-15..09-24 | 4 | 0 | 0 | 0 | 3 | 0/3 / 0/3 / 2/3 | 20 of 66 |
| 09-10..09-24 (all pre-stay incl. boundary) | 6 | 0 | 0 | 0 | 3 | 0/4 / 0/4 / 2/4 | 20 of 187 |
| Post-stay 10-18..11-08 | 0 | - | - | - | - | - | - |

- **Real entries lost (stay, if the operator labels all stay entries real):** 35 of 35 at L=30, 34 at L=60, 33 at L=120/240. The 80 percent entry-day bar needs 13 of 16 entry-days; the best any L reaches is 1 of 16.
- **False entries removed:** none can be counted as false yet (labels blank). Outside the stay: 0 after 10-18; 6 before the stay of which at most 4 are in cluster B (3 of them *kept* by the camera leg at L=240, so the rule would remove only 1 of cluster B at L=240 and 4 at L<=120).
- **Stay nights that lose GUEST (local 22:00-06:00):** GUEST overlapped only **2 of the 21 stay nights**: 09-29 (21:25 start, 159 min, camera false) and 10-05 (21:55 start, 14 min, camera false). Both would be lost. On the other 19 stay nights GUEST was already absent at night under the current rule, so those nights are already SLEEP/home_night (and already take the CRITICAL exterior-person severity); the new rule adds NM severity change on 2 nights only.
- **Latch recommendation:** no L in {30,60,120,240} reaches 80 percent. Smallest L with the best attainable result is 60 (1/16 entry-days, no better at 120 or 240 for the primary stay).

Note on the 10-08 17:08 entry (the only L=60 hit): the cam run that preceded it is the only one in the stay that overlapped a guest-room run, so even the "kept" entries are coincidental, not systematic.

## 4. Q1: guest-WiFi devices, last 7 days (recorder, 11-02 to 11-09, no guest home)

Recorder retention is 7 days (`configuration.yaml` `purge_keep_days: 7`, per plan review F3); October is unrecoverable. The 11-01..11-08 window has **zero GUEST ticks** (F-5 audit, plus section 2: no run after 10-17), so every device that would set `wifi` here is a false positive for a guest-presence meaning.

### 4.1 Population

41 router `device_tracker` entities were on essid `Revel` in the window: 16 infrastructure (hostname prefix filter), 5 hostless, 19 pass filters 1-3 ("CANDIDATE", mostly Apple Watches and phones/laptops), 1 iPad (tablet filter). My replay applies the hostname and tablet filters and the direct person-tracker exclusion only; it does NOT have the device-registry sibling and MAC cross-reference (the three-layer Filter 4) that production applies, because the person trackers here are not router trackers and I did not expand the device registry. The production-faithful measure is the recorded `wifi_guest_floor` (4.2).

### 4.2 Production `wifi_guest_floor` (all filters, 4 h recency), `sensor.universal_room_automation_persons_in_house` attribute

| Day (CST) | covered h | hours with floor>=1 | min | max |
|---|---|---|---|---|
| 11-02 | 23.8 | 23.2 | 0 | 6 |
| 11-03 | 22.9 | 20.1 | 0 | 5 |
| 11-04 | 24.6 | 19.7 | 0 | 5 |
| 11-05 | 25.2 | 15.9 | 0 | 4 |
| 11-06 | 22.2 | 14.5 | 0 | 4 |
| 11-07 | 24.4 | 23.0 | 0 | 5 |
| 11-08 | 25.9 | 17.3 | 0 | 5 |

Runs of floor>=1 lasting at least S minutes (55 runs total): S=10: 35, S=30: 23, S=60: 21, S=120: 19; the longest run is 13.2 h. Days with at least one such run: all 7 at every S. (The floor includes the 4 h recency window, so it is an upper bound on the new "sustained new device" leg; the replay below is the closer analog.)

### 4.3 Per-device replay of "live not_home -> home edge, then continuously home >= S" (no boot edges: 0 edges fell within 180 s of an HA start)

Devices per local day that would set `wifi` (with-host / hostless):

| S | 11-02 | 11-03 | 11-04 | 11-05 | 11-06 | 11-07 | 11-08 | days with >=1 |
|---|---|---|---|---|---|---|---|---|
| 10 min | 8 / 1 | 4 / 2 | 4 / 1 | 4 / 1 | 4 / 1 | 3 / 0 | 2 / 0 | 7 of 7 |
| 30 min | 6 / 1 | 4 / 2 | 2 / 1 | 4 / 1 | 4 / 1 | 3 / 0 | 1 / 0 | 7 of 7 |
| 60 min | 5 / 1 | 4 / 2 | 1 / 1 | 4 / 1 | 4 / 1 | 3 / 0 | 0 / 0 | 7 of 7 (6 of 7 with-host only) |
| 120 min | 4 / 1 | 3 / 2 | 1 / 1 | 4 / 1 | 3 / 1 | 3 / 0 | 0 / 0 | 6 of 7 (11-08 is the only zero day) |

No sustain value in {10,30,60,120} reaches "wifi false on every day". **GO-WIFI-OFF** applies. I did not test S > 120 min; at S=120 a device-level zero day exists for 11-08 only.

### 4.4 Resident-coincident devices (unlinked resident phones/computers)

Device live edges within +-120 s of a `person.*` not_home->home transition (the criterion D0 Q1 asks for) are present on every candidate that sets `wifi` for long:
- `device_tracker.unifi_default_0e_a8_a4_be_6d_7e` (hostname "MacBookAir"): edges 11-02 21:05, 11-03 22:37, 11-05 22:41, 11-06 22:06, 11-07 23:44 CST, each within 60 s of Jaya's (and Ezinne's/Oji's) arrival; episodes 540-1594 min. **This is the same device the 10-17 audit reported as a guest-candidate ("home since 20:12:52Z, same minute Jaya arrived", owner unknown).** The coincidence repeats 5 of 5 times; it is almost certainly a resident device (Jaya's) that no filter links, so the 10-17 "MacBookAir edge" is not evidence of a guest.
- `device_tracker.unifi_default_02_f0_d7_b5_e4_cd` (hostless, private MAC 02:f0:d7:b5:e4:cd): 6 episodes in 6 days, longest 651 min; 2 of 6 edges within 1 min of Jaya's arrival (11-04 22:52, 11-05 22:40). The 10-17 audit called this "the best guest-phone candidate" (seen 10-14 to 10-16). Same caveat: it follows Jaya in this window.
- `device_tracker.iphone_4` (MAC 06:7b:aa:d0:af:aa): edges coincide with Ezinne/Jaya/Ziri/Oji arrivals on 11-06 22:06 and 11-07 10:33. The 10-17 audit also listed it as home 10-14 to 10-16.
- Apple Watches (hostname "Watch", about 10 distinct private-MAC entities, with 1-30 episodes each): flap in 6-30 min episodes; they pass filter 1-3 (no prefix) and are the bulk of the sustained "new" devices.
- Hostless OUI devices (4c:5f:72, 0c:47:c9, 4c:53:fd, 5c:e7:53): present 5.6-7 days, IoT-like.

Producer problem for the leg: a resident's private-MAC device that is not linked to a `person` entity re-edges with the resident and the filters have no stable identity to exclude it. Producer check: D1's "new and sustained" leg is fed by the same filters (`camera_census.py:6001-6140`); the production floor shows the filters already pass those devices.

## 5. Q4: camera leg alone

Path A fires (HOME_* states, 300 s persistence, medium+ confidence, census `house` zone):

| Window | Days | Days with a fire | Fires | Per day | Median fire length | Longest |
|---|---|---|---|---|---|---|
| 09-10..09-24 | 15 | 8 | 25 | 1.67 | 4.4 min | 541 min |
| Stay 09-27..10-17 | 21 | 10 | 43 | 2.05 | 4.0 min | 51.5 min |
| Post-stay 10-18..11-08 | 22 | 13 | 53 | 2.41 | 6.0 min | 219 min |
| 11-02..11-08 | 7 | 2 | 3 | 0.43 | 0.5 min | 3.2 min |

Camera fires are the same rate or higher with no guest as with one (2.41/day vs 2.05/day). Of the 43 stay fires, **7** fall within +-240 min of a >=30-min guest-room run; of the 53 post-stay fires, **0**. So the camera leg is uncorrelated with the room path; fired alone it carries no more guest information than the unidentified-bodies noise that already exists. Consequence for latch exposure: with INV-SPLIT-1 (room mandatory) a long latch cannot enter GUEST on its own, but it also does not make the room leg a better guest discriminator (recall 6 percent at best).

## 6. Day-by-day evidence (CDT/CST local dates, section 1 source)

| date (CDT/CST) | GUEST entries | GUEST min | guest-room occupied min (GB1+GB2) | GB runs >=30 min | Path A fires (HOME) | egress crossings | blank-person crossings |
|---|---|---|---|---|---|---|---|
| 09-01 | 1 | 242 | 267 | 1 | 0 | 8 | 8 |
| 09-02 | 1 | 14 | 39 | 1 | 0 | 4 | 4 |
| 09-03 | 6 | 224 | 352 | 1 | 0 | 19 | 19 |
| 09-04 | 0 | 0 | 305 | 1 | 1 | 47 | 47 |
| 09-05 | 1 | 146 | 457 | 2 | 0 | 82 | 76 |
| 09-06 | 0 | 0 | 26 | 0 | 1 | 58 | 44 |
| 09-07 | 2 | 92 | 149 | 2 | 0 | 12 | 8 |
| 09-08 | 1 | 170 | 234 | 1 | 1 | 36 | 30 |
| 09-09 | 3 | 151 | 439 | 2 | 0 | 47 | 38 |
| 09-10 | 2 | 121 | 196 | 1 | 1 | 29 | 23 |
| 09-11 | 0 | 0 | 28 | 0 | 0 | 26 | 18 |
| 09-12 | 0 | 0 | 12 | 0 | 0 | 30 | 21 |
| 09-13 | 0 | 0 | 0 | 0 | 0 | 77 | 66 |
| 09-14 | 0 | 0 | 55 | 0 | 1 | 72 | 66 |
| 09-15 | 0 | 0 | 929 | 1 | 0 | 31 | 24 |
| 09-16 | 2 | 15 | 65 | 2 | 9 | 32 | 26 |
| 09-17 | 1 | 5 | 63 | 1 | 5 | 33 | 29 |
| 09-18 | 1 | 46 | 70 | 1 | 1 | 52 | 37 |
| 09-19 | 0 | 0 | 33 | 0 | 0 | 18 | 10 |
| 09-20 | 0 | 0 | 19 | 0 | 0 | 19 | 15 |
| 09-21 | 0 | 0 | 0 | 0 | 3 | 7 | 4 |
| 09-22 | 0 | 0 | 8 | 0 | 0 | 5 | 2 |
| 09-23 | 0 | 0 | 19 | 0 | 4 | 4 | 2 |
| 09-24 | 0 | 0 | 6 | 0 | 1 | 8 | 5 |
| 09-25 | 1 | 8 | 149 | 2 | 1 | 47 | 39 |
| 09-26 | 0 | 0 | 12 | 0 | 0 | 9 | 8 |
| 09-27 | 1 | 44 | 247 | 2 | 0 | 22 | 17 |
| 09-28 | 1 | 9 | 494 | 5 | 1 | 27 | 17 |
| 09-29 | 2 | 207 | 615 | 4 | 0 | 21 | 17 |
| 09-30 | 3 | 101 | 623 | 7 | 0 | 7 | 6 |
| 10-01 | 0 | 0 | 506 | 3 | 2 | 17 | 13 |
| 10-02 | 3 | 120 | 532 | 4 | 0 | 17 | 15 |
| 10-03 | 0 | 0 | 345 | 1 | 7 | 165 | 130 |
| 10-04 | 3 | 143 | 686 | 4 | 1 | 83 | 63 |
| 10-05 | 3 | 36 | 304 | 4 | 1 | 44 | 34 |
| 10-06 | 4 | 81 | 469 | 5 | 0 | 5 | 2 |
| 10-07 | 0 | 0 | 464 | 2 | 0 | 5 | 1 |
| 10-08 | 2 | 28 | 495 | 5 | 2 | 12 | 7 |
| 10-09 | 4 | 126 | 486 | 3 | 6 | 29 | 18 |
| 10-10 | 3 | 29 | 318 | 4 | 0 | 14 | 10 |
| 10-11 | 1 | 38 | 362 | 1 | 0 | 46 | 29 |
| 10-12 | 2 | 77 | 416 | 3 | 4 | 41 | 30 |
| 10-13 | 1 | 11 | 246 | 1 | 12 | 17 | 12 |
| 10-14 | 0 | 0 | 0 | 0 | 7 | 11 | 7 |
| 10-15 | 0 | 0 | 48 | 1 | 0 | 2 | 0 |
| 10-16 | 1 | 16 | 730 | 5 | 0 | 1 | 1 |
| 10-17 | 1 | 46 | 172 | 3 | 0 | 13 | 8 |
| 10-18 | 0 | 0 | 39 | 0 | 0 | 6 | 1 |
| 10-19 | 0 | 0 | 14 | 0 | 0 | 10 | 6 |
| 10-20 | 0 | 0 | 0 | 0 | 7 | 16 | 9 |
| 10-21 | 0 | 0 | 5 | 0 | 2 | 7 | 2 |
| 10-22 | 0 | 0 | 12 | 0 | 1 | 17 | 9 |
| 10-23 | 0 | 0 | 37 | 1 | 0 | 22 | 12 |
| 10-24 | 0 | 0 | 6 | 0 | 1 | 17 | 7 |
| 10-25 | 0 | 0 | 0 | 0 | 5 | 10 | 3 |
| 10-26 | 0 | 0 | 10 | 0 | 4 | 22 | 13 |
| 10-27 | 0 | 0 | 0 | 0 | 8 | 15 | 6 |
| 10-28 | 0 | 0 | 0 | 0 | 10 | 7 | 4 |
| 10-29 | 0 | 0 | 0 | 0 | 7 | 3 | 3 |
| 10-30 | 0 | 0 | 59 | 0 | 4 | 16 | 12 |
| 10-31 | 0 | 0 | 0 | 0 | 1 | 30 | 21 |
| 11-01 | 0 | 0 | 31 | 0 | 0 | 3 | 2 |
| 11-02 | 0 | 0 | 6 | 0 | 0 | 7 | 3 |
| 11-03 | 0 | 0 | 0 | 0 | 2 | 16 | 8 |
| 11-04 | 0 | 0 | 0 | 0 | 1 | 9 | 4 |
| 11-05 | 0 | 0 | 0 | 0 | 0 | 20 | 10 |
| 11-06 | 0 | 0 | 9 | 0 | 0 | 18 | 11 |
| 11-07 | 0 | 0 | 0 | 0 | 0 | 11 | 5 |
| 11-08 | 0 | 0 | 0 | 0 | 0 | 26 | 11 |


## 7. Stop-clause verdict

| Clause | Result | Verdict |
|---|---|---|
| (a) no L keeps >=80 percent of stay entry-days AND the WiFi leg is off | L=30: 0/16, L=60: 1/16, L=120: 1/16, L=240: 1/16 of entry-days; WiFi must be off (4.3: wifi true on 7 of 7 days at S<=30, 6 of 7 at S=60/120, resident-linked devices) | **TRIGGERED** |
| (b) ~0 room-alone FPs on no-stay days since 09-10 (<=1) | 0 entries 10-18 to 11-08; 6 entries 09-10..09-18 (2 on the 09-10 deploy day, 4 cluster B). If cluster B is a visit: 2 unlabeled 09-10 entries remain, which is borderline against the <=1 bar; if cluster B is not a visit: 4 FP candidates, but 3 of 4 carry a camera run within 240 min, so a visit is likely | **Triggered or borderline (0 definite FPs; 2 deploy-day entries unlabeled); not triggered only if the operator labels cluster B and the 09-10 entries as non-visits** |

Per plan 2.3 and the D0 text: ship **D2 only** (`visitors_present`, a low-bar display entity from the room leg plus unidentified-body and WiFi evidence) and **park D3** with the revival trigger "a room-alone GUEST entry on a day the operator confirms no guest". Rationale in numbers: the proposed second leg would remove 33-35 of 35 stay entries (recall loss of essentially the whole stay) to prevent a false-entry population that is about zero since 10-18 and had no confirmed members before it. Marginal-benefit decomposition: benefit (remove the resident-in-GB2 FP) is 0 observed events; cost (lose the room leg on a real stay) is about 94 percent of entry-days. This is also the case the plan's section 2.3 set up as the stop.

Producer/consumer notes that sharpen the verdict:
- **Producer of the entries is solid for the stay:** all 35 stay entries are the room path at room-age 30+ min (none Path A), so the room leg is what a real guest stay actually exercises. The camera does not corroborate real guest-room dwell.
- **The room leg misses at least two stay days (10-14, 10-15)** with a known guest present (memory, 10-14), so recall of the existing room-only rule is already imperfect.
- **GUEST was already absent on 19 of 21 stay nights** (house in home_night/sleep), so the consumer effect of removing GUEST (NM exterior-person severity, SLEEP blocking) is already mostly the "no GUEST" behavior at night.
- **Entry timing:** **28 of the 35 stay entries start between 06:00 and 10:59 CDT** (hour counts: 06:8, 07:5, 08:7, 09:6, 10:2), 5 between 13:00 and 17:59, 2 at 21:xx. A morning cluster this tight (room occupied from about 05:30-10:30) fits a resident routine (for example someone in a guest room without a BLE fix there) at least as well as a guest. I did not attribute them; the table in section 2 has a blank column for the operator. This is the single most important label set for the decision.

## 8. Required operator inputs before any build (plan 5.0 b, c)

1. Confirm or correct the stay dates (section 1) and say what cluster B (09-15 to 09-19) was.
2. Label the 44 rows in section 2 as real / FP where known (especially the morning 06:00-10:00 entries on 10-04 to 10-13, which I cannot attribute).
3. Confirm the guest on 10-14/10-15 and where she slept (room leg did not register).
4. Say whether to accept the plan's recommendation (D2 only, park D3) or to override and build the second leg anyway (then D3 recall is about 6 percent per section 3).
5. Confirm that `MacBookAir` (0e:a8:a4:be:6d:7e), the hostless 02:f0:d7:b5:e4:cd and `iphone_4` (06:7b:aa:d0:af:aa) are resident devices (this reframes the 10-17 audit's WiFi evidence).

## 9. Falsifiers checked

- "The camera leg fires on real guest-room entries": falsified by section 3 (0 of 35 at L=30; the confidence column is 0.9 on every run).
- "The WiFi leg is clean over the 7-day no-guest window": falsified by section 4 (floor>=1 every day; sustained candidate devices every day at S<=30).
- "There is a false-entry population to fix": not found since 10-18 (0 entries in 22 days) and no confirmed FPs before; the only candidates are 2 deploy-day (09-10) + 4 cluster-B entries, label pending.
- What would reverse the verdict: operator labels that a majority of the 35 stay entries were residents (not the guest) AND the 10-04..10-13 morning entries were Ziri/Jaya in GB1/GB2 without a BLE fix. Then the room-alone FP population is large, the second leg's benefit is real, and recall loss is partly illusory. This is why the labels in section 8 gate the decision.

## Caveats and unknowns

- Room runs are from raw `occupancy_events`; the live gate's `first_seen` can restart on quiet breaks and a known-person cancel, which I did not replay (affects room-run matching, not the entry list).
- The cam replay uses `census_snapshots` zone `house` at about 60-90 s cadence; sub-minute Path A glitches are invisible.
- My device-level WiFi replay lacks Filter 4 sibling/MAC expansion; the production floor (4.2) is the guard against that. The two agree in direction.
- HVAC and presence state-of-play docs were not read for this probe; no ledger claim is re-asserted.
- Time zone: the recorder `NOW` and `date` are consistent; house_state_log and occupancy_events are naive UTC (verified against the 10-17 audit's 21:06:39Z).
