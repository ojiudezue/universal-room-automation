"""Camera integration and person census for Universal Room Automation v3.5.0."""
#
# Universal Room Automation vv5.22.0
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
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_AREA_ID,
    CONF_ROOM_NAME,
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
    # v3.10.1 Census v2
    CONF_ENHANCED_CENSUS,
    CONF_CENSUS_HOLD_INTERIOR,
    CONF_CENSUS_HOLD_EXTERIOR,
    CONF_CENSUS_BLE_CANCEL_ENABLED,
    DEFAULT_CENSUS_BLE_CANCEL_ENABLED,
    DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES,
    DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES,
    CENSUS_DECAY_STEP_SECONDS,
    CENSUS_PEAK_SUSTAIN_SECONDS,
    CENSUS_FACE_RECOGNITION_WINDOW_SECONDS,
    CONF_GUEST_VLAN_SSID,
    DEFAULT_GUEST_VLAN_SSID,
    PHONE_HOSTNAME_PREFIXES,
    WIFI_GUEST_RECENCY_HOURS,
    NON_GUEST_HOSTNAME_PREFIXES,
    TABLET_HOSTNAME_PREFIXES,
)

_LOGGER = logging.getLogger(__name__)

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
            _LOGGER.warning(
                "Camera entity %s not found in entity registry — skipping",
                camera_entity_id,
            )
            return []

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
            if bs_id.endswith("_person_occupancy"):
                # Frigate person occupancy (definitive suffix match)
                detected_platform = CAMERA_PLATFORM_FRIGATE

            elif bs_id.endswith("_person_detected"):
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
                # Try name-based match first
                base_name = bs_id[len("binary_sensor."):-len("_person_occupancy")]
                count_sensor_id = f"sensor.{base_name}_person_count"
                if ent_reg.async_get(count_sensor_id):
                    camera_info.person_count_sensor = count_sensor_id
                else:
                    # Fallback: search device sensors for *_person_count suffix
                    for s_entity in device_sensors:
                        if s_entity.entity_id.endswith("_person_count"):
                            camera_info.person_count_sensor = s_entity.entity_id
                            break

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
        """
        seen_device_ids: set[str] = set()
        all_camera_infos: list[CameraInfo] = []

        ent_reg = er.async_get(self.hass)

        for camera_entity_id in camera_entity_ids:
            camera_entry = ent_reg.async_get(camera_entity_id)
            if camera_entry is None:
                _LOGGER.warning(
                    "Camera entity %s not found in registry — skipping",
                    camera_entity_id,
                )
                continue

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
        # Step 1: standard resolution (same-device sensors)
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

            # Frigate: platform == "frigate" OR binary_sensor.*_person_occupancy
            if platform == CAMERA_PLATFORM_FRIGATE or entity_id.endswith("_person_occupancy"):
                camera_info = CameraInfo(
                    entity_id=entity_id,
                    platform=CAMERA_PLATFORM_FRIGATE,
                    area_id=entity.area_id,
                    person_binary_sensor=entity_id,
                )
                # Try to find matching sensor.*_person_count
                base_name = entity_id[len("binary_sensor."):-len("_person_occupancy")]
                count_sensor_id = f"sensor.{base_name}_person_count"
                if ent_reg.async_get(count_sensor_id):
                    camera_info.person_count_sensor = count_sensor_id
                frigate_sensors.append(camera_info)

            # UniFi Protect: platform == "unifiprotect" OR binary_sensor.*_person_detected
            elif platform == CAMERA_PLATFORM_UNIFI or entity_id.endswith("_person_detected"):
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

        # v5.9.0 D-A / D-E observability: last computed area-contribution map
        # for the interior (house) census, and the pre-dedup naive sum. Read
        # by the census sensor's extra_state_attributes.
        self._last_area_contributions: dict[str, dict[str, Any]] = {}
        self._last_raw_pre_dedup_sum: int = 0

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

        # --- 1. Gather BLE person data from person_coordinator ---
        ble_persons = self._get_ble_persons()

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
                # Both available — cross-validate
                camera_total, agreement = self._cross_validate_platforms(
                    frigate_total, binary_platform_count,
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
    ) -> tuple[int, str]:
        """Cross-validate person counts between Frigate and binary-detection platforms.

        Frigate provides numeric counts; other platforms (UniFi, Reolink, Dahua)
        provide per-camera binary detection summed as binary_platform_count.

        When both are available, Frigate's numeric count is preferred (more precise).
        binary_platform_count serves as a floor/confirmation signal.

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
            return (frigate_count, CENSUS_AGREEMENT_CLOSE)

        if frigate_count == 0 and binary_platform_count > 0:
            # Only binary platforms detect — use their per-camera count
            return (binary_platform_count, CENSUS_AGREEMENT_CLOSE)

        # Should not reach here, but fallback
        total = max(frigate_count, binary_platform_count)
        return (total, CENSUS_AGREEMENT_SINGLE)

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
        known_persons = face_ids | ble_ids
        identified_count = len(known_persons)
        identified_persons = sorted(list(known_persons))

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

    def _get_face_recognized_persons(self) -> set[str]:
        """Return set of person IDs from Frigate face recognition sensors.

        Scans all Frigate cameras for sensor.*_last_recognized_face entities.
        If the sensor value is a recognized name (not empty, "unknown", or
        "unavailable"), adds it to the set.

        Only useful when Frigate is available. Returns empty set otherwise.
        """
        face_ids: set[str] = set()

        for camera_info in self._camera_manager.get_all_frigate_cameras():
            # Derive face recognition sensor from binary_sensor entity ID
            # binary_sensor.{name}_person_occupancy -> sensor.{name}_last_recognized_face
            bs_id = camera_info.entity_id
            if bs_id.endswith("_person_occupancy"):
                base_name = bs_id[len("binary_sensor."):-len("_person_occupancy")]
                face_sensor_id = f"sensor.{base_name}_last_recognized_face"

                state = self.hass.states.get(face_sensor_id)
                if state and state.state.strip().lower() not in (
                    "unavailable", "unknown", "", "none", "no_match",
                ):
                    face_ids.add(state.state.strip())

        if face_ids:
            _LOGGER.debug("Face recognition identified: %s", face_ids)

        return face_ids

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
          - If fresh_count == stored peak: refresh peak timestamp (existing).
          - If within hold window: use stored peak
          - After hold window (house only): decay -1 per CENSUS_DECAY_STEP_SECONDS
          - After hold window (property): instant drop to fresh_count
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
            # Equal to stored peak: refresh timestamp (matches prior semantics).
            self._store_peak(zone, fresh_count, now)
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

        # After hold window
        if zone == "house":
            # Gradual decay: -1 per CENSUS_DECAY_STEP_SECONDS after hold expires
            elapsed_after_hold = elapsed - hold_seconds
            decay_steps = int(elapsed_after_hold / CENSUS_DECAY_STEP_SECONDS)
            decayed = max(fresh_count, peak - decay_steps)
            if decayed <= fresh_count:
                # Decay complete — reset peak to fresh
                self._peak_house_camera_count = fresh_count
                self._peak_house_timestamp = now
                return (fresh_count, False, 0)
            age_min = int(elapsed / 60)
            return (decayed, True, age_min)
        else:
            # Property: instant drop after hold expires
            self._peak_property_count = fresh_count
            self._peak_property_timestamp = now
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
            face_sensor_id = f"sensor.{base_name}_last_recognized_face"
            face_state = self.hass.states.get(face_sensor_id)

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
            # Frigate uses lowercase names: sensor.frigate_oji_udezue_last_camera
            sensor_id = f"sensor.frigate_{person_slug.lower()}_last_camera"
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

        # Recognized persons = BLE home + face recognized (union)
        recognized_set = set(ble_persons) | set(face_recognized)
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

        total = identified_count + held_unidentified

        return CensusZoneResult(
            zone=raw_result.zone,
            identified_count=identified_count,
            identified_persons=sorted(recognized_set),
            unidentified_count=held_unidentified,
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
