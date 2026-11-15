# AUDIT: crossing vision Phase 3 P3-D0b / P3-D0c / P3-D0d (2026-11-15)

Run Sun 2026-11-15 16:35-17:5x CST by the read-only prober. Spec: `PLANNING_crossing_vision.md` at b5bdb13a (P3-D0b, P3-D0c, P3-D0d, the Phase 3 decisions block, section 6 knobs), `AUDIT_crossing_vision_p3_d0_2026_11_15.md` (runs 1 and 2) and fixture `crossing_vision_door_eval_2026_11_14.json` read first. Presence / HVAC state-of-play docs not needed (no presence or HVAC logic touched). State changes: only the 14 llmvision `video_analyzer` calls of P3-D0c. No Bermuda diagnostics, no config-entry data printed (door-group map and interior-neighbour map read from the config entry on the HA host, nothing else), Frigate data only through the HA Frigate proxy and the HA websocket `frigate/events/get`.

Files: reference fixture `quality/tests/fixtures/crossing_door_reference_frigate.json` (commit 20af7227, made before any scoring); pair labels `quality/tests/fixtures/crossing_pass_key_pairs_2026_11_15.json`. Scripts `.claude/tmp/p3d0b_*.py`, `p3d0c_run.py`, `p3d0d_*.py` (not committed). Call log `.claude/tmp/p3d0c_calls.jsonl`.

## Verdicts

| Deliverable | Verdict | Headline | Model calls |
|---|---|---|---|
| P3-D0b second direction source | **NO-GO** (no instrument passes; I2 not scorable) | best instrument right 13/17 and 4/6 (gate 15 and 5); I1 10/17 and 3/6 with coverage 0.47 on 11-14 (gate 0.50); I3 scorable on one door group only | 0 |
| P3-D0c group counts on the recording window | **GO** (`recording_window` becomes the default route) | gate numbers met exactly: pinned undercount 6 (run 2: 6), worst clip 1 worse, 0 new over-count on the 7 small clips; two caveats below | **14 of 14** |
| P3-D0d pass key | **HOLD** (no candidate passes; collapse stays off) | K1 0.70 on the 10 scorable one-pass pairs, K2 fails on both shares, K3 0.76 and merges 3 of 4 round trips; 4 labelled round trips (< 20) | 0 |

## P3-D0b direction instrument (0 model calls)

### Step 0: freeze (and a disclosure)

Door polygons (normalised, one per Frigate door camera) and the contact mapping were committed in `crossing_door_reference_frigate.json` (20af7227) BEFORE any instrument was scored. Mapping rule used: the contact or cover whose registry area (entity `area_id`, else device `area_id`) equals the door group's cameras' area and whose device class is door / garage:

| Door group | Cameras (registry area) | Contact / cover | Recorder history | Scorable |
|---|---|---|---|---|
| front | madrone_g6_entry, front_door_aerial (Front Porch) | `binary_sensor.door_1467` (unifi_access, Front Porch) | rows since 2026-11-08, states `off`, `unavailable` only: never `on` | **no** (never opened) |
| garage_a | garage_a, doorbell_lite (Garage A) | `cover.konnected_f0f5bd523b00_garage_door` (esphome, class garage, Garage A) | since 2026-11-08, `opening/open/closing/closed/unavailable`, 8 opens on 11-14 | yes |

Not mapped by registry and therefore not part of any gate: `binary_sensor.elkm1_front_door` (elkm1, 128 on/off rows since 11-08, but its registry area is AV Closet; a name guess to call it the front door), the Kwikset front-entry status (area Entry Way, only `on`).

**Two disclosures on bias controls.** (1) The polygons were drawn from one live snapshot per camera, but the image reads of those snapshots were dropped by a tool request limit, so I drew them without a reliable view and wrote the notes from layout reasoning. Contact sheets viewed later in the run (G6 Entry: glass door along the right edge, mat bottom right; Front Door Aerial: overhead, mat bottom centre; Garage A interior: garage door across the top; doorbell_lite: garage face down the right side) are consistent with the polygons, and I did not redraw them (that would break the freeze), but polygon quality is an unverified input to every I1 number below. A pad sweep (0.05 / 0.10 / 0.15 / 0.20, and no E+45 cut) gave 10 / 10 / 9 / 9 of 17 right, so the result is not sensitive to pad. (2) I had read the fixture's human labels in my context before drawing; the polygons were drawn from geometry only, and the instruments never read labels.

### Step 1 data availability

All 46 fixture events have a stored `path_data` (`data.path_data`, list of [[x,y], t]) via `frigate/events/get` instance `frigate-f2`, plus `zones` (one `<cam>_property` zone per camera, so I2 has no order to read). All 834 stored person events on the 4 door cameras (earliest 2026-11-02) carry `path_data` (key counts: `path_data` 834 of 834). The step 1b MQTT capture is therefore NOT needed. I1 was scored on the path truncated to points with timestamp <= E + 45 s.

### Step 2: instruments on the 17 readable clips and the 6 tracker-wrong clips

Replay check first: I4 v0 reproduces the fixture's tracker direction on 46 of 46 events and 11/17 right, 0/6 on the tracker-wrong clips, so the replay is valid (the plan's discriminator).

| Instrument | Right of 17 (gate 15) | Tracker-wrong right of 6 (gate 5) | Decided of 17 | Wrong directions | Verdict |
|---|---|---|---|---|---|
| I1 track vs door (pad 0.05, cut E+45) | 10 | 3 | 11 | 1 | fail |
| I2 zone order | not scorable | not scorable | | | needs a homelab `<cam>_threshold` zone per door camera (Frigate config, not URA code); today one `<cam>_property` zone per camera; no events exist to score |
| I3 contact order (garage_a only) | 1 | 0 | 2 | 1 | fail; front has no usable contact |
| I4 v0 (today's rule) | 11 | 0 | 17 | 6 | the tracker, as required |
| I4 v1 (prefer entry when both windows hold an event) | **13** | **4** | 17 | 4 | fail (best) |
| I4 v2 (interior track start for entry / end for exit) | 12 | 2 | 17 | 5 | fail |
| I5 I1, else I3, else tracker | 13 | 3 | 17 (fallback included) | 4 | fail |
| tracker alone | 11 | 0 | 17 | 6 | baseline |

Per clip, I1 decided `in` on 16:14:56, `out` on 17:59:51 and `in` on 18:59:36 (three tracker-wrong clips fixed) and was `unclear` on 15:12:14, 18:43:18, 19:42:11, 19:45:29, 21:42:22 (it never decides when the track starts and ends away from the door, which is the case for the tracker-wrong clips on the G6 Entry camera). It was wrong on 14:17:23 (garage). I3 decided only 18:27:00 (right) and 14:17:23 (wrong; the open and the event start are within a few seconds of each other).

Sensitivity, not gate input (name-based mapping, labelled as such): scoring `binary_sensor.elkm1_front_door` as the front contact gives I3 12 right of the 15 front readable clips it decides on, and an I5 with it 13/17 and 4/6, still below the gate. If the operator confirms that zone is the front door, then wiring it into the registry area is the single change that makes I3 scorable for the front group.

### Step 3 determinism

I1, I3 and I4 v0 / v1 / v2 each run twice on the same inputs and gave identical output on all 101 crossings (the property the LLM failed). Pure functions of stored path points and recorder rows.

### Step 4 coverage on the 101 crossings of 11-14 (20 ambiguous included)

| Instrument | Decides in / out | Share | Notes |
|---|---|---|---|
| I1 | 47 (28 in, 19 out) | **0.47** (gate 0.50; fails) | 2 crossings had no matched event; of matched events 16 of 99 (16 %) still open at E + 45; on the 17 + 29 fixture events: 7 of 46 (15 %) open |
| I3 (cover) | 13 | 0.13 | 51 crossings are in the front group (no contact), 35 garage crossings had no open within 45 s |
| I4 v0 / v1 / v2 | 81 / 81 / 79 | 0.80 / 0.80 / 0.78 | v0 decides 0 of the 20 ambiguous; v1 gives 62 `in` and 19 `out` (a skew toward `in`) |
| I5 own decisions (I1 or I3) | 52 | **0.51** (passes) | fallback to the tracker on 49 (0.49), reported not gated |
| I1 agrees with tracker | 21 of the 37 crossings both decide | | the tracker is no oracle (35 % wrong on readable clips) |

The 10 of 20 ambiguous crossings I1 decides would add a direction where the tracker has none; that is unscored (no labels on ambiguous crossings).

### Verdict and what each outcome changes

**NO-GO.** No instrument or combination reaches 15/17 and 5/6; the best (I4 v1, 13 and 4) is an interior-timing variant that moves the tracker's ambiguity toward `in` (62 `in` vs 19 `out` on 11-14), not an independent signal, and it was picked as the best of about six variants on n = 17, so its 13 is inflated (selection-inflation caveat, plan bar bias control). I1, the only independent deterministic signal, is right where it decides but decides on 11 of 17 and fails the coverage gate (0.47). Direction stays the tracker's; P3-D9c is not planned on any of these. Operator questions this raises: (a) add a `<cam>_threshold` zone per door camera in Frigate (I2) and re-run; (b) confirm what `binary_sensor.door_1467` (Front Porch, never `on`) is, or give the front group a contact whose registry area is the Front Porch (the ELK zone is in AV Closet).

## P3-D0c recording-window group counts (14 of 14 Luna calls)

Call shape as P3-D0 run 2 (provider `01M7B731T26P2HXVW77AQR62PP`, model `gpt-6-luna`, 768 px, `max_tokens` 4000, same prompt and schema), 8 frames requested, `video_file = /api/frigate/frigate-f2/recording/<camera>/start/<E-5>/end/<E+15>` (camera from the stored event payload; instance `frigate-f2`; E = the crossing time; the window is complete because all clips are from 11-14, long past the 10 s lag), semaphore 2. 14 of 14 HTTP 200, 0 empty replies.

| Clip (11-14) | Human | Production | Run 2 (event clip) | **Recording window** | Event length |
|---|---|---|---|---|---|
| 18:43:18 (pinned) | 7 | 6 | 5 (under 2) | **8 (over 1)** | 16.2 s |
| 21:24:08 (pinned) | 4 | 2 | 2 (under 2) | 2 (under 2) | 25.2 s |
| 21:28:01 (pinned) | 3 | 2 | 2 (under 1) | 2 (under 1) | 5.5 s |
| 16:19:36 (pinned, false blank) | 4 | blank | 4 | 4 | 21.6 s |
| 16:16:11 (pinned) | 3 | error | 2 (under 1) | 2 (under 1) | 28.3 s |
| 16:23:52 (pinned) | 3 | error | 4 (over 1) | **1 (under 2)** | 48.7 s |
| 18:59:36 (reported, excluded) | 8-10 unpinned | 4 | 8 | 12 | 18.1 s |
| 16:30:44 | 2 | 2 | 2 | 2 | 40.2 s |
| 13:40:36 (289 MB event clip) | 1 | 1 | 1 | 1 | 469.8 s |
| 15:24:28 | 2 | 1 | 2 | 2 | 38.2 s |
| 21:54:39 | 2 | 2 | 2 | 2 | 18.5 s |
| 20:44:20 | 1 | 1 | 1 | 1 | 12.3 s |
| 21:03:34 | 2 | 2 | 2 | 2 | 10.2 s |
| 14:27:51 | 1 | 1 | 1 | 1 | 15.1 s |

Gate (plan): total undercount on the 6 pinned <= run 2's (6): undercount sums are 0 + 2 + 1 + 0 + 1 + 2 = **6** vs run 2's 2 + 2 + 1 + 0 + 1 + 0 = **6** (equal: pass). No pinned clip worse than run 2 by more than 1: worst is 16:23:52 at absolute error 2 vs 1 (worse by 1: pass). No new over-count on the 7 small clips (16:30:44, 13:40:36, 15:24:28, 21:54:39, 20:44:20, 21:03:34, 14:27:51: all equal the human count): pass. 18:59:36 is reported and excluded.

Latency (call wall time, run 2 event-clip time beside): median 11.4 s, max 30.9 s (18:43:18, 8 frames of a large party). Clips whose event is longer than 40 s: 16:23:52 16.8 s, 16:30:44 11.0 s (40.2 s event), 13:40:36 11.8 s against **86.6 s on the event-clip route** (the 289 MB clip that sat at the 90 s timeout). The recording-window route bounds clip size, which is the point.

Reading for the owner of P3-D2: the gate passes but only just, and the shape differs from run 2: the window is better on the biggest party (18:43 over by 1 instead of under 2) and worse on 16:23:52 (a 48.7 s event; the [E-5, E+15] window saw one person at a time, frame counts `[0,0,1,1,1,1,1]`, because a group arriving over a long event is not all inside 20 s). 18:59:36 reads 12 against 8-10 (the party keeps arriving through the window). The group bias is therefore a window-length effect on slow-forming groups, not a route flaw. **Verdict GO: `CROSSING_VISION_FRAME_ROUTE = recording_window` for every call**, with the named residual that a group trickling in over more than the 20 s window is undercounted, to be handled by the P3-D2 known-bias rule rather than a wider default window.

## P3-D0d pass key candidates (0 model calls)

### Labelled sets (fixture `crossing_pass_key_pairs_2026_11_15.json`)

Mined every opposite-direction pair within 60 s on one door group from `egress_identity_outcome` (3 days, exact E) plus `person_entry_exit_events` (E approximate = resolution - 20 s, 10-29 to 11-12): 326 crossings, **99 pairs** (43 already in the P3-D0 fixture, 56 new). Frigate events and recordings exist only from 2026-11-02, so pairs before 11-02 could not be viewed; the retention horizon is 13 days, not the plan's 30. This session's image reads were partly dropped by a tool request limit: I labelled the 7 old `not_viewed` pairs 8, 9, 10, 23, 24, 26, 29 and 22 new pairs from contact sheets I could actually see; the other 42 are `not_viewed` placeholders (the 8 old ones 6, 30, 31, 32, 33, 34, 36, 41 and 34 new), none counted below.

| Label | Count | By group |
|---|---|---|
| one_pass | **25** (14 old + 11 new) | garage_a 13, front 12; 6 with approximate E |
| round_trip | **4** (unchanged: pairs 11, 19, 20, 40) | front 2, garage_a 2 |
| unknown viewed (no traversal visible or several people) | 28 | |
| not viewed | 42 | |

Round-trip gate: **4 labelled, bar 20 -> HOLD by arithmetic.** Of the 57 labelled-viewed pairs 4 are round trips (7 %); even labelling every one of the 42 unviewed pairs at that rate gives about 3 more. Mining cannot reach 20; staging (about 10 step-out-and-back walks per door group) or accepting the residual by name is the remaining route (operator question already in decision 8).

### K1 door-contact cycle (pad 5 s)

Only the garage_a group has a mapped contact (the cover); front has none that opened, so every front pair has key None. Pairs before 2026-11-08 have no recorder rows and are excluded.

| Set | Scorable | Share the key | Wilson 95 % |
|---|---|---|---|
| one_pass | 10 of 25 (garage, since 11-08) | 7 of 10 = **0.70** (gate 0.80) | [0.40, 0.89] |
| round_trip | 2 of 4 | 0 merged (UB 0.66; gate <= 0.15, unreachable below n = 20) | [0.00, 0.66] |

K1 covers 40 % of the labelled one-pass set at all. **Fails** the share gate on what it can score and cannot score the front group.

### K2 right direction instead of collapse (two shares, finding 9)

Directions per member from the instrument; both members' directions compared. Caveat that applies to every K2 number: the pairs were selected because the tracker called them OPPOSITE, so K2 asks whether an instrument fixes those, which biases against a candidate that agrees with the tracker.

| Instrument | one_pass same direction, gap <= 30 s (source dedup, every reader) | one_pass same direction, gap <= 60 s (ledger only) | round_trip kept opposite (30 s / 60 s) |
|---|---|---|---|
| I1 only (both decided) | 3 of 3 (decided on 3 of 16 pairs) | 4 of 5 (decided on 5 of 25) | no round trip decided by I1 |
| I5 (I1 / I3 / tracker fallback) | 3 of 16 = 0.19 | 5 of 25 = 0.20 | 3 of 3 / 4 of 4 kept opposite |
| I4 v1 (from 11-08; the best-scoring instrument) | 10 of 13 = 0.77 (13 pairs decidable) | 14 of 20 = 0.70 (20 pairs decidable) | **0 of 3 / 0 of 4 kept opposite: all 4 round trips get the same direction** |
| I5 with v1 in the chain | 9 of 16 = 0.56 | 12 of 25 = 0.48 | 0 of 3 / 0 of 4 kept opposite |

Gate (>= 0.80 same-pass; round trips given one direction Wilson UB <= 0.15): **fails everywhere.** I1, the only independent signal, decides too few pairs to score (3 and 5), and the 1.00 / 0.80 on those is n = 3 / 5. The deployable I5 shares a direction on 0.19-0.20. I4 v1 reaches 0.77 / 0.70 only by pushing everything toward `in`, which also gives every round trip a single direction (4 of 4 merged), the exact harm the gate is there to catch. K2 does not make collapse unnecessary.

### K3 chained door-group events (gap 5 s; key = chain's first event id; crossing inside the chain, pad 0 or 2 s, same result)

| Set | Share the key | Wilson 95 % |
|---|---|---|
| one_pass | 19 of 25 = **0.76** (gate 0.80) | [0.57, 0.89] |
| round_trip | 3 of 4 merged = 0.75 | [0.30, 0.95]; gate <= 0.15 |

Beside it, the failed rule (ii) on the same set: 5 of 25 = 0.20 on one-pass pairs (P3-D0 measured 4 of 14 = 0.29), 0 of 4 on round trips. K3 is by far the best event-based key (0.20 to 0.76) because chaining across the door group's cameras absorbs the "two front cameras, two events" mechanism the P3-D0 audit named, but it sits just under the bar on one-pass pairs and merges 3 of 4 round trips (an event chain cannot tell two walks from one when the door is busy).

### Verdict and what changes

**HOLD for P3-D0d.** No candidate passes the share gate (K1 0.70 on a 40 % subset, K2 0.19-0.77 with all round trips merged for the best, K3 0.76), and the round-trip gate cannot be evaluated (4 of 20). Collapse stays off: `CROSSING_VISION_LEDGER_PASS_COLLAPSE` False, P3-D4, P3-D9a and P3-D9b stay parked. K3 is the candidate to carry forward if the operator stages round trips (it needs both the 0.80 share and a round-trip bound, and today it fails the second on 3 of 4); K1 needs a front contact that reports `on`.

## What is not done / caveats

* P3-D0b step 1b MQTT capture: not needed (stored events carry the path). I2 not scorable until homelab zones exist.
* I3 for the front group and K1 for the front group: no registry-mapped contact ever opened; the operator question is in the P3-D0b verdict.
* The recorder holds rows from 2026-11-08 only, so I4, I3, K1 and the contact leg of K2 are limited to 11-08 onward; K2 rows for earlier pairs use the tracker fallback, and I4 v1 was decidable on 13 / 20 one-pass pairs.
* Labelled one-pass pairs: 6 of 25 have approximate E (resolution time minus 20 s); K1 and K3 are sensitive to that by up to a few seconds.
* 42 pairs unviewed (tool request limit, not a choice); they are `not_viewed` in the fixture and not counted.
* I did not run an independent pass over the polygons; see the disclosure under step 0.
* Luna calls: 14 of the 14 P3-D0c budget. The 120-call P3-D0 budget was not touched.

## I1 v2 (polygons drawn from viewed snapshots)

Run Sun 2026-11-15 16:51-17:1x CST by the read-only prober. Redo of P3-D0b I1 because run 1 drew its polygons without seeing the snapshots (disclosure 1 above). Freeze rule kept: new polygons committed (6d683d62, `quality/tests/fixtures/crossing_door_reference_frigate_v2.json`) BEFORE any v2 scoring; scoring code is the run-1 script with only the fixture path swapped (`.claude/tmp/p3d0b2_score.py`, `p3d0b2_cov.py`, `p3d0b2_sweep.py`, `p3d0b2_elk.py`, not committed). Zero model calls, no HA state change.

**Snapshots.** Fetched 2026-11-15 16:51:18 (camera overlay clock 04:51:18 PM, overcast daylight, nobody in frame) via HA `camera_proxy`, entity from the registry (platform frigate, client `frigate-f2`, unique_id suffix = the Frigate camera in the fixture events): `camera.madrone_g6_entry`, `camera.front_door_aerial` (both Front Porch), `camera.garage_a_2`, `camera.doorbell_lite` (both Garage A). Each viewed one image per Read call. What was seen is recorded per camera in the fixture (door position, inside side, occlusion). Summary: G6 Entry has the glass door down the whole right edge with the mat abutting it; Front Door Aerial is overhead with the threshold along the bottom edge below the mat; Garage A is an interior overhead with the glass garage door across the top; doorbell_lite is the garage door face down the right side. The v2 polygons are close to v1's (v1's notes had been consistent with later contact sheets), with the G6 Entry polygon extended up the glass door and slightly wider.

### Result against the gates (E+45 truncation, pad 0.05, plan coverage rule: share of the 101 crossings of 11-14 decided in/out by I1 itself)

| | Right of 17 (gate 15) | Tracker-wrong right of 6 (gate 5) | Decided of 17 | Wrong direction | Coverage on 101 (gate 0.50) |
|---|---|---|---|---|---|
| I1 run 1 (blind polygons) | 10 | 3 | 11 | 1 | 0.47 |
| **I1 v2 (viewed polygons)** | **10** | **3** | 11 | 1 | **0.47** (47: 28 in, 19 out; front 26 of 52, garage_a 21 of 49; 48 unclear, 4 short, 2 no matched event) |

**Verdict: I1 FAILS all three gates again (10/17, 3/6, 0.47), same numbers as run 1.** The unverified-input worry did not change the outcome; run 1's number was not an artifact of the polygons. Per-clip decisions are identical to run 1 (right on 15:31:04, 16:14:56, 17:59:51, 18:59:36, 20:44:20, 20:57:38, 21:03:34, 21:12:33, 21:20:42, 21:28:01; wrong on 14:17:23; `unclear` on 15:12:14, 18:27:00, 18:43:18, 19:42:11, 19:45:29, 21:42:22). Determinism: I1 identical on two runs over all 101 crossings.

Why it stays at 11 decided (read from the path points, v2 polygons): on G6 Entry the tracks start and end entirely inside or entirely outside the door polygon. 15:12:14 (human in): first (0.63, 0.99), last (0.89, 0.98) both in the polygon; 19:45:29 (in): (0.67, 0.88) to (0.91, 0.96) both in; 18:43:18 (out): two points near (0.05, 0.81), both outside; 19:42:11 (out): two points (0.12, 0.78) to (0.02, 0.71), outside. So G6 Entry sees people on the mat only, or only at the far left, so start-vs-end against the door cannot separate in from out; this is a camera-geometry limit, not a polygon-drawing one. Open at E+45: 16 of 99 matched events (16 %), unchanged.

### Pad sweep (v2 polygons; right of 17 / tracker-wrong right of 6 / decided of 17)

| Pad | E+45 cut | No cut |
|---|---|---|
| 0.05 (plan value) | 10 / 3 / 11 | 10 / 3 / 11 |
| 0.10 | 9 / 2 / 10 | 9 / 2 / 10 |
| 0.15 | 9 / 2 / 10 | 9 / 2 / 10 |
| 0.20 | 8 / 2 / 9 | 8 / 2 / 9 |

(Run 1 sweep: 10 / 10 / 9 / 9 of 17.) Larger pads only lose decisions; no pad reaches 15 or 5. Truncation at E+45 changes nothing on these 17 (no cut gives the same numbers).

Other instruments are unchanged by the polygon redraw (they do not use polygons): I4 v1 13 / 4 (best), I5 (I1, else I3, else tracker) 13 / 3 with own-decision coverage 0.51 (52 of 101; fallback 0.49).

## Front-door contact facts (read-only, registry and integration data; the I3 front sensitivity)

Sources: entity and device registry and area registry (`config/entity_registry/list`, `device_registry/list`, `area_registry/list`) and current state attributes, 2026-11-15; recorder row counts by `ssh ha sqlite3 -readonly`. No config-entry data read, no name inference: identity below comes from `platform`, `unique_id`, device `identifiers`/`manufacturer`/`model` and state attributes.

| | `binary_sensor.elkm1_front_door` | `binary_sensor.door_1467` |
|---|---|---|
| Integration (entity platform) | `elkm1` | `unifi_access` |
| unique_id | `elkm1_zone_017` | `a2476bae-2905-4ee2-8989-e718f755aa92-access_door_dps` (door position sensor) |
| Device | "ElkM1", Elk Products M1, identifiers `(elkm1, _system)`, one hub device carrying 45 entities (8 alarm areas, zone sensors); device area AV Closet; entity `area_id` None | "Door 1467", manufacturer Ubiquiti, identifiers `(unifi_access, <same uuid>)`; device area **Front Porch**; entity `area_id` None; siblings: unlock button, doorbell event, access event, thumbnail, lock-rule select and sensors |
| Attributes | `index` 17 (zone 17 of the panel), Elk `area` 0, `device_class` door, `definition` 1, `logical_status` 0, `physical_status` 2, `triggered_alarm` false, no HA location | `device_class` door |
| Position | none in registry: the AV Closet area belongs to the hub (the Elk panel is in the closet), not to the zone. The label "Front Door" is the panel's zone name, a human label, not registry geometry | Front Porch by device area |
| Recorder 11-08 to 11-15 | 128 rows (78 off, 50 on) | 31 rows: 29 off, 2 unavailable, **never on** (device class door, so never open) |
| Same device | These are two different devices on different integrations | |

Findings: (1) `door_1467` is the UniFi Access hub's door position sensor on the Front Porch device. Never reporting open for 7 days means either the door never opened as seen by that DPS, or the sensor is not wired or paired (the registry cannot tell which; the same device's access event entity has 31 rows and the doorbell event 41 rows over the same window, so the device is alive). Unknown which; checking the Access app for the DPS wiring is an operator question. (2) `elkm1_front_door` is Elk panel zone 17 with `device_class: door`; nothing in the registry ties it to the Front Porch (the hub's area is AV Closet). Whether zone 17 is the front door contact is a name-level claim and stays unconfirmed by registry data; only the operator or the panel's zone programming can confirm it. (3) Neither is in the door-group mapping by registry area except `door_1467`, which is mapped and never opens.

### I3 for the front group under each candidate (sensitivity check, NOT a gate input; the Elk mapping is by name)

Front group readable clips: 15 (2 garage clips excluded). Scoring on the 17 readable and 6 tracker-wrong:

| Candidate contact | Right of 17 | Tracker-wrong right of 6 | Decided of 17 | Wrong direction |
|---|---|---|---|---|
| `binary_sensor.door_1467` (registry-mapped, Front Porch) | not scorable: never on, I3 decides 0 front clips | | 0 front | |
| `binary_sensor.elkm1_front_door` (sensitivity only) | 12 | 4 | 15 (all 15 front clips) | 3 (decided `out` on 15:12:14, 19:45:29, 21:42:22, human `in`) |
| garage cover only, for reference (garage group) | 1 | 0 | 2 | 1 |
| Elk plus cover as the I3 | 13 | 4 | 17 | 4 |
| I5 chain I1, else I3 (cover), else I3 (Elk), else tracker | 13 | 4 | 17 | 4 |

Verdict for the sensitivity: even granting the Elk zone as the front contact, the best combination is 13/17 and 4/6, still below 15 and 5 (the three Elk-wrong clips, 15:12:14, 19:45:29 and 21:42:22, are all clips I1 also left `unclear`; the cause of the Elk `out` reading on those three `in` clips was not investigated). Elk coverage on 11-14: 39 of 101 crossings decided (name-based, sensitivity). Run 1's statement (12 right of 15 front clips decided) is consistent: here 12 of 17 right with 15 decided.

## I1 v2 verdict

NO-GO unchanged for I1: 10/17 (gate 15), 3/6 (gate 5), coverage 0.47 (gate 0.50), with polygons now drawn from viewed snapshots. P3-D0b stays NO-GO; the front-contact route does not rescue it on the sensitivity numbers. The remaining levers are unchanged: an I2 Frigate threshold zone, or a front camera that sees the approach (G6 Entry sees only the mat).

## Ensemble check

Run Sun 2026-11-15 by the read-only prober, zero model calls, zero HA calls. Question: do the instruments' errors fall on different clips, so that a vote or disagreement rule could clear 15/17 and 5/6?

### Pre-registration (written before any combination was scored)

Voters per clip (all read from stored per-clip outputs, not re-run): **V** = vision run 2 (`max_tokens` 4000; `unclear` = abstain; source `.claude/tmp/p3d0_calls.jsonl` via `p3d0_score2.py`); **K** = I4 v1 (`p3d0b2_rows.json` field `I4v1`, always decides); **C** = contact: Elk zone 17 for the front group, garage cover for garage_a (`p3d0b2_elk.py` "I3 elk+cover"; None = abstain; the Elk mapping is by name, sensitivity only, as disclosed above); **I1** = Frigate path v2 (None = abstain); **T** = tracker. Truth = fixture human labels. Rules, fixed now:

* **R1** majority of {V, K, C}: a direction with at least 2 of the 3 votes; otherwise no decision (counts as not right).
* **R2** majority of {V, K, C, I1}: direction with strictly more votes than the other; tie or all abstain = no decision.
* **R3** contact decides, else vision, else tracker: C if decided; else V if decided; else T.
* **R4** vision-override: V if V decided, V differs from T, and C agrees with V; otherwise T.

Scored on the 17 readable clips and the 6 tracker-wrong clips; coverage = clips with a decision of 17 (R3 and R4 always decide via the tracker fallback).

Selection-inflation risk, stated plainly: n = 17 with 6 tracker-wrong clips; 4 rules, chosen after the per-clip errors of all four instruments were already known from the sections above, so any rule that "works" here has been picked with knowledge of the answer; a single clip is 6 points of accuracy; the single-instrument 13/17 numbers are themselves best-of-several (I4 best of about six variants). A pass on 17 clips is a hypothesis, not a measurement; a fail is informative.

### Per-clip matrix (17 readable clips; W = one of the 6 tracker-wrong clips; `.` = abstain)

Sources: V `p3d0_calls.jsonl` label `b:mt4000:8:<event_id>` (reproduces 13/17, 3/6 via `p3d0_score2.py`); K and I1 `p3d0b2_rows.json`; C `p3d0b2_elk.py`; T = fixture tracker. Combination script `.claude/scratchpad` (not committed).

| Clip 11-14 | Grp | Human | T | V (run 2) | I1 v2 | K (I4 v1) | C (Elk / cover) | W |
|---|---|---|---|---|---|---|---|---|
| 14:17:23 | garage | out | out | out | in X | out | in X (cover) | |
| 15:12:14 | front | in | in | out X | . | in | out X | |
| 15:31:04 | front | in | in | in | in | in | in | |
| 16:14:56 | front | in | out X | . X | in | in | in | W |
| 17:59:51 | front | out | in X | out | out | in X | out | W |
| 18:27:00 | garage | out | out | out | . | out | out | |
| 18:43:18 | front | out | out | out | . | in X | out | |
| 18:59:36 | front | in | out X | in | in | in | in | W |
| 19:42:11 | front | out | in X | out | . | in X | out | W |
| 19:45:29 | front | in | out X | out X | . | in | out X | W |
| 20:44:20 | front | out | out | out | out | out | out | |
| 20:57:38 | front | out | out | out | out | out | out | |
| 21:03:34 | front | out | out | out | out | in X | out | |
| 21:12:33 | front | out | out | out | out | out | out | |
| 21:20:42 | front | in | in | in | in | in | in | |
| 21:28:01 | front | out | out | out | out | out | out | |
| 21:42:22 | front | in | out X | out X | . | in | out X | W |
| right of 17 | | | 11 | 13 | 10 | 13 | 13 | |
| right of the 6 W | | | 0 | 3 | 3 | 4 | 4 | |

(I1's cell on 14:17:23 is `in` against human `out`; the other I1 blanks are `unclear`.)

### Scores (pre-registered rules, unchanged)

| Rule | Right of 17 (gate 15) | Decided of 17 (coverage) | Wrong directions | Right of the 6 W (gate 5) |
|---|---|---|---|---|
| R1 majority {V, K, C} | **14** | 17 | 3 | **4** |
| R2 majority {V, K, C, I1} | 13 | 16 (14:17:23 ties 2-2) | 3 | 4 |
| R3 contact, else vision, else tracker | 13 | 17 | 4 | 4 |
| R4 vision override (V and C agree against T) | 13 | 17 | 4 | 3 |
| best single (K or C or V) | 13 | 17 | 4 | 4 (V 3) |

Best pre-registered rule: **R1, 14/17 and 4/6, below both gates (15, 5)**. One clip better than any single instrument. Coverage on the 101 crossings of 11-14 is not computable: V ran on 31 clips only, so no ensemble coverage number is claimed.

Selection inflation, applied: R1 was the best of four rules chosen after the errors were known; its +1 over the singles is one clip on n = 17 and does not survive the plan's bias control. The honest reading is "13-14 of 17 whichever way it is combined".

### Are the errors on different clips? Mostly not

Per-clip misses by instrument (V, K, C, I1):

* **Shared by V, C and I1: 15:12:14, 19:45:29, 21:42:22**, all human `in`, all three instruments say `out` (I1 is `unclear` on all three, so V and C are the shared pair). These three are exactly R1's 3 misses. K gets them right only because K is the `in`-skewed variant: K is `in` on 11 of 17 clips and right on all 7 human-`in` clips and wrong on 4 of the 10 human-`out` clips (17:59:51, 18:43:18, 19:42:11, 21:03:34), so K's votes on these three are not independent evidence, they are its prior. No clip is missed by V, K and C all together (any of V, K, C is right on all 17), but the ensemble only gains where K's prior happens to be right.
* The errors that are NOT shared: K misses 4 `out` clips that V and C get right; V misses 16:14:56 (`unclear`); C misses 14:17:23 (garage cover, open within seconds of the event start). V and C complement K, not each other.
* So the diversity is K (a tracker-timing variant, skewed `in`) versus {V, C, I1} (correlated: all three read "person at the door at the end, or near the door" and call it `out` on these front clips). Majority over three votes where two are correlated cannot fix the clips where the correlated pair is wrong.

### Shared-miss clips: is the human label in question? (viewed one sheet per Read call, `.claude/tmp/vision_eval_media_<event_id>.sheet.jpg`)

* **21:42:22 (front_door_aerial, event 1794714143.73626-99jqst): the label is probably wrong.** Eight frames 21:42:23-21:42:31, overhead view with the mat at the bottom and the path across the top. Frame 1: a person leaning at the mat on the left (bottom-left); frames 2-4: they walk up the stepping stones toward the top of the frame, away from the door; frames 5-8 empty. That reads as a departure (`out`), the direction V and C both give. The earlier audit's description was "person walks from the path to the door" and is not what this sheet shows in time order. If the label is `out`, the tracker was right on this clip (not a tracker-wrong clip), and V, C and R1 are right on it.
* **15:12:14 (madrone_g6_entry, event 1794690734.705725-axkjnv): ambiguous, label in question.** Frames 15:12:14-15:12:29: a woman stands at the glass door on the mat (frame 1), walks left away from it and back, on her phone (frames 2-3), returns to the door (frame 5), and the door opens with her at its threshold at 15:12:27 (frame 7). One person with both a departure-looking start and an entry-looking end; "first and last position against the door" does not discriminate, which is why V flipped between its two runs (in, then out) and I1 and C are not informative. `in` is a defensible end-state reading; I would not treat it as a solid truth label.
* **19:45:29 (madrone_g6_entry, event 1794707129.471712-xc8gg6): the label `in` is solid.** A man walks from the path to the mat, the door opens as he reaches it (frames 15:45:30-15:45:36), the mat is empty afterwards. V, C and I1-adjacent logic all say `out`; this one is a true instrument failure (V described it as leaving, and the Elk zone reported `out`, cause not investigated, as noted in the I3 section).

Sensitivity (post-hoc relabelling after seeing the results, NOT a gate): if 21:42:22 were `out`, R1 is 15 of 17 (the gate number) with the 6 tracker-wrong clips becoming 5 and R1 right on 4 of them; with 15:12:14 also dropped, 15 of 16. A gate cleared only by relabelling the clips the rule missed is exactly the selection inflation named above; it says the label set needs a second review pass, not that the rule works.

### Verdict

Combining the current instruments is **not worth building**. Pre-registered best (R1) is 14/17 and 4/6: under the gate on both counts; the gain over a single instrument is one clip; the errors are correlated across the instruments that are genuinely independent of the tracker (V, C, I1 all fail on the same front `in` clips), and the one instrument that gets those clips right does so through an `in` bias that fails on 4 of 10 `out` clips and moves every round trip to one direction (P3-D0d K2 table). Two cheaper levers move the number more than an ensemble: (1) a second label pass on 21:42:22 and 15:12:14 (a mislabel changes the gates by up to 2 clips of 17); (2) the unchanged operator questions: a threshold zone per door camera (I2) and a front contact that is registry-mapped. Direction stays the tracker's; P3-D9c is not planned on an ensemble. Revival trigger: a new independent signal (I2 zone order or a registry-mapped front contact) whose errors do not overlap V's and C's on the front group, re-scored on a larger labelled set than 17.

## I6 adjacent outside cameras

Run Sun 2026-11-15 (started 17:2x CST) by the read-only prober. Zero model calls, no HA state change, no Bermuda diagnostics. Scripts `.claude/tmp/i6probe_*.py` (not committed). Frigate data only through the HA websocket `frigate/events/get` (instance `frigate-f2`, person label, 2026-11-13 22:00 to 2026-11-15 02:00 CST, 280 events; per-camera counts: madrone_g6_entry 64, garage_a 48, front_door_aerial 47, doorbell_lite 30, g5_bullet 26, SonoffWindow 24, front_side_ptz 21, rear_ptz 11, utilities_ptz 7, back_yard 1, garage_b 1; ArmCrest, hot_tub, pool_equipment, MadronePTUltra, ReolinkStudyBPorchPTZ none).

### Pre-registration (frozen in this commit, written before any I6 number was computed)

**Mapping used (no name guessing).**
* Door group per egress camera: integration config `door_groups` = madrone_g6_entry -> front, front_door_aerial -> front, doorbell_lite -> garage_a, garage_a -> garage_a (read from the config entry on the HA host; `egress_cameras` = the same four).
* Adjacent perimeter cameras: the operator-ratified `EXTERIOR_ADJACENCY_GRAPH` and its derived `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` (`const.py` 3026-3079): adjacent to madrone_g6_entry and front_door_aerial = front_side_ptz, utilities_ptz; adjacent to doorbell_lite = armcrest, g5_bullet, rear_ptz. garage_a has no edge in the graph (it is not a ring camera). Camera identity (Frigate camera name) from the entity registry: unique_id suffix; front_side_ptz, g5_bullet, rear_ptz, utilities_ptz all have Frigate events in the window (rear_ptz and utilities_ptz also exist as unifiprotect cameras; here the Frigate legs are used).
* Door-group sibling egress cameras (registry device area): Front Porch = madrone_g6_entry + front_door_aerial (both outward-facing, viewed 2026-11-15 snapshots); Garage A = garage_a (interior overhead, seen in the I1 v2 snapshots) + doorbell_lite (garage door face, outward).

**Outside set O per crossing (own camera always excluded):**
* front crossing: front_side_ptz, utilities_ptz, plus the OTHER front egress camera (sibling).
* garage_a crossing on garage_a: armcrest, g5_bullet, rear_ptz, plus doorbell_lite (sibling, outward).
* garage_a crossing on doorbell_lite: armcrest, g5_bullet, rear_ptz only. The sibling garage_a is an interior camera, so it is not an outside source (it is reported as a side note, not scored).
* **I6x** variant: the perimeter cameras only (no sibling).

**Knobs (written down now):** W_pre = 60 s, W_post = 60 s, event-start based, E = the fixture / `egress_identity_outcome` crossing time, co-present guard 2 s (a sibling event with start <= E+2 and end >= E-2 is discarded as co-present, because two cameras at one door both see the person at the door), person label only.

**I6 rule:** Pre = some O event with start in [E-60, E). Post = some O event with start in (E, E+60]. `in` if Pre and not Post; `out` if Post and not Pre; both or neither = no decision. No other branch, no tuning.

**I6b rule (strict bracket):** the interior side is the tracker's own, I4 v0 (`transit_validator.py` 2408-2423: interior event in [0, ENTRY] after E = entry/in, in [-EXIT, 0) before E = exit/out; equal to the fixture `tracker_direction` on the clips). I6b decides only when I6 and the interior side are both decided and AGREE; otherwise no decision. **I6f** (reported, not the bracket): I6 if decided, else the tracker.

**Truth and gates:** the fixture human labels; 17 readable clips, 6 tracker-wrong. Gate on the current labels: 15 of 17, 5 of 6, coverage >= 0.50 on the 101 crossings of 11-14 (share decided in/out by the instrument itself). Also reported with 21:42:22 and 15:12:14 set aside (15 clips; the 6 tracker-wrong become 5), labelled as such and not the gate. Independence: per-clip miss overlap with vision run 2 (V), I4 v1 (K), Elk/cover (C), I1 v2, using the matrix in "Ensemble check" above.

**Falsifier named in advance:** I6 is worth keeping only if it reaches the gates on its own AND its misses are on different clips from V, C, I1. If coverage on the 101 crossings is below 0.50 the instrument is dead on coverage regardless of accuracy.

### I6 results (rules above, unchanged, scored once)

Scored Sun 2026-11-15 17:5x CST. Window knobs as frozen (60 s / 60 s, start-based, 2 s co-present guard). Determinism: pure function of the stored Frigate events and the crossing time; the scoring script reads the 280 events from one fetch.

| Instrument | Right of 17 (gate 15) | Tracker-wrong right of 6 (gate 5) | Decided of 17 | Wrong direction | Coverage on the 101 crossings of 11-14 (gate 0.50) |
|---|---|---|---|---|---|
| **I6** (perimeter + sibling) | **5** | **1** | 6 | 1 (21:42:22) | **0.39** (39 of 101: front 19 of 52, garage_a 20 of 49; 38 none, 24 both) |
| I6x (perimeter cameras only) | 3 | 1 | 3 | 0 | 0.30 (30 of 101) |
| **I6b strict bracket** (I6 agrees with interior side) | **4** | **0** | 5 | 1 (21:42:22) | **0.17** (17 of 101) |
| I6f (I6, else tracker; reported only) | 12 | 1 | 17 | 5 | not an instrument (fallback 61 %) |
| tracker | 11 | 0 | 17 | 6 | |

Set aside 21:42:22 and 15:12:14 (labelled; the gate stays on the current labels): I6 5 of 15, tracker-wrong 1 of 5, wrong direction 0; I6b 4 of 15, 0 of 5; I6f 11 of 15; tracker 10 of 15.

**Verdict: I6 FAILS all three gates (5/17, 1/6, coverage 0.39). I6b FAILS (4/17, 0/6, 0.17). Even with the two labels set aside, 5 of 15 and 1 of 5.** Accuracy where it decides is high (5 of 6 under current labels, 5 of 5 with 21:42:22 set aside) but it decides on a third of the clips. Reasons, read from the per-clip rows below: 8 of the 17 clips have no outside-camera event at all in the 60 s windows (the perimeter cameras adjacent to the front are sparse: front_side_ptz 21 events and utilities_ptz 7 across the 28 h window; ArmCrest none), and 3 have outside events on BOTH sides (a busy porch: 15:31:04, 16:14:56, 18:59:36). The sibling door camera (aerial for a G6 crossing and the reverse) carried the front hits (18:43:18, 19:42:11, 20:57:38); without siblings (I6x) 3 right of 17.

**Recorder cross-check (same rules, person-occupancy sensors from the recorder, Frigate occupancy legs plus the two unifiprotect person-detected sensors for rear_ptz and utilities_ptz, resolved by entity registry device).** 175 on/off intervals in the window; I6 on them: 7 right of 17, 10 decided, 3 wrong (15:12:14, 19:45:29, 21:42:22, all human `in`, all called `out`), coverage 41 of 101 = 0.41. Same conclusion; the recorder source decides more clips but gets all three `in` clips wrong (an occupancy sensor holds on after the person left, so a post-E "event" is often the tail of the crossing person).

### Per-clip matrix next to the other instruments (current labels; W = tracker-wrong; `.` = abstain; X = wrong)

V, I1 v2, K, C are copied from the "Ensemble check" matrix above (not re-run); I6 and I6b from this section; I6b = I6 where it equals the interior side, else `.`.

| Clip 11-14 | Grp | Human | T | V (run 2) | I1 v2 | K (I4 v1) | C (Elk / cover) | **I6** | **I6b** | W |
|---|---|---|---|---|---|---|---|---|---|---|
| 14:17:23 | garage | out | out | out | in X | out | in X | out | out | |
| 15:12:14 | front | in | in | out X | . | in | out X | . | . | |
| 15:31:04 | front | in | in | in | in | in | in | . (both) | . | |
| 16:14:56 | front | in | out X | . | in | in | in | . (both) | . | W |
| 17:59:51 | front | out | in X | out | out | in X | out | . (none) | . | W |
| 18:27:00 | garage | out | out | out | . | out | out | out | out | |
| 18:43:18 | front | out | out | out | . | in X | out | out | out | |
| 18:59:36 | front | in | out X | in | in | in | in | . (both) | . | W |
| 19:42:11 | front | out | in X | out | . | in X | out | out | . (interior says in) | W |
| 19:45:29 | front | in | out X | out X | . | in | out X | . (none) | . | W |
| 20:44:20 | front | out | out | out | out | out | out | . (none) | . | |
| 20:57:38 | front | out | out | out | out | out | out | out | out | |
| 21:03:34 | front | out | out | out | out | in X | out | . (none) | . | |
| 21:12:33 | front | out | out | out | out | out | out | . (none) | . | |
| 21:20:42 | front | in | in | in | in | in | in | . (none) | . | |
| 21:28:01 | front | out | out | out | out | out | out | . (none) | . | |
| 21:42:22 | front | in | out X | out X | . | in | out X | out X | out X | W |
| right of 17 | | | 11 | 13 | 10 | 13 | 13 | **5** | **4** | |
| right of the 6 W | | | 0 | 3 | 3 | 4 | 4 | **1** | **0** | |

Outside events behind each I6 decision: 14:17:23 g5_bullet +37 s and doorbell_lite +29 s; 18:27:00 rear_ptz +9 s and g5_bullet +2 s; 18:43:18 front_door_aerial +15 s; 19:42:11 front_door_aerial +3 s; 20:57:38 madrone_g6_entry +9 s and +3 s; 21:42:22 madrone_g6_entry +17 s and +44 s.

### Independence: are I6's errors independent of the others?

* **I6's only wrong direction is 21:42:22**, the same clip V, C, T and I1 (abstains) miss, and that label is the one flagged above as probably wrong (the clip shows a departure). If the label is `out`, I6 has no wrong direction under the corrected label and is right on it; if it is `in`, I6 shares the miss with V and C. Either way this is not independent evidence about a hard clip.
* **I6's five rights are clips V already gets right** (14:17:23, 18:27:00, 18:43:18, 19:42:11, 20:57:38; also right in C except 14:17:23 and right in I1 except where I1 abstains). It fixes none of V's, C's and I1's shared misses (15:12:14, 19:45:29, 21:42:22): it abstains on the first two (no outside event) and is wrong on the third. It adds one clip where C and I1 are both wrong (14:17:23: cover and I1 say `in`, I6 says `out`), which is not enough to matter.
* So the errors are not shared because I6 mostly abstains where the others fail, not because it reads a different fact correctly on those clips. On the clips that discriminate (the six tracker-wrong clips) it decides one (19:42:11) and is wrong on one (21:42:22).
* Agreement with the tracker over all 101 crossings: where both decide (29 crossings), I6 agrees with the tracker's entry/exit on 17 (in/in 8, out/out 9) and disagrees on 12; the tracker is 35 % wrong on the readable clips, so this is not an accuracy number.

### I6 verdict and what changes

**NO-GO for I6 and I6b on the gates.** Direction stays the tracker's; P3-D9c is not planned on I6. The operator's premise (outside cameras clear things up) holds where an outside camera sees the person within 60 s (5 of 6 right) but that happens on 39 % of crossings at the front and the back combined, and the cheap alternatives are exhausted: widening W to 120 s was NOT run (the windows were frozen; doing it now would be tuning after seeing the sparsity). A larger W would add decisions but also raise the "both" share (3 of 17 now), and any change needs a new pre-registration. Revival trigger: a front approach camera whose Frigate events cover the driveway and walkway (today front_side_ptz and utilities_ptz are sparse and ArmCrest has no events in the window), re-scored on a larger labelled set than 17. A second label pass on 21:42:22 and 15:12:14 is the cheaper lever, as in the Ensemble check.

## G6 Entry I1 polygon re-check (the "sees only the mat" claim)

Viewed `.claude/tmp/door_snap_madrone_g6_entry.jpg` (the Frigate `camera.madrone_g6_entry` snapshot of 2026-11-15 16:51:18, 720x960 portrait fisheye, one image per Read call) and read the fixture `quality/tests/fixtures/crossing_door_reference_frigate_v2.json` polygon for `madrone_g6_entry`.

**The earlier note "G6 sees only the mat" (Front-door contact facts / I1 v2 verdict above: "a front camera that sees the approach (G6 Entry sees only the mat)") is wrong and is withdrawn.** What the image shows: the left half is the approach, with lawn, gravel bed, stepping stones climbing from the lower left (x 0-0.28, y 0.65-0.85) and porch paving along the bottom; the middle is a white limestone pier (x 0.30-0.62, y 0.15-0.72); the glass door and sidelights run down the right edge (black frame from about x 0.83 at y 0.3 to x 0.80-0.88 at the bottom, leaning with the fisheye); the doormat is at the bottom right (x 0.45-0.87, y 0.78-1.0) and abuts the lower glass. The upper left is blown out (white sky), so a person at x < 0.3, y < 0.5 is not detectable.

**Does the v2 polygon cover the door correctly?** Position: yes. [(0.82,0.25),(1.0,0.25),(1.0,1.0),(0.55,1.0),(0.55,0.78),(0.82,0.74)] covers the glass strip and the mat in front of it. What it gets wrong as a crossing test:
1. It includes the whole mat out to x = 0.55. A person standing on the mat is not yet at the door; arrival tracks (15:12:14 first point (0.63, 0.99); 19:45:29 first point (0.67, 0.88), both from the I1 v2 notes) start inside the polygon, so "start outside, end inside" cannot fire. The test only separates tracks that begin on the stepping stones, which this camera often misses (the blown-out upper left, and late detection).
2. The upper glass (y 0.25-0.72, x > 0.83) shows the house interior through the sidelights; a person inside walking past is "in the polygon" without any door crossing. The real door opening is the lower panel where the mat meets the frame, bottom right.
3. The test is positional (start in/end in), so it discards the strongest cue this camera has: horizontal displacement along the approach. From the point lists already in the I1 v2 section (not re-scored here): 15:12:14 moves (0.63,0.99) -> (0.89,0.98) and 19:45:29 (0.67,0.88) -> (0.91,0.96), both rightward toward the door (human `in`); 19:42:11 moves (0.12,0.78) -> (0.02,0.71), away from the door to the left (human `out`); 18:43:18 has two points near (0.05, 0.81), too short to read.

**Proposed better door-crossing line (NOT scored, NOT frozen as v3; a proposal for the operator or the next cycle):** (a) door strip: a thin polygon on the door opening only, about [(0.82,0.74),(1.0,0.74),(1.0,1.0),(0.88,1.0)], without the mat and without the upper glass (the lower panel where the mat ends at the frame); (b) a directed rule instead of start/end membership: a track whose x moves at least 0.15 toward the strip and ends inside or within 0.05 of it = arrival, one that starts inside the strip and ends at least 0.15 further left = departure, anything shorter = unclear; (c) ignore points with y < 0.74 for the decision (interior glass). Hazards named in advance: a person lingering on the mat gives displacement under 0.15 (unclear, as today), and a person stepping out and back (15:12:14) would still be read as `in` by their last move. If adopted, it needs a v3 fixture committed before any scoring, the same 17/6 gates and a coverage count, and the pad-sweep caveat from the I1 v2 section; I1 stays NO-GO until then. The downward package lens is a separate entity and was not used.
