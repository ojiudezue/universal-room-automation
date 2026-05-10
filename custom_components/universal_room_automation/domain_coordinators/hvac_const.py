"""Constants for HVAC Coordinator.

v3.8.0-H1: Initial implementation.
"""

from __future__ import annotations

from typing import Final

# ============================================================================
# Coordinator identity
# ============================================================================

HVAC_COORDINATOR_ID: Final = "hvac"
HVAC_COORDINATOR_NAME: Final = "HVAC Coordinator"
HVAC_COORDINATOR_PRIORITY: Final = 30

# ============================================================================
# Config keys
# ============================================================================

# Per-zone setpoints (dynamic: hvac_zone_{n}_cool_setpoint, etc.)
CONF_HVAC_COVER_ENTITIES: Final = "hvac_cover_entities"
CONF_HVAC_MAX_SLEEP_OFFSET: Final = "hvac_max_sleep_offset"
CONF_HVAC_COMPROMISE_MINUTES: Final = "hvac_compromise_minutes"
CONF_HVAC_AC_RESET_TIMEOUT: Final = "hvac_ac_reset_timeout"
CONF_HVAC_FAN_ACTIVATION_DELTA: Final = "hvac_fan_activation_delta"
CONF_HVAC_FAN_HYSTERESIS: Final = "hvac_fan_hysteresis"
CONF_HVAC_FAN_MIN_RUNTIME: Final = "hvac_fan_min_runtime"
# v4.5.9.2: occupancy-aware solar-gain cover close threshold.
# When a room is occupied, HVAC only closes its covers if room temp
# is at least this many °F above the zone's cooling setpoint. Default
# 2.0°F, configurable per-house from the coordinator_hvac config step.
# Read by CoverController._should_close_for_occupied_room.
CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA: Final = "hvac_occupied_cover_close_delta"
DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA: Final = 2.0  # °F

# v4.5.10 — Solar-gain cover management tunables (CM-level / HVAC step)
# Master toggle for the entire CoverController feature (parallels
# CONF_HVAC_FAN_CONTROL_ENABLED for fans). When False, CoverController
# .update() early-returns and no close/open commands fire — regardless
# of per-room CONF_COVER_HVAC_MANAGED settings.
CONF_HVAC_SOLAR_GAIN_COVER_ENABLED: Final = "hvac_solar_gain_cover_enabled"
DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED: Final = True

# Solar-gain temperature thresholds (was hardcoded as
# COVER_CLOSE_TEMP / COVER_OPEN_TEMP module constants).
CONF_HVAC_COVER_CLOSE_TEMP: Final = "hvac_cover_close_temp"
DEFAULT_HVAC_COVER_CLOSE_TEMP: Final = 85.0  # °F (matches v3.8.4 COVER_CLOSE_TEMP)
CONF_HVAC_COVER_OPEN_TEMP: Final = "hvac_cover_open_temp"
DEFAULT_HVAC_COVER_OPEN_TEMP: Final = 80.0  # °F (matches v3.8.4 COVER_OPEN_TEMP)

# Manual-override duration after a user touches a managed cover
# (was hardcoded as COVER_MANUAL_OVERRIDE_HOURS = 2).
CONF_HVAC_COVER_OVERRIDE_HOURS: Final = "hvac_cover_override_hours"
DEFAULT_HVAC_COVER_OVERRIDE_HOURS: Final = 2.0  # hours

# Solar banking floor: the coolest setpoint solar banking will drive
# zones to (was hardcoded as SOLAR_BANK_FLOOR = 72.0).
CONF_HVAC_SOLAR_BANK_FLOOR: Final = "hvac_solar_bank_floor"
DEFAULT_HVAC_SOLAR_BANK_FLOOR: Final = 72.0  # °F (matches v3.8.4 SOLAR_BANK_FLOOR)

# Solar window hours — when HVAC watches for solar-gain conditions
# (was hardcoded as COVER_SOLAR_HOUR_START / END = 13 / 18).
CONF_HVAC_COVER_SOLAR_START_HOUR: Final = "hvac_cover_solar_start_hour"
DEFAULT_HVAC_COVER_SOLAR_START_HOUR: Final = 13
CONF_HVAC_COVER_SOLAR_END_HOUR: Final = "hvac_cover_solar_end_hour"
DEFAULT_HVAC_COVER_SOLAR_END_HOUR: Final = 18

# Solar banking battery threshold — minimum SOC for banking to fire
# (was hardcoded as SOLAR_BANK_SOC_MIN = 95).
CONF_HVAC_SOLAR_BANK_SOC_MIN: Final = "hvac_solar_bank_soc_min"
DEFAULT_HVAC_SOLAR_BANK_SOC_MIN: Final = 95  # %

# Pre-cool / pre-heat forecast triggers
# (was hardcoded in hvac_predict.py as PRECOOL_FORECAST_HIGH = 90.0,
#  PREHEAT_FORECAST_LOW = 35.0).
CONF_HVAC_PRECOOL_FORECAST_HIGH: Final = "hvac_precool_forecast_high"
DEFAULT_HVAC_PRECOOL_FORECAST_HIGH: Final = 90.0  # °F
CONF_HVAC_PREHEAT_FORECAST_LOW: Final = "hvac_preheat_forecast_low"
DEFAULT_HVAC_PREHEAT_FORECAST_LOW: Final = 35.0  # °F

# v4.5.10: Hysteresis safety floor — Cover Open Temp must be at least
# this many °F below Cover Close Temp to prevent solar-gain flapping.
COVER_HYSTERESIS_MIN_GAP: Final = 3.0  # °F
CONF_HVAC_ARRESTER_ENABLED: Final = "hvac_arrester_enabled"
CONF_HVAC_AC_RESET_ENABLED: Final = "hvac_ac_reset_enabled"
CONF_HVAC_FAN_CONTROL_ENABLED: Final = "hvac_fan_control_enabled"

# v3.17.0: Zone Intelligence config keys
CONF_HVAC_VACANCY_GRACE_MINUTES: Final = "hvac_vacancy_grace_minutes"
CONF_HVAC_VACANCY_GRACE_CONSTRAINED: Final = "hvac_vacancy_grace_constrained"
CONF_HVAC_MAX_OCCUPANCY_HOURS: Final = "hvac_max_occupancy_hours"
CONF_ZONE_VACANCY_SWEEP_ENABLED: Final = "zone_vacancy_sweep_enabled"
CONF_PERSON_PREFERRED_ZONES: Final = "person_preferred_zones"
CONF_ZONE_PERSONS: Final = "zone_persons"
CONF_ZONE_CAMERAS: Final = "zone_cameras"
CONF_PRE_ARRIVAL_SOURCES: Final = "pre_arrival_sources"
DEFAULT_PRE_ARRIVAL_SOURCES: Final = ["geofence", "ble"]

# v3.19.0: Face-confirmed arrivals
FACE_FRESHNESS_SECONDS: Final = 30
FACE_ARRIVAL_COOLDOWN_SECONDS: Final = 60

# ============================================================================
# Defaults
# ============================================================================

DEFAULT_MAX_SLEEP_OFFSET: Final = 1.5  # F
DEFAULT_COMPROMISE_MINUTES: Final = 30
DEFAULT_AC_RESET_TIMEOUT: Final = 10  # minutes
DEFAULT_FAN_ACTIVATION_DELTA: Final = 2.0  # F
DEFAULT_FAN_HYSTERESIS: Final = 1.5  # F
DEFAULT_FAN_MIN_RUNTIME: Final = 10  # minutes
DEFAULT_ARRESTER_ENABLED: Final = True
DEFAULT_AC_RESET_ENABLED: Final = True
DEFAULT_FAN_CONTROL_ENABLED: Final = True

# v3.17.0: Zone Intelligence defaults
DEFAULT_VACANCY_GRACE_MINUTES: Final = 15  # Normal grace period
DEFAULT_VACANCY_GRACE_CONSTRAINED: Final = 5  # Grace during energy coast/shed
DEFAULT_MAX_OCCUPANCY_HOURS: Final = 8  # Stale sensor failsafe threshold
DEFAULT_ZONE_ENTRY_DWELL_MINUTES: Final = 3  # v4.2.2: Min occupancy before preset change
CONF_HVAC_ZONE_ENTRY_DWELL: Final = "hvac_zone_entry_dwell"  # Config key

# v3.17.0: Solar banking
SOLAR_BANK_SOC_MIN: Final = 95  # % — battery must be effectively full
SOLAR_BANK_TEMP_MIN: Final = 85.0  # °F — forecast must be hot
SOLAR_BANK_OFFSET: Final = -3.0  # °F from target_temp_high
SOLAR_BANK_FLOOR: Final = 72.0  # °F — absolute minimum cooling setpoint
MIN_DEADBAND: Final = 2.0  # °F — Ecobee auto mode minimum

# v3.17.0: Pre-arrival
PRE_ARRIVAL_FAN_TIMEOUT: Final = 15  # Minutes before auto-off
PRE_ARRIVAL_TIMEOUT_MINUTES: Final = 30  # Minutes before stale pre-arrival cleared

# v3.17.0: Duty cycle
DUTY_CYCLE_WINDOW_SECONDS: Final = 20 * 60  # 20-minute rolling window
DUTY_CYCLE_SHED: Final = 0.50  # 50% max runtime during shed
DUTY_CYCLE_COAST: Final = 0.75  # 75% max runtime during coast

# Override Arrester thresholds
OVERRIDE_SEVERE_DELTA: Final = 3.0  # F — severe override threshold
OVERRIDE_NORMAL_DELTA: Final = 1.0  # F — normal override threshold
OVERRIDE_SEVERE_GRACE_MINUTES: Final = 2  # grace before reverting severe
OVERRIDE_NORMAL_GRACE_MINUTES: Final = 5  # grace before compromise on normal
OVERRIDE_COAST_TOLERANCE_BONUS: Final = 1.0  # F — widen tolerance during energy coast

# AC Reset
AC_RESET_MAX_PER_DAY: Final = 2  # max resets per zone per day
AC_RESET_STUCK_MINUTES: Final = 10  # minutes past setpoint before reset
AC_RESET_OFF_DURATION_SECONDS: Final = 60  # seconds to hold off during reset

# Fan speed scaling (above cooling setpoint)
FAN_SPEED_LOW_PCT: Final = 33
FAN_SPEED_MED_PCT: Final = 66
FAN_SPEED_HIGH_PCT: Final = 100
FAN_SPEED_LOW_DELTA: Final = 2.0  # +2-3F -> low
FAN_SPEED_MED_DELTA: Final = 3.0  # +3-5F -> med
FAN_SPEED_HIGH_DELTA: Final = 5.0  # >+5F -> high
DEFAULT_FAN_VACANCY_HOLD: Final = 300  # 5 min hold after vacancy
DEFAULT_HUMIDITY_FAN_ON: Final = 60  # % RH threshold to activate
DEFAULT_HUMIDITY_FAN_OFF: Final = 50  # % RH threshold to deactivate (10% hysteresis)

# Cover Controller
COVER_SOLAR_MONTHS: Final = frozenset({4, 5, 6, 7, 8, 9, 10})
COVER_SOLAR_HOUR_START: Final = 13
COVER_SOLAR_HOUR_END: Final = 18
COVER_CLOSE_TEMP: Final = 85.0  # F
COVER_OPEN_TEMP: Final = 80.0  # F (5F hysteresis)
COVER_MANUAL_OVERRIDE_HOURS: Final = 2
COVER_COMMAND_WINDOW_SECONDS: Final = 120  # ignore state changes within this window (covers take 45-90s to move)

# ============================================================================
# Seasonal preset ranges (cool_setpoint, heat_setpoint)
# ============================================================================

SEASON_SUMMER: Final = "summer"
SEASON_SHOULDER: Final = "shoulder"
SEASON_WINTER: Final = "winter"

# Month ranges
SUMMER_MONTHS: Final = {6, 7, 8, 9}
WINTER_MONTHS: Final = {12, 1, 2}
# Shoulder = everything else (3, 4, 5, 10, 11)

# Default seasonal ranges: {season: {preset: (cool, heat)}}
SEASONAL_DEFAULTS: Final = {
    SEASON_SUMMER: {
        "home": (77, 70),
        "sleep": (76, 70),
        "away": (82, 60),
        "vacation": (85, 58),
    },
    SEASON_SHOULDER: {
        "home": (74, 70),
        "sleep": (73, 68),
        "away": (80, 62),
        "vacation": (82, 58),
    },
    SEASON_WINTER: {
        "home": (72, 70),
        "sleep": (70, 68),
        "away": (78, 60),
        "vacation": (80, 58),
    },
}

# ============================================================================
# House state -> preset mapping
# ============================================================================

HOUSE_STATE_PRESET_MAP: Final = {
    "home_day": "home",
    "home_evening": "home",
    "home_night": "home",
    "sleep": "sleep",
    "waking": "home",
    "away": "away",
    "vacation": "vacation",
    "arriving": "home",
    "guest": "home",
}

# ============================================================================
# Anomaly detection metrics
# ============================================================================

HVAC_METRICS: Final = [
    "zone_call_frequency",
    "short_cycle_rate",
    "override_frequency",
    "comfort_deviation_hours",
]

# Minimum samples before anomaly detection activates (14 days * 24/day)
HVAC_ANOMALY_MIN_SAMPLES: Final = 336

# ============================================================================
# Dispatcher signal for HVAC entity updates
# ============================================================================

SIGNAL_HVAC_ENTITIES_UPDATE: Final = "ura_hvac_entities_update"
