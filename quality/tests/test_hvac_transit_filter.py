"""HVAC fast occupancy response (v5.103.20) — D5: transit filter on the
away -> home edge (plan REV 7 §5b, drills 45-78, ruling R3).

INV-D5: (a) a cold room whose episode never persists never produces
`hvac_occupied = True`; (b) a cold room that persists produces True by
`t_persist + 45 s`; (c) D5 never applies in night/legacy states, to
hallways, to non-cold rooms, to zones whose last applied write is not
`away`, or to pre-arrival zones; (d) while the house stays in an evidence
state an unpersisted episode never causes a home/sleep write for Z by any
path — the pending hold (`pending and fused_empty and eligible`, a true
mirror of `_row1_hold_write`) blocks S1 in both directions while Z is
otherwise empty; pending / never-armed episodes never touch
`last_occupied_time`.

Reuses the D2 harness (real HVACCoordinator on the smoke StubHass, real
room-config entries, fake room coordinators with the accessor surface, a
hand-fired scheduler, a patched clock). Oracles are literals from the plan:
W = 60 s (knob 47 = 1), kitchen hold 180 -> J = 60, closet hold 60 -> J = 60,
exemption 900 s, alarm window 900 s.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402
from test_hvac_fast_occupancy_response import (  # noqa: E402
    S, T0, FakeScheduler, RoomCoord, _Clock, _captured, _drain, _entry_id,
    _pin_platform, _setup, _writes,
)


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    return True


KIT = "kitchen"
DIN = "dining"
ENT1 = "climate.test_zone_1"


def _away_zone(mods, clk, *, rooms=None, dwell=1, house_state="home_day",
               vacancy_away_age=600, grace=5):
    """zone_1 written away by a `vacant_past_grace` write `vacancy_away_age`
    seconds ago; rooms cold (no evidence yet); knob 47 = `dwell`."""
    rooms = rooms or {"zone_1": [(KIT, "common_area", {"occupied": False})]}
    coord, hass, coords, sched = _setup(
        mods, house_state=house_state, rooms=rooms, grace=grace,
        presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
    )
    coord._zone_entry_dwell = dwell
    away_at = clk.t - S(seconds=vacancy_away_age)
    coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", away_at)
    coord._zone_vacancy_away_at["zone_1"] = away_at
    coord._zone_last_away_reason["zone_1"] = "vacant_past_grace"
    z = coord.zone_manager.zones["zone_1"]
    z.last_occupied_time = away_at - S(seconds=grace * 60)
    _pass(coord, house_state)
    return coord, hass, coords, sched


def _pass(coord, house_state=None):
    hs = house_state or coord._house_state
    coord.zone_manager.update_room_conditions(
        house_state=hs, entry_dwell_s=float(coord._zone_entry_dwell) * 60.0,
        away_edge_fn=coord._zone_away_edge,
    )


async def _tick(coord, hass):
    """A periodic-tick S1 pass (producer + `_apply_house_state_presets`)."""
    _pass(coord)
    await coord._apply_house_state_presets()
    await _drain(hass)


def _evidence(rc: RoomCoord, *, onset, ev, active):
    rc.onset = onset
    rc.ev = ev
    rc.active = active


class _RC(RoomCoord):
    """RoomCoord + the D5 onset accessor."""

    def __init__(self, entry, **kw):
        super().__init__(entry, **kw)
        self.onset = None

    def get_hvac_evidence_onset(self):
        return self.onset


@pytest.fixture(autouse=True)
def _use_rc_with_onset():
    import test_hvac_fast_occupancy_response as D2
    orig = D2.RoomCoord
    D2.RoomCoord = _RC
    try:
        yield
    finally:
        D2.RoomCoord = orig


def _rows(hass, mods, action):
    return hass.data[mods["const"].DOMAIN]["activity_logger"].actions(action)


def _diag(coord, room):
    return coord.zone_manager.hvac_occupied_diag(room)


# ==========================================================================
# Transit and stay (rows 45, 46, 67, 68)
# ==========================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("pir_variant", [False, True])
async def test_transit_under_60s_no_write(mods, pir_variant):
    """Row 45/67/68 — periodic-tick horizon. A 20 s Kitchen transit at t=0
    into an away zone: tick 50 (pending -> hold, one row, no write), tick
    350 (lapsed, no pending, `last_occupied_time` untouched), tick 650. No
    home write at any tick. PIR variant: two pulses (0-5, 15-20) joined."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        z = coord.zone_manager.zones["zone_1"]
        lot_before = z.last_occupied_time
        # Evidence 0..20 s (active while it lasts), lighting `occupied` on.
        rc.data = {"occupied": True}
        _evidence(rc, onset=T0, ev=T0, active=True)
        # The listener sees the onset refresh: cold + not persisted -> a
        # re-check is scheduled, nothing queued.
        with _captured(hass) as tt:
            rc.refresh()
            assert tt.call_count == 0
        assert len(sched.live()) == 1
        if pir_variant:
            clk.t = T0 + S(seconds=5)
            _evidence(rc, onset=T0, ev=clk.t, active=False)
            rc.refresh()
            clk.t = T0 + S(seconds=15)
            _evidence(rc, onset=clk.t, ev=clk.t, active=True)
            rc.refresh()
        clk.t = T0 + S(seconds=20)
        _evidence(rc, onset=(T0 + S(seconds=15)) if pir_variant else T0,
                  ev=clk.t, active=False)
        rc.refresh()
        # Tick 50: pending -> hold.
        clk.t = T0 + S(seconds=50)
        await _tick(coord, hass)
        assert z.hvac_pending_arm_rooms == [KIT]
        assert z.any_room_hvac_occupied is False
        assert _writes(hass, ENT1) == []
        held = _rows(hass, mods, "preset_change_suppressed")
        assert len(held) == 1 and held[0]["details"]["reason"] == "pending_arm_hold"
        assert held[0]["details"]["pending_rooms"] == [KIT]
        assert z.last_occupied_time == lot_before
        # Tick 350: lapsed (ev 20 + J 60 = 80 < 350).
        clk.t = T0 + S(seconds=350)
        await _tick(coord, hass)
        assert z.hvac_pending_arm_rooms == []
        assert z.any_room_hvac_occupied is False
        assert _writes(hass, ENT1) == []
        assert z.last_occupied_time == lot_before
        assert coord.zone_manager.transit_filtered_today["zone_1"] == 1
        assert coord.zone_manager.room_release_at(KIT) is None
        # Tick 650 (past lapse + G + hold): still nothing.
        clk.t = T0 + S(seconds=650)
        await _tick(coord, hass)
        assert _writes(hass, ENT1) == []
        assert len(_rows(hass, mods, "preset_change_suppressed")) == 1
        assert z.last_occupied_time == lot_before
        assert z.pending_hold_s_today > 0


@pytest.mark.asyncio
async def test_stay_60s_writes_within_sla(mods):
    """Row 46. Continuous evidence from t=0: the arm re-check fires at
    episode_start + 60 + 1, re-enters the listener at step 5 and the fast
    run writes home — with NO periodic tick."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        rc.data = {"occupied": True}
        _evidence(rc, onset=T0, ev=T0, active=True)
        rc.refresh()
        assert coord._fast_path_arm_due[_entry_id(KIT)] == T0 + S(seconds=61)
        assert "zone_1" not in coord._fast_path_queued
        clk.t = T0 + S(seconds=61)
        _evidence(rc, onset=T0, ev=clk.t, active=True)
        sched.fire_all()
        assert "zone_1" in coord._fast_path_queued
        await _drain(hass)
        assert len(_writes(hass, ENT1, "home")) == 1
        d = _diag(coord, KIT)
        assert d["arm_class"] == "clean" and d["pending"] is False
        assert coord._last_fast_edge_to_write_s <= 45


@pytest.mark.asyncio
async def test_intermittent_pir_stay_arms_on_pulse_after_window(mods):
    """Pulses 0/50/85 (each joined within J=60): persists at the 85 s pulse
    (ev - start >= 60) and arms as `joined_transit`."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        rc.data = {"occupied": True}
        for onset_s, ev_s in ((0, 5), (50, 55)):
            clk.t = T0 + S(seconds=onset_s)
            _evidence(rc, onset=clk.t, ev=clk.t, active=True); rc.refresh()
            clk.t = T0 + S(seconds=ev_s)
            _evidence(rc, onset=T0 + S(seconds=onset_s), ev=clk.t, active=False); rc.refresh()
        assert "zone_1" not in coord._fast_path_queued
        clk.t = T0 + S(seconds=85)
        _evidence(rc, onset=clk.t, ev=clk.t, active=True); rc.refresh()
        assert "zone_1" in coord._fast_path_queued
        await _drain(hass)
        assert len(_writes(hass, ENT1, "home")) == 1
        d = _diag(coord, KIT)
        assert d["arm_class"] == "joined_transit"
        assert len(d["episode_onsets"]) == 3


# ==========================================================================
# Episodes (rows 50, 51, 66)
# ==========================================================================

def test_gap_longer_than_join_window_starts_new_episode(mods):
    """Row 51. Kitchen (hold 180, W 60 -> J 60): pulses 70 s apart are
    never joined; each is its own unpersisted episode."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0 + S(seconds=5), active=False)
        clk.t = T0 + S(seconds=6); _pass(coord)
        assert _diag(coord, KIT)["episode_start"] == T0.isoformat()
        clk.t = T0 + S(seconds=75)
        _evidence(rc, onset=clk.t, ev=clk.t + S(seconds=5), active=False)
        clk.t = T0 + S(seconds=81); _pass(coord)
        d = _diag(coord, KIT)
        assert d["episode_start"] == (T0 + S(seconds=75)).isoformat()
        assert len(d["episode_onsets"]) == 1
        assert d["pending"] is True and d["output"] is False
        assert coord.zone_manager.transit_filtered_today["zone_1"] == 1


def test_joined_transits_within_j_arm_and_are_classified(mods):
    """Row 66. Pulses 0-10 and 50-65 (gap 40 <= J): joined; ev 65 - start 0
    >= 60 -> persisted -> armed, classified `joined_transit`."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0 + S(seconds=10), active=False)
        clk.t = T0 + S(seconds=12); _pass(coord)
        _evidence(rc, onset=T0 + S(seconds=50), ev=T0 + S(seconds=65), active=False)
        clk.t = T0 + S(seconds=66); _pass(coord)
        d = _diag(coord, KIT)
        assert d["output"] is True and d["arm_class"] == "joined_transit"
        assert len(d["episode_onsets"]) == 2
        assert d["episode_active_s"] == 25.0
        assert coord.zone_manager.zones["zone_1"].any_room_hvac_occupied is True


def test_episode_lapses_at_ev_plus_j_and_counts_filtered(mods):
    """Row 50. onset 0, ev 10: live at ev + 60 (strict), lapsed at 71."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0 + S(seconds=10), active=False)
        clk.t = T0 + S(seconds=70); _pass(coord)
        assert _diag(coord, KIT)["pending"] is True
        assert coord.zone_manager.transit_filtered_today.get("zone_1", 0) == 0
        clk.t = T0 + S(seconds=71); _pass(coord)
        d = _diag(coord, KIT)
        assert d["pending"] is False and d["episode_start"] is None
        assert coord.zone_manager.transit_filtered_today["zone_1"] == 1
        assert coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms == []


def test_unarmed_episode_lifetime_below_w_plus_j(mods):
    """Closet (hold 60, W 60): pulses 0-10 and 50-55 stay unarmed and lapse
    at 55 + 60 = 115 (< W + J = 120)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk, rooms={"zone_1": [("cl", "closet", {"occupied": False})]},
        )
        rc = coords["cl"]
        _evidence(rc, onset=T0, ev=T0 + S(seconds=10), active=False)
        clk.t = T0 + S(seconds=11); _pass(coord)
        _evidence(rc, onset=T0 + S(seconds=50), ev=T0 + S(seconds=55), active=False)
        clk.t = T0 + S(seconds=115); _pass(coord)
        assert _diag(coord, "cl")["pending"] is True
        clk.t = T0 + S(seconds=116); _pass(coord)
        assert _diag(coord, "cl")["pending"] is False
        assert _diag(coord, "cl")["output"] is False


# ==========================================================================
# Pending hold (rows 59, 67, 69, 75, 76, 68, 58)
# ==========================================================================

def _pending_kitchen(coord, coords, clk):
    rc = coords[KIT]
    rc.data = {"occupied": True}
    _evidence(rc, onset=T0, ev=T0 + S(seconds=10), active=False)
    clk.t = T0 + S(seconds=20)
    _pass(coord)
    assert coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms == [KIT]


@pytest.mark.asyncio
async def test_pending_hold_blocks_both_directions(mods):
    """Rows 59/67. (a) zone away + pending Kitchen -> no home write. (b) zone
    Home in grace and empty with a stale `last_sent` away (misjudged edge):
    no vacancy away until the lapse, then away."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert _writes(hass, ENT1) == []
    with _Clock(T0) as clk, _pin_platform(mods):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        z = coord.zone_manager.zones["zone_1"]
        strat = mods["hvac_strategy"].strategy_for(hass, ENT1)
        strat._record_sent(ENT1, "set_preset_mode", "away")      # stale
        z.last_occupied_time = T0 - S(seconds=1000)              # past grace
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert _writes(hass, ENT1) == []                           # held
        clk.t = T0 + S(seconds=100)                                # lapsed
        _pass(coord)
        assert z.hvac_pending_arm_rooms == []
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "away")) == 1


@pytest.mark.asyncio
async def test_pending_hold_cleared_by_d5_shed(mods):
    """Row 69. Energy-shed force-away clears the pending hold (same path
    as the row-1 hold)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 - S(seconds=600))
        z = coord.zone_manager.zones["zone_1"]
        z.preset_mode = "home"
        _pending_kitchen(coord, coords, clk)
        z.runtime_exceeded = True
        coord._d5_enabled = True
        coord._energy_constraint_mode = "shed"
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "away")) == 1


@pytest.mark.asyncio
async def test_pending_hold_not_armed_for_house_away_transition(mods):
    """Row 69. Eligibility: with the house going `away` (target away) a
    stale pending list must not hold the away write."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        coord._house_state = "away"
        z = coord.zone_manager.zones["zone_1"]
        z.hvac_pending_arm_rooms = [KIT]                          # stale
        with patch.object(coord.zone_manager, "update_room_conditions"):
            await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "away")) == 1


@pytest.mark.asyncio
async def test_armed_room_with_pending_sibling_still_writes_home(mods):
    """Row 75 (REV 7 H1). Study persists and arms while the Kitchen is
    pending: fused not empty -> no hold -> home is written for the Study."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk,
            rooms={"zone_1": [(KIT, "common_area", {"occupied": True}),
                              ("study", "generic", {"occupied": True})]},
        )
        _evidence(coords[KIT], onset=T0, ev=T0 + S(seconds=10), active=False)
        _evidence(coords["study"], onset=T0 - S(seconds=70), ev=T0, active=True)
        clk.t = T0 + S(seconds=20)
        _pass(coord)
        z = coord.zone_manager.zones["zone_1"]
        assert z.hvac_pending_arm_rooms == [KIT]
        assert z.any_room_hvac_occupied is True
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "home")) == 1
        assert _rows(hass, mods, "preset_change_suppressed") == []


@pytest.mark.asyncio
async def test_pending_hold_row_latched_per_spell_and_relogged_after_drop(mods):
    """Row 76 (REV 7 L1). Two ticks in one spell -> one row; the spell drops
    (lapse); a new spell -> a second row."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets()
        clk.t = T0 + S(seconds=40); _pass(coord)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_rows(hass, mods, "preset_change_suppressed")) == 1
        clk.t = T0 + S(seconds=100); _pass(coord)                  # lapsed
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert "zone_1" not in coord._pending_hold_logged
        clk.t = T0 + S(seconds=200)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t + S(seconds=5), active=False)
        clk.t = T0 + S(seconds=210); _pass(coord)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_rows(hass, mods, "preset_change_suppressed")) == 2


def test_never_armed_episode_excluded_from_e_and_backfill(mods):
    """Row 68. A lapsed, never-armed Kitchen episode contributes nothing to
    E(Z) and never moves `last_occupied_time`."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        z = coord.zone_manager.zones["zone_1"]
        lot = z.last_occupied_time
        _pending_kitchen(coord, coords, clk)
        assert coord.zone_manager.room_release_at(KIT) is None
        assert coord.zone_manager.zone_release_at("zone_1") is None
        assert z.last_occupied_time == lot
        clk.t = T0 + S(seconds=400); _pass(coord)
        assert coord.zone_manager.room_release_at(KIT) is None
        assert z.last_occupied_time == lot


@pytest.mark.asyncio
async def test_zone3_repro_no_away_when_kitchen_enters_during_grace(mods):
    """Row 58 (zone 3 repro). Zone home; bedroom releases at 240; Kitchen
    entered at 510 (inside grace): last applied write is home -> D5 off ->
    the Kitchen arms at 510 and there is no away at 542."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [("bed", "bedroom", {"occupied": True}),
                                    (KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0 - S(seconds=3000))
        _evidence(coords["bed"], onset=T0 - S(seconds=100), ev=T0, active=False)
        _pass(coord)
        z = coord.zone_manager.zones["zone_1"]
        clk.t = T0 + S(seconds=300); _pass(coord)
        assert z.any_room_hvac_occupied is False
        assert z.last_occupied_time == T0 + S(seconds=240)
        clk.t = T0 + S(seconds=510)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass(coord)
        assert z.any_room_hvac_occupied is True
        assert z.hvac_pending_arm_rooms == []
        clk.t = T0 + S(seconds=542)
        await _tick(coord, hass)
        assert _writes(hass, ENT1, "away") == []


@pytest.mark.asyncio
async def test_unarmed_episode_blocks_vacancy_away(mods):
    """Row 59. Home zone, lot past grace, edge misjudged (stale last_sent):
    the pending Kitchen blocks the vacancy away; after the lapse it lands."""
    with _Clock(T0) as clk, _pin_platform(mods):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        mods["hvac_strategy"].strategy_for(hass, ENT1)._record_sent(ENT1, "set_preset_mode", "away")
        z = coord.zone_manager.zones["zone_1"]
        z.last_occupied_time = T0 - S(seconds=1000)
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert _writes(hass, ENT1) == []
        clk.t = T0 + S(seconds=100)
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "away")) == 1


@pytest.mark.asyncio
async def test_evidence_to_legacy_boundary_may_write_home_on_legacy_rule(mods):
    """REV 7 M2 (accepted boundary). Pending Kitchen in home_evening; at
    21:00 the house goes to home_night with the Kitchen lighting on: the
    legacy (shadow) rule arms on the lighting rising edge and writes home."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, house_state="home_evening")
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert _writes(hass, ENT1) == []
        coord._house_state = "home_night"
        clk.t = T0 + S(seconds=30)
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "home")) == 1


# ==========================================================================
# D5 scope (rows 58, 60, 61, 52, 57) + warm room + C2 + C3
# ==========================================================================

def test_d5_only_on_away_edge(mods):
    """Row 58. Last applied write home -> immediate arm; away -> pending."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["pending"] is True and _diag(coord, KIT)["output"] is False
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is True and _diag(coord, KIT)["cold"] is False


def test_pre_arrival_zone_bypasses_d5(mods):
    """Row 60."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._pre_arrival_zones.add("zone_1")
        _evidence(coords[KIT], onset=T0, ev=T0, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is True and _diag(coord, KIT)["pending"] is False


def test_away_edge_unknown_after_restart_fails_open(mods):
    """Row 61. No stamp and a registry miss -> away_edge False -> arm."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._zone_last_s1_write.pop("zone_1")
        mods["hvac_strategy"]._test_reset_cache()
        assert coord._zone_away_edge("zone_1") is False
        _evidence(coords[KIT], onset=T0, ev=T0, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is True


@pytest.mark.parametrize("hs,lighting", [
    ("sleep", False),        # night: the EVIDENCE term alone must arm (no D5)
    ("home_night", True),    # legacy: the shadow arms on the lighting edge
    ("guest", True),
])
def test_dwell_only_in_evidence_states(mods, hs, lighting):
    """Row 52. Night/legacy: no D5, no pending — the shadow / evidence OR
    decide immediately."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, house_state=hs)
        rc = coords[KIT]
        rc.data = {"occupied": lighting}
        _evidence(rc, onset=T0, ev=T0, active=True)
        _pass(coord)
        d = _diag(coord, KIT)
        assert d["output"] is True and d["pending"] is False
        assert coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms == []


def test_dwell_zero_is_rev3_behaviour(mods):
    """Row 57. Knob 47 = 0: the filter is off; an away-edge room arms at once."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, dwell=0)
        _evidence(coords[KIT], onset=T0, ev=T0, active=True)
        _pass(coord)
        d = _diag(coord, KIT)
        assert d["output"] is True and d["pending"] is False and d["episode_start"] is None


def test_dwell_15_boundary(mods):
    """Knob 47 = 15: W = 900 > hold 180 -> J = 180; a 200 s gap starts a new
    episode; 15 minutes of continuous evidence persists."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, dwell=15)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0, active=True)
        _pass(coord)
        assert coord.zone_manager.d5_join_window_s(KIT, 900.0) == 180.0
        clk.t = T0 + S(seconds=899); _evidence(rc, onset=T0, ev=clk.t, active=True); _pass(coord)
        assert _diag(coord, KIT)["pending"] is True
        clk.t = T0 + S(seconds=900); _evidence(rc, onset=T0, ev=clk.t, active=True); _pass(coord)
        assert _diag(coord, KIT)["output"] is True


def test_warm_room_no_dwell(mods):
    """A room whose output is already True is never filtered by new evidence."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0)
        _evidence(coords[KIT], onset=T0, ev=T0, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is True
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0)
        clk.t = T0 + S(seconds=30)
        _evidence(coords[KIT], onset=T0, ev=clk.t, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is True and _diag(coord, KIT)["cold"] is False


def test_d5_does_not_change_release(mods):
    """C2. With the filter on, release is still ev + hold (Kitchen 180)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0)
        rc = coords[KIT]
        _evidence(rc, onset=T0 - S(seconds=100), ev=T0, active=False)
        _pass(coord)
        assert coord.zone_manager.room_release_at(KIT) == T0 + S(seconds=180)


def test_hallway_never_arms_with_dwell(mods):
    """C3 (construction check). A hallway never pends and never arms."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk, rooms={"zone_1": [("hall", "hallway", {"occupied": True})]},
        )
        _evidence(coords["hall"], onset=T0, ev=T0, active=True)
        _pass(coord)
        z = coord.zone_manager.zones["zone_1"]
        assert z.any_room_hvac_occupied is False and z.hvac_pending_arm_rooms == []
        assert coord.zone_manager.d5_room_probe("hall", T0, 60.0, True) is None


# ==========================================================================
# Exemption (rows 47, 48, 49, 62, 72)
# ==========================================================================

def _arm_then_release(coord, coords, clk, room=KIT, span=100):
    """Arm `room` immediately (last write home), hold it `span` s, release
    it (evidence-state True -> False), then set the zone back to away."""
    coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", clk.t)
    rc = coords[room]
    _evidence(rc, onset=clk.t, ev=clk.t, active=True)
    _pass(coord)
    assert _diag(coord, room)["output"] is True
    clk.t = clk.t + S(seconds=span)
    _evidence(rc, onset=rc.onset, ev=clk.t, active=True)
    _pass(coord)
    clk.t = clk.t + S(seconds=181)                       # past hold 180
    _evidence(rc, onset=rc.onset, ev=rc.ev, active=False)
    _pass(coord)
    assert _diag(coord, room)["output"] is False
    coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", clk.t)
    coord._zone_vacancy_away_at["zone_1"] = clk.t


def test_same_room_return_rearms_immediately(mods):
    """Row 47. Release after a >= W arm -> a return within 900 s is exempt."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _arm_then_release(coord, coords, clk)
        assert _diag(coord, KIT)["released_at"] == clk.t.isoformat()
        clk.t = clk.t + S(seconds=300)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass(coord)
        d = _diag(coord, KIT)
        assert d["output"] is True and d["exempt_reason"] == "same_room_return"


def test_exemption_renews_on_each_release(mods):
    """Row 62."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _arm_then_release(coord, coords, clk)
        first = _diag(coord, KIT)["released_at"]
        clk.t = clk.t + S(seconds=100)
        _arm_then_release(coord, coords, clk)
        second = _diag(coord, KIT)["released_at"]
        assert second > first and second == clk.t.isoformat()


def test_exemption_not_renewed_by_ghost_blip_chain(mods):
    """Row 72. An exempt re-arm that lasts < W does NOT renew the anchor;
    once the original anchor ages past 900 s the room is cold again."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _arm_then_release(coord, coords, clk)
        anchor = _diag(coord, KIT)["released_at"]
        rc = coords[KIT]
        # Ghost blip 400 s later: exempt re-arm, 10 s long.
        clk.t = clk.t + S(seconds=400)
        _evidence(rc, onset=clk.t, ev=clk.t, active=True); _pass(coord)
        assert _diag(coord, KIT)["output"] is True
        clk.t = clk.t + S(seconds=10)
        _evidence(rc, onset=rc.onset, ev=clk.t, active=False); _pass(coord)
        clk.t = clk.t + S(seconds=181)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is False
        assert _diag(coord, KIT)["released_at"] == anchor        # not renewed
        # 901 s after the ORIGINAL anchor: cold again.
        clk.t = datetime.fromisoformat(anchor) + S(seconds=901)
        _evidence(rc, onset=clk.t, ev=clk.t, active=True); _pass(coord)
        assert _diag(coord, KIT)["cold"] is True and _diag(coord, KIT)["pending"] is True


def test_other_room_in_away_zone_waits_w(mods):
    """Row 48. The Kitchen is exempt; the Dining room (other room) is cold."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk,
            rooms={"zone_1": [(KIT, "common_area", {"occupied": False}),
                              (DIN, "common_area", {"occupied": False})]},
        )
        _arm_then_release(coord, coords, clk)
        clk.t = clk.t + S(seconds=100)
        _evidence(coords[DIN], onset=clk.t, ev=clk.t, active=True)
        _pass(coord)
        assert _diag(coord, DIN)["pending"] is True and _diag(coord, DIN)["output"] is False
        assert _diag(coord, DIN)["exempt_reason"] is None


def test_rearm_after_window_is_cold(mods):
    """Row 49. 901 s after the release the room is cold."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _arm_then_release(coord, coords, clk)
        clk.t = clk.t + S(seconds=901)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["cold"] is True and _diag(coord, KIT)["output"] is False


# ==========================================================================
# Alarm (rows 63, 73) + stamps (64, 71) + ledger / trigger (74, 78)
# ==========================================================================

@pytest.mark.asyncio
async def test_exempt_rearm_counted_once_in_quick_return_alarm(mods):
    """Row 63. An exempt fast_entry after a vacancy away counts (same-room);
    a second fast_entry on the same away does not."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, vacancy_away_age=100)
        _arm_then_release(coord, coords, clk)                   # exempt anchor
        away_at = coord._zone_vacancy_away_at["zone_1"]
        clk.t = clk.t + S(seconds=60)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t, exempt_reason="same_room_return")
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t)
        assert coord._quick_returns_today_view() == {"zone_1": 1}
        assert coord._fp_same_room_returns_today == {"zone_1": 1}
        assert coord._zone_vacancy_away_counted["zone_1"] == away_at


@pytest.mark.asyncio
async def test_quick_return_alarm_per_zone_and_sums(mods):
    """Row 73. Counters are per zone; quick = same + other."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods)
        z1 = coord.zone_manager.zones["zone_1"]; z2 = coord.zone_manager.zones["zone_2"]
        coord._zone_vacancy_away_at["zone_1"] = clk.t - S(seconds=10)
        coord._zone_vacancy_away_at["zone_2"] = clk.t - S(seconds=10)
        coord._note_quick_return("zone_1", z1, clk.t, exempt=True)
        coord._note_quick_return("zone_2", z2, clk.t, exempt=False)
        coord._zone_vacancy_away_at["zone_2"] = clk.t - S(seconds=5)
        coord._note_quick_return("zone_2", z2, clk.t, exempt=True)
        a = coord.get_mode_attrs()
        assert a["quick_returns_today"] == {"zone_1": 1, "zone_2": 2}
        assert a["same_room_returns_today"] == {"zone_1": 1, "zone_2": 1}
        assert a["other_room_returns_today"] == {"zone_2": 1}


@pytest.mark.asyncio
async def test_quick_return_nm_text_uses_constant(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods)
        nm = hass.data[mods["const"].DOMAIN]["notification_manager"]
        z1 = coord.zone_manager.zones["zone_1"]
        with patch.object(mods["hvac"], "HVAC_QUICK_RETURN_WINDOW_S", 600), \
             patch.object(mods["hvac"], "HVAC_QUICK_RETURN_NM_PER_DAY", 1):
            coord._zone_vacancy_away_at["zone_1"] = clk.t - S(seconds=10)
            coord._note_quick_return("zone_1", z1, clk.t)
        await _drain(hass)
        assert "within 10 minutes 1 times today" in nm.notes[0]["message"]


@pytest.mark.asyncio
async def test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace(mods):
    """Row 64. A house-state away write does not stamp the alarm anchor; a
    vacancy away does."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, house_state="away",
            rooms={"zone_1": [(KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "away", "zone_3": "away"},
        )
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "away")) == 1
        assert "zone_1" not in coord._zone_vacancy_away_at
        assert coord._zone_last_away_reason["zone_1"] == "house_state_transition"
        assert coord._zone_last_s1_write["zone_1"][:2] == ("away", "house_state_transition")
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord.zone_manager.zones["zone_1"].last_occupied_time = T0 - S(seconds=1000)
        await _tick(coord, hass)
        assert coord._zone_vacancy_away_at["zone_1"] == T0


@pytest.mark.asyncio
async def test_zone_last_s1_write_stamped_only_on_applied(mods):
    """Row 71. SKIPPED_ALREADY_CORRECT and a deferred write leave no stamp;
    an APPLIED write stamps `(preset, reason, ts)`."""
    with _Clock(T0) as clk, _pin_platform(mods):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        # (1) no-op: the zone's stored preset says `away` (S1 attempts the
        # write) but the strategy last SENT `home` and the entity OBSERVES
        # `home` -> SKIPPED_ALREADY_CORRECT, zero wire calls, NO stamp.
        mods["hvac_strategy"].strategy_for(hass, ENT1)._record_sent(ENT1, "set_preset_mode", "home")
        coord.zone_manager.zones["zone_1"].preset_mode = "away"
        await _tick(coord, hass)
        assert _writes(hass, ENT1) == []
        assert "zone_1" not in coord._zone_last_s1_write
        coord.zone_manager.zones["zone_1"].preset_mode = "home"
        # (2) deferred: manual zone under a live borrow (gate e)
        z = coord.zone_manager.zones["zone_1"]
        z.preset_mode = "manual"
        H.set_climate(hass, ENT1, preset_mode="manual", hold_activity="manual")
        coord._override_arrester._nudge_in_flight.add("zone_1")
        await _tick(coord, hass)
        assert "zone_1" not in coord._zone_last_s1_write
        # (3) applied
        coord._override_arrester._nudge_in_flight.discard("zone_1")
        z.preset_mode = "away"
        H.set_climate(hass, ENT1, preset_mode="away", hold_activity="away")
        await _tick(coord, hass)
        assert coord._zone_last_s1_write["zone_1"][0] == "home"
        assert coord._zone_last_s1_write["zone_1"][1] == "house_state_transition"
        assert coord._zone_last_s1_write["zone_1"][2] == T0


@pytest.mark.asyncio
async def test_trigger_threads_async_decision_cycle_to_run_to_apply(mods):
    """Rows 74/78 (REV 7 L3). `_async_decision_cycle(trigger=...)` reaches
    `_apply_house_state_presets`; the timer / setup default is `periodic`;
    the house-state and pre-arrival handlers pass their names."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods)
        seen = []

        async def _apply(**kw):
            seen.append(kw.get("trigger"))
            return False
        heavy = [
            patch.object(coord.zone_manager, "update_all_zones"),
            patch.object(coord.zone_manager, "update_room_conditions"),
            patch.object(coord, "_drain_hvac_degraded_room_events", new=AsyncMock()),
            patch.object(coord, "_check_carrier_freshness", new=AsyncMock()),
            patch.object(coord._egress_manager, "async_tick", new=AsyncMock()),
            patch.object(coord, "_apply_house_state_presets", side_effect=_apply),
            patch.object(coord._override_arrester, "check_ac_reset", new=AsyncMock()),
            patch.object(coord._fan_controller, "update", new=AsyncMock()),
            patch.object(coord._cover_controller, "update", new=AsyncMock()),
            patch.object(coord._predictor, "update", new=AsyncMock()),
            patch.object(coord, "_record_anomaly_observations", new=AsyncMock()),
            patch.object(coord, "async_save_zone_state", new=AsyncMock()),
            patch.object(coord, "_emit_and_reset_short_cycles", new=AsyncMock()),
        ]
        for p in heavy:
            p.start()
        try:
            coord._startup_audit_done = True
            await coord._async_decision_cycle(T0)                 # timer: positional now
            clk.advance(1)
            await coord._async_decision_cycle(trigger="house_state")
            clk.advance(1)
            await coord._async_decision_cycle(trigger="pre_arrival")
            assert seen == ["periodic", "house_state", "pre_arrival"]
        finally:
            for p in heavy:
                p.stop()
        # The handlers themselves pass their names.
        calls = []

        async def _spy(_now=None, *, trigger="periodic"):
            calls.append(trigger)
        with patch.object(coord, "_async_decision_cycle", side_effect=_spy), \
             patch.object(coord._override_arrester, "sunset_immune_holds"), \
             patch.object(coord._override_arrester, "sunset_temp_arrester_override"):
            coord._handle_house_state_changed({"new_state": "home_evening", "old_state": "home_day"})
            await _drain(hass)
        assert calls == ["house_state"]


@pytest.mark.asyncio
async def test_preset_change_row_carries_established_and_last_away_reason(mods):
    """Row 74. A home write after a vacancy away carries
    `last_away_reason == vacant_past_grace`, `established True`."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord.zone_manager.zones["zone_1"].last_occupied_time = T0 - S(seconds=1000)
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "away")) == 1
        coord.zone_manager.zones["zone_1"].preset_mode = "away"
        H.set_climate(hass, ENT1, preset_mode="away", hold_activity="away")
        clk.t = T0 + S(seconds=30)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        await _tick(coord, hass)
        rows = _rows(hass, mods, "preset_change")
        assert rows[-1]["details"]["new_preset"] == "home"
        assert rows[-1]["details"]["last_away_reason"] == "vacant_past_grace"
        assert rows[-1]["details"]["established"] is True
        assert rows[-1]["details"]["trigger"] == "periodic"
        assert rows[0]["details"]["last_away_reason"] is None


# ==========================================================================
# Exit timer with a pending room (rows 70, 77) + exit run (54)
# ==========================================================================

def test_exit_timer_reschedules_to_pending_lapse_without_consuming_key(mods):
    """Rows 70/77 (REV 7 L2). The zone is home with a released bedroom and a
    pending Kitchen; when the exit timer comes due it reschedules to
    `ev(kitchen) + J + SLACK` (never exactly ev + J) and the key stays
    unconsumed."""
    with _Clock(T0) as clk, _pin_platform(mods):
        coord, hass, coords, sched = _setup(
            mods, grace=5, rooms={"zone_1": [("bed", "bedroom", {"occupied": False}),
                                             (KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        _evidence(coords["bed"], onset=T0 - S(seconds=100), ev=T0 - S(seconds=100), active=False)
        _pass(coord)
        rel = T0 - S(seconds=100) + S(seconds=240)
        coord._schedule_exit_timer("zone_1")
        assert coord._fast_path_exit_due["zone_1"] == rel + S(seconds=302)
        # An away is applied by another path (no reschedule yet) and the
        # Kitchen goes pending on the resulting away edge: onset 400, ev 410.
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 + S(seconds=300))
        _evidence(coords[KIT], onset=T0 + S(seconds=400), ev=T0 + S(seconds=410), active=False)
        clk.t = rel + S(seconds=302)
        _pass(coord)
        assert coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms == [KIT]
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0
        assert "zone_1" not in coord._fp_exit_fired
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=410 + 60 + 2)
        assert coord._fast_path_exit_due["zone_1"] > T0 + S(seconds=410 + 60)


@pytest.mark.asyncio
async def test_exit_run_arms_persisted_room_before_away(mods):
    """Row 54. A fast_exit run's producer pass arms a room whose episode
    has persisted -> no away is written."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        z = coord.zone_manager.zones["zone_1"]
        z.preset_mode = "home"
        H.set_climate(hass, ENT1, preset_mode="home", hold_activity="home")
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 - S(seconds=600))
        z.last_occupied_time = T0 - S(seconds=1000)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0 + S(seconds=70), active=True)
        clk.t = T0 + S(seconds=71)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_exit")
        await _drain(hass)
        assert z.any_room_hvac_occupied is True
        assert _writes(hass, ENT1, "away") == []


@pytest.mark.asyncio
async def test_lighting_session_dwell_removed(mods):
    """Row 53 (behavioural). Knob 1, home_night (legacy), a 20 s-old lighting
    session, shadow armed -> S1 writes home (the retired lighting-session
    skip would have `continue`d)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, house_state="home_night",
            rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        _pass(coord)
        z = coord.zone_manager.zones["zone_1"]
        z.current_session_start = clk.t - S(seconds=20)
        assert z.any_room_hvac_occupied is True
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "home")) == 1


# ==========================================================================
# Arm re-check timer (rows 46, 55a-e, 65)
# ==========================================================================

def test_arm_recheck_scheduled_at_onset_plus_w(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _evidence(coords[KIT], onset=T0, ev=T0, active=True)
        coords[KIT].refresh()
        assert coord._fast_path_arm_due[_entry_id(KIT)] == T0 + S(seconds=61)
        assert sched.live()[0][0] == 61.0


def test_arm_recheck_reenters_at_step_5(mods):
    """Row 65. The re-check never queues directly: it re-enters
    `_on_room_refresh(from_step=5)`, which queues."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0, active=True); rc.refresh()
        clk.t = T0 + S(seconds=61)
        _evidence(rc, onset=T0, ev=clk.t, active=True)
        with patch.object(coord, "_on_room_refresh", wraps=coord._on_room_refresh) as spy, \
             _captured(hass) as tt:
            sched.fire_all()
            assert spy.call_args.kwargs == {"from_step": 5}
            assert tt.call_count == 1
            assert tt.coros[0].__name__ == "_async_zone_fast_run"


def test_arm_recheck_into_warm_zone_stops_at_gate(mods):
    """Row 65. If the zone became fused-occupied meanwhile, step 5 stops it."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk,
            rooms={"zone_1": [(KIT, "common_area", {"occupied": False}),
                              ("study", "generic", {"occupied": False})]},
        )
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0, active=True); rc.refresh()
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0)
        _evidence(coords["study"], onset=T0, ev=T0, active=True)
        _pass(coord)                                             # study armed -> warm
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0)
        clk.t = T0 + S(seconds=61)
        _evidence(rc, onset=T0, ev=clk.t, active=True)
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0


def test_arm_recheck_kill_switch_off_no_run(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0, active=True); rc.refresh()
        coord._fast_path_enabled = False
        clk.t = T0 + S(seconds=61)
        _evidence(rc, onset=T0, ev=clk.t, active=True)
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0


def test_arm_recheck_after_house_state_exit_runs_without_d5(mods):
    """The house left the evidence states before the re-check fired: the
    callback re-enters at step 5 (gates decide) — no D5, and the zone-cold
    gate lets the run queue."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        _evidence(rc, onset=T0, ev=T0, active=True); rc.refresh()
        coord._house_state = "home_night"
        clk.t = T0 + S(seconds=61)
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 1


@pytest.mark.parametrize("how", ["lapse", "arm", "prune", "unload", "teardown"])
def test_arm_recheck_cancelled_on(mods, how):
    """Rows 55a-e."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        eid = _entry_id(KIT)
        _evidence(rc, onset=T0, ev=T0 + S(seconds=5), active=False); rc.refresh()
        assert eid in coord._fast_path_arm_unsubs and len(sched.live()) == 1
        if how == "lapse":
            clk.t = T0 + S(seconds=100)                           # ev + J passed
            sched.fire_all()                                      # re-check sees the lapse
        elif how == "arm":
            clk.t = T0 + S(seconds=70)
            _evidence(rc, onset=T0, ev=clk.t, active=True)
            with _captured(hass):
                rc.refresh()
        elif how == "prune":
            coord._handle_zm_zones_updated({"deleted_zone_id": "zone_1", "deleted_zone_name": "Zone 1"})
        elif how == "unload":
            coord._on_room_lifecycle(eid, KIT, "unloaded")
        elif how == "teardown":
            coord._tearing_down = True
            coord._teardown_fast_path()
        assert eid not in coord._fast_path_arm_unsubs
        assert sched.live() == []


def test_transit_helper_text_matches_constant(mods):
    """The knob 47 helper states the exemption window in minutes; the number
    is HVAC_TRANSIT_EXEMPT_WINDOW_S / 60 (Bug Class #63 guard)."""
    from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
        HVAC_TRANSIT_EXEMPT_WINDOW_S,
    )
    base = Path(H._REAL_URA_PATH)
    for fn in ("strings.json", "translations/en.json"):
        data = json.loads((base / fn).read_text(encoding="utf-8"))
        text = json.dumps(data)
        assert f"within {HVAC_TRANSIT_EXEMPT_WINDOW_S // 60} minutes counts at once" in text, fn
        assert "Entry wait (minutes)" in text, fn
