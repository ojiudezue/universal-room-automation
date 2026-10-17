# v5.103.69: storm Stage B+C, observation-mode reserve gate, safety re-page, S10 notify HIGH

Bundled release; the operator approved bundling and restarting on 2026-10-17. Deploy risk: **HIGH**, because it changes battery reserve and grid-charge decisions and life-safety paging.

| Part | Card | Tier |
|---|---|---|
| 1. EC storm Stage B+C | EC-INCLEMENT-HARDENING-1 | 3 |
| 2. Observation mode gates reserve writes | EC-OBSERVATION-MODE-RESERVE-BYPASS-1 | 2 |
| 3. Safety alerts re-page after acknowledgement | SAFETY-NM-REFIRE-UNWIRED-1 | 2-DB |
| 4. Custom Preset Ranges notifications are HIGH | HVAC-S10-NOTIFY-UNDELIVERED-1 | 1 |

## 1. EC storm Stage B+C (EC-INCLEMENT-HARDENING-1)

Plan: `docs/planning/PLANNING_ec_storm_and_blind_decisions.md` Rev 3.5. Stage A shipped as v5.103.68.

Reviews, all four framings, in `docs/reviews/code-review/ec_stage_bc_review_{A,B,C,D}.md`:
- **A and D:** fixed in 9ff82272b.
- **B:** B-MED-1 was a boot gap in the hourly refresh, fixed in 186364ed3. B-LOW-2 was fixed in 95ecb7430.
- **C (per-site mutation):** 26 of 27 surviving mutants now fail a named test (218732b46). The remaining one is an equivalent LOW.

The operator approved the Tier-3 checkpoint on 2026-10-17.

### What changed
- **D-B1, alert time window.** An alert holds from Onset (or Sent) to Ends (or Expires). Cancels, non-Actual alerts, and alerts not yet started or already ended are dropped. Before this, an alert expired at its own start.
- **D-B2, product table** (`INCLEMENT_PRODUCT_TABLE`). Alerts are matched by NWS code or exact event name, and drift between the two writes `inclement_code_drift`.
  - Polygon products (SVW/TOW) count only when the polygon covers the house.
  - Wind Advisory is no longer gated out.
  - D-B2a: a per-product `precharge_eligible` column decides whether a hold may grid-charge.
- **D-B3, feed health and hold memory.** The new `inclement_alerts_stale` attribute flags a stale alert feed.
- **D-B4.** The hold logic uses the TOU engine's bottom rate instead of literal `off_peak`.
- **D-B5.** The legacy power-threat event list and min-severity fields are removed from the options flow. The constants are kept, and nothing is written to options.
- **D-B6, pre-onset prepare floor.** When a hold-class alert starts within the lead window, the reserve is raised to `number.*inclement_preonset_floor*` (default 80) before the storm arrives.
- **D-B7, Storm Guard trip-wire.** If Enphase Storm Guard turns on, a `storm_guard_enabled` anomaly is recorded.
- **D-C1, hourly forecast outlook.** `WeatherProviderManager` refreshes the outlook every 30 min. It treats an outlook older than 120 min as no data. When a provider recovers and the outlook is empty, one fetch runs immediately and is tracked (B-MED-1).
- **D-C2, forecast confirmation.** A zone grid-buy needs the local forecast to confirm the hazard over the alert window:
  - **Freeze / cold:** min temp <= 28 F, using apparent temp for wind chill and extreme cold.
  - **Winter storm:** min temp <= 32 F and rain chance >= 50% (or >= 1.0 mm where the provider gives no probability).
  - **Thunderstorm / tornado / hurricane (operator 2026-10-17, "I don't want grid buys on mere rain"):** a storm condition (lightning, hail, tornado, hurricane) in the forecast **and** rain chance >= 70% (or >= 1.0 mm where the provider gives no probability). Heavy rain ("pouring") alone does not confirm.
  - A confirmation latches for that alert until the alert ends.
  - **Effect of the convective rule:** every pre-charge-eligible convective product is a polygon warning (SVW/TOW/EWW), and those never consult the forecast. So the rule's practical effect is on convective **watches**: whether a Severe Thunderstorm Watch or Tornado Watch counts as corroborated, which decides full vs partial hold depth and the pre-onset floor. A watch with only heavy rain forecast now stays at partial hold.
  - Builder mutation drills (8ffba9104): AND→OR gives 10 RED; 70→50 gives 2 RED; adding "pouring" gives 1 RED.
  - Orchestrator drills on the bundle-bound branch, each restored, with a clean tree after:
    - `_cfg_buy_commanded` → True: 2 RED (`test_*_stripped_turn_on_no_*`)
    - convective AND→OR: RED (`test_forecast_confirms_predicates[...outlook7-False]`)
    - `_maybe_hourly_catch_up` neutered: 2 RED (`test_provider_recovery_after_boot_refreshes_hourly_immediately`, `test_hourly_catch_up_not_retriggered_once_rows_exist`)
- **D-C3.** New strategy-sensor attributes `inclement_forecast` and `inclement_buy_forecast`.

### Grid buying is still OFF
- Every grid pre-charge stays behind `inclement_grid_precharge_on_hold`, which is **False** (options flow). This release does not turn it on.
- Per plan Rev 3.3, the operator turns it on only after Stage C's forecast is validated live.
- Until then Stage B+C changes hold and prepare floors only. No grid import is commanded.

### Known limits
- The forecast thresholds are not fitted: no hourly rain-chance history existed. Revisit them once a season of `nws_alert` + forecast data accrues.
- The polygon top-up leg does not consult the forecast, by design. It covers a verified polygon warning over the house, capped at 60 min from the alert start.
- Plan §12 limits 14, 25 and 26 are recorded in the plan.

## 2. Observation mode gates reserve writes (EC-OBSERVATION-MODE-RESERVE-BYPASS-1)

### Why
In energy observation mode, two paths could still write the battery reserve to hardware:
- the Coordinator Manager's TOU-transition battery actions
- the write-verify self-heal re-send

### What changed
- **D1:** the TOU-transition path is gated (`energy.py`).
- **D2:** the write-verify re-send is gated at `WriteVerifier._pending_fire_retry`. In observation mode the pending episode is frozen, not reset (plan rev 3), so turning observation off resumes it cleanly.
- The conduct check stays ungated.

Plan: `docs/planning/PLANNING_ec_observation_mode_reserve_gate.md`. Writer coverage: `docs/planning/AUDIT_ec_observation_mode_writer_coverage.md`. Out of scope and carded separately: EV-charger writes in observation mode (EC-OBS-DP-EVSE-1).

## 3. Safety alerts re-page after acknowledgement (SAFETY-NM-REFIRE-UNWIRED-1)

Built and reviewed as v5.103.65 (`docs/readmes/README_v5.103.65.md`, review record `docs/reviews/code-review/v5.103.65_safety_nm_refire.md`). It ships here because v5.103.66–.68 shipped first.

### What changed
- An acknowledged smoke, CO or flood alarm is re-paged after its cooldown while the hazard stays active. Before, Safety sent no hazard type or location, so the re-check never matched.
- New Coordinator Manager setting **"Smoke, CO and flood repeat schedule"**: Standard (default, the old ladder), Fast start, or Urgent. Changing it does not reload the Coordinator Manager.
- The life-safety bypass of quiet hours needs severity HIGH or above.
- Side effects:
  - smoke/CO flash orange and flooding pulses blue
  - speakers announce smoke/CO overnight despite Do Not Disturb

Known gaps are carded: SAFETY-NO-INITIAL-SENSOR-PASS-1, NM-MULTI-ALERT-TRACKING-1 and SECURITY-REFIRE-INTRUSION-KEY-1. Separately, the kitchen smoke detector has been unavailable since 10-15, so this re-page cannot fire for it until it is re-paired.

## 4. Custom Preset Ranges notifications are HIGH (HVAC-S10-NOTIFY-UNDELIVERED-1)

Before, these notifications went out at MEDIUM and reached nobody. Now they are HIGH, so they reach the phone. They fire when URA gives up on a thermostat range:
- the thermostat is unreachable
- the range isn't taking
- the original range wasn't restored

## Merge

Branch `integ/bundle-v5.103.69` from develop fc4e80d4b:
- obs-gate merged in 52f63f735
- S10 merged in 23ef41ec8
- safety merged in 29c45c24f
- feature/ec-stage-b (8ffba9104) merged in b94e7ec33

`test_part2_ec_hc_writeback.py` conflicted twice on the reload-suppress key count. Each time both new keys were kept: `nm_life_safety_repeat_schedule` (103), then `inclement_preonset_floor` (104).

## Tests

- Stage B+C cycle files: 1876 passed before the convective change, and 1810 passed in the 8 cycle files after it.
- Full-suite name-diff of feature/ec-stage-b vs 88dd37aa0 found 1 NEW: a lint false positive, fixed test-only in 1ff5062cb. The isolated 152-file pass then showed NEW=[].
- Obs-gate + S10 files: 169 passed.
- Safety + NM + reload files: 400 passed.
- Full-suite name-diff of the integrated branch vs develop: _(filled at deploy)_.

## Live validation (prospective)
- **Live:** 0 URA ERRORs after restart mentioning `inclement`, `forecast`, `hourly`, `_reserve_action`, `notification_manager` or `safety`.
- **Live:** `sensor.ura_energy_coordinator_battery_strategy` attr `inclement_forecast.fetched_at` is set within a minute of setup and advances about every 30 min, with `providers_ok` > 0. A frozen `fetched_at` means a dead timer; `providers_ok=0` means a silent fetch failure.
- **Live:** `inclement_preonset` is `null` with no future hold alert.
- **Live:** `number.*inclement_preonset_floor*` exists and reads 80.
- **Live:** `inclement_alerts_stale` reads false.
- **Live:** `inclement_grid_precharge_on_hold` is still False in `.storage/core.config_entries`, and 0 `reserve_write` rows have reasons starting `Inclement pre-onset` with a grid charge.
- **Live:** Storm Guard switch reads off, and there are 0 `storm_guard_enabled` anomaly rows.
- **Live:** the options flow no longer shows the two legacy inclement fields, and there is no CM `async_update_entry` in the setup log window.
- **Live:** the CM options flow shows "Smoke, CO and flood repeat schedule" = Standard.
- **Live (event-gated):** the first test or real life-safety alert writes `notification_log` rows with `hazard_type` and a location.
- **Live:** with observation mode off (live state), `reserve_write` rows and reasons match the pre-restart pattern.
