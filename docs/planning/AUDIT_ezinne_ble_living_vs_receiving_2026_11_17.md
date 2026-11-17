# AUDIT: Ezinne BLE, Living Room vs Receiving Room (2026-11-17, read-only)

Probe window: 10:52-11:53 CST (the house clock reads CST, not CDT). HA restarted about 10:40 CST, so the history is post-restart only.
Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md section 3 (BLE), the BLE memory files, `person_coordinator.py` `_resolve_person_room` and `get_room_occupants`, Bermuda 0.8.7 source on the HA host.
Helpers: `.claude/tmp/ezblepos_*.py`. No state was changed. No Bermuda diagnostics were pulled.

## Answer
RSSI tuning helps, and it is the right lever. A scanner_areas change does nothing. The cause is a thin signal margin, not a mapping.

## 1. What "screek B" is (registry)
- Screek BP1_B is an ESPHome BLE proxy in the Living Room.
  - Device `67f9b8ec`, area Living Room, Wi-Fi MAC `08:ad:0a:5b:e6:58`.
  - Its bluetooth scanner device is "Screek BP1_B (08:AD:0A:5B:E6:5A)", area Living Room, config entry `bluetooth`.
- It is a scanner, not a tag. It is the nearest scanner to her right now.
- The other Living Room scanner is the Screek L13S mmWave sensor (`34:cd:b0:b2:85:16`, device area Living Room).
- The Receiving Room scanners are all three Shellys, each at offset 0:
  - `04:83:08:de:c1:22` (Shelly Plus Wall Display, "ShellyPlusDimmer Receiving Room1")
  - `04:83:08:de:c1:a6` (Shelly Plus Wall Display, "ShellyPlusDimmer Receiving Room2")
  - `a0:85:e3:bf:af:32` (Shelly 1PM Mini G4, "Shelly1PMG4 Receiving Room Fancy")

## 2. Her state now (REST, 11:52 CST)
- `person.ezinne` = home, source `device_tracker.ezinne_iphone_bermuda_tracker`.
- Her phone is resolved by IRK through the `private_ble_device` entry (its device carries the same `d90fcbad…` identifier); the Bermuda device is `iPhone_Ezinne`.
- `sensor.ezinne_iphone_area` = Living Room. `sensor.ezinne_iphone_nearest_scanner` = Screek BP1_B. `sensor.ezinne_iphone_nearest_rssi` = -62 dBm. `sensor.ezinne_iphone_distance` = 5.6 ft.
- `sensor.universal_room_automation_ezinne_location` = Living Room, `tracking_reason` bermuda, BLE axis "visible".
- Her recent_path flips Living Room to Receiving Room every 30 s in the 11:43-11:49 window.
- `device_tracker.ezinne_iphone` (private_ble) reports source `A0:85:E3:BF:AF:32`, the Receiving Room Shelly. That is HA's own bluetooth best-source and is not a URA input for room.

### Last hour of history (time share, 10:52-11:52)
| Measure | Result |
|---|---|
| Bermuda area | Living 51.8%, Receiving 21.0%, Kitchen 10.4%, Patio 9.0%, Breakfast 4.5%, Foyer 2.0% |
| URA person location | Living 50.0%, Receiving 21.7%, Kitchen 10.0%, Patio 7.5% |
| Nearest scanner | BP1_B 40.9%, L13S 11.0%, Receiving trio 21.1% combined, Patio Fans 9%, Kitchen apollo 8.8% |

URA person location tracks the Bermuda area one-to-one, so URA is passing Bermuda's flapping through unchanged.

### RSSI of the nearest scanner, by which scanner was nearest (joined history)
| Scanner | n | median | p10 | p90 |
|---|---|---|---|---|
| Screek BP1_B | 329 | -64 | -69 | -61 |
| Screek L13S (Living Room) | 108 | -69 | -73 | -65 |
| Receiving Room 1 | 54 | -67 | -74 | -65 |
| Receiving Room 2 | 57 | -67 | -73 | -63 |
| Receiving Fancy | 49 | -67 | -73 | -64 |

The margin when Receiving wins is only about 3 dB at the median, and the tails overlap.

Caveat: Receiving's best-of-three draw biases upward. Per-scanner distance sensors are dead, so the exact per-tick margin is unknowable.

## 3. Why per-scanner distances cannot be read (known card BERMUDA-DISTANCE-SENSORS-DEAD-1)
- All `*_distance_to_*` sensors are `unavailable`, `restored: true`.
- Their registry unique_ids are keyed to the Wi-Fi MAC (for example `a0:85:e3:bf:af:30`), but the live scanner address is the bluetooth MAC `...:32`.

## 4. Mechanism (Bermuda 0.8.7, `coordinator.py:1320-1455`)
- Distance is `10^((ref_power - (rssi + offset)) / (10 * attenuation))`.
  - `bermuda_advert.py:283`.
  - Live config: ref_power -55, attenuation 3.0, max radius 20 m, smoothing 20 samples.
- The nearest scanner is a two-way race against the incumbent, and a challenger only wins if one of these holds:
  - it is in the same area and is newer;
  - it is at least 15% closer AND its 5 s worst case beats the incumbent's best;
  - it is at least 30% closer outright (about 4 dB stronger).
- Her measured 3 dB gap is about 26% in distance, which is under the 30% outright bar.
- The result is sticky ownership by whichever scanner took the lead on a noisy sample. That produces the flapping.
- Offsets are keyed by scanner bluetooth address (`bermuda_advert.py:97`). A missing key means 0.

## 5. Where "mapped to Living Room" does and does not come from
- Living Room `scanner_areas` = `['foyer', 'dining_room']`.
- Receiving Room `scanner_areas` = `[]`. It is a Tier 1 direct room, owning its scanners.
- No room maps `receiving_room` as a borrowed scanner area.
- `_resolve_person_room` returns on the Tier 1 direct match first (`person_coordinator.py` lines 1722-1731). Adding `receiving_room` to Living Room's `scanner_areas` would therefore NOT change location.
- Which consumer shows the wrong room:
  - Bermuda `sensor.ezinne_iphone_area` and URA `…_ezinne_location`: both flap to Receiving Room, about 21% of the hour.
  - Room occupancy is NOT wrong. `binary_sensor.receiving_room_occupied` stayed `off` for the 2 h window (`ble_persons` is `[]`). BLE may extend but never create occupancy (`coordinator.py` ble_extend_not_create block).
  - Living Room occupancy is `on`, driven by motion. Its `ble_persons` is `["Ezinne"]`.
  - Exposure is display, `ura_person_location_change` moves (music following, transitions), `current_path` and `likely_next_room`. It is not room occupancy.

## 6. Recommendation (config-first, nothing changed)
Primary change, Bermuda options, per-scanner RSSI offset, UI path Bermuda > Configure > Calibration 1:
| Scanner | Address | Current | Proposed |
|---|---|---|---|
| Screek BP1_B (Living Room) | `08:ad:0a:5b:e6:5a` | no key (0) | +3 |

- Expected effect: the effective BP1_B reading at her seat becomes about -61 against Receiving at -67. That is about 6 dB, which clears the 30% outright bar. The flapping should drop.
- If +3 is not enough, step to +5.
- If a second lever is wanted, subtract 2 from the three Receiving scanners instead. They are consistent with a hot antenna or best-of-3 bias.
- Address check: BP1_A's Wi-Fi MAC is `e7:7c` and its offset key is `e7:7e`. The same pattern gives BP1_B's bluetooth address as `e6:5a`.

Side-risks:
- A positive offset on BP1_B makes people in Kitchen, Foyer, Dining or Receiving who are marginally closer to another scanner read as Living Room.
- A real occupant at the Living Room and Receiving boundary will favor Living Room.
- A person actually in Receiving, near the Wall Displays, reads about -55 or stronger, so they should still win by more than the 3 dB shift.
- I could not measure Oji, Jaya or Ziri. Their Bermuda area sensors are `unknown` today, so side-effects on them are unmeasured.

Not recommended:
- A `scanner_areas` change. It is inert because Tier 1 wins, and it would only add Tier 3 ambiguity.
- Removing any tuned mapping.

Falsifier: after the change, Receiving Room should fall from about 21% of the hour to the low single digits while she sits still. If it does not, the cause is not margin (for example the phone is physically nearer the Wall Displays), and a +3 will not help.

## 7. Unknowns
- Her actual position relative to BP1_B and the Wall Displays is not knowable from the registry.
- Kitchen, Patio and Breakfast hits (about 24% of the hour) may be real movement or bleed. I did not separate them.
- Oji, Jaya and Ziri have no Bermuda fix right now, so no cross-person comparison was possible.
