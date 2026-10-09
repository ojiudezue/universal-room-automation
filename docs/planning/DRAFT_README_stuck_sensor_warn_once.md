# DRAFT README section: stuck-sensor warning once per episode (STUCK-SENSOR-WARNING-PER-TICK-1)

Fold into the release README that ships `fix/stuck-sensor-warn-once` (33b730db4, rebased onto develop 2026-10-09).

## Problem
When a room's motion/radar sensor stays on for hours, URA correctly ignores it, but it wrote the same
"Sensor X stuck on for N hours — ignoring" WARNING into the HA log on every coordinator tick (~3/min per
sensor; 216 lines in 43 min live on 10-07, 483 for one sensor in a day), feeding the log floods that
rotate HA's log history out within hours.

## Solution
- The WARNING is written once per stuck episode, at the same moment the phone notification fires (when the
  per-day latch is first set). Later ticks write the same line at DEBUG.
- After a restart on the same day, the boot "Restored stuck-state" INFO line names the sensors already
  reported today (they log only DEBUG afterwards).
- Ignoring the sensor, the notification, and the per-day latch are unchanged. A still-stuck sensor warns
  again once after the day rolls over.

## Tests
- `test_stuck_sensor_consequence_prod.py`: helper semantics (WARNING once, DEBUG after, NM once) and
  `test_async_update_data_calls_emit_p22_stuck_sensor_for_tick_PROD` (structural wire-in anchor; the
  call-neuter drill in `_async_update_data` turns it red).
- Full-suite name-diff vs develop 2026-10-09: 0 NEW, 0 GONE.

## Live validation (prospective)
- After restart, with a known stuck sensor (Exercise Room / Master Bedroom radar), `ha_get_logs source=system`
  shows the "stuck on" WARNING with count 1 per sensor per day, not hundreds.
- `notification` / NM for the stuck sensor still arrives once per day.
