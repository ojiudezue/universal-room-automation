"""EC-BATTERY-CHARGE-SOURCE-DAY-1 — daily totals of the EC battery charge split.

Drives the production PeakAvoidanceTracker (the single per-tick integrator)
and the two production sensors. Oracles are hand-derived:
grid = min(charge, max(net, 0)) x elapsed_h; solar = charge x h - grid.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators.energy_billing import (  # noqa: E402
    PeakAvoidanceTracker,
)

_BASE = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


def _mk() -> PeakAvoidanceTracker:
    return PeakAvoidanceTracker(hass=MagicMock(), bill_cycle_day=1)


def _run(tr, start, n, *, battery_kw, net_kw, solar_kw=0.0):
    """n+1 ticks 6 min apart -> n integrated ticks of 0.1 h each."""
    for i in range(n + 1):
        tr.accumulate(
            now=start + timedelta(minutes=6 * i),
            solar_kw=solar_kw, battery_power_kw=battery_kw,
            net_import_kw=net_kw, effective_rate=0.1, period="off_peak",
        )


def test_split_accrues_into_correct_buckets():
    tr = _mk()
    # charge 5 kW, net import 2 kW -> grid 2 kW, solar 3 kW; 10 ticks x 0.1 h.
    _run(tr, _BASE, 10, battery_kw=5.0, net_kw=2.0, solar_kw=6.0)
    st = tr.get_status()
    assert st["charge_grid_kwh_today"] == pytest.approx(2.0, abs=1e-3)
    assert st["charge_solar_kwh_today"] == pytest.approx(3.0, abs=1e-3)
    assert st["charge_unsplit_kwh_today"] == 0.0
    assert st["grid_charge_kw"] == pytest.approx(2.0)
    assert st["solar_charge_kw"] == pytest.approx(3.0)


def test_pure_grid_charge_and_discharge_not_counted():
    tr = _mk()
    _run(tr, _BASE, 5, battery_kw=4.0, net_kw=6.0)  # net > charge: all grid
    _run(tr, _BASE + timedelta(hours=2), 5, battery_kw=-3.0, net_kw=0.0)
    st = tr.get_status()
    assert st["charge_grid_kwh_today"] == pytest.approx(2.0, abs=1e-3)
    assert st["charge_solar_kwh_today"] == pytest.approx(0.0, abs=1e-6)


def test_unsplit_when_net_none():
    tr = _mk()
    _run(tr, _BASE, 10, battery_kw=5.0, net_kw=None)
    st = tr.get_status()
    assert st["charge_unsplit_kwh_today"] == pytest.approx(5.0, abs=1e-3)
    assert st["charge_grid_kwh_today"] == 0.0
    assert st["charge_solar_kwh_today"] == 0.0
    assert st["grid_charge_kw"] is None
    assert st["solar_charge_kw"] is None


def test_local_midnight_reset():
    tr = _mk()
    _run(tr, datetime(2026, 7, 15, 23, 0, tzinfo=timezone.utc), 5,
         battery_kw=5.0, net_kw=5.0)
    assert tr.charge_grid_kwh_today == pytest.approx(2.5, abs=1e-3)
    # First tick on the next date zeroes all three buckets.
    tr.accumulate(
        now=datetime(2026, 7, 16, 0, 1, tzinfo=timezone.utc),
        solar_kw=0.0, battery_power_kw=0.0, net_import_kw=0.0,
        effective_rate=0.1,
    )
    assert tr.charge_grid_kwh_today == 0.0
    assert tr.charge_solar_kwh_today == 0.0
    assert tr.charge_unsplit_kwh_today == 0.0


def test_reset_keys_on_now_date_of_caller():
    """The reset keys on now.date() of the datetime the EC passes (dt_util.now(),
    local). A 23:59 -> 00:01 step in a non-UTC zone resets."""
    tz = timezone(timedelta(hours=-6))
    tr = _mk()
    _run(tr, datetime(2026, 7, 15, 23, 0, tzinfo=tz), 5, battery_kw=2.0, net_kw=0.0)
    assert tr.charge_solar_kwh_today == pytest.approx(1.0, abs=1e-3)
    tr.accumulate(now=datetime(2026, 7, 16, 0, 1, tzinfo=tz), solar_kw=0.0,
                  battery_power_kw=0.0, net_import_kw=0.0, effective_rate=0.1)
    assert tr.charge_solar_kwh_today == 0.0


def _snap_with(tr, date_iso):
    snap = tr.snapshot_state()
    snap["snapshot_date"] = date_iso
    return snap


def test_restore_same_day_keeps_totals():
    from homeassistant.util import dt as dt_util
    tr = _mk()
    _run(tr, _BASE, 10, battery_kw=5.0, net_kw=2.0)
    _run(tr, _BASE + timedelta(hours=3), 4, battery_kw=1.0, net_kw=None)
    snap = _snap_with(tr, dt_util.now().date().isoformat())
    fresh = _mk()
    fresh.restore_snapshot(snap)
    assert fresh.charge_grid_kwh_today == pytest.approx(2.0, abs=1e-3)
    assert fresh.charge_solar_kwh_today == pytest.approx(3.0, abs=1e-3)
    assert fresh.charge_unsplit_kwh_today == pytest.approx(0.4, abs=1e-3)


def test_restore_stale_day_discards():
    from homeassistant.util import dt as dt_util
    tr = _mk()
    _run(tr, _BASE, 10, battery_kw=5.0, net_kw=2.0)
    stale = (dt_util.now().date() - timedelta(days=1)).isoformat()
    fresh = _mk()
    fresh.restore_snapshot(_snap_with(tr, stale))
    assert fresh.charge_grid_kwh_today == 0.0
    assert fresh.charge_solar_kwh_today == 0.0
    assert fresh.charge_unsplit_kwh_today == 0.0


def test_restore_old_snapshot_without_new_keys():
    """Upgrade path: a snapshot saved before this cycle has no charge keys."""
    from homeassistant.util import dt as dt_util
    tr = _mk()
    _run(tr, _BASE, 10, battery_kw=5.0, net_kw=2.0)
    snap = _snap_with(tr, dt_util.now().date().isoformat())
    for k in ("charge_grid_kwh_today", "charge_solar_kwh_today",
              "charge_unsplit_kwh_today"):
        snap.pop(k, None)
    fresh = _mk()
    fresh.restore_snapshot(snap)
    assert fresh.charge_grid_kwh_today == 0.0
    assert fresh.charge_solar_kwh_today == 0.0
    assert fresh.charge_unsplit_kwh_today == 0.0


class _FakeEC:
    def __init__(self, tracker):
        self._t = tracker

    @property
    def peak_avoidance_status(self):
        return self._t.get_status()


def test_sensors_read_tracker(monkeypatch):
    sensor = importlib.import_module(
        "custom_components.universal_room_automation.sensor"
    )
    tr = _mk()
    _run(tr, _BASE, 10, battery_kw=5.0, net_kw=2.0)
    _run(tr, _BASE + timedelta(hours=3), 4, battery_kw=1.0, net_kw=None)
    monkeypatch.setattr(sensor, "_ec", lambda hass: _FakeEC(tr))
    grid = object.__new__(sensor.EnergyBatteryChargedFromGridTodaySensor)
    sun = object.__new__(sensor.EnergyBatteryChargedFromSunTodaySensor)
    grid.hass = sun.hass = MagicMock()
    assert grid.native_value == pytest.approx(2.0, abs=1e-3)
    assert sun.native_value == pytest.approx(3.0, abs=1e-3)
    attrs = sun.extra_state_attributes
    assert attrs["unsplit_kwh_today"] == pytest.approx(0.4, abs=1e-3)
    assert attrs["grid_charge_kw"] is None  # latest tick was net-unknown
    monkeypatch.setattr(sensor, "_ec", lambda hass: None)
    assert grid.native_value is None
