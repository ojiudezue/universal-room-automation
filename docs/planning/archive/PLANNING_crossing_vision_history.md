# PLANNING_crossing_vision history: NOT A BUILD SPEC

History only. The build spec is `docs/planning/PLANNING_crossing_vision.md`. Older history:
`HISTORY_crossing_vision_rev3_to_7_1.md`, `HISTORY_crossing_vision_partB_record_rev3_to_5.md`.

## 2026-11-15: Phase 3 amendment (VISION-AMBIGUOUS-CROSSINGS-1 + DOOR-VISION-GROUP-UNDERCOUNT-1)

Why: the ground-truth evaluation `AUDIT_door_vision_accuracy_2026_11_14.md` (46 clips counted by hand) found direction
wrong on 6 of 17 readable clips, 21 opposite-direction cluster pairs that are mostly one physical pass, every group of
3+ undercounted, one false blank, 4 errors with no recorded cause, and 46 calls against a cap of 40. Operator rule
2026-11-15: "The things we see not working have to be reasoned through and fed back into our new plans ie the direction
issue". The plan was rewritten in place (§0, §2, §3, §4, D1 step 8, P2-D2 step 3, new Phase 3, §6, §7, §8).

Text replaced (verbatim, from develop 92e93c54):

- INV-SCOPE: "Every frame sent belongs to a Frigate event on a camera in the crossing's own door group (live
  `door_groups`; no entry = a group of one); never an ambiguous crossing. Calls per local day ≤
  `CROSSING_VISION_DAILY_CALLS`, in flight ≤ `CROSSING_VISION_MAX_CONCURRENT`, nothing queued beyond (counted skip).
  Accepted residual: the cap counter is RAM, so each restart can allow up to one more cap that day."
  Replaced because: watching ambiguous crossings is an operator decision ("of course. No brainer"); a recording window
  is a second legal frame source; the RAM residual let 46 calls through a cap of 40 on a day with two restarts.
- INV-ADDITIVE ambiguous clause: "Ambiguous: bus key None, no row, no sample." Kept in substance (no DB row, no sample);
  the vision row now exists for ambiguous crossings.
- D1 step 8: "schema `{frames: [{index, people}], people_total, direction, group, desc}`". Was already wrong against
  the build (`crossing_vision.py:96-118` has no direction); corrected.
- P2-D2 step 3 ledger rule: "Term per outcome with validator direction. ... Cluster: one term with the primary's count
  if all members share a direction, else per-member camera terms. Vision direction never used. ... `ambiguous` no term."
  Replaced because the per-member rule gives +n and −n for one physical pass, and the direction source becomes a gated
  knob (INV-DIR-GATE).
- Knob row: "`CROSSING_VISION_DAILY_CALLS` | 40 | 3 (Number) | 0 = no calls; RAM counter, local midnight".
- §8 non-goal "vision direction" (one of the listed non-goals). It was a scope cut in this plan, not an operator
  decision; the D0 basis (51 % agreement, `AUDIT_crossing_vision_d0_2026_11_13.md:71`) compared vision with the
  validator, which the 11-14 hand count shows is itself wrong on about a third of readable clips.

Options considered and not taken:
- Make `direction` an amendable G3 key so vision fixes the tracker for every reader: rejected, readers act at resolution
  (notify, census union, DB, perimeter) 10-200 s before vision lands; a retro change is a different product and Tier 3
  on its own. Carded as EGRESS-TRACKER-DIRECTION-1 (filed by P3-D7).
- Collapse opposite pairs by time window only: rejected, it would also merge real round trips; the plan keys a pass on
  the shared Frigate event id, gated by the P3-D0 (d) measurement.
- A second "crowd" model call when the peak is 3+: rejected for more frames in the same call (no cap cost, no second
  model per crossing, a standing non-goal).
- Accept the RAM cap residual: rejected for rehydration, because of the restart-storm history.

## 2026-11-15 (later): Phase 3 plan-review fix-up

Reviews: `docs/reviews/code-review/plan_review_crossing_vision_p3_completeness_2026_11_15.md` (H1, H2, M1-M6, L1-L6) and
`plan_review_crossing_vision_p3_buildpred_G_2026_11_15.md` (B1-B12, G1-G3), both PLAN-FIX-REQUIRED on 810075a3. The
Phase 3 section was rewritten in place; the census plan's F-LEAD row and §8 non-goal were amended in the same commit.

Superseded text (810075a3), in substance:
- `pass_key` = "the member's OWN matched Frigate event", computed with `_match_event`. Wrong: `_match_event` picks the
  best event across the whole door group (`crossing_vision.py:761-778`), so the P3-D0 (d) gate measured the selector.
  Replaced by the Pass rule (E inside one event's [start, end] ± pad, own camera preferred, None never matches) and a
  round-trip negative set reported under both rules.
- "the primary's vision values" written onto every cluster member. Replaced by per-member attributes; a round-trip
  member never carries the primary's direction.
- Term hold "max(vision outcome, E_primary + 110)" with no release site, no anchor rule, no gate re-read, no prune
  coupling, and no statement for the no-request paths. Replaced by one release site, held terms blocking the anchor,
  teardown drop (counted), gates re-read at release, prune exemption with `TERM_HOLD_S ≤ 2 × CLUSTER_S`, and per-path
  counted residuals.
- Late joiner keyed on `members[0].direction` (an ambiguous primary would double count). Replaced by `term_direction`.
- Collapse described as if term-neutral. Replaced by W9-W11 naming the reconcile / credit changes.
- Cap rehydrate "one query before the listener, DB error = cap" on a DAO that does not exist. Replaced by a new
  error-reporting DAO (P3-D5 now Tier 2-DB), listener first at the cap sentinel, background rehydrate with timeout and
  one retry, counting by `ended_at` (call time).
- Recording-route fallback "in the same request" after an llmvision fetch failure (not buildable without a second
  call). Replaced: pre-call failures fall back; a fetch failure is an `error` row.
- A new `tracker_direction` row key. Replaced by reusing the existing `direction` key.
- EGRESS-TRACKER-DIRECTION-1 "filed by P3-D7" (weeks out, no slot). Replaced by P3-D8 right after P3-D4, gated on
  P3-D0 (d); §1 now states which readers keep the wrong direction until it ships.
- Census plan: "vision direction" was a blanket non-goal and F-LEAD had no direction bar. Now F-LEAD needs P3-D6
  FLIP-READY for the direction source in use, and every Phase 3 `pipeline_version` bump restarts bars a-e.

## 2026-11-15 (closure): Phase 3 closure review + harmonization fold-in

Inputs: `docs/reviews/code-review/plan_review_crossing_vision_p3_closure_2026_11_15.md` (HIGH-1, MEDIUM-1..5, L1-L5) on
25b30764, and `HARMONIZATION_identity_vision_census_2026_11_15.md` conflicts C1, C3, C5, C7, C8 (with C2 naming).

Superseded text (25b30764), in substance:
- P3-D0 (d) negative set = fixture `round_trip` pairs plus synthetic distinct-event pairs: vacuous (the 11-14 audit
  labels no round trips; the synthetic set cannot fail). Replaced by mined one-event opposite pairs over 14 days,
  hand-labelled, a minimum count (HOLD below it) and a merge-share bound; `end is None` rule stated; the one-event
  round trip named as a residual in P3-D4, P3-D7 and P3-D9b.
- Crossing vision computed `pass_key` itself and wrote it through G3. Replaced (C5): the tracker owns one pass key,
  stamped at creation (P3-D9a, before P3-D4); G3 now writes three fields, not four.
- "`_release_terms` is the only caller of the term builder". Replaced: the only setter of `term_done` and the only
  builder of request terms; `_request_terms` removed; set-before-apply kept; anchor block bounded by a deadline.
- Guard bump named only `LAYER_ALLOWLIST_TOTAL`. Now also `len(A.ROWS)` 231 → 232 and the PROVISIONAL constant, plus the
  merge rule with the interior branch (written in both plans).
- F-LEAD "FLIP-READY for the tracker" was undefined. P3-D6 now defines TRACKER-READY; the census row says F-LEAD in
  practice waits for P3-D7; recorded as an operator-visible tradeoff.
- P3-D5 DAO named `attrs.outcome`; now `json_extract(attrs_json, '$.outcome')`, ISO-shape bounds, read path, index via
  the `_create_table_safe` list.
- The tracker step was labelled P3-D8. Renumbered P3-D9 (a/b) so P3-D8 is the harmonization's "anchor honours stuck
  exclusion" deliverable (C1, operator decision pending).
- Knobs `..._PAIR_COLLAPSE` / `PAIR_SAME_EVENT_MIN` renamed `..._PASS_...` (C7: "pair" means the confusable-resident
  pair only).
- Interior plan D5 pointed at a fast-stage G3 write that never exists; now reads P3-D3's `vision_people_count` (C3).
- Census plan §3.3 now names the code parameter `vision_leads` (C2).

## 2026-11-15 (final): Phase 3 final spot-check fix-up

Input: `docs/reviews/code-review/plan_review_crossing_vision_p3_final_2026_11_15.md` (H1, M1-M3, L1-L4), plus the
coordinator's note that the music repair merge lowers the guard totals by 3.

Superseded text (5f602cd3), in substance:
- P3-D8 read `get_stuck_sensor_kinds()` as "stuck-excluded". Wrong: it is a label map; duty-cycle hits (sleepers) are
  labelled but not excluded and shadow chatter is labelled but not promoted, so the anchor would have fired on a
  sleeping house. Replaced by the room's `SensorExclusionSet` narrowed to the stuck clients, through a new room getter
  and a `camera_stream_health` wrapper over the existing `_ask` sweep; dead inputs still hold.
- Deadline "`EVENT_END_WAIT_S` 120 + `TIMEOUT_S` 90 = 320 s" (arithmetic wrong). Now E + 110 + 120 + 90 = E + 320 s,
  asserted ≥ E + 255 s.
- Round-trip gate MIN_N 5 with a 0.10 point-estimate ceiling (5 cannot show a ceiling: 0/5 has an upper bound ≈ 0.43).
  Now ≥ 20 labelled one-event round trips from up to 30 days and a Wilson upper bound ≤ 0.15; below 20 = HOLD with
  collapse off (orchestrator decision, recorded).
- Interior D5 was claimed as a `pass_key` consumer with no text in its plan; the interior plan now merges D5 windows by
  `pass_key`.
- Guard counts written as absolute numbers (231 → 232, 259 → 260). Now deltas against develop at merge time (P3-D3 +1),
  re-read by each builder, in both plans.
- P3-D9a lifecycle and guard delta, and P3-D9b's compute-before-dedup ordering, added.

## 2026-11-15 (P3-D0 fold-in): results of the Phase 3 probe fed back into the plan

Why: `AUDIT_crossing_vision_p3_d0_2026_11_15.md` (runs 1 and 2; decisions on run 2). Operator rule 2026-11-15: "The
things we see not working have to be reasoned through and fed back into our new plans". Results: (a) GO, cap 93; (b)
direction NO-GO 13/17 and 3/6 (gates 15, 5), 15:12:14 flipped between identical calls; (b) group NO-GO on the ≤ 1 bar
(25/30 exact, 1 over, 4 under; 18:43 and 21:24 under by 2), false blank fixed, empty replies were 1500-token truncation;
(c) recording route GO, a 289 MB event clip took 86.6 s against the 90 s timeout; (d) HOLD, ≤ 19 round trips and rule
(ii) shares a key on only 4 of 14 one-pass pairs; (e) errors not reproduced.

First draft of this fold-in PARKED LLM direction (P3-D3 direction, P3-D6 vision verdict, P3-D7) with a revival trigger.
The operator overruled the park the same day: "Is the bar right? I'd not park and instead build and hold off and
measure. We need reps." The final text records direction behind INV-DIR-GATE on every crossing, scores it per door
group for accuracy and repeat-call stability (sampled repeat 0.2), and flips per door group only at P3-D7's checkpoint.

What changed in the build spec:
- P3-D0 spec replaced by a DONE entry; NEW P3-D0b (deterministic direction instrument: Frigate track vs door, zone
  order, door contact order, interior-timing variants), P3-D0c (≤ 14-call recording-window group check), P3-D0d (pass
  key candidates: contact cycle, right-direction-instead-of-collapse, event chains).
- P3-D2: 8 frames on every crossing call (was: 8 only when camera peak ≥ 3 or event > 60 s), 4000 tokens, BEFORE 5 s,
  LAG 10 s, large-clip handling, named group bias with "vision count alone, not max with peak".
- P3-D3: adds `direction_confidence`, the sampled repeat row, per-member rule without a pass key; G3 role kept.
- P3-D4, P3-D9a: build waits for a passing P3-D0d candidate (was: P3-D4 ships with collapse off, P3-D9a ships on rule (ii)).
- P3-D6: every source scored the same way per door group; stability bar added; days-to-bar per door group.
- P3-D7: per-door-group flip map.
- P3-D9c NEW: the deterministic direction fix inside the tracker.
- P3-D1, P3-D5, P3-D8 marked built on `feature/crossing-p3-first`; P3-D5 residual text from that branch folded in.
- Decisions, tier, knobs, §7 sequence (anchor prerequisites S1-S3 and P3-D2 first), non-goals updated.

Text replaced (verbatim, from develop 94f276e5):

=====
**P3-D0 probe (go/no-go "worth building" gate; read-only plus ≤ `CROSSING_VISION_P3_PROBE_CALLS` (120) Luna calls, decided
in the Phase 3 decisions below).** It is evidence that building is worth it, NOT evidence the runtime bar will pass: at
15/17 the Wilson 95 % lower bound is about 0.66; the runtime bar (0.90) is decided only by P3-D6.
0. **Retention check first:** list which of the 46 11-14 event clips and the recording segments for each E ± 30 s are
   still retrievable through the HA Frigate proxy; commit the fixture
   `quality/tests/fixtures/crossing_vision_door_eval_2026_11_14.json` (46 events: event id, camera, crossing key, tracker
   direction, human count, human direction or `unreadable`, confidence flag, pair id, `one_pass` / `round_trip` /
   `unknown` per pair) BEFORE any replay. Missing clips are listed and excluded, not replaced.
(a) **Volume:** 14 days of `egress_identity_outcome` per day: crossings, ambiguous, simulated calls with ambiguous
   included and clustering applied, crossings with camera peak ≥ 3, HA restarts per day, and the `memory_episodes` row
   count (for the P3-D5 index decision), and the busy-collision rate (crossings that would have found
   `MAX_CONCURRENT` calls in flight; review L4). Output: the cap (P3-D5 rule).
(b) **Direction + count replay** on the retained clips with the P3-D3 prompt, both routes (event clip at 4 and 8 frames;
   recording window if (c) passes). Gates: direction right on ≥ `CROSSING_VISION_P3_DIR_GATE_OK` (15) of the 17
   readable clips AND on ≥ `CROSSING_VISION_P3_DIR_GATE_TRACKER_WRONG_OK` (5) of the 6 tracker-wrong ones; else the
   direction part of P3-D3, P3-D6 and P3-D7 parks (card, revival: a new model or route re-run on the same fixture) and
   watching ambiguous crossings ships count-only. Group gate for P3-D2, on the 4 group clips and the false blank:
   undercount ≤ `CROSSING_VISION_P3_GROUP_UNDERCOUNT_MAX` (1) against the human count, where the human count is a pinned
   integer; the 18:59 clip (human "~9", low confidence) is re-counted frame by frame in step 0 and, if it cannot be
   pinned to one integer, is reported but excluded from pass/fail. Plus no new over-count on the 33 exact clips.
(c) **Route check:** one call with `video_file` = the recording proxy path; record whether llmvision fetches it (status,
   frames returned) and the recording segment lag (time from E + AFTER until the window plays).
(d) **Pass mechanism:** for the 21 opposite pairs and the 4 same-direction pairs of 11-14, the share sharing a pass
   event under BOTH rules: (i) `_match_event`'s group-wide pick, (ii) the Pass rule. **Negative set (review HIGH-1):**
   mine 14 days of `egress_identity_outcome` for opposite-direction crossings on one door group within `CLUSTER_S` whose
   Es are BOTH inside one Frigate event's [start, end]; hand-label each from its clip as `one_pass` or `round_trip`
   (committed in the fixture), mining back up to `CROSSING_VISION_PASS_MINE_MAX_DAYS` (30) days until enough are found.
   Gate for P3-D4 collapse and P3-D9b: at least `CROSSING_VISION_PASS_ROUND_TRIP_MIN_N` (20) hand-labelled one-event
   round trips; under rule (ii) ≥ `CROSSING_VISION_PASS_SAME_EVENT_MIN` (0.80) of `one_pass` pairs share a `pass_key`;
   and the Wilson 95 % UPPER bound of the share of labelled round trips that rule (ii) merges (the one-event residual)
   ≤ `CROSSING_VISION_PASS_ROUND_TRIP_MERGE_UB_MAX` (0.15). Why not 5: at n = 5 even 0 merges has an upper bound of
   ≈ 0.43, so 5 cannot show any ceiling near 0.10. Fewer than 20 = **HOLD**: P3-D4 ships with
   `CROSSING_VISION_LEDGER_PASS_COLLAPSE` False (the kill path; terms as today) and P3-D9b waits; the rest of Phase 3
   is not blocked. Report rule (i) beside it to show the selector bias,
   and the `end is None` share at resolution time. Also the interior near-door events around 14:17:23 / 14:17:54 (the
   audit's open falsifier).
(e) Re-run the 4 error clips once and record llmvision's error text.
- **Acceptance:** `AUDIT_crossing_vision_p3_d0_<date>.md`, one row per item with numbers and every gate verdict; the
  fixture committed first. Discriminates: a model that copies the tracker's bias scores ≤ 11/17 and 0/6; a selector
  artefact shows rule (i) sharing on round trips while rule (ii) does not.


=====
**P3-D2 event-centred frames and group frames (Tier 2; route and numbers from P3-D0 (b)/(c)).**
1. `CROSSING_VISION_FRAME_ROUTE`: `recording_window` only if P3-D0 (c) passed, else `event_clip` (today). The URL is
   `/api/frigate/<instance>/recording/<camera>/start/<E − BEFORE>/end/<E + AFTER>` where `<camera>` is the matched
   event's Frigate camera name from the event payload (`after.camera`, `crossing_vision.py:562`) and `<instance>` comes
   from the event's MQTT source / `discover_frigate_instance_ids` (`:543-548`) as `_clip_reference` does today; never
   from the egress stem or entity id (registry rule).
2. The call waits until `E + AFTER + CROSSING_VISION_RECORDING_LAG_S` (from P3-D0 (c)) so the window is complete; the
   existing `EVENT_END_WAIT_S` remains the outer bound.
3. **Fallback semantics (one call, always):** failures detectable before the call (no instance, no camera name, the
   window end not yet reachable inside the outer bound) use `event_clip` for that same single call. A fetch failure
   inside llmvision is an `error` row with the P3-D1 text; no second call.
4. Frames: `CROSSING_VISION_MAX_FRAMES` (4) normally; `CROSSING_VISION_GROUP_MAX_FRAMES` (8) when `camera_peak_count`
   ≥ `CROSSING_VISION_GROUP_PEAK_MIN` (3) or the matched event is longer than `CROSSING_VISION_LONG_EVENT_S` (60). One
   call. The branch is crossing-only (keyed on the crossing's `camera_peak_count` inside `crossing_vision.py`);
   `analyze_crossing_frames` keeps taking `max_frames` from its caller, so interior clip callers (VISION-INTERIOR
   D3 / D5) keep their own frame count.
5. Rows record `frame_route`, `frames_requested`, `pipeline_version`.
- **Tests:** `test_recording_window_url_centred_on_crossing`, `test_recording_url_camera_from_event_payload`,
  `test_group_peak_uses_group_frames`, `test_long_event_uses_group_frames`, `test_single_person_keeps_four_frames`,
  `test_precall_route_failure_uses_event_clip_one_call`, `test_fetch_failure_is_error_row_no_second_call`,
  `test_frame_window_stays_in_door_group`, `test_interior_caller_frames_unchanged`.
- **Mutation:** window from event start instead of E → `test_recording_window_url_centred_on_crossing`; camera from
  the stem → `test_recording_url_camera_from_event_payload`; drop the peak branch → `test_group_peak_uses_group_frames`.
- **Live:** within 2 days, ≥ 1 row with `frames_requested = 8` and `ok`; the P3-D6 scorer's exact rate on graded 3+
  crossings reported beside the 11-14 baseline (0 of 4). Discriminates: a change that only helped singles leaves 3+ at 0.


=====
**P3-D3 watch every crossing, record vision's direction (Tier 3: removes an INV-SCOPE clause, adds a production G3
writer).**
1. `_on_egress_event` accepts `ambiguous` while `CROSSING_VISION_WATCH_AMBIGUOUS` is True; same match, cluster, gates,
   cap. The row's existing `direction` key keeps the tracker's value (now possibly `ambiguous`; no new
   `tracker_direction` key); ambiguous rows have `camera_peak_count = None`.
2. Schema and prompt add `direction` ∈ {`in`, `out`, `passing`, `unclear`} from each person's first and last position
   against the door (prompt fixed by P3-D0 (b); `in` = goes into the building). Anything else = `unclear`.
3. **Per-member attributes (review M3).** The vision result describes the analysed event. Each crossing key in the
   request carries its `pass_key` from the bus event / record (P3-D9a; None before P3-D9a ships); `vision_direction` and `vision_people_count` = the result's values
   only if its `pass_key` equals the analysed event's id, else None; `direction_agreement` against the member's OWN
   tracker direction: `agree`, `disagree`, `vision_only` (tracker ambiguous), `unclear` (vision unclear / passing), or
   `not_analysed` (different pass). A real round-trip member never carries the primary's direction.
4. **G3 write.** At the release site (P3-D4 step 2; with collapse off, at the vision outcome), ONE
   `amend_crossing(hass, source_ref, {vision_direction, vision_people_count, direction_agreement}, None,
   camera=<egress camera>, role="vision_direction")` per crossing key; `source_ref` is built from the bus event's
   `egress_camera` and `timestamp` exactly as `transit_validator.py:2525-2527` builds it (`egress:<camera>:<iso>`), not
   parsed from `crossing_key`. A member that joins after its request's release is amended at join time with
   `not_analysed`. Wrapped in try/except, failures counted `vision_amend_failed`. Ring retention (1800 s / 32 per camera,
   `const.py:6707-6708`) exceeds the worst release time (E + 110 s hold, or outcome ≤ E + 45 + 120 + 90 s), so
   `crossing_record_aged_out` is not expected; it is counted, never retried.
5. **Contract and guard (reviews M4, B9, B10; closure MEDIUM-3; harmonization C7).** The build adds
   `vision_direction`, `vision_people_count`, `direction_agreement` (default None) to `CrossingRecord`
   (`transit_validator.py:946-971`) and to `_CROSSING_AMENDABLE_KEYS` (`:980-983`); `pass_key` is a creation-time
   `CrossingRecord` field added by P3-D9a and is NOT amendable. The contract §2.3 field list and §4.2 role list are
   amended once by the orchestrator for all Phase 3 and step-7 fields and roles (harmonization C7), so neither build
   edits the contract. NEW layer-guard row `('R13', 'crossing_vision.py',
   'CrossingVisionShadow._release_terms:amend_crossing')` (max 1; `amend_crossing` is already in `R13_CALLEES`,
   `_layer_guard_engine.py:154-157`) in `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py` beside the
   reserved fast-stage row (`:212`, unchanged). Guard change, as a DELTA against develop at merge time (never an absolute number; other ships move the
   totals, e.g. the music repair merge lowers them by 3): P3-D3 = +1 R13 row, `len(A.ROWS)` +1, `LAYER_ALLOWLIST_TOTAL`
   +1, `LAYER_ALLOWLIST_TOTAL_PROVISIONAL` +1, and the assertion in `test_person_awareness_layer_guard.py:62` set to the
   re-read values; the `("R13", 8)` floor (`:147`) stays valid. Each builder re-reads the current totals on develop
   when it merges. Only P3-D3 changes the totals in this plan (P3-D8, P3-D9a: 0 rows expected); the interior branch's
   delta is 0, so a merge after P3-D3 keeps P3-D3's +1 and never undoes it. The amended signal payload carries the record's
   `person_id` (`transit_validator.py:1281-1290`); today's readers (`sensor.py:5092`, `:5231`) act on
   `exit_backfilled` only; perimeter and sightings do not subscribe.
6. `pipeline_version` (rung-1 `CROSSING_VISION_PIPELINE_VERSION`) on every row; P3-D2 and P3-D3 each bump it.
7. Trip-wires: `crossing_vision_direction_zero` (≥ `CROSSING_VISION_DIRECTION_ZERO_MIN_OK` (10) `ok` rows in 24 h and none
   with `vision_direction` in/out → MEDIUM, RAM latch); `crossing_vision_ambiguous_zero` (≥
   `CROSSING_VISION_AMBIGUOUS_ZERO_MIN` (5) ambiguous bus events counted by the bus listener in 24 h, and 0 rows with
   `direction = ambiguous` → MEDIUM). Bus count, not `egress_identity_outcome` rows (rows and bus differ under dedup).
8. Arrival record and the rung-2 follow-up (P2-D9): an ambiguous crossing produces NO arrival record and no follow-up
   before P3-D7, whatever `vision_direction` says; after P3-D7 an ambiguous crossing with `vision_direction = in` is an
   entry for P2-D9.
- **Tests:** `test_ambiguous_crossing_gets_row_and_call`, `test_watch_ambiguous_off_restores_skip`,
  `test_ambiguous_row_peak_none`, `test_vision_direction_parsed_and_unclear_default`, `test_direction_agreement_cases`
  (5 cases), `test_round_trip_member_not_given_primary_direction`, `test_g3_amend_once_per_crossing_key` (incl. a late
  joiner), `test_g3_source_ref_from_bus_fields`, `test_g3_never_sets_direction` (record `direction`, bus and DB row
  unchanged), `test_amend_failure_counted_never_raises`, `test_amended_signal_ignored_by_exit_backfill_readers`,
  `test_ambiguous_member_in_cluster_no_term_under_tracker`, `test_ambiguous_primary_late_joiner_no_double_term` (B1, see
  P3-D4 step 4), `test_ambiguous_no_arrival_record_before_flip`, `test_direction_zero_pages_once`,
  `test_ambiguous_zero_counts_bus_events`, `test_pipeline_version_on_every_row`, layer guard green with the new row.
  Golden: every pre-existing row key (incl. `direction`) and the bus payload unchanged.
- **Mutation:** keep the old skip → `test_ambiguous_crossing_gets_row_and_call`; pass `direction` into G3 →
  `test_g3_never_sets_direction`; copy the primary's values to all members →
  `test_round_trip_member_not_given_primary_direction`; drop the latch → `test_direction_zero_pages_once`.
- **Live:** within 1 day with crossings: ≥ 1 row with `direction = ambiguous` and a `vision_direction`; `g3_calls`
  shows role `vision_direction`; `get_crossing(<source_ref>)` shows `vision_direction`; Persons Entered / Exited Today
  unchanged in definition. Discriminates: a build that wrote direction into the record would move those counts and the
  `person_entry_exit_events.direction` of a disagreeing crossing; this one moves neither.


=====
**P3-D6 direction scoring (Tier 2, read-only; lands in the D4 / P2-D6 scorer build and P2-D10 grading, neither built
yet).** Scored per PASS (`pass_key`; a pass contributes one scored row, review B12), not per member. Oracles, strongest
first: operator grade (P2-D10 grade actions gain `_in` / `_out` / `_pass`); a named resident's `person.*` edge, not_home
→ home in [E − `CROSSING_VISION_DIRECTION_ORACLE_BEFORE_S` (300), E + `_AFTER_S` (60)] = in, home → not_home in
[E − 60, E + 300] = out, with a name attached by F3 or the NVR on that crossing; the P3-D0 fixture. Interior-camera
timing is the tracker's own input and never an oracle. **The oracle never scores groups or guests** (a resident edge
names one resident; grades are capped per day): the bar measures single-resident crossings, and group direction
stays unmeasured until graded group crossings exist. Reports per door / day-night: vision accuracy with Wilson bounds,
tracker accuracy on the same passes, disagreement win rate, ambiguous coverage, the INV-DIR-GATE verdict, scored
passes per day. Disposition `AUDIT_crossing_vision_direction_disposition_<date>.md`, one verdict per direction source:
- **vision:** FLIP-READY (INV-DIR-GATE bar met) / HOLD (bar named, passes still needed at the measured rate) / PARK
  (bound below 0.90 at ≥ `CROSSING_VISION_DIRECTION_PARK_N` (150) scored).
- **tracker (closure MEDIUM-4):** TRACKER-READY when the tracker's own direction accuracy on scored passes has a Wilson
  95 % lower bound ≥ `CROSSING_VISION_DIRECTION_ACC_LB_MIN` (0.90) over ≥ `_SCORED_MIN_N`; else TRACKER-BELOW-BAR. The
  census F-LEAD needs FLIP-READY for vision or TRACKER-READY for the tracker, whichever source the ledger uses. With
  the tracker measured at 11/17 (65 %), TRACKER-READY is not expected, so in practice F-LEAD waits for P3-D7.
**Expected gate time (review G3):** about 5-12 scored passes a day (≤ 5 grades plus named resident edges at ≈ 44 %
attach): 30 scored in 3-6 days; ≥ 15 disagreements at the tracker's 35 % error needs ≈ 43 scored, 4-9 days; the 0.90
lower bound needs ≈ 60 scored at 97 % accuracy (about 1-2 weeks) or ≈ 150 at 95 % (about 2-4 weeks); below ≈ 92 % it
never passes. Sized by error rates; no calendar minimum.
- **Acceptance:** a scorer run on ≥ 1 day of Phase 3 rows writes every number above and reproduces the fixture's 11/17
  tracker accuracy on the 11-14 clips.


=====
**P3-D7 vision direction leads the ledger (Tier 3, gated; operator checkpoint).** A reviewed change of
`CROSSING_VISION_LEDGER_DIRECTION_SOURCE` to `vision` after FLIP-READY; bumps `pipeline_version`; post-flip trip-wire:
the rolling `GO_REGRESSION_DAYS` (14) direction bar below threshold → NM "revert vision direction". Named residual: a
one-event round trip (Pass block) becomes one term in vision's direction, `L` off by one until the anchor; its rate is
the P3-D0 (d) merge share.
- **Tests:** `test_direction_source_vision_uses_vision_direction`, `test_vision_unclear_falls_back_to_tracker`,
  `test_ambiguous_with_vision_in_gets_entry_term`, `test_direction_regression_pages_revert`.
- **Live:** after the flip, ≥ 1 term row with `direction_source = vision` on a `direction_agreement = disagree` pass
  whose term sign follows vision.


=====
**Phase 3 decisions (taken by the orchestrator 2026-11-15 on the recommended defaults; the operator may override).**
1. P3-D0 may spend up to 120 Luna calls on the replay.
2. A collapsed pass gives no ledger term until the direction gate passes (P3-D4 step 5, W9-W11 name the effect).
3. The 110 s term hold applies only to the ledger and awareness path; the arrival notification, the census trust view
   and AWAY are untouched.
4. The cap default is sized from the P3-D0 (a) volume probe.
5. EGRESS-TRACKER-DIRECTION-1 is filed now and sequenced (P3-D9a before P3-D4, P3-D9b after it), not parked.
6. **Operator-visible tradeoff (closure MEDIUM-4):** census F-LEAD now needs a direction verdict (P3-D6). The tracker is
   measured at 65 %, so in practice F-LEAD waits for P3-D7 (vision FLIP-READY, about 1-4 weeks of scored crossings
   after P3-D3). The operator may instead accept the tracker's signs for F-LEAD.
7. **Pending operator decision:** P3-D8, a stuck-excluded live input stops holding the anchor while a dead input still
   holds (recommended yes).
8. **M2 (taken by the orchestrator, operator may override):** the one-event round-trip gate needs ≥ 20 hand-labelled
   round trips (mined from up to 30 days) and a Wilson upper bound ≤ 0.15; below 20 the verdict is HOLD and P3-D4
   ships with collapse off rather than blocking Phase 3.

Tier: P3-D0 probe; P3-D1 Tier 1; P3-D2, P3-D6, P3-D8 Tier 2; P3-D5 Tier 2-DB; P3-D3, P3-D4, P3-D7, P3-D9 Tier 3 (ledger input
surface, a production G3 writer, the F3 source): two plan reviews incl. framing G, four code reviews, orchestrator
re-grep of every term-construction site (`cluster_terms`, `_release_terms`, `_ledger_terms`, `_join_cluster` late
branch, the no-request paths `:620-622`, `:676-707`, the call-time paths `:869-882`, `:906`, `:928`, `:935-939`) and a real
source mutation of the INV-DIR-GATE site, operator checkpoint before deploy.


=====
6. Phase 3, in order: P3-D0 probe (retention check and fixture first; gates the P3-D2 route, the P3-D3 direction part,
   P3-D4 and P3-D9b). P3-D8 (anchor honours stuck exclusion, operator yes pending) with its prerequisites S1, S2 (= P3-D8b) and S3
   (`PLANNING_stuck_sensor_truth.md`) before P3-D3, because without an anchor no ledger use of Phase 3 can be measured;
   S1 ships before P3-D8 is relied on. P3-D1 + P3-D5 any time. P3-D3 (direction first: it dominates the
   net, audit §3c) with P3-D2. **P3-D9a (tracker pass key) before P3-D4**, so the ledger consumes the one F3-owned key
   and never computes its own. P3-D4. **P3-D9b (tracker pass dedup) right after P3-D4**, gated on P3-D0 (d) incl. the
   round-trip merge bound. P3-D6 with the scorer build (P2-D10 grading built there, harmonization C10). P3-D7 only after
   FLIP-READY. The census plan's F-LEAD cannot promote before a P3-D6 direction verdict for the source in use (census
   plan §3.2, amended with this plan); the `pipeline_version` bumps in P3-D2, P3-D3 and P3-D7 each restart the census
   bars a-e and the F-LEAD windows. Phase 3 builds never change the `deconflict_house` signature (harmonization C2;
   interior ship 5 owns that).



## 2026-11-15 (plan-review fix-up of bca9fb65)

Review: `docs/reviews/code-review/plan_review_crossing_vision_bca9fb65_2026_11_15.md` (PLAN-FIX-REQUIRED, 3 HIGH,
9 MEDIUM, 6 LOW). All 18 fixed in place. What changed against bca9fb65:
- P3-D3 rewritten: ambiguous requests never adopt later resolved members (finding 3, recommended rule taken, so no
  residual share needed); `term_direction` late-joiner rule moved in from P3-D4 step 4 without the pass clause, with
  the `prim_dir` mutation (1); direction fields optional, never move `outcome` (5); both amend sites through
  `_amend_vision_direction` (14); repeat call on its own budget (`REPEAT_DAILY_MAX` 15, replaced `REPEAT_CAP_RESERVE`),
  never a primary's slot, sha1 selection, tracked task, `node_id vision-repeat:`, `call_kind` instead of `stage`, named
  readers (2, 4); guard notes restored (13c); `member_inherited` relaxation recorded (13a).
- INV-DIR-GATE gained the repeat clause and invalid / missing values; the source is now the rung-2 per-door-group
  option `CONF_CROSSING_VISION_LEDGER_DIRECTION_SOURCE` (was a rung-1 constant), missing key = tracker, ungrouped
  `stem:<stem>`, substitution at `crossing_vision.py:658-661` (7). INV-SCOPE names the repeat budget.
- P3-D2 fire time on the window route (6); group-count reasoning on both legs (8).
- P3-D0b I1 path truncated at E+45 s (10), coverage gated on own decisions at 0.50 (was 0.80 with fallback) plus bias
  controls (17); P3-D0d K2 two shares and the P3-D9c / fixes-table twin-pass claims narrowed to 30 s / 60 s (9).
- P3-D6: PARK on the Wilson upper bound, 150 kept as hard stop (11); per pass once a key exists, day / night, n per
  cell, signed net count error (13b, 8); front-door-dominated reps and realistic stability n (15, 16); the 15:12:14
  change re-described as across a `max_tokens` difference, not an identical repeat (15).
- P2-D2 step 3 and P3-D4 step 5 made consistent on the `vision` branch (13d). P3-D8 marked APPROVED (18).
- New decision 13: absolute vs relative direction bar, recommended relative for the ledger flip, absolute for F-LEAD.
- Census plan F-LEAD row (`PLANNING_census_deconfliction.md` rung 0) made per door group, P3-D9c added to the bumps (12).

## 2026-11-15: P3-D10 / P3-D11 operator direction designs added

Why: operator, 2026-11-15, verbatim: "Arriving: when we detect a door crossing we can go back in history and get clips
of the approach inside and outside the house. Alternatively we can treat motion near an egress door as an anticipatory
crossing and collect clips from/frames to check if it was a crossing. If it a crossing we look to determine direction
and if not discard". Every direction instrument had scored 13-14 of 17 on an agent-made answer key with at least two
doubtful labels (`AUDIT_crossing_vision_p3_d0bcd_2026_11_15.md`), so new instruments are scored only on operator labels
(CROSSING-GRADING-PAGE-1 → `crossing_operator_grades.json`).

Added in place (no text removed): P3-D0e probe → P3-D10 retroactive approach clips (INV-APPROACH-DARK); P3-D0f probe →
P3-D11 anticipatory crossing (INV-ONE-F3); P3-D2b named (no-frigate-event recovery on the recording route); decisions
14-16; §4 invariant pointer and an INV-SCOPE widening for P3-D10 only; §6 knob rows; §7 step 6.8; §8 non-goal
exceptions; tier line. Correction to the brief recorded in the plan: the 26 % `no_frigate_event` are tracker-resolved
crossings with no matched Frigate event (`crossing_vision.py:675-679`), not crossings the tracker missed.
