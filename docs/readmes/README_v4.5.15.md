# v4.5.15 — Closet + Bathroom 60-min Lazy Auto-Off Failsafe

**Date:** 2026-05-12
**Type:** Tier 1 cycle
**Predecessor:** v4.5.14 (live-validated)

## Summary

URA's existing RESILIENCE-001 failsafe forces vacancy after 4 hours regardless of motion sensor state. That's the right ceiling for most rooms but too long for closets and bathrooms — typical use is minutes, and stuck-sensor / fan-as-motion / forgotten-light patterns can keep these spaces "occupied" indefinitely. This cycle adds a room-type-keyed failsafe: closet + bathroom drop to **60 min**, all other room types unchanged at 4 hours.

22 tests (8 new behavior tests added per Review LOW #2 remediation). Tier 1 staff-engineer review APPROVED-WITH-FIXES → both LOW findings addressed pre-deploy. No config keys, no DB schema changes, no new entities.

## What's new

### const.py — room-type-keyed failsafe durations

```python
DEFAULT_FAILSAFE_DURATION_SECONDS: Final = 4 * 3600  # 4 hours
ROOM_TYPE_FAILSAFE_DURATIONS: Final = {
    ROOM_TYPE_CLOSET: 3600,    # 60 min lazy auto-off
    ROOM_TYPE_BATHROOM: 3600,  # 60 min lazy auto-off
}
```

Closet + bathroom are the only room types with overrides. All other types (bedroom, garage, utility, common_area, media_room, generic, infrastructure) fall through to the 4-hour default — preserving original RESILIENCE-001 behavior.

### coordinator.py — three small changes

1. `__init__` stores `self._room_type: str = room_type` (was previously a local var only)
2. New helper `_get_failsafe_duration_seconds(self)` does the dict lookup
3. RESILIENCE-001 failsafe check at coordinator.py:1394 now uses the helper instead of a hard-coded constant. Log message also includes the room_type and the actual limit for operator clarity:
   ```
   Room Master Bath (bathroom): Forcing vacancy after 65.2 min (failsafe — limit 60 min)
   ```

### Removed (dead constant cleanup)

`MAX_OCCUPANCY_DURATION_SECONDS = 4 * 3600` at coordinator.py:128 — was the only call-site for the old hard-coded failsafe; now unused. Removed to eliminate duplicate-source-of-truth with `DEFAULT_FAILSAFE_DURATION_SECONDS` in const.py.

## Behavior matrix

| Room type | Occupancy duration | Failsafe fires? |
|---|---|---|
| closet | 30 min | ❌ No (within 60-min budget) |
| closet | exactly 60 min | ❌ No (strict `>` comparison) |
| closet | 65 min | ✅ Yes |
| bathroom | 65 min | ✅ Yes |
| bedroom | 65 min | ❌ No (uses 4-hr default) |
| bedroom | 4h05min | ✅ Yes |
| generic | 2 hours | ❌ No |
| unknown / null type | 65 min | ❌ No (defaults to 4 hr) |
| unknown / null type | 5 hours | ✅ Yes |

## Why fail-safe semantics, not stricter timeout

The user direction was specifically "even when motion sensor present". URA already has motion-based vacancy via `ROOM_TYPE_TIMEOUTS` (closet: 120s, bathroom: 300s). Those handle the normal case — motion clears, occupancy clears after the timeout. This cycle adds a SECOND layer: regardless of whether motion is still triggering, force vacancy at 60 min. Catches:

- Bathroom fan keeping motion sensor false-positive triggered
- Closet door open + motion sensor seeing adjacent-room activity
- Stuck motion sensor (battery dying, hardware fault)
- Light manually turned on (no motion source), forgotten

Critically, this works even for rooms with NO motion sensor — `_became_occupied_time` is set on any occupancy-source path (motion, camera, person tracking, manual), so the failsafe fires at 60 min regardless of source.

## What's NOT changed

- Motion-based timeouts (`ROOM_TYPE_TIMEOUTS`) — unchanged at closet=120s, bathroom=300s
- 4-hour default failsafe for all other room types — unchanged
- No new config options (per "60m default" direction; per-room override can be added later via options flow if needed)
- No DB schema, no entity changes, no migration

## Tier 1 Review

Single staff-engineer review per CLAUDE.md hotfix protocol. Mental execution covered:
- 9 occupancy-duration scenarios across 5 room types
- Camera extension short-circuit (`_failsafe_fired` flag) preserved
- Options-flow room_type change (reload re-reads, no stale-attribute hazard)
- Function-local import of `ROOM_TYPE_FAILSAFE_DURATIONS` — verified no module-level shadow (Bug Class #34 negative)
- Stuck motion sensor case — `_became_occupied_time` not refreshed by motion, failsafe still fires at 60 min

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 0 | — | — |
| LOW | 4 | 2 | 2 documented |

**LOW findings:**
- ✅ Fixed: dead `MAX_OCCUPANCY_DURATION_SECONDS` constant removed (eliminates duplicate-source-of-truth)
- ✅ Fixed: 8 new behavior tests pinning the failsafe decision logic (the original 14 tests were source-grep / lookup-only)
- Accepted: log format (em-dash style consistent with rest of codebase)
- Accepted: `DEFAULT_FAILSAFE_DURATION_SECONDS` and `MAX_OCCUPANCY_DURATION_SECONDS` naming asymmetry — old constant deleted, so no longer an issue

## Test count

- v4.5.14: 379 tests
- **v4.5.15: 401** (+22 from `test_v4515_closet_bathroom_failsafe.py`)

Breakdown:
- 6 const-dict structural tests (declarations, values, scope-pinning)
- 4 coordinator source-grep / AST tests (helper exists, integration site uses it, imports correct)
- 4 isolated lookup tests
- 8 behavior tests for the failsafe-fire decision (6 room types × multiple durations, including boundary at exactly 60 min)

## Live validation plan (post-restart)

1. **Closet + bathroom rooms tagged correctly:**
   - Find your closet/bathroom rooms in Settings → Devices & Services → URA → look at each's `room_type` config (should be "closet" or "bathroom")

2. **Existing room state preserved:**
   - No room transitions immediately on restart from this change

3. **Failsafe behavior:**
   - Hard to test live without a controlled stuck-sensor scenario. The most realistic test: leave a closet/bathroom light on for 65+ min with motion sensor seeing activity. URA should fire `Room <name> (closet): Forcing vacancy after X min (failsafe — limit 60 min)` in system logs.
   - Look for log entries matching: `ha_get_logs source=system search="failsafe" hours_back=2`

4. **No regressions on other room types:**
   - Confirm no rooms incorrectly transition to vacant
   - Master Bedroom 4-hour failsafe (which we saw fire earlier today) should still fire at the same 4-hour threshold

5. **No new URA errors:**
   - `ha_get_logs source=system level=ERROR search=universal_room_automation hours_back=1` empty

6. **Envoy race watch (5th restart this session):**
   - Bootstrap timing vs URA validation error. Statistical sample growing.

## Deploy notes

- 2 files touched (const.py, coordinator.py)
- HACS download required after deploy.sh
- HA restart required
- No entity changes
- No orphaned entries

## Documents

- BACKLOG: anomaly sensor refresh signals (Presence + MF) still pending; v4.5.13.2 envoy race parked

## Next

- **v4.5.16** — Duplicate-timestamp investigation (minor)
- **v4.5.17** — Bayesian prediction-scoring pipeline investigation (minor)
- **v4.6.0** — Routine Awareness Phase 1
