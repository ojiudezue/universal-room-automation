# PLANNING: egress arrival identity (arc step 7), rev 3.2, planned against the measured door direction

Card: EGRESS-DIRECTION-AWARE-IDENTITY-1 (FACE-EGRESS-ARRIVAL-1 folded). Arc: identity / vision / census, step 7
(`ARC_identity_vision_census_map.md` §4a row 5; sightings plan §2B / D8). Author ura-planner, 2026-11-17, develop @
ef6149950 (v5.108.36). One clean document: rev 3.1 is archived verbatim at
`docs/planning/archive/PLANNING_egress_direction_aware_identity_rev3_1.md` (NOT A BUILD SPEC; rev 1 and rev 2 next to it).
Nothing below layers on rev 3.1; where a rev 3.1 design survives it is restated here, and where it is parked §11 says so
with a revival trigger.

Read first, completely, for this revision: `AUDIT_door_direction_scoring_2026_11_17.md`,
`AUDIT_crossing_vision_p3_d0e_approach_2026_11_17.md` (verdict sections), `AUDIT_arc_day_validation_2026_11_17.md`,
the charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` §goals, the contract
`CONTRACT_person_awareness_layer.md` §2.3, §4.3, the arc map §4a, and rev 3.1 whole. `IDENTITY_FUSION_CAMERAS_MANUAL.md`
§5.5 was used through CLAUDE.md's F1-F5 summary and rev 3.1's reading; not re-read whole this revision (stated, not
hidden). `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` / `SENSOR_FLEET_CLASSES.md`: not needed, no room-occupancy or
sensor-class logic is read or changed. HVAC state of play: not needed, the HVAC deliverable (rev 3.1 D5) is parked. No
corrections-ledger claim is re-asserted.

## 1. What the measurements changed (the decision this revision exists for)

Rev 3.1 built "direction-aware" naming on the tracker's direction: an `entry` with the person `not_home` became a
candidate that waited up to 900 s for the person's own phone edge. Three measurements from 2026-11-16/17 break its
premises:

1. **The tracker's direction is wrong on true entries.** On the 19 operator-graded directional crossings the tracker is
   right 10/19 (Wilson 0.32-0.73); all 9 misses are a true `in` called `out` (in 6/15, out 4/4). An always-`in` rule
   scores 15/19. I4 v1 interior timing scores 17/19 but is the best of ~6 variants tuned on the same clips, no holdout,
   1 front `out` (direction audit §2, §4). No instrument passes the P3-D0b or P3-D6 bar; P3-D10 approach clips are
   NO-GO on all three tiers (approach audit verdict). Rev 3.1's candidate path only fires on tracker `entry`, so it
   would miss roughly half the arrivals it targets and would never see them as arrivals at all.
2. **Arrivals are phone-led, not face-led.** On 11-16 every F1 arrival edge (5) came 1 to 3 minutes BEFORE its door
   crossing, led by geofence / BLE (arc-day audit Part 1). At the crossing the person already reads `home`, so the veto
   that rev 3.1 rewrote does not fire on these arrivals; they go down the existing `attached` path. Rev 3.1's waiter
   (edge AFTER the crossing) projected 0 confirmations in its own 26 h live window (rev 3.1 §5.2). Its fixture (edges
   +266 to +810 s after) used 15-minute snapshot upper bounds and predates the geofence fixes; D0 below settles which
   regime is current.
3. **What today actually gets wrong on those arrivals.** Identity attach was 5/19 directional crossings; 6 correct vetoes
   of away Jaya (BLE keeps proposing her). A phone-led arrival with a single 0.6 face leg is announced "Someone arrived"
   (the name bar is 0.75), and when the tracker calls it `exit` (9/15 graded entries) it is announced "<Name> left"
   (`_arrival_departure_notify`, `transit_validator.py:2956`), the opposite of what happened.

### 1.1 The decision: (a), direction-independent, edge-anchored naming. Not (b). Rev 3.1's waiter parked.

| Option | Pro | Con | Verdict |
|---|---|---|---|
| (a) Name on direction-independent evidence: a face leg at the door crossing for slug S AND S's OWN F1 arrival edge in a window around the crossing; ignore the tracker's direction for the arrival text | Uses the two most reliable signals we have (F1 is hardened Tier-3 code, "Away Provenance is fine"; face at the door is the existing resolver). Works on the 9/15 entries the tracker calls `exit`. No waiter, no follow-up, no ring amend: the edge already exists when the crossing resolves (measured lead 1-3 min). Never touches `direction`, census, AWAY, security | Needs the person's phone to lead (true on the measured day; D0 confirms over 14 days). A true exit within the lead window after an arrival (went back to the car) is announced "arrived" (notification class, declared). Ambiguous crossings are out (the resolver never runs on them, `transit_validator.py:1872-1874`) | **Build, slice S1** |
| (b) Wait for P3-D6 / D7 per-door vision direction | Would fix direction for every consumer, not just arrival text | No source has passed its bar; P3-D6 needs ≥ 30 oracle-scored crossings per door group with ≥ 15 `out` (front has 1 `out` graded); weeks of grading before anything ships; v6.0.0 waits on it ("You better get a move on") | **Reject as a dependency.** Vision direction keeps recording behind INV-DIR-GATE (v5.108.36); if it passes P3-D6 later, §11 P-3 is the revival |
| (c) Simpler: raise the arrival notification bar to name 0.6 faces, or swap the `left` text to `arrived` when the person is `home` | Smallest code | Names 0.6 faces with no independent evidence (rev 3.1 fixture: 3/30 misrecognition on residents, upper bound 0.17-0.26); `home` alone does not mean "just arrived" (residents walk out and in all day) | Reject. (a) is (c) plus the one independent check that makes it safe |
| Rev 3.1 as written (veto rewrite + waiter + ring follow-ups + perimeter pair-state rewiring + ArrivalNotifier + sighting c' + F5 `camera_egress` + HVAC) | Covers face-before-phone arrivals | Gated on tracker direction (fails 1.1); its yield path fired 0 in the live window; heaviest ingredients in the arc (new waiter state machine, perimeter security rewiring, cross-coordinator timers) | Park every piece with a trigger (§11), the ArrivalNotifier move included (operator 2026-11-17: "Only proven code should supersede correct code") |

**Marginal-benefit decomposition (CLAUDE.md).** The benefit is "the right person named, with the right verb, at the
door". The simplest version that captures it: S1 (one pull of F1 edges at resolution, one record attribute, one text
rule in the existing notify function). Measured upside on 11-16: up to 5 phone-led arrivals; of the graded crossings, 9/15 true entries
currently get the wrong verb. Rev 3.1's added margin is the face-before-phone arrival, which fired 0 in its live window
and whose ingredients (waiter state machine × time, a new writer feeding a security consumer, cross-coordinator pair
timers) are exactly the risky class. The margin does not pay today; the waiter is parked with a numeric trigger (§11
P-1), not deleted.

**What S1 does NOT fix (named, not silent).** Bus / DB / census still carry the tracker's direction: a true entry the
tracker calls `exit` still evicts S from the 300 s egress union (harmless to AWAY: F1 `home` is the AWAY input, and an
evict only lowers the union) and the DB row still says `exit`. Fixing direction for every consumer is P3-D6's job, not
this card's. Face-before-phone arrivals (person `not_home` at the crossing) stay vetoed as today until P-1 fires.

## 2. Charter, goals served, drift check

Verbatim: "assist arrivals accuracy and personalization" (served: the right name and verb on phone-led arrivals, and an
F3 record step 8 can read); "egress only names people who are already home... Who made this rule? ... It should do
both" (served partly and said so: S1 names arrivals at the door whatever direction the tracker guessed; the
`not_home`-at-crossing half is P-1, measured in D0 and put to the operator, Q2); "You better get a move on" (S1 is
small, Tier 2-DB, no dependency on unproven direction); "A. Alert now, name it afterwards" (unchanged: the arrival
notice still goes at t_E + 45 s, and nothing waits); "I need away to be fast acting" (no AWAY input changes, INV-AWAY).

Operator rule 2026-11-17: "We should not rebuild tier 3 that are hardened and work and we should be skeptical of
others. With clear pro/con. Only proven code should supersede correct code." Applied: the resolver, the veto, the
tracker's direction, the census register/evict, perimeter and F1 (residency) are hardened and untouched. S1 adds a
read and an attribute; it supersedes nothing. Vision direction (unproven) supersedes nothing (INV-DIR-GATE kept).

Drift check (ura-arc rule 3). Change to WHAT is delivered vs rev 3.1: face-before-phone naming moves from "built" to
"parked, measured" (P-1, Q2); pair-arrival naming is kept (partner guard only for confusable pairs, operator
2026-11-14 "Agreed"); perimeter is not rewired (rev 3.1 H2/H3 had to rewire it only because rev 3.1 produced pair-member
identities that security could read; S1 produces none, INV-SECURITY).

## 3. Institutional context verified

Greps run 2026-11-17 on develop @ ef6149950: `def (subscribe_person_edges|get_crossings_since|attach_crossing_attribute|
dispatch_person_arriving|location_moves_since|get_person_edges_since|get_crossing|door_camera_device_ids|
_arrival_departure_notify|get_last_crossing|egress_identity_tier_labelled|_resolve_direction|
_resolve_egress_face_identity_ex|_derive_face_arrival|_known_identity_for|_record_crossing)`, `_person_raw ==
"not_home"`, `INV-DIR-GATE`, `class ArrivalNotifier` over `custom_components/universal_room_automation`;
`EGRESS_ENTRY_WINDOW|CONF_EGRESS_CONFUSABLE|EGRESS_ARRIVAL_|EGRESS_PAIR_GUARD|CONSUMER_CLASS_MIN_CONFIDENCE|
EGRESS_CROSSING_RING|EGRESS_FACE_UNION_TTL_S|IDENTITY_PROVENANCE_` in `const.py`; `class ResidencyEvent` in
`residency.py`. Prior-art scan (code, plans, analysis), REUSE-or-BUILD per piece:

| Piece | Verdict | Where |
|---|---|---|
| Face resolver + single-slug rule (K4) | REUSED unchanged | `_resolve_egress_face_identity_ex` `transit_validator.py:1778`; ambiguous short-circuit `:1872-1874`; veto `:2316-2327` |
| Face tier | REUSED | `egress_identity_tier_labelled` `transit_validator.py:129` (MEDIUM 0.6 one leg, BOOST 0.75 `const.py:3430`, HIGH 0.9) |
| Tracker direction | REUSED unchanged, not read for naming | `_resolve_direction` `transit_validator.py:2384`; windows `const.py:3381-3382` |
| F1 edges, pull per person | REUSED (shipped ship 3a phase 2) | `PresenceCoordinator.get_person_edges_since(t, *, persons, kinds)` `presence.py:6135`; record `ResidencyEvent` (`counted`, `source_stale`, `in_boot_window`) `residency.py:39-51`; contract §4.3 (float epoch) |
| F1 edge push | NOT NEEDED in S1 | `subscribe_person_edges` `residency.py:233` / `presence.py:6127` (rev 3.1 waiter only; parked P-1) |
| Crossing record + additive fields | REUSED (shipped) | `CrossingRecord` `identity_role`, `nameable` (tuple), `pair_state`, `pair_partner` `transit_validator.py:965-972`; record built at `:2526` before the notify at `:2559` |
| G3 amend | NOT NEEDED in S1 | `attach_crossing_attribute` `transit_validator.py:1243` (S1 writes the fields at creation, the one F3 ingest) |
| F3 reads | REUSED | `get_crossing` / `get_crossings_since` / `door_camera_device_ids` presence delegates `presence.py:6188-6205` |
| Arrival/departure notify | REUSED IN PLACE, one keyword added (`anchor=None`) | `_arrival_departure_notify` `transit_validator.py:2956`, sole call site `:2559`. The contract §2.3 move to `ArrivalNotifier` is PARKED (§11 P-6): correct, working code is not moved without a proven need |
| Eligible face provenance | REUSED values | `IDENTITY_PROVENANCE_FACE` "face", `IDENTITY_PROVENANCE_BLE_FACE` "ble+face" (`const.py:3674-3676`); excluded `ble`, `vision` |
| Edge-ring truncation | REUSED | `PresenceCoordinator.person_edges_truncated_since(t)` `presence.py:6149` (True also with no tracker) |
| Notification bar | REUSED | `CONSUMER_CLASS_MIN_CONFIDENCE` `const.py:7271` |
| Display name | REUSED | `person_ids.display_of` (RA9, used at `transit_validator.py` notify) |
| Outcome log (D8a) | REUSED, one additive payload key | `_log_egress_outcome` `transit_validator.py:2885` |
| Layer counters | REUSED | `_count_layer_event` `transit_validator.py:1005`; read by `get_layer_diagnostics` (contract §4.3) |
| Confusable pairs | NEW `CONF_EGRESS_CONFUSABLE_PAIRS` | grep `CONFUSABLE` 0 hits in code; rev 3.1 §2 same verdict; sightings plan §2B.3 parked trigger fired (Jaya/Ezinne swaps, rev 3.1 §5.3) |
| Edge-anchor knobs | NEW `EGRESS_ARRIVAL_EDGE_LEAD_S`, `EGRESS_ARRIVAL_EDGE_CONFIDENCE` | grep `EGRESS_ARRIVAL_` 0 hits in `const.py` |
| Provenance value | NEW `IDENTITY_PROVENANCE_FACE_RESIDENCY = "face+residency"` | contract §2.3 lists it as a step 7 addition; grep 0 hits |
| Zero-fire trip-wire | REUSED pattern | AnomalyDetector → NM (CLAUDE.md fire-check corollary); the S1 counter feeds it |
| Vision direction | REUSED as recorded-only | `CrossingRecord.vision_direction` `transit_validator.py:973-979`, `CROSSING_VISION_WATCH_AMBIGUOUS` `const.py:3836`, INV-DIR-GATE `crossing_vision.py:1723` |

Prior plans / analysis read: rev 3.1 (whole; its §2 table re-verified above where reused, not inherited),
`PLANNING_crossing_vision.md` P3 bars via the direction audit's quotes (`:681-690`, `:1060-1066`), the three 11-17
audits, the contract, the charter, arc map §4a. Memory: `reference_identity_model_f1_f5`,
`feedback_fire_check_and_forward_trace`, `feedback_alert_latency_over_precision`, `feedback_registry_not_name_guessing`,
`feedback_marginal_benefit_pushback`, `feedback_extend_existing_never_rebuild`.

**Config-first.** No knob makes the arrival text direction-independent: `switch.ura_name_people_at_doors` only turns
naming off; the 0.75 bar is a module constant and lowering it is option (c), rejected. Code is needed.

## 4. Facts, consumer classes, layer conformance (contract §6)

| # | Check | S1 |
|---|---|---|
| 1 Facts | produce | F3 identity attribute on the crossing record: `identity_role="arrival_edge_anchored"`, `nameable={S: 0.75}`. The record's `provenance`, `person_id` and `identity_confidence` keep the resolver's values; the anchor's own provenance `face+residency` is carried only in the anchor local and the D8a `edge_anchor` key. Nothing else |
| | consume | F3 (resolver output, the crossing itself); F1 edges (pull) |
| 2 Ingest | F3 | the ONE ingest: the `CrossingRecord(...)` built in `_resolve_direction` (`:2526`). No amend, no second writer |
| 3 Read | F1 | `PresenceCoordinator.get_person_edges_since` (A1). No `person.*` listener added; the veto's existing raw read is unchanged |
| | F3 | `_arrival_departure_notify` receives the resolver's locals plus the anchor (not the record), so a store failure cannot lose the notice |
| | thresholds | `CONSUMER_CLASS_MIN_CONFIDENCE["notification"]` by name; no inline 0.75 |
| | classes | `_arrival_departure_notify` = notification (the only consumer that acts on the anchor). Display: the D8a outcome row key and the layer counter. Security (perimeter, scoped mute): reads bus / record `person_id` + `identity_confidence`, which S1 does not change, so security sees nothing new. Access: nothing. house_state / census (F2): nothing |
| 4 Separation | | No F4 / F2 write. The anchor is not a sighting and not a census input |
| 5 Delivery | | §2 drift check; Q1-Q4 |
| 6 Guard delta | | Removes the contract's N1 allowlisted exception (notify hosted in the F3 owner). Adds nothing |
| 7 Seams | | Step 8 reads `nameable` through `get_crossing` / `get_crossings_since` (its D5); crossing vision count follow-ups are not in S1 (P-2) |
| 8 Clip path | | none |

## 5. Falsifiable invariants (reviewer D breaks these, pre-existing code included)

Terms: "anchor" = an `arrival_edge_anchored` role on a crossing record for slug S. "Window" = the closed interval
`t_E − EGRESS_ARRIVAL_EDGE_LEAD_S ≤ edge_ts ≤ t_E + EGRESS_ENTRY_WINDOW_SECONDS`, where t_E is `egress_timestamp`
converted to epoch seconds (`edge_ts` is a float epoch, contract §4.3). The pull returns everything since the lower
bound, so the upper bound is an explicit filter: an edge at t_E + 46 s is outside.

- **INV-ANCHOR-OWN-EVIDENCE.** An anchor for S exists on crossing C only if ALL hold: (i) the resolver returned exactly
  one slug S for C, with provenance in {`face`, `ble+face`} and at least one in-window FACE leg (not all legs synthetic)
  at tier ≥ MEDIUM. `ble+face` is eligible because its face leg is independent of the phone; the anchor counts only that
  face leg plus the F1 edge, never the BLE leg. `ble` (BLE-only, `attached_ble`) is excluded because a BLE-driven F1
  edge would count the same phone twice; `vision` is excluded (INV-DIR-GATE era, not a face match);
  (v) `person_edges_truncated_since(t_E − LEAD)` is False: a truncated edge ring could hide a partner's edge, so
  truncation means no anchor (counted `edge_anchor_truncated`); (ii) `person.S` has its OWN arrival edge (`kind == "arrival"`, `counted`, not `source_stale`, not
  `in_boot_window`) with `edge_ts` in the window; (iii) no partner of S in `CONF_EGRESS_CONFUSABLE_PAIRS` has such an
  arrival edge in the window; (iv) C's tracker direction is `entry` or `exit` (ambiguous never resolves a slug). Break it
  with any anchor where one of (i)-(v) is false, e.g. a BLE-only attach (`attached_ble` 0.72) anchored by a BLE-driven
  F1 edge (same evidence counted twice), or Jaya anchored while Ezinne's edge is in the window.
- **INV-SECURITY.** The anchor never raises bus `person_id` / `identity_confidence`, the DB row, the census
  register/evict call, or any value a security- or access-class consumer reads; `EGRESS_ARRIVAL_EDGE_CONFIDENCE` <
  `CONSUMER_CLASS_MIN_CONFIDENCE["security"]` (test-asserted at import). Break it with a perimeter follow-up, demote or
  scoped mute that names S from a crossing it would not have named with `EGRESS_ARRIVAL_EDGE_LEAD_S = 0`.
- **INV-DIRECTION-UNTOUCHED.** `CrossingRecord.direction`, bus `direction`, DB `direction`, the dedup key and the
  census register/evict choice are byte-identical with the feature on and off. Break it with any of them differing.
- **INV-NO-NAME-LOSS.** For any input, every (person, crossing) named with LEAD 0 is named with LEAD > 0, with the same
  name. The only text changes are "<S> left" → "<S> arrived" and "Someone arrived/left" → "<S> arrived", each only on
  an anchored crossing. Break it with a name dropped or a different person named.
- **INV-AWAY.** No input to `infer()` / `_run_inference`, the residency producer, the census trust view, or the
  geofence trigger changes. Break it with any AWAY entry time differing between LEAD 0 and LEAD > 0 on a replay.
- **INV-NOOP.** `EGRESS_ARRIVAL_EDGE_LEAD_S = 0` (or the name switch off): notification text, title, severity,
  `coordinator_id`, record fields, D8a row (except the additive key, written `null`), bus dict, DB row, census calls
  byte-identical to develop @ ef6149950. Also holds if `get_person_edges_since` raises or returns `()` (it never raises
  by contract; the call is wrapped anyway).
- **INV-NOTICE-ALWAYS.** The arrival/departure notice for an entry/exit crossing is still sent once at resolution
  whatever the anchor computation or the record store does (the call keeps its existing `try` at `:2558-2566`; an anchor
  error leaves `anchor=None`, so the body runs with today's values).

## 6. Producer and consumer checks

| Value | Producer (arithmetic, health, fire) | Consumers (class, file:line) |
|---|---|---|
| face slug + tier | resolver `:1778`; tier `:129`. Health: identity attach 5/19 directional crossings 11-16; 6 correct vetoes of away Jaya; face attaches mostly 0.6 (rev 3.1 §5.2) | bus, DB, census (unchanged); anchor rule (new) |
| F1 arrival edge | `ResidencyTracker` (`residency.py`), fed by HA `person.*` (phones: geofence, BLE). Health: 5 arrival edges 11-16, each 1-3 min before its crossing; ground truth = the operator's own arrivals that day (arc-day audit Part 1). Fire check: fires daily | anchor rule (new, read only) |
| tracker direction | `_resolve_direction`. Health: 10/19 graded, exit bias (audit §2) | bus, DB, census, notify verb when NOT anchored (unchanged) |
| anchor (`identity_role`, `nameable`) | §7 D1; expected fire: D0 (a) measures; ≥ 1/week is the yield gate | `_arrival_departure_notify` (notification, verb + name); D8a row key (display); layer counter → trip-wire; step 8 via `get_crossing` (its plan states its class) |

Forward trace: anchor → notify text (action: the household sees the right name and verb) → D8a row → trip-wire.
Nothing reaches access, security, house_state, F2 or F5. A producer whose output reaches no action would be a gap; the
notify is the action.

## 7. Deliverables (one branch, in order)

**D0 probe (read-only, `ssh ha "python3 -"`, ura-prober).** Over the last 14 days of `person_entry_exit_events`,
`memory_episodes` (`egress_identity_outcome`, `person_arrival` / `person_departure`) and the 27 graded crossings:
(a) for every F1 arrival edge, the nearest door crossing within ±600 s: signed lead distribution (p50, p90, max), the
tracker direction on that crossing, and whether the resolver returned slug = the edge's person with provenance in
{`face`, `ble+face`}, and at what tier; this sizes `EGRESS_ARRIVAL_EDGE_LEAD_S` (p90 + 30 s, capped at 600) and gives
the yield: anchors per week that change today's text (wrong verb fixed, or "Someone" → name); (b) wrong-name exposure:
every would-be anchor on a crossing with ground truth, plus any anchor where another tracked resident also had an
arrival edge in the window; (c) true exits (graded `out`, or exit rows followed by a departure edge ≤ 900 s) that have
the same person's arrival edge in the window (the "went back to the car" false "arrived" count); (d) **Q2 / P-1
evidence:** face-slug crossings whose person was `not_home` at resolution (`vetoed`) and whose own arrival edge came
AFTER, within 900 s, per week; (e) ambiguous crossings with a face slug in a direction-free ±45 s window and an own edge
(P-4 trigger); (f) D8a still writing; (g) how often `person_edges_truncated_since(t_E − LEAD)` would have been True.
- **Expected size of the graded check (stated before running it).** The 27 graded crossings are 11-14 13:00-18:52,
  where the D8a log shows few face attaches (attach was 5/19 on 11-16, mostly 0.6) and arrival edges are a handful per
  day: expect 0 to 4 would-be anchors among the 27. That is too few to judge a wrong-name rate.
- **Verify (go/no-go):** G-YIELD: (a) ≥ `EGRESS_ARRIVAL_EDGE_YIELD_FLOOR_PER_WEEK` (1) text-changing anchors per week.
  G-WRONG, on a labelled set of at least `EGRESS_ARRIVAL_EDGE_WRONG_GATE_MIN_N` (10) would-be anchors: 0 wrong names,
  and (c) ≤ 1 per week. If the 27 graded crossings give fewer than 10, widen the labelled set in this order until it
  reaches 10: the 41-cluster labelled egress fixture (`AUDIT_egress_history_labels_2026_11_13.md`, rev 3.1 §5.1), then
  D8a outcome rows whose person's arrival is confirmed by the operator's day records (arc-day audit style: an F1 edge
  plus the person `home` afterwards and no conflicting departure). Still under 10 after widening: report the n, the
  observed wrong count and the Wilson upper bound; the operator decides (no build by default). Fail either gate → back
  to the operator, no build.
- **Discriminates:** if arrivals were face-led (rev 3.1's premise) (a) shows leads ≤ 0 and (d) is large; if phone-led
  (this plan's premise) (a) shows leads 60-180 s and (d) near 0. The two predict opposite numbers.
- **Test / Live:** none (probe). Report goes into §8 of this file before build.

**D1 the edge anchor (producer side) and the verb rule (in the existing notify function).**
Producer, in `_resolve_direction` after the resolver returns and before the record is built (`:2526`): if
`EGRESS_ARRIVAL_EDGE_LEAD_S > 0`, the name switch is on (`PersonCensus.egress_identity_enabled()`, read fresh), the
resolver returned one slug S with provenance in {`face`, `ble+face`} and an in-window FACE leg at tier ≥
`EGRESS_ARRIVAL_EDGE_MIN_TIER` (`vetoed`, `attached_ble` / BLE-only, `vision` and abstain never anchor), then:
1. `lo = t_E − LEAD`, `hi = t_E + EGRESS_ENTRY_WINDOW_SECONDS`, with `t_E = egress_timestamp.timestamp()` (the crossing
   is a `datetime`; edges are float epoch);
2. if `presence.person_edges_truncated_since(lo)` is True → no anchor, counter `edge_anchor_truncated`. The read is
   needed: a truncated ring can hide a partner edge, so truncation must fail closed (no anchor), never open;
3. `presence.get_person_edges_since(lo, persons={person.S} ∪ partners(S), kinds={"arrival"})` once, then keep only
   `edge_ts <= hi` (the pull has no upper bound);
4. apply INV-ANCHOR-OWN-EVIDENCE (ii)-(iii) to the kept edges.
At resolution (t_E + 45 s) every edge in the window has already happened, so one synchronous pull is complete; no
waiter. On pass, the record is built with `identity_role="arrival_edge_anchored"`,
`nameable=((S, EGRESS_ARRIVAL_EDGE_CONFIDENCE),)`; bus, DB, census and the record's `person_id`, `identity_confidence`
and `provenance` keep the resolver's values (INV-SECURITY, INV-DIRECTION-UNTOUCHED). The anchor (slug, confidence,
lead, provenance `face+residency`) is a local passed to the notify call. On a partner edge: no anchor, counter
`edge_anchor_pair_blocked`; on any exception: no anchor, counter `edge_anchor_error`, everything else unchanged.
Notify: `_arrival_departure_notify(direction, person_id, identity_confidence, anchor=None)` (`transit_validator.py:2956`,
sole call site `:2559`) gains the keyword. If `anchor` is given and its confidence ≥
`CONSUMER_CLASS_MIN_CONFIDENCE["notification"]`, the title is "<display_of(S)> arrived" whatever `direction` says;
otherwise the body runs unchanged. One notice per crossing (no follow-up). The D8a row gains the additive key
`edge_anchor` (`{slug, lead_s}` or `null`) through `_log_egress_outcome` (`:2885`).
- **Verify:** (1) tracker `exit`, face 0.6 Jaya, Jaya's arrival edge at t_E − 120 s → "Jaya Udezue arrived", bus
  `direction` `exit`, census `evict_egress_face("jaya")` still called; (2) same with Ezinne's arrival edge at t_E − 90 s
  and `jaya|ezinne` configured → today's text ("Someone left"), counter `edge_anchor_pair_blocked`; (3) BLE-only
  `attached_ble` 0.72 with an own edge → no anchor; (3b) `ble+face` 0.75 with an own edge → anchor; (4) edge at
  t_E − LEAD − 1 → no anchor; (4b) edge at t_E + 46 s → no anchor; (4c) Ezinne's edge at t_E + 46 s does NOT block
  Jaya; (5) edge `source_stale` or `in_boot_window` → no anchor; (5b) truncated ring → no anchor; (6) `vetoed`
  (person `not_home`) → no anchor; (7) LEAD 0 → INV-NOOP golden replay; (8) Oji + Jaya arrive together (both edges in
  window, not a configured pair) with one Oji face → "Oji Udezue arrived" (operator 2026-11-14 pair naming kept).
- **Discriminates:** a build that reads the tracker direction for the verb fails (1); a build that counts BLE twice
  fails (3); a build missing the upper filter fails (4b); a build that leaks the anchor into
  `person_id`/`identity_confidence` fails the bus-equality assertion in (1).
- **Test:** `test_egress_edge_anchor.py::test_exit_called_entry_named_arrived`, `::test_partner_edge_blocks`,
  `::test_ble_only_never_anchors`, `::test_ble_face_anchors`, `::test_edge_before_window`,
  `::test_edge_after_upper_bound_t_plus_46`, `::test_partner_edge_after_upper_bound_ignored`,
  `::test_stale_and_boot_edges_ignored`, `::test_truncated_ring_no_anchor`, `::test_vetoed_never_anchors`,
  `::test_lead_zero_noop_golden` (golden replay over direction {entry, exit, ambiguous} × {None, 0.6, 0.75, 0.9}: NM
  kwargs equal to develop), `::test_non_confusable_pair_named`, `::test_anchor_never_reaches_bus_db_census`
  (INV-SECURITY, dict equality), `::test_edge_conf_below_security_bar`, `::test_edge_read_raises_notice_unchanged`.
  Mutation drills (review C): remove the partner check; remove the provenance check; remove the upper filter; remove
  the truncation check; pass the anchor's confidence into `identity_confidence`; each must turn a named test RED.
- **Live:** within the first day with a phone-led arrival, `egress_identity_outcome` rows carry `edge_anchor` non-null
  for that crossing AND `notification_log` shows "<Name> arrived" for it; the same crossing's
  `person_entry_exit_events.direction` is whatever the tracker said (discriminates "anchor worked" from "tracker
  happened to be right": count anchored rows whose DB direction is `exit`). Ground truth: the operator's own arrival
  that day.

**D2 zero-fire trip-wire.** Counter `edge_anchor_named` (layer diagnostics) feeds an AnomalyDetector check:
`edge_anchor_named == 0` over `EGRESS_ARRIVAL_EDGE_TRIPWIRE_DAYS` (7) while F1 arrival edges ≥ 3 in the same window →
anomaly to NM ("door arrival naming has not fired in 7 days although residents arrived").
- **Test:** `test_egress_edge_anchor.py::test_tripwire_fires_on_zero_with_arrivals`, `::test_tripwire_quiet_without_arrivals`.
- **Live:** layer diagnostics show `edge_anchor_named` incrementing; no anomaly row in the first week if (a) held.

**D3 docs, same commit.** Contract §2.3 (`face+residency` anchor provenance and the `arrival_edge_anchored` role; the
N1 notify exception stays allowlisted, its move now parked as P-6), manual §4.3 / §5.5 (step 7 S1 rule;
tracker-direction exit bias cited to the direction audit; owner `EgressDirectionTracker`), arc map §4a row 5,
sightings plan §2B pointer to this file, README.

## 8. D0 report (filled before build)

`AUDIT_step7_d0_2026_11_17.md`: phone-led premise holds (16/17 leads positive, p50 79 s, p90 ~250 s); G-YIELD met
weakly (1.7/week at LEAD 300); G-WRONG not evaluable (labelled n = 0); operator chose to build (answers 2026-11-17).

**Build notes (S1, 2026-11-17).** (1) `EgressResolution` gained two additive fields, `face_tier` / `live_face_legs`,
set on the `attached` and `attached_ble_face_corroborated` returns (pure tier helper, no decision change), because the
resolution carried no leg evidence for INV (i). (2) Pair names resolve through `slug_of` then the face first-name
mapper `census.canonical_person_slug` (`oji` -> `oji_udezue`); a name not tracked is kept as written and logged.
(3) The layer guard gained two allowlist rows (R8 the 0.75 const, R2 the nightly trip-wire delegate), so §4 row 6
"adds nothing" is +2. (4) The trip-wire runs as a nightly op over persisted rows, silent until the oldest outcome row
in the window carries the `edge_anchor` key.

## 9. Knobs

| Knob | Rung | Default | Why / kill switch |
|---|---|---|---|
| `EGRESS_ARRIVAL_EDGE_LEAD_S` | 1 | 300 (D0 (a) sets p90 + 30, ≤ 600) | measured lead 1-3 min; a model constant, change needs review. **0 = feature off** (INV-NOOP) |
| `EGRESS_ARRIVAL_EDGE_CONFIDENCE` | 1 | 0.75 | face + one independent own-device edge, same evidence class as perimeter's below-floor rule; must stay < security bar (import-time assert) |
| `EGRESS_ARRIVAL_EDGE_MIN_TIER` | 1 | `CONFIDENCE_MEDIUM` (one face leg) | raising to BOOST makes S1 name only what is already named |
| `CONF_EGRESS_CONFUSABLE_PAIRS` | 2 (CM options flow, one text field "Faces often confused", e.g. `jaya|ezinne`) | empty | per household, set once; empty = guard inert |
| `EGRESS_ARRIVAL_EDGE_YIELD_FLOOR_PER_WEEK` | 1 (D0 gate only) | 1 | operator's minimum-yield rule 2026-11-14 |
| `EGRESS_ARRIVAL_EDGE_TRIPWIRE_DAYS` | 1 | 7 | D2 |
| `EGRESS_ARRIVAL_EDGE_WRONG_GATE_MIN_N` | 1 (D0 gate only) | 10 | smallest labelled set on which 0 wrong names means anything; below it the operator decides |
| `switch.ura_name_people_at_doors` | 3 (exists) | on | turns all door naming off, anchor included |

## 10. Non-goals

Changing the tracker's direction, the dedup key, the DB direction or the census register/evict choice; acting on vision
direction (INV-DIR-GATE stays); the veto (`not_home` at the crossing stays vetoed); perimeter, scoped mute, locks,
alarm; F4 sightings and F5 `camera_egress`; HVAC pre-arrival; ambiguous crossings; follow-up messages; a crossing
waiter; Protect face names.

## 11. Parked (not deleted), each with its revival trigger

- **P-1 face-before-phone confirmation (rev 3.1 §6.2-§6.3 waiter, guards K1-K5, GPS leg).** Trigger: D0 (d) ≥ 1 per
  week. Then it is re-planned against the anchor (the same own-edge rule, post-crossing side) and reviewed Tier 3.
- **P-2 one naming path for follow-ups (rev 3.1 §6.7: `notify_arrival_followup`, perimeter send routing).** Trigger:
  crossing-vision count follow-ups or step 8 need a door-naming follow-up. Rides on P-6.
- **P-3 direction for every consumer.** Trigger: a source passes P3-D6 per door group (Wilson LB ≥ 0.90 on ≥ 30
  oracle-scored, ≥ 15 `out`). Owner: crossing vision plan, not this card.
- **P-4 ambiguous crossings.** Trigger: D0 (e) ≥ 1 per week with a face slug and an own edge; needs a direction-free leg
  window in the resolver (hardened code: pro/con review first).
- **P-5 pair-state for security (rev 3.1 §6.6) and F5 `camera_egress` / HVAC (rev 3.1 D4/D5).** Trigger: P-1 ships an
  egress identity that a security consumer could read, or an anchor ever leads its F1 edge (D0 (a) leads ≤ 0 at p50).
- **P-6 move the notify to `ArrivalNotifier` (contract §2.3 N1 exception, rev 3.1 §6.7).** Parked under the operator's
  2026-11-17 rule "Only proven code should supersede correct code": `_arrival_departure_notify` is correct and S1
  needs only a keyword. Trigger: a second door-naming sender is needed (P-2, crossing-vision count follow-up, step 8),
  or the layer guard cleanup (LAYER-LEAK-CLEANUP-1) schedules N1.
- **P-7 departure naming unchanged by design in S1.** "<Name> left" still follows the tracker's `exit` and the
  resolver's ≥ 0.75 rule; no F1 departure edge anchors it (departure edges often come minutes after the door, and the
  tracker is right on `out` 4/4 graded). Trigger: graded `out` crossings reach ≥ 15 and the tracker's `out` accuracy
  drops below 0.90 Wilson LB, or the operator reports wrong "left" names.

## 12. Residuals named

A true exit within LEAD of the same person's arrival is announced "arrived" (D0 (c) sizes it). The tracker-wrong
`exit` still evicts S from the 300 s egress union and the DB row still says `exit` (P-3). Two faces on one crossing,
and BLE-only attaches, stay anonymous. Confusable pairs arriving together stay anonymous.

## 13. Operator questions (each with the recommended default)

- **Q1. Accept (a) and do not wait for P3-D6 vision direction?** Default: yes.
- **Q2. Face-before-phone naming ("egress only names people who are already home... It should do both"): build now,
  or park until D0 (d) shows it happens?** Evidence so far: on 11-16 all 5 arrival edges came 1-3 min before the
  crossing (0 face-before-phone); rev 3.1's waiter projected 0 confirmations in its 26 h live window; its older
  fixture (edges +266 to +810 s after) rests on 15-min snapshot bounds. Default: park (P-1) and decide on D0 (d)'s
  14-day per-week count; ≥ 1 per week revives it as a Tier-3 follow-on built on the same own-edge rule.
- **Q3. When the tracker says "left" but the person's own phone says they just arrived, announce "arrived"?** Default:
  yes (9/15 graded entries currently get "left"; the reverse error is sized by D0 (c)).
- **Q4. Confusable pairs.** ANSWERED 2026-11-17: "Jaya Ezinne not only confusable pair. It can also be Jaya Oji." Initial value `jaya|ezinne, jaya|oji`; the setting accepts any number of pairs.

## 14. Tier, reviews, dependency, completion

**Tier 2-DB, operator-elevated per standing policy (identity naming is regression-prone), plus framing G.** Not Tier 3:
no state machine, no shared-primitive change (G3 untouched; one additive field write at the one ingest), no
cost/safety/security consumer, no AWAY input. Trigger to go back to Tier 3: P-1 or P-5 revived. Plan review: one
adversarial review + framing G before build. Build reviews: A local correctness (anchor rule, windows, flags), B
integration (byte-identical no-op, ingest order, notify exception path, D8a payload key), C per-site source mutation
(sonnet), plus G goal fidelity. Live validation + README write-back. Builder: ura-builder.
Dependency: none open (G1/A1/G2/A3/A9/G3 shipped in ship 3a). Blocks: step 8 D5 reads `nameable`.
Completion: rev 3.1 D0b (shipped by ship 3a); rev 3.1 D1-D6 and its ArrivalNotifier move superseded or parked as listed in §11; nothing dropped silently.
