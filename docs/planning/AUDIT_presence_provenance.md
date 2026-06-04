# AUDIT — Presence Provenance (Tier-1 OR Split, Context-Wide)

**Audit deliverable form.** This is the D1 gate artifact for the presence-hardening +
fan-noise mitigation program. It enumerates every reader of the bool-collapsed
`_room_occupied` / `raw_occupied` surface across the integration and either ratifies
the proposed per-room per-kind provenance split as SAFE or flags a GATING regression
that would defer the build.

**Versioning.** No version number is assigned to this audit. Investigations are
unversioned per operator convention (2026-06-03). The build cycle that consumes this
audit takes the next available patch number at deploy time.

**Status — GREEN (audit gate passed).** All surveyed consumers are SAFE or AT-RISK
(manageable at the seam). No GATING consumers found. Operator-signature line below.

**Audit method.** The work was originally executed in-place as Appendix A of
`docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` (lines
686-935). This document references that appendix as the canonical content rather than
duplicating it wholesale — the appendix carries 27-consumer file:line citations + the
SAFE/AT-RISK/GATING taxonomy + the four doc-fidelity corrections (A.6) + the four
build-time-verify items (A.7). This document adds the formal verdict, an operator
sign-off block, and specifies a read-only diagnostic invariants helper + harness test
that the build cycle is required to ship alongside the OR split.

---

## Gate verdict

**Verdict: GREEN — proceed with the OR split in the next buildable cycle.**

**Tally (from Appendix A.2 of the investigation doc):**

| Bucket | Count | Notes |
|---|---|---|
| SAFE consumers | 22 | Read-through derived property, or independent path through room coordinator. |
| AT-RISK consumers | 5 | All at the seam — 3 write sites + 1 deprecation-shim key + 1 name-only false alarm. Manageable in D2 without runtime regression. |
| GATING consumers | 0 | No reader silently depends on bool-collapsed semantics in a way that the split would break. |

**Operator-elevated Tier 2-DB** still applies regardless of the structural-only
findings. The trust-hierarchy ripple (presence ↔ HVAC ↔ compliance ↔ safety) is the
elevation justification; framing-disjoint three-reviewer protocol is mandatory.

**Operator sign-off line (to be filled at audit acceptance):**

```
Verdict acknowledged: GREEN — proceed.
Signed: <operator-name>
Date:   <YYYY-MM-DD>
Commit: <commit-hash where verdict is recorded>
```

---

## Reference — canonical audit content

The 27-consumer enumeration with file:line citations and SAFE/AT-RISK/GATING
verdicts lives in:

- **`docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` Appendix A**
  - A.1 — Re-pin the OR site(s) (writers at `presence.py:1499-1515` seed and
    `presence.py:1828-1870` live; mutator at `:315-318`); structural recognition
    that today's collapse is LAST-WRITER-WINS, not algebraic OR; discovery is by
    `area_id` + name keyword (NOT `CONF_*_SENSORS` lists).
  - A.2 — Consumer enumeration. Tracker readers (17 entries); HVAC consumers (5
    entries on an independent path); safety/compliance/aggregation (5 entries — all
    no-match greps).
  - A.3 — Prior-art verification (`is_room_direct_ble`, `check_zone_occupancy_confidence`
    actual signature, `PersonPhoneLeftBehindSensor`, `_ble_occupied` per-zone path).
  - A.4 — Fan-entity visibility (`CONF_FANS` reachable from presence side; no new
    CONF needed).
  - A.5 — Go/no-go (GO) + the six structural clarifications that constrain D2's design.
  - A.6 — Four doc-fidelity corrections to the investigation doc body (applied via
    the `INVESTIGATION_*.md` edit accompanying this audit).
  - A.7 — Four items NOT covered by the audit, stamped as build-time-verify.

The audit content is not duplicated here to keep the gate artifact short and
unambiguous. Reviewers walk Appendix A line-by-line during review.

---

## Build-cycle obligation — the invariants helper

D1 ratification requires the build cycle to ship a **read-only diagnostic helper**
that the operator (or a harness test) can call at any point to verify the derived
`_room_occupied` view stays algebraically consistent with the underlying
`_room_provenance` store. The helper is observation-only — it never mutates state.

**Spec:**

```python
def _audit_provenance_invariants(tracker) -> list[str]:
    """Return a list of invariant-violation strings; empty list = clean.

    Read-only diagnostic. Walks _room_provenance and verifies:
      1) For every room r, _room_occupied[r] == any(_room_provenance[r].values()).
      2) Every kind in _room_provenance[r] is in TIER1_KINDS.
      3) raw_occupied composes through _derived_mode (per A.6 correction #1) —
         walked indirectly via _derived_mode being callable without raise.
      4) No room is present in _room_provenance but absent from _room_occupied
         (or vice versa). Set equality of keys.

    Used by:
      - quality/tests/test_provenance_split.py::test_invariants_hold_after_inference
      - A future diagnostic button (NOT a v4.7.19 deliverable — backlog).
    """
```

**Module placement.** `domain_coordinators/presence.py`, module-level (not method),
adjacent to the `ZonePresenceTracker` class. Keeps it greppable and avoids attaching
diagnostic surface to the class proper.

**Harness test.** `quality/tests/test_provenance_split.py::test_invariants_hold_after_inference`
constructs a tracker via the production fixture, drives a sequence of
`update_room_occupancy` calls (mixed kinds + legacy bool path), runs one inference
cycle, then asserts `_audit_provenance_invariants(tracker) == []`. Parameterize over
{kind=motion, kind=mmwave, kind=occupancy, kind=None (legacy)} × {first call, second
call, occupied=False clear}.

**Why this is part of the audit deliverable, not the build deliverable.** The audit
is what proves NO blind regression. The helper makes that proof inspectable at
runtime so a future change to `_room_occupied` / `_room_provenance` semantics
trips a clear assertion instead of a silent drift. This is the in-code trip-wire that
the "no soak watching" rule requires.

---

## Acceptance criteria for D1 (this audit)

- **Verify (doc):** This file exists, references Appendix A of the investigation
  doc, and records the GREEN verdict.
- **Verify (gate):** No reader is classified GATING in Appendix A.2 — confirmed by
  walking the table (22 SAFE, 5 AT-RISK, 0 GATING).
- **Verify (sign-off):** Operator sign-off block populated before the build cycle
  begins. Empty sign-off block = "not yet accepted" = build cycle does not start.
- **Verify (helper spec):** Build cycle ships
  `_audit_provenance_invariants(tracker)` and the matching harness test.
- **Sensor:** None added by D1.
- **Test:** `quality/tests/test_presence_provenance_audit.py::test_audit_doc_exists`
  asserts this file is present and contains the verdict line, the Appendix A
  reference, and the helper spec block. Content review is human.
- **Live:** N/A — audit is pre-code.

---

## Cross-refs

- `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` —
  full investigation + Appendix A (the audit body).
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` —
  the first buildable cycle (Tier-1 OR split + Layer-1 fan-interference
  diagnostic + UI/sensor surface).
- `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` —
  the deferred roadmap (Layer 2/3 + PIR fusion + research note handoff).
- `docs/TECH_DEBT.md` — "Presence — Tier 1 ORs mmWave + PIR into one per-room bool"
  entry; updated to "Resolved (audit GREEN)" by the build cycle's D6 once the OR
  split lands.
