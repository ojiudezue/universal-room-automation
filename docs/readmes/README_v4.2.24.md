# v4.2.24 — Critical: Config Flow Save Fix (Async Update Listener)

**Date:** 2026-05-04 (post-incident)
**Severity:** CRITICAL — all room options-flow saves were silently corrupted

## Summary

`coordinator.py:837` registered a synchronous `@callback` function as a config-entry `add_update_listener`. HA 2024+ requires update listeners to be `async def` so HA can `await` them. The sync function returned `None`, and HA's `_async_save_and_notify` did `async_create_task(None)` → `TypeError: a coroutine was expected, got None`.

**Effect on every room options-flow save:**
1. UI showed **"Unknown error occurred"** even when the save backend ran.
2. The in-memory entry was mutated (HA does that before notifying listeners), so values *sometimes* survived to disk on the next periodic flush.
3. The async reload listener (`_async_update_listener`) was registered AFTER the broken sync one — so when the sync one crashed, the async one was skipped → URA didn't reload to pick up new options even when they did persist.
4. Disk write was unreliable: `_async_schedule_save` may or may not have run depending on call order inside `_async_save_and_notify`.

User saw "errors first save, accepts second save, but may be a mirage" — exactly: the second save's identical merged dict short-circuits HA's diff check, no listeners fire, no crash, no error banner — but no disk write either.

## Months of silent data loss

`modified_at` for several rooms hadn't moved since January–March, despite the user editing them repeatedly:
- Living Room: 2026-03-14
- Breakfast Nook: 2026-03-14
- Dining Room: 2026-01-20
- Patio: 2026-01-07
- Several others

Other rooms saved fine because their save attempts coincided with conditions that bypassed the broken listener (HA short-circuit on no-change, race with the periodic flush, etc).

## Fix

`coordinator.py:837-844`:
```python
# Before (BROKEN):
@callback
def _on_entry_update(hass, entry) -> None:
    self._update_signal_subscriptions()

# After (v4.2.24):
async def _on_entry_update(hass, entry) -> None:
    self._update_signal_subscriptions()
```

One-line change. The body is still synchronous (it just calls `_update_signal_subscriptions`); only the wrapper signature changes so HA can `await` it without a TypeError.

## Tests

Existing suite: 1725 passed, 86 failed (= baseline). No regressions. The bug is in HA framework integration, not testable in URA's mock-only test rig.

## Deployment notes

- **After deploy + restart:** options flow saves should complete cleanly without "Unknown error". Try Living Room → Cover Behavior → set Close Time Source → Sunset → Submit. Should land at first try, modified_at should update, dialog should close without an error banner.
- **Months of stuck config:** the user can now go through their stale rooms (Dining, Patio, etc) and re-save the changes that were silently failing. Each one should now persist properly.
- **Diagnostic:** `last_modified_at` field in `core.config_entries` storage is the canonical "did this save take" check.

## Bug class candidate for QUALITY_CONTEXT.md

**#28: Sync update_listener regression.** HA 2024+ requires `add_update_listener` to receive an `async def` function. Symptom: silent "Unknown error occurred" on options flow save with `TypeError: a coroutine was expected, got None` in HA logs. Pattern to grep: `@callback\s*\ndef\s+\w+\(.*entry.*\).*:\s*\n.*add_update_listener`.
