# URA v5.108.36: crossing vision watches every crossing; crossing-centred frames (P3-D2 + P3-D3)

Cards: VISION-AMBIGUOUS-CROSSINGS-1 (P3-D2, P3-D3; stays open for P3-D4/D6/D7 and the direction flip). Plan:
`docs/planning/PLANNING_crossing_vision.md` P3-D2 (Tier 2) and P3-D3 (Tier 3). Arc map row 6 ("score every instrument
once on the 27 -> build what passes"): `docs/planning/AUDIT_door_direction_scoring_2026_11_17.md`.
Build 00cd94cef; reviews A+G SHIP-after-M1, B SHIP, D SHIP, C FIX-REQUIRED (17 untested sites); fix pass 62508c18d;
orchestrator mutations RED (below). Review records `docs/reviews/code-review/v_crossing_p3_d2_d3_review_{A_G,B,C,D}.md`.

## What it does

- **P3-D2, crossing-centred frames.** The vision call reads 8 frames from the Frigate recording window around the
  crossing (`recording_window` route, gate passed in P3-D0c) at 4000 tokens, not 4 frames spread over the whole event.
  The event-clip route stays as the fallback; the short-clip path is kept.
- **P3-D3, watch every crossing, record direction behind the gate.** Crossings the tracker leaves ambiguous (35 of 54
  on 11-16) now get a vision call too. Every row records vision's count and direction (`vision_direction`,
  `vision_direction_confidence`, `direction_agreement`, `pipeline_version`, `call_kind`). Direction is attached to the
  crossing record only through the one G3 amend path (`transit_validator.amend_crossing`, role `vision_direction`).
  Stability repeats re-ask a sample of crossings within their own small daily budget, so P3-D6 can measure flips.

## Invariant (INV-DIR-GATE)

While a door group's direction source is `tracker` (every group today), nothing vision says about direction changes a
ledger term, L, guest_vis, a primary outcome, the cap count, an F1 edge, a notification, egress identity, the census
or any entity a consumer acts on. An ambiguous crossing never yields a ledger term; the tracker's `direction` is never
written. Review D traced every reader: the two `SIGNAL_EGRESS_RECORD_AMENDED` listeners (`sensor.py`) act only on
`exit_backfilled`; the new record fields have no reader outside `crossing_vision.py`; `crossing_ledger.cluster_terms`
drops non entry/exit members.

## Burst protection (review M1)

Ambiguous crossings never displace a resolved crossing's vision call: one in-flight slot is always kept free
(pending < `CROSSING_VISION_MAX_CONCURRENT` - 1), and ambiguous calls stop `CROSSING_VISION_AMBIGUOUS_CAP_RESERVE`
(30, rung 1: 19 resolved crossings on 11-16 x 1.5 headroom) calls short of the daily cap. Otherwise the row records
`skipped_reserved`. Residual: with two resolved crossings pending while one ambiguous call runs, the second resolved
one is `skipped_busy`; at most one ambiguous call is ever in flight.

## Knobs (rung 1, `const.py`)

13 new knobs for the route, window (BEFORE / AFTER / LAG / require-complete), watch-ambiguous switch, repeat rate and
daily budget, pipeline version and the cap reserve; each has an off value. Only a cap of 0 stops repeats (lowering the
cap mid-day does not).

## Behaviour changes to note

- Late joiners key on `term_direction`: when the primary built no term, a same-direction joiner gets its own term
  (only matters while the ledger is not promoted).
- `scripts/grading/make_grade_batch.py` reads primary rows only (a repeat shares `source_ref` / `started_at`).
- Layer guard +1 R13 row (`_amend_vision_direction:amend_crossing`), the sanctioned G3 feed (contract §2.3, §4.2).

## Orchestrator verification (Tier 3)

| Mutation (real source edit, restored) | Result |
|---|---|
| G3 amend also writes `direction` = vision | RED: `test_g3_never_sets_direction`, `test_amend_not_analysed_never_stamps_direction`, +3 |
| Ambiguous slot gate removed | RED: `test_burst_never_displaces_resolved_vision_call`, `test_ambiguous_never_admitted_at_max_concurrent_one` |

## Live checks after install

1. An ambiguous crossing gets a `crossing_vision_shadow` row with `analysed_ambiguous` and no ledger term.
2. Rows carry `pipeline_version`, `call_kind` (`primary` / `repeat`) and, on `ok`, `vision_direction`.
3. `calls_today` stays under the cap; repeats under their own budget; no `skipped_busy` on a resolved crossing while
   ambiguous calls are idle.
4. No change to ledger terms, the census or arrival notifications attributable to vision direction.

## Validated 2026-11-17

HA core restarted 10:40:14 CST (house home_day); entries loaded by 10:42:07.

| Criterion | Result | Evidence |
|---|---|---|
| Install | PASS | manifest v5.108.36; tag grep `CROSSING_VISION_AMBIGUOUS_CAP_RESERVE` (const.py), `_ambiguous_reserved` / `_amend_vision_direction` (crossing_vision.py) |
| Entries | PASS | 50/50 URA entries loaded |
| Errors | PASS | no URA ERROR; 53 WARNINGs all boot transients (rooms "All N sensors unavailable, holding 60s", HVAC boot-settle timeout, one aggregation re-anchor delta, zone=Outside fallback); no crossing_* lines |
| Cap rehydrate | PASS | `crossing_vision_today` / `_cap_rehydrate` on `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`: state ok, cap_hold false, failed 0, calls 7 = 7 primary rows in `crossing_vision_shadow` today; repeats 0 |
| 1-4 crossing path | Pending event | no crossing since the restart (last row 09:16); `pipeline_version` / `call_kind` / `vision_direction` not yet observed |

## Not done (accounted)

- Step 11, the arrival record: P2-D9 does not exist yet (`get_last_arrival_record` returns None).
- The optional "n+" display for groups of 3 or more.
- Contract §2.3 / §4.2 amendment naming the vision-direction G3 role (orchestrator, follows this release).
- P3-D10 approach clips: NO-GO on all three routes (`AUDIT_crossing_vision_p3_d0e_approach_2026_11_17.md`); revisit at
  ~15 graded exits.
- Accepted residuals: event-clip route, two requests on one event overwrite each other's end trigger (delayed, not
  lost); a repeat cancelled mid-call at unload stays counted.
