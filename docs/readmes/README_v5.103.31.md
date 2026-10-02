# v5.103.31: night lights go red at sleep on colour lights

**Card:** `ROOM-LIGHTING-SETUP-REDESIGN-1` (operator 2026-10-02: "check the color we're using — some kind of red shade to deal with night wakefulness prevention. Check automations and URA").

**Finding:** the house's own HA night automations use deep red RGB (255, 30, 10) (7 uses, e.g. master toilet at 40 %). URA's sleep night lights used 2000 K — the warmest kelvin, but amber, not red; kelvin cannot produce red. All 21 rooms with night lights were on 2000 K.

**Change:** in Sleep mode, night lights that support colour (rgb/rgbw/rgbww/hs/xy) turn on in RGB (255, 30, 10); white-only lights keep the sleep colour temperature (2000 K). New per-room choice in Devices → "Night-light colour at sleep": Red (recommended, default) / Warm white. Day and evening night lights are unchanged; no defaults were added to the evening fields (operator: no defaults that change behaviour on save).

**Behaviour change:** colour-capable night lights in all rooms turn red at sleep from the next restart.

**Tests:** red on colour lights + white-only split, warm-white choice, never red in day mode; drill: disabling the red branch fails the red test.

**Live:** at the next sleep-mode entry in a room with a colour night light, the light shows rgb_color [255, 30, 10].
