# URA v3.7.1 — Energy Coordinator Hotfix

## Summary

Critical hotfix for v3.7.0 Energy Coordinator deployment. Fixes crash-on-startup
bug that would break ALL coordinator manager sensors, plus 3 additional safety fixes.

## Bug Fixes (4)

### CRITICAL: `_energy_device_info()` missing imports (sensor.py)
- `DeviceInfo` and `VERSION` used without local imports
- Every other `_*_device_info()` helper uses local imports; this one was missed
- Would raise `NameError` on startup, crashing ALL coordinator manager sensor registration
- Fixed by adding `from homeassistant.helpers.device_registry import DeviceInfo` and `from .const import VERSION`

### Pool speed restore lost on entity unavailability (energy_pool.py)
- When pool speed entity was temporarily unavailable during off-peak restore,
  the code would skip the restore action but still clear `_original_speed` and
  set state to NORMAL, permanently losing the restore value
- Fixed: now defers restore to next cycle when entity is unavailable

### Inline `__import__("datetime")` in forecast (energy_forecast.py)
- `__import__("datetime").timedelta` used instead of proper import
- Fixed: added `timedelta` to existing `from datetime import` statement

### Malformed service string crash (energy.py)
- `service.split(".", 1)` would raise `ValueError` on unpack if service string
  had no dot separator
- Fixed: added guard check with warning log before split
