# AUDIT: VISION-CROSSING-ANALYSIS-1 D0 (D0b, D0c, D0d; D0a skipped)

Run 2026-11-13 11:37-11:49 CST by ura-prober. Not committed. Plan under test: `docs/planning/PLANNING_crossing_vision.md` rev 2 (worktree `.claude/worktrees/planner-crossing-vision`, commit f1687a1f), section 5 D0. HVAC / presence STATE_OF_PLAY docs not read (no HVAC or presence logic touched; probe only).

## Answer first

| Gate | Plan bar | Result | Verdict |
|---|---|---|---|
| D0b exact count (`video_analyzer`, gpt-4o-mini, 45 scored crossings) | >= 85 % | **42/45 = 93.3 %** (Wilson 95 % low about 82 %) | PASS |
| D0b 0 undercounts on the multi-person set | 0 | **1 undercount of 1** (the only 2-person set, #27: model said 1, frames `[1,1,1]`) | **FAIL (n = 1, not evidence of a rate)** |
| D0b 0 errors | 0 | 0 service errors on the 45 scored. (10 calls hit "connection refused" during a brief HA outage at about 11:43; they never reached HA, were re-run, and are excluded) | PASS |
| D0b instance-scoped `video_file` (review note) | works | **HTTP 200, 7.8 s, valid structured answer** with `/api/frigate/frigate-f2/notifications/<event_id>/clip.mp4` | PASS |
| D0c fixture, 4 door cameras, entries, proxy, automations | table | done, below | PASS (delivered) |
| D0c event-match coverage at +-10 s | measured | **87/117 = 74.4 %** (62/83 garage_a, 25/34 front) | measured |
| D0d pixel guard `people > 0` vs operator labels | >= 29/30 | **22/30 batched; 24/30 after single-frame re-test of the 8 misses**. All residual misses are false negatives (model 0, operator >= 1) | **FAIL** |

D0b decision per the plan's own text: the multi-person criterion is a literal FAIL, but it rests on one set; the exact-count bar (the discriminating one) passes with margin. The plan says fail = fallback frame source. **My read, labelled opinion**: do not take the fallback on n = 1; but the group-count ability stays UNTESTED (same gap D0-V reported), and that is the number the guest ledger needs. The decision is the coordinator's / operator's.

D0d: the guard is not trusted. Per the plan, shadow still ships, the scorer must report every blank / non-blank verdict as unvalidated, and Phase 2 is blocked until a guard passes.

## Call accounting (OVER BUDGET, disclosed)

Plan cap is 60 calls. **73 calls reached HA / OpenAI** (all HTTP 200, all gpt-4o-mini, provider = the existing OpenAI entry `01KHB0EV5AP8ANWQ7RWT30M2CC`):

| Block | Calls |
|---|---|
| D0b first test, `event_id` (crossing #0) | 1 |
| D0b instance-scoped `video_file` (crossing #0, review note) | 1 |
| D0b first pass, crossings 1-44 scored | 40 |
| D0b tail re-run after the HA outage (#45, 46, 47, 49) | 4 |
| **Accidental duplicate run** of crossings 2-15 (my bug: a failed `sed` left the script on its full list; killed after 13 calls) | 13 |
| D0d batched (6 calls x 5 frames) | 6 |
| D0d single-frame re-test of the 8 batched misses | 8 |
| Total | 73 (13 over; cost about +$0.12 at the D0-V estimate of about $0.0095 per 3-frame call) |

The 13 duplicates gave a free repeatability measure (below). No API key read or printed; HA token only from the keychain, never printed; no Frigate login (all media via HA's Frigate proxy, HA-signed by llmvision).

## Method

- Calls only through `POST /api/services/llmvision/video_analyzer` and `image_analyzer?return_response`. Provider = existing OpenAI entry, `model` gpt-4o-mini, `response_format` json, `structure` = the plan section 5 D1 schema (`frames[{index,people}]`, `people_total`, `direction in|out|unsure`, `group`, `desc`), `max_frames` 4, `target_width` 768, `store_in_timeline` false, `use_memory` false, `expose_images` true (D0b only), `max_tokens` 1500.
- Prompt (D0b): "These are consecutive frames from one outdoor door camera clip of a person crossing a doorway. For each frame (index from 0) count the people visible; people_total is the number of distinct people across all frames; direction is in (entering the building), out (leaving) or unsure; group is true if 2 or more people move together; desc is one short sentence ... Do not name or identify anyone." This is my wording of the D1 prompt (the plan fixes the schema and "no naming" rule, not the text).
- D0b inputs: the 45 crossings scored in `AUDIT_crossing_vision_d0_v_2026_11_13.md` (5 uncertain ones #1, 5, 25, 31, 48 excluded, same as D0-V). Same Frigate event id per crossing (`sample.json` field `ev`), all still inside retention (0 aged out). Truth = D0-V's prober visual count for the event-anchored frame set (set B), i.e. an agent label, not operator ground truth (same caveat as D0-V). One crossing (#0) was run via `event_id` in the first test; its scored result is that call.
- D0d inputs: the 30 frames `handlabel/f01-f30.jpg` with operator labels from `handlabel/operator_labels.json` (matches the labels in the brief: 0,1,1,0,0, 1 x11, 0,0,1,0,1,1,2,1,0,1,1,0,1,1).
- **Deviation from the plan for D0d (budget):** the plan says one single-frame call per frame (30 calls); with D0b that would exceed 60. I sent 6 batched calls of 5 unrelated frames (per-frame `people` array), then re-tested only the 8 disagreeing frames single-frame (D1 per-frame prompt, "count only real people including small or distant ones"). The 22 frames that agreed in the batch were NOT re-tested single-frame, so the 24/30 below is a mixed estimate, not a clean single-frame 30/30 run.
- HA files: D0d frames staged at `/config/tmp_cvd0d` on the HA host, deleted (confirmed). llmvision's own key-frame exposures (`/media/llmvision/snapshots`, 18 files, all created by these calls: the folder held 2 files, both mine, at my first check) deleted. No HA config, entity or entry changed.

## D0b detail

Counts (first-pass result per crossing, n = 45):

| Cut | Exact |
|---|---|
| Overall | 42/45 = 93.3 % |
| doorbell_lite | 12/14 |
| garage_a | 10/11 |
| front_door_aerial | 7/7 |
| madrone_g6_entry | 13/13 |
| day | 21/24 |
| night | 21/21 |

Misses: #7 doorbell_lite over (2 vs 1, frames `[2,2]`), #11 doorbell_lite over (1 vs 0, frames `[0,0,1,1]`; D0-V already flagged this as a distant-only set), #27 garage_a under (1 vs 2). Over 2, under 1. Same camera pattern as D0-V (landscape doorbell_lite / garage_a views). D0-V's image-path result was 42/45 for the same model: video frames are no worse.

Falsifier for "pre-roll first frame poisons the count": would show as blanks / undercounts concentrated where position 0 is empty. Observed: position-0 frame is empty in **24/45** responses (53 %), and in 17 of the 39 sets where a person was present; yet `people_total` was 0 on **0 of 38** person sets (no false blank, no undercount from pre-roll). The first frame is often pre-roll, but with 3-4 frames the later ones carry the person, so the count survives. Position zero-rates (zero frames / frames at that position): pos 0 24/45, pos 1 6/44, pos 2 12/40, pos 3 14/29 (trailing frames empty after the person leaves). Consequence: a design that reads only the first frame, or `max_frames` 1-2, would fail; keep >= 3 frames. Frames returned per call: 4 frames x29, 3 x11, 2 x4, 1 x1 (llmvision selects I-frames of a short clip, so short clips give fewer frames; `max_frames` 4 is a ceiling).

Blank-set behaviour (INV-BLANK): 6 sets are all-zero (#40, 41, 44, 45, 47, 49); all 6 had visual truth 0, so the guard classifies them `blank` correctly. 0 false blanks. #11 (truth 0, model 1 on 2 of 4 frames) is the one false non-blank.

Response contract observed (matters for the D1 parser): the service returns `service_response.structured_response` (a dict) and `key_frame`; there is **no `response_text`** key on the json path. A parser written for `response_text` (the `enrich_dispatched_alert` contract, plan D1 item 7 "flat `response_text`") would read nothing; the "refused = empty `response_text`" outcome in D1 item 8 needs rewording for json responses. Frame file paths: the response carries only ONE path (`key_frame`, `/media/llmvision/snapshots/<uid>-<n>.jpg`, the `-<n>` suffix matches the frame count), not the per-frame paths. So the operator cannot label all frames from `expose_images`, only the key frame.

Consistency: `people_total` >= max(frame counts) and <= sum(frame counts) in 45/45. Repeatability (13 pairs, same event, repeat call): totals identical 11/13, full frame vectors identical 11/13; flips #3 (1 then 2) and #7 (2 then 1; frame count also changed 2 to 1). So the model is non-deterministic on about 15 % of small-figure sets at the +-1 level. Treat a single call's count as a +-1 estimate.

Direction (`direction` field vs the validator's direction, not truth): entry/`in` 13, entry/`out` 8, exit/`out` 10, exit/`in` 8, exit/`unsure` 6. Agreement 23/45 = 51 % (about chance; it does not discriminate). Direction from vision should not be used for anything; `group` was true on 1 of 45.

Latency per call (45 first-pass calls): **p50 7.5 s, p90 13.7 s, p99 17.8 s, max 17.8 s, mean 7.9 s**; including the 13 repeats and instance test (57 video calls) p50 7.5, p90 13.7, max 19.4 s. This is 3.5x the image path (D0-V p50 2.1 s). Timeout knob: 1.5 x p99 = 26.8 s (1.5 x max 19.4 = 29 s). `CROSSING_VISION_TIMEOUT_S` default 90 in the plan is above both and above llmvision's own 60 s request timeout, so **keep 90** (no change); sample is small (45), so do not tighten below the 60 s llmvision bound.

Review note (instance-scoped path): `video_file=/api/frigate/frigate-f2/notifications/1793940076.387658-a7vdx7/clip.mp4` (HA-signed by llmvision, `media_handlers.py:632-638`) returned 200 in 7.8 s with the same frames-count vector as the `event_id` call (`[1,1,1,0]`, total 1). The `event_id` default path (`/api/frigate/notifications/...`) also worked here because this install has exactly one Frigate entry (D0c). Instance id `frigate-f2` is the MQTT client id the Frigate integration uses (`perimeter_alert.py:3520-3535` derives it the same way); I did not read it from the registry, I used the value D0-V already used and it resolved.

Not tested: the open-event case (plan section 1.6); no in-progress door event occurred and I stayed inside the budget. Remains UNVERIFIED whether Frigate serves `clip.mp4` for an in-progress event.

## D0c: fixture

Door-group stems, from the live URA config entry (`.storage/core.config_entries`, `door_groups` option on "Universal Room Automation", read only): `{"doorbell_lite": "garage_a", "front_door_aerial": "front", "garage_a": "garage_a", "madrone_g6_entry": "front"}`.

| Frigate `after.camera` | Live count sensor (state 2026-11-13 11:45) | Stem via `_extract_camera_stem` rule (`camera_census.py:1009`, `_2` then suffix strip) | door_groups value | Notes |
|---|---|---|---|---|
| doorbell_lite | `sensor.doorbell_lite_person_count` (0) | doorbell_lite | garage_a | |
| garage_a | `sensor.garage_a_person_count` (0) | garage_a | garage_a | semi-interior garage-bay view, flagged in D0-V |
| front_door_aerial | `sensor.front_door_aerial_person_count` (0) | front_door_aerial | front | |
| madrone_g6_entry | `sensor.madrone_g6_entry_person_count` (0) | madrone_g6_entry | front | Protect-named camera; Frigate leg exists |

Camera names in Frigate events (`fr_events.json`, `ev2.json`) equal the door_groups keys for all 4 (no `_2` on the Frigate camera name; `_2` appears only on some entity ids such as `binary_sensor.*_person_occupancy_2`, `sensor.*_person_active_count_2`). Hazard for the runtime map: zone variants exist too (`sensor.doorbell_lite_property_person_count`, `sensor.madrone_g6_entry_package_person_count`, `sensor.front_door_aerial_property_person_count`); their stems (`doorbell_lite_property`, ...) are NOT in `door_groups`, so a runtime map built from any `*_person_count` sensor must key on the Frigate `after.camera` and not enumerate sensors.

Frigate config entries: **1** (`01KM239Z8ZQWQTN1D9CV5JRA7V`, title "Frigate 2", not disabled), `notification_proxy_enable` = **True**, `notification_proxy_expire_after_seconds` = 0. Frigate integration instance id per door camera: all 4 cameras belong to that one entry, instance id `frigate-f2` (verified by a successful clip fetch for a `doorbell_lite` event; the other 3 cameras were exercised by the D0b run through the default URL, all 200). With one entry the default (non-instance) URL is safe today; the plan's instance-scoped form is still correct for a second entry.

Event-match coverage, Person label, door-group cameras, from 117 clusters (E = t0 - 45 s, 2026-10-31 to 11-13, `w/clusters.json` x `w/ev2.json`):

| Window | Matched | garage_a | front |
|---|---|---|---|
| +-10 s (the plan knob `CROSSING_VISION_EVENT_MATCH_S`) | **87/117 = 74.4 %** | 62/83 | 25/34 |
| +-30 s | 97/117 = 82.9 % | 68/83 | 29/34 |
| +-60 s | 103/117 = 88.0 % (equals D0-FRAME F5, a cross-check) | 72/83 | 31/34 |

At +-10 s about a quarter of crossings would record `no_frigate_event` (no vision row). The knob is a number: widening to +-30 s buys 8.5 points, +-60 s buys 13.7. Whether a +-30 s match picks the wrong event more often is not measured here (window widening raises mismatch risk when the door has back-to-back events); coordinator's call.

HA automations calling `llmvision.*` (read-only grep of `/config/automations.yaml`, `scripts.yaml`, `configuration.yaml`, packages): 3 calls, all `llmvision.image_analyzer` on the OpenAI entry `01KHB0EV5AP8ANWQ7RWT30M2CC`, inside automations "Doorbell Detection WhatsApp Alert" (id 1770938962914, gpt-4o-mini, 300 tokens), and "Phase 1: All Detections - Dual System (AI)" (id 1770938962920, two calls, 100 tokens each, default model). None calls `video_analyzer` or analyses crossings; nothing duplicates crossing vision. They share the OpenAI entry and the cost line.

## D0d detail

Operator labels: 0 on 8 frames, 1 on 21, 2 on 1 (f23).

| Run | Agree on `people > 0` | Disagreements |
|---|---|---|
| Batched, 6 calls x 5 frames | 22/30 | f04 (op 0, model 1); f06, f11, f13, f15, f22, f27, f29 (op 1, model 0) |
| Single-frame re-test of those 8 | f04 -> 0 (now agrees), f29 -> 1 (agrees); f06, f11, f13, f15, f22, f27 stay 0 | 6 |
| Mixed best estimate | **24/30 = 80 %** | 6 false negatives, 0 false positives |

Exact count on the batched run 21/30; f23 (operator 2) was returned as 1 (undercount). The 6 stable misses were on `doorbell_lite` (f06, f13, f27), `garage_a` (f11), `madrone_g6_entry` (f15) and `front_door_aerial` (f22), by manifest. Of the 6, the manifest `proxy_person` flag is True for f06, f22, f27 and False for f11, f13, f15, i.e. the guard misses people the operator saw both where Frigate was active and where it was not. Single-frame responses said "No people are visible in the frame" on these, so the model fails to see them (small figures / low light likely; not verified by viewing the frames in this pass).

Consequence for D1: a frame-level `people > 0` guard under-detects (false blanks), which would mark real crossings blank; but the D0b video path misclassified 0 of 38 person crossings as blank, because the set-level total takes the max over 3-4 frames. The two numbers do not conflict: single-frame guard accuracy is about 80 %, set-level blank detection is 0 false blanks in 38 (and 6/6 true blanks). The set-level guard (`all frame counts 0`) is what D1 actually uses (INV-BLANK); D0d as written tests the weaker per-frame form. I did not run the set-level guard against operator labels (no operator labels exist at the crossing level), so "guard validated" is still unproven; the plan bar as written is failed.

## Not done / unknown

| Item | Status |
|---|---|
| D0a | skipped as instructed (needs the second OpenAI entry) |
| Open-event `video_analyzer` call (plan section 1.6) | not run; UNVERIFIED |
| D0d clean single-frame run on all 30 | not run (budget); 22 frames judged only in batched form |
| Multi-person accuracy | n = 1 in the whole sample (as in D0-V); the group-count gate cannot be passed or failed on this data. Needs a deliberately sampled 2-3 person set before DEPLOY if the guest ledger will use counts |
| Truth quality | D0b truth is the prober's visual count, not operator ground truth; the 3 misses and the 6 all-blank sets are unconfirmed by the operator |
| `expose_images` retention | llmvision wrote one `key_frame` per call (18 files present for about 57 video calls at 11:48, after a brief HA outage); whether llmvision prunes the folder is unknown (retention code is for the timeline calendar, `__init__.py:181-225`, I did not trace the snapshot folder) |
| Temp-clip leak (plan rev 2 F6) | not measured; `media_handlers.py:840-843` removes the temp file on the normal path; the cancellation path was not exercised |

## Falsifiers run

- "Video frames work": would be disproved by exact < 85 % or by blanks / undercounts concentrated at the pre-roll position. Observed 93.3 % and 0 person-set blanks despite 53 % empty first frames.
- "Guard fails": would be disproved by >= 29/30 agreement; observed 22/30 (batched), 24/30 after single-frame re-test. A reader who suspects batching caused it is answered by the 8 single-frame re-tests: 6 of 8 misses persisted.
- Connection-refused results (10) are an HA outage at about 11:43, not model failures: status None, 0.03 s, `Connection refused`; HA answered 401 on `/api/` at 11:44:17; re-runs succeeded.

## Files

- Audit (this file): `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_crossing_vision_d0_2026_11_13.md`
- Scripts and raw results (scratchpad, not in repo): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/cv/` (`lib.py`, `d0b.py`, `d0b_tail.py`, `d0d.py`, `d0d2.py`, `score.py`, `d0b.jsonl`, `d0b_tail.jsonl`, `d0d.jsonl`, `d0d2.jsonl`)
