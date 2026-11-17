# PLANNING: person-awareness layer leak cleanup (sizing, cards, order)

Date 2026-11-17. Author ura-planner. Card LAYER-LEAK-CLEANUP-PLAN-1 (parent LAYER-LEAK-CLEANUP-1). Plan only: no code,
no kanban edit (the orchestrator mints the cards). Code read: `develop` @ 056c69993 (live line v5.108.34).

## Headline

- **What is left:** the guard allowlist on develop today has **228 rows / total 256**
  (`quality/tests/test_person_awareness_layer_guard.py:64`, `person_awareness_layer_allowlist_PROVISIONAL.py:28`), down
  from 238 / 266 on 11-14. Guard green on develop (150 passed, 2026-11-17).
- **66 of the 256 are not leaks.** They are ruled conforming rows that stay for good: pinned ingest feeders R13 (8), the
  stream-health owner row (1), threshold-equal constants R8 (3), census owner-display (#7 41, #7o 2), residents-home
  owner-display (#4 2), non-person name collisions (#32c 9). A further 4 are reserved step-7 / fast-stage rows.
- **186 rows are real cleanup**, plus 9 unguarded groups that no rule sees. 176 of the 186 close through **5 cleanup
  cards (6 builds)**; 10 close inside feature cards that are already planned (step 7, NVR W5c, crossing-vision Phase 2).
- **Effort, full close:** about **16-17 builder-days** across **6 builds** (two Tier 3, two Tier 2-DB, two Tier 1-2).
  **Calendar at current pace:** the arc ships first (§4a); interleaving one cleanup build per arc ship that leaves a
  builder slot free, about **3 weeks**.
- **Recommended (marginal benefit, §6): about 9 builder-days, 4 builds, about 1.5-2 weeks.** It closes everything with a
  live risk or a behaviour value (the security geofence arrival listener, the one BLE-in-room read with the
  phone-left-behind filter, the boot seed, the fail-open identity vetoes, the 13 cross-coordinator private reads). It
  parks the two Tier-3 rewrites of code that is correct today (lock edge ledger, presence inference snapshot) with
  revival triggers, and rules presence's own display entities owner-display instead of writing ~50 getters. Guard total
  then falls 256 -> 158 (feature cards included); full close falls it to about 69.

## 1. Institutional context verified

Mandatory reads done completely this session: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger
#1-#43; nothing below re-asserts a ledger claim), `docs/architecture/SENSOR_FLEET_CLASSES.md`,
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 C1-C39; the only HVAC touch here is a byte-identical
getter swap at `hvac.py:1558-1560, 2748-2749`), `docs/planning/CONTRACT_person_awareness_layer.md` (complete),
`docs/planning/AUDIT_person_awareness_layer_leaks_2026_11_14.md` (complete), `PLANNING_person_awareness_layer_ship3.md`
§9 and §17, `ARC_identity_vision_census_map.md` §4a, board cards LAYER-LEAK-CLEANUP-1, LAYER-LEAK-CLEANUP-PLAN-1,
PERSON-ID-INLINE-SWEEP-1 (incl. `folded_2026_11_16`), PRESENCE-BOOT-SEED-FROM-VIEW-1, G6-ONE-BLE-ROOM-READ-1,
STALE-SOURCE-ARRIVAL-CONSUMERS-1, LOCK-REGIME-BOOT-REALLY-AWAY-1, BLE-ARRIVAL-PRODUCER-HVAC-GATED-1,
NVR-WITNESS-CONSOLIDATION-1, EGRESS-DIRECTION-AWARE-IDENTITY-1.

Identity model: this plan produces no fact. It moves CONSUMERS of F1 (edges, level), F2 (census), F3 (crossings), F4
(BLE room, sightings) and F5 onto the contract §4 read surface. Consumer class of each reader is in §3 per card.

**Allowlist re-count (2026-11-17, from the module, not trusted):** 228 rows, max-sum 256, by group:

| Group (§9 #) | Card owner in the allowlist | Rows | Max | Files |
|---|---|---|---|---|
| #32 presence/census/zone privates (display + 13 cross-coordinator) | READ-API | 76 | 79 | sensor 53, binary_sensor 13, coordinator 5, hvac 4, coordinator_diagnostics 2, manager 1, `__init__` 1 |
| #7 census privates in census display | READ-API (owner_display) | 41 | 41 | sensor 39, binary_sensor 2 |
| #26 display `pc.data` / BLE-in-room display | G6 | 20 | 34 | aggregation 15, sensor 12, binary_sensor 6, house_status 1 |
| #31 inline person ids + raw `person.*` display name | PERSON-ID-INLINE-SWEEP-1 | 11 | 11 | camera_census 4, perimeter 2, 5 others 1 each |
| #25 presence inference `pc.data` | G6 (own Tier 3) | 4 | 10 | presence |
| #32c name collisions | READ-API | 9 | 9 | 8 files |
| #2 lock second ledger + raw reads/listeners | LOCK-REGIME-BOOT-REALLY-AWAY-1 | 9 | 9 | security_lock_regime |
| R13 pinned ingest feeders | READ-API | 8 | 8 | 6 files |
| #21 PLB `_is_room_occupied` + `pc.data` | G6 | 4 | 6 | binary_sensor |
| #33 member-to-member privates | READ-API | 6 | 6 | person_sighting 3, census, presence, person_coordinator |
| #6 literal-view display census callers | crossing-vision Phase 2 | 6 | 6 | aggregation, binary_sensor, sensor |
| reserved (step 7 A12/A13/D8, fast-stage G3) | step 7 / fast stage | 4 | 4 | perimeter, transit 2, crossing_vision |
| #27 census `_get_ble_persons` / `_ble_home_by_area` | G6 | 2 | 4 | camera_census |
| #1, #3, #22, #24, R8 | STALE-SOURCE (#1, #3), G6 (#22, #24), READ-API (R8) | 3 each | 3 each | security, perimeter, fan_veto + fan_recheck, lock, const |
| #20 room occupancy `get_persons_in_room` | G6 | 2 | 3 | coordinator |
| #4, #7o, #34 | READ-API | 2 each | 2 each | sensor, sensor, aggregation |
| #10, #13, #19, #29, OWN | step 7 (3), NVR (1), owner (1) | 1 each | 1 each | |

**Closed or changed since 11-14 (verified):**
- Music `#23`: the three `person_coordinator.data` reads now use `get_person_location` (music repair merge, -3; allowlist
  comment line 26). Step 8's arrival engine subscribes G1 and reads only §4 surfaces (presence doc header, step 8).
- `#5` boot seed H1 is **not on the allowlist and the code is still there** (`presence.py:3291-3298` reads
  `sensor.{DOMAIN}_identified_persons_in_house` into `_census_count`). The guard's R3 taint does not see an f-string built
  on `DOMAIN`. Finding: the group is UNGUARDED today; card L3 closes the code and adds the rule case.
- `#28` H6: `transitions.py` no longer reads `_camera_sightings` (grep 0); the store is read only inside
  `transit_validator.py:670, 765, 889`. It is now an internal legacy store, not a leak; DELETE candidate in L4 after a
  reader check.
- P5 (HVAC write of `_pre_arrival_enabled`): closed by G9 (`hvac.py:1242` calls `pc.set_pre_arrival_enabled`).
- Not yet built seams G6 needs: `persons_in_room` exists (`person_coordinator.py:2508`, phone filter inside, no reader
  migrated); `room_for_area`, `persons_in_room_or_scanner_areas` and the frozen `snapshot()` do not exist (grep 0).
- Ship 3 §9 names the cleanup doc `PLANNING_person_awareness_leak_cleanup.md`; the operator brief names this file. This
  file is the one; the §9 pointer needs a one-line fix by the orchestrator.

**REUSE / NEW per proposed piece** (greps over `custom_components`, `quality`, `docs/planning`):

| Piece | Verdict |
|---|---|
| One BLE-in-room read | REUSED `PersonTrackingCoordinator.persons_in_room` `person_coordinator.py:2508` |
| Area -> room map | NEW public `room_for_area(area_id)` over the existing private `_area_id_to_room` (no public equivalent, grep `room_for_area` 0) |
| Scanner-area union | NEW `persons_in_room_or_scanner_areas(room)` built on the one read (contract §2.4a; grep 0) |
| Move log for the lock | REUSED `location_moves_since` `person_coordinator.py:2312` |
| Edge feed for security / perimeter / lock | REUSED G1 `residency.subscribe_person_edges` + `get_person_edges_since`; EXTEND with the `approach` kind and all-person scope (contract §5 G1; not built) |
| Stale-source hold | REUSED `arrival_edges.stale_source_arrival` + the lock's hold pattern (`security_lock_regime.py` `_held_edges`) |
| Person id rule | REUSED `person_ids.tracked_person_entity_id` / `display_of` |
| Census boot read | REUSED `census_view.house_census_view(hass, cls="house_state")` |
| Diagnostic getters for cross-coordinator reads | NEW small public getters on presence (`signal_consensus()`, `last_transition_time()`, `ready_event`), fan state on presence (`fan_on_since(room)` etc.; `get_fan_last_transition` already public). No new value, no new store |
| Knobs | none new except one rung-1 kill switch (§5) |

Prior plans consulted: the ship 3 plan (§9, §11, §17), the contract, the audit, `PLANNING_person_awareness_read_api.md`
(skim), `PLANNING_lock_suspicious_arrival_hold.md` (S1 hold semantics), `PLANNING_identity_actions_v6.md` (step 8
reads, skim). Memory bodies: `feedback_marginal_benefit_pushback`, `feedback_extend_existing_never_rebuild`,
`feedback_tier2db_minimum_arc` (house-state changes get 3 reviews), `reference_identity_model_f1_f5`.
Config-first: no setting closes any leak; these are code-path routings. The G6 phone filter has an operator YES (Q1).

## 2. Falsifiable invariants (one per card plus the ratchet)

- **INV-RATCHET.** After each card merges, `LAYER_ALLOWLIST_TOTAL` equals the §4 value for that card or lower, and no
  card adds a row. Falsified by a merge whose total is higher, or by a new row under any card id.
- **INV-NOOP-PURE.** For every site a card marks "pure migration", the consumer's output (decision, attribute, entity
  state) is byte-identical under the live config on a recorded fixture. Falsified by any golden diff.
- Per-card invariants are in §3 (each one names the one behaviour change it is allowed, if any).

## 3. The cleanup cards

Effort = builder-days including the fix-up round; review time is the reviewers', counted in calendar not here.

### L1. G6 one BLE-in-room read (extends G6-ONE-BLE-ROOM-READ-1; folds C9 twins). Tier 2-DB. ~4 days, 1 build (2 commits)

| Group | Sites (verified 2026-11-17) | Class | Change | Rows / max |
|---|---|---|---|---|
| #20 room occupancy | `coordinator.py:3601` (radar-latch clear `ble_person`), `:4716` (BLE extends occupancy), `:5279` (`STATE_BLE_PERSONS` fill); unguarded `:1402` (display via `getattr`) | comfort | **behaviour:** phone-left-behind person no longer extends a room (operator Q1 YES, after the §2.4a probe) | 2 / 3 |
| #21 phone-left-behind sensor | `binary_sensor.py:2202-2204, 2291-2293` `_is_room_occupied` private + `pc.data` | house_state | pure (public `room_occupied(room)`) | 4 / 6 |
| #22 fan veto / fan recheck | `fan_veto.py:312` + `tracking_status` raw; `presence_fan_recheck.py:1375` `_area_id_to_room` + slug fallback `:1384-1386` | comfort | pure, plus the slug fallback becomes registry-only (registry-not-names) | 3 / 3 |
| #27 census BLE persons | `camera_census.py:2928` `_get_ble_persons`, `:3276` `_ble_home_by_area` | producer (F2 ingest) | pure; STALE concept split kept (presence doc gold patterns: do NOT align) | 2 / 4 |
| #26 display BLE loops | aggregation 15, sensor 12 (`sensor.py:3013, 3032, 3108` + `.data`), binary_sensor 6, house_status 1 | display | pure | 20 / 34 |
| C9 twins (unguarded) | `presence.py:4841` zone-tier `_phone_trustworthy` routes to the one predicate; `:7580` inference twin stays for L3 | comfort | pure | 0 |

Total 31 rows / 50. First commit = behaviour (#20, #21, #22, #27, twin 4841); second = display #26.
**Invariant INV-G6:** for every room R and tick, the set of BLE persons that extends, latch-clears or fills
`ble_persons` for R equals `persons_in_room(R)`; it differs from the raw `get_persons_in_room(R)` only by persons whose
phone-left-behind sensor reads `on`. Falsified by a tick where a person absent from `persons_in_room(R)` extends R.
**Acceptance:**
- **Verify (probe, D0, read-only, prober):** 7-day recorder count of ticks where a room was BLE-held by a person whose
  `*_phone_left_behind` read `on`. Zero or near-zero = ship; otherwise the operator decides with the count (contract
  §2.4a). Discriminates: a count of 0 with 0 PLB-on hours means the probe saw no input, report PLB-on hours too.
- **Test:** `test_g6_room_occupancy_reads_one_meaning` (PLB-on person does not extend; PLB-unknown keeps, fail-open),
  `test_g6_scanner_area_union_kept` (Jaya Bedroom borrows `jaya_bathroom`, presence doc §6 item 3),
  `test_g6_display_byte_identical` (golden over the 34 display rows), per-site call-neuter drills RED.
- **Live:** `binary_sensor.<room>_occupied` `ble_persons` attribute never lists a person whose
  `binary_sensor.*_phone_left_behind` is `on`; allowlist total 250 -> 200 (after L2 build 1).

### L2. Access edges onto G1 (STALE-SOURCE-ARRIVAL-CONSUMERS-1 + LOCK-REGIME-BOOT-REALLY-AWAY-1). Tier 3. ~6 days, 2 builds

| Group | Sites | Class | Change | Rows / max |
|---|---|---|---|---|
| #1 security geofence listener (S1) | `security.py:2198` `_setup_geofence_listener`, `:2231` `_resubscribe_geofence_persons`, `:2255` `_handle_person_state_change` | access | **behaviour (operator CONFIRMED 11-14):** a stale-source edge is HELD then confirmed, not acted on at once; 10/30-min windows and guest scope unchanged | 3 / 3 |
| #3 perimeter third ledger (S7) | `perimeter_alert.py:546` `_person_arrivals`, listener `:1120`, `_nonface_agrees` `pc.data`, `_followup_person_name` raw `person.*` | security | pure (same arrival rule over G1 + `location_moves_since`) | 3 / 3 |
| #2 lock second ledger (S2) | `security_lock_regime.py:1354` `_subscribe_person`, `async_setup` added-domain + `async_all`, `_away_due_ts`, `_away_setup`, `_away_boot_discharge` `:2646`, `_friendly`, `_person_for_sensor` `:1934`, `_start_synthetic_hold` | access | the restart / boot really-away fix is the card's own behaviour change (LOCK plan) | 9 / 9 |
| #24 lock Bermuda moves (S3) | `_ensure_pc_listener` `:1861`, `_on_pc_update` `:1884`, `_face_arrival_corroborated` `:1825` | access | pure (`location_moves_since`); **moved here from G6 by this plan:** it is the lock's surface and access-class | 3 / 3 |

Total 18 / 18. Build 1 = G1 extension (approach kind, all-person scope, separate deque so `recent_arrival` stays
byte-identical, ship 3 §10) + #1 + #3. Build 2 = #2 + #24 inside the LOCK restart plan.
**Invariant INV-ONE-LEDGER:** after build 2, no module other than `residency.py` keeps a per-person last-real or
arrival ledger, and no `person.*` state listener exists outside `presence._handle_geofence_change` and the
`ResidencyTracker` connect. Falsified by an R9 hit or a dict keyed by person entity filled from states (R9 polling-ledger
rule). INV-AWAY-LATENCY unchanged (G1 never sits in front of the direct geofence trigger).
**Acceptance:**
- **Verify:** a stale-source `not_home -> home` (source tracker unchanged > 10 s) while armed adds no expected arrival
  until the hold confirms; a real arrival adds it within hold + 1 s. Discriminates against "listener dropped": a guest's
  real arrival still adds a 10-min window.
- **Test:** `test_security_expected_arrival_via_g1_held_stale`, `test_security_approach_zone_30min_kept`,
  `test_perimeter_d105_same_verdicts_golden`, LOCK plan tests; per-site source mutation (framing C) on each consumer's G1
  callback.
- **Live:** `get_layer_diagnostics()["g1_subscribers"]` = 4 (crossing vision, music, security, perimeter) after build 1,
  5 after build 2; allowlist 256 -> 250 (build 1); build 2 removes 12 more when it revives.

### L3. Presence house-state inputs (PRESENCE-BOOT-SEED-FROM-VIEW-1 + H2 snapshot). Tier 3 (house state). ~3 days, 1 build

| Group | Sites | Class | Change | Rows / max |
|---|---|---|---|---|
| #5 boot seed (H1), UNGUARDED | `presence.py:3291-3298` reads the identified-persons display entity into `_census_count` | house_state | **behaviour at boot only:** seed from `house_census_view(hass, cls="house_state")`, else wait for the first `SIGNAL_CENSUS_UPDATED` | 0 (adds the R3 rule case first, then removes the code) |
| #25 inference `pc.data` (H2) | `presence.py` `_run_inference` (6 hits, `:7666`, `:8480`), `_update_ble_zone_presence` (2, `:6324`), `_is_known_person_in_room`, `_discover_guest_rooms` (`:9157`) | house_state | pure (one frozen `snapshot()` per tick) | 4 / 10 |
| #33 presence part | `_run_inference:_lost_away_since` (`presence.py` reads the person coordinator private) | house_state | pure (public getter) | 1 / 1 |
| C9 inference twin | `presence.py:7580` `_phone_trustworthy` closure | house_state | pure, with its existing parity test | 0 |

Total 5 / 11 (+1 rule case). **Invariant INV-L3:** the golden inference replay (`away_latency_golden_develop.json` and
the census trust golden) is byte-identical except boot ticks before the first census signal, where `_census_count` is
the house_state view's value or unset, never a display entity state. Falsified by any non-boot golden diff, or a boot
tick reading an entity state. Tier 2-DB minimum per `feedback_tier2db_minimum_arc`; elevated to Tier 3 because it
threads the inference path.
**Acceptance:**
- **Test:** `test_boot_seed_ignores_vision_sensors` (contract), `test_inference_snapshot_golden`, guard drill: an
  f-string `f"sensor.{DOMAIN}_..._persons_in_house"` state read is an R3 hit.
- **Live:** after a restart, `sensor.ura_presence_coordinator_house_state` reaches its pre-restart state without an
  AWAY flash (`last_away_branch` unchanged, `away_entries_today` not incremented by the boot); allowlist -11.

### L4. Person ids and member internals (PERSON-ID-INLINE-SWEEP-1, folded). Tier 2. ~1.5 days, 1 build

| Group | Sites | Change | Rows / max |
|---|---|---|---|
| #31 inline `person.<slug>` | `camera_census` `_derive_ble_crossing_trackers`, `_get_face_recognized_person_names`, `face_person_would_be_vetoed`, `is_face_leg_person_vetoed`; `perimeter_alert` `_followup_person_name`, `async_setup` (`:1118`); `person_coordinator._find_person_entity`; `person_sighting._emit`; `transit_validator._resolve_egress_face_identity_ex`; `house_status.who:_find_person_entity`; `notification_manager._get_person_name` raw state (`display_of`) | byte-identical on this house (entity ids are lower-cased slugs); fixes fail-open vetoes for a display-name install (portability, `feedback_portability_imperative`) | 11 / 11 |
| card fold 11-16 | name-vs-id readers `camera_census.py` ~6159-6176, ~6311-6320, ~3900-3912, `perimeter_alert.py` ~5117-5121; `__init__.py` ~3145-3163 rewrites `entry.data` to display names (re-grep at build) | unguarded; same rule | 0 |
| #33 rest | `camera_census._any_zone_occupied_snapshot:_zone_trackers`, `person_coordinator._ble_leads_enabled`, `person_sighting` `_face_arrival_cooldown`, `_face_recognition_enabled`, `_zone_trackers` | public getters | 5 / 5 |
| #34 restore writes | `aggregation.py` `seed_previous_location` / `_time` from display `async_added_to_hass` | restore moves into the person coordinator (ship 3 §17 default) | 2 / 2 |
| #16 (unguarded) | the lock passes the egress tracker object to `door_entry_areas` | pass presence's `door_entry_entities()` | 0 |
| H6 legacy store | `transit_validator.py:306, 670, 765, 889` `_camera_sightings` (no outside reader since PLB camera leg) | DELETE if its own reader is dead; else KEEP + DOCUMENT | 0 |

Total 18 / 18. **Invariant INV-ID:** no `person.` string is built outside `person_ids.py` (R12) and every test fixture
with a display-name person whose entity id differs from the slug vetoes the same as the slug case. **Test:**
`test_veto_display_name_person_not_fail_open` (each of the five veto sites), golden for the house's live config.
**Live:** census and egress veto counters unchanged over one day; allowlist -18.

### L5. Presence diagnostic internals (#32). Tier 1-2. ~2.5 days full / ~1 day recommended, 1 build

| Part | Sites | Change | Rows / max |
|---|---|---|---|
| 5a cross-coordinator decision reads | `hvac.py:1558-1560` (`_ready_event`), `hvac.py:2748-2749` (`_signal_consensus`, `_last_transition_time`, comfort, D-wait gate), `coordinator.py` fan state (`_fan_on_since` ×2, `_fan_off_at`, `_fan_interference_hold_until`, `_fan_recheck_manager` `:5006`), `coordinator_diagnostics.py` compliance (`_signal_consensus`, `_consensus_low_since`), `manager.py` `_dispatch_house_state_change`, `__init__.py` `handle_fan_recheck_force_restore` | public getters, byte-identical (HVAC doc: no decision changes) | 13 / 13 |
| 5b presence's own display entities | `sensor.py` 53 (`PresenceHouseStateSensor` 36, `PresenceDiagnosticSensor` 5, consensus 4, rearm / wake counters), `binary_sensor.py` 13 | **recommended: rule owner_display** (contract §2.7: an owner's own display entities may read its store under a counted allowlist). Full close = one `diagnostics_snapshot()` read | 63 / 66 |

**Invariant:** 5a byte-identical (HVAC Wait-for-Presence gate golden; compliance defer golden). **Test:**
`test_hvac_consensus_reads_public_getter` (call-neuter RED), `test_presence_display_attrs_golden` (5b, full close only).
**Live:** `sensor.ura_presence_coordinator_signal_consensus_confidence` and the house-state sensor attributes unchanged;
allowlist -13 (recommended) or -79 (full).

### Feature-owned groups (counted here, built there)

| Group | Rows / max | Owner | Notes |
|---|---|---|---|
| #10 perimeter 600 s egress cache, #13 census BLE exit listener, #19 perimeter census legs | 3 / 3 | EGRESS-DIRECTION-AWARE-IDENTITY-1 (step 7) | plus unguarded #11 (provenance on census), #12 (notify in producer), #14 (census DB amend) |
| reserved A12, A13, D8, fast-stage G3 | 4 / 4 | step 7 / fast stage | A12 retires with step 7's master switch; A13 / D8 / G3 become permanent pinned rows (R13 class) |
| #29 fan veto reads URA camera entity state | 1 / 1 | NVR-WITNESS-CONSOLIDATION-1 W5c | plus unguarded #8 (P3 F2 ingest, byte-identical house-count test), #17, #18 (W2) |
| #6 literal-view display census callers | 6 / 6 | crossing-vision Phase 2 promotion | one-line `cls="display"` each |
| #30 HVAC switch gates the BLE arrival producer | 0 (policy) | BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 | before v6.0.0 (operator pick A) |
| #9 security census input unwired | 0 | operator decision Q2 | stays open by ruling |

## 4. Guard total stepping down

Recommended order (§5). "Full" adds the parked pieces at the end.

| Step | Card | Rows removed (max) | Total after |
|---|---|---|---|
| 0 | develop today | | 256 |
| 1 | L2 build 1 (security S1 + perimeter S7 on G1) | 6 | 250 |
| 2 | L1 G6 (behaviour + display) | 50 | 200 |
| 3 | L4 ids + internals | 18 | 182 |
| 4 | L3 boot seed only (recommended part) | 0 (+ closes unguarded #5) | 182 |
| 5 | L5a cross-coordinator reads | 13 | 169 |
| 6 | L5b rule owner_display (a reviewed allowlist re-label, not a code change; rows stay, card owner changes) | 0 | 169 |
| 7 | feature cards as they ship (step 7 3 + A12 1, W5c 1, crossing-vision P2 6) | 11 | 158 |
| **Recommended floor** | permanent 66 + 3 pinned reserved + 66 owner_display (5b) + parked L2 build 2 (12) + parked L3 H2 (11) | | **158** |
| Full close | + L2 build 2 (12), L3 H2 (11), L5b getters (66) | 89 | **~69** |

(The ratchet constant moves at each merge; a re-label in step 6 changes no total.)

## 5. Recommended order (does not displace arc §4a)

Arc §4a rule: nothing new is dispatched unless it is the next open §4a row or the operator asks. So every L card waits
for a free builder slot after the current §4a row's build; none blocks or reorders §4a rows 3, 5, 6, 7.

1. **L1 D0 probe** (read-only, `ura-prober`, ~1 h): runs any time, no builder slot.
2. **L2 build 1** (security S1 + perimeter S7): the only HIGH live-risk leak (audit S1: 78 iPad blips/week could open
   suppression windows while armed). First builder slot after step 7's build is dispatched.
3. **L1 G6**: next free slot; shares the F4-BLE seam with interior vision (`persons_in_room` already built there).
4. **L4 ids**: Tier 2, small, any free slot. Portability value for the second install.
5. **L3 boot seed (H1 only)**: next free slot after a restart-safe window (`feedback_no_restart_during_sleep`).
6. **L5a**: smallest; can ride in the same build as L4 if both are free.
7. Parked (revival triggers in §6): L2 build 2 (lock ledger), L3 H2 snapshot, L5b getters.

Knob: one rung-1 kill switch, `G6_ROOM_OCCUPANCY_PHONE_FILTER_ENABLED` (const, default True; False = room occupancy
reads `persons_in_room(..., phone_filter=False)`, the named second meaning of contract §2.4a). Rung 1 because it gates a
40-room behaviour that should change only by review. No other numbers are added; L2 reuses
`LOCK_ARRIVAL_STALE_SOURCE_S` (10 s) and the arrival-hold Number.

## 6. Marginal-benefit decomposition (the recommended cut)

- **L2 build 2 (lock ledger, Tier 3, ~3 days):** the lock's ledger is correct today (presence doc §1, suspicious-arrival
  hold, 0 of 40 real arrivals held). Benefit = one ledger (INV-ONE-EDGE-LEDGER) and 12 rows. Risk = an access actuator
  rewrite. **Park** with trigger: LOCK-REGIME-BOOT-REALLY-AWAY-1 is dispatched for its own restart defect (then do #2 and
  #24 in that build, no extra review cost).
- **L3 H2 (inference snapshot, Tier 3, ~2 days):** reads are correct today; the parity test pins the twin. Benefit = 11
  rows. Risk = the house-state inference path (INV-AWAY-LATENCY). **Park** with trigger: any presence inference change
  that touches `_run_inference` reads, or a measured tick-inconsistency between two `pc.data` reads.
- **L5b (66 presence display rows):** display only, no decision reads them, and contract §2.7 already allows an owner's
  display entities. Writing ~50 getters buys nothing a consumer can feel. **Rule owner_display**; revive if the presence
  privates are refactored (the getters then come for free).
- Kept in the recommendation: everything with live risk (S1), a behaviour the operator approved (G6 Q1), boot AWAY risk
  (H1), fail-open vetoes on a second install (ids), and every cross-coordinator decision read (L5a).

## 7. Non-goals

No new fact, store or coordinator. No AWAY trigger change (INV-AWAY-LATENCY). No change to S1's 10/30-min windows or
guest scope. No wiring of the security census input (#9). No NVR classifier work outside W2/W5. No step-7 work. No
change to the STALE concept split (presence doc gold patterns). No allowlist rows added by any card.

## 8. Tier classification

L1 Tier 2-DB (40-room behaviour change, cross-coordinator). L2 Tier 3 (access; build 1 touches security alarm suppression,
build 2 the lock). L3 Tier 3 (house state; minimum Tier 2-DB per operator rule, elevated because it threads inference).
L4 Tier 2 (byte-identical here; identity vetoes). L5a Tier 1 with an HVAC byte-identity golden (touches `hvac.py`;
HVAC state-of-play gets a one-line write-back). Plan reviews before build per CLAUDE.md: L2 and L3 two framing-disjoint
plus framing G; L1 one plus G; L4, L5 card `next` is the plan.

## 9. Effort summary

| Card | Tier | Builds | Builder-days | In recommended cut |
|---|---|---|---|---|
| L1 G6 one BLE-in-room read | 2-DB | 1 | 4 | yes |
| L2 access edges on G1 | 3 | 2 | 6 (build 1: 3) | build 1 only |
| L3 presence house-state inputs | 3 | 1 | 3 (H1: 1) | H1 only |
| L4 person ids + internals | 2 | 1 | 1.5 | yes |
| L5 presence diagnostic internals | 1-2 | 1 | 2.5 (5a: 0.5) | 5a only (+ 5b ruling) |
| **Total** | | **6** | **~17** | **4 builds, ~9 days** |
