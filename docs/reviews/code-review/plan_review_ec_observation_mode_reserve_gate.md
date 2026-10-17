# Plan review: PLANNING_ec_observation_mode_reserve_gate.md (Tier 2, adversarial)

Reviewed 2026-10-17 against develop @ b6357392f. Verdict: FIX-PLAN (small; all fixes go in the plan text).

## Writer enumeration (re-run independently)

| Writer | file:line | Target | Observation-gated today? | After plan |
|---|---|---|---|---|
| Timer dispatch (`_execute_breaker_safe_dispatch` -> `_execute_service_action`) | energy.py:6609 gate, :7827 call | reserve / CFG / storage-mode select (energy_battery.py:6589) | YES, :6609 | unchanged |
| `_reserve_action`, `_apply_evse_battery_hold` | RESERVE_SET_VALUE_WRITERS | decision-dict builders (no call) | via :6609 / CM path | D1 |
| CM TOU path `evaluate` -> `_evaluate_battery` -> manager `_execute_action` | energy.py:1390-1396, manager.py:1054 | reserve + CFG + select | NO | D1 |
| `force_redispatch` via `_pending_fire_retry` (attempt ladder + cool-off probe) | energy_battery.py:7020; energy_write_verify.py:2186, :2299, :2331 | reserve | NO | D2 |
| Self-heal at energy_write_verify.py:514 | — | schedules a verify check, no write | n/a | cleared |
| `_check` delayed callback (:588/:607) | — | read/compare + anomaly, no write | n/a | cleared |
| Optimizer device/config dispatch | optimization.py:4677, :4826 | reserve hard-denied (:4562, :4717 -> :4528); obs veto :11639 | n/a for reserve | cleared |
| Hazard shed | energy.py:1414 | — | YES | — |
| DP EVSE switch on/off (`_dp_decision_tick` at :6505, before the :6609 gate) -> :5624, :5775, :5922 | EVSE charger switch | NO | not covered (outside INV targets) |
| `_reconcile_dp_excess_on_restore` | energy.py:1813 -> :6085 | EVSE switch | NO | not covered |

## Findings

1. **MEDIUM, scope gap (Bug Class #23).** The drain-precedence EVSE switch writes at energy.py:5624/5775/5922/6085 run under observation mode. `_dp_decision_tick` is called at :6505, before the :6609 gate. They fall outside INV-OBS (it names only reserve, CFG and select), so the plan is internally consistent. But the Problem statement says observation mode means compute-only, and a reader would conclude the energy package is clean after this cycle. **Plan change:** add a Non-goal: "EVSE/drain-precedence switch writes (energy.py:5624, :5775, :5922, :6085) also bypass observation mode. Out of INV-OBS scope; carded as EC-OBS-DP-EVSE-1." Mint the card.
2. **MEDIUM, D2 option.** Pick the chokepoint: **`WriteVerifier._pending_fire_retry`** (energy_write_verify.py:2331). `BatteryStrategy` has no coordinator reference (no `_coord` or observation read in energy_battery.py), so putting the gate in `force_redispatch` needs new coupling. `_pending_fire_retry` covers the attempt ladder and the cool-off probe. **Plan text:** "the chokepoint gate goes in `_pending_fire_retry`, reading `self._coord._observation_mode`".
3. **MEDIUM, OFF to ON to OFF.** Divergence age is wall-clock from `commanded_at` (watchdog ~:2158). If observation mode stays ON longer than the ladder thresholds and then turns OFF, the episode resumes already past attempt 1 and 2. Whether it bursts depends on ordering: the timer dispatch (:6609) runs before `reversion_sweep` (:7154) in the same tick, so it can open a fresh episode, but only if a new `commanded_at` resets attempts. **Plan change:** add a test: "ON for longer than the attempt-2 age, then OFF. The first OFF tick produces no `pending_write_standdown` page and no back-to-back retries; the episode resets from the fresh dispatch's commanded_at." If that fails, the fix is to reset the episode on the ON-to-OFF edge, which is a mutation the plan currently forbids. Decide this before build.
4. **LOW, conduct check.** `_conduct_check_reserve` (:1963) is detect-only. It sends no commands, but it does emit an anomaly and an NM page (`hardware_noncompliance`, :2069/:2090). Under observation mode the hardware still holds the last real commanded floor, so a page is still truthful. Leave it ungated. **Plan change:** state that explicitly in Non-goals, so nobody "fixes" it later.
5. **LOW, D1 side effects.** Skipping `_evaluate_battery` also skips `determine_mode` and the `_evse_battery_hold_active`, `_evse_hold_soc` and `_last_battery_decision` writes (energy.py:7182-7208). That is correct, because the timer tick still recomputes them. **Plan change:** say this, and assert in the ON test that `_last_battery_decision` is unchanged by `evaluate()`. This also confirms check_period_transition consumption is unchanged (EC-TOU-TRANSITION-DOUBLE-CONSUME-1 is preserved, because the plan keeps the :1390 call).
6. **LOW, test anchor.** The D1 OFF golden test must compare the full `ServiceCallAction` list, the `_stamp_cfg_ledger` call and the `_record_reserve_dispatch` kwargs. An action count alone would be a hollow anchor (#62).
7. **LOW, D3.** `RESERVE_SET_VALUE_WRITERS` lists only `number.set_value` writers. CFG `switch.*` and storage-mode `select.select_option` are not in it, so a D3 table built from it cannot prove INV-OBS for two of its three targets. **Plan change:** "D3 also lists switch/select writers found by grep `async_call\|select_option` over domain_coordinators/energy*.py" (use the table above as the seed).

## Cleared
- INV-OBS is falsifiable: mock `hass.services.async_call` and the manager `_execute_action` path.
- Byte-identical OFF is achievable: both gates are pure early-returns.
- No new number, so no knob is needed.
- In-flight race: a CM batch that already returned actions before the flip still executes. The window is one coroutine. Acceptable; note it in Non-goals.

## Must-fix before build
1, 2, 3 (decide the reset-on-edge question), 7.
