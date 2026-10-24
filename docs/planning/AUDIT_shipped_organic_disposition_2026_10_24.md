# Shipped-organic soak-exit disposition sweep, 2026-10-24 (16:50 CDT)

Read-only. Board not edited. 24 `shipped_organic` cards. Sources: URA DB and HA recorder via `ssh ha sqlite3 -readonly` (all timestamps UTC in DB; CDT = UTC-5), live HA running v5.103.89 (restart 19:03 UTC / 14:03 CDT), git, READMEs.

Shipped check: `master` in this repo is stale (head = v4.7.2 era), so "in master" is meaningless. Used `git merge-base --is-ancestor <branch> develop` and release tags v5.103.84-88 (v5.103.89 is HEAD, untagged at audit time). All 24 are in develop and deployed; no card's `next` describes un-deployed work except as stale board text (the `next` fields on most cards are pre-ship text that was never cleared).

## Summary table

| # | Card | Ver | Shipped | Verdict |
|---|---|---|---|---|
| 1 | EC-PREDICTOR-SOLCAST-UNWIRED-1 | .87 | y | DONE |
| 2 | REGIME-NEXT-ROOM-ACCURACY-JSON-COMPARE-1 | .87 | y | DONE (fire path is event-gated; in-suite) |
| 3 | WORKLOG-APPEND-AT-SHIP-1 | .87 | y | DONE |
| 4 | PREDICT-MODEL-DWELL-MIGRATION-1 | .85 | y | DONE |
| 5 | PREDICT-SCORER-BASELINE-SKILL-1 | .85 | y | DONE |
| 6 | WALLPANEL-URA-NOTIFY-1 | .89 | y | FRESH, not evaluated |
| 7 | WS-SUBSCRIBE-SEND-OFF-LOOP-1 | .71 | y | DONE |
| 8 | WS-SUBSCRIBE-SCHEMA-REALHA-1 | .71 | y | DONE |
| 9 | DEPLOY-DUALPUSH-SIGINT-TRAP-1 | .71 | y | DONE |
| 10 | EC-LOADED-VS-INSTALLED-VERSION-1 | .86 | y | RESIDUAL |
| 11 | NM-MULTI-ALERT-TRACKING-1 | .88 (+.89) | y | FRESH (.89 listing); .88 organic criterion met today |
| 12 | SAFETY-TEST-HAZARD-SENDS-NOTHING-1 | .84 | y | RESIDUAL |
| 13 | EC-RESERVE-WRITE-GOVERNOR-1 | .66 | y | DONE |
| 14 | EC-INCLEMENT-HARDENING-1 | .69 | y | CANNOT-EVALUATE (event-gated) |
| 15 | EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 | .89 | y | FRESH, not evaluated |
| 16 | EC-SHUTDOWN-SAVE-AFTER-WRITER-CLOSED-1 | .81 | y | DONE |
| 17 | NM-NOTIFY-SIGNATURE-MISMATCH-1 | .80 | y | DONE |
| 18 | BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1 | .83 | y | DONE |
| 19 | COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 | .86 | y | CANNOT-EVALUATE until 10-25 evening (concern flagged) |
| 20 | HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1 | .62 | y | DONE |
| 21 | PERSON-GPS-ANY-HOME-WINS-1 | .76 | y | RESIDUAL |
| 22 | HOUSE-STATE-SENSOR-ATTR-CHURN-1 | .76 | y | DONE |
| 23 | EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 | .79 (README text in .76/.79) | y | RESIDUAL |
| 24 | ZONE-TRACKER-PER-SENSOR-WIPE-1 | .72 | y | DONE (weak power) |

Totals: DONE 12, RESIDUAL 5, CANNOT-EVALUATE 2, FRESH 3 (incl. #11), REOPEN 0.

## Per-card detail

### 1. EC-PREDICTOR-SOLCAST-UNWIRED-1 (v5.103.87) DONE
- Discriminator (README_v5.103.87:14-17): `energy_forecast_today` numeric; `battery_full_time` no longer `missing_input=solcast`; a different failure (Solcast stale) would disagree with the Solcast sensor.
- Evidence: recorder `sensor.ura_energy_coordinator_energy_forecast_today`: `unknown` 19:03:10 UTC then `-116.6` at 19:03:40 (state is predicted_net_kwh); attr `predicted_production_kwh` 89.2715 equals `sensor.solcast_pv_forecast_forecast_today` 89.2715 at 19:03:26 (exact match, so wired to the right sensor). `battery_full_time` attrs `inputs: "solcast + capacity model"`, state `already_full`/`unlikely_today`, no `missing_input`.
- Note: pre-restart row 15:10 UTC showed -35.0 with production 92.38, so the forecast was already numeric before .89; the first post-.87 restart evidence is mixed but the exact Solcast match settles it.

### 2. REGIME-NEXT-ROOM-ACCURACY-JSON-COMPARE-1 (.87) DONE
- Discriminator: JSON `top` equal to `actual_value` counts as a hit; digest-only fire path.
- Evidence: `regime_detector.py` ~388-410 now uses `_NEXT_ROOM_TOP_SQL = actual_value`; card verify note 10-24 02:01: json_extract hits 1,135/4,845 (23%) vs 0 for the old compare. Merge `1898da293`, in tag v5.103.88. Live firing is weekly-digest-only and none is expected, so no organic observation is possible; the in-suite test is the authority.

### 3. WORKLOG-APPEND-AT-SHIP-1 (.87) DONE
- Evidence: `docs/planning/WORKLOG_2026-10_session.md:234-236` has release-index lines for v5.103.87, .88 and .89 written by deploy.sh.

### 4. PREDICT-MODEL-DWELL-MIGRATION-1 (.85) DONE
- Discriminator (README_v5.103.85:35-41): dwell_share rows ~47/h on the UTC hour, conf>=6, values in [0,1]; next_room prune moves the oldest row off 2026-05-13; skip_ratio_ok.
- Evidence (URA DB): `prediction_results` `dwell_share` 1,504 rows 2026-10-23T10:00 to 10-24T20:00; each sampled hour = 47 rows, confidence 44-192, predicted_value 0.0-0.64. `next_room` oldest now 2026-09-09T07:30 (was 05-13), so prune ran. `bayesian_occupancy` rows older than 45 d = 0. `skip_ratio_ok: true` for Jaya and Ezinne (skip_ratio 0.0); Oji (scored_since_start 0) and Ziri (0 predictions) are null, correctly unscored.
- Minor: 990 `next_room` rows are slightly past 45 d right now (ages 09-09 07:30 to 21:43 UTC); next nightly prune clears them. Hours 15, 18, 19 UTC show no dwell_share group in the 5-row sample only because I limited to 5; not a gap finding. Optimization next-room finding and the 0.23 s query timing not re-checked.

### 5. PREDICT-SCORER-BASELINE-SKILL-1 (.85) DONE
- Evidence: recorder `sensor.ura_coordinator_manager_{ezinne,jaya,oji_udezue}_next_room_accuracy` attrs include `baseline_top1_hit_rate_pct` and `skill_pct` (Ezinne 22.4 / 16.9, Jaya 27.6 / 5.5, Oji 13.8 / 6.9); house sensor `skill_pct` 7.9, `skill_dedup_pct` 9.0.

### 6. WALLPANEL-URA-NOTIFY-1 (.89) FRESH
- Listed only. Discriminators (README_v5.103.89:47, 60-61): `switch.ura_nm_panel_channel` off and `number.ura_nm_panel_lease_ttl_min` 30 after restart; NM health has no `panels` errors; operator-run test leak lights only targeted panels and ack releases them. Channel is default off; the live behaviour is operator-gated.

### 7-8. WS-SUBSCRIBE-SEND-OFF-LOOP-1 and WS-SUBSCRIBE-SCHEMA-REALHA-1 (.71) DONE
- Evidence: `websocket_api.py:234-235` `@callback def _send_on_loop`; `pytest quality/tests/test_websocket_api.py quality/tests/test_deploy_scripts.py` = 31 passed, 0 skips (run 16:5x CDT). README_v5.103.71:26-28 records the mutation drills (drop `@callback` -> 1 red; revert schema -> 4 red). Not live-observed (no recorder signal for a websocket subscribe); in-suite authority is the correct one for an import/registration defect.

### 9. DEPLOY-DUALPUSH-SIGINT-TRAP-1 (.71) DONE
- Evidence: `scripts/deploy.sh:265-292` rc 130/143 handling; `test_deploy_scripts.py::test_v4710_trap_restores_clean_url_on_sigint` passes (12/12 per README). Script-only; nothing to observe in HA.

### 10. EC-LOADED-VS-INSTALLED-VERSION-1 (.86) RESIDUAL
- Discriminator (README_v5.103.86:42-45): after install and before restart, Repairs shows `restart_pending_version_mismatch` and `restart_pending: true`; after restart the issue is gone.
- Evidence: negative half PASS: `sensor.ura_coordinator_manager_coordinator_manager` at 20:03:42 UTC `loaded_version 5.103.89`, `installed_version 5.103.89`, `restart_pending false`; no URA issue in `/config/.storage/repairs.issue_registry`. Positive half never observed: 0 recorder rows with `"restart_pending":true` in 7 days, even though .86-.89 were each installed then restarted (the install-to-restart gap was probably shorter than the sampling, or the attribute only records on state change; unknown).
- Disposition: close primary (no false positive, sensor wired and reading). Residual: positive-branch live proof; check on the next deploy that has an install-before-restart gap with `restart_pending` read directly from the live entity during the gap. The in-suite test covers it.

### 11. NM-MULTI-ALERT-TRACKING-1 (.88; listed again at .89) FRESH + organic criterion met
- Discriminator (README_v5.103.88:26): first ack marks every channel row of that alert acknowledged.
- Evidence (`notification_log`, today's operator smoke test, see #12): rows 23810-23813 (pushover, companion, whatsapp, imessage) all `acknowledged=1` with ack_time 21:47:50 UTC from one ack. Only the `[audit]` aggregate row 23814 (channel "companion,imessage,pushover,whatsapp") stays `acknowledged=0`; count of unacked single-channel CRITICAL rows since 10-17 = 0. README_v5.103.89:47 says "zero unacked CRITICAL rows"; the audit row is a literal exception (probably by design, but confirm the criterion text excludes `[audit]`).
- The smoke + perimeter overlap is in-suite only (by README).

### 12. SAFETY-TEST-HAZARD-SENDS-NOTHING-1 (.84) RESIDUAL
- Discriminator (README_v5.103.84:24-26): before the fix 0 rows; now a "TEST safety alert" row per channel; repeats on the life-safety schedule until ack.
- Evidence: 5 rows 2026-10-24T21:42:15-16 UTC (4 channels + audit), `hazard_type smoke`, `location Kitchen`, severity CRITICAL, delivered=1. The operator acked at 21:47:50 UTC. Sent path PASS (this is the first-ever evidence the test service delivers).
- Residual: 0 repeat rows between 21:42:16 and the 21:47:50 ack (5 min 34 s), and the README expected rows "every ~5 min on Standard". `cooldown_expires` on the imessage row = 21:49:50 (ack+2 min). Either the first repeat falls after 5:34 or no re-page fired; unknown. To close: run the test once more with the ack held back >10 min, or read the repeat schedule constants; this also closes README_v5.103.65's re-page criterion.

### 13. EC-RESERVE-WRITE-GOVERNOR-1 (.66) DONE
- Discriminator (README_v5.103.66:49): `reserve_write` rows with non-null value, path, status.
- Evidence: `ura_activity_log` `action='reserve_write'` 227 rows from 2026-10-16T23:42 to 10-24T20:08; latest `status applied, path timer, value 90, desire 90, hold_owner arbitrage_attain`; sampled rows carry real value/desire/owner, not sentinels.

### 14. EC-INCLEMENT-HARDENING-1 (.69) CANNOT-EVALUATE (event-gated)
- README_v5.103.69:111-126 already has a `Validated 2026-10-17` table; the observable criteria pass. The load-bearing behaviours (storm hold window, prepare floor, forecast confirmation, blind-gate inclement evaluation) need a qualifying NWS alert. `ura_activity_log` shows no inclement/storm hold rows since 10-17 and the board's own 10-24 02:09 note says no storm alert has occurred since.
- Trip-wire/trigger: the trigger is already recorded as "first storm schedules a buy block" on this card. Disposition: close the shipped deliverable as done-with-validated-table and leave the first-real-storm check as a parked trigger (do not keep it organic).

### 15. EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (.89) FRESH
- Listed only. Discriminators (README_v5.103.89:57-59): strategy sensor exposes `reserve_reference_source`, `reserve_last_landed(_at)`; next reserve change writes carry `reserve_reference_source` and no identical write inside 900 s; zero false CRITICAL `envoy_write_verification` pages when the local witness confirms. Residual already on card: RG-L2 (bind stream witness to Envoy serial before multi-home rollout).

### 16. EC-SHUTDOWN-SAVE-AFTER-WRITER-CLOSED-1 (.81) DONE
- README_v5.103.81:26-31 `Validated 2026-10-21`: `energy_state` rows stamped 20:45:47 UTC at the stop instant, 0 `write worker is closed` lines (previous 26 and 34). Disposable on that table; no contrary evidence found.

### 17. NM-NOTIFY-SIGNATURE-MISMATCH-1 (.80) DONE
- README_v5.103.80:33-41 `Validated 2026-10-20`: 0 `NM notify failed` / `unexpected keyword` lines after restart. The wake-backstop path is the only unobserved branch (at most once a day, gate-stall only); covered per-site in-suite with mutation drills. Close.

### 18. BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1 (.83) DONE
- Open items in README_v5.103.83:57+ (NULL-duration exit; replay G1-G4) both now evaluated:
  - `occupancy_events` since 10-21T23:30 UTC: 22 `exit` rows with NULL duration (fan/failsafe exit rows now exist); `entry` followed by `entry` in the same room: 0 after deploy vs 135 in 10-10..10-21.
  - Replay: `ssh ha "python3 - --days 7" < scripts/probes/occupancy_dwell_backtest.py`, shipped setting 0.02 / 1800 s / 48-cell: G1 true (median 0/day, max 1/room), G2 true (heuristic; 4 sample fires, 0 resident overlap), G3 true (Study A daytime fires 0, mean share 0.565), G4 true (47/47 rooms learned).
  - No notification from `bayesian_predictor`/`occupancy` coordinators since deploy (`notification_log` count 0).
- Residual not blocking: `anomaly_log` has 0 `occupancy.dwell_anomaly` rows, so "row shape after first on" is unexercised live; the replay predicts ~4 fires per 7 days, consistent with none in the 3 days since deploy. In-suite covers row shape.

### 19. COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (.86) CANNOT-EVALUATE until the 10-25 evening; concern
- Discriminator (README_v5.103.86:91-97): `whole_house_source = ec_total`; `delta_percent` does not walk steadily negative 14:00-23:00 local on a sunny day; `whole_house` tracks the Envoy lifetime consumption.
- Evidence: `whole_house_source: "ec_total"` first appears in the recorder at 2026-10-24 16 UTC (the card's code only loaded with the 10-24 restarts); a second restart at 19:03 UTC set `post_restart_window: true` and re-anchored (`whole_house` 0.0 at 19 UTC). So no clean evening has run on the new source. Right now (21:48 UTC): `whole_house 26.42`, `rooms_total 52.47`, `delta_kwh -34.14`, `delta_percent -129.2`.
- Concern to check, not a verdict: Envoy `lifetime_energy_consumption` (MWh) rose 33.1826 to 33.3123 in 24 h (about 130 kWh/day), but `whole_house` is 26 kWh at 16:48 CDT and is a post-restart delta while `rooms_total` is not obviously on the same window (scope mismatch). Pre-fix evenings (10-21..10-23, old source) show the original walk: -21.9 to -26.2 at 19 UTC, -34 to -37 at 22 UTC, -47 to -51 at 01 UTC.
- Test for 10-25: query `sensor.universal_room_automation_energy_coverage_delta` `delta_percent` at 19:00 UTC (14:00 CDT) vs 04:00 UTC (23:00 CDT) with no restart in between; passes if the drop is under about 10 points. If it still walks, REOPEN. Do not close now.

### 20. HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1 (.62) DONE
- Discriminator (README_v5.103.62:24-26).
- Evidence: README `Validated 2026-10-21` (all PASS bar "NOT-YET-EVALUABLE" log-read). Live now: `sensor.ura_hvac_coordinator_active_preset_overrides` at 21:48:15 UTC shows `s10_settle_held_s: {"zone_3": 579}`, i.e. the settle gate actively holding 591 s after the zone_3 preset change `away -> home` logged at 21:38:24 UTC; zone_3 home/away `skipped_already_correct`, `writes 0`, `failures 0`. Since the ship: 647 `preset_change` rows and 0 `climate_write` rows from an S10 site (sites seen: S1, S4, S5, S7, S11, S12, S3, S1+resume/pin). This is the previously missing positive observation of the gate holding after a real preset change.
- Caveat: S10 writes legitimately happen outside this window; the claim is only "no re-write inside the 600 s window".

### 21. PERSON-GPS-ANY-HOME-WINS-1 (.76) RESIDUAL
- README_v5.103.76:113-115: no-op at Madrone (one GPS tracker per person); real check at Wigton: `person.omonele` `tracker_sources.gps` matches its freshest tracker. No Wigton access from this host, so that discriminator cannot be evaluated here. Disposition: close primary (code merged `c446604b1`, diagnostic-only, kill switch `PERSON_GPS_FRESHEST_WINS_ENABLED`); park the Wigton check with revival trigger "next Wigton session / any iPad-vs-phone GPS disagreement report".

### 22. HOUSE-STATE-SENSOR-ATTR-CHURN-1 (.76) DONE
- Discriminator (README_v5.103.76:99-104): distinct `attributes_id` per hour from ~120 to well under 20; row count unchanged ~120.
- Evidence: recorder `sensor.ura_presence_coordinator_presence_house_state` (`PresenceHouseStateSensor`, sensor.py:5655): before 10-20 20:00 UTC 120 rows / 120 distinct per hour; sampled hours after: 120 rows / 1-12 distinct (10-21 04: 1; 10-23 20: 4; 10-24 20: 4). Row count stays 119-120.
- Note: first attempt used `sensor.ura_coordinator_manager_house_state` (a different class, 120/120 unchanged); that is not this card's entity.

### 23. EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (.79) RESIDUAL
- Discriminator (README_v5.103.76:45-52 text, README_v5.103.79:29-40 validated table): `utility_source == "statistics"`, divergence not 100, `utility_stats_error` null; refresh at most hourly.
- Evidence: `sensor.ura_energy_coordinator_predicted_bill` at 21:48:45 UTC: `utility_source statistics`, `utility_stats_error null`, `utility_stats_refreshed_at 2026-10-24T16:03:35-05:00`, `utility_stale false`; `utility_last_cycle` window 2026-09-24..2026-10-24, `utility_import_kwh 2335.36`, `utility_net_cost 188.36`, `ec_import_kwh 2258.04`, `divergence_cost_pct 20.9` (inside the README's expected +20-30% EC-history artifact range), `utility_bill_estimate 220.86`.
- Residuals: (a) the fixed numbers (3669.4 kWh / $295.13) belonged to the 08-23..09-23 window and are moot since the cycle rolled on 10-24 (window start now 09-24, so cycle day is 24, not 23; the open ANSWER about PEC reading 24/25 appears superseded and should be re-confirmed by the operator); (b) the sensor is now `unknown` / "Learning (0 days)" by design at cycle start; (c) MAPE and cycle scoring remain unproven until the 11-24 close (README says so); `accuracy_cycles_scored 0` at the 10-24 close.

### 24. ZONE-TRACKER-PER-SENSOR-WIPE-1 (.72) DONE (weak power)
- Organic check (README_v5.103.72:63): first sleeping nights show no spurious AWAY / zone holds.
- Evidence (`house_state_log` since 10-18 02:00 UTC): 7 `home_night->sleep`, 7 `sleep->waking`, 0 `sleep->away` or `home_night->away`. Prior: `sleep->away` on 09-13, 09-15, 10-01 and `home_night->away` 10-05 (the failure shape). So 7 clean nights vs 4 failures in the preceding ~6 weeks; supportive but the base rate is low, so power is modest. No contrary evidence.

## Method notes and gaps
- Cards 6, 11 (.89 listing), 15 were not evaluated beyond listing, per instruction.
- Verdict REOPEN count is 0; the closest are #19 (coverage drift, pending a clean evening) and #12 (re-page cadence unproven).
- Not verified: ERROR-level log scans (HA log at `/config/home-assistant.log` is empty on this host; core logs are elsewhere), the Optimization next-room finding, and `dwell_share` UTC-hour gaps beyond the sampled hours.
- Queries are reproducible with `ssh ha sqlite3 -readonly <db> "<sql>"` on `/config/universal_room_automation/data/universal_room_automation.db` and `/config/home-assistant_v2.db`.
