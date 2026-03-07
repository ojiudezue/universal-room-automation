# URA v3.7.7 — Consumption + EV Monitoring + TOU JSON File Support

## Summary

Adds consumption and EV monitoring sensors, L1 charger binary sensor,
and TOU rate loading from JSON file for easy rate updates without code changes.

## Changes

### New Sensors

| Sensor | Type | Source |
|--------|------|--------|
| `sensor.ura_energy_coordinator_total_consumption` | Power (kW) | Envoy CT clamp — whole-home consumption |
| `sensor.ura_energy_coordinator_net_consumption` | Power (kW) | Envoy balanced net — positive=importing, negative=exporting |
| `sensor.ura_energy_coordinator_ev_charge_rate_garage_a` | Power (W) | Emporia EVSE Garage A |
| `sensor.ura_energy_coordinator_ev_charge_rate_garage_b` | Power (W) | Emporia EVSE Garage B |
| `binary_sensor.ura_energy_coordinator_l1_charger_garage_a` | Plug | Moes smart plug socket state (any socket on = charging) |

### energy_const.py
- Added default EVSE entity IDs (Garage A/B power minute average)
- Added default L1 charger entity IDs (Moes plug sockets 1-4)
- Added config keys for EVSE, L1 charger, and TOU rate file
- Added `DEFAULT_TOU_RATE_FILE` path constant

### energy_tou.py
- **`TOURateEngine.from_json_file()`**: New class method to load TOU rates from
  `/config/universal_room_automation/tou_rates.json`. Validates and converts the
  JSON format to internal rate table. Falls back to PEC defaults if file not found
  or invalid.

### energy.py
- **TOU from JSON**: Constructor now attempts to load TOU rates from JSON file
  before falling back to hardcoded PEC defaults.
- **New monitoring accessors**: `total_consumption_kw`, `net_consumption_kw`,
  `evse_garage_a_power`, `evse_garage_b_power`, `l1_charger_active`

### sensor.py
- Added 4 new sensor classes: `EnergyTotalConsumptionSensor`,
  `EnergyNetConsumptionSensor`, `EnergyEVChargeRateASensor`,
  `EnergyEVChargeRateBSensor`

### binary_sensor.py
- Added `EnergyL1ChargerBinarySensor` — binary plug sensor derived from
  Moes smart plug switch states

### const.py
- VERSION bumped to 3.7.7

## TOU Rate File Format

Place at `/config/universal_room_automation/tou_rates.json`:
```json
{
  "utility": "PEC",
  "effective_date": "2025-01-01",
  "seasons": {
    "summer": {
      "months": [6, 7, 8, 9],
      "periods": {
        "off_peak": { "rate": 0.043481, "hours": [[0,14], [21,24]] },
        "mid_peak": { "rate": 0.093169, "hours": [[14,16], [20,21]] },
        "on_peak":  { "rate": 0.161843, "hours": [[16,20]] }
      }
    }
  },
  "fixed_charges": {
    "service_availability_monthly": 32.50,
    "delivery_per_kwh": 0.022546,
    "transmission_per_kwh": 0.019930
  }
}
```
