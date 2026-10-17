# EC Stage B+C — Tier-3 Review A (local correctness)

Branch `feature/ec-stage-b` @ 43b3a4845, diff base `pre-build-ec-stage-b` (88dd37aa0, three-dot).
Spec: `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.5 (§6 B+C, §7, §12, §16).
Lane: per-site arithmetic / clamps / helpers / None / time zones. Completeness of the
invariant surface is Review D's lane and is not covered here.

Targeted suites: `test_ec_stage_b_classification`, `test_ec_stage_b_preonset_precharge`,
`test_ec_stage_c_hourly_outlook`, `test_ec_stage_b_goldens`, `test_inclement_alert_classifier`
→ 1695 passed. One scratch probe (deleted; tree clean) reproduced A-HIGH-1.

## Findings

| ID | SEV | Site | Finding | Class |
|---|---|---|---|---|
| A-HIGH-1 | HIGH | `energy_battery.py:6291-6327` (pre-onset emit) vs `_result` `:6985-7010` | Under **bounded-degraded** telemetry (LKG SOC, fresh decision) `_precharge_refused_on_blind` allows the pre-charge, but `_degraded_telemetry_source` is still set when `_result` runs. `_result`'s D-MED-1 guard then suppresses the CFG `switch.turn_on` while the switch reads off. Probe (the `test_preonset_degraded_fresh_decision_control` scenario): reason `Inclement pre-onset … pre-charging (SOC 40.0%) (degraded telemetry: lkg)`, returned `charge_from_grid=True`, actions `[number.set_value]` only (**no turn_on**), latch `{'wsw': 'engaged'}`, `_tick_grid_buy` set, so the NM says "started grid-charging". The storm full-hold path avoids this by clearing the source around `_result` (`:6246-6270`). Plan §6 D-B6 step 3 (line 390) said not to copy that variant on the premise that it only changes the suffix. That premise is wrong: it also gates the turn_on. The positive-control test asserts only the reason prefix, so it is a hollow anchor. Fix: either (a) clear/restore `_degraded_telemetry_source` around the pre-onset `_result`, as the storm path does, and assert a `switch.turn_on` action in the control test; or (b) if the operator does not want a pre-onset buy under degraded telemetry, refuse it explicitly (no latch, no stamp, no NM). Either way, correct the plan line 390 premise. | #62 hollow anchor; #53 (gate computed, effect not consumed); plan premise error |
| A-MED-1 | MEDIUM | `weather_manager.py` `_refresh_hourly_locked` + `hourly_outlook` (health filter) → `_check_provider_health:368-392` | The hourly refresh and outlook drop a provider whose health is `STALE`. `STALE` = weather entity `last_changed` older than `weather_staleness_max_hours` (default 6). `last_changed` advances only when the **condition string** changes, not when attributes do. A provider that has read `cloudy` (or `snowy`) for more than 6 h is never hourly-fetched, and its rows are refused even though `get_forecasts` would return fresh data. Repro: overnight bottom-rate window, every provider steady on `cloudy` since 20:00, Winter Storm Watch onset 09:00 → at 03:00 all providers are `STALE`, `hourly_outlook` returns None, and `forecast_confirms` returns False. Result: no watch corroboration, no zone buy, no confirmed-watch prepare floor. It fails safe (raise-only), but it disables D-C2 exactly in long steady pre-storm and storm conditions. The hourly path already has its own freshness bound (`FORECAST_STALE_MIN` on `fetched_at`). Fix: on the hourly path, filter only `UNAVAILABLE`. Add a test with `last_changed` older than 6 h. | Stale-data source (#7) — reused gate with the wrong semantics for the new consumer |
| A-LOW-1 | LOW | `energy_battery.py` `_grid_buy_stamp` (zone/polygon record pick) | The zone leg names the first non-polygon `precharge_eligible` hold record, not the record that is also forecast-confirmed (the one `_zone_buy_confirmed` used). The polygon leg names the first `polygon_local` record, not the one inside its cap window. With two such records, the NM can name the wrong alert and print `forecast_confirmed=True` for an unconfirmed one. The episode key `(leg, alert_id)` also depends on `hold_alerts` order. That order is the stable sort of feed ∪ memory; memory order is first-admission order. When the feed changes, the key can flip and send a second NM. Fix: pick the record using the same predicate as the gate (eligible ∧ id ∈ confirmed; polygon ∧ in window). Observability only. | #63 concept split (eligible ≠ eligible∧confirmed) |
| A-LOW-2 | LOW | `inclement.py` `alert_id` | Duplicates `energy_outage_ledger.alert_key` byte-for-byte. The docstring says "same rule" but the code is copied (NEW), not imported (REUSED). The keys will drift if either copy changes. Import `alert_key` instead, or make one call the other. | Prior-art reuse miss |
| A-LOW-3 | LOW | `weather_manager.py` `_fetch_provider_hourly` | The precipitation unit only converts `in`/`inch`/`inches`. HA also allows `cm`, which would pass through 10x small (fails toward not confirming). Temperature `"C" in t_unit` is fine for °C/°F. | Unit handling |
| A-LOW-4 | LOW | `energy.py` `_storm_guard_entity` | The cached entity_id is never invalidated. If the switch is renamed or removed after the first resolve, the trip-wire goes inert until restart. Display/notice only. | — |
| A-INFO-1 | INFO | `energy_const.INCLEMENT_FORECAST_FAMILY` | Wind Chill Warning/Watch are in the `freeze` family, which tests **air** min temp ≤ 28 °F. A wind-chill product at air temp 30 °F (wind chill −5 °F) will not confirm, so no buy. Raise-only and spec-defined; the operator may want an apparent-temp leg later. | — |
| A-INFO-2 | INFO | `update_alert_memory` | A healthy **empty** feed keeps memory entries (rule 3 only fires on a non-empty feed), so an NWS early cancellation that leaves the feed empty keeps the hold to `end` (≤ Ends or start+48 h). This is plan-intended (§9 mutation "clear memory on an empty feed" must go RED). Noted so the operator knows the trade-off. | — |

## Cleared (holds because …)

- **match_product**: code row and name row are found independently (`row[0] == code`, upper-cased; `row[1].casefold() == event.casefold()`). The code row wins a disagreement. Drift cases: code row ≠ name row → mismatch; name row only, coded with a different code → mismatch; name row only, uncoded, alert has a code → observed_code; code row only → mismatch (`code_row is not name_row`, name_row None). This matches the docstring and D-B2. Drift is deduped per boot on `(casefold event, code, kind)`, with a WARNING only for mismatch (`_queue_inclement_drift`).
- **_hazard_window**: `start = Onset or Sent`, `end = Ends or Expires or start+48h`, both through `_parse_dt` (an unparseable value counts as missing; naive is coerced to local, aware is kept). No usable end → `build_record` returns None. Active rule `start ≤ now ≤ end`; start None = no lower bound.
- **Window split / prepare**: pre-onset rows never feed `tier`/`expires_at`. Prepare = non-polygon HOLD with `now < start ≤ now+lead`. Lead 0 means an empty set, which is the kill switch. `expires_at = max(end)` over active HOLD rows. `prepare_start` = min over all prepare rows; `prepare_event`/latch key = the earliest row of the prepare class (plan line 376). `.timestamp()` ordering is safe because every NWS time is aware after `_parse_dt`.
- **INV-6(ii) floor**: `max(reserve, partial, knob)` for warn or confirmed watch, else `max(reserve, partial)`, clamped 0–100. The knob is clamped in the fusion ctor and in `_inclement_config`. `_registered_floor`: full_hold → hold floor; partial → max(hold, pre); allow_discharge → pre or None.
- **Pre-charge gate** (`_apply_prepare`): option ∧ eligible∧confirmed on the same prepare-class row ∧ bottom ∧ SOC known < floor ∧ latch ≠ reached ∧ (engaged ∨ soc+surplus(mins to earliest start) < floor). Surplus failure → 0, which errs toward charging, as the plan says. The latch advances before the full_hold short-circuit (INV-6(viii)).
- **D-B2a full-hold legs**: the option short-circuits first (byte-identical). Zone = bottom ∧ `_zone_buy_confirmed` on the same record. Polygon = `polygon_topup_active` ∧ ¬guard. The guard is read only when the option and the guard toggle are both on. Topup window `[start, min(end, start+60m)]`, gated on `POINT_FEED_POLYGON_EXACT` and cap > 0; the helper swallows exceptions → all False.
- **Forecast confirm / latch**: zone records only (active + prepare). Window `[max(now,start), min(end, start+48h)]`. Latched per ID to its own `end` and pruned when `end < now`. Outlook None → False. Precipitation uses PoP ≥ 50 on hours whose provider carries PoP, else mm ≥ 1.0 (per hour, in `hourly_outlook`). Thresholds: freeze ≤ 28, winter ≤ 32 ∧ precip, convective precip ∨ storm condition (`_STORM_CONDITIONS` REUSED).
- **hourly_outlook stitching**: per-hour first usable provider in rank order (OWM, then Open-Meteo beyond its horizon). Slots are UTC hour-floored and the fetched rows are UTC hour-keyed, so they line up. Per-provider staleness comes from its own `fetched_at`, and a failed refresh keeps the old entry until it ages out. (See A-MED-1 for the health filter.)
- **Storm Guard registry**: exactly one `switch.*` with platform == `enphase_ev` and unique_id ending `_storm_guard`, otherwise None. Empty platform → off. The first readable value only seeds. NM + anomaly fire only on a known non-on → on transition.
- **Grid-buy NM**: one per `(leg, alert_id)`. The first tick after setup seeds. The set is bounded at 256. `_tick_grid_buy` is entry-reset at the top of `determine_mode`.
- **Number**: `InclementPreonsetFloorNumber` overrides `_key_default` (staticmethod resolved via `self`) and `_uid_suffix`/`_label`. It seeds from `{data, options}` clamped 0–100 and writes options only. The key is in both `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS`. `_inclement_config` re-reads it per tick with a clamp. Knob rungs match §7: rung 1 for constants, rung 3 for the slider.
- **D-B4**: `_is_bottom_rate` → `tou.is_bottom_rate(now)` (`rate_rank == 0`), falling back to the `off_peak` literal; it replaces every literal in the hold ladder and `compute_solar_horizon`.

## Verdict

**FIX-REQUIRED**:
1. A-HIGH-1: make the degraded pre-onset path consistent. Either actually turn the charge on (clear/restore the source as the storm path does) or refuse explicitly with no latch, stamp or NM. Strengthen the control test to assert the `switch.turn_on` action (or its absence). Fix the premise in plan line 390.
2. A-MED-1: drop the `STALE` (condition `last_changed`) filter from the hourly path; keep `fetched_at` staleness. Add a test.

Fix the LOWs in the same fix-up pass (1–30 LoC each): A-LOW-1 stamp predicate, A-LOW-2 import `alert_key`, A-LOW-3 `cm`.

## Bug-class frequency

| Class | Count |
|---|---|
| #62 hollow test anchor | 1 |
| #53 computed-but-not-consumed | 1 |
| #7 stale data source / reused gate wrong semantics | 1 |
| #63 coincidental equality / concept split | 1 |
| Prior-art reuse miss | 1 |
| Unit handling | 1 |
