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
