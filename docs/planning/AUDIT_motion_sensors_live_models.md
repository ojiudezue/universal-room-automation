# AUDIT — URA room sensor lists × device model (fan-noise Rev 2, C2 acceptance fixture)

**Date:** 2026-10-11. **Plan:** `docs/planning/PLANNING_fan_noise_running_rejection.md` Rev 2, C2 (Finding 7).
**Read-only.** Script: `scripts/fan_noise/audit_motion_sensors_models.py <storage_dir> [label]` — joins every URA room entry's
`motion_sensors` and `presence_sensors` (= `CONF_MMWAVE_SENSORS`) to the device registry and the family map
`sensor_capability.FAMILY_BY_MODEL_ID` (key = `model_id`, fallback `model`). Sources: main house
`/Users/okosisi/ha-config/.storage`; Wigton `ssh wigton 'cat /homeassistant/.storage/core.{config_entries,entity_registry,device_registry}'`.

## Findings

1. **ESPHome / cloud devices carry `model_id = None`.** LD2410 (`HLK-LD2410`), Screek, Seeed and the Meross MS600 only expose
   `model`. The plan's "lookup `device.model_id`" would miss them, so the family lookup falls back to `model` (builder
   deviation from the plan text — flagged for review).
2. **Jaya's radar is not identifiable as LD24xx.** `binary_sensor.jaya_3_presence` (and Kitchen, Study B, Ziri) are custom
   ESPHome builds whose device model is the board, `esp32-c3-devkitm-1`. Their family resolves `unknown` → recheck factor
   1.0. The plan's LD24xx factor 3.0 cannot reach Jaya until the device carries an LD24xx model (ESPHome `project:` name)
   or the map gains a per-device key. Open item for the operator.
3. **Radars filed as motion: 3, all Meross MS600** (`ms600 9.0.0`) — Guest Bedroom 1, Guest Bedroom 2, Media. Today the
   name regex excluded them (their names contain `presence`). Under C2 they are excluded by the model-id safety net
   (`generic_radar`). The plan's remedy "declare `kind: mmwave` in options" is **rejected by
   `validate_capabilities_payload`** (D-MEDIUM-1: a motion-wired entity may not be overridden to mmwave/occupancy), so the
   only clean operator fix is to move them to `presence_sensors`. Until then the safety net holds; its key carries the
   firmware string, so a firmware bump re-opens the gap — re-run this audit after Meross updates.
4. **`binary_sensor.ziri_3_moving_target`** (ESP32 board, LD2410 moving-target output) is in Ziri's `motion_sensors`. Neither
   the old regex nor the model map catches it — unchanged behaviour (it already counted as motion). Operator decision.
5. **Name-regex vs C2 delta (motion_sensors only):** 22 ZG-204ZV entries move from excluded to fan-immune witness (intended,
   SENSOR_FLEET_CLASSES Rule 1/3); the 3 MS600 stay excluded (safety net); `binary_sensor.outlet_lux_pir_mmwave_..._masterbath_motion`
   (Intecular IVO1 — UNVERIFIED whether this entity is the outlet's PIR or its mmWave output; its sibling `_occupancy` is in presence_sensors) moves from excluded to witness. Operator check. No other change.
6. **Wigton:** 3 rooms, each with one ecobee ECB501 occupancy entity in `motion_sensors`; no radars, no fans → C2/C4 inert there.

**Gate verdict:** zero unresolved radars-filed-as-motion that change behaviour versus today (3 MS600 resolved by the
safety net; Ziri's moving-target output unchanged). Operator follow-ups: move the 3 MS600 to presence sensors; decide
Ziri/Jaya ESP32 family.

### Main house (registry read 2026-10-11)

| Room | List | Entity | Manufacturer | model_id | model | Family | Override kind | Flag |
|---|---|---|---|---|---|---|---|---|
| AV Closet | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_avcloset_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Breakfast Nook | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_breakfast_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Butler Pantry | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_butler_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Dining Room | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Exercise Room | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_exercise_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Exercise Room | motion_sensors | binary_sensor.rgbw_motion_lux_3rd_zigbee_exercise_occupancy | Third Reality | 3RSNL02043Z | Zigbee multi-function night light | unknown | – | – |
| Exercise Room | presence_sensors | binary_sensor.mmwave_zigbee_gameroom_presence | HOBEIAN | ZG-204ZK | 24Ghz human presence sensor | zigbee_zk_zx | – | – |
| Exercise Room Closet | motion_sensors | binary_sensor.pir_zigbee_exercisecloset_occupancy | HOBEIAN | ZG-204Z | Motion sensor | pir | – | – |
| Foyer | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_entry_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Game Room | motion_sensors | binary_sensor.0xa4c1382e60e05225_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | pir | – |
| Garage A | motion_sensors | binary_sensor.garageopener_gdoblaq_wifi_garagea_motion | konnected | – | garage-door-gdov2-q | unknown | – | – |
| Garage A | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_garagea_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Garage B | motion_sensors | binary_sensor.ratgdov25i_dbfe2a_motion | ratgdo | – | v25iboard_secplus2 | unknown | – | – |
| Garage Hallway | motion_sensors | binary_sensor.mmwave_temp_hum_lux_garagehallway_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Garage Hallway | motion_sensors | binary_sensor.rgbw_motion_lux_3rdr_zigbee_garagehallway_occupancy_2 | Third Reality | 3RSNL02043Z | Zigbee multi-function night light | unknown | – | – |
| Guest Bedroom 1 | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_downguestroom_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Guest Bedroom 1 | motion_sensors | binary_sensor.smart_presence_sensor_24111917146201662002c4e7ae109bd3_sensor_presence_motion | Meross | – | ms600 9.0.0 | generic_radar | – | RADAR-FILED-AS-MOTION |
| Guest Bedroom 1 | presence_sensors | binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom1_occupancy | Meross | 16897 | Smart Presence Sensor | generic_radar | – | – |
| Guest Bedroom 1 Bathroom | motion_sensors | binary_sensor.rgbw_lux_motion_3rdr_wifi_matter_guestroom1bath_occupancy | ThirdReality | 4232 | Smart Night Light-W | unknown | – | – |
| Guest Bedroom 1 Closet | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_dnguestcloset_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Guest Bedroom 2 | motion_sensors | binary_sensor.mmwave_motion_lux_meross_wifi_jaya_sensor_presence_motion | Meross | – | ms600 9.0.0 | generic_radar | – | RADAR-FILED-AS-MOTION |
| Guest Bedroom 2 | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Guest Bedroom 2 Hallway | motion_sensors | binary_sensor.pir_zigbee_upguesthallway_occupancy | HOBEIAN | ZG-204Z | Motion sensor | pir | – | – |
| Jaya Bathroom | motion_sensors | binary_sensor.pir_zigbee_jayabathroom_occupancy | eWeLink | CK-TLSR8656-SS5-01(7002) | Motion sensor | unknown | – | – |
| Jaya Bedroom | presence_sensors | binary_sensor.jaya_3_presence | Espressif | – | esp32-c3-devkitm-1 | unknown | – | – |
| Jaya Bedroom | presence_sensors | binary_sensor.mmwave_zigbee_jayabedroom_presence | HOBEIAN | ZG-204ZK | 24Ghz human presence sensor | zigbee_zk_zx | – | – |
| Kitchen | motion_sensors | binary_sensor.motiontempluxhum_protect_blu_kitchen_motion | Ubiquiti | UFP-SENSE | UP Sense | unknown | – | – |
| Kitchen | presence_sensors | binary_sensor.mmwave_lux_temp_humidity_zigbee_kitchen_presence | HOBEIAN | ZG-204ZX | 24Ghz millimeter wave and T&H sensor | zigbee_zk_zx | – | – |
| Kitchen | presence_sensors | binary_sensor.mmwave_lux_wifi_esphome_kitchen_presence | Espressif | – | esp32-c3-devkitm-1 | unknown | – | – |
| Kitchen Hallway | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_stairkitchenhallway_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Kitchen Hallway Garage | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_garagekitchenhallway_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Kitchen Pantry | motion_sensors | binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_pantry_occupancy | ThirdReality | 4232 | Smart Night Light-W | unknown | – | – |
| Laundry | motion_sensors | binary_sensor.rgbw_lux_motion_3rdr_wifi_matter_laundry_occupancy | ThirdReality | 4232 | Smart Night Light-W | unknown | – | – |
| Laundry Closet | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_utilitycloset_presence_2 | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Living Room | motion_sensors | binary_sensor.mmwave_temp_lux_hum_zigbee_livingroom_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Living Room | presence_sensors | binary_sensor.mmwave_lux_temp_hum_zigbee_livingroom_presence | HOBEIAN | ZG-204ZX | 24Ghz millimeter wave and T&H sensor | zigbee_zk_zx | – | – |
| Living Room | presence_sensors | binary_sensor.screek_human_sensor_l13_2412s_presence | Screek | – | Human_Presence_Sensor | generic_radar | – | – |
| Master Bath Toilet | motion_sensors | binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_mastertoilet_occupancy | ThirdReality | 4232 | Smart Night Light-W | unknown | – | – |
| Master Bathroom | motion_sensors | binary_sensor.outlet_lux_pir_mmwave_temp_voc_pressure_invisoutet_mqtt_masterbath_motion | Intecular | – | IVO1 | unknown | – | – |
| Master Bathroom | presence_sensors | binary_sensor.outlet_lux_pir_mmwave_temp_voc_pressure_invisoutet_mqtt_masterbath_occupancy | Intecular | – | IVO1 | unknown | – | – |
| Master Bedroom | presence_sensors | binary_sensor.mmwave_temp_hum_lux_zigbee_masterbedroom_presence | HOBEIAN | ZG-204ZX | 24Ghz millimeter wave and T&H sensor | zigbee_zk_zx | – | – |
| Master Bedroom | presence_sensors | binary_sensor.screek_human_sensor_l13_b38b24_presence | Screek | – | Human_Presence_Sensor | generic_radar | – | – |
| Master Bedroom | presence_sensors | binary_sensor.switch_mmwave_inovelli_occupancy | Inovelli | VZM32-SN | mmWave Zigbee Dimmer | generic_radar | – | – |
| Master Closet Storage | motion_sensors | binary_sensor.motion_sonoff_zigbee_masterclosetstorage_occupancy | SONOFF | SNZB-03P | Zigbee PIR sensor | pir | – | – |
| Master Hallway | motion_sensors | binary_sensor.mmwave_temp_lux_hum_masterhallway_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Master Hallway | motion_sensors | binary_sensor.rgbw_motion_lux_3rd_zigbee_masterhallway_occupancy | Third Reality | 3RSNL02043Z | Zigbee multi-function night light | unknown | – | – |
| Media | motion_sensors | binary_sensor.mmwave_motion_lux_meross_wifi_mediaroom_sensor_presence_motion | Meross | – | ms600 9.0.0 | generic_radar | – | RADAR-FILED-AS-MOTION |
| Media | presence_sensors | binary_sensor.mmwave_motion_lux_matter_wifi_mediaroom_occupancy | Meross | 16897 | Smart Presence Sensor | generic_radar | – | – |
| Media Room Closet | motion_sensors | binary_sensor.pir_zigbee_mediacloset_occupancy | HOBEIAN | ZG-204Z | Motion sensor | pir | – | – |
| Oji Vanity | motion_sensors | binary_sensor.pir_zigbee_ojivanity_occupancy | HOBEIAN | ZG-204Z | Motion sensor | pir | – | – |
| Patio | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_patioleft_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Patio | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_patioright_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Receiving Room | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_hobeian_receiving_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Stair Closet | motion_sensors | binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_staircloset_occupancy | ThirdReality | 4232 | Smart Night Light-W | unknown | – | – |
| Study A | presence_sensors | binary_sensor.mmwave_zigbee_studya_presence | HOBEIAN | ZG-204ZK | 24Ghz human presence sensor | zigbee_zk_zx | – | – |
| Study A Closet | motion_sensors | binary_sensor.occupancy_lux_temp_humidity_studyacloset_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Study B | presence_sensors | binary_sensor.mmwave_lux_wifi_esphome_studyb_presence | Espressif | – | esp32-c3-devkitm-1 | unknown | – | – |
| Up Guestbedroom Closet | motion_sensors | binary_sensor.pir_zigbee_guestbedroom2_closet_occupancy | HOBEIAN | ZG-204Z | Motion sensor | pir | – | – |
| Upstairs Hallway | motion_sensors | binary_sensor.mmwavemotion_lux_temp_hum_upstairshallway_presence | HOBEIAN | ZG-204ZV | Millimeter wave motion detection | zigbee_zv | – | – |
| Ziri Bathroom | motion_sensors | binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_ziribath_occupancy | ThirdReality | 4232 | Smart Night Light-W | unknown | – | – |
| Ziri Bedroom (Bedroom 5) | motion_sensors | binary_sensor.ziri_3_moving_target | Espressif | – | esp32-c3-devkitm-1 | unknown | – | – |
| Ziri Bedroom (Bedroom 5) | presence_sensors | binary_sensor.mmwave_zigbee_ziribedroom_presence | HOBEIAN | ZG-204ZK | 24Ghz human presence sensor | zigbee_zk_zx | – | – |
| Ziri Bedroom (Bedroom 5) | presence_sensors | binary_sensor.ziri_3_presence | Espressif | – | esp32-c3-devkitm-1 | unknown | – | – |

Rooms: 43; entities: 63; radar-filed-as-motion: 3

### Wigton (registry read 2026-10-11 via ssh wigton)

| Room | List | Entity | Manufacturer | model_id | model | Family | Override kind | Flag |
|---|---|---|---|---|---|---|---|---|
| Down Guest bedroom hallway | motion_sensors | binary_sensor.master_closet_ecobee_downstairs_motion | ecobee Inc. | – | ECB501 | unknown | – | – |
| Game room | motion_sensors | binary_sensor.game_room_ecobee_upstairs_motion | ecobee Inc. | – | ECB501 | unknown | – | – |
| Study Hallway | motion_sensors | binary_sensor.study_hallway_ecobee_master_suite_motion | ecobee Inc. | – | ECB501 | unknown | – | – |

Rooms: 3; entities: 3; radar-filed-as-motion: 0
