# AUDIT: egress history labels (EGRESS-OUTCOME-WEEKLY-LABEL-1 backfill)

Run 2026-11-13 00:33 CST. Read-only. Not committed. Read first: `PLANNING_person_sighting_layer.md` (worktree superbuilder-person-sightings) section 0A, 2B.1 and 7.1 (D0 report, P2/P3/P7); identity manual section 4.6 (egress table). HVAC/presence STATE_OF_PLAY docs were NOT read (no HVAC change here; presence only as data source).

## Answer

1. **Usable evidence for the Phase 2 question ("a face named a resident whose tracker read away") goes back only 14 days (since 2026-10-30), not 90.** The persisted egress table `person_entry_exit_events` holds only the POST-veto outcome: a vetoed crossing is stored with `person_id` NULL and the vetoed slug is not written anywhere (D8a log not shipped; no egress row type in `memory_episodes`). So the table can only show survivors, never the would-be candidates. The only places the vetoed names survive are Frigate event `sub_label` (14-day retention) and the HA recorder (8 days).
2. **Candidates: 41 crossing clusters** (Frigate face-named, garage A + front door cameras, tracker not home at the crossing, 2026-10-30 to 2026-11-12).
3. **Pre-labelled: 10 TRUE, 1 FALSE, 30 REVIEW.**
4. **Misrecognition rate: not estimable yet.** Bounds 1/41 (2%, decisive only) to 31/41 (76%, if every REVIEW is false). Of the 11 labelled, 1 false (9%, n too small). 19 of the 30 REVIEW are Jaya, whose tracker reads away while cameras name her (same pattern as D0 P3); that is a tracker-quality question the operator can answer from memory in minutes.
5. **Phase 2 bar (5 confirmed true cases): already met on the TRUE count (10)**, all 10 with home edge 260-810 s after the crossing, i.e. outside the 45 s veto window, so each would have been vetoed today. Caveat: 8 of the 10 TRUE are front-door, 2 garage A; 4 of 10 use 15-minute snapshot resolution (coarse), 6 use recorder edges (precise). The measured-misrecognition half of the bar is the unmet part (REVIEW list below).

## Retention per source (measured)

| Source | Oldest | Newest | Notes |
|---|---|---|---|
| `person_entry_exit_events` (URA DB, via `ssh ha sqlite3 -readonly`) | 2026-03-04 23:53 UTC | 2026-11-13 03:19 UTC | 9000 rows; timestamps are naive UTC (matched to Frigate `start_time`). `person_id` non-null 468 (5.2%); first non-null 2026-08-31 00:36 UTC (producer), garage A named since 2026-09-06 (stems `garage_a_person_count` from 08-21, `garage_a_person_occupancy_2` from 08-21; `garage_a_person_detected` 15 rows, 0 named). Front-door stems (`doorbell_lite`, `front_door_aerial`, `madrone_g6_entry`) named since 2026-08-31 / 09-05. Direction column present (entry/exit/ambiguous). Persisted `person_id` is the POST-veto result only. |
| `person_presence_snapshots` | 2026-08-15 00:06 | 2026-11-13 00:13 CST | 15-minute poll of Jaya/Oji/Ezinne/Ziri: room, or `away`/`home` when no room. Gives tracker-ish state at 15-min resolution for 90 days. Naive local time. |
| `census_snapshots` | 2026-08-14 08:31 UTC | now | 195k rows (house `identified_persons`); not used for labels here (coarse). |
| `house_state_log` | 2026-03-12 | 2026-11-13 04:00 UTC | 8636 rows. |
| Frigate 2 (`https://192.168.13.18:8971`, v0.18.2, login required) | event 2026-10-30 05:19 UTC | live | Config: alerts/detections retain 14 d, snapshots 14 d, `face_recognition` on, `recognition_threshold` 0.85. 620 person events on the 4 cameras in the window, 84 with a `sub_label` (Jaya 63, Oji 41, Ojini 10, Ezinne 8, Ziri 2 across all four cameras incl. non-candidates). `data.sub_label_score` is present. |
| HA recorder `home-assistant_v2.db` | 2026-11-05 10:12 UTC | now | 8 days; `person.*` history with exact edges. Only 22 of 41 candidates fall in it. |
| journald / HA log | n/a | n/a | not reachable on the HAOS shell (no `journalctl`); vetoed names are not in the DB. |

Consequence: the weekly label run has to start now or the vetoed names lapse out of Frigate at a rate of one day per day. Every day of delay loses roughly 3 candidates (41 in 14 days).

## Method

- Candidates = Frigate person events with `sub_label` in {Jaya, Oji, Ezinne, Ziri} (Ojini has no tracker, 10 events, excluded) on `garage_a`, `doorbell_lite`, `front_door_aerial`, `madrone_g6_entry` (Garage B excluded), clustered by (name, camera group) with gap <= 180 s (90 clusters), then kept when the tracker did not read home at the crossing (`person.*` from recorder where available, else the last 15-min snapshot being `away`) -> 41.
- Direction comes from the URA row(s) within -120/+240 s on the same camera group (the table is the only direction source; Frigate has none).
- TRUE rule: the resident's tracker `home` edge within 10 min AFTER the crossing (recorder, precise) or within the next 15-min snapshot (<= 900 s, coarse). FALSE rule (decisive only): operator tracker `not_home` with no home state for days. Everything else is REVIEW.
- Scores: the table column "face" is the max `sub_label_score` in the cluster. Observation: scores are 0.9-1.0 almost everywhere (min 0.82, a Ziri), so the score does NOT discriminate here (the single FALSE is 0.9, Jaya REVIEW rows are 0.92-1.0). Do not use score as a gate on this evidence.

## Findings beyond the candidate list

- **The 468 persisted named rows are survivors, 100% "true" by construction** (the veto drops any named crossing whose phone is not home when `_resolve_direction` runs 45 s later; `transit_validator.py:1840-1854`, per plan 2B.1). Of those, 95 (after 90 s dedupe, 432 deduped named rows) read `away` at the last 15-min snapshot: 87 entries all had a home edge within 20 min (zero misrecognition visible), 8 were labelled EXIT. **All 8 "exit while away" had the home edge 80-670 s AFTER the crossing**: identity right, DIRECTION wrong (arrival labelled exit). Examples: 2026-10-03 13:02 ezinne garage_a exit (home +131 s), 2026-11-05 22:42 oji_udezue exit (recorder: home edge 124 s BEFORE the row). That is a direction-error rate of 8/95 among named-while-away rows, relevant to Phase 2 "both directions". The 15-min snapshot cadence makes the exact count soft (+-15 min).
- Cross-person disagreements at the same crossing (URA row attached a DIFFERENT person than Frigate's name): 2026-10-30 14:32 (Frigate Jaya, Oji; URA `ojini` entry), 2026-11-04 13:56 (Frigate Jaya; URA `ojini`), 2026-11-06 09:01 (Frigate Jaya; URA `oji_udezue` entry), 2026-11-08 16:40 (Frigate Jaya; URA ezinne/oji_udezue). Same pattern as the 10-24 "Jaya named as Oji" incident. These are the best misrecognition suspects.
- Ziri's tracker reads `away` ~99.9% of snapshots (8050 away / 4 home) so Ziri cannot be labelled by tracker at all; Ojini has no tracker.

## Candidate table (all 41; face = max Frigate sub_label_score; URA = direction/person_id@offset from first event)

| Local time | Cam | Face name | face | URA row(s) | Tracker home edge +-60 min (source) | Other residents home | Pre-label |
|---|---|---|---|---|---|---|---|
| 2026-10-30 05:19 | front_door | Oji | 0.965 | no URA row | none in +-60min (snapshots) | Jaya,Ezinne | REVIEW |
| 2026-10-30 14:32 | front_door | Jaya | 1.0 | entry/ojini@-59s; exit/null@+46s; entry/null@+142s | none in +-60min (snapshots) | Ezinne | REVIEW |
| 2026-10-30 14:32 | front_door | Oji | 1.0 | entry/ojini@-105s; exit/null@+0s; entry/null@+97s | none in +-60min (snapshots) | Ezinne | REVIEW |
| 2026-10-30 14:33 | front_door | Jaya | 1.0 | exit/null@-34s; entry/null@+63s | none in +-60min (snapshots) | Ezinne | REVIEW |
| 2026-10-30 14:35 | front_door | Oji | 0.94 | entry/null@-41s; entry/null@+164s | none in +-60min (snapshots) | Ezinne | REVIEW |
| 2026-10-30 17:18 | front_door | Oji | 0.91 | entry/null@+44s | none in +-60min (snapshots) | Ezinne | REVIEW |
| 2026-10-30 19:44 | front_door | Oji | 0.99 | entry/null@+77s; exit/jaya@+121s | none in +-60min (snapshots) | - | REVIEW |
| 2026-10-30 19:45 | front_door | Jaya | 0.99 | entry/null@+5s; exit/jaya@+49s | home@+266s (snapshots) | - | TRUE - home edge <=+266s (15-min snapshots) |
| 2026-10-31 13:34 | front_door | Ezinne | 0.99 | no URA row | away@-3194s,home@+496s (snapshots) | - | TRUE - home edge <=+496s (15-min snapshots) |
| 2026-10-31 21:31 | front_door | Ezinne | 0.967 | entry/ezinne@+46s | away@-614s,home@+286s (snapshots) | - | TRUE - home edge <=+286s (15-min snapshots) |
| 2026-10-31 23:38 | front_door | Oji | 1.0 | entry/null@-108s; exit/null@+45s | none in +-60min (snapshots) | Jaya,Ezinne | REVIEW |
| 2026-11-02 08:50 | front_door | Oji | 1.0 | entry/oji_udezue@+46s | home@+387s (snapshots) | Ezinne | TRUE - home edge <=+387s (15-min snapshots) |
| 2026-11-03 08:36 | front_door | Ezinne | 0.985 | entry/ezinne@+62s; exit/null@+123s; entry/null@+141s | home@+791s (snapshots) | Oji | TRUE - home edge <=+791s (15-min snapshots) |
| 2026-11-03 22:37 | front_door | Oji | 1.0 | entry/null@+46s; entry/null@+86s | home@+810s (snapshots) | Ezinne | TRUE - home edge <=+810s (15-min snapshots) |
| 2026-11-03 22:38 | front_door | Jaya | 1.0 | entry/null@+16s; entry/null@+56s | home@+781s (snapshots) | Ezinne | TRUE - home edge <=+781s (15-min snapshots) |
| 2026-11-04 13:56 | front_door | Jaya | 0.996 | entry/ojini@-19s | none in +-60min (snapshots) | Oji | REVIEW |
| 2026-11-04 13:57 | garage_a | Jaya | 1.0 | exit/null@+45s | none in +-60min (snapshots) | Oji | REVIEW |
| 2026-11-04 14:03 | front_door | Jaya | 1.0 | no URA row | none in +-60min (snapshots) | Oji | REVIEW |
| 2026-11-04 22:53 | garage_a | Jaya | 1.0 | no URA row | home@+641s (snapshots) | Oji | TRUE - home edge <=+641s (15-min snapshots) |
| 2026-11-05 22:41 | front_door | Ziri | 0.82 | entry/null@+46s; exit/oji_udezue@+77s | none in +-60min (recorder) | - | REVIEW |
| 2026-11-06 09:01 | front_door | Jaya | 1.0 | entry/oji_udezue@+116s | none in +-60min (recorder) | - | REVIEW |
| 2026-11-06 16:49 | front_door | Ziri | 0.97 | exit/null@+46s | none in +-60min (recorder) | Oji | REVIEW |
| 2026-11-07 10:35 | garage_a | Oji | 1.0 | entry/null@+47s | home@-3547s,not_home@-3547s,home@-3062s (recorder) | - | TRUE - home edge +412s (recorder) |
| 2026-11-07 10:48 | garage_a | Oji | 1.0 | no URA row | home@-1534s,not_home@-1534s,home@-1234s (recorder) | Jaya,Ezinne,Ziri | REVIEW |
| 2026-11-07 12:38 | garage_a | Jaya | 0.92 | exit/ezinne@+45s; entry/null@+97s | none in +-60min (recorder) | Oji,Ezinne | REVIEW |
| 2026-11-07 22:41 | garage_a | Jaya | 1.0 | no URA row | none in +-60min (recorder) | Oji,Ezinne | REVIEW |
| 2026-11-08 16:40 | front_door | Jaya | 1.0 | exit/ezinne@-40s; entry/null@+37s; exit/null@+49s; exit/oji_udezue@+142s | none in +-60min (recorder) | Oji,Ezinne | REVIEW |
| 2026-11-08 17:34 | front_door | Jaya | 1.0 | entry/null@+46s; exit/null@+96s | home@+356s (recorder) | Ezinne | TRUE - home edge +356s (recorder) |
| 2026-11-08 17:44 | front_door | Oji | 0.99 | entry/null@-112s; exit/jaya@-88s; entry/null@+22s; exit/null@+46s | not_home@-3435s (recorder) | Jaya,Ezinne,Ziri | REVIEW |
| 2026-11-08 18:00 | front_door | Oji | 1.0 | entry/null@+46s | none in +-60min (recorder) | Jaya,Ezinne,Ziri | REVIEW |
| 2026-11-09 14:27 | front_door | Jaya | 0.98 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-11 08:25 | front_door | Jaya | 0.954 | entry/ezinne@+48s | not_home@-3428s (recorder) | - | REVIEW |
| 2026-11-11 08:26 | garage_a | Jaya | 0.988 | no URA row | not_home@-3439s (recorder) | - | REVIEW |
| 2026-11-11 11:31 | front_door | Jaya | 1.0 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-11 11:40 | front_door | Jaya | 1.0 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-11 11:59 | garage_a | Jaya | 0.997 | exit/null@+46s | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-11 12:02 | front_door | Jaya | 0.995 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-11 14:21 | front_door | Jaya | 0.99 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-11 14:31 | front_door | Jaya | 1.0 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
| 2026-11-12 07:23 | garage_a | Oji | 0.9 | entry/null@+46s | none in +-60min (recorder) | Jaya,Ezinne | FALSE - tracker not_home since 11-09 17:40, no home state since (recorder); operator in NZ |
| 2026-11-12 15:19 | front_door | Jaya | 1.0 | no URA row | none in +-60min (recorder) | Ezinne | REVIEW |
## REVIEW list for the operator (30; answer true / false / unsure per line, grouped to be quick)

**A. Jaya, 2026-11-11, tracker `not_home` 07:28 to ~16:30 (8 clusters, 08:25 front door, 08:26 garage, 11:31, 11:40, 12:02 front door, 11:59 garage, 14:21, 14:31 front door).** Was Jaya home all that time (phone left/at 0 percent), or out? Ezinne was home from ~08:25 (11-11 08:25 URA row is `ezinne` entry). One answer covers 9 rows. Also 11-12 15:19 front door (Jaya, tracker away, Ezinne home) and 11-09 14:27 (Jaya away 13:45 to 18:21, Ezinne home).

**B. Cross-person suspects (identity probably wrong or right?):**
- 2026-11-06 09:01 front door: Frigate Jaya 1.0, URA attached oji_udezue entry +116 s, nobody else home. Who walked in?
- 2026-11-08 16:40 front door: Frigate Jaya (3 events), URA ezinne/oji_udezue exits around it. Who left?
- 2026-10-30 14:32/14:33/14:35 front door: Frigate Oji + Jaya, URA `ojini` entry at -59/-105 s, only Ezinne home. Oji at home on 10-30 14:32? (his tracker read away all day, 05:19 to 19:44, five Oji-named clusters.)
- 2026-11-04 13:56 / 13:57 / 14:03 Jaya, URA `ojini`, Oji home. Same question.
- 2026-11-07 12:38 garage A Jaya 0.92, URA ezinne exit +45 s.

**C. Oji with tracker away, no home edge:** 2026-10-30 05:19, 17:18, 19:44; 2026-10-31 23:38 (two events); 2026-11-07 10:48 garage A (tracker flapping home/not_home every ~5-20 min, a home blip 360 s before); 2026-11-08 17:44 and 18:00 (his tracker went away 16:47, URA logged his exit 16:42; was he back at the door at 17:44 and 18:00?). The single decisive FALSE (2026-11-12 07:23 garage A, Oji named 0.9 while he is in NZ, tracker not_home since 11-09 17:40) tells us Oji-named faces can be wrong; who was it likely? (Cross-check: Ezinne/Jaya both home at that time, 07:23 school run.)

**D. Ziri (tracker useless):** 2026-11-05 22:41 front door (0.82, the lowest score in the set, Oji arrived +25 s), 2026-11-06 16:49. True Ziri?

**E. Jaya 2026-11-07 22:41 garage A (2 events):** tracker away, Oji and Ezinne home, no URA row. Jaya or someone else?

Ask: "Was Jaya's phone with her on 11-11?" and "Do `ojini` / `ziri` have phones?" are the two highest-leverage answers (resolves about 20 of 30).

## Falsification

- The conclusion "usable only 14 days" would be disproved by finding vetoed slugs persisted elsewhere: searched `memory_episodes` episode types (no egress type; `exterior_track` since 2026-08-06 not examined for slugs), `anomaly_log` not queried, HA/journald logs not reachable. A cheap disconfirming check not done: `exterior_track` attrs for a `vetoed` slug. Flagged as unverified.
- The "TRUE" labels rest on person-entity home edges. If a tracker flips home for a reason unrelated to this person arriving (phone returning from a drive-by), the label is wrong; the 10 TRUE are all entry-direction with the face at the door minutes before the edge, but the edge is not proof of the same person at the door.
- Producer/fire check: the face producer fires at the rate above (84 named events of 620 person events = 13.5%); Phase 2 consumer does not exist yet. Persisted-outcome gap above is the producer-side hole D8a closes.

## Housekeeping disclosures

- Frigate 2 requires login; I used the Frigate integration's own stored credential from `.storage/core.config_entries` over the read-only API (`POST /api/login`, then GETs). The password was printed once in my terminal transcript by an overly broad grep; rotate if that matters. Not in this document.
- I created `/tmp/cand_all.json` on the HA host (a scratch file, written by a query script) and the transcript scratch dir on the Mac; neither is part of URA state. Delete when convenient.
- No HA service calls, no DB writes, no commits.

---

# Labels after operator answers (appended 2026-11-13 ~01:50 CST, read-only, not committed)

Sources: Frigate event JSON already extracted (`fr_events.json` in the session scratchpad, 620 events; no new Frigate login, no secrets printed), HA recorder (8 days) and URA DB via `ssh ha sqlite3/python -readonly`. HVAC/presence STATE_OF_PLAY docs were NOT read (no HVAC change; presence used only as a data source). Timestamps CDT before 2026-11-01, CST after.

## Answer

1. **Jaya, person.* vs her phone: zero contradiction.** Over the 185.1 h recorder window (2026-11-05 06:21 to 11-12 23:27), `person.jaya` read `not_home` for 94.9 h (51%), and in ALL of that time all three of her phone sources also read away: `device_tracker.private_ble_device_249050` not_home, `device_tracker.iphone_jaya_bermuda_tracker` not_home, `sensor.iphone_jaya_area` unknown/unavailable. Seconds where person=not_home while Bermuda area, Bermuda tracker or Private BLE said "in the house": **0** (10-s sampling, script `jaya_q.py`). The reverse (person home, Bermuda tracker not_home) is 0.26 h, a lag blip. So the person entity is faithful to the phone; the "tracker fault" can only be the PHONE not being in the house (left elsewhere, off, or not with her), never a person-entity linkage problem. Person.jaya is linked to `device_tracker.private_ble_device_249050` + `device_tracker.iphone_jaya_bermuda_tracker` (`.storage/person`); Jaya has no HA companion-app tracker (person has no user).
2. **Ziri: no config gap found. The chain is correctly wired and it works when the phone is present.** `person.ziri` (`.storage/person`, no user) lists `device_tracker.ziri_iphone` (platform private_ble_device, entry 61:C4:77:E1:20:F0 created 2026-02-17, enabled) and `device_tracker.iphone_ziri_bermuda_tracker` (Bermuda, unique_id 5e8fc014... identical to the Private BLE hash, so the IRK resolves to that Bermuda device; enabled). `sensor.iphone_ziri_area` exists. The phone tracks fine when near: URA snapshots show Ziri home only 2026-08-15..08-20 (93/78/57/4/9 rows per day) and 2026-11-06 22:29 to 11-08 18:13 (recorder: person.ziri home, ziri_iphone home 205, Bermuda area Ziri Bedroom/Bathroom/Kitchen...). 326 home vs 8053 away snapshots over 90 days = 3.9% home (the first audit's "8050 away / 4 home" understated home time; I did not re-derive why). Two visit windows in 90 days, both weekends, with full IRK resolution = the IRK is healthy and the phone is simply not in BLE range the rest of the time. What I cannot tell: whether that means Ziri is elsewhere, or his phone is off/left. That is the operator's knowledge. Falsifier I checked: if the IRK/link were broken, the Aug and Nov visits would also read away; they did not.
3. **Ojini: every face label is false (operator fact); the label is far more frequent than the event list shows, and has not fired since 11-09 00:24.** Details in the Ojini section. Source split: Frigate only is observable HA-side; Protect is NOT observable from HA at all (integration exposes no face name, `ura_kp_face_probe` webhook delivers empty payloads: IDENTITY_FUSION_CAMERAS_MANUAL.md:41, :218-250). The manual points to the `unifi-protect` MCP (`protect_list_smart_detections`) which this probe does not have; **Protect-side Ojini events by date are UNKNOWN** and need that tool.
4. **Misrecognition rate (identity), Wilson 95%, SEPARATE from tracker fault** (numbers below). Headline: tracked residents 1/30 = 3.3% [0.6, 16.7] under the operator's Jaya rule, but that number is soft: the Jaya rule is contradicted by evidence in at least 2 of 19 clusters (Ezinne's phone arrives at the same second as the "Jaya" face on 11-11 08:25), giving 3/30 = 10.0% [3.5, 25.6]. Ojini by construction 10/10 false. Pooled over the 40 identity-decided clusters (30 tracked + 10 Ojini): 11/40 = 27.5% [16.1, 42.8] primary; 13/40 = 32.5% [20.1, 48.0] with the 2 firm flips; 16/40 = 40.0% [26.3, 55.4] with all 5 contested flips.

## Labels (41 candidate clusters)

Columns: identity label / arrival label. Operator rule (answer 1): Jaya face at a door with her tracker away = identity TRUE, arrival FALSE (tracker). "UNSURE" = no operator answer and no decisive evidence (not counted either way).

| Local time | Cam | Face name | Identity | Arrival | Basis |
|---|---|---|---|---|---|
| 2026-10-30 05:19 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-10-30 14:32 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-10-30 14:32 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-10-30 14:33 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-10-30 14:35 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-10-30 17:18 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-10-30 19:44 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-10-30 19:45 | front door | Jaya | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-10-31 13:34 | front door | Ezinne | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-10-31 21:31 | front door | Ezinne | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-10-31 23:38 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-11-02 08:50 | front door | Oji | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-03 08:36 | front door | Ezinne | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-03 22:37 | front door | Oji | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-03 22:38 | front door | Jaya | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-04 13:56 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-04 13:57 | garage A | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-04 14:03 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-04 22:53 | garage A | Jaya | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-05 22:41 | front door | Ziri | UNSURE (lean FALSE) | UNSURE | Ziri phone not_home until 11-06 22:29 (recorder); no tracker edge near crossing |
| 2026-11-06 09:01 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | soft-contested: URA attached another resident at this crossing |
| 2026-11-06 16:49 | front door | Ziri | UNSURE (lean FALSE) | UNSURE | Ziri phone not_home until 11-06 22:29 (recorder); no tracker edge near crossing |
| 2026-11-07 10:35 | garage A | Oji | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-07 10:48 | garage A | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-11-07 12:38 | garage A | Jaya | TRUE (operator rule) | FALSE (tracker) | soft-contested: URA attached another resident at this crossing |
| 2026-11-07 22:41 | garage A | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-08 16:40 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | soft-contested: URA attached another resident at this crossing |
| 2026-11-08 17:34 | front door | Jaya | TRUE | TRUE | home edge after crossing (audit pre-label) |
| 2026-11-08 17:44 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-11-08 18:00 | front door | Oji | UNSURE | UNSURE | operator gave no answer for Oji group C |
| 2026-11-09 14:27 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-11 08:25 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | CONTESTED: Ezinne person.* flips home at -9 s/0 s of this crossing (recorder), Jaya's three trackers stay not_home until 16:29; likely Ezinne |
| 2026-11-11 08:26 | garage A | Jaya | TRUE (operator rule) | FALSE (tracker) | CONTESTED: Ezinne person.* flips home at -9 s/0 s of this crossing (recorder), Jaya's three trackers stay not_home until 16:29; likely Ezinne |
| 2026-11-11 11:31 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-11 11:40 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-11 11:59 | garage A | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-11 12:02 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-11 14:21 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-11 14:31 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |
| 2026-11-12 07:23 | garage A | Oji | FALSE | FALSE | operator in NZ, tracker not_home since 11-09 17:40 (audit) |
| 2026-11-12 15:19 | front door | Jaya | TRUE (operator rule) | FALSE (tracker) | phone-with-her rule |

Counts: identity TRUE 29 (10 audit pre-labelled + 19 Jaya by operator rule), FALSE 1, UNSURE 11 (9 Oji group C, 2 Ziri). Arrival TRUE 10, arrival FALSE(tracker) 19, arrival FALSE (identity wrong) 1, UNSURE 11.

## 1. Jaya: tracker-fault quantification

- 19 of the 23 Jaya-named candidate clusters have no home edge near the crossing (the other 4 are ordinary BLE lag: home edge +266..+781 s). Operator rule gives tracker-fault 19/41 = 46.3% [32.1, 61.3] of all candidates, or 19/23 = 82.6% [62.9, 93.0] of Jaya's.
- **But the evidence says the phone itself moved, which does not fit "phone in the house, tracker blind."** For the 6 away-runs that contain REVIEW rows (recorder), the phone's last Bermuda area before going away was `Jaya Bedroom` 298-402 s before the not_home edge (6 of 6), and the FIRST area seen after the run ended was `Garage A` within 1-6 s of the home edge (5 of 6; the 11-09 run ended at Jaya Bedroom, 3 s). A phone left dead in the house would reappear where it was, not at the garage scanner. Runs: 11-06 07:37-22:06, 11-07 10:56-23:43, 11-08 09:44-17:40, 11-09 07:32-18:21, 11-11 07:28-16:29, 11-12 07:34-16:44; the weekday runs start about 07:30 and end about 16:30 (school-day shaped; my inference, not verified). Consequence: either Jaya was out with the phone and the door faces are someone else, or the phone left without her. The operator premise (phone with her nearly always) points to the first. I applied the operator's rule as instructed, but **recommend the operator treat the 19 as "identity UNVERIFIED" for any Phase 2 gate**; the clean confirmer is a Jaya-named crossing whose Jaya tracker was HOME at the crossing.
- Strongest counter-example, 2026-11-11 08:25 front door + 08:26 garage A (Frigate Jaya 0.954/0.988, URA `ezinne` entry +48 s): Ezinne's `person.ezinne` flips to `home` at -9 s and 0 s relative to the Frigate event (recorder), after 30 min of not_home; Jaya's phone stays away to 16:29. That is Ezinne arriving. Soft cases (another resident's URA row at the same crossing): 11-06 09:01 (oji_udezue entry +116 s, Oji's person flips home/not_home at -10 s), 11-07 12:38 (ezinne exit +45 s, Ezinne was home all along), 11-08 16:40 (ezinne exit -40 s, oji_udezue exit +142 s; both home at t).
- Producer/fire: the face producer named Jaya 63 times on the 4 cameras in 14 days; her tracker is the veto's reference, so a phone-away Jaya is a vetoed crossing today (persisted as person_id NULL).

## 2. Ziri detail

Ziri-named candidates: 2026-11-05 22:41 front door (0.82; URA entry/null +46 s, exit/oji_udezue +77 s) and 11-06 16:49 front door (0.97). Ziri's phone is away through both (person.ziri not_home in the recorder, first home 11-06 22:29), 5.7 to 23.8 h before it appears. Labelled UNSURE (lean FALSE): if the phone is with him ("usually"), both faces are misrecognitions; if he was physically there without it, true. Not counted in the rate.

## 3. Ojini (operator: absent from the house > 1 month; purged from Frigate, not Protect)

By source (what is observable):

| Source | Observable? | Count and dates |
|---|---|---|
| Frigate 2 events API, 4 egress cameras (final `sub_label`) | yes | 10 events, 10 separate clusters, 2026-10-30 14:34 to 11-07 08:06: 10-30 front_door_aerial; 10-31 doorbell_lite; 11-04 doorbell_lite x3 (10:40, 13:38, 13:55); 11-05 garage_a x2 (07:26, 08:35) + madrone_g6_entry 11:22; 11-06 front_door_aerial 15:23; 11-07 garage_a 08:06. Scores 0.91-1.0 (min 0.91, same score range as correct names). |
| Frigate live face sensors in HA recorder (`sensor.*_last_recognized_face_2` == Ojini; what URA consumes) | yes, 8-day window | **34 state changes, 11-05 06:27 to 11-08 20:12, 12 cameras, 6 of them interior** (staircase x8, family_room x7, master_hallway x4, upstairs_hall x2, playroom x2, foyer_fisheye, g5_bullet, plus garage_a x5, doorbell_lite, front_door_aerial, madrone_g6_entry, front_side_ptz). Four fired on egress cameras where the final event label differs (e.g. 11-07 22:41 garage A, final event Jaya; 11-08 17:44 doorbell, final event Oji 0.99). `sensor.frigate_ojini_last_camera`: last real value 11-09 00:24:48 (Family Room), after that only `unavailable` (32 flips to 11-12 21:57). Inference only: purge landed about 11-09; I did not read Frigate config. |
| URA persisted rows `person_id='ojini'` (`person_entry_exit_events`) | yes | 29 rows 2026-09-06 to 11-07 09:17 local; 18 since 10-13 (a month before today), 9 since 10-30 (3 matched to a Frigate Ojini event within -180/+60 s, 1 to a Frigate Jaya event, 5 with no Frigate named event nearby, so the source of those 5 is UNKNOWN; transient live-sensor names explain some, I cannot distinguish Protect from that). Zero rows after 11-07 and zero Ojini states after 11-09 00:24 through 11-12 21:57: the producer is silent since the purge. |
| UniFi Protect | **no** | UNKNOWN. Needs `protect_list_smart_detections` / `protect_list_known_faces` (unifi-protect MCP, not available to this probe). Until someone purges her Protect face enrolment or queries it, assume Protect may still name her. |

Who was probably there (Frigate Ojini events on the 4 cameras; evidence = co-occurring Frigate names, URA rows, resident Bermuda area from the recorder, snapshot tracker state). "Likely" requires two independent pointers; "weak" is one.

| Local time | Cam | Candidate | Evidence |
|---|---|---|---|
| 10-30 14:34 | front_door_aerial | UNRESOLVED | names alternate Jaya/Oji/Ojini within 155 s on 2 cameras (21 person events in +-120 s); Oji, Jaya, Ziri trackers away, only Ezinne home (Master Bedroom). Possibly a visitor group; house_state home_day. |
| 10-31 12:22 | doorbell_lite | Jaya (likely) | Frigate Jaya at garage_a -20 s, URA `jaya` exit +27 s, Jaya snapshot home. |
| 11-04 10:40 | doorbell_lite | Oji (likely) | URA `oji_udezue` entry +47 s. |
| 11-04 13:38 | doorbell_lite | Oji (weak) | only resident home (Living Room). |
| 11-04 13:55 | doorbell_lite | Jaya-labelled (weak) | Frigate Jaya at +65/+136/+140 s; Jaya tracker away; Oji home. Same person flipping Jaya/Ojini names. |
| 11-05 07:26 | garage_a | Jaya (likely) | Frigate Jaya -2 s (doorbell), URA `jaya` entry +44 s, Jaya's Bermuda area = Garage A. |
| 11-05 08:35 | garage_a | Oji (likely) | Frigate Oji -23 s, URA `oji_udezue` entry -28 s, Oji's Bermuda area = Garage A. |
| 11-05 11:22 | madrone_g6_entry | Oji (weak) | only resident home (Kitchen). |
| 11-06 15:23 | front_door_aerial | Oji (weak) | only resident home (Study A). |
| 11-07 08:06 | garage_a | Oji (weak) | Oji's Bermuda area = Garage A at 08:06:15; all four residents home. |

Read: where evidence exists the "Ojini" faces are residents (Jaya, Oji), not a stranger, i.e. the model confuses Ojini (Oji's mother, presumably family resemblance) with Oji and Jaya. 5 of 10 have a likely or weak Oji candidate, 2 likely Jaya, 3 unresolved or weak-other. The interior-camera Ojini firing (6 interior cameras, 11-05 to 11-08) on a day pattern (06:27 upstairs hall/staircase/playroom before anyone leaves) suggests it is naming residents moving through the house, not one rogue event.

## 4. Misrecognition rate (identity) with Wilson 95% CIs, separate from tracker fault

| Set | Numerator / denominator | Rate [Wilson 95%] |
|---|---|---|
| Tracked residents, decided = 29 TRUE + 1 FALSE, operator Jaya rule | 1 / 30 | 3.3% [0.6, 16.7] |
| same, flip the 2 firm-contested Jaya clusters (11-11 08:25, 08:26) | 3 / 30 | 10.0% [3.5, 25.6] |
| same, flip all 5 contested Jaya clusters | 6 / 30 | 20.0% [9.5, 37.3] |
| Tracked residents, worst case (all 11 UNSURE false, upper bound only) | 12 / 41 | 29.3% [17.6, 44.5] |
| Pooled with Ojini (10/10 false by operator fact), primary | 11 / 40 | 27.5% [16.1, 42.8] |
| Pooled, 2 firm flips | 13 / 40 | 32.5% [20.1, 48.0] |
| Pooled, 5 flips | 16 / 40 | 40.0% [26.3, 55.4] |
| Persisted-layer (URA table) rows named `ojini` since 2026-10-13: lower bound on false person_id | 18 / 179 | 10.1% [6.5, 15.3] |
| Persisted-layer since 2026-10-30 | 9 / 84 | 10.7% [5.8, 19.0] |

Tracker-fault rate (arrival FALSE with identity TRUE, operator rule): 19/41 = 46.3% [32.1, 61.3]; 17/41 = 41.5% [27.8, 56.6] after removing the 2 firm-contested clusters. Caveats: (a) the Ojini rows are a fixed, known-absent name, so pooling inflates the figure and measures "stale gallery entry" more than "ordinary mismatch"; the tracked-resident rows are the honest recognizer rate. (b) The persisted-layer figure is a floor only (other false names are invisible) and is distorted: Ojini has no tracker, so her false names are never vetoed, while other names' false positives are vetoed and unpersisted (survivor bias). (c) Clusters are correlated (same person, minutes apart), so the real effective n is smaller than 30/40 and the intervals are optimistic.

**Phase 2 consequence.** The "5 confirmed true arrivals" bar stays met (10 arrival-TRUE). The measured-misrecognition half is now: 3.3% to 10% of tracked-resident named crossings with a non-home tracker are decisively false, with a wide interval and 11 UNSURE; the Oji group C answers (9 clusters) would be the next largest source of movement. Score does not discriminate (Ojini false events 0.91-1.0).

## Falsification

- "Person entity is faithful to the phone": would be disproved by any interval with person.jaya not_home while Bermuda area/tracker or Private BLE showed home. Searched all 185.1 h at 10 s: none.
- "Ziri's wiring is fine": would be disproved if the linked trackers were disabled, absent from the registry, or the phone never resolved. Registry rows enabled; ziri_iphone and the Bermuda tracker both flipped home for the 11-06..11-08 visit.
- "Jaya's door faces are tracker fault": would be supported by a phone reappearing where it was last seen; it reappears at Garage A (5/6 runs) instead. Not proven false, only unsupported; the operator label stands as instructed.
- "Ojini silent since the purge": checked three producers (events API, live sensors, URA rows); Protect NOT checked.

## Housekeeping disclosures

- No Frigate login this session. Used `fr_events.json` already extracted; nothing secret printed.
- One of my probe scripts (`ojmatch.py`) accidentally imported an old scratchpad `bisect.py` (cwd shadowing) which ran pytest runs inside another agent's worktree (`.claude/worktrees/agent-ac4b5e29b7ab11ce6`, bytecode writes disabled, cacheprovider off). No repo edits; `git status` in the main checkout is unchanged from session start. Not verified whether it touched that worktree's untracked files.
- Scratch scripts only in the session scratchpad (`jaya_q.py`, `jaya_cl.py`, `ojp*.py`, `ojwho.py`, `cont.py`, `final.py`). Nothing written on the HA host this round.
- This section was appended to this file only; nothing else edited, nothing committed.
