# v4.5.11.2 — Fix UnboundLocalError on HVAC coord setup

**Date:** 2026-05-10
**Type:** Tier 1 hotfix (1-line deletion + 7 regression tests)
**Predecessor:** v4.5.11.1
**Reproducer:** Confirmed in HA core log from 2026-05-10 19:39:53.974:

```
ERROR ... Failed to start coordinator hvac
  File "domain_coordinators/manager.py", line 240, in async_start
    await coordinator.async_setup()
  File "domain_coordinators/hvac.py", line 356, in async_setup
    for ce in self.hass.config_entries.async_entries(DOMAIN):
UnboundLocalError: cannot access local variable 'DOMAIN'
    where it is not associated with a value
```

## Summary

v4.5.11 added inside `HVACCoordinator.async_setup` (line 459):

```python
from ..const import DOMAIN
db = self.hass.data.get(DOMAIN, {}).get("database")
```

…to wire the AC ramp-down feature's database access. But `DOMAIN` was **already imported at module level** at line 27. Python's scoping rule: if a name is bound anywhere in a function body (including by an `import` statement), it's promoted to **local** for the **entire** function. The pre-existing line 356 — `for ce in self.hass.config_entries.async_entries(DOMAIN)` — was unaffected by my change, but now Python treats `DOMAIN` there as local, sees it's unbound at that point in execution, and raises `UnboundLocalError`.

**Net effect on v4.5.11/v4.5.11.1 live:**
- HVAC coord crashes 60s after URA loads, during `manager.async_start` → `hvac.async_setup` → line 356
- All other URA coords (Presence, Safety, Energy, Security) start successfully
- All v4.5.11 entities (8 Numbers, master Switch, 9 Buttons) appear in the entity registry because their platforms load, but their `_get_arrester()` / `_get_zone()` lookups return None — the OverrideArrester was never set up
- All v4.5.11 entities show as `unavailable`
- HVAC decision cycle never starts → cover management, fan control, override arrester, AC ramp-down all inert
- User observed this as "lockup" because URA's ~1500 entities going `unavailable` on a coord that crashed during setup produces a state-change burst that floods clients (websocket "Reached 4096 pending messages" was logged on the mobile app connection)

## Fix

`custom_components/universal_room_automation/domain_coordinators/hvac.py:459` — delete the redundant function-local import:

```python
# Before (v4.5.11):
    from ..const import DOMAIN   # ← creates local DOMAIN, shadows module name
    db = self.hass.data.get(DOMAIN, {}).get("database")

# After (v4.5.11.2):
    db = self.hass.data.get(DOMAIN, {}).get("database")  # uses module-level DOMAIN
```

Module-level `from ..const import DOMAIN` at line 27 remains the canonical binding.

## Regression test

New class `TestNoLocalImportShadowsModuleImport` in `test_v4511_ac_energy_aware_ramp_down.py` AST-walks every function body across 7 critical files (hvac.py, hvac_override.py, hvac_zones.py, hvac_const.py, number.py, switch.py, button.py) and flags any function-local `from X import Y` where:
1. `Y` is also imported at module level, AND
2. `Y` is referenced somewhere earlier in the same function body

The second condition is what makes this test PRECISE — not all function-local re-imports cause `UnboundLocalError`. Only the ones where the name is used before the local import statement executes do. The test would have caught the original v4.5.11 bug in <1 second.

Sanity-verified: planted the pattern in a minimal test program and confirmed the AST logic flags it. Removed from working tree before commit.

## Why my Tier 2 review missed it

- **Source-grep tests** confirmed `set_database(db)` exists in hvac.py — but they don't execute the code.
- **Module-level AST import-resolution test** confirmed every module-level import resolves to a defined symbol — but it didn't check function-local imports against module-level names.
- **Review pass 1 + 2** focused on correctness, edge cases, race conditions, lifecycle. Neither reviewer (me, twice) considered Python scoping semantics on function-local re-imports.

This is a new bug class for `QUALITY_CONTEXT.md`:

> **Bug Class #34 — Function-Local Import Shadows Module-Level Import**
> A function-local `from X import Y` statement creates `Y` as a local variable for the **entire** function body. If `Y` is also imported at module level AND referenced earlier in the function than the local import statement, `UnboundLocalError` is raised at runtime — Python's lexical-scope rule promotes `Y` to local at compile time, but the local binding doesn't exist until the import executes. **Test pattern:** AST-walk every function body; flag any local import whose imported name (a) shadows a module-level import AND (b) appears in an earlier line of the same function.

## Test count progression

- v4.5.11.1: 148 tests
- **v4.5.11.2: 155** (+7 — one per scanned file)

## Lessons learned (the day's debugging)

v4.5.10 + v4.5.10.1 + v4.5.11 + v4.5.11.1 + v4.5.11.2 = 5 releases in <14 hours, each with a real bug that the previous reviews missed:

- **v4.5.10:** ImportError — symbol imported from wrong module (Bug Class #32-shape)
- **v4.5.10.1:** fixed the ImportError; no new bugs
- **v4.5.11:** UnboundLocalError — function-local import shadows module-level (Bug Class #34 — NEW)
- **v4.5.11.1:** my attempted "zone_id naming" fix; inherited v4.5.11's underlying crash (only made the entity-resolution bug visible later)
- **v4.5.11.2:** fixes v4.5.11

**Pattern observed:** every Tier 2 review pass I ran was source-grep-driven. None of them executed code. They caught semantic bugs (logic errors in branches, missing channel parameters) but missed runtime-only bugs (import resolution failures, scoping errors, lifecycle ordering).

**Recommendation for future Tier 2 protocol:** add a third review pass that EXECUTES the integration in a stub-HA environment and confirms `async_setup_entry` for each domain coordinator returns without exception. This is more expensive than source-grep tests but catches an entire class of bugs that source-grep can never find. Alternatively, make the import-resolution + scoping AST patterns part of every cycle going forward.

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (1 file touched: hvac.py)
- After restart: verify `sensor.ura_hvac_coordinator_mode` has populated attributes (`last_evaluate`, `zone_count`, `house_state`, etc.) — that confirms HVAC coord async_setup completed
