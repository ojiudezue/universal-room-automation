# URA v5.103.53 — Fan trust follows sensor capability; per-room radar settings; memory writers live again

Cards: OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1, URA-SENSOR-TUNING-1, MEMORY-WRITERS-SILENT-DROP-1. Full-suite name-diff vs v5.103.52: 0 new, 0 gone (132 = 132).

## 1. Fan-noise rejection follows sensor capability (OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1)
**Problem:** fan-noise rejection keyed on the occupancy source label `mmwave`, which only the `presence_sensors` list produces. A radar filed elsewhere (e.g. a combined radar+motion sensor in `occupancy_sensors`) got no fan rejection, and a bed sensor next to a radar could be mistaken for radar-only.
**Fix:** each tick records whether the active sensors are *all radars by capability* (operator override > list > device family; bed/PIR/unknown never radar; fail-closed). The running-fan release (D2), its latch, the presence fan-interference hold (incl. its reset), and the fan recheck (eligibility, still-armed, VACATED, per-family window) read that instead of the label. Override Occupied always blocks the recheck. Kill switch `OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED` restores every old check. Display/DB labels unchanged.
Reviews: A correctness SHIP; B lifecycle FIX-REQUIRED (override no longer blocked recheck) → fixed + drilled.

## 2. Per-room radar settings for ZK/ZX (URA-SENSOR-TUNING-1 Phase A)
Room options gain a "Radar settings" block for Hobeian ZG-204ZK/ZX radars only: moving-people sensitivity, still-person sensitivity, watch distance (clipped to the device max), hold time — each defaulting to "Leave as is". On save URA sends only changed fields (never at boot, never to other settings). Service `universal_room_automation.reapply_radar_settings` re-sends the stored values. URA logs that it sent a value; battery radars apply it when they next wake (the device cannot report its settings back).
Review: FIX-REQUIRED (service unload, unclear labels, untested save path) → fixed + drilled.

## 3. Memory writers live again + recheck outcome + weekly health check (MEMORY-WRITERS-SILENT-DROP-1)
**Problem:** three memory writers (`phantom_retro`, `tracker_trust_excluded`, `house_state_transition`) had written 0 rows since v5.78.0 — the scheduler omitted HA's required task `name`, the TypeError was swallowed. Tests used a fake whose `name` had a default. Audit: docs/planning/AUDIT_memory_writer_coverage.md.
**Fix:** name passed; failures logged at WARNING (once per writer); the test fake now enforces HA's real signature. New `fan_recheck_outcome` episode per recheck (vacated / occupied / forced / cancel-driven / aborted, fan restored or left off, written immediately; a 5-min follow-up records whether the fan was turned back on by hand; timers cancelled on shutdown). Weekly check alerts once per writer-backed episode type with 0 rows in 7 days (last-run persisted). Expected volume < 100 rows/day total.
Reviews: A FIX-REQUIRED (hollow wire-in test, untracked timer/lost row, timestamp, aborts) → fixed, drill re-run by orchestrator (4 red); B volume/DB SHIP.

## Not built / deferred
- D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1 (MS600 motion bit can still clear the D2 latch in GB1/GB2/Media) — carded.
- FAN-TRANSITION-GATE-FOLLOWS-CAPABILITY-1 — parked (gate window is 0).
- Radar settings: anti-interference / advanced JSON — Phase B.
- Memory: device-health episodes (operator decision: recorder covers it); writer-less vocabulary types not built.
- Fan-recheck test fake lacks `verify_event_loop_thread` (33 pre-existing failures) — card needed.

## Validated 2026-10-11 (restart 20:58 CDT)
| Criterion | Result | Evidence |
|---|---|---|
| Installed | PASS | manifest on disk v5.103.53; release PR #624 carries 22 code files |
| Boot: 0 URA errors | PASS | HA system_log (search universal_room_automation): WARNING-level boot transients only, no ERROR. (`ha core logs` over SSH returns unauthorized — not a valid oracle.) |
| Memory writers live | PASS | `memory_episodes` row `house_state_transition` 2026-10-12T02:00:54Z home_evening→home_night, trigger periodic — first ever row of this type |
| `reapply_radar_settings` registered | PASS | websocket `get_services` lists it (14 URA services) |
| `fan_recheck_outcome` row on next recheck | PENDING (organic) | one-shot DB check after the next fan recheck; proven in-suite (6 behavioural tests, orchestrator drill 4 red) |
| Capability-routed fan trust | PENDING (organic) | folds into the 2026-10-18 fan re-measure |
