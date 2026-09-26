# PLANNING — HVAC W2: night still-sleeper hold + reloading-room placeholder readers

**Workstream:** HVAC-W2-OCCUPANCY-TRUTH (see kanban L1834).
**Scope of THIS plan:** two of the five W2 children — HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1
(Piece A) and HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1 (Piece B) — plus a scope-check on
HVAC-GUEST-AS-ZONE-PERSON-1 (Piece C).
**Not in scope:** HVAC-DEGRADED-ROOM-TRIPWIRE-1 (v5.103.15, in review), W2 fast path
(`PLANNING_hvac_w2_occupancy_fast_path.md`), HVAC-HOT-ENTRY-LATENCY-1, HVAC-GUEST-AS-ZONE-PERSON-1
build (Piece C only recommends whether it belongs here or later).
**Read first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — completely; this plan
assumes it and cites into it. Operator principle (binding): **HVAC matches occupancy IN THE ZONE
— never "anyone home"** (§9c/§9d/§11).
**Sequence:** builds start ONLY after (i) v5.103.15 live-room establishment merges to `develop`
and (ii) the W2 fast path lands or its plan reviews confirm no `hvac.py` overlap with these two
pieces. Flag: `hvac.py` overlap with Piece B (D5 site `~2278-2296`) and with the fast-path's
per-zone rate-limited cycle dispatch.

---

## Institutional context verified

### Design docs
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — read in full. Load-bearing sections:
  §2 (5-min tick, no occupancy-triggered cycle), §3.1 room producer + D8 night tail-hold
  (`const.py:1230-1242` bedroom/media 30 min), §3.2 shared retreat gate
  `conditioning_retreat_ok` + reset-only backstop (`hvac_zones.py:1085`;
  `hvac.py:3830 _zone_conditioning_retreat_ok`) and the list of readers that BYPASS it
  (§3.2 last row), §7 lockout mechanics, §9.3 the Jaya-night finding, §9.4 the three placeholder
  readers, §9b (failed room = not defined in URA), §9c (override switches — LEAVE AS IS),
  §9d (fast-path scope = shave the tick only), §11 approved arc.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` — the v5.103.15 branch introduces the
  live-room classifier this plan REUSES: `is_zone_transient_blocked`,
  `_coordinator_absent_this_pass`, `excluded = not defined` (feature/hvac-live-room-establishment).
- `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` — dispatched; overlap flagged below.
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` — origin of D7/D8 and the parked
  full 200-min/4-discharge machinery preserved on the night-leniency card.

### Kanban cards (read in full)
- **HVAC-W2-OCCUPANCY-TRUTH** (L1834) — parent, order, operator decisions 2026-09-26.
- **HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1** (L2261) — Piece A. TRIGGER_FIRED_2026_09_25
  documents Jaya nights 09-24/09-25, corroborator candidates (stationary in-suite BLE + radar
  micro-blips), and the zone-scoped-only constraint. Full 200-min/4-discharge design preserved
  on the card for reference — this plan does NOT propose that machinery outright; it lets the
  probe pick.
- **HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1** (L1965) — Piece B. Evidence: D5 coast defer
  `hvac.py:2278-2296` (Reviewer D F3), D6 stale-failsafe `presence.py:2148-2157` (F6),
  `continuous_occupied_since` `hvac_zones.py:746-754` (Reviewer B), zone.rooms frozen at
  discovery (F7). `next` sketches the fix; this plan lifts it into acceptance criteria.
- **HVAC-GUEST-AS-ZONE-PERSON-1** (L20648) — Piece C. Operator constraints 2026-08-20:
  (1) applies ONLY if zone has no assigned person (today zone_3 only), (2) VERIFY the sleep-latch
  actually reads zone_persons vs occupancy BEFORE building. Two-stage arm + post-sleep-onset
  recheck design captured on the card. Suppression-needs-a-discharge is unresolved.
- **HVAC-DEGRADED-ROOM-TRIPWIRE-1** (L1903) — the v5.103.15 in-flight cycle whose classifier
  Piece B REUSES.

### Memory bodies pulled
- `feedback_suppression_needs_discharge` — every hold Piece A introduces must name what
  re-arms it, what discharges it, and its restart/boot behaviour.
- `feedback_measure_before_build` — Piece A is empirically gated; measurement probe is D1.
- `feedback_extend_existing_never_rebuild` — REUSE the v5.103.15 classifier, do not duplicate.
- `feedback_verification_needs_disjoint_framings`, `feedback_falsify_before_asserting` —
  acceptance criteria discriminate the fix from a plausible different failure.
- `feedback_tier2plus_prior_art_scan` — REUSE/BUILD verdict per proposed piece, below.
- `feedback_coincidental_equality_masks_concept_split` — night-hold extension must not
  silently equal a house-wide "anyone home" gate.

### Prior-art scan (REUSED/NEW per proposed piece, file:line)

Piece A — night still-sleeper hold:
- **REUSED — in-suite BLE / person→room binding:** `CONF_ZONE_PERSONS` + BLE room mapping
  (Bermuda), the `ble_persons` config surface, `occupancy_source="override"` BLE anchor. Grep
  targets to re-run at build: `zone_persons`, `ble_room`, `bermuda`, `iphone_.*_area`,
  `iphone_.*_distance`, `_stationary`. Live entities present tonight:
  `device_tracker.iphone_jaya_bermuda_tracker`, `sensor.iphone_jaya_area`,
  `sensor.iphone_jaya_distance` (evidence card).
- **REUSED — radar micro-blip source:** the same D1 producer inputs
  (`binary_sensor.jaya_3_presence`, `binary_sensor.mmwave_zigbee_jayabedroom_presence`) already
  feed `RoomCondition.hvac_occupied` (`hvac_zones.py:988`). No new sensor.
- **REUSED — per-room-type night hold knob:** `ROOM_TYPE_HVAC_HOLD_NIGHT` (`const.py:1230-1242`)
  and per-room overrides `CONF_HVAC_VACANCY_HOLD_NIGHT` (`_effective_hvac_hold_seconds`
  `hvac_zones.py:894`). New behaviour extends the existing hold; it does NOT invent a second
  timer.
- **REUSED — night-window / house-state:** existing house-state `home_night` + the existing
  D7 night-trust gate site (`hvac.py:2403`). Do not invent a new time window.
- **REUSED — fused/established gates:** `conditioning_retreat_ok` (`hvac_zones.py:1085`);
  Piece A hooks the extension INSIDE the tail-hold, so the gate contract is unchanged.
- **NEW — "stationary in-suite BLE" predicate:** derived helper on the room, e.g.
  `is_bedroom_person_stationary_in_suite(room, window_s, distance_var_ft)`. NEW because grep
  should confirm no existing helper combines person↔room binding + distance variance + dwell.
  If grep finds one (e.g. inside `presence.py` or `person_coordinator.py`), REUSE it.
- **NEW — radar micro-blip tail-restart:** a "any raw source blip within the hold restarts
  the tail" behaviour. NEW as a *rule* but implemented by extending the existing tail-hold
  arm site in `hvac_zones.py` — no new timer surface.

Piece B — placeholder readers:
- **REUSED — shared retreat gate:** `_zone_conditioning_retreat_ok` (`hvac.py:3830`) via
  `conditioning_retreat_ok` (`hvac_zones.py:1085`). This is the exact call `next` on the card
  cites for D5.
- **REUSED — v5.103.15 live-room classifier:** `is_zone_transient_blocked`,
  `_coordinator_absent_this_pass`, `excluded = not defined` (feature branch
  `feature/hvac-live-room-establishment`). D6 Source-4 uses `_coordinator_absent_this_pass`
  to EXCLUDE reloading/absent rooms from the room count.
- **REUSED — synthetic-empty flag:** the coordinator-absent placeholder path
  (`hvac_zones.py:616-641`). `continuous_occupied_since` checks that flag rather than resetting
  when the room's `hvac_occupied` transitions to False on a synthetic row.
- **NEW — none.** Every fix is a rewire onto existing predicates.

Piece C — scope check only:
- **VERIFY-FIRST (operator 2026-08-20 constraint on the card):** does the sleep-veto path
  (`aggregation.py:4017-4019`) actually gate on zone_persons or on real zone occupancy? If the
  latter, one of the three protections in the card's premise is already there and the card
  scope shrinks. This verification is NOT in W2's other pieces and is a prerequisite before
  scoping.

### Code locations surveyed
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — §2 tick sites
  (`:1356-1547`), D5 duty-cycle occupancy defer (`:2271-2289`), D6 stale-failsafe reader
  (`:2063`), retreat-gate delegate (`:3830`), pre-arrival (`:4002`).
- `.../domain_coordinators/hvac_zones.py` — producer (`:966-1035`), tail-hold
  (`_effective_hvac_hold_seconds` `:894`), synthetic-empty (`:616-641`),
  `continuous_occupied_since` (`:746-754`), retreat gate (`:1085`).
- `.../domain_coordinators/presence.py` — D6 Source-4 room count (`:2148-2157`).
- `custom_components/universal_room_automation/const.py` — night-hold table (`:1230-1242`).
- Live evidence entities (card): `sensor.iphone_jaya_area`, `sensor.iphone_jaya_distance`,
  `device_tracker.iphone_jaya_bermuda_tracker`, `binary_sensor.jaya_3_presence`,
  `binary_sensor.mmwave_zigbee_jayabedroom_presence`,
  `fan.fanswitch_treat_wifi_jayabedroom`.

---

## Falsifiable invariants (state them up front — reviewer D must falsify these)

- **INV-A1 (night still-sleeper):** for every home_night interval in which a bedroom-typed room's
  bound zone_person is stationary in-suite (per the chosen corroborator), the zone containing
  that room does not retreat.
- **INV-A2 (zone scope):** the night hold NEVER extends because of a person stationary in a
  DIFFERENT zone. The gate is per-room→per-zone; it MUST NOT read house-wide `anyone home`.
- **INV-A3 (degrade safely):** if the corroborator input is stale, unavailable, or the person
  binding is missing, Piece A becomes a no-op — behaviour reverts to the current 30-min D8
  hold. A missing signal MUST NOT extend the hold.
- **INV-A4 (discharge):** the extended hold has a named backstop discharge (house-state exit
  from `home_night`; a hard cap; restart). A person leaving the suite must release the hold
  within one hold cycle.
- **INV-B1 (placeholder never trusts empty):** on ANY path that today reads
  `zone.any_room_hvac_occupied` raw and MAY drive the zone toward away, a room whose
  coordinator is absent (synthetic-empty) MUST be excluded from that reader OR the reader must
  route through `_zone_conditioning_retreat_ok`. No new path may act on a synthetic empty.
- **INV-B2 (continuity):** `continuous_occupied_since` (`hvac_zones.py:746-754`) MUST NOT reset
  when the only reason a room's `hvac_occupied` fell to False is the synthetic-empty
  placeholder.
- **INV-B3 (byte-identical on the healthy path):** when no room in the zone is
  coordinator-absent this pass, Piece B's decisions are byte-identical to develop
  post-v5.103.15.

Reviewer D's sole job: state each invariant in falsifiable form and BREAK it with a
legal-config reachable repro.

---

## Piece A — night still-sleeper hold

### A0 — MEASURE FIRST (deliverable D-A0, mandatory before any A build)

Cheap one-shot read-only probe over the HA recorder (`/config/home-assistant_v2.db`) via
`ssh ha "python3 -" < probe.py`. Window: 7 days. Per bedroom-typed room in every zone:

1. Enumerate night-window episodes where the zone's `hvac_occupied` (from
   `binary_sensor.<room>_<room>_hvac_occupied` OR the fused zone signal
   `sensor.ura_hvac_coordinator_zone_{n}_status` `any_room_hvac_occupied`) dropped between
   02:00–06:00 while a zone-bound person's BLE `sensor.iphone_<name>_area` reported the room
   or its bathroom sibling, AND `sensor.iphone_<name>_distance` variance stayed low
   (thresholds to fit; provisional ≤3 ft over ≥10 min).
2. For each such episode, count raw radar micro-blips (any state transition on either raw
   presence source) inside the drop gap.
3. Cross-cut by room, by night, by which sensor was UNAVAILABLE.
4. Also count episodes where BLE was ABSENT / stationary variance is NOT computable — to size
   the safe-degrade case (INV-A3).

Output written to `docs/planning/AUDIT_hvac_night_still_sleeper_probe_2026_XX_XX.md`. Numbers
required BEFORE A1 scoping:

| Number | Why it matters |
|---|---|
| `N_episodes` (drops with a stationary in-suite person) | sizes the problem; if <2 in 7 d, Piece A drops to PARK-with-trigger |
| Median gap length | tells us whether the current 30-min D8 hold + a small extension solves it, or whether the full 200-min machinery is needed |
| `N_episodes with ≥1 radar micro-blip in the gap` | picks between corroborator (b) radar-blip-restarts-tail vs (a) BLE-only |
| `N_episodes with BLE absent/degraded` | proves INV-A3 is reachable + sizes the no-op fraction |
| Sign convention on `distance` (ft vs m) | verifies the stationary threshold |

### A1 — Design (evaluated with A0 numbers)

Three options to compare AGAINST THE NUMBERS. Pick ONE with a written margin argument
(`feedback_marginal_benefit_pushback`); do not build the fancier when the simpler captures
most of the benefit.

- **(a) BLE-only extension.** If the bound zone_person is stationary in the room's suite,
  extend the per-room night tail-hold up to a cap. Reuses `_effective_hvac_hold_seconds`
  (`hvac_zones.py:894`) — add a night-time bonus term keyed on the new BLE-stationary
  predicate. Zone-scoped by construction (person→room binding).
- **(b) Radar-blip-restarts-tail.** Any raw presence blip (either radar) within the hold
  restarts the tail. Cheap, no BLE dependency, but does nothing when radars flatline (the
  09-24/09-25 pattern with `mmwave_zigbee` unavailable and Seeed silent). Likely dominated by
  (a) on the measured data.
- **(c) Both, AND-ed.** Extension arms on (a); blips restart on (b). Reviewer must justify
  each ingredient with margin.

Chosen corroborator (**provisional, gated on A0**): **(a) BLE stationary in-suite with (b) as
tail-restart if A0 shows radar blips inside the gap on ≥50% of episodes.** Reasoning: (a)
directly witnesses the failure mode (Jaya phone stationary through both nights while radars
lost her); (b) is cheap insurance when raw blips exist.

### A2 — Knob ladder (Numbers Get Knobs)

| Knob | Rung | Why |
|---|---|---|
| `HVAC_NIGHT_STILL_SLEEPER_MAX_EXTENSION_MIN` | Module const (`hvac_const.py`) | Safety cap on how long the hold may extend past D8. Change requires review. |
| `HVAC_NIGHT_STILL_SLEEPER_DISTANCE_VARIANCE_FT` | Module const | Definition of "stationary"; couples to sensor characteristics. |
| `HVAC_NIGHT_STILL_SLEEPER_DWELL_MIN` | Module const | How long BLE must be in-suite before arming. |
| `switch.ura_hvac_coordinator_night_still_sleeper_hold` | Switch entity (RestoreEntity) | Live kill-switch. Default: **OFF at first ship**; flipped ON after A0 + one clean night. |
| Per-room override: `CONF_HVAC_NIGHT_STILL_SLEEPER_ENABLE` | Options flow | Per-bedroom disable if a room's BLE is unreliable. |

Discharge (INV-A4): (1) house-state exits `home_night`; (2) BLE stationary predicate goes
False (person left the suite); (3) `MAX_EXTENSION_MIN` cap; (4) restart clears in-memory
extension state (fail-closed to D8).

### A3 — Wire-in anchors (mandatory per `feedback_wire_in_anchor_mandatory`)

- **Enclosing behavioural anchor:** an integration test drives the D1 producer through a
  simulated night: person BLE stationary in-suite, both radars silent for 45 min → assert
  `zone.hvac_occupied` remains True and preset does NOT flip at row-1 (`hvac.py:2013`).
- **Call-neuter drill:** temporarily neuter the BLE-stationary predicate in production source
  → the anchor test FAILS. Restore, re-verify GREEN. Repeat for the tail-restart branch if
  built.
- **Cross-cut mutation:** flip the person→room binding to a DIFFERENT zone's room → the hold
  MUST NOT extend the wrong zone (INV-A2).
- **Degrade drill:** set BLE `unavailable` → hold reverts to 30-min D8 (INV-A3).

### A4 — Acceptance criteria (must discriminate; `feedback_falsify_before_asserting`)

- **Sensor:** new `binary_sensor.<room>_<room>_hvac_night_still_sleeper_hold` reports the
  extension state with attributes (`ble_area`, `distance_ft`, `distance_variance_ft`,
  `blip_count`, `extension_remaining_s`, `discharge_reason` on release).
- **Verify (unit):** night simulation above.
- **Verify (discriminating):** a night with the person's BLE showing the room's *sibling
  bathroom* only, distance high-variance → NO extension. This distinguishes "sleeping" from
  "moving through the suite".
- **Verify (degrade):** BLE unavailable → extension never arms; behaviour == pre-Piece-A.
- **Verify (zone scope, INV-A2):** stationary in-suite person in zone_2 does NOT hold zone_1
  or zone_3 (drive a probe with zone_1 empty at 02:30).
- **Live:** re-run the A0 probe query 7 nights post-deploy. Every drop episode over the
  window either (i) has the BLE stationary predicate False at drop time (real vacancy) or
  (ii) shows the extension armed and the zone did NOT retreat. Any counter-example is a bug.
- **Live:** repeat the Jaya-night query specifically — 02:00–06:00 zone_2 with Jaya BLE
  stationary. Expected: zero retreats over the observation window.
- **Test:** `test_hvac_night_still_sleeper_holds_when_ble_stationary_zone_scoped`,
  `test_hvac_night_still_sleeper_does_not_arm_on_sibling_bathroom_only`,
  `test_hvac_night_still_sleeper_degrades_to_d8_on_ble_unavailable`,
  `test_hvac_night_still_sleeper_does_not_leak_across_zones`,
  `test_hvac_night_still_sleeper_restart_forgets_extension`.

### A5 — Non-goals
- No "anyone home" gate. Ever.
- No inference of house-wide guest/resident state from this predicate.
- No new time window; uses existing `home_night`.
- No change to D7 night-trust suppression or D8 base hold.
- Does not build the full 200-min/4-discharge machinery preserved on the card unless A0
  numbers argue for it (they likely will not; document either way).

### A6 — Tier and reviews
- **Tier 2-DB** (three framing-disjoint reviews) — regression-prone (touches the tail-hold in
  the shared retreat gate's producer path; consumer set = every zone at night). Framings:
  A = local correctness (BLE predicate, distance variance, dwell arithmetic);
  B = state-machine integrity + discharge coverage + restart + degrade paths;
  C = new-surface authority (switch/sensor/config knobs round-trip through options flow +
  RestoreEntity; test fixtures drive production).
- Plan-review pass BEFORE build (Tier 2 plan rule) with mandatory prior-art re-grep of the
  BLE / stationary / distance-variance surface.

---

## Piece B — placeholder readers (D5, D6, continuous-occupied)

### B1 — Rewire the three bypassing readers (deliverable D-B1)

Every fix REUSES the v5.103.15 classifier landed on `feature/hvac-live-room-establishment`.
No new predicate.

1. **D5 coast occupancy defer (`hvac.py:2278-2296`).** Replace the raw
   `zone.any_room_hvac_occupied` read with the shared retreat check:
   *defer coast-away when `not self._zone_conditioning_retreat_ok(zone)`*. This is exactly the
   call sketched in the card's `next`.
2. **D6 stale-failsafe Source-4 room count (`presence.py:2148-2157`).** Exclude rooms whose
   coordinator is absent this pass (v5.103.15 `_coordinator_absent_this_pass`) from the count.
   Also apply the v5.103.15 "excluded (failed/disabled/removed) = not defined" rule (§9b) —
   an excluded room contributes zero, matching the operator's option (a) choice.
3. **`continuous_occupied_since` (`hvac_zones.py:746-754`).** Do NOT reset the clock when the
   only reason `hvac_occupied` flipped False is the synthetic-empty placeholder. Detect via
   the synthetic-empty flag (`hvac_zones.py:616-641`); on synthetic rows, hold the previous
   value.
4. **zone.rooms frozen at discovery (Reviewer D F7).** Note only — not fixed here. Card
   `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` acknowledges this as a separate F7 concern;
   fixing it means resolving `zone.rooms` at each producer pass, which crosses the fast-path's
   territory. Leave as a follow-up card (see §Deferred below).

### B2 — Wire-in anchors

- **D5 anchor:** integration test — EC coast, zone runtime_exceeded, home_evening,
  `zone_1=[Office occupied, Study empty]`, Office coordinator reloads → assert D5 does NOT
  force away. Repeat with an all-dead zone under coast → assert D5 does NOT retreat it (INV-B1).
- **D6 anchor:** integration test — Source-4 count with 1 of 3 rooms coordinator-absent →
  count reads 2, no one-tick stale_occupancy away, no stuck-signal NM.
- **Continuity anchor:** unit test — a room flips to synthetic-empty for one pass →
  `continuous_occupied_since` unchanged.
- **Neuter drill:** revert each rewire one at a time in production source → the anchor test
  for that site FAILS RED; restore, re-verify GREEN. A site whose neuter leaves the suite
  green is an untested site.
- **Byte-identical drill (INV-B3):** run the healthy-path integration suite (no coordinator
  absent this pass) → results identical to develop post-v5.103.15.

### B3 — Knob ladder
- **No new knobs.** Fixes are behaviour-preserving rewires onto existing predicates.

### B4 — Acceptance criteria

- **Verify (D5):** Reviewer D F3 repro no longer forces away.
- **Verify (D6):** stale-failsafe count in `sensor.ura_presence_zone_{n}_source4_room_count`
  (or its actual name — verify at build) matches loaded-and-present room count.
- **Verify (continuity):** `sensor.ura_zone_{n}_continuous_occupied_since` does not reset on
  a coordinator reload of a sibling room.
- **Verify (INV-B3 byte-identity):** integration suite diff vs develop post-v5.103.15 on the
  healthy path = empty.
- **Test:** `test_d5_coast_defers_when_zone_not_cleared_to_retreat`,
  `test_d5_coast_does_not_retreat_all_dead_zone`,
  `test_d6_source4_excludes_coordinator_absent_rooms`,
  `test_continuous_occupied_ignores_synthetic_empty`.
- **Live:** post-deploy, force a room reload on zone_1 and confirm no one-tick D5 away, no
  stuck-signal NM on D6, no `continuous_occupied_since` reset in the recorder.
- **Live:** query `hvac_excursion_events` + `ac_ramp_events` for one week — no unexplained
  one-tick away/reset transitions correlated with room reloads.

### B5 — Non-goals
- Not resolving F7 (zone.rooms frozen at discovery); carded separately.
- Not changing the shared retreat gate itself (that shipped in v5.103.15).
- No behaviour change on the healthy path (INV-B3).

### B6 — Tier and reviews
- **Tier 2-DB** (three framing-disjoint reviews) — regression-prone (touches D5 duty-cycle,
  D6 stale failsafe, and the shared continuity clock; cross-coordinator with presence.py).
  Framings:
  A = correctness of each rewire + edge cases (coordinator-absent-on-boot, all-dead zone);
  B = cross-coordinator integrity (presence D6 Source-4 semantics preserved; no double-emit),
  restart, and byte-identity on the healthy path;
  C = adversarial completeness — re-enumerate EVERY reader of `any_room_hvac_occupied` and
  the synthetic-empty flag across the codebase (grep, do not trust the card's list) and
  verify each is either fixed or explicitly justified as safe.
- Plan-review pass BEFORE build.

---

## Piece C — HVAC-GUEST-AS-ZONE-PERSON-1 scope check

**Recommendation: DO NOT include in this plan. Sequence AFTER Pieces A + B.** Reasons:

1. **Operator prerequisite unresolved.** The card carries an explicit verify-first
   (2026-08-20): confirm whether the sleep-veto (`aggregation.py:4017-4019`) already gates on
   real zone occupancy vs `zone_persons` membership. That verification is a prerequisite; it
   may shrink or kill the card. It is not W2's other pieces' work.
2. **Coincidental-equality hazard.** A guest predicate that "counts an occupied guest room as
   the zone's person" is at risk of the exact coincidental-equality smell
   (`feedback_coincidental_equality_masks_concept_split`) between "in-zone occupancy" and
   "in-zone identity". Piece A introduces a person-binding predicate; Piece C would layer a
   *synthetic* person on top. Building them together tempts sharing plumbing that must stay
   disjoint (INV-A2 depends on real person→room binding; Piece C would supply a synthetic
   binding that MUST NOT feed Piece A's night hold, or a random guest-room blip could pin a
   whole zone at comfort overnight — worse than today).
3. **Suppression-needs-a-discharge is unresolved on Piece C.** The card documents a two-stage
   arm + post-sleep-onset recheck design but leaves the discharge contract open. That is a
   standalone design pass, not a Piece-A/B rider.
4. **Blast radius fits its own cycle.** Piece C touches three inert suppressions
   (`hvac.py:1788-1795`, `aggregation.py:4017-4019`, `aggregation.py:4152-4154`) + pre-arrival
   routing (`hvac.py:3267-3273`). It is Tier 2-DB in its own right and deserves independent
   framings.

**Proposed sequence:** Piece B → Piece A → verify-first on `aggregation.py:4017-4019` →
Piece C planning cycle (separate doc) if the verification confirms the gap. This preserves
the operator-approved W2 order (parent `next`: live-room gate → fast path → night hold →
placeholder readers → guest-as-person) and only reorders A/B for build efficiency (B is
smaller and unblocks nothing else, so it should ride the review pipeline in parallel with
Piece A's measurement probe).

---

## Sequencing (build order)

1. v5.103.15 merges to `develop`.
2. W2 fast-path plan lands OR its reviews confirm no `hvac.py` overlap with Piece B's D5 site
   or with any producer-pass ordering Piece B depends on. **Flag: reviewer must diff
   fast-path's dispatched cycle against Piece B's D5 rewire — they touch neighbouring code and
   share the assumption that a producer pass has just run.**
3. **Piece B build** (Tier 2-DB) — smaller, no measurement gate. Ships first.
4. **Piece A — D-A0 probe** (read-only). Numbers go into an AUDIT doc.
5. **Piece A design pick** (a / b / c) with margin justification. Plan-review pass.
6. **Piece A build** (Tier 2-DB). Ships with switch OFF by default; flip ON after one clean
   night + live probe re-run.
7. Piece C: verify-first, then a separate planning cycle.

## Deferred items (accounted for, not silently dropped)

- **F7 (zone.rooms frozen at discovery)** — carded on
  HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1 evidence; needs its own card + plan. Not fixed by
  Piece B.
- **Full 200-min/4-discharge night machinery** — preserved on
  HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1; unbuilt unless A0 numbers argue for it.
- **Jaya Zigbee radar hardware repair** (unavailable since 2026-09-25 19:32) — physical, not
  in this plan; parent card `next` notes it.
- **Piece C build** — see §Piece C recommendation.

## Return summary (per orchestrator ask)

- **Measured numbers:** NONE yet — D-A0 is the measurement gate; probe design is spec'd in
  A0 (7-day recorder read of night drops with stationary in-suite BLE + radar micro-blips
  per bedroom-typed room per zone). The A1 design pick is gated on those numbers.
- **Chosen corroborator (provisional):** (a) BLE stationary in-suite as the primary
  arm; (b) radar micro-blip tail-restart added ONLY if A0 shows radar blips in ≥50% of drop
  gaps. Zone-scoped by person→room binding; degrades to today's D8 when BLE is unavailable.
- **Invariants:** INV-A1..A4 (night hold), INV-B1..B3 (placeholder readers) — stated
  falsifiably above; reviewer D must break them with legal-config reachable repros.
- **Tiers:** Piece A = Tier 2-DB (3 framings + plan review + live re-probe write-back);
  Piece B = Tier 2-DB (3 framings + plan review + byte-identity healthy-path drill); Piece C
  = out of scope for this plan (own Tier 2-DB cycle after verify-first).

---

## D-A0 RESULTS (measured 2026-09-26)

**Probe:** `scripts/probes/hvac_night_sleeper_probe.py` (read-only; rerun:
`ssh ha "python3 - --days 8 [--verbose]" < scripts/probes/hvac_night_sleeper_probe.py`). Recorder window
**2026-09-18 04:18 → 2026-09-25 23:44 CDT** (≈7.8 nights; the 09-17/18 night is morning-only; 09-25/26 is in
progress). Drops = `binary_sensor.<room>_<room>_hvac_occupied` on→off with drop time in 22:00–08:00. Gap =
[drop, min(return, drop+90 min)]. "Stationary in-suite" = Bermuda `*_area` in the room's suite (room + en-suite /
scanner areas) ≥ 90 % of the gap AND pstdev(`*_distance`) ≤ 3 ft. Zone-away = zone climate `preset_mode` or
`hold_activity` == `away` inside the gap. Room/sensor/zone/person mapping pinned from `.storage/core.config_entries`
(bedroom-typed: Jaya Bedroom, Ziri Bedroom, Upstairs Guestroom [z2]; Master Bedroom [z1]; Guest Bedroom 1,
Guest Bedroom 1 Closet [z3, no zone_persons]).

**Anchor validation — PASS.** 09-24: fan off 01:31:04 → `jaya_3_presence` off 01:32:01; raw silence 02:02:54 →
02:56:56 (54 min); room occupied off 02:11:04; D1 tail 02:12:04 → 02:41:54; `hvac_occupied` off 02:42:07;
**zone_2 away 02:47**. 09-25: fan off 01:36:38 → `jaya_3_presence` off 01:37:12; Zigbee radar silent 01:23:04 →
02:25:42 (63 min); `hvac_occupied` off 02:04:57; **zone_2 away 02:09**. Jaya's phone in-suite 100 %, distance std
0.5 ft both nights.

### Per-room table

| Room (zone) | drops | returned ≤90 | stayed | stationary in-suite | stat → zone away | non-returning blips | BLE all-degraded |
|---|---|---|---|---|---|---|---|
| Jaya Bedroom (z2) | 17 | 14 | 3 | **12** | **8** | 0 | 7 (all = Jaya not_home / morning departure) |
| Ziri Bedroom (z2) | 6 | 0 | 5 (+1 censored) | 0 | 0 | 0 | 6 (Ziri `not_home` all window) |
| Upstairs Guestroom (z2) | 0 | – | – | – | – | – | – |
| Master Bedroom (z1) | 3 | 2 | 1 | 1 (2.6-min blip, house `away`) | 0 | 0 | 2 |
| Guest Bedroom 1 / Closet (z3) | 0 / 0 | – | – | – | – | – | – |
| **TOTAL** | **26** | **16** | **9** | **13** | **8** | **0 (0 %)** | 15 |

**Jaya still-sleeper episodes by house state** (stationary in-suite at drop):

| House state (hold table) | episodes | zone_2 went away | away duration (min) | return gaps (min) |
|---|---|---|---|---|
| `sleep` (night table, D8 30 min) — **Piece A scope** | **6** (09-20 01:58, 04:58; 09-21 01:33; 09-24 01:56, 02:42; 09-25 02:04) | **5** | 45.1, 50.1, 35.2, 6.0, 20.0 | 50.1, 55.6, 40.1, 5.0, 15.3, 24.9 → **median 32.5, max 55.6** |
| `home_day` (day table, 60 s) — 06:14–07:59 | 5 | 3 | 30.0, 15.1, 25.0 | 5.3, 30.0, 5.0, 25.0, 25.0 |
| `away` (house) | 1 | 0 | – | 0.1 |

### The plan's required numbers

| Number | Measured |
|---|---|
| `N_episodes` (night-table drops with stationary in-suite person) | **6 in 7.8 nights** (5 caused a zone_2 retreat) → above the <2 PARK line; Piece A proceeds |
| Median gap | **32.5 min** (sleep-state), max **55.6 min**; all 13 stationary episodes returned within 56 min. Needed extension ≈ gap + ≤5-min tick → a **60–90 min cap suffices; the 200-min / 4-discharge machinery is NOT warranted** |
| `N_episodes with ≥1 radar micro-blip in the gap` | **0 / 26 (0 %)** non-returning blips. Every raw blip inside a gap ENDED it |
| `N_episodes with BLE absent/degraded` | 15 / 26 all-degraded — every one is a person `not_home` / morning departure / Ziri away all week; **0 stationary episodes lost to BLE failure**. Night availability while home: area unknown/unavailable **jaya 1 %, ezinne 1 %, oji 8 %** (ziri: 0 h home) |
| Distance units | **ft** (`unit_of_measurement: ft`, positive). Stationary episodes: std **0.4–1.3 ft**, range 2.0–7.5 ft → ≤3 ft std threshold has ~2× headroom; a range-based threshold would need ≥8 ft |
| Discrimination | **0 / 9 STAYED (genuine-exit) episodes were stationary in-suite; 13 / 13 stationary episodes returned** — the BLE predicate separated sleepers from exits perfectly on this sample |

### Findings that change the plan

1. **Corroborator (b) already exists in code — it is not NEW.** `_compute_hvac_occupied`
   (`hvac_zones.py:966-1035`) rides the room's grace-held `STATE_OCCUPIED`: a raw blip lifts room occupancy, a
   held room clears the tail (`source="held"`) and re-tails on the next fall; after release a rising edge re-arms
   (`source="edge"`). Measured: 09-24 room on 01:58:27 → `hvac_occupied` on 02:01:54; 09-25 room on 02:25:43 → on
   02:29:51. The failure mode is the ABSENCE of any blip for ≥ D8 + room grace — which a blip-restart rule cannot
   touch. The plan's Prior-art line "NEW — radar micro-blip tail-restart" should read REUSED/EXISTING.
2. **The D1 producer only runs on the decision cycle** (`update_room_conditions` called at `hvac.py:1254`,
   `hvac.py:1647`), so `hvac_occupied` lags the room by 25 s–4 min. Relevant to the W2 fast path (§9d), not to
   Piece A.
3. **Bermuda flaps Bedroom↔Bathroom continuously while Jaya sleeps.** Bedroom-only share of the six sleep gaps:
   0.48, 0.20, 0.88, 0.24, **0.07** (09-24 02:42 anchor), 0.21 — 12–137 area flips per gap. The predicate MUST use
   the suite union. **A4's discriminating criterion "BLE showing the sibling bathroom only … → NO extension" would
   reject the anchor episode** (93 % "Jaya Bathroom"). Replace it with a discriminator that uses distance variance or
   an out-of-suite area (e.g. hallway/other room), not "bathroom only".
4. **Morning residual outside Piece A scope:** 3 zone_2 retreats (15–30 min) with Jaya stationary in-suite
   during `home_day` 06:14–07:00 (day table, 60-s bedroom hold). A5 scopes Piece A to `home_night`; these stay
   uncovered. Candidate for a separate card if the operator cares about early-morning comfort.
5. Master Bedroom and guest bedrooms show no still-sleeper problem (3 / 0 / 0 night drops, none a sleeper
   retreat). The problem is **Jaya-specific** on this data (Ziri was away all window — Ziri's room is unmeasured
   for sleepers).

### Recommendation (per A1 decision rule)

- **Corroborator: (a) BLE stationary in-suite ONLY, suite-union area, std ≤ 3 ft.** Do **not** add (b): blips
  appear in **0 %** of drop gaps (rule threshold 50 %), and blip-restart is existing producer behaviour anyway.
  Option (c) is dominated.
- **Cap:** `HVAC_NIGHT_STILL_SLEEPER_MAX_EXTENSION_MIN = 90` (measured max need ≈ 61 min incl. one tick; 90 gives
  margin and matches the probe horizon). Dwell: Jaya is in-suite well before every drop; a 10-min dwell is safe.
- **Marginal-benefit pushback (surface to the operator before building):** the simplest version is a **knob
  turn with zero code** — raise Jaya Bedroom's existing per-room `CONF_HVAC_VACANCY_HOLD_NIGHT` (live
  `hvac_vacancy_hold_night: 1800`) to 5400 s (legal: options-flow range 0–7200 s, `config_flow.py:11739`). On the measured data it captures all 5 sleep-state retreats, and
  its cost — conditioning zone_2 up to 60 extra min after a genuine night exit — measured **zero occurrences** in
  7.8 nights (every genuine Jaya exit was ≥ 07:30 on the day table, where the night hold does not apply;
  `FAN_TRUST_STATES = (home_night, sleep, waking)` `hvac_const.py:881`). Piece A's margin over the knob is
  BLE discrimination of night exits that did not happen in the sample, plus generality to other bedrooms that
  showed no problem. Recommendation: apply the knob turn now (operator decision; zone-scoped by construction, so it
  honours "never anyone home"), and PARK the Piece A build with revival trigger "a genuine night exit held a zone
  > 30 min, OR a second bedroom shows sleeper retreats in a re-probe". If the operator prefers the build anyway,
  build (a) only, with the cap above.
