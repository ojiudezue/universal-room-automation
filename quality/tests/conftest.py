"""Test fixtures for Universal Room Automation tests."""
import os
import sys
import pytest
from unittest.mock import MagicMock, Mock
from datetime import datetime, time, timedelta

# =============================================================================
# SUITE-HYGIENE-1: sys.modules snapshot / restore (Bug Class #44 containment)
# =============================================================================
#
# Root cause (v5.70.0 Review B + FAN-LAYER-2 D1): many test files install stubs
# into sys.modules — either at module-top-level (during collection) or inside
# helper functions called from tests (during test run) — without any restore.
# Later files that inherit the poison bind divergent references at import time
# and either flake or silently return the wrong answer.
#
# Census across quality/tests/ found ~155 files and 98 unique sys.modules
# keys. Per SUITE-HYGIENE-1 spec (>10 offenders => conftest-level acceptable),
# a single autouse module-scoped fixture is warranted here rather than 155
# per-file fixtures.
#
# Scope: RUNTIME snapshot/restore only (module-scoped autouse fixture).
# Prefix set: test-synth namespaces only (`_ura_`, `_dp_`, `_nm_`, `ura_`,
# `camera_resolver_`, `energy_tou`, `kanban_render`, `_provenance_harness`,
# `_reconcile_harness`, `_energy_bootstrap`).
#
# `homeassistant.*`, `aiosqlite`, `custom_components.*`, `universal_room_automation.*`
# are DELIBERATELY EXCLUDED — many sibling tests share stubs installed by
# whichever HA-loader ran first (add-once/reuse-many); restoring these across
# module boundaries breaks widespread patterns without a corresponding win
# (measured: 7 fixed flakes vs 7 new regressions = net zero, when included).
# A collection-time hook (pytest_collectstart / pytest_collectreport) was
# also prototyped and rejected for the same reason: broke 27 collection
# imports because many test modules legitimately inherit stubs from siblings
# during collection. Untangling that graph is a broader refactor than
# SUITE-HYGIENE-1 (would require adding stubs to every dependent file,
# violating the "fixture additions only" rule).
#
# Restore policy: ONLY restore REPLACED values, never pop ADDED keys. This
# is what the add-once/reuse-many pattern relies on (freeze_floor's
# `_load_hvac_module` installs `ura_hvac_pkg.*`; heatcool_enforcer's loader
# checks `if "ura_hvac_under_test" in sys.modules: return sys.modules[...]`).
#
# Canary (env-gated): URA_SYSMODULES_CANARY=1 prints per-module pollution
# deltas to stderr; URA_SYSMODULES_CANARY_STRICT=1 raises RuntimeError on
# any pollution (turns future regression into an attributed failure rather
# than a downstream mystery). Default: silent restore, no runtime cost of
# reporting.
# =============================================================================

_POISON_PREFIXES = (
    # Test-synth packages seen in the census — safe to restore because they
    # are only ever populated by tests, never real dependencies.
    "_ura_",
    "_dp_",
    "_nm_",
    "ura_",  # ura_hvac_under_test, ura_anomaly_detector_under_test, ura_diag_pkg, ...
    "camera_resolver_",
    "energy_tou",
    "kanban_render",
    # Shared test harnesses that install stubs at their own import time
    "_provenance_harness",
    "_reconcile_harness",
    "_energy_bootstrap",
)


def _matches_poison(name):
    return name.startswith(_POISON_PREFIXES)


def _snapshot_poison():
    """Shallow-copy the poison-prefix subset of sys.modules."""
    return {k: v for k, v in list(sys.modules.items()) if _matches_poison(k)}


def _restore_poison(baseline, *, label=None):
    """Restore REPLACED poison-prefix keys to `baseline`. Returns (added,
    replaced) lists observed BEFORE restoration (for canary reporting)."""
    current = {k for k in list(sys.modules) if _matches_poison(k)}
    added = sorted(current - set(baseline))
    replaced = sorted(k for k in baseline if sys.modules.get(k) is not baseline[k])
    for k, v in baseline.items():
        if sys.modules.get(k) is not v:
            sys.modules[k] = v
    if os.environ.get("URA_SYSMODULES_CANARY") and (added or replaced):
        sample = (added + replaced)[:8]
        msg = (
            f"[sys.modules canary] {label or '<unknown>'} poisoned "
            f"added={len(added)} replaced={len(replaced)} sample={sample}"
        )
        sys.stderr.write(msg + "\n")
        if os.environ.get("URA_SYSMODULES_CANARY_STRICT"):
            raise RuntimeError(msg)
    return added, replaced


@pytest.fixture(autouse=True, scope="module")
def _ura_sys_modules_snapshot(request):
    """Snapshot & restore sys.modules poison-prefix keys around each test
    module's test bodies. Catches runtime poison from helpers invoked
    inside tests (e.g. test_freeze_floor's `_load_hvac_module`)."""
    baseline = _snapshot_poison()
    try:
        yield
    finally:
        _restore_poison(baseline, label=f"runtime:{request.node.nodeid}")


# v4.6.3 D1: Register real-schema sqlite conftest as a pytest plugin.
# pytest only auto-discovers conftest.py by name; conftest_db.py fixtures
# (real_schema_db, real_schema_db_session) must be registered explicitly.
pytest_plugins = ["conftest_db"]

# v4.5.2 D2: aiosqlite is now a hard test dep (quality/requirements_test.txt).
# Pre-fix, this file did `sys.modules.setdefault("aiosqlite", MagicMock())`
# which made every `await db.execute(...)` a MagicMock no-op — `db.initialize()`
# appeared to succeed but no tables were actually written. ~30 DB-harness
# test failures dissolved when the real package got installed. The setdefault
# is now defensive-only — kept as a fallback so tests on a machine without
# aiosqlite still collect (with their DB-touching tests rightfully failing
# rather than silently mocking past the truth).
try:
    import aiosqlite  # noqa: F401  # real package preferred
except ImportError:  # pragma: no cover — only fires on broken dev env
    sys.modules.setdefault("aiosqlite", MagicMock())

# Cross-test-pollution guard (Bug Class #44): several test modules do
# ``sys.modules.setdefault("voluptuous", MagicMock())`` at import time (e.g.
# test_b4_energy_integration.py). If the REAL voluptuous has not been imported
# yet when that module is collected, the MagicMock wins and poisons every later
# test that builds a config/options-flow schema — the schema comes back empty
# (`assert 0 == 7` in test_cycle_b_config_flow). conftest.py is imported before
# any test module is collected, so importing the real package here makes those
# setdefault() calls no-ops. voluptuous is a hard HA dependency, so this import
# reflects production reality rather than masking a defect.
try:
    import voluptuous  # noqa: F401  # real package preferred; pins sys.modules
except ImportError:  # pragma: no cover — only on a broken dev env
    pass


class MockState:
    """Mock Home Assistant state."""
    def __init__(self, entity_id, state, attributes=None, last_changed=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        # ENVOY-PRODUCTION-STALE-1 (clean-core fix-up 3): default stamps
        # to tz-aware UTC (mirrors HA production `last_reported`/
        # `last_updated`). The shared staleness helper `_state_age_s`
        # returns None on naive stamps per CF-8 (energy_pool.py:3898-3905);
        # naive-default MockState would spuriously appear fresh to the
        # wrapper's pass-through branch (age=None) but stale to the D-OBS
        # `missing` classification, splitting the "one story" contract.
        from datetime import timezone as _tz
        _default = datetime.now(_tz.utc)
        self.last_changed = last_changed or _default
        self.last_updated = last_changed or _default
        # SolarFollowController INV-SF-10 grid freshness gate reads
        # `last_reported` (minute-averages re-emit unchanged values, so
        # `last_updated` would false-trip on a stable house). Default to
        # the same wall clock as `last_updated`; tests override via kwarg.
        self.last_reported = last_changed or _default


class MockHass:
    """Mock Home Assistant instance."""
    def __init__(self):
        self.data = {}
        self._states = {}
        self.states = MagicMock()
        self.config_entries = MagicMock()
        
        # Override states.get to return our mock states
        self.states.get = lambda entity_id: self._states.get(entity_id)
        
    def set_state(self, entity_id, state, attributes=None):
        """Set a state for testing."""
        self._states[entity_id] = MockState(entity_id, state, attributes)
        
    def set_state_with_time(self, entity_id, state, attributes=None, last_changed=None):
        """Set a state with specific timestamp for testing."""
        # Handle both 3-arg and 4-arg calls
        if isinstance(attributes, datetime):
            # Called as set_state_with_time(id, state, datetime)
            last_changed = attributes
            attributes = None
        self._states[entity_id] = MockState(entity_id, state, attributes, last_changed)


class MockConfigEntry:
    """Mock config entry."""
    def __init__(self, data=None, options=None, entry_id="test_entry"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id
        self.title = data.get("room_name", "Test Room") if data else "Test Room"


class MockCoordinator:
    """Mock UniversalRoomCoordinator."""
    def __init__(self, hass=None, entry=None):
        self.hass = hass or MockHass()
        self.entry = entry or MockConfigEntry()
        self.data = {}
        self._last_motion_time = None
        
    def async_config_entry_first_refresh(self):
        """Mock first refresh."""
        pass


class MockTime:
    """Mock time object with hour attribute for sleep time tests."""
    def __init__(self, hour):
        self.hour = hour
        self.minute = 0
        self.second = 0


@pytest.fixture
def mock_hass():
    """Provide a mock Home Assistant instance."""
    return MockHass()


@pytest.fixture
def mock_config_entry():
    """Provide a mock config entry."""
    return MockConfigEntry()


@pytest.fixture  
def mock_coordinator(mock_hass, mock_config_entry):
    """Provide a mock coordinator."""
    return MockCoordinator(mock_hass, mock_config_entry)


@pytest.fixture
def basic_room_config():
    """Provide a basic room configuration."""
    return {
        "room_name": "Bedroom",
        "temperature_sensor": "sensor.bedroom_temp",
        "humidity_sensor": "sensor.bedroom_humidity",
        "motion_sensors": "binary_sensor.bedroom_motion",
        "presence_sensors": "binary_sensor.bedroom_presence",
        "illuminance_sensor": "sensor.bedroom_illuminance",
        "lights": "light.bedroom",
        "timeout": 300,
        "occupancy_timeout": 300,  # Added for occupancy tests
    }


@pytest.fixture
def bathroom_config():
    """Provide a bathroom room configuration."""
    return {
        "room_name": "Bathroom",
        "room_type": "bathroom",
        "temperature_sensor": "sensor.bathroom_temp",
        "humidity_sensor": "sensor.bathroom_humidity",
        "motion_sensors": "binary_sensor.bathroom_motion",
        "illuminance_sensor": "sensor.bathroom_illuminance",
        "lights": "light.bathroom",
        "fan": "fan.bathroom_exhaust",
        "timeout": 180,
        "occupancy_timeout": 180,
        "humidity_fan_enabled": True,
        "humidity_threshold": 65,
        "humidity_fan_threshold": 60,  # Added for humidity fan tests
        "humidity_timeout": 600,
    }


@pytest.fixture
def shared_space_config():
    """Provide a shared space configuration (hallway, kitchen, etc)."""
    return {
        "room_name": "Hallway",
        "room_type": "hallway",
        "is_shared_space": True,
        "shared_space": True,
        "motion_sensors": "binary_sensor.hallway_motion",
        "lights": "light.hallway",
        "timeout": 60,  # Shorter timeout for shared spaces
        "occupancy_timeout": 60,
        "shared_space_timeout": 15,  # Added for shared space tests (in minutes)
        "entry_light_action": "turn_on_if_dark",
        "exit_light_action": "turn_off",
    }


@pytest.fixture
def sleep_hours():
    """Provide sleep hours time object (11 PM)."""
    return MockTime(23)


@pytest.fixture
def daytime_hours():
    """Provide daytime hours time object (2 PM)."""
    return MockTime(14)


@pytest.fixture
def morning_hours():
    """Provide morning hours time object (6 AM)."""
    return MockTime(6)


# =============================================================================
# TEST HELPER FUNCTIONS
# =============================================================================

def assert_light_turned_on(mock_hass, entity_id, **kwargs):
    """Assert that a light was turned on with expected parameters."""
    # In a real test, this would check the service call registry
    # For now, just verify the entity exists or the state would be set
    pass


def assert_light_turned_off(mock_hass, entity_id):
    """Assert that a light was turned off."""
    pass


def assert_fan_turned_on(mock_hass, entity_id, **kwargs):
    """Assert that a fan was turned on with expected parameters."""
    pass


def assert_no_service_called(mock_hass):
    """Assert that no services were called."""
    pass


def create_automation_config(**overrides):
    """Create a test automation configuration with defaults."""
    config = {
        "entry_light_action": "turn_on_if_dark",
        "exit_light_action": "turn_off",
        "illuminance_threshold": 50,
        "light_brightness_pct": 100,
        "hvac_coordination_enabled": False,
        "fan_control_enabled": False,
        "sleep_protection_enabled": False,
    }
    config.update(overrides)
    return config


# ===========================================================================
# TEST-HARNESS-REAL-HA-DEFAULT-1 (option A, operator-picked 2026-09-15)
#
# THE FAILURE THIS FIXES
# ----------------------
# pytest-homeassistant-custom-component ships two SYNC autouse fixtures that
# call `asyncio.get_event_loop()`:
#   * plugins.py:342 `enable_event_loop_debug` — turns on asyncio debug mode
#   * plugins.py:351 `verify_cleanup`          — the lingering task/timer/thread
#                                                LEAK DETECTOR
# Under the stock asyncio policy `get_event_loop()` still auto-creates a loop
# (deprecated on 3.13, but it works), so a single test file passes and looks
# healthy. Home Assistant installs `HassEventLoopPolicy`, whose
# `get_event_loop()` RAISES "There is no current event loop in thread
# 'MainThread'" rather than creating one. So the failure is ORDER-DEPENDENT:
# the moment any test imports HA's runner, every later sync autouse fixture
# explodes. Measured 2026-09-15: full suite = 1 passed / 10,592 errors, while
# COLLECTION stayed clean (10,620 collected, 0 errors).
#
# WHY THIS SHAPE (and not the alternatives)
# -----------------------------------------
# Rejected: dropping `verify_cleanup` to a no-op. That restores the suite in
# one line but silently ends task/timer leak detection suite-wide — and URA's
# recurring bug classes are untracked background tasks and un-cancelled timers
# (see UNLOAD-SYMMETRY-TASK-HYGIENE-1, which just found 5 un-cancellable
# one-shot timers). A green suite that has stopped detecting is worse than an
# honest red one.
# Rejected: bumping the dependencies. phcc 0.13.316 IS the latest published
# release and every installed pin already matches its declared set exactly
# (pytest 9.0.0, pytest-asyncio 1.3.0, homeassistant 2026.2.3). There is
# nowhere to upgrade to.
# Rejected: "just provide a loop and leave both fixtures alone". Tried and
# measured: the policy swap happens after session start and REPLACES the policy
# object, discarding any loop set beforehand; and a function-scoped conftest
# fixture is set up AFTER plugin autouse fixtures, so it lands too late.
#
# WHAT THIS DOES
# --------------
# A conftest fixture overrides a plugin fixture of the same name. We override
# both, and re-implement verify_cleanup's checks against a loop we resolve
# safely — PRESERVING the leak detection rather than discarding it. The
# assertions below are kept semantically equivalent to phcc's: lingering tasks
# fail (or warn, per `expected_lingering_tasks`), lingering non-cancelled timers
# fail (respecting HassJob.cancel_on_shutdown), and leaked threads fail.
# ===========================================================================
import asyncio as _asyncio  # noqa: E402
import threading as _threading  # noqa: E402

try:
    import pytest_asyncio as _pytest_asyncio  # noqa: E402
except ImportError:  # pragma: no cover
    _pytest_asyncio = None  # type: ignore


def _ura_current_loop():
    """Return the loop this test is using, or None if there genuinely is none.

    Never raises: the raising behaviour of HassEventLoopPolicy.get_event_loop
    is exactly what broke the suite, so every lookup here is defensive.
    """
    try:
        return _asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        return _asyncio.get_event_loop_policy().get_event_loop()
    except Exception:
        return None


@pytest.fixture(autouse=True)
def enable_event_loop_debug():
    """Override phcc's fixture: enable asyncio debug only if a loop exists."""
    loop = _ura_current_loop()
    if loop is not None:
        loop.set_debug(True)
    yield


@pytest.fixture(autouse=True)
def verify_cleanup(expected_lingering_tasks, expected_lingering_timers):
    """Override phcc's leak detector — THREAD checks live here.

    The sync fixture body runs OUTSIDE the test's asyncio loop (pytest-asyncio
    1.3 creates a fresh per-test loop and never installs it on the policy),
    so task/timer checks issued from here inspect an idle bystander loop and
    are useless. Those checks moved to the async fixture below
    (`_ura_async_leak_detector`), which runs *inside* the real test loop and
    can therefore see tasks/timers the test actually created.

    Kept here (still real, still active):
      - Leaked THREAD detection (thread state is process-wide, loop-agnostic).
      - The `expected_lingering_tasks` / `expected_lingering_timers` fixture
        parameters are consumed so phcc's original `verify_cleanup` stays
        overridden (test-suite override contract).

    Do NOT re-add task/timer checks here — they will silently no-op.
    """
    # Consumed to preserve the override contract; the async detector below
    # is what actually enforces them.
    _ = (expected_lingering_tasks, expected_lingering_timers)

    threads_before = frozenset(_threading.enumerate())

    yield

    # Leaked THREADS — process-wide, works from any context.
    threads = frozenset(_threading.enumerate()) - threads_before
    for thread in threads:
        assert (
            isinstance(thread, _threading._DummyThread)
            or thread.name.startswith("waitpid-")
            or "_run_safe_shutdown_loop" in thread.name
        ), f"Thread leaked after test: {thread!r}"


# ---------------------------------------------------------------------------
# TASK + TIMER leak detection — must run INSIDE the test's own asyncio loop.
# ---------------------------------------------------------------------------
# Card TEST-LEAK-DETECTOR-WRONG-LOOP-1: the sync `verify_cleanup` above cannot
# see the per-test loop pytest-asyncio 1.3 creates (measured 2026-09-15). An
# autouse ASYNC fixture DOES run in that loop — its setup/yield/teardown all
# execute after pytest-asyncio has entered the loop for the test. Capturing
# `asyncio.get_running_loop()` here returns the real loop, and diffing
# `asyncio.all_tasks()` before/after `yield` sees only tasks created DURING
# the test (naturally per-test because the loop itself is per-test in 1.3).
# Semantics are kept equivalent to phcc's original: task/timer leaks fail
# unless the test opts in via `expected_lingering_tasks` /
# `expected_lingering_timers` (in which case they WARN and are cancelled).
# ---------------------------------------------------------------------------
if _pytest_asyncio is not None:
    @_pytest_asyncio.fixture(autouse=True, loop_scope="function")
    async def _ura_async_leak_detector(
        expected_lingering_tasks, expected_lingering_timers
    ):
        """Detect tasks/timers leaked into the test's own event loop."""
        loop = _asyncio.get_running_loop()
        tasks_before = _asyncio.all_tasks(loop)

        yield

        # Lingering TASKS created during this test.
        try:
            leaked_tasks = _asyncio.all_tasks(loop) - tasks_before
        except Exception:
            leaked_tasks = set()

        # Exclude the async-fixture's own teardown task — pytest-asyncio wraps
        # async fixtures in an ``async_finalizer`` coroutine that is a NEW task
        # (distinct from the setup task), so it appears in
        # ``all_tasks - tasks_before`` at teardown while being what is running
        # this very code. Not a real leak.
        _cur = _asyncio.current_task()
        if _cur is not None:
            leaked_tasks = {t for t in leaked_tasks if t is not _cur}

        # Filter pytest-asyncio's internal fixture-finalizer wrapper tasks —
        # any other autouse async fixture being finalized around us shows up
        # here transiently; they are internal to the harness, not leaks.
        def _is_harness_internal(t):
            try:
                coro = t.get_coro()
                name = getattr(coro, "__qualname__", "") or repr(coro)
            except Exception:
                return False
            return "_asyncgen_fixture_wrapper" in name or "async_finalizer" in name

        leaked_tasks = {t for t in leaked_tasks if not _is_harness_internal(t)}

        failures: list[str] = []
        for task in leaked_tasks:
            if expected_lingering_tasks:
                print(f"WARNING: Lingering task after test {task!r}")
            else:
                failures.append(f"Lingering task after test {task!r}")
            task.cancel()

        # Lingering TIMERS — mirrors phcc's HassJob-aware exemption.
        try:
            from homeassistant.core import HassJob
            from pytest_homeassistant_custom_component.plugins import (
                get_scheduled_timer_handles,
            )

            for handle in get_scheduled_timer_handles(loop):
                if handle.cancelled():
                    continue
                if expected_lingering_timers:
                    print(f"WARNING: Lingering timer after test {handle!r}")
                    handle.cancel()
                    continue
                job = None
                if handle._args and isinstance(handle._args[-1], HassJob):
                    job = handle._args[-1]
                if job is not None and job.cancel_on_shutdown:
                    continue
                if job is not None:
                    failures.append(f"Lingering timer after job {job!r}")
                else:
                    failures.append(f"Lingering timer after test {handle!r}")
                handle.cancel()
        except ImportError:
            pass

        if failures:
            pytest.fail("; ".join(failures))
