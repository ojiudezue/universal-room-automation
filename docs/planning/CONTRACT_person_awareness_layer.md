# CONTRACT: the person-awareness layer (one ingest point per fact, one read surface, no leaks)

Date 2026-11-14, rev 2. Author ura-planner. Status: contract for operator approval; no code changed. Companion audit:
`docs/planning/AUDIT_person_awareness_layer_leaks_2026_11_14.md` (every site, leak table, code guard).
Rev 2 applies plan review `docs/reviews/plan-review/PLANREVIEW_person_awareness_layer_contract.md` (FIX-CONTRACT,
must-fix §6 items 1-8 and the lower findings) and the operator / orchestrator rulings of 2026-11-14 (§9). Rev 1 is
in git history; this file replaces it.
Code base read: `develop` (v5.108.21) plus `release/batch-2` @ dbff8335 (read API ship 2, stream health S2),
`feature/census-deconfliction-p2-ledger` @ 92e93c54, `feature/crossing-vision-fast-stage` @ a47e4c5b,
`feature/music-following-repair` @ 0ac39b2a (no code commits). Line numbers are batch-2 unless marked. Charter:
`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, "The operator's goals" (incl. the 2026-11-14 entries).
Read completely for this rev: CLAUDE.md (F1-F5, consumer classes, Registry not name guessing), the charter,
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. the §10 corrections ledger; nothing here re-asserts a ledger claim),
`SENSOR_FLEET_CLASSES.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md` §3-§5.5.

## 0. Why this contract exists (the drift, stated once)

Operator, 2026-11-14: "We should look for ways to express that consistency in code after inspecting reuse of existing
work. For [that] we may need a consolidated boundary crossing and person awareness function etc. That all consumers
can [read] and producers can feed?" ... "Unified functions or layers are powerful only if we get it right and make
sure there are no leaks." And: "Keep that resurrected F1-F5 framing front and center... Else we will drift."

The drift began in Claude's restatement on 2026-11-13. The operator asked for one function that "all consumers can
read and producers can feed". Claude restated it as "a reuse-first proposal, not a new layer" and carded
PERSON-AWARENESS-READ-API-1 as read views only. **The ingest half (producers feed through one point per fact) was
never specified.** The arc-map merge check then merged documents, but never tested plans against a layer contract,
so the layer was built as separate "one X" parts: the read API (`presence.py:6006-6060`, `census_view.py`,
`person_ids.py`), `census_deconflict.deconflict_house`, `crossing_ledger.py` fed by `crossing_vision.py`, the
stream-health getters (`domain_coordinators/camera_stream_health.py:529-668`), the planned `nvr_witness` layer, the
sighting store. Each part is sound; nothing proves every producer and consumer goes through them.

This contract therefore makes the INGEST half as concrete as the read half (§2), states the invariants falsifiably
(§3), and defines the check every plan review and the arc-map merge step runs (§6).

### 0a. Why the layer is worth having (utility, judged 2026-11-13, restated 2026-11-14)

On 2026-11-13 a read-only inventory of every F1-F5 producer and reader was run before anything was built, and the
idea was judged good and buildable from what exists. The findings that made the case:
- **Consumers were reaching into internals.** About 20 private census methods were called 40+ times from the transit
  validator, perimeter alerts, sightings and setup. Every one is a place a change to the census can silently break a
  consumer.
- **Person identity was normalized in many places.** Five ID formats; the name-to-`person.*` rule copied inline 14+
  times and the reverse 5 more. It worked in this house only because settings happened to store entity IDs. The worst
  copy fed the census, sightings and the egress BLE leg. One function removes the class of bug.
- **The natural host already existed.** PresenceCoordinator already owned the F1, F4 and F5 getters, the sighting
  producer and the census counts, so the layer is an extension, not a new coordinator.
- **It sets the ceiling the arc works under.** F5 arrivals over 14 days: 152 geofence, 68 BLE, 0 camera faces. F3
  crossings carried a name 30% (entry) / 49% (exit). A single layer is where vision and egress naming raise those
  numbers once, for every consumer, instead of per feature.
- **It is what lets vision lead later.** Census "based entirely on [vision]" only works if vision feeds one
  deconfliction point and every consumer reads one view by class; separate parts would each need re-wiring.
Verdict then: build it reuse-first (carded PERSON-AWARENESS-READ-API-1). What was missed then: the ingest half (§0).

## 1. The layer, in one picture

```
 PRODUCERS (evidence)                INGEST (one per fact)                    STORE                 READ SURFACE (one)
 HA person.* / PersonCoordinator ─▶ F1 level: PersonTrackingCoordinator tick ─▶ .data + overrule ─┐
                                    F1 edges: presence._handle_geofence_change                     │
                                      → ResidencyTracker.feed                ─▶ residency ledger   │
 Census face/BLE legs, egress reg, ─▶ F2 PersonCensus._apply_enhanced_house_                       │
 camera bodies (Frigate+Protect),       census: leg resolvers + union          ─▶ last_result      ├─▶ PresenceCoordinator
 crossing ledger, interior vision,      + _cross_validate_platforms (bodies)       (T + A)         │   read API (§4)
 WiFi, stream-health "missing"          → deconflict_house (term merge)                            │   + view_for_class
 Door cameras, NVR witness, vision ─▶ F3 EgressDirectionTracker.              ─▶ CrossingRecord     │   + push channels
                                      _resolve_direction → _record_crossing      + bus + DB         │     (§4.2)
 Census MQTT faces, zone picks,    ─▶ F4 PersonSightingProducer._emit (camera) ─▶ sighting store   │
 egress projection, BLE room            PersonTrackingCoordinator tick (BLE)   ─▶ .data location   │
 geofence / BLE / camera_face      ─▶ F5 dispatch_person_arriving()            ─▶ (event only)    ┘
 Stream health, NVR witness        ─▶ (evidence services, §2.6; not facts)
```

Rule of the picture: a producer never writes a store directly unless it IS that store's owner; a consumer never reads
a store, a producer internal, a raw producer entity, a URA person-awareness entity's state, or a hass.data object for
a person-awareness decision. It reads §4.

## 2. Per fact: producers, the ONE ingest point, store, provenance, read surface, forbidden paths

Consumer classes (manual §5.5(b), plus the two trust classes the plans use): `security` (de-escalate / annotate
only, identity ≥ 0.9), `access` (lock / alarm actuation, incl. alarm suppression and lock-all; reads trust, never F4
alone), `house_state` (AWAY, ARRIVING, SLEEP, GUEST), `comfort` (room occupancy, HVAC, fans, music, lights),
`notification` (naming ≥ 0.75), `display` (none). `suggestion` = `display`. Every reader declares exactly one class.

### 2.1 F1 — P is home (level) and P's home/away edges

| | |
|---|---|
| Producers allowed | HA `person.*` (external, raw); `PersonTrackingCoordinator` BLE-over-GPS overrule (`_gps_home_overruled`) |
| ONE ingest point | Level: `PersonTrackingCoordinator._async_update_data` (the only writer of `.data` and the overrule set). Edges: `PresenceCoordinator._handle_geofence_change`, the only `person.*` state listener allowed to turn a raw state change into an edge. It does two things and both stay: (a) `ResidencyTracker.feed` (edge records), (b) the direct house-state triggers `_run_inference("geofence_arrive" / "geofence_leave")` (`presence.py:9888, 9892`). (b) is the AWAY fast path and is never moved behind (a) or behind G1 (INV-AWAY-LATENCY) |
| Store(s) | `PersonTrackingCoordinator.data` / `_gps_home_overruled`; the residency ledger (`residency.py`, `_last_real`, `memory_episodes` `person_arrival` / `person_departure`) |
| Provenance / confidence | level: `source` (`gps` / `ble_overrule` / `raw`), tracker sources; edge: `counted`, `source_stale`, `in_boot_window`, `resident_set_resolved` |
| Read surface | Level, trust: `get_residents_home(zone_persons=None)`, `get_residents_home_count()`, `persons_home_for_trust`, `person_state_for_trust` (`person_coordinator.py:141-188`, `presence.py:5473-5514`). Edges: `get_recent_resident_arrival`, `get_residency_snapshot` (`presence.py:5516-5543`) and NEW `subscribe_person_edges(callback, *, persons, kinds)` (§5 G1) |
| Deliberate separation | level (trust state) vs edge (raw state). Bug Class #63. Never merged into one value |
| Forbidden | any second `person.*` state listener that derives an arrival/departure (today: lock regime, perimeter, security geofence listener); any second `_last_real` ledger; reading `person.*` raw for a level decision outside `person_state_for_trust` |

Identity vetoes (census face-leg veto, egress veto, sighting `person_state_at_emit`) read raw `person.*` by design.
They are layer-internal producer reads (§2.7), allowed only inside the producer modules listed in §2.7, and they
build the entity id with `person_ids.tracked_person_entity_id`, never inline (audit D9).

### 2.2 F2 — who is in the house now (trust view F2-T and awareness view F2-A)

What the code actually does (review D8, code wins over rev 1): the body dedup and the identity union happen BEFORE
`deconflict_house`. `deconflict_house` (`census_deconflict.py:90-131`, census-p2) takes a pre-computed
`trust.unidentified_count`, combines guest terms by `max`, and copies `identified_persons`; it has no sighting input
and no camera key. So the F2 ingest is a PAIR, and rev 2 names both halves.

| | |
|---|---|
| Producers allowed | named: face legs, BLE persons, egress registrations (F3 → F2); body terms: camera bodies (Frigate and Protect on one physical camera), crossing ledger `guest_vis`, interior vision room counts (planned), WiFi guest phones (corroborator), stream health / NVR witness "missing" marks |
| ONE ingest point (the pair) | **(1) `PersonCensus._apply_enhanced_house_census`** and the resolvers it calls: named evidence via `_resolve_face_legs` / `_resolve_ble_legs` into the union (`_normalize_name_set`, canonical slug: `camera_census.py:2533-2540`; synthetic face legs dedup by `(canonical_slug, engine, base_stem)`, `:3576-3588`), egress registrations via `register_egress_face` / `evict_egress_face` (`:4381, 4456`), and camera bodies via `_cross_validate_platforms` (`camera_census.py:2395`), which is where one body seen by Frigate and Protect on the same camera is counted once. **(2) `census_deconflict.deconflict_house`** (`camera_census.py:6665-6693` call site on census-p2), which merges the trust counts with the pulled body terms. Body terms are PULLED at that one call site from registered term providers (today `crossing_vision.census_tick(...)`, `camera_census.py:6644`); no provider pushes a count into the census. `deconflict_house` is the ONLY place where F4 or vision evidence meets F2 |
| Where each dedup key lives | canonical slug: the union in (1); same physical camera (Frigate vs Protect, pool-overhead four-integration case): `_cross_validate_platforms` in (1), moving to `nvr_witness.platform_for` at W5b; crossing `source_ref`: the ledger term provider feeding (2); a future named sighting term: (2), slug key, adds nothing when the slug is already in the union |
| Store | `PersonCensus.last_result` (house `CensusZoneResult`: trust fields + `aware_*`) and the DB `census_snapshots` row |
| Provenance / confidence | `count_provenance` ∈ {camera, vision, agree}, `aware_agreement`, `source_agreement`, `confidence`, `as_of`, `camera_input_dark` |
| Read surface | Pull: `PresenceCoordinator.get_house_census(view)` / `census_view.house_census_view(hass, cls=...)`, view chosen ONLY by `view_for_class(cls)`. Push: `SIGNAL_CENSUS_UPDATED` (F2-T counts) |
| Deliberate separation | F2-T vs F2-A; promotion ladder `PLANNING_census_deconfliction.md` §3.2; F4 sightings are terms in (2), never a second union |
| Change control | `_cross_validate_platforms` is F2 ingest: it moves to NVR witness (W5b) only with a byte-identical house-count test over a recorded fixture (charter: "vision and frigate/protect person counts with deconfliction. Until we trust vision") |
| Forbidden | any writer of `CensusZoneResult` count fields outside (1)/(2); a producer calling into the census to set a count; any reader of `census.last_result`, census privates, or the census entities' states for a decision; a reader passing a literal view instead of a class |

### 2.3 F3 — door crossing + identity attach (and F3 attributes)

| | |
|---|---|
| Producers allowed | door camera person legs (via `CameraResolver`), NVR witness corroboration (W2, planned), egress identity join (face / BLE legs from the census evidence API), crossing vision (F3 ATTRIBUTES only: `people_count`, provisional arrival record) |
| ONE ingest point | `EgressDirectionTracker._resolve_direction` → `_record_crossing(CrossingRecord)` + bus fire `ura_person_egress_event` (`transit_validator.py:2214`) + DB `person_entry_exit_events`. Amendments and attributes: NEW `EgressDirectionTracker.attach_crossing_attribute(source_ref, changes, provenance, *, camera, role, row_id=None, payload_extra={})` (G3), the ONE owner-side amend primitive for any field of a stored record (identity confirmation, exit backfill, pair resolution, vision attributes; `(source_ref, key, value, provenance)` = `changes={key: value}`); its sole push is `SIGNAL_EGRESS_RECORD_AMENDED` (§4.2). Until it exists the vision row store in `crossing_vision` keyed by the crossing `source_ref` is the attribute store, read only through `get_last_arrival_record()` |
| Store | `CrossingRecord` ring (tracker; one ring per egress camera, `EGRESS_CROSSING_RING_PER_CAMERA` records / `EGRESS_CROSSING_RING_MAX_AGE_S`, amended in place by `source_ref`, the "last crossing" pointers move only if the amended record is still the newest), DB rows, crossing-vision rows (single owner: §5 G8). Additive record fields (written only through G3): `identity_role`, `nameable`, `pair_state` (`none`/`pending`/`clear`/`conflict`), `pair_partner`, `identity_synthetic_corroborated` |
| Provenance / confidence | `identity_provenance` (values in `IDENTITY_PROVENANCE_VALUES`, adding `face+residency`, `face+ble_move`, `face+gps` for step 7), `identity_confidence`, `agreement_class`, `confidence`, `platforms_fired` (→ NVR families after W2) |
| Read surface | Pull on presence, delegating to the tracker: `get_last_crossing(camera)` (`presence.py:6043`), NEW `get_crossings_since(t, camera=None)` (G2, served from the ring, oldest first), NEW `get_crossing(source_ref)`, NEW `door_camera_device_ids()` (registry `device_id` of each egress entity), `get_last_arrival_record()`. Push: `ura_person_egress_event`, `SIGNAL_EGRESS_RECORD_AMENDED` (listeners allowed) |
| Class rule | An EGRESS-DERIVED identity whose record `pair_state` is `pending` or `conflict` does not qualify for the security class (perimeter's own face-leg evidence is outside this rule; named residual in the step 7 plan §12) |
| Forbidden | a consumer keeping its own crossing cache from the bus (perimeter `_note_egress_identity`); reading `hass.data["egress_tracker"]` attributes (`_egress_entities`, `_interior_neighbours_by_group`) outside the tracker; F3 provenance stored on the census object (`set_egress_identity_last_attach`) |

The one arrival/departure notification `_arrival_departure_notify` lives inside the producer today (a consumer of
class `notification` hosted in the F3 owner). It is an allowlisted exception until step 7 (EGRESS-DIRECTION-AWARE-IDENTITY-1)
moves it to `ArrivalNotifier` (`domain_coordinators/arrival_notify.py`, class notification), which becomes the
notification consumer and the single door-naming send site, perimeter's door-camera identity send included (§7).

### 2.4 F4 — P seen at X at T (camera sighting, BLE room, unnamed body sighting)

| | |
|---|---|
| Producers allowed | census MQTT face bridge, zone-camera face picks, egress projection (camera); Bermuda/IRK room (BLE); interior vision (unnamed body records, planned) |
| ONE ingest point | Camera / egress / interior: `PersonSightingProducer._emit` (`person_sighting.py:565`); interior vision adds `_emit_unnamed` ON THE SAME PRODUCER, not a sibling store. BLE room: `PersonTrackingCoordinator._async_update_data` (writes `location`, `previous_location`, fires `ura_person_location_change`) |
| Store | sighting store (`_last_sightings`), `PersonTrackingCoordinator.data[...]["location"]`; interior unnamed stores (VISION-INTERIOR-SIGHTINGS-1 ship 1, owner `person_sighting.py`): `_room_sightings`, `_path_records`, `_vision_counts` (and `_room_descriptions` from ship 2), written only by `_emit_unnamed(kind, payload)`, which sends no channel |
| Provenance / confidence | sighting `source`, `camera`, `zone`, `census_veto`, `confidence`; BLE `method`, `confidence`, `tracking_status`, `bermuda_area` |
| Read surface | Camera: `get_last_person_sighting(s)` (`presence.py:5987-5993`). BLE: the ONE BLE-in-room read (§2.4a), `get_person_location(name)`, `get_zone_occupants`; push `SIGNAL_PERSON_SIGHTING`, `ura_person_location_change` |
| Deliberate separation | **seen (F4) vs counted (F2).** F4 meets F2 only as a term inside `deconflict_house` (§2.2 (2)). No F4 store is read by the census elsewhere, and no F4 value reaches a house_state or access decision except through F2 or an access corroboration predicate (`face_input_corroborated`) |
| Forbidden | `TransitValidator._camera_sightings` as a second named store (legacy, unidentified-only; DELETE once `transitions.py` path validation moves to F4); `person_coordinator.data` reads outside the owner and its own display entities; access acting on F4 alone |

#### 2.4a The ONE BLE-person-in-room meaning (review D1/D2)

Today two meanings coexist (Bug Class #63): room occupancy reads raw `get_persons_in_room`
(`coordinator.py:3315, 4440, 5003`, plus display `:1385`), while fan recheck and the zone tier read
`_ble_corroboration.trustworthy_persons_in_room` (`_ble_corroboration.py:69-81`), which drops a person whose
`PersonPhoneLeftBehindSensor` reads `on`. Presence carries two inline twins of the same filter (`presence.py:4830`
zone tier, `:7355` inference) plus `_phone_left_behind_on`.

**Contract meaning (recommended): "persons in room R" = BLE persons whose resolved location is R, minus any person
whose phone-left-behind sensor reads `on` (fail-open: missing / unknown / unavailable keeps the person).** One read:
`PersonTrackingCoordinator.persons_in_room(room, *, active_only=False)` (G6) with the filter inside it, using the
registry-resolved `phone_trustworthy` predicate (moved from `_ble_corroboration.py:34-66`, which becomes a re-export).
All readers use it: room occupancy (`coordinator.py:3315, 4440, 5003, 1385`, class comfort), fan recheck, fan veto,
zone tier, lock regime, perimeter, music, presence inference.
**Built (VISION-INTERIOR-SIGHTINGS-1 ship 1, plan §14 seam; no reader migrated, that stays G6):** returns a
`tuple[str, ...]` of person names (the names `get_persons_in_room` returns); `active_only=True` keeps only persons whose
`tracking_status == TRACKING_STATUS_ACTIVE`. The filter is `_ble_corroboration.phone_trustworthy` called from
`person_coordinator.py` (not moved: three test files load `_ble_corroboration.py` standalone, so a module-level import
of `person_coordinator` there would break them; one predicate either way).

- **Behaviour change for room occupancy (needs an operator yes, §9 Q1).** A person whose phone-left-behind sensor
  reads `on` stops extending room occupancy (BLE hold, `:4440`), stops clearing the radar latch as `ble_person`
  (`:3315`) and drops out of `ble_persons` (`:5003`). Expected to be rare, because the sensor's own D9 carve-out
  (`binary_sensor.py:2184-2213`) keeps it off while the BLE room reads occupied, so the change bites only at edges
  (sensor-update lag, room vacated by another path). Gate: a one-shot recorder probe (7 days: ticks where a room was
  BLE-held by a person whose `*_phone_left_behind` read `on`) runs before the build; zero or near-zero = ship, else the
  operator decides with the count in hand. If the operator says no, room occupancy keeps the raw read as a named,
  allowlisted second meaning (`persons_in_room(..., phone_filter=False)`), never an unnamed one.
- **Scanner-area union is a derived read, not a second meaning.** Fan recheck L1 adds persons in rooms whose area is in
  this room's `CONF_SCANNER_AREAS` (presence doc §6 item 3: "deliberately differs... do not align them"). It stays,
  as `persons_in_room_or_scanner_areas(room)` built on the one read, with the area→room map from a public
  `room_for_area(area_id)` (replaces the private `_area_id_to_room` read and the slug fallback at
  `presence_fan_recheck.py:1375-1386`, audit C5).
- Presence inference twin (`presence.py:7355`) is house_state: it is migrated only inside the Tier-3 H2 snapshot work,
  with its existing parity test; until then it is an allowlisted twin.

### 2.5 F5 — P is arriving

| | |
|---|---|
| Producers allowed | geofence edge (presence), BLE pre-arrival (PersonCoordinator), the one camera site `_derive_face_arrival`, `camera_egress` (D8, planned) |
| ONE ingest point | NEW `signals.dispatch_person_arriving(hass, PersonArrivingPayload)` (G4). Today three raw `async_dispatcher_send(SIGNAL_PERSON_ARRIVING, dict)` sites (`presence.py:5678, 5937`, `person_coordinator.py:1172`) |
| Producer enable | BLE pre-arrival is gated by `PersonTrackingCoordinator._pre_arrival_enabled`; HVAC writes that private today (`hvac.py:1241`). It becomes a public setter `set_pre_arrival_enabled(value)` on the owner (G9) |
| Store | none (event); edge corroboration via residency (F1) |
| Provenance | `source` ∈ {geofence, ble, camera_face, camera_egress}; camera-derived sources need corroboration (`arrival_edges.arrival_source_needs_corroboration`) |
| Read surface | `SIGNAL_PERSON_ARRIVING` read through `PersonArrivingPayload.from_signal` (`signals.py:28-64` on release/batch-2; the class is not on develop until batch 2 merges). Step 7 extends it only with additive `ts=None` and `to_signal()` (today's dict keys exactly), used by G4 |
| Forbidden | any consumer deriving its own arrival from `person.*` (security `_handle_person_state_change`, `security.py:2255`); camera-derived arrival acting alone on access |

### 2.6 Evidence services (not facts; feed facts through their ingest points)

| Service | One read | Consumers allowed | Forbidden |
|---|---|---|---|
| Camera input stream health | `camera_stream_health.input_stream_dead / camera_stream_dead / entity_stream_dead / input_stream_view / entity_stream_view / input_room_quarantined / input_room_stuck_excluded` (`:529-668`; the last added by crossing vision P3-D8, room getter `camera_input_room_stuck_excluded`, stuck clients only) | room fusion, zone tier, fan recheck, census (as "missing"), crossing ledger held-input check (dead/view, never released-as-off, §3 INV-MISSING-NOT-ZERO), NVR witness | scanning `hass.data[DOMAIN]` for an object with a matching attribute outside `camera_stream_health._room_coordinators` (its owner row); re-deriving availability |
| Camera twin rule (ship 3b) | `camera_twin_health.physical_camera_dead(hass, entity_or_device)` (every paired NVR device lost; pages and diagnostics only); the one room-input list `camera_stream_health.room_stream_input_entities(hass, entry)` (room config entry lists plus the camera manager's area lookup); the one stuck-signal PAGE key `camera_stream_health.page_camera_key(er, dr, device)` (pure: the Frigate camera of a W1-paired device, else the device's own camera) | the camera stream-health pages (room trackers, the twin owner), diagnostics | a reader substituting a twin's reading (option A); a page key built from the owner's map or from an entity-id string; a hold, view or anchor reading `physical_camera_dead` |
| NVR witness (W2, planned) | `nvr_witness.family_of`, `corroborated(cam, t, window)`, `families_on_now`, `platform_for` | the 4 comparison sites (census `_cross_validate_platforms`, transit `_count_platforms_fired` `transit_validator.py:2733`, perimeter `_apply_single_source_gate` `perimeter_alert.py:5038`, room fusion agreement `binary_sensor.py:1837-1868`) | entity-name suffix family tests; per-site classifiers |
| Identity evidence (census) | public `PersonCensus` methods: `resolve_face_legs`, `resolve_ble_legs`, `tracked_person_slugs` (batch-2 `camera_census.py:4061`), `egress_identity_enabled` (`:4085`), `canonical_person_slug`, `known_face_guests`, `face_person_would_be_vetoed`, `face_suppressed_now` | layer producers only: egress tracker (F3), sighting producer (F4), perimeter D10.5 (until it reads F3/F4 instead) | any consumer outside the producer list deciding on raw legs |
| Person id rule | `person_ids.tracked_person_entity_id / slug_of / display_of / entity_key_slug` | everyone | inline `f"person.{slug.lower()}"`, `lower().replace(" ", "_")`, `.title()` inverses |
| Phone left behind | `phone_trustworthy(person)` (registry-resolved by unique id, fail-open; §2.4a) | the one BLE-in-room read; presence inference twin (allowlisted) | reading `binary_sensor.*_phone_left_behind` state anywhere else |
| Interior camera evidence (VISION-INTERIOR-SIGHTINGS-1 ship 1) | `PersonCensus.area_evidence()` (copies: per-entity last reading `by_entity`, display-only area contributions / house bodies, `as_of`); ship 3b `camera_stream_health.entity_stream_view(hass, eid, census=True)` and `camera_twin_health.physical_camera_dead` (display field `liveness`) | layer members only (the sighting producer) | a record source other than `by_entity`; the per-area contributions as a record source |

**Cameras outside rooms (review §3).** Stream health answers only for cameras that are some room input's own camera
(`_fold` returns None otherwise, `camera_stream_health.py:517-526`), so a door or garage camera that is no room's
input has no health answer and callers count it as before. Rev 2 records this as a known gap, owned by NVR witness
W2 (`camera_stream_dead` is its declared camera-keyed getter): W2 must extend the camera-keyed answer to every egress
and perimeter camera before any F3 or perimeter consumer may treat "no answer" as "live".

### 2.7 Layer members (who may touch stores)

Owners: `person_coordinator.py` (F1 level, F4-BLE, phone-left-behind predicate), `residency.py` +
`presence._handle_geofence_change` (F1 edges), `camera_census.py` + `census_deconflict.py` (F2),
`transit_validator.EgressDirectionTracker` (F3), `crossing_vision.py` + `crossing_ledger.py` (F3 attributes, F2 term
provider), `person_sighting.py` (F4), `presence.py` read API block and `_derive_face_arrival` (read surface, F5),
`signals.py`, `census_view.py`, `person_ids.py`, `arrival_edges.py` (pure rules), `camera_stream_health.py`,
`nvr_witness.py` (planned), `interior_vision.py` (`InteriorVisionSampler`, VISION-INTERIOR-SIGHTINGS-1; ship 1 ships
the pure core only, the sampler class arrives with the vision ships). A member may read another member's PUBLIC methods; it may read its OWN store. An owner's
own display entities (census sensors in `sensor.py`, person location sensors) may read the owner's store under a
counted allowlist (owner-display exemption), never for a decision.

## 3. Layer invariants (falsifiable)

- **INV-LAYER-INGEST.** No module writes a person-awareness store or a layer member's private state (§2 "Store",
  member privates) except its owner, and no producer reaches a fact except through its ingest point. Falsified by: a
  non-owner Store / setattr / Subscript store / record-type construction on a `CensusZoneResult` count field,
  `census.last_result`, `PersonTrackingCoordinator.data`, `_last_sightings`, a `CrossingRecord`, or any member
  private (today: `hvac.py:1241` writes `pc._pre_arrival_enabled`); a `SIGNAL_PERSON_ARRIVING` send outside
  `dispatch_person_arriving`; any of the six push channels (§4.2) sent outside its owner; a second `person.*`
  listener that produces an edge or arrival (today: 3, audit S1, S2, S7).
- **INV-LAYER-READ.** No module outside §2.7 reads, for a person-awareness decision or display: a store, a producer
  private (`_x` on a member object, however the object was obtained: hass.data, coordinator manager, a function
  argument, `self.coordinator`), a member's public method outside §4 (e.g. `get_persons_in_room` from a room
  coordinator), a `hass.data[DOMAIN]` member object other than through §4, a raw `person.*` / `device_tracker.*` /
  Bermuda / Frigate / Protect person entity (including ids built by `tracked_person_entity_id` or resolved from the
  registry), or a URA person-awareness entity's state. Falsified by any such read not on the guard allowlist
  (audit §5).
- **INV-LAYER-CLASS.** Every consumer read of F2 goes through `view_for_class(cls)` with a declared class literal from
  `CONSUMER_CLASSES`; every identity-confidence comparison reads `CONSUMER_CLASS_MIN_CONFIDENCE[cls]` /
  `min_confidence(cls)`. A producer confidence constant equal to a class threshold is allowlisted with its intent
  stated (today `BLE_TRANSITION_CONFIDENCE` 0.75 = notification bar, `const.py:3650`; §9 Q3). Falsified by a literal
  or Name view argument, a `partial` over `house_census_view`, an inline confidence threshold, or a reader whose
  declared class differs from the conformance table.
- **INV-DEDUP.** One body or face counted once: for any evidence set, adding evidence whose id duplicates one present
  (same canonical slug; same physical camera within the window; same crossing `source_ref`) changes neither F2 view.
  The slug and crossing keys are tested at the two ingest halves (§2.2); the physical-camera key at
  `_cross_validate_platforms`. Falsified by the same face as a census leg AND a sighting term raising the count, one
  body seen by Frigate and Protect on one camera counting 2, or one body on family_room + master_hallway counting 2
  (tests named in `PLANNING_census_deconfliction.md` §4, plus a `_cross_validate_platforms` same-camera test).
- **INV-SEEN-NOT-COUNTED.** F4 reaches F2 only inside `deconflict_house`. Falsified by any F4 store or
  `SIGNAL_PERSON_SIGHTING` read inside `camera_census.py` outside the term-provider pull, or by a sighting moving a
  house_state input.
- **INV-ONE-EDGE-LEDGER.** One F1 edge ledger (residency). Falsified today: residency `_last_real`, lock regime
  `_last_real`, perimeter `_person_arrivals` (3 ledgers; audit S2, S7).
- **INV-AWAY-LATENCY (hard, operator: "I need away to be fast acting").** Every push into house state is named, and
  no layer change removes one, delays one, gates one behind a slower path, or changes `_run_inference` call count or
  timing. The pushes into `presence._run_inference` today (`presence.py:7252` trigger set): `geofence_arrive` /
  `geofence_leave` direct from `_handle_geofence_change` (`:9888, 9892`); `census_update` from
  `SIGNAL_CENSUS_UPDATED` (`:5765`); `occupancy_change` (`:3852, 5822`); `camera_detection` (`:5859`); the periodic
  tick; the guest_* triggers (`guest_left_button` etc.). No layer fix may route AWAY through anything slower than
  today's path: in particular G1 / ResidencyTracker (boot window, stale rules, resident-only, `residency.py:10-11,
  123-125`) never sits in front of the direct geofence trigger. Falsified by a missing trigger, a trigger now
  dependent on a G1 callback, an added await/debounce before `_run_inference` on any of these paths, or a changed
  count on the golden inference replay.
- **INV-MISSING-NOT-ZERO (operator ruling 2026-11-14: "A dead input holds").** A dead/unhealthy evidence source is
  never read as zero before its cap: it is missing in every term and every comparison, and a held input neither
  creates nor ends occupancy. After `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` (900 s, zone; `const.py:6026`) or
  `CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S` (900 s, census; `:6035`) it releases (`VIEW_RELEASED`, counted off) and
  pages HIGH (`camera_stream_hold_released`, one per outage). Exception, orchestrator ruling: the crossing-ledger
  empty-house anchor never uses the released view; a dead Tier-1 input blocks the anchor for as long as it is dead
  (the anchor is not time-critical; a sleeping guest in front of a dead camera must not let it fire). Falsified by a
  dead input read as 0 / off before its cap, a release without the HIGH page, or the anchor firing while any Tier-1
  input's view is HELD or RELEASED.
  **Crossing vision P3-D8 (built 2026-11-15, `feature/crossing-p3-first`, operator yes 2026-11-15):** a LIVE Tier-1
  input (reads `on`, no stream view) that its room excludes under a STUCK client (`CROSSING_VISION_ANCHOR_STUCK_CLIENTS`
  = `p22_continuous`, `chatter` (act mode), `stuck_dutycycle` (promoted); read through
  `camera_stream_health.input_room_stuck_excluded`) no longer holds the anchor (listed `held_ignored_stuck`). This is not
  a dead input: a dead input (non on/off state, or any stream view) still holds even when also stuck-excluded, and the
  camera-stream client never releases. Kill switch `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK`. `p22_continuous` does not
  release in `CROSSING_VISION_ANCHOR_P22_HOLD_STATES` (sleep / waking / home_night); an input listed in several rooms
  releases only when every listing room stuck-excludes it.
  **Ship 3b (built 2026-11-14, `feature/layer-ship3b`; plan `PLANNING_person_awareness_layer_ship3.md` §6):**
  (a) *Device liveness.* A camera-derived input's "own camera" is its registry camera DEVICE
  (`CAMERA_STREAM_DEVICE_LEVEL_INPUTS`, decided Q12): live if any enabled `camera.*` entity on it reads live; dead on a
  tick only if no member is live, one reads `unavailable` (not restored) and its stamp (keyed by device id) passed the
  grace. So the 10 multi-channel Protect / Reolink person sensors that reach readers get the same hold, cap and
  release as Frigate inputs. (b) *Unwatched cameras.* The census interior and zone camera entities no room watches
  (the unwatched set U, live: the foyer group) are stamped and held by ONE house tracker owned by
  `camera_twin_health.CameraTwinHealth` (`CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED`); the house readers ask it only when
  no room has an opinion and only for an entity in U ∪ sticky. (c) *Pages, rule 2.* A camera is reported dead (HIGH)
  only when EVERY paired NVR device has lost it (`physical_camera_dead`, W1 pairs with an NVR-platform check); one NVR
  down with the other covering sends ONE MEDIUM `camera_stream_nvr_down_twin_covering` notice per member episode
  (`CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED`), never a HIGH. No reader takes a twin's reading (option A; per-reader
  coverage parked as DEAD-CAMERA-TWIN-COVERAGE-1).

## 4. The read surface (one place, by class)

### 4.1 Pull API on `PresenceCoordinator` (reached as `coordinator_manager.coordinators["presence"]`; display entities may call the pure module functions it delegates to)

| Fact | Method | Exists |
|---|---|---|
| F1 level | `get_residents_home(zone_persons=None)`, `get_residents_home_count()`; push `PersonTrackingCoordinator.async_add_listener` (HA coordinator update; listed listeners only, §4.2) | yes |
| F1 edges | `get_recent_resident_arrival`, `get_residency_snapshot`, NEW `subscribe_person_edges(cb, *, persons, kinds)` (push), NEW `get_person_edges_since(t, *, persons, kinds)` (pull over the same `ResidencyTracker.recent` ledger, no second store; plain tuple, `edge_ts >= t`, oldest first, `t` float epoch seconds) + `person_edges_truncated_since(t)`; every edge carries `counted` | G1 BUILT ship 3a D2 (phase 2) |
| F2 | `get_house_census(cls=...)` / `census_view.house_census_view(hass, cls=...)` (the view chosen by `census_view.view_for_class`) | BUILT ship 3a D4; six display callers stay on the literal trust view (Q3) |
| F3 | `get_last_crossing(camera)`, `get_crossings_since(t, camera=None)` (plain tuple of `CrossingRecord`, `ts >= t`, oldest first, `t` a `datetime`; covers at most `EGRESS_CROSSING_RING_MAX_AGE_S` and 32 records per camera, only since the tracker's creation, so no truncation read), `get_crossing(source_ref)`, `get_last_arrival_record()`, `door_camera_device_ids()`, `door_entry_entities()` / `door_neighbours_for_stem(stem)` (G5: entities, not areas, because the lock and perimeter resolve areas with different functions) | BUILT ship 3a D3 (G2, A3, A9, G5) |
| F4 | `get_last_person_sighting(s)`; unnamed interior records `get_room_sightings()` / `get_last_path_records()` (VISION-INTERIOR-SIGHTINGS-1 ship 1; display class, pinned readers); BLE via `get_person_location(name)`, `get_person_previous_seen(name)` (`person_coordinator.py`), `persons_in_room(room, active_only=False)`, `persons_in_room_or_scanner_areas(room)`, `location_moves_since(t)` on `PersonTrackingCoordinator`, with presence delegates `location_moves_since` / `location_moves_truncated_since` that never raise (plain tuple of frozen `PersonMove(person_entity, from_room, to_room, ts, method)`, `ts >= t`, oldest first, `t` a `datetime`) + `location_moves_truncated_since(t)` (True also when `t` is before the log's creation or older than `PERSON_LOCATION_MOVES_MAX_AGE_S`; on truncation, re-read `get_person_location`); push `TransitionDetector.async_add_listener` (listed listeners only) | moves BUILT ship 3a D4; G6 rest on G6-ONE-BLE-ROOM-READ-1 |
| F5 | push only: `signals.subscribe_person_arriving(hass, cb)` (sync `cb(PersonArrivingPayload)`, delivered inline) | BUILT ship 3a D1 |
| class | `view_for_class(cls)`, `min_confidence(cls)` (wraps `CONSUMER_CLASS_MIN_CONFIDENCE`; None for a class with no bar) | `min_confidence` BUILT ship 3a D4 |
| F4 / F1 public reads ruled legitimate at the guard's first run (plan rev 3.3 §12, §17 (b)) | person coordinator `get_person_confidence`, `get_persons_in_zone`, `get_tracked_person_count`, `get_person_previous_location`, `get_person_previous_location_time`, `get_diagnostic_data` (display class); presence `should_veto_due_to_reliable_signals` (comfort / house_state, zone fallback) and `check_zone_occupancy_confidence` (comfort, HVAC D6 confirmation) | existing methods, on the read list since ship 3a (guard R2 does not flag them) |
| evidence (ship 3b) | `PersonCensus.interior_camera_entities()` (the resolved census interior person sensors), `PresenceCoordinator.zone_camera_entities()` (zone camera tier cameras plus the Zone Manager `zone_cameras` picks, the HVAC D6 Source 3 list): read by the camera twin owner for its unwatched set U | ship 3b |

Change to make INV-LAYER-CLASS enforceable: `house_census_view(hass, cls=...)` takes a CLASS, not a view, and calls
`view_for_class` itself (the boot-window reason display entities call the module function stays valid).

### 4.2 Push channels (one owner each; the only listeners allowed)

| Channel | Fact | Owner (only sender) | Listed listeners |
|---|---|---|---|
| `SIGNAL_CENSUS_UPDATED` | F2-T counts | `camera_census.py` | presence (house_state), `binary_sensor.py`, `sensor.py` (display) |
| `ura_person_egress_event` (also through the module-local `EGRESS_EVENT` constants of `person_sighting.py` and `crossing_vision.py`) | F3 | `EgressDirectionTracker._resolve_direction` | the four egress display sensors (`sensor.py`), the sighting producer, crossing vision; perimeter's 600 s cache is an allowlist row (S6) |
| `SIGNAL_EGRESS_RECORD_AMENDED` | F3 record amended (`role` ∈ `arrival_confirmed`, `exit_backfilled`, `pair_resolved`, crossing-vision attribute roles; payload `{role, source_ref, row_id, person_id, egress_camera, **payload_extra}`, `payload_extra` wins on a clash) | `transit_validator._send_record_amended`, reached only through G3 `EgressDirectionTracker.attach_crossing_attribute` / `transit_validator.amend_crossing` (BUILT ship 3a D3). Replaced `SIGNAL_EGRESS_EXIT_BACKFILLED` (deleted); its sender `_backfill_exit_identity` sends `role="exit_backfilled"` | the two exit-backfill display readers (Persons Exited Today, Last Person Exit; act on `role == "exit_backfilled"`); pre-listed for step 7 A5: the four egress display sensors and the sighting producer |
| `SIGNAL_PERSON_SIGHTING` | F4 camera | `PersonSightingProducer._emit` | none (operator Q5) |
| `ura_person_location_change` | F4 BLE | `PersonTrackingCoordinator` (the one move site) | `transitions.py` (learning, display) |
| `SIGNAL_PERSON_ARRIVING` (`PersonArrivingPayload`) | F5 | `signals.dispatch_person_arriving` (BUILT ship 3a D1; the three producers send through it) | hvac (comfort), `domain_coordinators/music_following.py` (comfort), security (access), the connect inside `subscribe_person_arriving` |
| `SIGNAL_RESIDENCY_EVENT` (census-p2) | F1 edges | `presence._feed_residency` | only the connect inside `subscribe_person_edges` (G1) |
| `PersonTrackingCoordinator.async_add_listener` | F1 level / F4 BLE | HA coordinator update | the nine display sites (`aggregation.py`, `sensor.py`); reserved: step 8 music following; lock `record_bermuda_moves` is an allowlist row (S3) |
| `TransitionDetector.async_add_listener` | F4 BLE re-publish | HA coordinator update | root `music_following.py` (comfort), `__init__.py` Bayesian (display) |

Plus the F1 edge subscription (G1, a callback API, not a dispatcher channel; callback budget: sync, O(1), no await, no
loop over `hass.states`, no service / executor / database / recorder call, real work scheduled; it runs inside
`_feed_residency` before inference is scheduled, INV-AWAY-LATENCY). Payloads are additive-only; a key removal is a
contract change.

### 4.3 Ship 3a, phase 1: what is built (2026-11-14, `feature/layer-ship3a`, NOT deployed)

Read shapes and time types (written the same way in every plan that consumes them):

| Read | Returns | `t` |
|---|---|---|
| `get_person_edges_since(t, *, persons, kinds)` (D2) | plain tuple of `ResidencyEvent`, `edge_ts >= t`, oldest first; truncation via `person_edges_truncated_since(t)` | float epoch seconds |
| `location_moves_since(t)` | plain tuple of frozen `PersonMove(person_entity, from_room, to_room, ts, method)`, `ts >= t`, oldest first; truncation via `location_moves_truncated_since(t)` | `datetime` |
| `get_crossings_since(t, camera=None)` | plain tuple of `CrossingRecord`, `ts >= t`, oldest first; no truncation read (ring bound, RAM since creation) | `datetime` |

- **F5 ingest (G4):** `signals.dispatch_person_arriving(hass, payload)` rejects a missing / empty `source` (`ValueError`)
  and sends `payload.to_signal()`: `person_entity`, `source`; `sighting` and `zone` iff `sighting is not None`; `ts` iff
  set (plain dict literal). Each producer keeps its observation-mode suppression.
- **F4 camera ingest:** typed latch `signals.register_face_latch_callback(hass, cb) -> unsub` and
  `signals.face_latch_callbacks(hass) -> tuple` over the census face bridge's list (setup order unchanged); the key
  string lives only in `signals.py`.
- **F4 zone display write:** `ZonePresenceTracker.note_face(slug, when)` (the sighting producer's two assignments).
- **G3 sender:** `transit_validator._send_record_amended(hass, payload)` (sole sender); entries `attach_crossing_attribute`
  (owner side) and `transit_validator.amend_crossing(hass, ...)` (tracker → its G3; no tracker → the notice only).
  Forbidden keys `camera`, `direction`, `ts`, `source_ref`, `confidence` (and any non-amendable key) raise.
- **G5:** `door_entry_entities()` / `door_neighbours_for_stem(stem)`; `arrival_edges.door_entry_areas(tracker, area_of)`
  keeps its signature and reads `tracker.door_entry_entities()`; the lock still passes
  `hass.data[DOMAIN]["egress_tracker"]` (allowlist row, max 1), so the access path has no presence dependency.
- **G9:** `PersonTrackingCoordinator.set_pre_arrival_enabled(value)`; `hvac.py` calls it.
- **Layer diagnostics:** `PresenceCoordinator.get_layer_diagnostics()`, read on demand by the config-entry diagnostics
  download (`diagnostics.py`, coordinator-manager entry, key `person_awareness_layer`); counters only, never config-entry
  data / options.
- **Phase 2 (built after census-p2 merged):** G1 `residency.subscribe_person_edges` (+ presence delegate; `@callback`
  closure on `SIGNAL_RESIDENCY_EVENT`, coroutine / unknown kind rejected; crossing vision is its first subscriber),
  `get_person_edges_since` / `person_edges_truncated_since`; the class-taking census view
  (`census_view.view_for_class` is the one rule; `house_census_view(hass, view="trust", *, cls=None)`). The guard
  allowlist is final: 231 rows, `LAYER_ALLOWLIST_TOTAL` 259 (file name kept).

## 5. Gaps the layer still needs (each a small public seam; none is a new fact)

| Id | Seam | Replaces | Owner card |
|---|---|---|---|
| G1 | `subscribe_person_edges(cb, *, persons, kinds)` on presence, fed by `ResidencyTracker` (one ledger). Must deliver what today's listeners get: `persons` = residents OR every `person.*` (security watches guests too, `security.py:2235`); `kinds` include `arrival` (`-> home`), `departure` (`home ->`) and `approach` (`not_home -> named zone`, security's 30-min window, `security.py:2280-2288`); each edge carries `source_stale` and `in_boot_window`. Residency today records only resident `-> home` / `home ->` edges (`residency.py:10-11`), so G1 extends it (approach kind, all-person scope) rather than narrowing consumers. G1 never gates presence's own direct geofence trigger (INV-AWAY-LATENCY) | lock regime and perimeter `person.*` listeners + their ledgers; security geofence expected-arrival (S1) | LOCK restart plan (M8) + STALE-SOURCE-ARRIVAL-CONSUMERS-1 |
| G2 | `get_crossings_since(t, camera)` | perimeter `_note_egress_identity` 600 s cache | PERSON-AWARENESS-READ-API-1 ship 3 |
| G3 | `attach_crossing_attribute(source_ref, changes, provenance, *, camera, role, row_id=None, payload_extra={})` on the tracker: the one amend primitive (§2.3), sole sender of `SIGNAL_EGRESS_RECORD_AMENDED`; an AST guard test asserts it is the only `CrossingRecord` writer after creation | vision attribute store read sideways; private amend helpers; `SIGNAL_EGRESS_EXIT_BACKFILLED` | crossing vision Phase 2 or step 7, whichever builds first (the other extends it) |
| G4 | `dispatch_person_arriving(hass, payload)` | 3 raw dict sends | read API ship 3 |
| G5 | `EgressDirectionTracker.door_entry_entities()` / `door_neighbours_for_stem(stem)` public (entities, not areas; BUILT ship 3a D3) | `arrival_edges.door_entry_areas` and perimeter `_near_areas` reading tracker privates | read API ship 3 |
| G6 | the ONE BLE-in-room read (§2.4a): `persons_in_room(room, *, active_only)`, `persons_in_room_or_scanner_areas(room)`, `room_for_area(area_id)`, `location_moves_since(t)`, frozen `snapshot()` | room occupancy `coordinator.py:1385, 3315, 4440, 5003`; fan recheck `_l1_persons`; fan_veto / lock / perimeter / music / house_status `.data` reads; `_ble_corroboration` twins | read API ship 3 (room-occupancy filter behind §9 Q1) |
| G7 | named stream-health read for the ledger anchor: per Tier-1 input, `input_stream_view(hass, eid)` (and `entity_stream_view` for camera-derived inputs); any non-None view (HELD or RELEASED) = held; RELEASED is never "off" for the anchor; no substrate = blocked (unchanged) | `crossing_vision._held_inputs` hass.data scan (census-p2 `crossing_vision.py:1141-1145`) | census-p2 fix-up, after rebasing on batch-2 (S2 getters are not on census-p2) |
| G8 | single owner of the crossing-vision row store + `_ledger_terms` (shared seam census-p2 ↔ crossing-vision-fast-stage) | two branches extending `crossing_vision.py` with no named owner (review D12) | owner: census-p2 (`PLANNING_census_deconfliction.md`); fast-stage rebases on it after census-p2 merges, writes provisional rows only (no `apply_term`, `people_count` None on blank); merge gate test: ledger terms come from stage-B rows only, a provisional row never applies a term |
| G9 | `PersonTrackingCoordinator.set_pre_arrival_enabled(value)` | HVAC writes `pc._pre_arrival_enabled` (`hvac.py:1241`) | read API ship 3 (Tier 1, byte-identical) |

**Step 7 allowlist rows (EGRESS-DIRECTION-AWARE-IDENTITY-1, 2026-11-14; each max 1 site, owner that card):**
- Perimeter `_note_egress_identity` cache read, on the master-off path and as the master-on store-failure fallback
  only (INV-NOOP, INV-STORE-FAILURE in the plan). Retires when the master switch is removed.
- R3 producer read: `transit_validator.freshest_gps_fix` reads the `device_trackers` attribute of the `person.<slug>`
  state and each listed tracker's `source_type` / position attributes; GPS means `source_type == "gps"`, never a name
  test. Layer-internal, same class as the egress veto's `person.<slug>` read.

Contract additions A1-A13 from the step 7 plan (rev 3.1, `PLANNING_egress_direction_aware_identity.md` §14, reviewed in
`PLANREVIEW_egress_direction_aware_identity_3.md`) are applied above: A1/A1b §4.1 F1, A2 §4.1 F4, A3/A9 §2.3 + §4.1 F3,
A4 merged into G3, A5 §4.2, A6 §2.3, A7 §2.5, A8 §2.6 (reused, no new names), A10 §2.3 note, A11 §2.3 class rule,
A12/A13 the allowlist rows here.

## 6. The conformance check (run at every plan review AND the arc-map merge step)

Every plan in the arc carries a "Layer conformance" table; the reviewer re-greps it, the merge step compares plans
against it, and a plan that cannot fill a row is sent back.

1. **Facts.** Which F1-F5 (or evidence service) does it produce or consume? One row each.
2. **Ingest.** For each produced fact: the §2 ingest point it calls (function name). "New store" or "direct write"
   = fail.
3. **Read.** For each consumed fact: the §4 method or push channel, and the declared class. A raw entity, store,
   private, member public method outside §4, URA entity state, or hass.data object = fail unless the plan adds an
   allowlist row with reason, owner card, max count.
4. **Separation.** Does anything seen (F4) reach a count (F2) outside `deconflict_house`? Does anything reach access
   on F4 alone? Yes = fail.
5. **Delivery.** Does any fix change what a consumer delivers (a window, a scope, a class of person, a trigger)? Then
   it is named and goes to the operator (charter anti-drift rule 3); the planner never picks it.
6. **Guard delta.** Allowlist rows added (must be zero for a new consumer) and removed. Pinned readers
   (`PINNED_READERS`, rule R15, VISION-INTERIOR-SIGHTINGS-1): a method that may be CALLED only from named
   `(module, qualname)` pins (the F4 unnamed reads and the interior census term); a call anywhere else is a
   never-allowlistable hit. Not part of `LAYER_ALLOWLIST_TOTAL` (like `LISTED`). Pinned today: the four F4-unnamed
   reads, `interior_census_tick`, and the producer entry points `interior_tick` / `_emit_unnamed` plus
   `PersonCensus.area_evidence` (owner class only). Static limits: a bound-method alias and a display-entity state read
   are not seen.
7. **Seam check (arc map).** Does any other plan feed or read the same ingest point or add a method to the same read
   surface? Then the two plans name the shared contract and its single owner (M1-M12 style, e.g. G8), or merge.
8. **Clip path.** For vision deliverables: a frame source that can take a short clip (charter 2026-11-14).

## 7. What each remaining plan must change to conform (summary; detail in the audit §6)

- NVR witness W2-W6: W2 is the evidence service of §2.6 and must answer for every egress/perimeter camera (§2.6
  cameras outside rooms); the four comparison sites migrate to `corroborated` / `families_on_now`; W5b moves
  `_cross_validate_platforms` (F2 ingest) with a byte-identical house-count test; W5c room fusion publishes family
  agreement through a room-coordinator public getter, and fan_veto stops reading the entity state/attributes (audit
  C1). W6 seam linking is F3-internal.
- Interior vision: unnamed records via `PersonSightingProducer._emit_unnamed` (one F4 producer, not a sibling store);
  its count enters F2 only as a pulled term provider at the one call site (same shape as `census_tick`).
- Steps 7-8 (direction-aware egress, identity actions): `camera_egress` arrivals go through `dispatch_person_arriving`;
  the notify amend function moves out of the F3 producer into a notification consumer reading `get_last_crossing` +
  `min_confidence("notification")`; identity actions read `view_for_class("comfort")` (resolves to trust until rung
  3 is legal, which the plan must state) and F1 edges via G1, never raw `person.*`.
- Music repair: consumes F4-BLE through `ura_person_location_change` (D1's additive `ble_confidence` key is
  conformant); replaces `person_coord.data` reads (`music_following.py:535, 597, 656`) with G6; F5 via
  `PersonArrivingPayload` (already). Class `comfort`.
- Census-p2: G7 before merge (rebase on batch-2 first); owns G8; the term-provider pull stays the only F2 ingest for
  body terms.
- Crossing-vision fast stage: rebase on census-p2 after it merges; G8 merge gate test.

## 8. Non-goals

- No wiring of the security `context["census"]` input (audit S5; operator decision, §9 Q2).
- No change to AWAY triggers or their timing (INV-AWAY-LATENCY).
- No change to the stream-health hold caps or the release page (operator ruling; INV-MISSING-NOT-ZERO).
- No new fact, coordinator or store; every gap in §5 is a public seam over existing code.

## 9. Rulings applied, and what still needs the operator

Applied (2026-11-14, not reopened): a dead input holds up to 900 s for zone and census, then releases and pages HIGH;
the ledger anchor never uses the released view (orchestrator); AWAY stays fast and every push into house state is
named; fixes must not change what is delivered unless the operator says so (S1 keeps the 30-min approach window and
guest arrivals; S5 not wired); room occupancy is a comfort-class reader of the one BLE-in-room read.

Operator answers 2026-11-14 (verbatim: "Qs: 1 - yes. 2- unwired. But is there a trigger. 3 - keep it. S1 - confirm"):
- **Q1 (G6): YES.** Apply the phone-left-behind filter to room occupancy (`coordinator.py:3315, 4440, 5003`), after
  the §2.4a probe (zero or near-zero changed rooms = ship). A person flagged phone-left-behind no longer extends a
  room's occupancy by BLE.
- **Q2 (S5): UNWIRED.** Revival trigger (proposed 2026-11-14): two weeks of census logs with at most one false
  "unknown person" per week while no guests are present, AND the operator asks for unknown-person alerts. Detail:
  wire the security census input? It has never had a producer (`manager.py:1022-1033`), so the
  unknown-person ALERT_HIGH (fires even disarmed, `security.py:369-371`), the census-intent lock-all-doors path
  (`security.py:1104-1115`) and the persons-home SANCTIONED leg have never fired. Wiring it ACTIVATES a dormant
  lock-all-doors path fed by the census (the census that produced the phantom-GUEST class). Class `access`. This
  contract does not wire it; KEEP + DOCUMENT. If the operator wants it, it is its own Tier-3 card.
- **Q3 (D11, low): KEEP.** `BLE_TRANSITION_CONFIDENCE` = 0.75 equals the notification bar, so a BLE-only egress identity
  names the person in "X arrived" today (`>=`). Intended? The contract records it as intended unless the operator
  says otherwise.
- **S1 hold semantics: CONFIRMED.** S1 moves onto G1 with the stale-source rule applied as the lock regime applies it:
  a stale-source edge is HELD for the hold window and confirmed, not dropped, so a real arrival still opens the
  window (seconds later) and the 78-per-week iPad blips do not. Approach window (30 min) and guest arrivals unchanged.
