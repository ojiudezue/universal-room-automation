# Plan review: crossing vision Phase 3, closure spot-check (2026-11-15)

Scope: `git diff 810075a3 25b30764 -- docs/planning/PLANNING_crossing_vision.md docs/planning/PLANNING_census_deconfliction.md`,
checked against code on develop (25b30764). Answers `plan_review_crossing_vision_p3_completeness_2026_11_15.md` and
`plan_review_crossing_vision_p3_buildpred_G_2026_11_15.md`. Read only; no tests run. HVAC not touched. Presence: the
plan touches census inputs; this check verified ledger/tracker code directly and did not re-read the presence
state-of-play doc completely (no presence claim is asserted here beyond cited code).

**Verdict: PLAN-FIX-REQUIRED** (1 HIGH, 5 MEDIUM, 5 LOW). All fixes are plan text; none needs a redesign.

## Verified as closed (holds because ...)

- Cited call-time sites are exact: `crossing_vision.py:869` (disabled, `term_done = True`), `:873-876` (cap ->
  `_request_terms`), `:878-882` (no clip), `:906` (kill reply None), `:928` (outcome), `:935-939` (finally). No-request
  paths `:678`, `:690`, `:698`, `:702` and the late-joiner `:749` match P3-D4 step 7 / step 4.
- `_prune_requests` (`:780-787`) drops only `status == "done"` requests older than `2 x CLUSTER_S`; `CLUSTER_S = 60`
  (`const.py:3615`), so the setup assert `TERM_HOLD_S (110) <= 120` is consistent, and the "never prune unreleased"
  rule is needed because `finally` sets `status = "done"` before a held release.
- Anchor block: `CrossingLedger._sample_ok` (`crossing_ledger.py:469-482`) fails on `_entry_since_sample` and
  `evaluate` resets `_t_start = None` (`:496-499`); "fails as if an entry term arrived" maps onto that conjunct.
  Late rule `apply_term` `:447` (E < last anchor -> recorded, not applied) is what the block protects.
- `unsub_hold` vs `unsub_timer`: `_fire_request` (`:790-796`) clears `unsub_timer`; a separate slot is required. Teardown
  today cancels only `unsub_timer` (`:449-454`); the plan adds the hold cancel and drop. Consistent.
- W9-W11 arithmetic re-run against `census_tick` lift (`:373-391`), `_consume_credits` (`:403-417`), `apply_term`
  (`:441-466`) and `judge_reconcile` (`:554-585`): W9 today L=2, guest_vis 1; collapsed L=1, guest_vis 0. W10 today
  L=2 (one low), collapsed L=3. W11 0 both ways. INV-P2-ONCE holds in all three. Correct.
- P3-D5: `ended_at` is `dt_util.utcnow().isoformat()` at `_record` write (`:1012`), `started_at` is the crossing ts
  (`:960`); index `idx_episodes_node_type (node_id, episode_type, started_at)` (`database.py:2013-2014`) does not cover
  an `ended_at` range. Existing memory DAOs swallow errors via `_mem_dao_warn` (`database.py:11077`); the new
  `(count, ok)` return is a real difference. Local-day roll at `_roll_day` `:491-500`.
- Census plan edits: the F-LEAD row (`PLANNING_census_deconfliction.md:74`) restarts bars only on the CROSSING plan's
  `pipeline_version` bumps. The interior plan's `interior_leads` has its own bar (§9.D4) and never cites bars a-e
  (grep: no hits), and its own `pipeline_version` (`PLANNING_vision_interior_sightings.md:471`) is not named in the
  census row. No conflict.
- Structure: one clean document; review IDs are inline provenance, not layered overrides.

## Findings

### HIGH-1 Pass rule: the round-trip falsifier is vacuous as written, and the one-event round trip is unaddressed
`PLANNING_crossing_vision.md:564-576`, `:599-603`. Class: hollow gate (#62 shape, applied to a probe).
- The negative set is "fixture pairs labelled `round_trip`" plus "synthetic negatives = crossings with distinct
  own-camera events within +/- 10 s". The 11-14 audit labels no round trips (grep of
  `AUDIT_door_vision_accuracy_2026_11_14.md`: the only hit is the tracker comment), so the fixture part may be empty;
  the synthetic part cannot fail by construction (distinct own-camera events -> distinct `pass_key` under the
  own-camera preference). "0 round_trip pairs share" can therefore pass with n = 0.
- The case that CAN merge a real round trip is one Frigate event spanning both crossings (resident steps out for a
  parcel and back while staying in frame; events run 5-466 s per the audit). The tracker itself encodes that this is
  real: `transit_validator.py:2425-2427` "opposite direction NEVER collapses (exit->entry inside 30 s is a real
  round-trip)". Under `tracker` collapse is L-neutral (+1 -1 vs none) but changes credits/reconciles; under `vision`
  (P3-D7) it gives one term in vision's direction = off by one if vision reads in/out; under P3-D8 it suppresses the
  re-entry for every reader, so the census egress-face union evicts on the exit and never re-registers.
- Also undefined: an in-progress event (`end is None`, the ring stores it, `crossing_vision.py:771`) — is the window
  [start - pad, now], [start - pad, inf), or "no pass yet"? A builder will pick one.
- **Fix:** (a) P3-D0 (d) requires a minimum real negative count (`CROSSING_VISION_PAIR_ROUND_TRIP_MIN_N`, knob row),
  mined from 14 days of `egress_identity_outcome`: opposite-direction same-door pairs where one Frigate event spans
  both Es, hand-labelled from clips; if n is below the minimum the gate is HOLD, not pass. (b) State the `end is None`
  rule. (c) Name the one-event round trip as a residual in P3-D4 / P3-D7 / P3-D8 with its per-reader effect.

### MEDIUM-1 "Only caller of the term builder" contradicts steps 4 and 7
`:698` says `_release_terms` is "the only caller of the term builder"; steps 4 and 7 keep direct `_ledger_terms` calls
(`crossing_vision.py:678/690/698/702/749`), and the Tier line (`:840`) lists them as term sites. Fix: "the only setter
of `term_done` and the only builder of REQUEST terms"; also name `_request_terms` (`:1073-1078`, today's setter at
`:1077`) as replaced/removed. Class: build-prediction ambiguity.

### MEDIUM-2 A request whose release never happens blocks the anchor forever
Step 6 blocks the anchor "while any request has unreleased terms". Today `_request_terms` sets `term_done = True`
BEFORE `_ledger_terms` (`:1077-1078`) and the `finally` except sets it (`:938-939`), so an exception still releases.
The plan does not say `_release_terms` keeps set-before-apply, nor what happens if the hold timer is lost (callback
raises, scheduling fails). Then the request is never pruned (step 3) and the anchor never fires; `anchor_zero` pages,
but that is detection. Fix: set `term_done` before applying, and bound the anchor block by a deadline
(E_primary + `TERM_HOLD_S` + the worst outcome bound), counted when it expires. Class: suppression needs a discharge.

### MEDIUM-3 Layer-guard bump is incomplete; interior merge resolution
`test_person_awareness_layer_guard.py:62` asserts `LAYER_ALLOWLIST_TOTAL == 259 and len(A.ROWS) == 231`; the
allowlist also carries `LAYER_ALLOWLIST_TOTAL_PROVISIONAL = 259` (`:19` on the interior branch, same on develop). The
plan names only 259 -> 260. Fix: also `len(ROWS)` 231 -> 232 and the PROVISIONAL constant; the `("R13", 8)` floor
(`:147`) stays valid. `amend_crossing` is already in `R13_CALLEES` (`_layer_guard_engine.py:154-157`), so the row is
needed. Interior (`feature/interior-vision-d1`): its diff touches none of the three guard files, and its plan says
"rows added 0, stays 259" (`PLANNING_vision_interior_sightings.md:184`, `:203`). No textual collision today; the
resolution is that interior's number is a delta of 0, so whichever merges second takes 260 if Phase 3 P3-D3 landed
first. Put that sentence in both plans.

### MEDIUM-4 F-LEAD "FLIP-READY for the tracker" is undefined and effectively unreachable
`PLANNING_census_deconfliction.md:74` requires P3-D6 FLIP-READY "for the ledger's direction source in use (tracker
sign accuracy or vision)". P3-D6 (`PLANNING_crossing_vision.md:793-809`) defines FLIP-READY only for vision; tracker
accuracy is reported, not dispositioned. The measured tracker is 11/17 (65 %), far below a 0.90 lower bound, so in
practice F-LEAD now waits for P3-D7. That may be right (signs decide L), but it is a material gate change for the
charter and must be stated, and P3-D6 must define the tracker verdict. Framing-G item: operator should see it.

### MEDIUM-5 P3-D5 DAO under-specified for the actual schema
The plan says "`attrs.outcome`"; the column is `attrs_json` TEXT (`database.py:2010`), so the query needs
`json_extract(attrs_json, '$.outcome') IN (...)` (precedent `database.py:8438`). Bounds compare ISO strings
lexically: they must be produced with the same `isoformat()` shape as the writer (`+00:00` suffix, microseconds),
or rows at the boundary mis-sort. Also say whether the DAO goes through the read path (not `_write_queue`). Name the
`(episode_type, ended_at)` migration route (`_create_table_safe` index list vs a versioned migration).

### LOW
- L1 `CROSSING_VISION_DAILY_CALLS_MAX` (200) and the 200 000-row index threshold have no knob rows (only inline).
- L2 Step 6 "an anchor can never fire between E and release" overclaims: the bus event arrives 10-200 s after E, before
  any request exists; an anchor in that gap still makes the term late (pre-existing). Say "between the bus event and
  release".
- L3 W10 assumes the R edge precedes the terms; with terms first, today ends L=3 too. State the ordering.
- L4 Accepted residual (both members cap/busy -> two terms): bounded and counted, but terms use each member's camera
  peak, so +n_entry -n_exit can be non-zero; `skipped_busy` needs only 2 in flight (`MAX_CONCURRENT = 2`,
  `const.py:3617`) and P3-D0 (a) does not measure concurrency. Add busy-collision rate to P3-D0 (a).
- L5 Held terms vs the stuck sample (`entry_blocks=False`, `crossing_ledger.py:491`): say whether a held term blocks
  `stuck_ok`.

## Summary

| Severity | Found | Must fix before build |
|---|---|---|
| HIGH | 1 | 1 |
| MEDIUM | 5 | 5 |
| LOW | 5 | optional (fix in the same pass) |

Bug classes: hollow gate (HIGH-1), build-prediction ambiguity (MEDIUM-1, -5), suppression without discharge
(MEDIUM-2), one-missed-site on a guard constant (#53 shape, MEDIUM-3), goal fidelity (MEDIUM-4).
