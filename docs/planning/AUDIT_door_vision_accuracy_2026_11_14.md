# AUDIT: door crossing vision accuracy, 2026-11-14 (is it counting well? is direction the failure?)

Read-only probe, written 2026-11-15 (Sun) ~15:10 CST (`date` at start 14:02 CST; DST ended 11-01, zone is CST). Not committed.
Read first, completely: `PLANNING_crossing_vision.md` (INV-SCOPE / INV-BLANK / INV-ADDITIVE, §5 D1, §6 knobs), `crossing_vision.py`
(lines cited below), `AUDIT_crossing_vision_day_2026_11_14.md`, `vision_report_1114.json`. Presence/HVAC state-of-play docs not
needed (no HVAC; presence only through the census path already covered by the day audit). Identity manual §W1 read for the twin rule.

## Answer first

| Part | Verdict | Headline |
|---|---|---|
| 1 Design conformance | WORKING (one spec gap: frame selection) | 46 of 46 calls matched an event on the right camera in the right door group, max offset 9.9 s (limit 10). Clustering, cap, concurrency, shape all as designed. |
| 2 Counting | WORKING on 1-2 people, NOT WORKING on groups >= 3 | Vision exact 33/41 = 80.5 % on `ok` rows; all 8 misses are UNDER-counts (0 over). Frigate peak exact 33/41 = 80.5 % on the same rows (3 over, 5 under). Groups of 3+ are always undercounted by both. |
| 3 Direction | NOT WORKING | In 17 clips where direction is visible, 6 are labelled wrong (35 %), mostly arrivals labelled "exit". The 21 opposite-direction cluster members are NOT a Frigate-Protect double count of one camera in most cases. |
| 4 Verdict | Count: fine for singles, fails for groups. Direction: the top failure. | Net-negative totals come mainly from direction labels, plus group undercount and unseen arrivals; not from real asymmetry alone. |

## 1. Design conformance

Evidence base: shadow rows via `ssh ha` read-only (`memory_episodes`, type `crossing_vision_shadow`, 11-14: 73 rows = 41 ok, 25 clustered,
4 error, 1 blank, 2 no_frigate_event; the 11-14 json confirms), plus the live Frigate event id carried in each row (`attrs.event_id`).
A Frigate event id begins with the event start epoch, so match offset is checkable without the Frigate API.

| Designed behaviour | Live result | Verdict | Code |
|---|---|---|---|
| Trigger: every non-ambiguous `ura_person_egress_event` (entry/exit) reaches vision; ambiguous skipped | 73 rows = 81 non-ambiguous crossings minus 8 before the 12:48:34 switch-on; 20 ambiguous crossings skipped with no row, counter or term | WORKING by design; skip is silent (blind spot) | `crossing_vision.py:612-618` |
| Frigate event match (INV-SCOPE: event on a camera in the crossing's door group, start within +/-10 s) | 46 distinct matched events: `event_camera` in own door group 46/46 (front: madrone_g6_entry 18, front_door_aerial 11; garage_a: garage_a 11, doorbell_lite 6). Offset of event start vs crossing E: min -7.1 s, max +9.9 s, never > 10 | WORKING (0 cross-group, 0 out-of-window). 9.9 s is at the edge: the 2 `no_frigate_event` rows show the window is tight (D0 measured 26 % unmatched at +/-10 s) | `:675-678`, `_match_event` `:761-778`, `CROSSING_VISION_EVENT_MATCH_S = 10` `const.py:3609` |
| Clustering (same door group within 60 s, or already-analysed event, no second call) | 25 clustered rows; max gap to primary 58 s, all in the same door group. Only 4 of the 25 share the primary's direction | WORKING as built; the rule never looks at direction (see part 3) | `:664-672`, `_join_cluster` `:728-749` |
| Frame selection | `video_analyzer` is given the WHOLE Frigate event clip (`/api/frigate/<instance>/notifications/<id>/clip.mp4`) and llmvision picks `max_frames=4` evenly across it; clip lengths 5-466 s (median ~25 s). Frames returned: 4 on 37 rows, 3 on 4, 2 on 1. 24/41 ok rows have at least one EMPTY sampled frame | WORKING as built, but there is no crossing-centred frame choice. Plan §5 D1.7 never specified one | `_clip_reference` `:830-855`, `analyze_crossing_frames` `perimeter_enrichment.py:410-427` |
| Call result shape | 41 ok with `frame_counts` list + `people_count` clamped to [max frame, max x frames]; blank has `people_count` None (never 0); 4 errors have no vision fields | WORKING | `parse_vision_response` `:153-235`; INV-BLANK honoured (blank row 16:19:36, `people_count` None) |
| Daily cap and concurrency | 46 calls on 11-14 against cap 40. Live number `number.ura_notification_manager_crossing_vision_daily_calls` = 40. Explained: the cap counter is RAM and HA restarted at 16:06:48 and 22:02:18; calls were 14 before 16:06 and 32 after, each segment under 40. This is the plan's accepted residual | WORKING (residual visible: 46 > 40 in one local day). No `skipped_cap`, no `skipped_busy` rows | `:693-703`, `:873-877`; plan INV-SCOPE |
| INV-ADDITIVE (DB peak = bus peak) | Holds on all 73 (day audit) | WORKING | D2 |
| Latency | ok calls p50 9.7 s, p90 18.6 s, max 38.7 s (n=41, day audit) | WORKING | |
| Errors | 4 of 46 calls errored in ~2.1-2.3 s (16:16:11, 16:20:48, 16:23:52, 17:11:19); cause unknown (logged at INFO only, no retained log). All four clips are valid h264 today (downloaded and decoded), so it was not a missing clip | UNKNOWN cause | `perimeter_enrichment.py:452-457` |

## 2. Is it counting well: independent ground truth

Method. For each of the 46 matched Frigate events I fetched the event clip through HA's Frigate proxy (HA token from the keychain, held in
a shell variable, never printed; no Frigate login). Endpoint pattern from `/config/custom_components/frigate/views.py` (read over ssh):
`/api/frigate/notifications/<event_id>/{snapshot.jpg,thumbnail.jpg,clip.mp4}` (lines 316-340) and `/api/frigate/snapshot/<event_id>`
(line 227). The instance-scoped form wants the MQTT `client_id`, not the config entry id (`views.py:60-64`); the default-instance form works
with the single Frigate entry. All 46 clips downloaded (HTTP 200; one snapshot 404, clip fine). I built 8-frame (12 for the 466 s clip)
contact sheets with ffmpeg and counted distinct people myself, using denser sheets for the ambiguous ones. This is a human-eye count of
the clip, not of the 4 frames vision saw. Where I am not sure I say so.

Media saved (flat, because I may not mkdir `vision_eval_media/`): `/Users/okosisi/Code/universal-room-automation/.claude/tmp/vision_eval_media_<event_id>.{snap.jpg,clip.mp4,sheet.jpg}` and `..dense_*.jpg` (144 files, clips 1.6 GB, sheets 28 MB). Mapping event to row: `/Users/okosisi/Code/universal-room-automation/.claude/tmp/visev_index.txt`; scripts `visev_*.py|sh` in the same dir.

Table (one row per event = per primary crossing; `ok` rows 41, then the 5 non-ok). `*` = my count is low-confidence.

| Time | Camera (event) | Vision | Peak | My count | Vision agrees? | Peak agrees? |
|---|---|---|---|---|---|---|
| 12:59:22 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 13:01:06 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 13:40:36 | garage_a | 1 | 1 | 1 | yes | yes |
| 14:17:23 | garage_a | 1 | 1 | 1 | yes | yes |
| 14:18:39 | garage_a | 1 | 2 | 1 | yes | no (over) |
| 14:26:25 | garage_a | 1 | 1 | 1 | yes | yes |
| 14:27:51 | garage_a | 1 | 2 | 1 | yes | no (over) |
| 15:12:14 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 15:23:04 | doorbell_lite | 1 | 1 | 1 | yes | yes |
| 15:24:28 | garage_a | 1 | 2 | 2 | no (under) | yes |
| 15:25:50 | doorbell_lite | 1 | 1 | 2* (2nd small figure last frame) | no (under)* | no (under)* |
| 15:31:04 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 15:52:52 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 16:08:03 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 16:14:56 | madrone_g6_entry | 1 | 2 | 2 (woman with package, then a second woman) | no (under) | yes |
| 16:30:44 | garage_a | 2 | 3 | 2 | yes | no (over) |
| 16:39:28 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 16:41:01 | doorbell_lite | 1 | 1 | 1* | yes | yes |
| 17:30:13 | doorbell_lite | 1 | 1 | 1 | yes | yes |
| 17:31:26 | garage_a | 1 | 1 | 2* (child then adult with bags) | no (under)* | no (under)* |
| 17:59:51 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 18:27:00 | doorbell_lite | 1 | 1 | 1 | yes | yes |
| 18:43:18 | madrone_g6_entry | 6 | 5 | 7 (party at the door) | no (under 1) | no (under 2) |
| 18:52:54 | doorbell_lite | 1 | 1 | 1 | yes | yes |
| 18:59:36 | front_door_aerial | 4 | 4 | 8-9 (party arriving, hats, ~9 in one frame) | no (under ~5) | no (under ~5) |
| 19:42:11 | madrone_g6_entry | 2 | 2 | 2 | yes | yes |
| 19:45:29 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 20:34:47 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 20:44:20 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 20:57:38 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 21:03:34 | madrone_g6_entry | 2 | 2 | 2 | yes | yes |
| 21:12:33 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 21:15:44 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 21:20:42 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 21:24:08 | madrone_g6_entry | 2 | 4 | 4 (3 leave, 1 enters) | no (under 2) | yes |
| 21:28:01 | madrone_g6_entry | 2 | 1 | 3 | no (under 1) | no (under 2) |
| 21:42:22 | front_door_aerial | 1 | 1 | 1 | yes | yes |
| 21:43:40 | madrone_g6_entry | 1 | 1 | 1 | yes | yes |
| 21:50:21 | garage_a | 1 | 1 | 1 | yes | yes |
| 21:51:42 | garage_a | 1 | 1 | 1 | yes | yes |
| 21:54:39 | garage_a | 2 | 2 | 2 | yes | yes |
| 16:16:11 (error) | madrone_g6_entry | - | 2 | 3 (grey cardigan woman, blond woman, man) | n/a | no (under) |
| 16:19:36 (blank) | front_door_aerial | blank | 3 | 4 (family of 4 at the door) | false blank | no (under) |
| 16:20:48 (error) | front_door_aerial | - | 3 | 2 | n/a | no (over) |
| 16:23:52 (error) | madrone_g6_entry | - | 1 | 3 | n/a | no (under) |
| 17:11:19 (error) | front_door_aerial | - | 1 | 1 | n/a | yes |

(41 ok rows in time order, then the 5 non-ok rows = 46 events.)

Accuracy on the 41 `ok` rows (count over a clip):

| Instrument | Exact | Over | Under | People total (mine 67) |
|---|---|---|---|---|
| Vision | 33/41 = 80.5 % (35/41 = 85.4 % if my two low-confidence counts are dropped) | 0 | 8 (all) | 55 = 82 % |
| Frigate peak (`camera_peak_count`) | 33/41 = 80.5 % | 3 | 5 | 60 = 90 % |
| Peak on the 5 non-ok clips | 1/5 | 1 | 3 | n/a |

Shape of the errors. Vision is exact on every clip with 1 or 2 people except the 15:24, 16:14 and (low confidence) 15:25 and 17:31 clips,
where a second person appears at a different time in the clip. It undercounts every group of 3 or more: 18:43 (6 vs ~7), 18:59 (4 vs ~9),
21:24 (2 vs 4), 21:28 (2 vs 3). The Frigate peak has the opposite weakness on singles (3 over-counts of a single person in a garage clip,
peak 2 or 3) and is also low on groups (18:43 5 vs 7, 18:59 4 vs 9, 21:28 1 vs 3). Vision's one `blank` is a false blank (clip shows 4 people;
only ONE frame was returned, `frame_counts [0]`). Vision answer coverage: 41 of 46 matched events (89 %); the other 5 (4 errors, 1 blank) fall back to the camera peak, which on those 5 clips was wrong 4 times out of 5.

Mechanism for the group undercount (code): the call gives the model 4 frames of 768 px sampled evenly over the whole event
(`CROSSING_VISION_MAX_FRAMES 4`, `_TARGET_WIDTH 768`, `const.py:3594-3596`), and 24 of 41 ok rows contain an empty sampled frame
(`[0,4,4]` at 18:59, `[2,0,0]` at 19:42). A crowd that fills the doorstep for 2-3 s can be in 1-2 of 4 frames; the per-frame counts then cap the answer
(the clamp upper bound `peak x frames` does not lift it). Falsifier I could not run (a model call is a state-adjacent spend and I am read-only):
re-run 18:59 with more frames / a crowd-aware prompt and see whether the count rises toward 9.

## 3. Is direction the failure?

### 3a. The 21 opposite-direction members: who are the pairs?

I resolved each primary/member pair through the registry device ids in the 11-14 json (`camera.device_id`) and the W1 rule (a Frigate device
twins the non-Frigate device whose slug equals the Frigate object name from its identifier; `IDENTITY_FUSION_CAMERAS_MANUAL.md` W1 section,
`camera_resolver.py:895`; live registry identifiers read from `.storage/core.device_registry`: `frigate:<entry>:madrone_g6_entry`, `:front_door_aerial`,
`:garage_a`, `:doorbell_lite`).

| Pair class (primary vs member) | Opposite dir | Same dir |
|---|---|---|
| Same registry device, same platform (e.g. Garage A Protect twice, 17-36 s apart) | 8 | 0 |
| W1 twin: Frigate + Protect of the SAME camera (Madrone G6 Entry, Front Door Aerial, Garage A) | 3 | 0 |
| Different cameras on the same door group (Madrone G6 Entry vs Front Door Aerial) | 8 | 3 |
| Doorbell Lite (Frigate) vs Garage Doorbell Lite (Protect): the names differ, so NO W1 pair (slug `doorbell_lite` != `garage_doorbell_lite`); both are in door group garage_a | 2 | 1 |
| Total | 21 | 4 |

Answer: only 3 of the 21 are the Frigate and Protect entity of the same physical camera. 8 are the same camera device reporting twice, 8 are the
two front cameras (or the two garage cameras) of one door. So the pairs are not mainly "double reporting by two NVR entities"; they are the egress
tracker emitting an exit and an entry within 1-58 s of each other for one physical pass.

Mechanism (code, not run): `_resolve_direction` decides direction only from the timing of near-door INTERIOR camera detections: interior fires 0..45 s
after the egress event = entry, up to 30 s before = exit (`transit_validator.py:1085-1089`, `:2408-2423`); dedup is keyed by direction so an
opposite-direction event inside the window is never collapsed (`:2425-2438`, "exit then entry inside 30 s is a real round-trip"). One pass that
trips two egress sensors a few seconds apart, with interior activity on both sides, therefore yields an exit and an entry. Crossing vision then
clusters them by door group and time only (`crossing_vision.py:664-672`), never by direction, so the ledger gets +n and -n (day audit §4). UNVERIFIED:
that the interior events actually bracket these pairs; falsifier = replay the interior near-door events around 14:17:23 and 14:17:54.

### 3b. Is the direction label right? Clip-by-clip (sample, 17 clips where direction is visible)

I looked at the first and last position of the person against the door in the contact sheets (ffmpeg is present: `/opt/homebrew/bin/ffmpeg`).
Correct label: 18:43 exit (party leaves), 21:03 exit, 21:12 exit, 20:57 exit, 20:44 exit, 21:28 exit, 21:20 entry, 15:12 entry, 15:31 entry,
14:17 exit, 18:27 exit (11). WRONG label: 17:59:51 labelled entry, person walks away from the door; 19:42:11 labelled entry, two people walk away;
18:59:36 labelled exit, about 9 people ARRIVING; 19:45:29 labelled exit, man walks to the door and goes in; 16:14:56 labelled exit, woman walks
up with a package; 21:42:22 labelled exit, person walks from the path to the door (6). Not judged (no clear door passage): 12:59, 13:01 ladder clips,
garage walk-bys (14:18, 14:27, 14:26), 15:52, 16:08, 16:39, 21:15, 21:43 and others. Vision's own descriptions agree with me on the wrong ones
("leaves the doorway" at 17:59, "walk toward the house entrance" at 18:59, "walks toward the door carrying a package" at 16:14).

So direction is wrong in 6 of 17 visible cases (35 %), and the errors lean one way: 4 arrivals labelled exit (about 12 people) against 2 exits labelled entry (3 people).
That is a swing of about 9 people from "in" to "out" in this sample alone, one 9-person arrival being labelled an exit with a count of 4.

### 3c. Where does the net-negative come from?

Vision 9 in / 46 out; door crossings 30 / 43. Decomposition I can support:
1. Direction labels: the sample above moves about 9 people from out to in (a 18-point swing on the net of -37). Mislabelled arrivals dominate.
2. Group undercount: the 18:59 party arrival alone is ~5 people short, and it is labelled an exit anyway.
3. Twin passes: the 21 opposite-direction clustered members add a second term of the opposite sign for the same pass (ledger: +n and -n, day audit).
4. Unseen arrivals and real asymmetry: the census went 3 -> 10 at 16:08-16:50 with door tally +6 in / -12 out, and a 19:18 rise with zero door
   crossings (day audit §2a); 20 ambiguous crossings were never counted. People arriving by the garage or unseen cameras are plausible; I did not find evidence
   for or against that part. Residual unexplained: even after correcting my sample the totals stay net negative.

I did NOT establish a ground truth for whole-day in/out totals; only the labelled clips above.

## 4. Verdict

- **Is door vision counting well?** For one or two people, yes: 33/41 exact (80.5 %), no over-counts, always right when 1 person is in the clip (all misses
  are groups or clips with people at different times). For groups of three or more, no: it undercounts every one, by 1-5 people. Combined with 5 of 46 clips
  that return no count (4 errors, 1 false blank) and fall back to a camera peak that is itself wrong, door vision is NOT yet good enough to base census on groups.
  It is better than the Frigate peak on single-person garage clips (peak over-counts a lone person 3 times) and equal elsewhere.
- **Top failure: direction.** The count is acceptable; the direction attached to it is wrong in about a third of readable cases and the duplicate opposite-sign twin pass
  doubles it. Vision itself does not supply direction (`parse_vision_response` has no direction field, plan non-goal). Mechanism: direction comes only from interior-camera timing windows
  (`transit_validator.py:2408-2423`) and direction-keyed dedup refuses to merge an exit and an entry inside the window (`:2425-2438`); clustering in `crossing_vision.py:664-672` is direction-blind.
- **Fix, and cards.** (a) Direction: the evidence supports letting vision describe direction from the clip (first/last position vs the door) as a SECOND opinion on the
  same crossing; this is exactly VISION-AMBIGUOUS-CROSSINGS-1 (planned, tier 3, `kanban.data.yaml`; it also covers the 20 ambiguous crossings). It must also cover the labelled-wrong
  crossings, not only the ambiguous ones: the card as written targets the ambiguous ones, so the amendment should add "or disagrees with the tracker". The plan's non-goal "vision direction"
  would have to be lifted (`PLANNING_crossing_vision.md:489`). (b) Twin passes: collapse an opposite-direction pair inside the cluster window into one crossing before the ledger term
  (`crossing_vision.py:740-749`): no card exists for this, so a new card is needed. CENSUS-DECONFLICTION-LEDGER-1 (shipped_organic, tier 3) is the consumer of those terms and does not address direction labels; its F-LEAD gate (exact >= 95 %, vision wins
  >= 80 % of B/C disagreements) cannot pass until the group undercount is fixed. (c) Group undercount and false blank: more frames or a crowd-aware second pass for events whose camera peak >= 3, and event-centred frame selection;
  no card exists (new card). (d) Error cause: unknown; needs the llmvision error text recorded on the row (the row stores none).
  Marginal-benefit view: do (a) first (largest effect, already a card), (b) is a small change with a clear falsifier, (c) is worth a card only after (a) because direction errors dominate the net.

## Falsification and limits

- "Vision undercounts groups" would be disproved by any 3+ clip with vision >= my count: none among 18:43, 18:59, 21:24, 21:28.
- "Direction is wrong a third of the time" rests on 17 hand-read clips, not a random sample; wrong labels could be rarer on clips I could not judge. My counts are from a contact sheet of 8-12 frames,
  not frame-by-frame; the low-confidence ones are marked with `*`.
- I did not run any model call (read-only), so no fix is proven.
- Event ids confirmed live: all 46 clips returned HTTP 200 through `/api/frigate/notifications/<id>/clip.mp4`.

Files: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_door_vision_accuracy_2026_11_14.md`,
`/Users/okosisi/Code/universal-room-automation/.claude/tmp/visev_index.txt`, `visev_rows.json`, `visev_devs.json`, `visev_extract.py`, `visev_w1.py`, `visev_sheets.sh`, `visev_dense.sh`.
