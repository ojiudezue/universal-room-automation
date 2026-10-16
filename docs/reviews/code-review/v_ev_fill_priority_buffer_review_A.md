# EV-FILL-PRIORITY-SOC-CHATTER-1: Tier 3 Review A (local correctness)

Branch `feature/ev-fill-priority-buffer` @ `b1d5b878d`. Merge-base verified as `67e5c66e2`.
Scope: `energy_pool.py`, `energy.py`, `energy_const.py` diff (three-dot).

## Verdict: FIX-REQUIRED (1 HIGH)

## Findings

### A-HIGH-1: own off-peak ensure-on clears the latch one tick after the resume (EV and plug)
- **Where:** D2 peer term `_proactive_offpeak_holds` at `energy_pool.py:2830` (EV) and `:4562` (plug), together with the off-peak ensure-on claim at `:1763` (EV) and `:4024` (plug). Ensure-on runs on every `off_peak` tick with no daylight check (`:1399`).
- **Bug class:** #63 (coincidental equality masks a concept split). "Held by a peer" is used to mean "a new session started". `_proactive_offpeak_holds` is URA's own idempotent ensure-on intent, which re-claims every un-held charger on every off-peak tick. It is not a steal.
- **Repro (ran it with a throwaway test, then deleted it):** off_peak, `is_daylight=True` (the summer morning FP window that `fill-priority-daylight-restoration` enabled), forecast healthy, threshold 80. FP at SOC 79 pauses, then FP at SOC 80 resumes and sets the latch. `determine_actions("off_peak")` runs in the same tick and adds the id to `_proactive_offpeak_holds`. On the next FP tick at SOC 79, D2 pops the latch and FP emits `switch.turn_off`. The plug shows the same result through `SmartPlugController.determine_actions`. Both assertions failed: the charger re-paused inside the band.
- **Impact:** the band does nothing in the off_peak-daylight window, and chatter continues there. The observed incident (19:26Z, mid_peak) is still fixed because ensure-on does not claim in mid_peak. INV-1 lists "no intervening D1-D6", so a strict reading is not violated, but the discharge is self-inflicted every tick and the feature's purpose fails in a daily FP window.
- **Fix direction (planner/orchestrator call):** drop `_proactive_offpeak_holds` from both D2 peer sets. That reverses plan ruling B1 F4 for this one peer. A8's per-peer case needs updating, and a test should cover the off_peak-daylight resume → ensure-on → SOC 79 sequence. `_paused_by_dp` can stay as a peer because it is a genuine battery-protection owner.

## Cleared (holds because)
| Check | Evidence |
|---|---|
| Band read at call time | `_energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` is read through the module attribute at `:2799-2802` / `:4541-4544`. The kwarg only overrides it. energy.py passes no kwarg, so the module value is used. |
| Clamp / extremes | `max(0, thr-band)`. A negative band gives floor 85, so every latch is popped while SOC < 85 and the pause fires at SOC < 80, which is legacy behaviour. A band ≥ threshold gives floor 0, so D5 never releases the latch; D1-D4 and D6 still discharge it. The `max(0, ...)` is an equivalent mutant because SOC ≥ 0. |
| 77.0 / 76.9 boundary | Strict `soc < effective_floor`, so 77.0 keeps the latch and 76.9 pops it. D5 runs before the pause gate in the same tick, so 76.9 pauses on that same tick (INV-3). |
| SOC None | D5 is a no-op. `pause_conditions_global` is False and `resume_soc_met` is False, so no producer or pause fires. |
| resume_soc_met discriminator | The latch is set only inside the terminal-resume branch when `resume_soc_met` is true. A forecast-decay resume does not set it. The peer-held path and the untrusted-SOC refusal both `continue` before the set. |
| Latch dict | Keys are EVSE ids (EV) and plug entity ids (plug), the same key spaces as `_paused_by_fill_priority`. Values are monotonic floats used for diagnostics only. RAM-only. |
| D1 inert | Popped before `return` on both EV and plug. |
| D3 force charge | Unconditional pop, outside the FP-membership guard, on both. |
| D4 | EV pops at the head of `release_all_fill_priority`. Plug pops before the `grid_charge_on` early return (`:4105`). |
| Prune | EV `_prune_removed_evses` (`:1255`) and plug `prune_removed_plugs` (`:4182`). The `getattr` guard is harmless. |
| D6 else-branch | `energy.py:6972` binds to the `:6582` `if not self._observation_mode` because no other statement sits at that indent in between. It runs on every observation tick and only clears two dicts: no dispatch, no other state. `_ev` and `_smart_plugs` are always constructed (`energy.py:342-343`). |
| Arbitrage term | The per-id `not in latch` check at `:3226` suppresses the hand-off only for the latched id. The `_fill_priority_would_hold` publisher is unchanged, as the plan requires. |
| Pause gate | The latch changes only `pause_this_tick`. The excess-solar deferral and the would-hold publish still use the global verdict. |

## Builder plan discrepancies
1. Missing else-branch: **accept**. A minimal `else:` is correct.
2. `_plug` vs `_smart_plugs`: **accept**. Code wins.
3. Class names: **accept**.
4. Negative-band table row: **accept**. §5.3.2 verbatim gives behaviour matching the notes. The plan table row should be corrected.
5. A14 restore: **accept**. The latch is RAM-only, so there is no site to neuter.

## Stats
| Sev | Found | Fixed |
|---|---|---|
| HIGH | 1 | 0 (reviewer does not fix) |

Bug class frequency: #63 ×1.
