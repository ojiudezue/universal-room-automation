# PLANNING: direction-aware egress identity (arc step 7), rev 2

Card: EGRESS-DIRECTION-AWARE-IDENTITY-1 (thread identity, batch person-sightings, parent FACE-ARRIVAL-REBUILD-1;
FACE-EGRESS-ARRIVAL-1 folded). Arc: identity / vision / census, step 7 of `ARC_identity_vision_census_map.md` §4.
Tier 3. Status: rev 2, awaiting plan review 2 (adversarial build-prediction) and framing G re-check. Author
ura-planner, 2026-11-14, develop @ 371af9fd. Rev 1 is archived verbatim at
`docs/planning/archive/PLANNING_egress_direction_aware_identity_rev1.md`; nothing below layers on it.

Inputs to this revision: plan review 1 (`docs/reviews/plan-review/PLANREVIEW_egress_direction_aware_identity_1.md`,
FIX-PLAN, disposition table in §15), the layer contract `CONTRACT_person_awareness_layer.md` (§6 conformance check,
table in §3 here) and its audit `AUDIT_person_awareness_layer_leaks_2026_11_14.md` (§6 step-7 edits; the contract's
"audit §9" pointer means that §6, the audit has no §9), the charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`.

This file is the ONE build spec for Phase 2 of the person-sighting plan (§2B, D8b). Where
`PLANNING_person_sighting_layer.md` §2B / D8b differ, this file wins; the sighting plan gets a pointer in the D6 docs
commit.

Read first, completely (stated per CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (D5 touches `pre_arrival_sources`). No
corrections-ledger claim is re-asserted. Code-vs-doc contradictions (code wins, fixed in D6): manual §4.3 names
`TransitValidator` as the egress owner; the class is `EgressDirectionTracker` (`transit_validator.py:963`).

## 0. Operator decision recorded (2026-11-14)

Recommendation put to the operator after plan review 1 H1: allow naming for arrivals in pairs instead of abstaining
whenever anyone else crosses before confirmation, and add a minimum-yield gate the plan must meet before ship
(alongside the misrecognition gate). Operator, verbatim: **"Agreed"**.

Design constraints the operator attached to that recommendation, all carried into §6.4: each named person still needs
their own evidence at ≥ 0.75 for notification (no name inherited from a partner); conflicted pairs stay unnamed; the
0.9 security bar is unchanged.

## 1. Charter, goal served, drift check

Goals served, verbatim from the charter: "assist arrivals accuracy and personalization"; "egress only names people
who are already home... Who made this rule? ... It should do both"; "make it faster and faster until it can
eventually be used in security applications too". Hard constraint: "I need away to be fast acting."

What this delivers: arrivals the face-only veto erases today get a name minutes later, once the person's OWN phone
confirms them, including two people arriving together. Measured on the labelled fixture (§5): 4 of the 10 true
vetoed-or-missed arrivals become named, so named true arrivals go from 3 of 10 to 7 of 10. Departures get a label.
AWAY is not touched.

Drift check (ura-arc rule 3): rev 1 claimed zero drift and was wrong (review H1: its guards named about 0 of 10).
Rev 2 changes WHAT is delivered back toward the goal, and the two risk reductions that remain (name withheld until
the person's own phone confirms; the security bar is not lowered) were chosen by the operator (2026-11-12: "the name
is withheld from every consumer until the after-the-fact corroboration"; 2026-11-14: "Agreed"). What still stays
anonymous, named so it is not silent: two faces on ONE crossing (G4), same-slug double claims, confusable-pair
conflicts, crossings the egress detector never logged (2 of 10, §5), and arrivals whose phone confirms after 900 s.

## 2. Institutional context verified

Greps run 2026-11-14 on develop @ 371af9fd (each verdict re-checked, not inherited from rev 1):
`def _arrival_departure_notify|_resolve_egress_face_identity_ex|EGRESS_IDENTITY_DIRECTION_AWARE|CONSUMER_CLASS_MIN_CONFIDENCE|get_last_crossing|SIGNAL_EGRESS_ENTRY_CONFIRMED`;
`def subscribe_resident_edges|def dispatch_person_arriving|def view_for_class|def min_confidence|def get_crossings_since|def attach_crossing_attribute|def location_moves_since|def entry_areas`
(only `view_for_class` exists, `presence.py:5984`); `    def [a-z]` in `transit_validator.py` and `residency.py`;
`^def ` in `arrival_edges.py`; `_known_identity_for|_followup_check|_note_egress_identity|resolve_face_legs` in
`perimeter_alert.py`; `digest|quiet` in `notification_manager.py`; `get_pending_digest` in `database.py`.

| Piece | Verdict | Where |
|---|---|---|
| Face-only veto to replace | REUSED site | `transit_validator.py:2036-2050` (`_person_raw == "not_home"`, outcome `vetoed`) |
| Tier helper | REUSED | `egress_identity_tier_labelled` `:127-161` (one leg = `CONFIDENCE_MEDIUM` 0.6; ≥2 legs one camera = BOOST; two cameras = HIGH 0.9) |
| Resolver + caller | REUSED, extend | `_resolve_egress_face_identity_ex` `:1497`, caller `:2192` |
| Outcome log (D8a, live) | REUSED, new outcome labels | `_log_egress_outcome` `:2576`; `EGRESS_OUTCOME_EPISODE_TYPE` `const.py:3516` |
| Crossing record | REUSED, additive fields | `CrossingRecord` frozen dataclass `:943-960`; `_record_crossing` `:2247`; `get_last_crossing` `:1044` |
| Door-camera roster | REUSED + NEW sibling | `door_camera_stems()` `:1294`; NEW `door_camera_device_ids()` (registry `device_id` of each egress entity; Registry-not-names rule) |
| Arrival/departure notify | REUSED, MOVED (contract §7, audit N1) | `_arrival_departure_notify` `:2647`, call `:2278`; moves to NEW `domain_coordinators/arrival_notify.py` |
| Census register / evict | REUSED, unchanged calls | `:2306-2332`; `register_egress_face` / `evict_egress_face` (`camera_census.py:4381, 4456`) |
| DB INSERT | REUSED, return row id | `database.log_entry_exit_event` `database.py:4600` (returns None today), call `transit_validator.py:2348` |
| Row-id backfill | REUSED | `database.backfill_entry_exit_person_id` `database.py:4723` (idempotent) |
| Exit-backfill display pattern | REUSED | `SIGNAL_EGRESS_EXIT_BACKFILLED` `signals.py:39`; readers `sensor.py:4960`, `:5114` |
| F1 edge ledger | REUSED owner | `ResidencyTracker` `domain_coordinators/residency.py:62` (`on_event` `:109`, `recent_arrival` `:163`) |
| F1 edge subscription | NEW seam G1 (contract §5) | `subscribe_resident_edges(cb)` on presence, fed by `ResidencyTracker`; grep 0 hits |
| F5 dispatch | NEW seam G4 (contract §5) | `signals.dispatch_person_arriving(hass, PersonArrivingPayload)`; grep 0 hits; payload `signals.py:28-64` REUSED |
| F4-BLE moves | NEW seam G6 (contract §5) | `PersonTrackingCoordinator.location_moves_since(t)`; grep 0 hits |
| F3 history read | NEW seam G2 (contract §5) | `get_crossings_since(t, camera=None)`; grep 0 hits |
| Census view by class | REUSED | `PresenceCoordinator.view_for_class` `presence.py:5984` |
| Class thresholds | REUSED | `CONSUMER_CLASS_MIN_CONFIDENCE` `const.py:6512`; classes `const.py:6495-6499` |
| Stale-source rule | REUSED | `arrival_edges.stale_source_arrival` `:72` |
| Bermuda into entry area | REUSED pure rule | `arrival_edges.bermuda_arrival_into` `:191`, `nonface_arrival_source` `:269` (inputs now come from G1/G6, not tracker-local ledgers) |
| Camera-derived set | REUSED | `CAMERA_DERIVED_ARRIVAL_SOURCES` `const.py:3486` (holds `camera_egress`) |
| D2 arrival site | REUSED, egress branch | `PresenceCoordinator._derive_face_arrival` `presence.py:5825` |
| Quiet follow-up send | REUSED | `NotificationManager.async_notify(..., quiet=)` `notification_manager.py:1544`; quiet rows pre-acked `:1889` |
| Digest carries LOW | REUSED, verified | `get_pending_digest` `database.py:4925-4928` (`severity IN ('LOW','MEDIUM')`); digest-pref LOW is queued, not sent (`notification_manager.py:1965-1971`) |
| Perimeter D10.5 naming | REUSED site, REROUTED (H3) | `_known_identity_for` `perimeter_alert.py:5178-5262` (face legs read at `:5238`), follow-up `:5519-5589`, bus cache `_note_egress_identity` `:5156` |
| Below-floor face + own non-face signal (precedent) | REUSED rule | `perimeter_alert.py:5256-5261` (operator 2026-11-08) |
| Path scorer | REUSED | D7 `interior_paths.score_path`, loader `async_setup_path_map` `transit_validator.py:2363` |
| Sighting producer | REUSED, changed (M6) | `person_sighting.py:449-491` (role hardcoded `"attached"` at `:491`) |
| HVAC source filter | REUSED, conditional (D5) | `DEFAULT_PRE_ARRIVAL_SOURCES` `hvac_const.py:350`, literal `hvac.py:881`, selector `config_flow.py:8192`, filter `hvac.py:1431-1440`; migration precedent `_migrate_hvac_zone_entry_dwell_to_zero` `__init__.py:749` |
| Attach-rate counter | REUSED, relabel | `sensor.py:3993` |
| `freshest_gps_fix` | NEW pure helper in `arrival_edges` | grep `gps_fix` 0 hits outside plans |
| `SIGNAL_EGRESS_ENTRY_CONFIRMED`, `EGRESS_OUTCOMES_ATTACHED` | NEW | grep 0 hits |
| `CONF_EGRESS_CONFUSABLE_PAIRS` | NEW | grep `confusable` 0 hits in code; §2B.3 parked trigger fired |
| `ArrivalNotifier` (`notify_arrival`, `notify_arrival_followup`) | NEW module, moved logic | contract §7 moves the amend function out of the F3 owner; no NM-side arrival consumer exists |

Prior plans read: `PLANNING_person_sighting_layer.md` §0A, §2A, §2B, D8; `PLANNING_crossing_vision.md` §1-§8
(P2-D9 names at :376-378); `PLANNING_identity_actions_v6.md` (amend call :160, departure raw edge :149);
`PLANNING_census_deconfliction.md` §3.2; `PLANNING_person_awareness_read_api.md`; `PLANNING_perimeter_egress_mute_scoped.md`
:49-65; the contract and its plan review `PLANREVIEW_person_awareness_layer_contract.md` (D6: G1 must not gate
presence's own geofence AWAY trigger). Analysis: `AUDIT_egress_history_labels_2026_11_13.md` (whole), live D8a log
(§5). Memory: `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`,
`feedback_alert_latency_over_precision`, `feedback_registry_not_name_guessing`, `reference_egress_face_coverage_7pct_not_a_ceiling`.
Config-first: no knob makes the veto direction-aware; `switch.ura_name_people_at_doors` only turns naming off.

## 3. Facts, consumer classes, layer conformance (contract §6)

Produces F3 (identity role on a crossing; confirmed name later) and F5 `camera_egress` (only if D5 survives its fire
check). Consumes F1 edges and levels, F4-BLE, F3. Never writes F2 for a candidate.

| # | Check | This plan |
|---|---|---|
| 1 Facts | produce | F3 identity role + confirmed name; F5 `camera_egress` (conditional, D5) |
| | consume | F1 edges (confirmation leg a, G5 partner edge); F1 raw level at resolution (the veto itself, layer-internal producer read, contract §2.1); F4-BLE (confirmation leg b, G5 partner move); F3 (notify, perimeter, sightings, displays) |
| 2 Ingest | F3 | `EgressDirectionTracker._resolve_direction` → `_record_crossing` + bus + DB (the one F3 ingest). Confirmation updates the record inside the owner (`dataclasses.replace` in the ring); no other module writes it |
| | F5 | `signals.dispatch_person_arriving` (G4). No raw `async_dispatcher_send(SIGNAL_PERSON_ARRIVING, ...)` |
| | F2 | none new. Register/evict calls stay the existing egress pair; a candidate never registers |
| | F4 | `PersonSightingProducer._emit` source (c') — the one F4 ingest |
| 3 Read | F1 edges | `subscribe_resident_edges(cb)` (G1). The tracker adds NO `person.*` state listener |
| | F4-BLE | `location_moves_since(t)` (G6) and `get_person_location` |
| | F3 | `get_last_crossing`, `get_crossings_since` (G2), bus `ura_person_egress_event` |
| | F2 | none. If a follow-up ever needs a count, it reads `get_house_census(view_for_class("notification"))` |
| | thresholds | `CONSUMER_CLASS_MIN_CONFIDENCE["notification"]` / `["security"]` by name (min_confidence once G-ship-3 adds it). No inline 0.75 / 0.9 |
| | classes | `ArrivalNotifier` = notification; four entry/exit sensors, attach counter = display; D10.5 + scoped mute = security; HVAC pre-arrival and music following (`music_following.py:549-583`, via F4/F5 channels, no change) = comfort; locks, alarm, security expected-arrival add (`security.py:2424-2429`) = access (never on `camera_egress` alone); house_state = no input changes |
| 4 Separation | | No F4 reaches F2 here. Nothing reaches access on F4 or on `camera_egress` alone |
| 5 Guard delta | | removes N1 (notify hosted in the F3 owner) and P2 for the attach record (candidate provenance lives on `CrossingRecord`, not on the census). Adds one R3 row: `transit_validator.freshest_gps_fix` reads GPS `device_tracker.*` (producer-internal, max 1, this card). Zero rows for new consumers |
| 6 Seams | | G1, G2, G4, G6 are owned by PERSON-AWARENESS-READ-API-1 ship 3 (G1 shared with the LOCK restart plan and STALE-SOURCE-ARRIVAL-CONSUMERS-1, arc merge M13). Rule: if ship 3 has not merged when this build dispatches, D0b builds exactly those four seams in their owner modules to the contract signatures and ship 3 drops them; no private copies. `ArrivalNotifier.notify_arrival_followup` is the single owner of arrival naming for this card, crossing vision P2-D9, step 8 and perimeter D10.5 on door cameras (§6.6). Scoped egress mute: see §6.9 |
| 7 Clip path | | no vision frame source touched |

## 4. Falsifiable invariants (reviewer D breaks these, pre-existing code included)

- **INV-PROVISIONAL (arrivals).** Before the slug's own confirming edge, no consumer receives a candidate's slug as
  identity: bus `person_id` and any bus key (no `candidate_person_id` on the bus, L4), DB `person_id`,
  `CrossingRecord.person_id` / `nameable`, any notification text (original, name follow-up, count follow-up, perimeter
  "that was"), the four displays, census union, `SIGNAL_PERSON_SIGHTING`, `SIGNAL_PERSON_ARRIVING`. Break it with any
  of those carrying the slug with no edge of that slug's own device timestamped after the crossing.
- **INV-OWN-EVIDENCE.** A name renders in a notification only from that slug's own entry in the crossing's `nameable`
  map at ≥ `CONSUMER_CLASS_MIN_CONFIDENCE["notification"]`. Break it with a name rendered from a partner's edge, from
  a crossing-vision face entity, from a perimeter face leg, or from a pair whose members conflict.
- **INV-ONE-NAMING-PATH.** Every arrival message after the original, from any caller (this card, crossing vision,
  step 8, perimeter D10.5 on a door camera), goes through `ArrivalNotifier.notify_arrival_followup`, at most
  `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` per crossing. Break it with a second send site that names a person for a door
  crossing, or a third amend.
- **INV-CANDIDATE.** A candidate exists only if the slug is tracked (M7), G1 passes, G2 does not fail, G3 does not
  fail, G4 returned one slug, and G5 does not fire.
- **INV-SECURITY-BAR.** No egress-confirmed identity carries confidence ≥ `CONSUMER_CLASS_MIN_CONFIDENCE["security"]`,
  and no pair-conflicted identity qualifies for a security-class consumer (D10.5 demote, scoped egress mute). Break it
  with a confirmed candidate or a conflicted attach reaching a security decision.
- **INV-ACCESS (unchanged, re-proven).** No `camera_egress` arrival alone releases a lock, unlocks, adds an expected
  arrival or disarms (GPS-near-only confirmation included).
- **INV-NO-AWAY-DELAY (restated per M2).** With the switch on, no reachable path delays AWAY entry relative to the
  switch off: every census delta either removes a registration or keeps an evict; no inference input
  (`infer()` / `_run_inference`, residency producer, census trust view, presence's own geofence trigger) changes.
  Break it with a slug held in the union longer than switch-off would hold it.
- **INV-NOOP.** Switch off: outcome labels, DB row, notification text and recipients, census calls, bus dict and
  perimeter behaviour byte-identical to develop; golden replay over entry x {home, not_home, zone, unknown, untracked}
  and exit x {home, not_home, zone}.
- **INV-PAIR.** With `jaya|ezinne` configured: a named not-home slug whose partner made a non-face arrival edge in
  [t_E − 120 s, confirming edge] never gets named for that crossing; an attached slug whose partner made such an edge
  in [t_E − 120 s, t_E + 120 s] is never named for that crossing (the forward 75 s is covered by deferring the name,
  §6.5).

## 5. Measured yield (H1, the operator's minimum-yield gate)

### 5.1 Fixture replay: the 10 TRUE arrivals (`AUDIT_egress_history_labels_2026_11_13.md` :51-71)

Rule applied: rev 2 (§6), confirm window 900 s, pair `jaya|ezinne`.

| Crossing | Face / URA row | Own home edge | Today | Rev 1 | Rev 2 | Reason |
|---|---|---|---|---|---|---|
| 10-30 19:45 Jaya front | entry/null@+5; exit/jaya@+49 | ≤ +266 (snap) | anon | anon | **anon** | same-slug second claim (an exit attached `jaya`) in the interval: conflict (i) |
| 10-31 13:34 Ezinne front | no URA row | ≤ +496 | none | none | **none** | detector logged no crossing (out of scope) |
| 10-31 21:31 Ezinne front | entry/ezinne@+46 | ≤ +286 | named | named | named | already attached |
| 11-02 08:50 Oji front | entry/oji_udezue@+46 | ≤ +387 | named | named | named | already attached |
| 11-03 08:36 Ezinne front | entry/ezinne@+62 | ≤ +791 | named | named | named | already attached (review 1 counted it as a candidate; the row carries `ezinne`) |
| 11-03 22:37 Oji front | entry/null@+46 | ≤ +810 | anon | anon | **NAMED** | pair arrival with Jaya; own edge; not a confusable pair |
| 11-03 22:38 Jaya front | entry/null@+16 | ≤ +781 | anon | anon | **NAMED** | pair arrival with Oji; own edge; Ezinne home already (no partner edge) |
| 11-04 22:53 Jaya garage | no URA row | ≤ +641 | none | none | **none** | detector logged no crossing |
| 11-07 10:35 Oji garage | entry/null@+47 | +412 (recorder) | anon | anon (tier) | **NAMED** | own edge |
| 11-08 17:34 Jaya front | entry/null@+46; exit/null@+96 | +356 (recorder) | anon | anon | **NAMED** | the intervening crossing is anonymous, not a claim |

**Expected named count: 4 newly named of the 10 (7 of 10 named in total, vs 3 today and 3 under rev 1).** At a 600 s
window the 11-03 pair drops (781 / 810 s are snapshot upper bounds), giving 2. Caveats, stated: (a) the null rows
predate D8a, so the fixture cannot show whether URA's resolver had a face leg at each (Frigate did); 4 is an upper
bound until D0 replays the outcome log; (b) 11-03 22:37 / 22:38 rest on 15-minute snapshots.

Misrecognition replay on the other 31 clusters: 0 projected wrong names. The 19 Jaya phone-away clusters, the 9 Oji
group C and the 11-12 07:23 false Oji have no own home edge within 900 s, so they stay anonymous; the 11-11 08:25
shape (Jaya face, Ezinne's phone arriving) stays anonymous twice over (Jaya's own edge comes at 16:29, and G5 fires on
Ezinne's edge); the 10 Ojini events are untracked (M7) and the 2 Ziri have no edge.

### 5.2 Live D8a outcome log (79 rows, 2026-11-13 08:25 to 19:45 CST, `ssh ha sqlite3 -readonly`, run 11-14 02:50)

Outcomes: 42 `direction_ambiguous`, 23 `no_leg`, 6 `attached` (5 at tier 0.6, 1 at 0.9 synthetic), 4 `attached_ble`
(0.72), 4 `vetoed`. All 4 vetoed are `jaya` at tier 0.6 (14:11 exit, 14:11 entry, 14:32 entry, 14:36 exit) while
Ezinne's phone was home all afternoon; `person.jaya` first reads `home` at 18:13:01 (recorder), 3.5 h later. Rev 2
projection for this window: 2 entry candidates, 0 confirmed, 0 named — correctly, because Jaya's own phone did not
arrive. Rev 1 (G1 at 0.75) would have formed 0 candidates. Silence after 19:45 is overnight quiet: the crossing table
also has no rows after 19:43 CST, and the episode table wrote at 22:00 CST.

### 5.3 The two ship gates (both must pass; measured in D0, re-run before the operator checkpoint)

1. **Misrecognition gate (unchanged intent).** Replay wrong-person names on the 41-cluster fixture and on every
   outcome-log candidate = 0, and the resolver-level upper Wilson bound on tracked residents ≤ 0.30 (today 3/30
   [0.6, 16.7] to 3/30 with flips [3.5, 25.6], audit :222-223). A non-zero replay count blocks the confirmation leg
   that produced it, not the plan.
2. **Minimum-yield gate (NEW, operator 2026-11-14).** (a) The deterministic fixture replay names at least
   `EGRESS_ARRIVAL_YIELD_FLOOR_FIXTURE` = **4** of the 10 TRUE arrivals (the measured value; any design change that
   drops it below 4 fails the gate and goes back to the operator). (b) Over at least 7 days of D8a log before ship,
   projected confirmed names ≥ `EGRESS_ARRIVAL_YIELD_FLOOR_PER_WEEK` = **1** per week (the fixture rate is 4 in 14
   days = 2 per week; the floor is half of it to allow week-to-week variance). Below (b): the operator decides, the
   plan does not ship by default. Both knobs are rung 1 (module constants in `const.py`, read by the replay test and
   the D0 report): a ship gate must not be turnable without review. After ship, a zero-fire trip-wire replaces the
   calendar (§9 D2).

## 6. Design

### 6.1 The rule (face-only single-slug path; BLE branches unchanged; master `EGRESS_IDENTITY_DIRECTION_AWARE`)

| Direction | Slug status | Raw `person.<slug>` at resolution | Outcome (switch on) | Bus / DB `person_id` | Census call |
|---|---|---|---|---|---|
| entry | tracked | `home` | `attached` | slug | register (as today) |
| entry | tracked | `not_home` or a named zone | `arrival_candidate` if G1-G5 allow, else `vetoed_arrival_unverified` (failed guard named) | None | none (today: zone registers, not_home none) |
| entry / exit | tracked | missing / unknown / unavailable | `attached` (fail-open, as today) | slug | as today |
| entry / exit | untracked (M7: not in the tracked roster, e.g. `ojini`) | n/a | `vetoed_untracked` | None | none (today: registers) |
| exit | tracked | `home` | `departure_attached` (counted attached; L3 rename) | slug | evict (as today) |
| exit | tracked | named zone | `vetoed`, **evict kept** (M2) | None | evict (as today) |
| exit | tracked | `not_home` | `vetoed` (as today) | None | none (as today) |
| ambiguous | any | any | unchanged | None | none |

Tracked roster: the census public `tracked_person_slugs` (contract §2.6), the same membership test the sighting
producer applies. Declared switch-on census deltas, all of which can only lower the union (INV-NO-AWAY-DELAY): entry +
zone no longer registers; untracked faces no longer register.

### 6.2 Guards (evaluated at the resolution instant, `t_E + ENTRY_WINDOW_SECONDS` = 45 s; timing unchanged)

- **G1 face leg.** Tier ≥ `EGRESS_ARRIVAL_CANDIDATE_MIN_TIER` (= `CONFIDENCE_MEDIUM`, 0.6, one live leg) and not
  synthetic-only. Rev 1 required 0.75, which every live veto fails (§5.2). The face tier is no longer what names the
  person; the own-edge confirmation is (§6.3). Operator confirm: Q1.
- **G2 path.** `score_path(...)` below `EGRESS_ARRIVAL_PATH_MIN` (2) on a mapped door = FAIL. A door with no map, or
  `EGRESS_ARRIVAL_PATH_MIN` = 0, is `skipped` and passes (rev 1 tightened skipped to 0.9; dropped, same reason as G1).
- **G3 implied speed.** `arrival_edges.freshest_gps_fix(hass, person_entity)` (registry-resolved trackers of that
  person, `source_type == "gps"`, the tracker's own `last_updated`); distance to `zone.home` minus accuracy and radius
  over the fix age (floored at `EGRESS_ARRIVAL_GPS_MIN_AGE_S`, 60 s); FAIL above `EGRESS_ARRIVAL_MAX_SPEED_KMH` (150);
  no fix or older than `EGRESS_ARRIVAL_GPS_MAX_AGE_S` (86400) = `skipped`.
- **G4 single name.** The existing abstain / disagree rules returned one slug (unchanged). Two faces on ONE crossing
  stay anonymous (named residual; the count follow-up says "and 1 more").
- **G5 confusable pair.** If the slug has a partner in `CONF_EGRESS_CONFUSABLE_PAIRS` and that partner has a non-face
  arrival edge in [t_E − `EGRESS_PAIR_GUARD_WINDOW_S`, t_E + 45 s]: outcome `vetoed_pair_confusable`, no candidate.
  The window continues forward at confirmation (§6.3) and for attached entries (§6.5), which closes review H4's blind
  75 s. Partner edges come only from G1 (residency `-> home` edges, `counted`, not `source_stale`) and G6 (Bermuda
  move into a door entry area, `bermuda_arrival_into`). Empty pairs = G5 inert. This house: `jaya|ezinne` (Q2).

### 6.3 Candidate, waiter, own-evidence confirmation

At the crossing a candidate is anonymous everywhere (the original "Someone arrived" from the anonymous branch, bus
`person_id` None, no bus candidate key, no register, no sighting, no D10.5 identity). The slug lives only in the
waiter. After the INSERT returns its row id, ONE waiter per slug (`_arrival_waiters`, cap
`EGRESS_ARRIVAL_MAX_PENDING` 8, a newer candidate for the slug supersedes the older as `arrival_superseded`) waits
event-driven on G1 / G6 callbacks plus a `EGRESS_ARRIVAL_CONFIRM_POLL_S` (5 s) sweep for leg c, until
`crossing_ts + EGRESS_ARRIVAL_CONFIRM_WINDOW_S` (900 s). Not persisted: a restart leaves rows NULL and counts
`arrival_dropped_teardown`.

**Own confirming edge** = the first edge of the SLUG'S OWN devices strictly after `crossing_ts`:
(a) G1 resident edge for `person.<slug>` -> `home`, `counted`, not `source_stale`, not in the boot window;
(b) G6 Bermuda/IRK move of that person into a URA room with `ts > crossing_ts`, slug mapped through
`person_ids.tracked_person_entity_id`; (c) a GPS fix of that person after the crossing inside the home zone AND an
earlier fix farther than `EGRESS_ARRIVAL_CONFIRM_GPS_KM` (0.5).

**Pair rule (operator 2026-11-14).** Another person's crossing in (`crossing_ts`, edge] does NOT abstain. Two
residents arriving together are each named, each by their own face and their own edge. The candidate abstains
(`arrival_confirm_ambiguous`, reason recorded) only when the evidence is conflicted:
(i) another crossing in (`crossing_ts`, edge] claims the SAME slug (candidate or attached);
(ii) G5: the slug's confusable partner made a non-face arrival edge in [t_E − 120 s, edge];
(iii) the edge is stale-source (`stale_source_arrival`) — no confirmation, keep waiting.
No name is ever inherited: a partner's edge never confirms the slug, and a person with no face leg on any crossing
in the group stays "1 more" in the count follow-up.

**Confirmed confidence.** `EGRESS_ARRIVAL_CONFIRMED_CONFIDENCE` = 0.75 (one face leg + one independent own-device
edge for the same person; precedent: perimeter treats a below-floor face plus an independent non-face signal for the
same person as clearing its bar, `perimeter_alert.py:5256-5261`). It is fixed at 0.75 regardless of the face tier, so
it equals the notification bar and never reaches the security bar (INV-SECURITY-BAR). Q1 asks the operator to confirm.

On confirmation, one tracked task in `_confirm_tasks`, fresh-reading `switch.ura_name_people_at_doors` first (off =
count `arrival_confirm_disabled_skip`, write nothing): (1) `backfill_entry_exit_person_id(row_id, slug, 0.75)`, retry
until expiry if no row changed; (2) replace the ring's `CrossingRecord` with `identity_role="arrival_confirmed"`,
`person_id=slug`, `provenance="face+<leg>"`, `identity_confidence=0.75`, `nameable={slug: 0.75}`; (3) fire
`SIGNAL_EGRESS_ENTRY_CONFIRMED` {person_id, egress_camera, source_ref, crossing_ts, confirmed_at, identity_confidence,
identity_provenance, confirmed_by, confirm_lag_s}; (4) `ArrivalNotifier.notify_arrival_followup(source_ref,
kind="name", names=(slug,))`; (5) never a census register (the person enters F2 through the phone that confirmed them).

### 6.4 The crossing's nameable map (the H2 fix)

`CrossingRecord` gains additive defaulted fields `identity_role: str | None`, `nameable: Mapping[str, float]`
(frozen mapping), `identity_pair_conflict: str | None`. `nameable` is written only by the owner: at resolution
`{slug: identity_confidence}` for an `attached` slug whose confidence ≥ the notification bar and with no pair
conflict; at confirmation as in §6.3. A candidate's slug is never in it before its own edge.

### 6.5 Attached entries of a confusable-pair member (H4 forward window, M1)

If the attached slug has a configured partner, the original notify at t_E + 45 s is sent ANONYMOUS ("Someone
arrived": send now, name as a follow-up, per `feedback_alert_latency_over_precision`) and the name follows at
t_E + `EGRESS_PAIR_GUARD_WINDOW_S` through `notify_arrival_followup(kind="name")` only if no partner edge landed in
[t_E − 120 s, t_E + 120 s]. Bus `person_id`, DB row and census are unchanged (policy in the consumer). On a conflict
the record gets `identity_pair_conflict=<partner>`, `nameable` stays empty, and the bus carries the same key, which
the security-class readers treat as not qualifying: perimeter `_note_egress_identity` skips the entry
(`perimeter_alert.py:5156`), and the scoped egress mute (separate card) must apply the same rule.

### 6.6 One naming path per crossing (H2, H3)

`domain_coordinators/arrival_notify.py`, class `ArrivalNotifier` (class `notification`, created by the coordinator
manager, reads F3 through `get_last_crossing` / `get_crossings_since`; holds no F3 state of its own beyond its send
ledger):

- `notify_arrival(record)`: the moved `_arrival_departure_notify` body, byte-identical text and severity for the
  switch-off path; names render through `person_ids.display_of(slug)` (replacing `.title()` at `:2672`; display text
  equals today's `.title()` for the four residents, e.g. "Oji Udezue", L2).
- `notify_arrival_followup(source_ref, *, kind, names=(), guests=0, requester) -> bool`: the only place an arrival
  message is amended. Looks up the crossing by `source_ref` via `get_crossings_since`. Every name in `names` is kept
  only if `record.nameable[slug] >= CONSUMER_CLASS_MIN_CONFIDENCE["notification"]`; any other name is dropped and
  counted `followup_name_refused` (a crossing-vision face entity or a perimeter face leg cannot name a candidate).
  `kind="name"` with no surviving name returns False; `kind="count"` sends the surviving names plus "N not
  recognised". Severity LOW, `quiet=True`, fresh read of the name switch, at most `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING`
  (2) per `source_ref` in a RAM ledger (TTL 3600 s). Text "That was Oji Udezue" / "That was Oji Udezue, and 2 more not
  recognised".
- Callers: this card (§6.3, §6.5), crossing vision P2-D9 (count), step 8 (count), perimeter D10.5 on door cameras.

**Perimeter D10.5 rerouted (H3).** When the perimeter edge's camera is a door camera (resolved by registry
`device_id` against NEW `EgressDirectionTracker.door_camera_device_ids()`, never by stem or name), `_known_identity_for`
skips its face-leg and synthetic branches (`:5231-5261`) and takes identity only from the F3 crossing (bus cache,
which carries `person_id` only when attached), and `_followup_check` / `_async_send_identity_followup` hand the name
to `notify_arrival_followup(kind="name", requester="perimeter")` instead of sending their own "that was". Non-door
perimeter cameras (yard, driveway) are unchanged. Effect: one "that was X" per door crossing, validated against
`nameable`; a not-home Jaya face on the doorbell can no longer be named by perimeter before her phone confirms.

### 6.7 Departures, sighting producer, D2 egress branch

- `departure_attached`: labelled exit row + sighting + the existing "X left" + evict. No `SIGNAL_PERSON_DEPARTING`
  (grep 0, none added). Step 8 reads departures from G1 edges or `get_crossings_since`, never raw `person.*` (audit §6).
- Sighting producer (M6): NEW source (c') subscribed in `person_sighting.py` to `SIGNAL_EGRESS_ENTRY_CONFIRMED`,
  unsubscribed on teardown; emits through `_emit` with `identity_role="arrival_confirmed"` (the role becomes a
  parameter instead of the `"attached"` literal at `:491`), `ts = crossing_ts` (when the person was at the door) and
  additive `confirmed_at`. The 60 s `(slug, camera)` debounce applies; there is no earlier sighting for a candidate
  (INV-PROVISIONAL), so a confirmed emission is debounced only by an emission inside 60 s of `crossing_ts`.
- D2 egress branch: for an `egress_entry` sighting with `identity_role == "arrival_confirmed"` and
  `FACE_ARRIVAL_EGRESS_ENABLED`, `_derive_face_arrival` dispatches through `dispatch_person_arriving(hass,
  PersonArrivingPayload(source="camera_egress", ts=crossing_ts, ...))`; it skips raw `home` and
  `arrival_already_dispatched`. Built only if D5 survives its fire check.

### 6.8 HVAC (D5, conditional on the M3 fire check)

M3: the dispatch fires only for a GPS-led confirmation whose raw `person.*` is still not `home` at confirm time, and
lands 260-810 s after the person came in. D0 (g) counts that case. If it is 0 over the window, D5 is parked with the
revival trigger "D0 (g) > 0 per week" pending the operator's yes (Q5); otherwise D5 builds: `camera_egress` in
`DEFAULT_PRE_ARRIVAL_SOURCES` and the literal at `hvac.py:881`, the selector (label "Camera at a door (confirmed
arrival)"), a one-shot options migration modelled on `_migrate_hvac_zone_entry_dwell_to_zero` (`__init__.py:749`)
that appends when the stored list holds `camera_face` (live: `['geofence','ble','camera_face']`), sentinel
`pre_arrival_sources_camera_egress_migration_done`, and a stated check that the write does not reload the CM
(`OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7553`). HVAC logic unchanged.

### 6.9 Seams and residuals other plans must hear about

- Scoped egress mute (`PLANNING_perimeter_egress_mute_scoped.md` :62-65) expects step 7 to cut resident walk-out
  alerts. It will not: exit + home was already `attached`, and candidates stay anonymous at t_E + 45 s. The mute must
  also treat `identity_pair_conflict` as not qualifying. The arc-map row is the orchestrator's edit (M8).
- EXTERIOR-GUEST-EGRESS-1 (manual §6) is not triggered: yield is 4 of 10, not near zero.
- Detector misses (2 of the 10 TRUE had no URA crossing row) are an egress-detection residual, not identity; the
  orchestrator runs the adjacency sweep and cards it.
- Protect face names have no HA path (manual §2.3); this plan does not consume them (L5, Q6).

## 7. Producer and consumer checks

| Value | Producer (arithmetic, health) | Consumers (class, file:line) |
|---|---|---|
| face tier | `egress_identity_tier_labelled` `:127`; live: 10 of 10 face outcomes are 0.6 except one synthetic 0.9 (§5.2); healthy | G1 (gate); bus `identity_confidence` (security readers compare to 0.9) |
| own confirming edge | G1 residency edges (`counted`, stale, boot flags; `residency.py:109`), G6 Bermuda moves, GPS fixes; Jaya has no GPS tracker (audit :124) | waiter only |
| confirmed name | §6.3; fire check: projected 4 per 14 days (fixture), 0 in the 11 h live window | DB backfill, `CrossingRecord`, `SIGNAL_EGRESS_ENTRY_CONFIRMED` → Entered Today / Last Person Entry (display, `sensor.py:4960`, `:5114` pattern), sighting (c') (F4), `ArrivalNotifier` (notification), D2 (F5, conditional) |
| `identity_pair_conflict` | §6.5 | `ArrivalNotifier` (refuses), perimeter `_note_egress_identity` (skip), scoped mute (skip) |
| `nameable` | §6.4 | `ArrivalNotifier` only |
| outcome labels | `_log_egress_outcome` | attach counter `sensor.py:3993` (counts `EGRESS_OUTCOMES_ATTACHED`), D0, trip-wire |

Forward trace: a confirmed name reaches notification (follow-up), display (entry sensors), F4 (sighting), F5
(conditional), and step 8 actions through those channels. Nothing reaches access or house_state.

## 8. Emission and decision sites (a hypothesis; reviewers re-grep)

Veto `transit_validator.py:2036-2050`; every `_ret` in `_resolve_egress_face_identity_ex` (`:1497-2103`); bus fire
`:2215`; `_record_crossing` `:2247` and the confirmation replace; notify call `:2278` (moved); census `:2306-2332`;
INSERT `:2348`; teardown (waiters, `_confirm_tasks`, G1/G6 unsubscribes); `sensor.py:3993` and the four
`_handle_egress_event` readers (`:4828`, `:4973`, `:5059`, `:5172`); `person_sighting.py:449-491`; `presence.py:5825`
(D2) and the three existing raw F5 sends (`presence.py:5678, 5937`, `person_coordinator.py:1172`, migrated by G4);
perimeter `:5156`, `:5178-5262`, `:5519-5589`; crossing-vision P2-D9 caller (seam, not this branch); step 8 callers
(seam); `hvac_const.py:350`, `hvac.py:881`, `config_flow.py:8192`, `__init__.py` migration (D5 only).

## 9. Deliverables (one branch, in order, Tier 3)

**D0 probe (read-only, `ssh ha "python3 -"`).** Report, committed to this plan's §5 before build: (a) would-be
candidates per week by guard verdict; (b) confirm lag by leg on all true cases (sizes the 900 s window); (c) pair
matrix: named face on a not-home slug with another resident's non-face edge within ±120 s, per pair; (d) wrong-person
confirmations per leg on replay; (e) G3 fix-age buckets on true arrivals; (f) yield: projected confirmed names per
week under the full rev 2 rule, with each true case's removing guard or clause (§5.1 table, regenerated from the log);
(g) M3 fire check: GPS-led confirmations with raw `person.*` not `home` at confirm time; (h) live check that D8a is
still writing.
- **Verify:** §5.3 gates computed from (d) and (f); (g) decides D5.
- **Discriminates:** a rule bug that abstains on any crossing shows 11-08 17:34 removed by "other crossing"; the
  correct rule names it.
- **Test:** none (read-only). **Live:** none.

**D0b seams (only those ship 3 has not merged).** G1 `subscribe_resident_edges`, G2 `get_crossings_since`, G4
`dispatch_person_arriving` (and migrate the three raw sends), G6 `location_moves_since`, NEW
`door_camera_device_ids()`.
- **Verify:** the three raw `SIGNAL_PERSON_ARRIVING` sends are gone; payloads equal before and after; presence's own
  geofence `_run_inference("geofence_leave")` trigger is not routed through G1 (contract review D6).
- **Test:** `test_layer_seams.py::test_dispatch_person_arriving_payload_equal`, `::test_resident_edges_callback_counted_only`,
  `::test_geofence_leave_trigger_unchanged`, `::test_door_camera_device_ids_registry_only` (an entity whose name
  matches a door stem but whose device differs is excluded).
- **Live:** L-0 `SIGNAL_PERSON_ARRIVING` geofence arrivals still reach HVAC (`hvac` pre-arrival row on the next
  arrival).

**D1 rule, guards, roster, record fields, outcome labels.**
- **Verify:** entry, one 0.6 face leg, `not_home`, no map, no GPS → `arrival_candidate`, bus `person_id` None, no
  bus candidate key, "Someone arrived", not in the union (today: `vetoed`). Same crossing with Ezinne's G1 edge at
  −9 s and pair `jaya|ezinne` → `vetoed_pair_confusable` (without G5: candidate, so it discriminates). Synthetic-only
  → G1; fix 3 h old at 9,000 km → G3; path 0 on a mapped door → G2. `ojini` face → `vetoed_untracked`, no register
  (today: attached + register). Exit + zone → `vetoed` AND evict. Exit + home → `departure_attached`, evict.
- **Test:** `test_egress_direction_aware.py` (the D8b list kept by name) plus `::test_g1_single_medium_leg_forms_candidate`,
  `::test_g2_skipped_passes_without_tightening`, `::test_g5_partner_arrival_vetoes_candidate`,
  `::test_g5_empty_pairs_inert`, `::test_untracked_face_vetoed_no_register`, `::test_exit_zone_vetoed_still_evicts`,
  `::test_no_candidate_key_on_bus`, `::test_noop_golden_replay` (INV-NOOP matrix incl. untracked).
- **Live:** L-a the first `arrival_candidate` outcome row shows a NULL DB row and an anonymous notification row.

**D2 waiter, own-evidence confirmation, pair rule, signal, displays, trip-wire.**
- **Verify:** own G1 edge at +4 min names the row, Entered Today shows the name, one quiet follow-up. Two candidates
  (Oji, Jaya) 60 s apart, each own edge at +13 min → both named (rev 1: both abstain). Jaya candidate + Ezinne
  anonymous crossing + Jaya edge → named. Jaya candidate + a later crossing attached `jaya` → ambiguous. Jaya
  candidate + Ezinne's edge only → stays anonymous to expiry (no inherited name). Bermuda read and GPS fix at
  t_E − 20 s do not confirm (an abs-window bug would). Stale-source blip confirms nothing. Edge at +901 s →
  `arrival_unconfirmed`.
- **Test:** the D8b confirmation list (`::test_confirm_waits_for_insert_row_id`,
  `::test_deferred_insert_then_ble_names_row_before_followup`, ...) plus `::test_pair_both_named_own_edges`,
  `::test_anonymous_intervening_crossing_does_not_abstain`, `::test_same_slug_second_claim_abstains`,
  `::test_partner_edge_never_confirms`, `::test_partner_edge_before_confirm_abstains`,
  `::test_confirmed_confidence_below_security_bar`, `::test_fixture_yield_meets_floor` (replays the hand-built
  10-case fixture `quality/tests/fixtures/egress_true_arrivals_2026_11_13.json`, asserts ≥
  `EGRESS_ARRIVAL_YIELD_FLOOR_FIXTURE` named and 0 wrong names on the 41-cluster fixture),
  `::test_zero_fire_tripwire`.
- **Trip-wire:** AnomalyDetector → NM when `arrival_candidate` > 0 and `arrival_confirmed` = 0 over
  `EGRESS_ARRIVAL_ZERO_FIRE_DAYS` (14).
- **Live:** L-b within 7 days, a confirmed row (backfilled `person_id`, outcome `arrival_confirmed`) or the
  `arrival_unconfirmed` reason for each candidate; compare the count to §5.3 (b).

**D3 ArrivalNotifier, nameable validation, attached pair deferral, perimeter reroute.**
- **Verify:** name follow-up + crossing-vision count follow-up on one crossing → exactly 2 quiet sends; a third → False.
  A count follow-up passing `names=("jaya",)` for an unconfirmed candidate renders "2 more not recognised" with no
  name. Attached Jaya with Ezinne's edge at +80 s → anonymous original, no name follow-up, `identity_pair_conflict`
  on the bus, perimeter cache skips it. Not-home Jaya face ≥ 0.9 on the doorbell during a perimeter edge → no
  perimeter "that was". Switch off → text byte-identical to develop; `display_of` text equals legacy `.title()` for
  the four residents.
- **Test:** `test_arrival_notify.py::test_cap_two_per_crossing`, `::test_name_requires_switch_and_threshold`,
  `::test_count_followup_refuses_candidate`, `::test_followup_refuses_unconfirmed_name_from_any_requester`,
  `::test_attached_pair_member_named_after_window`, `::test_attached_pair_conflict_stays_anonymous`,
  `::test_display_of_matches_legacy_title`, `::test_no_second_arrival_naming_site` (AST: any `async_notify` whose
  title or text names a person for a door crossing exists only in `arrival_notify.py`; perimeter door-camera
  follow-ups counted as calls into it, which is how step 8's `test_r7_and_perimeter_followup_same_crossing` must
  count them); `test_perimeter_alert.py::test_door_camera_identity_only_from_f3`,
  `::test_non_door_camera_face_legs_unchanged`, `::test_pair_conflict_not_cached`.
- **Live (M5, discriminating):** L-c the first follow-up appears in `notification_log` with severity LOW and
  `acknowledged = 1`; for a digest-pref recipient its bucket is `digest_queued` and it arrives in the next 08:00 or
  18:00 digest; for an immediate-pref recipient it is sent on the channels whose threshold admits LOW. A follow-up
  that never writes a row (or writes it unacked) is a failure, not latency.

**D4 sighting (c') and D2 egress branch.**
- **Verify:** a confirmed candidate yields one sighting with `identity_role="arrival_confirmed"`, `ts = crossing_ts`;
  a candidate never yields one before confirmation. D2 dispatches through `dispatch_person_arriving` only for
  GPS-led confirmations with raw not-home; tracker-confirmed → skip `home`.
- **Test:** `test_person_sighting.py::test_confirmed_egress_source_role`, `::test_candidate_emits_no_sighting`,
  `::test_confirmed_sighting_teardown_unsubscribes`; `test_face_arrival_rule.py::test_confirmed_egress_dispatches_camera_egress`,
  `::test_tracker_confirmed_skips_home`.
- **Live:** L-d the first confirmed arrival shows a sighting row with role `arrival_confirmed`.

**D5 HVAC `camera_egress` (conditional, §6.8).** Builds only if D0 (g) > 0, else parked with the operator's yes.
- **Verify:** GPS-confirmed candidate → HVAC `pre_arrival` row, not skipped by `pre_arrival_sources`; migration
  appends once and respects an operator who removed `camera_face`; no CM reload.
- **Test:** `test_hvac_camera_egress.py` (five named in the sighting plan) + `::test_migration_no_reload`.
- **Live:** L-e CM `pre_arrival_sources` contains `camera_egress`, sentinel set.

**D6 docs, same commit.** Manual §4.3 (veto direction-aware, `EgressDirectionTracker`), §4.6 / §5.5 (`person_id`
meaning, candidates, own-evidence naming, pair rule, one naming path); presence state of play §1 (`camera_egress`,
`ArrivalNotifier`); HVAC state of play §2 (only if D5 builds); sighting plan §2B pointer; contract allowlist rows (N1,
P2 removed; R3 GPS row added).

**Mutation drills (framing C, each RED then restored):** M20-M22, M21b, M24, M27, M28, M28b, M29, M33-M35, M38-M41
from the sighting plan, plus: M56 drop G5 → `::test_g5_partner_arrival_vetoes_candidate`; M57 remove the amend cap →
`::test_cap_two_per_crossing`; M58 skip the switch read → `::test_name_requires_switch_and_threshold`; M59 skip the
`nameable` check → `::test_count_followup_refuses_candidate`; M60 let a partner edge confirm →
`::test_partner_edge_never_confirms`; M61 restore "any crossing abstains" → `::test_pair_both_named_own_edges`; M62
perimeter door camera reads face legs → `::test_door_camera_identity_only_from_f3`; M63 drop the exit-zone evict →
`::test_exit_zone_vetoed_still_evicts`; M64 confirmed confidence = face tier → `::test_confirmed_confidence_below_security_bar`.

## 10. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `EGRESS_IDENTITY_DIRECTION_AWARE` | True at ship if both §5.3 gates pass | 1 | Master; False = INV-NOOP. Live kill for names = `switch.ura_name_people_at_doors` |
| `FACE_ARRIVAL_EGRESS_ENABLED` | True with the master if D5 builds, else False | 1 | `camera_egress` dispatch; False = names and labels only |
| `EGRESS_ARRIVAL_CANDIDATE_MIN_TIER` | 0.6 (`CONFIDENCE_MEDIUM`) | 1 | G1; review-only (raising it to 0.75 restores rev 1's ~0 yield) |
| `EGRESS_ARRIVAL_CONFIRMED_CONFIDENCE` | 0.75 | 1 | Must stay ≥ notification bar and < security bar; review-only |
| `EGRESS_ARRIVAL_PATH_MIN` | 2 | 1 | 0 = G2 skipped |
| `EGRESS_ARRIVAL_MAX_SPEED_KMH` / `_GPS_MIN_AGE_S` / `_GPS_MAX_AGE_S` | 150 / 60 / 86400 | 1 | G3 physics bounds |
| `EGRESS_ARRIVAL_CONFIRM_WINDOW_S` | 900 (M4; 4 of 10 true lags are 641-810 s) | 1 | 0 = labels only, no names |
| `EGRESS_ARRIVAL_CONFIRM_POLL_S` / `_MAX_PENDING` | 5 / 8 | 1 | sweep cadence for leg c; waiter cap |
| `EGRESS_ARRIVAL_CONFIRM_GPS_KM` | 0.5 | 1 | 0 = GPS leg off |
| `CONF_EGRESS_CONFUSABLE_PAIRS` | empty | 2 (CM options, egress step, "Faces often confused") | per-house fact; empty = G5 off |
| `EGRESS_PAIR_GUARD_WINDOW_S` | 120 | 1 | 0 = G5 off and no attached-pair deferral |
| `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` | 2 | 1 | alert hygiene; 0 = no amends |
| `EGRESS_ARRIVAL_YIELD_FLOOR_FIXTURE` | 4 (of 10) | 1 | ship gate, measured §5.1; read by the replay test |
| `EGRESS_ARRIVAL_YIELD_FLOOR_PER_WEEK` | 1 | 1 | ship gate on ≥ 7 days of D8a log; half the fixture rate |
| `EGRESS_ARRIVAL_ZERO_FIRE_DAYS` | 14 | 1 | trip-wire window; 0 = trip-wire off |
| `EGRESS_PATH_BUFFER_S` / `EGRESS_PATH_HOP_DEFAULT_WINDOW_S` | 180 / 30 | 1 | path horizons (sighting plan §2B.4) |

## 11. Non-goals

Changing the resolved direction from the path score; any AWAY, ARRIVING or GUEST input (census deltas only lower the
union); naming two faces on one crossing; vision naming anyone; `SIGNAL_PERSON_DEPARTING`; access or security acting
on `camera_egress` or on an egress-confirmed identity; lowering the 0.9 security bar; Protect face names; automatic
pair learning (parked; revival when the weekly labeller shows a second confusable pair); a DB role column; departure
actions (step 8); fixing detector misses; raising notification severity (Q4 is the operator's).

## 12. Open operator questions (recommended defaults)

1. Naming basis: one 0.6 face leg + the person's own phone edge counts as 0.75 for notification (never security).
   Default yes; without it §5 yield is 0.
2. Confusable pairs: `jaya|ezinne` only. Default yes.
3. Master on at ship when both §5.3 gates pass. Default yes (operator 2026-11-14: "we don't need to be so conservative").
4. Delivery (M5): arrival notices are LOW and follow-ups LOW + quiet; for a digest-pref recipient both arrive in the
   next 08:00 / 18:00 digest (`database.py:4925-4928`). Is that the product, or should a named arrival be sent
   immediately? Default: keep LOW; the operator sets delivery per recipient.
5. D5 HVAC `camera_egress`: park if D0 (g) = 0. Default park, revival trigger "D0 (g) > 0 per week".
6. Protect face names stay out of scope (no HA path, manual §2.3); card a Protect-API face bridge? Default: card it
   with revival trigger "Protect names reachable from HA", not built here.
7. Untracked known faces (M7): stop naming and registering them at doors. Default yes (Ojini false 10/10).

## 13. Tier, reviews, dependency

Tier 3: threads a role through the egress state machine read by census, notify, displays, perimeter, sightings, D2,
HVAC; one missed site leaks a name. Plan reviews: review 1 done (completeness + G, FIX-PLAN, dispositioned §15);
review 2 (adversarial build-prediction) and a framing G re-check on this revision before build dispatch. Code
reviews: A local, B integration / restart / teardown, C per-site mutation (§9 list), D completeness on
INV-PROVISIONAL, INV-ONE-NAMING-PATH and INV-NO-AWAY-DELAY including pre-existing readers. Orchestrator re-grep and one
real mutation; operator checkpoint before deploy with both §5.3 gate results. Step 8: shipping this satisfies the
identity half of F-NOTIFY (census plan §3.2 rung 2) and provides `notify_arrival_followup`; no step-8 deliverable that
names a person may build against another amend path.

## 14. Plan completion tracking

Carried from the sighting plan: G2-G4, waiter, confirmation legs, D2 branch, attach labels, path subscriptions.
Changed in rev 2: G1 floor 0.75 → 0.6 with own-edge naming; abstain rule → pair rule; window 600 → 900; amend
function moved to `ArrivalNotifier` with `nameable` validation; perimeter D10.5 rerouted on door cameras; exit-zone
evict kept; untracked faces vetoed; D5 conditional. Not done here, tracked: automatic pair learning (parked);
`EGRESS-PATH-OVERRIDES-DIRECTION-1` (evidence only); Protect face bridge (Q6); detector misses (orchestrator to card);
the patio door with no egress camera (named residual).

## 15. Plan review 1 disposition

| Finding | Disposition in rev 2 |
|---|---|
| H1 yield | Fixed: §5 measured yield (4 of 10 newly named, 0 projected misnames), pair rule §6.3 (operator "Agreed"), G1 floor + confirmed confidence §6.2-§6.3, yield gate §5.3, D0 (f) |
| H2 count follow-up names a candidate | Fixed: `nameable` map §6.4, validation in `notify_arrival_followup` §6.6, INV-OWN-EVIDENCE, M59 |
| H3 perimeter D10.5 own naming path | Fixed: door cameras rerouted through the one path §6.6, INV-ONE-NAMING-PATH, M62; §8 corrected |
| H4 G5 inputs and forward window | Fixed: inputs from G1 / G6 seams (§3 row 6, D0b), forward window at confirmation and via attached deferral §6.5, INV-PAIR restated |
| M1 security ignores pair conflict | Fixed: §6.5, INV-SECURITY-BAR, perimeter cache skip; scoped mute told §6.9 |
| M2 AWAY invariant | Fixed: exit-zone evict kept, INV-NO-AWAY-DELAY, M63 |
| M3 D4 near-dead | Fixed: D0 (g) fire check, D5 conditional, Q5; (c') `ts` = crossing ts §6.7 |
| M4 window | Fixed: 900 s default |
| M5 delivery | Fixed: digest carries LOW verified, L-c discriminating, Q4 |
| M6 sighting producer | Fixed: §6.7, D4 tests |
| M7 Ojini | Fixed: tracked-roster test §6.1, Q7 |
| M8 scoped mute seam | Stated §6.9; arc-map edit owed by the orchestrator |
| L1 | Fixed: `hvac.py:881`, migration precedent, reload check (§6.8); "EC-pin write" wording dropped |
| L2 | Fixed: "Oji Udezue" text |
| L3 | Fixed: `departure_attached`; INV-PROVISIONAL scoped to arrivals |
| L4 | Fixed: no candidate key on the bus |
| L5 | Q6 (Protect) and parked pair learning with trigger; operator yes requested |
| L6 | Fixed: music (comfort, reads F4/F5 channels, unaffected) and security expected-arrival (access, INV-ACCESS) in §3 classes |
| L7 | Arc-map citation (`:1840-1854` → `:2036-2050`) owed by the orchestrator |
