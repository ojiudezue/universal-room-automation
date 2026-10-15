# Bathroom-exhaust occupancy+resend: Review A (local correctness)

Branch `feature/bathroom-exhaust` @ 3fb3b3c41, base = merge-base 00fb0bb6e. No HVAC/presence code is touched, so the state-of-play docs were not needed. Cycle tests: 15/15 pass.

## Findings

- **HIGH (stale tests / #62):** 6 tests in `quality/tests/test_bathroom_exhaust_intelligence_cycle.py` FAIL on this branch: the four `test_FIXF_humidity_gate_*` tests (they use the old 2-arg signature), `test_FIXD_coordinator_call_site_*`, and `test_d4_non_wet_room_sleep_off_still_forces_off`. That last one asserts an emit on a fan believed off, so the new transition gate makes it fail as intended. The tests need updating or retiring.
- **HIGH (thread safety):** `_on_humidity_fan_state_change` (automation.py:3336) has no `@callback` decorator, so HA classifies it as an Executor job (`core.py:347-360`). It runs on a worker thread and mutates `_humidity_fan_triggered_time` etc. while the handler may be between awaits. Example: the handler reads `self._humidity_fan_triggered_time` at automation.py:3852 after the thread has set it to None, which raises TypeError. Fix: decorate it with `@callback`.
- **MEDIUM (#53 default split):** the plan (line 199) says dwell defaults to True for wet rooms. The runtime read at automation.py:~3456 uses a default of `False`, and only the config/options flow defaults to `wet_default`. Existing wet rooms get no dwell until someone re-saves their options. This copies the presence-runtime pattern, but it contradicts the plan. Either migrate the setting or document that a re-save is needed.
- **MEDIUM (dwell OFF obligation):** dwell-OFF (automation.py:~3880) needs `_humidity_presence_runtime_until` to be set. Repro: dwell enabled, presence-runtime disabled (a legal config, since the two toggles are independent), no humidity sensor. The fan then runs until the max-runtime cap. It also fails to fire if `_humidity_update_presence_runtime` returns early because no `became` snapshot exists (line ~4015).
- **MEDIUM (cap neutered for dwell):** with humidity None, `_humidity_cap_suppressed` is cleared on the very next tick (automation.py:~3672). Repro: a stuck-ON occupancy sensor in a no-humidity room. The fan runs to the cap, goes off for one tick, then dwell fires again, so it runs indefinitely.
- **LOW:** `or True` dead guard at automation.py:3852. Dwell treats `room_occupied=None` as vacant (`bool(None)`).

## Cleared
- Every humidity reader is None-guarded (spike, suppression, absolute trigger, OFF branch).
- Dwell uses max(last_changed) of ON states across occupancy+motion sensors and skips unknown/unavailable ones. All-unavailable means no fire.
- Re-assert happens only when the fan is believed on, is actually off, and 180 s have passed. The ON side does not re-emit on every tick. The cap and sleep OFF paths are gated.
- Every URA humidity-fan write carries `_humidity_fan_ctx()`, and `homeassistant.turn_*` propagates `service.context`. `on→unavailable` is excluded. Other URA writers skip humidity fans (`actuator_reconciler.py:110`).
- 3fb3b3c41: re-registers listeners when the fan-list tuple changes, and the `async_on_unload` hook is added only once.

**Verdict: FIX-REQUIRED** (both HIGHs, plus the two dwell MEDIUMs).
