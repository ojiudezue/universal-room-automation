"""EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1 — arbitrage release vs
fill-priority.

Live 2026-09-28: when grid charging ends, the arbitrage release turns the car
on. If the battery is still below the fill-priority target in a daylight
off-peak window, fill-priority turns it back off (one-tick flap). Fill-priority
only claims chargers that are ON, and arbitrage kept the car OFF, so a plain
membership check cannot see the hold. The release hands the car to
fill-priority instead. Drives the REAL controller methods.
"""
import datetime as _dt
import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# Mock homeassistant — mirror test_evse_offpeak_fill_release.py bootstrap.
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
        "utcnow": _dt.datetime.utcnow,
        "now": _dt.datetime.now,
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

_cc = sys.modules.get("custom_components") or types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name) or types.ModuleType(_ura_name)
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = _ura_name
sys.modules[_ura_name] = _ura

if f"{_ura_name}.const" not in sys.modules:
    _const_spec = importlib.util.spec_from_file_location(
        f"{_ura_name}.const", os.path.join(_ura_path, "const.py"),
    )
    _const_mod = importlib.util.module_from_spec(_const_spec)
    sys.modules[f"{_ura_name}.const"] = _const_mod
    _const_spec.loader.exec_module(_const_mod)
    _ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name) or types.ModuleType(_dc_name)
_dc.__path__ = [_dc_path]
_dc.__package__ = _dc_name
sys.modules[_dc_name] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_tou", "energy_pool"):
    _full_name = f"{_dc_name}.{_submod_name}"
    if _full_name in sys.modules:
        continue
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
)




def _make_ev(on=True):
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if on else "off")
    hass.set_state("sensor.garage_a_power_minute_average", "7000.0" if on else "0")
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


def _turn_ons(actions):
    return [
        a for a in actions
        if a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
    ]


def _grid_charge_holds_car(ev, hass):
    """Grid charging starts: arbitrage breaker pause turns the car OFF."""
    actions = ev.determine_arbitrage_actions(
        arbitrage_charging=True, tou_period="off_peak", pause_reason="breaker",
    )
    assert any(a["service"] == "switch.turn_off" for a in actions)
    assert "garage_a" in ev._paused_by_arbitrage
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power_minute_average", "0")


def _fill_priority_tick(ev, soc, is_daylight=True, tou="off_peak"):
    return ev.determine_fill_priority_actions(
        soc=soc, remaining_forecast_kwh=18.0, tou_period=tou,
        soc_threshold=80, excess_solar_kwh_threshold=5.0,
        is_daylight=is_daylight,
    )


def _release(ev):
    return ev.determine_arbitrage_actions(
        arbitrage_charging=False, tou_period="off_peak", grid_charge_on=False,
    )


class TestArbitrageReleaseRespectsFillPriority:
    """Grid charge ends at SOC 75 < fill target 80, daylight off-peak."""

    def test_release_below_fill_target_does_not_turn_car_on(self):
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        # Fill-priority evaluates while arbitrage keeps the car OFF: it wants
        # a hold (SOC 75 < 80, daylight) but does not claim an OFF charger.
        fp = _fill_priority_tick(ev, soc=75.0)
        assert fp == []
        assert "garage_a" not in ev._paused_by_fill_priority
        # Grid charging ends -> arbitrage release.
        actions = _release(ev)
        assert _turn_ons(actions) == [], (
            "arbitrage release turned the car on while fill-priority wants "
            "the battery filled first (one-tick flap)"
        )
        assert "garage_a" not in ev._paused_by_arbitrage
        assert "garage_a" in ev._paused_by_fill_priority, (
            "car must be handed to fill-priority so ensure-on does not "
            "turn it on next tick"
        )

    def test_next_tick_ensure_on_does_not_flap_and_fill_target_resumes(self):
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        _fill_priority_tick(ev, soc=75.0)
        assert _turn_ons(_release(ev)) == []
        # Next tick: off-peak ensure-on must defer to the fill-priority owner.
        ens = ev.determine_actions("off_peak", grid_charge_on=False)
        assert _turn_ons(ens) == []
        # Still below target: fill-priority keeps holding, no turn_on.
        assert _turn_ons(_fill_priority_tick(ev, soc=77.0)) == []
        assert "garage_a" in ev._paused_by_fill_priority
        # Battery reaches the fill target: fill-priority resumes the car.
        resumed = _fill_priority_tick(ev, soc=80.0)
        assert len(_turn_ons(resumed)) == 1
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_release_turns_car_on_when_fill_priority_not_holding(self):
        """SOC at/above the fill target -> release still turns the car on."""
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        _fill_priority_tick(ev, soc=85.0)
        actions = _release(ev)
        assert len(_turn_ons(actions)) == 1
        assert "garage_a" not in ev._paused_by_fill_priority

    def test_release_turns_car_on_at_night_fill_priority_inert(self):
        """Night off-peak: fill-priority inert -> verdict reset -> car on."""
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        _fill_priority_tick(ev, soc=75.0, is_daylight=True)
        _fill_priority_tick(ev, soc=75.0, is_daylight=False)
        assert len(_turn_ons(_release(ev))) == 1

    def test_release_turns_car_on_when_fill_priority_toggle_off(self):
        """Excess-solar toggle OFF -> release_all_fill_priority resets it."""
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        _fill_priority_tick(ev, soc=75.0)
        ev.release_all_fill_priority()
        assert len(_turn_ons(_release(ev))) == 1

    def test_release_respects_existing_fill_priority_membership(self):
        """Car already in the fill-priority set -> release leaves it paused."""
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        ev._paused_by_fill_priority.add("garage_a")
        assert _turn_ons(_release(ev)) == []
        assert "garage_a" in ev._paused_by_fill_priority

    def test_handed_off_car_manual_turn_on_is_honoured(self):
        """Owner turns the car on by hand after the hand-off: fill-priority
        treats it as a manual override (not re-paused forever)."""
        ev, hass = _make_ev(on=True)
        _grid_charge_holds_car(ev, hass)
        _fill_priority_tick(ev, soc=75.0)
        _release(ev)
        # Age the dispatch past the grace window, then the owner turns it on.
        ev._pause_dispatch_ts["garage_a"] -= 10_000
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "7000.0")
        actions = _fill_priority_tick(ev, soc=75.0)
        assert not any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" not in ev._paused_by_fill_priority
