"""Camera integration and person census for Universal Room Automation v3.5.0."""
#
# Universal Room Automation v3.4.0
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
    ENTRY_TYPE_ROOM,
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
)

_LOGGER = logging.getLogger(__name__)


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

    Discovery strategy:
      1. Scan entity registry for binary_sensor.* entities
      2. Entities ending in _person_occupancy  -> Frigate
      3. Entities ending in _person_detected   -> UniFi Protect
      4. Map each to its HA area_id for room association
      5. For Frigate, find the matching sensor.*_person_count
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the camera integration manager."""
        self.hass = hass
        # area_id -> list[CameraInfo]
        self._cameras_by_area: dict[str, list[CameraInfo]] = {}
        # entity_id -> CameraInfo
        self._camera_by_entity: dict[str, CameraInfo] = {}
        # entity_id -> platform str
        self._platform_by_entity: dict[str, str] = {}

    async def async_discover(self) -> None:
        """Discover camera entities via entity registry.

        Scans all binary_sensor entities, identifies Frigate and UniFi Protect
        person detection entities by name suffix, then associates them with
        HA areas (rooms) for later lookup.
        """
        ent_reg = er.async_get(self.hass)

        frigate_sensors: list[CameraInfo] = []
        unifi_sensors: list[CameraInfo] = []

        for entity in ent_reg.entities.values():
            if entity.domain != "binary_sensor":
                continue

            entity_id = entity.entity_id

            # Frigate: binary_sensor.*_person_occupancy
            if entity_id.endswith("_person_occupancy"):
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

            # UniFi Protect: binary_sensor.*_person_detected
            elif entity_id.endswith("_person_detected"):
                camera_info = CameraInfo(
                    entity_id=entity_id,
                    platform=CAMERA_PLATFORM_UNIFI,
                    area_id=entity.area_id,
                    person_binary_sensor=entity_id,
                )
                unifi_sensors.append(camera_info)

        # Build lookup maps
        self._cameras_by_area = {}
        self._camera_by_entity = {}
        self._platform_by_entity = {}

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
            "Camera discovery complete: %d Frigate, %d UniFi Protect entities found",
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
        """Calculate the house (interior) census.

        Steps:
        1. Collect camera person entities from all room configs
        2. Separate into Frigate and UniFi groups
        3. Sum Frigate counts; check UniFi presence
        4. Cross-validate the two platform counts
        5. Cross-correlate with BLE persons
        6. Return CensusZoneResult
        """
        # Collect camera entities explicitly configured per room
        configured_interior = self._get_interior_camera_entities()

        frigate_total = 0
        unifi_detected = False

        for entity_id in configured_interior:
            platform = self._camera_manager.get_platform_for_camera(entity_id)

            if platform == CAMERA_PLATFORM_FRIGATE:
                # Use person_count sensor if available, otherwise binary_sensor
                camera_info = self._camera_manager._camera_by_entity.get(entity_id)
                if camera_info and camera_info.person_count_sensor:
                    count = self._get_sensor_int(camera_info.person_count_sensor)
                    frigate_total += count
                else:
                    # Fall back: binary as 0 or 1
                    if self._is_entity_on(entity_id):
                        frigate_total += 1

            elif platform == CAMERA_PLATFORM_UNIFI:
                if self._is_entity_on(entity_id):
                    unifi_detected = True

            else:
                # Unknown/not discovered: treat as binary presence
                if self._is_entity_on(entity_id):
                    frigate_total += 1

        # Derive unifi_count from presence signal (binary only, no numeric count)
        unifi_count = 1 if unifi_detected else 0

        # Cross-validate platform counts
        if configured_interior:
            camera_total, agreement = self._cross_validate_platforms(frigate_total, unifi_count)
        else:
            # No interior cameras configured — BLE-only fallback
            camera_total = 0
            agreement = CENSUS_AGREEMENT_SINGLE

        # Cross-correlate with BLE
        ble_id_set = set(ble_persons)
        face_id_set: set[str] = set()  # Face recognition reserved for future cycles

        zone_result = self._cross_correlate_persons(
            face_ids=face_id_set,
            ble_ids=ble_id_set,
            camera_total=camera_total,
            zone="house",
            frigate_count=frigate_total,
            unifi_count=unifi_count,
            agreement=agreement,
            now=now,
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
        """
        egress_entities = self._get_integration_camera_list(CONF_EGRESS_CAMERAS)
        perimeter_entities = self._get_integration_camera_list(CONF_PERIMETER_CAMERAS)
        all_exterior = egress_entities + perimeter_entities

        exterior_count = 0
        for entity_id in all_exterior:
            if self._is_entity_on(entity_id):
                exterior_count += 1  # count distinct active cameras as proxy for persons

        # Confidence for exterior zone
        if not all_exterior:
            confidence = CENSUS_CONFIDENCE_NONE
            agreement = CENSUS_AGREEMENT_SINGLE
        elif exterior_count > 0:
            confidence = CENSUS_CONFIDENCE_MEDIUM
            agreement = CENSUS_AGREEMENT_SINGLE
        else:
            confidence = CENSUS_CONFIDENCE_MEDIUM
            agreement = CENSUS_AGREEMENT_SINGLE

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
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Cross-validation
    # ------------------------------------------------------------------

    def _cross_validate_platforms(
        self,
        frigate_count: int,
        unifi_count: int,
    ) -> tuple[int, str]:
        """Cross-validate person counts between platforms.

        UniFi provides a binary (0/1) signal; Frigate provides a numeric count.
        We use Frigate as the primary count source and UniFi as confirmation.

        Returns:
            (best_count, agreement_level)
            agreement_level: one of CENSUS_AGREEMENT_* constants
        """
        has_frigate = frigate_count > 0 or True  # always present if configured
        has_unifi = unifi_count is not None

        if frigate_count == 0 and unifi_count == 0:
            return (0, CENSUS_AGREEMENT_BOTH)

        if frigate_count > 0 and unifi_count > 0:
            # Both detect persons — use Frigate count (numeric)
            return (frigate_count, CENSUS_AGREEMENT_BOTH)

        if frigate_count > 0 and unifi_count == 0:
            # Frigate detects but UniFi does not — medium confidence
            return (frigate_count, CENSUS_AGREEMENT_CLOSE)

        if frigate_count == 0 and unifi_count > 0:
            # UniFi detects but Frigate does not — low confidence, use 1 as minimum
            return (1, CENSUS_AGREEMENT_CLOSE)

        # Single source fallback
        total = max(frigate_count, unifi_count)
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
            # single_source
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
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Helper: read configuration
    # ------------------------------------------------------------------

    def _get_interior_camera_entities(self) -> list[str]:
        """Return all camera_person_entities configured across all room entries.

        Reads CONF_CAMERA_PERSON_ENTITIES from each room config entry
        (options override data following HA pattern).
        """
        entities: list[str] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            merged = {**entry.data, **entry.options}
            room_cameras = merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
            if room_cameras:
                entities.extend(room_cameras)
        return entities

    def _get_integration_camera_list(self, conf_key: str) -> list[str]:
        """Return camera entity list from integration-level config.

        Reads conf_key (CONF_EGRESS_CAMERAS or CONF_PERIMETER_CAMERAS) from
        the integration config entry.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return merged.get(conf_key, [])
        return []

    # ------------------------------------------------------------------
    # Helper: read HA state
    # ------------------------------------------------------------------

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
