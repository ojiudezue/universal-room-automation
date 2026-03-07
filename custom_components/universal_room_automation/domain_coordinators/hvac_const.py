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

# ============================================================================
# Defaults
# ============================================================================

DEFAULT_MAX_SLEEP_OFFSET: Final = 1.5  # F
DEFAULT_COMPROMISE_MINUTES: Final = 30
DEFAULT_AC_RESET_TIMEOUT: Final = 10  # minutes
DEFAULT_FAN_ACTIVATION_DELTA: Final = 2.0  # F
DEFAULT_FAN_HYSTERESIS: Final = 1.5  # F
DEFAULT_FAN_MIN_RUNTIME: Final = 10  # minutes

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
