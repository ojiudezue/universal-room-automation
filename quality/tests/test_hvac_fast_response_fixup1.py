"""HVAC fast occupancy response (v5.103.20) — fix-up round 1 anchors.

Operator rulings (plan §0.6 R4-R8): (1) pending-hold CAP
`HVAC_PENDING_HOLD_CAP_S` = 600 with a `pending_hold_capped` ledger row;
(2) the same-room return window is knob 52 "Return Window (min)" (live,
0 = off); (3) per-room "Skip entry wait"; (4) fast entry in ALL house
states (outcome unchanged, arrives faster); (D-M2 overruled) the shadow
night tail is NOT carried across a night -> evidence crossing.

Review must-fixes: A-MED1 (ceiling counts fast triggers only), A-MED2
(buckets cleared on trip start/end), A-MED3 (per-room entity attrs never
contradict on/off), D-M1 (a disabled / deleted / retyped room can neither
pend nor hold), D-M3 (`_zone_vacancy_away_at` only on a REAL transition),
B-M3 (zone-filtered pass keeps other zones' absent set / classification),
Review C 1-5, C LOW anchors, A-LOW-5, B-L1, B-L3, D-L2.

Reuses the D2/D5 harness (real HVACCoordinator on the smoke StubHass, real
room-config entries, fake room coordinators, hand-fired scheduler, patched
clock). Oracles are literals: W = 60 s, kitchen hold 180 -> J = 60, cap
600 s, ceiling 6/h, bedroom hold 240, grace 5 min -> exit at release + 302.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402
from test_hvac_fast_occupancy_response import (  # noqa: E402
    S, T0, _Clock, _captured, _drain, _entry_id, _pin_platform, _setup, _writes,
)
from test_hvac_transit_filter import (  # noqa: E402
    DIN, ENT1, KIT, _arm_then_release, _away_zone, _diag, _evidence, _pass,
    _pending_kitchen, _rows, _tick, _use_rc_with_onset,  # noqa: F401 (autouse fixture)
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


def _pass_rw(coord, house_state=None):
    """A producer pass threading the LIVE Return Window (knob 52) exactly
    as the fast run and the full cycle do."""
    hs = house_state or coord._house_state
    coord.zone_manager.update_room_conditions(
        house_state=hs, entry_dwell_s=float(coord._zone_entry_dwell) * 60.0,
        away_edge_fn=coord._zone_away_edge,
        return_window_s=coord._return_window_s(),
    )


def _entry_of(hass, room):
    return next(e for e in hass.config_entries._entries if e.entry_id == _entry_id(room))


def _heavy(coord):
    """Patches that keep a REAL `_run_decision_cycle` cheap; the producer
    (`update_room_conditions`) and the exit-timer loop stay real."""
    return [
        patch.object(coord.zone_manager, "update_all_zones"),
        patch.object(coord, "_drain_hvac_degraded_room_events", new=AsyncMock()),
        patch.object(coord, "_check_carrier_freshness", new=AsyncMock()),
        patch.object(coord._egress_manager, "async_tick", new=AsyncMock()),
        patch.object(coord, "_apply_house_state_presets", new=AsyncMock(return_value=False)),
        patch.object(coord._override_arrester, "check_ac_reset", new=AsyncMock()),
        patch.object(coord._fan_controller, "update", new=AsyncMock()),
        patch.object(coord._cover_controller, "update", new=AsyncMock()),
        patch.object(coord._predictor, "update", new=AsyncMock()),
        patch.object(coord, "_record_anomaly_observations", new=AsyncMock()),
        patch.object(coord, "async_save_zone_state", new=AsyncMock()),
        patch.object(coord, "_emit_and_reset_short_cycles", new=AsyncMock()),
    ]


# ==========================================================================
# Ruling 1 — pending-hold cap (HVAC_PENDING_HOLD_CAP_S = 600)
# ==========================================================================

@pytest.mark.asyncio
async def test_pending_hold_cap_lifts_hold_after_600s_and_logs_once(mods):
    """A zone held ONLY by never-persisting Kitchen episodes (a fresh 10 s
    pulse every 100 s; each lapses before the next) stays held for 600 s of
    spell; the first tick past the cap lets the vacancy away through and
    writes ONE `pending_hold_capped` row for the spell."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 1
        z = coord.zone_manager.zones["zone_1"]
        z.last_occupied_time = T0 - S(seconds=1000)                    # past grace
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 - S(seconds=600))
        rc = coords[KIT]
        for k in range(0, 9):
            clk.t = T0 + S(seconds=100 * k)
            _evidence(rc, onset=clk.t - S(seconds=15), ev=clk.t - S(seconds=5), active=False)
            _pass(coord)
            assert z.hvac_pending_arm_rooms == [KIT], k
            await coord._apply_house_state_presets()
            await _drain(hass)
            if k <= 6:                                                  # spell 0..600 s: held
                assert _writes(hass, ENT1, "away") == [], k
                assert _rows(hass, mods, "pending_hold_capped") == [], k
                assert z.pending_hold_since == T0
            else:                                                       # > 600 s: capped
                assert len(_writes(hass, ENT1, "away")) == 1, k
                rows = _rows(hass, mods, "pending_hold_capped")
                assert len(rows) == 1, k
                assert rows[0]["zone"] == "zone_1"
                assert rows[0]["details"]["cap_s"] == 600
                assert rows[0]["details"]["held_s"] == 700
                assert rows[0]["details"]["pending_rooms"] == [KIT]
                assert "zone_1" in coord._pending_hold_cap_logged
            if k == 7:
                # The away is now the zone's last applied write.
                assert coord._zone_last_s1_write["zone_1"][:2] == ("away", "vacant_past_grace")
                z.preset_mode = "away"
                H.set_climate(hass, ENT1, preset_mode="away", hold_activity="away")


@pytest.mark.asyncio
async def test_pending_hold_cap_latch_clears_when_spell_ends(mods):
    """Spell ends (lapse, no pending) -> the cap latch is discarded so a
    later over-long spell logs its own row."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._pending_hold_cap_logged.add("zone_1")
        z = coord.zone_manager.zones["zone_1"]
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets()
        assert "zone_1" in coord._pending_hold_cap_logged                # spell alive: kept
        clk.t = T0 + S(seconds=200); _pass(coord)                        # lapsed
        assert z.hvac_pending_arm_rooms == []
        await coord._apply_house_state_presets()
        assert "zone_1" not in coord._pending_hold_cap_logged
        assert z.pending_hold_since is None


# ==========================================================================
# Ruling 2 — Return Window is knob 52 (live; 0 = off)
# ==========================================================================

@pytest.mark.parametrize("minutes,ret_after_s,expect_exempt", [
    (10, 400, True),      # default: 400 s < 600 s
    (10, 601, False),     # default: 601 s > 600 s -> cold
    (5, 200, True),       # 200 s < 300 s
    (5, 400, False),      # 400 s > 300 s -> cold
    (0, 1, False),        # 0 = exemption OFF: even 1 s later is cold
    (0, 0, False),        # 0 = OFF even at the release instant itself (delta 0)
])
def test_return_window_knob_live_value_drives_exemption(mods, minutes, ret_after_s, expect_exempt):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._return_window_minutes = minutes
        _arm_then_release(coord, coords, clk)
        released = datetime.fromisoformat(_diag(coord, KIT)["released_at"])
        clk.t = released + S(seconds=ret_after_s)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass_rw(coord)
        d = _diag(coord, KIT)
        if expect_exempt:
            assert d["output"] is True and d["exempt_reason"] == "same_room_return"
        else:
            assert d["cold"] is True and d["pending"] is True and d["output"] is False
            assert d["exempt_reason"] is None


def test_return_window_seconds_helper(mods):
    coord, hass, coords, sched = _setup(mods)
    assert coord._return_window_s() == 600.0                             # default 10
    coord._return_window_minutes = 0
    assert coord._return_window_s() == 0.0
    coord._return_window_minutes = 60
    assert coord._return_window_s() == 3600.0
    coord._return_window_minutes = "bad"
    assert coord._return_window_s() == 600.0                             # malformed -> default


@pytest.mark.asyncio
async def test_fast_run_threads_live_return_window_to_producer(mods):
    """The producer's fallback is the LAST threaded value; the fast run must
    thread the CURRENT knob. Earlier passes ran at the default (900 s); the
    knob is then set to 0 and a same-room return is driven through the fast
    run -> cold (a run that dropped the kwarg would re-use 900 -> exempt)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _arm_then_release(coord, coords, clk)                            # passes at 600 s
        assert coord.zone_manager._last_return_window_s == 600.0
        coord._return_window_minutes = 0
        clk.t = clk.t + S(seconds=60)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t)
        assert coord.zone_manager._last_return_window_s == 0.0
        assert _diag(coord, KIT)["cold"] is True and _diag(coord, KIT)["output"] is False


def test_return_window_number_entity_identity(mods):
    from custom_components.universal_room_automation import number as number_mod
    coord, hass, coords, _ = _setup(mods)
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": coord})
    entry = hass.config_entries._entries[0]
    entry.options = {}
    n = number_mod.ReturnWindowMinutesNumber(hass, entry)
    assert n.name == "52 · Return Window (min)"
    assert n.unique_id == f"{mods['const'].DOMAIN}_hvac_return_window_minutes"
    assert (n.native_min_value, n.native_max_value, n.native_step) == (0, 60, 1)
    assert n.native_value == 10                                          # default
    entry.options = {"hvac_return_window_minutes": 3}
    assert number_mod.ReturnWindowMinutesNumber(hass, entry).native_value == 3


# ==========================================================================
# Ruling 3 — per-room "Skip entry wait"
# ==========================================================================

def test_skip_entry_wait_room_arms_at_once_other_room_waits(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk,
            rooms={"zone_1": [(KIT, "common_area", {"occupied": False}),
                              (DIN, "common_area", {"occupied": False})]},
        )
        _entry_of(hass, KIT).options = {"hvac_skip_entry_wait": True}
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _evidence(coords[DIN], onset=clk.t, ev=clk.t, active=True)
        _pass(coord)
        k, d = _diag(coord, KIT), _diag(coord, DIN)
        assert k["output"] is True and k["cold"] is False and k["exempt_reason"] == "skip_entry_wait"
        assert d["output"] is False and d["cold"] is True and d["pending"] is True
        assert coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms == [DIN]


def test_skip_entry_wait_is_read_live_from_entry_options(mods):
    """Consumer proof for the reload-suppression allowlist: the producer
    merges `entry.options` on EVERY pass, so a toggle takes effect on the
    next pass with no reload (window 0 so the return exemption cannot mask
    the cold path)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord._return_window_minutes = 0
        e = _entry_of(hass, KIT)
        e.options = {"hvac_skip_entry_wait": True}
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass_rw(coord)
        assert _diag(coord, KIT)["output"] is True
        # Release (hold 180) and mark the zone away again.
        clk.t = clk.t + S(seconds=100)
        _evidence(coords[KIT], onset=coords[KIT].onset, ev=clk.t, active=False)
        clk.t = clk.t + S(seconds=181); _pass_rw(coord)
        assert _diag(coord, KIT)["output"] is False
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", clk.t)
        e.options = {"hvac_skip_entry_wait": False}                       # toggled, no reload
        clk.t = clk.t + S(seconds=10)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass_rw(coord)
        assert _diag(coord, KIT)["cold"] is True and _diag(coord, KIT)["output"] is False


def test_skip_entry_wait_listener_probe_queues_fast_entry_at_once(mods):
    """The listener's D5 probe honours the option: a skip room's first
    evidence queues `fast_entry` immediately (a plain room schedules the arm
    re-check and queues nothing)."""
    for skip, expect_runs in ((True, 1), (False, 0)):
        with _Clock(T0) as clk:
            coord, hass, coords, sched = _away_zone(mods, clk)
            _entry_of(hass, KIT).options = {"hvac_skip_entry_wait": skip}
            _pass(coord)                                                 # meta snapshot
            _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
            with _captured(hass) as tt:
                coords[KIT].refresh()
                assert tt.call_count == expect_runs, skip
            assert (len(sched.live()) == 0) is skip


# ==========================================================================
# Ruling 4 — fast entry in ALL house states (outcome unchanged, sooner)
# ==========================================================================

@pytest.mark.parametrize("hs", [
    "home_day", "home_evening", "home_night", "sleep", "waking", "guest", "arriving", "away",
])
def test_fast_entry_queues_in_every_house_state(mods, hs):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, house_state=hs,
            rooms={"zone_1": [(KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "away", "zone_2": "away", "zone_3": "away"},
        )
        coord._zone_last_s1_write["zone_1"] = ("away", "house_state_transition", T0 - S(seconds=600))
        _pass(coord)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        with _captured(hass) as tt:
            coords[KIT].refresh()
            assert tt.call_count == 1, hs
            assert tt.coros[0].__name__ == "_async_zone_fast_run"


# ==========================================================================
# D-M2 (overruled) — the night tail is NOT carried across sleep -> home_day
# ==========================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("night_state", ["sleep", "waking"])
async def test_night_tail_not_carried_across_crossing_jaya_repro(mods, night_state):
    """D's repro: Jaya's radar loses her at 06:40 (house asleep); house_day at
    07:00. The shadow's 30-minute night tail would still be armed (until
    ~07:11); the evidence rule releases at 06:40 + 240 s = 06:44, the zone's
    empty-since is back-filled to 06:44 and the 07:00 tick writes away
    (grace 5 min ran out at 06:49)."""
    from homeassistant.util import dt as real_dt
    t0630 = real_dt.as_utc(datetime(2026, 9, 28, 6, 30, tzinfo=real_dt.DEFAULT_TIME_ZONE))
    with _Clock(t0630) as clk:
        coord, hass, coords, sched = _setup(
            mods, house_state=night_state,
            rooms={"zone_1": [("jaya", "bedroom", {"occupied": True})]},
            presets={"zone_1": "sleep", "zone_2": "sleep", "zone_3": "sleep"},
        )
        rc = coords["jaya"]
        _evidence(rc, onset=t0630, ev=t0630, active=True)
        _pass(coord, night_state)
        assert _diag(coord, "jaya")["output"] is True
        t0640 = t0630 + S(minutes=10)
        clk.t = t0640 + S(seconds=60)                                    # 06:41
        rc.data = {"occupied": False}
        _evidence(rc, onset=t0630, ev=t0640, active=False)
        _pass(coord, night_state)
        assert _diag(coord, "jaya")["output"] is True                    # night: shadow tail
        t0700 = t0630 + S(minutes=30)
        clk.t = t0700
        coord._house_state = "home_day"
        _pass(coord, "home_day")
        d = _diag(coord, "jaya")
        assert d["rule"] == "evidence" and d["output"] is False
        assert d["armed"] is True                                        # the SHADOW still holds
        assert datetime.fromisoformat(d["tail_expires_at"]) > t0700       # ... until ~07:11
        z = coord.zone_manager.zones["zone_1"]
        assert z.any_room_hvac_occupied is False
        assert z.last_occupied_time == t0640 + S(seconds=240)             # 06:44 back-fill
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "away")) == 1
        assert coord._zone_last_s1_write["zone_1"][1] == "vacant_past_grace"


# ==========================================================================
# A-MED1 — the write ceiling counts FAST triggers only
# ==========================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("trigger,counted", [
    ("house_state", 0), ("pre_arrival", 0), ("periodic", 0), ("fast_entry", 1), ("fast_exit", 1),
])
async def test_write_ceiling_counts_only_fast_triggers(mods, trigger, counted):
    with _Clock(T0):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        _pass(coord)
        await coord._apply_house_state_presets(trigger=trigger)
        await _drain(hass)
        assert len(_writes(hass, ENT1, "home")) == 1
        assert coord._fast_writes_today.value == counted
        assert len(coord._fp_writes_bucket.get("zone_1", [])) == counted


# ==========================================================================
# A-MED2 — buckets cleared on trip start and on trip end (across midnight)
# ==========================================================================

def test_trip_clears_buckets_on_start_and_on_midnight_expiry(mods):
    from homeassistant.util import dt as real_dt
    midnight = real_dt.as_utc(datetime(2026, 9, 29, 0, 0, tzinfo=real_dt.DEFAULT_TIME_ZONE))
    with _Clock(midnight - S(minutes=10)) as clk:
        coord, hass, coords, sched = _setup(mods, presets={"zone_1": "home"})
        coord._fp_runs_bucket["zone_1"] = __import__("collections").deque([clk.t])
        for _ in range(7):                                               # 7 > 6 -> trip
            coord._note_fast_write("zone_1", clk.t, None)
            clk.advance(30)
        assert coord._fast_path_zone_tripped("zone_1") is True
        # Trip START: the breach is not carried.
        assert "zone_1" not in coord._fp_writes_bucket
        assert "zone_1" not in coord._fp_runs_bucket
        # Writes while tripped still land in the bucket (tick-only writes
        # are not fast, but the counter path is exercised here on purpose).
        for _ in range(7):
            coord._note_fast_write("zone_1", clk.t, None)
            clk.advance(30)
        assert len(coord._fp_writes_bucket["zone_1"]) == 7
        # Trip END at local midnight: fresh hour.
        clk.t = midnight
        assert coord._fast_path_zone_tripped("zone_1") is False
        assert "zone_1" not in coord._fp_writes_bucket
        coord._note_fast_write("zone_1", clk.t + S(seconds=60), None)
        assert coord._fast_path_zone_tripped("zone_1") is False           # 1, not 8
        assert len(coord._fp_writes_bucket["zone_1"]) == 1


# ==========================================================================
# A-MED3 — per-room entity attrs follow the ACTIVE rule
# ==========================================================================

def _room_attrs(mods, coord, room):
    from custom_components.universal_room_automation import binary_sensor as bs
    entry = SimpleNamespace(data={"room_name": room}, options={})
    fake = SimpleNamespace(
        _zone_manager=lambda: coord.zone_manager,
        coordinator=SimpleNamespace(entry=entry),
    )
    return bs.HVACOccupiedBinarySensor.extra_state_attributes.fget(fake)


def test_room_attrs_shadow_armed_but_rule_released(mods):
    """Lighting says occupied (shadow armed, source edge) while the
    evidence rule has released: `armed` False / `source` idle /
    `tail_expires_at` = the rule's release; the shadow rides on the
    `shadow_*` attrs."""
    with _Clock(T0):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True, "ev": T0 - S(seconds=1000)})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        _pass(coord)
        d = _diag(coord, KIT)
        assert d["armed"] is True and d["output"] is False and d["rule"] == "evidence"
        a = _room_attrs(mods, coord, KIT)
        assert a["armed"] is False and a["source"] == "idle"
        # The rule's (past) release instant, ev + 180, not the shadow's tail.
        assert a["tail_expires_at"] == (T0 - S(seconds=820)).isoformat()
        assert a["hold_expires_at"] == a["tail_expires_at"] == d["release_at"]
        assert a["shadow_tail_expires_at"] == d["tail_expires_at"]
        assert a["shadow_armed"] is True and a["shadow_source"] == d["source"]
        assert a["cold"] is False and a["pending"] is False


def test_room_attrs_pending_and_evidence_sources(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _pending_kitchen(coord, coords, clk)
        a = _room_attrs(mods, coord, KIT)
        assert a["armed"] is False and a["source"] == "pending" and a["pending"] is True
        assert a["episode_start"] == T0.isoformat() and a["dwell_s"] == 60.0
        clk.t = T0 + S(seconds=70)
        _evidence(coords[KIT], onset=T0, ev=clk.t, active=True)
        _pass(coord)
        a = _room_attrs(mods, coord, KIT)
        assert a["armed"] is True and a["source"] == "evidence"
        assert a["tail_expires_at"] == _diag(coord, KIT)["release_at"]
        assert a["arm_class"] == "clean" and a["armed_at"] == clk.t.isoformat()


# ==========================================================================
# D-M1 — a disabled / deleted / retyped room can neither pend nor hold
# ==========================================================================

async def _held_zone(mods, clk):
    """zone_1 Home, past grace, last applied write `away` (misjudged edge)
    with a pending Kitchen: the vacancy away is HELD."""
    # A second, empty, live room keeps the zone ESTABLISHED once the Kitchen
    # drops out (a zone with no live room cannot retreat — pre-existing gate).
    coord, hass, coords, sched = _setup(
        mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True}),
                                ("study", "generic", {"occupied": False})]},
        presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
    )
    coord._zone_entry_dwell = 1
    z = coord.zone_manager.zones["zone_1"]
    z.last_occupied_time = T0 - S(seconds=1000)
    coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 - S(seconds=600))
    _pending_kitchen(coord, coords, clk)
    await coord._apply_house_state_presets()
    await _drain(hass)
    assert _writes(hass, ENT1) == []
    return coord, hass, coords, z


@pytest.mark.asyncio
async def test_room_disabled_mid_pending_drops_out_and_releases_hold(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, z = await _held_zone(mods, clk)
        _entry_of(hass, KIT).disabled_by = "user"
        clk.t = T0 + S(seconds=30); _pass(coord)
        assert coord.zone_manager._room_hvac_class[KIT][0] == "excluded"
        assert z.hvac_pending_arm_rooms == []
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "away")) == 1


@pytest.mark.asyncio
async def test_room_deleted_mid_pending_clears_pending_state(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, z = await _held_zone(mods, clk)
        DOMAIN = mods["const"].DOMAIN
        hass.config_entries._entries.remove(_entry_of(hass, KIT))
        hass.data[DOMAIN].pop(_entry_id(KIT))
        clk.t = T0 + S(seconds=30); _pass(coord)
        zm = coord.zone_manager
        assert zm._hvac_pending[KIT] is False and zm._hvac_cold[KIT] is False
        assert zm._hvac_exempt_reason[KIT] is None and zm._hvac_episode_start.get(KIT) is None
        assert z.hvac_pending_arm_rooms == []


@pytest.mark.asyncio
async def test_room_retyped_to_hallway_mid_pending_clears_and_releases_hold(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, z = await _held_zone(mods, clk)
        from custom_components.universal_room_automation.const import CONF_ROOM_TYPE
        _entry_of(hass, KIT).data[CONF_ROOM_TYPE] = "hallway"
        clk.t = T0 + S(seconds=30); _pass(coord)
        zm = coord.zone_manager
        assert zm._hvac_pending[KIT] is False and zm._hvac_episode_start.get(KIT) is None
        assert zm._hvac_arm_source[KIT] == "hallway_excluded"
        assert z.hvac_pending_arm_rooms == []
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, ENT1, "away")) == 1


# ==========================================================================
# D-M3 — `_zone_vacancy_away_at` only on a REAL transition (§9.7 re-write)
# ==========================================================================

@pytest.mark.asyncio
async def test_vacancy_away_reissue_does_not_reanchor_quick_return(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        z = coord.zone_manager.zones["zone_1"]
        z.last_occupied_time = T0 - S(seconds=1000)
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "away")) == 1
        assert coord._zone_vacancy_away_at["zone_1"] == T0
        # §9.7: the status feed still reads `home` -> the tick re-issues.
        z.preset_mode = "home"
        H.set_climate(hass, ENT1, preset_mode="home", hold_activity="home")
        clk.t = T0 + S(seconds=100)
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "away")) == 2
        assert coord._zone_last_s1_write["zone_1"][2] == T0 + S(seconds=100)   # stamped
        assert coord._zone_vacancy_away_at["zone_1"] == T0                    # NOT re-anchored


# ==========================================================================
# B-M3 — a zone-filtered pass keeps other zones' absent set / classification
# ==========================================================================

def test_filtered_pass_keeps_other_zone_absent_set_and_row10_deferral(mods):
    """zone_2's only room lost its coordinator on a FULL pass (absent ->
    unestablished -> the arrester's row-10 comfort-delay keeps deferring).
    A zone_1-filtered fast pass must not re-evaluate zone_2: den stays
    absent, zone_2 stays unestablished, the grant stays in force. The next
    FULL pass re-evaluates it."""
    from homeassistant.config_entries import ConfigEntryState
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": False})],
                         "zone_2": [("den", "generic", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        zm = coord.zone_manager
        DOMAIN = mods["const"].DOMAIN
        arr = coord._override_arrester
        arr._comfort_delay_timers["zone_2"] = MagicMock()
        arr._comfort_delay_meta["zone_2"] = {"granted_at": T0}
        _pass(coord)
        assert arr.comfort_delay_active("zone_2") is False               # established + empty
        den_rc = hass.data[DOMAIN].pop(_entry_id("den"))
        arr._comfort_delay_timers["zone_2"] = MagicMock()
        _pass(coord)                                                     # full: den absent
        assert "den" in zm._coordinator_absent_this_pass
        assert zm.is_zone_hvac_established("zone_2") is False
        assert arr.comfort_delay_active("zone_2") is True                # row 10 keeps deferring
        hass.data[DOMAIN][_entry_id("den")] = den_rc                     # back, but no full pass yet
        _entry_of(hass, "den").state = ConfigEntryState.NOT_LOADED
        zm.update_room_conditions(house_state="home_day", zone_ids={"zone_1"})
        assert "den" in zm._coordinator_absent_this_pass                 # kept
        assert zm._room_hvac_class["den"][0] == "live"                   # kept (not re-classified)
        assert zm.is_zone_hvac_established("zone_2") is False
        assert arr.comfort_delay_active("zone_2") is True
        assert "zone_2" in arr._comfort_delay_timers
        _pass(coord)                                                     # full: re-evaluated
        assert "den" not in zm._coordinator_absent_this_pass
        assert zm._room_hvac_class["den"][0] == "transient"              # NOT_LOADED now seen


# ==========================================================================
# Review C — full cycle arms the exit timer; lock rule with the real stamp
# ==========================================================================

@pytest.mark.asyncio
async def test_full_cycle_arms_exit_timer_for_warm_zone_and_threads_return_window(mods):
    with _Clock(T0):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._return_window_minutes = 0
        coord._startup_audit_done = True
        ps = _heavy(coord)
        for p in ps:
            p.start()
        try:
            await coord._run_decision_cycle()
        finally:
            for p in ps:
                p.stop()
        assert coord._last_full_cycle_started_at == T0
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=240 + 302)
        assert sched.live()[0][0] == 542.0
        assert coord.zone_manager._last_return_window_s == 0.0
        assert coord.zone_manager._last_house_state == "home_day"


@pytest.mark.asyncio
async def test_waiting_periodic_skips_after_real_full_cycle_stamp(mods):
    """A periodic waiting behind a fast run is skipped because a REAL
    `_run_decision_cycle` stamped `_last_full_cycle_started_at` meanwhile
    (the stamp is production code, not a test write)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods)
        coord._startup_audit_done = True
        ps = _heavy(coord)
        for p in ps:
            p.start()
        spy = AsyncMock(wraps=coord._run_decision_cycle)
        try:
            with patch.object(coord, "_run_decision_cycle", new=spy):
                await coord._decision_cycle_lock.acquire()
                coord._fast_path_running = True
                waiting = asyncio.ensure_future(coord._async_decision_cycle())
                await asyncio.sleep(0)
                clk.advance(1)
                await coord._run_decision_cycle()                        # the real cycle ran
                assert coord._last_full_cycle_started_at == clk.t
                coord._fast_path_running = False
                coord._decision_cycle_lock.release()
                await waiting
                assert spy.await_count == 1                              # the waiter skipped
        finally:
            for p in ps:
                p.stop()


@pytest.mark.asyncio
async def test_fast_room_response_switch_restores_off_across_restart(mods):
    from custom_components.universal_room_automation import switch as switch_mod
    coord, hass, coords, _ = _setup(mods)
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": coord})
    sw = switch_mod.HVACFastRoomResponseSwitch(hass, hass.config_entries._entries[0])
    sw.async_write_ha_state = lambda: None
    assert coord.fast_room_response_enabled is True
    with patch.object(switch_mod.RestoreEntity, "async_added_to_hass", new=AsyncMock()), \
         patch.object(sw, "async_get_last_state", new=AsyncMock(return_value=MagicMock(state="off"))):
        await sw.async_added_to_hass()
    assert coord.fast_room_response_enabled is False and sw.is_on is False
    # unknown / unavailable never override the live value (Bug Class #52)
    for st in ("unknown", "unavailable"):
        with patch.object(switch_mod.RestoreEntity, "async_added_to_hass", new=AsyncMock()), \
             patch.object(sw, "async_get_last_state", new=AsyncMock(return_value=MagicMock(state=st))):
            await sw.async_added_to_hass()
        assert coord.fast_room_response_enabled is False
    with patch.object(switch_mod.RestoreEntity, "async_added_to_hass", new=AsyncMock()), \
         patch.object(sw, "async_get_last_state", new=AsyncMock(return_value=MagicMock(state="on"))):
        await sw.async_added_to_hass()
    assert coord.fast_room_response_enabled is True


# ==========================================================================
# C LOW anchors — kill switch in the exit preconditions, `_sync_arm_rechecks`
# wire-in, `exempt_reason` threading, lapse-counter armed guard
# ==========================================================================

def test_exit_timer_preconditions_honour_kill_switch(mods):
    with _Clock(T0):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        _pass(coord)
        coord._schedule_exit_timer("zone_1")
        assert "zone_1" in coord._fast_path_exit_due
        coord._fast_path_enabled = False                                 # bypass the setter
        assert coord._exit_timer_preconditions("zone_1") is False
        coord._schedule_exit_timer("zone_1")
        assert "zone_1" not in coord._fast_path_exit_due and sched.live() == []
        coord._fast_path_enabled = True
        assert coord._exit_timer_preconditions("zone_1") is True


@pytest.mark.asyncio
async def test_fast_run_cancels_arm_recheck_once_room_armed(mods):
    """The fast run's producer pass arms the Kitchen (persisted) -> the arm
    re-check the listener scheduled is cancelled by `_sync_arm_rechecks`
    (no `_on_room_refresh` involved: the run is awaited directly)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        rc = coords[KIT]
        eid = _entry_id(KIT)
        _evidence(rc, onset=T0, ev=T0, active=True); rc.refresh()
        assert eid in coord._fast_path_arm_unsubs and len(sched.live()) == 1
        clk.t = T0 + S(seconds=70)
        _evidence(rc, onset=T0, ev=clk.t, active=True)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t)
        assert coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms == []
        assert eid not in coord._fast_path_arm_unsubs
        assert all(r[1] is not None and r[2] for r in sched.pending if r[0] == 61.0)


@pytest.mark.asyncio
async def test_exempt_reason_threads_listener_to_run_to_row(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        _arm_then_release(coord, coords, clk)
        clk.t = clk.t + S(seconds=60)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        # (1) listener -> run kwargs
        run = AsyncMock()
        with patch.object(coord, "_async_zone_fast_run", new=run), _captured(hass):
            coords[KIT].refresh()
        assert run.call_args.kwargs["exempt_reason"] == "same_room_return"
        assert run.call_args.args == ("zone_1", "fast_entry")
        # (2) run -> S1 -> `preset_change` row
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t, exempt_reason="same_room_return")
        await _drain(hass)
        rows = _rows(hass, mods, "preset_change")
        assert rows[-1]["details"]["new_preset"] == "home"
        assert rows[-1]["details"]["exempt_reason"] == "same_room_return"
        assert rows[-1]["details"]["trigger"] == "fast_entry"


def test_lapse_counter_skips_armed_episode(mods):
    """`_lapse_episode` counts a lapsed episode as filtered ONLY when it
    never armed (helper-level anchor: the armed value is not reachable
    through the producer — an arm flips `prev_out`, which clears the
    episode on the next pass before any lapse)."""
    coord, hass, coords, sched = _setup(mods)
    zm = coord.zone_manager
    zm._hvac_episode_start[KIT] = T0
    zm._hvac_ep_armed[KIT] = True
    zm._lapse_episode(KIT, "zone_1")
    assert zm.transit_filtered_today.get("zone_1", 0) == 0
    assert KIT not in zm._hvac_episode_start
    zm._hvac_episode_start[KIT] = T0
    zm._hvac_ep_armed[KIT] = False
    zm._lapse_episode(KIT, "zone_1")
    assert zm.transit_filtered_today["zone_1"] == 1
    zm._lapse_episode(KIT, None)                                          # no zone: not counted
    assert zm.transit_filtered_today["zone_1"] == 1


# ==========================================================================
# A-LOW-5 live accrual, B-L1 warm-zone re-arm, B-L3 latch, D-L2 reason,
# B-M4 kill-switch scope
# ==========================================================================

@pytest.mark.asyncio
async def test_pending_hold_s_today_accrues_live_during_spell(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        z = coord.zone_manager.zones["zone_1"]
        _pending_kitchen(coord, coords, clk)                             # clk.t = T0 + 20
        await coord._apply_house_state_presets()
        assert z.pending_hold_since == T0 + S(seconds=20)
        clk.t = T0 + S(seconds=120)
        assert coord.zone_manager.get_zone_status_attrs("zone_1")["pending_hold_s_today"] == 100
        _pass(coord)                                                     # lapsed at +120
        await coord._apply_house_state_presets()
        assert z.pending_hold_since is None and z.pending_hold_s_today == 100.0
        clk.t = T0 + S(seconds=500)
        assert coord.zone_manager.get_zone_status_attrs("zone_1")["pending_hold_s_today"] == 100


def test_warm_zone_falling_edge_arms_exit_timer_without_run(mods):
    """B-L1: every pass so far saw bed1 ACTIVE (no exit timer: release
    unbounded). The falling-edge refresh (evidence advance into a WARM
    zone) queues no run but (re)arms the exit timer from live evidence."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        _pass(coord)
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == [] and "zone_1" not in coord._fast_path_exit_due
        clk.t = T0 + S(seconds=100)
        rc = coords["bed1"]
        rc.ev = clk.t; rc.active = False                                  # falling edge
        with _captured(hass) as tt:
            rc.refresh()
            assert tt.call_count == 0                                     # warm: no run
        assert coord._fast_path_exit_due["zone_1"] == clk.t + S(seconds=240 + 302)
        assert len(sched.live()) == 1 and sched.live()[0][0] == 542.0


@pytest.mark.asyncio
async def test_pending_hold_latch_closes_when_sibling_arms(mods):
    """B-L3: the hold ends because a sibling ARMED (fused not empty) — the
    row latch closes on that exit too, so the next spell logs again."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(
            mods, clk,
            rooms={"zone_1": [(KIT, "common_area", {"occupied": False}),
                              ("study", "generic", {"occupied": False})]},
        )
        z = coord.zone_manager.zones["zone_1"]
        _pending_kitchen(coord, coords, clk)
        await coord._apply_house_state_presets(); await _drain(hass)
        assert len(_rows(hass, mods, "preset_change_suppressed")) == 1
        assert "zone_1" in coord._pending_hold_logged
        clk.t = T0 + S(seconds=40)
        _evidence(coords["study"], onset=T0 - S(seconds=70), ev=clk.t, active=True)
        _pass(coord)
        assert z.hvac_pending_arm_rooms == [KIT] and z.any_room_hvac_occupied is True
        await coord._apply_house_state_presets(); await _drain(hass)
        assert len(_writes(hass, ENT1, "home")) == 1
        assert "zone_1" not in coord._pending_hold_logged                 # latch closed
        assert z.pending_hold_since is None and z.pending_hold_s_today == 20.0
        # Zone away again; a fresh Kitchen spell logs a second row.
        z.preset_mode = "away"; H.set_climate(hass, ENT1, preset_mode="away", hold_activity="away")
        clk.t = T0 + S(seconds=1000)
        _evidence(coords["study"], onset=T0 - S(seconds=70), ev=T0 + S(seconds=40), active=False)
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", clk.t)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t + S(seconds=5), active=False)
        clk.t = clk.t + S(seconds=10); _pass(coord)
        assert z.hvac_pending_arm_rooms == [KIT]
        await coord._apply_house_state_presets(); await _drain(hass)
        assert len(_rows(hass, mods, "preset_change_suppressed")) == 2


@pytest.mark.asyncio
async def test_shed_forced_away_is_not_booked_as_vacant_past_grace(mods):
    """D-L2: a zone that is BOTH past grace and shed-forced books the away
    as `energy_shed_cap_reached`, never `vacant_past_grace`."""
    with _Clock(T0):
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": False})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        z = coord.zone_manager.zones["zone_1"]
        z.last_occupied_time = T0 - S(seconds=1000)
        z.runtime_exceeded = True
        coord._d5_enabled = True
        coord._energy_constraint_mode = "shed"
        await _tick(coord, hass)
        assert len(_writes(hass, ENT1, "away")) == 1
        assert coord._zone_last_away_reason["zone_1"] == "energy_shed_cap_reached"
        assert "zone_1" not in coord._zone_vacancy_away_at


def test_kill_switch_off_keeps_release_clock_and_filter_on(mods):
    """B-M4 scope: the switch stops the FAST PATH only; the evidence rule
    (D1) and the transit filter (D5) keep running on the tick."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        coord.fast_room_response_enabled = False
        _pending_kitchen(coord, coords, clk)
        d = _diag(coord, KIT)
        assert d["rule"] == "evidence" and d["pending"] is True and d["cold"] is True
        clk.t = T0 + S(seconds=70)
        _evidence(coords[KIT], onset=T0, ev=clk.t, active=True)
        _pass(coord)
        assert _diag(coord, KIT)["output"] is True
        assert coord._fast_path_gates_open("zone_1", "fast_entry") is False


def test_legacy_and_night_passes_reset_stale_d5_fields(mods):
    """A-LOW-1/2: `exempt_reason`, `arm_onset`, `pending`, `cold` and the
    episode never survive a legacy or night pass (they are per-pass D5
    fields of the evidence rule only)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk)
        zm = coord.zone_manager
        _arm_then_release(coord, coords, clk)
        clk.t = clk.t + S(seconds=60)
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        _pass(coord)                                                     # exempt re-arm
        assert _diag(coord, KIT)["exempt_reason"] == "same_room_return"
        assert KIT in zm._hvac_arm_onset
        coord._house_state = "home_night"
        _pass(coord)                                                     # legacy pass
        d = _diag(coord, KIT)
        assert d["rule"] == "legacy"
        assert d["exempt_reason"] is None and d["pending"] is False and d["cold"] is False
        assert KIT not in zm._hvac_arm_onset and d["episode_start"] is None
        # Night: a live episode / exempt reason is dropped too.
        coord._house_state = "home_day"
        zm._hvac_exempt_reason[KIT] = "same_room_return"
        zm._hvac_episode_start[KIT] = clk.t
        coord._house_state = "sleep"
        _pass(coord)
        d = _diag(coord, KIT)
        assert d["rule"] == "night" and d["exempt_reason"] is None and d["cold"] is False
        assert d["episode_start"] is None


@pytest.mark.asyncio
async def test_quick_return_not_counted_when_zone_already_armed(mods):
    """B-L4: a `fast_entry` run on a zone that was ALREADY fused-occupied
    (a second room entering) is not a quick return even with a fresh,
    never-counted vacancy-away anchor."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        _pass(coord)
        z = coord.zone_manager.zones["zone_1"]
        assert z.any_room_hvac_occupied is True
        coord._zone_vacancy_away_at["zone_1"] = clk.t - S(seconds=100)   # stale anchor
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t)
        assert coord._quick_returns_today_view() == {}
        assert "zone_1" not in coord._zone_vacancy_away_counted


@pytest.mark.asyncio
async def test_quick_return_deduped_per_away_across_two_real_rearms(mods):
    """O1 dedup anchor (re-targeted after B-L4): TWO real re-arms on the
    SAME vacancy away (arm, release, arm again — no new away written)
    count ONE quick return."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, dwell=0, vacancy_away_age=100)
        away_at = coord._zone_vacancy_away_at["zone_1"]
        rc = coords[KIT]
        _evidence(rc, onset=clk.t, ev=clk.t, active=True)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t)
        assert coord._quick_returns_today_view() == {"zone_1": 1}
        clk.t = clk.t + S(seconds=200)
        _evidence(rc, onset=rc.onset, ev=T0, active=False); _pass(coord)   # released (hold 180)
        assert coord.zone_manager.zones["zone_1"].any_room_hvac_occupied is False
        assert coord._zone_vacancy_away_at["zone_1"] == away_at            # same away
        clk.t = clk.t + S(seconds=100)
        _evidence(rc, onset=clk.t, ev=clk.t, active=True)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t)
        assert coord.zone_manager.zones["zone_1"].any_room_hvac_occupied is True
        assert coord._quick_returns_today_view() == {"zone_1": 1}          # deduped


# ==========================================================================
# Fix-up round 2 — D-L1 spell closes when S1 is skipped; D-L2 cap >= W + J;
# D-L3 counters by reason; D-L4 suppressed-source falling edge; knob 52 form
# ==========================================================================

async def _open_spell(mods, clk):
    coord, hass, coords, sched = _away_zone(mods, clk)
    z = coord.zone_manager.zones["zone_1"]
    _pending_kitchen(coord, coords, clk)
    await coord._apply_house_state_presets()
    assert z.pending_hold_since == T0 + S(seconds=20)
    assert "zone_1" in coord._pending_hold_logged
    return coord, hass, coords, z


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["zone_intelligence_off", "egress_paused", "arriving", "observation"])
async def test_pending_spell_closes_when_s1_block_skipped(mods, how):
    """D-L1: a tick that never reaches the zone's S1 block closes its spell
    (the clock is the HOLD, not the pending room) and clears both latches."""
    with _Clock(T0) as clk:
        coord, hass, coords, z = await _open_spell(mods, clk)
        clk.t = T0 + S(seconds=50)
        if how == "zone_intelligence_off":
            coord._zone_intelligence_enabled = False
            await coord._apply_house_state_presets()
        elif how == "egress_paused":
            with patch.object(coord._egress_manager, "is_paused", return_value=True):
                await coord._apply_house_state_presets()
        elif how == "arriving":
            coord._house_state = "arriving"
            await coord._apply_house_state_presets()
        else:
            coord._observation_mode = True
            coord._startup_audit_done = True
            ps = [p for p in _heavy(coord) if "apply_house_state_presets" not in str(p)]
            for p in ps:
                p.start()
            try:
                await coord._run_decision_cycle()
            finally:
                for p in ps:
                    p.stop()
        assert z.pending_hold_since is None
        assert z.pending_hold_s_today == 30.0
        assert "zone_1" not in coord._pending_hold_logged
        assert "zone_1" not in coord._pending_hold_cap_logged


@pytest.mark.asyncio
async def test_zone_scoped_run_does_not_close_other_zones_spell(mods):
    """D-L1 scope: a fast run for zone_2 leaves zone_1's spell untouched."""
    with _Clock(T0) as clk:
        coord, hass, coords, z = await _open_spell(mods, clk)
        clk.t = T0 + S(seconds=50)
        await coord._apply_house_state_presets(zone_filter={"zone_2"}, trigger="fast_entry")
        assert z.pending_hold_since == T0 + S(seconds=20)
        assert "zone_1" in coord._pending_hold_logged


@pytest.mark.asyncio
async def test_pending_hold_cap_is_at_least_one_episode_at_knob_15(mods):
    """D-L2: knob 47 = 15 -> W = 900, kitchen J = 180 -> cap = 1080 s (> 600).
    A chain of never-persisting pulses (one every 200 s, gap 190 > J) is
    held at 1000 s and released past 1080 s; the row carries cap_s 1080."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [(KIT, "common_area", {"occupied": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord._zone_entry_dwell = 15
        z = coord.zone_manager.zones["zone_1"]
        z.last_occupied_time = T0 - S(seconds=1000)
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 - S(seconds=600))
        rc = coords[KIT]
        for k in range(0, 7):                                           # 0 .. 1200 s
            clk.t = T0 + S(seconds=200 * k)
            _evidence(rc, onset=clk.t - S(seconds=15), ev=clk.t - S(seconds=5), active=False)
            _pass(coord)
            assert z.hvac_pending_arm_rooms == [KIT], k
            assert coord._pending_hold_cap_s(z) == 1080.0
            await coord._apply_house_state_presets()
            await _drain(hass)
            if 200 * k <= 1080:
                assert _writes(hass, ENT1, "away") == [], k
            else:
                assert len(_writes(hass, ENT1, "away")) == 1, k
                rows = _rows(hass, mods, "pending_hold_capped")
                assert len(rows) == 1 and rows[0]["details"]["cap_s"] == 1080
                assert rows[0]["details"]["held_s"] == 1200
        # knob 47 = 1: W + J = 120 < 600 -> the constant rules.
        coord._zone_entry_dwell = 1
        assert coord._pending_hold_cap_s(z) == 600.0


@pytest.mark.asyncio
async def test_quick_return_counters_split_by_reason(mods):
    """D-L3: `skip_entry_wait` re-arms have their own counter and never land
    in `same_room_returns_today`; quick = same + skip + other."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods)
        z1 = coord.zone_manager.zones["zone_1"]
        for i, reason in enumerate(("skip_entry_wait", "same_room_return", None, "skip_entry_wait")):
            coord._zone_vacancy_away_at["zone_1"] = clk.t - S(seconds=10 + i)
            coord._note_quick_return("zone_1", z1, clk.t, exempt_reason=reason)
        a = coord.get_mode_attrs()
        assert a["quick_returns_today"] == {"zone_1": 4}
        assert a["skip_entry_wait_returns_today"] == {"zone_1": 2}
        assert a["same_room_returns_today"] == {"zone_1": 1}
        assert a["other_room_returns_today"] == {"zone_1": 1}
        # End to end: a skip-room fast entry counts in the skip bucket.
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _away_zone(mods, clk, vacancy_away_age=100)
        _entry_of(hass, KIT).options = {"hvac_skip_entry_wait": True}
        _evidence(coords[KIT], onset=clk.t, ev=clk.t, active=True)
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=clk.t, exempt_reason="skip_entry_wait")
        assert coord.zone_manager.zones["zone_1"].any_room_hvac_occupied is True
        assert coord._fp_skip_entry_wait_returns_today == {"zone_1": 1}
        assert coord._fp_same_room_returns_today == {}
        # ... and the daily reset clears it.
        coord._fp_quick_return_date = "1970-01-01"
        coord._quick_returns_today_view()
        assert coord._fp_skip_entry_wait_returns_today == {}


@pytest.mark.parametrize("active_after", [False, True])
def test_suppressed_source_falling_edge_rearms_exit_timer(mods, active_after):
    """D-L4 (grace 1 min): a refresh with NO evidence advance — a fan-recheck
    release (active -> False, no stamp) or a fan-demoted falling edge (stamp
    suppressed, active unchanged) — queues no run and re-arms the exit timer
    from live evidence: release + 60 + 2 when the evidence ended; no timer
    (unbounded) while it is still active."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, grace=1, constrained=1,
            rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        _pass(coord)
        rc = coords["bed1"]
        rc.refresh()                                                     # advance seen
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == []                                        # active: unbounded
        clk.t = T0 + S(seconds=30)
        rc.active = active_after                                         # same ev
        with _captured(hass) as tt:
            rc.refresh()
            assert tt.call_count == 0
        if active_after:
            assert sched.live() == [] and "zone_1" not in coord._fast_path_exit_due
        else:
            assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=240 + 62)
            assert sched.live()[0][0] == 272.0


def test_return_window_on_hvac_settings_form(mods):
    """Knob 52 is a form field of the HVAC settings step (presence_timing
    section) with the persisted value as its default, 0..60 min."""
    from custom_components.universal_room_automation import config_flow as _cf
    from test_hvac_vacancy_hold_ui_defaults import _walk_schema
    entry = SimpleNamespace(entry_id="cm", options={"hvac_return_window_minutes": 7}, data={})
    flow = _cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = MagicMock()
    flow.hass.states.async_all.return_value = []
    flow.hass.states.get.return_value = None
    result = asyncio.new_event_loop().run_until_complete(
        flow.async_step_coordinator_hvac_settings(user_input=None)
    )
    found = None
    for marker, value in _walk_schema(result["data_schema"]):
        if getattr(marker, "schema", None) == "hvac_return_window_minutes":
            found = (marker, value)
    assert found is not None, "knob 52 missing from the HVAC settings form"
    marker, value = found
    d = marker.default
    assert (d() if callable(d) else d) == 7
    cfg = value.config
    assert (cfg["min"], cfg["max"], cfg["step"], cfg["unit_of_measurement"]) == (0, 60, 1, "min")
