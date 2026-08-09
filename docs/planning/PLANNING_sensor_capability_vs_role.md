# PLANNING — Separate sensor CAPABILITY from analytic ROLE (SENSOR-CAPABILITY-1)

**Card:** `SENSOR-CAPABILITY-1` (`docs/planning/kanban.data.yaml:154`)
**Status:** pre_planning → planning draft
**Author date:** 2026-08-09
**Blocks:** STUCK-SENSOR-1
**Sibling of:** SIGNAL-TRUST-LEDGER (build-gated on this cycle)
**Proposed tier:** **Tier 3** (four framing-disjoint reviews incl. adversarial-completeness) — argued in §7.

---

## 0. Operator ruling that anchors the cycle

> *"My instinct is code change so we don't have fixed config buckets. Sensor reality should
> not pin use and analysis reality in software. It should just tell us what the hardware layer
> is. We could also add more options or detail to the kind of sensor in config."*
> — operator, 2026-08-09

This cycle takes that literally: keep the three CONF lists as a **wiring** declaration
(what URA is subscribed to), and add a **capability** descriptor and **role-derivation**
layer above them (what a given entity IS and what QUESTION it can answer). No config
migration; every new field is additive and defaults so that behaviour is byte-identical
to today when nothing is declared.

---

## 1. Institutional context verified

### 1.1 Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md:29,592` — confirms `TIER1_KINDS` is the substrate
  vocabulary, kind is "determined by which CONF list the entity is in".
- `docs/Coordinator/HOUSE_MANUAL.md:296` — same vocabulary flows to house-tier docs.

### 1.2 Prior planning docs consulted

| Doc | Relevance |
|---|---|
| `AUDIT_mmwave_only_rooms_2026-07-31.md` (Findings 1, 2, 6) | Finding 6 IS the root cause; this cycle's acceptance fixture. Six rooms named. |
| `PLANNING_mmwave_corroboration_tier3.md` (Amendment 4) | v5.40.0 veto + v5.42.0 D2 demotion shipped WITHOUT D0; Amendment 4 relocates the root cause here. |
| `PLANNING_signal_trust_ledger_abstraction.md` (Addendum 2026-08-09, §75, §141, §303–307) | Ledger's `RoomSignal(..., source_kind: 'mmwave'|'pir'|'camera'|'ble')` is not expressible today. This cycle is its declared prerequisite. |
| `CATALOG_cross_correlation_primitives.md` (P15, §160 verdict, §172 addendum) | P15 substrate kind-precedence is the primitive being changed. Standing verdict: **EXTEND, do not roll a new primitive.** |
| `PLANNING_paper_and_oss_fusion_library.md` §7 / §7b | Intent-vs-evidence axis is the same cut viewed differently — a bed is EVIDENCE, an mmWave is a weak WITNESS. Not expressible on today's vocabulary. |
| `PLANNING_presence_provenance_split_and_fan_diagnostic.md` (:50) | Where `TIER1_KINDS` was originally introduced; consumers audited there. |
| `INVESTIGATION_voice_satellites_ura.md` (:15–:87) | Prior TIER1_KINDS extension attempt (adding `voice_activity`). Confirms every consumer that iterates the tuple must be touched — the "extension point" catalogue is already written down. Reuse it. |
| `INVESTIGATION_presence_provenance_audit_and_fan_noise.md` (:352, :519) | Confirms `last_kind_to_fire` attr vocabulary is TIER1_KINDS-bound; capability layer must not silently break that. |
| `AUDIT_presence_provenance.md:96` + `presence.py:384` `_audit_provenance_invariants` | Runtime invariant: every `_room_provenance[r]` key is in `TIER1_KINDS`. Any capability layer must NOT emit a key outside this set on the legacy channel — the invariant asserts loudly. |

### 1.3 Memory bodies pulled

- `feedback_context_wide_scoping.md` — scope rooms + zones + house + cross-cutting.
- `feedback_marginal_benefit_pushback.md` — see §6.
- `feedback_suppression_needs_discharge.md` — no suppressed one-shots in this cycle (checked).
- `feedback_hollow_test_anchors.md` — Tier-3 framing C uses per-site source mutation.
- `feedback_no_fabrication.md` — every claim below cites file:line.

### 1.4 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/const.py:333–342` — the three CONF names + `TIER1_KINDS`.
- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py` (entire file, 784 lines) — kind mapping, precedence, seed, dispatch, refresh, teardown.
- `custom_components/universal_room_automation/domain_coordinators/presence.py:283–390, 484–770, 3062, 6286` — `_classify_entity_kind`, `_room_provenance`, audit invariant, batch aggregation.
- `custom_components/universal_room_automation/coordinator.py:1460–2015` — `_detect_duty_cycle_stuck` (D2), the positional `motion/mmwave/occupancy` list contract at :1995, the "Continuous rule DOES exclude" branch at :1960–1967 (cited by kanban), `occupancy_source` string vocabulary at :235, :3335–3437.
- `custom_components/universal_room_automation/binary_sensor.py:74, 445–447, 582–583, 644–645, 660–661` — attribute default shape.
- `custom_components/universal_room_automation/sensor.py:5006–5018` — provenance aggregation (function-local TIER1_KINDS import, Bug Class #34 comment).
- `custom_components/universal_room_automation/domain_coordinators/signals.py:170` — `SIGNAL_SUBSTRATE_KIND_CHANGED` payload contract.
- `config_flow.py`, `options_flow.py` — the three CONF lists appear together; capability entries would ride here.

### 1.5 Consumer enumeration of TIER1_KINDS and _KIND_TO_CONF (Bug Class #53 discipline)

The two shared primitives touched by this cycle. Every site listed here MUST be re-audited
during build and Reviewer D's completeness pass. This list was generated by grep over the
repo tree; production sites are load-bearing, doc/test sites are the invariant surface.

**`_KIND_TO_CONF` (production; total: 1 write site, 2 read sites, all in one file):**

| File:line | Kind | Notes |
|---|---|---|
| `occupancy_substrate.py:82` | definition | tuple-declared; unique writer |
| `occupancy_substrate.py:209` | read | inside `_discover_entity_map` — the CONF-list walk |
| `AUDIT_mmwave_only_rooms_2026-07-31.md:113` | doc | Finding 6 quote |

**`TIER1_KINDS` (production consumers — iterate the tuple, key by its members, or assert against it):**

| File:line | Consumer | What it does |
|---|---|---|
| `const.py:342` | definition | 3-tuple |
| `occupancy_substrate.py:64` | import | |
| `occupancy_substrate.py:262–263` | reset + snapshot per-kind bucket | `_reset_and_seed_room_bucket` |
| `occupancy_substrate.py:415` | snapshot pre-refresh raw state | inside `refresh_subscriptions` |
| `occupancy_substrate.py:513` | synthetic-edge delta computation | post-settle refresh step 7 |
| `occupancy_substrate.py:748, 755, 760` | stable-dict shape for `get_room_kinds` / `get_all_room_kinds` | public API shape contract |
| `presence.py:64` | import | |
| `presence.py:283–299` | `_classify_entity_kind` return-type contract | returns a TIER1_KINDS string |
| `presence.py:362, 384–387` | `_audit_provenance_invariants` — invariant #2 | RAISES on unknown key (legacy `"tier1"` sentinel allowed) |
| `presence.py:484` | `_room_provenance[room][kind] -> bool` storage shape | |
| `presence.py:631, 645, 648` | `provenance_for` public API — projected stable dict | Every TIER1_KINDS slot present |
| `presence.py:745, 763` | `record_room_edge` write path — `slot = kind if kind in TIER1_KINDS else "tier1"` | Silent fallback to `"tier1"` sentinel |
| `presence.py:3062` | dispatch contract docstring | |
| `presence.py:6286–6289` | per-tick per-kind bucket build | Tier-1 aggregate metrics |
| `binary_sensor.py:74, 447, 583, 645, 661` | attribute default dicts | `tier1_provenance`, `substrate_kinds` |
| `sensor.py:5013–5018` | provenance aggregation across rooms | function-local import |
| `signals.py:170` | signal payload doc | `SIGNAL_SUBSTRATE_KIND_CHANGED(room, kind, new_state)` |
| `coordinator.py:1460–1495, 1995` | `_detect_duty_cycle_stuck(motion_sensors, mmwave_sensors, occupancy_sensors, …)` | **Positional signature keyed by kind** — a legacy shape of `_KIND_TO_CONF` |
| `coordinator.py:235, 3335, 3362, 3419, 3437, 3723` | `_last_occupancy_source` vocabulary — includes `"mmwave"` gate | mmWave demotion gate (kanban ref) |

**Test / doc surface (invariant anchors — must remain passing or be updated with justification):**
`quality/tests/test_presence_provenance_split.py:24,42–43`; `test_substrate_backcompat.py:53,306`;
`test_zone_substrate_migration.py:17,31`; `test_substrate_discovery.py:18,60–63`.

### 1.6 Proposed additions — REUSED / NEW ledger

| Symbol | Verdict | Justification |
|---|---|---|
| `CONF_SENSOR_CAPABILITIES` (per-room, dict[entity_id, capability_dict]) | **NEW** | Grep `CONF_.*CAPABILIT` → 0 hits. No adjacent name occupies this. Sibling to the three CONF lists at `const.py:333–335`. |
| `CAPABILITY_KIND_*` string constants (`"pir"`, `"mmwave"`, `"occupancy"`, `"bed"`, `"camera_presence"`, `"ble_presence"`) | **NEW as constants, REUSED as strings.** `"pir"`/`"camera"`/`"ble"` already appear in `PLANNING_signal_trust_ledger_abstraction.md:141` as intended `source_kind` values (not yet in code). `"bed"` is new. The three legacy strings (`motion`/`mmwave`/`occupancy`) STAY as TIER1_KINDS — capability names are a **superset**. |
| `TIER1_CAPABILITIES: Final = TIER1_KINDS + ("bed", "camera_presence", "ble_presence", "pir_split")` | **NEW** | Superset tuple. TIER1_KINDS untouched (byte-identical fallback). See §3 for why we do NOT extend TIER1_KINDS itself. |
| `SensorCapability` frozen dataclass (`kind, trust_class, failure_mode, source`) | **NEW** | Grep `class .*Capability` → 0 hits in `custom_components/`. Nearest sibling `LkgValue` (value envelope, wrong axis). |
| `RoleQuery` enum (`CANDIDATE_FOR_STUCK`, `CORROBORATOR_FOR_ROOM`, `CREATOR_VS_EXTENDER`) | **NEW** | Grep `RoleQuery`/`Role\(` → 0 hits. Explicit query enum keeps role a computed function, never a stored field. |
| `resolve_role(room, entity, query) -> RoleVerdict` module in `domain_coordinators/sensor_role.py` | **NEW file** | Isolated pure module; no coordinator owns this logic today; putting it inside the substrate would over-couple discovery and semantics. |
| `SIGNAL_SUBSTRATE_KIND_CHANGED` payload shape | **REUSED, unchanged** | Payload stays `(room, kind, new_state)` with `kind ∈ TIER1_KINDS`. Capability-derived edges do NOT ride this channel in v1 — see §3.3. |
| `_KIND_TO_CONF` at `occupancy_substrate.py:82` | **REUSED, unchanged** | The CONF lists remain the wiring. No new lookup table. |
| Config-flow selector for per-entity capability overrides | **NEW field on the existing room step** | Grep `capability` in `config_flow.py`/`options_flow.py` → 0 hits. Rides the same step where the three CONF lists live. |

Every capability override entry is **operator-declared**; there is no auto-inference in v1 (see §3.2 for why, and §8 non-goals).

---

## 2. Falsifiable invariant (Tier-3 mandatory)

**I1 (byte-identity under empty overrides):** For every room whose config carries NO
`CONF_SENSOR_CAPABILITIES` entries, at every tick, in every codepath enumerated in §1.5:
- `OccupancySubstrate.get_all_room_kinds(room)` returns the identical dict.
- Every dispatch of `SIGNAL_SUBSTRATE_KIND_CHANGED` fires with the identical
  `(room, kind, new_state)` tuple, in the identical order, at the identical wall-clock
  offset from the driving state event.
- `_room_provenance[room]` has identical keys and identical values.
- `_detect_duty_cycle_stuck` returns the identical set.
- Every binary_sensor and sensor attribute exposed today keeps its identical shape and
  values.

**I2 (role is computed, never persisted):** `RoleQuery` verdicts are pure functions of
`(room capability map ⊕ CONF lists, question, current substrate raw-state)`. No coordinator
stores a role in memory across ticks. Adversarial framing D: find any storage path that
memoizes a role verdict beyond the tick in which it was queried.

**I3 (no silent invariant escape):** `_audit_provenance_invariants` at `presence.py:384`
(which RAISES on kinds outside `TIER1_KINDS ∪ {"tier1"}`) continues to pass. Capability
kinds outside TIER1_KINDS MUST NOT reach the legacy provenance channel. If they do, the
audit correctly RAISES — that is the desired failure mode, not a bug to route around.

The single load-bearing sentence: **"With no capability declared anywhere, behaviour is
byte-identical to today."** D's job is to break exactly this. Config-boundary tests: (a)
override present but pointing to an entity in NONE of the three CONF lists; (b) override
present and pointing to an entity in MULTIPLE CONF lists (P15 precedence collision); (c)
override capability kind = the CONF-derived kind (no-op override, must remain no-op); (d)
override arriving via `refresh_subscriptions` mid-flight (F4 lock discipline preserved).

---

## 3. Design (recommended shape)

### 3.1 Two-layer separation

```
Layer A — WIRING (unchanged, three CONF lists):
  CONF_MOTION_SENSORS, CONF_MMWAVE_SENSORS, CONF_OCCUPANCY_SENSORS
    → substrate discovery, listener registration, per-kind raw state,
      SIGNAL_SUBSTRATE_KIND_CHANGED. Stays TIER1_KINDS-valued.

Layer B — CAPABILITY (new, additive, optional):
  CONF_SENSOR_CAPABILITIES: {entity_id: {"kind": str, "trust_class": str,
                                          "failure_mode": str}}
    → operator-declared per entity, defaults absent. When absent, the
      capability is DERIVED from CONF-list membership using today's rule
      (motion → "motion" / mmwave → "mmwave" / occupancy → "occupancy").

Layer C — ROLE (new, computed, never stored):
  resolve_role(room, entity, query) -> RoleVerdict
    → pure function reading Layer A + Layer B + current substrate state.
      Callers ask the QUESTION they need (candidate-for-stuck-scoring,
      corroborator-for-independence, creator-vs-extender-for-occupancy).
      Role is a function of the question, not a property of the sensor.
```

### 3.2 What operators declare (and what they do NOT)

Operators declare ONLY the ambiguous cases via `CONF_SENSOR_CAPABILITIES`:

- The master-bedroom bed sensor: `{"kind": "bed", "trust_class": "strong_evidence",
  "failure_mode": "physical_independent"}`.
- Study A room cameras (already in `room_cameras`, not `occupancy_sensors`): capability
  is inferred for free from being wired into that field, not into a CONF-list.
- BLE-presence entities: same — inferred from BLE substrate, not this cycle's surface.

Operators do NOT declare capability for the vast majority of sensors — the CONF-list
default holds. **No auto-inference from device_registry / manufacturer strings in v1**
(rare-fire, hard-to-observe, easy-to-mis-attribute; deferred to §8).

### 3.3 Why TIER1_KINDS stays a 3-tuple

The prior `INVESTIGATION_voice_satellites_ura.md` (§16, §31, §198) proved that adding
even ONE kind to `TIER1_KINDS` requires touching every site in §1.5 above and shipping a
Tier 2-DB (or Tier 3) review because `_audit_provenance_invariants` RAISES on unknown
keys. That is a large blast radius per capability added. This cycle deliberately keeps
capability outside the substrate's dispatch channel:

- The substrate continues to emit `(room, kind ∈ TIER1_KINDS, new_state)`.
- Capability queries run at the CONSUMPTION site (e.g. `_detect_duty_cycle_stuck` asks
  "is the bed asserting?" via `resolve_role(room, bed_entity, CORROBORATOR_FOR_ROOM)`),
  not at the dispatch site.

This bounds the blast radius: adding a new capability kind is O(1) at the query site, not
O(N sites iterating TIER1_KINDS).

### 3.4 Immediate consumer wired in this cycle: `_detect_duty_cycle_stuck`

`coordinator.py:1995` today takes positional (motion, mmwave, occupancy) lists — this is
`_KIND_TO_CONF` re-shaped as a signature. The migration:

1. Keep the existing positional signature (byte-identical fallback).
2. Add a second internal path: `_resolve_corroborators(room)` which returns entities whose
   capability satisfies `CORROBORATOR_FOR_ROOM` — today the PIR list, but ALSO any entity
   with capability `"bed"` or `"camera_presence"` or `"ble_presence"` **when declared**.
3. Master Bedroom outcome: bed sensor is now consulted (corroborator), not judged
   (D2 candidate). D2 candidate list for master is `mmwave + occupancy − corroborators`.

This is the FIRST and ONLY consumer migrated in this cycle. It is the acceptance-fixture
consumer named in Finding 2 of the audit; other consumers (fan-recheck, provenance) are
NOT migrated here to keep the blast radius bounded.

---

## 4. Deliverables

### D1 — `SensorCapability` dataclass + capability derivation

Add `custom_components/universal_room_automation/domain_coordinators/sensor_capability.py`.
Pure module. Frozen dataclass. Function `derive_capability(room_config, entity_id) ->
SensorCapability` returning the operator-declared capability when present, else the
CONF-list-derived default.

**Acceptance Criteria**
- **Verify:** `derive_capability(room, entity)` for every entity in every CONF list of every
  room returns exactly today's kind string when no `CONF_SENSOR_CAPABILITIES` present.
- **Verify:** operator declaring `{"bed_entity": {"kind": "bed"}}` for a room whose bed_entity
  is in `CONF_OCCUPANCY_SENSORS` returns `SensorCapability(kind="bed", …)`; the underlying
  CONF-list membership is unchanged.
- **Test:** `test_capability_default_matches_conf_list` iterates every fixture room and
  asserts identity vs today's derivation.
- **Test:** `test_capability_override_survives_options_reload` uses the options-flow
  round-trip fixture pattern from `test_options_flow_roundtrip.py`.
- **Live:** none for D1 (no runtime surface yet).

### D2 — `resolve_role(room, entity, query) -> RoleVerdict`

Add `custom_components/universal_room_automation/domain_coordinators/sensor_role.py`. Pure
module. Enum `RoleQuery = {CANDIDATE_FOR_STUCK, CORROBORATOR_FOR_ROOM, CREATOR_VS_EXTENDER}`.
No side effects; no persistence; no listeners.

**Acceptance Criteria**
- **Verify:** `resolve_role(room, entity, CORROBORATOR_FOR_ROOM)` returns True for every
  motion-bucket entity today AND for any entity whose capability kind is one of
  `{"pir", "bed", "camera_presence", "ble_presence"}`.
- **Verify:** `resolve_role(room, entity, CANDIDATE_FOR_STUCK)` returns True for every
  mmwave/occupancy-bucket entity today MINUS entities whose capability declares
  `"bed"` or another `strong_evidence` trust_class.
- **Test:** `test_role_is_pure` — same inputs, N calls, N identical outputs; no state on
  the module.
- **Test:** `test_role_query_matrix` — 3 queries × 5 capability kinds × 3 CONF-list
  memberships = 45 cells, table-driven fixture.
- **Live:** none for D2 (queries not yet consumed).

### D3 — `_detect_duty_cycle_stuck` consults `resolve_role` for candidate + corroborator sets

Refactor `coordinator.py:1460`. Signature stays. Body computes `candidates` and
`corroborators` via `resolve_role` instead of positional list arithmetic.

**Acceptance Criteria**
- **Verify:** master bedroom's bed sensor is in `corroborators`, NOT in `candidates`, when
  operator has declared `{bed_entity: {"kind": "bed"}}`.
- **Verify:** every OTHER room's `candidates` and `corroborators` sets are identical to
  today's positional-derivation output (byte-identical fallback).
- **Sensor:** existing `sensor.<room>_stuck_sensors` attribute unchanged for all rooms
  where no capability is declared.
- **Test:** `test_d2_master_bedroom_bed_corroborates` — asserts bed OFF while mmwave ON
  yields the SAME D2 verdict as today (uncorroborated → notify), and bed ON while mmwave
  ON is corroborated (no notify).
- **Test:** `test_d2_no_capability_declared_byte_identical` — every room, every candidate
  set, every corroborator set, iterated fixture-wide.
- **Live:** post-deploy, `logbook` shows master bed sensor NOT appearing as D2 candidate
  in the next 24h of stuck-sensor NM notes; STUCK-SENSOR-1 becomes buildable next cycle.

### D4 — Config-flow options selector for `CONF_SENSOR_CAPABILITIES`

Add an optional textarea / mapping selector on the room options step (`options_flow.py`).
Empty by default. Validates entity_ids against the room's known sensor set (union of the
three CONF lists) — unknown entity_id ⇒ validation error naming the sensor.

**Acceptance Criteria**
- **Verify:** empty submission does not create the key (round-trip preserves absence).
- **Verify:** declaration for entity not in any CONF list is rejected with a message
  naming the entity_id.
- **Test:** `test_options_flow_capability_roundtrip`.
- **Live:** operator can declare master bed sensor via UI without editing `.storage`.

### D5 — Documentation write-back

Update `docs/Coordinator/PRESENCE_COORDINATOR.md` §29 and
`docs/planning/CATALOG_cross_correlation_primitives.md` P15 with a paragraph naming the
capability layer as the extension point that P15's standing verdict called for.

**Acceptance Criteria**
- **Verify:** P15 row references `sensor_role.resolve_role` as the role-derivation site.
- **Live:** README_v<version>.md contains the Validated <date> table for I1/I2/I3.

---

## 5. Numbers get knobs (rung ladder)

| Number | Value | Knob name | Rung | Why |
|---|---|---|---|---|
| Capability-kind vocabulary | `{"pir", "mmwave", "occupancy", "bed", "camera_presence", "ble_presence", "pir_split"}` | `TIER1_CAPABILITIES` in `const.py` | **1 — module constant** | Vocabulary is a schema; changing it needs review (breaks the role-query matrix). Never operator-tuned. |
| Per-entity capability override | operator-declared dict | `CONF_SENSOR_CAPABILITIES` in `const.py` + options flow | **2 — config/options flow** | Per-deployment declaration; infrequent; persistent. Exactly the operator's request ("more options or detail in config"). |
| Trust-class values | `{"strong_evidence", "witness", "weak_witness"}` | `TRUST_CLASS_*` constants | **1 — module constant** | Same rationale as vocabulary. |
| Failure-mode values | `{"physical_independent", "correlated_wireless", "correlated_bridge", "unknown"}` | `FAILURE_MODE_*` constants | **1 — module constant** | Same. |

**Kill-switch:** the whole capability layer's kill switch is "declare no overrides" — that
is the byte-identical fallback (I1). No separate kill switch needed.

No new thresholds; no timing constants; no windows. This cycle is a vocabulary + role
router, not a policy.

---

## 6. Marginal-benefit decomposition (mandatory)

Three variants considered.

### V1 — Simplest: add more CONF lists

Add `CONF_BED_SENSORS`, `CONF_CAMERA_PRESENCE_SENSORS`, `CONF_BLE_PRESENCE_SENSORS`.
Extend `TIER1_KINDS` to include each. Extend `_KIND_TO_CONF`. Every consumer in §1.5
picks up the new kinds by iterating the (now longer) tuple.

**Captures:** master-bedroom bed case — a bed lands in its own bucket instead of
`occupancy`. Immediate.

**Does NOT capture:** Study A `room_cameras` becoming a corroborator (still needs a
role-derivation site that can name "camera as corroborator"). Every future capability
addition = a new CONF list + a Tier 2-DB review (per `INVESTIGATION_voice_satellites_ura.md`
findings). "Corroborator" is STILL hardcoded to a CONF list, just a different one.

**Marginal cost:** low per addition, but O(N sites) each time, and pays down zero of the
downstream STUCK-SENSOR-1 or SIGNAL-TRUST-LEDGER blockage.

### V2 — Recommended: capability layer + role queries (§3)

**Captures:** V1 outcomes PLUS
- role derivation is O(1) at the query site to add a new capability kind
- STUCK-SENSOR-1 becomes buildable without hardcoding "corroborator = PIR bucket"
- SignalTrustLedger's `RoomSignal(..., source_kind)` becomes expressible
- intent-vs-evidence axis (`PLANNING_paper_and_oss_fusion_library.md` §7) has a home
- P15's "EXTEND, do not roll" verdict is honoured — the substrate stays, capability
  layers on top

**Marginal cost over V1:** one new dataclass, one new module (`sensor_role.py`), one new
CONF entry. Blast radius bounded because TIER1_KINDS is UNCHANGED (§3.3). One consumer
migrated in this cycle (D2); other consumers migrate in later cycles on their own budget.

**Verdict:** the margin pays. The blocking downstream card cannot be built on V1 without
re-introducing the exact defect it exists to fix.

### V3 — Rejected: full descriptor + auto-inference from device_registry

**Rejects:** manufacturer-string sniffing, device-integration classification, learned
capability. These are all rare-fire code paths whose failure mode is silent
mis-classification, which would then propagate into role queries. Ingredient risk: high;
observability: poor; testability: fixture-fragile. Deferred to §8 with an evidence
trigger ("if operator declares > N capabilities and the pattern is uniform per
integration, consider inference").

**Recommendation: BUILD V2.** Park V1 (subsumed) and V3 (deferred).

---

## 7. Tier classification argument

Per CLAUDE.md standing policy (2026-06-08): use Tier 2-DB for all regression-prone work;
elevate to Tier 3 when the change threads a value through a shared primitive consumed by
many sites and one missed site = silent defect.

**Ingredients present:**
- Shared primitive: `TIER1_KINDS` + `_KIND_TO_CONF` feeding ≥ 8 files in §1.5.
- One-missed-site topology (Bug Class #53): a consumer that iterates TIER1_KINDS but does
  not migrate to `resolve_role` will silently keep the old behaviour — and because
  behaviour "looks fine" (returns a value), the miss is invisible without a fixture
  covering that site.
- Cost-and-safety-impacting: presence trust feeds HVAC, lighting, fan-recheck, notification
  routing. A bed mis-classified as an mmWave stuck-candidate can vacate a sleeping
  bedroom (the exact hazard D2's `NOTIFY-ONLY` comment guards against, `coordinator.py:2007–2010`).
- Config × time × state seam: overrides can be added via options-flow mid-run; substrate
  refreshes on `SIGNAL_ROOM_ENTRY_LIFECYCLE`; F4 lock discipline must hold.

**Tier 3.** Four framing-disjoint reviews:

- **A — Local correctness.** Capability dataclass, derivation function, role resolver:
  arithmetic, type contracts, None handling, options-flow round-trip.
- **B — Integration + invariant preservation.** `_detect_duty_cycle_stuck` migration
  produces byte-identical candidate/corroborator sets when no override is declared, for
  every room; substrate dispatch payload unchanged; `_audit_provenance_invariants`
  continues to pass.
- **C — Per-site source mutation authority.** Reviewer edits `coordinator.py:1995` to
  hard-code `corroborators = motion_sensors` (bypassing `resolve_role`) and confirms
  `test_d2_master_bedroom_bed_corroborates` FAILS with the specific bed-as-corroborator
  assertion, not a generic pass/fail. Restore. Repeat for every migrated site.
- **D — Adversarial completeness.** State I1 as falsifiable and re-enumerate the ENTIRE
  §1.5 surface, including sites this cycle did NOT migrate (fan-recheck, provenance
  aggregate, binary_sensor attrs). Concrete legal-config repro for any deviation from
  I1. Extra scrutiny on: refresh-during-override, override-for-entity-in-multiple-CONF-
  lists (P15 collision), override arriving before boot-settle release.

The orchestrator MUST personally re-grep TIER1_KINDS + `_KIND_TO_CONF` + `resolve_role`
before deploy (independent verification, do not trust reviewer summaries).

**Operator checkpoint before deploy.** Surface: (a) the final invariant proof (I1
byte-identity fixture), (b) the list of consumers NOT migrated in this cycle, (c) the
mutation-anchored test names.

---

## 8. Explicit non-goals (parked, not deleted)

| Non-goal | Trigger to revisit |
|---|---|
| Chatter detection (transition-rate stuck class) | Owned by STUCK-SENSOR-1 / its chatter fold-in per kanban `third_class_chatter` note. This cycle does NOT touch `_detect_duty_cycle_stuck`'s detection logic — only its candidate/corroborator SET construction. |
| Graduating D2 from NOTIFY-ONLY to EXCLUSION | Owned by STUCK-SENSOR-1. This cycle only makes that discriminator EXPRESSIBLE; it does not flip the switch. |
| Building `SignalTrustLedger` | Explicitly build-gated on this cycle per `PLANNING_signal_trust_ledger_abstraction.md` Addendum 2026-08-09. Not built here. |
| Auto-inference of capability from device_registry / manufacturer strings | Revisit if the operator declares > 10 capability overrides AND the pattern is uniform per integration. Ingredient risk is high (§6 V3). |
| Migrating fan-recheck, sensor.py aggregation, or binary_sensor attrs to `resolve_role` | On their own budget in a follow-on cycle. This cycle migrates only D2 (the acceptance fixture). |
| Retiring `_KIND_TO_CONF` or shrinking TIER1_KINDS | Never. These are the wiring layer; the operator's ruling says wiring stays. |
| Extending `SIGNAL_SUBSTRATE_KIND_CHANGED` payload with capability info | Not in v1. Payload stays `(room, kind ∈ TIER1_KINDS, new_state)`. If a future ledger cycle needs a richer edge, it wraps this signal, does not replace it. |
| Voice-satellite `voice_activity` kind (`INVESTIGATION_voice_satellites_ura.md`) | That cycle's Tier 2-DB estimate now becomes a capability entry, not a TIER1_KINDS extension — likely cheaper. But out of scope here. |
| Deleting the `"tier1"` legacy sentinel at `presence.py:763` | Out of scope. Sentinel remains as-is. |

---

## 9. Plan-completion tracking template

To be filled at cycle close:

- D1 SensorCapability dataclass — [ ] shipped / [ ] deferred (reason)
- D2 resolve_role module — [ ] shipped / [ ] deferred (reason)
- D3 _detect_duty_cycle_stuck migration — [ ] shipped / [ ] deferred (reason)
- D4 config-flow selector — [ ] shipped / [ ] deferred (reason)
- D5 docs write-back — [ ] shipped / [ ] deferred (reason)
- Consumers listed in §1.5 but NOT migrated: [full list, each with "deferred to which cycle"]

---

## 10. Riskiest part of the change (surfaced for reviewer + operator)

The `_detect_duty_cycle_stuck` migration (D3) is the highest-risk site. Its current
positional signature `(motion_sensors, mmwave_sensors, occupancy_sensors)` IS a legacy
reification of `_KIND_TO_CONF`; the migration replaces set arithmetic on those three
lists with two `resolve_role` calls. The failure mode that keeps me up: an entity in
BOTH `mmwave_sensors` and `occupancy_sensors` under P15 precedence (defensive case,
`occupancy_substrate.py:214–222` WARN path) — today it appears in the concatenation
`mmwave_sensors + occupancy_sensors` and gets scored once; under `resolve_role` it must
also be scored exactly once. The mutation-anchored test in Reviewer C's framing MUST
cover this exact collision case with a legal fixture.

Second-riskiest: `_audit_provenance_invariants` at `presence.py:384` will RAISE if any
capability-derived kind leaks onto the legacy provenance channel. This is correct
behaviour, but a builder who "helpfully" adds `"bed"` to the audit's allowlist would
silently undo I3. The docstring on the audit function must be updated in this cycle to
say **explicitly** that TIER1_KINDS is the wiring vocabulary and capability kinds MUST
NOT be added to the allowlist under any future cycle. That is the durable ward.
