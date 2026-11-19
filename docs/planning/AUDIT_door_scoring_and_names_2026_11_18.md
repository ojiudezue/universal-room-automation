# AUDIT: door direction re-score on 56 grades + name accuracy (2026-11-18)

Prober, read-only. Run Wed 2026-11-18 23:51-00:10 CST (system `date`). Card VISION-AMBIGUOUS-CROSSINGS-1. Scripts: `.claude/tmp/gradescore_db.py` (ran on HA, read-only sqlite), `gradescore_run.py` (extends `doorscore_*.py` and `p3d0b2_score.py` I4/I1/I3/I6 logic), data `gradescore_db_out.json`, `gradescore_rows.json`. State changes: none. Read in full first: `AUDIT_door_direction_scoring_2026_11_17.md`, `AUDIT_step7_d0_2026_11_17.md`. No presence/HVAC logic touched, so state-of-play docs not needed.

## 1. Pull
`python3 scripts/grading/pull_grades.py --no-clear` -> "29 queued, 0 new or regraded, 56 total". The 29-row batch g20261117-1327 (graded 2026-11-17 20:14-20:32 UTC) was already imported in commit d8079b863. File: 56 rows (27 batch g20261115-1716 + 29 batch g20261117-1327), all kind=crossing. Directions: in 20, out 16, both 9, no_cross 9, unclear 1, unknown 1. **`who`, `guest_count`, `notes` appear in 0 of 56 rows** (the `who` page shipped 2026-11-18; pull_grades.py:66 says optional fields copied only when sent). The current manifest `homelab-automation/sites/urakanban/grade/manifest.json` is batch g20261118-0634 (41 cards, 16 already-graded keys) and has no grades back yet.

## 2. Door direction (in/out only, n = 36: front 27 = 16 in/11 out; garage_a 9 = 4 in/5 out)
Truth = operator. Tracker = `crossing_vision_shadow` row direction (50 rows) else `person_entry_exit_events` within [E, E+60] (5), none for 1. I4 v0 equals the tracker on 56/56. Wilson 95%.

| Instrument | Decided/36 | Right | Wrong | Wilson LB (decided) | Confusion |
|---|---|---|---|---|---|
| Always-`in` baseline | 36 | 20 | 16 | 0.40-0.70 | |
| Tracker (= I4 v0) | 36 | 23 | 13 | 0.48 | in>out 13 |
| Vision, production | 0 | | | | **no direction exists**: shadow `direction` is the tracker's copy (`attrs_json` keys have no vision direction) |
| I4 v1 | 36 | 30 | 6 | 0.68 | out>in 5, in>out 1 |
| I4 v2 | 33 | 26 | 7 | 0.62 | |
| I1 track vs door | 22 (ran 31) | 15 | 7 | 0.47 | |
| I3 garage cover | 4 | 1 | 3 | 0.05 | |
| I3 Elk (name-based, sensitivity) | 22 | 19 | 3 | 0.67 | in>out 3 |
| I6 outside cams | 12 | 10 | 2 | 0.55 | |

Offline instruments ran only on the 31 graded crossings inside the 11-14 fixture; vision offline runs (V1/V2/recwin) cover only the first 27 and were not rerun (needs model calls, none made).

Per door: front tracker 16/27 (LB 0.41; all 11 errors in>out), I4 v1 22/27 (0.63), I4 v2 22/26, Elk 19/22 (0.67). garage_a tracker 7/9 (0.45), I4 v1 8/9 (0.56), I6 4/4 decided (LB 0.51).

**P3-D6 bar (per door Wilson LB >= 0.90 on >= 30 scored): not met anywhere.** Front n=27 (<30), garage_a n=9; best front LB 0.67; no instrument approaches 0.90.

### I4 v1 holdout (graded after 11-17; tuned on first 19)
| Set | n | Tracker | I4 v1 | I4 v2 | Always-in |
|---|---|---|---|---|---|
| Tuning (batch 1) | 19 | 10 (0.53) | 17 (0.89, LB 0.69) | 13/17 | 15 |
| **Holdout (batch 2)** | 17 (12 out, 5 in) | 13 (LB 0.53) | **13 (0.76, LB 0.53)**, all 4 errors true out>in | 13/16 | 5 |

I4 v1's gain vanishes on holdout (equal to the tracker, 13/17); it is an in-bias fit, not a pass. Holdout front: tracker 10/14, I4 v1 11/14, I4 v2 12/14, Elk 11/11 (name-based, sensitivity only); holdout garage_a n=3 (tracker 3/3). The tracker's in>out bias persists (13 of its 13 errors). Holdout is out-heavy (12/17), so the always-in baseline is a poor reference here.

Non-directional: both (9): tracker emitted one direction on 9 (6 out, 3 in), I4 v1 on 9; no_cross (9): tracker emitted a direction on 8; unclear/unknown (2): both got directions. No instrument reports "did not pass" or a round trip.

## 3. Names
**Cannot be scored: 0 of 56 grades carry `who`.** Needs the g20261118-0634 batch (41 cards) graded. What URA named on the 56 (shadow `person_id`/`identity_provenance`): jaya/face 9 (in 5, out 2, both 2), ziri/ble 1 (in), oji_udezue/ble 1 (no_cross), none/no shadow row 45. So 11 of 56 named, 0 verifiable. Step 7 S1 anchors (`AUDIT_step7_d0`): the 2 would-be anchors (11-15 18:13:38, 11-13 18:18:07) are not in any graded batch; the 11-13 18:18:07 key is a card in the new manifest. Per-person Jaya/Ezinne/Oji right/wrong/blocked: unknown, n = 0.

## 4. Falsification
"I4 v1 passes" is disproved on holdout (13/17 = tracker). "Tracker is out-biased" would be disproved by holdout tracker errors being out>in; observed 4/4 in>out, so it stands. Not evaluated: count accuracy, D8a outcome rows, vision direction (none exists).
