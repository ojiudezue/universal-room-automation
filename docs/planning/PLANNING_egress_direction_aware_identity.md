# PLANNING: direction-aware egress identity (arc step 7)

Card: EGRESS-DIRECTION-AWARE-IDENTITY-1 (thread identity, batch person-sightings, parent FACE-ARRIVAL-REBUILD-1;
FACE-EGRESS-ARRIVAL-1 folded). Arc: identity / vision / census, step 7 of `ARC_identity_vision_census_map.md` §4.
Tier 3. Status: plan, not reviewed. Author ura-planner, 2026-11-14, develop @ fd893bbc.

This is the ONE build spec for Phase 2 of the person-sighting plan (§2B, D8b). It restates that design cleanly with
every rev-9/10/11 fix folded in and adds the pieces the arc map assigned to step 7: the pair-confusion guard and the
one arrival-notification amend function. `PLANNING_person_sighting_layer.md` §2B / D8b get a pointer to this file in
the same commit as its first review fix; where they differ, this file wins. Step 8 (`PLANNING_identity_actions_v6.md`)
depends on it.

Read first, completely, before this plan was written (stated per CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (D-HVAC touches
`pre_arrival_sources`). No §10 ledger claim is re-asserted. Contradictions found, code wins: none new; manual §4.3
still names `TransitValidator` as the egress owner (the class is `EgressDirectionTracker`, `transit_validator.py:963`;
`TransitValidator` is `:284`); fixed in the D5 docs commit.

## 1. Charter and goal served

Charter: `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Goals served, verbatim: "assist arrivals accuracy
and personalization"; "egress only names people who are already home... Who made this rule? ... It should do both";
"make it faster and faster until it can eventually be used in security applications too". Hard constraint: "I need
away to be fast acting." This plan names arrivals the face-only veto erases today (10 measured true cases, every home
edge 260-810 s after the crossing) and labels departures, without touching AWAY.

Drift check at dispatch: zero drift found. Risk reductions here (names withheld until a phone confirms; access needs
a second signal) do not change WHAT is delivered: the person is still named, minutes later, and the operator chose
this shape on 2026-11-12 ("the name is withheld from every consumer until the after-the-fact corroboration").

## 2. Institutional context verified

Greps run 2026-11-14 on develop: `def _arrival_departure_notify|_resolve_egress_face_identity_ex|EGRESS_IDENTITY_DIRECTION_AWARE|
CONSUMER_CLASS_MIN_CONFIDENCE|get_last_crossing|SIGNAL_EGRESS_ENTRY_CONFIRMED` across the integration; `not_home|
register_egress_face|evict_egress_face|log_entry_exit_event` in `transit_validator.py`; `^def ` in `arrival_edges.py`;
`PRE_ARRIVAL_SOURCES` in `hvac_const.py` and `config_flow.py`; `quiet` in `notification_manager.py`; attach-rate in
`sensor.py`.

| Piece | Verdict | Where |
|---|---|---|
| Face-only veto to replace | REUSED site | `transit_validator.py:2036-2050` (`_person_raw == "not_home"`, outcome `vetoed`) |
| Resolution channel | REUSED, extend | `EgressResolution` `transit_validator.py:91`; `_resolve_egress_face_identity_ex` `:1497`; one caller `:2192` |
| Pure tier helper | REUSED | `egress_identity_tier` `:121`, `egress_identity_tier_labelled` `:127` |
| Outcome log (D8a, live) | REUSED | `_log_egress_outcome` `:2576`; type `EGRESS_OUTCOME_EPISODE_TYPE` `const.py:3516` |
| Bus fire / crossing record | REUSED, additive keys | `:2215`; `_record_crossing(CrossingRecord)` `:2247`; `get_last_crossing` `:1044` |
| The one arrival/departure notify | REUSED, extend | `_arrival_departure_notify` `:2647`, call `:2278`; name rule reads `CONSUMER_CLASS_MIN_CONFIDENCE` `const.py:6512` |
| Census register / evict | REUSED, unchanged | `:2306-2332` (`if person_id` gate) |
| DB INSERT | REUSED, return the row id | `database.log_entry_exit_event` `database.py:4600` (returns None today), call `transit_validator.py:2348` |
| Row-id backfill | REUSED | `database.backfill_entry_exit_person_id` `database.py:4723` |
| Exit backfill displays (pattern) | REUSED | `SIGNAL_EGRESS_EXIT_BACKFILLED` `signals.py:39`; readers `sensor.py:4960`, `:5114` |
| Arrival edge helpers | REUSED | `arrival_edges.stale_source_arrival` `:72`, `nonface_arrival_source` `:269`, `bermuda_arrival_into` `:191`, `arrival_source_needs_corroboration` `:34` |
| Camera-derived source set | REUSED | `CAMERA_DERIVED_ARRIVAL_SOURCES` `const.py:3486` (already holds `camera_egress`) |
| D2 arrival site | REUSED, add egress branch | `PresenceCoordinator._derive_face_arrival` `presence.py:5825` (egress skipped `not_arrival_role` `:5842`), `_last_home_edge_ts` `:1857` |
| Quiet follow-up send | REUSED | `NotificationManager.async_notify(..., quiet=)` `notification_manager.py:1531-1544` |
| Path map + scorer | REUSED | D7 `interior_paths.score_path`, loader on the tracker (manual §4.5) |
| HVAC source filter | REUSED, default + migration | `DEFAULT_PRE_ARRIVAL_SOURCES` `hvac_const.py:350`; selector `config_flow.py:8192`; filter `hvac.py:1431-1437`, handler `:7222` |
| Attach-rate counter | REUSED, relabel | `sensor.py:3993` (`out == "attached"`) |
| `freshest_gps_fix` | NEW pure helper in `arrival_edges` | no GPS-fix picker exists (grep `gps_fix` = 0 outside plans) |
| `SIGNAL_EGRESS_ENTRY_CONFIRMED` | NEW signal | grep 0 hits |
| `EGRESS_OUTCOMES_ATTACHED` | NEW frozenset | grep 0 hits |
| Pair guard G5, `CONF_EGRESS_CONFUSABLE_PAIRS` | NEW | grep `confusable` 0 hits in code; the §2B.3 parked guard's trigger fired (`AUDIT_egress_history_labels_2026_11_13.md`) |
| Amend function `notify_arrival_followup` | NEW public method on the tracker | M3 of the arc map assigns it here; no follow-up branch exists |

Prior plans read: `PLANNING_person_sighting_layer.md` §0A, §2A, §2B (all), §2, D8, drills, live table;
`PLANNING_crossing_vision.md` §1-§8 (P2-D9 consumes the amend function); `PLANNING_census_deconfliction.md` §3.2
(F-NOTIFY bar names this card); `PLANNING_person_awareness_read_api.md` (RA3, RA5 shipped v5.108.21).
Analysis: `AUDIT_egress_history_labels_2026_11_13.md` (10 true cases; misrecognition 1/30 to 3/30, outer 6/30;
Jaya/Ezinne confusion; Ojini 10/10 false). Memory: `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`,
`reference_egress_face_coverage_7pct_not_a_ceiling` (amendments), `project_hyper_personalization_person_profile`.
Config-first: no knob makes the veto direction-aware; `switch.ura_name_people_at_doors` only turns naming off.

## 3. Facts and consumer classes

Produces F3 (identity role on a crossing; confirmed name later) and F5 `camera_egress` (confirmed, GPS-led arrivals
only, through the one D2 site). Consumes F1 (raw `person.*` edges, BLE location, GPS fixes) and F3. Never F2: a
candidate or a confirmation never registers in the census union (the person enters F2 through the phone that
confirmed them). Readers by class (`CONSUMER_CLASS_MIN_CONFIDENCE`): notification naming at >= 0.75 and only after
confirmation; display (four entry/exit sensors, sightings, attach counters) none; comfort (HVAC pre-arrival via
`camera_egress`) through the existing per-person zone map; access and security: never on this alone (D3 gate,
`face_input_corroborated`); house state: never (no AWAY, ARRIVING or GUEST input changes).

## 4. Measure first (P7-0, read-only, before build; one `ssh ha "python3 -"` probe)

Reads `memory_episodes` `egress_identity_outcome` rows (D8a, live since its ship), recorder `person.*`, Bermuda area
and GPS tracker history, and the labelled fixture. Reports:
(a) would-be candidates per week by guard verdict (G1-G5) and `vetoed_arrival_unverified` reasons;
(b) confirm lag by leg (tracker / BLE / GPS) on the 10 true cases plus any new ones; sizes `EGRESS_ARRIVAL_CONFIRM_WINDOW_S`
(600 s default; the measured max 810 s says 900 may be needed);
(c) the pair-confusion matrix: for every named face on a not-home slug, did another resident make a non-face arrival
edge within +-120 s (the 11-11 08:25 shape), per pair;
(d) wrong-person confirmations a replay of legs (a)-(c) would have produced, per leg (the rev-10 H1 class);
(e) G3 fix-age buckets on true arrivals (how often a true arrival fails G3 and stays anonymous).
**Go/no-go:** the operator states the misrecognition ceiling (§11 Q1). Default recommended: go when (d) is 0 on the
replay and the resolver-level upper Wilson bound is <= 0.30, because a wrong name now needs a wrong-person
confirmation, not just a wrong face. A non-zero (d) blocks the leg that produced it, not the plan.

## 5. Design

### 5.1 The rule (face-only single-slug path; BLE branches unchanged; switch `EGRESS_IDENTITY_DIRECTION_AWARE`)

| Direction | Raw `person.<slug>` | Outcome (switch on) | Bus / DB `person_id` at the crossing |
|---|---|---|---|
| entry | `home` | `attached` | slug |
| entry | `not_home` or a named zone | `arrival_candidate` if G1-G5 allow, else `vetoed_arrival_unverified` (failed guard named) | None; slug only in bus `candidate_person_id` and the waiter |
| entry / exit | missing, unknown, unavailable | `attached` (fail-open, as today) | slug |
| exit | `home` | `departure_candidate` (counted attached) | slug; evict as today |
| exit | `not_home` or a named zone | `vetoed`, no evict | None |
| ambiguous | any | unchanged | None |

Switch off: outcome labels, DB row, notification text, census calls and bus dict byte-identical to develop; keys
`identity_role`, `candidate_person_id`, `identity_guards`, `path_score`, `identity_pair_conflict` absent; no path
subscription, no waiter. Declared switch-on deltas: entry + zone becomes a candidate (no register); exit + zone becomes
vetoed (no evict; the slug can linger in the union up to `EGRESS_FACE_UNION_TTL_S`, as `not_home` does today).

### 5.2 Guards (evaluated at the resolution instant, `t_E + ENTRY_WINDOW_SECONDS` = 45 s; timing unchanged)

- **G1 face confidence:** `identity_confidence >= EGRESS_ARRIVAL_CANDIDATE_MIN_CONFIDENCE` (0.75) and not synthetic-only
  (at 0.9 `_last_identity_synthetic_corroborated`; below 0.9 any `FaceLeg.synthetic` leg).
- **G2 path:** `score_path(...) >= EGRESS_ARRIVAL_PATH_MIN` (2). 0 = not evaluated (`skipped`). A door with no map is
  `skipped`. A skipped G2 requires G1 at 0.9 non-synthetic.
- **G3 implied speed:** freshest GPS `device_tracker` of the person (`source_type == "gps"`, by that tracker's own
  `last_updated`), distance to `zone.home` minus accuracy and radius over the fix age (floored at 60 s); FAIL above
  `EGRESS_ARRIVAL_MAX_SPEED_KMH` (150); no fix or older than `EGRESS_ARRIVAL_GPS_MAX_AGE_S` (86400) = `skipped`.
- **G4 single name:** the existing abstain / disagree rules returned one slug (unchanged).
- **G5 pair guard (NEW, the fired §2B.3 trigger).** If the slug has a confusable partner in
  `CONF_EGRESS_CONFUSABLE_PAIRS` and that partner has a non-face arrival edge (`arrival_edges.nonface_arrival_source`:
  live `person.*` -> home edge or a Bermuda move into an entry area) within +-`EGRESS_PAIR_GUARD_WINDOW_S` (120) of
  `t_E`, the outcome is `vetoed_pair_confusable`: no candidate, no waiter, partner named in `identity_guards`. On an
  `attached` entry (slug already home) the bus gains `identity_pair_conflict: <partner>` and the notify consumer
  stays anonymous; bus `person_id`, DB row and census are unchanged (policy in the consumer). Empty pairs = G5 inert.
  This house: `jaya|ezinne` (operator to confirm, §11 Q2). Ojini is not tracked, so it can never be a candidate
  (no confirmation leg) and needs no pair.

### 5.3 Provisional candidate, waiter and confirmation

At the crossing a candidate gets "Someone arrived" from the existing anonymous branch (bus `person_id` None), no
union register, no sighting, no perimeter identity, no `_egress_identity_last_attach` write. After the INSERT returns
its row id, ONE waiter per slug (`_arrival_waiters`) polls every `EGRESS_ARRIVAL_CONFIRM_POLL_S` (5) until
`crossing_ts + EGRESS_ARRIVAL_CONFIRM_WINDOW_S`. Cap `EGRESS_ARRIVAL_MAX_PENDING` (8); a newer candidate for the slug
supersedes the older (`arrival_superseded`); not persisted (a restart leaves rows NULL, counted at teardown as
`arrival_dropped_teardown`). Confirmation = the first edge strictly after `crossing_ts`:
(a) tracker `person.<slug>` -> `home`, `stale_source_arrival` False; (b) BLE: PersonCoordinator `method == bermuda`,
a URA room, `last_changed > crossing_ts`, slug mapped through `person_ids.tracked_person_entity_id`; (c) GPS fix after
the crossing inside the home zone AND an earlier fix farther than `EGRESS_ARRIVAL_CONFIRM_GPS_KM` (0.5).
Abstain (`arrival_confirm_ambiguous`): any other egress crossing resolved in (`crossing_ts`, edge], a later candidate
for the slug, or (G5 again) the partner's non-face arrival edge in that interval.
On confirmation, one tracked task in `_confirm_tasks`, fresh-reading `switch.ura_name_people_at_doors` first (off =
count `arrival_confirm_disabled_skip`, write nothing): (1) `backfill_entry_exit_person_id(row_id, slug, conf)`, retry
until expiry if no row changed; (2) `SIGNAL_EGRESS_ENTRY_CONFIRMED` {person_id, egress_camera, timestamp, identity_confidence,
identity_provenance face, confirmed_by, confirm_lag_s}; readers: Persons Entered Today and Last Person Entry re-read
(mirror of the exit-backfill readers), sighting source (c'); (3) `notify_arrival_followup(crossing, kind="name")`
(5.4); (4) never a census register.

### 5.4 The one amend function (shared with step 8 and crossing-vision P2-D9)

`EgressDirectionTracker.notify_arrival_followup(crossing_ref, *, kind, names=(), guests=0) -> bool`. `crossing_ref` =
the `CrossingRecord.source_ref` (`egress:<camera>:<iso>`). It is the follow-up branch of the one notify site and the
only place an arrival message is amended. Rules: severity LOW, `quiet=True`; fresh-reads the name switch for
`kind="name"`; a name renders only through `person_ids.display_of(slug)` (replacing the inline `.title()` at `:2672`
in the same commit, display byte-identical for the four residents) and only at >= the notification class threshold;
at most `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` (2) follow-ups per crossing in a RAM ledger (TTL 3600 s), so original +
two amends is the ceiling; `kind` in {`name`, `count`}; text "That was Oji" / "That was Oji, and 2 more not
recognised" (count form owned by step 8); returns whether it sent. Crossing vision calls it for R-7; nothing else
calls `async_notify` for an arrival. Pair conflict or a vetoed role means `kind="name"` is refused.

### 5.5 Departures, D2 egress branch, HVAC

- `departure_candidate`: labelled exit row + sighting + the existing "X left" + evict. No `SIGNAL_PERSON_DEPARTING`
  (grep 0; none added). Step 8's DEPARTURE-ACTIONS-1 consumes the crossing record, not a new signal.
- D2: the one site dispatches `SIGNAL_PERSON_ARRIVING(source="camera_egress")` for an `egress_entry` sighting with
  `identity_role == "arrival_confirmed"` when `FACE_ARRIVAL_EGRESS_ENABLED`; rule 5 skips `home` (tracker-confirmed)
  and `arrival_already_dispatched` (a geofence or ble arrival after `crossing_ts`); only GPS-led confirmations
  dispatch. Access: `camera_egress` is camera-derived, so locks and security still need `face_input_corroborated`.
- HVAC (D-HVAC): `camera_egress` added to `DEFAULT_PRE_ARRIVAL_SOURCES`, the selector (label "Camera at a door
  (confirmed arrival)"), and a one-shot options migration (append when the stored list holds `camera_face`; sentinel
  `pre_arrival_sources_camera_egress_migration_done`; merged-view read, EC-pin write so no reload). HVAC logic and the
  filter are unchanged; the HVAC state of play §2 pre-arrival row updates in the same commit.
- Attach counter counts `out in EGRESS_OUTCOMES_ATTACHED` and adds `arrival_candidates_24h` / `_confirmed_24h` /
  `_unconfirmed_24h` / `pair_vetoed_24h`.

## 6. Falsifiable invariants (reviewer D breaks these, pre-existing code included)

- **INV-PROVISIONAL.** Before confirmation, no consumer receives a candidate's slug as identity: bus and DB
  `person_id`, notification name, four displays, census union, perimeter D10.5, `SIGNAL_PERSON_SIGHTING`,
  `SIGNAL_PERSON_ARRIVING`, `_egress_identity_last_attach`. Break it with any of those carrying the slug with no
  confirming edge timestamped after the crossing.
- **INV-CANDIDATE.** A candidate exists only if G1 passes, G3 does not fail, G5 does not fire, and G2 passes or is
  skipped with G1 at 0.9 non-synthetic.
- **INV-CENSUS-HOME.** `register_egress_face` is never called for a candidate's slug, at the crossing or confirmation.
- **INV-ACCESS (unchanged, re-proven).** No `camera_egress` arrival alone releases a lock, unlocks, adds an expected
  arrival or disarms. Falsifier includes a GPS-near-only confirmation.
- **INV-NOOP.** Switch off: §5.1 byte-identity; golden replay over entry x {home, not_home, zone, unknown} and exit x
  {home, not_home, zone}.
- **INV-AMEND-ONE.** Every arrival message after the original goes through `notify_arrival_followup`, at most 2 per
  crossing, quiet, LOW. Break it with a second `async_notify` call site for an arrival, or a third amend.
- **INV-AWAY-UNTOUCHED.** No input of `infer()` / `_run_inference`, the census trust view or the residency producer
  changes with the switch on vs off. Break it by any departure or candidate value read in `presence.py` inference.
- **INV-PAIR.** With a pair configured, a named not-home slug whose partner made a non-face arrival edge within the
  window never becomes a candidate and never gets a "That was" for that crossing.

## 7. Emission and decision sites (the plan's list is a hypothesis; reviewers re-grep)

Veto `:2036-2050`; resolver returns (every `_ret` in `_resolve_egress_face_identity_ex`); bus fire `:2215`; crossing
record `:2247`; notify `:2278` / `:2647`; census `:2306-2332`; INSERT `:2348`; teardown (waiters, `_confirm_tasks`);
`sensor.py:3993` and the four `_handle_egress_event` readers (`:4828`, `:4973`, `:5059`, `:5172`); `presence.py:5825`
(D2); `hvac_const.py:350`, `config_flow.py:8192`, `__init__.py` migration call; perimeter D10.5 reads bus
`person_id` only (no change, pinned); sighting producer source (c) reads `resolution.provenance` (no change).

## 8. Deliverables (one branch, D-ordered, Tier 3)

**D0 probe (P7-0, §4).** Verify: report committed with (a)-(e); the operator answers Q1/Q2 against it.
Live: none. Test: none (read-only).

**D1 rule, guards G1-G5, role channel, bus keys.** Verify: entry, face 0.75 non-synthetic, `not_home`, path 2, no
GPS -> bus `person_id` None, `candidate_person_id` set, "Someone arrived", not in the union (today: `vetoed`, no
candidate key; a leak would show the slug in `person_id`). Same crossing with Ezinne's tracker going home at -9 s and
pair `jaya|ezinne` -> `vetoed_pair_confusable` (without G5 it would be a candidate: discriminates). Face 0.6 -> G1;
fix 3 h old at 9,000 km -> G3; path 0 on a mapped door -> G2. Exit + home -> `departure_candidate`, evict, counted
attached. Tests: `test_egress_direction_aware.py` (the D8b list in the sighting plan, kept by name) plus
`::test_g5_partner_arrival_vetoes_candidate`, `::test_g5_attached_entry_notify_anonymous_bus_unchanged`,
`::test_g5_empty_pairs_inert`. Live: L-a first candidate shows `candidate_person_id` and a NULL row.

**D2 waiter, confirmation, `SIGNAL_EGRESS_ENTRY_CONFIRMED`, displays.** Verify: tracker home edge at +4 min names the
row, Entered Today shows the name, one quiet "That was X"; a Bermuda read at t_E - 20 s and a GPS fix at t_E - 20 s
each leave the candidate open (an abs-window bug confirms them); another crossing before the edge -> ambiguous;
stale-source iPad blip confirms nothing. Tests: the D8b confirmation list (`::test_confirm_waits_for_insert_row_id`,
`::test_deferred_insert_then_ble_names_row_before_followup`, `::test_intervening_crossing_abstains`, ...) plus
`::test_partner_edge_before_confirm_abstains`. Live: L-b a confirmed row within the window or an
`arrival_unconfirmed` outcome row.

**D3 amend function.** Verify: name follow-up and a crossing-vision count follow-up on one crossing give exactly 2
quiet sends; a third call returns False; switch off -> no name send; `display_of` text equals today's for the four
residents. Tests: `test_arrival_followup.py::test_cap_two_per_crossing`, `::test_name_requires_switch_and_threshold`,
`::test_display_of_matches_legacy_title`, `::test_no_second_arrival_notify_site` (AST: `async_notify` with an arrival
title only inside the tracker). Live: L-c the first "That was" message arrives quiet.

**D4 D2 egress branch + HVAC.** Verify: GPS-confirmed candidate with the egress flag -> HVAC `pre_arrival` row, not
skipped `pre_arrival_sources`; tracker-confirmed -> D2 skip `home`. Migration appends once, respects an operator who
removed `camera_face`. Tests: `test_face_arrival_rule.py::test_confirmed_egress_dispatches_camera_egress`,
`::test_tracker_confirmed_skips_home`; `test_hvac_camera_egress.py` (five named in the sighting plan). Live: L-d CM
`pre_arrival_sources` contains `camera_egress`, sentinel set.

**D5 docs, same commit.** Manual §4.3 (veto direction-aware, `EgressDirectionTracker`), §4.6 / §5.5 (`person_id`
meaning, provisional candidates, G5); presence state of play §1 (`camera_egress` source); HVAC state of play §2;
sighting plan §2B pointer. Live: n/a.

Mutation drills (framing C, each RED then restored): M20-M22, M21b, M24, M27 (rev-10 form), M28, M28b, M29, M33-M35,
M38-M41 from the sighting plan, plus M56 drop G5 -> `::test_g5_partner_arrival_vetoes_candidate`; M57 amend cap
removed -> `::test_cap_two_per_crossing`; M58 name follow-up skips the switch read -> `::test_name_requires_switch_and_threshold`.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `EGRESS_IDENTITY_DIRECTION_AWARE` | True at ship if Q1 go, else False | 1 | Master; False = INV-NOOP. Live kill = `switch.ura_name_people_at_doors` (names) |
| `FACE_ARRIVAL_EGRESS_ENABLED` | True with the master | 1 | `camera_egress` dispatch; False = labels and names only |
| `EGRESS_ARRIVAL_CANDIDATE_MIN_CONFIDENCE` | 0.75 | 1 | Equals notification class; review-only |
| `EGRESS_ARRIVAL_PATH_MIN` | 2 | 1 | 0 = G2 skipped (which tightens G1 to 0.9) |
| `EGRESS_ARRIVAL_MAX_SPEED_KMH` / `_GPS_MIN_AGE_S` / `_GPS_MAX_AGE_S` | 150 / 60 / 86400 | 1 | G3 physics bounds |
| `EGRESS_ARRIVAL_CONFIRM_WINDOW_S` / `_POLL_S` / `_MAX_PENDING` | 600 (D0 may set 900) / 5 / 8 | 1 | 0 window = labels only |
| `EGRESS_ARRIVAL_CONFIRM_GPS_KM` | 0.5 | 1 | 0 = GPS leg off |
| `CONF_EGRESS_CONFUSABLE_PAIRS` | empty | 2 (CM options, egress step, "Faces often confused") | Per-house fact; empty = G5 off |
| `EGRESS_PAIR_GUARD_WINDOW_S` | 120 | 1 | Reuses the face/non-face window size; 0 = G5 off |
| `ARRIVAL_FOLLOWUP_MAX_PER_CROSSING` | 2 | 1 | Alert hygiene; 0 = no amends |
| `EGRESS_PATH_BUFFER_S` / `EGRESS_PATH_HOP_DEFAULT_WINDOW_S` | 180 / 30 | 1 | Path horizons (sighting plan §2B.4) |

## 10. Non-goals

Changing the resolved direction from the path score; any census, AWAY, ARRIVING or GUEST input; vision naming anyone;
`SIGNAL_PERSON_DEPARTING`; access or security acting on `camera_egress` without the second signal; Protect face names
(no HA path); automatic pair learning (parked: revival when the weekly labeller shows a second confusable pair); a role
column in the DB; departure actions (step 8).

## 11. Open operator questions (recommended defaults)

1. Misrecognition ceiling for go. Default: replay wrong-person confirmations 0 and resolver upper bound <= 0.30.
2. Confusable pairs. Default `jaya|ezinne` only.
3. Master on at ship. Default yes (operator 2026-11-14: "we don't need to be so conservative"); the name switch is
   the live kill.
4. Confirm window 600 vs 900 s. Default: D0 (b) p95 + 60 s, capped 900.

## 12. Tier, reviews, dependency

Tier 3 (threads a role through the egress state machine read by census, notify, displays, perimeter, D2, HVAC; one
missed site leaks a name). Two plan reviews (completeness re-enumeration; adversarial build-prediction) plus framing
G; four code reviews (A local, B integration/restart/teardown, C per-site mutation, D completeness on INV-PROVISIONAL
and INV-AWAY-UNTOUCHED incl. pre-existing readers); orchestrator re-grep and one mutation; operator checkpoint before
deploy (house-adjacent identity). **Step 8 dependency:** shipping this card satisfies the identity half of F-NOTIFY
("EGRESS-DIRECTION-AWARE-IDENTITY-1 shipped", census plan §3.2 rung 2) and provides `notify_arrival_followup`, which
P2-D9 and step 8 call. No step-8 deliverable that names a person may build against another amend path.

## 13. Plan completion tracking

Carried from the sighting plan unchanged: G1-G4, waiter, confirmation legs, abstain rules, D2 branch, HVAC migration,
attach labels, path subscriptions. Added: G5, `identity_pair_conflict`, the amend function, `display_of` at the notify
site. Not done here, tracked: automatic pair learning (parked, trigger above); `EGRESS-PATH-OVERRIDES-DIRECTION-1`
(evidence only, D0 reports it); the patio door with no egress camera (named residual of the abstain rule).
