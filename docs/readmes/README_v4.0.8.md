# v4.0.8 — Diagnostic: Refresh Timing Instrumentation

## Problem
v4.0.7 two-tier fix reduced unnecessary callbacks by ~70-85%, but rooms still show 14-19 second delays between motion sensor firing and occupancy confirmation. Event callbacks fire within 10ms (proven), but something between the callback and the debounce follow-up refresh is delayed.

## Diagnostics Added
Microsecond-precision `time.monotonic()` checkpoints at WARNING level:

1. **`DIAG MOTION`** — When Tier 1 callback fires for an occupancy sensor (mono timestamp)
2. **`DIAG debounce_callback`** — When the 0.5s debounce follow-up fires (mono timestamp)
3. **`DIAG NEW ENTRY`** — After debounce check passes, shows phase1 duration
4. **`DIAG OCCUPANCY CHANGE`** — When state transition is detected, ms since refresh start
5. **`DIAG automation complete`** — After `handle_occupancy_change` returns, ms duration
6. **`DIAG Phase 3 DB queries`** — If prediction DB queries take >100ms
7. **`DIAG SLOW`** — If total `_async_update_data` exceeds 500ms

## What This Will Show
- **If debounce_callback mono is close to MOTION mono + 0.55:** Event loop is responsive, problem is elsewhere
- **If debounce_callback mono is 10-19s after MOTION mono:** Event loop starvation from poll storm
- **If Phase 3 DB >100ms:** DB contention is the bottleneck
- **If SLOW >500ms:** `_async_update_data` is too heavy, holding the shared lock

## Temporary
All DIAG logs will be removed once root cause is identified.
