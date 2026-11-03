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

## Live validation (prospective)
| Criterion | How to check | Result |
|---|---|---|
| Kitchen swept on the first empty update after 23:00 | `ura_activity_log` row `action=shared_space_auto_off`, `room=Kitchen`, with a time between 23:00 and 05:00 | pending |
| Kitchen overhead off by morning | `light.dimmer_tapo_wifi_matter_kitchenoverhead` history shows it off before 05:00 | pending |
| At most one sweep per room per night | no more than one `shared_space_auto_off` row per room per night | pending |
| No warning flash | no `auto_off_warning_flash` rows after the deploy | pending |
| No URA errors | log scan for `universal_room_automation` ERROR | pending |

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

## Live validation (prospective, sections 2-4 and 6)
| Criterion | How to check | Result |
|---|---|---|
| Detector check resolved | `binary_sensor.ura_coordinator_manager_camera_input_dark` attribute `detector_frozen_s` is mostly < 60 and `detector_hung_fired` is false. No `camera_detector_hung_inert_unresolved` log line | pending |
| Detector check healthy | No `Optimizer evaluator 'camera_detector_hung' raised` warnings | pending |
| Staged detector pause (operator, daytime only) | Per the camera draft's row L2 | pending, operator |
| Ack silent with speech off | The next safe-word ack with `nm_tts_enabled` off gives no `tts.speak` call and no `TTS ack announcement failed` error | pending (needs a real ack) |
| AC sensors at restart | Right after the restart, the AC ramp today/cycle sensors read unknown, not 0. The 30-day kWh keeps its value | pending |
| Midnight reset (section 6) | At 00:20 tonight, `sensor.universal_room_automation_rooms_energy_total` and each `sensor.zone_*_energy_today` equal their `room_energies` / rooms + zone-level attribute sums (within 0.1 kWh) | pending |
| Full suite | develop ce8a9543: 9 failed, all in the baseline, 0 new, 22 baseline names now pass. The midnight fix was then merged with targeted tests (132 passed) | PASS |
