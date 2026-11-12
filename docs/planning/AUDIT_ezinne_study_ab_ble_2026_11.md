# AUDIT: Ezinne placed in Study A (BLE / Bermuda), 2026-11-11 11:30 CST

Read-only probe. Read first, completely: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md and SENSOR_FLEET_CLASSES.md (incl. ledgers).

## Verdict
Root cause: a stale area assignment, not RSSI tuning. The Bermuda scanner "Screek BP1_B (08:AD:0A:5B:E6:5A)" is still filed in area **Study A** in the HA device registry, but the unit was physically moved to the **Living Room** (operator 2026-11-10, board card BLE-PROXY-PLACEMENT-1 `operator_instruction_2026_11_10`). Every advert Bermuda hears on it is labelled Study A. Study B's ESP and scanners are online and working; no Bermuda option change is needed.

## Findings
| # | Finding | Evidence |
|---|---|---|
| 1 | Her tracker: iPhone IRK Bermuda device `iPhone_Ezinne` (`sensor.ezinne_iphone_area` = Study A, nearest scanner Screek BP1_B, rssi -63, since 11:11 CST). `person.ezinne` = home (trackers: `device_tracker.ezinne_iphone`, `..._bermuda_tracker`, `zinny_s_iphone_15` GPS). URA `sensor.universal_room_automation_ezinne_location` = Study A, tracking_reason bermuda, confidence 0.3 low. | live /api/states 11:28 CST |
| 2 | The scanner that wins is BP1_B. Registry: parent device `67f9b8ec` (name_by_user "Screek BP1_LivingRoom") area `living_room`, modified 2026-11-06. BLE child device `9ca97f80` "Screek BP1_B (08:AD:0A:5B:E6:5A)" area `study_a`, `modified_at` 2026-10-05, via the parent. Bermuda reads the child's area. | `.storage/core.device_registry`; `bermuda.dump_devices` advert row area_name "Study A" |
| 3 | Live Bermuda adverts for Ezinne (dump_devices, 11:28): BP1_B -60 dBm 1.02 m (labelled Study A); Receiving Room Shelly dimmers 2.3-2.5 m; Living Room L13 2.6 m; Foyer proxy 2.7 m; Study B1 Shelly 4.64 m; **Study B ESP f0:9e:9e:b2:47:a2 -76 dBm 4.68 m (scanner, area Study B, offset 0, fresh)**; Study A BP1_A 5.55 m (offset +6); Study A panel 5.59 m (offset +3). Her ranking is the Receiving/Living/Foyer cluster, not either Study. | dump_devices |
| 4 | Study B ESP is a working Bermuda scanner: registry device `99578665` area Study B (bluetooth F0:9E:9E:B2:47:A2); `switch.mmwave_lux_wifi_esphome_studyb_control_bluetooth` on; Bermuda read her on it for 3.2 h on 11-10 (nearest_scanner history). Study B panel proxy (AE:20:0E:34:18:D9) is registered in Study B but has no advert for her now (0 devices nearby on its sensor). | registry; recorder |
| 5 | Bermuda options (`core.config_entries`, bermuda): ref_power -55, attenuation 3, max_area_radius 20, smoothing 20, update 5 s. Offsets: Study B scanners all 0; BP1_A +6; Study A panel +3; **BP1_B (e6:5a) has no entry (0)**. | config_entries |
| 6 | URA config: Study A `scanner_areas=['study_a_closet']`, presence sensors = ZK radar + `study_a_panel_person_occupancy`. Study B `scanner_areas=[]`, presence = ESPHome LD2410 `binary_sensor.mmwave_lux_wifi_esphome_studyb_presence`. No URA mapping routes a Study B scanner to Study A; the mislabel is upstream in Bermuda. | config_entries |
| 7 | 72 h history (recorder, 11-08 11:30 to 11-11 11:30): she is read "Study A" 19.2 h, all of it nearest scanner BP1_B (19.2 h, matches to the decimal). Minutes read Study A with Study A occupied: 1 of ~1150 (0.1%). Study A or B occupied with her in A: 14 min. | recorder SQL on states |
| 8 | The report "A while B mmWave is occupied" is NOT supported by the data: 19 B-mmWave episodes, 337 min on; she read Study A in 3 of those minutes. During the long 11-10 episodes she read Study B 69-88% (Master Bedroom the rest; B may have held other people). Right now B mmWave, Study A radar, panel person sensor and both room `occupied` sensors are all off (since 07:03 CST restart). | recorder; live states |

## What I could not establish
Where Ezinne physically is now. Sensors show neither study occupied; Bermuda geometry says near the Receiving Room / Foyer / Living Room, not B. "Likely in Study B" is unverified. Also unverified: the physical position of BP1_B beyond the operator's statement (living room).

## Falsifier I tried
If BP1_B were truly in Study A, Study A radar/panel would be on when she reads it. They are on 0.1% of those minutes. Not falsified; the mislabel stands.

## Fix (config-first, no code, no physical work)
1. HA UI: Settings > Devices > "Screek BP1_B (08:AD:0A:5B:E6:5A)" (device id 9ca97f80...) > set area to **Living Room**. Bermuda then labels it Living Room (may need a Bermuda entry reload if it does not refresh; reload is operator/orchestrator action, I changed nothing).
2. No RSSI offset change proposed: nothing in the data shows Study B under-reporting (ESP -76 dBm tracks real reads on 11-10). Do not tune offsets until the area is fixed and a re-measure exists.
3. Optional: BLE-PROXY-PLACEMENT-1 `verify_2026_11_11_overnight` says "BP1_B DONE: device area is Living Room" but checked only the parent device and its buttons. Correct that note.
Nothing requires physical presence.

Side effect to expect: the same mislabel inflates Study A for any phone near BP1_B (Study A room lights, HVAC occupancy, Study A fan holds). Only Ezinne's phone is currently on it.

Confidence: high on root cause (registry area + live advert label + 19.2 h = 19.2 h match); medium-low on her actual location.
