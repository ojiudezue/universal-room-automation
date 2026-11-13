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
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

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
    DOOR_STEM_DEDUP_S,
    CONF_DOOR_GROUPS,
    CONF_DOOR_INTERIOR_NEIGHBOURS,
    CONF_TRANSIT_CHECKPOINT_AREAS,
    DEFAULT_TRANSIT_CHECKPOINT_AREAS,
    CONF_TRANSIT_PROTECT_SOURCED_ENABLED,
    TRANSIT_PROTECT_SOURCED_ENABLED_DEFAULT,
    TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS,
    SIGNAL_URA_TRANSIT_CONFIG_CHANGED,
    SIGNAL_URA_FACE_RECOGNITION_CHANGED,
    DEFAULT_FACE_RECOGNITION_ENABLED,
    FACE_MATCH_WINDOW_S,
    FACE_MATCH_EXIT_WINDOW_BEFORE_S,
    FACE_MATCH_EXIT_WINDOW_AFTER_S,
    FACE_MATCH_ENTRY_WINDOW_BEFORE_S,
    FACE_MATCH_ENTRY_WINDOW_AFTER_S,
    FACE_MATCH_ABSTAIN_MARGIN_S,
    FACE_MATCH_MIN_CONFIDENCE,
    FACE_MATCH_CORRELATED_BOOST,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CENSUS_AGREEMENT_BOTH,
    CENSUS_AGREEMENT_SINGLE,
    CENSUS_AGREEMENT_DISAGREE,
    CENSUS_AGREEMENT_DISABLED,
    CENSUS_AGREEMENT_TWO_ENGINES,
    BLE_TRANSITION_CONFIDENCE,
    BLE_TRANSITION_ONLY_CONFIDENCE,
    BLE_PLUS_FACE_CORROBORATED_CONFIDENCE,
    FACE_PRODUCER_STALE_TTL_S,
    CONF_EGRESS_IDENTITY_FAILSAFE_STRICT,
    DEFAULT_EGRESS_IDENTITY_FAILSAFE_STRICT,
    IDENTITY_PROVENANCE_BLE,
    IDENTITY_PROVENANCE_BLE_FACE,
    IDENTITY_PROVENANCE_FACE,
    EGRESS_OUTCOME_LOG_PERSIST,
    EGRESS_OUTCOME_EPISODE_TYPE,
    EGRESS_OUTCOME_LOG_TEARDOWN_TIMEOUT_S,
    CONF_PERIMETER_CAMERAS,
    DEFAULT_INTERIOR_PATH_FILE,
    EGRESS_PATH_BUFFER_S,
    EGRESS_PATH_HOP_DEFAULT_WINDOW_S,
    INTERIOR_PATH_DETACHED_DOORS,
    INTERIOR_PATH_MAP_FALLBACK,
    INTERIOR_PATH_MAP_REVALIDATE_DEBOUNCE_S,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EgressResolution:
    """FACE-ARRIVAL-REBUILD-1 D8a (plan rev 11 §9 D8a): the ONE return channel
    of an egress identity resolution, built fresh on EVERY return path of
    ``EgressDirectionTracker._resolve_egress_face_identity_ex``.

    ``outcome`` is the same label the census outcome deque records (plus
    ``census_unavailable`` / ``resolver_error`` for the two paths that record
    none). ``slug`` is the person considered (the vetoed slug on a veto; None
    when there is none). ``tier`` / ``synthetic`` come from the pure
    ``egress_identity_tier`` helper on the face paths. ``provenance`` is
    ``face`` / ``ble`` / ``ble+face`` on an attach, else None. No decision
    reads this record; the outcome logger persists it.
    """

    outcome: str
    direction: str
    agreement: str
    slug: str | None = None
    identity_confidence: float | None = None
    tier: float | None = None
    synthetic: bool | None = None
    person_state: str | None = None
    provenance: str | None = None


def egress_identity_tier(in_window_legs) -> tuple[float, bool]:
    """FACE-ARRIVAL-REBUILD-1 D8a: PURE confidence-tier arithmetic of a
    single-slug face leg set (no stash, no ledger append, no I/O).

    Returns ``(tier, synthetic)``:
      * ``CONFIDENCE_HIGH`` when two legs resolve to DIFFERENT physical
        cameras (distinct ``base_stem``); ``synthetic`` is True when that 0.9
        holds only with a synthetic (MQTT latch) leg in the pair;
      * ``FACE_MATCH_CORRELATED_BOOST`` for >= 2 legs on one camera;
      * ``CONFIDENCE_MEDIUM`` for one leg.
    Module-level on purpose (plan rev 11 M2): tests call the resolver unbound
    with a bare ``SimpleNamespace`` self.
    """
    legs = list(in_window_legs)
    n = len(legs)

    def _independent(h_i, h_j) -> bool:
        return h_i.base_stem != h_j.base_stem

    has_independent_pair = any(
        _independent(legs[i], legs[j])
        for i in range(n) for j in range(i + 1, n)
    )
    if has_independent_pair:
        live = [h for h in legs if not getattr(h, "synthetic", False)]
        synthetic = not any(
            _independent(live[i], live[j])
            for i in range(len(live)) for j in range(i + 1, len(live))
        )
        return float(CONFIDENCE_HIGH), synthetic
    if n >= 2:
        return float(FACE_MATCH_CORRELATED_BOOST), False
    return float(CONFIDENCE_MEDIUM), False


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
        # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18): discharge
        # signal for CONF_FACE_RECOGNITION_ENABLED (the flag is cached
        # at boot at :259; the switch/options-flow update is now
        # reload-suppressed so we MUST refresh via this signal).
        self._face_recog_signal_unsub = None

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
                self._face_recognition_enabled = merged.get(
                    CONF_FACE_RECOGNITION_ENABLED,
                    DEFAULT_FACE_RECOGNITION_ENABLED,
                )
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

        # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18): subscribe to
        # SIGNAL_URA_FACE_RECOGNITION_CHANGED so a switch/options-flow
        # toggle of CONF_FACE_RECOGNITION_ENABLED refreshes our cached
        # flag WITHOUT a parent-entry reload. The signal is fired by
        # both the switch write and the reload-suppress branch of
        # `_async_update_listener` (idempotent — both paths re-read the
        # same persisted value).
        try:
            from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
                async_dispatcher_connect,
            )

            @callback
            def _on_face_recognition_changed(*_a) -> None:
                previous = self._face_recognition_enabled
                for cfg in self.hass.config_entries.async_entries(DOMAIN):
                    if cfg.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                        try:
                            merged = {**cfg.data, **cfg.options}
                            self._face_recognition_enabled = merged.get(
                                CONF_FACE_RECOGNITION_ENABLED,
                                DEFAULT_FACE_RECOGNITION_ENABLED,
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "TransitValidator: face-recog re-read failed",
                                exc_info=True,
                            )
                        break
                if previous != self._face_recognition_enabled:
                    _LOGGER.info(
                        "TransitValidator: face-recognition-enabled %s → %s "
                        "(via SIGNAL_URA_FACE_RECOGNITION_CHANGED)",
                        previous, self._face_recognition_enabled,
                    )

            self._face_recog_signal_unsub = async_dispatcher_connect(
                self.hass,
                SIGNAL_URA_FACE_RECOGNITION_CHANGED,
                _on_face_recognition_changed,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "TransitValidator: could not connect face-recognition dispatcher",
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
        # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18)
        try:
            if self._face_recog_signal_unsub is not None:
                self._face_recog_signal_unsub()
        except Exception:  # noqa: BLE001
            pass
        self._face_recog_signal_unsub = None
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
        # PLANNING_census_inputs_first D1 (R2.2 item 5 / R4.6):
        # per-stem door-group map and per-group interior-neighbours map,
        # populated from CONF_DOOR_GROUPS / CONF_DOOR_INTERIOR_NEIGHBOURS
        # at async_init (unset → today's per-stem / all-interior behaviour).
        self._door_group_by_stem: dict[str, str] = {}
        self._interior_neighbours_by_group: dict[str, list[str]] = {}
        # PLANNING_census_inputs_first R3.6 / R4.5 — peak_person_count
        # value buffer keyed by camera stem. Each entry is a bounded
        # deque of (timestamp, int) samples populated by a lightweight
        # state_changed listener on each CameraInfo.person_count_sensor.
        self._peak_count_buffer: dict[str, deque[tuple[datetime, int]]] = {}
        self._peak_count_unsubs: list[Callable[[], None]] = []
        # Stem -> entity_id of its person_count sensor (reverse lookup
        # for the buffer listener; keys never string-built — resolved
        # from `info.person_count_sensor` only).
        self._count_sensor_to_stem: dict[str, str] = {}
        # FACE-ARRIVAL-REBUILD-1 D8a: in-flight outcome-log writes (precedent
        # ExteriorTrackLinker._episode_tasks) and the teardown latch that
        # stops a `_delayed_resolve` already scheduled from writing after the
        # teardown gather (the DB closes after the tracker teardown).
        self._outcome_log_tasks: set = set()
        self._torn_down: bool = False
        # FACE-ARRIVAL-REBUILD-1 D7 / INTERIOR-PATH-MAP-1: the interior path
        # map (Phase 1: loaded, validated, exposed; NO runtime reader). Owner
        # is this tracker (the Phase 2 scorer's caller). Provenance reads
        # `pending` until the first load (EVENT_HOMEASSISTANT_STARTED, or
        # immediately on an entry reload while HA runs).
        self.path_map = None
        self.path_map_source: str = "pending"
        self.path_map_validation: str = "pending"
        self.path_map_sha256: str | None = None
        self._path_map_loaded_once: bool = False
        self._path_map_from_file: bool = False
        self._path_map_unsubs: list = []
        self._path_map_reval_unsub = None
        self._path_map_tasks: set = set()

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

        # PLANNING_census_inputs_first D1 (R2.2 / R4.5 / R4.6):
        # Read door-group + neighbours maps from the integration config
        # entry (unset → maps stay empty → today's behaviour). Build
        # `_count_sensor_to_stem` reverse-lookup from census CameraInfo
        # (NEVER string-built — reuse `info.person_count_sensor`), then
        # register the peak-count buffer listeners.
        self._load_door_config()
        if census:
            try:
                for info in census.get_transit_egress_entities():
                    pcs = getattr(info, "person_count_sensor", None)
                    pbs = getattr(info, "person_binary_sensor", None)
                    stem = None
                    if pcs:
                        from .camera_census import CameraIntegrationManager
                        stem = CameraIntegrationManager._extract_camera_stem(pcs)
                    if not stem and pbs:
                        from .camera_census import CameraIntegrationManager
                        stem = CameraIntegrationManager._extract_camera_stem(pbs)
                    if pcs and stem:
                        self._count_sensor_to_stem[pcs] = stem
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug(
                    "EgressDirectionTracker: peak-count map build failed: %s",
                    e,
                )
        if self._count_sensor_to_stem:
            try:
                from homeassistant.helpers.event import (
                    async_track_state_change_event,
                )
                for entity_id in set(self._count_sensor_to_stem.keys()):
                    unsub = async_track_state_change_event(
                        self.hass,
                        [entity_id],
                        self._on_peak_count_change,
                    )
                    self._peak_count_unsubs.append(unsub)
                    self._unsub.append(unsub)
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug(
                    "EgressDirectionTracker: peak-count subscribe failed: %s",
                    e,
                )

        _LOGGER.info(
            "EgressDirectionTracker initialized: %d egress sensors, %d egress count sensors, %d interior sensors, %d door-groups, %d neighbour-groups",
            len(self._egress_entities),
            len(self._egress_count_sensors),
            len(self._interior_entities),
            len(self._door_group_by_stem),
            len(self._interior_neighbours_by_group),
        )

    def _load_door_config(self) -> None:
        """Load CONF_DOOR_GROUPS / CONF_DOOR_INTERIOR_NEIGHBOURS from the
        integration-level config entry. Unset → maps stay empty →
        downstream behaviour is byte-identical to today."""
        self._door_group_by_stem = {}
        self._interior_neighbours_by_group = {}
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_INTEGRATION:
                    continue
                merged = {**entry.data, **entry.options}
                groups_raw = merged.get(CONF_DOOR_GROUPS) or {}
                nbrs_raw = merged.get(CONF_DOOR_INTERIOR_NEIGHBOURS) or {}
                if isinstance(groups_raw, dict):
                    for k, v in groups_raw.items():
                        if isinstance(k, str) and isinstance(v, str) and v:
                            self._door_group_by_stem[k] = v
                if isinstance(nbrs_raw, dict):
                    for group, cams in nbrs_raw.items():
                        if not isinstance(group, str):
                            continue
                        if isinstance(cams, (list, tuple)):
                            self._interior_neighbours_by_group[group] = [
                                str(c) for c in cams if isinstance(c, str)
                            ]
                break
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "EgressDirectionTracker: door-config read failed: %s", e,
            )

    @callback
    def _on_peak_count_change(self, event: Event) -> None:
        """Append person_count samples to the per-stem value buffer.

        R4.5: the 0→N edge path can't be `max()`ed at resolve time because
        the handler only re-fires on 0→N edges; buffering every int-valued
        state_changed on the count sensor gives the sampler a real
        time-series within the dedup+resolve-delay horizon.
        """
        new_state = event.data.get("new_state")
        if not new_state:
            return
        entity_id = new_state.entity_id
        stem = self._count_sensor_to_stem.get(entity_id)
        if not stem:
            return
        try:
            val = int(new_state.state)
        except (ValueError, TypeError, AttributeError):
            return
        if val < 0:
            return
        now = dt_util.now()
        buf = self._peak_count_buffer.get(stem)
        if buf is None:
            buf = deque(maxlen=64)
            self._peak_count_buffer[stem] = buf
        buf.append((now, val))
        # Prune anything older than the dedup+resolve-delay horizon
        # (same bound as the `_last_resolved` prune in `_prune_event_list`).
        horizon = max(60, DOOR_STEM_DEDUP_S + self.ENTRY_WINDOW_SECONDS)
        cutoff = now - timedelta(seconds=horizon)
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def _door_group_for_stem(self, stem: str | None) -> str | None:
        """Return the configured door-group for `stem`, or None (unset →
        per-stem dedup → today's behaviour)."""
        if not stem:
            return None
        return self._door_group_by_stem.get(stem)

    def _sample_peak_person_count(
        self,
        stem: str | None,
        egress_timestamp: datetime,
    ) -> int | None:
        """R3.6 / R4.5 sampler. Window:
        [egress_timestamp - DOOR_STEM_DEDUP_S, egress_timestamp + ENTRY_WINDOW_SECONDS].
        For a configured door_group, MAX across the group's cameras
        (not sum — two cameras seeing one 4-person arrival report 4,
        not 8). Returns None when no sample lies in the window."""
        if not stem:
            return None
        lo = egress_timestamp - timedelta(seconds=DOOR_STEM_DEDUP_S)
        hi = egress_timestamp + timedelta(seconds=self.ENTRY_WINDOW_SECONDS)
        group = self._door_group_for_stem(stem)
        if group:
            stems = [
                s for s, g in self._door_group_by_stem.items() if g == group
            ]
            if stem not in stems:
                stems.append(stem)
        else:
            stems = [stem]
        best: int | None = None
        for s in stems:
            buf = self._peak_count_buffer.get(s, ())
            # Review LOW: seed with the last sample STRICTLY BEFORE
            # window start, provided it isn't stale — the count sensor
            # is step-and-hold, so a value that was already true at the
            # egress moment but didn't re-fire inside the window still
            # represents the real multiplicity. Bound the seed horizon
            # to DOOR_STEM_DEDUP_S before `lo` so ancient samples (an
            # earlier household member's long-gone appearance) don't
            # leak forward.
            seed_cutoff = lo - timedelta(seconds=DOOR_STEM_DEDUP_S)
            seed: int | None = None
            for ts, v in buf:  # type: ignore[arg-type]
                if ts < lo:
                    if ts >= seed_cutoff:
                        seed = v
                else:
                    break
            if seed is not None and (best is None or seed > best):
                best = seed
            for ts, v in buf:  # type: ignore[arg-type]
                if lo <= ts <= hi:
                    if best is None or v > best:
                        best = v
        return best

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

        # UNLOAD-SYMMETRY-TASK-HYGIENE-1 fix-up (2026-09-16): per-detection
        # hot path — use the self-removing idiom (mirrors
        # ``hvac.py:1351 _unsub_kick``) so the retention list stays bounded
        # across process lifetime while still being cancellable on
        # ``async_teardown``.
        _captured_unsub = None

        async def _delayed_resolve(now):
            if _captured_unsub is not None:
                try:
                    self._unsub.remove(_captured_unsub)
                except ValueError:
                    pass  # Already drained by teardown — benign
            await self._resolve_direction(entity_id, timestamp)

        _captured_unsub = async_call_later(
            self.hass, self.ENTRY_WINDOW_SECONDS, _delayed_resolve,
        )
        self._unsub.append(_captured_unsub)

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

        # UNLOAD-SYMMETRY-TASK-HYGIENE-1 fix-up (2026-09-16): per-detection
        # hot path — self-removing idiom keeps ``self._unsub`` bounded.
        _captured_unsub = None

        async def _delayed_resolve(now):
            if _captured_unsub is not None:
                try:
                    self._unsub.remove(_captured_unsub)
                except ValueError:
                    pass  # Already drained by teardown — benign
            await self._resolve_direction(entity_id, timestamp)

        _captured_unsub = async_call_later(
            self.hass, self.ENTRY_WINDOW_SECONDS, _delayed_resolve,
        )
        self._unsub.append(_captured_unsub)

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
        self,
        egress_camera_id: str,
        timestamp: datetime,
        direction: str,
    ) -> tuple[str | None, float | None, str]:
        """3-tuple wrapper kept for its existing callers (plan rev 11 M2).

        Production calls ``_resolve_egress_face_identity_ex`` (one site,
        ``_resolve_direction``); this returns its first three values.
        """
        pid, conf, agree, _resolution = (
            EgressDirectionTracker._resolve_egress_face_identity_ex(
                self, egress_camera_id, timestamp, direction,
            )
        )
        return pid, conf, agree

    def _resolve_egress_face_identity_ex(
        self,
        egress_camera_id: str,
        timestamp: datetime,
        direction: str,
    ) -> tuple[str | None, float | None, str, EgressResolution]:
        """EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28) D2b: corroborated
        identity from the evaluation leg-set. Returns
        ``(canonical_slug_or_None, identity_confidence_or_None, agreement_class)``.

        The resolver is the SOLE observability author for the D3 surface:
        appends exactly ONE outcome to ``census._egress_identity_outcomes``
        per call, updates ``_egress_identity_agreement_class_last``, and
        (only on the attached path) populates ``_egress_identity_last_attach``
        + ``_egress_identity_boost_events``. This keeps
        ``contributor_engines`` / ``signed_lag_delta_seconds`` derived from
        the SAME in-window leg-set that made the decision (fix MED-5) and
        makes the outcome labels the authoritative rate producer (fix
        MED-3/MED-4/A5).

        Outcome vocabulary (single owner — this method):
          - ``"disabled"``            — kill-switch OFF, excluded from rates.
          - ``"direction_ambiguous"`` — direction=="ambiguous"; excluded
                                        from rates (never reads a leg).
          - ``"no_leg"``              — no in-window named leg; in denom.
          - ``"abstain"``             — DISAGREE with min-pair separation
                                        ``<= FACE_MATCH_ABSTAIN_MARGIN_S``.
          - ``"ambiguous"``           — DISAGREE with min-pair separation
                                        strictly greater than the margin.
          - ``"vetoed"``              — single-slug hit killed by the
                                        ``person.<slug>=not_home`` veto.
          - ``"attached"``            — successful attach.
        """
        # v5.108.1 review B-M1: entry-reset per call. Set True only when the
        # CONFIDENCE_HIGH result has no independent pair of LIVE (non-
        # synthetic) legs; the egress fire site reads it synchronously (no
        # await in between) into `identity_synthetic_corroborated`.
        self._last_identity_synthetic_corroborated = False
        census = self.hass.data.get(DOMAIN, {}).get("census")

        # FACE-ARRIVAL-REBUILD-1 D8a: every return builds a FRESH
        # EgressResolution (INV-LOG: one record per call, every path).
        def _ret(
            pid, conf, agree, outcome, *, slug=None, tier=None,
            synthetic=None, person_state=None, provenance=None,
        ):
            return (
                pid, conf, agree,
                EgressResolution(
                    outcome=outcome,
                    direction=direction,
                    agreement=agree,
                    slug=slug,
                    identity_confidence=conf,
                    tier=tier,
                    synthetic=synthetic,
                    person_state=person_state,
                    provenance=provenance,
                ),
            )

        # Kill-switch — before any leg read.
        if census is None:
            return _ret(None, None, CENSUS_AGREEMENT_DISABLED, "census_unavailable")
        try:
            if not census._is_egress_identity_enabled():
                _note = getattr(census, "_note_egress_identity_outcome", None)
                if _note is not None:
                    try:
                        _note("disabled")
                    except Exception:  # noqa: BLE001
                        pass
                census._egress_identity_agreement_class_last = (
                    CENSUS_AGREEMENT_DISABLED
                )
                return _ret(None, None, CENSUS_AGREEMENT_DISABLED, "disabled")
        except Exception:  # noqa: BLE001 — defensive; unknown census shape
            return _ret(None, None, CENSUS_AGREEMENT_DISABLED, "resolver_error")

        def _record(outcome: str, agreement_class: str) -> None:
            """Single write path for D3 outcome + agreement class."""
            try:
                census._note_egress_identity_outcome(outcome)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "egress-identity: _note outcome=%s failed",
                    outcome, exc_info=True,
                )
            census._egress_identity_agreement_class_last = agreement_class

        # MED-4 (2026-08-28): direction-ambiguous crossings have their
        # OWN outcome label so they never inflate the identity-rate
        # denominators; return-tuple stays DISAGREE to keep the DB
        # write-gate semantics unchanged.
        if direction == "ambiguous":
            _record("direction_ambiguous", CENSUS_AGREEMENT_DISAGREE)
            return _ret(None, None, CENSUS_AGREEMENT_DISAGREE, "direction_ambiguous")

        if not egress_camera_id:
            _record("no_leg", CENSUS_AGREEMENT_SINGLE)
            return _ret(None, None, CENSUS_AGREEMENT_SINGLE, "no_leg")
        egress_stem = self._extract_camera_stem(egress_camera_id)
        if not egress_stem:
            _record("no_leg", CENSUS_AGREEMENT_SINGLE)
            return _ret(None, None, CENSUS_AGREEMENT_SINGLE, "no_leg")

        # Assemble the leg-set (stems): egress-cam ∪ interior-adjacent
        # camera stems, deduplicated. `_get_interior_cameras_near`
        # returns full ENTITY_IDs — normalize each via `_extract_camera_stem`.
        stems: list[str] = [egress_stem]
        seen_stems = {egress_stem}
        try:
            near = self._get_interior_cameras_near(egress_camera_id) or []
        except Exception:  # noqa: BLE001 — defensive
            near = []
        for eid in near:
            try:
                s = self._extract_camera_stem(eid)
            except Exception:  # noqa: BLE001
                s = None
            if s and s not in seen_stems:
                seen_stems.add(s)
                stems.append(s)

        # Collect all NAME-carrying face legs across the leg-set.
        all_legs: list = []
        for stem in stems:
            try:
                legs = census._resolve_face_legs(stem)
            except Exception:  # noqa: BLE001 — defensive; accessor is fail-CLOSED
                _LOGGER.debug(
                    "egress-identity: _resolve_face_legs raised for stem=%s",
                    stem, exc_info=True,
                )
                continue
            if not legs:
                continue
            all_legs.extend(legs)

        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D4 §0: face-producer
        # health + provenance filter. Under STRICT + face-producer-down
        # (Frigate off, MQTT bridge stale, drill switch engaged), all
        # face-provenance legs are dropped BEFORE the classifier runs.
        # BLE legs (collected below) are untouched — they keep naming
        # the crossing. Read-time only; no timers.
        try:
            strict = census._is_egress_identity_failsafe_strict()
            face_live = census._is_face_producer_live()
        except Exception:  # noqa: BLE001
            strict = True
            face_live = True
        if strict and not face_live:
            if all_legs:
                try:
                    # Review OB-1: per-LEG counter distinct from the
                    # census per-TICK counter to keep unit consistent.
                    if not hasattr(census, "_face_dropped_producer_down_leg_count"):
                        census._face_dropped_producer_down_leg_count = 0
                    census._face_dropped_producer_down_leg_count += len(all_legs)
                except Exception:  # noqa: BLE001
                    pass
            all_legs = []

        # Review FS-2 (2026-09-04): per-leg wall-clock staleness gate
        # + person-not_home veto (defence-in-depth against a stuck-
        # but-flapping face sensor whose last_changed re-stamps and
        # defeats the signed-lag window). Wall-clock reference is
        # `dt_util.utcnow()`; when the crossing `timestamp` is
        # historical (test replay: |utcnow - timestamp| > 3600s) we
        # skip the wall-clock check so fixture-driven tests keep
        # working, but we ALWAYS apply the person-not_home veto (which
        # is the semantic backstop the enhanced-census path already
        # relies on at :4269-4290).
        try:
            _wall_now = dt_util.utcnow()
            if getattr(_wall_now, "tzinfo", None) is None:
                _wall_now = _wall_now.replace(tzinfo=dt_util.UTC)
        except Exception:  # noqa: BLE001
            _wall_now = timestamp
        try:
            _ts_ref = timestamp
            if getattr(_ts_ref, "tzinfo", None) is None:
                _ts_ref = _ts_ref.replace(tzinfo=dt_util.UTC)
            _historical = abs((_wall_now - _ts_ref).total_seconds()) > 3600.0
        except Exception:  # noqa: BLE001
            _historical = True
        # Review FS-2 person-not_home veto is intentionally NOT applied
        # here on the single-leg path — the downstream "vetoed" outcome
        # (see the SINGLE-SLUG branch below) already produces the
        # distinct label the observability deque relies on. The helper
        # `census.is_face_leg_person_vetoed(leg)` remains available for
        # future multi-leg wiring but is not consumed on this cycle.
        _fresh_all_legs = []
        for leg in all_legs:
            lc = getattr(leg, "last_changed", None)
            if lc is None:
                _fresh_all_legs.append(leg)
                continue
            if _historical:
                _fresh_all_legs.append(leg)
                continue
            try:
                if lc.tzinfo is None:
                    lc = lc.replace(tzinfo=dt_util.UTC)
                age_s = (_wall_now - lc).total_seconds()
            except Exception:  # noqa: BLE001
                _fresh_all_legs.append(leg)
                continue
            if age_s > FACE_PRODUCER_STALE_TTL_S:
                try:
                    census._face_dropped_stale_count += 1
                except Exception:  # noqa: BLE001
                    pass
                continue
            _fresh_all_legs.append(leg)
        all_legs = _fresh_all_legs

        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D2: BLE-transition
        # legs matching this crossing direction, from the census
        # provenance-guarded cache. Empty when no in-window BLE
        # transition exists for a tracked slug.
        try:
            ble_legs = census._resolve_ble_legs(timestamp, direction) or []
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "egress-identity: _resolve_ble_legs raised", exc_info=True,
            )
            ble_legs = []

        # Direction-keyed asymmetric signed-lag window.
        if direction == "exit":
            lo = -float(FACE_MATCH_EXIT_WINDOW_BEFORE_S)
            hi = float(FACE_MATCH_EXIT_WINDOW_AFTER_S)
        else:  # entry
            lo = -float(FACE_MATCH_ENTRY_WINDOW_BEFORE_S)
            hi = float(FACE_MATCH_ENTRY_WINDOW_AFTER_S)

        in_window: list = []
        for leg in all_legs:
            if leg.canonical_slug is None:
                continue
            # C-LOW-1: MIN_CONFIDENCE floor already enforced by the sole
            # producer (_resolve_face_legs); no defence-in-depth re-check.
            lc = leg.last_changed
            if lc is None:
                continue
            try:
                if lc.tzinfo is None:
                    lc = lc.replace(tzinfo=dt_util.UTC)
                delta = (lc - timestamp).total_seconds()
            except (TypeError, AttributeError):
                continue
            if delta < lo or delta > hi:
                continue
            in_window.append((leg, delta))

        # IDENTITY-FUSION-PRODUCER-1 D2 precedence branch. BLE legs
        # (from the direction-keyed cache above) are considered
        # alongside face legs. Trust model (plan §3.2 with H2):
        #   - No face in-window, BLE in-window  -> attached_ble
        #   - BLE + agreeing RESIDENT face      -> corroborated (BOOST)
        #   - BLE + disagreeing RESIDENT face   -> BLE wins
        #   - BLE + disagreeing `guest:*` face  -> ABSTAIN (H2:
        #     never attribute a guest's crossing to a resident).
        ble_slugs = {leg.person_slug for leg in ble_legs if leg.person_slug}
        face_slugs = {leg.canonical_slug for leg, _ in in_window
                      if leg.canonical_slug}
        if ble_slugs:
            # BLE-only path — no in-window face at all.
            if not in_window:
                # Multi-slug BLE (rare — two housemates crossing
                # simultaneously): defer to face-style DISAGREE.
                if len(ble_slugs) >= 2:
                    try:
                        census._ble_legs_abstained_count += 1
                    except Exception:  # noqa: BLE001
                        pass
                    _record("abstain", CENSUS_AGREEMENT_DISAGREE)
                    return _ret(None, None, CENSUS_AGREEMENT_DISAGREE, "abstain")
                slug = next(iter(ble_slugs))
                # D-5: INV-EGRESS-ID — a leg produced before a slug
                # was untracked must not attach after.
                try:
                    _tracked_all = set(census._get_tracked_person_slugs())
                except Exception:  # noqa: BLE001
                    _tracked_all = set()
                if slug not in _tracked_all:
                    try:
                        census._ble_legs_abstained_count += 1
                    except Exception:  # noqa: BLE001
                        pass
                    _record("abstain", CENSUS_AGREEMENT_DISAGREE)
                    return _ret(
                        None, None, CENSUS_AGREEMENT_DISAGREE, "abstain",
                        slug=slug,
                    )
                # D-2: cross-resident mislabel guard. If ANY tracked
                # resident currently derives ZERO bluetooth_le
                # trackers (i.e. an invisible potential crosser),
                # attribution is ambiguous — we cannot rule out that
                # THEIR crossing produced no leg and this leg belongs
                # to someone else. Abstain (fail closed).
                try:
                    _slug_map = dict(getattr(census, "_ble_tracker_slug_map", {}) or {})
                except Exception:  # noqa: BLE001
                    _slug_map = {}
                _slugs_with_ble = set(_slug_map.values())
                _invisible = [s for s in _tracked_all if s not in _slugs_with_ble]
                if _invisible:
                    _LOGGER.info(
                        "egress-identity: BLE-only attach ambiguous — "
                        "tracked resident(s) %r have zero bluetooth_le "
                        "trackers; abstaining to avoid cross-resident "
                        "mislabel (candidate=%s).",
                        sorted(_invisible), slug,
                    )
                    try:
                        census._ble_legs_abstained_count += 1
                    except Exception:  # noqa: BLE001
                        pass
                    _record("abstain_ble_ambiguous", CENSUS_AGREEMENT_DISAGREE)
                    return _ret(
                        None, None, CENSUS_AGREEMENT_DISAGREE,
                        "abstain_ble_ambiguous", slug=slug,
                    )
                _leg = next(l for l in ble_legs if l.person_slug == slug)
                try:
                    census._egress_identity_last_attach = {
                        "person": slug,
                        "camera": egress_camera_id,
                        "identity_confidence": float(BLE_TRANSITION_ONLY_CONFIDENCE),
                        "signed_lag_delta_seconds": (
                            (_leg.transition_ts - timestamp).total_seconds()
                            if _leg.transition_ts else None
                        ),
                        "direction": direction,
                        "agreement_class": CENSUS_AGREEMENT_SINGLE,
                        "contributor_engines": ["ble"],
                        "provenance": IDENTITY_PROVENANCE_BLE,
                    }
                except Exception:  # noqa: BLE001
                    pass
                _record("attached_ble", CENSUS_AGREEMENT_SINGLE)
                # rev5 D2 single-use: consume ONLY on the attach branch.
                try:
                    census._consume_ble_arriving_legs(slug)
                except Exception:  # noqa: BLE001
                    pass
                return _ret(
                    slug,
                    float(BLE_TRANSITION_ONLY_CONFIDENCE),
                    CENSUS_AGREEMENT_SINGLE,
                    "attached_ble",
                    slug=slug,
                    provenance=IDENTITY_PROVENANCE_BLE,
                )
            # BLE + face both present. Enumerate by single BLE slug for
            # H2 clarity (BLE window is narrow enough that concurrent
            # multi-slug BLE + face is out-of-scope for this cycle).
            if len(ble_slugs) == 1 and len(face_slugs) == 1:
                b_slug = next(iter(ble_slugs))
                f_slug = next(iter(face_slugs))
                if b_slug == f_slug:
                    # AGREEING resident: corroborated BOOST.
                    # Review OB-2 (A-MED-2): stamp the BOOST ledger so
                    # the corroboration event is visible in the same
                    # 24h rate the multi-face path uses.
                    try:
                        census._egress_identity_boost_events.append(
                            dt_util.utcnow().timestamp()
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    _record(
                        "attached_ble_face_corroborated",
                        CENSUS_AGREEMENT_TWO_ENGINES,
                    )
                    try:
                        census._egress_identity_last_attach = {
                            "person": b_slug,
                            "camera": egress_camera_id,
                            "identity_confidence": float(
                                BLE_PLUS_FACE_CORROBORATED_CONFIDENCE),
                            "signed_lag_delta_seconds": None,
                            "direction": direction,
                            "agreement_class": CENSUS_AGREEMENT_TWO_ENGINES,
                            "contributor_engines": sorted(
                                {l.engine for l, _ in in_window} | {"ble"}
                            ),
                            "provenance": IDENTITY_PROVENANCE_BLE_FACE,
                        }
                    except Exception:  # noqa: BLE001
                        pass
                    # rev5 D2 single-use: attach branch only.
                    try:
                        census._consume_ble_arriving_legs(b_slug)
                    except Exception:  # noqa: BLE001
                        pass
                    return _ret(
                        b_slug,
                        float(BLE_PLUS_FACE_CORROBORATED_CONFIDENCE),
                        CENSUS_AGREEMENT_TWO_ENGINES,
                        "attached_ble_face_corroborated",
                        slug=b_slug,
                        provenance=IDENTITY_PROVENANCE_BLE_FACE,
                    )
                # DISAGREEMENT — H2 / Review AT-1 (A-HIGH-2) 2026-09-04:
                # abstain unless the face slug is itself a TRACKED
                # RESIDENT (in _get_tracked_person_slugs()). The prior
                # `startswith("guest:")` check only fired when the
                # operator had wired `known_face_guests` — at the empty
                # default (D3 dormant), a face-recognized name like
                # "Ojini" passed through as a bare "ojini" slug that
                # this branch treated as a resident, letting BLE-wins
                # attribute her crossing to Oji. Now: any face slug
                # that isn't a tracked resident forces ABSTAIN.
                try:
                    _tracked = set(census._get_tracked_person_slugs())
                except Exception:  # noqa: BLE001
                    _tracked = set()
                if f_slug not in _tracked:
                    _LOGGER.info(
                        "egress-identity: ABSTAIN resident_vs_guest "
                        "(ble=%s, face=%s, tracked=%s)",
                        b_slug, f_slug, "yes" if b_slug in _tracked else "no",
                    )
                    try:
                        census._ble_legs_abstained_count += 1
                    except Exception:  # noqa: BLE001
                        pass
                    _record(
                        "abstain_resident_vs_guest",
                        CENSUS_AGREEMENT_DISAGREE,
                    )
                    return _ret(
                        None, None, CENSUS_AGREEMENT_DISAGREE,
                        "abstain_resident_vs_guest",
                    )
                # Two tracked residents disagree: BLE wins over face.
                _LOGGER.info(
                    "egress-identity: BLE wins over disagreeing face "
                    "(ble=%s, face=%s)", b_slug, f_slug,
                )
                _record(
                    "ble_face_disagree_ble_wins",
                    CENSUS_AGREEMENT_SINGLE,
                )
                try:
                    census._egress_identity_last_attach = {
                        "person": b_slug,
                        "camera": egress_camera_id,
                        "identity_confidence": float(BLE_TRANSITION_ONLY_CONFIDENCE),
                        "signed_lag_delta_seconds": None,
                        "direction": direction,
                        "agreement_class": CENSUS_AGREEMENT_SINGLE,
                        "contributor_engines": ["ble"],
                        "provenance": IDENTITY_PROVENANCE_BLE,
                    }
                except Exception:  # noqa: BLE001
                    pass
                # rev5 D2 single-use: attach branch only (BLE-wins).
                try:
                    census._consume_ble_arriving_legs(b_slug)
                except Exception:  # noqa: BLE001
                    pass
                return _ret(
                    b_slug,
                    float(BLE_TRANSITION_ONLY_CONFIDENCE),
                    CENSUS_AGREEMENT_SINGLE,
                    "ble_face_disagree_ble_wins",
                    slug=b_slug,
                    provenance=IDENTITY_PROVENANCE_BLE,
                )
            # Multi-slug on either side w/ BLE present: retain existing
            # ABSTAIN semantics (transit_validator.py DISAGREE branch,
            # RETAINED per H2 precedence rule).
            if len(ble_slugs | face_slugs) >= 2:
                try:
                    census._ble_legs_abstained_count += 1
                except Exception:  # noqa: BLE001
                    pass
                _record("abstain", CENSUS_AGREEMENT_DISAGREE)
                return _ret(None, None, CENSUS_AGREEMENT_DISAGREE, "abstain")

        if not in_window:
            _record("no_leg", CENSUS_AGREEMENT_SINGLE)
            return _ret(None, None, CENSUS_AGREEMENT_SINGLE, "no_leg")

        slugs = {leg.canonical_slug for leg, _ in in_window}

        # DISAGREE branch — split into "abstain" (close) vs "ambiguous"
        # (far) outcomes so both feed rate math via the SAME deque
        # (fix MED-3). Return tuple stays DISAGREE.
        if len(slugs) >= 2:
            deltas_by_slug: dict[str, list[float]] = {}
            for leg, d in in_window:
                deltas_by_slug.setdefault(leg.canonical_slug, []).append(d)
            min_sep: float | None = None
            keys = list(deltas_by_slug.keys())
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    for d1 in deltas_by_slug[keys[i]]:
                        for d2 in deltas_by_slug[keys[j]]:
                            sep = abs(d1 - d2)
                            if min_sep is None or sep < min_sep:
                                min_sep = sep
            outcome = (
                "abstain"
                if (min_sep is not None
                    and min_sep <= FACE_MATCH_ABSTAIN_MARGIN_S)
                else "ambiguous"
            )
            _LOGGER.info(
                "egress-identity: DISAGREE outcome=%s across %d slugs %r",
                outcome, len(slugs), sorted(slugs),
            )
            _record(outcome, CENSUS_AGREEMENT_DISAGREE)
            return _ret(None, None, CENSUS_AGREEMENT_DISAGREE, outcome)

        # |slugs| == 1.
        slug = next(iter(slugs))

        # Fail-open person-tracker veto (A5: distinct "vetoed" outcome).
        try:
            person_state = self.hass.states.get(f"person.{slug}")
        except Exception:  # noqa: BLE001
            person_state = None
        _person_raw = (
            getattr(person_state, "state", None)
            if person_state is not None else None
        )
        # HIGH-1 (2026-08-28): base_stem-ONLY independence predicate.
        # Protect + Frigate on the SAME physical camera have DIFFERENT
        # device_ids but the SAME base_stem — device_id is retained on
        # FaceLeg for observability only. FACE-ARRIVAL-REBUILD-1 D8a: the
        # tier arithmetic is the module-level PURE `egress_identity_tier`;
        # the veto path calls only that (no stash, no BOOST ledger append on
        # a vetoed crossing), the attach path below keeps its side effects.
        legs_only = [leg for leg, _ in in_window]
        if (
            person_state is not None
            and _person_raw == "not_home"
        ):
            _LOGGER.debug(
                "egress-identity: %s vetoed by person.%s=not_home",
                slug, slug,
            )
            _record("vetoed", CENSUS_AGREEMENT_SINGLE)
            _v_tier, _v_syn = egress_identity_tier(legs_only)
            return _ret(
                None, None, CENSUS_AGREEMENT_SINGLE, "vetoed",
                slug=slug, tier=_v_tier, synthetic=_v_syn,
                person_state=_person_raw,
            )

        identity_confidence, _tier_synthetic = egress_identity_tier(legs_only)
        if identity_confidence == float(CONFIDENCE_HIGH):
            agreement_class = CENSUS_AGREEMENT_BOTH
            # B-M1: does the 0.9 survive without the synthetic latch legs?
            self._last_identity_synthetic_corroborated = _tier_synthetic
        elif identity_confidence == float(FACE_MATCH_CORRELATED_BOOST):
            agreement_class = CENSUS_AGREEMENT_BOTH
            # BOOST event ledger (24h-filtered at the reader; MED-1).
            try:
                census._egress_identity_boost_events.append(
                    dt_util.utcnow().timestamp()
                )
            except Exception:  # noqa: BLE001
                pass
        else:
            agreement_class = CENSUS_AGREEMENT_SINGLE

        # MED-5: derive contributor_engines + signed_lag_delta from the
        # SAME in_window slice used to decide. Newest last_changed wins.
        contributor_engines: list[str] = []
        newest_delta: float | None = None
        for leg, d in in_window:
            if leg.engine and leg.engine not in contributor_engines:
                contributor_engines.append(leg.engine)
            if newest_delta is None or d > newest_delta:
                newest_delta = d
        try:
            census._egress_identity_last_attach = {
                "person": slug,
                "camera": egress_camera_id,
                "identity_confidence": identity_confidence,
                "signed_lag_delta_seconds": newest_delta,
                "direction": direction,
                "agreement_class": agreement_class,
                "contributor_engines": contributor_engines,
                # FACE-ARRIVAL-REBUILD-1 (plan rev 4 H1): explicit, the value
                # every reader already defaulted to for this path.
                "provenance": IDENTITY_PROVENANCE_FACE,
            }
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "egress-identity: last_attach populate failed",
                exc_info=True,
            )
        _record("attached", agreement_class)
        return _ret(
            slug, identity_confidence, agreement_class, "attached",
            slug=slug, tier=identity_confidence, synthetic=_tier_synthetic,
            person_state=_person_raw, provenance=IDENTITY_PROVENANCE_FACE,
        )

    async def _resolve_direction(
        self, egress_camera_id: str, egress_timestamp: datetime
    ) -> None:
        """Determine entry, exit, or ambiguous and fire event on bus.

        PLANNING_census_inputs_first D1 (R2.2 / R3.3 / R3.9 / R4.1):
        * Dedup window is the knob ``DOOR_STEM_DEDUP_S`` (default 30 s),
          replacing the historical 5 s inline literal.
        * When ``CONF_DOOR_GROUPS`` is SET and this stem has a group,
          dedup is scoped to the DOOR_GROUP (not just same-stem).
          UNSET → per-stem dedup (today's behaviour byte-identical).
        * Direction-keyed dedup (Review B3): dedup key is suffixed with
          the RESOLVED direction so an opposite-direction crossing in
          the window (exit t0 then entry t0+20) is NOT swallowed.
        * Interior-neighbour direction loop (Review A-HIGH): walk each
          neighbour forward (develop semantics — oldest first per
          camera, so a single-camera t-12/t+8 stays EXIT), then across
          cameras pick the match whose |delta| is smallest (so a
          cross-camera t+3 foyer beats a noisy t-25 family_room).
          Byte-identical to develop when exactly one neighbour matches.
        """
        # Compute dedup base key (direction suffix appended after resolve).
        stem = self._extract_camera_stem(egress_camera_id)
        dedup_base: str | None = None
        if stem:
            group = self._door_group_for_stem(stem)
            dedup_base = f"group:{group}" if group else stem

        direction = "ambiguous"
        near_door_cameras = self._get_interior_cameras_near(egress_camera_id)

        # Review A-HIGH: per-camera first-match (forward, develop
        # semantics); across cameras choose the match closest in time
        # to the egress event.
        best_abs_delta: float | None = None
        for interior_cam in near_door_cameras:
            interior_times = self._recent_interior_events.get(interior_cam, [])
            cam_match: tuple[float, str] | None = None
            for interior_time in interior_times:
                delta = (interior_time - egress_timestamp).total_seconds()
                if 0 <= delta <= self.ENTRY_WINDOW_SECONDS:
                    cam_match = (abs(delta), "entry")
                    break
                if -self.EXIT_WINDOW_SECONDS <= delta < 0:
                    cam_match = (abs(delta), "exit")
                    break
            if cam_match is None:
                continue
            if best_abs_delta is None or cam_match[0] < best_abs_delta:
                best_abs_delta = cam_match[0]
                direction = cam_match[1]

        # Review B3: direction-keyed dedup. Same stem/group + same
        # direction inside the window collapses; opposite direction
        # NEVER collapses (exit→entry inside 30 s is a real round-trip).
        if dedup_base is not None:
            dedup_key = f"{dedup_base}|{direction}"
            last = self._last_resolved.get(dedup_key)
            if last and (egress_timestamp - last).total_seconds() < DOOR_STEM_DEDUP_S:
                _LOGGER.debug(
                    "Egress dedup: skipping %s (key=%s resolved %.1fs ago)",
                    egress_camera_id, dedup_key,
                    (egress_timestamp - last).total_seconds(),
                )
                return
            self._last_resolved[dedup_key] = egress_timestamp

        # Multi-platform confidence boost: count how many platform sensors
        # fired for the same stem within 10 seconds
        platforms_fired = self._count_platforms_fired(stem, egress_timestamp) if stem else 1
        if direction != "ambiguous":
            confidence = 0.9 if platforms_fired >= 2 else 0.8
        else:
            confidence = 0.4 if platforms_fired >= 2 else 0.3

        # EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28) D2b: corroborated
        # identity across the leg-set (egress-cam stem + interior-adjacent
        # cameras), direction-keyed signed-lag window, agreement
        # classifier. Returns (slug_or_None, identity_confidence_or_None,
        # agreement_class). The bus/DB `confidence` field continues to
        # carry the pre-cycle platforms-fired crossing/direction value
        # (unmodified). Identity confidence goes into D3 attrs.
        (
            person_id,
            identity_confidence,
            agreement_class,
            resolution,
        ) = self._resolve_egress_face_identity_ex(
            egress_camera_id, egress_timestamp, direction,
        )
        # FACE-ARRIVAL-REBUILD-1 D8a: persist the outcome (one row per
        # resolution, every path). Observational; nothing below reads it.
        self._log_egress_outcome(resolution, egress_camera_id, egress_timestamp)

        # Fire event on HA bus (pre-cycle `confidence` semantics preserved).
        self.hass.bus.async_fire("ura_person_egress_event", {
            "direction": direction,
            "egress_camera": egress_camera_id,
            "timestamp": egress_timestamp.isoformat(),
            "person_id": person_id,
            "confidence": confidence,
            # Additive observability fields (D3). Consumers on the bus
            # that never referenced these keys are unaffected.
            "identity_confidence": identity_confidence,
            "agreement_class": agreement_class,
            # v5.108.1 B-M1 (additive): the 0.9 needed a synthetic MQTT
            # latch leg. Perimeter D10.5 then needs a non-face arrival edge.
            "identity_synthetic_corroborated": bool(
                getattr(self, "_last_identity_synthetic_corroborated", False)
            ),
            # FACE-ARRIVAL-REBUILD-1 (additive): how the identity was known,
            # read from THIS call's resolution (never the last-attach stash).
            # None when person_id is None.
            "identity_provenance": (
                resolution.provenance if person_id is not None else None
            ),
        })

        _LOGGER.debug(
            "Egress direction resolved: camera=%s, direction=%s, "
            "confidence=%.2f, person_id=%s",
            egress_camera_id, direction, confidence, person_id,
        )

        # ARRIVAL-DEPARTURE-NOTIFY-1 (Wave-1 consumer #1): turn a named
        # egress crossing into an "Oji arrived / Oji left" notification.
        # - Gate: direction in (entry, exit); skip ambiguous.
        # - Name only when identity_confidence >= 0.75 (card doctrine);
        #   otherwise graceful-anonymous "Someone arrived/left" — the
        #   card explicitly picks anonymous-notify over suppress.
        # - Best-effort: any NM/lookup failure MUST NOT break the emit.
        try:
            self._arrival_departure_notify(
                direction, person_id, identity_confidence,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "arrival/departure notify failed (non-fatal)",
                exc_info=True,
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
        census_ref = self.hass.data.get(DOMAIN, {}).get("census")
        if person_id and direction in ("entry", "exit"):
            if census_ref is not None:
                try:
                    if direction == "entry":
                        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D4/H1:
                        # forward the resolver's provenance tag so the
                        # census union can gate face-provenance names
                        # under a face-producer outage (BLE-provenance
                        # survives; guest:* goes to a separate bucket).
                        try:
                            _prov = str(
                                (getattr(census_ref, "_egress_identity_last_attach", {}) or {})
                                .get("provenance", IDENTITY_PROVENANCE_FACE)
                            )
                        except Exception:  # noqa: BLE001
                            _prov = IDENTITY_PROVENANCE_FACE
                        census_ref.register_egress_face(
                            person_id, egress_timestamp, provenance=_prov,
                        )
                    else:  # direction == "exit"
                        census_ref.evict_egress_face(person_id)
                except Exception:  # noqa: BLE001 — census register is
                    # best-effort; do not fail the egress emit path.
                    _LOGGER.debug(
                        "egress-face census %s failed for %s",
                        direction, person_id, exc_info=True,
                    )

        # D3 observability (outcome append + agreement class + last_attach)
        # is owned by the resolver — the SAME site that decides the class
        # writes it, keeping contributor_engines / signed_lag derived from
        # the in-window slice that made the decision (MED-5) and the
        # outcome labels the authoritative rate producer (MED-3/MED-4/A5).

        # Log to database if not ambiguous
        if direction != "ambiguous":
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database:
                # Review LOW: sample BEFORE the DB-write try so a sampler
                # exception can't lose the row. Sampler is best-effort and
                # falls back to None (NULL in DB) on error.
                try:
                    peak = self._sample_peak_person_count(
                        stem, egress_timestamp,
                    )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.debug(
                        "peak_person_count sampler failed (non-fatal): %s", e,
                    )
                    peak = None
                try:
                    await database.log_entry_exit_event(
                        person_id=person_id,
                        event_type="egress",
                        direction=direction,
                        egress_camera=egress_camera_id,
                        confidence=confidence,
                        peak_person_count=peak,
                    )
                except Exception as e:
                    _LOGGER.error("Failed to log entry/exit event: %s", e)

    # ------------------------------------------------------------------
    # FACE-ARRIVAL-REBUILD-1 D7: interior path map loading
    # ------------------------------------------------------------------

    def async_setup_path_map(self) -> None:
        """Schedule the FIRST path-map load at the resolver-ready point:
        immediately when HA is already running (an entry reload), else at
        EVENT_HOMEASSISTANT_STARTED (Frigate / Protect may register their
        cameras after URA). Also subscribes the registry-update re-validation
        (debounced) used while the installed source is not the file."""
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: PLC0415

        if bool(getattr(self.hass, "is_running", False)):
            self._spawn_path_map_load()
        else:
            started = {"unsub": None}

            @callback
            def _on_started(_event=None) -> None:
                started["unsub"] = None
                self._spawn_path_map_load()

            started["unsub"] = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _on_started,
            )
            self._path_map_unsubs.append(lambda: started["unsub"] and started["unsub"]())
        try:
            from homeassistant.helpers.entity_registry import (  # noqa: PLC0415
                EVENT_ENTITY_REGISTRY_UPDATED,
            )
        except Exception:  # noqa: BLE001
            EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
        self._path_map_unsubs.append(
            self.hass.bus.async_listen(
                EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated_path_map,
            )
        )

    @callback
    def _on_registry_updated_path_map(self, _event=None) -> None:
        """Re-validation while the file is NOT installed (whole-file
        rejection: one camera registered late kept the const / none). Once
        the file is installed, registry events do nothing (the button
        reloads)."""
        if self._torn_down or self._path_map_from_file or not self._path_map_loaded_once:
            return
        from homeassistant.helpers.event import async_call_later  # noqa: PLC0415

        if self._path_map_reval_unsub is not None:
            self._path_map_reval_unsub()
        delay = float(INTERIOR_PATH_MAP_REVALIDATE_DEBOUNCE_S)

        @callback
        def _fire(_now=None) -> None:
            self._path_map_reval_unsub = None
            self._spawn_path_map_load()

        self._path_map_reval_unsub = async_call_later(self.hass, delay, _fire)

    def _spawn_path_map_load(self) -> None:
        if self._torn_down:
            return
        task = self.hass.async_create_task(self.async_load_path_map())
        self._path_map_tasks.add(task)
        try:
            task.add_done_callback(self._path_map_tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    def _path_map_context(self):
        """Validator context from the live install (registry-resolved)."""
        from .camera_resolver import canonical_camera_key  # noqa: PLC0415
        from .interior_paths import ValidationContext  # noqa: PLC0415

        cm = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        resolver = None
        try:
            resolver = cm._get_resolver() if cm is not None else None
        except Exception:  # noqa: BLE001
            resolver = None
        cache: dict = {}

        def resolve_node(entity_id: str):
            if entity_id in cache:
                return cache[entity_id]
            out = (None, False)
            if resolver is not None and isinstance(entity_id, str):
                try:
                    if resolver._er.async_get(entity_id) is not None:
                        fusions = resolver.resolve_operator_declaration([entity_id])
                        if fusions:
                            out = (
                                canonical_camera_key(fusions[0]),
                                any(src.person_binary_sensor for src in fusions[0].sources),
                            )
                except Exception:  # noqa: BLE001
                    out = (None, False)
            cache[entity_id] = out
            return out

        groups: set[str] = set()
        egress_keys: dict[str, set[str]] = {}
        for ent in self._egress_entities:
            stem = self._extract_camera_stem(ent)
            group = self._door_group_for_stem(stem) or stem
            if not group:
                continue
            groups.add(group)
            key, _leg = resolve_node(ent)
            if key:
                egress_keys.setdefault(group, set()).add(key)
        exterior: set[str] = set().union(*egress_keys.values()) if egress_keys else set()
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_INTEGRATION:
                    continue
                merged = {**entry.data, **entry.options}
                for cam in merged.get(CONF_PERIMETER_CAMERAS) or []:
                    key, _leg = resolve_node(cam)
                    if key:
                        exterior.add(key)
                break
        except Exception:  # noqa: BLE001
            pass
        return ValidationContext(
            live_groups=groups,
            resolve_node=resolve_node,
            egress_keys_by_group=egress_keys,
            exterior_keys=exterior,
            detached_doors=set(INTERIOR_PATH_DETACHED_DOORS),
            buffer_s=float(EGRESS_PATH_BUFFER_S),
            default_window_s=float(EGRESS_PATH_HOP_DEFAULT_WINDOW_S),
        )

    async def async_load_path_map(self) -> str:
        """Load ``interior_paths.json`` through the shared JSON loader.

        Four outcomes: (1) file valid -> file map; (2) file absent -> the
        validated const, or no map; (3) file invalid at the FIRST load ->
        validated const or no map; (4) file invalid on a later load (button,
        re-validation) -> the previous map is kept. ``path_map_sha256`` names
        the INSTALLED source only (the file's sha when the file is installed,
        else None; never a rejected file's sha). Never raises."""
        from .interior_paths import PathMapError, validate  # noqa: PLC0415
        from .json_file_loader import (  # noqa: PLC0415
            STATUS_ABSENT,
            STATUS_LOADED,
            load_validated_json,
        )

        try:
            ctx = self._path_map_context()
            path = self.hass.config.path(DEFAULT_INTERIOR_PATH_FILE)
            outcome = await load_validated_json(
                self.hass, path, parse_validate=lambda spec: validate(spec, ctx),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Interior path map load failed: %s", exc)
            return self.path_map_validation
        first = not self._path_map_loaded_once
        self._path_map_loaded_once = True
        if outcome.status == STATUS_LOADED:
            pmap = outcome.value
            self.path_map = pmap
            self._path_map_from_file = True
            self.path_map_sha256 = outcome.raw_sha256
            self.path_map_source = (
                f"interior_paths.json (schema 1, {pmap.edge_count} edges)"
            )
            self.path_map_validation = (
                "ok" if not outcome.warnings
                else f"ok ({len(outcome.warnings)} warning(s): {outcome.warnings[0]})"
            )
            _LOGGER.info("Interior path map installed from %s (%s)", path, self.path_map_source)
            return self.path_map_validation
        verdict = (
            "file absent" if outcome.status == STATUS_ABSENT
            else f"rejected: {outcome.error}"
        )
        if outcome.status != STATUS_ABSENT:
            _LOGGER.warning("Interior path map file %s REJECTED: %s", path, outcome.error)
        if not first and self._path_map_from_file:
            # (4) a later invalid / absent file keeps the previous good map.
            self.path_map_validation = f"{verdict} (kept previous)"
            return self.path_map_validation
        # (2)/(3) and re-validation of a const/none install: validated const
        # or no map. The const is VALIDATED like the file (on a foreign
        # install its entity ids do not resolve -> no map).
        try:
            fallback, _warns = validate(INTERIOR_PATH_MAP_FALLBACK, ctx)
        except PathMapError as exc:
            fallback = None
            verdict = f"{verdict}; built-in const rejected: {exc}"
        self.path_map = fallback
        self._path_map_from_file = False
        self.path_map_sha256 = None
        self.path_map_source = "built-in const" if fallback is not None else "none"
        self.path_map_validation = verdict
        return self.path_map_validation

    def path_map_status(self) -> dict[str, Any]:
        """D7 provenance attrs (next to the seam ones)."""
        pmap = self.path_map
        return {
            "path_map_source": self.path_map_source,
            "path_map_validation": self.path_map_validation,
            "path_map_sha256": self.path_map_sha256,
            "path_map_doors": sorted(pmap.doors) if pmap is not None else [],
        }

    def _log_egress_outcome(
        self,
        resolution: EgressResolution,
        egress_camera_id: str,
        egress_timestamp: datetime,
    ) -> None:
        """FACE-ARRIVAL-REBUILD-1 D8a: persist ONE memory_episodes row
        (`egress_identity_outcome`) for this resolution.

        Never raises, never awaited by the caller (a tracked task in
        ``_outcome_log_tasks``, gathered with a bound at teardown). Returns
        without a task once ``async_teardown`` started (``_torn_down``) or
        when ``EGRESS_OUTCOME_LOG_PERSIST`` is False. ``node_id`` and
        ``source_ref`` are per crossing, so the 60 s (node_id, type) dedup of
        ``log_memory_episode`` cannot merge two crossings.
        """
        if self._torn_down or not EGRESS_OUTCOME_LOG_PERSIST:
            return
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return
        try:
            ts_iso = egress_timestamp.isoformat()
        except Exception:  # noqa: BLE001
            ts_iso = str(egress_timestamp)
        crossing_key = f"{egress_camera_id}@{ts_iso}"
        attrs = {
            "outcome": resolution.outcome,
            "direction": resolution.direction,
            "agreement": resolution.agreement,
            "slug": resolution.slug,
            "identity_confidence": resolution.identity_confidence,
            "tier": resolution.tier,
            "synthetic": resolution.synthetic,
            "person_state": resolution.person_state,
            "provenance": resolution.provenance,
            "egress_camera": egress_camera_id,
            "crossing_ts": ts_iso,
        }

        async def _write() -> None:
            try:
                await database.log_memory_episode(
                    node_id=f"egress:{crossing_key}",
                    episode_type=EGRESS_OUTCOME_EPISODE_TYPE,
                    attrs=attrs,
                    source_ref=crossing_key,
                    started_at=ts_iso,
                    ended_at=ts_iso,
                    dedup_source_ref=False,
                )
            except Exception:  # noqa: BLE001 — observational only
                _LOGGER.debug("egress outcome log failed", exc_info=True)

        try:
            task = self.hass.async_create_task(_write())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("egress outcome log task create failed", exc_info=True)
            return
        self._outcome_log_tasks.add(task)
        try:
            task.add_done_callback(self._outcome_log_tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    # ARRIVAL-DEPARTURE-NOTIFY-1 (Wave-1 consumer #1)
    ARRIVAL_NAME_CONFIDENCE_THRESHOLD = 0.75

    def _arrival_departure_notify(
        self,
        direction: str,
        person_id: str | None,
        identity_confidence: float | None,
    ) -> None:
        """Dispatch an arrival/departure notification off an egress crossing.

        - Skips direction=='ambiguous' (only entry/exit notify).
        - Names the person iff person_id truthy AND identity_confidence
          >= ARRIVAL_NAME_CONFIDENCE_THRESHOLD; else graceful-anonymous
          ("Someone arrived/left") per card doctrine (notify > suppress).
        - Best-effort: NM absence or exception is swallowed by the caller.
        """
        if direction not in ("entry", "exit"):
            return

        verb = "arrived" if direction == "entry" else "left"

        if (
            person_id
            and identity_confidence is not None
            and identity_confidence >= self.ARRIVAL_NAME_CONFIDENCE_THRESHOLD
        ):
            name = person_id.replace("_", " ").title()
        else:
            name = "Someone"

        title = f"{name} {verb}"
        message = title

        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            _LOGGER.debug(
                "arrival/departure notify skipped — NM not available (%s)",
                title,
            )
            return

        # Import locally to avoid a module-level dependency cycle.
        from .domain_coordinators.notification_manager import Severity

        _LOGGER.info("Arrival/departure notify: %s", title)

        async def _safe_notify() -> None:
            # LOW-1 fix (2026-09-06 review): the notify runs in a detached
            # task, so an exception inside async_notify would surface as an
            # unhandled-task error rather than the intended swallow. Wrap it.
            try:
                await nm.async_notify(
                    coordinator_id="presence",
                    severity=Severity.LOW,
                    title=title,
                    message=message,
                )
            except Exception:  # noqa: BLE001 — best-effort notify only
                _LOGGER.debug(
                    "arrival/departure notify failed (%s)", title,
                    exc_info=True,
                )

        self.hass.async_create_task(_safe_notify())

    def _get_interior_cameras_near(self, egress_camera_id: str) -> list[str]:
        """Return interior camera entity IDs near this egress camera.

        PLANNING_census_inputs_first R3.1 (CRITICAL-1):
          - If ``CONF_DOOR_INTERIOR_NEIGHBOURS`` is UNSET for the resolved
            door_group (or the stem has no group): fall back BYTE-IDENTICAL
            to today — return the full interior list. This keeps unset
            installs (Wigton 2nd home) working with zero regression; the
            upstream DB-write / register / notify gates are then
            byte-identical.
          - If the operator explicitly maps the door_group to an EMPTY
            list, honour that as a deliberate "no neighbours" opt-out
            (direction will tend AMBIGUOUS; downstream skips the row).
          - If the door_group is in the map with a non-empty list,
            narrow to that list.
        """
        stem = self._extract_camera_stem(egress_camera_id)
        group = self._door_group_for_stem(stem)
        if group is not None and group in self._interior_neighbours_by_group:
            configured = self._interior_neighbours_by_group[group]
            return list(configured)
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

        # R4.2 (N-HIGH-2): prune horizon >= DOOR_STEM_DEDUP_S +
        # ENTRY_WINDOW_SECONDS; dedup head writes `_last_resolved` only
        # after the 45 s delayed-resolve, so a smaller horizon can race
        # the writer and drop the first-leg key before the second leg's
        # dedup head consults it.
        prune_horizon = max(60, DOOR_STEM_DEDUP_S + self.ENTRY_WINDOW_SECONDS)
        dedup_cutoff = dt_util.now() - timedelta(seconds=prune_horizon)
        stale_stems = [
            stem for stem, ts in self._last_resolved.items()
            if ts < dedup_cutoff
        ]
        for stem in stale_stems:
            del self._last_resolved[stem]

    async def async_teardown(self) -> None:
        """Unsubscribe all listeners."""
        # FACE-ARRIVAL-REBUILD-1 D8a (plan rev 11 L3): latch FIRST so a
        # `_delayed_resolve` already scheduled cannot create an outcome-log
        # task after the gather below.
        self._torn_down = True
        for unsub in self._unsub:
            try:
                unsub()
            except Exception:
                pass
        self._unsub.clear()
        self._peak_count_unsubs.clear()
        self._peak_count_buffer.clear()
        self._count_sensor_to_stem.clear()
        pending = [t for t in self._outcome_log_tasks if not t.done()]
        if pending:
            import asyncio  # noqa: PLC0415
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=EGRESS_OUTCOME_LOG_TEARDOWN_TIMEOUT_S,
                )
            except Exception:  # noqa: BLE001 — bounded; never block unload
                for t in pending:
                    if not t.done():
                        t.cancel()
        self._outcome_log_tasks.clear()
        # D7: path-map listeners, debounce timer and in-flight loads.
        for unsub in self._path_map_unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._path_map_unsubs.clear()
        if self._path_map_reval_unsub is not None:
            try:
                self._path_map_reval_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._path_map_reval_unsub = None
        for t in list(self._path_map_tasks):
            if not t.done():
                t.cancel()
        self._path_map_tasks.clear()
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
