# Audit: README straggler live validation, 2026-10-21

Read-only one-shot probe, run Wed 2026-10-21 21:47-22:05 CDT. Live integration v5.103.83 (`/config/custom_components/universal_room_automation/manifest.json`); HA last restarted 2026-10-21 18:25 CDT (entity `last_updated` of the number entities, recorder DB). Sources: URA DB `ura_activity_log` / `notification_log` / `anomaly_log` (`ssh ha sqlite3 /config/universal_room_automation/data/universal_room_automation.db`), recorder `/config/home-assistant_v2.db`, `.storage/core.config_entries`.

**Log-read gap (applies to every "0 URA ERRORs" criterion):** HA core logs are not reachable here. `home-assistant.log*` is empty or pre-journald, `ha core logs` returns 401, docker socket is permission-denied, and no ha-mcp log tool was available to this agent. Those criteria are marked NOT-YET-EVALUABLE, not PASS. The only proxy is that the subsystem is demonstrably writing after the 10-21 18:25 restart.

**Ship dates (git):** v5.103.62 deployed 2026-10-15 19:15 CDT; v5.103.63 (EV buffer) 2026-10-15 22:00; v5.103.67 2026-10-16 14:44; v5.103.68 2026-10-16 22:50; the safety re-page (README_v5.103.65.md, internally titled "v5.103.63") shipped inside the v5.103.69 bundle, 2026-10-17 13:21 (`cfb15c4a2`).

**FAILs: none.** Notable: the v5.103.65 re-page ladder and the v5.103.68 event-gated floor criterion are not yet evaluable, because no qualifying event has occurred.

---

## README_v5.103.62.md (S10 settle gate)

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| `preset_range_by_zone.zone_3` home/away/sleep stay `skipped_already_correct` with correct ranges (home 70-77, away 62-80, sleep 70-77) | PASS (sleep partial) | `sensor.ura_hvac_coordinator_active_preset_overrides` (recorder, latest state 2026-10-21 21:41:15): home `skipped_already_correct` 70.0-77.0; away `skipped_already_correct` 62.0-80.0; sleep desired 70.0-77.0 correct but `status: null` (no sleep visit since the 18:25 restart, RAM status). Latch false and failures 0 for all three. |
| Originals unchanged (home 70/78, away 66/80) | PASS | same sensor `originals_pending_restore.zone_3`: home 70.0/78.0 captured 2026-10-13T11:38:06Z; away 66.0/80.0 captured 2026-10-13T12:14:11Z |
| After a zone_3 preset change, no S10 write within 600 s | PASS (vacuous) | zone_3 S10 `writes: 0` for all presets, `last_write_iso` 2026-10-13 (before the ship). Since the ship (2026-10-15 19:15) 433 `preset_change` rows exist and `climate_write` has zero S10-site rows (sites seen: S1, S4, S5, S7, S11, S12, B5/B6 only). The settle gate's skip step itself is not row-logged, so "skipped because of settle" is not observable; the observable is "no S10 write", which holds. |
| `s10_settle_held_s` is None for zone_3 once settled | PASS | sensor attribute `s10_settle_held_s: {"zone_3": null}`; no `s10_settle_held` rows in `ura_activity_log` or `notification_log` since the ship |
| 0 URA ERRORs after restart | NOT-YET-EVALUABLE | log-read gap (see top) |

## README_v5.103.63.md (EV fill-priority re-pause buffer)

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| Fill-priority entities available | PASS | `number.ura_energy_coordinator_fill_priority_soc` = 80 (last_updated 2026-10-21 18:25:37) |
| 0 URA ERRORs after restart | NOT-YET-EVALUABLE | log-read gap |
| Mid-peak episode with SOC near 80: one resume, no re-pause while SOC >= 77, no switch chatter | PASS (partial: the 77-80 hold branch was not exercised) | `ura_activity_log` garage_a, 2026-10-16 to 10-21: exactly one `fill_priority` pause per day (12:36-12:40Z) and one resume (17:19Z-18:59Z), no pause, resume, pause cycle. Day counts of garage_a fill-priority pauses: 1 on 10-15, 16, 17, 18, 20, 21; 2 on 10-19 (the second at 18:31Z carries `pause_owners=fill_priority,dp`, a drain-protection co-owner, not SOC chatter). `sensor.envoy_482543015950_battery` crosses the 75-82 band on the way up at the resume hour (10-21 17Z min 51 max 77; 18Z min 78 max 98), one resume at 18:10:54Z, no re-pause. SOC never dipped back into 77-80 after a resume in this window, so the new hold rule was neither stressed nor contradicted. |
| Side observation (not a README criterion) | note | `ev_toggle_tripwire` (HIGH) fired 10-18 22:50Z, 10-19 18:36Z, 10-21 22:47Z for garage_a; pause owners `none` / `dp`, not `fill_priority`. 22:00Z is the daily `pause_owners=us` off/on at the peak boundary. Not caused by fill priority, but a recurring flip-flop alert worth a card if none exists. |

## README_v5.103.65.md (safety re-page after acknowledgement; shipped in v5.103.69)

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| Alert pages with `hazard_type` and a location in `notification_log` | PASS (organic, not via the test service) | Safety rows since the ship carry both fields: `high_co2` / Master Bathroom (ids 22946, 22955, 2026-10-19 13:10Z and 14:24Z, MEDIUM), `freeze_risk` / Master Bathroom (ids 23395-23396, 2026-10-22 01:52:42Z, HIGH, companion, delivered=1), `low_humidity` / Garage A and Study A Closet. Pre-ship safety rows (ids 22387, 22494, 22495, 2026-10-16/17) have blank hazard_type. |
| Acknowledge, then one re-page row after the 120 s cooldown | NOT-YET-EVALUABLE | No acknowledged safety alert and no Safety test-service call since the ship (`acknowledged=0` on all safety rows). The only life-safety-class page since the ship is the freeze alert, which is HIGH (not CRITICAL; the repeat loop is for CRITICAL: `notification_manager.py:2790` `_repeat_alert`). Needs a deliberate test smoke alert; this is a one-shot operator or tester action, not a wait. |
| Unacknowledged alert repeats on the Standard ladder (~5 min), not 30 s | NOT-YET-EVALUABLE | same: no CRITICAL life-safety episode. The freeze alert has a single page (2 rows = one companion row plus its [audit] twin) over the ~55 min since 01:52Z. |
| Options flow shows "Smoke, CO and flood repeat schedule" = Standard; saving does not reload CM | PASS for the default, NOT-YET-EVALUABLE for no-reload | `core.config_entries`, "URA: Coordinator Manager": key `nm_life_safety_repeat_schedule` is absent, so `_life_safety_repeat_schedule()` returns the default Standard (`notification_manager.py:2666-2685`, default `const.py:3627`). Options-flow rendering and no-reload are suite-proven only. |
| 0 URA ERRORs | NOT-YET-EVALUABLE | log-read gap |

Recommended disposition: close D1 (hazard type and location) as validated live, and keep the re-page and ladder criteria open until one test smoke alert is run (`ura-prober` can do it only if the operator authorises the Safety test service; I did not call it).

## README_v5.103.67.md (EC outage ledger, Stage L)

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| Within 10 min of restart, 0 URA ERRORs mentioning `outage` / `ledger`, no "thread" RuntimeError | NOT-YET-EVALUABLE | log-read gap |
| At +5 min the first cloud sweep has run: `grid_outage` rows for off-grid events in the last 48 h, or a "0 events" log line, or a calendar-unresolved warning | NOT-YET-EVALUABLE (consistent, not proven) | `grid_outage` rows: 0 (all time). Consistent with no outage: `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history` recorder history 2026-10-15 to 10-21 is only `off` / `unavailable` flips, never `on` (last `off` at 2026-10-21 18:27:05, 1 min after the restart). The sweep's confirming log line is log-only, so whether it ran cannot be shown from the DB. |
| One `nws_alert` row per alert ID; no duplicates after a second restart | PASS | `ura_activity_log`: exactly 1 `nws_alert` row total, id 316571, 2026-10-20T15:24:03-05:00, Air Quality Alert AQA, alert `id` b5000b36-2a39-4a69-4baf-2a128d57e0a1, Expires 2026-10-21T19:00:00-05:00. That alert was active across the 2026-10-21 18:25 restart and no second row appeared (cross-restart dedup held). Caveat: only one alert has been seen since the ship, so update and cancel handling is not exercised live. |
| Side check: local witnesses | note | 0 `local_only` rows. Enpower `grid_status` shows only `unavailable` flips (e.g. 2026-10-20 23:05:56 daily), no real islanding; the README already says the local witness is unproven. |

## README_v5.103.68.md (EC storm Stage A)

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| With no inclement alert, `reserve_write` rows have `inclement_floor=null`; values and reasons match the pre-restart pattern | PASS | `ura_activity_log` `reserve_write`: 145 rows 2026-10-16 to 10-21 (1/20/0/39/80/5 per day on 10-16, 17, 18, 19, 20, 21), `json_extract(details_json,'$.inclement_floor')` is NULL for 145 of 145, `tick_floor` NULL for all. Reasons are the normal strategy text, for example id 317936 (2026-10-21 23:25:49Z) "Mid-peak (shoulder) - discharging ... (degraded telemetry: lkg)", id 317274 "Off-peak hold - SOC 8.0% <= target 10%". |
| `number.*inclement_blind_full_hold_floor*` exists with value 60 | PASS | `number.ura_energy_coordinator_inclement_blind_full_hold_floor` = 60 (last_updated 2026-10-21 18:25:37); entity registry `disabled_by: None` |
| 0 URA ERRORs mentioning `_reserve_action`, `tick_reserve_floor`, `rate_rank` | NOT-YET-EVALUABLE | log-read gap. Proxy: `reserve_write` rows keep landing after the restart (latest 2026-10-21T23:25:49Z), so `_reserve_action` is executing; this does not prove the absence of ERRORs. |
| Event-gated: first inclement hold writes `reserve_write` with non-null `inclement_floor`, non-null `floor_ok`, `value >= inclement_floor` | NOT-YET-EVALUABLE (event-gated) | 0 rows with a non-null `inclement_floor` since the ship. Discriminator for later: `select ... from ura_activity_log where action='reserve_write' and json_extract(details_json,'$.inclement_floor') is not null` and check `value >= inclement_floor` and `floor_ok` not null. Per the Soak Exit rule this should carry a revival trigger (first inclement hold), not ride organic. |

---

## Falsification notes
- v5.103.63 PASS would be disproved by a second `fill_priority` pause of the same charger within the same mid-peak window; the per-day pause counts show none (10-19's second pause carries a `dp` co-owner).
- v5.103.62 vacuous PASS would be disproved by a zone_3 S10 write row; none exist (`writes: 0`, last write predates the ship), but S10 writes may not be row-logged, so this rests on the sensor's own counters.
- v5.103.67 nws_alert dedup PASS rests on a single alert; a re-run after the next distinct alert is advisable but not required to close the criterion.
