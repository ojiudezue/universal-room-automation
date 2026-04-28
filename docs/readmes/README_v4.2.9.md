# v4.2.9 — Timezone-Naive Datetime Fix + Nightly Maintenance Time Budget

**Date:** 2026-04-27

## Summary

Fixes HA 2026.4 `ValueError` on TIMESTAMP sensors returning timezone-naive datetimes. Replaces all `pytz` usage with stdlib `timezone.utc`. Adds 5-minute time budget with rotating start index to nightly maintenance to prevent write queue congestion.

## Problem

HA 2026.4 raises `ValueError: Invalid datetime: sensor.zone_upstairs_last_occupant_time provides state '2026-04-27 02:08:06.845161', which is missing timezone information`. Multiple URA sensors affected. Additionally, first nightly maintenance run (v4.2.8) caused 12 minutes of write queue congestion.

## Changes

### Timezone fixes
- `aggregation.py:3542` — ZoneLastOccupantTimeSensor: `datetime.fromisoformat()` → `dt_util.parse_datetime()` + `timezone.utc` fallback
- `__init__.py:1802` — Room persistence restore: `datetime.fromisoformat()` → `dt_util.parse_datetime()`
- `sensor.py` — 4 sites: replaced `import pytz; .replace(tzinfo=pytz.UTC)` with `from datetime import timezone; .replace(tzinfo=timezone.utc)`
- `sensor.py:7719` — Activity log time_ago: added tz guard + `dt_util.parse_datetime()`
- `sensor.py:2166` — LastIdentifiedPersonSensor: guard `.isoformat()` on string
- `sensor.py:2235,4307` — Replaced `fromisoformat` with `dt_util.parse_datetime()` for consistency
- `database.py:2331` — Census INSERT fallback: `datetime.now()` → `dt_util.utcnow()`

### Nightly maintenance improvements
- 5-minute total time budget on all 4 maintenance/catch-up loops
- Rotating start index: each nightly run starts from the next table, preventing starvation
- Inter-method `asyncio.sleep(1.0)` added to startup catch-up loops

## Review: 2x adversarial
- R1: 2 HIGH (both fixed), 5 MEDIUM (3 fixed), 4 LOW
- R2: 1 CRITICAL (fixed — same as R1), 2 MEDIUM (accepted), 2 LOW

## Files Modified (5)
- `aggregation.py` — Zone last occupant tz fix
- `__init__.py` — Room persistence tz fix + maintenance budget + rotation
- `sensor.py` — pytz removal + fromisoformat fixes + time_ago guard
- `database.py` — Census timestamp fallback
- `const.py` — (unchanged from v4.2.8)
