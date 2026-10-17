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


# Base pre-onset scenario: Oct 16 03:00 (bottom rate), WSW Onset 15:00.
NOW = T(16, 3)
WSW = alert("Winter Storm Warning", sent=T(16, 2), onset=T(16, 15),
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
        "Freeze Warning": False, "Wind Chill Advisory": False,
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
    ("Severe Thunderstorm Watch", ol(min_temp=70, pop=10, cond=("lightning",)), True),
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
    assert s._last_inclement_decision.preonset_floor == 80


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
    wsa = alert("Winter Storm Watch", onset=T(16, 9), ends=T(17, 9), id_="wsa")
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
    wsw = alert("Winter Storm Warning", onset=NOW + timedelta(hours=10),
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
        alerts = [alert("Severe Thunderstorm Watch", onset=T(16, 9),
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
        alerts = [alert("Winter Storm Watch", onset=T(16, 9), ends=T(17, 3),
                        id_="wsa")]
        outlook = None
    elif case == "arbitrage_charge":
        pre_tick = lambda s: setattr(s, "_arbitrage_phase", ARBITRAGE_PHASE_CHARGE)
    elif case == "attain_charging":
        pre_tick = lambda s: setattr(s, "_attain_state", "charging")
    elif case == "forecast_unconfirmed":
        outlook = None
    elif case == "degraded_stale":
        alerts = [alert("Winter Storm Warning", onset=T(16, 13), ends=T(17, 3),
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
             "forecast_unconfirmed"]


@pytest.mark.parametrize("case", _REFUSALS)
def test_preonset_precharge_gates(clock, case):
    d, s = _gate_case(clock, case)
    dec = s._last_inclement_decision
    assert dec.reason != "classify_error"
    assert not preonset_emitted(d)
    assert not any(a["service"] == "switch.turn_on" for a in d["actions"])
    # The floor is still registered in every case.
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
    assert s._last_inclement_decision.preonset_floor == 80


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
        "Inclement pre-onset (Winter Storm Warning, onset 15:00) — pre-charging"
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
    wsw2 = alert("Winter Storm Warning", onset=T(16, 14), ends=T(17, 3), id_="wsw2")
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
    wsw = alert("Winter Storm Warning", onset=T(16, 11), ends=T(17, 3), id_="wsw")
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
    cancel = alert("Winter Storm Warning", type_="Cancel", onset=T(16, 11),
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
    assert a["inclement_preonset"] == {
        "floor": 80, "start": "2026-10-16T15:00:00-05:00",
        "event": "Winter Storm Warning", "class": "warn",
        "precharge": True, "latch": "engaged",
    }
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
    assert s._last_inclement_decision.preonset_floor == 90


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
    a = alert("Winter Storm Warning", onset=T(16, 13), ends=T(17, 3), id_="wsw")
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
    assert preonset_emitted(d) and "(degraded telemetry:" in d["reason"]


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
