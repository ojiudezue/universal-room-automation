"""UNLOAD-SYMMETRY-TASK-HYGIENE-1 — D1 + D3 behavioural tests.

Covers:
  D1: DBShuttingDown subclass + DEBUG-level routing of DAO except-arms;
      shutdown-path _drain_pending_futures raises DBShuttingDown; the
      connection-lost drain path still raises plain RuntimeError
      (discriminator — ensures the demotion is scoped to shutdown).
  D3: Seven diagnostics read sites route through _db_read() (reads
      counter increments, writes counter does not); orphan prune after
      split still writes.

All tests drive the REAL database.py / coordinator_diagnostics.py
modules (HA plumbing is mocked at module-load time by the shared
boot-race test prelude).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import types
from unittest.mock import MagicMock

import pytest

# Reuse the HA mock plumbing. UniversalRoomDatabase is resolved freshly
# per-test via _reload_db_modules() below — do NOT import it at module
# scope. Sibling test files (anomaly-coverage harness uses
# `import_isolated`; provenance/reconcile harnesses rewrite
# `sys.modules["custom_components.universal_room_automation.*"]`) can
# leave the `database` module and `coordinator_diagnostics` module as
# two DIFFERENT copies in sys.modules, so a module-level
# `UniversalRoomDatabase` captured at collection raises one
# `DBShuttingDown` class while cdiag's `except DBShuttingDown` arm (and
# this file's module-level import) hold a DIFFERENT class. The isinstance
# / pytest.raises checks then miss and the DAO logs ERROR instead of
# DEBUG. Reloading both modules together at the start of every test
# forces one consistent pair.
from test_db_write_worker_boot_race import ura_db  # noqa: F401,E402


def _reload_db_modules():
    """Return (database_module, coordinator_diagnostics_module), freshly
    loaded as a consistent pair.

    Guarantees:
      - `sys.modules[<database>]` is this exact `database` module object
        AFTER the call (so later imports anywhere resolve to it).
      - `coordinator_diagnostics.DBShuttingDown is database.DBShuttingDown`
        (cdiag's `from ..database import DBShuttingDown` is re-bound to
        the fresh database module).
    """
    import importlib
    import sys as _sys

    db_name = "custom_components.universal_room_automation.database"
    cdiag_name = (
        "custom_components.universal_room_automation."
        "domain_coordinators.coordinator_diagnostics"
    )
    # Drop any cached copies — a sibling harness may have left a swapped
    # database module behind.
    _sys.modules.pop(cdiag_name, None)
    _sys.modules.pop(db_name, None)
    db = importlib.import_module(db_name)
    cdiag = importlib.import_module(cdiag_name)
    assert cdiag.DBShuttingDown is db.DBShuttingDown, (
        "coordinator_diagnostics did not rebind to the freshly-reloaded "
        "database module"
    )
    return db, cdiag


@pytest.fixture(autouse=True)
def _hermetic_db_modules():
    """Ensure every test in this file sees a consistent (database,
    coordinator_diagnostics) pair, regardless of what sibling test
    modules left in sys.modules."""
    _reload_db_modules()
    yield


def _make_db(tmp_path: str, is_stopping: bool = False):
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)
    hass.is_stopping = is_stopping
    hass.data = {}

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task
    import sys as _sys
    db_mod = _sys.modules[
        "custom_components.universal_room_automation.database"
    ]
    return db_mod.UniversalRoomDatabase(hass)


def _dbshutting_down_cls():
    """Current DBShuttingDown class, from the live database module."""
    import sys as _sys
    return _sys.modules[
        "custom_components.universal_room_automation.database"
    ].DBShuttingDown


# ---------------------------------------------------------------------------
# D1 — DBShuttingDown subclass + DEBUG routing
# ---------------------------------------------------------------------------


def test_db_fast_fails_with_db_shutting_down_subclass(tmp_path):
    """D1: the _db() shutdown fast-fail must raise DBShuttingDown, not
    bare RuntimeError. DBShuttingDown subclasses RuntimeError so legacy
    `except RuntimeError` still catches it."""
    db = _make_db(str(tmp_path), is_stopping=True)

    async def _scenario():
        await db.initialize()
        cls = _dbshutting_down_cls()
        with pytest.raises(cls):
            async with db._db() as _conn:
                pass
        # Subclass relationship — legacy callers still work.
        assert issubclass(cls, RuntimeError)

    asyncio.get_event_loop().run_until_complete(_scenario())


def test_db_shutting_down_logs_debug_not_error_in_dao(tmp_path, caplog):
    """D1: a DAO call during shutdown returns its neutral default via the
    DBShuttingDown DEBUG arm — no ERROR record is emitted."""
    db = _make_db(str(tmp_path), is_stopping=True)

    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}

    logger = cdiag.DecisionLogger(hass)

    decision = types.SimpleNamespace(
        timestamp=__import__("datetime").datetime(2026, 10, 13),
        coordinator_id="test",
        decision_type="t",
        scope="s",
        situation_classified="s",
        urgency="low",
        confidence=1.0,
        context={},
        action={},
        expected_savings_kwh=0.0,
        expected_cost_savings=0.0,
        expected_comfort_impact=0.0,
        constraints_published={},
        devices_commanded=[],
    )

    async def _scenario():
        await db.initialize()
        with caplog.at_level(
            logging.DEBUG,
            logger="custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics",
        ):
            result = await logger.log_decision(decision)
        assert result is None  # neutral default
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors == [], f"unexpected ERROR records: {errors!r}"
        debugs = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG
            and "HA shutting down" in r.getMessage()
        ]
        assert debugs, "expected a DEBUG line marking the shutdown skip"

    asyncio.get_event_loop().run_until_complete(_scenario())


def test_db_other_errors_still_log_error(tmp_path, caplog):
    """D1 discriminator (over-swallow guard): a generic RuntimeError from
    a DAO is NOT a DBShuttingDown — the ERROR path must still fire."""
    db = _make_db(str(tmp_path), is_stopping=False)

    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    hass = MagicMock()

    # A fake database whose _db() context manager raises a generic
    # RuntimeError (NOT DBShuttingDown) — simulates a connection-lost
    # style failure.
    class _ExplodingDB:
        from contextlib import asynccontextmanager  # noqa: PLC0415

        @asynccontextmanager
        async def _db(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("connection lost")
            yield  # pragma: no cover

        @asynccontextmanager
        async def _db_read(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("connection lost")
            yield  # pragma: no cover

    hass.data = {cdiag.DOMAIN: {"database": _ExplodingDB()}}

    logger = cdiag.DecisionLogger(hass)

    async def _scenario():
        with caplog.at_level(
            logging.ERROR,
            logger="custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics",
        ):
            result = await logger.log_decision(
                types.SimpleNamespace(
                    timestamp=__import__("datetime").datetime(2026, 10, 13),
                    coordinator_id="t",
                    decision_type="t",
                    scope="s",
                    situation_classified="s",
                    urgency="low",
                    confidence=1.0,
                    context={}, action={},
                    expected_savings_kwh=0.0,
                    expected_cost_savings=0.0,
                    expected_comfort_impact=0.0,
                    constraints_published={},
                    devices_commanded=[],
                )
            )
        assert result is None
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "generic RuntimeError must still log ERROR"

    asyncio.get_event_loop().run_until_complete(_scenario())


def test_drain_pending_futures_shutdown_raises_dbshuttingdown(tmp_path):
    """D1 (P5 split): the shutdown-timeout drain path must raise
    DBShuttingDown into pending futures so DAO except-arms route to
    DEBUG."""
    db = _make_db(str(tmp_path), is_stopping=True)

    async def _scenario():
        await db.initialize()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        # Enqueue a factory + future directly to simulate a pending write
        # at drain time. The factory never runs.
        async def _factory(_db):  # pragma: no cover - never called
            return None
        db._write_queue.put_nowait((_factory, fut))

        # Shutdown-path drain
        db._drain_pending_futures("shutdown timeout", is_shutdown=True)

        with pytest.raises(_dbshutting_down_cls()):
            await fut

    asyncio.get_event_loop().run_until_complete(_scenario())


def test_drain_pending_futures_connection_lost_raises_runtime_error(tmp_path):
    """D1 (P5 discriminator): the non-shutdown drain path (reason=str(exc))
    must still raise plain RuntimeError so callers log at ERROR."""
    db = _make_db(str(tmp_path), is_stopping=False)

    async def _scenario():
        await db.initialize()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        async def _factory(_db):  # pragma: no cover - never called
            return None
        db._write_queue.put_nowait((_factory, fut))

        # Connection-lost call site: is_shutdown defaults to False.
        db._drain_pending_futures("connection lost: EBADF")

        with pytest.raises(RuntimeError) as excinfo:
            await fut
        # It must NOT be the DBShuttingDown subclass (type-check).
        assert type(excinfo.value) is RuntimeError
        assert not isinstance(excinfo.value, _dbshutting_down_cls())

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# D3 — diagnostics reads route through _db_read()
# ---------------------------------------------------------------------------


def _mk_detector(tmp_path):
    """Build an AnomalyDetector hitting the real DB. Uses `safety` as the
    coordinator_id so metric_names is non-empty."""
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    db = _make_db(str(tmp_path), is_stopping=False)
    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}
    det = cdiag.AnomalyDetector(hass, coordinator_id="safety", metric_names=["noise_floor"])
    # Give it a known metric name so load_baselines keeps rows.
    det.metric_names = ["noise_floor"]
    return db, det, cdiag


def test_diagnostics_reads_increment_reads_not_writes(tmp_path):
    """D3 (P6 in-suite oracle): the 7 converted sites route through
    `_db_read()` — `_db_stats['reads']` increases, `_db_stats['writes']`
    is unchanged by them."""
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    db = _make_db(str(tmp_path), is_stopping=False)
    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}

    dlog = cdiag.DecisionLogger(hass)
    ctrack = cdiag.ComplianceTracker(hass)
    det = cdiag.AnomalyDetector(hass, coordinator_id="safety", metric_names=["noise_floor"])
    det.metric_names = ["noise_floor"]

    async def _scenario():
        await db.initialize()
        await db.start_write_worker()

        reads0 = db._db_stats["reads"]
        writes0 = db._db_stats["writes"]

        # Invoke each of the 7 converted read sites.
        await dlog.get_decisions()
        await dlog.get_decisions_count()
        await ctrack.get_compliance_rate()
        await ctrack.get_override_count()
        await ctrack.get_override_sources()
        await det.get_anomaly_count()
        await det.load_baselines()  # SELECT portion only; no orphans => no prune

        reads = db._db_stats["reads"] - reads0
        writes = db._db_stats["writes"] - writes0

        assert reads == 7, (
            f"expected 7 _db_read() increments, got {reads}. "
            "A read site may have regressed to _db(); a swap left on _db() "
            "would increment writes instead."
        )
        assert writes == 0, (
            f"converted read sites must not increment writes; got {writes}"
        )

        await db.stop_write_worker()

    asyncio.get_event_loop().run_until_complete(_scenario())


def test_diagnostics_reads_survive_worker_stopped(tmp_path, caplog):
    """D3: with the write worker cancelled and hass.is_stopping=True, all
    7 converted read methods must return their neutral defaults without
    raising and without emitting ERROR."""
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    db = _make_db(str(tmp_path), is_stopping=True)
    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}

    dlog = cdiag.DecisionLogger(hass)
    ctrack = cdiag.ComplianceTracker(hass)
    det = cdiag.AnomalyDetector(hass, coordinator_id="safety", metric_names=["noise_floor"])
    det.metric_names = ["noise_floor"]

    async def _scenario():
        await db.initialize()
        # Worker is NOT started — simulates a stopped-worker shutdown.
        with caplog.at_level(logging.ERROR):
            assert await dlog.get_decisions() == []
            assert await dlog.get_decisions_count() == 0
            assert await ctrack.get_compliance_rate() == 1.0
            assert await ctrack.get_override_count() == 0
            assert await ctrack.get_override_sources() == []
            assert await det.get_anomaly_count() == 0
            # load_baselines returns None; must not raise.
            await det.load_baselines()
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors == [], f"unexpected ERROR records: {errors!r}"

    asyncio.get_event_loop().run_until_complete(_scenario())


def test_load_baselines_split_prune_still_writes(tmp_path):
    """D3: the orphan-prune DELETE after the SELECT→read split must still
    succeed via _db() — removes rows whose metric_name is not in the
    coordinator's current metric_names registry."""
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    db = _make_db(str(tmp_path), is_stopping=False)
    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}

    det = cdiag.AnomalyDetector(hass, coordinator_id="safety", metric_names=["noise_floor"])
    det.metric_names = ["noise_floor"]  # anything NOT this name is an orphan

    async def _scenario():
        await db.initialize()
        await db.start_write_worker()

        # Seed one orphan row (metric_name not in valid_metrics).
        async with db._db() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO metric_baselines "
                "(coordinator_id, metric_name, scope, mean, variance, "
                "sample_count, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("safety", "deprecated_metric", "all", 1.0, 0.1, 10,
                 "2026-10-13T00:00:00"),
            )
            await conn.commit()

        writes_before = db._db_stats["writes"]
        await det.load_baselines()
        writes_after = db._db_stats["writes"]
        assert writes_after > writes_before, (
            "orphan prune must perform at least one _db() write"
        )

        # Row is gone.
        import sqlite3
        conn = sqlite3.connect(db.db_file)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM metric_baselines "
                "WHERE coordinator_id='safety' AND metric_name='deprecated_metric'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert n == 0, "orphan row must have been pruned"

        await db.stop_write_worker()

    asyncio.get_event_loop().run_until_complete(_scenario())


# ---------------------------------------------------------------------------
# Fix-up (reviews A-L1/A-L2/B-LOW-1/B-LOW-3, 2026-10-14)
# ---------------------------------------------------------------------------


def _flush_with_expired_budget(db, monkeypatch):
    """Run _flush_pending_writes with one queued write and a budget that is
    already spent, so the write is left for the leftover drain.

    We patch ``database.time.monotonic`` only AFTER ``db.initialize()`` has
    run, so startup latency math (and pytest-homeassistant's own patch_time
    wrapper, which calls ``time.monotonic`` repeatedly on each event-loop
    tick) is not affected. Once installed, the stub's first return establishes
    the flush deadline baseline and every subsequent call is far past it, so
    the deadline check at the top of the loop body breaks before the queued
    write executes — leaving it for the leftover drain.
    """
    from custom_components.universal_room_automation import database as dbmod

    async def _scenario():
        await db.initialize()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        async def _factory(_db):  # pragma: no cover - never reached
            return None

        db._write_queue.put_nowait((_factory, fut))

        state = {"n": 0}

        def _mono():
            state["n"] += 1
            # First call = deadline baseline; everything after is far past it.
            return 0.0 if state["n"] == 1 else 1e9

        monkeypatch.setattr(dbmod.time, "monotonic", _mono)
        try:
            await db._flush_pending_writes()
        finally:
            monkeypatch.undo()
        with pytest.raises(RuntimeError) as excinfo:
            await fut
        return excinfo.value

    return asyncio.get_event_loop().run_until_complete(_scenario())


def test_flush_leftover_outside_shutdown_stays_plain_runtime_error(tmp_path, monkeypatch):
    """B-LOW-1: a worker stop that is NOT an HA stop (config-entry reload,
    VACUUM) and loses writes must fail them with plain RuntimeError, so
    callers keep logging ERROR."""
    db = _make_db(str(tmp_path), is_stopping=False)
    exc = _flush_with_expired_budget(db, monkeypatch)
    assert type(exc) is RuntimeError
    assert not isinstance(exc, _dbshutting_down_cls())


def test_flush_leftover_at_ha_stop_is_db_shutting_down(tmp_path, monkeypatch):
    """B-LOW-1 discriminator: the same leftover at a real HA stop is
    DBShuttingDown (callers log DEBUG)."""
    db = _make_db(str(tmp_path), is_stopping=True)
    exc = _flush_with_expired_budget(db, monkeypatch)
    assert isinstance(exc, _dbshutting_down_cls())


def test_load_baselines_prune_failure_keeps_saves_enabled(tmp_path):
    """A-L2: a non-shutdown failure of the orphan prune must not mark the
    load as failed — the baselines loaded, so saves stay enabled."""
    from custom_components.universal_room_automation.domain_coordinators import (
        coordinator_diagnostics as cdiag,
    )

    db = _make_db(str(tmp_path), is_stopping=False)
    hass = MagicMock()
    hass.data = {cdiag.DOMAIN: {"database": db}}
    det = cdiag.AnomalyDetector(hass, coordinator_id="safety", metric_names=["noise_floor"])
    det.metric_names = ["noise_floor"]

    async def _scenario():
        await db.initialize()
        await db.start_write_worker()
        async with db._db() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO metric_baselines "
                "(coordinator_id, metric_name, scope, mean, variance, "
                "sample_count, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("safety", "deprecated_metric", "all", 1.0, 0.1, 10,
                 "2026-10-13T00:00:00"),
            )
            await conn.commit()

        real_db = db._db

        def _failing_db():
            raise OSError("disk I/O error")

        db._db = _failing_db
        try:
            await det.load_baselines()
        finally:
            db._db = real_db
        assert det._baselines_loaded is True, (
            "a failed orphan prune must not disable baseline saves"
        )
        await db.stop_write_worker()

    asyncio.get_event_loop().run_until_complete(_scenario())
