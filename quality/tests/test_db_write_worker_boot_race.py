"""Tier-1 regression test: DB write worker boot-race.

Bug: at HA boot, URA coordinators can emit persist calls (census /
energy / environmental / occupancy) BEFORE UniversalRoomDatabase's
async write worker has been started via start_write_worker(). Pre-fix
behavior (v3.22.9): _db() raised RuntimeError("DB write worker not
running — call start_write_worker() first") and the row was DROPPED.

Fix (v5.16.2, structural): the pre-start submission is lossless — the
factory is enqueued onto the same _write_queue and drained when the
worker starts. Errors are demoted to DEBUG.

These tests drive the REAL database.py module (mocks are only for the
HA plumbing that database.py imports at module load).

Mutation guard: if the buffer is removed (raise reinstated), the
``test_pre_start_submit_buffers_and_drains_on_worker_start`` test must
FAIL. The mutation is EXECUTED in
``test_mutation_remove_buffering_makes_test_red`` by patch-editing the
production source in-place, re-importing the module, running the test
factory, then restoring the file byte-for-byte.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import sys
import tempfile
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock HA before importing URA code (same shape as test_database_resilience.py)
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


async def _submit_write(db: UniversalRoomDatabase, sql: str, params: tuple) -> None:
    """Perform one write via db._db() (the same context manager every DAO uses)."""
    async with db._db() as conn:
        await conn.execute(sql, params)
        await conn.commit()


# ---------------------------------------------------------------------------
# Real behavior test
# ---------------------------------------------------------------------------


def test_pre_start_submit_buffers_and_drains_on_worker_start(tmp_path):
    """A write submitted BEFORE start_write_worker() must be lossless.

    Scenario mirrors the boot race: coordinator calls a persist method that
    goes through _db() before the parent entry's start_write_worker() runs.
    Post-fix: the factory is enqueued; when the worker starts, it drains the
    queue and the row is committed.
    """
    db = _make_db(str(tmp_path))

    async def _scenario():
        # Set up the schema using a direct sqlite3 connection to avoid needing
        # the write worker for table creation.
        await db.initialize()

        # Simulate a coordinator that fires BEFORE start_write_worker():
        # kick off _db() usage as a background task, THEN start the worker.
        submit_task = asyncio.create_task(
            _submit_write(
                db,
                "INSERT INTO census_snapshots (timestamp, zone, identified_count, "
                "identified_persons, unidentified_count, total_persons) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-07-13T10:53:26", "test_zone", 0, "", 0, 0),
            )
        )
        # Give the submitter a chance to enqueue (raise would happen synchronously).
        await asyncio.sleep(0)
        # Now the worker starts — should drain the buffered write.
        await db.start_write_worker()
        # Bounded wait: submit + queue drain must complete.
        await asyncio.wait_for(submit_task, timeout=10.0)
        await db._write_queue.join()

        # Verify the row is actually persisted.
        import aiosqlite
        async with aiosqlite.connect(db.db_file) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM census_snapshots WHERE zone=?", ("test_zone",)
            )
            (count,) = await cur.fetchone()
        assert count == 1, "pre-start write should have been buffered and drained"

        # Clean up worker.
        await db.stop_write_worker()

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# EXECUTED mutation test — proves the buffer is load-bearing
# ---------------------------------------------------------------------------


def test_mutation_remove_buffering_makes_test_red(tmp_path):
    """Mutate database.py to reinstate the raise, confirm the buffer test fails.

    We rewrite database.py in-place, reload the module, run the same scenario,
    assert it raises RuntimeError (proving the buffer is what makes the good
    test pass), then restore the file byte-for-byte and reload again.
    """
    src_path = ura_db.__file__
    with open(src_path, "rb") as fh:
        original = fh.read()

    # The exact block installed by the Tier-1 fix.
    old_block = (
        b'        if self._write_task is None or self._write_task.done():\n'
        b'            _LOGGER.debug(\n'
        b'                "DB write submitted before worker start \xe2\x80\x94 buffering on queue"\n'
        b'                " (worker will drain on start)"\n'
        b'            )\n'
    )
    # The pre-fix behavior we are mutating BACK to.
    new_block = (
        b'        if self._write_task is None or self._write_task.done():\n'
        b'            raise RuntimeError(\n'
        b'                "DB write worker not running \xe2\x80\x94 call start_write_worker() first"\n'
        b'            )\n'
    )
    assert old_block in original, (
        "Fix block not found in database.py — test can't validate mutation. "
        "The Tier-1 buffer block must be present."
    )
    mutated = original.replace(old_block, new_block, 1)

    try:
        with open(src_path, "wb") as fh:
            fh.write(mutated)
        # Force reload so the mutated source is executed.
        importlib.reload(ura_db)
        MutatedDB = ura_db.UniversalRoomDatabase

        # Rebuild the DB fixture against the mutated module.
        hass = MagicMock()
        hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)

        def _schedule_task(coro, name=None):
            return asyncio.ensure_future(coro)

        hass.async_create_background_task = _schedule_task
        hass.async_create_task = _schedule_task
        db = MutatedDB(hass)

        async def _scenario():
            await db.initialize()
            # Pre-start submit MUST raise under the mutation.
            with pytest.raises(RuntimeError, match="worker not running"):
                async with db._db() as _conn:
                    pass

        asyncio.get_event_loop().run_until_complete(_scenario())
    finally:
        # Restore the file byte-for-byte and reload so subsequent tests see the fix.
        with open(src_path, "wb") as fh:
            fh.write(original)
        importlib.reload(ura_db)
