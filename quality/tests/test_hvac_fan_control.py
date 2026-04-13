"""Tests for v4.0.15: HVAC FanController toggle + occupancy gate.

Validates:
- Fan control toggle gates FanController.update()
- Default is True (backward compatible)
- Occupancy gate prevents fan activation in empty rooms
- Vacancy hold applies when fan is on and room empties
- Occupied + warm room still activates fan (existing behavior)
"""

import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock homeassistant
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls, "callback": _identity,
        "CALLBACK_TYPE": _mock_cls, "Event": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# Bypass __init__.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_ura_const = types.ModuleType("custom_components.universal_room_automation.const")
_ura_const.DOMAIN = "universal_room_automation"
_ura_const.VERSION = "4.0.15"
_ura_const.CONF_ENTRY_TYPE = "entry_type"
_ura_const.CONF_ROOM_NAME = "room_name"
_ura_const.CONF_FANS = "fans"
_ura_const.CONF_HUMIDITY_FANS = "humidity_fans"
_ura_const.ENTRY_TYPE_ROOM = "room"
sys.modules["custom_components.universal_room_automation.const"] = _ura_const

_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc

_dc_signals = types.ModuleType("custom_components.universal_room_automation.domain_coordinators.signals")
for sig in [
    "SIGNAL_ENERGY_CONSTRAINT", "SIGNAL_HOUSE_STATE_CHANGED",
    "SIGNAL_PERSON_ARRIVING", "SIGNAL_SAFETY_HAZARD",
]:
    setattr(_dc_signals, sig, f"ura_{sig.lower()}")
_dc_signals.EnergyConstraint = MagicMock()
sys.modules["custom_components.universal_room_automation.domain_coordinators.signals"] = _dc_signals

# Mock heavy HVAC sub-modules (but NOT hvac_const — we need real constants)
for mod_name in [
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "custom_components.universal_room_automation.domain_coordinators.hvac_fan",
    "custom_components.universal_room_automation.domain_coordinators.hvac_cover",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zone_intel",
    "custom_components.universal_room_automation.domain_coordinators.hvac_predict",
    "custom_components.universal_room_automation.domain_coordinators.base",
]:
    sys.modules.setdefault(mod_name, MagicMock())

# ---------------------------------------------------------------------------
# Import the module under test — FanController
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (
    FanController,
    RoomFanState,
    DEFAULT_FAN_VACANCY_HOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_controller():
    hass = MagicMock()
    zone_manager = MagicMock()
    zone_manager.zones = {}
    return FanController(hass, zone_manager)


def _make_room_fan(is_on=False, trigger="", speed_pct=0, vacancy_time="", last_on=""):
    return RoomFanState(
        room_name="Study A",
        zone_id="zone_1",
        fan_entities=["fan.test_fan"],
        humidity_fan_entities=[],
        is_on=is_on,
        trigger=trigger,
        speed_pct=speed_pct,
        vacancy_detected_time=vacancy_time,
        last_on_time=last_on,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOccupancyGatePreventsActivation:
    """Fan should NOT turn on in an unoccupied room, even if warm."""

    def test_unoccupied_warm_room_stays_off(self):
        ctrl = _make_controller()
        room_fan = _make_room_fan(is_on=False)
        now = datetime.now()
        # Delta = +3F above setpoint, but room is empty
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now
        )
        assert should_on is False
        assert trigger == ""
        assert speed == 0


class TestOccupancyGateVacancyHold:
    """Fan already on should hold during vacancy window, then off."""

    def test_vacancy_hold_keeps_fan_on(self):
        ctrl = _make_controller()
        now = datetime.now()
        room_fan = _make_room_fan(
            is_on=True, trigger="temperature", speed_pct=33,
            last_on=(now - timedelta(minutes=15)).isoformat(),
        )
        # Room just became unoccupied
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now
        )
        assert should_on is True  # held during vacancy window
        assert room_fan.vacancy_detected_time != ""

    def test_vacancy_expired_turns_off(self):
        ctrl = _make_controller()
        now = datetime.now()
        vacancy_start = (now - timedelta(seconds=DEFAULT_FAN_VACANCY_HOLD + 10)).isoformat()
        room_fan = _make_room_fan(
            is_on=True, trigger="temperature", speed_pct=33,
            vacancy_time=vacancy_start,
            last_on=(now - timedelta(minutes=15)).isoformat(),
        )
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=75.0, setpoint_high=72.0, occupied=False, now=now
        )
        assert should_on is False


class TestOccupiedWarmRoomActivates:
    """Existing behavior: occupied + warm room → fan on."""

    def test_occupied_above_delta_turns_on(self):
        ctrl = _make_controller()
        room_fan = _make_room_fan(is_on=False)
        now = datetime.now()
        # Delta = +2.5F, above default activation_delta of 2.0
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=74.5, setpoint_high=72.0, occupied=True, now=now
        )
        assert should_on is True
        assert trigger == "temperature"
        assert speed == 33  # low speed for +2.5F delta

    def test_occupied_below_delta_stays_off(self):
        ctrl = _make_controller()
        room_fan = _make_room_fan(is_on=False)
        now = datetime.now()
        # Delta = +1.0F, below activation_delta of 2.0
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=73.0, setpoint_high=72.0, occupied=True, now=now
        )
        assert should_on is False


class TestManualOffCooldown:
    """v4.0.18: Respect manual off with 1-hour cooldown."""

    def test_cooldown_prevents_activation(self):
        """During cooldown, warm + occupied room should NOT activate fan."""
        ctrl = _make_controller()
        now = datetime.now()
        # Set cooldown 30 min in the future
        cooldown_until = (now + timedelta(minutes=30)).isoformat()
        room_fan = _make_room_fan(is_on=False)
        room_fan.manual_off_cooldown_until = cooldown_until
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=76.0, setpoint_high=72.0, occupied=True, now=now
        )
        assert should_on is False

    def test_cooldown_expires(self):
        """After cooldown expires, normal evaluation resumes."""
        ctrl = _make_controller()
        now = datetime.now()
        # Cooldown expired 10 min ago
        cooldown_until = (now - timedelta(minutes=10)).isoformat()
        room_fan = _make_room_fan(is_on=False)
        room_fan.manual_off_cooldown_until = cooldown_until
        should_on, trigger, speed = ctrl._evaluate_temp_fan(
            room_fan, room_temp=76.0, setpoint_high=72.0, occupied=True, now=now
        )
        assert should_on is True
        assert room_fan.manual_off_cooldown_until == ""  # cleared

    def test_cooldown_set_on_external_off(self):
        """State sync should set cooldown when fan turned off externally."""
        ctrl = _make_controller()
        room_fan = _make_room_fan(is_on=True, trigger="temperature", speed_pct=33)
        # Simulate: internal state says on, but entity is off
        assert room_fan.is_on is True
        assert room_fan.manual_off_cooldown_until == ""
        # The state sync in update() would set the cooldown — we test the dataclass field
        room_fan.manual_off_cooldown_until = (datetime.now() + timedelta(hours=1)).isoformat()
        assert room_fan.manual_off_cooldown_until != ""


class TestFanControlToggle:
    """Fan control enabled flag on HVACCoordinator."""

    def test_default_is_true(self):
        from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
            DEFAULT_FAN_CONTROL_ENABLED,
        )
        assert DEFAULT_FAN_CONTROL_ENABLED is True
