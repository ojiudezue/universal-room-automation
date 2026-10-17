"""EC storm Stage B D-B2a / D-B6 / D-B7 / buy NM + Stage C D-C2 gates.

PLANNING_ec_storm_and_blind_decisions.md Rev 3.4 §3 INV-6 (i)-(viii), §6
D-B2a (eligibility, polygon immediate leg, forecast-confirmed buy), D-B6
(pre-onset floor + pre-charge + latch), D-B7 (Storm Guard trip-wire), the
"just enough" observability NM, and §12 cases 18-22.

Every decision test drives the REAL `BatteryStrategy.determine_mode` (frozen
clock, `_reserve_governor_harness`) with a real NWS alerts entity; the
forecast arrives through a fake WeatherProviderManager's `hourly_outlook`
(the D-C1 seam) so the real `_forecast_confirmed_ids` latch runs. Every
negative asserts `reason != "classify_error"` and has a positive control.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _CDT,
    _SOC,
    _st,
    clock,
    make_shell,
)
from conftest import MockState

import custom_components.universal_room_automation.domain_coordinators.inclement as inc
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    ARBITRAGE_PHASE_CHARGE,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    CONF_INCLEMENT_PREONSET_FLOOR,
    CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION,
    INCLEMENT_PRODUCT_TABLE,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)
from custom_components.universal_room_automation.domain_coordinators.inclement import (
    AlertClassifier,
    InclementFusion,
    Outlook,
)

_UTC = timezone.utc


def _inc():
    """The inclement module the battery imports AT CALL TIME (another test
    file may re-exec it into sys.modules after collection)."""
    import sys
    return sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.inclement"
    ]


_NWS = "sensor.stage_b6_nws"
_TS = "sensor.stage_b6_ts"
_DOMAIN = "universal_room_automation"


def T(day, hour, minute=0, month=10, year=2026, tz=_CDT):
    return datetime(year, month, day, hour, minute, tzinfo=tz)


def alert(event, *, onset, ends, sent=None, code=None, type_="Alert", id_=None):
    a = {"Event": event, "Type": type_, "Status": "Actual",
         "Severity": "Severe", "Certainty": "Likely",
         "ID": id_ or f"{event}|{onset.isoformat()}",
         "Onset": onset.isoformat(), "Ends": ends.isoformat(),
         "Sent": (sent or onset - timedelta(hours=1)).isoformat()}
    if code:
        a["NWSCode"] = code
    return a


def ol(min_temp=20.0, pop=80.0, mm=None, cond=()):
    return Outlook(window_start=T(16, 0), window_end=T(17, 0), hours=12,
                   min_temp_f=min_temp, max_pop=pop, max_precip_mm_no_pop=mm,
                   max_gust=None, conditions=frozenset(cond),
                   sources=(("weather.owm", "a", "b"),))


class FakeWM:
    """D-C1 seam: `hourly_outlook(start, end)` + condition election."""

    def __init__(self, outlook=None, stormy=False):
        self.outlook = outlook
        self.stormy = stormy
        self.calls: list = []
        self.hourly_fetched_at = None
        self.hourly_providers_ok = 0

    def hourly_outlook(self, start, end):
        self.calls.append((start, end))
        return self.outlook(start, end) if callable(self.outlook) else self.outlook

    def current_storm_condition(self, mode="majority"):
        return SimpleNamespace(is_stormy=self.stormy,
                               healthy_provider_count=2 if self.stormy else 0)


def bshell(clock, now, *, soc="40", alerts=(), outlook=None, option=True,
           reserve_soc=20, partial=50, knob=80, hw="0", stormy=False,
           watch_corr=True, peak_buffer=30):
    clock.t = now.astimezone(_UTC)
    c, s = make_shell(clock, soc=soc, reserve_state=hw,
                      peak_buffer_target=peak_buffer)
    s.reserve_soc = reserve_soc
    s._tou = TOURateEngine()
    opts = {
        CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS,
        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: partial,
        CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD: option,
        CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION: watch_corr,
    }
    if knob is not None:
        opts[CONF_INCLEMENT_PREONSET_FLOOR] = knob
    s._inclement_config_override = opts
    s._nws_last_updated_entity = lambda eid: _TS
    wm = FakeWM(outlook, stormy)
    c.hass.data[_DOMAIN]["weather_manager"] = wm
    c._test = SimpleNamespace(alerts=list(alerts), soc=soc)
    s._expected_solar_surplus_pct = lambda now, mins: 20.0
    return c, s, wm


def feed(c, alerts=None, *, state=None):
    if alerts is not None:
        c._test.alerts = list(alerts)
    if state == "unavailable":
        c.hass._states[_NWS] = MockState(_NWS, "unavailable", {})
    else:
        c.hass._states[_NWS] = MockState(
            _NWS, str(len(c._test.alerts)), {"Alerts": c._test.alerts})


def tick(clock, c, s, now, *, soc=None, blind=False, healthy=True):
    clock.t = now.astimezone(_UTC)
    if soc is not None:
        c._test.soc = soc
    if blind:
        _st(c.hass, _SOC, "unavailable", lu=clock.t)
        s._soc_lkg = None
        s._soc_lkg_at = None
    else:
        _st(c.hass, _SOC, str(c._test.soc), unit="%", lu=clock.t)
    if c.hass._states.get(_NWS) is None or c.hass._states[_NWS].state != "unavailable":
        feed(c)
    ts = MockState(_TS, now.isoformat(), {})
    ts.last_changed = ts.last_updated = clock.t if healthy else clock.t - timedelta(hours=2)
    c.hass._states[_TS] = ts
    s._last_inclement_decision_at = None
    tou = s._tou
    d = s.determine_mode(tou.get_current_period(now), tou.get_season(now), now=now)
    return d


def sets(d):
    return [a["data"]["value"] for a in d["actions"] if a["service"] == "number.set_value"]


def cfg_on(d):
    return any(a["service"] == "switch.turn_on" for a in d["actions"])


def preonset_emitted(d):
    return d["reason"].startswith("Inclement pre-onset")


def drain():
    loop = asyncio.get_event_loop()
    for _ in range(4):
        loop.run_until_complete(asyncio.sleep(0))


# Base pre-onset scenario: Oct 16 03:00 (bottom rate), WSW Onset 05:00.
# Stage E (expected diff, INV-9): was Onset 15:00 (12 h ahead). A D-B6 buy
# now fires only in the frozen schedule S = the h_req cheapest slots closest
# to Onset; with SOC 40 -> target 80, h_req = 2 -> S = {03:00, 04:00}, so a
# 2 h-ahead Onset keeps every "buy at NOW" assertion meaningful. The 12 h
# case is pinned by the Stage E INV-8/INV-9 tests.
NOW = T(16, 3)
WSW = alert("Winter Storm Warning", sent=T(16, 2), onset=T(16, 5),
            ends=T(17, 3), id_="wsw")


# ===========================================================================
# D-B2a — eligibility column + the two full-hold legs
# ===========================================================================
def test_precharge_eligible_column_values():
    """Independent oracle: the D-B2a evidence table, typed by hand."""
    expected = {
        "Winter Storm Warning": True, "Ice Storm Warning": True,
        "Blizzard Warning": True, "Hard Freeze Warning": True,
        "Extreme Cold Warning": True, "Wind Chill Warning": True,
        "Winter Storm Watch": True, "Hard Freeze Watch": True,
        "Extreme Cold Watch": True, "Wind Chill Watch": True,
        "Severe Thunderstorm Warning": True, "Tornado Warning": True,
        "Extreme Wind Warning": True,
        "Severe Thunderstorm Watch": False, "Tornado Watch": False,
        "Hurricane Warning": False, "Hurricane Watch": False,
        "Tropical Storm Warning": False, "Tropical Storm Watch": False,
        "Wind Advisory": False, "High Wind Warning": False,
        "High Wind Watch": False, "Winter Weather Advisory": False,
        # Stage E E0 (expected diff): Freeze Warning False -> True; Freeze
        # Watch added (True).
        "Freeze Warning": True, "Freeze Watch": True,
        "Wind Chill Advisory": False,
        "Cold Weather Advisory": False,
    }
    got = {row[1]: row[4] for row in INCLEMENT_PRODUCT_TABLE}
    assert got == expected
    polygons = {row[1] for row in INCLEMENT_PRODUCT_TABLE if row[3]}
    assert polygons == {"Severe Thunderstorm Warning", "Tornado Warning",
                        "Extreme Wind Warning"}


def _active(event, now, code=None, mins_ago=30, hours=3, id_=None):
    return alert(event, onset=now - timedelta(minutes=mins_ago),
                 ends=now + timedelta(hours=hours), code=code, id_=id_)


def test_fullhold_precharge_eligible_warn(clock):
    c, s, _ = bshell(clock, NOW, soc="50",
                     alerts=[_active("Winter Storm Warning", NOW, id_="w")],
                     outlook=ol())
    d = tick(clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold" and dec.grid_precharge is True
    assert dec.precharge_leg == "zone" and dec.buy_forecast_confirmed is True
    assert cfg_on(d) and "— pre-charging" in d["reason"]


def test_fullhold_precharge_ineligible_peak_nonpolygon(clock):
    now = T(16, 18)  # shoulder top rate
    c, s, _ = bshell(clock, now, soc="50",
                     alerts=[_active("Winter Storm Warning", now, id_="w")],
                     outlook=ol())
    d = tick(clock, c, s, now)
    assert s._last_inclement_decision.grid_precharge is False
    assert "holding charge" in d["reason"] and not cfg_on(d)
    # Control: same at bottom rate.
    c, s, _ = bshell(clock, NOW, soc="50",
                     alerts=[_active("Winter Storm Warning", NOW, id_="w")],
                     outlook=ol())
    assert cfg_on(tick(clock, c, s, NOW))


@pytest.mark.parametrize("now", [
    T(15, 17, month=6),   # summer peak
    T(16, 18),            # shoulder mid_peak (top)
    T(16, 3),             # bottom
])
def test_polygon_topup_verified_local_any_tou(clock, now):
    svw = _active("Severe Thunderstorm Warning", now, code="SVW",
                  mins_ago=20, hours=1, id_="svw")
    c, s, _ = bshell(clock, now, soc="55", alerts=[svw], outlook=None)
    d = tick(clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.grid_precharge is True and dec.precharge_leg == "polygon"
    assert cfg_on(d)


def test_polygon_topup_unverified_locality_refused(clock, monkeypatch):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW",
                  mins_ago=20, hours=1, id_="svw")
    monkeypatch.setattr(_inc(), "INCLEMENT_POINT_FEED_POLYGON_EXACT", False)
    monkeypatch.setattr(_inc(), "INCLEMENT_UNVERIFIED_POLYGON_TIER", "table")
    c, s, _ = bshell(clock, now, soc="55", alerts=[svw])
    d = tick(clock, c, s, now)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    assert s._last_inclement_decision.grid_precharge is False and not cfg_on(d)
    monkeypatch.setattr(_inc(), "INCLEMENT_POINT_FEED_POLYGON_EXACT", True)
    c, s, _ = bshell(clock, now, soc="55", alerts=[svw])
    assert cfg_on(tick(clock, c, s, now))


def _poly_flag(svw, now):
    return _inc().AlertClassifier().classify([svw], now=now).polygon_topup_active


def test_polygon_topup_cap_expires(monkeypatch):
    start = T(16, 15)
    svw = alert("Severe Thunderstorm Warning", code="SVW", onset=start,
                ends=start + timedelta(minutes=90), id_="svw")
    assert _poly_flag(svw, start + timedelta(minutes=59)) is True
    assert _poly_flag(svw, start + timedelta(minutes=60)) is True   # inclusive
    assert _poly_flag(svw, start + timedelta(minutes=61)) is False
    # The warning's own end binds first.
    short = alert("Severe Thunderstorm Warning", code="SVW", onset=start,
                  ends=start + timedelta(minutes=40), id_="s2")
    assert _poly_flag(short, start + timedelta(minutes=41)) is False
    # An Update re-stamps Onset → restarts the per-ID window, never past end.
    upd = alert("Severe Thunderstorm Warning", code="SVW", type_="Update",
                onset=start + timedelta(minutes=50),
                ends=start + timedelta(minutes=70), id_="svw-u")
    assert _poly_flag(upd, start + timedelta(minutes=65)) is True
    assert _poly_flag(upd, start + timedelta(minutes=71)) is False
    # DST fall-back night (2026-11-01 02:00 CDT → 01:00 CST): Onset 01:30 CDT.
    cst = timezone(timedelta(hours=-6))
    o = datetime(2026, 11, 1, 1, 30, tzinfo=_CDT)
    dst = alert("Severe Thunderstorm Warning", code="SVW", onset=o,
                ends=datetime(2026, 11, 1, 3, 0, tzinfo=cst), id_="dst")
    assert _poly_flag(dst, datetime(2026, 11, 1, 1, 30, tzinfo=cst)) is True   # +60
    assert _poly_flag(dst, datetime(2026, 11, 1, 1, 31, tzinfo=cst)) is False  # +61
    # Cap 0 = immediate leg off.
    monkeypatch.setattr(_inc(), "INCLEMENT_POLYGON_TOPUP_MAX_MIN", 0)
    assert _poly_flag(svw, start + timedelta(minutes=5)) is False


def test_polygon_topup_stops_at_threshold(clock):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=20,
                  hours=1, id_="svw")
    c, s, _ = bshell(clock, now, soc="90", alerts=[svw])
    assert not cfg_on(tick(clock, c, s, now))
    assert s._last_inclement_decision.grid_precharge is False
    c, s, _ = bshell(clock, now, soc="89", alerts=[svw])
    assert cfg_on(tick(clock, c, s, now))


def test_polygon_topup_option_off(clock):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=20,
                  hours=1, id_="svw")
    c, s, _ = bshell(clock, now, soc="55", alerts=[svw], option=False)
    assert not cfg_on(tick(clock, c, s, now))


def test_polygon_topup_respects_enabled_import_guard(clock):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=20,
                  hours=1, id_="svw")
    for enabled, tripped, expect in ((True, True, False), (False, True, True),
                                     (True, False, True)):
        c, s, _ = bshell(clock, now, soc="55", alerts=[svw])
        s._arbitrage_grid_import_guard_enabled = enabled
        s._grid_import_guard_triggered = lambda t=tripped: t
        d = tick(clock, c, s, now)
        assert cfg_on(d) is expect, (enabled, tripped)


def test_severe_thunderstorm_watch_never_precharges(clock):
    sva = _active("Severe Thunderstorm Watch", NOW, id_="sva")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[sva], outlook=ol(cond=("pouring",)),
                     watch_corr=False)
    d = tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    assert not cfg_on(d)
    # Control (synthetic: corroborated + forecast-confirmed winter watch).
    wsa = _active("Winter Storm Watch", NOW, id_="wsa")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[wsa], outlook=ol(),
                     watch_corr=False)
    assert cfg_on(tick(clock, c, s, NOW))


def test_fullhold_precharge_ineligible_corroborated_watch(clock):
    sva = _active("Severe Thunderstorm Watch", NOW, id_="sva")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[sva], outlook=ol(), stormy=True)
    d = tick(clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold" and dec.grid_precharge is False
    assert not cfg_on(d)
    wsa = _active("Winter Storm Watch", NOW, id_="wsa")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[wsa], outlook=ol(), stormy=True)
    assert cfg_on(tick(clock, c, s, NOW))


def test_fullhold_precharge_mixed_contributors_any(clock):
    now = NOW
    svw_old = _active("Severe Thunderstorm Warning", now, code="SVW",
                      mins_ago=120, hours=1, id_="svw")  # past its cap
    wsw = _active("Winter Storm Warning", now, id_="w")
    c, s, _ = bshell(clock, now, soc="50", alerts=[svw_old, wsw], outlook=ol())
    d = tick(clock, c, s, now)
    assert s._last_inclement_decision.precharge_leg == "zone" and cfg_on(d)
    # Without the WSW, the expired SVW alone does not buy.
    c, s, _ = bshell(clock, now, soc="50", alerts=[svw_old], outlook=ol())
    assert not cfg_on(tick(clock, c, s, now))


def test_precharge_flags_helper_never_drops_hold(clock, monkeypatch):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=20,
                  hours=1, id_="svw")
    # A value that makes int() raise INSIDE the guarded helper.
    monkeypatch.setattr(_inc(), "INCLEMENT_POLYGON_TOPUP_MAX_MIN", object())
    c, s, _ = bshell(clock, now, soc="55", alerts=[svw])
    d = tick(clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold" and dec.reason != "classify_error"
    cls = s._last_inclement_classification
    assert (cls.precharge_eligible, cls.polygon_topup_active,
            cls.prepare_precharge_eligible) == (False, False, False)
    assert not cfg_on(d)


def test_storm_threshold_constructor_arg_binds():
    """Two named thresholds (L1): fusion's constructor arg and the emission
    site's DEFAULT_STORM_CHARGE_THRESHOLD; the stricter wins (both apply)."""
    now = T(16, 3)
    cls = AlertClassifier().classify(
        [_active("Winter Storm Warning", now, id_="w")], now=now)
    f = InclementFusion(reserve_soc=20, grid_precharge_on_hold=True,
                        storm_charge_threshold=80)
    d = f.decide(None, cls, False, 0, "off_peak", now, 85,
                 bottom_rate=True, forecast_confirmed_ids={"w"})
    assert d.grid_precharge is False
    d = f.decide(None, cls, False, 0, "off_peak", now, 75,
                 bottom_rate=True, forecast_confirmed_ids={"w"})
    assert d.grid_precharge is True


# ===========================================================================
# INV-6(vii) — forecast-confirmed zone buys (Stage C gate)
# ===========================================================================
def test_zone_buy_requires_forecast_confirmation(clock):
    wsw = _active("Winter Storm Warning", NOW, id_="w")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[wsw], outlook=ol())
    assert cfg_on(tick(clock, c, s, NOW))
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[wsw], outlook=ol(min_temp=40))
    d = tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    assert not cfg_on(d)


def test_zone_buy_forecast_none_no_buy_floor_holds(clock):
    wsw = _active("Winter Storm Warning", NOW, id_="w")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[wsw], outlook=None)
    d = tick(clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold" and dec.reserve_floor == 50
    assert s._tick_reserve_floor == 50 and not cfg_on(d)


def test_condition_corroboration_does_not_authorize_buy(clock):
    wsa = _active("Winter Storm Watch", NOW, id_="wsa")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[wsa], outlook=None, stormy=True)
    d = tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    assert not cfg_on(d)


def test_polygon_leg_exempt_from_forecast(clock):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=20,
                  hours=1, id_="svw")
    c, s, wm = bshell(clock, now, soc="55", alerts=[svw], outlook=None)
    assert cfg_on(tick(clock, c, s, now))
    assert wm.calls == []  # polygon rows never query the forecast


def test_zone_buy_forecast_latch_no_flap(clock):
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 6), id_="w")
    c, s, wm = bshell(clock, NOW, soc="50", alerts=[wsw], outlook=ol())
    assert cfg_on(tick(clock, c, s, NOW))
    wm.outlook = None  # provider goes down
    assert s._last_inclement_decision.buy_forecast_confirmed is True
    tick(clock, c, s, T(16, 4))
    assert s._last_inclement_decision.buy_forecast_confirmed is True
    assert "w" in s._forecast_confirm_latch
    tick(clock, c, s, T(16, 6, 1))  # past the alert's end
    assert "w" not in s._forecast_confirm_latch


# ===========================================================================
# Stage C D-C2 — forecast corroboration of watches
# ===========================================================================
def test_forecast_confirms_freeze_watch(clock):
    hfa = _active("Hard Freeze Watch", NOW, id_="hfa")
    c, s, _ = bshell(clock, NOW, alerts=[hfa], outlook=ol(min_temp=22), option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    c, s, _ = bshell(clock, NOW, alerts=[hfa], outlook=ol(min_temp=40), option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "partial_hold"


def test_forecast_latch_no_flap(clock):
    hfa = alert("Hard Freeze Watch", onset=T(16, 1), ends=T(16, 9), id_="hfa")
    c, s, wm = bshell(clock, NOW, alerts=[hfa], outlook=ol(min_temp=22), option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    wm.outlook = ol(min_temp=35)
    tick(clock, c, s, T(16, 4))
    assert s._last_inclement_decision.hold_depth == "full_hold"


def test_forecast_never_demotes_warn(clock):
    wsw = _active("Winter Storm Warning", NOW, id_="w")
    c, s, _ = bshell(clock, NOW, alerts=[wsw], outlook=ol(min_temp=40), option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"


def test_forecast_none_is_noop(clock):
    hfa = _active("Hard Freeze Watch", NOW, id_="hfa")
    c, s, _ = bshell(clock, NOW, alerts=[hfa], outlook=None, option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "partial_hold"
    assert s._forecast_confirm_latch == {}


def test_forecast_window_capped(clock):
    long = alert("Hard Freeze Watch", onset=NOW - timedelta(hours=1),
                 ends=NOW + timedelta(hours=100), id_="long")
    c, s, wm = bshell(clock, NOW, alerts=[long], outlook=None, option=False)
    tick(clock, c, s, NOW)
    (start, end), = wm.calls
    assert start == NOW
    assert end - start == timedelta(hours=48)
    # A future (prepare) alert: window starts at its Onset.
    fut = alert("Winter Storm Warning", onset=NOW + timedelta(hours=5),
                ends=NOW + timedelta(hours=9), id_="fut")
    c, s, wm = bshell(clock, NOW, alerts=[fut], outlook=None, option=False)
    tick(clock, c, s, NOW)
    assert wm.calls == [(NOW + timedelta(hours=5), NOW + timedelta(hours=9))]


@pytest.mark.parametrize("event,outlook,expected", [
    ("Hard Freeze Watch", ol(min_temp=28), True),
    ("Hard Freeze Watch", ol(min_temp=29), False),
    ("Winter Storm Warning", ol(min_temp=32, pop=50), True),
    ("Winter Storm Warning", ol(min_temp=32, pop=49), False),
    ("Winter Storm Warning", ol(min_temp=33, pop=90), False),
    ("Winter Storm Warning", ol(min_temp=30, pop=None, mm=1.0), True),
    ("Winter Storm Warning", ol(min_temp=30, pop=None, mm=0.9), False),
    # Operator 2026-10-17: storm condition alone (pop 10) no longer confirms.
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=10, cond=("lightning",)), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=10), False),
    ("Wind Advisory", ol(), False),
    ("Winter Storm Warning", None, False),
])
def test_forecast_confirms_predicates(event, outlook, expected):
    assert inc.forecast_confirms(event, outlook) is expected


# ===========================================================================
# D-B6 — pre-onset prepare floor
# ===========================================================================
def test_preonset_floor_registered_before_onset(clock):
    """§3 INV-6 repro: reserve 20, partial 50, knob 80, WSW Sent 06:00
    Onset 21:00, Oct 18:00, SOC 70 sighted → every reserve write >= 80."""
    now = T(16, 18)
    wsw = alert("Winter Storm Warning", sent=T(16, 6), onset=T(16, 21),
                ends=T(17, 9), id_="wsw")
    c, s, _ = bshell(clock, now, soc="70", alerts=[wsw], option=False)
    d = tick(clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "allow_discharge" and dec.reason != "classify_error"
    assert dec.preonset_floor == 80 and s._tick_reserve_floor == 80
    assert sets(d) and all(v >= 80 for v in sets(d))
    assert s._last_reserve_level_desired == 80
    assert "+ pre-onset floor 80" in d["reason"]


def test_preonset_handoff_at_onset(clock):
    wsw = alert("Winter Storm Warning", sent=T(16, 6), onset=T(16, 21),
                ends=T(17, 9), id_="wsw")
    c, s, _ = bshell(clock, T(16, 20), soc="70", alerts=[wsw], option=False)
    tick(clock, c, s, T(16, 20))
    assert s._last_inclement_decision.preonset_floor == 80
    tick(clock, c, s, T(16, 21))
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold" and dec.preonset_floor is None


def test_preonset_floor_none_outside_lead(clock):
    wsw = alert("Winter Storm Warning", sent=T(16, 1), onset=T(16, 21),
                ends=T(17, 9), id_="wsw")
    c, s, _ = bshell(clock, T(16, 2), alerts=[wsw], option=False)
    tick(clock, c, s, T(16, 2))                       # 19 h ahead
    assert s._last_inclement_decision.preonset_floor is None
    assert s._tick_reserve_floor is None
    assert s._last_inclement_decision.reason != "classify_error"
    tick(clock, c, s, T(16, 8, 59))                   # 12 h 01 min ahead
    assert s._last_inclement_decision.preonset_floor is None
    tick(clock, c, s, T(16, 9, 0))                    # exactly 12 h: in
    # Stage E (expected diff, ref = TARGET): at 4-12 h the VALUE is set and
    # the floor is NOT registered (INV-8: from T - 4 h with no buy).
    assert s._last_inclement_decision.preonset_target == 80
    assert s._last_inclement_decision.preonset_floor is None
    assert s._tick_reserve_floor is None


def test_preonset_lead_zero_disables(clock, monkeypatch):
    monkeypatch.setattr(_inc(), "INCLEMENT_PREONSET_LEAD_H", 0)
    wsw = alert("Winter Storm Warning", onset=T(16, 4), ends=T(17, 9), id_="wsw")
    c, s, _ = bshell(clock, NOW, alerts=[wsw])
    d = tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor is None
    assert not preonset_emitted(d)
    monkeypatch.setattr(_inc(), "INCLEMENT_PREONSET_LEAD_H", 12)
    tick(clock, c, s, T(16, 3, 5))
    assert s._last_inclement_decision.preonset_floor == 80


def test_preonset_watch_floor_uncorroborated(clock):
    # Stage E (expected diff): Onset 09:00 -> 05:00 (inside the floor lead and
    # the buy schedule), so the registered floor and the buy stay observable.
    wsa = alert("Winter Storm Watch", onset=T(16, 5), ends=T(17, 9), id_="wsa")
    c, s, _ = bshell(clock, NOW, alerts=[wsa], outlook=None)
    d = tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor == 50
    assert s._last_inclement_decision.preonset_precharge is False
    assert not preonset_emitted(d)
    c, s, _ = bshell(clock, NOW, alerts=[wsa], outlook=ol())
    d = tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor == 80
    assert preonset_emitted(d)


def test_preonset_forecast_raise_only(clock):
    # A non-confirming forecast never lowers a warn's prepare floor.
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol(min_temp=60, pop=0),
                     option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor == 80
    # A forecast alone never creates a floor.
    c, s, _ = bshell(clock, NOW, alerts=[], outlook=ol(), option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor is None


def test_preonset_polygon_excluded(clock):
    svw = alert("Severe Thunderstorm Warning", code="SVW",
                onset=NOW + timedelta(minutes=30),
                ends=NOW + timedelta(minutes=90), id_="svw")
    c, s, _ = bshell(clock, NOW, alerts=[svw])
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor is None
    assert s._last_inclement_classification.prepare_alerts == ()


def test_preonset_partial_hold_takes_max(clock):
    wsa = _active("Winter Storm Watch", NOW, id_="wsa")      # partial 50
    # Stage E (expected diff): Onset +10 h -> +3 h (the floor registers from
    # T - 4 h with no buy; at +10 h only the value is set).
    wsw = alert("Winter Storm Warning", onset=NOW + timedelta(hours=3),
                ends=NOW + timedelta(hours=20), id_="wsw")
    c, s, _ = bshell(clock, NOW, alerts=[wsa, wsw], option=False)
    tick(clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "partial_hold" and dec.reserve_floor == 50
    assert dec.preonset_floor == 80 and s._tick_reserve_floor == 80


def _gate_case(clock, case):
    """Returns (d, s) for one INV-6(iii) gate; case 'control' = all pass."""
    now = NOW
    alerts = [WSW]
    kw = {}
    blind = False
    outlook = ol()
    pre_tick = None
    if case == "ineligible":
        alerts = [alert("Severe Thunderstorm Watch", onset=T(16, 5),
                        ends=T(17, 3), id_="sva")]
        outlook = ol(cond=("lightning",))
    elif case == "option_off":
        kw["option"] = False
    elif case == "not_bottom":
        now = T(16, 18)
        alerts = [alert("Winter Storm Warning", onset=T(16, 23), ends=T(17, 9),
                        id_="wsw")]
    elif case == "soc_at_floor":
        kw["soc"] = "85"
        # A non-positive solar term must not let SOC >= floor through the
        # solar test: the SOC < floor conjunct alone refuses.
        pre_tick = lambda s: setattr(s, "_expected_solar_surplus_pct",
                                     lambda n, m: -10.0)
    elif case == "solar_closes":
        pre_tick = lambda s: setattr(s, "_expected_solar_surplus_pct",
                                     lambda n, m: 45.0)
    elif case == "fully_blind":
        blind = True
    elif case == "uncorroborated_watch":
        alerts = [alert("Winter Storm Watch", onset=T(16, 5), ends=T(17, 3),
                        id_="wsa")]
        outlook = None
    elif case == "arbitrage_charge":
        pre_tick = lambda s: setattr(s, "_arbitrage_phase", ARBITRAGE_PHASE_CHARGE)
    elif case == "attain_charging":
        pre_tick = lambda s: setattr(s, "_attain_state", "charging")
    elif case == "forecast_unconfirmed":
        outlook = None
    elif case == "degraded_stale":
        # Stage E: Onset 04:00 so the decision tick (02:29) is in S.
        alerts = [alert("Winter Storm Warning", onset=T(16, 4), ends=T(17, 3),
                        id_="wsw")]
    elif case == "hour_not_in_schedule":
        # Stage E INV-9 refusal: every other gate passes, but 03:00 is not
        # one of the cheapest slots closest to a 15:00 Onset ({13:00, 14:00}).
        alerts = [alert("Winter Storm Warning", onset=T(16, 15), ends=T(17, 3),
                        id_="wsw")]
    c, s, _ = bshell(clock, now, alerts=alerts, outlook=outlook, **kw)
    if pre_tick:
        pre_tick(s)
    if case == "degraded_stale":
        # Envoy blind, SOC from LKG; the decision is 31 min older than the
        # frozen wall clock → `_precharge_refused_on_blind` refuses.
        clock.t = now.astimezone(_UTC)
        _st(c.hass, _SOC, "40", unit="%", lu=clock.t - timedelta(hours=1))
        s._soc_lkg = 40.0
        s._soc_lkg_at = clock.t - timedelta(seconds=30)
        feed(c)
        ts = MockState(_TS, "x", {})
        ts.last_changed = clock.t
        c.hass._states[_TS] = ts
        s._last_inclement_decision_at = None
        d = s.determine_mode("off_peak", "shoulder",
                             now=now - timedelta(minutes=31))
        assert d["envoy_available"] is False
        return d, s
    return tick(clock, c, s, now, blind=blind), s


_REFUSALS = ["ineligible", "option_off", "not_bottom", "soc_at_floor",
             "solar_closes", "fully_blind", "uncorroborated_watch",
             "degraded_stale", "arbitrage_charge", "attain_charging",
             "forecast_unconfirmed", "hour_not_in_schedule"]


@pytest.mark.parametrize("case", _REFUSALS)
def test_preonset_precharge_gates(clock, case):
    d, s = _gate_case(clock, case)
    dec = s._last_inclement_decision
    assert dec.reason != "classify_error"
    assert not preonset_emitted(d)
    assert not any(a["service"] == "switch.turn_on" for a in d["actions"])
    # Stage E (expected diff, ref = TARGET): the VALUE is set in every case;
    # the floor is registered wherever Onset is inside the 4 h floor lead.
    assert dec.preonset_target is not None
    if case not in ("not_bottom", "hour_not_in_schedule"):
        assert dec.preonset_floor is not None and s._tick_reserve_floor is not None


def test_preonset_precharge_gates_positive_control(clock):
    d, s = _gate_case(clock, "control")
    assert preonset_emitted(d) and cfg_on(d)
    assert s._preonset_precharge_latch == {"wsw": "engaged"}
    assert s._tick_grid_buy["leg"] == "preonset"
    # Latch entries drop when the alert leaves the prepare set (Onset).
    c = s._coord
    tick(clock, c, s, T(16, 15), soc="95")   # active hold, SOC above threshold
    assert s._preonset_precharge_latch == {}
    # Per-tick stamp is entry-reset: a non-buy tick reads None.
    assert s._tick_grid_buy is None


def test_polygon_buy_notifies_once_via_determine_mode(clock):
    now = T(16, 18)
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=20,
                  hours=1, id_="svw")
    c, s, _ = bshell(clock, now, soc="55", alerts=[])
    tick(clock, c, s, now)
    c._grid_buy_notify_tick()                 # seed
    feed(c, [svw])
    tick(clock, c, s, T(16, 18, 5))
    assert s._tick_grid_buy["leg"] == "polygon"
    c._grid_buy_notify_tick()
    drain()
    assert len(c.nm) == 1 and "verified-local" in c.nm[0]["message"]


def test_preonset_negatives_not_classify_error(clock):
    # The same alert shifted into the window produces the floor (control for
    # the out-of-lead negative).
    far = alert("Winter Storm Warning", onset=NOW + timedelta(hours=20),
                ends=NOW + timedelta(hours=30), id_="far")
    c, s, _ = bshell(clock, NOW, alerts=[far])
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.reason != "classify_error"
    assert s._last_inclement_decision.preonset_floor is None
    tick(clock, c, s, NOW + timedelta(hours=9))
    # Stage E (expected diff, ref = TARGET): 11 h ahead -> value only.
    assert s._last_inclement_decision.preonset_target == 80
    assert s._last_inclement_decision.preonset_floor is None


def test_preonset_precharge_routes_through_result(clock):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol(), hw="0")
    d = tick(clock, c, s, NOW)
    assert cfg_on(d)
    assert sets(d) == [80]
    assert s._last_charge_from_grid_desired is True
    assert s._last_reserve_level_desired == 80
    assert d["charge_from_grid"] is True


def test_preonset_reason_local_time_and_event(clock):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    d = tick(clock, c, s, NOW)
    assert d["reason"].startswith(
        "Inclement pre-onset (Winter Storm Warning, onset 05:00) — pre-charging"
    )


def _cfg_seq(clock, c, s, steps):
    out = []
    for now, soc in steps:
        d = tick(clock, c, s, now, soc=soc)
        out.append(bool(d["charge_from_grid"]))
    return out


def _on_off_transitions(seq):
    return sum(1 for a, b in zip(seq, seq[1:]) if a and not b)


def test_preonset_precharge_latch_no_flap(clock):
    c, s, _ = bshell(clock, NOW, soc="59", alerts=[WSW], outlook=ol())
    solar = {"v": 20.0}
    s._expected_solar_surplus_pct = lambda n, m: solar["v"]
    assert tick(clock, c, s, NOW, soc="59")["charge_from_grid"] is True
    solar["v"] = 25.0  # 59 + 25 >= 80: the solar test would now refuse
    assert tick(clock, c, s, T(16, 3, 5), soc="59")["charge_from_grid"] is True
    solar["v"] = 0.0
    seq = _cfg_seq(clock, c, s, [(T(16, 3, 10), "79"), (T(16, 3, 15), "80"),
                                 (T(16, 3, 20), "79"), (T(16, 3, 25), "78")])
    assert seq == [True, False, False, False]
    assert _on_off_transitions([True] + seq) == 1
    assert s._preonset_precharge_latch["wsw"] == "reached"


def test_preonset_precharge_reached_never_reengages(clock):
    c, s, _ = bshell(clock, NOW, soc="59", alerts=[WSW], outlook=ol())
    s._expected_solar_surplus_pct = lambda n, m: 0.0
    tick(clock, c, s, NOW, soc="59")
    tick(clock, c, s, T(16, 3, 5), soc="80")
    assert s._preonset_precharge_latch["wsw"] == "reached"
    d = tick(clock, c, s, T(16, 3, 10), soc="40")
    assert not preonset_emitted(d)
    # A second alert with a different ID is evaluated independently.
    wsw2 = alert("Winter Storm Warning", onset=T(16, 5), ends=T(17, 3), id_="wsw2")
    feed(c, [wsw2])
    d = tick(clock, c, s, T(16, 3, 15), soc="40")
    assert preonset_emitted(d)


def test_preonset_precharge_yields_to_arbitrage_charge(clock):
    d, s = _gate_case(clock, "arbitrage_charge")
    assert not preonset_emitted(d)


def test_preonset_precharge_yields_to_attain_charging(clock):
    d, s = _gate_case(clock, "attain_charging")
    assert not preonset_emitted(d)


def test_preonset_floor_below_buffer_target_option_false_no_refill(clock):
    """§12 5b: option False → the prepare floor blocks discharge, never
    refills (no pre-onset CFG); every reserve write >= floor."""
    c, s, _ = bshell(clock, NOW, soc="40", alerts=[WSW], outlook=ol(),
                     option=False, peak_buffer=60)
    s._arbitrage_enabled = True
    d = tick(clock, c, s, NOW)
    assert not preonset_emitted(d)
    assert all(v >= 80 for v in sets(d))
    assert s._last_reserve_level_desired >= 80


def test_preonset_floor_reaches_dp_drain_stamp(clock):
    c, s, _ = bshell(clock, NOW, soc="70", alerts=[WSW], option=False)
    tick(clock, c, s, NOW)
    assert s._offpeak_drain_branch_target == 80
    c, s, _ = bshell(clock, NOW, soc="70", alerts=[], option=False)
    tick(clock, c, s, NOW)
    assert s._offpeak_drain_branch_target is not None
    assert s._offpeak_drain_branch_target < 80


def test_preonset_precharge_solar_minutes_arg_real_helper(clock):
    """The int minutes reach the REAL `_expected_solar_surplus_pct` (spied,
    not replaced)."""
    cases = [
        (T(16, 23), T(17, 10), 660),                      # across midnight
        (T(16, 3), T(16, 15), 720),                       # pre-dawn
        (datetime(2026, 11, 1, 0, 30, tzinfo=_CDT),       # DST fall-back night
         datetime(2026, 11, 1, 11, 0, tzinfo=timezone(timedelta(hours=-6))),
         690),
    ]
    for now, onset, mins in cases:
        a = alert("Winter Storm Warning", onset=onset,
                  ends=onset + timedelta(hours=6), id_=f"w{mins}")
        c, s, _ = bshell(clock, now, alerts=[a], outlook=ol())
        del s._expected_solar_surplus_pct           # back to the real method
        seen = []
        real = type(s)._expected_solar_surplus_pct

        def spy(now_, m, _real=real, _s=s):
            seen.append(m)
            return _real(_s, now_, m)
        s._expected_solar_surplus_pct = spy
        tick(clock, c, s, now)
        assert seen and seen[-1] == mins and isinstance(seen[-1], int), (now, seen)


def test_preonset_solar_minutes_lead_48(clock, monkeypatch):
    monkeypatch.setattr(_inc(), "INCLEMENT_PREONSET_LEAD_H", 48)
    a = alert("Winter Storm Warning", onset=NOW + timedelta(hours=40),
              ends=NOW + timedelta(hours=50), id_="w48")
    c, s, _ = bshell(clock, NOW, alerts=[a], outlook=ol())
    seen = []
    s._expected_solar_surplus_pct = lambda n, m: seen.append(m) or 0.0
    tick(clock, c, s, NOW)
    assert seen == [2400]


def test_preonset_blind_hold_and_release(clock):
    # Stage E: Onset 11:00 -> 05:00 (registered floor inside the 4 h lead).
    wsw = alert("Winter Storm Warning", onset=T(16, 5), ends=T(17, 3), id_="wsw")
    c, s, _ = bshell(clock, NOW, alerts=[wsw], hw="0")
    d = tick(clock, c, s, NOW, blind=True)
    assert d["envoy_available"] is False
    assert sets(d) == [80] and d["reason"].startswith("Blind hold — ")
    c.hass._states["sensor.ab_envoy_battery"] = c.hass._states[_SOC]
    from _reserve_governor_harness import RESERVE_WRITE_EID
    for eid in (RESERVE_WRITE_EID,):
        _st(c.hass, eid, "80", unit="%")
    d = tick(clock, c, s, T(16, 3, 5), blind=True)
    assert sets(d) == []
    cancel = alert("Winter Storm Warning", type_="Cancel", onset=T(16, 5),
                   ends=T(17, 3), id_="wsw-c")
    feed(c, [cancel])
    d = tick(clock, c, s, T(16, 3, 10), blind=True)
    assert d["reason"].startswith("Blind release — ")
    assert sets(d) == [0]


def test_preonset_memory_survives_feed_loss(clock):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], option=False)
    tick(clock, c, s, NOW)
    feed(c, state="unavailable")
    tick(clock, c, s, T(16, 4))
    assert s._last_inclement_decision.preonset_floor == 80
    assert s._inclement_alerts_stale is True


def test_preonset_latch_interleaved_with_fullhold_topup(clock):
    """H2 trace: D-B6 engaged → a verified-local SVW full_hold top-up owns
    the emission (shadow). (a) SOC crosses the floor while shadowed →
    latch reached, D-B6 never resumes. (b) SOC stays below → D-B6 resumes."""
    for crossed in (True, False):
        c, s, _ = bshell(clock, NOW, soc="60", alerts=[WSW], outlook=ol())
        s._expected_solar_surplus_pct = lambda n, m: 0.0
        assert preonset_emitted(tick(clock, c, s, NOW, soc="60"))
        t1 = T(16, 3, 5)
        svw = alert("Severe Thunderstorm Warning", code="SVW", onset=t1,
                    ends=t1 + timedelta(minutes=30), id_="svw")
        feed(c, [WSW, svw])
        d = tick(clock, c, s, t1, soc="85" if crossed else "70")
        assert s._last_inclement_decision.precharge_leg == "polygon"
        assert "— pre-charging" in d["reason"]
        feed(c, [WSW])
        # Crossed: SOC sags back below the floor once the shadow ends — the
        # latch must already read "reached" (advanced DURING the shadow).
        d = tick(clock, c, s, T(16, 3, 40), soc="79" if crossed else "70")
        if crossed:
            assert s._preonset_precharge_latch["wsw"] == "reached"
            assert not preonset_emitted(d)
        else:
            assert s._preonset_precharge_latch["wsw"] == "engaged"
            assert preonset_emitted(d)


def test_inclement_preonset_attr_shape(clock):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    tick(clock, c, s, NOW)
    a = s._inclement_attrs()
    # Stage E (expected diff): new exact dict (value, active, floor_from,
    # buy_hours, event_time, event_time_source + the existing keys).
    assert a["inclement_preonset"] == {
        "floor": 80, "active": True,
        "floor_from": "2026-10-16T01:00:00-05:00",
        "buy_hours": ["2026-10-16T03:00:00-05:00", "2026-10-16T04:00:00-05:00"],
        "event_time": "2026-10-16T05:00:00-05:00", "event_time_source": "onset",
        "start": "2026-10-16T05:00:00-05:00",
        "event": "Winter Storm Warning", "class": "warn",
        "precharge": True, "latch": "engaged",
    }
    # 4-12 h ahead: the attr is non-null with active False (value only).
    far = alert("Winter Storm Warning", onset=T(16, 13), ends=T(17, 3), id_="far")
    c2, s2, _ = bshell(clock, NOW, alerts=[far], outlook=None)
    tick(clock, c2, s2, NOW)
    p2 = s2._inclement_attrs()["inclement_preonset"]
    assert p2["floor"] == 80 and p2["active"] is False
    assert p2["floor_from"] == "2026-10-16T09:00:00-05:00"
    assert p2["buy_hours"] == []
    assert a["inclement_buy_forecast"]["outlook"] == "ok"
    c, s, _ = bshell(clock, NOW, alerts=[], outlook=None)
    tick(clock, c, s, NOW)
    assert s._inclement_attrs()["inclement_preonset"] is None


def test_reserve_row_carries_tick_preonset_floor(clock):
    now = T(16, 18)
    wsw = alert("Winter Storm Warning", onset=T(16, 21), ends=T(17, 9), id_="wsw")
    c, s, _ = bshell(clock, now, soc="70", alerts=[wsw], option=False)
    tick(clock, c, s, now)
    from custom_components.universal_room_automation.domain_coordinators.hvac_strategy import (
        WriteStatus,
    )
    c._last_reserve_row_key = None
    c._record_reserve_dispatch(status=WriteStatus.APPLIED, path="timer",
                               target="number.x", value=80, reason="r")
    drain()
    import json
    row = json.loads(c.db.rows[-1]["details_json"])
    assert row["tick_preonset_floor"] == 80
    assert row["preonset_event"] == "Winter Storm Warning"
    assert row["tick_floor"] == 80


# §12 config extremes 18-22
@pytest.mark.parametrize("reserve_soc,partial,knob,expected", [
    (80, 50, 60, 80),     # 18: knob <= reserve_soc → reserve_soc
    (20, 50, 100, 100),   # 19: knob 100
    (20, 90, 80, 90),     # 20: partial > knob
    (20, 50, 0, 50),      # knob 0 → partial floor
])
def test_preonset_config_extremes(clock, reserve_soc, partial, knob, expected):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], reserve_soc=reserve_soc,
                     partial=partial, knob=knob, option=False)
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_floor == expected
    assert s._tick_reserve_floor == expected


def test_preonset_uncorroborated_watch_partial_gt_knob(clock):
    wsa = alert("Winter Storm Watch", onset=T(16, 9), ends=T(17, 3), id_="wsa")
    c, s, _ = bshell(clock, NOW, alerts=[wsa], partial=90, knob=80)
    tick(clock, c, s, NOW)
    # Stage E (expected diff, ref = TARGET): 6 h ahead -> value only.
    assert s._last_inclement_decision.preonset_target == 90


def test_preonset_solcast_unavailable_fails_toward_charging(clock):
    c, s, _ = bshell(clock, NOW, soc="70", alerts=[WSW], outlook=ol())

    def _boom(n, m):
        raise RuntimeError("solcast down")
    s._expected_solar_surplus_pct = _boom
    assert preonset_emitted(tick(clock, c, s, NOW))


# ===========================================================================
# D-B6 Number entity (mirrors D-A5)
# ===========================================================================
def _cm_entry(options):
    return SimpleNamespace(entry_id="cm1", title="CM",
                           data={"entry_type": "coordinator_manager"},
                           options=dict(options))


def _hass_with_energy():
    from unittest.mock import MagicMock
    energy = MagicMock()
    hass = SimpleNamespace(
        data={_DOMAIN: {"coordinator_manager": SimpleNamespace(
            coordinators={"energy": energy})}},
        config_entries=SimpleNamespace(),
    )

    def _update(entry, options=None, **kw):
        if options is not None:
            entry.options = dict(options)
    hass.config_entries.async_update_entry = MagicMock(side_effect=_update)
    return hass, energy


@pytest.mark.parametrize("opts,expected", [
    ({CONF_INCLEMENT_PREONSET_FLOOR: 65}, 65), ({}, 80),
    ({CONF_INCLEMENT_PREONSET_FLOOR: "junk"}, 80),
    ({CONF_INCLEMENT_PREONSET_FLOOR: 140}, 100),
])
def test_preonset_floor_number_seeds_from_options(opts, expected):
    from custom_components.universal_room_automation import number as nm
    hass, _ = _hass_with_energy()
    n = nm.InclementPreonsetFloorNumber(hass, _cm_entry(opts))
    assert n.native_value == expected
    assert (n.native_min_value, n.native_max_value, n.native_step) == (0, 100, 5)
    assert n.unique_id == f"{_DOMAIN}_energy_inclement_preonset_floor"
    assert n.name == "Inclement Pre-Onset Floor"


def test_preonset_floor_number_writes_options_only():
    from custom_components.universal_room_automation import number as nm
    hass, energy = _hass_with_energy()
    entry = _cm_entry({"other": 1})
    n = nm.InclementPreonsetFloorNumber(hass, entry)
    n.async_write_ha_state = lambda: None
    asyncio.new_event_loop().run_until_complete(n.async_set_native_value(70))
    assert entry.options == {"other": 1, CONF_INCLEMENT_PREONSET_FLOOR: 70}
    assert energy.method_calls == []


@pytest.fixture(scope="module")
def listener():
    import test_cm_reload_suppression as t
    return t, t._load_init_listener_helpers()


def _drive(listener, old, new):
    t, ns = listener
    hass = t._FakeHass(hvac=t._FakeHvac())
    entry = t._FakeEntry("cm1", {CONF_INCLEMENT_PREONSET_FLOOR: old})
    ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {CONF_INCLEMENT_PREONSET_FLOOR: new}
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry))
    return hass, hass.data[_DOMAIN]["cm_last_applied_options"]["cm1"]


def test_preonset_floor_key_in_options_reload_suppress_keys(listener):
    hass, _ = _drive(listener, 80, 70)
    assert hass.async_create_task.call_count == 0
    assert hass.config_entries.async_reload.call_count == 0


def test_preonset_floor_key_in_no_live_attr_keys(listener):
    _, snap = _drive(listener, 80, 70)
    assert snap[CONF_INCLEMENT_PREONSET_FLOOR] == 70


def test_preonset_floor_reads_live_slider(clock):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], option=False)
    del s._inclement_config_override
    entry = _cm_entry({CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS,
                       CONF_INCLEMENT_PREONSET_FLOOR: 70})
    c.hass.config_entries.async_entries = lambda domain=None: [entry]
    tick(clock, c, s, NOW)
    assert s._tick_reserve_floor == 70
    entry.options[CONF_INCLEMENT_PREONSET_FLOOR] = 90
    tick(clock, c, s, T(16, 3, 5))
    assert s._tick_reserve_floor == 90


@pytest.mark.parametrize("slider,expected", [(0, 50), (100, 100), (150, 100)])
def test_preonset_floor_slider_extremes_0_100(clock, slider, expected):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], knob=slider, option=False)
    tick(clock, c, s, NOW)
    assert s._tick_reserve_floor == expected


# ===========================================================================
# D-B7 Storm Guard trip-wire
# ===========================================================================
_SG = "switch.main_panel_wall_iq_gateway_hacs_storm_guard"


def _sg_shell(clock):
    c, s = make_shell(clock)
    saved = []

    async def _save(ev):
        saved.append(ev)
    c.db.save_anomaly_event = _save
    c._sg_saved = saved
    c._storm_guard_eid = _SG  # resolved target (resolver tested separately)
    return c, s


def _sg(c, state):
    if state is None:
        c.hass._states.pop(_SG, None)
    else:
        c.hass._states[_SG] = MockState(_SG, state, {})
    c._storm_guard_tick()
    drain()


def test_storm_guard_tripwire_fires_once_on_transition(clock):
    c, s = _sg_shell(clock)
    _sg(c, "off")
    _sg(c, "on")
    assert len(c.nm) == 1 and c.nm[0]["title"] == "Enphase Storm Guard is on"
    assert [e.type for e in c._sg_saved] == ["energy.storm_guard_enabled"]
    _sg(c, "on")
    assert len(c.nm) == 1
    _sg(c, "off")
    _sg(c, "on")
    assert len(c.nm) == 2 and len(c._sg_saved) == 2
    assert s._storm_guard_state == "on"


def test_storm_guard_tripwire_ignores_unavailable(clock):
    c, s = _sg_shell(clock)
    _sg(c, "unavailable")
    _sg(c, None)
    assert c.nm == [] and getattr(c, "_storm_guard_last", None) is None
    _sg(c, "off")
    _sg(c, "unavailable")
    _sg(c, "on")
    assert len(c.nm) == 1


def test_storm_guard_tripwire_on_at_boot_is_log_only(clock, caplog):
    import logging
    for _ in range(2):  # two simulated setups (fresh coordinators)
        c, s = _sg_shell(clock)
        with caplog.at_level(logging.WARNING):
            _sg(c, "on")
        assert c.nm == [] and c._sg_saved == []
    assert sum("Storm Guard is ON at startup" in r.message
               for r in caplog.records) == 2
    _sg(c, "off")
    _sg(c, "on")
    assert len(c.nm) == 1


def test_storm_guard_tripwire_disabled_empty_platform(clock, monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    monkeypatch.setattr(energy_const, "STORM_GUARD_PLATFORM", "")
    # Even a registry row that would match an empty platform is ignored:
    # "" is the kill switch, not a wildcard.
    from homeassistant.helpers import entity_registry as er
    ents = {_SG: SimpleNamespace(entity_id=_SG, platform="",
                                 unique_id="x_storm_guard")}
    monkeypatch.setattr(er, "async_get",
                        lambda hass: SimpleNamespace(entities=ents))
    c, s = make_shell(clock)
    assert c._storm_guard_entity() is None
    c.hass._states[_SG] = MockState(_SG, "off", {})
    c._storm_guard_tick()
    c.hass._states[_SG] = MockState(_SG, "on", {})
    c._storm_guard_tick()
    drain()
    assert c.nm == []


def test_storm_guard_entity_resolved_from_registry(clock, monkeypatch):
    """Registry lookup (no house entity_id literal): exactly one switch of
    platform enphase_ev whose unique_id ends `_storm_guard`."""
    from homeassistant.helpers import entity_registry as er
    ents = {
        _SG: SimpleNamespace(entity_id=_SG, platform="enphase_ev",
                             unique_id="enphase_ev_site_1_storm_guard"),
        "switch.other": SimpleNamespace(entity_id="switch.other",
                                        platform="enphase_ev",
                                        unique_id="enphase_ev_site_1_cfg"),
        "sensor.x_storm_guard": SimpleNamespace(
            entity_id="sensor.x_storm_guard", platform="enphase_ev",
            unique_id="y_storm_guard"),
    }
    monkeypatch.setattr(er, "async_get",
                        lambda hass: SimpleNamespace(entities=ents))
    c, s = make_shell(clock)
    assert c._storm_guard_entity() == _SG
    # Two matches → unresolved (inert).
    ents["switch.dup"] = SimpleNamespace(entity_id="switch.dup",
                                         platform="enphase_ev",
                                         unique_id="z_storm_guard")
    c2, _ = make_shell(clock)
    assert c2._storm_guard_entity() is None

def test_storm_guard_not_a_decision_input(clock):
    outs = []
    for state in ("off", "on"):
        c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
        c.hass._states[_SG] = MockState(_SG, state, {})
        c._storm_guard_eid = _SG
        c._storm_guard_tick()
        d = tick(clock, c, s, NOW)
        outs.append((d["reason"], d["actions"], s._tick_reserve_floor))
    assert outs[0] == outs[1]


# ===========================================================================
# Observability — ONE NM per grid-buy episode start
# ===========================================================================
def test_grid_buy_episode_notifies_once(clock):
    c, s, _ = bshell(clock, NOW, alerts=[], outlook=ol())
    tick(clock, c, s, NOW)
    c._grid_buy_notify_tick()          # first tick after setup: seeds
    assert c.nm == []
    feed(c, [WSW])
    tick(clock, c, s, T(16, 3, 5))
    c._grid_buy_notify_tick()
    drain()
    assert len(c.nm) == 1 and c.nm[0]["severity"] == "low"
    assert "Winter Storm Warning" in c.nm[0]["message"]
    assert "pre-onset" in c.nm[0]["message"]
    tick(clock, c, s, T(16, 3, 10))
    c._grid_buy_notify_tick()
    drain()
    assert len(c.nm) == 1
    # A floor-only tick never notifies.
    c2, s2, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol(), option=False)
    tick(clock, c2, s2, NOW)
    c2._grid_buy_notify_tick()
    tick(clock, c2, s2, T(16, 3, 5))
    c2._grid_buy_notify_tick()
    drain()
    assert c2.nm == []
    # Restart mid-episode (fresh coordinator, latch re-seeded): no re-fire.
    c3, s3, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    tick(clock, c3, s3, NOW)
    assert s3._tick_grid_buy is not None
    c3._grid_buy_notify_tick()
    tick(clock, c3, s3, T(16, 3, 5))
    c3._grid_buy_notify_tick()
    drain()
    assert c3.nm == []


def test_preonset_degraded_fresh_decision_control(clock):
    """Positive control for `degraded_stale`: same degraded telemetry (LKG
    SOC, Envoy blind) with a FRESH decision → bounded-degraded exemption
    allows the pre-charge; the standard degraded suffix follows the prefix."""
    now = NOW
    # Stage E: Onset 13:00 -> 05:00 (03:00 must be a scheduled slot).
    a = alert("Winter Storm Warning", onset=T(16, 5), ends=T(17, 3), id_="wsw")
    c, s, _ = bshell(clock, now, alerts=[a], outlook=ol())
    clock.t = now.astimezone(_UTC)
    _st(c.hass, _SOC, "40", unit="%", lu=clock.t - timedelta(hours=1))
    s._soc_lkg = 40.0
    s._soc_lkg_at = clock.t - timedelta(seconds=30)
    feed(c)
    ts = MockState(_TS, "x", {})
    ts.last_changed = clock.t
    c.hass._states[_TS] = ts
    d = s.determine_mode("off_peak", "shoulder", now=now)
    assert d["envoy_available"] is False
    assert preonset_emitted(d)
    assert "safety over cost, degraded telemetry: lkg" in d["reason"]
    # A-HIGH-1: the CFG turn_on is actually emitted (the D-MED-1 ON-heal
    # guard in `_result` must not swallow it), and only then latch + stamp.
    assert cfg_on(d) and d["charge_from_grid"] is True
    assert s._preonset_precharge_latch == {"wsw": "engaged"}
    assert s._tick_grid_buy["leg"] == "preonset"
    # The degraded source is restored after the emission.
    assert s._degraded_telemetry_source == "lkg"


def test_polygon_topup_requires_eligible_row(monkeypatch):
    """A polygon row flipped ineligible in the table never tops up."""
    mod = _inc()
    table = tuple(
        (r[0], r[1], r[2], r[3], False if r[0] == "SVW" else r[4])
        for r in mod.INCLEMENT_PRODUCT_TABLE
    )
    start = T(16, 15)
    svw = alert("Severe Thunderstorm Warning", code="SVW", onset=start,
                ends=start + timedelta(minutes=60), id_="svw")
    assert _poly_flag(svw, start + timedelta(minutes=5)) is True
    monkeypatch.setattr(mod, "INCLEMENT_PRODUCT_TABLE", table)
    assert _poly_flag(svw, start + timedelta(minutes=5)) is False


# ===========================================================================
# Review A / D fix-up (2026-10-17)
# ===========================================================================
def test_preonset_buy_reports_forecast_confirmed_fusion_direct():
    """D-MED-1 repro (fusion direct): reserve 20, partial 50, knob 80, option
    on, WSW `w1` Onset +6 h, bottom, SOC 40, confirmed={w1} → pre-onset buy
    AND buy_forecast_confirmed True."""
    now = T(16, 3)
    # Stage E (expected diff): Onset +6 h -> +1 h, a TOU engine and a buy-
    # schedule store are passed (no engine / no store -> no D-B6 buy).
    w1 = alert("Winter Storm Warning", onset=now + timedelta(hours=1),
               ends=now + timedelta(hours=12), id_="w1")
    cls = AlertClassifier().classify([w1], now=now)
    f = InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50,
                        grid_precharge_on_hold=True, preonset_floor=80)
    bat = SimpleNamespace(_expected_solar_surplus_pct=lambda n, m: 0.0,
                          _tou=TOURateEngine())
    d = f.decide(bat, cls, False, 0, "off_peak", now, 40, bottom_rate=True,
                 forecast_confirmed_ids=frozenset({"w1"}), preonset_latch={},
                 preonset_buy_schedule={})
    assert d.hold_depth == "allow_discharge" and d.preonset_target == 80
    assert d.preonset_floor == 80
    assert d.preonset_precharge is True and d.buy_forecast_confirmed is True
    # Control: unconfirmed → no buy and the attr reads False.
    d = f.decide(bat, cls, False, 0, "off_peak", now, 40, bottom_rate=True,
                 forecast_confirmed_ids=frozenset(), preonset_latch={},
                 preonset_buy_schedule={})
    assert d.preonset_precharge is False and d.buy_forecast_confirmed is False


def test_preonset_buy_attr_and_stamp_confirmed(clock):
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    d = tick(clock, c, s, NOW)
    assert preonset_emitted(d) and cfg_on(d)
    assert s._inclement_attrs()["inclement_buy_forecast"]["confirmed"] is True
    assert s._tick_grid_buy["forecast_confirmed"] is True


def _obs_episode(clock, observation):
    c, s, _ = bshell(clock, NOW, alerts=[], outlook=ol())
    tick(clock, c, s, NOW)
    c._grid_buy_notify_tick()                     # boot seed
    c._observation_mode = observation
    feed(c, [WSW])
    d = tick(clock, c, s, T(16, 3, 5))
    assert preonset_emitted(d) and cfg_on(d)
    c._grid_buy_notify_tick()
    drain()
    return c, s


def test_grid_buy_no_nm_and_latch_rolled_back_in_observation_mode(clock):
    """D-LOW-1 (#23): observation mode → no 'started grid-charging' NM and
    the pre-onset latch engaged this tick is rolled back."""
    c, s = _obs_episode(clock, True)
    assert c.nm == []
    assert s._preonset_precharge_latch == {}


def test_grid_buy_nm_and_latch_outside_observation_mode(clock):
    """Control for the observation-mode test."""
    c, s = _obs_episode(clock, False)
    assert len(c.nm) == 1
    assert s._preonset_precharge_latch == {"wsw": "engaged"}


def test_observation_rollback_keeps_prior_engaged_latch(clock):
    """Rollback only undoes an engage made THIS tick."""
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    tick(clock, c, s, NOW)
    c._grid_buy_notify_tick()
    assert s._preonset_precharge_latch == {"wsw": "engaged"}
    c._observation_mode = True
    tick(clock, c, s, T(16, 3, 5))
    c._grid_buy_notify_tick()
    assert s._preonset_precharge_latch == {"wsw": "engaged"}


def test_preonset_stripped_turn_on_no_latch_no_stamp(clock):
    """D-LOW-1: a `_result` whose CFG turn_on is withheld (switch reads off,
    no turn_on action) → latch NOT engaged, no grid-buy stamp."""
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    real = s._result

    def _strip(*a, **k):
        r = real(*a, **k)
        r["actions"] = [x for x in r["actions"] if x["service"] != "switch.turn_on"]
        return r
    s._result = _strip
    d = tick(clock, c, s, NOW)
    assert preonset_emitted(d) and not cfg_on(d)
    assert s._preonset_precharge_latch == {}
    assert s._tick_grid_buy is None


def test_fullhold_stripped_turn_on_no_stamp(clock):
    c, s, _ = bshell(clock, NOW, soc="50",
                     alerts=[_active("Winter Storm Warning", NOW, id_="w")],
                     outlook=ol())
    real = s._result

    def _strip(*a, **k):
        r = real(*a, **k)
        r["actions"] = [x for x in r["actions"] if x["service"] != "switch.turn_on"]
        return r
    s._result = _strip
    d = tick(clock, c, s, NOW)
    assert "— pre-charging" in d["reason"] and not cfg_on(d)
    assert s._tick_grid_buy is None
    # Control: unstripped → stamped.
    c, s, _ = bshell(clock, NOW, soc="50",
                     alerts=[_active("Winter Storm Warning", NOW, id_="w")],
                     outlook=ol())
    tick(clock, c, s, NOW)
    assert s._tick_grid_buy["leg"] == "zone"


def test_cfg_already_on_counts_as_commanded(clock):
    from _reserve_governor_harness import _st as _set
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    real = s._result
    eid = s._get_entity("charge_from_grid", "x", role="write")

    def _on(*a, **k):
        r = real(*a, **k)
        r["actions"] = [x for x in r["actions"] if x["service"] != "switch.turn_on"]
        _set(c.hass, eid, "on")
        return r
    s._result = _on
    tick(clock, c, s, NOW)
    assert s._preonset_precharge_latch == {"wsw": "engaged"}
    assert s._tick_grid_buy is not None


def _two_zone(order):
    # "a" Hard Freeze (air 30 °F: NOT confirmed) sorts before "b" WSW
    # (30 °F + PoP 80: confirmed). Both eligible zone warnings.
    hf = _active("Hard Freeze Warning", NOW, id_="a")
    ws = _active("Winter Storm Warning", NOW, id_="b")
    return [hf, ws] if order else [ws, hf]


@pytest.mark.parametrize("order", [True, False])
def test_zone_stamp_names_confirmed_record(clock, order):
    """A-LOW-1 / D-LOW-4: the zone stamp names the eligible AND confirmed
    record, independent of feed order."""
    c, s, _ = bshell(clock, NOW, soc="50", alerts=_two_zone(order),
                     outlook=ol(min_temp=30.0, pop=80.0))
    d = tick(clock, c, s, NOW)
    assert cfg_on(d)
    assert s._last_forecast_confirmed == frozenset({"b"})
    assert s._tick_grid_buy["alert_id"] == "b"
    assert s._tick_grid_buy["event"] == "Winter Storm Warning"


@pytest.mark.parametrize("order", [True, False])
def test_zone_stamp_key_order_independent(clock, order):
    a = _active("Winter Storm Warning", NOW, id_="w-a")
    b = _active("Ice Storm Warning", NOW, id_="w-b")
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[a, b] if order else [b, a],
                     outlook=ol())
    tick(clock, c, s, NOW)
    assert s._tick_grid_buy["alert_id"] == "w-a"


def test_polygon_stamp_names_in_window_record(clock):
    """Polygon leg: an expired-cap SVW ("p-a", sorts first) and an in-window
    one ("p-b") → the stamp names p-b."""
    now = T(16, 18)
    old = _active("Severe Thunderstorm Warning", now, code="SVW",
                  mins_ago=120, hours=1, id_="p-a")
    new = _active("Severe Thunderstorm Warning", now, code="SVW",
                  mins_ago=20, hours=1, id_="p-b")
    for alerts in ([old, new], [new, old]):
        c, s, _ = bshell(clock, now, soc="55", alerts=alerts)
        d = tick(clock, c, s, now)
        assert cfg_on(d) and s._last_inclement_decision.precharge_leg == "polygon"
        assert s._tick_grid_buy["alert_id"] == "p-b"


@pytest.mark.parametrize("event,air,app,expected", [
    ("Wind Chill Warning", 30.0, -5.0, True),
    ("Wind Chill Watch", 30.0, -5.0, True),
    ("Extreme Cold Warning", 30.0, -5.0, True),
    ("Extreme Cold Watch", 30.0, 29.0, False),
    ("Wind Chill Warning", 30.0, None, False),   # fallback: air 30 > 28
    ("Wind Chill Warning", 20.0, None, True),    # fallback: air 20 <= 28
    ("Wind Chill Warning", 20.0, 29.0, False),   # apparent wins when present
    ("Hard Freeze Warning", 30.0, -5.0, False),  # air-temp product
    ("Hard Freeze Watch", 28.0, 40.0, True),
])
def test_apparent_temperature_confirm(event, air, app, expected):
    o = Outlook(window_start=T(16, 0), window_end=T(17, 0), hours=12,
                min_temp_f=air, max_pop=None, max_precip_mm_no_pop=None,
                max_gust=None, conditions=frozenset(), min_apparent_f=app)
    assert inc.forecast_confirms(event, o) is expected


def test_inclement_alert_id_is_the_ledger_key():
    """A-LOW-2: one implementation, so memory and ledger keys cannot drift."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_outage_ledger as led,
    )
    mod = _inc()
    assert mod.alert_id is led.alert_key
    for a in ({"ID": "x", "URL": "u"}, {"URL": "u"},
              {"Event": "E", "Sent": "s"}, {}):
        assert mod.alert_id(a) == led.alert_key(a)
    assert mod.alert_id({"Event": "E", "Sent": "s"}) == "E|s"


def test_storm_guard_reresolves_when_cached_entity_vanishes(clock, monkeypatch):
    """A-LOW-4: cached target renamed → state missing → re-resolved."""
    from homeassistant.helpers import entity_registry as er
    new = "switch.renamed_storm_guard"
    ents = {_SG: SimpleNamespace(entity_id=_SG, platform="enphase_ev",
                                 unique_id="enphase_ev_site_1_storm_guard")}
    scans = []

    def _get(hass):
        scans.append(1)
        return SimpleNamespace(entities=ents)
    monkeypatch.setattr(er, "async_get", _get)
    c, s = make_shell(clock)
    c.hass._states[_SG] = MockState(_SG, "off", {})
    assert c._storm_guard_entity() == _SG
    assert c._storm_guard_entity() == _SG and len(scans) == 1  # cached, no scan
    # Rename: old state gone, registry carries the new id.
    del c.hass._states[_SG]
    ents.clear()
    ents[new] = SimpleNamespace(entity_id=new, platform="enphase_ev",
                                unique_id="enphase_ev_site_1_storm_guard")
    c.hass._states[new] = MockState(new, "off", {})
    assert c._storm_guard_entity() == new
    c._storm_guard_tick()
    c.hass._states[new] = MockState(new, "on", {})
    c._storm_guard_tick()
    drain()
    assert len(c.nm) == 1


def test_storm_guard_failed_reresolve_keeps_cached(clock, monkeypatch):
    from homeassistant.helpers import entity_registry as er
    monkeypatch.setattr(er, "async_get",
                        lambda hass: SimpleNamespace(entities={}))
    c, s = make_shell(clock)
    c._storm_guard_eid = _SG
    assert c._storm_guard_entity() == _SG     # state missing, no match → keep


def test_full_hold_degraded_precharge_reports_envoy_unavailable(clock):
    """Review B B-LOW-2: the pre-existing full-hold storm precharge degraded
    branch clears `_degraded_telemetry_source` around `_result`; the emitted
    decision must still say envoy_available=False (the Envoy-offline NM
    counter in `_track_envoy_availability` reads it)."""
    now = NOW
    a = alert("Winter Storm Warning", onset=now - timedelta(hours=1),
              ends=now + timedelta(hours=6), id_="wsw_on")
    c, s, _ = bshell(clock, now, alerts=[a], outlook=ol())
    clock.t = now.astimezone(_UTC)
    _st(c.hass, _SOC, "40", unit="%", lu=clock.t - timedelta(hours=1))
    s._soc_lkg = 40.0
    s._soc_lkg_at = clock.t - timedelta(seconds=30)
    feed(c)
    ts = MockState(_TS, "x", {})
    ts.last_changed = clock.t
    c.hass._states[_TS] = ts
    d = s.determine_mode("peak", "shoulder", now=now)
    assert "(storm precharge — safety over cost, degraded telemetry)" in d["reason"]
    assert d["charge_from_grid"] is True
    assert d["envoy_available"] is False
    assert s._degraded_telemetry_source == "lkg"
    # Review C fix-up (energy_battery.py:6322): the degraded full-hold site
    # stamps the grid buy (it commanded CFG on) — the stamp is the one the
    # buy NM + forecast-confirmed attribute read.
    assert cfg_on(d)
    assert s._tick_grid_buy is not None and s._tick_grid_buy["leg"] == "zone"
    assert s._tick_grid_buy["forecast_confirmed"] is True


# ===========================================================================
# Review C fix-up — discriminating tests for the surviving mutants
# (docs/reviews/code-review/ec_stage_bc_review_C.md). Oracles typed by hand.
# ===========================================================================
@pytest.mark.parametrize("event,outlook,expected", [
    # inclement.py:1337 — a freeze outlook with hours but NO temperature
    # (precip-only rows) must NOT confirm (fail-closed).
    ("Hard Freeze Warning", ol(min_temp=None, pop=90), False),
    ("Wind Chill Warning", ol(min_temp=None, pop=90), False),
    ("Hard Freeze Warning", ol(min_temp=10.0, pop=None), True),     # control
    # Operator 2026-10-17 — convective NEVER confirms on precipitation alone.
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=50, cond=()), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=None, mm=1.0, cond=()), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=None, mm=0.9, cond=()), False),
])
def test_review_c_forecast_confirms_fail_closed_and_convective_precip(
        event, outlook, expected):
    assert _inc().forecast_confirms(event, outlook) is expected


def _rec(a):
    r = _inc().build_record(a)
    assert r is not None
    return r


def test_review_c_polygon_topup_helper_window_edges(monkeypatch):
    """`polygon_topup_records` direct (the ONE predicate shared by the
    decision flag and the stamp): [start, min(end, start+cap)].
    classify() pre-filters expired / pre-onset rows, so these edges are
    defense-in-depth for the stamp caller (energy_battery `_grid_buy_stamp`
    re-evaluates at its own `dt_util.now()`)."""
    ptr = _inc().polygon_topup_records
    start = T(16, 15)
    short = _rec(alert("Severe Thunderstorm Warning", code="SVW", onset=start,
                       ends=start + timedelta(minutes=40), id_="s"))
    # :148 — the warning's own end binds before the 60-min cap.
    assert ptr([short], start + timedelta(minutes=40)) == [short]
    assert ptr([short], start + timedelta(minutes=41)) == []
    # :149 — never before the polygon onset.
    assert ptr([short], start - timedelta(minutes=1)) == []
    assert ptr([short], start) == [short]
    # :140 — cap 0 is the kill switch, even at the exact onset instant.
    monkeypatch.setattr(_inc(), "INCLEMENT_POLYGON_TOPUP_MAX_MIN", 0)
    assert ptr([short], start) == []


def test_review_c_precharge_flags_polygon_and_prepare_class():
    """inclement.py:162 — the non-polygon eligibility leg ignores polygon
    rows; :167 — prepare eligibility is read on the prepare CLASS rows
    only (an eligible watch cannot make a warn-class prepare eligible)."""
    now = NOW
    clf = _inc().AlertClassifier()
    svw = _active("Severe Thunderstorm Warning", now, code="SVW", mins_ago=10,
                  hours=1, id_="svw")
    c1 = clf.classify([svw], now=now)
    assert c1.tier != "none" and c1.polygon_topup_active is True
    assert c1.precharge_eligible is False
    c1b = clf.classify([_active("Winter Storm Warning", now, id_="w")], now=now)
    assert c1b.precharge_eligible is True                        # control
    hur = alert("Hurricane Warning", onset=T(16, 9), ends=T(17, 3), id_="hu")
    wsa = alert("Winter Storm Watch", onset=T(16, 10), ends=T(17, 3), id_="wa")
    c2 = clf.classify([hur, wsa], now=now)
    assert {r.alert_id for r in c2.prepare_alerts} == {"hu", "wa"}
    assert c2.prepare_precharge_eligible is False
    c3 = clf.classify([wsa], now=now)
    assert c3.prepare_precharge_eligible is True                 # control


@pytest.mark.parametrize("lead_h,onset_h,in_prepare", [
    (2.0, 5, False),    # default lead (12) would include it
    (20.0, 15, True),   # default lead (12) would exclude it
    (6.0, 5, True),
])
def test_review_c_classify_honours_preonset_lead_arg(lead_h, onset_h, in_prepare):
    """inclement.py:479 — the lead window is the ARGUMENT, not the module
    default (Bug Class #63: default == knob masks the split)."""
    a = alert("Winter Storm Warning", onset=NOW + timedelta(hours=onset_h),
              ends=NOW + timedelta(hours=onset_h + 6), id_="lead")
    got = _inc().AlertClassifier().classify([a], now=NOW, preonset_lead_h=lead_h)
    assert (len(got.prepare_alerts) == 1) is in_prepare


def test_review_c_active_full_hold_shadows_prepare_fields(clock):
    """inclement.py:981 — an active full_hold with a prepare row in the
    lead window: the active hold governs, prepare fields stay default."""
    fut = alert("Winter Storm Warning", onset=T(16, 15), ends=T(17, 3), id_="fut")
    c, s, _ = bshell(clock, NOW, soc="50",
                     alerts=[_active("Winter Storm Warning", NOW, id_="w"), fut],
                     outlook=ol())
    tick(clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "full_hold"
    assert dec.preonset_floor is None and dec.preonset_alert_id is None
    assert dec.preonset_precharge is False
    # Control: the same prepare row without the active hold registers.
    c, s, _ = bshell(clock, NOW, soc="50", alerts=[fut], outlook=ol())
    tick(clock, c, s, NOW)
    assert s._last_inclement_decision.preonset_alert_id == "fut"


def test_review_c_prepare_key_row_from_prepare_class(clock):
    """inclement.py:956 (LOW) — key row / latch id come from the prepare
    class rows: an earlier watch never names a warn-class prepare."""
    wsa = alert("Winter Storm Watch", onset=T(16, 10), ends=T(17, 3), id_="wa")
    wsw = alert("Winter Storm Warning", onset=T(16, 15), ends=T(17, 3), id_="ww")
    c, s, _ = bshell(clock, NOW, alerts=[wsa, wsw], outlook=ol())
    tick(clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.preonset_class == "warn"
    assert dec.preonset_alert_id == "ww"
    assert dec.preonset_event == "Winter Storm Warning"


def test_review_c_match_product_code_precedence_and_code_only():
    """inclement.py:298/308 (LOW) — the code row wins a code/name
    disagreement; a code-only match resolves by code."""
    mp = _inc().match_product
    # Stage E E1.3 (expected diff): match_product returns a third element,
    # `corroborable` (positions 0-4 of the row are unchanged).
    row, drift, corr = mp({"Event": "Winter Storm Warning", "NWSCode": "SVW"})
    assert row[1] == "Severe Thunderstorm Warning" and drift[2] == "mismatch"
    assert corr is True
    row, _, _ = mp({"Event": "Svr Tstm Wrn (renamed)", "NWSCode": "SVW"})
    assert row is not None and row[1] == "Severe Thunderstorm Warning"


def test_review_c_withheld_cfg_with_switch_already_on_not_commanded(clock):
    """energy_battery.py:2879 — `_result` withheld charge_from_grid (a
    chokepoint) while the CFG switch already reads on: NOT a commanded buy
    → no latch engage, no stamp."""
    from _reserve_governor_harness import _st as _set
    c, s, _ = bshell(clock, NOW, alerts=[WSW], outlook=ol())
    real = s._result
    eid = s._get_entity("charge_from_grid", "x", role="write")

    def _withhold(*a, **k):
        r = real(*a, **k)
        r["actions"] = [x for x in r["actions"] if x["service"] != "switch.turn_on"]
        r["charge_from_grid"] = False
        _set(c.hass, eid, "on")
        return r
    s._result = _withhold
    d = tick(clock, c, s, NOW)
    assert preonset_emitted(d)
    assert s._preonset_precharge_latch == {}
    assert s._tick_grid_buy is None
    assert s._cfg_buy_commanded(
        {"charge_from_grid": False,
         "actions": [{"service": "switch.turn_on"}]}) is False


def test_review_c_storm_guard_platform_filter(clock, monkeypatch):
    """energy.py Storm Guard registry resolve (LOW): a suffix-matching
    switch on ANOTHER platform is not a candidate."""
    from homeassistant.helpers import entity_registry as er
    ents = {
        _SG: SimpleNamespace(entity_id=_SG, platform="enphase_ev",
                             unique_id="enphase_ev_site_1_storm_guard"),
        "switch.foreign": SimpleNamespace(entity_id="switch.foreign",
                                          platform="other_integration",
                                          unique_id="x_storm_guard"),
    }
    monkeypatch.setattr(er, "async_get",
                        lambda hass: SimpleNamespace(entities=ents))
    c, _ = make_shell(clock)
    assert c._storm_guard_entity() == _SG


# ===========================================================================
# Operator 2026-10-17: "I don't want grid buys on mere rain." Convective
# confirms iff a STORM condition (excl. pouring / snowy-rainy) AND strong
# rain (pop >= 70, else no-pop amount >= 1.0 mm). Literals typed by hand.
# ===========================================================================
@pytest.mark.parametrize("event,outlook,expected", [
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=90, cond=("rainy",)), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=90, cond=("pouring",)), False),
    ("Tornado Warning", ol(min_temp=70, pop=90, cond=("snowy-rainy",)), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=60, cond=("lightning-rainy",)), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=69, cond=("lightning-rainy",)), False),
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=70, cond=("lightning-rainy",)), True),
    ("Tornado Watch", ol(min_temp=70, pop=None, mm=2.0, cond=("hail",)), True),
    ("Tornado Watch", ol(min_temp=70, pop=None, mm=0.9, cond=("hail",)), False),
    ("Tornado Watch", ol(min_temp=70, pop=None, mm=None, cond=("tornado",)), False),
    ("Severe Thunderstorm Warning", ol(min_temp=70, pop=95, cond=("pouring", "lightning")), True),
    # Non-convective families unchanged (pinned).
    ("Winter Storm Warning", ol(min_temp=30, pop=50, cond=()), True),
    ("Winter Storm Warning", ol(min_temp=30, pop=49, cond=("lightning",)), False),
    ("Hard Freeze Warning", ol(min_temp=28, pop=None, cond=()), True),
    ("Hard Freeze Warning", ol(min_temp=29, pop=99, cond=("lightning",)), False),
])
def test_convective_requires_storm_condition_and_strong_rain(event, outlook, expected):
    assert inc.forecast_confirms(event, outlook) is expected
