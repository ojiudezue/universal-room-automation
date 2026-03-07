# URA v3.7.8 — Net Power Entity Fix + Unit Correction

## Summary

Fixes wrong Envoy net power entity ID and corrects unit assumptions.
The Envoy reports net power in kW, not watts.

## Changes

### energy_const.py
- **Fixed net power entity**: `DEFAULT_NET_POWER_ENTITY` corrected from
  `sensor.envoy_202428004328_balanced_net_power_consumption` (doesn't exist) to
  `sensor.envoy_202428004328_current_net_power_consumption`.

### energy_billing.py
- **Fixed unit conversion**: Removed `/1000.0` in `accumulate()` — Envoy reports
  net power in kW, so `kW * hours = kWh` directly. Previous code would have
  undercounted energy by 1000x.

### sensor.py
- **Fixed net consumption sensor**: Removed erroneous `/1000.0` conversion.
  Envoy entity already reports kW.

### const.py
- VERSION bumped to 3.7.8
