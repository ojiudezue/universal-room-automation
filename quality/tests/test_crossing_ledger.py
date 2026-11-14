"""Crossing ledger pure core (PLANNING_crossing_vision.md P2-D2).

The module has no HA import; it is loaded straight from its file (no
package import, no sys.modules side effect beyond its own private name).
Times are plain epoch seconds. Oracles are hand-derived literals.

Defaults used by ``_L()`` are the plan's knob values written out as literals
(reset 3600, eval 60, lead 900, lag 60, delay 90 + 120 = 210, stuck 7200,
anchor-zero 172800), never the imported constants.
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
                reconcile_lag_s=60, reconcile_delay_s=210, stuck_s=7200,
                anchor_zero_s=172800, setup_ts=T0)
    args.update(kw)
    return CL.CrossingLedger(**args)


def _empty_minutes(led, start, minutes, *, R=2, bodies=0, dark=False,
                   edge_at=None, entry_at=None):
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
        events += led.evaluate(t)
    return events, t


def _known(led, *, R=2, t=T0):
    """Bring the ledger to known with L = R via an instant anchor."""
    led.empty_reset_s = 0
    led.census_tick(t, R, 0, False)
    [ev] = led.evaluate(t)
    led.empty_reset_s = 3600
    assert ev.kind == "anchor" and led.state == "known" and led.L == R
    return t


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
    events, t = _empty_minutes(led, T0, 59)
    assert _anchors(events) == [] and led.state == "unknown"
    events, t = _empty_minutes(led, T0 + 3600, 0)
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
        events += led.evaluate(t)
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
    led.evaluate(T0 + 1)  # the entry's own sample fails
    start = T0 + 60
    events = []
    for i in range(61):
        t = start + 60 * i
        if i == 20:
            led.apply_term(direction="exit", n=1, term_source="camera",
                           crossing_key="x@1", e_ts=t, now=t)
        led.census_tick(t, 0, 0, False)
        events += led.evaluate(t)
    assert len(_anchors(events)) == 1
    assert _anchors(events)[0].at == start + 3600


def test_dark_fleet_stops_window():
    led = _L()
    events = []
    for i in range(61):
        t = T0 + 60 * i
        led.census_tick(t, 2, 0, i == 40)
        events += led.evaluate(t)
    assert _anchors(events) == []
    assert led.census_tick(T0 + 3700, 2, 0, True)[1] is False  # unhealthy


def test_none_bodies_is_failing_sample():
    led = _L()
    events = []
    for i in range(61):
        t = T0 + 60 * i
        led.census_tick(t, 2, None if i == 10 else 0, False)
        events += led.evaluate(t)
    assert _anchors(events) == []
    assert led.census_tick(T0, 2, None, False) == (None, False)


def test_stale_body_value_fails_sample():
    """A stored body value older than 2 x eval fails (no census tick)."""
    led = _L(empty_reset_s=0)
    led.census_tick(T0, 2, 0, False)
    assert led.evaluate(T0 + 121) == []
    led.census_tick(T0 + 200, 2, 0, False)
    assert len(led.evaluate(T0 + 320)) == 1  # 120 s old: still fresh


def test_rising_edge_restarts_anchor_window():
    led = _L()
    events, _ = _empty_minutes(led, T0, 60, edge_at=30)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 61 * 60, 29)
    assert _anchors(events) == []
    events, _ = _empty_minutes(led, T0 + 91 * 60, 0)
    assert len(_anchors(events)) == 1


def test_stuck_on_sensor_does_not_block_anchor():
    """A sensor stuck ON makes no edges: the anchor still fires."""
    led = _L()
    events, _ = _empty_minutes(led, T0, 60)
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
    [a] = led.evaluate(T0)
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


def test_floor_raises_only():
    led = _L()
    _known(led, R=1)
    assert led.census_tick(T0 + 1, 3, 0, False) == (0, True)
    assert led.L == 3  # raised to R
    led.apply_term(direction="entry", n=2, term_source="vision",
                   crossing_key="a@1", e_ts=T0 + 2, now=T0 + 2)
    assert led.census_tick(T0 + 3, 1, 0, False) == (4, True)
    assert led.L == 5  # never lowered by the floor


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
    assert CL.term_count("no_frigate_event", None, 0, "camera") == (0, "camera")
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
    assert _anchors(led.evaluate(T0 + 30))
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
            led.evaluate(t)
            fired.append(led.stuck_due(t))
        assert fired.count(True) == 1, R
        assert fired.index(True) == 120  # 7200 s after the first sample
        # Re-arm: guest_vis back to 0, then stuck again -> pages again.
        led.apply_term(direction="exit", n=2, term_source="camera",
                       crossing_key="x@9", e_ts=T0 + 9000, now=T0 + 9000)
        led.census_tick(T0 + 9000, R, 0, False)
        led.evaluate(T0 + 9000)
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
        led.evaluate(t)
        assert led.stuck_due(t) is False


def test_anchor_zero_pages_once_and_rearms():
    led = _L(anchor_zero_s=1000)
    assert led.anchor_zero_due(T0 + 999) is False
    assert led.anchor_zero_due(T0 + 1000) is True
    assert led.anchor_zero_due(T0 + 5000) is False
    led.empty_reset_s = 0
    led.census_tick(T0 + 6000, 0, 0, False)
    assert _anchors(led.evaluate(T0 + 6000))
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
