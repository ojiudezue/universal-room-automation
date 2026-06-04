# Fan-noise Layer-1 (D1) — Review C: New surfaces + config round-trip + test-fixture authority + cross-rule precedence

**Branch:** `feature/fan-noise-layer1` @ `9522d0f`
**Framing:** Tier 2-DB Review C. New CONF round-trip, RestoreEntity, test-fixture authority, cross-rule precedence. (D1 adds no DB table — DAO is deferred D2 — so the DB-schema lane is light.)

> Note: this doc was reconstructed from Review C's completed analysis report; the reviewing agent finished its analysis but exited before persisting the file.

## Findings

| ID | Severity | Bug class | Location | Finding | Fix |
|---|---|---|---|---|---|
| C1 | LOW | Test-fixture authority (hollow test) | `quality/tests/test_fan_interference_gate_layer1.py` `test_audit_invariants_flag_occupied_with_no_provenance_no_hold` | Test "documents the helper's logic" rather than verifying it — monkey-patches state but asserts `[]` and never drives the violation case. Would pass even if the invariant logic were wrong. | Rewrite to actually construct an occupied-with-no-provenance-no-hold state and assert the audit flags it; or delete if `_audit_provenance_invariants` is test-only scaffolding (see note). |
| C2 | LOW | Config hygiene (stale references) | `config_flow.py` `CONF_ADJACENT_ROOMS` selector + `presence.py` `_apply_fan_interference_gate` resolver | Deleting a room leaves its `entry_id` in other rooms' `CONF_ADJACENT_ROOMS`. No cleanup. Resolver falls back to treating an unresolved token as a bare room name → `get_persons_in_room("<entry_id>")` returns empty → **safe at runtime**, but garbage accumulates in stored config. | Optional: prune stale `entry_id`s on reconfigure / room removal. Low priority — runtime is safe. |

## Confirmed-OK (not findings)
- **Self-reference:** reconfigure flow filters `e.entry_id != self._config_entry.entry_id`; install-time the room doesn't exist yet, so self-reference is impossible. Correct.
- **Blank adjacency:** empty/missing `CONF_ADJACENT_ROOMS` falls back to L1+L3 with no crash. Correct (matches locked operator decision).
- **`_audit_provenance_invariants` relaxation:** the helper is **test-only — never called from production code**, so the hold-extension relaxation is correct and gates no runtime behavior. (This is why C1 is LOW.)

## Verdict on test-fixture authority
The 22 new tests predominantly DRIVE production paths (`_room_occupied`, `_apply_fan_interference_gate`) rather than re-implementing logic — good. One hollow test (C1). No hand-copied constants/DDL found. The two brittle-test edits (`test_presence_provenance_surface.py` signal-allowlist widen; `test_v4510_hvac_tunables_and_labels.py` 3000→5000 window) are legitimate accommodations of the new signal + new Number entity, not regression masking.

## Severity counts
CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 2

## Fix-up status (Tier 2-DB fix-up pass)

| ID | Severity | Status | Notes |
|---|---|---|---|
| C1 | LOW | **FIXED** | `test_audit_invariants_flag_occupied_with_no_provenance_no_hold` rewritten. The new test subclasses the tracker so `_room_occupied` is forced True for room "a" while provenance OR is False AND no hold is active. The audit MUST flag this — assertion now reads `"no active" in v and "fan-interference hold" in v` against the returned violations. The truth-preserving safety net is genuinely tested instead of documented. |
| C2 | LOW | **DEFERRED** | Stale entry_id references in `CONF_ADJACENT_ROOMS` after room deletion. Runtime-safe (resolver appends as-is, downstream `get_persons_in_room` returns []). Per task spec defer list — pruning is low-value churn. The new `_rebuild_adjacency_cache` carries the same forward-compat behavior (resolved.append(tok) for unknown tokens). |
