"""Database for Universal Room Automation."""
from __future__ import annotations
#
# Universal Room Automation vv5.96.0
# Build: 2026-01-04
# File: database.py
# v3.3.1.2: Added WAL mode and busy_timeout to fix 'database is locked' errors
# v3.3.1: Added Optional import
#

import asyncio
import logging
import os
import shutil
import statistics
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DATABASE_DIR,
    DATABASE_NAME,
    MIN_DATA_DAYS_PREDICTION,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB write worker "ready" wait tuning (rung 1 — module constants).
#
# Backlog #13 (2026-08-01): during the HA STARTED boot window, event-loop
# starvation stalls the serial write worker >35s. The prior single-stage
# 35s timeout raised RuntimeError from the producer, and the worker later
# ran _execute with `done` already set — the caller never used the
# connection, so the row was SILENTLY LOST (4 lost writes/boot observed
# across 3 consecutive boots: census / energy / house-state / decision).
#
# Fix: two-stage wait. At the soft-warn boundary we log WARNING and keep
# waiting (async, no loop block). Only at the hard cap do we set `done`
# and raise. Rows now complete late instead of being dropped.
#
# Governance: rung 1 (module constants) — these are safety bounds, not
# operator policy. Kill-switch: set HARD_CAP == SOFT_WARN to restore the
# prior single-stage raise-at-35s behavior.
#
# NOTE: HARD_CAP interacts with HA's ~10-minute config-entry setup
# timeout — do NOT raise HARD_CAP without checking that budget. A hard
# cap that outlasts entry setup would deadlock startup instead of
# raising a diagnosable error.
#
# CALLER_HOLD_WARN_S (fix-up A-HIGH-1): time after which we log a
# WARNING that a caller is still holding the write connection. The
# worker NEVER abandons a live caller — abandoning + returning would
# hand the SAME sqlite connection to the next queued write while the
# late caller is still executing, silently interleaving or corrupting
# DB state. See _execute's INVARIANT comment.
# ---------------------------------------------------------------------------
DB_WRITE_READY_SOFT_WARN_S: float = 35.0
DB_WRITE_READY_HARD_CAP_S: float = 300.0
DB_WRITE_CALLER_HOLD_WARN_S: float = 120.0


def _sum_savings_from_rows(rows) -> tuple[float, int]:
    """Pure kernel for `get_ac_ramp_savings`: sum $ savings from an
    iterable of `(notes, effective)` tuples.

    Extracted so it can be exercised by a NON-HA-gated unit test (Bug
    Class #60/#62: `@_ha_only`-skipped tests silently pass on hosts
    without HA installed, giving no mutation coverage).

    Rules (must match the DAO's forward-only contract):
      * `effective in (None, 0)` -> skip.
      * Missing / malformed / non-parseable `kwh_avoided` -> skip.
      * Missing / malformed / non-finite / non-positive `rate` -> skip
        (row still counted by the kWh family, but contributes $0 here).
      * Otherwise, add `kwh_event * rate_event` to total and increment
        `counted_with_rate`.

    Returns `(total_usd, counted_with_rate)`.
    """
    import math as _math
    total_usd = 0.0
    counted_with_rate = 0
    for notes, effective in rows:
        if effective is None or effective == 0:
            continue
        if not notes:
            continue
        kwh_event: float | None = None
        rate_event: float | None = None
        try:
            for part in str(notes).split(";"):
                k, _sep, v = part.partition("=")
                key = k.strip()
                if key == "kwh_avoided":
                    try:
                        kwh_event = float(v)
                    except (ValueError, TypeError):
                        kwh_event = None
                elif key == "rate":
                    try:
                        rate_event = float(v)
                    except (ValueError, TypeError):
                        rate_event = None
        except (ValueError, AttributeError):
            continue
        if kwh_event is None:
            continue
        if rate_event is None or not _math.isfinite(rate_event) or rate_event <= 0:
            # Forward-only: no valid captured rate -> $0 contribution.
            continue
        counted_with_rate += 1
        total_usd += kwh_event * rate_event
    return (total_usd, counted_with_rate)


class UniversalRoomDatabase:
    """Manage SQLite database for room automation."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the database."""
        self.hass = hass
        db_dir = hass.config.path(DATABASE_DIR)
        os.makedirs(db_dir, exist_ok=True)
        self.db_file = os.path.join(db_dir, DATABASE_NAME)
        self._last_table_error: Exception | None = None
        # v3.22.8: Write queue serializes all DB writes through a single
        # asyncio task, eliminating contention entirely. Writes are queued
        # as coroutines and executed one at a time. Reads use independent
        # transient connections (WAL allows concurrent reads).
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._write_task: asyncio.Task | None = None
        self._db_stats = {"writes": 0, "reads": 0, "queue_peak": 0}
        _LOGGER.info("Database file: %s", self.db_file)

    # Tables eligible for drop-and-recreate repair on corruption
    _REPAIRABLE_TABLES: frozenset[str] = frozenset({"energy_snapshots"})

    async def start_write_worker(self) -> None:
        """Start the background write worker task (idempotent).

        Safe to call multiple times — only starts one worker.
        Multiple config entries may call this during startup.
        """
        if self._write_task is not None and not self._write_task.done():
            return  # Already running
        # v4.2.15: Use async_create_background_task so the write worker
        # (which runs forever) doesn't block HA startup completion.
        self._write_task = self.hass.async_create_background_task(
            self._write_worker(), "ura_db_write_worker"
        )
        _LOGGER.info("DB write worker started")

    async def stop_write_worker(self) -> None:
        """Stop the background write worker and CLOSE its persistent connection.

        DB space-reclamation fix-up HIGH-1/HIGH-2: cancelling the worker task
        triggers its ``asyncio.CancelledError`` handler, which flushes pending
        writes and RETURNS — exiting the ``async with aiosqlite.connect(...)``
        block, so the worker's persistent connection is closed (releasing any
        WAL lock that would conflict with an exclusive VACUUM). Idempotent.

        New writes submitted via ``_db()`` while the worker is stopped no
        longer raise (v5.16.2): they buffer on ``_write_queue`` silently and
        execute against the reopened connection once ``start_write_worker()``
        runs again. Deliberate stop windows (e.g. VACUUM) therefore see
        writes DEFERRED, not rejected — do not rely on fail-fast semantics.
        """
        if self._write_task is not None and not self._write_task.done():
            self._write_task.cancel()
            try:
                await self._write_task
            except (asyncio.CancelledError, Exception):
                pass
        self._write_task = None
        _LOGGER.info("DB write worker stopped (connection closed)")

    async def _write_worker(self) -> None:
        """Background task that processes write queue sequentially.

        Opens ONE connection, processes writes forever. Auto-reconnects
        on connection failure with 5s backoff. On permanent failure,
        drains pending futures with errors so callers don't hang.
        """
        while True:
            try:
                async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                    # DB space-reclamation (Part 1): declare INCREMENTAL
                    # auto_vacuum so freed pages can be returned to the OS via
                    # PRAGMA incremental_vacuum (incremental_vacuum() DAO, wired
                    # nightly). Declared BEFORE journal_mode=WAL — on a fresh
                    # file, WAL setup writes the header and would lock in
                    # auto_vacuum=0 otherwise. On an existing NONE-mode DB this
                    # declaration is INERT until a full VACUUM runs
                    # (vacuum_full_supervised() — the supervised button); on a
                    # fresh DB it takes effect immediately. Harmless either way;
                    # auto_vacuum + WAL is a supported combination.
                    await db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    await db.execute("PRAGMA journal_mode=WAL")
                    _LOGGER.info("DB write worker connection established")
                    while True:
                        factory, future = await self._write_queue.get()
                        try:
                            result = await factory(db)
                            if not future.done():
                                future.set_result(result)
                        except Exception as exc:
                            if not future.done():
                                future.set_exception(exc)
                        finally:
                            self._write_queue.task_done()
                            self._db_stats["writes"] += 1
                            qsize = self._write_queue.qsize()
                            if qsize > self._db_stats["queue_peak"]:
                                self._db_stats["queue_peak"] = qsize
                                if qsize > 10:
                                    _LOGGER.warning(
                                        "DB write queue peak: %d items", qsize
                                    )
            except asyncio.CancelledError:
                _LOGGER.info("DB write worker cancelled — flushing pending writes")
                await self._flush_pending_writes()
                return
            except Exception as exc:
                _LOGGER.error(
                    "DB write worker connection lost: %s — retrying in 5s", exc
                )
                self._drain_pending_futures(str(exc))
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    _LOGGER.info("DB write worker cancelled during reconnect — flushing")
                    await self._flush_pending_writes()
                    return

    async def _flush_pending_writes(self) -> None:
        """Gracefully execute remaining queued writes before shutdown.

        Opens a fresh connection and processes pending writes with a
        5-second time budget. Any writes remaining after the budget
        are failed via _drain_pending_futures.
        """
        deadline = time.monotonic() + 5.0
        flushed = 0
        try:
            async with aiosqlite.connect(self.db_file, timeout=5.0) as db:
                await db.execute("PRAGMA busy_timeout=5000")
                await db.execute("PRAGMA journal_mode=WAL")
                while not self._write_queue.empty():
                    if time.monotonic() > deadline:
                        _LOGGER.warning(
                            "DB flush hit 5s budget after %d writes", flushed
                        )
                        break
                    try:
                        factory, future = self._write_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        result = await factory(db)
                        if not future.done():
                            future.set_result(result)
                        flushed += 1
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    finally:
                        self._write_queue.task_done()
        except asyncio.CancelledError:
            _LOGGER.warning("DB flush interrupted by cancellation")
        except Exception as exc:
            _LOGGER.warning("DB flush connection failed: %s", exc)
        if flushed:
            _LOGGER.info("DB flush: executed %d pending writes", flushed)
        # Drain anything left over the budget
        remaining = self._write_queue.qsize()
        if remaining:
            self._drain_pending_futures("shutdown timeout")

    def _drain_pending_futures(self, reason: str) -> None:
        """Fail all pending write futures so callers don't hang."""
        drained = 0
        while not self._write_queue.empty():
            try:
                _factory, future = self._write_queue.get_nowait()
                if not future.done():
                    future.set_exception(
                        RuntimeError(f"DB write failed: {reason}")
                    )
                self._write_queue.task_done()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            _LOGGER.warning("DB write worker drained %d pending writes", drained)

    async def async_close(self) -> None:
        """Stop write worker and close connections on shutdown."""
        if self._write_task is not None and not self._write_task.done():
            self._write_task.cancel()
            try:
                await self._write_task
            except (asyncio.CancelledError, Exception):
                pass
            self._write_task = None
        _LOGGER.info(
            "DB stats: %d writes, %d reads, queue peak %d",
            self._db_stats["writes"],
            self._db_stats["reads"],
            self._db_stats["queue_peak"],
        )

    @asynccontextmanager
    async def _db(self):
        """Submit a write operation to the write queue.

        v3.22.8: Writes go through a single-worker queue. The worker
        holds one persistent connection and processes writes sequentially.
        v3.22.9: Fail fast if worker is not running (review fix F4).

        v5.16.2 (Tier-1): worker-gap hardening. Review A1 correction: the
        boot-time producers CANNOT hit this branch (they acquire the DB via
        hass.data, which is published only AFTER start_write_worker() at
        __init__.py:~1384-1385). The real trigger is the worker-RESTART
        window — stop_write_worker()/start_write_worker() re-cycles (e.g.
        the post-STARTED SPAN re-migration pass), during which
        _write_task.done() is transiently True while producers hold a live
        handle. Previously we raised + dropped the row (the observed
        boot-window ERROR lines). Now we enqueue onto _write_queue as
        normal; start_write_worker() drains queued items first. The queue
        is an unbounded asyncio.Queue, so this is lossless; producer-side
        throttles bound the volume. A DEBUG note is logged.
        """
        if self._write_task is None or self._write_task.done():
            _LOGGER.debug(
                "DB write submitted before worker start — buffering on queue"
                " (worker will drain on start)"
            )
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        # We need to yield a db connection to the caller inside the
        # context manager. Use an Event to synchronize.
        db_holder: list = []
        ready = asyncio.Event()
        done = asyncio.Event()

        async def _execute(db):
            db_holder.append(db)
            ready.set()
            # INVARIANT (backlog #13 fix-up A-HIGH-1): `done` is set on
            # EVERY caller exit path — normal yield-finally, pre-yield
            # exception (hard-cap raise, drain-propagated exception),
            # and cancellation-mid-park. Therefore this unbounded wait
            # cannot hang the worker. The prior 120s abandonment path
            # was UNSAFE: on caller-hold-timeout the worker returned
            # and handed the SAME sqlite connection to the next queued
            # write while the late caller was still executing on it,
            # silently interleaving statements and risking corruption.
            # We warn (repeatedly) but never abandon.
            _start = time.monotonic()
            _warn_tier = 0
            while not done.is_set():
                try:
                    await asyncio.wait_for(
                        done.wait(), timeout=DB_WRITE_CALLER_HOLD_WARN_S
                    )
                except asyncio.TimeoutError:
                    _warn_tier += 1
                    _held = time.monotonic() - _start
                    _LOGGER.warning(
                        "DB write caller holding connection >%.1fs "
                        "(held=%.1fs, tier=%d) — continuing to wait "
                        "(worker will NOT reuse this connection)",
                        DB_WRITE_CALLER_HOLD_WARN_S, _held, _warn_tier,
                    )
            return None

        async def _wait_ready_stage(timeout: float) -> str:
            """Wait up to `timeout` for `ready` set OR `future` complete.

            Returns 'ready' on ready set or on future normal completion,
            'timeout' on timeout. If `future` completes with an exception
            (drain path B-HIGH-1), sets `done` and re-raises that exception
            so parked callers unblock promptly during shutdown. On
            CancelledError (B-MED-2), sets `done` before re-raising so the
            worker's unbounded done-wait terminates.
            """
            ready_task = asyncio.ensure_future(ready.wait())
            try:
                done_set, _pending = await asyncio.wait(
                    {ready_task, future},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except BaseException:
                if not ready_task.done():
                    ready_task.cancel()
                done.set()
                raise
            if not ready_task.done():
                ready_task.cancel()
            if not done_set:
                return "timeout"
            if ready_task in done_set:
                return "ready"
            # `future` completed first — only reachable via drain.
            exc = future.exception()
            if exc is not None:
                done.set()
                raise exc
            return "ready"

        await self._write_queue.put((_execute, future))
        # Wait for worker to give us the connection.
        # Two-stage wait (backlog #13): soft-warn then continue up to a
        # hard cap, so a boot-window loop stall completes the row LATE
        # instead of raising and dropping it (the pre-fix silent-loss
        # path). See DB_WRITE_READY_{SOFT_WARN,HARD_CAP}_S above.
        soft = DB_WRITE_READY_SOFT_WARN_S
        hard = DB_WRITE_READY_HARD_CAP_S
        _wait_start = time.monotonic()
        if soft < hard:
            stage = await _wait_ready_stage(soft)
            if stage == "timeout":
                _elapsed = time.monotonic() - _wait_start
                _LOGGER.warning(
                    "DB write worker slow: no connection after %.1fs "
                    "(queue_depth=%d, elapsed=%.1fs); continuing to wait up to %.1fs",
                    soft, self._write_queue.qsize(), _elapsed, hard,
                )
                stage = await _wait_ready_stage(hard - soft)
                if stage == "timeout":
                    done.set()  # unblock worker if it runs _execute later
                    _elapsed = time.monotonic() - _wait_start
                    raise RuntimeError(
                        "DB write worker did not process request within "
                        f"{hard:.1f}s (queue_depth={self._write_queue.qsize()}, "
                        f"elapsed={_elapsed:.1f}s) — row dropped"
                    )
        else:
            # Single-stage kill-switch (SOFT >= HARD): restore raise-at-soft.
            stage = await _wait_ready_stage(soft)
            if stage == "timeout":
                done.set()
                _elapsed = time.monotonic() - _wait_start
                raise RuntimeError(
                    "DB write worker did not process request within "
                    f"{soft:.1f}s (queue_depth={self._write_queue.qsize()}, "
                    f"elapsed={_elapsed:.1f}s)"
                )
        try:
            yield db_holder[0]
        finally:
            done.set()
            # Wait for worker to complete our item
            try:
                await future
            except Exception:
                pass

    @asynccontextmanager
    async def _db_read(self):
        """Get a transient connection for read-only queries.

        WAL mode allows concurrent reads without contention.
        Each read gets its own short-lived connection.
        """
        self._db_stats["reads"] += 1
        async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
            await db.execute("PRAGMA busy_timeout=30000")
            await db.execute("PRAGMA query_only=ON")
            yield db

    async def _create_table_safe(
        self,
        db: "aiosqlite.Connection",
        table_name: str,
        statements: list[str],
    ) -> bool:
        """Create a single table and its indexes, isolated from other tables.

        Returns True if all statements succeeded, False if any failed.
        A failure here does NOT prevent other tables from being created.
        On failure, the exception is stored in self._last_table_error.
        """
        try:
            for stmt in statements:
                await db.execute(stmt)
            await db.commit()
            self._last_table_error = None
            return True
        except Exception as e:
            _LOGGER.error(
                "Error creating table %s (non-fatal, other tables unaffected): %s",
                table_name, e,
            )
            self._last_table_error = e
            # Attempt rollback so the connection stays usable
            try:
                await db.rollback()
            except Exception:
                pass
            return False

    async def _repair_corrupt_table(
        self,
        db: "aiosqlite.Connection",
        table_name: str,
        create_sql: str,
        index_sqls: list[str],
    ) -> bool:
        """Drop and recreate a table whose B-tree is corrupt.

        Only allowed for tables in _REPAIRABLE_TABLES to prevent
        accidental data loss on transient errors.
        """
        if table_name not in self._REPAIRABLE_TABLES:
            _LOGGER.error(
                "Table %s is not in repairable list, skipping repair", table_name
            )
            return False
        try:
            _LOGGER.warning(
                "Dropping corrupt table %s and recreating it", table_name
            )
            # table_name is validated against _REPAIRABLE_TABLES above
            await db.execute(f"DROP TABLE IF EXISTS {table_name}")  # noqa: S608
            await db.execute(create_sql)
            for idx_sql in index_sqls:
                await db.execute(idx_sql)
            await db.commit()
            _LOGGER.info("Successfully recreated table %s", table_name)
            return True
        except Exception as e2:
            _LOGGER.error("Failed to recreate table %s: %s", table_name, e2)
            try:
                await db.rollback()
            except Exception:
                pass
            return False

    async def initialize(self) -> bool:
        """Initialize database schema.

        Ordering invariant: this method is called from __init__.py BEFORE
        the database instance is stored in hass.data[DOMAIN]["database"].
        No other code can access the DB until initialize() returns True,
        so table creation is safe from concurrent access.

        v3.13.0: Refactored to per-table isolation so that corruption in one
        table (e.g. energy_snapshots B-tree) does not prevent creation of
        tables defined after it.
        """
        failed_tables: list[str] = []
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                # DB space-reclamation (Part 1): set INCREMENTAL auto_vacuum
                # BEFORE journal_mode=WAL and BEFORE any table is created.
                # CAVEAT: on a brand-new file, switching to WAL writes the DB
                # header and locks in auto_vacuum=0 — so auto_vacuum MUST be
                # declared first or it silently reverts to NONE. (auto_vacuum
                # can only be chosen for an empty DB without a full VACUUM.) On
                # an existing DB this declaration is a no-op until
                # vacuum_full_supervised() runs.
                await db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                # Enable WAL mode for better concurrency (prevents "database is locked")
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")

                # -- Occupancy events ----------------------------------------
                if not await self._create_table_safe(db, "occupancy_events", [
                    """CREATE TABLE IF NOT EXISTS occupancy_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        event_type TEXT NOT NULL,
                        trigger_source TEXT,
                        duration INTEGER
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_occupancy_room_time
                    ON occupancy_events(room_id, timestamp)""",
                ]):
                    failed_tables.append("occupancy_events")

                # -- Environmental data --------------------------------------
                if not await self._create_table_safe(db, "environmental_data", [
                    """CREATE TABLE IF NOT EXISTS environmental_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        temperature REAL,
                        humidity REAL,
                        illuminance REAL,
                        occupied BOOLEAN
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_env_room_time
                    ON environmental_data(room_id, timestamp)""",
                ]):
                    failed_tables.append("environmental_data")

                # -- Energy snapshots (corruption-aware) ---------------------
                _es_create = """CREATE TABLE IF NOT EXISTS energy_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        power_watts REAL,
                        occupied BOOLEAN,
                        lights_on INTEGER,
                        fans_on INTEGER,
                        switches_on INTEGER,
                        covers_open INTEGER
                    )"""
                _es_index = """CREATE INDEX IF NOT EXISTS idx_energy_room_time
                    ON energy_snapshots(room_id, timestamp)"""
                if not await self._create_table_safe(db, "energy_snapshots", [
                    _es_create, _es_index,
                ]):
                    # Only attempt drop+recreate for actual corruption, not
                    # transient errors like SQLITE_BUSY or disk-full
                    err_str = str(self._last_table_error).lower()
                    if "corrupt" in err_str or "malformed" in err_str:
                        if not await self._repair_corrupt_table(
                            db, "energy_snapshots", _es_create, [_es_index]
                        ):
                            failed_tables.append("energy_snapshots")
                    else:
                        failed_tables.append("energy_snapshots")

                # -- External conditions -------------------------------------
                if not await self._create_table_safe(db, "external_conditions", [
                    """CREATE TABLE IF NOT EXISTS external_conditions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        outside_temp REAL,
                        outside_humidity REAL,
                        weather_condition TEXT,
                        solar_production REAL,
                        forecast_high REAL,
                        forecast_low REAL,
                        occupied_room_count INTEGER,
                        occupied_zone_count INTEGER
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_external_time
                    ON external_conditions(timestamp)""",
                ]):
                    failed_tables.append("external_conditions")

                # -- Zone events ---------------------------------------------
                if not await self._create_table_safe(db, "zone_events", [
                    """CREATE TABLE IF NOT EXISTS zone_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        zone TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        event_type TEXT NOT NULL,
                        room_count INTEGER,
                        rooms TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_zone_time
                    ON zone_events(zone, timestamp)""",
                ]):
                    failed_tables.append("zone_events")

                # -- Energy history ------------------------------------------
                if not await self._create_table_safe(db, "energy_history", [
                    """CREATE TABLE IF NOT EXISTS energy_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        solar_production REAL,
                        solar_export REAL,
                        grid_import REAL,
                        grid_import_2 REAL,
                        battery_level REAL,
                        whole_house_energy REAL,
                        rooms_energy_total REAL,
                        outside_temp REAL,
                        outside_humidity REAL,
                        house_avg_temp REAL,
                        house_avg_humidity REAL,
                        temp_delta_outside REAL,
                        humidity_delta_outside REAL,
                        rooms_occupied INTEGER,
                        day_of_week INTEGER,
                        hour_of_day INTEGER,
                        is_weekend BOOLEAN,
                        UNIQUE(timestamp)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_energy_history_time
                    ON energy_history(timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_energy_history_dow_hour
                    ON energy_history(day_of_week, hour_of_day)""",
                ]):
                    failed_tables.append("energy_history")

                # -- Person visits -------------------------------------------
                if not await self._create_table_safe(db, "person_visits", [
                    """CREATE TABLE IF NOT EXISTS person_visits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        person_id TEXT NOT NULL,
                        room_id TEXT NOT NULL,
                        entry_time DATETIME NOT NULL,
                        exit_time DATETIME,
                        duration_seconds INTEGER,
                        confidence REAL,
                        detection_method TEXT,
                        transition_from TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_person_visits_person_time
                    ON person_visits(person_id, entry_time)""",
                    """CREATE INDEX IF NOT EXISTS idx_person_visits_room_time
                    ON person_visits(room_id, entry_time)""",
                ]):
                    failed_tables.append("person_visits")

                # -- Person presence snapshots --------------------------------
                if not await self._create_table_safe(db, "person_presence_snapshots", [
                    """CREATE TABLE IF NOT EXISTS person_presence_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        person_id TEXT NOT NULL,
                        room_id TEXT,
                        confidence REAL,
                        method TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_person_snapshots_time
                    ON person_presence_snapshots(timestamp, person_id)""",
                ]):
                    failed_tables.append("person_presence_snapshots")

                # -- Room transitions ----------------------------------------
                if not await self._create_table_safe(db, "room_transitions", [
                    """CREATE TABLE IF NOT EXISTS room_transitions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        person_id TEXT NOT NULL,
                        from_room TEXT NOT NULL,
                        to_room TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        duration_seconds INTEGER NOT NULL,
                        path_type TEXT NOT NULL,
                        confidence REAL,
                        via_room TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_transitions_person
                    ON room_transitions(person_id, timestamp DESC)""",
                    """CREATE INDEX IF NOT EXISTS idx_transitions_rooms
                    ON room_transitions(from_room, to_room, timestamp DESC)""",
                ]):
                    failed_tables.append("room_transitions")

                # -- Unknown devices -----------------------------------------
                if not await self._create_table_safe(db, "unknown_devices", [
                    """CREATE TABLE IF NOT EXISTS unknown_devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL,
                        first_seen DATETIME NOT NULL,
                        last_seen DATETIME NOT NULL,
                        room_id TEXT,
                        confidence REAL,
                        UNIQUE(device_id)
                    )""",
                ]):
                    failed_tables.append("unknown_devices")

                # -- Census snapshots ----------------------------------------
                if not await self._create_table_safe(db, "census_snapshots", [
                    """CREATE TABLE IF NOT EXISTS census_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        zone TEXT NOT NULL,
                        identified_count INTEGER NOT NULL,
                        identified_persons TEXT,
                        unidentified_count INTEGER NOT NULL,
                        total_persons INTEGER NOT NULL,
                        confidence TEXT,
                        source_agreement TEXT,
                        frigate_count INTEGER,
                        unifi_count INTEGER,
                        UNIQUE(timestamp, zone)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_census_timestamp
                    ON census_snapshots(timestamp)""",
                ]):
                    failed_tables.append("census_snapshots")

                # -- Person entry/exit events --------------------------------
                if not await self._create_table_safe(db, "person_entry_exit_events", [
                    """CREATE TABLE IF NOT EXISTS person_entry_exit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        person_id TEXT,
                        event_type TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        egress_camera TEXT NOT NULL,
                        confidence REAL NOT NULL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_entry_exit_timestamp
                    ON person_entry_exit_events(timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_entry_exit_person
                    ON person_entry_exit_events(person_id, timestamp)""",
                ]):
                    failed_tables.append("person_entry_exit_events")

                # -- Decision log --------------------------------------------
                if not await self._create_table_safe(db, "decision_log", [
                    """CREATE TABLE IF NOT EXISTS decision_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        decision_type TEXT NOT NULL,
                        scope TEXT NOT NULL DEFAULT 'house',
                        situation_classified TEXT,
                        urgency INTEGER,
                        confidence REAL,
                        context_json TEXT NOT NULL,
                        action_json TEXT NOT NULL,
                        expected_savings_kwh REAL,
                        expected_cost_savings REAL,
                        expected_comfort_impact INTEGER,
                        constraints_published TEXT,
                        devices_commanded TEXT
                    )""",
                ]):
                    failed_tables.append("decision_log")
                else:
                    # Migrate scope column for pre-c0.4 DBs
                    try:
                        cursor = await db.execute("PRAGMA table_info(decision_log)")
                        dl_columns = {row[1] for row in await cursor.fetchall()}
                        if "scope" not in dl_columns:
                            await db.execute(
                                "ALTER TABLE decision_log ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"
                            )
                            await db.commit()
                    except Exception as e:
                        _LOGGER.warning("decision_log scope migration failed: %s", e)

                    await self._create_table_safe(db, "decision_log_indexes", [
                        """CREATE INDEX IF NOT EXISTS idx_decision_timestamp
                        ON decision_log(timestamp)""",
                        """CREATE INDEX IF NOT EXISTS idx_decision_coordinator
                        ON decision_log(coordinator_id)""",
                        """CREATE INDEX IF NOT EXISTS idx_decision_scope
                        ON decision_log(scope)""",
                    ])

                # -- Compliance log ------------------------------------------
                if not await self._create_table_safe(db, "compliance_log", [
                    """CREATE TABLE IF NOT EXISTS compliance_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        decision_id INTEGER,
                        scope TEXT NOT NULL DEFAULT 'house',
                        device_type TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        commanded_state TEXT NOT NULL,
                        actual_state TEXT NOT NULL,
                        compliant BOOLEAN NOT NULL,
                        deviation_details TEXT,
                        override_detected BOOLEAN,
                        override_source TEXT,
                        override_duration_minutes INTEGER,
                        FOREIGN KEY (decision_id) REFERENCES decision_log(id)
                    )""",
                ]):
                    failed_tables.append("compliance_log")
                else:
                    # Migrate scope column for pre-c0.4 DBs
                    try:
                        cursor = await db.execute("PRAGMA table_info(compliance_log)")
                        cl_columns = {row[1] for row in await cursor.fetchall()}
                        if "scope" not in cl_columns:
                            await db.execute(
                                "ALTER TABLE compliance_log ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"
                            )
                            await db.commit()
                    except Exception as e:
                        _LOGGER.warning("compliance_log scope migration failed: %s", e)

                    await self._create_table_safe(db, "compliance_log_indexes", [
                        """CREATE INDEX IF NOT EXISTS idx_compliance_decision
                        ON compliance_log(decision_id)""",
                        """CREATE INDEX IF NOT EXISTS idx_compliance_timestamp
                        ON compliance_log(timestamp)""",
                        """CREATE INDEX IF NOT EXISTS idx_compliance_scope
                        ON compliance_log(scope)""",
                    ])

                # -- Anomaly log ---------------------------------------------
                if not await self._create_table_safe(db, "anomaly_log", [
                    # v4.6.7: 5 metric columns (observed_value, expected_mean,
                    # expected_std, z_score, sample_size) relaxed from NOT NULL
                    # to NULL. Pre-v4.6.7 the DAO synthesized 0.0 sentinel
                    # values when the AnomalyEvent dataclass field was None —
                    # caught and partially fixed in v4.6.3 B1, but the
                    # sentinel masked the difference between a true
                    # "baseline not yet learned" observation and a legitimate
                    # 0.0 value. Now NULL is the honest "no baseline yet"
                    # marker. Existing DBs are migrated via the rebuild
                    # dance below (gated PRAGMA user_version=467).
                    # v4.7.12 D1: ``anomaly_type`` is the canonical
                    # discriminator going forward. ``event_class`` is kept
                    # as a deprecated alias column during the dual-write
                    # window so rollback to v4.7.11 can still read pre-
                    # rename rows. Both columns carry the same value during
                    # the transition window. v5.0 drops ``event_class``.
                    #
                    # v4.7.12 Reviewer A fix-up (A1): the base CREATE TABLE
                    # below intentionally OMITS both ``event_class`` and
                    # ``anomaly_type``. The v4.6.1 ALTER tuple list at
                    # ~line 1241 adds them in the canonical post-base order
                    # so fresh-install and upgrade-install paths converge
                    # on identical PRAGMA table_info column ordering. This
                    # preserves the planning doc §10 invariant: "Fresh-install
                    # CREATE TABLE produces a row layout identical to an
                    # upgrade-installed table." Locked in by
                    # ``test_fresh_vs_upgrade_schema_column_order_identical``.
                    """CREATE TABLE IF NOT EXISTS anomaly_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        metric_name TEXT NOT NULL,
                        observed_value REAL,
                        expected_mean REAL,
                        expected_std REAL,
                        z_score REAL,
                        severity TEXT NOT NULL,
                        sample_size INTEGER,
                        house_state TEXT,
                        context_json TEXT,
                        resolved BOOLEAN NOT NULL DEFAULT 0,
                        resolution_notes TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp
                    ON anomaly_log(timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator
                    ON anomaly_log(coordinator_id)""",
                    """CREATE INDEX IF NOT EXISTS idx_anomaly_scope
                    ON anomaly_log(scope)""",
                    """CREATE INDEX IF NOT EXISTS idx_anomaly_severity
                    ON anomaly_log(severity)""",
                ]):
                    failed_tables.append("anomaly_log")

                # -- Optimization findings (Phase 1 — Optimization Coord) ----
                # Mirrors the anomaly_log shape so reviewers + analytics
                # tooling can read it the same way. Single-path writer is
                # ``log_finding`` below; pruner is ``prune_optimization_findings``.
                if not await self._create_table_safe(db, "optimization_findings", [
                    """CREATE TABLE IF NOT EXISTS optimization_findings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        target_id TEXT,
                        dimension TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        confidence REAL,
                        score REAL,
                        description TEXT NOT NULL,
                        proposed_action_json TEXT,
                        action_class TEXT,
                        applied_action_id TEXT,
                        applied_outcome TEXT,
                        predicted_effect_json TEXT,
                        observed_effect_json TEXT,
                        payload_json TEXT,
                        created_by TEXT NOT NULL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_optfindings_timestamp
                    ON optimization_findings(timestamp DESC)""",
                    """CREATE INDEX IF NOT EXISTS idx_optfindings_level_target
                    ON optimization_findings(level, target_id)""",
                    """CREATE INDEX IF NOT EXISTS idx_optfindings_dimension_severity
                    ON optimization_findings(dimension, severity)""",
                    """CREATE INDEX IF NOT EXISTS idx_optfindings_outcome
                    ON optimization_findings(applied_outcome)""",
                ]):
                    failed_tables.append("optimization_findings")

                # -- Optimization daily digest (Phase 3 — v4.7.36) -----------
                # One row per (date, generated_at) — the optimizer writes
                # one row per digest fire (morning/evening). Mirrors the
                # ``optimization_findings`` shape; pruned by
                # ``prune_optimization_daily_digest`` (90-day retention).
                # v4.7.36 fix-up B2: UNIQUE(date) so morning+evening digest
                # writes for the SAME date upsert into the same row instead
                # of appending duplicates. Multi-person notifications fire N
                # times per day; without UNIQUE the table would grow by N
                # rows/day with identical payloads.
                # -- Optimizer shadow-accuracy samples (v5.11.0 D2) ----------
                # Persists per-cycle shadow-accuracy sample tuples so the
                # rolling accuracy % survives HA restarts. Without this,
                # the 7-day window resets to zero on every restart and the
                # `warming_up` gate never closes (blocks L1->L2 promotion).
                # Writes are BATCHED per cycle via
                # ``log_shadow_samples_batch`` — NEVER per-sample (that was
                # the v5.0-v5.2 write-flood pattern).
                if not await self._create_table_safe(
                    db, "optimizer_shadow_samples", [
                    """CREATE TABLE IF NOT EXISTS optimizer_shadow_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        observed_at TEXT NOT NULL,
                        dimension TEXT NOT NULL,
                        target_id TEXT,
                        matched INTEGER NOT NULL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_optshadow_observed_at
                    ON optimizer_shadow_samples(observed_at DESC)""",
                    """CREATE INDEX IF NOT EXISTS idx_optshadow_dimension
                    ON optimizer_shadow_samples(dimension)""",
                ]):
                    failed_tables.append("optimizer_shadow_samples")

                if not await self._create_table_safe(db, "optimization_daily_digest", [
                    """CREATE TABLE IF NOT EXISTS optimization_daily_digest (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL UNIQUE,
                        generated_at TEXT NOT NULL,
                        findings_count INTEGER NOT NULL,
                        by_severity_json TEXT,
                        by_dimension_json TEXT,
                        summary_json TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_optdigest_date
                    ON optimization_daily_digest(date DESC)""",
                    """CREATE INDEX IF NOT EXISTS idx_optdigest_generated
                    ON optimization_daily_digest(generated_at DESC)""",
                ]):
                    failed_tables.append("optimization_daily_digest")

                # -- Metric baselines ----------------------------------------
                # F11 (v5.12.0, revised v5.13.1): the `metric_name` column
                # has ONE reserved prefix — `_migration` — used by
                # schema/scope migrations to persist an INFORMATIONAL
                # sentinel row. The sentinel records that a migration path
                # has executed at least once; it does NOT gate rewrites
                # (the rewrite branches are per-row idempotent and re-run
                # every boot so a boot-1 discovery race doesn't strand
                # rows). See `energy.py::_restore_energy_baselines` for the
                # `_migration/circuit_scope_v2` sentinel. Real coordinators
                # MUST NOT emit metrics whose name starts with `_`.
                if not await self._create_table_safe(db, "metric_baselines", [
                    """CREATE TABLE IF NOT EXISTS metric_baselines (
                        coordinator_id TEXT NOT NULL,
                        metric_name TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        mean REAL NOT NULL,
                        variance REAL NOT NULL,
                        sample_count INTEGER NOT NULL,
                        last_updated TEXT,
                        PRIMARY KEY (coordinator_id, metric_name, scope)
                    )""",
                ]):
                    failed_tables.append("metric_baselines")

                # -- Outcome log ---------------------------------------------
                if not await self._create_table_safe(db, "outcome_log", [
                    """CREATE TABLE IF NOT EXISTS outcome_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        scope TEXT NOT NULL DEFAULT 'house',
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        decisions_in_period INTEGER,
                        compliance_rate REAL,
                        override_count INTEGER,
                        metrics_json TEXT NOT NULL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_outcome_coordinator
                    ON outcome_log(coordinator_id)""",
                    """CREATE INDEX IF NOT EXISTS idx_outcome_scope
                    ON outcome_log(scope)""",
                ]):
                    failed_tables.append("outcome_log")

                # -- Parameter beliefs ---------------------------------------
                if not await self._create_table_safe(db, "parameter_beliefs", [
                    """CREATE TABLE IF NOT EXISTS parameter_beliefs (
                        coordinator_id TEXT NOT NULL,
                        parameter_name TEXT NOT NULL,
                        mean REAL NOT NULL,
                        std REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (coordinator_id, parameter_name)
                    )""",
                ]):
                    failed_tables.append("parameter_beliefs")

                # -- Parameter history ---------------------------------------
                if not await self._create_table_safe(db, "parameter_history", [
                    """CREATE TABLE IF NOT EXISTS parameter_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        parameter_name TEXT NOT NULL,
                        old_value REAL,
                        new_value REAL NOT NULL,
                        reason TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_param_history
                    ON parameter_history(coordinator_id, parameter_name)""",
                ]):
                    failed_tables.append("parameter_history")

                # -- Notification log ----------------------------------------
                if not await self._create_table_safe(db, "notification_log", [
                    """CREATE TABLE IF NOT EXISTS notification_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        hazard_type TEXT,
                        location TEXT,
                        person_id TEXT,
                        channel TEXT,
                        delivered INTEGER DEFAULT 0,
                        acknowledged INTEGER DEFAULT 0,
                        ack_time TEXT,
                        cooldown_expires TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_notification_log_date
                    ON notification_log(timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_notification_log_pending
                    ON notification_log(person_id, delivered, severity)""",
                ]):
                    failed_tables.append("notification_log")

                # -- Notification inbound ------------------------------------
                if not await self._create_table_safe(db, "notification_inbound", [
                    """CREATE TABLE IF NOT EXISTS notification_inbound (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        person_id TEXT,
                        channel TEXT NOT NULL,
                        raw_text TEXT NOT NULL,
                        parsed_command TEXT,
                        response_text TEXT,
                        alert_id INTEGER,
                        success INTEGER NOT NULL DEFAULT 0
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_notification_inbound_date
                    ON notification_inbound(timestamp)""",
                ]):
                    failed_tables.append("notification_inbound")

                # -- House state log -----------------------------------------
                if not await self._create_table_safe(db, "house_state_log", [
                    """CREATE TABLE IF NOT EXISTS house_state_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        state TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        trigger TEXT,
                        previous_state TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_house_state_timestamp
                    ON house_state_log(timestamp)""",
                ]):
                    failed_tables.append("house_state_log")

                # -- Energy daily --------------------------------------------
                if not await self._create_table_safe(db, "energy_daily", [
                    """CREATE TABLE IF NOT EXISTS energy_daily (
                        date TEXT PRIMARY KEY,
                        import_kwh REAL NOT NULL DEFAULT 0,
                        export_kwh REAL NOT NULL DEFAULT 0,
                        import_cost REAL NOT NULL DEFAULT 0,
                        export_credit REAL NOT NULL DEFAULT 0,
                        net_cost REAL NOT NULL DEFAULT 0,
                        consumption_kwh REAL,
                        solar_production_kwh REAL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_energy_daily_date
                    ON energy_daily(date DESC)""",
                ]):
                    failed_tables.append("energy_daily")

                # -- Energy peak import --------------------------------------
                if not await self._create_table_safe(db, "energy_peak_import", [
                    """CREATE TABLE IF NOT EXISTS energy_peak_import (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        seq INTEGER NOT NULL,
                        import_kw REAL NOT NULL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_energy_peak_import_seq
                    ON energy_peak_import(seq ASC)""",
                ]):
                    failed_tables.append("energy_peak_import")

                # -- EVSE state ----------------------------------------------
                if not await self._create_table_safe(db, "evse_state", [
                    """CREATE TABLE IF NOT EXISTS evse_state (
                        evse_id TEXT PRIMARY KEY,
                        paused_by_energy INTEGER NOT NULL DEFAULT 0,
                        excess_solar_active INTEGER NOT NULL DEFAULT 0,
                        updated_at DATETIME NOT NULL
                    )""",
                ]):
                    failed_tables.append("evse_state")

                # -- v3.13.0: Circuit state persistence ----------------------
                if not await self._create_table_safe(db, "circuit_state", [
                    """CREATE TABLE IF NOT EXISTS circuit_state (
                        circuit_id TEXT PRIMARY KEY,
                        was_loaded INTEGER NOT NULL DEFAULT 0,
                        zero_since TEXT,
                        alerted INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )""",
                ]):
                    failed_tables.append("circuit_state")

                # -- v3.15.0: Envoy cache (last-known sensor values) ----------
                if not await self._create_table_safe(db, "envoy_cache", [
                    """CREATE TABLE IF NOT EXISTS envoy_cache (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        soc REAL,
                        net_power REAL,
                        solar_production REAL,
                        battery_power REAL,
                        battery_capacity REAL,
                        lifetime_net_import REAL,
                        lifetime_net_export REAL,
                        lifetime_production REAL,
                        lifetime_consumption REAL,
                        lifetime_battery_charged REAL,
                        lifetime_battery_discharged REAL,
                        updated_at TEXT NOT NULL
                    )""",
                ]):
                    failed_tables.append("envoy_cache")

                # -- v3.15.0: Midnight snapshots (lifetime sensor values) ------
                if not await self._create_table_safe(db, "energy_midnight_snapshot", [
                    """CREATE TABLE IF NOT EXISTS energy_midnight_snapshot (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        snapshot_date TEXT NOT NULL,
                        lifetime_consumption REAL,
                        lifetime_production REAL,
                        lifetime_net_import REAL,
                        lifetime_net_export REAL,
                        lifetime_battery_charged REAL,
                        lifetime_battery_discharged REAL,
                        import_kwh_today REAL NOT NULL DEFAULT 0,
                        export_kwh_today REAL NOT NULL DEFAULT 0,
                        import_cost_today REAL NOT NULL DEFAULT 0,
                        export_credit_today REAL NOT NULL DEFAULT 0,
                        net_cost_today REAL NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )""",
                ]):
                    failed_tables.append("energy_midnight_snapshot")

                # -- v3.15.0: Generic energy state key-value store -------------
                if not await self._create_table_safe(db, "energy_state", [
                    """CREATE TABLE IF NOT EXISTS energy_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                ]):
                    failed_tables.append("energy_state")

                # -- v3.20.0: Room automation state persistence -------------
                if not await self._create_table_safe(db, "room_state", [
                    """CREATE TABLE IF NOT EXISTS room_state (
                        room_id TEXT PRIMARY KEY,
                        became_occupied_time TEXT,
                        last_occupied_state INTEGER NOT NULL DEFAULT 0,
                        occupancy_first_detected TEXT,
                        failsafe_fired INTEGER NOT NULL DEFAULT 0,
                        last_trigger_source TEXT,
                        last_lux_zone TEXT,
                        last_timed_open_date TEXT,
                        last_timed_close_date TEXT,
                        updated_at TEXT NOT NULL
                    )""",
                ]):
                    failed_tables.append("room_state")

                # -- v4.2.28: Room energy baseline persistence ----------------
                # Survives restarts so STATE_ENERGY_TODAY isn't reset to 0 on
                # every coordinator reload. Tracks one row per (room, sensor)
                # to support multi-energy-sensor rooms (v4.1.0+).
                # needs_reset=1 means baseline is stale (sensor was unavailable
                # at midnight reset); next available reading sets baseline=now
                # and clears the flag.
                if not await self._create_table_safe(db, "room_energy_baselines", [
                    """CREATE TABLE IF NOT EXISTS room_energy_baselines (
                        room_id TEXT NOT NULL,
                        sensor_id TEXT NOT NULL,
                        baseline_value REAL NOT NULL,
                        baseline_set_at TEXT NOT NULL,
                        needs_reset INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (room_id, sensor_id)
                    )""",
                ]):
                    failed_tables.append("room_energy_baselines")

                # -- v4.3.0 D4: Arbitrage cycle accounting -----------------------
                # One row per off-peak arbitrage decision cycle (5-min interval)
                # where charge_from_grid was active. Used to compute today/month/
                # total savings, the counterfactual on PredictedBillSensor, and
                # the rolling 7-day pace projection.
                if not await self._create_table_safe(db, "arbitrage_cycles", [
                    """CREATE TABLE IF NOT EXISTS arbitrage_cycles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        soc_before REAL,
                        soc_after REAL,
                        kwh_charged REAL NOT NULL,
                        off_peak_rate REAL NOT NULL,
                        displaced_rate REAL NOT NULL,
                        round_trip_efficiency REAL NOT NULL DEFAULT 0.90,
                        savings REAL NOT NULL,
                        season TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_arbitrage_cycles_timestamp
                    ON arbitrage_cycles(timestamp)""",
                ]):
                    failed_tables.append("arbitrage_cycles")

                # -- Energy Savings Unification (cycle #7) ---------------------
                # Baseline snapshot per savings component. One row per
                # component (arbitrage / peak_avoidance / kwh_avoided) written
                # ONCE at cutover; the lifetime sensor renders
                # `baseline + rollup_since_baseline` so a prune of any
                # rollup-source table cannot silently shrink the number.
                if not await self._create_table_safe(
                    db, "savings_lifetime_baseline", [
                    """CREATE TABLE IF NOT EXISTS savings_lifetime_baseline (
                        component TEXT PRIMARY KEY,
                        baseline_usd REAL NOT NULL DEFAULT 0.0,
                        baseline_kwh REAL NOT NULL DEFAULT 0.0,
                        first_recorded_iso TEXT NOT NULL
                    )""",
                ]):
                    failed_tables.append("savings_lifetime_baseline")

                # -- Activity log -----------------------------------------------
                if not await self._create_table_safe(db, "ura_activity_log", [
                    """CREATE TABLE IF NOT EXISTS ura_activity_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator TEXT NOT NULL,
                        action TEXT NOT NULL,
                        room TEXT,
                        zone TEXT,
                        importance TEXT NOT NULL DEFAULT 'info',
                        description TEXT NOT NULL,
                        details_json TEXT,
                        entity_id TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp
                    ON ura_activity_log(timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_activity_log_coordinator
                    ON ura_activity_log(coordinator, timestamp)""",
                ]):
                    failed_tables.append("ura_activity_log")

                # -- v4.0.0-B1: Bayesian beliefs persistence ------------------
                if not await self._create_table_safe(db, "bayesian_beliefs", [
                    """CREATE TABLE IF NOT EXISTS bayesian_beliefs (
                        person_id TEXT NOT NULL,
                        time_bin INTEGER NOT NULL,
                        day_type INTEGER NOT NULL,
                        room_id TEXT NOT NULL,
                        alpha REAL NOT NULL,
                        observation_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (person_id, time_bin, day_type, room_id)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_bayesian_person
                    ON bayesian_beliefs(person_id)""",
                ]):
                    failed_tables.append("bayesian_beliefs")

                # -- v4.0.0-B2: Prediction results for accuracy tracking ------
                if not await self._create_table_safe(db, "prediction_results", [
                    """CREATE TABLE IF NOT EXISTS prediction_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        prediction_timestamp DATETIME NOT NULL,
                        prediction_type TEXT NOT NULL,
                        predicted_value TEXT,
                        confidence REAL,
                        actual_value TEXT,
                        error_value REAL
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_prediction_results_ts
                    ON prediction_results(prediction_timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_prediction_results_type
                    ON prediction_results(prediction_type, prediction_timestamp)""",
                ]):
                    failed_tables.append("prediction_results")

                # -- v4.1.0: Room power profiles for B4 energy integration ---
                if not await self._create_table_safe(db, "room_power_profiles", [
                    """CREATE TABLE IF NOT EXISTS room_power_profiles (
                        room_id TEXT NOT NULL,
                        time_bin INTEGER NOT NULL,
                        day_type INTEGER NOT NULL,
                        avg_watts REAL NOT NULL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (room_id, time_bin, day_type)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_power_profiles_room
                    ON room_power_profiles(room_id)""",
                ]):
                    failed_tables.append("room_power_profiles")

                # -- v4.5.11: AC ramp-down per-zone-per-day state -------------
                # Compressor protection requires daily counters + min-interval
                # gates that survive HA restart. Otherwise restart loops bypass
                # the cap and could fire 3+ hard resets in minutes (warranty-
                # voiding short-cycling). One row per (zone_id, date).
                # Min-interval gate queries MAX(last_hard_reset_ts) without
                # date filter to catch the 23:59 -> 00:01 day-rollover edge.
                if not await self._create_table_safe(db, "ac_reset_state", [
                    """CREATE TABLE IF NOT EXISTS ac_reset_state (
                        zone_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        soft_nudge_count INTEGER NOT NULL DEFAULT 0,
                        hard_reset_count INTEGER NOT NULL DEFAULT 0,
                        last_soft_nudge_ts TEXT,
                        last_hard_reset_ts TEXT,
                        last_overshoot_ts TEXT,
                        in_flight_nudge_original_target REAL,
                        in_flight_nudge_started_ts TEXT,
                        in_flight_nudge_duration_s INTEGER,
                        lockout_flag INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (zone_id, date)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_ac_reset_state_zone
                    ON ac_reset_state(zone_id, date DESC)""",
                ]):
                    failed_tables.append("ac_reset_state")

                # -- v4.7.8: Egress Window HVAC Pause persistent state -------
                # One row per canonical HVAC zone. Tracks the 5-state lifecycle
                # (counting / paused / resume_countdown / cooldown). Survives
                # HA restart so all four restart scenarios (R1-R4) reach the
                # correct first-tick action without losing accumulated time.
                # PRIMARY KEY (zone_id) — egress pause is a per-zone lifecycle,
                # not a daily-bucketed counter (differs from ac_reset_state on
                # purpose; idle rows are never written, in-flight states are
                # the only persisted rows).
                if not await self._create_table_safe(db, "egress_state", [
                    """CREATE TABLE IF NOT EXISTS egress_state (
                        zone_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        first_open_at TEXT,
                        first_closed_at TEXT,
                        paused_at TEXT,
                        saved_hvac_mode TEXT,
                        saved_preset_mode TEXT,
                        triggered_by_room TEXT,
                        thermostat_entity TEXT,
                        cooldown_expires_at TEXT,
                        last_update_ts TEXT NOT NULL,
                        PRIMARY KEY (zone_id)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_egress_state_state
                    ON egress_state(state)""",
                ]):
                    failed_tables.append("egress_state")

                # Fan-noise Mode-2 mitigation: per-room state machine row,
                # persists across HA restart. Mirrors v4.7.8 egress_state shape.
                if not await self._create_table_safe(db, "fan_recheck_state", [
                    """CREATE TABLE IF NOT EXISTS fan_recheck_state (
                        room_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        state_entered_at TEXT,
                        snapshot_json TEXT,
                        attempts_in_hour INTEGER NOT NULL DEFAULT 0,
                        last_outcome TEXT,
                        last_attempt_at TEXT,
                        ble_ladder_layer TEXT,
                        last_update_ts TEXT NOT NULL,
                        PRIMARY KEY (room_id)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_fan_recheck_state_state
                    ON fan_recheck_state(state)""",
                ]):
                    failed_tables.append("fan_recheck_state")

                # -- v4.5.11: AC ramp-down append-only event log --------------
                # Every state transition logged for offline analysis. 30-day
                # rolling retention (auto-prune during day rollover).
                if not await self._create_table_safe(db, "ac_ramp_events", [
                    """CREATE TABLE IF NOT EXISTS ac_ramp_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        zone_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        triggered_by TEXT NOT NULL DEFAULT 'auto',
                        current_temp REAL,
                        target_high REAL,
                        kwh_rate_before REAL,
                        kwh_rate_after REAL,
                        action_taken TEXT,
                        soft_nudge_count_today INTEGER,
                        hard_reset_count_today INTEGER,
                        lockout_triggered INTEGER NOT NULL DEFAULT 0,
                        notes TEXT,
                        effective INTEGER,
                        preset_before TEXT,
                        preset_after TEXT,
                        mode_before TEXT,
                        mode_after TEXT,
                        restore_ok INTEGER,
                        restore_ok_immediate INTEGER
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_ac_ramp_events_zone_ts
                    ON ac_ramp_events(zone_id, timestamp)""",
                    """CREATE INDEX IF NOT EXISTS idx_ac_ramp_events_ts
                    ON ac_ramp_events(timestamp)""",
                ]):
                    failed_tables.append("ac_ramp_events")

                # -- HVAC-GOVERNED-EXCURSION-1 D2 (persistence) --------------
                # hvac_excursion_state: PER-ZONE persisted lease + snapshot
                # row (§4.5 of PLANNING_hvac_governed_excursion.md). PK is
                # zone_id — at most one live excursion per zone at a time.
                # The row IS the lease token (§4.4). REBUILD cache is
                # populated from this table by async_startup_excursion_audit.
                if not await self._create_table_safe(
                    db, "hvac_excursion_state", [
                        """CREATE TABLE IF NOT EXISTS hvac_excursion_state (
                            zone_id TEXT PRIMARY KEY,
                            excursion_id TEXT NOT NULL,
                            kind TEXT NOT NULL,
                            started_ts TEXT NOT NULL,
                            duration_s INTEGER,
                            pre_preset TEXT,
                            pre_target_low REAL,
                            pre_target_high REAL,
                            excursion_target_low REAL,
                            excursion_target_high REAL,
                            intended_mode TEXT NOT NULL,
                            caller_site TEXT NOT NULL
                        )""",
                    ]
                ):
                    failed_tables.append("hvac_excursion_state")

                # hvac_excursion_events: non-nudge outcome landing table
                # (§4.5). Nudge continues writing to ac_ramp_events (via
                # the new excursion_id column), preserving D1 sensors + AC8
                # rate comparison. One row per return/expiry.
                if not await self._create_table_safe(
                    db, "hvac_excursion_events", [
                        """CREATE TABLE IF NOT EXISTS hvac_excursion_events (
                            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            excursion_id TEXT NOT NULL,
                            zone_id TEXT NOT NULL,
                            kind TEXT NOT NULL,
                            started_ts TEXT NOT NULL,
                            ended_ts TEXT,
                            trigger TEXT,
                            trigger_detail TEXT,
                            site TEXT,
                            duration_actual_s INTEGER,
                            pre_preset TEXT,
                            pre_target_low REAL,
                            pre_target_high REAL,
                            preset_after TEXT,
                            target_low_after REAL,
                            target_high_after REAL,
                            mode_before TEXT,
                            mode_after TEXT,
                            restore_ok INTEGER,
                            restore_ok_immediate INTEGER
                        )""",
                        """CREATE INDEX IF NOT EXISTS idx_hvac_excursion_events_zone_ts
                        ON hvac_excursion_events(zone_id, started_ts)""",
                        """CREATE INDEX IF NOT EXISTS idx_hvac_excursion_events_excursion_id
                        ON hvac_excursion_events(excursion_id)""",
                    ]
                ):
                    failed_tables.append("hvac_excursion_events")

                # -- Hierarchical memory MVP (2026-08-02) --------------------
                # See docs/planning/ARCHITECTURE_hierarchical_memory.md §4/§5c.
                # memory_episodes: adjudicated notable events per node.
                # memory_facts: consolidated tier (compactor DEFERRED per
                # MVP parsimony pass; table + supersession ship, distill/
                # correct/redact not yet).
                if not await self._create_table_safe(db, "memory_episodes", [
                    """CREATE TABLE IF NOT EXISTS memory_episodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        node_id TEXT NOT NULL,
                        episode_type TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        adjudication TEXT NOT NULL DEFAULT 'unadjudicated',
                        adjudicated_at TEXT,
                        adjudicated_by TEXT,
                        attrs_json TEXT NOT NULL DEFAULT '{}',
                        source_ref TEXT
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_episodes_node_type
                    ON memory_episodes(node_id, episode_type, started_at)""",
                ]):
                    failed_tables.append("memory_episodes")

                if not await self._create_table_safe(db, "memory_facts", [
                    """CREATE TABLE IF NOT EXISTS memory_facts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        node_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        statement TEXT NOT NULL,
                        attrs_json TEXT NOT NULL DEFAULT '{}',
                        confidence REAL NOT NULL,
                        derived_from TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        superseded_by INTEGER,
                        UNIQUE(node_id, topic, statement)
                    )""",
                    """CREATE INDEX IF NOT EXISTS idx_facts_node_topic
                    ON memory_facts(node_id, topic)""",
                ]):
                    failed_tables.append("memory_facts")

                # Seed F1-F4 facts idempotently — per-row INSERT OR IGNORE
                # (HIGH A2). The UNIQUE(node_id, topic, statement) index
                # makes re-init a no-op regardless of any pre-existing
                # partial seed shape.
                try:
                    from .const import MEMORY_SEED_FACTS  # noqa: PLC0415
                    _now_iso = datetime.now(timezone.utc).isoformat()
                    inserted = 0
                    for fact in MEMORY_SEED_FACTS:
                        cur = await db.execute(
                            """INSERT OR IGNORE INTO memory_facts (
                                node_id, topic, statement, attrs_json,
                                confidence, derived_from, created_at,
                                superseded_by
                            ) VALUES (?, ?, ?, '{}', ?, ?, ?, NULL)""",
                            (
                                fact["node_id"], fact["topic"],
                                fact["statement"],
                                float(fact["confidence"]),
                                fact["derived_from"], _now_iso,
                            ),
                        )
                        if cur.rowcount:
                            inserted += int(cur.rowcount)
                    await db.commit()
                    if inserted:
                        _LOGGER.info(
                            "memory_facts seeded with %d new rows "
                            "(F1-F4; idempotent INSERT OR IGNORE)",
                            inserted,
                        )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning("memory_facts seed failed: %s", e)

                # ============================================================
                # Schema migrations (per-table, safe)
                # ============================================================

                # v4.7.17.1: Add `effective` column to ac_ramp_events
                # (NULL = "inconclusive / excluded from FP stats"). Existing
                # rows pre-deploy stay NULL and are excluded from the new
                # FP rate computation, which falls back to the old before/
                # after derivation for those rows.
                try:
                    cursor = await db.execute("PRAGMA table_info(ac_ramp_events)")
                    are_columns = {row[1] for row in await cursor.fetchall()}
                    if "effective" not in are_columns:
                        await db.execute(
                            "ALTER TABLE ac_ramp_events ADD COLUMN effective INTEGER"
                        )
                    # HVAC-GOVERNED-EXCURSION-1 D1: additive observability
                    # columns capturing preset/mode state around the nudge
                    # lifecycle. ADD COLUMN is O(1) — SQLite records the
                    # new column in the schema only; existing rows are not
                    # rewritten (they read as NULL). Safe on the live
                    # 1.18 GB DB. Each column is guarded individually so a
                    # partially-migrated DB (interrupted deploy) converges.
                    for _col, _decl in (
                        ("preset_before", "TEXT"),
                        ("preset_after", "TEXT"),
                        ("mode_before", "TEXT"),
                        ("mode_after", "TEXT"),
                        ("restore_ok", "INTEGER"),
                        ("restore_ok_immediate", "INTEGER"),
                        # HVAC-GOVERNED-EXCURSION-1 D2: cross-table analytics
                        # join key between ac_ramp_events (nudge home) and
                        # hvac_excursion_events (non-nudge). Nullable — rows
                        # written before the primitive migration are NULL.
                        ("excursion_id", "TEXT"),
                        # AC-RAMP-PIPELINE-HARDENING-1:
                        # D-SCORE: delayed durability classifier writes onto
                        # the nudge_evaluated row via event_id UPDATE.
                        ("durable", "INTEGER"),
                        ("durable_minutes", "INTEGER"),
                        # D6: reset-outcome drift discriminator (justified_ramp
                        # / floor_survived / inconclusive).
                        ("reset_outcome", "TEXT"),
                        # D6 (bounded add): kW draw captured at the SAME
                        # settle moment as `reset_outcome`. Answers "did
                        # the unit come back at a lower output stage."
                        # NULL when the settle read fails; row still
                        # writes and `reset_outcome` is unaffected.
                        ("kwh_rate_settle", "REAL"),
                        # F13 fix-up (2026-08-22): dedicated column for
                        # the D6 settle-time temperature so it stops
                        # overwriting `current_temp` (the completion-
                        # time reading). Pre-fix, an unreadable settle
                        # entity would write NULL over a real value.
                        ("current_temp_settle", "REAL"),
                        # F9 fix-up: distinct preset-restore verdict so
                        # a swallowed preset failure in the
                        # hard_reset_completed success branch does not
                        # get conflated with combined restore_ok.
                        ("preset_restore_ok", "INTEGER"),
                        # F19 fix-up (2026-08-22): the settled-restore
                        # verdict was previously written on top of
                        # `preset_after`/`mode_after` — that destroyed
                        # the immediate-sample value, so the
                        # (immediate=1, settled=0) signature (the
                        # load-bearing clobber signature) could never
                        # be inspected for what the immediate preset
                        # actually was. New columns preserve both.
                        ("preset_settled", "TEXT"),
                        ("mode_settled", "TEXT"),
                        # F5 fix-up ruling (2026-08-22): explicit
                        # truncated flag replaces the durable_minutes
                        # >= 15 min proxy. Set in _write_durable at
                        # the point the branch is already known.
                        # NULL for pre-migration rows; sensor excludes
                        # NULLs from both durability rates.
                        ("truncated", "INTEGER"),
                        # F8 (revised): populated by the settled-restore
                        # callback under option (c) — a NULL restore_ok
                        # with an explicit reason. Named blocker today:
                        # `stale_polled_integration` (ha_carrier's
                        # 30-min poll means hass.states cannot observe
                        # the preset write). See hvac_const.py
                        # AC_NUDGE_RESTORE_SETTLED_UNMEASURABLE_REASON
                        # and the CARRIER-STALE-POLL-REFRESH-1 card.
                        ("settled_reason", "TEXT"),
                    ):
                        if _col not in are_columns:
                            await db.execute(
                                f"ALTER TABLE ac_ramp_events ADD COLUMN {_col} {_decl}"
                            )
                    await db.commit()
                except Exception as e:
                    _LOGGER.warning("ac_ramp_events migration failed: %s", e)

                # AC-RAMP-PIPELINE-HARDENING-1 D-PARTITION + D-SCORE:
                # partition counters + night-session date-key +
                # in-flight durable started ts on ac_reset_state.
                # Guarded ALTER modelled on the ac_ramp_events block above.
                try:
                    cursor = await db.execute(
                        "PRAGMA table_info(ac_reset_state)"
                    )
                    ars_columns = {row[1] for row in await cursor.fetchall()}
                    _added_partition_cols = False
                    for _col, _decl in (
                        ("day_reset_count", "INTEGER NOT NULL DEFAULT 0"),
                        ("night_reset_count", "INTEGER NOT NULL DEFAULT 0"),
                        ("night_session_date", "TEXT"),
                        ("in_flight_durable_started_ts", "TEXT"),
                        # A3 fix-up (2026-08-22): companion to
                        # started_ts. Names the specific
                        # ac_ramp_events row the delayed callback is
                        # going to UPDATE, so restart resumption can
                        # write to the correct row without a scan.
                        ("in_flight_durable_event_id", "INTEGER"),
                    ):
                        if _col not in ars_columns:
                            await db.execute(
                                f"ALTER TABLE ac_reset_state ADD COLUMN {_col} {_decl}"
                            )
                            if _col == "day_reset_count":
                                _added_partition_cols = True
                    # AC-RAMP-PIPELINE-HARDENING-1 fix-up F2: migration-day
                    # inflation seed. Existing rows carry a `hard_reset_count`
                    # accumulated under the pre-partition regime; without
                    # this seed a zone that already spent 2 resets today
                    # would get a fresh 2+2 partition budget on top of it
                    # for the rest of upgrade day. Seed day_reset_count from
                    # the existing hard_reset_count on rows written today so
                    # upgrade-day cumulative budget matches pre-migration
                    # intent. Night stays at 0 (a night session that starts
                    # after migration is a fresh bucket by definition).
                    if _added_partition_cols:
                        await db.execute(
                            """UPDATE ac_reset_state
                               SET day_reset_count = hard_reset_count
                               WHERE day_reset_count = 0
                                 AND hard_reset_count > 0
                                 AND date = ?""",
                            (dt_util.now().date().isoformat(),),
                        )
                    await db.commit()
                except Exception as e:
                    _LOGGER.warning("ac_reset_state migration failed: %s", e)

                # v3.5.2: Add columns to room_transitions if absent
                try:
                    cursor = await db.execute("PRAGMA table_info(room_transitions)")
                    columns = {row[1] for row in await cursor.fetchall()}
                    if "validation_method" not in columns:
                        await db.execute(
                            "ALTER TABLE room_transitions ADD COLUMN validation_method TEXT"
                        )
                    if "checkpoint_rooms" not in columns:
                        await db.execute(
                            "ALTER TABLE room_transitions ADD COLUMN checkpoint_rooms TEXT"
                        )
                    await db.commit()
                except Exception as e:
                    _LOGGER.warning("room_transitions migration failed: %s", e)

                # v3.7.12: Add accuracy + temperature columns to energy_daily
                # R1 (2026-07-16): + predicted_consumption_source (source marker
                # for which estimator arm produced predicted_consumption_kwh).
                # Additive migration only.
                try:
                    cursor = await db.execute("PRAGMA table_info(energy_daily)")
                    ed_columns = {row[1] for row in await cursor.fetchall()}
                    for col, col_type in [
                        ("predicted_consumption_kwh", "REAL"),
                        ("avg_temperature", "REAL"),
                        ("prediction_error_pct", "REAL"),
                        ("adjustment_factor", "REAL"),
                        ("predicted_consumption_source", "TEXT"),
                    ]:
                        if col not in ed_columns:
                            await db.execute(
                                f"ALTER TABLE energy_daily ADD COLUMN {col} {col_type}"
                            )
                    await db.commit()
                except Exception as e:
                    _LOGGER.warning("energy_daily migration failed: %s", e)

                # v3.13.0: Add tou_period column to energy_history
                # Column populated by log_energy_history in M2 (v3.13.1)
                try:
                    cursor = await db.execute("PRAGMA table_info(energy_history)")
                    eh_columns = {row[1] for row in await cursor.fetchall()}
                    if "tou_period" not in eh_columns:
                        await db.execute(
                            "ALTER TABLE energy_history ADD COLUMN tou_period TEXT"
                        )
                        await db.commit()
                        _LOGGER.info("Added tou_period column to energy_history")
                except Exception as e:
                    _LOGGER.warning("energy_history tou_period migration failed: %s", e)

                # v4.6.0: Add person_id column to prediction_results for
                # per-person next-room scoring rows. Existing rows
                # (prediction_type='bayesian_occupancy') keep NULL person_id —
                # no backfill required (single-user install).
                try:
                    cursor = await db.execute("PRAGMA table_info(prediction_results)")
                    pr_columns = {row[1] for row in await cursor.fetchall()}
                    if "person_id" not in pr_columns:
                        await db.execute(
                            "ALTER TABLE prediction_results ADD COLUMN person_id TEXT"
                        )
                        await db.commit()
                        _LOGGER.info("Added person_id column to prediction_results")
                except Exception as e:
                    _LOGGER.warning("prediction_results person_id migration failed: %s", e)

                # v4.6.1 D0: Add unified AnomalyEvent columns to anomaly_log.
                # Existing rows get DEFAULT values automatically; no backfill
                # required on this single-user install.
                try:
                    cursor = await db.execute("PRAGMA table_info(anomaly_log)")
                    al_columns = {row[1] for row in await cursor.fetchall()}
                    new_al_cols = [
                        ("event_class", "TEXT DEFAULT 'point_in_time'"),
                        ("recovery_at", "TEXT NULL"),
                        ("correlation_id", "TEXT NULL"),
                        ("entity_id", "TEXT NULL"),
                        ("room_id", "TEXT NULL"),
                        ("person_id", "TEXT NULL"),
                        # v4.7.12 D1: anomaly_type discriminator replaces
                        # event_class as the canonical column name. Kept
                        # additive so upgrade installs gain the new column
                        # without losing the deprecated alias (dual-write
                        # window). v5.0 drops event_class.
                        ("anomaly_type", "TEXT DEFAULT 'point_in_time'"),
                    ]
                    for col_name, col_def in new_al_cols:
                        if col_name not in al_columns:
                            await db.execute(
                                f"ALTER TABLE anomaly_log ADD COLUMN {col_name} {col_def}"
                            )
                    await db.commit()
                    _LOGGER.info("anomaly_log v4.6.1 columns verified/added")
                except Exception as e:
                    _LOGGER.warning("anomaly_log v4.6.1 migration failed: %s", e)

                # NM Cycle B (2026-07-20) B0: additive `dry_run` column on
                # `notification_log`. Existing rows default 0 (real send).
                # Never removes columns, safe to re-run.
                try:
                    cursor = await db.execute("PRAGMA table_info(notification_log)")
                    nl_columns = {row[1] for row in await cursor.fetchall()}
                    if "dry_run" not in nl_columns:
                        await db.execute(
                            "ALTER TABLE notification_log "
                            "ADD COLUMN dry_run INTEGER DEFAULT 0"
                        )
                        await db.commit()
                        _LOGGER.info("Added dry_run column to notification_log (NM Cycle B B0)")
                except Exception as e:
                    _LOGGER.warning("notification_log dry_run migration failed: %s", e)

                # NM Cycle C (2026-07-20) C2: additive audit columns on
                # `notification_log`. Same pattern as B0 dry_run column.
                # All nullable; existing readers unaffected. Cycle C
                # populates them only on routing decisions that emit or
                # are dry-run-logged (see `_emit_audit_row`).
                try:
                    cursor = await db.execute("PRAGMA table_info(notification_log)")
                    nl_columns = {row[1] for row in await cursor.fetchall()}
                    _nm_c_audit_cols = [
                        ("recipient_id", "TEXT"),
                        ("route_reason", "TEXT"),
                        ("dnd_bypass_applied", "INTEGER"),
                        ("bucket_outcome", "TEXT"),
                        ("matrix_branch", "TEXT"),
                    ]
                    for col_name, col_type in _nm_c_audit_cols:
                        if col_name not in nl_columns:
                            await db.execute(
                                f"ALTER TABLE notification_log "
                                f"ADD COLUMN {col_name} {col_type}"
                            )
                    await db.commit()
                    _LOGGER.info(
                        "notification_log NM Cycle C audit columns verified/added",
                    )
                except Exception as e:
                    _LOGGER.warning(
                        "notification_log NM Cycle C audit migration failed: %s", e,
                    )

                # v4.6.1 D1 (review fix F3): backfill old TEXT severity values
                # to numeric-string equivalents matching the unified IntEnum.
                # v4.6.6 (Review A H1): `'critical' → '4'` (was → '2' pre-
                # v4.6.6). AnomalySeverity.CRITICAL moved from value 2 to 4
                # when the enum expanded from 3 to 5 buckets. Any TEXT
                # 'critical' rows surfaced by a stale-DB import AFTER the
                # one-shot D2 remap below has run must land at the new
                # CRITICAL value '4' or they would read back as ADVISORY.
                # ADVISORY/ALERT historical TEXT rows are still collapsed to
                # WARNING ('1') — they were never distinguished pre-v4.6.6
                # so there's no information to recover.
                # Match is by literal value so the UPDATE is idempotent
                # (second run finds 0 matching rows). Single transaction, safe
                # on empty tables.
                try:
                    cursor = await db.execute(
                        """UPDATE anomaly_log
                           SET severity = CASE severity
                               WHEN 'nominal'  THEN '0'
                               WHEN 'advisory' THEN '1'
                               WHEN 'alert'    THEN '1'
                               WHEN 'critical' THEN '4'
                               ELSE severity
                           END
                           WHERE severity IN ('nominal','advisory','alert','critical')"""
                    )
                    await db.commit()
                    if cursor.rowcount > 0:
                        _LOGGER.info(
                            "Backfilled %d legacy TEXT severity values to numeric IntEnum",
                            cursor.rowcount,
                        )
                except Exception as e:
                    _LOGGER.warning("anomaly_log severity backfill failed: %s", e)

                # v4.6.6 D2: severity vocabulary remap.
                # Pre-v4.6.6 the AnomalySeverity IntEnum had 3 buckets where
                # CRITICAL = 2. v4.6.6 expanded to 5 buckets
                # {INFO=0, WARNING=1, ADVISORY=2, ALERT=3, CRITICAL=4} so
                # ADVISORY (z 2-3) and ALERT (z 3-4) persist as distinct
                # integers instead of collapsing to WARNING. Historic CRITICAL
                # rows MUST move from '2' → '4' or they will read back as
                # ADVISORY (the new meaning of value 2) and silently misreport.
                #
                # CRITICAL: this migration is GATED via PRAGMA user_version
                # because it is NOT safe to re-run after v4.6.6 ships. Post-
                # v4.6.6 the WHERE clause `severity='2'` matches LEGITIMATE
                # ADVISORY rows produced by `map_diag_severity('advisory')`
                # in v4.6.6+ emit sites. Without the gate, every restart
                # would silently rewrite ADVISORY rows as CRITICAL — a
                # recurring data-corruption bug caught by v4.6.6 Tier 2-DB
                # Review A (C1). PRAGMA user_version=466 sentinel prevents
                # the second-run case.
                try:
                    cursor = await db.execute("PRAGMA user_version")
                    row = await cursor.fetchone()
                    current_user_version = row[0] if row else 0
                    if current_user_version < 466:
                        cursor = await db.execute(
                            """UPDATE anomaly_log
                               SET severity = '4'
                               WHERE severity = '2'"""
                        )
                        rewritten = cursor.rowcount
                        # Set the sentinel BEFORE the commit so a crash mid-
                        # commit leaves the migration unmarked and we re-try
                        # on next start (acceptable — UPDATE is purely
                        # additive at the row level, no data loss possible).
                        await db.execute("PRAGMA user_version = 466")
                        await db.commit()
                        if rewritten > 0:
                            _LOGGER.info(
                                "v4.6.6 D2 severity remap: rewrote %d historic "
                                "CRITICAL rows from '2' to '4' "
                                "(AnomalySeverity.CRITICAL moved from 2→4). "
                                "user_version set to 466 — migration will not "
                                "re-run.",
                                rewritten,
                            )
                        else:
                            _LOGGER.info(
                                "v4.6.6 D2 severity remap: no historic CRITICAL "
                                "rows to rewrite (DB is fresh or already remapped). "
                                "user_version set to 466 — migration will not re-run."
                            )
                    else:
                        _LOGGER.debug(
                            "v4.6.6 D2 severity remap: user_version=%d ≥ 466, "
                            "skipping (post-v4.6.6 ADVISORY rows would land at "
                            "severity='2' legitimately).",
                            current_user_version,
                        )
                except Exception as e:
                    _LOGGER.warning("v4.6.6 severity remap failed: %s", e)

                # v4.6.7: anomaly_log NOT NULL relaxation for 5 metric
                # columns. Pre-v4.6.7 schema required observed_value,
                # expected_mean, expected_std, z_score, sample_size to be
                # NOT NULL. The DAO synthesized 0.0/0 sentinels when the
                # AnomalyEvent dataclass field was None (v4.6.1.1 / v4.6.3
                # B1 history) — but sentinels mask the difference between
                # "baseline not yet learned" and "legitimate 0.0 observation."
                # NULL is the honest marker.
                #
                # SQLite can't ALTER COLUMN to remove NOT NULL, so this is
                # the table-rebuild dance: create new table with relaxed
                # schema, copy rows, drop old, rename, recreate indexes.
                # Gated via PRAGMA user_version=467 — runs once, ever.
                # The CREATE TABLE block above uses the relaxed schema for
                # fresh DBs; this block handles existing DBs.
                try:
                    cursor = await db.execute("PRAGMA user_version")
                    row = await cursor.fetchone()
                    uv = row[0] if row else 0
                    if uv < 467:
                        # Pre-check: does the existing table have NOT NULL
                        # on observed_value? (PRAGMA table_info returns 1
                        # in column 3 for NOT NULL columns.)
                        cursor = await db.execute("PRAGMA table_info(anomaly_log)")
                        cols = await cursor.fetchall()
                        notnull_cols = {row[1] for row in cols if row[3] == 1}
                        relaxed_targets = {
                            "observed_value", "expected_mean", "expected_std",
                            "z_score", "sample_size",
                        }
                        if not relaxed_targets & notnull_cols:
                            # Already relaxed (fresh DB created with v4.6.7+
                            # DDL) — just bump the sentinel and skip.
                            await db.execute("PRAGMA user_version = 467")
                            await db.commit()
                            _LOGGER.debug(
                                "v4.6.7: anomaly_log NULL columns already "
                                "relaxed (fresh DB). user_version → 467."
                            )
                        else:
                            # Table rebuild dance.
                            await db.execute("BEGIN")
                            # v4.7.12 D1: rebuild target carries the new
                            # ``anomaly_type`` column. If a pre-v4.6.7 DB
                            # upgrades straight to v4.7.12, the v4.6.1
                            # ALTER block (above) has already added the
                            # ``anomaly_type`` column to the old table,
                            # so we must copy it forward here or lose the
                            # backfilled values during the rebuild.
                            await db.execute(
                                """CREATE TABLE anomaly_log_v467 (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    timestamp TEXT NOT NULL,
                                    coordinator_id TEXT NOT NULL,
                                    scope TEXT NOT NULL,
                                    metric_name TEXT NOT NULL,
                                    observed_value REAL,
                                    expected_mean REAL,
                                    expected_std REAL,
                                    z_score REAL,
                                    severity TEXT NOT NULL,
                                    sample_size INTEGER,
                                    house_state TEXT,
                                    context_json TEXT,
                                    resolved BOOLEAN NOT NULL DEFAULT 0,
                                    resolution_notes TEXT,
                                    event_class TEXT,
                                    recovery_at TEXT,
                                    correlation_id TEXT,
                                    entity_id TEXT,
                                    room_id TEXT,
                                    person_id TEXT,
                                    anomaly_type TEXT DEFAULT 'point_in_time'
                                )"""
                            )
                            # v4.6.7 review M2: use an EXPLICIT column list
                            # (NOT `SELECT *`) to handle column-order drift
                            # safely. The v4.6.1 ALTER TABLE appended 6
                            # columns at the end (event_class, recovery_at,
                            # correlation_id, entity_id, room_id, person_id);
                            # `SELECT *` would have been order-dependent and
                            # would have caused silent data loss if column
                            # ordering ever shifted (it has historically).
                            # v4.7.12 D1: copy ``anomaly_type`` forward if
                            # it exists on the source table (pre-v4.6.7 DB
                            # that already ran the v4.6.1 ALTER block above
                            # and got the new column). Fall back to
                            # event_class for the value so the rebuild
                            # preserves the discriminator regardless of
                            # whether the v4.7.12 backfill block has run.
                            src_cols = {row[1] for row in await (
                                await db.execute("PRAGMA table_info(anomaly_log)")
                            ).fetchall()}
                            if "anomaly_type" in src_cols:
                                _src_at_expr = (
                                    "COALESCE(anomaly_type, event_class, 'point_in_time')"
                                )
                            else:
                                _src_at_expr = (
                                    "COALESCE(event_class, 'point_in_time')"
                                )
                            cursor = await db.execute(
                                f"""INSERT INTO anomaly_log_v467
                                    (id, timestamp, coordinator_id, scope,
                                     metric_name, observed_value, expected_mean,
                                     expected_std, z_score, severity,
                                     sample_size, house_state, context_json,
                                     resolved, resolution_notes, event_class,
                                     recovery_at, correlation_id, entity_id,
                                     room_id, person_id, anomaly_type)
                                   SELECT id, timestamp, coordinator_id, scope,
                                          metric_name, observed_value, expected_mean,
                                          expected_std, z_score, severity,
                                          sample_size, house_state, context_json,
                                          resolved, resolution_notes, event_class,
                                          recovery_at, correlation_id, entity_id,
                                          room_id, person_id, {_src_at_expr}
                                   FROM anomaly_log"""
                            )
                            copied = cursor.rowcount
                            await db.execute("DROP TABLE anomaly_log")
                            await db.execute(
                                "ALTER TABLE anomaly_log_v467 RENAME TO anomaly_log"
                            )
                            # Recreate indexes — DROP TABLE removed them.
                            await db.execute(
                                "CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp "
                                "ON anomaly_log(timestamp)"
                            )
                            await db.execute(
                                "CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator "
                                "ON anomaly_log(coordinator_id)"
                            )
                            await db.execute(
                                "CREATE INDEX IF NOT EXISTS idx_anomaly_scope "
                                "ON anomaly_log(scope)"
                            )
                            await db.execute(
                                "CREATE INDEX IF NOT EXISTS idx_anomaly_severity "
                                "ON anomaly_log(severity)"
                            )
                            await db.execute("PRAGMA user_version = 467")
                            await db.commit()
                            _LOGGER.info(
                                "v4.6.7 anomaly_log NULL relaxation: rebuilt "
                                "table with NULL on observed_value/expected_mean/"
                                "expected_std/z_score/sample_size. Copied %d "
                                "rows, recreated 4 indexes. user_version → 467.",
                                copied,
                            )
                    else:
                        _LOGGER.debug(
                            "v4.6.7 anomaly_log NULL relaxation: user_version=%d "
                            "≥ 467, skipping (already relaxed).",
                            uv,
                        )
                except Exception as e:
                    # v4.6.7 review H1: roll back the open transaction so
                    # downstream migration blocks (regime_cell_state etc.)
                    # don't execute against a leaked half-built rebuild
                    # transaction. Without rollback, a CREATE TABLE failure
                    # mid-rebuild would either commit the orphan table
                    # `anomaly_log_v467` on the next `db.commit()`, OR cause
                    # downstream `db.execute()` calls to operate inside the
                    # failed transaction with surprising behavior.
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    # Migration failure is logged but doesn't block startup.
                    # If the rebuild partial-failed, an orphan table named
                    # `anomaly_log_v467` may exist — operator should DROP it
                    # manually and re-run with an investigation.
                    _LOGGER.error(
                        "v4.6.7 anomaly_log NULL relaxation FAILED: %s. "
                        "DB may have an orphan `anomaly_log_v467` table — "
                        "check manually, DROP it if present, then restart.",
                        e,
                    )

                # v4.7.12 D1: anomaly_type discriminator backfill. The
                # new column was added by the v4.6.1 ALTER block above
                # (or by the v4.6.7 rebuild if it ran in this same boot);
                # copy historical event_class values across so consumers
                # that read from either column see consistent data during
                # the dual-write window. Gated on PRAGMA user_version=4712
                # so the UPDATE does not re-run — that would clobber any
                # v4.7.13+ emit that sets anomaly_type independently of
                # event_class (no such caller exists yet, but the gate
                # keeps the migration idempotent for the rollback-and-
                # reapply case).
                try:
                    cursor = await db.execute("PRAGMA user_version")
                    row = await cursor.fetchone()
                    current_user_version = row[0] if row else 0
                    if current_user_version < 4712:
                        cursor = await db.execute(
                            """UPDATE anomaly_log
                               SET anomaly_type = COALESCE(event_class, 'point_in_time')
                               WHERE anomaly_type IS NULL
                                  OR anomaly_type = 'point_in_time'"""
                        )
                        # v4.7.12 Reviewer A fix-up (A2): a driver-reported
                        # rowcount of -1 is indistinguishable from "0 rows
                        # backfilled" once clamped. On an install with
                        # thousands of legacy rows that's the only signal
                        # something is wrong. Log a WARNING before clamping.
                        if cursor.rowcount < 0:
                            _LOGGER.warning(
                                "v4.7.12 D1 anomaly_type backfill: aiosqlite "
                                "reported rowcount=%d (driver weirdness — "
                                "rowcount unavailable). Cannot confirm row "
                                "count; user_version=4712 will still be set.",
                                cursor.rowcount,
                            )
                            backfilled = 0
                        else:
                            backfilled = cursor.rowcount
                        await db.execute("PRAGMA user_version = 4712")
                        await db.commit()
                        _LOGGER.info(
                            "v4.7.12 D1 anomaly_type backfill: copied "
                            "event_class -> anomaly_type on %d rows. "
                            "user_version=4712.",
                            backfilled,
                        )
                    else:
                        _LOGGER.debug(
                            "v4.7.12 D1 anomaly_type backfill: user_version=%d "
                            ">= 4712, skipping (already migrated).",
                            current_user_version,
                        )
                except Exception as e:
                    # v4.7.12 Reviewer A fix-up (A4): backfill failure is a
                    # data-integrity loss — every downstream consumer that
                    # filters on anomaly_type sees historic regime_shift
                    # rows as point_in_time until the next successful
                    # boot. Promote from WARNING to ERROR so anomaly
                    # monitoring catches it.
                    _LOGGER.error(
                        "v4.7.12 D1 anomaly_type backfill failed: %s", e,
                        exc_info=True,
                    )

                # v4.6.2 D4: regime_cell_state tracks consecutive-run counter
                # per (person, time_bin, day_type) cell. Required by the 2-run
                # persistence guard before emitting a regime-shift AnomalyEvent.
                # PRAGMA-checked for idempotency — safe to run on every startup.
                try:
                    cursor = await db.execute("PRAGMA table_info(regime_cell_state)")
                    rcs_cols = {row[1] for row in await cursor.fetchall()}
                    if not rcs_cols:
                        await db.execute(
                            """CREATE TABLE IF NOT EXISTS regime_cell_state (
                                person_id TEXT NOT NULL,
                                time_bin INTEGER NOT NULL,
                                day_type INTEGER NOT NULL,
                                unacknowledged_consecutive INTEGER NOT NULL DEFAULT 0,
                                last_evaluated_at TEXT NOT NULL,
                                last_magnitude_bucket TEXT,
                                PRIMARY KEY (person_id, time_bin, day_type)
                            )"""
                        )
                        await db.commit()
                        _LOGGER.info("Created regime_cell_state table")
                except Exception as e:
                    _LOGGER.warning("regime_cell_state table creation failed: %s", e)

                # v4.6.2 D6: event-mode per-cell cooldown tracker.
                # PRIMARY KEY (person_id, time_bin, day_type) so one UPSERT
                # records the last notified timestamp without row proliferation.
                try:
                    cursor = await db.execute(
                        "PRAGMA table_info(regime_event_notification_log)"
                    )
                    renl_cols = {row[1] for row in await cursor.fetchall()}
                    if not renl_cols:
                        await db.execute(
                            """CREATE TABLE IF NOT EXISTS regime_event_notification_log (
                                person_id TEXT NOT NULL,
                                time_bin INTEGER NOT NULL,
                                day_type INTEGER NOT NULL,
                                last_notified_at TEXT NOT NULL,
                                PRIMARY KEY (person_id, time_bin, day_type)
                            )"""
                        )
                        await db.commit()
                        _LOGGER.info("Created regime_event_notification_log table")
                except Exception as e:
                    _LOGGER.warning(
                        "regime_event_notification_log table creation failed: %s", e
                    )

                # v4.6.2 D6: weekly digest queue — rows enqueued when
                # notification_mode='weekly_digest'; flushed Sunday 09:00.
                # FOREIGN KEY references anomaly_log.id for traceability.
                try:
                    cursor = await db.execute(
                        "PRAGMA table_info(regime_weekly_digest_queue)"
                    )
                    rwdq_cols = {row[1] for row in await cursor.fetchall()}
                    if not rwdq_cols:
                        await db.execute(
                            """CREATE TABLE IF NOT EXISTS regime_weekly_digest_queue (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                anomaly_log_id INTEGER NOT NULL,
                                queued_at TEXT NOT NULL,
                                person_id TEXT NOT NULL,
                                severity INTEGER NOT NULL,
                                FOREIGN KEY (anomaly_log_id) REFERENCES anomaly_log(id)
                            )"""
                        )
                        await db.commit()
                        _LOGGER.info("Created regime_weekly_digest_queue table")
                except Exception as e:
                    _LOGGER.warning(
                        "regime_weekly_digest_queue table creation failed: %s", e
                    )

                if failed_tables:
                    _LOGGER.warning(
                        "Database initialized with %d table failures: %s",
                        len(failed_tables), ", ".join(failed_tables),
                    )
                else:
                    _LOGGER.info("Database initialized successfully")
                return True
        except Exception as e:
            _LOGGER.error("Error initializing database (connection-level): %s", e)
            return False

    async def log_occupancy_event(
        self,
        room_id: str,
        event_type: str,
        trigger_source: str | None = None,
        duration: int | None = None,
    ) -> None:
        """Log occupancy event."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO occupancy_events (room_id, timestamp, event_type, trigger_source, duration)
                    VALUES (?, ?, ?, ?, ?)
                """, (room_id, datetime.utcnow().isoformat(), event_type, trigger_source, duration))
                await db.commit()
                _LOGGER.debug("Logged occupancy event for room %s: %s (trigger=%s)", room_id, event_type, trigger_source)
        except Exception as e:
            _LOGGER.error("Error logging occupancy event: %s", e)

    async def log_environmental_data(self, room_id: str, data: dict[str, Any]) -> None:
        """Log environmental snapshot."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO environmental_data (room_id, timestamp, temperature, humidity, illuminance, occupied)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    room_id,
                    datetime.utcnow().isoformat(),
                    data.get('temperature'),
                    data.get('humidity'),
                    data.get('illuminance'),
                    data.get('occupied'),
                ))
                await db.commit()
                _LOGGER.debug("Logged environmental data for room %s: temp=%.1f, humidity=%.1f", 
                             room_id, data.get('temperature', 0), data.get('humidity', 0))
        except Exception as e:
            _LOGGER.error("Error logging environmental data: %s", e)

    async def log_energy_snapshot(self, room_id: str, data: dict[str, Any]) -> None:
        """Log energy snapshot."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO energy_snapshots (
                        room_id, timestamp, power_watts, occupied,
                        lights_on, fans_on, switches_on, covers_open
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    room_id,
                    datetime.utcnow().isoformat(),
                    data.get('power_watts'),
                    data.get('occupied'),
                    data.get('lights_on'),
                    data.get('fans_on'),
                    data.get('switches_on'),
                    data.get('covers_open'),
                ))
                await db.commit()
                _LOGGER.debug("Logged energy snapshot for room %s: power=%.1fW", room_id, data.get('power_watts', 0))
        except Exception as e:
            _LOGGER.error("Error logging energy snapshot: %s", e)

    async def log_external_conditions(self, data: dict[str, Any]) -> None:
        """Log external conditions snapshot (weather, solar, occupancy counts)."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO external_conditions (
                        timestamp, outside_temp, outside_humidity, weather_condition,
                        solar_production, forecast_high, forecast_low,
                        occupied_room_count, occupied_zone_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    data.get('outside_temp'),
                    data.get('outside_humidity'),
                    data.get('weather_condition'),
                    data.get('solar_production'),
                    data.get('forecast_high'),
                    data.get('forecast_low'),
                    data.get('occupied_room_count'),
                    data.get('occupied_zone_count'),
                ))
                await db.commit()
                _LOGGER.debug(
                    "Logged external conditions: temp=%.1f, rooms=%d, zones=%d",
                    data.get('outside_temp', 0),
                    data.get('occupied_room_count', 0),
                    data.get('occupied_zone_count', 0)
                )
        except Exception as e:
            _LOGGER.error("Error logging external conditions: %s", e)

    async def log_zone_event(
        self,
        zone: str,
        event_type: str,
        room_count: int = 0,
        rooms: list[str] | None = None,
    ) -> None:
        """Log zone occupancy event."""
        try:
            rooms_str = ",".join(rooms) if rooms else None
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO zone_events (zone, timestamp, event_type, room_count, rooms)
                    VALUES (?, ?, ?, ?, ?)
                """, (zone, datetime.utcnow().isoformat(), event_type, room_count, rooms_str))
                await db.commit()
                _LOGGER.debug("Logged zone event: %s -> %s (%d rooms)", zone, event_type, room_count)
        except Exception as e:
            _LOGGER.error("Error logging zone event: %s", e)

    # =========================================================================
    # v3.6.0: DOMAIN COORDINATOR DECISION LOGGING
    # =========================================================================

    async def log_coordinator_decision(
        self,
        coordinator_id: str,
        decision_type: str,
        context_json: str,
        action_json: str,
        situation_classified: str | None = None,
        urgency: int | None = None,
        confidence: float | None = None,
        expected_savings_kwh: float | None = None,
        expected_cost_savings: float | None = None,
        expected_comfort_impact: int | None = None,
        constraints_published: str | None = None,
        devices_commanded: str | None = None,
    ) -> int | None:
        """Log a coordinator decision. Returns the decision_log row id."""
        try:
            async with self._db() as db:
                cursor = await db.execute("""
                    INSERT INTO decision_log (
                        timestamp, coordinator_id, decision_type,
                        situation_classified, urgency, confidence,
                        context_json, action_json,
                        expected_savings_kwh, expected_cost_savings,
                        expected_comfort_impact, constraints_published,
                        devices_commanded
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    coordinator_id, decision_type,
                    situation_classified, urgency, confidence,
                    context_json, action_json,
                    expected_savings_kwh, expected_cost_savings,
                    expected_comfort_impact, constraints_published,
                    devices_commanded,
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error logging coordinator decision: %s", e)
            return None

    async def log_compliance_check(
        self,
        decision_id: int | None,
        device_type: str,
        device_id: str,
        commanded_state: str,
        actual_state: str,
        compliant: bool,
        deviation_details: str | None = None,
        override_detected: bool = False,
        override_source: str | None = None,
        override_duration_minutes: int | None = None,
        scope: str = "house",
    ) -> None:
        """Log a compliance check result."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO compliance_log (
                        timestamp, decision_id, scope, device_type, device_id,
                        commanded_state, actual_state, compliant,
                        deviation_details, override_detected,
                        override_source, override_duration_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    decision_id, scope, device_type, device_id,
                    commanded_state, actual_state, compliant,
                    deviation_details, override_detected,
                    override_source, override_duration_minutes,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error logging compliance check: %s", e)

    async def log_house_state_change(
        self,
        state: str,
        confidence: float,
        trigger: str | None = None,
        previous_state: str | None = None,
    ) -> None:
        """Log a house state transition."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO house_state_log (
                        timestamp, state, confidence, trigger, previous_state
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    state, confidence, trigger, previous_state,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error logging house state change: %s", e)

    async def fetch_house_state_log_since(
        self,
        since_iso: str,
        limit: int,
    ) -> list[dict]:
        """Return house_state_log rows with timestamp >= since_iso, oldest first.

        Read-only sibling of count_house_state_changes_since. Used by
        RoutineForecaster (cycle: routine-next-state-forecaster) to aggregate
        a bounded window (default 60d / 5000 rows) into in-memory
        (prev_state, day_type, time_bin) -> next_state counts + dwell ETAs.

        Bounded by ``LIMIT ?`` to cap read pressure (no runaway scans even
        if the table grows). Internal SQL uses ``ORDER BY timestamp DESC
        LIMIT ?`` so an overflowed window keeps the NEWEST rows (review
        finding A-2 / B-2 — the prior ASC ordering froze the model on
        stale data after any flap storm). Rows are reversed in Python
        before returning so callers still see ascending chronological
        order, which is required for the dwell-time computation across
        consecutive rows.

        Returns ``[]`` on exception (matches count_house_state_changes_since
        failure mode) so callers can treat the forecaster as degraded
        rather than crashing the coordinator.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """
                    SELECT timestamp, state, previous_state, confidence
                    FROM house_state_log
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (since_iso, int(limit)),
                )
                rows = await cursor.fetchall()
                # Caller expects ascending chronological order — reverse
                # the DESC result. ``reversed()`` is O(n) and keeps the
                # newest-kept semantics from the LIMIT.
                return [
                    {
                        "timestamp": r[0],
                        "state": r[1],
                        "previous_state": r[2],
                        "confidence": r[3],
                    }
                    for r in reversed(rows or [])
                ]
        except Exception as e:
            _LOGGER.error(
                "Error fetching house_state_log since %s: %s", since_iso, e
            )
            return []

    async def count_house_state_changes_since(self, since_iso: str) -> int:
        """Return the number of house_state_log rows with timestamp >= since_iso.

        v4.6.5.1 P4 (M3 fix from v4.6.4 review): supports
        PresenceCoordinator._transitions_today hydration on setup. Without
        this, the daily transition counter resets to 0 on every reload/
        restart and the `transition_count_daily` baseline distribution skews
        low — biasing future thrashy-day anomalies to fire more often than
        they should.

        Caller passes the start-of-today ISO string (e.g. "2026-05-16"); the
        comparison works lexicographically against the UTC ISO timestamps in
        the table (any "YYYY-MM-DDTHH:MM:SS..." string from today is >= the
        bare date string). TZ note: there is an existing UTC-vs-local
        approximation here matching the production `_count_transition` reset
        check — not new to this fix.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?",
                    (since_iso,),
                )
                row = await cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            _LOGGER.error("Error counting house_state_log since %s: %s", since_iso, e)
            return 0

    # =========================================================================
    # v3.1.6: ENERGY HISTORY LOGGING AND QUERIES
    # =========================================================================

    async def log_energy_history(self, data: dict[str, Any]) -> None:
        """Log energy history snapshot for predictions (every 15 minutes)."""
        try:
            now = datetime.utcnow()
            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO energy_history (
                        timestamp, solar_production, solar_export, grid_import, grid_import_2,
                        battery_level, whole_house_energy, rooms_energy_total,
                        outside_temp, outside_humidity, house_avg_temp, house_avg_humidity,
                        temp_delta_outside, humidity_delta_outside, rooms_occupied,
                        day_of_week, hour_of_day, is_weekend, tou_period
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now.isoformat(),
                    data.get('solar_production'),
                    data.get('solar_export'),
                    data.get('grid_import'),
                    data.get('grid_import_2'),
                    data.get('battery_level'),
                    data.get('whole_house_energy'),
                    data.get('rooms_energy_total'),
                    data.get('outside_temp'),
                    data.get('outside_humidity'),
                    data.get('house_avg_temp'),
                    data.get('house_avg_humidity'),
                    data.get('temp_delta_outside'),
                    data.get('humidity_delta_outside'),
                    data.get('rooms_occupied'),
                    now.weekday(),  # 0=Monday, 6=Sunday
                    now.hour,
                    now.weekday() >= 5,  # Saturday=5, Sunday=6
                    data.get('tou_period'),
                ))
                await db.commit()
                _LOGGER.debug(
                    "Logged energy history: grid=%.2f kW, solar_export=%.2f kW",
                    data.get('grid_import', 0) or 0,
                    data.get('solar_export', 0) or 0
                )
        except Exception as e:
            _LOGGER.error("Error logging energy history: %s", e)

    async def get_days_of_energy_data(self) -> int:
        """Get number of days of energy history data available."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT MIN(timestamp), MAX(timestamp)
                    FROM energy_history
                """)
                row = await cursor.fetchone()
                if row and row[0] and row[1]:
                    min_date = datetime.fromisoformat(row[0])
                    max_date = datetime.fromisoformat(row[1])
                    return (max_date - min_date).days
                return 0
        except Exception as e:
            _LOGGER.error("Error getting days of energy data: %s", e)
            return 0

    async def get_energy_for_similar_days(
        self,
        day_of_week: int,
        temp_low: float,
        temp_high: float,
        limit: int = 10
    ) -> list[dict]:
        """Get energy data for similar days (same weekday, similar temperature)."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT
                        DATE(timestamp) as date,
                        SUM(CASE WHEN grid_import IS NOT NULL THEN grid_import ELSE 0 END) as total_grid_import,
                        SUM(CASE WHEN solar_export IS NOT NULL THEN solar_export ELSE 0 END) as total_solar_export,
                        AVG(outside_temp) as avg_temp,
                        AVG(rooms_occupied) as avg_occupancy
                    FROM energy_history
                    WHERE day_of_week = ?
                    AND outside_temp BETWEEN ? AND ?
                    GROUP BY DATE(timestamp)
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (day_of_week, temp_low, temp_high, limit))
                
                rows = await cursor.fetchall()
                return [
                    {
                        'date': row[0],
                        'grid_import': row[1] or 0,
                        'solar_export': row[2] or 0,
                        'net_energy': (row[1] or 0) - (row[2] or 0),
                        'avg_temp': row[3],
                        'avg_occupancy': row[4],
                    }
                    for row in rows
                ]
        except Exception as e:
            _LOGGER.error("Error getting similar days energy data: %s", e)
            return []

    async def get_energy_for_date_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> dict[str, float]:
        """Get total energy values for a date range."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT
                        SUM(CASE WHEN grid_import IS NOT NULL THEN grid_import ELSE 0 END) as total_grid_import,
                        SUM(CASE WHEN solar_export IS NOT NULL THEN solar_export ELSE 0 END) as total_solar_export,
                        SUM(CASE WHEN solar_production IS NOT NULL THEN solar_production ELSE 0 END) as total_solar_production,
                        AVG(outside_temp) as avg_temp,
                        AVG(rooms_occupied) as avg_occupancy,
                        COUNT(*) as record_count
                    FROM energy_history
                    WHERE timestamp BETWEEN ? AND ?
                """, (start_date.isoformat(), end_date.isoformat()))
                
                row = await cursor.fetchone()
                if row:
                    return {
                        'grid_import': row[0] or 0,
                        'solar_export': row[1] or 0,
                        'solar_production': row[2] or 0,
                        'net_energy': (row[0] or 0) - (row[1] or 0),
                        'avg_temp': row[3],
                        'avg_occupancy': row[4],
                        'record_count': row[5],
                    }
                return {'grid_import': 0, 'solar_export': 0, 'net_energy': 0}
        except Exception as e:
            _LOGGER.error("Error getting energy for date range: %s", e)
            return {'grid_import': 0, 'solar_export': 0, 'net_energy': 0}

    async def get_recent_weeks_energy(self, num_weeks: int = 4) -> list[dict]:
        """Get weekly energy totals for recent weeks."""
        try:
            results = []
            now = datetime.utcnow()
            
            for week_offset in range(num_weeks):
                # Calculate week start/end
                week_start = now - timedelta(days=now.weekday() + (week_offset * 7))
                week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
                week_end = week_start + timedelta(days=7)
                
                data = await self.get_energy_for_date_range(week_start, week_end)
                data['week_start'] = week_start.isoformat()
                data['week_end'] = week_end.isoformat()
                results.append(data)
            
            return results
        except Exception as e:
            _LOGGER.error("Error getting recent weeks energy: %s", e)
            return []

    async def get_recent_months_energy(self, num_months: int = 3) -> list[dict]:
        """Get monthly energy totals for recent months."""
        try:
            results = []
            now = datetime.utcnow()
            
            for month_offset in range(num_months):
                # Calculate month start/end
                year = now.year
                month = now.month - month_offset
                while month <= 0:
                    month += 12
                    year -= 1
                
                month_start = datetime(year, month, 1)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1)
                else:
                    month_end = datetime(year, month + 1, 1)
                
                data = await self.get_energy_for_date_range(month_start, month_end)
                data['month_start'] = month_start.isoformat()
                data['month_end'] = month_end.isoformat()
                results.append(data)
            
            return results
        except Exception as e:
            _LOGGER.error("Error getting recent months energy: %s", e)
            return []

    async def predict_energy(
        self,
        period: str,
        forecast_temp: float | None = None
    ) -> tuple[float | None, int]:
        """
        Predict energy needs for period.
        
        Args:
            period: "day", "week", or "month"
            forecast_temp: Expected average temperature for period
            
        Returns:
            Tuple of (predicted_kwh, confidence_percent) or (None, 0) if insufficient data
        """
        try:
            # Check data sufficiency
            days_of_data = await self.get_days_of_energy_data()
            if days_of_data < MIN_DATA_DAYS_PREDICTION:
                return (None, 0)
            
            now = datetime.utcnow()
            
            if period in ("day", "tomorrow"):
                # Get similar days (same weekday, similar temp).
                # "tomorrow" (2026-07-27, additive, display-only): mirrors the
                # "day" path but keys on tomorrow's weekday + tomorrow's
                # forecast temp. Feeds sensor.universal_room_automation_predicted_energy_tomorrow
                # for the dashboard "Net Tomorrow" tile. No decision consumer.
                temp_range = 10  # +/- 10 degrees
                if forecast_temp is None:
                    forecast_temp = 70  # Default assumption

                target_day = (now + timedelta(days=1)).weekday() if period == "tomorrow" else now.weekday()

                historical = await self.get_energy_for_similar_days(
                    day_of_week=target_day,
                    temp_low=forecast_temp - temp_range,
                    temp_high=forecast_temp + temp_range,
                    limit=10
                )
                
                if len(historical) < 3:
                    # Not enough similar days, get any recent data
                    yesterday = now - timedelta(days=1)
                    week_ago = now - timedelta(days=7)
                    data = await self.get_energy_for_date_range(week_ago, yesterday)
                    if data.get('record_count', 0) > 0:
                        # Estimate daily from weekly average
                        daily_avg = data['net_energy'] / 7
                        return (round(daily_avg, 1), 40)  # Low confidence
                    return (None, 0)
                
                values = [h['net_energy'] for h in historical]
                
            elif period == "week":
                historical = await self.get_recent_weeks_energy(4)
                if len(historical) < 2:
                    return (None, 0)
                values = [h['net_energy'] for h in historical if h.get('record_count', 0) > 0]
                
            elif period == "month":
                historical = await self.get_recent_months_energy(3)
                if len(historical) < 2:
                    return (None, 0)
                values = [h['net_energy'] for h in historical if h.get('record_count', 0) > 0]
            
            else:
                return (None, 0)
            
            if not values or len(values) < 2:
                return (None, 0)
            
            # Calculate prediction
            predicted = statistics.mean(values)
            
            # Calculate confidence based on consistency (coefficient of variation)
            std_dev = statistics.stdev(values)
            cv = std_dev / abs(predicted) if predicted != 0 else 1
            confidence = max(0, min(100, int((1 - cv) * 100)))
            
            # Adjust confidence based on data quantity
            data_factor = min(1.0, days_of_data / 30)  # Full confidence at 30 days
            confidence = int(confidence * data_factor)
            
            return (round(predicted, 1), confidence)
            
        except Exception as e:
            _LOGGER.error("Error predicting energy: %s", e)
            return (None, 0)

    # =========================================================================
    # EXISTING QUERIES (unchanged)
    # =========================================================================

    async def get_external_conditions_history(self, hours: int = 24) -> list[dict]:
        """Get external conditions history for predictions."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT timestamp, outside_temp, outside_humidity, weather_condition,
                           solar_production, forecast_high, forecast_low,
                           occupied_room_count, occupied_zone_count
                    FROM external_conditions
                    WHERE timestamp > ?
                    ORDER BY timestamp ASC
                """, (cutoff,))
                rows = await cursor.fetchall()
                return [
                    {
                        'timestamp': row[0],
                        'outside_temp': row[1],
                        'outside_humidity': row[2],
                        'weather_condition': row[3],
                        'solar_production': row[4],
                        'forecast_high': row[5],
                        'forecast_low': row[6],
                        'occupied_room_count': row[7],
                        'occupied_zone_count': row[8],
                    }
                    for row in rows
                ]
        except Exception as e:
            _LOGGER.error("Error getting external conditions history: %s", e)
            return []

    async def get_recent_data(self, room_id: str, limit: int = 100) -> dict[str, list]:
        """Get recent data for export."""
        try:
            async with self._db_read() as db:
                # Get occupancy events
                cursor = await db.execute("""
                    SELECT timestamp, event_type, trigger_source, duration
                    FROM occupancy_events
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                occupancy_rows = await cursor.fetchall()
                
                # Get environmental data
                cursor = await db.execute("""
                    SELECT timestamp, temperature, humidity, illuminance, occupied
                    FROM environmental_data
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                env_rows = await cursor.fetchall()
                
                # Get energy snapshots
                cursor = await db.execute("""
                    SELECT timestamp, power_watts, occupied, lights_on, fans_on, switches_on, covers_open
                    FROM energy_snapshots
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                energy_rows = await cursor.fetchall()
                
                return {
                    "occupancy": occupancy_rows,
                    "environmental": env_rows,
                    "energy": energy_rows
                }
        except Exception as e:
            _LOGGER.error("Error querying data for export: %s", e)
            return {"occupancy": [], "environmental": [], "energy": []}

    async def get_table_counts(self, room_id: str) -> dict[str, int]:
        """Get row counts for each table for a specific room."""
        try:
            async with self._db_read() as db:
                counts = {}
                
                cursor = await db.execute("SELECT COUNT(*) FROM occupancy_events WHERE room_id = ?", (room_id,))
                counts["occupancy_events"] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM environmental_data WHERE room_id = ?", (room_id,))
                counts["environmental_data"] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM energy_snapshots WHERE room_id = ?", (room_id,))
                counts["energy_snapshots"] = (await cursor.fetchone())[0]
                
                # v3.1.6: Add energy history count (global, not per-room)
                cursor = await db.execute("SELECT COUNT(*) FROM energy_history")
                counts["energy_history"] = (await cursor.fetchone())[0]
                
                return counts
        except Exception as e:
            _LOGGER.error("Error getting table counts: %s", e)
            return {"occupancy_events": 0, "environmental_data": 0, "energy_snapshots": 0, "energy_history": 0}

    # =========================================================================
    # PHASE 2: ENERGY QUERIES
    # =========================================================================

    async def get_energy_for_period(
        self, 
        room_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> float:
        """
        Calculate energy consumption for a time period.
        Integrates power readings over time (trapezoid rule).
        Returns kWh.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT timestamp, power_watts
                    FROM energy_snapshots
                    WHERE room_id = ?
                    AND timestamp >= ?
                    AND timestamp <= ?
                    ORDER BY timestamp ASC
                """, (room_id, start_time.isoformat(), end_time.isoformat()))
                
                rows = await cursor.fetchall()
                
                if len(rows) < 2:
                    return 0.0
                
                # Integrate power over time using trapezoid rule
                total_wh = 0.0
                for i in range(len(rows) - 1):
                    ts1 = datetime.fromisoformat(rows[i][0])
                    ts2 = datetime.fromisoformat(rows[i + 1][0])
                    power1 = rows[i][1] or 0
                    power2 = rows[i + 1][1] or 0
                    
                    # Time difference in hours
                    hours = (ts2 - ts1).total_seconds() / 3600
                    
                    # Average power * time = energy
                    avg_power = (power1 + power2) / 2
                    total_wh += avg_power * hours
                
                return total_wh / 1000  # Convert Wh to kWh
                
        except Exception as e:
            _LOGGER.error("Error calculating energy for period: %s", e)
            return 0.0

    # =========================================================================
    # PHASE 3: OCCUPANCY PREDICTION QUERIES
    # =========================================================================

    async def get_occupancy_percentage(self, room_id: str, days: int = 7) -> float | None:
        """
        Calculate percentage of time room was occupied over the last N days.
        Returns percentage (0-100) or None if insufficient data.
        """
        try:
            cutoff = dt_util.now() - timedelta(days=days)

            async with self._db_read() as db:
                # Get all entry/exit events in period
                cursor = await db.execute("""
                    SELECT timestamp, event_type, duration
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (room_id, cutoff.isoformat()))
                
                events = await cursor.fetchall()
                
                if not events:
                    return None
                
                # Calculate total occupied time
                total_occupied_seconds = 0
                current_entry_time = None
                
                for event in events:
                    timestamp = datetime.fromisoformat(event[0])
                    event_type = event[1]
                    duration = event[2]
                    
                    if event_type == "entry":
                        current_entry_time = timestamp
                    elif event_type == "exit" and duration:
                        total_occupied_seconds += duration
                
                # Calculate percentage
                total_period_seconds = days * 24 * 3600
                percentage = (total_occupied_seconds / total_period_seconds) * 100
                
                return min(100.0, max(0.0, percentage))
                
        except Exception as e:
            _LOGGER.error("Error calculating occupancy percentage: %s", e)
            return None

    async def get_peak_occupancy_hour(self, room_id: str, days: int = 7) -> int | None:
        """
        Find the hour of day (0-23) when room is most frequently occupied.
        Returns hour or None if insufficient data.
        """
        try:
            cutoff = dt_util.now() - timedelta(days=days)

            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT timestamp
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND event_type = 'entry'
                    AND timestamp >= ?
                """, (room_id, cutoff.isoformat()))
                
                events = await cursor.fetchall()
                
                if not events:
                    return None
                
                # Count entries by hour
                hour_counts = [0] * 24
                for event in events:
                    timestamp = datetime.fromisoformat(event[0])
                    hour_counts[timestamp.hour] += 1
                
                # Find peak hour
                peak_hour = hour_counts.index(max(hour_counts))
                
                return peak_hour if max(hour_counts) > 0 else None
                
        except Exception as e:
            _LOGGER.error("Error finding peak occupancy hour: %s", e)
            return None

    async def get_next_occupancy_prediction(self, room_id: str) -> tuple[datetime, float] | None:
        """
        Predict next occupancy time based on recent patterns.
        Returns (predicted_time, confidence) or None if insufficient data.
        Confidence is 0-100.
        """
        try:
            # Get entry events for last 7 days
            cutoff = dt_util.now() - timedelta(days=7)

            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT timestamp
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND event_type = 'entry'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (room_id, cutoff.isoformat()))
                
                events = await cursor.fetchall()
                
                if len(events) < 3:
                    return None
                
                now = dt_util.now()
                current_hour = now.hour
                current_weekday = now.weekday()
                
                # Group entries by hour and weekday
                hour_entries = {}
                for event in events:
                    timestamp = datetime.fromisoformat(event[0])
                    # Only consider future hours today or any hour on future days
                    if timestamp.weekday() == current_weekday and timestamp.hour > current_hour:
                        key = (timestamp.weekday(), timestamp.hour)
                        if key not in hour_entries:
                            hour_entries[key] = 0
                        hour_entries[key] += 1
                
                if not hour_entries:
                    # No entries later today, check tomorrow
                    tomorrow_weekday = (current_weekday + 1) % 7
                    for event in events:
                        timestamp = datetime.fromisoformat(event[0])
                        if timestamp.weekday() == tomorrow_weekday:
                            key = (timestamp.weekday(), timestamp.hour)
                            if key not in hour_entries:
                                hour_entries[key] = 0
                            hour_entries[key] += 1
                
                if not hour_entries:
                    return None
                
                # Find most common next entry time
                most_common = max(hour_entries.items(), key=lambda x: x[1])
                (pred_weekday, pred_hour), count = most_common
                
                # Calculate next occurrence of this weekday/hour
                days_ahead = (pred_weekday - current_weekday) % 7
                if days_ahead == 0 and pred_hour <= current_hour:
                    days_ahead = 7
                
                next_time = now.replace(hour=pred_hour, minute=0, second=0, microsecond=0)
                next_time += timedelta(days=days_ahead)
                
                # Confidence based on consistency (how many times vs total)
                confidence = min(100, (count / len(events)) * 100 * 7)  # Scale up for weekly pattern
                
                return (next_time, confidence)
                
        except Exception as e:
            _LOGGER.error("Error predicting next occupancy: %s", e)
            return None

    async def get_avg_time_to_comfort(self, room_id: str, days: int = 14) -> int | None:
        """
        Calculate average time (minutes) from occupancy to reaching comfort zone.
        This is for precool/preheat lead time calculation.
        Returns minutes or None if insufficient data.
        """
        try:
            cutoff = dt_util.now() - timedelta(days=days)

            async with self._db_read() as db:
                # Get occupancy events
                cursor = await db.execute("""
                    SELECT timestamp
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND event_type = 'entry'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (room_id, cutoff.isoformat()))
                
                entry_events = await cursor.fetchall()
                
                if not entry_events:
                    return None
                
                # For each entry, find when temperature reached comfort zone
                # Comfort zone defined in const.py: 68-76°F, 30-60% humidity
                times_to_comfort = []
                
                for entry in entry_events:
                    entry_time = datetime.fromisoformat(entry[0])
                    
                    # Get environmental data after entry
                    cursor = await db.execute("""
                        SELECT timestamp, temperature, humidity
                        FROM environmental_data
                        WHERE room_id = ?
                        AND timestamp >= ?
                        AND timestamp <= ?
                        AND temperature IS NOT NULL
                        ORDER BY timestamp ASC
                    """, (
                        room_id,
                        entry_time.isoformat(),
                        (entry_time + timedelta(hours=2)).isoformat()
                    ))
                    
                    env_data = await cursor.fetchall()
                    
                    # Find first reading in comfort zone
                    for reading in env_data:
                        timestamp = datetime.fromisoformat(reading[0])
                        temp = reading[1]
                        humidity = reading[2] or 50  # Default if None
                        
                        # Check if in comfort zone (68-76°F, 30-60%)
                        if 68 <= temp <= 76 and 30 <= humidity <= 60:
                            minutes = (timestamp - entry_time).total_seconds() / 60
                            times_to_comfort.append(minutes)
                            break
                
                if not times_to_comfort:
                    return None
                
                # Return average
                return int(sum(times_to_comfort) / len(times_to_comfort))
                
        except Exception as e:
            _LOGGER.error("Error calculating time to comfort: %s", e)
            return None

    # =========================================================================
    # v3.2.0: PERSON TRACKING METHODS
    # =========================================================================

    async def log_person_entry(
        self,
        person_id: str,
        room_id: str,
        confidence: float,
        detection_method: str,
        transition_from: str | None = None
    ) -> int:
        """Log person entering a room."""
        try:
            async with self._db() as db:
                cursor = await db.execute("""
                    INSERT INTO person_visits 
                    (person_id, room_id, entry_time, confidence, detection_method, transition_from)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    person_id,
                    room_id,
                    datetime.now(),
                    confidence,
                    detection_method,
                    transition_from
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Failed to log person entry: %s", e)
            return -1

    async def log_person_exit(
        self,
        visit_id: int,
        exit_time: datetime | None = None
    ) -> None:
        """Log person exiting a room."""
        try:
            if exit_time is None:
                exit_time = datetime.now()

            async with self._db() as db:
                # Update exit time and calculate duration
                await db.execute("""
                    UPDATE person_visits 
                    SET exit_time = ?,
                        duration_seconds = (
                            CAST((julianday(?) - julianday(entry_time)) * 86400 AS INTEGER)
                        )
                    WHERE id = ?
                """, (exit_time, exit_time, visit_id))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Failed to log person exit: %s", e)

    async def log_person_snapshot(
        self,
        person_id: str,
        room_id: str | None,
        confidence: float,
        method: str
    ) -> None:
        """Log periodic person presence snapshot."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO person_presence_snapshots 
                    (timestamp, person_id, room_id, confidence, method)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    datetime.now(),
                    person_id,
                    room_id,
                    confidence,
                    method
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Failed to log person snapshot: %s", e)

    async def get_person_last_location(self, person_id: str) -> dict[str, Any] | None:
        """Get person's last known location."""
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT room_id, entry_time, confidence, detection_method
                    FROM person_visits
                    WHERE person_id = ?
                    AND exit_time IS NULL
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, (person_id,))

                row = await cursor.fetchone()

                if row:
                    return {
                        'room_id': row['room_id'],
                        'entry_time': row['entry_time'],
                        'confidence': row['confidence'],
                        'method': row['detection_method']
                    }

                return None

        except Exception as e:
            _LOGGER.error("Failed to get person last location: %s", e)
            return None

    async def get_active_visit_id(self, person_id: str, room_id: str) -> int | None:
        """Get ID of person's active visit in room."""
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT id
                    FROM person_visits
                    WHERE person_id = ? 
                    AND room_id = ?
                    AND exit_time IS NULL
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, (person_id, room_id))

                row = await cursor.fetchone()

                if row:
                    return row['id']

                return None

        except Exception as e:
            _LOGGER.error("Failed to get active visit ID: %s", e)
            return None

    async def get_room_occupants(self, room_id: str) -> list[dict[str, Any]]:
        """Get list of people currently in room."""
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT person_id, entry_time, confidence, detection_method
                    FROM person_visits
                    WHERE room_id = ?
                    AND exit_time IS NULL
                    ORDER BY entry_time DESC
                """, (room_id,))

                rows = await cursor.fetchall()

                return [
                    {
                        'person_id': row['person_id'],
                        'entry_time': row['entry_time'],
                        'confidence': row['confidence'],
                        'method': row['detection_method']
                    }
                    for row in rows
                ]

        except Exception as e:
            _LOGGER.error("Failed to get room occupants: %s", e)
            return []

    async def log_unknown_device(
        self,
        device_id: str,
        room_id: str,
        confidence: float
    ) -> None:
        """Log unknown device detection (passive tracking)."""
        try:
            now = datetime.now()

            async with self._db() as db:
                # Insert or update
                await db.execute("""
                    INSERT INTO unknown_devices (device_id, first_seen, last_seen, room_id, confidence)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        last_seen = ?,
                        room_id = ?,
                        confidence = ?
                """, (device_id, now, now, room_id, confidence, now, room_id, confidence))

                await db.commit()
        except Exception as e:
            _LOGGER.error("Failed to log unknown device: %s", e)

    async def cleanup_person_data(self, retention_days: int, batch_size: int = 1000) -> int:
        """Remove person tracking data older than retention period. v4.2.8: Batched."""
        if retention_days == 0:
            return 0  # 0 = infinite retention

        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        for table, col in [
            ("person_visits", "entry_time"),
            ("person_presence_snapshots", "timestamp"),
            ("unknown_devices", "last_seen"),
        ]:
            _batch_count = 0
            while True:
                _batch_count += 1
                if _batch_count > 500:
                    _LOGGER.warning("Person data cleanup (%s) hit max batch limit", table)
                    break
                try:
                    async with self._db() as db:
                        cursor = await db.execute(
                            f"DELETE FROM {table} WHERE rowid IN ("
                            f"SELECT rowid FROM {table} WHERE {col} < ? LIMIT ?)",
                            (cutoff, batch_size))
                        await db.commit()
                        deleted = cursor.rowcount
                        total_deleted += deleted
                except Exception as e:
                    _LOGGER.error("Failed to cleanup %s: %s", table, e)
                    break
                if deleted < batch_size:
                    break
                await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info("Person data cleanup: deleted %d rows older than %d days", total_deleted, retention_days)
        return total_deleted

    async def get_zone_last_occupant(
        self,
        zone_rooms: list[str]
    ) -> dict[str, Any] | None:
        """Get last occupant across multiple rooms in a zone.
        
        Args:
            zone_rooms: List of room IDs/names in the zone
            
        Returns:
            Dict with person_id, entry_time, room_id or None if no visits found
        """
        if not zone_rooms:
            return None

        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                
                # Build query with parameterized placeholders
                placeholders = ','.join('?' * len(zone_rooms))
                cursor = await db.execute(f"""
                    SELECT person_id, entry_time, room_id
                    FROM person_visits
                    WHERE room_id IN ({placeholders})
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, zone_rooms)
                
                row = await cursor.fetchone()
                
                if row:
                    return {
                        'person_id': row['person_id'],
                        'entry_time': row['entry_time'],
                        'room_id': row['room_id']
                    }
                
                return None
                
        except Exception as e:
            _LOGGER.error("Failed to get zone last occupant: %s", e)
            return None

    # v3.3.0: Room transition methods for pattern learning

    async def log_transition(
        self,
        person_id: str,
        from_room: str,
        to_room: str,
        timestamp: datetime,
        duration_seconds: int,
        path_type: str,
        confidence: float,
        via_room: Optional[str] = None
    ) -> None:
        """Log a room-to-room transition."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO room_transitions 
                    (person_id, from_room, to_room, timestamp, 
                     duration_seconds, path_type, confidence, via_room)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    person_id,
                    from_room,
                    to_room,
                    timestamp,
                    duration_seconds,
                    path_type,
                    confidence,
                    via_room
                ))
                await db.commit()
                
            _LOGGER.debug(
                "Transition logged to DB: %s %s → %s (%s, %ds)",
                person_id, from_room, to_room, path_type, duration_seconds
            )
        except Exception as e:
            _LOGGER.error("Failed to log transition: %s", e)

    async def get_transitions(
        self,
        person_id: str,
        days: int = 30,
        hours: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Get transitions for a person.
        
        Args:
            person_id: Person to query
            days: Days to look back (if hours not specified)
            hours: Hours to look back (overrides days if specified)
            
        Returns:
            List of transition dicts with keys:
                from_room, to_room, timestamp, duration_seconds,
                path_type, confidence, via_room
        """
        try:
            # Calculate cutoff
            if hours is not None:
                cutoff = datetime.now() - timedelta(hours=hours)
            else:
                cutoff = datetime.now() - timedelta(days=days)

            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT 
                        from_room,
                        to_room,
                        timestamp,
                        duration_seconds,
                        path_type,
                        confidence,
                        via_room
                    FROM room_transitions
                    WHERE person_id = ?
                      AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (person_id, cutoff))
                
                rows = await cursor.fetchall()
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            _LOGGER.error("Failed to get transitions: %s", e)
            return []

    async def get_common_paths(
        self,
        person_id: str,
        days: int = 30,
        min_occurrences: int = 3
    ) -> list[dict[str, Any]]:
        """Get most common transition paths for a person.
        
        Returns:
            List of dicts with keys: from_room, to_room, count
        """
        try:
            cutoff = datetime.now() - timedelta(days=days)

            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT 
                        from_room,
                        to_room,
                        COUNT(*) as count
                    FROM room_transitions
                    WHERE person_id = ?
                      AND timestamp >= ?
                    GROUP BY from_room, to_room
                    HAVING count >= ?
                    ORDER BY count DESC
                """, (person_id, cutoff, min_occurrences))
                
                rows = await cursor.fetchall()
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            _LOGGER.error("Failed to get common paths: %s", e)
            return []

    # =========================================================================
    # v3.5.0: CENSUS SNAPSHOT METHODS
    # =========================================================================

    async def log_census(self, zone: str, result: Any) -> None:
        """Log a census snapshot for a single zone.

        Args:
            zone: "house" or "property"
            result: CensusZoneResult dataclass instance
        """
        try:
            import json
            identified_persons_json = (
                json.dumps(result.identified_persons)
                if result.identified_persons
                else None
            )
            timestamp = result.timestamp.isoformat() if result.timestamp else dt_util.utcnow().isoformat()

            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO census_snapshots (
                        timestamp, zone, identified_count, identified_persons,
                        unidentified_count, total_persons, confidence,
                        source_agreement, frigate_count, unifi_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp,
                    zone,
                    result.identified_count,
                    identified_persons_json,
                    result.unidentified_count,
                    result.total_persons,
                    result.confidence,
                    result.source_agreement,
                    result.frigate_count,
                    result.unifi_count,
                ))
                await db.commit()
                _LOGGER.debug(
                    "Census snapshot logged: zone=%s, total=%d, identified=%d, confidence=%s",
                    zone,
                    result.total_persons,
                    result.identified_count,
                    result.confidence,
                )
        except Exception as e:
            _LOGGER.error("Failed to log census snapshot: %s", e)

    async def get_census_history(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get census history for the last N hours.

        Returns:
            List of dicts with census snapshot data ordered by timestamp ascending.
        """
        try:
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT
                        timestamp, zone, identified_count, identified_persons,
                        unidentified_count, total_persons, confidence,
                        source_agreement, frigate_count, unifi_count
                    FROM census_snapshots
                    WHERE timestamp > ?
                    ORDER BY timestamp ASC
                """, (cutoff,))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Failed to get census history: %s", e)
            return []

    async def cleanup_census(self, retention_days: int = 90, batch_size: int = 1000) -> int:
        """Delete census snapshots older than retention_days. v4.2.8: Batched."""
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("Census cleanup hit max batch limit")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM census_snapshots WHERE rowid IN ("
                        "SELECT rowid FROM census_snapshots WHERE timestamp < ? LIMIT ?)",
                        (cutoff, batch_size))
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error("Failed to cleanup census snapshots: %s", e)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info("Census cleanup: deleted %d snapshots older than %d days", total_deleted, retention_days)
        return total_deleted

    # =========================================================================
    # v3.5.2: TRANSIT VALIDATION METHODS
    # =========================================================================

    async def update_transition_validation(
        self,
        person_id: str,
        timestamp,
        new_confidence: float,
        validation_method: str,
        checkpoint_rooms: list,
    ) -> None:
        """Update confidence and validation metadata for a recorded transition."""
        import json
        try:
            ts_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            async with self._db() as db:
                await db.execute("""
                    UPDATE room_transitions
                    SET confidence = ?,
                        validation_method = ?,
                        checkpoint_rooms = ?
                    WHERE person_id = ?
                      AND timestamp = ?
                """, (
                    new_confidence,
                    validation_method,
                    json.dumps(checkpoint_rooms),
                    person_id,
                    ts_str,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error updating transition validation: %s", e)

    async def log_entry_exit_event(
        self,
        person_id: Optional[str],
        event_type: str,
        direction: str,
        egress_camera: str,
        confidence: float,
    ) -> None:
        """Log a confirmed entry or exit event."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT INTO person_entry_exit_events
                        (timestamp, person_id, event_type, direction, egress_camera, confidence)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    person_id,
                    event_type,
                    direction,
                    egress_camera,
                    confidence,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error logging entry/exit event: %s", e)

    async def get_entry_exit_events_since(
        self,
        since,
        direction: str,
    ) -> list[dict]:
        """Return entry or exit events since the given datetime.

        Used by count sensors on startup to restore today's count from DB.
        Returns a list of dicts with keys: person_id, timestamp, egress_camera.
        """
        try:
            since_str = since.isoformat() if hasattr(since, "isoformat") else str(since)
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT person_id, timestamp, egress_camera
                    FROM person_entry_exit_events
                    WHERE timestamp >= ?
                      AND direction = ?
                    ORDER BY timestamp ASC
                """, (since_str, direction))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching entry/exit events: %s", e)
            return []

    # =========================================================================
    # EGRESS-EXIT-IDENTITY-BACKFILL-1 (2026-09-05): exit-identity backfill
    # =========================================================================

    async def find_unnamed_exit_crossings(
        self,
        t_lo_iso: str,
        t_hi_iso: str,
    ) -> list[tuple[int, str, str]]:
        """Return null-`person_id` exit rows in the half-open window
        ``(t_lo_iso, t_hi_iso]`` (ISO strings — the caller MUST supply
        NAIVE-UTC bounds matching the INSERT format at
        `log_entry_exit_event`).

        Nearest first (largest timestamp), ties broken by largest id
        (deterministic). Uses the transient read context — this is a
        pure query, not queued behind writes.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """
                    SELECT id, timestamp, egress_camera
                    FROM person_entry_exit_events
                    WHERE person_id IS NULL
                      AND direction = 'exit'
                      AND timestamp > ?
                      AND timestamp <= ?
                    ORDER BY timestamp DESC, id DESC
                    """,
                    (t_lo_iso, t_hi_iso),
                )
                rows = await cursor.fetchall()
                return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "Error fetching unnamed exit crossings (%s..%s): %s",
                t_lo_iso, t_hi_iso, e,
            )
            return []

    async def backfill_entry_exit_person_id(
        self,
        row_id: int,
        person_id: str,
        confidence: float,
    ) -> bool:
        """Idempotent UPDATE: set ``person_id`` + ``confidence`` on
        the row iff it is currently NULL. Returns True on a real
        write (rowcount == 1), False on the no-op (already named,
        or row missing).

        Uses the write queue via ``self._db()`` (same pattern as
        `update_transition_validation`). The ``AND person_id IS NULL``
        clause is the single-use / concurrent-double-fire guard.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """
                    UPDATE person_entry_exit_events
                    SET person_id = ?, confidence = ?
                    WHERE id = ? AND person_id IS NULL
                    """,
                    (person_id, float(confidence), int(row_id)),
                )
                await db.commit()
                changed = int(getattr(cursor, "rowcount", 0) or 0)
                if changed:
                    _LOGGER.info(
                        "exit-backfill DAO: row_id=%s <- person_id=%s "
                        "confidence=%.3f",
                        row_id, person_id, confidence,
                    )
                return changed == 1
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "Error backfilling entry_exit person_id (row_id=%s, "
                "person_id=%s): %s",
                row_id, person_id, e,
            )
            return False

    # =========================================================================
    # v3.6.29: Notification Manager database methods
    # =========================================================================

    async def log_notification(
        self,
        coordinator_id: str,
        severity: str,
        title: str,
        message: str,
        hazard_type: str | None = None,
        location: str | None = None,
        person_id: str | None = None,
        channel: str | None = None,
        delivered: int = 1,
        dry_run: int = 0,
        recipient_id: str | None = None,
        route_reason: str | None = None,
        dnd_bypass_applied: int | None = None,
        bucket_outcome: str | None = None,
        matrix_branch: str | None = None,
        acknowledged: int = 0,
    ) -> int | None:
        """Log a notification to the database. Returns the row ID.

        NM Cycle B B0: ``dry_run=1`` marks a would-have-sent row written by
        the minimal dry-run gate. Real sends stay ``dry_run=0`` — existing
        readers unaffected (default preserves prior behavior).

        NM Cycle C C2: the 5 audit fields are OPTIONAL — legacy callers
        that pass only the pre-C kwargs still INSERT successfully (all
        additive columns are nullable). Audit-populating callers pass
        the extended kwargs explicitly.

        IMSG-IMAGE-FAIL-1 (2026-08-14): ``acknowledged`` may be set to
        1 by write-time audit callers whose row must never be resurrected
        by ``get_active_critical``/``get_active_cooldown``. Default 0
        preserves prior behavior for all real-send callers.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute("""
                    INSERT INTO notification_log
                    (timestamp, coordinator_id, severity, title, message,
                     hazard_type, location, person_id, channel, delivered, dry_run,
                     recipient_id, route_reason, dnd_bypass_applied,
                     bucket_outcome, matrix_branch, acknowledged)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dt_util.utcnow().isoformat(),
                    coordinator_id, severity, title, message,
                    hazard_type, location, person_id, channel, delivered, dry_run,
                    recipient_id, route_reason, dnd_bypass_applied,
                    bucket_outcome, matrix_branch, int(acknowledged),
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Failed to log notification: %s", e)
            return None

    async def get_recent_routing_decisions(self, limit: int = 50) -> list[dict]:
        """NM Cycle C C2: return the most recent audit rows.

        Rows carry both real fires (dry_run=0) and would-fires
        (dry_run=1) — the ``route_reason`` / ``bucket_outcome`` fields
        distinguish. Returned newest-first.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM notification_log
                    WHERE route_reason IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching recent routing decisions: %s", e)
            return []

    async def get_notifications_today(self) -> list[dict]:
        """Get all delivered notifications from today.

        NM-IMAGE-1 fix-up (2026-08-11, review A-MED-1): excludes the
        `"[audit]"` sentinel. Adjudicated as PRE-EXISTING visibility bug
        — audit rows with `delivered=1` (real send that also emitted an
        audit row) were counting toward the today's-notifications total
        and appearing on dashboards. Same-class hygiene with the D3
        `get_pending_digest` sentinel filter; fixed here so the two
        reader-side surfaces (dashboard count + digest body) stay in
        agreement about what `"[audit]"` means.
        """
        try:
            today_start = dt_util.start_of_local_day().isoformat()
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE timestamp >= ? AND delivered > 0
                      AND message != '[audit]'
                    ORDER BY timestamp DESC
                """, (today_start,))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching today's notifications: %s", e)
            return []

    async def get_last_notification(self) -> dict | None:
        """Get the most recent delivered notification.

        NM-IMAGE-1 fix-up (2026-08-11, review A-MED-1): excludes the
        `"[audit]"` sentinel. The `last_notification` dashboard tile was
        surfacing `"[audit]"` as the most-recent message whenever the
        latest emit was a per-recipient audit row. Same-class hygiene
        with `get_notifications_today` and `get_pending_digest`.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE delivered > 0
                      AND message != '[audit]'
                    ORDER BY timestamp DESC LIMIT 1
                """)
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            _LOGGER.error("Error fetching last notification: %s", e)
            return None

    async def get_pending_digest(self, person_id: str) -> list[dict]:
        """Get pending digest notifications for a person.

        NM-IMAGE-1 (2026-08-11, D3 / rev-2 MED-2): excludes rows whose
        `message` field equals the canonical audit sentinel `"[audit]"`.
        The write site (`_emit_audit_row`) is intentional — the sentinel
        is the audit-row marker — so the leak is reader-side. Without
        this filter, LOW/MEDIUM audit rows (e.g. `dnd_suppressed` audit
        rows for MEDIUM alerts) get pulled into the next digest body and
        the operator sees a bare "Perimeter Alert — [audit]" line.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE person_id = ? AND delivered = 0
                      AND severity IN ('LOW', 'MEDIUM')
                      AND message != '[audit]'
                    ORDER BY timestamp
                """, (person_id,))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching pending digest: %s", e)
            return []

    async def mark_digest_delivered(self, person_id: str) -> None:
        """Mark all pending digest items as delivered for a person.

        NM-IMAGE-1 (2026-08-11, D3 / rev-2 §10.4): also marks the
        `message='[audit]'` sentinel rows `delivered=2` alongside real
        rows so the queue does not grow unboundedly at MEDIUM/LOW
        volume. `delivered=2` is a queue-management marker; both
        surviving `delivered > 0` reader queries now explicitly filter
        the sentinel — see `get_notifications_today` (:3849 region)
        and `get_last_notification` (:3872 region), each carrying
        `AND message != '[audit]'` in its SELECT after the fix-up
        review A-MED-1. Prior to that fix-up, `delivered=1` audit rows
        WERE reaching the today-count and last-notification dashboards
        — the docstring's earlier "readers already only inspect real
        rows" claim was aspirational, not true. D0 baseline captured
        pre-
        deploy to validate the bound holds live.
        """
        try:
            async with self._db() as db:
                await db.execute("""
                    UPDATE notification_log SET delivered = 2
                    WHERE person_id = ? AND delivered = 0
                      AND severity IN ('LOW', 'MEDIUM')
                """, (person_id,))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error marking digest delivered: %s", e)

    async def acknowledge_notification(self) -> None:
        """Acknowledge the most recent unacknowledged CRITICAL notification.

        IMSG-IMAGE-FAIL-1 fix-up HIGH-1 (2026-08-14): excludes the
        ``message='[audit]'`` sentinel from the inner SELECT — same
        idiom as the four sibling readers. Without this filter, the
        operator's ack lands on the audit twin written ~4ms after the
        real row (by the matrix-outcome audit at
        notification_manager.py:1787, which does NOT pass acknowledged=1);
        the REAL row stays acknowledged=0 and quietly resurrects at
        the next restart under its real title.
        """
        try:
            async with self._db() as db:
                await db.execute("""
                    UPDATE notification_log
                    SET acknowledged = 1, ack_time = ?
                    WHERE id = (
                        SELECT id FROM notification_log
                        WHERE acknowledged = 0 AND severity = 'CRITICAL'
                          AND message != '[audit]'
                        ORDER BY timestamp DESC LIMIT 1
                    )
                """, (dt_util.utcnow().isoformat(),))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error acknowledging notification: %s", e)

    async def get_active_critical(self) -> dict | None:
        """Get the most recent unacknowledged CRITICAL notification.

        IMSG-IMAGE-FAIL-1 (2026-08-14): excludes the ``message='[audit]'``
        sentinel — same idiom as ``get_notifications_today`` (:3862),
        ``get_last_notification`` (:3886), and ``get_pending_digest``
        (:3913). Without this filter an unacknowledged audit row (e.g.
        the pre-ack ``[ACK]`` audit or a legacy ``dnd_suppressed``
        audit) can be resurrected as the "active" alert.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE severity = 'CRITICAL' AND acknowledged = 0
                      AND message != '[audit]'
                    ORDER BY timestamp DESC LIMIT 1
                """)
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            _LOGGER.error("Error fetching active critical: %s", e)
            return None

    async def get_active_cooldown(self) -> dict | None:
        """Get the active cooldown notification (acked but cooldown not expired).

        IMSG-IMAGE-FAIL-1 (2026-08-14): excludes the ``message='[audit]'``
        sentinel — same idiom as the three sibling readers. An audit row
        marked acknowledged=1 (see ``log_notification(acknowledged=...)``)
        must never surface as an active cooldown.
        """
        try:
            now = dt_util.utcnow().isoformat()
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE severity = 'CRITICAL' AND acknowledged = 1
                      AND cooldown_expires IS NOT NULL AND cooldown_expires > ?
                      AND message != '[audit]'
                    ORDER BY timestamp DESC LIMIT 1
                """, (now,))
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            _LOGGER.error("Error fetching active cooldown: %s", e)
            return None

    async def set_cooldown(self, notification_id: int, cooldown_expires: str) -> None:
        """Set the cooldown expiry for a notification."""
        try:
            async with self._db() as db:
                await db.execute("""
                    UPDATE notification_log SET cooldown_expires = ?
                    WHERE id = ?
                """, (cooldown_expires, notification_id))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error setting cooldown: %s", e)

    async def prune_notification_log(self, retention_days: int = 30, batch_size: int = 1000) -> int:
        """Prune notifications older than retention_days. v4.2.8: Batched."""
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("Notification log prune hit max batch limit")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM notification_log WHERE rowid IN ("
                        "SELECT rowid FROM notification_log WHERE timestamp < ? LIMIT ?)",
                        (cutoff, batch_size))
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error("Error pruning notification log: %s", e)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        return total_deleted

    # ====================================================================
    # v3.9.7 C4b: Notification Inbound
    # ====================================================================

    async def log_inbound(
        self,
        person_id: str | None,
        channel: str,
        raw_text: str,
        parsed_command: str | None,
        response_text: str | None,
        alert_id: int | None,
        success: bool,
    ) -> int | None:
        """Log an inbound message. Returns row ID."""
        try:
            now = dt_util.utcnow().isoformat()
            async with self._db() as db:
                cursor = await db.execute("""
                    INSERT INTO notification_inbound
                    (timestamp, person_id, channel, raw_text, parsed_command,
                     response_text, alert_id, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (now, person_id, channel, raw_text, parsed_command,
                      response_text, alert_id, 1 if success else 0))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error logging inbound message: %s", e)
            return None

    async def prune_inbound_log(self, retention_days: int = 30, batch_size: int = 1000) -> int:
        """Prune inbound messages older than retention_days. v4.2.8: Batched."""
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("Inbound log prune hit max batch limit")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM notification_inbound WHERE rowid IN ("
                        "SELECT rowid FROM notification_inbound WHERE timestamp < ? LIMIT ?)",
                        (cutoff, batch_size))
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error("Error pruning inbound log: %s", e)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        return total_deleted

    async def get_inbound_today(self) -> list[dict]:
        """Get all inbound messages from today."""
        try:
            today_start = dt_util.start_of_local_day().isoformat()
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_inbound
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                """, (today_start,))
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.error("Error fetching inbound today: %s", e)
            return []

    # ====================================================================
    # v3.7.11: Energy Daily Billing Snapshots
    # ====================================================================

    async def log_energy_daily(
        self,
        date_str: str,
        import_kwh: float,
        export_kwh: float,
        import_cost: float,
        export_credit: float,
        net_cost: float,
        consumption_kwh: float | None = None,
        solar_production_kwh: float | None = None,
        predicted_consumption_kwh: float | None = None,
        avg_temperature: float | None = None,
        prediction_error_pct: float | None = None,
        adjustment_factor: float | None = None,
        predicted_consumption_source: str | None = None,
    ) -> None:
        """Save daily energy snapshot. Uses INSERT OR REPLACE for idempotency.

        R1 (2026-07-16): ``predicted_consumption_source`` marks which
        estimator arm produced ``predicted_consumption_kwh``:
        ``v1_regression`` / ``dow_legacy`` / ``fallback`` (const strings in
        ``energy_const.PRED_CONSUMPTION_SOURCE_*``).
        """
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO energy_daily
                    (date, import_kwh, export_kwh, import_cost, export_credit,
                     net_cost, consumption_kwh, solar_production_kwh,
                     predicted_consumption_kwh, avg_temperature,
                     prediction_error_pct, adjustment_factor,
                     predicted_consumption_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date_str, import_kwh, export_kwh, import_cost,
                    export_credit, net_cost, consumption_kwh,
                    solar_production_kwh, predicted_consumption_kwh,
                    avg_temperature, prediction_error_pct, adjustment_factor,
                    predicted_consumption_source,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving energy daily snapshot: %s", e)

    async def get_energy_daily_for_cycle(
        self, cycle_start: str, cycle_end: str
    ) -> dict:
        """Sum energy_daily rows for a billing cycle date range.

        Returns dict with total import/export/cost and day count.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as days,
                        COALESCE(SUM(import_kwh), 0) as total_import,
                        COALESCE(SUM(export_kwh), 0) as total_export,
                        COALESCE(SUM(import_cost), 0) as total_import_cost,
                        COALESCE(SUM(export_credit), 0) as total_export_credit,
                        COALESCE(SUM(net_cost), 0) as total_net_cost
                    FROM energy_daily
                    WHERE date >= ? AND date < ?
                """, (cycle_start, cycle_end))
                row = await cursor.fetchone()
                if row:
                    return {
                        "days": row[0],
                        "import_kwh": row[1],
                        "export_kwh": row[2],
                        "import_cost": row[3],
                        "export_credit": row[4],
                        "net_cost": row[5],
                    }
                return {"days": 0, "import_kwh": 0, "export_kwh": 0,
                        "import_cost": 0, "export_credit": 0, "net_cost": 0}
        except Exception as e:
            _LOGGER.error("Error querying energy daily for cycle: %s", e)
            return {"days": 0, "import_kwh": 0, "export_kwh": 0,
                    "import_cost": 0, "export_credit": 0, "net_cost": 0}

    async def get_energy_daily_recent(self, days: int = 30) -> list[dict]:
        """Get recent energy_daily rows for accuracy restore + regression.

        Returns list of dicts with all columns, ordered by date ascending.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT date, consumption_kwh, predicted_consumption_kwh,
                           prediction_error_pct, adjustment_factor,
                           avg_temperature
                    FROM energy_daily
                    WHERE consumption_kwh IS NOT NULL
                    ORDER BY date DESC
                    LIMIT ?
                """, (days,))
                rows = await cursor.fetchall()
                return [dict(row) for row in reversed(rows)]
        except Exception as e:
            _LOGGER.error("Error querying recent energy daily: %s", e)
            return []

    async def get_energy_temp_pairs(self, min_days: int = 30) -> list[tuple]:
        """Get consumption-temperature pairs for regression fitting.

        Returns list of (consumption_kwh, avg_temperature) tuples.
        Only includes rows where both values are non-null.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute("""
                    SELECT consumption_kwh, avg_temperature
                    FROM energy_daily
                    WHERE consumption_kwh IS NOT NULL
                      AND avg_temperature IS NOT NULL
                    ORDER BY date DESC
                    LIMIT 90
                """)
                rows = await cursor.fetchall()
                if len(rows) >= min_days:
                    return [(row[0], row[1]) for row in rows]
                return []
        except Exception as e:
            _LOGGER.error("Error querying temp pairs: %s", e)
            return []

    # ── Peak import history (load shedding auto-learning) ──────────

    async def save_peak_import_history(self, readings: list[float]) -> None:
        """Persist peak import readings for load shedding auto-learning.

        Replaces all rows — called hourly from Energy Coordinator.
        Keeps at most 1500 readings (matches in-memory cap).
        The learned threshold is recomputed from readings on each cycle,
        so only the raw readings need persistence.
        """
        try:
            async with self._db() as db:
                await db.execute("DELETE FROM energy_peak_import")
                if readings:
                    await db.executemany(
                        "INSERT INTO energy_peak_import (seq, import_kw) VALUES (?, ?)",
                        [(i, r) for i, r in enumerate(readings)],
                    )
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving peak import history: %s", e)

    async def get_peak_import_history(self) -> list[float]:
        """Restore peak import readings for load shedding auto-learning.

        Returns list of import_kw readings in original order.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT import_kw FROM energy_peak_import ORDER BY seq ASC"
                )
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            _LOGGER.error("Error restoring peak import history: %s", e)
            return []

    # =========================================================================
    # v3.11.0: EVSE STATE PERSISTENCE
    # =========================================================================

    async def save_evse_state(
        self,
        evse_id: str,
        paused_by_energy: bool,
        excess_solar_active: bool,
    ) -> None:
        """Save EVSE state for restart recovery."""
        try:
            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO evse_state
                        (evse_id, paused_by_energy, excess_solar_active, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    evse_id,
                    int(paused_by_energy),
                    int(excess_solar_active),
                    dt_util.utcnow().isoformat(),
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving EVSE state for %s: %s", evse_id, e)

    async def restore_evse_state(
        self,
        max_age_hours: float | None = 10.0,
    ) -> dict[str, dict[str, bool]]:
        """Restore EVSE states from DB. Returns {evse_id: {paused, excess_solar}}.

        v<next>: Adds `max_age_hours` staleness guard. Rows whose `updated_at`
        is older than the cutoff are skipped at read time (no DELETE — Bug
        Class #25). Default 10h covers a normal overnight outage but rejects
        a multi-day power outage where stale pause-intent should not steer
        today's decisions. Pass `None` to disable the filter entirely (for
        callers that want raw rows). `updated_at` is parsed via
        `dt_util.parse_datetime` (NOT `datetime.fromisoformat` — Bug Class
        #13/#21). Rows with missing / unparseable `updated_at` are skipped
        gracefully with INFO log.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT evse_id, paused_by_energy, excess_solar_active, "
                    "updated_at FROM evse_state"
                )
                rows = await cursor.fetchall()
                if max_age_hours is None:
                    return {
                        row[0]: {
                            "paused_by_energy": bool(row[1]),
                            "excess_solar_active": bool(row[2]),
                        }
                        for row in rows
                    }
                cutoff = dt_util.utcnow() - timedelta(hours=float(max_age_hours))
                result: dict[str, dict[str, bool]] = {}
                for row in rows:
                    evse_id, paused, excess, updated_at = row[0], row[1], row[2], row[3]
                    parsed = dt_util.parse_datetime(updated_at) if updated_at else None
                    if parsed is None:
                        _LOGGER.info(
                            "EVSE state row %s has missing/unparseable updated_at "
                            "(%r) — skipping restore",
                            evse_id, updated_at,
                        )
                        continue
                    # Guarantee tz-aware comparison
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=dt_util.UTC)
                    if parsed < cutoff:
                        _LOGGER.info(
                            "EVSE state row %s older than %sh — skipping restore",
                            evse_id, max_age_hours,
                        )
                        continue
                    result[evse_id] = {
                        "paused_by_energy": bool(paused),
                        "excess_solar_active": bool(excess),
                    }
                return result
        except Exception as e:
            _LOGGER.error("Error restoring EVSE state: %s", e)
            return {}

    # =========================================================================
    # v3.11.0: CLEANUP METHODS
    # =========================================================================

    async def cleanup_energy_history(self, retention_days: int = 180, batch_size: int = 1000) -> int:
        """Delete energy_history rows older than retention_days. v4.2.8: Batched."""
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("Energy history cleanup hit max batch limit")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM energy_history WHERE rowid IN ("
                        "SELECT rowid FROM energy_history WHERE timestamp < ? LIMIT ?)",
                        (cutoff, batch_size))
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error("Error cleaning up energy history: %s", e)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info("Energy history cleanup: deleted %d rows older than %d days", total_deleted, retention_days)
        return total_deleted

    async def cleanup_external_conditions(self, retention_days: int = 90, batch_size: int = 1000) -> int:
        """Delete external_conditions rows older than retention_days. v4.2.8: Batched."""
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("External conditions cleanup hit max batch limit")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM external_conditions WHERE rowid IN ("
                        "SELECT rowid FROM external_conditions WHERE timestamp < ? LIMIT ?)",
                        (cutoff, batch_size))
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error("Error cleaning up external conditions: %s", e)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info("External conditions cleanup: deleted %d rows older than %d days", total_deleted, retention_days)
        return total_deleted

    # =========================================================================
    # v3.13.0: CIRCUIT STATE PERSISTENCE
    # =========================================================================

    async def save_circuit_state(self, circuits: dict[str, dict]) -> None:
        """Save circuit monitor state for restart persistence.

        Args:
            circuits: dict mapping circuit_id to state dict with keys:
                was_loaded (bool), zero_since (float|None), alerted (bool)
        """
        if not circuits:
            return
        try:
            now = dt_util.utcnow().isoformat()
            async with self._db() as db:
                try:
                    for circuit_id, state in circuits.items():
                        # Store zero_since as string repr of float for round-trip
                        zero_since = state.get("zero_since")
                        zero_since_str = str(zero_since) if zero_since is not None else None
                        await db.execute("""
                            INSERT OR REPLACE INTO circuit_state
                                (circuit_id, was_loaded, zero_since, alerted, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            circuit_id,
                            1 if state.get("was_loaded") else 0,
                            zero_since_str,
                            1 if state.get("alerted") else 0,
                            now,
                        ))
                    await db.commit()
                    _LOGGER.debug("Saved circuit state for %d circuits", len(circuits))
                except Exception as e:
                    _LOGGER.error("Error saving circuit state: %s", e)
                    try:
                        await db.rollback()
                    except Exception:
                        pass
        except Exception as e:
            _LOGGER.error("Error connecting to DB for circuit state save: %s", e)

    async def restore_circuit_state(self) -> dict[str, dict]:
        """Restore circuit monitor state after restart.

        Returns:
            dict mapping circuit_id to state dict with keys:
                was_loaded (bool), zero_since (float|None), alerted (bool)
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT circuit_id, was_loaded, zero_since, alerted FROM circuit_state"
                )
                rows = await cursor.fetchall()
                result = {}
                for row in rows:
                    # Convert zero_since back to float (stored as text)
                    raw_zs = row["zero_since"]
                    zero_since = float(raw_zs) if raw_zs is not None else None
                    result[row["circuit_id"]] = {
                        "was_loaded": bool(row["was_loaded"]),
                        "zero_since": zero_since,
                        "alerted": bool(row["alerted"]),
                    }
                if result:
                    _LOGGER.info("Restored circuit state for %d circuits", len(result))
                return result
        except Exception as e:
            _LOGGER.error("Error restoring circuit state: %s", e)
            return {}

    # =========================================================================
    # v3.15.0: ENVOY CACHE PERSISTENCE
    # =========================================================================

    async def save_envoy_cache(self, data: dict[str, float | None]) -> None:
        """Save last-known Envoy sensor values (singleton row, upserted each cycle).

        Args:
            data: dict with keys matching envoy_cache columns (soc, net_power, etc.)
        """
        try:
            now = dt_util.utcnow().isoformat()
            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO envoy_cache
                        (id, soc, net_power, solar_production, battery_power,
                         battery_capacity, lifetime_net_import, lifetime_net_export,
                         lifetime_production, lifetime_consumption,
                         lifetime_battery_charged, lifetime_battery_discharged,
                         updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data.get("soc"),
                    data.get("net_power"),
                    data.get("solar_production"),
                    data.get("battery_power"),
                    data.get("battery_capacity"),
                    data.get("lifetime_net_import"),
                    data.get("lifetime_net_export"),
                    data.get("lifetime_production"),
                    data.get("lifetime_consumption"),
                    data.get("lifetime_battery_charged"),
                    data.get("lifetime_battery_discharged"),
                    now,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving envoy cache: %s", e)

    async def restore_envoy_cache(self) -> dict[str, Any] | None:
        """Restore last-known Envoy sensor values.

        Returns:
            dict with cached values + updated_at, or None if no cache.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM envoy_cache WHERE id = 1"
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                result = {k: row[k] for k in row.keys() if k != "id"}
                _LOGGER.info("Restored envoy cache (updated %s)", result.get("updated_at"))
                return result
        except Exception as e:
            _LOGGER.error("Error restoring envoy cache: %s", e)
            return None

    # =========================================================================
    # v3.15.0: MIDNIGHT SNAPSHOT PERSISTENCE
    # =========================================================================

    async def save_midnight_snapshot(self, data: dict[str, Any]) -> None:
        """Save midnight lifetime snapshots + billing accumulators.

        Args:
            data: dict with snapshot_date, lifetime_* values, and billing accumulators
        """
        try:
            now = dt_util.utcnow().isoformat()
            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO energy_midnight_snapshot
                        (id, snapshot_date, lifetime_consumption, lifetime_production,
                         lifetime_net_import, lifetime_net_export,
                         lifetime_battery_charged, lifetime_battery_discharged,
                         import_kwh_today, export_kwh_today,
                         import_cost_today, export_credit_today, net_cost_today,
                         updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data.get("snapshot_date"),
                    data.get("lifetime_consumption"),
                    data.get("lifetime_production"),
                    data.get("lifetime_net_import"),
                    data.get("lifetime_net_export"),
                    data.get("lifetime_battery_charged"),
                    data.get("lifetime_battery_discharged"),
                    data.get("import_kwh_today", 0),
                    data.get("export_kwh_today", 0),
                    data.get("import_cost_today", 0),
                    data.get("export_credit_today", 0),
                    data.get("net_cost_today", 0),
                    now,
                ))
                await db.commit()
                _LOGGER.debug("Saved midnight snapshot for %s", data.get("snapshot_date"))
        except Exception as e:
            _LOGGER.error("Error saving midnight snapshot: %s", e)

    async def restore_midnight_snapshot(self) -> dict[str, Any] | None:
        """Restore midnight snapshot (lifetime values + billing accumulators).

        Returns:
            dict with snapshot data, or None if no snapshot exists.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM energy_midnight_snapshot WHERE id = 1"
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                result = {k: row[k] for k in row.keys() if k != "id"}
                _LOGGER.info(
                    "Restored midnight snapshot for %s", result.get("snapshot_date")
                )
                return result
        except Exception as e:
            _LOGGER.error("Error restoring midnight snapshot: %s", e)
            return None

    # =========================================================================
    # v3.15.0: ENERGY STATE KEY-VALUE STORE
    # =========================================================================

    async def save_energy_state(self, key: str, value: str) -> None:
        """Save a key-value pair to the energy state store."""
        try:
            now = dt_util.utcnow().isoformat()
            async with self._db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO energy_state (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, value, now))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving energy state key '%s': %s", key, e)

    async def restore_energy_state(self, key: str) -> str | None:
        """Restore a value from the energy state store.

        Returns:
            The stored value string, or None if not found.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT value FROM energy_state WHERE key = ?", (key,)
                )
                row = await cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            _LOGGER.error("Error restoring energy state key '%s': %s", key, e)
            return None

    async def restore_energy_state_with_age(
        self,
        key: str,
        max_age_hours: float | None = 10.0,
    ) -> str | None:
        """Restore an energy_state value, gated by `updated_at` staleness.

        Sibling of `restore_energy_state`. Returns the stored value string,
        or None if the row is missing, older than `max_age_hours`, or has an
        unparseable `updated_at`. Existing callers that pass no `max_age_hours`
        use the default 10h envelope (see `restore_evse_state` for rationale).
        Pass `None` to disable the filter.

        Honors Bug Class #13/#21: `updated_at` is parsed via
        `dt_util.parse_datetime` (NOT `datetime.fromisoformat`).
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT value, updated_at FROM energy_state WHERE key = ?",
                    (key,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                value, updated_at = row[0], row[1]
                if max_age_hours is None:
                    return value
                parsed = dt_util.parse_datetime(updated_at) if updated_at else None
                if parsed is None:
                    _LOGGER.info(
                        "energy_state key %s has missing/unparseable updated_at "
                        "(%r) — skipping restore",
                        key, updated_at,
                    )
                    return None
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_util.UTC)
                cutoff = dt_util.utcnow() - timedelta(hours=float(max_age_hours))
                if parsed < cutoff:
                    _LOGGER.info(
                        "energy_state key %s older than %sh — skipping restore",
                        key, max_age_hours,
                    )
                    return None
                return value
        except Exception as e:
            _LOGGER.error(
                "Error restoring energy state key '%s' with age: %s", key, e
            )
            return None

    async def get_consumption_history(self, days: int = 60) -> list[dict]:
        """Get recent energy_daily rows for consumption history restore.

        Returns list of dicts with date, consumption_kwh, day_of_week.
        Only returns rows where consumption_kwh is not None.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT date, consumption_kwh
                    FROM energy_daily
                    WHERE consumption_kwh IS NOT NULL
                    ORDER BY date DESC
                    LIMIT ?
                """, (days,))
                rows = await cursor.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "date": row["date"],
                        "consumption_kwh": row["consumption_kwh"],
                    })
                if result:
                    _LOGGER.info(
                        "Retrieved %d consumption history rows for restore", len(result)
                    )
                return result
        except Exception as e:
            _LOGGER.error("Error getting consumption history: %s", e)
            return []

    # =========================================================================
    # v3.20.0: ROOM STATE PERSISTENCE
    # =========================================================================

    async def save_room_state(self, room_id: str, state: dict) -> None:
        """Save room automation state for restart resilience.

        Called periodically (every 5 minutes) by the room coordinator
        as a DB backup alongside RestoreEntity state persistence.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO room_state
                    (room_id, became_occupied_time, last_occupied_state,
                     occupancy_first_detected, failsafe_fired,
                     last_trigger_source, last_lux_zone,
                     last_timed_open_date, last_timed_close_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        room_id,
                        state.get("became_occupied_time"),
                        1 if state.get("last_occupied_state") else 0,
                        state.get("occupancy_first_detected"),
                        1 if state.get("failsafe_fired") else 0,
                        state.get("last_trigger_source"),
                        state.get("last_lux_zone"),
                        state.get("last_timed_open_date"),
                        state.get("last_timed_close_date"),
                        dt_util.now().isoformat(),
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning("Failed to save room state for %s: %s", room_id, err)

    async def get_room_state(self, room_id: str) -> dict | None:
        """Get saved room automation state.

        Returns a dict of column names to values, or None if not found.
        Used as fallback when RestoreEntity state is unavailable.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT * FROM room_state WHERE room_id = ?",
                    (room_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        except Exception as err:
            _LOGGER.warning("Failed to get room state for %s: %s", room_id, err)
            return None

    # =========================================================================
    # v4.2.28: ROOM ENERGY BASELINE PERSISTENCE
    # =========================================================================

    async def save_room_energy_baseline(
        self,
        room_id: str,
        sensor_id: str,
        baseline_value: float,
        set_at: str,
        needs_reset: bool = False,
    ) -> None:
        """Save a single energy baseline for restart resilience.

        Called when a room coordinator establishes or refreshes a baseline
        (midnight reset, first-seen, stale-baseline recovery, sanity-guard
        reset). Writes happen O(N_sensors) per day per room — negligible
        on the URA write queue.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO room_energy_baselines
                    (room_id, sensor_id, baseline_value, baseline_set_at, needs_reset)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        room_id,
                        sensor_id,
                        float(baseline_value),
                        set_at,
                        1 if needs_reset else 0,
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "Failed to save energy baseline for %s/%s: %s",
                room_id, sensor_id, err,
            )

    async def load_room_energy_baselines(self, room_id: str) -> dict:
        """Return {sensor_id: {baseline_value, baseline_set_at, needs_reset}}
        for the given room. Empty dict if none persisted.

        v4.2.28: uses fetchall() rather than `async for row in cursor` to avoid
        runtime risk on older aiosqlite versions (Tier 1 review HIGH #2).
        """
        out: dict = {}
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT sensor_id, baseline_value, baseline_set_at, needs_reset
                       FROM room_energy_baselines WHERE room_id = ?""",
                    (room_id,),
                )
                rows = await cursor.fetchall()
                for row in rows:
                    out[row[0]] = {
                        "baseline_value": row[1],
                        "baseline_set_at": row[2],
                        "needs_reset": bool(row[3]),
                    }
            return out
        except Exception as err:
            _LOGGER.warning(
                "Failed to load energy baselines for %s: %s", room_id, err,
            )
            return {}

    async def get_energy_baseline_schema_version(self) -> int | None:
        """Return the schema-version sentinel stored in room_energy_baselines.

        Returns 0 (treat as pre-versioned legacy) if no sentinel row exists.
        Returns ``None`` on a transient DB read error so the caller can
        skip the migration this boot instead of spuriously firing a full
        reset on a flaky read (fix-up pass A-M2).

        D1 migration: when the returned value is < ENERGY_BASELINE_SCHEMA_VERSION,
        the coordinator resets all rows once on first boot, then writes the
        current version via set_energy_baseline_schema_version().
        """
        from .const import (
            ENERGY_BASELINE_VERSION_ROOM_ID,
            ENERGY_BASELINE_VERSION_SENSOR_ID,
        )
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT baseline_value FROM room_energy_baselines
                       WHERE room_id = ? AND sensor_id = ?""",
                    (
                        ENERGY_BASELINE_VERSION_ROOM_ID,
                        ENERGY_BASELINE_VERSION_SENSOR_ID,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    return 0
                try:
                    return int(row[0])
                except (TypeError, ValueError):
                    return 0
        except Exception as err:
            _LOGGER.warning(
                "Failed to read energy_baseline schema version: %s", err,
            )
            return None

    async def set_energy_baseline_schema_version(self, version: int) -> None:
        """Write the schema-version sentinel into room_energy_baselines.

        Uses the existing INSERT-OR-REPLACE path so no new schema or write
        queue is introduced (post write-flood incident discipline).
        """
        from .const import (
            ENERGY_BASELINE_VERSION_ROOM_ID,
            ENERGY_BASELINE_VERSION_SENSOR_ID,
        )
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO room_energy_baselines
                    (room_id, sensor_id, baseline_value, baseline_set_at, needs_reset)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        ENERGY_BASELINE_VERSION_ROOM_ID,
                        ENERGY_BASELINE_VERSION_SENSOR_ID,
                        float(version),
                        dt_util.utcnow().isoformat(),
                        0,
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "Failed to write energy_baseline schema version: %s", err,
            )

    async def migrate_energy_baselines_if_needed(self, target_version: int) -> tuple[bool, int]:
        """Atomically check the schema-version sentinel and reset if stale.

        Fix-up pass A-M1: per-coordinator check-then-reset let a later
        room's reset wipe earlier rooms' freshly-written baselines (race
        across N room coordinators on first refresh). This method does
        SELECT version → if < target: DELETE all (except sentinel) +
        UPSERT sentinel — all inside a single queued write transaction
        (the write queue serializes coordinator calls → atomic). First
        room wins; the rest read the now-current sentinel and no-op.

        Returns ``(migration_ran, rows_deleted)``:
          - ``(False, 0)`` if the sentinel was already at or above target,
            or on read error (skip migration this boot).
          - ``(True, n)`` if the migration ran; ``n`` is rows deleted.
        """
        from .const import (
            ENERGY_BASELINE_VERSION_ROOM_ID,
            ENERGY_BASELINE_VERSION_SENSOR_ID,
        )
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """SELECT baseline_value FROM room_energy_baselines
                       WHERE room_id = ? AND sensor_id = ?""",
                    (
                        ENERGY_BASELINE_VERSION_ROOM_ID,
                        ENERGY_BASELINE_VERSION_SENSOR_ID,
                    ),
                )
                row = await cursor.fetchone()
                current = 0
                if row is not None:
                    try:
                        current = int(row[0])
                    except (TypeError, ValueError):
                        current = 0
                if current >= target_version:
                    return (False, 0)
                # Stale or missing — perform the reset + sentinel write in
                # the same transaction so the next caller sees the new
                # sentinel and skips.
                del_cursor = await db.execute(
                    """DELETE FROM room_energy_baselines
                       WHERE NOT (room_id = ? AND sensor_id = ?)""",
                    (
                        ENERGY_BASELINE_VERSION_ROOM_ID,
                        ENERGY_BASELINE_VERSION_SENSOR_ID,
                    ),
                )
                deleted = del_cursor.rowcount or 0
                await db.execute(
                    """INSERT OR REPLACE INTO room_energy_baselines
                    (room_id, sensor_id, baseline_value, baseline_set_at, needs_reset)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        ENERGY_BASELINE_VERSION_ROOM_ID,
                        ENERGY_BASELINE_VERSION_SENSOR_ID,
                        float(target_version),
                        dt_util.utcnow().isoformat(),
                        0,
                    ),
                )
                await db.commit()
                return (True, deleted)
        except Exception as err:
            _LOGGER.warning(
                "migrate_energy_baselines_if_needed failed: %s", err,
            )
            return (False, 0)

    async def reset_all_room_energy_baselines(self) -> int:
        """Delete every row in room_energy_baselines EXCEPT the schema-version
        sentinel. Returns count deleted. Called exactly once on first boot
        of code that introduces a new ENERGY_BASELINE_SCHEMA_VERSION.

        Cost is bounded by row count (one row per (room, sensor)) and runs
        outside the write-queue hot path (called from coordinator first-refresh).
        """
        from .const import (
            ENERGY_BASELINE_VERSION_ROOM_ID,
            ENERGY_BASELINE_VERSION_SENSOR_ID,
        )
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """DELETE FROM room_energy_baselines
                       WHERE NOT (room_id = ? AND sensor_id = ?)""",
                    (
                        ENERGY_BASELINE_VERSION_ROOM_ID,
                        ENERGY_BASELINE_VERSION_SENSOR_ID,
                    ),
                )
                await db.commit()
                return cursor.rowcount or 0
        except Exception as err:
            _LOGGER.warning(
                "reset_all_room_energy_baselines failed: %s", err,
            )
            return 0

    async def cleanup_room_energy_baselines(self, retention_days: int = 90) -> int:
        """Remove stale baselines older than retention_days. Batched per
        bug-class #25 (LIMIT 1000 per pass) and budgeted by nightly
        maintenance (Bug Class #28). Removes orphaned rows for rooms
        whose configuration no longer references the sensor.

        Fix-up pass A-H1: explicitly EXCLUDES the ``__schema_version__``
        sentinel row from cleanup. Without this, after 90 days the
        sentinel ages out → the next boot re-fires the D1 migration and
        wipes every baseline → recurring full reset cycle.
        """
        from datetime import timedelta as _td  # local import to avoid module top-level coupling
        from homeassistant.util import dt as _dtu
        from .const import (
            ENERGY_BASELINE_VERSION_ROOM_ID,
            ENERGY_BASELINE_VERSION_SENSOR_ID,
        )

        cutoff = (_dtu.utcnow() - _td(days=retention_days)).isoformat()
        total_deleted = 0
        try:
            while True:
                async with self._db() as db:
                    cursor = await db.execute(
                        """DELETE FROM room_energy_baselines
                        WHERE rowid IN (
                            SELECT rowid FROM room_energy_baselines
                            WHERE baseline_set_at < ?
                              AND NOT (room_id = ? AND sensor_id = ?)
                            LIMIT 1000
                        )""",
                        (
                            cutoff,
                            ENERGY_BASELINE_VERSION_ROOM_ID,
                            ENERGY_BASELINE_VERSION_SENSOR_ID,
                        ),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
                if deleted < 1000:
                    break
                await asyncio.sleep(0.1)
        except Exception as err:
            _LOGGER.warning("cleanup_room_energy_baselines failed: %s", err)
        return total_deleted

    # ====================================================================
    # v4.6.1 D2: Anomaly log cleanup with dual retention windows
    # ====================================================================

    async def cleanup_anomaly_log(
        self,
        retention_days_point_in_time: int = 90,
        retention_days_regime_shift: int = 365,
    ) -> int:
        """Delete old anomaly_log rows using per-class retention windows.

        Branches on the discriminator (``anomaly_type``, falling back to the
        legacy ``event_class`` alias) so historically significant
        regime_shift events are kept for a full year while point_in_time
        events cycle out at 90 days. Batched (LIMIT 1000 +
        asyncio.sleep(0.1)) matching the cleanup_room_energy_baselines
        pattern (Bug Class #27 prevention).
        Returns total rows deleted across all passes.

        v4.7.12 fix-up (Review A A3 + Review C C-M3 — convergent): widened
        the discriminator predicate from ``COALESCE(event_class, ...)`` to
        ``COALESCE(anomaly_type, event_class, 'point_in_time')`` so when
        v5.0 drops the ``event_class`` column the retention windows still
        evaluate correctly. Dual-write keeps both columns in sync today,
        so this change is a no-op until v5.0 — but locking it in now
        means v5.0 only has to drop the column.
        """
        from datetime import timedelta as _td
        from homeassistant.util import dt as _dtu

        now = _dtu.utcnow()
        cutoff_pit = (now - _td(days=retention_days_point_in_time)).isoformat()
        cutoff_rs = (now - _td(days=retention_days_regime_shift)).isoformat()
        total_deleted = 0

        try:
            while True:
                async with self._db() as db:
                    cursor = await db.execute(
                        """DELETE FROM anomaly_log
                        WHERE rowid IN (
                            SELECT rowid FROM anomaly_log
                            WHERE (
                                (COALESCE(anomaly_type, event_class, 'point_in_time') = 'regime_shift'
                                    AND timestamp < ?)
                                OR (COALESCE(anomaly_type, event_class, 'point_in_time') != 'regime_shift'
                                    AND timestamp < ?)
                            )
                            LIMIT 1000
                        )""",
                        (cutoff_rs, cutoff_pit),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
                if deleted < 1000:
                    break
                await asyncio.sleep(0.1)
        except Exception as err:
            _LOGGER.warning("cleanup_anomaly_log failed: %s", err, exc_info=True)
        return total_deleted

    # ====================================================================
    # Fix-up A-HIGH-1 (Batch 4) — decision_log retention prune per type
    # ====================================================================
    async def cleanup_decision_log(
        self,
        decision_type: str,
        retention_days: int,
        batch_size: int = 1000,
    ) -> int:
        """Delete `decision_log` rows of a given `decision_type` older than
        `retention_days`. Rows of OTHER decision_types are untouched.

        Sibling shape to `cleanup_anomaly_log` / `cleanup_room_energy_baselines`:
        batched (LIMIT + asyncio.sleep) so a large backlog doesn't stall
        the write queue during the nightly maintenance window.

        Wired into the nightly cadence in `__init__.py` per decision_type:
          * `dp_eval` — retention `CONF_DP_EVAL_LOG_RETENTION_DAYS`.
          * `blind_window_defer` — same retention as dp_eval today.
          * `blind_window_liveness_release` — same retention as dp_eval today.
        Returns total rows deleted across all passes.
        """
        from datetime import timedelta as _td
        from homeassistant.util import dt as _dtu

        if not decision_type or int(retention_days) <= 0:
            return 0
        cutoff = (_dtu.utcnow() - _td(days=int(retention_days))).isoformat()
        total_deleted = 0
        try:
            while True:
                async with self._db() as db:
                    cursor = await db.execute(
                        """DELETE FROM decision_log
                        WHERE rowid IN (
                            SELECT rowid FROM decision_log
                            WHERE decision_type = ?
                              AND timestamp < ?
                            LIMIT ?
                        )""",
                        (decision_type, cutoff, int(batch_size)),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
                if deleted < int(batch_size):
                    break
                await asyncio.sleep(0.1)
        except Exception as err:
            _LOGGER.warning(
                "cleanup_decision_log(%s, %d) failed: %s",
                decision_type, retention_days, err, exc_info=True,
            )
        return total_deleted

    # ====================================================================
    # v4.3.0 D4: Arbitrage cycle accounting
    # ====================================================================

    async def save_arbitrage_cycle(
        self,
        timestamp: str,
        soc_before: float | None,
        soc_after: float | None,
        kwh_charged: float,
        off_peak_rate: float,
        displaced_rate: float,
        round_trip_efficiency: float,
        savings: float,
        season: str | None,
    ) -> None:
        """Persist a single arbitrage cycle's accounting row."""
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO arbitrage_cycles
                    (timestamp, soc_before, soc_after, kwh_charged,
                     off_peak_rate, displaced_rate, round_trip_efficiency,
                     savings, season)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        timestamp,
                        float(soc_before) if soc_before is not None else None,
                        float(soc_after) if soc_after is not None else None,
                        float(kwh_charged),
                        float(off_peak_rate),
                        float(displaced_rate),
                        float(round_trip_efficiency),
                        float(savings),
                        season,
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning("Failed to save arbitrage cycle: %s", err)

    async def query_arbitrage_savings_since(self, since_iso: str) -> dict:
        """Return aggregate savings + cycle count + total kWh since a UTC ISO ts.

        Used by ROI sensors (today / cycle / total) and the PredictedBill
        counterfactual.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT COALESCE(SUM(savings), 0.0),
                              COALESCE(SUM(kwh_charged), 0.0),
                              COUNT(*)
                       FROM arbitrage_cycles WHERE timestamp >= ?""",
                    (since_iso,),
                )
                row = await cursor.fetchone()
                return {
                    "savings": float(row[0]) if row else 0.0,
                    "kwh_charged": float(row[1]) if row else 0.0,
                    "cycles": int(row[2]) if row else 0,
                }
        except Exception as err:
            _LOGGER.warning("query_arbitrage_savings_since failed: %s", err)
            return {"savings": 0.0, "kwh_charged": 0.0, "cycles": 0}

    async def query_arbitrage_savings_total(self) -> dict:
        """Lifetime savings + cycle count + kWh."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT COALESCE(SUM(savings), 0.0),
                              COALESCE(SUM(kwh_charged), 0.0),
                              COUNT(*)
                       FROM arbitrage_cycles""",
                )
                row = await cursor.fetchone()
                return {
                    "savings": float(row[0]) if row else 0.0,
                    "kwh_charged": float(row[1]) if row else 0.0,
                    "cycles": int(row[2]) if row else 0,
                }
        except Exception as err:
            _LOGGER.warning("query_arbitrage_savings_total failed: %s", err)
            return {"savings": 0.0, "kwh_charged": 0.0, "cycles": 0}

    async def query_arbitrage_last_cycle(self) -> dict | None:
        """Return the most recent cycle's full row for audit attributes.

        Returns None if no cycles persisted.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT timestamp, soc_before, soc_after, kwh_charged,
                              off_peak_rate, displaced_rate,
                              round_trip_efficiency, savings, season
                       FROM arbitrage_cycles ORDER BY id DESC LIMIT 1""",
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                return {
                    "timestamp": row[0],
                    "soc_before": row[1],
                    "soc_after": row[2],
                    "kwh_charged": float(row[3]),
                    "off_peak_rate": float(row[4]),
                    "displaced_rate": float(row[5]),
                    "round_trip_efficiency": float(row[6]),
                    "savings": float(row[7]),
                    "season": row[8],
                }
        except Exception as err:
            _LOGGER.warning("query_arbitrage_last_cycle failed: %s", err)
            return None

    async def query_arbitrage_pace_recent(self, days: int = 7) -> dict:
        """Avg savings/day + total cycles over the last N days.

        Used to project remaining savings for the bill cycle on
        PredictedBillSensor's counterfactual.

        v4.3.0 Review C2 fix: bucket cycles into LOCAL days in Python rather
        than SQL DATE() (which interprets the UTC ISO string as local time
        and miscounts boundaries for non-UTC users). Fetch raw timestamps,
        convert each via dt_util to local date, count distinct dates.
        """
        from datetime import timedelta as _td
        from homeassistant.util import dt as _dtu

        since = (_dtu.utcnow() - _td(days=days)).isoformat()
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT timestamp, savings FROM arbitrage_cycles
                       WHERE timestamp >= ?""",
                    (since,),
                )
                rows = await cursor.fetchall()
                total_savings = 0.0
                local_dates: set[str] = set()
                for ts_str, sav in rows:
                    total_savings += float(sav or 0.0)
                    parsed = _dtu.parse_datetime(ts_str)
                    if parsed is None:
                        continue
                    local_dates.add(_dtu.as_local(parsed).date().isoformat())
                days_with_cycles = len(local_dates)
                avg_per_day = (
                    total_savings / days_with_cycles
                    if days_with_cycles > 0 else 0.0
                )
                return {
                    "avg_savings_per_day": avg_per_day,
                    "days_with_cycles": days_with_cycles,
                    "lookback_days": days,
                }
        except Exception as err:
            _LOGGER.warning("query_arbitrage_pace_recent failed: %s", err)
            return {"avg_savings_per_day": 0.0, "days_with_cycles": 0, "lookback_days": days}

    # ====================================================================
    # Energy Savings Unification (cycle #7) — lifetime baseline
    # ====================================================================

    async def get_savings_baseline(self, component: str) -> dict | None:
        """Return the lifetime baseline row for a savings component.

        Components in use: "arbitrage", "peak_avoidance", "kwh_avoided".
        Returns None if no baseline is recorded yet.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT baseline_usd, baseline_kwh, first_recorded_iso
                       FROM savings_lifetime_baseline WHERE component = ?""",
                    (component,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                return {
                    "baseline_usd": float(row[0] or 0.0),
                    "baseline_kwh": float(row[1] or 0.0),
                    "first_recorded_iso": row[2],
                }
        except Exception as err:
            _LOGGER.warning("get_savings_baseline(%s) failed: %s", component, err)
            return None

    async def save_savings_baseline(
        self,
        component: str,
        baseline_usd: float,
        baseline_kwh: float,
        first_recorded_iso: str,
    ) -> None:
        """Persist the baseline row for a savings component (idempotent).

        Uses INSERT OR IGNORE so an existing baseline is never overwritten —
        the baseline is a one-shot cutover snapshot by design.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR IGNORE INTO savings_lifetime_baseline
                       (component, baseline_usd, baseline_kwh, first_recorded_iso)
                       VALUES (?, ?, ?, ?)""",
                    (
                        component,
                        float(baseline_usd),
                        float(baseline_kwh),
                        first_recorded_iso,
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "save_savings_baseline(%s) failed: %s", component, err
            )

    async def update_savings_baseline(
        self,
        component: str,
        baseline_usd: float,
        baseline_kwh: float,
    ) -> None:
        """UPDATE the baseline row for a component (post-cutover rollup).

        Fix-up B-HIGH-1/2: the lifetime baseline row is seeded once via
        `save_savings_baseline` (INSERT OR IGNORE) at cutover; subsequent
        midnight rollups fold the in-RAM lifetime_delta into the row via
        this method so the delta can be reset to 0 without losing money.
        Call cadence: at most twice/day (peak_avoidance + kwh_avoided) at
        local midnight — NOT per-tick (respects v5.2.1 write-flood lesson).
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """UPDATE savings_lifetime_baseline
                       SET baseline_usd = ?, baseline_kwh = ?
                       WHERE component = ?""",
                    (float(baseline_usd), float(baseline_kwh), component),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "update_savings_baseline(%s) failed: %s", component, err
            )

    # ====================================================================
    # Activity Log
    # ====================================================================

    async def log_activity(
        self,
        timestamp: str,
        coordinator: str,
        action: str,
        room: str | None,
        zone: str | None,
        importance: str,
        description: str,
        details_json: str | None,
        entity_id: str | None,
    ) -> None:
        """Write an activity log entry."""
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO ura_activity_log
                    (timestamp, coordinator, action, room, zone, importance,
                     description, details_json, entity_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        timestamp,
                        coordinator,
                        action,
                        room,
                        zone,
                        importance,
                        description,
                        details_json,
                        entity_id,
                    ),
                )
                await db.commit()
        except Exception as e:
            _LOGGER.debug("Activity log write failed (non-critical): %s", e)

    async def prune_activity_log(self, batch_size: int = 1000) -> int:
        """Prune activity log entries past retention window.

        Info: 7 days, notable/critical: 30 days.
        v4.2.8: Batched to avoid blocking write queue.
        """
        now = dt_util.utcnow()
        info_cutoff = (now - timedelta(days=7)).isoformat()
        notable_cutoff = (now - timedelta(days=30)).isoformat()
        total_deleted = 0
        # SAFETY: where clauses are hardcoded literals — never from user input
        for cutoff, where in [
            (info_cutoff, "importance = 'info' AND timestamp < ?"),
            (notable_cutoff, "importance != 'info' AND timestamp < ?"),
        ]:
            _batch_count = 0  # Reset per-tier
            while True:
                _batch_count += 1
                if _batch_count > 500:
                    _LOGGER.warning("Activity log prune hit max batch limit")
                    break
                try:
                    async with self._db() as db:
                        cursor = await db.execute(
                            f"DELETE FROM ura_activity_log WHERE rowid IN ("
                            f"SELECT rowid FROM ura_activity_log WHERE {where} LIMIT ?)",
                            (cutoff, batch_size),
                        )
                        await db.commit()
                        deleted = cursor.rowcount
                        total_deleted += deleted
                except Exception as e:
                    _LOGGER.error("Error pruning activity log: %s", e)
                    break
                if deleted < batch_size:
                    break
                await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info("Pruned %d activity log entries", total_deleted)
        return total_deleted

    # ====================================================================
    # Optimization findings (Phase 1 — Optimization Coordinator)
    # ====================================================================

    async def log_finding(self, finding) -> int | None:
        """Single-path writer for OptimizationFinding rows.

        Accepts a structurally-duck-typed OptimizationFinding (the dataclass
        lives in ``domain_coordinators.optimization`` to avoid a circular
        import). Returns the new ``id`` on success, ``None`` on failure.
        Modeled on ``save_anomaly_event`` (single-path writer, NULL-able
        metric columns, payload extras as JSON).
        """
        import json as _json

        # C-MED-1: never write the literal string "None" as the dimension —
        # that pollutes the analytics index. Reject the row with a warning
        # so the caller can be fixed; use an explicit ``unknown`` sentinel
        # if a None somehow leaks through severity too.
        _dim = getattr(finding, "dimension", None)
        if _dim is None:
            _LOGGER.warning(
                "log_finding: finding.dimension is None; rejecting row "
                "(target_id=%s, description=%s)",
                getattr(finding, "target_id", None),
                getattr(finding, "description", None),
            )
            return None
        _sev = getattr(finding, "severity", None)
        if _sev is None:
            _LOGGER.warning(
                "log_finding: finding.severity is None; rejecting row "
                "(target_id=%s, dimension=%s)",
                getattr(finding, "target_id", None),
                _dim,
            )
            return None

        try:
            payload_json = (
                _json.dumps(finding.payload, default=str)
                if getattr(finding, "payload", None) is not None
                else None
            )
            proposed_action_json = (
                _json.dumps(finding.proposed_action, default=str)
                if getattr(finding, "proposed_action", None) is not None
                else None
            )
            predicted_effect_json = (
                _json.dumps(finding.predicted_effect, default=str)
                if getattr(finding, "predicted_effect", None) is not None
                else None
            )
            observed_effect_json = (
                _json.dumps(finding.observed_effect, default=str)
                if getattr(finding, "observed_effect", None) is not None
                else None
            )
        except (TypeError, ValueError) as enc_err:
            _LOGGER.warning("log_finding: payload JSON encode failed: %s", enc_err)
            payload_json = proposed_action_json = None
            predicted_effect_json = observed_effect_json = None

        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """INSERT INTO optimization_findings
                       (timestamp, level, target_id, dimension, severity,
                        confidence, score, description, proposed_action_json,
                        action_class, applied_action_id, applied_outcome,
                        predicted_effect_json, observed_effect_json,
                        payload_json, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        finding.timestamp,
                        finding.level,
                        finding.target_id,
                        str(finding.dimension),
                        finding.severity,
                        finding.confidence,
                        finding.score,
                        finding.description,
                        proposed_action_json,
                        finding.action_class,
                        finding.applied_action_id,
                        finding.applied_outcome,
                        predicted_effect_json,
                        observed_effect_json,
                        payload_json,
                        finding.created_by,
                    ),
                )
                await db.commit()
                row_id = cursor.lastrowid
                return int(row_id) if row_id is not None else None
        except Exception as e:
            _LOGGER.warning("log_finding: insert failed: %s", e)
            return None

    async def log_findings_batch(self, findings: list) -> int:
        """Batched single-transaction writer for OptimizationFinding rows.

        v5.2.2 post-mortem fix for DB write-queue saturation: the cycle
        used to call ``log_finding`` (one ``_db()`` acquisition each) in
        a loop over N findings, which dumped N items into the single
        write queue back-to-back and starved core URA writes during the
        boot storm (35+ Sensor-Health findings/cycle).

        This DAO does ONE write-queue round-trip regardless of the
        finding count: a single ``self._db()`` acquisition, all rows
        ``executemany``'d in one transaction. Per-row None-guards mirror
        ``log_finding`` so a single bad row does NOT fail the batch —
        it's skipped with a warning, good rows still commit.

        Returns the count of rows actually written (0 if the batch was
        empty or every row was rejected by the None-guards / encode
        failed).
        """
        import json as _json

        if not findings:
            return 0

        # Pre-encode + guard rows first. Build the tuple list outside the
        # write-queue critical section so JSON encoding latency is not
        # held against the worker.
        rows: list[tuple] = []
        for finding in findings:
            # Mirror log_finding's None-guards: never persist NULL dim/sev.
            _dim = getattr(finding, "dimension", None)
            if _dim is None:
                _LOGGER.warning(
                    "log_findings_batch: skipping row with dimension=None "
                    "(target_id=%s, description=%s)",
                    getattr(finding, "target_id", None),
                    getattr(finding, "description", None),
                )
                continue
            _sev = getattr(finding, "severity", None)
            if _sev is None:
                _LOGGER.warning(
                    "log_findings_batch: skipping row with severity=None "
                    "(target_id=%s, dimension=%s)",
                    getattr(finding, "target_id", None),
                    _dim,
                )
                continue
            try:
                payload_json = (
                    _json.dumps(finding.payload, default=str)
                    if getattr(finding, "payload", None) is not None
                    else None
                )
                proposed_action_json = (
                    _json.dumps(finding.proposed_action, default=str)
                    if getattr(finding, "proposed_action", None) is not None
                    else None
                )
                predicted_effect_json = (
                    _json.dumps(finding.predicted_effect, default=str)
                    if getattr(finding, "predicted_effect", None) is not None
                    else None
                )
                observed_effect_json = (
                    _json.dumps(finding.observed_effect, default=str)
                    if getattr(finding, "observed_effect", None) is not None
                    else None
                )
            except (TypeError, ValueError) as enc_err:
                _LOGGER.warning(
                    "log_findings_batch: payload JSON encode failed for "
                    "target_id=%s — skipping row: %s",
                    getattr(finding, "target_id", None), enc_err,
                )
                continue
            rows.append((
                finding.timestamp,
                finding.level,
                finding.target_id,
                str(finding.dimension),
                finding.severity,
                finding.confidence,
                finding.score,
                finding.description,
                proposed_action_json,
                finding.action_class,
                finding.applied_action_id,
                finding.applied_outcome,
                predicted_effect_json,
                observed_effect_json,
                payload_json,
                finding.created_by,
            ))

        if not rows:
            return 0

        try:
            async with self._db() as db:
                await db.executemany(
                    """INSERT INTO optimization_findings
                       (timestamp, level, target_id, dimension, severity,
                        confidence, score, description, proposed_action_json,
                        action_class, applied_action_id, applied_outcome,
                        predicted_effect_json, observed_effect_json,
                        payload_json, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                await db.commit()
                return len(rows)
        except Exception as e:
            _LOGGER.warning("log_findings_batch: insert failed: %s", e)
            return 0

    async def prune_optimization_findings(
        self, batch_size: int = 1000,
    ) -> int:
        """Prune optimization findings past retention window.

        30 days for severity=critical, 14 days for high, 7 days for
        medium/low. Same batched-DELETE shape as ``prune_activity_log`` to
        dodge Bug Class #25 (write-queue stalls on large deletes).
        """
        now = dt_util.utcnow()
        crit_cutoff = (now - timedelta(days=30)).isoformat()
        high_cutoff = (now - timedelta(days=14)).isoformat()
        low_cutoff = (now - timedelta(days=7)).isoformat()
        total_deleted = 0
        # SAFETY: where clauses are hardcoded literals — never from user input
        for cutoff, where in [
            (crit_cutoff, "severity = 'critical' AND timestamp < ?"),
            (high_cutoff, "severity = 'high' AND timestamp < ?"),
            (low_cutoff, "severity IN ('medium', 'low') AND timestamp < ?"),
        ]:
            _batch_count = 0
            while True:
                _batch_count += 1
                if _batch_count > 500:
                    _LOGGER.warning(
                        "optimization_findings prune hit max batch limit"
                    )
                    break
                try:
                    async with self._db() as db:
                        cursor = await db.execute(
                            f"DELETE FROM optimization_findings WHERE rowid IN ("
                            f"SELECT rowid FROM optimization_findings WHERE {where} LIMIT ?)",
                            (cutoff, batch_size),
                        )
                        await db.commit()
                        deleted = cursor.rowcount
                        total_deleted += deleted
                except Exception as e:
                    _LOGGER.error(
                        "Error pruning optimization_findings: %s", e
                    )
                    break
                if deleted < batch_size:
                    break
                await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info(
                "Pruned %d optimization_findings entries", total_deleted
            )
        return total_deleted

    async def get_recent_optimization_findings(
        self, limit: int = 20,
    ) -> list[dict]:
        """Read recent optimization findings (most recent first)."""
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT id, timestamp, level, target_id, dimension,
                              severity, confidence, score, description,
                              proposed_action_json, action_class,
                              applied_action_id, applied_outcome,
                              predicted_effect_json, observed_effect_json,
                              payload_json, created_by
                       FROM optimization_findings
                       ORDER BY timestamp DESC
                       LIMIT ?""",
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.warning(
                "get_recent_optimization_findings failed: %s", e,
            )
            return []

    # ====================================================================
    # v5.17.0 — Observability WebSocket read DAOs (anomaly_log, ura_activity_log)
    # ====================================================================
    #
    # Read-only, parameterized-only, server-side row cap. Consumed by
    # ``websocket_api.py``. Never route these through ``_db()``.
    # Column names are hard-coded allowlists; user-supplied values are
    # bound with ``?`` placeholders only.

    async def query_anomalies(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        coordinator_id: str | None = None,
        severity: str | None = None,
        anomaly_type: str | None = None,
        resolved: bool | None = None,
        cursor: int | None = None,
        limit: int = 50,
        columns: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """v5.17.0 — filtered + cursor-paginated read of ``anomaly_log``.

        Returns a dict envelope: ``{rows, next_cursor, page_size, capped}``.

        Discipline (falsifiable invariant §1 of the planning doc):
          * Uses ``_db_read()`` — PRAGMA query_only=ON hard-fails writes.
          * All filters are bound with ``?`` placeholders; column names are
            hard-coded (allowlist).
          * ``limit`` is clamped to ``WS_MAX_PAGE_SIZE`` server-side BEFORE
            SQL execution; the client-supplied value cannot bypass the cap.
          * Cursor is the numeric ``id`` of the last row returned by the
            prior page; we filter with ``id < :cursor`` and order by
            ``id DESC``.

        ``severity`` accepts either the numeric strings '0'..'4' (raw
        storage) or the name aliases mapped by
        ``WS_ANOMALY_SEVERITY_NAME_TO_NUMBER`` (B0 probe finding #4).
        """
        from .const import (
            WS_ANOMALY_COLUMNS,
            WS_ANOMALY_SEVERITY_NAME_TO_NUMBER,
            WS_ANOMALY_SEVERITY_NUMBERS,
            WS_MAX_PAGE_SIZE,
        )

        # Server-side cap wins — reviewer B invariant probe.
        requested_limit = int(limit) if isinstance(limit, int) and limit > 0 else 50
        page_size = min(requested_limit, WS_MAX_PAGE_SIZE)
        capped = requested_limit > WS_MAX_PAGE_SIZE

        # Column projection (allowlisted).
        if columns:
            projected = tuple(c for c in columns if c in WS_ANOMALY_COLUMNS)
            if not projected:
                projected = WS_ANOMALY_COLUMNS
        else:
            projected = WS_ANOMALY_COLUMNS

        # v5.17.0 review fix A3: intersect against the LIVE table columns
        # so ALTER-added columns (anomaly_type, correlation_id, recovery_at,
        # person_id, room_id, entity_id) don't trip an OperationalError on
        # an un-migrated DB. Cheap PRAGMA once per query.
        try:
            async with self._db_read() as _pdb:
                pcur = await _pdb.execute("PRAGMA table_info(anomaly_log)")
                live_cols = {row[1] for row in await pcur.fetchall()}
        except Exception as exc:
            raise ValueError(f"anomaly_log unavailable: {exc}") from exc
        projected = tuple(c for c in projected if c in live_cols) or ("id",)
        col_sql = ", ".join(projected)

        # Filter binding — parameterized only. Column names are literals.
        clauses: list[str] = []
        params: list = []
        if since is not None:
            try:
                datetime.fromisoformat(since)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid since: {exc}")
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            try:
                datetime.fromisoformat(until)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid until: {exc}")
            clauses.append("timestamp < ?")
            params.append(until)
        if coordinator_id is not None:
            clauses.append("coordinator_id = ?")
            params.append(coordinator_id)
        if severity is not None:
            # Name -> number mapping at the DAO boundary (B0 finding #4).
            sev_val = WS_ANOMALY_SEVERITY_NAME_TO_NUMBER.get(severity, severity)
            if sev_val not in WS_ANOMALY_SEVERITY_NUMBERS:
                raise ValueError(f"invalid severity: {severity!r}")
            clauses.append("severity = ?")
            params.append(sev_val)
        if anomaly_type is not None:
            clauses.append("anomaly_type = ?")
            params.append(anomaly_type)
        if resolved is not None:
            clauses.append("resolved = ?")
            params.append(1 if resolved else 0)
        if cursor is not None:
            clauses.append("id < ?")
            params.append(int(cursor))

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT {col_sql} FROM anomaly_log "
            f"{where_sql} ORDER BY id DESC LIMIT ?"
        )
        params.append(page_size)

        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(sql, tuple(params))
                rows = await cur.fetchall()
                row_dicts = [dict(r) for r in rows]
        except aiosqlite.OperationalError as e:
            # v5.17.0 review fix A3: don't swallow schema/operational
            # errors into an empty success — surface them so an empty feed
            # is diagnosable at the WS boundary.
            _LOGGER.warning("query_anomalies operational error: %s", e)
            raise ValueError(f"query_anomalies operational error: {e}") from e
        except Exception as e:
            _LOGGER.warning("query_anomalies failed: %s", e)
            return {"rows": [], "next_cursor": None, "page_size": page_size, "capped": capped}

        next_cursor = None
        if row_dicts and "id" in row_dicts[-1]:
            # id DESC means the smallest id in the page is at the end.
            next_cursor = row_dicts[-1]["id"]
        return {
            "rows": row_dicts,
            "next_cursor": next_cursor,
            "page_size": page_size,
            "capped": capped,
        }

    async def query_activities(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        coordinator: str | None = None,
        room: str | None = None,
        zone: str | None = None,
        importance: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
        columns: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """v5.17.0 — filtered + cursor-paginated read of ``ura_activity_log``.

        Mirrors ``query_anomalies`` discipline: ``_db_read``-only,
        parameterized filters, server-side cap, allowlisted column
        projection. importance is name-valued (B0 probe finding #4) so it
        is filtered as-is against the storage strings.
        """
        from .const import (
            WS_ACTIVITY_COLUMNS,
            WS_ACTIVITY_IMPORTANCE_VALUES,
            WS_MAX_PAGE_SIZE,
        )

        requested_limit = int(limit) if isinstance(limit, int) and limit > 0 else 50
        page_size = min(requested_limit, WS_MAX_PAGE_SIZE)
        capped = requested_limit > WS_MAX_PAGE_SIZE

        if columns:
            projected = tuple(c for c in columns if c in WS_ACTIVITY_COLUMNS)
            if not projected:
                projected = WS_ACTIVITY_COLUMNS
        else:
            projected = WS_ACTIVITY_COLUMNS
        col_sql = ", ".join(projected)

        clauses: list[str] = []
        params: list = []
        if since is not None:
            try:
                datetime.fromisoformat(since)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid since: {exc}")
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            try:
                datetime.fromisoformat(until)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid until: {exc}")
            clauses.append("timestamp < ?")
            params.append(until)
        if coordinator is not None:
            clauses.append("coordinator = ?")
            params.append(coordinator)
        if room is not None:
            clauses.append("room = ?")
            params.append(room)
        if zone is not None:
            clauses.append("zone = ?")
            params.append(zone)
        if importance is not None:
            if importance not in WS_ACTIVITY_IMPORTANCE_VALUES:
                raise ValueError(f"invalid importance: {importance!r}")
            clauses.append("importance = ?")
            params.append(importance)
        if cursor is not None:
            clauses.append("id < ?")
            params.append(int(cursor))

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT {col_sql} FROM ura_activity_log "
            f"{where_sql} ORDER BY id DESC LIMIT ?"
        )
        params.append(page_size)

        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(sql, tuple(params))
                rows = await cur.fetchall()
                row_dicts = [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.warning("query_activities failed: %s", e)
            return {"rows": [], "next_cursor": None, "page_size": page_size, "capped": capped}

        next_cursor = None
        if row_dicts and "id" in row_dicts[-1]:
            next_cursor = row_dicts[-1]["id"]
        return {
            "rows": row_dicts,
            "next_cursor": next_cursor,
            "page_size": page_size,
            "capped": capped,
        }

    # ====================================================================
    # v5.11.0 D2 — Optimizer shadow-accuracy sample DAOs.
    # ====================================================================
    #
    # Schema DDL is defined once in ``__init__`` above (per Tier-2-DB
    # Review C: tests must read schema FROM production, never hand-copy).
    # These DAOs are the single writer + reader for the table.

    async def log_shadow_samples_batch(
        self, samples: list[tuple],
    ) -> int:
        """v5.11.0 D2 — batched writer for shadow-accuracy sample rows.

        Signature: samples = list of (observed_at_iso, dimension,
        target_id, matched_bool). One ``_db()`` round-trip regardless
        of sample count — mirrors ``log_findings_batch`` discipline
        (never per-sample; that pattern caused the v5.0-v5.2 write-flood
        incident that rolled the optimizer back).

        Returns the count of rows written.
        """
        if not samples:
            return 0
        rows: list[tuple] = []
        for s in samples:
            if not isinstance(s, tuple) or len(s) != 4:
                continue
            observed_at, dim, target_id, matched = s
            if not isinstance(observed_at, str) or not isinstance(dim, str):
                continue
            rows.append((
                observed_at,
                dim,
                target_id if isinstance(target_id, str) else None,
                1 if matched else 0,
            ))
        if not rows:
            return 0
        try:
            async with self._db() as db:
                await db.executemany(
                    """INSERT INTO optimizer_shadow_samples
                       (observed_at, dimension, target_id, matched)
                       VALUES (?, ?, ?, ?)""",
                    rows,
                )
                await db.commit()
                return len(rows)
        except Exception as e:
            _LOGGER.warning(
                "log_shadow_samples_batch: insert failed: %s", e,
            )
            return 0

    async def get_recent_shadow_samples(
        self, window_days: int = 7, limit: int = 50000,
    ) -> list[dict]:
        """v5.11.0 D2 — read shadow-accuracy samples within window.

        Used by the OC ``async_setup`` to seed ``_shadow_accuracy_samples``
        so the rolling accuracy % survives HA restarts.
        """
        cutoff = (dt_util.utcnow() - timedelta(days=window_days)).isoformat()
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT observed_at, dimension, target_id, matched
                       FROM optimizer_shadow_samples
                       WHERE observed_at >= ?
                       ORDER BY observed_at DESC
                       LIMIT ?""",
                    (cutoff, limit),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.warning(
                "get_recent_shadow_samples failed: %s", e,
            )
            return []

    async def prune_optimizer_shadow_samples(
        self, window_days: int = 7, batch_size: int = 1000,
    ) -> int:
        """v5.11.0 D2 — prune shadow samples past retention window.

        Batched-DELETE shape mirrors ``prune_optimization_findings`` to
        dodge Bug Class #25 (write-queue stalls on large deletes).
        """
        cutoff = (dt_util.utcnow() - timedelta(days=window_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning(
                    "optimizer_shadow_samples prune hit max batch limit"
                )
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        """DELETE FROM optimizer_shadow_samples
                           WHERE rowid IN (
                             SELECT rowid FROM optimizer_shadow_samples
                             WHERE observed_at < ? LIMIT ?
                           )""",
                        (cutoff, batch_size),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error(
                    "Error pruning optimizer_shadow_samples: %s", e,
                )
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info(
                "Pruned %d optimizer_shadow_samples entries", total_deleted,
            )
        return total_deleted

    # ====================================================================
    # v4.7.36 Phase 3 — Optimization daily digest DAOs.
    # ====================================================================

    async def log_daily_digest(
        self,
        date: str,
        generated_at: str,
        findings_count: int,
        by_severity: dict,
        by_dimension: dict,
        summary: dict,
    ) -> int | None:
        """Single-path writer for an optimizer daily-digest row.

        Mirrors the ``log_finding`` shape: defensive None-rejection on the
        required columns, JSON-encoded payload columns, returns the row id
        on success or None on failure.
        """
        import json as _json
        if date is None or generated_at is None:
            _LOGGER.warning(
                "log_daily_digest: date/generated_at None; rejecting row "
                "(date=%s, generated_at=%s)",
                date, generated_at,
            )
            return None
        try:
            by_severity_json = (
                _json.dumps(by_severity, default=str)
                if by_severity is not None else None
            )
            by_dimension_json = (
                _json.dumps(by_dimension, default=str)
                if by_dimension is not None else None
            )
            summary_json = (
                _json.dumps(summary, default=str)
                if summary is not None else None
            )
        except (TypeError, ValueError) as enc_err:
            _LOGGER.warning(
                "log_daily_digest: payload JSON encode failed: %s", enc_err,
            )
            by_severity_json = by_dimension_json = summary_json = None
        try:
            async with self._db() as db:
                # B2 fix-up: upsert on ``date``. Morning + evening fires for
                # the same calendar day land in the same row (latest fire
                # wins on generated_at + payload columns).
                cursor = await db.execute(
                    """INSERT INTO optimization_daily_digest
                       (date, generated_at, findings_count,
                        by_severity_json, by_dimension_json, summary_json)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(date) DO UPDATE SET
                           generated_at = excluded.generated_at,
                           findings_count = excluded.findings_count,
                           by_severity_json = excluded.by_severity_json,
                           by_dimension_json = excluded.by_dimension_json,
                           summary_json = excluded.summary_json""",
                    (
                        date, generated_at, int(findings_count),
                        by_severity_json, by_dimension_json, summary_json,
                    ),
                )
                await db.commit()
                row_id = cursor.lastrowid
                return int(row_id) if row_id is not None else None
        except Exception as e:
            _LOGGER.warning("log_daily_digest: insert failed: %s", e)
            return None

    async def get_recent_daily_digests(
        self, limit: int = 14,
    ) -> list[dict]:
        """Read recent digest rows (most recent first)."""
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT id, date, generated_at, findings_count,
                              by_severity_json, by_dimension_json,
                              summary_json
                       FROM optimization_daily_digest
                       ORDER BY generated_at DESC
                       LIMIT ?""",
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.warning(
                "get_recent_daily_digests failed: %s", e,
            )
            return []

    async def prune_optimization_daily_digest(
        self, batch_size: int = 500,
    ) -> int:
        """Prune digest rows older than the retention window (90 days).

        Same batched-DELETE shape as ``prune_optimization_findings`` so a
        large backlog can't stall the write queue (Bug Class #25).
        """
        # Local import — module-level retention const may be edited via
        # const.py; reading lazily keeps the DAO test-friendly.
        from .const import OPTIMIZER_DIGEST_RETENTION_DAYS
        cutoff = (
            dt_util.utcnow() - timedelta(days=OPTIMIZER_DIGEST_RETENTION_DAYS)
        ).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning(
                    "optimization_daily_digest prune hit max batch limit",
                )
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM optimization_daily_digest WHERE rowid IN ("
                        "SELECT rowid FROM optimization_daily_digest "
                        "WHERE generated_at < ? LIMIT ?)",
                        (cutoff, batch_size),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error(
                    "Error pruning optimization_daily_digest: %s", e,
                )
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info(
                "Pruned %d optimization_daily_digest entries", total_deleted,
            )
        return total_deleted

    async def get_recent_activities(self, limit: int = 10) -> list[dict]:
        """Get most recent activity log entries."""
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT timestamp, coordinator, action, room, zone,
                              importance, description, entity_id
                       FROM ura_activity_log
                       ORDER BY timestamp DESC
                       LIMIT ?""",
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.error("Error fetching recent activities: %s", e)
            return []

    # ====================================================================
    # v4.0.0-B1: Bayesian beliefs persistence
    # ====================================================================

    async def save_bayesian_beliefs(self, beliefs: list[dict]) -> None:
        """Bulk upsert Bayesian belief rows.

        Each dict must have: person_id, time_bin, day_type, room_id,
        alpha, observation_count, updated_at.
        """
        if not beliefs:
            return
        try:
            async with self._db() as db:
                await db.executemany(
                    """INSERT OR REPLACE INTO bayesian_beliefs
                       (person_id, time_bin, day_type, room_id,
                        alpha, observation_count, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            b["person_id"],
                            b["time_bin"],
                            b["day_type"],
                            b["room_id"],
                            b["alpha"],
                            b["observation_count"],
                            b["updated_at"],
                        )
                        for b in beliefs
                    ],
                )
                await db.commit()
            _LOGGER.debug("Saved %d Bayesian belief rows", len(beliefs))
        except Exception as e:
            _LOGGER.error("Error saving Bayesian beliefs: %s", e)

    async def load_bayesian_beliefs(self) -> list[dict]:
        """Load all Bayesian belief rows from DB.

        Returns list of dicts with: person_id, time_bin, day_type,
        room_id, alpha, observation_count, updated_at.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT person_id, time_bin, day_type, room_id,
                              alpha, observation_count, updated_at
                       FROM bayesian_beliefs"""
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.error("Error loading Bayesian beliefs: %s", e)
            return []

    async def clear_bayesian_beliefs(self) -> None:
        """Delete all rows from bayesian_beliefs table."""
        try:
            async with self._db() as db:
                await db.execute("DELETE FROM bayesian_beliefs")
                await db.commit()
            _LOGGER.info("Cleared bayesian_beliefs table")
        except Exception as e:
            _LOGGER.error("Error clearing Bayesian beliefs: %s", e)

    async def get_room_transition_counts(
        self, days: int | None = None
    ) -> list[dict]:
        """Get individual room transition rows for Bayesian prior initialization.

        Returns all rows (not grouped) so the caller can apply its own
        time-bin and day-type logic.

        Each dict has: person_id, from_room, to_room, timestamp,
        duration_seconds, confidence.
        """
        try:
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                if days is not None:
                    cutoff = (
                        dt_util.utcnow() - timedelta(days=days)
                    ).isoformat()
                    cursor = await db.execute(
                        """SELECT person_id, from_room, to_room, timestamp,
                                  duration_seconds, confidence
                           FROM room_transitions
                           WHERE timestamp >= ?
                           ORDER BY timestamp""",
                        (cutoff,),
                    )
                else:
                    cursor = await db.execute(
                        """SELECT person_id, from_room, to_room, timestamp,
                                  duration_seconds, confidence
                           FROM room_transitions
                           ORDER BY timestamp"""
                    )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.error("Error fetching room transition counts: %s", e)
            return []

    # ====================================================================
    # v4.0.0-B2: Prediction results for accuracy tracking
    # ====================================================================

    async def save_prediction_result(
        self,
        room_id: str,
        time_bin: int,
        day_type: int,
        predicted_prob: float,
        actual_occupied: int,
        timestamp: str,
    ) -> None:
        """Insert a prediction result into the prediction_results table.

        Maps to existing schema:
            prediction_type = "bayesian_occupancy"
            predicted_value = str(predicted_prob)
            actual_value = str(actual_occupied)
            error_value = (predicted_prob - actual_occupied) ** 2
            confidence = learning status confidence (time_bin * 10 + day_type
                         encoded for context)
        """
        error = (predicted_prob - actual_occupied) ** 2
        context_code = float(time_bin * 10 + day_type)
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO prediction_results
                       (room_id, prediction_timestamp, prediction_type,
                        predicted_value, confidence, actual_value, error_value)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        room_id,
                        timestamp,
                        "bayesian_occupancy",
                        str(round(predicted_prob, 4)),
                        context_code,
                        str(actual_occupied),
                        round(error, 6),
                    ),
                )
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving prediction result: %s", e)

    async def save_next_room_prediction_result(
        self,
        person_id: str,
        predicted_room: str,
        predicted_value_json: str,
        confidence: float,
        actual_room: str,
        error_value: float,
        prediction_timestamp: str,
    ) -> None:
        """Insert a next-room prediction result into prediction_results.

        Mirrors save_prediction_result() structure but targets the new
        person_id column and uses prediction_type='next_room'. The
        predicted_value column holds JSON (top room + alternatives + source)
        so downstream accuracy sensors can reconstruct the full prediction
        without a separate table.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO prediction_results
                       (room_id, prediction_timestamp, prediction_type,
                        predicted_value, confidence, actual_value, error_value,
                        person_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        predicted_room,
                        prediction_timestamp,
                        "next_room",
                        predicted_value_json,
                        round(confidence, 6),
                        actual_room,
                        round(error_value, 6),
                        person_id,
                    ),
                )
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving next_room prediction result: %s", e)

    # -----------------------------------------------------------------------
    # v4.6.2 D4 — regime_cell_state DAOs
    # -----------------------------------------------------------------------

    async def get_regime_cell_state(
        self,
        person_id: str,
        time_bin: int,
        day_type: int,
    ) -> dict | None:
        """Return the current state row for a (person, time_bin, day_type) cell,
        or None if no row exists yet."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT unacknowledged_consecutive, last_evaluated_at,
                              last_magnitude_bucket
                       FROM regime_cell_state
                       WHERE person_id = ? AND time_bin = ? AND day_type = ?""",
                    (person_id, time_bin, day_type),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                return {
                    "unacknowledged_consecutive": row[0],
                    "last_evaluated_at": row[1],
                    "last_magnitude_bucket": row[2],
                }
        except Exception as e:
            _LOGGER.warning(
                "get_regime_cell_state failed (person=%s tb=%d dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
            return None

    async def upsert_regime_cell_state(
        self,
        person_id: str,
        time_bin: int,
        day_type: int,
        counter: int,
        magnitude_bucket: str | None,
    ) -> None:
        """Insert or replace the regime_cell_state row for a cell.

        Uses INSERT OR REPLACE so the caller does not need to distinguish
        first-write from update. The PRIMARY KEY constraint on
        (person_id, time_bin, day_type) ensures idempotency within a run.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO regime_cell_state
                       (person_id, time_bin, day_type,
                        unacknowledged_consecutive, last_evaluated_at,
                        last_magnitude_bucket)
                       VALUES (?, ?, ?, ?, datetime('now'), ?)""",
                    (person_id, time_bin, day_type, counter, magnitude_bucket),
                )
                await db.commit()
        except Exception as e:
            _LOGGER.warning(
                "upsert_regime_cell_state failed (person=%s tb=%d dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )

    async def save_anomaly_event(self, event) -> Optional[int]:
        """Single-path writer for AnomalyEvent rows (v4.6.1 D0 / review fix B2).

        Called by AnomalyDetector.store_event() AND by emitter sites that
        don't hold an AnomalyDetector reference (energy coord, binary sensor
        canaries, future B7 regime detector). Keeps the anomaly_log INSERT
        in exactly one place so v4.6.2's 12-touchpoint migration can route
        every emit through this DAO without copy-paste.

        Accepts a structurally-duck-typed AnomalyEvent; no runtime isinstance
        check to avoid the circular-import dance (database is lower in the
        import graph than domain_coordinators.anomaly_event).
        """
        import json as _json
        # v4.6.7: anomaly_log metric columns are now NULL-able. Pre-v4.6.7
        # the DAO synthesized 0.0/0 sentinels when the AnomalyEvent dataclass
        # field was None — caught by review B1 as silently masking the
        # difference between "baseline not yet learned" and "legitimate 0.0
        # observation." Now NULL passes through honestly.
        #
        # Resolution order per field (preserves v4.6.3 B1 fallback for
        # legacy callers that still bury fields in payload):
        #   1. Explicit AnomalyEvent dataclass field if non-None
        #   2. payload top-level key (legacy store_anomaly() shape — pre-v4.6.3)
        #   3. payload["extra"] key (intermediate migration shape)
        #   4. None (writes NULL to the column — no longer a sentinel 0.0)
        payload_dict = event.payload if isinstance(event.payload, dict) else {}
        _payload_extra = (
            payload_dict.get("extra", {})
            if isinstance(payload_dict.get("extra"), dict)
            else {}
        )

        def _resolve_metric(field_name: str):
            """Resolve a metric field with the v4.6.3 B1 priority order.

            Returns the dataclass-field value if non-None, else falls back
            to payload top-level or payload["extra"], else None (v4.6.7:
            no more 0.0 sentinel synthesis — schema relaxed to NULL-able).

            v4.6.7 review M1: removed dead `zero_default` parameter; the
            schema relaxation made the sentinel obsolete.
            """
            val = getattr(event, field_name, None)
            if val is not None:
                return val
            return (
                payload_dict.get(field_name)
                if payload_dict.get(field_name) is not None
                else _payload_extra.get(field_name)
            )

        observed_value = _resolve_metric("observed_value")
        expected_mean = _resolve_metric("expected_mean")
        expected_std = _resolve_metric("expected_std")
        z_score = _resolve_metric("z_score")
        sample_size = _resolve_metric("sample_size")
        house_state = payload_dict.get("house_state")
        # v4.7.12 D1: resolution order for the discriminator value —
        # prefer ``event.anomaly_type`` (new canonical field) and fall
        # back to ``event.event_class`` for any caller that hasn't been
        # migrated to the v4.7.12 dataclass shape. Coerce to a plain
        # string so aiosqlite binds it as TEXT (StrEnum members ARE
        # strings, but `str(...)` keeps the contract explicit). The same
        # value lands in BOTH columns during the dual-write window so
        # readers on either column see consistent data; v5.0 drops the
        # event_class column and this dual-write.
        _discriminator = getattr(event, "anomaly_type", None)
        if _discriminator is None:
            _discriminator = getattr(event, "event_class", None)
        if _discriminator is None:
            # v4.7.12 Reviewer C fix-up (C-M2): silent default to
            # "point_in_time" masks the C-M1 / M-B2 class of caller bug
            # (anomaly_type None at the emit boundary). Log a WARNING so
            # the fallback shows up in core logs instead of disappearing
            # into a NULL-shaped point_in_time row. Production
            # __post_init__ now raises TypeError on None for dataclass
            # callers, but the DAO still has to handle duck-typed events
            # constructed outside the dataclass.
            _LOGGER.warning(
                "save_anomaly_event: event has neither anomaly_type nor event_class; "
                "defaulting to 'point_in_time'. Caller bug — coordinator=%s type=%s",
                getattr(event, "coordinator", "?"),
                getattr(event, "type", "?"),
            )
            _discriminator_str = "point_in_time"
        else:
            _discriminator_str = str(_discriminator)
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """INSERT INTO anomaly_log
                       (timestamp, coordinator_id, scope,
                        metric_name, observed_value,
                        expected_mean, expected_std, z_score,
                        severity, sample_size, house_state,
                        context_json, resolved, resolution_notes,
                        event_class, recovery_at, correlation_id,
                        entity_id, room_id, person_id, anomaly_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.detected_at,
                        event.coordinator,
                        "",
                        event.type,
                        observed_value,
                        expected_mean,
                        expected_std,
                        z_score,
                        int(event.severity),
                        sample_size,
                        house_state,
                        _json.dumps(event.payload),
                        0, None,
                        _discriminator_str,  # event_class (dual-write alias)
                        event.recovery_at,
                        event.correlation_id,
                        event.entity_id,
                        event.room_id,
                        event.person_id,
                        _discriminator_str,  # anomaly_type (canonical)
                    ),
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            # v4.7.12 Reviewer B fix-up (M-B1): rename log key from
            # "anomaly_type" to "discriminator" since the getattr chain
            # falls back to event_class for legacy duck-typed events.
            # Neutral naming avoids miscategorizing legacy events in
            # operator log triage.
            _LOGGER.warning(
                "Error saving AnomalyEvent (coordinator=%s type=%s discriminator=%s): %s",
                getattr(event, "coordinator", "?"),
                getattr(event, "type", "?"),
                getattr(event, "anomaly_type", getattr(event, "event_class", "?")),
                e,
                exc_info=True,
            )
            return None

    # -----------------------------------------------------------------------
    # v4.6.2 D5 — anomaly_log acknowledge (bulk recovery_at UPDATE)
    # -----------------------------------------------------------------------

    async def acknowledge_all_routine_shifts(self) -> int:
        """Mark every unacknowledged routine-shift event as recovered.

        Sets recovery_at = datetime('now') on all anomaly_log rows where
        coordinator_id='bayesian', metric_name='bayesian.routine_shift',
        and recovery_at IS NULL. Called by AcknowledgeRoutineChangesButton.

        Returns the number of rows updated.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """UPDATE anomaly_log
                       SET recovery_at = datetime('now')
                       WHERE coordinator_id = 'bayesian'
                         AND metric_name = 'bayesian.routine_shift'
                         AND recovery_at IS NULL""",
                )
                await db.commit()
                rows_updated = cursor.rowcount if cursor.rowcount >= 0 else 0
                _LOGGER.info(
                    "acknowledge_all_routine_shifts: %d rows updated", rows_updated
                )
                return rows_updated
        except Exception as e:
            _LOGGER.warning(
                "acknowledge_all_routine_shifts failed: %s", e, exc_info=True
            )
            return 0

    # -----------------------------------------------------------------------
    # v4.6.2 D6 — regime event notification log DAOs
    # -----------------------------------------------------------------------

    async def get_regime_last_notified(
        self, person_id: str, time_bin: int, day_type: int
    ) -> str | None:
        """Return ISO timestamp of last notification for this cell, or None."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT last_notified_at
                       FROM regime_event_notification_log
                       WHERE person_id = ? AND time_bin = ? AND day_type = ?""",
                    (person_id, time_bin, day_type),
                )
                row = await cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            _LOGGER.warning(
                "get_regime_last_notified failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )
            return None

    async def upsert_regime_last_notified(
        self, person_id: str, time_bin: int, day_type: int, notified_at: str
    ) -> None:
        """Record or update the last notification timestamp for this cell."""
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO regime_event_notification_log
                       (person_id, time_bin, day_type, last_notified_at)
                       VALUES (?, ?, ?, ?)""",
                    (person_id, time_bin, day_type, notified_at),
                )
                await db.commit()
        except Exception as e:
            _LOGGER.warning(
                "upsert_regime_last_notified failed (%s, tb=%d, dt=%d): %s",
                person_id, time_bin, day_type, e,
                exc_info=True,
            )

    async def enqueue_regime_weekly_digest(
        self,
        anomaly_log_id: int,
        person_id: str,
        severity: int,
        queued_at: str,
    ) -> None:
        """Add one event to the weekly digest queue.

        Called when notification_mode='weekly_digest' and a regime-shift
        event arrives. The queue is flushed Sunday 09:00 by the NM handler.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO regime_weekly_digest_queue
                       (anomaly_log_id, queued_at, person_id, severity)
                       VALUES (?, ?, ?, ?)""",
                    (anomaly_log_id, queued_at, person_id, severity),
                )
                await db.commit()
        except Exception as e:
            _LOGGER.warning(
                "enqueue_regime_weekly_digest failed (anomaly_id=%s, person=%s): %s",
                anomaly_log_id, person_id, e,
                exc_info=True,
            )

    async def flush_regime_weekly_digest_queue(self) -> list[dict]:
        """Return and delete all rows in regime_weekly_digest_queue.

        Called once per Sunday 09:00 flush. Returns rows as dicts before
        deleting so the caller can compose the digest message.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """SELECT id, anomaly_log_id, queued_at, person_id, severity
                       FROM regime_weekly_digest_queue
                       ORDER BY queued_at ASC"""
                )
                rows = await cursor.fetchall()
                if rows:
                    await db.execute("DELETE FROM regime_weekly_digest_queue")
                    await db.commit()
                return [
                    {
                        "id": r[0],
                        "anomaly_log_id": r[1],
                        "queued_at": r[2],
                        "person_id": r[3],
                        "severity": r[4],
                    }
                    for r in rows
                ]
        except Exception as e:
            _LOGGER.warning(
                "flush_regime_weekly_digest_queue failed: %s", e, exc_info=True
            )
            return []

    async def save_prediction_results_batch(self, rows: list[tuple]) -> None:
        """Batch-insert prediction results in a single transaction.

        Each row is a tuple of:
            (room_id, timestamp, prediction_type, predicted_value,
             confidence, actual_value, error_value)
        """
        if not rows:
            return
        try:
            async with self._db() as db:
                await db.executemany(
                    """INSERT INTO prediction_results
                       (room_id, prediction_timestamp, prediction_type,
                        predicted_value, confidence, actual_value, error_value)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                await db.commit()
                _LOGGER.debug("Batch-saved %d prediction results", len(rows))
        except Exception as e:
            _LOGGER.error("Error batch-saving prediction results: %s", e)

    async def get_prediction_results(
        self,
        days: int = 7,
        prediction_type: str = "bayesian_occupancy",
    ) -> list[dict]:
        """Query prediction results for accuracy calculation.

        Returns list of dicts with: predicted_probability, actual_occupied,
        error_value, room_id, timestamp.
        """
        try:
            cutoff = (
                dt_util.utcnow() - timedelta(days=days)
            ).isoformat()
            async with self._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT room_id, prediction_timestamp, predicted_value,
                              actual_value, error_value, confidence
                       FROM prediction_results
                       WHERE prediction_type = ?
                         AND prediction_timestamp >= ?
                       ORDER BY prediction_timestamp""",
                    (prediction_type, cutoff),
                )
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    try:
                        result.append({
                            "room_id": r["room_id"],
                            "timestamp": r["prediction_timestamp"],
                            "predicted_probability": float(r["predicted_value"]),
                            "actual_occupied": int(r["actual_value"]),
                            "error_value": r["error_value"],
                        })
                    except (ValueError, TypeError):
                        continue  # Skip malformed rows
                return result
        except Exception as e:
            _LOGGER.error("Error querying prediction results: %s", e)
            return []

    async def prune_prediction_results(self, days: int = 30, batch_size: int = 1000) -> int:
        """Delete old prediction results in batches.

        v4.2.8: Batched to avoid holding write queue for minutes on large tables.
        Each batch acquires _db(), deletes ≤batch_size rows, commits, releases.
        """
        cutoff = (dt_util.utcnow() - timedelta(days=days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("Prediction prune hit max batch limit (500K rows)")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        """DELETE FROM prediction_results
                           WHERE rowid IN (
                               SELECT rowid FROM prediction_results
                               WHERE prediction_timestamp < ?
                                 AND prediction_type = 'bayesian_occupancy'
                               LIMIT ?
                           )""",
                        (cutoff, batch_size),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as e:
                _LOGGER.error("Error pruning prediction results (batch): %s", e)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info("Pruned %d prediction results older than %d days", total_deleted, days)
        return total_deleted

    # ================================================================
    # v4.1.0: Room Power Profiles (B4 Energy Integration)
    # ================================================================

    async def save_power_profiles(self, profiles: list[dict]) -> None:
        """Save room power profiles to DB (full replace)."""
        try:
            async with self._db() as db:
                await db.execute("DELETE FROM room_power_profiles")
                for row in profiles:
                    await db.execute(
                        """INSERT OR REPLACE INTO room_power_profiles
                           (room_id, time_bin, day_type, avg_watts, sample_count)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            row["room_id"],
                            row["time_bin"],
                            row["day_type"],
                            row["avg_watts"],
                            row["sample_count"],
                        ),
                    )
                await db.commit()
                _LOGGER.debug("Saved %d power profile rows", len(profiles))
        except Exception as e:
            _LOGGER.error("Error saving power profiles: %s", e)

    async def load_power_profiles(self) -> list[dict]:
        """Load room power profiles from DB."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT room_id, time_bin, day_type, avg_watts, sample_count
                       FROM room_power_profiles"""
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "room_id": r[0],
                        "time_bin": r[1],
                        "day_type": r[2],
                        "avg_watts": r[3],
                        "sample_count": r[4],
                    }
                    for r in rows
                ]
        except Exception as e:
            _LOGGER.error("Error loading power profiles: %s", e)
            return []

    async def get_occupancy_time_today(self, room_id: str) -> int:
        """Get total occupied seconds since midnight from occupancy_events.

        Sums duration of all 'occupied' events for the room today.
        Returns seconds.
        """
        try:
            midnight = dt_util.start_of_local_day().isoformat()
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT COALESCE(SUM(duration), 0)
                       FROM occupancy_events
                       WHERE room_id = ?
                         AND event_type = 'occupied'
                         AND timestamp >= ?""",
                    (room_id, midnight),
                )
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            _LOGGER.error("Error getting occupancy time today: %s", e)
            return 0

    async def get_uncomfortable_minutes_today(self, room_id: str) -> int:
        """Get minutes outside comfort zone while occupied today.

        Counts environmental_data rows where room was occupied AND
        (temperature < 68 OR temperature > 78 OR humidity > 60 OR humidity < 30).
        Each row represents a ~5 minute snapshot interval.
        Returns approximate minutes.
        """
        try:
            now = dt_util.utcnow()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT COUNT(*)
                       FROM environmental_data
                       WHERE room_id = ?
                         AND timestamp >= ?
                         AND occupied = 1
                         AND (temperature < 68 OR temperature > 78
                              OR humidity > 60 OR humidity < 30)""",
                    (room_id, midnight.isoformat()),
                )
                row = await cursor.fetchone()
                count = row[0] if row else 0
                # Each environmental_data row is ~5 minutes apart
                return count * 5
        except Exception as e:
            _LOGGER.error("Error getting uncomfortable minutes: %s", e)
            return 0

    # =========================================================================
    # v4.5.11: AC RAMP-DOWN STATE + EVENT LOG
    # =========================================================================
    # ac_reset_state: per-zone-per-day counters + in-flight nudge state.
    # Survives HA restart so the daily caps + min-interval gates can't be
    # bypassed by a restart loop. Min-interval gate intentionally queries
    # MAX(last_hard_reset_ts) without a date filter to protect against
    # the 23:59 -> 00:01 day-rollover edge.
    # =========================================================================

    @staticmethod
    def _today_key() -> str:
        """Return today's date in YYYY-MM-DD (HA local time)."""
        return dt_util.now().date().isoformat()

    async def get_ac_reset_state(self, zone_id: str, date: str | None = None) -> dict:
        """Return today's ac_reset_state row for a zone, or fresh defaults.

        Defaults represent a fresh-day row (no DB row yet) so callers can
        treat the result as authoritative without checking for None.
        """
        date_key = date or self._today_key()
        defaults = {
            "zone_id": zone_id,
            "date": date_key,
            "soft_nudge_count": 0,
            "hard_reset_count": 0,
            "last_soft_nudge_ts": None,
            "last_hard_reset_ts": None,
            "last_overshoot_ts": None,
            "in_flight_nudge_original_target": None,
            "in_flight_nudge_started_ts": None,
            "in_flight_nudge_duration_s": None,
            "lockout_flag": 0,
            # AC-RAMP-PIPELINE-HARDENING-1 D-PARTITION + D-SCORE
            "day_reset_count": 0,
            "night_reset_count": 0,
            "night_session_date": None,
            "in_flight_durable_started_ts": None,
            "in_flight_durable_event_id": None,
        }
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT * FROM ac_reset_state WHERE zone_id = ? AND date = ?",
                    (zone_id, date_key),
                )
                row = await cursor.fetchone()
                if row is None:
                    return defaults
                columns = [d[0] for d in cursor.description]
                return dict(zip(columns, row))
        except Exception as err:
            _LOGGER.warning(
                "ac_reset_state read failed for %s/%s: %s",
                zone_id, date_key, err,
            )
            return defaults

    async def save_ac_reset_state(self, state: dict) -> None:
        """Upsert a full ac_reset_state row.

        Caller is responsible for setting the date field (typically today).
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO ac_reset_state (
                        zone_id, date,
                        soft_nudge_count, hard_reset_count,
                        last_soft_nudge_ts, last_hard_reset_ts, last_overshoot_ts,
                        in_flight_nudge_original_target,
                        in_flight_nudge_started_ts,
                        in_flight_nudge_duration_s,
                        lockout_flag,
                        day_reset_count, night_reset_count,
                        night_session_date,
                        in_flight_durable_started_ts,
                        in_flight_durable_event_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        state["zone_id"],
                        state["date"],
                        int(state.get("soft_nudge_count", 0)),
                        int(state.get("hard_reset_count", 0)),
                        state.get("last_soft_nudge_ts"),
                        state.get("last_hard_reset_ts"),
                        state.get("last_overshoot_ts"),
                        state.get("in_flight_nudge_original_target"),
                        state.get("in_flight_nudge_started_ts"),
                        state.get("in_flight_nudge_duration_s"),
                        1 if state.get("lockout_flag") else 0,
                        # AC-RAMP-PIPELINE-HARDENING-1 D-PARTITION + D-SCORE:
                        # extend the INSERT-OR-REPLACE tuple. Missing this is
                        # the "highest-probability silent failure" per the
                        # superseded plan §12-5 — every save would reset the
                        # partition counters to 0 and the budget would never
                        # deny.
                        int(state.get("day_reset_count", 0)),
                        int(state.get("night_reset_count", 0)),
                        state.get("night_session_date"),
                        state.get("in_flight_durable_started_ts"),
                        state.get("in_flight_durable_event_id"),
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "ac_reset_state save failed for %s: %s",
                state.get("zone_id"), err,
            )

    async def get_global_last_hard_reset_ts(self, zone_id: str) -> str | None:
        """Return the most recent hard-reset ISO timestamp for a zone across
        all dates (no date filter).

        Critical for the min-interval gate: a daily-cap counter resets at
        midnight, but the compressor doesn't care what day it is. If the
        last hard reset was 7 minutes ago at 23:55, attempting another at
        00:02 would bypass the daily cap (new date row) — but the global
        MAX query catches it.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT MAX(last_hard_reset_ts) FROM ac_reset_state
                       WHERE zone_id = ?""",
                    (zone_id,),
                )
                row = await cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception as err:
            _LOGGER.warning(
                "ac_reset_state global last_hard_reset_ts read failed for %s: %s",
                zone_id, err,
            )
            return None

    async def set_ac_in_flight_nudge(
        self,
        zone_id: str,
        original_target: float,
        started_ts: str,
        duration_s: int,
    ) -> None:
        """Mark a nudge in-flight before issuing the setpoint change.

        MUST be called BEFORE the climate.set_temperature call so a crash
        between this write and the setpoint change leaves a benign DB
        record (restore-to-original = no-op) rather than orphan drift.
        """
        date_key = self._today_key()
        state = await self.get_ac_reset_state(zone_id, date_key)
        state["in_flight_nudge_original_target"] = float(original_target)
        state["in_flight_nudge_started_ts"] = started_ts
        state["in_flight_nudge_duration_s"] = int(duration_s)
        await self.save_ac_reset_state(state)

    async def clear_ac_in_flight_nudge(self, zone_id: str) -> None:
        """Clear in-flight nudge state after a successful restore.

        Looks up by zone_id alone (no date) because a nudge that started
        before midnight and restores after midnight needs both rows
        addressed.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """UPDATE ac_reset_state
                       SET in_flight_nudge_original_target = NULL,
                           in_flight_nudge_started_ts = NULL,
                           in_flight_nudge_duration_s = NULL
                       WHERE zone_id = ?
                         AND in_flight_nudge_original_target IS NOT NULL""",
                    (zone_id,),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "ac_reset_state clear in-flight failed for %s: %s",
                zone_id, err,
            )

    async def get_zones_with_in_flight_nudge(self) -> list[dict]:
        """Return all rows where a nudge is in-flight (any date).

        Called by OverrideArrester.async_startup_audit so a crash mid-nudge
        doesn't leave the thermostat at the nudged setpoint forever.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT zone_id, date, in_flight_nudge_original_target,
                              in_flight_nudge_started_ts, in_flight_nudge_duration_s
                       FROM ac_reset_state
                       WHERE in_flight_nudge_original_target IS NOT NULL""",
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "zone_id": r[0],
                        "date": r[1],
                        "original_target": r[2],
                        "started_ts": r[3],
                        "duration_s": r[4],
                    }
                    for r in rows
                ]
        except Exception as err:
            _LOGGER.warning("ac_reset_state in-flight scan failed: %s", err)
            return []

    async def set_ac_lockout(self, zone_id: str, locked: bool) -> None:
        """Set or clear the lockout flag for today's row."""
        date_key = self._today_key()
        state = await self.get_ac_reset_state(zone_id, date_key)
        state["lockout_flag"] = 1 if locked else 0
        await self.save_ac_reset_state(state)

    # A1 fix-up (2026-08-22): per-zone diagnostic queries feeding the
    # five A1 sensors. All are per-zone + windowed so the total scan is
    # bounded by the 7-day retention window (see cleanup_ac_ramp_events).
    async def get_gate4_divergence_rows_7d(
        self, zone_id: str, since_iso: str,
    ) -> list[tuple[str, str]]:
        """Return (timestamp, notes) for gate4_divergence_shadow rows
        for zone since ISO cutoff. Rows are emitted only on
        agree<->diverge transitions (edge-triggered), so this list
        alternates. Caller pairs consecutive rows to compute the
        time spent in the diverge state.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT timestamp, COALESCE(notes, '')
                       FROM ac_ramp_events
                       WHERE zone_id = ?
                         AND event_type = 'gate4_divergence_shadow'
                         AND timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (zone_id, since_iso),
                )
                rows = await cursor.fetchall()
                return [(r[0], r[1]) for r in rows]
        except Exception as err:
            _LOGGER.debug("A1 gate4 divergence query failed for %s: %s",
                          zone_id, err)
            return []

    async def get_last_reset_outcome_for_zone(
        self, zone_id: str,
    ) -> str | None:
        """Return the most recent non-NULL reset_outcome for zone."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT reset_outcome
                       FROM ac_ramp_events
                       WHERE zone_id = ?
                         AND reset_outcome IS NOT NULL
                       ORDER BY event_id DESC
                       LIMIT 1""",
                    (zone_id,),
                )
                row = await cursor.fetchone()
                return row[0] if row else None
        except Exception as err:
            _LOGGER.debug("A1 last outcome query failed for %s: %s",
                          zone_id, err)
            return None

    async def get_durability_rate_for_zone(
        self, zone_id: str, since_iso: str,
    ) -> tuple[int, int, int, int]:
        """Return (full_ok, full_total, trunc_ok, trunc_total) counts
        of nudge_evaluated rows in the window.

        Split by the explicit `truncated` column (F5 fix-up ruling,
        2026-08-22): rows with `truncated=0` count toward full;
        `truncated=1` count toward truncated; `truncated IS NULL`
        (pre-migration rows) are EXCLUDED from both rates per the
        operator ruling — "an honest UNBOUND is more useful than a
        green count".

        `durable IS NULL` rows also excluded (unknown breaks the
        streak). Not a hot query — bounded by retention.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT durable, truncated
                       FROM ac_ramp_events
                       WHERE zone_id = ?
                         AND event_type = 'nudge_evaluated'
                         AND durable IS NOT NULL
                         AND truncated IS NOT NULL
                         AND timestamp >= ?""",
                    (zone_id, since_iso),
                )
                rows = await cursor.fetchall()
        except Exception as err:
            _LOGGER.debug("A1 durability rate query failed for %s: %s",
                          zone_id, err)
            return (0, 0, 0, 0)
        full_ok = full_total = trunc_ok = trunc_total = 0
        for durable_val, truncated_val in rows:
            if truncated_val == 1:
                trunc_total += 1
                if durable_val == 1:
                    trunc_ok += 1
            else:
                full_total += 1
                if durable_val == 1:
                    full_ok += 1
        return (full_ok, full_total, trunc_ok, trunc_total)

    # A3 fix-up (2026-08-22): bounded restart resumption of
    # in-flight durability windows.
    async def get_in_flight_durable_rows(self) -> list[dict]:
        """Return at most ONE (zone_id, event_id, started_ts) per zone
        for zones with an armed durability window on any date row.

        Idempotent: multiple boots see the same rows until a boot
        clears the marker via `clear_in_flight_durable`.

        The DAO filters on `in_flight_durable_started_ts IS NOT NULL`
        which returns only the small set of currently-armed rows —
        not the full ac_reset_state table. Per operator A3 bound
        'no table scan': in practice ac_reset_state has one row per
        (zone_id, date), and the WHERE clause degenerates to a small
        subset filter regardless of table size. If future scale makes
        this hot, add `CREATE INDEX ... WHERE in_flight_durable_started_ts
        IS NOT NULL` — deferred as premature.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT zone_id, date, in_flight_durable_started_ts,
                              in_flight_durable_event_id
                       FROM ac_reset_state
                       WHERE in_flight_durable_started_ts IS NOT NULL""",
                )
                rows = await cursor.fetchall()
        except Exception as err:
            _LOGGER.warning("in_flight_durable scan failed: %s", err)
            return []
        # Enforce <=1 row per zone (operator A3 bound). Under normal
        # arming the invariant already holds because arming clears any
        # prior marker on the same zone (see `_schedule_write_durable`
        # + `clear_in_flight_durable_for_zone`). Defensive: prefer the
        # most recent started_ts if a legacy DB happens to violate it.
        best: dict[str, dict] = {}
        for r in rows:
            zid = r[0]
            entry = {
                "zone_id": zid,
                "date": r[1],
                "started_ts": r[2],
                "event_id": r[3],
            }
            prev = best.get(zid)
            if prev is None or str(entry["started_ts"] or "") > str(
                prev["started_ts"] or ""
            ):
                best[zid] = entry
        return list(best.values())

    async def clear_in_flight_durable_for_zone(self, zone_id: str) -> None:
        """Clear the in-flight durable marker on EVERY row for this
        zone. Targeted 2-column UPDATE; scope 'every row' guards the
        <=1-row-per-zone invariant across day-rollover edges.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """UPDATE ac_reset_state
                       SET in_flight_durable_started_ts = NULL,
                           in_flight_durable_event_id = NULL
                       WHERE zone_id = ?
                         AND in_flight_durable_started_ts IS NOT NULL""",
                    (zone_id,),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "clear_in_flight_durable failed for %s: %s", zone_id, err,
            )

    async def set_in_flight_durable(
        self, zone_id: str, event_id: int, started_ts: str,
    ) -> None:
        """Atomically arm the in-flight durable marker for THIS zone
        on today's row while clearing any marker on OTHER date rows
        for the same zone (guarantees <=1 armed row per zone even
        across a day rollover mid-window)."""
        date_key = self._today_key()
        try:
            async with self._db() as db:
                # First: clear any previous marker on this zone (all
                # date rows) so arming a new window can't leave two
                # rows armed.
                await db.execute(
                    """UPDATE ac_reset_state
                       SET in_flight_durable_started_ts = NULL,
                           in_flight_durable_event_id = NULL
                       WHERE zone_id = ?
                         AND in_flight_durable_started_ts IS NOT NULL""",
                    (zone_id,),
                )
                # Then set on today's row (which may need creating).
                await db.execute(
                    """INSERT INTO ac_reset_state (
                        zone_id, date,
                        soft_nudge_count, hard_reset_count,
                        last_soft_nudge_ts, last_hard_reset_ts,
                        last_overshoot_ts,
                        in_flight_nudge_original_target,
                        in_flight_nudge_started_ts,
                        in_flight_nudge_duration_s,
                        lockout_flag,
                        day_reset_count, night_reset_count,
                        night_session_date,
                        in_flight_durable_started_ts,
                        in_flight_durable_event_id
                    ) VALUES (?, ?, 0, 0, NULL, NULL, NULL,
                              NULL, NULL, NULL,
                              0, 0, 0, NULL, ?, ?)
                    ON CONFLICT(zone_id, date) DO UPDATE SET
                        in_flight_durable_started_ts = excluded.in_flight_durable_started_ts,
                        in_flight_durable_event_id = excluded.in_flight_durable_event_id""",
                    (
                        zone_id, date_key,
                        started_ts, int(event_id),
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "set_in_flight_durable failed for %s: %s", zone_id, err,
            )

    # AC-RAMP-PIPELINE-HARDENING-1 fix-up F1: night bucket storage.
    # The night counter lives in the row keyed by (zone_id, session_date)
    # so a night session that crosses midnight (e.g. 22:00 D → 06:00 D+1)
    # addresses the SAME row on both sides. When session_date == today,
    # the night counter naturally co-exists with the day columns in one
    # row; when session_date < today (post-midnight), the night row is
    # a distinct row and this DAO writes ONLY its night columns so it
    # cannot clobber the day row's separate state.
    async def update_ac_night_counter(
        self, zone_id: str, session_date: str, night_reset_count: int,
    ) -> None:
        """Upsert the (zone_id, session_date) row's night counter fields
        WITHOUT touching any day/session-shared columns on that row.

        Uses INSERT + ON CONFLICT UPDATE so an existing row's other
        columns (soft_nudge_count, day_reset_count, hard_reset_count,
        last_hard_reset_ts, lockout_flag, in-flight nudge state) are
        preserved. On INSERT for a new session_date row, all other
        columns take their schema defaults (all 0 / NULL) — correct,
        because that row exists solely to carry night_reset_count for
        the crossed-midnight session.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO ac_reset_state (
                        zone_id, date,
                        soft_nudge_count, hard_reset_count,
                        last_soft_nudge_ts, last_hard_reset_ts,
                        last_overshoot_ts,
                        in_flight_nudge_original_target,
                        in_flight_nudge_started_ts,
                        in_flight_nudge_duration_s,
                        lockout_flag,
                        day_reset_count, night_reset_count,
                        night_session_date,
                        in_flight_durable_started_ts
                    ) VALUES (?, ?, 0, 0, NULL, NULL, NULL,
                              NULL, NULL, NULL,
                              0, 0, ?, ?, NULL)
                    ON CONFLICT(zone_id, date) DO UPDATE SET
                        night_reset_count = excluded.night_reset_count,
                        night_session_date = excluded.night_session_date""",
                    (
                        zone_id, session_date,
                        int(night_reset_count),
                        session_date,
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "ac_reset_state night-counter upsert failed for %s/%s: %s",
                zone_id, session_date, err,
            )

    async def clear_ac_zone_today(self, zone_id: str) -> None:
        """Reset today's counters + lockout for a zone (clear_lockout button)."""
        date_key = self._today_key()
        try:
            async with self._db() as db:
                await db.execute(
                    """UPDATE ac_reset_state
                       SET soft_nudge_count = 0,
                           hard_reset_count = 0,
                           lockout_flag = 0
                       WHERE zone_id = ? AND date = ?""",
                    (zone_id, date_key),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "ac_reset_state clear-zone-today failed for %s: %s",
                zone_id, err,
            )

    async def log_ac_ramp_event(
        self,
        zone_id: str,
        event_type: str,
        triggered_by: str = "auto",
        current_temp: float | None = None,
        target_high: float | None = None,
        kwh_rate_before: float | None = None,
        kwh_rate_after: float | None = None,
        action_taken: str | None = None,
        soft_nudge_count_today: int | None = None,
        hard_reset_count_today: int | None = None,
        lockout_triggered: bool = False,
        notes: str | None = None,
        effective: bool | None = None,
        preset_before: str | None = None,
        preset_after: str | None = None,
        mode_before: str | None = None,
        mode_after: str | None = None,
        restore_ok: bool | None = None,
        restore_ok_immediate: bool | None = None,
        excursion_id: str | None = None,
    ) -> int | None:
        """Append an event row to the ramp-down log.

        AC-RAMP-PIPELINE-HARDENING-1: returns ``cursor.lastrowid`` (the
        new event_id) so delayed-write callers (D-SCORE `_write_durable`,
        D5 `_verify_restore` back-fill, D6 `_write_reset_outcome`) can
        UPDATE precisely the row they wrote — no "UPDATE latest row"
        race. Returns ``None`` on write failure (existing callers all
        discard the return value; new callers guard on None).

        v4.7.17.1: `effective` column added — set by _evaluate_nudge_outcome:
            True  -> compressor released (counts toward kWh-avoided + NOT FP)
            False -> compressor did NOT release / no samples (counts as FP)
            None  -> inconclusive (kwh_rate_before below floor, excluded
                     from FP stats entirely)
        For non-evaluation event_types pass None.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    """INSERT INTO ac_ramp_events (
                        zone_id, timestamp, event_type, triggered_by,
                        current_temp, target_high,
                        kwh_rate_before, kwh_rate_after, action_taken,
                        soft_nudge_count_today, hard_reset_count_today,
                        lockout_triggered, notes, effective,
                        preset_before, preset_after,
                        mode_before, mode_after, restore_ok,
                        restore_ok_immediate, excursion_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        zone_id,
                        dt_util.now().isoformat(),
                        event_type,
                        triggered_by,
                        current_temp,
                        target_high,
                        kwh_rate_before,
                        kwh_rate_after,
                        action_taken,
                        soft_nudge_count_today,
                        hard_reset_count_today,
                        1 if lockout_triggered else 0,
                        notes,
                        # SQLite has no native BOOLEAN; INTEGER 0/1 + NULL.
                        None if effective is None else (1 if effective else 0),
                        preset_before,
                        preset_after,
                        mode_before,
                        mode_after,
                        None if restore_ok is None else (1 if restore_ok else 0),
                        None if restore_ok_immediate is None else (1 if restore_ok_immediate else 0),
                        excursion_id,
                    ),
                )
                await db.commit()
                try:
                    return int(cursor.lastrowid) if cursor.lastrowid else None
                except Exception:  # noqa: BLE001 — defensive
                    return None
        except Exception as err:
            _LOGGER.warning(
                "ac_ramp_events log failed for %s/%s: %s",
                zone_id, event_type, err,
            )
            return None

    # AC-RAMP-PIPELINE-HARDENING-1 (B-M1): update_ac_ramp_event_fields
    # DAO. Back-fills columns on a specific event_id row from delayed
    # callbacks (D-SCORE, D5 restore_ok, D6 reset_outcome). Whitelist-
    # driven so callers can't scribble arbitrary columns.
    _AC_RAMP_EVENT_UPDATABLE_FIELDS: tuple = (
        "durable",
        "durable_minutes",
        "reset_outcome",
        "restore_ok",
        "preset_after",
        "mode_after",
        "current_temp",
        "kwh_rate_settle",
        # F13 fix-up: settle-time temp goes here, NOT current_temp.
        "current_temp_settle",
        # F9 fix-up.
        "preset_restore_ok",
        # F5 ruling (2026-08-22 fix-up): the truncated flag is
        # written by _write_durable via the SAME UPDATE as durable.
        "truncated",
    )

    async def update_ac_ramp_event_fields(
        self, event_id: int, **fields,
    ) -> None:
        """UPDATE named columns on the ac_ramp_events row with matching
        ``event_id``. Silent no-op if the row is gone (retention) or the
        DAO can't write.

        Values are passed through as-is except for the bool ``restore_ok``
        (SQLite has no native BOOL — pack 0/1/None to match the INSERT
        path). Callers own type discipline for INTEGER/TEXT columns.
        """
        if event_id is None:
            return
        clean: dict = {}
        for k, v in fields.items():
            if k not in self._AC_RAMP_EVENT_UPDATABLE_FIELDS:
                _LOGGER.debug(
                    "update_ac_ramp_event_fields: rejecting unknown field %s",
                    k,
                )
                continue
            if k in ("restore_ok", "preset_restore_ok"):
                clean[k] = None if v is None else (1 if v else 0)
            else:
                clean[k] = v
        if not clean:
            return
        set_clause = ", ".join(f"{k} = ?" for k in clean)
        params = list(clean.values()) + [int(event_id)]
        try:
            async with self._db() as db:
                await db.execute(
                    f"UPDATE ac_ramp_events SET {set_clause} "
                    f"WHERE event_id = ?",
                    tuple(params),
                )
                await db.commit()
        except Exception as err:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "update_ac_ramp_event_fields failed for %s (%s): %s",
                event_id, list(clean.keys()), err,
            )

    async def update_ac_ramp_restore_settled(
        self,
        zone_id: str,
        preset_settled: str | None,
        mode_settled: str | None,
        restore_ok: bool | None,
        settled_reason: str | None = None,
    ) -> None:
        """Write the SETTLED restore verdict onto the most-recent
        nudge_restored row for ``zone_id``.

        HVAC-GOVERNED-EXCURSION-1 D1. Called by a scheduled callback
        ``AC_NUDGE_RESTORE_SETTLE_DELAY_S`` after ``_restore_after_nudge``
        completes, so a late cloud-poll setpoint clobber (the defect this
        cycle exists to measure) is captured in ``restore_ok`` — the
        immediate verdict lives in ``restore_ok_immediate``.

        Degrades to a silent no-op if the row no longer exists (retention
        cleanup, DB reset). Only updates rows where ``restore_ok IS NULL``
        so a delayed callback cannot overwrite a settled row from a
        subsequent nudge cycle on the same zone.
        """
        try:
            async with self._db() as db:
                await db.execute(
                    # F19 fix-up: settled values write to distinct
                    # columns so the immediate sample survives.
                    # F8 fix-up: settled_reason threads through so an
                    # intentionally-skipped sample explains itself.
                    """UPDATE ac_ramp_events
                       SET preset_settled = ?,
                           mode_settled = ?,
                           restore_ok = ?,
                           settled_reason = ?
                       WHERE event_id = (
                           SELECT event_id FROM ac_ramp_events
                           WHERE zone_id = ?
                             AND event_type = 'nudge_restored'
                             AND restore_ok IS NULL
                           ORDER BY event_id DESC
                           LIMIT 1
                       )""",
                    (
                        preset_settled,
                        mode_settled,
                        None if restore_ok is None else (1 if restore_ok else 0),
                        settled_reason,
                        zone_id,
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "ac_ramp_events settled-update failed for %s: %s",
                zone_id, err,
            )

    # =========================================================================
    # HVAC-GOVERNED-EXCURSION-1 D2 — hvac_excursion_state + _events DAOs.
    # See PLANNING_hvac_governed_excursion.md §4.4 (lease) + §4.5 (schema).
    # =========================================================================

    async def save_excursion_row(self, row: dict) -> None:
        """Upsert a hvac_excursion_state row. `zone_id` is the PK.

        Called by ``hvac_excursion.begin_excursion`` BEFORE the service
        call (R1 ordering — a crash between this write and the wire call
        leaves a benign row the boot audit can adjudicate).
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO hvac_excursion_state (
                        zone_id, excursion_id, kind, started_ts, duration_s,
                        pre_preset, pre_target_low, pre_target_high,
                        excursion_target_low, excursion_target_high,
                        intended_mode, caller_site
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["zone_id"],
                        row["excursion_id"],
                        row["kind"],
                        row["started_ts"],
                        row.get("duration_s"),
                        row.get("pre_preset"),
                        row.get("pre_target_low"),
                        row.get("pre_target_high"),
                        row.get("excursion_target_low"),
                        row.get("excursion_target_high"),
                        row["intended_mode"],
                        row["caller_site"],
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "hvac_excursion_state save failed for %s: %s",
                row.get("zone_id"), err,
            )

    async def clear_excursion_row(self, zone_id: str) -> None:
        """Delete the excursion state row for zone_id (called by return)."""
        try:
            async with self._db() as db:
                await db.execute(
                    "DELETE FROM hvac_excursion_state WHERE zone_id = ?",
                    (zone_id,),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "hvac_excursion_state clear failed for %s: %s",
                zone_id, err,
            )

    async def get_all_excursion_rows(self) -> list[dict]:
        """Return every persisted excursion state row.

        Called by ``async_startup_excursion_audit`` to rehydrate leases
        and adjudicate rows left over from a crash / restart.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT zone_id, excursion_id, kind, started_ts,
                              duration_s, pre_preset, pre_target_low,
                              pre_target_high, excursion_target_low,
                              excursion_target_high, intended_mode, caller_site
                       FROM hvac_excursion_state"""
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "zone_id": r[0], "excursion_id": r[1], "kind": r[2],
                        "started_ts": r[3], "duration_s": r[4],
                        "pre_preset": r[5], "pre_target_low": r[6],
                        "pre_target_high": r[7],
                        "excursion_target_low": r[8],
                        "excursion_target_high": r[9],
                        "intended_mode": r[10], "caller_site": r[11],
                    }
                    for r in rows
                ]
        except Exception as err:
            _LOGGER.warning("hvac_excursion_state scan failed: %s", err)
            return []

    async def log_excursion_event(
        self,
        *,
        excursion_id: str,
        zone_id: str,
        kind: str,
        started_ts: str,
        ended_ts: str | None = None,
        trigger: str | None = None,
        trigger_detail: str | None = None,
        site: str | None = None,
        duration_actual_s: int | None = None,
        pre_preset: str | None = None,
        pre_target_low: float | None = None,
        pre_target_high: float | None = None,
        preset_after: str | None = None,
        target_low_after: float | None = None,
        target_high_after: float | None = None,
        mode_before: str | None = None,
        mode_after: str | None = None,
        restore_ok: bool | None = None,
        restore_ok_immediate: bool | None = None,
    ) -> None:
        """Append a row to hvac_excursion_events (non-nudge home)."""
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT INTO hvac_excursion_events (
                        excursion_id, zone_id, kind, started_ts, ended_ts,
                        trigger, trigger_detail, site, duration_actual_s,
                        pre_preset, pre_target_low, pre_target_high,
                        preset_after, target_low_after, target_high_after,
                        mode_before, mode_after, restore_ok,
                        restore_ok_immediate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        excursion_id, zone_id, kind, started_ts, ended_ts,
                        trigger, trigger_detail, site, duration_actual_s,
                        pre_preset, pre_target_low, pre_target_high,
                        preset_after, target_low_after, target_high_after,
                        mode_before, mode_after,
                        None if restore_ok is None else (1 if restore_ok else 0),
                        None if restore_ok_immediate is None
                        else (1 if restore_ok_immediate else 0),
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "hvac_excursion_events log failed for %s/%s: %s",
                zone_id, kind, err,
            )

    async def get_ac_ramp_events_recent(
        self, days: int = 7, zone_id: str | None = None,
    ) -> list[dict]:
        """Return recent ramp-down events, newest first.

        Used by the diagnostic-dump button (D10) and by impact sensors (D8).
        """
        cutoff = (dt_util.now() - timedelta(days=days)).isoformat()
        try:
            async with self._db_read() as db:
                if zone_id:
                    cursor = await db.execute(
                        """SELECT * FROM ac_ramp_events
                           WHERE timestamp >= ? AND zone_id = ?
                           ORDER BY timestamp DESC""",
                        (cutoff, zone_id),
                    )
                else:
                    cursor = await db.execute(
                        """SELECT * FROM ac_ramp_events
                           WHERE timestamp >= ?
                           ORDER BY timestamp DESC""",
                        (cutoff,),
                    )
                rows = await cursor.fetchall()
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, r)) for r in rows]
        except Exception as err:
            _LOGGER.warning("ac_ramp_events recent read failed: %s", err)
            return []

    async def get_ac_ramp_kwh_avoided(
        self, days: int | None = None, since: "datetime | None" = None,
    ) -> tuple[float, int, int]:
        """Compute (kwh_avoided, total_nudge_evals, false_positive_count).

        Aggregates from `nudge_evaluated` events. Manual-triggered events
        excluded from false-positive math (R6) since user testing isn't
        a real false positive.

        kwh_avoided per event = max(0, before - after) * (capped projected
        remaining minutes / 60). Caller passes the projected-minutes via
        the action_taken JSON-ish notes field — for v4.5.11 we store a
        pre-computed kwh_avoided in `notes` column to keep the math close
        to where the data is fresh.

        Returns:
          (sum_kwh_avoided, count_evaluated, count_false_positive)
        """
        where_clauses = ["event_type = 'nudge_evaluated'", "triggered_by != 'manual'"]
        params: list = []
        # `since` (a concrete datetime, e.g. local-midnight) wins over the
        # rolling `days` window when both are supplied. This is how the
        # "today" cache anchors to local midnight so the sensor resets
        # cleanly at 00:00 local instead of drifting as a 24h-rolling sum
        # (which caused non-monotonic decreases as events aged out — v5.24+
        # fix; see HVACACKwhAvoidedTodaySensor docstring).
        if since is not None:
            where_clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        elif days is not None:
            where_clauses.append("timestamp >= ?")
            params.append((dt_util.now() - timedelta(days=days)).isoformat())
        where_sql = " AND ".join(where_clauses)
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT kwh_rate_before, kwh_rate_after, notes, effective
                        FROM ac_ramp_events
                        WHERE {where_sql}""",
                    params,
                )
                rows = await cursor.fetchall()
        except Exception as err:
            _LOGGER.warning("ac_ramp_events aggregate read failed: %s", err)
            return (0.0, 0, 0)

        # v4.7.17.1: FP rate is now derived from the `effective` column
        # written by the new _evaluate_nudge_outcome rule. Rows with
        # `effective = NULL` (pre-deploy events OR new "inconclusive"
        # classifications) are EXCLUDED from BOTH the FP count AND the
        # `count_evaluated` denominator — they shouldn't move the metric
        # in either direction. Rows with effective = 0/1 count normally.
        # kwh_avoided still comes from the `notes` field's parsed value
        # for evaluated rows where we have one.
        kwh_total = 0.0
        false_pos = 0
        counted = 0
        for before, after, notes, effective in rows:
            # v4.7.17.1: skip rows that the new rule explicitly excluded
            # OR pre-deploy rows that never had the column populated.
            if effective is None:
                continue
            counted += 1
            if effective == 0:
                false_pos += 1
                continue
            # effective == 1: parse kwh_avoided from notes; fall back to
            # flat projection from before/after diff when present.
            kwh_event = None
            if notes:
                try:
                    # notes format: "kwh_avoided=0.42;post_min=...;..."
                    for part in notes.split(";"):
                        k, _, v = part.partition("=")
                        if k.strip() == "kwh_avoided":
                            kwh_event = float(v)
                            break
                except (ValueError, AttributeError):
                    kwh_event = None
            if kwh_event is None and before is not None and after is not None:
                kwh_event = max(0.0, (before - after)) * (10.0 / 60.0)
            if kwh_event is not None:
                kwh_total += kwh_event
        return (kwh_total, counted, false_pos)

    async def get_ac_ramp_savings(
        self, days: int | None = None, since: "datetime | None" = None,
    ) -> tuple[float, int]:
        """Compute (sum_usd_savings, count_events_with_captured_rate).

        Standalone AC-ramp $ savings estimate — the D6 deferred deliverable
        of the #7 (v5.32.0) cycle. Each `nudge_evaluated` row that (a) is
        marked `effective=1` AND (b) carries a captured `rate=<float>` in
        its `notes` payload contributes `kwh_event × rate_event` to the sum.

        **Forward-only:** rows logged BEFORE the rate-capture change (or with
        a missing / malformed / non-positive rate) contribute kWh to the kWh
        family but $0 here — back-filling a current rate would guess.

        **NOT `kWh_family × rate` exactly.** Savings is the subset of
        effective rows that carry a valid captured `rate`; pre-deploy rows
        and rows whose rate capture failed contribute kWh (via
        `get_ac_ramp_kwh_avoided`) but $0 (via this method). The two families
        converge only once every row in the window carries a rate.

        Rough estimate (inherits the `rough_estimate / not billing-grade`
        caveat as the kWh family). MUST NOT be summed into the EC
        `energy_savings_total_*` family (double-counts vs peak-avoidance /
        arbitrage).

        Uses the same `since`/`days` windowing + `effective`/`triggered_by`
        exclusions as `get_ac_ramp_kwh_avoided`.
        """
        where_clauses = ["event_type = 'nudge_evaluated'", "triggered_by != 'manual'"]
        params: list = []
        if since is not None:
            where_clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        elif days is not None:
            where_clauses.append("timestamp >= ?")
            params.append((dt_util.now() - timedelta(days=days)).isoformat())
        where_sql = " AND ".join(where_clauses)
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT notes, effective
                        FROM ac_ramp_events
                        WHERE {where_sql}""",
                    params,
                )
                rows = await cursor.fetchall()
        except Exception as err:
            _LOGGER.warning("ac_ramp_events savings read failed: %s", err)
            return (0.0, 0)

        return _sum_savings_from_rows(rows)

    async def cleanup_ac_ramp_events(
        self, retention_days: int = 30, batch_size: int = 1000,
    ) -> int:
        """Prune ramp-down events older than retention_days.

        Called once per day on the first detection cycle of a new date
        (no separate cron — piggybacks on the rollover read of
        ac_reset_state). Bounded growth, no unbounded log file.

        Tier 2 review fix: cutoff uses dt_util.now() to match the
        timezone of timestamps written by log_ac_ramp_event (also
        dt_util.now()). Mixing dt_util.utcnow() vs dt_util.now() across
        the writer/cleaner would cause edge-rows to be wrongly classified
        — see QUALITY_CONTEXT.md Bug Class #11.
        """
        cutoff = (dt_util.now() - timedelta(days=retention_days)).isoformat()
        total_deleted = 0
        _batch_count = 0
        while True:
            _batch_count += 1
            if _batch_count > 500:
                _LOGGER.warning("ac_ramp_events cleanup hit max batch limit")
                break
            try:
                async with self._db() as db:
                    cursor = await db.execute(
                        "DELETE FROM ac_ramp_events WHERE rowid IN ("
                        "SELECT rowid FROM ac_ramp_events WHERE timestamp < ? LIMIT ?)",
                        (cutoff, batch_size),
                    )
                    await db.commit()
                    deleted = cursor.rowcount
                    total_deleted += deleted
            except Exception as err:
                _LOGGER.error("ac_ramp_events cleanup failed: %s", err)
                break
            if deleted < batch_size:
                break
            await asyncio.sleep(0.1)
        if total_deleted > 0:
            _LOGGER.info(
                "ac_ramp_events cleanup: deleted %d rows older than %d days",
                total_deleted, retention_days,
            )
        return total_deleted

    # =========================================================================
    # v4.7.8: Egress Window HVAC Pause persistence
    # -------------------------------------------------------------------------
    # One row per canonical HVAC zone tracking the egress-pause state machine.
    # Mirrors ac_reset_state DAO shape but uses zone_id (alone) as PK because
    # egress pause is a per-zone lifecycle, not a daily-bucketed counter.
    # All five DAOs guard reads + writes with try/except so transient SQLite
    # failures degrade gracefully (sensor sees stale state instead of crash).
    # =========================================================================

    async def get_egress_state(self, zone_id: str) -> dict | None:
        """Return egress_state row for a zone, or None if no row exists."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT * FROM egress_state WHERE zone_id = ?",
                    (zone_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                columns = [d[0] for d in cursor.description]
                return dict(zip(columns, row))
        except Exception as err:
            _LOGGER.warning(
                "egress_state read failed for %s: %s",
                zone_id, err,
            )
            return None

    async def save_egress_state(self, state: dict) -> None:
        """Upsert an egress_state row.

        All timestamp fields are stored as ISO strings (callers must format
        tz-aware datetimes via .isoformat() — see Bug Class #11).
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO egress_state (
                        zone_id, state,
                        first_open_at, first_closed_at, paused_at,
                        saved_hvac_mode, saved_preset_mode,
                        triggered_by_room, thermostat_entity,
                        cooldown_expires_at, last_update_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        state["zone_id"],
                        state["state"],
                        state.get("first_open_at"),
                        state.get("first_closed_at"),
                        state.get("paused_at"),
                        state.get("saved_hvac_mode"),
                        state.get("saved_preset_mode"),
                        state.get("triggered_by_room"),
                        state.get("thermostat_entity"),
                        state.get("cooldown_expires_at"),
                        state.get("last_update_ts") or dt_util.now().isoformat(),
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "egress_state save failed for %s: %s",
                state.get("zone_id"), err,
            )

    async def get_all_egress_state(self) -> list[dict]:
        """Return all egress_state rows (for rehydrate on coordinator startup)."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute("SELECT * FROM egress_state")
                rows = await cursor.fetchall()
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, r)) for r in rows]
        except Exception as err:
            _LOGGER.warning("egress_state scan failed: %s", err)
            return []

    async def clear_egress_state(self, zone_id: str) -> None:
        """Delete the egress_state row for a zone (resume / cooldown expiry)."""
        try:
            async with self._db() as db:
                await db.execute(
                    "DELETE FROM egress_state WHERE zone_id = ?",
                    (zone_id,),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "egress_state clear failed for %s: %s",
                zone_id, err,
            )

    async def async_delete_zone_data(
        self,
        zone_name: str,
        zone_id: str | None,
    ) -> dict[str, int]:
        """Purge all zone-keyed DB rows for a zone being deleted.

        Zone Delete Flow cycle: atomic multi-table purge triggered when a
        zone is removed from the Zone Manager options dict.

        Two keying regimes are handled:
          - Name-keyed: ``zone_events`` (col ``zone TEXT``, line 473),
            ``census_snapshots`` (col ``zone TEXT NOT NULL``, line 589),
            and ``ura_activity_log`` (col ``zone TEXT`` nullable, line
            1120). All three are always purged.
          - Id-keyed: ``ac_reset_state`` (PK ``zone_id``, line 1194),
            ``egress_state`` (PK ``zone_id``, line 1223), and
            ``ac_ramp_events`` (col ``zone_id NOT NULL``, line 1267).
            Purged only when ``zone_id`` is not None (husk zones with no
            thermostat have no zone_id and never wrote id-keyed rows).

        Eight tables total (fix-up R5 = 6 + HVAC-GOVERNED-EXCURSION-1
        fix-up r3 = +2 for hvac_excursion_state + hvac_excursion_events).
        Verified via re-grep of every ``zone TEXT`` and ``zone_id TEXT``
        column in the ``CREATE TABLE`` DDL surface (fix-up R5, review
        A-CRIT-1). ``room_state.last_lux_zone`` is a
        lux-band label (bright/dim), NOT a zone name — not purged.

        Note on ``fan_recheck_state``: the plan lists it as zone_id-keyed,
        but the live schema is per-ROOM (PK ``room_id``). Rooms survive
        zone deletion (they become unassigned), so fan_recheck rows must
        NOT be touched — skipping is correct.

        Atomicity: uses the same explicit ``BEGIN ... COMMIT`` shape as
        the v4.6.7 anomaly_log migration (database.py:1539) which is
        proven to work against the production ``aiosqlite.connect`` +
        ``_write_worker`` write-queue connection (worker at
        database.py:104 opens the connection with sqlite3's implicit
        deferred-transaction semantics — ``BEGIN`` is issued as a
        RAW statement AFTER the PRAGMA setup, before any auto-opened
        implicit txn interferes; the same pattern works here because
        this DAO is the sole caller for the duration of one _db() lease
        and no prior execute has been issued on the connection this
        turn). Fix-up R8: adjusted from ``BEGIN IMMEDIATE`` (which is
        the sqlite3 module's default write-lock flavor) to plain
        ``BEGIN`` to byte-match the migration precedent that has run
        in production since v4.6.7.

        Args:
            zone_name: Zone name string (matches ``zone_events.zone``).
            zone_id:   HVAC zone_id ("zone_N") or None for husk zones.

        Returns:
            Dict mapping table name to rows deleted. Tables that were
            skipped (id-keyed tables when zone_id is None) map to 0.
            On failure returns an empty dict and logs a warning.
        """
        # HVAC-GOVERNED-EXCURSION-1 fix-up r3 (2026-08-21): the D2
        # tables hvac_excursion_state (PK zone_id) and
        # hvac_excursion_events (zone_id NOT NULL) join the id-keyed
        # regime. Without deletion here, deleting a zone leaves orphan
        # excursion rows behind; a stale hvac_excursion_state row is
        # exactly what async_startup_excursion_audit rehydrates, so an
        # orphan produces a phantom excursion for a zone that no longer
        # exists. Both purged only when zone_id is not None (husk zones
        # have no id and never wrote id-keyed rows).
        result: dict[str, int] = {
            "zone_events": 0,
            "census_snapshots": 0,
            "ura_activity_log": 0,
            "ac_reset_state": 0,
            "egress_state": 0,
            "ac_ramp_events": 0,
            "hvac_excursion_state": 0,
            "hvac_excursion_events": 0,
        }
        try:
            async with self._db() as db:
                # Explicit transaction (Bug Class SPAN A-HIGH-1: partial
                # multi-table purge = silent inconsistency). Matches the
                # v4.6.7 anomaly_log migration pattern at line 1539.
                await db.execute("BEGIN")
                try:
                    # Name-keyed tables.
                    cur = await db.execute(
                        "DELETE FROM zone_events WHERE zone = ?",
                        (zone_name,),
                    )
                    result["zone_events"] = cur.rowcount or 0
                    cur = await db.execute(
                        "DELETE FROM census_snapshots WHERE zone = ?",
                        (zone_name,),
                    )
                    result["census_snapshots"] = cur.rowcount or 0
                    cur = await db.execute(
                        "DELETE FROM ura_activity_log WHERE zone = ?",
                        (zone_name,),
                    )
                    result["ura_activity_log"] = cur.rowcount or 0
                    # Id-keyed tables (skipped for husk zones).
                    if zone_id is not None:
                        cur = await db.execute(
                            "DELETE FROM ac_reset_state WHERE zone_id = ?",
                            (zone_id,),
                        )
                        result["ac_reset_state"] = cur.rowcount or 0
                        cur = await db.execute(
                            "DELETE FROM egress_state WHERE zone_id = ?",
                            (zone_id,),
                        )
                        result["egress_state"] = cur.rowcount or 0
                        cur = await db.execute(
                            "DELETE FROM ac_ramp_events WHERE zone_id = ?",
                            (zone_id,),
                        )
                        result["ac_ramp_events"] = cur.rowcount or 0
                        cur = await db.execute(
                            "DELETE FROM hvac_excursion_state WHERE zone_id = ?",
                            (zone_id,),
                        )
                        result["hvac_excursion_state"] = cur.rowcount or 0
                        cur = await db.execute(
                            "DELETE FROM hvac_excursion_events WHERE zone_id = ?",
                            (zone_id,),
                        )
                        result["hvac_excursion_events"] = cur.rowcount or 0
                    await db.commit()
                except Exception:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    raise
        except Exception as err:
            _LOGGER.warning(
                "async_delete_zone_data failed for zone=%r zone_id=%r: %s",
                zone_name, zone_id, err,
            )
            return {}
        _LOGGER.info(
            "async_delete_zone_data: zone=%r zone_id=%r rows=%s",
            zone_name, zone_id, result,
        )
        return result

    async def async_count_zone_rows(
        self,
        zone_name: str,
        zone_id: str | None,
    ) -> dict[str, int]:
        """Read-only pre-delete row-count per zone-keyed table.

        Zone Delete Flow fix-up R6 / A-HIGH-2: the D1 confirm screen
        must show HONEST row counts (not a table count masquerading as
        a row count). This DAO gets called once during
        ``_summarize_zone_deletion`` so the operator sees real numbers.

        Also serves as the Tier 2-DB pre-delete row-rate snapshot per
        review protocol.

        Returns a dict with the same 6 table keys as
        ``async_delete_zone_data``. Id-keyed tables report 0 when
        ``zone_id`` is None. On any read failure returns a dict of 6
        zeros and logs debug — the confirm screen degrades gracefully.
        """
        result: dict[str, int] = {
            "zone_events": 0,
            "census_snapshots": 0,
            "ura_activity_log": 0,
            "ac_reset_state": 0,
            "egress_state": 0,
            "ac_ramp_events": 0,
            # HVAC-GOVERNED-EXCURSION-1 fix-up r3: paired with the D2
            # tables added to async_delete_zone_data.
            "hvac_excursion_state": 0,
            "hvac_excursion_events": 0,
        }
        try:
            async with self._db_read() as db:
                for tbl in ("zone_events", "census_snapshots", "ura_activity_log"):
                    try:
                        cur = await db.execute(
                            f"SELECT COUNT(*) FROM {tbl} WHERE zone = ?",
                            (zone_name,),
                        )
                        row = await cur.fetchone()
                        result[tbl] = int(row[0]) if row else 0
                    except Exception as err:
                        _LOGGER.debug(
                            "async_count_zone_rows(%s): %s", tbl, err,
                        )
                if zone_id is not None:
                    for tbl in (
                        "ac_reset_state", "egress_state", "ac_ramp_events",
                        "hvac_excursion_state", "hvac_excursion_events",
                    ):
                        try:
                            cur = await db.execute(
                                f"SELECT COUNT(*) FROM {tbl} WHERE zone_id = ?",
                                (zone_id,),
                            )
                            row = await cur.fetchone()
                            result[tbl] = int(row[0]) if row else 0
                        except Exception as err:
                            _LOGGER.debug(
                                "async_count_zone_rows(%s): %s", tbl, err,
                            )
        except Exception as err:
            _LOGGER.debug(
                "async_count_zone_rows failed for zone=%r zone_id=%r: %s",
                zone_name, zone_id, err,
            )
        return result

    async def prune_stale_egress_state(self, cutoff_days: int = 7) -> int:
        """Prune stale egress_state rows.

        Removes idle rows (defensive — idle rows shouldn't exist) and any
        row whose last_update_ts is older than cutoff_days. Returns the
        number of rows deleted. Wired into the existing nightly maintenance
        hook (paired-cleanup per Bug Class #27).
        """
        cutoff = (dt_util.now() - timedelta(days=cutoff_days)).isoformat()
        deleted = 0
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    "DELETE FROM egress_state "
                    "WHERE state = 'idle' OR last_update_ts < ?",
                    (cutoff,),
                )
                await db.commit()
                deleted = cursor.rowcount
        except Exception as err:
            _LOGGER.warning("egress_state prune failed: %s", err)
            return 0
        if deleted > 0:
            _LOGGER.info(
                "egress_state prune: deleted %d stale rows (cutoff_days=%d)",
                deleted, cutoff_days,
            )
        return deleted

    # =========================================================================
    # Fan-noise Mode-2 mitigation: per-room state machine persistence.
    # Five DAOs mirror the egress_state shape (v4.7.8 precedent). All reads
    # and writes guard with try/except so transient SQLite failures degrade
    # gracefully (state machine restart-rehydrates as idle instead of crashing).
    # =========================================================================

    async def get_fan_recheck_state(self, room_id: str) -> dict | None:
        """Return fan_recheck_state row for a room, or None if no row exists."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT * FROM fan_recheck_state WHERE room_id = ?",
                    (room_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                columns = [d[0] for d in cursor.description]
                return dict(zip(columns, row))
        except Exception as err:
            _LOGGER.warning(
                "fan_recheck_state read failed for %s: %s",
                room_id, err,
            )
            return None

    async def save_fan_recheck_state(self, state: dict) -> None:
        """Upsert a fan_recheck_state row.

        snapshot_json is a JSON-serialized FanSnapshot. All timestamps are
        ISO strings (callers must format tz-aware datetimes via .isoformat()).
        """
        try:
            async with self._db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO fan_recheck_state (
                        room_id, state, state_entered_at, snapshot_json,
                        attempts_in_hour, last_outcome, last_attempt_at,
                        ble_ladder_layer, last_update_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        state["room_id"],
                        state["state"],
                        state.get("state_entered_at"),
                        state.get("snapshot_json"),
                        int(state.get("attempts_in_hour") or 0),
                        state.get("last_outcome"),
                        state.get("last_attempt_at"),
                        state.get("ble_ladder_layer"),
                        state.get("last_update_ts") or dt_util.now().isoformat(),
                    ),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "fan_recheck_state save failed for %s: %s",
                state.get("room_id"), err,
            )

    async def get_all_fan_recheck_state(self) -> list[dict]:
        """Return all fan_recheck_state rows (rehydrate on PC startup)."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute("SELECT * FROM fan_recheck_state")
                rows = await cursor.fetchall()
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, r)) for r in rows]
        except Exception as err:
            _LOGGER.warning("fan_recheck_state scan failed: %s", err)
            return []

    async def clear_fan_recheck_state(self, room_id: str) -> None:
        """Delete the fan_recheck_state row for a room."""
        try:
            async with self._db() as db:
                await db.execute(
                    "DELETE FROM fan_recheck_state WHERE room_id = ?",
                    (room_id,),
                )
                await db.commit()
        except Exception as err:
            _LOGGER.warning(
                "fan_recheck_state clear failed for %s: %s",
                room_id, err,
            )

    async def prune_stale_fan_recheck_state(self, cutoff_days: int = 14) -> int:
        """Prune idle rows + any row older than cutoff_days. Returns row count."""
        cutoff = (dt_util.now() - timedelta(days=cutoff_days)).isoformat()
        deleted = 0
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    "DELETE FROM fan_recheck_state "
                    "WHERE state = 'idle' OR last_update_ts < ?",
                    (cutoff,),
                )
                await db.commit()
                deleted = cursor.rowcount
        except Exception as err:
            _LOGGER.warning("fan_recheck_state prune failed: %s", err)
            return 0
        if deleted > 0:
            _LOGGER.info(
                "fan_recheck_state prune: deleted %d stale rows (cutoff_days=%d)",
                deleted, cutoff_days,
            )
        return deleted

    # =========================================================================
    # DB space-reclamation (incremental_vacuum + supervised activation VACUUM)
    #
    # The nightly prunes keep the LOGICAL DB size stable, but SQLite never
    # returns freed pages to the OS without a VACUUM. The DB file had
    # plateaued ~900 MB of mostly-empty pages. This pair reclaims that space
    # WITHOUT ever blocking core DB access unattended:
    #
    #   * incremental_vacuum() — SAFE, automatic. Bounded PRAGMA
    #     incremental_vacuum run through the single-writer worker, wired into
    #     the nightly 2:30 maintenance loop. No-ops cleanly until activation.
    #   * vacuum_full_supervised() — SUPERVISED, manual ONLY. The one-time
    #     full VACUUM that activates INCREMENTAL auto_vacuum. Exposed as a
    #     button; NEVER scheduled, because a full VACUUM of a ~900 MB Samba DB
    #     takes an exclusive lock for minutes (watchdog risk). v5.0.0
    #     write-flood is the cautionary precedent.
    # =========================================================================

    # Conservative per-night page cap for incremental_vacuum. At the default
    # 4096-byte page size this reclaims up to ~8 MB/night — enough to chip
    # away at the high-water mark while completing in well under a second
    # (and trivially under the 120s _db() guard). Intentionally NOT unbounded.
    _INCREMENTAL_VACUUM_MAX_PAGES = 2000

    async def incremental_vacuum(self, max_pages: int | None = None) -> int:
        """Reclaim up to `max_pages` freed pages back to the OS.

        Runs ``PRAGMA incremental_vacuum(N)`` through the single-writer worker
        (the ``_db()`` path), bounded to a conservative page count so it
        completes well under the 120s write-guard. Returns the number of pages
        actually reclaimed (delta in ``PRAGMA freelist_count``).

        NO-OPs (returns 0) when ``PRAGMA auto_vacuum`` is not INCREMENTAL
        (value 2) — i.e. before vacuum_full_supervised() has activated it on
        the existing DB. This makes it safe to wire into the nightly schedule
        immediately: it does nothing until activation, then begins reclaiming.
        """
        if max_pages is None:
            max_pages = self._INCREMENTAL_VACUUM_MAX_PAGES
        # Clamp to the conservative cap so a caller can't request an unbounded
        # (and potentially guard-busting) reclamation.
        max_pages = max(1, min(int(max_pages), self._INCREMENTAL_VACUUM_MAX_PAGES))
        reclaimed = 0
        try:
            async with self._db() as db:
                # Guard: incremental_vacuum only reclaims under INCREMENTAL
                # auto_vacuum. auto_vacuum values: 0=NONE, 1=FULL, 2=INCREMENTAL.
                cursor = await db.execute("PRAGMA auto_vacuum")
                row = await cursor.fetchone()
                mode = row[0] if row else 0
                if mode != 2:
                    _LOGGER.debug(
                        "incremental_vacuum: auto_vacuum=%s (not INCREMENTAL) "
                        "— no-op until supervised activation VACUUM runs",
                        mode,
                    )
                    return 0
                # Page size + freelist before, to report bytes reclaimed.
                cursor = await db.execute("PRAGMA page_size")
                row = await cursor.fetchone()
                page_size = row[0] if row else 4096
                cursor = await db.execute("PRAGMA freelist_count")
                row = await cursor.fetchone()
                free_before = row[0] if row else 0
                if free_before <= 0:
                    return 0
                # Bounded reclamation. SQLite caps N at the freelist size.
                await db.execute(f"PRAGMA incremental_vacuum({max_pages})")
                await db.commit()
                cursor = await db.execute("PRAGMA freelist_count")
                row = await cursor.fetchone()
                free_after = row[0] if row else 0
                reclaimed = max(0, free_before - free_after)
        except Exception as err:
            _LOGGER.warning("incremental_vacuum failed: %s", err)
            return 0
        if reclaimed > 0:
            _LOGGER.info(
                "incremental_vacuum: reclaimed %d pages (~%.1f MB) "
                "[cap=%d pages]",
                reclaimed,
                (reclaimed * page_size) / (1024 * 1024),
                max_pages,
            )
        return reclaimed

    # Guards against two concurrent supervised VACUUM runs (double button press).
    _vacuum_in_progress: bool = False

    async def vacuum_full_supervised(self) -> dict:
        """One-time SUPERVISED full VACUUM that activates INCREMENTAL auto_vacuum.

        This is a BLOCKING operation that takes an exclusive lock for minutes
        on a large DB. It is triggered MANUALLY (a button) and is NEVER wired
        into the unattended schedule. Operator runs it once, at low activity.

        Steps:
          (a) log start + current file size;
          (b) drain the pending write queue (graceful flush) so we don't race
              in-flight writes, then STOP the write worker (closes its
              persistent connection so it can't hold a WAL lock against the
              exclusive VACUUM; new writes queue rather than contend);
          (d) BEFORE the VACUUM, checkpoint(TRUNCATE) the WAL into the .db then
              copy the DB file to ``<db>.prevacuum.bak`` (a self-consistent,
              standalone rollback safety net);
          (c) on a DEDICATED short-lived connection (NOT the 120s-guarded
              worker path) with a high busy_timeout, set
              ``PRAGMA auto_vacuum=INCREMENTAL`` then run ``VACUUM`` — a 900 MB
              SMB VACUUM will exceed 120s and must not be interrupted;
          (e) verify via ``PRAGMA integrity_check`` (quick) + log final size;
          (f) RESTART the write worker (always, in a finally block) + return a
              result dict.

        Concurrent presses are rejected via ``_vacuum_in_progress``.
        """
        if self._vacuum_in_progress:
            _LOGGER.warning(
                "vacuum_full_supervised: a VACUUM is already in progress — "
                "ignoring re-entrant request"
            )
            return {"status": "already_running"}

        self._vacuum_in_progress = True
        result: dict = {"status": "error"}
        worker_was_running = (
            self._write_task is not None and not self._write_task.done()
        )
        try:
            def _file_mb(path: str) -> float:
                try:
                    return os.path.getsize(path) / (1024 * 1024)
                except OSError:
                    return -1.0

            size_before = _file_mb(self.db_file)
            _LOGGER.warning(
                "vacuum_full_supervised: STARTING supervised one-time VACUUM "
                "(file=%s, size=%.1f MB). This holds an exclusive lock for "
                "minutes — supervised op, NOT scheduled.",
                self.db_file, size_before,
            )
            result["size_mb_before"] = round(size_before, 1)

            # (b) Drain pending writes through the existing graceful flush so we
            # don't race in-flight writes against the exclusive VACUUM lock.
            # M-B1: surface (don't silently swallow) a flush error in the result
            # so the operator/log records it; we still continue because the
            # VACUUM uses its own connection and the worker is stopped next.
            try:
                await self._flush_pending_writes()
            except Exception as err:
                _LOGGER.warning(
                    "vacuum_full_supervised: write-queue flush raised %s "
                    "(continuing — VACUUM uses its own connection)", err,
                )
                result["flush_warning"] = str(err)

            # (b2) HIGH-2 (B-H1): STOP the write worker so its persistent
            # connection is CLOSED. A live worker connection holds a WAL lock
            # that conflicts with the VACUUM's exclusive lock — and any writes
            # arriving DURING the multi-minute VACUUM would contend on that lock
            # and fail after busy_timeout. Stopping closes the connection;
            # new _db() writes fail-fast (queued items wait) until restart.
            # The worker is ALWAYS restarted in the finally block below.
            await self.stop_write_worker()

            # (d) Back up the DB file BEFORE the VACUUM (rollback safety net).
            # M-B3: if an orphan/old .prevacuum.bak exists, shutil.copy2
            # overwrites it (no failure). M-B2: in WAL mode recent writes live
            # in the -wal sidecar, so a raw copy of the .db can be inconsistent.
            # Checkpoint(TRUNCATE) on the dedicated connection (worker now
            # stopped) folds the WAL back into the main file so the .bak is a
            # valid standalone DB.
            backup_path = f"{self.db_file}.prevacuum.bak"
            try:
                async with aiosqlite.connect(self.db_file, timeout=600.0) as ckpt:
                    await ckpt.execute("PRAGMA busy_timeout=600000")
                    # M-B2: make the .db self-consistent before the file copy.
                    await ckpt.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    await ckpt.commit()
            except Exception as err:
                _LOGGER.warning(
                    "vacuum_full_supervised: pre-backup WAL checkpoint raised "
                    "%s (continuing — backup may include -wal sidecar)", err,
                )
                result["checkpoint_warning"] = str(err)
            try:
                await self.hass.async_add_executor_job(
                    shutil.copy2, self.db_file, backup_path,
                )
                result["backup_path"] = backup_path
                _LOGGER.warning(
                    "vacuum_full_supervised: backed up DB to %s before VACUUM",
                    backup_path,
                )
            except Exception as err:
                _LOGGER.error(
                    "vacuum_full_supervised: backup to %s FAILED (%s) — "
                    "aborting VACUUM (no safety net)", backup_path, err,
                )
                result["status"] = "backup_failed"
                result["error"] = str(err)
                return result

            # (c) Dedicated short-lived connection with a high busy_timeout.
            # NOT the worker connection: VACUUM needs exclusive access and the
            # worker's persistent connection (plus transient readers) would
            # conflict. The worker is stopped (b2); run at low activity so
            # transient readers don't deadlock it.
            try:
                async with aiosqlite.connect(self.db_file, timeout=600.0) as db:
                    # 10-minute busy_timeout — generous headroom for a large
                    # SMB VACUUM. NOT bounded by the 120s _db() guard.
                    await db.execute("PRAGMA busy_timeout=600000")
                    # Activate INCREMENTAL auto_vacuum, then VACUUM to apply it.
                    await db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    await db.execute("VACUUM")
                    await db.commit()

                    # (e) Verify integrity (quick check) + row-count sanity.
                    cursor = await db.execute("PRAGMA integrity_check(1)")
                    integ_row = await cursor.fetchone()
                    integrity = integ_row[0] if integ_row else "no_result"
                    result["integrity_check"] = integrity

                    cursor = await db.execute("PRAGMA auto_vacuum")
                    av_row = await cursor.fetchone()
                    result["auto_vacuum_after"] = av_row[0] if av_row else None
            except Exception as err:
                _LOGGER.error(
                    "vacuum_full_supervised: VACUUM FAILED: %s — DB backup "
                    "preserved at %s for manual restore", err, backup_path,
                )
                result["status"] = "vacuum_failed"
                result["error"] = str(err)
                return result

            size_after = _file_mb(self.db_file)
            result["size_mb_after"] = round(size_after, 1)
            ok = result.get("integrity_check") == "ok"
            result["status"] = "ok" if ok else "integrity_warning"
            _LOGGER.warning(
                "vacuum_full_supervised: DONE. size %.1f MB -> %.1f MB "
                "(reclaimed ~%.1f MB), integrity=%s, auto_vacuum=%s. "
                "Nightly incremental_vacuum will now reclaim freed pages.",
                size_before, size_after, max(0.0, size_before - size_after),
                result.get("integrity_check"), result.get("auto_vacuum_after"),
            )
            return result
        finally:
            # HIGH-2: ALWAYS restart the write worker (even if VACUUM raised)
            # so DB writes resume. Only restart if it was running on entry —
            # don't spuriously start a worker that the caller never had up.
            if worker_was_running:
                try:
                    await self.start_write_worker()
                except Exception as err:
                    _LOGGER.error(
                        "vacuum_full_supervised: FAILED to restart write "
                        "worker after VACUUM: %s — writes will not flush!", err,
                    )
            self._vacuum_in_progress = False

    # =========================================================================
    # Hierarchical Memory MVP — episode + fact + baseline DAOs
    # (feature/memory-mvp 2026-08-02). See:
    #   docs/planning/ARCHITECTURE_hierarchical_memory.md §4, §5, §5c
    #   docs/planning/MVP_hierarchical_memory.md
    # All writes go through _db()'s write-queue like every other DAO.
    # Timestamps are UTC ISO with an explicit +00:00 offset — never naive
    # (audit gap #5).
    # =========================================================================

    async def log_memory_episode(
        self,
        node_id: str,
        episode_type: str,
        adjudication: str = "unadjudicated",
        adjudicated_by: str | None = None,
        attrs: dict | None = None,
        source_ref: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        dedup_source_ref: bool = False,
    ) -> int | None:
        """Insert a memory_episodes row. Returns row id or None on failure.

        Never raises: episode logging is observational, not on any control
        path.

        If `dedup_source_ref` is True and `source_ref` is provided, a row
        with the same source_ref that already exists causes the insert to
        be skipped and None returned (B-H3 real per-track dedup — used by
        ExteriorTrackLinker so teardown-flush + a subsequent idle-sweep
        close on the same track do not double-write).
        """
        import json as _json  # noqa: PLC0415
        try:
            from .const import (  # noqa: PLC0415
                MEMORY_EPISODE_DEDUP_WINDOW_S,
                MEMORY_EPISODE_TYPES,
            )
            if episode_type not in MEMORY_EPISODE_TYPES:
                _LOGGER.warning(
                    "log_memory_episode: unregistered episode_type=%r "
                    "(registry gate — add to MEMORY_EPISODE_TYPES first)",
                    episode_type,
                )
                return None
            # MED B4: in-memory per-(node_id, episode_type) dedup gate —
            # a repeat fire inside MEMORY_EPISODE_DEDUP_WINDOW_S is dropped
            # (Stage 1: no UPDATE-count machinery). Instance-scoped so it
            # survives across calls but resets on process restart.
            _dedup = self.__dict__.setdefault(
                "_memory_episode_dedup", {},
            )
            _dedup_key = (node_id, episode_type)
            _now_mono = datetime.now(timezone.utc).timestamp()
            _prev = _dedup.get(_dedup_key)
            if _prev is not None and (
                _now_mono - _prev
            ) < MEMORY_EPISODE_DEDUP_WINDOW_S:
                _LOGGER.debug(
                    "log_memory_episode: dropped repeat "
                    "(node=%s type=%s dt=%.1fs<%ds)",
                    node_id, episode_type, _now_mono - _prev,
                    MEMORY_EPISODE_DEDUP_WINDOW_S,
                )
                return None
            _dedup[_dedup_key] = _now_mono
            now_iso = datetime.now(timezone.utc).isoformat()
            started = started_at or now_iso
            adjudicated_at_iso = (
                now_iso if adjudication != "unadjudicated" else None
            )
            async with self._db() as db:
                if dedup_source_ref and source_ref:
                    # B-H3: existence check on source_ref — cheap SELECT,
                    # skip INSERT on match. Not a UNIQUE constraint (would
                    # require a schema migration); relying on this check
                    # is sufficient for the linker's teardown/idle-sweep
                    # race, and legacy callers get the pre-existing
                    # (node_id, episode_type) window dedup.
                    try:
                        existing = await db.execute(
                            "SELECT 1 FROM memory_episodes "
                            "WHERE source_ref = ? LIMIT 1",
                            (source_ref,),
                        )
                        row = await existing.fetchone()
                        if row is not None:
                            _LOGGER.debug(
                                "log_memory_episode: dedup_source_ref hit "
                                "(source_ref=%s) — dropping repeat.",
                                source_ref,
                            )
                            return None
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "dedup_source_ref existence check failed "
                            "(source_ref=%s) — falling through to insert.",
                            source_ref, exc_info=True,
                        )
                cursor = await db.execute(
                    """INSERT INTO memory_episodes (
                        node_id, episode_type, started_at, ended_at,
                        adjudication, adjudicated_at, adjudicated_by,
                        attrs_json, source_ref
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        node_id, episode_type, started, ended_at,
                        adjudication, adjudicated_at_iso, adjudicated_by,
                        _json.dumps(attrs or {}, default=str), source_ref,
                    ),
                )
                await db.commit()
                _LOGGER.debug(
                    "memory_episodes wrote row (node=%s type=%s "
                    "adjudication=%s by=%s)",
                    node_id, episode_type, adjudication,
                    adjudicated_by or "-",
                )
                return int(cursor.lastrowid) if cursor.lastrowid else None
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("log_memory_episode failed: %s", e)
            return None

    async def close_memory_episode(
        self,
        row_id: int,
        ended_at: str,
        close_attrs: dict | None = None,
    ) -> bool:
        """Force-close an open memory_episodes row (PATH-ALPHA D5).

        Sets ``ended_at`` on the row and merges ``close_attrs`` into
        ``attrs_json`` (the writer records close metadata like
        ``closed_by`` + ``duration_s``). Never raises — closing is
        observational.
        """
        import json as _json  # noqa: PLC0415
        try:
            async with self._db() as db:
                if close_attrs:
                    cursor = await db.execute(
                        "SELECT attrs_json FROM memory_episodes "
                        "WHERE id = ? LIMIT 1",
                        (int(row_id),),
                    )
                    row = await cursor.fetchone()
                    merged: dict = {}
                    if row is not None and row[0]:
                        try:
                            merged = _json.loads(row[0]) or {}
                        except Exception:  # noqa: BLE001
                            merged = {}
                    merged.update(close_attrs)
                    await db.execute(
                        "UPDATE memory_episodes SET ended_at = ?, "
                        "attrs_json = ? WHERE id = ?",
                        (
                            ended_at,
                            _json.dumps(merged, default=str),
                            int(row_id),
                        ),
                    )
                else:
                    await db.execute(
                        "UPDATE memory_episodes SET ended_at = ? "
                        "WHERE id = ?",
                        (ended_at, int(row_id)),
                    )
                await db.commit()
                return True
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("close_memory_episode failed: %s", e)
            return False

    async def fetch_open_memory_episodes_of_type(
        self, episode_type: str,
    ) -> list[dict]:
        """Return open (ended_at IS NULL) episodes of a given type.

        Used at boot by ``memory_writers.reconcile_open_away_block_on_boot``
        to discharge any OPEN episode left over across a restart.
        """
        try:
            async with self._db() as db:
                cursor = await db.execute(
                    "SELECT id, node_id, started_at, source_ref "
                    "FROM memory_episodes WHERE episode_type = ? "
                    "AND ended_at IS NULL",
                    (episode_type,),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "id": int(r[0]),
                        "node_id": r[1],
                        "started_at": r[2],
                        "source_ref": r[3],
                    }
                    for r in rows
                ]
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "fetch_open_memory_episodes_of_type(%s) failed: %s",
                episode_type, e,
            )
            return []

    async def upsert_memory_baseline(
        self,
        node_id: str,
        metric_name: str,
        new_sample: float,
        sample_cap: int,
    ) -> None:
        """Welford UPSERT for a memory baseline row.

        Uses the reused `metric_baselines` table with `coordinator_id`
        column carrying our tier prefix "memory" (distinct from other
        coordinators), `metric_name` = context-qualified signal name
        (e.g. "humidity:h14:home"), `scope` = the node_id (e.g.
        "room:study_a"). See architecture §5.

        Welford incremental update; count clamped to `sample_cap` so
        baselines track season drift without a scheduled forgetting job.
        """
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with self._db() as db:
                cursor = await db.execute(
                    """SELECT mean, variance, sample_count FROM
                       metric_baselines WHERE coordinator_id=?
                       AND metric_name=? AND scope=?""",
                    ("memory", metric_name, node_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    mean = float(new_sample)
                    variance = 0.0
                    count = 1
                else:
                    old_mean = float(row[0])
                    old_var = float(row[1])
                    old_n = int(row[2])
                    n = min(old_n + 1, sample_cap)
                    delta = float(new_sample) - old_mean
                    mean = old_mean + delta / n
                    delta2 = float(new_sample) - mean
                    # Welford's M2 update, normalized to variance.
                    # MED A-M1: at the clamp (old_n == sample_cap so
                    # n == old_n), shrink historical M2 by (n-1)/n so
                    # variance TRACKS current spread rather than inflating
                    # monotonically. Below the clamp it's the classic
                    # Welford update (scale=1.0 identity).
                    m2_old = old_var * max(old_n - 1, 0)
                    if old_n >= sample_cap:  # at cap — decay historical
                        scale = (n - 1) / max(n, 1)  # < 1
                    else:
                        scale = 1.0
                    m2 = m2_old * scale + delta * delta2
                    variance = m2 / max(n - 1, 1)
                    count = n
                await db.execute(
                    """INSERT INTO metric_baselines (
                        coordinator_id, metric_name, scope,
                        mean, variance, sample_count, last_updated
                    ) VALUES ('memory', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(coordinator_id, metric_name, scope)
                    DO UPDATE SET mean=excluded.mean,
                                  variance=excluded.variance,
                                  sample_count=excluded.sample_count,
                                  last_updated=excluded.last_updated""",
                    (metric_name, node_id, mean, variance, count, now_iso),
                )
                await db.commit()
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "upsert_memory_baseline failed (node=%s metric=%s): %s",
                node_id, metric_name, e,
            )

    # --- Memory read-DAO failure latch (LOW A-LOW) --------------------
    # One-shot WARNING per DAO name, DEBUG thereafter. Kept as an instance
    # attribute so it survives across calls but resets on process restart.
    def _mem_dao_warn(self, dao_name: str, exc: Exception) -> None:
        latch = self.__dict__.setdefault("_memory_read_dao_warned", set())
        if dao_name not in latch:
            latch.add(dao_name)
            _LOGGER.warning(
                "%s failed (first occurrence — subsequent failures at "
                "DEBUG): %s", dao_name, exc,
            )
        else:
            _LOGGER.debug("%s failed: %s", dao_name, exc)

    async def read_memory_baseline(
        self, node_id: str, metric_name: str,
    ) -> dict | None:
        """Read a single memory baseline row. Returns dict or None."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT mean, variance, sample_count, last_updated
                       FROM metric_baselines
                       WHERE coordinator_id='memory'
                         AND metric_name=? AND scope=?""",
                    (metric_name, node_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                return {
                    "mean": float(row[0]),
                    "variance": float(row[1]),
                    "sample_count": int(row[2]),
                    "last_updated": row[3],
                }
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("read_memory_baseline", e)
            return None

    async def read_memory_baselines_for_node(
        self, node_id: str,
    ) -> list[dict]:
        """List all memory baseline rows for a node."""
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT metric_name, mean, variance, sample_count,
                              last_updated
                       FROM metric_baselines
                       WHERE coordinator_id='memory' AND scope=?""",
                    (node_id,),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "metric_name": r[0], "mean": float(r[1]),
                        "variance": float(r[2]),
                        "sample_count": int(r[3]),
                        "last_updated": r[4],
                    }
                    for r in rows
                ]
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("read_memory_baselines_for_node", e)
            return []

    async def read_memory_episodes(
        self,
        node_id: str,
        episode_type: str | None = None,
        since_iso: str | None = None,
    ) -> list[dict]:
        """Read matching episodes for a node."""
        import json as _json  # noqa: PLC0415
        try:
            clauses = ["node_id = ?"]
            params: list = [node_id]
            if episode_type is not None:
                clauses.append("episode_type = ?")
                params.append(episode_type)
            if since_iso is not None:
                clauses.append("started_at >= ?")
                params.append(since_iso)
            where = " AND ".join(clauses)
            async with self._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT id, node_id, episode_type, started_at,
                              ended_at, adjudication, adjudicated_at,
                              adjudicated_by, attrs_json, source_ref
                       FROM memory_episodes
                       WHERE {where}
                       ORDER BY started_at ASC""",
                    tuple(params),
                )
                rows = await cursor.fetchall()
                out = []
                for r in rows:
                    try:
                        attrs = _json.loads(r[8]) if r[8] else {}
                    except Exception:  # noqa: BLE001
                        attrs = {}
                    out.append({
                        "id": int(r[0]), "node_id": r[1],
                        "episode_type": r[2],
                        "started_at": r[3], "ended_at": r[4],
                        "adjudication": r[5], "adjudicated_at": r[6],
                        "adjudicated_by": r[7], "attrs": attrs,
                        "source_ref": r[9],
                    })
                return out
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("read_memory_episodes", e)
            return []

    async def read_memory_facts(
        self,
        node_id: str,
        topic: str | None = None,
        include_superseded: bool = False,
    ) -> list[dict]:
        """Read facts for a node; by default only current (non-superseded)."""
        import json as _json  # noqa: PLC0415
        try:
            clauses = ["node_id = ?"]
            params: list = [node_id]
            if topic is not None:
                clauses.append("topic = ?")
                params.append(topic)
            if not include_superseded:
                clauses.append("superseded_by IS NULL")
            where = " AND ".join(clauses)
            async with self._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT id, node_id, topic, statement, attrs_json,
                              confidence, derived_from, created_at,
                              superseded_by
                       FROM memory_facts
                       WHERE {where}
                       ORDER BY id ASC""",
                    tuple(params),
                )
                rows = await cursor.fetchall()
                out = []
                for r in rows:
                    try:
                        attrs = _json.loads(r[4]) if r[4] else {}
                    except Exception:  # noqa: BLE001
                        attrs = {}
                    out.append({
                        "id": int(r[0]), "node_id": r[1], "topic": r[2],
                        "statement": r[3], "attrs": attrs,
                        "confidence": float(r[5]),
                        "derived_from": r[6], "created_at": r[7],
                        "superseded_by": r[8],
                    })
                return out
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("read_memory_facts", e)
            return []

    async def read_distinct_nodes_for_episodes(
        self, episode_type: str, since_iso: str,
    ) -> list[str]:
        """Distinct node_ids that have episodes of ``episode_type`` at
        or after ``since_iso``.

        MEMORY-COMPACTOR-1 fix-up HIGH-A1 (2026-08-14): the compactor
        engine's node discovery is data-driven — this DAO returns
        exactly the nodes that actually have episodes in the window,
        not a hardcoded / hass.data-derived candidate set (which
        misspelled a slot key and silently distilled nothing for
        every room-scoped rule).

        HIGH-2 (Stage-1) compliance: read via ``_db_read()`` — never
        touches the write queue. Covered by mutation drill #5 in
        ``quality/tests/test_memory_compactor.py``.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    "SELECT DISTINCT node_id FROM memory_episodes "
                    "WHERE episode_type = ? AND started_at >= ? "
                    "ORDER BY node_id ASC",
                    (episode_type, since_iso),
                )
                rows = await cursor.fetchall()
                return [str(r[0]) for r in rows if r[0] is not None]
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("read_distinct_nodes_for_episodes", e)
            return []

    async def get_memory_status_counts(self) -> dict:
        """Public read-only accessor for URAMemoryStatusSensor (LOW B9).

        Returns {episode_total, episodes_by_type, facts_count,
        baseline_row_count}. Uses the ``_db_read`` pool — never touches
        the write queue. Failures return zeros so the sensor never blocks.
        """
        try:
            async with self._db_read() as db:
                cur = await db.execute(
                    "SELECT COUNT(*), episode_type FROM memory_episodes "
                    "GROUP BY episode_type"
                )
                rows = await cur.fetchall()
                by_type: dict = {}
                total = 0
                for r in rows:
                    by_type[r[1]] = int(r[0])
                    total += int(r[0])
                cur = await db.execute(
                    "SELECT COUNT(*) FROM memory_facts "
                    "WHERE superseded_by IS NULL"
                )
                r = await cur.fetchone()
                facts_count = int(r[0]) if r else 0
                cur = await db.execute(
                    "SELECT COUNT(*) FROM metric_baselines "
                    "WHERE coordinator_id='memory'"
                )
                r = await cur.fetchone()
                baseline_row_count = int(r[0]) if r else 0
                return {
                    "episode_total": total,
                    "episodes_by_type": by_type,
                    "facts_count": facts_count,
                    "baseline_row_count": baseline_row_count,
                }
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("get_memory_status_counts", e)
            return {
                "episode_total": 0,
                "episodes_by_type": {},
                "facts_count": 0,
                "baseline_row_count": 0,
            }

    # ------------------------------------------------------------------
    # MEMORY-COMPACTOR-1 D3: combined-atomic distill DAO.
    # ------------------------------------------------------------------
    # CRIT-1 fix (plan review): _db() cannot be nested and each
    # acquisition = one queue submission = one commit. To honor
    # invariant §1(a) (fact INSERT + supersede UPDATE must be atomic
    # per logical fact), the compactor engine calls ONE combined DAO
    # that opens ONE _db() context and issues INSERT OR IGNORE +
    # optional supersede UPDATE + optional redaction UPDATE + one
    # commit(). The engine NEVER opens _db() itself.
    # ------------------------------------------------------------------

    async def distill_memory_fact(
        self,
        *,
        node_id: str,
        topic: str,
        statement: str,
        attrs: dict,
        confidence: float,
        derived_from: str,
        supersede_old_id: int | None = None,
        redact_episode_id: int | None = None,
    ) -> dict:
        """Atomic compactor write for one logical fact.

        INSERT OR IGNORE the fact; if `supersede_old_id` is set AND a
        new row was inserted, UPDATE the old row's `superseded_by` to
        point at the new row (WHERE-guarded so re-runs are no-ops).
        If `redact_episode_id` is set, transform that episode's
        `attrs_json` to a rollup shape (framework-only path; asserted
        off unless `MEMORY_REDACTION_HORIZON_DAYS` is set).

        All operations execute inside ONE `_db()` acquisition -> ONE
        `commit()` (invariant §1(a) atomicity). See
        docs/planning/PLANNING_memory_compactor.md §D3.

        Returns::

            {"inserted_id": int | None,
             "superseded":  bool,
             "redacted":    bool}
        """
        import json as _json  # noqa: PLC0415
        # Guard the redaction path from accidental use before the
        # horizon knob is set (rev-2 ships redaction disabled).
        if redact_episode_id is not None:
            from .const import MEMORY_REDACTION_HORIZON_DAYS  # noqa: PLC0415
            assert MEMORY_REDACTION_HORIZON_DAYS is not None, (
                "distill_memory_fact: redact_episode_id passed while "
                "MEMORY_REDACTION_HORIZON_DAYS is None (framework-only "
                "path is inert until the horizon knob is set)."
            )
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            async with self._db() as db:
                # (1) INSERT OR IGNORE the fact row.
                cur = await db.execute(
                    """INSERT OR IGNORE INTO memory_facts (
                        node_id, topic, statement, attrs_json,
                        confidence, derived_from, created_at,
                        superseded_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        node_id, topic, statement,
                        _json.dumps(attrs or {}, default=str),
                        float(confidence), derived_from, now_iso,
                    ),
                )
                # SQLite semantics: sqlite3_last_insert_rowid is NOT
                # reset on INSERT OR IGNORE when the row is IGNOREd, so
                # cursor.lastrowid alone would echo a prior INSERT's id.
                # The `cur.rowcount` guard (0 on IGNORE, 1 on success)
                # is load-bearing — do not drop it in a future refactor
                # (Review A LOW-A1).
                inserted_rowid = int(cur.lastrowid) if cur.rowcount else 0
                inserted = inserted_rowid > 0

                # (2) Supersede prior fact IFF new row was inserted.
                #     WHERE-guarded so a double-supersede is a no-op.
                superseded = False
                if inserted and supersede_old_id is not None:
                    upd = await db.execute(
                        """UPDATE memory_facts
                           SET superseded_by = ?
                           WHERE id = ? AND superseded_by IS NULL""",
                        (inserted_rowid, int(supersede_old_id)),
                    )
                    superseded = bool(upd.rowcount)

                # (3) Redaction stub — framework only.
                redacted = False
                if inserted and redact_episode_id is not None:
                    rollup = _json.dumps(
                        {"_redacted": True,
                         "topic": topic,
                         "fact_id": inserted_rowid},
                        default=str,
                    )
                    upd = await db.execute(
                        """UPDATE memory_episodes
                           SET attrs_json = ?
                           WHERE id = ?""",
                        (rollup, int(redact_episode_id)),
                    )
                    redacted = bool(upd.rowcount)

                # ONE commit for the whole logical fact (invariant §1(a)).
                await db.commit()

                return {
                    "inserted_id": inserted_rowid if inserted else None,
                    "superseded": superseded,
                    "redacted": redacted,
                }
        except AssertionError:
            # Do NOT swallow guard assertions (framework-only path).
            raise
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("distill_memory_fact failed: %s", e)
            return {
                "inserted_id": None,
                "superseded": False,
                "redacted": False,
            }

    # ------------------------------------------------------------------
    # D4 cadence guard state (set by memory_compactor after each run).
    # Instance-scoped; resets on process restart. Used by
    # run_memory_compactor() to skip a repeat run within cadence.
    # ------------------------------------------------------------------
    _last_compactor_stats: dict | None = None
    _last_compactor_run_ts: float | None = None

    def _compactor_within_cadence(self) -> bool:
        """True if the last compactor run was less than
        MEMORY_COMPACTOR_CADENCE_HOURS ago.
        """
        from .const import MEMORY_COMPACTOR_CADENCE_HOURS  # noqa: PLC0415
        if self._last_compactor_run_ts is None:
            return False
        if MEMORY_COMPACTOR_CADENCE_HOURS <= 0:
            return False
        now = datetime.now(timezone.utc).timestamp()
        return (now - self._last_compactor_run_ts) < (
            float(MEMORY_COMPACTOR_CADENCE_HOURS) * 3600.0
        )

    async def run_memory_compactor(
        self, *, triggered_by: str = "nightly",
    ) -> dict | None:
        """Thin adapter: nightly maintenance calls this.

        Cadence-guarded for nightly runs; the manual button passes
        `triggered_by='manual'` which BYPASSES the cadence guard
        (supervised override). Persists last-run stats on the DAO so
        `sensor.ura_memory_status` can surface them.
        """
        from .const import (  # noqa: PLC0415
            MEMORY_COMPACTOR_ENABLED,
            MEMORY_COMPACTOR_CADENCE_HOURS,
        )
        if not MEMORY_COMPACTOR_ENABLED or MEMORY_COMPACTOR_CADENCE_HOURS == 0:
            return None
        if triggered_by == "nightly" and self._compactor_within_cadence():
            _LOGGER.debug(
                "run_memory_compactor: skipped — within cadence "
                "(%.1fh)", float(MEMORY_COMPACTOR_CADENCE_HOURS),
            )
            return None
        # Local import — module-load asserts run here (episode-type ⊂
        # MEMORY_EPISODE_TYPES; topics ⊂ MEMORY_FACT_TOPICS).
        from .memory_compactor import MemoryCompactor  # noqa: PLC0415
        stats = await MemoryCompactor(self).run(triggered_by=triggered_by)
        self._last_compactor_stats = stats
        self._last_compactor_run_ts = datetime.now(timezone.utc).timestamp()
        _LOGGER.info(
            "memory_compactor run: created=%d superseded=%d writes=%d "
            "aborted=%s triggered_by=%s",
            stats.get("facts_created", 0),
            stats.get("facts_superseded", 0),
            stats.get("writes_total", 0),
            stats.get("aborted_reason"),
            triggered_by,
        )
        return stats

    async def read_decision_log_since(
        self, since_iso: str, limit: int = 500,
    ) -> list[dict]:
        """Read decision_log rows since a timestamp, oldest first.

        Used by MemoryFacade.narrative() to merge coordinator decisions
        with room episodes (architecture explicitly allows narrative to
        touch raw logs). Read-only via _db_read.
        """
        try:
            async with self._db_read() as db:
                cursor = await db.execute(
                    """SELECT timestamp, coordinator_id, decision_type,
                              scope, situation_classified
                       FROM decision_log
                       WHERE timestamp >= ?
                       ORDER BY timestamp ASC
                       LIMIT ?""",
                    (since_iso, int(limit)),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "timestamp": r[0],
                        "coordinator_id": r[1],
                        "decision_type": r[2],
                        "scope": r[3],
                        "situation_classified": r[4],
                    }
                    for r in (rows or [])
                ]
        except Exception as e:  # noqa: BLE001
            self._mem_dao_warn("read_decision_log_since", e)
            return []
