# Runbook: recorder excludes (what we stopped recording, and how to get it back)

This is the single ledger for every entity excluded from the Home Assistant recorder. The exclusions themselves live in
`/config/configuration.yaml` under `recorder: exclude:`, and each block there carries a dated comment pointing here.

## What an exclude does, and does not do

- It stops **history** (the `states` / `state_attributes` tables, and long-term statistics) for that entity.
- It does **not** touch live state. Rooms, automations, alerts, URA decisions and dashboard tiles that show the current value all keep working.
- It is **forward-only and not retroactive in either direction**. Excluding stops new rows; existing history ages out with `purge_keep_days` (7). Undoing it starts recording again from the restart. **The gap while excluded can never be backfilled.**

## How to undo (any entry below)

1. Edit `/config/configuration.yaml` (Samba mount `~/ha-config/configuration.yaml`): delete the entity line (or the glob) from `recorder: exclude:`.
2. Check the config: `ssh ha "ha core check"`.
3. Restart HA. Not while the house sleeps (see memory `feedback_no_restart_during_sleep`).
4. Confirm rows are flowing again: `SELECT count(*) FROM states s JOIN states_meta m USING(metadata_id) WHERE m.entity_id='<id>' AND s.last_updated_ts > strftime('%s','now','-1 hour');`
5. Update the ledger row below (mark it "restored <date>, why").

**Before you undo, check the cheaper option.** For the URA room mirrors, the **source** sensor still records the same values row for row, so point the chart at the source instead of re-enabling the mirror.

**When to undo:** you are adding a history-based card (history-graph, statistics-graph, apexcharts, mini-graph, plotly, a tile trend-graph), an Energy-dashboard source, a `history_stats` / `statistics` / `derivative` / `trend` / `utility_meter` helper, or URA code that calls `get_significant_states` or `statistics_during_period` on one of these entities. Grep this ledger for the entity first.

## Ledger

| Date | Entities | Why excluded | History consumers found at the time | Source of truth instead |
|---|---|---|---|---|
| 2026-04-28 | (none; retention/commit tuning only) | 22 GB DB | — | — |
| 2026-07-17 | `sensor.envoy_482543015950_energy_consumption_today` | Dead accumulator, uint32 spikes poisoned LTS (RUNBOOK_lts_repairs_r4.md) | — | SPAN / Envoy net consumption |
| 2026-09-20 | `*wall_panel_studyb_kiosk_*` (sensor/binary_sensor/light) | ~240k rows/day kiosk telemetry, no consumer | none | — |
| 2026-09-28 | `sensor.*_unfiltered_distance_to_*`, `sensor.envoy_stream_data_timestamp`, `sensor.envoy_stream_data_age` | Bermuda unfiltered distances + Envoy heartbeat; no reader | none (URA reads filtered distances live) | Bermuda filtered `*_distance_to_*` |
| (earlier) | `sensor.*_rx*`, `*_tx*`, `*still_energy*`, `*still_distance*`, `*move_energy*`, `*move_distance*`, `sensor.screek_human_sensor_*`, `sensor.mmwave_*` | radar/network diagnostics | none | the occupancy binaries |
| 2026-10-20 | UDM CPU/memory `_2`, `sensor.living_room_time_since_motion`, `sensor.*_detection_distance`, panel diagnostics (`*_panel_last_seen/_cpu_usage/_cpu_temperature/_ram_available/_bluetooth_devices_nearby/_ambient_noise`), `sensor.*_device_time` | write-rate audit (AUDIT_recorder_write_rate_2026_10_20.md) | none | UniFi keeps its own history |
| 2026-10-20 | `sensor.envoy_482543015950_lifetime_energy_production` | Envoy flaps to 0.046 MWh since 2026-09-13; each flap injects ~19 MWh of fake production into LTS | Energy prefs + 5 dashboards: **switched** to `production_ct_energy_delivered` / `sensor.solar_production_today` | `sensor.envoy_482543015950_production_ct_energy_delivered` |
| 2026-10-20 | 252 URA room mirrors: `sensor.<room>_{illuminance,power,energy_today,temperature,humidity}` (platform `universal_room_automation`; full list in configuration.yaml) | ~7.9k rows/hr, row-for-row duplicates of their source sensors | none (18 dashboards, Energy prefs, helpers, URA code, PWA checked) | each room's configured source sensor |
| 2026-10-20 | `sensor.invisoutlet_b7d0_{co2,voc,pressure,illuminance}`; `sensor.outlet_lux_pir_mmwave_temp_voc_pressure_invisoutet_mqtt_masterbath_{co2,pressure,voc,illuminance}` | ~7k rows/hr | none (masterbath illuminance is read **live** by automations.yaml:730/5894 and the Master Bath room; unaffected) | — |
| 2026-10-20 | `automation.frigate_mqtt_to_frigate_events_bridge_ura_snapshot_support` | ~900 rows/hr of `last_triggered` churn | none (its `frigate_events` bus events still reach perimeter_alert / exterior_track_linker) | automation traces |
| 2026-10-20 | `sensor.smart_plug_pm_current_consumption`, `sensor.hahm_loop_lag_p95` | ~1.2k rows/hr | none | HA health monitor keeps its own stats |

**Deliberately NOT excluded (2026-10-20):** `binary_sensor.madronewatermonitor_low_flow_leak` and `_tank_refill_leak` (we want leak on/off history for incident review); `sensor.iphone_oji_nearest_rssi` / `_distance` (useful for BLE tuning). They are the next ~3.8k rows/hr if ever needed.

Consumer map evidence for the 2026-10-20 batch: session 2026-10-20 prober report (dashboards = all 18 `.storage/lovelace.*`; Energy prefs `.storage/energy`; helpers in `core.config_entries` + `configuration.yaml` + `packages/`; URA history readers only `hvac_override.py:319/:6466` (SPAN ac power) and `energy.py:11762` (SmartHub statistics)). Backup of the pre-change config: `docs/dashboard-prototypes/ura-v8-backups/*_pre_recorder_throttle_configuration.yaml`.

## 2026-10-26 un-exclude (house-level sensors removed by mistake on 10-20)
- Removed from recorder exclude list: `sensor.universal_room_automation_predicted_energy_today`, `..._whole_house_energy_today`, `..._whole_house_power` (house-level, not room mirrors; audit AUDIT_house_sensors_correctness_2026_10_25.md R1). Takes effect at next HA restart. Undo: re-add the three lines. Backup: session scratchpad configuration.yaml.bak-20261026.
