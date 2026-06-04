# INVESTIGATION — Presence Provenance Audit + Fan-Noise Mitigation (Audit-First, Coupled)

**Versioning:** This is audit-first. D1 (the audit) ships no code — it's an
investigation, and investigations do not get version numbers. Only the build
half (D2 OR-split + downstream) takes a version, assigned at deploy time as the
next available patch — NOT pre-stamped here. (Operator convention, 2026-06-03.)

**One cycle, two coupled threads.** Thread D (Tier-1 PIR/mmWave OR split — the
PREREQUISITE) and Thread A (fan-noise interference rejection — the consumer)
are scoped together but **gated** by an audit-first deliverable: NO code change
to the OR-split until the audit proves zero blind regression across every
presence path (room, zone, house, presence-coordinator). Thread A's code
deliverables are explicitly DEFERRED if the audit surfaces a gating risk — only
D1 (the audit) and D2 (the OR split, conditional on D1 verdict) are committed
in-cycle.

## Tier classification

**Tier 2-DB.** Triggered by: (a) presence ↔ HVAC ↔ compliance ↔ safety
trust-hierarchy ripple — the OR split changes the shape of `_room_occupied`,
which is read directly at `presence.py:3282` to compute `signal_consensus`,
which gates the HVAC defer + compliance compliance gate
(`presence.py:3265-3328`); (b) `zone_events` DB rows include a `rooms` field
populated from `tracker._room_occupied` (`presence.py:3337` →
`database.py:1798` `log_zone_event`) — payload shape changes invalidate
historical row comparability; (c) `check_zone_occupancy_confidence`
(`presence.py:968`) source-1 counts mmWave/PIR as ONE source — splitting may
change source counts and thus the adaptive HVAC threshold at
`hvac.py:954-956`. The three risk axes (data integrity, migration correctness,
new-surface authority) are distinct enough that two reviewers with the same
framing would converge on the same blind spots — exactly the v4.6.3 pattern
that motivated Tier 2-DB.

**Operator elevation note.** Even if a strict reading of the Tier 2-DB
triggers leaves room for Tier 2, the operator's framing ("nothing is wrong, I
just want to make it more Right") + the trust-hierarchy ripple are explicit
elevation grounds per CLAUDE.md § "Operator-elevated Tier 2-DB". Elevate.

## Versioning note

No number is pre-assigned. D1 (audit) ships no code — investigations aren't
versioned. The build half (D2 OR-split) is API-additive: existing callers of
`update_room_occupancy(name, occupied)` keep working because the new signature
defaults the provenance arg. No house-state contract change, no migration. When
it ships it takes the next available patch number at deploy time. Per operator
convention (2026-06-03), this is patch-level — major bumps are reserved for
major new functionality, never for hardening or refactors.

---

## Institutional context verified

### Greps run + REUSED / NEW verdicts for every proposed addition

| Proposed addition | Verdict | Evidence |
|---|---|---|
| Per-room provenance dict `{"motion": bool, "mmwave": bool, "occupancy": bool, "camera": bool, "ble": bool}` on `ZonePresenceTracker` | **NEW** | `Grep "_room_signals\|_room_provenance" custom_components/...` → no matches. Today there is only `_room_occupied: Dict[str, bool]` (`presence.py:211`). |
| `STATE_OCCUPANCY_SOURCE` string vocabulary ("motion", "mmwave", "occupancy_sensor", "camera", "ble", "failsafe", "timeout", "grace_hold", "none") | **REUSED** | `const.py:608` + producers at `coordinator.py:1352, 1360, 1362, 1364, 1381, 1384, 1388, 1454, 1483, 1530`. D2 normalizes on this exact vocabulary; no parallel string set introduced. |
| `CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` (PIR vs mmWave config separation) | **REUSED** | `const.py:311-313`. Already separate in the per-room config flow (`config_flow.py:94, 989, 6430`); the OR collapse happens DOWNSTREAM at the room→zone seam, not at config. **No new CONF_*.** |
| `CONF_FANS` (room-level fan entity list, for fan-on awareness) | **REUSED** | `const.py:366` + readers in `automation.py`, `domain_coordinators/hvac_fans.py`, `domain_coordinators/hvac.py`, `domain_coordinators/hvac_predict.py`. The presence coordinator does NOT currently subscribe to these; D2/D3 add a presence-side listener but **do not introduce a new fan-config field**. |
| `CONF_FAN_VACANCY_HOLD`, `CONF_FAN_TEMP_THRESHOLD`, `CONF_FAN_CONTROL_ENABLED` | **REUSED (do-not-touch)** | `const.py:474-490`. These are HVAC fan-policy fields; D2/D3 do NOT read or write them. Listed here so reviewers verify we don't accidentally entangle presence with the HVAC fan policy. |
| `STATE_MOTION_DETECTED`, `STATE_PRESENCE_DETECTED` (already separate at room level) | **REUSED** | `const.py:600-601` + per-room evaluation at `coordinator.py:1255-1267`. Strong prior art: the room coordinator already knows which sensor fired. The presence coordinator does not. **D2 closes that seam.** |
| `_last_trigger_source` / `_last_trigger_entity` (per-room) | **REUSED** | `coordinator.py:1287, 1295`. Per-room first-trigger provenance already exists; D2 plumbs it to the zone tracker rather than re-deriving. |
| `TransientSignal.kind` vocabulary ("camera_person_detected", "mmwave_occupied", "pir_motion", "unidentified_person_count") | **REUSED (separate path)** | `presence.py:138-148`. **Critical reuse caveat:** TransientSignal is the v4.7.x Bug Class #48 transient-vs-reliable arbitration path (camera/burst), NOT the Tier-1 `_room_occupied` path. Aligning the new provenance keys with these strings AVOIDS a parallel vocabulary while leaving the two evaluation paths separate. |
| `VetoDecision` dataclass (`fired, confidence, reason, scope`) | **REUSED (pattern)** | `presence.py:151-167`. D3 (fan-on interference gate) emits a VetoDecision-shaped record into `signal_consensus_inputs` for diagnostic parity with the existing Bug Class #48 vetoes. **No new dataclass.** |
| `check_zone_occupancy_confidence(zone) -> (confirmed, possible)` | **REUSED (must update)** | `presence.py:968`. Source-1 currently counts mmWave+PIR as ONE source via `_room_occupied`. D1 audit MUST classify this — does the split change source-1 from "1 possible" to "2 possible"? If yes, HVAC's adaptive threshold (`hvac.py:956`, `min(2, possible)`) changes and reviewer B in the parallel triad MUST sign off. Default proposal: keep "Tier-1 OR (mmwave OR pir)" as ONE source until D1 closes the question — see D1.5 acceptance. |
| `signal_consensus` calc at `presence.py:3265-3328` | **REUSED (must update)** | The mmwave_occupied_count tally (`presence.py:3282`) currently increments when ANY truth in `_room_occupied` is set. With provenance split, this becomes `tracker._room_provenance[room].get("mmwave", False)` — semantically the SAME post-deploy provided seeding and the live update path both populate "mmwave". Audit must prove no row-shape change to the signal_consensus_inputs dict (which is surfaced via D5 sensor attrs). |
| `_signal_consensus_inputs` dict keys | **REUSED (additive only)** | `presence.py:3313-3320`. D3 adds `fan_interference_active: bool` and `fan_interference_rooms: list[str]` keys — additive, no rename, no removal. Sensor consumers (`SIGNAL_PRESENCE_ENTITIES_UPDATE`) tolerate missing keys per existing `.get()` patterns. |
| `raw_occupied` property on `ZonePresenceTracker` | **REUSED** | `presence.py:237-244` (added v4.7.18.1). D2 augments raw_occupied with a `raw_occupied_by_kind(kind: str) -> bool` sibling — additive, original property untouched. |
| `_first_positive_zone_occupied_since` (WAKING-gate-private) | **REUSED (unchanged)** | `presence.py:2532-2538, 2829`. Wake-gate-private per v4.7.18.1 field-usage audit (`PLANNING_v4.7.18.1 §"Field-usage audit"`). D1 audit re-verifies this remains gate-private after the split. |
| `log_zone_event` DB payload (rooms TEXT) | **REUSED (audit only)** | `database.py:1798-1810`, schema `database.py:426-438`. The `rooms` column is TEXT (likely JSON-encoded list). D1 audit confirms row shape is unchanged by the split — rooms list is derived from `_room_occupied` truthiness, which D2 preserves as a derived view. **No schema change.** |
| `SIGNAL_HOUSE_STATE_CHANGED`, `SIGNAL_PRESENCE_ENTITIES_UPDATE` | **REUSED (unchanged)** | `domain_coordinators/signals.py:12, 40`. No payload shape change. |
| `PersonPhoneLeftBehindSensor` | **REUSED (referenced only)** | `binary_sensor.py:102, 973`. D3 fan-on gate's BLE corroborator must NOT treat "phone left behind" as evidence of presence — referenced in the design to mark the known false-positive, not consumed by D2/D3 code in v4.7.19. |
| `is_room_direct_ble` / `CONF_SCANNER_AREAS` (BLE tier classification) | **REUSED** | `person_coordinator.py:565, 1154, 1166, 1209`; `const.py:317`. D3 design hooks ble-ladder Layer-1 evaluation to `is_room_direct_ble(room_name)`. v4.7.19 does NOT ship Layer-2 (adjacent) or Layer-3 (zone-absent) — see D-deferred. |
| `BLE_TIER_2_WEIGHT` | **REUSED (unchanged)** | `const.py:334`. v4.7.16 weighted-veto constant. D3 does not modify it. |
| `D3_DIAGNOSTIC_ENABLED` | **REUSED (unchanged)** | `const.py:344`. Kill switch for v4.7.16 weighted veto — unrelated to D3 of this doc. **Naming collision warning:** "D3" here refers to deliverable 3 of v4.7.19, NOT to v4.7.16's D3. Reviewers MUST disambiguate. |
| `STATE_OCCUPIED`, `STATE_OCCUPANCY_SOURCE`, `STATE_BLE_PERSONS` | **REUSED** | `const.py:608` + `coordinator.py:1352-1530`. |
| Anomaly emit `coordinator_diagnostics` / `AnomalyType` | **REUSED (unchanged)** | v4.7.12 `event_class → anomaly_type` migration. D3 fan-interference observation, if recorded, uses an existing `AnomalyType` value — D1 audit decides whether to record at all (cost vs benefit). Default = no new anomaly type. |

### Prior planning docs consulted (in `docs/planning/`)

- `PLANNING_v4.7.18.1_sleep_wake_deadlock.md` — *full read.* `raw_occupied`
  property introduced here; field-usage audit pattern is the template for D1.
  v4.7.18.1's audit covered ONE field; v4.7.19 D1 covers the entire
  `_room_occupied` surface area.
- `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md` — *skim.* Confirms no
  presence-side change shipped in v4.7.18 (DPM-only).
- `PLANNING_v4.7.17.1_dpm_climate_norm_baseline.md` + IMPLICATIONS — *skim.*
  DPM-only, no presence interaction.
- `PLANNING_v4.7.17.x_ac_nudge_eval_window_tuning.md` — *skim.* HVAC nudge
  timing; not a presence consumer.
- `PLANNING_v4.7.16` (referenced from `const.py:318-344` comments) — *grep
  context.* D3 here introduces a `D3_DIAGNOSTIC_ENABLED` kill switch and
  `BLE_TIER_2_WEIGHT` weighted-veto path. Confirms reuse, flags naming
  collision (above).
- `PLANNING_v4.7.15` (referenced from `presence.py:3265-3328` comments) —
  *grep context.* `signal_consensus` + `_check_zone_occupancy_confidence`
  relocation. These are the read-side consumers D1 must audit.
- `PLANNING_v4.7.14` (referenced from `presence.py:494-502, 2807-2814`
  comments) — *grep context.* AWAY-state person-tracker veto reads
  `any_zone_occupied` (mode-based). v4.7.18.1's wake gate switched to
  `any_zone_raw_occupied`. D1 must verify the AWAY-veto reader is unaffected
  by the provenance split.
- `PLANNING_v4.7.12` (AnomalyType discriminator) — *grep context.* If D3
  records a "fan_interference" observation, it must use an existing
  `AnomalyType` value or none. Default: no new emission in v4.7.19.

### Memory bodies pulled

- `project-fan-noise-mmwave-mitigation-backlog` — full body (the design
  source for Thread A). Layered 1+2+PIR-fusion backstop, 3-layer BLE ladder,
  interference-conditional reliability reframe. **v4.7.19 ships only the
  prerequisite (D2 split) + the silent confidence-discount Layer-1 gate
  (D3); Layer-2 adjacent-drift and Layer-3 zone-absent rare-pause are
  explicitly deferred** — see D-deferred.
- `project-v4_7_18_1_sleep_wake_deadlock` — full body. raw_occupied
  established 2026-06-03 and the wake gate is now load-bearing on it. D2
  must preserve raw_occupied semantics exactly (composition: raw_occupied
  remains `any(provenance[r][kind] for r in rooms for kind in TIER1_KINDS)`
  — definitionally identical to today's `any(_room_occupied.values())`
  when the split is in steady state).
- `feedback-no-fabrication` + `feedback-no-fabrication-dhcp-incident` —
  applied throughout D1. Every claim about a reader's behavior is grounded
  in a file:line citation, not a mental model.
- `feedback-pre-deploy-zero-bugs-gate` — applied to D-acceptance: explicit
  conflict-marker grep + py_compile + cycle tests + suite-baseline-diff
  before deploy.
- `feedback-db-sensitive-3x-targeted-reviews` — applied to Tier 2-DB review
  framing (D-review).
- `feedback-fix-lows-in-cycle` — LOWs from the three review passes are
  fixed in-cycle (1-30 LoC) where reasonable; only genuine non-issues
  deferred; deferral list capped ~6.
- `feedback-no-soak` — no "monitor 24h" close-out. Trip-wires go in code
  (the D1 audit-diff diagnostic helper is the in-code trip wire).

### Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — *full read.* Covers the
  house-state inference layer. Crucially, the design doc does NOT specify
  Tier-1 sensor provenance — it treats per-room occupancy as a black box
  fed by Census. **The doc is consistent with the OR split; no design-doc
  contract change required.** D6 updates §5 INPUTS to mention the
  provenance dict as a v4.7.19 addition; no other section changes.
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — *skim.* Cross-coordinator
  signal contracts. `SIGNAL_HOUSE_STATE_CHANGED` payload unchanged.
- `docs/Coordinator/PRESENCE_COORDINATOR 2.md` — *spot-check only;
  duplicate of v1 doc per filename pattern.*

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  — `ZonePresenceTracker` (`:188-460`), `_run_inference` consensus block
  (`:3260-3346`), `_handle_occupancy_change` (`:1828-1870`), seed loop
  (`:1490-1515`), `check_zone_occupancy_confidence` (`:968-1010`),
  `raw_occupied` (`:237-244`), AWAY-veto reader region (`:2580-2630`),
  WAKING gate (`:2820-2860`).
- `custom_components/universal_room_automation/coordinator.py` — per-room
  occupancy block (`:1185-1530`), tier1 listener setup (`:820-910`),
  `STATE_OCCUPANCY_SOURCE` assignments (`:1352-1530`).
- `custom_components/universal_room_automation/const.py:280-500, 600-620`
  — CONF_*, STATE_*, BLE-tier weights.
- `custom_components/universal_room_automation/config_flow.py:94-100,
  950-1000, 6400-6450` — sensor + scanner-area selectors.
- `custom_components/universal_room_automation/database.py:420-438,
  1795-1815` — `zone_events` schema + `log_zone_event`.
- `custom_components/universal_room_automation/domain_coordinators/signals.py`
  — `SIGNAL_HOUSE_STATE_CHANGED`, `SIGNAL_PRESENCE_ENTITIES_UPDATE` (no
  payload shape change).
- `custom_components/universal_room_automation/domain_coordinators/hvac.py:940-960,
  1438-1450` — `check_zone_occupancy_confidence` consumer.
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py`
  — fan-policy module; verified D2/D3 do not need to read it (the presence
  side reads `CONF_FANS` entity states directly).
- `custom_components/universal_room_automation/aggregation.py` — confirmed
  it does NOT read `_room_occupied`, so the split is invisible to it.
- `docs/BACKLOG.md:1-105` — Thread A design source, full read.
- `docs/TECH_DEBT.md:7-29` — Thread D shortcut declaration, full read.
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`
  — full read. Stub establishes the differentiated contribution
  (interference-conditional reliability + BLE zone-absence gating) and
  explicitly scopes the write-up + blueprint as a SEPARATE, NON-URA
  deliverable. D7 in this doc tracks it as a thin scope handoff, not a
  v4.7.19 build item.

---

## The cycle gate — audit-first

```
                  v4.7.19 — sequence is load-bearing
                  ==================================

  D1 (audit)  ──► verdict
                    │
        ┌───────────┴───────────┐
        │                       │
   GREEN: no                COLOR: at least one
   regression risk           regression risk surfaced
        │                       │
        ▼                       ▼
   D2 ships in-cycle      D2 + downstream
   D3 ships in-cycle      DEFERRED. v4.7.19
   D4..D7 ship            ships ONLY D1 + D6
                          (design-doc update
                           reflecting findings)
                          + D7 (handoff).
                          Re-plan as v4.7.20.
```

The audit's job is to **refuse to ship** the OR split if any reader path
silently depends on the bool-collapsed semantics. The operator framing is
explicit: *"NOTHING is wrong, I just want to make it more Right."*

---

## Deliverables

### D1 — Context-wide audit of every presence path (THE GATE)

**Scope.** A written audit (committed at
`docs/planning/AUDIT_v4.7.19_presence_provenance.md`) that enumerates EVERY
reader of the bool-collapsed `_room_occupied` / `raw_occupied` / mode
surface and proves the OR split introduces no semantic change for each
reader. Audit-FIRST means D1 closes BEFORE any code in D2 is written.

**Reader inventory (the audit must cover at minimum — completeness is the
acceptance bar):**

1. **`ZonePresenceTracker._derived_mode`** (`presence.py:247-275`) — Tier-1
   line `any(self._room_occupied.values())` at `:261`. After split:
   `any(provenance[r][kind] for r in rooms for kind in TIER1_KINDS)` where
   `TIER1_KINDS = ("motion", "mmwave", "occupancy")`. Prove set equality
   under steady state.
2. **`ZonePresenceTracker.raw_occupied`** (`presence.py:237-244`) —
   v4.7.18.1's WAKING-gate-private property. Prove raw_occupied semantics
   are byte-identical before vs after split (composition theorem).
3. **`ZonePresenceTracker.update_room_occupancy(name, occupied)`** call
   sites (`:1514, :1854, :1864`) — prove backward-compatible API: existing
   callers that don't pass a `kind` arg get the same effect as today (the
   new signature defaults `kind=None` → writes to all TIER1_KINDS or to
   the legacy bool slot; D2 picks one and the audit ratifies).
4. **Seed loop** (`presence.py:1491-1515`) — currently seeds from any
   binary_sensor that's ON. After split, the seed must classify by sensor
   type (use the room coordinator's `CONF_MOTION_SENSORS` vs
   `CONF_MMWAVE_SENSORS` vs `CONF_OCCUPANCY_SENSORS` lists to attribute
   each entity_id). Prove every entity_id maps to exactly one kind, with
   "occupancy" as fallback when neither motion nor mmwave matches.
5. **`_handle_occupancy_change`** (`presence.py:1828-1870`) — same
   classification as the seed loop. Audit must confirm entity→kind
   mapping is identical between the seed path and the live path
   (Bug Class #1 hazard from v4.7.18.1 B-HIGH-1: seed vs live divergence).
6. **`_run_inference` signal_consensus block** (`presence.py:3265-3328`)
   — line `:3282` `mmwave_occupied_count` increments on ANY truth in
   `_room_occupied`. After split: only when `provenance[r]["mmwave"]` is
   true. **This is a semantic change for mixed-sensor rooms** (motion ON
   + mmwave OFF previously counted toward `mmwave_occupied_count`).
   Audit must verify the consensus arithmetic is unchanged or
   classify the change as deliberate. Default: count BOTH motion-only and
   mmwave-only rooms toward the existing "Tier 1" tally, keeping
   `mmwave_occupied_count` as a Tier-1 tally (the variable name becomes a
   misnomer; rename to `tier1_occupied_count` is a D2 polish — surfaced
   to reviewers).
7. **`_run_inference` zone_events DB write** (`presence.py:3329-3346`) —
   `rooms = [rn for rn, occ in tracker._room_occupied.items() if occ]`.
   After split, `_room_occupied` becomes a derived view of `_room_provenance`
   (`occ := any(prov.values())`). Prove the same room list is produced. DB
   row shape **must be unchanged** (`zone_events.rooms` column unchanged).
8. **`check_zone_occupancy_confidence(zone)`** (`presence.py:968-1010`)
   source-1 (motion/mmWave) — currently "1 possible, 1 confirmed if recent
   activity in any room sensor." After split: **decide explicitly** whether
   the source count changes. Default proposal: keep source-1 = "Tier 1
   (mmwave OR pir)" as ONE source. Alternative (raises confidence
   threshold): split into source-1a (mmwave) + source-1b (pir), bringing
   `possible` from 4 to 5. **The default keeps HVAC behavior pinned.**
9. **AWAY-state veto reader** (`presence.py:2580-2630`) —
   `any_zone_occupied` (mode-based) unaffected; `any_zone_raw_occupied` is
   `t.raw_occupied`; both prove invariant under D1 §2 above. Audit ratifies.
10. **HVAC defer gate** (`hvac.py:940-960`) — consumes
    `check_zone_occupancy_confidence`. Pinned by D1 §8 default.
11. **Compliance gate** (search for `_signal_consensus` consumers in
    `compliance.py`, `aggregation.py`, anomaly emitters) — audit must
    enumerate every consumer and verify each reads only the documented
    keys (`presence.py:3313-3320`); if any consumer reads
    `mmwave_occupied_count` and treats it as "mmwave-specific" (it isn't,
    even today, per the OR collapse), call that out — that's a latent
    bug NOT introduced by D2.
12. **Safety coordinator** — verify no direct read of `_room_occupied` or
    tracker private state. Grep `domain_coordinators/safety.py` for
    `_room_occupied`, `raw_occupied`, `_zone_trackers`. Expected: no
    matches.
13. **House state machine + StateInferenceEngine** — these read
    `PresenceContext` fields, not tracker internals. Audit confirms no
    leak.
14. **Diagnostic / sensor surfaces** — `sensor.ura_presence_diagnostics`,
    `SIGNAL_PRESENCE_ENTITIES_UPDATE` subscribers, `binary_sensor`
    entities. Audit walks `sensor.py`, `binary_sensor.py` grep for
    `_room_occupied`, `raw_occupied`, `mode`.

**Audit deliverable also includes a read-only diagnostic helper.** A new
module-level function `_audit_provenance_invariants(tracker) ->
list[str]` (returns list of invariant-violation strings; empty = clean)
that can be called from a debug button or test to verify in-running
state that `_room_occupied == derived_from(_room_provenance)`. Used in
D-acceptance live validation.

#### Acceptance Criteria — D1

- **Verify (doc):** the audit doc enumerates ≥14 reader paths above, each
  with a file:line citation and a one-line verdict (UNCHANGED / SEMANTIC-
  CHANGE-EXPLAINED / GATING — requires-redesign).
- **Verify (gate):** if ANY reader is classified GATING, D1 closes with a
  "DO NOT SHIP D2 in v4.7.19" verdict, and the cycle ships only D1 + D6
  + D7. No code in D2.
- **Verify (data):** the audit doc cites a `zone_events` row count
  baseline-rate by `(zone, event_type)` collected from the last 7 days
  pre-deploy, to enable post-deploy ±25% comparison per Tier 2-DB rules.
- **Sensor:** none added in D1.
- **Test:** `quality/tests/test_v4_7_19_provenance_audit.py::test_audit_doc_exists`
  asserts the audit doc is present and lists every reader path; harness
  only — content review is human.
- **Live:** N/A (audit is pre-code).

### D1.5 — Audit verdict checkpoint (NO-OP if D1 verdict is GREEN; HARD STOP if any GATING)

A formal merge-decision step in the planning doc, NOT a code deliverable.
After D1 is reviewed but before D2 begins, the operator signs the verdict.
This memorializes the gate and prevents accidental "let's just try it"
drift.

#### Acceptance Criteria — D1.5

- **Verify:** verdict captured in the audit doc as "GREEN — proceed" or
  "RED — defer D2..D5 to v4.7.20" with timestamp + operator signature
  (commit author line acceptable).

---

### D2 — Split `_room_occupied` into per-room per-kind provenance (CONDITIONAL on D1 GREEN)

**Change.** Replace `ZonePresenceTracker._room_occupied: Dict[str, bool]`
with `_room_provenance: Dict[str, Dict[str, bool]]` keyed by room then by
kind, where kind ∈ {"motion", "mmwave", "occupancy"} (TIER1_KINDS;
"camera" and "ble" are already separately tracked at
`_camera_occupied`/`_ble_occupied` and stay there). Expose
`_room_occupied` as a **derived `@property` that returns
`{r: any(p.values()) for r, p in self._room_provenance.items()}`** —
preserves the existing read shape used by line `:3282` and `:3337`.

**API.** `update_room_occupancy(room_name, occupied, kind=None)`:
- `kind=None` (legacy path, backward compatible): writes to ALL
  TIER1_KINDS when occupied=True (sets a "tier1" pseudo-kind to preserve
  the "we don't know which" case); when occupied=False, clears all kinds.
  D1 audit must ratify the all-or-nothing semantics for legacy callers.
- `kind="motion" | "mmwave" | "occupancy"`: writes that single kind.

**Producers.** Update the seed loop (`presence.py:1491-1515`) and
`_handle_occupancy_change` (`presence.py:1828-1870`) to classify
entity_ids by reading the owning room coordinator's
`CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` /
`CONF_OCCUPANCY_SENSORS` config (already accessible via
`hass.data[DOMAIN][room_name].config` or equivalent — D2 builder verifies
the access path). Classification fallback: "occupancy".

**Diagnostic surface.** Add `signal_consensus_inputs` keys (additive):
- `tier1_occupied_count` (rename-marker for old `mmwave_occupied_count`
  — see D2 polish below)
- `tier1_provenance_breakdown` (Dict[zone, Dict[kind, int]]) — diagnostic
  only, surfaced via `SIGNAL_PRESENCE_ENTITIES_UPDATE`.

**Variable rename (polish).** `mmwave_occupied_count` →
`tier1_occupied_count` at `presence.py:3275, 3282, 3286, 3307, 3318`.
Documented in the audit because the original name was a misnomer (it
counted any Tier-1 truth, not just mmwave). Rename is a localized
refactor; reviewer C in the parallel triad signs off on the rename's
test-surface authority.

#### Acceptance Criteria — D2

- **Verify:** `tracker._room_occupied` (now a property) returns the SAME
  dict shape as today for every existing reader; spot-check at
  `:3282, :3337` via assertions.
- **Verify:** `tracker.raw_occupied` returns the SAME bool as today for
  every test fixture in `quality/tests/`.
- **Verify:** seed-path and live-path entity→kind classification agree
  for every configured occupancy sensor across all rooms.
- **Sensor:** `sensor.ura_presence_house_state.attributes` gains
  `tier1_provenance_breakdown` key showing
  `{"zone1": {"motion": 2, "mmwave": 1, "occupancy": 0}, ...}`.
- **Sensor:** `sensor.ura_presence_house_state.attributes` retains
  `mmwave_occupied_count` for one cycle (v4.7.19) as a deprecation
  shim aliasing `tier1_occupied_count`; removed in v4.7.20.
- **Test:** `quality/tests/test_v4_7_19_provenance_split.py`:
  - `test_room_occupied_property_shape_equiv`
  - `test_raw_occupied_invariant`
  - `test_update_room_occupancy_legacy_signature_back_compat`
  - `test_update_room_occupancy_kind_motion_only`
  - `test_update_room_occupancy_kind_mmwave_only`
  - `test_seed_path_classifies_by_config`
  - `test_live_path_classifies_by_config`
  - `test_seed_and_live_classification_agree`
  - `test_signal_consensus_inputs_keys_additive_only`
- **Live:** `sensor.ura_presence_house_state.attributes
  ["tier1_provenance_breakdown"]` shows non-zero counts for at least one
  zone within 5 minutes of restart. Cross-validated against
  `binary_sensor.<room>_occupied` and the underlying sensor entities.
- **Live:** `sensor.ura_presence_house_state.attributes
  ["mmwave_occupied_count"]` value matches
  `tier1_occupied_count` (deprecation shim integrity).
- **Live:** `zone_events` row rate by `(zone, event_type)` within ±25% of
  the 7-day pre-deploy baseline collected in D1.

---

### D3 — Fan-on interference-conditional reliability (CONDITIONAL on D1 GREEN + D2 LIVE-GREEN)

**Change.** When ANY `CONF_FANS` entity for a room is `on` (the
interferer is active) AND the room's mmwave is the SOLE positive Tier-1
signal (`provenance[r] == {"mmwave": True, "motion": False,
"occupancy": False}`) AND BLE Layer-1 is absent (no direct-BLE persons
in the room per `person_coordinator.get_persons_in_room(room_name)`) AND
camera/`_camera_occupied` is False → mark the room's mmwave contribution
as **suspect**: the room remains "occupied" under the existing decay
timer (no behavior change to the zone tracker's `mode` output), but the
diagnostic `signal_consensus_inputs["fan_interference_rooms"]` lists the
suspect room. NO automated pause-and-recheck is shipped in v4.7.19.

This is **Layer-1 only** of the 3-layer BLE ladder + the
interference-conditional gate. **Layers 2 (adjacent-drift) and 3
(zone-absent → rare pause) are DEFERRED to v4.7.20.** v4.7.19 ships only
the silent diagnostic — operator can confirm via the new diagnostic key
that fan-suspect rooms are flagged before any actuation is added.

**Producer.** A new presence-side state-change listener for every
`CONF_FANS` entity (already enumerable via the room coordinator config).
Listener writes `tracker._fan_on_rooms: Set[str]`. `_run_inference`
consults this set when computing the diagnostic key.

**Why this is the right v4.7.19 scope.** D3 is observation-only: it
doesn't change the zone-tracker `mode`, doesn't change HVAC behavior,
doesn't change consensus arithmetic (the new key is additive). It
surfaces "is the fan-interference theory borne out in this house's data"
without taking any risk on actuation. Operator gets a week of data; if
the diagnostic shows fan-suspect rooms reliably, v4.7.20 can ship Layer
2/3 + the rare-pause actuation behind a feature flag.

#### Acceptance Criteria — D3

- **Verify:** when no `CONF_FANS` are configured for any room,
  `fan_interference_rooms == []` always; no listener overhead.
- **Verify:** when a fan is on and only mmwave fires (synthetic test),
  the room appears in `fan_interference_rooms`. When PIR also fires, the
  room does NOT appear (corroboration kills the suspect flag). When BLE
  Layer-1 is present, the room does NOT appear.
- **Verify:** zone-tracker `mode` output is identical with and without
  the D3 listener active (observation-only invariant).
- **Sensor:** `sensor.ura_presence_house_state.attributes
  ["fan_interference_rooms"]` and `["fan_interference_active"]` present.
- **Test:** `quality/tests/test_v4_7_19_fan_interference_layer1.py`:
  - `test_no_fan_config_no_observation`
  - `test_fan_on_mmwave_sole_no_ble_flags_room`
  - `test_fan_on_mmwave_plus_pir_does_not_flag`
  - `test_fan_on_mmwave_plus_ble_does_not_flag`
  - `test_mode_output_invariant_with_d3_listener`
- **Live:** within 24h of organic fan-on time, at least one room appears
  in `fan_interference_rooms` IF mmwave-sole and BLE-absent (otherwise
  the operator's setup happens to not exhibit the pathology — also a
  valid finding).
- **Live:** zone-tracker `mode` distribution by zone is within ±5% of
  the 7-day pre-deploy baseline.

---

### D4 — `check_zone_occupancy_confidence` audit ratification (CONDITIONAL on D1 GREEN)

**Change.** Code-level update to source-1 reflecting the D1 verdict
(default: keep source-1 = "Tier 1 (mmwave OR pir)" = ONE source;
explicit comment citing the D1 audit). Adds a docstring section
explicitly defining the source count and pinning it to the D1 decision.

#### Acceptance Criteria — D4

- **Verify:** `check_zone_occupancy_confidence` source count
  (`possible`) is unchanged for every test zone vs pre-deploy.
- **Test:** `quality/tests/test_v4_7_19_zone_confidence_unchanged.py`
  parameterized over fixture zones.
- **Live:** HVAC defer-gate behavior unchanged. `hvac.py:954-956`
  threshold `min(2, possible)` evaluates to identical values.

---

### D5 — Provenance diagnostic sensor (NEW, exposed via existing patterns)

**Change.** Add per-room provenance attributes to existing
`ZoneAnyoneBinarySensor` (or sibling) rather than a new entity.
Attributes added:
- `tier1_provenance: {"motion": bool, "mmwave": bool, "occupancy": bool}`
- `last_kind_to_fire: str` (one of TIER1_KINDS or "")
- `fan_on: bool`
- `fan_interference_suspect: bool` (from D3)

Surface follows the existing `SIGNAL_PRESENCE_ENTITIES_UPDATE` pattern;
no new dispatcher signal.

#### Acceptance Criteria — D5

- **Verify:** existing binary_sensor `is_on` state unchanged.
- **Sensor:** new attrs visible in HA developer-tools / states UI per
  room within 1 minute of restart.
- **Test:** `quality/tests/test_v4_7_19_provenance_attrs.py`.
- **Live:** spot-check 3 rooms with mixed sensor configs (motion-only,
  mmwave-only, both) and verify the attrs match expected.

---

### D6 — Update `docs/Coordinator/PRESENCE_COORDINATOR.md` + `docs/TECH_DEBT.md`

**Change.** Section §5 INPUTS of `PRESENCE_COORDINATOR.md` gains a
"Tier-1 provenance" paragraph documenting the per-kind dict. Move the
TECH_DEBT.md entry for "Tier 1 ORs mmWave + PIR" from active to
"Resolved in v4.7.19" with a back-pointer to this planning doc + the
audit doc.

If D1 verdict is RED (D2 deferred), D6 instead updates TECH_DEBT.md
to record the audit verdict + the GATING reader(s), and bumps the
revisit trigger.

#### Acceptance Criteria — D6

- **Verify (always-ships):** TECH_DEBT.md reflects the cycle's actual
  outcome (resolved vs deferred-with-findings).
- **Verify (if D2 ships):** PRESENCE_COORDINATOR.md §5 names the
  provenance dict and links to D1 audit.
- **Test:** `quality/tests/test_v4_7_19_docs_updated.py` greps for
  expected markers.

---

### D7 — Separable, NON-URA deliverable scope handoff (NOT BUILT in v4.7.19)

**Status.** Distinct, separable, **not a v4.7.19 build item.** Flagged
here only so reviewers don't expect it.

The research note + reusable plain-HA blueprint
(`docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`,
currently a stub) is its own task with its own audience (the wider HA
community, not URA users). Per BACKLOG.md entry "Research note +
reusable HA blueprint (NON-URA)", the write-up + blueprint stand alone
on plain HA entities (mmwave + optional PIR + BLE/area presence + fan
state → template/Bayesian occupancy sensor). v4.7.19 does NOT write the
blueprint, does NOT publish the research note, does NOT touch the
stub.

**v4.7.19's only obligation to D7:** ensure that if D3 ships, the
internal URA Layer-1 gate logic is documented well enough (in code
comments and D6 design doc update) that a future blueprint writer can
extract the algorithm without re-deriving it. **One acceptance line:**
the D3 fan-interference gate function has a module-level docstring of
≥10 lines explaining the interference-conditional-reliability primitive.

#### Acceptance Criteria — D7

- **Verify:** D3 gate docstring ≥10 lines, explicitly names the
  primitive ("interference-conditional reliability") and cross-references
  the RESEARCH stub.
- **Test:** `quality/tests/test_v4_7_19_d3_docstring_present.py`.
- **Live:** N/A (no runtime artifact).

---

## Deferred (explicit, do-not-silently-drop list)

| Item | Why deferred | Tracked for |
|---|---|---|
| D2-D5 ALL (full split + fan-gate) | If D1 verdict is RED | v4.7.20 re-plan |
| BLE Layer-2 (adjacent-drift hold) | Out of v4.7.19 scope; needs adjacent-room configuration model and D3 1-week diagnostic feedback first | v4.7.20 |
| BLE Layer-3 (zone-absent → rare fan-pause-and-recheck) | Out of v4.7.19 scope; needs Layer 1+2 live data AND an actuation contract with HVAC fan policy (not yet designed) | v4.7.20 or v4.7.21 |
| PIR+mmWave fusion backstop (still-person case) | Out of v4.7.19 scope; needs PIR hardware in rooms that today have only mmwave; sized as a separate "hardware audit" cycle | v4.8.x backlog |
| Research note write-up + reusable HA blueprint | Non-URA, separate audience | D7 handoff above; standalone task |
| Rename `mmwave_occupied_count` → `tier1_occupied_count` (sensor attr key) | Shipped in v4.7.19 as a deprecation shim; removal deferred | v4.7.20 |

---

## Review framing (Tier 2-DB — three parallel reviews, framing-disjoint)

Per CLAUDE.md Tier 2-DB protocol:

- **Reviewer A — Data integrity + DB architecture preservation.**
  Focus: `zone_events` row-shape invariance, `_signal_consensus_inputs`
  key-set additive-only, `check_zone_occupancy_confidence` `possible`
  count invariance, sensor attribute additive-only, no new schema, no
  new table. Cross-check D1's data integrity claims against actual code
  in D2.

- **Reviewer B — Migration correctness + signal chain integrity.**
  Focus: every reader of `_room_occupied` and `raw_occupied`
  (D1 §1-§14) produces equivalent values pre vs post D2; classification
  agreement between seed path and live path (Bug Class #1 hazard);
  `SIGNAL_HOUSE_STATE_CHANGED` and `SIGNAL_PRESENCE_ENTITIES_UPDATE`
  payload shape; no double-emit risk in D3 fan listener; field-by-field
  shape comparison of `_signal_consensus_inputs` dict pre vs post.

- **Reviewer C — New surfaces + test fixture authority.**
  Focus: D5 new sensor attrs round-trip through RestoreEntity; D3 fan
  listener registers correctly and unregisters on reload (Bug Class
  lifecycle hazards); test fixtures in `quality/tests/test_v4_7_19_*`
  extract schema from production source (no hand-copy of DDL); tests
  drive production code paths (not their own INSERT/UPDATE/DELETE on
  `zone_events`); rename `mmwave_occupied_count` → `tier1_occupied_count`
  deprecation shim semantics + test coverage.

**Pre-review baseline tag.** Before any review-fix is applied:
```
git tag pre-review-v4.7.19 -m "Pre-review baseline for v4.7.19"
```

**Pre-deploy ±25% baseline snapshot.** Per Tier 2-DB:
- `zone_events` row rate by `(zone, event_type)` over last 7 days
- `_signal_consensus` distribution (mean / p5 / p95) over last 7 days
- `check_zone_occupancy_confidence` (confirmed, possible) tuple
  distribution by zone over last 7 days

**Live validation (Reviewer D — post-restart).** Within 1 hour of
HA restart, verify:
- `tier1_provenance_breakdown` shows non-zero per-kind counts in at
  least one zone (real values flowing, not sentinels)
- `zone_events` row rate per `(zone, event_type)` within ±25% of
  baseline
- `mmwave_occupied_count == tier1_occupied_count` (shim integrity)
- `check_zone_occupancy_confidence` (confirmed, possible) per zone
  matches baseline distribution
- No URA ERROR logs containing `_room_occupied`, `_room_provenance`,
  `tier1`, `provenance`, `fan_interference`

---

## Pre-deploy zero-bugs gate (per feedback memo)

Before `./scripts/deploy.sh 4.7.19 ...`:

1. `git grep -n '<<<<<<<\|=======\|>>>>>>>' custom_components/`
   — must be empty
2. `python3 -m py_compile` on every changed `.py` file
3. `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4_7_19_*.py -v`
   — all pass
4. Suite baseline diff: total test count and pass count vs
   `pre-review-v4.7.19`

---

## Outline of files expected to change (D2..D5 only — D1 doc-only)

| File | Change | LoC est |
|---|---|---|
| `docs/planning/AUDIT_v4.7.19_presence_provenance.md` | NEW — D1 deliverable | ~600 doc |
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | D2: `_room_provenance` + property + signature change at `:211, :237-244, :247-275, :315-318, :1491-1515, :1828-1870, :3275-3320, :3337`. D3: fan listener registration + `_fan_on_rooms` set + inference-block diagnostic keys. D4: docstring update at `:968-1010`. | ~250 prod |
| `custom_components/universal_room_automation/binary_sensor.py` | D5: extra attrs on existing zone-anyone sensor | ~40 prod |
| `custom_components/universal_room_automation/const.py` | No new CONF_*. Maybe add `TIER1_KINDS: Final = ("motion", "mmwave", "occupancy")` tuple constant. | ~3 prod |
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | D6: §5 update | ~20 doc |
| `docs/TECH_DEBT.md` | D6: mark resolved (or update if deferred) | ~10 doc |
| `quality/tests/test_v4_7_19_provenance_audit.py` | D1 test harness | ~30 test |
| `quality/tests/test_v4_7_19_provenance_split.py` | D2 tests | ~180 test |
| `quality/tests/test_v4_7_19_fan_interference_layer1.py` | D3 tests | ~120 test |
| `quality/tests/test_v4_7_19_zone_confidence_unchanged.py` | D4 tests | ~50 test |
| `quality/tests/test_v4_7_19_provenance_attrs.py` | D5 tests | ~70 test |
| `quality/tests/test_v4_7_19_docs_updated.py` | D6 marker tests | ~20 test |
| `quality/tests/test_v4_7_19_d3_docstring_present.py` | D7 obligation | ~15 test |

**Total estimate.** ~290 prod LoC + ~485 test LoC + ~630 doc LoC. Audit
doc dominates the doc volume.

---

## Cross-refs

- `docs/BACKLOG.md:3-105` — Fan-noise design (source for D3).
- `docs/TECH_DEBT.md:7-29` — Tier-1 OR shortcut (source for D1/D2).
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`
  — stub for the non-URA D7 handoff.
- `docs/planning/PLANNING_v4.7.18.1_sleep_wake_deadlock.md` — `raw_occupied`
  origin + the field-usage-audit pattern this doc generalizes.
- Memory `project-fan-noise-mmwave-mitigation-backlog` (recall: "fan noise
  mmwave").
