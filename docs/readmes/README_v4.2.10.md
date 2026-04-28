# v4.2.10 — EC Runtime Toggles + Off-Peak Drain Numbers + Memory Diagnostic

**Date:** 2026-04-27

## Summary

11 new entities on the Energy Coordinator and Coordinator Manager devices. 5 toggle switches for runtime control of EC features previously buried in config flow. 4 number entity sliders for off-peak battery drain targets. 2 memory diagnostic sensors for leak detection.

## New Entities

### 5 EC Toggle Switches (Energy Coordinator device)
| Entity | Controls | Default |
|--------|----------|---------|
| `switch.ura_energy_coordinator_grid_import_cap` | EV grid import cap (v4.0.18) | Off |
| `switch.ura_energy_coordinator_load_shedding` | HVAC constraint cascade | Off |
| `switch.ura_energy_coordinator_excess_solar_charging` | Route surplus solar to EV | Off |
| `switch.ura_energy_coordinator_grid_arbitrage` | Overnight grid charge on poor forecast | Off |
| `switch.ura_energy_coordinator_ev_tou_management` | Pause/resume EV by TOU period | On |

Implementation: Factory pattern (`_ec_switch_factory`) generates all 5 from a template. Each uses `SwitchEntity + RestoreEntity`, `@callback def _retry_restore`, deferred restore on startup.

### 4 Off-Peak Drain Number Sliders (Energy Coordinator device)
| Entity | Default | Range |
|--------|---------|-------|
| `number.ura_energy_coordinator_off_peak_drain_excellent` | 10% | 5-50% |
| `number.ura_energy_coordinator_off_peak_drain_good` | 15% | 5-60% |
| `number.ura_energy_coordinator_off_peak_drain_moderate` | 20% | 5-70% |
| `number.ura_energy_coordinator_off_peak_drain_poor` | 30% | 5-80% |

Implementation: `OffPeakDrainNumber(NumberEntity, RestoreEntity)`. Reads initial value from config entry, persists slider changes via RestoreEntity, updates BatteryStrategy drain targets at runtime.

### 2 Memory Diagnostic Sensors (Coordinator Manager device)
| Entity | Measures |
|--------|----------|
| `sensor.ura_coordinator_manager_memory_usage` | URA in-memory footprint (KB) with per-component breakdown |
| `sensor.ura_coordinator_manager_memory_delta` | Change since last measurement (leak detector) |

Attributes include: per-component bytes, DB write count, queue peak, key count.

## Energy Coordinator Changes
- `arbitrage_enabled` property/setter (forwards to BatteryStrategy)
- `ev_tou_enabled` property/setter + gate on `ev.determine_actions()`
- `offpeak_drain_targets` property + `set_offpeak_drain()` method with input validation

## Review: 2x adversarial
- CRITICAL: Wrong attribute name `_offpeak_drain_targets` → `_drain_targets` — caught and fixed
- HIGH: OffPeakDrainNumber missing RestoreEntity — fixed
- Full report: `docs/reviews/code-review/v4.2.10_ec_toggles_numbers_memory.md`

## Files Modified (4 + docs)
- `switch.py` — 5 EC toggle classes via factory + registration
- `number.py` — OffPeakDrainNumber class + registration
- `sensor.py` — 2 memory sensor classes + _cm_device_info helper
- `energy.py` — Properties, setters, EV TOU gate
