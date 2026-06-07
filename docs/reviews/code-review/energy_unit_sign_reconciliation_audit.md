# Energy Domain — Unit (W/kW/kWh) & Sign Reconciliation Audit

**Date:** 2026-06-07
**Scope:** Exhaustive audit of power/energy unit conversions, sensor unit
declarations, and power sign conventions across the energy domain
(`energy.py`, `energy_battery.py`, `energy_pool.py`, `energy_billing.py`,
`energy_forecast.py`, `aggregation.py`, `sensor.py`).
**Method:** Traced every `*1000` / `/1000` conversion to its source-unit
origin; cross-checked every `UnitOfPower`/`UnitOfEnergy` sensor declaration
against its `native_value`; verified every producer/consumer of signed power.

## Verdict

- **Sign conventions: clean.** Grid `net` positive=import / negative=export,
  and battery `net_power_w` positive=charging / negative=discharging are
  applied consistently everywhere. The Envoy `current_battery_discharge`
  sign flip (`energy_battery.py:261-271`) is applied at the property layer,
  so no threshold math reads an un-negated value. No sign bugs found.
- **MWh lifetime deltas: correct.** The `(current - snapshot) * 1000.0 → _kwh`
  lines (`energy.py:1422-1426, 1457, 1657`) are correct — the lifetime
  sensors report **MWh** (confirmed via `_get_lifetime_*` docstrings).
- **Unit declarations: 3 display-sensor BUGs fixed** (below) + **2 latent
  hardening gaps closed**.

## BUGs found and FIXED

| # | Site | Bug | Fix |
|---|---|---|---|
| 1 | `sensor.py` `_build_situation_attrs` grid-cost-per-hour | Read the **raw** `net_power` entity and divided by 1000 assuming W. On a kW-reporting Envoy the $/h figure was **1000x too low**. | Use the uom-normalized `energy._battery.net_power_w` (always W); handle `None`. |
| 2 | `sensor.py` `EnergyTotalConsumptionSensor` | Declares `kW` but returned `total_consumption_kw`, a historically mis-named property that returns the **raw** entity state (W or kW per firmware). Displayed ~1000x too large on W-firmware. | Return `energy.total_consumption_w / 1000.0` (normalized → true kW). |
| 3 | `sensor.py` `EnergyNetConsumptionSensor` | Declares `kW` but returned `net_consumption_kw` → raw `battery.net_power` (W or kW per firmware). Same 1000x mislabel. | Return `energy._battery.net_power_w / 1000.0`. |

These three were the last un-migrated consumers of the deliberately-trapped
mis-named `*_kw` properties; the v4.3.4 / v4.5.0 `_w`-normalization sweep
exists precisely to fix this class. The `net_consumption_kw` property
docstring (which falsely claimed "(kW)") was corrected to document that it
returns raw firmware-dependent units and must not gain new callers.

## Latent gaps HARDENED (correct today, fragile)

| Site | Gap | Fix |
|---|---|---|
| `energy.py` `_get_battery_capacity_kwh` (`:1941`) | `/1000` hardcoded as Wh→kWh with no `unit_of_measurement` check. Correct on the current Enphase Encharge (reports Wh), but a kWh-reporting firmware would collapse capacity to ~0.04 kWh and silently flip arbitrage/forecast to the 40 kWh fallback. | Added the same kW/W-style uom guard the power readers use (`kWh`→as-is, else `/1000`). |
| `energy_forecast.py` `_get_battery_capacity_kwh` (`:374`) | Same hardcoded Wh assumption (independent second implementation). | Same uom guard. |

## Confirmed OK (no change)

- All `_w / 1000.0 → _kw` boundary conversions read uom-normalized `_w`
  properties (`net_power_w`, `solar_production_w`, `total_consumption_w`).
- `energy_pool.py:288`, `energy.py:4545`, `energy_battery.py:297/323`,
  `energy_billing.py:166/188` — all uom-checked kW↔W normalizations.
- All `WATT` / `KILO_WATT_HOUR` aggregation sensors return values matching
  their declared unit (room/zone/whole-house sums honor the W power / kWh
  energy config contract).
- `aggregation.py:3817` and the SPAN circuit integration read true-W
  `STATE_POWER_CURRENT` (confirmed W at `coordinator.py:2290`).

## Validation

- `py_compile` clean; no conflict markers.
- Full suite: **zero new failures** vs the pre-fix baseline (39==39,
  identical names — all pre-existing order-dependent flakiness +
  `activity_logger` import errors). 677 energy-domain tests pass.
