# Plan review 2: direction-aware egress identity (rev 2)

Plan: `docs/planning/PLANNING_egress_direction_aware_identity.md` @ 3ca25a96. Reviewer: ura-reviewer, 2026-11-14.
Framings: (1) adversarial build-prediction, (2) G goal fidelity. Every file:line below was re-read at 3ca25a96.
HVAC, presence and identity manuals were not re-litigated; no corrections-ledger claim is re-asserted.

**Verdict: FIX-PLAN.** Four HIGH, ten MEDIUM. The goal direction is right and the operator's pair-arrival agreement
is implemented; the HIGHs are mechanisms a builder cannot build as written, or that silently change behaviour the
plan claims is unchanged.

## Section 1. Adversarial build-prediction

### HIGH

**B-H1. The crossing "ring" does not exist and its retention and replace semantics are unspecified.**
The plan says confirmation does "`dataclasses.replace` in the ring" (§3 row 2, §6.3 step 2), and `ArrivalNotifier`
looks up `source_ref` via `get_crossings_since` (§6.6). On develop the tracker holds only the last record overall and
per camera (`transit_validator.py:1036-1042`). G2 is a NEW seam (contract :304) with no stated size or horizon in the
plan or contract. Builder will get wrong: (a) retention shorter than 900 s + 120 s + follow-up lag, so a confirm or
a step-8/vision count follow-up finds no record and the `nameable` check cannot run; (b) "replace" by writing
`_last_crossing_by_camera[camera]`, which clobbers a newer crossing on the same door inside the 900 s window (the
11-03 22:37/22:38 pair is exactly this). Fix: state the ring size and age horizon (≥ confirm window + pair window +
max follow-up delay, as named knobs), replace by `source_ref` only, never touch `_last_crossing*` unless the replaced
record is still the newest, and say what `notify_arrival_followup` returns when the record has aged out (False,
counted).

**B-H2. The attached-pair conflict cannot be carried on the bus (§6.5); M1 and H4 are not actually fixed.**
The bus fires once at resolution, t_E + 45 s (`transit_validator.py:2215`, scheduled at `:1397`). §6.5 decides a
conflict over [t_E − 120, t_E + 120], then says "the bus carries the same key" and perimeter
`_note_egress_identity` skips the entry. A partner edge at +80 s is known 35 s after the bus fired; perimeter has
already cached `(ts, "jaya", conf, synthetic)` (`perimeter_alert.py:5156-5176`) and, for a 0.9 attach,
`_known_identity_for` demotes on it (`:5217-5230`). D3 Verify "Attached Jaya with Ezinne's edge at +80 s →
`identity_pair_conflict` on the bus, perimeter cache skips it" is not implementable. Repro: pair `jaya|ezinne`, Jaya
attached at 0.9 (two cameras) at t_E, Ezinne's G1 edge at t_E + 80 s, perimeter edge on the door at t_E + 90 s →
security de-escalates on a conflicted identity (INV-SECURITY-BAR broken). Fix: either delay the security-relevant
attach for pair members (perimeter reads the ring through G2 at decision time and honours `identity_pair_conflict`
written by the owner at t_E + 120), or fire an owner-side correction event and have perimeter evict; pick one, do
not offer both.

**B-H3. The perimeter reroute (§6.6) is not gated by the master and changes door-camera behaviour the plan does not
declare.** INV-NOOP says perimeter behaviour is byte-identical with the master off (§4), but §6.6 never says the
reroute sits behind `EGRESS_IDENTITY_DIRECTION_AWARE`. The reroute also removes, on door cameras, two branches that
are live operator rules: the synthetic-0.9 + non-face branch (`perimeter_alert.py:5231-5236`, v5.108.1 B-M1) and the
below-floor face + non-face branch (`:5256-5261`, operator 2026-11-08). Today a 0.6 Frigate Oji face on the doorbell
plus Oji's own arrival edge demotes and names; after the reroute it needs an F3 attach ≥ 0.9 in the bus cache, which
a 0.6 attach never is, and `nameable` excludes it (< 0.75). Repro: Oji arrives, Frigate one leg 0.6, `person.oji`
flips home at +30 s, perimeter edge at +5 s → today "that was Oji Udezue"; rev 2 → no demote, no name. Builder will
either gate it (breaking §6.6's intent) or not (breaking INV-NOOP). Fix: gate on the master, and either keep the
face + own-non-face path for door cameras by routing it into `nameable` (it is the same evidence class §6.3 uses for
0.75) or list it as a declared regression for the operator.

**B-H4. Seam names and shapes contradict the contract the plan says to build to.** §3 row 6 / D0b: "builds exactly
those four seams ... to the contract signatures". The plan calls G1 `subscribe_resident_edges(cb)` (§2 :74, §3 row 3,
D0b); the contract defines `subscribe_person_edges(cb, *, persons, kinds)` with all-person scope, an `approach`
kind and `in_boot_window` (`CONTRACT_person_awareness_layer.md:303`). §6.3 has the waiter wait "event-driven on G1 /
G6 callbacks", but G6 is a pull, `location_moves_since(t)` (contract :279, :308), with no callback. A builder
following the plan builds a second, narrower G1 under a different name (two F1 edge surfaces, a contract leak) and
invents a G6 callback. Fix: use the contract names verbatim; for leg b specify polling `location_moves_since` on the
5 s sweep (or add a G6 callback to the contract first).

### MEDIUM

**B-M1. "G1".."G6" means two different things.** §6.2 guards G1-G5 (face leg, path, speed, single name, pair) and
contract seams G1/G2/G4/G6 (edges, crossings, F5 dispatch, BLE moves) share labels in the same sentences (§6.2 G5
"Partner edges come only from G1 ... and G6"; INV-CANDIDATE "G1 passes, G2 does not fail"). Builders and reviewer C
will anchor tests to the wrong one. Rename guards (e.g. K1-K5).

**B-M2. "Not synthetic-only" is not computable from the tier helper.** `egress_identity_tier_labelled` sets
`synthetic` only on the two-camera HIGH branch; a single synthetic leg returns `(MEDIUM, 0.6, False)`
(`transit_validator.py:152-161`). G1 as written passes a lone synthetic latch leg. State the predicate
(`all(getattr(leg, "synthetic", False) for leg in legs_only)` → fail).

**B-M3. `PersonArrivingPayload` does not exist.** §2 row "F5 dispatch" says payload `signals.py:28-64` REUSED;
`signals.py` at 3ca25a96 defines only string constants there (`:25`, `:31`, `:39`) and `git grep PersonArrivingPayload`
finds it only in three docs. D0b "payloads equal before and after" needs a defined type. Mark NEW and give the fields
(today's dict keys at `presence.py:5622`, `:5881`, `person_coordinator.py:1141`).

**B-M4. The tracked roster read has no public API.** §6.1 uses "the census public `tracked_person_slugs` (contract
§2.6)"; only private `PersonCensus._get_tracked_person_slugs` exists (`camera_census.py:3901`) and D0b does not list a
new public method. Builder will call the private (a layer leak) or invent one. Add it to D0b.

**B-M5. Supersede vs same-slug conflict contradict.** §6.3: a newer candidate for the slug supersedes the older
(`arrival_superseded`). §6.3 (i): another crossing claiming the SAME slug "(candidate or attached)" makes the
candidate ambiguous. For Jaya front 22:37 then garage 22:40 (both candidates), one rule names the newer, the other
abstains both. Pick one and add a test.

**B-M6. Edges between resolution and waiter start are lost.** The waiter starts "after the INSERT returns its row id"
(§6.3); the INSERT awaits the write queue (`transit_validator.py:2348`, `database.py:4617`). A G1 callback or BLE move
in that gap never reaches the waiter. Subscribe before the await, or at waiter start replay
`ResidencyTracker.recent_arrival` (`residency.py:163`) and `location_moves_since(crossing_ts)`. Also say what
happens when `log_entry_exit_event` returns None (DB absent or error, `:2342-2357`): no waiter, or waiter without
backfill.

**B-M7. GPS leg (c) "an earlier fix farther than 0.5 km" has no source or age bound.** HA state holds only the
current fix; a prior fix needs a tracker-side memory or a recorder read. Unbounded, a fix from yesterday at work
satisfies it. Name the source and an age bound (knob), or drop leg (c) if D0 (b) shows it never leads.

**B-M8. New F3 surfaces not in the contract or D6.** `SIGNAL_EGRESS_ENTRY_CONFIRMED` is a new F3 push channel; the
contract's F3 push surface is only `ura_person_egress_event` (contract :127). Provenance `"face+<leg>"` is outside
`IDENTITY_PROVENANCE_VALUES` (`const.py:3495-3499`); the sighting (c') and any census path that gates on provenance
membership (`person_sighting.py:458` gates (c) on FACE / BLE_FACE) will drop or misbucket it. D6 lists only N1, P2, R3
contract edits. Add the channel and the provenance value (as a constant) to the contract and D6.

**B-M9. Outcome accounting on confirmation is unspecified.** The attach counter reads the census outcome deque
(`sensor.py:3979-3999`, appended by `_record` in the resolver, `camera_census.py:3627`). `arrival_confirmed` is
decided minutes later outside the resolver. Is it a second deque entry and a second D8a row (denominator counts the
crossing twice) or an update? `EGRESS_OUTCOMES_ATTACHED` membership is not listed. State it; the trip-wire and gate
(b) both count these labels.

**B-M10. The fixture yield test is close to tautological.** §5.1 caveat (a): the null rows predate D8a, so whether
the resolver had a face leg is unknown, and 4 is an upper bound. `test_fixture_yield_meets_floor` replays a hand-built
JSON; the builder must invent the face legs to make the four cases name, and the floor equals that invented upper
bound (Bug Class #62 adjacent). State where each fixture field comes from (Frigate face event, recorder edge time),
and mark which fields are assumed.

### LOW

- B-L1. Stale lines: raw F5 sends are `presence.py:5622, 5881`, `person_coordinator.py:1141`, not 5678, 5937, 1172
  (§8, D0b). Contract carries the same stale numbers.
- B-L2. `freshest_gps_fix` is placed in `arrival_edges` (§2, §6.2) and in `transit_validator` (§3 row 5). Pick one.
- B-L3. "Fresh read of the name switch": the switch is options-backed and the fresh reader exists,
  `PersonCensus._is_egress_identity_enabled` (`camera_census.py:4127`). Name it (or a public wrapper) so nobody reads
  `switch.ura_name_people_at_doors` state directly.
- B-L4. `EGRESS_ARRIVAL_MAX_PENDING` overflow policy (drop newest or oldest, counted label) is unstated.
- B-L5. How the tracker reaches `ArrivalNotifier` (hass.data key, None-safe when CM is not loaded) is unstated;
  today's notify already depends on NM (`transit_validator.py:2679`), so mirror that.
- B-L6. Perimeter `_known_identity_for(cam_key, edge)` receives a name-derived stem key (`perimeter_alert.py:5140-5154`),
  not an entity. Say where the entity / device_id comes from at that site for the `door_camera_device_ids()` test.
- B-L7. Arc map still cites the veto at `:1840-1854` and says access "only with second signal"
  (`ARC_identity_vision_census_map.md:45`), which contradicts INV-ACCESS here. Orchestrator-owned (L7), still open.

## Section 2. Framing G, goal fidelity

| Charter item | Verdict | Evidence |
|---|---|---|
| "It should do both" (egress names arrivals) | MET in direction | §5.1: 3 → 7 of 10 named (upper bound) |
| Pair arrivals named (operator "Agreed") | MET | §6.3 pair rule, own edge each, conflicts unnamed |
| Minimum-yield gate | MET, with B-M10 caveat | §5.3 (a) floor 4, (b) 1/week, rung 1 |
| 0.9 security bar unchanged | MET for candidates; LEAK via B-H2 for attached pairs | |
| AWAY fast | MET for latency (no inference input changes) | §4 INV-NO-AWAY-DELAY |
| One F3 / F5 ingest, one read surface | PARTIAL | B-H4 (G1 name), B-M3, B-M4, B-M8 |
| Clip-capable frame source kept | MET | §3 row 7, no vision frame source touched |
| Registry, not names | MET in design; B-L6 open at perimeter | `door_camera_device_ids()` by `device_id` |

**G-H1 (= B-H3).** The perimeter reroute removes the face + own-non-face naming on door cameras that the operator
asked for on 2026-11-08. That is a risk reduction that changes WHAT is delivered (fewer named arrivals at doors), the
exact drift pattern the charter forbids, and it is not listed in §1's "what still stays anonymous".

**G-M1. Attached-pair deferral (§6.5) is more than the operator agreed.** The 11-14 agreement covered naming
candidates in pairs and the yield gate. §6.5 additionally makes every attached Jaya or Ezinne arrival ≥ 0.75
anonymous at t_E + 45 and named only at t_E + 120. That is a latency regression on today's named arrivals for two of
four residents. Measure how often it bites (attached ≥ 0.75 for a pair member over the D8a window) and put it to the
operator, or drop it and rely on (ii) for candidates only.

**G-M2. Entry + zone no longer registers: AWAY is faster, but a false AWAY is not measured.** §6.1 declares the
deltas "can only lower the union", which satisfies the latency constraint. A lower union with a resident physically
inside and their phone reading a named zone can also produce a wrong AWAY (the known Zone-1 away-while-occupied
shape). D0 should count entry + zone registrations per week; if non-zero, state the trade to the operator.

No drift on: clip path, access (INV-ACCESS), Protect out of scope (Q6), untracked faces (Q7 asks the operator).

## Section 3. Review 1 dispositions (§15) checked against the body

| Finding | In the body? |
|---|---|
| H1 | Yes (§5, §6.2-§6.3, §5.3) |
| H2 | Yes (§6.4, §6.6, M59), subject to B-H1 (record lookup) |
| H3 | Rerouted (§6.6), but see B-H3 / G-H1 |
| H4 | Partly: inputs via seams (B-H4 names wrong); forward window for attached entries depends on B-H2, not fixed |
| M1 | NOT fixed: rests on a bus key that cannot exist at fire time (B-H2) |
| M2 | Yes (§6.1 exit + zone evict, M63) |
| M3 | Yes (D0 (g), D5 conditional) |
| M4 | Yes (900 s) |
| M5 | Yes (L-c, Q4); `database.py:4927` verified |
| M6 | Yes (§6.7); `person_sighting.py:491` verified |
| M7 | Yes in intent; API missing (B-M4) |
| M8 | Stated §6.9; orchestrator edit owed |
| L1-L6 | Yes |
| L7 | Still open (B-L7) |

## Must-fix before build dispatch

B-H1, B-H2, B-H3 (= G-H1), B-H4; B-M1 through B-M10; G-M1 and G-M2 as operator questions with a measured number.
LOWs may be fixed in the same edit.
