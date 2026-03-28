"""Presence Coordinator — house state inference and zone presence tracking.

Subscribes to Census updates, room occupancy sensors, BLE person tracking,
and zone camera detection. Infers house state via StateInferenceEngine.
Publishes SIGNAL_HOUSE_STATE_CHANGED.

v3.6.0-c1: Initial implementation with 3-tier zone presence signals.

Signal tiers for zone presence (any one sufficient for 'occupied'):
  1. Room occupancy sensors (mmWave/PIR) — via entity registry area_id
  2. Zone camera person/motion detection — via CameraIntegrationManager
  3. Bermuda BLE person location — via person_coordinator

Camera integration hardened from camera_census.py lessons:
  - Entity availability guards (unavailable/unknown states)
  - Entity registry for camera discovery (not substring matching)
  - Graceful degradation when sensors go offline
  - Camera detection timeout (person seen → zone occupied for N seconds)
  - try/except around all state reads
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_AREA_ID,
    CONF_ZONE_ROOMS,
    DIAGNOSTICS_SCOPE_HOUSE,
    DOMAIN,
)
from .base import BaseCoordinator, CoordinatorAction, Intent
from .coordinator_diagnostics import (
    AnomalyDetector,
    DecisionLog,
)
from .house_state import HouseState, HouseStateMachine
from .signals import (
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_CENSUS_UPDATED,
    SIGNAL_PERSON_ARRIVING,
)

_LOGGER = logging.getLogger(__name__)

# Camera detection timeout: after person/motion goes off, zone stays occupied
# for this duration before reverting to away. Prevents flapping.
_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300  # 5 minutes

# States that mean an entity is not providing real data
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})


# ============================================================================
# Zone Presence
# ============================================================================


class ZonePresenceMode:
    """Zone presence mode constants."""

    AWAY = "away"
    OCCUPIED = "occupied"
    SLEEP = "sleep"
    UNKNOWN = "unknown"
    AUTO = "auto"  # Used in select entity to mean "clear override"

    ALL_MODES = [AWAY, OCCUPIED, SLEEP, UNKNOWN]
    OVERRIDE_OPTIONS = [AUTO, AWAY, OCCUPIED, SLEEP]


class ZonePresenceTracker:
    """Tracks presence for a single zone using room sensors, cameras, and BLE.

    Three signal tiers (any one is sufficient for 'occupied'):
    1. Room occupancy sensors (mmWave/PIR) — discovered via entity registry area_id
    2. Zone camera person/motion detection — discovered via CameraIntegrationManager
    3. Bermuda BLE person location — read from person_coordinator

    Camera signals hold the zone occupied for _CAMERA_OCCUPANCY_TIMEOUT_SECONDS
    after the last detection, preventing flapping when cameras briefly lose sight.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_name: str,
        room_names: List[str],
    ) -> None:
        self.hass = hass
        self.zone_name = zone_name
        self.room_names = room_names
        self._override: Optional[str] = None
        self._has_sensors: bool = False
        self._room_occupied: Dict[str, bool] = {}
        self._camera_occupied: Dict[str, bool] = {}  # entity_id -> detection active
        self._camera_last_seen: Dict[str, datetime] = {}  # entity_id -> last detection time
        self._ble_occupied: bool = False
        self._last_activity: Optional[datetime] = None
        self._unsub_listeners: list = []
        # Track which signal tiers are available
        self._has_room_sensors: bool = False
        self._has_camera_sensors: bool = False
        self._has_ble_sensors: bool = False
        # Track entity_id -> room_name for reverse lookup
        self._entity_to_room: Dict[str, str] = {}
        # Track camera entity_ids belonging to this zone
        self._camera_entity_ids: Set[str] = set()
        # v3.19.0: Face-confirmed arrival tracking
        self._last_face_recognized: str = ""
        self._last_face_time: Optional[datetime] = None
        self._face_arrivals_today: int = 0

    @property
    def mode(self) -> str:
        """Return current zone presence mode."""
        if self._override is not None:
            return self._override
        return self._derived_mode

    @property
    def _derived_mode(self) -> str:
        """Derive zone mode from all signal tiers.

        v3.6.0.2: BLE (Tier 3) no longer gated by _has_sensors.
        BLE person tracking is the most reliable signal and should
        always determine zone state when available.
        """
        # Tier 3 first: BLE person location (always available, most reliable)
        if self._ble_occupied:
            return ZonePresenceMode.OCCUPIED

        # Tiers 1 & 2 require sensor discovery
        if self._has_sensors:
            # Tier 1: Room occupancy sensors
            if any(self._room_occupied.values()):
                return ZonePresenceMode.OCCUPIED

            # Tier 2: Camera person/motion detection (with timeout)
            if self._any_camera_occupied():
                return ZonePresenceMode.OCCUPIED

            return ZonePresenceMode.AWAY

        # No sensors discovered and no BLE — still report away if BLE
        # has ever updated (meaning the zone is known to the system)
        if self._has_ble_sensors:
            return ZonePresenceMode.AWAY

        return ZonePresenceMode.UNKNOWN

    def _any_camera_occupied(self) -> bool:
        """Check if any camera signal indicates occupancy (with timeout)."""
        if not self._camera_last_seen:
            return False

        now = dt_util.utcnow()
        timeout = timedelta(seconds=_CAMERA_OCCUPANCY_TIMEOUT_SECONDS)

        for entity_id, last_seen in self._camera_last_seen.items():
            # Currently detecting OR within timeout window
            if self._camera_occupied.get(entity_id, False):
                return True
            if (now - last_seen) < timeout:
                return True

        return False

    @property
    def is_overridden(self) -> bool:
        """Return True if zone mode is manually overridden."""
        return self._override is not None

    @property
    def has_sensors(self) -> bool:
        """Return True if zone has at least one sensor of any tier."""
        return self._has_sensors

    def set_override(self, mode: str) -> None:
        """Set a manual override for this zone."""
        if mode == ZonePresenceMode.AUTO:
            self.clear_override()
        else:
            self._override = mode

    def clear_override(self) -> None:
        """Clear manual override."""
        self._override = None

    def update_room_occupancy(self, room_name: str, occupied: bool) -> None:
        """Update occupancy state for a room in this zone."""
        if room_name in self.room_names:
            self._room_occupied[room_name] = occupied
            self._has_sensors = True
            self._has_room_sensors = True
            if occupied:
                self._last_activity = dt_util.utcnow()
                # Auto-resume: if override is AWAY but we detect presence, clear it
                if self._override == ZonePresenceMode.AWAY:
                    _LOGGER.info(
                        "Zone %s: auto-resuming from AWAY override — presence detected in %s",
                        self.zone_name, room_name,
                    )
                    self.clear_override()

    def update_camera_detection(self, entity_id: str, detected: bool) -> None:
        """Update camera person/motion detection for this zone.

        When detected=True, records timestamp for timeout-based occupancy.
        When detected=False, the timeout keeps the zone occupied for
        _CAMERA_OCCUPANCY_TIMEOUT_SECONDS before reverting to away.
        """
        self._camera_occupied[entity_id] = detected
        self._has_sensors = True
        self._has_camera_sensors = True
        if detected:
            self._camera_last_seen[entity_id] = dt_util.utcnow()
            self._last_activity = dt_util.utcnow()
            # Auto-resume from AWAY override on camera detection
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — camera detection on %s",
                    self.zone_name, entity_id,
                )
                self.clear_override()

    def update_ble_presence(self, has_persons: bool) -> None:
        """Update BLE-based person presence in this zone."""
        self._ble_occupied = has_persons
        if has_persons:
            self._has_sensors = True
            self._has_ble_sensors = True
            self._last_activity = dt_util.utcnow()
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — BLE presence detected",
                    self.zone_name,
                )
                self.clear_override()

    def set_sleep(self, sleeping: bool) -> None:
        """Set sleep mode (driven by house state, not zone sensors)."""
        if sleeping and self._override is None:
            # Only set sleep if not manually overridden
            self._override = ZonePresenceMode.SLEEP
        elif not sleeping and self._override == ZonePresenceMode.SLEEP:
            # Clear sleep override when house exits sleep
            self._override = None

    def mark_has_sensors(self) -> None:
        """Mark that this zone has at least one sensor."""
        self._has_sensors = True

    def register_entity(self, entity_id: str, room_name: str) -> None:
        """Register an entity_id → room_name mapping for this zone."""
        self._entity_to_room[entity_id] = room_name
        self._has_sensors = True
        self._has_room_sensors = True

    def register_camera(self, entity_id: str) -> None:
        """Register a camera entity_id for this zone."""
        self._camera_entity_ids.add(entity_id)
        self._has_sensors = True
        self._has_camera_sensors = True

    def to_dict(self) -> dict:
        """Serialize for diagnostics."""
        return {
            "zone_name": self.zone_name,
            "mode": self.mode,
            "derived_mode": self._derived_mode,
            "is_overridden": self.is_overridden,
            "override": self._override,
            "has_sensors": self._has_sensors,
            "signal_tiers": {
                "room_sensors": self._has_room_sensors,
                "camera_sensors": self._has_camera_sensors,
                "ble_sensors": self._has_ble_sensors,
            },
            "rooms": dict(self._room_occupied),
            "cameras": {
                eid: {
                    "detecting": self._camera_occupied.get(eid, False),
                    "last_seen": (
                        self._camera_last_seen[eid].isoformat()
                        if eid in self._camera_last_seen
                        else None
                    ),
                }
                for eid in self._camera_entity_ids
            },
            "ble_occupied": self._ble_occupied,
            "last_activity": (
                self._last_activity.isoformat() if self._last_activity else None
            ),
            # v3.19.0: Face-confirmed arrival state
            "last_face_recognized": self._last_face_recognized,
            "last_face_time": self._last_face_time.isoformat() if self._last_face_time else None,
            "face_arrivals_today": self._face_arrivals_today,
        }


# ============================================================================
# State Inference Engine
# ============================================================================


class StateInferenceEngine:
    """Infer house state from Census, time, and occupancy signals.

    Rules (evaluated in priority order):
    1. Census shows 0 people + all zones away → AWAY
    2. Census shows people + sleep hours → SLEEP
    3. Unidentified persons detected while home → GUEST
    4. Census shows people + time-based variant → HOME_DAY/EVENING/NIGHT
    5. Census shows new arrivals from AWAY → ARRIVING
    """

    def __init__(
        self,
        sleep_start_hour: int = 23,
        sleep_end_hour: int = 6,
        evening_start_hour: int = 18,
        night_start_hour: int = 21,
    ) -> None:
        self.sleep_start_hour = sleep_start_hour
        self.sleep_end_hour = sleep_end_hour
        self.evening_start_hour = evening_start_hour
        self.night_start_hour = night_start_hour
        self._confidence: float = 0.0

    @property
    def confidence(self) -> float:
        """Return confidence of last inference."""
        return self._confidence

    def infer(
        self,
        census_count: int,
        current_state: HouseState,
        any_zone_occupied: bool,
        now: Optional[datetime] = None,
        unidentified_count: int = 0,
    ) -> Optional[HouseState]:
        """Infer the appropriate house state.

        Returns the inferred state, or None if no change is warranted.
        """
        if now is None:
            now = dt_util.now()

        hour = now.hour

        # Nobody home
        if census_count == 0 and not any_zone_occupied:
            if current_state == HouseState.AWAY:
                return None  # Already away
            self._confidence = 0.9
            return HouseState.AWAY

        # People are home — determine variant
        has_people = census_count > 0 or any_zone_occupied

        if not has_people:
            return None

        # Arriving transition from AWAY
        if current_state == HouseState.AWAY:
            self._confidence = 0.85
            return HouseState.ARRIVING

        # Arriving → time-based home (must resolve before sleep/guest checks;
        # ARRIVING→SLEEP is not a valid state machine transition, so we first
        # move to HOME_*, then the next inference cycle handles HOME_*→SLEEP).
        if current_state == HouseState.ARRIVING:
            self._confidence = 0.85
            return self._time_based_home(hour)

        # Sleep hours (don't enter guest mode during sleep)
        if self._is_sleep_hour(hour):
            if current_state not in (HouseState.SLEEP, HouseState.WAKING):
                self._confidence = 0.7
                return HouseState.SLEEP
            return None

        # Waking transition
        if current_state == HouseState.SLEEP:
            self._confidence = 0.8
            return HouseState.WAKING

        # Waking → HOME_DAY
        if current_state == HouseState.WAKING:
            self._confidence = 0.85
            return HouseState.HOME_DAY

        # v3.15.0: Guest detection — unidentified persons while home
        # NOTE: ARRIVING excluded — must transition to HOME_* first (GUEST is
        # not a valid transition from ARRIVING). Guest detection fires next cycle.
        if unidentified_count > 0 and current_state in (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        ):
            if current_state != HouseState.GUEST:
                self._confidence = 0.8
                return HouseState.GUEST
        # Guest mode exit — unidentified gone, return to time-based home
        if current_state == HouseState.GUEST and unidentified_count == 0:
            self._confidence = 0.75
            return self._time_based_home(hour)

        # Time-based transitions while home
        time_home = self._time_based_home(hour)
        if current_state in (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        ):
            if time_home != current_state:
                self._confidence = 0.75
                return time_home
            return None

        return None

    def _time_based_home(self, hour: int) -> HouseState:
        """Determine HOME variant based on time of day.

        Timeline (with defaults): 0-5 night, 6-17 day, 18-20 evening, 21+ night.
        Hours before sleep_end (0-5 AM) are HOME_NIGHT so the valid
        transition HOME_NIGHT → SLEEP can fire on the next cycle.
        """
        if hour >= self.night_start_hour:
            return HouseState.HOME_NIGHT
        if hour >= self.evening_start_hour:
            return HouseState.HOME_EVENING
        if hour < self.sleep_end_hour:
            return HouseState.HOME_NIGHT
        return HouseState.HOME_DAY

    def _is_sleep_hour(self, hour: int) -> bool:
        """Check if current hour is within sleep hours."""
        if self.sleep_start_hour > self.sleep_end_hour:
            # Crosses midnight (e.g., 23-6)
            return hour >= self.sleep_start_hour or hour < self.sleep_end_hour
        return self.sleep_start_hour <= hour < self.sleep_end_hour


# ============================================================================
# Presence Coordinator
# ============================================================================


class PresenceCoordinator(BaseCoordinator):
    """Presence domain coordinator.

    Infers house state from Census + time + zone occupancy.
    Manages zone presence tracking with 3-tier signal support.
    Publishes SIGNAL_HOUSE_STATE_CHANGED.
    """

    PRESENCE_METRICS = [
        "census_count",
        "zone_occupied_count",
        "transition_count_daily",
    ]

    def __init__(
        self,
        hass: HomeAssistant,
        sleep_start_hour: int = 23,
        sleep_end_hour: int = 6,
    ) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="presence",
            name="Presence Coordinator",
            priority=60,
        )
        self._inference_engine = StateInferenceEngine(
            sleep_start_hour=sleep_start_hour,
            sleep_end_hour=sleep_end_hour,
        )
        self._zone_trackers: Dict[str, ZonePresenceTracker] = {}
        self._census_count: int = 0
        self._unidentified_count: int = 0
        self._transitions_today: int = 0
        self._transition_reset_date: str = ""
        # Room area_id lookup: room_name -> area_id (from config entries)
        self._room_area_ids: Dict[str, str] = {}
        # Deferred retry for hysteresis-blocked transitions
        self._retry_unsub: Optional[Any] = None
        # Outcome measurement
        self._outcome_true_positives: int = 0
        self._outcome_false_positives: int = 0
        self._last_transition_state: Optional[HouseState] = None
        self._last_transition_time: Optional[datetime] = None
        # v3.19.0: Face-confirmed arrival state
        self._face_arrival_cooldown: Dict[str, datetime] = {}
        self._face_recognition_enabled: bool = False

    @property
    def inference_engine(self) -> StateInferenceEngine:
        """Return the state inference engine."""
        return self._inference_engine

    @property
    def zone_trackers(self) -> Dict[str, ZonePresenceTracker]:
        """Return zone presence trackers."""
        return self._zone_trackers

    @property
    def census_count(self) -> int:
        """Return current census count."""
        return self._census_count

    @property
    def house_state(self) -> str:
        """Return current house state from the manager's state machine."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        state = manager.house_state
        return state.value if hasattr(state, 'value') else str(state)

    @property
    def confidence(self) -> float:
        """Return confidence of current state inference."""
        return self._inference_engine.confidence

    async def async_setup(self) -> None:
        """Set up the Presence Coordinator.

        Discovers zones and their rooms, sets up zone trackers,
        subscribes to Census and occupancy signals, discovers zone cameras.
        """
        _LOGGER.info("Setting up Presence Coordinator")

        # v3.6.0.3: Instantiate anomaly detector FIRST so it's always available
        # even if discovery fails. Minimum 24 samples (~1 day of hourly
        # observations) before activation.
        from .coordinator_diagnostics import AnomalyDetector
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id="presence",
            metric_names=self.PRESENCE_METRICS,
            minimum_samples=24,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Could not load presence anomaly baselines (non-fatal)", exc_info=True)

        # v3.19.0: Read face recognition toggle from integration config
        try:
            from ..const import CONF_FACE_RECOGNITION_ENABLED, ENTRY_TYPE_INTEGRATION, CONF_ENTRY_TYPE
            for config_entry in self.hass.config_entries.async_entries(DOMAIN):
                if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                    merged = {**config_entry.data, **config_entry.options}
                    self._face_recognition_enabled = merged.get(CONF_FACE_RECOGNITION_ENABLED, False)
                    break
        except Exception:
            self._face_recognition_enabled = False

        # v3.6.0.3: Wrap discovery/subscription in try/except so partial
        # failures don't prevent the coordinator from functioning.
        try:
            # Build room → area_id mapping from room config entries
            self._build_room_area_map()

            # Discover zones and create trackers
            self._discover_zones()

            # Discover and subscribe to room occupancy sensors (Tier 1)
            self._discover_room_sensors()

            # Discover and subscribe to zone cameras (Tier 2)
            self._discover_zone_cameras()

            # Subscribe to geofence (person entity state changes)
            self._subscribe_geofence()

            # Subscribe to census updates
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            self._unsub_listeners.append(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_CENSUS_UPDATED,
                    self._handle_census_update,
                )
            )

            # Periodic inference (every 60 seconds for time-based transitions + camera timeouts)
            self._unsub_listeners.append(
                async_track_time_interval(
                    self.hass,
                    self._periodic_inference,
                    timedelta(seconds=60),
                )
            )
        except Exception:
            _LOGGER.exception("Error during presence discovery (non-fatal)")

        # v3.6.0-c2.3: Seed census count from existing data before first
        # inference. Without this, _census_count=0 → infers "away" even
        # when people are home. Read from census manager if available,
        # else fall back to the identified_persons sensor state.
        try:
            census_mgr = self.hass.data.get(DOMAIN, {}).get(
                "camera_integration_manager"
            )
            if census_mgr and hasattr(census_mgr, "last_result"):
                last = census_mgr.last_result
                if last is not None:
                    self._census_count = last.house.total_persons
                    _LOGGER.info(
                        "Seeded census count from manager: %d",
                        self._census_count,
                    )
            if self._census_count == 0:
                # Fallback: read from sensor state
                state = self.hass.states.get(
                    f"sensor.{DOMAIN}_identified_persons_in_house"
                )
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        self._census_count = int(state.state)
                        _LOGGER.info(
                            "Seeded census count from sensor: %d",
                            self._census_count,
                        )
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            _LOGGER.warning("Failed to seed census count: %s", e)

        # Run initial inference with seeded census count
        await self._run_inference("startup")

        _LOGGER.info(
            "Presence Coordinator ready: %d zones tracked",
            len(self._zone_trackers),
        )

    def _build_room_area_map(self) -> None:
        """Build room_name → area_id mapping from room config entries.

        v3.6.0.11: Falls back to matching room names against HA area registry
        names when CONF_AREA_ID is not configured on the room entry.
        """
        from ..const import CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM

        # Build name→area_id lookup from HA area registry for fallback
        area_name_to_id: Dict[str, str] = {}
        try:
            from homeassistant.helpers import area_registry as ar
            area_reg = ar.async_get(self.hass)
            for area in area_reg.async_list_areas():
                area_name_to_id[area.name.lower()] = area.area_id
        except Exception:
            _LOGGER.debug("Cannot access area registry for room area fallback")

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                room_name = entry.data.get(CONF_ROOM_NAME, "")
                area_id = (
                    entry.options.get(CONF_AREA_ID)
                    or entry.data.get(CONF_AREA_ID)
                )
                # Fallback: match room name to HA area name
                if not area_id and room_name:
                    area_id = area_name_to_id.get(room_name.lower())
                    if area_id:
                        _LOGGER.debug(
                            "Room '%s' area_id resolved via area registry: %s",
                            room_name, area_id,
                        )
                if room_name and area_id:
                    self._room_area_ids[room_name] = area_id

        _LOGGER.info(
            "Room area map: %d rooms mapped to areas: %s",
            len(self._room_area_ids),
            {k: v for k, v in self._room_area_ids.items()},
        )

    def _discover_zones(self) -> None:
        """Discover zones and their rooms from config entries.

        v3.6.0.2: Full diagnostic logging + entry ID resolution.
        """
        from ..const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE, ENTRY_TYPE_ZONE_MANAGER,
            CONF_ZONE_NAME, CONF_ROOM_NAME,
        )

        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        entry_types = [e.data.get(CONF_ENTRY_TYPE, "unknown") for e in all_entries]
        _LOGGER.info(
            "Zone discovery: %d config entries, types: %s",
            len(all_entries), entry_types,
        )

        # Legacy: individual ENTRY_TYPE_ZONE entries
        for entry in all_entries:
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                zone_name = entry.data.get(CONF_ZONE_NAME, "")
                room_names = list(
                    entry.options.get(CONF_ZONE_ROOMS, [])
                    or entry.data.get(CONF_ZONE_ROOMS, [])
                )
                if zone_name and room_names:
                    self._zone_trackers[zone_name] = ZonePresenceTracker(
                        hass=self.hass,
                        zone_name=zone_name,
                        room_names=room_names,
                    )
                    _LOGGER.info(
                        "Zone tracker created (legacy): %s with rooms %s",
                        zone_name, room_names,
                    )

        # Zone Manager entry: zones in data["zones"] or options["zones"]
        zm_found = False
        for entry in all_entries:
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                zm_found = True
                # Check both data and options for zones
                data_zones = entry.data.get("zones", {})
                opts_zones = entry.options.get("zones", {})
                _LOGGER.info(
                    "Zone Manager found: entry_id=%s, data has %d zones, options has %d zones, "
                    "data keys: %s, options keys: %s",
                    entry.entry_id,
                    len(data_zones), len(opts_zones),
                    list(data_zones.keys()) if data_zones else "[]",
                    list(opts_zones.keys()) if opts_zones else "[]",
                )

                # Options takes priority over data (config flow writes to options)
                zones_data = opts_zones if opts_zones else data_zones

                for zone_name, zone_cfg in zones_data.items():
                    if zone_name in self._zone_trackers:
                        continue
                    raw_rooms = list(zone_cfg.get(CONF_ZONE_ROOMS, []))
                    _LOGGER.info(
                        "Zone '%s' raw room refs: %s", zone_name, raw_rooms,
                    )
                    # Resolve entry IDs to room names
                    room_names = []
                    for room_ref in raw_rooms:
                        room_entry = self.hass.config_entries.async_get_entry(room_ref)
                        if room_entry:
                            name = room_entry.data.get(CONF_ROOM_NAME, "")
                            if name:
                                room_names.append(name)
                                _LOGGER.debug(
                                    "  Resolved %s -> '%s'", room_ref[:12], name,
                                )
                                continue
                        # Fallback: treat as a room name directly
                        room_names.append(room_ref)
                        _LOGGER.debug(
                            "  Fallback (no entry): %s used as-is", room_ref[:20],
                        )
                    if zone_name and room_names:
                        self._zone_trackers[zone_name] = ZonePresenceTracker(
                            hass=self.hass,
                            zone_name=zone_name,
                            room_names=room_names,
                        )
                        _LOGGER.info(
                            "Zone tracker created: '%s' with %d rooms: %s",
                            zone_name, len(room_names), room_names,
                        )
                    else:
                        _LOGGER.warning(
                            "Zone '%s' skipped: zone_name=%r, room_names=%s",
                            zone_name, zone_name, room_names,
                        )
                break

        if not zm_found:
            _LOGGER.warning("No Zone Manager entry found among %d entries", len(all_entries))

        _LOGGER.info(
            "Zone discovery complete: %d zone trackers created: %s",
            len(self._zone_trackers), list(self._zone_trackers.keys()),
        )

    # ------------------------------------------------------------------
    # Tier 1: Room Occupancy Sensors (via entity registry area_id)
    # ------------------------------------------------------------------

    def _discover_room_sensors(self) -> None:
        """Discover room occupancy sensors using entity/device registry area_id.

        v3.6.0.11: Also checks device area_id when entity area_id is null.
        Many Zigbee/MQTT sensors have area_id on the device, not the entity.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            from homeassistant.helpers import device_registry as dr
            ent_reg = er.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
        except Exception:
            _LOGGER.warning("Cannot access entity/device registry — room sensor discovery skipped")
            return

        entity_ids: Set[str] = set()
        occupancy_keywords = ("occupancy", "motion", "presence", "mmwave")

        for _zone_name, tracker in self._zone_trackers.items():
            for room_name in tracker.room_names:
                area_id = self._room_area_ids.get(room_name)
                if not area_id:
                    _LOGGER.debug(
                        "Room '%s' has no area_id configured — trying name-based fallback",
                        room_name,
                    )
                    self._discover_room_sensors_by_name(
                        tracker, room_name, entity_ids,
                    )
                    continue

                # Find binary_sensor entities assigned to this area
                # Check both entity area_id and device area_id (fallback)
                for entity in ent_reg.entities.values():
                    if entity.domain != "binary_sensor":
                        continue
                    if not any(kw in entity.entity_id for kw in occupancy_keywords):
                        continue

                    # Resolve effective area: entity → device fallback
                    effective_area = entity.area_id
                    if not effective_area and entity.device_id:
                        dev_entry = dev_reg.async_get(entity.device_id)
                        if dev_entry:
                            effective_area = dev_entry.area_id

                    if effective_area == area_id:
                        entity_ids.add(entity.entity_id)
                        tracker.register_entity(entity.entity_id, room_name)
                        _LOGGER.debug(
                            "Zone %s: room %s (area %s) → occupancy sensor %s",
                            _zone_name, room_name, area_id, entity.entity_id,
                        )

        if entity_ids:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    list(entity_ids),
                    self._handle_occupancy_change,
                )
            )
            _LOGGER.info(
                "Subscribed to %d room occupancy entities across %d zones",
                len(entity_ids), len(self._zone_trackers),
            )

    def _discover_room_sensors_by_name(
        self,
        tracker: ZonePresenceTracker,
        room_name: str,
        entity_ids: Set[str],
    ) -> None:
        """Fallback: discover occupancy sensors by name matching.

        Only used when a room has no area_id configured. Less reliable
        than area_id-based discovery — a room named "den" could match
        "garden_motion", so we require BOTH the room name AND an occupancy
        keyword in the entity_id.
        """
        room_lower = room_name.lower().replace(" ", "_")
        occupancy_keywords = ("occupancy", "motion", "presence", "mmwave")

        # Avoid matching short room names that are substrings of unrelated entities
        if len(room_lower) < 3:
            _LOGGER.warning(
                "Room name '%s' is too short for name-based sensor matching — skipping",
                room_name,
            )
            return

        for state in self.hass.states.async_all():
            entity_id = state.entity_id
            if not entity_id.startswith("binary_sensor."):
                continue

            # Require BOTH room name and occupancy keyword
            entity_suffix = entity_id[len("binary_sensor."):]
            if (
                room_lower in entity_suffix
                and any(kw in entity_suffix for kw in occupancy_keywords)
            ):
                entity_ids.add(entity_id)
                tracker.register_entity(entity_id, room_name)
                _LOGGER.debug(
                    "Zone %s: room %s → occupancy sensor %s (name-based fallback)",
                    tracker.zone_name, room_name, entity_id,
                )

    # ------------------------------------------------------------------
    # Tier 2: Zone Camera Sensors (via CameraIntegrationManager)
    # ------------------------------------------------------------------

    def _discover_zone_cameras(self) -> None:
        """Discover cameras in each zone using CameraIntegrationManager.

        Cameras are mapped to zones via their area_id in the entity registry.
        If a camera's area_id matches a room's area_id, and that room is in
        a zone, the camera's person detection entity is subscribed for that zone.

        This mirrors how camera_census.py uses area_id for camera→room mapping,
        but applied at the zone level.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            _LOGGER.debug("No coordinator manager — camera discovery skipped")
            return

        # Get CameraIntegrationManager from the coordinator data
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if camera_manager is None:
            _LOGGER.debug("No camera manager initialized — zone camera discovery skipped")
            return

        if not camera_manager.has_cameras():
            _LOGGER.debug("No cameras discovered — zone camera signals unavailable")
            return

        camera_entity_ids: Set[str] = set()

        # Build area_id → zone mapping from room → zone assignments
        area_to_zone: Dict[str, str] = {}
        for zone_name, tracker in self._zone_trackers.items():
            for room_name in tracker.room_names:
                area_id = self._room_area_ids.get(room_name)
                if area_id:
                    area_to_zone[area_id] = zone_name

        # Find cameras in each zone's areas
        for area_id, zone_name in area_to_zone.items():
            cameras_in_area = camera_manager.get_cameras_for_area(area_id)
            tracker = self._zone_trackers[zone_name]

            for camera_info in cameras_in_area:
                person_sensor = camera_info.person_binary_sensor
                if person_sensor and person_sensor not in camera_entity_ids:
                    camera_entity_ids.add(person_sensor)
                    tracker.register_camera(person_sensor)
                    _LOGGER.debug(
                        "Zone %s: camera sensor %s (area %s, platform %s)",
                        zone_name, person_sensor, area_id, camera_info.platform,
                    )

        if camera_entity_ids:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    list(camera_entity_ids),
                    self._handle_camera_change,
                )
            )
            _LOGGER.info(
                "Subscribed to %d zone camera entities across %d zones",
                len(camera_entity_ids), len(self._zone_trackers),
            )

    # ------------------------------------------------------------------
    # Geofence: person entity state changes (home/not_home)
    # ------------------------------------------------------------------

    def _subscribe_geofence(self) -> None:
        """Subscribe to person.* entity state changes for geofence signals.

        HA person entities track home/not_home/zone state. When a person
        transitions to 'home' from 'not_home' (or vice versa), this provides
        an early AWAY→ARRIVING signal before camera census updates.
        """
        person_entity_ids = [
            state.entity_id
            for state in self.hass.states.async_all()
            if state.entity_id.startswith("person.")
        ]

        if not person_entity_ids:
            _LOGGER.debug("No person entities found — geofence signal unavailable")
            return

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass,
                person_entity_ids,
                self._handle_geofence_change,
            )
        )
        _LOGGER.info(
            "Subscribed to %d person entities for geofence signals",
            len(person_entity_ids),
        )

    @callback
    def _handle_geofence_change(self, event: Any) -> None:
        """Handle person entity state change (geofence transition)."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        new_zone = new_state.state
        old_zone = old_state.state if old_state else None

        # Guard: skip unavailable/unknown
        if new_zone in _UNAVAILABLE_STATES:
            return

        # Detect home arrival or departure
        if new_zone == "home" and old_zone != "home":
            self.handle_geofence_event(entity_id, "home")
            # v3.17.0 D3: Signal person arriving for HVAC zone pre-conditioning
            from homeassistant.helpers.dispatcher import (
                async_dispatcher_send as _dispatcher_send,
            )
            _dispatcher_send(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                {"person_entity": entity_id, "source": "geofence"},
            )
        elif new_zone == "not_home" and old_zone == "home":
            self.handle_geofence_event(entity_id, "not_home")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    @callback
    def _handle_census_update(self, census_data: dict) -> None:
        """Handle Census update signal."""
        old_count = self._census_count
        old_unidentified = self._unidentified_count
        try:
            self._census_count = int(census_data.get("interior_count", 0))
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid census interior_count: %s — keeping previous value",
                census_data.get("interior_count"),
            )
            return

        # v3.15.0: Track unidentified count for guest mode
        try:
            self._unidentified_count = int(census_data.get("unidentified_count", 0))
        except (ValueError, TypeError):
            self._unidentified_count = 0

        if old_count != self._census_count or old_unidentified != self._unidentified_count:
            self.hass.async_create_task(self._run_inference("census_update"))

    @callback
    def _handle_occupancy_change(self, event: Any) -> None:
        """Handle room occupancy sensor state change.

        Guards against unavailable/unknown states — treats them as 'not occupied'
        to avoid false positives from offline sensors (lesson from camera_census).
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Guard: treat unavailable/unknown as not occupied
        if new_state.state in _UNAVAILABLE_STATES:
            _LOGGER.debug(
                "Occupancy sensor %s is %s — treating as not occupied",
                entity_id, new_state.state,
            )
            occupied = False
        else:
            occupied = new_state.state == "on"

        # Find which zone and room this entity belongs to (via registered mapping)
        matched = False
        for _zone_name, tracker in self._zone_trackers.items():
            room_name = tracker._entity_to_room.get(entity_id)
            if room_name:
                tracker.update_room_occupancy(room_name, occupied)
                matched = True
                break

        if not matched:
            # Fallback: name-based matching for entities discovered by name
            for _zone_name, tracker in self._zone_trackers.items():
                for room_name in tracker.room_names:
                    room_lower = room_name.lower().replace(" ", "_")
                    if room_lower in entity_id:
                        tracker.update_room_occupancy(room_name, occupied)
                        matched = True
                        break
                if matched:
                    break

        self.hass.async_create_task(self._run_inference("occupancy_change"))

    @callback
    def _handle_camera_change(self, event: Any) -> None:
        """Handle camera person/motion detection state change.

        Guards against unavailable/unknown states. Camera detection uses
        timeout-based occupancy — when person is detected the zone stays
        occupied for _CAMERA_OCCUPANCY_TIMEOUT_SECONDS after detection ends.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Guard: unavailable/unknown means not detecting
        if new_state.state in _UNAVAILABLE_STATES:
            _LOGGER.debug(
                "Camera sensor %s is %s — treating as no detection",
                entity_id, new_state.state,
            )
            detected = False
        else:
            detected = new_state.state == "on"

        # Route to the correct zone tracker (EXISTING — unchanged)
        matched_zone_name = None
        for _zone_name, tracker in self._zone_trackers.items():
            if entity_id in tracker._camera_entity_ids:
                tracker.update_camera_detection(entity_id, detected)
                matched_zone_name = _zone_name
                break

        # v3.19.0: Face-confirmed arrival (ADDITIVE — all failures return gracefully)
        if detected and matched_zone_name and self._face_recognition_enabled:
            face_name = self._get_face_for_camera(entity_id)
            if face_name:
                self._handle_face_arrival(entity_id, face_name, matched_zone_name)

        self.hass.async_create_task(self._run_inference("camera_detection"))

    # ------------------------------------------------------------------
    # v3.19.0: Face-confirmed arrival helpers (additive — never modify
    # existing camera detection behavior, all failures return gracefully)
    # ------------------------------------------------------------------

    def _get_face_for_camera(self, camera_entity: str) -> Optional[str]:
        """Get recognized face from Frigate face sensor for this camera.

        v3.19.0: Uses confirmed Frigate naming pattern:
        binary_sensor.{name}_person_occupancy → sensor.{name}_last_recognized_face

        Returns face name if fresh (<30s), None on any failure.
        All failures are graceful — face rec is an accelerator, not a requirement.
        """
        try:
            # Derive face sensor from camera entity using Frigate naming convention
            bs_id = camera_entity
            base_name = None
            for suffix in ("_person_occupancy", "_person_detected", "_occupancy"):
                if bs_id.startswith("binary_sensor.") and bs_id.endswith(suffix):
                    base_name = bs_id[len("binary_sensor."):-len(suffix)]
                    break

            if not base_name:
                return None  # Not a recognized camera pattern

            face_sensor_id = f"sensor.{base_name}_last_recognized_face"
            state = self.hass.states.get(face_sensor_id)
            if not state:
                return None  # Face sensor doesn't exist

            # Check for valid face name
            face_value = state.state.strip() if state.state else ""
            if not face_value or face_value.lower() in ("unknown", "unavailable", "none", "no_match", ""):
                return None  # No face recognized

            # Freshness check: face rec must be recent (<30s)
            if state.last_changed:
                age = (dt_util.utcnow() - state.last_changed).total_seconds()
                if age > 30:  # FACE_FRESHNESS_SECONDS
                    return None  # Stale face data

            return face_value
        except Exception:  # noqa: BLE001
            return None  # Face rec is an accelerator — never fail

    @callback
    def _handle_face_arrival(self, camera_entity: str, face_name: str, zone_name: str) -> None:
        """Fire pre-arrival signal for face-recognized person in a zone.

        v3.19.0: Debounced (60s per person+zone). All failures graceful.
        """
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            # Map face name to person entity
            person_entity = self._find_person_entity_from_face(face_name)
            if not person_entity:
                _LOGGER.debug("Face '%s' has no matching person entity — skipping", face_name)
                return

            # Debounce: 60s cooldown per person+zone
            key = f"{person_entity}:{zone_name}"
            now = dt_util.utcnow()
            last = self._face_arrival_cooldown.get(key)
            if last and (now - last).total_seconds() < 60:
                return
            self._face_arrival_cooldown[key] = now

            # Update zone tracker face state
            tracker = self._zone_trackers.get(zone_name)
            if tracker:
                tracker._last_face_recognized = face_name
                tracker._last_face_time = now
                tracker._face_arrivals_today += 1

            # Update HVAC zone counter if available
            try:
                manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                if manager:
                    hvac = manager.coordinators.get("hvac")
                    if hvac and hvac.zone_manager:
                        for _zid, zstate in hvac.zone_manager.zones.items():
                            if zstate.zone_name == zone_name:
                                zstate.camera_face_arrivals_today += 1
                                break
            except Exception:  # noqa: BLE001
                pass  # Best effort — don't fail face arrival on HVAC counter update

            # Fire the signal
            async_dispatcher_send(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                {"person_entity": person_entity, "source": "camera_face"},
            )
            _LOGGER.info(
                "Camera face arrival: %s recognized in zone %s via %s",
                face_name, zone_name, camera_entity,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Face arrival handling failed (non-fatal)", exc_info=True)

    def _find_person_entity_from_face(self, face_name: str) -> Optional[str]:
        """Map Frigate face name to HA person entity.

        v3.19.0: Frigate face names are configured names (e.g., "Oji", "Jaya").
        Try matching to person.{lowercase_name}.
        """
        try:
            candidate = f"person.{face_name.lower().replace(' ', '_')}"
            if self.hass.states.get(candidate):
                return candidate
            # Try without modification
            candidate2 = f"person.{face_name}"
            if self.hass.states.get(candidate2):
                return candidate2
            return None
        except Exception:  # noqa: BLE001
            return None  # Face rec is an accelerator — never fail

    async def _periodic_inference(self, _now: Any = None) -> None:
        """Run periodic inference for time-based transitions and camera timeouts.

        Also updates BLE-based zone presence (Tier 3) from person_coordinator.
        """
        # Update BLE presence for each zone (Tier 3)
        self._update_ble_zone_presence()

        await self._run_inference("periodic")

    def _update_ble_zone_presence(self) -> None:
        """Update BLE-based zone presence from person_coordinator.

        Checks person_coordinator for persons located in rooms that belong
        to each zone. If any person is in a room within a zone, that zone
        is BLE-occupied.
        """
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator or not hasattr(person_coordinator, "data") or not person_coordinator.data:
            return

        for _zone_name, tracker in self._zone_trackers.items():
            zone_has_person = False
            for _person_id, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location and location not in ("away", "unknown", ""):
                    # Check if this person's room is in this zone
                    if location in tracker.room_names:
                        zone_has_person = True
                        break

            tracker.update_ble_presence(zone_has_person)

    def _schedule_deferred_retry(self, delay_seconds: float) -> None:
        """Schedule a one-shot deferred inference retry after hysteresis expires.

        v3.6.0.11: Prevents lost transitions when hysteresis blocks.
        """
        from homeassistant.helpers.event import async_call_later

        # Cancel any existing retry
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

        @callback
        def _retry_callback(_now):
            self._retry_unsub = None
            self.hass.async_create_task(self._run_inference("deferred_retry"))

        self._retry_unsub = async_call_later(
            self.hass, delay_seconds, _retry_callback,
        )
        _LOGGER.debug(
            "Deferred retry scheduled in %.0fs", delay_seconds,
        )

    async def _run_inference(self, trigger: str) -> None:
        """Run state inference and apply transitions.

        v3.6.0.11: Schedules deferred retry when hysteresis blocks.
        """
        if not self._enabled:
            return

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        # D4: Capture zone modes before inference for change detection
        zone_modes_before = {
            name: tracker.mode for name, tracker in self._zone_trackers.items()
        }

        any_zone_occupied = any(
            t.mode == ZonePresenceMode.OCCUPIED
            for t in self._zone_trackers.values()
        )

        current_state = manager.house_state_machine.state
        new_state = self._inference_engine.infer(
            census_count=self._census_count,
            current_state=current_state,
            any_zone_occupied=any_zone_occupied,
            unidentified_count=self._unidentified_count,
        )

        if new_state is not None:
            accepted = manager.house_state_machine.transition(
                new_state, trigger=trigger
            )
            if accepted:
                # Clear any pending retry — transition succeeded
                if self._retry_unsub is not None:
                    self._retry_unsub()
                    self._retry_unsub = None
                self._count_transition()

                # Propagate sleep state to zones
                if new_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(True)
                elif current_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(False)

                # Log decision (house-scoped)
                await self._log_state_transition(
                    current_state, new_state, trigger
                )

                # D3: Log house state change to database
                db = self.hass.data.get(DOMAIN, {}).get("database")
                if db is not None:
                    self.hass.async_create_task(
                        db.log_house_state_change(
                            state=new_state.value,
                            confidence=self._inference_engine.confidence,
                            trigger=trigger,
                            previous_state=current_state.value,
                        )
                    )

                # Publish signal
                from homeassistant.helpers.dispatcher import (
                    async_dispatcher_send,
                )
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_HOUSE_STATE_CHANGED,
                    {
                        "old_state": current_state.value,
                        "new_state": new_state.value,
                        "trigger": trigger,
                        "confidence": self._inference_engine.confidence,
                    },
                )

                # House-level anomaly detection
                if self.anomaly_detector is not None:
                    anomaly = self.anomaly_detector.record_observation(
                        "census_count",
                        DIAGNOSTICS_SCOPE_HOUSE,
                        float(self._census_count),
                    )
                    if anomaly:
                        await self.anomaly_detector.store_anomaly(anomaly)

                # Outcome measurement: record for accuracy tracking
                self._record_outcome(current_state, new_state, trigger)

            else:
                # Transition blocked (likely hysteresis) — schedule retry
                remaining = manager.house_state_machine.remaining_hysteresis()
                if remaining > 0 and trigger != "deferred_retry":
                    self._schedule_deferred_retry(remaining + 1)

        # D4: Log zone mode changes to database
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is not None:
            for zone_name, tracker in self._zone_trackers.items():
                old_mode = zone_modes_before.get(zone_name)
                new_mode = tracker.mode
                if old_mode is not None and old_mode != new_mode:
                    occupied_rooms = [
                        rn for rn, occ in tracker._room_occupied.items() if occ
                    ]
                    self.hass.async_create_task(
                        db.log_zone_event(
                            zone=zone_name,
                            event_type=new_mode,
                            room_count=len(occupied_rooms),
                            rooms=occupied_rooms if occupied_rooms else None,
                        )
                    )

        # Zone-scoped anomaly detection (runs every inference, not just on transition)
        await self._check_zone_anomalies()

    async def _check_zone_anomalies(self) -> None:
        """Record zone-level anomaly observations.

        Checks each zone's occupied status and records it as an observation
        for zone-scoped anomaly detection. Detects unusual occupancy patterns
        like "zone occupied at unusual time."
        """
        if self.anomaly_detector is None:
            return

        hour = dt_util.now().hour
        for zone_name, tracker in self._zone_trackers.items():
            if not tracker.has_sensors:
                continue
            scope = f"zone:{zone_name}"
            # Record occupancy as 1.0/0.0 observation for time-of-day baseline
            occupied_value = 1.0 if tracker.mode == ZonePresenceMode.OCCUPIED else 0.0
            anomaly = self.anomaly_detector.record_observation(
                "zone_occupied_count",
                scope,
                occupied_value,
            )
            if anomaly:
                await self.anomaly_detector.store_anomaly(anomaly)
                _LOGGER.info(
                    "Zone %s anomaly detected: severity=%s, z_score=%.1f",
                    zone_name, anomaly.severity.value, anomaly.z_score,
                )

    async def _log_zone_mode_change(
        self,
        zone_name: str,
        old_mode: str,
        new_mode: str,
        trigger: str,
    ) -> None:
        """Log a zone mode change as a decision (zone-scoped)."""
        if self.decision_logger is None:
            return

        decision = DecisionLog(
            timestamp=dt_util.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="zone_mode_change",
            scope=f"zone:{zone_name}",
            situation_classified=new_mode,
            urgency=30,
            confidence=0.9,
            context={
                "zone_name": zone_name,
                "old_mode": old_mode,
                "new_mode": new_mode,
                "trigger": trigger,
            },
        )
        await self.decision_logger.log_decision(decision)

    def _count_transition(self) -> None:
        """Count daily transitions."""
        today = dt_util.now().date().isoformat()
        if today != self._transition_reset_date:
            self._transitions_today = 0
            self._transition_reset_date = today
            # v3.19.0: Reset face arrival counters at midnight
            for tracker in self._zone_trackers.values():
                tracker._face_arrivals_today = 0
            self._face_arrival_cooldown.clear()
        self._transitions_today += 1

    # ------------------------------------------------------------------
    # Outcome measurement
    # ------------------------------------------------------------------

    def _record_outcome(
        self,
        old_state: HouseState,
        new_state: HouseState,
        trigger: str,
    ) -> None:
        """Record a state transition outcome for accuracy tracking.

        Tracks detection accuracy by measuring how often transitions are
        later contradicted (e.g., went to AWAY but immediately came back).
        """
        now = dt_util.utcnow()

        # Track if previous transition was contradicted
        if hasattr(self, '_last_transition_time') and self._last_transition_state is not None:
            elapsed = (now - self._last_transition_time).total_seconds()
            if elapsed < 120:  # Contradiction within 2 minutes
                self._outcome_false_positives += 1
                _LOGGER.debug(
                    "Potential false positive: %s lasted only %.0fs before %s",
                    self._last_transition_state.value, elapsed, new_state.value,
                )
            else:
                self._outcome_true_positives += 1

        self._last_transition_state = new_state
        self._last_transition_time = now

    @property
    def detection_accuracy(self) -> float:
        """Return detection accuracy as ratio of true positives to total."""
        total = self._outcome_true_positives + self._outcome_false_positives
        if total == 0:
            return 1.0
        return self._outcome_true_positives / total

    @property
    def false_positive_rate(self) -> float:
        """Return false positive rate."""
        total = self._outcome_true_positives + self._outcome_false_positives
        if total == 0:
            return 0.0
        return self._outcome_false_positives / total

    # ------------------------------------------------------------------
    # Decision logging
    # ------------------------------------------------------------------

    async def _log_state_transition(
        self,
        old_state: HouseState,
        new_state: HouseState,
        trigger: str,
    ) -> None:
        """Log a state transition as a decision."""
        if self.decision_logger is None:
            return

        decision = DecisionLog(
            timestamp=dt_util.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="state_transition",
            scope=DIAGNOSTICS_SCOPE_HOUSE,
            situation_classified=new_state.value,
            urgency=50,
            confidence=self._inference_engine.confidence,
            context={
                "old_state": old_state.value,
                "new_state": new_state.value,
                "trigger": trigger,
                "census_count": self._census_count,
                "zones": {
                    name: tracker.mode
                    for name, tracker in self._zone_trackers.items()
                },
            },
        )
        await self.decision_logger.log_decision(decision)

    async def evaluate(
        self,
        intents: list,
        context: dict,
    ) -> List[CoordinatorAction]:
        """Evaluate intents — Presence doesn't generate actions directly.

        Presence is informational: it publishes state, other coordinators
        react to it. But we still process intents if any are routed to us.
        """
        return []

    async def async_teardown(self) -> None:
        """Tear down the Presence Coordinator."""
        # Cancel deferred retry timer
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

        self._cancel_listeners()

        # Save anomaly baselines
        if self.anomaly_detector is not None:
            await self.anomaly_detector.save_baselines()

        _LOGGER.info("Presence Coordinator torn down")

    # ------------------------------------------------------------------
    # Override controls (backing select entities + services)
    # ------------------------------------------------------------------

    def set_house_state_override(self, state_value: str) -> None:
        """Set house state override from select entity or service call.

        Called by select entity when user changes the dropdown,
        or by ura.set_house_state service.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        if state_value == "auto":
            manager.house_state_machine.clear_override()
            # Clear zone sleep overrides too
            for tracker in self._zone_trackers.values():
                if tracker._override == ZonePresenceMode.SLEEP:
                    tracker.clear_override()
        else:
            try:
                house_state = HouseState(state_value)
                manager.house_state_machine.set_override(house_state)

                # Propagate AWAY to all zones
                if house_state == HouseState.AWAY:
                    for tracker in self._zone_trackers.values():
                        tracker.set_override(ZonePresenceMode.AWAY)
                elif house_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(True)
            except ValueError:
                _LOGGER.warning("Invalid house state override: %s", state_value)

    def get_house_state_override(self) -> str:
        """Get current house state override value for select entity."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None or not manager.house_state_machine.is_overridden:
            return "auto"
        return manager.house_state_machine.state.value

    # ------------------------------------------------------------------
    # Geofence signal (v3.6.0-c1.1: wired to person.* state changes)
    # ------------------------------------------------------------------

    def handle_geofence_event(self, person_id: str, zone: str) -> None:
        """Handle geofence enter/leave event for a person.

        When a person's device tracker transitions to/from 'home',
        triggers inference for state re-evaluation.

        v3.6.0.11: Triggers from any state on arrival, not just AWAY.
        The inference engine determines the valid transition.
        """
        if zone == "home":
            # Person arriving — trigger inference from any state
            self.hass.async_create_task(self._run_inference("geofence_arrive"))
            _LOGGER.info("Geofence: %s arrived home", person_id)
        elif zone == "not_home":
            # Person left — trigger inference to check if house is now empty
            self.hass.async_create_task(self._run_inference("geofence_leave"))
            _LOGGER.debug("Geofence: %s left home", person_id)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return full presence diagnostics."""
        summary = super().get_diagnostics_summary()
        summary["census_count"] = self._census_count
        summary["unidentified_count"] = self._unidentified_count
        summary["house_state"] = self.house_state
        summary["confidence"] = self.confidence
        summary["transitions_today"] = self._transitions_today
        summary["detection_accuracy"] = round(self.detection_accuracy, 3)
        summary["false_positive_rate"] = round(self.false_positive_rate, 3)
        summary["outcome_stats"] = {
            "true_positives": self._outcome_true_positives,
            "false_positives": self._outcome_false_positives,
        }
        summary["zones"] = {
            name: tracker.to_dict()
            for name, tracker in self._zone_trackers.items()
        }
        return summary
