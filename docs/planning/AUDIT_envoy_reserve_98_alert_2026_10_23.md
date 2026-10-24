# AUDIT: Envoy reserve_soc=98 "write not applied" alert (2026-10-23)

Read-only probe. Run at 2026-10-23 19:18 CDT (2026-10-24 00:18 UTC). All times UTC unless stated.
Sources: URA DB (`/config/universal_room_automation/data/universal_room_automation.db` via `ssh ha`), HA recorder (`/config/home-assistant_v2.db`), repo code. HA core log was NOT readable (no journald in the SSH add-on, supervisor 403), so no log lines are cited.

## Verdict
- (a) 98 was INTENDED. It is the EVSE battery-hold, not storm, arbitrage or attain. The alert itself is a false positive. The real fault is separate and is a BUG: the reserve is stuck at 98 because the release write back to 10 is never sent.
- (b) TRUE current reserve = 98. The local Envoy sensor is right. The cloud number (10.0) is stale.
- (c) Small money loss, no safety risk. Details below.

## Q1. Why 98 at 19:35
- Decision path is `_apply_evse_battery_hold` (`energy.py:5424`), which raises the reserve floor to current SOC while an EVSE charges, so the battery does not feed the car.
- `ura_activity_log` 19:35:34: `reserve_write applied path=timer value=98 desire=10 owner=evse_battery_hold` (entity `number.iq_battery_hacs_battery_reserve`).
- `ura_activity_log` 19:40:02: same value 98, `owner=dp_transition`.
- `decision_log` dp_eval 19:35:02 shows `charger_rate_kw=11.76`, `ev_load_w=11764`, `soc=98`, state HOLD_ONLY to HOLD_PRE_EVAL. At 19:40:02 it shows state TRANSITIONED, reason "fits".
- The EV (garage_b, about 11.7 kW) drew power 19:35 to about 19:44 only. From 19:45 `ev_load_w=0`.
- Not storm/inclement/arbitrage: `sensor.ura_energy_coordinator_battery_decision` at 00:15:05 shows `arbitrage_active=false`, `evse_battery_hold=false`, mode self_consumption.
- The same pattern ran this morning: 08:05 value 13 (alert 08:20), 09:50 value 12, 10:00 value 10 (10:01 cloud number caught up to 10.0), self-heal alert 11:10. That is the same class of alert on lower numbers.

## Q2. Which source is true
- `sensor.envoy_482543015950_reserve_battery_level` went to 98 at 19:35:50, 16 seconds after the write. It was 13/12/10 this morning and tracked every write. Recorder history shows no other changes.
- `number.iq_battery_hacs_battery_reserve` (cloud) has had NO state row since 10:01:15 (10.0). `number.enpower_*` has had none since 09:40 (10.0). Neither moved on the 98 write.
- Behavioural proof, battery `sensor.envoy_482543015950_current_battery_discharge` (kW, + = discharging, consistent with SOC falling at 22:31):
  - Last night 23:00 to 00:19 UTC (mid_peak): 5 to 9 kW discharge sustained.
  - Tonight 23:00 to 00:17 UTC (mid_peak): -0.03 to -0.06 kW, essentially idle.
  - SOC pinned 98 to 100 (`sensor.envoy_482543015950_battery`, last 98 at 23:33).
  - `battery_decision` net_power=5.98 kW at 00:15, so the house is importing from the grid while the strategy text says "discharging".
- Conclusion: the gateway enforces 98. This falsifier could have shown otherwise (a normal 5+ kW discharge tonight) and did not.

## Q3. Verifier and write path
- The write went to the CLOUD entity `number.iq_battery_hacs_battery_reserve` (`ENERGY_CLOUD_FIRST_WRITES = True`, `energy_const.py:533`; activity log entity_id).
- Alert source: `energy_write_verify.py:782`. It reads the cloud oracle (`_oracle_entity_for`, `energy_write_verify.py:337`) 900 s after the write, saw 10.0, and fired. The local Envoy sensor is only the secondary witness (`_local_entity_for`, `energy_write_verify.py:372`).
- So the cloud entity never reflected 98 although the gateway did. Why the cloud number did not update is UNKNOWN (no logs). Contrast: 09:50 to 10:01 it updated 1 minute after each write. Other cloud entities (`switch.iq_battery_hacs_charge_battery_from_grid`, schedules) are updating to 00:19, so the cloud integration is alive. The UDM firmware event (about 18:51) came before the 19:35 write, so it is not an obvious cause.
- Anomaly and alert rows: `anomaly_log` 19:50:34 `write_verification_failed` (commanded 98, oracle "10.0"). `notification_log` 19:50:34 to 19:50:35 CRITICAL. Same at 08:20 and 11:10.

## Q4. Self-heal and current risk
- NO re-sends. The only reserve writes since 19:35 are the two at 19:35:34 and 19:40:02 (activity log).
- `energy_state.wv_verified_records` (updated 00:15): reserve_soc `status: stale`, commanded 98, oracle 10.0, verified_at 19:55:02.
- Retirement logic: `energy_write_verify.py:911-931`, record goes STALE when current desire (10) equals the cloud oracle (10.0).
- Real bug (inferred from code, not reproduced): the release dispatch is deadbanded against the stale cloud entity. `_reserve_action` (`energy_battery.py:7024-7061`) computes `current_reserve` from the write-leg entity (cloud number = 10.0). Target 10 vs 10.0 gives |diff| < 2, so no action is emitted. The gateway therefore stays at 98 until something else changes the desire by 2 or more, or the cloud number refreshes.
- Money: mid_peak runs 22:00 to 02:00 UTC (`sensor.ura_energy_coordinator_tou_period` history), rate `sensor.ura_energy_coordinator_tou_rate` 0.0864 at 22:00. The house imports about 6 kW instead of using the battery. Rough exposure is about 12 kWh over the remaining about 1h40m, around $1 (spread between mid-peak and off-peak, not verified). Off-peak starts 02:00 UTC, so cost after that is nil. Next risk is tomorrow's mid-peak and morning solar absorption if it persists.
- Safety: a higher reserve means more backup energy, so no safety exposure. EV charging is not blocked.
- NM is re-alerting (`nm_alert_state` alerting/repeating at 23:59:42 and 00:06:41).
- Side observation: `sensor.ura_energy_coordinator_envoy_status` has read "stale" every 30 s since at least 18:00 UTC. Not investigated.

## Q5. Prior art
- Memory `reference_ec_reserve_verifiable_backout_knob.md` covers `CONF_RESERVE_VERIFIABLE_MAX_AGE_S`, the blind-window EVSE guard. It is not about this alert and the knob does not help here.
- Memory `project_envoy_boot_incident_2026_06_12.md` is about boot races. Not this issue.
- Code comment `energy_write_verify.py` `_local_entity_for` already says the Enpower number "read only 10.0/unavailable since 2026-08-05", and EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (2026-10-18) moved the witness to the Envoy sensor. The dispatch deadband still reads the cloud entity. That is the gap.
- Storm doctrine memory read: no storm hold is involved.
- I did not grep `docs/reviews` for earlier write-not-applied incidents beyond the above. Unknown whether one exists.

## Recommended operator action (nothing was changed by this probe)
1. Do not touch Storm Guard or the kill switches. Nothing is unsafe.
2. To release the reserve, set `number.iq_battery_hacs_battery_reserve` to 12 (or any value at least 2 away from 10). Do NOT set 10: the enphase_ev number returns early when the value equals its stored value (`/config/custom_components/enphase_ev/number.py` `async_set_native_value`, line 385-386), so a write of 10 is a no-op. At the next 5-minute tick URA sees 12 vs desire 10 (diff 2) and writes 10. Prediction to confirm: the Envoy reserve sensor returns to 10 and battery discharge resumes. This is inferred from code; if it does not release, fall back to the Enphase app.
3. Acknowledging the NM alert will not fix the stuck reserve. Ack only after step 2.
4. Card needed: (i) `_reserve_action` deadband must not trust the cloud number when it disagrees with the local Envoy sensor, or must always send on hold release; (ii) the write verifier should compare the cloud oracle to the local witness before firing a "not applied" CRITICAL; (iii) find why the cloud number did not refresh after the 19:35 write.
