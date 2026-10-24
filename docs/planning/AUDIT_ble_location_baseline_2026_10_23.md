# AUDIT: BLE person-location quality baseline (2026-10-23)

Read-only measurement. Nothing was changed. Prepared by ura-prober, 2026-10-23 18:40 CDT (`date`).
Read first (completely): `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.

## 0. Headline

- Raw Bermuda area for the three BLE-tracked residents flips a lot: **Oji 76/h, Jaya 62/h, Ezinne 36/h** room-to-room changes while the phone is placed (day 07-22 is 1.5x to 8x the night rate). 88% / 90% / 87% of Oji / Jaya / Ezinne changes leave a stay shorter than 60 s.
- Floor jumps: Oji 1.9/h, Ezinne 1.5/h, Jaya 3.1/h (Jaya daytime 8.1/h). Dominant cross-floor pair is **Jaya Bedroom (2nd floor) <-> Garage A (1st floor)**, and it appears for all three phones.
- The top flap pair is **Jaya Bathroom <-> Jaya Bedroom (2,188 quick transitions; 2,174 are A-B-A bounces)**, same floor, almost all Jaya. Top 10 pairs are all same-floor.
- Night (00-06 CDT) is mostly a hold, but not always: on nights 10-19 / 10-20 Oji and Jaya show 460-760 transitions in 6 h; Oji drifted to Kitchen / Receiving Room for ~3.4 h on 10-20. Jaya Bathroom is the only Jaya drift target (10% of night minutes).
- Radar witness agreement is good where the radar can hold the person and the phone is stable (Study A 97-99%), mediocre elsewhere (Kitchen 56-81%, Master Bedroom ZX 33-63%, Jaya Bedroom ZK 27-43%). Radar misses are a mix of BLE error and still-person radar drop; this audit cannot separate them (see caveats).
- URA's resolved `sensor.universal_room_automation_<p>_location` changes about 3.5x less often than the raw Bermuda area, so the smoothing already in URA is real. This audit measures the raw layer.

## 1. Method

- Source: HA recorder `/config/home-assistant_v2.db` on `ssh ha`, opened `mode=ro`. Registry from `/config/.storage/core.{area,floor,entity}_registry` and `core.config_entries` (only URA room option lists and Shelly `ble_scanner_mode` were read; no secrets printed).
- Window: **2026-10-16 18:39 CDT to 2026-10-23 18:39 CDT (168 h)**. Recorder `purge_keep_days: 7` (`~/ha-config/configuration.yaml`), so no longer window exists.
- Times: CDT (UTC-5). Day = 07:00-21:59, night = 22:00-06:59 for the rate split. The drift section uses 00:00-05:59.
- Person to entity (producer: Bermuda area sensor, whose state is the area name; consumer: URA `person_coordinator`, see STATE_OF_PLAY section 3):
  - Oji `sensor.iphone_oji_area`; Ezinne `sensor.ezinne_iphone_area`; Jaya `sensor.iphone_jaya_area`.
  - Ziri `sensor.iphone_ziri_area` is `unknown`/`unavailable` for the whole window (20 rows, no numeric distance rows). **Ziri has no usable BLE data in this window**; not measured.
- Series collapse: consecutive equal states merged (attribute-only rows such as `current_mac` ignored). `unknown`/`unavailable` is a gap, not a room. A transition counts only when both neighbours are real areas. Denominator is "observed hours" (time with a real area), because phones were absent for long stretches (Oji known 101.2 h, Ezinne 53.3 h, Jaya 89.9 h of 168 h; operator travel 10-14 to 10-18 per memory, other gaps unexplained, e.g. Ezinne nights 10-21/22).
- Floors: area name to `floor_id` via area registry (First Floor / Second Floor / Outside). All areas the phones were placed in had a floor.
- Radar witness: ZK/ZX presence radars per `SENSOR_FLEET_CLASSES.md`, entity found in `core.config_entries` URA room options. Minute grid, BLE state sampled at minute midpoint. "strict" = radar `on` at that instant; "tol60" = radar `on` at any time within +/-60 s of the minute. Reverse check: radar-on minutes with any of the 3 BLE residents in that room.
- Scripts: scratchpad `main.py`, `extra.py`, `z.py` (not committed). Earlier draft of the radar join sampled only minutes fully inside a segment and under-counted flappy periods; it was replaced by midpoint sampling (`z.py`), and the numbers below are from that.

## 2. Area-entity changes, floor jumps, short stays (per observed hour)

| Person | Observed h (day / night) | Changes total | /h overall | /h day | /h night | Floor jumps (/h overall, day, night) | Stays <30 s (/h overall, day, night) | Changes after stay <60 s |
|---|---|---|---|---|---|---|---|---|
| Oji | 101.2 (58.3 / 42.9) | 7,695 | 76.1 | 91.3 | 55.4 | 195 (1.9, 2.9, 0.65) | 5,992 (59.2, 72.5, 41.1) | 6,763 (88%) |
| Ezinne | 53.3 (28.2 / 25.0) | 1,897 | 35.6 | 60.6 | 7.5 | 80 (1.5, 2.7, 0.12) | 1,480 (27.8, 48.7, 4.2) | 1,657 (87%) |
| Jaya | 89.9 (30.7 / 59.2) | 5,592 | 62.2 | 101.3 | 41.9 | 278 (3.1, 8.1, 0.49) | 4,443 (49.4, 80.7, 33.2) | 5,015 (90%) |
| Ziri | 0 | no BLE data | | | | | | |

Notes: night-rate per hour is dominated by a few bad nights (section 6), not uniform. "Stays <30 s" counts closed stays between two state changes inside the window.

### URA-resolved layer, for comparison (`sensor.universal_room_automation_<p>_location`)

Restricted to values that exactly match an area name (names such as `Breakfast Nook`, `Media`, `Powder` do not match registry names `Breakfast`, `Media Room`, `Guest Toilet` and are dropped, so this under-counts a little).

| Person | Room-hours | Changes (/h) | Floor jumps | Stays <30 s |
|---|---|---|---|---|
| Oji | 99.9 | 2,029 (20.3) | 64 | 601 |
| Ezinne | 52.2 | 379 (7.3) | 15 | 141 |
| Jaya | 86.0 | 1,018 (11.8) | 84 | 305 |

## 3. Readings per minute and scanners hearing each person

Producer: Bermuda per-scanner `sensor.<phone>_distance_to_<scanner>` (filtered). The unfiltered variants are recorder-excluded (`configuration.yaml`, 2026-09-28 note), so raw advertisement rate is not derivable. Each recorder row is a state change of the rounded distance, not a raw advert, so rows/min is a **lower-bound proxy** for reading rate.

| Person | Distinct scanner entities recorded | Rows/min (whole 168 h) | State changes per active minute (median / p90) | Distinct scanners updating per active minute (p10 / median / p90 / max) |
|---|---|---|---|---|
| Oji | 7 | 4.1 | 30 / 38 | 3 / 3 / 5 / 7 |
| Ezinne | 57 (55 with data) | 38.2 | 259 / 309 | 22 / 30 / 35 / 53 |
| Jaya | 57 (55 with data) | 82.8 | 299 / 425 | 27 / 29 / 44 / 53 |
| Ziri | 47 | 0.09 (all unknown) | n/a | n/a |

- **Oji is not comparable.** The entity registry shows ~50 of Oji's per-scanner distance entities `disabled_by: integration` (Bermuda creates only a subset by default); only 7 are enabled and recorded. Oji's 3 scanners/min is a floor, not the number of scanners hearing him. Ezinne and Jaya have essentially all scanners enabled. Whether the enablement difference is deliberate: unknown.
- Both Ezinne and Jaya are heard by ~30 scanners per active minute (fleet is ~55 named scanners, includes Shelly, ESPHome, Screek, Z2M-less wired devices). Count of scanners per person is therefore not the limiting factor for them; Bermuda's selection / hysteresis among many scanners is the question for the flapping below.
- `sensor.iphone_oji_nearest_rssi` 65,074 rows and `sensor.ezinne_iphone_nearest_rssi` 39,531 rows over the window (about 6.5 and 3.9 rows/min if spread over 168 h).

## 4. Top 10 flapping pairs (leaving a stay of <60 s), all three phones pooled

"Quick transitions" = X to Y where the stay in X lasted under 60 s. "A-B-A bounces" = a short B stay between two stays in A. Total quick transitions across all pairs: 13,401, of which 497 (3.7%) cross floors.

| # | Pair | Floors | Cross-floor | Quick transitions | A-B-A bounces | By person |
|---|---|---|---|---|---|---|
| 1 | Jaya Bathroom / Jaya Bedroom | 2nd / 2nd | no | 2,188 | 2,174 | Jaya 2,184, Oji 4 |
| 2 | Foyer / Study A | 1st / 1st | no | 1,285 | 1,148 | Oji 1,277, Ezinne 8 |
| 3 | Living Room / Receiving Room | 1st / 1st | no | 894 | 636 | Oji 475, Ezinne 397, Jaya 22 |
| 4 | Master Bathroom / Master Bedroom | 1st / 1st | no | 820 | 608 | Oji 775, Ezinne 45 |
| 5 | Breakfast / Kitchen | 1st / 1st | no | 706 | 423 | Jaya 536, Oji 126, Ezinne 44 |
| 6 | Breakfast / Patio | 1st / 1st | no | 544 | 343 | Jaya 464, Oji 42, Ezinne 38 |
| 7 | Kitchen / Receiving Room | 1st / 1st | no | 492 | 267 | Oji 340, Ezinne 76, Jaya 76 |
| 8 | Kitchen / Patio | 1st / 1st | no | 448 | 218 | Jaya 375, Oji 58, Ezinne 15 |
| 9 | Foyer / Receiving Room | 1st / 1st | no | 376 | 254 | Oji 304, Ezinne 53, Jaya 19 |
| 10 | AV Closet / Master Bedroom | 1st / 1st | no | 308 | 195 | Oji 241, Ezinne 67 |

Cross-floor pairs (all transitions, not only quick), top: Garage A / Jaya Bedroom 101 + 90 (Oji 75, Ezinne 38, Jaya 78 across both directions), Jaya Bedroom / Guest Toilet 48 + 34, Laundry / Jaya Bedroom 36 + 30, Jaya Bedroom / Guest Bedroom 1 Bathroom 23 + 22, Media Room / Kitchen 19 + 17. The same Jaya Bedroom to ground-floor pattern shows up for Oji's and Ezinne's phones, which points at a scanner (the `jaya_3` ESPHome proxy (Jaya Bedroom) is among Jaya's two highest-count scanners, with `ziri_3`) hearing phones that are downstairs; this is a hypothesis from the pair data, not tested.

## 5. Radar witness agreement (ZK/ZX per fleet doc)

Radar entities: Study A ZK `binary_sensor.mmwave_zigbee_studya_presence`; Jaya Bedroom ZK `…jayabedroom_presence`; Ziri Bedroom ZK `…ziribedroom_presence`; Exercise Room ZK `binary_sensor.mmwave_zigbee_gameroom_presence`; Living Room ZX `…zigbee_livingroom_presence`; Kitchen ZX `…zigbee_kitchen_presence`; Master Bedroom ZX `…zigbee_masterbedroom_presence`.

Radar on-time in window: Study A 32.3 h (19.2%), Jaya Bedroom 20.7 h (12.3%), Master Bedroom 23.9 h (14.2%), Kitchen 16.9 h (10.1%), Living Room 8.2 h (4.9%), Ziri Bedroom 0.11 h, Exercise Room: **zero recorder rows** (never changed state; matches the 2026-10-18 note).

BLE says person is in room X: % of those minutes that radar X is on.

| Room (radar) | Person | BLE minutes | strict | tol60 | day 07-22 tol60 | night 22-07 tol60 |
|---|---|---|---|---|---|---|
| Study A (ZK) | Oji | 1,296 | 97% | 99% | 100% | 95% |
| Master Bedroom (ZX) | Oji | 2,229 | 45% | 60% | 83% | 53% |
| Master Bedroom (ZX) | Ezinne | 2,485 | 33% | 50% | 31% | 63% |
| Jaya Bedroom (ZK) | Jaya | 3,706 | 27% | 43% | 63% | 39% |
| Kitchen (ZX) | Jaya | 483 | 75% | 81% | 80% | 100% (23 min) |
| Kitchen (ZX) | Oji | 378 | 56% | 64% | 84% | 22% |
| Kitchen (ZX) | Ezinne | 150 | 57% | 63% | 63% | n/a |
| Living Room (ZX) | Oji | 181 | 58% | 61% | 65% | 36% |
| Living Room (ZX) | Ezinne | 143 | 50% | 53% | 53% | n/a |
| Jaya Bedroom (ZK) | Oji | 75 | 7% | 16% | 0% | 33% |
| Ziri Bedroom, Exercise Room | any | 0 | no BLE minutes in those rooms | | | |

Reverse (radar on, minutes with any of the 3 BLE residents in that room): Master Bedroom 1,032/1,073 (96%); Jaya Bedroom 756/940 (80%); Study A 1,226/1,833 (67%); Kitchen 572/879 (65%); Living Room 160/445 (36%). Radar-on without a BLE resident is expected for Ziri (no BLE), guests, and fan/phantom holds (Study A false holds are a documented issue, STUDYA-ZK-EMPTY-HOLD-1).

Reading the table: Study A high agreement means Oji's BLE is stable there and the ZK holds him. Master Bedroom ZX and Jaya Bedroom ZK disagree often, but both rooms are sleep rooms where a still person can drop a radar (fleet doc: ZK/ZX hold a still person, but this was measured as low on-time here), and Ezinne's daytime 31% is consistent with a phone left in the room. Union of the Master Bedroom witnesses (ZX, Screek, Inovelli, both bed sensors) during Oji's 00-06 BLE=Master Bedroom minutes: 1,198/1,232 (97%); for Jaya Bedroom (ZK + `jaya_3` LD2410) with Jaya BLE=Jaya Bedroom 00-06: 1,102/2,252 (49%).

## 6. Night behaviour 00:00-05:59 CDT

Per-night (hours in each area; known = real area):

| Person | Night | Known h | Main area | Other areas (h) | Changes | Floor jumps |
|---|---|---|---|---|---|---|
| Oji | 10-17, 10-18 | 0 | phone absent | | | |
| Oji | 10-19 | 6.0 | Master Bedroom 3.32 | Master Bathroom 1.49, Study A 0.54, Ezinne Makeup 0.27, AV Closet 0.10 | 459 | 0 |
| Oji | 10-20 | 6.0 | Kitchen 1.84 | Receiving Room 1.53, Master Bedroom 0.64, Study A 0.60, Jaya Bedroom 0.37 | 682 | 12 |
| Oji | 10-21 | 6.0 | Master Bedroom 6.00 | none | 0 | 0 |
| Oji | 10-22 | 6.0 | Master Bedroom 5.69 | Master Bathroom 0.21 | 145 | 0 |
| Oji | 10-23 | 6.0 | Master Bedroom 4.86 | Master Bathroom 0.70, Ezinne Makeup 0.22, AV Closet 0.21 | 471 | 0 |
| Ezinne | 10-19 | 6.0 | Master Bedroom 5.98 | AV Closet 0.02 | 76 | 0 |
| Ezinne | 10-20 | 6.0 | Master Bedroom 5.99 | none material | 10 | 0 |
| Ezinne | 10-23 | 6.0 | Master Bedroom 5.98 | Study B 0.02 | 36 | 0 |
| Ezinne | 10-17, 10-18, 10-21, 10-22 | 0 | phone absent | | | |
| Jaya | 10-17 | 5.8 | Jaya Bedroom 5.79 | trivial | 35 | 3 |
| Jaya | 10-18 | 6.0 | Jaya Bedroom 5.98 | Jaya Bathroom 0.02 | 12 | 0 |
| Jaya | 10-19 | 6.0 | Jaya Bedroom 3.78 | Jaya Bathroom 2.22 | 620 | 0 |
| Jaya | 10-20 | 6.0 | Jaya Bedroom 3.99 | Jaya Bathroom 2.00 | 763 | 0 |
| Jaya | 10-21 | 6.0 | Jaya Bedroom 5.93 | Jaya Bathroom 0.07 | 158 | 0 |
| Jaya | 10-22 | 6.0 | Jaya Bedroom 6.00 | none | 0 | 0 |
| Jaya | 10-23 | 6.0 | Jaya Bedroom 6.00 | none | 6 | 0 |

Drift summary (00-06 minutes, midpoint sampling, `z.py`):

| Person | Night minutes known | In usual sleep room | Drift minutes | Drift destinations (minutes) |
|---|---|---|---|---|
| Oji | 1,800 | 1,232 Master Bedroom (68%) | 568 (32%) | Master Bathroom 152, Kitchen 115, Receiving Room 96, Study A 66, Ezinne Makeup 34, AV Closet 22, Jaya Bedroom 22, Living Room 17, Foyer 11, Media Room 10, others <10 |
| Ezinne | 1,080 | 1,077 Master Bedroom (99.7%) | 3 | Study B 3 |
| Jaya | 2,510 | 2,252 Jaya Bedroom (90%) | 258 (10%) | Jaya Bathroom 256, Foyer 1, Butler Pantry 1 |

Interpretation limits:
- Oji and Ezinne share the Master Bedroom, so its witnesses stay on whatever Oji does; "witness on during Oji drift 564/568" cannot discriminate. Ezinne's phone, one room, holds all night on the three nights it was present, so the hold is achievable on this fleet.
- Oji's drift is concentrated on 10-19, 10-20, 10-23 (large change counts); 10-21 was a single hold. 10-20 putting Oji in Kitchen / Receiving Room for ~3.4 h at night is more consistent with either a real overnight wander or a phone left on a counter than with a second-floor jump; the data cannot say which. Not tested against Oji's own motion/lights.
- Jaya: while BLE said Jaya Bathroom (256 min), the Jaya Bedroom radars (ZK or LD2410) were on in 135 of 258 minutes (52%). Bathroom visits are real, but 10-19 and 10-20 show 2.0-2.2 h in the bathroom with 620-763 changes, which is a bedroom/bathroom flap (pair #1) rather than a 2-hour bathroom stay. Ground truth for that: Jaya Bathroom PIR `binary_sensor.pir_zigbee_jayabathroom_occupancy`; not queried here.

## 7. Scanner configuration (read from files / storage)

### ESPHome Bluetooth proxies (`~/ha-config/esphome/*.yaml`, non-archive, with `bluetooth_proxy`)

All have `bluetooth_proxy: active: true` except where noted. "defaults" = no `scan_parameters` block, so ESPHome's own defaults apply (value of those defaults not verified in this audit).

| File | esp32_ble_tracker scan_parameters |
|---|---|
| `apollo-air-1-a87420.yaml` | `active: false` (proxy `active: true`) |
| `jaya-3.yaml` | none (defaults) |
| `ziri-3.yaml` | none (defaults) |
| `konnected-523b00.yaml` | none (defaults) |
| `mmwave-lux-wifi-esphome-kitchen.yaml` | none (defaults) |
| `mmwave-lux-wifi-esphome-studyb.yaml` | none (defaults) |
| `ojifirstble-proxy.yaml` | `active: true` (comment: defaults kept so BLE can co-exist with WiFi) |
| `screek-bp1-a.yaml` | `active: true` (same comment) |
| `screek-bp1-b.yaml` | `active: true` (same comment) |
| `mmwave-lux-ble-screekld241s-mas.yaml` | no `esp32_ble_tracker` key in file; `bluetooth_proxy: active: true` only |
| `screekld2412-livingroom.yaml` | no `esp32_ble_tracker` key in file; `bluetooth_proxy: active: true` only |

No file sets `interval` or `window`. Not read: `archive/`, `secrets.yaml`.

### Shelly BLE scanner mode (`core.config_entries`, shelly domain, option `ble_scanner_mode`)

49 Shelly config entries: **37 `auto`, 5 `passive`, 7 unset** (the 7 are non-BLE types: Dimmer2, Flood G4, 5 H&T). Passive entries: `shelly1pmminig3-e4b063f68b9c`, `-e4b063f75f24`, `shelly1pmminig4-d885acf0520c`, `shelly2pmg3-b08184f5b920`, `-b08184f5b928`. What `auto` means in the Shelly integration (and whether it resolves to active or passive on a given device) was not verified here.

## 8. Caveats

1. Window is 7 days and contains operator travel (10-14 to 10-18 per memory) and long phone-absent gaps; per-hour rates use observed hours only, but the sample of "normal" days is small (about 4 nights each for Oji, 3 for Ezinne, 7 for Jaya).
2. A recorder row is a state change, not an advert. Bermuda's own hysteresis sits upstream of these rows and is not visible here.
3. Oji's distance sensors are mostly disabled; scanner-count comparison across people is invalid.
4. Radar is an imperfect witness: ZK/ZX can drop a still sleeper, phantom holds exist (Study A fan holds, Jaya LD2410 fan loop per STATE_OF_PLAY section 6/9), Ziri and guests have no BLE. Agreement below ~100% is not purely BLE error; agreement was never separated into BLE vs radar fault.
5. The radar join uses midpoint sampling; rapidly flapping minutes are sampled once, so flap-heavy periods are weighted by minutes not by changes.
6. Day/night rate split uses 07-22 vs 22-07; the night drift section uses 00-06.
7. URA-resolved location comparison drops three differently-named rooms (section 2 note).
8. No fabrication check: every number comes from the queries above; the Garage A / `jaya_3` explanation in section 4 is a hypothesis, not a finding.
