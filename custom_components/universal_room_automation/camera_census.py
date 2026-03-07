"""Camera integration and person census for Universal Room Automation v3.5.0."""
#
# Universal Room Automation v3.7.11
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

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
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
        """
        now = datetime.now()

        # --- 1. Gather BLE person data from person_coordinator ---
        ble_persons = self._get_ble_persons()

        # --- 2. House census ---
        house_result = await self._calculate_house_census(ble_persons, now)

        # --- 3. Property (exterior) census ---
        property_result = await self._calculate_property_census(now)

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
            },
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
            for entity_id in configured_interior:
                platform = self._camera_manager.get_platform_for_camera(entity_id)

                if platform == CAMERA_PLATFORM_FRIGATE:
                    camera_info = self._camera_manager._camera_by_entity.get(entity_id)
                    if camera_info and camera_info.person_count_sensor:
                        # Check if Frigate sensor is actually available
                        state = self.hass.states.get(camera_info.person_count_sensor)
                        if state and state.state not in ("unavailable", "unknown"):
                            frigate_available = True
                            count = self._get_sensor_int(camera_info.person_count_sensor)
                            frigate_total += count
                        # If unavailable, skip — will fall through to degraded mode
                    else:
                        # Binary-only Frigate sensor
                        if self._is_entity_available(entity_id):
                            frigate_available = True
                            if self._is_entity_on(entity_id):
                                frigate_total += 1

                else:
                    # All non-Frigate platforms (UniFi, Reolink, Dahua):
                    # count per-camera binary detections
                    if self._is_entity_available(entity_id):
                        binary_platforms_available = True
                        if platform and platform not in active_platforms:
                            active_platforms.append(platform)
                        if self._is_entity_on(entity_id):
                            binary_platform_count += 1

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
