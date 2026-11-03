# v5.103.101 — Shared-space auto-off becomes a night failsafe

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
The coordinator call that passes the room's occupancy into the sweep (`coordinator.py`, the periodic automation block in `_async_update_data`) has no behavioural test. Nothing in the suite drives the room coordinator's full update. The live criteria above cover it: if the call were wrong, no activity row would appear, or a row would appear while the room was occupied.
