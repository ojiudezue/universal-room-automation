# v4.6.8 — EC TOU Rate Reconciliation + Zone/House Cost Surface

**Date:** 2026-05-18 CDT
**Tier:** Tier 1 (single review)
**Predecessor:** v4.6.7 (anomaly_log NOT NULL relaxation)

## Why

Every cost calculation in URA was reading from static `CONF_ELECTRICITY_RATE`, ignoring the Energy Coordinator's TOU-aware rate that already existed. A handful of house-level sensors had already migrated to EC's `tou_engine` but with a hardcoded `0.1 $/kWh` fallback — silently reporting wrong cost if EC briefly dropped at startup. Zones had no cost sensors at all. The house had no realized-cost sensor pairing the existing `WholeHouseEnergyTodaySensor`.

This cycle wires every cost calculation through one helper that prefers EC's live `current_effective_rate` and falls back cleanly to static config when EC isn't configured.

## Behavior change — read this

Pre-v4.6.8: room-level `electricity_rate` config (per-room override or global default) was **always** the source of truth for cost calculations.

Post-v4.6.8: when Energy Coordinator is configured, **EC's TOU-aware rate wins** over any static rate, including per-room overrides. The static rate becomes a fallback used only when EC is absent. UI labels at all four config-flow entry points have been reworded to say "Fallback Electricity Rate" so the precedence is explicit.

If you have per-room electricity rate overrides set, they will be silently ignored as long as EC is active. To restore the old behavior, disable EC.

## Changes

### D1 — TOU async cleanup
- Deleted dead `TOURateEngine.from_json_file()` sync classmethod (~11 LoC).
- `EnergyCoordinator` now requires a pre-loaded `tou_engine` argument (was previously a noop branch).
- Closes the BACKLOG bug "Energy TOU blocking I/O" — production path has been async via `async_from_json_file` since v4.0.5; removing the dead fallback aligns with `feedback_single_user_no_backcompat`.

### D2 — Unified rate helper
New `_get_effective_rate_kwh(hass, *, room_entry=None) -> (rate, source)` in `domain_coordinators/energy_billing.py`. Four-tier resolution:

1. EC's live `current_effective_rate` → `(rate, "ec_tou")`
2. Room entry's `CONF_ELECTRICITY_RATE` override → `(rate, "static_config")`
3. Global integration entry's `CONF_ELECTRICITY_RATE` → `(rate, "static_config")`
4. `DEFAULT_ELECTRICITY_RATE` → `(rate, "static_config")`

Never returns `0.1` as a magic fallback. Logs at `_LOGGER.debug` if any tier raises (no more silent failures).

**Review fix (HIGH #1):** Initial implementation walked `hass.data[DOMAIN].values()` looking for dict-wrapped entries; the canonical slot is `hass.data[DOMAIN]["integration"]` (a ConfigEntry, per `__init__.py:612`). Fixed to read the slot directly.

### D3 — 8 cost calculation sites migrated
| Site | File | Before | After |
|---|---|---|---|
| Room cost today | `sensor.py:633-637` | static | helper |
| Room cost weekly/monthly + cost/hour | `coordinator.py:2113-2120` | static | helper |
| PredictedCost{Today,Week,Month} | `aggregation.py:1865-2032` | static | helper |
| EnergyCostPerOccupiedHour | `aggregation.py:2456-2461` | `0.1` magic fallback | helper |
| MostExpensiveCircuit | `aggregation.py:2542-2562` | `0.1` magic fallback | helper |
| OptimizationPotential | `aggregation.py:2599-2633` | `0.1` magic fallback | helper |

Sensors that surface `rate_source` in attributes now accurately reflect `"ec_tou"` or `"static_config"`.

### D4 — UI label clarification
All four `electricity_rate` config-flow surfaces (top-level home setup, room config setup, options flow global, options flow room energy) reworded to explicit "Fallback" framing. Both `strings.json` and `translations/en.json` updated in lockstep.

### D5 — Two new zone cost sensors
- **`ZoneEnergyCostTodaySensor`** — `sensor.<zone>_energy_cost_today`. `MONETARY/USD/TOTAL_INCREASING`. Enabled by default.
- **`ZoneCostPerHourSensor`** — `sensor.<zone>_cost_per_hour`. `MONETARY/USD-per-h/MEASUREMENT`. Enabled by default. Tracks current zone power × live rate.

Both registered at both zone-manager sensor list sites (`aggregation.py:349` and `aggregation.py:425`).

### D6 — One new whole-house cost sensor
- **`WholeHouseCostTodaySensor`** — `sensor.ura_whole_house_cost_today`. Pairs with existing `WholeHouseEnergyTodaySensor`. Returns None (not 0.0) when source energy is unconfigured. Enabled by default on the house device.

### D7 — BACKLOG.md surgery

**Removed (5 entries):**
- "URA DB Scale Management" archived section (killed per user directive)
- Bug "1. Config flow save timeout" (struck per user directive — treated as solved)
- Bug "2. Energy TOU blocking I/O" (resolved by D1)
- Sensor Reconciliation Cycle "D. Stub energy/cost prediction sensors" (shipped in v4.2.27, audit confirmed)
- Sensor Reconciliation Cycle "E. Legacy fixed-cost-rate vs EC TOU rate reconciliation" (resolved by D3)

**Added (3 entries):**
- "House Energy/Cost Accounting Reconciliation" (Tier 2 investigation) — fork to compare URA's `WholeHouseEnergy` path vs EC's Envoy-derived `cost_today`. Decide canonical realized-cost source.
- "AnomalyType discriminator promote" (Tier 2-DB, on tap) — add `AnomalyType` column to `AnomalyRecord` + `anomaly_log` schema migration.
- "Per-metric z-threshold customization" (deferred with trigger conditions) — promote only on documented signals.

## Files changed

| File | Lines |
|---|---|
| `domain_coordinators/energy_tou.py` | -11 (deleted sync loader) |
| `domain_coordinators/energy.py` | ~15 (collapsed fallback) |
| `domain_coordinators/energy_billing.py` | +70 (new helper) |
| `aggregation.py` | +215 (cost sites + 3 new sensors) |
| `sensor.py` | +8 (cost-today migration) |
| `coordinator.py` | +4 (rate helper wiring) |
| `strings.json` + `translations/en.json` | +14 each (4 surfaces, sync'd) |
| `docs/BACKLOG.md` | ~85 (5 removed, 3 added) |
| `docs/planning/PLANNING_v4.6.8_*.md` | +316 (new) |
| `quality/tests/test_v4_6_8_rate_reconciliation.py` | +310 (new, 18 tests) |
| `quality/tests/test_energy_tou.py` | ~56 (migrated 13 sites away from sync loader) |
| `docs/reviews/code-review/v4.6.8_*.md` | +85 (new) |

## Tests

- 49 v4.6.8-related tests pass (18 new in `test_v4_6_8_rate_reconciliation.py` + 30 migrated in `test_energy_tou.py` + 1 skipped on HA-import env limitation)
- Full bulk-run failure count identical at `pre-review-v4.6.8` baseline: 56 failed / 3183 passed / 14 errors. v4.6.8 introduced ZERO new failures. All failures are pre-existing environmental issues (mock-infrastructure `init_db` attribute, etc.) unrelated to v4.6.8 surfaces.

## Review

Tier 1 single-review. PASS WITH FIXES.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | `_get_effective_rate_kwh` step-3 was dead code (wrong assumed shape on `hass.data[DOMAIN]` values) | **FIXED** — reads canonical `["integration"]` slot directly |
| 2 | MEDIUM | Three `except Exception: pass` blocks silently swallowed errors | **FIXED** — added `_LOGGER.debug` to all three tiers |
| 3 | MEDIUM | `native_value` and `extra_state_attributes` independently recompute rate — microsecond race window | **DEFERRED** — sub-millisecond likelihood, one-cycle stale attribute label only |
| 4 | MEDIUM | Semantic shift documented in planning doc but lacked a test | **FIXED** — added `test_effective_rate_ec_wins_over_room_override` |
| 5 | LOW | Function-local imports for `DOMAIN` etc. in helper | **DEFERRED** — promote at next touch |
| 6 | LOW | Skipped test guards on module-load ImportError, not assertion | **DEFERRED** — test-env limitation |

Full review doc: `docs/reviews/code-review/v4.6.8_ec_tou_rate_reconciliation.md`.

Three new bug classes proposed for `QUALITY_CONTEXT.md` on next touch:
- "Silent fallback skipping a tier of the resolution chain"
- "Silent failure swallowing programmer error"
- "Attribute/state desync from independent recomputation"

## Live validation criteria

Per planning doc acceptance criteria, post-deploy verify:
- [ ] `sensor.universal_room_automation_predicted_cost_today` attribute `rate_source` shows `"ec_tou"`
- [ ] When TOU peak → off-peak transition fires, `sensor.<room>_energy_cost_today` reflects new rate within one cycle
- [ ] `sensor.universal_room_automation_energy_cost_per_occupied_hour` does NOT report a value implying 0.1 $/kWh during startup
- [ ] Two new zone cost sensors visible and non-None per zone
- [ ] `sensor.ura_whole_house_cost_today` visible on house device, non-None USD value
- [ ] No HA log warnings about blocking I/O on event loop from `energy_tou.py`
- [ ] UI options-flow re-open shows new "Fallback Electricity Rate" labels

## Commits

```
09a1182 v4.6.8 post-review doc: Tier 1 findings + bug class proposals
3f0a015 v4.6.8 review fixes: step-3 helper canonical slot + debug logging + EC-wins test
c4bb0c6 v4.6.8: EC TOU Rate Reconciliation + Zone/House Cost Surface
fdb916c v4.6.8 planning: EC TOU rate reconciliation + zone/house cost surface
```

---

**Deploy:** 2026-05-18 CDT (post-review pipeline)
