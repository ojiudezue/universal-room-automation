"""Crossing ledger pure core (PLANNING_crossing_vision.md P2-D2).

The module has no HA import; it is loaded straight from its file (no
package import, no sys.modules side effect beyond its own private name).
Times are plain epoch seconds. Oracles are hand-derived literals.

Defaults used by ``_L()`` are knob values written out as literals (reset
3600, eval 60, lead 900, lag 60, delay 90 + 120 = 210, arrival window 300 /
60, stuck 7200, anchor-zero 172800), never the imported constants. The
reset window is pinned at 3600 here (the shipped default is 1800) so the
window arithmetic below stays hand-checkable; the window length is a knob,
not the rule under test.

Worked examples W1-W8 (plan P2-D2): start anchored with ``L = R`` (resident
A home, plus B for the two-resident cases); B = a base time well after the
anchor; term outcomes land about 210 s after E; census ticks every 30 s.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = (Path(__file__).resolve().parents[2] / "custom_components"
         / "universal_room_automation" / "crossing_ledger.py")
_NAME = "_ura_crossing_ledger_under_test"


def _load():
    spec = importlib.util.spec_from_file_location(_NAME, _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = mod  # dataclasses needs the module registered
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(_NAME, None)
    return mod


CL = _load()
T0 = 1_000_000.0


def _L(**kw):
    args = dict(empty_reset_s=3600, eval_s=60, reconcile_lead_s=900,
                reconcile_lag_s=60, reconcile_delay_s=210,
                arrival_before_s=300, arrival_after_s=60, stuck_s=7200,
                anchor_zero_s=172800, setup_ts=T0)
    args.update(kw)
    return CL.CrossingLedger(**args)


def _empty_minutes(led, start, minutes, *, R=2, bodies=0, dark=False,
                   edge_at=None, entry_at=None, held=()):
    """Census tick + anchor sample once a minute from ``start``; returns
    the events and the last time."""
    events = []
    t = start
    for i in range(minutes + 1):
        t = start + 60 * i
        if edge_at is not None and i == edge_at:
            led.note_rising_edge(t)
        if entry_at is not None and i == entry_at:
            led.apply_term(direction="entry", n=1, term_source="vision",
                           crossing_key="k@entry", e_ts=t, now=t)
        led.census_tick(t, R, bodies, dark)
        events += led.evaluate(t, held)
    return events, t


def _known(led, *, R=2, t=T0):
    """Bring the ledger to known with L = R via an instant anchor."""
    led.empty_reset_s = 0
    led.census_tick(t, R, 0, False)
    [ev] = led.evaluate(t, ())
    led.empty_reset_s = 3600
    assert ev.kind == "anchor" and led.state == "known" and led.L == R
    return t


def _anchor_now(led, t, R):
    """One instant anchor at ``t`` (window 0), window restored after."""
    keep = led.empty_reset_s
    led.empty_reset_s = 0
    led.census_tick(t, R, 0, False)
    evs = led.evaluate(t, ())
    led.empty_reset_s = keep
    assert [e.kind for e in evs] == ["anchor"]
    return evs[0]


def _anchors(events):
    return [e for e in events if e.kind == "anchor"]


# ------------------------------------------------------------------- boot
def test_boot_unknown_until_anchor():
    led = _L()
    assert led.state == "unknown"
    assert led.census_tick(T0, 2, 0, False) == (None, True)
    ev = led.apply_term(direction="entry", n=3, term_source="vision",
                        crossing_key="a@1", e_ts=T0, now=T0)
    assert ev.applied is False and ev.reason == "unknown"
    assert led.L is None
    events, t = _empty_minutes(led, T0, 60)
    # The unknown-state entry failed the T0 sample (review A-MED-2): the
    # window opens at T0 + 60.
    assert _anchors(events) == [] and led.state == "unknown"
    events, t = _empty_minutes(led, T0 + 3660, 0)
    assert len(_anchors(events)) == 1 and led.state == "known"
    assert led.census_tick(t, 2, 0, False) == (0, True)


def test_restart_new_instance_is_unknown():
    """A restart builds a new ledger: never restores known."""
    led = _L()
    _known(led)
    assert _L().state == "unknown" and _L().guest_vis() is None


# ----------------------------------------------------------------- anchor
def test_anchor_needs_zero_bodies_and_no_edge_for_window():
    led = _L()
    # One body seen at minute 30: the window restarts there.
    events = []
    for i in range(61):
        t = T0 + 60 * i
        led.census_tick(t, 2, 1 if i == 30 else 0, False)
        events += led.evaluate(t, ())
    assert _anchors(events) == []
    # 3600 s after the first passing sample after the body (minute 31).
    events, _ = _empty_minutes(led, T0 + 61 * 60, 29)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 91 * 60, 0)
    assert len(_anchors(events)) == 1


def test_anchor_sets_L_to_resident_term():
    led = _L()
    _known(led, R=1)
    led.apply_term(direction="entry", n=4, term_source="vision",
                   crossing_key="a@1", e_ts=T0 + 10, now=T0 + 10)
    assert led.L == 5
    events, t = _empty_minutes(led, T0 + 60, 61, R=3)
    [a] = _anchors(events)
    assert a.l_before == 5 and a.l_after == 3 and a.residue == 2
    assert led.L == 3 and led.residue_last == 2
    assert led.census_tick(t, 3, 0, False) == (0, True)


def test_entry_term_restarts_anchor_window():
    led = _L()
    _known(led)
    # Entry term applied at minute 30 of an otherwise empty hour.
    events, _ = _empty_minutes(led, T0 + 60, 60, entry_at=30)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 61 * 60, 30)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 92 * 60, 0)
    assert len(_anchors(events)) == 1


def test_exit_term_does_not_restart_window():
    led = _L()
    _known(led, R=0)
    led.apply_term(direction="entry", n=2, term_source="vision",
                   crossing_key="e@0", e_ts=T0 + 1, now=T0 + 1)
    led.evaluate(T0 + 1, ())  # the entry's own sample fails
    start = T0 + 60
    events = []
    for i in range(61):
        t = start + 60 * i
        if i == 20:
            led.apply_term(direction="exit", n=1, term_source="camera",
                           crossing_key="x@1", e_ts=t, now=t)
        led.census_tick(t, 0, 0, False)
        events += led.evaluate(t, ())
    assert len(_anchors(events)) == 1
    assert _anchors(events)[0].at == start + 3600


def test_dark_fleet_stops_window():
    led = _L()
    events = []
    for i in range(61):
        t = T0 + 60 * i
        led.census_tick(t, 2, 0, i == 40)
        events += led.evaluate(t, ())
    assert _anchors(events) == []
    assert led.census_tick(T0 + 3700, 2, 0, True)[1] is False  # unhealthy


def test_none_bodies_is_failing_sample():
    led = _L()
    events = []
    for i in range(61):
        t = T0 + 60 * i
        led.census_tick(t, 2, None if i == 10 else 0, False)
        events += led.evaluate(t, ())
    assert _anchors(events) == []
    assert led.census_tick(T0, 2, None, False) == (None, False)


def test_stale_body_value_fails_sample():
    """A stored body value older than 2 x eval fails (no census tick)."""
    led = _L(empty_reset_s=0)
    led.census_tick(T0, 2, 0, False)
    assert led.evaluate(T0 + 121, ()) == []
    led.census_tick(T0 + 200, 2, 0, False)
    assert len(led.evaluate(T0 + 320, ())) == 1  # 120 s old: still fresh


def test_rising_edge_restarts_anchor_window():
    led = _L()
    events, _ = _empty_minutes(led, T0, 60, edge_at=30)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 61 * 60, 29)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 91 * 60, 0)
    assert len(_anchors(events)) == 1


def test_stuck_on_sensor_blocks_anchor():
    """A sensor stuck ON is a held level: the anchor never fires while it
    reads on (accepted; the anchor-zero page names it). Replaces the old
    edges-only rule."""
    led = _L()
    events, _ = _empty_minutes(led, T0, 120,
                               held=("binary_sensor.stuck_presence",))
    assert _anchors(events) == [] and led.state == "unknown"
    # Released: the window restarts at the first sample without it.
    events, _ = _empty_minutes(led, T0 + 121 * 60, 60)
    assert len(_anchors(events)) == 1


def test_anchor_independent_of_house_state():
    """The anchor predicate takes no house state at all: identical inputs
    give identical anchors whatever the (unpassed) house state is. The
    wiring-level twin drives the real producer with the house AWAY vs HOME
    (test_crossing_ledger_wiring)."""
    a, b = _L(), _L()
    ea, _ = _empty_minutes(a, T0, 60)
    eb, _ = _empty_minutes(b, T0, 60)
    assert [e.as_dict() for e in ea] == [e.as_dict() for e in eb]
    assert len(_anchors(ea)) == 1


def test_guest_surplus_discharges_with_resident_phone_home():
    """INV-P2-DISCHARGE: a resident's phone left at home keeps R = 1; the
    guest surplus (L = 4) still discharges once bodies read 0 for the
    window. The predicate never asks whether residents are away."""
    led = _L()
    _known(led, R=1)
    led.apply_term(direction="entry", n=3, term_source="vision",
                   crossing_key="g@1", e_ts=T0 + 5, now=T0 + 5)
    assert led.census_tick(T0 + 5, 1, 0, False) == (3, True)
    # The entry fails the T0+60 sample; the window opens at T0+120.
    events, t = _empty_minutes(led, T0 + 60, 61, R=1)
    assert len(_anchors(events)) == 1
    assert led.census_tick(t + 60, 1, 0, False) == (0, True)


def test_reset_window_zero_means_instant_anchor():
    led = _L(empty_reset_s=0)
    led.census_tick(T0, 2, 0, False)
    [a] = led.evaluate(T0, ())
    assert a.kind == "anchor" and led.state == "known"


def test_late_term_recorded_not_applied():
    led = _L()
    t = _known(led, R=2)
    ev = led.apply_term(direction="entry", n=2, term_source="vision",
                        crossing_key="late@1", e_ts=t - 30, now=t + 10)
    assert ev.applied is False and ev.reason == "late" and led.L == 2


def test_independent_flag_on_back_to_back_anchors():
    led = _L()
    events, t = _empty_minutes(led, T0, 120)
    a1, a2 = _anchors(events)
    assert a1.independent is True and a2.independent is False
    led.apply_term(direction="exit", n=1, term_source="camera",
                   crossing_key="x@1", e_ts=t + 1, now=t + 1)
    events, _ = _empty_minutes(led, t + 60, 60)
    assert _anchors(events)[0].independent is True


# ------------------------------------------------------------------ terms
def test_exit_clamps_at_zero_raw_kept():
    led = _L()
    _known(led, R=0)
    ev = led.apply_term(direction="exit", n=2, term_source="camera",
                        crossing_key="x@1", e_ts=T0 + 5, now=T0 + 5)
    assert ev.applied and led.L == 0 and led.L_raw == -2
    assert ev.l_after == 0 and ev.l_raw_after == -2


def test_floor_never_lowers():
    led = _L()
    _known(led, R=1)
    assert led.census_tick(T0 + 1, 3, 0, False) == (0, True)
    assert led.L == 3  # R rose 1 -> 3: lift 2
    led.apply_term(direction="entry", n=2, term_source="vision",
                   crossing_key="a@1", e_ts=T0 + 2000, now=T0 + 2000)
    assert led.census_tick(T0 + 2001, 1, 0, False) == (4, True)
    assert led.L == 5  # R fell: never lowered by the floor


def test_floor_only_on_rise():
    """R flat at 2 while L = 1 (an exit term before the departure edge):
    ten ticks never lift L."""
    led = _L()
    _known(led, R=2)
    led.apply_term(direction="exit", n=1, term_source="camera",
                   crossing_key="x@1", e_ts=T0 + 10, now=T0 + 10)
    for i in range(10):
        assert led.census_tick(T0 + 30 * (i + 1), 2, 0, False) == (0, True)
        assert led.L == 1


def test_ambiguous_no_term():
    led = _L()
    _known(led)
    assert led.apply_term(direction="ambiguous", n=1, term_source="camera",
                          crossing_key="a@1", e_ts=T0 + 1, now=T0 + 1) is None
    assert led.L == 2


def test_fallback_camera_then_one():
    assert CL.term_count("ok", 3, 1, "camera") == (3, "vision")
    assert CL.term_count("blank", None, 2, "camera") == (2, "camera")
    assert CL.term_count("error", None, None, "camera") == (1, "camera")
    assert CL.term_count("no_frigate_event", None, 0, "camera") == (1, "camera")
    assert CL.term_count("ok", None, 2, "camera") == (2, "camera")


def test_fallback_skip_policy():
    assert CL.term_count("ok", 2, 1, "skip") == (2, "vision")
    for outcome in ("blank", "error", "timeout", "no_frigate_event"):
        assert CL.term_count(outcome, None, 3, "skip") == (None, None)
    m = [{"crossing_key": "a", "direction": "entry", "camera_peak_count": 1}]
    assert CL.cluster_terms(m, "timeout", None, "skip") == []


def test_cluster_one_term_same_direction():
    members = [
        {"crossing_key": "p", "direction": "entry", "camera_peak_count": 1, "e_ts": 1.0},
        {"crossing_key": "m", "direction": "entry", "camera_peak_count": 1, "e_ts": 20.0},
    ]
    [t] = CL.cluster_terms(members, "ok", 2, "camera")
    assert (t["crossing_key"], t["n"], t["term_source"]) == ("p", 2, "vision")
    [t] = CL.cluster_terms(members, "error", None, "camera")
    assert (t["crossing_key"], t["n"], t["term_source"]) == ("p", 1, "camera")


def test_cluster_mixed_direction_per_member():
    members = [
        {"crossing_key": "p", "direction": "entry", "camera_peak_count": 2},
        {"crossing_key": "m", "direction": "exit", "camera_peak_count": None},
        {"crossing_key": "z", "direction": "ambiguous", "camera_peak_count": 1},
    ]
    terms = CL.cluster_terms(members, "ok", 5, "camera")
    assert [(t["crossing_key"], t["direction"], t["n"], t["term_source"])
            for t in terms] == [("p", "entry", 2, "camera"), ("m", "exit", 1, "camera")]


def test_residue_recorded_before_reset():
    led = _L()
    _known(led, R=2)
    led.apply_term(direction="entry", n=1, term_source="camera",
                   crossing_key="a@1", e_ts=T0 + 1, now=T0 + 1)
    led.apply_term(direction="exit", n=2, term_source="camera",
                   crossing_key="x@1", e_ts=T0 + 2, now=T0 + 2)
    assert led.L == 1
    # Residents now 0 (the floor never lowers L): residue = 1 - 0.
    events, _ = _empty_minutes(led, T0 + 60, 61, R=0)
    [a] = _anchors(events)
    assert (a.l_before, a.l_after, a.residue, led.residue_last) == (1, 0, 1, 1)


# -------------------------------------------------------------- reconcile
def test_reconcile_only_without_exit_term():
    led = _L()
    _known(led, R=2)
    t_e = T0 + 100
    due = led.note_departure("person.oji_udezue", t_e)
    assert due == t_e + 60 + 210
    led.apply_term(direction="exit", n=1, term_source="vision",
                   crossing_key="x@1", e_ts=t_e - 30, now=t_e + 5)
    ev = led.judge_reconcile("person.oji_udezue", due)
    assert ev.applied is False and ev.reason == "exit_term" and led.L == 1
    due2 = led.note_departure("person.ezinne", t_e + 2000)
    ev2 = led.judge_reconcile("person.ezinne", due2)
    assert ev2.applied is True and (ev2.l_before, ev2.l_after) == (1, 0)
    assert led.reconciled_today == 1


def test_reconcile_waits_for_late_exit_outcome():
    """The exit crossing E = t_e - 30 has its vision outcome at t_e + 100
    (after LAG, before LAG + timeout + end wait): judged at the returned due
    time, the exit term is already in and cancels the reconcile."""
    led = _L()
    _known(led, R=2)
    t_e = T0 + 1000
    due = led.note_departure("person.oji_udezue", t_e)
    timeline = sorted([
        (t_e + 100, "exit"),
        (due, "judge"),
    ])
    result = None
    for t, what in timeline:
        if what == "exit":
            led.apply_term(direction="exit", n=1, term_source="vision",
                           crossing_key="x@1", e_ts=t_e - 30, now=t)
        else:
            result = led.judge_reconcile("person.oji_udezue", t)
    assert result.applied is False and led.L == 1


def test_anchor_voids_pending_reconcile():
    led = _L()
    _known(led, R=2)
    t_e = T0 + 10
    due = led.note_departure("person.oji_udezue", t_e)
    events, _ = _empty_minutes(led, T0 + 20, 0, R=1)
    led.empty_reset_s = 0
    led.census_tick(T0 + 30, 1, 0, False)
    assert _anchors(led.evaluate(T0 + 30, ()))
    assert led.judge_reconcile("person.oji_udezue", due) is None
    assert led.L == 1


def test_reconcile_window_zero_disables():
    led = _L(reconcile_lead_s=0, reconcile_lag_s=0)
    _known(led, R=2)
    assert led.note_departure("person.oji_udezue", T0 + 5) is None
    assert led.judge_reconcile("person.oji_udezue", T0 + 999) is None
    assert led.L == 2


def test_reconcile_superseded_per_person():
    led = _L()
    _known(led, R=3)
    led.note_departure("person.oji_udezue", T0 + 10)
    due = led.note_departure("person.oji_udezue", T0 + 500)
    ev = led.judge_reconcile("person.oji_udezue", due)
    assert ev.e_ts == T0 + 500 and led.L == 2
    assert led.judge_reconcile("person.oji_udezue", due) is None


def test_reconcile_not_tracked_while_unknown():
    led = _L()
    assert led.note_departure("person.oji_udezue", T0) is None


def test_set_unknown_forgets():
    led = _L()
    _known(led, R=2)
    led.note_departure("person.oji_udezue", T0 + 1)
    led.set_unknown("switch_off")
    assert (led.state, led.L, led.guest_vis(), led.pending_people()) == (
        "unknown", None, None, [])


# -------------------------------------------------------------- trip-wires
def test_stuck_page_resident_independent():
    """guest_vis >= 1 held for the stuck window with zero bodies and no
    edge (an entry-term stream that blocks the anchor) pages once, whatever
    R is; re-arms when guest_vis reads 0."""
    for R in (0, 2):
        led = _L(empty_reset_s=10 ** 9)  # no anchor ever: the term stream
        _known(led, R=R)
        led.empty_reset_s = 10 ** 9
        led.apply_term(direction="entry", n=2, term_source="vision",
                       crossing_key="g@1", e_ts=T0 + 1, now=T0 + 1)
        fired = []
        for i in range(125):
            t = T0 + 60 + 60 * i
            if i % 20 == 0:
                led.apply_term(direction="entry", n=0, term_source="camera",
                               crossing_key=f"e@{i}", e_ts=t, now=t)
            led.census_tick(t, R, 0, False)
            led.evaluate(t, ())
            fired.append(led.stuck_due(t))
        assert fired.count(True) == 1, R
        assert fired.index(True) == 120  # 7200 s after the first sample
        # Re-arm: guest_vis back to 0, then stuck again -> pages again.
        led.apply_term(direction="exit", n=2, term_source="camera",
                       crossing_key="x@9", e_ts=T0 + 9000, now=T0 + 9000)
        led.census_tick(T0 + 9000, R, 0, False)
        led.evaluate(T0 + 9000, ())
        assert led._stuck_latched is False


def test_stuck_needs_zero_bodies():
    led = _L(empty_reset_s=10 ** 9)
    _known(led, R=0)
    led.empty_reset_s = 10 ** 9
    led.apply_term(direction="entry", n=1, term_source="vision",
                   crossing_key="g@1", e_ts=T0 + 1, now=T0 + 1)
    for i in range(200):
        t = T0 + 60 + 60 * i
        led.census_tick(t, 0, 1, False)  # a body is seen: not stuck
        led.evaluate(t, ())
        assert led.stuck_due(t) is False


def test_anchor_zero_pages_once_and_rearms():
    led = _L(anchor_zero_s=1000)
    led.census_tick(T0, 1, 1, False)  # enhanced census on: ticks arrive
    assert led.anchor_zero_due(T0 + 999) is False
    assert led.anchor_zero_due(T0 + 1000) is True
    assert led.anchor_zero_due(T0 + 5000) is False
    led.empty_reset_s = 0
    led.census_tick(T0 + 6000, 0, 0, False)
    assert _anchors(led.evaluate(T0 + 6000, ()))
    assert led.anchor_zero_due(T0 + 6999) is False
    assert led.anchor_zero_due(T0 + 7000) is True


@pytest.mark.parametrize("knob", ["stuck_s", "anchor_zero_s"])
def test_tripwire_zero_means_off(knob):
    led = _L(**{knob: 0})
    if knob == "anchor_zero_s":
        assert led.anchor_zero_due(T0 + 10 ** 7) is False
    else:
        _known(led, R=0)
        led._stuck_since = T0
        assert led.stuck_due(T0 + 10 ** 7) is False


def test_anchor_zero_silent_without_census_tick():
    """Enhanced census off: no census_tick ever arrived, so no page and no
    latch; the cause is named in the diagnostics (A-LOW-1 / D-L3)."""
    led = _L(anchor_zero_s=1000)
    assert led.anchor_zero_due(T0 + 10 ** 6) is False
    assert led.snapshot()["anchor_zero_suppressed"] == "no_census_tick"
    led.census_tick(T0 + 10 ** 6, 1, 1, False)
    assert led.snapshot()["anchor_zero_suppressed"] is None
    assert led.anchor_zero_due(T0 + 10 ** 6 + 1) is True


# ------------------------------------------------------- A-MED-1 / A-MED-2
def test_camera_peak_zero_is_one():
    assert CL.term_count("error", None, 0, "camera") == (1, "camera")
    assert CL.term_count("blank", None, None, "camera") == (1, "camera")
    m = [{"crossing_key": "a", "direction": "exit", "camera_peak_count": 0}]
    [t] = CL.cluster_terms(m, "error", None, "camera")
    assert (t["n"], t["term_source"]) == (1, "camera")


def test_entry_term_while_unknown_restarts_window():
    """Unknown, window 600, bodies 0, entry E = 290 (recorded `unknown`)
    -> no anchor at 600; the window restarts after the entry: first anchor
    at 960 (samples every 60 s: the 300 sample fails, 360 opens)."""
    led = _L(empty_reset_s=600)
    events = []
    for i in range(30):
        t = T0 + 60 * i
        if i == 5:
            ev = led.apply_term(direction="entry", n=1, term_source="camera",
                                crossing_key="g@290", e_ts=T0 + 290,
                                now=T0 + 290)
            assert ev.applied is False and ev.reason == "unknown"
        led.census_tick(t, 0, 0, False)
        events += led.evaluate(t, ())
    times = [a.at - T0 for a in _anchors(events)]
    assert times[0] == 960 and all(x >= 890 for x in times)


def test_late_entry_term_also_restarts_window():
    led = _L(empty_reset_s=600)
    t = _known(led, R=1)
    ev = led.apply_term(direction="entry", n=1, term_source="camera",
                        crossing_key="late@1", e_ts=t - 5, now=t + 30)
    assert ev.reason == "late"
    led.census_tick(t + 60, 1, 0, False)
    led.evaluate(t + 60, ())
    assert led._t_start is None  # the late entry failed the sample


def test_eval_zero_means_one_second():
    """EVAL_S 0 = a 1 s interval: a 1.5 s old body value is fresh (2 x 1),
    so the instant window anchors (it never could under 2 x 0)."""
    led = _L(eval_s=0, empty_reset_s=0)
    led.census_tick(T0, 2, 0, False)
    [a] = led.evaluate(T0 + 1.5, ())
    assert a.kind == "anchor" and led.state == "known"
    led2 = _L(eval_s=0, empty_reset_s=0)
    led2.census_tick(T0, 2, 0, False)
    assert led2.evaluate(T0 + 2.5, ()) == []  # 2.5 s old: stale


# ------------------------------------------------------- held inputs (D-M1)
def test_held_radar_blocks_anchor():
    """D-M1 repro: R = 2, a guest's entry makes L = 3, bodies 0 and no
    edges for 2 h, a radar holds the still guest -> no anchor, guest_vis 1."""
    led = _L()
    _known(led, R=2)
    led.apply_term(direction="entry", n=1, term_source="vision",
                   crossing_key="g@1", e_ts=T0 + 5, now=T0 + 5)
    events, t = _empty_minutes(led, T0 + 60, 120, R=2,
                               held=("binary_sensor.radar_gb1",))
    assert _anchors(events) == []
    assert led.census_tick(t, 2, 0, False) == (1, True)
    assert led.snapshot()["held"] == ["binary_sensor.radar_gb1"]


def test_no_hold_kill_switch_restores_edge_rule():
    led = _L(anchor_needs_no_hold=False)
    _known(led, R=2)
    led.apply_term(direction="entry", n=1, term_source="vision",
                   crossing_key="g@1", e_ts=T0 + 5, now=T0 + 5)
    events, t = _empty_minutes(led, T0 + 60, 61, R=2,
                               held=("binary_sensor.radar_gb1",))
    assert len(_anchors(events)) == 1
    assert led.census_tick(t, 2, 0, False) == (0, True)


def _held(readings, lkg):
    return CL.classify_held(readings, lkg)


def test_dead_input_last_on_blocks_anchor():
    """Input `on`, then `unavailable`: held (dead with last good on)."""
    lkg = {}
    assert _held({"binary_sensor.r": ("on", None)}, lkg) == ({"binary_sensor.r"}, set())
    held, dead = _held({"binary_sensor.r": ("unavailable", None)}, lkg)
    assert held == {"binary_sensor.r"} and dead == {"binary_sensor.r"}
    led = _L()
    events, _ = _empty_minutes(led, T0, 120, held=tuple(held))
    assert _anchors(events) == []


def test_dead_input_last_off_does_not_block():
    lkg = {}
    assert _held({"binary_sensor.r": ("off", False)}, lkg) == (set(), set())
    held, dead = _held({"binary_sensor.r": ("unavailable", None)}, lkg)
    assert held == set() and dead == set()
    led = _L()
    events, _ = _empty_minutes(led, T0, 60, held=tuple(held))
    assert len(_anchors(events)) == 1


def test_dead_input_no_known_good_blocks():
    for state in (None, "unavailable", "unknown"):
        held, dead = _held({"binary_sensor.r": (state, None)}, {})
        assert held == dead == {"binary_sensor.r"}, state


def test_stream_dead_input_frozen_reading_is_not_good():
    """A dead camera stream: its frozen `off` is not a good reading, so it
    neither releases the hold nor overwrites the last good `on`."""
    lkg = {"binary_sensor.panel_person": "on"}
    held, dead = _held({"binary_sensor.panel_person": ("off", True)}, lkg)
    assert held == dead == {"binary_sensor.panel_person"}
    assert lkg["binary_sensor.panel_person"] == "on"
    held, _ = _held({"binary_sensor.panel_person": ("off", True)}, {})
    assert held == {"binary_sensor.panel_person"}  # no good reading yet
    # Stream back (False) and reading off: released, last good off.
    held, _ = _held({"binary_sensor.panel_person": ("off", False)}, lkg)
    assert held == set() and lkg["binary_sensor.panel_person"] == "off"


def test_stuck_not_paged_while_held():
    """A still guest on a radar (held) never pages stuck, even with
    guest_vis >= 1 for the whole stuck window."""
    led = _L(empty_reset_s=10 ** 9)
    _known(led, R=0)
    led.empty_reset_s = 10 ** 9
    led.apply_term(direction="entry", n=1, term_source="vision",
                   crossing_key="g@1", e_ts=T0 + 1, now=T0 + 1)
    for i in range(200):
        t = T0 + 60 + 60 * i
        led.census_tick(t, 0, 0, False)
        led.evaluate(t, ("binary_sensor.radar",))
        assert led.stuck_due(t) is False


# ------------------------------------------- INV-P2-ONCE worked examples
B = T0 + 1000.0


def _tick(led, t, R):
    return led.census_tick(t, R, 0, False)


def _entry(led, e, n, now, key="e"):
    return led.apply_term(direction="entry", n=n, term_source="vision",
                          crossing_key=f"{key}@{e}", e_ts=e, now=now)


def _exit(led, e, n, now, key="x"):
    return led.apply_term(direction="exit", n=n, term_source="vision",
                          crossing_key=f"{key}@{e}", e_ts=e, now=now)


def test_resident_arrival_before_entry_term_counted_once():
    """W1 (A-HIGH-1 repro): B's edge first lifts L to 2 with a credit; B's
    own entry term (E = -20, outcome at +190) consumes it: guest_vis 0
    (the old per-tick floor gave 1)."""
    led = _L()
    _known(led, R=1)
    assert _tick(led, B, 2) == (0, True)
    assert led.L == 2
    ev = _entry(led, B - 20, 1, B + 190)
    assert (ev.credit_consumed, ev.l_after) == (1, 2)
    for t in (B + 210, B + 240):
        assert _tick(led, t, 2) == (0, True)
    assert led.L == 2


def test_entry_term_before_arrival_edge_no_lift():
    """W1b: the entry term lands first (L = 2), then R rises 1 -> 2 with
    L >= R: no lift, no credit."""
    led = _L()
    _known(led, R=1)
    _entry(led, B - 200, 1, B + 10)
    assert led.L == 2
    assert _tick(led, B + 30, 2) == (0, True)
    assert led.L == 2 and led.snapshot()["open_credits"] == []


def test_resident_with_guest_counts_guest():
    """W2: B arrives with a guest: lift 1, entry n = 2 consumes 1 adds 1."""
    led = _L()
    _known(led, R=1)
    _tick(led, B, 2)
    ev = _entry(led, B - 20, 2, B + 190)
    assert (ev.credit_consumed, led.L) == (1, 3)
    assert _tick(led, B + 210, 2) == (1, True)


def test_guest_alone_counts():
    """W3: a guest arrives alone: no credit, L = 2, R = 1."""
    led = _L()
    _known(led, R=1)
    ev = _entry(led, B - 20, 1, B + 190)
    assert (ev.credit_consumed, led.L) == (0, 2)
    assert _tick(led, B + 210, 1) == (1, True)


def test_exit_term_before_departure_edge_no_phantom():
    """W4 (A-HIGH-2 repro): L = R = 2; exit E = 200 -> L = 1; tick at 290
    with R = 2 flat -> no lift; departure t_e = 500 (R = 1); the judge
    consumes the exit: L = 1, guest_vis 0, reason exit_term."""
    led = _L()
    _known(led, R=2)
    _exit(led, B + 200, 1, B + 200)
    assert led.L == 1
    assert _tick(led, B + 290, 2) == (0, True)
    assert led.L == 1
    due = led.note_departure("person.b", B + 500)
    assert _tick(led, B + 500, 1) == (0, True)
    ev = led.judge_reconcile("person.b", due)
    assert (ev.applied, ev.reason, led.L) == (False, "exit_term", 1)
    assert _tick(led, due + 1, 1) == (0, True)


def test_resident_and_guest_depart_together():
    """W5: L = 3 (A, B, guest), R = 2; exit n = 2 -> L = 1; B's departure
    (R = 1) consumes one of the two."""
    led = _L()
    _known(led, R=2)
    _entry(led, B - 20, 1, B + 190, key="g")
    assert led.L == 3
    _exit(led, B + 1000, 2, B + 1210)
    assert led.L == 1
    due = led.note_departure("person.b", B + 1100)
    _tick(led, B + 1100, 1)
    ev = led.judge_reconcile("person.b", due)
    assert (ev.applied, led.L) == (False, 1)
    assert _tick(led, due + 1, 1) == (0, True)
    assert [list(x) for x in led._exits] == [[B + 1000, 1]]  # one left


def test_phone_home_walk_out_and_back_no_phantom():
    """W6: B's phone stays home (R = 2 throughout); B walks out (exit n = 1
    -> L = 1) and back (entry n = 1 -> L = 2): guest_vis 0 at every step
    (the old floor read 1 after the return)."""
    led = _L()
    _known(led, R=2)
    _exit(led, B, 1, B + 210)
    seen = []
    for i in range(20):
        seen.append(_tick(led, B + 210 + 30 * i, 2)[0])
    _entry(led, B + 900, 1, B + 1110)
    for i in range(20):
        seen.append(_tick(led, B + 1110 + 30 * i, 2)[0])
    assert seen == [0] * 40
    assert led.L == 2


@pytest.mark.parametrize("n,consumed", [(2, 2), (1, 1)])
def test_two_residents_one_term_two_edges(n, consumed):
    """W7: B and C arrive together, one edge each (ticks at 0 and 40):
    lifts to 2 and 3, credits 1 + 1. Entry n = 2 consumes both; a camera
    undercount n = 1 consumes one and the other credit expires (its lift
    stays): guest_vis 0 either way."""
    led = _L()
    _known(led, R=1)
    _tick(led, B, 2)
    _tick(led, B + 40, 3)
    assert led.L == 3
    ev = _entry(led, B - 20, n, B + 190)
    assert (ev.credit_consumed, led.L) == (consumed, 3)
    assert _tick(led, B + 400, 3) == (0, True)  # past expiry (40+60+210)
    assert led.snapshot()["open_credits"] == [] and led.L == 3


def test_uncounted_door_arrival_lift_persists():
    """W8: B arrives through an uncounted door: the lift (L = 2) outlives
    its credit; later B exits through a counted door, the departure judge
    consumes that exit: guest_vis 0 throughout."""
    led = _L()
    _known(led, R=1)
    assert _tick(led, B, 2) == (0, True)
    assert _tick(led, B + 400, 2) == (0, True)  # credit expired
    assert led.L == 2 and led.snapshot()["open_credits"] == []
    _exit(led, B + 5000, 1, B + 5210)
    assert led.L == 1
    due = led.note_departure("person.b", B + 5100)
    assert _tick(led, B + 5100, 1) == (0, True)
    ev = led.judge_reconcile("person.b", due)
    assert (ev.reason, led.L) == ("exit_term", 1)
    assert _tick(led, due + 1, 1) == (0, True)


def test_credit_expires_lift_stays():
    """A lift with no entry by t + 60 + delay: L keeps the lift, and a
    later guest entry adds 1 (the deficit never absorbs a guest)."""
    led = _L()
    _known(led, R=1)
    _tick(led, B, 2)
    _tick(led, B + 271, 2)  # 271 > 60 + 210: expired
    assert led.L == 2 and led.snapshot()["open_credits"] == []
    ev = _entry(led, B + 250, 1, B + 460)
    assert (ev.credit_consumed, led.L) == (0, 3)
    assert _tick(led, B + 470, 2) == (1, True)


def test_credit_open_until_expiry_boundary():
    """Expiry is t + AFTER + delay = +270: an outcome landing at +270
    still consumes; at +271 it does not."""
    for now, consumed in ((B + 270, 1), (B + 271, 0)):
        led = _L()
        _known(led, R=1)
        _tick(led, B, 2)
        ev = _entry(led, B + 60, 1, now)
        assert ev.credit_consumed == consumed, now


def test_credit_window_bounds():
    """Consumable for E in [t - 300, t + 60]."""
    for e, consumed in ((B - 300, 1), (B - 301, 0), (B + 60, 1), (B + 61, 0)):
        led = _L()
        _known(led, R=1)
        _tick(led, B, 2)
        ev = _entry(led, e, 1, B + 100)
        assert ev.credit_consumed == consumed, e - B


def test_anchor_clears_credits():
    led = _L()
    _known(led, R=1)
    _tick(led, B, 2)
    assert led.snapshot()["open_credits"] == [[B, 1]]
    _anchor_now(led, B + 10, 2)
    assert led.snapshot()["open_credits"] == [] and led.L == 2
    ev = _entry(led, B + 20, 1, B + 30)
    assert (ev.credit_consumed, led.L) == (0, 3)


def test_arrival_window_zero_credit_unconsumable():
    """BEFORE = AFTER = 0: only an entry with E == t consumes; otherwise
    the lift stays and the entry adds (the old double count returns only
    for exact-time terms)."""
    led = _L(arrival_before_s=0, arrival_after_s=0)
    _known(led, R=1)
    _tick(led, B, 2)
    ev = _entry(led, B - 20, 1, B + 100)
    assert (ev.credit_consumed, led.L) == (0, 3)
    led = _L(arrival_before_s=0, arrival_after_s=0)
    _known(led, R=1)
    _tick(led, B, 2)
    ev = _entry(led, B, 1, B + 100)
    assert (ev.credit_consumed, led.L) == (1, 2)


def test_lift_emits_one_event():
    led = _L()
    _known(led, R=1)
    assert led.drain_events() == []
    _tick(led, B, 3)
    [ev] = led.drain_events()
    assert (ev.kind, ev.n, ev.l_before, ev.l_after) == ("lift", 2, 1, 3)
    _tick(led, B + 30, 3)
    assert led.drain_events() == []


# ---------------------------------------------------------- exits consumed
def test_exit_consumed_once_by_reconciles():
    """A-MED-4: two residents depart, one exit term n = 1: the first
    reconcile is cancelled by it, the second applies (L 2 -> 1 -> 0)."""
    led = _L()
    _known(led, R=2)
    _exit(led, B + 100, 1, B + 310)
    assert led.L == 1
    due_a = led.note_departure("person.a", B + 200)
    due_b = led.note_departure("person.b", B + 250)
    ev_a = led.judge_reconcile("person.a", due_a)
    ev_b = led.judge_reconcile("person.b", due_b)
    assert (ev_a.applied, ev_a.reason) == (False, "exit_term")
    assert ev_b.applied is True and led.L == 0


def test_reconcile_consumes_earliest_exit():
    led = _L()
    _known(led, R=3)
    _exit(led, B + 300, 1, B + 510)
    _exit(led, B + 100, 1, B + 520)
    due = led.note_departure("person.a", B + 400)
    led.judge_reconcile("person.a", due)
    assert sorted(list(x) for x in led._exits) == [[B + 100, 0], [B + 300, 1]]


def test_late_exit_does_not_cancel_reconcile():
    """D-L1: resident A exits at E; an anchor runs at E + 30 (A's phone
    still home, R = 1); the exit outcome lands late; A's departure at
    E + 300 must reconcile (the ledger never paid that exit)."""
    led = _L()
    _known(led, R=1)
    e = B
    _anchor_now(led, e + 30, 1)
    ev = _exit(led, e, 1, e + 210)
    assert (ev.applied, ev.reason) == (False, "late")
    due = led.note_departure("person.a", e + 300)
    assert _tick(led, e + 300, 0) == (1, True)
    rec = led.judge_reconcile("person.a", due)
    assert rec.applied is True and led.L == 0
    assert _tick(led, due + 1, 0) == (0, True)


def test_anchor_clears_applied_exits_departure_reconciles():
    """Ruling Q1: L = R = 2; resident B exits at E (applied, L = 1); an
    anchor at E + 100 while B's phone still reads home (R = 2) resets L = 2;
    B's departure edge at E + 400 (exit inside its 900 s lead) must NOT be
    cancelled by the already-paid exit: it reconciles L 2 -> 1, guest 0."""
    led = _L()
    _known(led, R=2)
    e = B
    ev = _exit(led, e, 1, e + 10)
    assert (ev.applied, led.L) == (True, 1)
    _anchor_now(led, e + 100, 2)
    assert led.L == 2 and len(led._exits) == 0
    due = led.note_departure("person.b", e + 400)
    assert _tick(led, e + 400, 1) == (1, True)
    rec = led.judge_reconcile("person.b", due)
    assert (rec.applied, rec.reason, led.L) == (True, None, 1)
    assert _tick(led, due + 1, 1) == (0, True)


def test_unknown_exit_not_stored():
    led = _L()
    ev = _exit(led, B, 1, B + 10)
    assert ev.reason == "unknown" and len(led._exits) == 0


# ------------------------------------------------- config extremes (Tier 3)
@pytest.mark.parametrize("reset,no_hold,expect_anchor", [
    (0, True, False),     # instant window: a held input still blocks
    (0, False, True),     # kill switch off at the extreme: edge-only rule
    (10 ** 6, False, False),  # window never elapses
])
def test_reset_and_hold_knob_extremes(reset, no_hold, expect_anchor):
    led = _L(empty_reset_s=reset, anchor_needs_no_hold=no_hold)
    events, _ = _empty_minutes(led, T0, 120, R=1,
                               held=("binary_sensor.radar_gb1",))
    assert bool(_anchors(events)) is expect_anchor


def test_huge_arrival_window_consumes_once():
    """BEFORE / AFTER very large: one lift of 1 is still consumed at most
    once; a second entry adds a person."""
    led = _L(arrival_before_s=10 ** 6, arrival_after_s=10 ** 6)
    _known(led, R=1)
    _tick(led, B, 2)
    assert _entry(led, B - 500, 1, B + 100).credit_consumed == 1
    assert _entry(led, B + 5000, 1, B + 5100, key="g").credit_consumed == 0
    assert led.L == 3 and _tick(led, B + 5200, 2) == (1, True)


def test_eval_zero_and_reset_zero_with_reconcile_off():
    """EVAL 0, RESET 0, reconcile 0/0 together: anchors on a fresh sample,
    departures are not tracked, the surplus discharges at the next anchor."""
    led = _L(eval_s=0, empty_reset_s=0, reconcile_lead_s=0, reconcile_lag_s=0)
    led.census_tick(T0, 2, 0, False)
    assert _anchors(led.evaluate(T0 + 1, ()))
    _entry(led, T0 + 2, 2, T0 + 3, key="g")
    assert led.note_departure("person.a", T0 + 4) is None
    led.census_tick(T0 + 5, 2, 0, False)
    assert led.evaluate(T0 + 5, ()) == []  # the entry failed this sample
    led.census_tick(T0 + 6, 2, 0, False)
    assert _anchors(led.evaluate(T0 + 6, ())) and led.guest_vis() == 0


# ------------------------------------------------ review C fix-up (M4/M5)
def test_stuck_timer_restarts_on_body_sample():
    """CL40: guest_vis 2; 500 s of empty samples, one sample with a body,
    then 200 s empty: the stuck clock restarted at the body sample, so a
    600 s bound is NOT met (non-contiguous evidence never pages)."""
    led = _L(stuck_s=600)
    _known(led, R=0)
    led.L = led.L_raw = 2
    t = T0 + 60
    for i in range(10):  # T0+60 .. T0+600, empty
        tt = t + 60 * i
        led.census_tick(tt, 0, 0, False)
        led.evaluate(tt, ())
    led.census_tick(T0 + 660, 0, 1, False)  # a body
    led.evaluate(T0 + 660, ())
    for tt in (T0 + 720, T0 + 780, T0 + 840, T0 + 900):
        led.census_tick(tt, 0, 0, False)
        led.evaluate(tt, ())
    assert led.stuck_due(T0 + 900) is False
    for tt in (T0 + 960, T0 + 1020, T0 + 1080, T0 + 1140, T0 + 1200, T0 + 1320):
        led.census_tick(tt, 0, 0, False)
        led.evaluate(tt, ())
    assert led.stuck_due(T0 + 1320) is True  # 1320 - 720 = 600


def test_exit_after_lag_does_not_cancel_reconcile():
    """CL56: lag 60: an exit at t_e + 61 is outside [t_e - 900, t_e + 60]
    and must not cancel the departure; at t_e + 60 it does."""
    for offset, applied in ((61, True), (60, False)):
        led = _L()
        _known(led, R=1)
        t_e = B + 1000
        _exit(led, t_e + offset, 1, t_e + offset + 1)
        due = led.note_departure("person.a", t_e)
        rec = led.judge_reconcile("person.a", due)
        assert rec.applied is applied, offset


def test_reconcile_makes_next_anchor_independent():
    """CL59: an applied reconcile is new evidence: the next anchor is
    independent (back-to-back anchors with nothing between are not)."""
    led = _L()
    _known(led, R=1)
    assert _anchor_now(led, B, 1).independent is False
    due = led.note_departure("person.a", B + 100)
    assert led.judge_reconcile("person.a", due).applied is True
    assert _anchor_now(led, due + 10, 0).independent is True


def test_rebase_rearms_anchor_zero_page():
    """CL16: anchor-zero paged once; a rebase (re-enable) re-arms it, so a
    second drought of 100 s pages again."""
    led = _L(anchor_zero_s=100)
    led.census_tick(T0, 1, 1, False)
    assert led.anchor_zero_due(T0 + 150) is True
    assert led.anchor_zero_due(T0 + 160) is False  # latched
    led.rebase(T0 + 200)
    assert led.anchor_zero_due(T0 + 250) is False
    assert led.anchor_zero_due(T0 + 301) is True
