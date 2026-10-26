"""COVERAGE-EVENING-ATTRIBUTION-DRIFT-1: coverage reads TOTAL consumption.

EnergyCoverageDeltaSensor must compute unattributed = TOTAL house
consumption - attributed. The shared CONF_WHOLE_HOUSE_ENERGY_SENSORS field
is live-configured to the Envoy NET sensor (cost wants NET), so coverage
prefers the Energy Coordinator's resolved total entity
(``EnergyCoordinator._entity_lifetime_consumption``) and falls back to the
shared field when EC cannot supply it.

Drives the real ``native_value`` / ``extra_state_attributes`` /
``_get_whole_house_energy`` path; only hass/entry are faked. Oracles are
hand-derived from the distinct NET vs TOTAL counter increments below.
"""
import importlib
import os
import sys
from types import SimpleNamespace

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_agg = importlib.import_module(
    "custom_components.universal_room_automation.aggregation"
)
from homeassistant.core import State  # noqa: E402

NET = "sensor.envoy_1_lifetime_net_energy_consumption"
TOTAL = "sensor.envoy_1_lifetime_energy_consumption"
DOMAIN = _agg.DOMAIN


class _States:
    def __init__(self):
        self._s: dict[str, State] = {}

    def set_kwh(self, eid, kwh):
        self._s[eid] = State(eid, str(kwh), {"unit_of_measurement": "kWh"})

    def get(self, eid):
        return self._s.get(eid)


def _hass(states, ec):
    data = {}
    if ec is not None:
        data[DOMAIN] = {
            "coordinator_manager": SimpleNamespace(coordinators={"energy": ec})
        }
    return SimpleNamespace(states=states, data=data)


def _entry():
    return SimpleNamespace(
        options={_agg.CONF_WHOLE_HOUSE_ENERGY_SENSORS: [NET]}, data={},
    )


def _coverage(hass, attributed=4.0):
    s = object.__new__(_agg.EnergyCoverageDeltaSensor)
    s.hass = hass
    s.entry = _entry()
    s._tier_baselines = {}
    s._whole_house_scope = "unknown"
    s._whole_house_source = "unknown"
    s._scope_mismatch_warning = ""
    s._last_reclassify_date = s._today_local()
    s._post_restart_window = False
    s._get_rooms_total_energy = lambda: attributed
    s._get_zones_total_energy = lambda: 0.0
    s._get_house_devices_total_energy = lambda: 0.0
    return s


def _seed_and_advance(states, sensor):
    # Lifetime counters (> 1000 kWh -> today_derived; first read anchors).
    states.set_kwh(NET, 12928.0)
    states.set_kwh(TOTAL, 28641.0)
    assert sensor.native_value == -4.0  # both anchored at 0 today
    # Sunny afternoon: house used 10 kWh TOTAL, only 3 kWh NET from grid.
    states.set_kwh(NET, 12931.0)
    states.set_kwh(TOTAL, 28651.0)


def test_ec_total_configured_coverage_uses_total_not_net():
    states = _States()
    ec = SimpleNamespace(_entity_lifetime_consumption=TOTAL)
    sensor = _coverage(_hass(states, ec))
    _seed_and_advance(states, sensor)
    # TOTAL: 10 - 4 = 6.  (NET would give 3 - 4 = -1, the drift bug.)
    assert sensor.native_value == 6.0
    attrs = sensor.extra_state_attributes
    assert attrs["whole_house_source"] == "ec_total"
    assert attrs["whole_house"] == 10.0


def test_ec_absent_falls_back_to_whole_house_energy_sensors():
    states = _States()
    sensor = _coverage(_hass(states, None))
    _seed_and_advance(states, sensor)
    assert sensor.native_value == -1.0
    assert sensor.extra_state_attributes["whole_house_source"] == (
        "whole_house_energy_sensors")


def test_ec_without_total_entity_falls_back():
    states = _States()
    ec = SimpleNamespace(_entity_lifetime_consumption=None)
    sensor = _coverage(_hass(states, ec))
    _seed_and_advance(states, sensor)
    assert sensor.native_value == -1.0


def test_ec_total_entity_missing_from_state_machine_falls_back():
    states = _States()
    ec = SimpleNamespace(
        _entity_lifetime_consumption="sensor.envoy_1_does_not_exist")
    sensor = _coverage(_hass(states, ec))
    _seed_and_advance(states, sensor)
    assert sensor.native_value == -1.0
    assert sensor.extra_state_attributes["whole_house_source"] == (
        "whole_house_energy_sensors")


def test_ec_total_unavailable_stays_on_total_no_data():
    """An existing-but-unavailable total entity must NOT swap to NET."""
    states = _States()
    ec = SimpleNamespace(_entity_lifetime_consumption=TOTAL)
    sensor = _coverage(_hass(states, ec))
    states.set_kwh(NET, 12928.0)
    states._s[TOTAL] = State(TOTAL, "unavailable", {})
    assert sensor.native_value is None
    assert sensor.extra_state_attributes["whole_house_source"] == "ec_total"


def test_cost_sensor_reads_ec_cost_today_not_counter(monkeypatch):
    """AUDIT_house_sensors_correctness_2026_10_25 H10: the cost sensor no
    longer multiplies the (lifetime) NET counter by the rate; it mirrors the
    EC's realized cost_today."""
    states = _States()
    states.set_kwh(NET, 15346.0)
    states.set_kwh(TOTAL, 10.0)
    ec = SimpleNamespace(_entity_lifetime_consumption=TOTAL, cost_today=4.75)
    cost = object.__new__(_agg.WholeHouseCostTodaySensor)
    cost.hass = _hass(states, ec)
    cost.entry = _entry()
    monkeypatch.setattr(_agg, "_get_effective_rate_kwh", lambda h: (0.5, "t"))
    assert cost.native_value == pytest.approx(4.75)


def test_net_to_total_switch_publishes_no_data_then_total_baseline():
    """EC appears mid-run (boot / CM reload): the switch cycle is no-data,
    then TOTAL reads against its OWN baseline anchored at the switch."""
    states = _States()
    hass = _hass(states, None)
    sensor = _coverage(hass)
    states.set_kwh(NET, 12928.0)
    states.set_kwh(TOTAL, 28641.0)
    assert sensor.native_value == -4.0          # NET anchored
    states.set_kwh(NET, 12931.0)
    assert sensor.native_value == -1.0          # NET +3 - 4
    hass.data[DOMAIN] = {"coordinator_manager": SimpleNamespace(
        coordinators={"energy": SimpleNamespace(
            _entity_lifetime_consumption=TOTAL)})}
    assert sensor.native_value is None          # switch cycle: no data
    states.set_kwh(TOTAL, 28651.0)
    assert sensor.native_value == 6.0           # TOTAL +10 - 4, no jump
    assert sensor.extra_state_attributes["whole_house_source"] == "ec_total"


def test_total_to_net_switch_publishes_no_data():
    states = _States()
    hass = _hass(states, SimpleNamespace(_entity_lifetime_consumption=TOTAL))
    sensor = _coverage(hass)
    states.set_kwh(NET, 12928.0)
    states.set_kwh(TOTAL, 28641.0)
    assert sensor.native_value == -4.0
    hass.data.clear()                            # EC gone (reload)
    assert sensor.native_value is None
