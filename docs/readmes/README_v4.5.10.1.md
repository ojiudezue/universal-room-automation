# v4.5.10.1 — Fix ImportError on 5 v4.5.10 Number entities

**Date:** 2026-05-10
**Type:** Tier 1 hotfix (~3 LoC fix + 1 regression test)
**Predecessor:** v4.5.10
**Reproducer:** v4.5.10 live validation post-restart — 5 of the 7 new Number entities failed to register with `ImportError: cannot import name 'SIGNAL_HVAC_ENTITIES_UPDATE' from 'custom_components.universal_room_automation.domain_coordinators.signals'`.

## Summary

`_hvac_tunable_number_factory.async_added_to_hass` imported `SIGNAL_HVAC_ENTITIES_UPDATE` from `signals.py` — but that signal lives in `hvac_const.py`, not `signals.py`. Same Bug Class #32-shape miss as v4.5.0.1's `CONF_ENERGY_ARBITRAGE_SOC_TRIGGER` rename: source-grep test verified the import statement was present but didn't verify the source module actually exposes the symbol.

5 entities affected (the 2 entities that were registered before the failed ones — Cover Close Threshold, Cover Close Temp — registered fine because they reach the import only on the deferred-push path, which the first 2 didn't need; the other 5 hit the path during init):
- `number.ura_hvac_coordinator_cover_open_temp`
- `number.ura_hvac_coordinator_cover_override_duration`
- `number.ura_hvac_coordinator_solar_banking_cool_floor`
- `number.ura_hvac_coordinator_fan_on_threshold`
- `number.ura_hvac_coordinator_fan_off_hysteresis`

## Fix

`number.py:867` import statement:

```python
# Before (v4.5.10)
from .domain_coordinators.signals import (
    SIGNAL_HVAC_ENTITIES_UPDATE,
)
# After (v4.5.10.1)
from .domain_coordinators.hvac_const import (
    SIGNAL_HVAC_ENTITIES_UPDATE,
)
```

The signal is fired by hvac.py via `from .hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE` and consumed by sensor.py via the same path. Number entity should follow the same import.

## Regression test

New test `test_factory_signal_import_resolves` in `test_v4510_hvac_tunables_and_labels.py`:

AST-walks every `ImportFrom` statement inside `_hvac_tunable_number_factory`, then text-searches the target module file to verify the symbol is actually defined there. Catches the v4.5.0.1-shape bug (import statement is well-formed but source module doesn't expose the symbol) — what live HA caught manually now caught at test time.

This test is the v4.5.2 D5 generalized-migration-helper-imports test extended to a different code shape. Both share the underlying lesson: **verify imports RESOLVE, not just that they're textually present**.

**Test count progression:**
- v4.5.10: 92 tests, 0 isolated failures
- **v4.5.10.1: 93** (+1 regression test), 0 isolated failures across 59 files

## Lesson learned (v4.5.10.x)

Two half-shipped bits caught in v4.5.10 live validation:
- v4.5.10 originally: the entire D6 / mode-sensor surface from v4.5.9 worked, but the new factory's signal import was wrong
- (v4.5.10 source-grep tests verified factory mentions the signal, but didn't verify the source-module path is correct)

**Add to review checklist:** for every new cross-module import added in a release, source-grep the target module to verify the imported symbol is defined there. Or use the AST-walk pattern in `test_factory_signal_import_resolves` as a template.

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (only number.py touched, but the 5 broken entities won't appear without a restart)
