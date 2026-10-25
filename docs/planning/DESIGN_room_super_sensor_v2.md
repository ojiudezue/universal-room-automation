# DESIGN — Room super sensor v2 (science experiment)

**Status:** design and research only. No URA code change, no HA change, not committed. Written 2026-10-24; Rev 2 the same day.
**Source premise:** the uploaded "Madrone Super Sensor Specification" Rev 1.0 (`/Users/okosisi/.claude/uploads/75cc297f-1426-4620-b7aa-da058bc0fab0/6c3fc34e-madrone_super_sensor_spec.md`). Its fact-check is `docs/planning/AUDIT_super_sensor_spec_factcheck_2026_10_24.md`.

**Operator direction:**
- Brief: "This is a science experiment. The idea is to replace the hodge podge sensor fleet I have with very capable sensors that can go into each room. Take it serious and find the core set and each variant I want but make it practical."
- Rev 2: "I want ambient sound. I want possible distance sensor. Use the original premise and whittle. Consider only what's not possible first not what is not practical for the rooms."

**Method (Rev 2).** Start from the original spec's full feature set for every node and variant. Remove a feature **only if it is impossible**, meaning one of:
- (a) no ESPHome support and no viable external component;
- (b) physically incompatible;
- (c) a fabricated part capability.

Everything else is **KEPT**, or **FIXED** where it needed a different part, platform or wiring to become possible. Practicality concerns are recorded as **notes, not removals** (§2.4), and the operator decides on them.

**Correction carried in from the fact-check (orchestrator):** since ESPHome 2026.5.0 the ESP32-C6 supports Thread as an FTD/router (`openthread`) and Zigbee as an end device (native `zigbee`, router reportedly). It is never a coordinator or a border router, and it has a single 802.15.4 radio.

**Verification convention:**
- **VERIFIED (url):** I read the esphome.io, vendor or repo page in this session (docs at ESPHome 2026.10.0).
- **EST:** estimate.
- **UNVERIFIED:** I could not confirm it.

§8 lists every unverified item.

---

## 0. The answer in one screen

| | Decision |
|---|---|
| **Core node** | The original "Public Space" node, kept nearly whole: **XIAO ESP32-S3** + **LD2410C** radar (on 5 V) + **AM312 PIR** + **INMP441 mic → native `sound_level`** (level only, no streaming) + **BH1750** lux + **SHT40** T/RH + **MLX90614** IR temp + **VL53L1X ToF** (external component `vl53l1x_sensor`) + **WS2812B** status LED (via `esp32_rmt_led_strip` and a level shifter) + **BLE tracker/proxy**. On-chip fusion is kept but fixed, published as a diagnostic entity only. URA consumes the raw entities. |
| **Distance sensor** | **VL53L1X (4 m)** through community external component `github://soldierkam/vl53l1x_sensor` (VERIFIED README). The only **native** ToF is **VL53L0X** (`vl53l0x` platform, L0X only, "up to 2 m", reliable to ~60 cm, VERIFIED). Use L0X for short throws (bed pod at 60–100 cm), L1X for room or doorway throws. |
| **Ambient sound** | INMP441 I²S MEMS mic + `microphone: i2s_audio` + `sensor: sound_level` with `passive: false`, `rms` + `peak` in **relative dB** (0 dB = mic full scale), not SPL. No audio leaves the node. VERIFIED. |
| **Variants** | **Bedroom** (core with LD2450 in place of LD2410C, ToF bed pod on a tether). **Bathroom** (core minus ToF, plus SGP41; mic optional). **Environment** (no radar; SHT40 + BH1750 + ENS160/AHT2x + optional SCD41 + AQI LED + BLE proxy). **Boomer fall** (Seeed **MR60FDA2** kit, in place of the impossible MR24FDB1). **Boomer vitals** (Seeed **MR60BHA2** kit, in place of the impossible LD2402-as-vitals). |
| **Removed as impossible** | LD2402 as a breathing/heart-rate radar (fabricated capability). MR24FDB1 under ESPHome (no component exists). `neopixelbus` on esp-idf (platform fails; replaced, LED kept). `vl53l0x` platform driving a VL53L1X (register-incompatible; replaced, ToF kept). The old fusion arithmetic (cannot reach its threshold; re-weighted). Invented YAML keys and the uint8-as-int16 mic lambda (replaced with native platforms). ESP32-C5 memory and C6 coordinator/border-router claims (false). |
| **Cost** | Core ≈ **$62–80** per node (EST), bedroom ≈ $75–95, bathroom ≈ $55–70, environment ≈ $30–55, boomer kits ≈ +$35–45 each. |
| **Pilot** | **Study A**: worst measured false hold (~26 h/week, fan on, single ZK), operator is the oracle, low consequence. Pilot 2: **Jaya Bedroom** (bedroom variant vs incumbent LD2410 + fan loop, 68 %). Shadow mode: the node is in HA but not in URA config until it passes. |
| **URA changes** | None to start. Raw binary sensors go into the existing `presence_sensors` / `motion_sensors` lists. The AM312 PIR is a real **fan-immune witness**, which helps D2 and the fan recheck. |
| **Top risks** | (1) LD2410C fan phantom is **measured bad** (Jaya 68 %), so the pilot must measure it, with an LD2412 drop-in fallback. (2) 24 GHz crosstalk with the ~30 Hobeian radars already deployed. (3) +~20 Wi-Fi clients, and BLE proxy-per-node interacting with tuned Bermuda. (4) SHT40 self-heating inside a box with radar, mic, MCU and LED. (5) Mic privacy in bedrooms and bathrooms. |

---

## 1. Current fleet (live `core.config_entries`, read 2026-10-24)

### 1.1 Counts by room type (47 URA room entries)

| Room type | Rooms | Presence-class (holds still) | Motion-class | Notes |
|---|---|---|---|---|
| Bedroom | 5: Master, GB1, GB2, Jaya, Ziri | Master: Screek + ZX + Inovelli mmWave + 2 bed-presence. GB1/GB2: MS600 (Matter). Jaya/Ziri: ESPHome LD2410 (C3) + ZK | ZV / meross motion bit | Most fan-troubled rooms |
| Study / generic | 2: Study A, Study B | Study A: 1 ZK. Study B: 1 ESPHome LD2410 | none | Study A ≈ 26 h/week false hold |
| Media | 1 | MS600 (Matter) | meross motion bit (radar-derived) | No fan-immune witness; D2 fails closed |
| Common / living | 9: Living, Kitchen, Dining, Breakfast, Game, Exercise, Receiving, Patio, Butler | Living: ZX + Screek LD2412. Kitchen: ZX + ESPHome LD2410. Exercise: ZK, never on in 7 days | ZV in most; Protect in Kitchen | |
| Bathroom | 8 | none trusted (Master Bath InvisOutlet behaves motion-class) | Zigbee PIR, Matter RGBW motion-lux, night-light occupancy | MASTER-BATH-NO-TRUSTED-PRESENCE-1 |
| Hallway | 8 | none | ZV / PIR / Matter | Works |
| Closet / pantry / utility / infra | 13 | none | PIR / ZV / Matter | Works |
| Garage | 2 | none | ratgdo / gdo motion + ZV | Works |

Almost every room already has lux, temperature and RH from Hobeian, Matter or Zigbee combo units.

### 1.2 Pain points (PRESENCE_ARCHITECTURE_STATE_OF_PLAY §6, §9, §10)

1. **Fan phantom presence.**
   - Jaya LD2410: 68 % of fan-on empty time reads present. Ledger item 1: "steady fans are innocent" is false for LD2410.
   - Study A ZK: ~26 h/week of false holds.
   - Fan recheck: 27 of 28 releases were undone by the restore loop.
2. **Motion-class in presence roles.**
   - ZV units drop a still person in 30–70 s.
   - The Master Bath InvisOutlet behaves motion-class.
   - The MS600 motion bit is radar-derived, so it is not a fan-immune witness.
3. **Dead radars.** The Exercise Room ZK has zero `on` in 7 days. Some entities have `_presence` / `_presence_2` leftovers.
4. **Protocol sprawl.**
   - Meross is dual-homed native+Matter.
   - ESPHome boards report `esp32-c3-devkitm-1` as the model, so they resolve to family `unknown` (ledger item 9).
   - Zigbee, Matter-over-Wi-Fi, Wi-Fi ESPHome and BLE all coexist.
5. **No raw radar diagnostics** in ZK/ZX. The deferred fan-distance-band option needs ESPHome distance/energy outputs.

### 1.3 Replace vs keep

**Keep:**
- door/window contacts and egress windows;
- water-leak sensors;
- Zigbee buttons and Inovelli switches;
- Master bed-presence strips;
- listed smoke/CO alarms;
- thermostats and Halo panels;
- the tuned Bermuda proxy layout.

Hallway, closet, pantry and stair motion-lux units can stay. Whether a node goes there is a practicality decision (§2.4), not a capability one.

**Replace, in node rooms:** ZK/ZX, the ESPHome LD2410 C3 builds, Screek and MS600 as presence sources; Hobeian T/H/lux as the room's environmental source (after §6 bias tests); ZV/PIR as the motion source, because the node's AM312 *is* a PIR.

---

## 2. Feature ledger: original → kept / fixed / removed

### 2.1 Platform-level claims

| Original | Verdict | Reason / fix | Source |
|---|---|---|---|
| Split S3 (human nodes) / C6 (bath, env) | **KEPT, fixed** | Both chips work. S3 everywhere a mic or camera might go: PDM mic support is ESP32/S3 only, `i2s_audio` doesn't name C6, and S3 has 8 MB PSRAM for BLE proxy + I²S. C6 stays allowed for Bathroom and Environment when no mic is fitted, and the Seeed MR60 kits ship on a C6 | https://esphome.io/components/microphone/i2s_audio/ ; https://esphome.io/components/esp32/ ; https://esphome.io/components/psram/ |
| C6: "no I²S support" | **REMOVED (claim)** | Unverifiable / likely fabricated citation (fact-check E2). Treated as unknown | fact-check |
| C5: "512 KB SRAM, no PSRAM", "stub support" | **REMOVED (claim)** | Wrong / outdated (E3, E4) | fact-check |
| C6 as Zigbee coordinator / Thread border router | **REMOVED (claim)** | Impossible in ESPHome: Thread FTD/router and Zigbee end device only | correction above |
| "C6 BLE ~1 vs S3 ~8 devices" | **REMOVED (claim)** | Fabricated number (E6) | fact-check |
| Standalone ESPHome, native API, OTA | **KEPT** | | fact-check §3 |

### 2.2 Per-feature ledger (union of all original nodes)

| # | Original feature (part, platform) | In original nodes | Verdict | What changed / why | Verified source |
|---|---|---|---|---|---|
| F1 | mmWave presence, **HLK-LD2410C**, `ld2410` | Public, Bath | **FIXED** | Power from **5 V** (spec said 3V3, fatal E1). Real keys: `has_target`/`has_moving_target`/`has_still_target`; `moving_distance`, `still_distance`, `moving_energy`, `still_energy`, `detection_distance`; per-gate `g0–g8` energies only in engineering mode. *Note:* LD2412 (native, 14 gates) is a pin-compatible-in-spirit alternative if the pilot's fan test fails (§6) | https://esphome.io/components/sensor/ld2410/ ; https://esphome.io/components/sensor/ld2412/ |
| F2 | Multi-zone mmWave, **HLK-LD2450**, "external component `hanyuone/ld2450`" | Bedroom | **FIXED** | **Native** `ld2450`; the external repo is fabricated (E10). Keys: `has_target`, `has_moving_target`, `has_still_target`; `target_count`, `still_target_count`, `moving_target_count`; `target_1..3` x/y/speed/angle/distance/resolution; `zone_1..3` counts; numbers `presence_timeout`, `zone_N` x1/y1/x2/y2. 256000 baud | https://esphome.io/components/sensor/ld2450/ |
| F3 | PIR, **AM312**, `binary_sensor: gpio` | Public, Bedroom, Bath | **KEPT** | 3.3 V part on a GPIO input. Gains value in URA: a real PIR is the **fan-immune witness** D2 and the fan recheck need | core `gpio` binary sensor (standard; key set not re-read, §8) |
| F4 | BLE, `esp32_ble_tracker` + `bluetooth_proxy` | all | **KEPT** | `active: false` = adverts only. esp-idf recommended, no web_server, `connection_slots` ≤ 5. *Note:* §2.4 P3 (Bermuda tuning, proxy count) | https://esphome.io/components/bluetooth_proxy/ |
| F5 | **Ambient sound, INMP441** I²S, `microphone: i2s_audio` + custom lambda | Public, Bedroom | **FIXED** | Lambda removed: it treated `uint8_t` bytes as int16, and nothing called `capture` (E14, E15). Replaced with native **`sound_level`** (`passive: false` so it runs the mic itself; `rms`, `peak`, `measurement_duration` 50 ms–60 s, default 1 s; output is **relative dB**, 0 = mic full scale). The mic is wired as an external I²S ADC (`adc_type: external`, `i2s_din_pin`, `channel`, `bits_per_sample`, `sample_rate`). Nothing streams. Absolute dB SPL would need a one-point calibration offset against a meter (INMP441 sensitivity −26 dBFS @ 94 dB SPL per fact-check), applied with a `filters: - offset:` | https://esphome.io/components/sensor/sound_level/ ; https://esphome.io/components/microphone/ ; https://esphome.io/components/microphone/i2s_audio/ ; https://esphome.io/components/i2s_audio/ |
| F6 | Lux, **BH1750**, `bh1750` | all | **KEPT** | `address` 0x23 (0x5C alt), `update_interval`. *Note:* VEML7700 (0x10, auto-range, `glass_attenuation_factor`) is the better low-light part. Optional swap, not a removal | https://esphome.io/components/sensor/bh1750/ ; https://esphome.io/components/sensor/veml7700/ |
| F7 | Status LED, **WS2812B**, `light: neopixelbus` | all | **FIXED** | `neopixelbus` does not work on esp-idf (E13) → **`esp32_rmt_led_strip`** (`pin`, `num_leds`, `chipset: WS2812`, `channel_colors: GRB`; S3 and C6 have RMT). WS2812B at 3V3 supply is out of datasheet → run VDD from **5 V** with a **74AHCT125 level shifter** on data (or use SK6812, same platform, `chipset: SK6812`) | https://esphome.io/components/light/esp32_rmt_led_strip/ |
| F8 | IR human temp, **MLX90614**, `mlx90614` | Public, Bedroom, Bath | **FIXED** | Keys `ambient`, `object` (with `emissivity`, default 1.0; set 0.98 for skin). SMBus: bus at **100 kHz** (spec's 400 kHz was a fault risk, E24). The "5–15 °C person delta" was fabricated (E18), so its fusion weight is cut (F14). *Note:* weak occupancy signal; a narrow-FOV variant (DCI, 5°) aimed at a bed or chair is a real sensor but a different SKU | https://esphome.io/components/sensor/mlx90614/ |
| F9 | **Distance, VL53L1X** via `vl53l0x` platform | Public, Bedroom (bed) | **FIXED** | The `vl53l0x` platform covers **VL53L0X only** ("up to 2 m"; reliable to ~60 cm) and the L1X is register-incompatible (E9). Two working routes: **(a) VL53L1X + external component** `github://soldierkam/vl53l1x_sensor`, platform `vl53l1x_sensor`, `distance_mode` LOW 1.3 m / MEDIUM 3 m / HIGH 4 m, `timing_budget`, `roi_center`/`roi_size`, `enable_pin` (XSHUT), `address`. **(b) VL53L0X native** for throws ≤ ~1 m (`long_range`, `timing_budget`, `enable_pin`, `address`). Choice per variant below. VL53L4CX: no native support found, and I found no maintained ESPHome component in this session → not chosen (not proven impossible either) | https://esphome.io/components/sensor/vl53l0x/ ; https://github.com/m5k10/vl53l1x_sensor (README points to soldierkam) |
| F10 | T/RH, **SHT40**, `sht4x` | all | **FIXED** | No `offset` key (E16): use `filters: - offset:`. Heater off by default (`heater_max_duty: 0`). Needs the thermal layout rules (§2.5). *Note:* SHT45 = same driver, tighter grade | https://esphome.io/components/sensor/sht4x/ |
| F11 | VOC/NOx, **SGP41**, `sgp4x` | Bath | **FIXED** | Keys `voc_index` / `nox_index` (old `voc`/`nox` deprecated, removed 2027.2.0). `compensation: temperature_source/humidity_source` from SHT40 | https://esphome.io/components/sensor/sgp4x/ |
| F12 | eCO₂/TVOC/AQI, **ENS160 + AHT21**, `ens160` + `aht10` | Env | **KEPT** | `ens160` keys `eco2`/`tvoc`/`aqi`, `compensation` (fact-check VERIFIED). `aht10` has `variant: AHT20` ("AHT20 and AHT30"); **AHT21 not named** → UNVERIFIED but expected (AHT2x family); or drop the AHT and compensate from SHT40. Address clash: ENS160 0x52/0x53 vs LTR390 0x53 (LTR390 not used) | https://esphome.io/components/sensor/aht10/ ; fact-check §3 |
| F13 | CO₂, **SCD41**, `scd4x` (optional upgrade) | Env | **KEPT** | `co2`, `temperature_offset` (default 4 °C), `automatic_self_calibration` (default true), `measurement_mode` (periodic / low_power_periodic / single_shot / single_shot_rht_only), `address` 0x62 | https://esphome.io/components/sensor/scd4x/ |
| F14 | **On-chip fusion** (`template` lambdas, weights 0.50/0.25/0.15/0.10, enter 0.70 / exit 0.35) | Public, Bedroom, Bath, Boomer | **FIXED** | Possible, but the math is broken: radar alone cannot reach 0.70 (E19). Fix: radar has_target alone ⇒ occupied (radar weight ≥ threshold); PIR, ToF and sound only *raise* confidence or speed entry; IR weight ≤ 0.05; tuning thresholds exposed as `number` entities so no reflash. Published as `sensor.<node>_fusion_confidence` + `binary_sensor.<node>_fusion_occupied` **for diagnostics/dashboard only. URA does not consume it** (it fuses raw entities by capability; filing a fused radar boolean would hide the radar from fan-noise rejection). Duplicate top-level YAML keys merged; `interval` → one block | fact-check E19–E21 |
| F15 | **Mini cam** (dropped by the original spec's own "improvements") | original premise, Public/Bedroom | **KEPT as option** (not impossible) | `esp32_camera` supports the **XIAO ESP32-S3 Sense** (listed board example). Needs PSRAM + I²C; streams to HA over the native API. The Sense's camera uses the board-to-board connector, not the D-pads, so it does not steal sensor pins (UNVERIFIED pin detail). *Notes:* privacy, heat, RAM contention with BLE proxy + I²S, and URA already gets camera presence from Frigate/Protect. Operator decision | https://esphome.io/components/esp32_camera/ |
| F16 | Fan-automation template binary sensor (Bath) | Bath | **FIXED → moved** | Possible on-chip, but URA owns humidity-fan control (`humidity_fan_*` knobs). Kept as a diagnostic template; not used for actuation | — |
| F17 | AQI RGB indicator (Env) with `id(aqi_led_val)` | Env | **FIXED** | Undefined id (compile fail). Give the `aqi` sensor an `id` and drive `esp32_rmt_led_strip` from it | fact-check §4 |
| F18 | Boomer vitals, **HLK-LD2402** "breathing + heart rate", `screekworkshop/esphome_ld2402` | Boomer bedroom | **REMOVED: impossible (fabricated capability)** | LD2402 is a plain presence radar, not vitals, and the component repo does not exist (E11). **Replacement:** Seeed **MR60BHA2** kit, native `seeed_mr60bha2` (`has_target`, `breath_rate`, `heart_rate`, `distance`, `num_targets`) | https://esphome.io/components/seeed_mr60bha2/ ; https://wiki.seeedstudio.com/getting_started_with_mr60bha2_mmwave_kit/ |
| F19 | Boomer fall, **Seeed MR24FDB1**, "Seeed community ESPHome component" | Boomer public + bath | **REMOVED: impossible (no ESPHome support, no component found)** | Seeed shows Arduino only (E12); fall range ≤ 1.5 m. **Replacement:** Seeed **MR60FDA2** kit, native `seeed_mr60fda2` (`people_exist`, `fall_detected`; selects `install_height`, `height_threshold`, `sensitivity`; buttons `get_radar_parameters`, `factory_reset`) | https://esphome.io/components/seeed_mr60fda2/ ; https://wiki.seeedstudio.com/getting_started_with_mr60fda2_mmwave_kit/ |
| F20 | Boomer = "drop-in swap, rest of stack identical" | Boomer | **FIXED** | The MR60 parts ship as kits (XIAO C6 + BH1750 + WS2812). Practical shape: **kit node + the room's core node side by side**, not one PCB. Bare-module-on-S3 wiring is UNVERIFIED | Seeed wikis |
| F21 | Bed ToF in the same face as the wall radar (§7.7) | Bedroom | **FIXED (physically incompatible as one enclosure)** | Radar wants a 1.8–2.2 m wall; a bed ToF must look down at the mattress from 60–100 cm. Fix: **tethered ToF pod** (4-wire I²C + XSHUT cable, ≤ ~1 m at 100 kHz; EST safe length) on a headboard arm, back to the wall node | fact-check §5 |

### 2.3 Summary of removals (only these)

| Removed | Class |
|---|---|
| LD2402 as a vitals sensor (+ its fake component) | (c) fabricated capability |
| MR24FDB1 under ESPHome (+ its fake component) | (a) no support, no component |
| `neopixelbus` platform on esp-idf | (a) platform fails; LED kept via `esp32_rmt_led_strip` |
| `vl53l0x` platform for a VL53L1X | (b)/(a) register-incompatible; ToF kept via external component or L0X |
| Fusion arithmetic 0.50 vs 0.70 | logic impossible; fusion kept, re-weighted |
| Invented keys, mic lambda, duplicate YAML keys, undefined id | won't compile; replaced by verified keys |
| C5/C6 platform claims (memory, coordinator, BLE numbers) | false claims, no hardware removed |

### 2.4 Practicality notes (NOT removals; operator decides)

| # | Concern | Applies to | Suggested handling |
|---|---|---|---|
| P1 | **LD2410C fan phantom measured at 68 %** (Jaya) | all LD2410C nodes | Pilot measures it. If it fails, swap to LD2412 (native, 14-gate energies, 115200 baud) without changing anything else on the node |
| P2 | **Mic privacy** | bedrooms, bathrooms | Level only in firmware, no `voice_assistant`/streaming components compiled in. A hardware mic-cut jumper on the board. The operator chooses per room |
| P3 | **BLE proxy on every node** vs ~54 existing proxies and tuned Bermuda `scanner_areas`/RSSI | all | Compile it in; enable per node via a template `switch` or only on nodes that replace an existing proxy, so the scanner count does not grow uncontrolled; re-tune Bermuda per room as nodes land |
| P4 | **LED** as a night-light nuisance | bedrooms | `esp32_rmt_led_strip` brightness → 0 in Sleep (HA-side) or a red-only night profile |
| P5 | **MLX90614** is a weak occupancy signal at 90° FOV | all | Kept; fusion weight ≤ 0.05; consider the narrow-FOV SKU for bed/chair |
| P6 | **Self-heating**: radar + MCU + LED + mic + ENS160/SGP41 hotplates in one box | all | §2.5 layout rules, measured in §6 M5 |
| P7 | **24 GHz crosstalk**, more radars next to ~30 Hobeian 24 GHz units | all | Cap gates to room depth; remove replaced radars rather than stacking |
| P8 | **Camera** (F15) duplicates Frigate/Protect | public | Only if a room has no camera and needs one |
| P9 | **Small rooms** (closets, toilets, pantries) are over-served | — | Capability is fine. Whether a $70 node goes in a closet is a budget call |
| P10 | **ENS160 eCO₂ is estimated**, not measured | Env | SCD41 for real CO₂ (both kept) |
| P11 | **I²C at 100 kHz** slows the VL53L1X (its README suggests 400 kHz to avoid slow-operation warnings) | nodes with MLX + L1X | Accept the warnings, or put the ToF on a second I²C bus (costs 2 pins; the bedroom has them, public is tight) |

### 2.5 Thermal layout rules (T/RH credibility)

1. SHT40 on a **tail or chimney below** the electronics, behind its own bottom vents; a solid internal wall + air gap from the MCU, radar, LED, ENS160/SGP41.
2. Electronics vent at the top; sensor vent at the bottom. Convection must not pull warm air over the SHT40.
3. No web_server. Default BLE scan parameters (the docs warn aggressive scans cause heat/instability).
4. Measure bias for 48 h against a reference, then one `filters: - offset:`. If the bias tracks radar/Wi-Fi/LED activity, fix the layout instead.
5. SHT40 is the compensation source for SGP41/ENS160/SCD41.

---

## 3. Core node: "Public Space", whittled

### 3.1 Parts, pins, I²C map

**MCU:** XIAO ESP32-S3 (8 MB octal PSRAM; esp-idf; `variant: esp32s3`). Pads per Seeed (D0=GPIO1 … D5=GPIO6, D6=GPIO43, D7=GPIO44, D8–D10=GPIO7–9), VERIFIED in the fact-check.

| Pad | GPIO | Function | Notes |
|---|---|---|---|
| 5V | — | VBUS in → LD2410C VCC, WS2812B VDD, level shifter VCC | Never radar on 3V3 |
| 3V3 | — | I²C sensors, AM312, INMP441 | |
| D0 | GPIO1 | AM312 PIR out (input) | |
| D1 | GPIO2 | I²S LRCLK/WS → INMP441 WS | |
| D2 | GPIO3 | WS2812B data → 74AHCT125 → LED DIN | GPIO3 is an S3 strapping pin; an idle-low LED line is benign, but ESPHome may warn (UNVERIFIED) |
| D3 | GPIO4 | I²S BCLK/SCK → INMP441 SCK | |
| D4 | GPIO5 | I²C SDA | |
| D5 | GPIO6 | I²C SCL | |
| D6 | GPIO43 | UART TX → LD2410C RX | `logger: baud_rate: 0` |
| D7 | GPIO44 | UART RX ← LD2410C TX | |
| D8 | GPIO7 | I²S DIN ← INMP441 SD | INMP441 L/R pin → GND = left channel |
| D9 | GPIO8 | VL53L1X XSHUT (`enable_pin`) | |
| D10 | GPIO9 | spare (LD2410C OUT, or second-bus SDA for P11) | |

**I²C (single bus, 100 kHz):**

| Addr | Part |
|---|---|
| 0x23 | BH1750 |
| 0x29 | VL53L1X (default; external component allows reassign via XSHUT) |
| 0x44 | SHT40 |
| 0x5A | MLX90614 (SMBus, 100 kHz max) |

No collisions (fact-check §3 VERIFIED).

### 3.2 Power budget (EST unless noted)

| Load | Rail | Current |
|---|---|---|
| LD2410C | 5 V | ~79 mA typ, supply rated >200 mA (fact-check E1) |
| WS2812B ×1–3 | 5 V | ≤ 60 mA per LED at full white; ~5–20 mA typical status |
| S3 Wi-Fi + BLE scan + I²S | 3V3 LDO | ~100–200 mA avg, TX peaks ~350 mA (fact-check §5) |
| VL53L1X, MLX90614, SHT40, BH1750, AM312, INMP441 | 3V3 | ~25 mA total (VL53L1X ~15–20 mA ranging) |
| **Node total** | 5 V in | **~0.3–0.45 A avg, ~0.8 A peak → 5 V / 2 A USB-C supply** (1 A is marginal with 3 LEDs at full) |

PoE: an 802.3af → USB-C 5 V splitter works where a drop exists (power only; XIAO has no Ethernet).

### 3.3 Core YAML skeleton (every key cited)

```yaml
# ROOM SUPER SENSOR v2: CORE ("Public Space")
substitutions:
  node: rss-studya
  room: Study A

esphome:
  name: ${node}
  friendly_name: RSS ${room}

esp32:                              # https://esphome.io/components/esp32/
  variant: esp32s3
  framework:
    type: esp-idf                   # bluetooth_proxy page: esp-idf uses less memory

psram:                              # https://esphome.io/components/psram/
  mode: octal                       # S3 REQUIRES mode
  speed: 80MHz

logger:
  baud_rate: 0                      # free the hardware UART for the radar

api:
  encryption:
    key: !secret rss_api_key
ota:
  - platform: esphome
    password: !secret rss_ota_password

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
# no web_server (RAM + heat; bluetooth_proxy page)

external_components:                # ToF: VL53L1X is not native
  - source: github://soldierkam/vl53l1x_sensor   # https://github.com/m5k10/vl53l1x_sensor README

# ---------- BLE ----------
esp32_ble_tracker:
  scan_parameters:
    active: false                   # fact-check §3 VERIFIED
bluetooth_proxy:                    # https://esphome.io/components/bluetooth_proxy/
  active: false                     # adverts only (Bermuda); see note P3

# ---------- BUSES ----------
i2c:
  sda: GPIO5
  scl: GPIO6
  frequency: 100kHz                 # MLX90614 SMBus limit

uart:
  id: radar_uart
  tx_pin: GPIO43
  rx_pin: GPIO44
  baud_rate: 256000                 # https://esphome.io/components/sensor/ld2410/
  parity: NONE
  stop_bits: 1

i2s_audio:                          # https://esphome.io/components/i2s_audio/
  id: i2s_bus
  i2s_lrclk_pin: GPIO2
  i2s_bclk_pin: GPIO4

microphone:                         # https://esphome.io/components/microphone/i2s_audio/
  - platform: i2s_audio
    id: room_mic
    i2s_audio_id: i2s_bus
    adc_type: external
    i2s_din_pin: GPIO7
    pdm: false
    channel: left
    bits_per_sample: 32bit
    sample_rate: 16000

# ---------- RADAR ----------
ld2410:
  id: radar
  uart_id: radar_uart

binary_sensor:
  - platform: ld2410
    ld2410_id: radar
    has_target:
      name: Presence                # -> URA presence_sensors
      id: radar_presence
    has_moving_target:
      name: Radar Moving            # radar-derived: NOT a fan-immune witness
    has_still_target:
      name: Radar Still
  - platform: gpio                  # AM312 PIR: the fan-immune witness
    pin: GPIO1
    name: PIR Motion                # -> URA motion_sensors
    id: pir
    device_class: motion
  - platform: template              # F14 fixed fusion, DIAGNOSTIC ONLY
    name: Fusion Occupied (diag)
    lambda: |-
      return id(fusion_conf).state >= id(fusion_enter).state;

sensor:
  - platform: ld2410
    ld2410_id: radar
    moving_distance:
      name: Radar Moving Distance
    still_distance:
      name: Radar Still Distance
    moving_energy:
      name: Radar Moving Energy
      id: radar_move_e
    still_energy:
      name: Radar Still Energy
      id: radar_still_e
    detection_distance:
      name: Radar Detection Distance

  - platform: sound_level           # https://esphome.io/components/sensor/sound_level/
    passive: false                  # node drives the mic itself; nothing streams
    measurement_duration: 1000ms
    microphone:                     # https://esphome.io/components/microphone/ (source schema)
      microphone: room_mic
      channels: [0]
    rms:
      name: Sound Level RMS         # relative dB (0 = mic full scale)
      id: sound_rms
      filters:
        - throttle: 10s             # protect the API/recorder
    peak:
      name: Sound Level Peak
      filters:
        - throttle: 10s

  - platform: vl53l1x_sensor        # external component (README keys)
    name: Distance
    id: tof
    enable_pin: GPIO8
    distance_mode: MEDIUM           # LOW 1.3 m / MEDIUM 3 m / HIGH 4 m
    timing_budget: 200ms
    update_interval: 1s
    filters:
      - throttle: 5s

  - platform: bh1750                # https://esphome.io/components/sensor/bh1750/
    name: Illuminance
    address: 0x23
    update_interval: 30s

  - platform: sht4x                 # https://esphome.io/components/sensor/sht4x/
    address: 0x44
    update_interval: 30s
    temperature:
      name: Temperature
      id: room_t
      # filters: [ { offset: -0.0 } ]   # only from the §6 M5 measurement
    humidity:
      name: Humidity
      id: room_rh

  - platform: mlx90614              # https://esphome.io/components/sensor/mlx90614/
    ambient:
      name: IR Ambient
    object:
      name: IR Object
      id: ir_obj
      emissivity: 0.98

  - platform: template              # F14 fixed fusion confidence, DIAGNOSTIC ONLY
    name: Fusion Confidence (diag)
    id: fusion_conf
    update_interval: 2s
    lambda: |-
      float c = id(radar_presence).state ? 0.75 : 0.0;   // radar alone >= enter
      if (id(pir).state) c += 0.15;
      if (!isnan(id(sound_rms).state) && id(sound_rms).state > id(sound_gate).state) c += 0.05;
      if (!isnan(id(ir_obj).state) && !isnan(id(room_t).state)
          && id(ir_obj).state - id(room_t).state > 1.0) c += 0.05;
      return c > 1.0 ? 1.0 : c;

number:                             # fusion tuning without reflash
  - platform: template
    name: Fusion Enter Threshold
    id: fusion_enter
    min_value: 0.3
    max_value: 1.0
    step: 0.05
    initial_value: 0.7
    optimistic: true
    restore_value: true
  - platform: template
    name: Sound Gate (rel dB)
    id: sound_gate
    min_value: -90
    max_value: 0
    step: 1
    initial_value: -50
    optimistic: true
    restore_value: true

light:                              # https://esphome.io/components/light/esp32_rmt_led_strip/
  - platform: esp32_rmt_led_strip
    name: Status LED
    pin: GPIO3
    num_leds: 1
    chipset: WS2812
    channel_colors: GRB
```

**Keys not individually re-read this session** (core components, used in the house's working `jaya-3.yaml` or long-standing): `i2c` base keys; `uart` base keys; `logger.baud_rate`; `gpio` binary sensor `pin`/`device_class`; `template` binary_sensor/sensor/number keys (`lambda`, `update_interval`, `min_value`, `max_value`, `step`, `initial_value`, `optimistic`, `restore_value`); `filters: throttle`; `i2s_audio_id` on the mic (listed in the fact-check's VERIFIED set); `esp32_ble_tracker.scan_parameters.active` (fact-check VERIFIED). External component keys come from its README, not esphome.io. The fusion lambda's `isnan` and `.state` access are standard ESPHome C++ but not compiled here. **Nothing in this doc has been compiled.**

---

## 4. Variants (deltas on core) and room mapping

### 4.1 Bedroom (original 2.2): Master, Jaya, Ziri, GB1, GB2

| Delta | Detail |
|---|---|
| Radar | **LD2450 replaces LD2410C** (original choice, now native): same UART pins, `baud_rate: 256000`. Exposes `target_count` / still / moving counts and 3 zones. *Note P1-b:* LD2450 is the weaker still-holder (community, UNVERIFIED). If Jaya's M1 fails, add an LD2412 on UART2 (D9/D10) as the still-holder |
| ToF | **Tethered bed pod** (F21): **VL53L0X native** (bed at 60–100 cm is inside its reliable band) via `vl53l0x` platform, `address: 0x29`, `long_range: false`, `timing_budget: 33000us`. Or VL53L1X LOW mode via the external component if the mount is higher. Delta = empty-bed vs occupied-bed distance → template binary "bed occupied (ToF)" |
| Sound | Kept (snoring/TV level). Note P2 |
| LED | Kept; night profile (P4) |
| MLX90614 | Kept; aim at the bed if possible (P5) |
| BLE | Kept (P3) |
| SHT40 | Kept (sleep environment) |
| Recommended add (original Env feature) | SCD41 on the same bus (0x62). Shut-door CO₂ is the most useful bedroom air metric (P10) |

YAML delta (keys VERIFIED: https://esphome.io/components/sensor/ld2450/ , https://esphome.io/components/sensor/vl53l0x/):
```yaml
ld2450:
  id: tracker
  uart_id: radar_uart            # radar_uart baud_rate: 256000
binary_sensor:
  - platform: ld2450
    ld2450_id: tracker
    has_target:
      name: Presence
    has_moving_target:
      name: Radar Moving
    has_still_target:
      name: Radar Still
sensor:
  - platform: ld2450
    ld2450_id: tracker
    target_count:
      name: Target Count
    still_target_count:
      name: Still Targets
    moving_target_count:
      name: Moving Targets
    zone_1:
      target_count:
        name: Bed Zone Targets
  - platform: vl53l0x            # bed pod (replaces vl53l1x_sensor on this variant)
    name: Bed Distance
    id: bed_tof
    address: 0x29
    long_range: false
    timing_budget: 33000us
    update_interval: 2s
number:
  - platform: ld2450
    ld2450_id: tracker
    presence_timeout:
      name: Radar Timeout
    zone_1:
      x1:
        name: Bed Zone X1
      y1:
        name: Bed Zone Y1
      x2:
        name: Bed Zone X2
      y2:
        name: Bed Zone Y2
```

### 4.2 Bathroom (original 2.3): Master Bath, Jaya Bath, Ziri Bath (+ optional small baths)

| Delta vs core | Detail |
|---|---|
| ToF | **Removed by the original's own choice** (not impossibility). Can be re-added: pins are free |
| Mic | Original excluded it. **Kept as an option** per the operator's "I want ambient sound": S3 build only; strong privacy note P2 |
| Add | **SGP41** (0x59) with SHT40 compensation (F11) |
| Board | Original said C6. **C6 allowed if no mic** (`variant: esp32c6`, esp-idf). With a mic, use S3 |
| Physical | Conformal coat; PTFE vent on the SHT40 chamber; radar not aimed at shower glass, water flow or the exhaust fan (Seeed and Hi-Link guidance on water and vibration). SHT40 `update_interval: 10s` for URA's humidity-spike fan logic |
| Fan template (F16) | Diagnostic only; URA actuates |

YAML delta (https://esphome.io/components/sensor/sgp4x/):
```yaml
sensor:
  - platform: sgp4x
    update_interval: 60s
    store_baseline: true
    compensation:
      temperature_source: room_t
      humidity_source: room_rh
    voc_index:
      name: VOC Index
    nox_index:
      name: NOx Index
```

### 4.3 Environment (original 2.4): any room, standalone or beside a core node

No radar, PIR, mic or ToF (by the original's design). Parts: SHT40 + BH1750 + **ENS160 + AHT2x** (F12) + optional **SCD41** (F13) + **AQI WS2812B** (F17 fixed) + **BLE proxy**. C6 or S3.

```yaml
sensor:
  - platform: ens160              # keys per fact-check §3 (VERIFIED)
    eco2:
      name: eCO2
    tvoc:
      name: TVOC
    aqi:
      name: AQI
      id: aqi_val                 # fixes undefined id(aqi_led_val)
    compensation:
      temperature: room_t
      humidity: room_rh
  - platform: scd4x               # https://esphome.io/components/sensor/scd4x/
    address: 0x62
    measurement_mode: periodic
    automatic_self_calibration: true
    co2:
      name: CO2
```
(`aht10` with `variant: AHT20` only if the combo board's AHT is used; AHT21 is not named on the page.)

### 4.4 Boomer fall (original 2.5 row 1/3, MR24FDB1 → **MR60FDA2**)

Seeed MR60FDA2 kit (XIAO C6 + BH1750 + WS2812). Mount **top-down at 2.2–3.0 m**, 2 m sensing radius, 3×3×3 m fall zone. Use as a second node beside the room core.

```yaml
esp32:
  variant: esp32c6
  framework:
    type: esp-idf
uart:
  id: fall_uart
  baud_rate: 115200
  parity: NONE
  stop_bits: 1
  # tx_pin/rx_pin: from Seeed's shipped kit YAML (UNVERIFIED here)
seeed_mr60fda2:                   # https://esphome.io/components/seeed_mr60fda2/
  uart_id: fall_uart
binary_sensor:
  - platform: seeed_mr60fda2
    people_exist:
      name: Person Present
    fall_detected:
      name: Fall Detected
select:
  - platform: seeed_mr60fda2
    install_height:
      name: Install Height
    height_threshold:
      name: Fall Height Threshold
    sensitivity:
      name: Fall Sensitivity
button:
  - platform: seeed_mr60fda2
    get_radar_parameters:
      name: Read Radar Params
    factory_reset:
      name: Radar Factory Reset
```

### 4.5 Boomer vitals (original 2.5 row 2, LD2402 → **MR60BHA2**)

Seeed MR60BHA2 kit. Mount ~1 m above the head of the bed, 45° down, chest within 1.5 m. Sleep-only accuracy (Seeed warns of "significant inaccuracies" otherwise).

```yaml
seeed_mr60bha2:                   # https://esphome.io/components/seeed_mr60bha2/
  uart_id: vitals_uart            # 115200, NONE, 1
binary_sensor:
  - platform: seeed_mr60bha2
    has_target:
      name: Bed Presence (radar)
sensor:
  - platform: seeed_mr60bha2
    breath_rate:
      name: Breath Rate
    heart_rate:
      name: Heart Rate
    distance:
      name: Distance
    num_targets:
      name: Targets
```

### 4.6 Room mapping (capability-first; budget trims are notes)

| Variant | Rooms |
|---|---|
| Core (Public) | Study A, Study B, Media, Living, Kitchen, Dining, Breakfast, Game, Exercise, Receiving, Butler; optionally hallways (8), Foyer, Patio (outdoor rating not covered) |
| Bedroom | Master, Jaya, Ziri, GB1, GB2 |
| Bathroom | Master Bath, Jaya Bath, Ziri Bath; optionally Powder, Toilet, Vanity, GB baths |
| Environment | Kitchen (beside core, for ENS160/SCD41), AV Closet, Laundry, garages (temperature extremes: check part ratings, UNVERIFIED) |
| Boomer | Not deployed today; any bedroom/bath when needed |

The full-coverage count is ~19 core + 5 bedroom + 3–8 bath + ~4 env. A practical first wave is ~20 nodes in the rooms URA fuses hardest (bedrooms, studies, media, living/kitchen, 3 baths).

---

## 5. BOM (EST, USD single-unit retail, Oct 2026; not checked against live listings)

| Item | Core | Bedroom | Bath | Env |
|---|---|---|---|---|
| XIAO ESP32-S3 (C6 for env/bath-no-mic) | $7.50 | $7.50 | $5–7.50 | $5–7.50 |
| LD2410C / LD2450 | $4–6 | $12–15 (LD2450) | $4–6 | — |
| AM312 PIR | $1.50 | $1.50 | $1.50 | — |
| INMP441 mic | $3–4 | $3–4 | ($3–4 opt) | — |
| BH1750 | $1.50 | $1.50 | $1.50 | $1.50 |
| SHT40 (SHT45 +$4) | $5–8 | $5–8 | $5–8 | $5–8 |
| MLX90614 (BAA) | $8–12 | $8–12 | $8–12 | — |
| VL53L1X (core) / VL53L0X (bed pod) | $8–12 | $4–6 + cable $2 | — | — |
| WS2812B + 74AHCT125 | $1.50 | $1.50 | $1.50 | $1.50 |
| SGP41 | — | — | $12–18 | — |
| ENS160+AHT21 combo | — | — | — | $8–12 |
| SCD41 (optional) | — | (+$30–50 rec.) | — | (+$30–50) |
| USB-C 5 V/2 A supply + cable | $8–10 | $8–10 | $8–10 | $6–8 |
| PETG enclosure, vents, wire, headers | $4–6 | $5–7 | $5–8 | $3–5 |
| **Node total (EST)** | **~$62–80** | **~$65–85** (+SCD41 → $95–135) | **~$55–75** | **~$30–45** (+SCD41 → $60–95) |
| MR60FDA2 / MR60BHA2 kit | | | | +$35–45 each (EST) |

First wave of 20 (11 core, 5 bedroom with SCD41, 3 bath, 1 env): ≈ 11×$70 + 5×$110 + 3×$65 + $50 ≈ **$1,570** (EST).

---

## 6. How URA consumes it (raw, per capability; no fused entity)

| Node entity | URA field | Capability | Notes |
|---|---|---|---|
| `binary_sensor.<node>_presence` (LD2410C/LD2450 `has_target`) | `presence_sensors` (`CONF_MMWAVE_SENSORS = "presence_sensors"`, `const.py:480`) | radar, holds still, **fan-susceptible** | |
| `binary_sensor.<node>_pir_motion` (AM312) | `motion_sensors` | **PIR, fan-immune witness** | Unlocks D2 demotion + fan recheck in rooms that have none today (Media, GB1, GB2) |
| `…_radar_moving` / `…_radar_still` | **unfiled** | radar-derived | Filing `radar_moving` as motion repeats the D2-PIR-STAMP defect (§6 of the presence doc) |
| `…_fusion_occupied (diag)` / `…_fusion_confidence (diag)` | **unfiled** | fused | Dashboard only. Filing it would hide the radar from fan rejection |
| `…_bed_distance`, ToF template "bed occupied" | candidate `presence_sensors` *after* pilot (bed class, like the Master bed strips) | bed | |
| `…_sound_level_rms/peak`, `…_distance`, `…_ir_object`, radar distance/energy, LD2450 counts | unfiled sensors (room lists accept `binary_sensor` only) | diagnostic | Future consumers: fan-distance-band, TV/activity hints, census headcount |
| `…_temperature` / `…_humidity` / `…_illuminance` | `temperature_sensor` / `humidity_sensor` / `illuminance_sensor` | — | Only after §7 M4–M6 pass |
| `…_co2`, `…_voc_index`, `…_nox_index`, `…_eco2`, `…_aqi` | house `global_aq_sensors` exists (config key seen); no per-room AQ field | display | Per-room AQ use = future card |
| MR60FDA2 `fall_detected` | none; NM via a future card | safety-adjacent | Not life-safety-listed |
| MR60BHA2 `has_target` | `presence_sensors` candidate after test | radar near-field | |

**URA changes required: none.** Known wart: ESPHome reports the board as the device model, so the node resolves to family `unknown` (ledger item 9). Radar entities are still excluded as witnesses via the name fallback, which is correct, and the AM312 is filed under `motion_sensors`. **UNVERIFIED:** whether `is_fan_immune_motion_witness` keeps a PIR whose *device* family is `unknown`. Per §5 of the presence doc it keeps motion-kind entities whose family is not in `RADAR_SENSOR_FAMILIES`, and `unknown` is not, so it should be kept. The pilot confirms this from the D2 attributes.

---

## 7. Rollout

### 7.1 Pilot rooms

1. **Study A** (core).
   - Worst measured false hold (~26 h/week, fan on): STUDYA-ZK-EMPTY-HOLD-1.
   - The ZK is its only presence source.
   - The operator is the oracle, and mistakes are cheap.
2. **Jaya Bedroom** (bedroom variant), after Study A passes.
   - Gives a direct comparison against the incumbent LD2410 + fan loop (68 %).
   - Tests the ToF bed pod and the LD2450 still-hold.

7 days each. **Shadow:** the node is in HA but not in URA config.

### 7.2 Acceptance measurements (one-shot recorder queries at day 7; no soak watching)

Ground truth: BLE room location ±3 min (2026-10-11 method), plus operator-confirmed still periods.

| # | Measurement | Pass | Discriminates against |
|---|---|---|---|
| M1 | Still-person hold (BLE-occupied minutes with no PIR event ≥ 10 min where `presence` on) | ≥ incumbent and ≥ 95 % | motion-class behaviour (30–70 s drop) |
| M2 | Fan false occupancy (presence-on while BLE empty + fan on, per hour) | ≤ 0.1 h/h and ≤ 25 % of incumbent | "LD2410C repeats Jaya's 68 %". On fail: swap to LD2412 (P1) and re-run once |
| M3 | Empty-room false positives, fan off, adjacent room occupied | ≤ incumbent | 24 GHz crosstalk |
| M4 | Lux vs handheld meter at 5 levels | ±15 % (±5 lx < 30 lx) | enclosure window attenuation |
| M5 | SHT40 bias vs reference, 48 h | stable, σ < 0.2 °C after one offset; no correlation with radar/LED/Wi-Fi activity | layout failure |
| M6 | RH vs reference | ±2 % | |
| M7 | Sound: `rms` vs a phone SPL app at quiet / talk / TV | monotonic; one offset gives ±3 dB | broken I²S config (flat or saturated reading) |
| M8 | ToF: core throw to a fixed wall; bed pod empty vs occupied | ±3 cm wall; ≥ 10 cm separation bed | wrong platform/mode, ROI misaim |
| M9 | PIR as witness: D2 / recheck attributes in URA show the node PIR counted | seen ≥ 1× | witness classifier rejecting `unknown` family |
| M10 | Uptime: reboots, API disconnects, RSSI, heap | 0 unexplained reboots; < 1 disconnect/day | RAM pressure from BLE proxy + I²S |

**Go/no-go per room type:**
- **Presence:** decided by M1–M3.
- **Replacing the Hobeian T/RH/lux:** decided by M4–M6.
- **Bedroom:** needs Jaya to pass M1/M2/M8.
- **Bathroom:** needs one bath pilot for still-bather M1 and RH response.

### 7.3 Enclosure and mounting

- PETG; no metallic or carbon fill; radar window ≤ 2 mm plain plastic.
- Two chambers:
  - **upper:** MCU, radar, LED and gas sensors, with top vents;
  - **lower tail:** SHT40 behind a bottom vent or PTFE membrane, with a wall and an air gap between the chambers.
- Front-face windows: the BH1750 behind clear plastic; the VL53L1X and MLX90614 apertures unobstructed (no plastic over the ToF or IR, which attenuates both); the mic port with a dust mesh.
- Wall mount 1.8–2.2 m with 0/10/20° tilt wedges, USB-C from below. The bedroom bed pod is a separate small housing on a headboard arm.
- Bath: conformal coat and a drip edge.

### 7.4 Firmware management

- One `packages:` common file per variant plus per-room substitutions in `/config/esphome/`. Check the `packages` syntax at https://esphome.io/components/packages/ before writing it (not re-read).
- Pin the ESPHome version and the external component's git ref. Upgrade one pilot node first.
- Secrets in `secrets.yaml` only. The existing node YAMLs carry inline API keys and passwords; don't copy that.
- Throttle sound, ToF and radar-energy sensors. Add the high-rate diagnostics to the recorder excludes (`docs/planning/RUNBOOK_recorder_excludes.md`) if left enabled.
- Do not update MR60 radar firmware without cause: Seeed warns it can brick.

### 7.5 Failure modes

| Mode | Mitigation |
|---|---|
| Wi-Fi congestion (+20–35 clients) | No web_server, throttled sensors, push-on-change radar. Read-only UniFi per-AP 2.4 GHz client count before the wave |
| 2.4 GHz Wi-Fi/BLE/Zigbee coexistence | Default BLE scan parameters; Zigbee channel non-overlapping with Wi-Fi |
| BLE proxy growth vs Bermuda | P3: enable per node; retire nearby proxies; re-tune per room |
| 24 GHz crosstalk | Cap gates to room depth; aim away from shared walls; remove replaced radars |
| Fan phantom | Placement, LD2412 fallback, keep URA's D2/recheck. The node PIR is the witness |
| Self-heating | §2.5 + M5 |
| RAM pressure (BLE proxy + I²S + PSRAM) | S3 with PSRAM; `connection_slots` ≤ 5; M10 heap check |
| Mic privacy | P2; no audio components beyond `sound_level` |
| External component rot (`vl53l1x_sensor`) | Pin a git ref; VL53L0X native fallback for short throws |
| SCD41 ASC drift in unaired rooms | Disable `automatic_self_calibration` there; calibrate manually |

---

## 8. NOT verified / estimates

1. **Nothing in this doc has been compiled.** YAML keys are checked against the docs, not a build.
2. Core keys not re-read: `i2c`, `uart` base, `logger.baud_rate`, `gpio` binary sensor, `template` sensor/binary/number keys, `filters: throttle`, `packages`.
3. `vl53l1x_sensor` external component: keys from the README only; maintenance status, last commit, esp-idf compatibility and ESPHome 2026.10 compatibility not checked. The README source owner (soldierkam) differs from the fork URL (m5k10).
4. VL53L4CX: no ESPHome support found in this session. Not proven impossible; not chosen.
5. `aht10 variant: AHT20` driving an **AHT21**: not named on the docs page.
6. LD2410C fan behaviour vs LD2412: measured bad for LD2410 (Jaya); LD2412 unmeasured. LD2412 power from a reseller listing only.
7. LD2450 still-person drop-out: community reports.
8. GPIO3 strapping-pin warning on S3; XIAO S3 logger default port under esp-idf.
9. S3 three hardware UARTs (bedroom LD2412-fallback on UART2): Espressif datasheet not re-read.
10. XIAO S3 Sense camera pins do not conflict with the D-pads; the Sense onboard PDM mic pin mapping.
11. Seeed MR60 kit UART pins; bare MR60 modules wired to an S3.
12. Whether URA's witness classifier keeps a PIR on an `unknown`-family ESPHome device (M9 tests it).
13. All prices (§5) and all current figures (§3.2) are estimates.
14. I²C tether length for the bed pod (~1 m at 100 kHz) is an engineering estimate.
15. INMP441 sensitivity figure and the SPL calibration approach are from the fact-check, not a datasheet read here.
16. The ~54 proxy count is an operator/orchestrator figure.
17. MR60FDA2 FoV: Seeed gives two conflicting figures. Neither MR60 kit is a listed life-safety device.
18. Mounting height 1.8–2.2 m for LD24xx is typical practice, not a Hi-Link spec read here.

## Sources (read 2026-10-24)

esphome.io:
- https://esphome.io/components/sensor/ld2410/
- https://esphome.io/components/sensor/ld2412/
- https://esphome.io/components/sensor/ld2450/
- https://esphome.io/components/seeed_mr60bha2/
- https://esphome.io/components/seeed_mr60fda2/
- https://esphome.io/components/sensor/sound_level/
- https://esphome.io/components/microphone/
- https://esphome.io/components/microphone/i2s_audio/
- https://esphome.io/components/i2s_audio/
- https://esphome.io/components/sensor/vl53l0x/
- https://esphome.io/components/sensor/sht4x/
- https://esphome.io/components/sensor/scd4x/
- https://esphome.io/components/sensor/sgp4x/
- https://esphome.io/components/sensor/mlx90614/
- https://esphome.io/components/sensor/aht10/
- https://esphome.io/components/sensor/bh1750/
- https://esphome.io/components/sensor/veml7700/
- https://esphome.io/components/sensor/ltr390/
- https://esphome.io/components/light/esp32_rmt_led_strip/
- https://esphome.io/components/bluetooth_proxy/
- https://esphome.io/components/esp32/
- https://esphome.io/components/psram/
- https://esphome.io/components/esp32_camera/

Vendor and community:
- https://github.com/m5k10/vl53l1x_sensor
- https://wiki.seeedstudio.com/getting_started_with_mr60bha2_mmwave_kit/
- https://wiki.seeedstudio.com/getting_started_with_mr60fda2_mmwave_kit/
- https://openelab.io/da/products/ld2410-sensing-radar-module (LD2412 reseller specs)

House:
- `/Users/okosisi/ha-config/.storage/core.config_entries`
- `/Users/okosisi/ha-config/esphome/{jaya-3,screekld2412-livingroom,mmwave-lux-wifi-esphome-studyb}.yaml`
- `docs/architecture/SENSOR_FLEET_CLASSES.md`
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`
- the fact-check audit
