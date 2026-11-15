# Plan review: interior vision sightings, closure re-review (Tier 3 plan gate), 2026-11-15

Plan: `docs/planning/PLANNING_vision_interior_sightings.md` at adee0d3a (develop). History:
`docs/planning/archive/PLANNING_vision_interior_sightings_history.md` (draft 2 verbatim). Prior reviews:
`plan_review_vision_interior_completeness_2026_11_15.md` (C1, H1-H5, M1-M7, L1-L3) and
`plan_review_vision_interior_buildpred_G_2026_11_15.md` (B1-B14, G1-G8). Read only; the plan is not edited.

Code checked: `feature/layer-ship3b` @ 5d8b831d for 3b symbols, develop for the rest, 921c9c47 for P2-D8, the live
registry (`.storage` on the Samba mount) for the interior camera areas and room types. Presence and identity docs were
not re-read in full for this pass; no finding rests on a sensor-class or ledger claim. HVAC is not touched.

**Verdict: PLAN-FIX-REQUIRED.** 0 CRITICAL, 1 HIGH, 9 MEDIUM, 8 LOW. All 39 prior findings are closed or properly
answered, but the HIGH is a one-sentence fix in §8. The MEDIUMs are mostly under-specified rules that a builder
will fill in wrongly, plus one silent drop (the periodic head count). The fixes are text edits of about an hour; nothing
structural changes. Two operator questions are open (§5).

## 1. Closure of prior findings (verified by grep, not by the plan's table)

| Finding | Verdict | Evidence |
|---|---|---|
| C1 / B1 | CLOSED | §6.1-§6.2 conformance table; `_emit_unnamed` on `PersonSightingProducer` matches contract :141 / :394; 0 code hits for `_emit_unnamed` today (NEW, correct) |
| H1 | CLOSED (new defect N2) | `deconflict_house(..., extra_guest_terms=)` `census_deconflict.py:90-131`; pull at `_compute_awareness` `camera_census.py:6911-6948`. The truth table matches the function: `vis = max(present terms)`, `aware = vis if vision_leads else guest_cam` |
| H2 | CLOSED | guard structures in §6.3 all exist (`_layer_guard_engine.py:42, 93, 138, 162, 174, 182, 187, 207`); `persons_in_room` is already on READ_LIST PC (`:95`); `LAYER_ALLOWLIST_TOTAL = 259` (`allowlist_PROVISIONAL.py:26`) |
| H3 | CLOSED | `entity_stream_view` `camera_stream_health.py:1201`, `physical_camera_dead` `camera_twin_health.py:1165`, `interior_camera_entities` `camera_census.py:2706` |
| H4 | CLOSED | `persons_in_room(room, active_only=True)`; `TRACKING_STATUS_ACTIVE` `const.py:206` |
| H5 / G1 | CLOSED (L-1 reuse miss) | §8 frame-source interface; `analyze_crossing_images` at 921c9c47 `perimeter_enrichment.py:461` takes `image_entities`; `analyze_crossing_frames` `:360` takes `video_file` / `event_id` |
| M1 | Partial rejection UPHELD | `test_away_tick_identical_with_vision_payload` is at `quality/tests/test_census_trust_golden.py:70` on develop and 5d8b831d, committed 921fb0b7 on 2026-11-14 00:13, before the completeness review. That review's "0 hits" was wrong. The placement half of M1 is closed (§9.D1, own timer). See L-6 for the new golden variant |
| M2 | CLOSED (new defect N3) | §7 record rule |
| M3 | CLOSED | Spot-checked 35 cites on 5d8b831d; all match |
| M4 | CLOSED | D0(a) asserts interior key = `canonical_camera_key` (`camera_resolver.py:507`, min device id) = path-map node key |
| M5 | MOSTLY CLOSED | All gate and bar numbers are named (§12). Still open: `describe_person` / NM `describe` has no cooldown of its own, and `interior_frames_left` has no off value (L-4) |
| M6, M7, L1, L2, L3 | CLOSED | §9.D3, §9.D5, §9.D7, §6.3, §8 |
| B2 | CLOSED (new defects N4, N5) | partition formula in §9.D4 |
| B3 | CLOSED | Recomputed the Wilson UB: n=100 at 99 % exact gives UB 0.0545, w 0.272, interval 13 213 s; at 80 % w = 1. The plan's numbers are right |
| B4, B6, B7, B8, B10, B11, B12, B13, B14 | CLOSED | B7: live registry. All 7 interior camera devices have areas that map to URA rooms (game_room, master_hallway, garage_hallway, foyer, living_room, upstairs_hallway, stairs). None has an excluded type. B13: `log_memory_episode` is a direct insert (`database.py:10686`, `async with self._db()`) |
| B5 | CLOSED; it is now an operator question (Q1) | One flag. Interior moves `aware_guests` only once the crossing ledger leads |
| B9 | CLOSED for getters; new hollow risk L-3 (affect) and L-5 (store drill) | |
| G2 | CLOSED | switch ON, renamed "Interior Vision", options-flow default, stored state wins |
| G3 | CLOSED (arithmetic slip L-2) | bar counted from D0 + D7, no day floor |
| G4 | CLOSED | affect ON, recorded (card `operator_2026_11_15_emotion`) |
| G5 | CLOSED in text; see N4 and Q1 for whether the term can deliver | |
| G6, G7, G8 | CLOSED | D6 trigger is interval-based; W2 only gates the D4 flip |

**Seams.** `persons_in_room` does not exist on develop or 5d8b831d (only `get_persons_in_room`
`person_coordinator.py:2498`). `analyze_crossing_images` does not exist on develop; it exists only on
`feature/crossing-vision-fast-stage` 921c9c47, which has not merged. Both "first to build owns it" seams are sound. They
pin the signature (contract §2.4a and 921c9c47), and the second builder rebases. One gap: contract §2.4a does not
define `active_only` or the return type, so "exactly per contract" leaves both open (L-7).

## 2. New findings (build prediction on the rewrite)

### HIGH

**N1. A vision sample can read a dead Frigate leg's frame while the live Protect leg carries the record.** §8 picks the
still source as the Frigate member only (`frigate_member`-style rule). §7 lets a LIVE Protect member carry the record
when the Frigate member is held, released or has no reading. Neither §8 nor §9.D2 says that the sampler skips a group
whose Frigate member is not LIVE. Repro: Frigate person sensor for `family_room` held (stream dead), Protect binary
live and on, so `bodies_nvr` = 1 and the steady-state trigger fires. `call_model` fetches `camera.family_room`'s
`entity_picture`, which is stale or frozen. The vision count replaces the live NVR count (`bodies_source` vision) for up
to `INTERIOR_VISION_TERM_MAX_AGE_S` (600 s). After the D4 flip it feeds the term. This contradicts the operator's "a
dead camera is ... faulty equipment" (charter 2026-11-14). Fix (one sentence in §8 and a test in D2): sample only when
the still-source member is LIVE by §7, otherwise skip with reason `still_source_not_live`. Test:
`test_no_sample_from_non_live_still_source`.

### MEDIUM

**N2. With admission on, the interior term defeats the census's case-D fallback.** `deconflict_house` takes the max of
the present terms and sets `aware = vis` when leads (`census_deconflict.py:105, :117`). The interior term covers only 7
shared spaces, so it is a lower bound, but once present it stands in for the whole-house estimate. Repro: ADMITTED True,
LEADS True, crossing ledger unhealthy (`vis` ledger None), `guest_cam` = 2 (guests in a room with no interior camera, or
held), all interior groups LIVE and empty, so interior = 0. Then `aware_guests` = 0, where develop gives 2. The §9.D4
truth table row "True / True → max(ledger, interior)" hides this. The D4 bar (per-group exact) cannot catch it. Fix:
state the rule. Recommended: `_interior_tick` passes the interior term only when the ledger term is present, or as
`max(interior, guest_cam)`. Add a truth-table row for ledger None and a test.

**N3. `area_evidence()` cannot give "each LIVE member's platform reading" as §7 specifies.**
`_last_area_contributions` is per AREA, not per member (`camera_census.py:2140-2172`). It merges held readings
(`_held_value`) and skips watchdog-discounted cameras. A binary-only area is written as
`{"max_count": n, "platform": "binary"}`, not `binary_seen`. A builder who reads "Frigate `max_count`" will take a
Protect reading as Frigate. The per-member reading needs one interior camera per area, which holds on the live registry
today (7 distinct device areas) but is not asserted. Fix: have `area_evidence()` copy the per-entity last readings
(`_stream_last_reading`, `camera_census.py:2812`) keyed by entity, or state the (area, platform) shape and add "one
interior group per area" to the D0(a) assertions.

**N4. The static-scene rule, as written, may leave vision corrections almost no lifetime, and §8a and §9.D2
disagree on its scope.** §8a and §9.D4(d) say a vision count expires when ANY interior group's `bodies_nvr` changes.
The D2 Verify says "that group's NVR changes". The walk-through test needs ANY. With 7 cameras and noisy counts, ANY
may expire every correction within seconds, so D2 corrections and the D4 term rarely carry vision (G1, G5). It is also
unspecified whether a Protect 0/1 flicker counts as a change. Fix: one definition (ANY, with a debounce knob), and D0
measures the median time between interior count changes across all groups. That number decides whether vision
corrections live long enough to matter. Put it in §15.

**N5. A resident's slug can be subtracted in two partitions.** §9.D4(e) says "each slug in the one partition that
places them", but `named` per room is the BLE room ∪ fresh faces (≤ 300 s). BLE and a face can place one slug in two
rooms at once. Repro: Ezinne BLE in Living Room (family_room camera); her interior face sighting on the staircase 200 s
ago; one guest on the staircase. Staircase gives bodies 1, named {ezinne}, unnamed 0, so the guest is missed. There is no
tie-break rule. Fix: one placement per slug (BLE ACTIVE wins, else the newest face), applied before the per-room union,
with a test.

**N6. D5 hop windows are not cumulative along the chain.** Live `interior_paths.json` (garage_a) chains the edges
garage_a → staircase (63 s) → stairs_top (72 s) → playroom (67 s) / upstairs_hall (84 s), with staircase → family_room
at 85 s. §9.D5 opens each hop at `E + window_s` and closes the record at the largest window + pad (E + 100 s). A guest
reaching the playroom around E + 200 s is never a hop, so the path record stops at the first one or two cameras. Fix:
window per hop = previous hop's first on-edge (or the cumulative lag) + `window_s`, close at the cumulative max + pad,
with a test on the live chain shape.

**N7. Affect has an unnamed consumer risk and a hollow test.** §9.D3 does not say whether the NM reply text includes
affect. If it does, NM is an affect consumer, which contradicts "no consumer yet". `test_affect_has_no_reader` ("guard
pin") has no mechanism: `PINNED_READERS` pins method calls, not record fields (#62). Fix: the reply excludes affect
(stated and tested), and the guard forbids attribute reads of `.affect` outside `person_sighting.py` /
`interior_vision.py`, with a red drill.

**N8. No authorization rule for `describe`.** Requester = any resolved NM person. Any household member (or a guest
with an NM phone) can ask what another person is doing, mood included, through cloud inference. The operator named
privacy as "the main objection". Fix: route through the existing `_is_authorized_to_ack`-style gate with a knob
(default: operator only), or record it as an operator question.

**N9. Sampling can use up the daily cap that describe-on-demand needs.** D2 steady state across 7 groups at w = 1 can
reach about 160 calls a day against a cap of 60, so an operator `describe` can get "limit reached today". Fix: a
reserve knob (`INTERIOR_DESCRIBE_RESERVED_CALLS`, rung 1), or a separate describe cap.

**E1 (equivalence). The periodic head count direction was dropped silently.** Draft 2 §10 kept "Periodic
fixed-interval head count (sighting plan §15.8): D2's background sampling covers it; revival if the crossing ledger's
bar a fails twice. Asked, not assumed", and §12 carded it. The rewrite has 0 hits for "head count" or "15.8", no non-goal
and no card. That breaks arc rule 4 (no silent deferral). Fix: a §13 line or a card with its trigger.

### LOW

- **L-1.** §8's still-source rule re-describes `frigate_member` (`camera_stream_health.py:880`, 3b) plus
  `own_camera_entity_for_device` (`:744`). Mark it REUSE in §5 so a second implementation is not built.
- **L-2.** §9.D4 "0 of about 120 clears" the 0.03 false-guest UB is wrong. Wilson UB for 0/n = z²/(n+z²) = 0.0310 at
  n = 120. It needs n ≥ 125. A test written from the plan text will fail.
- **L-3.** D7 grades "disagreements first" bias the pooled exact rate low. That is conservative for the LB bars but
  should be stated, or stratified.
- **L-4.** M5 residue: no NM `describe` cooldown, and no off value for `interior_frames_left`.
- **L-5.** Drill `[iv_direct_store_write]` must use a non-`self` receiver (`producer._room_sightings[...] =`). The R7
  check skips `self.` writes (`_layer_guard_engine.py:922-925`), so a `self._room_sightings` sibling store inside the
  sampler stays GREEN. State it.
- **L-6.** The golden test's self-check `else` branch (`test_census_trust_golden.py:104-105`) asserts `aware ==
  unidentified_count`. The new `interior_admitted_5_lead` variant fails unless it gets its own branch. Name it. Also,
  pins must be (module, qualname). "The presence delegate" for `get_room_sightings` / `get_last_path_records` is
  missing from the pin list, so the delegate itself trips the guard.
- **L-7.** Seam: state `persons_in_room` returns person names and that `active_only` = `tracking_status ==
  TRACKING_STATUS_ACTIVE`. Contract §2.4a defines neither.
- **L-8.** Equivalence residue, each unrecorded: 1-3 frames per call became one still (`INTERIOR_VISION_MAX_FRAMES`
  dropped; D0(c) compares 1 frame vs clip, not 1 vs 3 stills); the D5 vision trigger "or guests_unnamed ≥ 1" was
  dropped; `describe_person`'s last-named-sighting fallback was dropped; "security use: D2 p90 ≤ 15 s" was dropped;
  §14 lost the sighting-layer §15.8 / §15.9.4 and census §3.6 edits. Also, §8c "built and pulled only after admission"
  contradicts §8a / D4 Live (term computed into diagnostics at ship). Reword to "pulled only after admission". The D3
  background task needs tracking and teardown cancel, as D2 has.

## 3. Goal fidelity (framing G)

| Operator said | Plan | Drift |
|---|---|---|
| "Is Vision working as designed is the central question. Starting with the door crossing version" | D0(b)/(c) and D7 measure interior counting; the scorer pages | MEDIUM: the labelling budget is not sequenced. D0 needs 210 interior frames plus 20 a day, against the one weekly run that door grading also needs. The operator put door first. Say that interior grading never delays the door set, or ask |
| Naming unenrolled people is a non-goal | §13 bullet; INV-IV-NO-NAME | none |
| "Emotion yes as prep" | affect ON, recorded, no consumer | none (N7 is a build risk, not a drift) |
| Supplement counts (G1) | D4 needs the shared LEADS flag | Risk reduction changes delivery: interior cannot move `aware_guests` until the crossing ledger is promoted, even if interior meets its own bar. The plan surfaces this as a question but does not put it to the operator (Q1). N2 and N4 bear on the same goal |
| Tight, not deferred | ship order D0+D1 / D3 / D2 / D5 / D4; switch ON | none, except E1 |
| Clips | §8 clip route, knobs default False until D0(c) | none |

## 4. Equivalence (arc rule 5)

The plan is one clean document; the history file is labelled not-a-spec. Every draft-2 deliverable D0-D7 is present.
Losses: E1 (head count, MEDIUM) and L-8 (small decisions). The "value per deliverable" margin table (draft 2 §5) is
gone. Its content is partly in §3 / §8c. LOW, no action needed beyond L-8.

## 5. Open operator questions

- **Q1 (from B5 / G5).** Interior can move the awareness guest count only after the crossing ledger is promoted to lead
  (one shared flag). Accept that coupling? Or should interior be able to lead on its own bar? That needs a second
  leads argument on `deconflict_house` (a census-plan signature change, Tier 3).
- **Q2 (N8).** Who may ask URA to `describe` a room or a person? Recommended: the operator only by default, with a
  knob.
- (If not answered in the text) the labelling budget: does interior D0 grading wait for, or share, the door-crossing
  labelling run?

## 6. Must fix before approval

N1; N2 (rule + truth-table row + test); N3; N4 (one definition + D0 measurement); N5; N6; N7; N9; E1; L-2. N8 and Q1
go to the operator. The remaining LOWs are fixed in the same edit.

## Summary

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 9 (N2-N9, E1) |
| LOW | 8 |

Bug classes: dead equipment used as signal (N1), concept split (#63: partial-coverage term as whole-house estimate N2;
area vs member granularity N3), one-missed-rule (#53: N5 placement tie-break, N6 cumulative window), hollow anchor (#62:
N7, L-5), silent deferral (E1).
