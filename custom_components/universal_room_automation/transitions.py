"""Room transition detection for Universal Room Automation v3.6.20.

Detects and classifies room-to-room transitions for pattern learning
and cross-room coordination.

v3.6.20: Added ping-pong suppression — if A→B followed by B→A within
         PING_PONG_WINDOW_SECONDS, the return leg is suppressed.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers.event import async_track_time_interval

from .const import PING_PONG_WINDOW_SECONDS

_LOGGER = logging.getLogger(__name__)


@dataclass
class RoomTransition:
    """Represents a room-to-room transition."""
    
    person_id: str
    from_room: str
    to_room: str
    timestamp: datetime
    duration_seconds: int
    path_type: str  # 'direct', 'via_hallway', 'separate'
    confidence: float
    via_room: Optional[str] = None


class TransitionDetector:
    """Detect and classify room-to-room transitions."""
    
    # Path classification parameters
    MAX_DIRECT_DURATION = 30  # seconds - max time for direct transition
    MAX_HALLWAY_DURATION = 60  # seconds - max time for hallway transition
    
    def __init__(
        self,
        hass: HomeAssistant,
        person_coordinator,
        database
    ) -> None:
        """Initialize transition detector."""
        self.hass = hass
        self.person_coordinator = person_coordinator
        self.database = database

        # Track recent locations for each person
        self._location_history: dict[str, list[dict[str, Any]]] = {}

        # Transition event listeners
        self._listeners: list[Callable] = []

        # v3.5.2: Transit validator (optional, wired in after init)
        self._transit_validator = None

        # v3.6.20: Ping-pong suppression — recent transitions per person
        # dict[person_id, list[tuple[from_room, to_room, timestamp]]]
        self._recent_transitions: dict[str, list[tuple[str, str, datetime]]] = {}

        _LOGGER.info("TransitionDetector initialized")
    
    async def async_init(self) -> None:
        """Initialize detector and subscribe to location changes."""
        # Subscribe to person location change events via event bus
        self.hass.bus.async_listen(
            "ura_person_location_change",
            self._on_location_change
        )
        
        # Start periodic cleanup of old location history
        async_track_time_interval(
            self.hass,
            self._async_cleanup_history,
            timedelta(minutes=5)
        )
        
        _LOGGER.info(
            "TransitionDetector initialized: "
            "Listening for 'ura_person_location_change' events, "
            "cleanup interval=5min"
        )
    
    def set_transit_validator(self, validator) -> None:
        """Wire in the TransitValidator after it is initialized."""
        self._transit_validator = validator
        _LOGGER.debug("TransitValidator wired into TransitionDetector")

    @callback
    def async_add_listener(self, listener: Callable) -> None:
        """Add listener for transition events."""
        self._listeners.append(listener)
    
    async def _on_location_change(self, event: Event) -> None:
        """Handle person location change event from person_coordinator.
        
        Event data:
            person_id: str
            previous_location: str
            current_location: str
            timestamp: datetime
        """
        data = event.data
        person_id = data.get("person_id")
        previous_location = data.get("previous_location")
        current_location = data.get("current_location")
        timestamp = data.get("timestamp", dt_util.now())
        
        _LOGGER.debug(
            "Location change event received: person=%s, %s → %s",
            person_id, previous_location, current_location
        )
        
        if not person_id or not current_location:
            _LOGGER.debug("Skipping: missing person_id or current_location")
            return
        
        # Skip if no previous location (first detection)
        if not previous_location or previous_location == "unknown":
            _LOGGER.debug("Skipping: no valid previous_location (first detection)")
            self._update_history(person_id, current_location, timestamp)
            return
        
        # Skip if location didn't actually change
        if previous_location == current_location:
            _LOGGER.debug("Skipping: location unchanged")
            return
        
        # Detect and classify transition
        transition = await self._detect_transition(
            person_id,
            previous_location,
            current_location,
            timestamp
        )
        
        if transition:
            _LOGGER.info(
                "Transition: %s %s → %s (%s, %ds, confidence=%.2f)",
                person_id, previous_location, current_location,
                transition.path_type, transition.duration_seconds, transition.confidence
            )

            # Log to database (always — even if suppressed)
            await self._log_transition(transition)

            # v3.5.2: Validate transition via camera checkpoint data
            if self._transit_validator:
                try:
                    validation = await self._transit_validator.validate_transition(transition)
                    if validation.path_confidence_delta != 0.0:
                        await self._update_transition_confidence(transition, validation)
                    # Attach validation result to transition for listeners
                    transition._validation = validation
                except Exception as e:
                    _LOGGER.error("Transit validation error: %s", e)

            # v3.6.20: Ping-pong suppression — suppress return leg if
            # A→B followed by B→A within window
            if self._is_ping_pong(person_id, previous_location, current_location, timestamp):
                _LOGGER.info(
                    "Ping-pong suppressed: %s %s → %s (return leg within %ds window)",
                    person_id, previous_location, current_location,
                    PING_PONG_WINDOW_SECONDS,
                )
                self._record_transition(person_id, previous_location, current_location, timestamp)
                # Skip notifying listeners — transition is logged but not acted on
            else:
                self._record_transition(person_id, previous_location, current_location, timestamp)
                # Notify listeners
                await self._notify_listeners(transition)
                _LOGGER.debug("Notified %d transition listeners", len(self._listeners))
        
        # Update history
        self._update_history(person_id, current_location, timestamp)
    
    async def _detect_transition(
        self,
        person_id: str,
        from_room: str,
        to_room: str,
        timestamp: datetime
    ) -> Optional[RoomTransition]:
        """Detect and classify transition."""
        
        # Get location history for this person
        history = self._location_history.get(person_id, [])
        
        if not history:
            # No history - direct transition with unknown duration
            return RoomTransition(
                person_id=person_id,
                from_room=from_room,
                to_room=to_room,
                timestamp=timestamp,
                duration_seconds=0,
                path_type="direct",
                confidence=0.5  # Low confidence without history
            )
        
        # Get last known location
        last_entry = history[-1]
        last_location = last_entry["location"]
        last_timestamp = last_entry["timestamp"]
        
        # Calculate duration
        duration = (timestamp - last_timestamp).total_seconds()
        
        # Classify transition type
        path_type, via_room = self._classify_path_type(
            from_room,
            to_room,
            duration,
            history
        )
        
        # Calculate confidence
        confidence = self._calculate_confidence(duration, path_type)
        
        return RoomTransition(
            person_id=person_id,
            from_room=from_room,
            to_room=to_room,
            timestamp=timestamp,
            duration_seconds=int(duration),
            path_type=path_type,
            confidence=confidence,
            via_room=via_room
        )
    
    def _classify_path_type(
        self,
        from_room: str,
        to_room: str,
        duration: float,
        history: list[dict[str, Any]]
    ) -> tuple[str, Optional[str]]:
        """Classify transition path type.
        
        Returns:
            (path_type, via_room)
            
        Path types:
            - direct: Quick, direct movement
            - via_hallway: Movement through intermediate room
            - separate: Separate events (person left one room, later entered another)
        """
        # Direct transition (fast)
        if duration <= self.MAX_DIRECT_DURATION:
            return ("direct", None)
        
        # Check for intermediate rooms in history
        if len(history) >= 2:
            # Look back up to 3 entries
            recent = history[-3:]
            
            for entry in recent:
                location = entry["location"]
                # Check if this might be a hallway/intermediate room
                if location not in [from_room, to_room]:
                    loc_lower = location.lower()
                if any(term in loc_lower for term in (
                    "hallway", "corridor", "hall", "foyer",
                    "entry", "landing", "passage", "vestibule",
                )):

                        return ("via_hallway", location)
        
        # Via hallway (medium duration)
        if duration <= self.MAX_HALLWAY_DURATION:
            return ("via_hallway", None)
        
        # Separate events (long duration)
        return ("separate", None)
    
    def _calculate_confidence(self, duration: float, path_type: str) -> float:
        """Calculate confidence score for transition (0.0 - 1.0)."""
        if path_type == "direct":
            # High confidence for quick transitions
            if duration <= 10:
                return 0.95
            elif duration <= 20:
                return 0.85
            else:
                return 0.75
        
        elif path_type == "via_hallway":
            # Medium confidence
            if duration <= 30:
                return 0.80
            else:
                return 0.65
        
        else:  # separate
            # Lower confidence for long gaps
            return 0.50
    
    def _update_history(
        self,
        person_id: str,
        location: str,
        timestamp: datetime
    ) -> None:
        """Update location history for person."""
        if person_id not in self._location_history:
            self._location_history[person_id] = []
        
        self._location_history[person_id].append({
            "location": location,
            "timestamp": timestamp
        })
        
        # Keep only last 10 entries per person
        if len(self._location_history[person_id]) > 10:
            self._location_history[person_id] = self._location_history[person_id][-10:]
    
    async def _log_transition(self, transition: RoomTransition) -> None:
        """Log transition to database."""
        try:
            await self.database.log_transition(
                person_id=transition.person_id,
                from_room=transition.from_room,
                to_room=transition.to_room,
                timestamp=transition.timestamp,
                duration_seconds=transition.duration_seconds,
                path_type=transition.path_type,
                confidence=transition.confidence,
                via_room=transition.via_room
            )
        except Exception as e:
            _LOGGER.error("Failed to log transition: %s", e)
    
    async def _update_transition_confidence(self, transition: RoomTransition, validation) -> None:
        """Update the confidence of the most recently logged transition.

        Called when TransitValidator returns a non-zero path_confidence_delta.
        Updates the database row that was just written by _log_transition().
        """
        try:
            new_confidence = min(1.0, transition.confidence + validation.path_confidence_delta)
            await self.database.update_transition_validation(
                person_id=transition.person_id,
                timestamp=transition.timestamp,
                new_confidence=new_confidence,
                validation_method=validation.path_method,
                checkpoint_rooms=validation.checkpoint_rooms,
            )
        except Exception as e:
            _LOGGER.error("Failed to update transition validation: %s", e)

    # ==========================================================================
    # v3.6.20: PING-PONG SUPPRESSION
    # ==========================================================================

    def _is_ping_pong(
        self, person_id: str, from_room: str, to_room: str, timestamp: datetime
    ) -> bool:
        """Check if this transition is the return leg of a ping-pong.

        A→B followed by B→A within PING_PONG_WINDOW_SECONDS = ping-pong.
        A→B followed by B→C = not ping-pong (different destination).
        """
        recent = self._recent_transitions.get(person_id, [])
        if not recent:
            return False

        window = timedelta(seconds=PING_PONG_WINDOW_SECONDS)
        # Check if any recent transition was to_room→from_room (the forward leg)
        for prev_from, prev_to, prev_ts in reversed(recent):
            if (timestamp - prev_ts) > window:
                break  # Too old
            if prev_from == to_room and prev_to == from_room:
                return True
        return False

    def _record_transition(
        self, person_id: str, from_room: str, to_room: str, timestamp: datetime
    ) -> None:
        """Record a transition for ping-pong detection."""
        if person_id not in self._recent_transitions:
            self._recent_transitions[person_id] = []
        self._recent_transitions[person_id].append((from_room, to_room, timestamp))
        # Keep only last 10 per person
        if len(self._recent_transitions[person_id]) > 10:
            self._recent_transitions[person_id] = self._recent_transitions[person_id][-10:]

    async def _notify_listeners(self, transition: RoomTransition) -> None:
        """Notify all registered listeners of transition."""
        import asyncio
        for listener in self._listeners:
            try:
                result = listener(transition)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                _LOGGER.error("Transition listener error: %s", e)

    async def _async_cleanup_history(self, now: datetime) -> None:
        """Periodic cleanup of old location history and ping-pong records."""
        cutoff = now - timedelta(hours=1)
        ping_pong_cutoff = now - timedelta(seconds=PING_PONG_WINDOW_SECONDS * 2)

        for person_id in list(self._location_history.keys()):
            history = self._location_history[person_id]

            # Remove entries older than 1 hour
            self._location_history[person_id] = [
                entry for entry in history
                if entry["timestamp"] > cutoff
            ]

            # Remove empty histories
            if not self._location_history[person_id]:
                del self._location_history[person_id]

        # v3.6.20: Clean up old ping-pong records
        for person_id in list(self._recent_transitions.keys()):
            self._recent_transitions[person_id] = [
                (f, t, ts) for f, t, ts in self._recent_transitions[person_id]
                if ts > ping_pong_cutoff
            ]
            if not self._recent_transitions[person_id]:
                del self._recent_transitions[person_id]
    
    async def get_recent_transitions(
        self,
        person_id: str,
        hours: int = 24
    ) -> list[RoomTransition]:
        """Get recent transitions for a person from database."""
        try:
            return await self.database.get_transitions(
                person_id=person_id,
                hours=hours
            )
        except Exception as e:
            _LOGGER.error("Failed to get recent transitions: %s", e)
            return []
