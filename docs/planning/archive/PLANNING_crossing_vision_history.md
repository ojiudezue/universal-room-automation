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
