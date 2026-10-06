"""SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1 — fast-fail _db() at HA shutdown.

At HA shutdown, HA cancels background tasks after the 20s stopping stage
and never restarts them. Any DB write submitted via _db() after that would
park on _write_queue for DB_WRITE_READY_HARD_CAP_S (300s), blocking HA's
100s stop + 60s final-write stages. The fix: when hass.is_stopping is True
AND the worker is not running, raise RuntimeError immediately. The v5.16.2
buffering semantics are preserved for deliberate stop windows (VACUUM,
SPAN re-migration) where is_stopping is False.

Tests:
  (a) is_stopping=True + worker stopped -> _db() raises fast (<1s), nothing
      is left stuck on _write_queue.
  (b) is_stopping=False + worker stopped (VACUUM window) -> write buffers
      and completes once start_write_worker() runs (byte-identical to
      v5.16.2 behavior; this reuses the mechanism exercised by
      test_db_write_worker_boot_race.py).
  (c) log_census returns promptly at shutdown without emitting ERROR.
  (d) Mutation drill: neutering the is_stopping guard in _db() makes (a)
      fail (would hang on the hard-cap).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import time
import types
from unittest.mock import MagicMock

import pytest

# Reuse the HA mock plumbing from the sibling boot-race test.
from test_db_write_worker_boot_race import ura_db, UniversalRoomDatabase  # noqa: F401,E402


def _make_db(tmp_path: str, is_stopping: bool = False) -> UniversalRoomDatabase:
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)
    hass.is_stopping = is_stopping

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task
    return UniversalRoomDatabase(hass)


# ---------------------------------------------------------------------------
# (a) Fast-fail at shutdown
# ---------------------------------------------------------------------------

def test_db_fast_fails_when_hass_is_stopping_and_worker_stopped(tmp_path):
    db = _make_db(str(tmp_path), is_stopping=True)

    async def _scenario():
        await db.initialize()
        t0 = time.monotonic()
        with pytest.raises(RuntimeError, match="Home Assistant is stopping"):
            async with db._db() as _conn:
                pass
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"fast-fail took {elapsed:.2f}s (should be <1s)"
        # Nothing left on the queue — producer did NOT enqueue.
        assert db._write_queue.qsize() == 0, (
            "fast-fail path must not enqueue a factory"
        )

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# (b) Buffering preserved when NOT stopping (VACUUM window)
# ---------------------------------------------------------------------------

def test_db_still_buffers_when_not_stopping_and_worker_stopped(tmp_path):
    """Deliberate stop windows (hass.is_stopping=False) must still buffer."""
    db = _make_db(str(tmp_path), is_stopping=False)

    async def _submit(sql, params):
        async with db._db() as conn:
            await conn.execute(sql, params)
            await conn.commit()

    async def _scenario():
        await db.initialize()
        submit_task = asyncio.create_task(_submit(
            "INSERT INTO census_snapshots (timestamp, zone, identified_count, "
            "identified_persons, unidentified_count, total_persons) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-10-06T00:00:00", "vacuum_window", 0, "", 0, 0),
        ))
        await asyncio.sleep(0)
        # Buffer must be in place — queue has an item.
        assert db._write_queue.qsize() == 1
        await db.start_write_worker()
        await asyncio.wait_for(submit_task, timeout=10.0)
        await db._write_queue.join()
        await db.stop_write_worker()

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# (c) log_census: wire-in anchor via the real producer
# ---------------------------------------------------------------------------

def test_log_census_returns_promptly_at_shutdown_without_error_log(tmp_path, caplog):
    db = _make_db(str(tmp_path), is_stopping=True)

    # Build a minimal CensusZoneResult-like object matching log_census's reads.
    import datetime as _dt

    result = types.SimpleNamespace(
        identified_persons=[],
        identified_count=0,
        unidentified_count=0,
        total_persons=0,
        confidence=0.0,
        source_agreement=0.0,
        frigate_count=0,
        unifi_count=0,
        timestamp=_dt.datetime(2026, 10, 6),
    )

    async def _scenario():
        await db.initialize()
        with caplog.at_level(logging.ERROR,
                              logger="custom_components.universal_room_automation.database"):
            t0 = time.monotonic()
            await db.log_census("house", result)
            elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"log_census took {elapsed:.2f}s during shutdown"
        # No ERROR log from the DAO's except arm.
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors == [], f"unexpected ERROR records: {errors}"
        # And nothing was enqueued.
        assert db._write_queue.qsize() == 0

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# (d) Mutation drill — neuter the is_stopping guard; (a) must hang/fail.
# ---------------------------------------------------------------------------

def test_mutation_remove_is_stopping_guard_makes_fast_fail_red(tmp_path):
    """Rewrite database.py to drop the is_stopping fast-fail; (a) must fail.

    Under the mutation, _db() falls through to the v5.16.2 buffer path and
    parks on the hard-cap wait. We cap the scenario at 2s and assert it
    does NOT raise the fast-fail RuntimeError (either it times out, or it
    raises the slow hard-cap error — both are the mutation signature).
    """
    src_path = ura_db.__file__
    with open(src_path, "rb") as fh:
        original = fh.read()

    guard_marker = b'            and getattr(self.hass, "is_stopping", False) is True\n        ):\n            raise RuntimeError(\n                "DB write skipped: Home Assistant is stopping and the "\n                "write worker is closed"\n            )\n'
    assert guard_marker in original, (
        "is_stopping guard not found in database.py — mutation can't run"
    )
    # Replace guard with a no-op pass so the fast-fail path is gone.
    mutated = original.replace(
        guard_marker,
        b'            and False  # mutation: fast-fail disabled\n        ):\n            raise RuntimeError(\n                "unreachable under mutation"\n            )\n',
        1,
    )

    # Disable bytecode caching to avoid stale .pyc poisoning.
    prior_dontwrite = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with open(src_path, "wb") as fh:
            fh.write(mutated)
        # Nuke __pycache__ for database.py
        pyc_dir = os.path.join(os.path.dirname(src_path), "__pycache__")
        if os.path.isdir(pyc_dir):
            for f in os.listdir(pyc_dir):
                if f.startswith("database."):
                    try:
                        os.remove(os.path.join(pyc_dir, f))
                    except OSError:
                        pass
        importlib.reload(ura_db)
        MutatedDB = ura_db.UniversalRoomDatabase

        # Shrink the hard cap so the test completes quickly under mutation.
        prior_soft = ura_db.DB_WRITE_READY_SOFT_WARN_S
        prior_hard = ura_db.DB_WRITE_READY_HARD_CAP_S
        ura_db.DB_WRITE_READY_SOFT_WARN_S = 0.2
        ura_db.DB_WRITE_READY_HARD_CAP_S = 0.5

        hass = MagicMock()
        hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
        hass.is_stopping = True

        def _schedule_task(coro, name=None):
            return asyncio.ensure_future(coro)

        hass.async_create_background_task = _schedule_task
        hass.async_create_task = _schedule_task
        db = MutatedDB(hass)

        async def _scenario():
            await db.initialize()
            raised_fast_fail = False
            raised_slow = False
            try:
                async with db._db() as _conn:
                    pass
            except RuntimeError as exc:
                if "Home Assistant is stopping" in str(exc):
                    raised_fast_fail = True
                else:
                    raised_slow = True
            # Under the mutation we MUST NOT see the fast-fail message —
            # that's the signature the guard is doing the work.
            assert not raised_fast_fail, (
                "mutation left fast-fail behavior intact — guard not load-bearing"
            )
            # And we SHOULD see the slow hard-cap error (proving we fell
            # through to the buffer/wait path).
            assert raised_slow, "expected slow hard-cap raise under mutation"

        asyncio.get_event_loop().run_until_complete(_scenario())

        ura_db.DB_WRITE_READY_SOFT_WARN_S = prior_soft
        ura_db.DB_WRITE_READY_HARD_CAP_S = prior_hard
    finally:
        with open(src_path, "wb") as fh:
            fh.write(original)
        # Clear bytecode cache again before reload so subsequent tests see fix.
        pyc_dir = os.path.join(os.path.dirname(src_path), "__pycache__")
        if os.path.isdir(pyc_dir):
            for f in os.listdir(pyc_dir):
                if f.startswith("database."):
                    try:
                        os.remove(os.path.join(pyc_dir, f))
                    except OSError:
                        pass
        importlib.reload(ura_db)
        sys.dont_write_bytecode = prior_dontwrite
