# v4.7.16.5 — EnergyImportTodaySensor state_class fix

**Tier 1.** Single class-attribute change + 2 source-grep tests + repo-wide audit guard.

## What broke

HA platform logged the following warning on every boot:

> `Entity sensor.ura_energy_coordinator_energy_import_today (<class 'EnergyImportTodaySensor'>) is using state class 'measurement' which is impossible considering device class ('energy') it is using; expected None or one of 'total', 'total_increasing'`

The class at `sensor.py:8021-8033` declared `device_class=ENERGY` with `state_class=MEASUREMENT` — an invalid combination per HA's sensor platform.

## Fix

`_attr_state_class = SensorStateClass.MEASUREMENT` → `SensorStateClass.TOTAL`.

Why `TOTAL` (not `TOTAL_INCREASING`):
- `native_value` returns `import_kwh − export_kwh`, which **can be negative** on export-heavy days.
- `TOTAL_INCREASING` requires monotonic non-decrease and would log a new warning every time the value dipped.
- `TOTAL` is HA's intended state_class for net/bidirectional accumulators. Matches sibling convention at `sensor.py:713` (`EnergyExportTodaySensor`) and `sensor.py:773`.

`last_reset` is not required for `TOTAL` (sibling sensors omit it and have been stable; HA's long-term statistics engine handles the daily roll-over without it).

## Repo-wide audit

A second test (`test_no_energy_measurement_combo_remains_anywhere`) walks every class in `sensor.py` and asserts that no class with `device_class=ENERGY` also declares `state_class=MEASUREMENT`. 7 ENERGY sensors enumerated, all correctly classed post-hotfix. The audit guard prevents recurrence.

## Live validation

```python
ha_get_state("sensor.ura_energy_coordinator_energy_import_today",
             attribute_keys=["state_class"])
# Expect: state_class == "total"
```

HA error log: the platform warning should not reappear after the next restart.

## Tier

1. 1 LoC production + 1 comment block + 2 tests. No DB / config-flow / migration / entity surface change.
