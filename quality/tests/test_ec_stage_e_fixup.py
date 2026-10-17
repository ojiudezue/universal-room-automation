"""EC storm Stage E review fix-up (reviews A/B/C/D, 2026-10-17)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from _ec_stage_e_harness import (  # noqa: F401 — fixtures
    L,
    alert,
    bshell,
    cfg_on,
    chi_clock,
    clock,
    inc_mod,
    outlook,
    preonset_emitted,
    tick,
)
from test_ec_stage_e_selection import _flow, _form_defaults, _submit, fdecide, opts
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_BUY_ADDED,
    CONF_INCLEMENT_BUY_PRODUCTS,
    CONF_INCLEMENT_BUY_REMOVED,
    CONF_INCLEMENT_HOLD_ADDED,
    CONF_INCLEMENT_HOLD_PRODUCTS,
    CONF_INCLEMENT_HOLD_REMOVED,
    FORECAST_FETCH_TIMEOUT_S,
    NWS_WEATHER_EVENT_NAMES,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

UTC = timezone.utc
WS_OK = dict(min_temp=20.0, pop=80.0)


def _a(event, onset, id_, hours=12):
    return alert(event, onset=onset, ends=onset + timedelta(hours=hours), id_=id_)


def _slots(*ts):
    return tuple(t.astimezone(UTC) for t in ts)


def _run(clock_, alerts, ticks, *, soc="20", extra=None):
    c, s, _ = bshell(clock_, ticks[0], soc=soc, alerts=alerts,
                     ol=outlook(**WS_OK), extra_opts=extra)
    out = []
    for t in ticks:
        d = tick(clock_, c, s, t)
        dec = s._last_inclement_decision
        out.append((preonset_emitted(d), d["reason"], dec.preonset_buy_hours,
                    dec.preonset_start, dec.preonset_alert_id, dec.preonset_floor,
                    dec.preonset_target))
    return out, s


# ---------------------------------------------------------------------------
# D-HIGH-1 / D-MED-1
# ---------------------------------------------------------------------------
def test_unlisted_prepare_never_moves_table_event_time(chi_clock):
    ticks = [L(2026, 12, 16, h) for h in (9, 10, 12, 14, 15)]
    wsw = _a("Winter Storm Warning", L(2026, 12, 16, 21), "wsw")
    fw = _a("Flood Watch", L(2026, 12, 16, 11), "fw", hours=2)
    extra = opts(hold_added=["Flood Watch"])
    alone, _ = _run(chi_clock, [wsw], ticks, extra=extra)
    mixed, _ = _run(chi_clock, [wsw, fw], ticks, extra=extra)
    # Pre-onset fields (emission, schedule, T, key, floor, value) identical
    # at every tick; the reason too while the Flood Watch is still pending
    # (from 11:00 it is itself active: its own capped hold, legitimately).
    strip = lambda rows: [r[:1] + r[2:] for r in rows]  # noqa: E731
    assert strip(mixed) == strip(alone)
    assert [r[1] for r in mixed[:2]] == [r[1] for r in alone[:2]]
    assert alone[-1][2] == _slots(L(2026, 12, 16, 14), L(2026, 12, 16, 15),
                                  L(2026, 12, 16, 16))


def test_unlisted_prepare_never_names_the_buy(chi_clock):
    t = L(2026, 12, 16, 9)
    fw = _a("Flood Watch", L(2026, 12, 16, 11), "fw")
    fz = _a("Freeze Watch", L(2026, 12, 16, 21), "fz")
    out, s = _run(chi_clock, [fw, fz], [t], extra=opts(hold_added=["Flood Watch"]))
    dec = s._last_inclement_decision
    assert dec.preonset_alert_id == "fz" and dec.preonset_event == "Freeze Watch"
    assert dec.preonset_start == L(2026, 12, 16, 21)


def test_stale_event_time_replans_after_earlier_alert_onsets(chi_clock):
    fz = _a("Freeze Watch", L(2026, 12, 16, 11), "fz", hours=1)
    wsw = _a("Winter Storm Warning", L(2026, 12, 16, 21), "wsw")
    c, s, _ = bshell(chi_clock, L(2026, 12, 16, 9), soc="20", alerts=[fz, wsw],
                     ol=outlook(**WS_OK))
    tick(chi_clock, c, s, L(2026, 12, 16, 9))
    assert s._preonset_buy_schedule["wsw"][1] == L(2026, 12, 16, 11)
    tick(chi_clock, c, s, L(2026, 12, 16, 11, 30))   # Freeze Watch active
    assert "wsw" not in s._preonset_buy_schedule
    tick(chi_clock, c, s, L(2026, 12, 16, 12, 30))   # it ended: re-plan to 21:00
    assert s._preonset_buy_schedule["wsw"][0] == _slots(
        L(2026, 12, 16, 14), L(2026, 12, 16, 15), L(2026, 12, 16, 16))


# ---------------------------------------------------------------------------
# D-MED-2 -> operator ruling 2026-10-17: ONE contiguous run (no on/off/on)
# ---------------------------------------------------------------------------
def test_contiguous_run_starts_earlier_never_splits(chi_clock):
    wsw = _a("Winter Storm Warning", L(2026, 12, 16, 23), "wsw")
    c, s, _ = bshell(chi_clock, L(2026, 12, 16, 12), soc="20", alerts=[wsw],
                     ol=outlook(**WS_OK))
    tick(chi_clock, c, s, L(2026, 12, 16, 12))
    assert s._preonset_buy_schedule["wsw"][0] == _slots(
        L(2026, 12, 16, 14), L(2026, 12, 16, 15), L(2026, 12, 16, 16))
    seen = {}
    for h in (13, 14, 15, 16, 17, 18, 20, 21, 22):
        d = tick(chi_clock, c, s, L(2026, 12, 16, h))
        seen[h] = (preonset_emitted(d), s._tick_reserve_floor)
    assert seen == {13: (False, None), 14: (True, 80), 15: (True, 80),
                    16: (True, 80), 17: (False, 80), 18: (False, 80),
                    20: (False, 80), 21: (False, 80), 22: (False, 80)}


def test_schedule_never_gapped_and_latest_equal_cost_run():
    """Drills (a)/(b): a set with a gap is never returned; among equal-cost
    runs the latest wins."""
    inc = inc_mod()

    class Tou:  # rank 0 everywhere except 05:00-06:59 UTC (rank 1)
        def get_season(self, d):
            return "s"

        def get_current_period(self, d):
            return "hi" if d.hour in (5, 6) else "lo"

        def period_rank(self, season, period):
            return 1 if period == "hi" else 0

        def get_current_rate(self, d):
            return 2.0 if d.hour in (5, 6) else 1.0
    now = datetime(2026, 10, 16, 2, tzinfo=UTC)
    t = datetime(2026, 10, 16, 9, tzinfo=UTC)  # slots 02..08
    got = inc.schedule_buy_hours(Tou(), now, t, 3, 12)
    hrs = [h.hour for h in got]
    assert hrs == list(range(hrs[0], hrs[0] + len(hrs)))  # contiguous
    assert hrs == [2, 3, 4]       # the only all-cheap run of 3
    got = inc.schedule_buy_hours(Tou(), now, t, 2, 12)
    assert [h.hour for h in got] == [7, 8]  # latest of the equal-cost runs


# A-LOW-1 / B3 and B2 (fusion direct, shared schedule store)
# ---------------------------------------------------------------------------
def _fusion(option=True):
    return inc_mod().InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50,
                                     grid_precharge_on_hold=option, preonset_floor=80)


def _decide(f, tou, sched, now, alerts, latch=None):
    inc = inc_mod()
    cls = inc.AlertClassifier().classify(alerts, now=now)
    bat = SimpleNamespace(_expected_solar_surplus_pct=lambda n, m: 0.0, _tou=tou)
    ids = frozenset(r.alert_id for r in cls.prepare_alerts)
    return f.decide(bat, cls, False, 0, "off_peak", now, 40, bottom_rate=True,
                    forecast_confirmed_ids=ids, preonset_latch=latch or {},
                    preonset_buy_schedule=sched)


def test_empty_schedule_never_frozen(chi_clock):
    class Boom:
        def get_season(self, d):
            raise RuntimeError("transient")
    now = L(2026, 10, 16, 3)
    w = [_a("Winter Storm Warning", L(2026, 10, 16, 5), "w")]
    sched: dict = {}
    d = _decide(_fusion(), Boom(), sched, now, w)
    assert sched == {} and d.preonset_precharge is False
    d = _decide(_fusion(), TOURateEngine(), sched, now + timedelta(minutes=5), w)
    assert sched["w"][0] == _slots(L(2026, 10, 16, 3), L(2026, 10, 16, 4))
    assert d.preonset_precharge is True


def test_non_key_schedule_entries_purged(chi_clock):
    """B2: only the current key alert may own a schedule. A LIVE non-key
    alert's stale entry (left from when it was the key) is purged, so it can
    never be reused when it becomes the key again."""
    now = L(2026, 10, 16, 3)
    w = _a("Winter Storm Warning", L(2026, 10, 16, 5), "w")
    w2 = _a("Winter Storm Warning", L(2026, 10, 16, 9), "w2")
    stale = ((now.astimezone(UTC),), L(2026, 10, 16, 9), 80)
    sched = {"w2": stale}
    _decide(_fusion(), TOURateEngine(), sched, now, [w, w2])
    assert set(sched) == {"w"}
    sched["w2"] = stale
    _decide(_fusion(option=False), TOURateEngine(), sched, now, [w, w2])
    assert sched == {}


# ---------------------------------------------------------------------------
# Review C MEDIUMs
# ---------------------------------------------------------------------------
def test_widened_confirmed_prepare_registers_only_lower():
    """X6: rule (i) `hi` needs a corroborable record."""
    now = L(2026, 10, 16, 3)
    cwa = _a("Cold Weather Advisory", now + timedelta(hours=3), "cwa")
    s_ = inc_mod().build_selection(opts(hold_added=["Cold Weather Advisory"]))
    _, d = fdecide([cwa], s_, now=now, option=False,
                   ol=outlook(min_temp=30.0, apparent=10.0, pop=0.0))
    assert d.preonset_target == 50 and d.preonset_floor == 50


def test_schedule_horizon_cutoff_and_boundary(chi_clock):
    """H3/H3b: slot H is a candidate iff T - H <= 12 h (inclusive)."""
    inc = inc_mod()
    tou = TOURateEngine()
    now = L(2026, 10, 16, 3, 30)
    got = inc.schedule_buy_hours(tou, now, L(2026, 10, 16, 15, 10), 20, 12)
    assert L(2026, 10, 16, 3).astimezone(UTC) not in got     # 12 h 10 m before T
    assert L(2026, 10, 16, 4).astimezone(UTC) in got         # 11 h 10 m
    got = inc.schedule_buy_hours(tou, now, L(2026, 10, 16, 15, 0), 20, 12)
    assert L(2026, 10, 16, 3).astimezone(UTC) in got         # exactly 12 h
    got = inc.schedule_buy_hours(tou, now, L(2026, 10, 16, 15, 0, ) + timedelta(seconds=1), 20, 12)
    assert L(2026, 10, 16, 3).astimezone(UTC) not in got     # 12 h + 1 s


def test_buy_added_and_removed_deltas_stored():
    """D6/D7: the buy deltas are produced (consumption is pinned elsewhere)."""
    inc = inc_mod()
    hold, buy = inc.selection_form_defaults({})
    deltas, err = inc.selection_form_deltas(hold, buy + ["Tornado Watch"])
    assert err is None and deltas[CONF_INCLEMENT_BUY_ADDED] == ["Tornado Watch"]
    deltas, err = inc.selection_form_deltas(
        hold, [n for n in buy if n != "Winter Storm Warning"])
    assert err is None
    assert deltas[CONF_INCLEMENT_BUY_REMOVED] == ["Winter Storm Warning"]


def test_unticking_default_buy_stops_the_buy(chi_clock):
    w = _a("Winter Storm Warning", L(2026, 10, 16, 5), "w")
    c, s, _ = bshell(chi_clock, L(2026, 10, 16, 3), soc="40", alerts=[w],
                     ol=outlook(**WS_OK),
                     extra_opts={CONF_INCLEMENT_BUY_REMOVED: ["Winter Storm Warning"]})
    assert not cfg_on(tick(chi_clock, c, s, L(2026, 10, 16, 3)))


def test_build_selection_clamps_buy_to_family_or_polygon(monkeypatch):
    inc = inc_mod()
    table = tuple(inc.INCLEMENT_PRODUCT_TABLE) + (
        (None, "Flood Watch", "watch", False, True),)
    monkeypatch.setattr(inc, "INCLEMENT_PRODUCT_TABLE", table)
    s_ = inc.build_selection({})
    assert "flood watch" in s_.hold and "flood watch" not in s_.buy


# ---------------------------------------------------------------------------
# A-LOW-2 + Review C LOWs
# ---------------------------------------------------------------------------
def test_validation_error_reshows_submitted_lists():
    flow = _flow()
    sub = {CONF_INCLEMENT_HOLD_PRODUCTS: ["Winter Storm Watch", "Flood Watch"],
           CONF_INCLEMENT_BUY_PRODUCTS: ["Winter Storm Warning"]}
    r = _submit(flow, sub)
    assert r["type"] == "form"
    keys = {str(getattr(k, "schema", k)): k for k in r["data_schema"].schema}
    assert keys[CONF_INCLEMENT_HOLD_PRODUCTS].default() == ["Flood Watch",
                                                            "Winter Storm Watch"]
    assert keys[CONF_INCLEMENT_BUY_PRODUCTS].default() == ["Winter Storm Warning"]


def test_partial_submit_keeps_other_list():
    """G8: a submit carrying only the buy key never wipes the hold list."""
    stored = opts(hold_added=["Flood Watch"])
    hold, buy = inc_mod().selection_form_defaults(stored)
    r = _submit(_flow(stored), {CONF_INCLEMENT_BUY_PRODUCTS: buy})
    assert r["type"] == "create_entry"
    assert r["data"][CONF_INCLEMENT_HOLD_ADDED] == ["Flood Watch"]
    assert r["data"][CONF_INCLEMENT_HOLD_REMOVED] == []


def test_shipped_constants_pinned():
    assert 0 < FORECAST_FETCH_TIMEOUT_S <= 30            # K5
    assert len(NWS_WEATHER_EVENT_NAMES) == 49            # V10


# ---------------------------------------------------------------------------
# (8) Update carry-over; (9) degenerate hazard window
# ---------------------------------------------------------------------------
def _engaged_then_reached(clock_):
    from _ec_stage_e_harness import feed
    a = _a("Winter Storm Warning", L(2026, 10, 16, 5), "a")
    c, s, _ = bshell(clock_, L(2026, 10, 16, 3), soc="40", alerts=[a],
                     ol=outlook(**WS_OK))
    assert preonset_emitted(tick(clock_, c, s, L(2026, 10, 16, 3)))
    tick(clock_, c, s, L(2026, 10, 16, 3, 5), soc="85")
    assert s._preonset_precharge_latch == {"a": "reached"}
    return c, s, feed


def test_update_same_event_carries_latch_and_schedule(chi_clock):
    c, s, feed = _engaged_then_reached(chi_clock)
    frozen = s._preonset_buy_schedule["a"][0]
    feed(c, [_a("Winter Storm Warning", L(2026, 10, 16, 5), "b")])  # the Update
    d = tick(chi_clock, c, s, L(2026, 10, 16, 3, 10), soc="40")
    assert s._preonset_precharge_latch == {"b": "reached"}
    assert s._preonset_buy_schedule["b"][0] == frozen
    assert not preonset_emitted(d)                       # no re-buy


def test_update_different_event_starts_fresh(chi_clock):
    c, s, feed = _engaged_then_reached(chi_clock)
    feed(c, [_a("Ice Storm Warning", L(2026, 10, 16, 5), "b")])
    d = tick(chi_clock, c, s, L(2026, 10, 16, 3, 10), soc="40")
    assert "a" not in s._preonset_precharge_latch
    assert preonset_emitted(d)                           # fresh episode


def test_hazard_window_end_not_after_start_falls_back():
    inc = inc_mod()
    on = "2026-10-16T05:00:00-05:00"
    start, end = inc._hazard_window({"Onset": on, "Expires": on})
    assert end - start == timedelta(hours=48)
    start, end = inc._hazard_window(
        {"Onset": on, "Expires": "2026-10-16T04:00:00-05:00"})
    assert end - start == timedelta(hours=48)
    start, end = inc._hazard_window(
        {"Onset": on, "Ends": "2026-10-16T09:00:00-05:00"})
    assert end - start == timedelta(hours=4)             # control
