## STUCK-SENSOR-WARNING-PER-TICK-1 — "sensor stuck on" logged once, not every tick

Tier 1 (log-only). Branch `fix/stuck-sensor-warn-once` (8bcd0c5fc). Reviews A (local correctness) + C (test authority via mutation): both SHIP; LOWs fixed in-cycle.

- When a room sensor stays on long enough to be ignored, URA used to log `Room X: Sensor Y stuck on for N hours — ignoring` as a WARNING on every coordinator tick (measured 2026-10-07: 216 lines in 43 min for two sensors; system_log counted 483 for one sensor in under 3 h). It now logs the WARNING once, at the same moment the stuck-sensor phone notification fires, and a DEBUG line on later ticks.
- Behaviour is unchanged: the sensor is still ignored, the notification still fires once per sensor per day, and the per-day latch is untouched (`_emit_p22_stuck_sensor_for_tick`, `coordinator.py`).
- Known, pre-existing: the latch clears only at day rollover, so a second stuck episode of the same sensor on the same day gets neither a notification nor a WARNING (DEBUG only). The comment that claimed otherwise is corrected.
- Tests: `test_p22_stuck_warning_fires_once_then_debug_PROD` (real helper, two ticks: one WARNING + one DEBUG + one notification) and `test_async_update_data_calls_emit_p22_stuck_sensor_for_tick_PROD` (structural anchor: the call sits in the `for s in stuck_sensors:` loop of `_async_update_data` with the right arguments). Drills: call removed, call moved out of the loop, and wrong argument all go red. Gap noted by review C: no harness runs a real `UniversalRoomCoordinator._async_update_data` tick, so the anchor is structural, not behavioural (this was already true on develop for the notification path).

### Live acceptance (after the restart)
- **Live:** HA core log over any hour with a stuck sensor (e.g. `binary_sensor.mmwave_zigbee_gameroom_presence`, Exercise Room) shows at most one `stuck on for` WARNING per sensor per day (system_log count for that message stays at 1 instead of climbing every tick).
- **Discriminates:** if the fix were not routed, the system_log count would climb by about 3 a minute again; if the latch broke, the stuck-sensor notification would repeat or never fire.
