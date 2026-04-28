# v4.2.14 — Remove Startup Catch-Up Prune

**Date:** 2026-04-28

## Summary

Removes the startup catch-up prune entirely. v4.2.13 delayed it from 5 min to 30 min but it still saturated the write queue for 15-20 minutes, blocking all DB reads (accuracy sensor, zone sensors, external DB access via MCP). Nightly 2:30 AM maintenance is the sole cleanup mechanism.

## Problem

The startup catch-up prune (v4.2.8) ran all 7 table cleanup operations shortly after boot. Even with batching (LIMIT 1000, asyncio.sleep(0.1)), the continuous writes held the DB write queue at 21-45 items for 15+ minutes. During this window:
- `_db_read()` connections blocked on WAL checkpoint
- Accuracy sensor returned 0 predictions (reads failed)
- Zone sensors couldn't refresh
- External SQLite reads via Samba/MCP returned "database is locked"
- db_queue_peak hit 45 on v4.2.13 boot (was 54 on v4.2.12)

## Timeline
| Version | Catch-up delay | Queue peak | Outcome |
|---------|---------------|------------|---------|
| v4.2.8 | 5 min | 94 | HA unresponsive, boot loop |
| v4.2.13 | 30 min | 45 | DB locked 15+ min after T+30 |
| v4.2.14 | REMOVED | 4 (expected) | Clean boot, nightly handles cleanup |

## Risk Assessment

If nightly 2:30 AM hasn't run yet, tables may be slightly bloated until tonight. This is acceptable — bloated tables cause slower reads, not crashes. The alternative (catch-up prune) causes DB lock contention that blocks all reads for 15+ minutes on every boot.

## Changes

- Removed `_startup_catchup_prune` (primary DB init path)
- Removed `_startup_catchup_deferred` (deferred DB init path)
- Bayesian init hardening from v4.2.13 retained

## Review: Tier 1 (hotfix) — removal-only change, no new logic
- Verified unload path `pop("unsub_startup_catchup", None)` is safe when key doesn't exist
- Nightly maintenance at 2:30 AM confirmed still wired (both paths)

## Files Modified (1)
- `__init__.py` — catch-up prune removed (both paths)
