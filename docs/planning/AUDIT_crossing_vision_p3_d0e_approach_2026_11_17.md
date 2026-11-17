# AUDIT: P3-D0e approach-clip probe, R-c leg (LLM montage), 2026-11-17

Run 2026-11-17 08:13-08:25 CST by ura-prober. Read-only. Plan: `PLANNING_crossing_vision.md:1247-1302`.
Scope: R-c only (the only tier that needs the call budget). R-a (Frigate stored records) and R-b (person detector) were NOT run here; the downloaded windows remain on disk for them until 2026-11-19.

## Method (as the plan states, with named deviations)
- Clips: the 276 windows downloaded by `.claude/tmp/appr_download.py` (HA Frigate proxy `/api/frigate/frigate-f2/recording/<cam>/start/<s>/end/<e>`, window [E-30, E+30]; results `.claude/tmp/appr_download_results.json`, 276 ok, 46 crossings). Camera sets frozen earlier in `quality/tests/fixtures/crossing_approach_camera_sets.json` (6 cameras per door group; inside camera = last entry: `foyer_fisheye` front, `staircase` garage_a).
- Montage (plan :1284): one sheet per clip, 2 frames per camera. Frames at E-12 s and E+12 s (the plan does not fix the offsets; chosen before any answer was read), each tile labelled OUTSIDE/INSIDE camera and BEFORE/AFTER. Built by `.claude/tmp/approachprobe_build.py`.
- Prompt (plan: ask only "first seen outside or inside, moving toward or away from the door"): see `approachprobe_run.py`; structured reply first_seen {outside, inside, both_at_once, nobody} x movement {toward_door, away_from_door, unclear}.
- Frozen mapping (set before scoring): outside + toward = `in`; inside + toward = `out`; anything else = unclear (abstain).
- Delivery deviation: llmvision `video_analyzer` needs a path HA can read. Each sheet was wrapped as a 3 s mp4 and served by a LAN-only HTTP server on the Mac (192.168.13.149:8765, serves only `approachsheet_<n>.mp4`, process ended with the run). Nothing was uploaded to HA or copied elsewhere; the model provider receives the frames as in every prior P3 call.
- Provider entry `01M7B731T26P2HXVW77AQR62PP` (`gpt-6-luna`) via `llmvision.video_analyzer` over the HA REST API. Calls log: `.claude/tmp/approachprobe_calls.jsonl` (33 lines).
- Constant: `CROSSING_DIRECTION_APPROACH_PROBE_CALLS` is NOT in `const.py` (grep of `custom_components`: 0 hits); it exists only in the plan (:1247, :1617 = 60, "46 primaries + 14 repeats"). Cap of 60 enforced in the runner from the plan.
- Truth: `quality/tests/fixtures/crossing_operator_grades.json`, 27 grades; 19 are in/out (scorable); 8 are both/no_cross (not direction-scorable, no calls spent on them). The 19 clips are 19 of the 46 downloaded crossings, matched by e_ts.

## Pass bar (plan, quoted)
:1293-1295: "the shares above on operator labels, deterministic (R-a, R-b; R-c reports repeat agreement against the P3-D6 stability bar), and errors not concentrated on V's misses." The shares are the P3-D0b gate (:682-684): "right on >= 15 of 17 AND >= 5 of 6 [tracker-wrong], deterministic, and deciding >= 0.50 of crossings on its OWN decisions". P3-D6 stability bar (:1054-1055): repeat-agreement Wilson 95% lower bound >= 0.80 over >= 20 repeats. The 17/6 denominators are the 11-14 set; on today's 19/9 set the same ratios are 88% and 83%.

## Per-clip result (n = clip index in `approachprobe_index.json`)
| n | group | truth | tracker | R-c primary (first_seen/movement) | R-c call | repeat |
|---|---|---|---|---|---|---|
| 0 | garage_a | in | in | outside/toward | in OK | same |
| 1 | garage_a | out | out | inside/toward | out OK | same |
| 2 | front | in | in | nobody | abstain | same |
| 3 | garage_a | in | out (T wrong) | nobody | abstain | not repeated |
| 4 | garage_a | in | out (T wrong) | inside/away | abstain | not repeated |
| 5 | front | in | in | outside/toward | in OK | same |
| 6 | front | in | out (T wrong) | nobody | abstain | not repeated |
| 7 | front | in | out (T wrong) | outside/toward | in OK | same |
| 8 | front | in | out (T wrong) | outside/toward | in OK | same |
| 9 | front | in | out (T wrong) | outside/toward | in OK | same |
| 10 | front | in | out (T wrong) | outside/toward | in OK | same |
| 11 | front | in | out (T wrong) | outside/toward | in OK | not repeated |
| 12 | front | in | in | outside/toward | in OK | same |
| 13 | front | in | out (T wrong) | outside/toward | in OK | same |
| 14 | front | in | in | outside/toward | in OK | not repeated |
| 15 | garage_a | out | out | inside/toward | out OK | same |
| 16 | front | in | in | outside/toward | in OK | same |
| 17 | garage_a | out | out | outside/toward | **in WRONG** | same |
| 18 | front | out | out | outside/toward | **in WRONG** | same |

## Scores (19 direction-scorable grades)
Counts: Decided clips = 0,1,5,7,8,9,10,11,12,13,14,15,16,17,18 = 15; right = 13, wrong = 2 (clips 17, 18); abstain = 4 (clips 2, 3, 4, 6). Corrected table:

| Measure | R-c |
|---|---|
| Decided | 15 of 19 = 79% coverage (gate 0.50 met) |
| Right on decided | 13 of 15 = 87% (bar 15/17 = 88%: 0.6 pt short; Wilson 95% about 0.62-0.96) |
| Right of all 19 | 13/19 = 68% (tracker 10/19, I4 17/19) |
| Right on the 9 tracker-wrong | 6 of 9 (clips 7,8,9,10,11,13); 3 abstain (3,4,6); 0 wrong. Bar 5 of 6 = 83% on decided: 6/6 on decided passes; 6/9 of all = 67% fails |
| `out` grades (n=4) | 2 right (1, 15), 2 wrong (17, 18): R-c reads every outside-first clip as `in` |
| Stability | 14 repeats, 14 agree (class-level); Wilson lower bound at n=14 about 0.78; P3-D6 bar needs >= 20 repeats, so not met by count |
| Independence | misses (17, 18) are tracker-RIGHT clips; R-c does not reproduce the tracker's entry-called-exit errors |

## Verdict: NO-GO for P3-D10 as a direction source (borderline), by the plan's literal bar
- Accuracy on decided 13/15 = 87% vs the 88% bar (also: 6/9 of tracker-wrong overall), and the whole-sample score 13/19 is below I4 (17/19) and below the "clearly better than tracker with coverage" intent; stability n=14 < 20 so the P3-D6 stability bar cannot be certified; tracker-wrong recovery on decided is 6/6 (passes) but 3 of the 9 were abstains.
- The two wrong calls are both `out` truths (a 4-clip sample): the montage cannot separate "first seen outside before E" (entry) from "seen outside after E" (exit) at fixed E-12/E+12 frames, because the model is asked for first sighting and the sheet shows outside cameras at both offsets. Hypothesis (not falsified live): per-camera frame ordering, not model ability, is the limit. Falsifier to run if revisited: add finer offsets (E-20, -8, +8, +20) on clips 17, 18 only.
- The 4 abstains are all "nobody": the person is small or absent in the two chosen frames (clip 2 viewed: person at the mat only in the E+12 aerial tile).

## What P3-D10 should do
1. Do not build P3-D10 on R-c as measured. Keep the plan's order: build R-a (0 calls) and R-b first; both are scorable offline from the downloaded windows, which expire 2026-11-19, so run them before then.
2. If R-c is revisited, it needs 4+ frames per camera with time labels and more `out` grades (4 here; the front group has 1) before any gate is meaningful.
3. R-c costs one call per crossing at runtime; at 87% on decided with `out` blind it adds nothing the tracker plus I4-style interior timing do not already cover.

## Calls and housekeeping
- Model calls spent: 33 of 60 (19 primaries + 14 repeats). 0 errors, all HTTP 200.
- Local artifacts in `.claude/tmp/` (gitignored): `approachsheet_*.jpg|mp4`, `approachprobe_*.py|json|jsonl`. No frames or clips were written anywhere else; no images are in this report.
- Not done: R-a, R-b, step 4 coverage on the 101 crossings and the P3-D2b share, step 5 per-clip overlap with V/C/I1 v2 beyond the tracker, the other 27 ungraded answer-key clips.

---
# Addendum 2026-11-17 (08:25-09:15 CST): R-a and R-b, same 19 grades, same bar

Model calls used by both routes: 0. Combined P3-D0e total stays 33 of 60. Scripts: `.claude/tmp/approachprobe_ra.py`, `approachprobe_rb.py` (outputs `approachprobe_ra_out.json`, `approachprobe_rb_out.json`). Order rule frozen as the plan (:1266-1268): first outside presence before first inside presence = in, reverse = out, within 3 s = unclear. Two reportings: LENIENT (a clip with presence on the outside cameras only counts `in`, inside only counts `out`) and STRICT (needs both sides, the plan's literal wording). The inside camera is the frozen one (`foyer_fisheye` / `staircase`).

Bias note: truth is 15 `in` / 4 `out`, so "always in" scores 15/19 on decided-all; the tracker's 10/19 is below it. Any lenient number near 13-15 is within that baseline and carries no direction information on its own.

## R-a Frigate stored person events (0 calls)
Source: Frigate `frigate/events/get` via the HA Frigate websocket (read-only, instance frigate-f2, 12 cameras, 351 person events over 11-14 12:00-20:00). Note: the HA proxy has no `/api/events` HTTP route (404); the websocket command is the proxy route. Presence = any event overlapping [E-30, E+30], start clipped to the window.
| | Lenient | Strict |
|---|---|---|
| Decided / 19 | 18 | 12 |
| Right on decided | 13 (72%) | 8 (67%) |
| Tracker-wrong clips right (of 9) | 5 right, 3 wrong, 1 abstain | 3 right, 3 wrong |
| `out` truths (4) | 3 right (1, 15, 17), 1 wrong (18) | 3 right |
Misses lenient: clips 3, 4, 5, 6 (read out, truth in: an inside event fired 16-30 s BEFORE the crossing, the same greeter/ambient-inside pattern that fools the tracker) and 18. Verdict: FAIL (13/18 vs 15/17; 5/8 vs 5/6). Its errors concentrate on the tracker's own misses (3, 4, 6), i.e. it copies the tracker's bias.

## R-b person detector on frames (0 calls)
Stock COCO YOLOX-s (opencv_zoo `object_detection_yolox_2022nov.onnx`, onnxruntime CPU), person conf >= 0.4, 2 fps, presence = 2 consecutive positive samples. Plan's door-strip displacement rule was NOT run (needs viewed-snapshot polygons per camera, frozen before labels); only the order rule. Frame differencing is the plan's weaker baseline (blurred abs-diff, 1% pixels changed).
| | YOLOX lenient | YOLOX strict | Frame-diff lenient | Frame-diff strict |
|---|---|---|---|---|
| Decided / 19 | 16 | 11 | 18 | 8 |
| Right on decided | 13 (81%) | 8 (73%) | 15 (83%) | 7 (88%) |
| Tracker-wrong right | 6 of 7 decided | 2 of 3 | 7 of 8 | 3 of 4 |
YOLOX lenient fails the 15/17 bar (13/16) and strict coverage is 11/19 = 58%. Frame differencing lenient reaches 15/18 only because it calls `in` whenever the outside cameras move, which equals the always-`in` baseline (15/19); its strict form decides only 8 of 19. Both fail the bar on honest terms. Determinism: both are deterministic by construction (same input, same output; not re-run twice).

## Updated P3-D10 verdict: NO-GO on all three tiers
| Tier | Right on decided | Coverage | Bar (15/17, 5/6, >= 0.50) |
|---|---|---|---|
| R-a | 13/18 lenient, 8/12 strict | 95% / 63% | fail |
| R-b YOLOX | 13/16 lenient, 8/11 strict | 84% / 58% | fail |
| R-b frame diff | 15/18 lenient (= always-in), 7/8 strict | 95% / 42% | fail (strict coverage < 0.50; lenient is the baseline) |
| R-c LLM montage | 13/15 | 79% | fail by 0.6 pt, stability n=14 |
None clears the bar. The order-of-presence signal is weak because the inside camera fires before the crossing on many entries (a person already inside, 16-30 s early), the same mechanism as the tracker's entry-called-exit errors, and the sample has only 4 `out` grades. Recommendation: P3-D10 stays unbuilt; direction work goes to the I4-style interior-timing variant (17/19) evaluated on production volume (P3-D6), not approach clips. Revisit approach clips only after the grade set has >= 15 `out` grades and a door-strip displacement rule (R-b step with frozen polygons) can be scored; the clips themselves expire 2026-11-19 and will need re-download from retained recordings if so.
Not done: door-strip displacement rule, step 4 coverage on 101 crossings and P3-D2b share, independence vs V/C/I1 v2.
