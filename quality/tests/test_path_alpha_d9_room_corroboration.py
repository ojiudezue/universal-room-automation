"""PATH-ALPHA D9 (Gap B, 2026-08-16) — PersonPhoneLeftBehindSensor
room-occupancy corroboration.

Conservative direction: D9 can only make phone_left_behind fire LESS. Two
required drills (both directions):

  1. Camera-less-room occupant (BLE in a room whose room coordinator reports
     STATE_OCCUPIED) is NOT flagged left-behind — corroboration path
     suppresses.
  2. Genuinely-abandoned phone (BLE home, room dark, no occupancy, no
     camera sighting) is STILL flagged — pre-D9 behavior preserved.

Plus mutation drills (2 shapes each) on the D9 code path — the kill-switch
knob and the _is_room_occupied call.

Tests drive the real `PersonPhoneLeftBehindSensor.is_on` production path
(no mocks around the corroboration branch itself — mocks are only on the
HA plumbing / person_coordinator / transit_validator surfaces).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Import the sensor module with a minimal HA + integration stub graph.
# Follows the pattern of test_v4714_1_forgotten_phone_hotfix.py.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
BINARY_SENSOR_PATH = (
    REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "binary_sensor.py"
)


@pytest.fixture
def sensor_class(monkeypatch):
    """Load PersonPhoneLeftBehindSensor from source with minimal stubs."""
    # Stub homeassistant.* minimally
    def _make_module(name, **attrs):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        return mod

    _BinarySensorDeviceClass = MagicMock()
    _EntityCategory = MagicMock()

    class _DeviceInfo(dict):
        def __init__(self, **kw):
            super().__init__(**kw)

    class _RestoreEntity: ...
    class _BinarySensorEntity: ...

    def _callback(fn):
        return fn

    class _AddEntitiesCallback: ...

    # dt_util.now — controllable
    import datetime as _dt

    class _dt_util:
        _now = _dt.datetime(2026, 8, 16, 12, 0, 0)

        @classmethod
        def now(cls):
            return cls._now

        @staticmethod
        def parse_datetime(s):
            return None

    # Build stub tree
    ha_root = _make_module("homeassistant")
    ha_root.util = _make_module("homeassistant.util")
    ha_root.util.dt = _dt_util
    ha_root.components = _make_module("homeassistant.components")
    ha_root.components.binary_sensor = _make_module(
        "homeassistant.components.binary_sensor",
        BinarySensorDeviceClass=_BinarySensorDeviceClass,
        BinarySensorEntity=_BinarySensorEntity,
    )
    ha_root.config_entries = _make_module(
        "homeassistant.config_entries", ConfigEntry=object
    )
    ha_root.core = _make_module(
        "homeassistant.core", HomeAssistant=object, callback=_callback
    )
    ha_root.helpers = _make_module("homeassistant.helpers")
    ha_root.helpers.entity_platform = _make_module(
        "homeassistant.helpers.entity_platform",
        AddEntitiesCallback=_AddEntitiesCallback,
    )
    ha_root.helpers.restore_state = _make_module(
        "homeassistant.helpers.restore_state", RestoreEntity=_RestoreEntity
    )
    ha_root.helpers.entity = _make_module(
        "homeassistant.helpers.entity",
        DeviceInfo=_DeviceInfo,
        EntityCategory=_EntityCategory,
    )

    for n, m in [
        ("homeassistant", ha_root),
        ("homeassistant.util", ha_root.util),
        ("homeassistant.util.dt", _dt_util),
        ("homeassistant.components", ha_root.components),
        ("homeassistant.components.binary_sensor", ha_root.components.binary_sensor),
        ("homeassistant.config_entries", ha_root.config_entries),
        ("homeassistant.core", ha_root.core),
        ("homeassistant.helpers", ha_root.helpers),
        ("homeassistant.helpers.entity_platform", ha_root.helpers.entity_platform),
        ("homeassistant.helpers.restore_state", ha_root.helpers.restore_state),
        ("homeassistant.helpers.entity", ha_root.helpers.entity),
    ]:
        monkeypatch.setitem(sys.modules, n, m)

    # Stub the URA package + neighbors that binary_sensor.py imports at
    # top level. We only need the class definition; downstream imports
    # (aggregation, coordinator, entity, binary_sensor_control_attrs) are
    # not exercised by is_on so we stub them minimally.
    pkg = types.ModuleType("custom_components")
    pkg.__path__ = [str(REPO_ROOT / "custom_components")]
    monkeypatch.setitem(sys.modules, "custom_components", pkg)
    subpkg = types.ModuleType("custom_components.universal_room_automation")
    subpkg.__path__ = [
        str(REPO_ROOT / "custom_components" / "universal_room_automation")
    ]
    monkeypatch.setitem(
        sys.modules, "custom_components.universal_room_automation", subpkg
    )
    # Load real const.py so our knob is visible
    const_spec = importlib.util.spec_from_file_location(
        "custom_components.universal_room_automation.const",
        REPO_ROOT
        / "custom_components"
        / "universal_room_automation"
        / "const.py",
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    monkeypatch.setitem(
        sys.modules,
        "custom_components.universal_room_automation.const",
        const_mod,
    )
    const_spec.loader.exec_module(const_mod)

    # Stub the sibling modules binary_sensor imports
    for sibling in (
        "aggregation",
        "coordinator",
        "entity",
        "binary_sensor_control_attrs",
    ):
        stub = types.ModuleType(
            f"custom_components.universal_room_automation.{sibling}"
        )
        # Provide names used at import time
        stub.AggregationEntity = type("AggregationEntity", (), {})
        stub.UniversalRoomCoordinator = type("UniversalRoomCoordinator", (), {})
        stub.UniversalRoomEntity = type("UniversalRoomEntity", (), {})
        stub.build_control_attrs = lambda *a, **k: {}
        monkeypatch.setitem(
            sys.modules,
            f"custom_components.universal_room_automation.{sibling}",
            stub,
        )

    # Load the sensor module
    spec = importlib.util.spec_from_file_location(
        "custom_components.universal_room_automation.binary_sensor",
        BINARY_SENSOR_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules,
        "custom_components.universal_room_automation.binary_sensor",
        mod,
    )
    spec.loader.exec_module(mod)
    return mod.PersonPhoneLeftBehindSensor, const_mod


def _build_sensor(sensor_class_pair, ble_location, room_occupied):
    Cls, _const = sensor_class_pair
    sensor = Cls.__new__(Cls)
    sensor._person_id = "Ezinne"
    sensor.hass = MagicMock()

    person_coord = MagicMock()
    person_coord.data = {"Ezinne": {"location": ble_location}}
    person_coord._is_room_occupied = MagicMock(return_value=room_occupied)

    transit_validator = MagicMock()
    transit_validator.get_last_camera_sighting = MagicMock(return_value=None)

    census = MagicMock()
    census.last_result = MagicMock()
    census.last_result.house = MagicMock()
    census.last_result.house.total_persons = 0

    sensor.hass.data = {
        "universal_room_automation": {
            "person_coordinator": person_coord,
            "transit_validator": transit_validator,
            "census": census,
        }
    }
    return sensor, person_coord


def test_d9_camera_less_room_occupant_suppressed(sensor_class):
    """(1) BLE places person in Office; Office coordinator says occupied;
    sensor MUST NOT fire."""
    sensor, person_coord = _build_sensor(
        sensor_class, ble_location="Office", room_occupied=True
    )
    result = sensor.is_on
    assert result is False, (
        "D9 corroboration failed: room-occupied person was flagged "
        "left-behind (would trigger denominator exclusion)"
    )
    person_coord._is_room_occupied.assert_called_with("Office")


def test_d9_abandoned_phone_still_fires(sensor_class):
    """(2) BLE says home in Office, Office coordinator says NOT occupied,
    no camera sighting — pre-D9 fire semantics preserved."""
    sensor, _ = _build_sensor(
        sensor_class, ble_location="Office", room_occupied=False
    )
    result = sensor.is_on
    assert result is True, (
        "pre-D9 fire path broken: genuine abandoned phone must still be "
        "flagged"
    )


def test_d9_kill_switch_disables_corroboration(sensor_class, monkeypatch):
    """Neuter drill shape A: flipping the module knob to False MUST make
    a room-occupied person get flagged (pre-D9 behavior restored)."""
    _Cls, const_mod = sensor_class
    monkeypatch.setattr(
        const_mod, "PHONE_LEFT_BEHIND_ROOM_CORROBORATION_ENABLED", False
    )
    sensor, person_coord = _build_sensor(
        sensor_class, ble_location="Office", room_occupied=True
    )
    result = sensor.is_on
    assert result is True, (
        "kill-switch broken: knob=False must return pre-D9 behavior "
        "(fire even when room is occupied)"
    )


def test_d9_home_generic_location_does_not_corroborate(sensor_class):
    """Neuter drill shape B: BLE location == 'home' is not a room name,
    so corroboration MUST be skipped (fails safe — no room to check
    against). Sensor fires as pre-D9."""
    sensor, person_coord = _build_sensor(
        sensor_class, ble_location="home", room_occupied=True
    )
    result = sensor.is_on
    # 'home' is not a specific room name; corroboration guard skips.
    # Sensor falls through to pre-D9 camera-sighting check → no sighting
    # → fires.
    assert result is True
    person_coord._is_room_occupied.assert_not_called()
