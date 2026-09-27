"""HVAC W1-B D-P1 (immune-hold persistence) + D-P1a (TAO restart-restore,
decision 46) via `_zone_state_store` side-keys `__immune_holds` /
`__tao_state`. No new table.

Restart is simulated by feeding a stored snapshot to a FRESH coordinator
through the real `async_setup` load seam (`_rehydrate_arrester_state`,
called BEFORE the first decision cycle) and by driving the real
`async_setup` with spies for the ordering anchor.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402


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
    """Real HA timers (arrester grace / TAO pre-warn / nudge eval) are armed
    by the production paths under test; the leak detector cancels + warns
    instead of failing (phcc opt-in)."""
    return True


ZONE = "zone_1"
ENT = "climate.test_zone_1"


def _coord_with_store(mods, data=None):
    coord, hass = H.make_coord(mods)
    coord._zone_state_store = H.FakeStore(data)
    coord._house_state = "home_day"
    coord._zone_intelligence_enabled = False
    z = coord.zone_manager.zones[ZONE]
    z.preset_mode = "manual"
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
    return coord, hass


async def _restart_into(mods, stored):
    """Fresh coordinator + the boot seam with `stored` as the store load."""
    coord, hass = _coord_with_store(mods, stored)
    await coord._rehydrate_arrester_state(stored)
    await H.drain(hass)
    return coord, hass


def _tao_rows(hass, mods):
    return [r for r in hass.data[mods["const"].DOMAIN]["database"].rows
            if r.get("action") == "tao_restore_evaluated"]


# ---- D-P1 immune holds -----------------------------------------------------


@pytest.mark.asyncio
async def test_immune_hold_persists_across_restart(mods):
    # Pre-shutdown: stamp -> a save is scheduled through the coordinator.
    coord_a, hass_a = _coord_with_store(mods)
    coord_a._override_arrester._stamp_immune_hold(ZONE, "u1", "Oji", "person.oji")
    await H.drain(hass_a)
    saved = coord_a._zone_state_store.saves[-1]
    assert saved["__immune_holds"][ZONE]["user_name"] == "Oji"
    assert isinstance(saved["__immune_holds"][ZONE]["started_ts"], str)
    # Restart into the saved snapshot.
    coord_b, hass_b = await _restart_into(mods, saved)
    arr = coord_b._override_arrester
    assert ZONE in arr._immune_holds
    from datetime import datetime
    assert isinstance(arr._immune_holds[ZONE]["started_ts"], datetime)
    assert arr._immune_holds[ZONE]["started_ts"].tzinfo is not None
    assert arr._corrective_writes_suppressed(ZONE) is True
    await coord_b._apply_house_state_presets()
    await H.drain(hass_b)
    assert H.preset_writes(hass_b, ENT) == [], "S1 must not reclaim across the restart"
    led = hass_b.data[mods["const"].DOMAIN]["activity_logger"]
    assert led.actions("preset_change_deferred")[0]["details"]["reason"] == "person_protected_hold"


@pytest.mark.asyncio
async def test_immune_hold_max_age_sunset_on_rehydrated_hold(mods):
    started = (H.local_now() - timedelta(seconds=14401)).isoformat()  # 4 h + 1 s
    stored = {"__immune_holds": {ZONE: {
        "user_id": "u", "user_name": "Oji", "person_entity": "person.oji",
        "started_ts": started, "next_activity_ts": None, "pending_sunset_state": None,
    }}}
    coord, hass = await _restart_into(mods, stored)
    arr = coord._override_arrester
    assert ZONE in arr._immune_holds
    assert arr.sunset_immune_holds("max_age_or_boundary") == 1
    assert ZONE not in arr._immune_holds
    # a fresh hold (4 h - 1 s) does NOT sunset
    arr.rehydrate_immune_holds({ZONE: {
        "user_name": "Oji", "started_ts": (H.local_now() - timedelta(seconds=14399)).isoformat(),
    }})
    assert arr.sunset_immune_holds("max_age_or_boundary") == 0


@pytest.mark.asyncio
async def test_immune_hold_next_activity_sunset_on_rehydrated_hold(mods):
    stored = {"__immune_holds": {ZONE: {
        "user_name": "Oji", "person_entity": "person.oji",
        "started_ts": (H.local_now() - timedelta(minutes=30)).isoformat(),
        "next_activity_ts": (H.local_now() - timedelta(seconds=1)).isoformat(),
    }}}
    coord, hass = await _restart_into(mods, stored)
    arr = coord._override_arrester
    assert arr.sunset_immune_holds("max_age_or_boundary") == 1


@pytest.mark.asyncio
async def test_immune_hold_stamped_and_sunset_ledger_rows(mods):
    coord, hass = _coord_with_store(mods)
    arr = coord._override_arrester
    arr._stamp_immune_hold(ZONE, "u1", "Oji", "person.oji")
    arr._immune_holds[ZONE]["started_ts"] = H.local_now() - timedelta(seconds=14401)
    arr.sunset_immune_holds("max_age_or_boundary")
    await H.drain(hass)
    led = hass.data[mods["const"].DOMAIN]["activity_logger"]
    st = led.actions("immune_hold_stamped")
    su = led.actions("immune_hold_sunset")
    assert len(st) == 1 and st[0]["zone"] == ZONE and st[0]["details"]["user_name"] == "Oji"
    assert len(su) == 1 and su[0]["zone"] == ZONE and su[0]["details"]["sunset_reason"] == "max_age"
    # the sunset also drops the persisted record
    assert coord._zone_state_store.saves[-1]["__immune_holds"] == {}


def test_rehydrate_drops_unparseable_started_ts(mods):
    coord, hass = _coord_with_store(mods)
    arr = coord._override_arrester
    assert arr.rehydrate_immune_holds({ZONE: {"started_ts": 12345.0}}) == 0
    assert ZONE not in arr._immune_holds


@pytest.mark.asyncio
async def test_immune_hold_boot_load_precedes_first_cycle(mods):
    """Wire-in anchor (N8): the REAL `async_setup` calls the rehydration
    seam BEFORE its first `_async_decision_cycle`."""
    from runtime_harness import StubBus
    _orig = StubBus.async_listen
    StubBus.async_listen = lambda self, et, li, *a, **k: _orig(self, et, li)
    try:
        coord, hass = _coord_with_store(mods, {"__immune_holds": {ZONE: {
            "user_name": "Oji", "started_ts": H.local_now().isoformat(),
        }}})
        order: list[str] = []
        real_rehydrate = coord._rehydrate_arrester_state

        async def _spy_rehydrate(stored):
            order.append("rehydrate")
            return await real_rehydrate(stored)

        async def _spy_cycle(*a, **k):
            order.append("cycle")
        coord._rehydrate_arrester_state = _spy_rehydrate
        coord._async_decision_cycle = _spy_cycle
        await coord.async_setup()
        assert order[:2] == ["rehydrate", "cycle"], order
        assert ZONE in coord._override_arrester._immune_holds
    finally:
        StubBus.async_listen = _orig


# ---- D-P1a TAO ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_tao_restore_within_window_keeps_on_and_s1_refuses(mods):
    now = H.local_now()
    stored = {"__tao_state": {
        "started_ts": (now - timedelta(hours=1)).isoformat(),
        "expires_at": (now + timedelta(hours=5)).isoformat(),
    }}
    coord, hass = await _restart_into(mods, stored)
    arr = coord._override_arrester
    assert arr._temp_arrester_override_active is True
    assert arr._temp_arrester_override_started_ts is not None
    assert (now - arr._temp_arrester_override_started_ts).total_seconds() > 3500
    assert arr._corrective_writes_suppressed(ZONE) is True
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert H.preset_writes(hass, ENT) == []
    led = hass.data[mods["const"].DOMAIN]["activity_logger"]
    assert led.actions("preset_change_deferred")[0]["details"]["reason"] == "person_protected_hold"
    rows = _tao_rows(hass, mods)
    assert len(rows) == 1 and '"decision": "restore_on"' in rows[0]["details_json"]


@pytest.mark.asyncio
async def test_tao_restore_after_window_turns_off_and_s1_reclaims(mods):
    now = H.local_now()
    stored = {"__tao_state": {
        "started_ts": (now - timedelta(hours=7)).isoformat(),
        "expires_at": (now - timedelta(hours=1)).isoformat(),
    }}
    coord, hass = await _restart_into(mods, stored)
    assert coord._override_arrester._temp_arrester_override_active is False
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1
    assert '"decision": "restore_off_expired"' in _tao_rows(hass, mods)[0]["details_json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, {}, {"__tao_state": {}},
                                    {"__tao_state": {"started_ts": None, "expires_at": None}}])
async def test_tao_restore_no_persisted_state(mods, stored):
    coord, hass = await _restart_into(mods, stored)
    assert coord._override_arrester._temp_arrester_override_active is False
    assert '"decision": "no_persisted_state"' in _tao_rows(hass, mods)[0]["details_json"]


@pytest.mark.asyncio
async def test_tao_restore_boundary_one_second(mods):
    now = H.local_now()
    for delta_s, expect in ((+1, True), (-1, False)):
        stored = {"__tao_state": {
            "started_ts": (now - timedelta(hours=5)).isoformat(),
            "expires_at": (now + timedelta(seconds=delta_s)).isoformat(),
        }}
        coord, hass = await _restart_into(mods, stored)
        assert coord._override_arrester._temp_arrester_override_active is expect


@pytest.mark.asyncio
async def test_tao_persistence_write_on_on(mods):
    coord, hass = _coord_with_store(mods)
    arr = coord._override_arrester
    arr.set_temp_arrester_override(True)
    await H.drain(hass)
    from homeassistant.util import dt as dt_util
    st = coord._zone_state_store.saves[-1]["__tao_state"]
    started = dt_util.parse_datetime(st["started_ts"])
    expires = dt_util.parse_datetime(st["expires_at"])
    assert started == arr._temp_arrester_override_started_ts
    assert (expires - started).total_seconds() == 21600  # 6 h, hardcoded


@pytest.mark.asyncio
async def test_tao_persistence_clear_on_off(mods):
    coord, hass = _coord_with_store(mods)
    arr = coord._override_arrester
    arr.set_temp_arrester_override(True)
    arr.set_temp_arrester_override(False)
    await H.drain(hass)
    assert coord._zone_state_store.saves[-1]["__tao_state"] == {"started_ts": None, "expires_at": None}


@pytest.mark.asyncio
async def test_tao_persistence_clear_on_sunset(mods):
    coord, hass = _coord_with_store(mods)
    arr = coord._override_arrester
    arr.set_temp_arrester_override(True)
    arr._temp_arrester_override_started_ts = H.local_now() - timedelta(seconds=21601)
    assert arr.sunset_temp_arrester_override("max_age_or_boundary") is True
    await H.drain(hass)
    assert coord._zone_state_store.saves[-1]["__tao_state"] == {"started_ts": None, "expires_at": None}


def test_tao_max_window_uses_hvac_const(mods):
    """`expires_at - started_ts` equals COMFORT_OVERRIDE_MAX_S (the 6 h TAO
    ceiling at hvac_const.py; the plan names it HVAC_ARRESTER_OVERRIDE_MAX_S)."""
    coord, hass = _coord_with_store(mods)
    arr = coord._override_arrester
    arr.set_temp_arrester_override(True)
    from homeassistant.util import dt as dt_util
    st = arr.export_tao_state()
    secs = (dt_util.parse_datetime(st["expires_at"]) - dt_util.parse_datetime(st["started_ts"])).total_seconds()
    assert secs == mods["hvac_const"].COMFORT_OVERRIDE_MAX_S == 21600


@pytest.mark.asyncio
async def test_tao_restore_is_atomic_switch_signal_and_internals(mods):
    """The coordinator channel sets the ARRESTER internals (what gate (a/b)
    reads) and fires the switch-UI dispatcher signal in one step."""
    from homeassistant.helpers import dispatcher as _d
    fired: list = []
    now = H.local_now()
    stored = {"__tao_state": {
        "started_ts": (now - timedelta(minutes=10)).isoformat(),
        "expires_at": (now + timedelta(hours=5)).isoformat(),
    }}
    coord, hass = _coord_with_store(mods, stored)
    orig = mods["hvac_override"].async_dispatcher_send
    mods["hvac_override"].async_dispatcher_send = lambda h, sig, *a: fired.append(sig)
    try:
        await coord._rehydrate_arrester_state(stored)
    finally:
        mods["hvac_override"].async_dispatcher_send = orig
    assert coord._override_arrester._temp_arrester_override_active is True
    assert mods["hvac_const"].SIGNAL_HVAC_TEMP_ARRESTER_OVERRIDE_UPDATE in fired


# ---- snapshot builder carries every side-key -----------------------------------


@pytest.mark.asyncio
async def test_snapshot_builder_carries_all_side_keys(mods):
    coord, hass = _coord_with_store(mods)
    coord._person_zone_map = {"person.x": [ZONE]}
    snap = coord._build_zone_state_snapshot()
    for k in ("__person_zone_map", "__short_cycles_today", "__immune_holds", "__tao_state"):
        assert k in snap
    assert snap["__person_zone_map"] == {"person.x": [ZONE]}


# ---- restart drills (config extremes) -------------------------------------------


@pytest.mark.asyncio
async def test_restart_mid_nudge_reclaims_on_first_tick(mods):
    """NUDGE rows are cleared by the boot audit and the restore timer is
    RAM-only: after a restart there is no gate (e) signal -> S1 reclaims."""
    coord, hass = await _restart_into(mods, {})
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1


@pytest.mark.asyncio
async def test_restart_mid_compromise_row_rehydrated_defers(mods):
    """COMPROMISE rows ARE rehydrated by the boot audit -> gate (e) holds
    for the row's remaining window even though the timer is gone."""
    coord, hass = await _restart_into(mods, {})
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=900)
    await coord._apply_house_state_presets()
    await H.drain(hass)
    assert H.preset_writes(hass, ENT) == []
    ex._test_clear_leases()
