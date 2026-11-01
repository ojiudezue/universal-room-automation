# AUDIT: Envoy second-source fallback — what exists, what is dormant, what is stale (2026-10-29)

Read-only probe, run Thu 2026-10-29 02:45-02:50 CDT (`date`). Branch develop @ 1ad65cb0b. No HVAC/presence docs relevant. Paths below are under `custom_components/universal_room_automation/` unless prefixed `docs/`.

## 0. Answer first

1. The "resolver" is the SOC read in `battery_soc` (`domain_coordinators/energy_battery.py:1060-1187`): tiers native Envoy (fresh < 300 s, `last_reported`) -> **stream** -> LKG (<=300 s) -> cloud fallback (<=600 s, `last_updated`) -> none. The "witness" is a different thing: the reserve-write witness (`energy_write_verify.py`, `RESERVE_LOCAL_WITNESS_ENABLED=True`, `energy_const.py:558`), which verifies reserve writes, not SOC/power telemetry.
2. The stream SOC tier exists in code but is **hard-off by a module constant** `SOC_STREAM_TIER_ENABLED = False` (`domain_coordinators/energy_const.py:345`). It is a rung-1 kill switch, so enabling it is a reviewed code change, not config. Live tier right now: `primary_envoy` (`sensor.ura_energy_coordinator_battery_strategy` attr `soc_resolution.tier`, DB row 2026-10-29 07:47:22Z).
3. The stream tier was built for the MQTT add-on (cowitness = fast sibling entity, `expire_after` contract). Its config fields are generic entity selectors, so `enphase_realtime` `_2` entities could be pointed at them, but the gate is still the constant, and the default freshness mode needs a co-witness (`energy_const.py:357`, `energy_battery.py:1826-1830`).
4. Smallest change (section 6): config-only is possible for solar-follow grid fallback; for SOC, either a config-only route through the existing *cloud-fallback* slot (untrusted tier, with a freshness defect) or a one-constant flip plus 2 config fields (needs Tier-3 review).

## 1. Code inventory

| Piece | file:line | What it does | Live/dormant | Config-only for realtime `_2`? |
|---|---|---|---|---|
| `battery_soc` resolver | `domain_coordinators/energy_battery.py:1060-1187` | envoy -> stream -> LKG -> cloud -> none; sets `_soc_source_last` | LIVE (envoy/lkg/cloud live; stream skipped) | n/a |
| Primary SOC entity + freshness | `energy_battery.py:1079-1083`, `energy_const.py:402` (`DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S=300`) | native entity via `_get_entity("battery_soc")`, `last_reported` age | LIVE | Role entity can be re-pointed (`energy_const.py` EC_ROLE_KEY_DEFAULTS), but that REPLACES native, not a fallback |
| Stream tier | `energy_battery.py:1769-1835` (`_stream_tier_configured`, `_read_stream_soc`, `_stream_cowitness_live`) | fail-closed read: unit exactly `%`, 0-100, freshness mode, co-witness live, not quarantined | **DORMANT**: `SOC_STREAM_TIER_ENABLED=False` (`energy_const.py:345`) | Fields are config; **switch is code** |
| Stream config fields | `energy_const.py:348,352`; wiring `domain_coordinators/energy.py:1186-1187`; UI `config_flow.py:6068-6069, 7462-7478` | `energy_stream_battery_soc_entity`, `energy_stream_cowitness_entity` (sensor domain selectors); neither is set in the live entry | Unset | Yes, any `sensor` entity |
| Freshness mode | `energy_const.py:357` `DEFAULT_SOC_STREAM_MAX_AGE_S=0`; `:360` cowitness 120 s | 0 = mode "b": needs `expire_after` contract + mandatory co-witness changed within 120 s (`last_updated`); >0 = mode "a" (`last_reported`) | Constants | No (rung-1 constants) |
| Divergence/quarantine | `energy_battery.py:1871-1920`; consts `energy_const.py:364,368`; reuses `DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT=3` (`:~326`) | native vs stream, 2 samples >=60 s apart beyond 3 pp -> `quarantined` + NM page | Dormant (needs tier on) | n/a |
| Trusted-tier set | `energy_battery.py:118-125` `SOC_TRUSTED_TIERS={envoy,lkg,stream}` | `cloud_fallback`/`none`/`*_reject` are untrusted: D2a hold-release refusal, D3 grid-charge withhold on cloud, D4 page | LIVE | n/a |
| Cloud SOC fallback | `energy_battery.py:1107-1185`; consts `energy_const.py:~320 (600 s)` | unit, range, `last_updated` age guards | LIVE; configured `sensor.iq_battery_hacs_battery_overall_charge` (core.config_entries, CM options) | **Yes: `energy_cloud_battery_soc_fallback_entity` accepts any sensor** |
| Resolver observability | `energy_battery.py:1468-1527` (`_evaluate_soc_resolution`), `:2111-2133`, status key at `:8234`; `sensor.py:14731` `fallback_active` | `soc_resolution.tier` etc. | LIVE | n/a |
| Reserve write witness | `energy_write_verify.py:369-409,518-575,1237-1280`; `energy_const.py:558` | native local reserve sensor is primary witness, cloud is corroborator (oracle phase 2, rev 2.2) | LIVE (shipped v5.103.8x; commits 06f243d44..7e12c9f4e) | Not an SOC/power path |
| Solar-follow grid fallback | `energy_pool.py:4985-5040`; `energy.py:660-682`; const `energy_const.py:1652-1654`, default `:2633-2635` | primary Emporia `sensor.mains_vue_3_power_minute_average`, fallback = a second sensor, `last_reported` <= `SOLAR_FOLLOW_GRID_FRESH_S` (180 s), W or kW | LIVE; live fallback = native `sensor.envoy_482543015950_current_net_power_consumption` | **Yes, config (`energy_solar_follow_grid_fallback_entity`)** |
| Role-entity repair scan | `__init__.py:915,1005`; `config_flow.py:1013-1075` | raises `ec_role_entity_<key>` repair for unresolvable role entities. The 10-14 live issue was `..._solar_follow_grid_fallback_entity` pointing at the retired MQTT stream | LIVE | n/a |
| Native-bound envoy status | `sensor.py:~14700-14730` | `envoy_status`, `fallback_active = src not in (None,"envoy")` | LIVE; currently `stale` state with `stale_sources=[]` at 07:45Z (unknown why; attr snapshot shows `fallback_active:false`) | n/a |

Not found in code: any `primary_envoy` config concept (it is only the tier label at `energy_battery.py:1493`), any grid/solar *power* stream tier, any "fast feed" consumer. `ENVOY-FAST-FEED-URA-CONSUMER-1` exists only as a prose reference (`docs/planning/kanban.data.yaml:30686`), **no card with that id exists**.

## 2. Plans and cards

| Doc / card | Status | What it planned |
|---|---|---|
| `docs/planning/PLANNING_envoy_local_witness_and_solar_follow.md` (2026-09-25) | planning; §3 measured | MQTT livedata as trusted witness; §4 SOC tier; §5 solar-follow upgrade |
| `docs/planning/AUDIT_envoy_mqtt_trust_measurement.md` | done | Run 1/2: freshness PASS, independence PASS (stream up 99.78% of native-down), binding constraint 3.8 (reconnect junk SOC=0 for ~36 s) |
| ENVOY-STREAM-TRUST-MEASURE-1 (`kanban.data.yaml:30389`) | done | The measurement above |
| ENVOY-STREAM-SOC-TIER-1 (`:30501`) | **parked** | Stream as SOC tier 3; revival trigger = read stream without holding sc_stream 24/7 (add-on drives peak cutouts) |
| SOLAR-FOLLOW-LOCAL-GRID-SOURCE-1 (`:30568`) | done | Fallback = `sensor.envoy_stream_grid_power`; now dangling (add-on stopped); repair issue exists |
| ENVOY-STREAM-AB-48H-1 (`:1121`) | done, NO-GO 2026-10-07 | Cutouts 30 -> 138 per 48 h with stream; add-on stopped, boot manual 2026-10-05 |
| `docs/planning/DESIGN_ec_degraded_data_policy.md`, `PLANNING_ec_degraded_data_phase1.md` (618 l), EC-DEGRADED-DATA-POLICY-1 (`:1141`) | done (v5.103.39) | D1 stream tier (built, dormant), D2a/D3/D4 untrusted-tier handling (live). README_v5.103.39:13,45: "Stream tier dormant", `stream_trust=disabled` |
| `docs/planning/PLANNING_ec_enphase_resilience_and_p1_adjust.md` | planned/shipped in part | ENPHASE-REALTIME-TRIAL-1 design; Phase-1 adjustments |
| ENPHASE-REALTIME-TRIAL-1 (`:1069`) | parked w/ readouts | Trial approved 10-05; 10-09 readout: SOC vs native p99 1.0 pp PASS; "second witness only"; net-power sign vs Emporia, battery-power plausibility, peak cutouts UNRESOLVED before URA consumes it; "decide whether EC uses realtime SOC as fallback witness" |
| EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1 (`:1154`) | parked | Act on fresh cloud SOC when Envoy blind; tier 3 plan not written |
| `docs/planning/PLANNING_ec_reserve_oracle_phase2.md` (rev 2.2) | built & shipped | Local witness primary, cloud corroborator for RESERVE writes. Stream witness tier **dropped** (rev 2.2 D0 P5 NO-GO, lines 61, 196, 413-414, 559-562). C4 residual (native down + cloud stale-equal) is explicitly accepted (line 384) |
| `docs/planning/PLANNING_envoy_telemetry_failover_map.md` (+D5 addendum), `AUDIT_envoy_telemetry_pairing_manual.md` | design | Generic telemetry pairing; recorder probe rejected D3/D4 on stale-power; `enphase_ev` grid power mismatch. Not read in full by this probe. |

## 3. Validity (plan claim vs code today)

- Stream tier code matches PLANNING_ec_degraded_data_phase1 (resolver position between native and LKG, `energy_battery.py:1094-1102`; `SOC_TRUSTED_TIERS` includes `stream`). Still present and unchanged in recent commits: `git log --since=2026-10-05` on energy files shows reserve-oracle phase 2, bill, storm, solar-CT commits; none touch the stream tier. `integ/overnight-2026-10-27` diff vs develop touches only binary_sensor, const, notification_manager, optimization, sensor.py (no energy files).
- **Stale: MQTT-specific assumptions.** Constant comments name MQTT `expire_after` (`energy_const.py:355-360`), "stream grid power" cowitness, 60 s `expire_after`; the NM page text says "Local stream battery level" (`energy_battery.py:1912`); the D0 A/B design depended on the add-on, which is stopped (board `kanban.data.yaml:1121+`). The heartbeat/microinverter-completeness check is in the 3.8 partial-fleet constraint (PLANNING_envoy_local_witness §3.8, binding constraint on SOC-0 junk after reconnect); no code implements a device-completeness check. realtime has the equivalent reconnect hazard UNMEASURED.
- **Stale: ENVOY-STREAM-SOC-TIER-1 revival trigger** is about the add-on; realtime is a different producer (no sc_stream hold per trial settings "stream OFF"). The trigger text does not cover it.
- **Stale: solar-follow fallback doc** says stream; live config has already been repaired to native net consumption (CM options, 10-14 repair).
- Freshness semantic drift: native SOC gate is `last_reported` (300 s). Cloud fallback gate is `last_updated`, which only moves on VALUE CHANGE. Live: `soc_resolution.cloud_soc_age_s = 11834.9` (07:47Z), i.e. a stable cloud SOC is rejected as `fallback_stale_reject` after 600 s even though the cloud sensor is healthy. Same would hit `sensor.envoy_482543015950_battery_2`: DB shows its state changes only every few minutes (04:01:32, 04:09:01, 04:12:31, 04:16:31 on 10-29Z) while `last_reported` advances. So a `last_updated` gate would reject realtime SOC; only mode "a" (`last_reported`, `energy_battery.py:1807-1814`) suits it.

## 4. Live facts (DB, ssh ha, `/config/home-assistant_v2.db`)

- Native drop last night: `sensor.envoy_482543015950_battery` `unavailable` 04:09:29Z (23:09 CDT) -> `30` at 04:30:09Z (20.7 min). Over the same window realtime `sensor.envoy_482543015950_battery_2` kept reporting 32/31/30 (04:09:01, 04:12:31, 04:16:31).
- Realtime power entities in the last hour: `sensor.envoy_482543015950_grid_power` (W, device_class power) 359 updates; `load_power` 359; `current_net_power_consumption_2` (kW) 59; `battery_2` and `pv_power` 0 state changes in the hour (value-stable; unknown whether `last_reported` advanced for them).
- EC live: tier `primary_envoy`, `tier_disagreement_pp 0.0`, cloud_soc 30, lkg_age 0.0; `envoy_status` state `stale` but `stale_sources []` (07:45Z) — unexplained, not investigated.
- Live URA options (core.config_entries, CM entry): no `energy_stream_*` keys set; `energy_cloud_battery_soc_fallback_entity=sensor.iq_battery_hacs_battery_overall_charge`; `energy_solar_follow_grid_entity=sensor.mains_vue_3_power_minute_average`; `energy_solar_follow_grid_fallback_entity=sensor.envoy_482543015950_current_net_power_consumption`; `energy_envoy_entity=sensor.envoy_482543015950_current_power_production`.
- Unverified: realtime unit on `battery_2` (restore_state read returned nothing; DB attrs not pulled for it) — the stream tier requires unit exactly `%` (`energy_battery.py:1797-1800`).

## 5. What exists / dormant / stale

- **Exists and live:** 4-tier SOC resolver incl. LKG and cloud; untrusted-tier handling (D2a/D3/D4); reserve-write local witness + cloud corroborator; solar-follow primary/fallback grid pair; generic entity-selector config surface.
- **Dormant:** stream SOC tier (constant False), its divergence/quarantine, co-witness freshness, trust persistence.
- **Stale:** MQTT-add-on assumptions (names, expire_after contract, heartbeat), ENVOY-STREAM-SOC-TIER-1 revival trigger, the nonexistent ENVOY-FAST-FEED-URA-CONSUMER-1 card, `last_updated`-based freshness for slow-changing values.
- **Not built at all:** any realtime-specific tier, grid/solar/net-power stream fallback beyond solar-follow, device-completeness/junk-on-reconnect gate for realtime.

## 6. Smallest change making enphase_realtime the fallback

1. **Config-only, low risk (solar-follow grid):** set `energy_solar_follow_grid_fallback_entity` to `sensor.envoy_482543015950_grid_power` (W, 10 s). Caveat: sign convention vs the Emporia/native net sensor was an open item in the 10-09 trial readout; verify sign before applying. Scope is EV solar-follow only, not SOC.
2. **Config-only SOC, with defects:** put `sensor.envoy_482543015950_battery_2` in `energy_cloud_battery_soc_fallback_entity`. It becomes an untrusted `cloud_fallback` tier (D3 withholds grid charge; D2a keeps holds), and the `last_updated` 600 s gate will reject it whenever SOC is stable. It also drops the real cloud oracle as fallback. Not recommended as-is.
3. **Proper path (needs code, Tier 3):** flip `SOC_STREAM_TIER_ENABLED` to True, set `energy_stream_battery_soc_entity=sensor.envoy_482543015950_battery_2` and a co-witness `sensor.envoy_482543015950_grid_power`, and set `DEFAULT_SOC_STREAM_MAX_AGE_S` to a value > 0 (mode "a", `last_reported`) because mode "b" assumes an MQTT `expire_after`. Precondition per the trial card: resolve net/battery-power metrics, and measure realtime reconnect junk (the 3.8 hazard) first (Measure Before You Build). Then rename the "stream" NM text.

Falsifier for this report's tier claim: a live attribute `soc_resolution.tier == "local_stream"` would mean the constant is overridden somewhere; grep found only `energy_const.py:345` and tests were not checked.
