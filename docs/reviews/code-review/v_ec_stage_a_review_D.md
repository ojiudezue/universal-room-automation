# EC Stage A — Tier-3 Review D (adversarial completeness, diff-blind)

Branch `feature/ec-stage-a`, base develop `f2ec3cb38`. Plan Rev 3.3 Stage A, INV-1 / INV-2 / INV-4.

**Verdict: FIX-REQUIRED** (one HIGH: INV-1 leak through the attain HOLD-CURRENT returns, reproduced in code).

## Invariants, falsifiable form

- **INV-1:** after any `determine_mode` call that registers `_tick_reserve_floor = F`, no reserve `number.set_value` with value < F leaves the tick (decision, EVSE overlay update-in-place or append, `force_redispatch`), and `_last_reserve_level_desired >= F`. Only `_reserve_action` writes `_last_reserve_level_desired`.
- **INV-2:** a fully blind tick emits at most one decision-side reserve write, never `switch.turn_on` / `select.select_option`, never refreshes `_desired_stamped_at`, and a blind raise is undone on the first `allow_discharge` blind tick.
- **INV-4:** `is_top_rate(now)` iff the active period's rate is the season's highest distinct rate and the season has at least 2 distinct rates.

## Surface re-enumerated (whole package, not the diff)

| Writer / path | file:line | Verdict |
|---|---|---|
| `_reserve_action` (sole writer of the stamp) | energy_battery.py:6403-6486, stamp :6437 | PASS. grep: `_last_reserve_level_desired =` occurs only at :6437 (plus init :448) |
| `_result` reserve block | :6567 | PASS. Routes through `_reserve_action` |
| 19 `_result(` calls | AST scan | PASS. 18 pass an int `reserve_level`; :5845 (grid disconnect) passes none, but it runs before any floor is registered, so INV-1 is vacuous there |
| **Attain HOLD-CURRENT returns** (`_get_attainability_hold_current_decision`, `actions: []`, no `_result`) | :4808-4850, reached from :5003 (cfg-unavailable defer) and :5342 (rate-window warm-up) | **LEAK (HIGH-1)** |
| Blind branch rules | :5680-5725 | PASS. de-escalate / hold / release are exclusive `elif` branches, so there is one `_reserve_action` call |
| EVSE overlay update-in-place | energy.py:5397-5466 | PASS. `max(existing, hold, dp)` and `existing` was folded upstream |
| EVSE overlay append | energy.py:5468-5560 | Inherits the stamp. It falls back to the ledger `_last_reserve_level` when the stamp is None, and that fallback is the vector for HIGH-1 |
| `force_redispatch` | energy_battery.py:6930-7010; `_effective_reserve_desired` energy_write_verify.py:1707 | PASS. max() over the stamp, EVSE, partial floor and DP. The I-D3 600 s gate is kept (`_desired_stamped_at =` only at :6730, inside `_result`) |
| Other `number` writers | `RESERVE_SET_VALUE_WRITERS` energy_const.py:2328 + AST lint over `rglob` | PASS. Pool, EVSE amps and radar are not reserve writers. config_flow.py:12819 only schedules the radar sender |
| CFG under blind | blind branch only appends `switch.turn_off` | PASS |
| INV-4 `is_top_period` / `is_top_rate` | energy_tou.py (diff) | PASS. Distinct-rate set, len ≥ 2, rank == max. `_is_top_rate_edge` falls back to the period name when there is no engine or it raises |

## Findings

### HIGH-1 — INV-1 leak: attain HOLD-CURRENT under a registered partial floor (Bug Class #53, one missed site)
`energy_battery.py:4808-4850` returns `actions: []` without calling `_result`, so `_reserve_action` is never reached and the stamp is not refreshed to ≥ F. The EVSE overlay append (energy.py:5487-5539) then composes `max(evse_hold_soc, stamp-or-ledger, dp)`, which can be below F. The plan's §5 enumeration (line 174) lists the 19 `_result` calls and misses these two returns.

**Legal-config repro (run in-harness and confirmed RED, scratch test since deleted):** a real `BatteryStrategy` and `EnergyCoordinator` via `shell(blind=False, cfg="unavailable", hw="40", reserve_soc=20)` (the CFG cloud leg not yet loaded at HA boot), `_arbitrage_enabled=True`, `_attain_reboot_recovered=False`, stamp None, KV ledger `_last_reserve_level=40`. Tick at 03:00 Oct off_peak with `partial_hold` floor 50. Result: reason `post-reboot HOLD CURRENT`, `_tick_reserve_floor=50`, stamp None. Then `_evse_battery_hold_active=True, _evse_hold_soc=35` → `_apply_evse_battery_hold` emits **`set_value 40`**. The governor row would be `value=40, tick_floor=50`, which is exactly the INV-1 live falsifier. The summer mid_peak attain call (:5991) reaches the same returns.

The defer path repeats every tick while the CFG write leg stays unavailable (the latch is not consumed, :4993-5006). For as long as the Enphase cloud leg is down after boot, the partial floor is not applied to hardware at all, even with no EVSE hold. Partial floor is the only hold depth affected (full_hold returns before attain).

**Fix (small):** in `_get_attainability_hold_current_decision`, when `self._tick_reserve_floor is not None`, route the floor through `_reserve_action(self._tick_reserve_floor)`. That folds and stamps it, and appending the action, which can only raise, does not unwind an in-flight charge. The minimum fix is to stamp via `_reserve_action` and drop the action, but that leaves the hardware below the floor. Add the two returns to the plan §5 list. Add a mutation-anchored test using the repro above.

### LOW-1 — Q6 override leaves the stamp stale under a floor (dormant)
`energy_battery.py:5655-5662, 5696`: with `BLIND_RESPECT_MANUAL_LOWER=True`, a held blind tick skips `_reserve_action`, so INV-1(ii) and the INV-2(d) release both stop holding by design. The constant is False (rung 1, energy_const.py:675). Record this in the plan as a stated exception for when the switch is flipped.

## Adjudications

1. **Review B LOW-2 (release restores a pre-raise value below `reserve_soc`): not a regression.** `_blind_pre_raise` is the pre-write base: URA's own stamped desire, else the hardware write leg (:5650-5651, :5722-5724). Pre-Stage-A blind never wrote except on de-escalation, so the hardware stayed at exactly that base. The release returns the hardware to the state the old code would have left it in. "Never wrote below reserve_soc" held before only because the old code never wrote at all. One edge case: if the base came from a stamp lower than the hardware (EVSE overlay raised the hardware above the stamp), the release writes the lower stamp. The overlay runs on blind ticks too and re-raises it to `max(stamp, hold_soc)` while the EVSE hold is active. Once the hold ends, the stamp is the correct desire. No change needed; optionally add a one-line note to plan §12.
2. **Review A LOW-1 (Q6 false-fire on cloud write-leg lag): real but dormant.** The conjunct `_wl < _desired and _last_reserve_level != _wl` fires when URA dispatched X, `_last_reserve_level` was stamped to X, and the cloud leg still reads the old value. That is ordinary cloud lag, not an operator action. Harmless while the constant is False. The conjunct must be fixed before the switch is flipped (for example, require `_wl` to differ from every value URA dispatched this episode, or require the condition to persist for two ticks). Card it with the Q6 knob.

## Checklist
| Invariant | Result |
|---|---|
| INV-1 (i) every `_reserve_action` output ≥ F | PASS |
| INV-1 (ii) stamp ≥ F after a holding tick | **LEAK** (HIGH-1; LOW-1 dormant) |
| INV-1 (iii) overlay / redispatch ≥ F | **LEAK** via HIGH-1 (overlay append); redispatch PASS |
| INV-1 sole stamp writer | PASS |
| INV-2 (a) one reserve write, no turn_on/select/stamp refresh | PASS |
| INV-2 (b) overlay append re-send ≥ F | PASS on blind ticks (the stamp is refreshed every held blind tick) |
| INV-2 (c) redispatch ≤ 600 s | PASS (gate unchanged) |
| INV-2 (d) release | PASS (restart loses it: documented known limit 8; Q6 dormant exception) |
| INV-4 | PASS |

**Must-fix:** HIGH-1.

Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
