# URA v3.7.5 — Lock Sweep Critical Fix

## Summary

Fixes a `TypeError` crash in the periodic lock sweep that prevented locks from
being auto-locked and the sweep sensor from ever updating.

## Root Cause

`compliance_tracker.schedule_check()` was called with 3 positional arguments but
the method requires 5. This `TypeError` crashed `_evaluate_lock_check()` AFTER
incrementing `_lock_checks_today` and populating `_lock_compliance`, but BEFORE
setting `_last_lock_sweep` and returning the `ServiceCallAction` list.

Result: the sweep appeared to run (compliance sensor updated), but locks were
never actually locked and the sweep sensor stayed at "no_sweep_yet" permanently.

## Changes

### security.py — `_evaluate_lock_check()`
- **Moved sweep persistence above compliance tracking** so `_last_lock_sweep`
  and the dispatcher signal are always saved, even if compliance tracking fails
- **Fixed `schedule_check()` call**: correct 5-argument signature with
  `decision_id`, `scope`, `device_type`, `device_id`, `commanded_state`
- **Added `await`**: `schedule_check` is async and was called without await
- **Wrapped in try/except**: compliance tracking is non-critical and should
  never crash the sweep

### const.py
- VERSION bumped to 3.7.5
