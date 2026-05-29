"""v4.7.6 D2 — Fill-priority pause (primary rule).

Drives `EVChargerController.determine_fill_priority_actions` and the
SmartPlugController mirror directly with mocked state.
"""
import pytest
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

# Mock homeassistant — mirror test_energy_evse.py shape
def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock
_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": __import__("datetime").datetime.utcnow,
        "now": __import__("datetime").datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_pool"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
    SmartPlugController,
)


def _make_ev(garage_a_on=True, garage_a_power=7000.0):
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if garage_a_on else "off")
    hass.set_state("sensor.garage_a_power_minute_average", str(garage_a_power))
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    evse_config = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
        },
    }
    return EVChargerController(hass, evse_config=evse_config), hass


def _make_plug(plug_on=True, plug_id="switch.moes_plug_garage_a"):
    hass = MockHass()
    hass.set_state(plug_id, "on" if plug_on else "off")
    sp = SmartPlugController(hass, plug_entities=[plug_id])
    return sp, hass, plug_id


# ---------------------------------------------------------------------------
# Pause / resume cases
# ---------------------------------------------------------------------------

class TestFillPriorityPause:
    def test_fill_priority_pause_off_peak_low_soc_healthy_solar(self):
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=51.0,
            remaining_forecast_kwh=18.0,
            tou_period="off_peak",
            soc_threshold=80,
            excess_solar_kwh_threshold=5.0,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" in ev._paused_by_fill_priority
        # solar_ok cached
        assert ev._fill_priority_solar_ok is True

    def test_fill_priority_resume_at_target_soc(self):
        ev, hass = _make_ev()
        # Pause first
        ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        hass.set_state("switch.garage_a", "off")
        actions = ev.determine_fill_priority_actions(
            soc=82.0, remaining_forecast_kwh=10.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        assert any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_fill_priority_resume_on_forecast_decay(self):
        ev, hass = _make_ev()
        ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        hass.set_state("switch.garage_a", "off")
        # remaining drops below threshold - safety_margin
        actions = ev.determine_fill_priority_actions(
            soc=52.0,
            remaining_forecast_kwh=2.0,    # 2.0 < (5.0 - 1.0) = 4.0
            tou_period="off_peak",
            soc_threshold=80,
            excess_solar_kwh_threshold=5.0,
            safety_margin_kwh=1.0,
        )
        assert any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_fill_priority_bypassed_during_peak(self):
        ev, hass = _make_ev()
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        # No actions — TOU pause is canonical during peak
        assert len(actions) == 0
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_fill_priority_idempotent_repause(self):
        ev, hass = _make_ev()
        for _ in range(3):
            actions = ev.determine_fill_priority_actions(
                soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
                soc_threshold=80, excess_solar_kwh_threshold=5.0,
            )
            assert any(a["service"] == "switch.turn_off" for a in actions)

    def test_fill_priority_defers_to_excess_solar(self):
        ev, hass = _make_ev()
        ev._excess_solar_active.add("garage_a")
        # Even though conditions would normally pause (SOC 51 < 80),
        # excess-solar membership takes precedence (logged + skipped).
        actions = ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        # No new pause dispatched for garage_a
        assert "garage_a" not in ev._paused_by_fill_priority


class TestFillPrioritySmartPlugParity:
    def test_fill_priority_smart_plug_parity(self):
        sp, hass, plug_id = _make_plug()
        actions = sp.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert plug_id in sp._paused_by_fill_priority


class TestFillPriorityResumeGating:
    def test_resume_blocked_when_drain_holds(self):
        ev, hass = _make_ev()
        ev.determine_fill_priority_actions(
            soc=51.0, remaining_forecast_kwh=18.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        ev._paused_by_battery_drain.add("garage_a")
        hass.set_state("switch.garage_a", "off")
        actions = ev.determine_fill_priority_actions(
            soc=82.0, remaining_forecast_kwh=10.0, tou_period="off_peak",
            soc_threshold=80, excess_solar_kwh_threshold=5.0,
        )
        # No turn_on; fill-priority discards self silently
        assert not any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" not in ev._paused_by_fill_priority
