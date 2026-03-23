"""Tests for v3.10.1 Census v2: Enhanced event-driven sensor fusion.

Covers:
  - Hold/decay mechanics (interior gradual decay, exterior instant drop)
  - Peak tracking and reset
  - Unrecognized camera count (seen vs recognized)
  - WiFi guest VLAN detection (SSID, hostname filtering, person exclusion, recency)
  - Face recognized person names (window, tracked persons)
  - Enhanced house census (formula: unidentified = camera_unrecognized; WiFi disabled)
  - Enhanced property census (hold/decay on exterior)
  - Config toggle (enabled/disabled)
  - Edge cases (no cameras, no WiFi guests, stale face recognition)
"""
import pytest
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch
from tests.conftest import MockHass, MockConfigEntry, MockState


# ============================================================================
# TEST CONSTANTS (mirrors const.py)
# ============================================================================

DOMAIN = "universal_room_automation"
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_INTEGRATION = "integration"
CAMERA_PLATFORM_FRIGATE = "frigate"
CAMERA_PLATFORM_UNIFI = "unifiprotect"
CONF_ENHANCED_CENSUS = "enhanced_census"
CONF_CENSUS_HOLD_INTERIOR = "census_hold_interior"
CONF_CENSUS_HOLD_EXTERIOR = "census_hold_exterior"
DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES = 15
DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES = 5
CENSUS_DECAY_STEP_SECONDS = 300
CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800
CONF_GUEST_VLAN_SSID = "guest_vlan_ssid"
DEFAULT_GUEST_VLAN_SSID = ""
PHONE_MANUFACTURERS = frozenset({
    "Apple, Inc.", "Samsung Electronics Co.,Ltd", "Google, Inc.",
    "OnePlus Technology (Shenzhen) Co., Ltd", "Huawei Technologies Co.,Ltd",
    "Xiaomi Communications Co Ltd", "Motorola Mobility LLC, a Lenovo Company",
    "LG Electronics", "Sony Mobile Communications Inc", "OPPO",
    "vivo Mobile Communication Co., Ltd.", "Nothing Technology Limited", "Fairphone",
})
PHONE_HOSTNAME_PREFIXES = (
    "iphone", "galaxy", "pixel", "oneplus", "huawei",
    "xiaomi", "redmi", "poco", "motorola", "nothing", "fairphone",
    "oppo", "vivo", "realme",
)
PHONE_ONLY_MANUFACTURERS = frozenset({
    "Apple, Inc.",
    "Google, Inc.",
    "OnePlus Technology (Shenzhen) Co., Ltd",
    "Huawei Technologies Co.,Ltd",
    "Xiaomi Communications Co Ltd",
    "Motorola Mobility LLC, a Lenovo Company",
    "Sony Mobile Communications Inc",
    "Nothing Technology Limited",
    "Fairphone",
})
WIFI_GUEST_RECENCY_HOURS = 24
NON_GUEST_HOSTNAME_PREFIXES = (
    "samsung", "homepod", "wiim", "sonos",
    "trc-", "urc",
    "espressif", "esp-", "esp_",
    "shelly", "tasmota", "tuya",
    "armcrest", "amcrest", "reolink", "dahua",
    "g3-", "g4-", "g5-",
    "envoy", "enphase",
    "ubiquiti", "unifi",
)
TABLET_HOSTNAME_PREFIXES = (
    "ipad",
)
CONF_CAMERA_PERSON_ENTITIES = "camera_person_entities"
CONF_EGRESS_CAMERAS = "egress_cameras"
CONF_PERIMETER_CAMERAS = "perimeter_cameras"
CONF_CENSUS_CROSS_VALIDATION = "census_cross_validation"


# ============================================================================
# LOCAL DATACLASSES (mirrors camera_census.py without HA imports)
# ============================================================================

@dataclass
class CameraInfo:
    entity_id: str
    platform: str
    area_id: Optional[str] = None
    person_binary_sensor: Optional[str] = None
    person_count_sensor: Optional[str] = None


@dataclass
class CensusZoneResult:
    zone: str
    identified_count: int
    identified_persons: list
    unidentified_count: int
    total_persons: int
    confidence: str
    source_agreement: str
    frigate_count: int
    unifi_count: int
    degraded_mode: bool = False
    active_platforms: list = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    wifi_guest_floor: int = 0
    camera_unrecognized: int = 0
    peak_held: bool = False
    peak_age_minutes: int = 0
    face_recognized_persons: list = field(default_factory=list)
    enhanced_census: bool = False


# ============================================================================
# STUB PERSON CENSUS (re-implements v2 methods under test)
# ============================================================================

class StubPersonCensusV2:
    """Re-implements Census v2 methods as pure Python for isolated testing.

    This mirrors the actual PersonCensus class methods from camera_census.py
    without any HA framework dependencies.
    """

    def __init__(self, hass, camera_manager=None):
        self.hass = hass
        self._camera_manager = camera_manager or StubCameraManager()
        self._peak_house_camera_count = 0
        self._peak_house_timestamp = None
        self._peak_property_count = 0
        self._peak_property_timestamp = None

    def _is_enhanced_census_enabled(self) -> bool:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                return bool(merged.get(CONF_ENHANCED_CENSUS, True))
        return True

    def _get_hold_seconds(self, zone: str) -> int:
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
        hold_seconds = self._get_hold_seconds(zone)

        if zone == "house":
            peak = self._peak_house_camera_count
            peak_ts = self._peak_house_timestamp
        else:
            peak = self._peak_property_count
            peak_ts = self._peak_property_timestamp

        if fresh_count >= peak or peak_ts is None:
            peak = fresh_count
            peak_ts = now
            if zone == "house":
                self._peak_house_camera_count = peak
                self._peak_house_timestamp = peak_ts
            else:
                self._peak_property_count = peak
                self._peak_property_timestamp = peak_ts
            return (fresh_count, False, 0)

        elapsed = (now - peak_ts).total_seconds()

        if elapsed < hold_seconds:
            age_min = int(elapsed / 60)
            return (peak, True, age_min)

        if zone == "house":
            elapsed_after_hold = elapsed - hold_seconds
            decay_steps = int(elapsed_after_hold / CENSUS_DECAY_STEP_SECONDS)
            decayed = max(fresh_count, peak - decay_steps)
            if decayed <= fresh_count:
                self._peak_house_camera_count = fresh_count
                self._peak_house_timestamp = now
                return (fresh_count, False, 0)
            age_min = int(elapsed / 60)
            return (decayed, True, age_min)
        else:
            self._peak_property_count = fresh_count
            self._peak_property_timestamp = now
            return (fresh_count, False, 0)

    def _get_unrecognized_camera_count(self) -> int:
        unrecognized = 0
        now = datetime.now()
        configured_interior = self._get_interior_camera_entities()

        for entity_id in configured_interior:
            platform = self._camera_manager.get_platform_for_camera(entity_id)
            if platform != CAMERA_PLATFORM_FRIGATE:
                continue

            camera_info = self._camera_manager._camera_by_entity.get(entity_id)
            if not camera_info or not camera_info.person_count_sensor:
                continue

            count = self._get_sensor_int(camera_info.person_count_sensor)
            if count <= 0:
                continue

            bs_id = camera_info.entity_id
            if not bs_id.endswith("_person_occupancy"):
                unrecognized += count
                continue

            base_name = bs_id[len("binary_sensor."):-len("_person_occupancy")]
            face_sensor_id = f"sensor.{base_name}_last_recognized_face"
            face_state = self.hass.states.get(face_sensor_id)

            face_is_fresh = False
            if face_state and face_state.state.strip().lower() not in (
                "unavailable", "unknown", "", "none", "no_match",
            ):
                # Check freshness
                last_changed = face_state.last_changed
                if last_changed is not None:
                    try:
                        age = (now - last_changed.replace(tzinfo=None)).total_seconds()
                        face_is_fresh = age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS
                    except (TypeError, AttributeError):
                        face_is_fresh = False

            if face_is_fresh:
                unrecognized += max(0, count - 1)
            else:
                unrecognized += count

        return unrecognized

    def _get_wifi_guest_count(self, now=None) -> int:
        if now is None:
            now = datetime.now()

        guest_ssid = ""
        tracked_persons = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                merged = {**entry.data, **entry.options}
                guest_ssid = merged.get(CONF_GUEST_VLAN_SSID, DEFAULT_GUEST_VLAN_SSID)
                raw = merged.get("tracked_persons", [])
                tracked_persons = [p.strip() for p in raw if p.strip()]
                break

        # Build set of family device_tracker entity_ids from person entities
        family_trackers: set = set()
        for person_entity_id in tracked_persons:
            person_state = self.hass.states.get(person_entity_id)
            if person_state is not None:
                trackers = person_state.attributes.get("device_trackers", [])
                family_trackers.update(trackers)
                source = person_state.attributes.get("source")
                if source:
                    family_trackers.add(source)

        # Layer 1: Device registry expansion — find sibling device_tracker
        # entities on the same HA device.
        if hasattr(self, '_device_registry_siblings'):
            for tracker_eid in list(family_trackers):
                siblings = self._device_registry_siblings.get(tracker_eid, [])
                family_trackers.update(siblings)

        # Layer 2: MAC cross-reference
        family_macs: set = set()
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

            is_on_ssid = False
            if guest_ssid:
                if attrs.get("essid") == guest_ssid:
                    is_on_ssid = True
            else:
                if attrs.get("is_guest", False):
                    is_on_ssid = True

            if not is_on_ssid:
                continue

            # Filter 1: exclude empty hostnames
            hostname = attrs.get("host_name", "").lower()
            if not hostname:
                continue

            # Filter 2: exclude infrastructure devices
            if any(hostname.startswith(p) for p in NON_GUEST_HOSTNAME_PREFIXES):
                continue

            # Filter 3: exclude tablets (count phones only, 1 per guest)
            if any(hostname.startswith(p) for p in TABLET_HOSTNAME_PREFIXES):
                continue

            # Filter 4: exclude tracked persons' devices (family phones)
            if state.entity_id in family_trackers:
                continue

            # Filter 4b: exclude by MAC match against family devices
            device_mac = attrs.get("mac", "").lower()
            if device_mac and device_mac in family_macs:
                continue

            # Filter 5: recency — only count recently-appeared devices
            last_changed = state.last_changed
            if last_changed is not None:
                try:
                    age = (now - last_changed.replace(tzinfo=None)).total_seconds()
                    if age > recency_seconds:
                        continue
                except (TypeError, AttributeError):
                    pass  # If can't determine age, count it

            guest_count += 1

        return guest_count

    def _get_face_recognized_person_names(self, now: datetime) -> list[str]:
        recognized = []
        tracked_persons = []
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
            sensor_id = f"sensor.frigate_{person_slug.lower()}_last_camera"
            state = self.hass.states.get(sensor_id)
            if state is None:
                continue
            if state.state.strip().lower() in ("unknown", "unavailable", ""):
                continue
            last_changed = state.last_changed
            if last_changed is not None:
                try:
                    age = (now - last_changed.replace(tzinfo=None)).total_seconds()
                except (TypeError, AttributeError):
                    age = CENSUS_FACE_RECOGNITION_WINDOW_SECONDS + 1
                if age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS:
                    recognized.append(person_slug)

        return recognized

    def _apply_enhanced_house_census(
        self, raw_result, ble_persons, now
    ):
        camera_unrecognized = self._get_unrecognized_camera_count()
        wifi_guests = self._get_wifi_guest_count(now)
        face_recognized = self._get_face_recognized_person_names(now)

        recognized_set = set(ble_persons) | set(face_recognized)
        identified_count = len(recognized_set)
        unidentified_raw = camera_unrecognized

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
            wifi_guest_floor=wifi_guests,
            camera_unrecognized=camera_unrecognized,
            peak_held=peak_held,
            peak_age_minutes=peak_age,
            face_recognized_persons=face_recognized,
            enhanced_census=True,
        )

    def _apply_enhanced_property_census(self, raw_result, now):
        raw_count = raw_result.total_persons
        held_count, peak_held, peak_age = self._apply_hold_decay(
            raw_count, "property", now
        )
        if held_count == raw_count and not peak_held:
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
            peak_held=peak_held,
            peak_age_minutes=peak_age,
            enhanced_census=True,
        )

    # --- Helpers mirroring production code ---

    def _get_interior_camera_entities(self):
        """Return interior camera binary_sensor entity IDs from camera manager."""
        return list(self._camera_manager._camera_by_entity.keys())

    def _get_sensor_int(self, entity_id, default=0):
        state = self.hass.states.get(entity_id)
        if state is None:
            return default
        try:
            return int(float(state.state))
        except (ValueError, TypeError):
            return default


class StubCameraManager:
    """Minimal camera manager stub for tests."""

    def __init__(self):
        self._camera_by_entity = {}
        self._platform_by_entity = {}

    def add_camera(self, entity_id, platform, person_count_sensor=None):
        info = CameraInfo(
            entity_id=entity_id,
            platform=platform,
            person_binary_sensor=entity_id,
            person_count_sensor=person_count_sensor,
        )
        self._camera_by_entity[entity_id] = info
        self._platform_by_entity[entity_id] = platform

    def get_platform_for_camera(self, entity_id):
        return self._platform_by_entity.get(entity_id, "")


# ============================================================================
# FIXTURES
# ============================================================================

def _make_integration_entry(options=None):
    """Create a mock integration config entry."""
    data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    return MockConfigEntry(data=data, options=options or {})


def _make_hass_with_entry(options=None):
    """Create MockHass with an integration config entry."""
    hass = MockHass()
    entry = _make_integration_entry(options)
    hass.config_entries.async_entries = lambda domain: [entry]
    return hass


def _make_raw_house_result(total=3, identified=3, unidentified=0, **kwargs):
    """Create a baseline CensusZoneResult for house zone."""
    return CensusZoneResult(
        zone="house",
        identified_count=identified,
        identified_persons=["oji", "ezinne", "jaya"][:identified],
        unidentified_count=unidentified,
        total_persons=total,
        confidence="high",
        source_agreement="both_agree",
        frigate_count=2,
        unifi_count=2,
        **kwargs,
    )


def _make_raw_property_result(total=1, **kwargs):
    """Create a baseline CensusZoneResult for property zone."""
    return CensusZoneResult(
        zone="property",
        identified_count=0,
        identified_persons=[],
        unidentified_count=total,
        total_persons=total,
        confidence="medium",
        source_agreement="single_source",
        frigate_count=total,
        unifi_count=0,
        **kwargs,
    )


# ============================================================================
# HOLD / DECAY TESTS
# ============================================================================

class TestHoldDecay:
    """Tests for _apply_hold_decay — the core peak-hold mechanism."""

    def test_initial_count_sets_peak(self):
        """First call should set the peak and return fresh count."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        count, held, age = census._apply_hold_decay(3, "house", datetime.now())
        assert count == 3
        assert held is False
        assert age == 0
        assert census._peak_house_camera_count == 3

    def test_higher_count_updates_peak(self):
        """A higher fresh count should update the peak."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        now = datetime.now()
        census._apply_hold_decay(2, "house", now)
        count, held, age = census._apply_hold_decay(5, "house", now + timedelta(seconds=30))
        assert count == 5
        assert held is False
        assert census._peak_house_camera_count == 5

    def test_equal_count_updates_timestamp(self):
        """Equal fresh count should update timestamp (>= comparison)."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(3, "house", t0)
        t1 = t0 + timedelta(seconds=30)
        count, held, age = census._apply_hold_decay(3, "house", t1)
        assert count == 3
        assert held is False
        assert census._peak_house_timestamp == t1

    def test_lower_count_within_hold_returns_peak(self):
        """During hold window, lower count should return stored peak."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(5, "house", t0)
        # 5 minutes later, count drops to 2
        t1 = t0 + timedelta(minutes=5)
        count, held, age = census._apply_hold_decay(2, "house", t1)
        assert count == 5
        assert held is True
        assert age == 5  # 5 minutes elapsed

    def test_hold_expires_house_starts_decay(self):
        """After hold window expires, house zone should start decaying."""
        hass = _make_hass_with_entry()  # default 15 min hold
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(5, "house", t0)
        # 16 minutes later (hold expired), fresh count is 1
        t1 = t0 + timedelta(minutes=16)
        count, held, age = census._apply_hold_decay(1, "house", t1)
        # After 15 min hold, 1 min elapsed = 60s / 300s = 0 decay steps
        # decayed = max(1, 5 - 0) = 5, but 1 min after hold only
        assert count == 5  # 0 complete decay steps
        assert held is True

    def test_house_decay_step_reduces_count(self):
        """Each 5-minute step after hold should reduce count by 1."""
        hass = _make_hass_with_entry()  # 15 min hold
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(5, "house", t0)
        # 20 minutes = 15 hold + 5 min = 1 decay step
        t1 = t0 + timedelta(minutes=20)
        count, held, age = census._apply_hold_decay(1, "house", t1)
        assert count == 4  # 5 - 1 step
        assert held is True

    def test_house_decay_multiple_steps(self):
        """Multiple decay steps should reduce count progressively."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(5, "house", t0)
        # 30 minutes = 15 hold + 15 min = 3 decay steps
        t1 = t0 + timedelta(minutes=30)
        count, held, age = census._apply_hold_decay(1, "house", t1)
        assert count == 2  # 5 - 3 steps = 2, still > fresh_count 1
        assert held is True

    def test_house_decay_bottoms_at_fresh(self):
        """Decay should never go below fresh count, then reset peak."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(3, "house", t0)
        # 40 minutes = 15 hold + 25 min = 5 decay steps
        # decayed = max(1, 3 - 5) = 1 (fresh count)
        t1 = t0 + timedelta(minutes=40)
        count, held, age = census._apply_hold_decay(1, "house", t1)
        assert count == 1  # bottomed at fresh
        assert held is False
        assert census._peak_house_camera_count == 1  # peak reset

    def test_property_hold_within_window(self):
        """Property zone should hold peak within its shorter window."""
        hass = _make_hass_with_entry()  # 5 min property hold
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(3, "property", t0)
        t1 = t0 + timedelta(minutes=3)
        count, held, age = census._apply_hold_decay(1, "property", t1)
        assert count == 3
        assert held is True

    def test_property_instant_drop_after_hold(self):
        """Property zone should drop instantly to fresh count after hold."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()
        census._apply_hold_decay(3, "property", t0)
        # 6 minutes later (hold expired)
        t1 = t0 + timedelta(minutes=6)
        count, held, age = census._apply_hold_decay(1, "property", t1)
        assert count == 1
        assert held is False
        assert census._peak_property_count == 1  # peak reset

    def test_custom_hold_duration_from_config(self):
        """Config-specified hold durations should override defaults."""
        hass = _make_hass_with_entry({
            CONF_CENSUS_HOLD_INTERIOR: 30,
            CONF_CENSUS_HOLD_EXTERIOR: 10,
        })
        census = StubPersonCensusV2(hass)
        assert census._get_hold_seconds("house") == 1800  # 30 min
        assert census._get_hold_seconds("property") == 600  # 10 min

    def test_default_hold_durations(self):
        """Default hold durations should be 15 min interior, 5 min exterior."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        assert census._get_hold_seconds("house") == 900
        assert census._get_hold_seconds("property") == 300

    def test_hold_no_config_entry_uses_defaults(self):
        """When no config entry exists, use defaults."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain: []
        census = StubPersonCensusV2(hass)
        assert census._get_hold_seconds("house") == 900
        assert census._get_hold_seconds("property") == 300


# ============================================================================
# UNRECOGNIZED CAMERA COUNT TESTS
# ============================================================================

class TestUnrecognizedCameraCount:
    """Tests for _get_unrecognized_camera_count — seen vs recognized."""

    def _setup_frigate_camera(self, hass, cam_mgr, base_name, person_count,
                               face_recognized=None, face_age_minutes=1):
        """Helper: set up a Frigate camera with count and face sensors.

        face_age_minutes: how old the face recognition is (default 1 min = fresh).
        """
        bs_id = f"binary_sensor.{base_name}_person_occupancy"
        count_id = f"sensor.{base_name}_person_count"
        face_id = f"sensor.{base_name}_last_recognized_face"
        now = datetime.now()

        cam_mgr.add_camera(bs_id, CAMERA_PLATFORM_FRIGATE, count_id)
        hass.set_state(count_id, str(person_count))
        face_value = face_recognized if face_recognized is not None else "unknown"
        hass.set_state_with_time(
            face_id, face_value,
            last_changed=now - timedelta(minutes=face_age_minutes),
        )

    def test_no_cameras_returns_zero(self):
        """No configured cameras should return 0."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        assert census._get_unrecognized_camera_count() == 0

    def test_all_faces_recognized(self):
        """All cameras see people with recognized faces = 0 unrecognized."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 1, "oji")
        self._setup_frigate_camera(hass, cam_mgr, "family_room", 1, "ezinne")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 0

    def test_unknown_face_counted(self):
        """Camera sees person with unknown face = unrecognized."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 1, "unknown")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 1

    def test_no_match_face_counted(self):
        """Face sensor showing 'no_match' = unrecognized."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 1, "no_match")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 1

    def test_mixed_recognized_and_unrecognized(self):
        """Mix of recognized and unrecognized across cameras."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 1, "oji")       # recognized
        self._setup_frigate_camera(hass, cam_mgr, "family_room", 1, "unknown")  # unrecognized
        self._setup_frigate_camera(hass, cam_mgr, "foyer", 2, "unknown")        # 2 unrecognized
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 3  # 0 + 1 + 2

    def test_recognized_face_with_extra_persons(self):
        """Camera sees 3 people, 1 recognized face = 2 unrecognized."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 3, "oji")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 2  # 3 - 1

    def test_zero_person_count_ignored(self):
        """Cameras with 0 person count should be skipped."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 0, "unknown")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 0

    def test_unifi_cameras_skipped(self):
        """Non-Frigate cameras should be skipped (no face recognition)."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        bs_id = "binary_sensor.foyer_person_detected"
        cam_mgr.add_camera(bs_id, CAMERA_PLATFORM_UNIFI)
        hass.set_state(bs_id, "on")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 0

    def test_unavailable_face_sensor_counts_as_unknown(self):
        """Unavailable face sensor = treat all detected as unrecognized."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        self._setup_frigate_camera(hass, cam_mgr, "playroom", 2, "unavailable")
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 2

    def test_stale_face_recognition_treated_as_unknown(self):
        """Face recognized > 30 min ago should be treated as stale/unknown."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        # Face was recognized 45 minutes ago — stale
        self._setup_frigate_camera(
            hass, cam_mgr, "playroom", 1, "oji", face_age_minutes=45
        )
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 1  # stale = unrecognized

    def test_fresh_face_recognition_subtracts(self):
        """Face recognized < 30 min ago should subtract from unrecognized."""
        hass = _make_hass_with_entry()
        cam_mgr = StubCameraManager()
        # Face recognized 5 minutes ago — fresh
        self._setup_frigate_camera(
            hass, cam_mgr, "playroom", 1, "oji", face_age_minutes=5
        )
        census = StubPersonCensusV2(hass, cam_mgr)
        assert census._get_unrecognized_camera_count() == 0  # recognized = not guest


# ============================================================================
# WIFI GUEST COUNT TESTS
# ============================================================================

class TestWiFiGuestCount:
    """Tests for _get_wifi_guest_count — guest VLAN phone detection."""

    def _add_device_tracker(self, hass, entity_id, state="home",
                             source_type="router", essid="", oui="",
                             is_guest=False, host_name="",
                             last_changed=None):
        """Helper to add a device_tracker entity to hass mock."""
        attrs = {
            "source_type": source_type,
            "essid": essid,
            "oui": oui,
            "is_guest": is_guest,
            "host_name": host_name,
        }
        if last_changed is not None:
            hass.set_state_with_time(entity_id, state, attrs, last_changed)
        else:
            hass.set_state(entity_id, state, attrs)

    def _setup_async_all(self, hass, entities):
        """Set up hass.states.async_all to return MockState objects."""
        def async_all(domain=None):
            return [hass._states[eid] for eid in entities if eid in hass._states]
        hass.states.async_all = async_all

    def test_no_devices_returns_zero(self):
        """No device trackers = 0 guests."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        hass.states.async_all = lambda domain: []
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_guest_phone_on_vlan_counted(self):
        """Phone on guest VLAN with matching hostname = counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.guest_iphone", "home",
            essid="Revel", oui="", host_name="iPhone",
        )
        self._setup_async_all(hass, ["device_tracker.guest_iphone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_non_phone_hostname_excluded(self):
        """IoT device (non-phone hostname) on guest VLAN = not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.smart_plug", "home",
            essid="Revel", oui="TP-LINK Technologies",
        )
        self._setup_async_all(hass, ["device_tracker.smart_plug"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_wrong_ssid_excluded(self):
        """Phone on main SSID (not guest) = not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.family_phone", "home",
            essid="MainNetwork", oui="", host_name="iPhone",
        )
        self._setup_async_all(hass, ["device_tracker.family_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_not_home_excluded(self):
        """Device not in 'home' state = not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.guest_phone", "not_home",
            essid="Revel", oui="", host_name="iPhone",
        )
        self._setup_async_all(hass, ["device_tracker.guest_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_non_router_source_excluded(self):
        """Device with non-router source_type = not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.ble_phone", "home",
            source_type="bluetooth", essid="Revel", oui="Apple, Inc.",
        )
        self._setup_async_all(hass, ["device_tracker.ble_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_multiple_guest_phones(self):
        """Multiple phones on guest VLAN = counted correctly."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.guest1", "home",
            essid="Revel", host_name="iPhone",
        )
        self._add_device_tracker(
            hass, "device_tracker.guest2", "home",
            essid="Revel", host_name="Galaxy-S24",
        )
        self._add_device_tracker(
            hass, "device_tracker.guest3", "home",
            essid="Revel", host_name="Pixel-9",
        )
        self._setup_async_all(hass, [
            "device_tracker.guest1",
            "device_tracker.guest2",
            "device_tracker.guest3",
        ])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 3

    def test_is_guest_fallback_when_no_ssid_configured(self):
        """Without configured SSID, use UniFi is_guest attribute."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: ""})
        self._add_device_tracker(
            hass, "device_tracker.guest_phone", "home",
            essid="SomeNetwork", host_name="iPhone", is_guest=True,
        )
        self._setup_async_all(hass, ["device_tracker.guest_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_is_guest_false_not_counted(self):
        """is_guest=False without configured SSID = not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: ""})
        self._add_device_tracker(
            hass, "device_tracker.family_phone", "home",
            essid="MainNetwork", oui="Apple, Inc.", is_guest=False,
        )
        self._setup_async_all(hass, ["device_tracker.family_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_mixed_guest_and_family(self):
        """Mix of guest and family devices — only guest phones counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.guest1", "home",
            essid="Revel", host_name="iPhone",
        )
        self._add_device_tracker(
            hass, "device_tracker.family1", "home",
            essid="MainWiFi", host_name="iPhone",
        )
        self._add_device_tracker(
            hass, "device_tracker.iot_device", "home",
            essid="Revel", host_name="ESP-12F",
        )
        self._setup_async_all(hass, [
            "device_tracker.guest1",
            "device_tracker.family1",
            "device_tracker.iot_device",
        ])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_hostname_fallback_iphone(self):
        """iPhone with empty OUI (randomized MAC) detected via hostname."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.iphone_14", "home",
            essid="Revel", oui="", host_name="iPhone",
        )
        self._setup_async_all(hass, ["device_tracker.iphone_14"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_hostname_fallback_galaxy(self):
        """Galaxy phone with empty OUI detected via hostname."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.galaxy_s24", "home",
            essid="Revel", oui="", host_name="Galaxy-S24",
        )
        self._setup_async_all(hass, ["device_tracker.galaxy_s24"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_hostname_fallback_pixel(self):
        """Pixel phone with empty OUI detected via hostname."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.pixel_9", "home",
            essid="Revel", oui="", host_name="Pixel-9-Pro",
        )
        self._setup_async_all(hass, ["device_tracker.pixel_9"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_hostname_no_match_iot(self):
        """IoT device with non-phone hostname not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.smart_plug", "home",
            essid="Revel", oui="", host_name="ESP-12F",
        )
        self._setup_async_all(hass, ["device_tracker.smart_plug"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_hostname_empty_not_counted(self):
        """Device with empty hostname and empty OUI not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.unknown_device", "home",
            essid="Revel", oui="", host_name="",
        )
        self._setup_async_all(hass, ["device_tracker.unknown_device"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_two_iphones_randomized_mac(self):
        """Two guest iPhones with randomized MACs both detected."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.iphone_14", "home",
            essid="Revel", oui="", host_name="iPhone",
        )
        self._add_device_tracker(
            hass, "device_tracker.iphone_5", "home",
            essid="Revel", oui="", host_name="iPhone",
        )
        self._setup_async_all(hass, [
            "device_tracker.iphone_14",
            "device_tracker.iphone_5",
        ])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 2

    def test_samsung_tv_excluded_by_hostname(self):
        """Samsung TV hostname doesn't match phone prefixes — not counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.samsung_tv", "home",
            essid="Revel", oui="Samsung Electronics Co.,Ltd",
            host_name="Samsung",
        )
        self._setup_async_all(hass, ["device_tracker.samsung_tv"])
        census = StubPersonCensusV2(hass)
        # Samsung OUI is NOT in PHONE_ONLY_MANUFACTURERS
        # hostname "Samsung" doesn't match any PHONE_HOSTNAME_PREFIXES
        assert census._get_wifi_guest_count() == 0

    def test_samsung_galaxy_phone_detected_by_hostname(self):
        """Samsung Galaxy phone (randomized MAC) detected via hostname."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.guest_galaxy", "home",
            essid="Revel", oui="", host_name="Galaxy-S24",
        )
        self._setup_async_all(hass, ["device_tracker.guest_galaxy"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_ipad_not_counted(self):
        """iPad on guest VLAN should NOT be counted (tablets excluded)."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.family_ipad", "home",
            essid="Revel", oui="", host_name="iPad",
        )
        self._setup_async_all(hass, ["device_tracker.family_ipad"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_homepod_not_counted(self):
        """HomePod on guest VLAN should NOT be counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.homepod", "home",
            essid="Revel", oui="Apple, Inc.", host_name="HomePod-Mini",
        )
        self._setup_async_all(hass, ["device_tracker.homepod"])
        census = StubPersonCensusV2(hass)
        # "HomePod-Mini" doesn't start with any PHONE_HOSTNAME_PREFIXES
        assert census._get_wifi_guest_count() == 0

    # --- Person exclusion tests ---

    def test_family_phone_excluded_by_person_entity(self):
        """Family member's phone (tracked person) should NOT be counted."""
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji_udezue"],
        })
        # Set up person entity with associated device_trackers
        hass.set_state("person.oji_udezue", "home", {
            "device_trackers": ["device_tracker.ojis_iphone"],
            "source": "device_tracker.ojis_iphone",
        })
        # Family phone on Revel
        self._add_device_tracker(
            hass, "device_tracker.ojis_iphone", "home",
            essid="Revel", host_name="iPhone",
        )
        # Guest phone on Revel
        self._add_device_tracker(
            hass, "device_tracker.guest_iphone", "home",
            essid="Revel", host_name="iPhone",
        )
        self._setup_async_all(hass, [
            "device_tracker.ojis_iphone",
            "device_tracker.guest_iphone",
        ])
        census = StubPersonCensusV2(hass)
        # Only guest phone should be counted, family excluded
        assert census._get_wifi_guest_count() == 1

    def test_multiple_family_phones_excluded(self):
        """All family members' phones excluded, only guests counted."""
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji_udezue", "person.ezinne"],
        })
        hass.set_state("person.oji_udezue", "home", {
            "device_trackers": ["device_tracker.ojis_iphone"],
            "source": "device_tracker.ojis_iphone",
        })
        hass.set_state("person.ezinne", "home", {
            "device_trackers": ["device_tracker.ezinnes_iphone"],
            "source": "device_tracker.ezinnes_iphone",
        })
        self._add_device_tracker(
            hass, "device_tracker.ojis_iphone", "home",
            essid="Revel", host_name="iPhone",
        )
        self._add_device_tracker(
            hass, "device_tracker.ezinnes_iphone", "home",
            essid="Revel", host_name="iPhone",
        )
        self._add_device_tracker(
            hass, "device_tracker.guest_iphone", "home",
            essid="Revel", host_name="iPhone",
        )
        self._setup_async_all(hass, [
            "device_tracker.ojis_iphone",
            "device_tracker.ezinnes_iphone",
            "device_tracker.guest_iphone",
        ])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_person_source_attribute_used_for_exclusion(self):
        """Person's 'source' attribute should also exclude family trackers."""
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji_udezue"],
        })
        # Person entity with source but no device_trackers attribute
        hass.set_state("person.oji_udezue", "home", {
            "source": "device_tracker.ojis_iphone",
        })
        self._add_device_tracker(
            hass, "device_tracker.ojis_iphone", "home",
            essid="Revel", host_name="iPhone",
        )
        self._setup_async_all(hass, ["device_tracker.ojis_iphone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    # --- Recency filter tests ---

    def test_old_phone_excluded_by_recency(self):
        """Phone on Revel for >24 hours should NOT be counted (resident)."""
        now = datetime.now()
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        # Phone connected 48 hours ago
        self._add_device_tracker(
            hass, "device_tracker.old_phone", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=48),
        )
        self._setup_async_all(hass, ["device_tracker.old_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count(now) == 0

    def test_recent_phone_counted(self):
        """Phone on Revel for <24 hours SHOULD be counted (guest)."""
        now = datetime.now()
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        # Phone connected 2 hours ago
        self._add_device_tracker(
            hass, "device_tracker.new_phone", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=2),
        )
        self._setup_async_all(hass, ["device_tracker.new_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count(now) == 1

    def test_recency_boundary_exactly_24h(self):
        """Phone at exactly 24 hours should NOT be counted (> threshold)."""
        now = datetime.now()
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        # Phone connected exactly 24h + 1 second ago
        self._add_device_tracker(
            hass, "device_tracker.boundary_phone", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=24, seconds=1),
        )
        self._setup_async_all(hass, ["device_tracker.boundary_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count(now) == 0

    def test_recency_boundary_just_under_24h(self):
        """Phone just under 24 hours should be counted."""
        now = datetime.now()
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.recent_phone", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=23, minutes=59),
        )
        self._setup_async_all(hass, ["device_tracker.recent_phone"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count(now) == 1

    # --- Shared entertainment network scenario ---

    def test_shared_network_full_scenario(self):
        """Full Revel scenario: TVs, HomePods, family phones, guest phones."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji_udezue", "person.ezinne"],
        })
        # Set up person entities
        hass.set_state("person.oji_udezue", "home", {
            "device_trackers": ["device_tracker.ojis_iphone"],
            "source": "device_tracker.ojis_iphone",
        })
        hass.set_state("person.ezinne", "home", {
            "device_trackers": ["device_tracker.ezinnes_iphone"],
            "source": "device_tracker.ezinnes_iphone",
        })

        all_entities = []

        # Samsung TVs (hostname "Samsung" doesn't match phone prefixes)
        for i in range(4):
            eid = f"device_tracker.samsung_tv_{i}"
            self._add_device_tracker(
                hass, eid, "home", essid="Revel", host_name="Samsung",
                last_changed=now - timedelta(days=30),
            )
            all_entities.append(eid)

        # HomePods (hostname "HomePod-*" doesn't match phone prefixes)
        for name in ["HomePod-Mini", "HomePod-Max"]:
            eid = f"device_tracker.{name.lower().replace('-', '_')}"
            self._add_device_tracker(
                hass, eid, "home", essid="Revel", host_name=name,
                last_changed=now - timedelta(days=30),
            )
            all_entities.append(eid)

        # WiiM (hostname "WiiM*" doesn't match phone prefixes)
        self._add_device_tracker(
            hass, "device_tracker.wiim_sub", "home",
            essid="Revel", host_name="WiiM Sub Pro-4D04",
            last_changed=now - timedelta(days=30),
        )
        all_entities.append("device_tracker.wiim_sub")

        # iPads (hostname "iPad" doesn't match phone prefixes)
        for i in range(3):
            eid = f"device_tracker.ipad_{i}"
            self._add_device_tracker(
                hass, eid, "home", essid="Revel", host_name="iPad",
                last_changed=now - timedelta(days=30),
            )
            all_entities.append(eid)

        # Family iPhones (excluded by person association)
        self._add_device_tracker(
            hass, "device_tracker.ojis_iphone", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=1),
        )
        all_entities.append("device_tracker.ojis_iphone")

        self._add_device_tracker(
            hass, "device_tracker.ezinnes_iphone", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=2),
        )
        all_entities.append("device_tracker.ezinnes_iphone")

        # Guest iPhones (recently joined, not family)
        self._add_device_tracker(
            hass, "device_tracker.iphone_14", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=1),
        )
        all_entities.append("device_tracker.iphone_14")

        self._add_device_tracker(
            hass, "device_tracker.iphone_5", "home",
            essid="Revel", host_name="iPhone",
            last_changed=now - timedelta(hours=1),
        )
        all_entities.append("device_tracker.iphone_5")

        self._setup_async_all(hass, all_entities)
        census = StubPersonCensusV2(hass)
        # Only the 2 guest iPhones should be counted
        assert census._get_wifi_guest_count(now) == 2

    def test_tv_not_counted_even_if_wakes(self):
        """TV that sleeps/wakes should not be counted (hostname filter)."""
        now = datetime.now()
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        # TV just woke up (recent last_changed) but hostname doesn't match
        self._add_device_tracker(
            hass, "device_tracker.samsung_tv", "home",
            essid="Revel", host_name="Samsung",
            last_changed=now - timedelta(minutes=5),
        )
        self._setup_async_all(hass, ["device_tracker.samsung_tv"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count(now) == 0

    def test_hostname_case_insensitive(self):
        """Hostname matching should be case-insensitive."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.guest1", "home",
            essid="Revel", host_name="IPHONE",
        )
        self._add_device_tracker(
            hass, "device_tracker.guest2", "home",
            essid="Revel", host_name="IPhone",
        )
        self._setup_async_all(hass, [
            "device_tracker.guest1",
            "device_tracker.guest2",
        ])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 2

    # --- Custom hostname / exclusion-based tests ---

    def test_custom_named_phone_counted(self):
        """Guest phone with custom hostname (e.g., 'Uche-s-S22') is counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.uche_s_s22", "home",
            essid="Revel", host_name="Uche-s-S22",
        )
        self._setup_async_all(hass, ["device_tracker.uche_s_s22"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_oneplus_phone_counted(self):
        """OnePlus phone with standard hostname is counted."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.oneplus_nord", "home",
            essid="Revel", host_name="OnePlus-Nord-N30-5G",
        )
        self._setup_async_all(hass, ["device_tracker.oneplus_nord"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 1

    def test_infrastructure_urc_remote_excluded(self):
        """URC remote (TRC-1480) excluded by infrastructure filter."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.urc_remote", "home",
            essid="Revel", host_name="TRC-1480",
        )
        self._setup_async_all(hass, ["device_tracker.urc_remote"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_infrastructure_envoy_excluded(self):
        """Enphase envoy excluded by infrastructure filter."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.envoy", "home",
            essid="Revel", host_name="envoywifi",
        )
        self._setup_async_all(hass, ["device_tracker.envoy"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_infrastructure_camera_excluded(self):
        """Amcrest camera excluded by infrastructure filter."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.camera", "home",
            essid="Revel", host_name="ArmCrestASH41Wifi",
        )
        self._setup_async_all(hass, ["device_tracker.camera"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_infrastructure_g3_camera_excluded(self):
        """Ubiquiti G3 camera excluded by infrastructure filter."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        self._add_device_tracker(
            hass, "device_tracker.g3_cam", "home",
            essid="Revel", host_name="g3-instant-study-a",
        )
        self._setup_async_all(hass, ["device_tracker.g3_cam"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_real_revel_network_scenario(self):
        """Real Revel network: 2 Android guest phones among 27 devices."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji_udezue", "person.ezinne"],
        })
        hass.set_state("person.oji_udezue", "home", {
            "device_trackers": ["device_tracker.phalanxiphone15promax"],
            "source": "device_tracker.phalanxiphone15promax",
        })
        hass.set_state("person.ezinne", "home", {
            "device_trackers": ["device_tracker.ezinne_iphone"],
            "source": "device_tracker.ezinne_iphone",
        })

        all_entities = []

        def add(eid, hn, age_days=30):
            self._add_device_tracker(
                hass, eid, "home", essid="Revel", host_name=hn,
                last_changed=now - timedelta(days=age_days),
            )
            all_entities.append(eid)

        # Infrastructure (always present)
        for i in range(5):
            add(f"device_tracker.samsung_{i}", "Samsung")
        add("device_tracker.homepod_mini", "HomePod-Mini")
        add("device_tracker.homepod_max", "HomePod-Max")
        add("device_tracker.wiim", "WiiM Sub Pro-4D04")
        for i in range(3):
            add(f"device_tracker.urc_{i}", "TRC-1480")
        add("device_tracker.camera", "ArmCrestASH41Wifi")
        add("device_tracker.envoy", "envoywifi")
        add("device_tracker.g3_cam", "g3-instant-study-a")
        add("device_tracker.esp1", "espressif")
        add("device_tracker.esp2", "espressif")

        # Family iPads (always present, excluded as tablets)
        for i in range(3):
            add(f"device_tracker.ipad_{i}", "iPad")

        # Family iPhones (old, excluded by recency)
        add("device_tracker.iphone_5", "iPhone")
        add("device_tracker.iphone_14", "iPhone")
        add("device_tracker.unifi_9c_b8", "iPhone")

        # Guest phones (recently arrived)
        self._add_device_tracker(
            hass, "device_tracker.uche_s_s22", "home",
            essid="Revel", host_name="Uche-s-S22",
            last_changed=now - timedelta(hours=3),
        )
        all_entities.append("device_tracker.uche_s_s22")

        self._add_device_tracker(
            hass, "device_tracker.oneplus_nord", "home",
            essid="Revel", host_name="OnePlus-Nord-N30-5G",
            last_changed=now - timedelta(hours=3),
        )
        all_entities.append("device_tracker.oneplus_nord")

        self._setup_async_all(hass, all_entities)
        census = StubPersonCensusV2(hass)
        # Only the 2 guest Android phones should be counted
        assert census._get_wifi_guest_count(now) == 2

    def test_device_registry_sibling_excludes_unifi_tracker(self):
        """Regression: UniFi tracker for family phone excluded via device registry.

        A family member's phone creates two device_trackers:
        - device_tracker.ezinne_iphone (Companion App, linked to person)
        - device_tracker.unifi_default_9c_b8_b4 (UniFi, NOT linked to person)
        Layer 1 (device registry expansion) should discover the sibling
        and exclude it from the guest count.
        """
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.ezinne"],
        })
        # Person entity with Companion App tracker
        hass.set_state("person.ezinne", "home", {
            "device_trackers": ["device_tracker.ezinne_iphone"],
            "source": "device_tracker.ezinne_iphone",
        })
        # UniFi tracker for same phone — on guest SSID, looks like a guest
        self._add_device_tracker(
            hass, "device_tracker.unifi_default_9c_b8_b4", "home",
            essid="Revel", host_name="iPhone",
        )
        self._setup_async_all(hass, ["device_tracker.unifi_default_9c_b8_b4"])
        census = StubPersonCensusV2(hass)
        # Without device registry: would count as 1 guest
        assert census._get_wifi_guest_count() == 1

        # WITH device registry sibling mapping: excluded
        census._device_registry_siblings = {
            "device_tracker.ezinne_iphone": [
                "device_tracker.unifi_default_9c_b8_b4",
            ],
        }
        assert census._get_wifi_guest_count() == 0

    def test_mac_cross_reference_excludes_family_phone(self):
        """Regression: Family phone excluded by MAC match even without
        device registry merge (e.g., different HA devices).

        Layer 2 collects MACs from family trackers and matches against
        WiFi candidate devices.
        """
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.ezinne"],
        })
        # Person entity with Companion App tracker
        hass.set_state("person.ezinne", "home", {
            "device_trackers": ["device_tracker.ezinne_iphone"],
            "source": "device_tracker.ezinne_iphone",
        })
        # Companion App tracker has MAC
        hass.set_state("device_tracker.ezinne_iphone", "home", {
            "source_type": "gps",
            "mac": "9C:B8:B4:9C:1C:52",
        })
        # UniFi tracker for same phone — same MAC, different entity_id
        self._add_device_tracker(
            hass, "device_tracker.unifi_default_9c_b8_b4", "home",
            essid="Revel", host_name="iPhone",
        )
        # Add MAC to UniFi tracker attributes
        hass._states["device_tracker.unifi_default_9c_b8_b4"].attributes["mac"] = "9c:b8:b4:9c:1c:52"
        self._setup_async_all(hass, ["device_tracker.unifi_default_9c_b8_b4"])
        census = StubPersonCensusV2(hass)
        # MAC match: family tracker has 9C:B8:B4:9C:1C:52, WiFi device has same → excluded
        assert census._get_wifi_guest_count() == 0

    def test_mac_case_insensitive(self):
        """MAC matching is case-insensitive."""
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji"],
        })
        hass.set_state("person.oji", "home", {
            "device_trackers": ["device_tracker.oji_phone"],
            "source": "device_tracker.oji_phone",
        })
        hass.set_state("device_tracker.oji_phone", "home", {
            "source_type": "gps",
            "mac": "AA:BB:CC:DD:EE:FF",
        })
        self._add_device_tracker(
            hass, "device_tracker.unifi_oji", "home",
            essid="Revel", host_name="iPhone",
        )
        hass._states["device_tracker.unifi_oji"].attributes["mac"] = "aa:bb:cc:dd:ee:ff"
        self._setup_async_all(hass, ["device_tracker.unifi_oji"])
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_actual_guest_not_excluded_by_mac(self):
        """Real guest devices are NOT excluded by MAC matching."""
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.ezinne"],
        })
        hass.set_state("person.ezinne", "home", {
            "device_trackers": ["device_tracker.ezinne_iphone"],
            "source": "device_tracker.ezinne_iphone",
        })
        hass.set_state("device_tracker.ezinne_iphone", "home", {
            "source_type": "gps",
            "mac": "AA:BB:CC:11:22:33",
        })
        # Guest phone with DIFFERENT MAC
        self._add_device_tracker(
            hass, "device_tracker.guest_phone", "home",
            essid="Revel", host_name="Galaxy-S24",
        )
        hass._states["device_tracker.guest_phone"].attributes["mac"] = "ff:ee:dd:cc:bb:aa"
        self._setup_async_all(hass, ["device_tracker.guest_phone"])
        census = StubPersonCensusV2(hass)
        # Different MAC → still counted as guest
        assert census._get_wifi_guest_count() == 1


# ============================================================================
# FACE RECOGNIZED PERSON NAMES TESTS
# ============================================================================

class TestFaceRecognizedPersonNames:
    """Tests for _get_face_recognized_person_names — Frigate last_camera."""

    def test_recently_seen_persons(self):
        """Persons with recently updated last_camera = recognized."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            "tracked_persons": ["person.oji_udezue", "person.ezinne"],
        })
        hass.set_state_with_time(
            "sensor.frigate_oji_udezue_last_camera",
            "playroom",
            last_changed=now - timedelta(minutes=5),
        )
        hass.set_state_with_time(
            "sensor.frigate_ezinne_last_camera",
            "family_room",
            last_changed=now - timedelta(minutes=10),
        )
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(now)
        assert sorted(result) == ["ezinne", "oji_udezue"]

    def test_stale_recognition_excluded(self):
        """Persons with old last_camera (>30 min) = not recognized."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            "tracked_persons": ["person.oji_udezue"],
        })
        hass.set_state_with_time(
            "sensor.frigate_oji_udezue_last_camera",
            "playroom",
            last_changed=now - timedelta(minutes=45),
        )
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(now)
        assert result == []

    def test_unknown_camera_excluded(self):
        """Person with 'Unknown' last_camera = not recognized."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            "tracked_persons": ["person.oji_udezue"],
        })
        hass.set_state_with_time(
            "sensor.frigate_oji_udezue_last_camera",
            "Unknown",
            last_changed=now - timedelta(minutes=2),
        )
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(now)
        assert result == []

    def test_no_sensor_exists(self):
        """Person with no last_camera sensor = not recognized."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            "tracked_persons": ["person.unknown_person"],
        })
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(now)
        assert result == []

    def test_person_name_slug_conversion(self):
        """Person entity IDs are properly converted to Frigate sensor slugs."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            "tracked_persons": ["person.jaya"],
        })
        hass.set_state_with_time(
            "sensor.frigate_jaya_last_camera",
            "staircase",
            last_changed=now - timedelta(minutes=1),
        )
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(now)
        assert result == ["jaya"]

    def test_boundary_at_window_edge(self):
        """Person at exactly 30 min should still be recognized (<=)."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            "tracked_persons": ["person.oji_udezue"],
        })
        hass.set_state_with_time(
            "sensor.frigate_oji_udezue_last_camera",
            "foyer",
            last_changed=now - timedelta(seconds=CENSUS_FACE_RECOGNITION_WINDOW_SECONDS),
        )
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(now)
        assert result == ["oji_udezue"]


# ============================================================================
# ENHANCED HOUSE CENSUS TESTS
# ============================================================================

class TestEnhancedHouseCensus:
    """Tests for _apply_enhanced_house_census — the full v2 pipeline."""

    def test_guests_via_camera_only(self):
        """Unrecognized camera persons should set unidentified count."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        hass.states.async_all = lambda domain: []
        cam_mgr = StubCameraManager()
        # 1 camera sees 2 people, face unknown
        bs_id = "binary_sensor.playroom_person_occupancy"
        count_id = "sensor.playroom_person_count"
        cam_mgr.add_camera(bs_id, CAMERA_PLATFORM_FRIGATE, count_id)
        hass.set_state(count_id, "2")
        hass.set_state("sensor.playroom_last_recognized_face", "unknown")

        census = StubPersonCensusV2(hass, cam_mgr)
        raw = _make_raw_house_result()
        now = datetime.now()
        result = census._apply_enhanced_house_census(raw, ["oji", "ezinne", "jaya"], now)

        assert result.camera_unrecognized == 2
        assert result.wifi_guest_floor == 0
        assert result.unidentified_count == 2  # camera_unrecognized
        assert result.identified_count == 3  # BLE persons
        assert result.total_persons == 5
        assert result.enhanced_census is True

    def test_guests_via_wifi_only(self):
        """WiFi-only guests no longer raise unidentified (WiFi disabled)."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        # 2 guest phones on WiFi
        for i in range(2):
            eid = f"device_tracker.guest{i}"
            hass.set_state(eid, "home", {
                "source_type": "router",
                "essid": "Revel",
                "host_name": "iPhone",
            })
        hass.states.async_all = lambda domain: [
            hass._states[f"device_tracker.guest{i}"] for i in range(2)
        ]

        census = StubPersonCensusV2(hass)  # no cameras
        raw = _make_raw_house_result()
        now = datetime.now()
        result = census._apply_enhanced_house_census(raw, ["oji", "ezinne", "jaya"], now)

        assert result.wifi_guest_floor == 2  # still counted for diagnostics
        assert result.camera_unrecognized == 0
        assert result.unidentified_count == 0  # camera-only: 0
        assert result.total_persons == 3

    def test_wifi_does_not_inflate_unidentified(self):
        """WiFi guests no longer raise unidentified above camera count."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})

        # Camera sees 1 unrecognized
        cam_mgr = StubCameraManager()
        bs_id = "binary_sensor.playroom_person_occupancy"
        count_id = "sensor.playroom_person_count"
        cam_mgr.add_camera(bs_id, CAMERA_PLATFORM_FRIGATE, count_id)
        hass.set_state(count_id, "1")
        hass.set_state("sensor.playroom_last_recognized_face", "unknown")

        # WiFi sees 3 guests
        for i in range(3):
            eid = f"device_tracker.guest{i}"
            hass.set_state(eid, "home", {
                "source_type": "router",
                "essid": "Revel",
                "host_name": "iPhone",
            })
        hass.states.async_all = lambda domain: [
            hass._states[f"device_tracker.guest{i}"] for i in range(3)
        ]

        census = StubPersonCensusV2(hass, cam_mgr)
        raw = _make_raw_house_result()
        now = datetime.now()
        result = census._apply_enhanced_house_census(raw, ["oji", "ezinne", "jaya"], now)

        assert result.camera_unrecognized == 1
        assert result.wifi_guest_floor == 3  # still tracked for diagnostics
        assert result.unidentified_count == 1  # camera-only

    def test_face_recognized_union_with_ble(self):
        """Face recognized persons should merge with BLE persons."""
        now = datetime.now()
        hass = _make_hass_with_entry({
            CONF_GUEST_VLAN_SSID: "Revel",
            "tracked_persons": ["person.oji_udezue", "person.ziri"],
        })
        hass.states.async_all = lambda domain: []

        # Face: oji seen on playroom 5 min ago, ziri on family_room
        hass.set_state_with_time(
            "sensor.frigate_oji_udezue_last_camera", "playroom",
            last_changed=now - timedelta(minutes=5),
        )
        hass.set_state_with_time(
            "sensor.frigate_ziri_last_camera", "family_room",
            last_changed=now - timedelta(minutes=3),
        )

        census = StubPersonCensusV2(hass)
        raw = _make_raw_house_result()
        # BLE uses person_id slugs too: "oji_udezue", "ezinne"
        result = census._apply_enhanced_house_census(raw, ["oji_udezue", "ezinne"], now)

        # Union: {oji_udezue, ezinne} | {oji_udezue, ziri}
        # oji_udezue deduplicates (same format from BLE and face recognition)
        assert result.identified_count == 3  # oji_udezue, ezinne, ziri
        assert result.face_recognized_persons == ["oji_udezue", "ziri"]

    def test_no_guests_no_wifi(self):
        """Zero guests everywhere = unidentified 0."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        hass.states.async_all = lambda domain: []
        census = StubPersonCensusV2(hass)
        raw = _make_raw_house_result()
        now = datetime.now()
        result = census._apply_enhanced_house_census(raw, ["oji", "ezinne", "jaya"], now)
        assert result.unidentified_count == 0
        assert result.total_persons == 3

    def test_hold_applied_to_unidentified(self):
        """Hold should be applied to the unidentified count."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        cam_mgr = StubCameraManager()
        bs_id = "binary_sensor.playroom_person_occupancy"
        count_id = "sensor.playroom_person_count"
        cam_mgr.add_camera(bs_id, CAMERA_PLATFORM_FRIGATE, count_id)
        hass.states.async_all = lambda domain: []

        census = StubPersonCensusV2(hass, cam_mgr)
        raw = _make_raw_house_result()
        t0 = datetime.now()

        # First: camera sees 3 unrecognized
        hass.set_state(count_id, "3")
        hass.set_state("sensor.playroom_last_recognized_face", "unknown")
        r1 = census._apply_enhanced_house_census(raw, ["oji"], t0)
        assert r1.unidentified_count == 3

        # 5 min later: camera sees 0 (people left camera view)
        hass.set_state(count_id, "0")
        t1 = t0 + timedelta(minutes=5)
        r2 = census._apply_enhanced_house_census(raw, ["oji"], t1)
        assert r2.unidentified_count == 3  # held
        assert r2.peak_held is True
        assert r2.peak_age_minutes == 5


# ============================================================================
# ENHANCED PROPERTY CENSUS TESTS
# ============================================================================

class TestEnhancedPropertyCensus:
    """Tests for _apply_enhanced_property_census."""

    def test_property_hold_applied(self):
        """Property should hold peak during hold window."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()

        raw1 = _make_raw_property_result(total=3)
        r1 = census._apply_enhanced_property_census(raw1, t0)
        assert r1.total_persons == 3

        # 3 min later: count drops to 0
        raw2 = _make_raw_property_result(total=0)
        t1 = t0 + timedelta(minutes=3)
        r2 = census._apply_enhanced_property_census(raw2, t1)
        assert r2.total_persons == 3  # held
        assert r2.peak_held is True
        assert r2.enhanced_census is True

    def test_property_drops_after_hold(self):
        """Property should drop instantly after hold expires."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()

        raw1 = _make_raw_property_result(total=3)
        census._apply_enhanced_property_census(raw1, t0)

        # 6 min later (hold expired)
        raw2 = _make_raw_property_result(total=0)
        t1 = t0 + timedelta(minutes=6)
        r2 = census._apply_enhanced_property_census(raw2, t1)
        assert r2.total_persons == 0
        assert r2.peak_held is False

    def test_property_no_change_passthrough(self):
        """If count doesn't change and no peak hold, return raw result."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        now = datetime.now()
        raw = _make_raw_property_result(total=2)
        result = census._apply_enhanced_property_census(raw, now)
        # First call: sets peak, no hold, returns raw
        assert result.total_persons == 2
        assert result.enhanced_census is False  # passthrough (no change)


# ============================================================================
# CONFIG TOGGLE TESTS
# ============================================================================

class TestEnhancedCensusConfig:
    """Tests for _is_enhanced_census_enabled config toggle."""

    def test_enabled_by_default(self):
        """Enhanced census should be enabled by default."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        assert census._is_enhanced_census_enabled() is True

    def test_explicitly_enabled(self):
        """Explicitly set to True."""
        hass = _make_hass_with_entry({CONF_ENHANCED_CENSUS: True})
        census = StubPersonCensusV2(hass)
        assert census._is_enhanced_census_enabled() is True

    def test_explicitly_disabled(self):
        """Explicitly set to False."""
        hass = _make_hass_with_entry({CONF_ENHANCED_CENSUS: False})
        census = StubPersonCensusV2(hass)
        assert census._is_enhanced_census_enabled() is False

    def test_no_integration_entry(self):
        """When no integration entry exists, defaults to True."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain: []
        census = StubPersonCensusV2(hass)
        assert census._is_enhanced_census_enabled() is True

    def test_reads_from_options_not_data(self):
        """Config should be read from merged data+options (options win)."""
        hass = MockHass()
        entry = MockConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION, CONF_ENHANCED_CENSUS: True},
            options={CONF_ENHANCED_CENSUS: False},
        )
        hass.config_entries.async_entries = lambda domain: [entry]
        census = StubPersonCensusV2(hass)
        # Options override data
        assert census._is_enhanced_census_enabled() is False


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestCensusV2EdgeCases:
    """Edge cases and boundary conditions."""

    def test_hold_decay_zero_count_initial(self):
        """Initial count of 0 should set peak to 0."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        count, held, age = census._apply_hold_decay(0, "house", datetime.now())
        assert count == 0
        assert held is False
        assert census._peak_house_camera_count == 0

    def test_empty_tracked_persons(self):
        """No tracked persons configured = empty face recognition."""
        hass = _make_hass_with_entry({"tracked_persons": []})
        census = StubPersonCensusV2(hass)
        result = census._get_face_recognized_person_names(datetime.now())
        assert result == []

    def test_wifi_guest_count_no_ssid_no_is_guest(self):
        """No SSID configured and no is_guest = 0 guests."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: ""})
        hass.set_state("device_tracker.phone", "home", {
            "source_type": "router",
            "essid": "MainNet",
            "oui": "Apple, Inc.",
            "is_guest": False,
        })
        hass.states.async_all = lambda domain: [hass._states["device_tracker.phone"]]
        census = StubPersonCensusV2(hass)
        assert census._get_wifi_guest_count() == 0

    def test_sensor_int_handles_bad_values(self):
        """_get_sensor_int should handle non-numeric state gracefully."""
        hass = _make_hass_with_entry()
        hass.set_state("sensor.test", "unavailable")
        census = StubPersonCensusV2(hass)
        assert census._get_sensor_int("sensor.test") == 0
        assert census._get_sensor_int("sensor.nonexistent") == 0

    def test_hold_decay_independent_per_zone(self):
        """House and property peaks should be tracked independently."""
        hass = _make_hass_with_entry()
        census = StubPersonCensusV2(hass)
        t0 = datetime.now()

        census._apply_hold_decay(5, "house", t0)
        census._apply_hold_decay(3, "property", t0)

        assert census._peak_house_camera_count == 5
        assert census._peak_property_count == 3

        t1 = t0 + timedelta(minutes=3)
        h_count, h_held, _ = census._apply_hold_decay(1, "house", t1)
        p_count, p_held, _ = census._apply_hold_decay(0, "property", t1)

        assert h_count == 5  # house held
        assert h_held is True
        assert p_count == 3  # property held
        assert p_held is True

    def test_enhanced_census_result_attributes(self):
        """Enhanced result should have all v2 attributes set."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        hass.states.async_all = lambda domain: []
        census = StubPersonCensusV2(hass)
        raw = _make_raw_house_result()
        now = datetime.now()
        result = census._apply_enhanced_house_census(raw, ["oji"], now)

        assert hasattr(result, "wifi_guest_floor")
        assert hasattr(result, "camera_unrecognized")
        assert hasattr(result, "peak_held")
        assert hasattr(result, "peak_age_minutes")
        assert hasattr(result, "face_recognized_persons")
        assert hasattr(result, "enhanced_census")
        assert result.enhanced_census is True

    def test_guest_returning_next_day(self):
        """Guest phone reconnecting to WiFi should be detected immediately."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        census = StubPersonCensusV2(hass)

        now = datetime.now()
        # Day 1: guest connects (recently)
        hass.set_state_with_time("device_tracker.guest_phone", "home", {
            "source_type": "router",
            "essid": "Revel",
            "host_name": "iPhone",
        }, last_changed=now)
        hass.states.async_all = lambda domain: [hass._states["device_tracker.guest_phone"]]
        assert census._get_wifi_guest_count(now) == 1

        # Guest disconnects (leaves or phone sleeps)
        hass.set_state_with_time("device_tracker.guest_phone", "not_home", {
            "source_type": "router",
            "essid": "Revel",
            "host_name": "iPhone",
        }, last_changed=now + timedelta(hours=6))
        assert census._get_wifi_guest_count(now + timedelta(hours=6)) == 0

        # Day 2: guest phone reconnects (recent last_changed)
        reconnect_time = now + timedelta(hours=20)
        hass.set_state_with_time("device_tracker.guest_phone", "home", {
            "source_type": "router",
            "essid": "Revel",
            "host_name": "iPhone",
        }, last_changed=reconnect_time)
        assert census._get_wifi_guest_count(reconnect_time) == 1

    def test_bedroom_guest_overnight(self):
        """Guest in bedroom (no cameras) — WiFi counted but not in unidentified."""
        hass = _make_hass_with_entry({CONF_GUEST_VLAN_SSID: "Revel"})
        cam_mgr = StubCameraManager()  # No cameras (simulating bedroom)

        t0 = datetime.now()
        # Guest phone stays on WiFi all night (arrived recently)
        hass.set_state_with_time("device_tracker.guest_phone", "home", {
            "source_type": "router",
            "essid": "Revel",
            "host_name": "iPhone",
        }, last_changed=t0)
        hass.states.async_all = lambda domain: [hass._states["device_tracker.guest_phone"]]

        census = StubPersonCensusV2(hass, cam_mgr)
        raw = _make_raw_house_result()

        # Check at midnight — WiFi counted but not in formula
        r1 = census._apply_enhanced_house_census(raw, ["oji", "ezinne"], t0)
        assert r1.wifi_guest_floor == 1
        assert r1.unidentified_count == 0  # camera-only: no cameras = 0

        # Check at 6am
        t1 = t0 + timedelta(hours=6)
        r2 = census._apply_enhanced_house_census(raw, ["oji", "ezinne"], t1)
        assert r2.wifi_guest_floor == 1
        assert r2.unidentified_count == 0  # camera-only
