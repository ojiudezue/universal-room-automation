"""Transit path validation for Universal Room Automation v3.5.2.

Validates room-to-room transitions using camera checkpoint data and
tracks egress camera direction (entry vs exit) via interior correlation.
"""
#
# Universal Room Automation v3.5.2
# Build: 2026-02-24
# File: transit_validator.py
#

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers import area_registry as ar_helper, entity_registry as er_helper
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
    CONF_TRANSIT_CHECKPOINT_AREAS,
    DEFAULT_TRANSIT_CHECKPOINT_AREAS,
    CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
    TRANSIT_PROTECT_SOURCED_ENABLED_DEFAULT,
    TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS,
    SIGNAL_URA_TRANSIT_CONFIG_CHANGED,
    FACE_MATCH_WINDOW_S,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_checkpoint_areas(
    areas_val: Any,
) -> tuple[str, ...] | None:
    """F7 fix (TRANSIT-1 fix-up): normalize the CONF_TRANSIT_CHECKPOINT_AREAS
    option value.

    Semantics:
      - ``None`` (absent)         -> return None (caller falls back to default)
      - ``()`` / ``[]`` (empty)   -> return ``()`` (KILL mode: operator meant
        "no checkpoint areas"; must NOT collapse to default)
      - list/tuple of strings     -> tuple(strings)
      - bare string (scalar)      -> single-element tuple (guards against
        ``tuple("foo")`` per-char expansion)
      - anything else             -> None (defensive; treat as absent)
    """
    if areas_val is None:
        return None
    if isinstance(areas_val, (list, tuple)):
        return tuple(str(a) for a in areas_val)
    if isinstance(areas_val, str):
        return (areas_val,)
    return None


def _protect_sourced_checkpoint_entities(
    hass: HomeAssistant,
) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """TRANSIT-1 (2026-08-07): enumerate Protect person cameras at checkpoint areas.

    Returns ``(entity_ids, by_area, entity_to_physical)``:
      - ``entity_ids``: flat list of ``binary_sensor.*`` entity_ids to
        subscribe (superset across every leg of every physical camera whose
        Protect device area_id is in ``CONF_TRANSIT_CHECKPOINT_AREAS``).
      - ``by_area``: diagnostic mapping ``area_id -> [entity_id, ...]`` for
        the ``checkpoint_cameras_by_area`` observability attribute.
      - ``entity_to_physical``: ``entity_id -> physical device_id`` map,
        used by F2 double-fire dedup so a single physical camera crossing
        does not fire twice (once for Protect leg, once for Frigate leg).

    Kill-switch: ``CONF_TRANSIT_PROTECT_SOURCED_ENABLED``. When False,
    returns ``([], {}, {})`` so callers UNION nothing — subscription set
    is byte-identical to the pre-cycle hand-list-only path. Empty
    checkpoint-areas tuple (F7 fix) is honored as "no Protect enumeration".

    Never raises; degrades to ``([], {}, {})``.
    """
    try:
        # Kill-switch: check integration config entry first.
        enabled = TRANSIT_PROTECT_SOURCED_ENABLED_DEFAULT
        checkpoint_areas: tuple[str, ...] = DEFAULT_TRANSIT_CHECKPOINT_AREAS
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                enabled = merged.get(
                    CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
                    TRANSIT_PROTECT_SOURCED_ENABLED_DEFAULT,
                )
                # F7 fix: `is not None` (empty tuple is a valid KILL setting;
                # falsy-check would silently expand to defaults). Also
                # normalizes scalar input to avoid `tuple("foo")` per-char.
                normalized = _normalize_checkpoint_areas(
                    merged.get(CONF_TRANSIT_CHECKPOINT_AREAS)
                )
                if normalized is not None:
                    checkpoint_areas = normalized
                break
        if not enabled:
            return [], {}, {}
        checkpoint_set = set(checkpoint_areas)
        # Empty checkpoint areas => nothing to enumerate (KILL mode).
        if not checkpoint_set:
            return [], {}, {}

        from homeassistant.helpers import (  # noqa: PLC0415
            device_registry as dr_helper,
        )
        from .camera_resolver import CameraResolver, PLATFORM_UNIFI  # noqa: PLC0415

        er = er_helper.async_get(hass)
        dr = dr_helper.async_get(hass)
        resolver = CameraResolver(er, dr, state_getter=hass.states.get)
        enumerated = resolver.enumerate_platform_cameras(PLATFORM_UNIFI, "person")
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "TRANSIT-1: Protect enumeration failed; falling back to hand-list only",
            exc_info=True,
        )
        return [], {}, {}

    by_area: dict[str, list[str]] = {}
    entity_ids: list[str] = []
    entity_to_physical: dict[str, str] = {}
    for cam in enumerated:
        if cam.area_id not in checkpoint_set:
            continue
        for eid in cam.legs:
            entity_ids.append(eid)
            by_area.setdefault(cam.area_id, []).append(eid)
            # F2 fix: every leg of the same physical camera keys to the
            # SAME device_id so `_on_camera_state_change` can dedup a
            # double-fire (Protect leg + Frigate leg both firing).
            entity_to_physical[eid] = cam.device_id
    return entity_ids, by_area, entity_to_physical


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
        # F5/F6 fix: subscriptions to state changes vs meta listeners
        # (registry-updated + config-change dispatcher) tracked separately
        # so `async_rebuild_subscriptions` can tear down/re-do the former
        # without dropping the latter.
        self._sub_unsub: list = []
        self._face_recognition_enabled = False
        # TRANSIT-1 diagnostic: area_id -> subscribed entity_ids from the
        # Protect enumeration path. Exposed as `checkpoint_cameras_by_area`
        # for observability (dashboard / diagnostics consumers).
        self.checkpoint_cameras_by_area: dict[str, list[str]] = {}
        # F1 fix: the set of Protect-sourced entity_ids that must be
        # UNIONed into `_get_shared_space_cameras()` — otherwise a
        # camera subscribed via Protect enumeration would have its
        # sightings recorded then filtered out at validate_transition.
        self._protect_entity_set: set[str] = set()
        # F2 fix: entity_id -> physical device_id map (Protect-sourced legs
        # share a device_id across their Protect + Frigate legs). Used to
        # collapse double-fires to ONE sighting per physical camera.
        self._entity_to_physical: dict[str, str] = {}
        # F2 fix: per-physical-camera last-sighting timestamp for dedup.
        self._last_physical_sighting: dict[str, datetime] = {}

    def build_diagnostic_attrs(self) -> dict[str, Any]:
        """F4 (2026-08-07 fix-up cycle-4): TRANSIT-DIAG-1 attr payload
        as a driveable method so behavioral tests can mutation-verify
        the population path without having to import sensor.py (which
        pulls the full package __init__ and 40+ HA imports).

        Returns a dict with two keys:
          ``checkpoint_cameras_by_area`` — dict[area, sorted list[eid]]
          ``protect_sourced_count`` — int (sum of camera counts)

        Sensor's PresenceDiagnosticSensor.extra_state_attributes calls
        this. Mutation drill (per F4 spec): forcing ``raw = {}`` in the
        production path — either here OR in sensor.py's reader — makes
        the behavioral test go RED.
        """
        raw = self.checkpoint_cameras_by_area or {}
        checkpoint_cameras_by_area = {
            a: sorted(list(eids)) for a, eids in raw.items()
        }
        protect_sourced_count = sum(
            len(v) for v in checkpoint_cameras_by_area.values()
        )
        return {
            "checkpoint_cameras_by_area": checkpoint_cameras_by_area,
            "protect_sourced_count": protect_sourced_count,
        }
        # F5 fix: debounce timer for registry-updated rebuilds.
        self._rebuild_timer_unsub = None
        # F6 fix: dispatcher listener for options-change signal (kept
        # across rebuilds so a re-init doesn't drop this hook).
        self._config_signal_unsub = None

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

        # Build camera-entity subscription set (rebuildable path).
        self._build_and_subscribe()

        # Schedule periodic cleanup of old sightings (every 30 minutes)
        unsub_cleanup = async_track_time_interval(
            self.hass,
            self._async_cleanup_sightings,
            timedelta(minutes=30),
        )
        self._unsub.append(unsub_cleanup)

        # F5 fix: self-heal on registry changes. If UniFi Protect wasn't
        # loaded at initial async_init (empty enumeration), a later Protect
        # entity registration triggers a debounced rebuild — no full restart
        # required. Filter by entity platform so unrelated churn is ignored.
        try:
            from homeassistant.helpers.entity_registry import (  # noqa: PLC0415
                EVENT_ENTITY_REGISTRY_UPDATED,
            )

            @callback
            def _on_registry_updated(evt: Event) -> None:
                data = evt.data or {}
                eid = data.get("entity_id")
                if not eid:
                    return
                try:
                    er = er_helper.async_get(self.hass)
                    entry = er.async_get(eid)
                except Exception:  # noqa: BLE001
                    return
                if entry is None:
                    return
                if getattr(entry, "platform", None) != "unifiprotect":
                    return
                self._schedule_rebuild()

            self._unsub.append(
                self.hass.bus.async_listen(
                    EVENT_ENTITY_REGISTRY_UPDATED, _on_registry_updated
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "TransitValidator: could not register EVENT_ENTITY_REGISTRY_UPDATED listener",
                exc_info=True,
            )

        # F6 fix: dispatcher signal so an options-change on the transit
        # knobs (kill switch, checkpoint areas) triggers a local re-init
        # without a parent-entry reload (RELOAD-WATCHDOG-HAZARD). The
        # options flow is expected to `async_dispatcher_send(hass,
        # SIGNAL_URA_TRANSIT_CONFIG_CHANGED)` on any transit-related change.
        # The re-init path exists regardless of wire-up; when wired it
        # avoids the parent-reload allowlist requirement.
        try:
            from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
                async_dispatcher_connect,
            )

            @callback
            def _on_config_changed(*_a) -> None:
                _LOGGER.info(
                    "TransitValidator: transit-config signal received; rebuilding subscriptions"
                )
                self._schedule_rebuild()

            self._config_signal_unsub = async_dispatcher_connect(
                self.hass, SIGNAL_URA_TRANSIT_CONFIG_CHANGED, _on_config_changed
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "TransitValidator: could not connect config-change dispatcher",
                exc_info=True,
            )

    def _build_and_subscribe(self) -> None:
        """(Re)build camera entity subscription set. F5/F6 idempotent path.

        Tears down any existing per-entity subscriptions in ``self._sub_unsub``
        and re-registers based on current census + Protect enumeration state.
        """
        # Tear down prior state-change subscriptions (but keep meta listeners).
        for unsub in self._sub_unsub:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._sub_unsub.clear()

        camera_entities: list[str] = []

        # TRANSIT-1: PREPEND Protect-sourced checkpoint enumeration in front
        # of the hand-list. UNIONed via the set() dedup at subscription time.
        # Kill-switch (CONF_TRANSIT_PROTECT_SOURCED_ENABLED=False) returns
        # ([], {}, {}) making this a byte-identical no-op vs legacy.
        protect_entities, by_area, entity_to_physical = (
            _protect_sourced_checkpoint_entities(self.hass)
        )
        if protect_entities:
            camera_entities.extend(protect_entities)
        self.checkpoint_cameras_by_area = by_area
        # F1 fix: expose the Protect-sourced entity set so
        # `_get_shared_space_cameras()` can UNION it with the legacy
        # hand-list — otherwise sightings from these entities are recorded
        # then filtered out at validate_transition (the cycle's value).
        self._protect_entity_set = set(protect_entities)
        # F2 fix: keep the entity->physical mapping fresh for dedup.
        self._entity_to_physical = dict(entity_to_physical)

        census = self.hass.data.get(DOMAIN, {}).get("census")
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")

        if census:
            try:
                interior_infos = census.get_transit_interior_entities()
                egress_infos = census.get_transit_egress_entities()
                camera_entities.extend(
                    info.person_binary_sensor for info in interior_infos
                    if info.person_binary_sensor
                )
                camera_entities.extend(
                    info.person_binary_sensor for info in egress_infos
                    if info.person_binary_sensor
                )
            except Exception as e:
                _LOGGER.debug("TransitValidator: census cross-platform failed: %s", e)
                census = None  # fall through to camera_manager

        if not census and camera_manager:
            try:
                interior = camera_manager._get_interior_camera_entities()
                camera_entities.extend(interior)
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

        subscribed = set(camera_entities)
        for entity_id in subscribed:
            unsub = async_track_state_change_event(
                self.hass,
                [entity_id],
                self._on_camera_state_change,
            )
            self._sub_unsub.append(unsub)

        _LOGGER.info(
            "TransitValidator subscriptions built: %d camera entities, "
            "face_recognition_enabled=%s, protect_sourced=%d",
            len(subscribed),
            self._face_recognition_enabled,
            len(self._protect_entity_set),
        )
        if self.checkpoint_cameras_by_area:
            _LOGGER.info(
                "TransitValidator Protect-sourced checkpoints: %s",
                {a: sorted(eids) for a, eids in self.checkpoint_cameras_by_area.items()},
            )

    @callback
    def _schedule_rebuild(self) -> None:
        """Debounce rebuild to coalesce churn (e.g. bulk registry ops)."""
        # Cancel prior pending rebuild if any.
        try:
            if self._rebuild_timer_unsub is not None:
                self._rebuild_timer_unsub()
        except Exception:  # noqa: BLE001
            pass
        self._rebuild_timer_unsub = None

        from homeassistant.helpers.event import async_call_later  # noqa: PLC0415

        @callback
        def _fire(_now) -> None:
            self._rebuild_timer_unsub = None
            try:
                self._build_and_subscribe()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("TransitValidator: rebuild failed", exc_info=True)

        try:
            self._rebuild_timer_unsub = async_call_later(self.hass, 5.0, _fire)
        except Exception:  # noqa: BLE001
            # If timer scheduling fails (test stubs), rebuild synchronously.
            _fire(None)

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
        legacy: list[str] = []
        if camera_manager:
            try:
                legacy = camera_manager._get_interior_camera_entities() or []
            except Exception as e:
                _LOGGER.debug("Could not get shared-space cameras: %s", e)
                legacy = []
        # F1 fix (TRANSIT-1 fix-up): UNION the Protect-sourced entity set.
        # Same kill-switch — when disabled, `_protect_entity_set` is empty
        # and this reduces to the legacy hand-list byte-identically. Without
        # this union, sightings recorded from Protect-sourced entities are
        # filtered out here and the entire cycle's value is discarded.
        if not self._protect_entity_set:
            return legacy
        # Dedup while preserving legacy order.
        seen: set[str] = set()
        out: list[str] = []
        for eid in legacy:
            if eid not in seen:
                seen.add(eid)
                out.append(eid)
        for eid in self._protect_entity_set:
            if eid not in seen:
                seen.add(eid)
                out.append(eid)
        return out

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

        # F2 fix (TRANSIT-1 fix-up): dedup double-fire by physical camera.
        # When both Protect and Frigate legs subscribe for the same physical
        # camera, a single crossing emits ≥2 state changes. Left unchecked,
        # `_correlate_sighting_to_transition` sees n_sightings >= n_transitions
        # from ONE camera's evidence -> wrong path_plausible/path_validated
        # feeds presence trust. Collapse to ONE logical sighting per physical
        # camera within TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS.
        physical = self._entity_to_physical.get(entity_id)
        if physical:
            last = self._last_physical_sighting.get(physical)
            if last is not None:
                age = (timestamp - last).total_seconds()
                if 0 <= age < TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS:
                    _LOGGER.debug(
                        "TransitValidator: F2 dedup — dropping sighting %s "
                        "(physical=%s, %.2fs after prior leg)",
                        entity_id, physical, age,
                    )
                    return
            self._last_physical_sighting[physical] = timestamp

        # Determine room from entity area_id
        room = None
        try:
            ent_reg = er_helper.async_get(self.hass)
            entity_entry = ent_reg.async_get(entity_id)
            if entity_entry and entity_entry.area_id:
                area_reg = ar_helper.async_get(self.hass)
                area = area_reg.async_get_area(entity_entry.area_id)
                if area:
                    room = area.name
        except Exception:
            _LOGGER.debug("Could not resolve room for camera entity %s", entity_id)

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
        for unsub in list(self._sub_unsub) + list(self._unsub):
            try:
                unsub()
            except Exception:
                pass
        self._sub_unsub.clear()
        self._unsub.clear()
        try:
            if self._rebuild_timer_unsub is not None:
                self._rebuild_timer_unsub()
        except Exception:  # noqa: BLE001
            pass
        self._rebuild_timer_unsub = None
        try:
            if self._config_signal_unsub is not None:
                self._config_signal_unsub()
        except Exception:  # noqa: BLE001
            pass
        self._config_signal_unsub = None
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
        self._egress_count_sensors: list[str] = []
        self._interior_entities: list[str] = []
        # Deduplication: stem -> last resolved timestamp
        self._last_resolved: dict[str, datetime] = {}

    async def async_init(self) -> None:
        """Subscribe to egress and near-door interior cameras.

        Uses cross-platform census helpers when available (resolves sensors
        across Frigate + UniFi for the same physical camera). Falls back to
        single-platform camera_manager resolution.
        """
        from homeassistant.helpers.event import async_track_state_change_event

        census = self.hass.data.get(DOMAIN, {}).get("census")
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")

        if census:
            # Cross-platform resolution via PersonCensus
            try:
                egress_infos = census.get_transit_egress_entities()
                interior_infos = census.get_transit_interior_entities()

                self._egress_entities = [
                    info.person_binary_sensor for info in egress_infos
                    if info.person_binary_sensor
                ]
                self._egress_count_sensors = [
                    info.person_count_sensor for info in egress_infos
                    if info.person_count_sensor
                ]
                self._interior_entities = [
                    info.person_binary_sensor for info in interior_infos
                    if info.person_binary_sensor
                ]
            except Exception as e:
                _LOGGER.debug("EgressDirectionTracker: census cross-platform failed: %s", e)
                census = None  # fall through to camera_manager

        if not census and camera_manager:
            # Fallback: single-platform resolution
            try:
                self._egress_entities = camera_manager._get_integration_camera_list(
                    CONF_EGRESS_CAMERAS
                )
                self._interior_entities = camera_manager._get_interior_camera_entities()
            except Exception as e:
                _LOGGER.debug("EgressDirectionTracker: error reading camera lists: %s", e)
                return
        elif not census and not camera_manager:
            _LOGGER.debug("EgressDirectionTracker: no camera_manager or census, skipping subscription")
            return

        # TRANSIT-1: PREPEND Protect-sourced interior enumeration in front of
        # the hand-list-derived _interior_entities. Same kill-switch as
        # TransitValidator; UNIONed with the existing set. `_get_interior_
        # cameras_near` returns `_interior_entities`, so appending here is
        # sufficient — subscription dedup happens via `set()` below.
        protect_entities, _by_area, _e2p = _protect_sourced_checkpoint_entities(self.hass)
        if protect_entities:
            # F8 fix (TRANSIT-1 fix-up): dedup + idempotent. Rebuilding via
            # re-init (F6 config change) must not accrete duplicates in
            # `_interior_entities`, and `_get_interior_cameras_near` returns
            # `list(self._interior_entities)` verbatim so dupes would leak.
            self._interior_entities = list(dict.fromkeys(
                list(self._interior_entities) + list(protect_entities)
            ))

        # Subscribe to egress binary sensors
        if self._egress_entities:
            for entity_id in set(self._egress_entities):
                unsub = async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._on_egress_state_change,
                )
                self._unsub.append(unsub)

        # Subscribe to egress person_count sensors (0→N transitions)
        if self._egress_count_sensors:
            for entity_id in set(self._egress_count_sensors):
                unsub = async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._on_egress_count_change,
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
            "EgressDirectionTracker initialized: %d egress sensors, %d egress count sensors, %d interior sensors",
            len(self._egress_entities),
            len(self._egress_count_sensors),
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
    def _on_egress_count_change(self, event: Event) -> None:
        """Handle person_count sensor transitions from 0 → N (N > 0).

        Frigate sensor.*_person_count provides high-confidence entry detection
        when it goes from 0 to a positive value.
        """
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not new_state or not old_state:
            return

        # Only trigger on 0 → N transitions
        try:
            old_val = int(old_state.state) if old_state.state.isdigit() else -1
            new_val = int(new_state.state) if new_state.state.isdigit() else 0
        except (ValueError, AttributeError):
            return

        if old_val != 0 or new_val <= 0:
            return

        entity_id = new_state.entity_id
        timestamp = dt_util.now()

        # Record as egress event using the stem to correlate with binary sensors
        if entity_id not in self._recent_egress_events:
            self._recent_egress_events[entity_id] = []
        self._recent_egress_events[entity_id].append(timestamp)
        self._prune_event_list(self._recent_egress_events, entity_id)

        # Schedule delayed resolution
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

    @staticmethod
    def _extract_camera_stem(entity_id: str) -> str | None:
        """Extract camera name stem from a sensor entity_id for deduplication."""
        from .camera_census import CameraIntegrationManager
        return CameraIntegrationManager._extract_camera_stem(entity_id)

    def _resolve_egress_face_identity(
        self, egress_camera_id: str, timestamp: datetime,
    ) -> str | None:
        """EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1: resolve the freshest
        recognized-face NAME on the egress camera's stem within
        ``FACE_MATCH_WINDOW_S`` of ``timestamp``. Returns the name (as
        published by the Frigate ``_last_recognized_face`` sensor — e.g.
        ``"Oji"``) or ``None``.

        Uses the REUSED census face readers so a single face-resolver
        implementation stays authoritative:
          - ``camera_census._resolve_face_entity_id`` for `_2`-suffix
            tolerant entity_id lookup.
          - Direct state read on the resolved entity_id filtered by stem
            (the census's `_get_face_recognized_persons_fresh` scans all
            cameras; here we want just this one crossing's stem).

        Mirrors the fail-open ``person.<slug> == not_home`` veto that
        ``camera_census._get_face_recognized_person_names`` applies at
        `:3346-3366` (plan-review C-LOW-2): if the person tracker says
        not_home, drop the recognition even if the face sensor is
        currently reporting the name (stale-face latch guard). Fail-open
        on missing/unknown/unavailable person state.

        Returns ``None`` on any error — I3: no identity without evidence.
        """
        if not egress_camera_id:
            return None
        stem = self._extract_camera_stem(egress_camera_id)
        if not stem:
            return None
        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census is None:
            return None
        # Kill-switch (2026-08-18): dormant by default. When False the
        # resolver returns None immediately so no identity is stamped and
        # no census register call fires downstream.
        try:
            if not census._is_egress_identity_enabled():
                return None
        except Exception:  # noqa: BLE001 — defensive; unknown census shape
            return None
        try:
            face_sensor_id = census._resolve_face_entity_id(stem)
        except Exception:  # noqa: BLE001 — defensive; helper is fail-CLOSED
            _LOGGER.debug(
                "egress-face: _resolve_face_entity_id raised for stem=%s",
                stem, exc_info=True,
            )
            return None
        if face_sensor_id is None:
            return None
        try:
            state = self.hass.states.get(face_sensor_id)
        except Exception:  # noqa: BLE001
            return None
        if state is None:
            return None
        val = state.state.strip() if isinstance(state.state, str) else ""
        if val.lower() in ("unavailable", "unknown", "", "none", "no_match"):
            return None
        # Freshness: state.last_changed must be within FACE_MATCH_WINDOW_S
        # of the crossing timestamp (I3).
        last_changed = getattr(state, "last_changed", None)
        if last_changed is None:
            return None
        try:
            if last_changed.tzinfo is None:
                last_changed = last_changed.replace(tzinfo=dt_util.UTC)
            # A-LOW-1 / C-LOW-3 (2026-08-18): sign-symmetric with the
            # census's `_get_egress_face_ids_fresh` — `age < 0` (face
            # recognized AFTER the crossing time; clock skew / future
            # timestamp) is treated as stale, not "fresh in the future".
            age = (timestamp - last_changed).total_seconds()
        except (TypeError, AttributeError):
            return None
        if age < 0 or age > FACE_MATCH_WINDOW_S:
            _LOGGER.debug(
                "egress-face %s dropped: age=%.1fs outside [0, %ds]",
                val, age, FACE_MATCH_WINDOW_S,
            )
            return None
        # A-HIGH-1 fix: canonicalize to the URA person-slug namespace via
        # the census (uses tracked_persons config). Same namespace as
        # `_get_face_recognized_person_names`, `ble_persons`,
        # `census.identified_persons`, the DB `person_id` column, and
        # `person.<slug>` — so veto, DB write, census union, and any
        # downstream joins all agree.
        canonical = census._canonical_person_slug(val)
        if not canonical:
            return None
        # Fail-open person-tracker veto (mirrors camera_census.py:3456).
        # Uses the CANONICAL URA slug so it queries the real HA entity
        # (`person.oji_udezue`), not a first-name slug that never exists.
        person_entity_id = f"person.{canonical}"
        try:
            person_state = self.hass.states.get(person_entity_id)
        except Exception:  # noqa: BLE001
            person_state = None
        if person_state is not None and person_state.state == "not_home":
            _LOGGER.debug(
                "egress-face %s dropped: %s=not_home "
                "(stale-face veto, mirrors census)",
                canonical, person_entity_id,
            )
            return None
        return canonical

    async def _resolve_direction(
        self, egress_camera_id: str, egress_timestamp: datetime
    ) -> None:
        """Determine entry, exit, or ambiguous and fire event on bus.

        Includes deduplication: when both Frigate and UniFi sensors fire for
        the same physical camera within 5 seconds, only resolve once.
        """
        # Deduplication by camera stem
        stem = self._extract_camera_stem(egress_camera_id)
        if stem:
            last = self._last_resolved.get(stem)
            if last and (egress_timestamp - last).total_seconds() < 5.0:
                _LOGGER.debug(
                    "Egress dedup: skipping %s (stem=%s resolved %.1fs ago)",
                    egress_camera_id, stem, (egress_timestamp - last).total_seconds(),
                )
                return
            self._last_resolved[stem] = egress_timestamp

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

        # Multi-platform confidence boost: count how many platform sensors
        # fired for the same stem within 10 seconds
        platforms_fired = self._count_platforms_fired(stem, egress_timestamp) if stem else 1
        if direction != "ambiguous":
            confidence = 0.9 if platforms_fired >= 2 else 0.8
        else:
            confidence = 0.4 if platforms_fired >= 2 else 0.3

        # EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1: stamp person_id from the
        # egress-camera's face sensor at emit time. None when no fresh
        # face within FACE_MATCH_WINDOW_S (I3: no identity without
        # evidence). Single resolution call reused for the bus event
        # AND the DB row so both sites always agree.
        person_id = self._resolve_egress_face_identity(
            egress_camera_id, egress_timestamp,
        )

        # Fire event on HA bus
        self.hass.bus.async_fire("ura_person_egress_event", {
            "direction": direction,
            "egress_camera": egress_camera_id,
            "timestamp": egress_timestamp.isoformat(),
            "person_id": person_id,
            "confidence": confidence,
        })

        _LOGGER.debug(
            "Egress direction resolved: camera=%s, direction=%s, "
            "confidence=%.2f, person_id=%s",
            egress_camera_id, direction, confidence, person_id,
        )

        # Feed the census union so the next census tick fuses this
        # identity with face_ids/ble_ids (I1: cardinality of the union,
        # not sum). Bounded by EGRESS_FACE_UNION_TTL_S on the census
        # side; canonicalization to URA person-slug happens there.
        #
        # B-CRIT-1 / B-HIGH-1 (2026-08-18) direction gating:
        #   - direction == "entry"    -> register (person came IN)
        #   - direction == "exit"     -> EVICT any prior registration for
        #                                this identity (walked-in-then-out
        #                                within the TTL) — do NOT register.
        #   - direction == "ambiguous"-> neither register nor evict (match
        #                                the DB-write gate at :1233; low-
        #                                confidence crossings must not
        #                                mutate the household census).
        # Registering on exit would inject a phantom identified person
        # into the census union for EGRESS_FACE_UNION_TTL_S after every
        # legitimate departure — surfacing as a phantom guest via
        # `identified_count`/`total_persons` → `_get_guest_count`.
        if person_id and direction in ("entry", "exit"):
            census = self.hass.data.get(DOMAIN, {}).get("census")
            if census is not None:
                try:
                    if direction == "entry":
                        census.register_egress_face(person_id, egress_timestamp)
                    else:  # direction == "exit"
                        census.evict_egress_face(person_id)
                except Exception:  # noqa: BLE001 — census register is
                    # best-effort; do not fail the egress emit path.
                    _LOGGER.debug(
                        "egress-face census %s failed for %s",
                        direction, person_id, exc_info=True,
                    )

        # Log to database if not ambiguous
        if direction != "ambiguous":
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database:
                try:
                    await database.log_entry_exit_event(
                        person_id=person_id,
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

    def _count_platforms_fired(self, stem: str, timestamp: datetime) -> int:
        """Count how many distinct platforms fired for the same camera stem within 10s.

        Uses entity_id suffix as platform heuristic:
          _person_occupancy / _person_count → frigate
          _person_detected → unifi
        """
        fired_platforms: set[str] = set()

        for entity_id, times in self._recent_egress_events.items():
            entity_stem = self._extract_camera_stem(entity_id)
            if entity_stem != stem:
                continue
            for t in times:
                if abs((t - timestamp).total_seconds()) <= 10:
                    # Determine platform from suffix
                    if "_person_occupancy" in entity_id or "_person_count" in entity_id:
                        fired_platforms.add("frigate")
                    elif "_person_detected" in entity_id:
                        fired_platforms.add("unifi")
                    else:
                        fired_platforms.add(entity_id)  # fallback: treat as unique
                    break

        return len(fired_platforms)

    def _prune_event_list(self, events_dict: dict, entity_id: str) -> None:
        """Prune event list to only keep recent events."""
        max_age = max(self.ENTRY_WINDOW_SECONDS, self.EXIT_WINDOW_SECONDS) + 30
        cutoff = dt_util.now() - timedelta(seconds=max_age)
        if entity_id in events_dict:
            events_dict[entity_id] = [
                ts for ts in events_dict[entity_id]
                if isinstance(ts, datetime) and ts >= cutoff
            ]

        # Also prune _last_resolved entries older than 60 seconds
        dedup_cutoff = dt_util.now() - timedelta(seconds=60)
        stale_stems = [
            stem for stem, ts in self._last_resolved.items()
            if ts < dedup_cutoff
        ]
        for stem in stale_stems:
            del self._last_resolved[stem]

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
