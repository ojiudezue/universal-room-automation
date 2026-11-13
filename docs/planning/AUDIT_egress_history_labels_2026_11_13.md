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
