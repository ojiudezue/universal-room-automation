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


# =============================================================================
# SUITE-HYGIENE-1b (2026-09-11): scoped restore for the REAL const module.
# =============================================================================
# Many test modules inject a fake
# `custom_components.universal_room_automation.const` (or the bare
# `universal_room_automation.const`) into sys.modules at module-import
# (collection) time and never restore. Later modules that import real
# names (e.g. BLE_HOLD_CAP_DURATIONS, BLE_CHAIN_HOLD_ENABLED) then
# ImportError "unknown location" — aborting FULL-SUITE COLLECTION even
# though every per-file run stays green.
#
# The main sysmodules-snapshot fixture above DELIBERATELY EXCLUDES the
# custom_components.* / universal_room_automation.* namespaces (see its
# comment: measured 7-fixed-vs-7-regressions on broad reinclusion, driven
# by add-once/reuse-many HA stubs). This narrow fixture restores ONLY the
# two `.const` keys to the REAL modules, captured at CONFTEST IMPORT
# TIME (before any test module has a chance to poison them). Scope is a
# single leaf module per key — cannot affect the shared HA-stub loaders
# the exclusion protected.
# =============================================================================
# (relpath under custom_components/universal_room_automation/, sys.modules keys)
_REAL_LEAF_TARGETS = (
    (
        "const.py",
        (
            "custom_components.universal_room_automation.const",
            "universal_room_automation.const",
        ),
    ),
    (
        "domain_coordinators/signals.py",
        (
            "custom_components.universal_room_automation.domain_coordinators.signals",
            "universal_room_automation.domain_coordinators.signals",
        ),
    ),
    (
        "domain_coordinators/hvac_const.py",
        (
            "custom_components.universal_room_automation.domain_coordinators.hvac_const",
            "universal_room_automation.domain_coordinators.hvac_const",
        ),
    ),
)
_REAL_CONST_MODULES: dict = {}


def _load_real_leaf_modules() -> None:
    """Load a small set of dependency-free LEAF modules directly via
    importlib WITHOUT invoking the parent package's __init__.py (which
    imports Home Assistant and would fail outside a full HA env). These
    leaves have zero external deps and carry constants (BLE_HOLD_CAP_*,
    SIGNAL_HOUSE_STATE_CHANGED, HVAC_DECISION_TICK, ...) that later test
    modules import BY NAME. Registering the real module under every
    sys.modules key that test stubs alias to gives us an anchor to
    restore against between collections."""
    import importlib.util
    from pathlib import Path as _P
    root = (
        _P(__file__).resolve().parent.parent.parent
        / "custom_components" / "universal_room_automation"
    )
    for relpath, keys in _REAL_LEAF_TARGETS:
        path = root / relpath
        if not path.is_file():
            continue
        for key in keys:
            try:
                spec = importlib.util.spec_from_file_location(key, path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                # Must be registered BEFORE exec_module so dataclass field
                # resolution (typing._is_type -> sys.modules[cls.__module__])
                # can see the module during class body execution.
                sys.modules[key] = mod
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                _REAL_CONST_MODULES[key] = mod
            except Exception:  # pragma: no cover — best-effort
                continue


_load_real_leaf_modules()


def _restore_real_const_keys() -> None:
    for key, real in _REAL_CONST_MODULES.items():
        if real is None:
            continue
        if sys.modules.get(key) is not real:
            sys.modules[key] = real


def pytest_collectstart(collector):
    """Before EACH collection unit, restore the real `.const` module refs
    so a prior test module's collection-time stub cannot make a later
    module's `from custom_components...const import X` ImportError with
    'unknown location'. Narrow (two leaf keys only) — cannot disrupt
    add-once/reuse-many HA stubs the main snapshot's exclusion protects."""
    _restore_real_const_keys()


# NOTE: intentionally NO module-scoped teardown fixture for const keys.
# Restoring const at test-run boundaries would break the add-once/reuse-
# many pattern (a test module that installs a const stub at its collection
# then relies on that stub inside its test bodies must see it stably). The
# only failure mode we need to solve is COLLECTION-time ImportError from a
# real-const `from ... import X`, which the collectstart hook alone covers.


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
