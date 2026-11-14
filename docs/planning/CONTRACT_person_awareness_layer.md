# CONTRACT: the person-awareness layer (one ingest point per fact, one read surface, no leaks)

Date 2026-11-14. Author ura-planner. Status: contract for operator approval; no code changed. Companion audit:
`docs/planning/AUDIT_person_awareness_layer_leaks_2026_11_14.md` (every site, leak table, code guard).
Code base read: `develop` (v5.108.21) plus `release/batch-2` @ dbff8335 (read API ship 2, stream health S2),
`feature/census-deconfliction-p2-ledger` @ d52ea568, `feature/crossing-vision-fast-stage` @ a47e4c5b,
`feature/music-following-repair` @ 0ac39b2a (no code commits yet, worktree clean). Line numbers are batch-2 unless
marked. Charter: `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, "The operator's goals" (incl. the
2026-11-14 entries).

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
 PRODUCERS (evidence)                INGEST (one per fact)                STORE                    READ SURFACE (one)
 HA person.* / PersonCoordinator ─▶ F1  PersonTrackingCoordinator tick ─▶ .data + overrule set ─┐
                                      + ResidencyTracker.feed (edges)  ─▶ residency ledger     │
 Census face/BLE legs, egress reg ─▶ F2  PersonCensus._apply_enhanced_   ─▶ last_result (T + A) ─┤
 crossing ledger, interior vision,      house_census ─ deconflict_house                        │
 WiFi, stream-health "missing"          (term providers PULLED here)                           ├─▶ PresenceCoordinator
 Door cameras, NVR witness, vision ─▶ F3  EgressDirectionTracker.                ─▶ CrossingRecord   │   read API (§4)
                                      _resolve_direction → _record_crossing   + bus + DB        │   + view_for_class
 Census MQTT faces, zone picks,    ─▶ F4  PersonSightingProducer._emit       ─▶ sighting store  │   + push channels
 egress projection, BLE room            (camera) / PersonCoordinator tick (BLE room)            │     (§4.2)
 geofence / BLE / camera_face      ─▶ F5  dispatch_person_arriving()         ─▶ (event only)    ┘
 Stream health, NVR witness        ─▶ (evidence services, §2.6; not facts)
```

Rule of the picture: a producer never writes a store directly unless it IS that store's owner; a consumer never reads
a store, a producer internal, a raw producer entity, or a hass.data object for a person-awareness decision. It reads
§4.

## 2. Per fact: producers, the ONE ingest point, store, provenance, read surface, forbidden paths

Consumer classes (manual §5.5(b), plus the two trust classes the plans use): `security` (de-escalate / annotate
only, identity ≥ 0.9), `access` (lock / alarm actuation; reads trust, never F4 alone), `house_state` (AWAY, ARRIVING,
SLEEP, GUEST), `comfort` (HVAC, fans, music), `notification` (naming ≥ 0.75), `display` (none). `suggestion` =
`display`. Every reader declares exactly one class.

### 2.1 F1 — P is home (level) and P's home/away edges

| | |
|---|---|
| Producers allowed | HA `person.*` (external, raw); `PersonTrackingCoordinator` BLE-over-GPS overrule (`_gps_home_overruled`) |
| ONE ingest point | Level: `PersonTrackingCoordinator._async_update_data` (the only writer of `.data` and the overrule set). Edges: `ResidencyTracker.feed` called from `PresenceCoordinator._handle_geofence_change` (the only `person.*` state listener allowed to turn a raw state change into an edge record) |
| Store(s) | `PersonTrackingCoordinator.data` / `_gps_home_overruled`; the residency ledger (`residency.py`, `_last_real`, `memory_episodes` `person_arrival` / `person_departure`) |
| Provenance / confidence | level: `source` (`gps` / `ble_overrule` / `raw`), tracker sources; edge: `counted`, `source_stale`, `in_boot_window`, `resident_set_resolved` |
| Read surface | Level, trust: `get_residents_home(zone_persons=None)`, `get_residents_home_count()`, `persons_home_for_trust`, `person_state_for_trust` (`person_coordinator.py:141-188`, `presence.py:5473-5514`). Edges: `get_recent_resident_arrival`, `get_residency_snapshot` (`presence.py:5516-5543`) and NEW `subscribe_resident_edges(callback)` (§5 gap G1) |
| Deliberate separation | level (trust state) vs edge (raw state). Bug Class #63. Never merged into one value |
| Forbidden | any second `person.*` state listener that derives an arrival/departure (today: lock regime, perimeter, security SanctionChecker); any second `_last_real` ledger; reading `person.*` raw for a level decision outside `person_state_for_trust` |

Identity vetoes (census face-leg veto, egress veto, sighting `person_state_at_emit`) read raw `person.*` by design.
They are layer-internal producer reads (§2.7), allowed only inside the producer modules listed in §3 INV-LAYER-READ.

### 2.2 F2 — who is in the house now (trust view F2-T and awareness view F2-A)

| | |
|---|---|
| Producers allowed | named: face legs, BLE persons, egress registrations (F3 → F2); body terms: camera bodies, crossing ledger `guest_vis`, interior vision room counts (planned), WiFi guest phones (corroborator), stream health / NVR witness "missing" marks |
| ONE ingest point | `PersonCensus._apply_enhanced_house_census` → `census_deconflict.deconflict_house` (`camera_census.py:6665-6693` on census-p2). Named evidence enters only via the union (`_normalize_name_set`) and the egress pair `register_egress_face` / `evict_egress_face` (`camera_census.py:4381, 4456`). **Body terms are PULLED by the census from registered term providers at that one call site** (today `crossing_vision.census_tick(...)`, `camera_census.py:6644`); no provider pushes a count into the census |
| Store | `PersonCensus.last_result` (house `CensusZoneResult`: trust fields + `aware_*`) and the DB `census_snapshots` row |
| Provenance / confidence | `count_provenance` ∈ {camera, vision, agree}, `aware_agreement`, `source_agreement`, `confidence`, `as_of`, `camera_input_dark` |
| Read surface | Pull: `PresenceCoordinator.get_house_census(view)` / `census_view.house_census_view(hass, view)`, with the view chosen ONLY by `view_for_class(cls)`. Push: `SIGNAL_CENSUS_UPDATED` (F2-T counts only; the one channel the house_state class reads, INV-P2-AWAY-LATENCY) |
| Deliberate separation | F2-T vs F2-A; promotion ladder `PLANNING_census_deconfliction.md` §3.2; F4 sightings are terms, never a second union |
| Forbidden | any writer of `CensusZoneResult` count fields outside `_apply_enhanced_house_census`; a producer calling into the census to set a count; any reader of `census.last_result`, census privates, or the census entities' states for a decision; a reader passing a literal view string instead of `view_for_class(cls)` |

### 2.3 F3 — door crossing + identity attach (and F3 attributes)

| | |
|---|---|
| Producers allowed | door camera person legs (via `CameraResolver`), NVR witness corroboration (W2, planned), egress identity join (face / BLE legs from the census evidence API), crossing vision (F3 ATTRIBUTES only: `people_count`, provisional arrival record) |
| ONE ingest point | `EgressDirectionTracker._resolve_direction` → `_record_crossing(CrossingRecord)` + bus fire `ura_person_egress_event` (`transit_validator.py:2214`) + DB `person_entry_exit_events`. Attributes: NEW `EgressDirectionTracker.attach_crossing_attribute(source_ref, key, value, provenance)` (gap G3); until it exists the vision record keyed by the crossing `source_ref` in `crossing_vision` is the attribute store, read only through `get_last_arrival_record()` |
| Store | `CrossingRecord` ring (tracker), DB rows, crossing-vision rows |
| Provenance / confidence | `identity_provenance`, `identity_confidence`, `agreement_class`, `confidence`, `platforms_fired` (→ NVR families after W2) |
| Read surface | Pull: `get_last_crossing(camera)` (`presence.py:6043`), NEW `get_crossings_since(t, camera=None)` (gap G2), `get_last_arrival_record()`. Push: `ura_person_egress_event` (the declared F3 channel; listeners allowed) |
| Forbidden | a consumer keeping its own crossing cache from the bus (perimeter `_note_egress_identity`); reading `hass.data["egress_tracker"]` attributes (`_egress_entities`, `_interior_neighbours_by_group`) outside the tracker; F3 provenance stored on the census object (`set_egress_identity_last_attach`) |

The one arrival/departure notification `_arrival_departure_notify` lives inside the producer today (a consumer of
class `notification` hosted in the F3 owner). It is an allowlisted exception until D8 moves the amend function out
(§7).

### 2.4 F4 — P seen at X at T (camera sighting, BLE room, unnamed body sighting)

| | |
|---|---|
| Producers allowed | census MQTT face bridge, zone-camera face picks, egress projection (camera); Bermuda/IRK room (BLE); interior vision (unnamed body records, planned) |
| ONE ingest point | Camera / egress / interior: `PersonSightingProducer._emit` (`person_sighting.py:565`); interior vision adds `_emit_unnamed` ON THE SAME PRODUCER, not a sibling store. BLE room: `PersonTrackingCoordinator._async_update_data` (writes `location`, `previous_location`, fires `ura_person_location_change`) |
| Store | sighting store (`_last_sightings`), `PersonTrackingCoordinator.data[...]["location"]` |
| Provenance / confidence | sighting `source`, `camera`, `zone`, `census_veto`, `confidence`; BLE `method`, `confidence`, `tracking_status`, `bermuda_area` |
| Read surface | `get_last_person_sighting(s)` (`presence.py:5987-5993`); BLE: `PersonTrackingCoordinator.get_person_location`, `get_persons_in_room(active_only=...)`, `get_zone_occupants`; push: `SIGNAL_PERSON_SIGHTING`, `ura_person_location_change` |
| Deliberate separation | **seen (F4) vs counted (F2).** F4 meets F2 ONLY as a term inside `deconflict_house` (named sighting = slug term, adds nothing if the slug is in the union; unnamed body = body term keyed by physical camera). No F4 store is read by the census elsewhere, and no F4 value reaches a house_state or access decision except through F2 or an access corroboration predicate (`face_input_corroborated`) |
| Forbidden | `TransitValidator._camera_sightings` as a second named store (legacy, unidentified-only since PLB camera leg; DELETE once `transitions.py` path validation moves to F4); `person_coordinator.data` reads outside the owner and its own display entities; access acting on F4 alone |

### 2.5 F5 — P is arriving

| | |
|---|---|
| Producers allowed | geofence edge (presence), BLE pre-arrival (PersonCoordinator), the one camera site `_derive_face_arrival`, `camera_egress` (D8, planned) |
| ONE ingest point | NEW `signals.dispatch_person_arriving(hass, PersonArrivingPayload)` (gap G4). Today three raw `async_dispatcher_send(SIGNAL_PERSON_ARRIVING, dict)` sites (`presence.py:5678, 5937`, `person_coordinator.py:1172`) |
| Store | none (event); edge corroboration via residency (F1) |
| Provenance | `source` ∈ {geofence, ble, camera_face, camera_egress}; camera-derived sources need corroboration (`arrival_edges.arrival_source_needs_corroboration`) |
| Read surface | `SIGNAL_PERSON_ARRIVING` read through `PersonArrivingPayload.from_signal` (`signals.py:28-64`) |
| Forbidden | any consumer deriving its own arrival from `person.*` (security `_handle_person_state_change`, `security.py:2255`); camera-derived arrival acting alone on access |

### 2.6 Evidence services (not facts; feed facts through their ingest points)

| Service | One read | Consumers allowed | Forbidden |
|---|---|---|---|
| Camera input stream health | `camera_stream_health.input_stream_dead / camera_stream_dead / entity_stream_dead / input_stream_view / entity_stream_view / input_room_quarantined` (`:529-668`) | room fusion, zone tier, fan recheck, census (as "missing"), crossing ledger held-input check, NVR witness | scanning `hass.data[DOMAIN]` for an object with a matching attribute (census-p2 `crossing_vision._held_inputs` ~:1142); re-deriving availability |
| NVR witness (W2, planned) | `nvr_witness.family_of`, `corroborated(cam, t, window)`, `families_on_now`, `platform_for` | the 4 comparison sites (census `_cross_validate_platforms` `camera_census.py:2395`, transit `_count_platforms_fired` `transit_validator.py:2733`, perimeter `_apply_single_source_gate` `perimeter_alert.py:5038`, room fusion agreement `binary_sensor.py:1837-1868`) | entity-name suffix family tests; per-site classifiers |
| Identity evidence (census) | public `PersonCensus` methods: `resolve_face_legs`, `resolve_ble_legs`, `tracked_person_slugs`, `canonical_person_slug`, `known_face_guests`, `face_person_would_be_vetoed`, `face_suppressed_now` | layer producers only: egress tracker (F3), sighting producer (F4), perimeter D10.5 (until it reads F3/F4 instead) | any consumer outside the producer list deciding on raw legs |
| Person id rule | `person_ids.tracked_person_entity_id / slug_of / display_of / entity_key_slug` | everyone | inline `lower().replace(" ", "_")`, `.title()` inverses |

### 2.7 Layer members (who may touch stores)

Owners: `person_coordinator.py` (F1 level, F4-BLE), `residency.py` + `presence._handle_geofence_change` (F1 edges),
`camera_census.py` + `census_deconflict.py` (F2), `transit_validator.EgressDirectionTracker` (F3), `crossing_vision.py`
+ `crossing_ledger.py` (F3 attributes, F2 term provider), `person_sighting.py` (F4), `presence.py` read API block and
`_derive_face_arrival` (read surface, F5), `signals.py`, `census_view.py`, `person_ids.py`, `arrival_edges.py` (pure
rules), `camera_stream_health.py`, `nvr_witness.py` (planned). A member may read another member's PUBLIC methods; it
may read its OWN store. An owner's own display entities (census sensors in `sensor.py`, person location sensors) may
read the owner's store under a counted allowlist (owner-display exemption), never for a decision.

## 3. Layer invariants (falsifiable)

- **INV-LAYER-INGEST.** No module writes a person-awareness store (§2 "Store") except that store's owner, and no
  producer reaches a fact except through its ingest point. Falsified by: a non-owner assignment to a `CensusZoneResult`
  count field, to `PersonTrackingCoordinator.data`, to `_last_sightings`, or to a `CrossingRecord`; a
  `SIGNAL_PERSON_ARRIVING` send outside `dispatch_person_arriving`; a second `person.*` listener that produces an edge
  or arrival (today: 3, audit §2).
- **INV-LAYER-READ.** No module outside §2.7 reads, for a person-awareness decision or display: a store, a producer
  private (`_x` on a member object), a `hass.data[DOMAIN]` member object other than through §4, a raw `person.*` /
  `device_tracker.*` / Bermuda / Frigate / Protect person entity, or a URA person-awareness entity's state.
  Falsified by any such read not on the guard allowlist (§8 of the audit).
- **INV-LAYER-CLASS.** Every consumer read of F2 goes through `view_for_class(cls)` with a declared class literal from
  `CONSUMER_CLASSES`; every identity-confidence comparison reads `CONSUMER_CLASS_MIN_CONFIDENCE[cls]`. Falsified by
  `house_census_view(hass, "trust")` / `get_house_census("trust")` with a literal view (today: 8 sites, all display /
  house_state, behaviour identical while F-LEAD is off), or by an inline 0.75 / 0.9.
- **INV-DEDUP.** One body or face counted once: for any term set, adding a term whose evidence id duplicates one
  present (same canonical slug; same physical camera within the window; same crossing `source_ref`) changes neither
  F2 view. Falsified by the same face as a census leg AND a sighting term raising the count, or one body on
  family_room and master_hallway counting 2 (tests named in `PLANNING_census_deconfliction.md` §4).
- **INV-SEEN-NOT-COUNTED.** F4 reaches F2 only inside `deconflict_house`. Falsified by any F4 store or
  `SIGNAL_PERSON_SIGHTING` read inside `camera_census.py` outside the term-provider pull, or by a sighting moving a
  house_state input.
- **INV-ONE-EDGE-LEDGER.** One F1 edge ledger. Falsified today: residency `_last_real`, lock regime `_last_real`,
  perimeter `_person_arrivals` (3 ledgers; audit S2, S7).
- **INV-AWAY-LATENCY (hard, operator).** Unchanged from the census plan: no layer change delays AWAY entry or changes
  `_run_inference` call count/timing. The layer's push channel to house_state is `SIGNAL_CENSUS_UPDATED` only.
- **INV-MISSING-NOT-ZERO.** A dead/unhealthy evidence source is missing in every term and every comparison, never 0
  ("A dead camera is not a presence or absence of signal. Its faulty equipment.").

## 4. The read surface (one place, by class)

### 4.1 Pull API on `PresenceCoordinator` (reached as `coordinator_manager.coordinators["presence"]`; display entities may call the pure module functions it delegates to)

| Fact | Method | Exists |
|---|---|---|
| F1 level | `get_residents_home(zone_persons=None)`, `get_residents_home_count()` | yes |
| F1 edges | `get_recent_resident_arrival`, `get_residency_snapshot`, NEW `subscribe_resident_edges(cb)` | G1 new |
| F2 | `get_house_census(view_for_class(cls))` | yes (literal-view callers to migrate) |
| F3 | `get_last_crossing(camera)`, NEW `get_crossings_since(t, camera=None)`, `get_last_arrival_record()`, NEW `entry_areas(camera=None)` | G2, G5 new |
| F4 | `get_last_person_sighting(s)`; BLE via `get_person_location(name)`, `get_persons_in_room(room, active_only=False)` (wrapped) | wrap new (G6) |
| F5 | (push only) | |
| class | `view_for_class(cls)`, `min_confidence(cls)` (wraps `CONSUMER_CLASS_MIN_CONFIDENCE`) | `min_confidence` new |

Change to make INV-LAYER-CLASS enforceable: `house_census_view(hass, cls=...)` takes a CLASS, not a view, and calls
`view_for_class` itself (the boot-window reason display entities call the module function stays valid).

### 4.2 Push channels (the only listeners allowed)

`SIGNAL_CENSUS_UPDATED` (F2-T counts, house_state + display), `ura_person_egress_event` (F3), `SIGNAL_PERSON_SIGHTING`
and `ura_person_location_change` (F4), `SIGNAL_PERSON_ARRIVING` via `PersonArrivingPayload` (F5), resident-edge
subscription (F1, G1). Payloads are additive-only; a key removal is a contract change.

## 5. Gaps the layer still needs (each a small public seam; none is a new fact)

| Id | Seam | Replaces | Owner card |
|---|---|---|---|
| G1 | `subscribe_resident_edges(cb)` on presence, fed by `ResidencyTracker` | lock regime and perimeter `person.*` listeners + their ledgers; security geofence expected-arrival | LOCK restart plan (M8) + STALE-SOURCE-ARRIVAL-CONSUMERS-1 |
| G2 | `get_crossings_since(t, camera)` | perimeter `_note_egress_identity` 600 s cache | PERSON-AWARENESS-READ-API-1 ship 3 |
| G3 | `attach_crossing_attribute(source_ref, ...)` on the tracker | vision attribute store read sideways | crossing vision Phase 2 |
| G4 | `dispatch_person_arriving(hass, payload)` | 3 raw dict sends | read API ship 3 |
| G5 | `EgressDirectionTracker.entry_areas()` public | `arrival_edges.door_entry_areas` reading tracker privates | read API ship 3 |
| G6 | `get_persons_in_room(room, active_only)` + `location_moves_since(t)` on PersonCoordinator | fan_veto / lock / perimeter / music `.data` reads | read API ship 3 |
| G7 | named stream-health read for the ledger | `crossing_vision._held_inputs` hass.data scan | census-p2 fix-up (before merge) |

## 6. The conformance check (run at every plan review AND the arc-map merge step)

Every plan in the arc carries a "Layer conformance" table; the reviewer re-greps it, the merge step compares plans
against it, and a plan that cannot fill a row is sent back.

1. **Facts.** Which F1-F5 (or evidence service) does it produce or consume? One row each.
2. **Ingest.** For each produced fact: the §2 ingest point it calls (function name). "New store" or "direct write"
   = fail.
3. **Read.** For each consumed fact: the §4 method or push channel, and the declared class. A raw entity, store,
   private or hass.data object = fail unless the plan adds an allowlist row with reason, owner card, max count.
4. **Separation.** Does anything seen (F4) reach a count (F2) outside `deconflict_house`? Does anything reach access
   on F4 alone? Yes = fail.
5. **Guard delta.** Allowlist rows added (must be zero for a new consumer) and removed.
6. **Seam check (arc map).** Does any other plan feed or read the same ingest point or add a method to the same read
   surface? Then the two plans name the shared contract and its single owner (M1-M12 style), or merge.
7. **Clip path.** For vision deliverables: a frame source that can take a short clip (charter 2026-11-14).

## 7. What each remaining plan must change to conform (summary; detail in the audit §9)

- NVR witness W2-W6: W2 is the F3 evidence service of §2.6; the four comparison sites migrate to `corroborated` /
  `families_on_now`; W5b census reads `families_live` as a missing mark through `deconflict_house` only; W5c room
  fusion publishes family agreement through a room-coordinator public getter, and fan_veto stops reading the entity
  state/attributes (audit C1). W6 seam linking is F3-internal.
- Interior vision: unnamed records via `PersonSightingProducer._emit_unnamed` (one F4 producer, not a sibling
  store); its count enters F2 only as a pulled term provider at the one call site (same shape as `census_tick`).
- Steps 7-8 (direction-aware egress, identity actions): `camera_egress` arrivals go through `dispatch_person_arriving`;
  the notify amend function moves out of the F3 producer into a notification consumer reading `get_last_crossing` +
  `min_confidence("notification")`; identity actions read `view_for_class("comfort")` (resolves to trust until rung
  3 is legal, which the plan must state) and F1 edges via G1, never raw `person.*`.
- Music repair: consumes F4-BLE through `ura_person_location_change` (declared channel; D1's additive
  `ble_confidence` key is conformant); replaces `person_coord.data` reads (`music_following.py:535, 597, 656`) with
  G6; F5 via `PersonArrivingPayload` (already). Class `comfort`.
- Census-p2: G7 before merge; the term-provider pull stays the only F2 ingest for body terms.
