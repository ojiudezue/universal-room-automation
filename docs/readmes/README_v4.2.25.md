# v4.2.25 — Bug Class #28 documentation + guard test

**Date:** 2026-05-04
**Type:** docs + test only, no runtime code changes

## Summary

Persists the v4.2.24 root cause (sync function passed to `entry.add_update_listener`) as Bug Class #28 in `docs/QUALITY_CONTEXT.md` and adds an AST-based guard test that fails CI/local builds if any future code reintroduces the pattern.

## What's in this release

### `docs/QUALITY_CONTEXT.md` — new Bug Class #28
- Pattern, impact, symptoms (mirage save behavior, "Unknown error occurred" UI, silent disk-write loss).
- Prevention checklist.
- Detection grep + guard test snippet.
- Historical example: v4.2.24 incident (months of silent config-save failures across Living Room, Dining, Patio, Breakfast Nook).
- Severity: CRITICAL.

### `quality/tests/test_update_listener_async.py` — guard test
- AST-walks every `*.py` under `custom_components/universal_room_automation`.
- For every `entry.add_update_listener(handler_name)` call, locates the handler function definition by name in the same file.
- Fails the test if it's `def` (not `async def`).
- Currently passes — codebase verified clean across all 5 callsites (1 in `coordinator.py`, 4 in `__init__.py` covering room/zone/coordinator manager/integration entries).

## Audit performed

Full grep + AST audit confirmed v4.2.24 is comprehensive. All `add_update_listener` callsites use `async def` handlers across every config entry type:

| File:line | Handler | Status |
|---|---|---|
| `coordinator.py:850` | `_on_entry_update` | async (fixed v4.2.24) |
| `__init__.py:1606` | `_async_update_listener` | async |
| `__init__.py:1711` | `_async_update_listener` | async |
| `__init__.py:1738` | `_async_update_listener` | async |
| `__init__.py:1832` | `_async_update_listener` | async |

## Tests

1726 passed (+1 guard test vs v4.2.24 baseline of 1725), 86 failed (= baseline → zero regressions).

## No deploy verification needed

Doc + test additions only. No HA restart required. HACS will pull the release for completeness; nothing changes at runtime.
