# Plan review: PLANNING_ev_fill_priority_soc_buffer.md (EV-FILL-PRIORITY-SOC-CHATTER-1)

- Reviewer: ura-reviewer (adversarial plan review, Tier 2-DB, one pass before build)
- Base: develop @ f7e6dd922, plan plus the "Orchestrator rulings" section
- Code read: `energy_pool.py` 2668-2921 (EV FP), 3120-3165 (arbitrage hand-off), 3491-3540 (EV release_all), 4018-4060 (plug release_all), 4384-4562 (plug FP); `energy.py` 6776-6845, 6942-6970 (call sites)
- HVAC/presence docs not applicable (energy-only change)

## Verdict: FIX-REQUIRED (plan edits only; the design direction, option A, is sound)

## Findings

1. **HIGH — No day-boundary or inert discharge, so a stale latch suppresses the next day's first pause (suppression without discharge, day-boundary-blind).**
   §5.3 lists four clear sites. The inert branch (`energy_pool.py:2760-2766`, plug `:4441-4446`) is not one of them. Peak and off_peak-night run every day, and Q2 dropped the TTL, so nothing time-anchored clears the latch.
   Repro: fill_priority_soc=80. The EV resumes at SOC 80 at 13:00 and the latch is set. Battery ends the day at 90+, overnight arbitrage grid-charges to 100, and SOC is 79 at 08:00 in daylight off_peak. The EV is ON (it charged overnight), so the latch says re-pause and the gate requires SOC < 77. The EV drains the home battery from 79 to 77 with no pause. Under the legacy code a pause fires at 79. That is INV-2 broken in spirit: this is the first pause of a new fill window, not chatter.
   Fix: clear the latch for every id in the inert branch (EV and plug), and say so explicitly. The orchestrator's Q2 ruling ("already has a discharge") is wrong without this site.

2. **HIGH — The named cross-owner-steal clear site is unreachable in the latched state.**
   §5.3 cites `:2871-2888`. That block sits under `elif evse_id in self._paused_by_fill_priority` (`:2865`). The latch exists only after the terminal discard at `:2916`, so a latched EVSE is never in the FP set and that branch never executes for it. Drain, arbitrage, load_shed, grid_cap, and blind_window pause through their own sets, which FP never observes.
   A8 ("drain takes over during latch → fresh FP pause at 78 after drain releases") will fail, or the builder will invent an ad-hoc site.
   Fix: specify a per-EVSE check at the top of the FP loop: if the id is latched and in any peer set (`_paused_by_grid_cap/_battery_drain/_us/_arbitrage/_load_shed/_blind_window`; plug: `_us/_battery_drain/_load_shed`), clear the latch. Alternatively, rule that a steal does not clear it.

3. **MEDIUM — The force-charge clear is placed inside a membership check.**
   `:2785-2793` and `:4458-4466` only act `if evse_id in self._paused_by_fill_priority`, and a latched EVSE is never in the set. The clear must be unconditional in the force_charge branch. A7 is also self-contradictory: "SOC=79 tick pauses immediately once force-charge clears below floor", but 79 is not below the floor of 77. Restate A7 as: force-charge on, then off at SOC 79 → pause fires at 79.

4. **MEDIUM — The latch is set on a forecast_decayed resume, not only on an SOC resume.**
   The terminal resume at `:2916`/`:4558` covers both `resume_soc_met` and `forecast_decayed`. The chatter mechanism is SOC-only, and the forecast side already has its own band (`safety_margin_kwh`, `:2726-2731`).
   Repro: SOC 78, forecast decays → resume and latch set. The forecast recovers to healthy with SOC still 78. Legacy behavior is to re-pause. Under the plan the EV draws the battery to 77 first.
   Fix: set the latch only when `resume_soc_met`. A10 should cover this case.

5. **MEDIUM — `_fill_priority_would_hold` (`:2776`) stays global and latch-blind, which contradicts the latch on the arbitrage hand-off path.**
   At SOC 78 with a latched EVSE, `would_hold=True`. The arbitrage release (`:3150-3160`) then adds the charger to the FP set and leaves it OFF until 80. Is that a re-pause inside the band (INV-1 says no membership transition) or a legitimate first claim? The plan must rule on this:
   - either make would_hold per-EVSE (latched → False for that id),
   - or exempt the hand-off and clear the latch there.

   Also add the hand-off to the §8 producer list. The plan omits that `:3156` and `:3525` are FP-set writers outside FP.

6. **MEDIUM — The SOC-below-floor clear has no specified location.**
   It must be evaluated for every latched id regardless of `is_on`, the excess-solar deferral (`:2836`), or untrusted-SOC refusal. Otherwise an EVSE that is OFF (car full or unplugged) while SOC dips below 77 stays latched. With SOC `None` (`pause_conditions_global` False) the latch should be left untouched. State that explicitly.

7. **MEDIUM — The live acceptance criteria are not discriminating.**
   L1 and L3 ("zero re-pause rows", "tripwire=0") are satisfied equally by the fix and by a regression that suppresses all pauses, or by a day with no charging. Add a positive control: on the same day, ≥1 `fill_priority_pause` row for a first pause below 80 (L2, made mandatory) and/or a re-pause row only at SOC < 77. Otherwise report "not exercised" rather than PASS.

8. **LOW — "Same latch" for the plug path is ambiguous.**
   `PlugPool` is a separate class with its own `_paused_by_fill_priority` (`:3634`). Specify a per-instance dict initialized in each `__init__` (`:585` and `:3634` siblings). The grid_charge_on held-resume (`:4529-4535` `continue`) correctly sets no latch; keep A6 asserting that.

9. **LOW — A4 monkeypatch hygiene.**
   If `energy_pool` does `from .energy_const import DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT`, patching `energy_const` is a no-op. The test must patch `energy_pool.<name>`, or this becomes a hollow anchor (#62). A cleaner option is to pass the band as a kwarg with the constant as default, matching `safety_margin_kwh`.

10. **LOW — Clamp wording.**
    The ruling `effective = min(band, soc_threshold)` gives floor ≥ 0. Fine, and §7's "clamp to 0" matches. Also clamp a negative band (`max(0, …)`), since the unit test only guards the constant, not a future kwarg.

## Cleared

- **Band=0 byte-identical:** holds. The floor becomes `soc_threshold`, so the gate equals the legacy `soc < soc_threshold`. The latch writes are dict-only side state.
- **Restart/reload:** the RAM-only latch matches the RAM-only FP set (`:585`). Losing it on reload yields at most one pause, which is acceptable (§5.4).
- **Resume edge unchanged (`:2773`):** confirmed. No EV can stay paused above 80 because of this change; the latch only gates pause, never resume. INV-1/2/3 are falsifiable once findings 1, 2, 4 and 6 are fixed.
- **release_all_fill_priority as a clear site:** reachable, since it is called when the excess-solar toggle is off (`energy.py:6842`, `:6968`). Note that when the toggle is off, FP is not called at all, so clearing there is required. Correct.
- **Knob rung 1 (module constant, 0 = kill switch):** justified.
- **Tests fail on develop:** A1, A3 and A7 assert behavior absent today (`:2770` has no band), so they will fail RED on develop. A2 and A5 are regression guards (green on develop by design, which is fine).

## Must-fix before build

Findings 1, 2, 3, 4, 5, 6, 7. 8-10 are recommended.
