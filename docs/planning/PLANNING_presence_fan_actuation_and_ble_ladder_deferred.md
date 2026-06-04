# PLANNING — Presence Fan Actuation + BLE Ladder Layers 2/3 (DEFERRED)

**Versioning.** No version numbers pre-stamped. Per operator convention
(2026-06-03), versions are assigned at deploy time. Each cycle below is sized
relative to the predecessor, NOT pinned to a vX.Y.Z. The cycle bands ("next
patch", "patch+1", "v4.8.x backlog band") indicate sequencing only.

**Purpose.** This doc tracks every item that the first buildable cycle
(`PLANNING_presence_provenance_split_and_fan_diagnostic.md`) consciously
deferred. The CLAUDE.md Plan Completion Tracking rule prohibits silently
dropping planned items; this doc satisfies that rule for the presence-
hardening + fan-noise program.

**Why a separate doc instead of a tail-section in the buildable cycle's plan.**
Each deferred item has its own gating conditions (1 week of D3 diagnostic data;
hardware audit; non-URA audience). Lumping them as "future work" in the
buildable cycle's plan invites them to be silently dropped if the buildable
cycle's review/fix-up phase runs long. A standalone doc with explicit
gating + ownership keeps each item discoverable.

---

## Index of deferred items

| # | Item | Defer reason | Gating condition before promotion to buildable | Audience |
|---|---|---|---|---|
| 1 | BLE Layer-2 — adjacent-drift hold | Needs adjacent-room config model + ~1 week of D3 diagnostic feedback | Layer-1 D3 fires in ≥1 room over a week of normal usage AND operator confirms the "drift" pattern from `_fan_on_rooms` × person-coordinator timeline | URA |
| 2 | BLE Layer-3 — zone-absent → rare fan-pause-and-recheck (THE FIRST ACTUATION) | Needs Layer-1+2 data + actuation contract with HVAC fan policy + Tier 2-DB review of the actuation surface | Layer-2 ships AND `fan_interference_rooms` exhibits ≥N events/week where N is operator-decided | URA |
| 3 | PIR + mmwave fusion backstop (still-person rejection) | Hardware-gated — rooms today have mmwave-only | Operator audits which rooms have PIR coverage and which don't; sized as a hardware-audit cycle THEN a code cycle | URA |
| 4 | NON-URA research note + reusable HA blueprint | Separate audience (HA community), URA-independent | Layer-1 diagnostic data confirms the interference-conditional-reliability primitive is empirically real in this house, AND the algorithm is stable enough to teach | NON-URA / community |
| 5 | Removal of `mmwave_occupied_count` deprecation shim | Shim ships in the first buildable cycle; removal is the next cycle's tail | First buildable cycle is LIVE for one full cycle without regression | URA |

---

## Item 1 — BLE Layer-2 (adjacent-drift hold)

**Cycle band.** "Patch + 1" relative to the first buildable cycle. Sized as
Tier 2 (NOT Tier 2-DB) — no DB shape change anticipated, only consensus
arithmetic adjustment.

**Why deferred.** Layer-2 requires a notion of "adjacent rooms" that does NOT
exist in the URA data model today. The operator's design intent is:

> *Jaya's phone flips bathroom↔bedroom interchangeably. Room absent BUT
> adjacent configured BLE room present → DRIFT case, lean occupied, hold
> under decay, do NOT pause.*

Three sub-questions need answers BEFORE this cycle is buildable:

1. **Adjacency model.** Do we add `CONF_ADJACENT_ROOMS: list[str]` to per-room
   config_flow (operator names neighbors), OR derive adjacency from HA's
   `area_id` hierarchy (cheap but brittle), OR rely on a topology helper
   maintained outside the room entry? Operator decision required.
2. **Diagnostic-first or production-first?** Layer-1 (the first buildable
   cycle) ships as observation-only. Layer-2 could ship observation-only
   first (additional diagnostic flags) and then add the "hold under decay"
   semantic in a successor. RECOMMENDATION: yes, two-step, to preserve the
   "nothing is wrong, make it more Right" discipline.
3. **Decay timer reuse vs new.** Does Layer-2's "hold under decay" reuse
   the existing `_room_occupied` decay or introduce a new layer-specific
   timer? RECOMMENDATION: reuse — adjacency is a vote toward
   `_room_provenance[r]["mmwave"]` staying True past its natural decay
   expiry, not a new timer surface.

**Promotion gating.** Layer-2 only moves from this doc into a buildable plan
when ALL of:

- The first buildable cycle is LIVE and validated (no regression in zone-
  tracker `mode` distribution, no `_audit_provenance_invariants` violations).
- `fan_interference_rooms` from D3 has fired in ≥1 room over ≥1 week of
  normal usage.
- Operator confirms the adjacency-model choice (above #1) in a recorded
  decision (memory body or planning-doc preamble).

## Item 2 — BLE Layer-3 (zone-absent → rare fan-pause-and-recheck) — THE FIRST ACTUATION

**Cycle band.** "Patch + 2" minimum. Tier 2-DB (operator-elevated).

**Why deferred.** This is the FIRST cycle that DOES anything. Per the
operator's framing in the memory body, the pause is "disconcerting" by
default — the entire program design is structured to make the pause feel
RARE, JUSTIFIED, and BLE-corroborated rather than periodic. That requires:

- Layer-1 + Layer-2 already shipped and producing reliable corroboration data.
- An actuation contract with `domain_coordinators/hvac_fans.py`. URA presence
  side currently does NOT command fans. The Layer-3 pause must:
  - Respect existing fan policy (CONF_FAN_VACANCY_HOLD, CONF_FAN_TEMP_THRESHOLD,
    CONF_FAN_CONTROL_ENABLED at `const.py:474-490`).
  - Not race the HVAC fan-policy coordinator (Bug Class lifecycle hazard).
  - Be behind a per-room feature flag (CONF_FAN_INTERFERENCE_PAUSE_ENABLED).
  - Snapshot fan state pre-pause and restore post-pause-recheck.
  - Have a hard ceiling on pause attempts per room per hour.
- A FIRST-class operator UI for: enabling the pause per room; viewing pause
  history (timestamp, outcome — "still occupied" / "vacated"); auditable
  recovery if the pause-recheck fires while the operator is actively in the
  room.

**Tier 2-DB elevation justification.** The actuation touches HVAC fan policy
+ presence trust + safety (operator-comfort-in-room is a safety-adjacent
concern). Three-reviewer framing-disjoint protocol applies.

**Promotion gating.** Same conditions as Item 1, PLUS:

- Layer-2 (Item 1) is LIVE and validated.
- HVAC fan-policy team review confirms the actuation contract is viable.
- Operator confirms the per-room feature flag + pause-history UI scope.

## Item 3 — PIR + mmwave fusion backstop (still-person rejection)

**Cycle band.** v4.8.x backlog. Hardware-gated.

**Why deferred.** PIR detects warm moving bodies; fan blades aren't warm so
PIR ignores fans, BUT PIR misses a still person (reading, sleeping). The
provenance split shipped in the first buildable cycle MAKES this fusion
expressible (`_room_provenance[r]["motion"]` is now distinct from `["mmwave"]`)
but the hardware requirement is real:

- Rooms today that have ONLY mmwave (no PIR) cannot participate in the fusion.
- Mixed rooms (both PIR + mmwave) gain a structural backstop: when fan-on +
  mmwave-suspect, recent PIR (within e.g. 5 minutes) corroborates "real
  warm body was here recently" → trust the mmwave.
- This kills the disruptive pause AND the still-person blind spot — but only
  in the rooms with both sensors.

**Promotion gating.**

- Operator audits which rooms have PIR coverage (a non-code deliverable).
- Layer-1 + Layer-2 (and ideally Layer-3) shipped first, so this is the
  backstop, not the foundation.
- Per CLAUDE.md "BLE Device Budget" / hardware-cost discipline: any
  recommendation to add PIR to rooms is a separate operator decision, not a
  URA cycle output.

## Item 4 — NON-URA research note + reusable HA blueprint

**Cycle band.** Separate from URA cycle cadence. NOT a URA cycle at all —
this is a HA-community publication.

**Audience.** HA users (millions, per operator) struggling with mmwave
false-positives from fans / pets. NOT URA users. The blueprint must run on
plain HA entities: a mmwave binary_sensor, optional PIR, BLE / area presence,
and a fan switch → template/Bayesian occupancy sensor.

**Stub.** `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`
captures the prior-art landscape + the publishable contribution
(interference-conditional reliability + BLE zone-absence gating).

**Why deferred.** The publishable contribution depends on the operator
validating in their own house that the interference-conditional-reliability
primitive WORKS — which is exactly what the first buildable cycle's D3
Layer-1 diagnostic is meant to surface. Publishing the note before the
diagnostic data confirms the theory would risk fabricating a contribution.

**Promotion gating.**

- D3 Layer-1 diagnostic has produced ≥1 week of data confirming the
  pathology exists.
- The algorithm has stabilized (Layer-1 logic in URA hasn't changed for ≥1
  cycle).
- Operator decides the audience-handoff is worth the writing time.

**URA's only in-cycle obligation to this item — already discharged.** The
first buildable cycle's D3 docstring obligation (the D7 obligation) ensures
that when the blueprint writer arrives, the algorithm is documented in code
in a form that can be extracted without re-derivation.

## Item 5 — Removal of `mmwave_occupied_count` deprecation shim

**Cycle band.** "Patch + 1" tail-clean (could combine with Item 1).

**Why deferred.** The first buildable cycle ships the shim for one cycle to
let any external dashboard or template that keys on `mmwave_occupied_count`
keep working through one upgrade. Removal is a one-line change with a test
update.

**Promotion gating.** First buildable cycle is LIVE for ≥1 full cycle
without regression and the shim has been logged as accessed (or, if no
access logging is feasible, simply elapsed one cycle).

---

## Cross-refs

- `docs/planning/AUDIT_presence_provenance.md`
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md`
  (the first buildable cycle this doc defers from)
- `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md`
  (the audit-first investigation — origin of this program)
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md`
  (stub for Item 4)
- `docs/BACKLOG.md` (Fan-noise + Research-note entries)
- Memory: `project-fan-noise-mmwave-mitigation-backlog`
