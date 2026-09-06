"""Camera integration and person census for Universal Room Automation v3.5.0."""
#
# Universal Room Automation vv5.97.1
# Build: 2026-02-23
# File: camera_census.py
# Cycle 3: Camera Integration & Census Core
#
# Provides:
#   - CameraIntegrationManager: Discovers Frigate and UniFi Protect camera entities
#   - PersonCensus: Dual-zone census engine (house interior + property exterior)
#   - CensusZoneResult: Per-zone census result dataclass
#   - FullCensusResult: Combined house + property result dataclass
#

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .camera_resolver import _strip_disambiguation_suffix

from .const import (
    DOMAIN,
    CONF_AREA_ID,
    CONF_ROOM_NAME,
    CONF_STUCK_CAMERA_HOURS,
    CONF_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED,
    DEFAULT_STUCK_CAMERA_HOURS,
    DEFAULT_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED,
    STUCK_CAMERA_NEVERZERO_HOURS,
    STATE_MOTION_DETECTED,
    STATE_OCCUPIED,
    STATE_PRESENCE_DETECTED,
    ENTRY_TYPE_ROOM,
    TRACKING_STATUS_STALE,
    TRACKING_STATUS_LOST,
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_EGRESS_CAMERAS,
    CONF_PERIMETER_CAMERAS,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_INTEGRATION,
    CAMERA_PLATFORM_FRIGATE,
    CAMERA_PLATFORM_UNIFI,
    CENSUS_CONFIDENCE_HIGH,
    CENSUS_CONFIDENCE_MEDIUM,
    CENSUS_CONFIDENCE_LOW,
    CENSUS_CONFIDENCE_NONE,
    CENSUS_AGREEMENT_BOTH,
    CENSUS_AGREEMENT_CLOSE,
    CENSUS_AGREEMENT_DISAGREE,
    CENSUS_AGREEMENT_SINGLE,
    CONF_CENSUS_CROSS_VALIDATION,
    CONF_CENSUS_DIVERGENCE_DOWNGRADE,
    DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE,
    # v3.10.1 Census v2
    CONF_ENHANCED_CENSUS,
    CONF_EGRESS_IDENTITY_ENABLED,
    DEFAULT_EGRESS_IDENTITY_ENABLED,
    CONF_CENSUS_HOLD_INTERIOR,
    CONF_CENSUS_HOLD_EXTERIOR,
    CONF_CENSUS_BLE_CANCEL_ENABLED,
    DEFAULT_CENSUS_BLE_CANCEL_ENABLED,
    DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES,
    DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES,
    # CENSUS-ACCURACY-1 D1 (2026-08-17): CENSUS_DECAY_STEP_SECONDS import
    # removed. The sole runtime reader (`_apply_hold_decay` house post-hold
    # linear decay slope) was deleted. The constant remains in const.py
    # tombstoned for grep-history clarity; do not re-import unless a new
    # explicit consumer is added.
    CENSUS_PEAK_SUSTAIN_SECONDS,
    CENSUS_FACE_RECOGNITION_WINDOW_SECONDS,
    EGRESS_FACE_UNION_TTL_S,
    FACE_MATCH_MIN_CONFIDENCE,
    FACE_NAME_LATCH_TTL_S,
    # FACE_MATCH_*_WINDOW_* consumed only by transit_validator; not
    # imported here (Review A-LOW-3).
    BLE_EGRESS_ENTRY_LEAD_S,
    BLE_EGRESS_EXIT_BACKFILL_WINDOW_S,
    BLE_EXIT_CLAIM_MAX_ATTEMPTS,
    BLE_EXIT_DEPARTURE_SETTLE_S,
    BLE_EXIT_PER_SLUG_COOLDOWN_S,
    BLE_TRANSITION_ONLY_CONFIDENCE,
    BLE_TRANSITION_CACHE_TTL_S,
    BLE_TRANSITION_CONFIDENCE,
    FACE_PRODUCER_STALE_TTL_S,
    CONF_KNOWN_FACE_GUESTS,
    DEFAULT_KNOWN_FACE_GUESTS,
    CONF_EGRESS_IDENTITY_FAILSAFE_STRICT,
    DEFAULT_EGRESS_IDENTITY_FAILSAFE_STRICT,
    CONF_GUEST_VLAN_SSID,
    DEFAULT_GUEST_VLAN_SSID,
    PHONE_HOSTNAME_PREFIXES,
    WIFI_GUEST_RECENCY_HOURS,
    NON_GUEST_HOSTNAME_PREFIXES,
    TABLET_HOSTNAME_PREFIXES,
)

_LOGGER = logging.getLogger(__name__)


async def _fire_camera_stuck_nm(
    hass: HomeAssistant, entity_id: str, count: int, hours: float,
    rule: str = "unchanged",
) -> None:
    """Fire Stuck-Signal D1 NM via the shared helper (per-day dedup).

    v5.36.1 FIX 2: `rule` distinguishes the trigger — "unchanged"
    (value held constant for STUCK_CAMERA_HOURS) vs "never_zero"
    (count stayed > 0 across value changes for STUCK_CAMERA_NEVERZERO_HOURS).
    Latch key includes the rule so an oscillating phantom that trips both
    rules still fires once per rule per day (operator visibility).
    """
    from .domain_coordinators._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
    if rule == "never_zero":
        diagnosis = (
            f"camera {entity_id} held person_count > 0 (last={count}) for "
            f"{hours:.1f}h with no interior corroboration (never-zero rule)"
        )
    else:
        diagnosis = (
            f"camera {entity_id} asserted person_count={count} for {hours:.1f}h "
            "with no interior corroboration"
        )
    await fire_stuck_signal(
        hass,
        kind="camera_stuck",
        key=(entity_id, rule),
        diagnosis=diagnosis,
        remedy="reload Frigate config entry",
    )


# Platform identifiers for Reolink and Dahua (not stored as named constants yet)
_CAMERA_PLATFORM_REOLINK = "reolink"
_CAMERA_PLATFORM_DAHUA = "dahua"


# ============================================================================
# DATACLASSES
# ============================================================================


@dataclass
class CameraInfo:
    """Information about a discovered camera entity."""

    entity_id: str
    platform: str  # "frigate" or "unifiprotect"
    area_id: str | None = None
    person_binary_sensor: str | None = None   # binary_sensor.*_person_occupancy or *_person_detected
    person_count_sensor: str | None = None    # sensor.*_person_count (Frigate only)


@dataclass
class CensusZoneResult:
    """Result for a single census zone (house or property)."""

    zone: str                           # "house" or "property"
    identified_count: int               # Known persons (face or BLE)
    identified_persons: list[str]       # List of person IDs
    unidentified_count: int             # Unknown persons (camera sees, cannot identify)
    total_persons: int                  # identified + unidentified
    confidence: str                     # "high", "medium", "low", "none"
    source_agreement: str               # "both_agree", "close", "disagree", "single_source"
    frigate_count: int                  # Raw Frigate count (if applicable)
    unifi_count: int                    # Raw UniFi count (if applicable)
    degraded_mode: bool = False         # True when primary platform (Frigate) is unavailable
    active_platforms: list[str] = field(default_factory=list)  # Platforms contributing data
    timestamp: datetime = field(default_factory=datetime.now)
    # v3.10.1 enhanced census attributes
    wifi_guest_floor: int = 0
    camera_unrecognized: int = 0
    peak_held: bool = False
    peak_age_minutes: int = 0
    face_recognized_persons: list[str] = field(default_factory=list)
    enhanced_census: bool = False
    # Cycle census_ble_cancel_unrecognized (2026-07-13): per-cycle diagnostic
    # count of unrecognized camera contributions cancelled by BLE area
    # correlation. Populated by ``_apply_enhanced_house_census`` from
    # ``PersonCensus._last_ble_cancelled_count``. Zero on the raw path and
    # whenever no cancellation occurred.
    ble_cancelled_count: int = 0


@dataclass
class FullCensusResult:
    """Combined house + property census."""

    house: CensusZoneResult                  # People inside the house
    property_exterior: CensusZoneResult      # People outside on property
    total_on_property: int                   # house.total + property_exterior.total
    ble_persons: list[str]                   # BLE-tracked person IDs (house only)
    face_persons: list[str]                  # Face-recognized person IDs (all zones)
    persons_outside: int                     # property_exterior.total (convenience)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class FaceLeg:
    """EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28): a single NAME-carrying
    face leg for the corroboration classifier in
    ``transit_validator._resolve_egress_face_identity``.

    Additive sibling of ``camera_resolver.DetectionLeg`` — shares the
    engine vocabulary (frigate / frigate2 / protect / protect2 / ...)
    so cross-camera + cross-engine agreement can be classified at the
    decision site.
    """
    entity_id: str
    engine: str
    device_id: str | None
    base_stem: str
    canonical_slug: str | None
    last_changed: datetime | None
    confidence: float | None


@dataclass(frozen=True)
class BleTransitionLeg:
    """A single BLE home<->away transition on one of a tracked
    resident's ``source_type == bluetooth_le`` device_trackers.

    Rev5 (EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1, 2026-09-05):
    the producer now subscribes DIRECTLY to the resident's bluetooth_le
    device_trackers (see
    :meth:`PersonCensus._derive_ble_crossing_trackers` +
    :meth:`PersonCensus._on_crossing_tracker_state_change`), NOT to
    ``person.<slug>`` (which was a lossy HA aggregate subject to the
    D-HIGH-1 GPS-race). Subscription IS the provenance gate — a
    non-bluetooth_le tracker is never subscribed, so wall tablets /
    GPS phones / camera_face-provenance updates cannot produce a leg.

    v1 = ENTRY-ONLY: only ``direction == "arriving"`` legs are
    produced. Exit attribution (departing legs → row UPDATE) is the
    deferred backfill card ``EGRESS-EXIT-IDENTITY-BACKFILL-1``.

    Sibling of :class:`FaceLeg`; consumed at the decision site by
    ``transit_validator._resolve_egress_face_identity``.
    """
    person_slug: str
    transition_ts: datetime
    direction: str  # "arriving" | "departing"
    engine: str  # always "ble"
    confidence: float
    provenance: str  # always "ble"
    source_entity: str


# ============================================================================
# CameraIntegrationManager
# ============================================================================


class CameraIntegrationManager:
    """Discover and manage camera entities from Frigate and UniFi Protect.

    Entity patterns confirmed from HA instance:

    Frigate:
      binary_sensor.{name}_person_occupancy   (device_class: occupancy)
      sensor.{name}_person_count              (person count)
      sensor.{name}_person_active_count       (active person count)

    UniFi Protect:
      binary_sensor.{name}_person_detected    (person detected binary)
      camera.{name}_high_resolution_channel   (video feed)

    Reolink:
      binary_sensor with "person" in name, platform == "reolink"

    Dahua:
      binary_sensor with "person" in name, platform == "dahua"

    Discovery strategy:
      1. Given a camera.* entity ID, resolve its device_id
      2. Find all binary_sensor entities on the same device
      3. Filter for person detection patterns by platform or name suffix
      4. For Frigate, find the matching sensor.*_person_count
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the camera integration manager."""
        self.hass = hass
        # area_id -> list[CameraInfo]
        self._cameras_by_area: dict[str, list[CameraInfo]] = {}
        # entity_id -> CameraInfo  (keyed by person_binary_sensor entity_id)
        self._camera_by_entity: dict[str, CameraInfo] = {}
        # entity_id -> platform str
        self._platform_by_entity: dict[str, str] = {}
        # device_id -> list[CameraInfo]  (cache to avoid re-resolving same device)
        self._resolved_devices: dict[str, list[CameraInfo]] = {}
        # B-HIGH-1 (2026-08-06): cache a SINGLE CameraResolver per manager;
        # invalidate via a dirty flag on registry-updated events instead of
        # re-constructing (and re-walking the entity+device registries) on
        # every `resolve_cross_platform_sensors` call. See `_get_resolver`
        # and `_register_registry_listeners`.
        self._resolver: Any = None
        self._resolver_dirty: bool = True
        self._resolver_unsubs: list = []
        self._resolver_listeners_registered: bool = False
        # B-LOW-1: crash counter for the broad resolver-crash fallback. First
        # crash is logged at ERROR (once per manager lifetime), subsequent
        # crashes at WARNING to avoid log flood while surfacing the initial
        # regression signal.
        self._resolver_crash_count: int = 0
        # EGRESS-CAMERA-DEAD-CONFIG-1 (2026-08-21): aggregate warn-once for
        # configured-but-missing camera entities. A stored config fact that
        # is re-checked every resolve tick must NOT re-log every tick (2,030
        # WARNINGs / 5h observed pre-fix). We log the first miss per entity
        # at WARNING (so operators can grep), then suppress until the entity
        # registry changes (`_register_registry_listeners` already flips
        # `_resolver_dirty` on EVENT_ENTITY_REGISTRY_UPDATED — we piggyback
        # via `_maybe_reset_unresolved`). We do NOT auto-substitute a `_N`
        # suffixed sibling — see PART C non-goal and
        # docs/planning/AUDIT_frigate_dead_leg_correctness.md L1.
        self._unresolved_warned: set[str] = set()
        # Public snapshot for the diagnostic sensor (Part B), keyed by
        # caller-supplied `scope` (typically the CONF_* list key). Each
        # scoped call to `resolve_configured_cameras` replaces its own slice
        # wholesale, so removal of an entity from stored config (the very
        # next operator action on this card: swap camera.garage_a →
        # camera.garage_a_2) is self-correcting on the next resolve tick.
        # A single flat dict would either flap across the three list callers
        # or need external knowledge of the union to prune correctly.
        self._unresolved_by_scope: dict[str, dict[str, str]] = {}

    def _register_registry_listeners(self) -> None:
        """B-HIGH-1: register EVENT_ENTITY/DEVICE_REGISTRY_UPDATED listeners
        that flip `_resolver_dirty=True`. Unsubs tracked (Bug Class #42:
        untracked listeners) — cleaned up in `async_shutdown`.
        """
        if self._resolver_listeners_registered:
            return
        try:
            from homeassistant.helpers.entity_registry import (  # noqa: PLC0415
                EVENT_ENTITY_REGISTRY_UPDATED,
            )
            from homeassistant.helpers.device_registry import (  # noqa: PLC0415
                EVENT_DEVICE_REGISTRY_UPDATED,
            )
        except Exception:  # noqa: BLE001 — running under test stubs w/o these
            return

        @callback
        def _invalidate(_evt) -> None:
            self._resolver_dirty = True
            # EGRESS-CAMERA-DEAD-CONFIG-1: clear warn-once set so an entity
            # that returns (or a new one that disappears) re-emits exactly
            # one WARNING on next resolve. Do NOT clear the per-scope
            # snapshots — each scoped `resolve_configured_cameras` call
            # rebuilds its own slice authoritatively.
            self._unresolved_warned.clear()

        try:
            self._resolver_unsubs.append(
                self.hass.bus.async_listen(EVENT_ENTITY_REGISTRY_UPDATED, _invalidate)
            )
            self._resolver_unsubs.append(
                self.hass.bus.async_listen(EVENT_DEVICE_REGISTRY_UPDATED, _invalidate)
            )
            self._resolver_listeners_registered = True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "CameraIntegrationManager: could not register registry-updated "
                "listeners for resolver cache invalidation: %s",
                exc,
            )

    def _get_resolver(self):
        """Return a cached CameraResolver, rebuilding on first use or when a
        registry-updated event has marked it dirty. See B-HIGH-1 note.
        """
        # Register listeners lazily on first use so pure-function unit tests
        # that never call this path aren't forced to stand up hass.bus.
        self._register_registry_listeners()
        if self._resolver is None or self._resolver_dirty:
            from .camera_resolver import CameraResolver  # noqa: PLC0415
            from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
            self._resolver = CameraResolver(
                er.async_get(self.hass),
                dr.async_get(self.hass),
                state_getter=lambda eid: self.hass.states.get(eid),
            )
            self._resolver_dirty = False
        return self._resolver

    async def async_shutdown(self) -> None:
        """Tear down cache-invalidation listeners (called from integration unload)."""
        for unsub in self._resolver_unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._resolver_unsubs = []
        self._resolver_listeners_registered = False
        self._resolver = None

    def resolve_camera_entity(self, camera_entity_id: str) -> list[CameraInfo]:
        """Resolve a camera.* entity ID to its person detection binary_sensors.

        Given a camera.* entity ID:
          1. Look up the entity in the registry to get its device_id
          2. Find ALL binary_sensor entities on that same device
          3. Filter for person detection patterns (Frigate, UniFi, Reolink, Dahua)
          4. For Frigate, also find the matching sensor.*_person_count on the device
          5. Return list of CameraInfo objects found

        Uses entity.platform from the registry as the authoritative way to identify
        the integration platform, falling back to name suffix matching if needed.

        Returns an empty list with a warning logged if the camera cannot be resolved.
        """
        ent_reg = er.async_get(self.hass)

        camera_entry = ent_reg.async_get(camera_entity_id)
        if camera_entry is None:
            # RECORDER-BLOAT-LOGFLOOD-1 (2026-08-21): warn-once per entity,
            # discharged when the entity returns to the registry. Same
            # `_unresolved_warned` set the `resolve_configured_cameras`
            # path uses (EGRESS-CAMERA-DEAD-CONFIG-1). Per-tick callers
            # (perimeter_alert.py:3805, `get_person_sensor`) were emitting
            # 1015 warnings each per garage_a/garage_b in a 5h window.
            if camera_entity_id not in self._unresolved_warned:
                self._unresolved_warned.add(camera_entity_id)
                _LOGGER.warning(
                    "Camera entity %s not found in entity registry — "
                    "skipping (further occurrences suppressed until "
                    "registry updates)",
                    camera_entity_id,
                )
            return []
        # Entity resolved — re-arm warn-once if it later disappears.
        self._unresolved_warned.discard(camera_entity_id)

        device_id = camera_entry.device_id
        if not device_id:
            _LOGGER.warning(
                "Camera entity %s has no device_id — cannot resolve person sensors",
                camera_entity_id,
            )
            return []

        # Return cached result if this device was already resolved
        if device_id in self._resolved_devices:
            return self._resolved_devices[device_id]

        # Find all binary_sensor entities on this device
        device_binary_sensors = [
            entity
            for entity in ent_reg.entities.values()
            if entity.device_id == device_id and entity.domain == "binary_sensor"
        ]

        # Find all sensor entities on this device (for Frigate person_count)
        device_sensors = [
            entity
            for entity in ent_reg.entities.values()
            if entity.device_id == device_id and entity.domain == "sensor"
        ]

        results: list[CameraInfo] = []

        for bs_entity in device_binary_sensors:
            bs_id = bs_entity.entity_id
            platform = bs_entity.platform or ""

            detected_platform: str | None = None

            # --- Person detection entity matching ---
            # Each platform requires BOTH platform match AND person-specific suffix/name
            # to avoid including motion, sound, and other non-person binary sensors.
            # CENSUS-SUFFIX-FIX: strip HA's `_N` disambiguation suffix
            # before suffix matching so `_2`-suffixed post-F1-retirement
            # entities are recognized. Real entity_id is stored below.
            bs_name_stripped = _strip_disambiguation_suffix(bs_id.split(".", 1)[1] if "." in bs_id else bs_id)
            if bs_name_stripped.endswith("_person_occupancy"):
                # Frigate person occupancy (definitive suffix match)
                detected_platform = CAMERA_PLATFORM_FRIGATE

            elif bs_name_stripped.endswith("_person_detected"):
                # UniFi Protect / generic person detected (definitive suffix match)
                if platform == CAMERA_PLATFORM_UNIFI:
                    detected_platform = CAMERA_PLATFORM_UNIFI
                elif platform == _CAMERA_PLATFORM_REOLINK:
                    detected_platform = _CAMERA_PLATFORM_REOLINK
                elif platform == _CAMERA_PLATFORM_DAHUA:
                    detected_platform = _CAMERA_PLATFORM_DAHUA
                else:
                    # Unknown platform but has person_detected suffix — treat as UniFi-like
                    detected_platform = CAMERA_PLATFORM_UNIFI

            elif (platform in (_CAMERA_PLATFORM_REOLINK, _CAMERA_PLATFORM_DAHUA)
                  and "person" in bs_entity.name.lower()):
                # Reolink/Dahua with non-standard naming but "person" in name
                detected_platform = platform

            else:
                # Not a person detection entity — skip
                continue

            # Build CameraInfo
            camera_info = CameraInfo(
                entity_id=bs_id,
                platform=detected_platform,
                area_id=bs_entity.area_id or camera_entry.area_id,
                person_binary_sensor=bs_id,
            )

            # For Frigate: also look for matching sensor.*_person_count on this device
            if detected_platform == CAMERA_PLATFORM_FRIGATE:
                # CENSUS-SUFFIX-FIX: strip HA `_N` from the binary's name
                # so the derived base is disambiguation-tolerant. Look for
                # canonical count first, then any `_N` variant. Store the
                # REAL entity_id.
                base_name = bs_name_stripped[:-len("_person_occupancy")]
                canonical_id = f"sensor.{base_name}_person_count"
                canonical = ent_reg.async_get(canonical_id)
                # Search device sensors for any *_person_count[_N] variant.
                fallback_id: str | None = None
                for s_entity in device_sensors:
                    s_name = s_entity.entity_id.split(".", 1)[1]
                    if _strip_disambiguation_suffix(s_name).endswith("_person_count"):
                        if s_entity.entity_id == canonical_id:
                            continue  # handled above
                        if fallback_id is None:
                            fallback_id = s_entity.entity_id
                if canonical is not None:
                    camera_info.person_count_sensor = canonical_id
                    if fallback_id is not None:
                        _LOGGER.warning(
                            "camera_census: both canonical (%s) and disambiguated (%s) person_count "
                            "sensors present on device %s; preferring canonical",
                            canonical_id, fallback_id, device_id,
                        )
                elif fallback_id is not None:
                    camera_info.person_count_sensor = fallback_id

            results.append(camera_info)

        if not results:
            _LOGGER.warning(
                "Camera entity %s (device_id=%s) has no person detection binary_sensors — "
                "no Frigate, UniFi Protect, Reolink, or Dahua person entities found on device",
                camera_entity_id,
                device_id,
            )

        # Cache by device_id to support deduplication
        self._resolved_devices[device_id] = results

        _LOGGER.debug(
            "Resolved camera %s (device_id=%s) -> %d person detection entities: %s",
            camera_entity_id,
            device_id,
            len(results),
            [r.entity_id for r in results],
        )

        return results

    def resolve_configured_cameras(
        self,
        camera_entity_ids: list[str],
    ) -> list[CameraInfo]:
        """Resolve a list of camera.* entity IDs to CameraInfo objects.

        Deduplicates by device_id: if two camera.* entities share the same device
        (e.g. high-res and medium-res channels), the device is only resolved once.

        Returns a flat list of all CameraInfo objects found.

        The diagnostic snapshot (EGRESS-CAMERA-DEAD-CONFIG-1) is populated by a
        separate scoped method (`record_unresolved_for_scope`) called from the
        stored-config caller, so that in-tree resolver-shape test stubs that
        pre-date the diagnostic remain signature-compatible.
        """
        seen_device_ids: set[str] = set()
        all_camera_infos: list[CameraInfo] = []

        ent_reg = er.async_get(self.hass)

        for camera_entity_id in camera_entity_ids:
            camera_entry = ent_reg.async_get(camera_entity_id)
            if camera_entry is None:
                # Part A: warn-once per entity; suppress until registry changes.
                if camera_entity_id not in self._unresolved_warned:
                    self._unresolved_warned.add(camera_entity_id)
                    _LOGGER.warning(
                        "Camera entity %s configured but not found in registry "
                        "— skipping (further occurrences suppressed until "
                        "registry updates; see Persons In House sensor "
                        "attribute 'unresolved_configured_cameras')",
                        camera_entity_id,
                    )
                continue
            # Entity resolved — allow it to re-warn if it later disappears.
            self._unresolved_warned.discard(camera_entity_id)

            device_id = camera_entry.device_id
            if not device_id:
                _LOGGER.warning(
                    "Camera entity %s has no device_id — skipping",
                    camera_entity_id,
                )
                continue

            # Deduplicate by device
            if device_id in seen_device_ids:
                _LOGGER.debug(
                    "Camera entity %s shares device_id=%s with a previously resolved camera — skipping duplicate",
                    camera_entity_id,
                    device_id,
                )
                continue

            seen_device_ids.add(device_id)
            infos = self.resolve_camera_entity(camera_entity_id)
            all_camera_infos.extend(infos)

        return all_camera_infos

    def record_unresolved_for_scope(
        self, scope: str, camera_entity_ids: list[str]
    ) -> None:
        """EGRESS-CAMERA-DEAD-CONFIG-1: replace the per-scope diagnostic
        snapshot for ``scope`` wholesale by walking the entity registry for
        the current configured list. Removing an entity from stored config
        (the operator's swap camera.garage_a -> camera.garage_a_2 flow) is
        self-correcting on the next tick — the next call for the same scope
        rebuilds a fresh slice. Empty lists clear the scope.

        Kept separate from `resolve_configured_cameras` to preserve the
        resolver's signature for in-tree test stubs that pre-date the
        diagnostic surface.
        """
        ent_reg = er.async_get(self.hass)
        slice_: dict[str, str] = {}
        for eid in camera_entity_ids:
            try:
                if ent_reg.async_get(eid) is None:
                    slice_[eid] = "not_in_registry"
            except Exception:  # noqa: BLE001 — registry stub variability
                continue
        if slice_:
            self._unresolved_by_scope[scope] = slice_
        else:
            self._unresolved_by_scope.pop(scope, None)

    def resolve_cross_platform_sensors(
        self,
        camera_entity_ids: list[str],
    ) -> list[CameraInfo]:
        """Resolve camera.* entities to person detection sensors across ALL platforms.

        Standard resolve_configured_cameras() only finds sensors on the same device
        as the camera.* entity. But a physical camera may have separate devices per
        integration (e.g. Frigate device + UniFi Protect device for the same camera).

        This method:
          1. Calls resolve_configured_cameras() to get device-matched sensors
          2. Extracts a name stem from each found sensor (e.g. "madrone_g6_entry")
          3. Searches the entity registry for sibling sensors on OTHER platforms:
             - binary_sensor.{stem}_person_detected
             - binary_sensor.{stem}_person_occupancy
             - binary_sensor.{stem}_person
             - sensor.{stem}_person_count
          4. Returns combined list, deduplicated by entity_id
        """
        # 2026-08-01 cutover: route through the new shared CameraResolver
        # when CENSUS_USE_NEW_RESOLVER=True (default). Fire-axe flag: flip
        # to False in a reviewed change to fall back to the legacy
        # name-stem-only path preserved below.
        try:
            from .camera_resolver import (  # noqa: PLC0415
                CENSUS_USE_NEW_RESOLVER, PLATFORM_FRIGATE, PLATFORM_UNIFI,
                resolve_area_id_for_entity, _strip_disambiguation_suffix,
                _strip_suffix, _entity_name, _PERSON_SUFFIXES,
            )
        except Exception:  # noqa: BLE001
            CENSUS_USE_NEW_RESOLVER = False
        if CENSUS_USE_NEW_RESOLVER:
            try:
                from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
                # B-HIGH-1: reuse the cached resolver; do NOT reconstruct.
                resolver = self._get_resolver()
                merged_infos: list[CameraInfo] = []
                # B-HIGH-2: dedup by (integration, resolved-device-id,
                # normalized-stem). Entity-id keyed dedup let F1 base
                # (`..._person_occupancy`) and F2 `_2`
                # (`..._person_occupancy_2`) emit as SEPARATE rows even
                # though they represent the same physical camera. Keying
                # off (integration, device_id, stem) collapses these while
                # preserving legitimate cross-integration siblings.
                seen_keys: set[tuple[str, str, str]] = set()
                ent_reg = er.async_get(self.hass)
                dev_reg = dr.async_get(self.hass)
                for cam_eid in camera_entity_ids:
                    _fusions = resolver.resolve_operator_declaration([cam_eid])
                    for src in [s for f in _fusions for s in f.sources]:
                        eid = src.person_binary_sensor
                        if not eid:
                            continue
                        # Normalize the stem (both orders: person-suffix
                        # first, then strip `_N`, then person-suffix again
                        # if the `_N` came after the person suffix).
                        _name = _entity_name(eid)
                        _stem = _strip_suffix(_name, _PERSON_SUFFIXES)
                        if _stem is None:
                            _pre = _strip_disambiguation_suffix(_name)
                            _stem = _strip_suffix(_pre, _PERSON_SUFFIXES) or _pre
                        _stem_norm = _strip_disambiguation_suffix(_stem or _name)
                        key = (src.integration or "", src.device_id or "", _stem_norm)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        # B-LOW-2 residual: default to CAMERA_PLATFORM_UNIFI
                        # only when integration is empty AND we cannot infer
                        # from the person_bs entity's `.platform`. This
                        # narrows the "unknown-integration → UNIFI" fallback
                        # to true unknowns; a Reolink/Dahua/Amcrest sibling
                        # is correctly labeled from its own `.platform`.
                        if src.integration == PLATFORM_FRIGATE:
                            plat = CAMERA_PLATFORM_FRIGATE
                        elif src.integration == PLATFORM_UNIFI:
                            plat = CAMERA_PLATFORM_UNIFI
                        elif src.integration:
                            plat = src.integration
                        else:
                            _ent = None
                            try:
                                _ent = ent_reg.async_get(eid)
                            except Exception:  # noqa: BLE001
                                _ent = None
                            _plat_attr = getattr(_ent, "platform", None) if _ent else None
                            # Residual: unknown-integration → UNIFI. This
                            # matches legacy's `platform or CAMERA_PLATFORM_UNIFI`
                            # default; kept for parity, narrowed to true
                            # unknowns by the branches above.
                            plat = _plat_attr or CAMERA_PLATFORM_UNIFI
                        # B-MED-1: legacy area precedence — entity.area_id,
                        # else device.area_id (via entity.device_id), else
                        # None. Guarded by helper.
                        _area = resolve_area_id_for_entity(ent_reg, dev_reg, eid)
                        merged_infos.append(CameraInfo(
                            entity_id=eid,
                            platform=plat,
                            area_id=_area,
                            person_binary_sensor=eid,
                            person_count_sensor=src.person_count_sensor,
                        ))
                if merged_infos:
                    _LOGGER.info(
                        "Cross-platform resolution (new-resolver): %d entities from %d cameras",
                        len(merged_infos), len(camera_entity_ids),
                    )
                    return merged_infos
                # Fall through to legacy if resolver returned nothing.
                _LOGGER.debug("CameraResolver returned no sources; falling back to legacy name-stem path")
            except Exception as exc:  # noqa: BLE001
                # B-LOW-1: escalate the FIRST resolver crash to ERROR (once
                # per manager lifetime), subsequent to WARNING. This surfaces
                # a resolver regression without flooding logs on repeated
                # bad-registry ticks.
                self._resolver_crash_count += 1
                if self._resolver_crash_count == 1:
                    _LOGGER.error(
                        "CameraResolver census cutover failed (%s); "
                        "using legacy path. Further crashes will log at WARNING "
                        "(count so far: %d).",
                        exc, self._resolver_crash_count,
                    )
                else:
                    _LOGGER.warning(
                        "CameraResolver census cutover failed (%s); "
                        "using legacy path (crash #%d this session).",
                        exc, self._resolver_crash_count,
                    )

        # Legacy path (preserved as fire-axe): standard resolution (same-device sensors)
        base_infos = self.resolve_configured_cameras(camera_entity_ids)
        seen_entity_ids = {info.entity_id for info in base_infos}
        additional: list[CameraInfo] = []

        ent_reg = er.async_get(self.hass)

        # Step 2-3: for each found sensor, extract stem and search for siblings
        for info in base_infos:
            stem = self._extract_camera_stem(info.entity_id)
            if not stem:
                continue

            # Sibling patterns to search for
            sibling_candidates = [
                (f"binary_sensor.{stem}_person_detected", "binary_sensor"),
                (f"binary_sensor.{stem}_person_occupancy", "binary_sensor"),
                (f"binary_sensor.{stem}_person", "binary_sensor"),
                (f"sensor.{stem}_person_count", "sensor"),
            ]

            for candidate_id, domain in sibling_candidates:
                if candidate_id in seen_entity_ids:
                    continue

                entry = ent_reg.async_get(candidate_id)
                if entry is None:
                    continue

                seen_entity_ids.add(candidate_id)

                if domain == "sensor":
                    # person_count sensor — attach to existing CameraInfo if possible
                    if info.person_count_sensor is None:
                        info.person_count_sensor = candidate_id
                    else:
                        # Already has one; create separate CameraInfo for tracking
                        additional.append(CameraInfo(
                            entity_id=candidate_id,
                            platform=entry.platform or CAMERA_PLATFORM_FRIGATE,
                            area_id=entry.area_id or info.area_id,
                            person_binary_sensor=None,
                            person_count_sensor=candidate_id,
                        ))
                else:
                    # binary_sensor sibling — determine platform
                    platform = entry.platform or ""
                    if candidate_id.endswith("_person_occupancy"):
                        detected_platform = CAMERA_PLATFORM_FRIGATE
                    elif candidate_id.endswith("_person_detected"):
                        detected_platform = CAMERA_PLATFORM_UNIFI if platform == CAMERA_PLATFORM_UNIFI else platform or CAMERA_PLATFORM_UNIFI
                    else:
                        detected_platform = platform or CAMERA_PLATFORM_UNIFI

                    additional.append(CameraInfo(
                        entity_id=candidate_id,
                        platform=detected_platform,
                        area_id=entry.area_id or info.area_id,
                        person_binary_sensor=candidate_id,
                    ))

        if additional:
            _LOGGER.info(
                "Cross-platform resolution found %d additional sensors: %s",
                len(additional),
                [a.entity_id for a in additional],
            )

        return base_infos + additional

    @staticmethod
    def _extract_camera_stem(entity_id: str) -> str | None:
        """Extract the camera name stem from a person detection entity_id.

        Examples:
          binary_sensor.madrone_g6_entry_person_occupancy -> madrone_g6_entry
          binary_sensor.madrone_g6_entry_person_detected  -> madrone_g6_entry
          sensor.madrone_g6_entry_person_count            -> madrone_g6_entry
        """
        # Remove domain prefix
        if "." not in entity_id:
            return None
        name = entity_id.split(".", 1)[1]

        # Known suffixes to strip
        for suffix in ("_person_occupancy", "_person_detected", "_person_count", "_person"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return None

    async def async_discover(
        self,
        room_cameras: list[str] | None = None,
        egress_cameras: list[str] | None = None,
        perimeter_cameras: list[str] | None = None,
    ) -> None:
        """Discover camera entities from configured camera.* entity lists.

        When camera lists are provided, resolves camera.* entity IDs to their
        person detection binary_sensors via the entity registry (device-based lookup).

        When no lists are provided, falls back to the legacy full-scan approach:
        scans ALL binary_sensor entities looking for Frigate and UniFi person
        detection suffixes.

        Builds internal lookup maps used by get_cameras_for_area(),
        get_platform_for_camera(), etc.
        """
        # Clear internal state
        self._cameras_by_area = {}
        self._camera_by_entity = {}
        self._platform_by_entity = {}
        self._resolved_devices = {}

        have_configured = any([room_cameras, egress_cameras, perimeter_cameras])

        if have_configured:
            await self._discover_from_configured_cameras(
                room_cameras=room_cameras or [],
                egress_cameras=egress_cameras or [],
                perimeter_cameras=perimeter_cameras or [],
            )
        else:
            await self._discover_full_scan()

    async def _discover_from_configured_cameras(
        self,
        room_cameras: list[str],
        egress_cameras: list[str],
        perimeter_cameras: list[str],
    ) -> None:
        """Build lookup maps from explicitly configured camera.* entity lists."""
        all_configured = list(set(room_cameras + egress_cameras + perimeter_cameras))
        all_infos = self.resolve_configured_cameras(all_configured)

        frigate_count = 0
        unifi_count = 0

        for camera_info in all_infos:
            entity_id = camera_info.entity_id

            # entity lookup (keyed by binary_sensor entity_id)
            self._camera_by_entity[entity_id] = camera_info
            self._platform_by_entity[entity_id] = camera_info.platform

            # area lookup
            area_id = camera_info.area_id or ""
            if area_id not in self._cameras_by_area:
                self._cameras_by_area[area_id] = []
            self._cameras_by_area[area_id].append(camera_info)

            if camera_info.platform == CAMERA_PLATFORM_FRIGATE:
                frigate_count += 1
            elif camera_info.platform == CAMERA_PLATFORM_UNIFI:
                unifi_count += 1

        _LOGGER.info(
            "Camera discovery complete (configured mode): %d Frigate, %d UniFi Protect entities found "
            "from %d configured camera entities",
            frigate_count,
            unifi_count,
            len(all_configured),
        )

    async def _discover_full_scan(self) -> None:
        """Legacy full-scan discovery: scan ALL binary_sensor entities in the registry.

        Identifies Frigate and UniFi Protect person detection entities by name suffix,
        then associates them with HA areas (rooms) for later lookup.
        """
        ent_reg = er.async_get(self.hass)

        frigate_sensors: list[CameraInfo] = []
        unifi_sensors: list[CameraInfo] = []

        for entity in ent_reg.entities.values():
            if entity.domain != "binary_sensor":
                continue

            entity_id = entity.entity_id
            platform = entity.platform or ""

            # CENSUS-SUFFIX-FIX: strip HA `_N` before suffix matching.
            eid_name_stripped = _strip_disambiguation_suffix(entity_id.split(".", 1)[1] if "." in entity_id else entity_id)
            # Frigate: platform == "frigate" OR binary_sensor.*_person_occupancy
            if platform == CAMERA_PLATFORM_FRIGATE or eid_name_stripped.endswith("_person_occupancy"):
                camera_info = CameraInfo(
                    entity_id=entity_id,
                    platform=CAMERA_PLATFORM_FRIGATE,
                    area_id=entity.area_id,
                    person_binary_sensor=entity_id,
                )
                # Try to find matching sensor.*_person_count (canonical first,
                # then any `_N` variant on the same base).
                base_name = eid_name_stripped[:-len("_person_occupancy")]
                canonical_id = f"sensor.{base_name}_person_count"
                if ent_reg.async_get(canonical_id):
                    camera_info.person_count_sensor = canonical_id
                else:
                    # Scan for `sensor.<base>_person_count_<N>` variants.
                    for cand in ent_reg.entities.values():
                        if cand.domain != "sensor":
                            continue
                        cand_name = cand.entity_id.split(".", 1)[1]
                        if not _strip_disambiguation_suffix(cand_name).endswith("_person_count"):
                            continue
                        stripped_base = _strip_disambiguation_suffix(cand_name)[:-len("_person_count")]
                        if stripped_base == base_name:
                            camera_info.person_count_sensor = cand.entity_id
                            break
                frigate_sensors.append(camera_info)

            # UniFi Protect: platform == "unifiprotect" OR binary_sensor.*_person_detected
            elif platform == CAMERA_PLATFORM_UNIFI or eid_name_stripped.endswith("_person_detected"):
                camera_info = CameraInfo(
                    entity_id=entity_id,
                    platform=CAMERA_PLATFORM_UNIFI,
                    area_id=entity.area_id,
                    person_binary_sensor=entity_id,
                )
                unifi_sensors.append(camera_info)

        for camera_info in frigate_sensors + unifi_sensors:
            # entity lookup
            self._camera_by_entity[camera_info.entity_id] = camera_info
            self._platform_by_entity[camera_info.entity_id] = camera_info.platform

            # area lookup
            area_id = camera_info.area_id or ""
            if area_id not in self._cameras_by_area:
                self._cameras_by_area[area_id] = []
            self._cameras_by_area[area_id].append(camera_info)

        _LOGGER.info(
            "Camera discovery complete (full-scan mode): %d Frigate, %d UniFi Protect entities found",
            len(frigate_sensors),
            len(unifi_sensors),
        )
        for camera_info in frigate_sensors:
            _LOGGER.debug(
                "Frigate camera: %s (area=%s, count_sensor=%s)",
                camera_info.entity_id,
                camera_info.area_id,
                camera_info.person_count_sensor,
            )
        for camera_info in unifi_sensors:
            _LOGGER.debug(
                "UniFi Protect camera: %s (area=%s)",
                camera_info.entity_id,
                camera_info.area_id,
            )

    def get_cameras_for_area(self, area_id: str) -> list[CameraInfo]:
        """Get all cameras (both platforms) covering a given HA area."""
        return self._cameras_by_area.get(area_id, [])

    def get_platform_for_camera(self, entity_id: str) -> str | None:
        """Return 'frigate' or 'unifiprotect' for a given camera entity_id."""
        return self._platform_by_entity.get(entity_id)

    def get_unresolved_configured_cameras(self) -> dict[str, str]:
        """Return {entity_id: reason} for configured cameras that failed to
        resolve on the most recent resolve pass for each scoped list (Part B
        of EGRESS-CAMERA-DEAD-CONFIG-1). Unions the per-scope snapshots so
        the caller sees a flat map across all three stored-config lists.
        Empty when every scoped resolve found all its entities. NEVER
        auto-substitutes suffixed siblings.
        """
        out: dict[str, str] = {}
        for slice_ in self._unresolved_by_scope.values():
            out.update(slice_)
        return out

    def get_all_frigate_cameras(self) -> list[CameraInfo]:
        """Return all discovered Frigate camera entities."""
        return [c for c in self._camera_by_entity.values() if c.platform == CAMERA_PLATFORM_FRIGATE]

    def get_all_unifi_cameras(self) -> list[CameraInfo]:
        """Return all discovered UniFi Protect camera entities."""
        return [c for c in self._camera_by_entity.values() if c.platform == CAMERA_PLATFORM_UNIFI]

    def has_cameras(self) -> bool:
        """Return True if any cameras have been discovered."""
        return bool(self._camera_by_entity)

    def get_person_sensor_for_area(self, area_id: str) -> list[str]:
        """Return person detection binary_sensor entity_ids for all cameras in an area.

        Convenience helper for coordinator.py occupancy extension:
        iterates CameraInfo objects for the area and returns their
        person_binary_sensor entity IDs (non-None only).
        """
        camera_infos = self.get_cameras_for_area(area_id)
        return [
            info.person_binary_sensor
            for info in camera_infos
            if info.person_binary_sensor
        ]

    def get_person_sensor(self, camera_entity_id: str) -> str | None:
        """Return the resolved person detection binary_sensor for a camera entity ID.

        Accepts either a camera.* entity ID or a binary_sensor entity ID.
        For binary_sensor IDs that are already tracked, returns person_binary_sensor.
        For camera.* IDs, resolves via the entity registry if not already cached.
        Returns None if no person detection sensor can be found.
        """
        # Fast path: already in the keyed-by-entity map (binary_sensor entity_id)
        if camera_entity_id in self._camera_by_entity:
            return self._camera_by_entity[camera_entity_id].person_binary_sensor

        # Try resolving as a camera.* entity_id
        infos = self.resolve_camera_entity(camera_entity_id)
        if infos:
            return infos[0].person_binary_sensor

        return None


# ============================================================================
# PersonCensus
# ============================================================================


class PersonCensus:
    """Dual-zone person census engine.

    Two census zones:

    House zone:
      Sources: interior room cameras (CONF_CAMERA_PERSON_ENTITIES per room) + BLE
      Counts: people inside the house
      Method: aggregate Frigate counts, validate against UniFi presence,
              cross-correlate with BLE person_coordinator data

    Property zone:
      Sources: egress + perimeter cameras (integration-level config)
      Counts: people outside but on the property (yard, driveway, porch)
      Method: any person detection on egress or perimeter cameras

    The two zones are independent. total_on_property = house + property_exterior.

    Cross-validation:
      When CONF_CENSUS_CROSS_VALIDATION is True (default), multi-platform
      cross-validation is used and confidence is derived from platform agreement.
      When False, only the FIRST person detection entity per device is used,
      cross-validation is skipped, and confidence is always "medium".
    """

    def __init__(
        self,
        hass: HomeAssistant,
        camera_manager: CameraIntegrationManager,
    ) -> None:
        """Initialize the PersonCensus."""
        self.hass = hass
        self._camera_manager = camera_manager
        self._last_result: FullCensusResult | None = None
        self._update_lock = asyncio.Lock()
        # v4.2.6: Defer census DB writes during startup to reduce write queue contention
        self._created_at: datetime = dt_util.now()
        # v4.2.8: Write throttle — DB write every 4th cycle (~120s)
        self._census_write_counter: int = 0

        # v3.10.1 Census v2: hold/decay state
        self._peak_house_camera_count: int = 0
        self._peak_house_timestamp: datetime | None = None
        self._peak_property_count: int = 0
        self._peak_property_timestamp: datetime | None = None

        # v5.9.0 D-B: sustain-before-latch pending state. A fresh_count above
        # the stored peak enters a pending state timestamped `now`; it only
        # promotes to `peak` after CENSUS_PEAK_SUSTAIN_SECONDS have elapsed
        # AND fresh_count has stayed >= pending value across the interval.
        # If fresh_count dips before the sustain window elapses, pending is
        # cleared and the current lower peak stands. Per-zone parity with
        # the existing peak fields.
        self._pending_house_peak: int = 0
        self._pending_house_peak_since: datetime | None = None
        self._pending_property_peak: int = 0
        self._pending_property_peak_since: datetime | None = None

        # CENSUS-ACCURACY-1 D1 (2026-08-17): LIFETIME monotonic counter that
        # increments each tick where the deleted `fresh_count == peak`
        # self-refresh would previously have fired. Published on
        # SIGNAL_CENSUS_UPDATED + persons_in_house attrs as the positive
        # discriminator for the empty-house acceptance test (proves the
        # deleted code path IS on the wire, not merely absent from output).
        self._peak_refresh_suppressed_count: int = 0
        # CENSUS-ACCURACY-1 D2 (2026-08-17): PER-TICK counter of face-sensor
        # lookups that failed to resolve either the un-suffixed or
        # `_2`-suffixed entity_id. Reset at the top of every census cycle.
        # Published on SIGNAL_CENSUS_UPDATED + attrs so operators can tell
        # whether a tick's face-dedup path was healthy.
        self._face_lookup_missing_count: int = 0
        # CENSUS-ACCURACY-1 D2: build-time enumerated map from frigate face
        # library person name (lowercased) -> live `frigate_*_last_camera`
        # entity_id. Memoised on first use; the enumeration is small
        # (~5 entries). None sentinel means "not yet built".
        self._frigate_person_last_camera_map: dict[str, str] | None = None
        # CENSUS-ACCURACY-1 D1 review fix-up (B-MEDIUM-1): cached
        # dispatch-time freshness stamps so the persons_in_house sensor
        # attr and the SIGNAL_CENSUS_UPDATED payload carry the identical
        # instant (previously two clocks stamped the same key).
        self._last_count_as_of: str | None = None
        self._last_peak_age_seconds: int = 0

        # v5.9.0 D-A / D-E observability: last computed area-contribution map
        # for the interior (house) census, and the pre-dedup naive sum. Read
        # by the census sensor's extra_state_attributes.
        self._last_area_contributions: dict[str, dict[str, Any]] = {}
        self._last_raw_pre_dedup_sum: int = 0

        # GUEST-CENSUS D1 (2026-08-16): PRE-BLE-cancel diagnostics + clamp
        # ceiling scalar. Published at Step 2 of _get_unrecognized_camera_count
        # so INV-CENSUS-ATTRIBUTION has a ceiling that does NOT drop when
        # BLE-cancel repairs (reviewer counter-example, plan-review P1). The
        # four *_pre_cancel/_ble_* attributes let observability discriminate
        # "BLE-cancel ran and cancelled zero" from "BLE-cancel never ran".
        self._last_camera_total_pre_cancel: int = 0
        self._last_area_raw_max_pre_cancel: dict[str, int] = {}
        self._last_ble_by_area: dict[str, int] = {}
        self._last_ble_cancel_enabled: bool = False
        # Enhanced-path per-area contributions POST-cancel (distinct from the
        # raw producer's ``_last_area_contributions`` above). Published so the
        # census sensor's ``area_contributions`` attr can show what actually
        # fed camera_unrecognized on the enhanced path.
        self._last_enhanced_area_contributions: dict[str, int] = {}

        # Cycle census_ble_cancel_unrecognized (2026-07-13): last per-cycle
        # BLE-cancellation total. Written at the END of
        # ``_get_unrecognized_camera_count`` so that any mid-cycle exception
        # leaves the prior value intact (rather than a partial half-count);
        # read by ``_apply_enhanced_house_census`` to populate the
        # ``ble_cancelled_count`` diagnostic on the returned CensusZoneResult.
        # Seed here so the attribute is always defined even before the first
        # enhanced-census cycle runs (avoids AttributeError on the raw path
        # or if the enhanced path takes an early-return during setup).
        self._last_ble_cancelled_count: int = 0

        # EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 (2026-08-18): egress-face
        # identity register. Names are stored in the Frigate first-name
        # slug namespace (see `_normalize_person_name`) so I5 dedup at the
        # census union sites cannot admit "Oji" and "oji" as two members.
        # TTL-pruned on read against EGRESS_FACE_UNION_TTL_S. Fed by
        # `transit_validator.EgressDirectionTracker._resolve_direction`
        # via `register_egress_face`; consumed at BOTH census union
        # writers (`:1855` raw and the enhanced house recompute) per
        # plan-review C-CRIT-1.
        self._egress_face_ids: dict[str, datetime] = {}
        # D-MED-2 (2026-08-18): once-per-ambiguous-head warning tracker
        # for `_canonical_person_slug`. Set of first-name heads where
        # tracked_persons has >1 matching slug; we warn on the first
        # collision, then fail-CLOSED silently for subsequent lookups.
        self._canonicalizer_ambiguity_warned: set[str] = set()

        # EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28): D3 observability.
        # Bounded rolling window of egress-identity outcomes for
        # attach_rate_24h / ambiguity_rate_24h math read synchronously
        # from the census sensor (sensor.py cannot await a DAO).
        # entries: (monotonic-or-wall ts_seconds, outcome_str).
        # outcome in {"attached", "ambiguous", "no_leg", "disabled"}.
        # Pruned on every append: pop-left while now - ts > 24h.
        self._egress_identity_outcomes: deque[tuple[float, str]] = deque(maxlen=8192)
        # MED-3 (2026-08-28): abstain is now a deque-derived rate — the
        # separate int counter + broken day-rollover has been removed;
        # "abstain" is a distinct outcome label in the SAME deque.
        # BOTH stamped at BOOST (not HIGH) event ledger, 24h-filtered.
        self._egress_identity_boost_events: deque[float] = deque(maxlen=1024)
        # Last successful attach + last agreement class.
        self._egress_identity_last_attach: dict[str, Any] = {}
        self._egress_identity_agreement_class_last: str | None = None

        # ------------------------------------------------------------------
        # Stuck-Signal Watchdog D1 (v5.35.0). Per-Frigate-camera state for the
        # census-layer stuck-count check. See
        # docs/planning/PLANNING_stuck_signal_watchdog.md.
        #
        # For each configured Frigate camera we track:
        #   `since` — first wall-clock ts we observed person_count > 0 in the
        #             current continuous run (reset whenever count returns to 0).
        #   `last_value` — most recently observed person_count (for the
        #             unchanged-value branch of the stuck window).
        #   `last_change` — wall-clock ts of the most recent VALUE change of
        #             person_count (any transition, including 0->N and N->M).
        #             The stuck window is measured from this stamp so a value
        #             that toggles between two non-zero values does NOT trip
        #             the unchanged rule.
        #   `duty_ring` — deque of (monotonic_seconds, bool_on) samples over
        #             the last CONF_STUCK_CAMERA_DUTYCYCLE_WINDOW window
        #             (D2 duty-cycle sibling; presently unused at the census
        #             layer — Fix #9 duty-cycle lives at coordinator.py.)
        # Fail-open: entire watchdog is wrapped in try/except at the call site;
        # if this dict grows stale it can only cause the discount to skip.
        self._camera_stuck_state: dict[str, dict[str, Any]] = {}
        # Published diagnostic list (list of dicts) for the census sensor's
        # `stuck_cameras` attribute — see URAPersonsInHouseSensor. Populated by
        # `_watchdog_stuck_cameras` on every census tick; empty on healthy.
        self._last_stuck_cameras: list[dict[str, Any]] = []
        # Set of Frigate camera entity_ids to DISCOUNT from the interior
        # census this tick. Consumed by `_calculate_house_census` — populated
        # by `_watchdog_stuck_cameras` after the corroboration check.
        self._watchdog_discounted_cameras: set[str] = set()
        # FIX 5 (A-HIGH-2) 2026-07-28: one-time WARN dedup for null-area
        # cameras. Grows bounded by camera count; entries persist for the
        # process lifetime (deliberate — one WARN per problem camera).
        self._null_area_warned: set[str] = set()

        # EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 rev5 (2026-09-05):
        # BLE-transition leg cache. Fed by
        # `_on_crossing_tracker_state_change`, which is subscribed only
        # to the resident device_trackers whose live source_type is
        # `bluetooth_le` (see `_derive_ble_crossing_trackers`).
        # Pruned on read against BLE_TRANSITION_CACHE_TTL_S. Deque is
        # bounded so a runaway producer can never blow the heap.
        self._ble_transition_cache: deque[BleTransitionLeg] = deque(maxlen=256)
        # Cancellers for the tracker-id state_changed listener registered
        # by `_register_ble_transition_listeners` (and re-registered by
        # `_refresh_ble_crossing_listeners` under the boot-race path);
        # drained by `async_teardown_ble_transition_listeners` at unload.
        self._ble_transition_unsubs: list[Any] = []
        # tracker_id -> slug map built by `_derive_ble_crossing_trackers`
        # and read by the edge handler to attribute the edge to a slug.
        self._ble_tracker_slug_map: dict[str, str] = {}
        # rev5 D3 observability counters — the ONLY signals distinguishing
        # working from dead post-re-arch (the old provenance counter is
        # retired: subscription is now the gate).
        self._ble_edge_dropped_invalid_count: int = 0
        self._ble_departing_edge_seen_count: int = 0
        self._ble_legs_produced_count: int = 0
        self._ble_legs_attached_count: int = 0
        self._ble_legs_abstained_count: int = 0
        # Rev5 fix-up (D-7): benign edges (first-write / old_state=None
        # / legitimate zone->zone) are counted here, NOT under
        # `_ble_edge_dropped_invalid_count`, so the latter reflects
        # forgery-shaped drops only.
        self._ble_edge_dropped_benign_count: int = 0
        # FRIGATE-SUBLABEL-FACE-BRIDGE-1 (2026-09-06) D1: URA-owned
        # Frigate face-NAME latch. Fed by the MQTT bridge
        # (`_on_frigate_face_msg` on `frigate/tracked_object_update`
        # where type=="face"); read by `_resolve_face_legs` to emit a
        # synthetic FaceLeg when the Frigate integration's
        # `sensor.*_last_recognized_face[_2]` has already reset (its
        # `async_call_later(60s)` latch-reset bug). Additive: never
        # replaces a live entity leg. Pruned on read/write against
        # `FACE_NAME_LATCH_TTL_S`. Fail-safe INHERITED via
        # `transit_validator._resolve_egress_face_identity` (leg-drop
        # under drill / producer outage) — no gate added here.
        # Key: URA base_stem. Value: (canonical_name_raw, utcnow ts).
        self._frigate_face_latch: dict[str, tuple[str, datetime]] = {}
        # MQTT subscription unsub callable (populated by
        # `async_register_frigate_face_listener`, drained by
        # `async_teardown_frigate_face_listener`). None when MQTT is
        # not loaded or subscribe raised — bridge is inert then.
        self._frigate_face_unsub: Any = None
        # D3 observability counters.
        self._frigate_face_msg_seen_count: int = 0
        # D-LOW-1: face-only counter (all-traffic counter is above);
        # incremented ONLY when `type=="face"` so live validation has
        # an honest face-yield signal independent of person/etc chatter.
        self._frigate_face_msg_face_count: int = 0
        self._frigate_face_msg_dropped_count: int = 0
        # B-MED: memoize camname -> latch base_stems (derived from the
        # entity registry face-sensor scan on the resolved device_ids).
        # Invalidated by rebinding when the underlying CameraResolver
        # instance changes (id(resolver) mismatch — resolver itself is
        # rebuilt whenever `_resolver_dirty` flips on
        # EVENT_ENTITY_REGISTRY_UPDATED / EVENT_DEVICE_REGISTRY_UPDATED).
        self._frigate_face_camname_cache: dict[str, list[str]] = {}
        # D2-LOW-2: hold a direct reference (not id()) so address reuse
        # of a freed resolver cannot inherit a stale cache. weakref
        # preferred to avoid extending resolver lifetime; falls back to
        # a strong ref if the resolver type disallows weakrefs.
        self._frigate_face_camname_cache_resolver_ref: Any = None
        # Last successful latch write (base_stem, canonical_name_raw, ts)
        # — for the persons-in-house sensor.
        self._frigate_face_last_latched: tuple[str, str, datetime] | None = None
        # One-time WARN latch for slugs that derive ZERO bluetooth_le
        # trackers (fatal for oji, who has only one BLE tracker).
        self._ble_zero_tracker_warned: set[str] = set()
        # EGRESS-EXIT-IDENTITY-BACKFILL-1 (2026-09-05) — rebuilt fresh
        # each `_derive_ble_crossing_trackers` pass. Names the tracked
        # residents currently BLE-invisible (0 bluetooth_le trackers
        # this pass). Consumed by `_backfill_exit_identity` as the
        # cross-resident abstain guard (invariant e). MUST NOT be
        # unioned with `_ble_zero_tracker_warned` (that latch never
        # clears → permanent abstain after one boot blip).
        self._ble_zero_tracker_slugs: set[str] = set()
        # EGRESS-EXIT-IDENTITY-BACKFILL-1 — tracked async backfill
        # tasks scheduled from the (sync) departing-edge callback.
        # Cancelled in `async_cancel_pending_backfill_tasks` (invoked
        # from the entry-unload path ONLY — NOT from listener refresh /
        # teardown, which would kill in-flight settle sleeps mid-flap
        # remediation).
        self._backfill_tasks: set[asyncio.Task] = set()
        # EGRESS-EXIT-IDENTITY-BACKFILL-1 — D3 observability counters.
        self._ble_exit_backfilled_count: int = 0
        self._ble_exit_edge_no_match_count: int = 0
        self._ble_exit_ambiguity_abstain_count: int = 0
        # Fix-up (2026-09-05) — additional exclusive-attribution guards.
        # Incremented when a settle re-read finds the tracker back in a
        # home state (flap, not real departure).
        self._ble_exit_flap_aborted_count: int = 0
        # Incremented when the DAO returns False (contended: row already
        # named by a concurrent write). Keeps counter sum reconcilable
        # against edges-reaching-DAO.
        self._ble_exit_backfill_noop_count: int = 0
        # D-LOW (counter-honesty, 2026-09-05): silent-return paths that
        # were previously invisible to the edges-reaching-DAO
        # reconciliation (`database is None`, SELECT exception, UPDATE
        # exception, task-schedule failure).
        self._ble_exit_error_count: int = 0
        # Incremented when the same slug's cooldown suppresses a
        # duplicate departing edge (multi-tracker resident: phone +
        # watch fire two edges from one physical departure).
        self._ble_exit_per_slug_cooldown_skipped_count: int = 0
        # EGRESS-EXIT-COMULTI-DEPART-1 (2026-09-06) — retry-claim
        # observability. `row_contention_retry` = re-SELECT attempts
        # made after the DAO's IS-NULL claim lost to a concurrent
        # edge (each retry claims a DIFFERENT next-nearest null row).
        # `row_lost` = the retry loop exhausted OR the re-SELECT
        # went empty after we lost the IS-NULL claim to a concurrent
        # writer AND this edge has no own crossing to bind. This is
        # the honest name (renamed 2026-09-06, A-3/D-2): the counter
        # measures "row was named by someone else while we tried" —
        # it does NOT specifically discriminate face-vs-BLE, since
        # the concurrent writer could be another BLE edge, a face
        # resolver, or any future writer. True face-vs-BLE
        # disagreement measurement requires provenance
        # discrimination — follow-up work, do NOT build here.
        # Keep-face+flag+measure: we never overwrite a claimed row.
        self._ble_exit_row_contention_retry_count: int = 0
        self._ble_exit_row_lost_count: int = 0
        # Per-slug cooldown timestamps (naive-UTC) — set when a slug
        # processes a departing edge (backfill OR abstain), read on
        # subsequent same-slug edges.
        self._ble_exit_last_edge_by_slug: dict[str, datetime] = {}
        # Rev5 fix-up (D-1a): sticky classification. Once a tracker in
        # a resident's `device_trackers` has been observed with
        # `source_type == "bluetooth_le"` while available, keep it in
        # the subscription set even while it flips to `unavailable`
        # (HA does not expose attributes on unavailable entities, so
        # a live-only re-classification would silently unsubscribe).
        # Removed only when the tracker leaves the person's
        # `device_trackers` OR is confirmed a different source_type
        # while available. Map: tracker_id -> slug.
        self._known_ble_trackers: dict[str, str] = {}
        # Rev5 fix-up (A-LOW-2): one-time WARN latch for a tracker_id
        # that derives to two different slugs (silent last-writer-wins
        # would be a data-quality bug).
        self._ble_tracker_id_collision_warned: set[str] = set()

        # D4 §0 fail-safe surface. Drill flag lives on
        # ``hass.data[DOMAIN]["face_drill_forced"]`` (Review DL-1) so an
        # INTEGRATION reload that rebuilds ``PersonCensus`` does NOT
        # silently release the drill. See ``get_face_drill_forced()`` /
        # ``set_face_drill_forced()`` classmethods below. Reason string
        # is per-instance (last read populates it) — pure diagnostic.
        self._face_producer_health_reason: str = "live"
        # Cached resolution of the Frigate health entity (Review FS-1
        # / A-CRIT-1). Entity is resolved via the entity registry, not
        # a string-built `_2` id (memory reference_frigate1_retired
        # _2suffix_permanent). ``_face_producer_health_entity is None``
        # after resolution means "genuinely unconfigured" (Frigate not
        # present) — inert, one-time WARNING at first resolve.
        self._face_producer_health_entity: str | None = None
        self._face_producer_health_resolved: bool = False
        self._face_producer_startup_warned: bool = False
        # D4 telemetry counters — split into two units per Review
        # OB-1 / A-MED-1. Census counter is per-TICK (incremented at
        # most once per census cycle when a face_recognized feed is
        # suppressed); tracker counter (`transit_validator`) is per-LEG.
        self._face_dropped_producer_down_ticks: int = 0
        self._face_dropped_stale_count: int = 0
        self._face_dropped_drill_forced_count: int = 0

        # D3 / H1: guest-namespace egress registrations kept SEPARATE from
        # the resident bucket so `identified_count` (resident scope) is
        # never inflated by a `guest:*` slug (v5.16-class regression
        # surface — see feedback_cross_investigation_synthesis.md).
        self._egress_guest_ids: dict[str, datetime] = {}
        # D4: provenance ledger for `_egress_face_ids` — a face-provenance
        # register-time entry is suppressed at read time when
        # `_is_face_producer_live()` is False; a ble-provenance entry is
        # not. Keys mirror `_egress_face_ids`; values are "face" or "ble".
        self._egress_face_ids_provenance: dict[str, str] = {}
        # H1: last computed identified-guests tally (used by census
        # sensor observability; enhanced-path writer stamps this).
        self._last_identified_guests_count: int = 0

    # ------------------------------------------------------------------
    # Transit detection helpers (cross-platform)
    # ------------------------------------------------------------------

    def get_transit_egress_entities(self) -> list[CameraInfo]:
        """Return cross-platform CameraInfo for configured egress cameras."""
        raw_cameras = self._get_raw_camera_list(CONF_EGRESS_CAMERAS)
        if not raw_cameras:
            return []
        return self._camera_manager.resolve_cross_platform_sensors(raw_cameras)

    def get_transit_interior_entities(self) -> list[CameraInfo]:
        """Return cross-platform CameraInfo for configured interior cameras."""
        raw_cameras = self._get_raw_camera_list(CONF_CAMERA_PERSON_ENTITIES)
        if not raw_cameras:
            return []
        return self._camera_manager.resolve_cross_platform_sensors(raw_cameras)

    def _get_raw_camera_list(self, conf_key: str) -> list[str]:
        """Read raw camera.* entity IDs from the integration config entry."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return merged.get(conf_key, [])
        return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def async_update_census(self) -> FullCensusResult:
        """Calculate both census zones from all available sources.

        Returns a FullCensusResult. Always returns a valid result;
        falls back to BLE-only or zero data gracefully if cameras
        are unavailable or not configured.

        Uses an asyncio lock to prevent concurrent mutations of
        peak hold/decay state from overlapping periodic + event triggers.
        """
        async with self._update_lock:
            return await self._async_update_census_locked()

    async def _async_update_census_locked(self) -> FullCensusResult:
        """Inner census update (must be called under self._update_lock)."""
        now = dt_util.utcnow()

        # rev5 D1 boot-race re-register: cheap idempotent set-diff on
        # the bluetooth_le tracker family. Picks up any tracker whose
        # integration loaded AFTER URA (state was None at setup).
        try:
            self._refresh_ble_crossing_listeners()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "rev5 BLE listener refresh raised (non-fatal)",
                exc_info=True,
            )

        # CENSUS-ACCURACY-1 D2: per-tick reset of face-lookup miss counter.
        # LIFETIME peak_refresh_suppressed_count is NOT reset here.
        self._face_lookup_missing_count = 0

        # --- 1. Gather BLE person data from person_coordinator ---
        ble_persons = self._get_ble_persons()

        # Stuck-Signal Watchdog D1 (v5.35.0) — runs UPSTREAM of the raw
        # camera tally so `_calculate_house_census` observes the discount
        # BEFORE it feeds C7's peak/decay state machine (this is the
        # exact cross-coupling that made the 2026-07-28 foyer incident
        # 11h silent — a stuck count IS fresh so C7's floor never aged).
        # Fail-open: any exception clears the discount set, restoring
        # byte-identical pre-watchdog behavior.
        try:
            self._watchdog_stuck_cameras(now)
        except Exception:  # noqa: BLE001 — fail-open (#7 accumulator pattern)
            _LOGGER.debug(
                "Stuck-signal watchdog raised (swallowed; census unchanged)",
                exc_info=True,
            )
            self._watchdog_discounted_cameras = set()
            self._last_stuck_cameras = []

        # --- 2. House census ---
        house_result = await self._calculate_house_census(ble_persons, now)

        # --- 3. Property (exterior) census ---
        property_result = await self._calculate_property_census(now)

        # --- 3.5. Apply enhanced census v2 (if enabled) ---
        if self._is_enhanced_census_enabled():
            house_result = self._apply_enhanced_house_census(
                house_result, ble_persons, now
            )
            property_result = self._apply_enhanced_property_census(
                property_result, now
            )

        # --- 4. Combine ---
        total_on_property = house_result.total_persons + property_result.total_persons

        result = FullCensusResult(
            house=house_result,
            property_exterior=property_result,
            total_on_property=total_on_property,
            ble_persons=ble_persons,
            face_persons=list(set(house_result.identified_persons + property_result.identified_persons)),
            persons_outside=property_result.total_persons,
            timestamp=now,
        )

        self._last_result = result

        _LOGGER.debug(
            "Census complete: house=%d (identified=%d, unidentified=%d, confidence=%s), "
            "property=%d, total=%d",
            house_result.total_persons,
            house_result.identified_count,
            house_result.unidentified_count,
            house_result.confidence,
            property_result.total_persons,
            total_on_property,
        )

        # v3.6.0-c2.3: Dispatch census signal for PresenceCoordinator.
        # Without this, _census_count stays 0 and house state is always "away".
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .domain_coordinators.signals import SIGNAL_CENSUS_UPDATED
        # GAP-A D8 (PATH-ALPHA, 2026-08-16): add face_recognized_count so
        # path α can gate on camera-provable identity evidence instead of
        # BLE-inflated census_count. See PLANNING_gap_a_census_hole.md +
        # AUDIT_tracking_status_consumers.md §D8. Source: face_recognized
        # is the camera-only identity set (list[str]) derived from Frigate
        # face-recognition sensors, subject to the person-tracker cross-
        # check at camera_census.py:3034-3055 (drops faces whose person.<slug>
        # says not_home; fail-OPEN if the person entity is missing —
        # documented upper bound, not addressed here). Freshness window
        # is CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800s (const.py:2609).
        _face_recognized = getattr(house_result, "face_recognized_persons", []) or []
        # CENSUS-ACCURACY-1 D1 (payload extension, INV-PAYLOAD-DISCRIMINABLE).
        # Review fix-up 2026-08-18:
        #   * B-MEDIUM-1 — `count_as_of` was stamped at dispatch time in the
        #     payload but at attr-read time in the sensor. Same key name,
        #     different clocks. Stamp ONCE here and cache on the instance;
        #     the sensor reads the cached value so payload and attr are the
        #     identical instant.
        #   * B-MEDIUM-2 — `peak_age_seconds` previously = int(minutes) * 60,
        #     which is 60× coarser than the name implies and defeats
        #     short-window discrimination. Compute a real second-precision
        #     value from the stored peak timestamp against the SAME utcnow
        #     used for `count_as_of`.
        _dispatch_utcnow = dt_util.utcnow()
        _count_as_of_iso = _dispatch_utcnow.isoformat()
        _peak_age_seconds = self._compute_peak_age_seconds(
            self._peak_house_timestamp,
            bool(getattr(house_result, "peak_held", False)),
            _dispatch_utcnow,
        )
        # Cache so the sensor attr can carry the identical instant.
        self._last_count_as_of = _count_as_of_iso
        self._last_peak_age_seconds = _peak_age_seconds
        async_dispatcher_send(
            self.hass,
            SIGNAL_CENSUS_UPDATED,
            {
                "interior_count": house_result.total_persons,
                "identified_count": house_result.identified_count,
                "unidentified_count": house_result.unidentified_count,
                "property_count": property_result.total_persons,
                "total_on_property": total_on_property,
                # v4.6.2.2: Census confidence fields for guest-mode hardening gate
                "confidence": house_result.confidence,
                "source_agreement": house_result.source_agreement,
                # GAP-A D8: camera-only identity count for path-α veto.
                "face_recognized_count": len(_face_recognized),
                # CENSUS-ACCURACY-1 D1 payload extension (INV-PAYLOAD-DISCRIMINABLE).
                "peak_held": bool(getattr(house_result, "peak_held", False)),
                "peak_age_seconds": _peak_age_seconds,
                "count_as_of": _count_as_of_iso,
                "peak_refresh_suppressed_count": (
                    self._peak_refresh_suppressed_count
                ),
                "face_lookup_missing_count": self._face_lookup_missing_count,
            },
        )

        # D5: Log census snapshots to database
        # v4.2.6: Skip DB writes during startup grace period (5 min)
        # v4.2.8: Write every 4th cycle (~120s) instead of every cycle (~30s).
        # Census compute runs every 30s for real-time sensors; DB write throttled
        # to reduce write queue load (was 4 writes/min, now 1/min).
        self._census_write_counter += 1
        startup_age = (dt_util.now() - self._created_at).total_seconds()
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is not None and startup_age >= 300 and self._census_write_counter % 4 == 0:
            self.hass.async_create_task(
                db.log_census(zone="house", result=house_result)
            )
            self.hass.async_create_task(
                db.log_census(zone="property", result=property_result)
            )

        return result

    @property
    def last_result(self) -> FullCensusResult | None:
        """Return the most recent census result."""
        return self._last_result

    # ------------------------------------------------------------------
    # House census
    # ------------------------------------------------------------------

    async def _calculate_house_census(
        self,
        ble_persons: list[str],
        now: datetime,
    ) -> CensusZoneResult:
        """Calculate the house (interior) census with graceful degradation.

        Supports 4 camera platforms: Frigate, UniFi Protect, Reolink, Dahua.
        When any platform is unavailable, the system degrades gracefully using
        whichever platforms remain operational.

        Platform capabilities:
          Frigate:   numeric person_count + binary occupancy + face recognition
          UniFi:     binary person_detected per camera (no count, no face in HA)
          Reolink:   binary person detection per camera
          Dahua:     binary person detection per camera

        Degradation modes:
          All platforms up:       cross-validate, use Frigate count, HIGH confidence
          Frigate down:           sum per-camera binary detections, MEDIUM confidence
          All cameras down:       BLE only, LOW confidence
          No cameras configured:  BLE only, confidence NONE
        """
        cross_validation_enabled = self._is_cross_validation_enabled()
        configured_interior = self._get_interior_camera_entities()

        # Categorize entities by platform and check availability
        frigate_total = 0
        frigate_available = False
        binary_platform_count = 0  # Per-camera count from non-Frigate platforms
        binary_platforms_available = False
        active_platforms: list[str] = []

        if cross_validation_enabled:
            # v5.9.0 D-A: same-area spatial dedup. Cameras sharing an HA
            # area_id observe the same physical space — a single body should
            # contribute at most 1 to that area regardless of how many
            # cameras see it. Across different areas we still SUM. Cameras
            # with no area_id fall back to individual contribution.
            #
            # Grouping is per-platform-family:
            #   * frigate_area_counts: area_id -> max Frigate person_count
            #     (Frigate is numeric — max over cameras in the area).
            #   * binary_area_seen:    area_id -> max(1) if any non-Frigate
            #     camera in the area detects a person (binary is 0/1 — max
            #     collapses to "at least one saw someone").
            # Unassigned cameras contribute individually (list of counts).
            # v5.9.0 B-C1: collect per-camera contributions with area_id
            # and collapse via the shared _dedup_by_area helper. The same
            # helper is used by _get_unrecognized_camera_count so both
            # paths cannot diverge.
            frigate_contributions: list[tuple[str | None, int]] = []
            binary_contributions: list[tuple[str | None, int]] = []
            raw_frigate_sum = 0
            raw_binary_sum = 0

            for entity_id in configured_interior:
                platform = self._camera_manager.get_platform_for_camera(entity_id)
                camera_info = self._camera_manager._camera_by_entity.get(entity_id)
                area_id = camera_info.area_id if camera_info else None

                if platform == CAMERA_PLATFORM_FRIGATE:
                    if camera_info and camera_info.person_count_sensor:
                        state = self.hass.states.get(camera_info.person_count_sensor)
                        if state and state.state not in ("unavailable", "unknown"):
                            frigate_available = True
                            count = self._get_sensor_int(camera_info.person_count_sensor)
                            # Stuck-Signal D1 discount (truth-preserving
                            # DOWNWARD only — never raises a count, never
                            # fires when interior corroboration is present;
                            # the watchdog's own corroboration gate already
                            # decided this). See _watchdog_stuck_cameras.
                            if entity_id in self._watchdog_discounted_cameras:
                                _LOGGER.debug(
                                    "Stuck-signal D1: discounting Frigate "
                                    "camera %s (person_count=%d) from house "
                                    "census — no interior corroboration",
                                    entity_id, count,
                                )
                                # A-MED-2 fix-up 2026-07-28: raw_pre_dedup_sum
                                # EXCLUDES discounted cameras (observability
                                # coherence — the "raw" attr should reflect
                                # what actually flowed through this tick,
                                # not the pre-discount hypothetical).
                                continue
                            raw_frigate_sum += count
                            if count > 0:
                                frigate_contributions.append((area_id, count))
                        # If unavailable, skip — falls through to degraded mode
                    else:
                        # Binary-only Frigate sensor
                        if self._is_entity_available(entity_id):
                            frigate_available = True
                            if self._is_entity_on(entity_id):
                                raw_frigate_sum += 1
                                frigate_contributions.append((area_id, 1))

                else:
                    # Non-Frigate platforms (UniFi, Reolink, Dahua): binary.
                    if self._is_entity_available(entity_id):
                        binary_platforms_available = True
                        if platform and platform not in active_platforms:
                            active_platforms.append(platform)
                        if self._is_entity_on(entity_id):
                            raw_binary_sum += 1
                            binary_contributions.append((area_id, 1))

            # Collapse per-platform contributions via the shared helper.
            frigate_total = self._dedup_by_area(frigate_contributions)
            binary_platform_count = self._dedup_by_area(binary_contributions)

            # Observability (D-E): record area contributions + naive sum
            # for the path that actually ships. Reflects both platforms so
            # the operator can measure dedup impact per-area.
            def _area_max_map(
                contribs: list[tuple[str | None, int]],
            ) -> dict[str, int]:
                out: dict[str, int] = {}
                for aid, cnt in contribs:
                    if not aid or cnt <= 0:
                        continue
                    if cnt > out.get(aid, 0):
                        out[aid] = cnt
                return out

            frigate_area_counts = _area_max_map(frigate_contributions)
            binary_area_seen = _area_max_map(binary_contributions)
            area_contribs: dict[str, dict[str, Any]] = {}
            for aid, cnt in frigate_area_counts.items():
                area_contribs[aid] = {"max_count": cnt, "platform": "frigate"}
            for aid, cnt in binary_area_seen.items():
                if aid in area_contribs:
                    # Both a Frigate and a binary camera share this area —
                    # keep the frigate max_count but note the mix.
                    area_contribs[aid]["binary_seen"] = cnt
                else:
                    area_contribs[aid] = {"max_count": cnt, "platform": "binary"}
            self._last_area_contributions = area_contribs
            self._last_raw_pre_dedup_sum = raw_frigate_sum + raw_binary_sum

            if frigate_available and CAMERA_PLATFORM_FRIGATE not in active_platforms:
                active_platforms.insert(0, CAMERA_PLATFORM_FRIGATE)

            # Determine count and agreement based on what's available
            degraded = False
            if frigate_available and binary_platforms_available:
                # Both available — cross-validate.
                # 2026-08-01 (census fusion policy): compute a corroboration
                # bundle so ``_cross_validate_platforms`` can downgrade an
                # UNCORROBORATED divergent max (the playroom-phantom shape).
                # Face + BLE + any-tier-1-zone-occupied are the three kinds
                # (CENSUS_DIVERGENCE_CORROBORATION_KINDS).
                # 2026-08-01 fix-up B-HIGH-1: use a freshness-gated view of
                # face recognitions here so a stale (hours-old) match cannot
                # corroborate a live divergence forever. The other consumer
                # (line ~1220 → _cross_correlate_persons) keeps the unfiltered
                # accessor to avoid silently changing that surface.
                _face_ids_corroboration = (
                    self._get_face_recognized_persons_fresh(now)
                    if frigate_available else set()
                )
                # A-M3 (2026-08-01 fix-up): this is the sole production call
                # site of _cross_validate_platforms — `corroborated=` MUST be
                # passed explicitly. The kwarg's default of True is legacy-off
                # (byte-identical pre-cycle behavior for tests / future callers
                # that omit it).
                # A-C2 (2026-08-01 fix-up): defensively wrap so a future
                # breakage inside the snapshot accessor cannot escape and
                # crash the census cycle — a corroboration miss just falls
                # back to False (which correctly LETS the downgrade fire).
                try:
                    _zone_occ = self._any_zone_occupied_snapshot()
                except Exception:  # noqa: BLE001 — fail-closed for corroboration
                    _LOGGER.debug(
                        "corroboration snapshot raised; treating zone-occ as False",
                        exc_info=True,
                    )
                    _zone_occ = False
                _corroborated = (
                    bool(_face_ids_corroboration)
                    or bool(ble_persons)
                    or _zone_occ
                )
                camera_total, agreement = self._cross_validate_platforms(
                    frigate_total, binary_platform_count,
                    corroborated=_corroborated,
                )
            elif frigate_available and not binary_platforms_available:
                # Only Frigate — single source
                camera_total = frigate_total
                agreement = CENSUS_AGREEMENT_SINGLE
            elif not frigate_available and binary_platforms_available:
                # Frigate down — use per-camera binary count as primary
                camera_total = binary_platform_count
                agreement = CENSUS_AGREEMENT_SINGLE
                degraded = True
                _LOGGER.debug(
                    "Census degraded mode: Frigate unavailable, using %d binary platform detections",
                    binary_platform_count,
                )
            elif not configured_interior:
                camera_total = 0
                agreement = CENSUS_AGREEMENT_SINGLE
            else:
                # All cameras unavailable
                camera_total = 0
                agreement = CENSUS_AGREEMENT_SINGLE
                degraded = True
                _LOGGER.warning("Census: all camera platforms unavailable")

        else:
            # Cross-validation disabled: use only the FIRST entity per device
            seen_device_ids: set[str] = set()
            ent_reg = er.async_get(self.hass)
            degraded = False

            single_source_total = 0
            for entity_id in configured_interior:
                entry = ent_reg.async_get(entity_id)
                device_id = entry.device_id if entry else None

                if device_id:
                    if device_id in seen_device_ids:
                        continue
                    seen_device_ids.add(device_id)

                if not self._is_entity_available(entity_id):
                    continue

                platform = self._camera_manager.get_platform_for_camera(entity_id)
                if platform == CAMERA_PLATFORM_FRIGATE:
                    camera_info = self._camera_manager._camera_by_entity.get(entity_id)
                    if camera_info and camera_info.person_count_sensor:
                        count = self._get_sensor_int(camera_info.person_count_sensor)
                        single_source_total += count
                    else:
                        if self._is_entity_on(entity_id):
                            single_source_total += 1
                else:
                    if self._is_entity_on(entity_id):
                        single_source_total += 1

                if platform and platform not in active_platforms:
                    active_platforms.append(platform)

            camera_total = single_source_total
            frigate_total = single_source_total
            binary_platform_count = 0
            agreement = CENSUS_AGREEMENT_SINGLE

            # v5.9.0 B-M2: cross-validation-disabled path doesn't compute
            # area contributions — clear the observability fields so stale
            # values from a prior enabled run don't leak into attributes.
            self._last_area_contributions = {}
            self._last_raw_pre_dedup_sum = single_source_total

        # Cross-correlate with BLE
        ble_id_set = set(ble_persons)

        # Collect face recognition IDs from Frigate (if available)
        face_id_set = self._get_face_recognized_persons() if frigate_available else set()

        zone_result = self._cross_correlate_persons(
            face_ids=face_id_set,
            ble_ids=ble_id_set,
            camera_total=camera_total,
            zone="house",
            frigate_count=frigate_total,
            unifi_count=binary_platform_count,
            agreement=agreement,
            now=now,
            degraded_mode=degraded,
            active_platforms=active_platforms,
        )

        return zone_result

    # ------------------------------------------------------------------
    # Property census
    # ------------------------------------------------------------------

    async def _calculate_property_census(self, now: datetime) -> CensusZoneResult:
        """Calculate the property (exterior) census.

        Checks egress cameras and perimeter cameras from integration config.
        Any detection = at least 1 person outside. We do not have numeric
        counts for the exterior (no Frigate person_count on perimeter cams
        in the current hardware config), so we report 0 or 1 per camera.

        When cross-validation is disabled, only the first entity per device is
        checked.
        """
        cross_validation_enabled = self._is_cross_validation_enabled()

        egress_entities = self._get_integration_camera_list(CONF_EGRESS_CAMERAS)
        perimeter_entities = self._get_integration_camera_list(CONF_PERIMETER_CAMERAS)
        all_exterior = egress_entities + perimeter_entities

        if cross_validation_enabled:
            exterior_count = 0
            for entity_id in all_exterior:
                if self._is_entity_on(entity_id):
                    exterior_count += 1
        else:
            # Single source: count only the first entity per device
            seen_device_ids: set[str] = set()
            ent_reg = er.async_get(self.hass)
            exterior_count = 0
            for entity_id in all_exterior:
                entry = ent_reg.async_get(entity_id)
                device_id = entry.device_id if entry else None

                if device_id:
                    if device_id in seen_device_ids:
                        continue
                    seen_device_ids.add(device_id)

                if self._is_entity_on(entity_id):
                    exterior_count += 1

        # Check which exterior entities are actually available
        available_count = sum(1 for e in all_exterior if self._is_entity_available(e))
        exterior_degraded = len(all_exterior) > 0 and available_count < len(all_exterior)

        # Confidence for exterior zone
        if not all_exterior:
            confidence = CENSUS_CONFIDENCE_NONE
            agreement = CENSUS_AGREEMENT_SINGLE
        elif available_count == 0:
            confidence = CENSUS_CONFIDENCE_NONE
            agreement = CENSUS_AGREEMENT_SINGLE
        elif exterior_count > 0:
            confidence = CENSUS_CONFIDENCE_MEDIUM
            agreement = CENSUS_AGREEMENT_SINGLE
        else:
            confidence = CENSUS_CONFIDENCE_MEDIUM
            agreement = CENSUS_AGREEMENT_SINGLE

        # Collect active platforms for exterior
        ext_platforms: list[str] = []
        for entity_id in all_exterior:
            if self._is_entity_available(entity_id):
                platform = self._camera_manager.get_platform_for_camera(entity_id)
                if platform and platform not in ext_platforms:
                    ext_platforms.append(platform)

        return CensusZoneResult(
            zone="property",
            identified_count=0,
            identified_persons=[],
            unidentified_count=exterior_count,
            total_persons=exterior_count,
            confidence=confidence,
            source_agreement=agreement,
            frigate_count=0,
            unifi_count=0,
            degraded_mode=exterior_degraded,
            active_platforms=ext_platforms,
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Cross-validation
    # ------------------------------------------------------------------

    def _cross_validate_platforms(
        self,
        frigate_count: int,
        binary_platform_count: int,
        *,
        corroborated: bool = True,
    ) -> tuple[int, str]:
        """Cross-validate person counts between Frigate and binary-detection platforms.

        Frigate provides numeric counts; other platforms (UniFi, Reolink, Dahua)
        provide per-camera binary detection summed as binary_platform_count.

        Agreement (both>0) and mutual-zero paths are unchanged: Frigate wins,
        BOTH agreement.

        Divergence (one>0, other==0):
        - If ``corroborated`` (a face-recognized person, a BLE-tracked person,
          or any tier-1 room-occupied zone is present) → keep the higher
          reading tagged CLOSE (pre-cycle behavior).
        - Else, when ``CONF_CENSUS_DIVERGENCE_DOWNGRADE`` is enabled
          (default), downgrade to ``min`` (== 0) tagged DISAGREE — the
          uncorroborated higher reading is NOT adopted. This closes the
          2026-08-01 playroom-phantom max-wins path where a lone
          uncorroborated Frigate 1 flipped house→GUEST despite Protect zero.

        The ``corroborated`` kwarg defaults to True so any legacy caller
        that omits it preserves pre-cycle behavior byte-identically.

        Returns:
            (best_count, agreement_level)
        """
        if frigate_count == 0 and binary_platform_count == 0:
            return (0, CENSUS_AGREEMENT_BOTH)

        if frigate_count > 0 and binary_platform_count > 0:
            # Both detect persons — use Frigate (numeric), confirmed by binary platforms
            return (frigate_count, CENSUS_AGREEMENT_BOTH)

        if frigate_count > 0 and binary_platform_count == 0:
            # Only Frigate detects
            return self._apply_divergence_downgrade(
                frigate_count, binary_platform_count,
                higher=frigate_count,
                corroborated=corroborated,
                direction="frigate=%d, binary=0" % frigate_count,
            )

        if frigate_count == 0 and binary_platform_count > 0:
            # Only binary platforms detect — use their per-camera count
            return self._apply_divergence_downgrade(
                frigate_count, binary_platform_count,
                higher=binary_platform_count,
                corroborated=corroborated,
                direction="frigate=0, binary=%d" % binary_platform_count,
            )

        # Should not reach here, but fallback
        total = max(frigate_count, binary_platform_count)
        return (total, CENSUS_AGREEMENT_SINGLE)

    def _apply_divergence_downgrade(
        self,
        frigate_count: int,
        binary_platform_count: int,
        *,
        higher: int,
        corroborated: bool,
        direction: str,
    ) -> tuple[int, str]:
        """Shared helper: apply the uncorroborated-divergence downgrade.

        Both divergent branches (frigate-only, binary-only) route through here
        so the downgrade rule lives in ONE place (A-M1 dedup). The per-branch
        `direction` label is preserved in the info log for post-hoc analysis.
        """
        if not corroborated and self._is_divergence_downgrade_enabled():
            _LOGGER.info(
                "Census divergence downgrade: %s, uncorroborated → min-wins (0, DISAGREE)",
                direction,
            )
            return (
                min(frigate_count, binary_platform_count),
                CENSUS_AGREEMENT_DISAGREE,
            )
        return (higher, CENSUS_AGREEMENT_CLOSE)

    def _any_zone_occupied_snapshot(self) -> bool:
        """Return True if the presence coordinator reports any occupied zone.

        Read-only best-effort accessor used only by the census-divergence
        corroboration bundle. Returns False on any failure (coordinator
        unavailable, wrong shape) — a conservative default that lets the
        divergence downgrade fire when we simply don't know.

        A-C1 (2026-08-01 fix-up): ``tracker.mode`` is the plain string
        contract from ``ZonePresenceMode.OCCUPIED`` == ``"occupied"``
        (presence.py:228-237), NOT a StrEnum whose ``.name`` is "OCCUPIED".
        Compare against the string directly. Kept as string to avoid a hot
        import cycle with ``domain_coordinators.presence``.

        A-H1: once-per-instance WARNING when the accessor takes the
        absent/exception path — so a future presence refactor that
        re-severs this limb is visible in logs, not silently False.
        """
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if mgr is None:
                self._warn_zone_snapshot_absent("coordinator_manager missing")
                return False
            presence = getattr(mgr, "coordinators", {}).get("presence")
            if presence is None:
                self._warn_zone_snapshot_absent("presence coordinator missing")
                return False
            trackers = getattr(presence, "_zone_trackers", None)
            if not trackers:
                self._warn_zone_snapshot_absent("zone trackers absent/empty")
                return False
            for tracker in trackers.values():
                mode = getattr(tracker, "mode", None)
                # Contract: ZonePresenceMode.OCCUPIED == "occupied"
                # (presence.py:228-237). Direct string compare.
                if mode == "occupied":
                    return True
            return False
        except (AttributeError, KeyError, TypeError) as exc:  # A-L2: narrow
            self._warn_zone_snapshot_absent(f"exception: {exc!r}")
            return False

    def _warn_zone_snapshot_absent(self, reason: str) -> None:
        """A-H1: once-per-instance drift warning for the zone-snapshot limb."""
        if getattr(self, "_zone_snapshot_absent_warned", False):
            return
        self._zone_snapshot_absent_warned = True
        _LOGGER.warning(
            "Census corroboration: _any_zone_occupied_snapshot degraded (%s); "
            "zone-occupied limb of the divergence-downgrade bundle is dark "
            "for this session. Investigate presence-coordinator wiring.",
            reason,
        )

    def _is_divergence_downgrade_enabled(self) -> bool:
        """Return True if the divergence-downgrade policy is enabled (default True).

        Reads CONF_CENSUS_DIVERGENCE_DOWNGRADE from the integration entry.
        False = fire-axe restore to pre-cycle max-wins behavior on the
        divergence branch.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(merged.get(
                    CONF_CENSUS_DIVERGENCE_DOWNGRADE,
                    DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE,
                ))
        return DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE

    # ------------------------------------------------------------------
    # Cross-correlation
    # ------------------------------------------------------------------

    def _cross_correlate_persons(
        self,
        face_ids: set[str],
        ble_ids: set[str],
        camera_total: int,
        zone: str,
        frigate_count: int,
        unifi_count: int,
        agreement: str,
        now: datetime,
        degraded_mode: bool = False,
        active_platforms: list[str] | None = None,
    ) -> CensusZoneResult:
        """Cross-correlate face recognition IDs with BLE IRK tracking IDs.

        Logic:
          known_persons = face_ids | ble_ids  (union — identified by either source)
          identified_count = len(known_persons)
          unidentified_count = max(0, camera_total - identified_count)  # guests
          total = max(camera_total, identified_count)

        Confidence rules:
          agreement == both_agree AND ble confirms faces  -> high
          agreement == both_agree, no faces               -> high (cameras agree)
          agreement == close                              -> medium
          agreement == disagree                           -> low
          agreement == single_source                      -> medium
          no camera data, BLE only                        -> low
          no data                                         -> none
        """
        # EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 fuse site 1 of 2 (I1/I5,
        # plan-review C-CRIT-1). Names normalized to Frigate first-name
        # slug BEFORE set-union so a resident recognized via face
        # ("Oji") and BLE ("oji_udezue") counts once, and an egress-face
        # for the same person does not add a third member.
        # D-MED-1 (2026-08-18): true byte-identical kill switch. When
        # EGRESS_IDENTITY_ENABLED is False, use the EXACT pre-cycle
        # expression `face_ids | ble_ids` — no canonicalization, no
        # egress term. Canonicalization can itself merge names the
        # pre-cycle code counted separately (e.g. face="Oji", ble=
        # "oji_udezue" -> pre-cycle 2, canonicalized 1), so gating only
        # the egress term is NOT byte-identical.
        if self._is_egress_identity_enabled():
            egress_face_ids = self._get_egress_face_ids_fresh(now)
            known_persons = (
                self._normalize_name_set(face_ids)
                | self._normalize_name_set(ble_ids)
                | egress_face_ids  # already canonicalized on register
            )
        else:
            known_persons = set(face_ids) | set(ble_ids)
        identified_count = len(known_persons)
        identified_persons = sorted(known_persons)

        if camera_total > 0:
            unidentified_count = max(0, camera_total - identified_count)
            total = max(camera_total, identified_count)
        else:
            # No camera data; rely on BLE only
            unidentified_count = 0
            total = identified_count

        # Determine confidence
        if camera_total == 0 and identified_count == 0:
            confidence = CENSUS_CONFIDENCE_NONE
        elif camera_total == 0 and identified_count > 0:
            # BLE only — low confidence (no camera cross-check)
            confidence = CENSUS_CONFIDENCE_LOW
        elif agreement == CENSUS_AGREEMENT_BOTH:
            # Both platforms agree
            confidence = CENSUS_CONFIDENCE_HIGH
        elif agreement == CENSUS_AGREEMENT_CLOSE:
            confidence = CENSUS_CONFIDENCE_MEDIUM
        elif agreement == CENSUS_AGREEMENT_DISAGREE:
            confidence = CENSUS_CONFIDENCE_LOW
        else:
            # single_source (including cross-validation disabled case)
            confidence = CENSUS_CONFIDENCE_MEDIUM

        return CensusZoneResult(
            zone=zone,
            identified_count=identified_count,
            identified_persons=identified_persons,
            unidentified_count=unidentified_count,
            total_persons=total,
            confidence=confidence,
            source_agreement=agreement,
            frigate_count=frigate_count,
            unifi_count=unifi_count,
            degraded_mode=degraded_mode,
            active_platforms=active_platforms or [],
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Helper: read configuration
    # ------------------------------------------------------------------

    def _is_cross_validation_enabled(self) -> bool:
        """Return True if census cross-validation is enabled (default True).

        Reads CONF_CENSUS_CROSS_VALIDATION from the integration config entry.
        Defaults to True if the key is absent.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(merged.get(CONF_CENSUS_CROSS_VALIDATION, True))
        return True

    def _get_interior_camera_entities(self) -> list[str]:
        """Return resolved person detection binary_sensor entity IDs for interior cameras.

        Reads CONF_CAMERA_PERSON_ENTITIES from the integration config entry
        (integration-level since v3.4.5 — previously stored per room).

        Each camera.* entity ID is resolved to its person detection binary_sensor
        entities via CameraIntegrationManager.resolve_configured_cameras().
        Room mapping is automatic: CameraInfo.area_id is populated from the HA
        entity registry during resolution, so cameras are associated with rooms
        without any per-room configuration.

        Returns a flat list of binary_sensor entity IDs.
        """
        return self._get_integration_camera_list(CONF_CAMERA_PERSON_ENTITIES)

    def _get_integration_camera_list(self, conf_key: str) -> list[str]:
        """Return resolved person detection binary_sensor IDs from integration-level config.

        Reads conf_key (CONF_EGRESS_CAMERAS or CONF_PERIMETER_CAMERAS) from the
        integration config entry (now stores camera.* entity IDs), then resolves
        each camera.* ID to its person detection binary_sensor entities.

        Returns a flat list of binary_sensor entity IDs.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                camera_entity_ids = merged.get(conf_key, [])
                if not camera_entity_ids:
                    return []
                # EGRESS-CAMERA-DEAD-CONFIG-1: record the per-scope diagnostic
                # snapshot BEFORE resolving so a removal from stored config
                # self-corrects on the next tick. Guarded by hasattr — some
                # in-tree test stubs mimic the manager's public surface only.
                if hasattr(self._camera_manager, "record_unresolved_for_scope"):
                    try:
                        self._camera_manager.record_unresolved_for_scope(
                            conf_key, camera_entity_ids
                        )
                    except Exception:  # noqa: BLE001 — diagnostic must never crash callers
                        _LOGGER.debug(
                            "record_unresolved_for_scope failed for %s",
                            conf_key,
                            exc_info=True,
                        )
                # Resolve camera.* IDs -> person detection binary_sensor entity IDs
                resolved = self._camera_manager.resolve_configured_cameras(camera_entity_ids)
                return [info.person_binary_sensor for info in resolved if info.person_binary_sensor]
        return []

    # ------------------------------------------------------------------
    # Helper: read HA state
    # ------------------------------------------------------------------

    def _is_entity_available(self, entity_id: str) -> bool:
        """Return True if an entity exists and is not unavailable/unknown."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.state not in ("unavailable", "unknown")

    def _is_entity_on(self, entity_id: str) -> bool:
        """Return True if a binary_sensor is in state 'on'."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if state.state in ("unavailable", "unknown"):
            _LOGGER.debug("Camera entity %s is %s — treating as off", entity_id, state.state)
            return False
        return state.state == "on"

    @staticmethod
    def _dedup_by_area(counts: list[tuple[str | None, int]]) -> int:
        """v5.9.0 D-A: same-area spatial dedup.

        Given a list of (area_id, count) contributions, collapse counts
        that share an ``area_id`` to ``max(count)`` for that area, then
        sum across areas. Cameras with a null ``area_id`` contribute
        individually (sum, no dedup).

        Used by ``_calculate_house_census`` (raw camera totals). NOTE
        (2026-07-13 BLE-cancel fix-up a3e5c49b): ``_get_unrecognized_camera_count``
        no longer calls this helper — it INLINES the same per-area-max
        semantics as Step 2/4 of its four-step algorithm, because the BLE
        subtraction must happen BETWEEN dedup and summation. If you change
        the dedup semantics here, mirror the change in that function's
        Step 2/4 (deliberate fork; see the review record
        wave2026_07_13 docs for rationale).
        """
        area_max: dict[str, int] = {}
        unassigned: list[int] = []
        for area_id, count in counts:
            if count <= 0:
                continue
            if area_id:
                if count > area_max.get(area_id, 0):
                    area_max[area_id] = count
            else:
                unassigned.append(count)
        return sum(area_max.values()) + sum(unassigned)

    def _get_sensor_int(self, entity_id: str, default: int = 0) -> int:
        """Return integer value of a numeric sensor."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return default
        try:
            return int(float(state.state))
        except (ValueError, TypeError):
            return default

    # ------------------------------------------------------------------
    # Helper: BLE person data
    # ------------------------------------------------------------------

    def _get_ble_persons(self) -> list[str]:
        """Return list of person IDs currently tracked as home by person_coordinator.

        Gracefully returns empty list if person_coordinator is not initialized
        or has no data.
        """
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator or not person_coordinator.data:
            return []

        home_persons: list[str] = []
        for person_id, person_info in person_coordinator.data.items():
            location = person_info.get("location", "")
            # A person is "home" if they have any room location (not away/unknown)
            if location and location not in ("away", "unknown", ""):
                home_persons.append(person_id)

        return home_persons

    def _build_room_to_area_id_map(self) -> dict[str, str]:
        """Return ``{room_name: registry_area_id}`` from URA room config entries.

        Cycle census_ble_cancel_unrecognized (2026-07-13) — Fix 3 (review
        A-H2). We CANNOT invert ``person_coordinator._area_id_to_room``:
        that dict is populated by ``_build_scanner_room_map()`` with THREE
        keys per area (registry area_id, area Name, normalized-name) all
        mapping to the same ``room_name`` value. Inverting it (`room -> aid`)
        is last-wins over the three keys and typically yields the
        *normalized name*, NOT the registry ``area_id``. But
        ``CameraInfo.area_id`` is the registry area_id — so a renamed area
        would silently never cancel.

        Rooms store their canonical registry area_id under ``CONF_AREA_ID``
        in the room config entry (see person_coordinator.py:549 for the
        production read of the same field). Build the map directly.
        """
        room_to_area: dict[str, str] = {}
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                merged = {**entry.data, **entry.options}
                room_name = merged.get(CONF_ROOM_NAME) or entry.data.get(
                    CONF_ROOM_NAME
                )
                area_id = merged.get(CONF_AREA_ID)
                if room_name and area_id:
                    room_to_area[room_name] = area_id
        except Exception:  # noqa: BLE001 — graceful degradation (invariant I3)
            _LOGGER.debug(
                "_build_room_to_area_id_map failed; returning empty",
                exc_info=True,
            )
            return {}
        return room_to_area

    # ------------------------------------------------------------------
    # Stuck-Signal Watchdog D1 (v5.35.0)
    # ------------------------------------------------------------------

    def _watchdog_stuck_cameras(self, now: datetime) -> None:
        """Per-Frigate-camera stuck-count check + corroboration + NM latch.

        For each configured Frigate camera with a person_count sensor,
        track how long its value has held > 0 without changing. When the
        window exceeds ``CONF_STUCK_CAMERA_HOURS`` (default 3h) AND there
        is ZERO interior corroboration in the camera's area (no BLE-here,
        no room-tier motion/mmwave/occupancy/occupied signal), record it
        as stuck. The camera is DISCOUNTED from the census tally this tick
        and a per-day NM latch fires.

        Populates:
          * ``self._camera_stuck_state`` — per-camera bookkeeping
          * ``self._watchdog_discounted_cameras`` — set consumed by
            ``_calculate_house_census`` to skip stuck contributions
          * ``self._last_stuck_cameras`` — diagnostic list for the
            ``stuck_cameras`` sensor attribute

        Fail-open: caller wraps in try/except.
        """
        # FIX 3 (B H-2) 2026-07-28: boot-settle gate — no verdicts until
        # presence has released the shared boot-settle predicate.
        if not self._d1_boot_settle_done():
            self._watchdog_discounted_cameras = set()
            self._last_stuck_cameras = []
            return

        stuck_hours = self._get_stuck_camera_hours()
        tiers_required = self._get_stuck_camera_tiers_required()

        configured_interior = self._get_interior_camera_entities()
        ble_by_area = self._ble_home_by_area()

        # Snapshot per-area room-tier corroboration ONCE per tick. Iterating
        # room coordinators once is O(rooms); the alternative of doing it
        # per-camera would be O(rooms * cameras).
        room_tier_by_area = self._room_tier_corroboration_by_area()

        # FIX 5 (A-HIGH-3) 2026-07-28: set of area_ids that have ANY URA
        # room mapped to them. Used to gate discount safety — a camera
        # in an area with no interior tier must never be census-dropped.
        _configured_interior_areas: set[str] = (
            self._interior_configured_areas()
        )

        stuck_now: set[str] = set()
        stuck_diag: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entity_id in configured_interior:
            platform = self._camera_manager.get_platform_for_camera(entity_id)
            if platform != CAMERA_PLATFORM_FRIGATE:
                continue
            camera_info = self._camera_manager._camera_by_entity.get(entity_id)
            if not camera_info or not camera_info.person_count_sensor:
                continue
            count_sensor = camera_info.person_count_sensor
            state = self.hass.states.get(count_sensor)
            if state is None or state.state in ("unavailable", "unknown"):
                # Availability transitions clear the stuck timer — an
                # offline camera cannot be "stuck asserting a count".
                self._camera_stuck_state.pop(entity_id, None)
                continue
            try:
                count = int(float(state.state))
            except (TypeError, ValueError):
                self._camera_stuck_state.pop(entity_id, None)
                continue

            seen.add(entity_id)
            rec = self._camera_stuck_state.get(entity_id)
            if count <= 0:
                # Any zero reading resets the stuck window (the count is
                # only stuck when it holds > 0 for the whole window).
                self._camera_stuck_state.pop(entity_id, None)
                continue

            # v5.36.1 FIX 2: track `nonzero_since` INDEPENDENTLY of value
            # changes. The unchanged-value window (`since`) still resets on
            # every value change, but nonzero_since only resets when count
            # hits 0 (handled above by pop) OR when corroboration appears
            # (below). This is the "never-zero" sibling rule that catches
            # oscillating phantoms the unchanged rule can't see.
            if rec is None:
                self._camera_stuck_state[entity_id] = {
                    "since": now,
                    "last_value": count,
                    "nonzero_since": now,
                }
                continue
            if rec.get("last_value") != count:
                # Value CHANGED: reset the unchanged-value window but keep
                # nonzero_since (count stayed > 0 across the change).
                # v5.36.1 FIX 2: do NOT `continue` here — the never-zero
                # rule must still be evaluated so a perpetually oscillating
                # phantom (that changes value on every tick) cannot evade
                # detection indefinitely. Update in place and fall through.
                rec["since"] = now
                rec["last_value"] = count
                # nonzero_since preserved as-is.

            # rec is not None (unchanged OR just-updated on change) — running hold.
            since = rec.get("since", now)
            hours = (now - since).total_seconds() / 3600.0
            nonzero_since = rec.get("nonzero_since", since)
            nonzero_hours = (now - nonzero_since).total_seconds() / 3600.0
            never_zero_hit = nonzero_hours >= STUCK_CAMERA_NEVERZERO_HOURS
            unchanged_hit = hours >= stuck_hours
            if not (unchanged_hit or never_zero_hit):
                continue
            stuck_rule = "unchanged" if unchanged_hit else "never_zero"

            # Stuck window exceeded. Check corroboration.
            area_id = camera_info.area_id
            ble_here = ble_by_area.get(area_id, 0) if area_id else 0
            room_tier = room_tier_by_area.get(area_id, 0) if area_id else 0
            corroborators = int(ble_here > 0) + int(room_tier > 0)

            corroborated = corroborators >= tiers_required

            # FIX 5 (A-HIGH-2) 2026-07-28: camera with area_id None — SKIP
            # discount entirely + one-time WARN. Silent auto-discount on a
            # nameless area is unsafe.
            # FIX 5 (A-HIGH-3): area has NO configured interior tier at all
            # (no rooms mapped to this area_id in `room_tier_by_area`
            # discovery + no BLE-resident capable of showing up here) →
            # notify-only, never discount. A lone stationary guest in a
            # camera-only area must not be census-dropped.
            area_has_interior = (
                bool(area_id) and area_id in _configured_interior_areas
            )
            safe_to_discount = bool(area_id) and area_has_interior

            entry_diag = {
                "entity_id": entity_id,
                "kind": "camera_stuck",
                "rule": stuck_rule,
                "hours": round(hours, 2),
                "nonzero_hours": round(nonzero_hours, 2),
                "count": count,
                "area_id": area_id,
                "interior_corroborators": corroborators,
                "ble_here": ble_here,
                "room_tier_on": room_tier,
                "discounted": (not corroborated) and safe_to_discount,
                "notify_only_reason": (
                    None if safe_to_discount
                    else ("no_area_id" if not area_id else "no_interior_tier")
                ),
            }
            stuck_diag.append(entry_diag)
            if corroborated:
                # Signals agree with the camera — do not discount, do not NM.
                # (Matches P18 zone-stale shape.) v5.36.1 FIX 2: also reset
                # nonzero_since so the never-zero window can't accumulate
                # while corroboration is present.
                rec["nonzero_since"] = now
                continue

            if not area_id and entity_id not in self._null_area_warned:
                self._null_area_warned.add(entity_id)
                _LOGGER.warning(
                    "Stuck-signal D1: camera %s has area_id=None — "
                    "notify-only, skipping census discount",
                    entity_id,
                )

            if safe_to_discount:
                stuck_now.add(entity_id)
            # NM notify fires regardless of discount decision (operator
            # visibility on any stuck camera).
            self.hass.async_create_task(_fire_camera_stuck_nm(  # noqa: untracked-ok
                self.hass, entity_id, count,
                hours if unchanged_hit else nonzero_hours,
                stuck_rule,
            ))
            # Fire-and-forget NM emit; per-day latched.

        # Purge state for cameras no longer configured or no longer
        # reporting a valid count (prevents unbounded growth across
        # config reloads — Bug Class #22 mitigation).
        for stale_id in list(self._camera_stuck_state.keys()):
            if stale_id not in seen:
                self._camera_stuck_state.pop(stale_id, None)

        self._watchdog_discounted_cameras = stuck_now
        self._last_stuck_cameras = stuck_diag

    def _d1_boot_settle_done(self) -> bool:
        """Shared boot-settle predicate — same source as ActuatorReconciler."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if mgr is None:
                return True
            presence = getattr(mgr, "coordinators", {}).get("presence")
            if presence is None:
                return True
            return bool(getattr(presence, "_boot_settle_done", True))
        except Exception:  # noqa: BLE001
            return True

    def _interior_configured_areas(self) -> set[str]:
        """Return the set of area_ids that have a URA room mapped to them."""
        out: set[str] = set()
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                area_id = entry.data.get(CONF_AREA_ID) or entry.options.get(
                    CONF_AREA_ID,
                )
                if area_id:
                    out.add(area_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "_interior_configured_areas failed", exc_info=True,
            )
        return out

    def get_stuck_cameras(self) -> list[dict[str, Any]]:
        """B L-3 fix-up 2026-07-28: public accessor for the sensor layer.

        Returns a copy of the last-computed stuck-camera diagnostic list.
        Callers (sensor.py) should use this instead of reaching into the
        private `_last_stuck_cameras` attribute.
        """
        return list(self._last_stuck_cameras or [])

    def _get_stuck_camera_hours(self) -> float:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                try:
                    return float(merged.get(
                        CONF_STUCK_CAMERA_HOURS, DEFAULT_STUCK_CAMERA_HOURS,
                    ))
                except (TypeError, ValueError):
                    return DEFAULT_STUCK_CAMERA_HOURS
        return DEFAULT_STUCK_CAMERA_HOURS

    def _get_stuck_camera_tiers_required(self) -> int:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                try:
                    return int(merged.get(
                        CONF_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED,
                        DEFAULT_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED,
                    ))
                except (TypeError, ValueError):
                    return DEFAULT_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED
        return DEFAULT_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED

    def _room_tier_corroboration_by_area(self) -> dict[str, int]:
        """Return ``{area_id: count_of_rooms_with_tier1_or_occupied}``.

        Iterates all room coordinators; counts a room as corroborating iff
        its live data shows any of motion/presence/occupied True. Safe to
        call every census tick (~2 Hz).
        """
        out: dict[str, int] = {}
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                area_id = entry.data.get(CONF_AREA_ID) or entry.options.get(
                    CONF_AREA_ID,
                )
                if not area_id:
                    continue
                room_coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if room_coord is None:
                    continue
                data = getattr(room_coord, "data", None) or {}
                if (
                    data.get(STATE_MOTION_DETECTED)
                    or data.get(STATE_PRESENCE_DETECTED)
                    or data.get(STATE_OCCUPIED)
                ):
                    out[area_id] = out.get(area_id, 0) + 1
        except Exception:  # noqa: BLE001 — corroboration best-effort
            _LOGGER.debug(
                "_room_tier_corroboration_by_area failed; treating as none",
                exc_info=True,
            )
            return {}
        return out

    def _ble_home_by_area(self) -> dict[str, int]:
        """Return ``{area_id: count}`` of residents BLE places at home, keyed by area.

        Cycle: census_ble_cancel_unrecognized (2026-07-13).

        Purpose: the *raw* census path (``_cross_correlate_persons``) already
        implicitly cancels residents whom BLE places at home when computing
        unidentified = max(0, camera_total - |face ∪ ble|). The *enhanced*
        path (``_apply_enhanced_house_census``, default ON) never consulted
        BLE — so a resident whose face wasn't matched in the last 30 min
        would show up as an unidentified count, arming the guest gate. This
        helper restores the missing property, but per-area rather than
        globally (see invariant I1 in PLANNING_census_ble_cancel_unrecognized.md):
        a resident in the kitchen must NOT cancel a genuine guest in the foyer.

        Consults ``person_coordinator.data``: for each tracked person whose
        ``location`` is a real room name and whose ``tracking_status`` is
        ACTIVE (i.e. NOT STALE and NOT LOST), resolves the room name to a
        registry ``area_id`` via ``_build_room_to_area_id_map`` (which reads
        each URA room entry's ``CONF_AREA_ID`` directly — see the docstring
        on that helper for why we cannot invert
        ``person_coordinator._area_id_to_room``).

        Exclusion rules (Fix 5a — Bug Class #7 stale data source):
        - ``tracking_status == 'stale'`` — bermuda_decay keeps a departed
          resident's room ≤300s under STALE; a departed resident MUST NOT
          cancel a real guest arriving in that area.
        - ``tracking_status == 'lost'`` — no recent tracking data at all.
        - ``location`` values ``away``/``unknown``/``home``/``lost`` (the
          "not resolved to a specific room" sentinels — cannot cancel a
          specific camera's area).
        - Room slugs that don't resolve to any registered ``area_id`` are
          DROPPED entirely (Fix 4 — A-H3): an unmapped resident must not
          cancel guests on null-area cameras. The prior implementation
          bucketed them under key ``None`` which cross-cancelled with
          null-area cameras and broke invariant I1.

        Returns ``{}`` on any exception or when ``person_coordinator`` is
        not initialized — graceful degradation means no cancellation is
        applied (invariant I3: correction is monotone-reducing, so ``{}``
        falls back to today's over-arming behavior, never inflates).
        """
        try:
            person_coordinator = (
                self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            )
            if not person_coordinator or not person_coordinator.data:
                return {}

            room_to_area = self._build_room_to_area_id_map()
            if not room_to_area:
                return {}

            result: dict[str, int] = {}
            for _person_id, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if not location or location in ("away", "unknown", "home", "lost"):
                    continue
                # Fix 5a: STALE/LOST residents cannot cancel. A departed
                # resident held in STALE by bermuda_decay must not cancel a
                # real guest walking into the room they just left.
                tracking_status = person_info.get("tracking_status")
                if tracking_status in (
                    TRACKING_STATUS_STALE, TRACKING_STATUS_LOST,
                ):
                    continue
                area_id = room_to_area.get(location)
                # Fix 4 (A-H3): unmapped location must cancel NOTHING —
                # DROP entirely rather than bucketing under None.
                if not area_id:
                    continue
                result[area_id] = result.get(area_id, 0) + 1

            return result
        except Exception:  # noqa: BLE001 — graceful degradation (invariant I3)
            _LOGGER.debug(
                "_ble_home_by_area failed; no BLE cancellation applied",
                exc_info=True,
            )
            return {}

    # ------------------------------------------------------------------
    # CENSUS-ACCURACY-1 D2 (2026-08-17): _2-suffix-tolerant resolvers.
    # See PLANNING_census_accuracy.md rev-2 §D2 + plan_review §3/F1.
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_peak_age_seconds(
        peak_ts: datetime | None,
        peak_held: bool,
        dispatch_utcnow: datetime,
    ) -> int:
        """Real second-precision age of the currently-held peak.

        CENSUS-ACCURACY-1 D1 review fix-up (B-MEDIUM-2): must NOT be
        `int(peak_age_minutes) * 60` — that is 60× coarser than the
        name implies and defeats short-window discrimination. Returns 0
        when there is no held peak.
        """
        if peak_ts is None or not peak_held:
            return 0
        try:
            return max(0, int((dispatch_utcnow - peak_ts).total_seconds()))
        except (TypeError, ValueError):
            return 0

    def _resolve_face_entity_id(self, base_name: str) -> str | None:
        """Resolve `sensor.<base>_last_recognized_face` tolerating the `_2`
        disambiguation suffix.

        Returns the entity_id of the FIRST variant whose live state is not
        unavailable/unknown/empty; returns None if neither hits. On a full
        miss the caller MUST fail CLOSED (no fresh-face `-1` credit) and
        the per-tick `_face_lookup_missing_count` is incremented here so
        every fail path is measured uniformly.

        Mirrors the shipped v5.78.0 `_has_any_suffix_stripped` pattern
        (camera_resolver.py:317-327). Does NOT construct Frigate
        unique_ids — that format is external and not derivable.
        """
        # EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28) B-HIGH-1 revert: this
        # helper stays byte-identical to the pre-cycle behaviour. Protect
        # coupling lives ONLY in `_resolve_face_legs` under the D2b kill
        # switch. Widening this helper to include `_face_recognized[_2]`
        # would feed Protect names into 4 pre-existing surfaces (guest
        # count, corroboration bundle, presence pre-arrival) OUTSIDE the
        # cycle's kill switch. Adding Protect to the census fresh-set is
        # a separate, kill-switch-gated cycle.
        canonical = f"sensor.{base_name}_last_recognized_face"
        suffixed = f"sensor.{base_name}_last_recognized_face_2"
        for candidate in (canonical, suffixed):
            try:
                state = self.hass.states.get(candidate)
            except Exception:  # noqa: BLE001 — defensive
                continue
            if state is None:
                continue
            val = state.state if isinstance(state.state, str) else ""
            if val.strip().lower() in (
                "unavailable", "unknown", "", "none",
            ):
                # State exists but unusable — try the next variant.
                continue
            return candidate
        # Neither variant resolved to a usable state. Fail-CLOSED: caller
        # gets None -> no `-1` credit. Measure it so operators can tell.
        self._face_lookup_missing_count += 1
        return None

    def _resolve_face_legs(self, base_name: str) -> list["FaceLeg"]:
        """EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28): additive sibling of
        ``_resolve_face_entity_id`` returning ALL live NAME-carrying face
        legs for a camera stem so the D2b classifier can reason about
        cross-camera / cross-engine corroboration at the decision site.

        Enumerates the two NAME-carrying suffixes directly on ``sensor.*``:
          - ``sensor.<base>_last_recognized_face[_2]`` — Frigate.
          - ``sensor.<base>_face_recognized[_2]``      — Protect (D1 bridge).

        DETECTION-only suffixes (``_face_detected`` / ``_smart_detect_face``
        / ``_ai_face``) carry no recognized name and are NOT enumerated
        (they would produce ``canonical_slug is None`` and be dropped
        downstream anyway).

        For each present entity: reads ``state`` + ``last_changed`` +
        optional ``confidence`` attr; drops sentinel states; drops below-
        floor confidences; populates ``canonical_slug`` via the census
        canonicalizer; resolves ``device_id`` via ``CameraResolver``; tags
        ``engine`` via the ``CameraResolver._engine_tag`` path (``_2``
        maps to the disambiguated engine, e.g. ``frigate2`` / ``protect2``).

        On any lookup error the accessor returns ``[]`` and increments
        ``_face_lookup_missing_count`` (mirrors the old helper's telemetry).
        Used ONLY by ``transit_validator._resolve_egress_face_identity``.
        """
        results: list[FaceLeg] = []
        try:
            # Build the (entity_id, engine_integration_hint) enumeration.
            candidates: list[tuple[str, str]] = [
                (f"sensor.{base_name}_last_recognized_face", "frigate"),
                (f"sensor.{base_name}_last_recognized_face_2", "frigate"),
                (f"sensor.{base_name}_face_recognized", "protect"),
                (f"sensor.{base_name}_face_recognized_2", "protect"),
            ]
            resolver = None
            try:
                if hasattr(self._camera_manager, "_get_resolver"):
                    resolver = self._camera_manager._get_resolver()
            except Exception:  # noqa: BLE001 — resolver optional
                resolver = None

            for entity_id, integration_hint in candidates:
                try:
                    state = self.hass.states.get(entity_id)
                except Exception:  # noqa: BLE001 — defensive
                    continue
                if state is None:
                    continue
                raw = state.state if isinstance(state.state, str) else ""
                val = raw.strip()
                if val.lower() in (
                    "unavailable", "unknown", "", "none", "no_match",
                ):
                    continue
                # Optional confidence attribute (Protect bridge exposes;
                # Frigate does not — treat absent as passing the floor).
                conf: float | None = None
                try:
                    attrs = getattr(state, "attributes", None) or {}
                    if "confidence" in attrs and attrs["confidence"] is not None:
                        conf = float(attrs["confidence"])
                except Exception:  # noqa: BLE001
                    conf = None
                if conf is not None and conf < FACE_MATCH_MIN_CONFIDENCE:
                    continue
                # Canonicalize the recognized name to the URA slug.
                try:
                    canonical = self._canonical_person_slug(val)
                except Exception:  # noqa: BLE001
                    canonical = ""
                canonical_slug = canonical or None
                # Resolve device_id + engine tag via the shared resolver.
                device_id: str | None = None
                engine: str = integration_hint
                if resolver is not None:
                    try:
                        device_id = resolver.resolve_entity_to_device_id(entity_id)
                    except Exception:  # noqa: BLE001
                        device_id = None
                    try:
                        dev = resolver._device(device_id) if device_id else None
                        integration = resolver._infer_integration(dev) or ""
                        # Reuse `_engine_tag` so the `_2` disambiguation
                        # maps to `frigate2` / `protect2` exactly like
                        # DetectionLeg (camera_resolver.py:174-176).
                        name_part = entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
                        engine = resolver._engine_tag(
                            integration or integration_hint, name_part, device_id,
                        ) or integration_hint
                    except Exception:  # noqa: BLE001
                        # Fall back to a suffix-anchored tag so `_2`
                        # still disambiguates when the resolver fails.
                        engine = (
                            f"{integration_hint}2"
                            if entity_id.endswith("_2") else integration_hint
                        )
                else:
                    engine = (
                        f"{integration_hint}2"
                        if entity_id.endswith("_2") else integration_hint
                    )
                last_changed = getattr(state, "last_changed", None)
                results.append(FaceLeg(
                    entity_id=entity_id,
                    engine=engine,
                    device_id=device_id,
                    base_stem=base_name,
                    canonical_slug=canonical_slug,
                    last_changed=last_changed,
                    confidence=conf,
                ))
            # FRIGATE-SUBLABEL-FACE-BRIDGE-1 (2026-09-06) D2: emit a
            # synthetic Frigate FaceLeg from the URA-owned MQTT latch
            # if a fresh (name, ts) exists for this base_stem. Additive
            # ONLY — designed to DEDUP with (not corroborate) any live
            # Frigate entity leg above, since Frigate's own sensor
            # resets after 60s via async_call_later.
            try:
                latch_entry = self._frigate_face_latch.get(base_name)
                if latch_entry is not None and FACE_NAME_LATCH_TTL_S > 0:
                    lname, lts = latch_entry
                    now = dt_util.utcnow()
                    age = (now - lts).total_seconds() if lts else None
                    if age is not None and age <= FACE_NAME_LATCH_TTL_S:
                        # canonicalize (mirrors the entity loop above).
                        try:
                            canonical = self._canonical_person_slug(lname)
                        except Exception:  # noqa: BLE001
                            canonical = ""
                        canonical_slug = canonical or None
                        # HIGH #4 (disagreement precedence): if a live
                        # ENTITY leg for the SAME base_stem already
                        # exists but names a DIFFERENT canonical_slug,
                        # the live entity wins — skip the synthetic
                        # entirely. A stale latch must not push a
                        # resolvable crossing to DISAGREE downstream.
                        _skip_synthetic = False
                        for _r in results:
                            if (
                                _r.base_stem == base_name
                                and _r.canonical_slug is not None
                                and canonical_slug is not None
                                and _r.canonical_slug != canonical_slug
                            ):
                                _skip_synthetic = True
                                break
                        if not _skip_synthetic:
                            # Choose the engine tag EXACTLY as the entity
                            # path would for this camera so the two dedup
                            # rather than count as two agreeing engines
                            # (would spuriously boost corroboration in
                            # transit_validator._resolve_egress_face_identity).
                            engine_tag: str | None = None
                            for _r in results:
                                if _r.engine in ("frigate", "frigate2"):
                                    engine_tag = _r.engine
                                    break
                            if engine_tag is None:
                                # F1 retired (memory: frigate1 retired /
                                # `_2` permanent) — default to the `_2`
                                # engine tag matching the live F2 entity.
                                _f2_eid = f"sensor.{base_name}_last_recognized_face_2"
                                _f1_eid = f"sensor.{base_name}_last_recognized_face"
                                try:
                                    _has_f2 = self.hass.states.get(_f2_eid) is not None
                                except Exception:  # noqa: BLE001
                                    _has_f2 = True
                                engine_tag = "frigate2" if _has_f2 else "frigate"
                                entity_sentinel = _f2_eid if _has_f2 else _f1_eid
                            else:
                                entity_sentinel = (
                                    f"sensor.{base_name}_last_recognized_face_2"
                                    if engine_tag == "frigate2"
                                    else f"sensor.{base_name}_last_recognized_face"
                                )
                            # Resolve device_id via the shared resolver
                            # (best-effort; None on failure).
                            _dev_id: str | None = None
                            try:
                                _resolver = None
                                if hasattr(self._camera_manager, "_get_resolver"):
                                    _resolver = self._camera_manager._get_resolver()
                                if _resolver is not None:
                                    _dev_id = _resolver.resolve_entity_to_device_id(
                                        entity_sentinel,
                                    )
                            except Exception:  # noqa: BLE001
                                _dev_id = None
                            synthetic = FaceLeg(
                                entity_id=entity_sentinel,
                                engine=engine_tag,
                                device_id=_dev_id,
                                base_stem=base_name,
                                canonical_slug=canonical_slug,
                                last_changed=lts,  # REQUIRED — classifier keys on it
                                confidence=None,   # passes FACE_MATCH_MIN_CONFIDENCE floor
                            )
                            # Dedup rule: if results already carries a leg
                            # with the same (canonical_slug, engine,
                            # base_stem), KEEP the fresher last_changed
                            # (mutate in place by replacement) instead of
                            # appending. A duplicate would double-count as
                            # agreement at transit_validator.py:1657.
                            _dup_idx: int | None = None
                            for _i, _r in enumerate(results):
                                if (
                                    _r.canonical_slug == synthetic.canonical_slug
                                    and _r.engine == synthetic.engine
                                    and _r.base_stem == synthetic.base_stem
                                ):
                                    _dup_idx = _i
                                    break
                            if _dup_idx is None:
                                results.append(synthetic)
                            else:
                                _existing = results[_dup_idx]
                                _existing_ts = _existing.last_changed
                                if (
                                    _existing_ts is None
                                    or (synthetic.last_changed is not None
                                        and synthetic.last_changed > _existing_ts)
                                ):
                                    results[_dup_idx] = synthetic
            except Exception:  # noqa: BLE001 — never fail the entity path
                _LOGGER.debug(
                    "_resolve_face_legs: frigate face latch emit raised "
                    "for base=%s", base_name, exc_info=True,
                )
        except Exception:  # noqa: BLE001 — fail-CLOSED: measure + return []
            self._face_lookup_missing_count += 1
            _LOGGER.debug(
                "_resolve_face_legs: unexpected error for base=%s",
                base_name, exc_info=True,
            )
            return []
        return results

    def _note_egress_identity_outcome(self, outcome: str) -> None:
        """EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28) D3: append one
        outcome to the rolling 24h deque, pruning older-than-24h entries
        on every append. Called by
        ``transit_validator._resolve_direction`` post-decision.
        """
        try:
            now_ts = dt_util.utcnow().timestamp()
        except Exception:  # noqa: BLE001
            now_ts = datetime.utcnow().timestamp()
        self._egress_identity_outcomes.append((now_ts, outcome))
        cutoff = now_ts - 86400.0
        d = self._egress_identity_outcomes
        while d and d[0][0] < cutoff:
            d.popleft()

    def _build_frigate_person_last_camera_map(self) -> dict[str, str]:
        """Build (once, memoised) a `frigate_person_key -> entity_id` map
        from the live entity registry.

        Frigate's `last_camera` per-person entities have unique_ids of the
        form `<ULID>:sensor_global_face:<PersonName>` where <PersonName>
        is the frigate face-library name in mixed case (e.g. `Oji`,
        `Ezinne`, `Jaya`, `Ziri`, `Default`). The URA-configured person
        slug (`oji_udezue`) does NOT match; matching is done by first-name
        lowercase (see caller). The observed entity_id carries the `_2`
        disambiguation suffix, so DO NOT construct it — enumerate.
        """
        result: dict[str, str] = {}
        try:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(self.hass)
        except Exception:  # noqa: BLE001 — HA lifecycle-defensive
            _LOGGER.debug(
                "D2: entity_registry unavailable; last_camera map empty",
                exc_info=True,
            )
            return result

        try:
            entries = er.async_entries_for_platform(registry, "frigate")
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "D2: async_entries_for_platform(frigate) failed; map empty",
                exc_info=True,
            )
            return result

        for entry in entries:
            eid = getattr(entry, "entity_id", "") or ""
            if not eid.startswith("sensor.frigate_"):
                continue
            # Match both `sensor.frigate_<name>_last_camera` and its `_2`
            # variant. The disambiguated variant is what the live system
            # actually exposes today (per plan review §3 registry probe).
            if not (
                eid.endswith("_last_camera")
                or eid.endswith("_last_camera_2")
            ):
                continue
            uid = getattr(entry, "unique_id", "") or ""
            # Format: <ULID>:sensor_global_face:<PersonName>
            parts = uid.split(":")
            if len(parts) != 3 or parts[1] != "sensor_global_face":
                _LOGGER.debug(
                    "D2: skipping frigate last_camera entry with unexpected "
                    "unique_id %r (entity_id=%s)",
                    uid,
                    eid,
                )
                continue
            key = parts[2].strip().lower()
            if not key:
                continue
            # Prefer the canonical (non-`_2`) form when both are present.
            existing = result.get(key)
            if existing and not existing.endswith("_2"):
                continue
            result[key] = eid

        _LOGGER.info(
            "D2 frigate last_camera map built: %d entries (%s)",
            len(result),
            sorted(result.keys()),
        )
        return result

    def _resolve_last_camera_entity_id(self, person_slug: str) -> str | None:
        """Resolve a URA person slug -> Frigate `last_camera` entity_id.

        Matching key is `person.name.split()[0].lower()` (first-name
        lowercase). Fail-CLOSED: returns None if no match; caller must NOT
        grant a face-based `identified` credit via this path.
        """
        # Defensive: some legacy tests construct PersonCensus via
        # `object.__new__` (bypassing __init__), so use getattr rather
        # than assuming the instance attribute is set.
        # B-HIGH-1 (review fix-up 2026-08-18): rebuild on EMPTY, not just
        # None. If the very first census tick runs before Frigate is in
        # the registry (or Frigate reloaded, or a person was added after
        # setup), the initial build returns {} and a memoise-on-None-only
        # scheme freezes that empty state forever — silently fail-CLOSED
        # for the life of the process. Rebuilding on empty is idempotent
        # (still ~5 registry entries) and self-heals as soon as Frigate
        # entries appear.
        cached = getattr(self, "_frigate_person_last_camera_map", None)
        if not cached:
            cached = self._build_frigate_person_last_camera_map()
            self._frigate_person_last_camera_map = cached
        # `person_slug` here is the URA slug (e.g. `oji_udezue`); the
        # frigate axis is first-name lowercase (e.g. `oji`). Use the leading
        # underscore-separated token as the match key.
        first_token = person_slug.split("_", 1)[0].strip().lower()
        if not first_token:
            return None
        resolved = self._frigate_person_last_camera_map.get(first_token)
        if resolved is None:
            # B-LOW-1 (review fix-up 2026-08-18): parallel-path telemetry.
            # The face resolver increments this counter on miss; the
            # last_camera resolver must too, otherwise a per-tick health
            # claim of 0 misses hides real fail-CLOSED events on the
            # last_camera axis (e.g. a URA person with no frigate face
            # library entry, or a post-reload window where the registry
            # is stale).
            try:
                self._face_lookup_missing_count += 1
            except AttributeError:
                # object.__new__ fixtures may not have set the attr.
                self._face_lookup_missing_count = 1
        return resolved

    def _get_face_recognized_persons(self) -> set[str]:
        """Return set of person IDs from Frigate face recognition sensors.

        Scans all Frigate cameras for sensor.*_last_recognized_face entities.
        If the sensor value is a recognized name (not empty, "unknown", or
        "unavailable"), adds it to the set.

        Only useful when Frigate is available. Returns empty set otherwise.

        Review FS-3 (2026-09-04): route through the central face-
        suppression checkpoint (``_face_suppressed_now``) so this raw
        producer — which feeds the ``face_ids`` union at
        ``_calculate_house_census`` (:1781) even when
        ``CONF_ENHANCED_CENSUS`` is False — is silenced under the D4
        fail-safe (drill / Frigate down / configured-but-absent).
        """
        if self._face_suppressed_now():
            return set()
        face_ids: set[str] = set()

        for camera_info in self._camera_manager.get_all_frigate_cameras():
            # Derive face recognition sensor from binary_sensor entity ID
            # binary_sensor.{name}_person_occupancy -> sensor.{name}_last_recognized_face
            bs_id = camera_info.entity_id
            if bs_id.endswith("_person_occupancy"):
                base_name = bs_id[len("binary_sensor."):-len("_person_occupancy")]
                # CENSUS-ACCURACY-1 D2: `_2`-suffix-tolerant resolver.
                face_sensor_id = self._resolve_face_entity_id(base_name)
                if face_sensor_id is None:
                    continue
                state = self.hass.states.get(face_sensor_id)
                if state and state.state.strip().lower() not in (
                    "unavailable", "unknown", "", "none", "no_match",
                ):
                    face_ids.add(state.state.strip())

        if face_ids:
            _LOGGER.debug("Face recognition identified: %s", face_ids)

        return face_ids

    def _get_face_recognized_persons_fresh(self, now: datetime) -> set[str]:
        """Freshness-gated view of face-recognized persons.

        B-HIGH-1 (2026-08-01 fix-up): the plain
        ``_get_face_recognized_persons`` has no age check — a
        recognition from hours ago will still corroborate a live
        divergence, defeating the whole downgrade. This wrapper drops
        entries whose ``state.last_changed`` age exceeds
        ``CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`` (same window the
        provenance path at ~l.2392 uses), returning only currently
        actionable identities. Used only by the corroboration bundle;
        the other consumer keeps the unfiltered accessor to avoid
        silently altering that surface without its own review.
        """
        fresh: set[str] = set()
        for camera_info in self._camera_manager.get_all_frigate_cameras():
            bs_id = camera_info.entity_id
            if not bs_id.endswith("_person_occupancy"):
                continue
            base_name = bs_id[len("binary_sensor."):-len("_person_occupancy")]
            # CENSUS-ACCURACY-1 D2: `_2`-suffix-tolerant resolver.
            face_sensor_id = self._resolve_face_entity_id(base_name)
            if face_sensor_id is None:
                continue
            try:
                state = self.hass.states.get(face_sensor_id)
            except Exception:  # noqa: BLE001 — best-effort corroboration read
                continue
            if not state:
                continue
            val = state.state.strip() if isinstance(state.state, str) else ""
            if val.lower() in ("unavailable", "unknown", "", "none", "no_match"):
                continue
            last_changed = getattr(state, "last_changed", None)
            if last_changed is None:
                # No timestamp → cannot verify freshness → treat as stale
                continue
            try:
                if last_changed.tzinfo is not None:
                    age = (now - last_changed).total_seconds()
                else:
                    age = (now - last_changed.replace(
                        tzinfo=dt_util.UTC
                    )).total_seconds()
            except (TypeError, AttributeError):
                continue
            if age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS:
                fresh.add(val)
        if fresh:
            _LOGGER.debug(
                "Face recognition (fresh, corroboration): %s", fresh,
            )
        return fresh

    # ------------------------------------------------------------------
    # EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 — egress-face identity register.
    # ------------------------------------------------------------------

    @staticmethod
    def _first_token_lower(name: Any) -> str:
        """Low-level helper: strip / lowercase / take pre-underscore token.
        Used for FIRST-TOKEN matching against tracked-persons slugs — NOT
        the canonical namespace itself (see `_canonical_person_slug`)."""
        if not name:
            return ""
        s = str(name).strip().lower()
        if not s:
            return ""
        return s.split("_", 1)[0]

    def _get_tracked_person_slugs(self) -> list[str]:
        """Return the URA-slug list from the integration config (with
        the ``person.`` prefix stripped). Mirrors the derivation in
        `_get_face_recognized_person_names` (:3402-3411)."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                raw = merged.get("tracked_persons", []) or []
                out: list[str] = []
                for p in raw:
                    slug = str(p).replace("person.", "").strip().lower()
                    if slug:
                        out.append(slug)
                return out
        return []

    def _canonical_person_slug(self, name: Any) -> str:
        """Canonicalize a person identifier to the URA person-slug namespace
        (Review A-HIGH-1 / A-MED-1 / B-MED-1 / B-MED-2 fix).

        The URA slug (e.g. ``"oji_udezue"``) is the namespace used by
        `_get_face_recognized_person_names` (returns URA slugs) and by
        `ble_persons` — both consumed at the enhanced-house recompute
        (:3510). Publishing `identified_persons`, the DB `person_id`,
        and the veto's `person.<slug>` lookup on any OTHER namespace
        (e.g. first-name only) produces silent divergence — the veto
        never fires against `person.oji_udezue`, DB rows carry `"Oji"`
        while census carries `"oji"`, and residents whose first names
        collide are counted once.

        Mapping rules:
          - Empty / None -> "".
          - If ``name`` (lowercased, stripped) matches a tracked_persons
            slug directly -> return that slug (already URA-canonical).
          - Else: match by FIRST TOKEN against each tracked slug's first
            token (Frigate face-library first names like ``"Oji"`` map
            to ``"oji_udezue"``). D-MED-2 (2026-08-18): if MORE THAN
            ONE tracked slug shares that first token, return "" (fail
            CLOSED — no identity attached) and log a warning ONCE per
            ambiguous head. Attaching to whichever tracked slug happens
            to be first in config would silently merge two residents
            into one and understate identified_count.
          - Else: pass-through the lowercased/stripped input. Preserves
            unmapped identifiers rather than collapsing them silently.

        Supported-configuration constraint: ``tracked_persons`` first
        names (pre-underscore tokens) SHOULD be unique for identity
        attribution to route via first-name match. If they are not,
        identities colliding on the first name will fail-CLOSED (no
        credit) and log a warning once at the first collision.
        """
        if not name:
            return ""
        s = str(name).strip().lower()
        if not s:
            return ""
        tracked = self._get_tracked_person_slugs()
        # Direct-match (already URA-canonical, incl. any casing).
        if s in tracked:
            return s
        # First-token match.
        head = s.split("_", 1)[0]
        matches = [slug for slug in tracked if slug.split("_", 1)[0] == head]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # D-MED-2 fail-CLOSED on ambiguity. Warn once per head so a
            # misconfigured deployment gets one loud signal, not spam.
            if head not in self._canonicalizer_ambiguity_warned:
                self._canonicalizer_ambiguity_warned.add(head)
                _LOGGER.warning(
                    "canonicalizer: ambiguous first-name '%s' matches "
                    "multiple tracked_persons slugs %s — no identity "
                    "attached (fail-CLOSED). Rename or drop one entry "
                    "so first names are unique for identity attribution.",
                    head, matches,
                )
            return ""
        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D3: known-face-guest
        # namespace. When first-token doesn't map to any tracked slug,
        # check the operator-configured `known_face_guests` list (case-
        # insensitive first-token match) and return `guest:<head>` so
        # downstream consumers can distinguish a face-recognized guest
        # (Ojini) from an unmapped stranger. H2 precedence: tracked
        # slugs win — this branch only runs when the tracked-slug
        # attempts above ALL missed.
        try:
            guests = self._get_known_face_guests()
        except Exception:  # noqa: BLE001 — options read is best-effort
            guests = []
        for g in guests:
            g_head = str(g).strip().lower().split("_", 1)[0]
            if g_head and g_head == head:
                return f"guest:{head}"
        # Fallback: preserve the (lowercased) identifier verbatim.
        return s

    def _get_known_face_guests(self) -> list[str]:
        """Return operator-configured `known_face_guests` list from the
        INTEGRATION entry options. See D3 in the plan §3.3."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                raw = merged.get(CONF_KNOWN_FACE_GUESTS, DEFAULT_KNOWN_FACE_GUESTS) or []
                out: list[str] = []
                for name in raw:
                    if not name:
                        continue
                    s = str(name).strip()
                    if s:
                        out.append(s)
                return out
        return list(DEFAULT_KNOWN_FACE_GUESTS)

    # Back-compat alias — external callers historically used the old name.
    def _normalize_person_name(self, name: Any) -> str:
        return self._canonical_person_slug(name)

    def _normalize_name_set(self, names) -> set[str]:
        """Canonicalize each name to the URA person-slug namespace and
        return as a set. Empties dropped. Safe on None."""
        out: set[str] = set()
        if not names:
            return out
        for n in names:
            norm = self._canonical_person_slug(n)
            if norm:
                out.add(norm)
        return out

    def _is_egress_identity_enabled(self) -> bool:
        """Read the EGRESS_IDENTITY_ENABLED kill switch from options.

        Default True (post-CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 ship,
        2026-08-18); operator kill-switch is
        `switch.ura_name_people_at_doors`. Fresh-read at every call —
        no cache — so a toggle from the device switch or the options
        flow takes effect on the next crossing without a reload.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(
                    merged.get(
                        CONF_EGRESS_IDENTITY_ENABLED,
                        DEFAULT_EGRESS_IDENTITY_ENABLED,
                    )
                )
        return DEFAULT_EGRESS_IDENTITY_ENABLED

    def register_egress_face(
        self, name: str, ts: datetime | None = None,
        provenance: str = "face",
    ) -> None:
        """Record a face-identified egress crossing so the census union
        fuses this identity for up to ``EGRESS_FACE_UNION_TTL_S``.

        Called by ``transit_validator.EgressDirectionTracker`` at emit
        time after ``_resolve_egress_face_identity`` returns a slug.
        The name is canonicalized to the URA person-slug namespace (I5)
        so union with `face_ids`/`ble_ids` deduplicates by identity.
        No-op on empty/blank input.

        Thread-safety (C-LOW-2): MUST be called from the event loop;
        `self._egress_face_ids` dict access is not thread-safe.

        Kill-switch: no-op when EGRESS_IDENTITY_ENABLED is False.
        """
        if not self._is_egress_identity_enabled():
            return
        norm = self._canonical_person_slug(name)
        if not norm:
            return
        # A-LOW-2 (2026-08-18): normalize tz-naive timestamps to UTC so a
        # later `(now - ts)` in `_get_egress_face_ids_fresh` cannot raise
        # TypeError and silently drop the entry.
        if ts is None:
            ts = dt_util.now()
        elif getattr(ts, "tzinfo", None) is None:
            _LOGGER.info(
                "register_egress_face: coercing tz-naive ts to UTC for %s",
                norm,
            )
            ts = ts.replace(tzinfo=dt_util.UTC)
        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D3/H1: guest slugs
        # (`guest:*`) live in a SEPARATE ledger so identified_count
        # (resident scope) is never inflated by a face-recognized guest.
        if norm.startswith("guest:"):
            self._egress_guest_ids[norm] = ts
            # Bound guest ledger too.
            if len(self._egress_guest_ids) > 32:
                self._get_egress_guest_ids_fresh(dt_util.utcnow())
            _LOGGER.info(
                "Egress-face GUEST identity registered for census union: %s "
                "(TTL=%ds, provenance=%s)",
                norm, EGRESS_FACE_UNION_TTL_S, provenance,
            )
            return
        self._egress_face_ids[norm] = ts
        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D4: remember provenance
        # so the fresh reader can gate face-provenance names under the
        # face-producer-down fail-safe while keeping BLE-provenance
        # registrations live.
        # Review A-LOW-2 (2026-09-04): admit the "ble+face" tag
        # emitted by the corroborated branch in transit_validator; only
        # coerce genuinely unknown values to "face".
        _prov = provenance if isinstance(provenance, str) else "face"
        self._egress_face_ids_provenance[norm] = (
            _prov if _prov in ("face", "ble", "ble+face") else "face"
        )
        # C-LOW-1: register-time TTL prune backstop so the dict stays
        # bounded even if readers stop firing.
        if len(self._egress_face_ids) > 32:
            self._get_egress_face_ids_fresh(dt_util.utcnow())
        _LOGGER.info(
            "Egress-face identity registered for census union: %s "
            "(TTL=%ds)",
            norm,
            EGRESS_FACE_UNION_TTL_S,
        )

    def evict_egress_face(self, name: str) -> None:
        """Remove any prior egress-face registration for ``name`` (B-CRIT-1
        eviction on exit — a resident who walked in then walked out
        within the TTL must not remain in the census union).

        No-op on empty/blank input or when the identity is not present.
        """
        norm = self._canonical_person_slug(name)
        if not norm:
            return
        if norm.startswith("guest:"):
            if self._egress_guest_ids.pop(norm, None) is not None:
                _LOGGER.info(
                    "Egress-face GUEST identity evicted from census union: %s "
                    "(exit crossing)",
                    norm,
                )
            return
        if self._egress_face_ids.pop(norm, None) is not None:
            self._egress_face_ids_provenance.pop(norm, None)
            _LOGGER.info(
                "Egress-face identity evicted from census union: %s "
                "(exit crossing)",
                norm,
            )

    def _get_egress_face_ids_fresh(self, now: datetime) -> set[str]:
        """Return the currently fresh egress-face names, pruning entries
        older than ``EGRESS_FACE_UNION_TTL_S``. Read at BOTH census union
        writers (raw `:1855` and enhanced house recompute) per
        plan-review C-CRIT-1 — fusing only one is a house-level no-op.

        Kill-switch: returns an empty set when EGRESS_IDENTITY_ENABLED is
        False, so both fuse sites are byte-identical to pre-cycle behaviour.
        """
        if not self._is_egress_identity_enabled():
            return set()
        if not self._egress_face_ids:
            return set()
        ttl = EGRESS_FACE_UNION_TTL_S
        stale: list[str] = []
        for n, ts in self._egress_face_ids.items():
            try:
                age = (now - ts).total_seconds()
            except (TypeError, AttributeError):
                stale.append(n)
                continue
            if age > ttl or age < 0:
                stale.append(n)
        for n in stale:
            self._egress_face_ids.pop(n, None)
            self._egress_face_ids_provenance.pop(n, None)
        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D4/H1: when
        # STRICT is ON AND the face producer is not live, exclude
        # face-provenance entries. BLE-provenance entries survive.
        strict = self._is_egress_identity_failsafe_strict()
        if strict and not self._is_face_producer_live():
            visible = {
                n for n in self._egress_face_ids.keys()
                if self._egress_face_ids_provenance.get(n, "face")
                in ("ble", "ble+face")
            }
            return visible
        return set(self._egress_face_ids.keys())

    def _get_egress_guest_ids_fresh(self, now: datetime) -> set[str]:
        """Return currently fresh `guest:*` egress-face names (D3/H1),
        pruning entries older than ``EGRESS_FACE_UNION_TTL_S``. Under
        face-producer-outage + STRICT the set is empty (guests are
        face-only by construction — no BLE provenance path exists)."""
        if not self._is_egress_identity_enabled():
            return set()
        if not self._egress_guest_ids:
            return set()
        strict = self._is_egress_identity_failsafe_strict()
        if strict and not self._is_face_producer_live():
            return set()
        ttl = EGRESS_FACE_UNION_TTL_S
        stale: list[str] = []
        for n, ts in self._egress_guest_ids.items():
            try:
                age = (now - ts).total_seconds()
            except (TypeError, AttributeError):
                stale.append(n)
                continue
            if age > ttl or age < 0:
                stale.append(n)
        for n in stale:
            self._egress_guest_ids.pop(n, None)
        return set(self._egress_guest_ids.keys())

    # ------------------------------------------------------------------
    # IDENTITY-FUSION-PRODUCER-1 (2026-09-04): D2 BLE-transition leg,
    # D4 face-producer health + drill guard. See
    # docs/planning/PLANNING_identity_fusion_producer_2026_09.md.
    # ------------------------------------------------------------------

    def _is_egress_identity_failsafe_strict(self) -> bool:
        """Read `CONF_EGRESS_IDENTITY_FAILSAFE_STRICT` from options.
        Default True. Kill-switch that ENABLES the D4 provenance
        filter + producer-health guard (see plan §6)."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(merged.get(
                    CONF_EGRESS_IDENTITY_FAILSAFE_STRICT,
                    DEFAULT_EGRESS_IDENTITY_FAILSAFE_STRICT,
                ))
        return DEFAULT_EGRESS_IDENTITY_FAILSAFE_STRICT

    def _is_face_producer_live(self) -> bool:
        """D4 §0 read-time producer-health gate (Review FS-1 fix).

        Returns False when any of the following holds; caller (resolver
        / union) MUST drop face-provenance legs and names in that case.

          - The on-demand drill switch is engaged (Review DL-1: read
            from ``hass.data[DOMAIN]["face_drill_forced"]``).
          - The face-producer health entity resolves to a real HA
            entity AND reports ``unavailable`` / ``unknown``.
          - The face-producer health entity is unresolved BUT Frigate
            cameras ARE configured (configured-but-absent -> DOWN,
            fail-CLOSED per operator directive).

        Fail-OPEN + startup WARNING (once) when the health entity is
        genuinely unconfigured (no Frigate cameras enumerated) — the
        gate is INERT in that deployment because there are no face
        producers to guard.

        Health entity is resolved via the entity registry (not a
        string-built `_2` id — memory
        ``reference_frigate1_retired_2suffix_permanent``). First
        resolved id is cached; a fresh resolution attempt runs if the
        cache is empty.

        Read-time only — no timers, no suppression, restart-safe.
        Populates ``_face_producer_health_reason`` so the diagnostic
        sensor can distinguish ``drill_forced`` vs natural causes.
        """
        # Drill takes precedence and its reason survives every branch.
        if self.get_face_drill_forced(self.hass):
            self._face_producer_health_reason = "drill_forced"
            self._face_dropped_drill_forced_count += 1
            return False
        ent_id = self._resolve_face_producer_health_entity()
        if ent_id is None:
            # No resolvable health entity. Is Frigate configured?
            configured = False
            try:
                configured = bool(
                    self._camera_manager.get_all_frigate_cameras()
                )
            except Exception:  # noqa: BLE001
                configured = False
            if configured:
                # Configured-but-absent -> fail-CLOSED (DOWN). This is
                # the operator-mandated behaviour per Review FS-1:
                # a deployment that HAS Frigate cameras but no status
                # entity is unhealthy, not "unknown".
                self._face_producer_health_reason = (
                    "frigate_status_missing_configured"
                )
                return False
            # Genuinely unconfigured -> inert. One-time WARNING so this
            # is not silent (Review FS-1).
            self._face_producer_health_reason = "inert_no_frigate"
            if not self._face_producer_startup_warned:
                _LOGGER.warning(
                    "Face-producer health entity not present AND no "
                    "Frigate cameras enumerated — egress-identity "
                    "face fail-safe is INERT for this deployment. "
                    "Configure `sensor.frigate_status[_2]` if Frigate "
                    "IS present so the D4 gate can protect emissions.",
                )
                self._face_producer_startup_warned = True
            return True
        try:
            st = self.hass.states.get(ent_id)
        except Exception:  # noqa: BLE001
            st = None
        if st is None:
            # Resolved via registry, but state disappeared: treat DOWN
            # (fail-CLOSED).
            self._face_producer_health_reason = "frigate_status_state_missing"
            return False
        val = st.state if isinstance(st.state, str) else ""
        if val.strip().lower() in ("unavailable", "unknown", "", "none"):
            self._face_producer_health_reason = "frigate_down"
            return False
        self._face_producer_health_reason = "live"
        return True

    def _resolve_face_producer_health_entity(self) -> str | None:
        """Resolve the Frigate producer-health entity via the entity
        registry (Review FS-1). Prefers ``sensor.frigate_status_2`` per
        the retired-Frigate-1 memory, then falls back through the four
        historically-plausible ids. Cached on first hit; if none
        resolve, returns ``None`` (caller distinguishes configured-vs-
        unconfigured Frigate).
        """
        if self._face_producer_health_resolved:
            return self._face_producer_health_entity
        try:
            ent_reg = er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            ent_reg = None
        candidates = (
            "sensor.frigate_status_2",
            "sensor.frigate_status",
            "binary_sensor.frigate_status_2",
            "binary_sensor.frigate_status",
        )
        resolved: str | None = None
        for candidate in candidates:
            entry = None
            if ent_reg is not None:
                try:
                    entry = ent_reg.async_get(candidate)
                except Exception:  # noqa: BLE001
                    entry = None
            if entry is None:
                continue
            # An entity_registry entry alone is insufficient (the test
            # harness's MagicMock registry returns truthy for anything).
            # Require a matching live state — a real HA registry entry
            # always has one. Absence -> keep looking.
            try:
                st = self.hass.states.get(candidate)
            except Exception:  # noqa: BLE001
                st = None
            if st is None:
                continue
            resolved = candidate
            break
        # Self-heal: only LATCH when resolution succeeded. If the
        # producer entity has not yet appeared (boot-ordering race —
        # census can tick seconds before frigate_status_2 acquires a
        # state), leave the cache unset so the next tick re-runs this
        # cheap registry+state lookup and recovers without a restart.
        # Once resolved to a real id, the flag latches for the session
        # and later up/down is handled by the state-based branch in
        # _is_face_producer_live (`frigate_down` /
        # `frigate_status_state_missing`).
        if resolved is not None:
            self._face_producer_health_entity = resolved
            self._face_producer_health_resolved = True
        return resolved

    def _face_suppressed_now(self) -> bool:
        """Central Review FS checkpoint. Every face-emission site MUST
        gate on this helper. Returns True iff STRICT is ON AND the
        face producer is not live (drill engaged, Frigate down, or
        configured-but-absent). Callers substitute an empty
        set/list/None for face-provenance results when True.
        """
        try:
            if not self._is_egress_identity_failsafe_strict():
                return False
        except Exception:  # noqa: BLE001
            # STRICT unreadable -> default True (fail-closed on gate).
            pass
        try:
            return not self._is_face_producer_live()
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def get_face_drill_forced(hass: HomeAssistant) -> bool:
        """Read the drill flag from ``hass.data[DOMAIN]`` (Review DL-1).
        Survives INTEGRATION reload; a rebuilt ``PersonCensus`` picks
        up the same value with no re-apply needed.
        """
        try:
            return bool(
                hass.data.get(DOMAIN, {}).get("face_drill_forced", False)
            )
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def set_face_drill_forced(hass: HomeAssistant, value: bool) -> None:
        """Write the drill flag on ``hass.data[DOMAIN]`` (Review DL-1)."""
        try:
            hass.data.setdefault(DOMAIN, {})["face_drill_forced"] = bool(value)
        except Exception:  # noqa: BLE001
            pass

    def is_face_leg_person_vetoed(self, leg) -> bool:
        """Review FS-2 helper: mirror of the existing
        ``person.<slug> = not_home`` veto at :4269-4290 for the
        resolver's leg-set path. Fail-OPEN when the person entity is
        missing/unknown/unavailable (matches the enhanced-census
        pattern). Consulted by ``transit_validator`` before admitting a
        face leg to the classifier.
        """
        try:
            slug = getattr(leg, "canonical_slug", None) or ""
        except Exception:  # noqa: BLE001
            return False
        if not slug or slug.startswith("guest:"):
            return False
        try:
            person_state = self.hass.states.get(f"person.{slug.lower()}")
        except Exception:  # noqa: BLE001
            person_state = None
        if person_state is None:
            return False
        try:
            return getattr(person_state, "state", None) == "not_home"
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 rev5 (2026-09-05)
    # ------------------------------------------------------------------

    # Rev5 fix-up (D-6): the `_VALID_HA_HOME_STATES` placeholder had
    # no readers and has been removed. The state gate in
    # `_on_crossing_tracker_state_change` names the admitted strings
    # inline; subscription IS the provenance gate (D-8): a tracker
    # flipping source_type is caught on the next refresh tick.

    def _derive_ble_crossing_trackers(self) -> dict[str, str]:
        """rev5 D1: return a tracker_id -> slug map of the resident
        device_trackers whose LIVE ``source_type == "bluetooth_le"``.

        For each slug in :meth:`_get_tracked_person_slugs`, read
        ``person.<slug>.attributes["device_trackers"]`` and keep only
        the tracker ids whose live-state ``source_type`` (lower-cased)
        equals ``bluetooth_le``. Non-bluetooth_le trackers (GPS phones,
        wall tablets, routers) are silently excluded — subscription IS
        the provenance gate for the crossing producer.

        INV-EGRESS-ID: slug MUST be one of ``_get_tracked_person_slugs``;
        this is guaranteed by construction (we iterate that list). A
        one-time WARNING is emitted for any tracked slug that derives
        ZERO bluetooth_le trackers (fatal for a single-BLE-tracker
        resident such as oji).

        READ-PATTERN reference: ``person_coordinator._read_source_inventory``
        (person_coordinator.py:206-243) — NOT reusable directly (it is a
        PersonCoordinator method with no bluetooth_le branch).
        """
        out: dict[str, str] = {}
        # EGRESS-EXIT-IDENTITY-BACKFILL-1 — freshly-built set each pass
        # (invariant e: rebuilt, never accumulated).
        zero_tracker_slugs_this_pass: set[str] = set()
        try:
            slugs = self._get_tracked_person_slugs()
        except Exception:  # noqa: BLE001
            slugs = []
        # Track which known-BLE trackers are still listed against a
        # person this pass; anything absent gets pruned from
        # `_known_ble_trackers` (rev5 fix-up D-1a).
        seen_known: set[str] = set()
        for slug in slugs:
            if not slug:
                continue
            try:
                person_state = self.hass.states.get(f"person.{slug}")
            except Exception:  # noqa: BLE001
                person_state = None
            trackers: list = []
            if person_state is not None:
                try:
                    attrs = getattr(person_state, "attributes", None) or {}
                    trackers = list(attrs.get("device_trackers") or [])
                except Exception:  # noqa: BLE001
                    trackers = []
            slug_ble_count = 0
            for tracker_id in trackers:
                if not tracker_id:
                    continue
                tid = str(tracker_id)
                try:
                    ts_state = self.hass.states.get(tid)
                except Exception:  # noqa: BLE001
                    ts_state = None
                src_type = ""
                live_available = False
                if ts_state is not None:
                    try:
                        t_state = str(getattr(ts_state, "state", "") or "").lower()
                        live_available = t_state not in ("", "unknown", "unavailable")
                        t_attrs = getattr(ts_state, "attributes", None) or {}
                        src_type = str(t_attrs.get("source_type", "") or "").lower()
                    except Exception:  # noqa: BLE001
                        src_type = ""
                        live_available = False
                # Sticky classification (rev5 fix-up D-1a). A tracker
                # once seen as bluetooth_le stays admitted while it is
                # still on this person's `device_trackers` — even
                # while unavailable / stateless — UNLESS it is
                # currently AVAILABLE with a different (non-empty)
                # source_type, which demotes it.
                is_ble_live = (src_type == "bluetooth_le")
                is_ble_sticky = (
                    self._known_ble_trackers.get(tid) == slug
                    and not (live_available and src_type and src_type != "bluetooth_le")
                )
                if is_ble_live or is_ble_sticky:
                    # A-LOW-2: warn once on cross-slug collision.
                    prior = out.get(tid)
                    if prior is not None and prior != slug and tid not in self._ble_tracker_id_collision_warned:
                        _LOGGER.warning(
                            "rev5 BLE producer: tracker_id %s derives to "
                            "multiple slugs (%s vs %s); last-writer-wins "
                            "would mask a config bug — please investigate.",
                            tid, prior, slug,
                        )
                        self._ble_tracker_id_collision_warned.add(tid)
                    out[tid] = slug
                    slug_ble_count += 1
                    if is_ble_live:
                        # Refresh sticky record on any live BLE hit.
                        self._known_ble_trackers[tid] = slug
                    seen_known.add(tid)
                elif live_available and src_type and src_type != "bluetooth_le":
                    # Confirmed non-BLE while available → demote.
                    if self._known_ble_trackers.pop(tid, None) is not None:
                        _LOGGER.info(
                            "rev5 BLE producer: tracker %s demoted from "
                            "bluetooth_le (source_type=%s)", tid, src_type,
                        )
            if slug_ble_count == 0:
                zero_tracker_slugs_this_pass.add(slug)
            if slug_ble_count == 0 and slug not in self._ble_zero_tracker_warned:
                _LOGGER.warning(
                    "rev5 BLE producer: tracked slug %s derives ZERO "
                    "bluetooth_le trackers (person.%s device_trackers=%r). "
                    "Egress attribution for this resident will not fire "
                    "until a bluetooth_le tracker becomes visible.",
                    slug, slug, trackers,
                )
                self._ble_zero_tracker_warned.add(slug)
        # Prune sticky-BLE entries whose tracker_id no longer appears
        # on any tracked resident's `device_trackers` (rev5 D-1a).
        for tid in list(self._known_ble_trackers.keys()):
            if tid not in seen_known:
                self._known_ble_trackers.pop(tid, None)
        # EGRESS-EXIT-IDENTITY-BACKFILL-1: publish this pass's fresh
        # zero-tracker set (assign, do NOT union).
        self._ble_zero_tracker_slugs = zero_tracker_slugs_this_pass
        return out

    @callback
    def _on_crossing_tracker_state_change(self, event) -> None:
        """rev5 D1: BLE crossing edge handler. Fires on a state_changed
        event for one of the derived bluetooth_le device_trackers.

        STATE GATE — admit only when ALL hold:
          - both ``old_state`` and ``new_state`` are present objects,
          - ``old.state != new.state``,
          - ``"home" in {old.state, new.state}`` (home-boundary edge),
          - BOTH sides are one of ``"home"``, ``"not_home"``, or a
            named zone (any other lower-alphanum string is treated as
            a zone name). If either side is ``unknown`` / ``unavailable``
            / ``None`` / ``""``, drop and increment
            ``_ble_edge_dropped_invalid_count``. This blocks BOTH
            unavailable-forge legs and zone->zone (both-away) forged
            legs.

        v1 ENTRY-ONLY: only ``new == "home"`` (arriving) produces a
        leg. A departing edge (``old == "home"``, ``new != "home"``) is
        counted in ``_ble_departing_edge_seen_count`` for observability
        only — exit attribution is deferred to card
        ``EGRESS-EXIT-IDENTITY-BACKFILL-1``.
        """
        try:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
        except Exception:  # noqa: BLE001
            return
        if new_state is None:
            # No new state at all — nothing to attribute; benign.
            self._ble_edge_dropped_benign_count += 1
            return
        try:
            new_s = str(getattr(new_state, "state", "") or "").lower()
        except Exception:  # noqa: BLE001
            self._ble_edge_dropped_invalid_count += 1
            return
        if old_state is None:
            # First-write / entity-add / restart transient: HA fires a
            # state_changed with old_state=None. Benign — do NOT count
            # against the forgery-shaped drop counter (rev5 D-7). We
            # also DO NOT synthesise an arrival from a bare add: only
            # a live post-add edge to "home" (handled next tick) counts.
            self._ble_edge_dropped_benign_count += 1
            return
        try:
            old_s = str(getattr(old_state, "state", "") or "").lower()
        except Exception:  # noqa: BLE001
            self._ble_edge_dropped_invalid_count += 1
            return
        _BAD = {"", "unknown", "unavailable", "none"}
        if new_s == old_s:
            # Not a boundary; silently ignore.
            return
        # Rev5 fix-up (D-1b): ADMIT `unavailable|unknown|not_home|zone → home`
        # as an arriving edge. The old side being missing/degraded on an
        # arrival is not a forge — only the NEW side matters, and
        # subscription IS the provenance gate. This restores oji's
        # `unavailable → home` arrivals that the strict old_s gate dropped.
        if new_s == "home":
            # Any non-home old_s (including bad-set members) → arrival.
            pass
        elif old_s == "home":
            # Departing edge (home → *). Reject when new_s is bad —
            # not a real boundary, likely a producer flap.
            if new_s in _BAD:
                self._ble_edge_dropped_invalid_count += 1
                return
        else:
            # Neither side is "home". Legitimate zone->zone (both-away)
            # is benign for the crossing producer — count it separately
            # (rev5 D-7). Bad-set members on either side stay forgery-shaped.
            if new_s in _BAD or old_s in _BAD:
                self._ble_edge_dropped_invalid_count += 1
                return
            self._ble_edge_dropped_benign_count += 1
            return
        # Both sides are non-empty, non-unknown, and one side is "home"
        # → the other side is "not_home" or a named zone. Admit.
        tracker_id = getattr(new_state, "entity_id", "") or ""
        slug = self._ble_tracker_slug_map.get(tracker_id, "")
        if not slug:
            # Received an edge for a tracker we no longer track (map
            # drift). Drop silently; the next refresh reconciles.
            return
        # INV-EGRESS-ID guard.
        try:
            tracked = set(self._get_tracked_person_slugs())
        except Exception:  # noqa: BLE001
            tracked = set()
        if slug not in tracked:
            # A-1 (2026-09-06): count the INV-EGRESS-ID map-drift drop
            # — this is the redefined meaning of the ambiguity/abstain
            # counter (the prior competing-edge abstain retired with
            # EGRESS-EXIT-COMULTI-DEPART-1). Without this incrementer
            # the sensor attribute is permanently 0 and the drop is
            # invisible.
            self._ble_exit_ambiguity_abstain_count += 1
            _LOGGER.warning(
                "rev5 BLE producer: dropping edge for slug %s — not in "
                "tracked_persons %r (map drift?)", slug, sorted(tracked),
            )
            return
        try:
            ts = getattr(new_state, "last_changed", None) or dt_util.utcnow()
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=dt_util.UTC)
        except Exception:  # noqa: BLE001
            ts = dt_util.utcnow()
        if new_s == "home":
            # v1 ENTRY-ONLY: attribute the arriving boundary.
            leg = BleTransitionLeg(
                person_slug=slug,
                transition_ts=ts,
                direction="arriving",
                engine="ble",
                confidence=BLE_TRANSITION_CONFIDENCE,
                provenance="ble",
                source_entity=tracker_id,
            )
            self._ble_transition_cache.append(leg)
            self._ble_legs_produced_count += 1
            _LOGGER.info(
                "rev5 BLE arriving leg: person=%s tracker=%s old=%s new=%s",
                slug, tracker_id, old_s, new_s,
            )
        else:
            # Departing boundary — count and schedule the async
            # backfill of any in-window null exit crossing
            # (EGRESS-EXIT-IDENTITY-BACKFILL-1).
            self._ble_departing_edge_seen_count += 1
            _LOGGER.debug(
                "rev5 BLE departing edge: person=%s tracker=%s old=%s new=%s",
                slug, tracker_id, old_s, new_s,
            )
            # naive-UTC form for cooldown + competing-edge bookkeeping.
            try:
                t_edge_naive = ts.astimezone(timezone.utc).replace(
                    tzinfo=None
                )
            except Exception:  # noqa: BLE001
                t_edge_naive = ts.replace(tzinfo=None) if getattr(
                    ts, "tzinfo", None
                ) else ts
            # Per-slug cooldown (fix-up: multi-tracker dedup). A phone +
            # watch on the same person will fire two edges from one
            # physical departure; only the FIRST reaches the DAO.
            cooldown_win = timedelta(seconds=BLE_EXIT_PER_SLUG_COOLDOWN_S)
            last_edge = self._ble_exit_last_edge_by_slug.get(slug)
            if last_edge is not None and (
                t_edge_naive - last_edge
            ) < cooldown_win:
                self._ble_exit_per_slug_cooldown_skipped_count += 1
                _LOGGER.debug(
                    "exit-backfill: cooldown-skip slug=%s last=%s new=%s",
                    slug, last_edge.isoformat(), t_edge_naive.isoformat(),
                )
                return
            self._ble_exit_last_edge_by_slug[slug] = t_edge_naive
            # EGRESS-EXIT-COMULTI-DEPART-1 (2026-09-06): the recent-
            # departing-edges deque + distinct-departer scan are
            # retired. Each edge is its own certain-WHO; co-departure
            # is reconciled via the retry-claim loop in
            # `_backfill_exit_identity`.
            try:
                task = self.hass.async_create_task(
                    self._backfill_exit_identity(slug, ts, tracker_id)
                )
                self._backfill_tasks.add(task)
                task.add_done_callback(self._backfill_tasks.discard)
            except Exception:  # noqa: BLE001
                self._ble_exit_error_count += 1
                _LOGGER.debug(
                    "exit-backfill: failed to schedule task for %s",
                    slug, exc_info=True,
                )

    async def _backfill_exit_identity(
        self, slug: str, t_edge, tracker_id: str | None = None,
    ) -> None:
        """EGRESS-EXIT-IDENTITY-BACKFILL-1 (+ EGRESS-EXIT-COMULTI-
        DEPART-1, 2026-09-06) — attribute `slug` to the nearest
        in-window null-`person_id` exit crossing.

        Each BLE `not_home` edge is its own certain-WHO (a resident's
        OWN tracker). Co-departure is two such edges producing two
        distinct null rows — BOTH get named their own slug. Ordering:
          1. fixed settle (`BLE_EXIT_DEPARTURE_SETTLE_S`, overridable
             via `_exit_settle_s` for tests) — retains the flap guard;
          2. tracker live re-read — abort if returned to home
             (flap, not a real departure — the wrong-WHO guard);
          3. retry-claim loop (SELECT nearest unconsumed null → UPDATE
             with IS-NULL claim; on `changed==0` re-SELECT and try
             the next row, bounded by `BLE_EXIT_CLAIM_MAX_ATTEMPTS`).
             The DAO's `WHERE id=? AND person_id IS NULL` prevents a
             double-WRITE; the retry loop reconciles the two edges
             onto two distinct rows despite same first-SELECT.

        TZ CONTRACT: the INSERT at database.py:3919 writes
        ``datetime.utcnow().isoformat()`` (NAIVE-UTC, no offset). We
        MUST derive the SELECT bounds identically or the comparison
        silently returns zero matches.
        """
        try:
            # tz-safe naive-UTC bounds (F2 in the plan).
            if getattr(t_edge, "tzinfo", None) is not None:
                t_hi_dt = t_edge.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                # naive already — assume UTC (matches the sync callback
                # path where dt_util.utcnow() feeds).
                t_hi_dt = t_edge
            t_lo_dt = t_hi_dt - timedelta(
                seconds=BLE_EGRESS_EXIT_BACKFILL_WINDOW_S
            )
            t_lo_iso = t_lo_dt.isoformat()
            t_hi_iso = t_hi_dt.isoformat()

            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                self._ble_exit_error_count += 1
                return

            # Fixed settle (F2 — retains the wrong-WHO flap guard).
            # Ordering MUST be: settle → live re-read flap-abort →
            # SELECT/claim loop. Test override contract preserved:
            # setting `_exit_settle_s` REPLACES the fixed settle
            # (0 = immediate). Direct-call test paths (no tracker_id)
            # skip both settle and flap re-read.
            if tracker_id:
                settle_override = getattr(self, "_exit_settle_s", None)
                if settle_override is None:
                    wait_s = float(BLE_EXIT_DEPARTURE_SETTLE_S)
                else:
                    wait_s = float(settle_override)
                if wait_s > 0:
                    try:
                        await asyncio.sleep(wait_s)
                    except asyncio.CancelledError:
                        raise

                # Flap re-read. If the tracker returned home during
                # settle, the departure was not durable — abort.
                try:
                    live = self.hass.states.get(tracker_id)
                    live_state = getattr(live, "state", None) if live else None
                except Exception:  # noqa: BLE001 — defensive
                    live_state = None
                if live_state in ("home", None, "unknown", "unavailable"):
                    self._ble_exit_flap_aborted_count += 1
                    _LOGGER.info(
                        "exit-backfill: flap-abort slug=%s tracker=%s "
                        "live_state=%r",
                        slug, tracker_id, live_state,
                    )
                    return

            # EGRESS-EXIT-COMULTI-DEPART-1 (2026-09-06) retry-claim
            # loop. Two co-departing edges both SELECT the same
            # nearest row; A wins the IS-NULL claim, B gets
            # `changed==0` and re-SELECTs — the remaining null row
            # now becomes rows[0] (LIMIT 2 in the DAO stays valid
            # because we re-SELECT after each write). One successful
            # claim per edge (invariant b).
            saw_contention = False
            claimed = False
            failed_row_ids: set[int] = set()
            for attempt in range(BLE_EXIT_CLAIM_MAX_ATTEMPTS):
                try:
                    rows = await database.find_unnamed_exit_crossings(
                        t_lo_iso, t_hi_iso
                    )
                except Exception:  # noqa: BLE001
                    self._ble_exit_error_count += 1
                    _LOGGER.debug(
                        "exit-backfill: SELECT failed for %s",
                        slug, exc_info=True,
                    )
                    return
                if not rows:
                    # No unconsumed null row remains. Distinguish
                    # "no crossing to bind" (first-attempt empty)
                    # from "the row we intended to claim was named
                    # by another writer" (later-attempt empty).
                    if attempt == 0:
                        self._ble_exit_edge_no_match_count += 1
                    elif saw_contention:
                        # Case-2 (keep-face+flag+measure, renamed
                        # 2026-09-06 A-3/D-2): a concurrent writer
                        # (face resolver OR another BLE edge) named
                        # the row(s) and we have no own crossing to
                        # bind. Do NOT overwrite; count for
                        # measurement. NOTE: this counter measures
                        # "row lost to concurrent writer", not
                        # specifically face-vs-BLE disagreement.
                        self._ble_exit_row_lost_count += 1
                        _LOGGER.debug(
                            "exit-backfill: row-lost slug=%s "
                            "bounds=%s..%s (no claimable null after "
                            "%d contended attempts)",
                            slug, t_lo_iso, t_hi_iso, attempt,
                        )
                    return
                row_id, _row_ts, egress_camera = rows[0]
                # B2 (2026-09-06): the DAO returns False on BOTH a
                # DB exception and a legitimate `changed==0`. If the
                # re-SELECT returns a row_id we already failed to
                # UPDATE this loop, that is not contention — a real
                # concurrent writer would have named it and it would
                # be filtered from the SELECT. Treat as a persistent
                # DB error, not a retry.
                if row_id in failed_row_ids:
                    self._ble_exit_error_count += 1
                    _LOGGER.debug(
                        "exit-backfill: repeated UPDATE failure on "
                        "row_id=%s slug=%s — treating as DB error",
                        row_id, slug,
                    )
                    return
                try:
                    ok = await database.backfill_entry_exit_person_id(
                        row_id, slug, BLE_TRANSITION_ONLY_CONFIDENCE
                    )
                except Exception:  # noqa: BLE001
                    self._ble_exit_error_count += 1
                    _LOGGER.debug(
                        "exit-backfill: UPDATE failed for "
                        "row_id=%s slug=%s",
                        row_id, slug, exc_info=True,
                    )
                    return
                if ok:
                    claimed = True
                    self._ble_exit_backfilled_count += 1
                    _LOGGER.info(
                        "exit-backfill: row_id=%s <- person_id=%s "
                        "cam=%s (window %ss, bounds %s..%s, "
                        "attempt=%d)",
                        row_id, slug, egress_camera,
                        BLE_EGRESS_EXIT_BACKFILL_WINDOW_S,
                        t_lo_iso, t_hi_iso, attempt + 1,
                    )
                    # EGRESS-EXIT-DISPLAY-REREAD-1: notify display
                    # sensors so PersonsExitedToday re-reads DB.
                    try:
                        from homeassistant.helpers.dispatcher import (
                            async_dispatcher_send,
                        )
                        from .domain_coordinators.signals import (
                            SIGNAL_EGRESS_EXIT_BACKFILLED,
                        )
                        async_dispatcher_send(
                            self.hass,
                            SIGNAL_EGRESS_EXIT_BACKFILLED,
                            {"row_id": row_id, "person_id": slug},
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "exit-backfill: dispatcher send failed",
                            exc_info=True,
                        )
                    return
                # `ok is False`: another writer claimed this row
                # between our SELECT and UPDATE. Count the retry and
                # try the next-nearest unconsumed row.
                saw_contention = True
                failed_row_ids.add(row_id)
                self._ble_exit_row_contention_retry_count += 1
                _LOGGER.debug(
                    "exit-backfill: contention retry slug=%s "
                    "row_id=%s attempt=%d",
                    slug, row_id, attempt + 1,
                )
            if not claimed:
                # Exhausted retry budget without a claim — treat as
                # a persistent contention noop (visible via the
                # retry counter).
                self._ble_exit_backfill_noop_count += 1
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "exit-backfill: unexpected failure for %s", slug, exc_info=True,
            )

    def _consume_ble_arriving_legs(self, slug: str) -> int:
        """rev5 D2 single-use: after an attach, remove ALL arriving
        legs for ``slug`` from the cache. Returns the number removed.
        Called from the transit_validator attach branch (ONLY on
        attach — never on abstain / disagree / no-leg)."""
        if not slug:
            return 0
        kept: deque[BleTransitionLeg] = deque(
            maxlen=self._ble_transition_cache.maxlen,
        )
        removed = 0
        for leg in list(self._ble_transition_cache):
            if leg.person_slug == slug and leg.direction == "arriving":
                removed += 1
                continue
            kept.append(leg)
        self._ble_transition_cache = kept
        if removed:
            self._ble_legs_attached_count += 1
        return removed

    def _resolve_ble_legs(
        self, timestamp: datetime, direction: str,
    ) -> list[BleTransitionLeg]:
        """rev5 D2: return in-window BLE-transition legs matching the
        egress ``direction``.

        v1 = ENTRY-ONLY. For ``direction == "entry"`` (arrival), admit
        an ``arriving`` leg only when it LEADS the crossing — i.e.
        ``0 <= (timestamp - leg.transition_ts) <= BLE_EGRESS_ENTRY_LEAD_S``
        (D0-measured median lead ~+105s, p75 +151s → 180s bound). For
        ``direction == "exit"`` (departure), return [] — the exit
        BLE edge fires ~+369s AFTER the crossing (far outside the
        45s resolve window), deferred to
        ``EGRESS-EXIT-IDENTITY-BACKFILL-1``.

        Prune stale entries against wall-clock (Review DL-2) so a
        backlogged / replayed egress event doesn't destructively evict
        fresh BLE legs.
        """
        try:
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt_util.UTC)
        except Exception:  # noqa: BLE001
            return []
        if direction != "entry":
            # v1: no exit attribution. Still prune the cache below?
            # No — pruning cost on a rare exit call is negligible;
            # leaving the cache to prune on the next entry read.
            return []
        ttl = BLE_TRANSITION_CACHE_TTL_S
        lead_bound = float(BLE_EGRESS_ENTRY_LEAD_S)
        try:
            now_wall = dt_util.utcnow()
            if getattr(now_wall, "tzinfo", None) is None:
                now_wall = now_wall.replace(tzinfo=dt_util.UTC)
        except Exception:  # noqa: BLE001
            now_wall = timestamp
        fresh: deque[BleTransitionLeg] = deque(
            maxlen=self._ble_transition_cache.maxlen,
        )
        matches: list[BleTransitionLeg] = []
        for leg in list(self._ble_transition_cache):
            try:
                lc = leg.transition_ts
                if lc.tzinfo is None:
                    lc = lc.replace(tzinfo=dt_util.UTC)
                wall_age = (now_wall - lc).total_seconds()
                cross_age = (timestamp - lc).total_seconds()
            except Exception:  # noqa: BLE001
                continue
            # Wall-clock prune — genuine staleness only.
            if wall_age > ttl or wall_age < -ttl:
                continue
            fresh.append(leg)
            # ENTRY-ONLY LEAD relation: leg fires BEFORE crossing, so
            # cross_age = (crossing_ts - leg_ts) is NON-NEGATIVE and
            # bounded by BLE_EGRESS_ENTRY_LEAD_S.
            if (
                leg.direction == "arriving"
                and 0.0 <= cross_age <= lead_bound
            ):
                matches.append(leg)
        self._ble_transition_cache = fresh
        return matches

    def _register_ble_transition_listeners(self) -> list:
        """rev5 D1: subscribe to the resident bluetooth_le
        device_trackers derived at CALL TIME. Returns the list of unsub
        callables (also stored on ``self._ble_transition_unsubs`` for
        teardown). Idempotent — tears down prior listeners first.

        Boot-race note: if the device_tracker integration loads AFTER
        URA, the derivation returns fewer trackers (or zero) here; the
        set-diff re-register in ``_refresh_ble_crossing_listeners``
        (invoked on ``EVENT_HOMEASSISTANT_STARTED`` and each periodic
        census tick) picks up any newly-appearing trackers.
        """
        # Teardown any prior listeners so re-invoking is safe.
        self.async_teardown_ble_transition_listeners()
        from homeassistant.helpers.event import async_track_state_change_event
        derived = self._derive_ble_crossing_trackers()
        entity_ids = sorted(derived.keys())
        if not entity_ids:
            # No trackers to subscribe → clear the map so the next
            # refresh set-diff re-derives freshly (rev5 B-HIGH-1).
            self._ble_tracker_slug_map = {}
            _LOGGER.info(
                "rev5 BLE producer: no bluetooth_le trackers derived at "
                "setup; will re-derive on HA start + census tick.",
            )
            return []
        try:
            unsub = async_track_state_change_event(
                self.hass, entity_ids,
                self._on_crossing_tracker_state_change,
            )
        except Exception:  # noqa: BLE001
            # B-HIGH-1: on a raised subscribe, DO NOT latch the map —
            # leave it empty so `_refresh_ble_crossing_listeners`'s
            # set-diff sees `added != {}` on the next tick and retries.
            self._ble_tracker_slug_map = {}
            self._ble_transition_unsubs = []
            _LOGGER.debug(
                "rev5 BLE listener registration failed for %r",
                entity_ids, exc_info=True,
            )
            return []
        # Subscribe succeeded — latch the map and record the unsub.
        self._ble_tracker_slug_map = dict(derived)
        self._ble_transition_unsubs.append(unsub)
        _LOGGER.info(
            "rev5 BLE crossing listeners registered for %d "
            "bluetooth_le tracker(s): %r", len(entity_ids), entity_ids,
        )
        return list(self._ble_transition_unsubs)

    def _refresh_ble_crossing_listeners(self) -> int:
        """rev5 D1 boot-race re-register. Re-derive the bluetooth_le
        tracker set and, if it has GROWN (new trackers visible now
        that weren't at setup), tear down + re-register so the new
        trackers get subscribed. Returns the number of NEW trackers
        picked up (>= 0). Idempotent when the set is unchanged
        (byte-identical: no teardown, no re-register).
        """
        try:
            derived = self._derive_ble_crossing_trackers()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "rev5 BLE re-derive raised (non-fatal)", exc_info=True,
            )
            return 0
        new_ids = set(derived.keys())
        cur_ids = set(self._ble_tracker_slug_map.keys())
        added = new_ids - cur_ids
        removed = cur_ids - new_ids
        if not added and not removed:
            # Refresh the slug-map values in case a tracker moved
            # between slugs (extremely unlikely, but cheap).
            self._ble_tracker_slug_map = dict(derived)
            return 0
        _LOGGER.info(
            "rev5 BLE producer: tracker set changed "
            "(added=%r removed=%r); re-registering listeners.",
            sorted(added), sorted(removed),
        )
        # Re-register against the CURRENT derived set. Teardown +
        # rebuild inside _register_ble_transition_listeners.
        self._register_ble_transition_listeners()
        return len(added)

    def async_teardown_ble_transition_listeners(self) -> None:
        """Drain and invoke every registered BLE-transition listener
        canceller. Safe to call multiple times."""
        for unsub in list(self._ble_transition_unsubs):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "BLE-transition listener teardown raised (non-fatal)",
                    exc_info=True,
                )
        self._ble_transition_unsubs = []
        # NOTE: pending exit-backfill tasks are NOT cancelled here.
        # This method runs on every refresh/re-register (see the
        # `async_teardown_ble_transition_listeners()` call inside
        # `_register_ble_transition_listeners`); cancelling here would
        # abort any in-flight settle sleep every time the tracked-set
        # is recomputed. Cancellation lives on the entry-unload path
        # via `async_cancel_pending_backfill_tasks()` instead.

    # ------------------------------------------------------------------
    # FRIGATE-SUBLABEL-FACE-BRIDGE-1 (2026-09-06) D1: MQTT bridge.
    # Subscribes to `frigate/tracked_object_update` and latches
    # (URA-base-stem -> (name, ts)) so `_resolve_face_legs` can emit a
    # synthetic FaceLeg while Frigate's own recognized-face sensor is
    # in its 60s reset window. Additive path — never touches the frozen
    # `_resolve_face_entity_id` / `_get_face_recognized_persons*` (fenced
    # by the B-HIGH-1 revert comment at camera_census.py:2856-2864).
    # ------------------------------------------------------------------
    async def async_register_frigate_face_listener(self) -> None:
        """Subscribe to the Frigate face-name MQTT topic. Idempotent —
        tears down any prior subscription first. Wrapped in try/except:
        if MQTT is not loaded / raises, the bridge stays inert (unsub
        None) and the point-read path is unaffected."""
        # Idempotent: drop any prior sub before re-registering.
        self.async_teardown_frigate_face_listener()
        try:
            from homeassistant.components import mqtt as _mqtt
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "frigate-face bridge: mqtt import failed — bridge inert",
                exc_info=True,
            )
            return
        topic_prefix = self._resolve_frigate_topic_prefix() or "frigate"
        topic = f"{topic_prefix}/tracked_object_update"
        try:
            unsub = await _mqtt.async_subscribe(
                self.hass,
                topic,
                self._on_frigate_face_msg,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "frigate-face bridge: mqtt.async_subscribe failed — "
                "bridge inert (point-read path unaffected)",
                exc_info=True,
            )
            return
        self._frigate_face_unsub = unsub
        _LOGGER.info(
            "frigate-face bridge: subscribed to %s (TTL=%ds, "
            "known-camname collision guard remains authoritative)",
            topic, FACE_NAME_LATCH_TTL_S,
        )

    def _resolve_frigate_topic_prefix(self) -> str | None:
        """D-MED-3: best-effort probe for the configured Frigate MQTT
        `topic_prefix`. Falls back to None (caller uses literal
        `"frigate"`); either way the known-camname collision guard in
        `_on_frigate_face_msg` prevents cross-host bleed (memory:
        frigate_mqtt_topic_collision)."""
        try:
            entries = self.hass.config_entries.async_entries("frigate")
        except Exception:  # noqa: BLE001
            return None
        for entry in entries or []:
            for src in (
                getattr(entry, "options", None) or {},
                getattr(entry, "data", None) or {},
            ):
                for key in ("topic_prefix", "mqtt_topic_prefix", "mqtt_topic"):
                    val = src.get(key) if isinstance(src, dict) else None
                    if isinstance(val, str) and val.strip():
                        return val.strip().rstrip("/")
        return None

    def async_teardown_frigate_face_listener(self) -> None:
        """Drain the Frigate face MQTT subscription. Safe to call
        multiple times. Called on entry-unload only (mirrors
        `async_teardown_ble_transition_listeners`)."""
        unsub = self._frigate_face_unsub
        self._frigate_face_unsub = None
        if unsub is None:
            return
        try:
            unsub()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "frigate-face bridge teardown raised (non-fatal)",
                exc_info=True,
            )

    def _compute_face_latch_stems(
        self, resolver: Any, camname: str,
    ) -> list[str]:
        """HIGH #2 (key-namespace fix): derive latch keys by scanning the
        entity registry for face sensors on the devices owned by this
        Frigate `camname`. This guarantees the WRITE key matches the
        READ key used by `_resolve_face_legs` (which enumerates
        ``sensor.<base>_last_recognized_face[_2]`` directly), regardless
        of resolution-suffix or `_N` disambiguation on the camera stem
        (e.g. ``camera.garage_a_2`` -> `garage_a`,
        ``camera.foyer_fisheye`` -> `foyer_fisheye`, both matching the
        real face sensor).

        MED #5 (single-stem): a single MQTT message latches exactly
        ONE base_stem — the F2 face-sensor stem when present (F1
        retired, memory: frigate1 retired / `_2` permanent), else the
        F1 stem. Two synthetic legs from one recognition would falsely
        score independent-pair CONFIDENCE_HIGH downstream.

        Returns `[]` on any lookup miss (unknown camname / device has
        no face sensor / registry error) — caller drops with counter.
        """
        try:
            frig_index = getattr(
                resolver, "_frigate_stem_to_device_ids", None,
            ) or {}
            device_ids = list(frig_index.get(camname) or [])
            if not device_ids:
                return []
        except Exception:  # noqa: BLE001
            return []
        try:
            registry = er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            return []
        # F2 (canonical, `_last_recognized_face_2`) wins; F1 fallback.
        f2_bases: list[str] = []
        f1_bases: list[str] = []
        try:
            entities = list(registry.entities.values())
        except Exception:  # noqa: BLE001
            entities = []
        for ent in entities:
            try:
                if getattr(ent, "device_id", None) not in device_ids:
                    continue
                eid = getattr(ent, "entity_id", "") or ""
                if not eid.startswith("sensor."):
                    continue
                name = eid.split(".", 1)[1]
                if name.endswith("_last_recognized_face_2"):
                    f2_bases.append(name[: -len("_last_recognized_face_2")])
                elif name.endswith("_last_recognized_face"):
                    f1_bases.append(name[: -len("_last_recognized_face")])
            except Exception:  # noqa: BLE001
                continue
        # Single-stem policy: prefer F2 (present-day canonical). Drop
        # F1 duplicates when F2 exists for the same base to avoid
        # two-leg double-count. Preserve dedup within each tier.
        seen: set[str] = set()
        chosen: list[str] = []
        for base in f2_bases:
            if base not in seen:
                seen.add(base)
                chosen.append(base)
        if not chosen:
            for base in f1_bases:
                if base not in seen:
                    seen.add(base)
                    chosen.append(base)
        return chosen

    @callback
    def _on_frigate_face_msg(self, msg: Any) -> None:
        """MQTT callback for `frigate/tracked_object_update`. Filters
        `type=="face"`, maps Frigate camname -> URA base_stem via the
        CameraResolver's Frigate-stem index (NEVER string-built —
        `_2` disambiguation is permanent), and latches (name, ts).
        Malformed / non-face / unknown-camera messages are counted
        under `_frigate_face_msg_dropped_count`."""
        self._frigate_face_msg_seen_count += 1
        try:
            payload_raw = getattr(msg, "payload", None)
            if payload_raw is None:
                self._frigate_face_msg_dropped_count += 1
                return
            if isinstance(payload_raw, (bytes, bytearray)):
                try:
                    payload_raw = payload_raw.decode("utf-8")
                except Exception:  # noqa: BLE001
                    self._frigate_face_msg_dropped_count += 1
                    return
            if isinstance(payload_raw, str):
                try:
                    data = json.loads(payload_raw)
                except Exception:  # noqa: BLE001
                    self._frigate_face_msg_dropped_count += 1
                    return
            elif isinstance(payload_raw, dict):
                data = payload_raw
            else:
                self._frigate_face_msg_dropped_count += 1
                return
            # Top-level fields (per Frigate integration
            # FrigateRecognizedFaceSensor consumer: data.get("type") /
            # data["name"] / data["camera"] — settled by the wire
            # parser, per D0).
            if not isinstance(data, dict):
                self._frigate_face_msg_dropped_count += 1
                return
            if data.get("type") != "face":
                # Non-face update on the shared topic — not a drop
                # error; increment neither seen nor dropped beyond
                # the seen we already counted.
                return
            # D-LOW-1: honest face-yield signal (increment ONLY on
            # actual face messages, not all tracked_object_update
            # traffic which is dominated by person).
            self._frigate_face_msg_face_count += 1
            name = data.get("name")
            camname = data.get("camera")
            if not isinstance(name, str) or not name.strip():
                self._frigate_face_msg_dropped_count += 1
                return
            if not isinstance(camname, str) or not camname.strip():
                self._frigate_face_msg_dropped_count += 1
                return
            camname = camname.strip()
            name = name.strip()
            # HIGH: Frigate emits a real "unknown" (+ unknown_score:0.8)
            # label. Drop face-library sentinel names BEFORE the latch
            # write; mirrors the entity path at _resolve_face_legs
            # sentinel filter. A latched "unknown" would falsely emit
            # a synthetic leg AND could push a same-stem live leg to
            # DISAGREE at transit_validator.
            if name.lower() in (
                "unavailable", "unknown", "none", "no_match", "",
            ):
                self._frigate_face_msg_dropped_count += 1
                return
            # Map Frigate camname -> device_ids via the shared
            # resolver's Frigate-stem index; then compute URA base
            # stems. Collision guard: `camname ∈ known frigate set`
            # (host is discarded by rsplit at camera_resolver.py:518 —
            # F1 is retired so no host disambiguation is available or
            # needed; memory: frigate1 retired / `_2` permanent).
            resolver = None
            try:
                if hasattr(self._camera_manager, "_get_resolver"):
                    resolver = self._camera_manager._get_resolver()
            except Exception:  # noqa: BLE001
                resolver = None
            if resolver is None:
                self._frigate_face_msg_dropped_count += 1
                return
            # B-MED: memoized camname -> latch base_stems lookup.
            # Invalidate on resolver rebuild (`_resolver_dirty` flips
            # on registry-update events → new resolver instance).
            prev_ref = self._frigate_face_camname_cache_resolver_ref
            prev_resolver = prev_ref() if callable(prev_ref) else prev_ref
            if prev_resolver is not resolver:
                self._frigate_face_camname_cache = {}
                try:
                    import weakref as _wr
                    self._frigate_face_camname_cache_resolver_ref = _wr.ref(resolver)
                except TypeError:
                    self._frigate_face_camname_cache_resolver_ref = resolver
            cached = self._frigate_face_camname_cache.get(camname)
            if cached is None:
                base_stems_list = self._compute_face_latch_stems(
                    resolver, camname,
                )
                self._frigate_face_camname_cache[camname] = base_stems_list
            else:
                base_stems_list = cached
            base_stems = set(base_stems_list)
            if not base_stems:
                # Unknown / non-URA camera OR no face-sensor entities
                # owned by any of its devices — drop with counter.
                self._frigate_face_msg_dropped_count += 1
                return
            now = dt_util.utcnow()
            # Latch write + prune-on-write. TTL nominally derived from
            # the FACE_MATCH_* window family (const.py:FACE_NAME_LATCH_TTL_S
            # = 330s), but the EFFECTIVE admission bound at the caller
            # is the tighter wall-clock face-producer staleness gate
            # `FACE_PRODUCER_STALE_TTL_S = 120s` (const.py:2326) applied
            # by `_is_face_producer_live()` — the 60s->120s widening on
            # the mis-attribution window is intentional (D-MED-1).
            if FACE_NAME_LATCH_TTL_S > 0:
                cutoff = now - timedelta(seconds=FACE_NAME_LATCH_TTL_S)
                # Prune stale entries opportunistically (bounded work
                # per message; the map keyed by base_stem is small).
                stale = [
                    k for k, (_n, t) in self._frigate_face_latch.items()
                    if t < cutoff
                ]
                for k in stale:
                    self._frigate_face_latch.pop(k, None)
            for stem in base_stems:
                self._frigate_face_latch[stem] = (name, now)
                self._frigate_face_last_latched = (stem, name, now)
            _LOGGER.debug(
                "frigate-face bridge: latched name=%r camname=%r "
                "stems=%r (latch_size=%d)",
                name, camname, sorted(base_stems),
                len(self._frigate_face_latch),
            )
        except Exception:  # noqa: BLE001 — never raise from the cb
            self._frigate_face_msg_dropped_count += 1
            _LOGGER.debug(
                "frigate-face bridge: cb raised (non-fatal)",
                exc_info=True,
            )

    def async_cancel_pending_backfill_tasks(self) -> None:
        """EGRESS-EXIT-IDENTITY-BACKFILL-1 fix-up (2026-09-05) —
        cancel any pending exit-backfill tasks scheduled from the
        departing-edge callback. Called from the entry-unload path
        ONLY. Safe to call multiple times."""
        for task in list(self._backfill_tasks):
            try:
                if not task.done():
                    task.cancel()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "exit-backfill task cancel raised (non-fatal)",
                    exc_info=True,
                )
        self._backfill_tasks.clear()

    # ------------------------------------------------------------------
    # v3.10.1: Enhanced Census (event-driven sensor fusion)
    # ------------------------------------------------------------------

    def _is_enhanced_census_enabled(self) -> bool:
        """Return True if enhanced census v2 is enabled (default True)."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(merged.get(CONF_ENHANCED_CENSUS, True))
        return True

    def _get_ble_cancel_enabled(self) -> bool:
        """H3 (2026-07-13) — read live BLE-cancel kill switch.

        Follows the same options-read pattern as ``_get_hold_seconds``
        (below) so a toggle in the integration config flow takes effect
        on the next census tick without a restart. Default TRUE
        preserves current behavior (subtraction ACTIVE); when False the
        Step-3 subtraction in ``_get_unrecognized_camera_count`` is
        skipped byte-identically to the pre-BLE-cancel path.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(
                    merged.get(
                        CONF_CENSUS_BLE_CANCEL_ENABLED,
                        DEFAULT_CENSUS_BLE_CANCEL_ENABLED,
                    )
                )
        return DEFAULT_CENSUS_BLE_CANCEL_ENABLED

    def _get_hold_seconds(self, zone: str) -> int:
        """Return hold duration in seconds for the given zone."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                if zone == "house":
                    minutes = merged.get(
                        CONF_CENSUS_HOLD_INTERIOR,
                        DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES,
                    )
                else:
                    minutes = merged.get(
                        CONF_CENSUS_HOLD_EXTERIOR,
                        DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES,
                    )
                return int(minutes) * 60
        if zone == "house":
            return DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES * 60
        return DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES * 60

    def _apply_hold_decay(
        self, fresh_count: int, zone: str, now: datetime
    ) -> tuple[int, bool, int]:
        """Apply hold/decay to a camera-based count.

        Returns (held_count, is_peak_held, peak_age_minutes).

        Logic:
          - v5.9.0 D-B: If fresh_count > stored peak, enter/continue a
            PENDING latch. Only promote to peak once fresh_count has held
            >= pending value for CENSUS_PEAK_SUSTAIN_SECONDS. Transient
            spikes below the sustain window never propagate through
            hold/decay. Downward moves keep instant/decay semantics — a real
            departure should not be delayed.
          - CENSUS-ACCURACY-1 D1 (2026-08-17): fresh_count == stored peak
            NO LONGER refreshes peak_ts (was the systematic-error tail).
          - If within hold window: use stored peak
          - After hold window (BOTH zones, post-D1): instant drop to
            fresh_count. The prior house-only linear decay slope
            (`-1 per CENSUS_DECAY_STEP_SECONDS`) has been removed —
            the property-zone instant-drop is now shared.
        """
        hold_seconds = self._get_hold_seconds(zone)

        if zone == "house":
            peak = self._peak_house_camera_count
            peak_ts = self._peak_house_timestamp
            pending = self._pending_house_peak
            pending_since = self._pending_house_peak_since
        else:
            peak = self._peak_property_count
            peak_ts = self._peak_property_timestamp
            pending = self._pending_property_peak
            pending_since = self._pending_property_peak_since

        # v5.9.0 D-B: sustain-before-latch gate on UPWARD moves.
        # v5.9.0 B-M1: the sustain gate is a HOUSE-ONLY policy. The
        # property (exterior) zone keeps its documented instant-rise /
        # instant-drop semantics — a perimeter camera firing is a safety
        # signal that must not be delayed by 15s.
        if peak_ts is None:
            # First observation: latch immediately (no prior peak to protect).
            self._store_peak(zone, fresh_count, now)
            self._clear_pending(zone)
            return (fresh_count, False, 0)

        sustain_applies = zone == "house"

        if fresh_count > peak and sustain_applies:
            # Upward move — must sustain before latching.
            if pending_since is None or fresh_count > pending:
                # Start (or raise) a pending latch. Higher pending resets
                # the sustain timer to `now` so the operator can't inch a
                # peak up by 1 every 14s.
                self._set_pending(zone, fresh_count, now)
                # Return the CURRENT peak — pending has not yet promoted.
                elapsed = (now - peak_ts).total_seconds()
                if elapsed < hold_seconds:
                    return (peak, True, int(elapsed / 60))
                # Peak is past hold window; fall through to decay path
                # (below) using stored peak/peak_ts — do NOT return here.
                # A-L1: keep _pending_* tidy — the peak is about to be
                # rewritten by the decay path, so the pending state
                # tracked against the old peak is no longer meaningful.
                self._clear_pending(zone)
            else:
                # fresh_count is at or below the pending target (but still
                # above the stored peak). Check whether it has sustained.
                pending_elapsed = (now - pending_since).total_seconds()
                if pending_elapsed >= CENSUS_PEAK_SUSTAIN_SECONDS:
                    # Sustain window met — promote pending to peak.
                    # Use pending value (the sustained-or-exceeded target).
                    self._store_peak(zone, pending, now)
                    self._clear_pending(zone)
                    return (pending, False, 0)
                # Still within sustain window: keep the CURRENT peak.
                elapsed = (now - peak_ts).total_seconds()
                if elapsed < hold_seconds:
                    return (peak, True, int(elapsed / 60))
                # Fall through to decay path.
                # A-L1: same rationale as above.
                self._clear_pending(zone)
        elif fresh_count > peak:
            # B-M1: property zone — no sustain gate. Latch instantly,
            # matching pre-v5.9.0 semantics for the exterior.
            self._store_peak(zone, fresh_count, now)
            self._clear_pending(zone)
            return (fresh_count, False, 0)
        elif fresh_count == peak:
            # CENSUS-ACCURACY-1 D1 (2026-08-17): DO NOT refresh peak_ts on
            # equality. The prior `_store_peak(zone, fresh_count, now)` call
            # here made a systematic-error peak immortal — every tick where
            # fresh == peak (steady wrong-high count) reset peak_ts to now,
            # so the hold + decay window never expired. Probe measured 74.5%
            # of elevated-census time as this tail. INV-PEAK-NO-SELF-REFRESH.
            # We still clear pending (a pending latch tracked against this
            # same peak is no longer meaningful) and return fresh_count with
            # peak_held=False (the returned COUNT is fresh; only the STORED
            # peak_ts is untouched so the natural decay path can fire).
            self._peak_refresh_suppressed_count += 1
            self._clear_pending(zone)
            return (fresh_count, False, 0)
        else:
            # fresh_count < peak. A dip clears any pending latch (the
            # higher value did NOT sustain). Then fall through to
            # hold/decay for the downward path (instant/decay semantics).
            if pending_since is not None and fresh_count < pending:
                self._clear_pending(zone)

        elapsed = (now - peak_ts).total_seconds()

        # Within hold window: use peak
        if elapsed < hold_seconds:
            age_min = int(elapsed / 60)
            return (peak, True, age_min)

        # After hold window: instant drop for both zones.
        # CENSUS-ACCURACY-1 D1 (2026-08-17): the house branch previously
        # applied a linear `-1 per CENSUS_DECAY_STEP_SECONDS` slope after
        # hold expiry, delaying a departure by (peak * step) seconds. The
        # property branch already used instant-drop; we now share that
        # semantics for both zones. INV-DECAY-HONEST.
        self._store_peak(zone, fresh_count, now)
        return (fresh_count, False, 0)

    # v5.9.0 D-B helpers for the sustain-latch state machine ------------------

    def _store_peak(self, zone: str, value: int, ts: datetime) -> None:
        """Write the promoted peak for the given zone."""
        if zone == "house":
            self._peak_house_camera_count = value
            self._peak_house_timestamp = ts
        else:
            self._peak_property_count = value
            self._peak_property_timestamp = ts

    def _set_pending(self, zone: str, value: int, ts: datetime) -> None:
        """Start/raise a pending latch for the given zone."""
        if zone == "house":
            self._pending_house_peak = value
            self._pending_house_peak_since = ts
        else:
            self._pending_property_peak = value
            self._pending_property_peak_since = ts

    def _clear_pending(self, zone: str) -> None:
        """Drop the pending latch for the given zone."""
        if zone == "house":
            self._pending_house_peak = 0
            self._pending_house_peak_since = None
        else:
            self._pending_property_peak = 0
            self._pending_property_peak_since = None

    def get_pending_peak_info(self, zone: str, now: datetime) -> dict[str, Any] | None:
        """Return {value, seconds_remaining} if a pending latch is active.

        Used by the census sensor's D-E observability attributes. Returns
        None when no pending latch is in flight.
        """
        if zone == "house":
            pending = self._pending_house_peak
            since = self._pending_house_peak_since
        else:
            pending = self._pending_property_peak
            since = self._pending_property_peak_since
        if since is None or pending <= 0:
            return None
        elapsed = (now - since).total_seconds()
        remaining = max(0, int(CENSUS_PEAK_SUSTAIN_SECONDS - elapsed))
        return {"value": pending, "seconds_remaining": remaining}

    def _get_unrecognized_camera_count(self) -> int:
        """Count interior cameras detecting persons with unrecognized faces.

        For each Frigate camera with person_count > 0, check if
        last_recognized_face is unknown/empty. If so, that camera
        is seeing an unrecognized person (potential guest).

        Face recognition must be fresh (within CENSUS_FACE_RECOGNITION_WINDOW_SECONDS)
        to be trusted. Stale face matches are treated as unknown.

        v5.9.0 B-C1 fix: per-camera unrecognized contributions are grouped
        by ``CameraInfo.area_id`` with same-area max / cross-area sum
        semantics, matching ``_calculate_house_census``. NOTE (2026-07-13
        fix-up a3e5c49b): the dedup is now INLINED as Steps 2/4 of the
        four-step algorithm below (no longer a ``_dedup_by_area`` call) so
        the BLE subtraction can happen between dedup and summation —
        keep the semantics in lockstep with ``_dedup_by_area``. Without this, the enhanced-census
        path (default ON) overwrites the raw house result with a naive
        sum and re-inflates the count Bug Class #53 D-A was meant to
        prevent.
        """
        now = dt_util.utcnow()
        configured_interior = self._get_interior_camera_entities()
        # Fix 2 (review A-H1 / B-M2 / C-HIGH-2): per-area redesign.
        #
        # The prior implementation subtracted BLE per-CAMERA with a
        # decrementing budget, then handed area-tagged contributions to
        # ``_dedup_by_area`` (same-area MAX). Two failure modes:
        #   (a) Same-area under-cancel — two cameras cover playroom, a
        #       resident is BLE-there: camera A cancelled, camera B not,
        #       ``_dedup_by_area`` takes max(0, B) = B, resident re-arms.
        #   (b) Order dependence — camera A vs B first changes which
        #       camera absorbs the cancellation.
        #
        # Redesign: (1) compute per-camera RAW contribution (post-face,
        # pre-BLE); (2) group by area, take MAX (mirrors
        # ``_dedup_by_area`` semantics); (3) subtract
        # ``min(area_raw_max, ble_here)`` per area; (4) sum. Null-area
        # cameras contribute individually and are never cancelled.
        ble_by_area = self._ble_home_by_area()
        raw_contributions: list[tuple[str | None, int]] = []

        for entity_id in configured_interior:
            platform = self._camera_manager.get_platform_for_camera(entity_id)
            if platform != CAMERA_PLATFORM_FRIGATE:
                continue

            camera_info = self._camera_manager._camera_by_entity.get(entity_id)
            if not camera_info or not camera_info.person_count_sensor:
                continue

            # Check if this camera currently sees a person
            count = self._get_sensor_int(camera_info.person_count_sensor)
            if count <= 0:
                continue

            area_id = camera_info.area_id

            # Check face recognition for this camera
            bs_id = camera_info.entity_id
            if not bs_id.endswith("_person_occupancy"):
                # Can't derive face sensor — count as unrecognized
                raw_contributions.append((area_id, count))
                continue

            base_name = bs_id[len("binary_sensor."):-len("_person_occupancy")]
            # CENSUS-ACCURACY-1 D2: `_2`-suffix-tolerant resolver. Fail-CLOSED
            # on a miss: with no resolvable face sensor we treat the entire
            # camera count as unrecognized (raw_contribution = count) via the
            # `face_is_fresh = False` branch below. This is the SAFE
            # direction — a missing sensor must NEVER grant a free `-1`.
            face_sensor_id = self._resolve_face_entity_id(base_name)
            face_state = (
                self.hass.states.get(face_sensor_id) if face_sensor_id else None
            )

            face_is_fresh = False
            if face_state and face_state.state.strip().lower() not in (
                "unavailable", "unknown", "", "none", "no_match",
            ):
                # Check freshness — stale face matches are unreliable
                last_changed = face_state.last_changed
                if last_changed is not None:
                    try:
                        if last_changed.tzinfo is not None:
                            age = (now - last_changed).total_seconds()
                        else:
                            age = (now - last_changed.replace(
                                tzinfo=dt_util.UTC
                            )).total_seconds()
                        face_is_fresh = age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS
                    except (TypeError, AttributeError):
                        face_is_fresh = False

            if face_is_fresh:
                # Camera sees someone AND face is recently recognized — not a guest
                # But there may be MORE people than the recognized face
                raw_contribution = max(0, count - 1)
            else:
                # Face is unknown, stale, or no match — all detected are unrecognized
                raw_contribution = count

            if raw_contribution > 0:
                raw_contributions.append((area_id, raw_contribution))

        # Step 2: collapse per-area (max within area). Null-area cameras
        # contribute individually and pass through unassigned_raw.
        area_raw_max: dict[str, int] = {}
        unassigned_raw: list[int] = []
        for aid, cnt in raw_contributions:
            if cnt <= 0:
                continue
            if aid:
                if cnt > area_raw_max.get(aid, 0):
                    area_raw_max[aid] = cnt
            else:
                unassigned_raw.append(cnt)

        # GUEST-CENSUS D1 (G2): publish the PRE-BLE-cancel per-area-max
        # scalar and dict so INV-CENSUS-ATTRIBUTION has a stable ceiling
        # that does NOT drop when BLE-cancel repairs, and so observability
        # can discriminate "cancel ran and cancelled zero" from
        # "cancel never ran". Consumed by _apply_enhanced_house_census
        # (clamp ceiling) and sensor.py (persons_in_house attrs).
        self._last_camera_total_pre_cancel = (
            sum(area_raw_max.values()) + sum(unassigned_raw)
        )
        self._last_area_raw_max_pre_cancel = dict(area_raw_max)
        self._last_ble_by_area = dict(ble_by_area)
        self._last_ble_cancel_enabled = bool(self._get_ble_cancel_enabled())

        # Step 3: per-area BLE subtraction. Invariants:
        #   I1 — an area with no resident BLE-here is untouched; a guest
        #        there still contributes.
        #   I2 — reduction is exactly ``min(area_raw_max, ble_here)``
        #        (C-HIGH-2 min-bound anchor: 2 residents in an area with
        #        pc=1 → cancelled == 1, not 2).
        #   I3 — subtraction is monotone-reducing. Null-area cameras
        #        (unassigned_raw) are NEVER cancelled — Fix 4 also
        #        enforces this at the source (_ble_home_by_area drops
        #        unmapped residents rather than bucketing under None).
        #
        # H3 (2026-07-13): the entire Step-3 subtraction is gated by the
        # BLE-cancel kill switch (read LIVE per tick). When OFF, we take
        # the byte-identical zero-cancellation path — area_raw_max flows
        # straight through as area_contributions and cancelled_total
        # stays 0. This matches the pre-BLE-cancel behavior (reviewer-
        # verified equivalent to the zero-cancellation path).
        cancelled_total = 0
        area_contributions: dict[str, int] = {}
        if not self._get_ble_cancel_enabled():
            for aid, raw_max in area_raw_max.items():
                if raw_max > 0:
                    area_contributions[aid] = raw_max
        else:
            for aid, raw_max in area_raw_max.items():
                ble_here = ble_by_area.get(aid, 0)
                correction = min(raw_max, ble_here)
                if correction > 0:
                    cancelled_total += correction
                    _LOGGER.info(
                        "BLE-cancel: area=%s raw_max=%d ble_here=%d correction=%d contribution=%d",
                        aid, raw_max, ble_here, correction, raw_max - correction,
                    )
                final = raw_max - correction
                if final > 0:
                    area_contributions[aid] = final

        # D3: publish per-cycle diagnostic. On earlier exception the
        # attribute retains its previous value (seeded 0 in __init__) —
        # publishing a partial half-count would be worse than surfacing
        # the last known good.
        self._last_ble_cancelled_count = cancelled_total

        # GUEST-CENSUS D1 (G2): enhanced-path per-area contributions
        # POST-cancel — what actually feeds camera_unrecognized. Distinct
        # from the raw producer's _last_area_contributions (:1358) which
        # sensor.py currently reads and which cannot report the enhanced
        # path's dedup.
        self._last_enhanced_area_contributions = dict(area_contributions)

        # Step 4: sum. Null-area contributions summed individually (no
        # dedup between null-area cameras — matches ``_dedup_by_area``).
        return sum(area_contributions.values()) + sum(unassigned_raw)

    def _get_wifi_guest_count(self, now: datetime | None = None) -> int:
        """Count GUEST phones on WiFi VLAN (shared entertainment network).

        The configured SSID (e.g., Revel) is a shared network with TVs,
        HomePods, WiiMs, family phones, guest phones, and IoT devices.
        Guests may have custom hostnames (e.g., "Uche-s-S22"), so instead
        of including known phone hostnames, we EXCLUDE known non-phone
        device types:

        1. Exclude empty hostnames (can't identify device type).
        2. Exclude infrastructure (NON_GUEST_HOSTNAME_PREFIXES): TVs,
           HomePods, WiiMs, cameras, IoT, network gear.
        3. Exclude tablets (TABLET_HOSTNAME_PREFIXES): iPads — guests
           may bring tablets but we count phones (1 per guest) for accuracy.
        4. Person exclusion (3-layer):
           a. Direct entity_id match from person.device_trackers
           b. Device registry sibling expansion — finds UniFi trackers
              that share an HA device with a person's Companion App tracker
           c. MAC cross-reference — excludes devices whose MAC matches
              any family tracker's MAC attribute
        5. Recency filter: Only counts devices whose state last changed
           within WIFI_GUEST_RECENCY_HOURS (default 24h).

        Returns count of guest phone devices currently connected.
        """
        if now is None:
            now = dt_util.utcnow()

        guest_ssid = ""
        tracked_persons: list[str] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                guest_ssid = merged.get(CONF_GUEST_VLAN_SSID, DEFAULT_GUEST_VLAN_SSID)
                raw = merged.get("tracked_persons", [])
                tracked_persons = [p.strip() for p in raw if p.strip()]
                break

        # Build set of family device_tracker entity_ids from person entities
        family_trackers: set[str] = set()
        for person_entity_id in tracked_persons:
            person_state = self.hass.states.get(person_entity_id)
            if person_state is not None:
                trackers = person_state.attributes.get("device_trackers", [])
                family_trackers.update(trackers)
                source = person_state.attributes.get("source")
                if source:
                    family_trackers.add(source)

        # Layer 1: Device registry expansion — find sibling device_tracker
        # entities on the same HA device. Catches UniFi trackers for phones
        # whose Companion App tracker is linked to a person entity.
        try:
            ent_reg = er.async_get(self.hass)
            seen_device_ids: set[str] = set()
            for tracker_eid in list(family_trackers):
                entry = ent_reg.async_get(tracker_eid)
                if entry and entry.device_id and entry.device_id not in seen_device_ids:
                    seen_device_ids.add(entry.device_id)
                    for sibling in er.async_entries_for_device(ent_reg, entry.device_id):
                        if sibling.domain == "device_tracker":
                            family_trackers.add(sibling.entity_id)
        except Exception:  # noqa: BLE001
            pass  # Graceful degradation — fall back to direct entity_id matching

        # Layer 2: MAC cross-reference — collect MACs from family trackers
        # that expose them, for matching against WiFi devices whose entity_id
        # wasn't discovered by Layer 1 (e.g., Private WiFi Address splits).
        family_macs: set[str] = set()
        for tracker_eid in family_trackers:
            tracker_state = self.hass.states.get(tracker_eid)
            if tracker_state:
                mac = tracker_state.attributes.get("mac", "")
                if mac:
                    family_macs.add(mac.lower())

        recency_seconds = WIFI_GUEST_RECENCY_HOURS * 3600
        guest_count = 0
        all_states = self.hass.states.async_all("device_tracker")

        for state in all_states:
            if state.state != "home":
                continue

            attrs = state.attributes
            if attrs.get("source_type", "") != "router":
                continue

            # Check if on configured SSID
            is_on_ssid = False
            if guest_ssid:
                if attrs.get("essid") == guest_ssid:
                    is_on_ssid = True
            else:
                if attrs.get("is_guest", False):
                    is_on_ssid = True

            if not is_on_ssid:
                continue

            # Filter 1: exclude empty hostnames (can't identify)
            hostname = attrs.get("host_name", "").lower()
            if not hostname:
                continue

            # Filter 2: exclude infrastructure devices
            if any(
                hostname.startswith(prefix)
                for prefix in NON_GUEST_HOSTNAME_PREFIXES
            ):
                continue

            # Filter 3: exclude tablets (count phones only, 1 per guest)
            if any(
                hostname.startswith(prefix)
                for prefix in TABLET_HOSTNAME_PREFIXES
            ):
                continue

            # Filter 4: exclude tracked persons' devices (family phones)
            # Checks entity_id (direct + device registry siblings)
            if state.entity_id in family_trackers:
                _LOGGER.debug(
                    "WiFi guest exclusion (family): %s (hostname=%s)",
                    state.entity_id, attrs.get("host_name", ""),
                )
                continue

            # Filter 4b: exclude by MAC match against family devices
            device_mac = attrs.get("mac", "").lower()
            if device_mac and device_mac in family_macs:
                _LOGGER.debug(
                    "WiFi guest exclusion (family MAC): %s (mac=%s, hostname=%s)",
                    state.entity_id, device_mac, attrs.get("host_name", ""),
                )
                continue

            # Filter 5: recency — only count recently-appeared devices
            last_changed = state.last_changed
            if last_changed is not None:
                try:
                    if last_changed.tzinfo is not None:
                        age = (now - last_changed).total_seconds()
                    else:
                        age = (now - last_changed.replace(
                            tzinfo=dt_util.UTC
                        )).total_seconds()

                    if age > recency_seconds:
                        _LOGGER.debug(
                            "WiFi guest exclusion (resident, %dh old): %s",
                            int(age / 3600), state.entity_id,
                        )
                        continue
                except (TypeError, AttributeError):
                    pass  # If can't determine age, count it

            guest_count += 1
            _LOGGER.debug(
                "WiFi guest device: %s (hostname=%s, essid=%s)",
                state.entity_id,
                attrs.get("host_name", ""),
                attrs.get("essid", ""),
            )

        return guest_count

    def _get_face_recognized_person_names(self, now: datetime) -> list[str]:
        """Return person IDs (slug format) Frigate has face-matched recently.

        Checks sensor.frigate_*_last_camera for each tracked person.
        A person is "recently recognized" if their last_camera sensor
        has a valid camera name (not "Unknown") and was updated within
        the face recognition window.

        Returns person IDs in slug format (e.g., "oji_udezue") to match
        the BLE person_id format from person_coordinator.
        """
        recognized: list[str] = []

        # Get tracked persons from integration config
        tracked_persons: list[str] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                raw = merged.get("tracked_persons", [])
                for p in raw:
                    # Normalize to slug: "person.oji_udezue" -> "oji_udezue"
                    slug = p.replace("person.", "").strip()
                    if slug:
                        tracked_persons.append(slug)
                break

        for person_slug in tracked_persons:
            # CENSUS-ACCURACY-1 D2: DO NOT construct the entity_id. The live
            # entities are keyed on the FRIGATE face-library first name
            # (`Oji`), NOT the URA slug (`oji_udezue`), and carry the `_2`
            # disambiguation suffix. Resolve via the build-time registry
            # enumeration keyed on person_slug's first token.
            sensor_id = self._resolve_last_camera_entity_id(person_slug)
            if sensor_id is None:
                # Fail-CLOSED: no face-based credit for this person via
                # this path. BLE path (upstream) is unaffected.
                continue
            state = self.hass.states.get(sensor_id)
            if state is None:
                continue

            # Check if value is a real camera name (not "Unknown")
            if state.state.strip().lower() in ("unknown", "unavailable", ""):
                continue

            # Check if recently updated — use UTC-aware comparison
            last_changed = state.last_changed
            if last_changed is not None:
                try:
                    # Ensure both sides are timezone-aware (HA states use UTC)
                    if last_changed.tzinfo is not None:
                        age = (now - last_changed).total_seconds()
                    else:
                        age = (now - last_changed.replace(
                            tzinfo=dt_util.UTC
                        )).total_seconds()
                except (TypeError, AttributeError):
                    age = CENSUS_FACE_RECOGNITION_WINDOW_SECONDS + 1

                if age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS:
                    # Person-trust cross-check: Frigate's last_camera sensor
                    # flaps unavailable⇄<camera>, re-stamping last_changed, so
                    # the age gate alone never elapses for a departed person.
                    # Drop the face-recognized person if their person.<slug>
                    # tracker reports not_home (mirrors v4.7.13/v4.7.14
                    # person-trust veto pattern). Fail-OPEN: if the person
                    # entity is missing/unknown/unavailable, count them
                    # (preserves prior behavior — conservative).
                    person_entity_id = f"person.{person_slug.lower()}"
                    try:
                        person_state = self.hass.states.get(person_entity_id)
                    except Exception:  # noqa: BLE001 — defensive
                        person_state = None
                    if (
                        person_state is not None
                        and person_state.state == "not_home"
                    ):
                        _LOGGER.debug(
                            "Face-recognized person %s dropped: "
                            "%s=not_home (stale-face latch guard)",
                            person_slug,
                            person_entity_id,
                        )
                        continue
                    recognized.append(person_slug)

        return recognized

    def _apply_enhanced_house_census(
        self,
        raw_result: CensusZoneResult,
        ble_persons: list[str],
        now: datetime,
    ) -> CensusZoneResult:
        """Apply enhanced census v2 to the house zone result.

        Uses camera-only for unidentified count:
          unidentified = camera_unrecognized
        WiFi guest count is still computed for diagnostics but excluded
        from the formula (too many false positives from IoT devices).
        Then applies hold/decay to stabilize the count.
        """
        # Get v2 signals
        camera_unrecognized = self._get_unrecognized_camera_count()
        wifi_guests = self._get_wifi_guest_count(now)
        face_recognized = self._get_face_recognized_person_names(now)

        # EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 fuse site 2 of 2 (I1/I5,
        # plan-review C-CRIT-1). THIS is the writer whose set survives
        # to `identified_count`, `unidentified_count` via
        # `raw_total_ceiling`, and every guest-math consumer — fusing
        # only the raw path at `:1855` is a house-level no-op because
        # this recompute would overwrite it. Names normalized to the
        # Frigate first-name slug namespace at the fuse boundary so BLE
        # slugs, Frigate slugs, and the egress-face register share one
        # namespace (I5).
        # D-MED-1 (2026-08-18): true byte-identical kill switch (see raw
        # fuse-site comment). When disabled, use the exact pre-cycle
        # expression with no canonicalization and no egress term.
        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D4/H1: face-provenance
        # union guard. Under STRICT + face-producer-down, drop the
        # face-recognized name feed entirely — those names are
        # face-provenance by construction. BLE names + BLE-provenance
        # egress registrations continue to accrue. Review OB-1 fix:
        # counter is per-TICK (not per-leg — that lives on the
        # tracker), and only increments when we actually SUPPRESSED
        # something (else it would inflate every idle tick).
        if self._face_suppressed_now():
            if face_recognized:
                self._face_dropped_producer_down_ticks += 1
            face_recognized = []
        if self._is_egress_identity_enabled():
            egress_face_ids = self._get_egress_face_ids_fresh(now)
            recognized_set = (
                self._normalize_name_set(ble_persons)
                | self._normalize_name_set(face_recognized)
                | egress_face_ids  # already canonicalized on register
            )
        else:
            recognized_set = set(ble_persons) | set(face_recognized)
        # H1: identified_guests SEPARATE from resident set so
        # `identified_count` (resident scope) is never inflated by
        # `guest:*` names. Read at every recompute; empty under
        # face-producer-down (guests are face-only by construction).
        try:
            identified_guests = self._get_egress_guest_ids_fresh(now)
        except Exception:  # noqa: BLE001
            identified_guests = set()
        self._last_identified_guests_count = len(identified_guests)
        identified_count = len(recognized_set)

        # Unidentified = camera-only (WiFi VLAN guest detection disabled —
        # too many false positives from persistent IoT/infrastructure devices
        # that pass hostname filters but aren't actual guests).
        # WiFi count is still captured in sensor attributes for diagnostics.
        unidentified_raw = camera_unrecognized

        # Apply hold/decay to unidentified count
        held_unidentified, peak_held, peak_age = self._apply_hold_decay(
            unidentified_raw, "house", now
        )

        # GUEST-CENSUS D1 — INV-CENSUS-ATTRIBUTION:
        # attribution ceiling = the raw derivation's semantic max. MUST use
        # the PRE-cancel scalar published above; using the POST-cancel
        # return (``camera_unrecognized``) would subtract identified
        # residents twice (once via BLE-cancel, once via the ceiling),
        # suppressing a real guest when cancellation is repaired
        # (reviewer counter-example, plan-review P1 — DO NOT "simplify"
        # back to camera_unrecognized). Safe to read
        # ``_last_camera_total_pre_cancel`` here: we called
        # ``_get_unrecognized_camera_count()`` on line above, on this tick.
        # Review A-LOW-1 (2026-08-16): drop trailing ``or 0`` — the getattr
        # default already handles the attribute-missing case. The ``or 0``
        # additionally coerced a legitimate 0 (Step-2 pre_cancel = 0) into
        # the fallback path, which is indistinguishable from "attribute never
        # written". No behaviour change on the attribute-missing branch
        # (default remains 0); the semantically-correct 0 is now preserved.
        camera_total_pre_cancel = int(
            getattr(self, "_last_camera_total_pre_cancel", 0)
        )
        # B-LOW-1 (2026-08-18): post-egress-face-fuse, `identified_count`
        # may exceed `camera_total_pre_cancel` by up to
        # |egress_face_ids| — that IS the purpose of the fuse (bridging
        # the transit gap when a resident has crossed but is not yet on
        # interior cameras). `max()` here therefore RAISES the ceiling
        # rather than clipping identity, i.e. `raw_total_ceiling` is the
        # union of physical evidence and identity evidence, both trusted.
        # The clamp below (`min(additive, ceiling)`) still prevents guest
        # inflation on top of that identified base.
        raw_total_ceiling = max(camera_total_pre_cancel, identified_count)
        additive_total = identified_count + held_unidentified
        clamped_total = min(additive_total, raw_total_ceiling)
        clamped_unidentified = max(0, clamped_total - identified_count)

        if clamped_total != additive_total:
            _LOGGER.info(
                "GUEST-CENSUS D1 clamp fired: additive=%d (id=%d + held=%d) "
                "> ceiling=%d (pre_cancel=%d) → total=%d, unidentified=%d",
                additive_total, identified_count, held_unidentified,
                raw_total_ceiling, camera_total_pre_cancel,
                clamped_total, clamped_unidentified,
            )

        total = clamped_total

        return CensusZoneResult(
            zone=raw_result.zone,
            identified_count=identified_count,
            identified_persons=sorted(recognized_set),
            unidentified_count=clamped_unidentified,
            total_persons=total,
            confidence=raw_result.confidence,
            source_agreement=raw_result.source_agreement,
            frigate_count=raw_result.frigate_count,
            unifi_count=raw_result.unifi_count,
            degraded_mode=raw_result.degraded_mode,
            active_platforms=raw_result.active_platforms,
            timestamp=raw_result.timestamp,
            # v2 attributes
            wifi_guest_floor=wifi_guests,
            camera_unrecognized=camera_unrecognized,
            peak_held=peak_held,
            peak_age_minutes=peak_age,
            face_recognized_persons=face_recognized,
            enhanced_census=True,
            # Cycle census_ble_cancel_unrecognized: read the count
            # deposited by _get_unrecognized_camera_count above; safe
            # because we just called it on this cycle. Attribute is
            # always defined (seeded 0 in __init__), so no getattr
            # dance required.
            ble_cancelled_count=self._last_ble_cancelled_count,
        )

    def _apply_enhanced_property_census(
        self,
        raw_result: CensusZoneResult,
        now: datetime,
    ) -> CensusZoneResult:
        """Apply hold/decay to the property (exterior) zone result."""
        raw_count = raw_result.total_persons
        held_count, peak_held, peak_age = self._apply_hold_decay(
            raw_count, "property", now
        )

        if held_count == raw_count and not peak_held:
            # No change needed
            return raw_result

        return CensusZoneResult(
            zone=raw_result.zone,
            identified_count=raw_result.identified_count,
            identified_persons=raw_result.identified_persons,
            unidentified_count=held_count,
            total_persons=raw_result.identified_count + held_count,
            confidence=raw_result.confidence,
            source_agreement=raw_result.source_agreement,
            frigate_count=raw_result.frigate_count,
            unifi_count=raw_result.unifi_count,
            degraded_mode=raw_result.degraded_mode,
            active_platforms=raw_result.active_platforms,
            timestamp=raw_result.timestamp,
            # v2 attributes
            peak_held=peak_held,
            peak_age_minutes=peak_age,
            enhanced_census=True,
        )
