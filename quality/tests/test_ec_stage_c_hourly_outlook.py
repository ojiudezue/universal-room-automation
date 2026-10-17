"""EC storm Stage C D-C1 — `WeatherProviderManager` hourly outlook.

Provider policy (coordinator ruling 2026-10-16): BACKUP, not cross-check.
Per hour slot, the first provider in the configured rank order that is
healthy, fresh (FORECAST_STALE_MIN) and carries that hour. A provider
without hourly support is skipped (not an error). All unusable → None.
Drives the REAL `_refresh_hourly_locked` / `_fetch_provider_hourly` /
`hourly_outlook` against a fake service bus.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _reserve_governor_harness import clock  # noqa: F401 — fixture
from conftest import MockHass as _BaseMockHass, MockState


class MockHass(_BaseMockHass):
    """conftest MockHass + the `config` HA's Store constructor touches."""

    def __init__(self):
        super().__init__()
        self.config = MagicMock()

import custom_components.universal_room_automation.domain_coordinators.weather_manager as wm_mod
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ENERGY_WEATHER_ENTITY,
    CONF_ENERGY_WEATHER_FALLBACK_1,
    CONF_ENERGY_WEATHER_FALLBACK_2,
)
from custom_components.universal_room_automation.domain_coordinators.inclement import (
    forecast_confirms,
)
from custom_components.universal_room_automation.domain_coordinators.weather_manager import (
    WeatherProviderManager,
)

_UTC = timezone.utc
OWM, DYN, OM = "weather.owm", "weather.dyn", "weather.om"
T0 = datetime(2026, 12, 1, 6, 0, tzinfo=_UTC)


def _rows(start, n, *, pop=True, temp=25.0, mm=None):
    out = []
    for i in range(n):
        r = {"datetime": (start + timedelta(hours=i)).isoformat(),
             "temperature": temp, "condition": "snowy",
             "wind_gust_speed": 20.0}
        if pop:
            r["precipitation_probability"] = 70
        if mm is not None:
            r["precipitation"] = mm
        out.append(r)
    return out


def _mgr(clock, *, owm_rows, om_rows, owm_state="snowy", om_unit="°F"):
    clock.t = T0
    hass = MockHass()
    for eid, unit in ((OWM, "°F"), (DYN, "°F"), (OM, om_unit)):
        st = MockState(eid, owm_state if eid == OWM else "cloudy",
                       {"apparent_temperature": 20, "temperature_unit": unit,
                        "precipitation_unit": "mm"})
        st.last_changed = st.last_updated = T0
        hass._states[eid] = st
    calls = []

    async def _svc(domain, svc, data, blocking=False, return_response=False):
        calls.append(data["entity_id"])
        eid = data["entity_id"]
        if eid == DYN:
            raise RuntimeError("hourly not supported")
        rows = owm_rows if eid == OWM else om_rows
        return {eid: {"forecast": rows}}
    hass.services = SimpleNamespace(async_call=_svc)
    m = WeatherProviderManager(hass, {
        CONF_ENERGY_WEATHER_ENTITY: OWM,
        CONF_ENERGY_WEATHER_FALLBACK_1: DYN,
        CONF_ENERGY_WEATHER_FALLBACK_2: OM,
    })
    asyncio.new_event_loop().run_until_complete(m._refresh_hourly())
    return m, calls


def test_backup_policy_owm_then_open_meteo_beyond_horizon(clock):
    m, calls = _mgr(clock, owm_rows=_rows(T0, 48),
                    om_rows=_rows(T0, 164, pop=False, temp=10.0, mm=2.0))
    assert set(calls) == {OWM, DYN, OM}
    assert m.hourly_providers_ok == 2 and m.hourly_fetched_at == T0
    o = m.hourly_outlook(T0 + timedelta(hours=40), T0 + timedelta(hours=60))
    assert o.hours == 20
    assert [s[0] for s in o.sources] == [OWM, OM]
    assert o.sources[0][2] == (T0 + timedelta(hours=47)).isoformat()
    assert o.max_pop == 70 and o.max_precip_mm_no_pop == 2.0
    assert o.min_temp_f == 10.0
    # Inside OWM's horizon only OWM is used (no cross-check).
    o2 = m.hourly_outlook(T0, T0 + timedelta(hours=10))
    assert [s[0] for s in o2.sources] == [OWM] and o2.min_temp_f == 25.0


def test_unhealthy_primary_skipped(clock):
    m, _ = _mgr(clock, owm_rows=_rows(T0, 48),
                om_rows=_rows(T0, 164, pop=False, temp=10.0, mm=2.0))
    m.hass._states[OWM] = MockState(OWM, "unavailable", {})
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert [s[0] for s in o.sources] == [OM]


def test_all_unusable_is_none(clock):
    m, _ = _mgr(clock, owm_rows=_rows(T0, 48), om_rows=[])
    m.hass._states[OWM] = MockState(OWM, "unavailable", {})
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


def test_forecast_stale_beyond_limit_is_none(clock):
    m, _ = _mgr(clock, owm_rows=_rows(T0, 48), om_rows=[])
    clock.t = T0 + timedelta(minutes=120)
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is not None
    clock.t = T0 + timedelta(minutes=121)
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


def test_forecast_first_tick_never_fetched(clock):
    clock.t = T0
    m = WeatherProviderManager(MockHass(), {CONF_ENERGY_WEATHER_ENTITY: OWM})
    assert m.hourly_fetched_at is None
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


def test_celsius_provider_converted(clock):
    m, _ = _mgr(clock, owm_rows=[], om_rows=_rows(T0, 10, pop=False,
                                                  temp=-5.0, mm=3.0),
                om_unit="°C")
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.min_temp_f == pytest.approx(23.0)
    assert forecast_confirms("Hard Freeze Watch", o) is True


def test_winter_storm_confirms_by_amount_when_no_probability(clock):
    m, _ = _mgr(clock, owm_rows=[], om_rows=_rows(T0, 10, pop=False,
                                                  temp=30.0, mm=1.5))
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.max_pop is None and forecast_confirms("Winter Storm Warning", o)


def test_forecast_timer_torn_down(clock, monkeypatch):
    unsub = MagicMock()
    monkeypatch.setattr(wm_mod, "async_track_time_interval",
                        lambda hass, cb, interval: unsub)
    monkeypatch.setattr(wm_mod, "async_track_state_change_event",
                        lambda hass, ents, cb: MagicMock())
    hass = MockHass()
    tasks = []
    loop = asyncio.new_event_loop()

    def _ct(coro, name=None):
        t = loop.create_task(coro)
        tasks.append(t)
        return t
    hass.async_create_task = _ct
    hass.services = SimpleNamespace(async_call=MagicMock())
    m = WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: OWM})

    async def _noop():
        return None
    m._refresh_all_providers = _noop
    m._hydrate_rolling_window_from_store = _noop
    loop.run_until_complete(m.async_setup())
    assert unsub in m._unsub_handles
    assert len(tasks) == 1 and tasks[0] in m._pending_refresh_tasks or tasks[0].done()
    loop.run_until_complete(m.async_teardown())
    unsub.assert_called_once()
    assert m._unsub_handles == [] and m._pending_refresh_tasks == set()
