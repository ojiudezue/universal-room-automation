# AUDIT: VISION-CROSSING-ANALYSIS-1 D0-V (vision model scoring, fast pass)

Run 2026-11-13 02:35-02:49 CST. Operator-approved. Not committed. Read first: `PLANNING_person_sighting_layer.md` rev 12 section 15.1, 15.4, 15.9; `AUDIT_vision_d0_frame_sim_2026_11_13.md`; `AUDIT_egress_history_labels_2026_11_13.md`. HVAC and presence STATE_OF_PLAY docs were not read (no HVAC change; presence used only as a label source).

## Answer first

1. **gpt-6-luna and gpt-6.1-sol are NOT usable through llmvision 1.7.1 today.** The dry call to each returned HTTP 400: `Unsupported value: 'temperature' does not support 0.5 with this model. Only the default (1) value is supported.` llmvision sends the OpenAI entry's temperature 0.5 / top_p 0.9 for every model except the exact names gpt-5, gpt-5-mini, gpt-5-nano (`providers.py:706-709`); `image_analyzer` has no per-call temperature field (`services.yaml` fields; `ServiceCallData` sets `self.temperature = float()` and ignores input, `__init__.py:~478`). Per-call model selection WORKS (the `model` field reached OpenAI). Fixes are outside this probe: change the entry's temperature (a config write, not allowed here), or an llmvision patch to omit temperature for gpt-6*. **Luna/Sol accuracy: not measured.**
2. **Accepted models, run on 50 crossings, 3 frames at 768 px, 0 errors, 0 refusals, 0 unparseable:** llmvision default `gpt-5-mini` and `gpt-4o-mini` (URA's pinned perimeter model; my addition as a plan-section-15.4 baseline). With frames anchored to the event start (set B, see 3): exact people-count vs my visual count **gpt-4o-mini 42/45 = 93 %, gpt-5-mini 39/45 = 87 %**. Both found a person on 38/38 person frames. Neither ever undercounted; every miss is an over-count (4o-mini 3, 5-mini 6), mostly tiny distant figures on the doorbell_lite view that my labels may have discounted.
3. **The frame offset rule in 15.9.3 is wrong as read, and that matters more than the model.** Clip frames at clip time 0/1/2 s (the obvious reading of "offsets from event start") sit BEFORE the event: OCR of the burned-in timestamp gives the Frigate `clip.mp4` start as 0 to 7.0 s before the event start (37 clips OCR-readable, median 2.4 s). By eye, **16/50 (32 %) of those frame sets contain no person; with the offset corrected, 7/50 (14 %)** (plus 5 uncertain either way). Offsets must be taken from the event start AFTER subtracting the clip pre-roll (or use the snapshot/thumbnail endpoints). This is the real-frame check on D0-FRAME's 100 % proxy claim: not borne out for clip-extracted frames.
4. **Go/no-go:** **GO (conditional) on the fast-pass count with an accepted model, NO-GO on gpt-6-luna/sol until the temperature blocker is fixed (a config or llmvision change, then re-run those two dry calls).** Conditions: (a) frame offsets fixed per 3; (b) the blank-frame guard is mandatory (about 14 % of correctly anchored sets still have no person; a model fed a blank set mostly says 0, but `gpt-5-mini` said 2 on one empty set); (c) the operator 30-frame hand-label (15.9.7) is still required before the count is trusted. Not done and not claimed: resident-like vs unknown, name consistency, descriptions quality grading, batch stage, ledger return to zero, measured token usage (see Not done).

## Method

| Item | Value |
|---|---|
| Pool | 117 garage-A and front crossing clusters 2026-10-31 to 11-13 (`w/clusters.json` from the prior audit), direction from `person_entry_exit_events` rows, t0 = last emit, E = t0 - 45 s |
| Sample (50) | Group L (40) = clusters with a resident label within +-120 s: tracker `person.*` state edge (12, recorder, 11-05 on), else Frigate face sub_label on the door cameras within E-10..E+90, else URA `person_id`. Group N (10) = clusters with none of those. Only 12 clusters in the whole window have a tracker edge within +-120 s (trackers lag arrivals by 4-13 min per the labels audit), so L is mostly face/URA-labelled; stated deviation from "40 with a tracker edge" |
| Strata | door x direction x day/night: L = garage A entry 18 (9 day, 9 night), garage A exit 11 (6 day, 5 night), front exit 7 (5 day, 2 night), front entry 4 (3 day, 1 night); N = front only (front exit 8, front entry 2); no unlabelled garage-A crossing existed with media. Residents in labels: Jaya 20, Ezinne 18, Oji 14, Ziri 4, Ojini 2 (names counted per crossing) |
| Cameras | doorbell_lite 17, madrone_g6_entry 13, garage_a 12, front_door_aerial 8. `garage_a` shows the garage bay from above (it is in the live `door_groups`, so inside the brief, but it is a semi-interior view; flag for the operator) |
| Frame source | Frigate event chosen by: has clip, nearest start to E within +-10 s. Frames extracted with ffmpeg from the event clip (`frame_source = clip` for all 150). Snapshot 200 on 49/50 events, thumbnail 200 on 50/50 (fetched, not sent). 768 px wide, JPEG q3, 3 frames |
| Path | HA REST `POST /api/services/llmvision/image_analyzer?return_response` with the existing OpenAI provider entry id, `image_file` = 3 paths, `target_width` 768, `max_tokens` 1500, `store_in_timeline` false, `expose_images` false. No API key was read, printed or copied (I only listed entry ids/titles with the key redacted). Frigate media came through HA's proxy `/api/frigate/frigate-f2/...` with the HA token; no Frigate login. Frames sat in `/config/tmp_d0v*` on the HA host (llmvision reads local paths) and were deleted afterwards |
| Prompt | "3 consecutive frames ... outdoor door camera ... How many distinct people are visible in total? Reply: COUNT: <int> then DESC: <one short sentence ... do not name or identify anyone>" |
| Truth | (1) **prober visual count**: I viewed every 3-frame set and counted people (5 marked uncertain and excluded). This is a human-style label by an agent, not operator ground truth, and can be wrong on tiny figures. (2) resident labels (tracker/face/URA) are a lower bound on people, not a count. (3) URA `peak_person_count` is camera-derived, not independent |
| Calls | 153 total (limit 200): 4 dry (default, luna 400, sol 400, 4o-mini) counted inside 3 below, set A gpt-5-mini 50, set B gpt-5-mini 50, set B gpt-4o-mini 50 |

Frame sets: **A** = clip offsets 0/1/2 s (naive). **B** = event-anchored: clip offset = OCR pre-roll + (0,1,2) s (default 2.0 s where OCR failed, 13 of 50).

## Per-model table

| Model | Accepted by llmvision | Calls | Errors / refusals / unparsed | Latency p50 / p90 / max (s) | Exact count vs visual (set B) | Over / under | Person sets with count >= 1 | Blank sets answered 0 | Count >= resident-label count (L, n=40) | Equals URA peak (n=50) |
|---|---|---|---|---|---|---|---|---|---|---|
| llmvision default = gpt-5-mini, set A (naive offsets) | yes | 50 | 0 / 0 / 0 | 4.4 / 6.4 / 14.0 | 37/46 = 80 % | 9 / 0 | 30/30 | 11/16 | 27/40 | 23/50 |
| gpt-5-mini, set B | yes | 50 | 0 / 0 / 0 | 4.0 / 5.8 / 8.5 | 39/45 = 87 % | 6 / 0 | 38/38 | 6/7 | 29/40 | 25/50 |
| gpt-4o-mini, set B | yes | 50 | 0 / 0 / 0 | 2.1 / 2.7 / 3.4 | 42/45 = 93 % | 3 / 0 | 38/38 | 7/7 | 28/40 | 28/50 |
| gpt-6-luna | NO: 400 temperature | 1 dry | 1 error | 0.9 | not measured | n/a | n/a | n/a | n/a | n/a |
| gpt-6.1-sol | NO: 400 temperature | 1 dry | 1 error | 0.6 | not measured | n/a | n/a | n/a | n/a | n/a |

Splits (set B exact / scored): gpt-4o-mini: front 20/20, garage_a group 22/25; entry 18/21, exit 24/24; day 21/24, night 21/21; group N (no resident label) 9/9. gpt-5-mini: front 20/20, garage_a group 19/25; entry 16/21, exit 23/24; day 18/24, night 21/21. Every miss is on the `doorbell_lite` / `garage_a` landscape views, where the person is a small figure at the car; per camera gpt-4o-mini doorbell_lite 11/14, gpt-5-mini 9/14. Small n: 45 scored, Wilson 95 % low bounds are about 82 % (4o-mini) and 74 % (5-mini), so the two models are not statistically separable; "4o-mini is better" is not shown.

Multi-person: only 1 of the scored sets has 2 people by my count (#27, both models exact); a 3 or 4 person case never occurred. **The group-count ability that matters for the guest ledger is effectively untested.** Directions: counts say nothing about direction; not scored.

Resident-label comparison is weak by construction: a name list is a lower bound (e.g. 3 face names at one crossing = 1 person). On the 12 crossings with a tracker edge, the model saw at least one person on 12/12 (gpt-5-mini) and 11/12 (gpt-4o-mini). The "false resident-like on the 10 non-resident crossings" test was NOT run (the prompt forbids identity by design; that needs the section 15.3 schema and a different pass).

## Frame-offset finding (affects D0-FRAME, which this overturns in part)

| Check | Result |
|---|---|
| Clip start vs Frigate event start, OCR of burned-in timestamp (37/50 readable) | pre-roll min 0, median 2.4, max 7.0 s |
| Prober visual, 3 frames at clip 0/1/2 s (set A) | 16/50 no person |
| Prober visual, 3 frames at event start + (0,1,2) (set B) | 7/50 no person, 5 uncertain |
| Blank sets in B are all front exits / empty porch with the Halloween bowl (#40,41,44,45), #47, #49 and a distant-only #11 | the Frigate event fired, the person had left or was never framed |
| Model on A vs B (same crossings, gpt-5-mini) | exact 80 % -> 87 %; blank-correct 11/16 -> 6/7 |

D0-FRAME's proxy (sensor/event ON) predicted 100 % of event-anchored sets have a person; the eye says 86 % (43/50 incl. uncertain as non-blank is at most 43/50, at least 38/50). The 30-frame hand label (15.9.7) is therefore likely to FAIL at the 95 % bar for front exits; frames are in `handlabel/` below.

## Cost estimate (measured tokens NOT available)

llmvision does not return usage, and the brief forbids reading the key, so I could not send the direct-API probe that section 15.4 asks for. Estimates from OpenAI's published rules and prices (pages fetched 2026-11-13: https://developers.openai.com/api/docs/guides/images-vision and https://developers.openai.com/api/docs/pricing):

| Model | Image-token rule used | Per frame | Per 3-frame call (input) | Price in / out per 1M | Est. per call | Est. per day at 14.1 calls (cost envelope per 15.9.5) |
|---|---|---|---|---|---|---|
| gpt-4o-mini | tile rule: base 2833 + 5667 per 512 px tile, detail auto | portrait 768x1024 = 4 tiles = 25,501; landscape 768x432 = 2 tiles = 14,167 | 62,900 mean over this sample (30 portrait, 20 landscape) | $0.15 / $0.60 | about $0.0095 (output about 40 tokens negligible) | about $0.13 |
| gpt-5-mini | patch rule, 32 px patches x 1.2 multiplier (page lists 1.2 for gpt-5-mini but marks it deprecated and not in the sizing table, so assumed) | portrait 768 patches = 922; landscape 336 = 403 | about 2,150 image + about 250 text/system | $0.25 / $2.00 | about $0.0006 input + unknown reasoning output; 300-1,500 output tokens assumed = $0.0006-0.003, total about $0.001-0.004 | about $0.02-0.05 |
| gpt-6-luna (blocked) | patch x 1.2 assumed from gpt-6-astra (only astra is in the page's table) | same as above | about 2,400 | $0.10 / $0.50 | about $0.0003 + output | under $0.01 |
| gpt-6.1-sol (blocked) | same assumption | same | about 2,400 | $2.00 / $10.00 | about $0.005 + output | about $0.07-0.15 |

Surprise: gpt-4o-mini is the most expensive per call on images (tile rule) although cheapest by headline price; at this volume it is still pennies a day. Latency observed: gpt-5-mini 4.0 s p50 is not slower than expected; its long call figures early in the session were my frame extraction, not the API.

## Not done (accounted)

| Item | Why |
|---|---|
| gpt-6-luna / gpt-6.1-sol fast pass | blocked by the temperature 400 above; only a config/llmvision change fixes it |
| Measured tokens / direct API probe | needs the API key; forbidden |
| Frame source comparison (snapshot vs thumbnail vs clip) | only clip frames were sent; snapshot/thumbnail availability was checked, not scored. A single best snapshot also cannot supply 3 frames |
| Description quality labelling (20 summaries) | needs operator; summaries are in the raw results (`res_*.jsonl`, scratchpad `v/`) |
| Resident-like vs unknown, matches_named_person, same-person pairs, false resident-like on N | prompt had no identity task by design |
| Batch (B) stage, provisional-vs-final, guest-ledger return to zero, deconfliction cases, Frigate/Protect count agreement beyond URA peak | out of the brief (fast pass only) |
| Entry/exit direction vs count by direction, group size 3+ | no group of 3+ in sample |

## Falsifiers

- "Frames before the event" would be disproved if OCR pre-roll were about 0: it is 0-7 s (median 2.4 s), and set A frames show visibly empty scenes where set B shows the person.
- "gpt-6 is blocked by temperature" would be disproved by a successful call: both returned the same 400 text within 1 s; gpt-5-mini and gpt-4o-mini on the identical payload path succeeded.
- "Over-counts are model errors" is NOT established: my visual labels discount tiny figures on doorbell_lite and may be the wrong side (model said 2 where I said faint 1 on #1, #5 uncertain). Operator ground truth on those 6 sets would settle it.

## Housekeeping

- Extra deliverable (coordinator, 30 frames for the operator hand-label, 15 garage-A group + 15 front group, 20 proxy-ON / 10 proxy-OFF, filenames neutral) written to `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/handlabel/` (`f01.jpg`..`f30.jpg`, `manifest.json`). Proxy = a door-group Frigate person event active at the frame time (computed from the event list, not from boxes). Garage-A group includes doorbell_lite; the `garage_a` camera frames are garage-bay views.
- Scratch on HA `/config/tmp_d0v`, `/config/tmp_d0v_b` created and deleted. No config, entity or entry changed; llmvision `store_in_timeline` and `expose_images` false. OpenAI received 150 successful door-camera frame sets (3 frames x 50, 3 passes counts above: 50 + 50 + 50 calls) and 3 rejected calls; no interior frames beyond the garage_a bay view.
- Scripts and raw results: `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/v/` (`sample.json`, `res_*.jsonl`, `score.py`, `pick.py`, `frames.py`, `framesB.py`, `run.py`).
