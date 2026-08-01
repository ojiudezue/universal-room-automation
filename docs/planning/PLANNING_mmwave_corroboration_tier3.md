# PLANNING — mmWave Corroboration + Comfort-Fan Away-Veto (Tier 3)

**Cycle name:** `mmwave_corroboration_tier3`
**Author:** ura-planner
**Date filed:** 2026-07-31
**Operator directive (2026-07-31):** *"Examine backlog 1 from all angles and then plan it. Tier 3 even though it's likely lighter. We've been down this road on fans many times."*
**Source backlog:** `docs/planning/BACKLOG_2026-07-26_small_cycles.md` item **#1** ("mmWave phantom occupancy → HVAC waste").
**Backlog tier estimate:** 2 → **OPERATOR ELEVATED TO TIER 3** (explicit; documented in §Tier Classification). Rationale: repeated fan-seam history (v4.7.13 sleep fans, v4.7.20 Layer-1 silent hold, v4.7.22 Mode-2 recheck, v5.23.0 fan-recheck release, v5.31.0 manual-off cooldown, DOC-2 shared-layer extraction still deferred); presence↔HVAC shared-primitive ripple; the change threads *demotion of a truth source* (mmWave) through every occupancy-consuming site — the exact "one missed site" (Bug Class #53) topology Tier 3 exists for.

---

## Falsifiable invariant (Tier 3 requirement — state up front)

**INVARIANT M (mmWave sustain floor):**

> For any room R and any tick T, if at T
> (a) the room's Tier-1 provenance shows mmwave as the **sole** positive kind
>     (motion=False, occupancy=False, mmwave=True), AND
> (b) a configured `CONF_FANS` entity in R has been continuously `on` for
>     at least `MMWAVE_FAN_CORROBORATION_GRACE_S` (default 180 s), AND
> (c) no BLE-trustworthy person is present in R (Layer 1) and no adjacent
>     room has a BLE-trustworthy person (Layer 2 optional; kill switch), AND
> (d) no camera-person signal is currently present for R's zone, AND
> (e) `_last_motion_time[R]` is either None or older than
>     `MMWAVE_FAN_CORROBORATION_STALE_S` (default =
>     `BLE_MOTION_CONFIRM_MULTIPLIER × occupancy_timeout[R]`, mirroring the
>     `ble_extend_not_create` chain window; const.py:375),
>
> **THEN**, from tick T forward, the mmwave-only signal MUST NOT
> continue to hold `STATE_OCCUPIED[R] == True`. The room decays to
> vacant at the natural `occupancy_timeout` boundary; any subsequent
> mmwave-only re-fire within the fan-on window MUST NOT re-create
> occupancy (mirrors `ble_extend_not_create` invariant (a) — the
> "cannot CREATE" leg — applied to mmwave under interference).

**INVARIANT V (comfort-fan away veto):**

> If `house_state ∈ {AWAY, VACATION}` AND the room has no trusted
> presence (BLE + camera + motion within `occupancy_timeout`, mmwave
> excluded), a **comfort** temperature-based fan actuation from
> `handle_temperature_based_fan_control` MUST be suppressed. Humidity
> fans (bathroom-exhaust), safety fans, and manually-actuated fans are
> exempt (they preserve their existing precedence). Sleep windows are
> untouched — this predicate is disjoint from `is_sleep_mode_active()`
> (which the D-AUT comment at automation.py:1724-1733 deliberately
> kept per-room, not house-state-coupled).

Reviewer D's sole job (§Reviews) is to break these two invariants by
enumerating **every** site — including pre-existing code, not just the
diff — that can flip `STATE_OCCUPIED` True or emit a comfort-fan
`turn_on` under the stated conditions, and to produce a concrete legal
repro (values + state) for each leak.

---

## Institutional context verified

### Prior planning docs consulted

| Doc | Body pulled? | Relevance |
|---|---|---|
| `docs/planning/PLANNING_ble_extend_not_create.md` | full read | **Direct template.** BLE-cannot-create pattern maps 1:1 onto mmwave-cannot-sustain-under-fan. Reuse: `BLE_MOTION_CONFIRM_MULTIPLIER` (const.py:375), `chain / motion` two-leg admission, per-site source-mutation test protocol, invariant-first framing. |
| `docs/planning/PLANNING_fan_actuation_shared_layer.md` | full read | Enumerates every duplicated fan-actuation surface (room-tier `automation.py:1542-1696`, HVAC-tier `hvac_fans.py:174-450`, humidity-fan sole-owner carve-out, `actuator_reconciler.py:778` third-writer). This cycle **does not extract** the shared layer (that's DOC-2, deferred until FOUNDATION GATE per its GO CRITERIA) but MUST enumerate its emission sites so the veto lands on all of them. |
| `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md` | headers + humidity carve-out section | Confirms humidity fans are SOLE-OWNER room-tier (`hvac_fans.py:291-296`) — the comfort-fan veto MUST NOT accidentally suppress humidity-fan actuations that share code paths. |
| `docs/planning/PLANNING_house_state_utilization.md` | §0 framing + AWAY row | AWAY is "thin — big posture upside" — this is one of the first real operational consumers of AWAY beyond presence-veto. Consistent with the roadmap. |
| `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` | referenced from `_compute_fan_interference_rooms` docstring (presence.py:3235) | Interference-conditional reliability rationale. Confirms the Layer-2/Layer-3 directions this cycle picks up were explicitly deferred there. |
| `docs/planning/project_v4_7_20_fan_noise_layer1_live.md` (memory) | pulled | Silent hold/decay design. Confirms existing gate is **extend-only** and CANNOT demote. |
| `docs/planning/project_v4_7_22_fan_recheck_mode2_live.md` (memory) | pulled | `presence_fan_recheck.py` reads `fan_controller._room_fans` + `manual_off_cooldown_until` (`:999-1002`). Fan-recheck already has an occupancy-release primitive (`OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE` at const.py:489) — this cycle does NOT modify it; the veto operates upstream of it. |
| `docs/planning/project_fan_noise_mmwave_mitigation_backlog.md` (memory) | pulled | Full layered design; Layer-3 zone-absent → pause-and-recheck listed as deferred — this cycle explicitly parks the Layer-3 elaboration per Marginal-Benefit Decomposition. |
| `docs/planning/PLANNING_stuck_signal_watchdog.md` (via const.py:2454 pointer) | referenced | The watchdog D-rules currently observe stuck signals from camera-census (`camera_census.py:92`), person_coordinator (`person_coordinator.py:1534`), actuator_reconciler (`actuator_reconciler.py:880`). It does **NOT** cover a stuck-True mmwave binary_sensor. Study A's dead Athom mmwave (unavailable) is a different failure mode (dead, not stuck-True); flagged as a D6 follow-up, not built here. |

### Memory bodies pulled (from `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/`)

- `project_guest_mode_false_positive_backlog.md` — lost-but-away exclusion pattern; mmwave-in-empty-house is topologically similar (a wrong "someone is there" that cascades). Cited as prior evidence that presence false-positives cascade multi-coordinator.
- `project_presence_guest_latch_and_veto_gap.md` — v5.16.0 pattern for adding new corroboration conditions to a presence signal chain; template for the D2 predicate placement.
- `project_v5_5_0_inclement_weather_shipped.md` — Tier 3 delicate-cycle example; reviewer discipline reference.
- `feedback_mutation_verification_pycache_staleness.md` — MUST disable bytecode + clear `__pycache__` for Reviewer C's per-site source mutation to be trustworthy (pyc can mask reverted source).
- `feedback_marginal_benefit_pushback.md` — this doc enforces its recommendation in §Marginal-Benefit Decomposition below.
- `project_jaya_bedroom_occupancy_resolved.md` — precedent for BLE-noise-driven flap; supports the L1 corroboration-not-alone posture.

### Design docs read

- `docs/Coordinator/HOUSE_MANUAL.md` §3.1 step 8 (BLE extend, never create) and §"ble_extend_not_create contract" — the mmwave analog contract must be added here after ship.
- `docs/Coordinator/PRESENCE.md` — checked for fan-recheck section; TBD, update after ship.
- `docs/Coordinator/HVAC.md` — checked for fan-controller section; TBD, update after ship (veto site cross-refs).

### Greps run + results (proof-of-work per proposed addition)

Every proposed addition below is annotated **REUSED** (file:line) or **NEW** (justification of why no equivalent exists).

**Occupancy-source strings (existing family — const.py:483-495):**
- `OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE = "fan_recheck_release"` (const.py:489) — REUSED sibling; new source string `OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED = "mmwave_fan_demoted"` is **NEW** because no existing source name captures the demotion event (grep on `OCCUPANCY_SOURCE_` returned FAN_RECHECK_RELEASE, MOTION, MMWAVE, BLE, CAMERA, TIMEOUT — none for "demoted-by-interference").

**Fan-interference primitive (presence.py:3208 `_compute_fan_interference_rooms`):**
- REUSED as the input to D2's demotion predicate. Its three conditions (mmwave-sole, BLE-absent, camera-absent) are ~identical to Invariant M's (a)/(c)/(d). Reuse the enumeration; add the fan-on-duration gate (b) and motion-staleness gate (e) as a WRAPPER, do NOT rewrite the primitive. This preserves the observation-only guarantee documented at presence.py:3273-3284.

**BLE ladder + phone-trustworthy checker (`_apply_fan_interference_gate`, presence.py:3369-3600):**
- REUSED. `_trustworthy_persons_in_room` (presence.py:3479-3486) is the Layer-1 corroboration primitive; adjacency map (`_adjacency_cache`, presence.py:2592-2604) is Layer-2. Nothing new.

**Fan-on tracking (`_fan_on_rooms` set on ZonePresenceTracker):**
- REUSED (presence.py:480). Populated by `_handle_fan_change` (state-change listener). Need per-room fan-on **duration** (currently only membership), so add a sibling dict `_fan_on_since: Dict[str, datetime]` on the tracker. **NEW** field — grep `_fan_on_` returned only `_fan_on_rooms` and `_fan_entity_to_room`.

**Chain/motion window (`BLE_MOTION_CONFIRM_MULTIPLIER`):**
- REUSED as the default for `MMWAVE_FAN_CORROBORATION_STALE_S` (see D1 knob table). Semantically the same predicate ("recent motion means within-timeout-territory").

**Config-flow / options-flow surface:**
- `CONF_FAN_INTERFERENCE_HOLD_S` (const.py:398), `CONF_FANS`, `CONF_ADJACENT_ROOMS`, `CONF_OCCUPANCY_TIMEOUT` (const.py:314), `CONF_MOTION_SENSORS`/`CONF_MMWAVE_SENSORS`/`CONF_OCCUPANCY_SENSORS` (const.py:333-335) — all REUSED unchanged.

**House-state read (`_house_state`):**
- `CoordinatorManager._house_state_machine` (manager.py:143, `.house_state` property). REUSED. Note per `PLANNING_house_state_utilization.md` §Rung-1: `getattr(presence, "_house_state", "")` at `energy.py:6824` is a dead read — do NOT copy that pattern; go through the CM property.

**Comfort-fan actuation sites (grep `_safe_service_call.*fan|SERVICE_TURN_ON.*fan|turn_on.*fan_entity`):**
- Room-tier: `automation.py:1740-1747` (turn_off), `automation.py:1784-1804` (turn_on) inside `handle_temperature_based_fan_control`. Veto goes HERE.
- HVAC-tier: `hvac_fans.py:_set_fan_state` (referenced :166, :281) called from `_evaluate_temp_fan` (`:174-450`). Veto **also** goes HERE via a shared predicate.
- Reconciler: `actuator_reconciler.py:778` (fan actuation site flagged in DOC-2 fan-actuation inventory). Veto goes HERE too — this is the "third writer" DOC-2 called out.
- Humidity path (`handle_humidity_based_fan_control` at automation.py:1713+) — EXPLICITLY EXCLUDED from the veto per the `hvac_fans.py:291-296` humidity sole-owner contract. Guard the predicate on comfort-fan calls only.

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/domain_coordinators/presence.py` (relevant blocks 380-580, 2500-2650, 3200-3600)
- `custom_components/universal_room_automation/coordinator.py:2090-2210` (BLE extend-not-create block — template)
- `custom_components/universal_room_automation/automation.py:1690-1830` (room-tier fan actuation — veto site 1)
- `custom_components/universal_room_automation/hvac_fans.py:150-450` (HVAC-tier fan controller — veto site 2)
- `custom_components/universal_room_automation/actuator_reconciler.py:770-890` (reconciler fan site — veto site 3; stuck_signal emit at :880 for pattern reference)
- `custom_components/universal_room_automation/const.py:314-498` (occupancy + fan-recheck + fan-interference knob family)
- `custom_components/universal_room_automation/domain_coordinators/signals.py:120-135` (`SIGNAL_FAN_INTERFERENCE_GATE_FIRED` — sibling signal for the new `SIGNAL_MMWAVE_FAN_DEMOTED`)
- `custom_components/universal_room_automation/binary_sensor.py:470-550` (`fan_interference_*` attrs — pattern for the new observability attrs)
- `custom_components/universal_room_automation/sensor.py:4500-4550` (`fan_interference_rooms` attr on presence primitive sensor — pattern to REUSE with a `mmwave_fan_demoted_rooms` sibling attr)

### Angles examined (operator: "from all angles")

**a) Sensor-level inventory (which rooms are mmwave-only, no PIR).** Study A confirmed one (single Zigbee mmwave `binary_sensor.mmwave_zigbee_studya_presence`, `motion_sensors=[]`, second Athom mmwave dead). Full inventory across ~41 rooms is **an audit deliverable (D0)** — planner CANNOT read live `entry.data`/`entry.options` from source; requires an ssh probe (per "Measure before you build"). D0 gates whether the fix's marginal benefit is one-room or fleet-wide.

**b) Fusion-level: why the v4.7.20/22 machinery doesn't engage.** ROOT CAUSE identified: `_apply_fan_interference_gate` (presence.py:3369+) is documented **truth-preserving extend-only** — its hold dict can ONLY extend `_room_occupied`, never demote (docstring line 3382-3384 + property docstring line 568-577). Study A needs the **opposite** direction: demote mmwave-sole hold when interference is confirmed. The existing primitive's flag output (`_compute_fan_interference_rooms`) can be reused as INPUT to a demotion decision, but the demotion machinery is NEW. This is the diff-blind observation D would have to make and it's called out here to save Reviewer D that step.

**c) v5.22.0 template (ble_extend_not_create).** Direct fit: swap "BLE" for "mmwave-under-fan-interference" and swap "cannot CREATE" for "cannot SUSTAIN past N minutes". The two-leg admission (CHAIN + MOTION) becomes a two-leg REJECTION (fan-on-duration + motion-stale). The kill switch semantics (`MULT=0`) become `MMWAVE_FAN_CORROBORATION_STALE_S = 0` (disable).

**d) Actuator feedback loop (fan ON → mmwave retrigger).** Study A: fan-on at 19:31, mmwave release came 33 s after fan-off → self-sustaining loop in an empty house. The fusion-level fix (D2) breaks the loop upstream (mmwave stops holding occupancy → next tick fan sees occupied=False → fan off). The house-away veto (D3) is a belt-and-suspenders that never lets the loop start when the house is AWAY/VACATION.

**e) House-state belt-and-suspenders.** Operator asked "shouldn't fan control key off away state?" Prior D-AUT decision (automation.py:1724-1733) kept the SLEEP gate per-room to avoid over-extending common-area rooms with disagreeing schedules. That reasoning does not apply to AWAY/VACATION — house-scope "nobody is home" is unambiguous. The veto is scoped narrowly: AWAY/VACATION only, comfort fans only, requires "no trusted presence" (BLE+camera+motion, mmwave excluded — this is the whole point). Sleep gate is untouched.

**f) Dead-sensor handling.** Study A's dead Athom mmwave (unavailable) is currently invisible because `sensor.<room>_unavailable_entities` tracks input sensors but the room continued to work off the *other* mmwave. The stuck-signal watchdog's D-rules (const.py:2454+, `_stuck_signal_nm.py`) currently cover camera-census, person-coordinator, and actuator-reconciler emit sites — NOT a stuck-True mmwave binary_sensor (Study A's Athom was `unavailable`, a different mode). Adding stuck/dead-mmwave to the watchdog is a **D6 follow-up** (small, additive), NOT part of the invariant-critical Tier 3 core.

**g) Interactions with existing machinery.**
- `occupancy_debounce` / `occupancy_timeout` (const.py:314-315, defaults :701-702) — the demotion never fires INSIDE debounce; it operates on the sustained-hold decision. No regression.
- `_fan_vacancy_start` grace hold (automation.py:1694-1703, `CONF_FAN_VACANCY_HOLD`) — currently keeps fans on for a grace period post-vacancy. Under D3 veto (house AWAY, no trusted presence), the vacancy hold is short-circuited because the fan-on path never fires in the first place. No regression when house is home.
- Fan-recheck (const.py:411-489, `OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE`, `_fan_recheck_mmwave_history_ticks` at const.py:477) — the recheck machinery already implements a pause-and-observe protocol. **This cycle does NOT modify recheck**; D2's demotion is upstream, D3's veto is at the actuation site, both are disjoint from recheck's counters. Reviewer B verifies no counter regression via a fan-recheck regression fixture (D5-T3).
- Freeze-floor (unrelated coordinator) — no interaction.

---

## Tier Classification

**Tier 3** (four framing-disjoint reviews + orchestrator independent verification + operator checkpoint BEFORE deploy).

**Operator-elevated 2026-07-31** (see directive above). Backlog #1 estimated Tier 2. Elevation rationale documented per CLAUDE.md "Standing policy … use the Tier 2-DB review protocol — 3 framing-disjoint reviews — for ALL regression-prone work" AND the Tier-3 trigger "cost-AND-safety-impacting … where a single wrong path = silent financial or comfort/safety loss." Cooling an empty Master Suite for 6 h is a real financial leak; the topology is Bug Class #53 (one missed emission/decision site) applied to *three* known fan-actuation sites + presence provenance.

Additional Tier-3 stringency (per CLAUDE.md §Tier 3):
- Falsifiable invariant stated up front (see above).
- Config-boundary/combinatorial testing at knob extremes (§D5-T7).
- Orchestrator independent verification via per-site source mutation on all four load-bearing sites **before deploy** (§Deploy gates).
- Operator checkpoint BEFORE deploy (§Deploy gates).

---

## Marginal-Benefit Decomposition (MANDATORY per CLAUDE.md)

**Benefit source separated:**

| Component | What it buys | Est. share of total benefit |
|---|---|---|
| **D3 house-AWAY comfort-fan veto** | Kills every empty-house comfort-fan turn-on globally; breaks the Study A feedback loop before it starts | **~70%** — biggest single lever; covers 100% of Study A + Master Bedroom class when house is AWAY/VACATION |
| **D2 mmwave-corroboration demotion (fusion)** | Kills the phantom occupancy hold itself; correct census / room-tile / HVAC even when house is HOME (2026-07-26 Master Bedroom was OCCUPIED-house with people elsewhere → veto wouldn't have fired) | ~25% — required to cover the operator-home case |
| **D4 Layer-2 adjacent-BLE relaxation** | Reduces false-demote when person legitimately in adjacent room | ~5% — quality-of-life |
| **D6 dead/stuck-mmwave in stuck-signal watchdog** | Alerts on the Athom-dead class instead of relying on unavailable_entities | ~5% — observability, not correction |

**Simplest version (recommended):** **D0 (audit) + D2 (demotion) + D3 (veto) + D5 (tests) + D7 (observability).** Skip D4 initially. Skip D6 initially.

**Elaborate version parked:** promoting Layer-3 (zone-absent → fan-pause-and-recheck) from the deferred backlog into this cycle; a full corroborate-or-kill fusion rewrite that touches every downstream reader. Both parked with evidence triggers:
- **Trigger to build D4:** Reviewer D flags a legal repro where D2 demotes a genuinely-occupied adjacent-room-person scenario AND live validation (D8) confirms it fires in the wild in the first 7 days.
- **Trigger to build D6:** a second incident where a mmwave dies (unavailable) or sticks-True and the operator loses time diagnosing it (Study A cost ~1 h on 07-31).
- **Trigger to build Layer-3 pause-and-recheck expansion:** D2 demotion demonstrated ineffective on a real recurrence (mmwave with fan-off-verification loop needed).

**Marginal risk pricing:** D2 is the risky ingredient (touches the presence provenance chain — the exact seam that broke in 2026-07-17 masterbath and required v5.22.0). D3 is comparatively low-risk (a single AND-guard at three known actuation sites). D4/Layer-3 add cross-coordinator state (fan-pause-and-observe) — categorically riskier per the "shared-primitive" trigger. Parking them keeps the ingredient risk within Tier 3 tolerance for this pass; if D4 later becomes necessary, it gets its own Tier 3 cycle.

**Recommendation:** ship D0/D2/D3/D5/D7. Do NOT elaborate to D4/D6/Layer-3 in this cycle.

---

## Deliverables

### D0: Sensor-Level Audit (probe-first; MANDATORY per "Measure before you build")

Enumerate every room whose configured occupancy substrate is **mmwave-only** (i.e. `CONF_MMWAVE_SENSORS` non-empty AND `CONF_MOTION_SENSORS` empty AND `CONF_OCCUPANCY_SENSORS` empty), plus rooms with a mix where one of the sensors is currently `unavailable`. Read from live `.storage/core.config_entries` via ssh; do NOT rely on planner-mental-model.

**Deliverable:** `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md` — a hand-built table of `room_name, mmwave_entities, motion_entities, occupancy_entities, dead_entities` for all ~41 rooms. This table is the acceptance fixture D5 diffs against.

**Acceptance Criteria**
- **Verify:** audit doc committed with N ≥ 1 rooms in the mmwave-only class (Study A confirmed ≥1; likely more).
- **Verify:** every room with an `unavailable` mmwave entity is called out (dead-sensor visibility gap).
- **Live:** — (offline audit, no live check).
- **Gate:** if N == 0 (no mmwave-only rooms), DOWNGRADE cycle to Tier 2 and revisit D3 alone (fusion demotion has no target).

### D1: Constants + Config Surface (Numbers-Get-Knobs)

All new numbers named + placed on the correct rung per CLAUDE.md "Numbers Get Knobs".

| Knob | Default | Rung | Home | Justification |
|---|---|---|---|---|
| `MMWAVE_FAN_CORROBORATION_ENABLED` | `True` | **Rung 1 (module constant)** — kill switch | `const.py` | Safety/trust bound on a demotion predicate; disable path if the demotion produces a real-world false-vacate |
| `MMWAVE_FAN_CORROBORATION_GRACE_S` | `180` | **Rung 1 (module constant)** | `const.py` | Fan must be on ≥ this long before demotion is legal — protects against transient fan pulses; not operator-tuned per-deploy |
| `MMWAVE_FAN_CORROBORATION_STALE_S` | (dynamic: `BLE_MOTION_CONFIRM_MULTIPLIER × room.occupancy_timeout`) | **derived** | `presence.py` demotion helper | Reuses the ble_extend_not_create window semantics; MULT=0 disables (existing kill switch inherited) |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | `True` | **Rung 2 (options flow)** — persistent per-deploy | `config_flow.py` / `options_flow.py` under advanced automation section | Operator-settable structure knob (some operators may want AWAY comfort fans; kill switch semantics) |
| `SIGNAL_MMWAVE_FAN_DEMOTED` | — | signal string | `domain_coordinators/signals.py` (sibling of `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` at :129) | New event for observability; NEW because no existing signal names the demotion event |
| `OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED` | `"mmwave_fan_demoted"` | source string | `const.py` (sibling of `OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE` at :489) | Diagnostic — shows in `binary_sensor.<room>_occupancy` attribute so operator can see WHY the room went vacant |
| `_fan_on_since: Dict[str, datetime]` | — | tracker field | `ZonePresenceTracker.__init__` (presence.py, sibling of `_fan_on_rooms` at :480) | Adds fan-on **duration** so D2 predicate leg (b) can be evaluated. NEW — grep confirmed no existing per-room fan-on-since tracking. |

**Acceptance Criteria**
- **Verify:** every constant appears with a docstring citing this planning doc.
- **Test:** `test_mmwave_corroboration_constants_present` asserts symbols importable.
- **Live:** kill-switch flip (`MMWAVE_FAN_CORROBORATION_ENABLED=False`) at const.py + restart → no `SIGNAL_MMWAVE_FAN_DEMOTED` emits; every stranded demote entry cleared (mirrors `_apply_fan_interference_gate` H-A2 kill-switch drain pattern at presence.py:3427-3443).

### D2: mmWave Fan-Corroboration Demotion (fusion)

Add a WRAPPER around the existing `_compute_fan_interference_rooms` primitive that promotes its verdict to a **demotion** (not extension) when Invariant M conditions hold. The demotion is applied at the same seam that `ble_extend_not_create` uses — the block that admits (or refuses) a hold from a truth-source that is not itself real motion.

**Where the change lands (all four sites; grep verified in Institutional Context):**

1. `presence.py` — new method `_compute_mmwave_fan_demoted_rooms(fan_suspect_rooms) -> List[str]` next to `_compute_fan_interference_rooms` (:3208). Inputs: the existing primitive's flagged set. Adds legs (b) fan-on-duration ≥ grace and (e) motion staleness. Outputs a sorted list.
2. `presence.py` — new tracker field `_fan_on_since` populated by the existing `_handle_fan_change` listener (add a two-line stamp/clear). REUSED handler; NEW field.
3. `presence.py` — the `_room_occupied` derived property (:521-580) already documents its truth-preserving extend semantics. Add a NEW helper `_room_occupied_with_demotion(...)` that consults `_mmwave_fan_demoted_rooms`. **Semantics:**
   - if room is in demoted set AND provenance shows mmwave-sole → return **False** regardless of the hold dict (the demotion overrides both the OR and the extend-hold);
   - otherwise return the existing derived value.
   Consumers of `_room_occupied` are enumerated in `AUDIT_fan_interference_gate_ripple.md` (referenced from presence.py:576) — Reviewer A verifies every one still reads a coherent value; Reviewer D re-enumerates them **including pre-existing** to catch any consumer that would silently break on a room reading vacant-under-mmwave-hold.
4. `coordinator.py` (the room coordinator's `_async_update_data`) — currently reads room occupancy via the entity registry / room's own sensor list. The demotion must also short-circuit the room coordinator's own occupied inference. **Mutation anchor site.** Add a check after the BLE extend-not-create block (:2160) that consults the presence coordinator's demoted set; if the room is demoted, mmwave firings do not create/sustain `STATE_OCCUPIED`.

**Emit the new signal:** every tick that flips a room INTO the demoted set, dispatch `SIGNAL_MMWAVE_FAN_DEMOTED` with payload `{"room_name": r, "reason": "mmwave_sole_fan_on_no_corroboration", "fan_on_since": iso, "last_motion_time": iso_or_none}`. Consumers: D7 observability sensor only. NM opt-in gated by `CONF_STUCK_SIGNAL_NM_ENABLED` sibling (do NOT wire NM in this cycle — noise concern; observability first).

**Truth-preserving invariant (mirrors the extend-hold's invariant, inverted):** the demotion NEVER fires while any of {motion=True, occupancy=True, BLE-trustworthy present in room, camera-person present in zone} is true. That means the worst-case failure is "a fan-suspect room reads vacant slightly earlier than it would have" — which is exactly the operator-desired direction, and by construction cannot silently vacate a room with any non-mmwave corroboration.

**Acceptance Criteria**
- **Verify:** Invariant M holds in every legal-config combination in D5-T7.
- **Sensor:** `binary_sensor.<room>_occupancy` attribute `occupancy_source` reads `"mmwave_fan_demoted"` on the exact tick the demotion first fires.
- **Sensor:** primitive sensor (sensor.py:4500-4550 area) gains an attribute `mmwave_fan_demoted_rooms` (sibling of `fan_interference_rooms`) listing currently-demoted rooms.
- **Test:** `test_mmwave_corroboration.py::test_studya_repro_2026_07_31` — construct the Study A conditions (single mmwave firing, no motion, no BLE, house AWAY, fan on ≥ grace), assert `STATE_OCCUPIED == False` after grace; assert fails on pre-D2 code (Reviewer C mutation anchor).
- **Test:** `test_no_demote_when_ble_present` — same conditions + BLE-trustworthy person → no demotion.
- **Test:** `test_no_demote_when_motion_recent` — same conditions + motion within `MMWAVE_FAN_CORROBORATION_STALE_S` → no demotion.
- **Live:** post-deploy, Study A room shows `occupancy_source=mmwave_fan_demoted` at least once within 24 h if a fan-on/mmwave-only condition recurs. If it never fires organically in 7 days, verify with a controlled test (turn on comfort fan in Study A with door closed, no one present).

### D3: Comfort-Fan House-AWAY Veto (belt-and-suspenders)

Add an AND-guard at every comfort-fan `turn_on` emission site. Guard shape:

```
if house_state ∈ {AWAY, VACATION}
   AND not room_has_trusted_presence(room)   # BLE OR camera OR motion within occupancy_timeout; mmwave EXCLUDED
   AND CONF_COMFORT_FAN_AWAY_VETO_ENABLED:
      return  # veto; log at INFO with reason
```

**Three actuation sites** (per Institutional Context §"Comfort-fan actuation sites"):

1. `automation.py:1784-1804` (`handle_temperature_based_fan_control` turn-on) — REUSE `_get_config`, add helper `_house_state_via_cm()` (thin accessor on the coordinator).
2. `hvac_fans.py` `_set_fan_state` call from `_evaluate_temp_fan` (`:174-450`) — same guard, injected via a shared predicate function to keep the two sites byte-equivalent (helper lives in `presence.py` or a new tiny `fan_veto.py`; either is acceptable — Reviewer B picks the placement they prefer).
3. `actuator_reconciler.py:778` — same guard. This is the DOC-2 third-writer site; without covering it a legitimate reconciler-driven fan-on bypasses the veto (Bug Class #53 repro right here).

**Explicit non-sites (do NOT add veto):**
- `handle_humidity_based_fan_control` (automation.py:1713+) — humidity fans are safety-adjacent (moisture) and were explicitly consolidated as sole-owner room-tier (`hvac_fans.py:291-296`).
- Any bathroom-exhaust path — same reason.
- Any safety-fan / freeze-protection path.
- Manual actuations by the user via HA UI or scripts — the veto is scoped to URA's own `turn_on` service calls in the three comfort-fan sites above.

**Kill switch:** `CONF_COMFORT_FAN_AWAY_VETO_ENABLED = False` at options-flow → predicate returns True unconditionally → identical to pre-D3 behavior. Reviewer B verifies byte-identical no-op path.

**Acceptance Criteria**
- **Verify:** Invariant V holds in every combinatorial test in D5-T7.
- **Test:** `test_comfort_fan_away_veto_room_tier` — house=AWAY, no trusted presence, temp > threshold → no `turn_on` call.
- **Test:** `test_comfort_fan_away_veto_hvac_tier` — same conditions on HVAC-tier path.
- **Test:** `test_comfort_fan_away_veto_reconciler` — same on reconciler path (mutation anchor for the third-writer coverage).
- **Test:** `test_veto_does_not_fire_humidity` — humidity path with same house-state must actuate normally (regression guard for the sole-owner contract).
- **Test:** `test_veto_does_not_fire_sleep_home` — house=SLEEP with occupant in bedroom → no veto (verifies the SLEEP D-AUT reasoning at automation.py:1724-1733 is preserved).
- **Live:** log-scan post-deploy for `"comfort fan veto (house_state=AWAY)"` INFO line at least once when house was AWAY and a comfort fan would have fired; verify no unintended veto by checking that at least one comfort fan actuation occurred while house was HOME (baseline preservation).

### D4: (PARKED) Layer-2 adjacent-BLE relaxation

See Marginal-Benefit Decomposition. Do NOT build; evidence-triggered.

### D5: Test Suite (per-site mutation authority)

**T1** — `test_mmwave_fan_corroboration_constants_present` (D1).
**T2** — Study A repro fixture (D2, mutation anchor for `_compute_mmwave_fan_demoted_rooms` at presence.py new site).
**T3** — Fan-recheck no-regression: replay a fan-recheck-release sequence, assert `OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE` counter and `_fan_recheck_mmwave_history_ticks` behavior are byte-identical pre- and post-cycle.
**T4** — All three D3 veto site tests (mutation anchors per site — Reviewer C edits each site's guard to a no-op individually and confirms exactly ONE test in T4 fails).
**T5** — Humidity/safety-fan non-veto tests (regression guard for the sole-owner and safety exemptions).
**T6** — Kill-switch tests: both `MMWAVE_FAN_CORROBORATION_ENABLED=False` and `CONF_COMFORT_FAN_AWAY_VETO_ENABLED=False` — assert byte-identical to pre-cycle for the covered code paths (mutation-anchored). Verify hold-drain on flip (D2 kill switch flip must clear stranded demoted entries, mirroring the `_apply_fan_interference_gate` H-A2 pattern).
**T7 — Config-boundary/combinatorial matrix (Tier 3 requirement).** Cross-product of the operator-independent knobs at extremes:
- `house_state ∈ {AWAY, VACATION, HOME_DAY, HOME_NIGHT, SLEEP}` × `fan_on_duration ∈ {0, grace-1, grace, grace+1}` × `last_motion_age ∈ {0, stale-1, stale, stale+1, None}` × `ble_present ∈ {True, False}` × `mmwave ∈ {True, False}` × `CONF_COMFORT_FAN_AWAY_VETO_ENABLED ∈ {True, False}` × `MMWAVE_FAN_CORROBORATION_ENABLED ∈ {True, False}`. Prune to legal-and-interesting combinations (~40-60 cases). At each, assert Invariants M and V hold or gracefully non-fire.
**T8** — Legal-config edge cases explicitly listed:
- Room with `motion_sensors=[]` + one mmwave (Study A shape) — D2 fires as expected.
- Room with mmwave-only where the sole mmwave is `unavailable` — no demote (nothing to demote), no crash. Reviewer D repro target.
- Room with two mmwaves, one `unavailable`, other firing — same D2 semantics apply to the firing one (dead sibling is invisible to the primitive).
- `MMWAVE_FAN_CORROBORATION_STALE_S = 0` (kill via inheritance from `BLE_MOTION_CONFIRM_MULTIPLIER=0`) — demotion path never gates; identical to pre-cycle.

**Test authority requirement (Bug Class #62):** every test in T1-T8 MUST exercise the PRODUCTION helper / property / actuation function. Grep review during Reviewer C: no test may reimplement Invariant M or V arithmetic; if a test's assertion could pass with a hand-rolled shim, it does not count.

### D6: (PARKED) Dead/stuck mmwave in stuck-signal watchdog

See Marginal-Benefit Decomposition. Evidence-triggered.

### D7: Observability (rung-2a conventions)

Route through coordinator state per rung-2a conventions (do NOT inject a new sensor platform).

- Extend the existing primitive sensor (sensor.py:4500-4550, `fan_interference_rooms` attr) to also expose `mmwave_fan_demoted_rooms` (sorted list) and `mmwave_fan_demoted_active` (bool).
- Extend `binary_sensor.<room>_occupancy` attributes (binary_sensor.py:470-550 area, sibling of `fan_interference_suspect`): `mmwave_fan_demoted` (bool), `mmwave_fan_demoted_since` (iso or None).
- Extend `binary_sensor.<room>_occupancy` attribute `occupancy_source` to include `"mmwave_fan_demoted"` when D2 fires.
- INFO log line at each D3 veto: `"comfort fan veto (house_state=%s, room=%s) — no trusted presence"`.

**Acceptance Criteria**
- **Sensor:** `sensor.presence_primitive` (or the actual primitive sensor name — confirm during build) shows `mmwave_fan_demoted_active=True` when at least one room is demoted.
- **Sensor:** `binary_sensor.<room>_occupancy` attribute `mmwave_fan_demoted` flips True on the demotion tick.
- **Live:** the primitive sensor's `mmwave_fan_demoted_rooms` attribute round-trips through the /ura-v6 dashboard's room-diagnostic tile without display errors.

### D8: Live Validation (Review D / post-deploy)

- **Live-1:** log-scan for at least one `SIGNAL_MMWAVE_FAN_DEMOTED` emit within 24 h of the first fan-on/mmwave-only condition (organic OR controlled test in Study A per D2 Live).
- **Live-2:** log-scan for at least one D3 veto INFO line within 24 h of an AWAY period where a comfort fan would have fired.
- **Live-3:** verify no unintended demotes — spot-check 3 HOME_DAY periods where mmwave-only rooms with fans on had someone present; assert no demote fired.
- **Live-4:** verify no fan-recheck counter drift — pull the `fan_recheck_*` attributes on 3 rooms with recheck enabled and compare to a pre-deploy baseline snapshot (D8 gate).
- **README-writeback (MANDATORY per CLAUDE.md):** after Live-1..4, the `README_v<version>.md`'s prospective Live section is replaced with a `Validated <date>` table (PASS/FAIL per criterion + concrete observed evidence).

---

## Files touched (concrete list for the builder)

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | Add `MMWAVE_FAN_CORROBORATION_ENABLED`, `MMWAVE_FAN_CORROBORATION_GRACE_S`, `OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED`, `CONF_COMFORT_FAN_AWAY_VETO_ENABLED`. |
| `custom_components/universal_room_automation/config_flow.py` + `options_flow.py` | Expose `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` in the advanced automation section (rung-2 knob). |
| `custom_components/universal_room_automation/domain_coordinators/signals.py` | Add `SIGNAL_MMWAVE_FAN_DEMOTED` next to `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` (:129). |
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | Add `_fan_on_since` tracker field (init at :480 area). Extend `_handle_fan_change` to stamp/clear it. Add `_compute_mmwave_fan_demoted_rooms` next to `_compute_fan_interference_rooms` (:3208). Add `_room_occupied_with_demotion` helper OR extend `_room_occupied` property (Reviewer B picks; docstring must state which). Emit `SIGNAL_MMWAVE_FAN_DEMOTED` on edge-into-demoted. Kill-switch drain path in the wrapper. |
| `custom_components/universal_room_automation/coordinator.py` | Room coordinator `_async_update_data` — after BLE extend-not-create block (:2160), consult presence's demoted set; short-circuit mmwave-sole occupancy creation/sustain. |
| `custom_components/universal_room_automation/automation.py` | Comfort-fan veto at `handle_temperature_based_fan_control` turn-on site (:1784-1804). |
| `custom_components/universal_room_automation/hvac_fans.py` | Same veto at HVAC-tier turn-on site (`_evaluate_temp_fan` / `_set_fan_state` boundary). |
| `custom_components/universal_room_automation/actuator_reconciler.py` | Same veto at reconciler comfort-fan turn-on (:778 area). |
| `custom_components/universal_room_automation/binary_sensor.py` | Add `mmwave_fan_demoted`, `mmwave_fan_demoted_since` attrs (:470-550 area). |
| `custom_components/universal_room_automation/sensor.py` | Add `mmwave_fan_demoted_rooms`, `mmwave_fan_demoted_active` attrs (:4500-4550 area). |
| `quality/tests/test_mmwave_corroboration.py` | NEW test module, T1-T8. |
| `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md` | NEW D0 audit table. |
| `docs/Coordinator/PRESENCE.md`, `docs/Coordinator/HVAC.md`, `docs/Coordinator/HOUSE_MANUAL.md` | Doc updates post-ship (add mmwave-fan-demoted contract next to §3.1 step 8 ble_extend_not_create). |

---

## Reviews (Tier 3 — four framing-disjoint reviews, run in parallel)

**Reviewer A — local correctness.** Per-site arithmetic + guard logic + None handling + isinstance guards on `_fan_on_since` reads + `dt_util.utcnow()` timezone-awareness (Bug Class #21) + enum/string comparison against actual const strings (Bug Class #22 — check that `"AWAY"` and `"VACATION"` match the actual HouseStateMachine .value strings). Verify humidity/safety-fan exemption regex-tight (no accidental catch).

**Reviewer B — integration / state-machine integrity.** Kill-switch flips produce byte-identical no-op paths for all four sites. `_room_occupied` property still returns coherent values to every consumer enumerated in `AUDIT_fan_interference_gate_ripple.md`. HVAC defer gate via `check_zone_occupancy_confidence` is not accidentally regressed (a fan-suspect room going demoted must not cause an HVAC retreat regression the extend-hold was originally designed to prevent — the veto covers the actuator side, so HVAC's read of a demoted room going vacant is legitimate; verify the composition). Fan-recheck counters unaffected. Boot-transient path: on restart, `_fan_on_since` is empty; demotion cannot fire on the first tick — the fan must have been on for ≥ grace, and the timer starts at first observation.

**Reviewer C — test authority via real per-site source mutation.** For each of the four load-bearing sites (D2 demotion helper; three D3 veto sites), Reviewer C **edits production source to neuter that one site** (comment out the guard / return early), runs the full suite, and confirms **exactly one specific test in T2/T4** fails. A site whose bypass leaves the suite green is an untested site = unacceptable. Then restore. **MANDATORY:** disable Python bytecode + clear `__pycache__` before mutation (per `feedback_mutation_verification_pycache_staleness.md`) — a stale .pyc will falsely PASS a mutation. Also verify tests drive PRODUCTION code paths (Bug Class #62), not hand-rolled shims.

**Reviewer D — adversarial completeness / diff-blind.** State Invariants M and V in falsifiable form. Re-enumerate the ENTIRE comfort-fan actuation surface — **including pre-existing code, not just the diff** — and every site that can flip `STATE_OCCUPIED` True under mmwave-alone conditions. Every flagged leak must come with a **concrete, legal-config reachable repro** (values + state; e.g. "house=AWAY, room in mmwave-only class, mmwave fires True at t=0, fan turns on at t=1, second mmwave-only room has BLE-trustworthy person, adjacent-room map includes both — does D2 spuriously demote room 2?"). Explicit re-enumeration targets:
- Every `_safe_service_call` or direct `hass.services.async_call` with domain in {`fan`, `switch`, `homeassistant`} and service `turn_on` where the entity list could contain a comfort-fan (grep across `custom_components/universal_room_automation/**/*.py`).
- Every write to `STATE_OCCUPIED = True` or `data[STATE_OCCUPIED] = True` in `coordinator.py` and `presence.py`.
- Every consumer of `_room_occupied` in `AUDIT_fan_interference_gate_ripple.md` — verify none of them CREATE occupancy from a mmwave-only read that bypasses the demotion.

Reviewer D must produce either a SHIP verdict with the invariant proof, or a list of leaks each with a legal repro (no hypotheticals).

**Between reviews:** fix all CRITICAL/HIGH from any reviewer. Re-run all four framings if a fix touches load-bearing code (Bug Class #53 corollary — a fix can reveal an N+1th site).

---

## Deploy gates (Tier 3 stringency)

1. All four reviewers return SHIP (or SHIP-after-fix) on Invariants M and V.
2. **Orchestrator independent verification BEFORE deploy:** the orchestrator personally re-greps every fan actuation site + every `STATE_OCCUPIED` write, and re-runs Reviewer C's per-site mutation on the four load-bearing sites (D2 demotion, three D3 vetos). Do NOT trust reviewer summaries — re-execute (per v5.5.3 D-HIGH-1 lesson).
3. **Pre-deploy snapshot of affected counters:** row-per-room dump of current `fan_interference_hold_active`, `occupancy_source`, and `fan_recheck_*` attributes. Post-deploy Live-4 diffs against this.
4. **Operator checkpoint BEFORE deploy** (not just before build). Surface: the invariant proof, the four review summaries, the D5-T7 combinatorial results, and the D0 audit table. Get explicit go.
5. Deploy via `./scripts/deploy.sh <version> "mmwave fan corroboration + AWAY comfort-fan veto" "<release notes>"`.
6. **Live Validation (Review D live).** Run all D8 checks; **write-back into `README_v<version>.md`** as a `Validated <date>` PASS/FAIL table before closing the cycle.

---

## Plan Completion Tracking (post-implementation checklist)

Explicitly document any planned item skipped or deferred. Expected deferrals (already scoped):
- **D4** (Layer-2 adjacent-BLE relaxation) — parked with evidence trigger.
- **D6** (dead/stuck-mmwave in stuck-signal watchdog) — parked with evidence trigger.
- **Layer-3 pause-and-recheck expansion** — parked with evidence trigger.
- **Presence.md / HVAC.md / HOUSE_MANUAL.md** doc updates — deferred until post-live-validation so the doc reflects observed, not prospective, behavior.

Any additional deferrals accumulated during build MUST be listed in the cycle close-out with `WHY` and `where tracked`.

---

## Amendment 2026-07-31 (operator input): camera corroboration must be PER-ROOM COVERAGE, not zone-scoped

Operator: cameras exist only in COMMON AREAS plus Study A (and Study A especially when away). No private room (bedrooms, most rooms) has camera coverage.

Consequence for the invariant-M camera leg as originally drafted ("no camera-person signal for R's **zone**"): zone-scoping is wrong in BOTH directions:
1. **It defeats incident #1.** The 2026-07-26 Master Bedroom case was house-OCCUPIED with people elsewhere. If "elsewhere" is a common area with a camera in the same zone, the zone-scoped camera leg reports person-present → demotion blocked → the phantom survives — the exact case D2 exists to fix.
2. **It can never legitimately corroborate a private room**, because no private room has a camera. The leg is either spuriously satisfied (by common-area traffic) or vacuously false. Both are wrong.

**Revised rule:** the camera leg participates ONLY for rooms with actual camera coverage (per a static coverage map: Study A + the common areas the census cameras see). For uncovered rooms the camera leg is ABSENT — the corroboration bar is PIR + BLE only. The truth-preserving invariant at the demotion site is updated accordingly: `camera-person present **in a camera-covered room's own coverage**`, never zone-wide.

**D0 addition:** the audit must produce the per-room camera-coverage map (from camera_census area mappings + operator confirmation), alongside the mmWave-only inventory and the PIR-exists-but-unwired list (Study A `binary_sensor.invisoutlet_b7d0_motion` is the known instance of the latter).

**Knob:** the coverage map is rung-1 (module constant / derived from census area config) — changing which rooms count as camera-covered should require review, not a dashboard toggle.

---

## Amendment 2 — 2026-07-31 (operator: "make sure we're not doubling up"): D2 RE-SCOPED after fan-recheck root-cause

Verification of the no-duplication challenge found the smoking gun:

**Study A's phantom was a CONFIG-CLASSIFICATION bug, not a missing mechanism.** The existing fan-recheck (v5.23.0, presence_fan_recheck.py) is precisely a fan↔mmWave demotion protocol (pause fan → clean-air mmWave observation → drop = release) and was FULLY ENABLED for Study A (CM master `fan_recheck_enabled=True` + room switch on + L2 allowed). It never fired because `coordinator.py:1928-1933` derives `occupancy_source` from the CONFIG BUCKET, not the device: Study A's working Zigbee mmWave lives in `occupancy_sensors` (source string `"occupancy_sensor"`), while `mmwave_sensors` holds only the dead Athom. The recheck's condition-2 gate (`not_mmwave_sole`) therefore vetoed on every tick. The same blindness applies to the v4.7.20/22 fan-interference gate and WOULD have applied to D2 as originally drafted.

**Consequences:**
1. **D0 gains a mandatory sweep: mmWave devices misfiled under `occupancy_sensors`** across all ~41 rooms (match on entity naming `mmwave`/`presence` + device class vs bucket). Reclassification (move to `mmwave_sensors`, wire available PIRs into `motion_sensors` — Study A: `binary_sensor.invisoutlet_b7d0_motion`) is a ZERO-CODE fix that hands each such room to the EXISTING recheck machinery.
2. **D2 (new demotion) is DEMOTED from the core to a parked deliverable.** Its coverage substantially duplicates fan-recheck once buckets are correct. Evidence trigger to un-park: post-reclassification, a phantom survives ≥1h in a room where recheck is enabled and its veto counters show it evaluated (i.e., the residue cases — rate-cap exhaustion, recheck-ineligible rooms — prove material).
3. **D3 (house-AWAY comfort-fan veto) remains the novel core** — nothing existing prevents a comfort fan turning ON into a phantom in an empty house; fan-recheck is reactive, rate-limited (2/hr), and cannot precede the turn-on.
4. Revised simple version: **D0 (audit + reclassify) + D3 (veto) + D5/D7 (tests/observability) + D8**. Tier-3 review discipline unchanged; Invariant M is now *delivered* by (existing recheck + correct classification) and D must attack it there, not in new code.

**Operator note (2026-08-01):** the Master Bathroom InvisOutlet is TRUSTED (per operator) — its behavior there is fine, unlike the Study A unit (removed for holding presence without cause). Do not migrate Master Bathroom off it; it remains the room's primary presence source, now correctly classified in `presence_sensors` (mmWave bucket) so recheck/corroboration machinery governs it. Trust is per-unit/per-placement, not per-product.

---

## Known residuals (fix-up pass 2026-08-01)

Two adversarial-review findings were adjudicated as accepted residuals rather than in-cycle fixes. Both are captured here so future cycles do not re-litigate.

### R1 — B-H2: fan already ON when house transitions to AWAY

**Shape:** the D3 veto is scoped to `turn_on` paths (all three actuation sites: `automation.py`, `hvac_fans.py::update`, `actuator_reconciler.py::_resolve_fan`). If a comfort fan is ALREADY running when house_state transitions to AWAY (e.g. everyone leaves a hot room), no OFF-edge is issued by D3 — the fan keeps running until organic coverage catches it.

**Why not an OFF-edge companion:**
1. **Fights manual-remote turn-ons while away.** An operator can legitimately turn a fan ON from their phone while the house is AWAY (guest arriving early, pre-cooling before returning). An OFF-edge companion would immediately kill that action; there is no clean way to distinguish "URA armed this" from "operator armed this" at the OFF-edge moment.
2. **Post-reclassification, fan-recheck now covers the shape organically.** After the D0 bucket-reclassification sweep, `presence_fan_recheck.py` reliably fires against the exact residual: fan-on + mmWave-only presence → recheck pauses fan → clean-air mmWave drops → occupancy releases → the vacancy path turns the fan OFF (`FanController._evaluate_temp_fan` vacancy branch + `handle_temperature_based_fan_control` vacancy-hold expiry). This is exactly the fan-noise-mode-2 coverage the v5.23.0 recheck was built for; correct bucket classification (per Amendment 2) is what makes it fire.
3. **D-HIGH-1 already closes the acute variant.** The 4th actuation site — `restore_after_recheck` — WAS vulnerable to a mid-recheck AWAY transition re-arming the fan; that specific path is now guarded by the veto (see D3 fix-up pass R2).

**Evidence trigger to un-park:** a documented case where a fan-on + AWAY residue survives ≥1 recheck cycle (or ≥30 min in a recheck-ineligible room) after the reclassification sweep is live.

### R2 — D-LOW-1: AI-rule executor can `fan.turn_on` unvetoed

**Shape:** operator-authored rules dispatched via the AI-rule executor call HA services directly and do NOT route through `should_veto_comfort_fan`. An operator rule with a `fan.turn_on` action bypasses the veto entirely.

**Why deferred:** operator-authored rules are a distinct trust domain — the operator has explicitly authored the intent. Vetoing operator rules from a URA-internal predicate would violate the "operator override wins" contract the AI-rule executor is built on. If a specific rule is misbehaving, the correct fix is to edit the rule (or add a house_state condition to it), not to layer URA guards over operator-authored actions.

**Evidence trigger to un-park:** an AI-rule-triggered comfort-fan turn-on into an empty house that the operator flags as unintended (i.e. the rule was buggy but the veto could have caught it). At that point we would evaluate a scoped guard on AI-rule dispatch — not an unconditional veto.
