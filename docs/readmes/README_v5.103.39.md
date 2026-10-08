# URA v5.103.39 — EC degraded-data safety, census door-event quality, HVAC Custom Preset Ranges (Batch C)

Three reviewed changes ship together (one restart).

## 1. EC degraded-data phase 1 (EC-DEGRADED-DATA-POLICY-1, EC-LKG-NEVER-PERSISTED-1, ENERGY-HISTORY-KW-SUMMED-AS-KWH-1, ENVOY-STREAM-AB-48H-1)
Tier 3: four framing-disjoint reviews (A/B/C/D) + D re-pass, all findings fixed.
- **No EV or L1-plug turn-on in a tick where charge-from-grid is on or being dispatched on** (captured pre-await `_ev_start_hold_label`; all drain-precedence reversion sites, should-start-by, plug drain/fill/release paths).
- **Untrusted battery SOC** (operator option 1): every EV start waits for a trusted reading except the off-peak ensure-on and should-start-by starts (`EV_UNTRUSTED_SOC_EXEMPT_PATHS`); exempt starts still obey every grid-charge/arbitrage/blind-window hold. Refusals and exempt starts are logged once per episode.
- Grid-charge command ledger stamped on every ON dispatch, cleared only by a fresh "off" read, not restored if older than 12 h (newer of command/dispatch stamps).
- Arbitrage chunk latch persisted with its TOU period; dropped on an off-peak boot after a non-off-peak save (restart across off-peak start no longer skips the night's charge).
- LKG SOC/solar + write-verify ledgers persist across restart; failed battery writes recorded (incl. `force_redispatch`); write-churn and Envoy-offline NMs.
- Cloud freshness from `sensor.enphase_cloud_last_successful_update`.
- **Stream tier (D1) stays dormant.** The 48h A/B readout was NO-GO (peak battery cutouts 30 → 138 with the MQTT stream add-on running; stream covered 4/7 native dropouts; its timestamp heartbeat frozen since 09-29). Add-on `13e68335_envoy_to_mqtt_json` stopped and set to manual boot.
- energy_history kW samples now integrated to kWh (shared LEAD-interval CTE) for similar-day and date-range queries.
- Known residual (carded): at a TOU transition the manager path can dispatch charge-from-grid ON one tick before the breaker pauses an already-charging EV.

## 2. Census inputs-first D1 — door event quality (CENSUS-INPUTS-FIRST-1)
Tier 2-DB: three reviews + fix pass + orchestrator mutation spot-checks.
- `_extract_camera_stem` now strips `_2` and `_person_count` legs (Frigate-2 occupancy sensors were bypassing dedup → most crossings logged twice).
- Door dedup window 5 s → `DOOR_STEM_DEDUP_S = 30`, keyed per door group and **per direction** (an exit and an entry 20 s apart are both kept); prune horizon ≥ window + 45 s resolve delay.
- Direction: each door's nearby interior cameras (`door_interior_neighbours`, Advanced); closest-in-time sighting across cameras wins. Unset = today's all-interior fallback.
- New `peak_person_count` column on `person_entry_exit_events` (fresh CREATE + ALTER; 6-column fallback if the ALTER fails) fed by a value buffer on each door's count sensor.
- New Advanced options on Camera Census: Door groups, Rooms next to each door, Main entry door (consumer arrives with the estimator cycle). Empty values are not saved, so the first save doesn't reload the integration.
- Face-name lookup fixed (nonexistent `er.async_entries_for_platform` → registry iteration); Revel guest-WiFi count locked out of the house total by test.

## 3. HVAC Batch C — Custom Preset Ranges (HVAC-CUSTOM-PRESET-RANGES-1, HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1, HVAC-S10-DPM-VS-S1-1, HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1)
Tier 2-DB + mandatory Review D; all findings fixed; full suite clean.
- **Ships OFF.** Switch `switch.ura_hvac_coordinator_guest_mode_actuation` ("Custom Preset Ranges") now resolves OFF after restart when it has no saved state or a saved `unavailable`/`unknown`, re-lands correctly when the HVAC coordinator is rebuilt, and never reads ON unless you set it.
- Only zones listed in Baseline Presets → "Zones that use custom ranges" (default empty) are edited. Edits go through one funnel (`emit_set_activity_setpoint`) and only after the original range is saved (whole-degree comparison — the x.5 leak found in review is fixed).
- Turning the switch off, or removing a zone from the list, puts the original ranges back. Write limit resets after each confirmed success.
- Compose-away, its throttle bypass, suppress stamps and the `cool − 7` range are deleted; the emitted-range map is retired.
- Brand-neutral: Generic thermostats return "unsupported" with zero calls; the ecobee half lands with W1-C P2.

## Pre-restart step
Turn **Custom Preset Ranges OFF** on the old code before restarting (old default is ON).

## Live validation
### Validated 2026-10-06 (restart onto v5.103.39 2026-10-05 ~13:56; checked 10-06 ~11:30)

| Check | Result | Evidence |
|---|---|---|
| EV/plug starts only via allowed paths | PASS | ura_activity_log since restart: 11 `charger_on`, all via off-peak ensure-on / overnight; 4 `ev_start_allowed_soc_untrusted_exempt` (exempt paths); 0 starts while URA commanded charge_from_grid |
| No EV start while charge_from_grid ON | PASS | Cloud CFG `switch.iq_battery_hacs_charge_battery_from_grid` OFF since 10-04 16:11; no URA CFG ON in window |
| SOC trust / tiering | PASS | battery_strategy `soc_source=envoy`, `soc_tier_trusted=true`, cloud divergence 2.1 pp |
| Stream tier dormant | PASS | `stream_trust=disabled`; stream add-on stopped + boot=manual (A/B NO-GO) |
| Census door rows carry head count | PASS | person_entry_exit_events since deploy: 19 rows, 17 with non-NULL peak_person_count, 6 with person_id |
| Door config applied | PASS | door_groups/neighbours/main_entry_door set 10-05 (garage_b neighbours = [] by operator ruling) |
| CPR switch resolves OFF after restart | PASS | `switch.ura_hvac_coordinator_guest_mode_actuation` = off after both restarts; `s10_switch_resolved value=False` rows |
| No S10 preset writes with empty rollout | PASS | 0 `S10_preset_range*` climate_write rows |
| URA errors at boot | PASS | none except shutdown-stage `DB write failed: shutdown timeout` (pre-existing slow shutdown; carded SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1) |

Note: the local Enpower `charge_from_grid` switch read ON for days while the cloud setting was OFF; it is not URA's gate (manual §2.6a).
