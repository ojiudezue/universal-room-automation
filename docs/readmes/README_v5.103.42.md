# URA v5.103.42 — Night lights follow one simple rule

Tier 2-DB: plan review (REV 3, 1 HIGH folded), three framing-disjoint build reviews (A correctness, B cross-controller parity, C test authority by per-site mutation), one fix pass, full-suite name-diff clean vs develop. Card: NIGHT-LIGHT-ACTION-SELECTOR-1 (closes LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1).

## Problem
Night lights had no rule of their own. They rode on the main lights' "on entry" setting, so a room set to "none" behaved differently in the main controller (night light off) and the background reconciler (night light on) during Sleep, and night lights came on with the main lights in bright daylight.

## Solution
- **During Sleep:** an occupied room's night lights always come on, whatever the main-light setting (Sleep colour/brightness).
- **Outside Sleep:** night lights come on only when the room is dark — the room's own light sensor, else your outdoor Illuminance integration, else the sun.
- **By day:** off, unless the room's new **"Use night lights by day"** checkbox is on (default off).
- A light in the night-light list is always treated as a night light, even if it is also a main light.
- Both controllers now use one shared helper for night-light colour and brightness, so they never fight over a bulb. Switch-type night lights get a plain on (no brightness/colour). The reconciler no longer re-applies brightness to a night light that is already on, so a manual dim sticks.
- Config: **one** new field. The five night-light colour/brightness fields moved to Advanced (saved values kept). Changing the new checkbox does not reload the room.
- No new timers.

## Behaviour changes to expect
- Rooms whose main lights are "none" now get night lights at dusk too (e.g. Breakfast Nook, Game Room, Jaya Bathroom, Living Room, Master Bedroom, Patio, Ziri Bathroom).
- Rooms whose night lights used to come on with the main lights in daylight stop doing that. Tick "Use night lights by day" on any room where you want the old daytime behaviour.

## Not in this release (carded)
- The reconciler's Sleep path sends brightness only while the main controller also sends colour (pre-existing).
- Turning off the operator's HA night-light automations — operational step after each room is onboarded and its URA automation is on.

## Live validation
### Validated 2026-10-09 (overnight pass, ~02:10 CDT; live HA manifest = v5.103.42, restarts 10-08 12:24 and 17:20 CDT; house Sleep from 22:00:33 CDT)

| Check | Result | Evidence |
|---|---|---|
| No URA errors at boot | NOT EVALUATED (log-read gap) | system_log is capped at 50 entries (oldest 01:43 CDT 10-09); journald error_log reaches back only to 21:57 CDT 10-08, so both boot windows are gone. This is not an all-clear. It rides the next attended restart (see EC-EV-TOGGLE-TRIPWIRE-1 deploy_checks). |
| New field present, default off | PASS (data) | `CONF_NIGHT_LIGHTS_BY_DAY = "night_lights_by_day"` (const.py:935, default False) is live. 5 of 50 URA entries carry it saved; the rest resolve to the default. The form layout itself was not opened (UI-only check). |
| Dusk, not Sleep: entry=none room turns its night light on once per entry | PASS | Living Room (main lights = none): `ura_activity_log` `light_turn_on light.white_series_smart_2_1_switch_light_1` at 20:01, 20:15 and 20:41 CDT, each paired with its own `occupancy_entry` (mmwave). Recorder: on 20:01 -> off 20:23 -> on 20:41 -> off 20:42. No repeated turn-ons within an occupancy. |
| Sleep: occupied rooms' night lights on, main lights stay off (URA) | PASS for URA | Living Room night light on at 22:22 CDT (in Sleep) by the main controller, off at 22:41. Master Bathroom reconciler: `switch.sonoff_1002197ef7_1 -> on (sleep_night_light)` 22:54 and `shelly2pmg3 ... switch_1 -> off (sleep_non_night_off)` 23:30. Master Closet's MAIN switch did turn on at 22:27:52, but the recorder context traces it to the operator's HA automation `automation.master_closet_storage_smart_lighting_v2` ("Master Closet & Storage Smart Lighting v3", triggered by the storage motion sensor), not to URA. This is the "turn off your HA night-light automations" step in Not-in-this-release. |
| Darkness by the room's own sensor | PASS | Master Closet night light on at 18:07 CDT, before sunset, while its own `sensor.rgbw_lux_motion_3rdr_wifi_mastercloset_illuminance` read 4.0 lx. Dark room, so it is correct by the rule. |
| Daytime, bright: no night light in a room without the checkbox | PENDING | Needs a bright-daytime observation; nothing since the restart was both bright and occupied. Next attended session. |
