"""EV-SENSOR-CLEANUP-1 (operator REUSE reversal 486cd1cd3) — behavioral tests
for the re-added per-bay EV charge-rate sensors.

`EnergyEVChargeRateGarageASensor` / `...GarageBSensor` re-expose each garage
EVSE bay's measured charge power (watts), sourced from the SAME per-bay power
`sensor.ura_ev_charging_status` already reads: ``energy.ev_status[<bay>]["power"]``.
The bay key is deterministic ("garage_a"/"garage_b" per DEFAULT_EVSE_ENTITIES),
so there is no evse_id->bay mapping ambiguity.

Each test drives the production `native_value` read path against a stubbed
coordinator manager. A mutation drill (change `_bay_key` or the `["power"]`
read) turns the value assertions RED.
"""
from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_sensor():
    try:
        sys.path.insert(0, os.path.join(_REPO, "custom_components"))
        from universal_room_automation import sensor as _sensor_mod  # noqa: PLC0415
        from universal_room_automation.const import DOMAIN  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"sensor module not importable: {e}")
    return _sensor_mod, DOMAIN


class _FakeManager:
    def __init__(self, ev_status):
        energy = type("E", (), {})()
        energy.ev_status = ev_status
        self.coordinators = {"energy": energy}


class _FakeHass:
    def __init__(self, domain, ev_status):
        self.data = {domain: {"coordinator_manager": _FakeManager(ev_status)}}


def _make(sensor_cls, domain, ev_status):
    s = sensor_cls.__new__(sensor_cls)
    s.hass = _FakeHass(domain, ev_status)
    return s


def test_garage_a_reads_its_own_bay_power():
    mod, DOMAIN = _load_sensor()
    ev_status = {
        "garage_a": {"power": 3300.4, "is_on": True, "charging": True},
        "garage_b": {"power": 7200.0, "is_on": True, "charging": True},
    }
    s = _make(mod.EnergyEVChargeRateGarageASensor, DOMAIN, ev_status)
    # Reads garage_a, NOT garage_b — proves the bay key is wired correctly.
    assert s.native_value == 3300.4


def test_garage_b_reads_its_own_bay_power():
    mod, DOMAIN = _load_sensor()
    ev_status = {
        "garage_a": {"power": 3300.4, "is_on": True, "charging": True},
        "garage_b": {"power": 7200.0, "is_on": True, "charging": True},
    }
    s = _make(mod.EnergyEVChargeRateGarageBSensor, DOMAIN, ev_status)
    assert s.native_value == 7200.0


def test_missing_bay_returns_none_safely():
    mod, DOMAIN = _load_sensor()
    s = _make(mod.EnergyEVChargeRateGarageASensor, DOMAIN, {"garage_b": {"power": 10.0}})
    assert s.native_value is None


def test_null_power_returns_none_not_zero():
    """A bay present but with power=None must read None, not 0 — None fails
    closed (no misleading 0 W charge rate)."""
    mod, DOMAIN = _load_sensor()
    s = _make(mod.EnergyEVChargeRateGarageASensor, DOMAIN, {"garage_a": {"power": None}})
    assert s.native_value is None


def test_non_numeric_power_returns_none():
    mod, DOMAIN = _load_sensor()
    s = _make(mod.EnergyEVChargeRateGarageASensor, DOMAIN, {"garage_a": {"power": "bad"}})
    assert s.native_value is None


def test_no_energy_coordinator_returns_none():
    mod, DOMAIN = _load_sensor()
    s = mod.EnergyEVChargeRateGarageASensor.__new__(mod.EnergyEVChargeRateGarageASensor)

    class _EmptyHass:
        data = {DOMAIN: {}}

    s.hass = _EmptyHass()
    assert s.native_value is None
