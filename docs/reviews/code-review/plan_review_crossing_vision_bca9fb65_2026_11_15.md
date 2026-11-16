# Plan review: crossing vision Phase 3 amendment (bca9fb65), Tier 3, 2026-11-15

Scope: `docs/planning/PLANNING_crossing_vision.md` at bca9fb65 against 50bffd62 (`git diff 50bffd62 bca9fb65`),
with `AUDIT_crossing_vision_p3_d0_2026_11_15.md` (runs 1 and 2) and the charter
`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Read only. Code claims were re-checked on develop bca9fb65.
`feature/crossing-p3-first` is NOT merged into develop (`git merge-base --is-ancestor` false), so the built P3-D1, D5
and D8 claims were not re-read. Reading disclosure: this review touches egress direction (F3) and the census ledger. I
did not read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` or `SENSOR_FLEET_CLASSES.md` for this pass. No finding below
depends on them; each finding cites the code.

**Verdict: PLAN-FIX-REQUIRED.** The direction of the amendment is right: build, record behind a closed gate, measure
per door, and add a deterministic second instrument. The fixes are spec gaps a builder would fill wrongly. Two are
HIGH: the ambiguous-primary late-joiner rule lives only in the parked P3-D4, and the repeat call is said to stay out
of every reader when it does not. None of the fixes changes scope.

## Ranked findings

| # | Sev | Framing | Finding | Fix in plan |
|---|---|---|---|---|
| 1 | HIGH | 1 + 2 | **The B1 late-joiner fix sits only in parked P3-D4.** P3-D3 lists `test_ambiguous_primary_late_joiner_no_double_term`, but the mechanism (`term_direction` stored on the request) is P3-D4 step 4, which is now parked. Today's code at `crossing_vision.py:741-746` sets `prim_dir = primary.members[0]["direction"]`. Once P3-D3 makes an ambiguous crossing a primary, `prim_dir = "ambiguous"`. Repro: ambiguous primary A at E; entry B folds in before release, so the term is +n_vision keyed on B; entry C joins late. `"entry" != "ambiguous"` gives C its own camera term, so the arrival is counted twice. The `prim_dir` mutation is listed only under P3-D4. | Move P3-D4 step 4 (without the `pass_key` clause) into P3-D3 as a step, with its mutation (`prim_dir` from `members[0]`). |
| 2 | HIGH | 1 + 2 | **The repeat call does not stay out of every reader.** The plan says the repeat is "never a term". It still reaches readers three ways. (a) Cap: the gate is `_calls_today + _waiting() >= cap` (`crossing_vision.py:693`). On a day with more than 83 primaries, repeats spend up to about 16 calls before the 10-call reserve stops them. Those primaries become `skipped_cap`, so their terms change from vision count to camera fallback (`crossing_ledger.py:166-169`). (b) Concurrency: the gate is `_pending() >= MAX_CONCURRENT` (`:700`). The plan does not say whether a repeat holds one of the 2 slots. If it does, primaries get `skipped_busy`, which P3-D0 (a) measured without repeats. If it does not, INV-SCOPE "in flight ≤ MAX_CONCURRENT" breaks. (c) Rows: no `node_id` is given (primary rows use `vision:{crossing_key}`, `:1007`), no `crossing_key` value, and `stage` is already taken by the fast-stage design (`stage = final / provisional`, plan line 221; `feature/crossing-vision-fast-stage` `crossing_vision.py:1025`). Node-keyed readers (`memory_query`), the trip-wire counts (`crossing_vision_zero`, error rate, `direction_zero` "≥ 10 ok rows") and any `stage != provisional` filter would count repeats. | Specify all of these: the repeat never takes a primary slot (it runs only when one is free and yields; otherwise it is skipped and counted); a repeat sub-budget the primaries never pay for, e.g. a repeat only when `calls_today + repeats_reserved < cap − projected primaries`, or simply `cap_for_primaries = cap` and repeats counted against a separate `REPEAT_DAILY_MAX`; `node_id = vision-repeat:{crossing_key}`; a distinct row key (`call_kind = repeat`) in place of overloading `stage`; and every row reader (trip-wires, scorer, rehydrate) names whether it includes repeats. Add the invariant clause "presence or absence of a repeat leaves every primary's outcome and term identical". Add a test that runs a full cap with the repeat rate at 0 and at 0.2. |
| 3 | HIGH | 1 | **Watching ambiguous crossings changes the terms of resolved crossings. The effect is not named.** After P3-D3, an ambiguous crossing becomes a request that claims the Frigate event (`match["analysed_by"]`, `:711`) and the 60 s cluster (`:666-672`). A resolved entry within 60 s now joins it. Before release, it takes the ambiguous primary's vision count. After release, it is a late joiner and gets a camera term (finding 1). Today it would have had its own vision call and count. INV-DIR-GATE still holds, because direction is not involved. But the Design-answers table and P3-D3 say the ambiguous count is "display only until P3-D7", and the shift for resolved crossings is not stated. | Name it as a residual with the measured share (P3-D0 (a) has the data: resolved crossings within 60 s after an ambiguous one on the same group). Either accept it or rule that an ambiguous request never adopts later resolved members (they open their own request). Add a test either way. |
| 4 | MEDIUM | 2 | **The repeat selection hash is under-specified.** A builder will likely reach for Python `hash()`, which is salted per process. Selection then changes across restarts and the test is flaky. | Specify `int(hashlib.sha1(crossing_key.encode()).hexdigest()[:8], 16) % 1000 < rate × 1000`, evaluated on the primary's `ok` outcome. The repeat is a tracked task started after `_record` and the G3 amend, never awaited by them, and cancelled in the teardown gather. |
| 5 | MEDIUM | 2 | **`direction` / `direction_confidence` parsing can move `outcome`.** If the builder makes either field required in the llmvision `structure`, a missing or out-of-enum value makes the reply `unparseable`. That changes `outcome` and therefore the term (vision count becomes camera fallback). This breaks INV-DIR-GATE exactly where the metamorphic test does not look, because the test permutes only valid values. | State that both fields are optional, that invalid or missing maps to `unclear` / None, and that they never change `outcome` or `people_count`. Extend `test_inv_dir_gate_metamorphic` with invalid and missing values. |
| 6 | MEDIUM | 2 | **Recording-window fire time is ambiguous.** Today the request waits for the Frigate event end (`:713-726`, up to `EVENT_END_WAIT_S` 120 s). P3-D2 step 2 says "waits until E + AFTER + LAG; EVENT_END_WAIT_S remains the outer bound". A builder will keep the event-end wait and add the lag, which leaves latency as it is. Or the builder will fire at E+25 on a `waiting` request while the event-end timer is still armed, which double-fires `_fire_request`. | On `recording_window`, fire at max(bus arrival, E + AFTER + LAG) without waiting for the event end, cancelling `req.unsub_timer`. Event end matters only for the event-clip fallback. Add a test that the request fires once at E+25 with the event still open. |
| 7 | MEDIUM | 1 | **The per-door-group source map is a rung-1 constant keyed by this install's door-group names.** That breaks portability (operator rule: "Portability is imperative"). It also leaves the key for an ungrouped stem undefined: `door_group` is None and `group_key = stem:<stem>` (`crossing_vision.py:646`). `cluster_terms` members carry no door group (`crossing_ledger.py:172-203`), so the builder must thread it through. | Key by the `CONF_DOOR_GROUPS` group key, falling back to `stem:<stem>`, with missing key = `tracker`. Put it on rung 2 (an options field per group, default `tracker`) and keep the flip as a checkpointed decision. Name the substitution site: the member dict built at `:658-661`, before `cluster_terms`. The INV-DIR-GATE mutation target is that one line. |
| 8 | MEDIUM | 3 | **The group-count use rule reasons from entries only.** "An undercount is absorbed by the anchor; an over-count on entry is a phantom guest" leaves out exits. An undercounted group EXIT (guests leave as 5 of 7) leaves L two high, which is a phantom guest until the anchor. The same group counted under on both legs cancels. The decision (vision alone, no max) still stands on the error totals (25/30 exact; max creates 3 over-counts to fix 1). | Restate the asymmetry with both legs, and have P3-D6 report signed net error per group visit (entry n − exit n) as well as exact rate. |
| 9 | MEDIUM | 1 | **The K2 and P3-D9c reach claims are overstated.** The source dedup is direction-keyed and per door group only when `CONF_DOOR_GROUPS` is set (`transit_validator.py:2394-2399`, `:2428-2438`), with a 30 s window (`const.py:3391`). P3-D0 pairs sit 17-58 s apart. A right direction makes pairs 30-58 s apart one ledger term (same-direction cluster, 60 s). For every other reader (notify, entered / exited, DB) they stay two same-direction events. | P3-D0d K2 reports two shares: within `DOOR_STEM_DEDUP_S`, which fixes every reader, and within `CLUSTER_S`, which fixes the ledger only. Soften "removes most twin passes" in P3-D9c. |
| 10 | MEDIUM | 1 | **P3-D0b I1 must score the track available at resolution time.** P3-D9c decides at E + ≤45 s, but Frigate events run 5-466 s, so the stored final `path_data` is not what the tracker will have. Scoring on the stored path overstates P3-D9c. | Truncate each path to points with timestamp ≤ resolution time (E+45) before scoring I1. Report the share of crossings whose path is still open at resolution. |
| 11 | MEDIUM | 3 | **The PARK rule is sized by n, not by error.** PARK needs LB < 0.90 at ≥ 150 scored per door group, which is about 25-50 days at 3-6 per group per day. At the measured 76 %, a Wilson 95 % UPPER bound below 0.90 shows "cannot reach the bar" at about n ≈ 35-45. The charter wants gates sized to error rates. | PARK when the Wilson 95 % upper bound is below 0.90 at ≥ `SCORED_MIN_N`, and keep 150 as a hard stop. Same for stability (UB < 0.80). |
| 12 | MEDIUM | 1 | **Census plan seam drift.** The census F-LEAD row (`PLANNING_census_deconfliction.md:74`) is still house-wide, not per door group, and its bump list names P3-D2, D3 and D7 but not P3-D9c. This plan says the census plan is "amended with this plan", but that file is not in the diff. | Amend the census F-LEAD row in the same commit: per door group, FLIP-READY or TRACKER-READY for that group's source, with P3-D9c added to the bumps. |
| 13 | LOW | 1 | **Dropped without a note.** (a) `test_round_trip_member_not_given_primary_direction` and its mutation were replaced by "members may inherit; the scorer counts `member_inherited`". That relaxation is defensible with no pass key, but it is not recorded as a deliberate change. (b) P3-D6 "scored per PASS (review B12)" became "primaries only", and the day/night split was dropped. (c) The guard text lost "the `("R13", 8)` floor stays valid", "only P3-D3 changes totals" and the reserved fast-stage row note. Live totals today: `LAYER_ALLOWLIST_TOTAL` 256, `_PROVISIONAL` 259, `len(ROWS)` 228 (`test_person_awareness_layer_guard.py:62`). The +1 delta is still right. (d) The P2-D2 step-3 cluster rule lost "under `vision` it takes vision's direction", while P3-D4 step 5 keeps it. | Add one line each, restore day/night in P3-D6, and make the P2-D2 step 3 and P3-D4 step 5 texts consistent. |
| 14 | LOW | 2 | **Guard row max 1 with two amend sites.** P3-D3 amends at the outcome and at late join. | Both go through `_amend_vision_direction`. Say so, or the late-join call in `_join_cluster` adds an unlisted row. |
| 15 | LOW | 1 | **The stability baseline is overstated.** "One flip between identical calls": 15:12:14 run 1 used `max_tokens` 1500 and run 2 used 4000, so the inputs were the same but the calls were not. "16/17 agreement" counts across that difference. Also, at n = 20 the 0.80 lower bound needs 20/20 (19/20 gives about 0.76), so "20 repeats in ≈ 4 days" understates the clock. | Reword. State realistic n (about 35-40 at 95 % agreement). |
| 16 | LOW | 3 | **The reps estimate assumes a 50/50 split.** 15 of the 17 readable clips and all 6 tracker-wrong clips are front-door (fixture `door_group`). All 4 vision misses are front (11/15 = 73 %); garage is 2/2. Per door, the front door does not rescue vision. The garage has too few scored crossings to say. | Use the measured per-group volume. Expect the front to be the binding group. |
| 17 | LOW | 1 | **The P3-D0b coverage gate is vacuous for I5.** I5 falls back to the tracker, so coverage is ≥ 81 % by construction. | Gate the instrument's own (non-fallback) decided share. Freeze the door polygons before seeing the labels: the plan commits them before scoring, which is good, but also keep the labeller blind. Note that choosing the best of about 6 instruments on n = 17 inflates the result. P3-D6 is the guard against that. |
| 18 | LOW | stale | **P3-D8 is shown as pending** (header "operator yes still pending", decision 7, and the knob row "True after operator yes"). The operator approved it ("Door vision stuck sensor - yes"). | Mark it approved and set the knob default to True. |

## 1. Completeness and equivalence (arc rule 5)

**Dropped from 50bffd62.** Every removed line was reviewed. Removed and justified: the old P3-D0 spec (moved to the
archive, results table in its place); the P3-D2 peak branch (replaced by 8 frames, with the evidence); P3-D9a gated on
"reported" (now parked, reason stated); the P3-D4 build (parked, with its spec kept). Removed silently: finding 13 (a-d).

**Claims re-grepped (all hold except where noted).**
- The `path_data`, `entered_zones`, `current_zones`, `velocity_angle` and `average_estimated_speed` keys are in
  `after` of `quality/tests/fixtures/frigate_events_mqtt_live.json`. HOLDS. `path_data` is a list of `[[x, y], ts]`.
- 0 hits for `path_data` / `velocity_angle` in `custom_components/`. HOLDS. `entered_zones` is read in
  `perimeter_alert.py:4530`, `:5001-5021`. HOLDS.
- Ring entry keeps none of the track fields (`crossing_vision.py:575-580`). HOLDS.
- 30 s same-direction dedup (`transit_validator.py:2428-2438`, `DOOR_STEM_DEDUP_S` 30 `const.py:3391`). HOLDS, with
  two caveats: it is door-group-scoped only when `CONF_DOOR_GROUPS` is set (`:2394-2399`), and it also dedups
  `ambiguous|ambiguous`. See finding 9.
- No cross-camera track id. HOLDS: the `after` key set is per-camera `id` only (no global or re-id field).
- G3: `direction` is forbidden (`transit_validator.py:977-979`). The four new keys are absent from
  `_CROSSING_AMENDABLE_KEYS` (`:980-983`), so the build adds them; `attach_crossing_attribute` raises on unknown keys
  (`:1074-1076`). `amend_crossing` takes a free `role`. `R13_CALLEES` includes `amend_crossing`
  (`_layer_guard_engine.py:154-157`). The guard +1 delta is correct against today's 256 / 259 / 228.
- Amended-signal readers act on `exit_backfilled` only (`sensor.py:5092`, `:5231`). HOLDS.
- The tracker reads no contact (no `contact` hit in `transit_validator.py`). HOLDS.

**INV-DIR-GATE.** It is falsifiable as written: permute `vision_direction` and confidence, and diff the term stream and
`L`. It is buildable against `crossing_ledger.py`: the ledger is direction-blind except for `m["direction"]`, so the
gate is one substitution where the member dict is built (`crossing_vision.py:658-661`). Three conditions:
- Door group has to be threaded through and the ungrouped key defined (finding 7).
- The permutation has to include invalid and missing values (finding 5).
- The invariant has to gain a repeat-presence clause (finding 2).

**Repeat row out of every reader.** NO as specified; see finding 2.

## 2. Build-prediction

What the builder will most likely get wrong, in order:
1. The ambiguous-primary late joiner (finding 1). The test is named but its mechanism is parked.
2. The repeat call holding a concurrency slot, its cap accounting, `node_id` and the `stage` collision (finding 2).
3. Repeat selection by `hash()` (finding 4).
4. Recording-window fire time: either a double fire with the event-end timer, or keeping the event-end wait (finding 6).
5. `direction_confidence` made a required schema field (finding 5).
6. The source map keyed by a hard-coded group name, with no stem fallback (finding 7).
7. 8 frames against the 90 s timeout. Acceptable on the window route: 20 s clip, 10.9 s measured; run 2 median 12.7 s.
   The 86.6 s tail is an event-clip artefact, and step 3 routes long events away from it. Residual risk: the P3-D0c
   fail branch keeps the event clip for events ≤ 60 s, and an unmeasured 60 s, 8-frame clip at 4000 tokens could
   approach 90 s. Have P3-D0c report latency for its clips longer than 40 s.
8. The scorer's per-confidence report has to exclude repeat rows and inherited members, and report n per cell. Without
   that, "high is better" will be read off cells of 2-3.

## 3. Framing G (charter goals)

- **"Is vision counting well" (the central question).** Partly served. Counts are scored on graded 3+ crossings only
  (≤ 5 grades a day), so the group answer is slow. Add signed net error per visit (finding 8). Run P2-D7 (the staged
  group walk) early: it is the only fast group oracle.
- **"We need reps."** Delivered. Direction is recorded on every crossing, ambiguous ones included, with stability
  repeats and per-door scoring, and a deterministic second instrument (P3-D0b) is measured beside it. That learning
  has value even if vision never flips. The realistic outcome on the data: front-door vision is at 73 %, below the
  0.90 bound, and actuation of direction will come from P3-D0b / P3-D9c or not at all. The plan says this honestly in
  the 76 % note. The early-park rule (finding 11) keeps reps from becoming a quiet multi-month soak.
- **Bar sized from error rates, not calendar.** The flip bar is (Wilson LB). The PARK rule is not (finding 11).
  - Open question for the operator: the bar is absolute (LB ≥ 0.90), but the ledger's counterfactual is the tracker at
    65 %. A relative bar would let a door flip at about 85 %: vision's LB above the tracker's UB on the same crossings,
    plus the existing disagreement-win ≥ 0.80. That would materially improve the ledger.
  - The plan's argument for 0.90 ("a wrong sign moves L by n until the anchor") applies equally to the tracker it
    keeps.
  - Recommend that the operator decide between the two bars. Neither choice breaks a hard constraint: AWAY reads the
    trust view only.
- **Vision count alone for groups.** Right on the evidence; see finding 8 for the reasoning fix.
- **Operator questions and defaults:**
  - P3-D0c 14 calls: yes.
  - Staged round trips: yes, but only after P3-D0d K2 is scored, since K2 may remove the need.
  - Frigate threshold zones (I2): worth asking now. It is a homelab config change with no URA code and it makes I2
    scorable.
  - Accept the tracker's signs for F-LEAD: no, at 65 %.
  - 8 frames everywhere: yes.
  - Group rule, vision alone: yes.
  - Repeat rate 0.2: yes, once finding 2 is fixed.
  - P3-D8: stale, already approved (finding 18).

## Summary

| Severity | Count |
|---|---|
| HIGH | 3 (1, 2, 3) |
| MEDIUM | 9 (4-12) |
| LOW | 6 (13-18) |

Must fix before build dispatch: 1, 2, 3. The MEDIUM findings are fixed in the plan text in the same pass; the LOWs are
one-line edits. Bug classes: #53 computed-but-not-consumed / one missed site (findings 1 and 3: a rule left in a parked
deliverable), shared-budget side effects (2), untracked background task (4, the repeat task), and coincidental equality
masking a concept split (`stage` overloaded by the fast-stage and repeat designs, 2c).
