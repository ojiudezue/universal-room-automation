# v5.103.76: the EC bill check compares against SmartHub hourly statistics

> **Draft.** The version number may be renumbered at deploy.

Card: EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (Step 2). Plan: `docs/planning/PLANNING_ec_bill_divergence_from_smarthub_stats.md` (plan-reviewed; Rev 2 binding). Audit: `docs/planning/AUDIT_smarthub_bill_actual_2026_10_18.md`.

**Tier 2, reviewed with 3 framing-disjoint passes** (A correctness/window/TOU math, B async/lifecycle/decision-cycle non-blocking, C mutation). Display/diagnostic only: no decision path reads these attributes. Deploy risk: LOW.

## Problem → solution

- **The problem.** `utility_divergence_pct` on the predicted-bill sensor read a false 100.0. It compared the dead SmartHub *monthly* entity (month-start reset) against EC's 23rd-start cycle accumulator.
- **The fix.** EC now reads SmartHub's *hourly* long-term statistics (alive, gap-free, within about 1% of three PEC bills), prices each hour through the same TOU engine calls as counter-mode billing, and compares against EC's `energy_daily` over the identical set of local dates.
  - Recorder call: `get_instance(hass).async_add_executor_job(statistics_during_period, hass, start, None, ids, "hour", None, {"change"})` (`energy.py` `_query_utility_statistics`). `recorder` is not added to the manifest.
  - The decision cycle only *schedules* the refresh as a tracked background task (`hass.async_create_background_task`, the `_refresh_outage_days_this_cycle` idiom; handle kept in a slot like `_dp_eval_last_task` and cancelled in `async_teardown`). Single-flight, at most once per `UTILITY_STATS_REFRESH_MIN` = 60 min, stamp set before the first await.
  - Pure helpers in `energy_billing.py`: `price_hourly_utility_rows`, `utility_window_end`, `sum_utility_window`, `tou_import_rate_floor`, `build_utility_divergence_block`.
  - Previous cycle start = `CostTracker._get_cycle_start(cycle_start − 1 day)` (no month arithmetic).
  - `ec_underpriced_days`: window days whose EC import cost / kWh is below the TOU engine's lowest effective rate for that date.
- **New options fields** (EC options step, next to the utility meter): *Utility import statistic*, *Utility export statistic*. Blank import = feature off (kill switch, legacy entity path unchanged, attributes byte-identical). A non-blank value must contain `:`.
- **Knobs:** `UTILITY_STATS_REFRESH_MIN` 60, `UTILITY_STATS_STALE_H` 48, `UTILITY_DAY_COMPLETE_LAST_HOUR` 23, `UTILITY_RATE_FLOOR_REL_TOL` 1e-6 (module consts, `energy_const.py`); statistic ids (options flow).

## Prerequisite (Step 1, operator config action, same restart window)

1. Clear `energy_utility_meter_entity` in the Coordinator Manager EC options (it is ignored once the statistic ids are set, but clearing it removes the dead entity).
2. Set *Utility import statistic* = `smarthub:smarthub_energy_sensor_<ACCT>_<LOC>` and *Utility export statistic* = `smarthub:smarthub_energy_return_sensor_<ACCT>_<LOC>` (ids in plan §2, `statistics_meta` 4699 / 6396).
3. Saving the two ids does **not** reload anything: EC reads them live from the CM options on every refresh (`_utility_stat_ids`, reusing `_get_cm_options`), and both keys are in `OPTIONS_RELOAD_SUPPRESS_KEYS`. A changed id is used on the next decision cycle; the cached comparison of the old ids is not shown in the meantime.

## Review fix-ups (Reviews A + B)

- **A-M1:** when EC has no `energy_daily` rows in the window (DB unavailable, or none), the divergence keys are `None` instead of a spurious ±100 %.
- **A-M2:** `utility_bill_estimate` adds the service charge from the loaded TOU rate file (`TOURateEngine.service_availability_monthly`), falling back to the PEC constant only when the file lacks it.
- **B-M1:** the statistic ids are no longer construction keys; saving them reloads neither the CM nor the parent integration (see Prerequisite 3).
- **B-L3:** the refresh is not scheduled once EC is disabled or teardown has started (`_utility_stats_closed`, set first thing in `async_teardown`).
- **Kept:** the per-day `energy_daily` reads (a grouped query needs a new `database.py` DAO, a Tier 2-DB trigger) and the 1 h `data_age_h` granularity (A-L2, accepted).

## Tests

- `test_ec_bill_divergence_smarthub_stats.py` (19), `test_ec_bill_divergence_sensor_attrs.py` (2), `test_ec_bill_divergence_options.py` (4), plus fix-up tests (6 in the stats file, `test_ec_role_defaults_rev5.py::test_utility_statistic_ids_save_does_not_reload`). Fix-up mutation drills (9 sites) all RED.
- The blank-ids snapshot test also passes against the pre-change `sensor.py`/`energy.py` (byte-identical no-op path).
- Builder mutation drills M1–M20, all RED (incl. schedule→direct await, deleted schedule call, deleted teardown cancel).

## Live validation (to be replaced by a Validated table)

All one-shot reads of `sensor.ura_energy_coordinator_predicted_bill` attributes, within ~1 h of the restart (the first refresh can land one interval late if the recorder was not ready at boot).

- **Source:** `utility_source == "statistics"`; `utility_divergence_pct` is NOT 100.0; `utility_stats_error` is null.
- **Last cycle (valid ONLY with `energy_bill_cycle_day = 23`; if the knob changed, recompute with `.claude/scratch/billprobe/` first and note it here):**
  - `utility_last_cycle.utility_import_kwh` = **3669.4 ± 0.5**
  - `utility_last_cycle.utility_net_cost` = **295.13 ± 0.5** (a base-rate build gives ~139.27; an end-exclusive or day-23 off-by-one build gives neither)
  - `utility_last_cycle.ec_import_kwh` = **3428.4** (= `SELECT SUM(import_kwh) FROM energy_daily WHERE date >= '2026-08-23' AND date < '2026-09-23'`)
- **Current cycle:** `utility_kwh` ≥ **2204.1** (09-23..10-17) and grows by one day per daily import; `utility_window` ends the day after the newest complete local day.
- **F1 attribution:** current-cycle `ec_underpriced_days` > 0 while pre-10-09 EC history is in the window; `utility_divergence_cost_pct` roughly +20–30%. That is an EC history artifact (F1), not a regression.
- **Cadence / loop safety:** `utility_stats_refreshed_at` advances at most once per hour; no `Detected blocking call` warnings mention `statistics` in the HA log after restart.

---

# Also in v5.103.76: house-state sensor attribute churn left out of the recorder

Card: HOUSE-STATE-SENSOR-ATTR-CHURN-1. Tier 1.


## Summary
`sensor.ura_presence_coordinator_presence_house_state` wrote about 2,870 recorder rows a day.
Measured 2026-10-19, 2,869 of them carried a distinct attribute blob (average 3.3 KB, about
9.5 MB/day of attribute JSON) for 13 state changes. The main cause is `dwell_seconds`, which
changes on every 30 s poll. HA dedupes attribute blobs by content, so leaving the churny keys
out of the recorder lets rows share blobs again.

## What changed
- `sensor.py` `PresenceHouseStateSensor._unrecorded_attributes` now also lists `dwell_seconds`,
  `zones`, `signal_consensus`, `signal_consensus_band` and `signal_consensus_inputs`. It already
  listed `stale_counted_home` and `nobody_home_zone_input`.
- Live `state.attributes` are unchanged. Dashboards, the PWA and in-process readers see every key.
- Low-churn diagnostics are still recorded: `state`, `previous_state`, `state_since`,
  `veto_path`, `last_veto_decision`, `last_away_*`, `away_entries_today`, `guest_reason`,
  `census_count` and `boot_settle_*`.

## Consumer check (recorder-history readers)
| Key | 24 h changes | History reader found | Decision |
|---|---|---|---|
| `dwell_seconds` | 2,869 | None. `routine_forecaster.py:343` computes its own local `dwell_seconds` from state timestamps and does not read the attribute | Unrecord. It can be derived from `state_since` |
| `zones` | 678 | None. Frontend bundles and tests read live state only | Unrecord |
| `signal_consensus_inputs` | 666 | `PLANNING_fan_noise_mitigation_layer2_actuation.md:44` lists "recorder attribute history" as a diagnostic recipe | Unrecord. The same dict stays recorded on `sensor.ura_presence_coordinator_signal_consensus_confidence` (`sensor.py` `SignalConsensusConfidenceSensor`) |
| `signal_consensus` | 67 | None | Unrecord. It is the native state of `sensor.ura_presence_coordinator_signal_consensus_confidence` |
| `signal_consensus_band` | 64 | None | Unrecord. It is recorded as `consensus_band` on the same sensor |
| `fan_interference_active` | 184 | n/a | Not a top-level key. It lives inside `signal_consensus_inputs` |

The `veto_path` and `last_veto_decision` history readers (`PLANNING_v4.7.15.1...md:458`, README_v5.103.54) are unaffected because both keys stay recorded.
Existing idiom followed: `_unrecorded_attributes` on `SafetyStatusSensor`, `SecurityComplianceSensor` and others in `sensor.py`.

## Tests
- New `quality/tests/test_house_state_attr_unrecorded.py`. It asserts on HA's combined
  `Entity.__combined_unrecorded_attributes`, which is the set the recorder actually receives.
  Churny keys must be in it and kept diagnostics must not be.
- `test_house_state_sleep_mask_ble_memory.py::test_unrecorded_attributes_set` exact pin updated.
- Mutation drill: removing `dwell_seconds` made the test go RED, and so did adding `veto_path`.
  The file was restored afterwards.

## Live acceptance (prospective, one-shot recorder query 1-2 h after the restart)
- Distinct `attributes_id` per hour for the sensor drops from about 120 to **well under 20**.
- Row count per hour is unchanged (about 120).
- State history is intact: the 13 or so daily state changes are still present.
- **Discriminator:** if the row count drops sharply while blobs stay high, something else
  changed (polling or write path), not this fix. If blobs stay at about 2,869, the exclusion
  did not take effect (wrong class, or a stale install).

---

# Also in v5.103.76: per-person GPS uses the freshest tracker

Card: PERSON-GPS-ANY-HOME-WINS-1. Plan: `docs/planning/PLANNING_person_gps_freshest_wins.md`. Tier 2, two reviews (A correctness, B ripple/lifecycle/test authority), both SHIP.

- **Before:** a person with several GPS trackers took the reading of the last one listed, so a stale iPad could overwrite the phone.
- **Now:** the freshest tracker in a real state (`home`, `not_home` or a zone) wins; unknown/unavailable never beats a real reading. This matches HA's own `person` entity. Kill switch: `PERSON_GPS_FRESHEST_WINS_ENABLED`.
- **Scope:** diagnostic only. Location and home/away still come from `person.<x>.state`; this changes `tracker_sources`, `tracking_reason` and `confidence` attributes.
- **Live:** no-op at Madrone (one GPS tracker per person). Check at Wigton: `person.omonele`'s `tracker_sources.gps` matches its freshest reporting tracker.

---

# Also in v5.103.76: 365-day retention for room history tables

Card: DB-SIZE-GROWTH-1. Plan: `docs/planning/PLANNING_db_retention_365d.md`. Tier 2-DB, three reviews (A data integrity, B migration/lifecycle, C mutation), all SHIP.

- Nightly (02:30) batched prune of `environmental_data`, `energy_snapshots`, `occupancy_events` and `room_transitions`: rows older than 365 days. 1,000-row batches, 0.1 s yield, at most 100 batches per table per night. `RETENTION_ROOM_HISTORY_DAYS = 365` (0 disables), `ROOM_HISTORY_PRUNE_MAX_BATCHES = 100`.
- The two duplicated nightly op lists in `__init__.py` are now one shared list (`nightly_maintenance.py`).
- **No row is old enough yet** (oldest 2025-11-19): deletion starts about 2026-11-19, ~one day of rows per night. Stops growth; does not shrink the file.
- **Live:** the 02:30 log shows a `room_history` run with 0 deleted per table; no write-queue warnings.
- Offline DB copy taken before deploy (D0).


## Validated 2026-10-20 (v5.103.76 restart ~10:45, v5.103.77 restart ~12:00 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Bill check reads SmartHub statistics | PASS | `utility_source: statistics`, `utility_stats_refreshed_at: 2026-10-20T12:04`, `utility_stats_error: null` |
| Same-window comparison | PASS | `utility_window: 2026-09-24..2026-10-20` (cycle day 24 after v5.103.77) |
| No false 100% divergence | PASS | `utility_divergence_pct: 3.4` (kWh). Cost: utility $176.71 vs EC $136.43; `ec_underpriced_days: 9` explains most of the $ gap (EC history, per plan M2) |
| Statistic ids saved without a reload | PASS | options save applied; all 50 entries stayed loaded |
| Load | PASS | manifest v5.103.76, 50/50 loaded, 0 URA ERRORs |
| House-state attr churn | not yet measured | one-shot recorder blob check due 1-2 h after restart |
| GPS freshest-wins | no-op here | one GPS tracker per person at Madrone; Wigton check pending its re-enable |
| 365-day retention | not yet exercised | first 02:30 run tonight should log `room_history` with 0 deleted |
| Clear `energy_utility_meter_entity` | NOT DONE via API | entity selector rejects an empty value; unused now that the import statistic id is set |
