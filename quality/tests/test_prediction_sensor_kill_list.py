"""Behavioral tests for the prediction-sensor kill-list cycle (2026-06).

Three deliverables:

D1. ``PeakOccupancyTimeSensor`` removed (superseded by
    ``<room>_bayesian_occupancy_pattern``).
D2-a. ``NextOccupancyInSensor`` removed (per-minute countdown was
      ~50k recorder writes/day; now derived client-side from the
      timestamp sensor).
D2-b. ``NextOccupancyTimeSensor`` refit:
      ``device_class=timestamp`` + tz-aware datetime native_value +
      only-on-change ``async_write_ha_state`` via overridden
      ``_handle_coordinator_update``.

Plus a registry-cleanup test that the v4.7.22 fan-recheck precedent is
reused in ``__init__.py`` to remove the two orphaned per-room
unique_ids on first integration startup post-upgrade.
"""

from __future__ import annotations

import datetime as _dt
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_REL = Path("custom_components/universal_room_automation")


# ---------------------------------------------------------------------------
# Static source checks (D1 + D2-a removal — no HA bootstrap required).
# ---------------------------------------------------------------------------


def test_sensor_source_removes_killed_classes():
    """The two killed sensor classes must not exist anywhere in sensor.py."""
    src = (ROOT_DIR / ROOT_REL / "sensor.py").read_text()
    assert "class PeakOccupancyTimeSensor" not in src, (
        "PeakOccupancyTimeSensor still present (D1 violation)"
    )
    assert "class NextOccupancyInSensor" not in src, (
        "NextOccupancyInSensor still present (D2-a violation)"
    )


def test_sensor_source_drops_killed_classes_from_setup_entry():
    """The two killed classes must not be instantiated in async_setup_entry."""
    src = (ROOT_DIR / ROOT_REL / "sensor.py").read_text()
    assert "PeakOccupancyTimeSensor(coordinator)" not in src
    assert "NextOccupancyInSensor(coordinator)" not in src
    # NextOccupancyTimeSensor MUST still be registered.
    assert "NextOccupancyTimeSensor(coordinator)" in src, (
        "NextOccupancyTimeSensor unexpectedly dropped from async_setup_entry"
    )


def test_sensor_source_drops_unused_state_imports():
    """STATE_NEXT_OCCUPANCY_IN and STATE_PEAK_OCCUPANCY_TIME are unused after
    the kill-list; keeping them imported would mask future regressions."""
    src = (ROOT_DIR / ROOT_REL / "sensor.py").read_text()
    assert "STATE_NEXT_OCCUPANCY_IN" not in src
    assert "STATE_PEAK_OCCUPANCY_TIME" not in src


# ---------------------------------------------------------------------------
# Registry-cleanup migration (mirrors v4.7.22 fan-recheck precedent).
# ---------------------------------------------------------------------------


def test_init_carries_prediction_kill_list_cleanup_block():
    """__init__.py must contain the run-once orphan-cleanup block for the two
    deleted per-room unique_ids, gated on the
    ``prediction_sensor_kill_list_cleanup_done`` flag, using the precedent
    pattern (``ent_reg.async_remove`` keyed by ``async_get_entity_id``)."""
    src = (ROOT_DIR / ROOT_REL / "__init__.py").read_text()
    assert "prediction_sensor_kill_list_cleanup_done" in src
    assert "next_occupancy_in" in src
    assert "peak_occupancy_time" in src
    # Routed through the precedent's removal API.
    assert "ent_reg.async_remove(eid)" in src
    # Must iterate ROOM entries (unique_ids are per-room).
    assert "ENTRY_TYPE_ROOM" in src


# ---------------------------------------------------------------------------
# Behavioral tests for the refit NextOccupancyTimeSensor (D2-b).
#
# We exercise the sensor in isolation by stubbing the small surface area it
# touches: CoordinatorEntity.__init__, device_info, async_write_ha_state.
# ---------------------------------------------------------------------------


@pytest.fixture
def _ha_stubs(monkeypatch):
    """Stub the homeassistant + integration imports just enough to import
    sensor.py's NextOccupancyTimeSensor without booting HA core."""
    # If the integration is already importable in this test session (e.g. via
    # conftest), just hand it back. Otherwise we cannot meaningfully exercise
    # the live class, so skip — the static checks above still cover the
    # removal contract.
    try:
        from custom_components.universal_room_automation import sensor as _s  # noqa: F401
    except Exception:
        pytest.skip(
            "HA stubs not present in test environment; static source checks "
            "above cover the kill-list contract."
        )
    return _s


def _fake_coordinator(mod, *, next_time, confidence=None, entry_id="room1"):
    """Build a minimal coordinator double for the sensor.

    Keys come from the module's actual STATE_* constants so a const rename
    fails here rather than silently testing dead keys.
    """
    coord = MagicMock()
    coord.entry.entry_id = entry_id
    coord.entry.data = {"room_name": "Test Room"}
    coord.last_update_success = True
    data = {}
    if next_time is not None:
        data[mod.STATE_NEXT_OCCUPANCY_TIME] = next_time
    if confidence is not None:
        data[mod.STATE_OCCUPANCY_CONFIDENCE] = confidence
    coord.data = data
    return coord


def _bare_sensor(mod, coord):
    """Instantiate the REAL NextOccupancyTimeSensor without running its
    environment-fragile constructor chain (CoordinatorEntity/UniversalRoomEntity
    __init__ depends on whichever HA mocks happen to be installed by sibling
    test files — the union varies with collection order). object.__new__ +
    explicit attrs keeps the PRODUCTION methods under test while making the
    test order-immune."""
    s = object.__new__(mod.NextOccupancyTimeSensor)
    s.coordinator = coord
    # Mirror the two sentinel attrs __init__ sets (asserted by the static
    # source check below so drift in __init__ fails loudly).
    s._last_written = object()
    s._last_confidence = object()
    s.async_write_ha_state = MagicMock()
    return s


def test_init_sets_change_sentinels_source_check():
    """_bare_sensor mirrors __init__'s sentinels; lock that contract."""
    full = (ROOT_DIR / ROOT_REL / "sensor.py").read_text()
    src = full[full.find("class NextOccupancyTimeSensor"):]
    src = src[:src.find("\nclass ", 1)]
    assert "self._last_written" in src and "self._last_confidence" in src


def test_next_occupancy_time_native_value_is_tz_aware(_ha_stubs):
    """native_value must return a tz-aware datetime; naive inputs are
    normalized to UTC (frontend ``device_class=timestamp`` requires tz)."""
    naive = _dt.datetime(2026, 6, 10, 7, 30, 0)  # no tzinfo
    coord = _fake_coordinator(_ha_stubs, next_time=naive)
    sensor = _bare_sensor(_ha_stubs, coord)
    value = sensor.native_value
    assert value is not None
    assert value.tzinfo is not None, "native_value must be tz-aware"


def test_next_occupancy_time_device_class_is_timestamp(_ha_stubs):
    """Frontend countdown rendering relies on device_class=timestamp."""
    from homeassistant.components.sensor import SensorDeviceClass
    from custom_components.universal_room_automation.sensor import (
        NextOccupancyTimeSensor,
    )

    assert NextOccupancyTimeSensor._attr_device_class == SensorDeviceClass.TIMESTAMP


def test_next_occupancy_time_writes_only_on_change(_ha_stubs):
    """``_handle_coordinator_update`` must suppress writes when neither the
    timestamp nor the confidence has changed since the last write."""
    t1 = _dt.datetime(2026, 6, 10, 7, 30, 0, tzinfo=_dt.timezone.utc)
    coord = _fake_coordinator(_ha_stubs, next_time=t1, confidence=0.8)
    sensor = _bare_sensor(_ha_stubs, coord)

    # First refresh: state transitions from sentinel → t1 ⇒ MUST write.
    sensor._handle_coordinator_update()
    assert sensor.async_write_ha_state.call_count == 1

    # Identical coordinator refresh ⇒ MUST NOT write again.
    sensor._handle_coordinator_update()
    sensor._handle_coordinator_update()
    assert sensor.async_write_ha_state.call_count == 1, (
        "duplicate refresh re-wrote state (per-cycle churn regression)"
    )

    # Prediction moves forward ⇒ write again.
    t2 = t1 + _dt.timedelta(minutes=15)
    coord.data[_ha_stubs.STATE_NEXT_OCCUPANCY_TIME] = t2
    sensor._handle_coordinator_update()
    assert sensor.async_write_ha_state.call_count == 2

    # Confidence change only ⇒ also a write (UI surfaces it as an attr).
    coord.data[_ha_stubs.STATE_OCCUPANCY_CONFIDENCE] = 0.6
    sensor._handle_coordinator_update()
    assert sensor.async_write_ha_state.call_count == 3
