# v3.14.2: Solar Window Timezone Fix

**Date:** 2026-03-13
**Branch:** develop -> main

## Problem

`_get_solar_window_hours()` compared `.date()` on UTC-aware datetimes from `sun.sun` against `now.date()` in the local timezone. Sunset at 7:40 PM CDT = 00:40 UTC *next day*, so the UTC `.date()` is March 14 while `now.date()` is March 13 → incorrectly subtracted 24h → got yesterday's sunset → negative window → clamped to 4 hours instead of ~12.

## Fix

Convert rising/setting datetimes to local timezone before comparing `.date()`:
```python
setting_local_date = setting.astimezone(now.tzinfo).date()
```
