"""EC-DB-RESTORE-TIMEOUT-1 — per-step boot restore timeouts + one late retry.

Was: ONE asyncio.wait_for(15 s) around the whole 14-step restore chain, so a
stall in step N cancelled steps N+1..14 (today's import/cost reset to 0).
Now: each step has its own timeout (EC_RESTORE_STEP_TIMEOUT_S, clipped to the
remaining EC_RESTORE_TOTAL_BUDGET_S), skipped steps land in
``_restore_skipped`` and the retry-safe ones are re-run once after HA start.

Bug classes guarded: #53 computed-but-not-consumed (``_restore_skipped`` must
drive the retry; the async_setup wire-in is anchored), untracked background
listener (retry handle cancelled on teardown).

Drives the real EnergyCoordinator methods bound onto a namespace shell; the
restore steps themselves are replaced by recorders (their bodies have their
own tests). Oracles are hand-written literals.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from _energy_bootstrap import bootstrap_energy_imports  # noqa: E402

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as em,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_billing as eb,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_tou as et,
)

STEP_METHODS = (
    "_restore_cycle_from_db", "_restore_accuracy_from_db",
    "_restore_peak_import_history", "_fit_temp_regression",
    "_restore_evse_state", "_restore_circuit_state",
    "_restore_energy_baselines", "_restore_consumption_history",
    "_restore_power_profiles", "_restore_midnight_snapshot",
    "_restore_envoy_cache", "_restore_load_shedding_level",
    "_restore_solar_follow_state", "_restore_bill_forecast_ledger",
)
STEP_NAMES = [
    "cycle", "accuracy", "peak_import", "temp_regression", "evse", "circuit",
    "energy_baselines", "consumption_history", "power_profiles",
    "midnight_snapshot", "envoy_cache", "load_shedding_level",
    "solar_follow_state", "bill_forecast_ledger",
]


class _Bus:
    def __init__(self):
        self.listeners = []
        self.unsubbed = 0

    def async_listen_once(self, event_type, cb):
        self.listeners.append((event_type, cb))

        def _unsub():
            self.unsubbed += 1
        return _unsub


class _Hass:
    def __init__(self, running=False, db=None):
        self.is_running = running
        self.bus = _Bus()
        self.tasks = []
        self.data = {"universal_room_automation": {"database": db}}

    def async_create_task(self, coro):
        task = asyncio.get_event_loop().create_task(coro)
        self.tasks.append(task)
        return task


def _bind(s, *names):
    for n in names:
        setattr(s, n, getattr(em.EnergyCoordinator, n).__get__(s))


def _shell(hang=(), running=False, db=None):
    """Namespace shell; each restore step records its call, `hang` never return."""
    s = types.SimpleNamespace()
    s.hass = _Hass(running=running, db=db)
    s._unsub_listeners = []
    s._peak_import_history = []
    s._bill_ledger_ready = False
    s.calls = []
    s._RESTORE_RETRY_SAFE = em.EnergyCoordinator._RESTORE_RETRY_SAFE
    for meth, name in zip(STEP_METHODS, STEP_NAMES):
        def _mk(name=name):
            async def _step(*a, **k):
                s.calls.append(name)
                if name in hang:
                    await asyncio.Event().wait()
            return _step
        setattr(s, meth, _mk())
    _bind(s, "_restore_all_sequential", "_restore_steps",
          "_schedule_restore_retry", "_retry_skipped_restores",
          "_reseed_cycle_after_boot", "_cancel_listeners")
    return s


def _live_const():
    """The energy_const module the production `from .energy_const import`
    resolves right now (another file's sys.modules reload can make the
    module-level `ec` stale)."""
    import importlib
    pkg = em.EnergyCoordinator._restore_all_sequential.__globals__["__package__"]
    return importlib.import_module(pkg + ".energy_const")


def _set_budgets(monkeypatch, step, total):
    mod = _live_const()
    monkeypatch.setattr(mod, "EC_RESTORE_STEP_TIMEOUT_S", step)
    monkeypatch.setattr(mod, "EC_RESTORE_TOTAL_BUDGET_S", total)


@pytest.fixture
def fast_budgets(monkeypatch):
    _set_budgets(monkeypatch, 0.05, 5.0)


# ---------------------------------------------------------------------------
# Per-step timeout
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hung_step_does_not_skip_later_steps(fast_budgets):
    s = _shell(hang=("evse",))
    await asyncio.wait_for(s._restore_all_sequential(None), timeout=3)
    assert s.calls == STEP_NAMES  # every step reached, in order
    assert s._restore_skipped == ["evse"]


@pytest.mark.asyncio
async def test_no_hang_no_skips(fast_budgets):
    s = _shell()
    await s._restore_all_sequential(None)
    assert s.calls == STEP_NAMES
    assert s._restore_skipped == []


@pytest.mark.asyncio
async def test_skipped_list_is_reset_each_pass(fast_budgets):
    s = _shell()
    s._restore_skipped = ["stale"]
    await s._restore_all_sequential(None)
    assert s._restore_skipped == []


@pytest.mark.asyncio
async def test_total_budget_skips_tail_without_running_it(monkeypatch, caplog):
    # step 0.1 s, budget 0.15 s: first hang uses 0.1, second is clipped to
    # ~0.05, then the budget is spent and the rest are not run at all.
    _set_budgets(monkeypatch, 0.1, 0.15)
    s = _shell(hang=("cycle", "accuracy"))
    import logging
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(s._restore_all_sequential(None), timeout=3)
    assert s.calls == ["cycle", "accuracy"]
    assert s._restore_skipped == STEP_NAMES
    # Budget-skipped steps are named as such (not reported as timeouts).
    budget_msgs = [r.getMessage() for r in caplog.records
                   if "total budget" in r.getMessage()]
    assert len(budget_msgs) == 12
    assert "'peak_import'" in budget_msgs[0]


@pytest.mark.asyncio
async def test_step_timeout_clipped_to_remaining_budget(monkeypatch):
    # Step timeout 10 s but total budget 0.1 s: the hung first step must be
    # cut at ~0.1 s (clip), not 10 s; everything after is budget-skipped.
    _set_budgets(monkeypatch, 10.0, 0.1)
    s = _shell(hang=("cycle",))
    await asyncio.wait_for(s._restore_all_sequential(None), timeout=3)
    assert s.calls == ["cycle"]
    assert s._restore_skipped == STEP_NAMES


@pytest.mark.asyncio
async def test_step_timeout_is_per_step_not_whole_chain(monkeypatch):
    # Every step takes 0.05 s; step budget 0.3 s (6x margin); chain total
    # 0.7 s > 0.3. A single whole-chain timeout of 0.3 would skip the tail.
    _set_budgets(monkeypatch, 0.3, 5.0)
    s = _shell()
    for meth, name in zip(STEP_METHODS, STEP_NAMES):
        async def _slow(*a, name=name, **k):
            await asyncio.sleep(0.05)
            s.calls.append(name)
        setattr(s, meth, _slow)
    await s._restore_all_sequential(None)
    assert s.calls == STEP_NAMES
    assert s._restore_skipped == []


# ---------------------------------------------------------------------------
# Wire-in: async_setup runs the per-step chain and arms the retry
# ---------------------------------------------------------------------------
class _Stop(Exception):
    pass


async def _drive_setup(s, monkeypatch):
    s._decision_timer_unsub = None
    s._solar_follow = None
    s._decision_interval = 5
    s._async_decision_cycle = None  # only passed to the (patched) tracker
    s._handle_safety_hazard = None  # only passed to the raising connect
    s._register_stop_save_job = lambda: None
    s._register_solar_follow_timer = lambda: None
    _bind(s, "async_setup")

    def _conn(*a, **k):
        raise _Stop  # first dispatcher subscribe comes after restore + retry arm

    # Patch the globals the bound function actually resolves (another test
    # file's sys.modules isolation can leave `em` != the defining module).
    g = em.EnergyCoordinator.async_setup.__globals__
    monkeypatch.setitem(g, "async_track_time_interval", lambda *a, **k: (lambda: None))
    monkeypatch.setitem(g, "async_dispatcher_connect", _conn)
    with pytest.raises(_Stop):
        await asyncio.wait_for(s.async_setup(), timeout=3)


@pytest.mark.asyncio
async def test_async_setup_hung_step_runs_rest_and_arms_retry(fast_budgets, monkeypatch):
    s = _shell(hang=("evse",))
    await _drive_setup(s, monkeypatch)
    assert s.calls == STEP_NAMES
    assert s._restore_skipped == ["evse"]
    assert [e for e, _ in s.hass.bus.listeners] == ["homeassistant_started"]
    assert len(s._unsub_listeners) == 1


@pytest.mark.asyncio
async def test_async_setup_clean_restore_arms_nothing(fast_budgets, monkeypatch):
    s = _shell()
    await _drive_setup(s, monkeypatch)
    assert s.hass.bus.listeners == []
    assert s._unsub_listeners == []


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_reruns_only_skipped_retry_safe_steps(fast_budgets):
    s = _shell()
    s._restore_skipped = ["accuracy", "evse", "midnight_snapshot",
                          "consumption_history"]
    await s._retry_skipped_restores("test")
    assert s.calls == ["accuracy", "consumption_history"]
    assert s._restore_skipped == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    "evse", "circuit", "midnight_snapshot", "envoy_cache",
    "load_shedding_level", "solar_follow_state",
])
async def test_boot_only_steps_never_retried(fast_budgets, name):
    s = _shell()
    s._restore_skipped = [name]
    await s._retry_skipped_restores("test")
    assert s.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    "accuracy", "temp_regression", "energy_baselines",
    "consumption_history", "power_profiles", "bill_forecast_ledger",
    "peak_import",
])
async def test_retry_safe_steps_are_retried(fast_budgets, name):
    s = _shell()
    s._restore_skipped = [name]
    await s._retry_skipped_restores("test")
    assert s.calls == [name]


@pytest.mark.asyncio
async def test_retry_peak_import_skipped_when_readings_accrued(fast_budgets):
    s = _shell()
    s._peak_import_history = [3.2]
    s._restore_skipped = ["peak_import"]
    await s._retry_skipped_restores("test")
    assert s.calls == []
    assert s._peak_import_history == [3.2]


@pytest.mark.asyncio
async def test_retry_ledger_skipped_when_already_loaded(fast_budgets):
    s = _shell()
    s._bill_ledger_ready = True
    s._restore_skipped = ["bill_forecast_ledger"]
    await s._retry_skipped_restores("test")
    assert s.calls == []


@pytest.mark.asyncio
async def test_retry_step_hanging_again_is_bounded(fast_budgets):
    s = _shell(hang=("accuracy",))
    s._restore_skipped = ["accuracy", "power_profiles"]
    await asyncio.wait_for(s._retry_skipped_restores("test"), timeout=3)
    assert s.calls == ["accuracy", "power_profiles"]


class _CycleDB:
    def __init__(self, data):
        self.data = data
        self.args = None

    async def get_energy_daily_for_cycle(self, start, end):
        self.args = (start, end)
        return self.data


@pytest.mark.asyncio
async def test_cycle_retry_keeps_since_boot_accrual(fast_budgets):
    """Late cycle restore = DB full days + today so far (reseed), not a
    plain overwrite that would drop what accrued since boot."""
    db = _CycleDB({"days": 5, "import_kwh": 100.0, "export_kwh": 20.0,
                   "net_cost": 40.0})
    s = _shell(db=db)
    s._billing = eb.CostTracker(types.SimpleNamespace(), et.TOURateEngine(), 24)
    # Since boot (cycle step was skipped): accumulators started at 0.
    s._billing._import_kwh_today = 3.0
    s._billing._export_kwh_today = 1.0
    s._billing._cost_today = 1.5
    s._billing._import_kwh_cycle = 3.0
    s._billing._export_kwh_cycle = 1.0
    s._billing._cost_this_cycle = 1.5
    s._restore_skipped = ["cycle"]
    await s._retry_skipped_restores("test")
    assert s.calls == []  # the boot variant (update_from_db) is NOT used
    assert s._billing._cost_this_cycle == pytest.approx(41.5)
    assert s._billing._import_kwh_cycle == pytest.approx(103.0)
    assert s._billing._export_kwh_cycle == pytest.approx(21.0)
    assert s._billing._db_days_in_cycle == 5
    # Keyed, so the next _check_cycle_reset does not zero the reseed.
    assert s._billing._cycle_start_date == db.args[0]
    from homeassistant.util import dt as dt_util
    s._billing._check_cycle_reset(dt_util.now())
    assert s._billing._cost_this_cycle == pytest.approx(41.5)


# ---------------------------------------------------------------------------
# Scheduling: started event, reload path, teardown
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_started_event_runs_retry_once(fast_budgets):
    s = _shell()
    s._restore_skipped = ["power_profiles"]
    s._schedule_restore_retry()
    assert s.calls == []  # nothing until HA has started
    assert len(s.hass.bus.listeners) == 1
    event_type, cb = s.hass.bus.listeners[0]
    assert event_type == "homeassistant_started"
    await cb(None)
    assert s.calls == ["power_profiles"]
    await cb(None)  # list cleared: a second fire re-runs nothing
    assert s.calls == ["power_profiles"]


@pytest.mark.asyncio
async def test_teardown_unsubscribes_started_listener(fast_budgets):
    s = _shell()
    s._restore_skipped = ["power_profiles"]
    s._schedule_restore_retry()
    s._cancel_listeners()
    assert s.hass.bus.unsubbed == 1
    assert s._unsub_listeners == []


@pytest.mark.asyncio
async def test_reload_path_runs_retry_as_tracked_task(fast_budgets):
    s = _shell(running=True)
    s._restore_skipped = ["accuracy"]
    s._schedule_restore_retry()
    assert s.hass.bus.listeners == []
    assert len(s.hass.tasks) == 1 and len(s._unsub_listeners) == 1
    await s.hass.tasks[0]
    assert s.calls == ["accuracy"]


@pytest.mark.asyncio
async def test_reload_task_cancelled_on_teardown(fast_budgets):
    s = _shell(running=True)
    s._restore_skipped = ["accuracy"]
    s._schedule_restore_retry()
    s._cancel_listeners()
    with pytest.raises(asyncio.CancelledError):
        await s.hass.tasks[0]
    assert s.calls == []


def test_constants_are_rung1_values():
    assert _live_const().EC_RESTORE_STEP_TIMEOUT_S == 10.0
    assert _live_const().EC_RESTORE_TOTAL_BUDGET_S == 45.0
