# v4.2.16 — Graceful DB Write Flush on Shutdown

**Date:** 2026-04-30

## Summary

Replaces fail-all drain with graceful flush on write worker shutdown. On cancel, opens a fresh connection and executes remaining queued writes with a 5-second time budget before failing anything left. Handles re-cancellation during flush to ensure futures are never orphaned.

## Problem

When the DB write worker was cancelled (reload or shutdown), `_drain_pending_futures` failed ALL pending writes with `RuntimeError`. Data written between the last completed write and the cancel was lost. On integration reload, this meant any in-flight census, energy, or activity writes were silently dropped.

## Changes

### Graceful flush (database.py)
- New `_flush_pending_writes()` method: opens fresh aiosqlite connection, processes remaining queue items with 5-second time budget, drains failures for anything left
- `CancelledError` handler in write worker now calls `_flush_pending_writes()` instead of `_drain_pending_futures()`
- Reconnect-cancel path also flushes instead of returning silently
- `CancelledError` caught inside flush to prevent orphaned futures if re-cancelled during flush
- Removed redundant local `import time` (module-level import exists)

## Review: Tier 1 (hotfix)
- 0 CRITICAL, 0 HIGH, 1 MEDIUM (CancelledError during flush — fixed), 2 LOW (redundant import — fixed, WAL pragma — accepted)
- Full report: `docs/reviews/code-review/v4.2.15_memory_delta_write_worker.md` (covers both v4.2.15 and v4.2.16)

## Files Modified (1)
- `database.py` — graceful flush method + cancel handler fixes
