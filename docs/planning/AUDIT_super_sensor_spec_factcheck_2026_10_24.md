# AUDIT — "Madrone Super Sensor Specification" fact-check (2026-10-24)

**Subject:** `/Users/okosisi/.claude/uploads/75cc297f-1426-4620-b7aa-da058bc0fab0/6c3fc34e-madrone_super_sensor_spec.md`. 2,375 lines, Rev 1.0, dated Feb 2026, written by an earlier AI agent.
**Method:** I read the whole spec. Every ESPHome platform and key was checked against the current esphome.io component pages, every version claim against esphome.io changelogs, and hardware claims against Seeed and reseller datasheets. The spec was compared with `docs/architecture/SENSOR_FLEET_CLASSES.md` for overlap with what the house already runs. Read-only audit: no other file was touched.

---

## 1. Summary verdict: MODIFY HEAVILY. Do not build as written.

The hardware idea holds up: an XIAO ESP32-S3 or C6 with an LD24xx radar and a shared I²C environmental bus is a common, workable ESPHome pattern. The document itself is not usable. None of the six YAML configs would compile as written. One wiring error would make every radar node fail (powered from 3V3 when it needs 5V). The on-chip fusion logic cannot mathematically reach its own "occupied" threshold from radar alone.

**The five biggest issues:**

1. **The YAML is largely invented or out of date.** LD2410 keys are made up (`has_static_target`, `occupancy`, `moving_target_distance`, `static_target_energy`). `neopixelbus` is used on `esp-idf`, which the docs say does not work. VL53L1X is driven through the `vl53l0x` platform, which does not support it. Top-level `binary_sensor:`/`sensor:`/`interval:` keys are duplicated, and the fusion addendum duplicates them again. External components are invented (`hanyuone/ld2450`, `screekworkshop/esphome_ld2402`, `seedstudio_mr24fdb1`). There is an undefined `id(aqi_led_val)`. The microphone lambda treats a `uint8_t` byte vector as int16 samples, and nothing calls `microphone.capture`, so it never runs.
2. **Radars are wired to 3V3.** HLK-LD2410C (and LD2450) need a 5 V supply (more than 200 mA) with 3.3 V logic. The spec says "all sensors run on 3V3, do not connect to 5V". Every radar node would brown out or fail to start.
3. **Fusion cannot reach "occupied" from radar alone.** A full radar vote is worth 0.50, or 0.65 on the bathroom node, and the entry threshold is 0.70. A still person needs the MLX90614 IR-delta vote to cross it. The spec's 5–15 °C IR delta is unsupported, and is implausible for a 90° FOV sensor at room distance. So the fused `Occupancy` entity, which the spec says automations should depend on *exclusively*, would mostly read **empty for a still occupant**. That is the failure mode URA already fights.
4. **"Boomer" vitals and fall modules are wrong or unsupported.** HLK-LD2402 is an ordinary 24 GHz presence radar, not a breathing or heart-rate sensor. MR24FDB1 has no ESPHome component (Seeed's wiki shows Arduino only), and fall range is ≤1.5 m. The ESPHome-supported Seeed parts are the MR60BHA2 (breathing/heart) and the MR60FDA2 / MR24HPC1 family.
5. **It duplicates what the house already runs.** The house already has ESPHome LD2410 nodes (Jaya, Ziri, Kitchen, Study B), Hobeian ZK/ZX presence radars and ZV motion-class radars, ESPHome BLE proxies feeding Bermuda, and Halo panels. The spec's main value (radar + BLE + lux + T/H) is already deployed. What's new is IR temp, ToF, mic dB and VOC/CO₂, and those are either weak signals (IR, mic) or cheaper as standalone additions (SCD41/SGP41 on an existing node).

**If you want something from it:** build an *Environment* node (C6 + SHT4x + SCD41 or SGP41, no radar). Fix the YAML per §4. Skip on-chip fusion: URA already fuses in its coordinators and can tune without reflashing. Spend radar money on more ZK/ZX or LD2410 nodes only where coverage gaps are measured.

---

## 2. Fabrications and errors

| # | Spec location | Claim | Truth | Class | Source |
|---|---|---|---|---|---|
| E1 | §5 header (L1073), all wiring diagrams | All sensors including LD2410C/LD2450 on 3V3; "do not connect to 5V" | LD2410C needs a **5 V** supply rated over 200 mA (~79 mA typical); I/O is 3.3 V | WRONG (fatal) | openelab.io LD2410C guide; Hi-Link datasheet |
| E2 | §1a L33, §9 L2357 | C6 has "No I²S support — open feature request since Nov 2023" | ESP32-C6 silicon has an I²S controller. ESPHome i2s_audio says only "works on ESP32 based chips" and doesn't exclude C6. No such feature request could be found | UNVERIFIABLE / likely fabricated citation | esphome.io/components/i2s_audio |
| E3 | §1a L29 | XIAO C5: "512KB SRAM, no PSRAM" | 384 KB SRAM + **8 MB PSRAM**, 8 MB flash, 240 MHz | WRONG | cnx-software XIAO C5 launch; thepihut listing |
| E4 | §1a L27/L38, §9 | C5 "stub support only (logger/core)", "XIAO board support: not yet" | Board was dated Mar 2026, so this was plausible in Feb 2026, but C5 work was already landing: adc C5 (2025.8.0), psram + openthread C5 (2025.12.0), wifi `band_mode` (2026.3.0). The esp32 page now lists C5 as supported | OUTDATED / overstated | esphome.io changelog 2025.8.0, 2025.12.0, 2026.3.0; /components/esp32 |
| E5 | §1a L34 | "I²C fixed in ESPHome 2025.12.0" for C6 and C5 | 2025.12.0 has only "[i2c] Fix port logic with ESP-IDF" (#12063), which is not chip-specific | UNVERIFIABLE / overstated | esphome.io/changelog/2025.12.0 |
| E6 | §1a L31 | C6 BLE proxy "picks up ~1 vs S3's ~8 in real-world tests" | No source | FABRICATED number | none |
| E7 | §1a L45, §9 L2369 | S3 "dual-core isolates the I²S task", so C6 "can't handle" BLE+UART+I²C+I²S | No ESPHome doc says this. The real constraint is RAM; BT proxy docs warn about memory (web_server, esp-idf preferred) | UNVERIFIABLE | esphome.io/components/bluetooth_proxy |
| E8 | §1a L47, §9 L2357 | C6 nodes "could eventually route Zigbee / be Thread border routers / Zigbee coordinators" | ESPHome OpenThread (2025.6.0) = Thread *device*. ESPHome Zigbee (2026.5.0 for C6/H2) = end devices. Neither is coordinator or border router | WRONG / overreach | esphome.io blog 2025-06-18; cnx-software 2026-05-26 |
| E9 | §2.1 L76, YAML 3.1/3.2, §8 | VL53L1X: "use vl53l0x platform; L1X is backward compatible" | The `vl53l0x` page documents only L0X. L1X is register-incompatible and needs an external component (e.g. soldierkam/m5k10 vl53l1x_sensor) | WRONG | esphome.io/components/sensor/vl53l0x; github.com/m5k10/vl53l1x_sensor |
| E10 | §2.2, YAML 3.2 | LD2450 is an "external component", `github://hanyuone/ld2450` | LD2450 is a **native** ESPHome platform (`ld2450`, hub `ld2450_id`). The repo name looks invented | WRONG + fabricated source | esphome.io/components/sensor/ld2450 |
| E11 | §2.5, YAML 3.5 | HLK-LD2402 = breathing + heart-rate vitals radar; `screekworkshop/esphome_ld2402` | LD2402 is a 24 GHz *human-presence* radar (moving/still/micro-motion), not vitals. Component repo not found | WRONG + fabricated | zbotic / domoticx LD2402 listings |
| E12 | §2.5, YAML 3.6 | MR24FDB1 has a "Seeed community ESPHome component" `seeedstudio_mr24fdb1` at limengdu/MR24FDB1-ESPHome | Seeed wiki shows Arduino examples only. No ESPHome component found. Fall range ≤1.5 m; 2.0 mm-pitch double-row header, not "Grove + 2.54mm pads" | UNVERIFIABLE / likely fabricated | wiki.seeedstudio.com/Radar_MR24FDB1 |
| E13 | §2.1 L74, all YAML | `light: neopixelbus` with `framework: esp-idf` | "NeoPixelBus does **not** work with ESP-IDF". ESP32 support deprecated 2026.6. Use `esp32_rmt_led_strip` | WRONG (compile fail) | esphome.io/components/light/neopixelbus |
| E14 | YAML 3.1/3.2 mic lambda | `for (int16_t sample : x)`, `/32767`, `+94` gives dB | `on_data` x is `std::vector<uint8_t>` (raw bytes). With 32-bit samples the math is garbage. The +94 offset ignores INMP441 sensitivity (−26 dBFS @ 94 dB SPL). ESPHome already ships a native `sound_level` sensor (rms/peak) | WRONG | esphome.io/components/microphone; /sensor/sound_level |
| E15 | YAML 3.1/3.2 | Mic publishes on its own | Nothing calls `microphone.capture`, so no data. If started, publishing every frame floods the API | WRONG | esphome.io/components/microphone |
| E16 | §6.6 L1627 | "ESPHome's `offset:` parameter on the `sht4x` sensor" | sht4x has no `offset` key. Use `filters: - offset:` on the temperature sub-sensor | WRONG (invented key) | esphome.io/components/sensor/sht4x |
| E17 | §2.3, YAML 3.3/3.6 | sgp4x keys `voc:` / `nox:` | Renamed `voc_index` / `nox_index`; old names deprecated, removed 2027.2.0 (still accepted today) | OUTDATED | esphome.io/components/sensor/sgp4x |
| E18 | §8.2 L1831 | Person raises MLX90614 delta "5–15 °C" | Unsupported. With a 90° FOV at 2 m, a body fills a few percent of the cone, so the averaged rise is ~sub-1 °C to low single digits. Combined with E19 this breaks the fusion | FABRICATED / implausible | MLX90614 datasheet FOV; physics |
| E19 | §8.5 | Hysteresis enter 0.70 / exit 0.35 with radar weight 0.50 (0.65 bathroom) | Radar alone can never cross 0.70. A still person is "empty" unless IR votes | LOGIC ERROR | spec arithmetic |
| E20 | §8 L1807 | Fusion runs "at ~10ms update cycles" | The YAML runs it at `update_interval: 2s` | Self-contradiction | spec |
| E21 | §8.7 L2328 | Tune for >80% occupied / <20% empty | Contradicts the 70/35 thresholds in §8.5 | Self-contradiction | spec |
| E22 | §7.1 L1644 | XIAO "0.5mm pad spacing" | XIAO castellated pads are 2.54 mm pitch | WRONG | Seeed XIAO wiki |
| E23 | §7.1 L1668 | MLX90614 ESS = "90° half-angle FOV"; narrow is "xAA, 5°" | The suffix sets FOV: BAA ≈ 90° *full* FOV; 5° is the DCI/DCC variant. "ESS" isn't the FOV code | WRONG | Melexis MLX90614 datasheet ordering codes |
| E24 | YAML 3.1 etc. | `i2c frequency: 400kHz` with MLX90614 on the bus | MLX90614 is SMBus, max 100 kHz | WRONG (bus fault risk) | Melexis datasheet |
| E25 | §5.3/5.4 vs YAML 3.3/3.4 | Bathroom and Environment are C6 builds on GPIO22/23 | Their YAML declares `board: seeed_xiao_esp32s3` and GPIO5/6 | Internal contradiction | spec |
| E26 | §7.5 L1744 | "Section 4.5" full integrated PCB | No §4.5; it's §6.5 | Broken ref | spec |
| E27 | §5.4 L1364 | Environment node "~25–30 mA total" | C6 WiFi average current alone is in that range or higher with TX bursts. ENS160 runs a heated hotplate. Understated | Likely WRONG | Espressif C6 datasheet |
| E28 | §6.6 L1627 | XIAO self-heating "~0.5–1 °C" | No source. Enclosed S3 with WiFi+BLE scanning plus a 5 V radar typically shows more | UNVERIFIABLE | none |
| E29 | §2.2/8.2 | "LD2450 does not expose energy values" | True, but it exposes still/moving target counts and per-target speed, which the fusion ignores | Incomplete | esphome ld2450 page |
| E30 | §4 | "All prices verified February 2026" | Ballpark plausible (XIAO C5 $6.90 matches). "Verified" is not evidenced | UNVERIFIABLE | — |

## 3. Verified-real claims

| Claim | Status | Source |
|---|---|---|
| ESPHome runs standalone (native API, MQTT, web_server REST) | VERIFIED | esphome.io |
| C6 is ESP-IDF only (no Arduino); S3 supports both | VERIFIED | esphome.io/components/esp32 |
| C6 listed as officially supported in 2025.6.0 (June 2025) | VERIFIED (earlier initial work via esphome#4377) | esphome.io/changelog/2025.6.0 |
| `seeed_xiao_esp32c6` board definition added 2025.12.0 | VERIFIED (#12307) | esphome.io/changelog/2025.12.0 |
| C6: WiFi 6 2.4 GHz, BLE 5, 802.15.4; single-core RISC-V; 512 KB SRAM, no PSRAM | VERIFIED | esphome esp32 page; Espressif |
| C5: dual-band WiFi 6, BLE 5, 802.15.4, single-core RISC-V | VERIFIED (memory figures wrong, see E3) | cnx-software |
| XIAO S3: dual-core LX7, 8 MB PSRAM, BLE 5 | VERIFIED | Seeed wiki |
| XIAO S3 pin map (D0=G1 … D6=G43, D7=G44, D8–D10=G7–9) and C6 map (D0=G0 … D3=G21, D4/5=G22/23, D6/7=G16/17, D8=G19, D9=G20, D10=G18) | VERIFIED | Seeed XIAO wikis |
| LD2410 native, 256000 baud, parity NONE / 1 stop | VERIFIED | esphome.io ld2410 |
| LD2450 tracks 3 targets with X/Y, 256000 baud | VERIFIED | esphome.io ld2450 |
| I²C addresses: BH1750 0x23 (0x5C alt), SHT4x 0x44, MLX90614 0x5A, VL53L1X 0x29, SGP41 0x59, ENS160 0x52/0x53, AHT21 0x38: no collisions | VERIFIED | component pages / datasheets |
| `mlx90614` keys `ambient`/`object` | VERIFIED | esphome.io mlx90614 |
| `ens160` keys `eco2`/`tvoc`/`aqi`, `compensation: temperature/humidity` | VERIFIED | esphome.io ens160 |
| `sgp4x` `compensation: temperature_source/humidity_source` | VERIFIED | esphome.io sgp4x |
| `i2s_audio` mic keys `i2s_din_pin`, `adc_type: external`, `pdm`, `channel`, `bits_per_sample`, `i2s_audio_id` | VERIFIED | esphome.io i2s_audio mic |
| `ota: - platform: esphome`, `api: encryption: key` | VERIFIED (current syntax) | esphome.io |
| `bluetooth_proxy: active: false` = no GATT connections, adverts only (fine for Bermuda) | VERIFIED | esphome.io bluetooth_proxy |
| SCD41 photoacoustic CO₂, native `scd4x` | VERIFIED | esphome.io scd4x |
| Decay math "~50% in 8 cycles" at 0.08 (0.92⁸≈0.51) | VERIFIED (arithmetic) | — |
| NVS-wear mitigation (write only on drift) | Reasonable design | — |
| PETG > PLA for heat; ABS/PETG radar-transparent; no metal/CF fill | Reasonable / standard | — |

## 4. YAML key-by-key findings

| Block | Key(s) in spec | Verdict | Fix |
|---|---|---|---|
| `esp32.board` (3.3, 3.4) | `seeed_xiao_esp32s3` on "C6" nodes | Contradiction | `seeed_xiao_esp32c6` (≥2025.12.0) + GPIO22/23 |
| `i2c.frequency` | 400kHz | Unsafe with MLX90614 | 100kHz |
| `binary_sensor: ld2410` | `has_static_target`, `occupancy` | **Invented** | `has_target`, `has_moving_target`, `has_still_target` |
| `sensor: ld2410` | `moving_target_distance`, `static_target_distance`, `moving_target_energy`, `static_target_energy` | **Invented** | `moving_distance`, `still_distance`, `moving_energy`, `still_energy`, `detection_distance` |
| `external_components` ld2450 | `github://hanyuone/ld2450` | Fabricated / unnecessary | delete; native `ld2450` |
| `binary_sensor/sensor: ld2450` | `has_target`, `target_count`, `ld2450_id` | Valid | — |
| `sensor: vl53l0x` for VL53L1X | `long_range`, `address` | Keys valid for L0X; wrong chip | external vl53l1x component, or buy a VL53L0X (2 m) |
| `sensor: sht4x` | temperature/humidity; `offset:` (prose) | `offset` invented | `filters: [offset: -x]` |
| `sensor: sgp4x` | `voc`, `nox` | Deprecated | `voc_index`, `nox_index` |
| `sensor: ens160` | `compensation: temperature/humidity` | Valid | — |
| `sensor: mlx90614` | `ambient`, `object` | Valid | add `emissivity` 0.98 for skin |
| `sensor: bh1750` | `address`, `unit_of_measurement` | Valid | — |
| `microphone: i2s_audio` | config keys | Valid | — |
| `microphone.on_data` lambda | int16 iteration | Wrong type | use native `sound_level` sensor (`passive: true`, `rms`/`peak`), or start with `microphone.capture` |
| `light: neopixelbus` | `type: GRB`, `variant: WS2812X` | Keys valid, **platform fails on esp-idf** | `esp32_rmt_led_strip` (`chipset: ws2812`, `rgb_order: GRB`) |
| duplicate top-level `binary_sensor:` (3.2, 3.3) and the addendum's `sensor:`/`binary_sensor:`/`interval:` | — | YAML duplicate keys; ESPHome rejects or the last block wins | merge into one list per domain |
| `interval` (3.4) | `id(aqi_led_val)` | Undefined id, compile fail | give the `aqi` sensor an id |
| `binary_sensor: seeedstudio_mr24fdb1`, `ld2402` platforms | `fall_detected`, `breathing_rate`, `heart_rate` | **Invented** components/keys | no native support; for vitals use `seeed_mr60bha2` |
| `esp32_ble_tracker.scan_parameters.active: false` | — | Valid | — |
| fusion `sensor` lambdas | reference `ld2410_moving_energy` etc. | Will compile once ids are fixed; math flaw E19 | — |

## 5. Practicality issues

- **Power budget.** Two LD2410/LD2450 at 5 V is ~80–100+ mA. S3 WiFi + continuous BLE scan + I²S adds ~100–200 mA with TX peaks. 5 V/1 A USB is fine *if* the radar is on the 5 V pin. Through the XIAO's 3V3 LDO (~700 mA max on S3) it is wrong (E1).
- **Radio coexistence.** One 2.4 GHz radio is time-shared between WiFi and BLE scanning. ESPHome warns that aggressive scan settings cause WiFi instability and RAM pressure. Adding I²S DMA buffers plus an API flood from the mic lambda makes it worse. Workable on S3 with PSRAM, defaults, and no web_server, but not "free".
- **Self-heating vs temperature readings.** Radar, MCU, ENS160 hotplate and SGP41 hotplate share one enclosure. SHT4x and AHT21 will read high, and RH low as a result. This also corrupts the IR delta: it subtracts the SHT40 "ambient", so a warm-biased ambient suppresses the vote. Needs a thermal partition, not just "ventilation slots".
- **Mounting geometry conflict.** The radar wants a 1.8–2.2 m wall or corner. The ToF bed sensor must sit 60–100 cm *directly above the mattress*, facing down. One enclosure can't do both, and the spec stacks them in one face (§7.7).
- **mmWave inter-node interference.** Multiple 24 GHz FMCW modules in adjacent rooms can cross-detect through drywall. LD2410 gate/energy thresholds need per-room tuning. The house already has 24 GHz Hobeian ZK/ZX and ZV in many rooms; adding more 24 GHz in the same rooms increases this.
- **On-chip fusion vs URA.** It needs a reflash per tuning iteration. It hides raw signals behind one boolean, and it conflicts with URA's capability-based fusion (fan-noise rejection keys on the radar-bearing capability of *raw* entities; `SENSOR_FLEET_CLASSES.md` rule 3). Feed URA the raw `has_still_target`/`has_moving_target` + energy instead.
- **Privacy.** An always-on mic in bedrooms. "Level only" is a firmware promise, not a hardware guarantee.
- **WS2812B at 3V3** is out of datasheet (3.5–5.3 V). Also, a status LED inside a bedroom sensor is a night-light nuisance.

### House-context conflicts (per `docs/architecture/SENSOR_FLEET_CLASSES.md`)

| Spec choice | Already deployed | Assessment |
|---|---|---|
| LD2410C presence nodes | ESPHome HLK-LD2410 in Jaya, Ziri, Kitchen, Study B (`SENSOR_FLEET_CLASSES.md` §ESPHome) | Duplicate. Proven pattern; extend only where a gap is measured |
| LD2450 bedroom multi-target | Hobeian ZK (Jaya, Ziri, Study A…) and ZX (Master Bedroom…) still-person radars | Duplicates still-hold capability. Target count is new, but URA has no consumer for it |
| AM312 PIR "fast trigger" | 22 ZV motion-class + 5 Hobeian PIRs | Duplicate |
| BLE proxy on every node | Existing ESPHome proxies + Bermuda with tuned `scanner_areas`/RSSI (memory: BLE config is tuned) | Adds scanners Bermuda must be re-tuned for; not "free" |
| SHT40 T/H, BH1750 lux | ZX has T/H; Hobeian units report lux; Halo panels; HVAC thermostats | Mostly duplicate |
| On-chip `Occupancy` "use only this" | URA coordinators fuse raw sensors by capability | Conflicts; would be filed as an unknown-family radar-derived entity |
| SGP41 / SCD41 / ENS160 air quality | not in the fleet doc | **New value.** Best salvage |
| MLX90614, VL53L1X, INMP441 | none | New but weak or unproven signals; skip unless a specific use case (bed occupancy) is measured |

---
Sources: esphome.io/components/{sensor/ld2410, sensor/ld2450, sensor/vl53l0x, light/neopixelbus, microphone, microphone/i2s_audio, i2s_audio, sensor/sound_level, sensor/sht4x, sensor/mlx90614, sensor/ens160, sensor/sgp4x, bluetooth_proxy, esp32, seeed_mr60bha2}; esphome.io/changelog/{2025.6.0, 2025.8.0, 2025.12.0, 2026.3.0}; esphome.io/blog/2025/06/18/esphome-2025-6; cnx-software.com (XIAO C5 launch; ESPHome 2026.5.0); wiki.seeedstudio.com/Radar_MR24FDB1; openelab.io HLK-LD2410C guide; zbotic.in / domoticx.net HLK-LD2402 listings; github.com/m5k10/vl53l1x_sensor.
