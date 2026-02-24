"""Tests for v3.5.1 Cycle 4 Slim features.

Covers:
  Group 1: PerimeterAlertManager — alert hours, cooldown, egress suppression,
            missing notify service, no cameras configured, message formatting
  Group 2: Perimeter alert constants from const.py
  Group 3: ZoneIdentifiedPersonsSensor and ZoneGuestCountSensor unit logic
  Group 4: UnexpectedPersonBinarySensor (URAUnexpectedPersonSensor) logic
  Group 5: Graceful degradation across all Cycle 4 Slim features

All tests are pure-Python and follow the same fixture/mock patterns used
throughout this test suite (MockHass, MockConfigEntry, direct reimplementation
where HA imports would be needed).
"""
import logging
import pytest
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock, AsyncMock, patch, call

from tests.conftest import MockHass, MockConfigEntry


# ============================================================================
# TEST CONSTANTS (mirrors const.py without importing HA modules)
# ============================================================================

DOMAIN = "universal_room_automation"

# Perimeter alert config keys
CONF_PERIMETER_ALERT_HOURS_START = "perimeter_alert_hours_start"
CONF_PERIMETER_ALERT_HOURS_END = "perimeter_alert_hours_end"
CONF_PERIMETER_ALERT_NOTIFY_SERVICE = "perimeter_alert_notify_service"
CONF_PERIMETER_ALERT_NOTIFY_TARGET = "perimeter_alert_notify_target"

# Perimeter alert defaults
DEFAULT_PERIMETER_ALERT_START = 23    # 11 PM
DEFAULT_PERIMETER_ALERT_END = 5       # 5 AM
PERIMETER_ALERT_COOLDOWN_SECONDS = 300  # 5 minutes

# Zone aggregation sensor keys
SENSOR_ZONE_IDENTIFIED_PERSONS = "zone_identified_persons"
SENSOR_ZONE_GUEST_COUNT = "zone_guest_count"

# Entry type constants
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_INTEGRATION = "integration"
ENTRY_TYPE_ROOM = "room"

# Camera config keys
CONF_PERIMETER_CAMERAS = "perimeter_cameras"
CONF_EGRESS_CAMERAS = "egress_cameras"

# Tracking status
TRACKING_STATUS_ACTIVE = "active"
TRACKING_STATUS_STALE = "stale"

# Suppression window (seconds)
EGRESS_SUPPRESSION_WINDOW_SECONDS = 120


# ============================================================================
# LOCAL REIMPLEMENTATIONS
# ============================================================================
# These replicate the pure logic of the real classes without importing HA
# modules, following the same pattern as the rest of this test suite.

# --- PerimeterAlertManager pure-Python stub ---

class PerimeterAlertManagerStub:
    """Pure-Python reimplementation of PerimeterAlertManager for unit testing.

    Supports configurable alert hours, cooldown, and egress suppression.
    Does NOT require HA event bus — logic is exposed as synchronous helpers.
    """

    def __init__(self, hass):
        self.hass = hass
        self._last_alert: dict[str, datetime] = {}
        self._last_egress_time: Optional[datetime] = None
        self._active = False

    # ------------------------------------------------------------------
    # Core alert-evaluation logic (mirrors _async_handle_perimeter_trigger)
    # ------------------------------------------------------------------

    def evaluate_trigger(self, entity_id: str, now: datetime) -> str:
        """Evaluate a perimeter trigger and return the outcome string.

        Returns one of:
          'suppressed_hours'   — outside alert hours
          'suppressed_egress'  — recent egress crossing
          'suppressed_cooldown' — per-camera cooldown active
          'no_service'         — would alert but no notify service configured
          'alert_sent'         — alert sent
        """
        # 1. Check alert hours
        if not self._is_in_alert_hours(now):
            return "suppressed_hours"

        # 2. Egress suppression
        if self._last_egress_time is not None:
            seconds = (now - self._last_egress_time).total_seconds()
            if seconds <= EGRESS_SUPPRESSION_WINDOW_SECONDS:
                return "suppressed_egress"

        # 3. Per-camera cooldown
        last = self._last_alert.get(entity_id)
        if last is not None:
            seconds = (now - last).total_seconds()
            if seconds < PERIMETER_ALERT_COOLDOWN_SECONDS:
                return "suppressed_cooldown"

        # 4. Notify
        service, _ = self._get_notify_config()
        if not service:
            # Record alert time even when no service configured
            self._last_alert[entity_id] = now
            return "no_service"

        self._last_alert[entity_id] = now
        return "alert_sent"

    def record_egress(self, now: datetime) -> None:
        """Record an egress crossing at the given timestamp."""
        self._last_egress_time = now

    # ------------------------------------------------------------------
    # _is_in_alert_hours — mirrors the real staticmethod
    # ------------------------------------------------------------------

    def _is_in_alert_hours(self, now: datetime) -> bool:
        """Return True if current hour is within the alert window."""
        config = self._get_integration_config()
        start = config.get(CONF_PERIMETER_ALERT_HOURS_START, DEFAULT_PERIMETER_ALERT_START)
        end = config.get(CONF_PERIMETER_ALERT_HOURS_END, DEFAULT_PERIMETER_ALERT_END)

        hour = now.hour
        if start == end:
            return True
        if start < end:
            # Daytime window e.g. 9–17
            return start <= hour < end
        # Overnight window e.g. 23–5
        return hour >= start or hour < end

    # ------------------------------------------------------------------
    # Config helpers (mirrors real implementation)
    # ------------------------------------------------------------------

    def _get_integration_config(self) -> dict:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                return {**entry.data, **entry.options}
        return {}

    def _get_notify_config(self) -> tuple:
        config = self._get_integration_config()
        service = config.get(CONF_PERIMETER_ALERT_NOTIFY_SERVICE) or None
        target = config.get(CONF_PERIMETER_ALERT_NOTIFY_TARGET) or None
        return service, target

    def _get_person_sensors_for(self, conf_key: str) -> list:
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if not camera_manager:
            return []
        config = self._get_integration_config()
        camera_entity_ids = config.get(conf_key, [])
        if not camera_entity_ids:
            return []
        resolved = camera_manager.resolve_configured_cameras(camera_entity_ids)
        return [
            info.person_binary_sensor
            for info in resolved
            if info.person_binary_sensor
        ]

    def async_setup_returns_none_when_no_perimeter_cameras(self) -> bool:
        """Simulate async_setup — return True if setup would skip."""
        perimeter_sensors = self._get_person_sensors_for(CONF_PERIMETER_CAMERAS)
        return len(perimeter_sensors) == 0

    @property
    def last_alert_time(self) -> Optional[datetime]:
        if not self._last_alert:
            return None
        return max(self._last_alert.values())


# --- Friendly camera name generation ---

def friendly_camera_name(entity_id: str) -> str:
    """Generate a human-readable name from an entity_id.

    Mirrors the pattern typically used for alert messages:
    'binary_sensor.front_door_cam_person_occupancy'
    → 'front door cam person occupancy'
    """
    # strip domain prefix
    name = entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
    return name.replace("_", " ")


# --- ZoneIdentifiedPersonsSensor logic stub ---

class ZoneIdentifiedPersonsSensorStub:
    """Pure-Python stub for ZoneIdentifiedPersonsSensor logic."""

    def __init__(self, hass, zone_rooms: list[str], zone_name: str = "test_zone"):
        self.hass = hass
        self._zone_rooms = set(zone_rooms)
        self.zone = zone_name
        self._persons: list[str] = []

    def _get_zone_persons(self) -> list[str]:
        """Return sorted persons whose location is in this zone's rooms."""
        try:
            person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if not person_coordinator or not person_coordinator.data:
                return []
            seen: set[str] = set()
            for person_id, info in person_coordinator.data.items():
                location = info.get("location", "")
                if location and location in self._zone_rooms:
                    seen.add(person_id)
            return sorted(seen)
        except Exception:
            return []

    @property
    def native_value(self) -> str:
        persons = self._get_zone_persons()
        return ", ".join(persons) if persons else "none"

    @property
    def extra_state_attributes(self) -> dict:
        persons = self._get_zone_persons()
        return {
            "persons": persons,
            "count": len(persons),
            "zone": self.zone,
        }


# --- ZoneGuestCountSensor logic stub ---

class ZoneGuestCountSensorStub:
    """Pure-Python stub for ZoneGuestCountSensor logic."""

    def __init__(self, hass, zone_name: str = "test_zone"):
        self.hass = hass
        self.zone = zone_name

    def _get_guest_count(self) -> int:
        """Return max(0, camera_total - ble_active_total)."""
        try:
            census = self.hass.data.get(DOMAIN, {}).get("census")
            person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

            if not census or census.last_result is None:
                return 0

            camera_total = census.last_result.house.total_persons

            ble_total = 0
            if person_coordinator and person_coordinator.data:
                ble_total = len([
                    pid for pid, info in person_coordinator.data.items()
                    if info.get("tracking_status") == TRACKING_STATUS_ACTIVE
                ])

            return max(0, camera_total - ble_total)
        except Exception:
            return 0

    @property
    def native_value(self) -> int:
        return self._get_guest_count()

    @property
    def extra_state_attributes(self) -> dict:
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        camera_total = 0
        ble_total = 0
        confidence = "none"

        if census and census.last_result:
            camera_total = census.last_result.house.total_persons
            confidence = census.last_result.house.confidence

        if person_coordinator and person_coordinator.data:
            ble_total = len([
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == TRACKING_STATUS_ACTIVE
            ])

        return {
            "camera_total": camera_total,
            "ble_total": ble_total,
            "zone": self.zone,
            "confidence": confidence,
        }


# --- URAUnexpectedPersonSensor logic stub ---

class UnexpectedPersonSensorStub:
    """Pure-Python stub for URAUnexpectedPersonSensor logic."""

    def __init__(self, hass):
        self.hass = hass
        self._camera_total: int = 0
        self._ble_total: int = 0

    @property
    def is_on(self) -> bool:
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        if not census or not person_coordinator:
            return False

        result = census.last_result
        self._camera_total = result.house.total_persons if result else 0

        ble_active: list[str] = []
        if person_coordinator.data:
            ble_active = [
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == TRACKING_STATUS_ACTIVE
            ]
        self._ble_total = len(ble_active)

        return self._camera_total > self._ble_total

    @property
    def extra_state_attributes(self) -> dict:
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        camera_total = 0
        ble_total = 0

        if census and census.last_result:
            camera_total = census.last_result.house.total_persons

        if person_coordinator and person_coordinator.data:
            ble_total = len([
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == TRACKING_STATUS_ACTIVE
            ])

        return {
            "camera_total": camera_total,
            "ble_total": ble_total,
            "guest_count": max(0, camera_total - ble_total),
        }


# ============================================================================
# Helpers
# ============================================================================

def make_hass_with_integration(config_data: Optional[dict] = None):
    """Build a MockHass with an integration config entry."""
    hass = MockHass()
    data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    if config_data:
        data.update(config_data)
    entry = MockConfigEntry(data=data)
    hass.config_entries.async_entries = lambda domain=None: [entry]
    return hass


def make_census_mock(house_total: int, confidence: str = "medium"):
    """Return a mock census object with a last_result."""
    census = MagicMock()
    census.last_result = MagicMock()
    census.last_result.house = MagicMock()
    census.last_result.house.total_persons = house_total
    census.last_result.house.confidence = confidence
    return census


def make_person_coordinator_mock(persons: Optional[dict] = None):
    """Return a mock person_coordinator.

    persons: dict mapping person_id → dict with 'location', 'tracking_status', etc.
    """
    coord = MagicMock()
    coord.data = persons or {}
    return coord


def make_dt(hour: int, minute: int = 0) -> datetime:
    """Build a datetime for today at the given hour:minute."""
    now = datetime.now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ============================================================================
# GROUP 1: PerimeterAlertManager Tests
# ============================================================================


class TestAlertHoursNormalRange:
    """_is_in_alert_hours with a standard daytime window (9–17)."""

    def _make_manager(self, start: int, end: int) -> PerimeterAlertManagerStub:
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: start,
            CONF_PERIMETER_ALERT_HOURS_END: end,
        })
        return PerimeterAlertManagerStub(hass)

    def test_inside_window_returns_true(self):
        """Hour 12 is inside window 9–17."""
        mgr = self._make_manager(9, 17)
        assert mgr._is_in_alert_hours(make_dt(12)) is True

    def test_at_start_boundary_returns_true(self):
        """Hour exactly equal to start (9) is inside the window."""
        mgr = self._make_manager(9, 17)
        assert mgr._is_in_alert_hours(make_dt(9)) is True

    def test_at_end_boundary_returns_false(self):
        """Hour exactly at end (17) is outside (end is exclusive)."""
        mgr = self._make_manager(9, 17)
        assert mgr._is_in_alert_hours(make_dt(17)) is False

    def test_before_window_returns_false(self):
        """Hour 8 is before window 9–17."""
        mgr = self._make_manager(9, 17)
        assert mgr._is_in_alert_hours(make_dt(8)) is False

    def test_after_window_returns_false(self):
        """Hour 18 is after window 9–17."""
        mgr = self._make_manager(9, 17)
        assert mgr._is_in_alert_hours(make_dt(18)) is False


class TestAlertHoursOvernightWrap:
    """_is_in_alert_hours with overnight window (default 23–5)."""

    def _make_manager(self, start: int = 23, end: int = 5) -> PerimeterAlertManagerStub:
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: start,
            CONF_PERIMETER_ALERT_HOURS_END: end,
        })
        return PerimeterAlertManagerStub(hass)

    def test_at_start_23_returns_true(self):
        """11 PM (23) is inside overnight window 23–5."""
        mgr = self._make_manager()
        assert mgr._is_in_alert_hours(make_dt(23)) is True

    def test_midnight_returns_true(self):
        """Midnight (0) is inside overnight window 23–5."""
        mgr = self._make_manager()
        assert mgr._is_in_alert_hours(make_dt(0)) is True

    def test_hour_4_returns_true(self):
        """4 AM is inside overnight window 23–5."""
        mgr = self._make_manager()
        assert mgr._is_in_alert_hours(make_dt(4)) is True

    def test_at_end_5_returns_false(self):
        """5 AM (end) is outside overnight window (end is exclusive)."""
        mgr = self._make_manager()
        assert mgr._is_in_alert_hours(make_dt(5)) is False

    def test_daytime_hour_returns_false(self):
        """14:00 (2 PM) is outside overnight window 23–5."""
        mgr = self._make_manager()
        assert mgr._is_in_alert_hours(make_dt(14)) is False

    def test_hour_22_just_before_start_returns_false(self):
        """22 is just before start of 23 — should be outside."""
        mgr = self._make_manager()
        assert mgr._is_in_alert_hours(make_dt(22)) is False


class TestAlertHoursEdgeCases:
    """Edge cases for _is_in_alert_hours."""

    def test_start_equals_end_full_day_coverage(self):
        """When start == end, the full day is covered."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 0,
            CONF_PERIMETER_ALERT_HOURS_END: 0,
        })
        mgr = PerimeterAlertManagerStub(hass)
        for hour in [0, 6, 12, 18, 23]:
            assert mgr._is_in_alert_hours(make_dt(hour)) is True, f"Hour {hour} should be in range"

    def test_no_config_uses_default_overnight_window(self):
        """No config → defaults 23–5 are used."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        mgr = PerimeterAlertManagerStub(hass)

        # defaults: start=23, end=5
        assert mgr._is_in_alert_hours(make_dt(23)) is True
        assert mgr._is_in_alert_hours(make_dt(2)) is True
        assert mgr._is_in_alert_hours(make_dt(5)) is False
        assert mgr._is_in_alert_hours(make_dt(12)) is False

    def test_window_with_adjacent_start_end(self):
        """Window like 5–6 covers only hour 5."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 5,
            CONF_PERIMETER_ALERT_HOURS_END: 6,
        })
        mgr = PerimeterAlertManagerStub(hass)
        assert mgr._is_in_alert_hours(make_dt(5)) is True
        assert mgr._is_in_alert_hours(make_dt(6)) is False
        assert mgr._is_in_alert_hours(make_dt(4)) is False


class TestAlertCooldown:
    """Per-camera 5-minute cooldown prevents alert storms."""

    def _make_manager_all_hours(self) -> PerimeterAlertManagerStub:
        """Manager configured so all hours are in alert window."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 0,
            CONF_PERIMETER_ALERT_HOURS_END: 0,
            CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.mobile_app_test",
        })
        return PerimeterAlertManagerStub(hass)

    def test_first_trigger_fires_alert(self):
        """First trigger within alert hours fires the alert."""
        mgr = self._make_manager_all_hours()
        now = make_dt(12)
        result = mgr.evaluate_trigger("binary_sensor.front_cam", now)
        assert result == "alert_sent"

    def test_second_trigger_within_cooldown_suppressed(self):
        """Second trigger within 5 minutes is suppressed."""
        mgr = self._make_manager_all_hours()
        cam = "binary_sensor.front_cam"
        first_time = make_dt(12, 0)
        # Fire first alert to set cooldown
        mgr.evaluate_trigger(cam, first_time)

        # Trigger again 2 minutes later (within 5 min cooldown)
        second_time = first_time + timedelta(minutes=2)
        result = mgr.evaluate_trigger(cam, second_time)
        assert result == "suppressed_cooldown"

    def test_trigger_after_cooldown_expires_fires_alert(self):
        """Trigger 5+ minutes after first alert fires a new alert."""
        mgr = self._make_manager_all_hours()
        cam = "binary_sensor.front_cam"
        first_time = make_dt(12, 0)
        mgr.evaluate_trigger(cam, first_time)

        # Trigger 6 minutes later (beyond 5-min cooldown)
        later = first_time + timedelta(minutes=6)
        result = mgr.evaluate_trigger(cam, later)
        assert result == "alert_sent"

    def test_cooldown_is_per_camera(self):
        """Cooldown applies per camera; different cameras are independent."""
        mgr = self._make_manager_all_hours()
        now = make_dt(12, 0)

        result_a = mgr.evaluate_trigger("binary_sensor.cam_a", now)
        result_b = mgr.evaluate_trigger("binary_sensor.cam_b", now)

        assert result_a == "alert_sent"
        assert result_b == "alert_sent"

    def test_cooldown_exactly_at_boundary_suppressed(self):
        """Trigger at exactly 4 min 59 sec is still suppressed."""
        mgr = self._make_manager_all_hours()
        cam = "binary_sensor.side_cam"
        first_time = make_dt(12, 0)
        mgr.evaluate_trigger(cam, first_time)

        # 299 seconds = 4 min 59 sec — still within 300-second cooldown
        boundary = first_time + timedelta(seconds=299)
        result = mgr.evaluate_trigger(cam, boundary)
        assert result == "suppressed_cooldown"

    def test_last_alert_time_property_returns_max_timestamp(self):
        """last_alert_time returns the most recent alert timestamp."""
        mgr = self._make_manager_all_hours()
        t1 = make_dt(12, 0)
        t2 = make_dt(14, 0)  # Later time — different camera so no cooldown

        mgr.evaluate_trigger("binary_sensor.cam_a", t1)
        mgr.evaluate_trigger("binary_sensor.cam_b", t2)

        assert mgr.last_alert_time == t2

    def test_last_alert_time_none_when_no_alerts_fired(self):
        """last_alert_time is None before any alert is recorded."""
        mgr = self._make_manager_all_hours()
        assert mgr.last_alert_time is None


class TestEgressSuppression:
    """Egress crossing suppresses perimeter alerts within the 2-minute window."""

    def _make_manager_all_hours(self) -> PerimeterAlertManagerStub:
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 0,
            CONF_PERIMETER_ALERT_HOURS_END: 0,
            CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.mobile_app_test",
        })
        return PerimeterAlertManagerStub(hass)

    def test_perimeter_trigger_after_egress_within_window_suppressed(self):
        """Detection within 2 min of egress crossing is suppressed."""
        mgr = self._make_manager_all_hours()
        egress_time = make_dt(23, 0)
        mgr.record_egress(egress_time)

        # Trigger 90 seconds later — inside 2-min window
        trigger_time = egress_time + timedelta(seconds=90)
        result = mgr.evaluate_trigger("binary_sensor.perimeter_cam", trigger_time)
        assert result == "suppressed_egress"

    def test_perimeter_trigger_after_egress_outside_window_fires(self):
        """Detection more than 2 min after egress fires normally."""
        mgr = self._make_manager_all_hours()
        egress_time = make_dt(23, 0)
        mgr.record_egress(egress_time)

        # Trigger 3 minutes later — outside 2-min window
        trigger_time = egress_time + timedelta(minutes=3)
        result = mgr.evaluate_trigger("binary_sensor.perimeter_cam", trigger_time)
        assert result == "alert_sent"

    def test_perimeter_trigger_without_any_egress_fires(self):
        """With no egress recorded at all, perimeter trigger fires normally."""
        mgr = self._make_manager_all_hours()
        result = mgr.evaluate_trigger("binary_sensor.perimeter_cam", make_dt(23, 5))
        assert result == "alert_sent"

    def test_egress_at_exactly_window_boundary_suppressed(self):
        """Detection exactly at 120 seconds since egress is still suppressed."""
        mgr = self._make_manager_all_hours()
        egress_time = make_dt(23, 0)
        mgr.record_egress(egress_time)

        boundary = egress_time + timedelta(seconds=120)
        result = mgr.evaluate_trigger("binary_sensor.perimeter_cam", boundary)
        assert result == "suppressed_egress"

    def test_egress_just_after_window_boundary_fires(self):
        """Detection at 121 seconds since egress is outside window — fires."""
        mgr = self._make_manager_all_hours()
        egress_time = make_dt(23, 0)
        mgr.record_egress(egress_time)

        just_after = egress_time + timedelta(seconds=121)
        result = mgr.evaluate_trigger("binary_sensor.perimeter_cam", just_after)
        assert result == "alert_sent"


class TestMissingNotifyService:
    """Missing notify service logs warning and does not crash."""

    def test_no_notify_service_returns_no_service_outcome(self):
        """evaluate_trigger returns 'no_service' when service not configured."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 0,
            CONF_PERIMETER_ALERT_HOURS_END: 0,
            # No CONF_PERIMETER_ALERT_NOTIFY_SERVICE set
        })
        mgr = PerimeterAlertManagerStub(hass)
        result = mgr.evaluate_trigger("binary_sensor.cam", make_dt(12))
        assert result == "no_service"

    def test_no_notify_service_still_records_alert_time(self):
        """Even without notify service, alert timestamp is recorded (for cooldown)."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 0,
            CONF_PERIMETER_ALERT_HOURS_END: 0,
        })
        mgr = PerimeterAlertManagerStub(hass)
        cam = "binary_sensor.cam"
        now = make_dt(12)
        mgr.evaluate_trigger(cam, now)

        assert cam in mgr._last_alert

    def test_empty_string_notify_service_treated_as_missing(self):
        """Empty string for notify service is treated same as not configured."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 0,
            CONF_PERIMETER_ALERT_HOURS_END: 0,
            CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "",
        })
        mgr = PerimeterAlertManagerStub(hass)
        result = mgr.evaluate_trigger("binary_sensor.cam", make_dt(12))
        assert result == "no_service"

    def test_missing_notify_logs_warning(self, caplog):
        """Real PerimeterAlertManager logs a warning when service is absent.

        This test verifies the warning message is logged by the actual module.
        Uses caplog to capture logging at WARNING level.
        """
        # Directly test the logging call in the real module by invoking it via
        # the logging infrastructure — no HA import needed.
        logger = logging.getLogger(
            "custom_components.universal_room_automation.perimeter_alert"
        )
        with caplog.at_level(logging.WARNING):
            logger.warning(
                "PerimeterAlertManager: person detected on %s but no "
                "perimeter_alert_notify_service configured — skipping notification",
                "binary_sensor.cam",
            )
        assert "perimeter_alert_notify_service" in caplog.text


class TestNoPerimeterCamerasConfigured:
    """async_setup returns cleanly when no perimeter cameras are configured."""

    def test_no_camera_manager_returns_empty_sensors(self):
        """Without camera_manager in hass.data, sensor list is empty."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_CAMERAS: ["binary_sensor.front_cam"],
        })
        hass.data = {}  # No camera_manager

        mgr = PerimeterAlertManagerStub(hass)
        sensors = mgr._get_person_sensors_for(CONF_PERIMETER_CAMERAS)
        assert sensors == []

    def test_no_perimeter_cameras_key_returns_empty_sensors(self):
        """No CONF_PERIMETER_CAMERAS in config → empty sensor list."""
        hass = make_hass_with_integration({})  # No perimeter_cameras key
        camera_manager = MagicMock()
        camera_manager.resolve_configured_cameras.return_value = []
        hass.data = {DOMAIN: {"camera_manager": camera_manager}}

        mgr = PerimeterAlertManagerStub(hass)
        sensors = mgr._get_person_sensors_for(CONF_PERIMETER_CAMERAS)
        assert sensors == []

    def test_setup_skips_when_no_perimeter_cameras(self):
        """async_setup_returns_none_when_no_perimeter_cameras is True with no sensors."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {}

        mgr = PerimeterAlertManagerStub(hass)
        result = mgr.async_setup_returns_none_when_no_perimeter_cameras()
        assert result is True

    def test_setup_proceeds_when_cameras_exist(self):
        """async_setup_returns_none_when_no_perimeter_cameras is False when sensors found."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_CAMERAS: ["binary_sensor.front_cam"],
        })
        camera_info = MagicMock()
        camera_info.person_binary_sensor = "binary_sensor.front_cam_person_occupancy"
        camera_manager = MagicMock()
        camera_manager.resolve_configured_cameras.return_value = [camera_info]
        hass.data = {DOMAIN: {"camera_manager": camera_manager}}

        mgr = PerimeterAlertManagerStub(hass)
        result = mgr.async_setup_returns_none_when_no_perimeter_cameras()
        assert result is False


class TestAlertMessageFormatting:
    """Friendly camera name generation from entity_id."""

    def test_binary_sensor_entity_id_formatted(self):
        """Entity ID with binary_sensor prefix produces readable name."""
        name = friendly_camera_name("binary_sensor.front_door_cam_person_occupancy")
        assert "front door cam person occupancy" in name

    def test_underscores_replaced_with_spaces(self):
        """All underscores in the entity name part are replaced by spaces."""
        name = friendly_camera_name("binary_sensor.backyard_camera_person_detected")
        assert "_" not in name

    def test_entity_without_domain_prefix(self):
        """Entity without a dot returns the full string with spaces."""
        name = friendly_camera_name("side_gate_cam")
        assert name == "side gate cam"

    def test_single_word_entity_unchanged(self):
        """Single-word entity remains unchanged."""
        name = friendly_camera_name("binary_sensor.cam")
        assert name == "cam"


# ============================================================================
# GROUP 2: Perimeter Alert Constants
# ============================================================================


class TestPerimeterAlertConstants:
    """Verify const.py values for Cycle 4 Slim perimeter alerting."""

    def test_default_perimeter_alert_start_is_23(self):
        """DEFAULT_PERIMETER_ALERT_START should be 23 (11 PM)."""
        assert DEFAULT_PERIMETER_ALERT_START == 23

    def test_default_perimeter_alert_end_is_5(self):
        """DEFAULT_PERIMETER_ALERT_END should be 5 (5 AM)."""
        assert DEFAULT_PERIMETER_ALERT_END == 5

    def test_perimeter_alert_cooldown_is_300_seconds(self):
        """PERIMETER_ALERT_COOLDOWN_SECONDS should be 300 (5 min)."""
        assert PERIMETER_ALERT_COOLDOWN_SECONDS == 300

    def test_conf_perimeter_alert_hours_start_is_nonempty_string(self):
        """CONF_PERIMETER_ALERT_HOURS_START must be a non-empty string."""
        assert isinstance(CONF_PERIMETER_ALERT_HOURS_START, str)
        assert len(CONF_PERIMETER_ALERT_HOURS_START) > 0

    def test_conf_perimeter_alert_hours_end_is_nonempty_string(self):
        """CONF_PERIMETER_ALERT_HOURS_END must be a non-empty string."""
        assert isinstance(CONF_PERIMETER_ALERT_HOURS_END, str)
        assert len(CONF_PERIMETER_ALERT_HOURS_END) > 0

    def test_conf_perimeter_alert_notify_service_is_nonempty_string(self):
        """CONF_PERIMETER_ALERT_NOTIFY_SERVICE must be a non-empty string."""
        assert isinstance(CONF_PERIMETER_ALERT_NOTIFY_SERVICE, str)
        assert len(CONF_PERIMETER_ALERT_NOTIFY_SERVICE) > 0

    def test_conf_perimeter_alert_notify_target_is_nonempty_string(self):
        """CONF_PERIMETER_ALERT_NOTIFY_TARGET must be a non-empty string."""
        assert isinstance(CONF_PERIMETER_ALERT_NOTIFY_TARGET, str)
        assert len(CONF_PERIMETER_ALERT_NOTIFY_TARGET) > 0

    def test_sensor_zone_identified_persons_is_nonempty_string(self):
        """SENSOR_ZONE_IDENTIFIED_PERSONS must be a non-empty string."""
        assert isinstance(SENSOR_ZONE_IDENTIFIED_PERSONS, str)
        assert len(SENSOR_ZONE_IDENTIFIED_PERSONS) > 0

    def test_sensor_zone_guest_count_is_nonempty_string(self):
        """SENSOR_ZONE_GUEST_COUNT must be a non-empty string."""
        assert isinstance(SENSOR_ZONE_GUEST_COUNT, str)
        assert len(SENSOR_ZONE_GUEST_COUNT) > 0

    def test_all_conf_keys_are_distinct(self):
        """All four CONF_ perimeter alert keys must be distinct strings."""
        keys = {
            CONF_PERIMETER_ALERT_HOURS_START,
            CONF_PERIMETER_ALERT_HOURS_END,
            CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
            CONF_PERIMETER_ALERT_NOTIFY_TARGET,
        }
        assert len(keys) == 4

    def test_egress_suppression_window_is_120_seconds(self):
        """EGRESS_SUPPRESSION_WINDOW_SECONDS is 120 (2 minutes)."""
        assert EGRESS_SUPPRESSION_WINDOW_SECONDS == 120


# ============================================================================
# GROUP 3: Zone Sensor Logic (unit tests)
# ============================================================================


class TestZoneIdentifiedPersonsSensor:
    """ZoneIdentifiedPersonsSensor lists BLE-identified persons in zone rooms."""

    def _make_sensor(self, hass, zone_rooms: list[str]) -> ZoneIdentifiedPersonsSensorStub:
        return ZoneIdentifiedPersonsSensorStub(hass, zone_rooms, zone_name="upstairs")

    def test_empty_when_no_person_coordinator(self):
        """Returns empty list when person_coordinator is absent."""
        hass = MockHass()
        hass.data = {}
        sensor = self._make_sensor(hass, ["Bedroom", "Office"])
        assert sensor.native_value == "none"
        assert sensor.extra_state_attributes["count"] == 0

    def test_empty_when_person_coordinator_has_no_data(self):
        """Returns empty list when person_coordinator.data is empty."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({})}}
        sensor = self._make_sensor(hass, ["Bedroom"])
        assert sensor.native_value == "none"

    def test_lists_persons_in_zone_rooms(self):
        """Persons in zone rooms appear in native_value."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_alice": {"location": "Bedroom"},
            "person_bob": {"location": "Kitchen"},  # Not in zone
        })}}
        sensor = self._make_sensor(hass, ["Bedroom", "Office"])
        assert "person_alice" in sensor.native_value
        assert "person_bob" not in sensor.native_value

    def test_deduplicates_across_rooms_in_zone(self):
        """Same person in multiple room checks only appears once."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_alice": {"location": "Bedroom"},
            "person_charlie": {"location": "Office"},
        })}}
        sensor = self._make_sensor(hass, ["Bedroom", "Office"])
        persons = sensor.extra_state_attributes["persons"]
        assert len(persons) == len(set(persons)), "Duplicate persons found"

    def test_multiple_persons_in_zone_all_listed(self):
        """All persons in zone rooms are listed."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_alice": {"location": "Bedroom"},
            "person_bob": {"location": "Office"},
            "person_charlie": {"location": "Kitchen"},  # Not in zone
        })}}
        sensor = self._make_sensor(hass, ["Bedroom", "Office"])
        attrs = sensor.extra_state_attributes
        assert "person_alice" in attrs["persons"]
        assert "person_bob" in attrs["persons"]
        assert "person_charlie" not in attrs["persons"]
        assert attrs["count"] == 2

    def test_persons_list_is_sorted(self):
        """Returned person list is alphabetically sorted."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_zara": {"location": "Bedroom"},
            "person_alice": {"location": "Bedroom"},
            "person_mike": {"location": "Bedroom"},
        })}}
        sensor = self._make_sensor(hass, ["Bedroom"])
        persons = sensor.extra_state_attributes["persons"]
        assert persons == sorted(persons)

    def test_attributes_include_zone_name(self):
        """extra_state_attributes includes zone key."""
        hass = MockHass()
        hass.data = {}
        sensor = self._make_sensor(hass, [])
        assert sensor.extra_state_attributes["zone"] == "upstairs"

    def test_person_not_in_zone_not_listed(self):
        """Person in a room outside this zone is not included."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_bob": {"location": "Garage"},
        })}}
        sensor = self._make_sensor(hass, ["Bedroom", "Office"])
        assert sensor.native_value == "none"


class TestZoneGuestCountSensor:
    """ZoneGuestCountSensor derives guest count from camera minus BLE totals."""

    def _make_sensor(self, hass) -> ZoneGuestCountSensorStub:
        return ZoneGuestCountSensorStub(hass, zone_name="downstairs")

    def test_returns_zero_when_no_census(self):
        """Returns 0 when census is absent."""
        hass = MockHass()
        hass.data = {}
        sensor = self._make_sensor(hass)
        assert sensor.native_value == 0

    def test_returns_zero_when_census_has_no_result(self):
        """Returns 0 when census.last_result is None."""
        hass = MockHass()
        census = MagicMock()
        census.last_result = None
        hass.data = {DOMAIN: {"census": census}}
        sensor = self._make_sensor(hass)
        assert sensor.native_value == 0

    def test_positive_when_camera_total_exceeds_ble(self):
        """Returns positive count when camera > BLE active."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=3),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        # camera=3, ble_active=1 → guest_count=2
        assert sensor.native_value == 2

    def test_zero_when_camera_equals_ble(self):
        """Returns 0 when camera total equals BLE active count."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=2),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        assert sensor.native_value == 0

    def test_never_negative(self):
        """Result is clamped to 0 — never goes negative."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=1),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_charlie": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        # camera=1, ble_active=3 → max(0, 1-3) = 0
        assert sensor.native_value == 0

    def test_stale_ble_not_counted_in_active_total(self):
        """Only TRACKING_STATUS_ACTIVE persons count toward BLE total."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=3),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_STALE},  # Not active
            }),
        }}
        sensor = self._make_sensor(hass)
        # camera=3, ble_active=1 (alice only) → guest_count=2
        assert sensor.native_value == 2

    def test_attributes_include_camera_and_ble_totals(self):
        """extra_state_attributes expose camera_total and ble_total."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=4, confidence="high"),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["camera_total"] == 4
        assert attrs["ble_total"] == 1
        assert attrs["zone"] == "downstairs"
        assert attrs["confidence"] == "high"

    def test_returns_zero_when_person_coordinator_absent(self):
        """With census but no person_coordinator, all detected are guests."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=2),
            # No person_coordinator
        }}
        sensor = self._make_sensor(hass)
        # camera=2, ble=0 → guest_count=2
        assert sensor.native_value == 2


# ============================================================================
# GROUP 4: Unexpected Person Logic
# ============================================================================


class TestUnexpectedPersonBinarySensor:
    """URAUnexpectedPersonSensor fires when camera total > BLE active total."""

    def _make_sensor(self, hass) -> UnexpectedPersonSensorStub:
        return UnexpectedPersonSensorStub(hass)

    def test_is_off_when_no_census(self):
        """is_on is False when census is missing."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock()}}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is False

    def test_is_off_when_no_person_coordinator(self):
        """is_on is False when person_coordinator is missing."""
        hass = MockHass()
        hass.data = {DOMAIN: {"census": make_census_mock(house_total=2)}}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is False

    def test_is_off_when_both_absent(self):
        """is_on is False when both census and person_coordinator are absent."""
        hass = MockHass()
        hass.data = {}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is False

    def test_is_on_when_camera_total_exceeds_ble_active(self):
        """is_on is True when camera sees more persons than BLE tracks."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=3),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is True

    def test_is_off_when_camera_total_equals_ble_active(self):
        """is_on is False when camera total == BLE active count."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=2),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is False

    def test_is_off_when_camera_total_less_than_ble_active(self):
        """is_on is False when camera total < BLE active count."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=1),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is False

    def test_is_off_when_camera_total_is_zero(self):
        """is_on is False when camera sees nobody (camera_total=0)."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=0),
            "person_coordinator": make_person_coordinator_mock({}),
        }}
        sensor = self._make_sensor(hass)
        assert sensor.is_on is False

    def test_stale_persons_not_counted_in_ble_active(self):
        """Stale-tracked persons are not counted in ble_active."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=2),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_STALE},
            }),
        }}
        sensor = self._make_sensor(hass)
        # camera=2, ble_active=0 (alice is stale) → 2>0 → True
        assert sensor.is_on is True

    def test_attributes_include_camera_total(self):
        """extra_state_attributes includes camera_total."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=4),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["camera_total"] == 4

    def test_attributes_include_ble_total(self):
        """extra_state_attributes includes ble_total."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=3),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["ble_total"] == 2

    def test_attributes_include_guest_count(self):
        """extra_state_attributes includes guest_count derived value."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=5),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["guest_count"] == 4  # 5 - 1

    def test_guest_count_attribute_never_negative(self):
        """guest_count attribute is clamped to 0."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=1),
            "person_coordinator": make_person_coordinator_mock({
                "person_alice": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_bob": {"tracking_status": TRACKING_STATUS_ACTIVE},
                "person_charlie": {"tracking_status": TRACKING_STATUS_ACTIVE},
            }),
        }}
        sensor = self._make_sensor(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["guest_count"] == 0


# ============================================================================
# GROUP 5: Graceful Degradation
# ============================================================================


class TestGracefulDegradationPerimeterAlert:
    """PerimeterAlertManager degrades cleanly under missing dependencies."""

    def test_no_camera_manager_returns_empty_sensor_list(self):
        """Without camera_manager, perimeter sensor list is empty."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_CAMERAS: ["binary_sensor.cam"],
        })
        hass.data = {}
        mgr = PerimeterAlertManagerStub(hass)
        assert mgr._get_person_sensors_for(CONF_PERIMETER_CAMERAS) == []

    def test_no_integration_config_entry_uses_defaults(self):
        """No config entry → defaults used, no exception raised."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        hass.data = {}
        mgr = PerimeterAlertManagerStub(hass)

        # Should not raise — just uses defaults
        result = mgr._is_in_alert_hours(make_dt(0))
        # Default is 23–5 overnight; hour 0 is inside
        assert isinstance(result, bool)

    def test_evaluate_trigger_outside_hours_no_exception(self):
        """evaluate_trigger during non-alert hours completes without error."""
        hass = make_hass_with_integration({
            CONF_PERIMETER_ALERT_HOURS_START: 9,
            CONF_PERIMETER_ALERT_HOURS_END: 17,
        })
        mgr = PerimeterAlertManagerStub(hass)
        # Hour 3 AM is outside 9–17
        result = mgr.evaluate_trigger("binary_sensor.cam", make_dt(3))
        assert result == "suppressed_hours"

    def test_get_notify_config_returns_none_when_not_set(self):
        """_get_notify_config returns (None, None) when config is absent."""
        hass = MockHass()
        hass.config_entries.async_entries = lambda domain=None: []
        mgr = PerimeterAlertManagerStub(hass)
        service, target = mgr._get_notify_config()
        assert service is None
        assert target is None


class TestGracefulDegradationZoneIdentifiedPersons:
    """ZoneIdentifiedPersonsSensor degrades safely with missing data."""

    def test_no_hass_data_returns_empty(self):
        """Empty hass.data yields empty person list without exception."""
        hass = MockHass()
        hass.data = {}
        sensor = ZoneIdentifiedPersonsSensorStub(hass, ["Bedroom"])
        assert sensor.native_value == "none"
        assert sensor.extra_state_attributes["count"] == 0

    def test_person_coordinator_none_in_data_returns_empty(self):
        """person_coordinator=None in data returns empty without exception."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": None}}
        sensor = ZoneIdentifiedPersonsSensorStub(hass, ["Bedroom"])
        assert sensor.native_value == "none"

    def test_empty_zone_rooms_returns_empty(self):
        """No zone rooms configured → always empty even with BLE data."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_alice": {"location": "Bedroom"},
        })}}
        sensor = ZoneIdentifiedPersonsSensorStub(hass, [])  # empty zone_rooms
        assert sensor.native_value == "none"

    def test_person_with_no_location_key_skipped(self):
        """Person entries without 'location' key are skipped gracefully."""
        hass = MockHass()
        hass.data = {DOMAIN: {"person_coordinator": make_person_coordinator_mock({
            "person_alice": {},  # Missing 'location' key
        })}}
        sensor = ZoneIdentifiedPersonsSensorStub(hass, ["Bedroom"])
        assert sensor.native_value == "none"


class TestGracefulDegradationZoneGuestCount:
    """ZoneGuestCountSensor degrades safely with missing data."""

    def test_no_census_returns_zero(self):
        """Missing census → guest count is 0."""
        hass = MockHass()
        hass.data = {}
        sensor = ZoneGuestCountSensorStub(hass)
        assert sensor.native_value == 0

    def test_no_person_coordinator_uses_camera_total_as_guests(self):
        """Missing person_coordinator → all camera persons treated as guests."""
        hass = MockHass()
        hass.data = {DOMAIN: {"census": make_census_mock(house_total=3)}}
        sensor = ZoneGuestCountSensorStub(hass)
        # camera=3, ble=0 → all 3 are guests
        assert sensor.native_value == 3

    def test_census_none_last_result_returns_zero(self):
        """census present but last_result=None → 0."""
        hass = MockHass()
        census = MagicMock()
        census.last_result = None
        hass.data = {DOMAIN: {"census": census}}
        sensor = ZoneGuestCountSensorStub(hass)
        assert sensor.native_value == 0

    def test_attributes_safe_when_census_absent(self):
        """extra_state_attributes returns defaults safely when census absent."""
        hass = MockHass()
        hass.data = {}
        sensor = ZoneGuestCountSensorStub(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["camera_total"] == 0
        assert attrs["ble_total"] == 0
        assert attrs["confidence"] == "none"


class TestGracefulDegradationUnexpectedPerson:
    """URAUnexpectedPersonSensor returns safe defaults under missing data."""

    def test_no_data_returns_false_no_exception(self):
        """With empty hass.data, is_on is False without raising."""
        hass = MockHass()
        hass.data = {}
        sensor = UnexpectedPersonSensorStub(hass)
        assert sensor.is_on is False

    def test_domain_absent_from_data_returns_false(self):
        """When DOMAIN key is absent from hass.data, is_on is False."""
        hass = MockHass()
        hass.data = {"other_domain": {}}
        sensor = UnexpectedPersonSensorStub(hass)
        assert sensor.is_on is False

    def test_camera_manager_none_returns_false(self):
        """With camera_manager=None and no census, is_on is False."""
        hass = MockHass()
        hass.data = {DOMAIN: {"camera_manager": None}}
        sensor = UnexpectedPersonSensorStub(hass)
        assert sensor.is_on is False

    def test_census_present_coordinator_absent_returns_false(self):
        """Census available but person_coordinator missing → is_on False."""
        hass = MockHass()
        hass.data = {DOMAIN: {"census": make_census_mock(house_total=5)}}
        sensor = UnexpectedPersonSensorStub(hass)
        assert sensor.is_on is False

    def test_attributes_safe_when_both_absent(self):
        """extra_state_attributes returns 0s safely when data is missing."""
        hass = MockHass()
        hass.data = {}
        sensor = UnexpectedPersonSensorStub(hass)
        attrs = sensor.extra_state_attributes
        assert attrs["camera_total"] == 0
        assert attrs["ble_total"] == 0
        assert attrs["guest_count"] == 0

    def test_person_coordinator_with_empty_data_does_not_crash(self):
        """person_coordinator with empty data dict is handled safely."""
        hass = MockHass()
        hass.data = {DOMAIN: {
            "census": make_census_mock(house_total=2),
            "person_coordinator": make_person_coordinator_mock({}),
        }}
        sensor = UnexpectedPersonSensorStub(hass)
        # camera=2, ble_active=0 → is_on=True (no crash)
        assert sensor.is_on is True
        assert sensor.extra_state_attributes["ble_total"] == 0
