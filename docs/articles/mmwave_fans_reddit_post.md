# Reddit post (r/homeassistant)

<!-- draft: true -->
<!-- Not a site article: this is the r/homeassistant crosspost that links BACK to /notes/mmwave-phantom-presence/ -->

**Title:** Found out why my mmWave sensors see ghosts: it's the exact second the fan changes speed

**Body:**

Came home to find my study fan had been running for 4 hours in an empty
room with the house in away mode. The mmWave sensor swore someone was in
there. PIR said nothing. Classic mmWave-plus-fan problem, but I wanted to
know the actual mechanism before "fixing" it by moving sensors around.

So I pulled a week of recorder history and wrote a quick script against
the sqlite db. Three things jumped out:

1. Both phantom events that week started at the exact second of a fan
speed change. Not "while the fan was on". The rising edge of the mmWave
sensor lined up to the second with the fan turning on or stepping speed.
Two different rooms, two different fan types (ceiling fan and a DC tower
fan).

2. Fans running at steady speed were innocent. Hours of constant-speed
fan in vacant rooms, zero phantoms. The radar apparently adapts to a
constant moving target. What it can't ignore is the change: spin-up,
spin-down, speed steps look like a new mover entering the room.

3. On sensors that expose LD2410 still_energy, the phantom has a
recognizable texture: tight low band (roughly 33 to 47) that drifts
slowly, while a real person is higher (median ~79) and much noisier.

I also went looking for whether any firmware handles this. Short answer
no. Fan blade rejection is still a research topic. Zone exclusion
polygons (LD2450 style) are the only hardware-side fix and they cost you
the coverage under the fan, which is where people actually sit.

The fix I landed on, no new hardware:

- If occupancy is about to be created on mmWave alone (no PIR, no BLE,
no camera) and the mmWave edge is within 5 seconds of a fan power or
speed change in that room, don't create it. 5 seconds is enough because
the alignment is to the second. A real person walking in usually trips
PIR or BLE anyway, and those are never blocked.
- If mmWave-only occupancy somehow persists under a running fan for 10+
minutes with stale PIR, release it and don't let mmWave alone re-create
it until something changes (mmWave drops, PIR fires, fan turns off).
- Separately: fan automations can't turn on from mmWave-only evidence
while the house is away. That's what let the original incident feed
itself (fan turns on, fan keeps mmWave excited, mmWave keeps room
occupied, room keeps fan on).

Each piece has a kill switch and a counter so I can see it working.
Since shipping it: the restart that used to recreate the incident now
does nothing, which is the correct nothing.

Main takeaway if you have this problem: check your recorder history
before moving sensors or masking zones. If your phantoms line up with
fan transitions like mine did, a short suppression window around fan
state changes is way cheaper than giving up mmWave coverage.

Longer writeup with the probe numbers and design notes:
[link to universalroom.org post]. The whole thing is part of an
open-source HA integration I've been running for 18 months
(https://github.com/ojiudezue/universal-room-automation).

Happy to share the recorder query if anyone wants to check their own
history for the transition alignment.
