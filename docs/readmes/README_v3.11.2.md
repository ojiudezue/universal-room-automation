# v3.11.2 — Datetime Timezone Hotfix

**Date**: 2026-03-12
**Scope**: Critical bugfix — naive datetime crashes

---

## Problem

Four locations in sensor.py used naive datetimes (`datetime.now()` or `datetime.fromisoformat()` on DB strings) that were subtracted from or compared with timezone-aware datetimes. This caused:

1. `TypeError: can't subtract offset-naive and offset-aware datetimes` — 221 occurrences in 17 minutes
2. `ValueError: Invalid datetime ... missing timezone information` — 14 occurrences

The census validation age sensor (`_check_rooms` callback) was the worst offender, crashing on every aggregation timer tick and flooding the HA event loop with error logging, causing significant performance degradation across the entire instance including config flow responsiveness.

## Fixes

| Location | Issue | Fix |
|---|---|---|
| sensor.py:2745 | `datetime.now() - result.timestamp` | `dt_util.utcnow()` + tzinfo guard |
| sensor.py:2135 | `datetime.now() - last_time` in occupant attributes | `dt_util.utcnow()` + tzinfo guard |
| sensor.py:2197 | `fromisoformat(entry_time)` returns naive | Add UTC tzinfo if missing |
| sensor.py:4216 | `fromisoformat(ts)` for lock sweep | Add UTC tzinfo if missing |
