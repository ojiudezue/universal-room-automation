# AUDIT: door direction + count instruments scored once on the 27 operator grades (2026-11-17)

Run Tue 2026-11-17 08:0x-08:1x CST (system clock `CST`; brief said CDT) by the read-only prober, repo HEAD 056c69993 (v5.108.34 manifest).
Arc map row 6 (`ARC_identity_vision_census_map.md:156`). Read first, completely: `AUDIT_crossing_vision_p3_d0bcd_2026_11_15.md`, the P3 sections of
`PLANNING_crossing_vision.md` (P3-D2 :735, P3-D3 :792, P3-D6 :1032, P3-D0b :649, P3-D0e :1247, P3-D0f :1354, P3-D10/D11 :1304/:1376), manual §5.5 (door crossings are F3: a crossing is not a sighting; direction/count are F3 attributes, not F1/F2/F4/F5 facts). Presence / HVAC state-of-play not needed (no presence or HVAC logic read or changed).
State changes: none. No model calls. No Frigate/Protect login; no footage touched or copied.

## Where the 27 grades live
`quality/tests/fixtures/crossing_operator_grades.json` (27 rows, `kind=crossing`, batch g20261115-1716, graded 2026-11-16 03:38-05:18 UTC), written by `scripts/grading/pull_grades.py` from the urakanban `/grade/` queue. Backups: `.claude/tmp/grades.backup-20261115.jsonl` (6 rows), `grades_backup_pre_interior_20261116.jsonl` (30 rows, 3 are interior-desc). All 27 keys match fixture events of `crossing_vision_door_eval_2026_11_14.json`. Scripts: `.claude/tmp/doorscore_db.py` (remote DB read), `doorscore_join.py`, `doorscore_stats.py`, joined data `doorscore_joined.json` (local only).

Sample shape (this limits everything below): 27 crossings, all 2026-11-14 12:59-18:52 CST (the first 27 of the 46-clip answer key, chronological, not random). Operator direction: **in 15, out 4, both (round trip) 3, no_cross 5**. By door: front 15 rows (in 12, out 1, both 2), garage_a 12 rows (in 3, out 3, both 1, no_cross 5). Direction-scorable (in/out only): 19 = front 13, garage_a 6. **A classifier that always says `in` is right on 15/19 (79 %, Wilson 95 % 0.57-0.91).** All 5 `no_cross` are garage_a. Overlap with the agent-made labels: 7 of the 27 had an agent direction; 6 agree, 1 disagrees (17:59:51: agent `out`, operator `in`, so the old "tracker-wrong" label on that clip is retracted: the tracker said `in`, correct). Operator counts differ from agent counts on 7 of 27 (agent overcounted garage pairs by 1 on 5; 18:43:18 operator 8 vs agent 7).

## 1. Direction instruments that exist (producer, file:line, state)
| Id | Instrument | Producer | Live in production? |
|---|---|---|---|
| T | Tracker direction = interior-camera timing (+45 s entry, -30 s exit, nearest wins, else ambiguous); written to bus `ura_person_egress_event`, DB `person_entry_exit_events` | `transit_validator.py:2373-2423` (`_resolve_direction`), `EGRESS_ENTRY/EXIT_WINDOW_SECONDS` 45/30 `const.py:3381-3382`, triggers `:1628`, `:1672` | yes (I4 v0 = T, reproduces fixture 46/46) |
| V | Crossing-vision direction (LLM on frames) | **none in production**: `RESPONSE_SCHEMA` has no direction (`crossing_vision.py:104-123`); episode `direction` field is the tracker's, copied from the bus event (`:708`, `:742`); ambiguous crossings skipped. Offline only: P3-D0 run 1 (mt1500, 46 clips), run 2 (mt4000, 31 clips), P3-D0c recording window (14 clips) | **no** (P3-D3 unbuilt) |
| I1 | Frigate track vs door polygon (stored `path_data`, E+45 cut), v2 polygons | offline script `p3d0b2_score.py`; fixture `crossing_door_reference_frigate_v2.json` | no |
| I2 | Frigate zone order | needs a `<cam>_threshold` zone per door camera; only `<cam>_property` exists | not scorable |
| I3 | Door contact order. Garage_a: `cover.konnected_f0f5bd523b00_garage_door` (registry area Garage A). Front: `binary_sensor.door_1467` (registry-mapped, never `on`) = not scorable; `binary_sensor.elkm1_front_door` is a NAME-based mapping, sensitivity only | offline | no |
| I4 v1/v2 | Interior-timing variants (prefer entry when both windows hold an event / track start-end) | offline variants of the tracker rule | no (v1 picked best of ~6 on n=17) |
| I6 | Adjacent outside cameras' Frigate presence order (EXTERIOR_ADJACENCY_GRAPH `const.py:3026-3079` + sibling) | offline `i6probe_score.py` | no |
| R-a/b/c, anticipatory | P3-D0e approach clips (R-a Frigate records, R-b detector, R-c LLM montage), P3-D0f candidates | 276 windows downloaded (`appr_*.mp4`, step 0 only); **no scoring has been run**, no audit exists | no |
| BLE before/after, resident edge | Only the planned P3-D6 oracle (`PLANNING_crossing_vision.md:1032`, not built); BLE is not a door-direction producer | n/a | no |

## 2. Per-instrument scoring on the 19 direction-scorable grades (operator truth)
"Decided" = said in/out. Abstain = unclear/passing/none/both-sides. Right/wrong counted on decided only; coverage = decided of 19.

| Instrument | Ran | Decided | Right | Wrong | Abstain | Confusion (truth>said) | Right on the 9 tracker-wrong | Wilson 95 % on decided-right |
|---|---|---|---|---|---|---|---|---|
| Tracker (T) | 19 | 19 | 10 | 9 | 0 | in>out 9 | 0 of 9 (by def.) | 0.32-0.73 |
| I1 track vs door | 19 | 12 | 7 | 5 | 7 | in>out 4, out>in 1 | 5 of 9 | 0.32-0.81 |
| I3 garage cover | 19 | 4 | 1 | 3 | 15 | in>out 2, out>in 1 | n/a (garage only) | n=4 |
| I3 Elk (name-based, sensitivity) | 19 | 11 | 8 | 3 | 8 | in>out 3 | 4 of 9 | n=11 |
| I4 v1 | 19 | 19 | 17 | 2 | 0 | in>out 1, out>in 1 | 8 of 9 | 0.69-0.97 |
| I4 v2 | 19 | 17 | 13 | 4 | 2 | in>out 4 | 4 of 9 | n=17 |
| I6 outside cams | 19 | 8 | 7 | 1 | 11 | in>out 1 | 2 of 9 | 0.53-0.98 (n=8) |
| Vision run 1 (mt1500, truncation defect) | 19 | 11 | 10 | 1 | 8 | in>out 1 | 3 of 9 | 0.62-0.98 (n=11) |
| Vision run 2 (mt4000) | 11 | 8 | 6 | 2 | 3 | in>out 2 | 0 of 3 run | n=8 |
| Vision recording window (D0c) | 5 | 2 | 2 | 0 | 3 | none | n/a | n=2 |
| Production vision direction | 0 | 0 | | | | does not exist | | |

Coverage on the 101 crossings of 11-14 cannot be recomputed from the 27 (graded subset); P3-D0 audit figures stand (I1 0.47, I3 0.13, I6 0.39, I4 0.78-0.80).

Per truth class: tracker right on `out` 4/4 but on `in` only 6/15 (an exit bias: all 9 misses are true `in` called `out`). I4 v1: `in` 14/15, `out` 3/4. I1: `in` 7/15 (4 abstain), `out` 0/4 (3 abstain, 1 wrong). I6: `in` 4/15 (10 abstain), `out` 3/4. Vision run 1: `in` 8/15 (6 abstain), `out` 2/4.

Per door (counts only):
- front (12 in, 1 out): T 6/13; I1 6 right 2 wrong 5 abstain; I3 cover 0 decided; I3 Elk 8 right 3 wrong; I4 v1 11/13; I4 v2 10 right 2 wrong; I6 3 right 1 wrong 9 abstain; V run1 6 right 1 wrong 6 abstain. The single `out` makes front `out` accuracy unmeasurable.
- garage_a (3 in, 3 out): T 4/6; I1 1 right 3 wrong 2 abstain; I3 cover 1 right 3 wrong; I4 v1 6/6; I4 v2 3 right 2 wrong; I6 4/4 decided (2 abstain); V run1 4/4 decided (2 abstain).

Round trips (3 `both`): the tracker emitted one direction each (out, in, out); I4 v1 also one direction each; I1 decided 1 (`in`); no instrument has a round-trip output. `no_cross` (5, all garage_a): the tracker wrote a crossing record for all 5 (4x out, 1x in; 5/5 false crossings); I4 v1 emitted a direction on all 5; I1 said `in` on 3 of 5; I6 said `in` on 4 of 5. No instrument reports "did not pass". Vision recorded count 1 or 2 on those, a presence count, not a pass.

## 3. Counts (operator count on the 22 in/out/both grades; vision rows exist only where a call ran)
| Count source | n scored | Exact | Within 1 | Over | Under |
|---|---|---|---|---|---|
| Production shadow vision (4 frames, event-clip route; `crossing_vision_shadow` rows) | 17 (5 of 22 not ok: 3 error, 1 blank, 1 error = 16:16:11, 16:19:36, 16:20:48, 16:23:52, 17:11:19) | 16 | 16 | 0 | 1 |
| Vision run 1 (mt1500, 8 frames) | 21 | 17 | 21 | 3 | 1 |
| Vision run 2 (mt4000, 8 frames) | 13 | 8 | 12 | 3 | 2 |
| Recording window D0c (P3-D2 route) | 6 | 3 | 5 | 1 | 2 |
| Camera peak / tracker `peak_person_count` | 22 | 15 | 20 | 3 | 4 |

On the 4 groups of 3+ (16:16:11 op 3, 16:19:36 op 4, 16:23:52 op 3, 18:43:18 op 8): peak 0/4 exact (all under); production vision 1 non-ok-excluded (only 18:43:18 ok, 6 vs 8 under); recording window 2/4 exact (4 right at 16:19:36, 8 right at 18:43:18; 2 vs 3 and 1 vs 3 under). Production count exactness (16/17) is almost all 1-2 person crossings and errors/blank hide the group cases (4 of the 5 failures are groups).

## 4. Falsification
- "I4 v1 passes": would be disproved by a prior-only explanation. It is one: always-`in` scores 15/19; I4 v1 scores 17/19 (+2 clips), it emitted a direction on all 8 `both`/`no_cross` crossings, it is the best of ~6 variants tuned on the same clips (no holdout), and the 27 contain 1 front `out`. On the earlier agent-labelled `out` clips it was wrong 4/10 (P3-D0b audit). Not a pass; a hypothesis.
- "I1/I6/V are accurate where they decide" (7/12, 7/8, 10/11): small n, partly overlapping clips (the same front `in` clips are missed by all of V, I3 Elk and I1; audit ensemble section). Coverage fails the 0.50 gate regardless.
- Observation that would overturn "direction stays the tracker's": a second source right on >=15/17-equivalent AND on the front `out` class at n>=15 with its own coverage >=0.50. None observed.

## 5. Recommendation per P3 deliverable
Bars quoted from the plan: **P3-D0b gate** (`:681-690`): right on >= 15 of 17 AND >= 5 of 6 tracker-wrong, deterministic, own-decision coverage >= 0.50. **P3-D6** (`:1060-1066`): per door group, Wilson 95 % lower bound >= 0.90 on >= 30 oracle-scored crossings AND right on >= 0.80 of >= 15 tracker-disagreements AND stability repeat-agreement LB >= 0.80 over >= 20 repeats; PARK when the UPPER bound < 0.90 at n >= 30. **P3-D0c** gate (`:695`): undercount on the 6 pinned <= run 2's, worst clip no worse than 1, no new over-count on 7 small clips (passed 11-15). **P3-D0e/D0f**: coverage >= 0.50, errors not on V's misses; D0f build only if graded tracker misses >= 3/week/door group or step 5 direction gate passes and candidates/day <= 150.

| Deliverable | Verdict | Evidence |
|---|---|---|
| **P3-D2** recording-window route + 8 frames | **PASS, build** (count only; plan bar already met 11-15). The 27 do not contradict it: recording-window counts are right on both big parties it can see (4, 8) and the route fixes the failures (3 error + 1 blank in production = 4 of 5 non-ok rows are 3+ groups). Residual stays: a group that arrives over > 20 s is undercounted (16:23:52: 1 vs 3). Only 6 graded crossings ran on that route, so the count accuracy claim rests on the original 30-clip bar plus these 6. |
| **P3-D3** record vision direction on every crossing, behind INV-DIR-GATE | **Build as recorded-only; the grades give no bar to flip.** Plan has no pass bar for building (operator "build and hold off and measure"); the flip bar is P3-D6. Vision direction today: run 1 10/11 decided but 8 of 19 abstain and in>out only; run 2 6/8 on 8. Needs the production reps, the stability repeat, and `out` grades: propose a minimum of 30 scored per door group per P3-D6 (front currently 12 in / 1 out). |
| **P3-D10** approach clips | **Needs more grades AND the unrun probe.** D0e step 0 (download, retention 5 d continuous) was done; R-a/R-b/R-c were never scored (no audit). Clips expire 2026-11-19 12:59-21:54 CST. Score R-a on the 27 (+ the remaining 19 answer-key clips) before they expire. No verdict possible. |
| **P3-D11** extended tracker (contact + motion trigger; `combine_direction`) | **FAILS for direction, needs more grades for the trigger.** No direction source reaches the P3-D0b gate (best independent I1 5/9 on tracker-wrong at 12/19 decided; I3 contact garage 1/4 right; front contact unmapped); the extension would only be justified by I4-v1-style bias, which the always-`in` baseline explains. Trigger part: 5 of 27 tracker crossings were no-pass (all garage_a) and 3 were round trips, but the 27 hold zero tracker MISSES (they are drawn from tracker records), so the D0f miss gate (>= 3/week) is unevaluated; needs a graded batch of `unmatched` candidates. Propose bar for the direction part if none: Wilson LB >= 0.90 per door group at n >= 30 with at least 15 `out` grades (the same P3-D6 bar, applied to a deterministic source, no stability test). |

Gaps the grades expose (card-worthy, not built here): (1) no instrument or tracker output means "did not pass" (5/27 = 19 % false crossings, all garage); (2) round trips (3/27) collapse to one direction; (3) the sample has 1 front `out` and no tracker-ambiguous crossings, so the 20-53 % ambiguous crossings are unscored; (4) tracker `in`->`out` error 9/15 is the dominant failure and is unchanged by every independent instrument except the `in`-biased I4 v1.

## 6. What is not done
- Coverage on the 101 crossings was not recomputed (needs all-crossing outputs, P3-D0 figures cited).
- P3-D0e R-a/b/c and P3-D0f not scored (no code exists in the repo; would need the downloaded windows).
- The other 19 answer-key clips and the pair batch are ungraded (operator).
- Interior-desc grades (3 rows in the 30-row backup) are a different pilot and not used.
