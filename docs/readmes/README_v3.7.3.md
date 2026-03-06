# URA v3.7.3 — Envoy Resilience & Consumption Cross-Check

## Summary

Hardening the Energy Coordinator against Envoy outages (WiFi/cellular/ethernet
connectivity issues are common) and adding consumption tracking cross-checks
for data integrity.

## Changes

### Envoy offline safeguard (energy_battery.py)
- Added `envoy_available` property: checks both SOC and storage mode readability
- When Envoy is unavailable, `determine_mode()` returns a hold result with
  **zero actions** — the system stays in its current state until we can read again
- Logs a warning each cycle the Envoy is down
- Battery status dict now includes `envoy_available` flag

### Envoy availability tracking (energy.py)
- Tracks consecutive unavailable cycles (`_envoy_unavailable_count`)
- After 3 consecutive misses (~15 minutes), sends NM alert:
  "Envoy Offline — battery strategy holding, no commands issued"
- Logs reconnection when Envoy comes back
- Tracks `envoy_last_available` timestamp
- All exposed in `get_energy_summary()` for dashboard/diagnostics

### Consumption cross-check (energy.py)
- Hourly comparison of our `lifetime_energy_consumption` delta vs Envoy's
  `energy_consumption_today` sensor (which resets at midnight)
- If they diverge by >15%, logs a warning with both values
- Detects Envoy reboots: if Envoy's daily value is 2x+ our delta and our
  delta is suspiciously low (<5 kWh), re-seeds the lifetime snapshot
- Skips early morning when both values are near zero (avoids false positives)
- Rate-limited to once per hour to prevent log spam

### New entity constants (energy_const.py)
- `DEFAULT_CONSUMPTION_TODAY_ENTITY` — Envoy's daily consumption (resets at midnight)
- `DEFAULT_PRODUCTION_TODAY_ENTITY` — Envoy's daily production (resets at midnight)

## Design Philosophy

Energy management requires defense in depth. The Envoy connects via WiFi,
cellular, and ethernet — any can fail. The safest behavior when blind is to
hold current state and alert, never to make assumptions. The cross-check
provides an independent verification channel so we catch data corruption
before it compounds into wrong billing or forecast errors.
