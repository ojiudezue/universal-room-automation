# AUDIT: recorder write rate, last 24h (probe 2026-10-20 07:53-08:00 CDT)

Read-only. Source: `/config/home-assistant_v2.db` opened `mode=ro`, window `last_updated_ts > now-86400`; states JOIN states_meta; "stats" = entity_id present in statistics_meta. Config: `/config/configuration.yaml:12-52`.

## Answer first
Two entities dominate and have no recorder value: the ESPectre test movement score (~5,000 rows/hr, 94.6k distinct floats) and the UDM CPU/memory pair (~3,760 rows/hr combined). Jaya 3 `detection_distance` (886/hr) is high because the ESPHome yaml has NO filters and a person is present; it is not misconfigured relative to its sibling Ziri 3 (identical yaml, 0.2/hr because that room is empty).

## 1. Top 25 by rows/hr (24h)
| # | entity | rows/hr | distinct | stats |
|---|---|---|---|---|
| 1 | sensor.espectre_test_movement_score | 4998 | 94598 | yes |
| 2 | binary_sensor.madronewatermonitor_low_flow_leak | 2065 | 2 | no |
| 3 | sensor.phalanxudmpro_memory_utilization_2 | 1999 | 54 | yes |
| 4 | sensor.phalanxudmpro_cpu_utilization_2 | 1765 | 244 | yes |
| 5 | sensor.living_room_time_since_motion | 1362 | 6263 | no |
| 6 | sensor.living_room_illuminance | 1321 | 256 | yes |
| 7 | sensor.invisoutlet_b7d0_co2 | 1078 | 820 | no |
| 8 | ...invisoutet_mqtt_masterbath_co2 | 1058 | 802 | no |
| 9 | automation.frigate_mqtt_to_frigate_events_bridge_ura_snapshot_support | 896 | 1 | no |
| 10 | sensor.jaya_3_detection_distance | 886 | 123 | no |
| 11 | ...masterbath_pressure | 863 | 422 | no |
| 12 | sensor.invisoutlet_b7d0_pressure | 860 | 426 | no |
| 13 | ...masterbath_voc | 841 | 461 | no |
| 14 | sensor.invisoutlet_b7d0_voc | 769 | 269 | no |
| 15 | sensor.garage_kitchenhallway_device_time | 719 | 17243 | no |
| 16 | sensor.dimmer_tapo_wifi_matter_khallway_device_time | 718 | 17237 | no |
| 17 | sensor.invisoutlet_b7d0_illuminance | 711 | 4507 | no |
| 18 | sensor.study_a_illuminance | 711 | 4504 | yes |
| 19 | sensor.tapo_s515d_take_2_device_time | 706 | 16953 | no |
| 20 | sensor.ezinne_iphone_nearest_rssi | 659 | 65 | yes |
| 21 | sensor.wall_panel_master_bridge_..._humidity | 655 | 640 | no |
| 22 | sensor.iphone_oji_nearest_rssi | 655 | 76 | yes |
| 23 | sensor.smart_plug_pm_current_consumption | 639 | 34 | yes |
| 24 | sensor.wall_panel_master_bridge_..._temperature | 621 | 374 | no |
| 25 | sensor.master_bedroom_iphone_ezinne_distance_to_mmwave_lux_screekl13s_wifi_masterbedroom | 582 | 2190 | yes |

Notes: the "stats" column is true when the entity has a statistics_meta row, i.e. a long-term-statistics `state_class`. Rows 2 and 9 are a binary_sensor / automation (automation state rows are attribute-change writes: 1 distinct state, so `last_triggered` or attribute churn; not investigated). The wall_panel master bridge rows pre-date homelab bridge 1.6.9 deadband (see homelab CONFIGS.md:705-713, which says sensors dropped to a handful per hr on panels now on 1.6.9; Master still shows 620-655/hr here, so its rollout is unverified). Pre-existing excludes (config.yaml:17-46) already cover screek/mmwave_/still/move/rx/tx/unfiltered Bermuda/Study B kiosk.

## 2. ESPectre
- Entities: 24 `*espectre_test*`. Only `sensor.espectre_test_movement_score` is hot; `binary_sensor.espectre_test_motion_detected` 98/hr (3 states); all others 0.1/hr.
- movement_score: 5017 rows in the last hour; range 0.0-1.0; 94,598 distinct values/24h (float noise like 1.3e-08); median |delta| between consecutive rows 6e-07, p90 0.155, zero-delta fraction 0 (every row is a new float); median gap 0.26 s. Matches `evaluation_interval_ms: 250` (`/config/esphome/espectre-test.yaml`, espectre block).
- Device: ESPHome (ESP32-C6), `/config/esphome/espectre-test.yaml`, package `github://francescopace/espectre/.../espectre-source-github.yaml@main`. Sensor is defined inside the external package, so its filters/update_interval are NOT in the local yaml (unknown without reading the package; I did not fetch it). The local lever is `evaluation_interval_ms` (comment: "250-1000 recommended; detector and live telemetry interval").
- Producer/consumer: no URA code or room reads it (probe did not grep the repo; homelab CONFIGS.md:713 hands this to URA as a test sensor to exclude/purge). The 12 `csi_*_rate`/rssi diagnostics have statistics but only 0.1/hr.
- homelab-automation: only references are docs/CONFIGS.md:713, a vibememo entry and sites/urakanban/index.html; no ESPectre config there.

## 3. Jaya 3 vs other mmWave boards
| board | yaml | detection/moving distance rows/hr | recorded? |
|---|---|---|---|
| jaya-3 (ESP32-C3, LD2410, BLE proxy) | jaya-3.yaml | detection_distance 886, moving_distance 19, still/energy sensors not in top (see below) | yes, no glob matches `jaya_3_detection_distance` |
| ziri-3 (same board/yaml) | ziri-3.yaml | detection_distance 0.2 | yes |
| livingroom/master LD2412 (screek) | screekld2412-livingroom.yaml, mmwave-lux-ble-screekld241s-mas.yaml | n/a | excluded by `sensor.screek_human_sensor_*`, `*still_*`, `*move_*` globs |
| kitchen/studyb LD2410 | mmwave-lux-wifi-esphome-*.yaml | n/a | `sensor.mmwave_*` excluded |

- jaya-3.yaml and ziri-3.yaml are line-for-line identical apart from name, keys and IP. Neither has any `filters:` (no throttle, delta, or_, heartbeat) and neither sets `update_interval` on the ld2410 sensors (veml7700 only: 10s). The grep of the other boards found only `update_interval` values (LD2412 boards: 1s on the ld2412 platform line, 30-600s on others; LD2410 kitchen/studyb: 10s on the lux sensor) and no throttle/delta/or_ filters.
- Why Jaya writes more: the filterless ld2410 `detection_distance` publishes whenever the radar reports a new value (jaya: median gap 1.26 s in the last hour, 542 rows/hr in the sampled hour, values 13.8-63.4 cm... unit as reported, median |delta| 1.18, p90 8.3). The distance only moves while there is a target; Ziri 3's room is evidently still/empty so the value rarely changes (5 distinct values/24h). It is occupancy-driven, not config-driven. I did not verify in the ESPHome ld2410 source whether it suppresses unchanged values; the 0 zero-delta rows in Jaya's data are consistent with changes-only publication.
- Other Jaya rows: veml7700 ambient light 102/hr (10 s poll with a stats state_class), iphone_jaya_distance_to_jaya_3 201/hr (Bermuda, filtered).

## 4. UDM CPU/memory
- `sensor.phalanxudmpro_cpu_utilization_2` 1765/hr (244 distinct, stats yes), `..._memory_utilization_2` 1999/hr (54 distinct, stats yes). Last hour medians: CPU gap 2.2 s, |delta| 2.0 (range 11.6-29.6); memory gap 1.2 s, |delta| 0.1 (38.8-40.1).
- Integration: core `unifi` (entity registry platform `unifi`), config entry "Default", `/config/.storage/core.config_entries`. Options: allow_bandwidth_sensors False, allow_uptime_sensors True, track_clients/devices/wired_clients True, detection_time 300, dpi_restrictions True, ssid_filter [...]. There is NO poll/scan interval option. The ~1-2 s cadence suggests push (websocket) updates, but I did not read the unifi component source (docker access denied; web search could not confirm), so push-vs-poll is unverified. Hence no integration-side throttle.

## 5. Recorder config (`/config/configuration.yaml:12-52`)
`purge_keep_days: 7`, `commit_interval: 5`, `auto_purge: true`, `auto_repack: true`, exclude: 1 entity (`sensor.envoy_..._energy_consumption_today`) plus globs: `sensor.*_rx|tx` variants, `*still_energy*`, `*still_distance*`, `*move_energy*`, `*move_distance*`, `sensor.screek_human_sensor_*`, `sensor.mmwave_*`, `*_unfiltered_distance_to_*`, `envoy_stream_data_timestamp|age`, and the Study B kiosk globs. No include list. Entity-level exclusions apply to ALL consumers of history/stats, not just the DB.

## Recommended attenuation (ranked by rows removed)
| entity | rows/hr | recommendation | alternative |
|---|---|---|---|
| espectre_test_movement_score (+ binary 98/hr) | 4998 | Exclude `sensor.espectre_test_*` movement score from recorder (test device, no consumer). If it must be kept, raise `evaluation_interval_ms` to 1000 and, in an override of the package sensor, add `filters: [throttle_average: 10s]` with `or:`-style heartbeat (`delta: 0.05` + `throttle: 60s`) | Recorder exclude is the cleanest; device-side only possible if the package sensor can be overridden (unverified) |
| UDM cpu 1765 + mem 1999 | 3764 | HA-side only: recorder exclude (loses CPU/mem statistics, which exist today) or a template sensor with `state: ... ` + `delay`/`trigger: time_pattern /1 minute` recorded in place of the raw ones, excluding the raw entities | No integration knob exists (verified options). Disabling `_2` entities loses the live value |
| jaya_3_detection_distance | 886 | ESPHome: `filters: [ delta: 5, or: [ throttle: 30s ] ]` ... in ESPHome terms `filters: - or: [ - delta: 5.0 - throttle: 30s ]` on the `detection_distance` sensor (and the same on `moving_distance` for parity; apply to ziri-3.yaml too for consistency). Presence binaries are unaffected | Add glob `sensor.*_detection_distance` to recorder exclude (consistent with the existing still/move distance excludes) |
| living_room_time_since_motion 1362, invisoutlet co2/pressure/voc/illuminance (~5,300 combined across two boards), `*_device_time` x3 (~2,150), living_room_illuminance 1321, study_a_illuminance 711 | see table | Not requested but visible: `*_device_time` timestamp sensors are 17k-distinct and have no history value (exclude by glob `sensor.*_device_time`); `time_since_motion` is a derived counter (exclude). For the invisoutlet/masterbath air sensors and the lux sensors, add device-side `delta` + heartbeat filters in their firmware/Zigbee2MQTT reporting settings (not inspected) | |
| madronewatermonitor_low_flow_leak 2065, automation.frigate_mqtt_to_frigate_events_bridge_ura_snapshot_support 896 | 2961 | Binary with 2 states and 1 distinct state: rows come from attribute updates. Not investigated; examine the attributes before attenuating | |

Estimated saving from the first three lines alone: ~9,650 of the top-25 rows/hr.

## Unknowns
Contents of the external ESPectre package yaml; whether Master's wall-panel bridge is on 1.6.9; push-vs-poll for the unifi sensors; ESPHome ld2410 change-only publish behavior; any URA consumer of the ESPectre or UDM entities (not grepped).

## Measured after restart (2026-10-20)
The excludes took effect at the 09:59 CDT restart (recorder run 1200, 14:59:25Z). Source: `states` in `/config/home-assistant_v2.db` (read-only). "Excluded" means the 52 `states_meta` entities matched by the 3 named entities and the 2026-10-20 globs (`*_detection_distance`, the six `*_panel_*` diagnostics, `*_device_time`).

| window (UTC) | total rows/hr | excluded-set rows/hr | everything else rows/hr |
|---|---|---|---|
| before: 11:58-14:58 (3 h) | 148,648 | 9,448 | 139,200 |
| after: 15:00-15:50 (50 min) | 146,971 | 0 | 146,971 |
| delta | -1,677 (-1.1%) | -9,448 (-100%) | +7,771 (+5.6%) |

The excludes work: the targeted entities wrote 0 rows, and the 9.4k/hr removed matches the ~9.65k/hr estimated above. The total barely moved because everything else rose 5.6% in the after-window. The likely causes are post-boot churn (entities re-reporting and registry updates in the first hour) and the change in time of day. I have not checked either cause. A like-for-like comparison against the same clock hours on a later day would separate them.

## Re-measure 2026-11-11 02:00-02:05 CST (overnight pass, read-only) — batch 2 candidates

Operator instruction 2026-11-10 on RECORDER-WRITE-RATE-ATTENUATION-1: "Prioritize and fix". Source: `/config/home-assistant_v2.db` opened `sqlite3 -readonly` over ssh, window last 24 h.

**Totals:** 3.35M state rows/day (~140k/hr; daily 2.92M on 11-06 rising to 3.40M on 11-10). 138k event rows/day. DB file 10.9 GB (was 15.3 GB on 10-20).
**The 10-20 batch held:** none of its targets (ESPectre score, UDM CPU/mem, `*_detection_distance`, panel diagnostics, `*_device_time`, invisoutlet air) is in the top 80 any more. **No single entity now writes more than 1.9k/hr.** The load is a wide tail: top 50 entities = 17k/hr, ranks 51-200 = 36k/hr, the remaining 18,420 entities = 87k/hr. So further gains come from **families**, not single entities.

| family | rows/hr | entities | share | history consumers found | lever |
|---|---|---|---|---|---|
| `sensor.span_panel*` (2 panels, `_2` = 2nd panel 192.168.8.229, NOT duplicates) | 41,960 | 571 | 30% | Energy prefs: 27 `*_consumed_energy` only; URA history reader `hvac_override.py` (SPAN AC power) | see 2a + 2c |
| of which `*_produced_energy*` | 9,049 | 92 | 6.5% | **none** (Energy prefs, all `.storage/lovelace*`, automations.yaml, packages, URA code: 0 hits). 84 of 92 have <=2 distinct values/24 h (load-only circuits); the 8 that move are feed_through x2, range, oven, dryer x2, metering kit, mains_emporia_vue | **2a: recorder exclude glob** |
| `sensor.beszel*` (homelab server monitor) | 16,396 | 502 | 12% | `lovelace.lab_servers` (119 mini-graph cards) + `lovelace.lab_uptime` (76 mini-graph cards) read their history | 2b: operator call (Beszel keeps its own history; the lab dashboards' graphs would go blank) |
| SPAN poll interval | (~21k/hr if 15 s -> 30 s) | — | — | URA energy/load decisions read SPAN power **live**; slower poll = staler load data | 2c: integration option `snapshot_update_interval: 15.0` on both SPAN entries; NOT recommended without an energy-side review |
| `call_service` events, `system_log.write` from the wall-kiosk user | 101,449 events/day (was 77k on 11-10) | — | 74% of event rows, ~3% of all rows | none | 2d: panel-side (URA-V8-PANEL-RENDER-SPIN-1); websocket "Connection lost" loop |
| `sensor.system*`, `sensor.lxc*`, `sensor.envoy*` | 4.3k / 3.6k / 3.0k | 55 / 135 / 105 | ~8% | not checked | later |

**Recommendation (2a, staged, not applied):** add to `recorder: exclude: entity_globs:` in `/config/configuration.yaml`:
```yaml
      # 2026-11-11 batch 2a (AUDIT_recorder_write_rate_2026_10_20.md re-measure): SPAN produced-energy
      # counters, ~9k rows/hr; 84/92 never change (load-only circuits); no Energy pref / dashboard /
      # automation / URA reader. Consumed-energy + power stay recorded.
      - sensor.span_panel_*_produced_energy
      - sensor.span_panel_*_produced_energy_2
```
Takes effect at the next restart (do NOT restart for it). Undo per RUNBOOK_recorder_excludes.md. Add the ledger row when applied.
