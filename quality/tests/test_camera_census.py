"""Tests for v3.4.0 camera census features.

These tests verify the camera integration and person census logic:
- CameraIntegrationManager: discovery, lookup, platform identification
- PersonCensus: house census, property census, cross-validation,
  cross-correlation, guest detection, graceful degradation
- FullCensusResult: combined totals
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from tests.conftest import MockHass, MockConfigEntry


# ============================================================================
# TEST CONSTANTS (mirrors const.py without importing from the integration)
# ============================================================================

DOMAIN = "universal_room_automation"
CAMERA_PLATFORM_FRIGATE = "frigate"
CAMERA_PLATFORM_UNIFI = "unifiprotect"
CENSUS_CONFIDENCE_HIGH = "high"
CENSUS_CONFIDENCE_MEDIUM = "medium"
CENSUS_CONFIDENCE_LOW = "low"
CENSUS_CONFIDENCE_NONE = "none"
CENSUS_AGREEMENT_BOTH = "both_agree"
CENSUS_AGREEMENT_CLOSE = "close"
CENSUS_AGREEMENT_DISAGREE = "disagree"
CENSUS_AGREEMENT_SINGLE = "single_source"
CONF_CAMERA_PERSON_ENTITIES = "camera_person_entities"
CONF_EGRESS_CAMERAS = "egress_cameras"
CONF_PERIMETER_CAMERAS = "perimeter_cameras"
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_INTEGRATION = "integration"
ENTRY_TYPE_ROOM = "room"


# ============================================================================
# LOCAL REIMPLEMENTATIONS
# These mirror the real implementation without importing HA modules, following
# the same pattern as the existing test suite (pure-Python logic under test).
# ============================================================================

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CameraInfo:
    """Information about a discovered camera entity."""
    entity_id: str
    platform: str
    area_id: Optional[str] = None
    person_binary_sensor: Optional[str] = None
    person_count_sensor: Optional[str] = None


@dataclass
class CensusZoneResult:
    """Result for a single census zone."""
    zone: str
    identified_count: int
    identified_persons: list
    unidentified_count: int
    total_persons: int
    confidence: str
    source_agreement: str
    frigate_count: int
    unifi_count: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FullCensusResult:
    """Combined house + property census."""
    house: CensusZoneResult
    property_exterior: CensusZoneResult
    total_on_property: int
    ble_persons: list
    face_persons: list
    persons_outside: int
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================================
# Pure-Python test doubles for CameraIntegrationManager
# (replaces the HA entity-registry dependency)
# ============================================================================

class StubCameraIntegrationManager:
    """Standalone logic extracted from CameraIntegrationManager for testing."""

    def __init__(self):
        self._cameras_by_area = {}
        self._camera_by_entity = {}
        self._platform_by_entity = {}

    def _process_entities(self, entities):
        """Simulate async_discover from a list of (entity_id, area_id) tuples."""
        frigate_sensors = []
        unifi_sensors = []
        known_count_sensors = set()

        # First pass: collect known count sensor ids
        for entity_id, area_id in entities:
            known_count_sensors.add(entity_id)

        for entity_id, area_id in entities:
            if not entity_id.startswith("binary_sensor."):
                continue
            if entity_id.endswith("_person_occupancy"):
                camera_info = CameraInfo(
                    entity_id=entity_id,
                    platform=CAMERA_PLATFORM_FRIGATE,
                    area_id=area_id,
                    person_binary_sensor=entity_id,
                )
                base_name = entity_id[len("binary_sensor."):-len("_person_occupancy")]
                count_sensor_id = f"sensor.{base_name}_person_count"
                if count_sensor_id in known_count_sensors:
                    camera_info.person_count_sensor = count_sensor_id
                frigate_sensors.append(camera_info)
            elif entity_id.endswith("_person_detected"):
                camera_info = CameraInfo(
                    entity_id=entity_id,
                    platform=CAMERA_PLATFORM_UNIFI,
                    area_id=area_id,
                    person_binary_sensor=entity_id,
                )
                unifi_sensors.append(camera_info)

        self._cameras_by_area = {}
        self._camera_by_entity = {}
        self._platform_by_entity = {}

        for camera_info in frigate_sensors + unifi_sensors:
            self._camera_by_entity[camera_info.entity_id] = camera_info
            self._platform_by_entity[camera_info.entity_id] = camera_info.platform
            area_id = camera_info.area_id or ""
            if area_id not in self._cameras_by_area:
                self._cameras_by_area[area_id] = []
            self._cameras_by_area[area_id].append(camera_info)

    def get_cameras_for_area(self, area_id):
        return self._cameras_by_area.get(area_id, [])

    def get_platform_for_camera(self, entity_id):
        return self._platform_by_entity.get(entity_id)

    def has_cameras(self):
        return bool(self._camera_by_entity)

    def get_all_frigate_cameras(self):
        return [c for c in self._camera_by_entity.values() if c.platform == CAMERA_PLATFORM_FRIGATE]

    def get_all_unifi_cameras(self):
        return [c for c in self._camera_by_entity.values() if c.platform == CAMERA_PLATFORM_UNIFI]


# ============================================================================
# Pure-Python PersonCensus logic for testing
# ============================================================================

class PersonCensusStub:
    """Pure-Python reimplementation of PersonCensus census logic for testing.

    Accepts injected data instead of reading from HA, enabling pure-unit tests
    that follow the same patterns as the rest of the suite (MockHass, etc.).
    """

    def __init__(self, hass, camera_manager):
        self.hass = hass
        self._camera_manager = camera_manager
        self._last_result = None

    # ------------------------------------------------------------------
    # Public API (synchronous mirror of async methods)
    # ------------------------------------------------------------------

    def calculate_census(self):
        now = datetime.now()
        ble_persons = self._get_ble_persons()
        house_result = self._calculate_house_census(ble_persons, now)
        property_result = self._calculate_property_census(now)
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
        return result

    # ------------------------------------------------------------------
    # House census
    # ------------------------------------------------------------------

    def _calculate_house_census(self, ble_persons, now):
        configured_interior = self._get_interior_camera_entities()

        frigate_total = 0
        unifi_detected = False

        for entity_id in configured_interior:
            platform = self._camera_manager.get_platform_for_camera(entity_id)

            if platform == CAMERA_PLATFORM_FRIGATE:
                camera_info = self._camera_manager._camera_by_entity.get(entity_id)
                if camera_info and camera_info.person_count_sensor:
                    count = self._get_sensor_int(camera_info.person_count_sensor)
                    frigate_total += count
                else:
                    if self._is_entity_on(entity_id):
                        frigate_total += 1
            elif platform == CAMERA_PLATFORM_UNIFI:
                if self._is_entity_on(entity_id):
                    unifi_detected = True
            else:
                if self._is_entity_on(entity_id):
                    frigate_total += 1

        unifi_count = 1 if unifi_detected else 0

        if configured_interior:
            camera_total, agreement = self._cross_validate_platforms(frigate_total, unifi_count)
        else:
            camera_total = 0
            agreement = CENSUS_AGREEMENT_SINGLE

        ble_id_set = set(ble_persons)
        face_id_set = set()

        return self._cross_correlate_persons(
            face_ids=face_id_set,
            ble_ids=ble_id_set,
            camera_total=camera_total,
            zone="house",
            frigate_count=frigate_total,
            unifi_count=unifi_count,
            agreement=agreement,
            now=now,
        )

    # ------------------------------------------------------------------
    # Property census
    # ------------------------------------------------------------------

    def _calculate_property_census(self, now):
        egress_entities = self._get_integration_camera_list(CONF_EGRESS_CAMERAS)
        perimeter_entities = self._get_integration_camera_list(CONF_PERIMETER_CAMERAS)
        all_exterior = egress_entities + perimeter_entities

        exterior_count = 0
        for entity_id in all_exterior:
            if self._is_entity_on(entity_id):
                exterior_count += 1

        if not all_exterior:
            confidence = CENSUS_CONFIDENCE_NONE
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

    def _cross_validate_platforms(self, frigate_count, unifi_count):
        if frigate_count == 0 and unifi_count == 0:
            return (0, CENSUS_AGREEMENT_BOTH)
        if frigate_count > 0 and unifi_count > 0:
            return (frigate_count, CENSUS_AGREEMENT_BOTH)
        if frigate_count > 0 and unifi_count == 0:
            return (frigate_count, CENSUS_AGREEMENT_CLOSE)
        if frigate_count == 0 and unifi_count > 0:
            return (1, CENSUS_AGREEMENT_CLOSE)
        total = max(frigate_count, unifi_count)
        return (total, CENSUS_AGREEMENT_SINGLE)

    # ------------------------------------------------------------------
    # Cross-correlation
    # ------------------------------------------------------------------

    def _cross_correlate_persons(self, face_ids, ble_ids, camera_total,
                                  zone, frigate_count, unifi_count, agreement, now):
        known_persons = face_ids | ble_ids
        identified_count = len(known_persons)
        identified_persons = sorted(list(known_persons))

        if camera_total > 0:
            unidentified_count = max(0, camera_total - identified_count)
            total = max(camera_total, identified_count)
        else:
            unidentified_count = 0
            total = identified_count

        if camera_total == 0 and identified_count == 0:
            confidence = CENSUS_CONFIDENCE_NONE
        elif camera_total == 0 and identified_count > 0:
            confidence = CENSUS_CONFIDENCE_LOW
        elif agreement == CENSUS_AGREEMENT_BOTH:
            confidence = CENSUS_CONFIDENCE_HIGH
        elif agreement == CENSUS_AGREEMENT_CLOSE:
            confidence = CENSUS_CONFIDENCE_MEDIUM
        elif agreement == CENSUS_AGREEMENT_DISAGREE:
            confidence = CENSUS_CONFIDENCE_LOW
        else:
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
    # Configuration helpers
    # ------------------------------------------------------------------

    def _get_interior_camera_entities(self):
        entities = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            merged = {**entry.data, **entry.options}
            room_cameras = merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
            if room_cameras:
                entities.extend(room_cameras)
        return entities

    def _get_integration_camera_list(self, conf_key):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return merged.get(conf_key, [])
        return []

    # ------------------------------------------------------------------
    # HA state helpers
    # ------------------------------------------------------------------

    def _is_entity_on(self, entity_id):
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if state.state in ("unavailable", "unknown"):
            return False
        return state.state == "on"

    def _get_sensor_int(self, entity_id, default=0):
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return default
        try:
            return int(float(state.state))
        except (ValueError, TypeError):
            return default

    # ------------------------------------------------------------------
    # BLE person data
    # ------------------------------------------------------------------

    def _get_ble_persons(self):
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator or not person_coordinator.data:
            return []
        home_persons = []
        for person_id, person_info in person_coordinator.data.items():
            location = person_info.get("location", "")
            if location and location not in ("away", "unknown", ""):
                home_persons.append(person_id)
        return home_persons


# ============================================================================
# Helpers used across tests
# ============================================================================

def make_hass_with_entries(integration_data=None, room_entries=None):
    """Build a MockHass wired up with config entries.

    integration_data: dict merged with {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    room_entries: list of dicts merged with {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    """
    hass = MockHass()

    all_entries = []

    if integration_data is not None:
        entry_data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
        entry_data.update(integration_data)
        all_entries.append(MockConfigEntry(data=entry_data, entry_id="integration_entry"))

    for i, room_data in enumerate(room_entries or []):
        entry_data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
        entry_data.update(room_data)
        all_entries.append(MockConfigEntry(data=entry_data, entry_id=f"room_entry_{i}"))

    # Wire async_entries to return our list
    hass.config_entries.async_entries = lambda domain=None: all_entries

    return hass


def make_camera_manager_with_entities(entity_tuples):
    """Build a StubCameraIntegrationManager pre-loaded with entity data.

    entity_tuples: list of (entity_id, area_id) pairs
    """
    mgr = StubCameraIntegrationManager()
    # include count sensors so the manager can associate them
    mgr._process_entities(entity_tuples)
    return mgr


# ============================================================================
# CameraIntegrationManager Tests
# ============================================================================

class TestCameraIntegrationManagerDiscovery:
    """Test entity discovery in CameraIntegrationManager."""

    def test_discovers_frigate_by_person_occupancy_suffix(self):
        """Discovery identifies Frigate entities by _person_occupancy suffix."""
        entities = [
            ("binary_sensor.front_door_cam_person_occupancy", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        assert mgr.has_cameras() is True
        frigate_cameras = mgr.get_all_frigate_cameras()
        assert len(frigate_cameras) == 1
        assert frigate_cameras[0].entity_id == "binary_sensor.front_door_cam_person_occupancy"
        assert frigate_cameras[0].platform == CAMERA_PLATFORM_FRIGATE

    def test_discovers_unifi_by_person_detected_suffix(self):
        """Discovery identifies UniFi entities by _person_detected suffix."""
        entities = [
            ("binary_sensor.backyard_camera_person_detected", "area_outdoor"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        assert mgr.has_cameras() is True
        unifi_cameras = mgr.get_all_unifi_cameras()
        assert len(unifi_cameras) == 1
        assert unifi_cameras[0].entity_id == "binary_sensor.backyard_camera_person_detected"
        assert unifi_cameras[0].platform == CAMERA_PLATFORM_UNIFI

    def test_discovers_both_platforms_simultaneously(self):
        """Discovery handles mixed Frigate and UniFi entities in one pass."""
        entities = [
            ("binary_sensor.living_room_cam_person_occupancy", "area_living"),
            ("binary_sensor.garage_camera_person_detected", "area_garage"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        assert len(mgr.get_all_frigate_cameras()) == 1
        assert len(mgr.get_all_unifi_cameras()) == 1

    def test_ignores_non_binary_sensor_entities(self):
        """Non binary_sensor entities are not registered as cameras."""
        entities = [
            ("sensor.front_door_cam_person_count", "area_living"),
            ("camera.living_room_high_resolution_channel", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        assert mgr.has_cameras() is False

    def test_associates_frigate_person_count_sensor(self):
        """Frigate discovery associates the matching sensor.*_person_count."""
        entities = [
            ("binary_sensor.living_cam_person_occupancy", "area_living"),
            ("sensor.living_cam_person_count", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        frigate_cameras = mgr.get_all_frigate_cameras()
        assert len(frigate_cameras) == 1
        camera = frigate_cameras[0]
        assert camera.person_count_sensor == "sensor.living_cam_person_count"

    def test_frigate_without_count_sensor_has_none(self):
        """Frigate camera with no matching count sensor leaves person_count_sensor as None."""
        entities = [
            ("binary_sensor.office_cam_person_occupancy", "area_office"),
            # No sensor.office_cam_person_count in entity list
        ]
        mgr = make_camera_manager_with_entities(entities)

        frigate_cameras = mgr.get_all_frigate_cameras()
        assert frigate_cameras[0].person_count_sensor is None

    def test_multiple_frigate_cameras_same_area(self):
        """Multiple Frigate cameras can be associated to the same area."""
        entities = [
            ("binary_sensor.cam_a_person_occupancy", "area_living"),
            ("binary_sensor.cam_b_person_occupancy", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        cameras = mgr.get_cameras_for_area("area_living")
        assert len(cameras) == 2


class TestCameraIntegrationManagerLookup:
    """Test lookup methods of CameraIntegrationManager."""

    def test_get_cameras_for_area_returns_correct_cameras(self):
        """get_cameras_for_area returns only cameras for that area."""
        entities = [
            ("binary_sensor.living_cam_person_occupancy", "area_living"),
            ("binary_sensor.bedroom_cam_person_occupancy", "area_bedroom"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        living_cameras = mgr.get_cameras_for_area("area_living")
        bedroom_cameras = mgr.get_cameras_for_area("area_bedroom")

        assert len(living_cameras) == 1
        assert living_cameras[0].entity_id == "binary_sensor.living_cam_person_occupancy"
        assert len(bedroom_cameras) == 1

    def test_get_cameras_for_area_returns_empty_list_for_unknown_area(self):
        """get_cameras_for_area returns [] for an area with no cameras."""
        entities = [
            ("binary_sensor.living_cam_person_occupancy", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        cameras = mgr.get_cameras_for_area("area_nonexistent")
        assert cameras == []

    def test_has_cameras_returns_false_when_nothing_discovered(self):
        """has_cameras returns False before any entities are registered."""
        mgr = StubCameraIntegrationManager()
        assert mgr.has_cameras() is False

    def test_has_cameras_returns_true_after_discovery(self):
        """has_cameras returns True once at least one entity is registered."""
        entities = [
            ("binary_sensor.cam_person_occupancy", "area_a"),
        ]
        mgr = make_camera_manager_with_entities(entities)
        assert mgr.has_cameras() is True

    def test_get_platform_for_frigate_camera(self):
        """get_platform_for_camera returns 'frigate' for Frigate entity."""
        entities = [
            ("binary_sensor.front_cam_person_occupancy", "area_front"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        platform = mgr.get_platform_for_camera("binary_sensor.front_cam_person_occupancy")
        assert platform == CAMERA_PLATFORM_FRIGATE

    def test_get_platform_for_unifi_camera(self):
        """get_platform_for_camera returns 'unifiprotect' for UniFi entity."""
        entities = [
            ("binary_sensor.back_cam_person_detected", "area_back"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        platform = mgr.get_platform_for_camera("binary_sensor.back_cam_person_detected")
        assert platform == CAMERA_PLATFORM_UNIFI

    def test_get_platform_for_unknown_entity_returns_none(self):
        """get_platform_for_camera returns None for unregistered entity."""
        mgr = StubCameraIntegrationManager()
        platform = mgr.get_platform_for_camera("binary_sensor.not_registered")
        assert platform is None


# ============================================================================
# PersonCensus — House Census Tests
# ============================================================================

class TestPersonCensusHouseNoCameras:
    """House census with no cameras falls back to BLE-only."""

    def test_ble_only_fallback_confidence_is_low(self):
        """BLE-only fallback (no cameras) should yield low confidence."""
        hass = make_hass_with_entries(room_entries=[
            {"room_name": "Bedroom"}  # No camera_person_entities
        ])
        hass.data = {DOMAIN: {"person_coordinator": MagicMock(
            data={"person_alice": {"location": "bedroom"}}
        )}}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        result = census.calculate_census()

        assert result.house.confidence == CENSUS_CONFIDENCE_LOW
        assert "person_alice" in result.house.identified_persons

    def test_no_cameras_no_ble_yields_none_confidence(self):
        """No cameras and no BLE persons returns confidence none."""
        hass = make_hass_with_entries(room_entries=[
            {"room_name": "Bedroom"}
        ])
        # No person_coordinator
        hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        result = census.calculate_census()

        assert result.house.confidence == CENSUS_CONFIDENCE_NONE
        assert result.house.total_persons == 0


class TestPersonCensusHouseFrigate:
    """House census reading from Frigate count sensors."""

    def test_frigate_count_sensor_read(self, mock_hass):
        """Frigate person_count sensor provides numeric count."""
        entities = [
            ("binary_sensor.living_cam_person_occupancy", "area_living"),
            ("sensor.living_cam_person_count", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("sensor.living_cam_person_count", "2")
        mock_hass.set_state("binary_sensor.living_cam_person_occupancy", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.living_cam_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        # 2 persons from Frigate count sensor, no BLE
        assert result.house.frigate_count == 2
        assert result.house.total_persons >= 2

    def test_frigate_binary_fallback_when_no_count_sensor(self, mock_hass):
        """Frigate binary sensor contributes 1 when no count sensor available."""
        entities = [
            ("binary_sensor.office_cam_person_occupancy", "area_office"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.office_cam_person_occupancy", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.office_cam_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.frigate_count == 1

    def test_frigate_off_contributes_zero(self, mock_hass):
        """Frigate binary sensor that is 'off' contributes 0."""
        entities = [
            ("binary_sensor.office_cam_person_occupancy", "area_office"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.office_cam_person_occupancy", "off")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.office_cam_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.frigate_count == 0


class TestPersonCensusHouseUniFi:
    """House census reading from UniFi binary presence sensors."""

    def test_unifi_on_sets_unifi_detected(self, mock_hass):
        """UniFi 'on' state sets unifi_count=1 in result."""
        entities = [
            ("binary_sensor.back_cam_person_detected", "area_back"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.back_cam_person_detected", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.back_cam_person_detected"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.unifi_count == 1

    def test_unifi_off_sets_unifi_count_zero(self, mock_hass):
        """UniFi 'off' state sets unifi_count=0."""
        entities = [
            ("binary_sensor.back_cam_person_detected", "area_back"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.back_cam_person_detected", "off")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.back_cam_person_detected"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.unifi_count == 0


# ============================================================================
# PersonCensus — Cross-Validation Tests
# ============================================================================

class TestPersonCensusCrossValidation:
    """Test cross-validation logic between Frigate and UniFi platforms."""

    def _make_census(self):
        """Return a bare PersonCensusStub with empty hass/manager."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {}
        mgr = StubCameraIntegrationManager()
        return PersonCensusStub(hass, mgr)

    def test_both_agree_zero_returns_both_agree(self):
        """Frigate=0, UniFi=0 → both_agree, count=0."""
        census = self._make_census()
        count, agreement = census._cross_validate_platforms(0, 0)
        assert count == 0
        assert agreement == CENSUS_AGREEMENT_BOTH

    def test_both_detect_returns_both_agree_with_frigate_count(self):
        """Frigate=3, UniFi=1 → both_agree, count=3 (Frigate is authoritative)."""
        census = self._make_census()
        count, agreement = census._cross_validate_platforms(3, 1)
        assert count == 3
        assert agreement == CENSUS_AGREEMENT_BOTH

    def test_frigate_only_detection_returns_close(self):
        """Frigate detects persons, UniFi does not → close agreement."""
        census = self._make_census()
        count, agreement = census._cross_validate_platforms(2, 0)
        assert count == 2
        assert agreement == CENSUS_AGREEMENT_CLOSE

    def test_unifi_only_detection_returns_close_with_min_one(self):
        """UniFi detects, Frigate does not → close agreement, count=1."""
        census = self._make_census()
        count, agreement = census._cross_validate_platforms(0, 1)
        assert count == 1
        assert agreement == CENSUS_AGREEMENT_CLOSE

    def test_both_agree_yields_high_confidence(self, mock_hass):
        """Both cameras agree → confidence is high."""
        entities = [
            ("binary_sensor.cam_a_person_occupancy", "area_a"),
            ("binary_sensor.cam_b_person_detected", "area_a"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.cam_a_person_occupancy", "on")
        mock_hass.set_state("binary_sensor.cam_b_person_detected", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: [
                    "binary_sensor.cam_a_person_occupancy",
                    "binary_sensor.cam_b_person_detected",
                ],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.confidence == CENSUS_CONFIDENCE_HIGH

    def test_one_detects_other_does_not_yields_medium_confidence(self, mock_hass):
        """Frigate on, UniFi off → close agreement → medium confidence."""
        entities = [
            ("binary_sensor.cam_a_person_occupancy", "area_a"),
            ("binary_sensor.cam_b_person_detected", "area_a"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.cam_a_person_occupancy", "on")
        mock_hass.set_state("binary_sensor.cam_b_person_detected", "off")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: [
                    "binary_sensor.cam_a_person_occupancy",
                    "binary_sensor.cam_b_person_detected",
                ],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.confidence == CENSUS_CONFIDENCE_MEDIUM

    def test_no_cameras_configured_falls_back_to_ble_only(self, mock_hass):
        """No interior cameras → single_source agreement, BLE-only path."""
        mgr = StubCameraIntegrationManager()

        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, "room_name": "Bedroom"})
        ]
        mock_hass.data = {DOMAIN: {"person_coordinator": MagicMock(
            data={"person_bob": {"location": "bedroom"}}
        )}}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        # BLE only → single_source agreement → low confidence
        assert result.house.source_agreement == CENSUS_AGREEMENT_SINGLE
        assert result.house.confidence == CENSUS_CONFIDENCE_LOW


# ============================================================================
# PersonCensus — Cross-Correlation Tests
# ============================================================================

class TestPersonCensusCrossCorrelation:
    """Test face+BLE union for identified count and guest detection."""

    def _bare_census(self):
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {}
        mgr = StubCameraIntegrationManager()
        return PersonCensusStub(hass, mgr)

    def test_face_and_ble_union_for_identified_count(self):
        """Face IDs and BLE IDs are unioned for identified_count."""
        census = self._bare_census()
        now = datetime.now()

        result = census._cross_correlate_persons(
            face_ids={"alice", "bob"},
            ble_ids={"bob", "charlie"},  # bob overlaps
            camera_total=3,
            zone="house",
            frigate_count=3,
            unifi_count=1,
            agreement=CENSUS_AGREEMENT_BOTH,
            now=now,
        )

        # Union: alice, bob, charlie = 3 identified
        assert result.identified_count == 3
        assert set(result.identified_persons) == {"alice", "bob", "charlie"}

    def test_guest_detection_camera_total_exceeds_identified(self):
        """Camera total > identified count → unidentified guests detected."""
        census = self._bare_census()
        now = datetime.now()

        result = census._cross_correlate_persons(
            face_ids=set(),
            ble_ids={"alice"},  # 1 identified
            camera_total=3,     # camera sees 3 people
            zone="house",
            frigate_count=3,
            unifi_count=1,
            agreement=CENSUS_AGREEMENT_BOTH,
            now=now,
        )

        assert result.identified_count == 1
        assert result.unidentified_count == 2  # 3 - 1 = 2 guests
        assert result.total_persons == 3

    def test_no_guests_when_identified_matches_camera(self):
        """No unidentified guests when BLE count equals camera count."""
        census = self._bare_census()
        now = datetime.now()

        result = census._cross_correlate_persons(
            face_ids=set(),
            ble_ids={"alice", "bob"},
            camera_total=2,
            zone="house",
            frigate_count=2,
            unifi_count=1,
            agreement=CENSUS_AGREEMENT_BOTH,
            now=now,
        )

        assert result.unidentified_count == 0
        assert result.total_persons == 2

    def test_total_at_least_identified_when_camera_lower(self):
        """Total cannot be less than identified count even if camera count is lower."""
        census = self._bare_census()
        now = datetime.now()

        result = census._cross_correlate_persons(
            face_ids=set(),
            ble_ids={"alice", "bob", "charlie"},  # 3 BLE identified
            camera_total=1,                         # camera only sees 1
            zone="house",
            frigate_count=1,
            unifi_count=1,
            agreement=CENSUS_AGREEMENT_BOTH,
            now=now,
        )

        # total = max(camera_total, identified_count) = max(1, 3) = 3
        assert result.total_persons == 3
        assert result.unidentified_count == 0  # identified >= camera


# ============================================================================
# PersonCensus — Property (Exterior) Census Tests
# ============================================================================

class TestPersonCensusPropertyCensus:
    """Test the property (exterior) census zone."""

    def test_no_egress_or_perimeter_configured_yields_zero_count_none_confidence(self):
        """No exterior cameras → 0 count, confidence=none."""
        hass = make_hass_with_entries(
            integration_data={},  # No egress_cameras or perimeter_cameras
        )
        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        result = census.calculate_census()

        assert result.property_exterior.total_persons == 0
        assert result.property_exterior.confidence == CENSUS_CONFIDENCE_NONE

    def test_egress_camera_active_increments_exterior_count(self, mock_hass):
        """Active egress camera increments exterior count by 1."""
        mock_hass.set_state("binary_sensor.front_door_cam_person_occupancy", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_EGRESS_CAMERAS: ["binary_sensor.front_door_cam_person_occupancy"],
                CONF_PERIMETER_CAMERAS: [],
            })
        ]
        mock_hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.property_exterior.total_persons == 1

    def test_perimeter_camera_active_increments_exterior_count(self, mock_hass):
        """Active perimeter camera increments exterior count by 1."""
        mock_hass.set_state("binary_sensor.backyard_person_detected", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_EGRESS_CAMERAS: [],
                CONF_PERIMETER_CAMERAS: ["binary_sensor.backyard_person_detected"],
            })
        ]
        mock_hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.property_exterior.total_persons == 1

    def test_multiple_active_cameras_count_reflected(self, mock_hass):
        """Multiple active exterior cameras each contribute 1 to count."""
        mock_hass.set_state("binary_sensor.front_cam_person_occupancy", "on")
        mock_hass.set_state("binary_sensor.side_cam_person_detected", "on")
        mock_hass.set_state("binary_sensor.back_cam_person_detected", "off")

        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_EGRESS_CAMERAS: ["binary_sensor.front_cam_person_occupancy"],
                CONF_PERIMETER_CAMERAS: [
                    "binary_sensor.side_cam_person_detected",
                    "binary_sensor.back_cam_person_detected",
                ],
            })
        ]
        mock_hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.property_exterior.total_persons == 2

    def test_egress_inactive_yields_zero_count(self, mock_hass):
        """Egress camera reporting off yields 0 exterior count."""
        mock_hass.set_state("binary_sensor.front_door_cam_person_occupancy", "off")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_EGRESS_CAMERAS: ["binary_sensor.front_door_cam_person_occupancy"],
                CONF_PERIMETER_CAMERAS: [],
            })
        ]
        mock_hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.property_exterior.total_persons == 0

    def test_exterior_cameras_configured_but_inactive_yields_medium_confidence(self, mock_hass):
        """Exterior cameras exist but all off → medium confidence (not none)."""
        mock_hass.set_state("binary_sensor.front_door_cam_person_occupancy", "off")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_EGRESS_CAMERAS: ["binary_sensor.front_door_cam_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        # cameras configured but inactive → medium (not none)
        assert result.property_exterior.confidence == CENSUS_CONFIDENCE_MEDIUM


# ============================================================================
# FullCensusResult Tests
# ============================================================================

class TestFullCensusResult:
    """Test the combined FullCensusResult totals."""

    def test_total_on_property_equals_house_plus_exterior(self, mock_hass):
        """total_on_property = house.total + property_exterior.total."""
        mock_hass.set_state("binary_sensor.living_cam_person_occupancy", "on")
        mock_hass.set_state("sensor.living_cam_person_count", "2")
        mock_hass.set_state("binary_sensor.front_door_person_occupancy", "on")

        entities = [
            ("binary_sensor.living_cam_person_occupancy", "area_living"),
            ("sensor.living_cam_person_count", "area_living"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_EGRESS_CAMERAS: ["binary_sensor.front_door_person_occupancy"],
                CONF_PERIMETER_CAMERAS: [],
            }),
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.living_cam_person_occupancy"],
            }),
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.total_on_property == result.house.total_persons + result.property_exterior.total_persons

    def test_persons_outside_equals_property_exterior_total(self, mock_hass):
        """persons_outside is a convenience alias for property_exterior.total."""
        mock_hass.set_state("binary_sensor.backyard_person_detected", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_PERIMETER_CAMERAS: ["binary_sensor.backyard_person_detected"],
            })
        ]
        mock_hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.persons_outside == result.property_exterior.total_persons

    def test_ble_persons_included_in_result(self):
        """BLE persons from person_coordinator appear in ble_persons list."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {DOMAIN: {"person_coordinator": MagicMock(
            data={
                "person_alice": {"location": "bedroom"},
                "person_bob": {"location": "kitchen"},
            }
        )}}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        result = census.calculate_census()

        assert "person_alice" in result.ble_persons
        assert "person_bob" in result.ble_persons


# ============================================================================
# Graceful Degradation Tests
# ============================================================================

class TestGracefulDegradation:
    """Test that the census handles missing/bad data without crashing."""

    def test_unavailable_camera_entity_treated_as_off(self, mock_hass):
        """Camera entity in 'unavailable' state treated as off (not raising)."""
        entities = [
            ("binary_sensor.cam_a_person_occupancy", "area_a"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.cam_a_person_occupancy", "unavailable")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.cam_a_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        # unavailable → treated as off → frigate_count = 0
        assert result.house.frigate_count == 0

    def test_unknown_state_camera_treated_as_off(self, mock_hass):
        """Camera entity in 'unknown' state treated as off."""
        entities = [
            ("binary_sensor.cam_a_person_occupancy", "area_a"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("binary_sensor.cam_a_person_occupancy", "unknown")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.cam_a_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        result = census.calculate_census()

        assert result.house.frigate_count == 0

    def test_missing_person_coordinator_returns_empty_ble_list(self):
        """Missing person_coordinator yields empty BLE list without error."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {}  # No DOMAIN key at all

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        ble = census._get_ble_persons()

        assert ble == []

    def test_person_coordinator_with_no_data_returns_empty_ble_list(self):
        """person_coordinator with empty data yields empty BLE list."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {DOMAIN: {"person_coordinator": MagicMock(data=None)}}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        ble = census._get_ble_persons()

        assert ble == []

    def test_no_integration_entry_yields_empty_exterior_camera_list(self):
        """No integration config entry → exterior camera lists are empty."""
        hass = MockHass()
        # Only room entries, no integration entry
        hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, "room_name": "Bedroom"})
        ]
        hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        egress = census._get_integration_camera_list(CONF_EGRESS_CAMERAS)
        perimeter = census._get_integration_camera_list(CONF_PERIMETER_CAMERAS)

        assert egress == []
        assert perimeter == []

    def test_no_room_entries_yields_empty_interior_camera_list(self):
        """No room config entries → interior camera entity list is empty."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION})
        ]
        hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        interior = census._get_interior_camera_entities()

        assert interior == []

    def test_person_away_not_counted_as_home(self):
        """Person with location='away' is not included in BLE home list."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {DOMAIN: {"person_coordinator": MagicMock(
            data={
                "person_alice": {"location": "away"},
                "person_bob": {"location": "bedroom"},
            }
        )}}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        ble = census._get_ble_persons()

        assert "person_alice" not in ble
        assert "person_bob" in ble

    def test_person_unknown_location_not_counted_as_home(self):
        """Person with location='unknown' is not included in BLE home list."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {DOMAIN: {"person_coordinator": MagicMock(
            data={"person_charlie": {"location": "unknown"}}
        )}}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        ble = census._get_ble_persons()

        assert "person_charlie" not in ble

    def test_count_sensor_unavailable_defaults_to_zero(self, mock_hass):
        """Unavailable count sensor returns 0 via _get_sensor_int."""
        entities = [
            ("binary_sensor.cam_person_occupancy", "area_a"),
            ("sensor.cam_person_count", "area_a"),
        ]
        mgr = make_camera_manager_with_entities(entities)

        mock_hass.set_state("sensor.cam_person_count", "unavailable")
        mock_hass.set_state("binary_sensor.cam_person_occupancy", "on")
        mock_hass.config_entries.async_entries = lambda domain=None: [
            MockConfigEntry(data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_CAMERA_PERSON_ENTITIES: ["binary_sensor.cam_person_occupancy"],
            })
        ]
        mock_hass.data = {}

        census = PersonCensusStub(mock_hass, mgr)
        # Direct helper check
        count = census._get_sensor_int("sensor.cam_person_count")
        assert count == 0

    def test_full_census_completes_without_any_data(self):
        """calculate_census() returns a valid FullCensusResult even with no data."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {}

        mgr = StubCameraIntegrationManager()
        census = PersonCensusStub(hass, mgr)
        result = census.calculate_census()

        assert isinstance(result, FullCensusResult)
        assert result.total_on_property == 0
        assert result.persons_outside == 0
