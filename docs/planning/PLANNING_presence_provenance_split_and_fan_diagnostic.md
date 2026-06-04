# PLANNING — Presence Provenance Split + Fan-Interference Diagnostic (Observation-Only)

**Versioning.** No version number pre-stamped. Per operator convention
(2026-06-03), the next available patch number is assigned at deploy time.
References to "this cycle" in deliverables intentionally avoid a vX.Y.Z stamp.
Internal short-hand: "the provenance-split cycle."

**Predecessors that MUST be read in order before scoping or building.**

1. `docs/planning/AUDIT_presence_provenance.md` — gate verdict (GREEN) +
   `_audit_provenance_invariants` helper spec + operator sign-off block.
2. `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md`
   (full body + Appendix A — 27-consumer audit). The four doc-fidelity
   corrections are folded inline into the body (§D1, §D2, §D4) and
   summarized in **Appendix A.6**.
3. Memory body `project-fan-noise-mmwave-mitigation-backlog`.

**Cycle tier — Tier 2-DB (operator-elevated).** Three framing-disjoint
reviewers + post-deploy live validation. Justification matches the
investigation body: presence ↔ HVAC ↔ compliance ↔ safety trust-hierarchy
ripple. The audit being GREEN does NOT downgrade the tier — the trust-
hierarchy ripple is the elevation reason.

**Cycle is observation-only.** Zero changes to the zone-tracker `mode` output,
HVAC behavior, consensus arithmetic semantics, or any actuation surface. The
operator's framing — *"nothing is wrong, make it more Right"* — is honored
strictly by this scope. Any actuation (Layer-2 hold, Layer-3 pause-and-recheck)
ships in a later cycle. See `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md`.

---

## Institutional context verified

### Greps run + REUSED / NEW verdicts for every proposed addition

Per CLAUDE.md "Institutional Context First", every proposed new symbol or surface
listed below has been validated against `const.py`, `config_flow.py`,
`sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`,
`button.py`, `domain_coordinators/*.py`, and the per-coordinator design doc
`docs/Coordinator/PRESENCE_COORDINATOR.md`. References to file:line are
inherited from the investigation doc + Appendix A unless re-grepped during this
planning pass.

| Proposed addition | Verdict | Evidence |
|---|---|---|
| `ZonePresenceTracker._room_provenance: Dict[str, Dict[str, bool]]` | **NEW** | `Grep "_room_provenance"` → no matches. Replaces `_room_occupied` storage at `presence.py:211`. |
| `ZonePresenceTracker._room_occupied` (now a derived property) | **REUSED (read shape preserved)** | `presence.py:211` → becomes `@property`. Existing readers (Appendix A.2 rows 1, 4, 7, 10) untouched. |
| `TIER1_KINDS: Final = ("motion", "mmwave", "occupancy")` | **NEW (const module-level)** | `Grep "TIER1_KINDS"` → no matches. Tuple constant in `const.py`. No alternative exists. |
| `update_room_occupancy(room_name, occupied, kind=None)` signature | **REUSED (backward-compat)** | `presence.py:315-318`. `kind=None` defaults to legacy bool-write semantics — see D2 producer rules. |
| `ZonePresenceTracker._last_kind_per_room: Dict[str, str]` | **NEW** | `Grep "_last_kind_per_room"` → no matches. Diagnostic-only attribute. |
| `ZonePresenceTracker._fan_on_rooms: Set[str]` | **NEW** | `Grep "_fan_on_rooms\|fan_on_rooms"` → no matches. Populated by D3 fan-state listener. |
| `signal_consensus_inputs["tier1_provenance_breakdown"]` key | **REUSED (additive dict key)** | Dict at `presence.py:3313` — already extensible. No new dispatcher signal. |
| `signal_consensus_inputs["tier1_occupied_count"]` key | **REUSED (additive dict key, supersedes name)** | Replaces misnomer `mmwave_occupied_count`; old key kept as deprecation-shim alias for one cycle. |
| `signal_consensus_inputs["fan_interference_active"]` + `["fan_interference_rooms"]` keys | **REUSED (additive dict keys)** | Same dict, same dispatcher. |
| `CONF_FANS` (read access from presence side) | **REUSED** | `const.py:366`; read pattern matches `check_zone_occupancy_confidence` at `presence.py:1003-1008`. No new CONF. |
| `CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` / `CONF_OCCUPANCY_SENSORS` (read access from presence side, NEW path) | **REUSED (NEW cross-coordinator read path)** | `const.py:311-313`; today only consumed by `coordinator.py`. D2 adds a presence-side read — see Corrections doc #3. |
| `STATE_OCCUPANCY_SOURCE` string vocabulary | **REUSED** | `const.py:608` + producers at `coordinator.py:1352-1530`. D2's TIER1_KINDS strings align with the substring vocabulary already used in entity discovery (`presence.py:1460`). |
| `SIGNAL_PRESENCE_ENTITIES_UPDATE` | **REUSED (unchanged)** | `domain_coordinators/signals.py`. D5 sensor refresh rides this existing dispatcher. |
| `OccupiedBinarySensor` (per-room) | **REUSED (attrs additive)** | `binary_sensor.py:200` (RestoreEntity). D5 adds diagnostic attrs to this entity. |
| `PresenceHouseStateSensor` | **REUSED (attrs additive)** | `sensor.py:3755`. D5 adds zone-level rollup attrs to its `zones` map (which already exposes `signal_tiers` etc per `sensor.py:3855-3872`). |
| `SignalConsensusConfidenceSensor` | **REUSED (attrs unchanged)** | `sensor.py:3929`. Surface receives the new dict keys for free via `signal_consensus_inputs` round-trip. |
| `_audit_provenance_invariants(tracker)` module-level helper | **NEW** | Spec from `AUDIT_presence_provenance.md`. Diagnostic-only; no class attachment. |
| New diagnostic Number / Switch / Button entity | **NOT PROPOSED — explicit decline** | Per "Number Fields = Form Fields" feedback and the operator's "no actuation in this cycle" directive: zero new actuator-class entities. All surface is read-only attrs on existing entities. |
| New ConfigEntry option / config-flow field | **NOT PROPOSED — explicit decline** | D3 listener uses `CONF_FANS` already in entries. No new option. |

### Prior planning docs consulted (in `docs/planning/`)

- `PLANNING_v4.7.18.1_sleep_wake_deadlock.md` — *full read.* Source of the
  `raw_occupied` property + the field-usage-audit pattern this cycle's audit
  generalizes. Corrections doc #1 depends on the composition path this doc
  established.
- `PLANNING_v4.7.16` planning + `const.py:318-344` comments — *grep context.*
  Confirms BLE_TIER_2_WEIGHT + D3_DIAGNOSTIC_ENABLED naming collision risk
  with this cycle's deliverable D3 — disambiguated in the deliverable preamble.
- `PLANNING_v4.7.15` planning + `presence.py:3265-3328, 968-1010` comments —
  *grep context.* `signal_consensus` arithmetic + `check_zone_occupancy_confidence`
  authority. Both are audit-cleared SAFE (Appendix A.2 rows #7 and #21).
- `PLANNING_v4.7.14` planning + `presence.py:494-502, 2807-2814` comments —
  *grep context.* AWAY-state person-tracker veto. Audit-cleared SAFE (row #12).
- `PLANNING_v4.7.12` (AnomalyType discriminator) — *grep context.* D3
  fan-interference observation does NOT emit a new anomaly type in this cycle.
- `INVESTIGATION_presence_provenance_audit_and_fan_noise.md` + Appendix A —
  *full read.* The audit content this cycle consumes.

### Memory bodies pulled

- `project-fan-noise-mmwave-mitigation-backlog` — *full body.* The design source
  for this thread. This cycle ships the prereq (D2 split) + the silent
  diagnostic (Layer-1 Layer-1 BLE corroboration check at observation level only,
  no actuation).
- `project-v4_7_18_1_sleep_wake_deadlock` — *full body.* `raw_occupied`'s
  origin + load-bearing role in the WAKING gate. D2 must preserve its semantics
  exactly (the audit ratified this — see Corrections doc #1).
- `feedback-no-fabrication` + `feedback-no-fabrication-dhcp-incident` — applied
  throughout. Every consumer claim cited by file:line.
- `feedback-pre-deploy-zero-bugs-gate` — applied to deploy-time gate (below).
- `feedback-db-sensitive-3x-targeted-reviews` — applied to Tier 2-DB review
  framing (below).
- `feedback-fix-lows-in-cycle` — review-pass LOWs in 1-30 LoC range are fixed
  in-cycle; only non-issues deferred; cap ~6.
- `feedback-no-soak` — no "monitor 24h" close-out. The `_audit_provenance_invariants`
  helper is the in-code trip-wire that replaces a calendar reminder.
- `feedback-plan-phrasing-number-fields` — applied to UI surface design (D5).
  "Number fields" are not platform Number entities — and this cycle proposes
  NEITHER form fields NOR Number entities.

### Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — *full read.* §5 INPUTS is the
  one section that needs a Tier-1 provenance paragraph in D6. No contract
  change required.
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — *skim.* Cross-coordinator
  signal contracts; `SIGNAL_HOUSE_STATE_CHANGED` + `SIGNAL_PRESENCE_ENTITIES_UPDATE`
  payload shapes unchanged.

### Code locations surveyed end-to-end (re-grepped during this planning pass)

- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  — `ZonePresenceTracker` (`:188-460`), `_run_inference` consensus block
  (`:3260-3346`), `_handle_occupancy_change` (`:1828-1870`), seed loop
  (`:1490-1515`), `check_zone_occupancy_confidence` (`:968-1010`),
  `raw_occupied` (`:237-244`), AWAY-veto region (`:2580-2630`), WAKING gate
  (`:2820-2860`).
- `custom_components/universal_room_automation/coordinator.py` —
  per-room occupancy block (`:1185-1530`), STATE_OCCUPANCY_SOURCE assignments
  (`:1352-1530`), `CONF_FANS` enumeration (`:739-744`).
- `custom_components/universal_room_automation/sensor.py` — `PresenceHouseStateSensor`
  (`:3755-3873`), the `zones` attr dict shape (`:3855-3872`),
  `SignalConsensusConfidenceSensor` (`:3929-3995`).
- `custom_components/universal_room_automation/binary_sensor.py` —
  `OccupiedBinarySensor` (`:200-300`, RestoreEntity round-trip),
  `PersonPhoneLeftBehindSensor` (`:973`).
- `custom_components/universal_room_automation/const.py:280-500, 600-620, 366`
  — CONF_*, STATE_*, CONF_FANS.
- `custom_components/universal_room_automation/database.py:420-438,
  1795-1815` — `zone_events` schema + `log_zone_event` (no schema change).
- `custom_components/universal_room_automation/domain_coordinators/signals.py`
  — verified no new signal required.
- `custom_components/universal_room_automation/domain_coordinators/hvac.py:940-960,
  1438-1450` — `check_zone_occupancy_confidence` consumer (per Corrections #2,
  unaffected).
- `custom_components/universal_room_automation/aggregation.py` — re-confirmed
  no `_room_occupied` reads.

---

## The cycle gate — already passed (GREEN)

The audit gate that the investigation body specified is GREEN per
`AUDIT_presence_provenance.md`. This cycle is unblocked to ship D2-D6.

```
   AUDIT verdict (GREEN, signed by operator)
         │
         ▼
   This cycle ships:
     D2  — split _room_occupied into _room_provenance
     D3  — fan-on interference diagnostic (Layer-1 BLE corroboration,
            observation-only, NO actuation)
     D4  — check_zone_occupancy_confidence docstring fix (per Corrections #2)
     D5  — UI / sensor surface (the operator's explicit emphasis)
     D6  — docs/Coordinator/PRESENCE_COORDINATOR.md §5 + docs/TECH_DEBT.md
     D7  — D3 docstring obligation (10+ line module-level docstring
            naming the interference-conditional-reliability primitive)

   DEFERRED to subsequent cycles (see PLANNING_presence_fan_actuation_*.md):
     Layer-2 (adjacent-drift hold)
     Layer-3 (zone-absent → rare fan-pause-and-recheck) + actuation contract
     PIR + mmwave fusion backstop (hardware-gated)
     NON-URA research note + reusable HA blueprint (D7 handoff, separate
        audience, plain-HA entities)
```

---

## Deliverables

### D2 — Split `_room_occupied` into per-room per-kind provenance

**Change.** Replace
`ZonePresenceTracker._room_occupied: Dict[str, bool]` with
`_room_provenance: Dict[str, Dict[str, bool]]` keyed by room then by kind, where
kind ∈ `TIER1_KINDS = ("motion", "mmwave", "occupancy")`. Expose `_room_occupied`
as a derived `@property` returning
`{r: any(p.values()) for r, p in self._room_provenance.items()}`.

**Critical semantic note (per Corrections #4, restated honestly post-fix-up).**
Today's `_room_occupied` is last-writer-wins per room (mutator at
`presence.py:315-318` is bare assignment). D2's derived OR is "stronger on True,
equivalent on False" relative to that bool — NOT uniformly stronger:

- **True-edges:** per-kind ADDITIVE — a True write for one kind does not clear
  other kinds, so the OR stays True as long as any kind is still firing. This
  IS strictly stronger than the prior collapse (a quiet semantic improvement).
- **False-edges:** FULL-ROOM CLEAR — an `occupied=False` call wipes the entire
  per-kind bucket for the room regardless of `kind`, because today's discovery
  path cannot distinguish per-kind off-edges (the state-change callback only
  knows the ENTITY that went off; the prior bool was a full-room clear too).
  Equivalent to the old bool here, not stronger. Per-kind False clearing is
  intentionally NOT pursued in this cycle — the discovery path genuinely can't
  surface per-kind off-edges, and any heuristic "guess the kind from the
  entity_id at off-time" would re-introduce the seed-vs-live divergence hazard
  (v4.7.18.1 B-HIGH-1).

The build agent MUST flag this honest framing to reviewer A in the PR
description so the strengthening on True is not mistaken for uniform
strengthening, and so the full-room-clear semantics are visible up front. The
matching docstring on the `_room_occupied` property in `presence.py` carries
the same description verbatim (R1-H1 fix-up).

**API.** `update_room_occupancy(room_name, occupied, kind=None)`:
- `kind=None` (legacy path, backward compatible): when `occupied=True`, writes a
  sentinel `kind="tier1"` slot (preserves "we don't know which" case + the
  derived OR returns True). When `occupied=False`, clears all kinds for the
  room. The audit ratified this preserves today's behavior for any caller that
  doesn't pass a kind.
- `kind ∈ TIER1_KINDS`: writes that single kind. Other kinds are not touched
  unless `occupied=False` (which clears all).

**Producers.** Update the seed loop (`presence.py:1499-1515`) and
`_handle_occupancy_change` (`presence.py:1828-1870`) to classify the
firing entity_id. Per Corrections #3, the classification path is a NEW
cross-coordinator read of the owning room entry's `CONF_MOTION_SENSORS` /
`CONF_MMWAVE_SENSORS` / `CONF_OCCUPANCY_SENSORS` lists. Resolution algorithm:

1. Find the room ConfigEntry by iterating `hass.config_entries.async_entries(DOMAIN)`
   and matching `entry.data.get("room_name") == room_name` AND
   `entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM`.
2. If the entry has `CONF_MMWAVE_SENSORS` and the firing entity_id is in that
   list → kind = "mmwave". Else if in `CONF_MOTION_SENSORS` → "motion".
   Else if in `CONF_OCCUPANCY_SENSORS` → "occupancy". Else fall back to (3).
3. **Fallback (substring on entity_id).** If no room entry resolves or the
   entity is not in any list, classify by entity_id substring per the existing
   discovery filter at `presence.py:1460`: `"mmwave"` or `"presence"` → "mmwave";
   `"motion"` → "motion"; else "occupancy". This matches the keyword vocabulary
   the tracker already trusts for discovery.

**Producer invariant — seed/live agreement.** The same classifier function MUST
be used by both the seed loop and the live state-change callback. Bug Class #1
(seed-vs-live divergence) was the v4.7.18.1 B-HIGH-1 hazard; D2 must NOT
reintroduce it. The classifier is a module-level function (`_classify_entity_kind`),
NOT a method, so both call paths use the same code.

**`_last_kind_per_room: Dict[str, str]`.** Diagnostic-only attribute, updated by
the mutator at the moment a kind transitions from False to True. Empty string
when no kind has fired since last full clear.

**Variable rename (in-cycle polish).** `mmwave_occupied_count` (the
`_run_inference` local variable at `presence.py:3275-3318`) is and has always
been a misnomer — counts ALL Tier-1 truth, not mmwave-only. Rename to
`tier1_occupied_count` in the local, AND keep `mmwave_occupied_count` as a
deprecation-shim alias in the published `_signal_consensus_inputs` dict for one
cycle. Removal of the shim is explicitly tracked in the deferred roadmap.

#### Acceptance Criteria — D2

- **Verify (algebra):** for every fixture tracker, `tracker._room_occupied`
  (now a property) returns a dict with the same shape, keys, and values as
  today (drive via the existing fixture set in `quality/tests/`).
- **Verify (raw_occupied):** `tracker.raw_occupied` is byte-identical to today
  across all fixtures.
- **Verify (classifier):** seed-path and live-path entity → kind classification
  agree byte-for-byte for every configured Tier-1 sensor across every
  room-entry test fixture. The classifier is reached via the same function
  from both paths (test asserts function identity, not just equal output).
- **Verify (fallback):** for an entity_id not in any CONF_* list and unresolvable
  to a room entry, fallback substring classification matches the discovery
  filter's vocabulary at `presence.py:1460`.
- **Sensor:** `_signal_consensus_inputs["tier1_provenance_breakdown"]` populated
  with `{zone: {kind: int}}` after one inference cycle.
- **Sensor:** `_signal_consensus_inputs["tier1_occupied_count"]` matches the
  rename-shim `mmwave_occupied_count` exactly within the SAME tick.
- **Sensor:** all four UI surface items in D5 below are emitted via either
  `OccupiedBinarySensor.extra_state_attributes` or
  `PresenceHouseStateSensor.extra_state_attributes`.
- **Test:** `quality/tests/test_presence_provenance_split.py`:
  - `test_room_occupied_property_shape_equiv` — shape & values vs today
  - `test_raw_occupied_invariant` — byte-identical
  - `test_update_room_occupancy_legacy_signature_back_compat` — kind=None path
  - `test_update_room_occupancy_kind_motion_only`
  - `test_update_room_occupancy_kind_mmwave_only`
  - `test_update_room_occupancy_kind_occupancy_only`
  - `test_update_room_occupancy_occupied_false_clears_all_kinds`
  - `test_classify_entity_kind_uses_config_lists_first`
  - `test_classify_entity_kind_falls_back_to_substring`
  - `test_seed_and_live_use_same_classifier_function` — function identity
  - `test_signal_consensus_inputs_additive_only` — pre/post key-set diff
  - `test_invariants_hold_after_inference` — calls `_audit_provenance_invariants`,
    asserts `== []` across a synthetic inference run
- **Live (post-deploy ±1h):** `sensor.ura_presence_house_state.attributes
  ["zones"][<zone>]["tier1_provenance_breakdown"]` shows non-zero per-kind
  counts in at least one zone.
- **Live (post-deploy ±1h):** `mmwave_occupied_count == tier1_occupied_count`
  in `signal_consensus_inputs`.
- **Live (post-deploy ±1h):** `zone_events` row rate by `(zone, event_type)`
  within ±25% of the 7-day pre-deploy baseline collected in audit D1.
- **Live (post-deploy ±1h):** `_audit_provenance_invariants(tracker)` returns
  `[]` for every active tracker (exposed via a temporary template sensor or a
  one-shot ha_call_service into a debug entry — operator-driven, not committed).

### D3 — Fan-on interference-conditional Layer-1 diagnostic (OBSERVATION ONLY)

**Change.** When ALL of:
1. A configured `CONF_FANS` entity for the room is `state == "on"`, AND
2. `_room_provenance[room]["mmwave"]` is True AND
   `_room_provenance[room]["motion"]` is False AND
   `_room_provenance[room]["occupancy"]` is False (mmwave is the SOLE positive
   Tier-1 signal), AND
3. BLE Layer-1 indicates absence — i.e.,
   `person_coordinator.get_persons_in_room(room_name)` returns an empty list
   AND no `_camera_occupied[room]` truth for the same room,

then the room is added to a per-tick set `fan_interference_rooms` published in
`_signal_consensus_inputs`. The zone-tracker `mode` output is UNCHANGED — no
suppression, no decay change, no consensus arithmetic shift. This is purely a
diagnostic flag.

**Producer.** A new presence-side state-change listener registered per
`CONF_FANS` entity discovered during ZonePresenceTracker setup. Listener writes
into `ZonePresenceTracker._fan_on_rooms: Set[str]`. Listener is unregistered on
tracker teardown and on coordinator reload (Bug Class lifecycle — reviewer C
verifies). Listener is one per room, not one per fan entity, to keep the
state-change firehose narrow.

**BLE-Layer-1 access path.** `person_coordinator.get_persons_in_room(room_name)`
returns a list of person identifiers; empty list = no direct-BLE person in the
room. This bypasses the per-zone aggregation `_ble_occupied` (per Appendix A.3
finding). Build-time verify: `person_coordinator` resolution path during
`_run_inference` (operator confirms via spot-check of `presence.py:1003-1008`
pattern).

**Why observation-only is the right scope.** D3 takes zero risk on the zone
tracker's `mode` output and on HVAC behavior. It surfaces "is the
fan-interference pathology borne out in this house's data" so the operator can
DECIDE whether actuation is worth shipping. The deferred-roadmap doc spells out
what the operator looks at to make that call.

**Layer-2 and Layer-3 are DEFERRED.** See
`PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md`.

**D3 docstring obligation (THE D7 HANDOFF).** The D3 fan-interference gate
function MUST carry a module-level docstring of ≥10 lines that:

- Names the primitive ("interference-conditional reliability").
- Explains why static-reliability fusion (AOD/Bayesian) does not solve fan/pet
  interference (the structural blind spot per the research note stub).
- Cross-references `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`.
- Documents the THREE conditions (fan-on + mmwave-sole + BLE-Layer-1-absent) +
  why each is necessary.
- Notes that Layers 2 and 3 are deferred.

This docstring is the SOLE obligation this cycle owes the future blueprint
writer.

#### Acceptance Criteria — D3

- **Verify (no fans):** when no rooms have `CONF_FANS` configured,
  `_fan_on_rooms == set()` permanently, `fan_interference_rooms == []` per tick.
- **Verify (positive fire):** synthetic tracker fixture: fan on, mmwave sole,
  no PIR, no BLE, no camera → room appears in `fan_interference_rooms`.
- **Verify (negative — PIR corroboration):** fan on + mmwave + PIR → room is
  NOT in `fan_interference_rooms`.
- **Verify (negative — BLE corroboration):** fan on + mmwave + BLE-Layer-1
  present → room is NOT in `fan_interference_rooms`.
- **Verify (negative — camera corroboration):** fan on + mmwave + camera →
  room is NOT in `fan_interference_rooms`.
- **Verify (mode invariant):** zone-tracker `mode` output is byte-identical
  with and without D3 listener active, across the entire fixture suite.
- **Verify (lifecycle):** listener is unregistered on tracker teardown
  (verified via `async_will_remove_from_hass` or equivalent) and on
  coordinator reload.
- **Sensor:** `_signal_consensus_inputs["fan_interference_active"]: bool` and
  `["fan_interference_rooms"]: list[str]` exposed; round-tripped through
  `signal_consensus_inputs` to all readers per D5.
- **Test:** `quality/tests/test_presence_fan_interference_layer1.py`:
  - `test_no_fan_config_no_observation`
  - `test_fan_on_mmwave_sole_no_ble_no_camera_flags_room`
  - `test_fan_on_mmwave_plus_pir_does_not_flag`
  - `test_fan_on_mmwave_plus_ble_does_not_flag`
  - `test_fan_on_mmwave_plus_camera_does_not_flag`
  - `test_mode_output_invariant_with_d3_listener`
  - `test_listener_lifecycle_unregister_on_reload`
  - `test_d3_docstring_meets_obligation` — asserts ≥10 lines and the four
    key phrases ("interference-conditional", "fusion", "RESEARCH_2026-06-03",
    "deferred")
- **Live:** within 24h of organic fan-on time, at least one room appears in
  `fan_interference_rooms` IF the pathology exists in the operator's house.
  Absence of fires is also a valid finding ("operator's setup doesn't exhibit
  the pathology").
- **Live:** zone-tracker `mode` distribution by zone is within ±5% of the
  7-day pre-deploy baseline (mode-invariance proof).

### D4 — `check_zone_occupancy_confidence` docstring fix

**Change.** Per Corrections doc #2, the helper is independent of the OR split.
D4 collapses to a docstring update at `presence.py:968-1010` that explicitly
documents: source-1 reads each room coordinator's `_last_motion_time` (NOT the
zone tracker's `_room_occupied`); `possible` count is unchanged regardless of
D2; `hvac.py:953-961` adaptive-threshold behavior is pinned by this
documentation, not by code.

#### Acceptance Criteria — D4

- **Verify:** docstring explicitly cites Corrections #2 and the audit verdict.
- **Test:** `quality/tests/test_zone_confidence_doc.py::test_docstring_references_audit`.
- **Live:** `check_zone_occupancy_confidence(zone)` returns identical
  `(confirmed, possible)` tuples for every test zone vs the 7-day pre-deploy
  baseline.

### D5 — UI / sensor surface (THE OPERATOR'S EXPLICIT EMPHASIS — do not stint)

**Design philosophy.** The operator's mandate: *"for the presence work don't
stint on the UI/sensor surface. Make sure that's well considered."* The
investigation doc's original D5 was thin — ~40 LoC of attrs bolted onto a single
binary_sensor. This redesign treats the diagnostic surface as a first-class
deliverable.

**Operator's concrete user-story for the surface.** The operator must be able to
build, post-deploy, a dashboard card that watches for fan-interference over a
week of normal usage. The card answers two questions:

1. Per-room: *which Tier-1 sensor type is currently driving "occupied"*?
2. Per-room: *is this room being flagged as fan-interference-suspect right now,
   and has it been flagged recently*?

That dashboard is the evidence base for the later GO/NO-GO decision on
actuation (Layer-2 / Layer-3 in the deferred cycle).

**Design choices, evaluated explicitly:**

#### Choice 1 — Attrs on existing entities vs new dedicated sensor entities?

**Decision: Attrs on EXISTING entities. NO new platform Entity classes.**

Rationale:
- **Dashboard consumability** — operator's user-story is to read these as
  attributes of the already-canonical `OccupiedBinarySensor` (per-room) and
  `PresenceHouseStateSensor` (zone-rollup). HA dashboard `entities` card +
  `attribute` template-sensor pattern handles this idiomatically; no
  custom-entity glue.
- **Entity-count noise** — adding ~3 new diagnostic entities per room across an
  install with ~15 rooms = ~45 new entities competing for the entity-picker UI.
  Net cost > net value for what is fundamentally a diagnostic readout.
- **RestoreEntity round-trip** — provenance/fan-interference state is computed
  fresh every `_run_inference` tick. There is nothing to restore — last-known
  state is meaningless across restart (tracker rebuilds from sensor states).
  Putting these into RestoreEntity would be misleading.
- **Signal pipeline** — `OccupiedBinarySensor` and `PresenceHouseStateSensor`
  are already subscribers of the existing dispatchers; their attrs refresh on
  the next `_run_inference` tick without new wiring.
- **Backward compat** — old dashboards that read `is_on` keep working
  unchanged; new dashboards opt into the attrs.

**Counter-consideration weighed.** A dedicated
`sensor.ura_presence_provenance_<zone>` per zone would be more dashboard-card-
friendly for the operator's user-story (single entity to drop into a card,
attrs render cleanly). REJECTED because (a) the zone-rollup attrs already live
on `PresenceHouseStateSensor.zones`, (b) entity-count noise outweighs the
dashboard polish, (c) a future cycle can extract a dedicated entity if the
operator's dashboard work surfaces friction.

#### Choice 2 — Surface placement (which existing entity carries which attrs)

| Attribute | Entity | Rationale |
|---|---|---|
| `tier1_provenance: {"motion": bool, "mmwave": bool, "occupancy": bool}` | `OccupiedBinarySensor` (per-room) | Per-room provenance belongs on the per-room occupied sensor. Adjacent to `is_on` for visual alignment. |
| `last_kind_to_fire: str` | `OccupiedBinarySensor` (per-room) | Same locality as `tier1_provenance`. Empty string until a kind fires; persists across kind-False transitions (cleared only at full room-vacant decay). |
| `fan_on: bool` | `OccupiedBinarySensor` (per-room) | Per-room fan state — derived from `_fan_on_rooms` membership. Lets the operator see which rooms have a running fan adjacent to the provenance dict, without a dashboard hop. |
| `fan_interference_suspect: bool` | `OccupiedBinarySensor` (per-room) | Per-room flag from D3. The operator's week-long card watches this field for fire density. |
| `tier1_provenance_breakdown: Dict[zone, Dict[kind, int]]` | `PresenceHouseStateSensor.attributes["zones"][zone]` | Zone-level rollup. Extends the existing `zones[zone]` dict (which already exposes `signal_tiers`, `cameras_active`, etc per `sensor.py:3855-3872`). |
| `fan_interference_rooms: list[str]` | `PresenceHouseStateSensor.attributes["zones"][zone]` | Zone-level flag list. Card-friendly. |
| `fan_interference_active: bool` | `PresenceHouseStateSensor.attributes` (top-level, sibling to `signal_consensus_inputs`) | House-wide rollup — "any room currently suspect?" |
| `signal_consensus_inputs["tier1_occupied_count"]` (and shim `mmwave_occupied_count`) | `SignalConsensusConfidenceSensor.attributes["signal_consensus_inputs"]` (already exposed) | Free ride on `sensor.py:3987-3991`. No new code on the sensor side. |

#### Choice 3 — Deprecation-shim policy for `mmwave_occupied_count`

`mmwave_occupied_count` is renamed to `tier1_occupied_count` internally. The
published `_signal_consensus_inputs` dict keeps BOTH keys for one cycle, with
`mmwave_occupied_count` aliasing the new value. Removal of the shim is
tracked in the deferred-roadmap doc. The shim is documented in the D3
docstring AND in the D6 design-doc update.

#### Choice 4 — Refresh cadence

Both surface entities (`OccupiedBinarySensor`, `PresenceHouseStateSensor`)
already refresh on `SIGNAL_PRESENCE_ENTITIES_UPDATE` per
`presence.py:_run_inference` end-of-tick. NO new dispatcher signal. NO polling
loop.

#### Acceptance Criteria — D5

- **Verify (no new entity classes):** `Grep` of `binary_sensor.py` and
  `sensor.py` shows zero new `class .*Entity` blocks added by D5. Only
  attribute-dict extensions to existing entities.
- **Verify (per-room attrs visible):** for every active room,
  `state.attributes` of `binary_sensor.<room>_occupied` contains
  `tier1_provenance`, `last_kind_to_fire`, `fan_on`,
  `fan_interference_suspect`.
- **Verify (zone rollup):** `sensor.ura_presence_house_state.attributes
  ["zones"][<zone>]` contains `tier1_provenance_breakdown` and
  `fan_interference_rooms`. Top-level attrs contain
  `fan_interference_active`.
- **Verify (no RestoreEntity coupling):** D5 does NOT touch any
  `async_added_to_hass` / `async_get_last_state` path. Fresh per-tick reads only.
- **Sensor (operator dashboard):** A standard HA `entities` card with the
  per-room `OccupiedBinarySensor` entity expanded shows the four new attrs in
  the entity-more-info panel without additional template helpers.
- **Test:** `quality/tests/test_presence_provenance_surface.py`:
  - `test_occupied_binary_sensor_carries_provenance_attrs`
  - `test_occupied_binary_sensor_carries_fan_attrs`
  - `test_house_state_sensor_zones_carries_breakdown`
  - `test_house_state_sensor_top_level_fan_interference_active`
  - `test_no_new_entity_classes_introduced_by_d5`
  - `test_attrs_refresh_via_existing_signal` (asserts attrs refresh on the
    next `SIGNAL_PRESENCE_ENTITIES_UPDATE` dispatch, not on a new signal)
- **Live (post-deploy ±1h):** spot-check 3 rooms with mixed sensor configs
  (motion-only, mmwave-only, both) in HA developer-tools / states and verify
  the attrs match expected.
- **Live (post-deploy +1 week):** operator-built dashboard card surfaces at
  least one `fan_interference_suspect=True` event IF the pathology exists.
  Surface this finding back to the deferred roadmap to inform Layer-2/3
  go/no-go.

### D6 — Update `docs/Coordinator/PRESENCE_COORDINATOR.md` + `docs/TECH_DEBT.md`

**Change.** `PRESENCE_COORDINATOR.md` §5 INPUTS gains a "Tier-1 provenance"
paragraph documenting `_room_provenance` and the kind vocabulary. `TECH_DEBT.md`
"Presence — Tier 1 ORs mmWave + PIR" entry moves to "Resolved" with a
back-pointer to `AUDIT_presence_provenance.md` and this planning doc.

#### Acceptance Criteria — D6

- **Verify:** `PRESENCE_COORDINATOR.md` §5 contains a "Tier-1 provenance"
  subsection naming the kind vocabulary and linking the audit + this plan.
- **Verify:** `TECH_DEBT.md` Presence entry shows "Resolved (audit GREEN)"
  with the back-pointer.
- **Test:** `quality/tests/test_presence_provenance_docs.py` greps for
  the expected marker strings.

### D7 — D3 docstring obligation (the SOLE in-cycle handoff to the future blueprint writer)

Already specified inline in D3. D7 is not a separate code artifact; it is the
docstring discipline + the test that enforces it
(`test_d3_docstring_meets_obligation`). The non-URA research note and the
reusable HA blueprint themselves are NOT built in this cycle — see the
deferred-roadmap doc.

---

## Deferred (explicit, do-not-silently-drop list)

| Item | Why deferred | Tracked at |
|---|---|---|
| BLE Layer-2 (adjacent-drift hold) | Needs adjacent-room configuration model + 1 week of D3 diagnostic feedback | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` |
| BLE Layer-3 (zone-absent → rare fan-pause-and-recheck) | Needs Layer-1+2 live data + an actuation contract with HVAC fan policy + Tier 2-DB-level review of the actuation surface | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` |
| PIR + mmwave fusion backstop | Hardware-gated — needs PIR present in rooms that today only have mmwave | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` (v4.8.x backlog band) |
| NON-URA research note write-up + reusable HA blueprint | Separate audience (HA community), URA-independent, plain-HA entities | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` (D7 handoff section) |
| Removal of `mmwave_occupied_count` deprecation shim | Shim ships THIS cycle; removal is the next cycle's tail-clean | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` |

---

## Tier 2-DB review framing (three parallel reviews, framing-disjoint)

Per CLAUDE.md Tier 2-DB protocol. The three reviewer briefs MUST be given to
three independent agents in parallel; their framings explicitly differ so blind
spots cannot converge.

### Reviewer A — Data integrity + DB architecture preservation

Focus:
- `zone_events` row-shape invariance (`database.py:1798-1810`,
  `presence.py:3337`). Verify the `rooms` column TEXT payload is shape-identical
  pre vs post D2.
- `_signal_consensus_inputs` key-set is ADDITIVE only. New keys: `tier1_occupied_count`,
  `tier1_provenance_breakdown`, `fan_interference_active`, `fan_interference_rooms`.
  Old key `mmwave_occupied_count` retained as deprecation shim. Diff the key-set
  pre vs post.
- `check_zone_occupancy_confidence` `possible` count invariance (per Corrections
  #2 — should be trivially OK).
- No new schema, no new table.
- The "last-writer-wins → derived OR" strengthening per Corrections #4 — assess
  whether it produces a downstream row-rate change in `zone_events` or
  `presence_anomalies`.

### Reviewer B — Migration correctness + signal chain integrity

Focus:
- Every reader in Appendix A.2 (#1-#29) produces equivalent values pre vs post
  D2. The 14 SAFE rows in the tracker-readers section + the 5 SAFE rows in the
  HVAC-consumer section + the 7 SAFE rows in safety/compliance/aggregation are
  the audit's structural claim — verify reviewer-by-reviewer in code.
- Seed-path and live-path classifier agreement (Bug Class #1 hazard). Walk the
  test `test_seed_and_live_use_same_classifier_function` line-by-line, then
  walk the actual call sites in `presence.py:1499-1515` and
  `presence.py:1828-1870` to confirm both invoke the same module-level
  `_classify_entity_kind`.
- `SIGNAL_HOUSE_STATE_CHANGED` and `SIGNAL_PRESENCE_ENTITIES_UPDATE` payload
  shape unchanged (verified via the existing v4.7.14 test).
- D3 listener: no double-emit, no missed-deregister, no cross-coordinator
  race with the seed loop.
- Field-by-field shape comparison of `_signal_consensus_inputs` dict pre vs post
  (consume the existing snapshot pattern).

### Reviewer C — New surfaces + test fixture authority

Focus:
- D5 new attrs round-trip through HA's state machine. Note: D5 explicitly
  declines RestoreEntity coupling — verify that's actually the case (no
  `async_get_last_state` reads added for the new attrs).
- D3 listener registers correctly and unregisters on tracker teardown AND on
  coordinator reload. Listener lifecycle is the v4.7.18.1 Bug Class repeat
  risk.
- Test fixtures in `quality/tests/test_presence_*.py` extract schema from
  production source (no hand-copy of DDL or hand-copied dict shapes).
- Tests drive production code paths (the classifier is invoked via the seed
  loop and the live callback in tests, not by hand-constructed mock dicts).
- `mmwave_occupied_count` → `tier1_occupied_count` deprecation shim semantics
  + test coverage. Shim must be tested in BOTH directions (reader sees old key
  AND new key with equal values).
- D3 docstring obligation test (`test_d3_docstring_meets_obligation`) actually
  asserts the four key phrases.

### Pre-review baseline tag

```
git tag pre-review-<cycle-version> -m "Pre-review baseline"
```

(`<cycle-version>` = the patch number assigned at deploy time.)

### Pre-deploy ±25% baseline snapshot

Per Tier 2-DB:
- `zone_events` row rate by `(zone, event_type)` over last 7 days.
- `_signal_consensus` distribution (mean / p5 / p95) over last 7 days.
- `check_zone_occupancy_confidence` (confirmed, possible) tuple distribution
  per zone over last 7 days.
- Zone-tracker `mode` distribution per zone over last 7 days (new — supports
  D3 mode-invariance live check).

### Live validation (Reviewer D — post-restart)

Within 1 hour of HA restart, verify:
- `tier1_provenance_breakdown` shows non-zero per-kind counts in at least one
  zone (real values flowing, not sentinels — sentinels-only = payload shape
  broken, the v4.6.1.1 / v4.6.3-initial-build pattern).
- `zone_events` row rate per `(zone, event_type)` within ±25% of baseline.
- `mmwave_occupied_count == tier1_occupied_count` for every tick of the first
  hour (shim integrity).
- `check_zone_occupancy_confidence` `(confirmed, possible)` matches baseline
  distribution per zone.
- Zone-tracker `mode` distribution per zone within ±5% of baseline.
- `_audit_provenance_invariants(tracker) == []` for every active tracker.
- No URA ERROR logs containing `_room_occupied`, `_room_provenance`, `tier1`,
  `provenance`, `fan_interference`, `_fan_on_rooms`.

---

## Pre-deploy zero-bugs gate (per feedback memo)

Before `./scripts/deploy.sh <patch> ...`:

1. `git grep -n '<<<<<<<\|=======\|>>>>>>>' custom_components/` — must be empty.
2. `python3 -m py_compile` on every changed `.py` file.
3. `PYTHONPATH=quality python3 -m pytest quality/tests/test_presence_*.py -v` —
   all pass.
4. Suite baseline diff: total test count + pass count vs pre-review tag.

---

## Outline of files expected to change

| File | Change | LoC est |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | D2 `_room_provenance` + `@property` + classifier function + signature changes (`:211, :237-244, :247-275, :315-318, :1491-1515, :1828-1870`); D3 fan listener + `_fan_on_rooms` + inference-block diagnostic keys (`:3275-3320`); D4 docstring fix (`:968-1010`); `_audit_provenance_invariants` helper (module-level). | ~260 prod |
| `custom_components/universal_room_automation/binary_sensor.py` | D5 attrs on `OccupiedBinarySensor` — `extra_state_attributes` extension. | ~35 prod |
| `custom_components/universal_room_automation/sensor.py` | D5 attrs on `PresenceHouseStateSensor.zones[...]` + top-level (`:3855-3872, 3820-3830`). | ~30 prod |
| `custom_components/universal_room_automation/const.py` | `TIER1_KINDS: Final = ("motion", "mmwave", "occupancy")` tuple. | ~3 prod |
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | D6 §5 update. | ~20 doc |
| `docs/TECH_DEBT.md` | D6 mark resolved. | ~10 doc |
| `quality/tests/test_presence_provenance_audit.py` | D1 harness — audit doc existence + `_audit_provenance_invariants` helper. | ~30 test |
| `quality/tests/test_presence_provenance_split.py` | D2 tests (12 functions). | ~200 test |
| `quality/tests/test_presence_fan_interference_layer1.py` | D3 tests (8 functions, incl. docstring obligation). | ~140 test |
| `quality/tests/test_zone_confidence_doc.py` | D4 docstring marker. | ~20 test |
| `quality/tests/test_presence_provenance_surface.py` | D5 tests (6 functions). | ~110 test |
| `quality/tests/test_presence_provenance_docs.py` | D6 marker tests. | ~20 test |

**Total estimate.** ~330 prod LoC + ~520 test LoC + ~30 doc LoC.

---

## Cross-refs

- `docs/planning/AUDIT_presence_provenance.md`
- `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` (+
  Appendix A consumer audit; A.6 = the four folded doc-fidelity corrections)
- `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md`
  (deferred roadmap — Layer 2/3 + PIR fusion + research note handoff)
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`
- `docs/BACKLOG.md` (Fan-noise + Research-note entries)
- `docs/TECH_DEBT.md` (Tier-1 OR provenance)
- Memory: `project-fan-noise-mmwave-mitigation-backlog`
