# AUDIT: unattributed energy in the URA coverage sensor (config-only proposal)

Read-only probe, 2026-11-01 ~10:15 CST. Sources: `ssh ha` recorder (`/config/home-assistant_v2.db`, states + statistics), `~/ha-config/.storage/core.config_entries|entity_registry|device_registry`. No HA state changed. No config applied.

## 1. How coverage is computed (the premise needs one correction)

Coverage is built from ENERGY (kWh) sensors, not power sensors.
- `native_value` = whole_house - (rooms + zones + house_devices): aggregation.py:3420-3431 (`native_value`), attributes at 3503-3523.
- whole_house = EC lifetime-consumption entity (`ec_total`): aggregation.py:3555-3590.
- rooms tier = sum of each room coordinator's `STATE_ENERGY_TODAY`: aggregation.py:3638-3646. Per room, that comes from `energy_sensors` (plural) or legacy `energy_sensor` (singular): coordinator.py:4817-4822 (if plural is empty, only the singular is used).
- zones tier = `zone_energy_sensors` of every zone: aggregation.py:3648-3675.
- house tier = `house_device_energy_sensors` (integration entry): aggregation.py:3677-3690.
- `zone_power_sensors` and `house_device_power_sensors` have NO runtime reader (const.py:340,342). Room `power_sensors` feed only the room W readout (coordinator.py:4790-4812), not coverage.
- There is NO dedup: the same sensor in two tiers or two rooms is summed twice.
- Rooms tier uses energy_sensors; a room with power sensors but no matching energy sensor contributes 0 kWh.

## 2. Measured baseline (10-31 end of day, last state 23:59:53 local, recorder)
whole_house 114.12 kWh; rooms 48.45; zones 25.36; house_devices 23.19; attributed 97.00; unattributed 17.12 (15.0%).

Reported 15% is understated because of double counts (producer check, summed from statistics deltas 10-31):
| Double count | kWh | Evidence |
|---|---|---|
| `sensor.span_panel_garage_a_evse_consumed_energy` is both Garage A room `energy_sensor` and a `house_device_energy_sensors` entry | 6.86 | core.config_entries (Garage A, integration entry) |
| `sensor.span_panel_receiving_living_room_plugs_consumed_energy` is `energy_sensor` of BOTH Living Room and Receiving Room | 2.21 | core.config_entries |
Unique attributed = 97.00 - 9.07 = 87.93; TRUE unattributed = 26.19 kWh = 23.0%.

Today (11-01) the sensor shows rooms_total 33.77 vs whole_house 9.06 (`post_restart_window: true`), so today is not usable as a baseline. Not investigated here; unknown cause.

## 3. Proposal table (all config; kWh/day = 10-31 statistics delta; W = recorder latest ~10:12 local)
SPAN Wh sensors are converted by unit, assumed handled by `energy_state_to_kwh`.

### A. Remove double counts / junk first
| Action | Where | Sensor | Note |
|---|---|---|---|
| Replace Garage A `energy_sensor` | Garage A room | remove `span_panel_garage_a_evse_consumed_energy`; set `energy_sensors` = [`sensor.garage_plugs_energy_today`] (4.71 kWh, 137 W) | EVSE already counted at house tier. Keep EVSE in power_sensors. |
| Living Room: drop energy sensor | Living Room | `span_panel_receiving_living_room_plugs_consumed_energy` | keep on Receiving Room only |
| Remove nonsense energy sensors | Garage Hallway | `sensor.back_hallway_cooling_energy_last_month` (176 kWh "last month" counter; HIGH risk of a one-shot jump at month rollover) | no replacement |
| | Jaya Bedroom | `sensor.seeedstudio_mmwave_kit_047d34_existence_energy` (no recorder state; wrong device) | replace with `sensor.sub_panel_vue_3_b_energy_today_3` (Bedroom 4 plugs, 0.14 kWh) |
| | Guest Bedroom 2 Bath, Oji Vanity | `*_energy_returned` sensors (0.0) | replace with the matching `*_energy` consumed sensor (verify it exists) |
| | Media Room Closet, Study A Closet | `media_room_closet_energy_today/_power`, `smart_plug_pm_current_consumption` have no recorder state in 24 h | verify entity ids; Study A Closet power should be `span_panel_office_closet_power` (450 W) |

### B. Add unassigned loads (not in any room/zone/house list)
| Sensor (energy) | kWh/day | W now | Area / label | Proposed home |
|---|---|---|---|---|
| span_panel_master_lights_consumed_energy | 2.03 | 98.6 | Main Panel Wall (SPAN) | Master Bedroom room (or Master Suite zone) |
| span_panel_master_plugs_consumed_energy | 1.58 | 13.5 | SPAN | Master Bedroom room |
| span_panel_freezer_consumed_energy | 1.45 | 3.8 | SPAN | house_device_energy_sensors (location unverified) |
| span_panel_furnace_consumed_energy | 1.14 | 14.4 | SPAN | house_device |
| span_panel_fridge_consumed_energy | 0.80 | 209.5 | SPAN | Kitchen room |
| span_panel_wine_cooler_consumed_energy | 0.57 | 6.6 | SPAN | house_device (location unverified) |
| span_panel_study_a_b_a_v_closet_lts_consumed_energy | 0.56 | 11.7 | SPAN | house_device (spans 3 rooms) |
| span_panel_unknown_consumed_energy_2 (A/V closet top plug) | 0.32 | 13.9 | SPAN | AV Closet room |
| span_panel_double_oven_consumed_energy | 0.30 | 6.0 | SPAN | Kitchen room |
| span_panel_entry_living_hall_lights_consumed_energy | 0.26 | 4.4 | SPAN | Foyer room (currently empty config) |
| span_panel_grinder_pump_consumed_energy | 0.16 | 4.8 | SPAN | house_device |
| span_panel_range_consumed_energy | 0.15 | 5.4 | SPAN | Kitchen room |
| span_panel_unknown_consumed_energy (Study A closet plug 2) | 0.10 | 3.9 | SPAN | Study A Closet room |
| span_panel_a_v_consumed_energy (A/V plug 2 security panel) | 0.10 | 4.8 | SPAN | AV Closet room |
| span_panel_dining_receiving_lights_consumed_energy | 0.10 | 5.0 | SPAN | Dining Room only (its POWER sensor is currently triple-listed in Dining, Living, Receiving: remove from the latter two) |
| span_panel_generator_trickle_charge_consumed_energy | 0.09 | 0 | SPAN | house_device |
| span_panel_patio_plugs_consumed_energy | 0.08 | 3.5 | SPAN | Patio room |
| span_panel_warming_drawer_consumed_energy | 0.04 | 0 | SPAN | Kitchen room |
| sensor.garage_plugs_energy_today | 4.71 | 137 | Vue sub panel | Garage A room (see A) |
| sensor.sub_panel_vue_3_b_energy_today_5 (Media Room Plugs) | 1.64 | 74.9 | Vue | Media room |
| sensor.sub_panel_vue_3_b_energy_today_2 (Forced Air 1 & 2) | 1.52 | 60.7 | Vue | house_device (air handlers; not zone AC compressors) |
| sensor.utility_refridgerator_energy_today | 0.97 | 0 | Vue | Laundry room (utility dishwasher is there) |
| sensor.sub_panel_vue_3_b_energy_today_9 (Laundry + Landscape Txformer) | 0.62 | 0 | Vue | Laundry room |
| sensor.bedroom_5_lights_energy_today | 0.46 | 0 | Vue | Ziri Bedroom |
| sensor.kitchen_and_pantry_lights_energy_today | 0.44 | 0 | Vue | Kitchen room |
Sum of additions: SPAN 9.85 kWh, Vue 10.36 kWh = 20.2 kWh.

### C. Overlaps to AVOID (would double count; do not add)
| Sensor | Why |
|---|---|
| `span_panel_subpanel_*` (17.9 kWh), `sub_panel_vue_3_energy_today` (17.8), `sub_panel_vue_3_b_energy_today` (4.75) | parents of the Vue circuits; CM already excludes subpanel power. Use only leaf circuits. |
| `sub_panel_vue_balance_energy_today` (10.03) | unmonitored remainder of the sub panel; adding it hides the real residual. Optional, not recommended. Vue 3 vs 3_B parentage not verified: unknown. |
| `madrone_pool_vsf_power`, `_vsf_2_power` (1250+450 W) | downstream of SPAN pool circuit (already house_device). |
| `powerplug_energymonitor_tapo_matter_*`, Meross plug, `shelly1pmg3_masterbedroom_*` (56.9 W, 1.21 kWh), landscape transformers (dewenwils 0.74+0.57) | probably downstream of SPAN or Vue circuits listed above; adding both double counts. Verify the panel before choosing leaf vs circuit. |
| Envoy/Enphase/encharge/inverter/solcast/battery/mains_vue/ura_* sensors | production, storage, grid, forecast or URA-derived values; not loads. |
| SPAN `none_power_*`, `unmapped_tab_*` | unavailable or 0 W. |

## 4. Estimated coverage after changes (10-31 basis)
Unique attributed 87.93 kWh + additions 20.2 = 108.1 of 114.12 kWh = ~94.7% (unattributed ~6.0 kWh, ~5%). The remainder is plausibly water heaters, `balance` and untagged Vue circuits (unverified). Caveats: (a) removing the two double counts first makes the sensor WORSE (23% unattributed) before the additions land; (b) additions use 10-31 deltas for one day and will vary; (c) rooms listed with new sensors must have multi-sensor `energy_sensors` set, which supersedes the singular `energy_sensor` (coordinator.py:4817-4822), so keep any wanted singular value inside the list.

## Applied 2026-11-01 (operator-approved config; no restart, no parent reload)
Backup: `docs/dashboard-prototypes/ura-v8-backups/20261101T_pre_power_coverage_core.config_entries.json`. Each change made via the room `energy` options step or the integration `energy_sensors` step (ha_set_integration), then diffed against the backup. Only intended fields changed. The room step also writes its own current-value defaults (`electricity_rate`, `notify_daily_energy_summary`, `power_sensors`) into options (+4 keys, or +1 where they were already in options). The singular `energy_sensor` stays in `entry.data` (the flow can't clear it), but a non-empty options `energy_sensors` supersedes it (coordinator.py:4816-4821, merge = `{**data, **options}`).

### Step 0 location map (coverage-feeding fields only)
- Rooms tier: 30 rooms with `energy_sensor(s)`. Zones tier: 3 zone AC circuits (ac1, ac_2, ac_3). House tier: Garage A/B EVSE + pool. Whole house: Envoy lifetime net consumption.
- EC options (`energy_circuit_extra_entities` = Vue balance POWER + Vue 3 mains POWER, `energy_evse_*`, grid/mains) do NOT feed coverage (they feed the EC circuit/load view). No double count with coverage.
- Double counts found: Garage A EVSE (room + house), Receiving/Living plugs (2 rooms), and NEW (missed by audit): `shelly2pmg3_e4b323135af8_switch_0_energy` in both Laundry Closet and Laundry.
- `sub_panel_vue_balance_energy_today` was in no coverage location. Sub-panel mains (`sub_panel_vue_3_energy_today`, `span_panel_subpanel_*`) are in no coverage location, so balance + circuits does not double count the mains.

### Changes (field `energy_sensors` unless noted; before = effective)
| Entry | Before → After |
|---|---|
| Garage A | garage_a_evse → [garage_plugs_energy_today] (EVSE kept at house tier only) |
| Living Room | receiving_living_room_plugs → [entry_living_hall_lights]; power: dropped dining_receiving_lights_power |
| Receiving Room | plugs (unchanged); power: dropped dining_receiving_lights_power |
| Dining Room | + dining_receiving_lights |
| Laundry | − e4b323135af8_switch_0 (kept on Laundry Closet); + utility_refridgerator |
| Garage Hallway | back_hallway_cooling_energy_last_month → [garage_hall_lights_energy_today] |
| Jaya Bedroom | mmwave existence_energy → [sub_panel_vue_3_b_energy_today_3] |
| Guest Bedroom 2 Bathroom | overhead_energy_returned → [upguestbathroom_overhead_energy, _sconce_energy] |
| Oji Vanity | − ojivanity_energy_returned |
| Master Bedroom | + master_lights, master_plugs |
| Kitchen | + fridge, freezer, double_oven, range, warming_drawer |
| Butler Pantry | + wine_cooler |
| AV Closet | + unknown_consumed_energy_2, a_v |
| Study A Closet | + unknown_consumed_energy (plug 2); power: smart_plug_pm → span_panel_office_closet_power |
| Patio | (none) → [patio_plugs] |
| Media | + sub_panel_vue_3_b_energy_today_5 |
| Ziri Bedroom | + bedroom_5_lights_energy_today |
| Integration `house_device_energy_sensors` | + furnace, study_a_b_a_v_closet_lts, grinder_pump, generator_trickle_charge, sub_panel_vue_3_b_energy_today_2, sub_panel_vue_balance_energy_today |

### Skipped
- `kitchen_and_pantry_lights_energy_today`: Kitchen Pantry inovelli dimmer is likely downstream (double count).
- `sub_panel_vue_3_b_energy_today_9` (Laundry + landscape): washer/dishwasher channels are likely downstream.
- Media Room Closet (`media_room_closet_energy_today` = unknown): no verified replacement; left as is.
- Garage B `em_shelly_wifi_garageb_energy` may overlap the house-tier Garage B EVSE (its power list includes the EVSE). Unverified; not changed.
- Pool VSF, sub-panel mains, mains balance (`mainw_vue_balance_*`), downstream plugs: not added, per section C.

### Estimated coverage (10-31 basis)
87.93 unique + 9.83 SPAN + 9.57 Vue (incl. Jaya/garage-hall replacements) + 10.03 balance ≈ 117.4 of 114.1 kWh (>100%). Without balance: ≈107.3 kWh (~94%). Exceeding 100% means the balance probably overlaps counted circuits. Likely cause: the Vue 3 balance also covers the Vue 3B channels, or 3B is not subtracted (parentage unverified). Check tomorrow's full-day `energy_coverage_delta`. If it goes materially negative, remove `sub_panel_vue_balance_energy_today` from house devices (one-field undo). Today's per-room totals restart from the change time, so 11-01 is not a valid baseline.
