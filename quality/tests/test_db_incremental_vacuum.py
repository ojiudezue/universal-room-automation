"""Tests for DB space-reclamation (incremental_vacuum + supervised VACUUM).

Behavioral tests run the REAL DAO methods against a temp-file DB through the
single-writer worker, plus structural tests for the button + nightly wiring.

Covers:
- incremental_vacuum: NO-OPs (returns 0) when auto_vacuum != INCREMENTAL;
  reclaims pages when it IS; bounded page count; runs through the worker path.
- vacuum_full_supervised: converts an existing NONE-mode DB with bloat to
  INCREMENTAL auto_vacuum, VACUUMs, file shrinks, integrity_check passes,
  backup file created. Concurrent-run guard.
- The Vacuum Database button registers + calls the DAO; lives on CM device;
  is NOT wired into the nightly schedule.
- incremental_vacuum is a member of the nightly _cleanup_ops list.
"""

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code (mirror resilience test boot)
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
        "async_track_state_change_event": MagicMock(),
        "async_track_time_change": MagicMock(),
        "async_track_point_in_time": MagicMock(),
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

from custom_components.universal_room_automation.database import (  # noqa: E402
    UniversalRoomDatabase,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    """Create a UniversalRoomDatabase pointing at a temp directory with a
    real-scheduling background-task shim + a real executor-job shim (so the
    file-copy backup actually runs)."""
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


async def _with_worker(db: UniversalRoomDatabase, coro_factory):
    """Start worker, run op, drain queue, stop worker."""
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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _auto_vacuum_mode(db_file: str) -> int:
    import aiosqlite
    async with aiosqlite.connect(db_file) as db:
        cur = await db.execute("PRAGMA auto_vacuum")
        row = await cur.fetchone()
        return row[0] if row else 0


async def _create_bloat(db_file: str) -> None:
    """Insert then delete a large blob payload so the DB has freed pages."""
    import aiosqlite
    async with aiosqlite.connect(db_file) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS _bloat (id INTEGER, payload BLOB)")
        blob = b"x" * 4000
        await db.executemany(
            "INSERT INTO _bloat (id, payload) VALUES (?, ?)",
            [(i, blob) for i in range(4000)],
        )
        await db.commit()
        await db.execute("DELETE FROM _bloat")
        await db.commit()
        # Force a WAL checkpoint so freed pages land on the main-DB freelist
        # (and are visible to the separate worker connection that runs
        # incremental_vacuum). Without this, WAL-resident frees may not yet be
        # reflected in PRAGMA freelist_count on another connection.
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.commit()


# ---------------------------------------------------------------------------
# incremental_vacuum
# ---------------------------------------------------------------------------


class TestIncrementalVacuum:
    def test_noop_when_auto_vacuum_not_incremental(self, tmp_path):
        """On an existing NONE-mode DB, incremental_vacuum returns 0 (no-op)."""
        db = _make_db(str(tmp_path))

        async def _do():
            # initialize() sets auto_vacuum=INCREMENTAL on a FRESH file before
            # tables — so to simulate an EXISTING NONE-mode DB we force NONE
            # first, then check the no-op path.
            import aiosqlite
            async with aiosqlite.connect(db.db_file) as conn:
                await conn.execute("PRAGMA auto_vacuum=NONE")
                await conn.execute("VACUUM")  # apply NONE
                await conn.commit()
            assert await _auto_vacuum_mode(db.db_file) == 0
            await _create_bloat(db.db_file)
            return await db.incremental_vacuum()

        reclaimed = _run(_with_worker(db, _do))
        assert reclaimed == 0

    def test_reclaims_when_incremental(self, tmp_path):
        """When auto_vacuum=INCREMENTAL and pages are freed, it reclaims > 0."""
        db = _make_db(str(tmp_path))

        async def _do():
            # Fresh DB from initialize() is already INCREMENTAL.
            assert await _auto_vacuum_mode(db.db_file) == 2
            await _create_bloat(db.db_file)
            # Freed pages now sit on the freelist; incremental_vacuum reclaims.
            return await db.incremental_vacuum()

        reclaimed = _run(_with_worker(db, _do))
        assert reclaimed > 0

    def test_bounded_page_count(self, tmp_path):
        """A caller requesting a huge page count is clamped to the cap."""
        db = _make_db(str(tmp_path))
        cap = db._INCREMENTAL_VACUUM_MAX_PAGES

        async def _do():
            await _create_bloat(db.db_file)
            # Request far more than the cap; reclamation must not exceed cap.
            return await db.incremental_vacuum(max_pages=10_000_000)

        reclaimed = _run(_with_worker(db, _do))
        assert 0 < reclaimed <= cap

    def test_runs_through_worker_path(self, tmp_path):
        """incremental_vacuum must use the single-writer _db() path.

        Source assertion: the method body opens `self._db()`, not `_db_read()`.
        """
        src = Path(
            "custom_components/universal_room_automation/database.py"
        ).read_text()
        idx = src.find("async def incremental_vacuum(")
        assert idx >= 0
        end = src.find("\n    async def ", idx + 1)
        body = src[idx:end]
        assert "self._db()" in body
        assert "self._db_read()" not in body


# ---------------------------------------------------------------------------
# vacuum_full_supervised
# ---------------------------------------------------------------------------


class TestVacuumFullSupervised:
    def test_converts_and_shrinks_and_backs_up(self, tmp_path):
        """On a NONE-mode DB with bloat: converts to INCREMENTAL, VACUUMs,
        file shrinks, integrity passes, backup created."""
        db = _make_db(str(tmp_path))

        async def _do():
            # Force NONE mode + bloat to mimic the production high-water DB.
            import aiosqlite
            async with aiosqlite.connect(db.db_file) as conn:
                await conn.execute("PRAGMA auto_vacuum=NONE")
                await conn.execute("VACUUM")
                await conn.commit()
            assert await _auto_vacuum_mode(db.db_file) == 0
            await _create_bloat(db.db_file)
            size_before = os.path.getsize(db.db_file)
            result = await db.vacuum_full_supervised()
            return result, size_before

        result, size_before = _run(_with_worker(db, _do))

        assert result["status"] == "ok"
        assert result["integrity_check"] == "ok"
        assert result["auto_vacuum_after"] == 2
        # Backup file created.
        backup = f"{db.db_file}.prevacuum.bak"
        assert os.path.exists(backup)
        assert result["backup_path"] == backup
        # File shrank (bloat reclaimed).
        assert os.path.getsize(db.db_file) < size_before
        # auto_vacuum now INCREMENTAL on the live file.
        assert _run(_auto_vacuum_mode(db.db_file)) == 2

    def test_concurrent_run_guard(self, tmp_path):
        """A second call while one is in progress returns already_running."""
        db = _make_db(str(tmp_path))

        async def _do():
            await db.initialize()
            db._vacuum_in_progress = True  # simulate in-flight VACUUM
            return await db.vacuum_full_supervised()

        result = _run(_do())
        assert result["status"] == "already_running"

    def test_post_vacuum_incremental_vacuum_now_active(self, tmp_path):
        """After supervised VACUUM, the DB is INCREMENTAL and freed pages are
        reclaimable (proving incremental_vacuum stops no-op'ing).

        We verify via a fresh connection (the supervised VACUUM persists the
        auto_vacuum mode to the file header; the no-op guard in
        incremental_vacuum keys off exactly this PRAGMA value)."""
        db = _make_db(str(tmp_path))

        async def _do():
            import aiosqlite
            async with aiosqlite.connect(db.db_file) as conn:
                await conn.execute("PRAGMA auto_vacuum=NONE")
                await conn.execute("VACUUM")
                await conn.commit()
            assert await _auto_vacuum_mode(db.db_file) == 0
            await _create_bloat(db.db_file)
            await db.vacuum_full_supervised()
            # Activation persisted to the file header -> the no-op guard now
            # passes, so incremental_vacuum will reclaim freed pages.
            assert await _auto_vacuum_mode(db.db_file) == 2
            # Confirm reclamation on a fresh connection (same primitive the DAO
            # uses: PRAGMA incremental_vacuum under INCREMENTAL auto_vacuum).
            await _create_bloat(db.db_file)
            async with aiosqlite.connect(db.db_file) as conn:
                cur = await conn.execute("PRAGMA freelist_count")
                free_before = (await cur.fetchone())[0]
                await conn.execute("PRAGMA incremental_vacuum(2000)")
                await conn.commit()
                cur = await conn.execute("PRAGMA freelist_count")
                free_after = (await cur.fetchone())[0]
            return free_before, free_after

        free_before, free_after = _run(_with_worker(db, _do))
        assert free_before > 0
        assert free_after < free_before


# ---------------------------------------------------------------------------
# Button + nightly wiring (structural)
# ---------------------------------------------------------------------------


def _button_src() -> str:
    return Path("custom_components/universal_room_automation/button.py").read_text()


def _init_src() -> str:
    return Path("custom_components/universal_room_automation/__init__.py").read_text()


class TestButtonAndWiring:
    def test_button_class_exists(self):
        assert "class VacuumDatabaseButton(" in _button_src()

    def test_button_registered_in_cm_setup(self):
        assert "VacuumDatabaseButton(hass, entry)" in _button_src()

    def test_button_on_cm_device(self):
        src = _button_src()
        idx = src.find("class VacuumDatabaseButton(")
        block = src[idx: src.find("\nclass ", idx + 1)]
        assert "coordinator_manager" in block

    def test_button_unique_id(self):
        src = _button_src()
        idx = src.find("class VacuumDatabaseButton(")
        block = src[idx: src.find("\nclass ", idx + 1)]
        assert 'f"{DOMAIN}_vacuum_database"' in block

    def test_button_calls_dao(self):
        src = _button_src()
        idx = src.find("class VacuumDatabaseButton(")
        block = src[idx: src.find("\nclass ", idx + 1)]
        assert "vacuum_full_supervised()" in block

    def test_button_press_invokes_dao(self):
        """The button's async_press body calls vacuum_full_supervised on the
        resolved database, and guards re-entrant presses via _running.

        (Source-grep rather than runtime: importing button.py pulls in the
        full coordinator/automation chain which needs a much larger HA mock
        surface than this DAO-focused suite provides — the existing
        test_v462_d5_acknowledge_button.py uses the same source-grep idiom.)
        """
        src = _button_src()
        idx = src.find("class VacuumDatabaseButton(")
        block = src[idx: src.find("\nclass ", idx + 1)]
        press_idx = block.find("async def async_press(")
        press = block[press_idx:]
        assert "self._running" in press, "press must guard re-entrancy"
        assert "await database.vacuum_full_supervised()" in press
        assert 'get("database")' in press

    def test_incremental_vacuum_in_nightly_ops(self):
        """incremental_vacuum is a member of the nightly _cleanup_ops list."""
        src = _init_src()
        assert '("incremental_vacuum", "incremental_vacuum", {})' in src

    def test_supervised_vacuum_not_in_nightly_schedule(self):
        """vacuum_full_supervised must NOT be wired into _cleanup_ops.

        It must never appear as a scheduled cleanup-ops tuple (a blocking
        full VACUUM is button-triggered only). A doc-comment mention is fine;
        what we forbid is the method name used as an op in the list.
        """
        src = _init_src()
        assert '"vacuum_full_supervised"' not in src
        assert "vacuum_full_supervised," not in src

    def test_nightly_loop_budget_respected(self):
        """The nightly loop still has the 5-min budget break (unchanged)."""
        src = _init_src()
        assert "hit 5-min budget" in src
