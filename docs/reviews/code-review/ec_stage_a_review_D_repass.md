# EC Stage A — Review D re-pass (adversarial completeness), fix-up ed8aead06

Branch `feature/ec-stage-a` @ 6357dc2d4. Scope: D-HIGH-1 fix (`_get_attainability_hold_current_decision`), INV-1 / INV-2 re-enumeration.

## Re-enumeration (grep, not the builder's list)

determine_mode (energy_battery.py:5489) — entry-reset `_tick_reserve_floor = None` at :5542, before any return. Returns:
- :5776 blind dict — floor registered :5657, all reserve writes via `_reserve_action` (:5714).
- :5865 grid-disconnect `_result` — before floor registration (F = None, INV-1 vacuous).
- :5908/:5943/:5944/:5955/:5971/:5978/:6047/:6067/:6082/:6199/:6335/:6363 — `_result`.
- :6023/:6250 `attain_result` from `_run_attain_branch` (:5075) → `_result`-backed helpers, or `_get_attainability_hold_current_decision` (:4860 dict) via :5023 (defer) and :5362 (warm-up), or `_get_attainability_hold_decision` → `_result`.
- :6157 hold decision, :6221 `_get_arbitrage_decision` (:3913) — only `_result` returns (awk sweep of :3913–:5488: the only non-`_result` dict return is :4860).

Builder claim confirmed: dict returns are exactly :5776 and :4860.

Reserve `number.set_value` sites in package: energy_battery.py:6502 (`_reserve_action`, sole stamper of `_last_reserve_level_desired`, :6457), :7009 (`force_redispatch`, desire from `_effective_reserve_desired` = max(stamp, holds), energy_write_verify.py:1707); energy.py:5536 (EVSE append, clamps to stamp else ledger) and in-place raise above it (max only); energy.py:8781/:8805 and energy_pool.py:411/:429/:4964 unchanged since the first pass (not reserve-floor-relevant / raise-only, as cleared there).

## D-HIGH-1 verification

Original repro (sighted, CFG unavailable, latch unconsumed, stamp None, ledger 40, hw 40, partial floor 50, EVSE hold 40): hold-current now calls `_reserve_action(max(50, 40)=50)` (energy_battery.py:4850–4860) → stamp 50, action set_value 50; EVSE overlay updates in place with max ≥ 50. Pinned by `test_hold_current_defer_applies_partial_floor_and_overlay`. CLOSED.

Extremes:
| Case | Result |
|---|---|
| live reserve 80 > F 50 | level 80, deadband → no action, stamp 80. Holds (`test_hold_current_never_lowers_inflight_charge_reserve`) |
| repeated defer | entry-reset + re-register each tick; deadband idempotent. Holds (`..._repeats_each_tick_without_lowering`) |
| warm-up caller (:5362) | same helper. Holds (`test_hold_current_warmup_path_applies_partial_floor`) |
| floor > target | n/a on this path (no target); fold is max |
| no floor | zero actions, stamp untouched → INV-2 byte-identical (golden |hc cases + `test_hold_current_no_floor_zero_actions`) |
| force_redispatch after hold-current | desire = max(stamp ≥ F, holds) ≥ F. Holds |
| unreadable reserve | writes F; INV-1 holds, but see D-MED-1 |

## Findings

**D-MED-1 (MEDIUM, Bug class: hand-rolled second path / lost fallback) — energy_battery.py:4851–4856.** When the write-leg reserve is unreadable, hold-current requests bare `F` with `compare_to=None`, ignoring the KV-restored ledger `_last_reserve_level` that the EVSE overlay deliberately falls back to (energy.py:~5490, v5.17.3 D-MED-1). Repro: restart mid-ATTAIN, cloud reserve number `unknown` before first poll (write role is cloud-first), CFG `unavailable`, ledger 80 (in-flight charge), partial floor 50, EVSE hold 45 → action set_value 50 (lowers in-flight 80 → 50, the unwind hold-current exists to prevent) and stamp 50, so the EVSE append clamps to 50 instead of 80 (pre-fix 80). Also no deadband (`current_reserve is None`) → re-dispatch of 50 every tick while unreadable. INV-1 is NOT broken (all writes ≥ F); the raise-only promise in the comment is. Fix: base = hw if readable else `_last_reserve_level_desired` else `_last_reserve_level`; level = max(F, base); pass `compare_to=base` when hw is None (mirrors blind branch :5707–5709). Add a test for this case (none exists).

**Clear — unrefreshed `_desired_stamped_at` on hold-current.** The sweep reads a stale stamp → stands down (no self-heal re-dispatch). That can only suppress a write, never emit one below F; no flap. Matches the blind-path v5.17.5 I-D3 convention.

## Tests
`quality/tests/test_ec_stage_a_*.py` (4 files): 289 passed (.venv-ha, PYTHONPATH=quality, no bytecode).

## Invariant checklist
- INV-1 (no reserve write < F; stamp ≥ F): PASS across all enumerated paths.
- INV-2 (no floor ⇒ pre-Stage-A behaviour): PASS.
- Raise-only on hold-current (fix-up's own claim): LEAK when reserve unreadable (D-MED-1).

## Verdict
**SHIP** on INV-1/INV-2. D-MED-1 is a MEDIUM to fix in-cycle (small, ~6 LoC + one test) per fix-LOWs/MEDs policy; it is not ship-blocking for the stated invariant.
