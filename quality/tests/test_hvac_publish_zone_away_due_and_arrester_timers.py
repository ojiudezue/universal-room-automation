"""HVAC-PUBLISH-ZONE-AWAY-DUE-AND-ARRESTER-TIMERS-1 — display-only timers.

(1) `away_due_at` on `sensor.ura_hvac_coordinator_zone_{n}_status`, driven
    through the REAL `HVACZoneStatusSensor.extra_state_attributes` (wire-in
    anchor: the sensor must hand the LIVE grace to the zone manager) over the
    REAL `HVACCoordinator` + `ZoneManager` (fast-occupancy harness).
(2) Per-zone `grace_until` / `compromise_until` in the REAL
    `OverrideArrester.get_arrester_detail`, armed through the production
    override paths (normal / severe detection, startup audit, compromise)
    and retired when the timer is cancelled.
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402
from test_hvac_fast_occupancy_response import (  # noqa: E402
    S,
    T0,
    _Clock,
    _exit_setup,
)


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    """Real arrester grace / compromise timers are armed by the production
    paths under test; the leak detector cancels + warns instead of failing."""
    return True


ZONE = "zone_1"
ENT = "climate.test_zone_1"


# ---------------------------------------------------------------------------
# (1) away_due_at on the zone status sensor
# ---------------------------------------------------------------------------


def _zone_status_attrs(mods, hass, coord, zone_id=ZONE):
    """Drive the REAL sensor property with a minimal `self` (no entity
    platform needed): hass.data -> coordinator_manager -> hvac."""
    from custom_components.universal_room_automation import sensor as sensor_mod

    DOMAIN = mods["const"].DOMAIN
    hass.data.setdefault(DOMAIN, {})["coordinator_manager"] = types.SimpleNamespace(
        coordinators={"hvac": coord},
    )
    fake_self = types.SimpleNamespace(hass=hass, _zone_id=zone_id)
    return sensor_mod.HVACZoneStatusSensor.extra_state_attributes.fget(fake_self)


def test_away_due_at_published_when_zone_empty_past_release(mods):
    """Bedroom evidence ends at T0 (day hold 240 s) -> release T0+240;
    grace knob 48 = 10 min -> away due T0+840. Past the release the zone is
    HVAC-empty and the sensor publishes that instant (ISO, local tz)."""
    with _Clock(T0) as clk:
        coord, hass, coords, _sched = _exit_setup(mods, clk, grace=10, constrained=3)
        coords["bed1"].active = False
        clk.t = T0 + S(seconds=300)                       # past the release
        coord.zone_manager.update_room_conditions(house_state="home_day")
        assert coord.zone_manager.zones[ZONE].any_room_hvac_occupied is False
        attrs = _zone_status_attrs(mods, hass, coord)
    assert "away_due_at" in attrs
    due = datetime.fromisoformat(attrs["away_due_at"])
    assert due == T0 + S(seconds=240 + 600)
    # Same helper the exit timer uses, minus the 2 s timer slack.
    assert due == coord._exit_due(ZONE)[0] - S(seconds=2)


def test_away_due_at_none_once_due_time_has_passed(mods):
    """Review L2: after the exit instant (T0+840) the zone has retreated (or
    is overdue); the sensor must not keep showing a past instant. One second
    before due it still publishes; at due and after it reads None."""
    with _Clock(T0) as clk:
        coord, hass, coords, _sched = _exit_setup(mods, clk, grace=10, constrained=3)
        coords["bed1"].active = False
        clk.t = T0 + S(seconds=300)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        clk.t = T0 + S(seconds=839)
        before = _zone_status_attrs(mods, hass, coord)["away_due_at"]
        clk.t = T0 + S(seconds=840)
        at_due = _zone_status_attrs(mods, hass, coord)["away_due_at"]
        clk.t = T0 + S(seconds=1200)
        after = _zone_status_attrs(mods, hass, coord)["away_due_at"]
    assert datetime.fromisoformat(before) == T0 + S(seconds=840)
    assert at_due is None
    assert after is None


def test_away_due_at_follows_constrained_grace(mods):
    """Under coast the LIVE grace is knob 49 (3 min) -> T0+240+180."""
    with _Clock(T0) as clk:
        coord, hass, coords, _sched = _exit_setup(mods, clk, grace=10, constrained=3)
        coords["bed1"].active = False
        clk.t = T0 + S(seconds=300)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        EC = mods["hvac"].EnergyConstraint
        coord._handle_energy_constraint(EC(mode="coast", setpoint_offset=0.0))
        attrs = _zone_status_attrs(mods, hass, coord)
    assert datetime.fromisoformat(attrs["away_due_at"]) == T0 + S(seconds=240 + 180)


def test_away_due_at_none_while_zone_occupied(mods):
    """Evidence still active -> zone HVAC-occupied -> None."""
    with _Clock(T0) as clk:
        coord, hass, coords, _sched = _exit_setup(mods, clk, grace=10, constrained=3)
        assert coord.zone_manager.zones[ZONE].any_room_hvac_occupied is True
        attrs = _zone_status_attrs(mods, hass, coord)
    assert "away_due_at" in attrs
    assert attrs["away_due_at"] is None


def test_away_due_at_none_while_room_hold_still_running(mods):
    """Discriminator for the occupied gate: evidence ended at T0 but the
    bedroom hold (240 s) is still running at T0+100, so the zone is still
    HVAC-occupied even though a release instant is already known. Published
    value stays None until the zone is actually empty."""
    with _Clock(T0) as clk:
        coord, hass, coords, _sched = _exit_setup(mods, clk, grace=10, constrained=3)
        coords["bed1"].active = False
        clk.t = T0 + S(seconds=100)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        assert coord.zone_manager.zones[ZONE].any_room_hvac_occupied is True
        assert coord.zone_manager.zone_release_at(ZONE) == T0 + S(seconds=240)
        attrs = _zone_status_attrs(mods, hass, coord)
    assert attrs["away_due_at"] is None


# ---------------------------------------------------------------------------
# (2) arrester grace_until / compromise_until
# ---------------------------------------------------------------------------


def _arr(mods):
    coord, hass = H.make_coord(mods)
    arr = coord._override_arrester
    arr.enabled = True
    return coord, hass, arr


def _zone_detail(arr, zone_name="Zone 1"):
    return arr.get_arrester_detail()["zones"][zone_name]


def _normal_event():
    # +2 F on the cooling setpoint: NORMAL band (1-3 F) -> grace then compromise.
    return H.make_event(ENT, old_preset="home", new_preset="manual",
                        old_high=76.0, new_high=78.0, old_low=68.0, new_low=68.0)


def _severe_event():
    return H.make_event(ENT, old_preset="home", new_preset="manual",
                        old_high=76.0, new_high=64.0, old_low=68.0, new_low=64.0)


def _until(detail, key):
    v = detail[key]
    return datetime.fromisoformat(v) if v is not None else None


@pytest.mark.asyncio
async def test_grace_until_set_on_normal_override_and_cleared_on_cancel(mods):
    oc = mods["hvac_const"]
    with _Clock(T0):
        coord, hass, arr = _arr(mods)
        assert _zone_detail(arr)["grace_until"] is None
        arr._handle_climate_change(_normal_event())
        await H.drain(hass)
        assert ZONE in arr._grace_timers, "normal override must arm its grace"
        d = _zone_detail(arr)
        assert _until(d, "grace_until") == T0 + S(
            minutes=oc.OVERRIDE_NORMAL_GRACE_MINUTES,
        )
        assert d["compromise_until"] is None
        # Cancel (the path every re-arm / deferral uses).
        arr._cancel_arrester_timers(ZONE)
        assert _zone_detail(arr)["grace_until"] is None


@pytest.mark.asyncio
async def test_grace_until_set_on_severe_override_and_cleared_on_disable(mods):
    oc = mods["hvac_const"]
    with _Clock(T0):
        coord, hass, arr = _arr(mods)
        arr._handle_climate_change(_severe_event())
        await H.drain(hass)
        assert _until(_zone_detail(arr), "grace_until") == T0 + S(
            minutes=oc.OVERRIDE_SEVERE_GRACE_MINUTES,
        )
        arr.enabled = False                               # cancels every timer
        assert _zone_detail(arr)["grace_until"] is None


@pytest.mark.asyncio
async def test_grace_until_set_by_startup_audit(mods):
    oc = mods["hvac_const"]
    with _Clock(T0):
        coord, hass, arr = _arr(mods)
        H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual",
                      high=60.0, low=60.0)
        pm = MagicMock()
        pm.current_season = "summer"
        pm.get_preset_for_house_state.return_value = "home"
        pm.get_seasonal_setpoints.return_value = (76.0, 68.0)
        await arr.async_startup_audit(pm)
        assert ZONE in arr._grace_timers, "startup audit must arm its grace"
        assert _until(_zone_detail(arr), "grace_until") == T0 + S(
            minutes=oc.OVERRIDE_SEVERE_GRACE_MINUTES,
        )


@pytest.mark.asyncio
async def test_compromise_until_set_when_compromise_applies_and_cleared_on_revert(mods):
    with _Clock(T0):
        coord, hass, arr = _arr(mods)
        zone = coord.zone_manager.zones[ZONE]
        await arr._apply_compromise(zone, "home", 77.0, 68.0, 76.0, 68.0)
        await H.drain(hass)
        assert ZONE in arr._compromise_timers, "compromise must arm its timer"
        d = _zone_detail(arr)
        assert _until(d, "compromise_until") == T0 + S(
            minutes=arr._compromise_minutes,
        )
        assert d["grace_until"] is None
        # The compromise timer's own fire path (revert) retires it.
        await arr._revert_override(zone, "home")
        await H.drain(hass)
        assert _zone_detail(arr)["compromise_until"] is None
