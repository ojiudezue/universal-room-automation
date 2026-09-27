# AUDIT — HVAC raw-evidence gaps (CRIT-1 safety of "release at last raw evidence + tail")

**Date:** 2026-09-26 · **Card:** `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` · **Read-only measurement.**
**Probe:** `scripts/probes/hvac_raw_evidence_gap_probe.py`, run as
`ssh ha "python3 - --days 7 --end 2026-09-26T19:20:00Z --graces 300,600" < scripts/probes/hvac_raw_evidence_gap_probe.py`.
**Window:** 2026-09-19 23:16Z → 2026-09-26 18:20Z UTC. Excluded: everything after 19:20Z (the empty-house period) and
the 5 HA restarts (from `homeassistant_stop` to `homeassistant_start` + 15 min). **6.74 days** included; **82.4 h**
of day state (`home_day` / `home_evening`).
**Read first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (§3, C24).

## 0. The question

Today `_compute_hvac_occupied` (`hvac_zones.py:1048-1123`) follows the room's `STATE_OCCUPIED`. That value stays
True for the room's `occupancy_timeout` after the last raw evidence (`coordinator.py:3596-3621`). After that, the
per-room-type tail starts (`const.py:1219-1224`). The day tail is 60 s for every type except media_room, which gets
120 s through `DEFAULT_HVAC_VACANCY_HOLD`. So today a room stays HVAC-occupied for **timeout + tail** after its last
evidence, which is about 360 s for most rooms. The proposed fix releases at **last raw evidence + T**. The CRIT-1
question is how often a person who is still in the room gives no raw evidence for longer than T during the day. And
when that happens, how often could it actually send a zone to away while the person is there?

## 1. Method (what "gap", "MID", "risk" mean)

- **Evidence** is the union of the `on` intervals of every configured `motion_sensors`, `presence_sensors` and
  `occupancy_sensors` entity for the room (config read from `/config/.storage/core.config_entries`). A radar that stays
  `on` counts as continuous evidence. `unavailable` / `unknown` counts as no evidence.
- A **gap** is a stretch where every configured sensor is not `on`, with evidence on both sides of it.
- **MID-session gap:** evidence comes back in the same room within `occupancy_timeout`. This is the card's
  definition of "the person was still there". Lighting `STATE_OCCUPIED` never dropped, so **today's design never
  releases HVAC occupancy on a MID gap.** Every MID gap longer than T is therefore a *new* false release that the fix
  would add.
- **LATE-resume gap:** evidence comes back after `occupancy_timeout`, but soon enough (≤ timeout + current tail + G)
  that today's design could not have retreated the zone because of this room. The fix could. These gaps are
  **ambiguous**: they may be a still person, or a person who left and came back.
- **FR_T (false releases per day):** MID gaps longer than T, divided by 6.74 days.
- **ZR_T (zone-retreat risk):** the gap is longer than T + G. In addition, no *other* non-hallway room in the same
  HVAC zone had raw evidence anywhere in `[gap_start+T, gap_start+T+G]`. Those rooms' own evidence is extended by T,
  so they are modelled under the fixed design too. G is the zone vacancy grace, knob 48
  `number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes`. **Its recorder history shows 10 min for the whole
  window. It was set to 5 min at 2026-09-26 22:06Z, after the window ended.** Both G = 300 s (live now) and
  G = 600 s are reported. ZR is an **upper bound**: the model leaves out the up-to-5-min decision tick, which only
  delays a retreat.
- **Scope:** 33 rooms: every non-hallway room listed in `live_rooms` of `sensor.ura_hvac_coordinator_zone_N_status`.
  The 7 hallways are excluded, and so are Patio, Garage A and Garage B, which are in no zone.
- **Modality** comes from the device-registry model. **PIR** = "Motion sensor", "Smart Night Light-W",
  "Zigbee multi-function night light", "UP Sense" and the garage openers. Everything else is **radar**. That includes
  the HOBEIAN "Millimeter wave motion detection" (PIR + radar fused into one binary), Screek, Seeed/ESPHome, Meross
  MS600, the Inovelli mmWave dimmer and the bed-presence sensor.

## 2. Headline

| | T = 60 | T = 120 | T = 180 | T = 300 |
|---|---|---|---|---|
| **Day false room releases / day** (MID gaps > T, all rooms) | **71.7** | 42.3 | 27.2 | 11.0 |
| **Day zone-retreat risk, MID** (G = 300 s, 6.74 d) | **23** | 18 | 14 | **0** |
| Day zone-retreat risk, MID (G = 600 s) | 0 | 0 | 0 | 0 |
| **Day zone-retreat risk, LATE-resume** (ambiguous; G = 300 s) | 44 | 40 | 37 | 31 |
| Day zone-retreat risk, LATE-resume (G = 600 s) | 55 | 49 | 43 | 36 |

1. **Raw evidence goes quiet all the time while people are present.** A flat 60 s tail would drop about 72 room-level
   HVAC occupancies per day. Most of them are harmless, because another room in the zone keeps the zone occupied.
2. **Under the live 5-min grace, a 60 s tail would have retreated a zone about 23 times in 6.74 days (~3.4 per day)
   while that zone's only occupied room was in a MID gap.** 20 of the 23 are the **Kitchen** (zone_3). The others are
   Jaya Bedroom (2) and Master Bathroom (1). A room with a 300 s timeout **cannot** produce a MID-gap retreat at
   G = 300 s, because a MID gap is at most 300 s. The MID risk lives only in rooms with timeouts above 360 s.
3. **Under the 10-min grace that was live for the whole window, MID risk is 0 at every T.** Knob 48 was lowered from
   10 to 5 min at 22:06Z today. That change, combined with this fix, is what creates the MID risk.
4. **The LATE-resume class is larger (44 events per week at T = 60, G = 300) and 30 of them are the Kitchen.** These
   are gaps longer than the Kitchen's 600 s timeout that resumed within about 16 min. A BLE phone was in the room for
   only **1 of 44** of them. For all 30 Kitchen events, another room (often the patio) had evidence at the same time.
   These look more like leave-and-return trips than still people, but that cannot be proven from the data (§6).

## 3. Per room type (day)

MID gaps: count, percentiles in seconds, false releases per day at each T, and MID zone-retreat counts at G = 300.

| Room type | Rooms | MID n | p50 | p90 | p99 | max | FR60/d | FR120/d | FR180/d | FR300/d | ZR60 | ZR120 | ZR180 | ZR300 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bathroom | 7 | 256 | 39 | 306 | 728 | 836 | 15.6 | 9.5 | 6.7 | 3.9 | 1 | 1 | 0 | 0 |
| bedroom | 6 | 298 | 29 | 158 | 341 | 495 | 14.7 | 7.3 | 3.7 | 0.6 | 2 | 1 | 1 | 0 |
| closet | 6 | 9 | 32 | 204 | 204 | 204 | 0.3 | 0.3 | 0.3 | 0 | 0 | 0 | 0 | 0 |
| common_area | 8 | 499 | 51 | 281 | 579 | 603 | 34.6 | 21.2 | 13.4 | 6.2 | 20 | 16 | 13 | 0 |
| generic | 2 | 38 | 55 | 296 | 396 | 396 | 2.5 | 1.5 | 1.0 | 0.5 | 0 | 0 | 0 | 0 |
| infrastructure | 1 | 0 | – | – | – | – | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| media_room | 1 | 0 | – | – | – | – | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| utility | 2 | 98 | 24 | 187 | 386 | 386 | 4.0 | 2.5 | 1.5 | 0.3 | 0 | 0 | 0 | 0 |

For reference, night (home_night / sleep / waking): FR60/d by type is bathroom 1.5, bedroom 4.9, common 15.9,
utility 2.5. MID ZR60 at G = 300 is common 15 (Kitchen), utility 3 (Kitchen Pantry), bedroom 2 (Jaya), bathroom 1
(Jaya Bath). Night tails are 5–30 min (`const.py:1230-1242`), so these are not the operative risk at night.

## 4. Per modality (day)

| Modality | Rooms | MID n | p50 | p90 | p99 | max | FR60/d | FR120/d | FR180/d | FR300/d | ZR60 | ZR120 | ZR180 | ZR300 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PIR-only | 12 | 221 | 32 | 206 | 585 | 836 | 11.9 | 6.8 | 4.5 | 1.9 | **0** | 0 | 0 | 0 |
| PIR + radar | 2 (Kitchen, Exercise Room) | 213 | 45 | 442 | 592 | 603 | 14.4 | 10.7 | 7.9 | 5.6 | **20** | 16 | 13 | 0 |
| radar | 19 | 764 | 41 | 209 | 515 | 779 | 45.4 | 24.8 | 14.3 | 3.9 | 3 | 2 | 1 | 0 |

**The risky rooms are not the PIR-only rooms.** The PIR-only rooms (bathrooms, closets, pantry, laundry, vanity,
toilet) had **0** MID zone-retreat events at any T. They are short-visit rooms, and a long silence in them is usually
a real departure. The risk sits in the **Kitchen**: PIR (UP Sense) plus two radars, a 600 s timeout, a 12.9 % daytime
evidence duty cycle, and a MID p90 of 442 s. It also sits in two radar rooms, Jaya Bedroom (500 s timeout) and Master
Bathroom (900 s timeout). A radar does not guarantee continuity: the Living Room has 3 radars and still has the
highest FR60 of any room (17.4 per day).

## 5. Per room (day, rooms with MID gaps)

| Room | Zone | Type | Mods | Timeout | MID n | p50 | p90 | max | FR60/d | FR120/d | FR180/d | FR300/d | ZR60/120/180/300 (G=300) | LATE ZR60/120/180/300 (G=300) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Living Room | z1 | common | radar | 300 | 241 | 53 | 185 | 295 | 17.4 | 8.8 | 3.9 | 0 | 0/0/0/0 | 8/5/3/0 |
| Master Bedroom | z1 | bedroom | radar | 300 | 157 | 34 | 156 | 295 | 8.8 | 3.4 | 1.6 | 0 | 0/0/0/0 | 1/0/0/0 |
| Master Bathroom | z1 | bathroom | radar | 900 | 137 | 38 | 379 | 779 | 7.9 | 5.3 | 3.9 | 2.2 | 1/1/0/0 | 1/1/1/1 |
| Master Bath Toilet | z1 | bathroom | PIR | 300 | 63 | 30 | 130 | 288 | 3.1 | 1.2 | 0.5 | 0 | 0 | 0 |
| Oji Vanity | z1 | bathroom | PIR | 600 | 27 | 63 | 493 | 585 | 2.1 | 1.5 | 1.2 | 0.9 | 0 | 0 |
| Study B | z1 | generic | radar | 300 | 25 | 44 | 221 | 296 | 1.3 | 0.6 | 0.5 | 0 | 0 | 0 |
| Study A | z1 | generic | radar | 540 | 13 | 67 | 387 | 396 | 1.2 | 0.9 | 0.6 | 0.5 | 0 | 0 |
| Jaya Bedroom | z2 | bedroom | radar | 500 | 124 | 22 | 176 | 495 | 4.9 | 3.1 | 1.8 | 0.6 | 2/1/1/0 | 1/1/1/0 |
| Jaya Bathroom | z2 | bathroom | PIR | 900 | 18 | 151 | 641 | 836 | 2.1 | 1.3 | 1.2 | 0.7 | 0 | 1/1/1/1 |
| Game Room | z2 | common | radar | 540 | 17 | 56 | 353 | 445 | 1.2 | 0.7 | 0.6 | 0.3 | 0 | 0 |
| Ziri Bedroom | z2 | bedroom | radar | 500 | 6 | 62 | 209 | 209 | 0.5 | 0.2 | 0.2 | 0 | 0 | 0 |
| Guest Bedroom 2 | z2 | bedroom | radar | 300 | 4 | 123 | 132 | 132 | 0.3 | 0.3 | 0 | 0 | 0 | 0 |
| Exercise Room | z2 | common | PIR+radar | 900 | 4 | 43 | 603 | 603 | 0.2 | 0.2 | 0.2 | 0.2 | 0 | 0 |
| **Kitchen** | z3 | common | PIR+radar | 600 | 210 | 47 | 442 | 600 | 14.4 | 10.7 | 7.9 | 5.5 | **20/16/13/0** | **30/30/29/28** |
| Kitchen Pantry | z3 | utility | PIR | 500 | 60 | 33 | 206 | 386 | 3.1 | 2.1 | 1.2 | 0.3 | 0 | 0 |
| Laundry | z3 | utility | PIR | 300 | 38 | 17 | 77 | 289 | 0.9 | 0.5 | 0.3 | 0 | 0 | 0 |
| Dining Room | z3 | common | radar | 300 | 16 | 15 | 270 | 282 | 0.7 | 0.6 | 0.6 | 0 | 0 | 2/2/2/1 |
| Breakfast Nook | z3 | common | radar | 480 | 9 | 94 | 411 | 411 | 0.9 | 0.5 | 0.5 | 0.3 | 0 | 0 |
| Guest Bedroom 1 | z3 | bedroom | radar | 300 | 6 | 52 | 298 | 298 | 0.3 | 0.3 | 0.2 | 0 | 0 | 0 |

Rooms with fewer than 6 MID gaps and no risk are left out: the closets, Guest Bedroom 1/2 bathrooms, Ziri Bathroom,
Butler Pantry, Laundry Closet and Guest Bedroom 1 Closet. The full output comes from the probe.

## 6. Cross-checks: was the person really still there?

- **Living Room camera (the only room with a URA camera person sensor that fires).**
  `binary_sensor.living_room_camera_person_detected` was `on` during **64 of 117** day MID gaps longer than 60 s
  (55 %), 32 of 59 longer than 120 s, and 15 of 26 longer than 180 s. So the camera saw a person while all three
  Living Room radars were off. This is direct evidence that radars miss still people. It is not an artifact of the
  gap definition. Adding the camera to the evidence only lowers Living Room FR60 from 17.4 to 12.0 per day, because
  the camera's `on` pulses are brief as well. The Living Room's MID ZR is still 0 at G = 300, because its gaps are
  capped by its 300 s timeout.
- **BLE phones** (`sensor.iphone_oji_area`, `sensor.ezinne_iphone_area`, `sensor.iphone_jaya_area`; Ziri's is
  `unknown`). A phone was in the room for at least 50 % of the gap in **2 of 23** MID risk events (both Jaya in the
  Kitchen) and **1 of 44** LATE events (Ezinne in the Master Bedroom). Phones are often `unknown`, so this
  undercounts.
- **Evidence elsewhere.** All 30 Kitchen LATE events had evidence in another room (most often the Patio) during the gap. The
  Patio signal is weak, though: the Patio radar is `on` for **65 %** of the day. The Master Bedroom and Jaya Bedroom
  radars are each `on` for about **45 %** of the day, which is consistent with fan-driven or phantom radar.
- **Sensor unavailability** touched 8 of 96 Kitchen day MID gaps longer than 60 s (the ESPHome kitchen radar changes
  availability often: 346 `unavailable` rows in 7 d), 3 of 59 in the Master Bedroom and 3 of 9 in Study B. It touched
  1 of 23 MID risk events and 6 of 44 LATE events. Production grace-holds through unavailability, so those events
  overstate the risk slightly.

## 7. Recommended day tail per room type (G = 300 s live)

The rule: choose the smallest T at which **MID zone-retreat risk = 0** in this sample. Within that, keep the
LATE (ambiguous) risk small. A room-level false release on its own is harmless. Only a zone retreat hurts.

A MID gap can only retreat a zone if gap > T + G. So T must be at least (max MID gap − G) for the rooms that can be
the only occupied room in their zone.

| Room type | Max day MID gap | T ≥ max − 300 | **Recommended T** | MID ZR at rec. T | LATE ZR at rec. T (G = 300) | vs today (timeout + tail) for a 300 s room |
|---|---|---|---|---|---|---|
| closet / infrastructure / generic | 204 / – / 396 | ≥ 0 / – / ≥ 96 | **60 s** (generic 120 s) | 0 | 0 | 360 → 60–120 s |
| utility (pantries, laundry) | 386 | ≥ 86 | **120 s** | 0 | 0 | 360 → 120 s |
| bathroom | 836 (Jaya Bath; no retreat, zone occupied) | measured ZR = 0 from 180 | **180 s** | 0 | 2 (Master Bath 1241 s, Jaya Bath 1051 s; phones elsewhere) | 360 → 180 s |
| bedroom | 495 (Jaya Bedroom, phone in the en-suite) | ≥ 195 | **240 s** | 0 | ≤ 1 | 360 → 240 s |
| common_area | 603 | ≥ 303 | **300 s** | 0 | 1 (Dining), **plus Kitchen 28** | 360 → 300 s |
| media_room | no data | – | keep 120 s | – | – | – |
| **Kitchen (per-room exception)** | 600 | ≥ 300 | **keep today's behaviour (timeout + 60 = 660 s)** until the ambiguous gaps are resolved | 0 at 300 | 28 at T = 300; 0 only at T ≥ ~660 | no change |

- With these tails and the Kitchen exception, the day zone-retreat risk becomes **MID 0 and LATE about 3–4
  (ambiguous) per week**. Today the equivalent figure is 0 by construction.
- **Marginal benefit (per the pushback rule).** The fix helps most in the short-visit rooms: closets, pantries,
  laundry and bathrooms. That is where transit flips happen, and where a 60–180 s tail is safe. For bedrooms and
  common areas, the safe T is 240–300 s. That saves only 60–120 s against today's 360 s in a 300 s-timeout room.
  For the Kitchen, no shortening is safe on this evidence. **For common_area and bedroom, the fix buys too little to
  justify a CRIT-1 revisit.** A per-type release (short for PIR and short-visit types, today's behaviour for
  common_area and bedroom) captures most of the benefit. Transit arming is handled separately by Stage B (arming-edge
  persistence, C24).
- **If knob 48 goes back to 10 min, MID risk is 0 at every T.** The LATE risk (G = 600) is 55/49/43/36, driven by the
  Kitchen. A shorter grace and shorter tails together create the MID risk; neither does on its own. Any build should
  size T with the grace, not in isolation. For example, derive the release as `max(T_type, max_mid_gap − G)` per room.
- **Implementation note (read in the source, not measured).** `_last_motion_time` is refreshed only while a raw sensor
  is `on` (`coordinator.py:3589`). The camera and BLE overrides only seed it when it is unset (`coordinator.py:3680`,
  `:3867`). A fix keyed on `_last_motion_time` would therefore **drop camera- and BLE-held occupancy** that today's
  `STATE_OCCUPIED` holds. The Living Room camera evidence above shows that this matters.

## 8. What I could not measure

1. **Ground truth of presence.** "MID" (evidence resumed within the timeout) is the card's proxy for "still
   there". It cannot tell a still person from a short leave-and-return trip, so FR and ZR are upper bounds for the
   still-person harm. For the same reason, LATE events cannot be settled either way. Only the Living Room has a
   camera. BLE covers 3 people, phones are often `unknown`, and a phone left behind would look like presence.
2. **Rooms with almost no evidence.** Receiving Room (2 `on` events in 7 d, while Oji's phone reported
   `Receiving Room` often), Media, Study A Closet, AV Closet, Stair Closet and Media Room Closet had 0 MID gaps. The
   probe says nothing about them. **The Receiving Room sensor
   `binary_sensor.occupancy_lux_temp_humidity_hobeian_receiving_presence` looks deaf.** That is a separate sensor
   health finding, and it affects today's behaviour too.
3. **Production fusion filters are not modelled.** Stuck-sensor exclusion (`_fusion_filter_active`), the
   fan-transition gate, the mmWave-demoted latch, the unavailability `grace_hold`, and the camera and BLE `STATE_OCCUPIED`
   overrides are all left out. Phantom radars (Patio 65 %, Master and Jaya Bedroom about 45 % duty) make their rooms
   look *more* continuous than production may see them. That understates gaps in those rooms.
4. **The 5-min decision tick is not modelled**, so ZR is an upper bound. D5 energy-shed and other readers of the
   fused signal that bypass the gate (state-of-play §3.2) are also not modelled.
5. **Sample size.** 6.74 days. The Kitchen is 20 of the 23 MID risk events and 30 of the 44 LATE events. Per-room
   counts outside the Kitchen are single digits.
6. **Other house states.** `away`, `arriving` and `guest` time is left out of both the day and the night buckets.

