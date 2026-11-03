"""ENERGY-TODAY-MIDNIGHT-FREEZE-1: composed energy-today totals must accept
every staggered post-midnight room reset, yet still hold a mid-day dip
(the C-H1 protection from 342caccf) and survive a restart that samples
before the rooms have loaded.

Live repro (2026-11-03): rooms_energy_total 48.08 at 23:59:35, 39.66 at
00:00:05 (partial reset accepted), then frozen at 39.66 until a restart
because the one-drop-per-date allowance was already used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.universal_room_automation import aggregation as agg
from custom_components.universal_room_automation.aggregation import (
    RoomsEnergyTotalSensor,
    WholeHouseEnergySensor,
    ZoneEnergyTodaySensor,
)


def _t(day, h, m, s=0):
    return datetime(2026, 11, day, h, m, s)


def _clock(dt):
    return patch.object(agg.dt_util, "now", return_value=dt)


# ------------------------------------------------------------ fixtures

def _room(name, kwh):
    return SimpleNamespace(
        entry=SimpleNamespace(entry_id=name, data={"room_name": name,
                                                   "zone": "z"}, options={}),
        data={"energy_today": kwh},
    )


class _Rooms:
    """Drives RoomsEnergyTotalSensor through its real native_value."""

    def __init__(self):
        self.rooms = []

    def make(self):
        s = RoomsEnergyTotalSensor.__new__(RoomsEnergyTotalSensor)
        s.hass = SimpleNamespace(data={})
        s._last_valid_value = None
        s._last_accepted_date = None
        return s

    def read(self, s, values):
        rooms = [_room(f"r{i}", v) for i, v in enumerate(values)]
        with patch.object(agg, "_get_room_coordinators", return_value=rooms):
            return s.native_value


class _Zone:
    def make(self):
        s = ZoneEnergyTodaySensor.__new__(ZoneEnergyTodaySensor)
        s.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda eid: None),
            config_entries=SimpleNamespace(async_entries=lambda domain=None: []),
            data={},
        )
        s.zone = "z"
        s._last_valid_value = None
        s._last_accepted_date = None
        s._zone_tier_baselines = {}
        s._zone_tier_reclassify_date = None
        s._contrib = {}
        return s

    def read(self, s, values):
        rooms = [_room(f"r{i}", v) for i, v in enumerate(values)]
        s._get_zone_coordinators = lambda: rooms
        return s.native_value


class _House:
    def make(self):
        s = WholeHouseEnergySensor.__new__(WholeHouseEnergySensor)
        s.hass = SimpleNamespace(data={})
        s._get_sensor_list = lambda *_a: ["sensor.envoy"]
        return s

    def read(self, s, values):
        s._sum_sensors = lambda _sensors: round(sum(values), 2)
        return s.native_value


DRIVERS = {"rooms": _Rooms(), "zone": _Zone(), "house": _House()}


def _drive(kind, script):
    """script: list of (datetime, [room values]); returns the outputs."""
    d = DRIVERS[kind]
    s = d.make()
    out = []
    for when, values in script:
        with _clock(when):
            out.append(d.read(s, values))
    return out


# Three rooms resetting one after another after midnight (independent
# oracle: each output is the plain sum of the room values at that tick).
STAGGERED = [
    (_t(2, 23, 59, 35), [30.0, 10.0, 8.0]),    # 48.0
    (_t(3, 0, 0, 5), [0.1, 10.0, 8.0]),        # room 0 reset -> 18.1
    (_t(3, 0, 0, 40), [0.1, 0.0, 8.0]),        # room 1 reset -> 8.1
    (_t(3, 0, 1, 10), [0.2, 0.0, 0.0]),        # room 2 reset -> 0.2
    (_t(3, 2, 0, 0), [1.5, 1.4, 1.54]),        # 4.44
]
STAGGERED_EXPECT = [48.0, 18.1, 8.1, 0.2, 4.44]


def _check_staggered(kind):
    assert _drive(kind, STAGGERED) == STAGGERED_EXPECT


def _check_midday_dip_held(kind):
    out = _drive(kind, [
        (_t(3, 10, 0), [3.0, 2.0, 1.0]),     # 6.0
        (_t(3, 10, 1), [3.0, 0.0, 1.0]),     # room 1 unavailable -> 4.0 dip
        (_t(3, 10, 2), [3.1, 2.0, 1.0]),     # back -> 6.1
    ])
    assert out == [6.0, 6.0, 6.1]


# ------------------------------------------------- per-sensor behaviour

def test_rooms_total_accepts_staggered_midnight_resets():
    _check_staggered("rooms")


def test_zone_energy_accepts_staggered_midnight_resets():
    _check_staggered("zone")


def test_house_energy_accepts_staggered_midnight_resets():
    _check_staggered("house")


def test_rooms_total_holds_midday_dip():
    _check_midday_dip_held("rooms")


def test_zone_energy_holds_midday_dip():
    _check_midday_dip_held("zone")


def test_house_energy_holds_midday_dip():
    _check_midday_dip_held("house")


# ------------------------------------------------- window boundaries

def _boundary(second_tick):
    return _drive("rooms", [
        (_t(3, 0, 0, 30), [5.0]),
        (second_tick, [4.0]),
    ])[1]


def test_window_last_second_inside_accepts_drop():
    assert _boundary(_t(3, 0, 14, 59)) == 4.0


def test_window_closed_at_15_minutes_holds_drop():
    assert _boundary(_t(3, 0, 15, 0)) == 5.0


def test_window_constant_value_pinned():
    assert agg.ENERGY_TODAY_RESET_ACCEPT_WINDOW_MIN == 15


def test_drop_across_date_change_outside_window_accepted():
    # Restart that missed midnight: last value from yesterday, now 06:56.
    out = _drive("rooms", [
        (_t(2, 23, 0), [40.0]),
        (_t(3, 6, 56), [0.9]),
    ])
    assert out == [40.0, 0.9]


# ------------------------------------------ restart before rooms load

def _saved(s):
    return s.extra_restore_state_data.as_dict()


def test_rooms_total_restart_before_rooms_load_holds_restored_value():
    d = DRIVERS["rooms"]
    a = d.make()
    with _clock(_t(3, 6, 50)):
        assert d.read(a, [6.0, 6.79]) == 12.79
        payload = _saved(a)
    b = d.make()
    with _clock(_t(3, 6, 56)):
        b._apply_restore(payload)
        assert d.read(b, [0.91]) == 12.79        # partial boot load held
        assert d.read(b, [6.0, 6.9]) == 12.9      # rooms loaded


def test_rooms_total_async_added_to_hass_applies_restore():
    from homeassistant.helpers.restore_state import RestoredExtraData
    s = DRIVERS["rooms"].make()
    payload = {"last_valid_value": 7.5, "last_accepted_date": "2026-11-03",
               "baselines": {}}

    async def _noop(self):
        return None

    async def _extra():
        return RestoredExtraData(payload)

    s.async_get_last_extra_data = _extra
    with patch.object(agg.AggregationEntity, "async_added_to_hass", _noop), \
            _clock(_t(3, 9, 0)):
        asyncio.run(s.async_added_to_hass())
    assert s._last_valid_value == 7.5
    assert str(s._last_accepted_date) == "2026-11-03"


def test_zone_restart_before_rooms_load_holds_restored_value():
    d = DRIVERS["zone"]
    a = d.make()
    with _clock(_t(3, 6, 50)):
        assert d.read(a, [4.44]) == 4.44
        payload = _saved(a)
    b = d.make()
    with _clock(_t(3, 6, 56)):
        b._apply_restore(payload)
        assert d.read(b, [0.5]) == 4.44
