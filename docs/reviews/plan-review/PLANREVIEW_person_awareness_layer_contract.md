# PLAN REVIEW: person-awareness layer contract + leak audit (framings D + G)

Date 2026-11-14. Reviewer: ura-reviewer, framing D (adversarial completeness, diff-blind) and framing G (goal
fidelity). Subject: develop @ 4e3e2ac9, `docs/planning/CONTRACT_person_awareness_layer.md` and
`docs/planning/AUDIT_person_awareness_layer_leaks_2026_11_14.md`. Code read via `git show` / `git grep` on
`release/batch-2`, `develop`, `feature/census-deconfliction-p2-ledger`, `feature/crossing-vision-fast-stage`
(`feature/music-following-repair` has no code commits). Nothing modified except this file. Line numbers are
batch-2 unless a branch is named.

Read first: CLAUDE.md (F1-F5, consumer classes, Registry not name guessing), the charter entries in
`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` as quoted in the contract §0, and manual §5.5 as the
contract cites it. PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md and SENSOR_FLEET_CLASSES.md were NOT re-read completely in
this pass (stated gap); no finding below depends on a presence-doc claim, every one is cited to code.

## Verdict: FIX-CONTRACT

The contract is the right shape and closes the stated drift on paper (an ingest column now exists for every fact).
It is not yet shippable as the arc's layer of record: two of its invariants are stated more strongly than the code
it calls conforming (INV-AWAY-LATENCY, INV-MISSING-NOT-ZERO), its F2 "one ingest" names a function that does not do
the dedup the contract assigns to it, the audit missed the single largest F4-BLE consumer (room occupancy), and three
proposed fixes change what is delivered without saying so.

## 1. Framing D: sites the audit missed

| # | SEV | Site | Invariant | Scenario |
|---|---|---|---|---|
| D1 | HIGH | `coordinator.py:3310-3318` (latch clear "ble_person"), `:4436-4441` (BLE extends room occupancy), `:4998-5003` (`STATE_BLE_PERSONS`) | INV-LAYER-READ | Every room tick on ~40 rooms reads `hass.data[DOMAIN]["person_coordinator"].get_persons_in_room` directly. This is the highest-volume F4-BLE consumer in the package (comfort: lights, occupancy) and the audit lists `coordinator.py` only once, as display D7 (`:1383`). Any G6 migration that misses these leaves the layer's biggest reader outside it. |
| D2 | HIGH | `coordinator.py:4440` vs `_ble_corroboration.py:69-81` | Bug Class #63 concept split inside "BLE persons in room" | Room occupancy uses raw `get_persons_in_room`; fan recheck / zone tier use `trustworthy_persons_in_room`, which drops a person whose `PersonPhoneLeftBehindSensor` is `on`. Phone left in the bedroom, person away: the room-occupancy path keeps extending occupancy while the fan path says no BLE. Contract G6 (`get_persons_in_room(room, active_only)`) does not name which semantics the one read has, so the migration will silently pick one. |
| D3 | MED | `_ble_corroboration.py:34-66` `phone_trustworthy` | INV-LAYER-READ (URA person-awareness entity state as a decision input) | Reads `binary_sensor.*_phone_left_behind` STATE after resolving it from the registry by unique_id. Not in the audit; invisible to R3 because no entity-id literal or f-string appears. Feeds fan recheck L1/L2 and the presence zone-tier gate (comfort). |
| D4 | MED | `presence_fan_recheck.py:1375` `getattr(person_coord, "_area_id_to_room", None)`; `:1384-1386` slug fallback `str(area).lower().replace(" ", "_")` | INV-LAYER-READ (producer private), Registry-not-names | Closes the audit's admitted gap for `:672` and `:1168`: both fetch the person coordinator and pass it to `_l1_persons`, which reads a PersonTrackingCoordinator private and falls back to a slug guess. The `:1168` site cancels a fan recheck mid-flight on that result. R1's intra-function dataflow cannot see it (the object is bound in the caller, read in the callee). |
| D5 | MED | `domain_coordinators/hvac.py:1238-1241` `pc._pre_arrival_enabled = value` | INV-LAYER-INGEST (non-owner write into a layer member) | Closes the other admitted gap. It is a WRITE of a person-coordinator private (BLE pre-arrival enable, F5 producer gating) from HVAC. Toggling HVAC pre-arrival silently turns the BLE F5 producer on/off. R1 detects reads only. |
| D6 | MED | `domain_coordinators/presence.py:7252` trigger set: `geofence_arrive`/`geofence_leave` (`:9888, 9892`), `occupancy_change` (`:3852, 5822`), `camera_detection` (`:5859`), `census_update` (`:5765`), periodic, guest_* | INV-AWAY-LATENCY as worded | Contract §3: "The layer's push channel to house_state is `SIGNAL_CENSUS_UPDATED` only." False today: a raw `person.*` geofence leave drives `_run_inference("geofence_leave")` directly. A builder who enforces the sentence (or routes geofence through G1 / ResidencyTracker, which records only `home <-> not_home` edges with boot/stale rules, `residency.py:10-11, 123-125`) removes or gates an AWAY trigger. Scenario: last resident leaves during the residency boot window; the edge is uncounted; AWAY waits for the next periodic tick. |
| D7 | MED | `camera_stream_health.py:590-647` `VIEW_RELEASED`; consumers `presence.py:843` ("dead past ... HOLD_MAX_S: off"), `:4372`, `occupancy_substrate.py:311, 358`, `camera_census.py:2728-2735` | INV-MISSING-NOT-ZERO as worded ("never 0") | A dead input is HELD for `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` = 900 s (`const.py:6026`, census cap `:6035`) and then counted as OFF. Camera dead 16 min with a sleeping person in view: the zone tier and census now read 0 for that input. The audit lists the S2 readers as conforming. Either the invariant states the cap or the code is a leak; the contract must say which (operator ruling of 11-14, "a dead stream neither creates nor ends occupancy", reads as no release). Side drift: `camera_census.py:2728` comment says 600 s, the constant is 900. |
| D8 | MED | `census_deconflict.py:90-131` (census-p2) | INV-DEDUP | The contract makes `deconflict_house` the F2 ingest that dedups named sightings by slug and bodies by physical camera. The function takes a pre-computed `trust.unidentified_count`, combines guest terms by `max`, and copies `identified_persons`. It has no sighting input and no camera key. The body dedup (Frigate vs Protect on one camera, the pool-overhead four-integration case) happens upstream in `_cross_validate_platforms` (`camera_census.py:2395`), which the audit files as an NVR comparison (P3), not as F2 ingest. INV-DEDUP's own falsifier (one body on family_room + master_hallway counting 2) targets code outside the named ingest. |
| D9 | LOW | `camera_census.py:4760, 4817, 6630` `f"person.{slug.lower()}"`; `person_sighting.py:605`; `transit_validator.py:2020`; `person_coordinator.py:1773`; `perimeter_alert.py:1118` | Registry-not-names, contract §2.6 | Inline `person.` construction instead of `person_ids.tracked_person_entity_id`. Five are inside layer producers (the identity vetoes). A friendly-name person ("Oji Udezue") whose entity id is not the lower-cased slug makes the veto read `None` and fail open. Not in the audit. |
| D10 | LOW | `security.py:2235` watches `async_all("person")` (all persons), `:2273, 2283` | INV-LAYER-READ, scope of S1 | Adds to S1: the listener covers guests and excluded persons (the lock regime filters `_excluded(cfg)`, `security_lock_regime.py:599`), and security also receives `SIGNAL_PERSON_ARRIVING` (`:819`), so one geofence arrival can add the expected arrival twice. |
| D11 | LOW | `const.py:3650` `BLE_TRANSITION_CONFIDENCE = 0.75`, `const.py:315` `CONFIDENCE_HIGH = 0.9` | INV-LAYER-CLASS, Bug Class #63 | Producer confidences equal the notification (0.75) and security (0.9) class thresholds. R8 only catches literals outside `const.py`; a coincidental producer constant crossing a class gate is invisible. State whether a BLE-only crossing is meant to clear notification naming exactly. |
| D12 | LOW | `crossing_vision.py` on census-p2 (`_ledger_terms` `:1052-1065`) and fast-stage (`_write_fast`, provisional rows, `stage` field) | contract §6 item 6 (seam check) | Two in-flight branches both extend `crossing_vision.py`'s F3 attribute store with no named shared owner. Holds today because the fast stage writes rows only (no `apply_term`) and keeps `people_count` None on blank (INV-BLANK). The merge must assert terms come from B rows only, or the provisional row double-applies a crossing. |

Cleared (holds because):
- Audit S1 HIGH: confirmed. `security.py:2254-2288` has no stale-source or boot test; `check_entry` returns
  SANCTIONED for any live expected arrival (`security.py:303-304`) before any census leg.
- INV-LAYER-CLASS inline literals: `git grep` of `(>=|>) 0.(75|9|8|85|7)` over perimeter, transit, sighting, lock
  regime and NM found none; the 8 literal-view sites are the real surface.
- Fast-stage frame source is registry-only (`_fast_image_entities`, by Frigate unique_id), and the B clip path is
  untouched: the clip-path constraint holds on that branch.

## 2. Breaking the code guard (R1-R9)

| Rule | Leak that slips past | Detection change that closes it |
|---|---|---|
| R1 private read | (a) Object bound in caller, private read in callee: the real `_l1_persons` case (D4). (b) `vars(pc)["_x"]`, `pc.__dict__.get("_x")`. (c) WRITES: `pc._pre_arrival_enabled = v` (D5). (d) `self._presence._residency` through `coordinator_manager.coordinators["presence"]` (not a `hass.data[...][K]` key in the list) | Receiver-agnostic: flag any Attribute (Load, Store, Del) or `getattr/setattr/hasattr` constant whose name is in the harvested private set of any member class, outside that class's module; collisions go to the allowlist. Add `coordinators["presence"]` and `coordinator_manager` to the origin keys. Flag `vars(`/`__dict__` on any receiver |
| R2 store read | (a) Public methods that return the store (`get_persons_in_room`, D1) are not store reads, yet they are the same fact outside §4. (b) `getattr(pc, "data")`. (c) `self.coordinator.data` in any `CoordinatorEntity` constructed with the person coordinator (receiver has no `hass.data` origin) | Two lists: store attributes AND member public methods; any call on a member object outside §2.7 + §4 is a hit. Bind `self.coordinator` by scanning `CoordinatorEntity.__init__(coordinator=...)` call sites |
| R3 raw entity | (a) `hass.states.async_all()` with no domain + `.startswith("person.")` (real shape, `presence.py:5315-5317`). (b) Entity id resolved from the registry by URA unique_id (D3). (c) `hass.states.get(tracked_person_entity_id(p))` (the sanctioned id helper feeds a raw read). (d) `async_entity_ids("person")`. (e) Templates: `Template("{{ is_state('person.x','home') }}")`, `async_track_template_result`. (f) Entity lists from config (`CONF_*` person lists) | Dataflow taint from `PERSON_ENTITY_PREFIX`, `tracked_person_entity_id`, `async_get_entity_id(..., DOMAIN, uid)` with a person-awareness unique_id suffix, and `startswith("person."/"device_tracker."/"sensor.bermuda")` filters over `async_all()`. Scan string constants for `states.person`, `is_state('person.` |
| R4 hass.data scan | (a) Helper indirection: `data = self._domain_data(); for v in data.values()` (the actual H3 site, census-p2 `crossing_vision.py:1121-1145`). (b) Comprehension + `getattr` (the canonical S2 getter itself, `camera_stream_health.py:515`; R4 as written flags the owner). (c) `hasattr`, `filter(lambda`, `isinstance(v, RoomCoordinator)` | Any `.values()`/`.items()` iteration whose element reaches `getattr/hasattr/isinstance` with a member-ish name, regardless of where the dict came from; owner row for `camera_stream_health._room_coordinators` |
| R5 literal view | (a) `house_census_view(hass, VIEW_TRUST)` (Name, not Constant). (b) `functools.partial(house_census_view, hass, "trust")`. (c) A class lie: a house_state reader passing `cls="display"` | Accept only `view_for_class(<str literal in CONSUMER_CLASSES>)` or `cls=<literal>`; reject any Name/partial. Pin a per-file declared class map (the conformance table) and fail when the literal differs |
| R6 F5 send | (a) `SIG = SIGNAL_PERSON_ARRIVING` alias or `import ... as _ARR`. (b) `dispatcher_send` (sync) or `hass.helpers.dispatcher`. (c) `hass.bus.async_fire` of an arrival event. (d) No rule at all for the other push channels: `ura_person_egress_event` fires, `SIGNAL_PERSON_SIGHTING`, `SIGNAL_CENSUS_UPDATED`, `ura_person_location_change` sent outside their owners | Resolve the signal VALUE (import the string constants), match all dispatcher/bus send forms, and extend the rule to all five push channels with one owner each |
| R7 F2 write | (a) `setattr(res, "total_persons", n)`, `dataclasses.replace(...)`, `res.__dict__.update`. (b) `census.last_result = CensusResult(...)` (Store on `.last_result`, not a count field). (c) Every other §2 store has no write rule: `pc.data[p]["location"] = ...` (Subscript Store), `_last_sightings[...]`, `CrossingRecord(...)` construction | One write rule per §2 store: Attribute and Subscript Store, setattr/replace, and constructor calls of the store's record type outside the owner |
| R8 confidence literal | (a) `_MIN = 0.75` module-local Name. (b) `0.750`, `3/4`, `> 0.74`. (c) A new `const.py` constant equal to a class threshold (D11; `const.py` is excluded) | Any Compare whose one side names `confidence` must have `CONSUMER_CLASS_MIN_CONFIDENCE[...]` or `min_confidence(...)` on the other side; anything else is a hit. In `const.py`, flag confidence constants equal to a class threshold unless allowlisted |
| R9 person listener | (a) `async_track_state_change_event(hass, self._persons, cb)` with the list built in another method. (b) `hass.bus.async_listen(EVENT_STATE_CHANGED, cb)` + filter in the callback. (c) `async_track_state_change_filtered`, `async_track_template_result`. (d) Polling ledger: a timer that reads `person.*` and compares to a stored `_last_*` dict, no listener at all | Treat the entity-list argument via R3 taint; flag `EVENT_STATE_CHANGED` listeners whose callback reads `entity_id.startswith("person.")`; flag any member-outside module holding a dict keyed by person entity id whose values are states and that is compared on a timer |

Stated limit that must stay stated: AST scanning cannot prove absence for dynamic names. The anti-hollow controls in
audit §5 are good; add one positive snippet per leak above to the parametrised set.

## 3. Framing G: goal fidelity

**One ingest per fact, or re-description?** Mixed.
- F5 (G4 `dispatch_person_arriving`) and F1 edges (G1 `subscribe_resident_edges`) are real consolidations.
- F2 re-describes. `deconflict_house` is named the ingest, but the identity union, the camera body count and the
  platform dedup are computed before it and passed in (D8). The real F2 ingest is `_apply_enhanced_house_census`
  plus its leg resolvers; the contract should name that, and put `_cross_validate_platforms` inside F2 ingest.
- F4-BLE "ingest" is the PersonCoordinator tick, and the read surface is PersonCoordinator public methods wrapped
  by presence (G6), but the largest reader (D1) and the only trust-filtered read (D2) are not mapped. The charter
  says "all consumers can [read]": a read that the 40-room tick does not use is not the layer.
- Evidence services (§2.6) are a good addition, but "no opinion" (`_fold` returns None when no room watches a
  camera, `camera_stream_health.py:517-526`) means a door/garage camera that is no room's input has no health answer
  at all; callers "count the input as before". The contract should say who answers for cameras outside rooms.

**Hard constraints.**
- AWAY fast: at risk through the D6 wording and through G1 if presence's own geofence trigger is moved behind
  ResidencyTracker. Must-fix.
- Vision short-clip path: preserved (§6 item 7; fast stage uses stills as an addition, B clip path intact).
- Dead camera = faulty equipment: the contract states it absolutely, the code releases at 900 s (D7). Must be
  reconciled with the operator, not left implicit.
- Vision + Frigate/Protect deconfliction until vision is trusted: preserved in `deconflict_house`
  (`aware = vis if vision_leads else guest_cam`), but the Frigate-vs-Protect half lives in P3, which the contract
  routes to NVR witness W5b. The contract should state that P3 is F2 ingest and moves only with a byte-identical
  census count test.

**Fixes that silently change delivery.**
1. S1 via G1: residency records only `-> home` and `home ->` edges of residents (`residency.py:10-11`). Security
   today also opens a 30-min window on `not_home -> <named zone>` (`security.py:2280-2288`) and watches guests.
   Moving to G1 drops the approach window and guest arrivals. That may be right, but it is a behaviour change that
   needs an operator line.
2. S5 wiring: `context["census"]` feeds `has_unknown_persons`, which returns ALERT_HIGH even when disarmed
   (`security.py:369-371`) and, in `_handle_census_intent`, locks all doors (`security.py:1104-1115`). "When wired,
   read `view_for_class("security")`" turns on a dormant lock-all-doors path fed by the census, the same census that
   produced the phantom-GUEST class. This is class `access`, not `security`, and must not be wired by a layer card.
   KEEP + DOCUMENT is right; the "when wired" sentence should go.
3. G7 / H3: moving `crossing_vision._held_inputs` to `input_stream_view` imports `VIEW_RELEASED`: after 900 s a dead
   Tier-1 input stops holding the empty anchor, which is the exact "empty anchor fires under a sleeping guest" case
   the audit cites as the reason for G7. Use `input_stream_dead` (no release) or decide D7 first.
4. G6 picking one BLE-in-room semantics (D2) changes either room occupancy or fan veto.

## 4. Side findings verified

- **Security `context["census"]` has no producer: CONFIRMED.** `manager.py:1022-1033` `_build_context` returns
  `house_state`, `house_state_machine`, `timestamp`, `coordinators_active` only; `git grep '"census"'` on batch-2
  finds only `hass.data` keys and the two `context.get("census", {})` reads (`security.py:283, 346`). Consequence is
  larger than "LOW dead": the unknown-person ALERT_HIGH and lock-all-doors paths (`security.py:369-371, 1104-1115`)
  never fire, and the persons_home SANCTIONED leg never fires, so armed entries are sanctioned only by expected
  arrivals (which S1 feeds).
- **S2 stream-health getters on release/batch-2: CONFIRMED.** `camera_stream_health.py:529` `input_stream_dead`,
  `:544` `camera_stream_dead`, `:566` `entity_stream_dead`, `:608` `input_stream_view`, `:633` `entity_stream_view`,
  `:661` `input_room_quarantined`. Not on develop (develop's module ends at `_is_restored`, `:306`) and not on
  census-p2 (`_held_inputs` docstring says so, `crossing_vision.py:1104-1110`). G7 needs census-p2 rebased on
  batch-2.

## 5. Invariant checklist (D)

| Invariant | Result |
|---|---|
| INV-LAYER-INGEST | LEAK: D5 (HVAC writes a person-coordinator private); write rules exist only for F2 (R7) |
| INV-LAYER-READ | LEAK: D1, D3, D4 missed by the audit |
| INV-LAYER-CLASS | PASS on literals; LEAK risk D11 (coincidental producer constants) |
| INV-DEDUP | Mis-anchored: D8 (named ingest does not dedup; P3 does) |
| INV-SEEN-NOT-COUNTED | PASS today (no F4 input to `deconflict_house` exists) |
| INV-ONE-EDGE-LEDGER | LEAK as audited (3 ledgers); G1 fix changes delivery (§3.1) |
| INV-AWAY-LATENCY | Wording false (D6); the invariant itself holds today |
| INV-MISSING-NOT-ZERO | LEAK as worded (D7, 900 s release) |

## 6. Must-fix (contract and audit, before the contract is the arc's layer of record)

1. Rewrite INV-AWAY-LATENCY's channel sentence to the real trigger set (D6) and state that G1 must not gate
   presence's own geofence trigger.
2. Reconcile INV-MISSING-NOT-ZERO with `VIEW_RELEASED` (D7): operator ruling on the 900 s release, then fix the
   invariant or card the code. Specify G7 with `input_stream_dead`, not the view, until then.
3. Re-anchor F2 ingest and INV-DEDUP (D8): name `_apply_enhanced_house_census` + leg resolvers + `_cross_validate_platforms`
   as the F2 ingest; state where the slug and physical-camera keys actually live.
4. Add D1-D5 to the audit table; define G6 as ONE BLE-in-room read with an explicit phone-left-behind semantics and
   list every caller (coordinator.py x3, fan recheck, fan veto, lock, perimeter, music) (D2).
5. Strike "when wired" from S5; reclassify as access, KEEP + DOCUMENT; any wiring is its own Tier 3 card.
6. Mark the S1-via-G1 behaviour changes (approach zone window, guest persons) for an operator decision.
7. Extend R1-R9 per §2 (write contexts, receiver-agnostic private names, public-method reads, R3 taint, all five
   push channels, all §2 stores for R7).
8. Apply contract §6 item 6 to census-p2 vs crossing-vision-fast-stage (D12) before either merges.
