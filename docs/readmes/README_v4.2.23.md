# v4.2.23 — Cover Storm Hotfix (urgent)

**Date:** 2026-05-04 (post-incident)

## Summary

Emergency hotfix for a regression introduced in v4.2.22 that caused a 40-minute, 2200+ event cover-command storm on `cover.living_blinds` (Living Room) at sunset tonight. Two changes:

1. **Daily dedup is set BEFORE the verify-and-retry helper runs**, not after. Internal retries (3 attempts within `_send_covers_with_verify`) ARE the daily budget. If they fail, log + count, but do NOT loop on the next coordinator cycle.
2. **`blocking=False`** for cover service calls. `blocking=True` was causing 294 false service-call timeouts in one Living Room session — group covers whose sub-blinds settle asynchronously over 30-60s blew past any reasonable per-call timeout.

## Incident summary

- 7:43 PM CDT today (sunset): URA fired `cover.close_cover` on `cover.living_blinds` (a Hunter Douglas group of 10 sub-blinds).
- Group state flapped `closing` ↔ `open` for tens of seconds while sub-blinds settled async.
- v4.2.22's verify pass saw `state="open"` after 8s settle, marked as straggler, retried 2x, then returned `success=False`. Dedup NOT set.
- Coordinator next cycle (~30s later) re-entered `check_timed_cover_close`, fired again. Repeat for 40 min.
- Sensor `sensor.living_room_automation_health`: `cover_attempts_today=98, cover_failures_today=97, service_failures_today=294`.
- 8:40 PM CDT: all 10 sub-blinds finally aligned to `closed`, dedup set, storm ended.

## Root cause

v4.2.22 design: "verified state success → set dedup; otherwise retry next cycle." This is correct for individual covers with stable state. It's wrong for HA group covers whose state flaps during physical settling — the verify never sees a stable closed state, so dedup is never set, so the coordinator loops forever.

## Fix

`automation.py` `check_timed_cover_open` and `check_timed_cover_close` runners now set `_last_timed_open_date` / `_last_timed_close_date` to today **immediately on runner entry** (after sleep-mode re-check). The helper's internal retries (per-cover sequential + 8s settle + 2 straggler retries) are still the safety mechanism for individual RF stragglers — but a single helper invocation per day is the hard cap.

`_send_covers_with_verify` now uses `blocking=False` and a 5s per-call timeout. `_safe_service_call` returns immediately after handing the command to HA's service registry; the outer 8s settle + state re-check is the authoritative confirmation.

## Diagnostics still work

`sensor.<room>_automation_health` continues to expose:
- `cover_attempts_today` — total covers commanded today (single helper run = N for N-cover batch)
- `cover_failures_today` — covers that didn't reach commanded state after internal retries
- `last_cover_failure_entities` — which entities persisted as stragglers

If the helper fails its single shot, the user sees the failure on the sensor — but URA does not retry until the next sunset/sunrise window.

## Tests

16 tests pass (added `test_blocking_false_for_cover_calls` for the v4.2.23 invariant). Full suite: same baseline as v4.2.22, zero new regressions.

## Trade-off acknowledged

If the very first close attempt (with 3 internal retries) genuinely fails on a normal night, the blinds stay open until tomorrow morning. The user can:
- Manually close from the HA UI.
- Toggle `switch.<room>_cover_automation` off and on to re-fire (each fresh runner re-evaluates state, but won't re-fire if dedup date is set — to force, may need to wait until midnight or accept the stuck-open).

This is the safer trade than the storm. A future v4.2.24+ could add a manual-retry button entity per room.

## Deployment notes

- No HA restart required for safety, but recommended to clear the v4.2.22 in-memory dedup state.
- After deploy: verify `sensor.living_room_automation_health` `cover_attempts_today` resets to 0 at midnight, single value at next sunset.
- Watch tomorrow's sunset (~7:44 PM CDT 2026-05-05) for one clean close attempt.
