# v5.103.105 — Config-flow timing logs: DEBUG by default, WARNING only for slow steps

**Card:** CONFIG-FLOW-SLOW-ONBOARDING-1 (follow-up). **Tier:** 1 (hotfix, diagnostic logging only).

## Why
`docs/planning/AUDIT_config_flow_performance.md` (profiling section) measured every config/options
step rendering in under 20 ms live. The timing shim in `_cflow_timing.py` still logged ENTER and EXIT
at WARNING for every step, which made it log noise with no signal.

## Change
- `custom_components/universal_room_automation/_cflow_timing.py`
  - ENTER / EXIT lines and the one-shot "instrumented" line are now DEBUG.
  - New module constant `CFLOW_SLOW_MS: Final = 250` (knob rung 1, module constant: it is a
    diagnostic threshold, so changing it should go through review). `0` or negative means warn on every step.
  - On exit, ONE WARNING `CFLOW-TIMING: SLOW <class>.<step> elapsed_ms=… threshold_ms=…
    autodetect_calls=… autodetect_ms=…`, only when `elapsed_ms > CFLOW_SLOW_MS`.
  - Unchanged: the `CONFIG_FLOW_TIMING` master gate, the `_cflow_timing_silent` shim, and the autodetect
    helper wrappers (they never logged). Overhead is still only monotonic() calls.
- To see per-step timing again, set `custom_components.universal_room_automation._cflow_timing: debug`
  under `logger:`.

## Tests
`quality/tests/test_cflow_timing_instrumentation.py` covers these cases:
- A fast step logs at DEBUG only, with no WARNING.
- The boundary at 249 / 250 / 251 ms: only a strictly greater value warns.
- A slow step logs exactly one WARNING with all the fields.
- `CFLOW_SLOW_MS=0` warns on every step, including a 0 ms one.
- The silent shim logs nothing.

Each mutation turned a named test red: `>` to `>=`, dropping the `<= 0` conjunct, always-warn, and ENTER/EXIT back to WARNING.

## Live validation (prospective)
- **Live:** open a room options flow and click through a few steps. The HA log should show no
  `CFLOW-TIMING` WARNING lines for those (fast) steps.
- **Live:** with the logger set to debug for `_cflow_timing`, ENTER/EXIT lines appear at DEBUG.
