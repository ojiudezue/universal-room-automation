# v4.6.3.2 — Thread-Safety Hotfix for `URARecentAnomaliesSensor`

**Date:** 2026-05-15 CDT
**Type:** Tier 1 hotfix (1 LoC production + behavioral test)
**Predecessor:** v4.6.3.1 (caused the wedge this fixes)

## Problem

After v4.6.3.1 deployed at 2026-05-14 23:18 UTC, HA restart resulted in a 35+ min wedge. The captured logs showed:

```
2026-05-15 00:09:57.660 WARNING [homeassistant.helpers.frame] Detected that custom
integration 'universal_room_automation' calls hass.async_create_task from a thread
other than the event loop, which may cause Home Assistant to crash or data to corrupt.
At custom_components/universal_room_automation/sensor.py, line 10321:
  self.hass.async_create_task(self._async_refresh())

2026-05-15 00:09:57.664 ERROR Exception in _handle_activity_logged when dispatching
'ura_activity_logged': RuntimeError: ... ReportBehavior.ERROR for custom integrations.
```

Plus two `coroutine 'URARecentAnomaliesSensor._async_refresh' was never awaited` warnings surfacing at unrelated GC sites (sqlalchemy, aiolifx — Python attributes orphan coroutines to wherever GC runs, not where they were created).

### Root cause

`URARecentAnomaliesSensor._handle_activity_logged` (introduced in v4.6.3 D12, fix-up B Review A3) is a dispatcher subscriber. Dispatchers in HA fire on whichever thread invoked `async_dispatcher_send`. `ActivityLogger.log` is async, but downstream callers (recorder thread completions, sync worker tasks) can synchronously trigger dispatch from non-event-loop threads.

`self.hass.async_create_task(coro)` raises `RuntimeError` when called from a non-event-loop thread under `ReportBehavior.ERROR` — which applies to custom integrations. Each firing:
- Raised the RuntimeError in the dispatcher subscriber
- Orphaned the unscheduled coroutine
- Failed the sensor refresh
- Generated a multi-line stack trace through HA's logging pipeline

This is **NOT v4.6.3.1's bug.** v4.6.3.1's only production code change was removing work from `_check_zone_anomalies`. The thread-safety bug shipped in v4.6.3 and lay dormant until v4.6.3.1's restart trigger exposed it (combined with accumulated DB/recorder state from the 3h v4.6.3 emit flood).

### Whether this is the full wedge cause

**Honest answer: unconfirmed.** Three thread-safety errors fired in the 30+ min wedge window — not the volume I'd expect to single-handedly wedge HA. The supervisor logs showed `Error on API for request services:` repeating for 30 min, suggesting event-loop starvation. Memory peaked at 10.4/11.7 GB (vs ~4 GB normal). Whether the thread-safety bug cascaded into the wedge, or whether something else (silent baseline restore? recorder backpressure? Bayesian predictor load?) caused both, is undetermined.

**This fix addresses the one concrete, log-visible URA bug.** If the wedge recurs after deploy, the next-step diagnostic is timing checkpoints throughout URA's setup phases.

## Fix

One-line change at `sensor.py:10321`:

```python
# BEFORE (unsafe — raises RuntimeError on non-event-loop thread):
self.hass.async_create_task(self._async_refresh())

# AFTER (thread-safe; routes to event loop regardless of caller's thread):
self.hass.add_job(self._async_refresh())
```

`hass.add_job` is HA's canonical thread-safe job dispatcher. Works from any thread, automatically queues the coroutine on the event loop.

## Files changed

- `custom_components/universal_room_automation/sensor.py` — 1 line replaced (the `async_create_task` → `add_job`) + ~12 lines of explanatory comment block
- `quality/tests/test_v463_anomaly_migration.py` — new test `test_recent_anomalies_handler_uses_thread_safe_scheduling` (source-grep that pins the fix; behavioral verification of thread-safety would need a real hass + multiprocessing harness, out of scope)

## Test count

- v4.6.3.1: 3094 passing
- **v4.6.3.2: 3095 passing** (+1 new pinning test)
- Pre-existing 56 failures + 14 errors unchanged

## What this hotfix is NOT

- **NOT a memory-bloat fix.** The 5+ GB anomalous allocation observed during the wedge is unexplained by this bug alone.
- **NOT a retention or DB-scale fix.** `occupancy_events` is at 2.19M rows; `anomaly_log` at 41 MB. Separate cycle queued in BACKLOG as URA DB Scale Management.
- **NOT a guarantee URA boots cleanly on re-enable.** It removes the one visible bug. If the wedge recurs, next step is timing/memory checkpoints in URA's setup paths.

## Live validation plan

After HACS download + HA restart:
1. **Watch for the thread-safety warning to STOP appearing in logs.** Specifically:
   ```bash
   ha core logs --lines 200 2>&1 | grep "async_create_task from a thread"
   ```
   Should be zero hits after this version is live.
2. **Watch for `coroutine 'URARecentAnomaliesSensor._async_refresh' was never awaited`** — should also stop.
3. **`sensor.ura_coordinator_manager_recent_anomalies`** should refresh on every anomaly emit (not get stuck at startup state).
4. **If wedge recurs**, immediately:
   ```bash
   ha core logs --lines 5000 > /tmp/ura-hang-v4632.log 2>&1
   sudo mv /config/custom_components/universal_room_automation /config/custom_components/universal_room_automation.DISABLED
   ha core restart
   ```
   Capture logs first, then bail out. Next diagnostic step is the timing-checkpoint version.

## Re-enable path post-deploy

URA is currently renamed to `.DISABLED` on the live HA host. After HACS downloads v4.6.3.2, the canonical `universal_room_automation/` directory will be created with the new code. On next HA restart, HA will load the new directory — effectively re-enabling URA automatically. No manual rename required.

(The `.DISABLED` directory should be removed manually after confirming v4.6.3.2 boots cleanly.)
