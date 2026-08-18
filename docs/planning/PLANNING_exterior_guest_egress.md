# PLANNING — EXTERIOR-GUEST-EGRESS-1 (rev 2, FACE-INDEPENDENT rescope)

**Kanban card:** `EXTERIOR-GUEST-EGRESS-1`
**Thread:** presence
**Split from:** `CENSUS-DECAY-SEPARATION-1` P8 (2026-08-16 operator ruling)
**Author:** oji@outlook.com
**Rev:** 2 — 2026-08-18 (operator ruling: *"Build face independent"*)
**Prior rev:** rev 1 (2026-08-16) — proposed D1 (populate `person_id` on egress) + D2 (guest corroboration behind switch) + parked D3 (track-linker→egress hand-off). Rev-1 D1/D2 are NOW PARKED per measured evidence (see below); rev-2 promotes the ex-D3 face-independent hand-off to the sole cycle deliverable.

**Parked (fast-follow card, NOT this cycle):** `EXTERIOR-GUEST-FACE-FASTFOLLOW-1` — Protect Alarm Manager webhook path to bring NVR-side `recognized_person_name` into HA. Revisit trigger: *"named face recognition at door/exterior cameras ≥30% in a re-run of PROBE Q2/Q3."*

---

## Rev-2 rescope summary (why the face arm is dead-on-arrival right now)

Two probes committed 2026-08-17 / 2026-08-18:

- `docs/planning/PROBE_exterior_guest_egress.md` — Frigate leg. Combined `_2`-suffix face-rec at door/exterior cams, ±45s window: **~7.0%** coverage. 30% gate fails.
- `docs/planning/PROBE_protect_face_egress.md` — Protect leg. `unifiprotect` HA integration exposes **no** face-name entity (`event_type="face"` = detection only, no WHO). NVR *does* run recognition, but names cluster on the interior Family Room cam (276 detections, several named) and the Madrone G6 Entry cam sees ~10 detections / 0 names in 7.7 d. Consumable-in-HA face-name coverage at the door = **~0%**. Combined Frigate+Protect at egress = still **~7%**.
- The identity arm (rev-1 D1/D2) has no identity to weight. **PARKED** (fast-follow card above).

The face-independent signal, by contrast, is strong: **220 approach+person exterior tracks** in an ~11-day window, **207 (94%)** terminate at an egress-adjacent camera, ~18/day, produced by `ExteriorTrackLinker.classify()` with zero face-recognition dependency. This is what rev-2 wires — as a **contribution to `census_confidence` consumed by the EXISTING guest gate**, never as a third arm and never as a solo GUEST trigger.

---

## Institutional context verified

### Grep-verified prior art (REUSED vs NEW for every proposed addition)

**REUSED — no new machinery proposed for these:**

- **`ExteriorTrackLinker.classify()`** — `exterior_track_linker.py:705-735`. Emits `approach` when the track touches an operator-declared egress-adjacent camera. REUSE unchanged as the sole substrate for the corroboration signal.
- **`ExteriorTrackLinker._close_track()`** — `exterior_track_linker.py:633-652`. Called on track closure; already computes `classification` via `_write_episode` (`:659`). REUSE as the dispatch point (add a signal fire alongside the existing episode write; no behavioral change to the persistence path).
- **`ExteriorTrackLinker.find_owning_track()`** — `exterior_track_linker.py:823-855`. NOT touched by this cycle (no runtime read from the presence side — presence receives the closure signal, does not poll the linker).
- **`EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS`** — `const.py:1828` (probe cites `:1859` — actual const line; verify at build time). REUSE as the "last hop is a door" membership test.
- **`EXTERIOR_ADJACENCY_GRAPH`** — `const.py:1742`. Not required for this cycle (we do not walk adjacency; only test membership of last hop). Listed here to preclude accidental duplication.
- **`SIGNAL_CENSUS_UPDATED`** — `domain_coordinators/signals.py:18`, produced at `camera_census.py:1248-1275`, consumed at `presence.py:4322-4379` (`_handle_census_update`). REUSE the **consumer wiring**. The rev-2 cycle does NOT rewrite the published `confidence` field on this payload — see §Producer/Consumer for why the injection is scoped to the guest gate, not the shared payload.
- **`self._census_confidence`** — `presence.py:1616` (init), `:4358` (assign), `:5066/5097` (consumed by `_guest_gate_armed` Guard 2). REUSE unchanged. The nudge computes an *effective* confidence LOCALLY inside `_guest_gate_armed` — the attribute itself is not mutated.
- **`_guest_gate_armed`** — `presence.py:5063-5141`. REUSE. Injection is a one-line change inside Guard 2 (`census_confidence` → `self._effective_guest_confidence(census_confidence, now)`). Guards 1 (existence) and 3 (persistence) are UNTOUCHED.
- **`_guest_room_gate_armed`** — `presence.py:4830-4859`. NOT touched by rev-2. (Rev-1 D2 proposed dwell-shortening here; parked with rev-1 D1/D2.)
- **Arm-composition expression** at `presence.py:5391, 5399` (`unid_gate_armed or guest_room_gate_armed`) — REUSE unchanged. **This cycle MUST NOT add a third `or` term.**
- **`_guest_detection_enabled`** kill-switch (`presence.py:4842`, `:5084`) — REUSE as the master OFF path; the corroboration path inherits it (disabled guest detection ⇒ corroboration also inert regardless of the new switch).
- **`CENSUS_CONFIDENCE_{NONE,LOW,MEDIUM,HIGH}`** — `const.py:1426-1429`. REUSE as the effective-confidence codomain (the uplift stays within this 4-value ladder; never invents a new level).
- **`_confidence_at_least`** — `presence.py` (used at `:5097`). REUSE as the comparison operator on the *effective* value — no change to its arithmetic.
- **`ExteriorTrack` fields (`hops`, `cameras`, `identified`, `label`)** — `exterior_track_linker.py:521+`. REUSE read-only.
- **Switch persistence machinery** — `_guest_detection_enabled`-style pattern (`presence.py:4842`). REUSE for the new kill-switch entity.
- **`ura_person_egress_event`** — `transit_validator.py:1102-1108`. NOT consumed by this cycle. (Rev-1 D1/D2 depended on it; rev-2 does not — the signal source is the exterior track linker, not the transit validator.)

**NEW — proposed additions, each with justification:**

- **`SIGNAL_EXTERIOR_APPROACH_EGRESS`** (new dispatcher signal) — NEW. Justification: no existing signal fires *only* when a person track closes with `classification=approach` AND last hop ∈ egress-adjacent set. The nearest is the memory-episode write inside `_write_episode`, which is a DB-persist side effect, not a subscribable event; polling the DB from presence would be architecturally wrong. Fires at `_close_track` next to the existing `async_create_task(self._write_episode(track))` call (`exterior_track_linker.py:646`). Payload: `{"camera": <last_hop>, "track_id": <id>, "closed_at": <utc_iso>, "camera_count": <int>, "duration_s": <float>}`. Additive-only; no existing consumer.
- **`PresenceCoordinator._on_approach_egress(payload)`** (new @callback) — NEW. Subscribes to `SIGNAL_EXTERIOR_APPROACH_EGRESS` in `async_added_to_hass`. Records `self._last_approach_egress_ts: datetime | None` (in-memory, NOT persisted across restart per INV-5) and increments a diagnostic counter. Does NOT trigger inference on its own — the guest gate re-evaluates on the NEXT census tick (or on the existing persistence recheck timer). Rationale: we do not want a bare exterior signal to cause a house-state re-tick; we want it to *modulate* an already-in-progress guest-gate evaluation driven by interior evidence.
- **`PresenceCoordinator._effective_guest_confidence(census_confidence, now)`** (new helper) — NEW. Returns `census_confidence` unchanged if the corroboration switch is OFF, if `_last_approach_egress_ts` is None, if `(now - _last_approach_egress_ts).total_seconds() > EXTERIOR_APPROACH_CORROB_WINDOW_S`, OR if `_guest_detection_enabled` is False. Otherwise returns `census_confidence` raised by AT MOST one ladder step (`none→low`, `low→medium`, `medium→high`; `high→high`). Single-step-only is a hard invariant.
- **`switch.ura_presence_exterior_approach_corroboration_enabled`** — rung 3 entity, default OFF. NEW. Kill switch; ship OFF, flip ON post-Tier-3 checkpoint.
- **`EXTERIOR_APPROACH_CORROB_WINDOW_S`** — rung 1 module const. NEW. Bounded time window for the nudge (proposal: 180s; probe shows 60s co-fire cadence between track closure and downstream census re-count; 180s covers restart of a census tick + inference).
- **`EXTERIOR_APPROACH_CORROB_MAX_STEPS`** — rung 1 module const, value 1. NEW. Hard-caps the uplift so no legal config can push confidence more than one ladder step. Constant, not tunable at runtime — a change requires review (bug-class #53 defense: computed-but-not-consumed inverse — the cap is consumed at exactly one site, verified by mutation).
- **Diagnostic attrs on the existing guest-diagnostic sensor** — REUSE the sensor, add attrs: `last_approach_egress_ts`, `approach_corroboration_credits_applied_total`, `approach_corroboration_switch_state`. Verify sensor identity at build time (probe rev-1 referenced this pattern); do NOT add a new sensor.

### Prior planning docs consulted

- `docs/planning/PROBE_exterior_guest_egress.md` (rev-1 D0 probe — Frigate leg). Full read.
- `docs/planning/PROBE_protect_face_egress.md` (rev-2 D0 probe — Protect leg). Full read.
- `docs/planning/RESEARCH_census_vs_guest_separation.md` — separation-of-concerns ruling; this rev-2 cycle is the exterior-only surgical piece of P8, now measure-narrowed. Read.
- `docs/planning/PLANNING_circling_severity.md`, `PLANNING_circling_label_transition_dispatch.md`, `AUDIT_memory_handbuild_compactor_exterior_track.md` — sibling exterior-linker work (`EXTERIOR-DWELL-LOITER-1`). Disjoint (loiter is a different security signal, no code overlap). Skimmed.
- `docs/planning/PLANNING_presence_pair_guest_latch_veto_gap.md` — GUEST latch semantics. Not touched by rev-2 (INV-1 explicitly forbids latching from an exterior-only signal).
- `docs/PLANNING_v3.5.2_CYCLE_6.md:428-551` — original egress-tracker design context. Referenced.

### Memory bodies pulled

- `project_presence_guest_latch_and_veto_gap.md` — GUEST latch shipped v5.16.0; rev-2 preserves latch state-machine untouched.
- `feedback_hollow_test_anchors.md`, `feedback_falsify_before_asserting.md`, `feedback_mutation_verification_pycache_staleness.md` — Tier-3 test-authority requirements; per-site mutation with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared.
- `feedback_marginal_benefit_pushback.md` — enforces §Marginal-benefit verdict below.
- `feedback_measure_before_build.md` — the two probes are the probe-first gate; both committed BEFORE this rev.
- `feedback_suppression_needs_discharge.md` — the window-bounded credit is a decay, not a suppression, but INV-5 covers the discharge (window expiry + restart clears).
- `feedback_wire_in_anchor_mandatory.md` — Deliverable acceptance criteria require an enclosing-method behavioral anchor + call-neuter drill (see D1 test list).
- `reference_frigate_ghost_evidence_chain.md` — precedes rev-2's decision to NOT depend on face identity; consulted.
- `project_house_zones_vs_hvac_zones.md` — architecture note; the exterior signal is coordinator-scoped, does not touch zone/HVAC.
- `project_frigate1_retired...` — noted; the linker's substrate is Frigate-2-era episodes; no dependency on retired Frigate-1 infrastructure.

### Design docs read

- No `docs/Coordinator/presence.md` exists (grep confirms absent). Read `presence.py:1600-1640` (init), `:4300-4400` (census update handler), `:4820-4900` (guest-room gate + kill switch), `:5040-5170` (guest-gate arm), `:5380-5410` (arm composition), `:5580-5600` (arm caller) end-to-end.

### Code surveyed end-to-end during scoping

- `custom_components/universal_room_automation/exterior_track_linker.py:400-855` — track lifecycle, classify, close, episode write.
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1616, 4300-4400, 4820-4900, 5040-5170, 5380-5410, 5580-5600`.
- `custom_components/universal_room_automation/camera_census.py:1180-1280` — census producer + `SIGNAL_CENSUS_UPDATED` dispatch site (read to confirm we do NOT need to modify the producer).
- `custom_components/universal_room_automation/domain_coordinators/signals.py` — signal registry (where the new signal name is added).
- `custom_components/universal_room_automation/const.py:254-256, 1426-1429, 1742, 1828` — confidence ladder + egress-adjacent camera list.

---

## Tier classification — **Tier 3** (four framing-disjoint reviews + adversarial completeness + operator checkpoint before deploy)

Argument (per CLAUDE.md Tier-3 triggers):

1. **First-ever exterior → house-state trust edge.** Every existing coupling threads the other way (GUEST demotes exterior severity via `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`, `const.py:1617`). Rev-2 creates the first exterior signal that can *raise* a value that a house-state gate reads — the guard-2 confidence used by `_guest_gate_armed`. That is a shared-primitive write with cost-and-safety consequences.
2. **Threads a value through a state machine with one load-bearing consumer.** The `_effective_guest_confidence` uplift is read at exactly one site (`_guest_gate_armed` Guard 2). Bug Class #53 (computed-but-not-consumed) applies in mirror form: one mis-routed path admits a phantom credit. Per D-review completeness: the reviewer must re-enumerate ALL confidence read-sites in `presence.py` (not just the diff) and verify NO OTHER site silently picks up the effective value.
3. **Cost-AND-safety-impacting.** A false-positive GUEST costs comfort + security posture; a false-negative missed guest costs the corroboration this cycle exists to add. The nudge sits directly on the decision boundary.
4. **Independent operator knobs interact.** `_guest_detection_enabled` × new `_approach_corroboration_enabled` switch × `_guest_require_confidence` × `EXTERIOR_APPROACH_CORROB_WINDOW_S` × `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` (operator-editable set). Combinatorial. Tier-3 config-boundary testing required (test at extremes: window=0, `_guest_require_confidence="high"` with 1-step cap, empty egress-adjacent set, etc.).

**Standing policy also applies:** trust-hierarchy ripple (exterior tracker ↔ presence ↔ NM severity ↔ HVAC posture via house_state). Tier 3 is the correct bar.

**Four framings (each per CLAUDE.md, disjoint):**
- **A — local correctness:** the ladder-step uplift arithmetic (single-step cap, no downgrade path, `none→low` boundary), payload shape of the new signal, kill-switch inertness, allow-list of egress cameras honored, timezone-aware `now`.
- **B — state-machine / integration integrity:** guest-gate byte-behavior identical on switch-OFF path AND on switch-ON no-corroboration path; GUEST latch semantics preserved; restart clears `_last_approach_egress_ts`; `SIGNAL_CENSUS_UPDATED` payload unmodified (display consumers see identical values); no double-emit of the new signal on the linker restart path.
- **C — test authority via real per-site source mutation:** for each load-bearing site, edit the production source to bypass the guard, run the suite, confirm a SPECIFIC named test fails, restore. Sites: (i) the `_close_track` dispatch call; (ii) the `_effective_guest_confidence` helper's window check; (iii) the single-step cap; (iv) the switch-OFF short-circuit; (v) the `_guest_detection_enabled` inheritance; (vi) the "last hop ∈ egress-adjacent" membership test. `PYTHONDONTWRITEBYTECODE=1` + `__pycache__` cleared between drills.
- **D — adversarial completeness / diff-blind:** state the invariants below in falsifiable form and BREAK them across the entire presence + linker surface, including pre-existing code. Sample invariant-break enumerations D must attempt: (i) can any pre-existing code path read `_last_approach_egress_ts` other than the helper? (ii) can `_effective_guest_confidence` be reached from any site OTHER than `_guest_gate_armed`? (iii) can a `classification=circling` track wrongly dispatch on the new signal? (iv) legal-config combo that lets the uplift step twice within one gate evaluation (e.g. two closures in <180s stacking)? (v) can a HA restart during an in-flight arm timer preserve the credit via any restored attribute?

**Operator checkpoint BEFORE deploy** — mandatory per Tier 3.

---

## Falsifiable invariants

**INV-1 (solo trigger impossible — primary):** Under NO reachable path may the exterior approach-egress signal ALONE cause a transition INTO `HouseState.GUEST`. Falsifier: with `_census_count=0`, `_unidentified_count=0`, `_census_confidence="none"`, fire `SIGNAL_EXTERIOR_APPROACH_EGRESS` 10× within the window; assert house_state stays out of GUEST for ≥3 census ticks. (Discriminating from the plausible defect *"we accidentally added a third `or` term"*: that defect would satisfy `unidentified_count=0` — the census guard-1 short-circuit — only if it also bypassed guard 1; the discriminator is to test with `_unidentified_count=0` AND `census_confidence="none"` AND assert no transition — a mis-scoped uplift that also bypassed guard 1 would transition.)

**INV-2 (kill-switch inertness):** With `switch.ura_presence_exterior_approach_corroboration_enabled = OFF` (default), the return value of `_guest_gate_armed` is byte-identical (same bool, same log lines, same timer scheduling) to the pre-cycle behavior for the ENTIRE (census_count × unidentified_count × confidence × persistence × first_seen) input matrix. Falsifier: run the existing guest-gate suite with switch OFF; assert zero behavioral diff via a golden-log fixture.

**INV-3 (single-step cap):** `_effective_guest_confidence` returns a value at most ONE rung above `census_confidence` on the ladder `none < low < medium < high`, and NEVER downgrades. Falsifier: monkeypatch `EXTERIOR_APPROACH_CORROB_MAX_STEPS = 3`, feed `census_confidence="none"`; assert return is `"low"` (single-step cap wins), not `"high"`.

**INV-4 (no unidentified-count inflation):** The nudge modifies confidence ONLY. It MUST NOT increase `self._unidentified_count`, `self._census_count`, or `self._face_recognized_count`. The guard-1 existence test (`unidentified_count <= 0 → disarm`) is preserved: interior evidence still must supply the count. Falsifier: with `unidentified_count=0` and the corroboration switch ON, fire the signal; assert `self._unidentified_count == 0` and gate disarms.

**INV-5 (bounded, non-persistent, discharged by window expiry AND restart):** `_last_approach_egress_ts` is in-memory only. After HA restart (or coordinator reload), it is `None`. After `EXTERIOR_APPROACH_CORROB_WINDOW_S` seconds since the last fire, the uplift is not applied. Discharge = window expiry (natural) + restart clear (defensive). Falsifier (a): fire signal at T; simulate restart at T+5s; assert no uplift at T+10s. Falsifier (b): fire signal at T; advance clock to T+window+1; assert no uplift.

**INV-6 (no `SIGNAL_CENSUS_UPDATED` payload mutation):** The published census payload (`camera_census.py:1248-1275`) is byte-identical pre/post cycle. All existing consumers of the shared `confidence` attr see the same value. Falsifier: golden-fixture the payload dict pre/post; assert equality.

**Note on INV design:** INV-2 is deliberately *behavioral* not *structural* — the "no new `or`" grep will pass even for a defect that adds a silent short-circuit inside `_guest_gate_armed` guard chain. The golden-log fixture is the real discriminator. INV-1 similarly requires a live counter-example, not just a code read (per `feedback_falsify_before_asserting.md`). INV-6 exists because a lazy implementation might rewrite the shared attr; the invariant forces the injection to be gate-local.

---

## PRODUCER AND CONSUMER check (mandatory)

### Value: `census_confidence` (the primitive being nudged)

**PRODUCER (existing, UNCHANGED by rev-2):**
- Computed in `camera_census.HouseCensus` → `house_result.confidence` (a `CENSUS_CONFIDENCE_*` string).
- Dispatched via `SIGNAL_CENSUS_UPDATED` at `camera_census.py:1258` (payload key `"confidence"`).
- Consumed by `presence._handle_census_update` at `presence.py:4358` → stored as `self._census_confidence`.
- Multiple derivations? A single derivation in the census producer (source-agreement + count reconciliation). One winner.
- Dependencies: BLE census, camera person-tracker, face-recognition entities. Current health per PROBE_exterior_guest_egress.md Q3: Frigate `_2`-suffix face sensors live post-fix; interior BLE presence live. **Confidence values observed in the wild are populated (probe indirectly confirms via `_handle_census_update` firing on the live instance).**
- **External ground truth?** None internal — cross-validated only against the visible interior evidence (who's home per Ade/Oji/Shola/Ziri BLE + face rec).

**CONSUMER + call-site check (pre-rev-2):**
- `presence.py:5097` inside `_guest_gate_armed` Guard 2 — TRUST-DECISION (gates GUEST admission). **This is the only trust-decision consumer.**
- `sensor.py:3719` (`census_confidence` sensor) — DISPLAY.
- `binary_sensor.py:1630, 1635` — DISPLAY / gating flag.
- Various logging sites — DISPLAY.

**Rev-2 injection point (single, load-bearing):**
- `presence.py:5097` line changes from `if not self._confidence_at_least(census_confidence, ...)` to `if not self._confidence_at_least(self._effective_guest_confidence(census_confidence, now), ...)`. Nothing else moves. `self._census_confidence` (the attribute) is NEVER mutated by the nudge. Display consumers (sensor.py, binary_sensor.py) continue to read the RAW attribute and see identical values — INV-6.

### Value: the new `_last_approach_egress_ts`

**PRODUCER:** `_on_approach_egress` callback, fires on `SIGNAL_EXTERIOR_APPROACH_EGRESS` from `ExteriorTrackLinker._close_track` when `classify(track) == "approach"` AND `track.hops[-1].camera ∈ EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS`. Local-only signal; no cross-namespace identity.

**CONSUMER:** `_effective_guest_confidence` at exactly ONE call site. D-review must confirm no other site reads it.

### Value: `SIGNAL_EXTERIOR_APPROACH_EGRESS` payload

**PRODUCER:** `ExteriorTrackLinker._close_track` — additive alongside the existing `async_create_task(self._write_episode(track))` at `:646`. No behavioral change to episode persistence.

**CONSUMER:** `PresenceCoordinator._on_approach_egress` — new, sole consumer. Additive `event.data.get()` reads only.

---

## Deliverable

### D1 — Approach-egress corroboration as a `census_confidence` contribution to the EXISTING guest gate (single deliverable)

**Behavior:**
1. `ExteriorTrackLinker._close_track` dispatches `SIGNAL_EXTERIOR_APPROACH_EGRESS` when `classify(track) == "approach"` AND `track.label == "person"` AND `track.hops[-1].camera` is a member of `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS`.
2. `PresenceCoordinator._on_approach_egress` records `self._last_approach_egress_ts = now`. It does NOT trigger inference; it only records.
3. On the NEXT `_guest_gate_armed` evaluation (driven by the existing census-update path or the pre-existing persistence recheck timer), Guard 2 substitutes `census_confidence` → `self._effective_guest_confidence(census_confidence, now)`. If the switch is OFF, the helper returns the input unchanged (INV-2). If the switch is ON and the recorded ts is within `EXTERIOR_APPROACH_CORROB_WINDOW_S`, the effective value is raised by AT MOST one ladder step (INV-3), capped by `EXTERIOR_APPROACH_CORROB_MAX_STEPS = 1`.
4. Guard 1 (existence: `unidentified_count > 0`) is UNTOUCHED. Guard 3 (persistence timer) is UNTOUCHED. The nudge cannot make a zero-unidentified state arm the gate (INV-4).
5. Kill switches (defense in depth): (a) `switch.ura_presence_exterior_approach_corroboration_enabled` OFF ⇒ helper returns input unchanged; (b) `_guest_detection_enabled` OFF ⇒ existing guard at `:5084` already returns False before Guard 2 runs; the helper is inert regardless.

**Where the nudge injects (single site):**
- `presence.py:5097` — the Guard 2 comparison. Exactly one line diff for the read; the helper + subscriber + init are added elsewhere but the trust-decision surface is one line, one comparator. D-review verifies no other site reads the effective value.

**Acceptance criteria (each testable + discriminating):**

- **Verify (grep):** `git grep -n 'guest_room_gate_armed\|unid_gate_armed' custom_components/universal_room_automation/domain_coordinators/presence.py` — the arm-composition expression at `:5391` and `:5399` is byte-identical to pre-cycle (INV-1 structural check; the behavioral INV-1 test is below).
- **Verify (grep):** `git grep -n '_effective_guest_confidence' custom_components/universal_room_automation/domain_coordinators/presence.py` returns exactly TWO matches (definition + single call site). Any additional match is a D-review CRITICAL finding.
- **Verify (grep):** `git grep -n 'SIGNAL_EXTERIOR_APPROACH_EGRESS' custom_components/universal_room_automation/` — exactly one producer (linker `_close_track`) and one consumer (presence `_on_approach_egress`).
- **Sensor:** existing guest-diagnostic sensor exposes `last_approach_egress_ts` (ISO utc or `None`), `approach_corroboration_credits_applied_total` (int, monotonic), `approach_corroboration_switch_state` (`on`/`off`). Same sensor, additive attrs.
- **Sensor discrimination (crucial):** if the fix works, `approach_corroboration_credits_applied_total` MUST increment ONLY when (a) an approach-egress signal fired within window AND (b) Guard 2 was actually evaluated AND (c) the effective value differed from the raw. Under the plausible defect *"credit counter increments on every signal fire regardless of Guard 2 evaluation"* the counter would grow at ~18/day even when no gate evaluation happened; the discriminating check is to compare the counter's delta over an empty-house window (residents away until Wed) against the actual `SIGNAL_EXTERIOR_APPROACH_EGRESS` fire count — they should DIVERGE (fires happen; credits do not, because unidentified_count=0 gates out at Guard 1).
- **Test — INV-1 falsifier:** `test_approach_signal_alone_does_not_arm_guest`. Fire the signal with `_unidentified_count=0, _census_confidence="none"`; assert `_guest_gate_armed(...) is False` across 3 ticks; assert no GUEST transition.
- **Test — INV-2 falsifier (switch OFF inertness):** `test_switch_off_gate_byte_identical` — golden-log fixture of `_guest_gate_armed` over a matrix of inputs with switch OFF; assert diff is empty vs pre-cycle golden.
- **Test — INV-3 falsifier (single-step cap):** `test_effective_confidence_capped_at_one_step` — monkeypatch cap to 3, feed `"none"`; assert output is `"low"` not `"high"`.
- **Test — INV-4 falsifier (no count inflation):** `test_signal_does_not_inflate_unidentified_count`.
- **Test — INV-5 falsifier (a) restart clears:** `test_restart_clears_last_approach_egress_ts` — instantiate coordinator, set attr, re-instantiate; assert None.
- **Test — INV-5 falsifier (b) window bounds:** `test_uplift_expires_at_window_boundary`.
- **Test — INV-6 falsifier (payload unchanged):** `test_census_signal_payload_unchanged` — golden-dict fixture of `SIGNAL_CENSUS_UPDATED` payload; assert byte-equal.
- **Test — mutation drills (Reviewer C):** per-site, listed in Tier §C above. Each drill's named test MUST fail on mutation and PASS on restore.
- **Live (partial — see empty-house note):** with switch **OFF** (ship state), post-restart the diagnostic attr `approach_corroboration_switch_state = "off"` and `approach_corroboration_credits_applied_total` stays at 0 for 24h regardless of exterior signal traffic. Under the plausible defect *"switch is ignored"* the counter would rise. Discriminating.
- **Live (bounded — post-checkpoint switch-ON, only when residents home):** with switch **ON**, fire the linker path organically (a person approaches a door) with `_unidentified_count > 0` interior evidence present; observe `last_approach_egress_ts` updates AND (only if the census had confidence just-below the guest require threshold) `approach_corroboration_credits_applied_total` increments. Under the plausible defect *"nudge applies even when unidentified=0"* the counter increments during the empty-house window; that IS the negative check we can run TODAY without waiting for guests.

**Empty-house-window validation plan (residents away until Wed):**
- What CAN be validated today (empty house):
  - INV-2, INV-3, INV-4, INV-5, INV-6 — all in-suite (deterministic).
  - Diagnostic sensor emits `switch_state="off"` and credit counter stays 0.
  - `SIGNAL_EXTERIOR_APPROACH_EGRESS` fires organically on delivery/passerby traffic (~18/day per probe); assert `last_approach_egress_ts` updates but `unidentified_count` stays 0 → INV-4 discriminating live check works TODAY.
- What CANNOT be validated until residents return (Wed+):
  - The intended positive path (real guest arrival → nudge shortens guest-gate time-to-arm). Live-validation of this waits for organic guest events; recorded in README post-Wed.
- Non-goal today: do NOT flip the switch ON with an empty house until the operator returns and can observe.

---

## Numbers get knobs

| Name | Value | Rung | Rationale |
|---|---:|---|---|
| `switch.ura_presence_exterior_approach_corroboration_enabled` | OFF (ship) | 3 (entity) | Operator kill switch; ship OFF, flip ON post-Tier-3 checkpoint + observed presence of residents. The fire axe. Persisted via existing switch machinery. |
| `EXTERIOR_APPROACH_CORROB_WINDOW_S` | 180 | 1 (module const) | Bounds the trust-hierarchy edge in time. Probe shows co-fire cadence ~60s between track closure and downstream census tick; 180s covers a delayed inference re-tick without extending trust beyond the linker's observation horizon. Changing this REQUIRES review — it's the primary safety bound. |
| `EXTERIOR_APPROACH_CORROB_MAX_STEPS` | 1 | 1 (module const) | Hard cap: the nudge is AT MOST one ladder step. Not runtime-tunable — a bump to 2+ would categorically change the trust-hierarchy blast radius and demands review. Constant load asserts `MAX_STEPS in (0, 1)` at import time. |
| `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` | existing (const.py) | 1 | REUSED unchanged. Operator-editable via code; changing it changes the corroboration surface — review-gated. |
| `_guest_require_confidence` | existing | 3 (already-exposed) | REUSED unchanged. Operator can raise this to require `"high"` post-uplift, which combined with `MAX_STEPS=1` means the raw confidence must be at least `"medium"` for the nudge to matter — a natural safety knob. |
| `_guest_detection_enabled` | existing | 3 (already-exposed) | REUSED as the master kill; OFF makes the whole path (including corroboration) inert. Documented as the belt-and-suspenders switch alongside the new one. |

**Kill switch semantics:** setting `switch.ura_presence_exterior_approach_corroboration_enabled = OFF` MUST make the cycle byte-behavior-inert (INV-2 golden-log). This is documented on the switch entity's description text.

**Not exposed to config-flow / not a Number entity:** the window and max-step values are safety-relevant bounds, not day-to-day operator tuning (per Numbers-Get-Knobs rung 1 guidance). If the operator later wants to tune the window, a review-gated const change is the correct path.

---

## Non-goals (explicit)

1. **NOT a solo exterior→GUEST arm.** No new `or` term at `presence.py:5391/5399`. If a reviewer sees one, it is a CRITICAL finding.
2. **NOT a third guest arm anywhere else.** The nudge is a Guard-2 confidence modifier, not a new arm path.
3. **NOT face identity.** No `person_id` resolution, no Frigate `sub_label` promotion, no llmvision, no NVR REST integration. Rev-1 D1/D2 are PARKED (fast-follow card `EXTERIOR-GUEST-FACE-FASTFOLLOW-1`).
4. **NOT a mutation of `SIGNAL_CENSUS_UPDATED` payload.** The shared `confidence` attribute stays as computed by `camera_census.HouseCensus`. Rev-2 injection is gate-local (INV-6).
5. **NOT persisting corroboration credit across restart.** In-memory only (INV-5).
6. **NOT triggering inference from the exterior signal.** The signal only records the ts; the guest gate re-evaluates on the existing census tick / persistence recheck path. Rationale: prevents a bare exterior signal from causing house-state re-ticks and preserves the "interior evidence leads" invariant.
7. **NOT changing `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`.** The pre-existing one-way demotion (GUEST demotes exterior severity) is orthogonal and untouched.
8. **NOT touching `_guest_room_gate_armed`** (the multi-room dwell path). Rev-1 D2's dwell-shortening idea is PARKED.
9. **NOT modifying `ExteriorTrackLinker.classify()`** — REUSED as-is. Only `_close_track` gets a signal dispatch alongside the existing episode write.
10. **NOT wired to `circling` or `pass_by` classifications.** Only `approach` + person + egress-adjacent last hop qualifies. This is a security invariant (a circling track is a loiter concern, handled by `EXTERIOR-DWELL-LOITER-1`).

---

## Marginal-benefit verdict (per CLAUDE.md decomposition)

**Decomposition:**
- **Simplest version:** ship D1 as specified — one signal, one subscriber, one guard-2-local helper, one switch, two constants.
- **Even simpler alternative considered:** "just lower `_guest_require_confidence` by one rung." REJECTED — that would apply to ALL gate evaluations regardless of exterior corroboration, and the whole point of the probe evidence is that the *conditional* nudge (corroborated-by-egress) is the value; an unconditional lowering weakens the gate globally.
- **Fancier version considered:** wire the nudge into the `camera_census` producer to raise `house_result.confidence` at source. REJECTED — that would mutate a shared primitive read by display sensors (INV-6 violation), and it would blur the "interior evidence leads" invariant (the census producer would need to know about exterior signals — a categorical cross-coordinator write).

**Marginal benefit:**
- Probe evidence: **94% termination rate at egress-adjacent cameras, ~18 approach-tracks/day, face-independent.** This is a real, abundant, cheap-to-observe signal.
- Benefit realized: when a genuinely unknown person crosses the property and enters, the guest gate is more likely to fire on the census tick *when the confidence is just-below threshold* — closing a real class of missed-guest cases the operator has flagged. In wall-clock terms: guest gate arms one persistence-window sooner (typical: 60-180s) IF the confidence uplift moves the value across the require-threshold. Otherwise no effect.

**Marginal ingredient risk:**
- FIRST exterior → house-state trust edge — categorically new. Tier-3 machinery (four framing-disjoint reviews + operator checkpoint) directly prices this.
- Cross-coordinator dispatch: additive-only, additive consumer, no shared-state write.
- The cap (single ladder step, non-persistent, in-memory) is intentionally minimal — this is the SMALLEST viable trust-edge that captures the probe's evidence.

**Verdict: BUILD. The Tier-3 ingredient risk is warranted, PROVIDED the cycle stays at the minimum viable shape specified.** Concretely:

- The probe's 94%/18-per-day evidence clears the empirical bar; this is not a speculative feature.
- The alternative "make the operator manually lower `_guest_require_confidence`" (a rung-3 knob turn, $0 of code) was seriously considered. It fails because it weakens the gate always, not just when corroboration exists — turning a discriminating primitive into a blunter one. The corroborated uplift IS the value.
- The single-step cap + window + non-persistent design keeps the "if this goes wrong" blast radius bounded to one census-tick / one persistence-window / one guest-gate arm. There is no path to a runaway or a persisted phantom credit.
- Tier 3 is the CORRECT bar, and the operator checkpoint before deploy is the correct gate — do not attempt to descope to Tier 2. The trust-hierarchy edge is real and new.

**If this itself were still too much:** the alternate simpler-still shape is "ship D1 but leave the switch OFF permanently and use the diagnostic counter as an offline observability tool for weeks before flipping." That IS the shipping plan (switch defaults OFF; operator flip is a post-checkpoint decision) — so the cycle already embeds its own simpler-mode.

---

## Test plan summary (per Tier-3 §C authority)

Every named test above must survive a mutation drill: comment/neuter the production site → the named test MUST fail with a specific assertion (not a generic import error). Reviewer C runs the drills per-site (NOT aggregate monkeypatch), with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared between mutations (per `feedback_mutation_verification_pycache_staleness.md`).

Anchor list (each demands a mutation-verified behavioral test — the wire-in anchor, per `feedback_wire_in_anchor_mandatory.md`, is the enclosing-method behavioral anchor, NOT a helper-existence test):

1. `_close_track` dispatches the new signal when-and-only-when `classify=="approach"` + person + egress-adjacent last hop.
2. `_on_approach_egress` records `_last_approach_egress_ts` and does NOT trigger inference.
3. `_effective_guest_confidence` returns raw when switch OFF, returns raw when ts None, returns raw when window expired, returns raw when `_guest_detection_enabled` False, returns +1 rung otherwise.
4. Single-step cap is respected regardless of MAX_STEPS knob value >1.
5. Guard 1 (unidentified_count > 0) short-circuits before Guard 2 — the nudge cannot force-arm.
6. `SIGNAL_CENSUS_UPDATED` payload byte-unchanged (golden fixture).
7. Restart clears `_last_approach_egress_ts`.
8. Grep + behavioral: no third `or` term in arm composition.
9. D-review completeness: no OTHER site reads `_effective_guest_confidence` or `_last_approach_egress_ts`.

---

## Rev-1 → Rev-2 audit trail (accounted-for)

- **Rev-1 D0 probe (Frigate)** → SHIPPED (`PROBE_exterior_guest_egress.md`). NO-GO called on D1 (~7% coverage).
- **Rev-2 D0 probe (Protect)** → SHIPPED (`PROBE_protect_face_egress.md`). Confirmed NO-GO on D1 (Protect adds 0% consumable identity at door).
- **Rev-1 D1 (populate `person_id` on egress event)** → PARKED. Card: `EXTERIOR-GUEST-FACE-FASTFOLLOW-1`. Revisit trigger: probe re-run showing ≥30% named coverage at door/exterior cams.
- **Rev-1 D2 (guest-room dwell shortening via `_guest_room_gate_armed`)** → PARKED with D1 (its value was contingent on D1 identity).
- **Rev-1 D3 (track-linker → egress hand-off)** → PROMOTED to sole cycle deliverable (this rev's D1).
- Nothing silently dropped.
