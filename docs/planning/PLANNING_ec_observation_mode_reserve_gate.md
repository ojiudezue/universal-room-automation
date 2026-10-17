# PLANNING — EC observation-mode gate on the CM TOU-transition path and the write-verify re-send

Card: `EC-OBSERVATION-MODE-RESERVE-BYPASS-1` · Tier 2 (2 code reviews + validator) · Arc: `ARC_energy_coordinator_resilience.md`
Written 2026-10-17 by the overnight pass. Build goes to `review` only; no unattended deploy.

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
do NOT call `_evaluate_battery()` and return no battery actions (DEBUG log once per transition).

**Acceptance criteria**
- **Test:** observation mode ON + TOU transition → `evaluate()` returns `[]`; no CFG ledger stamp; no
  `_record_reserve_dispatch` call; `_tou_transition_count` still increments; `_last_period` consumed.
- **Test:** observation mode OFF → identical actions to develop for the same fixture (golden/equality).
- **Mutation:** removing the D1 gate makes the ON test fail.

### D2 — gate the write-verify re-send
Skip `_pending_watchdog_reserve` while observation mode is on (no anomalies, no NM page, no retry), AND
add a defence-in-depth early return in the re-send chokepoint (`_pending_fire_retry` or
`force_redispatch` — builder picks whichever can read the coordinator's mode without new coupling;
`WriteVerifier` already holds `self._coord`) so any future caller is covered. Do not reset or mutate
pending-episode state while skipped (resume naturally when the mode turns off).

**Acceptance criteria**
- **Test:** observation mode ON + a diverged pending episode past the attempt-1 age → no
  `number.set_value` call, no `pending_write_stuck` anomaly, no NM call.
- **Test:** observation mode OFF → ladder fires exactly as today (existing pending-watchdog tests stay green).
- **Mutation:** removing each gate individually leaves at least one specific test red (the chokepoint
  gate needs its own test that calls the chokepoint directly with mode ON).

### D3 — enumeration note
In the README (attended deploy writes it), a table: each entry of `RESERVE_SET_VALUE_WRITERS` → the
observation gate that covers it (file:line). Any writer not covered is a finding, not silently left.

## Non-goals
- Witness selection / frozen local reading (`EC-SELFHEAL-UNEXPLAINED-RESENDS-1`).
- Who consumes the TOU period (`EC-TOU-TRANSITION-DOUBLE-CONSUME-1`).
- Other coordinators' observation gates.
- No version bump / README / deploy in this pass (overnight → `review` lane).

## Live criteria (for the attended deploy)
- **Live:** with observation mode OFF (normal), the next TOU boundary still produces the usual
  `tou_transition_*` decision and reserve row (byte-identical path).
- Optional, operator-attended only: flip observation mode ON across a quiet minute and confirm no
  `reserve_write` rows with path `evaluate`/redispatch appear; flip back OFF.
