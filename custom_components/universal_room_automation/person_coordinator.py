"""Person tracking coordinator for Universal Room Automation."""
#
# Universal Room Automation v4.0.4
# Build: 2026-01-03
# File: person_coordinator.py
# v3.2.9: No changes (zone fixes in aggregation.py, fan fixes in automation.py)
# v3.2.8.3: Fixed previous_location_time to record when person LEFT (not when they entered)
# v3.2.8.1: Implemented staleness decay logic with tracking_status and recent_path
# v3.2.8.1: Fixed Previous Seen sensor to track previous_location_time separately
# NEW: Three-tier scanner resolution for room-level person tracking
#   - Tier 1: Direct HA area name match (zero config for dense scanner homes)
#   - Tier 2: CONF_SCANNER_AREAS override lookup (for sparse scanner homes)
#   - Tier 3: Occupancy disambiguation (when multiple rooms share a scanner)
# v3.2.8: Added support for active state change listeners in aggregation sensors
# FIX v3.2.6: Previous location bug - was reading from current dict instead of self.data
# FIX v3.2.6: Lowered confidence threshold from 0.5 to 0.3 for room occupant matching
# FIX v3.2.6: Added comprehensive diagnostic logging for room occupant matching
#

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er, device_registry as dr, area_registry as ar
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_TRACKED_PERSONS,
    CONF_PERSON_HIGH_CONFIDENCE_DISTANCE,
    CONF_PERSON_MEDIUM_CONFIDENCE_DISTANCE,
    DEFAULT_HIGH_CONFIDENCE_DISTANCE,
    DEFAULT_MEDIUM_CONFIDENCE_DISTANCE,
    UPDATE_INTERVAL,
    ENTRY_TYPE_ROOM,
    CONF_ENTRY_TYPE,
    CONF_AREA_ID,
    CONF_SCANNER_AREAS,
    STATE_OCCUPIED,
    CONF_PERSON_DECAY_TIMEOUT,
    DEFAULT_PERSON_DECAY_TIMEOUT,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_STALE,
    TRACKING_STATUS_LOST,
    STALE_THRESHOLD_SECONDS,
    MAX_RECENT_PATH_LENGTH,
)

_LOGGER = logging.getLogger(__name__)


class PersonTrackingCoordinator(DataUpdateCoordinator):
    """Coordinator for person tracking across rooms."""

    def __init__(self, hass: HomeAssistant, integration_entry: ConfigEntry) -> None:
        """Initialize the person tracking coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Person Tracking",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.integration_entry = integration_entry
        self.tracked_persons = integration_entry.data.get(CONF_TRACKED_PERSONS, [])
        
        # Distance thresholds for confidence calculation
        self.high_confidence_distance = integration_entry.data.get(
            CONF_PERSON_HIGH_CONFIDENCE_DISTANCE,
            DEFAULT_HIGH_CONFIDENCE_DISTANCE
        )
        self.medium_confidence_distance = integration_entry.data.get(
            CONF_PERSON_MEDIUM_CONFIDENCE_DISTANCE,
            DEFAULT_MEDIUM_CONFIDENCE_DISTANCE
        )
        
        # v3.2.4: Scanner-to-rooms mapping for three-tier resolution
        self._scanner_to_rooms: dict[str, list[str]] = {}
        self._area_id_to_room: dict[str, str] = {}  # area_id -> room_name (direct match)
        self._room_coordinators: dict[str, Any] = {}  # room_name -> coordinator reference
        # v3.8.9: Rooms with direct (Tier 1) BLE coverage (no CONF_SCANNER_AREAS)
        self._direct_ble_rooms: set[str] = set()
        # v3.6.21: Cache scanner map — only rebuild when room entries change
        self._scanner_map_entry_ids: set[str] = set()
        
        # v3.2.8.1: Decay timeout for staleness detection
        self.decay_timeout = integration_entry.data.get(
            CONF_PERSON_DECAY_TIMEOUT,
            DEFAULT_PERSON_DECAY_TIMEOUT
        )
        
        # D6+D7: DB visit tracking for person entry/exit/snapshot logging
        self._active_visit_ids: dict[str, int] = {}  # person_name -> visit_id
        self._last_snapshot_time: datetime | None = None
        self._SNAPSHOT_INTERVAL_SECONDS = 900  # 15 minutes

        # v3.18.6: BLE pre-arrival detection state
        self._person_was_away: dict[str, bool] = {}
        self._person_lost_since: dict[str, datetime] = {}  # When person went LOST
        self._pre_arrival_enabled: bool = True
        self._min_away_minutes: int = 15  # Minimum LOST time before BLE re-detection triggers pre-arrival

        _LOGGER.info(
            "Person tracking coordinator initialized for %d persons: %s (decay timeout: %ds)",
            len(self.tracked_persons),
            self.tracked_persons,
            self.decay_timeout
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch person location data with staleness decay tracking.
        
        v3.2.8.1: Implements presence decay logic that was missing from v3.2.8:
        - Tracks last_bermuda_update timestamp
        - Calculates tracking_status (active/stale/lost)
        - Maintains previous_location_time for Previous Seen sensor
        - Builds recent_path for debugging movement patterns
        """
        try:
            # v3.2.4: Build scanner-to-room mapping on each update
            await self._build_scanner_room_map()
            
            person_data = {}
            now = dt_util.now()
            
            for person_name in self.tracked_persons:
                # Get old data before update
                old_data = self.data.get(person_name, {}) if self.data else {}
                old_location = old_data.get("location", "unknown")
                old_path = old_data.get("recent_path", [])
                old_previous_location_time = old_data.get("previous_location_time")
                old_last_bermuda_update = old_data.get("last_bermuda_update")
                
                # Get person entity
                person_entity_id = f"person.{person_name.lower().replace(' ', '_')}"
                person_state = self.hass.states.get(person_entity_id)
                
                if not person_state:
                    _LOGGER.warning("Person entity not found: %s", person_entity_id)
                    person_data[person_name] = {
                        "location": "unknown",
                        "previous_location": old_location,
                        "previous_location_time": old_previous_location_time,
                        "last_changed": None,
                        "last_bermuda_update": None,
                        "tracking_status": TRACKING_STATUS_LOST,
                        "confidence": 0.0,
                        "method": "none",
                        "recent_path": old_path,
                    }
                    continue
                
                # Get Bermuda area sensor for room-level location
                area_sensor = await self._find_bermuda_area_sensor(person_name)
                
                if area_sensor:
                    area_state = self.hass.states.get(area_sensor)
                    if area_state and area_state.state not in ("unknown", "unavailable"):
                        # v3.2.4: Resolve Bermuda area to actual room using three-tier strategy
                        bermuda_area = area_state.state
                        resolved_room = self._resolve_person_room(bermuda_area)
                        
                        # Calculate confidence based on Bermuda distance sensors
                        confidence = await self._calculate_confidence(person_name, bermuda_area, resolved_room)
                        
                        # v3.2.8.3: Track location changes and previous_location_time
                        location_changed = (resolved_room != old_location)
                        previous_location_time = old_previous_location_time
                        if location_changed and old_location not in ("unknown", ""):
                            # v3.2.8.3 FIX: Record NOW (when person left), not old last_changed (when they entered)
                            previous_location_time = now
                            _LOGGER.debug(
                                "Person %s moved: '%s' -> '%s' (previous seen: %s)",
                                person_name, old_location, resolved_room, previous_location_time
                            )

                            # v3.3.0: Fire location change event for transition detection
                            event_data = {
                                "person_id": person_name,
                                "previous_location": old_location,
                                "current_location": resolved_room,
                                "timestamp": now
                            }
                            self.hass.bus.async_fire(
                                "ura_person_location_change",
                                event_data
                            )
                            _LOGGER.debug(
                                "Fired ura_person_location_change event: %s",
                                event_data
                            )

                            # D6: Log person exit (old room) and entry (new room) to database
                            self.hass.async_create_task(
                                self._log_person_room_change(
                                    person_name, old_location, resolved_room,
                                    confidence, "bermuda",
                                )
                            )
                        
                        # v3.2.8.1: Track recent path
                        recent_path = self._update_recent_path(old_path, resolved_room, old_location)
                        
                        # v3.2.8.1: Bermuda update detected - mark as active
                        last_bermuda_update = now
                        tracking_status = TRACKING_STATUS_ACTIVE
                        
                        person_data[person_name] = {
                            "location": resolved_room,
                            "bermuda_area": bermuda_area,  # Original Bermuda area for debugging
                            "previous_location": old_location,
                            "previous_location_time": previous_location_time,
                            "last_changed": area_state.last_changed,
                            "last_bermuda_update": last_bermuda_update,
                            "tracking_status": tracking_status,
                            "confidence": confidence,
                            "method": "bermuda",
                            "recent_path": recent_path,
                        }
                        
                        _LOGGER.debug(
                            "Person %s: Bermuda area '%s' resolved to room '%s' (confidence: %.2f, status: %s)",
                            person_name, bermuda_area, resolved_room, confidence, tracking_status
                        )

                        # v3.18.6: Detect BLE away→present transition for pre-arrival
                        # Guard: only trigger if person was LOST for >= min_away_minutes
                        # This prevents false triggers from quick trips (gardening, mailbox, etc.)
                        was_away = self._person_was_away.get(person_name, False)
                        if resolved_room and was_away:
                            # Person just appeared via BLE after being genuinely away
                            self._person_was_away[person_name] = False
                            self._person_lost_since.pop(person_name, None)
                            if self._pre_arrival_enabled:
                                # v3.21.1: Check Presence observation mode before dispatching
                                # DOMAIN already imported at module level (line 32)
                                mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                                presence_obs = False
                                if mgr:
                                    pres = getattr(mgr, "coordinators", {}).get("presence")
                                    if pres:
                                        presence_obs = getattr(pres, "observation_mode", False)
                                if presence_obs:
                                    _LOGGER.info(
                                        "BLE pre-arrival: %s [observation mode] would dispatch SIGNAL_PERSON_ARRIVING",
                                        person_name,
                                    )
                                else:
                                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                                    from .domain_coordinators.signals import SIGNAL_PERSON_ARRIVING
                                    person_entity = self._find_person_entity(person_name)
                                    if person_entity:
                                        async_dispatcher_send(
                                            self.hass,
                                            SIGNAL_PERSON_ARRIVING,
                                            {"person_entity": person_entity, "source": "ble"},
                                        )
                                    _LOGGER.info(
                                        "BLE pre-arrival: %s detected in %s (was away >%dm)",
                                        person_name, resolved_room, self._min_away_minutes,
                                    )
                        elif resolved_room:
                            # Present — clear away state
                            self._person_was_away[person_name] = False
                            self._person_lost_since.pop(person_name, None)
                        else:
                            # No room detected — track LOST duration
                            if tracking_status == TRACKING_STATUS_LOST:
                                if person_name not in self._person_lost_since:
                                    self._person_lost_since[person_name] = now
                                lost_duration = (now - self._person_lost_since[person_name]).total_seconds()
                                if lost_duration >= self._min_away_minutes * 60:
                                    self._person_was_away[person_name] = True
                    else:
                        # Bermuda sensor exists but no room detected
                        # v3.2.8.1: Check if we have recent Bermuda data to decay
                        if old_last_bermuda_update:
                            time_since_update = (now - old_last_bermuda_update).total_seconds()
                            if time_since_update < self.decay_timeout:
                                # Still within decay window - keep old location but mark as stale
                                tracking_status = TRACKING_STATUS_STALE
                                location = old_location
                                last_bermuda_update = old_last_bermuda_update
                                confidence = max(0.1, old_data.get("confidence", 0.3) * 0.5)  # Decay confidence
                                
                                person_data[person_name] = {
                                    "location": location,
                                    "previous_location": old_data.get("previous_location", "unknown"),
                                    "previous_location_time": old_previous_location_time,
                                    "last_changed": old_data.get("last_changed"),
                                    "last_bermuda_update": last_bermuda_update,
                                    "tracking_status": tracking_status,
                                    "confidence": confidence,
                                    "method": "bermuda_decay",
                                    "recent_path": old_path,
                                }
                                _LOGGER.debug(
                                    "Person %s: Bermuda stale (%.0fs since update), keeping location '%s' with status '%s'",
                                    person_name, time_since_update, location, tracking_status
                                )
                                continue
                        
                        # No recent Bermuda data or exceeded decay timeout - check person state for home/away
                        if person_state.state == "home":
                            person_data[person_name] = {
                                "location": "home",
                                "previous_location": old_location,
                                "previous_location_time": old_previous_location_time if old_location not in ("home", "unknown") else None,
                                "last_changed": person_state.last_changed,
                                "last_bermuda_update": None,
                                "tracking_status": TRACKING_STATUS_LOST,
                                "confidence": 0.3,
                                "method": "person_state",
                                "recent_path": [],  # Clear path when tracking is lost
                            }
                        else:
                            person_data[person_name] = {
                                "location": "away",
                                "previous_location": old_location,
                                "previous_location_time": old_previous_location_time if old_location not in ("away", "unknown") else None,
                                "last_changed": person_state.last_changed,
                                "last_bermuda_update": None,
                                "tracking_status": TRACKING_STATUS_LOST,
                                "confidence": 0.9,
                                "method": "person_state",
                                "recent_path": [],  # Clear path when away
                            }
                            # v3.18.6: Mark person as away for BLE pre-arrival detection
                            self._person_was_away[person_name] = True
                else:
                    # No Bermuda sensor - fall back to person entity state
                    if person_state.state == "home":
                        location = "home"
                        confidence = 0.3  # Low confidence - no room-level tracking
                    else:
                        location = "away"
                        confidence = 0.9  # High confidence for away state
                    
                    person_data[person_name] = {
                        "location": location,
                        "previous_location": old_location,
                        "previous_location_time": old_previous_location_time if old_location != location else None,
                        "last_changed": person_state.last_changed,
                        "last_bermuda_update": None,
                        "tracking_status": TRACKING_STATUS_LOST,
                        "confidence": confidence,
                        "method": "person_state",
                        "recent_path": [],
                    }
                    # v3.18.6: Track away state for BLE pre-arrival detection
                    if location == "away":
                        self._person_was_away[person_name] = True

            # D7: Periodic person snapshot logging (~every 15 minutes)
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                should_snapshot = (
                    self._last_snapshot_time is None
                    or (now - self._last_snapshot_time).total_seconds()
                    >= self._SNAPSHOT_INTERVAL_SECONDS
                )
                if should_snapshot:
                    self._last_snapshot_time = now
                    for pname, pdata in person_data.items():
                        self.hass.async_create_task(
                            db.log_person_snapshot(
                                person_id=pname,
                                room_id=pdata.get("location"),
                                confidence=pdata.get("confidence", 0.0),
                                method=pdata.get("method", "unknown"),
                            )
                        )

            return person_data

        except Exception as err:
            _LOGGER.error("Error updating person tracking data: %s", err)
            raise UpdateFailed(f"Error updating person tracking data: {err}") from err

    async def _log_person_room_change(
        self,
        person_name: str,
        old_room: str,
        new_room: str,
        confidence: float,
        method: str,
    ) -> None:
        """Log person exit from old room and entry to new room in database.

        Manages active visit IDs for exit/entry pairing.
        """
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return

        try:
            # Close the previous visit (exit old room)
            old_visit_id = self._active_visit_ids.pop(person_name, None)
            if old_visit_id is not None and old_visit_id > 0:
                await db.log_person_exit(visit_id=old_visit_id)

            # Open a new visit (enter new room) — skip for non-room locations
            if new_room not in ("away", "unknown", "home", ""):
                visit_id = await db.log_person_entry(
                    person_id=person_name,
                    room_id=new_room,
                    confidence=confidence,
                    detection_method=method,
                    transition_from=old_room,
                )
                if visit_id > 0:
                    self._active_visit_ids[person_name] = visit_id
        except Exception as e:
            _LOGGER.error("Error logging person room change for %s: %s", person_name, e)

    async def _build_scanner_room_map(self) -> None:
        """
        Build mapping from scanner area_ids to room names.

        v3.6.21: Cached — only rebuilds when room config entries change.

        This enables three-tier resolution:
        - Tier 1: Direct area match (area_id == bermuda area)
        - Tier 2: Scanner areas override (scanner_areas contains bermuda area)
        - Tier 3: Occupancy disambiguation (when multiple rooms share scanner)
        """
        # v3.6.21: Check if room entries changed since last build
        current_entry_ids = set()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                current_entry_ids.add(entry.entry_id)

        if current_entry_ids == self._scanner_map_entry_ids and self._area_id_to_room:
            # Room coordinators may change each cycle (new coordinators init), refresh those only
            domain_data = self.hass.data.get(DOMAIN, {})
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                room_name = entry.data.get("room_name")
                if room_name and entry.entry_id in domain_data:
                    coordinator = domain_data[entry.entry_id]
                    if hasattr(coordinator, 'data'):
                        self._room_coordinators[room_name] = coordinator
            return

        self._scanner_map_entry_ids = current_entry_ids
        self._scanner_to_rooms = {}
        self._area_id_to_room = {}
        self._room_coordinators = {}
        self._direct_ble_rooms = set()

        # Get area registry for name resolution
        area_reg = ar.async_get(self.hass)

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            
            room_name = entry.data.get("room_name")
            if not room_name:
                continue
            
            # Get config from both data and options (options override)
            config = {**entry.data, **entry.options}
            
            area_id = config.get(CONF_AREA_ID)
            scanner_areas = config.get(CONF_SCANNER_AREAS) or []

            # v3.8.9: Track rooms with direct BLE coverage (Tier 1)
            # A room is Tier 1 if it has an area_id but no scanner_areas override.
            if area_id and not scanner_areas:
                self._direct_ble_rooms.add(room_name.lower().replace(" ", "_"))

            # Build area_id to room mapping for Tier 1 (direct match)
            if area_id:
                # Get the HA area name for this area_id
                area_entry = area_reg.async_get_area(area_id)
                if area_entry:
                    # Store by both area_id and area name (for flexible matching)
                    self._area_id_to_room[area_id] = room_name
                    self._area_id_to_room[area_entry.name] = room_name
                    self._area_id_to_room[area_entry.name.lower().replace(" ", "_")] = room_name
                    
                    _LOGGER.debug(
                        "Tier 1 mapping: area '%s' (id: %s) -> room '%s'",
                        area_entry.name, area_id, room_name
                    )
            
            # Build scanner areas mapping for Tier 2 (override)
            # If no scanner_areas configured, use the room's own area
            effective_scanner_areas = scanner_areas if scanner_areas else ([area_id] if area_id else [])
            
            for scanner_area in effective_scanner_areas:
                if not scanner_area:
                    continue
                    
                # Normalize area for matching
                scanner_area_normalized = scanner_area.lower().replace(" ", "_")
                
                if scanner_area_normalized not in self._scanner_to_rooms:
                    self._scanner_to_rooms[scanner_area_normalized] = []
                
                if room_name not in self._scanner_to_rooms[scanner_area_normalized]:
                    self._scanner_to_rooms[scanner_area_normalized].append(room_name)
                
                # Also add by original name for flexible matching
                if scanner_area not in self._scanner_to_rooms:
                    self._scanner_to_rooms[scanner_area] = []
                if room_name not in self._scanner_to_rooms[scanner_area]:
                    self._scanner_to_rooms[scanner_area].append(room_name)
                    
                    _LOGGER.debug(
                        "Tier 2 mapping: scanner area '%s' -> room '%s'",
                        scanner_area, room_name
                    )
            
            # Store coordinator reference for Tier 3 occupancy check
            domain_data = self.hass.data.get(DOMAIN, {})
            if entry.entry_id in domain_data:
                coordinator = domain_data[entry.entry_id]
                if hasattr(coordinator, 'data'):
                    self._room_coordinators[room_name] = coordinator

    def _resolve_person_room(self, bermuda_area: str) -> str:
        """
        Resolve Bermuda scanner area to actual room name using three-tier strategy.
        
        Tier 1: Direct area match
            - If bermuda_area matches a room's CONF_AREA_ID exactly
            - Works for dense scanner homes (one scanner per room)
        
        Tier 2: Scanner areas override
            - If bermuda_area is in any room's CONF_SCANNER_AREAS list
            - Works for sparse scanner homes (shared scanners)
        
        Tier 3: Occupancy disambiguation
            - If multiple rooms claim the scanner area
            - Choose based on: currently occupied > most recently occupied > first alphabetically
        
        Args:
            bermuda_area: The area name reported by Bermuda (e.g., "Kitchen", "Study A Closet")
        
        Returns:
            The resolved room name, or bermuda_area as fallback
        """
        if not bermuda_area:
            return "unknown"
        
        bermuda_normalized = bermuda_area.lower().replace(" ", "_")
        
        # Tier 1: Direct area match
        if bermuda_area in self._area_id_to_room:
            room = self._area_id_to_room[bermuda_area]
            _LOGGER.debug("Tier 1 match: '%s' -> '%s'", bermuda_area, room)
            return room
        if bermuda_normalized in self._area_id_to_room:
            room = self._area_id_to_room[bermuda_normalized]
            _LOGGER.debug("Tier 1 match (normalized): '%s' -> '%s'", bermuda_area, room)
            return room
        
        # Tier 2: Scanner areas lookup
        candidates = []
        if bermuda_area in self._scanner_to_rooms:
            candidates = self._scanner_to_rooms[bermuda_area]
        elif bermuda_normalized in self._scanner_to_rooms:
            candidates = self._scanner_to_rooms[bermuda_normalized]
        
        if len(candidates) == 0:
            # No mapping found - return bermuda area as fallback
            _LOGGER.debug("No mapping for '%s', using as-is", bermuda_area)
            return bermuda_area
        
        if len(candidates) == 1:
            room = candidates[0]
            _LOGGER.debug("Tier 2 match (single): '%s' -> '%s'", bermuda_area, room)
            return room
        
        # Tier 3: Multiple rooms claim this scanner - disambiguate by occupancy
        _LOGGER.debug(
            "Tier 3 disambiguation needed: '%s' claimed by %s",
            bermuda_area, candidates
        )
        
        return self._disambiguate_by_occupancy(candidates, bermuda_area)

    def _disambiguate_by_occupancy(self, candidates: list[str], bermuda_area: str) -> str:
        """
        Disambiguate between multiple rooms that share a scanner.
        
        Priority:
        1. Currently occupied room (most recently became occupied wins ties)
        2. If none occupied, return first alphabetically
        
        Args:
            candidates: List of room names that claim this scanner area
            bermuda_area: Original Bermuda area for fallback
        
        Returns:
            Selected room name
        """
        occupied_rooms = []
        
        for room_name in candidates:
            if self._is_room_occupied(room_name):
                occupied_time = self._get_room_occupied_time(room_name)
                occupied_rooms.append((room_name, occupied_time))
        
        if len(occupied_rooms) == 1:
            room = occupied_rooms[0][0]
            _LOGGER.debug("Tier 3: Single occupied room '%s'", room)
            return room
        
        if len(occupied_rooms) > 1:
            # Multiple rooms occupied - pick most recently became occupied
            # Sort by time descending (most recent first), using datetime.min for None
            _epoch = dt_util.utc_from_timestamp(0)
            occupied_rooms.sort(
                key=lambda x: x[1] if x[1] else _epoch,
                reverse=True
            )
            room = occupied_rooms[0][0]
            _LOGGER.debug(
                "Tier 3: Multiple occupied, picked most recent '%s' from %s",
                room, [r[0] for r in occupied_rooms]
            )
            return room
        
        # No rooms occupied - return first alphabetically for consistency
        room = sorted(candidates)[0]
        _LOGGER.debug("Tier 3: None occupied, picked first alphabetically '%s'", room)
        return room

    def _is_room_occupied(self, room_name: str) -> bool:
        """Check if room is currently occupied via its coordinator."""
        coordinator = self._room_coordinators.get(room_name)
        if coordinator and hasattr(coordinator, 'data') and coordinator.data:
            return coordinator.data.get(STATE_OCCUPIED, False)
        return False

    def _get_room_occupied_time(self, room_name: str) -> datetime | None:
        """Get timestamp when room became occupied."""
        coordinator = self._room_coordinators.get(room_name)
        if coordinator and hasattr(coordinator, 'get_became_occupied_time'):
            return coordinator.get_became_occupied_time()
        return None

    def _find_person_entity(self, person_name: str) -> str | None:
        """Find person.* entity matching a tracked person name.

        v3.18.6: Maps BLE person name (from Bermuda sensor) to HA person entity.
        Uses the same logic as _async_update_data (line 133 pattern).
        """
        # Try direct match (same pattern as person_entity_id construction)
        candidate = f"person.{person_name.lower().replace(' ', '_')}"
        if self.hass.states.get(candidate):
            return candidate
        # Try without transformation
        candidate = f"person.{person_name}"
        if self.hass.states.get(candidate):
            return candidate
        return None

    # ==========================================================================
    # BERMUDA SENSOR DISCOVERY
    # ==========================================================================

    async def _find_bermuda_area_sensor(self, person_name: str) -> str | None:
        """Find the Bermuda area sensor for a person.

        v3.6.19: Replaced 8 hardcoded iPhone patterns with smarter discovery:
        1. Config override (CONF_BERMUDA_AREA_SENSORS per person)
        2. Private BLE derivation (device_tracker.* → sensor.*_area)
        3. Minimal fallback (2 common patterns)
        4. Registry fallback (Bermuda platform entities, last resort)
        """
        from .const import CONF_BERMUDA_AREA_SENSORS

        normalized_name = person_name.lower().replace(" ", "_")
        first_name = person_name.split()[0].lower() if person_name else ""

        # Strategy 1: Config override — explicit sensor per person
        bermuda_overrides = self.integration_entry.options.get(
            CONF_BERMUDA_AREA_SENSORS,
            self.integration_entry.data.get(CONF_BERMUDA_AREA_SENSORS, {})
        ) or {}
        override_sensor = bermuda_overrides.get(person_name) or bermuda_overrides.get(normalized_name)
        if override_sensor:
            if self.hass.states.get(override_sensor):
                _LOGGER.debug("Found Bermuda area sensor for %s via config override: %s", person_name, override_sensor)
                return override_sensor
            _LOGGER.warning("Configured Bermuda sensor %s for %s not found in HA", override_sensor, person_name)

        # Strategy 2: Private BLE derivation — find device_tracker from private_ble_device
        ent_reg = er.async_get(self.hass)
        for entity_entry in ent_reg.entities.values():
            if (entity_entry.platform == "private_ble_device"
                and entity_entry.domain == "device_tracker"
                and (first_name in entity_entry.entity_id or normalized_name in entity_entry.entity_id)):
                # Derive area sensor: sensor.{object_id}_area
                object_id = entity_entry.entity_id.split(".", 1)[1]
                area_sensor = f"sensor.{object_id}_area"
                if self.hass.states.get(area_sensor):
                    _LOGGER.debug("Found Bermuda area sensor for %s via private_ble: %s", person_name, area_sensor)
                    return area_sensor

        # Strategy 3: Minimal fallback — two common patterns
        patterns = [
            f"sensor.{first_name}_iphone_area",
            f"sensor.{normalized_name}_area",
        ]
        for pattern in patterns:
            if self.hass.states.get(pattern):
                _LOGGER.debug("Found Bermuda area sensor for %s: %s", person_name, pattern)
                return pattern

        # Strategy 4: Registry fallback — search Bermuda platform entities
        for entity_id, entity_entry in ent_reg.entities.items():
            if (entity_id.startswith("sensor.")
                and entity_id.endswith("_area")
                and "bermuda" in (entity_entry.platform or "")
                and (first_name in entity_id or normalized_name in entity_id)):
                _LOGGER.debug("Found Bermuda area sensor via registry for %s: %s", person_name, entity_id)
                return entity_id

        _LOGGER.warning("No Bermuda area sensor found for %s (tried: config, private_ble, patterns, registry)", person_name)
        return None

    # ==========================================================================
    # v3.2.4: FIXED CONFIDENCE CALCULATION
    # ==========================================================================

    async def _calculate_confidence(self, person_name: str, bermuda_area: str, resolved_room: str) -> float:
        """
        Calculate confidence score for person location based on Bermuda distance sensors.
        
        v3.2.4 FIX: Uses bermuda_area (scanner location) for scanner matching,
        not resolved_room (which may be different due to three-tier resolution).
        
        Algorithm:
        1. Find all Bermuda distance sensors for this person
        2. Find scanners in the bermuda_area
        3. Count how many see the device within high confidence distance
        4. Return tiered confidence based on scanner agreement
        """
        try:
            # Get Bermuda distance sensors for this person
            # v3.6.17: Only scan Bermuda entities instead of ALL entities
            ent_reg = er.async_get(self.hass)
            normalized_person = person_name.lower().replace(" ", "_")
            person_no_sep = person_name.lower().replace(" ", "")
            distance_sensors = []

            bermuda_entries = self.hass.config_entries.async_entries("bermuda")
            for be in bermuda_entries:
                for entity_entry in er.async_entries_for_config_entry(
                    ent_reg, be.entry_id
                ):
                    eid = entity_entry.entity_id
                    if (eid.startswith("sensor.") and
                        "distance_to_" in eid and
                        (normalized_person in eid or person_no_sep in eid)):
                        distance_sensors.append(eid)
                        # Auto-enable disabled sensors inline
                        if entity_entry.disabled:
                            ent_reg.async_update_entity(eid, disabled_by=None)
                            _LOGGER.info("Auto-enabled Bermuda distance sensor: %s", eid)

            if not distance_sensors:
                _LOGGER.debug("No Bermuda distance sensors found for %s", person_name)
                return 0.5  # Medium confidence - detected via area sensor but no distance data
            
            # v3.2.4 FIX: Get scanners in the BERMUDA area (where the person was detected)
            # Not the resolved room, which may be different
            area_scanners = await self._get_area_scanners(bermuda_area)
            
            if not area_scanners:
                _LOGGER.debug("No BLE scanners found in area %s", bermuda_area)
                return 0.5
            
            # Count scanners that see device within confidence distances
            close_scanners = 0
            very_close_scanners = 0
            detected_by_any = False
            # v3.6.21: Derive "very close" threshold from configurable high_confidence_distance
            very_close_threshold = self.high_confidence_distance / 2
            # v3.6.24: Track closest area scanner distance for music following
            closest_area_distance = None

            for sensor_id in distance_sensors:
                sensor_state = self.hass.states.get(sensor_id)
                if not sensor_state or sensor_state.state in ("unknown", "unavailable"):
                    continue

                detected_by_any = True

                try:
                    distance_ft = float(sensor_state.state)

                    # Extract scanner name from sensor_id
                    # Pattern: sensor.{person}_iphone_distance_to_{scanner_name}
                    scanner_name = sensor_id.split("distance_to_")[-1]
                    scanner_name_normalized = scanner_name.lower().replace("-", "_")

                    # Check if this scanner is in the area
                    is_area_scanner = any(
                        scanner_name_normalized in s.lower() or
                        s.lower() in scanner_name_normalized
                        for s in area_scanners
                    )

                    if is_area_scanner:
                        # v3.6.24: Track closest distance
                        if closest_area_distance is None or distance_ft < closest_area_distance:
                            closest_area_distance = distance_ft
                        if distance_ft < very_close_threshold:
                            very_close_scanners += 1
                            _LOGGER.debug(
                                "Very close scanner: %s (%.1f ft) for %s",
                                scanner_name, distance_ft, person_name
                            )
                        elif distance_ft < self.high_confidence_distance:
                            close_scanners += 1
                            _LOGGER.debug(
                                "Close scanner: %s (%.1f ft) for %s",
                                scanner_name, distance_ft, person_name
                            )

                except (ValueError, IndexError) as e:
                    _LOGGER.debug("Error parsing distance sensor %s: %s", sensor_id, e)
                    continue

            # v3.6.24: Store closest distance in person data for downstream consumers
            if person_name in self.data and closest_area_distance is not None:
                self.data[person_name]["closest_distance"] = closest_area_distance

            # Calculate confidence based on scanner count and distance
            if very_close_scanners >= 1:
                return 0.9  # At least one scanner very close (<5ft)
            elif close_scanners >= 2:
                return 0.9  # Multiple scanners confirm presence
            elif close_scanners == 1:
                return 0.7  # Single scanner confirmation
            elif detected_by_any:
                return 0.5  # Detected but scanner matching uncertain
            else:
                return 0.3  # Weak detection
            
        except Exception as e:
            _LOGGER.error("Error calculating confidence for %s in %s: %s", person_name, bermuda_area, e)
            return 0.5

    async def _get_area_scanners(self, area_name: str) -> list[str]:
        """
        Get list of BLE scanner device names in a Home Assistant area.
        
        v3.2.4 FIX: Searches by area name, not by room entry.
        Looks for Shelly, ESPHome, and other BLE-capable devices.
        """
        try:
            area_reg = ar.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
            
            # Find area by name
            area_entry = None
            for area in area_reg.async_list_areas():
                if (area.name == area_name or 
                    area.name.lower().replace(" ", "_") == area_name.lower().replace(" ", "_") or
                    area.id == area_name):
                    area_entry = area
                    break
            
            if not area_entry:
                _LOGGER.debug("Area not found: %s", area_name)
                return []
            
            scanners = []

            # v3.6.18: Only scan BLE integration devices instead of ALL devices
            ble_domains = ("shelly", "esphome", "bluetooth", "bermuda")
            for domain in ble_domains:
                for ce in self.hass.config_entries.async_entries(domain):
                    for device in dr.async_entries_for_config_entry(
                        dev_reg, ce.entry_id
                    ):
                        if device.area_id != area_entry.id:
                            continue
                        scanner_name = device.name_by_user or device.name
                        if scanner_name:
                            normalized_name = scanner_name.lower().replace(" ", "_").replace("-", "_")
                            scanners.append(normalized_name)
                            _LOGGER.debug("Found BLE scanner in area %s: %s", area_name, scanner_name)
            
            return scanners
            
        except Exception as e:
            _LOGGER.error("Error getting area scanners for %s: %s", area_name, e)
            return []

    # ==========================================================================
    # PUBLIC API METHODS
    # ==========================================================================

    def get_person_location(self, person_name: str) -> str:
        """Get current location for a person."""
        if not self.data or person_name not in self.data:
            return "unknown"
        return self.data[person_name]["location"]

    def get_person_confidence(self, person_name: str) -> float:
        """Get confidence score for a person's location."""
        if not self.data or person_name not in self.data:
            return 0.0
        return self.data[person_name]["confidence"]
    
    def get_person_previous_location(self, person_name: str) -> str:
        """Get previous location for a person."""
        if not self.data or person_name not in self.data:
            return "unknown"
        return self.data[person_name].get("previous_location", "unknown")
    

    def _update_recent_path(self, old_path: list[str], new_location: str, old_location: str) -> list[str]:
        """
        Update the recent path list with new location.
        
        v3.2.8.1: Implements path tracking for debugging movement patterns.
        
        Args:
            old_path: Previous path list
            new_location: New room location
            old_location: Previous room location
        
        Returns:
            Updated path list (max length = MAX_RECENT_PATH_LENGTH)
        """
        # Don't add to path if location didn't change
        if new_location == old_location:
            return old_path
        
        # Don't track non-room locations in path
        if new_location in ("unknown", "away", "home", ""):
            return old_path
        
        # Add new location to front of path
        new_path = [new_location] + old_path
        
        # Trim to max length
        return new_path[:MAX_RECENT_PATH_LENGTH]

    def get_person_previous_seen(self, person_name: str) -> datetime | None:
        """Get when person was last seen (last_changed timestamp)."""
        if not self.data or person_name not in self.data:
            return None
        return self.data[person_name].get("last_changed")
    def get_person_previous_location_time(self, person_name: str) -> datetime | None:
        """
        Get when person was last seen in their previous location.
        
        v3.2.8.1: Fixed - now returns previous_location_time instead of last_changed.
        This is what the "Previous Seen" sensor should display.
        
        Args:
            person_name: Name of person to check
        
        Returns:
            Timestamp when person was last in their previous location, or None
        """
        if not self.data or person_name not in self.data:
            return None
        return self.data[person_name].get("previous_location_time")

    def get_room_occupants(self, room_name: str) -> list[str]:
        """
        Get list of people currently in a room.
        
        v3.2.4: Uses resolved room names from three-tier resolution.
        Falls back to fuzzy matching for compatibility.
        v3.2.6: Lowered confidence threshold from 0.5 to 0.3
        v3.2.6: Added comprehensive diagnostic logging
        """
        if not self.data:
            _LOGGER.debug(
                "🔍 ROOM OCCUPANTS [%s]: No person data available (coordinator.data is empty)",
                room_name
            )
            return []
        
        occupants = []
        room_lower = room_name.lower().replace(" ", "_")
        
        _LOGGER.debug(
            "🔍 ROOM OCCUPANTS [%s]: Checking %d tracked persons, room_lower='%s'",
            room_name, len(self.data), room_lower
        )
        
        for person_name, person_info in self.data.items():
            location = person_info.get("location", "")
            confidence = person_info.get("confidence", 0)
            
            # Skip non-room locations
            if not location or location in ("unknown", "away", "home"):
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: %s skipped - non-room location '%s'",
                    room_name, person_name, location
                )
                continue
            
            # Check confidence threshold (v3.2.6: lowered from 0.5 to 0.3)
            if confidence < 0.3:
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: %s skipped - confidence %.2f < 0.3 threshold",
                    room_name, person_name, confidence
                )
                continue
            
            location_lower = location.lower().replace(" ", "_")
            
            # v3.6.19: Exact match only — three-tier resolution already
            # maps Bermuda areas to canonical room names. Fuzzy matching
            # caused false positives (e.g. "den" matching "garden").
            is_match = (room_lower == location_lower)
            
            if is_match:
                occupants.append(person_name)
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: ✓ MATCH - %s at '%s' (confidence: %.2f)",
                    room_name, person_name, location, confidence
                )
            else:
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: %s NO MATCH - location '%s' vs room '%s'",
                    room_name, person_name, location_lower, room_lower
                )
        
        _LOGGER.debug(
            "🔍 ROOM OCCUPANTS [%s]: Result = %s (%d people)",
            room_name, occupants, len(occupants)
        )
        
        return occupants
    
    # Alias for compatibility with v3.2.0 sensor.py
    def get_persons_in_room(self, room_name: str) -> list[str]:
        """Alias for get_room_occupants - for v3.2.0 compatibility."""
        return self.get_room_occupants(room_name)

    def is_room_direct_ble(self, room_name: str) -> bool:
        """
        Return True if room has direct (Tier 1) BLE scanner coverage.

        A room is Tier 1 when its own CONF_AREA_ID matches a Bermuda area
        and it does NOT configure CONF_SCANNER_AREAS. Rooms that configure
        CONF_SCANNER_AREAS are Tier 2 (shared scanner from an adjacent room)
        and return False — BLE alone should not drive occupancy for these
        rooms without motion/mmWave confirmation.

        Uses cached _direct_ble_rooms set built during _build_scanner_room_map.
        """
        return room_name.lower().replace(" ", "_") in self._direct_ble_rooms

    def get_zone_occupants(self, zone_rooms: list[str]) -> list[str]:
        """
        Get list of people currently in any room within a zone.
        """
        if not self.data:
            return []
        
        occupants = set()
        for room_name in zone_rooms:
            room_occupants = self.get_room_occupants(room_name)
            occupants.update(room_occupants)
        
        return sorted(list(occupants))
    
    # Alias for compatibility with v3.2.0 aggregation.py
    def get_persons_in_zone(self, zone_rooms: list[str]) -> list[str]:
        """Alias for get_zone_occupants - for v3.2.0 compatibility."""
        return self.get_zone_occupants(zone_rooms)

    # ==========================================================================
    # v3.2.6: DIAGNOSTIC DATA
    # ==========================================================================

    def get_diagnostic_data(self) -> dict[str, Any]:
        """
        Get diagnostic information about person tracking coordinator.
        
        v3.2.6: Added for troubleshooting staleness and matching issues.
        """
        return {
            "tracked_persons": self.tracked_persons,
            "data_available": self.data is not None,
            "person_count": len(self.data) if self.data else 0,
            "last_update": self.last_update_success_time.isoformat() if hasattr(self, 'last_update_success_time') and self.last_update_success_time else "unknown",
            "update_interval_seconds": UPDATE_INTERVAL,
            "area_mappings_count": len(self._area_id_to_room),
            "scanner_mappings_count": len(self._scanner_to_rooms),
            "room_coordinators_count": len(self._room_coordinators),
            "confidence_threshold": 0.3,
            "persons_data": {
                name: {
                    "location": info.get("location", "unknown"),
                    "confidence": info.get("confidence", 0),
                    "method": info.get("method", "unknown"),
                    "bermuda_area": info.get("bermuda_area", "N/A"),
                }
                for name, info in (self.data or {}).items()
            }
        }

    def get_tracked_person_count(self) -> int:
        """
        Get count of tracked people who are home (not away/unknown).
        
        v3.2.6: Added for whole-house occupant count sensor.
        """
        if not self.data:
            return 0
        
        count = 0
        for person_info in self.data.values():
            location = person_info.get("location", "unknown")
            if location not in ("unknown", "away"):
                count += 1
        
        return count
