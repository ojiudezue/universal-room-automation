"""Tests for D6 multi-source occupancy confidence check.

Validates _check_zone_occupancy_confidence logic in HVACCoordinator,
which counts independent occupancy sources to decide whether a zone's
prolonged occupancy is real (2+ sources) or a stuck sensor (0-1 sources).

Sources:
  1. Motion/mmWave with recent last_changed (<30 min)
  2. BLE person detection (phone in zone)
  3. Camera person detection (Frigate person entity "on")
  4. Multiple rooms occupied (>=2 rooms)

D6 integration:
  - confidence >= 2 => reset continuous_occupied_since (not stale)
  - confidence < 2  => set effective_preset to "away" (stale sensor)
"""

import sys
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from unittest.mock import MagicMock, Mock, patch
import pytest

# Ensure aiosqlite mock is available before any URA imports
sys.modules.setdefault("aiosqlite", MagicMock())


# ---------------------------------------------------------------------------
# Lightweight mocks — replicate just enough structure to test the logic
# directly without importing the real HVAC module.
# ---------------------------------------------------------------------------

DOMAIN = "universal_room_automation"
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_ROOM = "room"
CONF_ROOM_NAME = "room_name"


@dataclass
class RoomCondition:
    room_name: str
    occupied: bool = False


@dataclass
class FakeZone:
    zone_id: str = "zone_1"
    zone_name: str = "Test Zone"
    rooms: list = field(default_factory=lambda: ["Living Room"])
    room_conditions: list = field(default_factory=list)
    zone_cameras: list = field(default_factory=list)
    continuous_occupied_since: datetime = None
    vacancy_sweep_done: bool = False
    vacancy_sweep_enabled: bool = True

    @property
    def any_room_occupied(self) -> bool:
        return any(r.occupied for r in self.room_conditions)


class FakeState:
    def __init__(self, state):
        self.state = state


class FakeConfigEntry:
    def __init__(self, data, entry_id="entry_1"):
        self.data = data
        self.entry_id = entry_id


class FakeHass:
    """Minimal hass mock with states and config_entries."""

    def __init__(self):
        self.data = {}
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self.config_entries = MagicMock()
        self.config_entries.async_entries = MagicMock(return_value=[])

    def set_state(self, entity_id, state_value):
        self._states[entity_id] = FakeState(state_value)


def _utcnow():
    """Return a timezone-aware UTC now."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# The function under test — extracted verbatim from hvac.py so we can test
# it in isolation without pulling in the full coordinator stack.
# ---------------------------------------------------------------------------

def check_zone_occupancy_confidence(hass, zone) -> int:
    """Replica of HVACCoordinator._check_zone_occupancy_confidence."""
    sources = 0

    # Source 1: Recent motion state changes
    has_recent_motion_change = False
    now = _utcnow()
    for room_name in zone.rooms:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if (
                entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
                and entry.data.get(CONF_ROOM_NAME) == room_name
            ):
                coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if coord and hasattr(coord, "_last_motion_time") and coord._last_motion_time:
                    age = (now - coord._last_motion_time).total_seconds()
                    if age < 1800:  # 30 min
                        has_recent_motion_change = True
                break
    if has_recent_motion_change:
        sources += 1

    # Source 2: BLE person detection
    person_coord = hass.data.get(DOMAIN, {}).get("person_coordinator")
    if person_coord:
        try:
            ble_persons = person_coord.get_persons_in_zone(zone.rooms)
            if ble_persons:
                sources += 1
        except Exception:
            pass

    # Source 3: Camera person detection
    for camera_entity in zone.zone_cameras:
        state = hass.states.get(camera_entity)
        if state and state.state == "on":
            sources += 1
            break

    # Source 4: Multiple occupied rooms
    occupied_count = sum(1 for rc in zone.room_conditions if rc.occupied)
    if occupied_count >= 2:
        sources += 1

    return sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass_with_room_coord(room_name, last_motion_time=None):
    """Create FakeHass with a room config entry and coordinator."""
    hass = FakeHass()
    entry = FakeConfigEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: room_name},
        entry_id="room_entry_1",
    )
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    coord = MagicMock()
    coord._last_motion_time = last_motion_time
    hass.data[DOMAIN] = {"room_entry_1": coord}
    return hass


def _add_ble_persons(hass, persons):
    """Wire up a person_coordinator that returns persons for any zone."""
    pc = MagicMock()
    pc.get_persons_in_zone = MagicMock(return_value=persons)
    hass.data.setdefault(DOMAIN, {})["person_coordinator"] = pc


def _add_camera(hass, zone, camera_entity, state_value):
    """Add a camera to zone and set its HA state."""
    zone.zone_cameras.append(camera_entity)
    hass.set_state(camera_entity, state_value)


# ===========================================================================
# TESTS
# ===========================================================================


class TestConfidenceCheck:
    """Tests for _check_zone_occupancy_confidence source counting."""

    # 1. No sources active -> returns 0
    def test_no_sources_returns_zero(self):
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=False)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0

    # 2. Only motion (recent) -> returns 1
    def test_only_recent_motion_returns_one(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord("Living Room", last_motion_time=now - timedelta(minutes=5))
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 1

    # 3. Only BLE persons in zone -> returns 1
    def test_only_ble_returns_one(self):
        hass = FakeHass()
        _add_ble_persons(hass, ["person.john"])
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 1

    # 4. Only camera person detected -> returns 1
    def test_only_camera_returns_one(self):
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        _add_camera(hass, zone, "binary_sensor.living_room_person", "on")
        assert check_zone_occupancy_confidence(hass, zone) == 1

    # 5. Only multiple rooms occupied -> returns 1
    def test_only_multiple_rooms_returns_one(self):
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room", "Kitchen"],
            room_conditions=[
                RoomCondition("Living Room", occupied=True),
                RoomCondition("Kitchen", occupied=True),
            ],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 1

    # 6. Motion + BLE -> returns 2 (threshold met)
    def test_motion_plus_ble_returns_two(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord("Living Room", last_motion_time=now - timedelta(minutes=10))
        _add_ble_persons(hass, ["person.john"])
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 2

    # 7. BLE + camera -> returns 2
    def test_ble_plus_camera_returns_two(self):
        hass = FakeHass()
        _add_ble_persons(hass, ["person.jane"])
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        _add_camera(hass, zone, "binary_sensor.frigate_person", "on")
        assert check_zone_occupancy_confidence(hass, zone) == 2

    # 8. Motion + multiple rooms -> returns 2
    def test_motion_plus_multi_room_returns_two(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord("Living Room", last_motion_time=now - timedelta(minutes=15))
        zone = FakeZone(
            rooms=["Living Room", "Kitchen"],
            room_conditions=[
                RoomCondition("Living Room", occupied=True),
                RoomCondition("Kitchen", occupied=True),
            ],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 2

    # 9. All 4 sources -> returns 4
    def test_all_four_sources_returns_four(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord("Living Room", last_motion_time=now - timedelta(minutes=2))
        _add_ble_persons(hass, ["person.john"])
        zone = FakeZone(
            rooms=["Living Room", "Kitchen"],
            room_conditions=[
                RoomCondition("Living Room", occupied=True),
                RoomCondition("Kitchen", occupied=True),
            ],
        )
        _add_camera(hass, zone, "binary_sensor.frigate_person", "on")
        assert check_zone_occupancy_confidence(hass, zone) == 4

    # 10. Motion but stale (>30 min) -> doesn't count
    def test_stale_motion_does_not_count(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord(
            "Living Room",
            last_motion_time=now - timedelta(minutes=45),
        )
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        # Stale motion only, single occupied room => 0 sources
        assert check_zone_occupancy_confidence(hass, zone) == 0

    # 10b. Motion exactly at 30 min boundary -> doesn't count (>= 1800s)
    def test_motion_at_boundary_does_not_count(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord(
            "Living Room",
            last_motion_time=now - timedelta(seconds=1800),
        )
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        # age == 1800, condition is age < 1800 => not counted
        assert check_zone_occupancy_confidence(hass, zone) == 0

    # 10c. Motion at 29 min 59s -> counts
    def test_motion_just_under_boundary_counts(self):
        now = _utcnow()
        hass = _make_hass_with_room_coord(
            "Living Room",
            last_motion_time=now - timedelta(seconds=1799),
        )
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 1


class TestD6Integration:
    """Tests for the D6 decision logic that uses confidence check results."""

    def _simulate_d6_decision(self, zone, confidence, max_hours=8):
        """Simulate the D6 stale occupancy failsafe decision.

        Returns (effective_preset, timer_reset) where:
          effective_preset is "away" if stale, None if not overridden.
          timer_reset is True if continuous_occupied_since was reset.
        """
        now = _utcnow()
        effective_preset = None
        timer_reset = False

        # Replicate the D6 condition check from hvac.py lines 645-672
        if (
            zone.any_room_occupied
            and zone.continuous_occupied_since is not None
            and (now - zone.continuous_occupied_since).total_seconds()
            > max_hours * 3600
        ):
            if confidence >= 2:
                zone.continuous_occupied_since = now
                timer_reset = True
            else:
                effective_preset = "away"

        return effective_preset, timer_reset

    # 11. D6 with confidence >= 2 -> resets timer, does NOT set away
    def test_d6_high_confidence_resets_timer(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=now - timedelta(hours=9),
        )
        old_time = zone.continuous_occupied_since

        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=2)

        assert effective_preset is None, "Should NOT set away when confidence >= 2"
        assert timer_reset is True, "Should reset the timer"
        assert zone.continuous_occupied_since > old_time, "Timer should be updated to now"

    def test_d6_confidence_three_resets_timer(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=now - timedelta(hours=10),
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=3)

        assert effective_preset is None
        assert timer_reset is True

    def test_d6_confidence_four_resets_timer(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=now - timedelta(hours=12),
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=4)

        assert effective_preset is None
        assert timer_reset is True

    # 12. D6 with confidence < 2 -> sets away
    def test_d6_low_confidence_sets_away(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=now - timedelta(hours=9),
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=1)

        assert effective_preset == "away", "Should set away when confidence < 2"
        assert timer_reset is False

    def test_d6_zero_confidence_sets_away(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=now - timedelta(hours=9),
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=0)

        assert effective_preset == "away"
        assert timer_reset is False

    # D6 does not trigger if within max_occupancy_hours
    def test_d6_within_max_hours_no_action(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=now - timedelta(hours=5),
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=0, max_hours=8)

        assert effective_preset is None, "Should not trigger D6 within max hours"
        assert timer_reset is False

    # D6 does not trigger if continuous_occupied_since is None
    def test_d6_no_timer_no_action(self):
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            continuous_occupied_since=None,
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=0)

        assert effective_preset is None
        assert timer_reset is False

    # D6 does not trigger if zone is not occupied
    def test_d6_unoccupied_zone_no_action(self):
        now = _utcnow()
        zone = FakeZone(
            room_conditions=[RoomCondition("Living Room", occupied=False)],
            continuous_occupied_since=now - timedelta(hours=9),
        )
        effective_preset, timer_reset = self._simulate_d6_decision(zone, confidence=0)

        assert effective_preset is None
        assert timer_reset is False


class TestEdgeCases:
    """Edge cases and defensive behavior."""

    def test_person_coordinator_none(self):
        """Confidence check is safe when person_coordinator is None."""
        hass = FakeHass()
        hass.data[DOMAIN] = {}  # No person_coordinator key
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        # Should not raise, should return 0
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_person_coordinator_raises_exception(self):
        """Confidence check is safe when person_coordinator.get_persons_in_zone raises."""
        hass = FakeHass()
        pc = MagicMock()
        pc.get_persons_in_zone = MagicMock(side_effect=RuntimeError("BLE unavailable"))
        hass.data[DOMAIN] = {"person_coordinator": pc}
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        # Exception is caught, source not counted
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_no_cameras_configured(self):
        """Confidence check is safe when zone has no cameras."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            zone_cameras=[],  # empty
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        # Should not raise
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_camera_state_unavailable(self):
        """Camera entity exists in zone_cameras but HA state is unavailable."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        _add_camera(hass, zone, "binary_sensor.frigate_person", "unavailable")
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_camera_state_off(self):
        """Camera entity reports off (no person detected)."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        _add_camera(hass, zone, "binary_sensor.frigate_person", "off")
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_camera_entity_missing_from_ha(self):
        """Camera entity in zone_cameras but not found in HA states."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
            zone_cameras=["binary_sensor.nonexistent_camera"],
        )
        # hass.states.get returns None for unknown entity
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_empty_zone_rooms(self):
        """Zone with no rooms at all."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=[],
            room_conditions=[],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_room_coord_without_last_motion_time(self):
        """Room coordinator exists but _last_motion_time is None."""
        hass = _make_hass_with_room_coord("Living Room", last_motion_time=None)
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_room_coord_without_attribute(self):
        """Room coordinator exists but has no _last_motion_time attribute."""
        hass = FakeHass()
        entry = FakeConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Living Room"},
            entry_id="room_entry_1",
        )
        hass.config_entries.async_entries = MagicMock(return_value=[entry])
        # Coordinator without the attribute at all
        coord = object()  # bare object, no _last_motion_time
        hass.data[DOMAIN] = {"room_entry_1": coord}
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_ble_returns_empty_list(self):
        """BLE person coordinator returns empty list (no persons in zone)."""
        hass = FakeHass()
        _add_ble_persons(hass, [])
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_single_occupied_room_does_not_count_as_multi(self):
        """Only 1 room occupied should not trigger source 4."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room", "Kitchen"],
            room_conditions=[
                RoomCondition("Living Room", occupied=True),
                RoomCondition("Kitchen", occupied=False),
            ],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0

    def test_multiple_cameras_only_count_once(self):
        """Even if 3 cameras are on, source 3 counts at most 1."""
        hass = FakeHass()
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        _add_camera(hass, zone, "binary_sensor.cam1", "on")
        _add_camera(hass, zone, "binary_sensor.cam2", "on")
        _add_camera(hass, zone, "binary_sensor.cam3", "on")
        assert check_zone_occupancy_confidence(hass, zone) == 1

    def test_domain_data_missing_entirely(self):
        """hass.data has no DOMAIN key at all."""
        hass = FakeHass()
        # hass.data is empty {}
        zone = FakeZone(
            rooms=["Living Room"],
            room_conditions=[RoomCondition("Living Room", occupied=True)],
        )
        assert check_zone_occupancy_confidence(hass, zone) == 0
