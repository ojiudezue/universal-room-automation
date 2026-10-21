"""EC-SHUTDOWN-SAVE-AFTER-WRITER-CLOSED-1.

HA does not unload config entries on stop, and Stage 2 cancels URA's DB write
worker (after which ``database._db`` raises ``DBShuttingDown``). The Energy
Coordinator therefore persists its state from a Stage-1 shutdown job
(``hass.async_add_shutdown_job``), bounded by ``EC_STOP_SAVE_TIMEOUT_S``.

Drives the real ``EnergyCoordinator`` methods and the real
``UniversalRoomDatabase`` (schema from production source). Reuses the
sys.modules isolation + real-DB fixtures of ``test_ec_outage_ledger``.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from unittest.mock import AsyncMock

import pytest

import test_ec_outage_ledger as OL
from test_ec_outage_ledger import (  # noqa: F401  (fixtures)
    _real_module_isolation,
    real_db,
    _Hass,
    _FakeDB,
    _make_db,
)

ENERGY_MOD = "custom_components.universal_room_automation.domain_coordinators.energy"
CONST_MOD = (
    "custom_components.universal_room_automation.domain_coordinators.energy_const"
)
DB_MOD = "custom_components.universal_room_automation.database"

_OTHER_SAVES = (
    "_save_evse_state", "_save_circuit_state", "_save_energy_baselines",
    "_save_envoy_cache", "_save_midnight_snapshot", "_save_load_shedding_level",
)


class _ShutdownHass(_Hass):
    """_Hass plus HA's shutdown-job registry (core.py async_add_shutdown_job)."""

    def __init__(self, db=None):
        super().__init__(db)
        self.shutdown_jobs = []
        self.removed = []

    def async_add_shutdown_job(self, hassjob, *args):
        entry = (hassjob, args)
        self.shutdown_jobs.append(entry)

        def _remove():
            self.removed.append(entry)
            self.shutdown_jobs.remove(entry)

        return _remove

    async def run_stage1(self):
        """Mirror core.async_stop Stage 1: call each job with its (empty) args."""
        for job, args in list(self.shutdown_jobs):
            await job.target(*args)


def _shell(hass, peak=None):
    c = OL._CycleShell()
    c.hass = hass
    c._stop_save_unsub = None
    c._stop_persist_done = False
    c._peak_import_history = peak if peak is not None else []
    c.timer_cancels = []
    c._decision_timer_unsub = lambda: c.timer_cancels.append(1)
    for n in _OTHER_SAVES:
        setattr(c, n, AsyncMock())
    return c


def _counts(c):
    return [getattr(c, n).await_count for n in _OTHER_SAVES]


# ---------------------------------------------------------------------------
# Wire-in: async_setup registers the Stage-1 job (enclosing-method anchor)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_setup_registers_stage1_stop_job():
    E = sys.modules[ENERGY_MOD]
    c = OL._CycleShell()
    c.hass = _ShutdownHass(_FakeDB())
    c._decision_timer_unsub = None
    c._stop_save_unsub = None
    c._stop_persist_done = True  # setup must re-arm the latch
    c._solar_follow = None
    c._decision_interval = 5

    async def _restore(now):
        return None

    c._restore_all_sequential = _restore
    c._register_solar_follow_timer = lambda: None
    c._unsub_listeners = []
    c._outage_ledger = None
    c._write_verifier = object()
    c._optimizer_intent_unsub = None

    class _Stop(Exception):
        pass

    def _conn(*a, **k):
        raise _Stop  # first dispatcher subscribe is after the registration

    orig_track, orig_conn = E.async_track_time_interval, E.async_dispatcher_connect
    E.async_track_time_interval = lambda *a, **k: (lambda: None)
    E.async_dispatcher_connect = _conn
    try:
        with pytest.raises(_Stop):
            await c.async_setup()
    finally:
        E.async_track_time_interval = orig_track
        E.async_dispatcher_connect = orig_conn

    assert len(c.hass.shutdown_jobs) == 1
    job, args = c.hass.shutdown_jobs[0]
    assert args == ()  # zero-arg job, like core's job.args
    assert job.target == c._async_persist_on_stop
    assert c._stop_save_unsub is not None
    assert c._stop_persist_done is False


def test_register_is_idempotent_one_job_only():
    c = _shell(_ShutdownHass())
    c._register_stop_save_job()
    c._register_stop_save_job()
    assert len(c.hass.shutdown_jobs) == 1


# ---------------------------------------------------------------------------
# Behaviour: Stage-1 job persists through the real DB while the worker lives
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stage1_job_persists_real_rows_and_stops_timer(real_db):
    hass = _ShutdownHass(real_db)
    c = _shell(hass, peak=[1.5, 2.25, 7.0])
    c._register_stop_save_job()

    await hass.run_stage1()

    assert await real_db.get_peak_import_history() == [1.5, 2.25, 7.0]
    assert _counts(c) == [1] * len(_OTHER_SAVES)
    assert c.timer_cancels == [1]
    assert c._decision_timer_unsub is None


@pytest.mark.asyncio
async def test_same_save_after_worker_closed_lands_nothing(tmp_path):
    """The discriminator: the identical persist run after Stage 2 (worker
    closed, is_stopping) writes no row — why the job must run in Stage 1."""
    db = _make_db(tmp_path)
    assert await db.initialize()
    db.hass.is_stopping = True  # worker never started == cancelled
    c = _shell(_ShutdownHass(db), peak=[4.0])
    await c._async_persist_state()
    db.hass.is_stopping = False
    await db.start_write_worker()
    try:
        assert await db.get_peak_import_history() == []
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_stop_job_then_teardown_does_not_double_write():
    hass = _ShutdownHass(_FakeDB())
    c = _shell(hass)
    for n in ("_solar_follow_timer_unsub", "_solar_follow", "_tou_boundary_unsub",
              "_outage_ledger", "_write_verifier", "_dp_eval_last_task",
              "_optimizer_intent_unsub"):
        setattr(c, n, None)
    c._cancel_listeners = lambda: None
    c._cancel_utility_refresh = lambda: None
    c._register_stop_save_job()

    await hass.run_stage1()
    await c._async_persist_on_stop()  # second call: no-op
    assert _counts(c) == [1] * len(_OTHER_SAVES)

    await c.async_teardown()
    assert _counts(c) == [1] * len(_OTHER_SAVES)
    assert len(hass.removed) == 1 and hass.shutdown_jobs == []
    assert c._stop_save_unsub is None


@pytest.mark.asyncio
async def test_teardown_without_stop_job_still_persists_once():
    """Reload / unload path (no HA stop): teardown keeps persisting."""
    hass = _ShutdownHass(_FakeDB())
    c = _shell(hass)
    for n in ("_solar_follow_timer_unsub", "_solar_follow", "_tou_boundary_unsub",
              "_outage_ledger", "_write_verifier", "_dp_eval_last_task",
              "_optimizer_intent_unsub"):
        setattr(c, n, None)
    c._cancel_listeners = lambda: None
    c._cancel_utility_refresh = lambda: None
    c._register_stop_save_job()

    await c.async_teardown()
    assert _counts(c) == [1] * len(_OTHER_SAVES)
    assert hass.shutdown_jobs == []


# ---------------------------------------------------------------------------
# Bound: a wedged save cannot stall HA Stage 1
# ---------------------------------------------------------------------------
def test_stop_save_timeout_constant_fits_stage1_budget():
    E = sys.modules[ENERGY_MOD]
    assert sys.modules[CONST_MOD].EC_STOP_SAVE_TIMEOUT_S == 10
    assert E.EC_STOP_SAVE_TIMEOUT_S == 10
    assert E.EC_STOP_SAVE_TIMEOUT_S < 20  # HA STOPPING_STAGE_SHUTDOWN_TIMEOUT


@pytest.mark.asyncio
async def test_stop_job_abandons_a_hung_save(monkeypatch, caplog):
    E = sys.modules[ENERGY_MOD]
    monkeypatch.setattr(E, "EC_STOP_SAVE_TIMEOUT_S", 0.05)
    c = _shell(_ShutdownHass(_FakeDB()))

    async def _hang():
        await asyncio.Event().wait()

    c._save_envoy_cache = _hang
    with caplog.at_level(logging.WARNING, logger=E.__name__):
        await asyncio.wait_for(c._async_persist_on_stop(), 2.0)
    assert any("exceeded" in r.getMessage() for r in caplog.records)
    assert c._save_midnight_snapshot.await_count == 0  # abandoned mid-sequence


# ---------------------------------------------------------------------------
# DEBUG downgrade: DBShuttingDown only
# ---------------------------------------------------------------------------
def _dao_calls(db):
    return {
        "save_energy_state": lambda: db.save_energy_state("k", "v"),
        "save_peak_import_history": lambda: db.save_peak_import_history([1.0]),
        "save_evse_state": lambda: db.save_evse_state("evse", True, False),
        "save_circuit_state": lambda: db.save_circuit_state({"c": {"was_loaded": True}}),
        "save_envoy_cache": lambda: db.save_envoy_cache({"soc": 50.0}),
        "save_midnight_snapshot": lambda: db.save_midnight_snapshot({"snapshot_date": "2026-10-20"}),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("dao", [
    "save_energy_state", "save_peak_import_history", "save_evse_state",
    "save_circuit_state", "save_envoy_cache", "save_midnight_snapshot",
])
async def test_dao_shutdown_skip_logs_debug_not_error(tmp_path, caplog, dao):
    db = _make_db(tmp_path)
    assert await db.initialize()
    db.hass.is_stopping = True  # worker not running + stopping => DBShuttingDown
    with caplog.at_level(logging.DEBUG, logger=DB_MOD):
        await _dao_calls(db)[dao]()
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == []
    assert any("skipped: HA shutting down" in r.getMessage()
               and r.levelno == logging.DEBUG for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("dao", [
    "save_energy_state", "save_peak_import_history", "save_evse_state",
    "save_circuit_state", "save_envoy_cache", "save_midnight_snapshot",
])
async def test_dao_other_runtime_error_still_logs_error(tmp_path, caplog, dao):
    db = _make_db(tmp_path)
    assert await db.initialize()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _broken():
        raise RuntimeError("disk on fire")
        yield  # pragma: no cover

    db._db = _broken
    with caplog.at_level(logging.DEBUG, logger=DB_MOD):
        await _dao_calls(db)[dao]()
    assert any(r.levelno == logging.ERROR and "disk on fire" in r.getMessage()
               for r in caplog.records)
