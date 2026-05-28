# URA v4.7.4.1 — async_update_entry re-entrancy hotfix

**Release date:** 2026-05-28
**Tier:** Tier 1 (hotfix — single bug, minimal blast radius, one-file code change)
**Scope:** `__init__.py` migration deferral + Bug Class #46 documentation + 3 new regression tests

---

## Bug

On first HA boot after a HACS upgrade to v4.7.4, the Zone Manager entry setup timed out with:

```
asyncio.exceptions.CancelledError: Global task timeout: Bootstrap stage 2 timeout
```

The traceback pointed at the TOU engine load (`__init__.py:1809`), but TOU is not slow. The real culprit is the `customize_buckets` migration helper introduced in v4.7.4.

## Root cause

`__init__.py:async_setup_entry` (Zone Manager path, ~line 2350) called `hass.config_entries.async_update_entry(entry, options=...)` while still inside `async_setup_entry`. HA's update-listener machinery fires `_async_update_listener` synchronously when options change, which calls `hass.async_create_task(async_reload(entry_id))`. On cold install, that reload schedules a second full pass through `async_setup_entry` before the first pass has returned — doubling the bootstrap-2 cost. With enough zones, the two overlapping setup passes exhausted HA's 120-second bootstrap-2 budget.

**Why the second boot worked:** The migration is idempotent. Once `customize_buckets` is persisted to `entry.options`, `_migration_needed` is `False` on every subsequent load. No second `async_update_entry` call → no reload → single clean setup pass → fast.

This is Bug Class #46 (filed 2026-05-28).

## Fix

The inline `hass.config_entries.async_update_entry(...)` call in the migration block at `__init__.py:2350` is replaced with:

```python
hass.async_create_task(
    _v474_defer_customize_buckets_persist(hass, entry, _new_options),
    name="ura_v474_customize_buckets_migration",
)
```

A new module-scope async helper `_v474_defer_customize_buckets_persist` holds the actual `async_update_entry` call. By the time the event loop schedules that task, `async_setup_entry` has already returned — so the update-listener-triggered reload runs as a clean second pass with the migration already persisted, making it a benign no-op on its second setup.

## Migration intent preserved

The `customize_buckets` flag still gets written to `entry.options` — just on the first event loop tick after setup returns rather than inline during setup. No data is lost.

## Files changed

| File | Change |
|---|---|
| `custom_components/universal_room_automation/__init__.py` | Replaced inline `async_update_entry` call with `async_create_task`; added `_v474_defer_customize_buckets_persist` module-scope helper (~line 3147). |
| `docs/QUALITY_CONTEXT.md` | Added Bug Class #46; bumped class count to 46. |
| `quality/tests/test_v4741_migration_deferral.py` | New — 5 AST + source-grep tests covering the fix. |
| `docs/readmes/README_v4.7.4.1.md` | This file. |
