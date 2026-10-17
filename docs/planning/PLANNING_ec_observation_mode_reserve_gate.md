# PLANNING — EC observation-mode gate on the CM TOU-transition path and the write-verify re-send

Card: `EC-OBSERVATION-MODE-RESERVE-BYPASS-1` · Tier 2 (2 code reviews + validator) · Arc: `ARC_energy_coordinator_resilience.md`
Written 2026-10-17 by the overnight pass. **Rev 2** after one Tier-2 plan review (FIX-PLAN, 3 MED + 4 LOW, all folded in). **Rev 3** (post code review): D2 episode handling changed from RESET to FREEZE — see D2. Build goes to `review` only; no unattended deploy.

## Problem

Energy observation mode (`switch.ura_energy_coordinator_observation_mode`) means "compute, do not actuate"
(Bug Class #23). Two paths still send reserve / charge-from-grid commands while it is on:

1. **CM TOU-transition path.** `EnergyCoordinator.evaluate()` (`energy.py:1377-1398`) calls
   `_evaluate_battery()` (`energy.py:7177`) on a TOU period change with no observation check. The
   returned actions go to `CoordinatorManager._run_all_evaluations` (`manager.py:984-1007`) →
   `_execute_action` (`manager.py:1035`), which calls `hass.services.async_call` unconditionally.
   `_evaluate_battery` also stamps the CFG intent ledger and writes a DEFERRED `reserve_write` row
   (governor C2) — both describe a dispatch that, under observation mode, must not happen.
2. **Write-verify re-send.** The timer tick runs `WriteVerifier.reversion_sweep()` (`energy.py:~7150`)
   outside any observation gate → `_pending_watchdog_reserve` (`energy_write_verify.py:2118`) →
   `_pending_fire_retry` (`:2331`) → `BatteryStrategy.force_redispatch` (`energy_battery.py:6916`), a
   real `number.set_value`. The watchdog also emits `pending_write_stuck` anomalies + NM pages that
   say "Re-dispatching".

Live: the switch was only ever off/unavailable over the recorder window (10-09..10-17), so this is
latent here. It matters on any home that uses observation mode (multi-home rollout).

## Falsifiable invariant

**INV-OBS:** while `EnergyCoordinator._observation_mode` is True, no code path in the energy package
issues a `hass.services.async_call` that targets the reserve number, the charge-from-grid switch or the
storage-mode select — including actions returned to the CoordinatorManager.

When observation mode is False, behaviour is byte-identical to develop (same actions, same rows, same
ledger stamps, same anomalies/pages).

## Institutional context verified

- **REUSED** the existing gate pattern `if not self._observation_mode:` (`energy.py:6609` timer
  dispatch, `:7103` load-shed, `:1414` hazard handler). No new constant, knob or config field.
- **REUSED** the governor's writer inventory `RESERVE_SET_VALUE_WRITERS` (`energy_const.py:~2320-2335`,
  12 literal writers) as the enumeration surface: the build must state, per writer, which gate covers it.
- Audit read: `docs/reviews/code-review/audit_reserve_surface_ground_truth.md` §3 (CM path not gated) and §5 O-1.
- Related cards: `EC-TOU-TRANSITION-DOUBLE-CONSUME-1` (same `evaluate()` entry point — this cycle must
  NOT change who consumes `check_period_transition`); `EC-SELFHEAL-UNEXPLAINED-RESENDS-1` (false
  re-send ladder on the same `force_redispatch` path — witness fix is separate, operator PICK pending;
  do not touch witness selection here).
- Config-first: not applicable (the missing thing is the gate itself).

## Deliverables

### D1 — gate the CM TOU-transition battery actions
In `evaluate()`, keep `check_period_transition()` + `_tou_transition_count` exactly as today (the period
is still consumed, so the double-consumer behaviour is unchanged), but when `_observation_mode` is True,
do NOT call `_evaluate_battery()` and return no battery actions (DEBUG log once per transition). This also skips `determine_mode` and the updates to `_evse_battery_hold_active`, `_evse_hold_soc` and `_last_battery_decision` (`energy.py:7182-7208`) on this path — correct, because the timer tick recomputes them every cycle.

**Acceptance criteria**
- **Test:** observation mode ON + TOU transition → `evaluate()` returns `[]`; no CFG ledger stamp; no
  `_record_reserve_dispatch` call; `_tou_transition_count` still increments; `_last_period` consumed.
- **Test:** observation mode ON also asserts `_last_battery_decision` is unchanged.
- **Test:** observation mode OFF → identical to develop for the same fixture: compare the FULL `ServiceCallAction` list (service, target, data), the `_stamp_cfg_ledger` call and the `_record_reserve_dispatch` arguments — not a count (hollow-anchor class #62).
- **Mutation:** removing the D1 gate makes the ON test fail.

### D2 — gate the write-verify re-send (rev 3)

> **Rev 3 change (2026-10-17, after code reviews A+B, both SHIP):** while observation mode is on the pending
> episode is FROZEN (skip the watchdog; do NOT reset). The rev-2 reset cleared the stand-down pin and made
> `is_pending_episode_active` False, so after OFF the `_result` leg could re-send a stuck value (Review B
> LOW-B2), `is_reserve_verifiable` could flip True and release the blind-window EVSE guard (LOW-B3), and the
> overlapping write_reverted / self_heal_starvation alarms re-enabled while on (Review A LOW-1). Freezing
> keeps those protections; the existing ladder-spacing gate (≥ attempt-1 age between attempts) still
> prevents back-to-back retries when the mode turns off. The rev-2 text below is superseded on this point.

Two gates, both in `energy_write_verify.py`:
1. In `reversion_sweep` (`:726`), when `self._coord._observation_mode` is True, skip
   `_pending_watchdog_reserve` (no anomalies, no NM page, no retry) AND call
   `self._reset_pending_episode(WRITE_VERIFY_SURFACE_RESERVE)` (`:2108`). **Decision (plan review
   finding 3):** the episode is RESET, not frozen, while the mode is on, so turning the mode off starts a
   fresh ladder: at most one attempt-1 re-send on the first diverged tick, then the existing ≥15-min
   ladder spacing; never an immediate stand-down or back-to-back retries. The conduct check
   (`_conduct_check_reserve`, `:1963`) is NOT gated (see Non-goals).
2. Defence-in-depth chokepoint: an early return (DEBUG log) at the top of `_pending_fire_retry`
   (`:2331`) when `self._coord._observation_mode` is True. This covers the attempt ladder (`:2299`) and
   the cool-off probe (`:2186`). Do NOT gate inside `BatteryStrategy.force_redispatch` — it has no
   coordinator reference and adding one is new coupling (plan review finding 2).
   Read the mode via `getattr(self._coord, "_observation_mode", False)` so test doubles without it keep
   today's behaviour.

**Acceptance criteria**
- **Test:** observation mode ON + a diverged pending episode past the attempt-1 age → no
  `number.set_value` call, no `pending_write_stuck` anomaly, no NM call; episode state reset.
- **Test (mode OFF→ON→OFF):** mode on for longer than the attempt-2 age with divergence standing, then
  off → the first OFF tick fires at most ONE attempt (attempt 1), no `pending_write_standdown`, and the
  next tick inside 15 min fires nothing.
- **Test:** `_pending_fire_retry` called directly with mode ON → no `force_redispatch` call.
- **Test:** observation mode OFF → ladder fires exactly as today (existing pending-watchdog tests stay green).
- **Mutation:** removing each gate individually leaves at least one specific test red.

### D3 — enumeration note
In the README (attended deploy writes it), a table: each entry of `RESERVE_SET_VALUE_WRITERS` PLUS every
switch/select writer found by grepping `async_call|select_option|turn_on|turn_off` across
`domain_coordinators/energy*.py` (the inventory lists only `number.set_value` writers, so it cannot prove
charge-from-grid or storage mode) → the observation gate that covers it (file:line). Any writer not covered
is a finding, not silently left. The plan review's table (`docs/reviews/code-review/plan_review_ec_observation_mode_reserve_gate.md`) is the starting fixture.

## Non-goals
- **Drain-precedence EVSE charger switch writes also bypass observation mode** (`energy.py:5624`, `:5775`,
  `:5922`, restore reconcile `:1813` → `:6085`; `_dp_decision_tick` runs at `:6505`, before the `:6609`
  gate). They are outside INV-OBS (not reserve/CFG/storage-mode) and are carded separately as
  `EC-OBS-DP-EVSE-1`. After this cycle the energy package is NOT fully observation-clean.
- **The reserve conduct check stays ungated on purpose** (`_conduct_check_reserve`, `:1963`; anomaly +
  page at `:2069/:2090`). It sends no commands, and the hardware still holds the last real floor, so its
  page stays truthful in observation mode. Do not "fix" it.
- **In-flight race accepted:** a manager batch whose actions were already returned when the mode flips
  still executes (one-coroutine window).
- Witness selection / frozen local reading (`EC-SELFHEAL-UNEXPLAINED-RESENDS-1`).
- Who consumes the TOU period (`EC-TOU-TRANSITION-DOUBLE-CONSUME-1`).
- Other coordinators' observation gates.
- No version bump / README / deploy in this pass (overnight → `review` lane).

## Live criteria (for the attended deploy)
- **Live:** with observation mode OFF (normal), the next TOU boundary still produces the usual
  `tou_transition_*` decision and reserve row (byte-identical path).
- Optional, operator-attended only: flip observation mode ON across a quiet minute and confirm no
  `reserve_write` rows with path `evaluate`/redispatch appear; flip back OFF.
