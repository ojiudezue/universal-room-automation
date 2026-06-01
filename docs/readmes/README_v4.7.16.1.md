# v4.7.16.1 — Emergency Bug Class #34 Fix

**Production-blocking hotfix.** Single-file, ~3 LoC.

## What broke

v4.7.15.1's D6 (HVAC consensus defer gate, shipped earlier in this session) added a new code path inside `_apply_house_state_presets` at `hvac.py:806`:

```python
if self._defer_gate_enabled:
    manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
```

That function already had a function-local `from ..const import DOMAIN` at line 1065 (introduced in v3.23.0 for activity logging). Per Python scoping rules, the local import makes `DOMAIN` function-local for the **entire** function body — so the reference at line 806 (which precedes line 1065) raises `UnboundLocalError` at runtime.

The defer gate switch defaults ON. Every HVAC decision cycle (`_async_decision_cycle` at line 658 → `_run_decision_cycle` at line 713 → `_apply_house_state_presets` at line 781) hit the new branch and crashed.

## Evidence

HA core error log captured after v4.7.16 deploy:

```
File "/config/.../hvac.py", line 658, in _async_decision_cycle
File "/config/.../hvac.py", line 713, in _run_decision_cycle
    await self._apply_house_state_presets()
File "/config/.../hvac.py", line 806, in _apply_house_state_presets
```

Stack traceback repeating on every tick.

## Bug class

**Bug Class #34 — Function-local import shadows module-level import.** The repo has a long-standing test guard at `quality/tests/test_v4511_ac_energy_aware_ramp_down.py::TestNoLocalImportShadowsModuleImport::test_no_function_local_imports_shadow_module_imports` that catches this exact pattern. It was already flagging the v4.7.15.1 regression when I ran cycle tests during hotfix development.

There is a sibling fix at `hvac.py:509-513` (v4.5.11.2) that documents the same hazard for `async_setup`. v4.7.15.1's D6 didn't get the same caution applied.

## Fix

Delete the redundant `from ..const import DOMAIN` at line 1065. `DOMAIN` is already imported at module level on line 27, so the local import added nothing — it only created the scoping trap that activated when v4.7.15.1 added a new reference earlier in the function.

```diff
                 # Activity log: HVAC preset change
-                from ..const import DOMAIN
                 activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
```

Comment added at the deletion site documenting why this is module-level and not local, to prevent regression.

## Sibling sites NOT touched

- **`hvac.py:1153`** (`_async_apply_preset_overrides`): uses alias `from ..const import DOMAIN as _DOMAIN_KEY` — does not shadow `DOMAIN` itself. Safe.
- **`hvac.py:1615`** (`_handle_person_arriving`): local `from ..const import DOMAIN` is the **only** reference in that function — no earlier shadowing. Safe.

## Test plan

- `pytest quality/tests/test_v4511_ac_energy_aware_ramp_down.py` — Bug Class #34 regression guard passes
- Post-deploy live: error log shows no further `_apply_house_state_presets` tracebacks; HVAC zone presets actually apply on state transitions

## Rollback

```bash
git revert <merge-commit>
```

Or HACS install v4.7.16 (but production was broken there too — this hotfix is the only working path forward without disabling the defer gate via `switch.ura_hvac_coordinator_hvac_consensus_defer_gate → off`).

## Tier

1 (hotfix). One file, ~3 LoC, no DB/config-flow/entity surface change.
