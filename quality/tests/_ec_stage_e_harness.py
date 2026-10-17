"""Shared harness for the EC storm Stage E tests (PLANNING_ec_storm_stage_e.md).

Drives the REAL `BatteryStrategy.determine_mode` through the reserve-governor
shell (`_reserve_governor_harness.make_shell`), with a real NWS alerts entity
and the D-C1 forecast seam (`hourly_outlook`) faked, same as the Stage B/C
tests. `chi_clock` re-pins `dt_util.now/as_local` to America/Chicago (the
base `clock` fixture pins a fixed -05:00 offset, which is wrong in winter and
across DST); it is function-scoped via monkeypatch (restored afterwards).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _SOC,
    _st,
    _dt_modules,
    clock,
    make_shell,
)
from conftest import MockState

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    CONF_INCLEMENT_PREONSET_FLOOR,
    CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

CHI = ZoneInfo("America/Chicago")
UTC = timezone.utc
NWS = "sensor.stage_e_nws"
TS = "sensor.stage_e_ts"
DOMAIN = "universal_room_automation"


def inc_mod():
    """The inclement module the battery imports AT CALL TIME."""
    name = "custom_components.universal_room_automation.domain_coordinators.inclement"
    mod = sys.modules.get(name)
    if mod is None:
        import importlib
        mod = importlib.import_module(name)
    return mod


@pytest.fixture
def chi_clock(clock, monkeypatch):
    from homeassistant.util import dt as real_dt
    saved = real_dt.DEFAULT_TIME_ZONE
    real_dt.set_default_time_zone(CHI)
    for m in _dt_modules():
        monkeypatch.setattr(m, "now", lambda: clock.t.astimezone(CHI), raising=False)
        monkeypatch.setattr(m, "as_local", lambda d: d.astimezone(CHI), raising=False)
    yield clock
    real_dt.set_default_time_zone(saved)


def L(year, month, day, hour, minute=0):
    """Local America/Chicago wall time (DST-correct)."""
    return datetime(year, month, day, hour, minute, tzinfo=CHI)


def alert(event, *, onset, ends, sent=None, code=None, type_="Alert", id_=None):
    a = {"Event": event, "Type": type_, "Status": "Actual",
         "Severity": "Severe", "Certainty": "Likely",
         "ID": id_ or f"{event}|{onset.isoformat()}",
         "Onset": onset.isoformat(), "Ends": ends.isoformat(),
         "Sent": (sent or onset - timedelta(hours=1)).isoformat()}
    if code:
        a["NWSCode"] = code
    return a


def outlook(min_temp=20.0, pop=80.0, mm=None, cond=(), apparent=None):
    Outlook = inc_mod().Outlook
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    return Outlook(window_start=t0, window_end=t0 + timedelta(hours=12),
                   hours=12, min_temp_f=min_temp, max_pop=pop,
                   max_precip_mm_no_pop=mm, max_gust=None,
                   conditions=frozenset(cond),
                   sources=(("weather.owm", "a", "b"),),
                   min_apparent_f=apparent)


class FakeWM:
    """D-C1 seam: `hourly_outlook(start, end)` + condition election."""

    def __init__(self, ol=None, stormy=False):
        self.outlook = ol
        self.stormy = stormy
        self.hourly_fetched_at = None
        self.hourly_providers_ok = 0

    def hourly_outlook(self, start, end):
        return self.outlook(start, end) if callable(self.outlook) else self.outlook

    def current_storm_condition(self, mode="majority"):
        return SimpleNamespace(is_stormy=self.stormy,
                               healthy_provider_count=2 if self.stormy else 0)


def bshell(clock, now, *, soc="40", alerts=(), ol=None, option=True,
           reserve_soc=20, partial=50, knob=80, stormy=False,
           watch_corr=True, extra_opts=None, surplus=0.0):
    clock.t = now.astimezone(UTC)
    c, s = make_shell(clock, soc=soc, reserve_state="0", peak_buffer_target=30)
    s.reserve_soc = reserve_soc
    s._tou = TOURateEngine()
    opts = {
        CONF_INCLEMENT_NWS_ALERTS_ENTITY: NWS,
        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: partial,
        CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD: option,
        CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION: watch_corr,
    }
    if knob is not None:
        opts[CONF_INCLEMENT_PREONSET_FLOOR] = knob
    if extra_opts:
        opts.update(extra_opts)
    s._inclement_config_override = opts
    s._nws_last_updated_entity = lambda eid: TS
    wm = FakeWM(ol, stormy)
    c.hass.data[DOMAIN]["weather_manager"] = wm
    c._test = SimpleNamespace(alerts=list(alerts), soc=soc)
    s._expected_solar_surplus_pct = lambda now, mins: float(surplus)
    return c, s, wm


def feed(c, alerts=None):
    if alerts is not None:
        c._test.alerts = list(alerts)
    c.hass._states[NWS] = MockState(
        NWS, str(len(c._test.alerts)), {"Alerts": c._test.alerts})


def tick(clock, c, s, now, *, soc=None):
    clock.t = now.astimezone(UTC)
    if soc is not None:
        c._test.soc = soc
    _st(c.hass, _SOC, str(c._test.soc), unit="%", lu=clock.t)
    feed(c)
    ts = MockState(TS, now.isoformat(), {})
    ts.last_changed = ts.last_updated = clock.t
    c.hass._states[TS] = ts
    s._last_inclement_decision_at = None
    tou = s._tou
    return s.determine_mode(tou.get_current_period(now), tou.get_season(now), now=now)


def cfg_on(d):
    return any(a["service"] == "switch.turn_on" for a in d["actions"])


def cfg_off(d):
    return any(a["service"] == "switch.turn_off" for a in d["actions"])


def preonset_emitted(d):
    return d["reason"].startswith("Inclement pre-onset")
