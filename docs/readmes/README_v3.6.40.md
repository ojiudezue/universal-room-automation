# v3.6.40 — Cover automation hotfix: legacy fallback + API consistency

## Summary

Two fixes from code review of v3.6.39.

## Fix 1: Legacy `COVER_ACTION_ALWAYS` mapped to wrong mode

**Problem:** `_get_cover_open_mode()` mapped both `COVER_ACTION_ALWAYS` and
`COVER_ACTION_SMART` to `COVER_OPEN_ON_ENTRY_AFTER_TIME`. The old "always"
behavior was "open on entry regardless of time," but the mapping added a
time gate that didn't exist before — a regression for legacy users.

**Fix:** `COVER_ACTION_ALWAYS` now maps to `COVER_OPEN_ON_ENTRY` (no time
gate). `COVER_ACTION_SMART` still maps to `COVER_OPEN_ON_ENTRY_AFTER_TIME`.

## Fix 2: Inconsistent `_is_cover_open_time()` signature

**Problem:** `_is_cover_open_time()` called `dt_util.now()` internally while
`_is_cover_close_time(now)` received `now` as a parameter — inconsistent API.

**Fix:** Added optional `now` parameter to `_is_cover_open_time()`. The
`check_timed_cover_open()` caller now passes its `now` through, ensuring
a single time snapshot per cycle.

## Files Changed

| File | Change |
|------|--------|
| `automation.py` | `_get_cover_open_mode()`: split ALWAYS→ON_ENTRY vs SMART→ON_ENTRY_AFTER_TIME; `_is_cover_open_time(now)`: added optional parameter, updated caller |
