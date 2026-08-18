# PLANNING — Sensor Trust / Exclusion Program (shared primitive + chatter client)

**Program name (operator-coined 2026-08-18):** **Sensor Trust / Exclusion Program (STEP)** — the unified umbrella for room-tier sensor-vote untrust. STUCK-SENSOR-1 (v5.75.0 SHIPPED), SENSOR-CAPABILITY-1 (SHIPPED), and this cycle are ALL parts of STEP, not separate initiatives. This planning doc scopes the SHARED PRIMITIVE + the first NEW client (physics-based chatter). It re-parents the two shipped cycles under STEP retroactively for coherence.

**This cycle's card:** `SENSOR-HEALTH-SURFACING-1` (retained for kanban continuity; re-scoped).
**Tier:** **2-DB** (three framing-disjoint reviews + Live). Operator elevation 2026-08-18: shared-primitive change touching the room-tier occupancy fusion.
**Created:** 2026-08-18 (full rewrite after two DO-NOT-SHIP reviews of the initial surface+notify design).
**Origin:** `AUDIT_roadmap_undone_worthwhile.md` #1; `INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md`.

**Depends on:** RESEARCH_sensor_chatter_definition_prior_art.md (IN FLIGHT — BGP route-flap damping, CAN babbling-idiot / bus-guardian, glitch-filter minimum-dwell, Nagios flap detection, WSN fault taxonomies). **The chatter DEFINITION is TBD-pending that research.** This plan explicitly does NOT author a first-principles definition; §4-D2 slots it in once the research lands.

---

## 0. Feasibility verdict — up front

**BUILDABLE NOW for the shared primitive + the chatter client.** Rationale below distinguishes the two dependency chains the operator asked about.

### 0.1 The shared exclusion primitive already exists in ad-hoc form

Grep-verified: `stuck_sensors: set[str]` is TODAY the room-tier "untrust a sensor's vote / exclude from occupancy fusion" primitive. Six consumer sites in `coordinator.py`:

- `coordinator.py:2712` — motion_detected: `for sensor in motion_sensors if sensor and sensor not in stuck_sensors and self._is_sensor_on(sensor)`
- `coordinator.py:2719` — presence_detected: same filter shape
- `coordinator.py:2726` — occupancy_detected: same
- `coordinator.py:2740, 2748, 2756` — `any_sensor_active` legs across all three kinds

STUCK-SENSOR-1 v5.75.0 already writes into that set via `_promote_dutycycle_to_exclusion` (`coordinator.py:2141-2187`, called at `:2567-2569`). P22 continuous-on writes via `_p22_stuck_sensor_set` (`:2498`). So the CONSUMER contract exists; there is no missing "exclusion path" that STUCK-SENSOR-1 or this cycle is blocked on building.

**What DOES need building** — and what STEP D1 is about — is the FORMALIZATION of this set into a proper shared primitive with a documented API, invariants, and per-client entry points so future detectors compose cleanly rather than each open-coding a `stuck_sensors.add(...)` at the tick site. Today STUCK-SENSOR-1's addition is architecturally invisible (it looks like it's part of the D2 duty-cycle detector), and a chatter client that just piggybacks the same way would compound the coupling.

### 0.2 Chatter (physics, corroborator-free) can ship independently of any remaining SENSOR-CAPABILITY-1 work

**Chatter detector:** the operator's key architectural distinction — chatter is quarantine-ALWAYS on a physics violation the definition of which a correctly-working sensor CANNOT satisfy. No corroborator is needed to distinguish "chatter" from "legit"; the physics floor does that intrinsically. Chatter therefore has **NO dependency on SENSOR-CAPABILITY-1** (which exists to separate corroborator role from candidate role for detectors that DO need corroboration).

**Stuck (dutycycle) detector:** corroboration-gated (can't distinguish "stuck-on" from "sleeping person" without a corroborator). Its dependence on SENSOR-CAPABILITY-1 is via `resolve_role(..., RoleQuery.CORROBORATOR_FOR_ROOM)` — which is SHIPPED (`coordinator.py:1608-1704`, migrated in SENSOR-CAPABILITY-1 D3 and consumed by STUCK-SENSOR-1 v5.75.0 D1). The residual capability work (`STUCK-D2-DEMOTION-ROLE-MIGRATE-1` — `_d2_motion_sensors_present` gate not yet on `resolve_role`) affects the D2 demotion / detection LATCH but not the exclusion PROMOTION. So the stuck client is also not blocked on the shared primitive being formalized — it merely benefits from the formalization.

### 0.3 The formalized shared primitive itself does NOT depend on SENSOR-CAPABILITY-1

STEP D1 (formalize the shared exclusion primitive) is a pure refactor of the six existing consumer sites onto a documented API surface + a lightweight per-tick `SensorExclusionSet` object owned by the RoomCoordinator. It preserves byte-identical behaviour for every existing writer (P22, STUCK-SENSOR-1 D1). It has no dependency on capability layer refinement.

### 0.4 Ship sequence recommendation

1. **STEP D1 (shared primitive formalization)** + **STEP D2 (chatter client)** ship TOGETHER in this cycle. Chatter is the first NEW client of the formalized primitive; formalizing it while adding the first new client is the moment where the API contract is proven by having two independent writers (STUCK-SENSOR-1 as pre-existing writer, chatter as new writer).
2. **Stuck client full role migration** (`STUCK-D2-DEMOTION-ROLE-MIGRATE-1`) sequences AFTER, once SENSOR-CAPABILITY-1's remaining hardening lands. Not part of THIS cycle.
3. **Substrate-level chatter filter** (`SUBSTRATE-STUCK-FILTER-1`) — separate cycle; blast radius is zone + house tier; explicit non-goal here.

### 0.5 Residual seam called out for reviewers

The occupancy substrate's per-kind bucket (`occupancy_substrate._raw_state[room][kind]`) is set True whenever ANY entity of that kind fires on; it does NOT re-filter through the shared exclusion primitive. Result: a room-quarantined chatterer's on-edges still flip the substrate bucket, which the ZONE tier reads. This is the SAME residual seam STUCK-SENSOR-1 accepted (§"No propagation to zone/house tier"); this cycle inherits that decision. The follow-up card `SUBSTRATE-STUCK-FILTER-1` covers a future closure across ALL clients (chatter and stuck together).

---

## 1. Model (operator-decided 2026-08-18)

- **Quarantine = untrust from FUSION.** The shared primitive removes the sensor's VOTE from the room's occupancy computation. It does NOT force-vacant, it does NOT interlock any actuator, it does NOT propagate.
- **Fusion carries the safety.** Room occupancy = fusion of REMAINING trusted votes. If a working sensor / BLE / camera / occupancy_sensor still says present → room stays present. If ONLY the quarantined sensor claimed present → room correctly goes vacant. This is the whole safety story.
- **DETECTOR-per-client, gate-per-client.** The shared primitive is client-agnostic; each detector owns its own promotion gate:
  - **Chatter:** quarantine-ALWAYS on physics violation, no corroboration gate at detection. The definition IS the safety.
  - **Stuck (STUCK-SENSOR-1 today):** corroboration-GATED + sleep-doctrine gated + kill-switch gated. Needs corroborator infrastructure (SENSOR-CAPABILITY-1) to distinguish stuck from sleeping.
- **Auto-release per client, symmetric with detection.** Chatter release = quiet-window (mirrors `ActuatorReconciler.check_quarantine_release`, `actuator_reconciler.py:949-1000`). Stuck release = existing per-tick re-evaluation (already in place; not owned by this cycle).
- **Physics definition of chatter: TBD.** The operator explicitly wants the chatter definition grounded in prior art (BGP RFD, CAN bus-guardian babbling-idiot cutoff, glitch-filter minimum-dwell, Nagios flap detection, WSN fault taxonomies) so it uses criteria a correctly-working sensor CANNOT satisfy — sub-hardware-dwell / rate-ceiling / duty-cycle-impossibility — NEVER a raw transitions/min. `RESEARCH_sensor_chatter_definition_prior_art.md` is IN FLIGHT; this plan defers §4-D2's definition to it.

**Reversal of prior non-goal, explicit:** the shipped-but-DO-NOT-SHIP-reviewed build was scoped "chatter does NOT exclude from occupancy — notify-only." **That non-goal is REVERSED.** Chatter DOES exclude, through the shared fusion-preserving primitive.

---

## 2. Falsifiable invariants (Reviewer D falsifies these)

Two families of invariants: shared-primitive invariants (STEP-EXCLUDE-*) and chatter-client invariants (INV-CHATTER-*). The chatter physics-definition-specific invariant is deferred to the research doc; INV-CHATTER-{1,3,4} are definition-agnostic and can be finalized now.

### 2.1 Shared primitive (STEP D1)

- **STEP-EXCLUDE-1 (fusion contract):** For any tick where a Tier-1 sensor `s` is in the room's `SensorExclusionSet`, the room's `motion_detected` / `presence_detected` / `occupancy_detected` MUST equal the fusion of the room's REMAINING trusted sensors (i.e. `s` contributes 0). AND: if any other entity `t` of any Tier-1 kind reads `on` and is NOT excluded, the appropriate occupancy leg MUST read True. (No detector may transitively suppress a non-excluded sensor's vote through the shared primitive.)
- **STEP-EXCLUDE-2 (byte-identity under empty-clients):** If no client-detector promotes an entity into the set for this tick (both P22 and STUCK-SENSOR-1 quiet, chatter client disabled), the room's occupancy computation MUST be byte-identical to pre-cycle behaviour.
- **STEP-EXCLUDE-3 (client isolation):** A promotion by client A (e.g. chatter) that later becomes ineligible MUST NOT release a promotion by client B (e.g. STUCK-SENSOR-1) whose gates still hold. Release-per-client, not release-per-set.
- **STEP-EXCLUDE-4 (no zone/house propagation):** The set is scoped to the room-tier fusion at `coordinator.py:2712-2756`. It MUST NOT be read by any zone-tier tracker or house-tier aggregator directly. (Existing indirect propagation through corrected room-tier signals into substrate consumers is by design.)

### 2.2 Chatter client (STEP D2)

- **INV-CHATTER-1 (safety):** For any sensor `s` the chatter detector flags per §4-D2 (definition TBD, physics-based), `s` MUST appear in the shared exclusion set this tick AND STEP-EXCLUDE-1 MUST hold.
- **INV-CHATTER-2 (correctness — definition-anchored):** DEFERRED to the research doc. The invariant SHAPE is fixed: "a sensor whose observed behaviour does not violate the definition MUST NOT be flagged." The specific definition (and thus the specific busy-real fixture that discriminates) comes from the research.
- **INV-CHATTER-3 (release):** After `CHATTER_RELEASE_QUIET_S` seconds with ZERO state transitions AND entity currently available, `s` MUST be released from chatter quarantine on the next tick AND `fire_stuck_signal_recovered(kind="chatter", key=(s,))` MUST fire once so the per-day latch clears. STEP-EXCLUDE-3 (client isolation) MUST hold: releasing chatter's promotion of `s` MUST NOT release any concurrent STUCK-SENSOR-1 promotion of `s`.
- **INV-CHATTER-4 (kill-switch byte-identity):** With `CHATTER_QUARANTINE_ENABLED = False`, chatter client contributes 0 promotions to the shared set. STEP-EXCLUDE-2 hold-condition satisfied at the chatter axis.

**Discriminator (operator-mandated acceptance-criterion shape):** the busy-real vs chatter-fault fixture pair for INV-CHATTER-2 is authored ONCE the research doc lands and specifies the un-fakeable criterion. Requirement: identical raw rate, opposite verdicts. If any proposed acceptance test produces identical outcomes on the pair, it does not discriminate.

Reviewer D re-enumerates STEP-EXCLUDE-{1..4} across every consumer + every client (Bug Class #53 shape).

---

## 3. Institutional context verified (REUSED / NEW per addition)

### 3.1 REUSED (the reason this cycle is contained)

| Proposed | Verdict | Evidence |
|---|---|---|
| Room-tier vote exclusion | **REUSED — SHIPPED, ad-hoc** | `stuck_sensors` filter at `coordinator.py:2712, 2719, 2726, 2740, 2748, 2756`. STEP D1 formalizes it. |
| Existing writer: P22 continuous-on | **REUSED** | `_p22_stuck_sensor_set` at `coordinator.py:2498`. STEP D1 keeps this writer's contract byte-identical. |
| Existing writer: STUCK-SENSOR-1 D1 dutycycle | **REUSED** | `_promote_dutycycle_to_exclusion` at `coordinator.py:2141-2187`, called at `:2567-2569`. STEP D1 keeps byte-identical. |
| Corroborator-role infrastructure | **REUSED** | `resolve_role(RoleQuery.CORROBORATOR_FOR_ROOM)` at `coordinator.py:1608-1704`. Not consumed by chatter (physics is corroborator-free); relevant only to the stuck client already using it. |
| Boot-settle gate | **REUSED** | `self._d2_boot_settle_done()` at `coordinator.py:1843-1854`. Chatter detector MUST gate on it. |
| NM emit + per-day dedup + kill switch | **REUSED** | `_stuck_signal_nm.fire_stuck_signal(kind="chatter", ...)`, `_LATCHES` at `_stuck_signal_nm.py:47`, `CONF_STUCK_SIGNAL_NM_ENABLED` at `config_flow.py:6575`, `STUCK_SIGNAL_NM_HAZARD_TYPE = "stuck_signal"` at `const.py:3778`. Append `"chatter"` to the sub-classification comment at `const.py:3773-3776`. |
| Recovery discharge | **REUSED** | `fire_stuck_signal_recovered` — used today by actuator flap release at `actuator_reconciler.py:975-989`. |
| Auto-release pattern | **REUSED (adapted)** | `ActuatorReconciler.check_quarantine_release` at `actuator_reconciler.py:949-1000`. Stability-window + zero-transitions + availability check. Chatter client mirrors the shape. |
| Sensor kind → CONF bucket | **REUSED** | `occupancy_substrate._KIND_TO_CONF` at `occupancy_substrate.py:82-86`; `TIER1_KINDS` at `const.py:342`. |
| Surface: `UnavailableEntitiesSensor` with `reason="chattering"` | **REUSED, EXTENDED (kept from prior build)** | `sensor.py:1677-1900`. Mirror the flapping-actuator D2.11 branch. Consumer: operator dashboards only; no trust code reads. |
| Substrate state-change listener | **REUSED (piggyback via `subscribe()`)** | `OccupancySubstrate.subscribe(cb)` at `occupancy_substrate.py:764-783`. Chatter detector subscribes here — no new `async_track_state_change_event` registration; Bug Class #38 discipline inherited. |

### 3.2 NEW (grep-justified)

| Proposed | NEW justification |
|---|---|
| `SensorExclusionSet` shared primitive (formalized API around today's `stuck_sensors`) | Today's `stuck_sensors` is a bare `set[str]` mutated in-place by multiple writers at the tick site. No API, no invariant enforcement, no per-client provenance, no test surface. Formalization adds an object with `promote(client, entity, reason)` / `release(client, entity)` / `is_excluded(entity)` / `provenance(entity)` methods. Client isolation (STEP-EXCLUDE-3) is enforced by tracking which clients promoted each entity. |
| Physics chatter detector | Grep `chatter` in `custom_components/`: zero code hits. All `flap`-family code is actuator availability quarantine (D2.11). No existing detector implements physics-based sensor-value oscillation. Definition itself TBD-research. |
| `_chattering_entities: set[str]` | Sibling scoping specifically for the diagnostic surface (D5) — lets the operator distinguish chatter from stuck/continuous causes. `SensorExclusionSet.provenance()` provides the machine-readable equivalent. |
| `CHATTER_*` module constants | Follow "Numbers Get Knobs" ladder — §5. |

### 3.3 Prior planning docs consulted

- `docs/planning/INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` — founding incident + the class both shipped detectors are blind to.
- `docs/planning/PLANNING_stuck_sensor_consequence.md` (v5.75.0 SHIPPED) — full read. The exclusion path this cycle formalizes. The "no propagation to zone/house" ruling this cycle inherits. STUCK-SENSOR-1 hereby retroactively re-parented under STEP.
- `docs/planning/PLANNING_sensor_capability_vs_role.md` — retroactively re-parented under STEP as the capability layer supporting corroboration-gated clients. Does NOT gate the chatter client (physics doesn't need corroborators).
- `docs/planning/PLANNING_stuck_signal_watchdog.md` — parent cycle for the NM surface (`fire_stuck_signal` + latch).
- `docs/planning/PLANNING_signal_trust_ledger_abstraction.md` §Criterion 4 (2026-08-13 amendment) — `chatter` present in the MANIFEST as **DEFERRED — no production site**. This cycle CREATES the production site; ledger migration remains separate. Reviewer A owns the shape-compatibility cross-check against `quality/fixtures/ledger_golden/MANIFEST.json` "chatter_adjudication" block.
- `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md` Finding 6 — 6 rooms with no PIR. Under physics-based chatter definition, no-PIR rooms ARE covered (physics is intrinsic to the sensor, not to the room).
- `docs/planning/AUDIT_corroborator_options.md` — mmwave-mmwave non-corroboration ruling. Relevant to stuck client, not chatter.

### 3.4 Memory bodies pulled

- `feedback_wire_in_anchor_mandatory.md` — per-site behavioral anchor + neuter drill per deliverable (§4 acceptance).
- `feedback_hollow_test_anchors.md` — busy-real vs chatter-fault fixture pair as primary defense; per-site source mutation for the chatter detector.
- `feedback_falsify_before_asserting.md` — STEP-EXCLUDE-{1..4} + INV-CHATTER-{1,3,4} in falsifiable form; INV-CHATTER-2 shape fixed, contents deferred to research.
- `feedback_mutation_verification_pycache_staleness.md` — `PYTHONDONTWRITEBYTECODE=1` + cleared `__pycache__` for drills.
- `feedback_suppression_needs_discharge.md` — per-day NM latch explicit discharge (recovery NM, calendar rollover, release scan backstop).
- `feedback_measure_before_build.md` — D0 recorder probe is a hard build gate for whatever physics thresholds the research doc identifies.
- `feedback_marginal_benefit_pushback.md` — corroboration explicitly REMOVED from chatter detection per operator's physics-based scoping (§1); recorded not to re-introduce without evidence.
- `feedback_context_wide_scoping.md` — STEP program-level scoping (rooms + shared primitive + multiple detector clients) satisfies the rule.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — no new DAO; anomaly rows land through existing `_write_stuck_anomaly`.

### 3.5 Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` (indirectly via `_d2_boot_settle_done`).
- No new coordinator doc created — this is a RoomCoordinator internal primitive + detector.

### 3.6 Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/coordinator.py:275-320, 1493-1855, 2100-2280, 2480-2760`.
- `custom_components/universal_room_automation/actuator_reconciler.py:440-1005`.
- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py` end-to-end.
- `custom_components/universal_room_automation/domain_coordinators/_stuck_signal_nm.py` end-to-end.
- `custom_components/universal_room_automation/sensor.py:1677-1900, 2265-2360, 4688-4743`.
- `custom_components/universal_room_automation/const.py:3510-3780`.
- `custom_components/universal_room_automation/domain_coordinators/sensor_role.py` (corroborator role — not consumed by chatter; noted for stuck-client sibling).

---

## 4. Deliverables

### D0 — Prior-art research doc lands (BLOCKING gate on D2)

`docs/planning/RESEARCH_sensor_chatter_definition_prior_art.md` is IN FLIGHT (separate task). It grounds the chatter definition in prior art (BGP route-flap damping, CAN babbling-idiot / bus-guardian, glitch-filter minimum-dwell, Nagios flap detection, WSN fault taxonomies) so the criterion is one a correctly-working sensor CANNOT satisfy — sub-hardware-dwell / rate-ceiling / duty-cycle-impossibility — NEVER a raw transitions/min. **D2 does not build until D0 lands** and specifies:
- The un-fakeable criterion (per-edge and/or per-window).
- Source of any hardware-timing threshold (device_class defaults / entity attribute / capability declaration / measured).
- The busy-real vs chatter-fault fixture recipe for INV-CHATTER-2.

**Companion recorder probe** (per "measure before you build"): `docs/planning/AUDIT_chatter_physics_floor_probe.md` — one-shot recorder scan for whatever measured threshold the research selects, validated against the founding-incident Garage B sensor AND at least one legitimately-busy hallway/kitchen PIR. This is a hard go/no-go gate on D2: if any real, healthy, currently-in-use sensor's observed behaviour trips the proposed criterion, the criterion is wrong.

**Acceptance:**
- **Verify:** D0 research doc present in repo before D2 build PR merges.
- **Verify:** D0 companion probe doc present.
- **Verify (discriminator):** probe reads Garage B ratgdo as violating; reads at least one legit-busy PIR as clean; both on the SAME criterion.

### D1 — Shared primitive: `SensorExclusionSet` (formalization + client isolation)

**Location:** new module `custom_components/universal_room_automation/domain_coordinators/sensor_exclusion.py` OR helper class in `coordinator.py`. Prefer the module — easier to test, keeps coordinator lean, matches sibling architecture (`sensor_role.py`, `sensor_capability.py`).

**API:**
```
class SensorExclusionSet:
    def __init__(self, room_name: str) -> None: ...
    def reset_tick(self) -> None: ...
    def promote(self, client: str, entity_id: str, reason: str) -> None: ...
    def release(self, client: str, entity_id: str) -> None: ...
    def is_excluded(self, entity_id: str) -> bool: ...
    def excluded(self) -> set[str]: ...
    def provenance(self, entity_id: str) -> dict[str, str]:
        """{client -> reason} for each client currently promoting entity_id."""
```

**Semantics:**
- Multi-writer: multiple clients (chatter, STUCK-SENSOR-1, P22) may promote the same entity; STEP-EXCLUDE-3 requires each release to be per-client (entity leaves the set only when the LAST client releases).
- Per-tick reset semantics: `reset_tick()` clears TICK-SCOPED promotions. Sticky client promotions (chatter uses a stability window; STUCK-SENSOR-1 D1 recomputes per tick — both flow through `promote()` each tick they're active). This preserves today's per-tick recompute behaviour byte-identical.
- Consumers read `is_excluded(entity_id)` at the six existing filter sites. The bare `set[str]` local variable at `coordinator.py:2498` becomes `SensorExclusionSet` and the six `sensor not in stuck_sensors` checks become `not exclusion_set.is_excluded(sensor)`. The MIGRATION preserves control flow; the diff is per-site line replacement + one construction.
- **Byte-identity requirement:** with chatter client disabled and only the pre-existing writers (P22, STUCK-SENSOR-1 D1) migrated onto `promote()`, every occupancy fusion output MUST equal pre-cycle output on the ledger_golden replay fixture set.

**Client identity:** the string `client` argument is the detector name (`"p22_continuous"`, `"stuck_dutycycle"`, `"chatter"`). Provenance surfaces to `_stuck_sensor_kinds` (map preserved for backwards compat) and to the diagnostic sensor.

**Acceptance Criteria — D1:**
- **Verify (STEP-EXCLUDE-1):** promoted entity contributes 0 to `motion_detected` etc.; non-promoted entity still contributes.
- **Verify (STEP-EXCLUDE-2, byte-identity):** ledger_golden_replay green with only P22 + STUCK-SENSOR-1 migrated (chatter disabled) — same `production_source_git_sha`, byte-identical rows.
- **Verify (STEP-EXCLUDE-3, client isolation):** promote(A, e) then promote(B, e) then release(A, e) → `is_excluded(e)` True; release(B, e) → False. Reviewer C authors a per-client-release mutation drill: delete the per-client tracking, assert the isolation test reds.
- **Verify (STEP-EXCLUDE-4, no propagation):** grep-based test (`quality/tests/test_sensor_exclusion_scope.py`) asserts `SensorExclusionSet` is not imported into `domain_coordinators/presence.py`, `hvac.py`, or any zone/house-tier module.
- **Test:** `test_sensor_exclusion_set_multi_client_promote_release`, `test_sensor_exclusion_ledger_golden_byte_identity`, `test_sensor_exclusion_scope_room_tier_only`.
- **Mutation drill:** at each of the 6 consumer sites, mutate the `is_excluded(sensor)` check to `False`; assert a NAMED occupancy-fusion test reds per site. Deleting one check leaving suite green = hollow anchor.
- **Live:** `_stuck_sensor_kinds` continues to populate at the same rate as pre-cycle on rooms where P22 or STUCK-SENSOR-1 was already active.

### D2 — Chatter client (physics-based; DEFINITION TBD per D0)

**Location:** new `ChatterDetector` in `coordinator.py` (or `domain_coordinators/chatter_detector.py` — prefer module for testability). Registered as a subscriber on `OccupancySubstrate.subscribe()` for state-change edges.

**DEFINITION: TBD — see `RESEARCH_sensor_chatter_definition_prior_art.md` (in flight); must be built only from un-fakeable criteria (sub-hardware-dwell / rate-ceiling / duty-cycle-impossibility), NEVER a raw rate.** The plan explicitly does not author a first-principles definition. When the research lands, insert:
- The precise criterion (per-edge and/or per-window).
- The threshold source (per-device-class default / entity attribute / capability field / measured — decided by research).
- The busy-real vs chatter-fault fixture pair.

**Algorithm skeleton (definition-agnostic, definition slots in at the marked step):**
1. On every substrate state-change edge for entity `e` in room `R`:
2. If `e` value ∈ `{"unavailable", "unknown"}` → do NOT count as a transition (unavailable bursts are a separate fault class).
3. Track whatever the definition needs (last-edge timestamp / rolling window of edges / duty accumulator — per D0).
4. **[DEFINITION STEP — TBD per D0]** apply the un-fakeable criterion. If violated, mark `e` chattering.
5. Regardless of verdict, prune the tracker to the observation window.
6. Boot-settle gate: while `_d2_boot_settle_done()` is False, steps 1-3 execute but step 4 is a no-op.

**Tick-site consumption (`coordinator.py` immediately after STUCK-SENSOR-1 D1 promotion loop at line 2569):**
```
if CHATTER_QUARANTINE_ENABLED and self._chatter_quarantine_enabled_option():
    for e in list(self._chattering_entities):
        exclusion_set.promote("chatter", e, reason="physics_violation")
        self._stuck_sensor_kinds[e] = "chatter"  # backcompat surface
        # NM emit — once per day per (kind, entity) — existing latch
        self.hass.async_create_task(fire_stuck_signal(
            self.hass,
            kind="chatter",
            key=(e,),
            diagnosis=<per D0 criterion>,
            remedy=f"Replace sensor {e} — chatter pattern indicates hardware fault",
            title_override=f"Chattering sensor: {room_name} — {e}",
        ))
```

**Fail-safe:** every exception in `ChatterDetector` is caught at the callsite; on exception the shared exclusion set reverts byte-identical for THIS tick (chatter promotes zero). Matches D2 duty-cycle try/except shape at `coordinator.py:2543`.

**Acceptance Criteria — D2 (partial; DEFINITION-anchored tests deferred to research):**
- **Verify (INV-CHATTER-1):** on any fixture the research doc's definition classifies as chatter → entity IS excluded via `SensorExclusionSet` AND STEP-EXCLUDE-1 holds.
- **Verify (INV-CHATTER-2, discriminator — DEFERRED):** busy-real vs chatter-fault fixture pair per D0 — SAME raw rate, opposite outcomes.
- **Verify (fusion preservation, definition-agnostic):** room with two motion sensors; one chattering per D0 criterion, one legit and `on`. Assert `motion_detected == True`.
- **Verify (fusion honesty, definition-agnostic):** room with ONE sensor of any kind, chattering. Assert `motion_detected == False` (fusion correctly falls through; no force-vacant needed).
- **Verify (INV-CHATTER-4, kill switch):** with `CHATTER_QUARANTINE_ENABLED = False`, no `"chatter"` client promotion in `SensorExclusionSet.provenance()` on any entity.
- **Verify (boot-settle gate):** simulate D0-criterion-violating edges during `_d2_boot_settle_done() == False`; assert no promotion. Release; simulate again; assert promotion.
- **Verify (no-PIR room):** mmwave-only room with a chattering mmwave. Assert quarantine engages — chatter does NOT require a corroborator.
- **Test:** definition-agnostic tests above wire immediately; definition-anchored tests (busy-real / chatter-fault / Garage B replay) land when D0 lands.
- **Mutation drill:** for each of steps (2), (3), (4-DEFINITION), (5), (6) — mutation MUST red a NAMED test. Run with `PYTHONDONTWRITEBYTECODE=1`.
- **Live:** post-restart on a room with a known chatterer: `_chattering_entities` non-empty within 10 min; `exclusion_set.is_excluded(e)` True; `_stuck_sensor_kinds[e] == "chatter"`; downstream fusion filter engages.

### D3 — Chatter auto-release (mirrors `check_quarantine_release`)

**Location:** `ChatterDetector.check_release(now_mono)` called from the same tick site immediately after D2 promotion.

**Algorithm:**
1. For each `e in list(self._chattering_entities)`:
2. Compute time since last observed transition (from the detector's own tracker).
3. If < `CHATTER_RELEASE_QUIET_S`: continue.
4. State check: if entity currently unavailable/unknown → skip release (matches actuator-flap release rule; quiet-on-dead-hardware ≠ stability).
5. Release: `self._chattering_entities.discard(e)`; clear detector's per-entity state; `exclusion_set.release("chatter", e)`; INFO log; `fire_stuck_signal_recovered(kind="chatter", key=(e,), message=...)` so per-day latch clears.

**Acceptance Criteria — D3:**
- **Verify (INV-CHATTER-3):** quarantine engaged; then no transitions for `CHATTER_RELEASE_QUIET_S`; on next tick entity leaves `_chattering_entities`, `exclusion_set.provenance(e)` no longer contains `"chatter"` client, one recovered NM fires.
- **Verify (STEP-EXCLUDE-3 at release):** entity concurrently promoted by both `"chatter"` and `"stuck_dutycycle"`; chatter releases; assert `is_excluded(e)` remains True (stuck holds the entity).
- **Verify (discharge — per suppression-needs-discharge rule):** post-release, a new violation immediately re-quarantines and emits a NEW NM (latch cleared by recovery NM).
- **Verify (unavailable-during-release):** quiet for `CHATTER_RELEASE_QUIET_S` BUT currently unavailable → NO release.
- **Test:** `test_chatter_auto_release_after_quiet_window`, `test_chatter_release_preserves_concurrent_stuck_promotion`, `test_chatter_release_fires_recovered_nm_and_clears_latch`, `test_chatter_release_skipped_when_unavailable`, `test_chatter_reflap_after_release_emits_new_nm`.
- **Live:** on a physically-replaced sensor, within `CHATTER_RELEASE_QUIET_S + 1 tick`: released; recovered NM logged.

### D4 — Corroboration REMOVED from chatter detection (recorded rationale)

Per §1 architecture: chatter is physics-based and quarantine-ALWAYS at DETECTION. Corroboration was needed in the reviewed build BECAUSE the prior detection was a raw transitions/min threshold with no floor — corroboration compensated for a rule that could not distinguish "busy" from "broken". Under the D0 research-anchored physics definition:

- A legitimately working sensor cannot violate the un-fakeable criterion by construction.
- Corroboration adds no discriminator power on true positives; adds two failure modes on false positives:
  - **Anchor-is-broken-thing:** self-corroboration if the corroborator is the chatterer.
  - **No-PIR rooms (6 per audit):** cannot be scored under corroboration at all.

**Argument the other way (for the record):** RF-burst / EMI could theoretically make a legit sensor look chattering. Counter: an RF-vulnerable sensor is still unreliable regardless of cause; flagging it is correct behaviour.

**Decision: corroboration REMOVED from chatter detection AND release.** Recorded revisit trigger: field evidence of a legit sensor being false-quarantined AND its device_class/attribute-timing does not explain the observed violation.

**Acceptance Criteria — D4:**
- **Verify (no-PIR room):** mmwave-only room with a chattering mmwave (per D0 criterion). Assert quarantine engages. Under the old corroboration rule this room could not be scored; this cycle covers it.
- **Test:** `test_chatter_no_pir_room_still_scored`.

### D5 — Surface: `UnavailableEntitiesSensor` reason="chattering" (KEPT verbatim from prior build)

Extend `sensor.py:_unavailable_details` (`sensor.py:1814-1868`) mirroring flapping-actuator D2.11 branch. Read `chattering_ids = getattr(coordinator, "_chattering_entities", set())`; emit per-entity `details` rows with `reason="chattering"`, `transition_count`, `since` (chatter-onset iso timestamp). Include in `unavailable_sensors`. Additive schema only.

**Producer/Consumer check:** ONLY consumer is operator-facing dashboards. NO trust-decision code reads this sensor — the fusion-time authority is `SensorExclusionSet.is_excluded()`.

**Acceptance Criteria — D5:**
- **Verify:** `_chattering_entities = {"binary_sensor.foo"}` → attrs `details` includes a row `{entity_id: "binary_sensor.foo", reason: "chattering", transition_count: <int>, since: <iso>}`.
- **Verify (discriminator):** empty set → zero `reason == "chattering"` rows.
- **Verify (provenance parity):** `_stuck_sensor_kinds[e] == "chatter"` iff `SensorExclusionSet.provenance(e)` contains client `"chatter"` iff `e in _chattering_entities`.
- **Test:** `test_unavailable_entities_sensor_surfaces_chattering_sensor`, `test_unavailable_entities_sensor_no_chatter_when_set_empty`, `test_chatter_diag_provenance_parity`.
- **Live:** `sensor.<room>_unavailable_entities.attributes.details[*].reason` includes `"chattering"` iff `_chattering_entities` non-empty.

### D6 — Wire-in anchors (mandatory per feedback_wire_in_anchor_mandatory)

New test file `quality/tests/test_chatter_wire_in.py`:

1. **Listener-wire test:** monkey-patch `ChatterDetector._on_edge` to record calls; simulate 5 substrate state-changes on a covered entity; assert 5 calls. DELETE the `substrate.subscribe(...)` call in RoomCoordinator setup; assert reds.
2. **Tick-site wire test:** monkey-patch `_chattering_entities` to `{"sentinel"}`; run one tick; assert `exclusion_set.is_excluded("sentinel")` True AND `_stuck_sensor_kinds["sentinel"] == "chatter"`. DELETE the chatter block; assert reds.
3. **Surface wire test:** SOURCE-MUTATE `sensor.py:_unavailable_details` chatter branch (not monkey-patch); assert `test_unavailable_entities_sensor_surfaces_chattering_sensor` reds. Restore + status-check per feedback_unrestored_mutation_drill.
4. **Release wire test:** monkey-patch `check_release` to no-op; assert `test_chatter_auto_release_after_quiet_window` reds.
5. **Shared-primitive wire tests (STEP D1):** at each of the 6 consumer sites, source-mutate the `is_excluded()` check to `False`; assert a named fusion test reds per site.

Run all drills with `PYTHONDONTWRITEBYTECODE=1` + cleared `__pycache__`.

**Acceptance Criteria — D6:**
- **Test:** `test_chatter_listener_wired`, `test_chatter_tick_site_promotes_via_exclusion_set`, `test_chatter_surface_wired`, `test_chatter_release_wired`, `test_exclusion_set_consumer_sites_wired` (parameterized over 6 sites).
- **Verify (mutation):** `≥10 failed` on mutation (4 chatter + 6 consumer sites), `0 failed` on restore.

---

## 5. Numbers on the knob ladder

| Knob | Value | Rung | Home | Why here |
|---|---|---|---|---|
| `CHATTER_QUARANTINE_ENABLED` | `True` | **Rung 1 — module const** (kill switch) | `const.py` near `STUCK_EXCLUSION_ENABLED` (`const.py:3725`) | Safety-critical kill; setting False → chatter client promotes 0 into `SensorExclusionSet` → INV-CHATTER-4 hold. |
| `CONF_CHATTER_QUARANTINE_ENABLED` | default True | **Rung 2 — options flow** | `config_flow.py` alongside `CONF_STUCK_SENSOR_EXCLUSION_ENABLED` | Per-deployment enable; AND-composed with rung-1 via helper analogous to `_stuck_exclusion_enabled` at `coordinator.py:2121`. |
| `CHATTER_RELEASE_QUIET_S` | `900` (15 min) | **Rung 1** | `const.py` | Symmetric with STUCK-SENSOR-1's `CORROBORATOR_DISAGREE_S = 900`. Substantial-enough stability proof; short-enough operator recovery. |
| Any per-edge / per-window / per-dwell chatter thresholds | **TBD per D0 research** | **Rung 1** by default (physics-derived constants that should require code review); per-entity overrides via `sensor_capability` (rung 2) if research indicates per-hardware variation | `const.py` (defaults) + `sensor_capability` schema (overrides) | Values and structure come from the research doc; do not commit to specific numbers here. Marginal-benefit rule: no dashboard-tunable rung-3 knob. |
| `CONF_STUCK_SIGNAL_NM_ENABLED` | reused | Rung 2 | existing | Silences all `stuck_signal` NM incl. new `chatter` kind. |

**Kill-switch semantics** documented on `CHATTER_QUARANTINE_ENABLED`: `False` → detector may still populate `_chattering_entities` (D5 surface stays useful during dogfood), but the tick-site does NOT call `exclusion_set.promote("chatter", ...)` and does NOT emit NM. INV-CHATTER-4 + STEP-EXCLUDE-2 (at the chatter axis) hold byte-identical.

No rung-3 knob (dashboard `number`/`switch`) introduced.

---

## 6. Non-goals (explicit)

1. **Substrate-level chatter filtering.** Substrate's per-kind bucket still sees chattering edges → zone-tier leak. Follow-up card `SUBSTRATE-STUCK-FILTER-1` — separate cycle; blast radius covers zone + house tier. Not here.
2. **New DB table.** Existing `anomaly_log` via `_write_stuck_anomaly` suffices.
3. **New house-level aggregate sensor.** House-tier `stuck_sensors_by_room` aggregator (`sensor.py:4688-4743`) automatically picks up `_stuck_sensor_kinds`.
4. **Corroboration in chatter detection or release.** REMOVED — §4-D4. Revisit trigger recorded.
5. **Signal-trust-ledger MIGRATION of chatter.** This cycle CREATES the production `kind="chatter"` site; the ledger migration is a separate M5 cycle.
6. **Actuator chatter.** D2.11 actuator flap quarantine covers availability transitions — distinct primitive, unchanged.
7. **Per-room dashboard chatter-sensitivity knob.** Sensitivity should require review.
8. **Rev-1 "no exclusion" non-goal REVERSED.** Chatter DOES exclude via the shared fusion-preserving primitive.
9. **First-principles chatter definition.** Deferred to `RESEARCH_sensor_chatter_definition_prior_art.md` per operator instruction.
10. **STUCK-SENSOR-1 D2-demotion role migration.** `STUCK-D2-DEMOTION-ROLE-MIGRATE-1` — separate cycle, sequences after remaining SENSOR-CAPABILITY-1 hardening. Retro-parented under STEP but not built here.

---

## 7. Producer AND Consumer sections

### Producer check — `SensorExclusionSet` (all clients)
- **Computed by:** three clients — P22 (`_p22_stuck_sensor_set`, `coordinator.py:2498`), STUCK-SENSOR-1 D1 (`_promote_dutycycle_to_exclusion`, `:2141-2187`), chatter (`ChatterDetector.check(...)`, NEW).
- **Depends on:** for chatter — substrate listener + `_last_transition_*` tracker + `_d2_boot_settle_done()` + D0 criterion. For P22 — `_sensor_on_since` + hours threshold. For STUCK-SENSOR-1 — `_detect_duty_cycle_stuck` + role-aware corroborators + `_d2_house_state_allows`.
- **Health of dependencies:** substrate `subscribe()` proven; boot-settle proven; role-aware corroborators proven (SENSOR-CAPABILITY-1 shipped); D0 grounds the chatter criterion in prior art before ship.
- **Multiple derivations?** MULTIPLE — three clients. STEP-EXCLUDE-3 (client isolation) is the safety on multi-derivation.
- **External ground truth:** ledger_golden fixtures for STUCK-SENSOR-1 D1 rows; D0 research + probe for chatter.

### Consumer + call-site check — `SensorExclusionSet` (6 sites, unchanged shape)
- Trust-decision consumers (all in `coordinator.py`, ROOM tier only):
  - `:2712` — motion_detected leg
  - `:2719` — presence_detected leg
  - `:2726` — occupancy_detected leg
  - `:2740, 2748, 2756` — `any_sensor_active` legs
- Display consumers of `_stuck_sensor_kinds` / `_chattering_entities`:
  - `sensor.py:_unavailable_details` (D5 addition)
  - `sensor.py:2265-2360` RoomInsightSensor reason ladder (existing; chatter shows up for free)
  - `sensor.py:4688-4743` house-tier aggregator (existing; chatter shows up for free)
- **NOT consumers (STEP-EXCLUDE-4 assertion):** any zone-tier tracker, house-tier aggregator, HVAC, presence coordinator, occupancy substrate. Reviewer A grep-verifies.

---

## 8. Files changed

| File | Change | Lines (est.) |
|---|---|---|
| `custom_components/universal_room_automation/const.py` | Add `CHATTER_*` constants (`CHATTER_QUARANTINE_ENABLED`, `CHATTER_RELEASE_QUIET_S`, and TBD-per-D0 physics thresholds); append `"chatter"` to sub-classification comment | +30 |
| `custom_components/universal_room_automation/domain_coordinators/sensor_exclusion.py` (new) | `SensorExclusionSet` shared primitive | +160 |
| `custom_components/universal_room_automation/coordinator.py` | Migrate 6 consumer sites onto `SensorExclusionSet.is_excluded()`; migrate P22 + STUCK-SENSOR-1 D1 writers onto `promote()`; add `ChatterDetector` init + substrate subscribe + tick-site promotion/release block + kill-switch helper | +180 |
| `custom_components/universal_room_automation/sensor.py` | Extend `_unavailable_details` with chatter branch | +30 |
| `custom_components/universal_room_automation/config_flow.py` | Add `CONF_CHATTER_QUARANTINE_ENABLED` | +8 |
| `quality/tests/test_sensor_exclusion.py` (new) | STEP D1 shared-primitive tests (multi-client, byte-identity, scope, mutation) | +220 |
| `quality/tests/test_chatter_detector.py` (new) | D2 definition-agnostic tests + D4 no-PIR test; definition-anchored tests added when D0 lands | +200 |
| `quality/tests/test_chatter_release.py` (new) | D3 tests | +140 |
| `quality/tests/test_unavailable_entities_chatter.py` (new) | D5 tests | +80 |
| `quality/tests/test_chatter_wire_in.py` (new) | D6 wire-in + mutation drill (chatter + 6 consumer sites) | +200 |
| `docs/planning/RESEARCH_sensor_chatter_definition_prior_art.md` (in flight, separate task) | D0 research doc | — |
| `docs/planning/AUDIT_chatter_physics_floor_probe.md` (new, D0) | D0 companion probe | +200 |

**No changes to:** `database.py`, `notification_manager.py`, `occupancy_substrate.py`, `_stuck_signal_nm.py`, `actuator_reconciler.py`.

---

## 9. Review protocol — Tier 2-DB (three framing-disjoint reviews + Live)

Elevation rationale: SHARED-PRIMITIVE formalization writes into the same set STUCK-SENSOR-1 already writes into; a subtle STEP-EXCLUDE-{1,3} bug could regress room occupancy silently across all rooms simultaneously. Two DO-NOT-SHIP reviews on the prior scope motivate the tier bump.

- **Review A — data integrity + fixture byte-identity + consumer / scope enumeration re-verification.** Owns: independent grep of every `SensorExclusionSet.is_excluded()` consumer to verify all 6 sites migrated (Bug Class #53); STEP-EXCLUDE-4 scope grep (primitive not imported outside RoomCoordinator); `ledger_golden_replay.py` green (STUCK-SENSOR-1 D1 rows byte-identical after migration onto `promote()`; chatter's persisted anomaly row shape compatible with MANIFEST "chatter_adjudication" block); no new DB writer; no unbounded per-entity dict growth on entity removal.
- **Review B — physics correctness + STEP-EXCLUDE-{1,2,3} + INV-CHATTER-{1,3,4} + async / lifecycle / restart semantics.** Owns: end-to-end trace of a state-change from substrate → chatter listener → detector state → tick-site → `SensorExclusionSet.promote("chatter", ...)` → 6 consumer sites; STEP-EXCLUDE-3 client-isolation MUTATION-verified (delete per-client tracking → per-client-release test reds); boot-settle gate mutation-verified; restart resilience (`_chattering_entities` RAM-cleared on restart; per-day NM latch survives per existing `_stuck_signal_nm`); D3 release symmetry with `check_quarantine_release`; unavailable-state handling on both detection (skip) and release (skip); STEP-EXCLUDE-1 second clause (chatter MUST NOT suppress a non-quarantined sensor's true vote).
- **Review C — surfaces (D5) + test authority via per-site source mutation + wire-in anchors + D0 anchoring.** Owns: D5 attr round-trip through operator dashboard; D6 wire-in tests fail on deletion; mutation-verified with `PYTHONDONTWRITEBYTECODE=1` + cleared `__pycache__`; D0 research doc AND companion probe both present in repo; the chatter DEFINITION step in D2 is genuinely built on D0's un-fakeable criterion (not a raw rate re-emerging under a new name); busy-real / chatter-fault fixture pair authored per D0 recipe and each fixture actually discriminates.

**Plan review — Tier 2-DB (2 plan reviews, framing-disjoint per CLAUDE.md 2026-08-11 rule):**
- **Plan-Review-1 (completeness):** independently re-grep §3.1 REUSED ledger and §7 consumer enumeration; verify D0 is documented as a HARD gate; verify STEP-EXCLUDE-{1..4} + INV-CHATTER-{1,3,4} are falsifiable in the discriminator sense; verify the STEP program re-parents STUCK-SENSOR-1 + SENSOR-CAPABILITY-1 explicitly.
- **Plan-Review-2 (adversarial build-prediction):** what will the builder get wrong? Ambiguities in `SensorExclusionSet` API (does promote()-then-promote() by the same client repeat-log or dedupe?); the D2/D3 tick-site ordering vs STUCK-SENSOR-1 D1's existing block; the `_chattering_entities` vs `SensorExclusionSet.provenance()` two-surface parity trap.

**Fix CRITICAL/HIGH from any review before deploy.** Orchestrator independent verification pre-ship: personally re-grep the 6 consumer sites AND re-run at least one per-site mutation drill.

**Pre-deploy acceptance gate:** ledger_golden_replay green; D0 research + probe docs present; suite baseline diff shows only expected new tests + the 6 consumer-site line replacements.

**Live Validation (Review D):** post-restart —
1. Chatterer room (Garage B ratgdo if still): `_chattering_entities` non-empty within 10 min; `SensorExclusionSet.is_excluded(e)` True on that room; room's `motion_detected` reads from remaining sensors.
2. Legit-busy room: after ≥30 min live, entity NOT in `_chattering_entities` (INV-CHATTER-2 per D0 fixture recipe).
3. `sensor.<room>_unavailable_entities.attributes.details` includes `reason="chattering"` iff quarantined.
4. `SELECT COUNT(*) FROM anomaly_log WHERE json_extract(payload,'$.kind')='chatter'` ≥ 1 on chatterer rooms, 0 on legit-busy rooms.
5. STUCK-SENSOR-1 v5.75.0 continues to fire per its shipped behaviour (STEP-EXCLUDE-2 hold on the stuck axis).
6. Post-release: `fire_stuck_signal_recovered` fires; entity leaves; within `CHATTER_RELEASE_QUIET_S + 1 tick`.
7. DB write-rate ±25% pre/post per 2026-06-09 write-flood memory.

Post-restart, write observed table into `docs/readmes/README_v<version>.md`.

---

## 10. Deferred / parked

- **Substrate-level exclusion filter** → `SUBSTRATE-STUCK-FILTER-1` (queue). Covers ALL clients (chatter and stuck together).
- **STUCK-SENSOR-1 D2-demotion role migration** → `STUCK-D2-DEMOTION-ROLE-MIGRATE-1` (queue). Sequences after SENSOR-CAPABILITY-1 hardening.
- **Corroboration re-introduction into chatter** → parked (§4-D4). Trigger recorded.
- **Per-room dashboard chatter-sensitivity knob** → parked. Trigger: operator asks after ≥14d organic experience.
- **Auto-learning of physics thresholds from live observation** → parked; D0 default + capability override cover initial deployment.
- **Signal-trust-ledger migration of chatter** → separate M5 cycle.

---

## 11. Operator decisions needed

**None** — the plan carries recommendations for each open question:
- Ship-together vs ship-separately: **STEP D1 + D2 ship in one cycle** (§0.4); D0 (research + probe) blocks D2 not D1.
- Corroboration in chatter → **REMOVED** at both detection and release (§4-D4).
- Substrate leak → **KNOWN, DEFERRED** (§6.1).
- Physics thresholds → **TBD per D0** (§5, §4-D2).
- Kill switch defaults → **ON** at both rungs; operator flips off without code change.
- Rev-1 "no exclusion" non-goal → **REVERSED** (§6.8).
- Re-parenting of STUCK-SENSOR-1 + SENSOR-CAPABILITY-1 under STEP → **retroactive, doc-only** — no code change to those cycles is implied by re-parenting.

If the operator wants Tier 3 (fourth adversarial-completeness reviewer) given the two prior DO-NOT-SHIP reviews and the shared-primitive scope, they say so; otherwise the plan proceeds under Tier 2-DB.
