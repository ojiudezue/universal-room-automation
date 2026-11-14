# PLANNING: NVR witness layer (one record of which NVR saw a person, where and when; policy stays with each feature)

Card: NVR-WITNESS-CONSOLIDATION-1 (batch person-sightings, parent VISION-CROSSING-ANALYSIS-1). Plan amendment for the
operator, 2026-11-13. One clean doc; nothing here edits another plan (edits other plans need are in §11).
Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Arc map: `ARC_identity_vision_census_map.md`.
Read for this plan: the card (every field), `AUDIT_protect_clip_witness_probe_2026_11_13.md`,
`AUDIT_protect_face_name_interfaces_2026_11_13.md`, `AUDIT_frigate_face_name_latency_2026_11_13.md`,
`AUDIT_crossing_vision_d0_2026_11_13.md`, `PLANNING_camera_input_stream_health.md`, `PLANNING_crossing_vision.md`,
`PLANNING_census_deconfliction.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1-§5.5, the ura-arc skill, memories
`reference_pooloverhead_four_integrations`, `reference_frigate_ghost_evidence_chain`. HVAC and presence state-of-play docs
were not read: this plan changes no HVAC or room-occupancy path. A builder of W5 (census reads) reads the presence doc first.

## 1. Charter, operator words, and the goal

Operator, verbatim: "For all camera work I like to exercise both nvr platforms simultaneously, then cross compare to
reduce errors... How can protect be a separate witness? ...centralize the rules to deconflict to increase confidence."
"I generally favor consolidation so there's no drift and there is one place to make better... Bring me a plan amendment
but it's not necessary to disturb what's in flight. ...check to see if the protect mechanics will allow easy
implementation." On the per-camera agreement record: "Critical for learning. Has to be baked into the design. Note this."

Charter goals served: "Vision is to assist census accuracy. And assist arrivals accuracy... Especially when combined with
facial recognition from the nvr systems"; "guests should be both vision and frigate/protect person counts with
deconfliction"; settings "help with accuracy (first)". Hard constraint honoured: "I need away to be fast acting" (nothing
here touches AWAY or house state).

Goal: one shared evidence layer that records every Frigate and Protect person fire per physical camera, keeps a
per-camera agreement history learned once and persisted, classifies NVR family in one place, and gives crossing vision
Protect as a real second witness. Each feature keeps its own decision.

### 1.1 Critique of "centralize the evidence, keep policy per feature"

For full consolidation: one place to improve, no drift in windows or classification (today: no window / 10 s / 60 s, and
three meanings of "agree", probe Q5). Against centralising the decisions too: the three sites answer different questions
(census: how many bodies now; transit: did two NVRs see this crossing; perimeter: should a lone first alert be demoted),
serve different consumer classes (display vs security de-escalate), and a single policy edit would move all three at
once, the opposite of a safe migration. The middle this plan takes, which goes further than my first answer: the
evidence, the family classifier, the agreement history AND the corroboration predicate itself
(`corroborated(cam, t, window_s)`) live in one module; each consumer supplies only its window and what it does with the
answer. All windows become named knobs in one const block, so drift is visible in one diff.

## 2. F1-F5 and consumer classes

Produces F3/F4 evidence, not an identity fact: "NVR family X saw a person on physical camera C at time t" (event-level
evidence under F3 crossings and F4-shaped sightings). It names no one, attaches no identity, writes no F2.

| Reader | Uses | Class (manual §5.5(b) / arc map) |
|---|---|---|
| Transit crossing confidence (`transit_validator.py:2165`) | `corroborated(cam, t, 10)` | display (DB/bus `confidence`; no decision reader found by grep, re-verify at plan review) |
| Perimeter single-source demote (`perimeter_alert.py:4924`, line moved from 4780 since Part A) | families fired, families live, agreement rate | security (severity de-escalate) |
| Crossing vision (Phase 1 shadow, Phase 2 ledger) | Protect event id / clip window, family agreement per crossing | display (Phase 1), F2 input via census only (Phase 2) |
| Census `deconflict_house` (`PLANNING_census_deconfliction.md` §3.3) | families live per camera, agreement as provenance | F2 input; awareness view only |
| `sensor` attributes, weekly scorer | agreement history | display |

## 3. Institutional context verified (REUSE or NEW per piece)

| Piece | Verdict | Where |
|---|---|---|
| Person legs per physical camera, all integrations | REUSE `CameraResolver.resolve_detection_legs` + `DetectionLeg(entity_id, engine, integration, device_id)` | `camera_resolver.py:1117`, `:165` |
| Engine tag from device integration (not entity suffix) | REUSE `CameraResolver._engine_tag` | `camera_resolver.py:1433` |
| NVR family from engine | REUSE `nvr_family`, moved into the layer, `perimeter_fp_gates.nvr_family` kept as a re-export | `perimeter_fp_gates.py:16` |
| Physical camera key | REUSE `canonical_camera_key` | `camera_resolver.py:460` |
| Agreement tracker shape, Store persistence, delayed save | REUSE pattern of `AgreementTracker` + `Store(hass, 1, f"{DOMAIN}.perimeter_agreement")` + `async_delay_save` | `perimeter_fp_gates.py:129`, `perimeter_alert.py:5058-5078`, `PERIMETER_AGREEMENT_SAVE_DELAY_S` `const.py:2635` |
| Stream-dead state | REUSE the stream-health getter (S1 `camera_input_stream_dead`, in build on `feature/camera-input-stream-health-s1`, no commits yet) | `PLANNING_camera_input_stream_health.md` §5 S1 |
| Protect clip by range / by event | REUSE HA unifiprotect proxy `/api/unifiprotect/video/{entry}/{camera}/{start}/{end}` (`views.py:275`), by event (`views.py:332`, 400 while ongoing) | probe Q1, live 200 on 2026.11.1 |
| Protect event id | REUSE `event.<site>_<cam>_smart_detection` attribute `event_id` (no end time) | probe Q1 |
| Clip into llmvision | REUSE `video_analyzer` `video_file` with a `/api` path (signed by llmvision) | llmvision 1.7.1 `media_handlers.py:629-642` |
| Crossing vision call contract | REUSE `perimeter_enrichment.analyze_crossing_frames` | `PLANNING_crossing_vision.md` D1.7 |
| Zero-fire page | REUSE `_stuck_signal_nm.fire_stuck_signal` (cited by the S1 plan at `:165`; re-verify) | |
| Witness module, episode ledger, `corroborated()` | NEW: no shared helper exists (probe Q5 grep `protect` x `frigate` over the component found three private ones) | `nvr_witness.py` |
| Protect event entity per device lookup | NEW small resolver helper; nothing resolves `event.*_smart_detection` today (grep `smart_detection` in the component: none) | `camera_resolver.py` |

Prior art scanned: plans `PLANNING_perimeter_fp_build_2026_11.md` (D5 tracker), `PLANNING_crossing_vision.md`, census
deconfliction, stream health, arc map M2/M4; memory ghost chain (operator ruling: cross-corroboration, not latency
gates, is the preferred FP defence: this layer is that ruling's shared home); pool-overhead (four integrations on one
camera: family classification must come from the device integration, and Dahua / Amcrest / Reolink are their own
families, never "protect").

## 4. Producer and consumer checks (with fire check)

**Producer (per-family fires).** Today each site derives fires its own way: transit from `_recent_egress_events`
(`transit_validator.py:1365`), perimeter from `_record_leg_fire` (`perimeter_alert.py:2919`), census from snapshot
counts (`camera_census.py:2140-2210`). Fire check, 7 days (probe Q4): door cameras Frigate edges 107 / 93 / 35 / 67,
Protect 85 / 85 / 37 / 37. Transit 0.9 share over 14 days: doorbell_lite 51/76, front_door_aerial 13/28, madrone 14/53,
**garage_a 0/71**: a zero-fire producer leg (§5). Perimeter `agreement_by_camera` and census `source_agreement` rates:
not measured yet (W0).

**Producer arithmetic caveat.** Perimeter's tracker opens a sample only when an alert fires (`perimeter_alert.py:5026`),
so its rate is "of alerts, how many were corroborated", not "of person events, how often did both NVRs see it". The layer
records every episode, so its rates will differ. That is why each consumer migrates behind its own opt-in (§6).

**Consumers and sites** (grep: `_count_platforms_fired(`, `_cross_validate_platforms(`, `nvr_family(`): transit
`:2165`; census `camera_census.py:2148`; perimeter `:2754, :4537, :4574, :4706, :4795, :4805, :4941, :5026, :5362`.
`resolve_cross_platform_sensors` callers: `camera_census.py:1700, :1707` (feeding transit `:547, :1093, :1180`).

**Forward trace.** Fires today reach: crossing confidence (DB/bus only), perimeter severity (NM), census agreement tag
and divergence downgrade (house count, guest mode). Nothing feeds crossing vision from Protect. After this plan: same
actions, plus crossing vision gets Protect clips.

## 5. The garage_a Protect leg: cause from code, and the fix

Cause (code read, registry confirmed 2026-11-13): garage_a is the only door camera whose configured Frigate camera
entity carries `_2` (`camera.garage_a_2`; the others are `camera.doorbell_lite`, `camera.front_door_aerial`,
`camera.madrone_g6_entry`, all platform frigate). Transit subscribes `info.person_binary_sensor` per `CameraInfo` from
`resolve_cross_platform_sensors` (`transit_validator.py:1096`, `camera_census.py:856-874`), which calls
`resolve_operator_declaration` → `resolve_capabilities`. Rung 5 computes the stem `garage_a_2` from the camera entity
(`camera_resolver.py:1531-1566`); the exact-stem lookup misses the Protect device (stem `garage_a`); the guarded `_N`
collapse (`:984-991`) only accepts a sibling that `_shares_evidence_with_inputs` (`:1485`): MAC, identifier tuple, or
both Frigate. The Frigate device has no MAC and the Protect device has no Frigate identifier, so the Protect sibling is
dropped. It is resolver fusion, not subscription. Falsifier for the plan review: a unit fixture with this exact registry
shape must show the Protect `person_detected` missing from `resolve_cross_platform_sensors(["camera.garage_a_2"])`.

Config-first: renaming `camera.garage_a_2` to `camera.garage_a` would likely fix it, but it ripples into every list and
dashboard naming that entity and does not fix the next install ("portability is imperative"). Not a one-line config fix.

Fix (W1): in the `_N` collapse, also accept a candidate whose stem equals the input Frigate device's own object name
taken from its Frigate identifier (`<instance>:garage_a`): same-name evidence from the NVR itself, not an entity-name
guess. Ripple: `resolve_operator_declaration` also feeds room camera fusion, fan veto, sighting pick resolution and
`canonical_camera_key` (the key for garage_a becomes the smaller of the two device ids). Every caller is listed and
golden-tested in W1. Census also gains the Protect leg for garage_a wherever it resolves that camera.

## 6. Invariants (falsifiable)

- **INV-W-OPTOUT.** For each consumer (transit, perimeter, census, crossing vision), with its opt-in knob False, its
  decision output (confidence value, severity, held/proceed, count and agreement tag, vision call set) is byte-identical
  to develop for any fire sequence. Break it by any opted-out consumer whose output changes when the layer is on.
- **INV-W-ONE-EPISODE.** One physical event on one camera (fires whose gaps are all ≤ `NVR_WITNESS_EPISODE_GAP_S`)
  yields exactly one episode and at most one agreement sample, however many legs, re-triggers or families fired, and
  across restarts (only closed episodes persist; an open episode is dropped at shutdown, never replayed). Break it by any
  fire sequence that raises the sample count of one camera by more than one for one event.
- **INV-W-ONE-CLASSIFIER.** NVR family is derived only by `nvr_witness.family_of` (device integration via
  `_engine_tag`). Grep test: no `"_person_detected" in` / `"_person_occupancy" in` family guess remains in transit,
  perimeter or census.
- **INV-W-EVIDENCE-ONLY.** The layer never writes a consumer's state, a census field, house state, `person_id` or an NM
  alert other than its own zero-fire page.
- **INV-W-ONE-HEALTH.** Stream death is read only through the stream-health getter; the layer adds leg-state
  availability (the leg's own `unavailable`, as perimeter does today at `:4787`) and nothing else.
- **INV-W-CLIP-SCOPE.** Every Protect clip fetched is for a camera in the crossing's own door group, with a range inside
  [E − `CROSSING_VISION_PROTECT_PRE_S`, E + `CROSSING_VISION_PROTECT_POST_S`], under crossing vision's existing cap and
  concurrency (its INV-SCOPE and INV-OFF apply unchanged).

## 7. Deliverables

### W0: read-only probe (now, no build)
Measure: fires per day per (camera, family) over every camera the layer will cover (door + perimeter + census lists),
to size the Store; perimeter `agreement_by_camera` and census `source_agreement` distribution; the W1 fixture (registry
shape for all four door cameras and every perimeter camera with a `_N` camera entity); and the episode gap that
separates events (distribution of inter-fire gaps per camera).
- **Verify:** `docs/planning/AUDIT_nvr_witness_w0_<date>.md` with the four tables.
- **Live:** none.

### W1: resolver `_N` collapse accepts Frigate object-name evidence (Tier 2-DB, ships first, alone)
- **Verify:** `resolve_cross_platform_sensors(["camera.garage_a_2"])` on the live-shape fixture returns the Protect
  `binary_sensor.garage_a_person_detected`; the three bare-named cameras are unchanged.
- **Verify (discriminating):** an unrelated Protect camera `camera_a` and Frigate `camera_a_2` whose Frigate object
  name is `camera_a_2` are NOT collapsed (the guard from A-MED-2 still holds).
- **Tests:** `test_resolver_frigate_object_name_collapses_protect_sibling`,
  `test_resolver_unrelated_n_suffix_not_collapsed`, `test_fusion_callers_golden_except_garage_shape` (room fusion, fan
  veto, pick resolution, `canonical_camera_key`). Mutation: remove the new evidence clause → first test red.
- **Live:** within a day, a `person_entry_exit_events` row with `egress_camera` = `binary_sensor.garage_a_person_detected`
  or garage_a `confidence = 0.9`. Under a different failure (subscription, not fusion) the resolver test passes but no
  live row appears: that discriminates.

### W2: `nvr_witness.py` core + transit adopts it (Tier 3)
Pure core `WitnessLedger` (no HA import, caller passes `now`) and thin `NvrWitnessLayer` at
`hass.data[DOMAIN]["nvr_witness"]`, built in `__init__.py`, torn down with tracked unsubs and a final save. Subscribes
person legs from `resolve_detection_legs(camera, "person")` for the union of configured camera lists; rescans on
`entity_registry_updated`. API: `family_of(entity_id)`, `families_live(cam)`, `families_fired(cam, t, window_s)`,
`corroborated(cam, t, window_s)`, `episodes(cam, since)`, `agreement(cam, window_s, min_samples)` returning
samples / both / frigate_only / protect_only / rate. Episodes per camera carry per-family first and last fire time and
count; closed episodes persist in Store `universal_room_automation.nvr_witness`, bounded by `NVR_WITNESS_HISTORY_N` per
camera. Each consumer computes agreement over its own window from the episodes (the operator's agreement record).
Transit: `_count_platforms_fired` returns `len(families_fired(cam, ts, TRANSIT_PLATFORM_WINDOW_S))` when
`NVR_WITNESS_USE_TRANSIT`; the stem→camera mapping goes through the resolver.
- **Verify:** fires of `occupancy_2` + `person_count` (both Frigate) count one family; Protect + Frigate within 10 s
  count two; a Dahua leg counts as its own family, never Protect.
- **Verify:** 5 re-fires of both families inside one episode give one sample; restart mid-episode gives no duplicate.
- **Tests:** `test_witness_one_episode_many_legs`, `test_witness_restart_no_replay`, `test_family_from_device_not_suffix`,
  `test_transit_optout_byte_identical`, `test_transit_optin_matches_legacy_on_door_fixture`,
  `test_no_suffix_family_guess_remains` (grep), `test_agreement_window_is_consumer_supplied`. Mutation: count fires
  instead of episodes → one-episode test red; drop the opt-out branch → byte-identical test red.
- **Live:** `sensor.ura_nvr_witness` (diagnostic, attributes unrecorded) lists per camera `samples`, `both`,
  `frigate_only`, `protect_only` for the last 7 days; door-camera numbers agree with probe Q4 within ±15 %.

### W3: zero-fire trip-wire (with W2)
When one family on a camera has 0 fires in 24 h while the other has ≥ `NVR_WITNESS_SILENT_FAMILY_MIN_OTHER`, page once
per day per camera (this is the garage_a shape seen from the other side).
- **Tests:** `test_silent_family_pages_once`, `test_both_silent_no_page`. **Live:** no page on a healthy day.

### W4: crossing vision gets Protect as a second witness (Tier 2-DB, rides crossing vision Phase 2)
(a) Gap fill: when the crossing has no matched Frigate event (`no_frigate_event`, 26 % at ±10 s in D0), fetch the
Protect range clip `/api/unifiprotect/video/<unifiprotect entry id>/<Protect camera entity>/<E − pre>/<E + post>`
(recording mode is `always`, so a clip exists even with no Protect event), called after `post + settle`. Entry id and
camera entity come from the resolver and config entries, never hard-coded. (b) Dual witness: per
`CROSSING_VISION_DUAL_WITNESS_MODE`, also analyse the Protect clip when the layer shows a one-family crossing, or on all
crossings. Rows record `frame_source` (`frigate_event` / `protect_range`) and, for dual calls, both counts and the
family agreement of the episode.
- **Verify:** a no-Frigate-event crossing yields one Protect call and a row with `frame_source = protect_range`.
- **Verify:** mode `off` → develop crossing vision byte-identical (INV-W-OPTOUT).
- **Tests:** `test_protect_gap_fill_one_call`, `test_protect_range_in_door_group_only`, `test_dual_mode_disagreement_only`,
  `test_protect_clip_url_from_registry`.
- **Live (gated):** one paid dry call on a Protect range clip needs the operator's ok (card open unknown); then the
  `no_frigate_event` share of rows falls toward the Protect-covered share.

### W5: perimeter and census read the layer (Tier 2-DB each, after W2 has ≥ 14 days of episodes)
Perimeter: `_apply_single_source_gate` reads `families_live`, `corroborated(cam, t, 60)` and `agreement(cam, 60, 20)`
when `NVR_WITNESS_USE_PERIMETER`; its own tracker stays until the flip is validated, then goes to the supersession audit.
Census: `_cross_validate_platforms` arithmetic is unchanged (it answers "how many", not "who saw"); `deconflict_house`
reads `families_live` for rule 5 and exposes per-camera agreement as display provenance.
- **Tests:** `test_perimeter_optout_byte_identical`, `test_perimeter_optin_demotes_on_layer_rate`,
  `test_census_counts_unchanged_with_layer`. **Live:** gate rows carry `witness_rate`; census counts equal develop.

## 8. Knobs

| Knob | Rung | Default | Why / kill |
|---|---|---|---|
| `NVR_WITNESS_ENABLED` | 1 | True | False = no subscriptions; every consumer uses its legacy path |
| `NVR_WITNESS_EPISODE_GAP_S` | 1 | 60 (W0 confirms) | ≥ the largest consumer window, so one event is one episode |
| `NVR_WITNESS_HISTORY_N` | 1 | 500 per camera | bounds the Store; W0 sizes it |
| `NVR_WITNESS_SAVE_DELAY_S` | 1 | 30 | same as perimeter's save delay |
| `NVR_WITNESS_USE_TRANSIT` / `_PERIMETER` / `_CENSUS` | 1 | False until each ship's flip | reviewed flip per consumer; False = develop |
| `TRANSIT_PLATFORM_WINDOW_S` | 1 | 10 | names the literal at `transit_validator.py:2705` |
| `NVR_WITNESS_SILENT_FAMILY_MIN_OTHER` | 1 | 20 per 24 h | 0 = trip-wire off |
| `RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` | 1 | True | False = W1 off |
| `CROSSING_VISION_PROTECT_GAP_FILL` | 3 (switch, config-flow entry) | on | off = Frigate only |
| `CROSSING_VISION_DUAL_WITNESS_MODE` | 3 (select) | `disagreement` | `off` / `disagreement` / `all`; cost dial for the operator |
| `CROSSING_VISION_PROTECT_PRE_S` / `_POST_S` | 1 | 5 / 15 | clip range; W4 tests the end-of-segment case |

## 9. Migration order (in-flight work untouched)

1. W0 now (read-only). 2. W1 after stream-health S1 merges (both touch `camera_resolver.py` callers). 3. W2 + W3 after
crossing vision Phase 1 ships (`feature/crossing-vision-shadow`, fix-up a10cd299) and read-API ship 1. 4. W4 with
crossing vision Phase 2. 5. W5 perimeter, then census, after ≥ 14 days of W2 episodes and after the census plan's CD1.
Perimeter Part A (v5.108.20) is not reopened: W5 is additive behind a knob.

## 10. Tier, reviews, non-goals

Tier 3 for W2 (shared primitive consumed by four features; the failure mode is one missed site). W1, W4, W5 Tier 2-DB
each (ripple into fusion, NM severity, census). Two plan reviews (completeness, adversarial build prediction) plus
framing G (goal fidelity) before any build; four code reviews for W2 with orchestrator re-grep and mutation.

Non-goals: centralising consumer policy (thresholds, demote rules, count arithmetic); a Protect face-name path (the face
audit found none live; separate card); Reolink / Dahua / Amcrest as NVR witnesses (they keep their own family, no
agreement policy); a new DB table (Store first; revival: W0 shows the weekly scorer needs SQL joins with labels, or
the Store exceeds 1 MB); ground truth for madrone_g6_entry disagreement (comes from the weekly labelling run, arc map
M10); any AWAY, house-state, lock or HVAC change.

## 11. Edits other plans need (not made here)

- `PLANNING_crossing_vision.md` §8: the "probe of Protect event clips" lever becomes W4 here; INV-SCOPE gains the
  Protect range clip; `frame_source` gains `protect_range`; knobs from §8 above.
- `PLANNING_census_deconfliction.md` §3.3 rule 5 and §2: add the witness layer as the source of "which NVR leg is live"
  per camera; `aware_agreement` may carry per-camera witness provenance (display).
- `PLANNING_camera_input_stream_health.md` S2: expose the dead-stream state keyed by camera entity (the witness layer
  needs it without a room), from the same `_camera_unavail_since` record.
- `PLANNING_perimeter_fp_build_2026_11.md` / perimeter docs: D5 tracker is superseded at W5 flip.
- `ARC_identity_vision_census_map.md`: add a row and merge entry M13 (three Frigate-vs-Protect rule sites → one evidence
  layer; policy separate).
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §3: the fusion doctrine gains the witness layer; §4 records the W1 resolver rule.

## 12. Open questions (with recommended defaults)

1. Dual-witness cost: analyse both clips on every crossing (what "exercise both" means literally) or only on
   disagreement? Default `disagreement`, operator can set `all`. This is a product tradeoff, so it is the operator's call.
2. Paid dry call on a Protect range clip: needs ok. Default: one call before W4 build.
3. Store vs DB table for the agreement history. Default Store, revisit on the trigger in §10.
4. Ship W1 ahead as its own hotfix-sized cycle (it fixes live data now)? Default yes, Tier 2-DB.

## 13. Plan completion tracking

To be filled at each ship: delivered, deferred (with reason and card), and the supersession audit of perimeter's
`AgreementTracker` and transit's suffix classifier (DELETE / KEEP + WIRE / KEEP + DOCUMENT).
