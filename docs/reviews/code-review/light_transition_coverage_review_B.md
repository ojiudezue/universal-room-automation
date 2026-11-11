# LIGHT-TRANSITION-COVERAGE-1 — Review B (reconciler / lifecycle / cross-path)

Commit reviewed: `dfc4268c` on `fix/light-transition-coverage`, base `origin/develop` (three-dot).
Verdict: **SHIP** (no CRITICAL/HIGH/MEDIUM; one LOW pre-existing residual widened).

## Questions and answers

| Concern | Result | Evidence |
|---|---|---|
| Reconcile loop / flap from mid-fade reads | Holds | The reconciler only triggers on an `unavailable -> available` edge (`actuator_reconciler.py:461-466`) and the periodic re-check at `:1208`. Brightness/attribute updates during a fade are not edges. The no-op gate compares on/off state only (`:646`). A 3 s off-fade that still reads `on` produces no new edge, so no re-dispatch. |
| No-op gate disturbed | Holds | `transition` is added to the payload at dispatch (`:701-707`), not to `desired.params`, so `has_params_to_apply` is unchanged. Night lights also get it at dispatch (domain `light`), which is correct, and `_nl_params(include_transition=False)` keeps a basic night light from being re-sent every pass. |
| Our own fade mis-booked as a manual change | Holds at defaults | Writes go through `_safe_service_call` with the URA context (`automation.py:961-969`, reconciler `:733-745`). HA keeps that context on the entity's state writes for 5 s (`homeassistant/helpers/entity.py:82`), and `_note_manual_light_change` skips URA contexts (`actuator_reconciler.py:514-517`). Defaults are 1 s on and 3 s off, both under 5 s. |
| LightPolicyOracle / manual holds | Holds | Hold checks run before dispatch (`actuator_reconciler.py:673-682`). The new turn_off sites keep their existing `light_hold_allowed` filtering (shared-space `automation.py:~4677`). The transition does not change which entities are allowed. |
| Exit fade racing an entry | Holds | Only the order of commands matters: a turn_on sent mid-fade supersedes the off-transition on the device. Entry/exit already carried transitions before this diff (`automation.py:1606, 1711, 1843, 1894, 2022`). The new sites (away leave-on sweep `:922`, shared-space failsafe `:4694`) run on vacant/Away rooms where no ON hold is booked. |
| Devices that reject `transition` | Holds | HA strips `transition` when the entity lacks `LightEntityFeature.TRANSITION` (`components/light/__init__.py:361-362, 375-376`). `switch.*` is never given it (domain-split at every site). Light-domain fans are excluded in the reconciler (`_is_fan`, `:704`). |
| Restored / unavailable entities | Holds | `_reconcile_one` skips unavailable/unknown (`:640-643`) before the dispatch line. |
| Lifecycle | N/A | No new tasks, timers or listeners. |

## Findings

**LOW B-1 — pre-existing 5 s context residual now applies to more sites (bug class: echo-context window, Slice C known residual).**
The fade knobs allow up to 10 s (`config_flow.py:3003-3008`). Some devices report the final on/off state only when the transition finishes. If that report arrives more than 5 s after the call, it carries a new context and is booked as a person's change when the room is occupied.
Repro: `light_transition_seconds_off = 8`, room occupied, house goes to sleep. The reconciler dispatches `turn_off` with `transition: 8` to a non-night light. The device reports `off` at about 8 s with a new context, which books a manual OFF cooldown. URA then cannot turn that light ON again until the cooldown ends.
The same residual already applied to entry/exit before this diff, and the defaults do not trigger it. Possible fix: card it with the existing Slice C residual, or cap the dispatch transition below `CONTEXT_RECENT_TIME_SECONDS`. Not a blocker.

## Tests run
`test_light_transition_coverage.py`, `test_reconcile_on_return.py`, `test_reconciler_fan_manual_on_guards.py`, `test_nightlight_red_reconcile_parity.py`, `test_fan_transition_gate.py`, `test_v4519_transition_detector_teardown.py`, `test_v460_score_on_transition.py`, `test_v4_6_8_rate_reconciliation.py`: 111 passed.

## Summary
| Sev | Found | Fixed | Deferred |
|---|---|---|---|
| CRIT/HIGH/MED | 0 | 0 | 0 |
| LOW | 1 | 0 | 1 (pre-existing class) |
