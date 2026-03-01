"""Safety Coordinator — environmental hazard detection and response.

Monitors smoke, CO, water leak, freeze risk, air quality, temperature
extremes, and humidity. Highest priority coordinator (100) — overrides
all other coordinators during safety events.

v3.6.0-c2: Initial implementation with full hazard type enumeration,
bidirectional rate-of-change detection, room-type-aware humidity
thresholds, flooding escalation, and alert deduplication.

Hazard types (12):
  SMOKE, FIRE, WATER_LEAK, FLOODING, CARBON_MONOXIDE, HIGH_CO2,
  HIGH_TVOC, FREEZE_RISK, OVERHEAT, HVAC_FAILURE, HIGH_HUMIDITY,
  LOW_HUMIDITY

Detection capabilities:
  - Binary sensor discovery (smoke, leak) via entity registry area_id
  - Numeric sensor monitoring (CO, CO2, TVOC, temperature, humidity)
  - Rate-of-change detection (bidirectional, date-based season)
  - Room-type-aware humidity thresholds (normal, bathroom, basement)
  - Flooding escalation (multi-sensor or sustained >15min)
  - Alert deduplication with per-severity suppression windows
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_AREA_ID,
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    ROOM_TYPE_BATHROOM,
)
from .base import (
    BaseCoordinator,
    CoordinatorAction,
    ConstraintAction,
    Intent,
    NotificationAction,
    ServiceCallAction,
    Severity,
)
from .signals import SIGNAL_SAFETY_HAZARD

_LOGGER = logging.getLogger(__name__)

# States that mean an entity is not providing real data
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})


# ============================================================================
# Enums
# ============================================================================


class HazardType(StrEnum):
    """Types of environmental hazards."""

    SMOKE = "smoke"
    FIRE = "fire"
    WATER_LEAK = "water_leak"
    FLOODING = "flooding"
    CARBON_MONOXIDE = "carbon_monoxide"
    HIGH_CO2 = "high_co2"
    HIGH_TVOC = "high_tvoc"
    FREEZE_RISK = "freeze_risk"
    OVERHEAT = "overheat"
    HVAC_FAILURE = "hvac_failure"
    HIGH_HUMIDITY = "high_humidity"
    LOW_HUMIDITY = "low_humidity"


# ============================================================================
# Data classes
# ============================================================================


@dataclass
class Hazard:
    """Represents a detected environmental hazard."""

    type: HazardType
    severity: Severity
    confidence: float
    location: str
    sensor_id: str
    value: Any
    threshold: Any
    detected_at: datetime
    message: str


# ============================================================================
# Thresholds
# ============================================================================

# Numeric sensor thresholds: hazard_type -> {severity: threshold}
# For CO, CO2, TVOC, HUMIDITY: higher value = worse (check >=)
# For FREEZE_RISK: lower value = worse (check <=)
NUMERIC_THRESHOLDS: dict[str, dict[Severity, float]] = {
    HazardType.CARBON_MONOXIDE: {
        Severity.CRITICAL: 100.0,
        Severity.HIGH: 50.0,
        Severity.MEDIUM: 35.0,
        Severity.LOW: 25.0,  # v3.6.0-c2.6: raised from 10 (WHO safe limit) to 25
    },
    HazardType.HIGH_CO2: {
        Severity.HIGH: 2500.0,
        Severity.MEDIUM: 1500.0,
        Severity.LOW: 1000.0,
    },
    HazardType.HIGH_TVOC: {
        Severity.HIGH: 1000.0,
        Severity.MEDIUM: 500.0,
        Severity.LOW: 250.0,
    },
    HazardType.FREEZE_RISK: {
        Severity.HIGH: 35.0,
        Severity.MEDIUM: 40.0,
        Severity.LOW: 45.0,
    },
    HazardType.OVERHEAT: {
        Severity.HIGH: 115.0,
        Severity.MEDIUM: 105.0,
        Severity.LOW: 100.0,  # v3.6.0-c2.6: raised from 95 to reduce false positives
    },
}

# Room-type humidity thresholds
# {room_type: {"low": threshold, "medium": threshold, "high": threshold, "window_hours": hours}}
HUMIDITY_THRESHOLDS: dict[str, dict[str, float]] = {
    # v3.6.0-c2.6: raised normal/basement thresholds to reduce false positives
    "normal": {"low": 70.0, "medium": 80.0, "high": 90.0, "window_hours": 2.0},
    "bathroom": {"low": 80.0, "medium": 85.0, "high": 90.0, "window_hours": 4.0},
    "basement": {"low": 65.0, "medium": 75.0, "high": 85.0, "window_hours": 2.0},
}

# Low humidity thresholds (universal)
LOW_HUMIDITY_THRESHOLDS: dict[Severity, float] = {
    Severity.MEDIUM: 25.0,
    Severity.LOW: 30.0,
}

# Light patterns by hazard type
LIGHT_PATTERNS: dict[str, dict[str, Any]] = {
    "fire": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 250},
    "water_leak": {"color": (0, 0, 255), "effect": "pulse"},
    "co": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 500},
    "freeze": {"color": (100, 150, 255), "effect": "pulse"},
    "warning": {"color": (255, 255, 0), "effect": "pulse"},
}

# Flooding escalation: sustained leak threshold
FLOODING_SUSTAINED_MINUTES = 15


# ============================================================================
# Rate of Change Detector
# ============================================================================


class RateOfChangeDetector:
    """Track sensor history and detect rapid changes.

    Stores last N readings per entity_id. Compares rate over 30-minute
    window. Uses date-based season detection (no HVAC entity dependency).
    Excludes bathrooms from humidity spike detection.
    """

    RATE_THRESHOLDS: dict[str, dict[str, Any]] = {
        "temperature_drop": {
            "rate": -5.0,
            "hazard": HazardType.HVAC_FAILURE,
            "active_season": "heating",
        },
        "temperature_rise": {
            "rate": 5.0,
            "hazard": HazardType.HVAC_FAILURE,
            "active_season": "cooling",
        },
        "temperature_rise_extreme": {
            "rate": 10.0,
            "hazard": HazardType.OVERHEAT,
            "active_season": "any",
        },
        "humidity_rise": {
            "rate": 20.0,
            "hazard": HazardType.WATER_LEAK,
            "active_season": "any",
            "exclude_room_types": ["bathroom"],
        },
    }

    # Window for rate calculation
    WINDOW_MINUTES = 30
    MAX_HISTORY = 60  # readings to keep per entity

    def __init__(self) -> None:
        """Initialize the rate-of-change detector."""
        # entity_id -> deque of (datetime, float)
        self._history: dict[str, deque] = {}

    def record(self, entity_id: str, timestamp: datetime, value: float) -> None:
        """Record a sensor reading."""
        if entity_id not in self._history:
            self._history[entity_id] = deque(maxlen=self.MAX_HISTORY)
        self._history[entity_id].append((timestamp, value))

    def get_rate(self, entity_id: str, now: datetime | None = None) -> float | None:
        """Calculate rate of change over the window period.

        Returns rate in units per 30 minutes, or None if insufficient data.
        """
        history = self._history.get(entity_id)
        if not history or len(history) < 2:
            return None

        if now is None:
            now = dt_util.utcnow()

        window_start = now - timedelta(minutes=self.WINDOW_MINUTES)

        # Find the oldest reading within the window
        oldest_in_window = None
        for ts, val in history:
            if ts >= window_start:
                oldest_in_window = (ts, val)
                break

        if oldest_in_window is None:
            return None

        # Get the most recent reading
        latest = history[-1]

        # Need at least some time difference
        time_diff = (latest[0] - oldest_in_window[0]).total_seconds()
        if time_diff < 60:  # Less than 1 minute - not enough data
            return None

        # Rate per 30 minutes
        value_diff = latest[1] - oldest_in_window[1]
        rate_per_second = value_diff / time_diff
        rate_per_30min = rate_per_second * (30 * 60)

        return rate_per_30min

    def check_thresholds(
        self,
        entity_id: str,
        sensor_type: str,
        room_type: str = "normal",
        now: datetime | None = None,
    ) -> list[tuple[str, HazardType, float]]:
        """Check if rate of change exceeds any thresholds.

        Args:
            entity_id: The sensor entity ID.
            sensor_type: "temperature" or "humidity".
            room_type: Room type for exclusion checks.
            now: Current time (for testing).

        Returns:
            List of (threshold_name, hazard_type, rate) tuples for exceeded thresholds.
        """
        rate = self.get_rate(entity_id, now)
        if rate is None:
            return []

        season = self._get_current_season(now)
        results = []

        for name, config in self.RATE_THRESHOLDS.items():
            # Check sensor type match
            if sensor_type == "temperature" and "temperature" not in name:
                continue
            if sensor_type == "humidity" and "humidity" not in name:
                continue

            # Check season applicability
            active_season = config.get("active_season", "any")
            if active_season != "any" and not self._season_matches(
                season, active_season
            ):
                continue

            # Check room type exclusions
            excluded = config.get("exclude_room_types", [])
            if room_type in excluded:
                continue

            # Check threshold direction
            threshold_rate = config["rate"]
            if threshold_rate > 0 and rate >= threshold_rate:
                results.append((name, config["hazard"], rate))
            elif threshold_rate < 0 and rate <= threshold_rate:
                results.append((name, config["hazard"], rate))

        return results

    @staticmethod
    def _get_current_season(now: datetime | None = None) -> str:
        """Determine current season from date.

        Nov-Mar = 'heating', May-Sep = 'cooling', Apr+Oct = 'shoulder'.
        """
        if now is None:
            now = dt_util.now()
        month = now.month
        if month in (11, 12, 1, 2, 3):
            return "heating"
        elif month in (5, 6, 7, 8, 9):
            return "cooling"
        else:  # April, October
            return "shoulder"

    @staticmethod
    def _season_matches(current_season: str, active_season: str) -> bool:
        """Check if the current season matches the active season.

        Shoulder season matches both heating and cooling.
        """
        if active_season == "any":
            return True
        if current_season == "shoulder":
            return True  # Both directions active in shoulder season
        return current_season == active_season

    def clear(self, entity_id: str | None = None) -> None:
        """Clear history for an entity or all entities."""
        if entity_id is not None:
            self._history.pop(entity_id, None)
        else:
            self._history.clear()


# ============================================================================
# Alert Deduplicator
# ============================================================================


class AlertDeduplicator:
    """Prevent alert fatigue with per-severity suppression windows.

    Tracks the last alert time per hazard key (type:location). A new
    alert is suppressed if it arrives within the suppression window
    for that severity level.
    """

    SUPPRESSION_WINDOWS: dict[Severity, timedelta] = {
        Severity.CRITICAL: timedelta(minutes=1),
        Severity.HIGH: timedelta(minutes=5),
        Severity.MEDIUM: timedelta(minutes=15),
        Severity.LOW: timedelta(hours=1),
    }

    def __init__(self) -> None:
        """Initialize the deduplicator."""
        # hazard_key -> last alert datetime
        self._last_alert: dict[str, datetime] = {}

    def should_alert(self, hazard: Hazard, now: datetime | None = None) -> bool:
        """Check if an alert should be sent for this hazard.

        Returns True if alert should proceed, False if suppressed.
        """
        if now is None:
            now = dt_util.utcnow()

        key = f"{hazard.type.value}:{hazard.location}"
        window = self.SUPPRESSION_WINDOWS.get(hazard.severity, timedelta(hours=1))

        last = self._last_alert.get(key)
        if last is not None and (now - last) < window:
            return False

        self._last_alert[key] = now
        return True

    def clear(self) -> None:
        """Clear all deduplication state."""
        self._last_alert.clear()


# ============================================================================
# Safety Coordinator
# ============================================================================


class SafetyCoordinator(BaseCoordinator):
    """Environmental hazard detection and response coordinator.

    Priority 100 (highest). Monitors smoke, CO, water leak, freeze risk,
    air quality, temperature extremes, and humidity. Can override all other
    coordinators during safety events.

    Sensor discovery:
    - Binary: smoke detectors, leak sensors (via entity registry area_id)
    - Numeric: CO, CO2, TVOC, temperature, humidity sensors

    Detection:
    - Binary hazards: immediate on state change
    - Numeric hazards: threshold-based severity classification
    - Rate-of-change: bidirectional, season-aware
    - Flooding escalation: multi-sensor or sustained >15min
    - Room-type humidity: normal/bathroom/basement thresholds

    Response:
    - CRITICAL: all lights 100%, notify all channels
    - HIGH: targeted response (HVAC override, valve close), notify
    - MEDIUM: request ventilation/dehumidification, notify
    - LOW: log only
    """

    COORDINATOR_ID = "safety"
    PRIORITY = 100

    # v3.6.0-c2.9: Anomaly detection metrics
    # Tracks hazard trigger frequency — detects when sensors fire more or less
    # frequently than historical baseline (e.g., smoke detector triggering
    # more often than normal could indicate a faulty sensor or real issue).
    SAFETY_METRICS = [
        "hazard_trigger_frequency",
        "active_hazard_count",
    ]

    def __init__(
        self,
        hass: HomeAssistant,
        water_shutoff_valve: str | None = None,
        emergency_lights: list[str] | None = None,
    ) -> None:
        """Initialize the Safety Coordinator.

        Args:
            hass: Home Assistant instance.
            water_shutoff_valve: Optional valve entity to close on water leak.
            emergency_lights: Optional light entities for evacuation lighting.
        """
        super().__init__(
            hass,
            coordinator_id=self.COORDINATOR_ID,
            name="Safety Coordinator",
            priority=self.PRIORITY,
        )
        # v3.6.0-c2.1: Configurable entities from CM options
        self._water_shutoff_valve = water_shutoff_valve
        self._emergency_lights = emergency_lights or []

        # Active hazards: key="{type}:{location}" -> Hazard
        self._active_hazards: dict[str, Hazard] = {}
        self._deduplicator = AlertDeduplicator()
        self._rate_detector = RateOfChangeDetector()

        # Discovered sensors
        self._binary_sensors: dict[str, str] = {}  # entity_id -> hazard_type
        self._numeric_sensors: dict[str, str] = {}  # entity_id -> sensor_type
        self._sensor_locations: dict[str, str] = {}  # entity_id -> location
        self._sensor_room_types: dict[str, str] = {}  # entity_id -> room_type

        # Room mapping: room_name -> area_id
        self._room_area_ids: dict[str, str] = {}
        # Room types: room_name -> room_type
        self._room_types: dict[str, str] = {}

        # Leak tracking for flooding escalation
        self._leak_start_times: dict[str, datetime] = {}  # entity_id -> first leak time
        self._active_leak_sensors: set[str] = set()

        # Sustained humidity tracking: entity_id -> first_above_threshold_time
        self._humidity_above_since: dict[str, datetime] = {}
        # v3.6.0-c2.6: Track whether we already fired a hazard for this sustained period
        # Prevents repeated hazard creation on every state change after window expires
        self._humidity_hazard_fired: set[str] = set()  # entity_ids with active fired hazard

        # Diagnostics counters
        self._hazards_detected_24h: int = 0
        self._alerts_sent_24h: int = 0
        self._false_alarms_7d: int = 0
        self._total_hazards_7d: int = 0
        self._last_counter_reset: datetime | None = None
        self._response_times: list[float] = []  # seconds

    @property
    def active_hazards(self) -> dict[str, Hazard]:
        """Return currently active hazards."""
        return dict(self._active_hazards)

    @property
    def sensors_monitored(self) -> int:
        """Return total number of monitored sensors."""
        return len(self._binary_sensors) + len(self._numeric_sensors)

    # =========================================================================
    # Setup
    # =========================================================================

    async def async_setup(self) -> None:
        """Set up the Safety Coordinator.

        Discovers safety-related sensors via entity registry area_id mapping,
        then subscribes to state changes.
        """
        # v3.6.0.3: Instantiate anomaly detector FIRST so it's always
        # available even if discovery fails.
        from .coordinator_diagnostics import AnomalyDetector
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id="safety",
            metric_names=self.SAFETY_METRICS,
            minimum_samples=720,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Could not load safety anomaly baselines", exc_info=True)

        # v3.6.0.3: Wrap discovery/subscription in try/except so partial
        # failures don't prevent the coordinator from functioning.
        try:
            self._build_room_mappings()
            self._discover_sensors()
            self._subscribe_to_sensors()

            # Periodic check for sustained conditions (flooding, humidity)
            unsub = async_track_time_interval(
                self.hass, self._async_periodic_check, timedelta(minutes=1)
            )
            self._unsub_listeners.append(unsub)
        except Exception:
            _LOGGER.exception("Error during safety discovery (non-fatal)")

        _LOGGER.info(
            "Safety Coordinator set up: %d binary sensors, %d numeric sensors",
            len(self._binary_sensors),
            len(self._numeric_sensors),
        )

    def _build_room_mappings(self) -> None:
        """Build room_name -> area_id and room_name -> room_type mappings."""
        try:
            for config_entry in self.hass.config_entries.async_entries(DOMAIN):
                if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                merged = {**config_entry.data, **config_entry.options}
                room_name = merged.get(CONF_ROOM_NAME, "")
                area_id = merged.get(CONF_AREA_ID, "")
                room_type = merged.get(CONF_ROOM_TYPE, "generic")
                if room_name:
                    if area_id:
                        self._room_area_ids[room_name] = area_id
                    self._room_types[room_name] = room_type
        except Exception:
            _LOGGER.debug("Could not build room mappings", exc_info=True)

    def _discover_sensors(self) -> None:
        """Discover safety sensors from URA rooms + global config.

        v3.6.0.3: Scoped discovery. Only monitors sensors from:
        1. URA room-configured areas (entities matching room area_ids)
        2. Global safety devices from config flow
        """
        try:
            from homeassistant.helpers import entity_registry as er

            ent_reg = er.async_get(self.hass)
        except Exception:
            _LOGGER.warning("Could not access entity registry for sensor discovery")
            return

        # Build area_id -> (room_name, room_type) lookup
        area_to_room: dict[str, tuple[str, str]] = {}
        for room_name, area_id in self._room_area_ids.items():
            room_type = self._room_types.get(room_name, "normal")
            area_to_room[area_id] = (room_name, room_type)

        seen_entity_ids: set[str] = set()

        # Source 1: Entities in URA room areas
        for entity in ent_reg.entities.values():
            entity_area_id = getattr(entity, "area_id", None)
            if entity_area_id and entity_area_id in area_to_room:
                self._classify_entity(entity.entity_id, entity, area_to_room)
                seen_entity_ids.add(entity.entity_id)

        # Source 2: Global safety devices from config flow
        global_entities = self._collect_global_entities()
        for entity_id in global_entities:
            if entity_id in seen_entity_ids:
                continue  # Room-discovered takes precedence
            entity = ent_reg.entities.get(entity_id)
            if entity:
                self._classify_entity(entity_id, entity, area_to_room)
                seen_entity_ids.add(entity_id)

        global_only = global_entities - seen_entity_ids
        _LOGGER.info(
            "Safety sensor discovery: %d from rooms, %d global, %d total "
            "(%d binary, %d numeric)",
            len(seen_entity_ids) - len(global_entities) + len(global_only),
            len(global_entities),
            len(seen_entity_ids),
            len(self._binary_sensors),
            len(self._numeric_sensors),
        )

    def _collect_global_entities(self) -> set[str]:
        """Collect globally configured safety device entities from CM config.

        v3.6.0.3: Reads global sensor lists from Coordinator Manager
        config entry options.
        """
        from ..const import (
            CONF_GLOBAL_SMOKE_SENSORS,
            CONF_GLOBAL_LEAK_SENSORS,
            CONF_GLOBAL_AQ_SENSORS,
            CONF_GLOBAL_TEMP_SENSORS,
            CONF_GLOBAL_HUMIDITY_SENSORS,
            ENTRY_TYPE_COORDINATOR_MANAGER,
            CONF_ENTRY_TYPE,
        )
        entities: set[str] = set()
        for config_entry in self.hass.config_entries.async_entries(DOMAIN):
            if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                continue
            merged = {**config_entry.data, **config_entry.options}
            for key in (
                CONF_GLOBAL_SMOKE_SENSORS,
                CONF_GLOBAL_LEAK_SENSORS,
                CONF_GLOBAL_AQ_SENSORS,
                CONF_GLOBAL_TEMP_SENSORS,
                CONF_GLOBAL_HUMIDITY_SENSORS,
            ):
                vals = merged.get(key, [])
                if isinstance(vals, list):
                    entities.update(vals)
                elif isinstance(vals, str) and vals:
                    entities.add(vals)
        return entities

    def _classify_entity(
        self,
        entity_id: str,
        entity: Any,
        area_to_room: dict[str, tuple[str, str]],
    ) -> None:
        """Classify a single entity as a safety sensor if applicable.

        v3.6.0-c2.6: Prefers device_class for classification to avoid
        false positives from substring matching (e.g. "temp" matching
        template sensors). Falls back to entity_id word-boundary matching
        only when device_class is not set.
        """
        import re

        # Determine location from area_id
        entity_area_id = getattr(entity, "area_id", None)
        location = "unknown"
        room_type = "normal"

        if entity_area_id and entity_area_id in area_to_room:
            room_name, room_type = area_to_room[entity_area_id]
            location = room_name
        else:
            # Fallback: try to extract location from entity_id
            location = self._location_from_entity_id(entity_id)

        # Get device_class from entity registry entry
        device_class = getattr(entity, "device_class", None) or ""
        original_device_class = getattr(entity, "original_device_class", None) or ""
        effective_dc = (device_class or original_device_class).lower()

        # Binary sensors: smoke, leak
        if entity_id.startswith("binary_sensor."):
            if effective_dc == "smoke":
                self._binary_sensors[entity_id] = HazardType.SMOKE
                self._sensor_locations[entity_id] = location
                self._sensor_room_types[entity_id] = room_type
            elif effective_dc in ("moisture", "water"):
                self._binary_sensors[entity_id] = HazardType.WATER_LEAK
                self._sensor_locations[entity_id] = location
                self._sensor_room_types[entity_id] = room_type
            else:
                # Fallback to entity_id matching for binary sensors without device_class
                eid_lower = entity_id.lower()
                if re.search(r'\bsmoke\b', eid_lower):
                    self._binary_sensors[entity_id] = HazardType.SMOKE
                    self._sensor_locations[entity_id] = location
                    self._sensor_room_types[entity_id] = room_type
                elif re.search(r'\b(water_?leak|leak)\b', eid_lower):
                    self._binary_sensors[entity_id] = HazardType.WATER_LEAK
                    self._sensor_locations[entity_id] = location
                    self._sensor_room_types[entity_id] = room_type

        # Numeric sensors
        elif entity_id.startswith("sensor."):
            sensor_type = None

            # Prefer device_class classification
            if effective_dc == "carbon_monoxide":
                sensor_type = "co"
            elif effective_dc == "carbon_dioxide":
                sensor_type = "co2"
            elif effective_dc in ("volatile_organic_compounds", "volatile_organic_compounds_parts"):
                sensor_type = "tvoc"
            elif effective_dc == "temperature":
                sensor_type = "temperature"
            elif effective_dc == "humidity":
                sensor_type = "humidity"

            # Fallback: word-boundary matching on entity_id (no substring)
            if sensor_type is None:
                eid_lower = entity_id.lower()
                if re.search(r'\bcarbon_monoxide\b', eid_lower) or re.search(r'\bco_level\b', eid_lower):
                    sensor_type = "co"
                elif re.search(r'\bco2\b', eid_lower) or re.search(r'\bcarbon_dioxide\b', eid_lower):
                    sensor_type = "co2"
                elif re.search(r'\btvoc\b', eid_lower) or re.search(r'\bvolatile\b', eid_lower):
                    sensor_type = "tvoc"
                elif re.search(r'\btemperature\b', eid_lower):
                    # Only match full word "temperature", NOT "temp" which matches template sensors
                    sensor_type = "temperature"
                elif re.search(r'\bhumidity\b', eid_lower):
                    sensor_type = "humidity"

            if sensor_type:
                self._numeric_sensors[entity_id] = sensor_type
                self._sensor_locations[entity_id] = location
                self._sensor_room_types[entity_id] = room_type

    def _discover_sensors_fallback(self) -> None:
        """Fallback sensor discovery using state machine entity IDs.

        v3.6.0-c2.6: Uses device_class from state attributes and word-boundary
        matching to avoid false positives from substring matching.
        """
        import re

        try:
            all_states = self.hass.states.async_all()
        except Exception:
            return

        for state in all_states:
            entity_id = state.entity_id
            location = self._location_from_entity_id(entity_id)
            device_class = (state.attributes.get("device_class") or "").lower()

            if entity_id.startswith("binary_sensor."):
                if device_class == "smoke":
                    self._binary_sensors[entity_id] = HazardType.SMOKE
                    self._sensor_locations[entity_id] = location
                elif device_class in ("moisture", "water"):
                    self._binary_sensors[entity_id] = HazardType.WATER_LEAK
                    self._sensor_locations[entity_id] = location
                else:
                    eid_lower = entity_id.lower()
                    if re.search(r'\bsmoke\b', eid_lower):
                        self._binary_sensors[entity_id] = HazardType.SMOKE
                        self._sensor_locations[entity_id] = location
                    elif re.search(r'\b(water_?leak|leak)\b', eid_lower):
                        self._binary_sensors[entity_id] = HazardType.WATER_LEAK
                        self._sensor_locations[entity_id] = location

            elif entity_id.startswith("sensor."):
                sensor_type = None

                # Prefer device_class
                if device_class == "carbon_monoxide":
                    sensor_type = "co"
                elif device_class == "carbon_dioxide":
                    sensor_type = "co2"
                elif device_class in ("volatile_organic_compounds", "volatile_organic_compounds_parts"):
                    sensor_type = "tvoc"
                elif device_class == "temperature":
                    sensor_type = "temperature"
                elif device_class == "humidity":
                    sensor_type = "humidity"

                # Fallback: word-boundary matching
                if sensor_type is None:
                    eid_lower = entity_id.lower()
                    if re.search(r'\bcarbon_monoxide\b', eid_lower):
                        sensor_type = "co"
                    elif re.search(r'\bco2\b', eid_lower):
                        sensor_type = "co2"
                    elif re.search(r'\btvoc\b', eid_lower):
                        sensor_type = "tvoc"
                    elif re.search(r'\btemperature\b', eid_lower):
                        sensor_type = "temperature"
                    elif re.search(r'\bhumidity\b', eid_lower):
                        sensor_type = "humidity"

                if sensor_type:
                    self._numeric_sensors[entity_id] = sensor_type
                    self._sensor_locations[entity_id] = location

    @staticmethod
    def _location_from_entity_id(entity_id: str) -> str:
        """Extract a location hint from an entity ID."""
        # binary_sensor.kitchen_smoke -> kitchen
        parts = entity_id.split(".", 1)
        if len(parts) < 2:
            return "unknown"
        name = parts[1]
        # Strip common suffixes
        for suffix in (
            "_smoke", "_leak", "_water_leak", "_carbon_monoxide",
            "_co2", "_tvoc", "_temperature", "_temp", "_humidity",
            "_co_level", "_volatile",
        ):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name.replace("_", " ").title() if name else "unknown"

    def _subscribe_to_sensors(self) -> None:
        """Subscribe to state changes for all discovered sensors."""
        all_entity_ids = list(self._binary_sensors.keys()) + list(
            self._numeric_sensors.keys()
        )
        if not all_entity_ids:
            return

        unsub = async_track_state_change_event(
            self.hass, all_entity_ids, self._async_sensor_state_changed
        )
        self._unsub_listeners.append(unsub)

    # =========================================================================
    # State change handler
    # =========================================================================

    @callback
    def _async_sensor_state_changed(self, event: Any) -> None:
        """Handle safety sensor state change."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        state_value = new_state.state
        if state_value in _UNAVAILABLE_STATES:
            return

        # Queue an intent for this sensor change
        from .base import Intent

        intent = Intent(
            source="state_change",
            entity_id=entity_id,
            data={
                "state": state_value,
                "old_state": getattr(
                    event.data.get("old_state"), "state", None
                ),
            },
            coordinator_id=self.COORDINATOR_ID,
        )

        # Get the coordinator manager and queue the intent
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is not None:
            manager.queue_intent(intent)

    # =========================================================================
    # Evaluate
    # =========================================================================

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate safety intents and return proposed actions."""
        if not self._enabled:
            return []

        actions: list[CoordinatorAction] = []

        for intent in intents:
            entity_id = intent.entity_id
            state_value = intent.data.get("state", "")

            hazards = await self._process_sensor(entity_id, state_value)
            for hazard in hazards:
                response_actions = await self._respond_to_hazard(hazard)
                actions.extend(response_actions)

        return actions

    async def _process_sensor(
        self, entity_id: str, state_value: str
    ) -> list[Hazard]:
        """Process a sensor state change and return any detected hazards."""
        hazards: list[Hazard] = []

        # Binary sensor handling
        if entity_id in self._binary_sensors:
            hazard = self._handle_binary_hazard(
                entity_id,
                state_value,
                self._binary_sensors[entity_id],
            )
            if hazard is not None:
                hazards.append(hazard)

        # Numeric sensor handling
        elif entity_id in self._numeric_sensors:
            try:
                value = float(state_value)
            except (ValueError, TypeError):
                return hazards

            sensor_type = self._numeric_sensors[entity_id]
            now = dt_util.utcnow()

            # Record for rate-of-change detection
            self._rate_detector.record(entity_id, now, value)

            # Check numeric thresholds
            if sensor_type == "co":
                hazard = self._handle_numeric_hazard(
                    entity_id, value, HazardType.CARBON_MONOXIDE
                )
                if hazard is not None:
                    hazards.append(hazard)

            elif sensor_type == "co2":
                hazard = self._handle_numeric_hazard(
                    entity_id, value, HazardType.HIGH_CO2
                )
                if hazard is not None:
                    hazards.append(hazard)

            elif sensor_type == "tvoc":
                hazard = self._handle_numeric_hazard(
                    entity_id, value, HazardType.HIGH_TVOC
                )
                if hazard is not None:
                    hazards.append(hazard)

            elif sensor_type == "temperature":
                temp_hazards = self._handle_temperature(entity_id, value, now)
                hazards.extend(temp_hazards)

            elif sensor_type == "humidity":
                humidity_hazards = self._handle_humidity(entity_id, value, now)
                hazards.extend(humidity_hazards)

            # Check rate-of-change thresholds
            room_type = self._sensor_room_types.get(entity_id, "normal")
            roc_results = self._rate_detector.check_thresholds(
                entity_id, sensor_type, room_type, now
            )
            for name, hazard_type, rate in roc_results:
                location = self._sensor_locations.get(entity_id, "unknown")
                hazard = Hazard(
                    type=hazard_type,
                    severity=Severity.MEDIUM,
                    confidence=0.75,
                    location=location,
                    sensor_id=entity_id,
                    value=rate,
                    threshold=self._rate_detector.RATE_THRESHOLDS[name]["rate"],
                    detected_at=now,
                    message=(
                        f"Rapid {sensor_type} change detected in {location}: "
                        f"{rate:.1f}/30min (threshold: "
                        f"{self._rate_detector.RATE_THRESHOLDS[name]['rate']})"
                    ),
                )
                hazards.append(hazard)

        return hazards

    # =========================================================================
    # Binary hazard handling
    # =========================================================================

    def _handle_binary_hazard(
        self,
        entity_id: str,
        new_state: str,
        hazard_type: str,
    ) -> Hazard | None:
        """Handle a binary sensor state change (smoke, leak)."""
        location = self._sensor_locations.get(entity_id, "unknown")

        if new_state != "on":
            # Hazard cleared
            key = f"{hazard_type}:{location}"
            self._active_hazards.pop(key, None)
            # Clear leak tracking
            if hazard_type == HazardType.WATER_LEAK:
                self._leak_start_times.pop(entity_id, None)
                self._active_leak_sensors.discard(entity_id)
            # v3.6.0.3: Push entity updates on hazard clear
            self._notify_entity_update()
            return None

        now = dt_util.utcnow()

        if hazard_type == HazardType.SMOKE:
            severity = Severity.CRITICAL
            message = f"SMOKE DETECTED in {location}!"
            confidence = 0.95
        elif hazard_type == HazardType.WATER_LEAK:
            severity = Severity.HIGH
            message = f"Water leak detected in {location}!"
            confidence = 0.95
            # Track leak start for flooding escalation
            if entity_id not in self._leak_start_times:
                self._leak_start_times[entity_id] = now
            self._active_leak_sensors.add(entity_id)
            # Check flooding escalation
            flooding = self._check_flooding_escalation(now)
            if flooding is not None:
                return flooding
        else:
            severity = Severity.HIGH
            message = f"Hazard: {hazard_type} in {location}"
            confidence = 0.90

        return Hazard(
            type=HazardType(hazard_type),
            severity=severity,
            confidence=confidence,
            location=location,
            sensor_id=entity_id,
            value="on",
            threshold="on",
            detected_at=now,
            message=message,
        )

    def _check_flooding_escalation(self, now: datetime) -> Hazard | None:
        """Check if water leak should be escalated to flooding.

        Escalation triggers:
        1. Multiple leak sensors active simultaneously
        2. Single sensor active for >15 minutes
        """
        # Multi-sensor escalation
        if len(self._active_leak_sensors) >= 2:
            locations = [
                self._sensor_locations.get(eid, "unknown")
                for eid in self._active_leak_sensors
            ]
            return Hazard(
                type=HazardType.FLOODING,
                severity=Severity.CRITICAL,
                confidence=0.95,
                location=", ".join(set(locations)),
                sensor_id=",".join(self._active_leak_sensors),
                value="multiple_sensors",
                threshold="2+ sensors",
                detected_at=now,
                message=(
                    f"FLOODING: Multiple water leak sensors active in "
                    f"{', '.join(set(locations))}!"
                ),
            )

        # Sustained single sensor escalation
        for sensor_id, start_time in self._leak_start_times.items():
            if sensor_id in self._active_leak_sensors:
                duration = (now - start_time).total_seconds() / 60.0
                if duration >= FLOODING_SUSTAINED_MINUTES:
                    location = self._sensor_locations.get(sensor_id, "unknown")
                    return Hazard(
                        type=HazardType.FLOODING,
                        severity=Severity.CRITICAL,
                        confidence=0.90,
                        location=location,
                        sensor_id=sensor_id,
                        value=f"{duration:.0f} minutes",
                        threshold=f"{FLOODING_SUSTAINED_MINUTES} minutes",
                        detected_at=now,
                        message=(
                            f"FLOODING: Sustained water leak in {location} "
                            f"for {duration:.0f} minutes!"
                        ),
                    )

        return None

    # =========================================================================
    # Numeric hazard handling
    # =========================================================================

    def _handle_numeric_hazard(
        self,
        entity_id: str,
        value: float,
        hazard_type: HazardType,
    ) -> Hazard | None:
        """Handle a numeric sensor exceeding thresholds."""
        severity = self._classify_severity(hazard_type, value)
        if severity is None:
            # Below all thresholds — clear any active hazard
            location = self._sensor_locations.get(entity_id, "unknown")
            key = f"{hazard_type}:{location}"
            self._active_hazards.pop(key, None)
            # v3.6.0.3: Push entity updates on hazard clear
            self._notify_entity_update()
            return None

        location = self._sensor_locations.get(entity_id, "unknown")
        threshold = self._get_threshold(hazard_type, severity)

        messages: dict[HazardType, str] = {
            HazardType.CARBON_MONOXIDE: f"CO {value} ppm in {location}",
            HazardType.HIGH_CO2: f"High CO2 ({value} ppm) in {location}",
            HazardType.HIGH_TVOC: f"High TVOC ({value} ppb) in {location}",
        }

        return Hazard(
            type=hazard_type,
            severity=severity,
            confidence=0.85,
            location=location,
            sensor_id=entity_id,
            value=value,
            threshold=threshold,
            detected_at=dt_util.utcnow(),
            message=messages.get(hazard_type, f"{hazard_type.value}: {value}"),
        )

    @staticmethod
    def _classify_severity(hazard_type: HazardType, value: float) -> Severity | None:
        """Classify severity for a numeric sensor value.

        For FREEZE_RISK: lower value = worse (check <=).
        For everything else: higher value = worse (check >=).
        """
        thresholds = NUMERIC_THRESHOLDS.get(hazard_type)
        if thresholds is None:
            return None

        if hazard_type == HazardType.FREEZE_RISK:
            # Lower is worse
            for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
                if sev in thresholds and value <= thresholds[sev]:
                    return sev
        else:
            # Higher is worse
            for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
                if sev in thresholds and value >= thresholds[sev]:
                    return sev

        return None

    @staticmethod
    def _get_threshold(hazard_type: HazardType, severity: Severity) -> float | None:
        """Get the threshold value for a hazard type and severity."""
        thresholds = NUMERIC_THRESHOLDS.get(hazard_type)
        if thresholds is None:
            return None
        return thresholds.get(severity)

    # =========================================================================
    # Temperature handling
    # =========================================================================

    def _handle_temperature(
        self, entity_id: str, value: float, now: datetime
    ) -> list[Hazard]:
        """Handle temperature sensor readings.

        Checks for:
        1. Freeze risk (value <= threshold)
        2. Overheat (value >= threshold)
        Note: Rate-of-change is handled separately in _process_sensor.
        """
        hazards: list[Hazard] = []
        location = self._sensor_locations.get(entity_id, "unknown")

        # Freeze risk
        freeze_severity = self._classify_severity(HazardType.FREEZE_RISK, value)
        if freeze_severity is not None:
            threshold = self._get_threshold(HazardType.FREEZE_RISK, freeze_severity)
            hazards.append(
                Hazard(
                    type=HazardType.FREEZE_RISK,
                    severity=freeze_severity,
                    confidence=0.90,
                    location=location,
                    sensor_id=entity_id,
                    value=value,
                    threshold=threshold,
                    detected_at=now,
                    message=f"Freeze risk: {value}F in {location}",
                )
            )

        # Overheat
        overheat_severity = self._classify_severity(HazardType.OVERHEAT, value)
        if overheat_severity is not None:
            threshold = self._get_threshold(HazardType.OVERHEAT, overheat_severity)
            hazards.append(
                Hazard(
                    type=HazardType.OVERHEAT,
                    severity=overheat_severity,
                    confidence=0.85,
                    location=location,
                    sensor_id=entity_id,
                    value=value,
                    threshold=threshold,
                    detected_at=now,
                    message=f"Overheat warning: {value}F in {location}",
                )
            )

        return hazards

    # =========================================================================
    # Humidity handling
    # =========================================================================

    def _handle_humidity(
        self, entity_id: str, value: float, now: datetime
    ) -> list[Hazard]:
        """Handle humidity sensor readings with room-type-aware thresholds.

        v3.6.0-c2.6: Raised thresholds and added one-shot firing.
        Room type thresholds:
        - Normal: LOW=70, MEDIUM=80, HIGH=90, sustained 2hr
        - Bathroom: LOW=80, MEDIUM=85, HIGH=90, sustained 4hr
        - Basement: LOW=65, MEDIUM=75, HIGH=85, sustained 2hr

        High humidity hazards fire ONCE per sustained period (not on every
        state change after window expires). Cleared when value drops below
        threshold.
        """
        hazards: list[Hazard] = []
        location = self._sensor_locations.get(entity_id, "unknown")
        room_type = self._sensor_room_types.get(entity_id, "normal")

        # Determine effective room type for thresholds
        if room_type == "bathroom":
            thresholds = HUMIDITY_THRESHOLDS["bathroom"]
        elif room_type == "basement":
            thresholds = HUMIDITY_THRESHOLDS["basement"]
        else:
            thresholds = HUMIDITY_THRESHOLDS["normal"]

        # High humidity check with sustained window enforcement
        if value >= thresholds["low"]:
            # Above at least the LOW threshold — start or continue tracking
            if entity_id not in self._humidity_above_since:
                self._humidity_above_since[entity_id] = now

            elapsed_hours = (now - self._humidity_above_since[entity_id]).total_seconds() / 3600.0
            window_hours = thresholds["window_hours"]

            if elapsed_hours >= window_hours:
                # v3.6.0-c2.6: Only fire hazard once per sustained period
                if entity_id not in self._humidity_hazard_fired:
                    self._humidity_hazard_fired.add(entity_id)

                    # Sustained window elapsed — classify severity
                    severity_key = "low"
                    if value >= thresholds["high"]:
                        severity = Severity.HIGH
                        severity_key = "high"
                    elif value >= thresholds["medium"]:
                        severity = Severity.MEDIUM
                        severity_key = "medium"
                    else:
                        severity = Severity.LOW
                        severity_key = "low"

                    hazards.append(
                        Hazard(
                            type=HazardType.HIGH_HUMIDITY,
                            severity=severity,
                            confidence=0.80,
                            location=location,
                            sensor_id=entity_id,
                            value=value,
                            threshold=thresholds[severity_key],
                            detected_at=now,
                            message=f"High humidity: {value}% in {location} sustained {elapsed_hours:.1f}h (room type: {room_type})",
                        )
                    )
        else:
            # Below all thresholds — clear sustained tracking and one-shot flag
            self._humidity_above_since.pop(entity_id, None)
            self._humidity_hazard_fired.discard(entity_id)

        # Low humidity check (universal thresholds, fires immediately)
        low_severity = None
        for sev in (Severity.MEDIUM, Severity.LOW):
            if sev in LOW_HUMIDITY_THRESHOLDS and value <= LOW_HUMIDITY_THRESHOLDS[sev]:
                low_severity = sev
                break

        if low_severity is not None:
            hazards.append(
                Hazard(
                    type=HazardType.LOW_HUMIDITY,
                    severity=low_severity,
                    confidence=0.80,
                    location=location,
                    sensor_id=entity_id,
                    value=value,
                    threshold=LOW_HUMIDITY_THRESHOLDS[low_severity],
                    detected_at=now,
                    message=f"Low humidity: {value}% in {location}",
                )
            )

        return hazards

    # =========================================================================
    # Response actions
    # =========================================================================

    async def _respond_to_hazard(self, hazard: Hazard) -> list[CoordinatorAction]:
        """Generate response actions for a detected hazard.

        Tracks the hazard, generates severity-appropriate actions, and
        handles alert deduplication.
        """
        # Track the hazard
        key = f"{hazard.type.value}:{hazard.location}"
        self._active_hazards[key] = hazard
        self._hazards_detected_24h += 1

        # Generate actions based on severity
        actions: list[CoordinatorAction] = []

        if hazard.severity == Severity.CRITICAL:
            actions.extend(self._critical_response(hazard))
        elif hazard.severity == Severity.HIGH:
            actions.extend(self._high_response(hazard))
        elif hazard.severity == Severity.MEDIUM:
            actions.extend(self._medium_response(hazard))
        else:
            actions.extend(self._low_response(hazard))

        # Send notification if not deduplicated
        if self._deduplicator.should_alert(hazard):
            self._alerts_sent_24h += 1
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=hazard.severity,
                    confidence=hazard.confidence,
                    description=f"Safety alert: {hazard.message}",
                    message=hazard.message,
                    channels=self._get_notification_channels(hazard.severity),
                )
            )

        # Log decision
        if self.decision_logger is not None:
            try:
                await self.decision_logger.log_decision(
                    coordinator_id=self.COORDINATOR_ID,
                    decision_type=f"hazard_{hazard.type.value}",
                    context={"severity": hazard.severity.name, "location": hazard.location},
                    action=hazard.message,
                    scope=hazard.location,
                )
            except Exception:
                pass

        # v3.6.0-c2.9: Record hazard trigger as anomaly observation
        if self.anomaly_detector is not None:
            try:
                scope = hazard.location or "house"
                anomaly = self.anomaly_detector.record_observation(
                    "hazard_trigger_frequency",
                    scope,
                    1.0,  # Each trigger is a count observation
                )
                if anomaly:
                    await self.anomaly_detector.store_anomaly(anomaly)
                # Also record current active hazard count
                anomaly2 = self.anomaly_detector.record_observation(
                    "active_hazard_count",
                    "house",
                    float(len(self._active_hazards)),
                )
                if anomaly2:
                    await self.anomaly_detector.store_anomaly(anomaly2)
            except Exception:
                _LOGGER.debug("Anomaly recording failed", exc_info=True)

        # v3.6.0.3: Push entity updates on hazard change
        self._notify_entity_update()

        return actions

    def _critical_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """CRITICAL severity: Maximum response — designated emergency lights, full alert.

        v3.6.0-c2.8: Only uses explicitly configured emergency lights.
        Never targets entity_id "all" — if no emergency lights are configured,
        the response is notification-only (no light manipulation).
        """
        actions: list[CoordinatorAction] = []

        # Emergency lights: only configured lights, full brightness, white
        if self._emergency_lights:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.CRITICAL,
                    confidence=hazard.confidence,
                    description=f"Emergency lights for {hazard.type.value}",
                    service="light.turn_on",
                    service_data={
                        "entity_id": self._emergency_lights,
                        "brightness": 255,
                    },
                )
            )
        else:
            _LOGGER.warning(
                "CRITICAL hazard (%s) but no emergency lights configured — "
                "skipping light response. Configure emergency lights in "
                "Coordinator Manager → Safety Monitoring.",
                hazard.type.value,
            )

        # Flooding: water shutoff (if configured)
        if hazard.type == HazardType.FLOODING:
            actions.extend(self._water_shutoff_actions(hazard))

        return actions

    def _high_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """HIGH severity: Urgent response — targeted actions."""
        actions: list[CoordinatorAction] = []

        # Freeze risk: override HVAC to heat
        if hazard.type == HazardType.FREEZE_RISK:
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.HIGH,
                    confidence=hazard.confidence,
                    description="Freeze protection — forcing heat",
                    constraint_type="hvac",
                    constraint_data={"mode": "heat", "min_temp": 55},
                )
            )

        # Overheat: override HVAC to cool
        if hazard.type == HazardType.OVERHEAT:
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.HIGH,
                    confidence=hazard.confidence,
                    description="Overheat protection — forcing cooling",
                    constraint_type="hvac",
                    constraint_data={"mode": "cool", "max_temp": 78},
                )
            )

        # Water leak: water shutoff if configured
        if hazard.type in (HazardType.WATER_LEAK, HazardType.FLOODING):
            actions.extend(self._water_shutoff_actions(hazard))

        return actions

    def _medium_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """MEDIUM severity: Prompt response — ventilation, dehumidification."""
        actions: list[CoordinatorAction] = []

        if hazard.type in (HazardType.HIGH_CO2, HazardType.HIGH_TVOC):
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    confidence=hazard.confidence,
                    description=f"Ventilation request for {hazard.type.value}",
                    constraint_type="ventilation",
                    constraint_data={"mode": "boost", "reason": hazard.type.value},
                )
            )

        if hazard.type == HazardType.HIGH_HUMIDITY:
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    confidence=hazard.confidence,
                    description="Dehumidification request",
                    constraint_type="dehumidifier",
                    constraint_data={"mode": "on", "location": hazard.location},
                )
            )

        if hazard.type == HazardType.HVAC_FAILURE:
            actions.append(
                CoordinatorAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    confidence=hazard.confidence,
                    description=f"HVAC failure detected: {hazard.message}",
                )
            )

        return actions

    def _low_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """LOW severity: Advisory — log only."""
        return [
            CoordinatorAction(
                coordinator_id=self.COORDINATOR_ID,
                severity=Severity.LOW,
                confidence=hazard.confidence,
                description=f"Advisory: {hazard.message}",
            )
        ]

    def _water_shutoff_actions(self, hazard: Hazard) -> list[CoordinatorAction]:
        """Generate water shutoff actions if valve is configured."""
        valve_entity = self._water_shutoff_valve
        if valve_entity:
            return [
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=valve_entity,
                    severity=hazard.severity,
                    confidence=hazard.confidence,
                    description="Water shutoff — closing main valve",
                    service="valve.close",
                    service_data={"entity_id": valve_entity},
                )
            ]
        return []

    @staticmethod
    def _get_light_pattern_key(hazard_type: HazardType) -> str:
        """Map hazard type to light pattern key."""
        mapping = {
            HazardType.SMOKE: "fire",
            HazardType.FIRE: "fire",
            HazardType.WATER_LEAK: "water_leak",
            HazardType.FLOODING: "water_leak",
            HazardType.CARBON_MONOXIDE: "co",
            HazardType.FREEZE_RISK: "freeze",
        }
        return mapping.get(hazard_type, "warning")

    @staticmethod
    def _get_notification_channels(severity: Severity) -> list[str]:
        """Get notification channels based on severity."""
        if severity == Severity.CRITICAL:
            return ["imessage", "speaker", "lights"]
        elif severity == Severity.HIGH:
            return ["imessage", "speaker"]
        elif severity == Severity.MEDIUM:
            return ["imessage"]
        return []  # LOW = log only

    # =========================================================================
    # Periodic checks
    # =========================================================================

    @callback
    def _async_periodic_check(self, _now: Any = None) -> None:
        """Periodic check for sustained conditions (flooding escalation)."""
        now = dt_util.utcnow()

        # Check flooding escalation for active leak sensors
        if self._active_leak_sensors:
            flooding = self._check_flooding_escalation(now)
            if flooding is not None:
                key = f"{flooding.type.value}:{flooding.location}"
                if key not in self._active_hazards:
                    self._active_hazards[key] = flooding
                    # Queue intent for the flooding detection
                    manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                    if manager is not None:
                        intent = Intent(
                            source="periodic_check",
                            entity_id="safety.flooding_escalation",
                            data={"hazard_type": "flooding"},
                            coordinator_id=self.COORDINATOR_ID,
                        )
                        manager.queue_intent(intent)

    # =========================================================================
    # Test hazard service
    # =========================================================================

    async def handle_test_hazard(
        self, hazard_type: str, location: str, severity: str
    ) -> None:
        """Handle test_safety_hazard service call.

        Creates a test hazard for notification pipeline verification.
        Does NOT trigger real responses (no HVAC override, no valve close).
        Only sends notifications.
        """
        try:
            h_type = HazardType(hazard_type)
        except ValueError:
            _LOGGER.warning("Invalid hazard type for test: %s", hazard_type)
            return

        try:
            sev = Severity[severity.upper()]
        except (KeyError, AttributeError):
            sev = Severity.MEDIUM

        now = dt_util.utcnow()
        hazard = Hazard(
            type=h_type,
            severity=sev,
            confidence=1.0,
            location=location,
            sensor_id="test",
            value="test",
            threshold="test",
            detected_at=now,
            message=f"TEST: {h_type.value} in {location} (severity: {sev.name})",
        )

        # Only send notification, no real response actions
        if self._deduplicator.should_alert(hazard):
            channels = self._get_notification_channels(sev)
            _LOGGER.info(
                "Test safety hazard: %s in %s (severity: %s, channels: %s)",
                hazard_type,
                location,
                severity,
                channels,
            )

    # =========================================================================
    # Hazard clearing
    # =========================================================================

    def clear_hazard(self, hazard_type: HazardType, location: str) -> None:
        """Clear an active hazard."""
        key = f"{hazard_type.value}:{location}"
        self._active_hazards.pop(key, None)
        # v3.6.0.3: Push entity updates on hazard clear
        self._notify_entity_update()

    def clear_all_hazards(self) -> None:
        """Clear all active hazards."""
        self._active_hazards.clear()
        self._leak_start_times.clear()
        self._active_leak_sensors.clear()
        self._humidity_hazard_fired.clear()
        # v3.6.0.3: Push entity updates on hazard clear
        self._notify_entity_update()

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return diagnostics summary for the Safety Coordinator."""
        summary = super().get_diagnostics_summary()

        summary["active_hazards"] = len(self._active_hazards)
        summary["active_hazard_details"] = {
            key: {
                "type": h.type.value,
                "severity": h.severity.name,
                "location": h.location,
                "detected_at": h.detected_at.isoformat(),
            }
            for key, h in self._active_hazards.items()
        }
        summary["sensors_monitored"] = self.sensors_monitored
        summary["binary_sensors"] = len(self._binary_sensors)
        summary["numeric_sensors"] = len(self._numeric_sensors)
        summary["hazards_detected_24h"] = self._hazards_detected_24h
        summary["alerts_sent_24h"] = self._alerts_sent_24h
        summary["false_alarm_rate"] = (
            self._false_alarms_7d / max(self._total_hazards_7d, 1)
        )
        summary["response_times"] = {
            "count": len(self._response_times),
            "avg_seconds": (
                sum(self._response_times) / len(self._response_times)
                if self._response_times
                else 0.0
            ),
        }

        return summary

    def get_safety_status(self) -> str:
        """Return the overall safety status string."""
        if not self._active_hazards:
            return "normal"

        worst = max(
            (h.severity for h in self._active_hazards.values()),
            default=Severity.LOW,
        )
        if worst == Severity.CRITICAL:
            return "critical"
        elif worst == Severity.HIGH:
            return "alert"
        elif worst == Severity.MEDIUM:
            return "warning"
        # LOW severity = advisory (active hazard, but log-only response)
        return "advisory"

    def get_all_hazards_detail(self) -> list[dict]:
        """Return all active hazards as serializable dicts.

        v3.6.0.3: Full hazard detail for glanceable entities.
        Capped at 20, sorted by severity (critical first).
        """
        SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        hazards = []
        for hazard in self._active_hazards.values():
            hazards.append({
                "hazard_type": hazard.type.value,
                "severity": hazard.severity.name.lower(),
                "location": hazard.location,
                "sensor_id": hazard.sensor_id,
                "value": hazard.value,
                "threshold": hazard.threshold,
                "detected_at": hazard.detected_at.isoformat() if hazard.detected_at else None,
                "message": hazard.message,
            })
        hazards.sort(key=lambda h: SEVERITY_ORDER.get(h["severity"], 99))
        return hazards[:20]

    def get_water_leak_status(self) -> dict:
        """Return water leak status for binary sensor.

        v3.6.0.3: Dedicated water leak glanceable entity.
        """
        leak_hazards = {
            k: v for k, v in self._active_hazards.items()
            if v.type in (HazardType.WATER_LEAK, HazardType.FLOODING)
        }
        if not leak_hazards:
            return {"active": False}

        locations = list(set(h.location for h in leak_hazards.values()))
        sensor_ids = list(set(h.sensor_id for h in leak_hazards.values()))
        flooding = any(h.type == HazardType.FLOODING for h in leak_hazards.values())

        # Find earliest detection time
        detected_times = [
            h.detected_at for h in leak_hazards.values() if h.detected_at
        ]
        first_detected = min(detected_times).isoformat() if detected_times else None

        return {
            "active": True,
            "locations": locations,
            "sensor_ids": sensor_ids,
            "sensor_count": len(sensor_ids),
            "flooding_escalated": flooding,
            "first_detected": first_detected,
        }

    def get_air_quality_status(self) -> dict:
        """Return air quality status for binary sensor.

        v3.6.0.3: Dedicated air quality glanceable entity.
        """
        AQ_TYPES = {HazardType.SMOKE, HazardType.CARBON_MONOXIDE, HazardType.HIGH_CO2, HazardType.HIGH_TVOC}
        aq_hazards = {
            k: v for k, v in self._active_hazards.items()
            if v.type in AQ_TYPES
        }
        if not aq_hazards:
            return {"active": False}

        SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        hazard_types = list(set(h.type.value for h in aq_hazards.values()))
        locations = list(set(h.location for h in aq_hazards.values()))
        sensor_ids = list(set(h.sensor_id for h in aq_hazards.values()))
        severities = [
            h.severity.name.lower()
            for h in aq_hazards.values()
        ]
        worst = min(severities, key=lambda s: SEVERITY_ORDER.get(s, 99))

        return {
            "active": True,
            "hazard_types": hazard_types,
            "locations": locations,
            "sensor_ids": sensor_ids,
            "worst_severity": worst,
        }

    def _notify_entity_update(self) -> None:
        """Fire dispatcher signal to update safety entities.

        v3.6.0.3: Push updates instead of polling.
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        async_dispatcher_send(self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE)

    def get_diagnostics_status(self) -> str:
        """Return diagnostics health status."""
        total_sensors = self.sensors_monitored
        if total_sensors == 0:
            return "degraded"

        # Check how many sensors are available
        available = 0
        for entity_id in list(self._binary_sensors.keys()) + list(
            self._numeric_sensors.keys()
        ):
            try:
                state = self.hass.states.get(entity_id)
                if state and state.state not in _UNAVAILABLE_STATES:
                    available += 1
            except Exception:
                pass

        if available >= total_sensors:
            return "healthy"
        elif available >= total_sensors * 0.5:
            return "degraded"
        return "degraded"

    # =========================================================================
    # Teardown
    # =========================================================================

    async def async_teardown(self) -> None:
        """Tear down the Safety Coordinator."""
        self._cancel_listeners()
        self._active_hazards.clear()
        self._deduplicator.clear()
        self._rate_detector.clear()
        self._leak_start_times.clear()
        self._active_leak_sensors.clear()
        self._humidity_hazard_fired.clear()
        _LOGGER.info("Safety Coordinator torn down")
