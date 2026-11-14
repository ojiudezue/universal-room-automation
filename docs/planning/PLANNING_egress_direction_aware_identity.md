# PLANNING: direction-aware egress identity (arc step 7), rev 3

Card: EGRESS-DIRECTION-AWARE-IDENTITY-1 (thread identity, batch person-sightings, parent FACE-ARRIVAL-REBUILD-1;
FACE-EGRESS-ARRIVAL-1 folded). Arc: identity / vision / census, step 7 of `ARC_identity_vision_census_map.md` §4.
Tier 3. Status: rev 3, awaiting the orchestrator's contract amendment (§14), the operator answers (§13) and a
re-check of plan review 2's findings before build dispatch. Author ura-planner, 2026-11-14, develop @ 9148b4f6.
Rev 2 is archived verbatim at `docs/planning/archive/PLANNING_egress_direction_aware_identity_rev2.md` (rev 1 at
`..._rev1.md`); nothing below layers on either. Disposition of every plan review 2 finding: §17.

Inputs: plan review 2 (`docs/reviews/plan-review/PLANREVIEW_egress_direction_aware_identity_2.md`, FIX-PLAN), the
orchestrator's rulings on it (H1-H4, G-M1, G-M2, L7; recorded in §0), the layer contract
`CONTRACT_person_awareness_layer.md` rev 2, the charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`.

This file is the ONE build spec for Phase 2 of the person-sighting plan (§2B, D8b). Where
`PLANNING_person_sighting_layer.md` §2B / D8b differ, this file wins; the sighting plan gets a pointer in D6.

Read first, completely, for this revision (stated per CLAUDE.md and the planner brief):
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger), `SENSOR_FLEET_CLASSES.md`,
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger; D5 touches `pre_arrival_sources`), the contract, the
charter, `AUDIT_egress_history_labels_2026_11_13.md`. `IDENTITY_FUSION_CAMERAS_MANUAL.md` was read for rev 2 and
not re-read. No corrections-ledger claim is re-asserted. Code-vs-doc contradictions found (code wins; fixed by D6
or listed for the orchestrator in §15): manual §4.3 names `TransitValidator` as the egress owner, the class is
`EgressDirectionTracker` (`transit_validator.py:963`); the contract cites `PersonArrivingPayload` at
`signals.py:28-64` as existing, it does not exist (`domain_coordinators/signals.py:25-39` are string constants);
the contract's raw F5 send lines (`presence.py:5678, 5937`, `person_coordinator.py:1172`) are stale, they are
`presence.py:5622`, `:5881`, `person_coordinator.py:1141`; the contract lists `PersonCensus.tracked_person_slugs`
as a public method, only the private `_get_tracked_person_slugs` exists (`camera_census.py:3901`); rev 2 cited
`register_egress_face` / `evict_egress_face` at `camera_census.py:4381, 4456`, they are at `:4147`, `:4222`.

## 0. Decisions recorded

**Operator, 2026-11-14 ("Agreed").** Allow naming for arrivals in pairs instead of abstaining whenever anyone else
crosses before confirmation; add a minimum-yield gate. Attached constraints: each named person needs their own
evidence at ≥ the notification bar; conflicted pairs stay unnamed; the 0.9 security bar is unchanged.

**Operator, 2026-11-12.** "the name is withheld from every consumer until the after-the-fact corroboration" (the
basis for candidates being anonymous, §6.3).

**Orchestrator rulings on plan review 2 (2026-11-14), carried into the body, not decided here:**
- H1: the crossing ring gets count and age retention on the knob ladder, per-camera keying, replace by
  `source_ref` without overwriting a newer crossing (§6.4), with the 11-03 22:37/22:38 pair as a worked case.
- H2: the pair conflict must reach perimeter before it can stand down, or perimeter must not use a pair-member
  attach until the pair window closes; INV-SECURITY-BAR must hold with a 0.9 attach (§6.6).
- H3: rev 3 must NOT reduce what is named today. The perimeter below-floor face + own non-face path (operator
  2026-11-08) and the synthetic-0.9 path stay on door cameras, routed through the one naming path, behind the
  master switch so the no-op path is byte-identical. Fewer named arrivals at doors is not an allowed trade (§6.7).
- H4: contract names and shapes exactly; anything the contract lacks is listed as a contract addition (§14), no
  private seams.
- G-M1: attached-pair deferral is beyond what the operator agreed; measured and put as a question (§13 QA). Plan
  default: NO deferral of an already-attached name (today's behaviour); a conflict is surfaced as a follow-up.
- G-M2: D0 counts arrivals where the phone reads a named non-home zone while the person is home, and the plan states
  the wrong-AWAY cost (§5.4, §13 QB).

## 1. Charter, goal served, drift check

Goals served, verbatim from the charter: "assist arrivals accuracy and personalization"; "egress only names people
who are already home... Who made this rule? ... It should do both"; "make it faster and faster until it can
eventually be used in security applications too". Hard constraint: "I need away to be fast acting."

What this delivers: arrivals the face-only veto erases today get a name minutes later, once the person's OWN phone
confirms them, including two people arriving together. Upper bound on the labelled fixture (§5.1): 4 of the 10 true
arrivals newly named (3 → 7 of 10). Departures get a label. AWAY latency is not touched. Nothing named today at a
door stops being named: attached names keep their t_E + 45 s timing, and perimeter keeps every evidence path it has.

Drift check (ura-arc rule 3). Rev 2 drifted twice and rev 3 removes both: (1) its perimeter reroute would have
stopped naming door arrivals the operator asked to be named on 2026-11-08 (review G-H1); rev 3 keeps those paths;
(2) its attached-pair deferral delayed today's named Jaya / Ezinne arrivals by 75 s without the operator's say
(review G-M1); rev 3 does not defer and asks (§13 QA). Changes to WHAT is delivered that remain, each named and
each the operator's to confirm: entry with the phone in a named zone becomes a candidate instead of a named attach
(§6.1, QB; basis: operator 2026-11-12 quote above); untracked faces stop registering (Q7); a pair-member attach
reaches security consumers up to 75 s later (§6.6, folded into QA). What stays anonymous, named so it is not silent:
two faces on ONE crossing, same-slug double claims, pair conflicts on candidates, crossings the egress detector
never logged (2 of 10, §5.1), arrivals whose phone confirms after 900 s.

## 2. Institutional context verified

Greps run 2026-11-14 on develop @ 9148b4f6 (each verdict re-checked; rev 2 verdicts not inherited):
`def _arrival_departure_notify|_resolve_egress_face_identity_ex|_last_crossing|def get_last_crossing|def _record_crossing|class CrossingRecord|def door_camera_stems|def _log_egress_outcome|async_fire\(|log_entry_exit_event|_person_raw == "not_home"|def egress_identity_tier_labelled|_is_egress_identity_enabled`
in `transit_validator.py`;
`def location_moves_since|def subscribe_person_edges|def get_crossings_since|def dispatch_person_arriving|class PersonArrivingPayload|def min_confidence|def display_of|def tracked_person_entity_id|def recent_arrival|def on_event|def stale_source_arrival|def bermuda_arrival_into|def nonface_arrival_source|def score_path`
repo-wide (seams: 0 hits); `SIGNAL_PERSON_ARRIVING` in `presence.py`, `person_coordinator.py`, `signals.py`;
`_known_identity_for\(|def _followup_check|def _async_send_identity_followup|_note_egress_identity\(|that was` in
`perimeter_alert.py`; `_egress_identity_outcomes|"attached"` in `sensor.py` / `camera_census.py`;
`IDENTITY_PROVENANCE_VALUES` (defined `const.py:3499`, 0 readers); `camera_face|pre_arrival_sources` in `hvac.py`.

| Piece | Verdict | Where |
|---|---|---|
| Face-only veto to replace | REUSED site | `transit_validator.py:2036-2050` (`_person_raw == "not_home"`, outcome `vetoed`) |
| Tier helper | REUSED | `egress_identity_tier_labelled` `:127-161` (one leg `CONFIDENCE_MEDIUM` 0.6; ≥ 2 legs one camera `FACE_MATCH_CORRELATED_BOOST` 0.75 `const.py:3404`; two cameras `CONFIDENCE_HIGH` 0.9). Its `synthetic` flag is set only on the HIGH branch (`:152-158`) |
| Resolver + caller | REUSED, extend | `_resolve_egress_face_identity_ex` `:1497`, caller `:2192` |
| Outcome log (D8a, live) | REUSED, new outcome labels | `_log_egress_outcome` `:2576`; `EGRESS_OUTCOME_EPISODE_TYPE` `const.py:3516` |
| Census outcome deque | REUSED, unchanged labels for exits | `_note_egress_identity_outcome` `camera_census.py:3617-3631`; reader `sensor.py:3973-4003` |
| Crossing store | REUSED, EXTENDED to a ring (H1) | `CrossingRecord` frozen dataclass `:943-960`; `_record_crossing` `:1039-1042` (today: last overall + last per camera only, `:1036-1037`); `get_last_crossing` `:1044-1053` |
| Door-camera roster | REUSED + NEW sibling | `door_camera_stems()` `:1294`; NEW `door_camera_device_ids()` (contract addition A9) |
| Arrival/departure notify | REUSED, MOVED (contract §7, audit N1) | `_arrival_departure_notify` `:2647-2709`, call `:2278`; NM read `:2679` |
| Census register / evict | REUSED, unchanged calls | `transit_validator.py:2305-2332`; `register_egress_face` / `evict_egress_face` `camera_census.py:4147`, `:4222` |
| DB INSERT | REUSED, return row id | `log_entry_exit_event` `database.py:4600-4652` (returns None today; `self._db()` write path) |
| Row-id backfill | REUSED | `backfill_entry_exit_person_id` `database.py:4723-4769` (idempotent `AND person_id IS NULL`) |
| Exit-backfill display pattern | REUSED | `SIGNAL_EGRESS_EXIT_BACKFILLED` `signals.py:39`; readers `sensor.py:4960`, `:5114` |
| F1 edges (push) | REUSED contract seam G1 | `subscribe_person_edges(cb, *, persons, kinds)` (contract §5 G1); 0 hits in code; fed by `ResidencyTracker` (`residency.py:62`, `on_event` `:109-161`, `recent` deque `:89`) |
| F1 edges (pull, per person) | NEW contract addition A1 | the only pull today is `get_recent_resident_arrival` (`presence.py:5462-5478`), newest of ANY resident, not per person |
| F5 dispatch | REUSED contract seam G4 + NEW type A7 | `dispatch_person_arriving(hass, PersonArrivingPayload)`; payload type does not exist (dict keys today `presence.py:5622-5626`, `:5881-5890`, `person_coordinator.py:1141-1145`) |
| F4-BLE moves | REUSED contract seam G6 (pull) | `location_moves_since(t)` (contract §4.1, §5 G6); shape undefined (A2) |
| F3 history | REUSED contract seam G2 + A3 | `get_crossings_since(t, camera=None)`; NEW `get_crossing(source_ref)` |
| Census view by class | REUSED | `PresenceCoordinator.view_for_class` `presence.py:5984` |
| Class thresholds | REUSED | `CONSUMER_CLASS_MIN_CONFIDENCE` `const.py:6512`; classes `:6495-6496` |
| Stale-source rule | REUSED | `arrival_edges.stale_source_arrival` `:72` |
| Bermuda into entry area | REUSED pure rule | `arrival_edges.bermuda_arrival_into` `:191`, `nonface_arrival_source` `:269` |
| Camera-derived set | REUSED | `CAMERA_DERIVED_ARRIVAL_SOURCES` `const.py:3486` |
| D2 arrival site | REUSED, egress branch | `PresenceCoordinator._derive_face_arrival` `presence.py:5825` |
| Quiet follow-up send | REUSED | `NotificationManager.async_notify(..., quiet=)` (`notification_manager.py:1544`; quiet rows pre-acked `:1889`) |
| Digest carries LOW | REUSED | `get_pending_digest` `database.py:4910`, LOW/MEDIUM filter `:4925-4928` |
| Perimeter D10.5 identity | REUSED site, master-gated READ SOURCE change (H2) and SEND routing (H3) | `_note_egress_identity` `perimeter_alert.py:5156-5176`; `_known_identity_for` `:5178-5262` (egress-event branch `:5213-5236`, face legs `:5237-5261`); `_apply_egress_identity_gate` `:5348-5432`; `_followup_check` `:5519-5542`; `_async_send_identity_followup` `:5565-5589`; `PERIMETER_EGRESS_IDENTITY_MATCH_S` 15, `_WAIT_S` 0, `PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S` 90, `_POLL_S` 5 (`const.py:2692-2733`) |
| Name switch fresh read | REUSED via NEW public wrapper A8 | `PersonCensus._is_egress_identity_enabled` `camera_census.py:4127` |
| Tracked roster | REUSED via NEW public wrapper A8 | `PersonCensus._get_tracked_person_slugs` `camera_census.py:3901` |
| Path scorer | REUSED | `interior_paths.score_path` `:200`; loader `async_setup_path_map` `transit_validator.py:2363` |
| Sighting producer | REUSED, changed (rev 1 M6) | `person_sighting.py:449-495` (role literal `"attached"` at `:491`; source (c) gates on FACE / BLE_FACE at `:458-461`) |
| HVAC source filter | REUSED, conditional (D5) | literal `hvac.py:881`; CM read `:1436-1440`; filter `_handle_person_arriving` `:7222`, `:7231`; `DEFAULT_PRE_ARRIVAL_SOURCES` `hvac_const.py:350`; selector `config_flow.py:8192`; migration precedent `_migrate_hvac_zone_entry_dwell_to_zero` `__init__.py:749` |
| `freshest_gps_fix` | NEW producer-internal helper in `transit_validator.py` (B-L2) | grep `gps_fix` 0 hits outside plans |
| `SIGNAL_EGRESS_ENTRY_CONFIRMED` | NEW (contract addition A5) | grep 0 hits |
| `CONF_EGRESS_CONFUSABLE_PAIRS` | NEW | grep `confusable` 0 hits in code; sighting plan §2B.3 parked trigger fired |
| `ArrivalNotifier` | NEW module, moved logic (A10) | contract §7 "a notification consumer"; egress tracker created at `__init__.py:3473` |

Prior plans read: `PLANNING_person_sighting_layer.md` §0A, §2A, §2B, D8; `PLANNING_crossing_vision.md` §1-§8;
`PLANNING_identity_actions_v6.md`; `PLANNING_census_deconfliction.md` §3.2; `PLANNING_person_awareness_read_api.md`;
`PLANNING_perimeter_egress_mute_scoped.md` §3-§4 (re-read this rev: qualifying crossing = entry/exit, tracked
resident, conf ≥ `EGRESS_MUTE_MIN_IDENTITY_CONF`, not synthetic; mutes LATER edges); the contract and its review.
Analysis: `AUDIT_egress_history_labels_2026_11_13.md` (whole), live D8a log and `person_entry_exit_events`
(§5, re-queried 2026-11-14). Memory: `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`,
`feedback_alert_latency_over_precision`, `feedback_registry_not_name_guessing`,
`reference_egress_face_coverage_7pct_not_a_ceiling`. Config-first: no knob makes the veto direction-aware;
`switch.ura_name_people_at_doors` only turns naming off.

## 3. Facts, consumer classes, layer conformance (contract §6)

Produces F3 (identity role on a crossing; confirmed name later; pair state) and F5 `camera_egress` (only if D5
survives its fire check). Consumes F1 edges, F1 raw level at resolution (the veto, layer-internal producer read,
contract §2.1), F4-BLE, F3. Never writes F2 for a candidate.

| # | Check | This plan |
|---|---|---|
| 1 Facts | produce | F3 identity role, confirmed name, `pair_state`; F5 `camera_egress` (conditional, D5) |
| | consume | F1 edges (confirmation leg a; K5 partner edges), F1 raw level at resolution, F4-BLE (confirmation leg b; K5 partner moves), F3 (notifier, perimeter, sightings, displays) |
| 2 Ingest | F3 | `EgressDirectionTracker._resolve_direction` → `_record_crossing` + bus + DB (the one F3 ingest). Confirmation and pair resolution amend the ring record inside the owner (`_amend_crossing`, §6.4); nothing else writes it |
| | F5 | `signals.dispatch_person_arriving` (G4, payload A7). No raw `async_dispatcher_send(SIGNAL_PERSON_ARRIVING, ...)` |
| | F2 | none new. Register/evict stay the existing egress pair; a candidate never registers |
| | F4 | `PersonSightingProducer._emit` source (c') — the one F4 ingest |
| 3 Read | F1 edges | push `subscribe_person_edges(cb, persons=<tracked roster entity ids>, kinds={"arrival"})` (G1); pull `get_person_edges_since(t, persons=, kinds=)` (A1). The tracker adds NO `person.*` state listener |
| | F4-BLE | `location_moves_since(t)` (G6, pull, polled on the 5 s sweep) |
| | F3 | `get_last_crossing`, `get_crossings_since` (G2), `get_crossing(source_ref)` (A3), bus `ura_person_egress_event` |
| | F2 | none |
| | thresholds | `CONSUMER_CLASS_MIN_CONFIDENCE["notification"]` / `["security"]` by name (`min_confidence(cls)` once it exists). No inline 0.75 / 0.9 |
| | classes | `ArrivalNotifier` = notification; four entry/exit sensors and the attach counter = display; perimeter D10.5 demote, perimeter identity follow-up, scoped egress mute = security; HVAC pre-arrival and music following (via F4/F5, unchanged) = comfort; locks, alarm, security expected-arrival add (`security.py:2424-2429`) = access (never on `camera_egress` alone); house_state = no input change |
| 4 Separation | | No F4 reaches F2 here. Nothing reaches access on F4 or on `camera_egress` alone |
| 5 Delivery | | Named in §1 and put to the operator in §13 (QA, QB, Q7). The planner picks none of them |
| 6 Guard delta | | Removes N1 (notify hosted in the F3 owner) and P2 for the attach record. Adds R3: `transit_validator.freshest_gps_fix` reads GPS `device_tracker.*` (producer-internal, max 1). Adds one allowlist row while the master exists: perimeter keeps its bus cache on the master-off path (§6.6), owner card this one |
| 7 Seams | | G1, G2, G4, G6 are owned by PERSON-AWARENESS-READ-API-1 ship 3 (G1 shared with the LOCK restart plan and STALE-SOURCE-ARRIVAL-CONSUMERS-1, arc merge M13). If ship 3 has not merged when this build dispatches, D0b builds exactly those seams plus the §14 additions the orchestrator accepts, in their owner modules, to the contract signatures; ship 3 drops them. `ArrivalNotifier` is the single send site for arrival naming on door cameras for this card, crossing vision P2-D9, step 8 and perimeter D10.5 follow-ups on door cameras (§6.7). Scoped egress mute: §6.10 |
| 8 Clip path | | no vision frame source touched |

## 4. Falsifiable invariants (reviewer D breaks these, pre-existing code included)

Terms: "egress-derived identity" = `person_id` on the bus, on a `CrossingRecord`, on the DB row, or on
`SIGNAL_EGRESS_ENTRY_CONFIRMED`. "Master" = `EGRESS_IDENTITY_DIRECTION_AWARE`.

- **INV-PROVISIONAL (arrivals, master on).** Before the slug's own confirming edge, no egress-derived channel carries
  a candidate's slug: bus `person_id` and any bus key, DB `person_id`, `CrossingRecord.person_id` / `nameable`, the
  arrival notification and every follow-up sent for that crossing, the four displays, the census union,
  `SIGNAL_PERSON_SIGHTING`, `SIGNAL_PERSON_ARRIVING`. Break it with any of those carrying the slug with no edge of
  that slug's own devices timestamped after the crossing. Scope note (H3): perimeter may name the same person from
  its OWN unchanged evidence (a face leg ≥ the security bar, a below-floor face plus that person's own non-face
  arrival edge, a synthetic 0.9 plus a non-face edge); that is today's behaviour, not an egress-derived channel.
- **INV-OWN-EVIDENCE.** An arrival follow-up renders a name only from that slug's entry in the crossing's `nameable`
  map at ≥ `CONSUMER_CLASS_MIN_CONFIDENCE["notification"]`. Break it with a name rendered from a partner's edge, a
  crossing-vision face entity, or a candidate whose pair conflicts.
- **INV-ONE-NAMING-PATH (master on).** Every door-camera naming message after the original arrival notification
  (arrival follow-ups from this card, crossing vision, step 8; perimeter identity follow-ups on door cameras) is
  sent from `arrival_notify.py`; arrival follow-ups are capped at `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` per crossing.
  Break it with another `async_notify` that names a person for a door crossing or door-camera alert, or a third
  arrival amend.
- **INV-NO-NAME-LOSS (H3).** For any input, the set of (person, door crossing or door-camera alert) pairs named today
  (master off) is a subset of those named with the master on, except the declared deltas: entry with the phone in a
  named zone (QB), untracked faces (Q7). Timing for an attached arrival name is unchanged (t_E + 45 s). A perimeter
  identity follow-up for a pair member may land up to `EGRESS_PAIR_GUARD_WINDOW_S` − 45 s later (§6.6), never lost.
  Break it with a golden-replay input where master-on drops a name master-off sends, outside those deltas.
- **INV-CANDIDATE.** A candidate exists only if the slug is tracked, K1 passes, K2 does not fail, K3 does not fail,
  K4 returned one slug, and K5 does not fire.
- **INV-SECURITY-BAR (master on).** (a) No egress-confirmed identity carries confidence ≥
  `CONSUMER_CLASS_MIN_CONFIDENCE["security"]`. (b) An egress-derived identity whose record `pair_state` is `pending`
  or `conflict` never qualifies for a security-class decision: perimeter D10.5 demote, perimeter identity
  follow-up, scoped egress mute. Break (b) with: pair `jaya|ezinne`, Jaya attached at 0.9 (two cameras) at t_E,
  Ezinne's edge at t_E + 80 s, and any perimeter follow-up, demote or mute decision on that door, at any time
  after t_E + 45 s, that treats Jaya as known from the egress record. Master off: today's behaviour (no pair concept), INV-NOOP.
- **INV-ACCESS (unchanged, re-proven).** No `camera_egress` arrival alone releases a lock, unlocks, adds an expected
  arrival or disarms (GPS-only confirmation included).
- **INV-NO-AWAY-DELAY.** With the master on, no reachable path delays AWAY entry relative to master off: every
  census delta either removes a registration or keeps an evict; no inference input (`infer()` / `_run_inference`,
  residency producer, census trust view, presence's own geofence trigger `presence.py:9888, 9892`) changes. Break it
  with a slug held in the union longer than master off would hold it.
- **INV-RING.** A ring amend never changes any field of a record other than the one whose `source_ref` it names,
  and `get_last_crossing(camera)` after an amend returns the newest crossing on that camera. Break it with the
  §6.4 worked case returning Oji's record as Jaya's camera's last crossing, or any field of R2 changing when R1 is
  confirmed.
- **INV-NOOP.** Master off: outcome labels, deque labels, DB row, notification text / severity / recipients,
  census calls, bus dict, perimeter cache, perimeter decisions and perimeter send call byte-identical to develop;
  golden replay over entry x {home, not_home, zone, unknown, untracked} and exit x {home, not_home, zone}, plus a
  perimeter replay over {face_leg ≥ 0.9, face 0.6 + own edge, synthetic 0.9 + edge, bus 0.9} on a door camera.
- **INV-PAIR (candidates).** With `jaya|ezinne` configured: a candidate slug whose partner made a non-face arrival
  edge in [t_E − `EGRESS_PAIR_GUARD_WINDOW_S`, confirming edge] is never named for that crossing. (Attached pair
  members: §6.6; their names are not withheld by default, QA.)

## 5. Measurements (H1 yield; G-M1; G-M2)

### 5.1 Fixture replay: the 10 TRUE arrivals (`AUDIT_egress_history_labels_2026_11_13.md` :51-71)

Rule applied: rev 3 (§6), confirm window 900 s, pair `jaya|ezinne`. Field provenance (B-M10), per case in the JSON
fixture: crossing time + camera + face name + score = Frigate event (`sub_label`, audit :21); URA row offsets and
`person_id` = `person_entry_exit_events`; own home edge = recorder (exact) or 15-min snapshot (upper bound, marked
`assumed_edge_upper_bound`); raw person state at resolution = recorder or snapshot (marked `assumed_state`);
**URA resolver legs at resolution = ASSUMED** one in-window leg of the Frigate-named slug (`assumed_legs`), because
these rows predate D8a. The fixture is therefore a RULE-REGRESSION fixture, not a yield proof; the yield proof is
gate (b) on the D8a log (§5.5).

| Crossing | Face / URA row | Own home edge | Today | Rev 3 | Reason |
|---|---|---|---|---|---|
| 10-30 19:45 Jaya front | entry/null@+5; exit/jaya@+49 | ≤ +266 (snap) | anon | anon | an attached crossing claims `jaya` inside (crossing, edge]: conflict (i) |
| 10-31 13:34 Ezinne front | no URA row | ≤ +496 | none | none | detector logged no crossing (out of scope) |
| 10-31 21:31 Ezinne front | entry/ezinne@+46 | ≤ +286 | named | named | attached (name timing unchanged at t_E + 45 s; QA) |
| 11-02 08:50 Oji front | entry/oji_udezue@+46 | ≤ +387 | named | named | attached |
| 11-03 08:36 Ezinne front | entry/ezinne@+62 | ≤ +791 | named | named | attached (timing unchanged; QA) |
| 11-03 22:37 Oji front | entry/null@+46 | ≤ +810 | anon | **NAMED** | pair arrival with Jaya; own edge; not a confusable pair (worked case §6.4) |
| 11-03 22:38 Jaya front | entry/null@+16 | ≤ +781 | anon | **NAMED** | pair arrival with Oji; own edge; Ezinne home already (no partner edge) |
| 11-04 22:53 Jaya garage | no URA row | ≤ +641 | none | none | detector logged no crossing |
| 11-07 10:35 Oji garage | entry/null@+47 | +412 (recorder) | anon | **NAMED** | own edge |
| 11-08 17:34 Jaya front | entry/null@+46; exit/null@+96 | +356 (recorder) | anon | **NAMED** | the intervening crossing is anonymous, not a claim |

Upper bound: 4 newly named (7 of 10 named, vs 3 today). At a 600 s window the 11-03 pair drops (snapshot bounds),
giving 2. The 11-03 rows are TWO URA entry crossings ~40 s apart on the front door (Oji cluster +46 / +86 s, Jaya
cluster +16 / +56 s: the same two rows seen from both Frigate clusters); the projection assumes each row's in-window
legs held one name. If either row held both faces, K4 abstains that row and it stays "1 more" (named residual).

Misrecognition replay on the other 31 clusters: 0 projected wrong names (19 Jaya phone-away clusters, 9 Oji group
C and the 11-12 07:23 false Oji have no own home edge within 900 s; 11-11 08:25 stays anonymous twice over: Jaya's
own edge is 16:29 and K5 fires on Ezinne's edge; 10 Ojini events are untracked; 2 Ziri have no edge).

### 5.2 Live D8a outcome log (re-queried 2026-11-14 ~09:45 CST, `ssh ha sqlite3 -readonly`)

85 rows (79 on 11-13, 6 on 11-14). Rows with a slug: `attached` entry jaya 0.6 ×1 and 0.9 ×1 (19:39, 19:41),
`attached` exit jaya 0.6 ×4, `attached_ble` entry ezinne 0.72 ×2 and jaya 0.72 ×2, `vetoed` jaya ×4 (entry 14:11,
14:32; exit 14:11, 14:36; tier 0.6, `person.jaya` not_home). Every `person_state` read is `home`, `not_home` or
null: no named-zone resolution in the window. Rev 3 projection: 2 entry candidates (14:11, 14:32), 0 confirmed (Jaya's
own phone first reads home at 18:13), 0 named.

### 5.3 G-M1: what an attached-pair deferral would cost (measured, for §13 QA)

Today the arrival notification names an attached person iff identity confidence ≥ 0.75
(`transit_validator.py:2666-2672`), i.e. BOOST (0.75) or HIGH (0.9) attaches; a single 0.6 leg and BLE 0.72 are
anonymous already. A deferral would make those named Jaya / Ezinne arrivals anonymous at t_E + 45 s and name them at
t_E + 120 s (75 s later), and permanently anonymous when Ezinne's / Jaya's edge lands in the window.
- Fixture (10 TRUE): 2 of the 3 arrivals named today are Ezinne (10-31 21:31, 11-03 08:36); their tier is not
  recorded (pre-D8a), so 0 to 2 would be delayed.
- D8a window (26 h): 1 named pair-member entry (Jaya 0.9, 11-13 19:41); it would have been delayed 75 s.
- `person_entry_exit_events`, 14 days to 11-14: 26 entry rows named `jaya` (14) or `ezinne` (12) of 35 resident
  named entries; the row carries no identity confidence, so 26 (~13 / week) is the upper bound on delayed names.
- D0 (c) adds the conflict rate: attached pair-member entries with the partner's edge in ±120 s.

### 5.4 G-M2: entry with the phone in a named zone (for §13 QB)

Today such an entry attaches, registers in the census union for `EGRESS_FACE_UNION_TTL_S` (300 s, `const.py:3388`)
and names at ≥ 0.75. Rev 3 makes it a candidate (anonymous, no register) until the person's own edge. Cost model:
(1) names: each such crossing named today is named later or not at all; (2) wrong AWAY: the only AWAY-relevant
effect is the 300 s union membership removed; it can produce a wrong AWAY only when that registration was the sole
evidence keeping the house out of AWAY while the person was physically home. The D8a window shows 0 named-zone
resolutions (§5.2). D0 (i) measures it over the full window (§9 D0).

### 5.5 Ship gates (both must pass; measured in D0, re-run before the operator checkpoint)

1. **Misrecognition gate.** Replay wrong-person names on the 41-cluster fixture and on every outcome-log candidate
   = 0, and the resolver-level upper Wilson bound on tracked residents ≤ 0.30 (today 3/30 [0.6, 16.7] to 3/30 with
   flips [3.5, 25.6], audit :222-223). A non-zero replay count blocks the confirmation leg that produced it.
2. **Minimum-yield gate (operator 2026-11-14).** (a) Rule regression: the fixture replay names ≥
   `EGRESS_ARRIVAL_YIELD_FLOOR_FIXTURE` = 4 of 10 under its stated assumptions (a design change that drops it fails
   and goes back to the operator). (b) Yield proof: over ≥ 7 days of D8a log (which records the legs), projected
   confirmed names ≥ `EGRESS_ARRIVAL_YIELD_FLOOR_PER_WEEK` = 1 per week. Below (b): the operator decides; the plan
   does not ship by default. Both rung 1. After ship a zero-fire trip-wire replaces the calendar (D2).

## 6. Design

Labels: guards are K1-K5 (this plan); G1, G2, G4, G6 are contract seams only (B-M1).

### 6.1 The rule (face-only single-slug path; BLE branches unchanged; master on)

| Direction | Slug status | Raw `person.<slug>` at resolution | D8a outcome | Deque label | Bus / DB `person_id` | Census call | Arrival notify |
|---|---|---|---|---|---|---|---|
| entry | tracked | `home` | `attached` | `attached` | slug | register | as today (named iff ≥ 0.75) |
| entry | tracked | `not_home` or a named zone | `arrival_candidate` if K1-K5 allow, else `vetoed_arrival_unverified` (failed guard recorded) | `arrival_candidate` / `vetoed` | None | none (today: zone registers) | "Someone arrived" |
| entry / exit | tracked | missing / unknown / unavailable | `attached` (fail-open, as today) | `attached` | slug | as today | as today |
| entry / exit | untracked | n/a | `vetoed_untracked` | `vetoed` | None | none (today: registers) | "Someone ..." |
| exit | tracked | `home` | `departure_attached` | `attached` (unchanged, so the attach-rate sensor `sensor.py:3993` is unchanged) | slug | evict | as today |
| exit | tracked | named zone | `vetoed`, evict kept | `vetoed` | None | evict (as today) | as today |
| exit | tracked | `not_home` | `vetoed` (as today) | `vetoed` | None | none | as today |
| ambiguous | any | any | unchanged | unchanged | None | none | none |

Tracked roster: `PersonCensus.tracked_person_slugs()` (public wrapper of `camera_census.py:3901`, A8), the same
membership the sighting producer applies. Census deltas, both lowering the union only: entry + zone no longer
registers; untracked faces no longer register.

### 6.2 Guards (evaluated at resolution, `t_E + EGRESS_ENTRY_WINDOW_SECONDS` = 45 s; timing unchanged)

- **K1 face leg.** Tier label from `egress_identity_tier_labelled(legs_only)` ≥ `EGRESS_ARRIVAL_CANDIDATE_MIN_TIER`
  (= `CONFIDENCE_MEDIUM`, one leg) AND NOT `all(getattr(leg, "synthetic", False) for leg in legs_only)` (B-M2: the
  helper returns `synthetic` False for a lone synthetic leg, `:159-161`, so the predicate is computed here). Fail →
  `vetoed_arrival_unverified` reason `k1`.
- **K2 path.** `score_path(...)` < `EGRESS_ARRIVAL_PATH_MIN` (2) on a mapped door = FAIL. No map, or knob 0 =
  skipped (pass).
- **K3 implied speed.** `transit_validator.freshest_gps_fix(hass, person_entity)` (registry-resolved trackers of
  that person, `source_type == "gps"`, newest `last_updated`): distance to `zone.home` minus accuracy and radius,
  over fix age floored at `EGRESS_ARRIVAL_GPS_MIN_AGE_S` (60); FAIL above `EGRESS_ARRIVAL_MAX_SPEED_KMH` (150); no
  fix or older than `EGRESS_ARRIVAL_GPS_MAX_AGE_S` (86400) = skipped. The fix read here is kept on the waiter as
  `prior_fix` (leg c, §6.3).
- **K4 single name.** Existing abstain / disagree rules returned one slug (unchanged).
- **K5 confusable pair (candidates only).** If the slug has a partner in `CONF_EGRESS_CONFUSABLE_PAIRS` and the
  partner has a non-face arrival edge in [t_E − `EGRESS_PAIR_GUARD_WINDOW_S`, resolution]: `vetoed_pair_confusable`.
  Partner edges: F1 via `get_person_edges_since(t_E − 120, persons={partner}, kinds={"arrival"})` (A1) filtered
  `counted` and not `source_stale`; F4-BLE via `location_moves_since(t_E − 120)` (G6) filtered by
  `bermuda_arrival_into` over the door's entry areas. Empty pairs = inert.

### 6.3 Candidate, waiter, own-evidence confirmation

At the crossing a candidate is anonymous everywhere (original "Someone arrived", bus `person_id` None, no bus
candidate key, no register, no sighting). The slug lives only in the waiter.

**Waiter start (B-M6).** The waiter is registered SYNCHRONOUSLY in `_resolve_direction` right after `_record_crossing`
and before the DB INSERT `await` (today `:2348`); `_resolve_direction` has no await between the resolver call
(`:2192`) and the INSERT, so no F1 callback can run in between. The F1 edge subscription is ONE tracker-wide
`subscribe_person_edges(self._on_person_edge, persons=<tracked roster entity ids via
person_ids.tracked_person_entity_id>, kinds={"arrival"})` made at `async_init` and unsubscribed at teardown (it
exists before any crossing, so no edge is lost). An edge between t_E and resolution means the raw person read
`home` at resolution, i.e. `attached`, not a candidate. Bermuda moves are PULLED with `location_moves_since(crossing_ts)`
on each sweep, so moves before the first sweep are caught. The waiter's `row_id` is filled when the INSERT returns.
`log_entry_exit_event` returns the row id (`cursor.lastrowid`) and None on error / no DB: the waiter still runs,
and on confirmation the backfill is skipped and counted `arrival_confirm_no_row` (record, signal, follow-up still
proceed).

**Waiter set.** `_arrival_waiters` keyed by slug, one per slug: a newer candidate for the same slug supersedes the
older (older terminal `arrival_superseded`, its row stays NULL). Cap `EGRESS_ARRIVAL_MAX_PENDING` (8): a new
candidate beyond the cap evicts the OLDEST waiter (`arrival_dropped_cap`). Sweep every `EGRESS_ARRIVAL_CONFIRM_POLL_S`
(5 s) until `crossing_ts + EGRESS_ARRIVAL_CONFIRM_WINDOW_S` (900 s) → `arrival_unconfirmed`. Not persisted: a
restart ends every waiter `arrival_dropped_teardown`.

**Own confirming edge** = the first edge of the SLUG'S OWN devices strictly after `crossing_ts`:
(a) G1 edge for `person.<slug>` `-> home`, `counted`, not `source_stale`, not `in_boot_window`;
(b) a `location_moves_since` move of that person into a URA room with `ts > crossing_ts` (slug mapped through
`person_ids.tracked_person_entity_id`);
(c) GPS (B-M7): `prior_fix` (captured at resolution by K3) is younger than
`EGRESS_ARRIVAL_CONFIRM_GPS_PRIOR_MAX_AGE_S` (1800) and farther than `EGRESS_ARRIVAL_CONFIRM_GPS_KM` (0.5) from home,
AND a current fix from `freshest_gps_fix` with `last_updated > crossing_ts` is inside the home zone. Both come from
HA state; no recorder read. Leg (c) is dropped from the build if D0 (b) shows it never leads (knob 0 = off).

**Pair rule (operator 2026-11-14).** Another person's crossing in (`crossing_ts`, edge] does NOT abstain. The
candidate abstains (`arrival_confirm_ambiguous`, reason recorded) only when:
(i) an ATTACHED (`attached` / `departure_attached`) crossing in (`crossing_ts`, edge] carries the same slug (a later
CANDIDATE for the same slug is handled by supersede above, never by (i); B-M5);
(ii) K5 at confirmation: the partner's non-face edge in [t_E − 120 s, edge];
(iii) the edge is stale-source: not a confirmation, keep waiting.
A partner's edge never confirms the slug.

**Confirmed confidence.** `EGRESS_ARRIVAL_CONFIRMED_CONFIDENCE` = 0.75 regardless of face tier (one face leg + one
independent own-device edge; same evidence class as perimeter's below-floor face + own non-face signal,
`perimeter_alert.py:5256-5261`). It equals the notification bar and is below the security bar.

**On confirmation**, one tracked task in `_confirm_tasks`, first reading `PersonCensus.egress_naming_enabled()`
(public wrapper of `_is_egress_identity_enabled`, A8; B-L3; off → `arrival_confirm_disabled_skip`, write nothing):
(1) `backfill_entry_exit_person_id(row_id, slug, 0.75)`, retried each sweep until the window ends if it returns
False; (2) `_amend_crossing(source_ref, identity_role="arrival_confirmed", person_id=slug,
provenance=<A6 constant for the leg>, identity_confidence=0.75, nameable={slug: 0.75})` (§6.4); (3) fire
`SIGNAL_EGRESS_ENTRY_CONFIRMED` {person_id, egress_camera, source_ref, crossing_ts, confirmed_at,
identity_confidence, identity_provenance, confirmed_by, confirm_lag_s} (A5); (4)
`ArrivalNotifier.notify_arrival_followup(source_ref, kind="name", names=(slug,), requester="egress")`; (5) write one
`egress_identity_confirmation` episode row (§6.8); (6) never a census register.

### 6.4 The crossing ring (H1)

Store: `_crossing_ring: dict[str, deque[CrossingRecord]]` keyed by `record.camera` (the egress entity id, the same
key `_last_crossing_by_camera` uses, `:1036`). Retention, both rung 1, applied on every append and on every read:
- count `EGRESS_CROSSING_RING_PER_CAMERA` = 32 per key (measured peak on any one egress entity: 9 crossings in a
  30-min window, D8a 11-13/14, so 32 is ~3.5x);
- age `EGRESS_CROSSING_RING_MAX_AGE_S` = 1800 ≥ confirm window 900 + pair window 120 + longest follow-up caller
  delay (crossing-vision count follow-up and step 8, each must state theirs ≤ 600 s; checked by a test that asserts
  the knob ≥ the sum). Older records are dropped.
`_record_crossing` keeps its two existing assignments (`:1041-1042`) unchanged and also appends to the ring.

`_amend_crossing(source_ref, **changes) -> bool` (owner-private; the only ring writer besides append):
1. find the record with that `source_ref` in `_crossing_ring[camera]` (the caller passes the camera it stored with the
   waiter or pair timer; the camera is never parsed out of the string; match is exact `source_ref` equality inside
   that deque); not found → False, counted `crossing_record_aged_out`;
2. replace it IN PLACE at the same index with `dataclasses.replace(record, **changes)`;
3. if `_last_crossing_by_camera.get(camera)` has the same `source_ref`, assign the replacement there; same for
   `_last_crossing`; otherwise leave both untouched.

`get_crossings_since(t, camera=None)` returns ring records with `ts ≥ t`, oldest first; `get_crossing(source_ref)`
(A3) returns one or None. `ArrivalNotifier.notify_arrival_followup` on an aged-out record returns False, counted
`followup_record_aged_out`.

**Worked case, 11-03 front door** (two entry crossings, R1 ~22:37:46 Oji candidate, R2 ~22:38:26 Jaya candidate, both
on the doorbell entity). After R2: ring `[R1, R2]`, `_last_crossing_by_camera[doorbell] = R2`. Oji's own edge
(≤ 22:51, snapshot bound +810 s from 22:37) confirms first: R1 is replaced at index 0; the last-by-camera holds
R2's `source_ref`, so it is not touched (INV-RING: `get_last_crossing(doorbell)` still returns Jaya's crossing).
Jaya's edge confirms R2: replaced at index 1; R2 is the newest, so last-by-camera and `_last_crossing` get the
replacement. Neither amend reads or writes the other record. Test `::test_ring_amend_does_not_clobber_newer`.

`CrossingRecord` gains additive defaulted fields: `identity_role: str | None`, `nameable: Mapping[str, float]`
(frozen mapping, default empty), `pair_state: str | None` (None | `pending` | `clear` | `conflict`; §6.6),
`pair_partner: str | None`, `identity_synthetic_corroborated: bool` (the bus field, so perimeter can read it from the
record, §6.6). Written at resolution and by `_amend_crossing` only.

### 6.5 The `nameable` map

At resolution: `{slug: identity_confidence}` for an `attached` slug whose confidence ≥ the notification bar
(exactly today's naming rule); empty otherwise. At confirmation: §6.3. A candidate's slug is never in it before its
own edge. A pair `conflict` on an attached record (§6.6) does NOT remove the entry by default (QA); it only blocks
security consumers.

### 6.6 Pair members, the bus timing and security consumers (H2)

The bus fires once at t_E + 45 s (`:2215`). A pair conflict can be known only at t_E + `EGRESS_PAIR_GUARD_WINDOW_S`.
Rev 3 takes the second branch of the orchestrator's H2 ruling: **with the master on, perimeter does not use a
pair-member attach until the owner has closed the pair window.**

Owner side. For an `attached` entry whose slug has a configured partner, the record is written with
`pair_state="pending"`; if the partner's edge (K5 sources) already lies in [t_E − 120, resolution] it is written
`conflict` at once. A per-record timer at t_E + `EGRESS_PAIR_GUARD_WINDOW_S` (tracked; cancelled at teardown) runs
the K5 check over the whole window and amends `pair_state` to `clear` or `conflict` (+ `pair_partner`). A slug with
no partner gets `pair_state=None`. Master off: never set.

Perimeter side (master on). Perimeter stops reading its own bus cache for identity and reads F3 through G2 (the
contract's stated purpose of G2, §5): in `_known_identity_for`, the egress-event branch (`:5213-5236`) iterates
`get_crossings_since(edge − PERIMETER_EGRESS_IDENTITY_MATCH_S − EGRESS_ENTRY_WINDOW_SECONDS)` filtered by
`self._egress_key(record.camera) == cam_key` (the existing key function, `:5145-5154`), `person_id` set,
`identity_confidence` set, and `abs(edge − record.ts) ≤ match_s` (today's tests, same order), and additionally
skips a record whose `pair_state` is `pending` or `conflict`; `identity_synthetic_corroborated` comes from the
record. The face-leg branch (`:5237-5261`) is unchanged. `_note_egress_identity` keeps writing its cache (master off
reads it; master on ignores it), so the master-off path is byte-identical. In `_followup_check`, when no identity is
known and the window has elapsed, the follow-up is NOT expired while a matching record has `pair_state="pending"`;
it re-polls until that record leaves `pending` (bounded by the record's t_E + 120 s + one poll), then decides as
today. So a pair member's perimeter follow-up lands at most 75 s later than today, never lost (INV-NO-NAME-LOSS).

Timing note (code-verified): at default knobs the bus-based DEMOTE branch is unreachable today, because the decision
runs at the edge (`PERIMETER_EGRESS_IDENTITY_WAIT_S` 0, settle ≤ 20 s) while a crossing record exists only from
t_E + 45 s and must lie within 15 s of the edge. The reachable security use of an egress attach is the identity
FOLLOW-UP (90 s window, 5 s poll) and the scoped mute. Both honour `pair_state` with the master on. Review 2's
repro (perimeter edge at t_E + 90 s) does not match at 15 s; the falsifier in INV-SECURITY-BAR (b) is the
follow-up and mute variant, which is reachable today.

On conflict, the arrival side: `ArrivalNotifier.notify_arrival_followup(source_ref, kind="pair_conflict",
names=(slug,), partner=<partner>)` sends one quiet LOW line, e.g. "Jaya Udezue arrived may have been Ezinne
Udezue (faces often confused)" with display names from `person_ids.display_of`; it counts against the per-crossing
cap. The original name is not retracted from the DB, census or bus (today's behaviour; QA asks whether to withhold).

### 6.7 One naming path (H3)

`domain_coordinators/arrival_notify.py`, class `ArrivalNotifier` (class `notification`). Created in `__init__.py`
next to the egress tracker (`:3473`) and stored at `hass.data[DOMAIN]["arrival_notifier"]`; callers read it the way
the tracker reads NM today (`:2679`), None-safe (B-L5): if None, the tracker calls the module function
`arrival_notify.notify_arrival(hass, record)` for the original (same text), and follow-ups return False counted
`followup_no_notifier`.

- `notify_arrival(record)`: the moved `_arrival_departure_notify` body; text, title, severity and `coordinator_id`
  byte-identical for the master-off path; names render through `person_ids.display_of(slug)` (`person_ids.py:56-63`,
  the same `.replace("_", " ").title()` transform as `:2672`).
- `notify_arrival_followup(source_ref, *, kind, names=(), guests=0, partner=None, requester) -> bool`: the only place
  an arrival message is amended. Reads the record with `get_crossing(source_ref)`. `kind="name"` keeps a name only if
  `record.nameable[slug] ≥ CONSUMER_CLASS_MIN_CONFIDENCE["notification"]` (others dropped, `followup_name_refused`);
  no surviving name → False. `kind="count"` sends surviving names plus "N not recognised". `kind="pair_conflict"`
  §6.6. All: severity LOW, `quiet=True`, `egress_naming_enabled()` read fresh, at most
  `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` (2) per `source_ref` in a RAM ledger (TTL = ring age).
- `send_perimeter_identity(*, entity_id, message, severity, hazard_type, location) -> None`: the perimeter door-camera
  "that was X" send. Byte-identical NM call to `perimeter_alert.py:5576-5584` (same title
  `FOLLOWUP_TITLE`, message, severity, `hazard_type`, `location`, `quiet=True`, `coordinator_id="perimeter_alert"`).
  It does NOT validate against `nameable` and does not count against the arrival cap: perimeter's evidence rules are
  its own and unchanged (H3). Its only effect is that the send lives in the one module.

Perimeter routing (master on only). In `_async_send_identity_followup`, when the alerting entity is on a door
camera, the NM call is replaced by `notifier.send_perimeter_identity(...)`. Door camera test (Registry rule, B-L6):
the entity id comes from `state["entity_id"]` (the alert's sensor, `:5571`); its registry `device_id` is compared
with `EgressDirectionTracker.door_camera_device_ids()` (A9: the registry `device_id` of each egress entity). Never by
stem or name. Master off, notifier None, or not a door camera → today's direct send.

What perimeter still names on door cameras with the master on (unchanged): a face leg ≥ the security bar; a
below-floor face + that person's own non-face arrival edge (operator 2026-11-08); a synthetic 0.9 + a non-face edge
(v5.108.1 B-M1); an egress record ≥ 0.9 that is not pair-pending / conflict. Callers of
`notify_arrival_followup`: this card (§6.3, §6.6), crossing vision P2-D9 (count), step 8 (count).

### 6.8 Outcome accounting (B-M9)

- One D8a `egress_identity_outcome` row per crossing at resolution (unchanged count), with the new labels in §6.1.
- One deque entry per crossing at resolution (unchanged count); labels in §6.1; the attach-rate sensor logic is
  unchanged.
- Each waiter's terminal state writes ONE row of a NEW episode type `egress_identity_confirmation`
  (`EGRESS_CONFIRMATION_EPISODE_TYPE`, `node_id` = the crossing `source_ref`, so it joins the outcome row): outcome ∈
  {`arrival_confirmed`, `arrival_unconfirmed`, `arrival_confirm_ambiguous`, `arrival_superseded`,
  `arrival_dropped_cap`, `arrival_dropped_teardown`, `arrival_confirm_disabled_skip`}, plus slug, leg, lag, row id
  backfilled yes/no. Through the existing memory-episode writer (batched queue, not a per-row write path). A
  teardown terminal is written only if the DB is still open (same latch as `_outcome_log_tasks`, `:1012-1013`).
- The attach sensor gains a display attribute `egress_identity_confirmed_24h` from a tracker counter.
- Gate (b) and the trip-wire count candidates from outcome rows and confirmations from confirmation rows; nothing
  counts a crossing twice.

### 6.9 Departures, sighting producer, D2 egress branch

- `departure_attached`: labelled D8a row + sighting + the existing "X left" + evict. No `SIGNAL_PERSON_DEPARTING`.
- Sighting producer: NEW source (c') subscribed in `person_sighting.py` to `SIGNAL_EGRESS_ENTRY_CONFIRMED`,
  unsubscribed on teardown; emits through `_emit` with `identity_role="arrival_confirmed"` (the role becomes a
  parameter instead of the literal at `:491`), provenance = the A6 constant (source (c)'s FACE / BLE_FACE gate at
  `:458-461` is not on this path), `ts = crossing_ts`, additive `confirmed_at`. The 60 s `(slug, camera)` debounce
  applies.
- D2 egress branch: for an `egress_entry` sighting with `identity_role == "arrival_confirmed"` and
  `FACE_ARRIVAL_EGRESS_ENABLED`, `_derive_face_arrival` dispatches `dispatch_person_arriving(hass,
  PersonArrivingPayload(person_entity=..., source="camera_egress", sighting=..., zone=..., ts=crossing_ts))`; skips
  raw `home` and `arrival_already_dispatched`. Built only if D5 survives its fire check.

### 6.10 HVAC (D5, conditional) and seams other plans must hear

D5: the dispatch fires only for a GPS-led confirmation whose raw `person.*` is still not `home` at confirm time. D0 (g)
counts it. 0 over the window → D5 parked with revival trigger "D0 (g) > 0 per week" (Q5); otherwise D5 adds
`camera_egress` to `DEFAULT_PRE_ARRIVAL_SOURCES` (`hvac_const.py:350`) and the literal at `hvac.py:881`, the selector
(label "Camera at a door (confirmed arrival)", `config_flow.py:8192`), and a one-shot options migration modelled on
`_migrate_hvac_zone_entry_dwell_to_zero` (`__init__.py:749`) that appends when the stored list holds `camera_face`,
sentinel `pre_arrival_sources_camera_egress_migration_done`, with a stated check that the write does not reload the
CM (`OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7553`). HVAC logic unchanged (`_handle_person_arriving`
`hvac.py:7222-7231` filter only).

Seams:
- Scoped egress mute (`PLANNING_perimeter_egress_mute_scoped.md` §3): its "qualifying crossing" must also require
  `pair_state ∉ {pending, conflict}` (read from the record via G2, as perimeter does above). Step 7 does not cut
  resident walk-out alerts there (exit + home was already attached; candidates stay anonymous at t_E + 45 s).
- EXTERIOR-GUEST-EGRESS-1 not triggered (yield 4 of 10, not near zero).
- Detector misses (2 of 10 TRUE had no URA row): egress-detection residual; orchestrator cards it.
- Protect face names have no HA path; not consumed (Q6).

## 7. Producer and consumer checks

| Value | Producer (arithmetic, health) | Consumers (class, file:line) |
|---|---|---|
| face tier | `egress_identity_tier_labelled` `:127`; live 11-13/14: face attaches 0.6 except one 0.9 (§5.2); healthy | K1 (gate); bus `identity_confidence`; ring record; perimeter follow-up (security, ≥ 0.9) |
| own confirming edge | G1 residency edges (`counted`, stale, boot flags; `residency.py:109-161`), G6 moves, GPS fixes (Jaya has no GPS tracker, audit :124) | waiter only |
| confirmed name | §6.3; fire check: 4 per 14 days on the fixture (upper bound), 0 in the 26 h live window (§5.2) | DB backfill; ring record; `SIGNAL_EGRESS_ENTRY_CONFIRMED` → Entered Today / Last Person Entry (display, `sensor.py:4960`, `:5114` pattern), sighting (c') (F4), `ArrivalNotifier` (notification), D2 (F5, conditional) |
| `pair_state` | §6.6 (owner timer at t_E + 120 s) | perimeter `_known_identity_for` + `_followup_check` (security, master on), scoped mute (security, its card), `ArrivalNotifier` pair-conflict line (notification) |
| `nameable` | §6.5 | `ArrivalNotifier.notify_arrival_followup` only |
| D8a / confirmation rows | §6.8 | attach sensor (display), D0, trip-wire, gate (b) |

Forward trace: a confirmed name reaches notification (follow-up), display (entry sensors), F4 (sighting), F5
(conditional), and step 8 through those channels. Nothing reaches access or house_state.

## 8. Emission and decision sites (a hypothesis; reviewers re-grep)

Veto `transit_validator.py:2036-2050`; every `_ret` in `_resolve_egress_face_identity_ex` (`:1497-2103`); bus fire
`:2215`; `_record_crossing` `:1039-1042` + ring append + `_amend_crossing`; `get_last_crossing` `:1044`; notify call
`:2278` (moved); census `:2305-2332`; waiter registration (new, before `:2348`); INSERT `:2348`; teardown (waiters,
`_confirm_tasks`, pair timers, G1 unsubscribe); deque `camera_census.py:3617-3631` and its reader `sensor.py:3973-4003`;
four `_handle_egress_event` readers (`sensor.py:4828`, `:4973`, `:5059`, `:5172`); `person_sighting.py:449-495`;
`presence.py:5825` (D2) and the three raw F5 sends (`presence.py:5622`, `:5881`, `person_coordinator.py:1141`,
migrated by G4); perimeter `:5156-5176`, `:5178-5262`, `:5348-5432`, `:5519-5542`, `:5565-5589`; crossing-vision
P2-D9 caller and step 8 callers (seam); `hvac_const.py:350`, `hvac.py:881`, `config_flow.py:8192`, `__init__.py`
migration (D5 only); `__init__.py:3473` (notifier creation).

## 9. Deliverables (one branch, in order, Tier 3)

**D0 probe (read-only, `ssh ha "python3 -"`).** Committed to §5 before build: (a) would-be candidates per week by
guard verdict; (b) confirm lag by leg on true cases (sizes the window; decides leg c); (c) pair matrix: named face on
a not-home slug, and attached pair-member entries, with the partner's non-face edge within ±120 s; (d) wrong-person
confirmations per leg on replay; (e) K3 fix-age buckets on true arrivals; (f) yield under the full rev 3 rule,
regenerating §5.1 from the log; (g) D5 fire check: GPS-led confirmations with raw `person.*` not `home` at confirm;
(h) D8a still writing; **(i) G-M2:** entry crossings whose D8a `person_state` is a named zone, per week; of those,
how many were named today (≥ 0.75); how many were truly home (own home edge ≤ 900 s, or a Bermuda in-house room fix);
and of the truly-home ones, how many have a `house_state_log` AWAY entry within `EGRESS_FACE_UNION_TTL_S` (300 s)
after the crossing (wrong-AWAY exposure upper bound); **(j) G-M1:** pair-member entries attached ≥ 0.75 per week
(the names a deferral would delay 75 s), and how many of those had a partner edge in ±120 s (would become
anonymous).
- **Verify:** §5.5 gates from (d) and (f); (g) decides D5; (i), (j) answer QB, QA with numbers.
- **Discriminates:** a rule that abstains on any crossing shows 11-08 17:34 removed by "other crossing"; the correct
  rule names it.
- **Test:** none. **Live:** none.

**D0b seams (only those ship 3 has not merged, plus the §14 additions the orchestrator accepts).** G1
`subscribe_person_edges`, A1 `get_person_edges_since`, G2 `get_crossings_since` + A3 `get_crossing`, G4
`dispatch_person_arriving` + A7 `PersonArrivingPayload` (migrate the three raw sends), G6 `location_moves_since`
(A2 shape), A8 census wrappers, A9 `door_camera_device_ids()`.
- **Verify:** the three raw `SIGNAL_PERSON_ARRIVING` sends are gone; payload dicts equal before and after; presence's
  own `_run_inference("geofence_leave")` trigger is not routed through G1.
- **Test:** `test_layer_seams.py::test_dispatch_person_arriving_payload_equal`,
  `::test_person_edges_callback_counted_flags`, `::test_person_edges_since_per_person`,
  `::test_geofence_leave_trigger_unchanged`, `::test_door_camera_device_ids_registry_only` (an entity whose name
  matches a door stem but whose device differs is excluded), `::test_tracked_person_slugs_public_matches_private`.
- **Live:** L-0 geofence arrivals still reach HVAC (a `pre_arrival` row on the next arrival).

**D1 rule, guards, roster, ring, record fields, outcome labels.**
- **Verify:** entry, one 0.6 leg, `not_home`, no map, no GPS → `arrival_candidate`, bus `person_id` None, no
  candidate key, "Someone arrived", not in the union (today: `vetoed`). Same with Ezinne's edge at −9 s and pair
  `jaya|ezinne` → `vetoed_pair_confusable` (without K5: candidate). Lone synthetic leg → `k1`. Fix 3 h old at
  9,000 km → `k3`. Path 0 on a mapped door → `k2`. `ojini` face → `vetoed_untracked`, no register (today: attached
  + register). Exit + zone → `vetoed` AND evict. Exit + home → D8a `departure_attached`, deque `attached`, evict.
  Ring worked case §6.4.
- **Test:** `test_egress_direction_aware.py` (the D8b list kept by name) plus
  `::test_k1_single_medium_leg_forms_candidate`, `::test_k1_lone_synthetic_leg_vetoed`,
  `::test_k2_skipped_passes`, `::test_k5_partner_arrival_vetoes_candidate`, `::test_k5_empty_pairs_inert`,
  `::test_untracked_face_vetoed_no_register`, `::test_exit_zone_vetoed_still_evicts`, `::test_no_candidate_key_on_bus`,
  `::test_ring_amend_does_not_clobber_newer`, `::test_ring_retention_count_and_age`,
  `::test_ring_age_covers_confirm_pair_followup`, `::test_deque_labels_unchanged_for_exits`,
  `::test_noop_golden_replay` (INV-NOOP matrix incl. untracked and the perimeter replay).
- **Live:** L-a the first `arrival_candidate` row shows a NULL DB row and an anonymous notification row.

**D2 waiter, own-evidence confirmation, pair rule, signal, displays, confirmation rows, trip-wire.**
- **Verify:** own G1 edge at +4 min names the row, Entered Today shows the name, one quiet follow-up. Two candidates
  (Oji, Jaya) 40 s apart, own edges at +13 min → both named. Jaya candidate + Ezinne anonymous crossing + Jaya edge
  → named. Jaya candidate + later attached `jaya` crossing → ambiguous. Jaya front candidate then Jaya garage
  candidate 3 min later → front `arrival_superseded`, garage named on her edge (B-M5). Jaya candidate + Ezinne's edge
  only → anonymous to expiry. Bermuda move and GPS fix at t_E − 20 s do not confirm. Stale-source edge confirms
  nothing. Edge at +901 s → `arrival_unconfirmed`. Edge arriving while the INSERT is still awaiting → confirmed,
  backfill applied when the row id lands (B-M6). INSERT returns None → confirmed, `arrival_confirm_no_row`. Ninth
  candidate → oldest `arrival_dropped_cap`.
- **Test:** the D8b confirmation list (`::test_confirm_waits_for_insert_row_id`,
  `::test_deferred_insert_then_ble_names_row_before_followup`, ...) plus `::test_pair_both_named_own_edges`,
  `::test_anonymous_intervening_crossing_does_not_abstain`, `::test_attached_same_slug_claim_abstains`,
  `::test_candidate_same_slug_supersedes`, `::test_partner_edge_never_confirms`,
  `::test_partner_edge_before_confirm_abstains`, `::test_edge_during_insert_await_confirms`,
  `::test_insert_none_confirms_without_backfill`, `::test_cap_drops_oldest`, `::test_gps_leg_needs_recent_prior_fix`,
  `::test_confirmed_confidence_below_security_bar`, `::test_one_confirmation_row_per_waiter`,
  `::test_fixture_yield_meets_floor` (hand-built `quality/tests/fixtures/egress_true_arrivals_2026_11_13.json` with
  per-field provenance and `assumed_*` markers; asserts ≥ `EGRESS_ARRIVAL_YIELD_FLOOR_FIXTURE` named under the stated
  assumptions and 0 wrong names on the 41-cluster fixture; docstring says rule-regression, not yield proof),
  `::test_zero_fire_tripwire`.
- **Trip-wire:** AnomalyDetector → NM when `arrival_candidate` outcome rows > 0 and `arrival_confirmed`
  confirmation rows = 0 over `EGRESS_ARRIVAL_ZERO_FIRE_DAYS` (14).
- **Live:** L-b within 7 days, a confirmation row for each candidate (confirmed with a backfilled `person_id`, or its
  terminal reason); compare the count with §5.5 (b).

**D3 ArrivalNotifier, nameable validation, pair state, perimeter read source and send routing.**
- **Verify:** name follow-up + crossing-vision count follow-up on one crossing → exactly 2 quiet sends; a third →
  False. A count follow-up passing `names=("jaya",)` for an unconfirmed candidate renders "2 more not recognised"
  with no name. Attached Jaya 0.9 at t_E with Ezinne's edge at t_E + 80 s → "Jaya Udezue arrived" at t_E + 45 s
  (unchanged), `pair_state` pending then conflict at t_E + 120 s, one pair-conflict line, and a perimeter follow-up
  on that door neither names Jaya from the egress record nor expires while pending. Attached Jaya 0.9 with no
  partner edge → perimeter follow-up names her at ≤ t_E + 125 s. Oji, Frigate one leg 0.6, `person.oji` home at
  +30 s, perimeter edge at +5 s → "that was Oji Udezue" exactly as today, sent through `send_perimeter_identity`
  (review H3 repro). Not-home Jaya face leg ≥ 0.9 on the doorbell during a perimeter alert → perimeter "that was
  Jaya" as today. Master off → every text, call and decision byte-identical.
- **Test:** `test_arrival_notify.py::test_cap_two_per_crossing`, `::test_name_requires_switch_and_threshold`,
  `::test_count_followup_refuses_candidate`, `::test_followup_refuses_unconfirmed_name_from_any_requester`,
  `::test_followup_on_aged_out_record_false`, `::test_attached_pair_member_named_at_45s`,
  `::test_pair_conflict_line_once`, `::test_display_of_matches_legacy_title`,
  `::test_perimeter_send_byte_identical_kwargs`, `::test_no_second_door_naming_site` (AST: any `async_notify` naming
  a person for a door crossing or door-camera alert lives in `arrival_notify.py`, except perimeter's master-off
  branch, which the test names); `test_perimeter_alert.py::test_master_on_reads_f3_not_cache`,
  `::test_pair_pending_not_known`, `::test_pair_conflict_not_known`, `::test_followup_waits_for_pair_pending`,
  `::test_face_nonface_path_kept_on_door_camera`, `::test_synthetic_nonface_path_kept_on_door_camera`,
  `::test_non_door_camera_unchanged`, `::test_door_camera_by_device_id_not_name`, `::test_master_off_cache_path_identical`.
- **Live (discriminating):** L-c the first arrival follow-up appears in `notification_log` with severity LOW and
  `acknowledged = 1`; for a digest-pref recipient its bucket is `digest_queued`; a follow-up that never writes a row,
  or writes it unacked, is a failure, not latency. L-c2 the next perimeter identity follow-up on a door camera has the
  same title / message shape as before ship.

**D4 sighting (c') and D2 egress branch.**
- **Verify:** a confirmed candidate yields one sighting with `identity_role="arrival_confirmed"`, `ts = crossing_ts`,
  provenance the A6 constant; a candidate never yields one before confirmation. D2 dispatches only for GPS-led
  confirmations with raw not-home; tracker-confirmed → skip `home`.
- **Test:** `test_person_sighting.py::test_confirmed_egress_source_role`, `::test_candidate_emits_no_sighting`,
  `::test_confirmed_sighting_teardown_unsubscribes`; `test_face_arrival_rule.py::test_confirmed_egress_dispatches_camera_egress`,
  `::test_tracker_confirmed_skips_home`.
- **Live:** L-d the first confirmed arrival shows a sighting row with role `arrival_confirmed`.

**D5 HVAC `camera_egress` (conditional, §6.10).**
- **Verify:** GPS-confirmed candidate → HVAC `pre_arrival` row; migration appends once and respects an operator who
  removed `camera_face`; no CM reload.
- **Test:** `test_hvac_camera_egress.py` (five named in the sighting plan) + `::test_migration_no_reload`.
- **Live:** L-e CM `pre_arrival_sources` contains `camera_egress`, sentinel set.

**D6 docs, same commit.** Manual §4.3 (veto direction-aware; owner `EgressDirectionTracker`), §4.6 / §5.5 (`person_id`
meaning, candidates, own-evidence naming, pair rule, pair state, one naming path); presence state of play §1 (ring,
`camera_egress`, `ArrivalNotifier`, perimeter read source with the master on); HVAC state of play §2 (only if D5
builds); sighting plan §2B pointer; contract rows (N1, P2 removed; R3 and the perimeter master-off cache row added).

**Mutation drills (framing C, each RED then restored):** M20-M22, M21b, M24, M27, M28, M28b, M29, M33-M35, M38-M41
from the sighting plan, plus: M56 drop K5 → `::test_k5_partner_arrival_vetoes_candidate`; M57 remove the amend cap →
`::test_cap_two_per_crossing`; M58 skip the switch read → `::test_name_requires_switch_and_threshold`; M59 skip the
`nameable` check → `::test_count_followup_refuses_candidate`; M60 let a partner edge confirm →
`::test_partner_edge_never_confirms`; M61 restore "any crossing abstains" → `::test_pair_both_named_own_edges`; M62
amend writes `_last_crossing_by_camera` unconditionally → `::test_ring_amend_does_not_clobber_newer`; M63 drop the
exit-zone evict → `::test_exit_zone_vetoed_still_evicts`; M64 confirmed confidence = face tier →
`::test_confirmed_confidence_below_security_bar`; M65 perimeter ignores `pair_state` →
`::test_pair_pending_not_known`; M66 perimeter skips the face+non-face branch on door cameras →
`::test_face_nonface_path_kept_on_door_camera`; M67 waiter registered after the INSERT await →
`::test_edge_during_insert_await_confirms`; M68 drop the synthetic-only predicate → `::test_k1_lone_synthetic_leg_vetoed`.

## 10. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `EGRESS_IDENTITY_DIRECTION_AWARE` | True at ship if both §5.5 gates pass | 1 | Master; False = INV-NOOP. Live kill for names = `switch.ura_name_people_at_doors` |
| `FACE_ARRIVAL_EGRESS_ENABLED` | True with the master if D5 builds, else False | 1 | `camera_egress` dispatch |
| `EGRESS_ARRIVAL_CANDIDATE_MIN_TIER` | `CONFIDENCE_MEDIUM` (0.6) | 1 | K1; raising to 0.75 restores rev 1's ~0 yield |
| `EGRESS_ARRIVAL_CONFIRMED_CONFIDENCE` | 0.75 | 1 | Must stay ≥ notification bar and < security bar (test-pinned) |
| `EGRESS_ARRIVAL_PATH_MIN` | 2 | 1 | 0 = K2 skipped |
| `EGRESS_ARRIVAL_MAX_SPEED_KMH` / `_GPS_MIN_AGE_S` / `_GPS_MAX_AGE_S` | 150 / 60 / 86400 | 1 | K3 physics bounds |
| `EGRESS_ARRIVAL_CONFIRM_WINDOW_S` | 900 | 1 | 4 of 10 true lags are 641-810 s; 0 = labels only |
| `EGRESS_ARRIVAL_CONFIRM_POLL_S` / `_MAX_PENDING` | 5 / 8 | 1 | sweep cadence; waiter cap (overflow drops oldest) |
| `EGRESS_ARRIVAL_CONFIRM_GPS_KM` | 0.5 | 1 | 0 = GPS leg off |
| `EGRESS_ARRIVAL_CONFIRM_GPS_PRIOR_MAX_AGE_S` | 1800 | 1 | prior fix must be recent (B-M7); 0 = GPS leg off |
| `EGRESS_CROSSING_RING_PER_CAMERA` | 32 | 1 | ring count; measured peak 9 / 30 min |
| `EGRESS_CROSSING_RING_MAX_AGE_S` | 1800 | 1 | ≥ confirm + pair + follow-up delay (test-pinned) |
| `CONF_EGRESS_CONFUSABLE_PAIRS` | empty | 2 (CM options, egress step, "Faces often confused") | per-house fact; empty = K5 and pair state off |
| `EGRESS_PAIR_GUARD_WINDOW_S` | 120 | 1 | 0 = K5 off and `pair_state` never set |
| `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` | 2 | 1 | alert hygiene; 0 = no amends |
| `EGRESS_ARRIVAL_YIELD_FLOOR_FIXTURE` | 4 (of 10) | 1 | rule-regression gate |
| `EGRESS_ARRIVAL_YIELD_FLOOR_PER_WEEK` | 1 | 1 | yield gate on ≥ 7 days of D8a log |
| `EGRESS_ARRIVAL_ZERO_FIRE_DAYS` | 14 | 1 | trip-wire window; 0 = off |
| `EGRESS_PATH_BUFFER_S` / `EGRESS_PATH_HOP_DEFAULT_WINDOW_S` | 180 / 30 | 1 | path horizons (sighting plan §2B.4) |

## 11. Non-goals

Changing direction resolution; any AWAY, ARRIVING or GUEST input (census deltas only lower the union); naming two
faces on one crossing; vision naming anyone; `SIGNAL_PERSON_DEPARTING`; access or security acting on `camera_egress`
or on an egress-confirmed identity; lowering the 0.9 bar; changing any perimeter evidence rule (H3); confusable-pair
awareness for perimeter's OWN face legs (today's behaviour, named residual); Protect face names; automatic pair
learning (parked; revival when the weekly labeller shows a second confusable pair); a DB role column; departure
actions (step 8); detector misses; raising notification severity (Q4).

## 12. Residuals named

- Perimeter's own face-leg path (`:5237-5261`) does not know about confusable pairs (today's behaviour; a 0.9 Jaya
  face leg on the doorbell while Ezinne arrives still names Jaya there). Not carded by this plan; the orchestrator
  decides whether to card it.
- A restart drops waiters and pair timers: rows stay NULL; a pair-pending record does not survive (the ring is RAM),
  so after a restart perimeter falls back to no egress identity for that crossing (safe direction).
- The patio door has no egress camera.

## 13. Operator questions (recommendations)

- **QA (G-M1). Attached Jaya / Ezinne arrivals: defer the name until the pair window closes?** Measured (§5.3):
  upper bound ~13 named pair-member entries per week (26 DB rows in 14 days); 1 in the 26 h D8a window; on the
  fixture 0-2 of the 3 named true arrivals. Cost of deferral: each is anonymous at t_E + 45 s and named at
  t_E + 120 s (75 s later), and stays anonymous when the partner's edge lands in ±120 s (D0 (j) gives that rate).
  Benefit: a Jaya/Ezinne swap on an attached crossing is not named at all instead of named then corrected.
  **Recommendation: no deferral (the plan default).** The arrival notification is a notification-class consumer
  where latency beats precision (`feedback_alert_latency_over_precision`), the measured swap case (11-11 08:25) was
  an Ezinne arrival correctly attached as `ezinne`, and the conflict line plus the security exclusion cover the
  wrong-name risk where it matters. Related, no answer needed unless you object: a pair-member attach reaches
  perimeter's follow-up up to 75 s later (§6.6); nothing is lost.
- **QB (G-M2). Entry with the phone in a named zone: candidate (rev 3) or named attach (today)?** The D8a window had
  0 such resolutions; D0 (i) gives per-week counts, how many were named today, how many were truly home, and the
  AWAY-within-300 s count (wrong-AWAY exposure). **Recommendation: keep rev 3 (candidate) if D0 (i) shows 0 wrong
  AWAYs; if it shows any, keep today's attach for named zones.** Basis: your 2026-11-12 rule that the name is
  withheld until the person's own corroboration.
- **Q1.** Naming basis: one 0.6 face leg + the person's own phone edge = 0.75 for notification (never security).
  Recommend yes; without it the yield is 0.
- **Q2.** Confusable pairs: `jaya|ezinne` only. Recommend yes.
- **Q3.** Master on at ship when both §5.5 gates pass. Recommend yes.
- **Q4.** Delivery: arrival notices and follow-ups are LOW (follow-ups quiet); a digest-pref recipient gets them in
  the next 08:00 / 18:00 digest. Recommend keep LOW; you set delivery per recipient.
- **Q5.** D5 HVAC `camera_egress`: park if D0 (g) = 0. Recommend park with trigger "D0 (g) > 0 per week".
- **Q6.** Protect face names stay out of scope. Recommend a card with trigger "Protect names reachable from HA".
- **Q7.** Untracked known faces (e.g. `ojini`): stop naming and registering at doors. Recommend yes (10 of 10 false).

## 14. Contract additions (for the orchestrator to amend `CONTRACT_person_awareness_layer.md`)

Each is something this plan needs that the contract lacks or states wrongly. D0b builds none of them until the
contract carries them.

| # | Addition | Why | Contract section |
|---|---|---|---|
| A1 | F1 pull `get_person_edges_since(t, *, persons, kinds)` on presence, over `ResidencyTracker.recent` (`residency.py:89`), same filters and record fields as G1 | K5 needs a partner's edges BEFORE the crossing; `get_recent_resident_arrival` is newest-of-any-resident | §2.1 read surface, §4.1, §5 (G1 sibling) |
| A1b | G1 edge payload also carries `counted` (residency field), next to `source_stale` / `in_boot_window` | confirmation leg (a) requires counted | §5 G1 |
| A2 | G6 `location_moves_since(t)` return shape: tuple of frozen records `(person_entity, from_room, to_room, ts, method)`, oldest first, pull only (no callback) | leg (b), K5; review H4 | §4.1, §5 G6 |
| A3 | F3 `get_crossing(source_ref)`; and G2 semantics: served from the owner's ring, retention `EGRESS_CROSSING_RING_PER_CAMERA` / `_MAX_AGE_S`, oldest first, amended records keep position | notifier lookup; review H1 | §2.3 store/read, §4.1, §5 G2 |
| A4 | `CrossingRecord` additive fields `identity_role`, `nameable`, `pair_state`, `pair_partner`, `identity_synthetic_corroborated`; owner-only amend by `source_ref` | §6.4 | §2.3 store |
| A5 | Sixth push channel `SIGNAL_EGRESS_ENTRY_CONFIRMED` (F3), owner `EgressDirectionTracker` | review B-M8 | §4.2 |
| A6 | Provenance constants `IDENTITY_PROVENANCE_FACE_RESIDENCY` = `face+residency`, `_FACE_BLE_MOVE` = `face+ble_move`, `_FACE_GPS` = `face+gps`, added to `IDENTITY_PROVENANCE_VALUES` (`const.py:3499`) | review B-M8 | §2.3 provenance |
| A7 | Define `PersonArrivingPayload` (frozen dataclass in `domain_coordinators/signals.py`: `person_entity`, `source`, `sighting=None`, `zone=""`, additive `ts=None`; `to_signal()` = today's dict keys exactly, `from_signal()`); correct the "exists at `signals.py:28-64`" citation and the raw-send lines to `presence.py:5622`, `:5881`, `person_coordinator.py:1141` | review B-M3, B-L1 | §2.5, §4.2 |
| A8 | Public `PersonCensus.tracked_person_slugs()` (the contract lists it; code has only `_get_tracked_person_slugs` `camera_census.py:3901`) and NEW `PersonCensus.egress_naming_enabled()` (wraps `_is_egress_identity_enabled` `:4127`) | review B-M4, B-L3 | §2.6 identity evidence |
| A9 | Public `EgressDirectionTracker.door_camera_device_ids()` (registry `device_id` of each egress entity) | perimeter door-camera test by registry; review B-L6 | §4.1 F3 row (next to G5 `entry_areas`) |
| A10 | Name `ArrivalNotifier` (`domain_coordinators/arrival_notify.py`, class notification, `hass.data[DOMAIN]["arrival_notifier"]`) as the "notification consumer" §7 moves the amend function into, and the single door-naming send site | review H3 | §2.3 note, §7 |
| A11 | Consumer-class rule: an F3 record with `pair_state` ∈ {`pending`, `conflict`} does not qualify for the security class | review H2 | §2 consumer classes / §2.3 |
| A12 | Allowlist row, until the master is retired: perimeter `_note_egress_identity` cache read on the master-off path only (G2 on the master-on path) | INV-NOOP; review B-H3 | audit §5 allowlist |
| A13 | Allowlist row R3: `transit_validator.freshest_gps_fix` reads GPS `device_tracker.*` (producer-internal, max 1) | K3, leg (c) | audit §5 allowlist |

## 15. Orchestrator-owned edits (outside this plan's files)

- **Arc map, `ARC_identity_vision_census_map.md:45` (L7 / B-L7).** Replace the whole row with:

  `| **EGRESS-DIRECTION-AWARE-IDENTITY-1** = sightings §2B / D8 (Phase 2), with FACE-EGRESS-ARRIVAL-1 folded (§2B.6) | P: F3 (identity role, confirmed name, pair state), F5 `camera_egress` (confirmed candidates, conditional on D0 (g)). C: F1 edges (G1 + pull A1), F4-BLE (G6), F3, path map | notif (follow-up via ArrivalNotifier), disp, sec (perimeter D10.5 and scoped mute: never on a pair-pending / conflict record, never on an egress-confirmed 0.75), acc never on `camera_egress` alone (INV-ACCESS, `arrival_source_needs_corroboration`), comfort via F5 → HVAC `camera_egress` (D5, conditional) | `transit_validator.py` veto `:2036-2050`, `_resolve_egress_face_identity_ex`, crossing ring + `_amend_crossing`, `_arrival_departure_notify` moved to `arrival_notify.ArrivalNotifier`, perimeter `_known_identity_for` (G2 read, master on), D2 egress branch, HVAC source selector | Phase 2 gates: misrecognition 0 on replay + Wilson ≤ 0.30; yield ≥ 4/10 fixture and ≥ 1/week on D8a; Jaya/Ezinne pair guard | plan rev 3 | 7 |`

  (Changes: veto `:1840-1854` → `:2036-2050`; "acc (only with second signal, D3 gate)" → "acc never on
  `camera_egress` alone", which matches INV-ACCESS; "hs via F5 → HVAC" → "comfort via F5 → HVAC" since HVAC is a
  comfort-class consumer; status "planned" → "plan rev 3".)
- **Arc map M8 / scoped mute row (rev 1 M8, still open):** the scoped mute's qualifying crossing gains
  `pair_state ∉ {pending, conflict}` (§6.10); its "egress naming reduces walk-out alerts" expectation does not hold
  for step 7.
- **Contract amendment:** §14 A1-A13.
- **Adjacency sweep and cards:** detector misses (2 of 10); perimeter face-leg confusable-pair residual (§12) if you
  want it carded.
- **Identity manual §4.3 owner name** (`TransitValidator` → `EgressDirectionTracker`) lands in D6.

## 16. Tier, reviews, dependency, completion tracking

Tier 3: threads a role and a pair state through the egress state machine read by census, notify, displays, perimeter,
mute, sightings, D2, HVAC; one missed site leaks a name or drops one. Plan reviews: 1 and 2 done (FIX-PLAN each,
dispositioned); a re-check of review 2's findings plus framing G on rev 3 before build. Code reviews: A local, B
integration / restart / teardown, C per-site mutation (§9 list), D completeness on INV-PROVISIONAL,
INV-ONE-NAMING-PATH, INV-NO-NAME-LOSS, INV-SECURITY-BAR, INV-RING and INV-NO-AWAY-DELAY including pre-existing
readers; G goal fidelity. Orchestrator re-grep and one real mutation; operator checkpoint before deploy with both
§5.5 gate results. Step 8: shipping this provides `notify_arrival_followup`; no step-8 deliverable that names a
person may build against another amend path.

Not done here, tracked: automatic pair learning (parked); `EGRESS-PATH-OVERRIDES-DIRECTION-1` (evidence only);
Protect face bridge (Q6); detector misses (orchestrator); patio door; perimeter face-leg pair residual (§12).
Changed in rev 3: ring with retention and amend-by-`source_ref`; perimeter reads F3 via G2 with `pair_state` (master
on) and keeps every evidence path; perimeter door-camera sends routed through `ArrivalNotifier`; attached-pair
deferral removed (QA); guards renamed K1-K5; contract seam names; contract additions §14; waiter registered before the
INSERT await; supersede vs conflict split; GPS prior-fix bound; outcome accounting split into outcome and
confirmation rows; fixture provenance marked; D0 (i) and (j).

## 17. Plan review 2 disposition

| Finding | Disposition in rev 3 |
|---|---|
| B-H1 ring | Fixed: §6.4 (per-camera ring, count 32 and age 1800 rung 1, amend by `source_ref`, last-crossing untouched unless newest, aged-out → False counted, 11-03 worked case), INV-RING, M62, A3/A4 |
| B-H2 pair vs bus timing | Fixed: §6.6 (owner `pair_state` pending → clear/conflict at t_E + 120; perimeter master-on reads F3 via G2 and skips pending/conflict; follow-up waits for pending), INV-SECURITY-BAR (b) with the 0.9 falsifier, M65, A11. Timing note: review's +90 s repro does not match at `MATCH_S` 15; the reachable variant is the follow-up and mute |
| B-H3 / G-H1 perimeter reroute | Fixed per ruling: face+non-face and synthetic+non-face kept on door cameras, routing of the send only, master-gated; INV-NO-NAME-LOSS, INV-NOOP perimeter replay, M66, review repro is a D3 Verify |
| B-H4 seams | Fixed: contract names verbatim (`subscribe_person_edges(cb, *, persons, kinds)`, `location_moves_since` as a polled pull); missing pieces listed as A1-A13 |
| B-M1 G-label clash | Fixed: guards K1-K5 |
| B-M2 synthetic predicate | Fixed: §6.2 K1 predicate, M68 |
| B-M3 payload | Fixed: A7 (marked NEW, fields from `presence.py:5622`, `:5881`, `person_coordinator.py:1141`) |
| B-M4 roster API | Fixed: A8, D0b test |
| B-M5 supersede vs conflict | Fixed: §6.3 (candidate-candidate = supersede; (i) only for attached claims), D2 test |
| B-M6 edges before waiter | Fixed: §6.3 waiter start (synchronous, before the await; tracker-wide G1 subscription; G6 pull from `crossing_ts`), None row id path, M67 |
| B-M7 GPS prior fix | Fixed: prior fix captured at K3, age knob 1800, HA state only; leg droppable on D0 (b) |
| B-M8 new F3 surfaces | Fixed: A5, A6; sighting (c') bypasses the `:458` gate by design (§6.9) |
| B-M9 accounting | Fixed: §6.8 (one outcome row, one deque entry, one confirmation row per crossing) |
| B-M10 fixture | Fixed: §5.1 provenance, `assumed_*` fields, gate (a) relabelled rule-regression, gate (b) is the yield proof |
| B-L1 lines | Fixed in this plan; contract fix is A7 |
| B-L2 helper home | Fixed: `transit_validator.freshest_gps_fix` |
| B-L3 switch read | Fixed: A8 `egress_naming_enabled()` |
| B-L4 overflow | Fixed: drop oldest, `arrival_dropped_cap` |
| B-L5 notifier reach | Fixed: §6.7 hass.data key, None-safe fallback |
| B-L6 perimeter entity | Fixed: `state["entity_id"]` → registry `device_id` vs A9 |
| B-L7 arc map | Exact text in §15 |
| G-M1 deferral | Not decided: measured §5.3, D0 (j), QA; default no deferral, conflict follow-up line |
| G-M2 zone AWAY | D0 (i), §5.4 cost model, QB |
