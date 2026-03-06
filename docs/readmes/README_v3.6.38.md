# v3.6.38 — Fix motion-to-light delay + implement timed cover close + fix cover timing

## Summary

Three fixes in one release:
1. Fixed occupancy debounce causing 8-30s motion-to-light delay
2. Implemented timed cover close (sunset/time-based) — config existed but was never wired
3. Fixed cover open timing: sunrise offset overflow bug + implemented combined timing modes

## Fix 1: Occupancy debounce latency (CRITICAL)

**Problem:** The occupancy entry debounce (Fix #6 from v3.6.14) blocked the
first motion event but never scheduled a follow-up evaluation. The system
waited for the 30-second polling interval to confirm occupancy.

If a motion sensor fires once and stays on (common for PIR/mmWave), the debounce
blocks the instant event-driven refresh, and the system falls back to the 30s
poll. This produced random delays of 0-30 seconds between motion and lights.

**Fix:**
1. Reduced debounce from 2.0s to 0.5s — still filters glitches, imperceptible
2. Added `_debounce_refresh_callback` — schedules follow-up `async_refresh()`
   after debounce expires (~0.55s), so occupancy confirms without waiting for poll

New path: motion → debounce blocks → follow-up at 0.55s → occupancy → lights on.

## Fix 2: Timed cover close — not implemented (CRITICAL)

**Problem:** `CONF_TIMED_CLOSE_ENABLED`, `CONF_CLOSE_TIMING_MODE`,
`CONF_CLOSE_TIME`, and `CONF_SUNSET_OFFSET` were all exposed in the config
flow UI (users could configure them) but **no code ever read or acted on them**.
The "close covers at sunset" feature simply didn't exist.

**Fix:** Implemented `check_timed_cover_close()` in automation.py:
- Supports all four timing modes: sun, time, both_latest, both_earliest
- Uses `_is_after_sunset()` (with offset via timedelta) and `_is_after_close_time()`
- Triggers once per day per room (dedup via `_last_timed_close_date`)
- Wired into coordinator.py periodic tasks alongside auto-off checks

## Fix 3: Cover open timing bugs (MEDIUM)

**Problem A:** `_is_within_cover_time_window()` used
`sunrise_time.replace(minute=sunrise_time.minute + offset)` which overflows
if minute > 59 (e.g., sunrise 6:50 + offset 15 = minute 65 → ValueError).

**Fix:** Replaced with `sunrise_time + timedelta(minutes=offset)`.

**Problem B:** `TIMING_MODE_BOTH_LATEST` and `TIMING_MODE_BOTH_EARLIEST` were
stubs (`pass # TODO`), silently falling through to `return True` (always allow).

**Fix:** Implemented both modes:
- `both_latest`: after sunrise AND in time range (whichever is later gates it)
- `both_earliest`: after sunrise OR in time range (whichever is earlier allows it)

Refactored into helper methods `_is_after_sunrise()` and `_is_in_open_time_range()`
for reuse and clarity.

## Files Changed

| File | Change |
|------|--------|
| `coordinator.py` | Debounce fix: `async_call_later` import, 2.0→0.5s, `_debounce_refresh_callback`, cleanup; wire `check_timed_cover_close()` |
| `automation.py` | `timedelta` import, `_last_timed_close_date` tracking, `check_timed_cover_close()`, `_is_after_sunset()`, `_is_after_close_time()`, refactored `_is_within_cover_time_window()` with `_is_after_sunrise()` and `_is_in_open_time_range()`, fixed sunrise offset math |
