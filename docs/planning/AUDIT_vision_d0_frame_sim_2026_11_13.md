# AUDIT: VISION-CROSSING-ANALYSIS-1 D0-FRAME and D0-SIM (read-only probe)

Run 2026-11-13 00:30 CST (CDT ended 2026-11-01; Frigate titles before that date are CDT). Card VISION-CROSSING-ANALYSIS-1.
Design under test: `PLANNING_person_sighting_layer.md` §15.3, §15.4a (D0-FRAME), §15.5, §15.5a, §15.6 (D0-SIM), read from branch
`plan/face-arrival-rebuild`. Nothing was changed; no OpenAI or other model was called. Not committed.

## Answer first

1. **The plan anchors the wrong clock. This is the headline.** The plan treats `t0` (the crossing emit) as "0-20 s after the camera
   edge" (§15.5 stage table). In code `t0` is **edge + 45 s**: `transit_validator.py:1274` schedules `_resolve_direction` with
   `async_call_later(..., self.ENTRY_WINDOW_SECONDS)` (`const.py:3296`, 45), `ura_person_egress_event` fires inside it
   (`transit_validator.py:2018`), and the DB row is stamped `datetime.utcnow()` at write (`database.py:4628`). Frames sampled at
   `t0 + offset` are taken 45+ s after the person reached the door.
2. **Measured consequence (sensor-on proxy, 69 recorder-backed garage-A/front clusters, 2026-11-05 on):** anchored at `t0`, the
   fast pass finds **0 guarded frames on 63 %** of crossings (garage A 60 %, front 73 %) and 3 frames on only 30 %. Anchored at the
   camera edge `E = t0 - 45 s`, 3 of 3 frames exist on 100 % of crossings (Wilson 95 % lower bound 94.7 %).
3. **Go/no-go:** D0-FRAME **GO only if capture is edge-anchored** (listener at the camera edge, not the crossing event). As written
   (t0-anchored) it is **NO-GO**. D0-SIM: F-stage and B-window chain coverage **FAIL as written**, pass-or-near-pass if
   edge-anchored (B window needs >= 90 s). Volume and concurrency **PASS** (14 crossings/day, 1-2 concurrent sequences).
4. **Not measured, and the gate cannot be closed without it:** real person-in-frame labels. Frigate per-update MQTT payloads
   (box, frame time) are not retained anywhere readable, and the 30-frame operator hand-label is not done. Every "blank" figure
   below is a **detection-state proxy** (a sensor or Frigate event says a person is tracked), an upper bound on non-blank.

## Method and sources (all read-only)

| Source | How | Result used |
|---|---|---|
| `person_entry_exit_events`, 2026-10-31 00:00Z to 2026-11-13 03:00Z | `ssh ha sqlite3 -readonly`, `select ... from person_entry_exit_events` | 187 rows on garage A + front groups, 185 crossings after 10 s leg dedupe, 117 clusters at 120 s gap |
| Door grouping | `.storage/core.config_entries` URA option `door_groups` | `doorbell_lite`->garage_a, `garage_a`->garage_a, `front_door_aerial`->front, `madrone_g6_entry`->front |
| Interior neighbours | same entry, `door_interior_neighbours` | garage_a: garage_hallway, staircase, stairs_top; front: foyer_fisheye, family_room (no master_hallway) |
| Frigate 2 event list | HA websocket `media_source/browse_media` on `media-source://frigate/frigate-f2/event-search/clips/...` (HA token, read-only). Gives event id (start epoch), duration s, top score, label. Only events with a clip are listed | Person events per camera since 2026-10-30 06:00Z (Frigate retention floor), 11 cameras + 5 exterior |
| Snapshot / thumbnail / clip availability | `GET /api/frigate/frigate-f2/notifications/<id>/snapshot.jpg`, `/thumbnail/<id>`, `.../clip.mp4`, 40 random Person events per door camera | table below |
| Detection state history | HA REST `/api/history/period` for the 8 door sensors. **Recorder history only reaches back to 2026-11-05 13:25Z**, so sensor-based figures use the 69 clusters from that date | sensor on-intervals |
| Direct Frigate API (`:5000`, `:8971`) | tried; `:8971` needs a login I was not given, `:5000` closed. Not used. HA's proxy exposes no events-list route (404) | media_source browse was the substitute |

Day/night: local hour < 07 or >= 18 is night (approximation, no sun lookup). `E = t0 - 45 s`; validated: sensor-blank at
`E-1` is 84 % and at `E+0` is 0 %, so the estimate is aligned to about 1 s.

Scripts: scratchpad `w/an.py` ... `an5.py`, `snap.py` (not committed; scratchpad
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/w/`).

## Finding 0: plan-vs-code discrepancies this probe found

| # | Plan statement | Verified reality | Evidence |
|---|---|---|---|
| 0a | `t0` is 0-20 s after the camera edge (§15.5 "Edge" row) | `t0 = edge + 45 s` (ENTRY_WINDOW for both directions; EXIT_WINDOW 30 s is not used by the delayed resolve) | `transit_validator.py:1274`, `:2018`; `const.py:3296`; `database.py:4628`; Frigate event start minus (t0-45) p10/p50/p90 = -7.4 / -0.6 / +8.7 s over 103 matched clusters |
| 0b | Doorbell Lite is in the Front group (§15.5 table: "Front (doorbell_lite + front_door_aerial)") | Live `door_groups` puts doorbell_lite in **garage_a**; operator fixture says the same | `.storage/core.config_entries` `door_groups`; `FIXTURE_camera_paths_interior.md` "Operator answers" |
| 0c | 14.4 crossings/day, 3-25 range, worst 25 (§15.5) | garage A + front only: **14.1/day** mean over 13.1 d; full-day p50 12, p90 26, **max 30** (2026-10-31). Worst-case cap should be >= 40, not 25 | table V1 below |
| 0d | F frame 1 = Frigate event best snapshot (§15.5 table) | best snapshot 404s on **17.5 % of doorbell_lite and 30 % of madrone_g6_entry** Person events (garage A and front_door_aerial 100 %); thumbnail 200 on 160/160 | table F3 |

## D0-FRAME

### F1. Blank rate by anchor (sensor-on proxy, 69 clusters, 2026-11-05 on; "blank" = none of the door group's 4 sensors on)

| Door | n | t0 + 0 | t0 + 3 | t0 + 6 | E + 0 | E + 1 | E + 3 | E + 6 | E + 8 |
|---|---|---|---|---|---|---|---|---|---|
| garage A | 50 | 78 % (Frigate events, 83 clusters) | 80 % | 82 % | 0 % | 0 % | 2 % | 0 % | 0 % |
| front | 19 | 79 % | 71 % | 68 % | 0 % | 0 % | 0 % | 16 % | 21 % |
| both | 69 | 79 % | 77 % | 78 % | 0 % | 0 % | 1 % | 4 % | 6 % |

Garage-A t0 row is the Frigate-event proxy over all 83 garage-A clusters (13 days, no recorder limit); the sensor proxy on its 50
cluster subset gives 0-3 % at E offsets. The two proxies agree on direction: **t0-anchored blank 77-82 %, edge-anchored 0-6 %.**
Front tails off after E+6 (16-21 % blank): the front door cameras stop tracking sooner (continuous detection span from first-on:
front p10/p50/p90 = 5.3 / 14.1 / 61.7 s; garage A 16.1 / 29.8 / 82.3 s).

Day vs night (sensor proxy, edge-anchored): garage A day 0-3 % blank, night 0 %; front day 0 % to E+3, night 0 %. t0-anchored
(Frigate-event proxy): garage A day 73-80 %, night 85-89 %; front day 77-86 %, **night 50-67 %** (n=12, small). Night is not
worse edge-anchored on this sample; sample is 39 night clusters, IR-specific failure of the detector is not visible here and is
not a person-in-frame test.

### F2. 3-frame sets, event-start anchored (Frigate events matched within +-60 s of E, n = 103 of 117 clusters)

| Door | n | set (s after event start) | >= 2 of 3 with person | 3 of 3 | 0 of 3 (all blank) |
|---|---|---|---|---|---|
| garage A | 72 | (0,1,2), (0,1,3), (1,2,3) | 100 % | 100 % | 0 % |
| garage A | 72 | (0,2,4), (0,2,5) | 100 % | 98 % | 0 % |
| front | 31 | (0,1,2), (0,1,3) | 100 % | 93 % | 0 % |
| front | 31 | (1,2,3), (0,2,4), (0.5,1.5,2.5) | 93 % | 93 % | 0 % |

Day/night split is the same within 5 points (n=21+10 front). Cause of the front 7 %: 2 of 31 matched events lasted <= 2 s
(3 of 103 overall are <= 1 s). Event duration p10/p50/p90 = 6 / 18 / 42 s.

### F3. Frame-source availability (40 random Person events per camera, 2026-10-30 on)

| Frigate camera | Best snapshot 200 | Thumbnail 200 | Clip 200 (8 each) | 404 snapshot: event dur (s) |
|---|---|---|---|---|
| garage_a | 40/40 | 40/40 | 8/8 | none |
| doorbell_lite | 33/40 | 40/40 | 8/8 | 21,21,7,23,5,23,19 |
| front_door_aerial | 40/40 | 40/40 | 7/8 (one 400, dur 6 s) | none |
| madrone_g6_entry | 28/40 | 40/40 | 8/8 | 134,11,10,13,16,14,34,37,25,16,53,56 |

Clips are large (5-116 MB, 1-22 s to fetch through the proxy) but present: **a retrospective frame extract from the clip is a
working fallback** and needs no live capture. I did not extract frames (no detector available, and out of scope).

### F4. Who owns the frame: a single fixed camera is blank about half the time

| Door group | Camera / leg | on at E+0 | E+3 | E+6 |
|---|---|---|---|---|
| garage A | garage_a Protect / Frigate | 24 % / 52 % | 50 % / 52 % | 54 % / 56 % |
| garage A | doorbell_lite Protect / Frigate | 18 % / 38 % | 32 % / 46 % | 48 % / 56 % |
| front | front_door_aerial Protect / Frigate | 26 % / 21 % | 47 % / 53 % | 47 % / 42 % |
| front | madrone_g6_entry Protect / Frigate | 16 % / 58 % | 32 % / 79 % | 26 % / 79 % |

The "~0 % blank" in F1 is the **union** across the group's cameras. The plan's F stage is "door camera only" (§15.5 stage table);
fixing one camera per door would blank 21-79 % of crossings. The guard must pick the camera whose detector is on at capture
time (rule 1 of §15.5a does this implicitly if evaluated across the group; say so in the plan).

### F5. Crossings with no Frigate Person event at all (clip-bearing list)

| Door | Frigate-leg cluster, event | Frigate-leg, none | Protect-only, event | Protect-only, none |
|---|---|---|---|---|
| garage A | 61 | 6 | 11 | 5 |
| front | 23 | 1 | 8 | 2 |

14 of 117 clusters (12 %) have no clip-bearing Person event within +-60 s of the edge; 26 of 117 (22 %) have only a Protect leg.
So Frigate-event-id-driven frames (§15.5a) cover about 88 % of crossings; the rest need the Protect thumbnail / live-grab
branch. Caveat: the listing only shows events with a clip, so events without one count as "none" here.

### F6. Gate (plan §15.4a thresholds)

| Threshold | As written (t0-anchored) | Edge-anchored | Verdict |
|---|---|---|---|
| >= 2 of 3 frames with a person on >= 95 % of events | 33 % (n=69) | 100 % (69/69, Wilson low 94.7 %); event-start sets 100 % garage, 100 % front for (0,1,2) | **FAIL as written; PASS edge-anchored (borderline on Wilson bound, n small)** |
| 0 all-blank sets on >= 99 % | 63 % all-blank | 100 % (0 all-blank in 69; 0 in 103 on the event proxy) | **FAIL as written; PASS edge-anchored** |
| 3rd frame exists by t0 + 6 s p90 | meaningless: t0 is edge + 45 s | 3rd frame at E + 2 s (frames at 0, 1, 2 s, spacing >= 1 s) | **Restate the threshold as E + 6 s, not t0 + 6 s** |
| Automatic label agrees with operator hand label >= 95 % (30 frames/camera) | not run | not run | **OPEN, operator action; the whole gate is a proxy until then** |

**D0-FRAME verdict: GO conditional on (1) edge-anchored capture and (2) the 30-frame label check passing.** Not measured:
Frigate update cadence (the plan's "next two updates with a box" supply), whether box-in-frame holds at those frames, true night
IR failure rate.

## D0-SIM

### V1. Crossing volume (garage A + front, 2026-10-31 00:00Z to 2026-11-13 03:00Z = 13.1 d)

| Measure | Value |
|---|---|
| Deduped crossings | 185 (127 garage A = 9.7/day; 58 front = 4.4/day) = **14.1/day** |
| Direction | garage A 68 entry / 59 exit; front 26 entry / 32 exit |
| Per local day (full days) | p50 12, p90 26, max 30; 2026-11-08 = 26, 2026-10-31 = 30, 2026-11-10 = 2 |
| Local hour peak | 07:00 (27), 16-17:00 (17 + 44), then thin; 22:00 has 10 |
| Peak person count (rows) | 1: 126, 2: 53, 3: 4, none: 6 |

### V2. Sequence clustering and concurrency (plan rule: same-door crossing during an open window extends it, cap 180 s)

| B window | Sequences | per day | Extended | Max crossings in one | Max concurrent (any doors) |
|---|---|---|---|---|---|
| 30 s | 165 | 12.6 | 19 | 3 | 1 |
| 60 s (plan) | 133 | 10.1 | 36 | 5 | 1 |
| 90 s | 125 | 9.5 | 37 | 5 | 2 |

`CROSSING_VISION_MAX_CONCURRENT = 2` covers every observed day (plan said "at most 2 doors in 300 s"; here 1 at 60 s, 2 at 90 s).

### V3. F stage timeline (3 guarded frames, spacing >= 1 s, max wait 6 s; call latency L = 3 s MODELED, D0-V will measure)

| Design | Frame availability (n=69) | First count lands after camera edge E | Lands <= 30 s after edge |
|---|---|---|---|
| A: trigger = crossing emit t0 (as written) | 3 frames 30 %, >= 2 33 %, >= 1 36 %, **0 = skipped_blank 63 %** | p50 50 s, p90 54 s (of the 25 that fire) | 0 % |
| B: capture armed at the camera edge, analyse once direction resolves or on the clip | 3 frames 100 % | p50 5 s, p90 5 s (frames done at E+2, plus L) | 100 % |

Design B means the F call cannot wait for direction (resolved at E+45); direction is a vision output, which §15.3 item 8 already
lists. If F is kept at t0 it is a post-hoc description, not a "fast" pass. A hybrid is possible: capture/hold frames at E (or pull
them from the Frigate clip at t0), call at t0.

### V4. B stage (time-lapse) frames, schedule from §15.5: door at 0,5,10,15,20,30,40,50,60 s; up to 2 chain cameras at 5,15,...,55 s; 21 scheduled; blank dropped

| Anchor | Door/dir | n | Door frames kept p50 | Chain kept p50 | Total p50 / p90 | Door kept = 0 | Chain kept = 0 | > 12 |
|---|---|---|---|---|---|---|---|---|
| t0 (as written) | garage A entry | 27 | 0 | 1 | 2 / 8 | 66 % | 44 % | 7 % |
| t0 | garage A exit | 23 | 2 | 0 | 2 / 7 | 43 % | 82 % | 4 % |
| t0 | front entry | 9 | 2 | 0 | 5 / 9 | 33 % | 77 % | 0 % |
| t0 | front exit | 10 | 0 | 0 | 0 / 7 | 90 % | 90 % | 0 % |
| E (edge) | garage A entry | 27 | 6 | 1 | 8 / 11 | 0 % | 37 % | 3 % |
| E | garage A exit | 23 | 6 | 0 | 7 / 11 | 0 % | 65 % | 4 % |
| E | front entry | 9 | 6 | 0 | 7 / 13 | 0 % | 55 % | 11 % |
| E | front exit | 10 | 3 | 0 | 3 / 8 | 0 % | 90 % | 0 % |

Door frames use the door-group sensors (recorder, 69 clusters); chain frames use Frigate Person events on the chain camera. The
cap of 12 almost never binds (0-11 %). Interior chain used: garage A = staircase, stairs_top; front = foyer_fisheye, family_room
(live `door_interior_neighbours`). Exterior chain for exits: garage A = rear_ptz, g5_bullet; front = front_side_ptz,
utilities_ptz. Exits on the front door reach a chain camera on only 2 of 19 crossings: the exterior chain is mostly empty.

### V5. Hop times (Frigate Person event start on a chain camera, seconds after edge E; all 13 days)

| Door | Dir | n | Any chain cam within E-10..E+180 | First hop p10 / p50 / p90 | Hops that start before E+45 (i.e. before a t0-anchored window even opens) |
|---|---|---|---|---|---|
| garage A | entry | 46 | 67 % (staircase 30, stairs_top 7) | 12 / 34 / 67 s | 70 % |
| garage A | exit | 37 | 54 % (g5_bullet 15, rear_ptz 6) | -3 / 18 / 162 s | 65 % |
| front | entry | 15 | 53 % (foyer 7, family_room 4) | 2 / 18 / 117 s | 75 % |
| front | exit | 19 | 10 % | 15 / 34 / 34 s | 100 % |

Entries whose first interior hop falls inside a window of length W after the edge (of those that hop at all):

| W | garage A entry | front entry |
|---|---|---|
| 30 s | 48 % | 62 % |
| 60 s | 84 % | 88 % |
| 90 s | 94 % | 88 % |
| 120 s | 97 % | 100 % |
| 180 s | 100 % | 100 % |

Only 57 % (garage A) and 47 % (front) of ALL entries reach a chain camera within 60 s; 33-47 % never reach one in 300 s (they
walk to a camera outside the live neighbour list, or no camera sees them). Coverage by chain is therefore capped around 55-67 %
regardless of window.

### V6. Daily call and frame volume (counts only; per-call tokens and dollars not re-derived, they need D0-V usage)

| Item | Measured | Plan §15.5 |
|---|---|---|
| F calls/day | 14.1 (design B), 5.2 sent / 8.9 `skipped_blank` (design A) | 14.4 |
| B calls/day (60 s window, clustering) | 10.1 | 10.5 |
| F frames/day (3 per call) | 42 (design B) | not stated |
| B frames/day (kept, p50 ~7 per crossing, cap 12) | about 70 | not stated |
| Days exceeding plan worst case 25 | 3 of 13 (30, 26, 26) | worst = 25 |
| Interior head count (§15.8) | modeled 48/day, not simulated (no occupancy-by-time probe run) | 48 |

At measured volume the plan's per-day cost envelope (about $0.30 mean, $0.68 worst at modeled tokens) is unchanged in count terms;
nothing here changes the cost row.

### V7. Gate (plan §15.6 pass/fail table)

| Check | Pass bar | As written (t0) | Edge-anchored | Verdict |
|---|---|---|---|---|
| F lands by t0 + 12 s | >= 90 % | vacuously true but 63 % of crossings send nothing | n/a (lands E + 5 s) | **FAIL as written** |
| F sends >= 2 non-blank frames | >= 95 %, 0 blank sent | 33 % | 100 % (proxy; Wilson low 94.7 %) | **FAIL as written; conditional PASS** |
| B inside census interior hold (t0+180 s) | >= 95 % | not measured (needs census clock; B lands t0 + 70-90 s modeled, unmeasured) | same | **OPEN** |
| B window holds every chain camera the person hit in first 60 s | >= 90 % of entries | hops inside [t0, t0+60] = 22 % garage A, 12 % front | inside [E, E+60] = 84 % garage A, 88 % front; 94 % / 88 % at 90 s | **FAIL as written; near-pass edge-anchored at W = 90 s (garage A), 120 s (front)** |
| Entry S inside 300 s TTL | >= 95 % | holds on the modeled clock; not measured | same | **OPEN (not measurable without a call-latency number)** |
| No day exceeds the daily cap or 2 concurrent sequences | 100 % | cap at 25 would be exceeded on 3 of 13 days; concurrency max 1 (60 s) / 2 (90 s) | same | **PASS on concurrency; set cap >= 40** |
| Measured daily cost <= envelope x 1.5 | | counts at or under plan | same | **PASS on counts; cost unmeasured (D0-V)** |

**D0-SIM verdict: NO-GO as written; GO if the plan (1) re-anchors capture and the B window to the camera edge, (2) lengthens B to
90 s and states a 55-65 % ceiling on chain coverage, (3) sets the daily cap >= 40.**

## Recommended plan edits (not applied; the plan is not mine to change)

1. Correct §15.5 "Edge" row: `t0 = edge + 45 s`, and define a distinct `E` (camera edge time, available as the `timestamp` field of
   `ura_person_egress_event`, `transit_validator.py:2019`). Anchor F and B to `E`.
2. Decide F trigger: edge-armed listener on the door-group sensors, or retrospective clip extract at t0 (clips present, 23 of 24 sampled).
3. Replace "best snapshot (frame 1)" with a source chain: best snapshot, else thumbnail (160/160), else clip frame; Protect-only crossings (22 %) use
   the Protect thumbnail.
4. Guard must evaluate across the door group's cameras, not one camera (F4).
5. Fix §15.5 table: doorbell_lite belongs to garage A.
6. Raise the daily-cap worst case to >= 40 calls per stage and keep concurrency 2.

## Not verified / caveats

| Item | Why |
|---|---|
| True person-in-frame | no boxes retained, no hand labels, no local detector run; sensor-on and Frigate-event presence are upper bounds |
| Frigate update cadence | per-update MQTT payloads are not stored anywhere I can read; the plan's "next two updates" cannot be sized |
| Recorder-backed sample | sensor figures cover 69 of 117 clusters (history starts 2026-11-05 13:25Z), front n=19 only |
| Event list completeness | Frigate listing shows only clip-bearing events; "no event" in F5 may include clip-less events |
| Day/night | hour cutoff, not sun; night n=39 clusters |
| Latency L = 3 s | modeled; D0-V supplies the measured value |
| Tokens/cost | not re-derived |
| Hop chain cameras | `staircase` assumed to be the "garage hallway/stairs" camera (live `door_interior_neighbours` lists `staircase_person_occupancy` and a Protect garage-hallway leg); exterior chain camera names are inferred from the fixture |
| Falsifier for the headline | would be t0-anchored blank near 0 % or `t0 - E` near 0; measured sensor-blank at E-1 is 84 % and at E+0 is 0 %, and code shows the 45 s delay. Both point the same way |
