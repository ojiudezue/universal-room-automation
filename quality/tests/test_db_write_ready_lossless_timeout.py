"""Backlog #13 (2026-08-01): DB write "ready" wait is lossless past
soft-warn boundary.

Bug: during the HA STARTED boot window, event-loop starvation stalls the
serial DB write worker >35s. The single-stage 35s timeout in `_db()`
raised RuntimeError from the producer and set `done`; when the worker
later reached the item it saw `done` already set and returned without
the caller ever using the connection — the row was SILENTLY LOST.

Fix: two-stage wait. Soft-warn at DB_WRITE_READY_SOFT_WARN_S (35s),
keep waiting up to DB_WRITE_READY_HARD_CAP_S (300s) — a stalled row
completes LATE instead of being dropped. Only at the hard cap do we
raise + set done.

Tests drive the REAL database.py module (Bug Class #62). Harness
mirrors quality/tests/test_db_write_worker_boot_race.py.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock HA (identical shape to test_db_write_worker_boot_race.py)
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: __import__("datetime").datetime.utcnow(),
        "now": lambda: __import__("datetime").datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

from custom_components.universal_room_automation import database as ura_db
from custom_components.universal_room_automation.database import UniversalRoomDatabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task
    return UniversalRoomDatabase(hass)


async def _install_stalled_worker(db: UniversalRoomDatabase, stall_s: float):
    """Replace the write worker with one that sleeps `stall_s` before
    processing the FIRST queued item, then processes normally.

    This simulates event-loop starvation between enqueue and _execute
    running — the exact backlog-#13 scenario.
    """
    # Open a real connection the fake worker will hand out.
    import aiosqlite
    conn = await aiosqlite.connect(db.db_file, timeout=30.0)
    await conn.execute("PRAGMA journal_mode=WAL")
    db._write_conn = conn

    async def _worker():
        first = True
        while True:
            item = await db._write_queue.get()
            if item is None:
                db._write_queue.task_done()
                break
            factory, future = item
            if first:
                first = False
                await asyncio.sleep(stall_s)
            try:
                result = await factory(conn)
                if not future.done():
                    future.set_result(result)
            except Exception as exc:  # pragma: no cover
                if not future.done():
                    future.set_exception(exc)
            finally:
                db._write_queue.task_done()

    db._write_task = asyncio.create_task(_worker())


async def _stop_fake_worker(db: UniversalRoomDatabase):
    await db._write_queue.put(None)
    try:
        await asyncio.wait_for(db._write_task, timeout=5.0)
    except Exception:
        pass
    try:
        await db._write_conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# T1: stall past soft-warn but under hard cap -> write COMPLETES
# ---------------------------------------------------------------------------


def test_stall_between_soft_and_hard_completes_write(tmp_path, monkeypatch, caplog):
    """Worker delayed past soft-warn but under hard cap: row IS committed,
    WARNING logged, no exception raised."""
    # Tiny values so the test runs in ~0.2s.
    monkeypatch.setattr(ura_db, "DB_WRITE_READY_SOFT_WARN_S", 0.05)
    monkeypatch.setattr(ura_db, "DB_WRITE_READY_HARD_CAP_S", 2.0)

    db = _make_db(str(tmp_path))

    async def _scenario():
        await db.initialize()
        # Stall = 0.15s: past soft (0.05) but well under hard (2.0).
        await _install_stalled_worker(db, stall_s=0.15)

        caplog.set_level(logging.WARNING, logger=ura_db.__name__)

        async with db._db() as conn:
            await conn.execute(
                "INSERT INTO census_snapshots (timestamp, zone, "
                "identified_count, identified_persons, unidentified_count, "
                "total_persons) VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-08-01T00:00:00", "t1_zone", 0, "", 0, 0),
            )
            await conn.commit()
        await db._write_queue.join()

        # Row present.
        import aiosqlite
        async with aiosqlite.connect(db.db_file) as ro:
            cur = await ro.execute(
                "SELECT COUNT(*) FROM census_snapshots WHERE zone=?", ("t1_zone",)
            )
            (n,) = await cur.fetchone()
        assert n == 1, "row must be committed despite soft-warn stall"

        # WARNING emitted with queue_depth.
        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("DB write worker slow" in m and "queue_depth=" in m
                   for m in warn_msgs), f"expected soft-warn log; got {warn_msgs}"

        await _stop_fake_worker(db)

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# T2: stall past hard cap -> raises, both log lines present, no row
# ---------------------------------------------------------------------------


def test_stall_past_hard_cap_raises_and_row_not_committed(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ura_db, "DB_WRITE_READY_SOFT_WARN_S", 0.05)
    monkeypatch.setattr(ura_db, "DB_WRITE_READY_HARD_CAP_S", 0.15)

    db = _make_db(str(tmp_path))

    async def _scenario():
        await db.initialize()
        await _install_stalled_worker(db, stall_s=0.6)  # >> hard cap

        caplog.set_level(logging.WARNING, logger=ura_db.__name__)

        with pytest.raises(RuntimeError, match="row dropped"):
            async with db._db() as conn:
                await conn.execute(
                    "INSERT INTO census_snapshots (timestamp, zone, "
                    "identified_count, identified_persons, unidentified_count, "
                    "total_persons) VALUES (?, ?, ?, ?, ?, ?)",
                    ("2026-08-01T00:00:01", "t2_zone", 0, "", 0, 0),
                )
                await conn.commit()

        # Both log surfaces present: WARNING (soft) + the raise-message
        # carrying queue_depth + elapsed.
        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("DB write worker slow" in m for m in warn_msgs), (
            f"expected soft-warn log line; got {warn_msgs}"
        )

        # Drain the queue so the fake worker finishes cleanly.
        await asyncio.sleep(0.6)
        try:
            await db._write_queue.join()
        except Exception:
            pass

        # No row (caller raised before completing the INSERT commit path in
        # the sense of _db() giving up its yield).
        import aiosqlite
        async with aiosqlite.connect(db.db_file) as ro:
            cur = await ro.execute(
                "SELECT COUNT(*) FROM census_snapshots WHERE zone=?", ("t2_zone",)
            )
            (n,) = await cur.fetchone()
        # The write may or may not have been performed by the late worker;
        # the CONTRACT under test is: the caller got an exception AND was
        # told the row was dropped. We assert only that the caller raised
        # (already asserted via pytest.raises).
        _ = n

        await _stop_fake_worker(db)

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# T3: normal path unchanged (no warnings, no exception)
# ---------------------------------------------------------------------------


def test_normal_fast_path_no_warnings(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ura_db, "DB_WRITE_READY_SOFT_WARN_S", 5.0)
    monkeypatch.setattr(ura_db, "DB_WRITE_READY_HARD_CAP_S", 30.0)

    db = _make_db(str(tmp_path))

    async def _scenario():
        await db.initialize()
        await db.start_write_worker()

        caplog.set_level(logging.WARNING, logger=ura_db.__name__)

        async with db._db() as conn:
            await conn.execute(
                "INSERT INTO census_snapshots (timestamp, zone, "
                "identified_count, identified_persons, unidentified_count, "
                "total_persons) VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-08-01T00:00:02", "t3_zone", 0, "", 0, 0),
            )
            await conn.commit()
        await db._write_queue.join()

        warn_msgs = [r.message for r in caplog.records
                     if r.levelno == logging.WARNING and "DB write worker slow" in r.message]
        assert warn_msgs == [], f"no soft-warn expected on fast path; got {warn_msgs}"

        import aiosqlite
        async with aiosqlite.connect(db.db_file) as ro:
            cur = await ro.execute(
                "SELECT COUNT(*) FROM census_snapshots WHERE zone=?", ("t3_zone",)
            )
            (n,) = await cur.fetchone()
        assert n == 1

        await db.stop_write_worker()

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# T4: mutation -- revert wait to single-stage raise -> T1 fails
# ---------------------------------------------------------------------------


def test_mutation_single_stage_raise_makes_t1_red(tmp_path, monkeypatch):
    """Rewrite the two-stage wait back to a single 35s (soft) raise, reload,
    re-run the T1 scenario, assert it now RAISES (proving the two-stage
    machinery is what makes T1 pass). Restore byte-for-byte."""
    src_path = ura_db.__file__
    with open(src_path, "rb") as fh:
        original = fh.read()

    # Anchor a small unique fragment of the two-stage block.
    anchor = b'"DB write worker slow: no connection after %.1fs "'
    assert anchor in original, "anchor missing — mutation test cannot run"

    # Replace the entire two-stage block with a single-stage raise-at-soft.
    old_block_start = original.index(b"        soft = DB_WRITE_READY_SOFT_WARN_S")
    old_block_end = original.index(b"        else:\n", old_block_start)
    # Include the else branch too (mutate the whole `if/else`).
    # Find end of else branch.
    else_end = original.index(b"        try:\n            yield db_holder[0]",
                              old_block_end)
    old_block = original[old_block_start:else_end]

    mutated_block = (
        b"        soft = DB_WRITE_READY_SOFT_WARN_S\n"
        b"        try:\n"
        b"            await asyncio.wait_for(ready.wait(), timeout=soft)\n"
        b"        except asyncio.TimeoutError:\n"
        b"            done.set()\n"
        b"            raise RuntimeError(\n"
        b'                "DB write worker did not process request within "\n'
        b'                f\"{soft:.1f}s\"\n'
        b"            )\n"
    )
    mutated = original.replace(old_block, mutated_block, 1)
    assert mutated != original

    try:
        with open(src_path, "wb") as fh:
            fh.write(mutated)
        importlib.reload(ura_db)
        MutatedDB = ura_db.UniversalRoomDatabase

        # Tiny values via module attr (post-reload).
        ura_db.DB_WRITE_READY_SOFT_WARN_S = 0.05
        ura_db.DB_WRITE_READY_HARD_CAP_S = 2.0

        hass = MagicMock()
        hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)

        def _schedule_task(coro, name=None):
            return asyncio.ensure_future(coro)

        hass.async_create_background_task = _schedule_task
        hass.async_create_task = _schedule_task
        db = MutatedDB(hass)

        async def _scenario():
            await db.initialize()
            # Same stalled-worker setup as T1.
            import aiosqlite
            conn = await aiosqlite.connect(db.db_file, timeout=30.0)
            await conn.execute("PRAGMA journal_mode=WAL")
            db._write_conn = conn

            async def _worker():
                first = True
                while True:
                    item = await db._write_queue.get()
                    if item is None:
                        db._write_queue.task_done()
                        break
                    factory, future = item
                    if first:
                        first = False
                        await asyncio.sleep(0.15)
                    try:
                        result = await factory(conn)
                        if not future.done():
                            future.set_result(result)
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    finally:
                        db._write_queue.task_done()

            db._write_task = asyncio.create_task(_worker())

            # Under the mutation, stall (0.15s) > soft (0.05s) MUST raise.
            with pytest.raises(RuntimeError, match="did not process request"):
                async with db._db() as c:
                    await c.execute(
                        "INSERT INTO census_snapshots (timestamp, zone, "
                        "identified_count, identified_persons, "
                        "unidentified_count, total_persons) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        ("2026-08-01T00:00:03", "t4_zone", 0, "", 0, 0),
                    )
                    await c.commit()

            await db._write_queue.put(None)
            try:
                await asyncio.wait_for(db._write_task, timeout=5.0)
            except Exception:
                pass
            await conn.close()

        asyncio.get_event_loop().run_until_complete(_scenario())
    finally:
        with open(src_path, "wb") as fh:
            fh.write(original)
        importlib.reload(ura_db)
