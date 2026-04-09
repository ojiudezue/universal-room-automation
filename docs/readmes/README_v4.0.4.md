# v4.0.4 — Fix: Logbook API + Reload Performance

## Bug Fixes

### 1. Logbook platform crash (from v3.23.0)
**Problem:** HA 2026.x changed `async_describe_event` from 2 args to 3 args (added `domain` as first argument). Our `logbook.py` called with 2 args, causing `TypeError` on every startup and reload. This error fired on every HA restart since v3.23.0 (Activity Log release).

**Fix:** Changed `async_describe_event("ura_action", callback)` to `async_describe_event("universal_room_automation", "ura_action", callback)`.

### 2. Room coordinator reload re-trigger (pre-existing, improved in v4.0.3)
Already shipped in v4.0.3 — this release includes the logbook fix that was also contributing to reload noise.

## Files Changed
- `logbook.py` — 3-arg API call for HA 2026.x
- `quality/tests/test_activity_logger.py` — Updated logbook test mocks to match 3-arg signature

## Review
2x staff-engineer review. 0 CRITICAL, 1 HIGH (test mock fix — applied), 2 MEDIUM (import fragility noted, comment clarity).
