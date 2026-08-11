"""Constants for Universal Room Automation."""
#
# Universal Room Automation vv5.69.0
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
VERSION: Final = "v5.69.0"

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
# v5.7.0 WS-A4: per-zone outdoor flag. An outdoor zone (e.g. "Outside",
# "Front Porch") still tracks raw occupancy but is EXCLUDED from the
# indoor-occupancy aggregation that gates the v5.7.0 AWAY path β. An
# occupied doorbell-camera zone must not block AWAY when everyone is away.
CONF_ZONE_IS_OUTDOOR: Final = "zone_is_outdoor"
DEFAULT_ZONE_IS_OUTDOOR: Final = False
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
CONF_WHOLE_HOUSE_POWER_SENSOR: Final = "whole_house_power_sensor"  # Legacy singular
CONF_WHOLE_HOUSE_ENERGY_SENSOR: Final = "whole_house_energy_sensor"  # Legacy singular
CONF_WHOLE_HOUSE_POWER_SENSORS: Final = "whole_house_power_sensors"  # v4.1.0: plural
CONF_WHOLE_HOUSE_ENERGY_SENSORS: Final = "whole_house_energy_sensors"  # v4.1.0: plural

# v4.1.0: Zone-level and house-level energy attribution
CONF_ZONE_POWER_SENSORS: Final = "zone_power_sensors"
CONF_ZONE_ENERGY_SENSORS: Final = "zone_energy_sensors"
CONF_HOUSE_DEVICE_POWER_SENSORS: Final = "house_device_power_sensors"
CONF_HOUSE_DEVICE_ENERGY_SENSORS: Final = "house_device_energy_sensors"

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
# Coverage rating returned when delta_percent is out of bounds (negative,
# >100%, or None). Distinct from INCOMPLETE so post-deploy auditors can
# grep for it as a telemetry signal. See PLANNING_energy_unit_normalization
# D3 + Bug Class #30 recurrence on the energy device class.
COVERAGE_RATING_ANOMALOUS: Final = "Anomalous"

# Energy baseline schema-version sentinel (D1 migration). When the persisted
# version is < ENERGY_BASELINE_SCHEMA_VERSION on first boot of new code,
# all rows in room_energy_baselines are reset (because legacy rows may
# hold raw Wh values that would produce hugely-negative deltas vs the
# new kWh-normalized current_value).
ENERGY_BASELINE_SCHEMA_VERSION: Final = 2
# Reserved sentinel room_id / sensor_id used to track the schema version
# inside the existing room_energy_baselines table (no new schema needed).
ENERGY_BASELINE_VERSION_ROOM_ID: Final = "__schema_version__"
ENERGY_BASELINE_VERSION_SENSOR_ID: Final = "energy_baseline_version"

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
CONF_OCCUPANCY_DEBOUNCE: Final = "occupancy_debounce"

# v4.7.2 D4: Per-room guest designation + occupancy threshold
CONF_ROOM_IS_GUEST_ROOM: Final = "room_is_guest_room"
CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: Final = "room_guest_occupancy_threshold_min"

# Room types
ROOM_TYPE_BEDROOM: Final = "bedroom"
ROOM_TYPE_CLOSET: Final = "closet"
ROOM_TYPE_BATHROOM: Final = "bathroom"
ROOM_TYPE_MEDIA_ROOM: Final = "media_room"
ROOM_TYPE_GARAGE: Final = "garage"
ROOM_TYPE_UTILITY: Final = "utility"
ROOM_TYPE_COMMON_AREA: Final = "common_area"
ROOM_TYPE_GENERIC: Final = "generic"
ROOM_TYPE_INFRASTRUCTURE: Final = "infrastructure"  # v4.2.0: Always-on equipment rooms

# --- Step 2: Sensors ---
CONF_MOTION_SENSORS: Final = "motion_sensors"
CONF_MMWAVE_SENSORS: Final = "presence_sensors"  # Note: blueprint calls them presence_sensors
CONF_OCCUPANCY_SENSORS: Final = "occupancy_sensors"  # Combined motion+presence sensors

# Presence provenance-split cycle: Tier-1 occupancy provenance vocabulary.
# Used by ZonePresenceTracker._room_provenance keys and the entity classifier.
# Order is intentional — mmwave preferred over motion when an entity matches
# both substrings (e.g. "mmwave_motion"). See _classify_entity_kind in
# domain_coordinators/presence.py.
TIER1_KINDS: Final = ("motion", "mmwave", "occupancy")

# --- SENSOR-CAPABILITY-1 (plan: docs/planning/PLANNING_sensor_capability_vs_role.md) ---
# CAPABILITY layer sits ABOVE the three CONF lists. The CONF lists remain the
# WIRING declaration (what URA is subscribed to) and their kinds remain
# TIER1_KINDS-valued for the substrate dispatch channel (I3). Capability is
# resolved at the CONSUMPTION site via `sensor_role.resolve_role`, NOT at the
# substrate dispatch site — this bounds blast radius per new kind to O(1)
# instead of O(N sites iterating TIER1_KINDS). Extending TIER1_KINDS itself
# is deliberately OUT of scope; `presence._audit_provenance_invariants`
# RAISES on kinds outside TIER1_KINDS ∪ {"tier1"} and that is the desired
# failure mode when a capability kind leaks onto the legacy channel.
#
# Capability kind vocabulary (rung 1 — module constant; changing it is a
# schema change that must go through code review, never operator config).
CAPABILITY_KIND_MOTION: Final = "motion"
CAPABILITY_KIND_MMWAVE: Final = "mmwave"
CAPABILITY_KIND_OCCUPANCY: Final = "occupancy"
CAPABILITY_KIND_PIR: Final = "pir"
CAPABILITY_KIND_BED: Final = "bed"
CAPABILITY_KIND_CAMERA_PRESENCE: Final = "camera_presence"
CAPABILITY_KIND_BLE_PRESENCE: Final = "ble_presence"
CAPABILITY_KIND_PIR_SPLIT: Final = "pir_split"

# TIER1_CAPABILITIES is a SUPERSET of TIER1_KINDS. Consumers that ask role
# questions may see any of these values; consumers of the legacy substrate
# dispatch channel see ONLY TIER1_KINDS members.
TIER1_CAPABILITIES: Final = TIER1_KINDS + (
    CAPABILITY_KIND_PIR,
    CAPABILITY_KIND_BED,
    CAPABILITY_KIND_CAMERA_PRESENCE,
    CAPABILITY_KIND_BLE_PRESENCE,
    CAPABILITY_KIND_PIR_SPLIT,
)

# Trust class vocabulary (rung 1) — closed set; open strings would defeat
# the role-query matrix's testability. Strong-evidence sensors are DEMOTED
# from stuck-candidate lists and ELEVATED into the corroborator set.
TRUST_CLASS_STRONG_EVIDENCE: Final = "strong_evidence"
TRUST_CLASS_WITNESS: Final = "witness"
TRUST_CLASS_WEAK_WITNESS: Final = "weak_witness"
TRUST_CLASSES: Final = (
    TRUST_CLASS_STRONG_EVIDENCE,
    TRUST_CLASS_WITNESS,
    TRUST_CLASS_WEAK_WITNESS,
)

# Failure-mode vocabulary (rung 1) — enumerates whether the failure of this
# sensor is INDEPENDENT of another sensor's failure. Used later by the
# corroboration/independence logic; carried through capability today.
FAILURE_MODE_PHYSICAL_INDEPENDENT: Final = "physical_independent"
FAILURE_MODE_CORRELATED_WIRELESS: Final = "correlated_wireless"
FAILURE_MODE_CORRELATED_BRIDGE: Final = "correlated_bridge"
FAILURE_MODE_UNKNOWN: Final = "unknown"
FAILURE_MODES: Final = (
    FAILURE_MODE_PHYSICAL_INDEPENDENT,
    FAILURE_MODE_CORRELATED_WIRELESS,
    FAILURE_MODE_CORRELATED_BRIDGE,
    FAILURE_MODE_UNKNOWN,
)

# Per-room operator-declarable capability overrides. Absent key = empty
# dict = byte-identical fallback (I1). Rung 2 (options flow).
#
# Shape: {entity_id: {"kind": <TIER1_CAPABILITIES>,
#                     "trust_class": <TRUST_CLASSES>,
#                     "failure_mode": <FAILURE_MODES>}}
#
# Only "kind" is required in a declaration; trust_class and failure_mode
# default per capability (see sensor_capability.DEFAULT_TRUST_BY_KIND /
# DEFAULT_FAILURE_MODE_BY_KIND).
CONF_SENSOR_CAPABILITIES: Final = "sensor_capabilities"

# v3.2.4: CONF_PHONE_TRACKER deprecated - use person tracking with Bermuda instead
CONF_PHONE_TRACKER: Final = "phone_tracker"  # DEPRECATED in v3.2.4 - kept for migration
# v3.2.4: Scanner areas for sparse scanner homes (optional override)
CONF_SCANNER_AREAS: Final = "scanner_areas"  # List of HA area_ids where BLE scanners are
# v4.7.16 D4: Per-room opt-out for camera-presence Tier 2 signal contribution.
# When True, presence.py discovery skips tracker.register_camera() for the
# zone owning this room's area_id. Use for rooms with chronic camera
# person-classifier false positives (TV reflections, sun-glare hallways).
# The room still appears in URA; only its camera signal is muted. Lazy
# default per v4.7.4.4 Bug Class #46 doctrine — no migration helper,
# absent key reads as False.
CONF_DISABLE_CAMERA_PRESENCE: Final = "disable_camera_presence"
DEFAULT_DISABLE_CAMERA_PRESENCE: Final = False

# v4.7.16 D3: BLE evidence weight for rooms borrowing a scanner via
# CONF_SCANNER_AREAS (ble_tier=2). Tier 1 rooms (own scanner) implicitly
# weight 1.0; Tier 0 rooms (no BLE) weight 0.0. Operator-tunable constant —
# raise toward 1.0 for high-confidence borrowed scanners; lower toward
# 0.3 for noisier shared scanners. Not exposed via options flow in
# v4.7.16; see PLANNING_v4.7.16 §2 D3 rationale.
BLE_TIER_2_WEIGHT: Final = 0.6

# ble_extend_not_create — BLE-extends-occupancy predicate multiplier.
#
# History:
#   - 2026-07-17: introduced as the window-width multiplier for the
#     recent-motion confirmation leg (b) of the two-leg admission
#     predicate in the coordinator BLE block. Admission required
#     `_last_motion_time` within (multiplier x occupancy_timeout) OR
#     chain-unbroken (leg (a)).
#   - 2026-08-10 (BLE-WARM-CREATE-1): leg (b) was measured admitting
#     BLE-only CREATE events off adjacent-room bleed and was DELETED.
#     Admission is now CHAIN-ONLY.
#
# In the BLE block this constant no longer scales a window; it is
# purely the ON/OFF kill switch for the chain-based BLE hold. In the
# D2 mmWave-fan demotion block (also in coordinator.py) the same
# constant is still read as a PIR-staleness multiplier — do NOT
# interpret the constant as pure-kill globally. Read the two blocks
# together before changing this value.
#
# Rung: module constant (Numbers Get Knobs rung 1). Safety/trust bound
# on a truth-source-elevation predicate; not operator-tuned per-deployment.
# Kill semantics: setting to 0 disables the BLE hold path entirely
# (chain-leg predicate always false → BLE can neither create nor
# extend) AND disables the D2 mmWave-fan demotion block entirely via its
# own outer `MULT > 0` guard (coordinator.py; the staleness arithmetic
# never runs at 0 — it is NOT a threshold-collapse).
# --- MULT clean-break split 2026-08-10 (MULT_SPLIT_APPROVED_2026_08_10) ---
# Single-user, no back-compat: the ambiguous multi-purpose
# BLE_MOTION_CONFIRM_MULTIPLIER is REPLACED by two purpose-named
# constants. No deprecated alias. Both remain rung-1 module constants
# because they are safety/trust bounds; changing either should require
# code review.
#
# 1) BLE_CHAIN_HOLD_ENABLED — bool KILL SWITCH for the BLE chain-hold
#    admission gate in the coordinator BLE block. Post-BLE-WARM-CREATE-1
#    (v5.66.0) that block is a pure on/off gate; MULT>0 semantics
#    collapse to "enabled". Setting False disables the BLE hold path
#    entirely (chain-leg predicate always false → BLE can neither
#    create nor extend). Kill semantics: `False`.
BLE_CHAIN_HOLD_ENABLED: Final = True

# 2) D2_PIR_STALENESS_MULTIPLIER — INT multiplier consumed by the D2
#    mmWave-fan demotion block: PIR staleness threshold =
#    `D2_PIR_STALENESS_MULTIPLIER × occupancy_timeout`. Also guards the
#    outer `MULT > 0` predicate that disables the D2 block entirely
#    (mirrors the historical MMWAVE_FAN_CORROBORATION guard). Kill
#    semantics: `0` disables the whole D2 predicate (outer guard);
#    this is NOT a threshold-collapse (staleness arithmetic never
#    runs at 0). Value 2 = 2× room's motion timeout (bedroom 60min,
#    closet 8min).
D2_PIR_STALENESS_MULTIPLIER: Final = 2

# v4.7.16 D3 (post-review B MEDIUM #1): kill switch for the per-room
# weighted veto block in _run_inference. Default ON because D3 is the
# scaffolding for the v4.7.15 helper integration; future cycles will
# flip it from diagnostic → gating. Operator can set False to skip the
# per-cycle work (~1200 string normalizations / cycle on a 30-room
# install) when the diagnostic data is not in use. Module-level
# constant rather than an options-flow field because this is a
# performance kill-switch, not a user-facing knob.
D3_DIAGNOSTIC_ENABLED: Final = True

# Fan-noise mitigation D1 (Layer-1 silent interference-conditioned discount
# + decay). Per-Presence-Coordinator hold duration applied when a room is
# fan-interference-suspect AND the BLE corroboration ladder says
# not-corroborated. The hold can only EXTEND occupancy via the derived
# `_room_occupied` view — it NEVER shortens a genuinely-occupied room.
# Default mirrors the camera-tier 300s convention
# (`_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` at presence.py:71). Range 60-1800.
# The whole feature (observation diagnostic + gate hold) is kill-switched
# by `D3_DIAGNOSTIC_ENABLED` above — operator collapsed the proposed
# `CONF_FAN_INTERFERENCE_GATE_ENABLED` into the existing flag per the
# locked decision 2026-06-04.
CONF_FAN_INTERFERENCE_HOLD_S: Final = "fan_interference_hold_s"
DEFAULT_FAN_INTERFERENCE_HOLD_S: Final = 300

# Fan-noise mitigation D1: per-room adjacency list for Layer-2 BLE
# corroboration ("probably the same person drifting" — bathroom <-> bedroom).
# Stored as a list of OTHER room entry_ids. Empty list is SAFE — L2 simply
# does not fire and the gate falls back to L1 + L3. No migration helper
# per Bug Class #46 lazy-derivation doctrine: readers use
# ``entry.options.get(CONF_ADJACENT_ROOMS, [])``.
CONF_ADJACENT_ROOMS: Final = "adjacent_rooms"

# Fan-noise Mode-2 mitigation (room-tier BLE-gated fan-pause + clean recheck).
# Master kill switch per PresenceCoordinator; default False = opt-in.
CONF_FAN_RECHECK_ENABLED: Final = "fan_recheck_enabled"
DEFAULT_FAN_RECHECK_ENABLED: Final = False

# Per-room opt-in. Default True — operator wants the recheck broadly active
# (Exercise + Jaya + Ziri are the motivating rooms); find-and-disable per room
# rather than find-and-enable. Master switch + sleep gate still bound behaviour.
CONF_ROOM_FAN_RECHECK_ENABLED: Final = "room_fan_recheck_enabled"
DEFAULT_ROOM_FAN_RECHECK_ENABLED: Final = True

# Per-room Tier-1-only weak-authorize via L2 adjacent-empty path. Default True
# (advanced/collapsed) — a user is unlikely to discover and flip this, so a
# False default would leave it inert; find-and-disable instead. Ignored in
# Tier-2 (where L2 is an unconditional safety veto, never flag-gated).
CONF_FAN_RECHECK_L2_ALLOWED: Final = "fan_recheck_l2_allowed"
DEFAULT_FAN_RECHECK_L2_ALLOWED: Final = True

# Per-room still-capability attestation for Tier-0/2 rooms. With no scanner,
# BLE absence cannot authorize a drop — the drop rests on the physical recheck.
# Safe ONLY if the room's mmwave can see stillness. Default True (advanced/
# collapsed) — find-and-disable per room. Ignored for Tier-1 rooms (BLE
# backstops the recheck).
CONF_FAN_RECHECK_TRUST_SENSORS_OK: Final = "fan_recheck_trust_sensors_ok"
DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK: Final = True

# Settle time before pausing — gives L1/L2 a chance to fire and cancel.
CONF_FAN_RECHECK_ARM_DELAY_S: Final = "fan_recheck_arm_delay_s"
DEFAULT_FAN_RECHECK_ARM_DELAY_S: Final = 60

# Fan spin-down window. Long enough for airflow to stop so mmwave sees a clean field.
CONF_FAN_RECHECK_SPINDOWN_S: Final = "fan_recheck_spindown_s"
DEFAULT_FAN_RECHECK_SPINDOWN_S: Final = 30

# After spin-down, hold fan off while observing mmwave. Drops -> fan-coupled,
# release; persists -> real presence, restore.
CONF_FAN_RECHECK_WINDOW_S: Final = "fan_recheck_window_s"
DEFAULT_FAN_RECHECK_WINDOW_S: Final = 60

# Per-room rate limit.
CONF_FAN_RECHECK_COOLDOWN_S: Final = "fan_recheck_cooldown_s"
DEFAULT_FAN_RECHECK_COOLDOWN_S: Final = 1800

# Hard ceiling per room per hour. 0 disables.
CONF_FAN_RECHECK_MAX_PER_HOUR: Final = "fan_recheck_max_per_hour"
DEFAULT_FAN_RECHECK_MAX_PER_HOUR: Final = 2

# HVAC handshake duration. Sized as SPINDOWN + WINDOW + 2*margin.
CONF_FAN_RECHECK_HVAC_SUPPRESS_S: Final = "fan_recheck_hvac_suppress_s"
DEFAULT_FAN_RECHECK_HVAC_SUPPRESS_S: Final = 600

# FIX C (room-tier fan manual-off cooldown).
# Duration (seconds) that a manually-off fan is held OFF against re-arm
# by the room-tier temperature-fan path (automation.py
# handle_temperature_based_fan_control) after an external actor turns
# the fan off. Mirrors the HVAC-tier manual-off cooldown at
# hvac_fans.py:207-217 (which previously hard-coded 1h inline).
#
# Rung: module constant per CLAUDE.md "Numbers Get Knobs" — safety
# cooldown that protects manual actions; misconfiguring it re-creates
# the exact re-arm bug, so tuning requires reviewed code change.
#
# Kill switch: 0 = feature disabled (pre-fix behavior). Use if a bad
# interaction with a specific room config appears live and needs
# reversal without a rollback.
DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S: Final = 3600

# FAN-MANUAL-1 (2026-08-10). Symmetric ON-side of the manual-off
# cooldown. When URA detects an external actor turning a fan ON, honor
# that intent for this many seconds before allowing any URA
# ``turn_off`` to fire against the fan (temperature-below-threshold
# revert, vacancy sweep, FAN_SLEEP_OFF, HVAC vacancy/temp OFF).
# Discharge conditions (bounded runtime + external OFF + allowlisted
# trigger paths + safety + fan_control_enabled off) enumerated in
# docs/planning/PLANNING_fan_manual_on_override.md §5.3.
#
# Rung: module constant per CLAUDE.md "Numbers Get Knobs". The value
# governs whether a comfort revert can fire against a human's explicit
# ON action; misconfiguring re-creates the original "system overrules
# the human" complaint. Tuning should require a reviewed code change.
#
# Kill switch: 0 = feature disabled (no hold ever opens; pre-fix
# behavior). Mirrored on the per-room CONF (explicit 0 in the
# per-room override disables the feature for that room only).
DEFAULT_FAN_MANUAL_ON_HOLD_S: Final = 3600
CONF_FAN_MANUAL_ON_HOLD_S: Final = "fan_manual_on_hold_s"

# Trigger requires occupancy_source == "mmwave" for N consecutive ticks.
CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS: Final = "fan_recheck_mmwave_history_ticks"
DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS: Final = 3

# room_type as a conservatism DIAL (D1.5): high-still-risk types extend the
# recheck window and force L3-only in Tier-1. NOT an eligibility gate.
ROOM_TYPE_RECHECK_FACTOR: Final = {
    "bedroom": 2.0,
    "media_room": 2.0,
}
DEFAULT_RECHECK_FACTOR: Final = 1.0

# STATE_OCCUPANCY_SOURCE value set when the room-tier fan-recheck releases.
OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE: Final = "fan_recheck_release"

# mmWave fan-corroboration demotion (Tier-3 D2 — planning doc
# docs/planning/PLANNING_mmwave_corroboration_tier3.md §D2). Passive
# backstop to the pause-based fan-recheck (v5.23.0): when a room's
# occupancy is sustained by mmwave-alone AND fans have been on for
# ≥GRACE seconds AND no PIR motion in ≥MULT×occupancy_timeout AND no
# BLE-trustworthy person is present, demote the room to vacant (mmwave
# cannot SUSTAIN past its natural timeout under these conditions).
#
# Truth-preserving invariant: NEVER fires while any of {motion=True,
# occupancy(non-mmwave)=True, BLE person in room, camera-person in
# covered room} holds. Worst-case failure mode = a fan-suspect room
# reads vacant slightly earlier.
#
# Ordering vs recheck (v5.23.0): the pause-based recheck gets first
# crack; D2 does NOT evaluate while a recheck is in-flight for the
# room. D2's staleness bar (MULT×timeout) is deliberately HIGHER than
# recheck's trigger bar. D2 is the backstop for recheck-ineligible /
# rate-capped rooms.
#
# Kill switches (rung-1 module constants):
#   1) MMWAVE_FAN_CORROBORATION_ENABLED — disables the whole predicate.
#   2) D2_PIR_STALENESS_MULTIPLIER=0 — also disables the derived
#      staleness gate (mirrors the ble_extend_not_create kill).
#   3) D3_DIAGNOSTIC_ENABLED — third UPSTREAM kill switch: D2's
#      _compute_mmwave_fan_demoted_rooms wraps _compute_fan_interference_rooms,
#      which short-returns [] when D3_DIAGNOSTIC_ENABLED is False. Reuse
#      of the D3 primitive is BY DESIGN (single interference-conditional
#      reliability primitive); D2 is NOT decoupled from D3.
# MMWAVE_FAN_CORROBORATION_GRACE_S values below 300 are clamped to 300
# in the wrapper (fail-safe floor; see D-MED-2). Setting it very low
# does NOT disable the feature — use ENABLED=False for that.
MMWAVE_FAN_CORROBORATION_ENABLED: Final = True
MMWAVE_FAN_CORROBORATION_GRACE_S: Final = 600
OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED: Final = "mmwave_fan_demoted"

# Fan-transition coincidence gate (rung-1 module constant).
#
# Separability probe (docs/planning/AUDIT_fan_signature_separability_probe.md,
# 2026-08-01) found that mmWave phantom-occupancy onsets align to the exact
# second (Δt ≤ 1-2s) of a fan power/speed TRANSITION, while steady-state fan
# runtime of 20+ hours produces zero phantom edges. Two independent rooms,
# two fan types, exact-second alignment.
#
# Semantics: when a room's occupancy would be NEWLY CREATED with source =
# mmwave (mmwave-sole rising edge) AND (now - fan_last_transition) <=
# FAN_TRANSITION_SUSPECT_WINDOW_S, the CREATION is suppressed. PIR / BLE /
# camera evidence inside the window still creates occupancy normally — only
# the mmwave-sole creation path is gated. The suppression does NOT extend
# an existing occupancy hold and does NOT interfere with D2 (sustain) or
# fan-recheck (test-under-fan). It gates CREATION only — the one direction
# nothing else covers.
#
# Kill switch: 0.0 disables the gate (matches other rung-1 kill-switch
# semantics in this file).
FAN_TRANSITION_SUSPECT_WINDOW_S: Final = 5.0

CONF_DOOR_SENSORS: Final = "door_sensor"
CONF_DOOR_TYPE: Final = "door_type"
CONF_WINDOW_SENSORS: Final = "window_sensor"
# v4.7.8 D1: Per-room egress-window flag. When True (default), an opened
# window for this room counts toward the canonical HVAC zone's egress-pause
# threshold. Lazy default per v4.7.4.4 Bug Class #46 doctrine: no migration
# helper — readers must default to True when key is absent.
CONF_IS_EGRESS_WINDOW: Final = "is_egress_window"
DEFAULT_IS_EGRESS_WINDOW: Final = True
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
# v4.5.9: per-room opt-out from HVAC solar-gain cover management. Default True
# preserves pre-v4.5.9 behavior; setting to False removes the room's covers
# from CoverController's discovery so HVAC won't close/open them. Per-room
# automation (timed open/close, exit close, entry open) is unaffected.
CONF_COVER_HVAC_MANAGED: Final = "cover_hvac_managed"

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

# --- Step 5: Climate & Fans ---
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
CONF_HUMIDITY_FAN_MAX_RUNTIME: Final = "humidity_fan_max_runtime"
CONF_FAN_VACANCY_HOLD: Final = "fan_vacancy_hold"

# --- Comfort-fan house-AWAY veto (mmwave-corroboration Tier-3 cycle, D3) ---
# Rung 2 (options-flow) kill switch. When True (default), comfort-fan
# `turn_on` service calls at all three comfort-fan actuation sites
# (room-tier automation.py, HVAC-tier hvac_fans.py, actuator_reconciler.py)
# are SUPPRESSED when house_state ∈ {AWAY, VACATION} AND the room lacks
# trusted presence (recent motion within occupancy_timeout, BLE-trustworthy
# person in room, or camera-person in a camera-covered room). mmWave is
# EXCLUDED from trusted presence — that is the whole point (an empty house
# with a phantom mmwave firing should NEVER cool itself).
#
# KILL SWITCH SEMANTICS: setting this False at the options-flow makes the
# veto helper return False unconditionally — behavior becomes byte-identical
# to pre-cycle. Humidity fans / safety fans / sleep path are NEVER touched
# by this veto regardless of setting.
#
# Per-room knob (default ON) so per-integration override is a simple
# options-flow toggle. Rationale for rung-2 placement: operators may
# legitimately want AWAY comfort fans (e.g. pet-cooling); the knob is
# infrequently changed but IS operator-legitimate to change.
# See PLANNING_mmwave_corroboration_tier3.md D1/D3.
CONF_COMFORT_FAN_AWAY_VETO_ENABLED: Final = "comfort_fan_away_veto_enabled"
DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED: Final = True

# Camera-coverage map (rung-1 module constant per PLANNING Amendment 1).
# Only rooms in this frozenset consult the camera-person leg of the
# comfort-fan veto's trusted-presence check. Uncovered rooms (all
# private bedrooms, most rooms) rely on PIR + BLE only — camera person
# signals for uncovered rooms are ignored to prevent common-area camera
# traffic from spuriously "corroborating" a private room via zone-scope.
#
# TODO-REVIEWED: initial population is Study A only (per operator: cameras
# exist only in common areas + Study A). The camera-census common areas
# should be appended here once D0 audit produces the mapping — candidates
# by area name (from camera_census.py:678 area→camera map): "Kitchen",
# "Great Room", "Foyer", "Front Entry", "Backyard" — reviewer to confirm
# room-name spellings against live config before adding. Changing this
# constant should require code review, not a dashboard toggle.
CAMERA_COVERED_ROOMS: Final = frozenset({"Study A"})

# --- Room-camera fusion cycle (2026-08-01) ---
# NEW per-room key: multi-select of any camera-related entities. Resolved
# to physical camera devices by camera_resolver.CameraResolver. Sidesteps
# the v3.4.5 CONF_CAMERA_PERSON_ENTITIES migration (which strips its own
# key from room entries) by intentionally using a distinct identifier.
CONF_ROOM_CAMERAS: Final = "room_cameras"

# D4 auto-enable of per-integration person-detect switches. Person YES,
# face NEVER (invariant).
CONF_AUTO_ENABLE_PERSON_DETECTION: Final = "auto_enable_person_detection"
DEFAULT_AUTO_ENABLE_PERSON_DETECTION: Final = True

# --- Bathroom-exhaust intelligence (humidity-fan unification cycle) ---
# Toggle #3: master enable for humidity-fan automation (D4/D5).
# Default True — preserves behavior for entries without the new field.
CONF_HUMIDITY_FAN_CONTROL_ENABLED: Final = "humidity_fan_control_enabled"
DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED: Final = True

# Wet-room flag (D4). Defaults to True iff room_type == bathroom; else False.
# Operator opts in for laundry/mudroom. Gates D2/D3 default-on + the
# sleep-policy exemption in automation.py.
CONF_WET_ROOM: Final = "wet_room"

# D2 — EMA-baseline humidity-spike detection.
CONF_HUMIDITY_FAN_SPIKE_ENABLED: Final = "humidity_fan_spike_enabled"
CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT: Final = "humidity_fan_spike_delta_pct"
CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S: Final = "humidity_fan_spike_ema_alpha_s"
CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE: Final = "humidity_fan_spike_baseline_mode"
HUMIDITY_FAN_SPIKE_MODE_EMA: Final = "ema"
HUMIDITY_FAN_SPIKE_MODE_WINDOW_MIN: Final = "window_min"
DEFAULT_HUMIDITY_FAN_SPIKE_DELTA_PCT: Final = 10  # pp above baseline
DEFAULT_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S: Final = 2700  # ~45 min time constant
DEFAULT_HUMIDITY_FAN_SPIKE_BASELINE_MODE: Final = HUMIDITY_FAN_SPIKE_MODE_EMA

# D3 — Presence/usage-proportional post-vacancy runtime.
CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED: Final = "humidity_fan_presence_runtime_enabled"
CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S: Final = "humidity_fan_presence_runtime_base_s"
CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S: Final = "humidity_fan_presence_runtime_per_min_s"
CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S: Final = "humidity_fan_presence_runtime_cap_s"
DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S: Final = 60
DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S: Final = 30
DEFAULT_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S: Final = 600

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

# --- feature/sleep-fans-and-flash: sleep-onset bedroom fan activation ---
# CM/HVAC-level threshold. On house-state transition INTO "sleep", each
# HVAC-managed bedroom room that is (a) OCCUPIED and (b) at/above this
# room-temp threshold gets its comfort fan turned ON at the policy-capped
# speed with trigger="sleep_onset". Master kill switch: 0 disables the
# feature entirely. One-shot per sleep entry (latched until house leaves
# FAN_TRUST_STATES). Per-room opt-out is CONF_FAN_SLEEP_POLICY=off
# (which the sleep-onset activator already respects).
CONF_SLEEP_FAN_ON_TEMP_F: Final = "sleep_fan_on_temp_f"
DEFAULT_SLEEP_FAN_ON_TEMP_F: Final = 72.0

# feature/sleep-fans-and-flash rung-1 module constants ("Numbers Get Knobs").
# Scar-cited by operator 2026-08-03:
#   - SLEEP_FAN_ON_REARM_S: minimum seconds between successive sleep-onset
#     fires per FanController / per RoomAutomation instance. Guards against
#     the 2026-08-03 06:00-class spurious sleep->waking->home_day->sleep
#     dawn re-entry re-transitioning every bedroom fan. 0 disables the
#     re-arm guard (fires on every sleep edge). Default 6h.
#   - SLEEP_FAN_ON_STAGGER_S: sequential delay between per-room fan
#     turn-ons during a single sleep-onset burst. mmWave fan-transition
#     excitation is exact-second — simultaneous multi-room transitions
#     are the worst radar case. 0 disables the stagger (simultaneous
#     activation, mirrors pre-cycle behavior).
# Rung-1 rationale: changing either affects mmWave-radar interaction and
# should require review (not a dashboard-level tune).
SLEEP_FAN_ON_REARM_S: Final = 21600  # 6 hours
SLEEP_FAN_ON_STAGGER_S: Final = 5

# --- Step 7: Energy Monitoring ---
CONF_POWER_SENSORS: Final = "power_sensors"
CONF_ENERGY_SENSOR: Final = "energy_sensor"  # Legacy singular — kept for migration
CONF_ENERGY_SENSORS: Final = "energy_sensors"  # v4.1.0: plural, multiple=True
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
DEFAULT_OCCUPANCY_DEBOUNCE: Final = 150  # milliseconds (UI) — converted to seconds in coordinator
DEFAULT_DARK_THRESHOLD: Final = 20      # lux (from blueprint v3.5.1)
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
DEFAULT_HUMIDITY_FAN_TIMEOUT: Final = 600  # 10 minutes (min-runtime gate — not an off-delay)
DEFAULT_HUMIDITY_FAN_MAX_RUNTIME: Final = 3600  # 60 minutes — force-off cap for stuck sensors
DEFAULT_HUMIDITY_FAN_HYSTERESIS: Final = 10  # % RH — OFF threshold = ON threshold − hysteresis
DEFAULT_FAN_VACANCY_HOLD: Final = 300  # 5 minutes extra after occupancy timeout

# Cover defaults
# v4.5.4: DEFAULT_OPEN_TIME_START/END and DEFAULT_CLOSE_TIME removed —
# never referenced anywhere; .get(CONF_OPEN_TIME_START, 7) calls in
# automation.py use literals. The CONFs themselves (CONF_OPEN_TIME_START
# etc.) and helpers (_is_in_open_time_range, _is_after_close_time) are
# still alive in the legacy fallback chain inside _is_cover_open_time
# and _is_cover_close_time — leave those for a future migration cycle.
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
    ROOM_TYPE_INFRASTRUCTURE: 120,  # 2 minutes (rarely visited)
}

# v4.5.15: Room-type-specific failsafe durations. Caps the maximum time
# a room can stay "occupied" before URA forces vacancy, regardless of
# motion sensor state. Distinct from ROOM_TYPE_TIMEOUTS (which is the
# normal motion-clear delay) — this is the upper bound that fires even
# when motion sensors continuously trigger (stuck sensor, false
# positive, fan-driven air movement reading as motion, etc.).
#
# Rooms NOT in this dict use DEFAULT_FAILSAFE_DURATION_SECONDS (4 hr).
# Closet + bathroom get 60-min lazy auto-off per v4.5.15 — typical
# usage of these spaces never approaches an hour, and the failsafe
# catches the "light left on with fan running" + "stuck sensor"
# patterns that motion-clear can miss.
DEFAULT_FAILSAFE_DURATION_SECONDS: Final = 4 * 3600  # 4 hours
ROOM_TYPE_FAILSAFE_DURATIONS: Final = {
    ROOM_TYPE_CLOSET: 3600,    # 60 min lazy auto-off
    ROOM_TYPE_BATHROOM: 3600,  # 60 min lazy auto-off
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

# Zone-level thermostat (v3.6.23): consumed by HVACCoordinator zone
# auto-discovery (Writer A). NOTE 2026-08-06: the v3.3.5.9 Writer-B preset
# override constants (CONF_ZONE_VACANT_PRESET / CONF_ZONE_OCCUPIED_PRESET /
# DEFAULT_ZONE_*_PRESET / HVAC_PRESET_SKIP) were deleted with the Writer-B
# code path — none were set in live config, none had a config-flow surface,
# and their only consumer was `ZoneAnyoneBinarySensor._handle_zone_occupancy_change`.
CONF_ZONE_THERMOSTAT: Final = "zone_thermostat"

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

# Census fusion policy (divergence-aware confidence) — 2026-08-01 cycle.
# When two camera platforms cover the same interior zone and DIVERGE (one>0,
# other==0), the merge currently picks max (see camera_census
# ``_cross_validate_platforms``). If no corroborating signal is present
# (no face-ID, no BLE person, no zone-occupied predicate), the uncorroborated
# higher source is downgraded to ``min`` (== 0) tagged ``DISAGREE`` (which
# maps to LOW confidence and does not clear the guest-flip bar).
# ``False`` = fire-axe restore to pre-cycle max-wins behavior.
CONF_CENSUS_DIVERGENCE_DOWNGRADE: Final = "census_divergence_downgrade"
DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE: Final = True
# Kinds of corroboration that suppress the divergence downgrade. Rung-1
# (module constant): changing the set redefines the invariant and requires
# review, not operator tuning.
CENSUS_DIVERGENCE_CORROBORATION_KINDS: Final = frozenset(
    {"face", "ble", "zone_occupied"}
)

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

# ----------------------------------------------------------------------------
# XCORR-1: burst-demotion for isolated single-camera alerts.
# Probe-grounded (docs/planning/AUDIT_xcorr_engine_corroboration_probe.md).
# Cross-engine corroboration on the same camera CANNOT gate dispatch — solo
# firing is the norm on the exterior cameras that matter (77–93% solo).
# Instead: when a SECOND (or later) alert fires from the SAME collapsed
# camera-key within a window, and there is (a) no sibling-engine
# corroboration on that camera, (b) no adjacent-camera activity per the
# linker's adjacency graph, (c) it is deep-night, DEMOTE severity to LOW
# (never silence — composes with the demote-never-silence invariant INV-XP).
# The FIRST alert from a camera always fires at full severity.
# Rung-1 module constants — safety-adjacent; changes require code review.
# ----------------------------------------------------------------------------
# Kill switch: False = today's behavior byte-identical, feature disabled.
PERIMETER_BURST_DEMOTE_ENABLED: Final = True
# Burst window in seconds. Probe observed 2026-08-08 incident: 5 alerts in
# 18 minutes; 30-minute window comfortably covers that pattern.
PERIMETER_BURST_WINDOW_S: Final = 1800
# Minimum dispatched-alert count within window (INCLUDING the current one)
# before demotion applies. Value 2 = demote from the SECOND alert onwards
# (first-alert-is-sacred invariant).
PERIMETER_BURST_MIN_ALERTS: Final = 2
# When True, demotion only applies inside the perimeter alert-hours window
# (deep-night, default 23-05). Redundant today because dispatch is already
# gated by _is_in_alert_hours, but preserved as an explicit kill for future
# 24h alert coverage.
PERIMETER_BURST_NIGHT_ONLY: Final = True

# ----------------------------------------------------------------------------
# Exterior-person NM escalation (D1/D2/D4 — PLANNING_exterior_person_escalation)
# Rung-1 module consts (safety-adjacent; changes require code review).
# Values are Severity NAMES (strings) to keep const.py independent of the
# domain_coordinators.base import graph; perimeter_alert.py coerces via
# Severity[<name>] at emit time. Unknown / missing keys fail-safe to CRITICAL.
# ----------------------------------------------------------------------------
NM_HAZARD_EXTERIOR_PERSON: Final = "exterior_person"
# Fix-up (2026-08-06, A-H1/D-H1): distinct hazard for vehicle path so it
# CANNOT collapse a subsequent person emission via NM's boot-settle guard
# (which keys on (coord_id, hazard_type)). Dedup is (coord,title,location)
# which already differs. Token buckets are PER-CHANNEL (see NM Cycle B B3)
# — NOT partitioned by hazard — so a non-life-safety vehicle emit still
# consumes 1 channel token that a subsequent non-life-safety person emit
# would need. INV-XP mitigation: the first-alert-per-track gate for
# vehicles bounds volume so channel contention is negligible in practice;
# person CRITICAL and vehicle HIGH remain independent by title/hazard for
# dedup and boot-settle. Not a life-safety hazard (base frozenset
# unchanged) — operators may promote via CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS.
NM_HAZARD_EXTERIOR_VEHICLE: Final = "exterior_vehicle"

# GUEST default extracted so a follow-up cycle can flip it without churning
# the full mapping table (plan D2).
NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY: Final = "MEDIUM"

# House-state (HouseState StrEnum values are lowercase, e.g. "away") →
# Severity name. Fallback (unknown / missing / None) is CRITICAL (fail-safe
# rule — unknown state is treated as away).
NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE: Final = {
    "away": "CRITICAL",
    "vacation": "CRITICAL",
    "sleep": "CRITICAL",
    "home_night": "CRITICAL",   # unattended-observation state
    "guest": NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY,
    "home_day": "LOW",
    "home_evening": "LOW",
    "arriving": "LOW",
    "waking": "LOW",
}
NM_HAZARD_EXTERIOR_PERSON_DEFAULT_SEVERITY: Final = "CRITICAL"  # fail-safe

# ----------------------------------------------------------------------------
# ExteriorTrackLinker (build/exterior-track — PLANNING_exterior_track_linking.md)
# Rung-1 module constants. All are named knobs (Numbers Get Knobs);
# adjacency + severity map ship as reviewed module tables (operator declares).
# Kill switch: TRACK_LINK_WINDOW_S = 0 → linker never links, cross-camera
# suppression disabled → per-camera behavior is byte-identical to today.
# ----------------------------------------------------------------------------
TRACK_LINK_WINDOW_S: Final = 180  # link an event to an open track if Δt ≤ 180s
TRACK_CLOSE_IDLE_S: Final = 300   # close an idle track after 5 min silence

# Operator-DECLARED adjacency for the 9 perimeter cameras (Frigate camera
# names as keys). Symmetric: declaring A→B implies B→A at load time via
# ExteriorTrackLinker.set_adjacency. Empty default — operator populates via
# a follow-up config surface OR the runtime setter. Same-camera linking
# works with an empty graph; cross-camera linking requires at least one
# declared edge. Tests inject their own graph via set_adjacency().
# Provenance: AUDIT_exterior_camera_adjacency_probe.md "Operator ratification
# (2026-08-06)". Base = probe's 24 proposed pairs (threshold: symmetric filtered
# count ≥ 3). Removals per ratification §3,§4: pool_equipment↔rear_ptz and
# rear_ptz↔utilities_ptz (physically impossible / missed-intermediate
# artifacts). Additions per ratification §1,§2 (pool service chain +
# back_yard↔hot_tub confirmed): rear_ptz↔armcrest, rear_ptz↔back_yard,
# g5_bullet↔armcrest (already in probe), g5_bullet↔back_yard, armcrest↔hot_tub
# (already in probe), back_yard↔hot_tub, hot_tub↔pool_equipment. Symmetrized
# in ExteriorTrackLinker constructor — declaring A→B is sufficient.
EXTERIOR_ADJACENCY_GRAPH: Final[dict[str, tuple[str, ...]]] = {
    # Probe pairs kept (22 after the two removals).
    "front_side_ptz": (
        "utilities_ptz", "rear_ptz", "g5_bullet", "hot_tub",
        "reolinkstudybporchptz", "madrone_g6_entry", "front_door_aerial",
        "back_yard",
    ),
    "front_door_aerial": (
        "madrone_g6_entry", "hot_tub", "front_side_ptz", "rear_ptz",
    ),
    "madrone_g6_entry": (
        "front_door_aerial", "utilities_ptz", "g5_bullet", "front_side_ptz",
        "rear_ptz",
    ),
    "armcrest": (
        "back_yard", "doorbell_lite", "reolinkstudybporchptz", "hot_tub",
        "g5_bullet",
        # Ratified additions (pool service chain).
        "rear_ptz",
    ),
    "doorbell_lite": (
        "g5_bullet", "armcrest", "rear_ptz",
    ),
    "g5_bullet": (
        "front_side_ptz", "doorbell_lite", "armcrest", "rear_ptz",
        "madrone_g6_entry",
        # Ratified addition (pool service chain enters via g5_bullet).
        "back_yard",
    ),
    "rear_ptz": (
        "front_side_ptz", "g5_bullet", "doorbell_lite", "front_door_aerial",
        "madrone_g6_entry",
        # Ratified additions (pool service chain).
        "armcrest", "back_yard",
    ),
    "hot_tub": (
        "front_side_ptz", "front_door_aerial", "armcrest",
        # Ratified additions.
        "back_yard", "pool_equipment",
    ),
    "back_yard": (
        "armcrest", "front_side_ptz",
        # Ratified additions.
        "rear_ptz", "g5_bullet", "hot_tub",
    ),
    "pool_equipment": (
        # Only chain-terminal edge: pool_equipment↔hot_tub. The probe's
        # rear_ptz co-firings were missed-intermediate artifacts.
        "hot_tub",
    ),
    "utilities_ptz": (
        "front_side_ptz", "madrone_g6_entry",
    ),
    "reolinkstudybporchptz": (
        "armcrest", "front_side_ptz",
    ),
}

# Labels bucketed by the linker (one track family per label). Frigate raw
# labels are normalized by _bucket_label: person, {car,truck,bus,motorcycle,
# vehicle} → car, {dog,cat,animal,bird,raccoon,deer} → animal.
EXTERIOR_TRACK_LABELS: Final = ("person", "car", "animal")

# Classification thresholds (space-time only — no re-identification).
EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS: Final = 0  # 0 = disabled; primary approach signal is EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS
EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS: Final = 3

# Cameras that are "one hop from an egress" (front door / back door zones)
# — operator-declared. Any track touching one of these classifies as
# `approach` (unless already `circling`). Empty default; safe fallback is
# the camera-count heuristic.
# Egress cameras (operator config): madrone_g6_entry, doorbell_lite,
# front_door_aerial. Egress-adjacent = perimeter cameras with an edge in the
# ratified EXTERIOR_ADJACENCY_GRAPH to ANY of those three. Provenance:
# AUDIT_exterior_camera_adjacency_probe.md "Operator ratification (2026-08-06)".
EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS: Final[tuple[str, ...]] = (
    # Adjacent to madrone_g6_entry.
    "front_door_aerial", "utilities_ptz", "g5_bullet", "front_side_ptz",
    "rear_ptz",
    # Adjacent to doorbell_lite (add-only unique).
    "armcrest",
    # Adjacent to front_door_aerial (unique add).
    "hot_tub",
)

# (label × house-state × classification) severity map.
# Value = Severity name string (perimeter_alert coerces via Severity[<name>]).
# Missing key falls back to NM_HAZARD_EXTERIOR_PERSON severity (existing behavior).
# animal/* defaults to DIGEST (below CRITICAL/HIGH/MEDIUM/LOW/DIGEST hierarchy).
NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP: Final[dict[str, dict[str, dict[str, str]]]] = {
    "person": {
        "away":     {"pass_by": "MEDIUM",   "approach": "HIGH",     "circling": "CRITICAL"},
        "sleep":    {"pass_by": "MEDIUM",   "approach": "HIGH",     "circling": "CRITICAL"},
        "vacation": {"pass_by": "MEDIUM",   "approach": "HIGH",     "circling": "CRITICAL"},
        "home_night": {"pass_by": "LOW",    "approach": "MEDIUM",   "circling": "HIGH"},
        "home_day": {"pass_by": "DIGEST",   "approach": "LOW",      "circling": "MEDIUM"},
    },
    "car": {
        # Exterior cycle 2 (2026-08-06 operator GO): deep-night vehicle
        # while unoccupied is the negative-signal case — HIGH first-alert,
        # with narrative. The night-window gate (EXTERIOR_VEHICLE_NIGHT_*)
        # lives in perimeter_alert.py; outside the window vehicle events
        # feed the linker (census/episode) but do NOT dispatch NM.
        # Continuation coercion may still demote/escalate via cycle-1 rules.
        "away":     {"pass_by": "HIGH",     "approach": "HIGH",     "circling": "HIGH"},
        "sleep":    {"pass_by": "HIGH",     "approach": "HIGH",     "circling": "HIGH"},
        "vacation": {"pass_by": "HIGH",     "approach": "HIGH",     "circling": "HIGH"},
        "home_night": {"pass_by": "LOW",    "approach": "LOW",      "circling": "MEDIUM"},
        "home_day": {"pass_by": "DIGEST",   "approach": "DIGEST",   "circling": "LOW"},
    },
    "animal": {
        # Digest-only default across the board — vehicle/person land above
        # this in the severity ladder. Escalation ships in a follow-up cycle.
        "away":     {"pass_by": "DIGEST",   "approach": "DIGEST",   "circling": "DIGEST"},
        "sleep":    {"pass_by": "DIGEST",   "approach": "DIGEST",   "circling": "DIGEST"},
        "home_night": {"pass_by": "DIGEST", "approach": "DIGEST",   "circling": "DIGEST"},
        "home_day": {"pass_by": "DIGEST",   "approach": "DIGEST",   "circling": "DIGEST"},
    },
}

# Rung-2 options knob (plan D4). Delays live-fallback snapshot capture by N
# seconds so the still frame is closer to the detection moment despite
# acquisition lag. Ignored on the Frigate event-frame path (event snapshot
# is inherently at-detection-time). 0 disables the delay.
CONF_EXTERIOR_SNAPSHOT_OFFSET_S: Final = "exterior_snapshot_offset_s"
DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S: Final = 5
MIN_EXTERIOR_SNAPSHOT_OFFSET_S: Final = 0
MAX_EXTERIOR_SNAPSHOT_OFFSET_S: Final = 60

# Rung-1 module constant (review B-HIGH-2 boot settle gate). Perimeter
# state-change events fired within N seconds of manager setup are ignored to
# suppress spurious CRITICALs caused by RestoreEntity replay / initial state
# publication after HA restart.
PERIMETER_BOOT_SETTLE_S: Final = 30

# Rung-1 kill switch (2026-08-06 protect-person-legs cycle). When True,
# PerimeterAlertManager additionally subscribes the UniFi-Protect
# `binary_sensor.<camera_slug>_person_detected` (+ `_2`) sibling of each
# configured perimeter/egress person sensor, giving perimeter/egress alerting
# a second independent detection engine (Protect smart-detect) alongside the
# existing Frigate `_person_occupancy` (+ `_2`) legs. Camera-key collapse
# (cooldown + in-flight, keyed via `_camera_key_for_sensor` which strips
# `_person_detected` / `_person_occupancy` and `_2`) guarantees a triple-fire
# across all legs yields exactly ONE alert. Set False for a byte-identical
# backout to pre-cycle subscription behavior.
#
# Kill-switch semantics: False → the subscription set collapses byte-identical
# to the pre-cycle behavior (Frigate `_person_occupancy` base + `_2` sibling
# only). No coverage log line is emitted for Protect legs, `_protect_person_legs`
# returns [] unconditionally, and `_rescan_siblings` skips the Protect-leg
# probe. Reversion is a one-line toggle here — no other code change required.
#
# Cycle-3 resolver-legs (2026-08-07) RENAME: `PERIMETER_PROTECT_PERSON_LEGS_
# ENABLED` -> `PERIMETER_MULTI_ENGINE_LEGS_ENABLED`. Kill-switch semantics
# generalized from "Protect person legs only" to "every integration's
# family (person/vehicle/animal) sensor for a configured camera, sourced
# via CameraResolver.resolve_detection_legs()". False collapses the
# subscription set to the configured base + `_2` sibling ONLY (byte-
# identical to pre-cycle behavior for the person path; vehicle/animal
# paths degrade to base+`_2` derived via legacy suffix search retained
# only as a fallback in this mode). Reversion is a one-line toggle here.
# The old constant name is retained as a passthrough alias below for one
# release so any out-of-tree consumers do not break; new code MUST read
# the MULTI_ENGINE name.
# Cycle-3 fix-up (2026-08-07, F3): OFF now falls back to the v5.58.0-shipped
# behavior — Frigate `_person_occupancy` base + `_2` sibling PLUS a Protect
# stem-probed leg (recovered from the retired `_protect_person_legs`). This
# preserves the Protect coverage v5.58.0 delivered, so a kill-switch pull
# does NOT silently regress to pre-v5.58.0 Frigate-only wiring. The Dahua
# `_smart_motion_human` base is also recognized so an operator whose
# configured base is native-AI keeps person detection on OFF.
PERIMETER_MULTI_ENGINE_LEGS_ENABLED: Final = True
PERIMETER_PROTECT_PERSON_LEGS_ENABLED: Final = PERIMETER_MULTI_ENGINE_LEGS_ENABLED  # DEPRECATED alias — remove one release post-cycle-3

# 2026-08-06 protect-person-legs fix-up (A-L2 + operator ruling): UniFi Protect
# exposes the raw camera as `camera.<slug>` while the resolution-channel
# entities (which the operator commonly configures for Frigate ingest) carry a
# suffix. Strip these when deriving the Protect person-leg slug from the
# configured camera entity id so `camera.rear_ptz_high_resolution_channel`
# resolves to the Protect leg `binary_sensor.rear_ptz_person_detected`.
CAMERA_RESOLUTION_CHANNEL_SUFFIXES: Final = (
    "_high_resolution_channel",
    "_medium_resolution_channel",
    "_low_resolution_channel",
)

# Review A-M2 label filter. Only Frigate events whose `after.label` is in this
# set update the cached snapshot event_id. Prevents e.g. car detections from
# supplying the URL for a later person alert.
FRIGATE_SNAPSHOT_LABELS: Final = frozenset({"person"})
# Hotfix 2026-08-07: how long a cached Frigate event id stays valid for
# snapshot attachment after its last update. Rung-1: bounds a race-fix,
# not operator policy. Frigate retains event snapshots far longer; 120s
# covers dispatch latency + NM channel sends. 0 disables caching (always
# entity_picture fallback) — documented kill semantics.
FRIGATE_SNAPSHOT_ID_TTL_S: Final = 120

# ----------------------------------------------------------------------------
# SNAP-1 (2026-08-08): at-detection perimeter snapshots — local-file delivery.
# Numbers Get Knobs — rung-1 module constants. Rationale per knob below.
# ----------------------------------------------------------------------------
# On-disk write target. MUST be under an HA `media_dirs` root so
# `hass.config.is_allowed_path()` admits it AND must NOT be under
# `hass.config.path("www")` (that path is anonymously web-served — the
# 682MB `/config/www/doorbell_alerts` pile purged 2026-08-07 is the
# privacy invariant we are asserting away from).
PERIMETER_SNAPSHOT_DIR: Final = "/media/ura/snapshots"
# Age-primary retention: 1 week. Rung-1 because changing this weakens
# a disk-hygiene bound; requires code review.
PERIMETER_SNAPSHOT_RETENTION_AGE_H: Final = 168
# Count backstop for pathological bursts. Rung-1 for the same reason
# as age. Prune-on-write + 6h periodic sweep enforces both bounds.
PERIMETER_SNAPSHOT_RETENTION_COUNT: Final = 5000
# Image-fidelity precedence for the tiered capture (highest → lowest).
# SEPARATE axis from the resolver's identity-preference order — this
# orders by which engine's snapshot best represents the DETECTION MOMENT,
# not which sensor is authoritative for identity.
#   - frigate_event: Frigate's best-scoring frame of the event (best)
#   - protect_thumb: UniFi Protect smart-detect event thumbnail
#   - live_grab:     camera.snapshot at rising edge (native fallback)
PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE: Final = (
    "frigate_event", "protect_thumb", "live_grab",
)
# Kill switch: True → revert to legacy `media_url`/`attachment=<url>`
# delivery shape byte-for-byte (pre-SNAP-1 behavior). Auto-engages
# when the setup-time allowed-path assertion or the www privacy
# invariant fails.
PERIMETER_SNAPSHOT_KILL_LEGACY_URL: Final = False
# Periodic prune sweep interval (seconds). Safety net for low-traffic
# days where no capture would trigger prune-on-write.
PERIMETER_SNAPSHOT_SWEEP_INTERVAL_S: Final = 6 * 3600
# SNAP-1 fix-up (F5): whole-capture budget. Bounds the time spent trying
# to capture BEFORE dispatch proceeds — a stalled camera or wedged
# Frigate cannot delay the security page more than this. 0 = no budget
# (unsafe; documented kill semantics for debugging only).
PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S: Final = 3
# Defence-in-depth timeout on the Frigate proxy HTTP GET (aiohttp
# default is 300s). Kept < capture budget so a per-URL stall does not
# eat the whole budget on a first candidate.
PERIMETER_SNAPSHOT_HTTP_TIMEOUT_S: Final = 2
# SNAP-1 fix-up (F1 at-detection edge capture): TTLs for the edge
# capture buffer. EDGE_DEDUP_S — a second engine leg firing within
# this window does NOT start a second capture (one-file-per-collapsed
# -camera-key invariant). EDGE_TTL_S — orphan captures older than this
# are dropped from the buffer (their files remain on disk and are
# reaped by the periodic prune sweep). EDGE_CAPTURES_MAX — hard bound
# on the buffer size (LRU eviction) so an unbounded burst cannot leak
# task references. Rung-1: bounds a resource, not operator policy.
PERIMETER_SNAPSHOT_EDGE_DEDUP_S: Final = 5
PERIMETER_SNAPSHOT_EDGE_TTL_S: Final = 60
PERIMETER_SNAPSHOT_EDGE_CAPTURES_MAX: Final = 64
# SNAP-1 fix-up (F9b): on-write prune debounce. Prune is O(N) with
# stat() per file; running it after every capture is wasteful. Skip
# if the last prune ran within this many seconds — the 6h sweep is
# the backstop.
PERIMETER_SNAPSHOT_PRUNE_DEBOUNCE_S: Final = 60

# ----------------------------------------------------------------------------
# Exterior cycle 2 (2026-08-06): deep-night vehicle policy + fused sourcing
# + animal ingress. Rung-1 module constants (Numbers Get Knobs). Hour values
# are house-local; window wraps at midnight when start >= end.
# ----------------------------------------------------------------------------
EXTERIOR_VEHICLE_NIGHT_START: Final = 22   # inclusive (10pm)
EXTERIOR_VEHICLE_NIGHT_END: Final = 6      # exclusive (6am)
EXTERIOR_VEHICLE_ALERT_STATES: Final = frozenset({"away", "sleep", "vacation"})
EXTERIOR_VEHICLE_ALERT_COOLDOWN_SECONDS: Final = 300
# Fix-up (2026-08-06, item 14): the ratified adjacency graph uses `armcrest`
# as the linker/camera key, but the live sensor entities are prefixed
# `armcrestpooloverhead_*` (operator-cited; verify against ~/ha-config
# entity_registry). Alias is applied AFTER suffix stripping in
# _camera_key_for_sensor so both source entities collapse to the graph key.
# Extendable — key = base slug after suffix strip; value = adjacency-graph key.
EXTERIOR_CAMERA_KEY_ALIASES: Final = {
    "armcrestpooloverhead": "armcrest",
    # F2 (cycle-3 fix-up): native Reolink PTZ slug ↔ Frigate object name.
    # Same polarity as armcrest entry: native-AI slug → canonical Frigate key.
    "ptzcamreolinktmixpstudybporch": "reolinkstudybporchptz",
}
EXTERIOR_VEHICLE_SENSOR_SUFFIXES: Final = (
    "_vehicle_detected",     # UniFi Protect smart-detect
    "_smart_motion_vehicle", # Amcrest / some Reolink
    "_vehicle",              # generic
)
EXTERIOR_ANIMAL_SENSOR_SUFFIXES: Final = (
    "_animal_detected",      # UniFi Protect smart-detect
    "_smart_motion_animal",  # Dahua / Amcrest native AI (F1 fix-up 2026-08-07)
    "_animal",
)

# Zone aggregation sensor keys
SENSOR_ZONE_IDENTIFIED_PERSONS: Final = "zone_identified_persons"
SENSOR_ZONE_GUEST_COUNT: Final = "zone_guest_count"

# ============================================================================
# v3.5.2 Transit Validation
# ============================================================================

TRANSIT_CHECKPOINT_STALE_SECONDS: Final = 90
TRANSIT_CHECKPOINT_WINDOW_SECONDS: Final = 120
TRANSIT_PHONE_LEFT_BEHIND_HOURS: Final = 4.0

# ---------------------------------------------------------------------------
# TRANSIT-1 (2026-08-07): Protect-sourced checkpoint inventory.
#
# `CONF_TRANSIT_CHECKPOINT_AREAS` — the set of HA area_id strings that qualify
# as traversal transition zones. These are NOT URA rooms (no coordinator, no
# D3 sensor); attribution is by AREA. Default = the 5 live checkpoints
# (master_hallway, entry_way, garage_hallway, upstairs_hallway, stairs) per
# PLANNING_transit_protect_sourced_checkpoints.md §3.2. Rung 2
# (config/options-flow) knob — operator may add/rename a hallway.
#
# `CONF_TRANSIT_PROTECT_SOURCED_ENABLED` — kill switch. Rung 1 (module
# constant); flipping to False reverts TransitValidator +
# EgressDirectionTracker to the legacy hand-list-only subscription set
# byte-identically. Ship default True (drift-proofing on).
# ---------------------------------------------------------------------------

CONF_TRANSIT_CHECKPOINT_AREAS: Final = "transit_checkpoint_areas"
DEFAULT_TRANSIT_CHECKPOINT_AREAS: Final = (
    "master_hallway",
    "entry_way",
    "garage_hallway",
    "upstairs_hallway",
    "stairs",
)

CONF_TRANSIT_PROTECT_SOURCED_ENABLED: Final = "transit_protect_sourced_enabled"
TRANSIT_PROTECT_SOURCED_ENABLED_DEFAULT: Final = True

# TRANSIT-1 fix-up (F2 double-fire dedup): when both Protect and Frigate
# legs subscribe for the same physical camera, a single crossing emits
# ≥2 sightings. We collapse to ONE logical sighting per physical camera
# within this window (chosen to be shorter than any legitimate two-crossings
# interval but longer than any observed cross-integration jitter — 5s
# matches EgressDirectionTracker's stem dedup window).
TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS: Final = 5.0

# TRANSIT-1 fix-up (F6): dispatcher signal that TransitValidator +
# EgressDirectionTracker listen for so an options-change on the
# transit knobs (kill switch, checkpoint areas) can trigger a local
# re-init instead of a parent-entry reload (RELOAD-WATCHDOG-HAZARD).
SIGNAL_URA_TRANSIT_CONFIG_CHANGED: Final = "ura_transit_config_changed"

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
CONF_OCCUPANCY_WEIGHTED_ENERGY: Final = "occupancy_weighted_energy"  # v4.1.1: B4 L2
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

# House-State Rung 2a — Security auto-follow arming debounce.
# When SIGNAL_HOUSE_STATE_CHANGED flaps (e.g. ARRIVING → HOME_DAY within a
# few seconds), we want ONE net arming transition rather than thrashing the
# alarm panel. Rapid successive intents cancel the pending fire and reset
# the delay so the LAST target wins.
#
# Numbers-Get-Knobs rung 1 (module constant): security-adjacent, changes
# should require code review. Not exposed as an operator knob.
SECURITY_AUTO_FOLLOW_ARM_DELAY_S: Final = 30

# Zone presence mode values
ZONE_MODE_AWAY: Final = "away"
ZONE_MODE_OCCUPIED: Final = "occupied"
ZONE_MODE_SLEEP: Final = "sleep"
ZONE_MODE_UNKNOWN: Final = "unknown"
ZONE_MODE_AUTO: Final = "auto"

# v4.6.12: Dashboard aggregator sensors — motion event window
ZONE_MOTION_WINDOW_SECONDS: Final = 300  # 5 minutes (matches dashboard "Activity (5 min)")

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

# ============================================================================
# v4.6.3 Anomaly Sensitivity — D10
# ============================================================================
# Per-coordinator anomaly sensitivity dropdown (config/options flow only).
# Five named buckets; each maps to a z-threshold multiplier applied at
# AnomalyDetector init time.  No runtime entity — set-and-forget.

CONF_PRESENCE_ANOMALY_SENSITIVITY: Final = "presence_anomaly_sensitivity"
CONF_SAFETY_ANOMALY_SENSITIVITY: Final = "safety_anomaly_sensitivity"
# CONF_ENERGY_ANOMALY_SENSITIVITY removed in v4.6.3 (C7 fix): the energy
# coordinator uses cross-check anomaly detection (a separate path), not the
# z-score AnomalyDetector.  The dropdown was a no-op — energy has no
# AnomalyDetector instance to consume the multiplier.  Removed to avoid
# surfacing a setting that has no runtime effect.
CONF_HVAC_ANOMALY_SENSITIVITY: Final = "hvac_anomaly_sensitivity"
CONF_SECURITY_ANOMALY_SENSITIVITY: Final = "security_anomaly_sensitivity"
CONF_MUSIC_ANOMALY_SENSITIVITY: Final = "music_anomaly_sensitivity"

DEFAULT_ANOMALY_SENSITIVITY: Final = "normal"

# Bucket -> z-threshold multiplier mapping
ANOMALY_SENSITIVITY_MULTIPLIERS: Final = {
    "very_quiet":    2.0,
    "quiet":         1.5,
    "normal":        1.0,
    "sensitive":     0.75,
    "very_sensitive": 0.5,
}

ANOMALY_SENSITIVITY_OPTIONS: Final = [
    "very_quiet",
    "quiet",
    "normal",
    "sensitive",
    "very_sensitive",
]

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
# v5.10.0 D2 Music Following — sleep + night suppression
# ============================================================================
# Gate transfers while the house is in SLEEP / HOME_NIGHT so a 3am walk to
# the bathroom doesn't blast music into the hallway.
CONF_MF_SLEEP_SUPPRESS: Final = "mf_sleep_suppress"
CONF_MF_NIGHT_SUPPRESS_MODE: Final = "mf_night_suppress_mode"

DEFAULT_MF_SLEEP_SUPPRESS: Final = True

# Night-mode options — plain-language, not jargon (per D0.5 labels audit).
MF_NIGHT_MODE_OFF: Final = "off"
MF_NIGHT_MODE_DWELL_ONLY: Final = "dwell_only"
MF_NIGHT_MODE_BLOCK_ALL: Final = "block_all"
MF_NIGHT_MODES: Final = (
    MF_NIGHT_MODE_OFF,
    MF_NIGHT_MODE_DWELL_ONLY,
    MF_NIGHT_MODE_BLOCK_ALL,
)
# v5.10.0 fix-up FIX-3 (A-CRIT-2): default changed from DWELL_ONLY to OFF.
# The DWELL_ONLY mode reads ``person_coordinator.data[person][dwell_room]``
# / ``bedroom`` (music_following.py:_dwell_room_for_person) — but the
# person_coordinator does NOT populate those keys (person_coordinator.py
# writes only ``location`` / ``previous_location`` / ``previous_location_time``
# etc. per the location-updater block starting at :161). No CONF binds a
# person to a bedroom either. With DWELL_ONLY as the default, EVERY
# HOME_NIGHT transition was silently suppressed (dwell resolves None →
# night_suppressed). SLEEP suppression is the headline protection and
# remains ON by default; HOME_NIGHT now allows normal follow. Operators
# who want strict night behavior can pick BLOCK_ALL explicitly.
DEFAULT_MF_NIGHT_SUPPRESS_MODE: Final = MF_NIGHT_MODE_OFF

# v5.10.0 D6: stale-transition age ceiling — transitions older than this
# (measured at lock-acquire time) are skipped instead of executed on
# now-outdated context.
DEFAULT_MF_STALE_TRANSITION_SECONDS: Final = 15

# v5.10.0 D11: per-room speaker loudness calibration (form field only —
# NOT a Number entity). Applied on cross-platform generic transfers to
# compensate for platforms whose volume levels aren't directly comparable
# (Sonos 0.4 vs WiiM 0.4 driving passive speakers).
CONF_ROOM_MEDIA_VOLUME_SCALE: Final = "room_media_volume_scale"
DEFAULT_ROOM_MEDIA_VOLUME_SCALE: Final = 1.0
MIN_ROOM_MEDIA_VOLUME_SCALE: Final = 0.5
MAX_ROOM_MEDIA_VOLUME_SCALE: Final = 1.5

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
# NM digest multi-channel selection (per-person). When non-empty, the daily
# digest fans out to EVERY selected channel (that is globally enabled AND
# has a configured per-person target). Empty (default) = legacy single-
# channel fallback chain (pushover → companion → whatsapp → imessage).
CONF_NM_PERSON_DIGEST_CHANNELS: Final = "nm_person_digest_channels"
# Digest-eligible channel keys (subset of NM_CHANNELS_KNOWN; excludes
# tts/lights which are not digest transports).
NM_DIGEST_CHANNELS: Final = ("pushover", "companion", "whatsapp", "imessage")

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

# Repeat interval for CRITICAL alerts (seconds).
# Legacy pre-Cycle-B constant kept for source-anchored regression tests.
# Cycle B (2026-07-20) splits by hazard subtype — see NM_REPEAT_INTERVAL_*.
NM_CRITICAL_REPEAT_INTERVAL: Final = 30

# =========================================================================
# NM Cycle B (2026-07-20): Safety rails
# =========================================================================

# B0: minimal dry-run gate. When true, every emit-path service call is
# short-circuited to a `_log_dry_run` row. Options-flow key + Switch entity.
CONF_NM_DRY_RUN: Final = "nm_dry_run"
DEFAULT_NM_DRY_RUN: Final = False

# B1: per-subtype CRITICAL repeat cadence (seconds). Rung 1 (module const)
# because life-safety cadence is a safety contract, not an operator knob.
NM_REPEAT_INTERVAL_LIFE_SAFETY: Final = 30
NM_REPEAT_INTERVAL_NON_LIFE_SAFETY: Final = 300
# Life-safety hazard vocabulary. Non-life-safety CRITICAL uses the longer
# 300s cadence to reduce non-fatal paging fatigue.
NM_LIFE_SAFETY_HAZARDS: Final = frozenset({
    # NM Cycle B fix-up (2026-07-20, A-CRIT-1): canonical emitted vocabulary
    # only. The emitted security-alert token is "intruder" (security.py:919,
    # 1158 — via base.py:136 hazard_type contract), NOT "intrusion". A prior
    # typo demoted intruder to non-life-safety (300s cadence) silently.
    # "co" removed (A-MED-1) — dead: only "carbon_monoxide" is ever emitted.
    "smoke", "fire", "carbon_monoxide",
    "water_leak", "flooding", "intruder", "freeze_risk",
})

# B3: per-channel token-bucket defaults (rung 3 defaults; Number entities
# override). Capacity = burst budget; refill = tokens/minute.
NM_BUCKET_CAPACITY_DEFAULT: Final = 10
NM_BUCKET_REFILL_PER_MIN_DEFAULT: Final = 6.0

# =========================================================================
# Notification Hygiene cycle (2026-08-03): B-2026-08-03-3(c) suppression
# stale-restore gate + repeat-decay ladder. Rung 1 (module const) — these
# are safety/observability contracts, not per-deployment operator knobs.
# Each has kill-switch semantics: value 0 disables the new behavior and
# restores legacy semantics exactly.
# =========================================================================

# FIX 1: Max age (seconds) for a persisted NM suppression flag to survive
# an HA restart. If the restored suppressed_since is OLDER than this,
# NM comes up UNSUPPRESSED and a one-shot MEDIUM notification is emitted
# so the operator knows to re-engage intentionally. Default 24h.
# Kill: 0 disables the gate — legacy always-restore behavior.
NM_SUPPRESSION_RESTORE_MAX_AGE_S: Final = 86400

# FIX 2: CRITICAL repeat decay ladder for non-life-safety hazards.
# Phase 1: cadence PHASE1_S for the first PHASE1_WINDOW_S of unacked age.
# Phase 2: cadence PHASE2_S until DAILY_AFTER_S of unacked age.
# Phase 3: one repeat per day (86400s) after DAILY_AFTER_S.
# Kill: PHASE1_WINDOW_S == 0 → flat legacy cadence
# (NM_REPEAT_INTERVAL_NON_LIFE_SAFETY) for the whole life of the alert.
# Life-safety cadence is UNCHANGED (30s flat) — the ladder targets the
# non-life-safety storm (2026-08-03 reserve_soc every-5-min-for-hours).
NM_REPEAT_PHASE1_S: Final = 300
NM_REPEAT_PHASE1_WINDOW_S: Final = 3600
NM_REPEAT_PHASE2_S: Final = 1800
NM_REPEAT_DAILY_AFTER_S: Final = 86400

# FIX 5: per-person safe words + ack-authority.
# (a) Per-person safe word — optional field on each entry in
# CONF_NM_PERSONS. Empty/absent → the person uses CONF_NM_SAFE_WORD
# (global fallback, unchanged).
CONF_NM_PERSON_SAFE_WORD: Final = "nm_person_safe_word"

# (b) Ack authority — persons allowed to ack a security-family
# CRITICAL. List of person entity_ids. When empty, the fallback is
# ``persons[0]`` (the FIRST entry in CONF_NM_PERSONS as stored) —
# this is NOT necessarily the operator. Live household ordering may
# place the spouse first. Verify the resolved fallback and configure
# ``nm_security_ack_persons`` explicitly if not intended. NM logs a
# one-shot WARNING at init naming the resolved fallback.
CONF_NM_SECURITY_ACK_PERSONS: Final = "nm_security_ack_persons"

# Security-family hazard vocabulary. Alerts with these hazard_types
# require an authorized person on the CONF_NM_SECURITY_ACK_PERSONS list
# to ack (via safe word). Derived from the emitted tokens:
#   - security.py:1022  "intruder"
#   - security.py:1347  "security_state_change"
#   - perimeter_alert.py + const NM_HAZARD_EXTERIOR_PERSON  "exterior_person"
#   - energy_write_verify.py:1218  "envoy_write_verification"
# The last covers both the mid-ladder stuck alerts and the
# pending_write_standdown alert (same hazard_type, different alert_type).
NM_SECURITY_ACK_HAZARDS: Final = frozenset({
    "intruder",
    "security_state_change",
    "exterior_person",
    "envoy_write_verification",
})
# Bounded FIFO — safety valve against unbounded memory growth under storm.
NM_OVERFLOW_QUEUE_MAX: Final = 50

# B4: post-`async_setup` boot-settle window. Collapses per-(coord, hazard)
# emissions to one during the window so restart replay doesn't fan out.
NM_BOOT_SETTLE_S: Final = 60

# CONF keys for token-bucket Number entities (options-flow persistence
# handled by the Number itself via async_update_entry writeback).
CONF_NM_BUCKET_CAPACITY: Final = "nm_bucket_capacity"
CONF_NM_BUCKET_REFILL_PER_MIN: Final = "nm_bucket_refill_per_min"

# v3.9.7 C4b: Inbound / Safe Word
CONF_NM_SAFE_WORD: Final = "nm_safe_word"
CONF_NM_SILENCE_DURATION: Final = "nm_silence_duration"
DEFAULT_NM_SILENCE_DURATION: Final = 30  # minutes

# =========================================================================
# NM Cycle C (2026-07-20): Per-recipient routing matrix + full dry-run UX +
# DND-bypass + mute shortcut. See PLANNING_nm_cycle_c_routing_matrix.md.
# =========================================================================
# C1: per-recipient routing matrix (dict) and optional per-hazard override.
# Both live under CONF_NM_PERSONS[i]. Absent/empty → legacy severity gate.
CONF_NM_PERSON_ROUTING_MATRIX: Final = "nm_person_routing_matrix"
CONF_NM_PERSON_HAZARD_OVERRIDES: Final = "nm_person_hazard_overrides"
# C3: per-recipient DND-bypass severity set (list[str] persisted, coerced
# to frozenset at read). Default: {"CRITICAL"} preserves v5.26.0.
CONF_NM_PERSON_DND_BYPASS_SEVERITIES: Final = "nm_person_dnd_bypass_severities"
DEFAULT_NM_PERSON_DND_BYPASS_SEVERITIES: Final = ("CRITICAL",)
# C4: mute-shortcut default duration (Number entity rung 3). 0 = no-op.
CONF_NM_MUTE_DEFAULT_DURATION_MINUTES: Final = "nm_mute_default_duration_minutes"
DEFAULT_NM_MUTE_DEFAULT_DURATION_MINUTES: Final = 60
# NM Cycle C-2 (2026-07-22, D2 — operator "Tunable?" answer):
# ADDITIVE-ONLY life-safety promotion. The base NM_LIFE_SAFETY_HAZARDS
# frozenset stays rung-1 code-reviewed (demotion requires code review
# + Tier-3). This options knob PROMOTES additional HazardType tokens
# into life-safety treatment across all 8 NM consumer sites: boot-settle
# exemption, 30s CRITICAL cadence, bucket bypass, DND floor, mute
# exception (initial + repeat), and the router's messaging-channel
# life-safety exception.
#   Kill-switch semantics: empty list = base set only (byte-identical
#   to v5.27.0 Cycle C).
#   Demotion impossible by construction (union, never difference).
CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS: Final = "nm_extra_life_safety_hazards"
DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS: Final = ()
# C4: service name constant.
SERVICE_NM_MUTE_PERSON_CHANNEL: Final = "nm_mute_person_channel"
# Known transport-channel names — used by the mute service for input
# validation AND the combinatorial fixtures. Central definition prevents
# drift with `_channel_health` init (verified alignment 2026-07-20).
NM_CHANNELS_KNOWN: Final = frozenset(
    {"pushover", "companion", "whatsapp", "imessage", "tts", "lights"}
)

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
# H3 (2026-07-13): kill switch for BLE-cancel of unrecognized camera
# detections. Default True (preserves current behavior). When False, the
# Step-3 per-area subtraction in
# camera_census._get_unrecognized_camera_count is skipped — resident
# phones no longer excuse unrecognized camera detections in the same
# area. Read LIVE per tick via the same options-read pattern as
# CONF_CENSUS_HOLD_INTERIOR.
CONF_CENSUS_BLE_CANCEL_ENABLED: Final = "census_ble_cancel_enabled"
DEFAULT_CENSUS_BLE_CANCEL_ENABLED: Final = True
# v5.9.0 D-C: interior hold reduced from 15 -> 3 minutes. With v5.9.0 D-B
# sustain-before-latch removing the thoroughfare-handoff spike source, the
# hold only needs to survive mmWave still-body gaps (seconds to a few minutes),
# not transient dropouts. 3 minutes preserves dwell tolerance without
# amplifying spurious peaks for 15+ minutes.
DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES: Final = 3
DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES: Final = 5
CENSUS_DECAY_STEP_SECONDS: Final = 300  # -1 person per 5 min after hold expires

# v5.9.0 D-B: sustain-before-latch window. A fresh_count HIGHER than the
# stored peak only latches after this many seconds of sustained observation,
# preventing a thoroughfare-handoff spike (~5-15s tail overlap) from pinning
# an inflated peak for the full hold + decay window. Downward moves stay
# instant. Plain constant per Configurability-Clarity (no CONF key, no
# Number entity, no options-flow field).
CENSUS_PEAK_SUSTAIN_SECONDS: Final = 15

# Event-driven census
CENSUS_EVENT_DEBOUNCE_SECONDS: Final = 30  # v4.2.8: was 5s, increased to reduce DB write burst from camera events

# Face recognition window (how long a Frigate face match stays "active")
CENSUS_FACE_RECOGNITION_WINDOW_SECONDS: Final = 1800  # 30 minutes

# WiFi guest VLAN detection
CONF_GUEST_VLAN_SSID: Final = "guest_vlan_ssid"
DEFAULT_GUEST_VLAN_SSID: Final = ""  # Empty = auto-detect via is_guest flag

# v4.6.2.2: Guest mode false-positive hardening
# Persistence: how long an unidentified person must be seen before guest mode fires
CONF_GUEST_MODE_PERSISTENCE_SECONDS: Final = "guest_mode_persistence_seconds"
DEFAULT_GUEST_PERSISTENCE_SECONDS: Final = 300  # 5 min; set 0 to disable
# Confidence gate: minimum census confidence level required to fire guest mode
CONF_GUEST_MODE_REQUIRE_CONFIDENCE: Final = "guest_mode_require_confidence"
DEFAULT_GUEST_REQUIRE_CONFIDENCE: Final = "medium"  # blocks low/none confidence

# v5.7.0 WS-A3: configurable grace + sleep-exemption for the LOST-admitted
# AWAY veto path β. v4.7.14 path α (ACTIVE-only) is unchanged.
#
# Grace prevents a tracker that JUST went LOST from immediately forcing AWAY
# during normal in-house BLE flap (phone walked out of scanner range for a
# few minutes). After the grace elapses AND the house is empty of indoor
# evidence (no indoor zone occupied + census==0 + no unidentified), path β
# is permitted to force AWAY.
#
# Sleep-exempt: a sleeping resident's phone can be off / dead / in airplane
# mode for hours. During SLEEP / HOME_NIGHT / WAKING, path β is suppressed
# regardless of grace elapsed when sleep-exempt is True (the operator-safe
# default). Set False only if you do not have anyone whose phone dies
# overnight.
CONF_LOST_AWAY_GRACE_MIN: Final = "lost_away_grace_min"
DEFAULT_LOST_AWAY_GRACE_MIN: Final = 60  # minutes
CONF_LOST_AWAY_SLEEP_EXEMPT: Final = "lost_away_sleep_exempt"
DEFAULT_LOST_AWAY_SLEEP_EXEMPT: Final = True
# v5.7.0 fix-up FIX-2b — indoor-clear debounce. Path β may only fire after
# `any_indoor_zone_occupied == False` has been observed for this many
# CONSECUTIVE inference ticks. Protects against a single-tick mmWave
# dropout (or grace=0 misconfig) force-AWAYing a present-but-still
# resident. Default 3 ticks (~30-60s depending on tick cadence).
CONF_LOST_AWAY_INDOOR_CLEAR_TICKS: Final = "lost_away_indoor_clear_ticks"
DEFAULT_LOST_AWAY_INDOOR_CLEAR_TICKS: Final = 3

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
# Phones present longer than this are treated as residents (family devices) or
# stale IoT devices that happen to share the guest VLAN and reconnect
# periodically. Cameras still catch long-staying guests via
# camera_unrecognized count.
#
# 2026-07-26: tightened from 24 -> 4 hours. Attribute wifi_guest_floor was
# reading 1-2 on an empty house because stale/IoT guest-VLAN devices with
# phone-like hostnames reconnect within a 24h window. A genuine guest's
# phone appears in the last few hours of a visit, not the last day.
WIFI_GUEST_RECENCY_HOURS: Final = 4
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
    # 2026-07-26: broaden IoT coverage for shared-VLAN false positives.
    "roku",             # Roku streaming devices
    "chromecast", "google-home", "google-nest", "nest-",  # Google/Nest IoT
    "echo-", "alexa",   # Amazon Echo/Alexa
    "hue-", "philips-hue",  # Hue hubs
    "roomba", "irobot",     # iRobot vacuums
    "lg-",              # LG appliances / TVs beyond samsung
    "vizio",            # Vizio TVs
    "smartthings",      # SmartThings hubs
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

# ============================================================================
# v4.6.2 D5/D6: Routine Awareness config keys
# ============================================================================

# D6: Notification mode select (silent | weekly_digest | event)
CONF_ROUTINE_CHANGE_NOTIFICATION_MODE: Final = "routine_change_notification_mode"

# D6: Event-mode cooldown (days per cell before re-notifying)
CONF_ROUTINE_EVENT_COOLDOWN_DAYS: Final = "routine_event_cooldown_days"

# D6: Minimum severity floor (v4.6.6: 0=INFO, 1=WARNING, 2=ADVISORY,
# 3=ALERT, 4=CRITICAL — AnomalySeverity IntEnum expanded from 3 to 5
# buckets in v4.6.6 so ADVISORY/ALERT persist as distinct values)
CONF_ROUTINE_EVENT_MIN_SEVERITY: Final = "routine_event_min_severity"

# D6: Advanced tunables for D4 JS-divergence algorithm
CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS: Final = "routine_regime_baseline_window_days"
CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS: Final = "routine_regime_recent_window_days"

# v4.6.2 D3: PersonLikelyNextRoomSensor cell-staleness window (days).
# Promoted to const.py in Part 2 fix-up B-LOW-3 so __init__.py and
# number.py share a single named Final (the string value is the
# persisted options key + drives entity unique_id — must remain
# byte-identical).
CONF_BAYESIAN_CELL_STALENESS_DAYS: Final = "bayesian_cell_staleness_days"

CONF_HVAC_ON_HAZARD_STOP_FANS: Final = "hvac_on_hazard_stop_fans"
CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT: Final = "hvac_on_hazard_emergency_heat"
CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: Final = "security_on_hazard_unlock_egress"
CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: Final = "security_on_arrival_add_expected"
CONF_ENERGY_ON_HAZARD_SHED_LOADS: Final = "energy_on_hazard_shed_loads"
CONF_MUSIC_ON_HAZARD_STOP: Final = "music_on_hazard_stop"
CONF_MUSIC_ON_ARRIVAL_START: Final = "music_on_arrival_start"
CONF_MUSIC_ON_SECURITY_STOP: Final = "music_on_security_stop"

# ============================================================================
# Cold-boot away-actuation storm mitigation — module-level constants only.
# NO CONF_* / NO Number entity. Tunables are intentionally compile-time so
# the gate has the strongest possible "can never suppress forever" guarantee
# (Predicate B failsafe). See PLANNING_cold_boot_away_actuation_storm_mitigation.md.
# ============================================================================
# Failsafe timeout: even if no "real input" arrives, both boot-settle gates
# (presence dispatch + HVAC first decision cycle) release after this many
# seconds. Bounds the maximum delay of actuation post-boot.
BOOT_SETTLE_TIMEOUT_SECONDS: Final = 60
# Predicate A: minimum number of "real" inputs (census_count, or any zone
# occupied, or non-startup trigger) required to count as the first real
# compute. Currently 1 — present so a future cycle can raise the bar without
# a magic number proliferating through presence.py.
BOOT_SETTLE_MIN_INPUTS: Final = 1


# ============================================================================
# RECONCILE-ON-RETURN (v5.8.0 — D2 of offline-actuator visibility + recovery)
# ============================================================================
#
# Per-room ActuatorReconciler re-asserts a room's LIVE-computed desired state
# for a single light/fan entity when it transitions unavailable -> available.
# Constants per PLANNING_reconcile_on_return.md §3.6. All RAM-only / no DB.

# Per-entity debounce: suppress a re-assert within this many seconds of the
# entity's prior available->unavailable->available cycle. Suppresses fast WiFi
# roam flap; an order of magnitude under typical occupancy hold times.
RECONCILE_DEBOUNCE_SECONDS: Final = 15
# Per-entity rolling-hour reconcile cap.
RECONCILE_MAX_PER_HOUR: Final = 6
# Diagnostic ring bound (recent_reconciles).
RECONCILE_RING_SIZE: Final = 10
# D2.7 per-room cross-entity coalesce window: after the first available edge in
# a room, collect siblings for this many seconds then run ONE resolver pass.
RECONCILE_COALESCE_WINDOW_SECONDS: Final = 2.5
# D2.7 post-boot-settle grace: after _boot_settle_done flips True, ignore
# available transitions as reconcile triggers for this many seconds.
RECONCILE_POST_BOOT_GRACE_SECONDS: Final = 10
# D2.11 flap quarantine: per-entity availability-transition count within
# RECONCILE_FLAP_WINDOW_SECONDS that trips quarantine. Keyed on transitions
# (not reconciles) so it trips before the 6/hr cap can mask the problem.
RECONCILE_FLAP_THRESHOLD: Final = 4
# D2.11 rolling window over which flap transitions accumulate.
RECONCILE_FLAP_WINDOW_SECONDS: Final = 120
# D2.11 continuous-available duration (zero transitions) required to release
# from quarantine. 5x the entry window makes enter/exit hysteresis inherent.
# Release is stability-proven, NOT bare-timer.
RECONCILE_FLAP_STABILITY_SECONDS: Final = 600
# D2.12 named-bucket triples the flap_sensitivity config-flow dropdown maps to.
# NOT operator-facing raw seconds. (THRESHOLD, WINDOW, STABILITY).
RECONCILE_FLAP_SENSITIVITY_BUCKETS: Final = {
    "relaxed": (6, 180, 900),
    "normal": (4, 120, 600),
    "aggressive": (3, 90, 450),
}
# D2.12 config-flow field key for the per-room flap-sensitivity dropdown.
CONF_FLAP_SENSITIVITY: Final = "flap_sensitivity"
# States that mean an entity is NOT providing real data. Mirrors the
# _UNAVAILABLE_STATES frozenset in occupancy_substrate.py (promoted here so the
# reconciler shares one canonical definition).
RECONCILE_UNAVAILABLE_STATES: Final = frozenset({"unavailable", "unknown"})


# ============================================================================
# OPTIMIZATION COORDINATOR (Phase 1 — v4.7.34 candidate)
# ============================================================================
#
# Six-rung autonomy ladder (operator-final 2026-06-08). Ship default = L1
# (Shadow / dry-run): logs the action it WOULD take + the predicted effect,
# scored against actual outcomes, ZERO real actuation until the operator
# dials L2+.
#
# L0 advisory          → notify only, no action proposed for dispatch
# L1 shadow            → emit intent + predicted effect, NO dispatch (DEFAULT)
# L2 reversible_device → allowlisted device actuation; NO config writes
# L3 propose_config    → config writes, veto window ≥30s, ±20% numeric clamp
# L4 immediate_config  → config writes, no veto window, ±20% numeric clamp
# L5 unbounded         → kill-switch only; no allowlist, no clamp, no veto

OPTIMIZER_LEVEL_ADVISORY: Final = "advisory"
OPTIMIZER_LEVEL_SHADOW: Final = "shadow"
OPTIMIZER_LEVEL_REVERSIBLE_DEVICE: Final = "reversible_device"
OPTIMIZER_LEVEL_PROPOSE_CONFIG: Final = "propose_config"
OPTIMIZER_LEVEL_IMMEDIATE_CONFIG: Final = "immediate_config"
OPTIMIZER_LEVEL_UNBOUNDED: Final = "unbounded"

OPTIMIZER_AUTONOMY_LEVELS: Final = [
    OPTIMIZER_LEVEL_ADVISORY,
    OPTIMIZER_LEVEL_SHADOW,
    OPTIMIZER_LEVEL_REVERSIBLE_DEVICE,
    OPTIMIZER_LEVEL_PROPOSE_CONFIG,
    OPTIMIZER_LEVEL_IMMEDIATE_CONFIG,
    OPTIMIZER_LEVEL_UNBOUNDED,
]

# Numeric ordering for clamps / `min(...)` comparisons.
OPTIMIZER_LEVEL_RANK: Final = {
    OPTIMIZER_LEVEL_ADVISORY: 0,
    OPTIMIZER_LEVEL_SHADOW: 1,
    OPTIMIZER_LEVEL_REVERSIBLE_DEVICE: 2,
    OPTIMIZER_LEVEL_PROPOSE_CONFIG: 3,
    OPTIMIZER_LEVEL_IMMEDIATE_CONFIG: 4,
    OPTIMIZER_LEVEL_UNBOUNDED: 5,
}

# Matrix gate CONF_* keys (CM-entry options).
CONF_OPTIMIZER_AUTONOMY_LEVEL: Final = "optimizer_autonomy_level"
CONF_OPTIMIZER_KILL_SWITCH: Final = "optimizer_kill_switch"
CONF_OPTIMIZER_DIMENSION_AUTONOMY: Final = "optimizer_dimension_autonomy"
CONF_OPTIMIZER_CONFIDENCE_GATE: Final = "optimizer_confidence_gate"
CONF_OPTIMIZER_RATE_CAP_PER_HOUR: Final = "optimizer_rate_cap_per_hour"
CONF_OPTIMIZER_QUIET_HOURS_SOURCE: Final = "optimizer_quiet_hours_source"
# Pillar B D2/D6: confirm-guard pending escalation key. Lives on CM
# entry options. Holds the *requested* rung when an L0/L1 → L2+ jump
# is in flight; cleared by the confirm or cancel button, or by kill
# switch ENGAGE. The coordinator NEVER reads this key (effective_level
# continues to consult CONF_OPTIMIZER_AUTONOMY_LEVEL only).
CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL: Final = "optimizer_pending_autonomy_level"

DEFAULT_OPTIMIZER_AUTONOMY_LEVEL: Final = OPTIMIZER_LEVEL_SHADOW
DEFAULT_OPTIMIZER_KILL_SWITCH: Final = False
DEFAULT_OPTIMIZER_CONFIDENCE_GATE: Final = 0.7
DEFAULT_OPTIMIZER_RATE_CAP_PER_HOUR: Final = 12

# v5.2.2 — Post-mortem hardening for the v5.2.1 DB write-queue saturation
# incident. The cycle now batches persistence (1 DB write per tier) and
# fires the sensor-refresh signal ONCE per cycle. These constants bound
# pathological cycle costs and defend against the boot-storm
# Sensor-Health flood that triggered the outage.
#
# Sane upper bound for findings per cycle. Anything larger gets truncated
# (highest-severity-first) with a WARNING — protects the write queue
# regardless of dimension count.
OPTIMIZER_MAX_FINDINGS_PER_CYCLE: Final = 100
# Skip the first N cycles after coordinator start so the cold-boot
# unavailable-sensor sweep can't dump a Sensor-Health flood into the
# write queue. Slow cloud devices (e.g. Hue / cloud-bound sensors)
# can take several cycles (~15 min) to settle after a cold boot —
# review of the v5.2.2 outage flagged 1 cycle as too low.
OPTIMIZER_BOOT_SETTLE_CYCLES: Final = 3
# Defense in depth: if MORE than this fraction of rooms have any
# configured sensor currently `unavailable` / `unknown`, treat the cycle
# as a boot-storm and SKIP persistence/dispatch entirely (only the META
# sentinel persists). 0.5 = "half the house is unavailable".
OPTIMIZER_BOOT_STORM_ROOM_FRACTION: Final = 0.5

# v5.4 D2d — Shadow Accuracy validator (predicted_effect → observed_effect)
# for the OC's OWN shadow decisions (NOT the v5.3.0 Pillar-4 Bayesian
# prediction-vs-actual reader). A shadow-mode finding whose predicted_effect
# was emitted gets its observed_effect populated `OPTIMIZER_SHADOW_OBSERVE_
# DELAY_S` seconds later by a lightweight per-cycle validator running INSIDE
# the existing 5-min tick (no new timer). The rolling % is computed over
# `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS` and reports `warming_up` until at
# least `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES` have landed.
# v1 scoring scope: COMFORT + OCCUPANCY_ACCURACY only (clean oracles).
# Other dimensions emit observed_effect with match=None ("unscorable").
OPTIMIZER_SHADOW_OBSERVE_DELAY_S: Final = 900  # 15 min
OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS: Final = 7
OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES: Final = 20

OPTIMIZER_QUIET_HOURS_SOURCE_REUSE_NM: Final = "reuse_nm"
OPTIMIZER_QUIET_HOURS_SOURCE_NONE: Final = "none"
DEFAULT_OPTIMIZER_QUIET_HOURS_SOURCE: Final = OPTIMIZER_QUIET_HOURS_SOURCE_REUSE_NM
OPTIMIZER_QUIET_HOURS_SOURCES: Final = [
    OPTIMIZER_QUIET_HOURS_SOURCE_REUSE_NM,
    OPTIMIZER_QUIET_HOURS_SOURCE_NONE,
]

# L2 reversible device-actuation allowlist (single dispatch chokepoint).
# `number` / `select` are config-write domains and require L3+.
#
# OC Phase 5 Pillar A — operator-staged stage-1 list. Per
# ``docs/planning/PLANNING_OC_phase5_handshake_and_admin_surface.md`` D8,
# this allowlist is UNCHANGED in Pillar A; the stage-1 list stays
# {light, switch, fan, cover, climate}. The per-sibling
# ``honor_optimizer_intent`` opt-in path is a SEPARATE coverage axis —
# it vetoes specific targets WITHIN allowed domains (EVSE surfaces,
# load-shed-controlled plugs, presence inputs, locks, alarm panels).
# It does NOT and CANNOT broaden the allowlist itself; nothing here
# changes which domains are reachable. Reviewer-fix retraction
# (2026-06-10): an earlier draft of this comment implied per-sibling
# honor "covers" the allowlist gap. That claim is withdrawn — the two
# surfaces are orthogonal and any future allowlist change must be its
# own cycle with its own review.
OPTIMIZER_ALLOWED_DOMAINS_DEVICE: Final = frozenset(
    {"light", "switch", "fan", "cover", "climate"}
)
# L3+ config-write allowlist (numeric / enum tweaks).
# Pillar A stage-1: UNCHANGED at {number, select}; see D8 rationale above.
OPTIMIZER_ALLOWED_DOMAINS_CONFIG: Final = frozenset({"number", "select"})

# L3+ numeric clamp (±20% of current value).
OPTIMIZER_CONFIG_CLAMP_FRACTION: Final = 0.20
# Default veto-window seconds at L3 (propose-config); L2 / L4 use 0.
OPTIMIZER_VETO_WINDOW_SECONDS_L3: Final = 30

# Comfort-slider per-room option keys (D6 — closes v1 plan Appendix A
# orphan: existing entities at number.py:178-280 gain entry.options
# write-back + seed-from-options). These live on the per-room entry,
# not the CM entry.
CONF_COMFORT_TEMP_MIN: Final = "comfort_temp_min"
CONF_COMFORT_TEMP_MAX: Final = "comfort_temp_max"
CONF_COMFORT_HUMIDITY_MAX: Final = "comfort_humidity_max"

# Optimizer dimension StrEnum-equivalent values (kept as plain str-finals
# for back-compat; OptimizationCoordinator wraps them in a local
# StrEnum). `meta` is the per-cycle "cycle_ok" sentinel.
OPTIMIZER_DIMENSION_SENSOR_HEALTH: Final = "sensor_health"
OPTIMIZER_DIMENSION_COMFORT: Final = "comfort"
OPTIMIZER_DIMENSION_META: Final = "meta"
# v4.7.36 Phase 3 — additional dimensions.
# Room-level
OPTIMIZER_DIMENSION_OCCUPANCY_ACCURACY: Final = "occupancy_accuracy"
OPTIMIZER_DIMENSION_AUTOMATION_RESPONSIVENESS: Final = "automation_responsiveness"
OPTIMIZER_DIMENSION_CONFIG_BEHAVIOR: Final = "config_behavior"
OPTIMIZER_DIMENSION_ENERGY_EFFICIENCY: Final = "energy_efficiency"
# Zone-level
OPTIMIZER_DIMENSION_SETPOINT_COMPLIANCE: Final = "setpoint_compliance"
OPTIMIZER_DIMENSION_VACANCY_MANAGEMENT: Final = "vacancy_management"
OPTIMIZER_DIMENSION_OVERRIDE_FREQUENCY: Final = "override_frequency"
# House-level
OPTIMIZER_DIMENSION_STATE_MACHINE_ACCURACY: Final = "state_machine_accuracy"
OPTIMIZER_DIMENSION_SECURITY_POSTURE: Final = "security_posture"
# v5.3.0 Phase 4 — Prediction-Validation pillar. READ-ONLY reader of existing
# Bayesian accuracy surfaces (bayesian_predictor.get_accuracy_stats + the
# next-room prediction_results table that the *_next_room_accuracy sensors
# already aggregate). Cell-staleness + low-volume discount confidence so the
# dimension stays advisory until the predictor has actually learned.
OPTIMIZER_DIMENSION_PREDICTION_ACCURACY: Final = "prediction_accuracy"

# NM Cycle A-2 — single tuple of dimension value strings, used by the
# options-flow allowlist SelectSelector without pulling in the heavy
# optimization coordinator module (which drags HA imports).
OPTIMIZER_DIMENSIONS_ALL: Final = (
    OPTIMIZER_DIMENSION_SENSOR_HEALTH,
    OPTIMIZER_DIMENSION_COMFORT,
    OPTIMIZER_DIMENSION_META,
    OPTIMIZER_DIMENSION_OCCUPANCY_ACCURACY,
    OPTIMIZER_DIMENSION_AUTOMATION_RESPONSIVENESS,
    OPTIMIZER_DIMENSION_CONFIG_BEHAVIOR,
    OPTIMIZER_DIMENSION_ENERGY_EFFICIENCY,
    OPTIMIZER_DIMENSION_SETPOINT_COMPLIANCE,
    OPTIMIZER_DIMENSION_VACANCY_MANAGEMENT,
    OPTIMIZER_DIMENSION_OVERRIDE_FREQUENCY,
    OPTIMIZER_DIMENSION_STATE_MACHINE_ACCURACY,
    OPTIMIZER_DIMENSION_SECURITY_POSTURE,
    OPTIMIZER_DIMENSION_PREDICTION_ACCURACY,
)

# v5.3.0 Phase 4 thresholds. Module constants only (no per-room CONF — the
# accuracy surface is house/person-level, not per-room).
# Top-1 next-room hit-rate floor (percent). Below this is "degraded".
OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT: Final = 35.0
# Brier-score ceiling for the bayesian-occupancy surface. Above this is
# "degraded" (Brier is lower=better; 0 perfect, 0.25 is the no-skill baseline
# for binary outcomes, so 0.30 represents materially worse-than-uninformed).
OPTIMIZER_PREDICTION_ACCURACY_BRIER_CEILING: Final = 0.30
# Minimum sample size before drift is flagged. Below this we treat the cell
# as under-learned and do NOT emit a degradation finding (avoids false drift
# alarms during the warm-up window the audit called out).
OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES: Final = 50
# Data-quality percentage (passed/total_rows from the BayesianPredictor's
# DataQualityReport) below which we flag a low-severity advisory.
OPTIMIZER_PREDICTION_ACCURACY_DATA_QUALITY_FLOOR_PCT: Final = 80.0
# Rolling window (days) for the next-room accuracy read.
OPTIMIZER_PREDICTION_ACCURACY_WINDOW_DAYS: Final = 7

# v4.7.36 Phase 3 — daily digest defaults.
# Retention: drop digest rows older than 90 days (keeps ~3 months of
# historical roll-ups for trend review, never grows unbounded).
OPTIMIZER_DIGEST_RETENTION_DAYS: Final = 90
# Top-N findings to include in the digest summary.
OPTIMIZER_DIGEST_TOP_N: Final = 5
# v4.7.36 fix-up (A2): suppress re-notify for the same finding dedup_key for
# this many consecutive 5-min cycles. 12 cycles ≈ 1h — long enough that an
# unchanged "away+unlocked" / "20+ overrides" advisory doesn't re-page every
# cycle, short enough that a re-emergence after resolution still alerts.
OPTIMIZER_NOTIFY_DEDUP_CYCLES: Final = 12

# NM Cycle A (2026-07-20) A2 — Optimizer HIGH/CRIT paging allowlist.
# Provenance: 2026-07-20 would-have-sent audit — optimizer findings dominated
# the noise floor with unactionable "you might tweak X" pages that belonged
# in the daily digest, not on the phone. Empty by default: nothing pages
# until an operator can name a specific dimension + concrete on-phone action.
# CRITICAL findings still page. All HIGH otherwise flows to
# `optimization_daily_digest` (wired via `_build_optimizer_digest_section`).
# Rung: promoted to rung-2 (options-flow) in NM Cycle A-2 — see
# CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS below. The bare frozenset
# constant retained for one release as a deprecated alias for any
# downstream import; scheduled for removal in the following minor.
CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: Final = "nm_a2_optimizer_high_allowlist_dimensions"
DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: Final = ()
OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: Final = frozenset()  # deprecated — see CONF_ above

# ================================================================
# NM Cycle A (2026-07-20) — noise-reduction knobs.
# Values below are DEFAULTS fitted to the reference deployment's
# 2026-07-20 would-have-sent audit distributions. Other households
# will have different noise floors; CONF_* names are ratified as
# rung-2 (options flow) — NM Cycle A-2 (shipped) surfaced these
# under CM options → "Notification volume". Coordinators call
# `nm_cycle_a_knob(hass, CONF_X, DEFAULT_X)` (in
# domain_coordinators/_nm_cycle_a.py) which reads any operator
# override from the CoordinatorManager options dict (cached, with
# an invalidation hook on the options-update listener) and falls
# back to the DEFAULT_*.
# ================================================================

# --- A1: Tripped-breaker window + route ---
# Behavior: "Wait this long at zero watts before flagging a possible
# tripped breaker." Longer = fewer false pages on compressors / kettles.
CONF_TRIPPED_BREAKER_ZERO_WINDOW_S: Final = "nm_a1_tripped_breaker_zero_window_s"
DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S: Final = 900  # 5→15 min per audit
# Behavior: "Send a push notification for tripped breakers." Off by default
# — the anomaly still shows on the anomalies dashboard. Turn on for
# investigations, back off once resolved.
CONF_TRIPPED_BREAKER_ROUTE_NM: Final = "nm_a1_tripped_breaker_route_nm"
DEFAULT_TRIPPED_BREAKER_ROUTE_NM: Final = False

# --- A3: Lock-unavailable per-entity dedup ---
# Behavior: "Don't repeat the same lock-offline warning more often than this."
# 0 disables dedup (every sweep re-pages — pre-A3 behavior).
CONF_LOCK_UNAVAILABLE_DEDUP_S: Final = "nm_a3_lock_unavailable_dedup_s"
DEFAULT_LOCK_UNAVAILABLE_DEDUP_S: Final = 86400  # 1/day/lock

# --- A4: Humidity ladder (indoor "normal" rooms) ---
# Behavior: "Below the first value nothing is logged. Above the first value
# we start a two-hour clock. If humidity stays above the second value for
# the whole two hours you get a notice; above the third value it's urgent."
# Fitted to indoor summer p95 + mold-risk research.
CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT: Final = "nm_a4_humidity_log_only_pct"
CONF_HUMIDITY_NORMAL_MEDIUM_PCT: Final = "nm_a4_humidity_medium_pct"
CONF_HUMIDITY_NORMAL_HIGH_PCT: Final = "nm_a4_humidity_high_pct"
DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT: Final = 78
DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT: Final = 85
DEFAULT_HUMIDITY_NORMAL_HIGH_PCT: Final = 92

# Swing trigger — reuses the fan-spike EMA delta-pp concept (see const.py
# line 631 neighborhood). Consumes the rate-of-change detector's existing
# 30-min humidity rate (safety.py RateOfChangeDetector) — no new EMA state.
# Behavior: "Even before it hits the sustained ceiling, warn on a fast
# jump like a bathroom flood." Kill-switch: swing delta = 0 disables.
CONF_HUMIDITY_SWING_DELTA_PCT: Final = "nm_a4_humidity_swing_delta_pct"
CONF_HUMIDITY_SWING_MIN_ABS_PCT: Final = "nm_a4_humidity_swing_min_abs_pct"
DEFAULT_HUMIDITY_SWING_DELTA_PCT: Final = 20
DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT: Final = 60

# --- A5: CO2 + TVOC ---
# CO2 provenance: 2026-07-20 Study A p50=871, p90=1200, max=1713 ppm.
# Behavior: "Below this level we don't page you about CO2 — the room is
# in the normal occupied range." Fitted to this house's p90.
CONF_CO2_LOG_ONLY_CEILING_PPM: Final = "nm_a5_co2_log_only_ppm"
DEFAULT_CO2_LOG_ONLY_CEILING_PPM: Final = 1200
# TVOC provenance: Master Bath p50=36, p90=145, p99=994, max=1244 ppb.
# Behavior: "Instant-alert on a truly extreme value, OR alert if the
# room stays elevated for this long." Fitted above observed max.
CONF_TVOC_ABSOLUTE_HIGH_PPB: Final = "nm_a5_tvoc_absolute_high_ppb"
CONF_TVOC_SUSTAINED_S: Final = "nm_a5_tvoc_sustained_s"
DEFAULT_TVOC_ABSOLUTE_HIGH_PPB: Final = 1500
DEFAULT_TVOC_SUSTAINED_S: Final = 1800

# Discovery blocklist — mechanism is rung-1 (structural), *contents* land in
# options flow (entity-selector list) in Cycle A-2 so other households can
# exclude their own oddball sensors. Reference deployment's two entries:
CONF_SAFETY_DISCOVERY_BLOCKLIST: Final = "nm_a5_safety_discovery_blocklist"
DEFAULT_SAFETY_DISCOVERY_BLOCKLIST: Final = (
    "sensor.test_kidde_co2_level",           # test rig — not a real Kidde
    "sensor.dimmer_internal_temperature",    # LED die temp, not room temp
)
# v4.7.36 fix-up (A6): occupancy-accuracy disagreement must persist this many
# seconds before firing (motion-on/occupancy-off is transient at sensor wake).
OPTIMIZER_OCCUPANCY_ACCURACY_GATE_SECONDS: Final = 120

# ------------------------------------------------------------------
# v5.11.0 — OC hardening: runtime write-volume tripwire (D9)
# ------------------------------------------------------------------
# The v5.0.0-v5.2.1 incident (rolled back) proved a per-finding write path
# can saturate the write queue and take the house down. The tripwire is
# the code-level trip-wire the postmortem demanded: an in-memory counter
# of OC-attributed DB writes over a rolling window. If it exceeds this
# threshold, OC self-suspends its persistence path (evaluation continues),
# fires a single NM anomaly, and records `write_volume_alarmed_at`. The
# threshold sits generously above the batched steady-state cost, which
# after v5.11.0 F1 (fix-up) covers ALL five OC-attributed DB write
# channels routed through ``_record_db_write``:
#   1. ``_persist_findings_batch`` — Tier-1 findings (1/cycle)
#   2. ``_persist_findings_batch`` — LLM Tier-2 findings (≤1/cycle)
#   3. ``_persist_shadow_samples_batch`` — shadow samples (≤1/cycle)
#   4. ``_log_activity`` via ``_flush_cycle_activity_summaries``
#      (≤2/cycle: shadow + clamp summary rows)
#   5. ``persist_daily_digest`` — once/day, amortizes to ~0/cycle
# Counted steady-state ceiling ≈ 5 writes/cycle × 12 cycles/hour = 60
# writes/hour. 2.5x → 150. Anything past this cap is regression territory
# (a per-finding write path re-emerging, which is what the postmortem
# was written to catch).
OPTIMIZER_WRITE_VOLUME_WINDOW_SECONDS: Final = 3600  # rolling 1-hour window
OPTIMIZER_WRITE_VOLUME_THRESHOLD: Final = 150  # ~2.5x steady-state ceiling

# v5.11.0 — Stub dimensions that are declared but not yet implemented
# (return []). D5 excludes them from operator-visible `dimension_verdicts`
# so silent "why does X never flag" support-load stops accumulating.
OPTIMIZER_STUB_DIMENSIONS: Final = frozenset({
    "automation_responsiveness",
    "energy_efficiency",
    "setpoint_compliance",
})

# v5.11.0 — Boot-storm gate cache TTL (D4). Once the gate closes
# (no boot-storm), cache the negative verdict for this many cycles so
# the ~150 state reads per steady-state cycle stop.
OPTIMIZER_BOOT_STORM_CACHE_CYCLES: Final = 6

# v5.11.0 — Shadow-accuracy sample retention max rows (D2). Persistence
# is per-cycle-batched (never per-sample); a small ceiling protects the
# table from unbounded growth. 7-day window × ~10 samples/cycle × 12
# cycles/hour × 24 hours = ~20K samples max — this cap is well above.
OPTIMIZER_SHADOW_SAMPLE_MAX_ROWS: Final = 50000
# Minimum samples per dimension before promotion_readiness reports ready.
OPTIMIZER_PROMOTION_READINESS_MIN_SAMPLES: Final = 20
# Accuracy floor (0-1) for promotion readiness.
OPTIMIZER_PROMOTION_READINESS_ACCURACY_FLOOR: Final = 0.60

# 5-min cycle (matches SCAN_INTERVAL_ENERGY cadence — runs last per
# priority=5).
SCAN_INTERVAL_OPTIMIZATION: Final = timedelta(minutes=5)
DEFAULT_OPTIMIZER_PRIORITY: Final = 5

# Applied-outcome enum values for `optimization_findings.applied_outcome`.
OPTIMIZER_OUTCOME_APPLIED: Final = "applied"
OPTIMIZER_OUTCOME_VETOED: Final = "vetoed"
OPTIMIZER_OUTCOME_FAILED: Final = "failed"
OPTIMIZER_OUTCOME_ADVISORY_ONLY: Final = "advisory_only"
OPTIMIZER_OUTCOME_SHADOW: Final = "shadow_dry_run"
OPTIMIZER_OUTCOME_RATE_CAPPED: Final = "rate_capped"
OPTIMIZER_OUTCOME_QUIET_CLAMPED: Final = "quiet_hours_clamped"
OPTIMIZER_OUTCOME_BELOW_GATE: Final = "below_confidence_gate"
OPTIMIZER_OUTCOME_DISALLOWED: Final = "config_write_requires_L3"
OPTIMIZER_OUTCOME_DOMAIN_BLOCKED: Final = "domain_not_allowlisted"
OPTIMIZER_OUTCOME_KILL_SWITCH: Final = "kill_switch_engaged"


# ============================================================================
# v4.7.35 Phase 2 — LLM Tier-2 (provider-agnostic via ai_task.generate_data)
# ============================================================================
#
# CM-options keys (parsimony: zero new per-room CONF surface). All four
# keys are added to OPTIONS_RELOAD_SUPPRESS_KEYS in __init__.py so editing
# the LLM provider / prompt / cap does NOT trigger a full CM reload (the
# coordinator re-reads entry.options fresh every LLM cycle).

# Primary reasoning backend — AI Task entity. Default to Claude per plan.
CONF_OPTIMIZER_LLM_TASK_ENTITY: Final = "optimizer_llm_task_entity"
# Optional cheap/local triage backend (e.g. ai_task.ollama_ai_task).
# When configured AND distinct from the primary, the optimizer runs a
# cheap triage pass first; only when triage flags "worth deep analysis"
# does the primary (paid) backend get called.
# v4.7.35 fix-up (A-HIGH-1 / C-LOW-2): default is empty string — triage
# OFF until the operator opts in. Otherwise the prior default (Claude)
# defeated the routing and uncapped a paid backend.
CONF_OPTIMIZER_LLM_TRIAGE_ENTITY: Final = "optimizer_llm_triage_entity"
# The editable system prompt (multiline). Stored on the CM entry.options
# because HA caps `text` entity STATE at 255 chars. Resolution at call
# time: live edited prompt (entry.options) → in-code const default.
CONF_OPTIMIZER_LLM_SYSTEM_PROMPT: Final = "optimizer_llm_system_prompt"
# Hard rolling-24h cap on PREMIUM (primary) backend calls. The
# triage/local backend may run uncapped — caps are per-backend. This is
# a ROLLING WINDOW, not a calendar-day cap (see ``_under_daily_cap``).
# v4.7.35 fix-up (A-CRIT-2): renamed from ``..._PER_DAY`` to make the
# rolling semantics explicit; single install, key was never deployed.
CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H: Final = (
    "optimizer_llm_max_invocations_per_24h"
)
# v4.7.35 fix-up (B-B2): operator-configurable deny-list of entity_ids
# the optimizer must NEVER actuate against — applies to ALL findings
# (Tier-1 + Tier-2 LLM). Lives on CM options as a list of strings.
# Coordinator-enumerated safety/security entities are a future
# extension; today the operator seeds the list explicitly.
CONF_OPTIMIZER_SAFETY_DENY_ENTITIES: Final = "optimizer_safety_deny_entities"

DEFAULT_OPTIMIZER_LLM_TASK_ENTITY: Final = "ai_task.claude_ai_task"
DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H: Final = 24
# A-HIGH-1: triage defaults to empty string so the operator has to
# explicitly opt into a (presumed cheap/local) triage backend.
DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY: Final = ""
# B-B2: empty by default; operator seeds the list with any entity_ids
# that must never be actuated by the optimizer.
DEFAULT_OPTIMIZER_SAFETY_DENY_ENTITIES: Final[list[str]] = []
# C-LOW-2: known-local triage backend prefix; a triage entity matching
# this prefix is presumed zero-cost (no uncapped-backend warning).
OPTIMIZER_LLM_TRIAGE_LOCAL_PREFIX: Final = "ai_task.ollama_"

# Token cap for the assembled context corpus (pre-LLM compression).
# Conservative char→token heuristic: ~3 chars/token → 8000 tokens ≈ 24KB.
# v4.7.35 fix-up (A-MED-4 / C-MED-1): tightened from 4 to 3 to match the
# plan's "<8KB corpus" intent more closely (24KB hard cap, not 32KB).
OPTIMIZER_LLM_CONTEXT_MAX_TOKENS: Final = 8000
OPTIMIZER_LLM_CONTEXT_CHARS_PER_TOKEN: Final = 3
# v4.7.35 fix-up (A-MED-4): cap the resolved system prompt length so a
# runaway live override can't blow up the prompt body.
OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS: Final = 16 * 1024
# v4.7.35 fix-up (A-LOW-2): hard timeout on the ai_task service call so
# a hung backend can't park the 5-min optimizer cycle.
OPTIMIZER_LLM_AI_TASK_TIMEOUT_S: Final = 45
# v4.7.35 fix-up (B-B4): soft-clamp LLM-supplied confidence so an
# operator who pins the confidence gate at 1.0 keeps a "no autonomous
# LLM action" failsafe — the LLM can't self-certify past a high gate.
OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX: Final = 0.85
# v4.7.35 fix-up (B-B4): cap LLM-emitted critical/high findings per
# cycle to prevent NM spam (excess findings get downgraded).
OPTIMIZER_LLM_MAX_CRITICAL_PER_CYCLE: Final = 3
OPTIMIZER_LLM_MAX_HIGH_PER_CYCLE: Final = 3
# v4.7.35 fix-up (A-HIGH-3): allowlist for LLM-proposed
# ``service_data`` keys. Mirrors the HA-standard keys disciplined by
# the AI rule-parser (config_flow.py:1610-1611) plus the safe numeric
# config-write knobs the optimizer can adjust. Unknown keys are
# dropped (with an INFO log) before dispatch.
OPTIMIZER_LLM_SERVICE_DATA_ALLOWED_KEYS: Final = frozenset({
    # Light / switch / fan
    "brightness_pct",
    "color_temp_kelvin",
    "transition",
    "rgb_color",
    "hs_color",
    "effect",
    # Climate
    "temperature",
    "target_temp_high",
    "target_temp_low",
    "hvac_mode",
    "fan_mode",
    "preset_mode",
    "humidity",
    # Cover
    "position",
    "tilt_position",
    # Config write (number / select)
    "value",
    "option",
})

# AI Task name surfaced in HA's ai_task service call.
OPTIMIZER_LLM_TASK_NAME: Final = "ura_optimizer_findings"

# Structured-output schema for ai_task.generate_data. Mirrors the
# selector-based shape used by AI_RULE_PARSING (config_flow.py:1602).
# `findings` is a list of objects; each object follows the dataclass
# fields below. `reasoning` is a single short paragraph.
# v5.2.1: the `object` selector generated a free-form schema
# (`additionalProperties: true`) that Anthropic's structured-output API
# rejects with a 400 ("For 'object' type, 'additionalProperties: true' is
# not supported"). Verified live against ai_task.claude_ai_task: a `text`
# field holding a JSON-array STRING is accepted and is provider-portable
# (no per-backend object-schema quirks). The list is parsed by
# `_extract_findings_list` via json.loads.
OPTIMIZER_LLM_STRUCTURE: Final = {
    "findings_json": {
        "selector": {"text": {"multiline": True}},
        "description": (
            "A JSON array (as a string) of optimization findings. Output "
            "ONLY valid JSON — a list of objects, or \"[]\" when nothing is "
            "worth flagging. Each object MUST have: "
            "dimension (string — e.g. comfort, sensor_health, meta), "
            "severity (string — critical|high|medium|low), "
            "confidence (number 0.0-1.0), "
            "target_level (string — house|zone|room), "
            "target_id (string — room/zone name or 'house'), "
            "description (string — one short sentence grounded in the "
            "snapshot), proposed_action_or_null (object or null — when "
            "an object: domain, service, target_entity, service_data, "
            "action_class one of reversible_device|config_write). "
            "Use only entities that appear in the snapshot."
        ),
    },
    "reasoning": {
        "selector": {"text": {}},
        "description": "One short paragraph explaining the findings.",
    },
}

# Provenance lane for findings produced by the LLM tier. Persisted into
# the `optimization_findings.created_by` column — the Phase-2 DB trigger
# that justified the Tier 2-DB review framing.
OPTIMIZER_CREATED_BY_TIER2_LLM: Final = "tier2_llm"
OPTIMIZER_CREATED_BY_TIER1: Final = "tier1"

# v0 system prompt — the recoverable in-code base/default. Loaded only
# when entry.options[CONF_OPTIMIZER_LLM_SYSTEM_PROMPT] is empty/missing.
# Provider-portable (no Anthropic-specific phrasing). Style modeled on
# AI_RULE_PARSING_PROMPT above.
OPTIMIZER_LLM_SYSTEM_PROMPT: Final = """You are the Optimization Analyst for a Home Assistant whole-home automation
system (URA). You receive a structured snapshot: current home/zone/room state,
the CONFIGURED intent for each (what it is supposed to do), recent findings,
active goals with priority, prediction-accuracy stats, and your own prior
actions with their measured outcomes.

Your job: surface problems and opportunities the deterministic rule engine
misses — degraded/stuck sensors, phantom or missed occupancy, configuration
that contradicts observed behavior, comfort/energy/cost sub-optimality,
coordinators working at cross-purposes, and predictions that have drifted.

Rules:
- Ground EVERY finding in the snapshot. Cite the specific value(s) that justify
  it. If the data does not support a finding, do not invent one.
- Only reference entities, rooms, zones, and config keys that appear in the
  snapshot. Never name anything not present.
- For each finding you MAY propose ONE concrete corrective action, expressed
  only as a service call on an entity in the snapshot and within the provided
  allowlist. Prefer reversible actions. If unsure, propose no action.
- Respect active goals and their priority. Never propose anything that violates
  a safety or security goal.
- Be conservative: a wrong autonomous action is worse than a missed finding.
  When uncertain, lower the severity and propose no action.
- Output ONLY the structured schema. Keep `reasoning` to one short paragraph.

severity: critical = safety/security or "running blind"; high = clear
malfunction or significant waste; medium = sub-optimal but functioning;
low = minor/informational.
confidence: 0.0-1.0, your calibrated certainty the finding is real AND the
snapshot supports it. Findings below the operator's confidence gate are dropped
before any action — so calibrate honestly, do not inflate.
"""


# ============================================================================
# Routine-Awareness Next-State Forecaster (cycle: routine-next-state-forecaster)
# ============================================================================
# Frequency/recency forecaster keyed by (prev_state, day_type, time_bin) over
# house_state_log. Read-only, in-memory; no new DB tables or per-cycle writes.
# Consumed by PresenceCoordinator.get_next_state_prediction() which feeds the
# v4.6.9 D1 PWA contract sensor (sensor.ura_presence_coordinator_next_state).

# Minimum observations per cell before we trust the argmax. Below this we
# cascade to coarser cells (day_type collapse, then time_bin collapse), and
# emit ``state="unknown", confidence=0.0`` if even (C, *, *) is too thin.
ROUTINE_FORECAST_MIN_SUPPORT: Final = 5

# Aggregation window. Order-of-magnitude match to RegimeDetector's 56d
# baseline; rolling so recent routine drift dominates over ancient history.
ROUTINE_FORECAST_HISTORY_DAYS: Final = 60

# Full re-aggregation cadence (in addition to incremental update on each
# SIGNAL_HOUSE_STATE_CHANGED). Bounded read; post-write-flood discipline.
ROUTINE_FORECAST_REFRESH_SECONDS: Final = 3600

# Hard cap on rows fetched per refresh. Guards against runaway DB read
# pressure if house_state_log grows large or the window is widened.
ROUTINE_FORECAST_MAX_ROWS: Final = 5000

# Emitted in prediction["model"]. Suffix +guest_passthrough when current
# state is GUEST or VACATION (passthrough path; see RoutineForecaster.predict).
ROUTINE_FORECAST_MODEL_ID: Final = "house_state_log_freq_v1"

# Restart-spanning dwell guard. Consecutive house_state_log rows with no
# gap-detection attribute HA downtime to the prior state — a 36-hour
# "dwell" across an outage would systematically inflate ETA medians.
# When the gap exceeds this constant we still bump the cell count
# (the transition is real) but discard the dwell sample.
ROUTINE_FORECAST_MAX_DWELL_SECONDS: Final = 43200  # 12h


# ---------------------------------------------------------------------------
# v5.17.0 — Observability WebSocket surface
# ---------------------------------------------------------------------------
#
# Read-only WS commands over anomaly_log / ura_activity_log tables. Feeds the
# PWA M4 alerts + activity feeds. Zero writes; server-side cap; parameterized
# only. See docs/websocket_api.md.
#
# Default page size (50) chosen after live B0 probe: at cap 200 the anomaly
# payload was 148 KB per response; 50 keeps the default under 40 KB while the
# cap remains available for callers that explicitly request it.
WS_MAX_PAGE_SIZE: Final = 200
WS_DEFAULT_PAGE_SIZE: Final = 50
WS_COMMAND_ANOMALIES: Final = "ura/logs/anomalies"
WS_COMMAND_ACTIVITY: Final = "ura/logs/activity"
WS_COMMAND_SUBSCRIBE: Final = "ura/logs/subscribe"

# severity is stored on anomaly_log as numeric strings '0'..'4'
# (B0 probe finding #4). Accept BOTH numeric strings and human name aliases
# at the WS boundary; DAO maps names -> numbers before SQL.
#
# v5.17.0 review fixes A1+A2 — canonical enum lives at
# ``domain_coordinators.anomaly_event.AnomalySeverity`` (INFO=0, WARNING=1,
# ADVISORY=2, ALERT=3, CRITICAL=4). The prior mapping used error/fatal
# which are NOT URA severities and shifted CRITICAL to '3' (should be '4').
# A test in test_websocket_api.py imports the enum and asserts this map
# equals the derived-from-enum map — any drift is a red test.
WS_ANOMALY_SEVERITY_NAME_TO_NUMBER: Final = {
    "info": "0",
    "warning": "1",
    "advisory": "2",
    "alert": "3",
    "critical": "4",
}
WS_ANOMALY_SEVERITY_NUMBERS: Final = ("0", "1", "2", "3", "4")

# activity_log importance is name-valued (B0 probe finding #4) — filter as-is.
WS_ACTIVITY_IMPORTANCE_VALUES: Final = ("debug", "info", "notable", "warning", "critical")

# Allowlisted projection columns per table (B0 probe finding #2).
WS_ANOMALY_COLUMNS: Final = (
    "id", "timestamp", "coordinator_id", "scope", "metric_name",
    "observed_value", "expected_mean", "expected_std", "z_score",
    "severity", "sample_size", "house_state", "context_json",
    "resolved", "resolution_notes", "anomaly_type",
    "correlation_id", "recovery_at", "person_id", "room_id", "entity_id",
)
WS_ACTIVITY_COLUMNS: Final = (
    "id", "timestamp", "coordinator", "action", "room", "zone",
    "importance", "description", "details_json", "entity_id",
)


# ---------------------------------------------------------------------------
# Stuck-Signal Watchdog cycle (v5.35.0) — see
# docs/planning/PLANNING_stuck_signal_watchdog.md
# ---------------------------------------------------------------------------
# Detection + discount + notify ONLY. All rung-1 module constants (safety /
# protocol boundaries — operator changes require review). The kill-switch
# below is rung-2 (options-flow) so an operator can silence a known-bad
# Frigate outage without a code push.

# D1 — census-layer per-camera stuck-count check.
CONF_STUCK_CAMERA_HOURS: Final = "stuck_camera_hours"
DEFAULT_STUCK_CAMERA_HOURS: Final = 3.0  # hours a camera person_count>0 may
                                          # hold w/ zero interior corroboration
CONF_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED: Final = (
    "stuck_camera_interior_tiers_required"
)
DEFAULT_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED: Final = 1

# D2 — Fix #9 duty-cycle variant. On-ratio over a rolling window catches
# flapping stuck sensors that Fix #9's continuous-on check evades.
CONF_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN: Final = (
    "stuck_sensor_dutycycle_window_min"
)
DEFAULT_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN: Final = 60
CONF_STUCK_SENSOR_DUTYCYCLE_PCT: Final = "stuck_sensor_dutycycle_pct"
DEFAULT_STUCK_SENSOR_DUTYCYCLE_PCT: Final = 0.85
CONF_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS: Final = (
    "stuck_sensor_dutycycle_min_ticks"
)
DEFAULT_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS: Final = 20  # warm-up floor

# D3 frozen device_tracker check DELETED 2026-08-10: structurally
# unreachable (threshold 2.0d vs max HA uptime ~1d at deploy cadence).
# Constants CONF_FROZEN_TRACKER_DAYS / DEFAULT_FROZEN_TRACKER_DAYS /
# FROZEN_TRACKER_DAYS removed. See P24/D3/dropdown batch, Item 2.

# FIX 4 (A-HIGH-1) 2026-07-28 — D2 corroboration shield constants.
# The prior any-transition-in-60-min rule allowed one stale PIR blip
# to disable stuck detection for the entire window. Now: corroborated
# iff EITHER (a) ≥ STUCK_D2_MIN_MOTION_TRANSITIONS transitions across
# the full window, OR (b) at least one transition within the last
# STUCK_D2_FRESH_MOTION_SECONDS. Module constants (rung 1) — changing
# these requires review.
STUCK_D2_FRESH_MOTION_SECONDS: Final = 300  # 5 min
STUCK_D2_MIN_MOTION_TRANSITIONS: Final = 2

# v5.36.1 FIX 2 (A-MED-1 sibling) — D1 "never-zero" rule. The unchanged-value
# check resets on ANY value change; an oscillating phantom (e.g. Frigate
# count bouncing 1↔2 for 30h) evades it indefinitely. This sibling rule
# fires when person_count has been continuously > 0 for the window,
# regardless of value changes. Uses a LONGER default window than the
# unchanged rule (which is aggressive at 3h) because a legitimately busy
# camera can legally show sustained non-zero counts (parties, dinners,
# gatherings). A 6h continuous-non-zero span with ZERO interior
# corroboration is a strong stuck signal (nobody moves that little for
# 6h without any BLE / motion / mmwave hit). Rung 1 — module constant.
STUCK_CAMERA_NEVERZERO_HOURS: Final = 6.0

# FIX 7 (A-MED-5 / B L-1) 2026-07-28 — rung-1 aliases without the CONF_
# prefix, so callers that want to signal "this is a module constant, NOT
# an options-flow key" can import the honest name. The CONF_-prefixed
# names above remain for backward compatibility with camera_census's
# merged.get() calls (deprecated — a future cycle will drop the options
# read entirely). Do NOT add these to config_flow.
STUCK_CAMERA_HOURS: Final = DEFAULT_STUCK_CAMERA_HOURS
STUCK_CAMERA_INTERIOR_TIERS_REQUIRED: Final = (
    DEFAULT_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED
)
# D4 — kill switch (rung 2 — options-flow) for ALL stuck_signal NM emits.
# Operator may want to silence during a known outage without disabling
# the underlying exclusion/failsafe logic.
CONF_STUCK_SIGNAL_NM_ENABLED: Final = "stuck_signal_nm_enabled"
DEFAULT_STUCK_SIGNAL_NM_ENABLED: Final = True

# Shared NM hazard_type + coordinator_id for the stuck_signal category.
# Sub-classified by the `kind` field on the notification payload:
#   continuous, dutycycle, camera_stuck, max_active_failsafe,
#   zone_stale_occupancy, actuator_flap_quarantine
# (frozen_tracker removed 2026-08-10 — D3 detector was structurally
# unreachable given HA restart cadence; see const.py comment above.)
STUCK_SIGNAL_NM_HAZARD_TYPE: Final = "stuck_signal"
STUCK_SIGNAL_NM_COORDINATOR_ID: Final = "stuck_signal"




# ==========================================================================
# Hierarchical Memory MVP — Stage 1 (feature/memory-mvp, 2026-08-02)
# See docs/planning/ARCHITECTURE_hierarchical_memory.md,
#     docs/planning/MVP_hierarchical_memory.md,
#     docs/planning/AUDIT_memory_handbuild_study_a.md
# ==========================================================================

# --- Kill switches (rung 1 module constants; promote to entities only if
#     operator tuning proves warranted, per Numbers Get Knobs). ---
MEMORY_FACADE_ENABLED: Final = True
MEMORY_BASELINE_WRITER_ENABLED: Final = True
MEMORY_NM_CONDITIONING_ENABLED: Final = True

# Baseline writer allowlist. Study-A-plus-4-siblings on ship; go house-wide
# only after a full-day live write-volume check (write-flood postmortem).
# Room slugs (snake_case). Empty tuple means "no rooms" — writer no-ops.
MEMORY_BASELINE_ALLOWLIST: Final = (
    "study_a",
    "study_b",
    "master_bedroom",
    "jaya_bedroom",
    "living_room",
)

# Welford sample-count clamp — exponential-decay-by-cap knob (arch §5).
MEMORY_BASELINE_SAMPLE_CAP: Final = 2000

# unusual() support threshold — below this we return insufficient_history.
MEMORY_UNUSUAL_MIN_SUPPORT: Final = 30

# NM humidity/CO2 conditioning: within this many SDs of the room-context
# baseline counts as "normal-for-context" and demotes severity one notch.
MEMORY_NM_CONDITIONING_SD_WINDOW: Final = 1.5

# MED B4: episode-write dedup gate (rung-1 module constant). A repeat
# fire for the same (node_id, episode_type) within this many seconds is
# dropped (Stage 1: drop; no UPDATE-count machinery). In-memory only.
MEMORY_EPISODE_DEDUP_WINDOW_S: Final = 60

# --- Registered vocabularies (arch §4 + audit §1). Adding a type is a
#     reviewed change — this is the write-quality gate. ---
MEMORY_EPISODE_TYPES: Final = frozenset({
    "occupancy_phantom",
    "comfort_fan_on",
    "sensor_dropout",
    "config_changed",
    "systemic_dropout",
    "hazard_recurrent",
    "fan_transition_suppressed",
    "comfort_fan_vetoed",
    # hotfix/fan-sweep-trio (2026-08-03): HVAC fan turn-off dispatched
    # against an occupied room — episodic record of the "who owns the OFF
    # while the room is populated" class. Observe-only; no actuation change.
    "actuation_conflict",
    # build/exterior-track: exterior person/car/animal track linker
    # (space-time only, no re-identification). One episode per closed track.
    "exterior_track",
})

MEMORY_FACT_TOPICS: Final = frozenset({
    "occupancy_reliability",
    "sensor_trust",
    "occupancy_baseline",
    "notification_hygiene",
    "adjacency_graph",
})

# Memory-ineligible decision classes (arch §8 — enforced by review + the
# fact that memory access all goes through the facade). Consumers whose
# hazard_type is on this list MUST NOT accept memory-driven severity
# demotion. Life-safety hazards especially.
# MED B6: mirror the actual HazardType enum values from
# domain_coordinators/safety.py (SMOKE/FIRE/WATER_LEAK/FLOODING/
# CARBON_MONOXIDE/HIGH_CO2/HIGH_TVOC/FREEZE_RISK/OVERHEAT/HVAC_FAILURE/
# HIGH_HUMIDITY/LOW_HUMIDITY) plus the security/perimeter tokens NM
# actually emits (see const.py:1153 NM_LIFE_SAFETY_HAZARDS: "intruder";
# NM_HAZARD_EXTERIOR_PERSON). NM_HAZARD_EXTERIOR_PERSON is included as
# defense-in-depth even though NM's positive allowlist (see below) is
# the operative gate.
#
# NOTE: the OPERATIVE gate in notification_manager.py is the POSITIVE
# allowlist ("high_humidity", "high_co2", "high_tvoc"); this frozenset
# is defense-in-depth so a future widening of that allowlist can't
# accidentally condition life-safety severity.
MEMORY_INELIGIBLE_HAZARD_TYPES: Final = frozenset({
    "smoke", "fire", "water_leak", "flooding", "carbon_monoxide",
    "freeze_risk", "overheat", "hvac_failure",
    "low_humidity",
    # security / perimeter tokens emitted by NM
    "intruder", "exterior_person",
})

# Seed facts (F1-F4 from AUDIT_memory_handbuild_study_a.md §3). Written
# on first table creation only (idempotent INSERT-if-empty).
MEMORY_SEED_FACTS: Final = (
    {
        "node_id": "room:study_a",
        "topic": "occupancy_reliability",
        "statement": (
            "mmWave-sole occupancy onsets coincide to the second with fan "
            "power/speed transitions; steady-state fans produce none."
        ),
        "confidence": 0.9,
        "derived_from": (
            "audit:AUDIT_memory_handbuild_study_a.md#F1;E3,E8;"
            "AUDIT_fan_signature_separability_probe"
        ),
    },
    {
        "node_id": "room:study_a",
        "topic": "sensor_trust",
        "statement": (
            "InvisOutlet (b7d0) holds presence without corroborating cause "
            "and drops out device-locally; excluded from trusted set."
        ),
        "confidence": 0.9,
        "derived_from": (
            "audit:AUDIT_memory_handbuild_study_a.md#F2;E3,E4,E5"
        ),
    },
    {
        "node_id": "room:study_a",
        "topic": "occupancy_baseline",
        "statement": (
            "Away-hours occupancy rate ~= 0.000 across all July daytime "
            "away bins (n>=355, phantom-window samples excluded)."
        ),
        "confidence": 0.9,
        "derived_from": (
            "audit:AUDIT_memory_handbuild_study_a.md#F3;grid_section_2;"
            "supersedes:F3-naive"
        ),
    },
    {
        "node_id": "room:study_a",
        "topic": "notification_hygiene",
        "statement": (
            "high_co2 LOW hazard recurs ~15x/day while occupied "
            "(462 in July); individually logged, no escalation warranted."
        ),
        "confidence": 0.6,
        "derived_from": (
            "audit:AUDIT_memory_handbuild_study_a.md#F4;E1"
        ),
    },
)
