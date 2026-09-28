"""HVAC fast occupancy response (v5.103.20) — D2: event-driven zone runs.

Plan: docs/planning/PLANNING_hvac_fast_occupancy_response.md REV 3 §5 + §11d
(drill rows 15-42) + the config extremes the build brief lists.

Drives the REAL `HVACCoordinator` (W1-B harness: real modules on the smoke
StubHass) with REAL room-config entries and fake room coordinators that
expose the v5.103.20 accessor surface. Climate writes are observed on the
wire (`hass.services.calls`), ledger rows on the FakeActivityLogger, timers
on a fake `async_call_later` that the tests fire by hand, and the clock is
patched on the ONE `homeassistant.util.dt` module every HVAC host shares.

Invariants: INV-1 (re-arm = periodic outcome within the SLA), INV-2 (no
early vacancy away), INV-3 (exit = periodic outcome at release + G, once),
INV-4 (zone scope), INV-5 (shadow untouched — see test_hvac_evidence_clock).
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402
from runtime_harness import StubConfigEntry  # noqa: E402


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


S = timedelta  # noqa: N816
T0 = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)   # 10:00 CDT, home_day


_ACTIVE_CLOCK: list = []


class _Clock:
    """Patches `homeassistant.util.dt.utcnow` / `now` (the one module every
    HVAC host reads after `rebind_real_funnels`)."""

    def __init__(self, start: datetime):
        self.t = start
        from homeassistant.util import dt as real_dt
        self._dt = real_dt
        self._p1 = patch.object(real_dt, "utcnow", side_effect=lambda: self.t)
        self._p2 = patch.object(
            real_dt, "now", side_effect=lambda tz=None: real_dt.as_local(self.t),
        )

    def __enter__(self):
        self._p1.start()
        self._p2.start()
        _ACTIVE_CLOCK.append(self)
        return self

    def __exit__(self, *a):
        self._p1.stop()
        self._p2.stop()
        if _ACTIVE_CLOCK and _ACTIVE_CLOCK[-1] is self:
            _ACTIVE_CLOCK.pop()

    def advance(self, seconds: float):
        self.t = self.t + S(seconds=seconds)
        return self.t

    def bind(self, coord) -> None:
        """Point the clock global of the coordinator's ACTUAL functions at
        the patched module. Under a full run the harness re-imports HVAC
        modules and a class can be bound to an earlier module generation
        whose `dt_util` is a different (unpatched) object — the same reason
        `_w1b_harness.rebind_real_funnels` exists for the funnels."""
        for fn in (
            type(coord.zone_manager).update_room_conditions,
            type(coord)._async_zone_fast_run,
            type(coord)._apply_house_state_presets,
        ):
            g = getattr(fn, "__globals__", None)
            if g is not None and "dt_util" in g:
                g["dt_util"] = self._dt


class FakeScheduler:
    """Stand-in for `async_call_later`: records (delay, cb), fires by hand."""

    def __init__(self):
        self.pending: list[list] = []   # [delay, cb, cancelled]

    def __call__(self, hass, delay, cb):
        rec = [float(delay), cb, False]
        self.pending.append(rec)

        def _cancel():
            rec[2] = True
        return _cancel

    def live(self):
        return [r for r in self.pending if not r[2]]

    def fire_all(self):
        for r in list(self.live()):
            r[2] = True
            r[1](None)


class RoomCoord:
    """Fake room coordinator: v5.103.20 accessor surface + listener API."""

    def __init__(self, entry, *, occupied=False, ev=None, active=False):
        self.entry = entry
        self.config_entry = entry          # vacancy sweep reads it
        self.data = {"occupied": occupied}
        self.ev = ev
        self.active = active
        self.last_update_success = True
        self.listeners: list = []

    def get_last_hvac_evidence_time(self):
        return self.ev

    def is_hvac_evidence_active(self):
        return self.active

    def async_add_listener(self, cb, context=None):
        self.listeners.append(cb)

        def _unsub():
            if cb in self.listeners:
                self.listeners.remove(cb)
        return _unsub

    def refresh(self):
        for cb in list(self.listeners):
            cb()


def _room_entry(room_name: str, room_type: str, entry_id: str | None = None):
    from custom_components.universal_room_automation.const import (
        CONF_ROOM_NAME, CONF_ROOM_TYPE, ENTRY_TYPE_ROOM,
    )
    from homeassistant.config_entries import ConfigEntryState
    e = StubConfigEntry(
        entry_id=entry_id or f"room_{room_name}", entry_type=ENTRY_TYPE_ROOM,
        data={CONF_ROOM_NAME: room_name, CONF_ROOM_TYPE: room_type},
    )
    e.state = ConfigEntryState.LOADED
    e.disabled_by = None
    return e


def _setup(mods, *, house_state="home_day", rooms=None, presets=None,
           grace=5, constrained=5, clk=None):
    """rooms: {zone_id: [(room_name, room_type, RoomCoord kwargs)]}."""
    coord, hass = H.make_coord(mods)
    if clk is None:
        clk = _ACTIVE_CLOCK[-1] if _ACTIVE_CLOCK else None
    if clk is not None:
        clk.bind(coord)
    DOMAIN = mods["const"].DOMAIN
    coord._house_state = house_state
    coord._boot_settle_done = True
    coord._zone_intelligence_enabled = True
    coord._zone_entry_dwell = 0
    coord._vacancy_grace = grace
    coord._vacancy_grace_constrained = constrained
    coord._zone_state_store = H.FakeStore()
    rooms = rooms or {"zone_1": [("bed1", "bedroom", {})]}
    coords: dict[str, RoomCoord] = {}
    for zid, rl in rooms.items():
        zone = coord.zone_manager.zones[zid]
        zone.rooms = [r[0] for r in rl]
        for name, rtype, kw in rl:
            e = _room_entry(name, rtype)
            hass.config_entries._entries.append(e)
            if kw.get("absent"):
                continue
            rc = RoomCoord(e, **{k: v for k, v in kw.items() if k != "absent"})
            hass.data[DOMAIN][e.entry_id] = rc
            coords[name] = rc
    for zid, p in (presets or {}).items():
        z = coord.zone_manager.zones[zid]
        z.preset_mode = p
        H.set_climate(hass, z.climate_entity, preset_mode=p, hold_activity=p)
    sched = FakeScheduler()
    mods["hvac"].async_call_later = sched
    coord._setup_fast_path_listeners()
    return coord, hass, coords, sched


def _writes(hass, ent, preset=None):
    return H.preset_writes(hass, ent, preset)


async def _drain(hass):
    await H.drain(hass, rounds=6)


def _entry_id(name):
    return f"room_{name}"


def _pin_platform(mods):
    """The smoke StubHass has no entity registry, so `strategy_for` is a
    registry miss (uncached generic, `last_sent` always None — the plan's
    fallback case). Pin a platform so the strategy caches and `last_sent`
    is observable."""
    return patch.object(mods["hvac_strategy"], "_entity_platform", return_value="test_platform")


class _TaskCapture:
    """Records the coroutines a sync callback hands to `hass.async_create_task`
    and closes them (no lingering tasks in sync tests)."""

    def __init__(self):
        self.coros: list = []

    @property
    def call_count(self) -> int:
        return len(self.coros)


@contextmanager
def _captured(hass):
    cap = _TaskCapture()
    orig = hass.async_create_task

    def _c(coro, *a, **k):
        cap.coros.append(coro)
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass
        return MagicMock()
    hass.async_create_task = _c
    try:
        yield cap
    finally:
        hass.async_create_task = orig


# ==========================================================================
# Listener lifecycle + entry trigger (rows 20-27, 32, restart storm)
# ==========================================================================

def test_subscribe_then_enumerate_no_miss_no_double(mods):
    coord, hass, coords, _ = _setup(mods)
    assert len(coords["bed1"].listeners) == 1
    assert coord._fast_path_lifecycle_unsub is not None
    coord._setup_fast_path_listeners()          # idempotent
    assert len(coords["bed1"].listeners) == 1


def test_restart_storm_listeners_idempotent(mods):
    """5 rapid `options_updated` + `loaded` events -> exactly one listener
    per room; `unloaded` releases it; teardown releases everything."""
    coord, hass, coords, _ = _setup(mods)
    eid = _entry_id("bed1")
    for _ in range(5):
        coord._on_room_lifecycle(eid, "bed1", "options_updated")
        coord._on_room_lifecycle(eid, "bed1", "loaded")
    assert len(coords["bed1"].listeners) == 1
    assert set(coord._fast_path_room_unsubs) == {eid}
    coord._on_room_lifecycle(eid, "bed1", "unloaded")
    assert coords["bed1"].listeners == []
    coord._on_room_lifecycle(eid, "bed1", "loaded")
    assert len(coords["bed1"].listeners) == 1
    coord._teardown_fast_path()
    assert coords["bed1"].listeners == []
    assert coord._fast_path_lifecycle_unsub is None


@pytest.mark.asyncio
async def test_rearm_while_lighting_still_on_triggers_fast_entry(mods):
    """Row 20 (premise). Lighting `occupied` stays True the whole time; the
    zone was written away; NEW EVIDENCE -> a fast_entry run writes home
    within one run (no lighting edge ever happens)."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(
            mods, rooms={"zone_1": [("bed1", "bedroom", {"occupied": True})]},
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        rc = coords["bed1"]
        rc.ev = T0 - S(seconds=1000); rc.active = False
        coord.zone_manager.update_room_conditions(house_state="home_day")
        z = coord.zone_manager.zones["zone_1"]
        assert z.any_room_hvac_occupied is False
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0 - S(seconds=600))
        # New evidence arrives; lighting never changed.
        clk.advance(5)
        rc.ev = clk.t; rc.active = True
        rc.refresh()
        assert "zone_1" in coord._fast_path_queued
        await _drain(hass)
        assert len(_writes(hass, "climate.test_zone_1", "home")) == 1
        assert _writes(hass, "climate.test_zone_2") == []
        assert _writes(hass, "climate.test_zone_3") == []
        rows = hass.data[mods["const"].DOMAIN]["activity_logger"].actions("preset_change")
        assert len(rows) == 1
        d = rows[0]["details"]
        assert d["trigger"] == "fast_entry"
        assert d["edge_ts"] == clk.t.isoformat()
        assert d["zone_empty_since"] is None
        assert coord._fast_entry_runs_today.value == 1
        assert coord._fast_writes_today.value == 1
        assert coord._last_fast_edge_to_write_s == 0.0
        assert "zone_1" not in coord._fast_path_queued


def test_listener_ignores_refresh_without_evidence_advance(mods):
    """Row 21 + the None rule."""
    coord, hass, coords, _ = _setup(
        mods, presets={"zone_1": "away"},
    )
    rc = coords["bed1"]
    coord.zone_manager.update_room_conditions(house_state="home_day")
    with _captured(hass) as tt:
        rc.ev = None; rc.refresh()                      # None never counts
        assert tt.call_count == 0 and coord._fp_last_ev == {}
        rc.ev = T0; rc.refresh()
        assert tt.call_count == 1
        coord._fast_path_queued.clear()
        rc.refresh()                                     # same ev: no advance
        assert tt.call_count == 1
        rc.ev = T0 - S(seconds=5); rc.refresh()          # earlier: no advance
        assert tt.call_count == 1
        rc.ev = None; rc.refresh()                       # None does not overwrite
        assert coord._fp_last_ev["bed1"] == T0
        rc.ev = T0 + S(seconds=1); rc.refresh()
        assert tt.call_count == 2


def test_fp_last_ev_none_rule(mods):
    coord, hass, coords, _ = _setup(mods, presets={"zone_1": "away"})
    rc = coords["bed1"]
    with _captured(hass) as tt:
        rc.ev = None; rc.refresh(); rc.refresh()
        assert tt.call_count == 0
        rc.ev = T0; rc.refresh()                         # first non-None = advance
        assert tt.call_count == 1


def test_listener_skips_warm_zone(mods):
    """Row 22. Stored fused value True -> no run."""
    coord, hass, coords, _ = _setup(
        mods, rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})]},
        presets={"zone_1": "home"},
    )
    coord.zone_manager.update_room_conditions(house_state="home_day")
    assert coord.zone_manager.zones["zone_1"].any_room_hvac_occupied is True
    with _captured(hass) as tt:
        coords["bed1"].ev = T0 + S(seconds=30); coords["bed1"].refresh()
        assert tt.call_count == 0
        assert coord._fp_last_ev["bed1"] == T0 + S(seconds=30)   # still stored


def test_listener_skips_hallway(mods):
    """Row 23."""
    coord, hass, coords, _ = _setup(
        mods, rooms={"zone_1": [("hall", "hallway", {"ev": T0, "active": True})]},
        presets={"zone_1": "away"},
    )
    with _captured(hass) as tt:
        coords["hall"].refresh()
        assert tt.call_count == 0
        assert coord._fp_last_ev == {}


def test_entry_limiter_denies_second_run_within_60s(mods):
    """Row 24. Last write NOT away -> the 60 s floor applies: 59 s later a
    second advance is limited; 60 s later it runs."""
    with _Clock(T0) as clk:
        coord, hass, coords, _ = _setup(mods, presets={"zone_1": "home"})
        rc = coords["bed1"]
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0 - S(seconds=300))
        coord._fp_last_entry_run["zone_1"] = T0
        with _captured(hass) as tt:
            clk.advance(59)
            rc.ev = clk.t; rc.refresh()
            assert tt.call_count == 0
            assert coord._fast_limited_today.value == 1
            clk.advance(1)
            rc.ev = clk.t; rc.refresh()
            assert tt.call_count == 1


def test_rearm_limiter_exempt_keyed_on_last_sent(mods):
    """Row 25. `zone.preset_mode` reads `home` (the §9.7 status feed) while
    the strategy's `last_sent` is `away` and there is NO stamp -> exempt."""
    with _Clock(T0), _pin_platform(mods):
        coord, hass, coords, _ = _setup(mods, presets={"zone_1": "home"})
        z = coord.zone_manager.zones["zone_1"]
        strat = mods["hvac_strategy"].strategy_for(hass, z.climate_entity)
        strat._record_sent(z.climate_entity, "set_preset_mode", "away")
        z.preset_mode = "home"
        coord._fp_last_entry_run["zone_1"] = T0
        with _captured(hass) as tt:
            coords["bed1"].ev = T0 + S(seconds=1); coords["bed1"].refresh()
            assert tt.call_count == 1
        assert coord._zone_last_write_is_away(z) is True


def test_limiter_exemption_order(mods):
    """Rows 26/27. The S1 stamp is checked FIRST: stamp `home` + last_sent
    `away` -> NOT exempt; no stamp + last_sent `away` -> exempt (registry
    fallback); no stamp + registry miss -> not exempt."""
    with _Clock(T0), _pin_platform(mods):
        coord, hass, coords, _ = _setup(mods, presets={"zone_1": "home"})
        z = coord.zone_manager.zones["zone_1"]
        strat = mods["hvac_strategy"].strategy_for(hass, z.climate_entity)
        strat._record_sent(z.climate_entity, "set_preset_mode", "away")
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0)
        assert coord._zone_last_write_is_away(z) is False
        coord._zone_last_s1_write.pop("zone_1")
        assert coord._zone_last_write_is_away(z) is True
        strat._clear_sent(z.climate_entity)
        assert coord._zone_last_write_is_away(z) is False
        coord._zone_last_s1_write["zone_1"] = ("away", "vacant_past_grace", T0)
        assert coord._zone_last_write_is_away(z) is True


def test_tearing_down_guards_every_callback(mods):
    """Row 32."""
    coord, hass, coords, sched = _setup(mods, presets={"zone_1": "away"})
    coord._tearing_down = True
    with _captured(hass) as tt:
        coords["bed1"].ev = T0; coords["bed1"].refresh()
        assert tt.call_count == 0
        coord._on_exit_timer("zone_1")
        assert tt.call_count == 0
        # With a pending room the callback's own guard is load-bearing (the
        # pending reschedule runs BEFORE the preconditions).
        coord.zone_manager.zones["zone_1"].hvac_pending_arm_rooms = ["bed1"]
        coord._on_exit_timer("zone_1")
        assert sched.live() == []
        # A REAL room that was released must not be re-attached while
        # tearing down (a phantom entry id would fail to attach regardless).
        eid = _entry_id("bed1")
        coord._release_room_listener(eid)
        assert coords["bed1"].listeners == []
        coord._on_room_lifecycle(eid, "bed1", "loaded")
        assert eid not in coord._fast_path_room_unsubs
        assert coords["bed1"].listeners == []
        assert coord._fast_path_gates_open("zone_1", "fast_entry") is False
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == []
    # Fix-up 1: a zone that passes EVERY other precondition (home, evidence
    # state, established, released, due now) — only `_tearing_down` stops
    # the exit callback and the scheduler.
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        coords["bed1"].active = False
        coord._schedule_exit_timer("zone_1")
        assert len(sched.live()) == 1                       # armed while up
        clk.t = coord._fast_path_exit_due["zone_1"]
        coord._tearing_down = True
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0
        assert "zone_1" not in coord._fp_exit_fired and sched.live() == []
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == []


@pytest.mark.asyncio
async def test_teardown_releases_before_first_await(mods):
    """Row 33. At the moment the zone-state save (the first await) runs,
    listeners are already released, timers cancelled, queue cleared."""
    coord, hass, coords, sched = _setup(mods, presets={"zone_1": "home"})
    coord._fast_path_exit_unsubs["zone_1"] = sched(hass, 10, lambda _n: None)
    coord._fast_path_queued.add("zone_1")
    seen = {}

    async def _save(data):
        seen["listeners"] = list(coords["bed1"].listeners)
        seen["timers"] = sched.live()
        seen["queued"] = set(coord._fast_path_queued)
        seen["tearing"] = coord._tearing_down
    coord._zone_state_store.async_save = _save
    await coord.async_teardown()
    assert seen == {"listeners": [], "timers": [], "queued": set(), "tearing": True}


def test_boot_settle_suppresses_fast_path(mods):
    coord, hass, coords, _ = _setup(mods, presets={"zone_1": "away"})
    coord._boot_settle_done = False
    with _captured(hass) as tt:
        coords["bed1"].ev = T0; coords["bed1"].refresh()
        assert tt.call_count == 0
    assert coord._fast_path_gates_open("zone_1", "fast_entry") is False


def test_kill_switch_off_restores_tick_only(mods):
    """Switch OFF: listeners ignore refreshes, exit timers cancelled; ON:
    timers re-armed via reschedule."""
    with _Clock(T0):
        coord, hass, coords, sched = _setup(mods, presets={"zone_1": "away"})
        coord._fast_path_exit_unsubs["zone_1"] = sched(hass, 10, lambda _n: None)
        coord.fast_room_response_enabled = False
        assert sched.live() == []
        with _captured(hass) as tt:
            coords["bed1"].ev = T0; coords["bed1"].refresh()
            assert tt.call_count == 0
        assert coord._fast_path_gates_open("zone_1", "fast_entry") is False
        with patch.object(coord, "reschedule_exit_timers") as rs:
            coord.fast_room_response_enabled = True
            assert rs.call_count == 1
        assert coord.get_mode_attrs()["fast_room_response_enabled"] is True


# ==========================================================================
# The fast run: scope, lock, queue (rows 15-19, 28-31, two zones)
# ==========================================================================

@pytest.mark.asyncio
async def test_fast_run_leaves_sibling_zones_untouched(mods):
    """Row 15. zone_2's room_conditions / lot / css / session untouched by
    a zone_1 fast run (filter BEFORE clear())."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={
                "zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})],
                "zone_2": [("bed2", "bedroom", {"occupied": True, "ev": T0, "active": True})],
            },
            presets={"zone_1": "away", "zone_2": "away", "zone_3": "home"},
        )
        coord.zone_manager.update_room_conditions(house_state="home_day")
        z2 = coord.zone_manager.zones["zone_2"]
        before = (list(z2.room_conditions), z2.last_occupied_time,
                  z2.continuous_occupied_since, z2.current_session_start)
        coords["bed2"].data = {"occupied": False}; coords["bed2"].active = False
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0)
        await _drain(hass)
        after = (list(z2.room_conditions), z2.last_occupied_time,
                 z2.continuous_occupied_since, z2.current_session_start)
        assert after == before
        assert len(z2.room_conditions) == 1


@pytest.mark.asyncio
async def test_s1_writes_only_origin_zone(mods):
    """Row 16. zone_1 AND zone_2 are away with occupied rooms (a periodic
    tick would write both); a zone_1 fast run writes ONLY zone_1."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={
                "zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})],
                "zone_2": [("bed2", "bedroom", {"occupied": True, "ev": T0, "active": True})],
            },
            presets={"zone_1": "away", "zone_2": "away", "zone_3": "home"},
        )
        coord.zone_manager.update_room_conditions(house_state="home_day")
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0)
        await _drain(hass)
        assert len(_writes(hass, "climate.test_zone_1", "home")) == 1
        assert _writes(hass, "climate.test_zone_2") == []


@pytest.mark.asyncio
async def test_absent_set_built_before_zone_loop(mods):
    """Row 17 (B-M3 semantics). zone_2's room has NO coordinator. After a
    full pass it is in `_coordinator_absent_this_pass`; a zone_1 fast run
    KEEPS it there (other zones' rooms keep their previous value)."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={
                "zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})],
                "zone_2": [("ghost", "bedroom", {"absent": True})],
            },
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        coord.zone_manager.update_room_conditions(house_state="home_day")
        assert "ghost" in coord.zone_manager._coordinator_absent_this_pass
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0)
        assert "ghost" in coord.zone_manager._coordinator_absent_this_pass
        assert coord.zone_manager.is_zone_hvac_established("zone_2") is False


@pytest.mark.asyncio
async def test_fast_run_is_zone_scoped(mods):
    """Rows 18/19 + INV-4 spies. zone_1 drifted to `cool` (a periodic tick
    would enforce heat_cool); D9 gate on; a fast run calls NONE of the
    house-wide writers."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        z = coord.zone_manager.zones["zone_1"]
        z.hvac_mode = "cool"
        H.set_climate(hass, z.climate_entity, preset_mode="away", hold_activity="away", state="cool")
        coord.zone_manager.update_room_conditions(house_state="home_day")
        spies = {
            "enforcer": patch.object(mods["hvac"], "emit_set_hvac_mode", new=AsyncMock()),
            "dpm": patch.object(coord, "_async_apply_preset_overrides", new=AsyncMock()),
            "egress": patch.object(coord._egress_manager, "async_tick", new=AsyncMock()),
            "ac_reset": patch.object(coord._override_arrester, "check_ac_reset", new=AsyncMock()),
            "fans": patch.object(coord._fan_controller, "update", new=AsyncMock()),
            "covers": patch.object(coord._cover_controller, "update", new=AsyncMock()),
            "predictor": patch.object(coord._predictor, "update", new=AsyncMock()),
            "anomaly": patch.object(coord, "_record_anomaly_observations", new=AsyncMock()),
            "sunset": patch.object(coord._override_arrester, "sunset_immune_holds"),
            "carrier": patch.object(coord, "_check_carrier_freshness", new=AsyncMock()),
        }
        started = {k: p.start() for k, p in spies.items()}
        try:
            coord._fast_path_queued.add("zone_1")
            await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0)
            await _drain(hass)
            assert len(_writes(hass, "climate.test_zone_1", "home")) == 1
            for k, m in started.items():
                assert m.call_count == 0, k
            # Periodic (no filter) DOES run the enforcer + DPM -> the spies
            # discriminate the skip from "never wired".
            await coord._apply_house_state_presets()
            assert started["enforcer"].call_count == 1
            assert started["dpm"].call_count == 1
        finally:
            for p in spies.values():
                p.stop()


@pytest.mark.asyncio
async def test_fast_run_sweeps_only_its_zone(mods):
    """INV-4: the vacancy sweep runs for the run's zone only, and only when
    the zone is LIGHTING-empty."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={
                "zone_1": [("bed1", "bedroom", {"occupied": False, "ev": T0 - S(seconds=1000)})],
                "zone_2": [("bed2", "bedroom", {"occupied": False, "ev": T0 - S(seconds=1000)})],
            },
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        for zid in ("zone_1", "zone_2"):
            z = coord.zone_manager.zones[zid]
            z.last_occupied_time = T0 - S(seconds=1000)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        with patch.object(coord, "_execute_vacancy_sweep", new=AsyncMock()) as sw:
            coord._fast_path_queued.add("zone_1")
            await coord._async_zone_fast_run("zone_1", "fast_exit")
            await _drain(hass)
            assert [c.args[0].zone_id for c in sw.call_args_list] == ["zone_1"]
        assert len(_writes(hass, "climate.test_zone_1", "away")) == 1
        assert _writes(hass, "climate.test_zone_2") == []


@pytest.mark.asyncio
async def test_sweep_waits_for_lighting_empty_after_fast_exit(mods):
    """§5.9: away lands at hold + G while lighting is still on; the sweep
    does not run until the lighting is empty."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0 - S(seconds=1000)})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord.zone_manager.zones["zone_1"].last_occupied_time = T0 - S(seconds=1000)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        with patch.object(coord, "_execute_vacancy_sweep", new=AsyncMock()) as sw:
            coord._fast_path_queued.add("zone_1")
            await coord._async_zone_fast_run("zone_1", "fast_exit")
            await _drain(hass)
            assert sw.call_count == 0
        assert len(_writes(hass, "climate.test_zone_1", "away")) == 1


@pytest.mark.asyncio
async def test_two_zones_same_second(mods):
    """Evidence in zone_1 and zone_3 in the same loop turn: both run, each
    writes only its zone, order-independent."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={
                "zone_1": [("bed1", "bedroom", {"occupied": True})],
                "zone_3": [("bed3", "bedroom", {"occupied": True})],
            },
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "away"},
        )
        coord.zone_manager.update_room_conditions(house_state="home_day")
        for n in ("bed1", "bed3"):
            coords[n].ev = T0; coords[n].active = True
        for n in ("bed3", "bed1"):
            coords[n].refresh()
        assert coord._fast_path_queued == {"zone_1", "zone_3"}
        await _drain(hass)
        assert len(_writes(hass, "climate.test_zone_1", "home")) == 1
        assert len(_writes(hass, "climate.test_zone_3", "home")) == 1
        assert _writes(hass, "climate.test_zone_2") == []
        assert coord._fast_path_queued == set()


@pytest.mark.asyncio
async def test_queue_entry_cleared_on_every_exit_path(mods):
    """Row 29: gate fails before the lock; gate fails after the lock;
    exception inside; cancellation while waiting."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(mods, presets={"zone_1": "away"})
        # (a) gate fails before the lock (zone not in zm.zones).
        coord._fast_path_queued.add("nope")
        await coord._async_zone_fast_run("nope", "fast_entry")
        assert "nope" not in coord._fast_path_queued
        # (b) gate fails after the lock wait (kill switch flipped).
        coord._fast_path_queued.add("zone_1")
        await coord._decision_cycle_lock.acquire()
        task = asyncio.ensure_future(coord._async_zone_fast_run("zone_1", "fast_entry"))
        await asyncio.sleep(0)
        coord._fast_path_enabled = False
        coord._decision_cycle_lock.release()
        await task
        assert "zone_1" not in coord._fast_path_queued
        coord._fast_path_enabled = True
        # (c) exception inside.
        coord._fast_path_queued.add("zone_1")
        with patch.object(coord.zone_manager, "update_room_conditions",
                          side_effect=RuntimeError("boom")):
            await coord._async_zone_fast_run("zone_1", "fast_entry")
        assert "zone_1" not in coord._fast_path_queued
        assert coord._fast_path_running is False
        assert not coord._decision_cycle_lock.locked()
        # (d) cancellation while waiting for the lock.
        coord._fast_path_queued.add("zone_1")
        await coord._decision_cycle_lock.acquire()
        task = asyncio.ensure_future(coord._async_zone_fast_run("zone_1", "fast_entry"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        coord._decision_cycle_lock.release()
        assert "zone_1" not in coord._fast_path_queued


@pytest.mark.asyncio
async def test_fast_path_running_only_true_while_holding_lock(mods):
    """Row 30."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(mods, presets={"zone_1": "away"})
        seen = []
        real = coord.zone_manager.update_room_conditions

        def _spy(**kw):
            seen.append(coord._fast_path_running)
            return real(**kw)
        coord._fast_path_queued.add("zone_1")
        await coord._decision_cycle_lock.acquire()
        task = asyncio.ensure_future(coord._async_zone_fast_run("zone_1", "fast_entry"))
        await asyncio.sleep(0)
        assert coord._fast_path_running is False       # waiting, not running
        with patch.object(coord.zone_manager, "update_room_conditions", side_effect=_spy):
            coord._decision_cycle_lock.release()
            await task
        assert seen == [True]
        assert coord._fast_path_running is False


@pytest.mark.asyncio
async def test_gates_rechecked_after_lock_wait(mods):
    """Row 31 + "kill switch toggled mid-flight": flipped while the run
    waits for the lock -> no producer pass, no write."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={"zone_1": [("bed1", "bedroom", {"occupied": True, "ev": T0, "active": True})]},
            presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        coord._fast_path_queued.add("zone_1")
        await coord._decision_cycle_lock.acquire()
        task = asyncio.ensure_future(coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0))
        await asyncio.sleep(0)
        coord.fast_room_response_enabled = False
        coord._decision_cycle_lock.release()
        await task
        await _drain(hass)
        assert _writes(hass, "climate.test_zone_1") == []
        assert coord._fast_entry_runs_today.value == 0


@pytest.mark.asyncio
async def test_fast_write_seeds_nudge_skip_on_next_tick(mods):
    """Row 28. A fast S1 write at t: a full cycle at t+60 s starts with the
    zone in `_zones_written_this_cycle` (the soft-nudge dispatch reads it);
    at t+130 s it does not."""
    with _Clock(T0) as clk:
        coord, hass, coords, _ = _setup(mods, presets={"zone_1": "away"})
        coord._zone_last_s1_write["zone_1"] = ("home", "house_state_transition", T0)
        seen = {}

        async def _apply(**kw):
            seen["set"] = set(coord._zones_written_this_cycle)
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
            clk.advance(60)
            await coord._run_decision_cycle()
            assert seen["set"] == {"zone_1"}
            clk.advance(70)                              # t + 130
            await coord._run_decision_cycle()
            assert seen["set"] == set()
        finally:
            for p in heavy:
                p.stop()


@pytest.mark.asyncio
async def test_periodic_lock_rules(mods):
    """§5.5: waits behind a fast run; skips behind a full cycle; a waiting
    periodic skips if a full cycle ran meanwhile (row 39)."""
    with _Clock(T0) as clk:
        coord, hass, coords, _ = _setup(mods)
        run = AsyncMock()
        with patch.object(coord, "_run_decision_cycle", new=run):
            # skips behind a full cycle
            await coord._decision_cycle_lock.acquire()
            coord._fast_path_running = False
            await coord._async_decision_cycle()
            assert run.call_count == 0
            # waits behind a fast run, then runs
            coord._fast_path_running = True
            t = asyncio.ensure_future(coord._async_decision_cycle())
            await asyncio.sleep(0)
            assert run.call_count == 0
            coord._fast_path_running = False
            coord._decision_cycle_lock.release()
            await t
            assert run.call_count == 1
            # row 39: a full cycle started while waiting -> skip
            await coord._decision_cycle_lock.acquire()
            coord._fast_path_running = True
            t = asyncio.ensure_future(coord._async_decision_cycle())
            await asyncio.sleep(0)
            clk.advance(1)
            coord._last_full_cycle_started_at = clk.t
            coord._fast_path_running = False
            coord._decision_cycle_lock.release()
            await t
            assert run.call_count == 1


def test_waiting_periodic_skips_if_full_cycle_ran(mods):
    """Row 39 (sync alias of the last leg of test_periodic_lock_rules)."""
    with _Clock(T0) as clk:
        coord, hass, coords, _ = _setup(mods)
        run = AsyncMock()

        async def go():
            with patch.object(coord, "_run_decision_cycle", new=run):
                await coord._decision_cycle_lock.acquire()
                coord._fast_path_running = True
                t = asyncio.ensure_future(coord._async_decision_cycle())
                await asyncio.sleep(0)
                clk.advance(1)
                coord._last_full_cycle_started_at = clk.t
                coord._fast_path_running = False
                coord._decision_cycle_lock.release()
                await t
        asyncio.get_event_loop().run_until_complete(go())
        assert run.call_count == 0


# ==========================================================================
# Exit timer (rows 34-38, grace extremes, crossing to sleep)
# ==========================================================================

def _exit_setup(mods, clk, *, grace=10, constrained=3, house_state="home_day",
                room_type="bedroom"):
    coord, hass, coords, sched = _setup(
        mods, house_state=house_state, grace=grace, constrained=constrained,
        rooms={"zone_1": [(("bed1"), room_type, {"occupied": True, "ev": clk.t, "active": True})]},
        presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
    )
    coord.zone_manager.update_room_conditions(house_state=house_state)
    return coord, hass, coords, sched


def test_exit_timer_fires_at_release_plus_grace(mods):
    """Row 37 + "grace 10 / constrained 3": due = release + G + 2 s; coast
    on -> the constrained grace; coast off -> normal again."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        rc = coords["bed1"]
        rc.active = False                                # evidence at T0, hold 240
        coord._schedule_exit_timer("zone_1")
        rel = T0 + S(seconds=240)
        assert coord._fast_path_exit_due["zone_1"] == rel + S(seconds=602)
        assert sched.live()[0][0] == 842.0
        EC = mods["hvac"].EnergyConstraint
        coord._handle_energy_constraint(EC(mode="coast", setpoint_offset=0.0))
        assert coord._fast_path_exit_due["zone_1"] == rel + S(seconds=182)
        coord._handle_energy_constraint(EC(mode="normal", setpoint_offset=0.0))
        assert coord._fast_path_exit_due["zone_1"] == rel + S(seconds=602)
        assert len(sched.live()) == 1


def test_exit_timer_grace_zero(mods):
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk, grace=0, constrained=0)
        coords["bed1"].active = False
        coord._schedule_exit_timer("zone_1")
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=242)


def test_exit_timer_uses_grace_at_fire_time(mods):
    """Row 36. Scheduled with grace 3; the knob is RAISED to 10 by a bypass
    writer (no reschedule hook); when the timer fires at the OLD due the
    callback re-reads the LIVE grace -> not due -> lazy reschedule, no run.
    A callback using the scheduled grace would run here."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk, grace=3, constrained=3)
        coords["bed1"].active = False
        coord._schedule_exit_timer("zone_1")
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=240 + 182)
        coord._vacancy_grace = 10                         # bypass writer
        clk.t = T0 + S(seconds=240 + 182)
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0
        assert "zone_1" not in coord._fp_exit_fired
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=240 + 602)
        # ... and it does run once the live due is reached.
        clk.t = T0 + S(seconds=240 + 602)
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 1
        assert coord._fp_exit_fired["zone_1"] == ("zone_1", T0 + S(seconds=240))


def test_exit_timer_reads_live_evidence(mods):
    """Row 35. Evidence advances between passes; at the scheduled due the
    callback recomputes from the LIVE accessor -> not due -> lazy
    reschedule, NO run."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        rc = coords["bed1"]; rc.active = False
        coord._schedule_exit_timer("zone_1")
        due = coord._fast_path_exit_due["zone_1"]
        rc.ev = T0 + S(seconds=500)                       # live advance, no pass
        clk.t = due
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=500 + 240 + 602)
        assert len(sched.live()) == 1


def test_exit_timer_lazy_reschedule_while_active(mods):
    """While the room stays active (unbounded release) no timer exists;
    once evidence ends a timer is armed."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == []
        coords["bed1"].active = False
        coord._schedule_exit_timer("zone_1")
        assert len(sched.live()) == 1


@pytest.mark.asyncio
async def test_exit_timer_one_shot_under_feed_disagreement(mods):
    """Rows 34 + §9.7: the fast exit writes away; the status feed still
    reads `home` afterwards. The one-shot key AND the write stamp both stop
    a second fast exit; re-issues stay on the tick."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        rc = coords["bed1"]; rc.active = False
        coord._schedule_exit_timer("zone_1")
        clk.t = T0 + S(seconds=240 + 602)
        sched.fire_all()
        await _drain(hass)
        assert len(_writes(hass, "climate.test_zone_1", "away")) == 1
        z = coord.zone_manager.zones["zone_1"]
        z.preset_mode = "home"                            # feed disagreement
        H.set_climate(hass, z.climate_entity, preset_mode="home", hold_activity="away")
        # Simulate the stamp being lost (restart / periodic home write) —
        # the one-shot key alone must block re-arming for this episode.
        coord._zone_last_s1_write.pop("zone_1", None)
        mods["hvac_strategy"]._test_reset_cache()
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == []
        assert coord._fp_exit_fired["zone_1"] == ("zone_1", T0 + S(seconds=240))


@pytest.mark.asyncio
async def test_exit_timer_one_shot_consumed_on_gate_e_deferral(mods):
    """A deferred exit run (W1-B gate (e): manual zone under a live borrow)
    consumes the key; the tick owns the rest of the episode."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        rc = coords["bed1"]; rc.active = False
        z = coord.zone_manager.zones["zone_1"]
        z.preset_mode = "manual"
        H.set_climate(hass, z.climate_entity, preset_mode="manual", hold_activity="manual")
        # Gate (e): a live borrow (nudge in flight) — D49: the vacancy-away
        # bypass defers ONLY for (a/b) and (e), never for (c)/(d).
        coord._override_arrester._nudge_in_flight.add("zone_1")
        coord._override_arrester._compromise_timers["zone_1"] = lambda: None
        coord._schedule_exit_timer("zone_1")
        clk.t = T0 + S(seconds=240 + 602)
        sched.fire_all()
        await _drain(hass)
        assert _writes(hass, "climate.test_zone_1") == []
        assert coord._fp_exit_fired["zone_1"] == ("zone_1", T0 + S(seconds=240))
        coord._schedule_exit_timer("zone_1")
        assert sched.live() == []


def test_exit_timer_cancelled_on_zone_prune(mods):
    """Row 38."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        coords["bed1"].active = False
        coord._schedule_exit_timer("zone_1")
        assert len(sched.live()) == 1
        coord._handle_zm_zones_updated({"deleted_zone_id": "zone_1", "deleted_zone_name": "Zone 1"})
        assert sched.live() == []
        assert "zone_1" not in coord._fast_path_exit_unsubs


def test_exit_timer_survives_crossing_to_sleep(mods):
    """"A crossing from home_evening to sleep in the middle of a timeout":
    the timer armed in home_evening fires after the house entered sleep;
    the shadow rides `occupied` -> release unbounded -> no run, no timer."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk, house_state="home_evening")
        rc = coords["bed1"]; rc.active = False
        coord._schedule_exit_timer("zone_1")
        coord._house_state = "sleep"
        coord.zone_manager.update_room_conditions(house_state="sleep")
        clk.t = T0 + S(seconds=240 + 602)
        with _captured(hass) as tt:
            sched.fire_all()
            assert tt.call_count == 0
        assert sched.live() == []


def test_exit_timer_rescheduled_on_grace_knob_change(mods):
    """number.py wire-in: the grace Number setter calls
    `reschedule_exit_timers` and the due moves."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _exit_setup(mods, clk)
        coords["bed1"].active = False
        coord._schedule_exit_timer("zone_1")
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=240 + 602)
        from custom_components.universal_room_automation import number as number_mod
        ent = number_mod.VacancyGraceMinutesNumber(hass, H.make_coord.__globals__  # noqa: E501
                                                  and hass.config_entries._entries[0])
        ent._get_hvac = lambda: coord
        ent.async_write_ha_state = lambda: None
        asyncio.get_event_loop().run_until_complete(ent.async_set_native_value(4))
        assert coord._fast_path_exit_due["zone_1"] == T0 + S(seconds=240 + 242)


@pytest.mark.asyncio
async def test_backfill_prevents_early_vacancy_away(mods):
    """Row 13 (INV-2, periodic leg). Evidence ends at T0 (hold 240 ->
    release T0+240). A tick at T0+310 sees the zone empty: with the
    back-fill `last_occupied_time == T0+240`, 70 s into the grace -> no
    away. Without it the grace would count from the last occupied PASS
    (T0) and the away would land 230 s early."""
    with _Clock(T0) as clk:
        coord, hass, coords, _ = _setup(
            mods, rooms={"zone_1": [("bed1", "bedroom", {"occupied": False, "ev": T0, "active": True})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord.zone_manager.update_room_conditions(house_state="home_day")
        assert coord.zone_manager.zones["zone_1"].last_occupied_time == T0
        coords["bed1"].active = False
        clk.t = T0 + S(seconds=310)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        assert coord.zone_manager.zones["zone_1"].last_occupied_time == T0 + S(seconds=240)
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert _writes(hass, "climate.test_zone_1") == []
        clk.t = T0 + S(seconds=545)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        await coord._apply_house_state_presets()
        await _drain(hass)
        assert len(_writes(hass, "climate.test_zone_1", "away")) == 1


# ==========================================================================
# Ceiling, runaway, quick-return (rows 40-42)
# ==========================================================================

def test_write_ceiling_trips_and_clears_at_local_midnight(mods):
    """Row 40. 7 fast writes in an hour -> trip + one NM; gates closed until
    local midnight; open after."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods, presets={"zone_1": "home"})
        nm = hass.data[mods["const"].DOMAIN]["notification_manager"]
        for i in range(6):
            coord._note_fast_write("zone_1", clk.t, None)
            clk.advance(60)
        assert coord._fast_path_zone_tripped("zone_1") is False
        coord._note_fast_write("zone_1", clk.t, None)
        assert coord._fast_path_zone_tripped("zone_1") is True
        assert coord._fast_path_gates_open("zone_1", "fast_entry") is False
        coord._note_fast_write("zone_1", clk.t, None)      # no second NM
        asyncio.get_event_loop().run_until_complete(H.drain(hass))
        assert [n["hazard_type"] for n in nm.notes] == ["hvac_fast_path_write_ceiling"]
        assert coord.get_mode_attrs()["fast_tripped_zones"] == ["zone_1"]
        # Local midnight after T0 in the environment's zone (independent
        # literal date; the zone is whatever HA's DEFAULT_TIME_ZONE is).
        from homeassistant.util import dt as real_dt
        midnight_local = datetime(2026, 9, 29, 0, 0, 0, tzinfo=real_dt.DEFAULT_TIME_ZONE)
        clk.t = midnight_local - S(minutes=1)
        assert coord._fast_path_zone_tripped("zone_1") is True
        clk.t = midnight_local
        assert coord._fast_path_zone_tripped("zone_1") is False
        assert coord._fast_path_gates_open("zone_1", "fast_entry") is True


@pytest.mark.asyncio
async def test_runaway_guard_trips_at_31_runs(mods):
    """Row 41. 30 runs in an hour are fine; the 31st trips (denied) + NM."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods, presets={"zone_1": "home"})
        nm = hass.data[mods["const"].DOMAIN]["notification_manager"]
        for i in range(30):
            coord._fast_path_queued.add("zone_1")
            await coord._async_zone_fast_run("zone_1", "fast_entry")
            clk.advance(10)
        assert coord._fast_path_zone_tripped("zone_1") is False
        assert coord._fast_entry_runs_today.value == 30
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_entry")
        assert coord._fast_path_zone_tripped("zone_1") is True
        assert coord._fast_entry_runs_today.value == 30
        await _drain(hass)
        assert [n["hazard_type"] for n in nm.notes] == ["hvac_fast_path_runaway"]


@pytest.mark.asyncio
async def test_quick_return_counter_and_nm_latch(mods):
    """Row 42 (O1). One event per APPLIED `vacant_past_grace` away: the FIRST
    fast_entry within 900 s of it counts (exempt or not); later entries on
    the same away do not; the 12th event per zone per day fires ONE LOW NM
    whose text reads the window from the constant; an entry >= 900 s after
    the away is not a quick return."""
    with _Clock(T0) as clk:
        coord, hass, coords, sched = _setup(mods, presets={"zone_1": "away"})
        nm = hass.data[mods["const"].DOMAIN]["notification_manager"]
        z = coord.zone_manager.zones["zone_1"]
        for i in range(13):
            away_at = clk.t - S(seconds=100 + i)
            coord._zone_vacancy_away_at["zone_1"] = away_at
            coord._note_quick_return("zone_1", z, clk.t, exempt_reason=("same_room_return" if i % 2 == 0 else None))
            coord._note_quick_return("zone_1", z, clk.t)   # same away: no 2nd event
        assert coord._quick_returns_today_view()["zone_1"] == 13
        assert coord._fp_same_room_returns_today["zone_1"] == 7
        assert coord._fp_other_room_returns_today["zone_1"] == 6
        await _drain(hass)
        assert [n["hazard_type"] for n in nm.notes] == ["hvac_quick_return_rate"]
        assert nm.notes[0]["severity"].name == "LOW"
        assert "within 15 minutes 12 times today" in nm.notes[0]["message"]
        coord._zone_vacancy_away_at["zone_1"] = clk.t - S(seconds=900)
        coord._note_quick_return("zone_1", z, clk.t)
        assert coord._quick_returns_today_view()["zone_1"] == 13
        attrs = coord.get_mode_attrs()
        assert attrs["quick_returns_today"] == {"zone_1": 13}
        assert attrs["same_room_returns_today"] == {"zone_1": 7}
        assert attrs["other_room_returns_today"] == {"zone_1": 6}


# ==========================================================================
# Equivalence (INV-1) + INV-2
# ==========================================================================

_SEEDS = [
    # (house_state, zone preset, room kwargs, zone lot age s, expect_write)
    ("home_day", "away", {"occupied": True, "active": True}, 0, ["home"]),
    ("home_day", "home", {"occupied": False}, 1000, ["away"]),
    ("sleep", "home", {"occupied": True, "active": True}, 0, ["sleep"]),
    # manual write-through under open gates = resume-then-pin (2 calls)
    ("home_day", "manual", {"occupied": True, "active": True}, 0, ["resume", "home"]),
    ("home_day", "home", {"occupied": True, "active": True}, 0, []),
    ("arriving", "away", {"occupied": True, "active": True}, 0, []),
    ("home_day", "home", {"occupied": False}, 100, []),         # inside grace
]


@pytest.mark.asyncio
@pytest.mark.parametrize("hs,preset,rkw,lot_age,expect", _SEEDS)
async def test_fast_decision_equals_periodic_decision(mods, hs, preset, rkw, lot_age, expect):
    """For every seed the fast run's S1 outcome for zone_1 equals the
    periodic run's outcome for zone_1 (writes AND non-writes)."""
    assert any(s[4] for s in _SEEDS)                      # seeds MUST write
    outcomes = []
    for fast in (False, True):
        with _Clock(T0):
            rk = dict(rkw); rk.setdefault("ev", T0 - S(seconds=lot_age))
            coord, hass, coords, _ = _setup(
                mods, house_state=hs,
                rooms={"zone_1": [("bed1", "bedroom", rk)]},
                presets={"zone_1": preset, "zone_2": "home", "zone_3": "home"},
            )
            if preset == "manual":
                coord._override_arrester.enabled = True
            coord.zone_manager.zones["zone_1"].last_occupied_time = T0 - S(seconds=lot_age)
            coord.zone_manager.update_room_conditions(house_state=hs)
            coord.zone_manager.zones["zone_1"].last_occupied_time = T0 - S(seconds=lot_age)
            if fast:
                coord._fast_path_queued.add("zone_1")
                await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0)
            else:
                await coord._apply_house_state_presets()
            await _drain(hass)
            w = _writes(hass, "climate.test_zone_1")
            outcomes.append([c[2].get("preset_mode") for c in w])
    assert outcomes[0] == outcomes[1]
    assert outcomes[1] == expect


@pytest.mark.asyncio
async def test_evidence_during_grace_prevents_away(mods):
    """INV-2. Release at T0+240; a fast_exit at T0+540 with fresh evidence
    at T0+500 must NOT write away (fast or periodic)."""
    for fast in (False, True):
        with _Clock(T0) as clk:
            coord, hass, coords, _ = _setup(
                mods,
                rooms={"zone_1": [("bed1", "bedroom", {"occupied": False, "ev": T0})]},
                presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
            )
            coord.zone_manager.update_room_conditions(house_state="home_day")
            clk.t = T0 + S(seconds=540)
            coords["bed1"].ev = T0 + S(seconds=500)
            if fast:
                coord._fast_path_queued.add("zone_1")
                await coord._async_zone_fast_run("zone_1", "fast_exit")
            else:
                coord.zone_manager.update_room_conditions(house_state="home_day")
                await coord._apply_house_state_presets()
            await _drain(hass)
            assert _writes(hass, "climate.test_zone_1") == []


@pytest.mark.asyncio
async def test_preset_change_row_carries_trigger_edge_ts_zone_empty_since(mods):
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods,
            rooms={"zone_1": [("bed1", "bedroom", {"occupied": False, "ev": T0 - S(seconds=1000)})]},
            presets={"zone_1": "home", "zone_2": "home", "zone_3": "home"},
        )
        coord.zone_manager.zones["zone_1"].last_occupied_time = T0 - S(seconds=1000)
        coord.zone_manager.update_room_conditions(house_state="home_day")
        coord._fast_path_queued.add("zone_1")
        await coord._async_zone_fast_run("zone_1", "fast_exit")
        await _drain(hass)
        rows = hass.data[mods["const"].DOMAIN]["activity_logger"].actions("preset_change")
        d = rows[0]["details"]
        assert d["trigger"] == "fast_exit" and d["edge_ts"] is None
        assert d["zone_empty_since"] == (T0 - S(seconds=760)).isoformat()
        assert d["reason"] == "vacant_past_grace"
        assert coord._zone_last_s1_write["zone_1"][0] == "away"
        assert coord._zone_last_s1_write["zone_1"][1] == "vacant_past_grace"
        assert coord._zone_vacancy_away_at["zone_1"] == T0
        assert coord._zone_last_away_reason["zone_1"] == "vacant_past_grace"
        assert d["established"] is True and d["last_away_reason"] is None
        assert d["exempt_reason"] is None


# ==========================================================================
# Switch entity round-trip
# ==========================================================================

@pytest.mark.asyncio
async def test_fast_room_response_switch_roundtrip(mods):
    from custom_components.universal_room_automation import switch as switch_mod
    coord, hass, coords, _ = _setup(mods)
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = MagicMock(
        coordinators={"hvac": coord},
    )
    sw = switch_mod.HVACFastRoomResponseSwitch(hass, hass.config_entries._entries[0])
    sw.async_write_ha_state = lambda: None
    assert sw.is_on is True
    assert sw.unique_id == f"{mods['const'].DOMAIN}_hvac_fast_room_response"
    assert sw.name == "31 · Fast Room Response"
    await sw.async_turn_off()
    assert coord.fast_room_response_enabled is False
    await sw.async_turn_on()
    assert coord.fast_room_response_enabled is True


# ==========================================================================
# Plan-named aliases (REV 7 §D2 acceptance) for behaviours proven above
# ==========================================================================

@pytest.mark.asyncio
async def test_periodic_waits_behind_fast_run(mods):
    with _Clock(T0):
        coord, hass, coords, _ = _setup(mods)
        run = AsyncMock()
        with patch.object(coord, "_run_decision_cycle", new=run):
            await coord._decision_cycle_lock.acquire()
            coord._fast_path_running = True
            t = asyncio.ensure_future(coord._async_decision_cycle())
            await asyncio.sleep(0)
            assert run.call_count == 0
            coord._fast_path_running = False
            coord._decision_cycle_lock.release()
            await t
            assert run.call_count == 1


@pytest.mark.asyncio
async def test_periodic_skips_behind_full_cycle(mods):
    with _Clock(T0):
        coord, hass, coords, _ = _setup(mods)
        run = AsyncMock()
        with patch.object(coord, "_run_decision_cycle", new=run):
            await coord._decision_cycle_lock.acquire()
            coord._fast_path_running = False
            await coord._async_decision_cycle()
            coord._decision_cycle_lock.release()
            assert run.call_count == 0


def test_listener_lifecycle_idempotent(mods):
    test_restart_storm_listeners_idempotent(mods)
