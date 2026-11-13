# PLANNING: census deconfliction (one function, two views, a promotion ladder)

Cards: VISION-CROSSING-ANALYSIS-1 (Phase 2, census side), CENSUS-OCCUPANCY-ESTIMATOR-1 (merged here),
CENSUS-GUEST-FLOOR-1 (superseded here). Tier 3 plus the house-state rule. Status: clean consolidation 2026-11-13 of
crossing-vision rev 7.1 §B3 / §B11.1-§B11.2 / P2-D4 / P2-D5 (`plan/crossing-vision` @ 1e76c98a) and the census
occupancy estimator (round 6, 2026-10-04). History, not instructions: `docs/planning/archive/HISTORY_*`. Siblings:
`PLANNING_crossing_vision.md` (the vision producer and ledger), `PLANNING_person_awareness_read_api.md` (the read
surface), `PLANNING_camera_input_stream_health.md` (source health), `PLANNING_person_sighting_layer.md` (F1-F5 home).

## 1. Objective and charter

Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, "The operator's goals". The goals
this plan serves, verbatim: "Vision is to assist census accuracy. And assist arrivals accuracy and personalization.
Especially when combined with facial recognition from the nvr systems. Frankly our job is to make it faster and faster
until it can eventually be used in security applications too."; "guests should be both vision and frigate/protect
person counts with deconfliction. Until we trust vision"; "The hard part about census is NOT residents". Hard
constraint: "I need away to be fast acting. That's how it saves $ on energy treatment."

Objective. `PersonCensus` stays the one writer of F2. Every piece of evidence about how many people are in the house
(camera bodies, the crossing ledger, later interior vision, guest rooms, guest WiFi, named sightings) enters F2 only
as a term of ONE function, `census_deconflict.deconflict_house`, which dedups by evidence source so no face or body
is counted twice. The function returns two views of F2:

- **Trust view (F2-T):** who the house acts on. Today's fields and arithmetic, byte-identical to develop.
- **Awareness view (F2-A):** who is around, best estimate, with provenance and agreement.

Each consumer class starts on the trust view and is PROMOTED to read the awareness view one rung at a time, by a
measured bar and an operator Tier-3 checkpoint (§3.2). Operator 2026-11-13: "This is where it starts but it can prove
itself and be promoted. No dogma here." AWAY must never get slower at any rung.

## 2. F1-F5: produced and consumed

| Fact | Role here |
|---|---|
| F1 P is home | consumed: `R = max(get_residents_home_count(), identified_count)` (resident term). Never moved by this plan |
| F2 who is in the house | PRODUCED: F2-T (unchanged) and F2-A (new), single writer `PersonCensus`, single site `_apply_enhanced_house_census` (`camera_census.py:6407`) |
| F3 door crossing + identity attach (owner `EgressDirectionTracker`, `transit_validator.py:1007`) | consumed indirectly: the crossing ledger (sibling plan) turns F3 crossings into `guest_vis` |
| F4 P seen at X at T | MAY feed F2 as a term (rule retired 2026-11-13, CLAUDE.md d1d7b387), only through this function; a named sighting whose slug is already in the union adds nothing. No F4 term is built in this plan |
| F5 P is arriving | none |

Names come only from face and BLE (the identified union). Vision supplies counts, never names.

## 3. Readers by consumer class, and the promotion ladder

### 3.1 The two-view contract

| | Trust view (F2-T) | Awareness view (F2-A) |
|---|---|---|
| Question | Who does the house act on? | Who is around, best estimate? |
| Fields | today's `CensusZoneResult` `identified_count`, `identified_persons`, `unidentified_count`, `total_persons`; the `SIGNAL_CENSUS_UPDATED` payload (`camera_census.py:1868-1900`); existing entities | NEW on the house `CensusZoneResult`: `aware_guests`, `aware_total = identified_count + aware_guests`, `aware_identified` (= trust `identified_persons`; same union, no second identity path), `count_provenance` ∈ {`camera`, `vision`, `agree`}, `aware_agreement` |
| Arithmetic | develop, byte-identical | `deconflict_house` (§3.3) |
| Payload | unchanged | NOT on `SIGNAL_CENSUS_UPDATED`; awareness readers use `get_house_census` only |

### 3.2 The promotion ladder (the one statement of it; other plans reference this section)

`CROSSING_VISION_CONSUMER_CLASSES` (rung 1) is the set of classes promoted to read F2-A. `view_for_class(cls)`
(read-API plan) returns `awareness` only when `cls` is in that set AND the downgrade switch
`switch.ura_crossing_vision_census_authority` (rung 3, default ON, RestoreEntity, OFF = treat the set as empty) is ON;
every other input, including unknown or misspelt strings and a missing switch, returns `trust` (allow-list).
**Legal members** are the rungs whose consumer wiring has been built and reviewed. Any other member raises at import
(`test_consumer_classes_rejects_illegal`). Adding a rung to the legal set is a reviewed code change in that rung's
own Tier-3 plan; adding it to the active set is an operator checkpoint.

Separately, `CROSSING_VISION_AWARENESS_VISION_LEADS` (rung 1, default False) decides whether vision may change the
awareness VALUE (flip F-LEAD). While False, `aware_guests == guest_cam` in every case, so F2-A equals F2-T plus
agreement metadata.

| Rung | Class | Consumers | Bar to promote (all measured; then operator Tier-3 checkpoint) | Status |
|---|---|---|---|---|
| 0 | (value flip) F-LEAD | changes the awareness value | Bars a, b, d, e (§3.4) AND every §15.7a number: ≥ 100 graded crossings over ≥ 7 days incl. ≥ 10 with a non-resident; exact ≥ 95 % overall and ≥ 90 % at night, per door; vision wins ≥ 80 % of B/C disagreements; false guest ≤ 2 %; healthy ≥ 95 %. After the flip the same numbers over a rolling 14 days are a trip-wire (AnomalyDetector → NM, "revert F-LEAD") | gated |
| 1 | `display` | the two awareness entities, `crossing_vision_last`, personalization suggestions (suggestion = display) | none: legal and active at deploy (`frozenset({"display"})`), because F2-A equals F2-T until F-LEAD | ships active |
| 2 | `notification` (F-NOTIFY) | the arrival count follow-up (sibling plan) | bars a, b, d, e + bar c (groups) + exact-count ≥ `CROSSING_VISION_NOTIFY_EXACT_MIN` (0.90) on ≥ `CROSSING_VISION_NOTIFY_MIN_GRADED` (30) graded crossings, AND EGRESS-DIRECTION-AWARE-IDENTITY-1 shipped or measured entry attach ≥ `CROSSING_VISION_NOTIFY_MIN_ATTACH` (0.50). Names stay ≥ 0.75 from F3 | legal now, inactive |
| 3 | `comfort` | HVAC guest mode, pre-arrival conditioning (operator 2026-11-13: "HVAC is comfort basically so since it's not security I'd say it can once it's earned") | F-LEAD live ≥ 30 days with the rolling F-LEAD numbers held, false guest ≤ `CENSUS_LADDER_COMFORT_FALSE_GUEST_MAX` (0.02) on comfort-relevant hours, and a rung plan that reads `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely and names the HVAC input it changes. Which HVAC input drives guest mode today is not verified here | NOT legal; needs its own Tier-3 plan |
| 4 | `house_state` | AWAY, ARRIVING, SLEEP, WAKING, GUEST latch, Path A, boot seed | comfort rung live ≥ 30 days AND a proof that AWAY entry time and `_run_inference` call count are unchanged or earlier on a replay (INV-P2-AWAY-LATENCY at this rung), AND live AWAY latency (last resident departure → AWAY row) median / p90 within 10 % of the P2-D0 (v) baseline over 7 days | NOT legal; needs its own Tier-3 plan |
| 5 | `security` | SC auto-follow, lock regime, SanctionChecker, perimeter severity | last. Bound by manual §5.5(a): de-escalate or annotate only, never escalate, actuate or suppress below 0.9; a count carries no identity confidence, so this rung needs its own confidence model. Revival trigger: notification rung live ≥ 30 days with bars held and p90 latency at the security target (≤ 15 s) | NOT legal; needs its own Tier-3 plan |

A class not promoted reads F2-T (byte-identical behaviour).

### 3.3 The function: `census_deconflict.deconflict_house`

NEW pure module `census_deconflict.py` (no HA import, no clock read). Called once per census evaluation from
`_apply_enhanced_house_census`, after `identified_count`, sync, no await. Returns `(trust_fields, awareness_fields)`;
trust fields are passed through unchanged.

Terms in this plan's build:
- `guest_cam` = the trust view's post-hold `unidentified_count` (the camera estimate always exists; a camera-dark
  tick yields the trust view's held value).
- `guest_vis` = `max(0, L − R)` from the crossing ledger via `census_tick` (sibling plan), or None (case D).

Cases (§15.7):
| Case | Condition | `aware_guests` while vision does not lead | once F-LEAD | `aware_agreement` |
|---|---|---|---|---|
| A agree | `abs(guest_vis − guest_cam) < CROSSING_VISION_DISAGREE_FLAG_MIN` | shared value | shared value | `both_agree` |
| B vision higher | `guest_vis > guest_cam` | `guest_cam` | `guest_vis` | `close` within the flag, else `disagree` |
| C camera higher | `guest_cam > guest_vis` | `guest_cam` | `guest_vis` | `close` / `disagree` |
| D one side missing | `guest_vis` None | `guest_cam` (`vision_only` cannot raise anything) | the side that exists | `single_source` |

Values use `CENSUS_AGREEMENT_*` (`const.py:2439-2446`). `count_provenance` names the estimate that produced
`aware_guests`.

Dedup rules (apply to every term, now and later):
1. Named evidence (BLE id, face leg, egress registration, named sighting) adds a person only by canonical slug. REUSE
   the union (`camera_census.py:2533-2540`, kill-switch fork kept byte-identical) and the face-leg key
   `(canonical_slug, engine, base_stem)` (`camera_census.py:3576-3588`).
2. Body evidence (camera bodies, ledger, interior vision, WiFi) is keyed by physical camera
   (`camera_resolver.canonical_camera_key`), ledger or VLAN. Overlapping cameras combine by max
   (`CONF_INTERIOR_CAMERA_OVERLAP_GROUPS`, estimator D2; the only measured pair is {family_room, master_hallway}, J = 0.56).
3. Guest-side terms combine by max, never sum (estimator H1).
4. Residents are subtracted once, through `R`.
5. An unhealthy source is missing (case D), never zero: camera stream dead (stream-health plan getter), vision
   outage, capped or stale, `camera_input_dark`.

Future terms (each a deliverable of the plan that builds its producer, entering only through this function, with the
rules above): interior vision room counts (VISION-INTERIOR-SIGHTINGS-1), held camera max `M_cam` over
`FLOOR_WINDOW_S`, guest-room unknown occupancy `U_gr`, WiFi guest phones as corroborator only (never a floor, estimator
ruling 5). Each needs a measured gate before it moves `aware_guests`.

### 3.4 Bars a-e (measured on the dark ledger by the sibling plan's scorer)

Window ≥ `CROSSING_VISION_GO_WINDOW_DAYS` (7) and every bar's minimum sample. Thresholds are rung-1 constants shared by
the scorer and the regression trip-wire.

| Bar | Oracle | Pass | Knob |
|---|---|---|---|
| a drift | each independent empty anchor: residue = pre-anchor `L − R_last`; truth 0 | residue == 0 on ≥ 80 % of ≥ 10 anchors AND abs(residue) ≤ 1 on every anchor | `CROSSING_VISION_GO_DRIFT_ZERO_SHARE` 0.80, `_DRIFT_MAX_ABS` 1, `_MIN_ANCHORS` 10 |
| a2 reconcile load (reported beside a) | share of resident departures needing reconcile | ≤ 20 % | `CROSSING_VISION_GO_RECONCILE_SHARE_MAX` 0.20 |
| b resident arrivals | each counted residency arrival: a watched-door entry term in [edge − 300 s, edge + 60 s] with n ≥ 1 | ≥ 90 % matched; of matched ≥ 75 % `term_source = vision` | `CROSSING_VISION_GO_ARRIVAL_MATCH_MIN` 0.90, `_VISION_TERM_SHARE_MIN` 0.75, `_ARRIVAL_WINDOW_BEFORE_S` / `_AFTER_S` 300 / 60 |
| c groups | ≥ 10 staged 2-3 person crossings, operator-labelled | vision exact ≥ 8/10; no undercount by ≥ 2 | `CROSSING_VISION_GO_GROUP_EXACT_MIN` 0.80, `_GROUP_MIN_N` 10 |
| d false guest | evaluations with ≥ 1 resident home and no labelled guest | `guest_vis ≥ 1` on ≤ 2 % of time | `CROSSING_VISION_GO_FALSE_GUEST_MAX` 0.02 |
| e known | ledger `known` share of time | ≥ 90 % | `CROSSING_VISION_GO_KNOWN_SHARE_MIN` 0.90 |

Bar b needs the residency producer firing; if P2-D0 (i) finds it did not, bar b uses recorder `person.*` `not_home →
home` edges for the same residents and the dead producer becomes its own card.

### 3.5 Reader verdicts (develop line numbers)

| # | Consumer | File:line | Class | View |
|---|---|---|---|---|
| 1-4 | AWAY entry: nobody-home, path α, path β, D2 external-empty ticks | `presence.py:1181-1189`, `:1227-1239`, `:1300-1370`, `:7887-7895` | house_state | trust |
| 5 | ARRIVING from AWAY (`has_people`) | `presence.py:1349-1370` | house_state | trust |
| 6 | SLEEP / HOME_* / WAKING, wake backstop, re-arm bypass, boot settle | `presence.py:199-204`, `:7027-7050`, `:7136-7150` | house_state | trust |
| 7 | Path A guest gate → `visitors_present`, `guest_reason` (`_guest_gate_armed` `:6917-6990`, recheck timer `:7003-7017`, `_d5_guest_confidence` `:7579-7582`) | presence | house_state | trust |
| 8 | GUEST night-stay latch (`_refresh_guest_stay`, DB walk) | presence | house_state | not a census reader |
| 9 | SC auto-follow `arriving → DISARMED` | `security.py:189-195` | security | trust |
| 10 | Lock regime | `security_lock_regime.py` | security | trust (reads house state / person edges) |
| 11 | `SanctionChecker unknown_present` | `security.py:282-346` | security | stays unwired |
| 12 | Exterior-person severity | `perimeter_alert.py:2004-2015` | security | trust |
| 13 | `PersonPhoneLeftBehindSensor` | `binary_sensor.py:2185-2189`, `:2232` | house_state (AWAY input) | trust (`total_persons` is never vision-derived; the PLB loop cannot form) |
| 14 | HVAC | no census read today | comfort | trust until rung 3 |
| 15 | existing census entities (§3.6) | `sensor.py:3753, :3776, :4148, :4216-4217, :5159-5220`; `aggregation.py:6696-6778` | display | trust (unchanged) |
| 16 | `URAUnexpectedPersonSensor`, `CensusMismatchSensor` | `binary_sensor.py:1891-1990`, `:2043-2045` | display | trust |
| 17 | `house_status.py` people field | `:206-210` | display | trust (reads `presence.census_count`) |
| 18 | Presence `census_count` sensor | `sensor.py:5798, :6302-6316` | display of the AWAY input | trust |
| 19 | Census DB snapshot | `database.py:4485-4524` | record | existing columns unchanged |
| 20 | NEW awareness entities, `crossing_vision_last` | new | display | awareness |
| 21 | Arrival count follow-up | sibling plan | notification | awareness at rung 2 |
| 22 | Personalization (PERSON-PROFILE-PREFERENCES-1) | via read API | display (suggestion) | awareness |

### 3.6 Entities

Existing entities stay on the trust view. Evidence: `CensusMismatchSensor` reads the `persons_in_house` STATE
(`binary_sensor.py:2043-2045`); the presence boot seed reads the `identified_persons_in_house` STATE into
`_census_count`, an AWAY input (`presence.py:3233-3239`); `ura_v7` (12x), `ura_v8` (13x), v4-v6 and the PWA chart
`persons_in_house`; `ZoneGuestCountSensor` mirrors the house value into every zone.

| Entity | View |
|---|---|
| `sensor.universal_room_automation_persons_in_house`, `guest_count`, `identified_persons_in_house`, `total_persons_on_property`, `sensor.zone_*_guest_count`, `URAUnexpectedPersonSensor`, `CensusMismatchSensor`, presence `census_count`, `visitors_present` | trust, unchanged (no new attributes) |
| NEW `sensor.ura_census_people_around` (state `aware_total`) | awareness |
| NEW `sensor.ura_census_guests_around` (state `aware_guests`) | awareness |

The awareness entities are house level (per-zone awareness waits for VISION-INTERIOR-SIGHTINGS-1). State never
`unknown` (the camera estimate always exists). Unrecorded attributes: `count_provenance`, `aware_agreement`,
`vision_status` (`unknown_ledger` / `dark` / `switch_off` / `ok`), `ledger_state`, `last_crossing` (the vision
plan's provisional F-stage result). Operator action at deploy: repoint the headline "people" cards on `ura_v8` and the
PWA (`dashboard-v3/src/components/tabs/Presence.tsx`) to the awareness entities (list from P2-D0 (ix)); keep the trust
entities on a diagnostics card. The house-visible change happens at F-LEAD, so the F-LEAD checkpoint lists the
repointed cards.

## 4. Invariants (falsifiable)

**Test configuration (non-hollow, #63).** At the dark default `aware_guests == guest_cam`, so a leak is invisible.
Every INV-P2-AWAY-LATENCY and INV-P2-AWARE-NO-TRUST test and drill runs with `CROSSING_VISION_AWARENESS_VISION_LEADS =
True`, class set `{display, notification}`, switch ON and a ledger where `guest_vis ≠ guest_cam` (e.g. camera 0,
`L = R + 3`), in addition to the dark default.

**INV-P2-AWAY-LATENCY (hard, operator).** For any vision result, ledger value, class set or switch state, the AWAY entry
time AND the number and timing of `_run_inference` calls equal develop. Choke points; a vision value reaching any of
them breaks it: (1) the `SIGNAL_CENSUS_UPDATED` keys presence reads (`camera_census.py:1868-1900`); (2)
`PresenceCoordinator._handle_census_update` (`presence.py:5609-5662`) or its trigger list (`:5676-5685`); (3) the
existing `total_persons` / `unidentified_count` / `identified_count` in `_apply_enhanced_house_census`; (4) the boot
seed (`presence.py:3224-3242`); (5) `_inference_engine._confidence`. A vision value may exist in `presence.py` only
inside `get_house_census` / `view_for_class`. Holds at every rung below 4; rung 4's plan must re-prove it.
Tests:
- `test_away_tick_identical_with_vision_payload`: real `async_dispatcher_send(SIGNAL_CENSUS_UPDATED, payload)` →
  `_handle_census_update` → `_run_inference`; HOME_DAY, last resident leaves, camera 0; AWAY tick and
  `_run_inference` count equal a golden from develop (`quality/tests/fixtures/away_latency_golden_develop.json`) AND a
  same-build differential (payload without vision vs with vision at 50 vs None → identical). Golden provenance: the
  generator script under `scripts/` runs the test harness against the develop merge-base in a commit that precedes
  every production change on the branch, time frozen, the periodic inference timer driven explicitly. A golden
  regenerated after the build is a hollow oracle (#62) and a review finding.
- `test_census_existing_fields_golden_all_classes`: census-input replay, class set `{display, notification}`, switch
  ON, vs the develop golden; every existing numeric field AND the existing keys of the real dispatched payload
  (captured by a dispatcher listener) equal.
- `test_boot_seed_ignores_vision_sensors`: awareness entities at 50 at setup; `_census_count` seeded as develop.
- `test_census_mismatch_sensor_unchanged`: awareness at 50; `CensusMismatchSensor` equal to develop.
Mutation drills (framing C): (1) publish `aware_total` under `interior_count` → `test_census_existing_fields_golden_all_classes`;
(2) in `_handle_census_update` assign `get_house_census("awareness").total` to the value it takes from `interior_count`
→ `test_away_tick_identical_with_vision_payload` (calling and discarding is not a drill); (3) assign `guest_vis` to
`unidentified_count` in the producer → `test_census_existing_fields_golden_all_classes`; (4) seed from
`sensor.ura_census_people_around` → `test_boot_seed_ignores_vision_sensors`. Grep anchor (supporting): `vision` and
`aware_` in `domain_coordinators/presence.py` only inside `get_house_census` / `view_for_class` (develop has 1
unrelated `vision` hit). Live: AWAY latency median / p90 over 7 days after each promotion within 10 % of the P2-D0 (v)
baseline.

**INV-P2-AWARE-NO-TRUST.** No reader in a class that is not promoted, and no existing entity, reads an awareness field
(`aware_*`, `count_provenance`) or `get_house_census("awareness")`; `view_for_class` returns `trust` for every class not
in the active set under every config. Break it by a grep hit outside the promoted callers, or a config making
`view_for_class("security")` return `awareness`. Tests: `test_excluded_consumers_never_read_vision` (injects awareness
values 0 / 50 / None at the census result and the read API; identical outputs for presence inference inputs, PLB,
`CensusMismatchSensor`, the four existing census sensors, `house_status`, SC auto-follow, lock regime, perimeter
severity); `test_view_for_class_security_always_trust` parametrised over every class set and switch value and over
`house_state`, `security`, `hvac`, `comfort`, `""`, `"Display"`, `"suggestion"`. Review-D duty: `grep -rn "states.get("`
for the two new entity ids returns only diagnostics.

**INV-P2-AWARE-DECONFLICT.** While `CROSSING_VISION_AWARENESS_VISION_LEADS` is False, `aware_guests == guest_cam` for
every input (cases A-D). Test: `test_awareness_equals_trust_until_lead` (golden over the four cases). Mutation: let case
B pick `guest_vis` → red.

**INV-DEDUP.** For any term set, adding a term whose evidence id duplicates one already present (same canonical slug;
same physical camera inside the window; same crossing) changes neither view. Tests:
`test_same_face_as_leg_and_sighting_counts_once`, `test_overlap_pair_max_not_sum` (one body on family_room and
master_hallway → 1), `test_guest_side_max_not_sum` (estimator gate 9: `R = 2, U_gr = 1, M_cam = 3, T = 0` → 3, not 4;
property test at the function level). Mutation: sum the guest side → `test_guest_side_max_not_sum` red.

**INV-P2-IDENTITY.** The function and the ledger never change `identified_count`, `identified_persons`, any `person_id`,
any resident's home/away, or any input of `get_residents_home` (PLB included). Test:
`test_no_vision_identity_provenance_stamped` (no path writes `identity_provenance = "vision"`;
`IDENTITY_PROVENANCE_VISION` at `const.py:3458` stays unused, KEEP + DOCUMENT).

**INV-NO-NAME (estimator).** Emptying face inputs changes no count term other than the named union.

**INV-SINGLE-WRITER.** Only `_apply_enhanced_house_census` assigns the awareness fields; a grep test fails on any other
writer of `CensusZoneResult` count fields outside the census module.

## 5. Deliverables

### CD0: read-only probe (part of the sibling plan's P2-D0)
(v) AWAY latency baseline: last resident departure edge → AWAY row in `house_state_log`, 14 days, median / p90, share of
AWAYs per path label. (ix) every dashboard / PWA reference to the trust census entities.
- **Verify:** audit `docs/planning/AUDIT_crossing_vision_p2_d0_<date>.md` carries both rows with numbers.
- **Live:** none.

### CD1: `census_deconflict.py` + census wiring (Tier 3)
Pure function (§3.3); in `_apply_enhanced_house_census`, after `identified_count`: compute
`R = max(presence.get_residents_home_count(), identified_count)` (presence via the coordinator manager; missing presence
or any error → `R = identified_count`); one `census_tick(now, resident_term=R, camera_bodies=self._last_house_camera_bodies,
camera_input_dark=self._camera_input_dark_latched)` on `hass.data[DOMAIN]["crossing_vision"]` → `(guest_vis | None,
healthy)` (missing object or any exception → `(None, False)`); then `deconflict_house`; set the awareness fields on the
house result. `_last_house_camera_bodies` (NEW census scalar, None at construction) = the house raw path's `camera_total`
(`camera_census.py:2140-2210`, every configured interior platform, before face subtraction and BLE cancel), None when
that path is degraded with all platforms unavailable; NOT `_last_camera_total_pre_cancel` (`:6069`, Frigate only, minus
one body per fresh face). The latch passed is the previous run's (`_refresh_camera_input_dark_latch()` runs after the
result, `:1860`): accepted one-interval lag. No change to `unidentified_raw`, the clamp ceiling, `active_platforms`, the
payload dict or any existing field.
- **Verify:** §4 tests; `test_camera_bodies_counts_face_labelled_person` (count 1 with a fresh face → bodies 1 while
  `_last_camera_total_pre_cancel` = 0); `test_missing_vision_object_case_d`; `test_estimate_exception_case_d`;
  `test_property_zone_unchanged`.
- **Mutation:** read `_last_camera_total_pre_cancel` instead → the face-labelled test red.
- **Live:** the house result carries non-null `aware_total` after the first census tick; existing census fields equal
  their pre-deploy values on a replayed hour.

### CD2: awareness entities (Tier 3, with CD1)
`sensor.ura_census_people_around`, `sensor.ura_census_guests_around` on the Census device, reading
`get_house_census(view_for_class("display"))` (read-API ship 1). Recorded states, unrecorded attributes (§3.6).
- **Test:** `test_awareness_entities_equal_trust_dark`, `test_awareness_entities_never_unknown`.
- **Live:** both entities have numeric states equal to `guest_count` / `persons_in_house` while F-LEAD is off; P2-F1
  checkpoint confirms no `automations.yaml` reference to them.

### CD3: class set, downgrade switch, trip-wires (Tier 3)
`CROSSING_VISION_CONSUMER_CLASSES = frozenset({"display"})`, legal `{display, notification}`;
`switch.ura_crossing_vision_census_authority`; trip-wires: `crossing_vision_disagree` (B or C persisting ≥
`CROSSING_VISION_DISAGREE_PERSIST_N` per door in 24 h → AnomalyDetector → NM); after F-LEAD, any F-LEAD number below
threshold over `CROSSING_VISION_GO_REGRESSION_DAYS` (14) → NM "revert F-LEAD"; per promoted rung, its bar regressing →
NM recommending demotion.
- **Tests:** `test_consumer_classes_rejects_illegal`, `test_switch_off_reads_trust`, `test_disagree_persist_pages`,
  `test_bar_regression_pages_only_after_flip`. Config extremes: class set `{display}` vs the full legal set; switch OFF
  with classes on; ledger `unknown`; `CROSSING_VISION_GRADE_DAILY_N = 0`.
- **Live:** switch entity present, ON; no page on day one.

### CD4: flips (operator Tier-3 checkpoints, one const edit each)
F-LEAD (`CROSSING_VISION_AWARENESS_VISION_LEADS = True`) and F-NOTIFY (`notification` into the active set), each with
the disposition audit and the gate numbers of §3.2 attached. Revert: the switch (seconds) or the const (reviewed).
- **Live:** after each flip, AWAY latency within 10 % of baseline (INV-P2-AWAY-LATENCY); for F-LEAD, the awareness
  entities differ from trust only on crossings with `count_provenance = vision`.

### CD5: rung plans 3-5 (not built here)
Comfort, house_state, security each get their own Tier-3 plan that adds the class to the legal set, wires its consumer,
re-runs INV-P2-AWAY-LATENCY, and meets the §3.2 bar. Card per rung at promotion time.

## 6. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CROSSING_VISION_CONSUMER_CLASSES` | `frozenset({"display"})` | 1 | Promoted classes; legal set raises on anything else |
| `switch.ura_crossing_vision_census_authority` | ON | 3 | Downgrade only; OFF = every class reads trust |
| `CROSSING_VISION_AWARENESS_VISION_LEADS` | False | 1 | F-LEAD; False = awareness equals trust |
| `CROSSING_VISION_DISAGREE_FLAG_MIN` | 1 | 1 | Agreement threshold |
| `CROSSING_VISION_DISAGREE_PERSIST_N` | 5 per camera per 24 h | 1 | Disagreement page; 0 = off |
| `CROSSING_VISION_NOTIFY_EXACT_MIN` / `_NOTIFY_MIN_GRADED` | 0.90 / 30 | 1 | Rung 2 bar |
| `CROSSING_VISION_NOTIFY_MIN_ATTACH` | 0.50 | 1 | Rung 2 identity bar |
| `CROSSING_VISION_GO_*` (§3.4) | per table | 1 | Bars a-e, shared with the scorer |
| `CROSSING_VISION_GO_WINDOW_DAYS` / `_REGRESSION_DAYS` | 7 / 14 | 1 | Bar window / rolling regression window |
| `CENSUS_LADDER_COMFORT_FALSE_GUEST_MAX` | 0.02 | 1 | Rung 3 bar (NEW; grep `CENSUS_LADDER` = 0 hits) |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` | [] | 2 | Per-install overlap (estimator D2); built when the `M_cam` term is built |

## 7. Dependencies and sequence

1. Read-API ship 1 (`PLANNING_person_awareness_read_api.md`) lands first: `get_house_census`, `view_for_class`.
2. Crossing vision Phase 1 merged (`feature/crossing-vision-shadow`); the ledger (`crossing_ledger.py`, `census_tick`)
   from `PLANNING_crossing_vision.md` P2-D2 / P2-D3 ships with or before CD1.
3. CD1 + CD2 + CD3 ship dark (display active, F-LEAD off). Two plan reviews (completeness; adversarial build-prediction)
   plus a goal-fidelity framing per the charter; four code reviews (A local; B integration / restart / byte-identical
   dark path; C per-site mutation; D adversarial completeness on INV-P2-AWAY-LATENCY and INV-DEDUP incl. pre-existing
   readers); orchestrator re-grep + mutation; operator checkpoint before deploy.
4. CD4 flips when the scorer reports the bars. Rung plans 3-5 after.
5. Stream health ship 1 before any F-LEAD (a dead camera must read as missing, not zero).

## 8. Non-goals

Changing any trust-view field or the census payload; vision supplying a name; vision direction; promoting comfort,
house_state or security in this plan; per-zone awareness (VISION-INTERIOR-SIGHTINGS-1); building the `M_cam`, `U_gr`,
WiFi or interior-vision terms (their own plans, through §3.3); the estimator's door-tally attribution pipeline (§9);
`HouseState.GUEST` migration (superseded by GUEST-MODE-SPLIT-VISITORS-1, v5.108.0); exterior or property census.

## 9. Carried from the estimator (round 6), and what is not

Carried: the guest-side max rule and its falsifying triple (INV-DEDUP); measured overlap groups and the max-per-component
rule; INV-NO-NAME; WiFi guest phones out of any floor, corroborator only, after the D4 filter (state == home, per-install
deny/allow lists, "appeared since last empty anchor"); "absent is not zero" degradation (a missing term drops out of the
max; `census.health` ∈ {ok, degraded, absent}); the empty-anchor idea (implemented as the ledger anchor, sibling plan);
resident subtraction once.

Not carried as build (operator decision needed, see report): the door-tally attribution pipeline (leg-collapse,
same-person, round-trip pairing, main-entry-door prior with reversal, P-AMB ambiguous policy, `T_amb` / `B` ESTIMATE
band) and the FLOOR → `total_persons` promotion (estimator D6, which is rung 4 here). The ledger replaces T; whether
any attribution step should be added to the ledger is decided by bar a (drift) and bar a2 (reconcile load).
