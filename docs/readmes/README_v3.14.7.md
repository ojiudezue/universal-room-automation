# v3.14.7: Net Grid Exchange Sensor

**Date:** 2026-03-13
**Branch:** develop -> main

## Changes

### `sensor.py` — `EnergyImportTodaySensor`
- **Value**: Now shows `import_kwh - export_kwh` (negative = net export day). Previously only showed import (always >= 0).
- **State class**: Changed from `TOTAL_INCREASING` to `MEASUREMENT` to allow negative values.
- **Attributes**: Now includes full breakdown: `import_kwh`, `export_kwh`, `import_cost`, `export_credit`, `net_cost`.

### `domain_coordinators/energy.py` — `battery_full_time`
- Hold cache now persists last known value through brief Envoy outages within a session.

## Envoy Availability Note
URA does NOT poll the Envoy directly — it reads HA entity states. The HA Enphase integration polls the Envoy (~60s). Envoy drops are network issues, not rate limiting from URA.
