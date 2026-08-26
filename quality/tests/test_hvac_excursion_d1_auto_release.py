"""D1-only auto-release sweep + stale-boot BANKING release + HIGH-1 skip.

Cycle: HVAC-EXCURSION-D1-ONLY (2026-08-26). Scope is D1 alone. D2/D3/D4
are parked; nothing here exercises D3 recovery or D4 OFF_PHASE_CEILING.

Test authority (C-4 / C-8 anchors):

* HIGH-1 skip tests **discriminate**: they bind a coord with a
  resolvable ``climate_entity`` AND spy ``emit_set_preset_mode``, so
  ``emit_called == 0`` can only come from the ``pre_preset in (None,
  "", "manual")`` skip branch — NOT from the no-entity-resolvable
  fallback (which ALSO yields no emit). Removing the skip branch turns
  these tests RED.
* B3 re-entrancy: dropping the ``_sweep_running`` guard turns
  ``test_reentrant_sweep_is_no_op_while_prior_pass_running`` RED.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

_this_dir = os.path.dirname(__file__)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
_ex = _mods["hvac_excursion"]
_sp = sys.modules[
    "custom_components.universal_room_automation."
    "domain_coordinators.hvac_setpoint"
]
_ORIG_EMIT = _sp.emit_set_preset_mode


def teardown_function(_):
    _sp.emit_set_preset_mode = _ORIG_EMIT


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _FakeDB:
    def __init__(self):
        self.events: list[dict] = []
        self.rows: list[dict] = []

    async def save_excursion_row(self, row):
        self.rows.append(dict(row))

    async def clear_excursion_row(self, zone_id):
        self.rows = [r for r in self.rows if r.get("zone_id") != zone_id]

    async def log_excursion_event(self, **kwargs):
        self.events.append(kwargs)

    async def get_all_excursion_rows(self):
        return list(self.rows)


def _fake_coord_with_zone(zone_id: str, entity_id: str):
    """Coord whose ``_zone_manager.zones[zone_id].climate_entity`` resolves —
    the load-bearing rig for the HIGH-1 discrimination tests."""
    zone = MagicMock()
    zone.climate_entity = entity_id
    zm = MagicMock()
    zm.zones = {zone_id: zone}
    coord = MagicMock()
    coord._zone_manager = zm
    coord.hass = MagicMock()
    return coord


def _fake_hass(entity_id: str, preset: str = "auto",
               low: float = 70.0, high: float = 76.0):
    hass = MagicMock()
    st = MagicMock()
    st.attributes = {
        "preset_mode": preset,
        "target_temp_low": low,
        "target_temp_high": high,
    }
    hass.states = MagicMock()
    hass.states.get = lambda eid: st if eid == entity_id else None
    return hass


def setup_function(_):
    _ex._test_clear_leases()
    _ex._sweep_running = False


def _install_spy():
    spy = AsyncMock(return_value=True)
    _sp.emit_set_preset_mode = spy
    return spy


# ---------------------------------------------------------------------------
# Sweep — lease-expiry writes ended event
# ---------------------------------------------------------------------------


def test_sweep_releases_expired_banking_row_writes_ended_event():
    db = _FakeDB()
    hass = _fake_hass("climate.z1")
    _ex._test_bind(hass=hass, db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")
    spy = _install_spy()

    _ex._test_seed_row(
        zone_id="zone_1",
        kind=_ex.EXCURSION_KIND.BANKING,
        duration_s=1,
        started_ts=_ex._now() - 3600,
        pre_preset="home_day",
        site="test_seed",
    )
    # Use direct _rows check: _test_has_row reaps stale rows as a
    # side-effect (via _row_present_and_fresh), which would swallow our
    # fixture before the sweep gets to it.
    assert "zone_1" in _ex._rows

    released = _run(_ex._auto_release_sweep(coord=coord))
    assert released == 1
    assert "zone_1" not in _ex._rows

    ended = [e for e in db.events if e["kind"] == "banking"]
    assert len(ended) == 1
    assert ended[0]["trigger"] == "lease_expiry"
    assert ended[0]["preset_after"] == "home_day"
    assert ended[0]["restore_ok"] is True

    assert spy.await_count == 1
    args, kwargs = spy.call_args
    assert args[1] == "climate.z1"
    assert args[2] == "home_day"


def test_sweep_no_op_when_no_rows_expired():
    db = _FakeDB()
    _ex._test_bind(hass=_fake_hass("climate.z1"), db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")
    _install_spy()

    _ex._test_seed_row(
        zone_id="zone_1",
        kind=_ex.EXCURSION_KIND.BANKING,
        duration_s=3600,
        pre_preset="home_day",
    )
    released = _run(_ex._auto_release_sweep(coord=coord))
    assert released == 0
    assert _ex._test_has_row("zone_1")
    assert db.events == []


# ---------------------------------------------------------------------------
# HIGH-1 pre_preset skip — DISCRIMINATING (C-4 fix)
# ---------------------------------------------------------------------------


def _seed_expired_banking(pre_preset):
    return _ex._test_seed_row(
        zone_id="zone_1",
        kind=_ex.EXCURSION_KIND.BANKING,
        duration_s=1,
        started_ts=_ex._now() - 3600,
        pre_preset=pre_preset,
        site="test_seed",
    )


def _run_sweep_with_spy(pre_preset):
    db = _FakeDB()
    hass = _fake_hass("climate.z1")
    _ex._test_bind(hass=hass, db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")
    spy = _install_spy()
    _seed_expired_banking(pre_preset)
    released = _run(_ex._auto_release_sweep(coord=coord))
    return released, db, spy


def test_auto_return_skips_preset_when_pre_preset_manual():
    """HIGH-1: pre_preset == 'manual' -> no preset write, restore_ok=None.

    Load-bearing discriminator: entity IS resolvable, coord IS
    provided. The ONLY reason emit is skipped is the HIGH-1 branch.
    """
    released, db, spy = _run_sweep_with_spy("manual")
    assert released == 1
    assert spy.await_count == 0  # RED if HIGH-1 skip removed
    assert len(db.events) == 1
    assert db.events[0]["restore_ok"] is None
    assert db.events[0]["preset_after"] is None
    assert db.events[0]["trigger"] == "lease_expiry"


def test_auto_return_skips_preset_when_pre_preset_none():
    released, db, spy = _run_sweep_with_spy(None)
    assert released == 1
    assert spy.await_count == 0
    assert db.events[0]["restore_ok"] is None
    assert db.events[0]["preset_after"] is None


def test_auto_return_skips_preset_when_pre_preset_empty():
    released, db, spy = _run_sweep_with_spy("")
    assert released == 1
    assert spy.await_count == 0
    assert db.events[0]["restore_ok"] is None
    assert db.events[0]["preset_after"] is None


def test_auto_return_writes_preset_when_pre_preset_legitimate():
    """Discriminator vs a global skip — a legit pre_preset MUST emit."""
    released, db, spy = _run_sweep_with_spy("home_day")
    assert released == 1
    assert spy.await_count == 1
    assert db.events[0]["restore_ok"] is True
    assert db.events[0]["preset_after"] == "home_day"


# ---------------------------------------------------------------------------
# B3 re-entrancy + B6 torn-down-coord guards
# ---------------------------------------------------------------------------


def test_reentrant_sweep_is_no_op_while_prior_pass_running():
    """Tick fires while a prior sweep awaits a slow (Carrier ~60s)
    preset emit -> the re-entrant tick must NOT re-collect the same
    row. Removing ``_sweep_running`` turns this RED (double emit +
    released2 == 1)."""
    db = _FakeDB()
    _ex._test_bind(hass=_fake_hass("climate.z1"), db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")

    gate = asyncio.Event()
    call_count = {"n": 0}

    async def _slow_emit(*args, **kwargs):
        call_count["n"] += 1
        await gate.wait()
        return True

    _sp.emit_set_preset_mode = _slow_emit
    _seed_expired_banking("home_day")

    async def _scenario():
        t1 = asyncio.create_task(_ex._auto_release_sweep(coord=coord))
        await asyncio.sleep(0)  # let sweep 1 hit the await
        # asyncio.wait_for turns "sweep 2 blocks on the same emit" (the
        # neutered-guard failure mode) into a clean TimeoutError instead
        # of a suite-wide hang. With the guard intact, sweep 2 returns 0
        # immediately.
        released2 = await asyncio.wait_for(
            _ex._auto_release_sweep(coord=coord), timeout=1.0,
        )
        assert released2 == 0
        gate.set()
        released1 = await t1
        return released1

    try:
        released1 = _run(_scenario())
    except asyncio.TimeoutError:
        # Neutered guard: sweep 2 got stuck waiting on the same emit.
        gate.set()
        raise AssertionError(
            "re-entrant sweep blocked on the same emit — B3 guard missing"
        )
    assert released1 == 1
    assert call_count["n"] == 1  # NOT double-emitted


def test_sweep_skips_when_coord_hass_gone():
    """B6: torn-down coord (hass=None) -> sweep is a no-op; row NOT
    released. Removing the torn-down guard turns this RED."""
    db = _FakeDB()
    _ex._test_bind(hass=None, db=db)
    coord = MagicMock()
    coord.hass = None
    _seed_expired_banking("home_day")
    released = _run(_ex._auto_release_sweep(coord=coord))
    assert released == 0
    # Row still present (torn-down guard prevented reap). Use direct
    # _rows peek — _test_has_row would reap it as a probe side-effect.
    assert "zone_1" in _ex._rows
    assert db.events == []


# ---------------------------------------------------------------------------
# Stale-boot BANKING release
# ---------------------------------------------------------------------------


def test_stale_boot_banking_release_writes_preset_and_ended_event():
    db = _FakeDB()
    db.rows.append({
        "zone_id": "zone_1",
        "excursion_id": "exc-bank-1",
        "kind": "banking",
        "started_ts": "2026-08-25T10:00:00+00:00",
        "pre_preset": "home_day",
        "pre_target_low": 70.0,
        "pre_target_high": 76.0,
        "intended_mode": "heat_cool",
        "duration_s": 900,
        "caller_site": "S11_solar_banking",
        "excursion_target_low": 70.0,
        "excursion_target_high": 74.0,
    })
    hass = _fake_hass("climate.z1")
    _ex._test_bind(hass=hass, db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")
    spy = _install_spy()

    _run(_ex.async_startup_excursion_audit(hass, coord))

    assert spy.await_count == 1
    args, _ = spy.call_args
    assert args[1] == "climate.z1"
    assert args[2] == "home_day"

    ended = [e for e in db.events if e["kind"] == "banking"]
    assert len(ended) == 1
    assert ended[0]["trigger"] == "stale_boot_release"
    assert ended[0]["preset_after"] == "home_day"
    assert not _ex._test_has_row("zone_1")


def test_stale_boot_banking_release_skips_preset_when_manual():
    db = _FakeDB()
    db.rows.append({
        "zone_id": "zone_1",
        "excursion_id": "exc-bank-2",
        "kind": "banking",
        "started_ts": "2026-08-25T10:00:00+00:00",
        "pre_preset": "manual",
        "pre_target_low": 70.0,
        "pre_target_high": 76.0,
        "intended_mode": "heat_cool",
        "duration_s": 900,
        "caller_site": "S11_solar_banking",
    })
    hass = _fake_hass("climate.z1", preset="manual")
    _ex._test_bind(hass=hass, db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")
    spy = _install_spy()

    _run(_ex.async_startup_excursion_audit(hass, coord))

    assert spy.await_count == 0  # HIGH-1 also applies on boot path
    ended = [e for e in db.events if e["kind"] == "banking"]
    assert len(ended) == 1
    assert ended[0]["trigger"] == "stale_boot_release"
    assert ended[0]["restore_ok"] is None


# ---------------------------------------------------------------------------
# _returned double-return guard
# ---------------------------------------------------------------------------


def test_natural_close_then_sweep_does_not_double_return():
    db = _FakeDB()
    _ex._test_bind(hass=_fake_hass("climate.z1"), db=db)
    coord = _fake_coord_with_zone("zone_1", "climate.z1")
    _install_spy()

    tok = _ex._test_seed_row(
        zone_id="zone_1",
        kind=_ex.EXCURSION_KIND.BANKING,
        duration_s=1,
        started_ts=_ex._now() - 3600,
        pre_preset="home_day",
    )
    _run(_ex.return_excursion(tok, trigger="natural_end",
                              preset_after="home_day", restore_ok=True))
    assert not _ex._test_has_row("zone_1")

    _ex._rows["zone_1"] = tok  # simulate a race where sweep sees stale ref
    _run(_ex._auto_release_sweep(coord=coord))

    ended = [e for e in db.events if e["kind"] == "banking"]
    assert len(ended) == 1
