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

# Per-month solar thresholds (kWh) derived from actual Enphase production data
# (50 panels, 19.4kW DC). Keyed by month number → (P25, P50, P75).
# Classification: excellent >= P75, good >= P50, moderate >= P25, poor < P25.
SOLAR_MONTHLY_THRESHOLDS: Final = {
    1: (33.0, 61.0, 83.0),   # Jan (extrapolated from Dec)
    2: (49.0, 66.0, 80.0),
    3: (60.0, 80.0, 95.0),
    4: (73.0, 93.0, 108.0),
    5: (85.0, 103.0, 118.0),
    6: (106.0, 125.0, 136.0),
    7: (100.0, 120.0, 133.0),
    8: (88.0, 108.0, 124.0),
    9: (68.0, 88.0, 104.0),
    10: (50.0, 68.0, 83.0),
    11: (36.0, 52.0, 66.0),
    12: (33.0, 61.0, 83.0),
}

# Fallback static thresholds for custom override mode
SOLAR_DAY_THRESHOLDS: Final = {
    "excellent": 100.0,
    "good": 80.0,
    "moderate": 50.0,
    "poor": 30.0,
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
DEFAULT_BATTERY_SOC_ENTITY: Final = "sensor.envoy_202428004328_battery"
DEFAULT_BATTERY_POWER_ENTITY: Final = "sensor.envoy_202428004328_encharge_aggregate_power"
DEFAULT_NET_POWER_ENTITY: Final = "sensor.envoy_202428004328_current_net_power_consumption"

# Envoy lifetime accumulators (for accurate daily consumption tracking)
# These monotonically increase and never reset — delta gives true daily values.
DEFAULT_LIFETIME_CONSUMPTION_ENTITY: Final = "sensor.envoy_202428004328_lifetime_energy_consumption"
DEFAULT_LIFETIME_PRODUCTION_ENTITY: Final = "sensor.envoy_202428004328_lifetime_energy_production"
DEFAULT_LIFETIME_NET_IMPORT_ENTITY: Final = "sensor.envoy_202428004328_lifetime_net_energy_consumption"
DEFAULT_LIFETIME_NET_EXPORT_ENTITY: Final = "sensor.envoy_202428004328_lifetime_net_energy_production"
DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY: Final = "sensor.envoy_202428004328_lifetime_battery_energy_charged"
DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY: Final = "sensor.envoy_202428004328_lifetime_battery_energy_discharged"
DEFAULT_BATTERY_CAPACITY_ENTITY: Final = "sensor.envoy_202428004328_battery_capacity"

# Envoy daily sensors (reset at midnight — useful for cross-checks)
DEFAULT_CONSUMPTION_TODAY_ENTITY: Final = "sensor.envoy_202428004328_energy_consumption_today"
DEFAULT_PRODUCTION_TODAY_ENTITY: Final = "sensor.envoy_202428004328_energy_production_today"

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

# EVSE (Emporia WiFi chargers)
DEFAULT_EVSE_GARAGE_A_POWER_ENTITY: Final = "sensor.garage_a_power_minute_average"
DEFAULT_EVSE_GARAGE_B_POWER_ENTITY: Final = "sensor.garage_b_power_minute_average"

# Monitored plugs (L1 charger — switch-only, no power sensor)
DEFAULT_L1_CHARGER_ENTITIES: Final = [
    "switch.smartplug_moes_wifi_garagealeftfront_socket_1",
    "switch.smartplug_moes_wifi_garagealeftfront_socket_2",
    "switch.smartplug_moes_wifi_garagealeftfront_socket_3",
    "switch.smartplug_moes_wifi_garagealeftfront_socket_4",
]

# TOU rate file path
DEFAULT_TOU_RATE_FILE: Final = "universal_room_automation/tou_rates.json"

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
CONF_ENERGY_SOLCAST_TOMORROW_ENTITY: Final = "energy_solcast_tomorrow_entity"
CONF_ENERGY_WEATHER_ENTITY: Final = "energy_weather_entity"
CONF_ENERGY_SOLAR_CLASSIFICATION_MODE: Final = "energy_solar_classification_mode"
CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT: Final = "energy_solar_threshold_excellent"
CONF_ENERGY_SOLAR_THRESHOLD_GOOD: Final = "energy_solar_threshold_good"
CONF_ENERGY_SOLAR_THRESHOLD_MODERATE: Final = "energy_solar_threshold_moderate"
CONF_ENERGY_SOLAR_THRESHOLD_POOR: Final = "energy_solar_threshold_poor"

CONF_ENERGY_EVSE_A_ENTITY: Final = "energy_evse_a_entity"
CONF_ENERGY_EVSE_B_ENTITY: Final = "energy_evse_b_entity"
CONF_ENERGY_L1_CHARGER_ENTITIES: Final = "energy_l1_charger_entities"
CONF_ENERGY_TOU_RATE_FILE: Final = "energy_tou_rate_file"

# Solar classification modes
SOLAR_CLASS_MODE_AUTOMATIC: Final = "automatic"
SOLAR_CLASS_MODE_CUSTOM: Final = "custom"

# ============================================================================
# E6: Load Shedding + Constraint Config
# ============================================================================

CONF_ENERGY_LOAD_SHEDDING_ENABLED: Final = "energy_load_shedding_enabled"
CONF_ENERGY_LOAD_SHEDDING_THRESHOLD: Final = "energy_load_shedding_threshold_kw"
CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES: Final = "energy_load_shedding_sustained_minutes"
CONF_ENERGY_LOAD_SHEDDING_MODE: Final = "energy_load_shedding_mode"

CONF_ENERGY_CONSTRAINT_COAST_OFFSET: Final = "energy_constraint_coast_offset"
CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET: Final = "energy_constraint_precool_offset"
CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET: Final = "energy_constraint_preheat_offset"
CONF_ENERGY_CONSTRAINT_SHED_OFFSET: Final = "energy_constraint_shed_offset"
CONF_ENERGY_PREHEAT_TEMP_THRESHOLD: Final = "energy_preheat_temp_threshold"

# ============================================================================
# Off-Peak Drain Targets (% SOC) — based on tomorrow's solar forecast
# ============================================================================
# Aggressive drain: off-peak grid at $0.043 is 3.7x cheaper than peak ($0.162).
# Draining to low SOC overnight maximizes room for tomorrow's solar absorption.
# Risk is minimal: arbitrage catches poor-forecast + low-SOC scenarios.
# When SOC > target: drain stored solar (free energy) during cheap off-peak
# When SOC <= target: hold and import cheap grid at $0.043/kWh

DEFAULT_OFFPEAK_DRAIN_EXCELLENT: Final = 10
DEFAULT_OFFPEAK_DRAIN_GOOD: Final = 15
DEFAULT_OFFPEAK_DRAIN_MODERATE: Final = 20
DEFAULT_OFFPEAK_DRAIN_POOR: Final = 30
DEFAULT_OFFPEAK_DRAIN_UNKNOWN: Final = 40

CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT: Final = "energy_offpeak_drain_excellent"
CONF_ENERGY_OFFPEAK_DRAIN_GOOD: Final = "energy_offpeak_drain_good"
CONF_ENERGY_OFFPEAK_DRAIN_MODERATE: Final = "energy_offpeak_drain_moderate"
CONF_ENERGY_OFFPEAK_DRAIN_POOR: Final = "energy_offpeak_drain_poor"

# ============================================================================
# Grid Charge Arbitrage
# ============================================================================
# When tomorrow is poor/very_poor solar and SOC < trigger, charge from grid
# overnight at off-peak rate ($0.043) to avoid importing at mid-peak/peak later.

DEFAULT_ARBITRAGE_SOC_TRIGGER: Final = 30
DEFAULT_ARBITRAGE_SOC_TARGET: Final = 80
CONF_ENERGY_ARBITRAGE_ENABLED: Final = "energy_arbitrage_enabled"
CONF_ENERGY_ARBITRAGE_SOC_TRIGGER: Final = "energy_arbitrage_soc_trigger"
CONF_ENERGY_ARBITRAGE_SOC_TARGET: Final = "energy_arbitrage_soc_target"

# ============================================================================
# EVSE Refinement
# ============================================================================

DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD: Final = 95
DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD: Final = 5.0
EVSE_CHARGING_POWER_THRESHOLD: Final = 100  # watts
CONF_ENERGY_EXCESS_SOLAR_ENABLED: Final = "energy_excess_solar_enabled"
CONF_ENERGY_EXCESS_SOLAR_SOC: Final = "energy_excess_solar_soc"
CONF_ENERGY_EXCESS_SOLAR_KWH: Final = "energy_excess_solar_kwh"

# Load shedding defaults
DEFAULT_LOAD_SHEDDING_THRESHOLD_KW: Final = 5.0
DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES: Final = 15
LOAD_SHEDDING_MODE_FIXED: Final = "fixed"
LOAD_SHEDDING_MODE_AUTO: Final = "auto"
LOAD_SHEDDING_AUTO_MIN_DAYS: Final = 30
LOAD_SHEDDING_AUTO_PERCENTILE: Final = 90  # 90th percentile of peak import

# Constraint offset defaults (degrees F)
DEFAULT_CONSTRAINT_COAST_OFFSET: Final = 3.0
DEFAULT_CONSTRAINT_PRECOOL_OFFSET: Final = -2.0
DEFAULT_CONSTRAINT_PREHEAT_OFFSET: Final = 2.0
DEFAULT_CONSTRAINT_SHED_OFFSET: Final = 5.0
DEFAULT_PREHEAT_TEMP_THRESHOLD: Final = 40.0  # F — forecast low below this triggers pre_heat

# Load shedding priority order (cascade)
LOAD_SHEDDING_PRIORITY: Final = ["pool", "ev", "smart_plugs", "hvac"]
