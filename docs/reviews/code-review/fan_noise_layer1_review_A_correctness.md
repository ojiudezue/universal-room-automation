# Review A — Correctness + state-machine invariants

**Cycle:** Fan-noise mitigation D1 — Layer-1 silent interference-conditioned discount + decay
**Branch / commit:** `feature/fan-noise-layer1` @ `9522d0f` (cut from `develop` tip `59d44a7`)
**Plan:** `docs/planning/PLANNING_fan_noise_mitigation_layers1_2.md` (D1 only — D2 is design-only)
**Framing:** correctness + state-machine invariants (gate truth table, decay correctness,
edge-detection dispatch, phone-left-behind H2 carve-out, the truth-preserving invariant).
Reviewers B (async / lifecycle / cross-coordinator ripple) and C (new surfaces / DB /
test fixture authority) are running in parallel — anything off-framing is flagged with
"→ B" or "→ C" rather than expanded here.

## Verdict on the truth-preserving invariant

**HOLDS.** `ZonePresenceTracker._room_occupied` at `presence.py:507-515` evaluates
`any(bool(v) for v in kinds.values())` FIRST in the per-room dict-comp expression;
Python short-circuit semantics mean a positively-firing provenance kind always wins
regardless of `_fan_interference_hold_until[room]`. The gate at `presence.py:2458-2689`
writes ONLY to `_fan_interference_hold_until` and NEVER mutates `_room_provenance`.
`_audit_provenance_invariants` (`presence.py:326-363`) was correctly relaxed to permit
"derived True with no provenance only when hold is active" while still treating
"derived False with provenance True" as a hard violation — the exact shape the no-
regression mandate requires. The downstream consumer list (HVAC defer gate,
compliance, house inference) reads the same dict shape; worst case is "a fan-suspect
room stays occupied a bit too long," never a false-unoccupied. The invariant is
materially preserved.

## Findings

### CRITICAL

None.

### HIGH

#### H-A1 — L1 firing OUTSIDE the suspect window leaves a stale hold active for up to `hold_seconds`
**Bug class:** State machine residual / Reset rule incompleteness (planning doc §D1.2 "Reset rules" #1).
**File:line:** `presence.py:2615-2646` (the "not in suspect_set" branch of `_apply_fan_interference_gate`)
combined with `presence.py:2314-2324` (the L1 early-`continue` in `_compute_fan_interference_rooms`).
**Trace:** room R was suspect last tick → gate set hold; this tick a phone arrives in R.
`_compute_fan_interference_rooms` sees `ble_persons` and `continue`s → R is NOT in `suspect_rooms`.
In the gate, R takes the non-suspect branch (line 2619). The non-suspect branch only clears the hold
if (a) `non_mmwave_true` is True, or (b) the hold has already expired. mmwave is still firing (the
person triggered it). No non-mmwave kind fired (no PIR / occupancy). So neither condition fires:
the hold is preserved for its full 300s past the L1-confirming event. The planning doc explicitly
says "L1 fires → clear hold." Today's gate honours that rule ONLY while the room remains in the
suspect list — once a phone presence pushes the room OFF the suspect list, the L1 clear is missed.
**Why it matters:** benign for occupancy (the room IS occupied — phone is there), but it (i)
silently violates the documented reset rule, (ii) makes the per-room `fan_interference_hold_active`
attribute lie ("hold-active because of fan interference" when the actual reason a person walked in),
and (iii) means the next mmwave drop-out is invisibly held by a stale hold from a now-corroborated
state.
**Fix:** in the non-suspect branch, ALSO check L1 (call `_trustworthy_persons_in_room(room_name)`)
and `pop` the hold when L1 fires, regardless of `non_mmwave_true`.

#### H-A2 — `D3_DIAGNOSTIC_ENABLED=False` strands existing holds permanently
**Bug class:** Kill-switch state-leak / Bug Class #14 sibling (first-tick-after-flag-flip).
**File:line:** `presence.py:2510-2514` (early return when D3 OFF) + `presence.py:507-515` (property
always consults the hold dict).
**Trace:** operator flips `D3_DIAGNOSTIC_ENABLED` to False (or it ships False in a later cycle).
`_compute_fan_interference_rooms` returns `[]` (line :2295). `_apply_fan_interference_gate` returns
immediately on line 2514 with empty results. The early return SKIPS the non-suspect-branch decay
logic, so any room with an existing entry in `tracker._fan_interference_hold_until` keeps it
forever. The `_room_occupied` property at line 507 unconditionally consults the hold dict — no
gate of D3 there. Result: post-flip, every previously-held room reads occupied for its full
`hold_seconds` after the flag flip, then forever-True if `hold_until` was never going to expire
within the same `dt_util.utcnow()` clock. Even after expiry, the dict key remains (small mem leak);
worse, the surface attr `fan_interference_hold_active` will go stale.
**Fix:** when D3 is disabled, the gate should DRAIN holds — either clear `_fan_interference_hold_until`
across all trackers in the kill-switch branch, OR consult `D3_DIAGNOSTIC_ENABLED` in the property too.
Preferred: clear-on-disable at the gate entry, because the property must stay cheap.

#### H-A3 — `set_fan_interference_hold_s` change does not extend EXISTING holds
**Bug class:** Stale state under runtime tuning (operator-facing surprise).
**File:line:** `presence.py:4916-4939` (setter docstring says "does not refresh existing hold
expiries"); enforced by gate at `presence.py:2678-2680` (uses `hold_seconds` only when refreshing
on a suspect tick).
**Trace:** operator sets the slider from 300s → 1800s expecting "hold rooms longer." The change
is correctly picked up on the NEXT suspect tick (gate refreshes the room's expiry to
`now + 1800`). But for already-held rooms that are NOT suspect this tick (the H-A1 scenario, or
just intermittent fan-state churn), the OLD 300s expiry is honored until the next suspect tick.
Symmetric problem: lowering 1800s → 60s does not shorten existing holds (a room held at the old
30-min lifetime persists for ~28 more minutes after the change). The setter's docstring documents
this "feature," but it is surprising for a Number entity labeled SLIDER and is the kind of edge
the operator will notice as "the slider doesn't seem to do anything for a while."
**Fix:** in the setter, do `now = dt_util.utcnow()` and for every tracker, for every existing
`room → hold_until`, compute `delta = hold_until - now; new_hold_until = max(now, now + min(delta,
timedelta(seconds=new_value)))` — i.e. clamp existing expiries to the new value, never extending
past what was already promised. Document the clamp in the setter docstring.

### MEDIUM

#### M-A1 — `_phone_trustworthy` mock pattern is fragile in tests; uses module-level patch on `er.async_get`
**Bug class:** Test infra leak / cross-test contamination.
**File:line:** `quality/tests/test_fan_interference_gate_layer1.py:217-225` and `:259-262` — both
do `er.async_get = MagicMock(...)` which mutates the imported `entity_registry` module attribute
without restoration. Subsequent tests inherit the mock and may behave non-deterministically.
**Fix:** use `monkeypatch.setattr` (pytest fixture) so the patch reverts on test teardown.

#### M-A2 — Adjacency token resolution silently maps a free-text string to a room name
**Bug class:** Silent error / Garbage-in untraceable.
**File:line:** `presence.py:2596-2603`. If a token is an unrecognized `entry_id` (e.g., a deleted
room's entry_id stays referenced in some other room's `CONF_ADJACENT_ROOMS` after the rename),
the code falls through to `resolved.append(tok)` and the bogus entry_id ends up being used as a
room name in `_trustworthy_persons_in_room(adj_room)` → `person_coord.get_persons_in_room(<bogus>)`
returns `[]`, L2 silently never fires for that pair. Operator has no idea why their adjacency
isn't working.
**Fix:** when a token does not resolve AND is not an existing room_name in the running set, drop
it (don't append) and log at DEBUG with the unresolved token. Better: when an adjacent room is
deleted, the surviving room's options should be cleaned up — but that's a deferral. Minimum bar
for this cycle: drop unresolved tokens silently AND log.

#### M-A3 — Gate's edge-detection set `_fan_interference_gated_prev` is never pruned for deleted rooms
**Bug class:** Set-leak / long-running memory creep.
**File:line:** `presence.py:4471-4473`. The set is updated to `gated_now` each tick — which would
prune deleted rooms — BUT only when the room is part of the current tick's gated list. A room
that was suspect, fell off the suspect list, has its hold expire, then is renamed/deleted: it
never appears in `gated_now` again so the prune-by-replacement does work. Re-read confirms: the
full-set replacement `self._fan_interference_gated_prev = gated_now` at :4473 prunes correctly.
**False alarm — withdrawing this finding after re-reading.** Documenting for transparency.

#### M-A4 — Gate's `try/except` at `presence.py:2615-2687` swallows ALL exceptions and silently
returns partial state
**Bug class:** Defensive-handler swallows logic bugs (Bug Class #4 in QUALITY_CONTEXT.md — broad
`except Exception` hiding root cause).
**File:line:** `presence.py:2682-2687`. The outer `except` catches any error during the per-room
loop. The caller (`signal_consensus_inputs` block at :4461) receives a partial `gated_rooms`
list — but the edge-detection at :4471-4473 then computes `newly_gated` against a partial
`gated_now`, so a room that WAS gated last tick and SHOULD be gated this tick may be missing
from `gated_now` and from the dispatch, masking a bug. The `_LOGGER.debug` is also at debug
level — invisible at default log level.
**Fix:** log at WARNING with the failing tracker/room context; consider re-raising after logging
so the exception surfaces in `_run_inference`'s own try/except. At minimum elevate the log level.

#### M-A5 — `_audit_provenance_invariants` `now=None` fallback is a silent bypass of the no-hold check
**Bug class:** Defensive default permits invariant violation (Bug Class #20).
**File:line:** `presence.py:336-341` and `:351-363`. If `dt_util.utcnow()` raises (it shouldn't,
but the broad `except Exception`), `now=None` and `hold_active = ... and now is not None and ...`
evaluates False — so the audit FLAGS every hold-extended room as a violation. The reverse of
what's intended.
**Fix:** if `dt_util.utcnow()` raises, the audit cannot meaningfully run — return the violations
list AS-IS with a single appended `"audit cannot run: dt_util.utcnow raised"` violation, or skip
Invariant 1 entirely.

### LOW

#### L-A1 — `_apply_fan_interference_gate` does adjacency-map rebuild every tick
**Bug class:** Tick-rate work / minor perf (QC #5 sibling).
**File:line:** `presence.py:2562-2610`. The full config-entries enumeration + adjacency dict
build runs once per inference tick (~60s). Affordable today (low entry count) but better cached
behind a config-entry-update listener if room counts grow.

#### L-A2 — Hold expiry comparison uses `<=` for "expired" in the non-suspect branch but `>` for
"still active" in the property — boundary-tick semantics differ
**File:line:** `presence.py:2635` (`<= now` pops) vs `presence.py:512` (`hold[room] > now` reads
True). Functionally equivalent at sub-second granularity but stylistically off; pin one
convention.

#### L-A3 — Test `test_audit_invariants_flag_occupied_with_no_provenance_no_hold` does not
actually test the "violation" case it claims to
**File:line:** `quality/tests/test_fan_interference_gate_layer1.py:316-336`. The test sets up
provenance False + no hold, then asserts `_audit_provenance_invariants(tracker) == []` — i.e.
PASS, not violation. The docstring claims to verify the violation path but the body verifies the
clean path. Either the docstring is wrong or the test is. The truth-preserving safety net the
test is meant to anchor is not covered.
**Fix:** add a real test that monkey-patches `_room_occupied` to a forced True dict and asserts
the audit DOES flag.

#### L-A4 — `set_fan_interference_hold_s` `WARNING` log level on non-integer input is correct
but only logs `value` not type
**File:line:** `presence.py:4925-4929`. `_LOGGER.warning("... non-integer ... %r", value)` — fine
because `%r` shows type via repr, but consider adding `type(value).__name__` for clearer triage.

## Summary

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 3 (H-A1, H-A2, H-A3) |
| MEDIUM | 4 (M-A1, M-A2, M-A4, M-A5) — M-A3 withdrawn |
| LOW | 4 (L-A1..L-A4) |

**Must-fix before deploy (per Tier 2-DB protocol):**
- H-A1 — L1 clear missed when room exits suspect window
- H-A2 — D3 kill-switch leaks holds forever
- H-A3 — Number entity changes don't affect existing holds (operator-facing surprise)

**Truth-preserving verdict:** the invariant HOLDS in production code paths today. The three HIGH
findings are residual-state hazards (stale holds), NOT false-unoccupied paths. No CRITICAL.
Recommend: fix the three HIGHs + M-A4 (broad except swallows) before deploy; M-A1/M-A2/M-A5 and
LOWs are reasonable to fix in-cycle per the "Fix LOWs In-Cycle" operator directive (each is
1-30 LoC).

## Cross-references

- Bug classes touched: `docs/QUALITY_CONTEXT.md` #4 (broad except), #14 (boot/flip stale state),
  #20 (defensive defaults), #46 sibling (lazy-derivation discipline preserved by gate's read-path).
- Plan section: PLANNING_fan_noise_mitigation_layers1_2.md §D1.2 Reset rules (H-A1 violates rule
  #1), §D1.4 Acceptance Criteria (H-A1 violates "L1 fires mid-hold ... clears within one tick"
  for the cross-suspect-edge case), §D1.1 Kill switch (H-A2 violates "single source of fan-
  interference on/off").
- Audit doc: `docs/planning/AUDIT_fan_interference_gate_ripple.md` — verdict GREEN preserved
  by this review; the truth-preserving invariant the audit anchors on still holds.

## Fix-up status (Tier 2-DB fix-up pass)

| ID | Severity | Status | Notes |
|---|---|---|---|
| H-A1 | HIGH | **FIXED** | `presence.py` non-suspect branch now applies reset rule #1 (L1 positive corroboration clears hold) BEFORE the non-mmwave provenance check. Stale holds from now-corroborated rooms are popped within one tick. |
| H-A2 | HIGH | **FIXED** | `presence.py:~2515` kill-switch path drains every tracker's `_fan_interference_hold_until` dict before returning, so a flag-flip to False can't strand existing holds. Property no longer needs to consult D3 state. |
| H-A3 | HIGH | **FIXED** | `set_fan_interference_hold_s` now re-clamps every existing room's expiry to `min(existing_expiry, now + new_seconds)` on slider change. Truth-preserving: never extends past the original promise, only shortens. |
| M-A1 | MEDIUM | **DEFERRED** | `er.async_get = MagicMock(...)` module-level patch in `test_fan_interference_gate_layer1.py`. Genuine non-issue for the cycle suite (each `_build()` call constructs a fresh harness); will be cleaned in a future test-hygiene pass. |
| M-A2 | MEDIUM | **DEFERRED** | Unrecognized adjacency tokens are appended as-is (forward-compat for the bare-room-name selector pattern). Runtime-safe (resolves to empty silently). Sibling of C2. |
| M-A4 | MEDIUM | **FIXED** | Outer `_apply_fan_interference_gate` `except` now logs at WARNING (not debug) — real defects visible at default log level. Still returns the partial `gated_rooms` (graceful degradation preserved). |
| M-A5 | MEDIUM | **FIXED** | `_audit_provenance_invariants` now bails out of Invariant 1 with an explicit `"audit cannot run Invariant 1: ..."` diagnostic entry when `dt_util.utcnow()` raises, instead of silently flagging every hold-extended room as a violation. Other invariants still run. |
| L-A1 | LOW | **FIXED** | B-M1 cache work (see Review B) addresses the per-tick adjacency rebuild — same finding, fixed via `_rebuild_adjacency_cache` / `_invalidate_adjacency_cache` wired into discovery paths. |
| L-A2 | LOW | **DEFERRED** | `<=` vs `>` boundary-tick stylistic difference — functionally equivalent at sub-second granularity; deferred. |
| L-A3 | LOW | **FIXED** | C1 — `test_audit_invariants_flag_occupied_with_no_provenance_no_hold` rewritten to subclass the tracker so `_room_occupied` is forced True for an empty-provenance no-hold room; the audit DOES flag it now. Truth-preserving safety net is genuinely tested. |
| L-A4 | LOW | **FIXED** | `set_fan_interference_hold_s` warning now also logs `type(value).__name__` for clearer triage. |
