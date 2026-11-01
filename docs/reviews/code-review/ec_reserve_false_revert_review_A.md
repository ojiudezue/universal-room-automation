# EC reserve false-revert fix-up: Review A (local correctness)

Branch `fix/ec-reserve-false-revert` @ 80b755e45, base 8e2e9b7b7 (merge-base verified).
Scope: `_witness_memory_step` / `_witness_confirmed_for` (energy_write_verify.py:617-695), gate (1303-1313), diag attrs (2900-2911), kill switch (energy_const.py:590).
Targeted suite: `test_ec_reserve_false_revert_fixup.py` 33 passed.

## Truth table: gate `_witness_confirmed_for` (all other D3 conditions held)

| switch | mem | mem.value==C, first_at>=T_c | sweep witness for (C,T_c) | reason | cloud raw==V | result |
|---|---|---|---|---|---|---|
| off | any | any | any | any | any | False (pages, pre-fix-up) |
| on | None | - | - | - | - | False |
| on | set | no (new value or re-send T_c>first_at) | - | - | - | False |
| on | set | yes | no / None | - | - | False |
| on | set | yes | yes | local / low_soc_guard / error / unresolved / fallback_only / soc_unknown_high | - | False (live local path decides) |
| on | set | yes | yes | unavailable | no | False (pages: cloud moved) |
| on | set | yes | yes | unavailable | yes | True (CLOUD_STALE) |

Step: trusted and |local-C| < 2 stamps (fresh V when no mem / value differs / mem older than T_c, else bumps last_at); trusted and >= 2 clears; untrusted no-op; ledger None clears. Deadband is strict `<`, matching `_local_confirms` (606-608).

## Findings

- **No CRITICAL / HIGH / MEDIUM.**
- **LOW-1** energy_write_verify.py:649-656. Cloud raw non-numeric: `float(raw)` raises and is swallowed, so no stamp. Fail-closed, correct. A stale prior-ledger memory survives, but the gate filters it on value / first_at (685). No action.
- **LOW-2** energy_write_verify.py:626-628. With the kill switch off, the step returns before resetting `_sweep_witness`, so the cache can go stale. Harmless because the gate checks the switch first (677). Cosmetic. Optional: reset before the switch check.
- **Info: types.** Restored `_last_reserve_level_at` is a tz-aware datetime or None (energy.py:2096-2107). A None T_c clears the memory. A non-datetime T_c fails the gate's isinstance check (683) and raises in the step's `<` (swallowed). Restored `commanded` may be str or int; both sides use `float()`, so equality is consistent. C vs V: both come from `float()` of the same oracle entity's raw string ("10" == "10.0" → 10.0), so units cancel.
- **Info: residual R2 (plan section 10).** Say cloud had V, caught up to C, then something reverted it back to V while the Envoy was down. The gate says CLOUD_STALE until the Envoy returns. The plan states and accepts this. It is not a new leak.
- Diag attrs are display-only. They are None when unset, and the datetimes are ISO strings (2900-2911).

## Verdict: **SHIP**. Nothing must be fixed. LOW-2 is an optional tidy-up.

Bug classes checked: #53 (gate and step share one cached read, so nothing is computed and then dropped), None handling, type coercion, kill-switch gating.
