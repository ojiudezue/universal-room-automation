# Audit: person->home to garage-door-open gap (2026-11-05 .. 2026-11-12 14:2x CST)

Read-only recorder probe (`/config/home-assistant_v2.db` via `ssh ha`, times CST). Run 2026-11-12.

## Method
- Person edge = `person.{oji_udezue,jaya,ezinne,ziri}` state not_home->home (unavailable/unknown skipped as prior state). 118 raw edges; **78 dropped as reverting within 10 s** (applied to all four people, not only Oji's iPad), leaving 40 settled edges.
- Garage A door = `cover.konnected_f0f5bd523b00_garage_door` (Garage A per docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.2.md:386), first transition into `opening` (the cover repeats `opening` every ~0.5 s while moving; collapsed to the first). 42 opens.
- Garage B door = `binary_sensor.openclose_zigbee_garageb_contact` going `on`. Only 8 `on` rows, all 11-12 13:43-13:44 (suspect; see caveats).
- Match = door opened 0..600 s after the edge. Tracker = person `source` attribute at the edge. Bermuda first-area: not extracted (unknown).

## Garage arrivals (27 person-door pairs)
| person | person->home | garage | door open | gap s | edge tracker |
|---|---|---|---|---|---|
| oji | 11-05 08:30:53 | A | 08:31:03 | 9.5 | phalanxiphone15promaxcflare |
| oji | 11-05 18:24:38 | A | 18:30:32 | 353.8 | phalanxiphone15promaxcflare |
| oji | 11-05 22:40:29 | A | 22:40:38 | 9.0 | phalanxiphone15promaxcflare |
| oji | 11-06 09:01:15 | A | 09:01:22 | 6.4 | private_ble_device_8ce182 |
| ezinne | 11-06 17:33:36 | A | 17:34:22 | 45.7 | zinny_s_iphone_15 |
| oji | 11-06 22:06:01 | A | 22:07:25 | 83.8 | phalanxiphone15promaxcflare |
| jaya | 11-06 22:06:09 | A | 22:07:25 | 75.8 | iphone_jaya_bermuda_tracker |
| ezinne | 11-06 22:06:15 | A | 22:07:25 | 69.8 | zinny_s_iphone_15 |
| ziri | 11-06 22:29:55 | A | 22:31:20 | 85.0 | ziri_iphone |
| ezinne | 11-07 10:33:25 | A | 10:33:46 | 20.9 | zinny_s_iphone_15 |
| jaya | 11-07 10:33:28 | A | 10:33:46 | 17.4 | private_ble_device_249050 |
| ziri | 11-07 10:33:30 | A | 10:33:46 | 16.1 | ziri_iphone |
| oji | 11-07 12:13:49 | A | 12:14:34 | 44.2 | phalanxiphone15promaxcflare |
| ziri | 11-07 17:40:30 | A | 17:40:49 | 19.1 | ziri_iphone |
| ezinne | 11-07 18:11:28 | A | 18:11:47 | 19.2 | zinny_s_iphone_15 |
| oji | 11-07 18:11:28 | A | 18:11:47 | 19.0 | phalanxiphone15promaxcflare |
| ezinne | 11-07 23:43:40 | A | 23:43:56 | 16.3 | zinny_s_iphone_15 |
| jaya | 11-07 23:43:54 | A | 23:43:56 | 1.9 | private_ble_device_249050 |
| ziri | 11-08 00:30:07 | A | 00:30:18 | 10.8 | ziri_iphone |
| ezinne | 11-08 13:58:51 | A | 13:58:57 | 6.0 | ezinne_iphone |
| oji | 11-08 13:58:51 | A | 13:58:57 | 5.9 | private_ble_device_8ce182 |
| jaya | 11-08 17:40:47 | A | 17:41:00 | 13.5 | iphone_jaya_bermuda_tracker |
| ziri | 11-08 17:40:48 | A | 17:41:00 | 12.2 | ziri_iphone |
| ezinne | 11-09 08:42:17 | A | 08:45:13 | 175.5 | zinny_s_iphone_15 |
| ezinne | 11-11 08:24:51 | A | 08:25:11 | 19.9 | zinny_s_iphone_15 |
| ezinne | 11-12 13:37:49 | A | 13:38:07 | 18.3 | zinny_s_iphone_15 |
| ezinne | 11-12 13:37:49 | B | 13:43:27 | 337.4 | zinny_s_iphone_15 (B sensor suspect) |

Stats (all 27): min 1.9 s, median 19.0 s, max 353.8 s; under 5 s: 1; under 10 s: 6 (1.9, 5.9, 6.0, 6.4, 9.0, 9.5).
Distinct arrivals (people sharing one door-open collapsed) are ~18 vehicle events; per-event the edge-to-open lead is typically 6-20 s, i.e. person->home usually precedes door open by a short margin. Cars with multiple occupants show the same door-open with several people edges.
Note: all gaps are positive by construction (edge before open). Cases where home preceded open by only a few seconds (1.9-9.5 s) are the ones where an arrival-triggered action cannot beat the door.

## Front-door lock (`lock.doorlock_kwikset_zwave_frontentry` -> unlocked)
8 unlocks since 11-05 (first row 11-06 13:28; no earlier). **0 fell within 10 min after a settled person edge.** No gap stats.

## Caveats
- Garage B: contact sensor shows `on` only 8 times, all within 70 s on 11-12 13:43-13:44; Garage A contact (`openclose_zigbee_garageadoor1_contact`) only ever `on`/unavailable (appears stuck), so not used. B door coverage is effectively nil; the B row is likely not a real arrival (Ezinne's A arrival was 5 min earlier).
- Unrestricted revert filter (78 dropped) was applied to every person, not only Oji; Oji-only iPad blips were not separated out.
- Bermuda first-area not extracted (unknown); tracker is the person `source` attribute at the edge.
- Konnected cover logged 1046 `opening` rows (0.5 s repeats during travel), collapsed here.
