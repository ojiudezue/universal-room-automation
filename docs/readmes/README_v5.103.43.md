# URA v5.103.43 — Night lights turn off when the room empties

Post-deploy fix for v5.103.42 (found live on 10-09). Root cause proven from recorder + URA activity log; two framing-disjoint reviews (both caught and blocked an over-broad first fix); full-suite name-diff clean after a stale test oracle was updated to the intended rule. Cards: NIGHT-LIGHT-ACTION-SELECTOR-1, LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1.

## Problem
- Living Room's night light (Inovelli) came on at 02:37 during Sleep and stayed on until it was turned off by hand at 05:18. The room's exit setting is "leave on", and turning night lights off still depended on that setting.
- Under house Sleep, rooms without sleep protection lit night lights with evening colour/brightness instead of Sleep.

## Fix
- Night lights that the rule turned on now turn off when the room empties, whatever the main exit setting — except lights on the room's "leave on when empty" list. Both controllers agree.
- Night lights use Sleep colour/brightness whenever the house is in Sleep, even in rooms with sleep protection off. Main-light behaviour in those rooms is unchanged (an earlier draft that changed it was blocked in review).

## Not changed (operator decision pending)
- Rooms with sleep protection on (e.g. Master Bath Toilet) still ignore the first 2 motion entries during Sleep, so the night light waits for the 3rd. Not a regression; awaiting the operator's call.

## Live validation (prospective)
- Living Room: after an occupied→vacant transition at night, ura_activity_log shows a night-light turn_off; recorder shows the Inovelli light off within the vacancy timeout.
- During house Sleep, a night-light turn_on in a room without sleep protection logs the sleep mode, not "evening".
- Main lights in rooms without sleep protection are not turned off on entry during Sleep.
- No URA errors at boot.

## Validated 2026-10-10 (observed window 2026-10-09 22:00 → 2026-10-10 08:00 CDT; see also README_v5.103.44.md's table for the Master Bath Toilet sleep-protection case, which found a live-validation gap)

| Criterion | Result | Evidence |
|---|---|---|
| Living Room: occupied→vacant at night logs a night-light turn_off, light actually goes off | PASS | `ura_activity_log`: `light_turn_on "Turned on 1 night light(s) (sleep)"` at 03:53:35Z paired with `occupancy_entry`; `light_turn_off` at 04:00:41Z paired with `occupancy_exit` (same timestamp, same transaction). Repeats at 04:04:15Z/04:12:58Z. |
| During Sleep, night-light turn_on logs sleep mode (not "evening") in a room without sleep protection | PASS | Both Living Room `light_turn_on` descriptions above explicitly say `"(sleep)"`, during the `sleep` house state (03:00:10Z–11:00:41Z per `house_state_log`). |
| Main lights in rooms without sleep protection are not turned off on entry during Sleep | PASS (no counter-evidence found) | No `light_turn_off` logged immediately following any `occupancy_entry` for Living Room in the window — the only `light_turn_off` rows are tied to `occupancy_exit`, as expected. |
| No URA errors at boot | PASS | `ha_get_logs(source=system_service, slug=core, search="universal_room_automation", hours_back=4)` → 0 lines (boot-health check at the 2026-10-10 15:52Z restart; postdates the observed night, included per the live-validation checklist) |

Net: all four of this README's own criteria hold on the observed night. The separate, room-specific sleep-protection night-light criterion belongs to v5.103.44 and is tracked there (not confirmed — see that README's table).
