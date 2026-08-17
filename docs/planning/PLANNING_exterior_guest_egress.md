# PLANNING — EXTERIOR-GUEST-EGRESS-1

**Kanban card:** `EXTERIOR-GUEST-EGRESS-1`
**Thread:** presence
**Split from:** `CENSUS-DECAY-SEPARATION-1` P8 (2026-08-16 operator ruling)
**Author:** oji@outlook.com
**Date:** 2026-08-16

---

## Institutional context verified

### Grep-verified prior art (REUSED vs NEW for every proposed addition)

**REUSED — no new machinery proposed for these:**

- **`EgressDirectionTracker`** — `transit_validator.py:830-1140`. Already resolves entry/exit/ambiguous with correct time-windowed correlation, dedup by camera stem (`:1063-1073`), multi-platform confidence boost (`:1093-1099`). REUSE as the sole producer of the direction verdict.
- **`ura_person_egress_event` HA-bus event** — fired at `transit_validator.py:1102-1108`. Payload today: `{direction, egress_camera, timestamp, person_id=None, confidence}`. REUSE the event; augment the payload (SEE NEW below).
- **`database.log_entry_exit_event`** — `database.py:3709-3734`. Already accepts `person_id: Optional[str]`. REUSE. No DDL change needed.
- **`_guest_room_gate_armed`** — `presence.py:4830-4859`. REUSE as the sole GUEST arm gate; this cycle adds a NEW *modifier* (dwell shortening / confidence contribution), never a new arm.
- **`_guest_gate_armed`** (unidentified path) — `presence.py:4861+`. REUSE unchanged.
- **`unid_gate_armed or guest_room_gate_armed`** — `presence.py:5391, 5399`. REUSE unchanged; **this cycle MUST NOT add a third `or` term.** That would be the operator-forbidden solo-arm.
- **`EXTERIOR_ADJACENCY_GRAPH`** — `const.py:1742`. REUSE.
- **`EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS`** — `const.py:1828`. REUSE; this is the canonical "an exterior track just approached a door" surface.
- **`ExteriorTrackLinker.classify()`** — `exterior_track_linker.py:705-735`. REUSE; `approach` classification is the corroboration substrate.
- **`ExteriorTrack.sub_label`** — `exterior_track_linker.py:521-551`. REUSE as-is; this is Frigate's promoted sub_label (identity in Frigate's namespace, not URA's). **Do NOT conflate with `person_id`.**
- **`transit_validator._camera_sightings`** / face-recognition path — `transit_validator.py:540-568`, `_face_recognition_enabled` gated on `CONF_FACE_RECOGNITION_ENABLED`. This IS URA's local-only identity channel (Frigate + Protect person_id). REUSE as the identity source.
- **`CONF_FACE_RECOGNITION_ENABLED`** — REUSE as the master identity kill-switch; if OFF, this cycle is a no-op.
- **`EGRESS_ENTRY_WINDOW_SECONDS=45` / `EGRESS_EXIT_WINDOW_SECONDS=30` / `EGRESS_AMBIGUOUS_COOLDOWN_SECONDS=60`** — `const.py:2119-2121`. REUSE.
- **`sensor.py:4136,4214,4275,4323`** — four existing consumers of `ura_person_egress_event`. REUSE; verify additive payload keys don't break them (they use `.get()` — additive is safe).

**NEW — proposed additions, each with justification:**

- **`person_id` populated on `ura_person_egress_event`** (currently hard-coded `None` at `transit_validator.py:1106` and `:1121`). NEW behavior on an EXISTING field. Justification: this IS the cycle. Producer: a new helper `_resolve_identity_at_egress(egress_camera_id, egress_timestamp)` that queries `self._camera_sightings` (or the Protect equivalent) within the ENTRY window and returns `person_id | "unidentified" | None`. Local-only sources; llmvision excluded (operator ruling).
- **`identity_source` field on the event** (NEW payload key). Values: `"frigate_sub_label" | "protect_face" | "none"`. Justification: consumer needs to know provenance to weight trust; also unblocks the discriminating live check (see §4). Additive — existing consumers unaffected.
- **`GUEST_EGRESS_CORROB_WINDOW_S`** — rung 1 (module const). NEW because no equivalent guest-corroboration window exists; MUST NOT be reused as EGRESS_ENTRY_WINDOW (different semantic — one is "when is a match still a match", the other is "how long does an unknown-entry stay corroborative for the guest arm").
- **`GUEST_EGRESS_CORROB_DWELL_REDUCTION_S`** — rung 1 (module const). NEW. Amount by which guest-room dwell threshold is shortened when a same-window unidentified-entry egress event is present. Bounded and reviewable.
- **`switch.ura_presence_exterior_guest_corroboration_enabled`** — rung 3 (entity). NEW kill switch, default OFF for the shipping cycle; flipping ON is the operator opt-in AFTER live probe and Tier-3 review pass. Uses the existing switch-persistence machinery consistent with `_guest_detection_enabled` (`presence.py:4842`).

### Prior planning docs consulted

- `docs/planning/RESEARCH_census_vs_guest_separation.md` — separation-of-concerns ruling; this cycle is the exterior-only surgical piece of P8. Read.
- `docs/planning/RESEARCH_guest_actuation_and_census.md` — census-vs-guest read; scoped.
- `docs/PLANNING_v3.5.2_CYCLE_6.md:428-551` — original egress-tracker design context (per card ref). Referenced.
- `docs/planning/PLANNING_circling_severity.md`, `PLANNING_circling_label_transition_dispatch.md`, `AUDIT_memory_handbuild_compactor_exterior_track.md` — sibling exterior work (EXTERIOR-DWELL-LOITER-1); disjoint from this cycle (loiter is a different security signal, no code overlap).
- `docs/planning/PLANNING_presence_pair_guest_latch_veto_gap.md` (untracked in git status) — cross-reference for latched-guest semantics; NOT touched.

### Memory bodies pulled

- `project_presence_guest_latch_and_veto_gap.md` — GUEST latch shipped v5.16.0; this cycle preserves those semantics (no change to latch state machine).
- `project_v5_5_0_inclement_weather_shipped.md` — pattern for shipping a dormant capability behind a config gate.
- `feedback_hollow_test_anchors.md`, `feedback_falsify_before_asserting.md`, `feedback_mutation_verification_pycache_staleness.md` — Tier-3 test-authority requirements.
- `feedback_marginal_benefit_pushback.md` — enforces §7 below.
- `feedback_measure_before_build.md` — enforces §5 probe gate.
- `project_frigate_ghost_evidence_chain.md` — Frigate identity/sub_label evidence patterns; consult on producer noise.

### Design docs read

- No `docs/Coordinator/presence.md` file present in this checkout (grep confirms absent). Read `presence.py:4820-5410` and `:5780-5945` end-to-end for guest-gate wiring instead.

### Code surveyed end-to-end during scoping

- `custom_components/universal_room_automation/transit_validator.py` — `EgressDirectionTracker` (:829-1200), `TransitValidator._face_recognition_enabled` path (:194-568).
- `custom_components/universal_room_automation/exterior_track_linker.py` — `_link_or_create` (:400-551), `_close_track` / `_write_episode` (:633-702), `classify` (:705-735), `census_counts` (:766-777).
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — guest gates (:4820-5000), arm composition (:5377-5411), transition sites (:5780-5945).
- `custom_components/universal_room_automation/database.py` — `log_entry_exit_event` (:3709-3734), `get_entry_exit_events_since` (:3736+).
- `custom_components/universal_room_automation/sensor.py` — four egress-event consumers (:4120-4330).
- `custom_components/universal_room_automation/const.py` — egress windows, adjacency graph, egress-adjacent list, NM severity coupling.

---

## Tier classification — **Tier 3** (agree with operator assessment)

Four independent triggers fire:

1. **First-ever exterior → house-state trust edge.** Every other coupling today is one-way (guest DEMOTES exterior severity via `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` at `const.py:1617`). Reversing that direction is a new architectural surface, per the Tier-3 "shared primitive consumed by many decision sites" trigger.
2. **Identity is threaded through a state machine.** `person_id` on `ura_person_egress_event` will be read by (at minimum) the guest gate, four existing sensor consumers, the DB log, and any future consumer. Bug Class #53 (computed-but-not-consumed) applies inversely: exactly-one wrong path admits a phantom identity.
3. **Cost-AND-safety-impacting.** GUEST state changes NM routing, alert severities, HVAC posture — a false-guest costs comfort AND security posture; a missed guest costs the corroboration this cycle is designed to add.
4. **Independent operator knobs interact.** `CONF_FACE_RECOGNITION_ENABLED` × `_guest_detection_enabled` × new corroboration switch × per-guest-room `threshold_min` × dwell-reduction constant. Combinatorial. Tier-3 config-boundary testing required.

**Standing policy also applies:** trust-hierarchy ripple change (presence ↔ NM ↔ security) — Tier 2-DB / three-review protocol is the *floor*; Tier 3 (four framings incl. adversarial completeness) is the correct bar.

**Reviews required:** A=local correctness (identity resolution arithmetic + payload shape + kill-switch inertness), B=state-machine / integration (guest arm composition unchanged on no-op path, latch semantics preserved, restart-safety of the corroboration window), C=test authority via real per-site source mutation (bypass the identity resolver → a SPECIFIC test must fail; bypass the corroboration gate → a SPECIFIC test must fail), D=adversarial completeness (state the invariants below and BREAK them; re-enumerate ALL arm paths in `presence.py` including pre-existing code, not just the diff).

**Operator checkpoint required BEFORE deploy** (Tier-3 rule).

---

## Falsifiable invariants

**INV-1 (primary):** Under no reachable path may an exterior signal — including an `ura_person_egress_event` with `direction=entry` and *any* `person_id` value including `None`, and including any `ExteriorTrackLinker` classification (`approach`, `circling`, or promoted-identity) — cause a transition INTO `HouseState.GUEST`. Falsifier: inject an `ura_person_egress_event` with `direction=entry, person_id="unidentified", confidence=0.9` while both `_guest_room_gate_armed` and `_guest_gate_armed` return `False`; assert house_state does NOT transition to GUEST across ≥2 evaluation ticks.

**INV-2 (kill-switch inertness):** With `switch.ura_presence_exterior_guest_corroboration_enabled = OFF` (default this cycle), the byte-shape and timing of `_guest_room_gate_armed`'s return value and the arm-composition expression at `presence.py:5391/5399` MUST be identical to their pre-cycle behavior for ALL inputs. Falsifier: run the existing guest-gate suite with switch OFF; any behavioral delta = fail.

**INV-3 (identity provenance):** Every `ura_person_egress_event` with a non-`None` `person_id` MUST carry a non-`"none"` `identity_source` field, AND that `identity_source` MUST be one of the two local-only channels (`frigate_sub_label`, `protect_face`). Falsifier: monkeypatch the resolver to return `("alice", "llmvision")`; assert the event either drops the person_id or refuses to fire.

**INV-4 (single-path corroboration):** The corroboration mechanism, if enabled, MUST be expressible as EITHER (a) shortening `threshold_min` for a specific already-armed guest room OR (b) contributing to `census_confidence` used by the existing unid gate — NEVER as an independent third arm. Falsifier: grep the diff for a new `guest_armed = ... or exterior_corroborated`; any such introduction = fail.

**INV-5 (restart safety):** The corroboration window is bounded by `GUEST_EGRESS_CORROB_WINDOW_S` and is NOT persisted across restart. After HA restart, no in-flight corroboration credit survives. Falsifier: fire an egress event at T; simulate restart at T+5s; verify no corroboration credit is available at T+10s.

**Note on INV design (from `feedback_falsify_before_asserting.md`):** INV-2 is deliberately *behavioral* not *structural* — a real defect (silent import of new branch that always short-circuits) would satisfy a "no new `or`" grep but violate the behavioral variant. INV-1 similarly demands a live counter-example, not just a code read.

---

## Deliverables

### D0 — Probe (must run BEFORE any build code lands)

**Read-only recorder + DB probe.** Deliverable is a committed report `docs/planning/PROBE_exterior_guest_egress.md` with numbers, decision, and go/no-go call. See §5 for the exact script spec.

**Acceptance criteria:**
- **Verify:** report exists on develop with all four numbered probe outputs (see §5) and a stated go/no-go.
- **Test:** N/A (probe is one-shot, not a test fixture — but the fixtures for D1-D2 ARE the observed sightings/tracks from the probe window, hand-built per `feedback_measure_before_build.md`).
- **Live:** N/A (probe IS the live read).

### D1 — Populate `person_id` on the egress event (identity plumbing only, no house-state coupling)

Replace the hard-coded `None` at `transit_validator.py:1106` and `:1121` with a call to a new helper `_resolve_identity_at_egress(egress_camera_id, egress_timestamp)` that:
- Reads `self._camera_sightings` (populated by the existing face-recognition path, `:194+`) within `[egress_timestamp - EGRESS_ENTRY_WINDOW_SECONDS, egress_timestamp + EGRESS_ENTRY_WINDOW_SECONDS]`.
- Filters to sightings whose camera stem matches the egress camera stem OR any camera in `EXTERIOR_ADJACENCY_GRAPH[egress_camera_stem]`.
- Returns `(person_id, identity_source)` where `person_id ∈ {<known_id>, "unidentified", None}` and `identity_source ∈ {"frigate_sub_label", "protect_face", "none"}`.
- Returns `(None, "none")` if `self._face_recognition_enabled` is False.
- Local-only: hard-coded set of allowed identity source tags; llmvision explicitly not in that set.

Add `identity_source` to the event payload.

**Acceptance criteria:**
- **Verify:** `git grep 'person_id=None' custom_components/universal_room_automation/transit_validator.py` returns ZERO matches inside `_resolve_direction` after the change; the two prior sites now pass through the resolver.
- **Verify:** `git grep '"llmvision"' custom_components/universal_room_automation/transit_validator.py` returns ZERO matches (source allow-list check).
- **Sensor:** `sensor.today_entries` (`sensor.py:4136`) `entries` attribute shows entries with `person_id != "unidentified"` when a face was resolved within the window.
- **Test:** `test_egress_identity_resolves_from_recent_sighting`, `test_egress_identity_unidentified_when_face_rec_off`, `test_egress_identity_rejects_non_allowlisted_source`, `test_egress_identity_source_field_present_on_all_events`.
- **Live (discriminating):** After a resident walks through a covered egress and their face is resolved locally, the next entry in `person_entry_exit_events` (queried via ura-sqlite) has `person_id` = the resident's URA person_id. Under the plausible failure "resolver silently returns Frigate sub_label instead of URA person_id", the row would instead carry the Frigate label (which is a different namespace and won't match `person_registry` IDs) — check the value belongs to `person_registry`, not merely non-null.

### D2 — Corroboration wire-in (behind default-OFF switch)

Add `switch.ura_presence_exterior_guest_corroboration_enabled` (default OFF). When ON AND a `ura_person_egress_event` fires with `direction=entry, person_id="unidentified"` within `GUEST_EGRESS_CORROB_WINDOW_S` of an already-armed guest-room first_seen, the guest-room dwell requirement is shortened by `GUEST_EGRESS_CORROB_DWELL_REDUCTION_S`.

**Explicit non-mechanism:** the corroboration does NOT add an `or` term to `guest_armed`. It modifies `_guest_room_gate_armed`'s dwell arithmetic for a specific room whose `first_seen` is already set. If `first_seen is None`, no corroboration credit applies — the guest-room gate remains the sole primary arm.

**Acceptance criteria:**
- **Verify:** grep `presence.py:5391,5399` — the arm-composition expression is byte-identical to pre-cycle.
- **Verify:** mutation drill (Review C): comment-out the corroboration branch in `_guest_room_gate_armed` — `test_corroboration_shortens_dwell_when_switch_on` MUST fail; `test_corroboration_inert_when_switch_off` MUST still pass. Restore.
- **Sensor:** a new diagnostic attribute on the existing guest-diagnostic sensor exposes `last_corroboration_credit_room`, `last_corroboration_credit_ts`, `corroboration_switch_state` (name reused from existing diagnostics conventions — verify at build time and REUSE the sensor, do not add a new one).
- **Test:** `test_no_corroboration_without_armed_room` (INV-1 falsifier), `test_switch_off_is_inert` (INV-2 falsifier), `test_corroboration_expires_at_window_boundary` (INV-5 falsifier), `test_corroboration_does_not_create_third_arm` (grep + behavioral).
- **Live (discriminating):** with switch ON, when a guest is admitted through a covered egress and dwells in a guest room, `first_seen`-to-GUEST latency is < `threshold_min - DWELL_REDUCTION_S` (observable in the diagnostic sensor + `ura_house_state` history). Under the plausible failure "corroboration fires but from any interior sighting (not egress-specific)", latency would shrink even when NO recent egress event exists — the discriminating check is to also confirm `last_corroboration_credit_ts` is within `GUEST_EGRESS_CORROB_WINDOW_S` of a `person_entry_exit_events` row.

### D3 (conditional — only if probe passes AND D2 has ≥2 weeks organic time)

Track-linker → egress hand-off (approach-classified exterior track terminates near an egress camera → boosts D2's confidence). **Deferred by default.** Rationale: marginal benefit (see §7) is a small confidence bump on top of D2's already-narrow effect; the ingredient risk (cross-coordinator write from linker into transit validator) is categorically new. Carded separately if D2 organic evidence justifies revisit.

**No debt:** D3 is CARDED as `EXTERIOR-GUEST-EGRESS-TRACK-HANDOFF-1` (pre-planning) with the trigger "revisit if D2 live shows ≥N/week guest admissions where the resident face was NOT resolvable and corroboration was the load-bearing signal". Not silently dropped.

---

## Producer AND Consumer check (mandatory)

### Value: `person_id` on `ura_person_egress_event`

**PRODUCER:**
- Computed by NEW `_resolve_identity_at_egress` in `EgressDirectionTracker`.
- Two derivations exist: (a) Frigate `sub_label` promoted after 2 hops on the exterior linker (`exterior_track_linker.py:521-551`) — a DIFFERENT identity namespace, NOT reused; (b) URA `person_id` from `TransitValidator._camera_sightings` (`transit_validator.py:540-568`) — this IS the one used.
- Which wins: (b), unconditionally. (a) is Frigate's own label space, not `person_registry` IDs — mixing them silently would produce phantom identities.
- Dependencies: `TransitValidator` running, `_face_recognition_enabled = True`, at least one Frigate face-detect or Protect face-detect entity live, `_camera_sightings` populated within the window.
- **Health check today (must run in probe):** how many entries in `_camera_sightings` in the last 7 days? Is `_face_recognition_enabled` True in live config? Frigate face-recognition addon status? (per `project_frigate_ghost_evidence_chain.md`, Frigate face detection has been noisy historically — probe measures ACTUAL fresh-face rate, not assumed).

**CONSUMER + call-site check:**
- `sensor.py:4136,4214,4275,4323` — display + count sensors. Trust-decision: NO (display only). Additive payload keys safe.
- `database.log_entry_exit_event` — persist. Trust-decision: no (log only). Accepts nullable `person_id` today.
- NEW: `_guest_room_gate_armed` corroboration branch — TRUST-DECISION. Reads `person_id` only to verify `== "unidentified"`; treats known-face entries as anti-corroboration (a known resident coming in is NOT guest evidence). This asymmetry is load-bearing and must be tested.

### Value: `direction` on the same event (existing, verify no regression)

Producer unchanged (`_resolve_direction`). Consumer set expands by one (the new corroboration branch). Verify existing consumers still see identical direction values on the pre-cycle test suite.

### Value: `_guest_room_state[room].first_seen` (existing)

Producer: unchanged (`_maybe_arm_guest_room`, `_maybe_disarm_guest_room` in presence.py). Consumer expands: new corroboration branch READS `first_seen` and modifies the dwell comparison. Trust-decision: yes. Must be UTC-aware (Bug Class #11, per existing docstring `presence.py:4838`).

---

## Numbers get knobs (rung + rationale)

| Name | Value | Rung | Rationale |
|---|---:|---|---|
| `GUEST_EGRESS_CORROB_WINDOW_S` | 90 (proposal, probe-informed) | 1 (module const) | Behavioral bound on trust-hierarchy edge; changing it should REQUIRE review. |
| `GUEST_EGRESS_CORROB_DWELL_REDUCTION_S` | 300 (proposal) | 1 (module const) | Directly attenuates safety-relevant threshold; review-gated. Bounded s.t. `threshold_min*60 - DWELL_REDUCTION_S > 60` (INV-4 arithmetic; assert in const load). |
| `switch.ura_presence_exterior_guest_corroboration_enabled` | OFF | 3 (entity) | Operator kill switch; ship OFF, flip ON post-review. Kill-switch semantics documented on the switch. |
| `EGRESS_ENTRY_WINDOW_SECONDS` | 45 (existing) | 1 | REUSED unchanged. Do NOT tune in this cycle. |
| `identity_source` allow-list | `{"frigate_sub_label", "protect_face"}` | 1 (module const set) | Security boundary — llmvision exclusion; review-gated set. |

Kill switch: setting `switch.ura_presence_exterior_guest_corroboration_enabled = OFF` MUST make the cycle byte-behavior-inert (INV-2). This is the fire-axe.

---

## Non-goals (explicit)

1. **NOT a solo exterior→GUEST arm.** No new `or` term in `guest_armed`. If a reviewer sees one, that is a CRITICAL finding.
2. **NOT llmvision, NOT cloud face recognition, NOT household reference photos leaving LAN.** Identity source allow-list is enforced in code.
3. **NOT a change to `_guest_gate_armed` (unidentified path).** Only `_guest_room_gate_armed` gains a corroboration modifier.
4. **NOT touching `ExteriorTrackLinker` in this cycle** (D3 is deferred/carded).
5. **NOT a schema migration.** `person_entry_exit_events.person_id` is already nullable text.
6. **NOT changing `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`.** The one-way severity demotion stays; this cycle is orthogonal.
7. **NOT persisting corroboration credit across restart.** In-memory only; INV-5.
8. **NOT `_face_recognition_enabled` default flip.** Ship whatever the operator has today; this cycle documents the dependency, doesn't force it.

---

## §5 Probe-first gate (MUST run before D1 build dispatch)

**Read-only script, single-shot, over existing recorder + URA DB. NO code writes. Ship over `ssh ha`.**

**Probe outputs required:**

1. **Egress-event fire rate:** `SELECT date(timestamp), COUNT(*), direction FROM person_entry_exit_events WHERE timestamp > date('now', '-14 days') GROUP BY 1, direction`. Report daily fire counts and direction distribution.
2. **Confidence distribution:** `SELECT confidence, COUNT(*) FROM person_entry_exit_events WHERE timestamp > date('now', '-14 days') GROUP BY 1`. Report the 0.3/0.4/0.8/0.9 histogram.
3. **Face-resolution feasibility:** count of `memory_episodes` rows with `episode_type='face_seen'` (or equivalent camera-sighting record) in the past 14 days, broken down by camera stem. Cross-reference with egress camera stems. Report % of egress events for which a face-sighting exists within ±45s.
4. **`approach`-classified track termination:** `SELECT COUNT(*) FROM memory_episodes WHERE episode_type='exterior_track' AND json_extract(attrs,'$.classification')='approach' AND ...` — how often does an approach-classified track's last hop land on an `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` camera, and how often is that within 60s of a subsequent `ura_person_egress_event(direction=entry)`?

**Go/no-go thresholds (state these, honor them):**

- **Go D1 (identity plumbing)** iff output (3) shows ≥30% of `direction=entry` events have an in-window face-sighting. Below that, `person_id` will be `None` for most events and D1 delivers little value — recommend deferring D1 pending Frigate face-tuning.
- **Go D2 (corroboration wire-in)** iff, IN ADDITION, output (1) shows ≥3 `direction=entry` events/week on average (below that, corroboration will fire too rarely to be a useful signal — the operator would legitimately prefer to lower `threshold_min` directly, which is a rung-3 knob turn worth $0 of code).
- **NO-GO on D3** unconditionally this cycle (see §7); track linker hand-off is a separate cycle with its own probe on output (4).

**Honest outcome recognition:** if arrivals-via-egress are too rare or too low-confidence to be a useful corroborator, the plan is to NOT build the hand-off. Say so in the probe report, park the plan, and card the trigger to revisit (e.g. "revisit after Frigate face-rec tune-up ships").

Probe report committed as `docs/planning/PROBE_exterior_guest_egress.md` on develop before D1 build dispatch. Tier-3 plan review verifies the probe report exists and its numbers support the go/no-go call before the review clears.

---

## §7 Marginal-benefit decomposition & recommendation

**Simplest possible version — D1 alone (identity on the egress event, no house-state coupling):**
- Cost: ~40 LoC + one module const set + tests. Tier 2 review would suffice for D1 in isolation (no cross-coordinator edge).
- Benefit: the four existing sensor consumers stop reporting `"unidentified"` for every entry regardless of who actually came in. The DB log becomes attributable. Downstream systems (dashboards, future cycles like CENSUS-DEDUP-REPAIR-1) get identity for free.

**Fancier version — D1 + D2 (add the corroboration wire-in):**
- Marginal cost over D1: cross-coordinator trust edge (Tier 3, four framing-disjoint reviews, operator checkpoint), the switch entity, the arithmetic modifier in `_guest_room_gate_armed`, ~5 additional tests including mutation drills, restart-safety proof.
- Marginal benefit: modestly faster GUEST admission for genuinely unknown persons entering through covered doors, and only when a guest room ALSO fires first_seen. In wall-clock terms: `GUEST_EGRESS_CORROB_DWELL_REDUCTION_S` = 300s = 5 minutes off a 30-minute dwell in a hopefully-rare event.

**Fanciest version — D1 + D2 + D3 (track linker hand-off):**
- Marginal cost over D2: NEW writer from `ExteriorTrackLinker` into transit-validator/presence surface, new identity-crosswalk between Frigate sub_label namespace and URA person_id namespace, combinatorial explosion with the linker's own kill switches.
- Marginal benefit: a small additional confidence bump on top of D2, only for the subset of guest admissions where an approach-classified track was observable and terminated at the right camera.

**Recommendation:** **Ship D1 alone in this cycle.** D2 and D3 both fail the marginal-benefit test *until* D1 is live and the operator has observed identity resolution working organically. Specifically:

1. D1 captures the LARGE component of the benefit (making every entry attributable, unlocking downstream cycles, closing the "we can't tell who came in" gap the card describes as load-bearing).
2. D2's marginal benefit is ~5 minutes of dwell reduction in a rare event; its marginal ingredient risk is the FIRST exterior→house-state trust edge in the codebase — categorically risky per the standing Tier-3 rule. This is exactly the "elaborate spec that was fun to write is a sunk-cost trap" pattern.
3. **Park D2** in a carded follow-up (`EXTERIOR-GUEST-EGRESS-CORROB-2`) with the evidence trigger: "revisit if post-D1 data shows ≥N/week guest admissions where dwell latency was the operator-observable pain, AND face-resolution rate is high enough that the anti-corroboration asymmetry (known faces = NOT guest) does real work."
4. D3 stays parked as previously stated.

**With this recommendation, the cycle drops from Tier 3 to Tier 2** (no house-state trust edge; just identity plumbing on an existing event with additive payload). If the operator overrides and wants D1+D2 in one cycle, Tier 3 protocol applies as specified.

**Operator decision requested at plan-review:** ship D1-only (Tier 2), or ship D1+D2 (Tier 3 with checkpoint)?

---

## Test plan summary (per Tier-3 §C authority)

Every test cited in acceptance criteria must survive the mutation drill: comment/neuter the production site → the named test MUST fail with a specific assertion, not a generic import error. Reviewer C runs the drills per-site (NOT aggregate monkeypatch), with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared between mutations (per `feedback_mutation_verification_pycache_staleness.md`).

Anchor list (each demands a mutation-verified behavioral test):
- Identity resolver returns the URA person_id, not the Frigate sub_label (D1).
- Identity source allow-list rejects llmvision (D1).
- Event payload includes `identity_source` on every fire path (D1).
- `person_id=None` when face rec is disabled (D1).
- Corroboration is inert with switch OFF (D2 / INV-2).
- Corroboration does NOT arm GUEST without prior `first_seen` (D2 / INV-1).
- Corroboration window is bounded and non-persistent (D2 / INV-5).
- Grep + behavioral: no third `or` term in guest arm (D2 / INV-4).
