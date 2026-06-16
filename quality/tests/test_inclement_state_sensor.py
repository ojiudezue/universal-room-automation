"""Unit guard for the v5.5.1 D6 InclementStateSensor.

This sensor re-surfaces the inclement-scoped subset of the Energy
Coordinator's ``battery_status`` dict on its own entity
(``sensor.ura_inclement_state``) so it can be dashboarded without the full
battery payload that rides on EnergyBatteryStrategySensor.

The test extracts the REAL ``native_value`` + ``extra_state_attributes``
bodies from sensor.py source and drives them (Bug Class #44 fixture
authority), so a future refactor that breaks the None-guards or leaks
non-inclement battery keys fails loudly. It does NOT touch the inclement
decision logic — observability-only.
"""

from __future__ import annotations

import os
import logging
from unittest.mock import MagicMock

import pytest

_SENSOR_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "sensor.py",
)
_DOMAIN = "universal_room_automation"

# Keys the sensor MUST surface, and battery keys it MUST NOT leak.
_INCLEMENT_KEYS = {
    "storm_forecast",
    "inclement_hold_depth",
    "inclement_source",
    "active_alert_event",
    "inclement_gated_out_events",
    "inclement_expires_at",
    "inclement_grid_precharge",
    "inclement_reserve_floor",
    "inclement_reason",
    "inclement_solar_horizon",
}
_NON_INCLEMENT_BATTERY_KEYS = {"mode", "soc", "reserve_soc"}


def _extract_methods():
    """Extract native_value + extra_state_attributes from InclementStateSensor."""
    with open(_SENSOR_PY, "r") as fh:
        src = fh.read()
    cls_at = src.index("class InclementStateSensor(")
    cls_end = src.index("\nclass ", cls_at + 1)
    nv_def = src.index("    def native_value(", cls_at)
    nv_end = src.index("\n    @property", nv_def)
    nv_src = src[nv_def:nv_end]
    esa_def = src.index("    def extra_state_attributes(", cls_at)
    esa_src = src[esa_def:cls_end]

    def _dedent(s: str) -> str:
        return "\n".join(l[4:] if len(l) >= 4 else l for l in s.splitlines()) + "\n"

    g: dict = {"DOMAIN": _DOMAIN, "_LOGGER": logging.getLogger("test.inclement")}
    exec(compile(_dedent(nv_src), "<native_value>", "exec"), g)
    exec(compile(_dedent(esa_src), "<extra_state_attributes>", "exec"), g)
    return g["native_value"], g["extra_state_attributes"]


def _fake_self(battery_status):
    obj = MagicMock()
    energy = MagicMock()
    energy.battery_status = battery_status
    manager = MagicMock()
    manager.coordinators = {"energy": energy}
    obj.hass.data = {_DOMAIN: {"coordinator_manager": manager}}
    return obj


def _fake_self_no_manager():
    obj = MagicMock()
    obj.hass.data = {_DOMAIN: {}}
    return obj


def _fake_self_no_energy():
    obj = MagicMock()
    manager = MagicMock()
    manager.coordinators = {}
    obj.hass.data = {_DOMAIN: {"coordinator_manager": manager}}
    return obj


_STUB_STATUS = {
    # non-inclement battery keys — must NOT leak into attributes
    "mode": "hold",
    "soc": 62,
    "reserve_soc": 30,
    # inclement subset
    "inclement_tier": "watch",
    "storm_forecast": {"severity": "watch"},
    "inclement_hold_depth": 0.15,
    "inclement_source": "nws_alert",
    "active_alert_event": "Severe Thunderstorm Watch",
    "inclement_gated_out_events": ["Frost Advisory"],
    "inclement_expires_at": "2026-06-15T22:00:00+00:00",
    "inclement_grid_precharge": True,
    "inclement_reserve_floor": 50,
    "inclement_reason": "active NWS watch within solar horizon",
    "inclement_solar_horizon": {"hours": 6},
}


def test_native_value_returns_inclement_tier():
    native_value, _ = _extract_methods()
    obj = _fake_self(_STUB_STATUS)
    assert native_value(obj) == "watch"


def test_native_value_defaults_to_none_when_key_absent():
    native_value, _ = _extract_methods()
    obj = _fake_self({"mode": "hold"})
    assert native_value(obj) == "none"


def test_native_value_unknown_when_manager_missing():
    native_value, _ = _extract_methods()
    assert native_value(_fake_self_no_manager()) == "unknown"


def test_native_value_unknown_when_energy_missing():
    native_value, _ = _extract_methods()
    assert native_value(_fake_self_no_energy()) == "unknown"


def test_attributes_return_inclement_subset():
    _, esa = _extract_methods()
    attrs = esa(_fake_self(_STUB_STATUS))
    assert set(attrs.keys()) == _INCLEMENT_KEYS
    assert attrs["inclement_source"] == "nws_alert"
    assert attrs["storm_forecast"] == {"severity": "watch"}
    assert attrs["inclement_solar_horizon"] == {"hours": 6}


def test_attributes_exclude_non_inclement_battery_keys():
    _, esa = _extract_methods()
    attrs = esa(_fake_self(_STUB_STATUS))
    for key in _NON_INCLEMENT_BATTERY_KEYS:
        assert key not in attrs


def test_attributes_missing_keys_never_raise():
    _, esa = _extract_methods()
    attrs = esa(_fake_self({}))  # battery_status empty
    assert set(attrs.keys()) == _INCLEMENT_KEYS
    assert all(v is None for v in attrs.values())


def test_attributes_empty_when_manager_missing():
    _, esa = _extract_methods()
    assert esa(_fake_self_no_manager()) == {}


def test_attributes_empty_when_energy_missing():
    _, esa = _extract_methods()
    assert esa(_fake_self_no_energy()) == {}
