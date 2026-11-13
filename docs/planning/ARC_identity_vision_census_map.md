# ARC MAP: identity / vision / census / perimeter (plan-merge analysis)

Date 2026-11-13. Author ura-planner. Branch `plan/arc-map` from develop d1d7b387. Read-only on code and HA; plan text only.
Operator brief (2026-11-13): plans must be consistent, "not Frankenstein"; "look for opportunities to merge plans. I
didn't want artificial seams that will sink us later." Test used here: **a seam is artificial if two plans change the same
function / field / contract, or if one must be re-planned when the other lands.**

Anchors: CLAUDE.md identity rule (F1-F5, consumer classes; rule on census and sightings REVISED d1d7b387),
`PLANNING_person_sighting_layer.md` §0A, §2A, §2B, §15.7; `IDENTITY_FUSION_CAMERAS_MANUAL.md` §5.5;
`AUDIT_person_awareness_interface_inventory_2026_11_13.md`.

Inputs read: `PLANNING_crossing_vision.md` rev 7 (worktree planner-crossing-vision @ 62c4bb3a; header, Part B §B0-§B9,
§B11 in full; a Tier-3 re-review is editing it, so it is not edited here); `PLANNING_person_sighting_layer.md` (§0A, §2A,
§2B headings, §15.7); `PLANNING_perimeter_gate_evidence_and_input_health.md` (plan/perimeter-batch 514d4e06, Parts A
and B); `PLANNING_phone_left_behind_camera_leg.md` rev 2 (plan/phone-left-behind-camera 9d1fd11d; build on
`feature/phone-left-behind-camera`, reviews A and B SHIP); `PLANNING_house_state_axes_step1.md` header
(plan/house-state-step1); `PLANNING_census_occupancy_estimator.md` header and §0; `PLANNING_census_accuracy.md` outline;
every named card in `kanban.data.yaml`, plus open EXTERIOR-* / LOCK-* / PHONE-LEFT-BEHIND-* cards.
Presence docs: `SENSOR_FLEET_CLASSES.md` and the section outline plus census/sighting lines of
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` were read. **The state-of-play doc was NOT read completely** (1,053 lines).
This map asserts no presence mechanism of its own; every presence claim below is quoted from a plan that read it
completely. A builder of any presence ship still has to read it completely.

Code wins (checked here): the census already dedups synthetic face legs by `(canonical_slug, engine, base_stem)`
(`camera_census.py:3576-3588`) and canonicalises the identified union (`camera_census.py:2533-2540`). No
sighting-to-census path exists in code today. The F3 owner in code is `EgressDirectionTracker`
(`transit_validator.py:1007`), not `TransitValidator` (inventory finding 8; still unfixed in plan §2A / manual §5.5).

---

## 1. Card and plan map

Column key. **F**: P = produces, C = consumes. **Classes**: the §5.5(b) class of each reader: sec (security
de-escalate, ≥ 0.9), notif (notification naming, ≥ 0.75), disp (display, none), plus the two non-§5.5 trust classes the
plans use: hs (house-state trust) and acc (access actuation: locks, alarm). Status from the board on 2026-11-13.

| Card / plan | F | Reader classes | Seams / files touched | Depends on | Status | Order |
|---|---|---|---|---|---|---|
| **VISION-CROSSING-ANALYSIS-1** Phase 1 shadow (`crossing_vision.py`, Part A D1-D3) | P: F3 attribute (vision count per crossing). C: F3 bus event | disp (scorer, diagnostic attr) | new `crossing_vision.py`; additive `peak_person_count` key on `ura_person_egress_event`; `memory_episodes` writer; llmvision second OpenAI entry | D0 (done, AUDIT_crossing_vision_d0*) | built on `feature/crossing-vision-shadow` (reviews A, B SHIP) | 2 |
| **VISION-CROSSING-ANALYSIS-1** Phase 2 Part B / §B11 | P: F2-A (awareness view), F3 attribute (arrival record n/k/guests). C: F3, F1 (R), F2-T | disp, notif (count phrase, F-NOTIFY); trust view to hs/sec/acc unchanged | `camera_census._apply_enhanced_house_census` (~6407-6560), `CensusZoneResult`, `SIGNAL_CENSUS_UPDATED` payload, new `crossing_ledger.py`, two awareness entities, `_arrival_departure_notify` (count amend), `PresenceCoordinator` read slice (P2-RA) | Phase 1 scorer; F-NOTIFY blocked by EGRESS-DIRECTION-AWARE-IDENTITY-1 | rev 7 under Tier-3 re-review | 6 |
| **VISION-INTERIOR-SIGHTINGS-1** | P: unnamed body evidence per room (F4-shaped) → F2-A input. C: interior frames, NVR faces, path map | disp (per-zone awareness), suggestion (= disp) | new producer; `CameraResolver`; census deconfliction function (§3); `CROSSING_VISION_INTERIOR_ENABLED` reserved | crossing-vision Phase 1 accuracy; §3 function | planned, unplanned in text | 9 |
| **PERSON-AWARENESS-READ-API-1** | Read surface for F1, F2-T, F2-A, F3, F4, F5 | all classes, routed by `view_for_class` | `presence.py` (new getters next to `:5409-5466`, `:5907`), public `PersonCensus` methods replacing ~20 privates, id helpers beside `person_coordinator.py:130` | none | pre_planning | 3 (ship 1), 11 (ship 2) |
| **PERSON-ID-NORMALISE-ONE-RULE-1** | none (id rule under F1-F4 keys) | n/a | `camera_census.py:3900-3912, 6159-6176, 6311-6320`, `perimeter_alert.py:5117-5121`, 14+ inline copies, 5 `.title()` inverses | none | inbox, Tier 1 | merged into 3 |
| **FACE-ARRIVAL-REBUILD-1** Phase 1 (sightings D0-D7) | P: F4; F5 via the one D2 site (flag off). C: F3 (egress projection) | disp; acc gate (D3: camera-derived arrival never alone) | `person_sighting.py`, `presence._derive_face_arrival`, `arrival_edges.arrival_source_needs_corroboration`, `CAMERA_DERIVED_ARRIVAL_SOURCES`, `interior_paths.json` | none | in_progress (Phase 1 shipped in parts, v5.108.16+) | done / validate |
| **EGRESS-DIRECTION-AWARE-IDENTITY-1** = sightings §2B / D8 (Phase 2), with FACE-EGRESS-ARRIVAL-1 folded (§2B.6) | P: F3 (identity attach changes for away/home people), F5 `camera_egress` (confirmed candidates). C: F1, path map | notif (follow-up), acc (only with second signal, D3 gate), hs via F5 → HVAC `camera_egress` | `transit_validator.py` veto `:1840-1854`, `_resolve_egress_face_identity_ex`, `_arrival_departure_notify` (follow-up), D2 egress branch, HVAC source selector | Phase 2 gate: true cases MET (10); misrecognition rate measured, operator ceiling open; Jaya/Ezinne pair guard required | planned | 7 |
| **INTERIOR-PATH-MAP-1** (D7) | none directly; path score input for D8, vision B-stage chains, interior vision | n/a | `interior_paths.json`, loader shared with exterior seam loader | none | shipped_organic | dispose now (soak exit) |
| **CENSUS-OCCUPANCY-ESTIMATOR-1** (`PLANNING_census_occupancy_estimator.md`, round 6, 2026-10-04) | P: F2 head count (hybrid floor) + `guests_present` flag | hs and HVAC guest actuation as written (its D5 flag "flows into HVAC guest-mode actuation") | `camera_census` house count; door tally T; `R_home` | CENSUS-GROUND-TRUTH-CSV-FIX-1 (operator answer) | pre_planning | merged into 6 |
| **CENSUS-ACCURACY-1** (`PLANNING_census_accuracy.md` rev 2) | P: F2-T `unidentified_count` input (decay/hold) | hs, disp | census decay/hold; `_2`-suffix face resolution sites | none | pre_planning | 5b (re-verify first) |
| **CENSUS-GUEST-FLOOR-1** | P: WiFi guest count as F2 floor | hs | `_get_wifi_guest_count` (`camera_census.py:2779`) | estimator | pre_planning | superseded (close) |
| **PERSON-PROFILE-PREFERENCES-1** | C: F1, F2-A, F3 arrival record, F4 | suggestion (= disp) | per-person profile store (new); reads via read API | read API ship 1; arrival record | pre_planning | 8 |
| **DEPARTURE-ACTIONS-1** | C: F3 departure candidates | acc / hs / suggestion (to decompose) | consumers TBD | D8 | inbox | 8 |
| **PHONE-LEFT-BEHIND-CAMERA-LEG-1** | C: F4 (`get_last_person_sighting`) | disp only (operator ruling A) | `binary_sensor.py` `PersonPhoneLeftBehindSensor` (`:2098-2274`), NextRoom display, retires `TransitValidator._camera_sightings` named branch | sightings D1 (shipped) | built, reviews A+B SHIP | 1 |
| **PHONE-LEFT-BEHIND-TRANSIENT-FLICKER-1** | C: F1, F2-T (census-ready gate likely) | hs (PLB is an AWAY input) | same `is_on` the camera leg just rewrote | camera leg merged | inbox | 10 |
| **Perimeter Part A** (D1 daylight demote, D2 gate rows, D3 VLM location shadow); cards PERIMETER-GATE-DECISIONS-NOT-PERSISTED-1, PERIMETER-ZONE-AGREEMENT-FIX-OR-REMOVE-1 (residuals), PERIMETER-FP-GATES-DISPOSE-1 (data) | C: F3 (D10.5 identity), F1 (persons home) | sec (severity de-escalate), disp (rows, scorer) | `perimeter_alert.py`, `perimeter_enrichment.py`, `perimeter_fp_gates.py`, `const.py`, `memory_episodes` | none | built | 1 |
| **PERIMETER-SWITCH-LABELS-AND-FLOW-PARITY-1** | none | n/a | perimeter `_IntegrationOptionsSwitch` keys, options flow | Part A (adds knobs) | inbox, Tier 1 | 4 |
| **Perimeter Part B D4** camera-input stream health; = **PANEL-KS-HEALTH-AS-INPUT-1** | P: input health (room tier) | hs (room occupancy → lights, fans, HVAC) | `coordinator.py` room fusion exclusion set, `sensor.<room>_unavailable_entities` attrs, stuck-signal NM | none | planned, not built | 5 |
| **CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1** | C: the D4 health predicate | hs (zone tier), F2 inputs | `occupancy_substrate.py`, presence zone tier, `presence_fan_recheck.py`, `fan_veto.py`, census camera counts | D4 | inbox | 5 (second ship) |
| **STALE-SOURCE-ARRIVAL-CONSUMERS-1** | C: F5 / F1 edges | acc (security expected-arrival) | `security.py` expected-arrival add (`:2382` handler), `arrival_edges.stale_source_arrival` | GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 | inbox | 10 |
| **EGRESS-OUTCOME-WEEKLY-LABEL-1** | none (labels) | operator | D8a outcome log, labeller script | operator answers (Jaya phone 11-11; Ojini / Ziri trackers) | waiting_me | 0 |
| **HOUSE-STATE step 1a** | P: F1 edges (residency), occupancy getter; lock off ARRIVING taint; exterior severity | acc, sec, disp | `residency.py`, `presence.py`, `security_lock_regime.py`, `perimeter_alert.py` | lock-release branch | shipped (per brief) | validate |
| **HOUSE-STATE-VACATION-OVERLAY-1B** | P: house-state overlay | hs, acc | `presence.py` house-state machine, lock regime page conditions | 1a live checks L1/L4; HOUSE-STATE-LOG-MISSING-AWAY-ROWS-1 | parked | 10 |
| LOCK-* restart cluster: LOCK-REGIME-BOOT-REALLY-AWAY-1 (**two board entries, tiers 2 and 3**), LOCK-BOOT-LOCKOUT-UNAVAILABLE-AT-SETUP-1 and LOCK-LOCKOUT-UNAVAILABLE-AT-SETUP-1 (**same defect, two ids**), LOCK-BOOT-RECHECK-ENGAGE-1 | C: F1 edges, house state | acc | `security_lock_regime.py` boot recheck, `_last_real` | lockout ON (LOCK-REGIME-SWITCHES-OFF-1 answer) | parked | 10 |
| LOCK-VACATION-PHANTOM-SLEEP-DAILY-UNLOCK-1 | C: house state | acc | lock regime engage/release on SLEEP | lockout ON; 1b | parked | merged into 1b |
| LOCK-UNCOUNTED-RETURN-ARM-REDUNDANT-1 | C: F1 edges | acc (page) | `security_lock_regime.py` | 1a | inbox, Tier 1 | 4 |
| LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1, LOCK-ENTRY-AREAS-WRONG-OBJECT-1 | C: F5 `camera_face`, F3 entry areas | acc | `arrival_edges.py` | shipped per presence doc §1 | board shows open | close after check |
| LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 | C: house state | acc | lock regime | merged before 1a | presumed done with 1a | validate |
| EXTERIOR-PERSONS-HOME-ALWAYS-ZERO-1, EXTERIOR-PERSON-SEVERITY-ARRIVING-BODY-ONLY-1 | C: F1 | sec (NM severity) | `perimeter_alert.py` | folded into 1a | inbox (should close with 1a validation) | validate |
| EXTERIOR-SEAM-FILE-LOADER-1 | none | n/a | seam loader (shared with path map D7) | D7 | open | dispose with D7 |
| EXTERIOR-GUEST-FACE-FASTFOLLOW-1, EXTERIOR-GUEST-EGRESS-1, EXTERIOR-DWELL-LOITER-1 | C: F3 | sec / hs | perimeter / egress | parked with triggers | parked | keep parked |

---

## 2. Merge analysis

| # | Group | Shared seam | Decision | Reason |
|---|---|---|---|---|
| M1 | crossing-vision P2-RA read slice + PERSON-AWARENESS-READ-API-1 + PERSON-ID-NORMALISE-ONE-RULE-1 | the same façade on `PresenceCoordinator` (`get_house_census`, `view_for_class`), the same public `PersonCensus` methods, the same id function | **MERGE into one plan, two ships.** Ship 1 (Tier 2, lands before crossing-vision P2-D4): `get_house_census(view)`, `view_for_class(cls)`, the consumer-class threshold table (replaces the 0.75 / 0.9 literals at `transit_validator.py:2601`, `perimeter_alert.py:5019`), `slug_of` / `display_of` beside `tracked_person_entity_id`, the four residual sites A-D, a public F3 "last crossing + attach" getter on `EgressDirectionTracker`, `get_last_arrival_record()`. Ship 2 (Tier 2, parallel any time after ship 1): migrate the ~40 private census reads and 14+ inline copies, delete the dead seed branch `presence.py:3222`. | If the slice stays inside the crossing-vision plan, the API plan has to be re-planned around a contract another plan already fixed (the artificial-seam test, both halves). Residual A feeds sightings and the egress BLE leg (inventory §5), so the id rule belongs in the ship every new consumer is born on. Crossing-vision §B11.3 keeps a one-line pointer: "P2-RA = read-API ship 1". |
| M2 | VISION-INTERIOR-SIGHTINGS-1 + CENSUS-OCCUPANCY-ESTIMATOR-1 + CENSUS-ACCURACY-1 + CENSUS-GUEST-FLOOR-1 + crossing-vision F2-A awareness view | the house guest count: one value, today planned in four places with four formulas (estimator hybrid floor; §15.7 cases A-D; rev-7 `aware_guests`; WiFi floor) | **MERGE the arithmetic into the one deconfliction function (§3), owned by ONE plan.** Estimator: its floor terms (held camera max, door tally T, `R_home`, "guest-side terms maxed, never summed") become source terms and rules of the function; its door tally T IS the crossing ledger, so it is not built twice. GUEST-FLOOR: superseded (the estimator header already says so); WiFi guest count enters the function as a corroborator term only, never a floor. Interior vision: **KEEP SEPARATE as a producer plan** (new frames, its own measure-first probe), but it must add its count only as a §3 source term, never with its own fusion. CENSUS-ACCURACY-1: **KEEP SEPARATE** (it fixes an input of the trust view: decay/hold and `_2` face resolution); re-verify scope first, because FACE-SOURCE-REGISTRY-DISCOVERY-1 (v5.107.1, live 11-10) already reads `_2` face sensors through the device, so the suffix half may be done. | Four plans each changing the house guest count is the textbook artificial seam: each lands and forces the next to re-plan. Producers are legitimately separate (different evidence, different probes); the place where evidence becomes a count must be one. |
| M3 | EGRESS-DIRECTION-AWARE-IDENTITY-1 + sightings §2B egress arrival candidates + crossing-vision arrival record n/k | F3 identity attach and the one arrival notification `_arrival_departure_notify` | **Card + §2B: already one (D8); keep.** Crossing-vision arrival record: **KEEP SEPARATE**, with two contracts pinned: (a) `k` reads the F3 attach only through the read-API F3 getter (M1), and counts a Phase 2 provisional candidate only after confirmation; (b) the amend-the-arrival-message mechanism is ONE function, built by D8 (its notify follow-up ships first, F-NOTIFY is blocked on it) and reused by crossing-vision R-7. | Vision never decides identity (INV-P2-IDENTITY), so the producers are disjoint; the shared pieces are a read contract and one notify amend site. Pinning both removes the seam without merging two Tier-3 plans that are at different gates. |
| M4 | Perimeter Part B D4 + PANEL-KS-HEALTH-AS-INPUT-1 + CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 | one predicate "this camera-derived input's stream is dead"; readers at room tier, zone tier, fan recheck, census | **MERGE into one plan, two ships**, moved OUT of the perimeter doc into its own file. D4 is the implementation of PANEL-KS-HEALTH-AS-INPUT-1 (KS-agnostic redesign, KS `foreground_app` leg parked) → close the KS card into D4. Ship 1 = D4 room tier + a public health getter. Ship 2 = the residual card's zone tier / fan recheck readers on the same getter. Census reads it through §3 (a dead source is case D "missing", never zero). | Without the getter, the residual would re-derive the predicate in three readers. Part A shares nothing with Part B (the perimeter plan's own §8.1 says so), so keeping them in one doc is the false merge. |
| M5 | PERIMETER-ZONE-AGREEMENT-FIX-OR-REMOVE-1 + VLM location (D3) + gate decisions (D2) | the "on property or street?" question and its evidence rows | **MERGE confirmed (already Part A).** Fix-or-remove is decided in one disposition from D2 rows + D3 location rows, after D0-B and ~4 weeks. Two gates answering the same question must not both survive: the disposition keeps at most one. PERIMETER-SWITCH-LABELS: **KEEP SEPARATE** (Tier 1) but sequence right after Part A so the new knobs are labelled once. | Same question, same rows, same file; already one ship. |
| M6 | PLB transient flicker + PLB camera leg | `PersonPhoneLeftBehindSensor.is_on` | **KEEP SEPARATE, sequenced.** Camera leg is built and reviewed; merging reopens it. Flicker is planned on top of the merged camera-leg code, Tier 2-DB (AWAY input), and must not use the sighting attributes as a gate (ruling A; a trust use needs its own plan). | One function, but strictly ordered; no re-plan once the order holds. |
| M7 | HOUSE-STATE-VACATION-OVERLAY-1B + LOCK-VACATION-PHANTOM-SLEEP-DAILY-UNLOCK-1 | vacation representation and the lock regime's SLEEP engage/release | **MERGE the lock card into 1b's plan** as a named case its two plan reviews must close. | 1b changes what VACATION is; the phantom-sleep defect is a VACATION → SLEEP walk. Planning the lock fix first means re-planning it when 1b lands. |
| M8 | LOCK-REGIME-BOOT-REALLY-AWAY-1 (two entries) + LOCK-BOOT-LOCKOUT-UNAVAILABLE-AT-SETUP-1 + LOCK-LOCKOUT-UNAVAILABLE-AT-SETUP-1 + LOCK-BOOT-RECHECK-ENGAGE-1 | lock regime boot recheck and `_last_real` seeding | **MERGE into one "lock regime restart" plan**; dedupe the duplicate ids on the board. | Same function (boot recheck), same revival trigger (lockout ON), a joint restart test already named in one card. |
| M9 | STALE-SOURCE-ARRIVAL-CONSUMERS-1 + sightings D3 access gate | the predicate the security expected-arrival add applies | **KEEP SEPARATE card, ONE predicate**: extend `arrival_edges.arrival_source_needs_corroboration` (or a sibling in `arrival_edges`) with the stale-source test; no second gate in `security.py`. | Prevents a second arrival-policy site beside D3's. |
| M10 | EGRESS-OUTCOME-WEEKLY-LABEL-1 + crossing-vision grading (R-8) | operator labelling of the same crossings | **MERGE the operator surface**: one weekly run per crossing key asking identity (who) and count (how many); separate scoring scripts. | Two labelling loops on the same crossings double the operator's work and drift on keys. Needs operator OK (§5). |
| M11 | PERSON-PROFILE-PREFERENCES-1, DEPARTURE-ACTIONS-1 | read API; D8 | **KEEP SEPARATE** (consumers); both born on the read API. | No shared write. |
| M12 | Crossing vision (Part A + Part B) as one doc | producer (F3 attribute, ledger) vs census owner function | **SPLIT**: Part A + ledger + arrival record stay in `PLANNING_crossing_vision.md`; §B11.1 deconfliction and the awareness view move to the census plan (§4). | Interior vision would otherwise have to amend the crossing-vision plan to add its count: the seam the operator warned about. Do this after the running Tier-3 re-review returns. |

---

## 3. Census and sightings: the one deconfliction function

**Old framing dropped.** "Census and sightings never feed each other" is RETIRED (operator 2026-11-13, CLAUDE.md
d1d7b387). Correction notes added on this branch to `PLANNING_person_sighting_layer.md` §2A and manual §4.5a.

**Rule.** Any evidence, including sightings and interior vision, MAY reach F2, but only as a source term of ONE
deconfliction function that dedups by evidence source, so no face or body is counted twice. Nothing else writes F2.

**The function.** `census_deconflict.deconflict_house(terms, residents) -> HouseCount` (NEW pure module, no HA imports),
called from exactly one site: `PersonCensus._apply_enhanced_house_census` (`camera_census.py` ~6407-6560, the site rev 7
already chose). It returns both views: F2-T (byte-identical to develop until a separate Tier-3 decision) and F2-A.
Rev 7's `_awareness_vision_estimate` is folded into it, not kept beside it.

REUSE, not rebuild:

| Piece | Existing |
|---|---|
| Identity dedup | union with `_normalize_name_set` + egress registrations (`camera_census.py:2533-2540`); kill-switch fork kept byte-identical |
| Face-leg dedup key | `(canonical_slug, engine, base_stem)`, keep fresher (`camera_census.py:3576-3588`) |
| Physical camera key | `camera_resolver.canonical_camera_key` (sightings D1) |
| Disagreement cases | §15.7 cases A-D, `CENSUS_AGREEMENT_*` (`const.py:2439-2446`), rev-7 §B11.1 arithmetic |
| Resident subtraction | `R = max(residents_home, identified_count)` (crossing record §16a R4) |
| Guest-side combination | estimator H1: guest-side terms MAXED, never summed |
| Measured camera overlap | estimator ruling 6: only {family_room, master_hallway} overlap (J = 0.56) |

Each input is a **term** with an evidence id. Rules:
1. **Named evidence** (BLE id, face leg, egress registration, named sighting) adds a person only by canonical slug; a slug
   already in the union adds nothing, whatever the source. A named sighting is a term, not a second union.
2. **Body evidence** (camera body count, crossing ledger L, interior vision room count, WiFi guest count) is keyed by
   physical camera (or ledger / VLAN); overlapping cameras combine by max; guest-side terms combine by max.
3. **Residents subtracted once** via R.
4. **Unhealthy source = missing** (case D), never zero: dead stream (M4 getter), vision outage, capped, stale.
5. **Trust view unchanged** until a Tier-3 flip; awareness view moves under F-LEAD.

**Falsifiable invariant INV-DEDUP.** For any input set, removing every term that duplicates an already-present
evidence id (same slug, or same physical camera within the window) leaves both outputs unchanged. Break it by feeding
the same face as a census leg AND a sighting term (count must not rise), or the same body on family_room and
master_hallway. Enforcement: the single call site; a grep test that no module outside the census writes
`CensusZoneResult` count fields; a mutation drill that sums instead of maxes the guest side → red.

**Who feeds it:** crossing vision (ledger L, per-crossing terms), interior vision (room counts, unnamed), sightings
(named terms; adds nothing today because the census reads the same faces), CENSUS-ACCURACY-1 (fixes the camera-hold
input), estimator (terms + rules), WiFi (corroborator), stream health (missing marks).

---

## 4. Recommended sequence and surviving docs

| Step | Ship | Tier | Note |
|---|---|---|---|
| 0 | Operator answers (§5) | op | unblocks labels, lock cards, estimator fixture |
| 1 | Perimeter Part A; PLB camera leg | 2 / 2-DB | both built; finish reviews, ship |
| 2 | Crossing vision Phase 1 shadow | 2-DB | built; starts the scorer clock |
| 3 | Read API ship 1 (M1) | 2 | before any new F2-A / arrival consumer |
| 4 | PERIMETER-SWITCH-LABELS; LOCK-UNCOUNTED-RETURN-ARM-REDUNDANT | 1 | cleanups after Part A / 1a |
| 5 | Camera input stream health ship 1 (D4), then ship 2 (zone / fan / census readers); CENSUS-ACCURACY-1 re-verified and, if still needed, its decay fix | 2-DB | room-tier ripple; builder reads HVAC state of play |
| 6 | Census deconfliction plan: §3 function + awareness view + estimator terms (rev-7 P2-D4, estimator folded) | 3 | after the crossing-vision re-review; house-state rule applies |
| 7 | Sightings Phase 2 / D8 (direction-aware egress, pair guard) incl. the one notify amend function | 3 | after operator sets the misrecognition ceiling |
| 8 | Arrival record + F-NOTIFY; PERSON-PROFILE-PREFERENCES-1; DEPARTURE-ACTIONS-1 | 2-DB / 3 / 2 | consumers on the read API |
| 9 | VISION-INTERIOR-SIGHTINGS-1 (probe first, then producer feeding §3) | 3 | |
| 10 | 1b vacation overlay (+ LOCK-VACATION-PHANTOM); lock restart plan when lockout ON; PLB flicker; STALE-SOURCE-ARRIVAL | 3 / 2 | |
| 11 | Read API ship 2 (migration) | 2 | parallel any time after 3 |

Docs to consolidate:

| Surviving doc | Absorbs | Retired / pointer |
|---|---|---|
| `PLANNING_census_deconfliction.md` (NEW name; F2 owner plan) | crossing-vision §B11.1-§B11.2 + §B3 verdicts + P2-D4; `PLANNING_census_occupancy_estimator.md` (terms, rules, guests_present); CENSUS-GUEST-FLOOR-1 | estimator plan marked SUPERSEDED with a pointer; crossing-vision keeps producer + ledger + arrival record and points here |
| `PLANNING_person_awareness_read_api.md` (NEW) | crossing-vision §B11.3 (P2-RA), PERSON-ID-NORMALISE-ONE-RULE-1, inventory §7 verdicts | crossing-vision §B11.3 becomes a pointer; the id card closes into it |
| `PLANNING_camera_input_stream_health.md` (NEW, moved) | perimeter Part B §7, PANEL-KS-HEALTH-AS-INPUT-1, CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 | perimeter doc keeps Part A only |
| `PLANNING_person_sighting_layer.md` | stays the F1-F5 home (§2A) and Phase 2 / D8 | no change beyond the §2A correction |
| `PLANNING_house_state_axes_step1.md` Part B | LOCK-VACATION-PHANTOM-SLEEP-DAILY-UNLOCK-1 | |

---

## 5. Needs the operator

1. **Does the awareness view ever reach the trust view?** The new rule lets sightings feed F2; rev 7 keeps F2-T
   byte-identical. Default: interior and vision terms move F2-A only; F2-T changes need their own Tier-3 decision.
2. **Estimator `guests_present` flag** was designed to drive HVAC guest-mode actuation (a trust read). Under rev 7 that
   would breach INV-P2-AWARE-NO-TRUST. Default: the flag is awareness (display / suggestion) until a Tier-3 trust plan.
3. **Approve the doc moves in §4** (three new files, estimator plan superseded), timed after the crossing-vision Tier-3
   re-review returns.
4. **One weekly labelling run** for identity and count (M10).
5. **Still open, already asked:** Jaya's phone on 11-11 and Ojini / Ziri trackers (EGRESS-OUTCOME-WEEKLY-LABEL-1);
   the 10-03 departure timeline (CENSUS-GROUND-TRUTH-CSV-FIX-1); were the lock switches turned off on purpose
   (LOCK-REGIME-SWITCHES-OFF-1); the Phase 2 misrecognition ceiling.

Board hygiene for the orchestrator (no operator needed): LOCK-REGIME-BOOT-REALLY-AWAY-1 appears twice; the two
LOCKOUT-UNAVAILABLE-AT-SETUP ids are one defect; EXTERIOR-PERSONS-HOME-ALWAYS-ZERO-1 / EXTERIOR-PERSON-SEVERITY-* and
LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 / LOCK-ENTRY-AREAS-WRONG-OBJECT-1 should be validated against 1a and closed;
INTERIOR-PATH-MAP-1 is due a soak-exit disposition; manual §5.5 and plan §2A still name `TransitValidator` as the F3 owner.
