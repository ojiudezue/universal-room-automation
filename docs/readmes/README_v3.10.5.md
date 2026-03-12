# v3.10.5 — Season-Aware Battery Strategy + TOU Rate File Support

**Fixes battery strategy for shoulder/winter seasons. Adds external TOU rate file with separate import/export rates.**

## Problem

The battery strategy treated mid-peak identically in all seasons: "hold charge for peak." But shoulder and winter have **no peak period** — mid-peak IS the highest-rate window ($0.086/kWh vs $0.043 off-peak). The battery was holding charge for a peak that never came, missing the best export window.

## Fix: Season-Aware `determine_mode()`

`BatteryStrategy.determine_mode()` now receives the current season from the TOU engine:

- **Summer mid-peak**: Hold charge for upcoming peak (unchanged)
- **Shoulder/Winter mid-peak**: Discharge battery at low reserve — covers home load, solar exports at $0.086/kWh (2x off-peak rate)
- **Summer peak**: Discharge (unchanged)
- **Off-peak (all seasons)**: Charge from solar (unchanged)

The `season` field is now included in all battery decision results, visible in `sensor.ura_energy_battery_decision` attributes.

## TOU Rate File (`tou_rates.json`)

Rates can now be loaded from an external JSON file at `/config/universal_room_automation/tou_rates.json` instead of only using hardcoded defaults. The loader already existed but was enhanced:

### Separate Import/Export Rates
Each period can specify `import_rate` and `export_rate` independently. Falls back to symmetric `rate` field for backward compat.

### Period Name Normalization
Seven aliases are mapped to internal names: `on_peak`/`on-peak`/`onpeak` → `peak`, `off-peak`/`offpeak` → `off_peak`, `mid-peak`/`midpeak` → `mid_peak`. Unknown period names are logged and skipped.

### Validation
Each season must have an `off_peak` period (it's the fallback). Missing `off_peak` causes graceful fallback to built-in PEC defaults.

### Rate Source Sensor
`sensor.ura_tou_period` now includes a `rate_source` attribute showing the active rate configuration:
- `"built-in PEC 2026"` — using hardcoded defaults
- `"tou_rates.json (PEC, effective 2026-01-01)"` — loaded from file

## Files Changed

- `energy_battery.py` — `determine_mode(tou_period, season)`, season in all return dicts
- `energy_tou.py` — `_PERIOD_ALIASES`, import/export rate support, `rate_source` property, validation
- `energy.py` — Both callers pass season
- `sensor.py` — `rate_source` in TOU period sensor attributes
- `tou_rates.json` — Created on HA host with PEC 2026 rates

## Tests

40 new tests (892 total):
- 21 battery strategy tests (season-aware discharge, envoy unavailable, reserve actions)
- 19 TOU engine tests (JSON loading, aliases, validation, asymmetric rates, fallbacks)
