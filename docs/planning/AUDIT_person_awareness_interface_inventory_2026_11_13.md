# AUDIT: person-awareness interface inventory (read-only)

Date: 2026-11-13 (host `date` at start: Fri Nov 13 14:57:55 CST 2026; the host zone is CST, not CDT).
Branch read: `develop` @ 8f578a41. Read-only: no code, config or HA state changed; this file is the only write.
Author: ura-prober (Sonnet 5.5).

Question (operator): should there be one consolidated boundary-crossing + person-awareness read/feed interface, after checking reuse of existing work?

## 0. Answer first

1. **There is no single home today, and no façade exists that covers more than one fact.** Each of F1-F5 has one logical owner, but consumers reach each fact by a different route: a module helper (F1), a bare `hass.data[...]` object plus private methods (F2, F3), a bus event (F3), a dispatcher signal (F5), or a getter nobody calls (F4).
2. **The natural home for a read API is `PresenceCoordinator`, not `PersonCensus`.** It already owns the public getters for F1 (`get_residents_home*`, `presence.py:5409-5434`), F4 (`get_last_person_sighting(s)`, `:5907-5917`), F5-adjacent (`get_recent_resident_arrival`, `:5436`), and it is the one object that already holds the sighting producer, the residency tracker and the census count (`_census_count`, `:5609-5660`). `PersonCensus` is the right owner of F2 *writes* but its public surface is two methods (`register_egress_face` `camera_census.py:4137`, `evict_egress_face` `:4212`) plus `last_result` (`:1957`); everything else outside callers use is underscore-private (Section 4).
3. **Biggest finding: the consumers that most need a façade are the identity producers themselves.** `transit_validator.py`, `perimeter_alert.py`, `person_sighting.py` and `__init__.py` call about 20 distinct underscore-private census methods 40+ times (Section 4). This is the "reaches into another coordinator's private fields" pattern the operator asked about.
4. **Two of the five facts have a producer whose output is read by nothing.** F4 `get_last_person_sighting(s)` has zero production callers; `SIGNAL_PERSON_SIGHTING` has zero subscribers (Section 3.4). `camera_egress` is a named arrival source with no producer (Section 3.5). These are by-design Phase 1 states (plan §2A, D0-gated), recorded here as findings, not defects.
5. **Id-normalisation drift is real and is wider than the card lists.** Five id namespaces coexist (display name, `person.<x>` entity id, slug, Frigate first name, `.title()` display); at least 14 hand-copies of the name-to-entity rule exist outside the one helper (Section 5). The card's residual sites reach no wrong answer on this house today because the live options carry entity ids; the same read of `entry.data` would carry display names (Section 5, evidence row 1).

Docs read: `PLANNING_person_sighting_layer.md` §2A (lines 437-497) and §2B.1-2B.3a (499-606) in full; `IDENTITY_FUSION_CAMERAS_MANUAL.md` §5.3-§7 (lines 793-938) in full plus the heading outline and header (lines 1-40); `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` completely (1053 lines). I did NOT read manual §1-§4 or §5.1-§5.2 bodies or the remainder of the 3,043-line planning doc; code at the cited lines was read directly instead.

## 1. Frame (one identity model)

Plan §2A table (`PLANNING_person_sighting_layer.md:441-447`) and manual §5.5 (`IDENTITY_FUSION_CAMERAS_MANUAL.md:853-868`) are the frame:

| Fact | Single writer per the plan | Consumer classes per manual §5.5(b) |
|---|---|---|
| F1 P is home | HA `person.*` + `PersonCoordinator` | security de-escalate >= 0.9, notification naming >= 0.75, display none |
| F2 who is in the house now | `PersonCensus` union | (same classes) |
| F3 door crossing + identity attach | `EgressDirectionTracker` | (same) |
| F4 P seen at X at T | sighting producer | (same) |
| F5 P is arriving | geofence / BLE / D2 site | (same) |

Doc-vs-code correction: plan §2A and manual §5.5 name `TransitValidator._arrival_departure_notify` and `TransitValidator` as F3 owner. In code `_arrival_departure_notify` (`transit_validator.py:2603`), `_resolve_direction` (`:2096`), the bus fire (`:2191`) and the census register (`:2272`) are all inside `class EgressDirectionTracker` (starts `:1007`); `class TransitValidator` is `:282-1006`. Line numbers in plan §2A (`:2047`, `:2140`) are stale (now `:2603`, `:2191`).

## 2. F1: P is home

### 2.1 Producers / writers

| # | Site | file:line | Notes |
|---|---|---|---|
| 1 | HA `person.*` state (external) | n/a | the raw fact |
| 2 | Trust-state overlay `effective_person_state` | `person_coordinator.py:801` | differs from raw only for a BLE-overruled GPS-home person |
| 3 | Module wrapper `person_state_for_trust(hass, entity_id)` | `person_coordinator.py:144` | the trust-reader seam; fail-open to raw state |
| 4 | Residents-at-home level read `get_residents_home()` / `_count()` | `presence.py:5409` / `:5433` | residents x `person_state_for_trust` minus phone-left-behind |
| 5 | Residency edge producer `ResidencyTracker` (`_feed_residency`) | `residency.py:62`, `presence.py:5258` | raw EDGES, not level; counted rule `arrival_edges.counted_return` (`arrival_edges.py:140`, call `residency.py:134`); ledger `update_last_real` (`residency.py:153`) |
| 6 | Second ledger copy in the lock regime (same functions, own `_last_real`) | `security_lock_regime.py:1409, 1489, 1781` | delegates to the same `arrival_edges` functions (INV-RULE per doc), but is a separate store, so two ledgers of one fact |
| 7 | `memory_episodes` rows `person_arrival` / `person_departure` | `presence.py:5298` (`_persist_residency_event`) | live read 2026-11-13 21:00 UTC: 1 `person_departure` row in 14 days (started 20:54 UTC today), 0 `person_arrival` rows. Zero arrivals is expected only if step 1a landed today; the deploy time is not verified by this audit |

Multi-writer flag: levels (row 4) and edges (rows 5, 6) are deliberate concept split (doc Bug Class #63). Rows 5 and 6 are two ledgers of the same edge fact.

### 2.2 Consumers

| Consumer | file:line | Class | Route |
|---|---|---|---|
| HVAC night-trust preset hold | `hvac.py:3415-3417` | comfort-HVAC (trust) | `person_state_for_trust` per `zone.zone_persons` |
| HVAC activity-log display list | `hvac.py:3993-3995` | display | same helper, 2nd copy of the loop |
| HVAC fan vacancy hold | `hvac_fans.py:1529-1531` | comfort-HVAC (trust) | same helper |
| HVAC zone has-home-person | `hvac_zones.py:2726-2729` | comfort-HVAC | same helper (doc: no production caller) |
| Zone sleep / non-sleep fallback occupied | `aggregation.py:4759-4765`, `:4896-4901` | house-state trust | same helper, 2 loops |
| Census stale-face latch guard | `camera_census.py:5663-5679` | house-state trust | helper fetched via `_trust_reader` |
| `who()` NM text menu | `house_status.py:220-244` | display | helper + private `pc._find_person_entity` |
| Residents-home sensor / house-state attrs | `sensor.py:5801, 6131, 6140-6149` | display | `presence.get_residents_home*` accessor |
| Exterior-person severity | `perimeter_alert.py:2009, 2079` | notification severity | `presence.get_residents_home_count()` accessor |
| Lock regime (resident edge, away lock) | `security_lock_regime.py:1199, 1759, 2004, 2453, 2609, 2652, 2714` | security-access (actuation) | raw `hass.states.get(pid)`, by design (edge reader) |
| Identity vetoes: census / egress | `camera_census.py:4516, 4573`; `transit_validator.py:2012` | trust (identity gate) | raw `hass.states.get(f"person.{slug}")`, by design |
| Sighting producer `person_state_at_emit` | `person_sighting.py:625` | display / evidence | raw state |
| Perimeter | `perimeter_alert.py:5368` | security de-escalate | raw `states.get(f"person.{slug}")` |
| NM person display name | `notification_manager.py:4763-4766` | display | `friendly_name` else `.title()` |

Façade seams already present (REUSE): `person_state_for_trust` (`person_coordinator.py:144`), `get_residents_home*` (`presence.py:5409-5434`), `get_recent_resident_arrival` (`:5436`), `get_residency_snapshot` (`:5463`).

Gap: the 8 HVAC/aggregation trust readers each re-implement "any of zone persons home" (loop + helper). `get_residents_home` answers a different question (global residents, not per-zone persons) and is called by none of them.

## 3. F2: who is in the house now

### 3.1 Producers

| # | Site | file:line | Notes |
|---|---|---|---|
| 1 | Union of face ids + BLE ids + egress registrations | `camera_census.py:2527-2540` (tick), `:6440-6455` (enhanced recompute) | canonicalised via `_normalize_name_set` only when `EGRESS_IDENTITY_ENABLED`; else raw `face_ids \| ble_ids` (byte-identical kill-switch branch, comment `:2527-2535`). Two copies of the union expression (house path `:2536-2540`, enhanced path `:6447-6455`) |
| 2 | BLE person list `_get_ble_persons` | `camera_census.py:2716-2733` | returns `person_coordinator.data` KEYS (display names) with a non-away location |
| 3 | Face names `_get_face_recognized_person_names` | `camera_census.py:6305-6370` | builds its own tracked-slug list `:6311-6320`; person entity `:6370` |
| 4 | Egress registrations `register_egress_face` / `evict_egress_face` | `camera_census.py:4137`, `:4212` | the only public write API; called from `transit_validator.py:2272`, `:2276` |
| 5 | Signal payload `SIGNAL_CENSUS_UPDATED` | `camera_census.py:1869-1900` | carries counts and flags only (`interior_count`, `identified_count`, `unidentified_count`, `property_count`, `total_on_property`, `confidence`, `source_agreement`, `face_recognized_count`, `camera_input_dark`, `degraded_mode`, `peak_*`, `count_as_of`, ...). **The identified-name set is NOT on the signal.** |
| 6 | DB write `db.log_census` (every 4th cycle) | `camera_census.py:1893-1904` region; `database.py:4474-4492` | stores `identified_persons` JSON |
| 7 | Presence-side shadow copy `_census_count`, `_unidentified_count`, `_face_recognized_count` | `presence.py:5609-5660` | second store of the F2 counts, fed by the signal |
| 8 | Seed read at presence setup | `presence.py:3219-3243` | reads `hass.data[DOMAIN]["camera_integration_manager"]` which has NO writer anywhere in `custom_components` (grep: only this reader), then falls back to `sensor.universal_room_automation_identified_persons_in_house`, which does exist in the registry (verified in `.storage/core.entity_registry`). The first branch is dead; the fallback works |

### 3.2 Consumers

| Consumer | file:line | Class | Route |
|---|---|---|---|
| Presence inference (count, unidentified, face count, dark flag, confidence) | `presence.py:5609-5661` | house-state trust | dispatcher signal `SIGNAL_CENSUS_UPDATED` (counts only) |
| Census display sensors (persons, identified, unidentified, confidence, validation age) | `sensor.py:3678-4262` | display | `hass.data[DOMAIN]["census"].last_result` direct |
| Unidentified sensor, binary guest sensors, aggregation | `sensor.py:5179-5202`; `binary_sensor.py:1937-1990, 2186-2188`; `aggregation.py:6740-6778` | display / guest evidence | `census.last_result.house` direct |
| Zone/room identity | `coordinator.py:1354-1370` | display | dead branch: `getattr(census, "get_room_identified_persons", ...)`; method does not exist, falls to `person_coordinator.get_persons_in_room` (comment `:1361-1363`) |
| Identity producers reading census privates | see Section 4 | security / notification / display | `hass.data[DOMAIN]["census"]` + underscore methods |
| BLE persons for sensors | `aggregation.py:2234-2327`, `:5944-6025`, `:6670-6681`; `binary_sensor.py:1953-1994, 2065`; `sensor.py:3248-3311` | display | `person_coordinator.data` dict direct (26 + 13 + 7 `hass.data["person_coordinator"]` fetches in aggregation / sensor / binary_sensor) |
| Security entry verdict | `security.py:282-346` | security | `context["census"]` dict (`persons_home`, `unknown_present`); the producer of that context key was not traced: unknown |

### 3.3 Multi-writer / multi-normalisation flags

- The same union is computed in two places (`camera_census.py:2536-2540`, `:6447-6455`) with the same kill-switch fork.
- F2 counts live in three stores: `PersonCensus.last_result`, presence `_census_count` et al., and sensor entity state.
- `_get_ble_persons` returns display names; the union canonicalises them through `_canonical_person_slug` (first-token mapping, `camera_census.py:3915`), whereas the F1 helpers use entity ids.

## 4. Reaching into private fields: PersonCensus (and others)

Counts below are `grep -noE "census(_ref|_mgr)?\._<name>"` outside `camera_census.py`, 2026-11-13.

| Caller | Private census methods used (count) | Why it needs them |
|---|---|---|
| `transit_validator.py` | `_ble_legs_abstained_count` 5, `_egress_identity_last_attach` 4, `_consume_ble_arriving_legs` 3, `_get_tracked_person_slugs` 2, `_face_dropped_producer_down_leg_count` 2, `_egress_identity_boost_events` 2, `_egress_identity_agreement_class_last` 2, `_resolve_face_legs` 1, `_resolve_ble_legs` 1, `_note_egress_identity_outcome` 1, `_is_face_producer_live` 1, `_is_egress_identity_failsafe_strict` 1, `_is_egress_identity_enabled` 1, `_face_dropped_stale_count` 1, `_egress_identity_outcomes` 1 | F3 identity attach reads face/BLE legs and writes outcome counters on the census |
| `person_sighting.py` | `_get_tracked_person_slugs` 2, `_canonical_person_slug` 2, `_face_suppressed_now` 1 (plus public `face_person_would_be_vetoed` `:630`, and `_frigate_face_named_ring` via getattr `:710`) | F4 mapper and suppression, by design ("ONE mapper", `person_sighting.py:589-590`) |
| `perimeter_alert.py` | `_resolve_face_legs` 2, `_get_tracked_person_slugs` 1, `_get_known_face_guests` 1, `_canonical_person_slug` 1 | D10.5 known-person gate |
| `__init__.py` | `_is_egress_identity_enabled` 2, `_is_egress_identity_failsafe_strict` 1, `_get_known_face_guests` 1, `_get_face_name_aliases` 1, `_register_ble_transition_listeners` 1, `_refresh_ble_crossing_listeners` 1, `_is_cross_validation_enabled` 1, `_get_ble_cancel_enabled` 1 | setup wiring |
| `sensor.py` | `_egress_identity_outcomes` 1 | display |

Public seams on `PersonCensus` that outside code may use today: `register_egress_face`, `evict_egress_face`, `last_result`, `face_person_would_be_vetoed` (`camera_census.py:5645`), `get_transit_egress_entities` / `get_transit_interior_entities` (`:1695`, `:1702`), `get_stuck_cameras` (`:2995`), `get_pending_peak_info` (`:5922`). The tracked-slug list and canonical slug, which four consumers need, are not public.

Other cross-coordinator private reads: `house_status.py:236` (`pc._find_person_entity`), `transit_validator.py:2236-2240` area (`census_ref._egress_identity_last_attach` read to forward provenance).

## 5. Id-normalisation drift

### 5.1 The namespaces

| Namespace | Example | Where it is the native key |
|---|---|---|
| Display name | `Oji Udezue` | `PersonTrackingCoordinator.tracked_persons` (`person_coordinator.py:985`, doc: live holds display names), `person_coordinator.data` keys, `_get_ble_persons` output |
| Entity id | `person.oji_udezue` | HA, `tracked_person_entity_id` (`person_coordinator.py:130-141`), residency, lock regime, `PersonSighting.person_entity` |
| URA slug | `oji_udezue` | census union, egress `person_id`, DB `person_id` |
| Face first name | `Oji` | Frigate face library; mapped by `_canonical_person_slug` first-token rule (`camera_census.py:3915`) |
| Title-case display | `Oji Udezue` / `Ziri` | rebuilt with `.title()` (below) |

Evidence row 1 (live): in `.storage/core.config_entries` the integration entry has `data.tracked_persons = ['Ezinne','Oji Udezue','Jaya','Ziri']` and `options.tracked_persons = ['person.ezinne','person.oji_udezue','person.jaya','person.ziri']`. `person_coordinator.py:974` reads `integration_entry.data` (display names); the census readers read `{**data, **options}` (entity ids). So the same config key is read in two different namespaces by different consumers on this house. Corroborates the card text (`kanban.data.yaml:35050-35061`: `__init__.py:3145-3163` rewrites `entry.data` to display names while options keep ids).

### 5.2 Hand-copies of name -> entity id / slug

| Site | file:line | Rule | Same as helper? |
|---|---|---|---|
| THE helper `tracked_person_entity_id` | `person_coordinator.py:130-141` | keep `person.*`, else `person.` + lower + space->`_` | n/a |
| copy | `person_coordinator.py:821` | same rule | yes (card sites 807/979/1729 have moved to 821/993/1743) |
| copy | `person_coordinator.py:993` | same rule | yes |
| copy + unnormalised fallback | `person_coordinator.py:1743`, `:1747` (`person.{person_name}`) | rule, then raw name | partly |
| `arrival_edges.py:65` | `replace("person.","").lower()` (no space handling) | slug from entity id | n/a (inverse direction) |
| `arrival_edges.py:201`, `:239` | `str(name).lower().replace(" ","_")` | name -> slug | yes, inlined |
| `residency.person_slug` | `residency.py` (imported `presence.py:5419`) | entity id -> slug | inverse |
| `presence.py:5381`, `:7223` | `lower().replace(" ","_")` | name -> slug | yes, inlined |
| `_ble_corroboration.py:40` | same | yes, inlined |
| `binary_sensor.py:2125`, `sensor.py:16420`, `switch.py:6572` | same, for unique ids / entity naming | yes, inlined |
| **Residual A** `camera_census._get_tracked_person_slugs` | `camera_census.py:3900-3912` (rule at `:3909`) | `replace("person.","").strip().lower()`, **no space->`_`** | NO: `Oji Udezue` would give `oji udezue` |
| **Residual B** wifi-guest tracked list | `camera_census.py:6160-6176` (`:6171` reads `states.get(person_entity_id)` with the raw list entry) | `p.strip()`, no mapping at all, entry used as an entity id | NO: display name would give `states.get('Oji Udezue')` -> None |
| **Residual C** face-name tracked list | `camera_census.py:6311-6320` (rule `:6318`) | `p.replace("person.","").strip()`, no lower, no space map | NO |
| face entity construction | `camera_census.py:6370` (`person.{person_slug.lower()}`), `:4516`, `:4573`, `:5654` | `person.<slug>` | consistent only if slug is already `_`-form |
| **Residual D** perimeter | `perimeter_alert.py:5117-5121` (rule `:5120`) | `replace("person.","").strip().lower()`, no space map | NO |
| perimeter entity build | `perimeter_alert.py:1015`, `:5368` | `person.{slug}` | consistent only if slug is `_`-form |
| `person_sighting.py:605` | `person.{mapped}` where `mapped` must be a member of `_get_tracked_person_slugs()` (`:596`) | depends on Residual A | inherits A |
| `transit_validator.py:2012` | `person.{slug}` | same | inherits |
| Display-name reconstructions | `transit_validator.py:2622-2626` (`replace("_"," ").title()`), `notification_manager.py:4766`, `binary_sensor.py:121-122`, `__init__.py:3147-3149`, `music_following.py:53-62` (docstring names the same `.title()` rule and has its own helper) | slug -> display via `.title()` | five independent copies of the inverse rule |
| `_canonical_person_slug` | `camera_census.py:3915` | tracked-slug match, else first-token match, D-MED-2 ambiguity rule | the census-side mapper, a SECOND name->slug rule alongside the entity-id helper |

Verdict on card PERSON-ID-NORMALISE-ONE-RULE-1: the four residual sites (`camera_census.py:3900-3912`, `:6159-6176`, `:6311-6320`, `perimeter_alert.py:5117-5121`) are confirmed in the code at those lines. The card's "not reachable on this house" holds because live `options.tracked_persons` are entity ids (evidence row 1). This audit adds: Residual A feeds `person_sighting._emit` (`:596`) and `transit_validator.py:1771, 1905`, so a display-name config would zero out sightings and the egress BLE leg, not only the census.

## 4a. F3: door crossing + identity attach

### Producers

| # | Site | file:line | Notes |
|---|---|---|---|
| 1 | Direction resolver + identity join `_resolve_direction`, `_resolve_egress_face_identity_ex` | `transit_validator.py:2096`, `:1488` | one writer of (camera, direction, ts, slug, provenance, confidence) |
| 2 | Bus event `ura_person_egress_event` | `transit_validator.py:2191` | keys: `direction, egress_camera, timestamp, person_id, confidence, identity_confidence, agreement_class, identity_synthetic_corroborated, identity_provenance` |
| 3 | DB row `person_entry_exit_events` (entry/exit, not ambiguous) | `database.py:4623`, `:4637` | exit backfill UPDATE `database.py:4749` |
| 4 | Census register / evict | `transit_validator.py:2272`, `:2276` | entry registers, exit evicts |
| 5 | Notification | `transit_validator.py:2603` | threshold `ARRIVAL_NAME_CONFIDENCE_THRESHOLD = 0.75` is a class attribute (`:2601`) |
| 6 | Outcome log | `transit_validator.py:2535` (`_log_egress_outcome`) | observational |
| 7 | Legacy per-camera sighting store `_camera_sightings` (keyed by raw face/label string, not slug) | `transit_validator.py:302, 951` | a second "who was seen where" store, F4-like, different keys; superseded by F4 in the plan but still read (below) |
| 8 | Third veto copy inline in the resolver | `transit_validator.py:2012` region (face-only veto), plus `camera_census.py:4501` and `:5645` | plan §2B.1 already notes the duplicate (`:517-519`) |

Fire check (live, `person_entry_exit_events`, 2026-10-30..2026-11-13 21:00 UTC): entry 117 rows, 35 with `person_id` (30%); exit 111 rows, 54 with `person_id` (49%). Producer fires; identity attach is sparse, which caps every identity consumer (manual §5.5(c) gate).

### Consumers

| Consumer | file:line | Class | Route |
|---|---|---|---|
| Four display sensors (entered/exited today, last entry/exit) | `sensor.py:4763, 4894, 5004, 5054` listeners; DB readers `sensor.py:4742, 4876, 4948, 5097` -> `database.get_entry_exit_events_since` | display | bus event + DB |
| Perimeter D10.5 known-person gate | `perimeter_alert.py:1008` listener, `:4987` `_note_egress_identity`, `:5009-5019` `_known_identity_for` | security de-escalate; floor `max(0.9, PERIMETER_EGRESS_KNOWN_MIN_CONF)` with 0.9 inline at `:5019` (const `const.py:2663`) | bus event |
| Sighting producer (face-provenance entry/exit projection) | `person_sighting.py:449` | display/evidence | bus event |
| Census union | `transit_validator.py:2272` -> `camera_census.py:4137` | house-state trust (F2) | direct call on census |
| Arrival/departure NM | `transit_validator.py:2603` | notification (>= 0.75) | in-class call |
| Lock regime / perimeter entry areas | `security_lock_regime.py:1811`, `perimeter_alert.py:5157` | security | read `hass.data["egress_tracker"]` private attrs through `arrival_edges.door_entry_areas` (`arrival_edges.py:328`) |
| Phone-left-behind / camera sighting display | `sensor.py:3559-3561`, `binary_sensor.py:2193-2217` | display | `transit_validator.get_last_camera_sighting` (`transit_validator.py:741`) |
| `transitions.py:422` | `source_signal="transit_validator"` | display/learning | not traced further: unknown |

Threshold constants are scattered: 0.75 notification (`transit_validator.py:2601`), 0.9 security (`perimeter_alert.py:5019` inline plus `const.py:2663`), `CONFIDENCE_HIGH` 0.9 / `CONFIDENCE_MEDIUM` 0.6 / `FACE_MATCH_CORRELATED_BOOST` 0.75 (`const.py:315-316, 3364`). No object maps consumer class -> minimum confidence; each consumer applies its own number.

## 3.4 F4: P seen at X at T

### Producers

| # | Site | file:line | Notes |
|---|---|---|---|
| 1 | `PersonSightingProducer._emit` (the one emit function) | `person_sighting.py:565`; dispatch `:649`; store `:660-668` | sources: census MQTT bridge, face-name sensors on zone-camera picks, egress bus event (`:449`). Enabled by `FACE_SIGHTING_ENABLED = True` (`const.py:3378`) |
| 2 | Zone-tracker display fields `_last_face_recognized` / `_last_face_time` | written `person_sighting.py:666-667`; read `presence.py:1032-1033`, `sensor.py:6022-6024` | display only |
| 3 | Legacy `_camera_sightings` | `transit_validator.py:302, 951` | different keys, see F3 row 7 |

### Consumers

| Consumer | file:line | Route |
|---|---|---|
| `get_last_person_sighting(person_entity)` / `get_last_person_sightings()` | defined `presence.py:5907`, `:5913` | **zero production callers** (grep over `custom_components`: no call sites besides the definitions) |
| `SIGNAL_PERSON_SIGHTING` | defined `signals.py:31`, sent `person_sighting.py:649` | **zero subscribers** (grep: only the definition, the sender and a comment in `const.py:3377`) |
| D2 arrival rule `_derive_face_arrival` | `presence.py:5799` (passed as `arrival_rule` `:5791`) | in-process callback; gated off (`FACE_ARRIVAL_INTERIOR_ENABLED = False`, `const.py:3391`) |
| Sighting diagnostics | `presence.py:5917`, `sensor.py:5911` | display |
| HVAC `camera_face_arrivals_today` counter | `presence.py:5888` | display |

Fire check for F4: sightings are RAM only; I did not read the live diagnostics sensor, so the sighting count over a window is **unknown** from this audit. Doc state: D0-P3 failed, interior arrival disabled (`const.py:3391`, presence doc §1 row 84).

## 3.5 F5: P is arriving

### Producers of `SIGNAL_PERSON_ARRIVING` (`signals.py:25`)

| # | Site | file:line | `source` | Payload |
|---|---|---|---|---|
| 1 | Presence geofence edge (`home` from non-home, observation-mode gated) | `presence.py:5598` | `geofence` | `{person_entity, source}` |
| 2 | PersonCoordinator BLE pre-arrival (`_find_person_entity`) | `person_coordinator.py:1146` | `ble` | `{person_entity, source}` |
| 3 | `_derive_face_arrival` | `presence.py:5857` | `camera_face` | `{person_entity, source, sighting, zone}` |
| 4 | `camera_egress` | none | named in `CAMERA_DERIVED_ARRIVAL_SOURCES` (`const.py:3446`) and `arrival_edges.arrival_source_needs_corroboration`, but no producer (`presence.py:5805` says Phase 1 has none) | n/a |

Fire check (live, `ura_activity_log`, 14 days to 2026-11-13 21:00 UTC; this is the HVAC consumer's `pre_arrival` rows, so it counts handled signals per zone, not raw dispatches): 220 `pre_arrival` rows; `source` geofence 152, ble 68, camera_face 0. Consistent with the producer being off. `pre_arrival_standdown` 1.

### Consumers

| Consumer | file:line | Class | What it reads |
|---|---|---|---|
| HVAC pre-conditioning | `hvac.py:1511`, handler `:7222` | comfort-HVAC | `source` filter, `person_entity` -> `_person_zone_map` |
| Security expected-arrival add | `security.py:818`, handler `:2382` | security-access | `person_entity`, `source`, `sighting`; dict-or-attribute dual read; applies `arrival_source_needs_corroboration` |
| SC lock regime | `security_lock_regime.py:1247` `on_person_arriving` (fed from `security.py:2392`) | security-access (unlock) | same payload |
| Music following | `music_following.py:281`, handler `:549` | personalization | no-op (logs at DEBUG; arrival-start not implemented, `:565-571`) |

Other F5-adjacent: residency arrival rows (Section 2.1 row 7) and `get_recent_resident_arrival` (`presence.py:5436`) feed exterior ARRIVING severity (`perimeter_alert.py:2002-2041`); that is a level read, not the signal.

## 6. Existing façade-like seams (REUSE candidates)

| Seam | file:line | What it already gives | Gap |
|---|---|---|---|
| `person_state_for_trust` | `person_coordinator.py:144` | F1 trust state, fail-open | takes an entity id; callers rebuild person lists themselves |
| `tracked_person_entity_id` | `person_coordinator.py:130` | name -> entity id, one rule | 14+ inline copies, 4 residual readers |
| `PresenceCoordinator.get_residents_home*`, `get_recent_resident_arrival`, `get_residency_snapshot` | `presence.py:5409-5466` | F1 level + F5-edge accessors, sync, never raise | not used by HVAC / aggregation trust readers |
| `PresenceCoordinator.get_last_person_sighting(s)` | `presence.py:5907-5913` | F4 accessor | no callers |
| `PersonCensus.last_result` | `camera_census.py:1957` | F2 counts + `identified_persons` list | read by ~20 display sites directly; presence gets counts only via the signal |
| `PersonCensus.face_person_would_be_vetoed` | `camera_census.py:5645` | F2 veto predicate, public | used only by `person_sighting.py:630` |
| `PersonCoordinator` getters | `person_coordinator.py:1995-2335` (`get_person_location`, `get_persons_in_room`, `get_zone_occupants`, `get_tracked_person_count`) | location (BLE) accessors | ~79 `hass.data["person_coordinator"]` fetches; many read `.data` dict directly (aggregation 26, sensor 13, presence 11, binary_sensor 7) |
| `house_status.who()` | `house_status.py:189-246` | a read-only "who is home" composer with per-field `source` and age; documented "no trust decision reads this module" (`:9-10`) | display only; builds its own person list from `pc.data` keys and private `_find_person_entity` |
| `arrival_edges.py` | module | shared pure edge rules (`live_arrival_slug`, `counted_return`, `stale_source_arrival`, `door_entry_areas`, `arrival_source_needs_corroboration`) | the lock regime, residency and perimeter each keep their own ledgers |
| `canonical_camera_key` / `CameraResolver` | `camera_resolver.py:460`, `:514` | F3/F4 "which physical camera" | four independent `CameraResolver(...)` constructions: `__init__.py:638`, `transit_validator.py:242`, `binary_sensor.py:1591`, `camera_census.py:538` (the census one is cached per manager, `:451`) |
| `signals.py` | `signals.py:18-31` | `SIGNAL_CENSUS_UPDATED`, `SIGNAL_PERSON_ARRIVING`, `SIGNAL_PERSON_SIGHTING` | payload shapes are dict (F2, F5) vs frozen dataclass (F4); F5 handlers must accept both (`security.py:2395-2410`) |
| Identity constants | `const.py:3446-3459` (`CAMERA_DERIVED_ARRIVAL_SOURCES`, `IDENTITY_PROVENANCE_*`) | shared provenance vocabulary | no class -> threshold map |

## 7. Is there a natural home for a single read API?

Short answer: yes, on `PresenceCoordinator`, extended; not on `PersonCensus`; and a thin module beside it for the id rule. Verdicts per the CLAUDE.md prior-art rule:

| Piece | Verdict | Basis |
|---|---|---|
| Host object | **REUSE** `PresenceCoordinator` as the read façade host | already holds F1 accessors (`:5409-5466`), F4 store + accessor (`:5907-5917`), F2 count copies (`:5609-5661`), residency (`:5217`), and is where `SIGNAL_PERSON_ARRIVING` is produced (`:5598, :5857`). `PersonCensus` is a compute object whose outside surface is private by convention; promoting its privates would widen a Tier-3 object |
| F1 per-zone "any listed person home" | **EXTEND** `get_residents_home` family (e.g. take an optional person list) | replaces the 6 duplicate loops: `hvac.py:3415, 3993`, `hvac_fans.py:1529`, `hvac_zones.py:2726`, `aggregation.py:4759, 4896`; keeps `person_state_for_trust` as the one trust read |
| F2 identified set + counts | **EXTEND**: add accessors returning `identified_persons` set and counts from `census.last_result`, class-tagged | replaces direct `.last_result` reads at `sensor.py:3715, 5179`, `binary_sensor.py:1937, 1981, 2186`, `aggregation.py:6740, 6773`, and the dead `get_room_identified_persons` hook (`coordinator.py:1365`) |
| F2 census-private reads by producers | **NEW (small)**: public methods on `PersonCensus` for `tracked_person_slugs()`, `canonical_person_slug()`, `face_suppressed_now()`, `known_face_guests()`, `resolve_face_legs()` | replaces the ~20 private methods in Section 4; this is the only part that is a producer-side interface rather than a consumer view. No equivalent public method exists (grep `camera_census.py`) |
| F3 last crossing / identity attach | **NEW**: a public getter on `EgressDirectionTracker` (or presence) for the last crossing + attach per camera | today F3 is only a bus event, a DB table and private `_egress_identity_last_attach` on census; consumers that want "the latest crossing" must listen to the bus (perimeter keeps its own 600 s cache, `perimeter_alert.py:4998-5004`) |
| F4 last-seen | **REUSE** `get_last_person_sighting(s)` (`presence.py:5907`) | exists, uncalled |
| F5 arrival | **REUSE** `SIGNAL_PERSON_ARRIVING` + `arrival_edges`; **EXTEND** with one normalised payload type | payload is dict in 3 producers and mixed dict/attr in 3 consumers (`security.py:2395-2410`, `music_following.py:560-568`) |
| Consumer-class views (security >= 0.9, notification >= 0.75, display none) | **NEW** (one small function or table), but it replaces existing literals | thresholds today: `transit_validator.py:2601` (0.75), `perimeter_alert.py:5019` (0.9 inline), `const.py:2663`, plus the planned `EGRESS_ARRIVAL_CANDIDATE_MIN_CONFIDENCE` (plan §2B.2). No class->threshold object exists |
| Id normalisation | **REUSE** `tracked_person_entity_id` (`person_coordinator.py:130`) + **EXTEND** with `slug_of(entity_id)`, `display_of(slug)` | collapses the 14+ copies and 5 `.title()` copies of Section 5; census `_canonical_person_slug` stays as the face-name (first-token) mapper but should be a public method |

What a consumer-facing view would consolidate (ad-hoc reads replaced): the six zone person-home loops (F1), the ~20 `.last_result` / `.data` direct reads (F2), the four private-census callers (Section 4), the bus-listener-plus-private-cache pattern in perimeter (F3), the dict-or-attr payload reads (F5), and the scattered 0.75 / 0.9 literals.

What it must NOT consolidate (settled concept splits, doc Bug Class #63 and plan §2A): levels (`get_residents_home`) vs raw edges (residency, lock regime, identity vetoes read raw by design); seen (F4) vs counted (F2); sightings never feed the census and the census never reads sightings (plan §2A "The census does not read sightings"). A class-aware façade can expose each with its own method; it must not merge them into one "person is home" value.

## 8. Findings summary

| # | Finding | Evidence | Disposition candidate |
|---|---|---|---|
| 1 | F4 accessor + signal have no readers | grep, `presence.py:5907`, `signals.py:31` | by design in Phase 1; first real consumer is the façade or D2 |
| 2 | `camera_egress` arrival source has no producer | `const.py:3446`; `presence.py:5805` | by design (Phase 2); keep |
| 3 | Producers read ~20 private census methods | Section 4 | NEW public census methods (small) |
| 4 | Presence seed reads a `hass.data` key that nothing writes | `presence.py:3222`; one grep hit total | KEEP + WIRE or DELETE after confirming the sensor fallback is sufficient; the fallback works (entity exists) |
| 5 | Residual normalisation sites A-D plus 14+ inline copies | Section 5 | existing card PERSON-ID-NORMALISE-ONE-RULE-1; scope should include `.title()` copies and the `entry.data` vs `entry.options` split read |
| 6 | Union expression duplicated with a byte-identical kill-switch fork | `camera_census.py:2536-2540`, `:6447-6455` | note only |
| 7 | Three ledgers of resident edges (residency, lock regime, perimeter `_person_arrivals`) | `residency.py:153`, `security_lock_regime.py:1489`, `perimeter_alert.py:1015-1020` | doc says rules are shared via `arrival_edges`; stores are not |
| 8 | Doc names `TransitValidator` as F3 owner; code owner is `EgressDirectionTracker` | `transit_validator.py:282, 1007, 2603` | fix plan §2A and manual §5.5 in the same turn as the next doc edit |
| 9 | Identity attach on crossings is 30% (entry) / 49% (exit) over 14 days | DB read above | caps consumer value (manual §5.5(c)) |

## 9. Falsification and unknowns

- To disprove "F4 has no readers": a production call to `get_last_person_sighting` or a `async_dispatcher_connect(..., SIGNAL_PERSON_SIGHTING, ...)`. Both greps over `custom_components/universal_room_automation` returned none (tests were not searched).
- To disprove "census privates are reached by producers": the counts in Section 4 come from `grep -noE` and can be reproduced.
- Unknown: producer of `context["census"]` for `security.py:282-346`; live sighting counts (RAM only, diagnostics sensor not read); deploy time of residency (only the one `person_departure` row timestamp is verified); `transitions.py:422` consumer behavior; manual §1-§4 and the rest of the 3,043-line planning doc not read.
- Time note: live DB times above are UTC (21:00 UTC = 15:00 CST).
