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
