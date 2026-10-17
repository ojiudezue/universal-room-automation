"""EC storm Stage E E2 — buy in the cheapest hours closest to the event;
register the pre-onset floor no earlier than needed (PLANNING_ec_storm_stage_e
.md §E2, INV-8, INV-9; OQ-6 50 pp/h + 1 h margin, OQ-7 approved).

Battery tests drive the REAL `BatteryStrategy.determine_mode` with the real
`TOURateEngine` on America/Chicago wall time (`chi_clock`). The INV-9 oracle
is the hand-written `fixtures/ec_stage_e_buy_schedule_cases.json`.
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from _ec_stage_e_harness import (  # noqa: F401 — fixtures
    L,
    alert,
    bshell,
    cfg_on,
    chi_clock,
    clock,
    feed,
    inc_mod,
    outlook,
    preonset_emitted,
    tick,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

FIX = Path(__file__).parent / "fixtures" / "ec_stage_e_buy_schedule_cases.json"
REPO = Path(__file__).resolve().parents[2]
UTC = timezone.utc
WS_OK = dict(min_temp=20.0, pop=80.0)  # confirms the winter-storm family


def wsw(onset, id_="wsw", hours=12, event="Winter Storm Warning"):
    return alert(event, onset=onset, ends=onset + timedelta(hours=hours), id_=id_)


def utc_slots(*locals_):
    return tuple(t.astimezone(UTC) for t in locals_)


# ===========================================================================
# The pure scheduler (INV-9) against the hand table
# ===========================================================================
def test_buy_schedule_hand_table(chi_clock):
    inc = inc_mod()
    cases = json.loads(FIX.read_text())["cases"]
    assert len(cases) >= 12
    tou = TOURateEngine()
    for c in cases:
        now = datetime.fromisoformat(c["now"])
        onset = datetime.fromisoformat(c["onset"])
        h = inc.preonset_h_req(c["soc"], 80)
        got = inc.schedule_buy_hours(tou, now, onset, h, 12)
        exp = tuple(datetime.fromisoformat(x) for x in c["expected"])
        assert got == exp, (c["id"], got, exp)


def test_schedule_includes_current_slot_at_half_past(chi_clock):
    inc = inc_mod()
    now = L(2026, 10, 16, 3, 30)
    s = inc.schedule_buy_hours(TOURateEngine(), now, L(2026, 10, 16, 5), 2, 12)
    assert s == utc_slots(L(2026, 10, 16, 3), L(2026, 10, 16, 4))
    assert inc.preonset_slot(now) in s


def test_schedule_soc_at_target_empty_no_floor(chi_clock):
    inc = inc_mod()
    assert inc.preonset_h_req(80, 80) == 0
    assert inc.preonset_h_req(95, 80) == 0
    assert inc.preonset_h_req(None, 80) == 0
    assert inc.preonset_h_req(79, 80) == 2
    assert inc.schedule_buy_hours(TOURateEngine(), L(2026, 12, 16, 6),
                                  L(2026, 12, 16, 21), 0, 12) == ()
    # Battery: SOC >= target, 5 h ahead (outside the 4 h floor lead) ->
    # no schedule, no floor via (ii).
    now = L(2026, 12, 16, 16)
    c, s, _ = bshell(chi_clock, now, soc="85", alerts=[wsw(L(2026, 12, 16, 21))],
                     ol=outlook(**WS_OK))
    tick(chi_clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.preonset_target == 80 and dec.preonset_buy_hours == ()
    assert dec.preonset_floor is None and s._preonset_buy_schedule == {}


def test_schedule_unranked_hour_excluded():
    inc = inc_mod()

    class Tou:
        def get_season(self, d):
            return "s"

        def get_current_period(self, d):
            return "gap" if d.hour == 4 else "low"

        def period_rank(self, season, period):
            return None if period == "gap" else 0

    now = datetime(2026, 10, 16, 2, tzinfo=UTC)
    got = inc.schedule_buy_hours(Tou(), now, datetime(2026, 10, 16, 5, tzinfo=UTC), 2, 12)
    assert got == (datetime(2026, 10, 16, 2, tzinfo=UTC),
                   datetime(2026, 10, 16, 3, tzinfo=UTC))


def test_schedule_engine_missing_no_buy(chi_clock):
    inc = inc_mod()
    assert inc.schedule_buy_hours(None, L(2026, 10, 16, 3), L(2026, 10, 16, 5), 2, 12) == ()

    class Boom:
        def get_season(self, d):
            raise RuntimeError("tariff gone")
    assert inc.schedule_buy_hours(Boom(), L(2026, 10, 16, 3), L(2026, 10, 16, 5), 2, 12) == ()
    now = L(2026, 10, 16, 3)
    c, s, _ = bshell(chi_clock, now, soc="40", alerts=[wsw(L(2026, 10, 16, 5))],
                     ol=outlook(**WS_OK))
    s._tou = None
    d = tick_period(chi_clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.preonset_buy_hours == () and dec.preonset_precharge is False
    assert not preonset_emitted(d) and not cfg_on(d)
    assert dec.preonset_floor == 80  # floor rule (i) unaffected
    # Control: with the engine the same tick buys.
    c2, s2, _ = bshell(chi_clock, now, soc="40", alerts=[wsw(L(2026, 10, 16, 5))],
                       ol=outlook(**WS_OK))
    assert preonset_emitted(tick(chi_clock, c2, s2, now))


def tick_period(clock_, c, s, now):
    """`tick` for a strategy whose engine was removed."""
    s._tou = None
    tou = TOURateEngine()
    from _ec_stage_e_harness import TS, _SOC, _st
    from conftest import MockState
    clock_.t = now.astimezone(UTC)
    _st(c.hass, _SOC, str(c._test.soc), unit="%", lu=clock_.t)
    feed(c)
    ts = MockState(TS, now.isoformat(), {})
    ts.last_changed = ts.last_updated = clock_.t
    c.hass._states[TS] = ts
    s._last_inclement_decision_at = None
    return s.determine_mode(tou.get_current_period(now), tou.get_season(now), now=now)


def test_schedule_dst_fall_back_and_spring_forward(chi_clock):
    inc = inc_mod()
    tou = TOURateEngine()
    fb = inc.schedule_buy_hours(tou, L(2026, 11, 1, 0, 30),
                                datetime(2026, 11, 1, 10, tzinfo=UTC), 5, 12)
    # Five distinct UTC slots: 00:00 CDT, 01:00 CDT, 01:00 CST, 02:00 CST,
    # 03:00 CST -- no skip, no duplicate.
    assert fb == tuple(datetime(2026, 11, 1, h, tzinfo=UTC) for h in (5, 6, 7, 8, 9))
    sf = inc.schedule_buy_hours(tou, L(2026, 3, 8, 0, 30),
                                datetime(2026, 3, 8, 9, tzinfo=UTC), 5, 12)
    assert sf == tuple(datetime(2026, 3, 8, h, tzinfo=UTC) for h in (6, 7, 8))


def test_schedule_window_across_midnight(chi_clock):
    inc = inc_mod()
    got = inc.schedule_buy_hours(TOURateEngine(), L(2026, 12, 16, 18),
                                 L(2026, 12, 17, 0), 2, 12)
    assert got == utc_slots(L(2026, 12, 16, 22), L(2026, 12, 16, 23))


# ===========================================================================
# Battery: the INV-9 repro, closest-to-event, unavoidable top rate
# ===========================================================================
def test_preonset_floor_from_schedule_start(chi_clock):
    """INV-9 repro: winter WSW Onset 21:00, SOC 30 at 06:00, option on,
    forecast confirmed -> S = {15:00, 16:00}; no CFG 06:00-14:59; floor
    registered from 15:00; CFG on at 15:00."""
    t0 = L(2026, 12, 16, 6)
    c, s, _ = bshell(chi_clock, t0, soc="30", alerts=[wsw(L(2026, 12, 16, 21))],
                     ol=outlook(**WS_OK))
    d = tick(chi_clock, c, s, t0)
    # 06:00 is 15 h out: beyond the 12 h prepare window, nothing yet.
    assert s._last_inclement_decision.preonset_target is None and not cfg_on(d)
    d = tick(chi_clock, c, s, L(2026, 12, 16, 9))  # first prepare tick: freeze
    dec = s._last_inclement_decision
    assert dec.preonset_buy_hours == utc_slots(L(2026, 12, 16, 15), L(2026, 12, 16, 16))
    assert dec.preonset_floor is None and not cfg_on(d)
    assert dec.preonset_floor_from == L(2026, 12, 16, 15)
    for hh, mm in ((9, 0), (10, 0), (12, 0), (14, 0), (14, 59)):
        d = tick(chi_clock, c, s, L(2026, 12, 16, hh, mm))
        assert not cfg_on(d), (hh, mm)
        # The fusion itself refuses off-schedule (not only the emission).
        assert s._last_inclement_decision.preonset_precharge is False, (hh, mm)
        assert s._last_inclement_decision.preonset_floor is None, (hh, mm)
        assert s._tick_reserve_floor is None
    d = tick(chi_clock, c, s, L(2026, 12, 16, 15))
    assert preonset_emitted(d) and cfg_on(d)
    assert s._last_inclement_decision.preonset_floor == 80
    assert s._tick_reserve_floor == 80


def test_schedule_cheapest_closest_to_event(chi_clock):
    t0 = L(2026, 10, 16, 10)
    c, s, _ = bshell(chi_clock, t0, soc="70", alerts=[wsw(L(2026, 10, 16, 21))],
                     ol=outlook(**WS_OK))
    d = tick(chi_clock, c, s, t0)
    assert s._last_inclement_decision.preonset_buy_hours == utc_slots(
        L(2026, 10, 16, 15), L(2026, 10, 16, 16))
    assert not cfg_on(d)
    assert preonset_emitted(tick(chi_clock, c, s, L(2026, 10, 16, 15)))


def test_schedule_uses_higher_rate_only_if_unavoidable(chi_clock):
    now = L(2026, 12, 16, 17, 30)
    c, s, _ = bshell(chi_clock, now, soc="30", alerts=[wsw(L(2026, 12, 16, 19))],
                     ol=outlook(**WS_OK))
    d = tick(chi_clock, c, s, now)
    assert s._last_inclement_decision.preonset_buy_hours == utc_slots(
        L(2026, 12, 16, 17), L(2026, 12, 16, 18))
    assert preonset_emitted(d)
    # Control: Onset 23:00 -> the bottom-rate 21:00-22:00, not 17-21.
    c2, s2, _ = bshell(chi_clock, now, soc="30", alerts=[wsw(L(2026, 12, 16, 23))],
                       ol=outlook(**WS_OK))
    d2 = tick(chi_clock, c2, s2, now)
    assert s2._last_inclement_decision.preonset_buy_hours == utc_slots(
        L(2026, 12, 16, 21), L(2026, 12, 16, 22))
    assert not preonset_emitted(d2)


def test_schedule_frozen_while_soc_rises(chi_clock):
    """Drill (a) fixture: winter Onset 21:00, SOC 20 at 13:00 -> h_req 3,
    S = {14:00, 15:00, 16:00}; SOC 45 at 14:30 must NOT re-plan to
    {15:00, 16:00} (the buy keeps running until SOC >= 80)."""
    t0 = L(2026, 12, 16, 13)
    c, s, _ = bshell(chi_clock, t0, soc="20", alerts=[wsw(L(2026, 12, 16, 21))],
                     ol=outlook(**WS_OK))
    plan = [((13, 0), "20", False), ((13, 30), "20", False), ((14, 0), "20", True),
            ((14, 30), "45", True), ((15, 0), "60", True), ((15, 30), "75", True),
            ((16, 0), "85", False)]
    got = []
    for (hh, mm), soc, _exp in plan:
        d = tick(chi_clock, c, s, L(2026, 12, 16, hh, mm), soc=soc)
        got.append(preonset_emitted(d))
    assert got == [e for *_x, e in plan]
    assert s._preonset_buy_schedule["wsw"][0] == utc_slots(
        L(2026, 12, 16, 14), L(2026, 12, 16, 15), L(2026, 12, 16, 16))


# ===========================================================================
# INV-8: floor lead, eligibility loss, observation mode, Updates
# ===========================================================================
@pytest.mark.parametrize("lead,first", [(0, None), (4, 17), (12, 9), (13, 9)],
                         ids=["0", "4", "12", "13"])
def test_preonset_floor_lead_window(chi_clock, monkeypatch, lead, first):
    """Option off (no buy): floor from T - min(lead, 12). Effective lead 13
    clamps to 12; lead 0 -> no floor."""
    monkeypatch.setattr(inc_mod(), "INCLEMENT_PREONSET_FLOOR_LEAD_H", lead)
    t0 = L(2026, 12, 16, 9)
    c, s, _ = bshell(chi_clock, t0, soc="70", alerts=[wsw(L(2026, 12, 16, 21))],
                     option=False)
    seen = {}
    for hh, mm in ((9, 0), (16, 59), (17, 0), (20, 59)):
        tick(chi_clock, c, s, L(2026, 12, 16, hh, mm))
        seen[(hh, mm)] = s._last_inclement_decision.preonset_floor
    if first is None:
        assert set(seen.values()) == {None}
    elif first == 17:
        assert seen == {(9, 0): None, (16, 59): None, (17, 0): 80, (20, 59): 80}
    else:
        assert set(seen.values()) == {80}
        # Effective lead = min(lead, LEAD_H 12): the floor starts at 09:00
        # (v5.103.69 timing) for both 12 and 13.
        assert s._last_inclement_decision.preonset_floor_from == L(2026, 12, 16, 9)


@pytest.mark.parametrize("loss", ["unconfirm", "option_off"])
def test_preonset_floor_clears_on_eligibility_loss(chi_clock, loss):
    t15 = L(2026, 12, 16, 15)
    c, s, wm = bshell(chi_clock, t15, soc="30", alerts=[wsw(L(2026, 12, 16, 21))],
                      ol=outlook(**WS_OK))
    d = tick(chi_clock, c, s, t15)
    assert preonset_emitted(d) and s._preonset_precharge_latch == {"wsw": "engaged"}
    assert s._last_inclement_decision.preonset_floor == 80
    if loss == "unconfirm":
        s._forecast_confirm_latch.clear()
        wm.outlook = None
    else:
        s._inclement_config_override["inclement_grid_precharge_on_hold"] = False
    d = tick(chi_clock, c, s, L(2026, 12, 16, 16))
    dec = s._last_inclement_decision
    assert not preonset_emitted(d)
    assert s._preonset_precharge_latch == {}
    assert s._preonset_buy_schedule["wsw"][0] == ()  # D2-LOW-2: hours dropped, carry metadata kept
    assert dec.preonset_floor is None and s._tick_reserve_floor is None
    tick(chi_clock, c, s, L(2026, 12, 16, 17))  # falls back to rule (i)
    assert s._last_inclement_decision.preonset_floor == 80


def test_schedule_cleared_before_engage_on_option_off_and_unconfirm(chi_clock):
    t0 = L(2026, 12, 16, 13)
    c, s, wm = bshell(chi_clock, t0, soc="30", alerts=[wsw(L(2026, 12, 16, 21))],
                      ol=outlook(**WS_OK))
    tick(chi_clock, c, s, t0)
    assert set(s._preonset_buy_schedule) == {"wsw"}
    assert s._preonset_precharge_latch == {}  # never engaged
    s._inclement_config_override["inclement_grid_precharge_on_hold"] = False
    tick(chi_clock, c, s, L(2026, 12, 16, 13, 30))
    assert s._preonset_buy_schedule["wsw"][0] == ()  # D2-LOW-2: hours dropped, carry metadata kept
    # Re-enabled: a FRESH schedule from that tick (SOC now 75 -> h_req 2).
    s._inclement_config_override["inclement_grid_precharge_on_hold"] = True
    tick(chi_clock, c, s, L(2026, 12, 16, 14), soc="75")
    assert s._preonset_buy_schedule["wsw"][0] == utc_slots(
        L(2026, 12, 16, 15), L(2026, 12, 16, 16))
    # Unconfirm before engagement also deletes it.
    s._forecast_confirm_latch.clear()
    wm.outlook = None
    tick(chi_clock, c, s, L(2026, 12, 16, 14, 30))
    assert s._preonset_buy_schedule["wsw"][0] == ()  # D2-LOW-2: hours dropped, carry metadata kept


def test_schedule_cleared_every_observation_mode_tick(chi_clock):
    t0 = L(2026, 12, 16, 15)
    c, s, _ = bshell(chi_clock, t0, soc="30", alerts=[wsw(L(2026, 12, 16, 21))],
                     ol=outlook(**WS_OK))
    c._observation_mode = True
    tick(chi_clock, c, s, t0)
    assert set(s._preonset_buy_schedule) == {"wsw"}
    c._grid_buy_notify_tick()
    assert s._preonset_buy_schedule == {}
    assert s._preonset_precharge_latch == {}


def test_schedule_fresh_on_update_new_id(chi_clock):
    t0 = L(2026, 12, 16, 13)
    c, s, _ = bshell(chi_clock, t0, soc="30",
                     alerts=[wsw(L(2026, 12, 16, 21), id_="a")], ol=outlook(**WS_OK))
    tick(chi_clock, c, s, t0)
    assert s._preonset_buy_schedule["a"][0] == utc_slots(
        L(2026, 12, 16, 15), L(2026, 12, 16, 16))
    # The NWS Update: a new message ID with a moved Onset.
    feed(c, [wsw(L(2026, 12, 16, 23), id_="b")])
    tick(chi_clock, c, s, L(2026, 12, 16, 13, 30))
    assert set(s._preonset_buy_schedule) == {"b"}
    assert s._preonset_buy_schedule["b"][0] == utc_slots(
        L(2026, 12, 16, 21), L(2026, 12, 16, 22))


# ===========================================================================
# Multi-alert registered floor (§E2.4 worked answers)
# ===========================================================================
def _two(now, option):
    warn = wsw(now + timedelta(hours=10), id_="warn")
    watch = alert("Tornado Watch", onset=now + timedelta(hours=3),
                  ends=now + timedelta(hours=12), id_="watch")
    return [warn, watch], dict(option=option, ol=outlook(**WS_OK))


def test_two_alerts_registered_floor_no_buy_is_lower(chi_clock):
    now = L(2026, 10, 16, 3)
    al, kw = _two(now, option=False)
    c, s, _ = bshell(chi_clock, now, soc="40", alerts=al, **kw)
    tick(chi_clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.preonset_class == "warn" and dec.preonset_target == 80
    assert dec.preonset_floor == 50  # lower: only the unconfirmed watch is in 4 h


def test_two_alerts_registered_equals_target_under_buy(chi_clock):
    now = L(2026, 10, 16, 3)
    al, kw = _two(now, option=True)
    c, s, _ = bshell(chi_clock, now, soc="40", alerts=al, **kw)
    tick(chi_clock, c, s, now)
    # T = the earliest prepare start (the watch, 06:00) -> S = {04:00, 05:00}.
    assert s._last_inclement_decision.preonset_buy_hours == utc_slots(
        L(2026, 10, 16, 4), L(2026, 10, 16, 5))
    assert s._last_inclement_decision.preonset_floor == 50
    d = tick(chi_clock, c, s, L(2026, 10, 16, 4))
    assert preonset_emitted(d)
    assert s._last_inclement_decision.preonset_floor == 80


def test_preonset_two_alerts_floor_value_and_gate(chi_clock):
    """A CONFIRMED table watch inside the floor window raises the
    window-class value; the gate is T = earliest start."""
    now = L(2026, 10, 16, 3)
    warn = wsw(now + timedelta(hours=10), id_="warn")
    wsa = alert("Winter Storm Watch", onset=now + timedelta(hours=3),
                ends=now + timedelta(hours=12), id_="wsa")
    c, s, _ = bshell(chi_clock, now, soc="90", alerts=[warn, wsa], option=False,
                     ol=outlook(**WS_OK))
    tick(chi_clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.preonset_floor == 80 and dec.preonset_floor_from == L(2026, 10, 16, 2)
    # 1 h earlier the gate (T - 4 h = 02:00) is closed.
    c2, s2, _ = bshell(chi_clock, now, soc="90", alerts=[
        wsw(now + timedelta(hours=11), id_="warn"),
        alert("Winter Storm Watch", onset=now + timedelta(hours=4, minutes=1),
              ends=now + timedelta(hours=12), id_="wsa")],
        option=False, ol=outlook(**WS_OK))
    tick(chi_clock, c2, s2, now)
    assert s2._last_inclement_decision.preonset_floor is None


# ===========================================================================
# §4.3 — one assertion per reader row (target vs registered)
# ===========================================================================
def _crafted(s, now, **kw):
    """A real decision with chosen pre-onset fields (reader-row isolation)."""
    base = s._last_inclement_decision
    dec = replace(base, **kw)
    s._inclement_decision = lambda tou_period, now_, _d=dec: _d
    return dec


def test_preonset_field_split_readers(chi_clock):
    now = L(2026, 10, 16, 3)
    slot = inc_mod().preonset_slot(now)
    # Row 1: the buy requires the slot holding `now` in buy_hours.
    c, s, _ = bshell(chi_clock, now, soc="40", alerts=[wsw(L(2026, 10, 16, 5))],
                     ol=outlook(**WS_OK))
    tick(chi_clock, c, s, now)
    _crafted(s, now, preonset_precharge=True, preonset_buy_hours=())
    assert not preonset_emitted(tick(chi_clock, c, s, now))
    # Rows 2 + 3: reserve_level and the NM stamp target read the VALUE.
    c, s, _ = bshell(chi_clock, now, soc="40", alerts=[wsw(L(2026, 10, 16, 5))],
                     ol=outlook(**WS_OK))
    tick(chi_clock, c, s, now)
    _crafted(s, now, preonset_precharge=True, preonset_buy_hours=(slot,),
             preonset_target=85, preonset_floor=55)
    d = tick(chi_clock, c, s, now)
    assert preonset_emitted(d)
    assert s._last_reserve_level_desired == 85
    # Row 1 reads the VALUE, not the registered floor (not reachable from the
    # fusion today -- a buy slot implies (ii) -- but pins the reader).
    c1, s1, _ = bshell(chi_clock, now, soc="40", alerts=[wsw(L(2026, 10, 16, 5))],
                       ol=outlook(**WS_OK))
    tick(chi_clock, c1, s1, now)
    _crafted(s1, now, preonset_precharge=True, preonset_buy_hours=(slot,),
             preonset_target=80, preonset_floor=None)
    assert preonset_emitted(tick(chi_clock, c1, s1, now))
    assert s._tick_grid_buy["target"] == 85
    # Row 4: attr `floor` = value, `active` = registered.
    a = s._stage_b_attrs(s._inclement_decision("x", now))["inclement_preonset"]
    assert a["floor"] == 85 and a["active"] is True
    _crafted(s, now, preonset_target=85, preonset_floor=None)
    a = s._stage_b_attrs(s._inclement_decision("x", now))["inclement_preonset"]
    assert a["floor"] == 85 and a["active"] is False
    # Rows 5 + 6 + 7 (registered readers): active partial hold (50) + a
    # prepare WSW 6 h out -> value 80, registered None.
    wsa = alert("Winter Storm Watch", onset=now - timedelta(minutes=30),
                ends=now + timedelta(hours=8), id_="wsa")
    far = wsw(now + timedelta(hours=6), id_="far")
    c, s, _ = bshell(chi_clock, now, soc="70", alerts=[wsa, far], option=False)
    d = tick(chi_clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.hold_depth == "partial_hold" and dec.preonset_target == 80
    assert dec.preonset_floor is None
    assert s._tick_reserve_floor == 50                     # row 5
    assert "pre-onset floor" not in d["reason"]            # row 6
    from custom_components.universal_room_automation.domain_coordinators.hvac_strategy import (
        WriteStatus,
    )
    import asyncio
    c._last_reserve_row_key = None
    c._record_reserve_dispatch(status=WriteStatus.APPLIED, path="timer",
                               target="number.x", value=50, reason="r")
    loop = asyncio.get_event_loop()
    for _ in range(4):
        loop.run_until_complete(asyncio.sleep(0))
    row = json.loads(c.db.rows[-1]["details_json"])
    assert row["tick_floor"] == 50
    assert row["tick_preonset_floor"] is None              # row 7


def test_preonset_in_window_hold_unchanged_golden():
    spec = importlib.util.spec_from_file_location(
        "ec_stage_e_capture", REPO / "scripts" / "golden" / "ec_stage_e_capture.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    allowed, bad = g.compare()
    assert bad == []
    # Non-E0 in-window (active / polygon) cells: no diff at all.
    assert all(r[0] in g.ALLOWED_DIFF_PRODUCTS for r in allowed)
