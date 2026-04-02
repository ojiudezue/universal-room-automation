"""Constants for Universal Room Automation."""
#
# Universal Room Automation v3.22.2
# Build: 2026-03-20
# File: const.py
# v3.3.5.1: Fixed OptionsFlow abort messages (no_zones_configured), expanded device sensors,
#           improved cross-platform music transfer handling, added Denon platform detection
# v3.3.5: BUG-008a FIX - Entity registry platform detection for music following
#         - WiiM entities no longer misdetected as Linkplay
#         - Added PLATFORM_WIIM constant and wiim.play_url transfer method
# v3.3.4: BUG-008 FIX - Platform-agnostic music transfer (WiiM/Linkplay support)
# v3.3.3: Added "Manage Zones" to integration options menu
# v3.3.3: Zone configuration now accessible from integration entry
# v3.3.2: Zone entries now properly set up in __init__.py enabling zone OptionsFlow
# v3.3.1.4: Fixed timestamp string parsing in pattern_learning.py
# v3.3.1.3: Fixed pattern learning sensor __init__ signature mismatch
# v3.3.1.2: Fixed missing Optional/AggregationEntity imports in sensor.py
# v3.3.1.2: Added database WAL mode for concurrency
# v3.3.1: Added music following configuration (room/zone media player settings)
# v3.3.1: Renamed ReconfigureButton to ReloadRoomButton
# v3.3.1: Fixed Optional import in database.py
# v3.3.1: Fixed missing person_tracking strings
# v3.2.9: Fixed zone sensor race condition with deferred initialization
#

from datetime import timedelta
from typing import Final

# Integration domain
DOMAIN: Final = "universal_room_automation"

# Integration info
NAME: Final = "Universal Room Automation"
VERSION: Final = "3.22.2"

# Platforms
PLATFORMS: Final = ["binary_sensor", "sensor", "switch", "button", "number", "select"]

# Update intervals
UPDATE_INTERVAL: Final = 30  # seconds - used by person_coordinator
SCAN_INTERVAL_OCCUPANCY: Final = timedelta(seconds=30)  # Responsive occupancy checks
SCAN_INTERVAL_ENERGY: Final = timedelta(minutes=5)      # Energy calculations
SCAN_INTERVAL_PREDICTIONS: Final = timedelta(minutes=15) # Prediction updates
SCAN_INTERVAL_ENERGY_HISTORY: Final = timedelta(minutes=15)  # v3.1.6: Energy history logging

# ============================================================================
# v3.0.0 ENTRY TYPE CONSTANTS
# ============================================================================

ENTRY_TYPE_INTEGRATION: Final = "integration"
ENTRY_TYPE_ROOM: Final = "room"
ENTRY_TYPE_ZONE: Final = "zone"
ENTRY_TYPE_ZONE_MANAGER: Final = "zone_manager"
ENTRY_TYPE_COORDINATOR_MANAGER: Final = "coordinator_manager"
CONF_ENTRY_TYPE: Final = "entry_type"
CONF_INTEGRATION_ENTRY_ID: Final = "integration_entry_id"
CONF_OVERRIDE_NOTIFICATIONS: Final = "override_notifications"

# ============================================================================
# v3.1.0 AGGREGATION & ZONES CONSTANTS
# ============================================================================

# Zone configuration
CONF_ZONE: Final = "zone"
CONF_ZONE_NAME: Final = "zone_name"
CONF_ZONE_ROOMS: Final = "zone_rooms"
CONF_ZONE_DESCRIPTION: Final = "zone_description"
CONF_SHARED_SPACE: Final = "shared_space"
CONF_SHARED_SPACE_AUTO_OFF_HOUR: Final = "shared_space_auto_off_hour"
CONF_SHARED_SPACE_WARNING: Final = "shared_space_warning"

# ============================================================================
# v3.3.1 MUSIC FOLLOWING CONFIGURATION
# ============================================================================

# Room-level music following
CONF_ROOM_MEDIA_PLAYER: Final = "room_media_player"
CONF_MUSIC_FOLLOWING_ENABLED: Final = "music_following_enabled"

# Zone-level music configuration
CONF_ZONE_PLAYER_ENTITY: Final = "zone_player_entity"
CONF_ZONE_PLAYER_MODE: Final = "zone_player_mode"

# Zone player mode options
ZONE_PLAYER_MODE_INDEPENDENT: Final = "independent"  # Use zone player only
ZONE_PLAYER_MODE_AGGREGATE: Final = "aggregate"      # Use all room players
ZONE_PLAYER_MODE_FALLBACK: Final = "fallback"        # Try zone player, then rooms

# Water leak sensor
CONF_WATER_LEAK_SENSOR: Final = "water_leak_sensor"

# Alert lights
CONF_ALERT_LIGHTS: Final = "alert_lights"
CONF_ALERT_LIGHT_COLOR: Final = "alert_light_color"

# Alert light color presets
ALERT_COLOR_AMBER: Final = "amber"
ALERT_COLOR_RED: Final = "red"
ALERT_COLOR_BLUE: Final = "blue"
ALERT_COLOR_GREEN: Final = "green"
ALERT_COLOR_WHITE: Final = "white"

# RGB values for alert colors
ALERT_COLOR_RGB: Final = {
    ALERT_COLOR_AMBER: [255, 191, 0],
    ALERT_COLOR_RED: [255, 0, 0],
    ALERT_COLOR_BLUE: [0, 0, 255],
    ALERT_COLOR_GREEN: [0, 255, 0],
    ALERT_COLOR_WHITE: [255, 255, 255],
}

# Security alert thresholds (minutes)
DEFAULT_DOOR_ALERT_THRESHOLD: Final = 10  # Normal hours
DEFAULT_WINDOW_ALERT_THRESHOLD: Final = 30  # Normal hours
SLEEP_DOOR_ALERT_THRESHOLD: Final = 1  # During sleep for shared/egress
SLEEP_WINDOW_ALERT_THRESHOLD: Final = 5  # During sleep for shared/egress

# Shared space defaults
DEFAULT_SHARED_SPACE_AUTO_OFF_HOUR: Final = 23  # 11 PM

# Aggregation sensor entity IDs (base names)
AGGREGATION_ANYONE_HOME: Final = "anyone_home"
AGGREGATION_ROOMS_OCCUPIED: Final = "rooms_occupied"
AGGREGATION_SAFETY_ALERT: Final = "safety_alert"
AGGREGATION_SECURITY_ALERT: Final = "security_alert"
AGGREGATION_CLIMATE_DELTA: Final = "climate_delta"
AGGREGATION_PREDICTED_COOLING: Final = "predicted_cooling_need"
AGGREGATION_PREDICTED_HEATING: Final = "predicted_heating_need"

# v3.1.6: New aggregation sensors
AGGREGATION_HUMIDITY_DELTA: Final = "humidity_delta"
AGGREGATION_TEMP_DELTA_OUTSIDE: Final = "temp_delta_outside"
AGGREGATION_HUMIDITY_DELTA_OUTSIDE: Final = "humidity_delta_outside"
AGGREGATION_HVAC_DIRECTION: Final = "hvac_direction"
AGGREGATION_OCCUPANT_COUNT: Final = "occupant_count"
AGGREGATION_PREDICTED_ENERGY_TODAY: Final = "predicted_energy_today"
AGGREGATION_PREDICTED_ENERGY_WEEK: Final = "predicted_energy_week"
AGGREGATION_PREDICTED_ENERGY_MONTH: Final = "predicted_energy_month"
AGGREGATION_PREDICTED_COST_TODAY: Final = "predicted_cost_today"
AGGREGATION_PREDICTED_COST_WEEK: Final = "predicted_cost_week"
AGGREGATION_PREDICTED_COST_MONTH: Final = "predicted_cost_month"
AGGREGATION_WHOLE_HOUSE_POWER: Final = "whole_house_power"
AGGREGATION_WHOLE_HOUSE_ENERGY: Final = "whole_house_energy_today"
AGGREGATION_ROOMS_ENERGY_TOTAL: Final = "rooms_energy_total"
AGGREGATION_ENERGY_COVERAGE_DELTA: Final = "energy_coverage_delta"

# ============================================================================
# v3.2.0 PERSON TRACKING CONSTANTS
# ============================================================================

# Person tracking configuration
CONF_TRACKED_PERSONS: Final = "tracked_persons"
CONF_PERSON_DATA_RETENTION: Final = "person_data_retention_days"
CONF_TRANSITION_DETECTION_WINDOW: Final = "transition_detection_window"
CONF_TRACK_PERSONS_IN_ROOM: Final = "track_persons_in_room"

# v3.2.8: Presence decay configuration
CONF_PERSON_DECAY_TIMEOUT: Final = "person_decay_timeout"
DEFAULT_PERSON_DECAY_TIMEOUT: Final = 300  # 5 minutes - time before person location becomes "stale"

# v3.2.8: Tracking status states
TRACKING_STATUS_ACTIVE: Final = "active"    # Recently updated by Bermuda
TRACKING_STATUS_STALE: Final = "stale"      # Not updated within decay timeout
TRACKING_STATUS_LOST: Final = "lost"        # No recent Bermuda data, cleared location

# v3.2.8: Stale threshold (shorter than decay timeout)
STALE_THRESHOLD_SECONDS: Final = 60  # 1 minute - time before "stale" status

# v3.2.8: Path tracking
MAX_RECENT_PATH_LENGTH: Final = 10  # Number of recent room transitions to track

# Default values
DEFAULT_PERSON_DATA_RETENTION: Final = 90  # days (0 = infinite)
DEFAULT_TRANSITION_WINDOW: Final = 120  # seconds

# Person tracking update intervals
SCAN_INTERVAL_PERSON_TRACKING: Final = timedelta(seconds=15)  # Person location updates
SCAN_INTERVAL_PERSON_SNAPSHOTS: Final = timedelta(minutes=15)  # Database snapshots

# Person confidence levels
CONFIDENCE_HIGH: Final = 0.9   # 3+ scanners agree
CONFIDENCE_MEDIUM: Final = 0.6  # 2 scanners agree
CONFIDENCE_LOW: Final = 0.3     # 1 scanner or disagreement

# v3.2.0.1: BLE distance thresholds for confidence calculation
CONF_PERSON_HIGH_CONFIDENCE_DISTANCE: Final = "person_high_confidence_distance"
CONF_PERSON_MEDIUM_CONFIDENCE_DISTANCE: Final = "person_medium_confidence_distance"
DEFAULT_HIGH_CONFIDENCE_DISTANCE: Final = 10.0  # feet - close enough to be in room
DEFAULT_MEDIUM_CONFIDENCE_DISTANCE: Final = 25.0  # feet - detected but maybe not in room

# Detection methods
DETECTION_METHOD_BERMUDA: Final = "bermuda_ble"
DETECTION_METHOD_GPS: Final = "phone_gps"
DETECTION_METHOD_COMBINED: Final = "combined"

# Room-level person sensor keys
SENSOR_CURRENT_OCCUPANTS: Final = "current_occupants"
SENSOR_OCCUPANT_COUNT: Final = "occupant_count"
SENSOR_LAST_OCCUPANT: Final = "last_occupant"
SENSOR_LAST_OCCUPANT_TIME: Final = "last_occupant_time"

# Integration-level person sensor keys
SENSOR_PERSON_LOCATION: Final = "person_location"
SENSOR_PERSON_PREVIOUS_LOCATION: Final = "person_previous_location"
SENSOR_PERSON_PREVIOUS_SEEN: Final = "person_previous_seen"

# State keys for aggregation
STATE_ZONES_OCCUPIED: Final = "zones_occupied"
STATE_OCCUPIED_ROOMS: Final = "occupied_rooms"
STATE_SHARED_SPACES_OCCUPIED: Final = "shared_spaces_occupied"
STATE_HOTTEST_ROOM: Final = "hottest_room"
STATE_COLDEST_ROOM: Final = "coldest_room"
STATE_TEMP_DELTA: Final = "temp_delta"
STATE_MOST_HUMID_ROOM: Final = "most_humid_room"
STATE_LEAST_HUMID_ROOM: Final = "least_humid_room"
STATE_HUMIDITY_DELTA: Final = "humidity_delta"
STATE_ALERT_ROOMS: Final = "alert_rooms"
STATE_ALERT_TYPES: Final = "alert_types"
STATE_OPEN_DOORS: Final = "open_doors"
STATE_OPEN_WINDOWS: Final = "open_windows"
STATE_FORECAST_HIGH: Final = "forecast_high"
STATE_FORECAST_LOW: Final = "forecast_low"
STATE_PREDICTED_KWH: Final = "predicted_kwh"
STATE_OCCUPIED_ZONES: Final = "occupied_zones"

# ============================================================================
# v3.1.6 ENERGY SETUP CONSTANTS
# ============================================================================

# Solar/Grid sensors
CONF_SOLAR_EXPORT_SENSOR: Final = "solar_export_sensor"
CONF_GRID_IMPORT_SENSOR: Final = "grid_import_sensor"
CONF_GRID_IMPORT_SENSOR_2: Final = "grid_import_sensor_2"
CONF_BATTERY_LEVEL_SENSOR: Final = "battery_level_sensor"
CONF_WHOLE_HOUSE_POWER_SENSOR: Final = "whole_house_power_sensor"
CONF_WHOLE_HOUSE_ENERGY_SENSOR: Final = "whole_house_energy_sensor"

# Energy rate fields
CONF_DELIVERY_RATE: Final = "delivery_rate"
CONF_EXPORT_REIMBURSEMENT_RATE: Final = "export_reimbursement_rate"

# Energy setup defaults
DEFAULT_DELIVERY_RATE: Final = 0.05  # $/kWh transmission
DEFAULT_EXPORT_REIMBURSEMENT_RATE: Final = 0.08  # $/kWh net metering credit

# Energy confidence level thresholds
ENERGY_CONFIDENCE_HIGH: Final = 75
ENERGY_CONFIDENCE_MEDIUM: Final = 50
ENERGY_CONFIDENCE_LOW: Final = 25

# Confidence level labels
CONFIDENCE_LEVEL_HIGH: Final = "high"
CONFIDENCE_LEVEL_MEDIUM: Final = "medium"
CONFIDENCE_LEVEL_LOW: Final = "low"
CONFIDENCE_LEVEL_VERY_LOW: Final = "very low"
CONFIDENCE_LEVEL_COLLECTING: Final = "collecting"

# Coverage rating thresholds (% unaccounted)
COVERAGE_EXCELLENT_THRESHOLD: Final = 10
COVERAGE_GOOD_THRESHOLD: Final = 20
COVERAGE_FAIR_THRESHOLD: Final = 30

# Coverage rating labels
COVERAGE_RATING_EXCELLENT: Final = "Excellent"
COVERAGE_RATING_GOOD: Final = "Good"
COVERAGE_RATING_FAIR: Final = "Fair"
COVERAGE_RATING_INCOMPLETE: Final = "Incomplete"

# Minimum data days for predictions
MIN_DATA_DAYS_PREDICTION: Final = 14

# HVAC direction values
HVAC_DIRECTION_COOLING: Final = "cooling"
HVAC_DIRECTION_HEATING: Final = "heating"
HVAC_DIRECTION_NEUTRAL: Final = "neutral"

# ============================================================================
# CONFIGURATION KEYS - Organized by Config Flow Step
# ============================================================================

# --- Step 1: Basic Setup ---
CONF_ROOM_NAME: Final = "room_name"
CONF_ROOM_TYPE: Final = "room_type"
CONF_AREA_ID: Final = "area_id"
CONF_OCCUPANCY_TIMEOUT: Final = "occupancy_timeout"

# Room types
ROOM_TYPE_BEDROOM: Final = "bedroom"
ROOM_TYPE_CLOSET: Final = "closet"
ROOM_TYPE_BATHROOM: Final = "bathroom"
ROOM_TYPE_MEDIA_ROOM: Final = "media_room"
ROOM_TYPE_GARAGE: Final = "garage"
ROOM_TYPE_UTILITY: Final = "utility"
ROOM_TYPE_COMMON_AREA: Final = "common_area"
ROOM_TYPE_GENERIC: Final = "generic"

# --- Step 2: Sensors ---
CONF_MOTION_SENSORS: Final = "motion_sensors"
CONF_MMWAVE_SENSORS: Final = "presence_sensors"  # Note: blueprint calls them presence_sensors
CONF_OCCUPANCY_SENSORS: Final = "occupancy_sensors"  # Combined motion+presence sensors
# v3.2.4: CONF_PHONE_TRACKER deprecated - use person tracking with Bermuda instead
CONF_PHONE_TRACKER: Final = "phone_tracker"  # DEPRECATED in v3.2.4 - kept for migration
CONF_PHONE_TRACKERS: Final = "phone_trackers"  # v3.1.5: Multi-phone support (DEPRECATED)
CONF_ROOM_BEACONS: Final = "room_beacons"  # v3.1.5: ESPresense/Bermuda room sensors
# v3.2.4: Scanner areas for sparse scanner homes (optional override)
CONF_SCANNER_AREAS: Final = "scanner_areas"  # List of HA area_ids where BLE scanners are
CONF_DOOR_SENSORS: Final = "door_sensor"
CONF_DOOR_TYPE: Final = "door_type"
CONF_WINDOW_SENSORS: Final = "window_sensor"
CONF_TEMPERATURE_SENSOR: Final = "temperature_sensor"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"
CONF_ILLUMINANCE_SENSOR: Final = "illuminance_sensor"

# Door types
DOOR_TYPE_INTERIOR: Final = "interior"
DOOR_TYPE_EGRESS: Final = "egress"

# --- Step 3: Devices ---
CONF_LIGHTS: Final = "lights"
CONF_LIGHT_CAPABILITIES: Final = "light_capabilities"
CONF_FANS: Final = "fans"
CONF_HUMIDITY_FANS: Final = "humidity_fans"
CONF_COVERS: Final = "covers"
CONF_COVER_TYPE: Final = "cover_type"

# v3.2.8.2: Multi-domain auto/manual devices (backward compatible)
CONF_AUTO_SWITCHES: Final = "auto_switches"  # Legacy - still supported
CONF_MANUAL_SWITCHES: Final = "manual_switches"  # Legacy - still supported
CONF_AUTO_DEVICES: Final = "auto_devices"  # New - supports switch, light, fan, input_boolean
CONF_MANUAL_DEVICES: Final = "manual_devices"  # New - supports switch, light, fan, input_boolean

# Supported device domains for auto/manual control
AUTO_MANUAL_SUPPORTED_DOMAINS: Final = ["switch", "light", "fan", "input_boolean"]

# Light capabilities
LIGHT_CAPABILITY_BASIC: Final = "basic"
LIGHT_CAPABILITY_BRIGHTNESS: Final = "brightness"
LIGHT_CAPABILITY_FULL: Final = "full"

# === v3.2.2.5: NIGHT LIGHT CONFIGURATION ===
# Night lights are a subset of CONF_LIGHTS used during sleep hours
CONF_NIGHT_LIGHTS: Final = "night_lights"
CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS: Final = "night_light_sleep_brightness"
CONF_NIGHT_LIGHT_SLEEP_COLOR: Final = "night_light_sleep_color"
CONF_NIGHT_LIGHT_DAY_BRIGHTNESS: Final = "night_light_day_brightness"
CONF_NIGHT_LIGHT_DAY_COLOR: Final = "night_light_day_color"

# Night light defaults
DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS: Final = 15  # 15% during sleep
DEFAULT_NIGHT_LIGHT_SLEEP_COLOR: Final = 2000  # Warm red (Kelvin)
DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS: Final = 100  # Full brightness
DEFAULT_NIGHT_LIGHT_DAY_COLOR: Final = 4000  # Cool white (Kelvin)

# Cover types
COVER_TYPE_SHADE: Final = "shade"
COVER_TYPE_TILT: Final = "tilt"

# --- Step 4: Automation Behavior ---
# Lighting
CONF_ENTRY_LIGHT_ACTION: Final = "entry_light_action"
CONF_EXIT_LIGHT_ACTION: Final = "exit_light_action"
CONF_ILLUMINANCE_THRESHOLD: Final = "illuminance_dark_threshold"
CONF_LIGHT_BRIGHTNESS_PCT: Final = "light_brightness_pct"
CONF_LIGHT_TRANSITION_ON: Final = "light_transition_seconds_on"
CONF_LIGHT_TRANSITION_OFF: Final = "light_transition_seconds_off"

# Light actions
LIGHT_ACTION_NONE: Final = "none"
LIGHT_ACTION_TURN_ON: Final = "turn_on"
LIGHT_ACTION_TURN_ON_IF_DARK: Final = "turn_on_if_dark"
LIGHT_ACTION_TURN_OFF: Final = "turn_off"
LIGHT_ACTION_LEAVE_ON: Final = "leave_on"

# Covers
CONF_ENTRY_COVER_ACTION: Final = "entry_cover_action"
CONF_EXIT_COVER_ACTION: Final = "exit_cover_action"
CONF_OPEN_TIMING_MODE: Final = "open_timing_mode"
CONF_OPEN_TIME_START: Final = "open_time_start"
CONF_OPEN_TIME_END: Final = "open_time_end"
CONF_SUNRISE_OFFSET: Final = "sunrise_offset"
CONF_CLOSE_TIMING_MODE: Final = "close_timing_mode"
CONF_CLOSE_TIME: Final = "close_time"
CONF_SUNSET_OFFSET: Final = "sunset_offset"
CONF_TIMED_CLOSE_ENABLED: Final = "timed_close_enabled"

# Cover actions (legacy — kept for backwards compat)
COVER_ACTION_NONE: Final = "none"
COVER_ACTION_ALWAYS: Final = "always"
COVER_ACTION_SMART: Final = "smart"
COVER_ACTION_AFTER_SUNSET: Final = "after_sunset"

# v3.6.39: Cover open modes (replaces entry_cover_action + open_timing_mode)
CONF_COVER_OPEN_MODE: Final = "cover_open_mode"
COVER_OPEN_NONE: Final = "none"
COVER_OPEN_ON_ENTRY: Final = "on_entry"
COVER_OPEN_AT_TIME: Final = "at_time"
COVER_OPEN_ON_ENTRY_AFTER_TIME: Final = "on_entry_after_time"
COVER_OPEN_AT_TIME_OR_ON_ENTRY: Final = "at_time_or_on_entry"

# v3.6.39: Cover open time source
CONF_COVER_OPEN_TIME_SOURCE: Final = "cover_open_time_source"
TIME_SOURCE_SUNRISE: Final = "sunrise"
TIME_SOURCE_SPECIFIC_HOUR: Final = "specific_hour"
CONF_COVER_OPEN_HOUR: Final = "cover_open_hour"
DEFAULT_COVER_OPEN_HOUR: Final = 7

# v3.6.39: Cover close time source
CONF_COVER_CLOSE_TIME_SOURCE: Final = "cover_close_time_source"
TIME_SOURCE_SUNSET: Final = "sunset"
CONF_COVER_CLOSE_HOUR: Final = "cover_close_hour"
DEFAULT_COVER_CLOSE_HOUR: Final = 21

# Cover timing modes (legacy — kept for backwards compat)
TIMING_MODE_SUN: Final = "sun"
TIMING_MODE_TIME: Final = "time"
TIMING_MODE_BOTH_LATEST: Final = "both_latest"
TIMING_MODE_BOTH_EARLIEST: Final = "both_earliest"

# --- Step 5: Climate & HVAC ---
CONF_CLIMATE_ENTITY: Final = "climate_entity"
CONF_HVAC_COORDINATION_ENABLED: Final = "hvac_coordination_enabled"
CONF_TARGET_TEMP_COOL: Final = "target_temp_cool"
CONF_TARGET_TEMP_HEAT: Final = "target_temp_heat"
CONF_FAN_CONTROL_ENABLED: Final = "fan_control_enabled"
CONF_FAN_TEMP_THRESHOLD: Final = "fan_temp_threshold"
CONF_FAN_SPEED_LOW_TEMP: Final = "fan_speed_low_temp"
CONF_FAN_SPEED_MED_TEMP: Final = "fan_speed_med_temp"
CONF_FAN_SPEED_HIGH_TEMP: Final = "fan_speed_high_temp"
CONF_HUMIDITY_FAN_THRESHOLD: Final = "humidity_fan_threshold"
CONF_HUMIDITY_FAN_TIMEOUT: Final = "humidity_fan_timeout"
CONF_HVAC_EFFICIENCY_ALERTS: Final = "hvac_efficiency_alerts"
CONF_FAN_VACANCY_HOLD: Final = "fan_vacancy_hold"

# --- Step 6: Sleep Protection ---
CONF_SLEEP_PROTECTION_ENABLED: Final = "sleep_protection_enabled"
CONF_SLEEP_START_HOUR: Final = "sleep_start_hour"
CONF_SLEEP_END_HOUR: Final = "sleep_end_hour"
CONF_SLEEP_BYPASS_MOTION: Final = "sleep_bypass_motion_count"
CONF_SLEEP_BLOCK_COVERS: Final = "sleep_block_covers"
CONF_FAN_SLEEP_POLICY: Final = "fan_sleep_policy"
FAN_SLEEP_OFF: Final = "off"
FAN_SLEEP_REDUCE: Final = "reduce"
FAN_SLEEP_NORMAL: Final = "normal"
DEFAULT_FAN_SLEEP_POLICY: Final = "reduce"

# --- Step 7: Energy Monitoring ---
CONF_POWER_SENSORS: Final = "power_sensors"
CONF_ENERGY_SENSOR: Final = "energy_sensor"
CONF_ELECTRICITY_RATE: Final = "electricity_rate"
CONF_NOTIFY_DAILY_ENERGY: Final = "notify_daily_energy_summary"

# --- Step 8: Notifications ---
CONF_NOTIFY_SERVICE: Final = "notification_service"
CONF_NOTIFY_TARGET: Final = "notification_target"
CONF_NOTIFY_LEVEL: Final = "notification_level"

# Notification levels
NOTIFY_LEVEL_OFF: Final = "off"
NOTIFY_LEVEL_ERRORS: Final = "errors"
NOTIFY_LEVEL_IMPORTANT: Final = "important"
NOTIFY_LEVEL_ALL: Final = "all"

# --- Integration-Level (Shared) ---
CONF_OUTSIDE_TEMP_SENSOR: Final = "outside_temp_sensor"
CONF_OUTSIDE_HUMIDITY_SENSOR: Final = "outside_humidity_sensor"
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_SOLAR_PRODUCTION_SENSOR: Final = "solar_production_sensor"
CONF_ELECTRICITY_RATE_SENSOR: Final = "electricity_rate_sensor"

# ============================================================================
# DEFAULT VALUES
# ============================================================================

DEFAULT_OCCUPANCY_TIMEOUT: Final = 300  # 5 minutes
DEFAULT_DARK_THRESHOLD: Final = 20      # lux (from blueprint v3.5.1)
DEFAULT_SCAN_INTERVAL: Final = 30       # seconds
DEFAULT_ELECTRICITY_RATE: Final = 0.15  # $/kWh

# Lighting defaults
DEFAULT_LIGHT_BRIGHTNESS: Final = 100  # %
DEFAULT_LIGHT_TRANSITION_ON: Final = 1  # seconds
DEFAULT_LIGHT_TRANSITION_OFF: Final = 3  # seconds

# Climate defaults
DEFAULT_TARGET_TEMP_COOL: Final = 76  # °F
DEFAULT_TARGET_TEMP_HEAT: Final = 68  # °F
DEFAULT_FAN_TEMP_THRESHOLD: Final = 80  # °F
DEFAULT_FAN_SPEED_LOW: Final = 69  # °F
DEFAULT_FAN_SPEED_MED: Final = 72  # °F
DEFAULT_FAN_SPEED_HIGH: Final = 75  # °F
DEFAULT_HUMIDITY_THRESHOLD: Final = 60  # %
DEFAULT_HUMIDITY_FAN_TIMEOUT: Final = 600  # 10 minutes
DEFAULT_FAN_VACANCY_HOLD: Final = 300  # 5 minutes extra after occupancy timeout

# Cover defaults
DEFAULT_OPEN_TIME_START: Final = 7  # 7 AM
DEFAULT_OPEN_TIME_END: Final = 20  # 8 PM
DEFAULT_CLOSE_TIME: Final = 21  # 9 PM
DEFAULT_SUNRISE_OFFSET: Final = 0  # minutes
DEFAULT_SUNSET_OFFSET: Final = 0  # minutes

# Sleep protection defaults
DEFAULT_SLEEP_START: Final = 22  # 10 PM
DEFAULT_SLEEP_END: Final = 7  # 7 AM
DEFAULT_SLEEP_BYPASS_COUNT: Final = 3  # motion events needed to bypass

# Room type timeout defaults
ROOM_TYPE_TIMEOUTS: Final = {
    ROOM_TYPE_BEDROOM: 900,      # 15 minutes
    ROOM_TYPE_CLOSET: 120,       # 2 minutes
    ROOM_TYPE_BATHROOM: 300,     # 5 minutes
    ROOM_TYPE_MEDIA_ROOM: 1800,  # 30 minutes
    ROOM_TYPE_GARAGE: 600,       # 10 minutes
    ROOM_TYPE_UTILITY: 600,      # 10 minutes
    ROOM_TYPE_COMMON_AREA: 900,  # 15 minutes
    ROOM_TYPE_GENERIC: 300,      # 5 minutes
}

# ============================================================================
# STATE KEYS (for coordinator data)
# ============================================================================

# Phase 1: Core
STATE_OCCUPIED: Final = "occupied"
STATE_MOTION_DETECTED: Final = "motion_detected"
STATE_PRESENCE_DETECTED: Final = "presence_detected"
STATE_TEMPERATURE: Final = "temperature"
STATE_HUMIDITY: Final = "humidity"
STATE_ILLUMINANCE: Final = "illuminance"
STATE_DARK: Final = "dark"
STATE_TIMEOUT_REMAINING: Final = "timeout_remaining"
STATE_BLE_PERSONS: Final = "ble_persons"
STATE_OCCUPANCY_SOURCE: Final = "occupancy_source"

# Phase 2: Energy
STATE_POWER_CURRENT: Final = "power_current"
STATE_ENERGY_TODAY: Final = "energy_today"
STATE_ENERGY_COST_TODAY: Final = "energy_cost_today"
STATE_ENERGY_MONTHLY: Final = "energy_monthly"
STATE_ENERGY_COST_MONTHLY: Final = "energy_cost_monthly"
STATE_ENERGY_WEEKLY: Final = "energy_weekly"
STATE_ENERGY_COST_WEEKLY: Final = "energy_cost_weekly"
STATE_COST_PER_HOUR: Final = "cost_per_hour"
STATE_LIGHTS_ON_COUNT: Final = "lights_on_count"
STATE_FANS_ON_COUNT: Final = "fans_on_count"
STATE_SWITCHES_ON_COUNT: Final = "switches_on_count"
STATE_COVERS_OPEN_COUNT: Final = "covers_open_count"
STATE_COVERS_POSITION_AVG: Final = "covers_position_avg"

# Phase 3: Predictions
STATE_NEXT_OCCUPANCY_TIME: Final = "next_occupancy_time"
STATE_NEXT_OCCUPANCY_IN: Final = "next_occupancy_in"
STATE_OCCUPANCY_PCT_7D: Final = "occupancy_percentage_7d"
STATE_PEAK_OCCUPANCY_TIME: Final = "peak_occupancy_time"
STATE_PRECOOL_START_TIME: Final = "precool_start_time"
STATE_PREHEAT_START_TIME: Final = "preheat_start_time"
STATE_PRECOOL_LEAD_MINUTES: Final = "precool_lead_minutes"
STATE_PREHEAT_LEAD_MINUTES: Final = "preheat_lead_minutes"

# Phase 4: Advanced
STATE_COMFORT_SCORE: Final = "comfort_score"
STATE_ENERGY_EFFICIENCY_SCORE: Final = "energy_efficiency_score"
STATE_ENERGY_WASTE_IDLE: Final = "energy_waste_idle"
STATE_TIME_SINCE_MOTION: Final = "time_since_motion"
STATE_TIME_SINCE_OCCUPIED: Final = "time_since_last_occupied"
STATE_DAYS_SINCE_OCCUPIED: Final = "days_since_occupied"
STATE_TIME_IN_COMFORT: Final = "time_in_comfort_zone_today"
STATE_TIME_UNCOMFORTABLE: Final = "time_uncomfortable_today"
STATE_OCCUPANCY_PATTERN: Final = "occupancy_pattern_detected"
STATE_OCCUPANCY_CONFIDENCE: Final = "occupancy_confidence"
STATE_LAST_TRIGGER_SOURCE: Final = "last_trigger_source"
STATE_LAST_TRIGGER_ENTITY: Final = "last_trigger_entity"
STATE_LAST_TRIGGER_TIME: Final = "last_trigger_time"
STATE_LAST_ACTION_DESCRIPTION: Final = "last_action_description"
STATE_LAST_ACTION_ENTITY: Final = "last_action_entity"
STATE_LAST_ACTION_TYPE: Final = "last_action_type"
STATE_LAST_ACTION_TIME: Final = "last_action_time"
STATE_LAST_ACTION_DEVICES: Final = "last_action_devices"
STATE_LAST_ACTION_RESULT: Final = "last_action_result"
STATE_LAST_ACTION_TRIGGER: Final = "last_action_trigger"

# Automation state
STATE_SLEEP_MODE_ACTIVE: Final = "sleep_mode_active"
STATE_HVAC_COORDINATED: Final = "hvac_coordinated"

# ============================================================================
# ATTRIBUTE KEYS
# ============================================================================

ATTR_LAST_MOTION: Final = "last_motion"
ATTR_LAST_CHANGED: Final = "last_changed"
ATTR_TIMEOUT: Final = "timeout"
ATTR_SENSOR_COUNT: Final = "sensor_count"
ATTR_CONFIDENCE: Final = "confidence"
ATTR_CONFIDENCE_LEVEL: Final = "confidence_level"
ATTR_BASED_ON: Final = "based_on"
ATTR_PREDICTION_TIME: Final = "prediction_time"
ATTR_DEVICES: Final = "devices"
ATTR_UNAVAILABLE: Final = "unavailable_entities"
ATTR_ISSUES: Final = "configuration_issues"
ATTR_AUTOMATION_ENABLED: Final = "automation_enabled"
ATTR_LAST_TRIGGERED: Final = "last_triggered"
ATTR_DATA_DAYS: Final = "data_days"
ATTR_METHOD: Final = "method"
ATTR_VALUE: Final = "value"
ATTR_UNIT: Final = "unit"

# v3.2.8: Path tracking attribute
ATTR_RECENT_PATH: Final = "recent_path"
ATTR_TRACKING_STATUS: Final = "tracking_status"
ATTR_LAST_BERMUDA_UPDATE: Final = "last_bermuda_update"
ATTR_PREVIOUS_LOCATION_TIME: Final = "previous_location_time"

# ============================================================================
# DEVICE INFO
# ============================================================================

MANUFACTURER: Final = "Universal Room Automation"
MODEL: Final = "Smart Room"

# ============================================================================
# ICON MAPPINGS
# ============================================================================

# Phase 1: Core
ICON_OCCUPIED: Final = "mdi:home-account"
ICON_VACANT: Final = "mdi:home-outline"
ICON_MOTION: Final = "mdi:motion-sensor"
ICON_PRESENCE: Final = "mdi:account-details"
ICON_TEMPERATURE: Final = "mdi:thermometer"
ICON_HUMIDITY: Final = "mdi:water-percent"
ICON_ILLUMINANCE: Final = "mdi:brightness-6"
ICON_TIMEOUT: Final = "mdi:timer-sand"
ICON_DARK: Final = "mdi:weather-night"

# Phase 2: Energy
ICON_POWER: Final = "mdi:flash"
ICON_ENERGY: Final = "mdi:lightning-bolt"
ICON_COST: Final = "mdi:currency-usd"
ICON_DEVICES: Final = "mdi:devices"

# Phase 3: Predictions
ICON_PREDICTION: Final = "mdi:crystal-ball"
ICON_OCCUPANCY_FORECAST: Final = "mdi:calendar-clock"
ICON_PRECONDITIONING: Final = "mdi:thermostat-auto"

# Phase 4: Advanced
ICON_COMFORT: Final = "mdi:home-heart"
ICON_EFFICIENCY: Final = "mdi:leaf"
ICON_PATTERN: Final = "mdi:chart-line"
ICON_ANOMALY: Final = "mdi:alert-circle"
ICON_DIAGNOSTIC: Final = "mdi:information"
ICON_CONFIG_STATUS: Final = "mdi:check-circle"
ICON_LAST_TRIGGER: Final = "mdi:history"
ICON_LAST_ACTION: Final = "mdi:robot"
ICON_ROOM_ALERT: Final = "mdi:alert-circle"

# v3.1.6: Energy icons
ICON_HVAC_DIRECTION: Final = "mdi:hvac"
ICON_COOLING: Final = "mdi:snowflake"
ICON_HEATING: Final = "mdi:fire"
ICON_SOLAR: Final = "mdi:solar-power"
ICON_BATTERY: Final = "mdi:battery"
ICON_GRID: Final = "mdi:transmission-tower"
ICON_COVERAGE: Final = "mdi:chart-pie"

# v3.2.0.1: Person tracking icons
ICON_PERSON: Final = "mdi:account"
ICON_PERSON_LOCATION: Final = "mdi:account-arrow-right"
ICON_OCCUPANTS: Final = "mdi:account-multiple"

# v3.2.8: Tracking status icons
ICON_TRACKING_ACTIVE: Final = "mdi:account-check"
ICON_TRACKING_STALE: Final = "mdi:account-clock"
ICON_TRACKING_LOST: Final = "mdi:account-off"

# Automation
ICON_SLEEP_MODE: Final = "mdi:sleep"
ICON_HVAC_COORD: Final = "mdi:hvac"
ICON_RECONFIGURE: Final = "mdi:cog-refresh"

# ============================================================================
# DATABASE
# ============================================================================

DATABASE_DIR: Final = "universal_room_automation/data"
DATABASE_NAME: Final = "universal_room_automation.db"

# Data retention (days)
RETENTION_DETAILED: Final = 7    # Keep all events for 7 days
RETENTION_AGGREGATED: Final = 30  # Keep hourly summaries for 30 days
RETENTION_ARCHIVE: Final = 365    # Keep daily summaries for 1 year
RETENTION_PREDICTIONS: Final = 365 # Keep all predictions for learning
RETENTION_DEBUG: Final = 30       # Keep debug events for 30 days
RETENTION_ENERGY_HISTORY: Final = 90  # v3.1.6: Energy history for predictions

# ============================================================================
# COMFORT & ENERGY THRESHOLDS
# ============================================================================

# Comfort thresholds (defaults)
COMFORT_TEMP_MIN: Final = 68  # °F
COMFORT_TEMP_MAX: Final = 76  # °F
COMFORT_HUMIDITY_MIN: Final = 30  # %
COMFORT_HUMIDITY_MAX: Final = 60  # %

# Energy thresholds
IDLE_POWER_THRESHOLD: Final = 5  # Watts (below this is considered idle waste)

# HVAC direction thresholds
HVAC_COOLING_THRESHOLD: Final = 5  # degrees above comfort max
HVAC_HEATING_THRESHOLD: Final = 5  # degrees below comfort min

# HVAC Zone Preset Triggers (v3.3.5.9)
CONF_ZONE_THERMOSTAT: Final = "zone_thermostat"  # v3.6.23: Zone-level climate entity
CONF_ZONE_VACANT_PRESET: Final = "zone_vacant_preset"
CONF_ZONE_OCCUPIED_PRESET: Final = "zone_occupied_preset"
DEFAULT_ZONE_VACANT_PRESET: Final = "away"
DEFAULT_ZONE_OCCUPIED_PRESET: Final = "home"
HVAC_PRESET_SKIP: Final = ("manual", "sleep")

# Alert type to color mapping
ALERT_TYPE_COLORS: Final = {
    "water_leak": ALERT_COLOR_RED,
    "temperature": ALERT_COLOR_AMBER,
    "humidity": ALERT_COLOR_BLUE,
    "security": ALERT_COLOR_RED,
    "safety": ALERT_COLOR_AMBER,
}

# ============================================================================
# v3.5.0 Camera Census
# ============================================================================

CONF_CAMERA_PERSON_ENTITIES: Final = "camera_person_entities"
CONF_EGRESS_CAMERAS: Final = "egress_cameras"
CONF_PERIMETER_CAMERAS: Final = "perimeter_cameras"
CONF_CAMERA_PLATFORM: Final = "camera_platform"

SCAN_INTERVAL_CENSUS: Final = timedelta(seconds=30)

CAMERA_PLATFORM_FRIGATE: Final = "frigate"
CAMERA_PLATFORM_UNIFI: Final = "unifiprotect"

CENSUS_CONFIDENCE_HIGH: Final = "high"
CENSUS_CONFIDENCE_MEDIUM: Final = "medium"
CENSUS_CONFIDENCE_LOW: Final = "low"
CENSUS_CONFIDENCE_NONE: Final = "none"

CENSUS_AGREEMENT_BOTH: Final = "both_agree"
CENSUS_AGREEMENT_CLOSE: Final = "close"
CENSUS_AGREEMENT_DISAGREE: Final = "disagree"
CENSUS_AGREEMENT_SINGLE: Final = "single_source"

CONF_CENSUS_CROSS_VALIDATION: Final = "census_cross_validation"

# ============================================================================
# v3.5.1 Perimeter Alerting & Zone Aggregation
# ============================================================================

# Perimeter alert config keys
CONF_PERIMETER_ALERT_HOURS_START: Final = "perimeter_alert_hours_start"
CONF_PERIMETER_ALERT_HOURS_END: Final = "perimeter_alert_hours_end"
CONF_PERIMETER_ALERT_NOTIFY_SERVICE: Final = "perimeter_alert_notify_service"
CONF_PERIMETER_ALERT_NOTIFY_TARGET: Final = "perimeter_alert_notify_target"

# Perimeter alert defaults
DEFAULT_PERIMETER_ALERT_START: Final = 23   # 11 PM
DEFAULT_PERIMETER_ALERT_END: Final = 5      # 5 AM
PERIMETER_ALERT_COOLDOWN_SECONDS: Final = 300  # 5 minutes

# Zone aggregation sensor keys
SENSOR_ZONE_IDENTIFIED_PERSONS: Final = "zone_identified_persons"
SENSOR_ZONE_GUEST_COUNT: Final = "zone_guest_count"

# ============================================================================
# v3.5.2 Transit Validation
# ============================================================================

TRANSIT_CHECKPOINT_STALE_SECONDS: Final = 90
TRANSIT_CHECKPOINT_WINDOW_SECONDS: Final = 120
TRANSIT_PHONE_LEFT_BEHIND_HOURS: Final = 4.0

# v3.5.2 Egress Direction Tracking
EGRESS_ENTRY_WINDOW_SECONDS: Final = 45
EGRESS_EXIT_WINDOW_SECONDS: Final = 30
EGRESS_AMBIGUOUS_COOLDOWN_SECONDS: Final = 60

# v3.5.2 Census Mismatch
CENSUS_MISMATCH_THRESHOLD: Final = 2
CENSUS_MISMATCH_DURATION_MINUTES: Final = 10

# v3.5.2 Face Recognition
CONF_FACE_RECOGNITION_ENABLED: Final = "face_recognition_enabled"

# ============================================================================
# v3.6.0 Domain Coordinators
# ============================================================================

# Config toggle for domain coordinator system
CONF_DOMAIN_COORDINATORS_ENABLED: Final = "domain_coordinators_enabled"

# Data retention for coordinator logs (days)
RETENTION_DECISION_LOG: Final = 90
RETENTION_COMPLIANCE_LOG: Final = 90
RETENTION_HOUSE_STATE_LOG: Final = 365
RETENTION_ANOMALY_LOG: Final = 90
RETENTION_OUTCOME_LOG: Final = 365
RETENTION_PARAMETER_HISTORY: Final = 365

# v3.6.0-c0.4: Per-coordinator enable/disable config keys
CONF_PRESENCE_ENABLED: Final = "presence_coordinator_enabled"
CONF_SAFETY_ENABLED: Final = "safety_coordinator_enabled"
CONF_SECURITY_ENABLED: Final = "security_coordinator_enabled"
CONF_ENERGY_ENABLED: Final = "energy_coordinator_enabled"
CONF_HVAC_ENABLED: Final = "hvac_coordinator_enabled"
CONF_COMFORT_ENABLED: Final = "comfort_coordinator_enabled"
CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED: Final = "music_following_coordinator_enabled"

# Mapping coordinator_id -> config key for enable/disable
COORDINATOR_ENABLED_KEYS: Final = {
    "presence": "presence_coordinator_enabled",
    "safety": "safety_coordinator_enabled",
    "security": "security_coordinator_enabled",
    "energy": "energy_coordinator_enabled",
    "hvac": "hvac_coordinator_enabled",
    "comfort": "comfort_coordinator_enabled",
    "music_following": "music_following_coordinator_enabled",
    "notification_manager": "notification_manager_enabled",
}

# v3.6.0-c0.4: Diagnostics constants
DIAGNOSTICS_SCOPE_HOUSE: Final = "house"

# v3.6.0-c1: Presence Coordinator constants
CONF_SLEEP_START_HOUR: Final = "sleep_start_hour"
CONF_SLEEP_END_HOUR: Final = "sleep_end_hour"
CONF_GEOFENCE_ENTITIES: Final = "geofence_entities"
DEFAULT_SLEEP_START_HOUR: Final = 23
DEFAULT_SLEEP_END_HOUR: Final = 6

# v3.6.0-c2.1: Safety Coordinator config constants
CONF_WATER_SHUTOFF_VALVE: Final = "water_shutoff_valve"
CONF_EMERGENCY_LIGHT_ENTITIES: Final = "emergency_light_entities"

# v3.6.0.3: Global safety device selectors for scoped discovery
CONF_GLOBAL_SMOKE_SENSORS: Final = "global_smoke_sensors"
CONF_GLOBAL_LEAK_SENSORS: Final = "global_leak_sensors"
CONF_GLOBAL_AQ_SENSORS: Final = "global_aq_sensors"
CONF_GLOBAL_TEMP_SENSORS: Final = "global_temp_sensors"
CONF_GLOBAL_HUMIDITY_SENSORS: Final = "global_humidity_sensors"

# v3.6.0-c3: Security Coordinator config constants
CONF_SECURITY_LOCK_ENTITIES: Final = "security_lock_entities"
CONF_SECURITY_GARAGE_ENTITIES: Final = "security_garage_entities"
CONF_SECURITY_ENTRY_SENSORS: Final = "security_entry_sensors"
CONF_SECURITY_LIGHT_ENTITIES: Final = "security_light_entities"
CONF_SECURITY_CAMERA_ENTITIES: Final = "security_camera_entities"
CONF_SECURITY_CAMERA_RECORDING: Final = "security_camera_recording"
CONF_SECURITY_CAMERA_RECORD_DURATION: Final = "security_camera_record_duration"
CONF_SECURITY_ALARM_PANEL: Final = "security_alarm_panel"
CONF_SECURITY_AUTO_FOLLOW: Final = "security_auto_follow"
CONF_SECURITY_LOCK_CHECK_INTERVAL: Final = "security_lock_check_interval"
CONF_SECURITY_DELEGATE_LIGHTS_TO_NM: Final = "security_delegate_lights_to_nm"

# Zone presence mode values
ZONE_MODE_AWAY: Final = "away"
ZONE_MODE_OCCUPIED: Final = "occupied"
ZONE_MODE_SLEEP: Final = "sleep"
ZONE_MODE_UNKNOWN: Final = "unknown"
ZONE_MODE_AUTO: Final = "auto"

# House state override options (all 9 states + auto)
HOUSE_STATE_OVERRIDE_OPTIONS: Final = [
    "auto", "away", "arriving", "home_day", "home_evening",
    "home_night", "sleep", "waking", "guest", "vacation",
]
ZONE_PRESENCE_OVERRIDE_OPTIONS: Final = ["auto", "away", "occupied", "sleep"]

# ============================================================================
# v3.6.19 Music Following Hardening
# ============================================================================

# Bermuda area sensor config override (optional per-person dict)
CONF_BERMUDA_AREA_SENSORS: Final = "bermuda_area_sensors"

# Transfer cooldown (seconds) — blocks repeated transfers to same target
MUSIC_TRANSFER_COOLDOWN_SECONDS: Final = 8

# Ping-pong suppression window (seconds) — suppress A→B→A return leg
PING_PONG_WINDOW_SECONDS: Final = 60

# Post-transfer verification delay (seconds)
TRANSFER_VERIFY_DELAY_SECONDS: Final = 2

# Speaker group unjoin delay (seconds)
GROUP_UNJOIN_DELAY_SECONDS: Final = 5

# ============================================================================
# v3.6.24 Music Following Coordinator — configurable tuning parameters
# ============================================================================

CONF_MF_COOLDOWN_SECONDS: Final = "mf_cooldown_seconds"
CONF_MF_PING_PONG_WINDOW: Final = "mf_ping_pong_window"
CONF_MF_VERIFY_DELAY: Final = "mf_verify_delay"
CONF_MF_UNJOIN_DELAY: Final = "mf_unjoin_delay"
CONF_MF_POSITION_OFFSET: Final = "mf_position_offset"
CONF_MF_MIN_CONFIDENCE: Final = "mf_min_confidence"
CONF_MF_HIGH_CONFIDENCE_DISTANCE: Final = "mf_high_confidence_distance"

DEFAULT_MF_COOLDOWN_SECONDS: Final = 8
DEFAULT_MF_PING_PONG_WINDOW: Final = 60
DEFAULT_MF_VERIFY_DELAY: Final = 2
DEFAULT_MF_UNJOIN_DELAY: Final = 5
DEFAULT_MF_POSITION_OFFSET: Final = 3
DEFAULT_MF_MIN_CONFIDENCE: Final = 0.6
DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE: Final = 8.0  # feet — tighter than person tracking (10ft)

# ============================================================================
# v3.6.29 Notification Manager
# ============================================================================

CONF_NM_ENABLED: Final = "notification_manager_enabled"

# Channel enable/severity keys
CONF_NM_PUSHOVER_ENABLED: Final = "nm_pushover_enabled"
CONF_NM_PUSHOVER_SEVERITY: Final = "nm_pushover_severity"
CONF_NM_PUSHOVER_SERVICE: Final = "nm_pushover_service"
CONF_NM_COMPANION_ENABLED: Final = "nm_companion_enabled"
CONF_NM_COMPANION_SEVERITY: Final = "nm_companion_severity"
CONF_NM_WHATSAPP_ENABLED: Final = "nm_whatsapp_enabled"
CONF_NM_WHATSAPP_SEVERITY: Final = "nm_whatsapp_severity"
CONF_NM_IMESSAGE_ENABLED: Final = "nm_imessage_enabled"
CONF_NM_IMESSAGE_SEVERITY: Final = "nm_imessage_severity"
CONF_NM_TTS_ENABLED: Final = "nm_tts_enabled"
CONF_NM_TTS_SEVERITY: Final = "nm_tts_severity"
CONF_NM_TTS_SPEAKERS: Final = "nm_tts_speakers"
CONF_NM_LIGHTS_ENABLED: Final = "nm_lights_enabled"
CONF_NM_LIGHTS_SEVERITY: Final = "nm_lights_severity"
CONF_NM_ALERT_LIGHTS: Final = "nm_alert_lights"

# Person config keys
CONF_NM_PERSONS: Final = "nm_persons"
CONF_NM_PERSON_ENTITY: Final = "nm_person_entity"
CONF_NM_PERSON_PUSHOVER_KEY: Final = "nm_person_pushover_key"
CONF_NM_PERSON_PUSHOVER_DEVICE: Final = "nm_person_pushover_device"
CONF_NM_PERSON_COMPANION_SERVICE: Final = "nm_person_companion_service"
CONF_NM_PERSON_WHATSAPP_PHONE: Final = "nm_person_whatsapp_phone"
CONF_NM_PERSON_IMESSAGE_HANDLE: Final = "nm_person_imessage_handle"
CONF_NM_PERSON_DELIVERY_PREF: Final = "nm_person_delivery_pref"
CONF_NM_PERSON_DIGEST_MORNING: Final = "nm_person_digest_morning"
CONF_NM_PERSON_DIGEST_EVENING_ENABLED: Final = "nm_person_digest_evening_enabled"
CONF_NM_PERSON_DIGEST_EVENING: Final = "nm_person_digest_evening"

# Quiet hours keys
CONF_NM_QUIET_USE_HOUSE_STATE: Final = "nm_quiet_use_house_state"
CONF_NM_QUIET_MANUAL_START: Final = "nm_quiet_manual_start"
CONF_NM_QUIET_MANUAL_END: Final = "nm_quiet_manual_end"

# Cooldown keys (per hazard type, in minutes)
CONF_NM_COOLDOWN_SMOKE: Final = "nm_cooldown_smoke"
CONF_NM_COOLDOWN_CO: Final = "nm_cooldown_co"
CONF_NM_COOLDOWN_FLOODING: Final = "nm_cooldown_flooding"
CONF_NM_COOLDOWN_WATER_LEAK: Final = "nm_cooldown_water_leak"
CONF_NM_COOLDOWN_FREEZE: Final = "nm_cooldown_freeze"
CONF_NM_COOLDOWN_INTRUSION: Final = "nm_cooldown_intrusion"
CONF_NM_COOLDOWN_DEFAULT: Final = "nm_cooldown_default"

# Delivery preference values
NM_DELIVERY_IMMEDIATE: Final = "immediate"
NM_DELIVERY_DIGEST: Final = "digest"
NM_DELIVERY_OFF: Final = "off"

# Default severity thresholds per channel
DEFAULT_NM_PUSHOVER_SEVERITY: Final = "MEDIUM"
DEFAULT_NM_COMPANION_SEVERITY: Final = "HIGH"
DEFAULT_NM_WHATSAPP_SEVERITY: Final = "HIGH"
DEFAULT_NM_IMESSAGE_SEVERITY: Final = "HIGH"
DEFAULT_NM_TTS_SEVERITY: Final = "CRITICAL"
DEFAULT_NM_LIGHTS_SEVERITY: Final = "HIGH"

# Default cooldowns (minutes)
DEFAULT_NM_COOLDOWN_SMOKE: Final = 2
DEFAULT_NM_COOLDOWN_CO: Final = 2
DEFAULT_NM_COOLDOWN_FLOODING: Final = 5
DEFAULT_NM_COOLDOWN_WATER_LEAK: Final = 10
DEFAULT_NM_COOLDOWN_FREEZE: Final = 15
DEFAULT_NM_COOLDOWN_INTRUSION: Final = 3
DEFAULT_NM_COOLDOWN_DEFAULT: Final = 10

# Dedup windows (seconds) per severity
NM_DEDUP_CRITICAL: Final = 60
NM_DEDUP_HIGH: Final = 300
NM_DEDUP_MEDIUM: Final = 900
NM_DEDUP_LOW: Final = 3600

# Repeat interval for CRITICAL alerts (seconds)
NM_CRITICAL_REPEAT_INTERVAL: Final = 30

# v3.9.7 C4b: Inbound / Safe Word
CONF_NM_SAFE_WORD: Final = "nm_safe_word"
CONF_NM_SILENCE_DURATION: Final = "nm_silence_duration"
DEFAULT_NM_SILENCE_DURATION: Final = 30  # minutes

# v3.9.8 C4b+: BlueBubbles/iMessage webhook
WEBHOOK_BB_ID: Final = f"{DOMAIN}_bluebubbles_reply"

# DB retention (days)
RETENTION_NOTIFICATION_LOG: Final = 30

# v3.10.0: Automation Chaining
CONF_AUTOMATION_CHAINS: Final = "automation_chains"

# v3.10.0: Lux trigger thresholds
LUX_DARK_THRESHOLD: Final = 50       # Below = dark (triggers lux_dark)
LUX_BRIGHT_THRESHOLD: Final = 200    # Above = bright (triggers lux_bright)

# v3.10.0: Trigger type constants (M1 subset)
TRIGGER_ENTER: Final = "enter"
TRIGGER_EXIT: Final = "exit"
TRIGGER_LUX_DARK: Final = "lux_dark"
TRIGGER_LUX_BRIGHT: Final = "lux_bright"
AUTOMATION_CHAIN_TRIGGERS_M1: Final = [
    TRIGGER_ENTER, TRIGGER_EXIT, TRIGGER_LUX_DARK, TRIGGER_LUX_BRIGHT,
]

# v3.12.0: M2 Coordinator Signal Triggers
TRIGGER_HOUSE_STATE_PREFIX: Final = "house_state_"
TRIGGER_ENERGY_CONSTRAINT: Final = "energy_constraint"
TRIGGER_SAFETY_HAZARD: Final = "safety_hazard"
TRIGGER_SECURITY_EVENT: Final = "security_event"

# House state values for trigger generation (matches HouseState enum)
HOUSE_STATE_TRIGGER_VALUES: Final = [
    "away", "arriving", "home_day", "home_evening", "home_night",
    "sleep", "waking", "guest", "vacation",
]

# Full trigger list (M1 + M2)
AUTOMATION_CHAIN_TRIGGERS_M2: Final = [
    TRIGGER_ENTER, TRIGGER_EXIT, TRIGGER_LUX_DARK, TRIGGER_LUX_BRIGHT,
    *[f"{TRIGGER_HOUSE_STATE_PREFIX}{s}" for s in HOUSE_STATE_TRIGGER_VALUES],
    TRIGGER_ENERGY_CONSTRAINT,
    TRIGGER_SAFETY_HAZARD,
    TRIGGER_SECURITY_EVENT,
]

# Trigger groups for config flow sub-steps
CHAIN_GROUP_OCCUPANCY: Final = [TRIGGER_ENTER, TRIGGER_EXIT]
CHAIN_GROUP_LIGHT: Final = [TRIGGER_LUX_DARK, TRIGGER_LUX_BRIGHT]
CHAIN_GROUP_HOUSE_STATE: Final = [
    f"{TRIGGER_HOUSE_STATE_PREFIX}{s}" for s in HOUSE_STATE_TRIGGER_VALUES
]
CHAIN_GROUP_COORDINATOR: Final = [
    TRIGGER_ENERGY_CONSTRAINT, TRIGGER_SAFETY_HAZARD, TRIGGER_SECURITY_EVENT,
]

# ============================================================================
# v3.12.0 M3: AI NL Rules
# ============================================================================

CONF_AI_RULES: Final = "ai_rules"
CONF_AI_RULE_TRIGGER: Final = "ai_rule_trigger"
CONF_AI_RULE_PERSON: Final = "ai_rule_person"
CONF_AI_RULE_DESCRIPTION: Final = "ai_rule_description"

# All available trigger types for AI rules (same as M2 full list)
AI_RULE_TRIGGER_OPTIONS: Final = AUTOMATION_CHAIN_TRIGGERS_M2

AI_RULE_PARSING_PROMPT: Final = """You are a Home Assistant automation rule parser.

TASK: Convert a natural language rule into a list of Home Assistant service calls.

ROOM: {room_name}
TRIGGER: When {trigger_label}
RULE: {description}

AVAILABLE ENTITIES IN THIS ROOM:
{entities_json}

REQUIREMENTS:
- Only use entity_ids from the available entities list above.
- Each service call must have: domain, service, target (with entity_id), data.
- Use exact entity_ids as shown — do not invent entity IDs.
- If a device is mentioned but not in the list, omit it.
- data may be an empty object {{}} if no parameters needed.
- For lights: use color_temp_kelvin (integer), brightness_pct (0-100).
- For media_player: use volume_level (0.0-1.0).
- For climate: use temperature (number).

Output only valid JSON. No explanation text."""

# ============================================================================
# v3.10.1 Census v2: Event-Driven Sensor Fusion
# ============================================================================

# Master enable/disable
CONF_ENHANCED_CENSUS: Final = "enhanced_census"

# Hold/decay timing (defaults in seconds, configurable via UI in minutes)
CONF_CENSUS_HOLD_INTERIOR: Final = "census_hold_interior"
CONF_CENSUS_HOLD_EXTERIOR: Final = "census_hold_exterior"
DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES: Final = 15
DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES: Final = 5
CENSUS_DECAY_STEP_SECONDS: Final = 300  # -1 person per 5 min after hold expires

# Event-driven census
CENSUS_EVENT_DEBOUNCE_SECONDS: Final = 5  # Debounce rapid detection events

# Face recognition window (how long a Frigate face match stays "active")
CENSUS_FACE_RECOGNITION_WINDOW_SECONDS: Final = 1800  # 30 minutes

# WiFi guest VLAN detection
CONF_GUEST_VLAN_SSID: Final = "guest_vlan_ssid"
DEFAULT_GUEST_VLAN_SSID: Final = ""  # Empty = auto-detect via is_guest flag

# Phone manufacturer allowlist (OUI values from UniFi device_tracker)
PHONE_MANUFACTURERS: Final = frozenset({
    "Apple, Inc.",
    "Samsung Electronics Co.,Ltd",
    "Google, Inc.",
    "OnePlus Technology (Shenzhen) Co., Ltd",
    "Huawei Technologies Co.,Ltd",
    "Xiaomi Communications Co Ltd",
    "Motorola Mobility LLC, a Lenovo Company",
    "LG Electronics",
    "Sony Mobile Communications Inc",
    "OPPO",
    "vivo Mobile Communication Co., Ltd.",
    "Nothing Technology Limited",
    "Fairphone",
})
# Hostname patterns for phones with randomized MACs (empty OUI).
# Modern phones use private MAC addresses, stripping the OUI.
# Matching by hostname is the fallback — case-insensitive prefix match.
PHONE_HOSTNAME_PREFIXES: Final = (
    "iphone", "galaxy", "pixel", "oneplus", "huawei",
    "xiaomi", "redmi", "poco", "motorola", "nothing", "fairphone",
    "oppo", "vivo", "realme",
)
# OUI manufacturers that make ONLY phones (safe to match by OUI alone).
# Samsung is excluded because Samsung TVs share the same OUI.
# For Samsung phones, hostname fallback ("galaxy") is used instead.
PHONE_ONLY_MANUFACTURERS: Final = frozenset({
    "Apple, Inc.",
    "Google, Inc.",
    "OnePlus Technology (Shenzhen) Co., Ltd",
    "Huawei Technologies Co.,Ltd",
    "Xiaomi Communications Co Ltd",
    "Motorola Mobility LLC, a Lenovo Company",
    "Sony Mobile Communications Inc",
    "Nothing Technology Limited",
    "Fairphone",
})
# How recently a phone must have appeared on the SSID to count as a guest.
# Phones present longer than this are treated as residents (family devices).
# Cameras still catch long-staying guests via camera_unrecognized count.
WIFI_GUEST_RECENCY_HOURS: Final = 24
# Infrastructure device hostname prefixes — devices that are definitely NOT
# guest personal devices on a shared entertainment SSID. Everything that
# doesn't match these (and isn't a tablet) is a potential guest phone.
# Case-insensitive prefix match.
NON_GUEST_HOSTNAME_PREFIXES: Final = (
    "samsung",          # Samsung TVs (Galaxy phones use "Galaxy-*" or custom names)
    "homepod",          # Apple HomePods
    "wiim",             # WiiM speakers
    "sonos",            # Sonos speakers
    "trc-",             # URC universal remotes (TRC-1480 etc.)
    "urc",              # URC remotes (alternative naming)
    "espressif",        # ESP-based IoT devices
    "esp-", "esp_",     # ESP hostname variants
    "shelly",           # Shelly switches/sensors
    "tasmota",          # Tasmota-flashed devices
    "tuya",             # Tuya IoT
    "armcrest", "amcrest",  # Amcrest cameras
    "reolink",          # Reolink cameras
    "dahua",            # Dahua cameras
    "g3-", "g4-", "g5-",   # Ubiquiti cameras (G3/G4/G5 Instant)
    "envoy",            # Enphase Envoy
    "enphase",          # Enphase devices
    "ubiquiti", "unifi",    # Ubiquiti network gear
)
# Tablet hostname prefixes — excluded from phone-only guest counting.
# Guests may bring tablets but we count phones (1 per person) for accuracy.
TABLET_HOSTNAME_PREFIXES: Final = (
    "ipad",
)

# ============================================================================
# v3.22.0: CROSS-COORDINATOR SIGNAL RESPONSE CONFIG KEYS (all default OFF)
# ============================================================================
# These toggles control whether coordinators react to cross-system signals.
# Stored in Coordinator Manager entry options, read via BaseCoordinator._get_signal_config().

CONF_HVAC_ON_HAZARD_STOP_FANS: Final = "hvac_on_hazard_stop_fans"
CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT: Final = "hvac_on_hazard_emergency_heat"
CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: Final = "security_on_hazard_unlock_egress"
CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: Final = "security_on_arrival_add_expected"
CONF_ENERGY_ON_HAZARD_SHED_LOADS: Final = "energy_on_hazard_shed_loads"
CONF_MUSIC_ON_HAZARD_STOP: Final = "music_on_hazard_stop"
CONF_MUSIC_ON_ARRIVAL_START: Final = "music_on_arrival_start"
CONF_MUSIC_ON_SECURITY_STOP: Final = "music_on_security_stop"
