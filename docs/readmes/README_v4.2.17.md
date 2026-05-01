# v4.2.17 — EV Battery Drain Auto-Pause + Utility Meter Integration (B-Lite)

**Date:** 2026-04-30

## Summary

Two features: (1) EV charger auto-pauses when drawing from home battery below SOC threshold, (2) Utility company meter entity for bill prediction divergence tracking + Emporia mains power stored in grid_import_2.

## Cycle A: EV Battery Drain Auto-Pause

### Problem
When the EV is plugged in during evening/night, the charger drains the Enphase battery instead of drawing from the grid. User was manually pausing charging via the Emporia app every evening.

### Solution
New pause reason `_paused_by_battery_drain` in `EVChargerController`, following the existing `_paused_by_grid_cap` pattern.

**Pause when:** EVSE charging AND battery discharging (>100W) AND SOC < configurable threshold (default 50%)
**Resume when:** Battery stops discharging OR SOC recovers (+5% hysteresis) OR off-peak TOU starts
**Manual override:** If user turns charger back on during pause, 1h cooldown before re-pause
**Priority:** Grid cap > Battery drain > TOU. All pause reasons cross-check each other on resume.

### Config
- `energy_ev_battery_drain_soc`: SOC threshold slider (10-90%, step 5, default 50%)

### State persistence
- `_paused_by_battery_drain` set persisted to DB via `save_energy_state` / `restore_energy_state`
- Cooldown timers are memory-only (lost on restart, acceptable)

## B-Lite: Utility Meter + Emporia Grid Import

### Config
- `energy_utility_meter_entity`: Optional entity picker (domain=sensor, device_class=energy) for SmartHub or similar utility company net energy meter

### grid_import_2
- Empty DB column now populated with Emporia mains import power (kW) from `CONF_ENERGY_GRID_IMPORT_ENTITY`
- UOM-aware: checks `unit_of_measurement` attribute (W or kW) before conversion

### Divergence attributes on predicted_bill sensor
- `utility_kwh`: Current utility meter reading
- `envoy_kwh`: URA's Envoy-derived cycle import
- `utility_divergence_pct`: % difference
- `cycles_aligned`: Whether utility and URA billing cycles started within 2 days of each other
- `prediction_source`: Always "envoy" (auto-switching deferred to B3)

## Review: Tier 2 (2x adversarial)

### Review 1 (Correctness)
| Severity | Found | Fixed |
|----------|-------|-------|
| CRITICAL | 1 | TOU resume defeats battery drain + triggers false cooldown |
| HIGH | 1 | Utility divergence compares incompatible cycle boundaries |
| MEDIUM | 1 | grid_import_2 hardcodes W without checking UOM |
| LOW | 3 | Accepted |

### Review 2 (Race Conditions + Safety)
| Severity | Found | Fixed |
|----------|-------|-------|
| HIGH | 3 | TOU/grid cap/excess solar resume don't check battery drain |
| MEDIUM | 3 | Battery drain resume doesn't check TOU pause; cooldown lost on restart (accepted); import hygiene |
| LOW | 2 | Accepted |

All CRITICAL and HIGH fixed. Full report: `docs/reviews/code-review/v4.2.17_ev_drain_utility_meter.md`

## Files Modified (8)
- `energy_pool.py` — Battery drain detection, pause/resume/cooldown, cross-pause-state guards
- `energy.py` — Battery drain wiring, grid_import_2 logging, utility divergence property, state persistence
- `energy_billing.py` — `import_kwh_cycle` property
- `energy_const.py` — Battery drain + utility meter config keys
- `config_flow.py` — SOC threshold slider + utility meter entity picker
- `sensor.py` — Divergence attributes on predicted_bill sensor
- `strings.json` — Labels + descriptions
- `translations/en.json` — Same
