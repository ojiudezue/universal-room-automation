# AUDIT: crossing vision Phase 3 P3-D0 probe (go/no-go), 2026-11-15

Run Sun 2026-11-15 15:36-16:50 CST by the read-only prober. Spec: `PLANNING_crossing_vision.md` at 50bffd62, P3-D0 and step 0 (read completely, with `AUDIT_door_vision_accuracy_2026_11_14.md`, `crossing_vision.py`, `perimeter_enrichment.py:360-470`). Presence/HVAC state-of-play docs not needed (no presence or HVAC logic touched).

Fixture (committed with this audit): `quality/tests/fixtures/crossing_vision_door_eval_2026_11_14.json`.
**Luna model calls used: 91 of the 120 cap** (log `.claude/tmp/p3d0_calls.jsonl`, one JSON line per call): 1 route probe (c) + 4 error re-runs (e) + 46 replay R1 + 19 R2 + 19 R3 + 2 diagnostic. HA state changed only by the llmvision `video_analyzer` service calls (provider "OpenAI Madrone Vision" = `CROSSING_VISION_PROVIDER_ID` `const.py:3587`, model `gpt-6-luna` `const.py:3575`, 768 px, `max_tokens` 1500, same call shape as `analyze_crossing_frames`, `perimeter_enrichment.py:410-431`).

## Verdicts

| Gate | Verdict | Headline |
|---|---|---|
| Step 0 retention + fixture | DONE | 46/46 event clips retrievable (HTTP 200) through the HA Frigate proxy; fixture written before any replay |
| (a) volume / cap | **GO** | max simulated daily calls 62 (11-14, ambiguous included) -> cap `ceil(62 x 1.5)` = **93**; busy collisions 0 of 137 (1 of 137 at a pessimistic 90 s call); `memory_episodes` 18,855 rows < 200,000 so no new index |
| (b) direction | **NO-GO** (park the direction part of P3-D3/D6/D7) | best config right on 14/17 readable (gate 15) and 3/6 tracker-wrong clips (gate 5) |
| (b) group count | **NO-GO on the strict plan numbers; one named fix to retest** | 18:43 party under-counted by 2 in every config (gate <= 1); one new over-count on the 8-frame event-clip route; root cause of both empty large-group replies found (`max_tokens`) |
| (c) recording-proxy route | **GO** | llmvision fetched `/api/frigate/frigate-f2/recording/<cam>/start/<s>/end/<e>`: status 200, 7 frames returned; recording complete about 5 s after window end |
| (d) round trips / pass mechanism | **HOLD** | at most 19 hand-labelled round trips are possible (4 found + 15 unviewed) < 20, and pass rule (ii) shares a pass key on only 4 of 21 opposite pairs |
| (e) error text | informational, not reproduced | 0 of 4 re-runs errored; no error text exists to capture; the 4 on 11-14 were transient |

## Step 0. Retention and fixture

* Events listed over the HA Frigate websocket (`frigate/events/get`, instance `frigate-f2` = the `client_id` attribute of the Frigate camera entities; not the config-entry id): 834 person events on the 4 door cameras, earliest 2026-11-02 (about 13 days of Frigate event retention). So the plan's 30-day mining horizon is impossible on the Frigate side regardless of DB retention.
* All 46 11-14 event ids: in the event list, `has_clip` true, clip route `/api/frigate/frigate-f2/notifications/<id>/clip.mp4` HTTP 200 (first pass 33, remaining 13 re-checked after a restart blip). Local copies also exist from the previous audit.
* Disturbance to disclose: a bulk download burst (the proxy ignores `Range`, so each probe pulled a whole clip, about 1.4 GB total) ran 15:43-15:45 CST; HA stopped at 15:45:48 and started 15:48:14 (recorder `homeassistant_stop` / `_start`). The commit log shows v5.108.26 was deployed 15:43-15:48 (`893fe07e`, `b33dd68a`), so the restart is that deploy's, not the probe's (not proven; no journal on the ssh host). Clip probes during 15:45-15:49 saw 000/404, re-checked fine afterwards. Later probes used early-closed reads.
* Fixture: 46 events (event id, camera, door group, crossing key, tracker direction, human count + confidence flag, human direction or `unreadable`, tracker-wrong flag, production outcome/count, camera peak, group-gate flag), 25 pairs with relation (opposite/same) and a `one_pass` / `round_trip` / `unknown` label plus label basis, and 43 `mined_pairs`. Human counts and 17 readable directions are transcribed from the 11-14 audit tables (section 2, 3b), not re-judged, except 18:59:36.
* **18:59:36 pin:** frame by frame (contact sheets of the clip, 06:59:40-06:59:48 PM overlay) one frame shows 8-9 distinct people and the party keeps arriving; I could not pin one integer (range 8-10). Per the plan it is reported and **excluded from group pass/fail**; `human_count` is null in the fixture.

## (a) Volume

Sources and limits (be careful reading the numbers): `egress_identity_outcome` exists only from 2026-11-13 (192 rows, 3 days); earlier days come from `person_entry_exit_events` (resolved crossings only, logged at resolution time = E + 0-45 s, so E is approximated as t - 20 s and ambiguous crossings are unknown, and about 70-75 % of the outcome-table count on overlapping days: 11-13 had 27 logged vs 37 resolved). So the 14-day max is a lower-bound for pre-11-13 days; the max day is a day with full data.

| Day | resolved | ambiguous | simulated calls (resolved only) | simulated calls (ambiguous included) | camera peak >= 3 | HA starts |
|---|---|---|---|---|---|---|
| 11-08 | 26* | n/a | 18 | n/a | 0* | 3 |
| 11-09 | 6* | n/a | 5 | n/a | 0* | 2 |
| 11-10 | 2* | n/a | 2 | n/a | 0* | 4 |
| 11-11 | 12* | n/a | 11 | n/a | 1* | 3 |
| 11-12 | 27* | n/a | 18 | n/a | 0* | 5 |
| 11-13 | 37 | 42 | 25 | 55 | 8 | 5 |
| 11-14 | 81 | 20 | 54 | **62** | 10 | 4 |
| 11-15 (to ~15:00) | 2 | 10 | 1 | 8 | 0 | 2 (15:45 deploy restart, 14:17 earlier) |

(* = from `person_entry_exit_events`; 10-29..11-07 also computed, all <= 25 calls/day; script `.claude/tmp/p3d0_vol.py`.) Simulation: primary = first crossing of a door group not within 60 s of the group's previous primary (`CROSSING_VISION_CLUSTER_S`), ignoring the event-match miss rate (so an upper bound). HA starts from the recorder `homeassistant_start` events (recorder holds 11-08 onward only).

* **Cap:** max simulated 62 x `CROSSING_VISION_CAP_HEADROOM` 1.5 = **93** (<= 200). If pre-11-13 days were scaled up by 1/0.73 the max stays 62 (11-14 is the busiest day). Note ambiguous share is 53 % on 11-13 and 20 % on 11-14, so watching ambiguous roughly doubles 11-13-type days.
* **Busy collision (`MAX_CONCURRENT` = 2):** modelled with fire time = matched Frigate event end and a 15 / 40 / 90 s call: 0 of 103 (resolved only) and 0 / 0 / 1 of 137 (ambiguous included). Measured call latency on the replay was 7-29 s (event-clip route, 25-29 s for the 8-frame group clips). Observed in production 11-14: zero `skipped_busy` rows (previous audit). Rate < 1 %: **GO**.
* `memory_episodes`: 18,855 rows (min 2026-08-02), 394 rows added on 11-14 -> far below `CROSSING_VISION_CAP_REHYDRATE_INDEX_ROWS` (200,000): no `idx_episodes_type_ended` needed.

## (b) Direction and count replay

Prompt (new, fixed here; P3-D3 prompt text) and schema = production schema plus `direction` enum `in|out|passing|unclear`, "from each person's first and last position against the door; `in` = from outside into the building". Configs: R1 event clip, 8 frames, all 46 events; R2 event clip, 4 frames, the 17 readable + 2 extra group clips (19); R3 recording window [E-10, E+15], 8 frames, the same 19. Truth = the fixture's human labels.

| Config | direction right (gate 15/17) | tracker-wrong clips right (gate 5/6) | tracker-right clips right |
|---|---|---|---|
| R1 event clip x 8 | 12/17 as run; **14/17** after re-running the 2 empty replies (below) | 2/6 as run; **3/6** after the re-run | 10/11 |
| R2 event clip x 4 | 11/17 (2 empty) | 2/6 | 9/11 |
| R3 recording window x 8 | 11/17 (2 empty) | 2/6 | 9/11 |

Discrimination: a model copying the tracker's bias scores <= 11/17 and 0/6; vision scores 14/17 and 3/6, so it is not a copy of the tracker (it gets 17:59:51, 19:42:11, 18:59:36 right) but it still misses the plan's bar. Misses in the best config: 16:14:56 (`unclear`), 19:45:29 and 21:42:22 (vision `out`, human `in`; vision's own description on 21:42 says "walks out of the doorway", my hand label from the earlier audit says it walks from the path to the door; the human label is the plan's truth). **Verdict NO-GO: direction part of P3-D3, P3-D6, P3-D7 parks** (card, revival = new model or route re-run on the same fixture, per plan). Count-only watching of ambiguous crossings still ships.

**Count / group (R1 8 frames vs production on the 11-14 run):**
* Empty replies: the two largest groups (18:43:18 party of ~7, 18:59:36 party of 8-10) returned `response_text: ""` in all 6 calls (R1, R2, R3) = production `OUTCOME_REFUSED`. Cause: output token exhaustion at `CROSSING_VISION_MAX_TOKENS` 1500. Re-run with `max_tokens` 4000 (2 diagnostic calls): 18:43 -> 5 people, direction `out` (correct); 18:59 -> 8 people, direction `in` (correct). **P3-D2 must raise `CROSSING_VISION_MAX_TOKENS` for the 8-frame group path (4000 worked; latency 25-30 s).**
* Group gate (undercount <= 1 against human; 18:59 excluded): 18:43 vision 5 vs human 7 -> under 2, FAIL (production 11-14 had 6); 21:24:08 R1 2 / R2 3 vs 4 -> under 2 / 1; 21:28:01 2 vs 3 -> under 1 PASS; false blank 16:19:36 -> 4 vs 4 PASS in every config (fixes the false blank). Strict reading: FAIL on 18:43.
* New over-count on the 33 exact clips: R1 has one (16:30:44, human 2, vision 3, was 2 in production). R2/R3 covered only 19 clips so the other exact clips are unmeasured there.
* All counts R1: exact 37, over 2, under 5 of 44 with human count (production on the same: 33/41 exact on 41 ok rows).
* **Verdict (b) group: NO-GO on the strict numbers.** The single-variable retest that would change it: R1/R2 with `max_tokens` 4000 on the 4 group clips + the exact clips (29 calls of budget left, unspent because the plan says "decide on this run").
* Frame observation (R3): the [E-10, E+15] window is dominated by empty leading frames (frame counts like `[0,0,0,2,3,4,4]`), so BEFORE should be nearer 5 s than 10 s.

## (c) Route check (recording proxy)

* One llmvision call, `video_file = /api/frigate/frigate-f2/recording/front_door_aerial/start/<E-10>/end/<E+15>` (E = 2026-11-14 20:44:20): HTTP 200 in 10.9 s, 7 structured frames returned (8 requested), `direction: out`. Authenticated view works because llmvision signs the HA path (the instance-scoped form with the `client_id` works). **GO: `CROSSING_VISION_FRAME_ROUTE = recording_window` is usable.** R3 then ran 19 calls on the route, all 200.
* **Recording lag** (no model calls; direct fetch of the last 25 s window at lag 0, 5, 10, 20, 30, 60, 120 s on front_door_aerial and garage_a): window length returned 24.7-30.1 s for every lag >= 5 s; at lag 0 garage_a returned only 14.8 s. So `CROSSING_VISION_RECORDING_LAG_S` = 10 (observed complete from 5). Each fetch took 1-2 s.
* Note: the proxy ignores `Range`; a probe downloads the whole body.

## (d) Pass mechanism and the round-trip negative set

**Data limit.** Mining was done from `egress_identity_outcome` (3 days, exact E) plus `person_entry_exit_events` for 10-30..11-12 (E approximate); Frigate events exist only back to 11-02, so the effective horizon is 13 days, not 30. Candidates: opposite-direction crossings in one door group within 60 s whose Es both lie inside one Frigate event, plus every cluster pair of the 11-14 audit: 43 pairs (fixture `mined_pairs`).

**Hand labels** (contact sheets of the recording window, rubric: `round_trip` = two distinct door traversals in opposite directions in the clip; `one_pass` = one traversal or one person loitering at the door; `unknown` = no door traversal visible, e.g. driveway-only view). Viewed 28 of 43: 14 `one_pass`, 4 `round_trip` (pairs 11 cleaners in and out on 11-13 12:22; 19 and 20 man leaves and re-enters the garage 11-14 14:17-14:19; 40 one person leaves, a different person arrives 17 s later, 21:42), 10 `unknown`. Not viewed: 15 (listed in the fixture as `not_viewed`).

| Gate | Result |
|---|---|
| >= 20 hand-labelled round trips | **4 found; 4 + 15 unviewed = 19 < 20 at most -> HOLD** (arithmetic; the 15 unviewed are also mostly the audit's single-person descriptions) |
| rule (ii) merge share of round trips, Wilson 95 % upper bound | 0 of 4 -> UB 0.49 (n too small; the 0.15 bar is unreachable below n = 20) |
| rule (i) (`_match_event` group pick) beside it | 1 of 4 -> UB 0.70 |
| rule (ii) shares a pass key on >= 80 % of `one_pass` pairs | **FAIL: 4 of 14 (0.29)** on the labelled `one_pass` pairs |

* The 11-14 pair mechanism table (25 audit pairs): opposite 21: rule (i) shares an event on **3**, rule (ii) on **4**; same-direction 4: 0 and 0. Sensitivity of rule (ii) to the pad: 2 s 5/24, 10 s 5/24, 30 s 8/24, 60 s 9/24 (24 opposite pairs incl. chain links). Reading: most pairs sit 17-58 s apart while Frigate events last 5-60 s, so the member lands in a different event; pass-key collapse as specified would merge about a fifth of the pairs the audit counted as one physical pass.
* The `end is None` share at resolution time: of 116 crossings with a rule-(ii) pass event (4 have none), 9 (7.8 %) belong to an event whose recorded end is later than E + 45 s, i.e. plausibly still open at resolution.
* The audit's open falsifier (interior events around 14:17:23 / 14:17:54, 11-14): Frigate person events on interior cameras bracket both crossings: `staircase 14:17:04-14:17:26`, `family_room 14:16:47-14:17:43` and `14:17:43-14:18:03`, `g5_bullet 14:18:01-14:18:31` (plus `garage_a 14:17:22-14:18:12`, `doorbell_lite 14:17:52-14:18:37`). Consistent with the exit-then-entry mechanism (interior activity just before the first and just after the second); not proven (I did not run the tracker's ring).
* **Verdict HOLD** per the plan: P3-D4 ships with `CROSSING_VISION_LEDGER_PASS_COLLAPSE` False, P3-D9b waits; the rest of Phase 3 is not blocked. Extra finding for the plan: even with enough round trips, rule (ii) as written fails the >= 0.80 same-pass bar by a wide margin on this data, so P3-D9b needs a different pass mechanism (or a longer window), not just more labels.

## (e) Error clips

Re-ran the 4 clips with the production prompt/schema/4 frames (16:16:11, 16:20:48, 16:23:52, 17:11:19): all 4 returned 200 with a valid structured response in 7-18 s (counts 2, 2, 3, 1 vs human 3, 2, 3, 1). **0 of 4 reproduce; no error text to record.** The 11-14 errors (about 2.2 s) were therefore transient (the day audit saw two HA restarts that day; the error time cluster 16:16-17:11 was not tied to one). P3-D1 (error text on the row) remains the way to capture the next one; the 5th "blank" and the group false-blank are covered above.

## What is unchanged / not done

* 29 calls unspent; no config sweep beyond the three plan configs and the 2 token diagnostics.
* Not viewed: 15 mined pairs (their labels are `unknown`, basis `not_viewed`); same-direction pairs are not labelled.
* No HA config, helper, or entity state was changed; clips only through the HA Frigate proxy; no Bermuda diagnostics; the HA token was only read into process memory (it is visible in the local process list of the curl probes while they ran, never printed or written).
* Scripts: `.claude/tmp/p3d0_*.py` (not committed).
