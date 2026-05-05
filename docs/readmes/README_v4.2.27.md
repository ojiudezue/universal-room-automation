# v4.2.27 — Bug A (previous_seen wipe) + 5 stub prediction sensors restored

**Date:** 2026-05-05
**Type:** Hotfix — sensor reconciliation cycle findings (audit May 5 2026)

## Summary

Two correctness bugs found by audit. Both are surgical, low-risk fixes that produce immediately-visible improvements for users.

1. **Bug A (`person_coordinator.py`)** — anyone who left home for >1 update cycle was showing `previous_seen=unknown` and `previous_location=Away` instead of the actual last room/timestamp. The data was being clobbered every cycle while in steady-state away. Fixed.

2. **5 stub prediction sensors (`aggregation.py`)** — `predicted_energy_week`, `predicted_energy_month`, `predicted_cost_today`, `predicted_cost_week`, `predicted_cost_month` were all permanently `unknown` because their classes were missing `async_update()`. Bug Class #29 (stub sensor implementation). Fixed; cost variants are sign-aware on net energy (positive kWh × import rate, negative kWh × export rate).

3. **Bonus: dt_util.now() migration** — converted 7 `datetime.now()` (timezone-naive) calls in `aggregation.py` to `dt_util.now()` (timezone-aware, HA convention). Affects the 6 prediction sensors plus alert debouncing and light-flash cooldown logic. Bug Class #21 prevention.

## Changes

### `custom_components/universal_room_automation/person_coordinator.py`

Bug A fix in two fallback branches (lines 309-353 and 335-367):

- Added `old_previous_location = old_data.get("previous_location", "unknown")` read.
- Added `was_real_room = old_location and old_location not in ("away", "home", "unknown", "")` transition detector.
- On real-room → away/home transition, capture `new_previous_location = old_location` and `new_previous_location_time = now`.
- Otherwise, preserve `old_previous_location` and `old_previous_location_time` from `old_data`.
- Both Bermuda-no-area and no-Bermuda-sensor branches use identical logic.

Net effect: a person away for hours now correctly shows their last indoor room and last sighting time, not "Away" / "unknown".

### `custom_components/universal_room_automation/aggregation.py`

Five stub classes restored to functional state:
- `PredictedEnergyWeekSensor` — adds `async_update()` calling `db.predict_energy("week", forecast_temp)`. 60-min cache TTL.
- `PredictedEnergyMonthSensor` — adds `async_update()` calling `db.predict_energy("month", ...)`. 6-hour cache TTL. Plus missing `_cache_time` initialization.
- `PredictedCostTodaySensor` — adds `async_update()` and `_cache_time` init. 15-min TTL. Sign-aware cost.
- `PredictedCostWeekSensor` — same shape. 60-min TTL.
- `PredictedCostMonthSensor` — same shape. 6-hour TTL.

Cost variants use static `CONF_ELECTRICITY_RATE + CONF_DELIVERY_RATE` for now. Attributes flag `rate_source: "static_config"` to make TOU-aware migration debt visible. Migration to EC's `current_effective_rate` is filed in BACKLOG (E) for v4.5.x.

Plus: 7 `datetime.now()` → `dt_util.now()` conversions throughout the file (6 prediction sensors plus 2 collateral fixes in `_process_alerts` debounce and `_flash_light` cooldown).

### `docs/BACKLOG.md`

New "Sensor Reconciliation Cycle (audit findings, May 5 2026)" section documenting:
- A: previous_seen bug (fixed in this hotfix)
- B: kid weekday-afternoon `likely_next_room=unknown` is correct behavior (not a bug; B6 enhancement opens UX work)
- C: Frigate face DB undersized (user handling; not URA code)
- D: 5 stub energy/cost sensors (fixed in this hotfix)
- E: legacy fixed-cost-rate vs EC TOU rate reconciliation (architectural debt for v5.0)

Plus B6 (away_typical display + cell staleness) and B7 (regime-shift detection, sharing AnomalyDetector infrastructure) plan entries paired into v4.5.0 "Routine Awareness".

Plus B5 (Appliance Scheduler) reference to the new planning doc.

## What we parked

| ID | Severity | Reason |
|---|---|---|
| Bug C | MEDIUM | Frigate face DB sample size — user-side config, not URA code |
| Energy room sensors (5306 kWh "today") | HIGH | Will ship as v4.2.28 separately. Audit at `docs/reviews/v4.2.27_energy_audit_findings.md`. Defects 1+2: in-memory baseline lost on restart; possible tz-mismatch in midnight detection. |
| Envoy bill discrepancy | HIGH | Stated assumptions for user referee at `docs/reviews/v4.2.27_envoy_bill_assumptions.md`. Likely cause: URA reading lifetime gross vs net consumption, OR Envoy is data-down while URA reports "online" (separate availability defect). User to verify direction of discrepancy. |
| EC `envoy_status: online` while sensors unavailable | MEDIUM | Filed for follow-up. Availability check tracks integration loaded-state, not data freshness. |

## Tests

Pre-existing test environment failures persist (Python 3.9 vs 3.10+ syntax in test files); not regressed by this change. AST verification confirms all 6 prediction sensor classes have `async_update` and `_cache_time` initialized.

## Code review

Tier 1 adversarial review at `docs/reviews/code-review/v4.2.27_bug_a_energy_stubs.md`:
- 2 reviewer "CRITICAL" flags evaluated: both **rejected as false positives** with evidence.
  - `datetime.now()` flag was correct on the convention but overstated severity (existing working sensor used same pattern). Fixed anyway via dt_util migration.
  - `_attr_should_poll = False` flag was wrong — only one specific class in the file sets it; default is True; existing prediction sensor demonstrably polls.
- HIGH and MEDIUM findings reviewed and accepted as not blocking.
- Verdict: ready for deploy.

## Related planning docs

- `docs/planning/PLANNING_v4.4.x_APPLIANCE_SCHEDULER.md` — B5 plan for cost-deferral via LG ThinQ + Rainbird forecast-aware skip. Provider plugin pattern, restart-survivable, reload-resilient.
- `docs/reviews/v4.2.27_energy_audit_findings.md` — full root-cause analysis driving v4.2.28 hotfix.
- `docs/reviews/v4.2.27_envoy_bill_assumptions.md` — user-facing assumptions document for refereeing the Envoy bill discrepancy.

## Deploy notes

No HA restart strictly required for Bug A (person_coordinator runs continuously; new code path applies on next update cycle). Prediction sensor restoration becomes visible on the next polling cycle (~30s) after deploy.

## Next planned ship

- **v4.2.28** — energy room sensor fix (room `_energy_baselines_today` persistence + tz consistency in midnight detection). Separate hotfix to keep blast radius narrow.
- **v4.5.0** — Routine Awareness (B6 + B7 paired) and/or Energy Architecture Alignment refactor.
