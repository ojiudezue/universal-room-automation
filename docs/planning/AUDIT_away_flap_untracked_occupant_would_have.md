# AUDIT - Would the AWAY-flap guard have helped? (HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1)

**Written:** Sun 2026-10-18 00:3x CDT (`date` run at start: 00:14 CDT). Read-only. Data through ~00:15 CDT.
**Author:** ura-prober. **Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1 (`docs/planning/kanban.data.yaml:810`).
**Operator instruction (2026-10-17, verbatim):** "I want HVAC to go away fast. As long as that happens, house to be more careful. Also unclear if this works well? Rooms have no cameras only common areas. Measure when this would have helped if engaged first."
**Docs read completely first:** PRESENCE_ARCHITECTURE_STATE_OF_PLAY, SENSOR_FLEET_CLASSES, IDENTITY_FUSION_CAMERAS_MANUAL, HVAC_ARCHITECTURE_STATE_OF_PLAY, plus the card and `PLANNING_house_away_flap_untracked_occupant.md` (Rev 2).

## 0. Answer in six lines

1. **It fixes flap COUNT, not untracked-occupant TIME.** Simulated with the plan's own rule (camera-body stamp, W = 20 min) it absorbs 34 of 65 trip AWAY entries (52%) and 136 of 193 baseline entries (70%), but removes only 529 of 2,314 AWAY minutes (23%) in the windows where all four phones were away.
2. **Cameras cannot see the bedroom occupant.** During those windows the Guest Bedroom 2 complex (still-holding radar) was occupied for 487 AWAY minutes. 140 of them also had a camera body in the prior 20 min and the guard fixes those; the other 347 had no camera body and 344 of them stay AWAY (29% of the 487 fixed in total). Cameras saw a body inside only 1 of 65 trip AWAY episodes (between 3 min after entry and 3 min before exit); they saw the occupant when they walked past one, which is what ended most episodes (a census update was the exit trigger in the large majority).
3. **HVAC mostly does not need the house edge to go away.** For the 55 AWAY episodes of 30 min or more, 113 of 165 zone-episodes (69%) were already on the Away preset (zone vacancy) before the house flipped AWAY. Only 22% (36) were first moved by the house edge. Median time from a door-exit crossing to the zone reaching Away: 5.1 min (p90 22.2 min).
4. **A "HVAC fast, house careful" split costs HVAC nothing and keeps the non-HVAC benefit,** but it also leaves HVAC's own comfort hits in place (see section 4). Riding HVAC on the guarded signal would remove 364 occupied-zone minutes of away preset and give up about 556 empty-zone minutes of savings on the trip data.
5. **Security auto-arm is not live** (`security_auto_follow = false` in the live CM entry), so today's cost of the delay is zero. If it were on: 256 arm events over the window, 125 with an occupant inside (no door crossing at either end); the guard (W = 20) leaves 88 and 45. Every genuine departure of 30 min or more is delayed a median 19.5 min (max 24.6).
6. **Verdict:** worth building only as the cheap, house-side guard with a smaller W (10 min captures nearly all of the absorption at half the delay), HVAC left on the fast path, and with the camera-less hole stated plainly. It does not solve a guest in a bedroom. See section 6.

## 1. Method, sources, and what is NOT known

| Item | Source |
|---|---|
| AWAY entries and exits | URA DB `house_state_log` (UTC, naive), 2026-08-16 -> 2026-10-18 04:16Z. 258 AWAY entries. Window matches the plan's "59 normal days". |
| Camera body | URA DB `census_snapshots` zone=`house`, `total_persons > 0`. Verified this equals the plan's stamp (`unidentified_count > 0 or face > 0`) in the all-phones-away windows: 313 of 316 positive snapshots had unidentified > 0. |
| Door crossings | `person_entry_exit_events` (egress), direction exit/entry. |
| Room occupancy | `occupancy_events` entry/exit paired into intervals; room ids mapped through `.storage/core.config_entries`. |
| Tracked-phone state | HA recorder `person.*` (recorder only reaches back to 2026-10-10 09:12Z, so the "all four away" windows exist only for the trip). |
| Zone membership | Zone Manager config entry (`zones.txt` in scratch); Upstairs = `climate.up_hallway_zone_2` contains Guest Bedroom 2, its bathroom, closet, hallway, Game Room, Jaya, Ziri; Back Hallway = zone 3 contains Kitchen, GB1. |
| HVAC | URA DB `decision_log` (coordinator hvac, preset_change, `scope` = zone) and `ura_activity_log`. |
| Security | live `security_auto_follow` in `/config/.storage/core.config_entries` (CM entry): `false`. Code: `security.py:1094` short-circuits when off. |

Scripts and raw JSON: `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/d/` (`an6.py`..`an20.py`, `data*.json`, `trip_table.md`). The URA DB was queried in place read-only over `ssh ha` (`?mode=ro`) because the Samba copy is 1.4 GB.

**There is no ground truth for who was home.** The guest is stated by the operator (board / memory) but no sensor says "guest". Proxies, in decreasing strength: (a) door crossings bounding the episode, (b) camera body, (c) the Guest Bedroom 2 complex (Matter MS600 occupancy is a still-holding presence radar per SENSOR_FLEET_CLASSES; bathroom, closet, hallway are PIR/occupancy sensors), (d) other rooms (weak: Kitchen has ZX plus LD2410 radars with known fan phantoms; Garage B read occupied 22 h of the trip and is excluded as phantom). The Guest Bedroom 2 complex showed all four rooms occupied the full hour at 10-16 11:00 CDT, which is suspicious; treat its minutes as indicative.

## 2. Part 1 - AWAY entries with someone home vs genuinely empty

### 2.1 Trip (10-14 17:27 CDT -> 10-18 00:15 CDT, 78.8 h)
- 65 AWAY entries (19.8/day) totalling 2,295 AWAY minutes. Baseline rate was 3.2/day.
- Recorder: all four `person.*` not_home for 2,765 minutes (46.1 h); the house was AWAY for 2,314 of them (84%). Jaya was home the rest.
- GUEST mode armed twice in the whole trip (10-16 07:00-07:16, 10-17 16:06-16:52 CDT). The gate does not evaluate from AWAY (card investigation_2026_10_15), so guest mode contributed nothing.
- Door crossings: 51 of 65 entries had no exit crossing before and no entry crossing at the end (occupant inside throughout). 14 were door-bounded (an exit crossing before, or an entry crossing at the end; an entry at the end only shows someone came in, not that the house was empty before).

AWAY minutes inside the all-phones-away windows, by the best available evidence that someone was home (today, no guard):

| Evidence in that minute | AWAY minutes | Share |
|---|---|---|
| Camera body within the last 20 min | 517 | 22% |
| No camera, but Guest Bedroom 2 complex occupied | 347 | 15% |
| No camera, no GB2, but another (weaker) room occupied | 467 | 20% |
| No sensor evidence at all | 983 | 42% |

The 983 "no evidence" minutes cannot be split between an empty house and a silent occupant (10-15 08:00-22:00 and 10-17 07:00-15:00 are the long ones). They are reported, not claimed either way.

### 2.2 Every trip AWAY entry (times CDT; "W=20 guard" is the section 3 simulation)

| # | start CDT | AWAY min | door crossing | min since last cam body | GB2-complex occupied min | ended by | W=20 guard |
|---|---|---|---|---|---|---|---|
| 1 | 10-14 18:06 | 31.5 | none | 1.5 | 0 | census_upda | AWAY +19 min, residual 13 min |
| 2 | 10-14 18:42 | 6.5 | entry at end | 1.4 | 0 | census_upda | ABSORBED |
| 3 | 10-15 07:33 | 12.1 | exit before | 1.4 | 0 | census_upda | ABSORBED |
| 4 | 10-15 07:49 | 109.6 | exit before | 1.0 | 0 | census_upda | AWAY +19 min, residual 90 min |
| 5 | 10-15 09:41 | 6.1 | none | 1.5 | 0 | census_upda | ABSORBED |
| 6 | 10-15 09:50 | 1.8 | none | 2.7 | 0 | census_upda | ABSORBED |
| 7 | 10-15 09:55 | 29.5 | none | 1.0 | 0 | census_upda | AWAY +19 min, residual 10 min |
| 8 | 10-15 10:29 | 1.9 | none | 1.0 | 0 | census_upda | ABSORBED |
| 9 | 10-15 11:11 | 9.0 | none | 0.4 | 0 | census_upda | ABSORBED |
| 10 | 10-15 12:06 | 57.0 | none | 0.9 | 0 | census_upda | AWAY +20 min, residual 37 min |
| 11 | 10-15 16:18 | 109.5 | none | 0.5 | 0 | occupancy_c | AWAY +20 min, residual 89 min |
| 12 | 10-15 18:10 | 12.0 | none | 113.0 | 0 | census_upda | AWAY +0 min, residual 12 min |
| 13 | 10-15 19:01 | 238.6 | entry at end | 0.5 | 0 | census_upda | AWAY +20 min, residual 219 min |
| 14 | 10-16 07:36 | 60.2 | entry at end | 0.4 | 0 | census_upda | AWAY +20 min, residual 40 min |
| 15 | 10-16 08:37 | 14.5 | none | 61.5 | 14 | census_upda | AWAY +0 min, residual 14 min |
| 16 | 10-16 08:53 | 112.0 | none | 77.1 | 112 | census_upda | AWAY +0 min, residual 112 min |
| 17 | 10-16 10:49 | 26.3 | none | 3.6 | 26 | census_upda | AWAY +17 min, residual 9 min |
| 18 | 10-16 11:18 | 0.5 | none | 1.1 | 1 | deferred_re | ABSORBED |
| 19 | 10-16 11:20 | 0.5 | none | 2.6 | 1 | deferred_re | ABSORBED |
| 20 | 10-16 11:23 | 37.3 | none | 1.2 | 37 | census_upda | AWAY +19 min, residual 18 min |
| 21 | 10-16 12:04 | 19.0 | none | 2.0 | 19 | census_upda | AWAY +18 min, residual 1 min |
| 22 | 10-16 12:24 | 76.5 | none | 1.0 | 77 | census_upda | AWAY +19 min, residual 57 min |
| 23 | 10-16 13:44 | 2.9 | none | 1.1 | 3 | census_upda | ABSORBED |
| 24 | 10-16 13:51 | 0.6 | none | 0.9 | 1 | census_upda | ABSORBED |
| 25 | 10-16 13:53 | 27.0 | none | 1.0 | 1 | census_upda | AWAY +19 min, residual 8 min |
| 26 | 10-16 14:21 | 0.5 | none | 29.0 | 1 | deferred_re | AWAY +0 min, residual 1 min |
| 27 | 10-16 14:22 | 4.5 | none | 1.1 | 3 | census_upda | ABSORBED |
| 28 | 10-16 14:30 | 33.3 | none | 3.0 | 0 | census_upda | AWAY +17 min, residual 16 min |
| 29 | 10-16 15:06 | 1.0 | none | 39.4 | 0 | census_upda | AWAY +0 min, residual 1 min |
| 30 | 10-16 15:10 | 4.8 | none | 2.2 | 0 | census_upda | ABSORBED |
| 31 | 10-16 15:18 | 22.2 | none | 0.6 | 0 | census_upda | AWAY +20 min, residual 2 min |
| 32 | 10-16 15:44 | 1.2 | none | 2.4 | 1 | census_upda | ABSORBED |
| 33 | 10-16 15:46 | 0.5 | none | 4.5 | 1 | deferred_re | ABSORBED |
| 34 | 10-16 15:51 | 3.0 | none | 1.5 | 0 | census_upda | ABSORBED |
| 35 | 10-16 15:55 | 4.5 | none | 5.5 | 0 | census_upda | ABSORBED |
| 36 | 10-16 16:12 | 3.5 | none | 1.0 | 0 | census_upda | ABSORBED |
| 37 | 10-16 16:18 | 5.5 | none | 1.5 | 0 | census_upda | ABSORBED |
| 38 | 10-16 16:25 | 3.5 | none | 8.0 | 0 | census_upda | ABSORBED |
| 39 | 10-16 16:31 | 4.7 | none | 2.5 | 0 | census_upda | ABSORBED |
| 40 | 10-16 16:37 | 1.8 | none | 8.2 | 0 | census_upda | ABSORBED |
| 41 | 10-16 16:40 | 2.0 | none | 0.5 | 0 | census_upda | ABSORBED |
| 42 | 10-16 16:43 | 26.5 | none | 1.0 | 4 | census_upda | AWAY +19 min, residual 7 min |
| 43 | 10-16 17:10 | 63.1 | none | 1.0 | 63 | census_upda | AWAY +19 min, residual 44 min |
| 44 | 10-16 18:14 | 17.6 | none | 65.1 | 7 | census_upda | AWAY +0 min, residual 18 min |
| 45 | 10-16 18:35 | 36.5 | none | 2.0 | 36 | census_upda | AWAY +18 min, residual 18 min |
| 46 | 10-16 19:13 | 5.0 | none | 39.5 | 4 | census_upda | AWAY +0 min, residual 5 min |
| 47 | 10-16 19:19 | 0.5 | none | 1.0 | 0 | deferred_re | ABSORBED |
| 48 | 10-16 19:20 | 3.4 | none | 1.3 | 0 | census_upda | ABSORBED |
| 49 | 10-16 19:27 | 15.5 | none | 6.4 | 0 | census_upda | AWAY +14 min, residual 1 min |
| 50 | 10-16 19:43 | 1.0 | none | 1.0 | 0 | census_upda | ABSORBED |
| 51 | 10-16 19:45 | 13.9 | none | 3.1 | 0 | census_upda | ABSORBED |
| 52 | 10-16 20:00 | 0.5 | none | 0.4 | 0 | census_upda | ABSORBED |
| 53 | 10-16 20:02 | 0.5 | none | 1.9 | 0 | deferred_re | ABSORBED |
| 54 | 10-16 20:03 | 4.4 | none | 0.6 | 0 | census_upda | ABSORBED |
| 55 | 10-16 20:09 | 241.6 | entry at end | 1.0 | 70 | periodic | AWAY +20 min, residual 222 min |
| 56 | 10-17 07:02 | 114.1 | exit before | 1.0 | 0 | occupancy_c | AWAY +19 min, residual 95 min |
| 57 | 10-17 08:57 | 5.8 | none | 116.2 | 0 | occupancy_c | AWAY +0 min, residual 6 min |
| 58 | 10-17 09:04 | 366.2 | entry at end | 123.0 | 0 | census_upda | AWAY +0 min, residual 366 min |
| 59 | 10-17 15:26 | 7.5 | exit before | 0.2 | 7 | occupancy_c | ABSORBED |
| 60 | 10-17 15:35 | 2.5 | exit before | 1.2 | 3 | periodic | ABSORBED |
| 61 | 10-17 18:33 | 0.6 | entry at end | 0.0 | 1 | census_upda | ABSORBED |
| 62 | 10-17 18:37 | 3.7 | entry at end | 0.2 | 4 | census_upda | ABSORBED |
| 63 | 10-17 18:44 | 0.6 | entry at end | 1.9 | 1 | census_upda | ABSORBED |
| 64 | 10-17 18:47 | 22.5 | none | 2.0 | 5 | census_upda | AWAY +18 min, residual 4 min |
| 65 | 10-17 19:11 | 242.4 | entry at end | 1.0 | 0 | census_upda | AWAY +19 min, residual 223 min |


### 2.3 Baseline (08-16 -> 10-14 17:27 CDT, 59.5 days)
- 193 AWAY entries, 7,912 AWAY minutes (two multi-hour genuine episodes of 1,395 and 1,599 min dominate the minutes).
- 118 door-bounded (67 under 5 min, 81 under 15 min, 29 of 30 min or more). These are mostly people stepping out and back (exit crossing, AWAY, back inside within minutes), not an untracked occupant.
- 75 with no door crossing at either end (occupant inside throughout): 39 under 5 min, 58 under 15 min, 10 of 30 min or more.
- Guest context: 146 GUEST sessions in the window (181.6 h total; 144 before the trip, median 34 min). 46 baseline AWAY entries began during or within 3 h after a GUEST session; 48 had the Guest Bedroom 1 or 2 complex occupied for 3 min or more inside the episode.
- Caveat: "no door crossing" assumes the five egress cameras catch every crossing. `person_entry_exit_events` is the only crossing record; a missed crossing would put a real departure in the "inside" bucket.

## 3. Part 2 - Would the card's mechanism have prevented the AWAY?

**Mechanism (plan Rev 2, `PLANNING_house_away_flap_untracked_occupant.md` D1-D3):** AWAY on all three branches (nobody-home, path alpha, path beta) is held until `now - last camera body >= W`, where "camera body" = `unidentified_count > 0 or face_recognized_count > 0` from the census payload; BLE never moves the stamp; discharge is the existing 60 s periodic inference; default W = 1200 s.

**Simulation:** replay each real AWAY entry at t0; the entry starts at the first time T >= t0 with no body in the previous W min (bodies seen after t0 push T out; +30 s for the 60 s periodic); if T >= the real exit time the AWAY never happens (ABSORBED). Hysteresis (up to 120 s) not added. Assumes the real exit time is unchanged.

| W (min) | Trip entries absorbed (of 65) | Baseline absorbed (of 193) | Trip AWAY min, all phones away (of 2,314) | of those with GB2 occupied (of 487) | Median delay of AWAY >= 30 min |
|---|---|---|---|---|---|
| 0 (today) | 0 | 0 | 2,314 | 487 | 0 |
| 5 | 22 | 101 | 2,160 | 447 | 4.5 |
| 10 | 31 | 116 | 2,018 | 412 | 9.5 |
| 15 | 33 | 131 | 1,899 | 379 | 14.5 |
| 20 (default) | 34 | 136 | 1,785 | 344 | 19.5 |
| 30 | 42 | 146 | 1,592 | 278 | 29.5 |

By evidence class at W = 20 (trip): inside-throughout entries 27 of 51 absorbed, door-bounded 7 of 14 absorbed. Entries shorter than 10 min: 32 of 36 absorbed (the 4 that remain are camera-blind or unknown).
Inside-throughout breakdown, trip (51): camera body within 5 min before entry: 24 absorbed, 15 remain; GB2 complex occupied and camera-blind: 4 remain; neither: 3 absorbed, 5 remain. Baseline (75): camera-seen 50 absorbed, 11 remain; blind/none 4 absorbed, 10 remain.

**Where it works:** the many 0.5-6 min flaps where a camera saw the person 1-3 min before the AWAY (10-16 13:44..20:03: 24 short entries absorbed). **Where it fails:**
- 10-16 08:37 (14.5 min), 08:53 (112 min), 18:14 (17.6), 19:13 (5.0): the last camera body was 39-77 min earlier and the Guest Bedroom 2 complex was occupied; the guard changes nothing (AWAY +0 min delay because the quiet period had already elapsed).
- 10-16 20:09 (241.6 min), 10-17 19:11 (242.4 min), 10-15 19:01 (238.6 min): a camera saw someone 0.5-1.0 min before entry, so AWAY is held 19-20 min, then the house is AWAY for about 220 more minutes with an occupant in a camera-less room (GB2 occupied 70 min inside the 10-16 episode). The guard only shifts these.
- 10-17 09:04 (366 min) and 10-15 18:10: no camera for 113-123 min, no room evidence. Unknown (empty or silent).

**Do the sensors it uses see the occupant?** The stamp uses only cameras: `camera_person_entities` in the live integration entry = playroom, master_hallway, staircase, foyer_fisheye, family_room, upstairs_hall, stairs_top (core.config_entries). Room cameras are configured only on Living Room (family_room) and Upstairs Hallway; bedrooms, bathrooms, closets, Kitchen, Study, Garage have none. Result: 1 of 65 trip episodes had a camera body 3 min after entry through 3 min before exit. The guard is blind to a person who stays in a bedroom; it relies on the person walking past a hallway camera every W minutes.

## 4. Part 3 - HVAC side

### 4.1 How fast does HVAC go away today after a true departure?
- Strict genuine departures (exit crossing within 30 min before the AWAY, episode of 30 min or more, no camera or GB2 evidence inside): 14 episodes (12 baseline, 2 trip), 42 zone-episodes. 16 were already on Away at the exit. For the other 26: exit crossing -> zone Away median 5.1 min, p75 8.0, p90 22.2, max 37.2. Cause of that first Away write: house-state edge 17, zone vacancy 8, stale occupancy 1.
- All 55 AWAY episodes of 30 min or more (165 zone-episodes): 113 (69%) already on Away before the house edge; 36 (22%) first moved by the house edge (delay 0.0 min after it); 15 by zone vacancy a median 11.4 min after the edge (p90 20.3, max 70.9); 1 never. Source: `decision_log` hvac preset_change, `scope` zone.
- So HVAC already goes away fast through its own zone vacancy (5-min grace, HVAC doc 3.2/knob 48); the house edge is the first mover in about 1 of 5 zone-episodes.

### 4.2 Decoupled design (HVAC fast, house careful) vs HVAC riding the guarded signal
Trip, all-phones-away windows (2,765 min = 8,295 zone-minutes). Zones sat on the Away preset 8,155 zone-min (98%). Away zone-minutes by the cause of the last write and whether any room in the zone was occupied (raw `occupancy_events`, includes hold tails, so "occupied" over-states comfort hit):

| Cause of away preset | Zone empty | Zone had an occupied room | Total |
|---|---|---|---|
| House-state edge (`house_state_transition`) | 1,985 | 775 (zone 1: 89, zone 2: 385, zone 3: 301) | 2,760 |
| Zone vacancy / runtime / stale (`vacant_past_grace` etc.) | 4,599 | 796 (zone 1: 13, zone 2: 417, zone 3: 366) | 5,395 |

- **Decoupled (HVAC unchanged):** keeps all 1,985 empty-zone edge minutes of savings, keeps all 775 occupied-zone edge minutes as comfort hits, and does nothing for the 796 vacancy-caused ones. Cost to HVAC: zero. Benefit to HVAC: zero.
- **HVAC on the guarded signal (W = 20):** the guard removes 920 of the 2,760 edge-caused zone-minutes (33%): 364 were occupied-zone (comfort hit avoided; 47% of the 775) and 556 were empty-zone (savings given up; upper bound, zone vacancy would send many of those zones away after its own grace). 411 occupied-zone edge minutes remain. The 796 vacancy-caused ones are untouched either way.
- Preset writes: trip 237 total, 170 edge-caused; 70 of those edge-caused writes fall inside absorbed episodes (W = 20; 67 at W = 10). Baseline: 198 of 2,191 edge-caused writes (9%) fall inside absorbed episodes (3.4/day).
- Departure savings given up if HVAC rides the guard: the 36 zone-episodes first moved by the edge x about 19.5 min = about 700 zone-minutes over 63.6 days (about 11 zone-min/day); at W = 10 about 340.
- Ratio on the trip: 1.5 savings-minutes given up per comfort-minute avoided (556 / 364). Baseline edge-caused away zone-min (6,192) removed by the guard: 1,712 (28%); in the 75 inside-throughout episodes 448 of 936 (48%).

## 5. Part 4 - Genuine departures delayed (security auto-arm and other AWAY consumers)

- **Security auto-arm is OFF live.** `security_auto_follow = false` (`/config/.storage/core.config_entries`, CM entry); `security.py:1094` returns before queueing the intent; no switch entity exposes it (grep `switch.py`). So the real cost of the delay today is 0 arms delayed. `alarm_control_panel.elkm1_area_1` has been `disarmed` since 10-13 20:53 CDT (recorder). When enabled, `SECURITY_AUTO_FOLLOW_ARM_DELAY_S = 30` (const.py:3151) does not absorb flaps of 1-15 min.
- **If it were on, delayed departures** (AWAY episodes, 63.6 days): 55 of 30 min or more (0.87/day), 28 of 60 min or more, 14 strict genuine. Delay = W minus the time since the last camera body at the AWAY decision: W = 5: median 4.5 (max 9.6); W = 10: 9.5 (max 14.6); W = 20: 19.5 (p90 20.4, max 24.6). Zero were absorbed.
- **Arm events with an occupant inside (if on), 30 s debounce:** today 256 (baseline 192, trip 64), of which 125 inside-throughout (75 + 50). W = 10: 111 / 57. W = 20: 88 / 45. The guard roughly halves false arms; it does not zero them.
- **Exterior person alerts (NM), trip window:** 440 CRITICAL `exterior_person` alerts fired while the house read AWAY (deduped by second/title/location); 132 of them (30%) fall in minutes the W = 20 guard would turn non-AWAY (CRITICAL -> HIGH/MEDIUM under `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY`, const.py:2314). 308 stay CRITICAL because the occupant is still camera-blind. Counts are notification_log rows, not delivered pages.

## 6. Part 5 - Verdict

**Does the change pay off?** For flap count and churn, yes: about half of trip entries and 70% of baseline entries disappear, 41% of the trip's edge-driven thermostat writes, 30% of the CRITICAL exterior alerts, and roughly half of the false auto-arms (if auto-follow were ever enabled). For "an untracked occupant is protected", mostly no: it protects 23% of AWAY minutes in the trip and 29% of the minutes with the bedroom radar occupied, because it keys on cameras.

**Would a decoupled "HVAC fast / house careful" split capture most of the value?** Yes for the non-HVAC consumers (alerts, arming, lights sweep, someone-home), at zero HVAC cost, and HVAC already goes away on its own vacancy in 69% of zone-episodes. No for HVAC comfort: the split leaves 775 occupied-zone edge minutes plus 796 vacancy-caused minutes (1,571 zone-min on the trip) in place, and the guard would fix at most 364 of them. If HVAC comfort for the untracked occupant matters, the lever is the HVAC occupancy rules for camera-less rooms, not the house state. Mechanically the split needs HVAC to read the unguarded inference while others read the guarded one (the plan routes everything through one house-state signal; this is new scope, not costed here).

**Recommended shape (for the operator to decide, not done):**
1. W = 10 min rather than 20: 31 of the 34 trip absorptions and 116 of 136 baseline at half the departure delay (9.5 vs 19.5 min). The curve flattens from 15 up.
2. Guard the house-state consumers; leave HVAC on the fast path (operator instruction). Consider a separate HVAC-side hold for the "house edge returns within minutes" churn only if the 3.4 writes/day matters.
3. State the hole: a guest in a bedroom is invisible to this guard.

**What fails for occupants in camera-less bedrooms (observed):** 4 dedicated blind entries (10-16 08:37, 08:53, 18:14, 19:13: 149 AWAY min, 137 of them with GB2 occupied, no camera body for 39-77 min before entry); 3 long episodes (about 240 min each) where the guard only shifts the start by 19-20 min; 344 of 347 camera-blind GB2 AWAY minutes unchanged. Candidate fills, each with a trade: (a) a still-holding presence radar veto on AWAY for rooms with a ZK/ZX/Matter-MS600 radar (parked in plan section 10; the GB2 radar is exactly that class; would cover about 350-490 AWAY min but the Kitchen radars carry fan phantoms, 17.6 h occupied on the trip); (b) the estimator's door tally (egress crossings with no exit imply someone is still inside; 51 of 65 trip entries had no exit crossing); (c) accept it.

## 7. Falsification and uncertainty

- *If the guest was not home,* the 487 + 467 "evidence" minutes are phantoms and the guard's lost-savings side dominates. Observation that would show it: no GB2 radar rise-edges while the garage reports an exit. Not available; the operator's statement is the only anchor.
- *If egress misses crossings,* "inside throughout" (51/65, 75/193) over-counts. Observation: reconcile `person_entry_exit_events` against `person.*` home/not_home edges (recorder, 10-10 on). Not done.
- *Simulation is open-loop:* it keeps the real exit time, ignores the 120 s state-machine dwell (adds delay), and ignores that holding the house home could change when ARRIVING is declared. Real behaviour could absorb more or fewer.
- *"Zone occupied" for HVAC uses raw room occupancy,* including hold tails; comfort-hit minutes are an upper bound.
- *Disproof tests run:* the stamp predicate (313/316 snapshots with total>0 had unidentified>0); whether cameras saw anyone inside episodes (1/65); whether HVAC depends on the house edge (22%, measured).
- Not checked: lights AWAY sweep (Kitchen automation is OFF per card text), someone-home binary sensor automations, EVSE/battery (plan says no subscription), whether the Matter GB2 radar is fan-susceptible.
