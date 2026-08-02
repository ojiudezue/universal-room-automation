# Fan-Transition Coincidence Gate — Tier 2-DB Review Record (shipped v5.46.0)

Change: creation-only suppression of mmWave-sole occupancy within
`FAN_TRANSITION_SUSPECT_WINDOW_S=5.0` s of a fan power/speed transition
(branch `feature/fan-transition-gate`, build `b5f1cfa66`, fix-up `3bc2042b4`).
Basis: `docs/planning/AUDIT_fan_signature_separability_probe.md` — both labeled
phantom events began at the exact second of a fan transition; steady-state fans
produced multi-hour negatives.

Three framing-disjoint reviews per the raised autonomous mandate (Tier 2-DB
minimum for all regression-prone work).

## Findings

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| B1 | HIGH | Gate suppression fell into the debounce else-branch, resetting `_occupancy_first_detected` — a PIR corroboration one tick later restarted debounce from zero, contradicting the block comment | FIXED — `_fan_gate_suppressed` local flag; else-branch preserves debounce clock + refresh unsub when set; new preservation test; orchestrator drill 2 red on guard neuter |
| B2 | MED | Same-tick event-ordering race: mmWave-triggered refresh can read the fan stamp before `_handle_fan_change` writes it → gate misses | DOCUMENTED (gate comment + `get_fan_last_transition` docstring) — deliberate; D2 sustain-demotion backstops per three-mechanism complementarity |
| B3 | MED | Gate `except Exception` logged at DEBUG — silent no-op invisible to operator (bug class #23 territory) | FIXED — WARNING one-shot per boot (`_fan_gate_error_logged` latch, mirrors `_d2_no_pir_logged`), subsequent DEBUG |
| C1 | MED | Tests exec the delimiter-sliced gate block; a future early-return above it could make it unreachable with tests green | FIXED (guard) — source-scan test rejects unconditional `return` between substrate-gap canary and `_BLOCK_START` |
| A2 | LOW | Bare-except fallback in `_handle_fan_change` stamped `utcnow()` on malformed states | FIXED — no stamp on exception (fail-open on gate) |
| B4 | LOW | `get_fan_last_transition` returned first tracker's stamp (correct-by-coincidence) | FIXED — max across trackers |
| C2 | LOW | `fan_transition_suppressed_count` attr wiring untested | FIXED — source-level wiring test |
| C4 | LOW | Missing boundary coverage: `window+ε`, negative delta | FIXED — two tests pin both edges |
| C5 | LOW | T12 mislabeled "mutation drill" | FIXED — docstring |
| A1 | LOW | Truly-coincident human entry (mmWave-sole) delayed ≤5 s + debounce | ACCEPTED trade (post-B1 fix the debounce clock is preserved, shrinking the cost); noted in README validation table |
| A3 | LOW | `unavailable→on` reconnect counts as a stamping edge | ACCEPTED — rare, defensive direction |

Summary: 1 HIGH, 3 MED, 7 LOW found; 1 HIGH, 3 MED, 5 LOW fixed; 2 LOW accepted with rationale. Verdicts: A SHIP, B FIX-THEN-SHIP, C SHIP.

## Bug classes
- #62 fixture-state authority: NOT hit — tests slice production source between
  mutation-anchor delimiters (import-time assert on delimiter presence);
  reviewer C ran an independent mutation (predicate flip) → targeted red.
- #23 observation-mode gating: B3 was a near-miss (DEBUG-swallowed failure).
- New pattern worth noting: **delimiter-sliced block testing** — strong against
  replica drift, weak on reachability (mitigated by the C1 source-scan guard).

## Orchestrator verification (mandatory)
- Drill 1: neuter `any_sensor_active = False` inside the gate → 4 failed.
- Drill 2: neuter the B1 preservation guard (`if not _fan_gate_suppressed` →
  `if True`) → 1 failed (the preservation test).
- Byte-identical restore verified; final clean run 19/19; PYTHONDONTWRITEBYTECODE
  + __pycache__ purge throughout.

## Suite
Targeted trio 67/67. Full suite 7919 passed / 34 failed = develop baseline,
zero drift (34 incl. 2 order-dependent `test_energy_restart_resilience`
BillingRestoreDaily failures that pass in isolation — pre-existing pollution,
tracked separately).
