"""DB-SIZE-GROWTH-1: 365-day retention for the per-room history tables.

Plan: docs/planning/PLANNING_db_retention_365d.md.

Drives the REAL ``UniversalRoomDatabase.cleanup_room_history`` against a temp
DB created by the production ``initialize()`` (production DDL, never a
hand-copied schema), through the real write worker. Time is controlled by
scoping a fake ``dt_util`` onto the database module with ``monkeypatch``
(restored after each test). All cutoffs in assertions are hardcoded literal
dates derived by hand, not recomputed by the code under test.

Also drives the shared nightly op list + rotating runner
(``nightly_maintenance.py``) that BOTH nightly paths in ``__init__.py`` call.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from custom_components.universal_room_automation import database as db_mod  # noqa: E402
from custom_components.universal_room_automation import (  # noqa: E402
    nightly_maintenance as nm,
)

UniversalRoomDatabase = db_mod.UniversalRoomDatabase

TABLES = ("environmental_data", "energy_snapshots", "occupancy_events", "room_transitions")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task

    async def _executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor_job
    return UniversalRoomDatabase(hass)


def _clock(monkeypatch, utc: datetime, local: datetime) -> None:
    """Scope a fixed clock onto database.dt_util (monkeypatch restores it)."""
    monkeypatch.setattr(
        db_mod, "dt_util",
        SimpleNamespace(utcnow=lambda: utc, now=lambda: local),
    )


async def _insert(db, table: str, timestamps: list[str]) -> None:
    import aiosqlite
    async with aiosqlite.connect(db.db_file) as conn:
        for ts in timestamps:
            if table == "room_transitions":
                await conn.execute(
                    "INSERT INTO room_transitions (person_id, from_room, to_room, timestamp, "
                    "duration_seconds, path_type) VALUES ('p', 'a', 'b', ?, 5, 'direct')", (ts,))
            elif table == "occupancy_events":
                await conn.execute(
                    "INSERT INTO occupancy_events (room_id, timestamp, event_type) "
                    "VALUES ('r', ?, 'entry')", (ts,))
            else:
                await conn.execute(
                    f"INSERT INTO {table} (room_id, timestamp) VALUES ('r', ?)", (ts,))
        await conn.commit()


async def _remaining(db, table: str) -> list[str]:
    import aiosqlite
    async with aiosqlite.connect(db.db_file) as conn:
        cur = await conn.execute(f"SELECT timestamp FROM {table} ORDER BY timestamp")
        return [r[0] for r in await cur.fetchall()]


async def _run(db, coro_factory):
    await db.initialize()
    await db.start_write_worker()
    try:
        result = await coro_factory()
        await db._write_queue.join()
        return result
    finally:
        if db._write_task is not None and not db._write_task.done():
            db._write_task.cancel()
            try:
                await db._write_task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# DAO: keep side of the cutoff, both timestamp formats, both clocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_history_prune_keeps_rows_younger_than_cutoff_both_formats(tmp_path, monkeypatch):
    """Texas evening: UTC date (11-20) is one day ahead of local (11-19).

    UTC tables: cutoff 2025-11-20 (UTC date - 365 d).
    room_transitions (local clock): cutoff 2025-11-19.
    """
    tz = timezone(timedelta(hours=-6))
    _clock(monkeypatch,
           utc=datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc),
           local=datetime(2026, 11, 19, 21, 0, tzinfo=tz))
    db = _make_db(str(tmp_path))

    async def body():
        utc_rows = ["2025-11-19T23:59:59.999999",  # delete (before UTC cutoff)
                    "2025-11-20T00:00:00",         # keep (on cutoff date)
                    "2025-11-21T08:00:00.1"]       # keep
        for t in TABLES[:3]:
            await _insert(db, t, utc_rows)
        await _insert(db, "room_transitions", [
            "2025-11-18 23:59:59.5-06:00",  # delete (before local cutoff)
            "2025-11-19 22:00:00.1-06:00",  # keep: 364 d 23 h old (UTC clock would delete it)
            "2025-11-20 00:00:01.1-06:00",  # keep
        ])
        deleted = await db.cleanup_room_history(retention_days=365)
        return deleted, {t: await _remaining(db, t) for t in TABLES}

    deleted, rem = await _run(db, body)
    for t in TABLES[:3]:
        assert rem[t] == ["2025-11-20T00:00:00", "2025-11-21T08:00:00.1"], t
    assert rem["room_transitions"] == [
        "2025-11-19 22:00:00.1-06:00", "2025-11-20 00:00:01.1-06:00"]
    assert deleted == 4


@pytest.mark.asyncio
async def test_room_history_prune_utc_tables_use_utc_date_east_of_utc(tmp_path, monkeypatch):
    """Sydney just after local midnight (plan PR-1): local date 11-20 is a day
    ahead of the UTC date 11-19. A UTC row at 2025-11-19T14:00 is younger than
    365 d (now - 365 d = 2025-11-19T13:30Z) and must be kept; a local-date
    cutoff (2025-11-20) would delete it.
    """
    tz = timezone(timedelta(hours=11))
    _clock(monkeypatch,
           utc=datetime(2026, 11, 19, 13, 30, tzinfo=timezone.utc),
           local=datetime(2026, 11, 20, 0, 30, tzinfo=tz))
    db = _make_db(str(tmp_path))

    async def body():
        for t in TABLES[:3]:
            await _insert(db, t, ["2025-11-18T23:00:00", "2025-11-19T14:00:00"])
        await db.cleanup_room_history(retention_days=365)
        return {t: await _remaining(db, t) for t in TABLES[:3]}

    rem = await _run(db, body)
    for t in TABLES[:3]:
        assert rem[t] == ["2025-11-19T14:00:00"], t


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.asyncio
async def test_room_history_prune_covers_each_table(tmp_path, monkeypatch, table):
    """Each of the four tables is pruned (drop one from the table tuple -> red)."""
    _clock(monkeypatch,
           utc=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
           local=datetime(2026, 12, 1, 6, 0, tzinfo=timezone(timedelta(hours=-6))))
    db = _make_db(str(tmp_path))
    old = "2025-01-01 00:00:00-06:00" if table == "room_transitions" else "2025-01-01T00:00:00"
    new = "2026-11-30 00:00:00-06:00" if table == "room_transitions" else "2026-11-30T00:00:00"

    async def body():
        await _insert(db, table, [old, new])
        n = await db.cleanup_room_history(retention_days=365)
        return n, await _remaining(db, table)

    n, rem = await _run(db, body)
    assert rem == [new]
    assert n == 1


@pytest.mark.parametrize("days", [0, -1])
@pytest.mark.asyncio
async def test_room_history_prune_zero_disables(tmp_path, monkeypatch, days):
    _clock(monkeypatch,
           utc=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
           local=datetime(2026, 12, 1, 6, 0, tzinfo=timezone(timedelta(hours=-6))))
    db = _make_db(str(tmp_path))

    async def body():
        await _insert(db, "environmental_data", ["2020-01-01T00:00:00", "2026-11-30T00:00:00"])
        n = await db.cleanup_room_history(retention_days=days)
        return n, await _remaining(db, "environmental_data")

    n, rem = await _run(db, body)
    assert n == 0
    assert rem == ["2020-01-01T00:00:00", "2026-11-30T00:00:00"]


@pytest.mark.asyncio
async def test_room_history_prune_batch_cap(tmp_path, monkeypatch):
    """batch_size=2, max_batches=3 -> 6 rows per call; remainder next call."""
    _clock(monkeypatch,
           utc=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
           local=datetime(2026, 12, 1, 6, 0, tzinfo=timezone(timedelta(hours=-6))))
    monkeypatch.setattr(db_mod.asyncio, "sleep", _no_sleep)
    db = _make_db(str(tmp_path))

    async def body():
        await _insert(db, "environmental_data",
                      [f"2025-01-{d:02d}T00:00:00" for d in range(1, 11)])
        first = await db.cleanup_room_history(retention_days=365, batch_size=2, max_batches=3)
        left_after_first = len(await _remaining(db, "environmental_data"))
        second = await db.cleanup_room_history(retention_days=365, batch_size=2, max_batches=3)
        return first, left_after_first, second, await _remaining(db, "environmental_data")

    first, left, second, rem = await _run(db, body)
    assert first == 6
    assert left == 4
    assert second == 4
    assert rem == []


@pytest.mark.asyncio
async def test_room_history_prune_default_cap_is_module_constant(tmp_path, monkeypatch):
    """max_batches=None reads ROOM_HISTORY_PRUNE_MAX_BATCHES from const."""
    # Patch the const module the DAO's lazy ``from .const import`` resolves
    # (sys.modules entry; another test file may have swapped it).
    const = sys.modules[db_mod.__package__ + ".const"]
    _clock(monkeypatch,
           utc=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
           local=datetime(2026, 12, 1, 6, 0, tzinfo=timezone(timedelta(hours=-6))))
    monkeypatch.setattr(const, "ROOM_HISTORY_PRUNE_MAX_BATCHES", 2, raising=False)
    monkeypatch.setattr(db_mod.asyncio, "sleep", _no_sleep)
    db = _make_db(str(tmp_path))

    async def body():
        await _insert(db, "environmental_data",
                      [f"2025-01-{d:02d}T00:00:00" for d in range(1, 11)])
        return await db.cleanup_room_history(retention_days=365, batch_size=3)

    assert await _run(db, body) == 6


async def _no_sleep(_s):
    return None


# ---------------------------------------------------------------------------
# Shared nightly op list + runner (both __init__ nightly paths call it)
# ---------------------------------------------------------------------------


def test_nightly_ops_include_room_history_primary_and_deferred():
    """One list serves both paths; it carries the room_history op at 365 d."""
    ops = nm.nightly_cleanup_ops()
    assert ("room_history", "cleanup_room_history", {"retention_days": 365}) in ops
    assert sum(1 for o in ops if o[1] == "cleanup_room_history") == 1


def test_retention_constant_values():
    from custom_components.universal_room_automation import const
    assert const.RETENTION_ROOM_HISTORY_DAYS == 365
    assert const.ROOM_HISTORY_PRUNE_MAX_BATCHES == 100


class _RecordingDB:
    def __init__(self, fail: str | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._fail = fail

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _m(**kw):
            self.calls.append((name, kw))
            if name == self._fail:
                raise RuntimeError("boom")
        return _m


@pytest.mark.asyncio
async def test_run_nightly_cleanup_invokes_room_history_with_365():
    db = _RecordingDB()
    data: dict = {}
    await nm.run_nightly_cleanup(data, db, sleep=_no_sleep)
    assert ("cleanup_room_history", {"retention_days": 365}) in db.calls
    assert len(db.calls) == len(nm.nightly_cleanup_ops())
    assert data["_nightly_start_idx"] == 1


@pytest.mark.asyncio
async def test_run_nightly_cleanup_rotates_and_survives_failure():
    ops = nm.nightly_cleanup_ops()
    db = _RecordingDB(fail=ops[0][1])
    data = {"_nightly_start_idx": len(ops) - 1}
    await nm.run_nightly_cleanup(data, db, sleep=_no_sleep)
    # starts at the last op, wraps, and keeps going after the failing first op
    assert db.calls[0][0] == ops[-1][1]
    assert len(db.calls) == len(ops)
    assert data["_nightly_start_idx"] == 0


@pytest.mark.asyncio
async def test_run_nightly_cleanup_budget_stops_between_ops():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = iter([t0, t0, t0 + timedelta(seconds=299), t0 + timedelta(seconds=301)]
                 + [t0 + timedelta(seconds=400)] * 50)
    db = _RecordingDB()
    await nm.run_nightly_cleanup({}, db, now_fn=lambda: next(times), sleep=_no_sleep)
    assert len(db.calls) == 2
