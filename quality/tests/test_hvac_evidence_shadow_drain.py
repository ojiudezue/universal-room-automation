"""HVAC evidence shadow recording — E6 drain wire-in anchors (plan rev 2 D3).

Every `update_room_conditions` caller in `HVACCoordinator` (boot in
`async_setup`, the periodic tick in `_run_decision_cycle`, the zone-scoped
fast run in `_async_zone_fast_run`) must hand the rows the producer queued
to the database. Each test drives the ENCLOSING method, with the producer
replaced by one that queues a row, and asserts the row reached the
database's batched writer. Neutering any one drain call turns exactly its
test RED. Also: no database -> rows dropped quietly; the write is never
awaited on the decision path.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402
from test_hvac_fast_occupancy_response import (  # noqa: E402
    T0, _Clock, _drain, _setup,
)


@pytest.fixture(autouse=True)
def _entity_registry_not_loaded(monkeypatch):
    from homeassistant.helpers import entity_registry as er

    def _not_loaded(hass):
        raise KeyError("entity registry not loaded on the StubHass")
    monkeypatch.setattr(er, "async_get", _not_loaded)


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


class _ShadowDB:
    """Wraps the harness FakeDB; records batched shadow writes."""

    def __init__(self, inner):
        self._inner = inner
        self.batches: list[list[dict]] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def log_hvac_evidence_shadow(self, rows):
        self.batches.append(list(rows))
        return len(rows)


def _row(tag):
    return {"timestamp": "2026-11-10T00:00:00+00:00", "row_type": "episode",
            "zone_id": "zone_1", "house_state": "guest", "details": {"tag": tag}}


def _install_db(hass, mods):
    DOMAIN = mods["const"].DOMAIN
    db = _ShadowDB(hass.data[DOMAIN]["database"])
    hass.data[DOMAIN]["database"] = db
    return db


def _queueing_producer(zm, tag):
    def _urc(*a, **k):
        zm._ev_shadow_pending_rows.append(_row(tag))
    return _urc


@pytest.mark.asyncio
async def test_tick_caller_drains(mods):
    """`_run_decision_cycle` drains after its `update_room_conditions`."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(mods)
        db = _install_db(hass, mods)
        zm = coord.zone_manager
        heavy = [
            patch.object(zm, "update_all_zones"),
            patch.object(zm, "update_room_conditions", side_effect=_queueing_producer(zm, "tick")),
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
        for p in heavy:
            p.start()
        try:
            coord._startup_audit_done = True
            await coord._run_decision_cycle()
            await _drain(hass)
        finally:
            for p in heavy:
                p.stop()
        assert [[r["details"]["tag"] for r in b] for b in db.batches] == [["tick"]]
        # grace stamped at drain time: knob 48 = 5 min in _setup -> 300 s.
        assert db.batches[0][0]["details"]["grace_s_at_close"] == 300.0
        assert zm._ev_shadow_pending_rows == []


@pytest.mark.asyncio
async def test_fast_run_caller_drains(mods):
    """`_async_zone_fast_run` drains after its zone-scoped producer call."""
    with _Clock(T0):
        coord, hass, coords, _ = _setup(
            mods, presets={"zone_1": "away", "zone_2": "home", "zone_3": "home"},
        )
        db = _install_db(hass, mods)
        zm = coord.zone_manager
        with patch.object(zm, "update_room_conditions", side_effect=_queueing_producer(zm, "fast")):
            coord._fast_path_queued.add("zone_1")
            await coord._async_zone_fast_run("zone_1", "fast_entry", edge_ts=T0)
            await _drain(hass)
        assert [[r["details"]["tag"] for r in b] for b in db.batches] == [["fast"]]
        assert zm._ev_shadow_pending_rows == []


@pytest.mark.asyncio
async def test_boot_caller_drains(mods):
    """`async_setup` drains after its initial `update_room_conditions`
    (the setup may stop later on StubHass gaps; the drain is before)."""
    coord, hass = H.make_coord(mods)
    db = _install_db(hass, mods)
    zm = coord.zone_manager

    async def _no_discover():
        return len(zm.zones)
    with patch.object(zm, "async_discover_zones", side_effect=_no_discover), \
         patch.object(zm, "update_room_conditions", side_effect=_queueing_producer(zm, "boot")):
        try:
            await asyncio.wait_for(coord.async_setup(), timeout=10.0)
        except Exception:  # noqa: BLE001 — StubHass gaps after the drain
            pass
        await _drain(hass)
    assert ["boot"] in [[r["details"]["tag"] for r in b] for b in db.batches]
    for t in getattr(hass, "_stub_tasks", []):
        if not t.done():
            t.cancel()


@pytest.mark.asyncio
async def test_no_database_drops_quietly(mods):
    coord, hass = H.make_coord(mods)
    DOMAIN = mods["const"].DOMAIN
    hass.data[DOMAIN].pop("database", None)
    zm = coord.zone_manager
    zm._ev_shadow_pending_rows.append(_row("x"))
    coord._drain_hvac_evidence_shadow_rows()             # must not raise
    assert zm._ev_shadow_pending_rows == []


@pytest.mark.asyncio
async def test_drain_is_sync_and_tracked(mods):
    """The drain never awaits: it is a plain function, schedules ONE task
    per drain (tracked on `_pending_tasks`), and skips empty queues."""
    import inspect
    coord, hass = H.make_coord(mods)
    assert not inspect.iscoroutinefunction(type(coord)._drain_hvac_evidence_shadow_rows)
    db = _install_db(hass, mods)
    zm = coord.zone_manager
    n0 = len(coord._pending_tasks)
    coord._drain_hvac_evidence_shadow_rows()             # empty: nothing
    assert len(coord._pending_tasks) == n0
    zm._ev_shadow_pending_rows.extend([_row("a"), _row("b")])
    coord._drain_hvac_evidence_shadow_rows()
    assert len(coord._pending_tasks) == n0 + 1
    await _drain(hass)
    assert [[r["details"]["tag"] for r in b] for b in db.batches] == [["a", "b"]]
