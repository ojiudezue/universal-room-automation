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

## Live validation (prospective)
- No URA errors at boot from automation / actuator_reconciler / lighting.
- `Use night lights by day` appears on a room's Lighting step, default off; colour fields only under Advanced.
- At dusk (house not Sleep), an occupied entry=none room with night lights (e.g. Living Room) turns its night light on; ura_activity_log shows one turn_on, not repeated.
- Tonight in Sleep: occupied rooms' night lights on; main lights stay off.
- Daytime, bright: no night light comes on in a room without the checkbox.
