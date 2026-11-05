# v5.103.101: night lights-out failsafe; alarm for a hung camera detector; ack no longer speaks when speech is off; AC savings totals survive restarts

Cards: SHARED-SPACE-AUTO-OFF-FAILSAFE-1, CAMERA-SILENT-PRODUCER-TRIPWIRE-1, NM-ACK-TTS-IGNORES-DISABLE-1, HVAC-KWH-AVOIDED-TOTAL-NOT-MONOTONIC-1, TEST-DPM-WINTER-MONTH-COUPLED-1 (tests only), ENERGY-TODAY-MIDNIGHT-FREEZE-1. Deploy risk: LOW-MEDIUM. Lights and fans are only ever turned OFF; the other changes are a new alarm, a gate on speech, sensor values at restart, and test clocks.

## Contents
1. Shared-space night failsafe (below)
2. Camera detector-hung alarm
3. Safe-word acknowledgement respects "spoken alerts off"
4. AC savings sensors at restart
5. Dynamic-preset tests pinned to a summer clock
6. Energy-today totals no longer freeze at midnight

---

## 1. Shared-space auto-off becomes a night failsafe

Card: SHARED-SPACE-AUTO-OFF-FAILSAFE-1 (Tier 2). Plan: `docs/planning/PLANNING_shared_space_auto_off_failsafe.md` (rev 2).

## Why
On the night of 2026-11-02 the Kitchen overhead stayed on from 21:16 to 05:01. The overhead is on the Kitchen's leave-on list, and the 23:00 shared-space sweep skipped leave-on lights. The sweep also ran only during the 23:00 hour and ignored whether anyone was in the room.

## What changed
- **The sweep waits for an empty room.** From the auto-off hour (default 23:00) to a new give-up hour (default 05:00), URA checks every update. The first time the room reads empty, it turns off everything in it. It does this once per night.
- **Leave-on lights are included in this sweep.** Leaving the room during the day still keeps them on, and the zone and Away sweeps are unchanged.
- **A person's manual-on hold is still respected.**
- **No sweep while URA is still settling after a restart.** It tries again on the next update.
- **If the room stays occupied all night, nothing is swept.** That includes fans and switches, which used to be forced off at 23:00. If a sensor sticks on after bedtime, the room stays "occupied" and gets no sweep that night. The operator accepted this.
- **The 10:55 PM warning flash is removed.** The sweep only runs when nobody is there, so the flash had nobody to warn. The "Pre-Off Warning Flash" setting is still in the form, marked retired, and has no effect.
- **The activity log shows the actual time** the sweep ran, for example "Shared space night failsafe auto-off at 01:37 (room vacant)".

## New setting
Room options, Basic setup, shown when Shared Space is on: **Auto-Off Give-Up Hour** (`shared_space_auto_off_cutoff_hour`, 0-23, default 5). If you set it to the same value as the Auto-Off Hour, URA checks only during that one hour, as it did before. The window can wrap past midnight (23 to 5 is the normal case).

## Validated 2026-11-04 (overnight read-only pass; live since the 11-03 18:01 restart)
| Criterion | Result | Evidence |
|---|---|---|
| Kitchen swept on the first empty update after 23:00 | FAIL (by design, not a code fault) | No Kitchen row. `switch.kitchen_automation` is off (paused on purpose since at least 10-08), and the failsafe runs inside the room's automation-enabled gate (`coordinator.py` `elif self._is_automation_enabled()` :5335 → call :5441), as the old sweep did. Kitchen was vacant 23:13-23:17 with the overhead on. Decision carded on SHARED-SPACE-AUTO-OFF-FAILSAFE-1 (PICK). |
| Kitchen overhead off by morning | as-observed | Off at 23:18:45, switched by hand (logbook entry with no automation context), not by URA |
| Failsafe fires in unpaused shared spaces | PASS | 15 `shared_space_auto_off` rows 23:00-23:38: Game Room, Media Room Closet, Breakfast Nook, Guest Bedroom 2 Hallway, Kitchen Hallway, Upstairs Hallway, Stair Closet, Kitchen Pantry, Butler Pantry, Laundry, Laundry Closet, Dining Room (23:00), Powder (23:05), Living Room (23:08), Garage B (23:38) |
| At most one sweep per room per night | PASS | GROUP BY room: every count = 1 |
| No warning flash | PASS | 0 `auto_off_warning_flash` rows after the deploy (last 10-31 03:55Z) |
| No URA errors | PASS | `ha_get_logs source=system` (in-memory since boot) filtered to universal_room_automation: WARNINGs only, no ERROR |

## Known gap
The occupancy hand-off now lives in a small coordinator helper (`_run_shared_space_failsafe`), which has its own test. The single line in `_async_update_data` that calls that helper is still untested, because nothing in the suite drives the room coordinator's full update. The live criteria above cover it: if the call were missing, no activity row would appear.

A restart in the window also skips the sweep until the presence coordinator is registered and settled (fails closed), then retries on the next update.


---

## 2. Camera detector-hung alarm (CAMERA-SILENT-PRODUCER-TRIPWIRE-1)
The existing camera alarm catches Frigate going down: its person sensors turn unavailable. It cannot see a hung detector, where every sensor stays available but Frigate's overall detection rate (`sensor.frigate_detection_fps_2`) stops changing. This release adds a check, `camera_detector_hung`, that pages through the notification manager when that number holds the same value for 15 minutes after boot settle.

How it behaves:
- The sensor is found through the entity registry. If none is found (for example on a Protect-only install), the check stays inactive and logs one INFO line.
- It pages once per episode, and the page clears when the value changes.
- During quiet hours it waits and pages when they end, held for at most 12 hours.
- It has two knobs, both code constants: `CAMERA_DETECTOR_FROZEN_S` = 900 and `CAMERA_DETECTOR_QUIET_DEFER_MAX_S` = 43200.
- The camera-input-dark binary sensor gains three attributes: `detector_frozen_s`, `detector_hung_fired` and `detector_hung_deferred_quiet`.
- Full detail: `docs/readmes/README_DRAFT_camera_detector_hung_tripwire.md`. Plan: `docs/planning/PLANNING_camera_detector_hung_tripwire.md`.

## 3. Safe-word acknowledgement respects "spoken alerts off" (NM-ACK-TTS-IGNORES-DISABLE-1)
Acknowledging a CRITICAL alert used to try to speak on all 5 speakers even when spoken alerts were switched off. It is now gated by the same enable and severity check as the alert itself, `_channel_qualifies("tts", CRITICAL)`. With speech on, behaviour is unchanged.

## 4. AC savings sensors at restart (HVAC-KWH-AVOIDED-TOTAL-NOT-MONOTONIC-1)
The AC ramp impact sensors published seeded zeros at restart, which statistics read as resets.
- Until the first refresh, they now read unknown.
- The kWh total keeps its restored value.
- "AC kWh Avoided (Total)" is renamed "(30 days)", and its state class changes from TOTAL_INCREASING to TOTAL.
- "AC Ramp Savings Lifetime" is renamed "(30 days)".
- Unique IDs are unchanged.

**Operator action after deploy:** go to Developer Tools → Statistics and fix or clear `sensor.ura_hvac_coordinator_ac_kwh_avoided_total`.

## 5. Dynamic-preset tests (TEST-DPM-WINTER-MONTH-COUPLED-1)
21 tests failed from Nov 1 because dynamic presets deliberately skip winter months and the tests read the real calendar. The tests now pin the month to July, and a new `test_winter_month_skips` covers the winter gate. There is no production change.

## 6. Energy-today totals no longer freeze at midnight (ENERGY-TODAY-MIDNIGHT-FREEZE-1)
The zone, all-rooms and whole-house "energy today" totals allowed one drop per day. Rooms reset at their own moments after midnight, so the first post-midnight sample used up that drop and the real reset was refused. The totals then held a stale number for hours, for example Master Suite 34.45 kWh at 02:00 when its rooms summed to 4.44. This happened 2 nights out of 2.

The fix:
- One shared helper, `_accept_energy_today`, now accepts every drop in the first 15 minutes after local midnight (`ENERGY_TODAY_RESET_ACCEPT_WINDOW_MIN` = 15, code constant), plus any drop across a date change.
- A mid-day drop is still held.
- The all-rooms total now restores its value at restart, as the zone totals already did, so a boot sample taken before the rooms load is not booked as a reset.
- One review: SHIP. Its finding about long-term statistics is carded as ENERGY-TODAY-STATS-STEPPED-RESET-1 (pre-existing).

## Validated 2026-11-04 (sections 2-4 and 6; overnight read-only pass)
| Criterion | Result | Evidence |
|---|---|---|
| Detector check resolved | PASS | 02:05 11-04: `binary_sensor.ura_coordinator_manager_camera_input_dark` `detector_frozen_s`=0, `detector_hung_fired`=false, `detector_hung_deferred_quiet`=false; `sensor.frigate_detection_fps_2`=30 |
| Detector check healthy | PASS | system_log since the 18:01 restart: no `camera_detector_hung` and no `Optimizer evaluator 'camera_detector_hung' raised` line. The INFO `inert_unresolved` line cannot be read from system_log (WARNING+); the attributes above show the sensor was resolved |
| Staged detector pause (operator, daytime only) | pending, operator | Per the camera draft's row L2 |
| Ack silent with speech off | pending (no ack yet) | No safe-word ack since the restart (`notification_log` has no `ack_time` after it). Proven in-suite |
| AC sensors at restart | PASS | `ac_kwh_avoided_today` and `ac_ramp_savings_today`: unknown 18:01:43, real value 18:02:51, never 0. `ac_kwh_avoided_total` held 292.27 across the restart, then 281.151 at midnight; hourly statistics sum 0 → -11.119 (honest decrease, no re-add) |
| Midnight reset (section 6) | PASS | Read 02:02-02:10 (the window where it froze before): rooms total 4.54 vs room_energies sum 4.53; Master Suite 3.44 = 3.34 + 0.098 zone-level; Back Hallway 0.45 = 0.387 + 0.06; Upstairs 0.38 = 0.295 + 0.082; Entertainment 0.08; Outside 0.01 |
| Full suite | PASS | develop ce8a9543: 9 failed, all in the baseline, 0 new, 22 baseline names now pass. The midnight fix was then merged with targeted tests (132 passed) |
