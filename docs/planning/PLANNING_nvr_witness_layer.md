# PLANNING: NVR witness layer (one record of which NVR saw a person, where and when; policy stays with each feature)

Card: NVR-WITNESS-CONSOLIDATION-1 (batch person-sightings, parent VISION-CROSSING-ANALYSIS-1). Plan amendment for the
operator, 2026-11-13, rewritten after plan review 1 (`docs/reviews/plan-review/PLANREVIEW_nvr_witness_layer_1.md`).
One clean doc; nothing here edits another plan (the edits other plans need are in §11).
Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Arc map: `ARC_identity_vision_census_map.md`.
Read for this plan: the card (every field), `AUDIT_protect_clip_witness_probe_2026_11_13.md`,
`AUDIT_protect_face_name_interfaces_2026_11_13.md`, `AUDIT_frigate_face_name_latency_2026_11_13.md`,
`AUDIT_crossing_vision_d0_2026_11_13.md`, `PLANNING_camera_input_stream_health.md`, `PLANNING_crossing_vision.md`,
`PLANNING_census_deconfliction.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md` (§1-§5.5), the ura-arc skill, memories
`reference_pooloverhead_four_integrations`, `reference_frigate_ghost_evidence_chain`. HVAC and presence state-of-play
docs were not read by the planner. Builders of W5c (room fusion, which feeds fan veto and room occupancy) and W5b
(census) read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` completely first.

## 1. Charter, operator words, and the goal

Operator, verbatim: "For all camera work I like to exercise both nvr platforms simultaneously, then cross compare to
reduce errors... How can protect be a separate witness? ...centralize the rules to deconflict to increase confidence."
"I generally favor consolidation so there's no drift and there is one place to make better... Bring me a plan amendment
but it's not necessary to disturb what's in flight. ...check to see if the protect mechanics will allow easy
implementation." On the per-camera agreement record: "Critical for learning. Has to be baked into the design. Note this."

Charter goals served: "Vision is to assist census accuracy. And assist arrivals accuracy... Especially when combined with
facial recognition from the nvr systems"; "guests should be both vision and frigate/protect person counts with
deconfliction"; settings "help with accuracy (first)". Hard constraint honoured: "I need away to be fast acting" (nothing
here touches AWAY, house state or locks).

Goal: one shared evidence layer that (a) records every Frigate and Protect person fire per physical camera, (b) keeps a
per-camera agreement record learned once, persisted and read by every feature (first-class output, the plan cannot ship
without it), (c) classifies NVR family in exactly one function, used by every site that votes by family, and (d) gives
crossing vision Protect as a real second witness. Each feature keeps its own decision.

### 1.1 Critique of "centralize the evidence, keep policy per feature"

For full consolidation: one place to improve, no drift. Today there are four Frigate-vs-Protect comparison sites with
four windows (none / 10 s / 60 s / state now) and four meanings of "agree" (§4.2), plus nine suffix or platform
classifiers (§4.1). Against centralising the decisions too: the sites answer different questions (census: how many
bodies now; transit: did two NVRs see this crossing; perimeter: demote a lone first alert; room fusion: is the room's
camera evidence contested now), serve different consumer classes (display, comfort, security de-escalate), and one
policy edit would move all of them at once, the opposite of a safe migration. So this plan centralises the evidence, the
classifier, the agreement record and the corroboration predicates (`corroborated(cam, t, window_s)` and
`families_on_now(cam)`); each feature supplies its window and decides what to do with the answer. Every window becomes a
named knob in one const block, so drift shows in one diff. No comparison or classifier site is left outside this plan:
each is migrated or carries a written KEEP reason (§4.1, §4.2).

## 2. F1-F5 and consumer classes

Produces F3/F4 evidence, not an identity fact: "NVR family X saw a person on physical camera C at time t". It names no
one, attaches no identity and writes no F2.

| Reader | Uses | Class (manual §5.5(b) / arc map) |
|---|---|---|
| Transit crossing confidence (`transit_validator.py:2165`) | `corroborated(cam, t, 10)` | display (review 1 verified: no decision reader of crossing `confidence` on bus or DB) |
| Perimeter single-source demote (`perimeter_alert.py:4924`) and leg tags | `family_of`, families live, agreement | security (severity de-escalate) |
| Room camera fusion `agreement` (`binary_sensor.py:1827-1860`) → fan veto (`fan_veto.py:424-441`) | `families_on_now`, `family_of` | comfort (fan veto DENY on `split`) |
| Crossing vision | Protect event entity, clip range, per-crossing family agreement | display (Phase 1), F2 input via census only (Phase 2) |
| Census (`_cross_validate_platforms`, `deconflict_house`) | `family_of`, families live, agreement as provenance | F2 input; awareness view only for new reads |
| `sensor.ura_nvr_witness`, weekly scorer | agreement record | display |

## 3. Institutional context verified (REUSE or NEW per piece)

| Piece | Verdict | Where |
|---|---|---|
| Person legs per physical camera | REUSE `CameraResolver.resolve_detection_legs`, `DetectionLeg` | `camera_resolver.py:1117`, `:165` |
| Engine tag from device integration | REUSE `CameraResolver._engine_tag` | `camera_resolver.py:1433` |
| NVR family from engine | REUSE `nvr_family`, moved into `nvr_witness.py`; `perimeter_fp_gates.nvr_family` stays a re-export | `perimeter_fp_gates.py:16` |
| Frigate object name of a device | REUSE `_frigate_object_name_for_device` (W1) | `camera_resolver.py:1519`, used at `:1020` |
| Physical camera key | REUSE `canonical_camera_key` | `camera_resolver.py:460` |
| Agreement record shape, Store, delayed save | REUSE pattern of `AgreementTracker`, `Store(hass, 1, f"{DOMAIN}.perimeter_agreement")`, `async_delay_save` | `perimeter_fp_gates.py:129`, `perimeter_alert.py:5058-5078`, `const.py:2635` |
| Stream-dead state | REUSE the stream-health getter, camera-keyed form from S2 (§9) | `PLANNING_camera_input_stream_health.md` S1/S2 |
| Protect clip by range / by event | REUSE HA proxy `/api/unifiprotect/video/{entry}/{camera}/{start}/{end}` (`views.py:275`), by event (`:332`, 400 while ongoing) | probe Q1, live 200 on 2026.11.1 |
| Protect event id | REUSE `event.*_smart_detection` attribute `event_id` | probe Q1 |
| Clip into llmvision | REUSE `video_analyzer` `video_file` with an `/api` path | llmvision 1.7.1 `media_handlers.py:629-642` |
| Crossing vision call contract | REUSE `perimeter_enrichment.analyze_crossing_frames` | `PLANNING_crossing_vision.md` D1.7 |
| Zero-fire page | REUSE `fire_stuck_signal(hass, kind, key, diagnosis, ..., severity=)`, one per (kind, key) per day | `domain_coordinators/_stuck_signal_nm.py:165` |
| Witness module, episode ledger, `family_of`, `corroborated`, `families_on_now` | NEW: no shared helper exists (probe Q5; review 1 re-grep) | `nvr_witness.py` |
| Protect event entity per device | NEW resolver helper keyed by device id (grep `smart_detection` in the component: none) | `camera_resolver.py` |

Prior art scanned: `PLANNING_perimeter_fp_build_2026_11.md` (D5 tracker), crossing vision, census deconfliction, stream
health, arc map M2/M4; memory ghost chain (operator ruling: cross-corroboration, not latency gates, is the preferred FP
defence; this layer is that ruling's shared home); pool-overhead (family comes from the device integration; Dahua,
Amcrest, Reolink are their own families, never "protect"). Parked trigger fired: `PLANNING_crossing_vision.md:351` parks a
Protect clip probe with revival at `no_frigate_event` > 25 %; D0 measured 26 %. W4 answers it.

## 4. Producer and consumer checks (with fire check)

### 4.1 Every family classifier site (migrate or KEEP)

`family_of(entity_id)` = `nvr_family(_engine_tag(...))` from the entity registry (integration of the entity's device).
If the entity has no registry entry (test fixture, late boot), the suffix fallback runs INSIDE `family_of` only.

| Site | What it decides | Decision | Deliverable |
|---|---|---|---|
| `transit_validator.py:2700-2710` substring test | platform per fired entity | MIGRATE to `family_of` | W2 |
| `perimeter_alert.py:578-583` `_leg_tag` | leg engine tag | MIGRATE | W2 |
| `perimeter_alert.py:623-657, :671, :708` `base_engine` / `_e2` | engine of the configured base and `_2` sibling (feeds `nvr_family` at every gate) | MIGRATE; "legacy" stays only when `family_of` returns unknown | W2 |
| `perimeter_alert.py:4525-4528` `_is_frigate_person_entity` | is this leg Frigate (zone gate, `:4537`, `:4574`) | MIGRATE to `family_of(eid) == "frigate"` | W2 |
| `perimeter_alert.py:2179` `platform == CAMERA_PLATFORM_FRIGATE` | Frigate camera name for the D2 event cache | MIGRATE to `family_of` | W2 |
| `camera_census.py:635-649`, `:985-990`, `:1143`, `:1171`, `:875-898` `CameraInfo.platform` | Frigate numeric count vs binary platform: this IS the family vote in `_cross_validate_platforms` and the snapshots (`:2026, :2105, :2195, :2827, :3796, :3837, :5984, :6000`) | MIGRATE the assignment to `family_of`; the count arithmetic is unchanged | W5b |
| `binary_sensor.py:1827-1860` room fusion | per-source `on_integrations` | MIGRATE (see 4.2) | W5c |
| `camera_resolver._engine_tag` | engine from integration | KEEP: it is the source `family_of` wraps | n/a |
| `camera_resolver._has_any_suffix*` | which entity on a device is the person sensor (slot picking, not a family vote) | KEEP: picks a sensor, does not vote | n/a |

Before migration, W0 lists every live person entity with its suffix-derived class and its `family_of` class; any
mismatch is a named behaviour change in the deliverable that migrates it.

### 4.2 Every comparison site

| Site | Window | "Agree" means | Decision |
|---|---|---|---|
| Census `_cross_validate_platforms` (`camera_census.py:2330`) | none (snapshot) | both counts > 0 | KEEP the count policy (it answers "how many"); classifier migrated (W5b); `deconflict_house` reads families live and agreement as provenance (W5b) |
| Transit `_count_platforms_fired` (`:2689`) | 10 s | ≥ 2 families | MIGRATE to `corroborated` (W2) |
| Perimeter `_apply_single_source_gate` (`:4924`) + `AgreementTracker` | 60 s | other family fired; rate ≥ 0.6 over ≥ 20 | MIGRATE to layer reads behind opt-in, after a replay check (W5a) |
| Room fusion `agreement` (`binary_sensor.py:1827-1860`) → fan veto (`fan_veto.py:424-441`) | state now | all available sources on / split | MIGRATE: agreement counted per family via `families_on_now` (two legs of one NVR stop being two votes), behind opt-in; fan veto policy (DENY on `split`) unchanged (W5c) |

### 4.3 Producer, fire check, forward trace

Fires today come from three private stores: transit `_recent_egress_events` (`transit_validator.py:1365`), perimeter
`_record_leg_fire` (`perimeter_alert.py:2916`), census snapshot counts (`camera_census.py:2140-2210`), plus room fusion
state reads. Fire check, 7 days (probe Q4): door cameras Frigate edges 107 / 93 / 35 / 67, Protect 85 / 85 / 37 / 37.
Transit 0.9 share over 14 days: doorbell_lite 51/76, front_door_aerial 13/28, madrone 14/53, **garage_a 0/71**: a
zero-fire leg (§5). Perimeter `agreement_by_camera`, census `source_agreement`, room fusion `agreement` distributions:
measured in W0.

Rate caveat: perimeter's tracker opens a sample only when an alert fires (`perimeter_alert.py:5026`), so its rate is
"of alerts, how many were corroborated". The layer records every episode, so its rate differs. W5a has a replay gate.

Forward trace: fires reach crossing confidence (DB/bus only), perimeter severity (NM), census agreement and downgrade
(house count, guest mode), room fusion agreement (fan veto). Nothing feeds crossing vision from Protect today.

Rescan paths: `transit_validator.py:417` rebuilds on `entity_registry_updated` for `unifiprotect` entries only. W2 owns
one rescan path in the layer; transit's listener keeps its own subscription rebuild, and W2 adds no second listener in
transit (a test asserts one layer rescan per registry event).

## 5. The garage_a Protect leg: cause and fix

Cause (code read; registry confirmed by the planner and by review 1): garage_a is the only door camera whose configured
Frigate camera entity carries `_2` (`camera.garage_a_2`; the others are bare and platform frigate). Transit subscribes
`info.person_binary_sensor` per `CameraInfo` from `resolve_cross_platform_sensors` (`transit_validator.py:1096`,
`camera_census.py:856-874`) → `resolve_operator_declaration` → `resolve_capabilities`. Rung 5 takes the stem
`garage_a_2` (`camera_resolver.py:1531-1566`); the exact-stem lookup misses the Protect device (stem `garage_a`); the
guarded `_N` collapse (`:984-991`) needs `_shares_evidence_with_inputs` (`:1485`): MAC, identifier tuple or both
Frigate. The Frigate device has no MAC and the Protect device no Frigate identifier, so the Protect sibling is dropped.
Resolver fusion, not subscription.

Config-first: renaming the entity to `camera.garage_a` would likely work but ripples into every list naming it and does
not help another install. Not a one-line config fix.

Fix (W1): in the `_N` collapse, also accept a candidate whose stem equals the input Frigate device's object name from
REUSED `_frigate_object_name_for_device` (`camera_resolver.py:1519`). Same-name evidence from the NVR's own identifier.

W1 callers (every path through `resolve_capabilities`): `__init__.py:647` (room fusion), `binary_sensor.py:1596` (room
fused sensor → fan veto), `camera_census.py:857` (→ transit `:547, :1093, :1180`), `transit_validator.py:2407` (door-group
key), `person_sighting.py:334, :503`, `camera_resolver.py:829/833/863` (pick resolution), and
`perimeter_alert.py:2341` → `resolve_detection_legs` → `resolve_capabilities` (`:1171`). W1 DOES change perimeter input
for garage_a: its egress-role wiring of `camera.garage_a_2` gains the Protect leg, so garage_a's `families_live` and
`AgreementTracker` samples change in Part A code. This is a small, intended change to shipped Part A and is named here.
`canonical_camera_key` for garage_a is `min` of the device ids; the Frigate id (`7c45...`) is smaller than the Protect id
(`f843...`), so the live key does not change.

## 6. Invariants (falsifiable)

- **INV-W-OPTOUT.** For each consumer (transit, perimeter, census, room fusion, crossing vision), with its opt-in knob
  False, its decision output (confidence, severity, held/proceed, count and agreement tag, fused `agreement`, vision call
  set) is byte-identical to develop for any fire sequence.
- **INV-W-ONE-EPISODE.** One physical event on one camera (fires with every gap ≤ `NVR_WITNESS_EPISODE_GAP_S`) yields
  exactly one episode and at most one agreement sample, however many legs, re-triggers or families fired, and across
  restarts (only closed episodes persist; an open episode is dropped at shutdown, never replayed).
- **INV-W-ONE-CLASSIFIER.** Every site in §4.1 marked MIGRATE derives family only through `nvr_witness.family_of`. Grep
  test over `transit_validator.py`, `perimeter_alert.py`, `camera_census.py`, `binary_sensor.py`: no
  `"_person_detected" in`, `"_person_occupancy" in`, `.endswith("_person_detected`, `.endswith("_person_occupancy`, or
  `platform == CAMERA_PLATFORM_FRIGATE` / `CAMERA_PLATFORM_UNIFI` used as a family vote, outside an allowlist naming the
  §4.1 KEEP rows by line. The allowlist is part of the test and every entry carries its reason.
- **INV-W-EVIDENCE-ONLY.** The layer writes no consumer state, census field, house state, `person_id`, or NM alert other
  than its own zero-fire page.
- **INV-W-ONE-HEALTH.** Stream death is read only through the stream-health getter; the layer adds only leg-state
  availability (as perimeter does at `:4787`). With the getter absent, the layer reports stream health as unknown and
  never derives it.
- **INV-W-CLIP-SCOPE.** Every Protect clip is for a camera in the crossing's own door group, range inside
  [E − `CROSSING_VISION_PROTECT_PRE_S`, E + `CROSSING_VISION_PROTECT_POST_S`], under crossing vision's existing cap and
  concurrency (its INV-SCOPE and INV-OFF apply unchanged).

## 7. Deliverables

### W0: read-only probe (now)
Tables: fires per day per (camera, family) for every camera the layer covers (sizes the Store); inter-fire gap
distribution per camera (sets the episode gap); perimeter `agreement_by_camera`, census `source_agreement`, room fusion
`agreement` distributions; suffix class vs `family_of` class for every live person entity (§4.1); the W1 fixture (registry
shape for the four door cameras and every camera with a `_N` camera entity).
- **Verify:** `docs/planning/AUDIT_nvr_witness_w0_<date>.md` with all five tables. **Live:** none.

### W1: resolver `_N` collapse accepts Frigate object-name evidence (Tier 2-DB, ships first, alone)
- **Verify:** `resolve_cross_platform_sensors(["camera.garage_a_2"])` on the live-shape fixture returns
  `binary_sensor.garage_a_person_detected`; the three bare-named door cameras are unchanged.
- **Verify (discriminating):** Protect `camera_a` and Frigate `camera_a_2` whose Frigate object name is `camera_a_2`
  are NOT collapsed (A-MED-2 guard holds).
- **Tests:** `test_resolver_frigate_object_name_collapses_protect_sibling`, `test_resolver_unrelated_n_suffix_not_collapsed`,
  `test_fusion_callers_golden_except_garage_shape` covering every §5 caller including perimeter; the expected delta is
  written out: garage_a gains the Protect leg in transit, census egress, perimeter egress wiring and any room fusing
  `camera.garage_a_2`; `canonical_camera_key` unchanged. Mutation: remove the new clause → first test red.
- **Live:** within a day a `person_entry_exit_events` row with `egress_camera` = `binary_sensor.garage_a_person_detected`
  or garage_a `confidence = 0.9`. If the cause were subscription rather than fusion, the resolver test passes but no row
  appears; that discriminates.

### W2: `nvr_witness.py` core, the agreement record, transit and perimeter classifier migration (Tier 3)
Pure core `WitnessLedger` (no HA import, caller passes `now`) plus `NvrWitnessLayer` at `hass.data[DOMAIN]["nvr_witness"]`,
built in `__init__.py`, torn down with tracked unsubs and a final save. Subscribes person legs from
`resolve_detection_legs(camera, "person")` for the union of configured camera lists; one rescan path on
`entity_registry_updated`. API: `family_of(entity_id)`, `families_live(cam)`, `families_on_now(cam)`,
`families_fired(cam, t, window_s)`, `corroborated(cam, t, window_s)`, `episodes(cam, since)`,
`agreement(cam, window_s, min_samples)` → samples / both / frigate_only / protect_only / rate.

The agreement record (first-class): every closed episode stores per-family first and last fire time and count; episodes
persist in Store `universal_room_automation.nvr_witness`, bounded by `NVR_WITNESS_HISTORY_N` per camera; each consumer
computes agreement over its own window from the episodes. `sensor.ura_nvr_witness` (diagnostic, attributes unrecorded)
shows the per-camera record.

Transit: `_count_platforms_fired` returns `len(families_fired(cam, ts, TRANSIT_PLATFORM_WINDOW_S))` when
`NVR_WITNESS_USE_TRANSIT`. Perimeter: the §4.1 perimeter rows use `family_of` (classification only; the gate policy is
W5a). The perimeter classifier swap is pure if W0 shows zero suffix/`family_of` mismatches on perimeter legs; any mismatch
is listed and gated by `NVR_WITNESS_USE_PERIMETER_CLASSIFIER`.
- **Verify:** `occupancy_2` + `person_count` (both Frigate) count one family; Protect + Frigate within 10 s count two; a
  Dahua leg is its own family, never Protect.
- **Verify:** 5 re-fires of both families in one episode give one sample; restart mid-episode gives no duplicate.
- **Tests:** `test_witness_one_episode_many_legs`, `test_witness_restart_no_replay`, `test_family_from_device_not_suffix`,
  `test_family_suffix_fallback_only_inside_family_of`, `test_transit_optout_byte_identical`,
  `test_transit_optin_matches_legacy_on_door_fixture`, `test_perimeter_leg_tags_from_family_of`,
  `test_one_classifier_grep` (§6 pattern set + allowlist), `test_agreement_window_is_consumer_supplied`,
  `test_single_rescan_per_registry_event`, `test_stream_health_absent_reports_unknown`. Mutation: count fires instead of
  episodes → one-episode test red; drop the opt-out branch → byte-identical test red; reinstate one perimeter `endswith`
  tag → grep test red.
- **Live:** `sensor.ura_nvr_witness` lists per camera `samples`, `both`, `frigate_only`, `protect_only` for 7 days;
  door-camera numbers agree with probe Q4 within ±15 %.

### W3: zero-fire trip-wire (with W2)
When one family on a camera has 0 fires in 24 h while the other has ≥ `NVR_WITNESS_SILENT_FAMILY_MIN_OTHER`, call
`fire_stuck_signal(kind="nvr_witness_silent_family", key=(cam, family), severity="HIGH")` (MEDIUM reaches no channel
under the live NM config, `_stuck_signal_nm.py:177-180`).
- **Tests:** `test_silent_family_pages_once_at_high` (asserts `severity == "HIGH"`), `test_both_silent_no_page`.
- **Live:** no page on a healthy day.

### W4: crossing vision gets Protect as a second witness (Tier 2-DB, rides crossing vision Phase 2; BLOCKED on Q1)
(a) Gap fill: a crossing with no matched Frigate event (26 % at ±10 s in D0) fetches the Protect range clip
`/api/unifiprotect/video/<unifiprotect entry id>/<Protect camera entity>/<E − pre>/<E + post>` (recording mode `always`,
so a clip exists even without a Protect event), called after `post + settle`. Entry id from config entries; the Protect
camera entity and the `event.*_smart_detection` entity resolved by DEVICE id from the fusion, never by name or stem
(live: `event.garage_a_garage_doorbell_lite_smart_detection` is on the Doorbell Lite device, `event.garage_a_garage_a_smart_detection`
on garage_a). (b) Dual witness per `CROSSING_VISION_DUAL_WITNESS_MODE`: the value is the operator's (Q1, blocking). Rows
record `frame_source` (`frigate_event` / `protect_range`), and for dual calls both counts and the episode's family agreement.
- **Verify:** a no-Frigate-event crossing yields one Protect call and a row with `frame_source = protect_range`.
- **Verify:** mode `off` → develop crossing vision byte-identical.
- **Tests:** `test_protect_gap_fill_one_call`, `test_protect_range_in_door_group_only`, `test_dual_mode_per_setting`,
  `test_protect_clip_url_from_registry`, `test_event_entity_by_device_doorbell_lite_vs_garage_a` (the live pair above).
- **Live (gated):** one paid dry call on a Protect range clip, with the operator's ok; then the `no_frigate_event` share
  falls toward the Protect-covered share.

### W5: perimeter gate, census and room fusion read the layer (Tier 2-DB each, after ≥ 14 days of W2 episodes)
**W5a perimeter gate.** `_apply_single_source_gate` reads `families_live`, `corroborated(cam, t, 60)` and
`agreement(cam, 60, 20)` when `NVR_WITNESS_USE_PERIMETER`. Pre-flip replay gate: over the W2 window, replay every
perimeter alert and count those whose demote outcome changes under the layer rate at the current threshold; non-zero →
the list goes to the operator and the flip waits for their ok. The tracker stays until the flip is validated, then goes
to the supersession audit.
**W5b census.** `CameraInfo.platform` assignment via `family_of`; `_cross_validate_platforms` arithmetic unchanged;
`deconflict_house` reads `families_live` for rule 5 and shows per-camera agreement as display provenance. Behind
`NVR_WITNESS_USE_CENSUS`.
**W5c room fusion.** `agreement` counts families, not sources, via `families_on_now` (two legs of one NVR are one vote),
behind `NVR_WITNESS_USE_ROOM_FUSION`; fan veto policy unchanged. W0 shows how many rooms change class.
- **Tests:** `test_perimeter_optout_byte_identical`, `test_perimeter_replay_gate_lists_changed_alerts`,
  `test_perimeter_optin_demotes_on_layer_rate`, `test_census_counts_unchanged_with_layer`,
  `test_room_fusion_optout_byte_identical`, `test_room_fusion_two_legs_one_family_not_split`,
  `test_fan_veto_policy_unchanged`.
- **Live:** gate rows carry `witness_rate`; census counts equal develop; room fused sensors carry `agreement_basis: family`.

## 8. Knobs

| Knob | Rung | Default | Why / kill |
|---|---|---|---|
| `NVR_WITNESS_ENABLED` | 1 | True | False = no subscriptions; every consumer uses its legacy path |
| `NVR_WITNESS_EPISODE_GAP_S` | 1 | 60 (W0 confirms) | ≥ the largest consumer window |
| `NVR_WITNESS_HISTORY_N` | 1 | 500 per camera | bounds the Store; W0 sizes it |
| `NVR_WITNESS_SAVE_DELAY_S` | 1 | 30 | same as perimeter's save delay |
| `NVR_WITNESS_USE_TRANSIT` / `_PERIMETER` / `_PERIMETER_CLASSIFIER` / `_CENSUS` / `_ROOM_FUSION` | 1 | False until each flip | reviewed flip per consumer; False = develop |
| `TRANSIT_PLATFORM_WINDOW_S` | 1 | 10 | names the literal at `transit_validator.py:2705` |
| `NVR_WITNESS_SILENT_FAMILY_MIN_OTHER` | 1 | 20 per 24 h | 0 = trip-wire off |
| `RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` | 1 | True | False = W1 off |
| `CROSSING_VISION_PROTECT_GAP_FILL` | 3 (switch, config-flow entry) | on | off = Frigate only |
| `CROSSING_VISION_DUAL_WITNESS_MODE` | 3 (select) | operator decides (Q1) | `off` / `disagreement` / `all`; cost dial |
| `CROSSING_VISION_PROTECT_PRE_S` / `_POST_S` | 1 | 5 / 15 | clip range; W4 tests the end-of-segment case |

## 9. Migration order (in-flight work untouched)

1. W0 now (read-only). 2. W1 after stream-health S1 merges (both touch resolver callers). W1 is the one step that
changes shipped perimeter Part A input, for garage_a only (§5). 3. Stream-health S2 delivers the camera-keyed getter.
4. W2 + W3 after S2, crossing vision Phase 1 (`feature/crossing-vision-shadow`, fix-up a10cd299) and read-API ship 1.
If S2 slips, W2 may ship first with INV-W-ONE-HEALTH's absent-getter rule (health unknown, never derived). 5. W4 with
crossing vision Phase 2, after Q1. 6. W5a, W5b, W5c after ≥ 14 days of W2 episodes; W5b after the census plan's CD1.

## 10. Tier, reviews, non-goals

Tier 3 for W2 (shared primitive, five consumers, failure mode one missed site). W1, W4, W5a-c Tier 2-DB each. Plan review
2 (adversarial build prediction) plus framing G before build; four code reviews for W2 with orchestrator re-grep and
mutation, and an operator checkpoint before deploy.

Non-goals: centralising consumer policy (thresholds, demote rules, count arithmetic, fan veto rule); a Protect face-name
path (card `D1-PROTECT-FACE-BRIDGE-ADDON-1`); Reolink / Dahua / Amcrest as agreement witnesses (they keep their own
family); a new DB table (Store first; revival: W0 or the scorer needs SQL joins with labels, or the Store exceeds 1 MB);
ground truth for madrone_g6_entry disagreement (weekly labelling run, arc map M10); any AWAY, house-state, lock or HVAC
change.

## 11. Edits other plans need (not made here)

- `PLANNING_crossing_vision.md` §8: the parked "probe of Protect event clips" (trigger fired) becomes W4; INV-SCOPE gains
  the Protect range clip; `frame_source` gains `protect_range`; the §8 knobs above.
- `PLANNING_census_deconfliction.md` §3.3 rule 5 and §2: the witness layer is the source of families live per camera;
  `aware_agreement` may carry per-camera witness provenance (display); `CameraInfo.platform` comes from `family_of`.
- `PLANNING_camera_input_stream_health.md` S2: expose dead-stream state keyed by camera entity from the same
  `_camera_unavail_since` record; S2 precedes W2.
- Perimeter docs (`PLANNING_perimeter_fp_build_2026_11.md`): W1 changes garage_a egress legs; D5 tracker superseded at
  the W5a flip.
- `ARC_identity_vision_census_map.md`: new row and merge entry M13 (four comparison sites and nine classifier sites → one
  evidence layer; policy separate).
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §3 (witness layer, `family_of`) and §4 (W1 resolver rule).
- Presence and SENSOR_FLEET docs: W5c changes the room fusion `agreement` basis (written by the W5c build).

## 12. Open questions

1. **BLOCKING W4 (operator):** analyse both NVRs' clips on every crossing (the literal "exercise both"), or only when the
   layer shows a one-family crossing? Planner's view: `disagreement` costs less, `all` is what you described. W4 is not
   built until you choose.
2. Paid dry call on a Protect range clip before W4 build: needs ok. Recommended: one call.
3. Store vs DB table for the agreement record. Recommended: Store, revisit on the §10 trigger.
4. Ship W1 ahead as its own cycle (fixes live data now)? Recommended: yes, Tier 2-DB, naming the Part A garage_a change.

## 13. Plan completion tracking

Filled at each ship: delivered, deferred (reason and card), and the supersession audit of perimeter's `AgreementTracker`,
the migrated suffix classifiers and the room fusion source count (DELETE / KEEP + WIRE / KEEP + DOCUMENT).
