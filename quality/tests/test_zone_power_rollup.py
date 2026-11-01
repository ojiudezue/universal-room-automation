"""ZONE-LIVE-POWER-ROLLUP-1: zone power/energy include zone-level loads.

Drives the REAL ZoneTotalPowerSensor / ZoneEnergyTodaySensor /
ZoneCostPerHourSensor classes with a fake hass (config entries + states)
and fake room coordinators. Oracles are hand-computed literals.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.universal_room_automation import aggregation as agg
from custom_components.universal_room_automation.aggregation import (
    ZoneEnergyCostTodaySensor,
    ZoneCostPerHourSensor,
    ZoneEnergyTodaySensor,
    ZoneTotalPowerSensor,
)

ZONE = "upstairs"


class _States:
    def __init__(self, values: dict):
        self.values = values

    def get(self, eid):
        if eid not in self.values:
            return None
        val, unit = self.values[eid]
        return SimpleNamespace(
            entity_id=eid, state=str(val),
            attributes={"unit_of_measurement": unit},
        )


class _Entries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain=None):
        return list(self._entries)


def _zm_entry(zone_power=None, zone_energy=None):
    zone = {}
    if zone_power is not None:
        zone["zone_power_sensors"] = zone_power
    if zone_energy is not None:
        zone["zone_energy_sensors"] = zone_energy
    return SimpleNamespace(
        entry_id="zm",
        data={"entry_type": "zone_manager", "zones": {ZONE: zone}},
        options={},
    )


def _coord(power=0.0, energy=0.0, power_sensors=(), energy_sensors=()):
    entry = SimpleNamespace(
        entry_id="room",
        data={"zone": ZONE, "power_sensors": list(power_sensors),
              "energy_sensors": list(energy_sensors)},
        options={},
    )
    return SimpleNamespace(
        entry=entry,
        data={"power_current": power, "energy_today": energy},
    )


def _hass(states, entries):
    return SimpleNamespace(
        states=_States(states), config_entries=_Entries(entries), data={},
    )


def _make(cls, hass, coords):
    s = cls.__new__(cls)
    s.hass = hass
    s.zone = ZONE
    # Mimic only the attributes __init__ sets that native_value reads.
    if cls is ZoneEnergyTodaySensor:
        s._last_valid_value = None
        s._last_accepted_date = None
        s._zone_tier_baselines = {}
        s._zone_tier_reclassify_date = None
        s._contrib = {}
    s._get_zone_coordinators = lambda: coords
    return s


def test_const_keys_match_literals():
    # The fixture uses literal keys; pin them so a rename can't hollow it.
    assert agg.CONF_ZONE_POWER_SENSORS == "zone_power_sensors"
    assert agg.CONF_ZONE_ENERGY_SENSORS == "zone_energy_sensors"
    assert agg.STATE_POWER_CURRENT == "power_current"
    assert agg.STATE_ENERGY_TODAY == "energy_today"


# ---------------------------------------------------------------- power

def test_power_adds_zone_level_sensor():
    hass = _hass({"sensor.ac_z1_power": (2400, "W")},
                 [_zm_entry(zone_power=["sensor.ac_z1_power"])])
    s = _make(ZoneTotalPowerSensor, hass, [_coord(power=300.0)])
    assert s.native_value == 2700.0
    a = s.extra_state_attributes
    assert a["rooms_power_w"] == 300.0
    assert a["zone_level_power_w"] == 2400.0
    assert a["zone_level_sensors"] == ["sensor.ac_z1_power"]


def test_power_kw_normalised():
    hass = _hass({"sensor.ac_kw": (1.5, "kW")},
                 [_zm_entry(zone_power=["sensor.ac_kw"])])
    s = _make(ZoneTotalPowerSensor, hass, [_coord(power=100.0)])
    assert s.native_value == 1600.0


def test_power_skips_room_overlap():
    hass = _hass({"sensor.shared": (500, "W"), "sensor.ac": (1000, "W")},
                 [_zm_entry(zone_power=["sensor.shared", "sensor.ac"])])
    room = _coord(power=500.0, power_sensors=["sensor.shared"])
    s = _make(ZoneTotalPowerSensor, hass, [room])
    assert s.native_value == 1500.0
    assert s.extra_state_attributes["zone_level_skipped_room_overlap"] == [
        "sensor.shared"]


def test_power_unavailable_skipped_not_zeroed():
    hass = _hass({"sensor.dead": ("unavailable", "W"), "sensor.ac": (800, "W")},
                 [_zm_entry(zone_power=["sensor.dead", "sensor.ac"])])
    s = _make(ZoneTotalPowerSensor, hass, [_coord(power=200.0)])
    assert s.native_value == 1000.0
    assert s.extra_state_attributes["zone_level_unavailable"] == ["sensor.dead"]


def test_power_no_zone_config_is_rooms_only():
    hass = _hass({}, [_zm_entry()])
    s = _make(ZoneTotalPowerSensor, hass, [_coord(power=250.0), _coord(power=50.0)])
    assert s.native_value == 300.0


def test_power_other_zone_sensors_ignored():
    zm = _zm_entry(zone_power=["sensor.ac"])
    zm.data["zones"]["downstairs"] = {"zone_power_sensors": ["sensor.other"]}
    hass = _hass({"sensor.ac": (100, "W"), "sensor.other": (9999, "W")}, [zm])
    s = _make(ZoneTotalPowerSensor, hass, [_coord(power=0.0)])
    assert s.native_value == 100.0


# ---------------------------------------------------------- cost per hour

def test_cost_per_hour_includes_zone_level_power():
    hass = _hass({"sensor.ac": (2000, "W")}, [_zm_entry(zone_power=["sensor.ac"])])
    s = _make(ZoneCostPerHourSensor, hass, [_coord(power=0.0)])
    with patch.object(agg, "_get_effective_rate_kwh", return_value=(0.25, "t")):
        # 2.0 kW * 0.25 = 0.5 $/h; rooms 0 W alone would return None.
        assert s.native_value == 0.5


# ---------------------------------------------------------------- energy

def _at(day):
    return datetime(2026, 11, day, 12, 0, 0)


def test_energy_adds_today_native_zone_sensor():
    hass = _hass({"sensor.ac_today": (3.25, "kWh")},
                 [_zm_entry(zone_energy=["sensor.ac_today"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=1.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 4.25
    a = s.extra_state_attributes
    assert a["rooms_energy_kwh"] == 1.0
    assert a["zone_level_energy_kwh"] == 3.25


def test_energy_wh_normalised():
    hass = _hass({"sensor.ac_wh": (2500, "Wh")},
                 [_zm_entry(zone_energy=["sensor.ac_wh"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=0.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 2.5


def test_energy_lifetime_counter_is_today_delta():
    states = {"sensor.ac_total": (5000.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.ac_total"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=1.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 1.0  # first read anchors: 0 delta
        states["sensor.ac_total"] = (5002.5, "kWh")
        assert s.native_value == 3.5


def test_energy_overlap_skipped():
    hass = _hass({"sensor.circuit": (4.0, "kWh")},
                 [_zm_entry(zone_energy=["sensor.circuit"])])
    room = _coord(energy=4.0, energy_sensors=["sensor.circuit"])
    s = _make(ZoneEnergyTodaySensor, hass, [room])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 4.0
    assert s.extra_state_attributes["zone_level_skipped_room_overlap"] == [
        "sensor.circuit"]


def test_energy_overlap_legacy_singular_room_key():
    hass = _hass({"sensor.circuit": (4.0, "kWh")},
                 [_zm_entry(zone_energy=["sensor.circuit"])])
    room = _coord(energy=4.0)
    room.entry.data.pop("energy_sensors")
    room.entry.data["energy_sensor"] = "sensor.circuit"
    s = _make(ZoneEnergyTodaySensor, hass, [room])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 4.0


def test_energy_unavailable_skipped_and_held():
    states = {"sensor.ac_today": (3.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.ac_today"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=1.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 4.0
        states["sensor.ac_today"] = ("unavailable", "kWh")
        # Same day: drop is not accepted, last valid held.
        assert s.native_value == 4.0
        assert s.extra_state_attributes["zone_level_unavailable"] == [
            "sensor.ac_today"]


def test_energy_midnight_reset_lifetime_counter():
    states = {"sensor.ac_total": (5000.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.ac_total"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=0.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        s.native_value
        states["sensor.ac_total"] = (5010.0, "kWh")
        assert s.native_value == 10.0
    with patch.object(agg.dt_util, "now", return_value=_at(2)):
        # New day: re-anchors to 5012 -> 0, decrease accepted.
        states["sensor.ac_total"] = (5012.0, "kWh")
        assert s.native_value == 0.0
        states["sensor.ac_total"] = (5013.5, "kWh")
        assert s.native_value == 1.5


def test_energy_midnight_native_counter_reset_accepted():
    states = {"sensor.ac_today": (12.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.ac_today"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=0.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 12.0
    with patch.object(agg.dt_util, "now", return_value=_at(2)):
        states["sensor.ac_today"] = (0.25, "kWh")
        assert s.native_value == 0.25


def test_energy_native_above_threshold_flips_to_derived():
    states = {"sensor.young": (900.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.young"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=0.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        assert s.native_value == 900.0
        states["sensor.young"] = (1001.0, "kWh")
        # Flips to derived and re-anchors: contributes 0, drop held.
        s.native_value
        assert s._zone_tier_baselines["sensor.young"]["scope"] == "today_derived"
        states["sensor.young"] = (1003.0, "kWh")
        s.native_value
        assert s.extra_state_attributes["zone_level_energy_kwh"] == 2.0


def test_energy_midnight_reeval_reclassifies_replaced_counter():
    # Lifetime counter replaced overnight by a fresh today counter: the
    # midnight re-evaluation must reclassify it as today_native.
    states = {"sensor.ac": (5000.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.ac"])])
    s = _make(ZoneEnergyTodaySensor, hass, [_coord(energy=0.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)):
        s.native_value
    with patch.object(agg.dt_util, "now", return_value=_at(2)):
        states["sensor.ac"] = (2.0, "kWh")
        assert s.native_value == 2.0


def test_energy_init_sets_tracker_state():
    hass = _hass({}, [_zm_entry()])
    entry = SimpleNamespace(entry_id="zm", data={}, options={})
    s = ZoneEnergyTodaySensor(hass, entry, ZONE)
    assert s._zone_tier_baselines == {}
    assert s._contrib == {}


# ------------------------------------------------------- energy cost today

def test_energy_cost_today_includes_zone_level_energy():
    hass = _hass({"sensor.ac_today": (4.0, "kWh")},
                 [_zm_entry(zone_energy=["sensor.ac_today"])])
    s = _make(ZoneEnergyCostTodaySensor, hass, [_coord(energy=0.0)])
    with patch.object(agg.dt_util, "now", return_value=_at(1)), \
         patch.object(agg, "_get_effective_rate_kwh", return_value=(0.25, "t")):
        # rooms 0 kWh alone -> None; 4 kWh * 0.25 = 1.0
        assert s.native_value == 1.0


def test_energy_cost_today_lifetime_counter_and_overlap():
    states = {"sensor.ac_total": (5000.0, "kWh"), "sensor.room": (2.0, "kWh")}
    hass = _hass(states, [_zm_entry(zone_energy=["sensor.ac_total", "sensor.room"])])
    room = _coord(energy=2.0, energy_sensors=["sensor.room"])
    s = _make(ZoneEnergyCostTodaySensor, hass, [room])
    with patch.object(agg.dt_util, "now", return_value=_at(1)), \
         patch.object(agg, "_get_effective_rate_kwh", return_value=(0.5, "t")):
        assert s.native_value == 1.0  # room 2 kWh only; counter anchors
        states["sensor.ac_total"] = (5003.0, "kWh")
        assert s.native_value == 2.5  # (2 + 3) * 0.5


def test_zone_tier_threshold_matches_coverage():
    assert ZoneEnergyCostTodaySensor._ZONE_TIER_CUMULATIVE_THRESHOLD_KWH == 1000.0
