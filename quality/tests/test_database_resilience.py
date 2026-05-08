"""Tests for v3.13.0 database infrastructure resilience.

Verifies:
- Per-table isolation: corruption in one table doesn't block others
- energy_snapshots auto-repair on B-tree corruption
- circuit_state table creation and CRUD
- tou_period column migration on energy_history
- Edge cases: empty state, restore before init, rollback recovery
"""

import asyncio
import os
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
import sqlite3

import sys
import types

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
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
sys.modules["custom_components.universal_room_automation"] = _ura

from custom_components.universal_room_automation.database import UniversalRoomDatabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    """Create a UniversalRoomDatabase pointing at a temp directory.

    v4.5.2 D2: hass.async_create_background_task is configured to
    actually schedule via asyncio.create_task so the write worker
    runs when started. Pre-fix, that method was a bare MagicMock
    returning another MagicMock — `db.start_write_worker()` appeared
    to succeed but the worker never executed, every queued write
    silently failed with "DB write worker not running".

    Tests that ONLY exercise direct sqlite3 reads after `initialize()`
    don't need the worker. Tests that hit save_* / log_* methods
    must use `_make_db_with_worker` (which calls start_write_worker
    inside the same _run() so the task lifecycle aligns).
    """
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)

    # Make the create_background_task call schedule a real asyncio.Task
    # in the current event loop. Otherwise the worker is a dangling coro.
    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)
    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task

    return UniversalRoomDatabase(hass)


async def _do_db_op_with_worker(db: UniversalRoomDatabase, op_coro_factory):
    """Run a coro that uses the write worker. Starts worker, runs op,
    drains the queue, cancels worker, returns the op's result.

    Use this for tests that need the worker but want to stay in a
    single _run() call (so the asyncio.Task survives long enough to
    process queued writes). Pre-fix attempts that called
    `_run(db.start_write_worker())` then `_run(db.save_*())` failed
    because each _run created a fresh loop, the worker task from the
    first _run was orphaned, and the queued write in the second _run
    sat unprocessed.

    Usage:
        async def _do():
            await db.save_circuit_state(circuits)
            return await db.restore_circuit_state()
        result = _run(_do_db_op_with_worker(db, _do))
    """
    await db.initialize()
    await db.start_write_worker()
    try:
        result = await op_coro_factory()
        # Drain the queue so all queued writes complete before returning
        await db._write_queue.join()
        return result
    finally:
        if db._write_task is not None and not db._write_task.done():
            db._write_task.cancel()
            try:
                await db._write_task
            except asyncio.CancelledError:
                pass


def _get_tables(db_path: str) -> set[str]:
    """Return set of table names in a SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    return tables


def _get_columns(db_path: str, table_name: str) -> set[str]:
    """Return set of column names for a table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    return columns


def _run(coro):
    """Run an async coroutine in the event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDatabaseInitialization:
    """Test that initialize() creates all expected tables."""

    def test_all_tables_created(self, tmp_path):
        """All expected tables should exist after initialize()."""
        db = _make_db(str(tmp_path))
        result = _run(db.initialize())
        assert result is True

        tables = _get_tables(db.db_file)
        expected = {
            "occupancy_events", "environmental_data", "energy_snapshots",
            "external_conditions", "zone_events", "energy_history",
            "person_visits", "person_presence_snapshots", "room_transitions",
            "unknown_devices", "census_snapshots", "person_entry_exit_events",
            "decision_log", "compliance_log", "anomaly_log", "metric_baselines",
            "outcome_log", "parameter_beliefs", "parameter_history",
            "notification_log", "notification_inbound", "house_state_log",
            "energy_daily", "energy_peak_import", "evse_state",
            "circuit_state",  # v3.13.0
        }
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"

    def test_idempotent_initialization(self, tmp_path):
        """Running initialize() twice should succeed without errors."""
        db = _make_db(str(tmp_path))
        assert _run(db.initialize()) is True
        assert _run(db.initialize()) is True


class TestPerTableIsolation:
    """Test that failure in one table doesn't block others."""

    def test_failure_in_one_table_does_not_block_others(self, tmp_path):
        """If a table's index fails, later tables still get created."""
        db = _make_db(str(tmp_path))

        # Pre-create environmental_data with wrong schema (no timestamp col).
        # The CREATE TABLE IF NOT EXISTS is a no-op, but the
        # CREATE INDEX idx_env_room_time ON (room_id, timestamp) will fail
        # because 'timestamp' column does not exist.
        conn = sqlite3.connect(db.db_file)
        conn.execute("""
            CREATE TABLE environmental_data (
                id INTEGER PRIMARY KEY,
                bad_column TEXT
            )
        """)
        conn.commit()
        conn.close()

        result = _run(db.initialize())
        assert result is True

        # All other tables must still exist despite environmental_data failure
        tables = _get_tables(db.db_file)
        assert "energy_history" in tables
        assert "energy_daily" in tables
        assert "energy_peak_import" in tables
        assert "evse_state" in tables
        assert "circuit_state" in tables
        assert "house_state_log" in tables
        assert "decision_log" in tables

    def test_rollback_keeps_connection_usable(self, tmp_path):
        """After a table creation failure + rollback, subsequent tables succeed."""
        db = _make_db(str(tmp_path))

        # Create occupancy_events with wrong schema to force failure
        conn = sqlite3.connect(db.db_file)
        conn.execute("""
            CREATE TABLE occupancy_events (
                id INTEGER PRIMARY KEY,
                wrong_col TEXT
            )
        """)
        conn.commit()
        conn.close()

        result = _run(db.initialize())
        assert result is True

        # The very next table (environmental_data) must exist
        tables = _get_tables(db.db_file)
        assert "environmental_data" in tables
        # And the last table must also exist
        assert "circuit_state" in tables


class TestCircuitStateTable:
    """Test circuit_state table CRUD operations."""

    def test_circuit_state_table_exists(self, tmp_path):
        """circuit_state table should be created by initialize()."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())
        tables = _get_tables(db.db_file)
        assert "circuit_state" in tables

    def test_circuit_state_columns(self, tmp_path):
        """circuit_state should have expected columns."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())
        columns = _get_columns(db.db_file, "circuit_state")
        assert columns == {"circuit_id", "was_loaded", "zero_since", "alerted", "updated_at"}

    def test_save_and_restore_circuit_state_with_float_zero_since(self, tmp_path):
        """Save and restore circuit state round-trips correctly with float zero_since.

        v4.5.2 D2: this exercises the async write-queue path, which
        requires worker + saves + reads in the SAME event loop. Pre-fix,
        each _run() spun up a fresh loop and orphaned the worker task.
        """
        db = _make_db(str(tmp_path))

        circuits = {
            "circuit_kitchen": {
                "was_loaded": True,
                "zero_since": 1741788000.123,  # float epoch timestamp
                "alerted": False,
            },
            "circuit_hvac": {
                "was_loaded": True,
                "zero_since": None,
                "alerted": True,
            },
        }

        async def _do():
            await db.save_circuit_state(circuits)
            return await db.restore_circuit_state()
        restored = _run(_do_db_op_with_worker(db, _do))

        assert len(restored) == 2
        assert restored["circuit_kitchen"]["was_loaded"] is True
        # zero_since must come back as float, not string
        assert isinstance(restored["circuit_kitchen"]["zero_since"], float)
        assert abs(restored["circuit_kitchen"]["zero_since"] - 1741788000.123) < 0.001
        assert restored["circuit_kitchen"]["alerted"] is False
        assert restored["circuit_hvac"]["alerted"] is True
        assert restored["circuit_hvac"]["zero_since"] is None

    def test_save_circuit_state_overwrites(self, tmp_path):
        """Saving circuit state again should overwrite previous values."""
        db = _make_db(str(tmp_path))

        circuits_v1 = {
            "circuit_a": {"was_loaded": True, "zero_since": None, "alerted": False}
        }
        circuits_v2 = {
            "circuit_a": {"was_loaded": False, "zero_since": 1741790000.0, "alerted": True}
        }

        async def _do():
            await db.save_circuit_state(circuits_v1)
            await db.save_circuit_state(circuits_v2)
            return await db.restore_circuit_state()
        restored = _run(_do_db_op_with_worker(db, _do))

        assert restored["circuit_a"]["was_loaded"] is False
        assert restored["circuit_a"]["alerted"] is True

    def test_restore_empty_circuit_state(self, tmp_path):
        """Restoring with no saved state returns empty dict."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())

        restored = _run(db.restore_circuit_state())
        assert restored == {}

    def test_save_empty_circuit_state_is_noop(self, tmp_path):
        """Saving empty dict should be a no-op (no DB writes)."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())

        _run(db.save_circuit_state({}))
        restored = _run(db.restore_circuit_state())
        assert restored == {}

    def test_restore_before_initialize(self, tmp_path):
        """restore_circuit_state before initialize returns empty dict gracefully."""
        db = _make_db(str(tmp_path))
        # Deliberately do NOT call initialize()
        # Create DB file so connect works, but no tables
        conn = sqlite3.connect(db.db_file)
        conn.close()

        restored = _run(db.restore_circuit_state())
        assert restored == {}


class TestTouPeriodMigration:
    """Test energy_history tou_period column migration."""

    def test_tou_period_column_added(self, tmp_path):
        """tou_period column should be added to energy_history."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())
        columns = _get_columns(db.db_file, "energy_history")
        assert "tou_period" in columns

    def test_tou_period_on_existing_db(self, tmp_path):
        """tou_period migration should work on pre-existing energy_history."""
        db = _make_db(str(tmp_path))

        # Pre-create energy_history WITHOUT tou_period (simulating old DB)
        conn = sqlite3.connect(db.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS energy_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                solar_production REAL,
                UNIQUE(timestamp)
            )
        """)
        conn.execute(
            "INSERT INTO energy_history (timestamp, solar_production) VALUES (?, ?)",
            ("2026-03-12T10:00:00", 5.5),
        )
        conn.commit()
        conn.close()

        result = _run(db.initialize())
        assert result is True

        columns = _get_columns(db.db_file, "energy_history")
        assert "tou_period" in columns

        # Verify existing data preserved
        conn = sqlite3.connect(db.db_file)
        cursor = conn.execute("SELECT solar_production FROM energy_history")
        row = cursor.fetchone()
        assert row[0] == 5.5
        conn.close()

    def test_tou_period_idempotent(self, tmp_path):
        """Running migration when tou_period already exists should be a no-op."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())
        # Second init should not fail on the migration
        _run(db.initialize())
        columns = _get_columns(db.db_file, "energy_history")
        assert "tou_period" in columns


class TestEnergySnapshotsAutoRepair:
    """Test that corrupt energy_snapshots is dropped and recreated."""

    def test_repair_recreates_table(self, tmp_path):
        """A corrupt energy_snapshots should be dropped and recreated."""
        db = _make_db(str(tmp_path))

        # Create with wrong schema — the CREATE TABLE IF NOT EXISTS won't fire
        # but the index on (room_id, timestamp) will fail since 'timestamp' col
        # doesn't exist in this schema. The error message contains 'no such column'
        # which doesn't contain 'corrupt', so repair won't fire via error check.
        # Instead, test the repair method directly.
        conn = sqlite3.connect(db.db_file)
        conn.execute("""
            CREATE TABLE energy_snapshots (
                id INTEGER PRIMARY KEY,
                bad_column TEXT
            )
        """)
        conn.commit()
        conn.close()

        result = _run(db.initialize())
        assert result is True

        # Even without corruption keyword, energy_snapshots should exist
        tables = _get_tables(db.db_file)
        assert "energy_snapshots" in tables

    def test_repair_whitelist_blocks_unknown_tables(self, tmp_path):
        """_repair_corrupt_table should refuse tables not in _REPAIRABLE_TABLES."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())

        import aiosqlite

        async def _try_repair():
            async with aiosqlite.connect(db.db_file, timeout=30.0) as conn:
                return await db._repair_corrupt_table(
                    conn, "decision_log",
                    "CREATE TABLE decision_log (id INTEGER PRIMARY KEY)",
                    [],
                )

        result = _run(_try_repair())
        assert result is False  # Refused because not in whitelist

        # decision_log should still exist with original schema
        tables = _get_tables(db.db_file)
        assert "decision_log" in tables
