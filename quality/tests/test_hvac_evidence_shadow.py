"""HVAC evidence-rule shadow recording (HVAC-GUEST-EVIDENCE-RULE-1 phase 1).

Plan: docs/planning/PLANNING_hvac_evidence_shadow_recording_2026_11.md rev 2.

INV-SHADOW (plan §2): the producer's every pre-existing output is identical
to a golden captured on PRE-BUILD source, with the recorder const True AND
False. The only allowed differences are the new shadow dicts and rows in
`hvac_evidence_shadow`.
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _hvac_ev_shadow_replay as R  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_const as HC,
)


# ==========================================================================
# D0: INV-SHADOW golden (captured on pre-build source)
# ==========================================================================

def _diff_first(golden: list[dict], got: list[dict]) -> str:
    assert len(golden) == len(got), f"pass count {len(got)} != golden {len(golden)}"
    for i, (g, o) in enumerate(zip(golden, got)):
        if g != o:
            for k in g:
                if g[k] != o.get(k):
                    return f"pass {i + 1} ({g['_pass']}): key {k} differs"
            return f"pass {i + 1}: extra keys {set(o) - set(g)}"
    return ""


def test_inv_shadow_golden_const_on(monkeypatch):
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_ENABLED", True, raising=False)
    golden = R.load_golden()["passes"]
    got = R.run_replay()
    assert got == golden, _diff_first(golden, got)


def test_inv_shadow_golden_const_off(monkeypatch):
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_ENABLED", False, raising=False)
    golden = R.load_golden()["passes"]
    got = R.run_replay()
    assert got == golden, _diff_first(golden, got)


def test_golden_records_capture_commit_and_coverage():
    """The golden names its capture commit and covers what the plan lists:
    every house state, a zone-filtered pass, an absent room, a hallway
    re-type, a D5 pending room and a restart (pass 120)."""
    g = R.load_golden()
    assert len(g["capture_commit"]) == 40
    passes = g["passes"]
    states = {p["_pass"]["house_state"] for p in passes}
    assert states == {
        "home_day", "home_evening", "home_night", "sleep", "waking",
        "guest", "arriving", "away", None,
    }
    assert any(p["_pass"]["zone_ids"] for p in passes)
    assert any(p["_coordinator_absent_this_pass"] for p in passes)
    assert any(p["_hvac_arm_source"].get("clo") == "hallway_excluded" for p in passes)
    assert any(any(p["_hvac_pending"].values()) for p in passes)
    assert passes[119]["_pass"]["n"] == 120


# ==========================================================================
# Shared small-world harness (real ZoneManager, fake rooms)
# ==========================================================================

import asyncio  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sqlite3  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ROOM_TYPE,
    DOMAIN,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_zones as _hz,
)

S = timedelta  # noqa: N816
T0 = datetime(2026, 11, 5, 20, 0, 0, tzinfo=timezone.utc)


class _World:
    """zones: {zone_id: [(room, type)]}. Every room gets a fake coordinator."""

    def __init__(self, zones: dict[str, list[tuple[str, str]]]):
        self.entries = {r: R._Entry(r, rt) for rl in zones.values() for r, rt in rl}
        self.coords = {r: R._RoomCoord() for r in self.entries}
        self.hass = MagicMock()
        ents = list(self.entries.values())

        class _CEs:
            def async_entries(self, dom):
                return ents

        self.hass.config_entries = _CEs()
        self.hass.data = {DOMAIN: {}}
        self.absent: set[str] = set()
        self._sync()
        self.hass.states = MagicMock()
        self.hass.states.get = lambda e: None
        self.zm = _hz.ZoneManager(self.hass)
        for zid, rl in zones.items():
            z = _hz.ZoneState(zone_id=zid, zone_name=zid, climate_entity=f"climate.{zid}")
            z.rooms = [r for r, _ in rl]
            self.zm._zones[zid] = z

    def _sync(self):
        d = self.hass.data[DOMAIN]
        d.clear()
        for r, e in self.entries.items():
            if r not in self.absent:
                d[e.entry_id] = self.coords[r]

    def set(self, room, *, occupied=None, ev="keep", active=None, refresh_ok=None):
        c = self.coords[room]
        if occupied is not None:
            c.data = {"occupied": occupied}
        if ev != "keep":
            c.ev = ev
        if active is not None:
            c.active = active
        if refresh_ok is not None:
            c.last_update_success = refresh_ok

    def tick(self, when, hs, zone_ids=None, dwell=0.0, edge=None):
        self._sync()
        with patch.object(_hz.dt_util, "now", return_value=when), \
             patch.object(_hz.dt_util, "utcnow", return_value=when):
            self.zm.update_room_conditions(
                house_state=hs, zone_ids=zone_ids, entry_dwell_s=dwell,
                away_edge_fn=(edge or (lambda z: False)), return_window_s=0.0,
            )

    def rows(self, row_type="episode"):
        return [r for r in self.zm._ev_shadow_pending_rows if r["row_type"] == row_type]


@pytest.fixture
def no_boot(monkeypatch):
    """Most tracker tests start at the first pass; open the boot window."""
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S", 0)


def _iso(t):
    return t.isoformat()


# ==========================================================================
# D1: shadow terms before the early return
# ==========================================================================

def test_shadow_term_matches_evidence_rule_in_evidence_states():
    """200 random (ev age, active) tuples, refresh_ok True, W = 0: in
    home_day the shadow term equals the live evidence decision."""
    rng = random.Random(7)
    zm = _hz.ZoneManager(MagicMock())
    for i in range(200):
        room = f"r{i}"
        rt = rng.choice(["bedroom", "common_area", "closet", "generic", "bathroom"])
        ev = None if rng.random() < 0.15 else T0 - S(seconds=rng.randint(0, 600))
        active = rng.random() < 0.3
        live = zm._compute_hvac_occupied(
            room_name=room, room_type=rt, state_occupied=rng.random() < 0.5,
            now=T0, house_state="home_day", last_evidence=ev,
            evidence_active=active, refresh_ok=True, apply_evidence_rule=True,
            entry_dwell_s=0.0,
        )
        assert zm._hvac_ev_shadow_out[room] is live, (rt, ev, active)
        assert zm._ev_shadow_pass_rooms[room] is True


def test_shadow_term_computed_in_legacy_states():
    """guest (legacy). Bedroom evidence hold 240 (independent literal):
    evidence 200 s old -> shadow evidence True; 250 s old -> False while
    the legacy side stays True (lighting `occupied` still riding)."""
    zm = _hz.ZoneManager(MagicMock())

    def _p(age):
        return zm._compute_hvac_occupied(
            room_name="b", room_type="bedroom", state_occupied=True, now=T0,
            house_state="guest", last_evidence=T0 - S(seconds=age),
            evidence_active=False, refresh_ok=True, apply_evidence_rule=True,
        )
    assert _p(200) is True                      # live (legacy) output
    assert zm._hvac_ev_shadow_out["b"] is True
    assert _p(250) is True                      # legacy still holds
    assert zm._hvac_ev_shadow_out["b"] is False
    assert zm._hvac_legacy_shadow_out["b"] is True
    assert zm._hvac_rule["b"] == "legacy"


def test_shadow_term_boundaries_hardcoded():
    """Bedroom hold 240: 239 s -> True, 240 s -> False (strict <), 241 ->
    False; refresh failing -> `active` ignored."""
    zm = _hz.ZoneManager(MagicMock())
    for age, want in ((239, True), (240, False), (241, False)):
        zm._compute_hvac_occupied(
            room_name="b", room_type="bedroom", state_occupied=False, now=T0,
            house_state="away", last_evidence=T0 - S(seconds=age),
            evidence_active=False, refresh_ok=True, apply_evidence_rule=True,
        )
        assert zm._hvac_ev_shadow_out["b"] is want, age
    zm._compute_hvac_occupied(
        room_name="b", room_type="bedroom", state_occupied=False, now=T0,
        house_state="away", last_evidence=T0 - S(seconds=900),
        evidence_active=True, refresh_ok=False, apply_evidence_rule=True,
    )
    assert zm._hvac_ev_shadow_out["b"] is False
    assert zm._ev_shadow_pass_rooms["b"] is False


def test_legacy_shadow_dict_in_evidence_states():
    """home_day: lighting `occupied` riding, evidence 250 s old (> 240):
    live output False (evidence rule), legacy dict True (shadow armed)."""
    zm = _hz.ZoneManager(MagicMock())
    out = zm._compute_hvac_occupied(
        room_name="b", room_type="bedroom", state_occupied=True, now=T0,
        house_state="home_day", last_evidence=T0 - S(seconds=250),
        evidence_active=False, refresh_ok=True, apply_evidence_rule=True,
    )
    assert out is False
    assert zm._hvac_output["b"] is False
    assert zm._hvac_legacy_shadow_out["b"] is True
    assert zm._hvac_ev_shadow_out["b"] is False


def test_const_off_writes_no_shadow_state(monkeypatch):
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_ENABLED", False)
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", active=False)
    w.tick(T0 + S(seconds=400), "guest")
    w.zm.reset_daily_counters()
    zm = w.zm
    assert zm._hvac_ev_shadow_out == {} and zm._hvac_legacy_shadow_out == {}
    assert zm._ev_shadow_pass_rooms == {} and zm._ev_shadow_ep == {}
    assert zm._ev_shadow_pending_rows == [] and zm._ev_shadow_first_pass_at is None


# ==========================================================================
# D2: zone tracker and exposure
# ==========================================================================

def _guest_less_open(w, room="b"):
    """t0: occupied + evidence. t0+240: evidence 240 s old (released for
    the evidence rule), lighting still occupied (legacy holds) -> a `less`
    episode opens at t0+240."""
    w.set(room, occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set(room, active=False)
    w.tick(T0 + S(seconds=240), "guest")
    ep = w.zm._ev_shadow_ep["z1"]["open"]
    assert ep is not None and ep["kind"] == "less"
    assert ep["started_at"] == T0 + S(seconds=240)


def test_episode_resumed(no_boot):
    """Evidence stops at t0, legacy holds (lighting riding), evidence
    returns at t0+420 -> less / resumed, 180 s."""
    w = _World({"z1": [("b", "bedroom")]})
    _guest_less_open(w)
    w.tick(T0 + S(seconds=300), "guest")
    w.set("b", active=True, ev=T0 + S(seconds=420))
    w.tick(T0 + S(seconds=420), "guest")
    rows = w.rows()
    assert len(rows) == 1
    r = rows[0]
    assert (r["kind"], r["outcome"], r["house_state"], r["rule"]) == ("less", "resumed", "guest", "legacy")
    assert r["duration_s"] == 180.0
    assert r["started_at"] == _iso(T0 + S(seconds=240))
    assert r["ended_at"] == _iso(T0 + S(seconds=420))
    assert r["details"]["legacy_rooms"] == ["b"]
    assert r["details"]["resumed_rooms"] == ["b"]


def test_unobserved_release_then_reentry_is_released(no_boot):
    """F2. t0+240: lighting off -> legacy tail to t0+300 (bedroom legacy
    tail 60). No pass sees the release. t0+360: the person re-enters and
    the next pass is a zone-scoped fast run -> legacy re-armed AND
    evidence back -> `released`, ended_at = t0+300 (the rev-1 rule would
    have booked `resumed`)."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", occupied=False, active=False)
    w.tick(T0 + S(seconds=240), "guest")
    assert w.zm._hvac_tail_until["b"] == T0 + S(seconds=300)
    w.set("b", occupied=True, active=True, ev=T0 + S(seconds=360))
    w.tick(T0 + S(seconds=360), "guest", zone_ids={"z1"})
    rows = w.rows()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "released"
    assert rows[0]["ended_at"] == _iso(T0 + S(seconds=300))
    assert rows[0]["duration_s"] == 60.0


def test_observed_release_closes_released(no_boot):
    """Legacy releases on a pass (tail expired): closes `released` at the
    tail instant, not at the pass time."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", occupied=False, active=False)
    w.tick(T0 + S(seconds=240), "guest")          # tail to t0+300, opens
    w.tick(T0 + S(seconds=400), "guest")          # released (observed)
    r = w.rows()[0]
    assert r["outcome"] == "released"
    assert r["ended_at"] == _iso(T0 + S(seconds=300))


def test_hallway_retype_mid_episode(no_boot):
    """F6. A room re-typed to hallway mid-episode drops out of both sides
    on that pass, although its stale dict entries still read True."""
    w = _World({"z1": [("b", "bedroom")]})
    _guest_less_open(w)
    w.entries["b"].data[CONF_ROOM_TYPE] = "hallway"
    w.tick(T0 + S(seconds=300), "guest")
    zm = w.zm
    assert "b" not in zm._ev_shadow_pass_rooms
    assert zm._hvac_legacy_shadow_out["b"] is True      # stale, not read
    assert zm._ev_shadow_ep["z1"]["L"] is False
    assert w.rows()[0]["outcome"] == "released"


def test_absent_room_not_read(no_boot):
    """F6. A coordinator-absent room's previous True is not read."""
    w = _World({"z1": [("b", "bedroom")]})
    _guest_less_open(w)
    w.absent.add("b")
    w.tick(T0 + S(seconds=300), "guest")
    zm = w.zm
    assert "b" not in zm._ev_shadow_pass_rooms
    assert zm._hvac_legacy_shadow_out["b"] is True
    assert zm._ev_shadow_ep["z1"]["L"] is False


def test_episode_interrupted_on_state_change(no_boot):
    w = _World({"z1": [("b", "bedroom")]})
    _guest_less_open(w)
    w.tick(T0 + S(seconds=400), "away")
    r = w.rows()[0]
    assert (r["outcome"], r["house_state"], r["rule"]) == ("interrupted", "guest", "legacy")
    assert r["duration_s"] == 160.0


def test_fast_run_zone_filter_isolated(no_boot):
    """A fast run on z2 leaves z1's episode record and exposure untouched."""
    w = _World({"z1": [("b", "bedroom")], "z2": [("m", "media_room")]})
    _guest_less_open(w)
    w.tick(T0 + S(seconds=300), "guest")
    rec_before = dict(w.zm._ev_shadow_ep["z1"])
    expo_before = dict(w.zm._ev_shadow_expo)
    assert expo_before[("z1", "guest")] == 300.0
    w.tick(T0 + S(seconds=500), "guest", zone_ids={"z2"})
    assert w.zm._ev_shadow_ep["z1"] == rec_before
    assert w.zm._ev_shadow_expo == expo_before
    assert w.zm._ev_shadow_ep["z2"]["t"] == T0 + S(seconds=500)


def test_lighting_only_hallway_occupant_no_episode(no_boot):
    """A hallway occupant (lighting only) neither opens nor closes."""
    w = _World({"z1": [("b", "bedroom"), ("h", "hallway")]})
    w.set("h", occupied=True, ev=T0, active=True)
    for k in range(6):
        w.tick(T0 + S(seconds=300 * k), "guest")
    assert w.zm._ev_shadow_ep["z1"]["open"] is None
    assert w.zm._ev_shadow_pending_rows == []


def test_more_episode_kind_more(no_boot):
    """guest: legacy released (lighting off past the 60 s tail) while a
    fresh evidence stamp holds the evidence side -> `more`; it closes
    `released` when the evidence side releases."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", occupied=False, active=False, ev=T0 + S(seconds=100))
    w.tick(T0 + S(seconds=100), "guest")                 # tail to t0+160
    w.tick(T0 + S(seconds=200), "guest")                 # legacy released, ev 100 s old
    ep = w.zm._ev_shadow_ep["z1"]["open"]
    assert ep is not None and ep["kind"] == "more"
    w.tick(T0 + S(seconds=400), "guest")                 # ev 300 s old > 240
    r = w.rows()[0]
    assert (r["kind"], r["outcome"], r["duration_s"]) == ("more", "released", 200.0)


def test_short_episode_writes_no_row(no_boot):
    """59 s episode -> no row; 60 s -> a row (MIN_EPISODE_S = 60)."""
    for gap, want in ((59, 0), (60, 1)):
        w = _World({"z1": [("b", "bedroom")]})
        _guest_less_open(w)
        w.set("b", active=True, ev=T0 + S(seconds=240 + gap))
        w.tick(T0 + S(seconds=240 + gap), "guest")
        assert len(w.rows()) == want, gap


def test_exposure_seconds_and_gap_cap(no_boot):
    """F1. One zone legacy-occupied for exactly 2 h in guest (legacy tail
    0 via a day override of 0): passes every 300 s t0..t0+7200, released
    on the t0+7500 pass -> 7500 s (the interval ending at the
    release-observing pass is charged to the previous, occupied pass).
    Then a 900 s gap (3 ticks) while occupied adds 600 (2 ticks)."""
    w = _World({"z1": [("b", "bedroom")]})
    w.entries["b"].options = {"hvac_vacancy_hold": 0}
    w.set("b", occupied=True, ev=T0, active=True)

    def _total():
        return w.zm._ev_shadow_expo.get(("z1", "guest"), 0.0) + sum(
            r["duration_s"] for r in w.rows("exposure"))
    for k in range(0, 25):
        w.tick(T0 + S(seconds=300 * k), "guest")
    w.set("b", occupied=False, active=False)
    w.tick(T0 + S(seconds=7500), "guest")
    assert _total() == 7500.0
    w.tick(T0 + S(seconds=7800), "guest")                # L False: nothing charged
    assert _total() == 7500.0
    w.set("b", occupied=True, active=True, ev=T0 + S(seconds=8100))
    w.tick(T0 + S(seconds=8100), "guest")
    w.tick(T0 + S(seconds=9000), "guest")                # 900 s gap -> +600
    assert _total() == 8100.0
    w.zm.reset_daily_counters()
    ex = w.rows("exposure")
    # A-M1: written incrementally at every 1800 s, the rest at midnight.
    assert [r["duration_s"] for r in ex] == [1800.0, 1800.0, 1800.0, 1800.0, 900.0]
    assert {(r["zone_id"], r["house_state"], r["rule"]) for r in ex} == {("z1", "guest", "legacy")}
    assert w.zm._ev_shadow_expo == {} and w.zm._ev_shadow_rows_today == {}


def test_exposure_written_incrementally_before_midnight(no_boot):
    """A-M1: exposure reaches the queue without a daily reset, so a restart
    loses < 1800 s per (zone, state). 1799 s -> no row; 1800 s -> one row
    of 1800 and the bucket is zeroed."""
    assert HC.HVAC_EVIDENCE_SHADOW_EXPOSURE_FLUSH_S == 1800
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "home_day")
    w.tick(T0 + S(seconds=299), "home_day")
    for k in range(1, 6):
        w.tick(T0 + S(seconds=299 + 300 * k), "home_day")   # 1799 s
    assert w.rows("exposure") == []
    w.tick(T0 + S(seconds=1800), "home_day")
    assert [(r["house_state"], r["duration_s"]) for r in w.rows("exposure")] == [("home_day", 1800.0)]
    assert w.zm._ev_shadow_expo[("z1", "home_day")] == 0.0


def test_exposure_charged_to_previous_state(no_boot):
    """The interval is charged to the PREVIOUS pass's house state."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.tick(T0 + S(seconds=300), "home_day")
    w.tick(T0 + S(seconds=420), "home_day")
    assert w.zm._ev_shadow_expo == {("z1", "guest"): 300.0, ("z1", "home_day"): 120.0}


def test_boot_window_excluded():
    """F9, default 600 s window (literals). First pass t0 anchors boot.
    A divergence at t0+599 opens nothing; at t0+600 it opens with
    opened_s_after_boot 600. Exposure: nothing before t0+600."""
    assert HC.HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S == 600
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0 - S(seconds=1000), active=False)
    w.tick(T0, "guest")                                   # L True, E False
    w.tick(T0 + S(seconds=599), "guest")
    assert w.zm._ev_shadow_ep["z1"]["open"] is None
    assert w.zm._ev_shadow_expo == {}
    w.tick(T0 + S(seconds=600), "guest")
    ep = w.zm._ev_shadow_ep["z1"]["open"]
    assert ep is not None and ep["opened_s_after_boot"] == 600.0
    assert w.zm._ev_shadow_expo == {}                    # interval ends at boot end
    w.tick(T0 + S(seconds=601), "guest")
    assert w.zm._ev_shadow_expo == {("z1", "guest"): 1.0}


def test_pending_and_refresh_rooms_are_episode_unions(no_boot):
    """F8. home_day, knob 47 W = 300 s, zone on its away edge: a cold room
    with fresh evidence is PENDING (evidence side held empty) while the
    lighting arm holds the legacy side -> `less`. A second room's refresh
    fails on one pass only. Both appear in the row although neither holds
    on the closing pass."""
    w = _World({"z1": [("k", "common_area"), ("c", "closet")]})
    edge = lambda z: True  # noqa: E731
    w.set("k", occupied=True, ev=T0, active=True)
    w.coords["k"].onset = T0
    w.tick(T0, "home_day", dwell=300.0, edge=edge)
    assert w.zm._hvac_pending["k"] is True
    w.set("c", refresh_ok=False)
    w.tick(T0 + S(seconds=120), "home_day", dwell=300.0, edge=edge)
    w.set("c", refresh_ok=True)
    w.set("k", ev=T0 + S(seconds=320))
    w.tick(T0 + S(seconds=320), "home_day", dwell=300.0, edge=edge)
    assert w.zm._hvac_pending["k"] is False
    r = w.rows()[0]
    assert (r["kind"], r["outcome"], r["rule"]) == ("less", "resumed", "evidence")
    assert r["details"]["pending_rooms"] == ["k"]
    assert r["details"]["refresh_failed_rooms"] == ["c"]


def test_tracker_exception_does_not_raise(monkeypatch, no_boot):
    """A tracker / note fault is swallowed; the producer's outputs are the
    same as without the recorder."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(w.zm, "_ev_shadow_track", _boom)
    monkeypatch.setattr(w.zm, "_ev_shadow_term", _boom)
    monkeypatch.setattr(w.zm, "_ev_shadow_flush_exposure", _boom)
    w.tick(T0, "guest")
    w.zm.reset_daily_counters()
    assert w.zm.zones["z1"].any_room_hvac_occupied is True
    assert w.zm._hvac_output["b"] is True


def test_row_cap_per_zone_day(monkeypatch, no_boot):
    """Cap 2 (scoped): episodes 1-2 written, the 3rd writes ONE `capped`
    row, the 4th nothing; the daily reset re-opens the budget."""
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY", 2)
    w = _World({"z1": [("b", "bedroom")]})

    def _one_episode(t):
        w.set("b", occupied=True, ev=t, active=True)
        w.tick(t, "guest")
        w.set("b", active=False)
        w.tick(t + S(seconds=240), "guest")
        w.set("b", active=True, ev=t + S(seconds=400))
        w.tick(t + S(seconds=400), "guest")
        return t + S(seconds=1000)
    t = T0
    for _ in range(4):
        t = _one_episode(t)
    kinds = [r["row_type"] for r in w.zm._ev_shadow_pending_rows if r["row_type"] != "exposure"]
    assert kinds == ["episode", "episode", "capped"]
    w.zm.reset_daily_counters()
    w.zm.drain_shadow_rows()
    _one_episode(t)
    assert [r["row_type"] for r in w.zm._ev_shadow_pending_rows if r["row_type"] != "exposure"] == ["episode"]


def test_zone_removed_closes_interrupted(no_boot):
    """E5. A zone gone from the manager closes `interrupted` on the next
    FULL pass and drops its exposure without a row."""
    w = _World({"z1": [("b", "bedroom")], "z2": [("m", "media_room")]})
    _guest_less_open(w)
    w.tick(T0 + S(seconds=300), "guest")
    del w.zm._zones["z1"]
    w.tick(T0 + S(seconds=400), "guest", zone_ids={"z2"})
    assert "z1" in w.zm._ev_shadow_ep                     # filtered pass: kept
    w.tick(T0 + S(seconds=500), "guest")
    assert "z1" not in w.zm._ev_shadow_ep
    assert not any(k[0] == "z1" for k in w.zm._ev_shadow_expo)
    r = w.rows()[0]
    assert (r["zone_id"], r["outcome"], r["duration_s"]) == ("z1", "interrupted", 260.0)


def test_night_state_episode_rule(no_boot):
    """sleep (night rule): the night tail (bedroom 1800) holds the legacy
    side long after the 240 s evidence release -> `less`, rule `night`."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "sleep")
    w.set("b", occupied=False, active=False)
    w.tick(T0 + S(seconds=300), "sleep")
    w.set("b", occupied=True, active=True, ev=T0 + S(seconds=900))
    w.tick(T0 + S(seconds=900), "sleep")
    r = w.rows()[0]
    assert (r["rule"], r["kind"], r["outcome"], r["duration_s"]) == ("night", "less", "resumed", 600.0)


# ==========================================================================
# D3: the table, the write, the prune
# ==========================================================================

from custom_components.universal_room_automation import database as db_mod  # noqa: E402
from custom_components.universal_room_automation import nightly_maintenance as nm_mod  # noqa: E402


def _make_db(tmp_path):
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)

    def _schedule(coro, name=None):
        return asyncio.ensure_future(coro)
    hass.async_create_background_task = _schedule
    hass.async_create_task = _schedule

    async def _exec(func, *args):
        return func(*args)
    hass.async_add_executor_job = _exec
    return db_mod.UniversalRoomDatabase(hass)


async def _with_db(db, body):
    await db.initialize()
    await db.start_write_worker()
    try:
        out = await body()
        await db._write_queue.join()
        return out
    finally:
        if db._write_task is not None and not db._write_task.done():
            db._write_task.cancel()
            try:
                await db._write_task
            except asyncio.CancelledError:
                pass


def _sample_rows(n=5):
    rows = []
    for i in range(n):
        rows.append(_hz.ZoneManager._ev_shadow_row(
            T0 + S(seconds=i), "episode", "z1", "guest", rule="legacy",
            kind="less", outcome="resumed", started_at=T0, ended_at=T0 + S(seconds=300),
            duration_s=300.0, opened_s_after_boot=900.0,
            details={"legacy_rooms": ["b"], "resumed_rooms": ["b"],
                     "refresh_failed_rooms": [], "pending_rooms": []},
        ))
    return rows


@pytest.mark.asyncio
async def test_table_created_idempotent(tmp_path):
    db = _make_db(tmp_path)

    async def body():
        await db.initialize()                             # second time
    await _with_db(db, body)
    con = sqlite3.connect(db.db_file)
    cols = [r[1] for r in con.execute("PRAGMA table_info(hvac_evidence_shadow)")]
    idx = [r[1] for r in con.execute("PRAGMA index_list(hvac_evidence_shadow)")]
    con.close()
    assert cols == [
        "id", "timestamp", "row_type", "zone_id", "house_state", "rule", "kind",
        "outcome", "started_at", "ended_at", "duration_s", "opened_s_after_boot",
        "details_json",
    ]
    assert "idx_hvac_ev_shadow_ts" in idx


@pytest.mark.asyncio
async def test_drain_batches_one_executemany(tmp_path):
    """One call with 5 rows -> one write connection, one executemany, no
    per-row execute; five rows in the real table, typed columns, JSON."""
    from contextlib import asynccontextmanager
    db = _make_db(tmp_path)
    calls = {"db": 0, "many": 0, "exec_insert": 0}
    orig_db = db._db

    @asynccontextmanager
    async def _spy_db():
        calls["db"] += 1
        async with orig_db() as conn:
            orig_many, orig_exec = conn.executemany, conn.execute

            async def _many(*a, **k):
                calls["many"] += 1
                return await orig_many(*a, **k)

            async def _exec(sql, *a, **k):
                if "INSERT INTO hvac_evidence_shadow" in sql:
                    calls["exec_insert"] += 1
                return await orig_exec(sql, *a, **k)
            conn.executemany, conn.execute = _many, _exec
            yield conn

    async def body():
        db._db = _spy_db
        try:
            return await db.log_hvac_evidence_shadow(_sample_rows(5))
        finally:
            db._db = orig_db
    assert await _with_db(db, body) == 5
    assert calls == {"db": 1, "many": 1, "exec_insert": 0}
    con = sqlite3.connect(db.db_file)
    rows = con.execute(
        "SELECT row_type, zone_id, house_state, kind, outcome, duration_s, "
        "opened_s_after_boot, details_json FROM hvac_evidence_shadow"
    ).fetchall()
    con.close()
    assert len(rows) == 5
    assert rows[0][:7] == ("episode", "z1", "guest", "less", "resumed", 300.0, 900.0)
    assert json.loads(rows[0][7])["legacy_rooms"] == ["b"]


@pytest.mark.asyncio
async def test_prune_window(tmp_path, monkeypatch):
    """Default window 180 d (literal): 181 d old goes, 179 d stays. A
    window of 0 is clamped to 1 d: the 36 h row goes, the 1 h row stays."""
    from types import SimpleNamespace
    now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db_mod, "dt_util", SimpleNamespace(utcnow=lambda: now, now=lambda: now))
    db = _make_db(tmp_path)
    old = (now - S(days=181)).isoformat()
    kept = (now - S(days=179)).isoformat()
    h36 = (now - S(hours=36)).isoformat()
    h1 = (now - S(hours=1)).isoformat()

    async def body():
        rows = _sample_rows(4)
        for r, ts in zip(rows, (old, kept, h36, h1)):
            r["timestamp"] = ts
        await db.log_hvac_evidence_shadow(rows)
        d1 = await db.prune_hvac_evidence_shadow()
        con = sqlite3.connect(db.db_file)
        mid = sorted(r[0] for r in con.execute("SELECT timestamp FROM hvac_evidence_shadow"))
        con.close()
        d2 = await db.prune_hvac_evidence_shadow(window_days=0)
        return d1, mid, d2
    d1, mid, d2 = await _with_db(db, body)
    assert d1 == 1 and mid == sorted([kept, h36, h1])
    assert d2 == 2
    con = sqlite3.connect(db.db_file)
    left = [r[0] for r in con.execute("SELECT timestamp FROM hvac_evidence_shadow")]
    con.close()
    assert left == [h1]


def test_prune_registered_nightly():
    ops = {name: (meth, kw) for name, meth, kw in nm_mod.nightly_cleanup_ops()}
    assert ops["hvac_evidence_shadow"] == ("prune_hvac_evidence_shadow", {})


@pytest.mark.asyncio
async def test_nightly_runner_calls_shadow_prune():
    """The real runner reaches the op (anchor for the list entry)."""
    called = []

    class _DB:
        def __getattr__(self, name):
            async def _m(**kw):
                called.append(name)
            return _m

    async def _no_sleep(_s):
        return None
    await nm_mod.run_nightly_cleanup({}, _DB(), sleep=_no_sleep)
    assert "prune_hvac_evidence_shadow" in called


@pytest.mark.asyncio
async def test_no_activity_log_or_signal(tmp_path):
    """A shadow write touches only its own table: no ura_activity_log row
    (so no Last Activity sensor / ura_action bus event path)."""
    db = _make_db(tmp_path)

    async def body():
        await db.log_hvac_evidence_shadow(_sample_rows(2))
    await _with_db(db, body)
    con = sqlite3.connect(db.db_file)
    n_act = con.execute("SELECT COUNT(*) FROM ura_activity_log").fetchone()[0]
    n_sh = con.execute("SELECT COUNT(*) FROM hvac_evidence_shadow").fetchone()[0]
    con.close()
    assert (n_act, n_sh) == (0, 2)


# ==========================================================================
# D4: containment
# ==========================================================================

import ast  # noqa: E402
import importlib.util  # noqa: E402
import inspect  # noqa: E402
from pathlib import Path  # noqa: E402

_PKG = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
_SHADOW_ATTRS = {
    "_hvac_ev_shadow_out", "_hvac_legacy_shadow_out", "_ev_shadow_pass_rooms",
    "_ev_shadow_ep", "_ev_shadow_expo", "_ev_shadow_rows_today",
    "_ev_shadow_pending_rows", "_ev_shadow_first_pass_at",
}
# Functions allowed to touch the shadow state (plan D4: E1, the tracker,
# the drain, reset_daily_counters; plus the constructor and E2's clear).
_ALLOWED = {
    "__init__", "update_room_conditions", "reset_daily_counters",
    "_ev_shadow_note_room", "_ev_shadow_run_tracker", "_ev_shadow_track",
    "_ev_shadow_finish", "_ev_shadow_zone_removed", "_ev_shadow_flush_exposure",
    "_ev_shadow_queue_exposure", "drain_shadow_rows",
}


def _func_attr_uses(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Attribute(self, node):
            if node.attr in _SHADOW_ATTRS:
                out.append((self.stack[-1] if self.stack else "<module>", node.attr, node.lineno))
            self.generic_visit(node)
    V().visit(tree)
    return out


def test_shadow_dicts_have_one_reader():
    """Containment lint (plan D4): across the integration, the shadow
    state is touched only inside the recorder's own functions."""
    bad = []
    for path in _PKG.rglob("*.py"):
        for fn, attr, line in _func_attr_uses(path):
            if path.name != "hvac_zones.py" or fn not in _ALLOWED:
                bad.append(f"{path.name}:{line} {fn} -> {attr}")
    assert not bad, bad


def test_hvac_occupied_diag_keys_unchanged():
    """No key is added to the per-room diagnostic (recorder churn)."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    assert set(w.zm.hvac_occupied_diag("b")) == {
        "armed", "tail_expires_at", "source", "rule", "output",
        "evidence_release_at", "release_at", "episode_start", "episode_onsets",
        "episode_active_s", "armed_at", "arm_span_s", "arm_class", "dwell_s",
        "exempt_reason", "pending", "cold", "released_at",
    }


def test_no_await_in_tracker():
    """The tracker, the queue and the drain are sync (never awaited on
    the producer path)."""
    ZM = _hz.ZoneManager
    for name in (
        "_ev_shadow_term", "_ev_shadow_note_room", "_ev_shadow_run_tracker",
        "_ev_shadow_track", "_ev_shadow_note_releases", "_ev_shadow_verdict",
        "_ev_shadow_finish", "_ev_shadow_row", "_ev_shadow_zone_removed",
        "_ev_shadow_flush_exposure", "drain_shadow_rows", "update_room_conditions",
        "reset_daily_counters",
    ):
        fn = getattr(ZM, name)
        assert not inspect.iscoroutinefunction(fn), name
        assert not inspect.isasyncgenfunction(fn), name


# ==========================================================================
# D5: the §7 verdict query as a tested artifact
# ==========================================================================

_PROBE = Path(__file__).resolve().parents[2] / "scripts" / "probes" / "hvac_evidence_shadow_verdict.py"


def _verdict_mod():
    spec = importlib.util.spec_from_file_location("_ev_verdict", _PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ep(state, *, outcome="resumed", dur=400.0, kind="less", boot=5000.0,
        pending=(), refresh=(), ts="2026-11-12T00:00:00+00:00"):
    return {"timestamp": ts, "row_type": "episode", "zone_id": "zone_1",
            "house_state": state, "rule": "legacy", "kind": kind, "outcome": outcome,
            "started_at": ts, "ended_at": ts, "duration_s": dur,
            "opened_s_after_boot": boot,
            "details": {"legacy_rooms": ["b"], "resumed_rooms": [],
                        "refresh_failed_rooms": list(refresh), "pending_rooms": list(pending)}}


def _ex(state, hours, ts="2026-11-12T06:00:00+00:00"):
    return {"timestamp": ts, "row_type": "exposure", "zone_id": "zone_1",
            "house_state": state, "rule": "legacy", "duration_s": hours * 3600.0,
            "details": None}


async def _verdicts(tmp_path, rows, **kw):
    db = _make_db(tmp_path)

    async def body():
        await db.log_hvac_evidence_shadow(rows)
    await _with_db(db, body)
    con = sqlite3.connect(db.db_file)
    try:
        out = _verdict_mod().run_verdict(con, since="2026-11-11T00:00:00", grace=300, **kw)
    finally:
        con.close()
    return {r["st"]: r for r in out}


@pytest.mark.asyncio
async def test_verdict_query_branches(tmp_path):
    """Reference home_day 100 h with 1 premature -> ref 0.01; bar =
    max(1.5 x 0.01, 0.02) = 0.02 (literals)."""
    rows = [
        _ex("home_day", 100), _ep("home_day"),
        _ex("guest", 50),                                         # zero rows -> SAFE
        _ex("sleep", 40), *[_ep("sleep") for _ in range(5)],       # 0.125 -> NOT SAFE
        _ex("away", 10),                                          # floor -> INSUFFICIENT
        _ex("waking", 40), _ep("waking"), _ep("waking"),           # 0.05, 2 ev -> INSUFFICIENT
        _ex("arriving", 40),
        _ep("arriving", pending=["b"]), _ep("arriving", refresh=["b"]),
        _ep("arriving", boot=100.0),                              # all excluded
        _ep("arriving", outcome="released"),                      # saved
        _ep("arriving", dur=200.0),                               # below grace
        _ep("arriving", kind="more", outcome="released"),
        _ep("guest", ts="2026-11-01T00:00:00+00:00"),             # before :since
    ]
    v = await _verdicts(tmp_path, rows)
    assert v["home_day"]["verdict"] == "REFERENCE"
    assert v["home_day"]["ref_rate"] == 0.01 and v["home_day"]["bar"] == 0.02
    assert (v["guest"]["verdict"], v["guest"]["premature"]) == ("SAFE", 0)
    assert (v["sleep"]["verdict"], v["sleep"]["premature"], v["sleep"]["rate"]) == ("NOT SAFE", 5, 0.125)
    assert v["away"]["verdict"] == "INSUFFICIENT"
    assert (v["waking"]["verdict"], v["waking"]["premature"]) == ("INSUFFICIENT", 2)
    a = v["arriving"]
    assert (a["verdict"], a["premature"], a["saved"], a["eligible"], a["more_eps"]) == ("SAFE", 0, 1, 1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("n,want", [(1, "INSUFFICIENT"), (2, "INSUFFICIENT"), (3, "NOT SAFE")])
async def test_verdict_zero_reference_rate(tmp_path, n, want):
    """Reference with exposure and NO episode rows -> ref_rate 0, bar =
    abs floor 0.02. guest 40 h: 1 / 2 / 3 premature = 0.025 / 0.05 /
    0.075 per h."""
    rows = [_ex("home_evening", 40), _ex("guest", 40), *[_ep("guest") for _ in range(n)]]
    v = await _verdicts(tmp_path, rows)
    assert v["home_evening"]["ref_rate"] == 0.0
    assert v["guest"]["verdict"] == want


@pytest.mark.asyncio
async def test_verdict_thin_reference(tmp_path):
    rows = [_ex("home_day", 20), _ex("guest", 40)]
    v = await _verdicts(tmp_path, rows)
    assert v["guest"]["verdict"] == "INSUFFICIENT (reference)"


# ==========================================================================
# Fix-up 1 (reviews A / B / C)
# ==========================================================================

def test_two_room_one_release_is_resumed_not_released(no_boot):
    """B-H1 repro. guest, z1 = b (bedroom) + k (common_area). t0+250: b's
    evidence is 250 s old (> 240) but its lighting still holds; k is off,
    legacy tail to t0+310. L True (b, k), E False -> `less` opens. t0+400:
    b's evidence returns; k released at t0+310 but b held L the whole time
    -> `resumed` (premature), 150 s. The old any-room rule said `released`."""
    w = _World({"z1": [("b", "bedroom"), ("k", "common_area")]})
    for r in ("b", "k"):
        w.set(r, occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", active=False)
    w.set("k", occupied=False, active=False)
    w.tick(T0 + S(seconds=250), "guest")
    assert w.zm._hvac_tail_until["k"] == T0 + S(seconds=310)
    w.set("b", active=True, ev=T0 + S(seconds=400))
    w.tick(T0 + S(seconds=400), "guest")
    r = w.rows()[0]
    assert (r["outcome"], r["duration_s"], r["ended_at"]) == (
        "resumed", 150.0, _iso(T0 + S(seconds=400)))


def test_zone_release_is_latest_room_release(no_boot):
    """B-M1. b off at t0+250 (tail t0+310), k off at t0+280 (tail t0+340);
    both released by t0+500 -> `released`, ended_at = t0+340 (the zone's
    legacy side released with its LAST room), 90 s."""
    w = _World({"z1": [("b", "bedroom"), ("k", "common_area")]})
    for r in ("b", "k"):
        w.set(r, occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", occupied=False, active=False)
    w.set("k", active=False)
    w.tick(T0 + S(seconds=250), "guest")
    w.set("k", occupied=False)
    w.tick(T0 + S(seconds=280), "guest")
    w.tick(T0 + S(seconds=500), "guest")
    r = w.rows()[0]
    assert (r["outcome"], r["ended_at"], r["duration_s"]) == (
        "released", _iso(T0 + S(seconds=340)), 90.0)


def test_two_room_unobserved_release_of_both_is_released(no_boot):
    """B-H1 keeps F2: both holders released between passes (b at t0+310,
    k at t0+340), then a re-entry -> `released` at the LATER release
    (B-M1)."""
    w = _World({"z1": [("b", "bedroom"), ("k", "common_area")]})
    for r in ("b", "k"):
        w.set(r, occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", occupied=False, active=False)
    w.set("k", active=False)
    w.tick(T0 + S(seconds=250), "guest")            # opens; b tail t0+310
    w.set("k", occupied=False)
    w.tick(T0 + S(seconds=280), "guest")            # k tail t0+340
    w.set("b", occupied=True, active=True, ev=T0 + S(seconds=400))
    w.tick(T0 + S(seconds=400), "guest", zone_ids={"z1"})
    r = w.rows()[0]
    assert (r["outcome"], r["ended_at"]) == ("released", _iso(T0 + S(seconds=340)))


def test_superseded_release_does_not_count(no_boot):
    """A release followed by an OBSERVED re-arm no longer counts. b and k
    each release and come back (lighting, no evidence) while the episode
    stays open; evidence then returns with both holding -> `resumed`."""
    w = _World({"z1": [("b", "bedroom"), ("k", "common_area")]})
    for r in ("b", "k"):
        w.set(r, occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", active=False)
    w.set("k", active=False)
    w.tick(T0 + S(seconds=250), "guest")            # opens (both lighting on)
    w.set("b", occupied=False)
    w.tick(T0 + S(seconds=260), "guest")            # b tail t0+320
    w.tick(T0 + S(seconds=330), "guest")            # b release observed
    w.set("b", occupied=True)
    w.tick(T0 + S(seconds=340), "guest")            # b back (no evidence)
    w.set("k", occupied=False)
    w.tick(T0 + S(seconds=350), "guest")            # k tail t0+410
    w.tick(T0 + S(seconds=420), "guest")            # k release observed
    w.set("k", occupied=True)
    w.tick(T0 + S(seconds=430), "guest")            # k back
    assert w.rows() == []
    w.set("b", active=True, ev=T0 + S(seconds=500))
    w.tick(T0 + S(seconds=500), "guest")
    r = w.rows()[0]
    assert (r["outcome"], r["duration_s"]) == ("resumed", 250.0)


def test_zone_rediscovered_with_new_rooms_closes_interrupted(no_boot):
    """B-L1. Same zone id, different room set -> the open episode closes
    `interrupted` and the record restarts on the new rooms."""
    w = _World({"z1": [("b", "bedroom"), ("k", "common_area")]})
    w.zm._zones["z1"].rooms = ["b"]
    _guest_less_open(w)
    w.zm._zones["z1"].rooms = ["b", "k"]
    w.tick(T0 + S(seconds=400), "guest")
    r = w.rows()[0]
    assert (r["outcome"], r["duration_s"]) == ("interrupted", 160.0)
    assert w.zm._ev_shadow_ep["z1"]["rooms"] == ("b", "k")


def test_more_episode_resumed_and_flipped(no_boot):
    """C MEDIUM-3. `more` (legacy released, fresh evidence holds E) ->
    legacy re-arms with evidence: `resumed`; legacy re-arms without
    evidence: `flipped`."""
    def _more_open():
        w = _World({"z1": [("b", "bedroom")]})
        w.set("b", occupied=True, ev=T0, active=True)
        w.tick(T0, "guest")
        w.set("b", occupied=False, active=False, ev=T0 + S(seconds=100))
        w.tick(T0 + S(seconds=100), "guest")
        w.tick(T0 + S(seconds=200), "guest")
        assert w.zm._ev_shadow_ep["z1"]["open"]["kind"] == "more"
        return w
    w = _more_open()
    w.set("b", occupied=True, active=True, ev=T0 + S(seconds=290))
    w.tick(T0 + S(seconds=290), "guest")
    r = w.rows()[0]
    assert (r["kind"], r["outcome"], r["duration_s"]) == ("more", "resumed", 90.0)
    w = _more_open()
    w.set("b", occupied=True)
    w.tick(T0 + S(seconds=400), "guest")             # ev 300 s old -> E False
    r = w.rows()[0]
    assert (r["kind"], r["outcome"], r["duration_s"]) == ("more", "flipped", 200.0)


def test_none_house_state_rows(no_boot):
    """C MEDIUM-2. House state None is recorded as "none" on episode and
    exposure rows, with rule `legacy`."""
    w = _World({"z1": [("b", "bedroom")]})
    w.set("b", occupied=True, ev=T0, active=True)
    w.tick(T0, None)
    w.set("b", active=False)
    w.tick(T0 + S(seconds=240), None)
    w.set("b", active=True, ev=T0 + S(seconds=420))
    w.tick(T0 + S(seconds=420), None)
    w.zm.reset_daily_counters()
    ep = w.rows()[0]
    ex = w.rows("exposure")[0]
    assert (ep["house_state"], ep["rule"]) == ("none", "legacy")
    assert (ex["house_state"], ex["rule"], ex["duration_s"]) == ("none", "legacy", 420.0)


def test_room_lists_capped_at_20():
    """C MEDIUM-1. 25 rooms in every list -> each written list is the
    sorted first 20."""
    zm = _hz.ZoneManager(MagicMock())
    names = [f"r{i:02d}" for i in range(25)]
    ep = {"kind": "less", "state": "guest", "rule": "legacy", "started_at": T0,
          "opened_s_after_boot": 900.0, "legacy_rooms": set(names),
          "refresh_failed_rooms": set(names), "pending_rooms": set(names),
          "tails": {}, "releases": {}}
    zm._ev_shadow_finish("z1", ep, "resumed", T0 + S(seconds=300),
                         T0 + S(seconds=300), resumed_rooms=list(reversed(names)))
    d = zm._ev_shadow_pending_rows[0]["details"]
    for key in ("legacy_rooms", "resumed_rooms", "refresh_failed_rooms", "pending_rooms"):
        assert d[key] == names[:20], key


def test_default_constants():
    """C LOW-4: rung-1 defaults pinned as literals."""
    assert HC.HVAC_EVIDENCE_SHADOW_ENABLED is True
    assert HC.HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S == 60
    assert HC.HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY == 96
    assert HC.HVAC_EVIDENCE_SHADOW_RETENTION_DAYS == 180
    assert HC.HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S == 600
    assert HC.HVAC_EVIDENCE_SHADOW_MAX_ROOMS_PER_LIST == 20
    assert HC.HVAC_EVIDENCE_SHADOW_EXPOSURE_FLUSH_S == 1800


@pytest.mark.asyncio
async def test_db_shutting_down_is_quiet(tmp_path, caplog):
    """A-L1 / C HIGH-1. DBShuttingDown -> 0, DEBUG only; any other failure
    -> 0 with one WARNING."""
    import logging
    from contextlib import asynccontextmanager
    db = _make_db(tmp_path)

    def _raising(exc):
        @asynccontextmanager
        async def _db():
            raise exc
            yield  # pragma: no cover
        return _db
    caplog.set_level(logging.DEBUG, logger=db_mod.__name__)
    db._db = _raising(db_mod.DBShuttingDown("stopping"))
    assert await db.log_hvac_evidence_shadow(_sample_rows(2)) == 0
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns == []
    assert any("shutting down" in r.getMessage() for r in caplog.records)
    caplog.clear()
    db._db = _raising(RuntimeError("disk"))
    assert await db.log_hvac_evidence_shadow(_sample_rows(2)) == 0
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1 and "insert failed" in warns[0].getMessage()


@pytest.mark.asyncio
async def test_malformed_rows_skipped(tmp_path):
    """C LOW-2. A row missing a NOT NULL field is skipped and not counted."""
    db = _make_db(tmp_path)
    rows = _sample_rows(3)
    rows[1]["zone_id"] = ""
    rows.append("not a dict")

    async def body():
        return await db.log_hvac_evidence_shadow(rows)
    assert await _with_db(db, body) == 2
    con = sqlite3.connect(db.db_file)
    n = con.execute("SELECT COUNT(*) FROM hvac_evidence_shadow").fetchone()[0]
    con.close()
    assert n == 2


@pytest.mark.asyncio
async def test_prune_multi_batch(tmp_path, monkeypatch):
    """C LOW-1. batch_size 2, 5 old rows + 1 new -> 5 deleted over 3
    batches, the new one kept."""
    from types import SimpleNamespace
    now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db_mod, "dt_util", SimpleNamespace(utcnow=lambda: now, now=lambda: now))
    db = _make_db(tmp_path)

    async def body():
        rows = _sample_rows(6)
        for i, r in enumerate(rows[:5]):
            r["timestamp"] = (now - S(days=200, seconds=i)).isoformat()
        rows[5]["timestamp"] = (now - S(days=1)).isoformat()
        await db.log_hvac_evidence_shadow(rows)
        return await db.prune_hvac_evidence_shadow(batch_size=2)
    assert await _with_db(db, body) == 5
    con = sqlite3.connect(db.db_file)
    n = con.execute("SELECT COUNT(*) FROM hvac_evidence_shadow").fetchone()[0]
    con.close()
    assert n == 1


@pytest.mark.asyncio
async def test_verdict_boundaries_and_outcome_sets(tmp_path):
    """C MEDIUM-4 + A-L2 (grace 300, floor 30 h, abs floor 0.02).
    - home_day exactly 30.0 h, no episodes: reference holds (floor is <).
    - guest 50 h: resumed dur=300 (grace is >=), released 300, flipped
      400, interrupted 400 -> eligible 4, premature 1, saved 1; rate 0.02
      == bar -> SAFE (SAFE is <=).
    - sleep exactly 30.0 h, no episodes -> SAFE (state floor is <).
    - waking 40 h after :since + 1000 h BEFORE it, 3 premature -> 0.075
      -> NOT SAFE (old exposure excluded).
    - away: one `more` episode, no exposure -> listed, NO EXPOSURE."""
    old = "2026-11-01T00:00:00+00:00"
    rows = [
        _ex("home_day", 30.0),
        _ex("guest", 50),
        _ep("guest", dur=300.0), _ep("guest", outcome="released", dur=300.0),
        _ep("guest", outcome="flipped", dur=400.0),
        _ep("guest", outcome="interrupted", dur=400.0),
        _ex("sleep", 30.0),
        _ex("waking", 40), _ex("waking", 1000, ts=old),
        *[_ep("waking") for _ in range(3)],
        _ep("away", kind="more", outcome="released"),
        # home_evening: episodes but no exposure -> must not feed ref_rate.
        _ep("home_evening"), _ep("home_evening"),
    ]
    v = await _verdicts(tmp_path, rows)
    assert v["home_day"]["verdict"] == "REFERENCE" and v["home_day"]["bar"] == 0.02
    g = v["guest"]
    assert (g["eligible"], g["premature"], g["saved"], g["rate"], g["verdict"]) == (4, 1, 1, 0.02, "SAFE")
    assert v["sleep"]["verdict"] == "SAFE"
    assert (v["waking"]["occ_zone_h"], v["waking"]["verdict"]) == (40.0, "NOT SAFE")
    a = v["away"]
    assert (a["occ_zone_h"], a["more_eps"], a["verdict"]) == (None, 1, "NO EXPOSURE")


def test_room_that_left_the_pass_is_not_a_holder(no_boot):
    """B-H1 holders = rooms legacy-on at the PREVIOUS pass. k leaves the
    pass (re-typed to hallway) without a release; b releases unobserved and
    re-enters -> `released` at b's release. Counting every episode room
    would wait on k forever and book `resumed`."""
    w = _World({"z1": [("b", "bedroom"), ("k", "common_area")]})
    for r in ("b", "k"):
        w.set(r, occupied=True, ev=T0, active=True)
    w.tick(T0, "guest")
    w.set("b", occupied=False, active=False)
    w.set("k", active=False)
    w.tick(T0 + S(seconds=250), "guest")              # opens; b tail t0+310
    w.entries["k"].data[CONF_ROOM_TYPE] = "hallway"
    w.tick(T0 + S(seconds=260), "guest")
    w.set("b", occupied=True, active=True, ev=T0 + S(seconds=400))
    w.tick(T0 + S(seconds=400), "guest", zone_ids={"z1"})
    r = w.rows()[0]
    assert (r["outcome"], r["ended_at"]) == ("released", _iso(T0 + S(seconds=310)))

