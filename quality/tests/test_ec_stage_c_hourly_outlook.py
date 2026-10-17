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

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_ENERGY_WEATHER_ENTITY,
    CONF_ENERGY_WEATHER_FALLBACK_1,
    CONF_ENERGY_WEATHER_FALLBACK_2,
)

_WM = "custom_components.universal_room_automation.domain_coordinators.weather_manager"


class _Store:
    """Inert stand-in for HA's Store (the ring is not under test here)."""

    def __init__(self, *a, **k):
        pass


@pytest.fixture
def wm_mod(clock, monkeypatch):
    """The weather_manager module, imported at TEST time (never at collection,
    so this file cannot pre-load it into another file's stub environment),
    with a deterministic clock shim on ITS OWN `dt_util` binding (whatever
    dt module another file installed) and an inert Store. A module this
    fixture imported is removed again afterwards."""
    import importlib
    import sys
    pre = sys.modules.get(_WM)
    mod = pre or importlib.import_module(_WM)

    class _Dt:
        UTC = timezone.utc

        @staticmethod
        def utcnow():
            return clock.t

        @staticmethod
        def as_utc(d):
            return d.astimezone(timezone.utc)

        @staticmethod
        def parse_datetime(v):
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

    monkeypatch.setattr(mod, "dt_util", _Dt)
    monkeypatch.setattr(mod, "Store", _Store)
    yield mod
    if pre is None:
        sys.modules.pop(_WM, None)


def _forecast_confirms(*a):
    import sys
    return sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.inclement"
    ].forecast_confirms(*a)


_UTC = timezone.utc
OWM, DYN, OM = "weather.owm", "weather.dyn", "weather.om"
T0 = datetime(2026, 12, 1, 6, 0, tzinfo=_UTC)


def _rows(start, n, *, pop=True, temp=25.0, mm=None, app=None):
    out = []
    for i in range(n):
        r = {"datetime": (start + timedelta(hours=i)).isoformat(),
             "temperature": temp, "condition": "snowy",
             "wind_gust_speed": 20.0}
        if app is not None:
            r["apparent_temperature"] = app
        if pop:
            r["precipitation_probability"] = 70
        if mm is not None:
            r["precipitation"] = mm
        out.append(r)
    return out


def _mgr(wm_mod, clock, *, owm_rows, om_rows, owm_state="snowy", om_unit="°F",
         lc_age=timedelta(0), p_unit="mm"):
    clock.t = T0
    hass = MockHass()
    for eid, unit in ((OWM, "°F"), (DYN, "°F"), (OM, om_unit)):
        st = MockState(eid, owm_state if eid == OWM else "cloudy",
                       {"apparent_temperature": 20, "temperature_unit": unit,
                        "precipitation_unit": p_unit})
        st.last_changed = st.last_updated = T0 - lc_age
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
    m = wm_mod.WeatherProviderManager(hass, {
        CONF_ENERGY_WEATHER_ENTITY: OWM,
        CONF_ENERGY_WEATHER_FALLBACK_1: DYN,
        CONF_ENERGY_WEATHER_FALLBACK_2: OM,
    })
    asyncio.new_event_loop().run_until_complete(m._refresh_hourly())
    return m, calls


def test_backup_policy_owm_then_open_meteo_beyond_horizon(wm_mod, clock):
    m, calls = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48),
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


def test_unhealthy_primary_skipped(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48),
                om_rows=_rows(T0, 164, pop=False, temp=10.0, mm=2.0))
    m.hass._states[OWM] = MockState(OWM, "unavailable", {})
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert [s[0] for s in o.sources] == [OM]


def test_all_unusable_is_none(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48), om_rows=[])
    m.hass._states[OWM] = MockState(OWM, "unavailable", {})
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


def test_forecast_stale_beyond_limit_is_none(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48), om_rows=[])
    clock.t = T0 + timedelta(minutes=120)
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is not None
    clock.t = T0 + timedelta(minutes=121)
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


def test_forecast_first_tick_never_fetched(wm_mod, clock):
    clock.t = T0
    m = wm_mod.WeatherProviderManager(MockHass(), {CONF_ENERGY_WEATHER_ENTITY: OWM})
    assert m.hourly_fetched_at is None
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


def test_celsius_provider_converted(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=[], om_rows=_rows(T0, 10, pop=False,
                                                  temp=-5.0, mm=3.0),
                om_unit="°C")
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.min_temp_f == pytest.approx(23.0)
    assert _forecast_confirms("Hard Freeze Watch", o) is True


def test_winter_storm_confirms_by_amount_when_no_probability(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=[], om_rows=_rows(T0, 10, pop=False,
                                                  temp=30.0, mm=1.5))
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.max_pop is None and _forecast_confirms("Winter Storm Warning", o)


def test_forecast_timer_torn_down(wm_mod, clock, monkeypatch):
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
    m = wm_mod.WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: OWM})

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


# ---------------------------------------------------------------------------
# Review A fix-up: A-MED-1 (STALE is not an hourly gate), A-LOW-3 (cm),
# operator 2026-10-17 apparent-temperature leg.
# ---------------------------------------------------------------------------
def test_condition_stale_providers_still_hourly_fetched_and_used(wm_mod, clock):
    """A-MED-1 repro: every provider steady on the same condition for 7 h
    (> the 6 h condition-staleness default) → `_check_provider_health` reads
    STALE, yet the hourly rows are still fetched and used (freshness is
    FORECAST_STALE_MIN on fetched_at)."""
    m, calls = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48),
                    om_rows=_rows(T0, 164, pop=False, temp=10.0, mm=2.0),
                    owm_state="cloudy", lc_age=timedelta(hours=7))
    assert m._check_provider_health(OWM) == wm_mod.WeatherProviderHealth.STALE
    assert set(calls) == {OWM, DYN, OM} and m.hourly_providers_ok == 2
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o is not None and [x[0] for x in o.sources] == [OWM]
    assert _forecast_confirms("Winter Storm Warning", o) is True


def test_condition_stale_refresh_gate_alone(wm_mod, clock):
    """Refresh leg on its own: a STALE-only manager fetches (rows land)."""
    m, calls = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48), om_rows=[],
                    lc_age=timedelta(hours=7))
    assert OWM in calls and OWM in m._hourly


def test_condition_stale_outlook_gate_alone(wm_mod, clock):
    """Outlook leg on its own: rows fetched while fresh, provider then goes
    condition-STALE → still used; UNAVAILABLE → refused."""
    m, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48), om_rows=[])
    m.hass._states[OWM].last_changed = T0 - timedelta(hours=7)
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is not None
    m.hass._states[OWM] = MockState(OWM, "unavailable", {})
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None


@pytest.mark.parametrize("unit,raw,mm", [
    ("mm", 1.5, 1.5), ("cm", 0.15, 1.5), ("in", 0.1, 2.54), ("inches", 0.1, 2.54),
])
def test_precipitation_unit_converted_to_mm(wm_mod, clock, unit, raw, mm):
    m, _ = _mgr(wm_mod, clock, owm_rows=[], p_unit=unit,
                om_rows=_rows(T0, 10, pop=False, temp=30.0, mm=raw))
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.max_precip_mm_no_pop == pytest.approx(mm)


def test_cm_amount_confirms_winter_storm(wm_mod, clock):
    """0.15 cm = 1.5 mm >= 1.0 mm → confirms (passed through raw it would
    read 0.15 and refuse)."""
    m, _ = _mgr(wm_mod, clock, owm_rows=[], p_unit="cm",
                om_rows=_rows(T0, 10, pop=False, temp=30.0, mm=0.15))
    assert _forecast_confirms("Winter Storm Warning",
                              m.hourly_outlook(T0, T0 + timedelta(hours=5)))


def test_apparent_temperature_aggregated(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 10, temp=30.0, app=-5.0),
                om_rows=[])
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.min_temp_f == 30.0 and o.min_apparent_f == -5.0
    assert _forecast_confirms("Wind Chill Warning", o) is True
    assert _forecast_confirms("Extreme Cold Watch", o) is True
    # Hard Freeze is an AIR-temperature product: 30 °F air does not confirm.
    assert _forecast_confirms("Hard Freeze Warning", o) is False


def test_apparent_temperature_celsius_converted(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=[], om_unit="°C",
                om_rows=_rows(T0, 10, pop=False, temp=-1.0, app=-20.0))
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.min_apparent_f == pytest.approx(-4.0)


def test_apparent_absent_falls_back_to_air(wm_mod, clock):
    m, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 10, temp=30.0), om_rows=[])
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.min_apparent_f is None
    assert _forecast_confirms("Wind Chill Warning", o) is False
    m2, _ = _mgr(wm_mod, clock, owm_rows=_rows(T0, 10, temp=20.0), om_rows=[])
    assert _forecast_confirms("Wind Chill Warning",
                              m2.hourly_outlook(T0, T0 + timedelta(hours=5)))


# ---------------------------------------------------------------------------
# Review B fix-up: B-MED-1 — provider recovering after boot triggers ONE
# tracked hourly catch-up instead of waiting for the 30-min timer.
# ---------------------------------------------------------------------------
def _boot_mgr(wm_mod, clock, owm_state):
    clock.t = T0
    hass = MockHass()
    hass._states[OWM] = MockState(OWM, owm_state, {"apparent_temperature": 20,
                                                   "temperature_unit": "°F"})
    hass._states[OWM].last_changed = hass._states[OWM].last_updated = T0
    calls = []

    async def _svc(domain, svc, data, blocking=False, return_response=False):
        calls.append((data["entity_id"], data.get("type")))
        return {data["entity_id"]: {"forecast": _rows(T0, 48)}}
    hass.services = SimpleNamespace(async_call=_svc)
    loop = asyncio.new_event_loop()
    hass.async_create_task = lambda coro, name=None: loop.create_task(coro)
    m = wm_mod.WeatherProviderManager(hass, {CONF_ENERGY_WEATHER_ENTITY: OWM})

    async def _noop():
        return None
    m._refresh_all_providers = _noop  # condition path not under test
    loop.run_until_complete(m._refresh_hourly())
    return m, hass, loop, calls


def _state_event(hass, state):
    hass._states[OWM] = MockState(OWM, state, {"apparent_temperature": 20,
                                               "temperature_unit": "°F"})
    hass._states[OWM].last_changed = hass._states[OWM].last_updated = T0
    return SimpleNamespace(data={"entity_id": OWM,
                                 "new_state": hass._states[OWM]})


def _drain(m, loop):
    while m._pending_refresh_tasks:
        loop.run_until_complete(asyncio.gather(*list(m._pending_refresh_tasks)))


def test_provider_recovery_after_boot_refreshes_hourly_immediately(wm_mod, clock):
    m, hass, loop, calls = _boot_mgr(wm_mod, clock, "unavailable")
    assert OWM not in m._hourly and calls == []
    assert m.hourly_outlook(T0, T0 + timedelta(hours=5)) is None
    # still unavailable / unknown -> no catch-up
    m._handle_provider_state_change(_state_event(hass, "unknown"))
    assert m._hourly_catch_up_task is None  # nothing scheduled while down
    _drain(m, loop)
    assert calls == []
    # provider comes up; clock NOT advanced (no 30-min timer fired)
    m._handle_provider_state_change(_state_event(hass, "snowy"))
    _drain(m, loop)
    assert calls == [(OWM, "hourly")]
    assert m.hourly_providers_ok == 1
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o is not None and o.hours == 5


def test_hourly_catch_up_not_retriggered_once_rows_exist(wm_mod, clock):
    m, hass, loop, calls = _boot_mgr(wm_mod, clock, "unavailable")
    # two state changes before the loop runs -> debounced to ONE fetch
    m._handle_provider_state_change(_state_event(hass, "snowy"))
    m._handle_provider_state_change(_state_event(hass, "cloudy"))
    _drain(m, loop)
    assert calls == [(OWM, "hourly")]
    # rows exist: later condition changes never re-fetch hourly
    for s in ("rainy", "snowy", "cloudy"):
        m._handle_provider_state_change(_state_event(hass, s))
        _drain(m, loop)
    assert calls == [(OWM, "hourly")]
    loop.run_until_complete(m.async_teardown())
    assert m._pending_refresh_tasks == set()


# ---------------------------------------------------------------------------
# Review C fix-up — catch-up task lifecycle + outlook aggregation.
# ---------------------------------------------------------------------------
def test_hourly_catch_up_task_tracked_and_cancelled_by_teardown(wm_mod, clock):
    """Bug Class #19: the catch-up task is in `_pending_refresh_tasks` while
    in flight and `async_teardown` cancels it (a hung provider call must not
    outlive teardown)."""
    m, hass, loop, calls = _boot_mgr(wm_mod, clock, "unavailable")
    gate = asyncio.Event()

    async def _hang(domain, svc, data, blocking=False, return_response=False):
        calls.append((data["entity_id"], data.get("type")))
        await gate.wait()
        return {data["entity_id"]: {"forecast": _rows(T0, 48)}}
    hass.services = SimpleNamespace(async_call=_hang)
    m._handle_provider_state_change(_state_event(hass, "snowy"))
    task = m._hourly_catch_up_task
    assert task is not None
    loop.run_until_complete(asyncio.sleep(0.01))
    assert calls == [(OWM, "hourly")] and not task.done()
    assert task in m._pending_refresh_tasks
    loop.run_until_complete(asyncio.wait_for(m.async_teardown(), 2.0))
    assert task.cancelled()
    assert m._pending_refresh_tasks == set()


def test_second_recovery_after_finished_catch_up_fetches_again(wm_mod, clock):
    """`not pending.done()` debounce: once the first catch-up FINISHED
    without rows (provider returned nothing), a later recovery must fetch
    again — a finished task never blocks the next catch-up."""
    m, hass, loop, calls = _boot_mgr(wm_mod, clock, "unavailable")
    replies = [[], _rows(T0, 48)]

    async def _svc(domain, svc, data, blocking=False, return_response=False):
        calls.append((data["entity_id"], data.get("type")))
        return {data["entity_id"]: {"forecast": replies.pop(0)}}
    hass.services = SimpleNamespace(async_call=_svc)
    m._handle_provider_state_change(_state_event(hass, "snowy"))
    _drain(m, loop)
    assert calls == [(OWM, "hourly")] and OWM not in m._hourly
    assert m._hourly_catch_up_task.done()
    m._handle_provider_state_change(_state_event(hass, "cloudy"))
    _drain(m, loop)
    assert calls == [(OWM, "hourly"), (OWM, "hourly")]
    assert OWM in m._hourly


def test_hourly_catch_up_guards(wm_mod, clock):
    """LOW guards: empty entity_id, missing new_state, and a hass double
    that does not return a Future each schedule/track nothing."""
    m, hass, loop, calls = _boot_mgr(wm_mod, clock, "unavailable")
    ev = _state_event(hass, "snowy")
    m._maybe_hourly_catch_up(ev, "")
    assert m._hourly_catch_up_task is None
    m._maybe_hourly_catch_up(SimpleNamespace(data={"entity_id": OWM,
                                                   "new_state": None}), OWM)
    assert m._hourly_catch_up_task is None
    hass.async_create_task = lambda coro, name=None: None
    m._maybe_hourly_catch_up(ev, OWM)
    assert m._hourly_catch_up_task is None and m._pending_refresh_tasks == set()


def test_outlook_aggregates_conditions_gust_and_floors_slot(wm_mod, clock):
    """`hourly_outlook`: conditions + gusts aggregated; pop wins over amount
    in an hour that has both; a window starting mid-hour is floored to the
    hour slot."""
    rows = _rows(T0, 10, mm=4.0)          # pop 70 AND 4 mm each hour
    rows[2]["condition"] = "lightning"
    rows[3]["wind_gust_speed"] = 45.0
    m, _ = _mgr(wm_mod, clock, owm_rows=rows, om_rows=[])
    o = m.hourly_outlook(T0, T0 + timedelta(hours=5))
    assert o.conditions == frozenset({"snowy", "lightning"})
    assert o.max_gust == 45.0
    assert o.max_pop == 70 and o.max_precip_mm_no_pop is None
    # Mid-hour start: slots T0..T0+5h are all < T0+5h30 → 6 hours.
    o2 = m.hourly_outlook(T0 + timedelta(minutes=30),
                          T0 + timedelta(hours=5, minutes=30))
    assert o2 is not None and o2.hours == 6
    # The aggregated condition alone confirms a convective product.
    norain = _rows(T0, 10, pop=False)
    for r in norain:
        r["condition"] = "cloudy"
    norain[1]["condition"] = "lightning"
    m2, _ = _mgr(wm_mod, clock, owm_rows=norain, om_rows=[])
    assert _forecast_confirms("Severe Thunderstorm Watch",
                              m2.hourly_outlook(T0, T0 + timedelta(hours=5))) is True


def test_refresh_hourly_serialised_by_lock(wm_mod, clock):
    """LOW: concurrent `_refresh_hourly` calls never overlap (WPM-C1)."""
    m, calls = _mgr(wm_mod, clock, owm_rows=_rows(T0, 48), om_rows=[])
    state = {"in": 0, "max": 0}

    async def _svc(domain, svc, data, blocking=False, return_response=False):
        state["in"] += 1
        state["max"] = max(state["max"], state["in"])
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        state["in"] -= 1
        return {data["entity_id"]: {"forecast": _rows(T0, 48)}}
    m.hass.services = SimpleNamespace(async_call=_svc)

    async def _both():
        await asyncio.gather(m._refresh_hourly(), m._refresh_hourly())
    asyncio.new_event_loop().run_until_complete(_both())
    assert state["max"] == 1
