"""Energy Coordinator constants — TOU rate tables, entity mappings, defaults."""

from __future__ import annotations

from typing import Final

# ============================================================================
# PEC TOU Rate Table (2026 Interconnect Time-of-Use)
# ============================================================================
# Source: docs/plans/TOU.md — PEC Interconnection Metering < 50kW
# Import and export rates are symmetric.
# Hours use 24h convention: (start_inclusive, end_exclusive)

PEC_TOU_RATES: Final = {
    "summer": {
        "months": [6, 7, 8, 9],
        "periods": {
            "off_peak": {
                "hours": [(0, 14), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(14, 16), (20, 21)],
                "import_rate": 0.093169,
                "export_rate": 0.093169,
            },
            "peak": {
                "hours": [(16, 20)],
                "import_rate": 0.161843,
                "export_rate": 0.161843,
            },
        },
    },
    "shoulder": {
        "months": [3, 4, 5, 10, 11],
        "periods": {
            "off_peak": {
                "hours": [(0, 17), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(17, 21)],
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
    "winter": {
        "months": [12, 1, 2],
        "periods": {
            "off_peak": {
                "hours": [(0, 5), (9, 17), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(5, 9), (17, 21)],
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
}

PEC_FIXED_CHARGES: Final = {
    "service_availability": 32.50,
    "delivery_per_kwh": 0.022546,
    "transmission_per_kwh": 0.019930,
}

# ============================================================================
# Solar Day Classification Thresholds (kWh)
# ============================================================================

SOLAR_DAY_THRESHOLDS: Final = {
    "excellent": 60.0,
    "good": 45.0,
    "moderate": 30.0,
    "poor": 15.0,
    # below poor = very_poor
}

# ============================================================================
# Battery Strategy Defaults
# ============================================================================

DEFAULT_RESERVE_SOC: Final = 20
DEFAULT_STORM_CHARGE_THRESHOLD: Final = 90
DEFAULT_DECISION_INTERVAL_MINUTES: Final = 5
DEFAULT_BILL_CYCLE_START_DAY: Final = 23

# Battery storage mode values (Enphase Enpower)
BATTERY_MODE_SELF_CONSUMPTION: Final = "self_consumption"
BATTERY_MODE_SAVINGS: Final = "savings"
BATTERY_MODE_BACKUP: Final = "backup"

# ============================================================================
# Entity ID Defaults (Enphase/Envoy)
# ============================================================================

# Solar / Grid / Battery
DEFAULT_SOLAR_PRODUCTION_ENTITY: Final = "sensor.envoy_202428004328_current_power_production"
DEFAULT_GRID_CONSUMPTION_ENTITY: Final = "sensor.envoy_202428004328_current_power_consumption"
DEFAULT_BATTERY_SOC_ENTITY: Final = "sensor.encharge_aggregate_battery_percentage"
DEFAULT_BATTERY_POWER_ENTITY: Final = "sensor.envoy_202428004328_encharge_aggregate_power"
DEFAULT_NET_POWER_ENTITY: Final = "sensor.envoy_202428004328_balanced_net_power_consumption"

# Envoy lifetime accumulators (for accurate daily consumption tracking)
# These monotonically increase and never reset — delta gives true daily values.
DEFAULT_LIFETIME_CONSUMPTION_ENTITY: Final = "sensor.envoy_202428004328_lifetime_energy_consumption"
DEFAULT_LIFETIME_PRODUCTION_ENTITY: Final = "sensor.envoy_202428004328_lifetime_energy_production"
DEFAULT_LIFETIME_NET_IMPORT_ENTITY: Final = "sensor.envoy_202428004328_lifetime_net_energy_consumption"
DEFAULT_LIFETIME_NET_EXPORT_ENTITY: Final = "sensor.envoy_202428004328_lifetime_net_energy_production"
DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY: Final = "sensor.envoy_202428004328_lifetime_battery_energy_charged"
DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY: Final = "sensor.envoy_202428004328_lifetime_battery_energy_discharged"
DEFAULT_BATTERY_CAPACITY_ENTITY: Final = "sensor.envoy_202428004328_battery_capacity"

# Enpower control entities
DEFAULT_STORAGE_MODE_ENTITY: Final = "select.enpower_482348004678_storage_mode"
DEFAULT_RESERVE_SOC_ENTITY: Final = "number.enpower_482348004678_reserve_battery_level"
DEFAULT_GRID_ENABLED_ENTITY: Final = "switch.enpower_482348004678_grid_enabled"
DEFAULT_CHARGE_FROM_GRID_ENTITY: Final = "switch.enpower_482348004678_charge_from_grid"

# Solcast forecast
DEFAULT_SOLCAST_TODAY_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_today"
DEFAULT_SOLCAST_TOMORROW_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_tomorrow"
DEFAULT_SOLCAST_REMAINING_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_remaining_today"
DEFAULT_SOLCAST_PEAK_ENTITY: Final = "sensor.solcast_pv_forecast_peak_forecast_today"
DEFAULT_SOLCAST_PEAK_TIME_ENTITY: Final = "sensor.solcast_pv_forecast_peak_time_today"

# Weather
DEFAULT_WEATHER_ENTITY: Final = "weather.phalanxmadrone"

# ============================================================================
# Config Keys (Energy-specific options flow)
# ============================================================================

CONF_ENERGY_RESERVE_SOC: Final = "energy_reserve_soc"
CONF_ENERGY_DECISION_INTERVAL: Final = "energy_decision_interval"
CONF_ENERGY_BILL_CYCLE_DAY: Final = "energy_bill_cycle_day"
CONF_ENERGY_SOLAR_ENTITY: Final = "energy_solar_entity"
CONF_ENERGY_GRID_ENTITY: Final = "energy_grid_entity"
CONF_ENERGY_BATTERY_SOC_ENTITY: Final = "energy_battery_soc_entity"
CONF_ENERGY_BATTERY_POWER_ENTITY: Final = "energy_battery_power_entity"
CONF_ENERGY_NET_POWER_ENTITY: Final = "energy_net_power_entity"
CONF_ENERGY_STORAGE_MODE_ENTITY: Final = "energy_storage_mode_entity"
CONF_ENERGY_RESERVE_SOC_ENTITY: Final = "energy_reserve_soc_entity"
CONF_ENERGY_GRID_ENABLED_ENTITY: Final = "energy_grid_enabled_entity"
CONF_ENERGY_CHARGE_FROM_GRID_ENTITY: Final = "energy_charge_from_grid_entity"
CONF_ENERGY_SOLCAST_TODAY_ENTITY: Final = "energy_solcast_today_entity"
CONF_ENERGY_SOLCAST_REMAINING_ENTITY: Final = "energy_solcast_remaining_entity"
CONF_ENERGY_WEATHER_ENTITY: Final = "energy_weather_entity"
