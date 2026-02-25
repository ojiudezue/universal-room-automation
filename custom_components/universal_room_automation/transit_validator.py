"""Transit path validation for Universal Room Automation v3.5.2.

Validates room-to-room transitions using camera checkpoint data and
tracks egress camera direction (entry vs exit) via interior correlation.
"""
#
# Universal Room Automation v3.5.2
# Build: 2026-02-24
# File: transit_validator.py
#

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_EGRESS_CAMERAS,
    CONF_FACE_RECOGNITION_ENABLED,
    ENTRY_TYPE_INTEGRATION,
    CONF_ENTRY_TYPE,
    TRANSIT_CHECKPOINT_STALE_SECONDS,
    TRANSIT_CHECKPOINT_WINDOW_SECONDS,
    EGRESS_ENTRY_WINDOW_SECONDS,
    EGRESS_EXIT_WINDOW_SECONDS,
    EGRESS_AMBIGUOUS_COOLDOWN_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class TransitValidationResult:
    """Result of transit path validation via camera checkpoint data."""

    # Path validation
    path_validated: bool
    path_confidence_delta: float  # -0.15 to +0.10, applied to transition confidence
    checkpoint_rooms: list[str]
    path_method: str  # "path_confirmed" | "path_plausible" | "no_camera_data" | "path_implausible"

    # Identity validation (separate concern)
    identity_status: str  # "confirmed" | "unidentified" | "mismatch" | "unavailable"
    camera_person_id: str | None  # Face-recognized ID (may differ from BLE ID)


class TransitValidator:
    """Validates room transitions using camera checkpoint data.

    Called by TransitionDetector after each transition is recorded.
    Camera data is optional — all methods degrade gracefully to
    returning the original BLE-only confidence if no camera data exists.
    """

    # If the egress or shared-space camera last saw this person more than
    # this many seconds ago, we can't use it as a transit checkpoint.
    CHECKPOINT_STALE_SECONDS = TRANSIT_CHECKPOINT_STALE_SECONDS

    # Time window within which a camera checkpoint must have fired
    # after BLE said the person left room A (to count as "path confirmed").
    CHECKPOINT_WINDOW_SECONDS = TRANSIT_CHECKPOINT_WINDOW_SECONDS

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize TransitValidator."""
        self.hass = hass
        # Map: person_id -> list of {camera_entity_id, timestamp, room}
        self._camera_sightings: dict[str, list[dict[str, Any]]] = {}
        self._unsub: list = []
        self._face_recognition_enabled = False

    async def async_init(self) -> None:
        """Subscribe to camera person detection entities.

        Pulls the list of configured camera entities from hass.data[DOMAIN]:
        - interior camera entities (CONF_CAMERA_PERSON_ENTITIES at integration level)
        - egress cameras (CONF_EGRESS_CAMERAS at integration level)

        For each entity, listens to state changes. When a camera fires,
        records a sighting entry keyed by person_id (if face recognition
        provides an ID) or as "unidentified".
        """
        # Load face recognition config
        for config_entry in self.hass.config_entries.async_entries(DOMAIN):
            if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**config_entry.data, **config_entry.options}
                self._face_recognition_enabled = merged.get(CONF_FACE_RECOGNITION_ENABLED, False)
                break

        # Gather all camera entities to subscribe to
        camera_entities: list[str] = []

        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if camera_manager:
            try:
                # Get interior cameras (person detection binary sensors resolved from camera entities)
                interior = camera_manager._get_interior_camera_entities()
                camera_entities.extend(interior)

                # Get egress cameras
                egress = camera_manager._get_integration_camera_list(CONF_EGRESS_CAMERAS)
                camera_entities.extend(egress)
            except Exception as e:
                _LOGGER.debug("Could not get camera list from camera_manager: %s", e)

        if not camera_entities:
            _LOGGER.debug(
                "TransitValidator: no camera entities found — path validation will always return no_camera_data"
            )

        # Subscribe to state changes for each camera entity
        from homeassistant.helpers.event import async_track_state_change_event

        for entity_id in set(camera_entities):
            unsub = async_track_state_change_event(
                self.hass,
                [entity_id],
                self._on_camera_state_change,
            )
            self._unsub.append(unsub)

        # Schedule periodic cleanup of old sightings (every 30 minutes)
        unsub_cleanup = async_track_time_interval(
            self.hass,
            self._async_cleanup_sightings,
            timedelta(minutes=30),
        )
        self._unsub.append(unsub_cleanup)

        _LOGGER.info(
            "TransitValidator initialized: subscribed to %d camera entities, "
            "face_recognition_enabled=%s",
            len(set(camera_entities)),
            self._face_recognition_enabled,
        )

    async def validate_transition(
        self,
        transition: Any,
        concurrent_transitions: list[Any] | None = None,
    ) -> TransitValidationResult:
        """Assess how well camera data supports a recorded transition.

        Returns a TransitValidationResult with path validation and
        identity validation as separate concerns.

        When concurrent_transitions is provided, uses
        _correlate_sighting_to_transition() to assign shared-space
        camera sightings to the correct person.
        """
        shared_cameras = self._get_shared_space_cameras()

        if not shared_cameras:
            # No cameras configured at all
            return TransitValidationResult(
                path_validated=False,
                path_confidence_delta=0.0,
                checkpoint_rooms=[],
                path_method="no_camera_data",
                identity_status="unavailable",
                camera_person_id=None,
            )

        # Look for sightings in the checkpoint window around transition timestamp
        ts = transition.timestamp
        if isinstance(ts, str):
            ts = dt_util.parse_datetime(ts) or dt_util.now()

        window_start = ts - timedelta(seconds=self.CHECKPOINT_STALE_SECONDS)
        window_end = ts + timedelta(seconds=self.CHECKPOINT_WINDOW_SECONDS)

        # Collect all "unidentified" or person-specific sightings in window
        relevant_sightings: list[dict[str, Any]] = []

        # Check sightings for the specific person
        person_sightings = self._camera_sightings.get(transition.person_id, [])
        for sighting in person_sightings:
            sighting_ts = sighting.get("timestamp")
            if isinstance(sighting_ts, str):
                sighting_ts = dt_util.parse_datetime(sighting_ts)
            if sighting_ts and window_start <= sighting_ts <= window_end:
                if sighting.get("camera_entity_id") in shared_cameras:
                    relevant_sightings.append(sighting)

        # Also check unidentified sightings (cameras can't always ID)
        unidentified_sightings = self._camera_sightings.get("unidentified", [])
        for sighting in unidentified_sightings:
            sighting_ts = sighting.get("timestamp")
            if isinstance(sighting_ts, str):
                sighting_ts = dt_util.parse_datetime(sighting_ts)
            if sighting_ts and window_start <= sighting_ts <= window_end:
                if sighting.get("camera_entity_id") in shared_cameras:
                    relevant_sightings.append(sighting)

        # Determine path method
        if concurrent_transitions:
            path_method = self._correlate_sighting_to_transition(
                transition, concurrent_transitions, relevant_sightings
            )
        elif relevant_sightings:
            path_method = "path_confirmed"
        else:
            # Check if shared-space cameras are active (have any recent sightings at all)
            cameras_active = self._are_shared_space_cameras_active(shared_cameras)
            if cameras_active:
                path_method = "path_implausible"
            else:
                path_method = "no_camera_data"

        # Map path_method to confidence delta and path_validated
        delta_map = {
            "path_confirmed": +0.10,
            "path_plausible": 0.00,
            "no_camera_data": 0.00,
            "path_implausible": -0.15,
        }
        path_confidence_delta = delta_map.get(path_method, 0.0)
        path_validated = path_method in ("path_confirmed", "path_plausible")

        checkpoint_rooms = list({s.get("room", "") for s in relevant_sightings if s.get("room")})

        # Identity validation
        identity_status = "unavailable"
        camera_person_id = None

        if self._face_recognition_enabled and relevant_sightings:
            # Look for face-matched sightings
            face_matched = [
                s for s in relevant_sightings
                if s.get("person_id") and s.get("person_id") != "unidentified"
            ]
            if face_matched:
                best_match = face_matched[0]
                cam_pid = best_match.get("person_id")
                camera_person_id = cam_pid
                if cam_pid == transition.person_id:
                    identity_status = "confirmed"
                else:
                    identity_status = "mismatch"
            else:
                identity_status = "unidentified"

        return TransitValidationResult(
            path_validated=path_validated,
            path_confidence_delta=path_confidence_delta,
            checkpoint_rooms=checkpoint_rooms,
            path_method=path_method,
            identity_status=identity_status,
            camera_person_id=camera_person_id,
        )

    def get_last_camera_sighting(
        self,
        person_id: str,
        max_age_hours: float = 4.0,
    ) -> dict[str, Any] | None:
        """Return the most recent camera sighting for a person.

        Used by phone-left-behind detection. Returns None if no sighting
        within max_age_hours or if person has never been seen by cameras.
        """
        sightings = self._camera_sightings.get(person_id, [])
        if not sightings:
            return None

        cutoff = dt_util.now() - timedelta(hours=max_age_hours)
        recent = []
        for sighting in sightings:
            ts = sighting.get("timestamp")
            if isinstance(ts, str):
                ts = dt_util.parse_datetime(ts)
            if ts and ts >= cutoff:
                recent.append((ts, sighting))

        if not recent:
            return None

        # Return most recent
        recent.sort(key=lambda x: x[0], reverse=True)
        return recent[0][1]

    def _get_shared_space_cameras(self) -> list[str]:
        """Return all shared-space camera entity IDs (hallways, foyers, stairs).

        Instead of computing topology between specific rooms, we check
        ALL configured interior cameras. A sighting on any interior camera
        within the checkpoint window is treated as path support.

        Cameras configured via CONF_CAMERA_PERSON_ENTITIES are shared-space
        cameras by definition (users configure only common-area cameras there).
        """
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if not camera_manager:
            return []

        try:
            return camera_manager._get_interior_camera_entities()
        except Exception as e:
            _LOGGER.debug("Could not get shared-space cameras: %s", e)
            return []

    def _are_shared_space_cameras_active(self, shared_cameras: list[str]) -> bool:
        """Check if any shared-space camera has fired in the last 10 minutes."""
        cutoff = dt_util.now() - timedelta(minutes=10)
        for person_id, sightings in self._camera_sightings.items():
            for sighting in sightings:
                if sighting.get("camera_entity_id") not in shared_cameras:
                    continue
                ts = sighting.get("timestamp")
                if isinstance(ts, str):
                    ts = dt_util.parse_datetime(ts)
                if ts and ts >= cutoff:
                    return True
        return False

    def _correlate_sighting_to_transition(
        self,
        transition: Any,
        concurrent_transitions: list[Any],
        sightings: list[dict[str, Any]],
    ) -> str:
        """Assign camera sightings to transitions when multiple people transit simultaneously.

        Rules:
        1. Face-matched sighting → assign to matching person's transition
        2. Unidentified sighting → assign to closest-timed transition
        3. If sightings < transitions, unmatched transitions get "no_camera_data" (not negative)
        4. If sightings >= transitions, all get "path_plausible"
        """
        all_transitions = [transition] + list(concurrent_transitions)
        n_transitions = len(all_transitions)
        n_sightings = len(sightings)

        if n_sightings == 0:
            return "no_camera_data"

        if n_sightings >= n_transitions:
            # Enough sightings for all transitions
            return "path_plausible"

        # Check if this transition has a face-matched sighting
        ts = transition.timestamp
        if isinstance(ts, str):
            ts = dt_util.parse_datetime(ts) or dt_util.now()

        for sighting in sightings:
            # Rule 1: face-matched
            if (sighting.get("person_id")
                    and sighting.get("person_id") != "unidentified"
                    and sighting.get("person_id") == transition.person_id):
                return "path_plausible"

        # Rule 2: assign unidentified sighting to closest-timed transition
        if sightings:
            best_transition = None
            best_delta = None
            for t in all_transitions:
                t_ts = t.timestamp
                if isinstance(t_ts, str):
                    t_ts = dt_util.parse_datetime(t_ts) or dt_util.now()
                for sighting in sightings:
                    s_ts = sighting.get("timestamp")
                    if isinstance(s_ts, str):
                        s_ts = dt_util.parse_datetime(s_ts)
                    if s_ts:
                        delta = abs((s_ts - t_ts).total_seconds())
                        if best_delta is None or delta < best_delta:
                            best_delta = delta
                            best_transition = t

            if best_transition and best_transition.person_id == transition.person_id:
                return "path_plausible"

        # Rule 3: this transition not assigned a sighting
        return "no_camera_data"

    @callback
    def _on_camera_state_change(self, event: Event) -> None:
        """Handle state change event from a camera person detection entity."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        # Only record when camera fires (state becomes "on" or a non-zero count)
        state_val = new_state.state
        if state_val not in ("on", "true", "1") and not (
            state_val.isdigit() and int(state_val) > 0
        ):
            return

        entity_id = new_state.entity_id
        timestamp = dt_util.now()

        # Determine room from entity area_id
        room = None
        try:
            entity_registry = self.hass.helpers.entity_registry.async_get(self.hass)
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry and entity_entry.area_id:
                area_registry = self.hass.helpers.area_registry.async_get(self.hass)
                area = area_registry.async_get_area(entity_entry.area_id)
                if area:
                    room = area.name
        except Exception:
            pass

        # Determine person_id from face recognition data
        person_id = "unidentified"
        if self._face_recognition_enabled:
            attrs = new_state.attributes
            # Some integrations expose person/face data in attributes
            face_id = attrs.get("person_id") or attrs.get("face_id") or attrs.get("label")
            if face_id and str(face_id) != "unknown":
                person_id = str(face_id)

        sighting = {
            "camera_entity_id": entity_id,
            "timestamp": timestamp,
            "room": room,
            "person_id": person_id,
        }

        if person_id not in self._camera_sightings:
            self._camera_sightings[person_id] = []
        self._camera_sightings[person_id].append(sighting)

        # Cap list size
        if len(self._camera_sightings[person_id]) > 200:
            self._camera_sightings[person_id] = self._camera_sightings[person_id][-200:]

        _LOGGER.debug(
            "Camera sighting recorded: entity=%s, person=%s, room=%s",
            entity_id, person_id, room,
        )

    @callback
    def _async_cleanup_sightings(self, now: datetime) -> None:
        """Periodic cleanup — remove sightings older than 4 hours."""
        cutoff = now - timedelta(hours=4)
        for person_id in list(self._camera_sightings.keys()):
            self._camera_sightings[person_id] = [
                s for s in self._camera_sightings[person_id]
                if _parse_ts(s.get("timestamp")) >= cutoff
            ]
            if not self._camera_sightings[person_id]:
                del self._camera_sightings[person_id]

    async def async_teardown(self) -> None:
        """Unsubscribe all listeners."""
        for unsub in self._unsub:
            try:
                unsub()
            except Exception:
                pass
        self._unsub.clear()
        _LOGGER.debug("TransitValidator torn down")


class EgressDirectionTracker:
    """Correlate egress camera events with interior cameras to determine direction.

    Egress cameras are at exterior doors. Interior near-door cameras are
    in foyers, hallways near garage entry, etc.

    Direction logic:
    - Egress fires, then interior fires within ENTRY_WINDOW_SECONDS → entry
    - Interior fires, then egress fires within EXIT_WINDOW_SECONDS → exit
    - Neither match → ambiguous
    """

    ENTRY_WINDOW_SECONDS = EGRESS_ENTRY_WINDOW_SECONDS
    EXIT_WINDOW_SECONDS = EGRESS_EXIT_WINDOW_SECONDS
    AMBIGUOUS_COOLDOWN_SECONDS = EGRESS_AMBIGUOUS_COOLDOWN_SECONDS

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize EgressDirectionTracker."""
        self.hass = hass
        # Recent egress events: {camera_entity_id: list[datetime]}
        self._recent_egress_events: dict[str, list[datetime]] = {}
        # Recent interior-near-door events: {camera_entity_id: list[datetime]}
        self._recent_interior_events: dict[str, list[datetime]] = {}
        self._unsub: list = []
        self._egress_entities: list[str] = []
        self._interior_entities: list[str] = []

    async def async_init(self) -> None:
        """Subscribe to egress and near-door interior cameras."""
        from homeassistant.helpers.event import async_track_state_change_event

        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if not camera_manager:
            _LOGGER.debug("EgressDirectionTracker: no camera_manager, skipping subscription")
            return

        try:
            self._egress_entities = camera_manager._get_integration_camera_list(
                CONF_EGRESS_CAMERAS
            )
            self._interior_entities = camera_manager._get_interior_camera_entities()
        except Exception as e:
            _LOGGER.debug("EgressDirectionTracker: error reading camera lists: %s", e)
            return

        # Subscribe to egress cameras
        if self._egress_entities:
            for entity_id in set(self._egress_entities):
                unsub = async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._on_egress_state_change,
                )
                self._unsub.append(unsub)

        # Subscribe to interior cameras
        if self._interior_entities:
            for entity_id in set(self._interior_entities):
                unsub = async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._on_interior_state_change,
                )
                self._unsub.append(unsub)

        _LOGGER.info(
            "EgressDirectionTracker initialized: %d egress cameras, %d interior cameras",
            len(self._egress_entities),
            len(self._interior_entities),
        )

    @callback
    def _on_egress_state_change(self, event: Event) -> None:
        """Handle egress camera detection."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        state_val = new_state.state
        if state_val not in ("on", "true", "1") and not (
            state_val.isdigit() and int(state_val) > 0
        ):
            return

        entity_id = new_state.entity_id
        timestamp = dt_util.now()

        if entity_id not in self._recent_egress_events:
            self._recent_egress_events[entity_id] = []
        self._recent_egress_events[entity_id].append(timestamp)
        self._prune_event_list(self._recent_egress_events, entity_id)

        # Schedule resolution after ENTRY_WINDOW_SECONDS
        from homeassistant.helpers.event import async_call_later

        async def _delayed_resolve(now):
            await self._resolve_direction(entity_id, timestamp)

        async_call_later(self.hass, self.ENTRY_WINDOW_SECONDS, _delayed_resolve)

    @callback
    def _on_interior_state_change(self, event: Event) -> None:
        """Handle interior camera detection."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        state_val = new_state.state
        if state_val not in ("on", "true", "1") and not (
            state_val.isdigit() and int(state_val) > 0
        ):
            return

        entity_id = new_state.entity_id
        timestamp = dt_util.now()

        if entity_id not in self._recent_interior_events:
            self._recent_interior_events[entity_id] = []
        self._recent_interior_events[entity_id].append(timestamp)
        self._prune_event_list(self._recent_interior_events, entity_id)

    async def _resolve_direction(
        self, egress_camera_id: str, egress_timestamp: datetime
    ) -> None:
        """Determine entry, exit, or ambiguous and fire event on bus."""
        direction = "ambiguous"
        near_door_cameras = self._get_interior_cameras_near(egress_camera_id)

        for interior_cam in near_door_cameras:
            interior_times = self._recent_interior_events.get(interior_cam, [])
            for interior_time in interior_times:
                delta = (interior_time - egress_timestamp).total_seconds()

                if 0 <= delta <= self.ENTRY_WINDOW_SECONDS:
                    direction = "entry"
                    break
                if -self.EXIT_WINDOW_SECONDS <= delta < 0:
                    direction = "exit"
                    break

            if direction != "ambiguous":
                break

        confidence = 0.8 if direction != "ambiguous" else 0.3

        # Fire event on HA bus
        self.hass.bus.async_fire("ura_person_egress_event", {
            "direction": direction,
            "egress_camera": egress_camera_id,
            "timestamp": egress_timestamp.isoformat(),
            "person_id": None,
            "confidence": confidence,
        })

        _LOGGER.debug(
            "Egress direction resolved: camera=%s, direction=%s, confidence=%.2f",
            egress_camera_id, direction, confidence,
        )

        # Log to database if not ambiguous
        if direction != "ambiguous":
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database:
                try:
                    await database.log_entry_exit_event(
                        person_id=None,
                        event_type="egress",
                        direction=direction,
                        egress_camera=egress_camera_id,
                        confidence=confidence,
                    )
                except Exception as e:
                    _LOGGER.error("Failed to log entry/exit event: %s", e)

    def _get_interior_cameras_near(self, egress_camera_id: str) -> list[str]:
        """Return interior camera entity IDs physically adjacent to this egress camera.

        Without explicit adjacency mapping from the user, we return ALL interior
        cameras. This is conservative (may produce false matches) but ensures
        we don't miss direction determinations. In a well-configured home, only
        foyer/hallway cameras near doors will be in the interior camera list.
        """
        return list(self._interior_entities)

    def _prune_event_list(self, events_dict: dict, entity_id: str) -> None:
        """Prune event list to only keep recent events."""
        max_age = max(self.ENTRY_WINDOW_SECONDS, self.EXIT_WINDOW_SECONDS) + 30
        cutoff = dt_util.now() - timedelta(seconds=max_age)
        if entity_id in events_dict:
            events_dict[entity_id] = [
                ts for ts in events_dict[entity_id]
                if isinstance(ts, datetime) and ts >= cutoff
            ]

    async def async_teardown(self) -> None:
        """Unsubscribe all listeners."""
        for unsub in self._unsub:
            try:
                unsub()
            except Exception:
                pass
        self._unsub.clear()
        _LOGGER.debug("EgressDirectionTracker torn down")


def _parse_ts(ts) -> datetime:
    """Parse a timestamp to datetime, defaulting to epoch if invalid."""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        parsed = dt_util.parse_datetime(ts)
        if parsed:
            return parsed
    return datetime.fromtimestamp(0, tz=dt_util.DEFAULT_TIME_ZONE)
