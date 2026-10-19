# PLANNING: EC bill check rebuilt from SmartHub hourly statistics (kWh + $ divergence)

**Card:** EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1, Step 2 (Step 1 is a config action, see §0).
**Arc:** `ARC_energy_coordinator_resilience.md`.
**Tier:** 2 (two framing-disjoint build reviews + live validation). Justification in §9.
**Status:** DRAFT, needs one adversarial plan review before build dispatch (Tier-2 plan-review rule).
**Evidence base:** `AUDIT_smarthub_bill_actual_2026_10_18.md` plus the measurement in §2 (run 2026-10-19 07:07 UTC,
read-only, scratch scripts in `.claude/scratch/billprobe/`).

---

## 0. Prerequisite (NOT built in this cycle): Step 1, operator config action

Clear `energy_utility_meter_entity` in the Coordinator Manager EC options. It is read only at EC construction
(`energy.py:609-612`), so a save reloads the parent; do it in a planned restart window (memory
`feedback_parent_entry_reload_watchdog_hazard`, `feedback_no_restart_during_sleep`). Effect on its own:
`utility_meter_divergence` returns None at `energy.py:11573` and the false `utility_divergence_pct: 100.0` disappears.
Step 2 does not depend on Step 1 for correctness (the new source takes precedence, D3), but Step 1 should happen first
so the false 100% stops today.

**Config-first check for Step 2:** no existing setting produces a utility-side kWh or $ figure over the 23rd-start
cycle. The audit's option (c) (SQL-integration sensor) would give kWh only, no TOU pricing, and would still be compared
against EC's to-the-minute cycle accumulator rather than a same-window figure. The operator explicitly chose the DB
path. Code is required.

## 1. Institutional context verified

### 1a. REUSE-or-BUILD per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Recorder statistics read from a coordinator, off the event loop | **REUSE pattern** | `hvac_override.py:19` imports `get_instance as recorder_get_instance`; `hvac_override.py:1889-1893` and `:6466-6472` call `recorder_get_instance(self.hass).async_add_executor_job(<sync recorder fn>, self.hass, ...)` under `try/except Exception`. Same shape here, with `statistics_during_period` |
| `statistics_during_period` API | **REUSE (HA)** | `.venv-ha/.../recorder/statistics.py:2077-2100`: sync function, opens `session_scope(hass=hass, read_only=True)` (`:2091`). Sync + session = must run on the recorder executor. `RecorderInstance.async_add_executor_job` = `loop.run_in_executor(self._db_executor, ...)` (`recorder/core.py:348-352`). Safe as specified; never call it on the loop |
| Pricing an energy slice at the TOU rate for its instant | **REUSE** | `energy_billing.py:455-472` (counter mode, "TOU BY REFERENCE"): `self._tou.get_effective_import_rate(slice_dt)` for import, `self._tou.get_export_rate(slice_dt)` for export. `energy_tou.py:534-545`. Price each hour with the hour-start local datetime through the SAME `self._tou` instance; no rate caching |
| Bill-cycle start | **REUSE** | `CostTracker._get_cycle_start(now)` `energy_billing.py:533-544` (cycle day from `CONF_ENERGY_BILL_CYCLE_DAY`, `energy_const.py:274`); public wrapper `EnergyCoordinator.get_billing_cycle_start` `energy.py:11622` |
| EC-side kWh/$ over an arbitrary date range | **REUSE** | `database.get_energy_daily_for_cycle(cycle_start, cycle_end_exclusive)` `database.py:4940-4975` (sums `import_kwh`, `export_kwh`, `import_cost`, `export_credit`, `net_cost` over `date >= ? AND date < ?`); already used by `_restore_cycle_from_db` `energy.py:1528-1538` |
| Publishing surface | **REUSE** | `EnergyCoordinator.utility_meter_divergence` `energy.py:11562-11615` (producer) and `EnergyPredictedBillSensor.extra_state_attributes` `sensor.py:11120-11126` (sole copier). Extend both; no new entity |
| Periodic driver | **REUSE** | `_async_decision_cycle` `energy.py:6352`, timer `energy.py:1182-1186`. Gate the refresh inside it by elapsed time; no new timer |
| Statistic-id config fields | **NEW** (2 options fields) | grep `STATISTIC_ID\|statistic_id` in `const.py`, `config_flow.py`, `domain_coordinators/energy_const.py`: none. The existing `CONF_ENERGY_UTILITY_METER_ENTITY` uses an `EntitySelector(domain="sensor", device_class="energy")` (`config_flow.py:7283-7288`); `smarthub:*` ids are external statistics with no entity, so it cannot hold them |
| Refresh interval / stale threshold constants | **NEW** module constants | grep `UTILITY_` in `energy_const.py`: only `CONF_ENERGY_UTILITY_METER_ENTITY` (`:1431`) |
| External-statistics reader in URA | **NEW** (the audit's grep for `statistics_during_period\|get_last_statistics\|async_add_external` returned nothing; re-ran 2026-10-19, still nothing) | First external-statistics consumer |

### 1b. Prior docs / memory / design docs

- `AUDIT_smarthub_bill_actual_2026_10_18.md` (full): monthly entity dead since 06-02; hourly/daily external stats
  alive; sole consumer is the divergence attribute; `cycles_aligned` has no consumer; audit recommended parking (b).
  The operator overrode the park on 2026-10-18 ("I want it done"); this plan is the simplest form of (b).
- `PLANNING_ec_billing_emporia_counters.md` (REV 4 header, §0): records three PEC bills in kWh (06-24..07-25 2,778;
  07-25..08-25 2,752; 08-25..09-24 3,564). Used as external ground truth in §2.
- `PLANNING_UTILITY_METER_INTEGRATION.md:126`: "B-Lite: divergence attributes only. No automatic source switching."
  This plan stays inside B-Lite.
- `ARC_energy_coordinator_resilience.md`: card sits in this arc; no other arc deliverable reads the divergence.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md`: no utility-meter / SmartHub section (grep `smarthub|utility meter`
  empty). D5 adds one.
- Memory: `project_battery_soc_envoy_not_span`, `feedback_measure_before_build`, `feedback_marginal_benefit_pushback`,
  `project_envoy_boot_incident_2026_06_12` (do NOT add `recorder` to `after_dependencies`/`dependencies`; see D1).

### 1c. Code surveyed end-to-end
`energy.py:600-620, 1175-1190, 1525-1540, 11562-11640`; `energy_billing.py:440-560, 600-705, 770-800`;
`energy_tou.py:40-135, 470-560`; `sensor.py:11070-11135`; `database.py:4864-4975`; `config_flow.py:7270-7295`;
`energy_const.py:2555-2575` (`EC_CONSTRUCTION_ENTITY_KEYS`); `hvac_override.py:1880-1900, 6460-6475`;
`manifest.json` (deps: http, frontend, logbook; no recorder).

### 1d. Consumer enumeration (the tier question)
`git grep "utility_meter_divergence|utility_divergence|utility_kwh"` outside docs: `energy.py:11562` (producer) and
`sensor.py:11121-11126` (attribute copy). Outside the repo: `/config/.storage/lovelace.ura_v6` displays the attribute.
`cycles_aligned`: no consumer. **No decision path reads any of it.** Display/diagnostic only, so Tier 2 holds.

## 2. Measure-before-build (D0, done): go/no-go numbers

Statistic ids (`statistics_meta`, all `source=smarthub`, `kWh`, `has_sum=1`):

| meta id | statistic_id | role |
|---|---|---|
| 4699 | `smarthub:smarthub_energy_sensor_<ACCT>_<LOC>` | hourly grid IMPORT |
| 6396 | `smarthub:smarthub_energy_return_sensor_<ACCT>_<LOC>` | hourly grid EXPORT |
| 4700 / 6397 | `..._daily_...` | daily (not used) |

Cadence and lag:
- 8,236 hourly rows on 4699; **0 gaps > 1 h** since 2026-08-23. Per-hour `state` never negative (0.0-23.92), so 4699
  is import, not net. `sum(state)` over a window equals `sum` delta over it (3669.45 = 3669.45), so HA's
  `"change"` type is equivalent.
- **Ingestion is once a day, not per poll:** 23-24 rows land together at ~15:48-17:02 UTC, carrying the previous
  local day (05:00 to 04:00 UTC). Newest hour at write time is about 13-14 h old. Just before the next import it is
  about 38 h old. At probe time (10-19 07:07 UTC) the newest row was 10-18 03:00 UTC, **28 h old**. So the card's
  "~16 h" is a best case, and the stale threshold must sit above 38 h.

Reconciliation with external ground truth (PEC bills, kWh, from the counters plan). Summing hourly import over the
local dates **inclusive of both read days**:

| PEC bill | PEC kWh | SmartHub hourly | delta |
|---|---|---|---|
| 06-24..07-25 | 2,778 | 2,758.2 | -0.7% |
| 07-25..08-25 | 2,752 | 2,783.3 | +1.1% |
| 08-25..09-24 | 3,564 | 3,573.6 | +0.3% |

(End-exclusive windows give -3.2%, -2.4%, -1.7%. PEC appears to bill read-day to read-day inclusive.)
**GO: the hourly series reproduces the billed kWh within about 1%.**

Priced with the live TOU table (`/config/universal_room_automation/tou_rates.json` equals the built-in
`PEC_TOU_RATES`; effective import = base + delivery 0.022546 + transmission 0.01993):

| Window (EC cycle, local) | SmartHub import kWh / $ | export kWh / $ | SmartHub net $ (variable) | EC `energy_daily` same dates: import kWh / net $ |
|---|---|---|---|---|
| 08-23..09-22 (complete) | 3,669.4 / 324.83 | 249.7 / 29.70 | **295.13** | 3,428.4 / 199.40 |
| 09-23..10-17 (to last complete day) | 2,204.1 / 195.46 | 236.7 / 12.89 | **182.57** | 2,109.0 / 137.35 |

Per-day comparison in EC's counter-mode era (10-09..10-17): totals SmartHub 632.0 kWh / $55.7 vs EC 678.3 kWh / $60.4.
Clean days (10-10, 10-11, 10-13, 10-14, 10-17) agree within 0-2% in kWh and $. The gap comes from three EC-side days:
10-12 import 144.5 vs 102.0; 10-15 and 10-16 export 63.6/85.3 vs 33.7/39.4.

**Findings this measurement surfaced (out of scope; for the orchestrator to card):**
- **F1:** EC `energy_daily.import_cost / import_kwh` is below the minimum possible effective rate (0.0860 $/kWh) on
  28 of 57 days since 08-23, all before 2026-10-09 (e.g. cycle 08-23..09-22: 0.0658). Since counter mode
  (10-09) it is 0.086-0.097. EC's pre-10-09 history under-prices. The current cycle's first live $ divergence will read about +25%, and
  most of that comes from EC's history, not from the utility.
- **F2:** EC daily outliers vs utility on 10-12 (import +42 kWh) and 10-15/10-16 (export about 2x).
- **F3 (operator question):** PEC bill windows run 24th/25th to 24th/25th, read day inclusive. `energy_bill_cycle_day`
  is 23. Is 23 right?

These findings are why the feature is worth building. Once the false 100% is gone, a same-window per-cycle
comparison catches real EC billing defects.

## 3. Falsifiable invariants

- **INV-1 (same window):** whenever the predicted-bill sensor publishes a divergence number, the utility total and the EC
  total are sums over the **identical set of local dates** `[window_start, window_end)`. `window_end` is the day after
  the newest local day the utility series covers completely. When that set is empty, or either source is
  unavailable, **no divergence number is published**: the keys are absent or None, never 0.0 and never 100.0. Break it
  with an early-cycle day (cycle day 23, local date 23rd/24th, newest utility day = 22nd), a mid-day partial import, a
  DST day (23/25 rows), or a recorder exception.
- **INV-2 (loop safety + cadence):** no recorder or URA-DB query for this feature runs on the event loop, and at most
  one statistics query runs per `UTILITY_STATS_REFRESH_MIN` (a concurrent decision cycle cannot start a second one).
  Break it with two overlapping decision cycles, a restart, or a slow executor.

## 4. Producer and consumer checks

**Producer: utility kWh/$.** Hourly `change` for the two configured statistic ids. Dependency health: alive and
gap-free (§2); the monthly sensor is dead (audit). Arithmetic: import $ = Σ kWh_h × `get_effective_import_rate(h_local)`;
export $ = Σ kWh_h × `get_export_rate(h_local)`, where `h_local` is the hour start converted to local time with
`dt_util.as_local`. The same `self._tou` instance and the same functions as counter mode (`energy_billing.py:458,466`) mean both sides
use the same price book. This compares *usage priced identically*, not PEC's invoice. Fixed `service_availability`
($32.50) is excluded from the divergence on both sides and shown only in `utility_bill_estimate` for a completed
cycle. External ground truth: PEC kWh bills (§2), within about 1%.

**Producer: EC side.** `get_energy_daily_for_cycle(window_start, window_end)` over the same dates (`import_kwh`,
`export_kwh`, `net_cost`). Dependency health: F1/F2 above. The EC side is the thing being audited, so health problems
show up as divergence, which is intended.

**Consumers.** §1d: `sensor.py:11121-11126` (display) and the `lovelace.ura_v6` card (display). None are
trust-decisions. Legacy keys `utility_kwh`, `envoy_kwh`, `utility_divergence_pct`, and `prediction_source` keep their names so the dashboard
keeps rendering. Their values become like-for-like (D3).

## 5. Emission / decision-site enumeration

`git grep -n "utility_meter_divergence\|_utility_meter_entity\|CONF_ENERGY_UTILITY_METER_ENTITY"`:
`energy.py:609-612` (read), `energy.py:11562-11615` (producer), `sensor.py:11121` (copy), `config_flow.py:6079, 7283-7288`
(options field), `energy_const.py:1431, 2586` (constant; membership in `EC_CONSTRUCTION_ENTITY_KEYS`). All divergence
publication goes through the single producer property. The builder makes the new branch there and adds no second
publisher. The two new CONF keys must be added at every site where the existing key appears (config_flow schema +
`_get_current`, `EC_CONSTRUCTION_ENTITY_KEYS` because they are read at construction, strings/translations).

## 6. Deliverables

### D1: Hourly utility-statistics refresh (producer)
New `async def _async_refresh_utility_stats(self, now)` on `EnergyCoordinator`, called from `_async_decision_cycle`.
It returns immediately unless both statistic ids are configured AND `now - self._utility_stats_last_run >=
UTILITY_STATS_REFRESH_MIN`. An in-flight flag (`self._utility_stats_inflight`) gives single-flight (INV-2). The stamp is
set **before** the first `await` so a raising query does not retry every tick. It queries
`recorder_get_instance(hass).async_add_executor_job(statistics_during_period, hass, start_utc, None, {imp_id, exp_id},
"hour", None, {"change"})` with `start_utc` = local midnight of the **previous** cycle start (covers last-completed +
current cycle, about 1,500 rows per id). The call sits under `try/except Exception` and logs at debug. On failure the
cached result is kept and `utility_stats_error` is set. Pure helper `price_hourly_utility_rows(rows_imp, rows_exp, tou,
tz) -> dict[local_date, {imp_kwh, imp_cost, exp_kwh, exp_credit, hours}]` in `energy_billing.py`, unit-testable with no
HA. If the recorder is not loaded (`"recorder" not in hass.config.components`), skip silently. Do **not** add
`recorder` to `manifest.json` deps (boot-incident memory). `hvac_override` already relies on it being loaded.

**Acceptance criteria**
- **Verify:** with ids blank, `statistics_during_period` is never called (mock asserts 0 calls). This is the kill switch.
- **Verify:** 3 decision cycles inside one interval cause 1 executor call. 2 overlapping invocations cause 1 call.
- **Verify:** the pricing helper on a fixture of 24 summer hours of 1 kWh each gives import $ = 17×(0.043481+0.042476)
  + 3×(0.093169+0.042476) + 4×(0.161843+0.042476) to 1e-6. A base-rate-only bug would give a total lower by
  24×0.042476 = $1.019, so the fixture discriminates.
- **Verify:** a DST fall-back fixture (25 rows on one local date) still counts that date complete. A spring-forward
  fixture (23 rows) also counts it complete.
- **Test:** `test_utility_stats_disabled_when_ids_blank`, `test_utility_stats_single_flight_and_interval`,
  `test_price_hourly_utility_rows_effective_rate`, `test_price_hourly_utility_rows_dst_days`,
  `test_utility_stats_recorder_exception_keeps_cache`. Wire-in anchor: `test_decision_cycle_calls_utility_refresh`
  must fail if the call in `_async_decision_cycle` is deleted.
- **Live:** debug log or attribute `utility_stats_refreshed_at` advances at most once per hour. No `Detected blocking
  call` warnings mention `statistics` in the HA log after restart.

### D2: Same-window comparison (current cycle + last completed cycle)
After pricing, `window_end` = day after the newest local date whose last row covers local 23:00. For the current cycle,
`window_start = cycle_start` and the window is `[cycle_start, min(window_end, today))`. Await
`db.get_energy_daily_for_cycle(window_start, window_end)` (existing DAO, read pool), so the EC side covers exactly the
same dates. Also compute the **last completed cycle** `[prev_cycle_start, cycle_start)` once the utility series covers
it completely. Until then that block is absent. The result is a cached dict:
`window_start, window_end, utility_days, ec_days, utility_import_kwh, utility_export_kwh, utility_import_cost,
utility_export_credit, utility_net_cost, ec_import_kwh, ec_export_kwh, ec_net_cost, divergence_kwh, divergence_kwh_pct,
divergence_cost, divergence_cost_pct, newest_hour, data_age_h, stale` plus `last_cycle: {...same..., utility_bill_estimate
= utility_net_cost + service_availability}`. Percent reference: `max(|utility|, |ec|, 1.0)`, matching the existing
`energy.py:11606`. The sign convention is utility minus EC: positive means EC under-counts.

**Acceptance criteria**
- **Verify (INV-1):** a fixture where the newest complete utility day is before `cycle_start` (e.g. today = 24th, cycle day
  23, utility through the 22nd) publishes no divergence keys or None, and does NOT publish 0 or 100.
- **Verify (INV-1):** `utility_days == ec_days` whenever divergence is published. If `ec_days < utility_days` (missing
  `energy_daily` rows), publish anyway with `ec_days` shown. Test both.
- **Verify:** a partial last day (rows to 15:00 local) is excluded from the window.
- **Test:** `test_utility_window_empty_publishes_no_divergence`, `test_utility_window_matches_ec_dates`,
  `test_utility_partial_day_excluded`, `test_last_cycle_absent_until_complete`.
- **Live (discriminating):** `last_cycle.utility_import_kwh` = **3669.4 ± 0.5** and `last_cycle.utility_net_cost` =
  **295.13 ± 0.5**. A wrong-window build (end-exclusive or day-23 off-by-one) or a base-rate build (~$139.27 net)
  cannot produce these values. `last_cycle.ec_import_kwh` = **3428.4** (equals `SELECT SUM(import_kwh) FROM energy_daily
  WHERE date >= '2026-08-23' AND date < '2026-09-23'`). Current-cycle `utility_import_kwh` ≥ **2204.1** (09-23..10-17)
  and grows by one day per daily import.

### D3: Publish on the predicted-bill sensor (consumer surface)
`utility_meter_divergence` (`energy.py:11562`) returns the D2 cache when statistic ids are configured; otherwise the
existing entity branch runs unchanged. Precedence: statistics win, so there are no two publishers. `sensor.py:11120-11126` copies
the new keys. Legacy keys are kept with like-for-like values: `utility_kwh` = current-window utility import, `envoy_kwh`
= current-window EC import (name kept for the dashboard; documented as "EC billed import"), `utility_divergence_pct` =
`divergence_kwh_pct`, `prediction_source` unchanged. New keys: `utility_cost`, `ec_cost`, `utility_divergence_cost`,
`utility_divergence_cost_pct`, `utility_window`, `utility_data_age_h`, `utility_stale`, `utility_source: "statistics"`,
`utility_last_cycle` (dict). Attribute payload stays small (no per-day arrays).

**Acceptance criteria**
- **Verify:** with ids configured and a legacy entity also set, the published values come from statistics
  (`utility_source == "statistics"`).
- **Verify:** byte-identical attributes on the no-op path. With ids blank, the attribute dict equals the pre-change
  output for the same fixture (snapshot test).
- **Test:** `test_predicted_bill_attrs_statistics_precedence`, `test_predicted_bill_attrs_unchanged_when_ids_blank`.
- **Live:** `sensor.ura_energy_coordinator_predicted_bill` has `utility_source: statistics`, and `utility_divergence_pct` is
  NOT 100.0. With the current EC history (F1), `utility_divergence_cost_pct` for the current cycle is roughly +20-30%.
  Read that as an EC artifact, not a regression. Recorded in README, not "fixed".

### D4: Config fields (two)
`CONF_ENERGY_UTILITY_IMPORT_STATISTIC_ID`, `CONF_ENERGY_UTILITY_EXPORT_STATISTIC_ID` (`energy_const.py`, default `""`).
Add them to the EC options step next to the utility meter field as `TextSelector`. Labels follow the style guide:
"Utility import statistic" / "Utility export statistic". Help text: "Long-term statistic id from your utility integration, e.g.
smarthub:... Leave blank to turn the bill check off." Read at construction, so add them to `EC_CONSTRUCTION_ENTITY_KEYS`.
Validation: if non-blank, the value must contain `:` (external-statistic form). Otherwise show a form error, not a
silent store. Export blank and import set is allowed (export treated as 0, `utility_export_kwh` absent).

**Acceptance criteria**
- **Verify:** options round-trip preserves both values; blank clears them.
- **Test:** `test_options_utility_statistic_ids_roundtrip`, `test_options_utility_statistic_id_requires_colon`.
- **Live:** operator sets the two ids (values in §2) in the same restart window as Step 1; after restart D2's Live
  numbers appear within one refresh interval of the first decision cycle.

### D5: Docs
Add a "Utility bill check" section to `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md`: source, daily-import lag (13-38 h),
same-window rule, what the divergence means (usage priced with URA's price book; not the PEC invoice), the F1 caveat.
README for the release with a validated table per the README write-back rule.

## 7. Numbers get knobs

| Number | Name | Rung | Why |
|---|---|---|---|
| 60 min | `UTILITY_STATS_REFRESH_MIN` (`energy_const.py`) | module const | Data lands once a day; hourly is ample and bounds recorder load. Not an operator policy |
| 48 h | `UTILITY_STATS_STALE_H` (`energy_const.py`) | module const | Normal max age is about 38 h (§2). 48 h flags a missed daily import. Display flag only |
| local 23:00 row present | `UTILITY_DAY_COMPLETE_LAST_HOUR = 23` | module const | Day-complete rule; DST-safe (D1 test) |
| previous cycle start | (derived from `energy_bill_cycle_day`) | existing config | Reuses the cycle knob |
| statistic ids | D4 fields | config/options flow | Per deployment. **Blank = kill switch** (feature off, legacy path) |

## 8. Non-goals
- No change to `predicted_bill` itself, `cost_this_cycle`, `energy_daily`, or any accrual path. No calibration from utility
  data (B3 stays unbuilt; `PLANNING_UTILITY_METER_INTEGRATION.md:126` B-Lite holds).
- No fix for F1/F2 (EC-side billing defects). They get their own cards.
- No anomaly / NM trip-wire on divergence. It is a candidate for a follow-up card once F1 is understood; today it would
  fire on EC history.
- No PEC invoice reproduction (taxes, PCRF, rider changes); fixed charge shown only in `utility_bill_estimate`.
- No auto-discovery of statistic ids; no SQL integration; no change to the smarthub integration (upstream issue text is
  in the audit §4, posting needs operator yes).
- No deletion of the legacy entity branch this cycle. After live validation, list it as a DELETE candidate in the
  post-ship supersession audit (it is buggy by design: month-start vs 23rd, `cycles_aligned` always False).

## 9. Tier
**Tier 2.** Display/diagnostic attributes only. §1d proves no decision consumer. There are no schema changes and no new
DB writes (reads go through the existing read-pool DAO), and no shared primitive changes (TOU engine called read-only, as
counter mode does). It is not Tier 2-DB: none of the triggers fire. The regression risk lies in event-loop blocking (INV-2) and
the options flow, so the two build reviews are A = correctness/window arithmetic/DST/INV-1, B = async/executor/
single-flight/restart/options round-trip. Elevate to Tier 2-DB if the builder finds it must touch `database.py`.

## 10. Open questions for the operator
1. **F3:** PEC bills read-day to read-day (24th/25th inclusive). Should `energy_bill_cycle_day` stay 23? (Config-only.)
2. OK to put the two `smarthub:` statistic ids into EC options in the Step-1 restart window?
3. F1/F2 cards: investigate EC's pre-10-09 under-pricing and the 10-12 / 10-15 / 10-16 daily outliers (recommended;
   they explain most of the divergence this feature will show).

## Plan review 2026-10-19 (Tier-2 adversarial)

**Verdict: FIX-PLAN** (one HIGH, small edits; then SHIP-TO-BUILD without re-review).

Verified: `statistics_during_period` signature (`recorder/statistics.py:2077-2085`), sync + `session_scope` so it must go through the recorder executor; `"change"` = per-row `sum - prev_sum` with the first row's prev taken from `_statistics_at_time(start_time)` (`:1907-1959`), so the first hour of the window is correct and `has_sum=1` ids are the right column choice. `_get_cycle_start` (`energy_billing.py:533-544`) is knob-driven local date. No URA consumer of the divergence keys beyond `sensor.py` (the frontend bundle, `dashboard/`, `dashboard-v3/_v3archive` reference `predicted_bill` only; none reads `utility_*`). No decision path. Tier 2 holds.

- **HIGH H1 — the refresh can delay/skip EC decisions.** D1 says "called from `_async_decision_cycle`" and awaits the executor. `_async_decision_cycle` holds `_cycle_in_flight=True` across `_decision_cycle_body` (`energy.py:6352-6375`) and a TOU-boundary tick arriving meanwhile is *skipped*, not queued. A slow recorder executor (purge, stats compile, the DB being a Samba-adjacent SQLite) would drop a boundary tick: cost-impacting. Fix: launch the refresh as a tracked background task (`entry.async_create_background_task` / tracked + cancelled on unload) guarded by `_utility_stats_inflight`; the decision cycle never awaits it. Add test: refresh blocked on an un-set Event, decision cycle still completes and a second cycle runs.
- **MED M1 — Live numbers are tied to cycle_day=23.** Open question 1 (F3) may change the knob in the very restart window D4 uses. State that D2 Live values hold only if `energy_bill_cycle_day` stays 23; otherwise re-derive with the probe script before validation. Also specify `prev_cycle_start = _get_cycle_start(cycle_start - 1 day)` (no hand-rolled month math).
- **MED M2 — divergence self-explanation.** Add `ec_underpriced_days` (count of window days where EC `import_cost/import_kwh` < min effective import rate) to the published dict, so a +25–32% cost divergence visibly attributes to F1 rather than relying on README prose.
- **LOW L1 — INV-1 contradicts D2.** INV-1 says `utility_days == ec_days` whenever published; D2 publishes when `ec_days < utility_days`. Reword INV-1 to "identical date window; `ec_days` reported".
- **LOW L2 — first-run stamp.** Initialise `_utility_stats_last_run = None` so the first tick runs; with stamp-before-await a recorder-not-ready boot delays data one interval — say so in D4 Live.
- **LOW L3 — unload.** Cancel the background task on EC teardown; test it.
