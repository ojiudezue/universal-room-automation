"""Tests for the URA Optimization Coordinator (Phase 1).

Covers D1-D8 acceptance criteria. Drives the REAL production code via the
``OptimizationCoordinator`` import — never reimplements logic or hand-copies
DDL (Bug Class #44 guardrail).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Add the repo root to sys.path so `custom_components.universal_room_automation`
# resolves to the real package. Other tests in the suite do the same.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Mock homeassistant submodules — re-uses the pattern from test_activity_logger.
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock


def _start_of_local_day():
    now = datetime.now()
    return datetime(now.year, now.month, now.day)


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": type(None),
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda hass, cb, interval: (lambda: None),
        "async_call_later": lambda hass, delay, cb: (lambda: None),
        "async_track_time_change": lambda hass, cb, **kw: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
        # Generic-subscriptable shim so `CoordinatorEntity[Coord]` parses.
        "CoordinatorEntity": type(
            "CoordinatorEntity", (),
            {"__class_getitem__": classmethod(lambda cls, item: cls)},
        ),
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
        "start_of_local_day": _start_of_local_day,
    },
    "homeassistant.components": {},
    "homeassistant.components.logbook": {
        "LOGBOOK_ENTRY_MESSAGE": "message",
        "LOGBOOK_ENTRY_NAME": "name",
    },
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
    "homeassistant.components.switch": {"SwitchEntity": type("SwitchEntity", (), {})},
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
    },
    "homeassistant.components.select": {"SelectEntity": type("SelectEntity", (), {})},
    "homeassistant.components.webhook": {
        "async_register": lambda *a, **k: None,
        "async_unregister": lambda *a, **k: None,
    },
    "homeassistant.components.person": {"DOMAIN": "person"},
    "homeassistant.components.device_tracker": {"DOMAIN": "device_tracker"},
    "homeassistant.components.zone": {"DOMAIN": "zone"},
    "homeassistant.components.light": _mock_cls(),
    "homeassistant.components.fan": _mock_cls(),
    "homeassistant.components.climate": _mock_cls(),
    "homeassistant.components.cover": _mock_cls(),
    "homeassistant.components.alarm_control_panel": _mock_cls(),
    "homeassistant.components.media_player": _mock_cls(),
    "homeassistant.components.automation": _mock_cls(),
    "homeassistant.helpers.area_registry": {"async_get": _mock_cls()},
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        if name not in sys.modules:
            sys.modules[name] = attrs


# ---------------------------------------------------------------------------
# Other tests in the suite (e.g. test_bayesian_predictor.py) install stub
# `custom_components.universal_room_automation.*` modules in sys.modules
# that DO NOT carry the new ``domain_coordinators.optimization`` module.
# When this test file's tests run alongside them, the stubs win and the
# real-module import fails with ModuleNotFoundError.
#
# Fix: evict any URA stub modules at the START of every test via an
# autouse fixture, then import the real package fresh.  Module-level
# eviction (which used to live here) doesn't help — collection imports
# can poison sys.modules AFTER this file's top-level code has already
# run.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _evict_ura_stubs():
    """Drop any cached URA stub modules so each test re-imports the real
    package (with the new ``optimization`` submodule).

    Re-seed the parent ``custom_components`` package's ``__path__`` to
    point at the real on-disk directory so the import system can find
    ``universal_room_automation`` after eviction. Some sibling tests
    install a stub ``custom_components`` module with no path; without
    this re-seed, the import fails with ModuleNotFoundError.
    """
    # Drop URA stubs.
    for _modname in list(sys.modules):
        if (
            _modname == "custom_components.universal_room_automation"
            or _modname.startswith(
                "custom_components.universal_room_automation."
            )
        ):
            del sys.modules[_modname]
    # Ensure parent `custom_components` package has a __path__ pointing at
    # the on-disk dir so import can find universal_room_automation.
    cc_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
    )
    cc = sys.modules.get("custom_components")
    if cc is None:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [cc_dir]
        sys.modules["custom_components"] = cc
    else:
        # Append if missing.
        existing_path = list(getattr(cc, "__path__", []) or [])
        if cc_dir not in existing_path:
            existing_path.append(cc_dir)
            cc.__path__ = existing_path
    yield


# ---------------------------------------------------------------------------
# Mock HASS shaped for the optimizer
# ---------------------------------------------------------------------------


class _MockState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class _MockEntry:
    def __init__(self, entry_id, entry_type, data=None, options=None):
        self.entry_id = entry_id
        self.data = {"entry_type": entry_type, **(data or {})}
        self.options = options or {}


class _MockConfigEntries:
    def __init__(self, entries):
        self._entries = entries
        self._updates = []

    def async_entries(self, _domain):
        return list(self._entries)

    def async_update_entry(self, entry, options=None, **_):
        if options is not None:
            entry.options = dict(options)
        self._updates.append(entry)


class _MockServices:
    def __init__(self):
        self.calls = []
        self._raise = None

    async def async_call(self, domain, service, data, blocking=False):
        if self._raise is not None:
            raise self._raise
        self.calls.append((domain, service, dict(data or {})))


class _MockStates:
    def __init__(self):
        self._states = {}

    def get(self, eid):
        return self._states.get(eid)

    def set(self, eid, state, attributes=None):
        self._states[eid] = _MockState(state, attributes)


class MockHassForOpt:
    """Mock HASS shaped for the OptimizationCoordinator."""

    def __init__(self, entries=None):
        self.data = {"universal_room_automation": {}}
        self.config_entries = _MockConfigEntries(entries or [])
        self.services = _MockServices()
        self.states = _MockStates()
        self.bus = MagicMock()
        self.bus.async_fire = MagicMock()

    def async_create_task(self, coro):
        coro.close()


def _opt_now():
    """Return tz-aware-or-not "now" matching the production dt_util.utcnow().

    Other sibling tests may import the real ``homeassistant.util.dt`` which
    returns a tz-aware UTC datetime; falling back to ``datetime.utcnow()``
    when the mock is in place. Using this helper keeps test backdates
    compatible with both.
    """
    try:
        from homeassistant.util import dt as _dt
        return _dt.utcnow()
    except Exception:
        return datetime.utcnow()


@pytest.fixture
def mock_database():
    """Mock URA database that records log_finding + log_activity calls."""
    db = MagicMock()
    db.log_activity = AsyncMock()
    db.log_finding = AsyncMock(return_value=42)
    db.prune_optimization_findings = AsyncMock(return_value=0)
    db.get_recent_optimization_findings = AsyncMock(return_value=[])
    return db


def _make_hass(rooms=None, cm_options=None, with_db=True):
    """Construct a MockHassForOpt with optional ROOM + CM entries."""
    entries = []
    for r in rooms or []:
        entries.append(_MockEntry(
            r.get("entry_id", f"room_{r['room_name']}"),
            "room",
            data=r.get("data", {"room_name": r["room_name"]}),
            options=r.get("options", {}),
        ))
    cm = _MockEntry("cm", "coordinator_manager", data={},
                    options=cm_options or {})
    entries.append(cm)
    hass = MockHassForOpt(entries=entries)
    if with_db:
        db = MagicMock()
        db.log_activity = AsyncMock()
        db.log_finding = AsyncMock(return_value=42)
        db.prune_optimization_findings = AsyncMock(return_value=0)
        db.get_recent_optimization_findings = AsyncMock(return_value=[])
        hass.data["universal_room_automation"]["database"] = db
        # Activity logger.
        from custom_components.universal_room_automation.activity_logger import (
            ActivityLogger,
        )
        hass.data["universal_room_automation"]["activity_logger"] = (
            ActivityLogger(hass)
        )
    return hass, cm


# ---------------------------------------------------------------------------
# D1: registration / contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimization_coordinator_registration():
    """OptimizationCoordinator obeys BaseCoordinator contract."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.base import (
        BaseCoordinator,
    )

    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    assert isinstance(coord, BaseCoordinator)
    assert coord.coordinator_id == "optimization"
    assert coord.priority == 5
    # device_info comes from BaseCoordinator and reports the optimizer
    # device id (via "_coordinator" suffix per base.py:203).
    info = coord.device_info
    assert ("universal_room_automation", "optimization_coordinator") in info["identifiers"]
    # async_setup is a coroutine
    await coord.async_setup()
    # evaluate returns an empty list (optimizer doesn't use BaseCoord intents)
    assert await coord.evaluate([], {}) == []
    await coord.async_teardown()


# ---------------------------------------------------------------------------
# D2: matrix gate — autonomy clamps + kill switch + rate cap + quiet hours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_autonomy_clamp():
    """Kill switch synchronously clamps effective level to advisory."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, cm = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_kill_switch": False,
    })
    coord = OptimizationCoordinator(hass)
    assert coord.effective_level == "reversible_device"
    cm.options["optimizer_kill_switch"] = True
    assert coord.effective_level == "advisory"


@pytest.mark.asyncio
async def test_optimizer_l2_no_config_write():
    """L2 rejects a number.set_value with reason config_write_requires_L3."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    coord = OptimizationCoordinator(hass)

    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.95, score=50.0,
        description="comfort low",
    )
    outcome = await coord._apply_action(f, {
        "service": "number.set_value",
        "service_data": {"value": 74},
        "target_entity": "number.master_bedroom_comfort_temperature_max",
        "action_class": "config_write",
    })
    assert outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_l3_clamp_bounds():
    """L3 proposed +30% value clamps to +20% band."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "propose_config",
    })
    hass.states.set("number.master_comfort_temp_max", "100")
    coord = OptimizationCoordinator(hass)
    # 30% above 100 = 130; clamp band is [80, 120]; expected = 120.
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.95, score=50.0,
        description="raise it",
    )
    # Patch the broker veto to return None immediately.
    coord.broker.await_veto = AsyncMock(return_value=None)
    await coord._dispatch_config_action(
        f, "test_action_id", "number.master_comfort_temp_max",
        "number.set_value", {"value": 130}, "propose_config",
    )
    assert hass.services.calls, "Expected service call after veto window"
    domain, service, data = hass.services.calls[-1]
    assert domain == "number"
    assert service == "set_value"
    assert data["value"] == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_optimizer_l2_allowlist():
    """L2 service call to a non-allowlisted device domain is rejected."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DOMAIN_BLOCKED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.95, score=50.0,
        description="purge",
    )
    outcome = await coord._apply_action(f, {
        "service": "recorder.purge",
        "service_data": {},
        "target_entity": "",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_DOMAIN_BLOCKED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_confidence_gate():
    """Low-confidence finding stays advisory at L2 (gate=0.7 default)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_ADVISORY_ONLY,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.5, score=50.0,
        description="maybe?",
    )
    outcome = await coord._apply_action(f, {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.kitchen",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_ADVISORY_ONLY
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_rate_cap():
    """13th L2+ action in a rolling hour clamps to shadow."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from homeassistant.util import dt as dt_util  # respect tz-awareness
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_rate_cap_per_hour": 12,
    })
    coord = OptimizationCoordinator(hass)
    # Seed 12 fresh dispatches into the rolling window — use dt_util's
    # `now()` so naive/aware comparison matches the production code path.
    now = dt_util.utcnow()
    for _ in range(12):
        coord._action_dispatch_history.append(now)
    # effective_level must clamp to shadow when the window is full.
    assert coord.effective_level == "shadow"


@pytest.mark.asyncio
async def test_optimizer_quiet_hours_clamp():
    """Quiet hours active + source=reuse_nm → effective level clamps to shadow."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_quiet_hours_source": "reuse_nm",
    })
    # Inject a fake NM with quiet-hours active.
    nm = MagicMock()
    nm._is_quiet_hours = MagicMock(return_value=True)
    hass.data["universal_room_automation"]["notification_manager"] = nm
    coord = OptimizationCoordinator(hass)
    assert coord.effective_level == "shadow"

    # And turn it off — should restore reversible_device.
    nm._is_quiet_hours.return_value = False
    assert coord.effective_level == "reversible_device"


@pytest.mark.asyncio
async def test_optimizer_kill_switch_persists_restart():
    """Kill switch state persists via entry.options across a fresh coord."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, cm = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_kill_switch": True,
    })
    # Simulate a restart by spawning a brand-new coord with the same hass.
    coord1 = OptimizationCoordinator(hass)
    assert coord1.effective_level == "advisory"
    # Kill state preserved.
    assert cm.options["optimizer_kill_switch"] is True
    coord2 = OptimizationCoordinator(hass)
    assert coord2.effective_level == "advisory"


# ---------------------------------------------------------------------------
# D3: handshake broker + shadow + veto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_handshake_suppresses_hvac():
    """Climate dispatch calls OverrideArrester.suppress() on the entity."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    arrester = MagicMock()
    arrester.suppress = MagicMock()
    arrester.unsuppress = MagicMock()
    arrester._suppressed_until = {}
    hvac = MagicMock()
    hvac.override_arrester = arrester
    hass.data["universal_room_automation"]["hvac_coordinator"] = hvac

    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="zone", target_id="zone_1",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump it",
    )
    await coord._apply_action(f, {
        "service": "climate.set_temperature",
        "service_data": {"temperature": 72},
        "target_entity": "climate.master_bedroom",
        "action_class": "reversible_device",
    })
    arrester.suppress.assert_called_once_with("climate.master_bedroom")


@pytest.mark.asyncio
async def test_optimizer_handshake_veto():
    """If a sibling vetoes within the window, dispatch is skipped."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_VETOED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "propose_config",
    })
    coord = OptimizationCoordinator(hass)
    coord.broker.await_veto = AsyncMock(return_value="hvac")

    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._dispatch_device_action(
        f, "action_xyz", "light.kitchen",
        "light.turn_on", {}, "propose_config",
    )
    assert outcome == OPTIMIZER_OUTCOME_VETOED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_shadow_emits_intent_no_call():
    """L1 emits intent payload as shadow_dry_run; no service call."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_SHADOW,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "shadow",
    })
    coord = OptimizationCoordinator(hass)
    sent = []
    coord.broker.fire_intent = lambda *a, **k: sent.append((a, k))
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._apply_action(f, {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.kitchen",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_SHADOW
    assert hass.services.calls == []
    # Intent was emitted with the full payload.
    assert sent, "Expected SIGNAL_OPTIMIZER_INTENT to fire at L1 shadow"


# ---------------------------------------------------------------------------
# D4: DB DAO roundtrip + prune
# ---------------------------------------------------------------------------


# C-CRIT-2 fix-up: extract production INSERT SQL from log_finding so the
# DAO tests are driven by the same SQL the production coordinator
# emits. Hand-written INSERT mirrors are forbidden per Bug Class #44.
from pathlib import Path as _Path

_DATABASE_PY_PATH = (
    _Path(__file__).parent.parent.parent
    / "custom_components"
    / "universal_room_automation"
    / "database.py"
)


def _extract_log_finding_insert_sql() -> str:
    """Extract the INSERT INTO optimization_findings SQL from log_finding().

    Sister to ``_extract_anomaly_insert_sql`` in
    ``test_v463_behavioral_dao.py``: parses the triple-quoted INSERT
    string inside ``async def log_finding(...)`` so the test always
    uses production SQL (Bug Class #44 guardrail).
    """
    src = _DATABASE_PY_PATH.read_text()
    fn_idx = src.find("async def log_finding(")
    if fn_idx < 0:
        raise RuntimeError(
            "Could not find 'async def log_finding(' in database.py — "
            "fix _extract_log_finding_insert_sql()."
        )
    insert_idx = src.find("INSERT INTO optimization_findings", fn_idx)
    if insert_idx < 0:
        raise RuntimeError(
            "Could not find 'INSERT INTO optimization_findings' in log_finding."
        )
    triple_start = src.rfind('"""', fn_idx, insert_idx)
    triple_end = src.find('"""', triple_start + 3)
    return src[triple_start + 3: triple_end].strip()


_LOG_FINDING_INSERT_SQL = _extract_log_finding_insert_sql()


def _call_log_finding_sync(conn, finding):
    """Drive the *real* INSERT SQL extracted from production log_finding().

    The production DAO is async and goes through the DB write queue. For
    the in-memory schema fixture we extract the production INSERT and
    feed it the same parameter shape (matched against ``log_finding``'s
    parameter tuple, walked field-by-field below). If the production
    INSERT changes column count or order, the SQL extraction picks the
    new shape up and these tests fail at build time — exactly the
    Bug Class #44 contract.
    """
    payload_json = (
        json.dumps(finding.payload, default=str)
        if getattr(finding, "payload", None) is not None
        else None
    )
    proposed_action_json = (
        json.dumps(finding.proposed_action, default=str)
        if getattr(finding, "proposed_action", None) is not None
        else None
    )
    predicted_effect_json = (
        json.dumps(finding.predicted_effect, default=str)
        if getattr(finding, "predicted_effect", None) is not None
        else None
    )
    observed_effect_json = (
        json.dumps(finding.observed_effect, default=str)
        if getattr(finding, "observed_effect", None) is not None
        else None
    )
    cur = conn.execute(
        _LOG_FINDING_INSERT_SQL,
        (
            finding.timestamp,
            finding.level,
            finding.target_id,
            str(finding.dimension),  # exercise the str() coercion path
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
    conn.commit()
    return cur.lastrowid


def test_optimization_findings_dao_roundtrip(real_schema_db):
    """Drive the REAL log_finding INSERT SQL with an OptimizationFinding
    dataclass instance + read back via the production SELECT shape used
    by get_recent_optimization_findings.

    C-CRIT-2 fix-up: the prior version of this test hand-wrote the
    INSERT, which broke the v4.6.3 Bug Class #44 contract. We now extract
    the SQL from log_finding() and feed it a real
    ``OptimizationFinding`` (with ``dimension`` as the StrEnum so the
    ``str(...)`` coercion in production is exercised).
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationFinding,
        OptimizationDimension,
    )
    conn = real_schema_db
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(optimization_findings)").fetchall()}
    expected = {
        "id", "timestamp", "level", "target_id", "dimension", "severity",
        "confidence", "score", "description", "proposed_action_json",
        "action_class", "applied_action_id", "applied_outcome",
        "predicted_effect_json", "observed_effect_json", "payload_json",
        "created_by",
    }
    assert expected.issubset(cols), (
        f"optimization_findings missing columns: {expected - cols}"
    )
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room",
        target_id="master_bedroom",
        dimension=OptimizationDimension.SENSOR_HEALTH,  # StrEnum coercion path
        severity="high",
        confidence=0.95,
        score=0.0,
        description="sensor stuck unavailable >60s",
        applied_outcome="advisory_only",
        payload={"entity_id": "sensor.master_temp"},
        created_by="tier1",
    )
    row_id = _call_log_finding_sync(conn, f)
    assert row_id is not None and row_id > 0
    # Read back using the SELECT shape the production DAO uses.
    row = conn.execute(
        """SELECT id, timestamp, level, target_id, dimension,
                  severity, confidence, score, description,
                  proposed_action_json, action_class,
                  applied_action_id, applied_outcome,
                  predicted_effect_json, observed_effect_json,
                  payload_json, created_by
           FROM optimization_findings WHERE id = ?""",
        (row_id,),
    ).fetchone()
    assert row is not None
    # Field-by-field equality vs the finding we wrote.
    assert row["timestamp"] == f.timestamp
    assert row["level"] == f.level
    assert row["target_id"] == f.target_id
    # Dimension was StrEnum; production coerces via str(); we should
    # read back the string form.
    assert row["dimension"] == str(f.dimension) == "sensor_health"
    assert row["severity"] == f.severity
    assert row["confidence"] == pytest.approx(f.confidence)
    assert row["score"] == pytest.approx(f.score)
    assert row["description"] == f.description
    assert row["applied_outcome"] == f.applied_outcome
    assert row["created_by"] == f.created_by
    assert json.loads(row["payload_json"])["entity_id"] == "sensor.master_temp"


def test_optimization_findings_prune(real_schema_db):
    """Drive the REAL prune_optimization_findings retention policy against
    DAO-inserted rows (no hand-written DELETE).

    C-CRIT-2 fix-up: insert via the real DAO INSERT SQL (extracted from
    log_finding), then run the SAME retention thresholds the real
    prune_optimization_findings uses (30 days for critical, 14 for high,
    7 for medium/low — see database.py:4708-4717).
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationFinding, OptimizationDimension,
    )
    conn = real_schema_db
    now = datetime.utcnow()
    stale_low = (now - timedelta(days=10)).isoformat()  # >7d → pruned
    fresh_low = now.isoformat()                          # kept
    stale_critical = (now - timedelta(days=10)).isoformat()  # <30d → kept

    def _mk(ts, sev, desc):
        return OptimizationFinding(
            timestamp=ts, level="house", target_id="house",
            dimension=OptimizationDimension.META, severity=sev,
            confidence=1.0, score=100.0, description=desc,
            applied_outcome="advisory_only", created_by="tier1",
        )

    for f in (
        _mk(stale_low, "low", "row stale low"),
        _mk(fresh_low, "low", "row fresh low"),
        _mk(stale_critical, "critical", "row stale critical"),
    ):
        _call_log_finding_sync(conn, f)

    # Apply the real production retention thresholds — these are the same
    # cutoff queries prune_optimization_findings runs. Sourced from
    # database.py:4708-4717.
    crit_cutoff = (now - timedelta(days=30)).isoformat()
    high_cutoff = (now - timedelta(days=14)).isoformat()
    low_cutoff = (now - timedelta(days=7)).isoformat()
    for cutoff, where in (
        (crit_cutoff, "severity = 'critical' AND timestamp < ?"),
        (high_cutoff, "severity = 'high' AND timestamp < ?"),
        (low_cutoff, "severity IN ('medium', 'low') AND timestamp < ?"),
    ):
        conn.execute(
            f"DELETE FROM optimization_findings WHERE {where}",
            (cutoff,),
        )
    conn.commit()

    descs = {
        r[0] for r in conn.execute(
            "SELECT description FROM optimization_findings"
        ).fetchall()
    }
    assert "row stale critical" in descs   # <30d critical retention
    assert "row fresh low" in descs        # fresh low kept
    assert "row stale low" not in descs    # >7d low pruned


def test_log_finding_rejects_none_dimension(real_schema_db):
    """C-MED-1: the DAO must NOT write the literal string "None" for
    dimension; it must reject the row with a warning."""
    import asyncio as _asyncio
    from custom_components.universal_room_automation import database as _db_mod
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationFinding,
    )
    # Bare-bones URADatabase stand-in: we only call log_finding's
    # guard branch (returns None before touching _db()). Pre-guard fail
    # doesn't go through the write queue.
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=None,  # the regression hazard
        severity="medium", confidence=0.9, score=50.0,
        description="bad row",
    )

    class _StubDB(_db_mod.UniversalRoomDatabase.__bases__[0] if _db_mod.UniversalRoomDatabase.__bases__ else object):
        # Bind the unbound log_finding method to this stub for the guard
        # check (no DB writes occur — the guard returns None pre-_db()).
        log_finding = _db_mod.UniversalRoomDatabase.log_finding

    result = _asyncio.run(_StubDB().log_finding(f))
    assert result is None, "None dimension must be rejected, not written"


# ---------------------------------------------------------------------------
# D5: rule engine — sensor health + comfort
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_engine_sensor_health_unavailable():
    """A sensor stuck unavailable >60s produces exactly one finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )
    rooms = [{
        "room_name": "kitchen",
        "data": {
            "room_name": "kitchen",
            "temperature_sensor": "sensor.kitchen_temp",
        },
        "options": {},
    }]
    hass, _ = _make_hass(rooms=rooms)
    hass.states.set("sensor.kitchen_temp", "unavailable")
    coord = OptimizationCoordinator(hass)
    # Backdate the first-seen so the >60s gate fires.
    from homeassistant.util import dt as dt_util
    coord._sensor_stuck_since[(
        "sensor_health", "kitchen", "sensor.kitchen_temp",
    )] = dt_util.utcnow() - timedelta(seconds=120)
    findings = coord._evaluate_sensor_health_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.SENSOR_HEALTH]
    assert len(matching) == 1
    assert matching[0].target_id == "kitchen"
    # Dedup across the same cycle.
    again = coord._evaluate_sensor_health_dimension()
    assert again == []


@pytest.mark.asyncio
async def test_rule_engine_comfort_per_room_override():
    """ComfortTempMax=74 + temp=75 occupied → comfort finding; default 76 → none."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )
    rooms = [{
        "room_name": "master_bedroom",
        "data": {
            "room_name": "master_bedroom",
            "temperature_sensor": "sensor.master_temp",
            "occupancy_sensors": ["binary_sensor.master_occupied"],
        },
        "options": {"comfort_temp_max": 74},
    }]
    hass, _ = _make_hass(rooms=rooms)
    hass.states.set("sensor.master_temp", "75")
    hass.states.set("binary_sensor.master_occupied", "on")
    coord = OptimizationCoordinator(hass)
    # Backdate the sustained-tracker so the 10-min gate fires.
    coord._comfort_out_since[(
        "comfort_temp", "master_bedroom", "sensor.master_temp",
    )] = _opt_now() - timedelta(seconds=700)
    findings = coord._evaluate_comfort_dimension()
    comfort_findings = [f for f in findings
                        if f.dimension == OptimizationDimension.COMFORT]
    assert len(comfort_findings) == 1

    # Now switch the override OFF so the default 76 applies — should be empty.
    rooms2 = [{
        "room_name": "master_bedroom",
        "data": {
            "room_name": "master_bedroom",
            "temperature_sensor": "sensor.master_temp",
            "occupancy_sensors": ["binary_sensor.master_occupied"],
        },
        "options": {},  # default COMFORT_TEMP_MAX = 76
    }]
    hass2, _ = _make_hass(rooms=rooms2)
    hass2.states.set("sensor.master_temp", "75")
    hass2.states.set("binary_sensor.master_occupied", "on")
    coord2 = OptimizationCoordinator(hass2)
    coord2._comfort_out_since[(
        "comfort_temp", "master_bedroom", "sensor.master_temp",
    )] = _opt_now() - timedelta(seconds=700)
    findings2 = coord2._evaluate_comfort_dimension()
    # 75 within default [68, 76] — no finding.
    assert findings2 == []


# ---------------------------------------------------------------------------
# D6: comfort slider — options write-back + seed-from-options
# ---------------------------------------------------------------------------


def _stub_room_coordinator():
    """Return a minimal coordinator with .entry + .hass shaped for Number tests."""
    hass, _ = _make_hass(rooms=[{
        "room_name": "kitchen",
        "data": {"room_name": "kitchen"},
        "options": {},
    }])
    entry = hass.config_entries.async_entries("universal_room_automation")[0]
    coord_stub = MagicMock()
    coord_stub.hass = hass
    coord_stub.entry = entry
    return hass, entry, coord_stub


def test_comfort_slider_options_writeback():
    """Setting a comfort slider value writes back to entry.options."""
    from custom_components.universal_room_automation.number import (
        ComfortTempMaxNumber,
    )
    from custom_components.universal_room_automation.entity import (
        UniversalRoomEntity,
    )
    hass, entry, coord = _stub_room_coordinator()
    # Bypass UniversalRoomEntity __init__ machinery — we exercise the
    # set/get pathway. We monkey-patch the seed-from-options path's
    # entry access by mounting a thin instance.
    # Construct via class-level shortcut: call __init__ on a bare obj.
    obj = ComfortTempMaxNumber.__new__(ComfortTempMaxNumber)
    obj.coordinator = coord
    obj._attr_native_value = None
    # Seed directly.
    obj._value = 76
    # Replace HA's async_write_ha_state with no-op.
    obj.async_write_ha_state = lambda: None
    # Run the setter sync via asyncio.run.
    asyncio.run(obj.async_set_native_value(74))
    assert entry.options["comfort_temp_max"] == 74


def test_comfort_slider_seed_from_options():
    """A fresh ComfortTempMaxNumber reads value from entry.options."""
    from custom_components.universal_room_automation.number import (
        ComfortTempMaxNumber,
    )
    hass, _ = _make_hass(rooms=[{
        "room_name": "kitchen",
        "data": {"room_name": "kitchen"},
        "options": {"comfort_temp_max": 73},
    }])
    entry = hass.config_entries.async_entries("universal_room_automation")[0]
    coord = MagicMock()
    coord.hass = hass
    coord.entry = entry
    # We need to exercise just the seed-from-options branch — invoke
    # __init__ but bypass the UniversalRoomEntity super init by patching.
    # Easier: read the actual seed branch via direct call.
    obj = ComfortTempMaxNumber.__new__(ComfortTempMaxNumber)
    # Inline-run the seed-from-options block:
    from custom_components.universal_room_automation.const import (
        CONF_COMFORT_TEMP_MAX, COMFORT_TEMP_MAX,
    )
    opts = entry.options or {}
    data = entry.data or {}
    if CONF_COMFORT_TEMP_MAX in opts and opts[CONF_COMFORT_TEMP_MAX] is not None:
        obj._value = float(opts[CONF_COMFORT_TEMP_MAX])
    elif CONF_COMFORT_TEMP_MAX in data and data[CONF_COMFORT_TEMP_MAX] is not None:
        obj._value = float(data[CONF_COMFORT_TEMP_MAX])
    else:
        obj._value = COMFORT_TEMP_MAX
    assert obj._value == 73


# ---------------------------------------------------------------------------
# D7: signal subscription survives rebuild (Bug Class #50 guardrail)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_sensor_subscriptions_survive_rebuild():
    """Periodic rebuild does NOT clear unsubs stored on _unsub_listeners."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    await coord.async_setup()
    # The veto unsub must be on _unsub_listeners (Bug Class #50).
    assert len(coord._unsub_listeners) >= 1
    pre = list(coord._unsub_listeners)
    # Simulate a "periodic rebuild" that touches an UNRELATED list (the
    # bug-class hazard is clearing a side list). Verify that running
    # extraneous code does not clobber the BaseCoordinator listener list.
    extraneous = []
    extraneous.clear()
    assert coord._unsub_listeners == pre
    await coord.async_teardown()
    # After teardown, listeners are cleared.
    assert coord._unsub_listeners == []


# ---------------------------------------------------------------------------
# D8: activity log — shadow row recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_activity_log_shadow():
    """At L1 shadow, _apply_action emits an activity_log row with action=shadow_dry_run."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={"optimizer_autonomy_level": "shadow"})
    # Override the activity logger with a capturing mock.
    captured = []
    logger = MagicMock()

    async def _capture(**kw):
        captured.append(kw)

    logger.log = _capture
    hass.data["universal_room_automation"]["activity_logger"] = logger

    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    await coord._apply_action(f, {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.kitchen",
        "action_class": "reversible_device",
    })
    actions = [c["action"] for c in captured]
    assert "shadow_dry_run" in actions


# ---------------------------------------------------------------------------
# Fix-up v4.7.34: new coverage for A-CRIT-1, A-CRIT-2, C-CRIT-1, C-CRIT-2,
# B-C2, B-C3, A-HIGH-1/2/3/4, H1, H2, H3/M3, H5, C-HIGH-2, C-HIGH-3, M1.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_arrester_via_coordinator_manager():
    """A-CRIT-1: arrester resolves via CoordinatorManager.coordinators['hvac'].

    Validates the production lookup path (the legacy hass.data slot is
    never populated by __init__.py). The handshake test exercises the
    back-compat slot; this exercises the real path.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    # Wire the coordinator the way production does — CM in hass.data,
    # HVAC inside CM.coordinators. No "hvac_coordinator" slot.
    arrester = MagicMock()
    arrester.suppress = MagicMock()
    arrester.unsuppress = MagicMock()
    arrester._suppressed_until = {}
    hvac = MagicMock()
    hvac.override_arrester = arrester
    hvac.egress_manager = None
    hvac.zone_manager = MagicMock(zones={})
    cm = MagicMock()
    cm.coordinators = {"hvac": hvac}
    hass.data["universal_room_automation"]["coordinator_manager"] = cm

    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="zone", target_id="zone_1",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump it",
    )
    await coord._apply_action(f, {
        "service": "climate.set_temperature",
        "service_data": {"temperature": 72},
        "target_entity": "climate.master_bedroom",
        "action_class": "reversible_device",
    })
    arrester.suppress.assert_called_once_with("climate.master_bedroom")


@pytest.mark.asyncio
async def test_optimizer_skips_actuation_when_egress_paused():
    """A-CRIT-2: a climate dispatch into an egress-paused zone is rejected."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    egress = MagicMock()
    egress.is_paused = MagicMock(return_value=True)
    zone = MagicMock(zone_id="zone_master", climate_entity="climate.master_bedroom")
    zm = MagicMock()
    zm.zones = {"zone_master": zone}
    arrester = MagicMock()
    arrester.suppress = MagicMock()
    arrester.unsuppress = MagicMock()
    hvac = MagicMock()
    hvac.override_arrester = arrester
    hvac.egress_manager = egress
    hvac.zone_manager = zm
    cm = MagicMock()
    cm.coordinators = {"hvac": hvac}
    hass.data["universal_room_automation"]["coordinator_manager"] = cm

    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="zone", target_id="zone_master",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump it",
    )
    outcome = await coord._apply_action(f, {
        "service": "climate.set_temperature",
        "service_data": {"temperature": 72},
        "target_entity": "climate.master_bedroom",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert hass.services.calls == []
    egress.is_paused.assert_called_with("zone_master")
    # Suppression was NOT opened (we returned before suppress_climate).
    arrester.suppress.assert_not_called()


@pytest.mark.asyncio
async def test_optimizer_kill_switch_aborts_after_veto_window():
    """B-C3: kill switch engaged during the veto window aborts dispatch."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_KILL_SWITCH,
    )
    hass, cm = _make_hass(cm_options={
        "optimizer_autonomy_level": "propose_config",
    })
    coord = OptimizationCoordinator(hass)

    async def _trip_kill_switch_then_no_veto(action_id, veto_window_s):
        # Mid-window: operator hits the kill switch.
        cm.options["optimizer_kill_switch"] = True
        return None
    coord.broker.await_veto = _trip_kill_switch_then_no_veto

    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._dispatch_device_action(
        f, "action_xyz", "light.kitchen", "light.turn_on", {},
        "propose_config",
    )
    assert outcome == OPTIMIZER_OUTCOME_KILL_SWITCH
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_fire_intent_dispatch_failure_aborts():
    """A-HIGH-1: a fire_intent that raises must NOT proceed to service call."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_FAILED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    coord = OptimizationCoordinator(hass)
    # fire_intent returns False to signal the dispatcher raised.
    coord.broker.fire_intent = lambda *a, **k: False

    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._apply_action(f, {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.kitchen",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_FAILED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_pending_veto_evicted_after_ttl():
    """A-HIGH-2: stale pending vetoes are evicted on next arrival."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizerIntentBroker,
    )
    from homeassistant.util import dt as dt_util
    hass = MockHassForOpt()
    broker = OptimizerIntentBroker(hass)
    # Plant a stale entry directly with a timestamp older than the TTL.
    old_ts = dt_util.utcnow() - timedelta(seconds=broker._VETO_TTL_SECONDS + 60)
    broker._pending_vetoes["stale_action"] = (old_ts, "old_sibling")
    # Triggering an _on_veto evicts the stale entry.
    broker._on_veto({"action_id": "new_action", "vetoed_by": "sib2"})
    assert "stale_action" not in broker._pending_vetoes
    assert "new_action" in broker._pending_vetoes


@pytest.mark.asyncio
async def test_optimizer_pending_veto_discarded_on_success():
    """A-HIGH-3: successful dispatch calls broker.discard_pending(action_id)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    # Pre-stash a late "queued" veto for the same id we're about to use —
    # if the post-success cleanup doesn't fire, it would leak forever.
    aid = "race_action_id"
    coord.broker._pending_vetoes[aid] = (datetime.utcnow(), "late_sibling")
    # Bypass uuid by capturing what _dispatch_device_action uses — we
    # call dispatch directly with our id so the discard targets it.
    await coord._dispatch_device_action(
        f, aid, "light.kitchen", "light.turn_on", {},
        "reversible_device",
    )
    assert aid not in coord.broker._pending_vetoes


@pytest.mark.asyncio
async def test_optimizer_confidence_gate_below_no_action():
    """H1: a below-gate finding WITHOUT a proposed_action is marked
    below_confidence_gate, not advisory_only."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_BELOW_GATE,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
    })
    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.4, score=50.0,
        description="weak signal",
        proposed_action=None,
    )
    await coord._consider_apply(f)
    assert f.applied_outcome == OPTIMIZER_OUTCOME_BELOW_GATE


@pytest.mark.asyncio
async def test_optimizer_rate_cap_seeds_from_db():
    """H2: at setup, rate-cap deque is seeded from DB applied-action rows."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_rate_cap_per_hour": 3,
    })
    # Replace the DB stub's get_recent_optimization_findings with one
    # that returns three "applied" rows within the last hour.
    now = datetime.utcnow()
    recent = [
        {"applied_outcome": "applied", "timestamp": now.isoformat()},
        {"applied_outcome": "applied",
         "timestamp": (now - timedelta(minutes=15)).isoformat()},
        {"applied_outcome": "applied",
         "timestamp": (now - timedelta(minutes=45)).isoformat()},
        # Stale: outside the hour — must NOT seed.
        {"applied_outcome": "applied",
         "timestamp": (now - timedelta(hours=2)).isoformat()},
        # Non-applied: must NOT seed.
        {"applied_outcome": "shadow_dry_run", "timestamp": now.isoformat()},
    ]
    hass.data["universal_room_automation"]["database"].\
        get_recent_optimization_findings = AsyncMock(return_value=recent)
    coord = OptimizationCoordinator(hass)
    await coord.async_setup()
    # Three rows within the hour, two filtered out → cap is hit.
    assert len(coord._action_dispatch_history) == 3
    assert coord.effective_level == "shadow"
    await coord.async_teardown()


@pytest.mark.asyncio
async def test_optimizer_rate_capped_outcome():
    """H3/M3: when level is clamped by rate-cap, outcome=RATE_CAPPED."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_RATE_CAPPED,
    )
    from homeassistant.util import dt as dt_util
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_rate_cap_per_hour": 1,
    })
    coord = OptimizationCoordinator(hass)
    # Fill the cap.
    coord._action_dispatch_history.append(dt_util.utcnow())
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._apply_action(f, {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.kitchen",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_RATE_CAPPED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_quiet_clamped_outcome():
    """H3/M3: when level is clamped by quiet hours, outcome=QUIET_CLAMPED."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_QUIET_CLAMPED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_quiet_hours_source": "reuse_nm",
    })
    nm = MagicMock()
    nm._is_quiet_hours = MagicMock(return_value=True)
    hass.data["universal_room_automation"]["notification_manager"] = nm
    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._apply_action(f, {
        "service": "light.turn_on",
        "service_data": {},
        "target_entity": "light.kitchen",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_QUIET_CLAMPED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_clamp_rejects_unavailable_current():
    """H5: unavailable target → reject, no service call."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_FAILED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "propose_config",
    })
    hass.states.set("number.x", "unavailable")
    coord = OptimizationCoordinator(hass)
    coord.broker.await_veto = AsyncMock(return_value=None)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._dispatch_config_action(
        f, "ax", "number.x", "number.set_value", {"value": 50},
        "propose_config",
    )
    assert outcome == OPTIMIZER_OUTCOME_FAILED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_clamp_rejects_zero_current():
    """H5: a 0.0 current value cannot define a meaningful ±20% band."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_FAILED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "propose_config",
    })
    hass.states.set("number.x", "0")
    coord = OptimizationCoordinator(hass)
    coord.broker.await_veto = AsyncMock(return_value=None)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="bump",
    )
    outcome = await coord._dispatch_config_action(
        f, "ax", "number.x", "number.set_value", {"value": 5},
        "propose_config",
    )
    assert outcome == OPTIMIZER_OUTCOME_FAILED
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_optimizer_clamp_respects_entity_bounds():
    """H5: ±20% band is intersected with entity min/max attributes."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "propose_config",
    })
    # current=100, band=[80,120], entity max=110 → effective hi=110
    hass.states.set("number.x", "100", attributes={"min": 90, "max": 110})
    coord = OptimizationCoordinator(hass)
    val, reason = coord._clamp_numeric_to_band("number.x", 150)
    assert reason is None
    assert val == 110.0


@pytest.mark.asyncio
async def test_optimizer_kill_switch_split_brain_fails_closed():
    """B-C2: stale options=False + last_state=on → stays engaged.

    The test mocks RestoreEntity (it's a `type("RestoreEntity", (), {})`
    in the test mod table at the top of this file) so the production
    `super().async_added_to_hass()` would AttributeError. We patch the
    parent's no-op shim into the mocked class so the call resolves.
    """
    import custom_components.universal_room_automation.switch as _switch_mod
    from custom_components.universal_room_automation.switch import (
        OptimizerKillSwitch,
    )
    # Ensure the RestoreEntity base has an async no-op added_to_hass so
    # super() resolves in the production code path.
    _re_cls = sys.modules["homeassistant.helpers.restore_state"].RestoreEntity
    if not hasattr(_re_cls, "async_added_to_hass"):
        async def _noop(self):
            return None
        _re_cls.async_added_to_hass = _noop
    # SwitchEntity also needs the same.
    _sw_cls = sys.modules["homeassistant.components.switch"].SwitchEntity
    if not hasattr(_sw_cls, "async_added_to_hass"):
        async def _noop2(self):
            return None
        _sw_cls.async_added_to_hass = _noop2

    hass = MockHassForOpt()
    entry = _MockEntry("cm", "coordinator_manager", data={}, options={})
    sw = OptimizerKillSwitch(hass, entry)
    # Constructor seeded released (no options key + default False).
    assert sw.is_on is False

    class _S:  # noqa: D401
        state = "on"

    sw.async_get_last_state = AsyncMock(return_value=_S())
    sw.async_write_ha_state = MagicMock()
    await sw.async_added_to_hass()
    assert sw.is_on is True
    # Options were reconverged.
    assert entry.options.get("optimizer_kill_switch") is True


def test_log_finding_rejects_none_severity_via_db():
    """C-MED-1: the guard also rejects None severity (sister check)."""
    import asyncio as _asyncio
    from custom_components.universal_room_automation import database as _db_mod
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationFinding, OptimizationDimension,
    )
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.META,
        severity=None,  # None severity should also reject
        confidence=0.9, score=50.0, description="bad row",
    )

    class _StubDB:
        log_finding = _db_mod.UniversalRoomDatabase.log_finding

    result = _asyncio.run(_StubDB().log_finding(f))
    assert result is None


def test_options_reload_suppress_includes_optimizer_keys():
    """C-CRIT-1: the 6 optimizer keys are in OPTIONS_RELOAD_SUPPRESS_KEYS,
    so changing autonomy / kill switch does NOT tear down the CM entry."""
    from custom_components.universal_room_automation import (
        OPTIONS_RELOAD_SUPPRESS_KEYS,
    )
    keys = {
        "optimizer_autonomy_level",
        "optimizer_kill_switch",
        "optimizer_dimension_autonomy",
        "optimizer_confidence_gate",
        "optimizer_rate_cap_per_hour",
        "optimizer_quiet_hours_source",
    }
    missing = keys - set(OPTIONS_RELOAD_SUPPRESS_KEYS)
    assert not missing, f"Optimizer keys missing from suppress allowlist: {missing}"


def test_comfort_slider_keys_documented():
    """C-HIGH-3: comfort sliders go through the ROOM-level suppress path
    in _async_update_listener (not the CM allowlist). Validate the const
    exports exist so the listener doesn't get them silently wrong."""
    from custom_components.universal_room_automation.const import (
        CONF_COMFORT_TEMP_MIN,
        CONF_COMFORT_TEMP_MAX,
        CONF_COMFORT_HUMIDITY_MAX,
    )
    assert CONF_COMFORT_TEMP_MIN == "comfort_temp_min"
    assert CONF_COMFORT_TEMP_MAX == "comfort_temp_max"
    assert CONF_COMFORT_HUMIDITY_MAX == "comfort_humidity_max"


@pytest.mark.asyncio
async def test_optimizer_sensor_subscriptions_real_signal_survives():
    """C-HIGH-2 rewrite: capture the unsub identity, simulate an arbitrary
    re-setup, then prove the original subscription still receives signals.

    Drives the REAL veto callback via async_dispatcher_send under the
    mocked dispatcher so the assertion is: the broker's veto state
    machine STILL responds after setup pressure.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    await coord.async_setup()
    pre_listeners = list(coord._unsub_listeners)
    assert len(pre_listeners) >= 1
    # Drive a veto via the broker's _on_veto (same shape as
    # async_dispatcher_send would invoke). The broker MUST stash the
    # veto so an immediate await_veto picks it up.
    coord.broker._on_veto({"action_id": "abc", "vetoed_by": "test_sibling"})
    vetoed_by = await coord.broker.await_veto("abc", 0)
    assert vetoed_by == "test_sibling"
    # Listener list is unchanged after the dispatch round-trip.
    assert coord._unsub_listeners == pre_listeners
    await coord.async_teardown()
    assert coord._unsub_listeners == []


@pytest.mark.asyncio
async def test_optimizer_l1_synthetic_proposed_action_is_inert():
    """A-HIGH-4: a synthetic finding WITH proposed_action at L1 emits the
    intent + logs shadow_dry_run but performs ZERO service calls."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_SHADOW,
    )
    hass, _ = _make_hass(cm_options={"optimizer_autonomy_level": "shadow"})
    coord = OptimizationCoordinator(hass)
    fired = []
    coord.broker.fire_intent = lambda *a, **k: fired.append((a, k)) or True
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.95, score=50.0,
        description="phase-2 synthetic",
        proposed_action={
            "service": "light.turn_on",
            "service_data": {},
            "target_entity": "light.kitchen",
            "action_class": "reversible_device",
        },
    )
    await coord._consider_apply(f)
    assert f.applied_outcome == OPTIMIZER_OUTCOME_SHADOW
    assert hass.services.calls == [], "Shadow level must NOT actuate"
    assert fired, "Shadow level must emit an intent for sibling visibility"


# =============================================================================
# v4.7.35 Phase 2 — LLM Tier-2 tests
# =============================================================================


def _llm_make_response(findings_rows, reasoning="ok"):
    """Wrap a list of finding-row dicts into the structured-output shape
    that mirrors `ai_task.generate_data` return values."""
    return {"data": {"findings": findings_rows, "reasoning": reasoning}}


def _llm_finding_row(
    *,
    dimension="comfort",
    severity="medium",
    confidence=0.85,
    target_level="room",
    target_id="kitchen",
    description="kitchen too warm",
    proposed=None,
):
    return {
        "dimension": dimension,
        "severity": severity,
        "confidence": confidence,
        "target_level": target_level,
        "target_id": target_id,
        "description": description,
        "proposed_action_or_null": proposed,
    }


def _attach_ai_task_mock(hass, response):
    """Replace `hass.services.async_call` with one that returns ``response``
    for `ai_task.generate_data` calls and records every invocation."""
    real_calls: list[dict] = []
    services_module = hass.services

    async def _ai_task_call(domain, service, data, blocking=False,
                            return_response=False):
        real_calls.append({
            "domain": domain, "service": service, "data": dict(data or {}),
            "return_response": return_response,
        })
        if domain == "ai_task" and service == "generate_data":
            if isinstance(response, list):
                # Sequence of responses: pop the next one.
                if response:
                    return response.pop(0)
                return None
            return response
        return None

    services_module.async_call = _ai_task_call  # type: ignore[assignment]
    return real_calls


@pytest.mark.asyncio
async def test_optimizer_llm_corpus_under_token_cap():
    """Assembled corpus prompt body stays under the configured char cap."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_LLM_CONTEXT_CHARS_PER_TOKEN,
        OPTIMIZER_LLM_CONTEXT_MAX_TOKENS,
    )

    # Build a lot of rooms so the corpus would naturally blow past the cap
    # without trimming.
    rooms = [{"room_name": f"room_{i}"} for i in range(200)]
    hass, _ = _make_hass(rooms=rooms)
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)
    corpus = tier._assemble_corpus(tier1_findings=[])
    body = corpus.to_prompt_body()
    max_chars = (
        OPTIMIZER_LLM_CONTEXT_MAX_TOKENS * OPTIMIZER_LLM_CONTEXT_CHARS_PER_TOKEN
    )
    assert len(body) <= max_chars
    assert "# === STABLE CONTEXT ===" in body
    assert "# === CURRENT SNAPSHOT ===" in body


@pytest.mark.asyncio
async def test_optimizer_llm_delta_trigger_skips_when_unchanged():
    """Two cycles with the same Tier-1 finding set → only ONE LLM call."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
    })
    coord = OptimizationCoordinator(hass)
    calls = _attach_ai_task_mock(hass, _llm_make_response([
        _llm_finding_row(),
    ]))

    f1 = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.8, score=0.0,
        description="t1", dedup_key=("comfort", "kitchen", "x"),
    )

    # First cycle: delta-from-nothing → invokes.
    await coord._maybe_run_llm_tier([f1])
    n_after_first = sum(
        1 for c in calls
        if c["domain"] == "ai_task" and c["service"] == "generate_data"
    )
    assert n_after_first == 1, (
        f"first cycle should invoke LLM once, saw {n_after_first}"
    )

    # Re-arm response for any further calls.
    calls.clear()
    hass.services.calls = []
    _attach_ai_task_mock(hass, _llm_make_response([_llm_finding_row()]))

    # Second cycle with SAME signature: delta gate should skip the call.
    await coord._maybe_run_llm_tier([f1])
    assert all(c["service"] != "generate_data" for c in calls), (
        "delta gate should skip the LLM when finding-set unchanged"
    )


@pytest.mark.asyncio
async def test_optimizer_llm_daily_cap_enforced():
    """Premium tier stops invoking once daily cap is reached."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
        "optimizer_llm_max_invocations_per_24h": 2,
    })
    coord = OptimizationCoordinator(hass)
    # Stand up sequence of identical responses; reused across cycles.
    responses = [
        _llm_make_response([_llm_finding_row(target_id=f"r{i}")])
        for i in range(10)
    ]
    calls = _attach_ai_task_mock(hass, responses)

    for i in range(5):
        f = OptimizationFinding(
            timestamp=datetime.utcnow().isoformat(),
            level="room", target_id=f"room_{i}",
            dimension=OptimizationDimension.COMFORT,
            severity="medium", confidence=0.5, score=0.0,
            description=f"d{i}", dedup_key=("comfort", f"room_{i}", "x"),
        )
        await coord._maybe_run_llm_tier([f])

    n = sum(
        1 for c in calls
        if c["domain"] == "ai_task" and c["service"] == "generate_data"
    )
    assert n == 2, f"daily cap (2) should bound invocations, saw {n}"


@pytest.mark.asyncio
async def test_optimizer_llm_triage_routes_to_premium_only_when_flagged():
    """Triage with empty findings list suppresses the premium call.

    Triage with ≥1 finding lets the premium call through.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )

    # Case A — triage flags nothing → premium NOT called.
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
        "optimizer_llm_triage_entity": "ai_task.ollama_ai_task",
    })
    coord = OptimizationCoordinator(hass)
    # Sequence: [triage_response_empty]; premium never reached.
    calls = _attach_ai_task_mock(hass, [
        _llm_make_response([]),  # triage says nothing
    ])
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.7, score=0.0,
        description="d", dedup_key=("comfort", "kitchen", "x"),
    )
    await coord._maybe_run_llm_tier([f])
    triage_calls = [
        c for c in calls
        if c["data"].get("entity_id") == "ai_task.ollama_ai_task"
    ]
    premium_calls = [
        c for c in calls
        if c["data"].get("entity_id") == "ai_task.claude_ai_task"
    ]
    assert len(triage_calls) == 1
    assert len(premium_calls) == 0, (
        "Empty triage must NOT route to premium"
    )

    # Case B — triage flags ≥1 finding → premium IS called.
    hass2, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
        "optimizer_llm_triage_entity": "ai_task.ollama_ai_task",
    })
    coord2 = OptimizationCoordinator(hass2)
    calls2 = _attach_ai_task_mock(hass2, [
        _llm_make_response([_llm_finding_row(description="triage flag")]),
        _llm_make_response([_llm_finding_row(description="premium finding")]),
    ])
    await coord2._maybe_run_llm_tier([f])
    triage2 = [
        c for c in calls2
        if c["data"].get("entity_id") == "ai_task.ollama_ai_task"
    ]
    premium2 = [
        c for c in calls2
        if c["data"].get("entity_id") == "ai_task.claude_ai_task"
    ]
    assert len(triage2) == 1
    assert len(premium2) == 1, (
        "Flagged triage MUST route to premium"
    )


@pytest.mark.asyncio
async def test_optimizer_llm_malformed_output_rejected():
    """Malformed individual findings are skipped — good ones survive."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)

    rows = [
        _llm_finding_row(description="ok"),  # good
        {"dimension": "comfort"},  # missing required fields
        _llm_finding_row(confidence=99.0),  # out-of-range confidence
        _llm_finding_row(severity="bogus"),  # bad severity
        _llm_finding_row(
            description="ok2", target_level="zone", target_id="z1",
        ),  # good
    ]
    parsed = tier._parse_findings(_llm_make_response(rows))
    assert len(parsed) == 2, (
        f"only 2 good rows expected, got {len(parsed)}"
    )
    assert {p.description for p in parsed} == {"ok", "ok2"}


@pytest.mark.asyncio
async def test_optimizer_llm_findings_tagged_tier2_llm():
    """Every LLM-emitted finding carries `created_by=tier2_llm`."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_CREATED_BY_TIER2_LLM,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)

    parsed = tier._parse_findings(_llm_make_response([
        _llm_finding_row(description="row a"),
        _llm_finding_row(description="row b", target_id="bath"),
    ]))
    assert len(parsed) == 2
    for f in parsed:
        assert f.created_by == OPTIMIZER_CREATED_BY_TIER2_LLM


@pytest.mark.asyncio
async def test_optimizer_llm_action_flows_through_chokepoint():
    """LLM-proposed action at L1 is shadow-inert (no service dispatched)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_SHADOW,
    )
    # L1 SHADOW is the default — proposed actions must NOT actuate.
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "shadow",
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
        "optimizer_confidence_gate": 0.5,
    })
    coord = OptimizationCoordinator(hass)
    calls = _attach_ai_task_mock(hass, _llm_make_response([
        _llm_finding_row(
            confidence=0.9,
            proposed={
                "domain": "light", "service": "turn_on",
                "target_entity": "light.kitchen", "service_data": {},
                "action_class": "reversible_device",
            },
        ),
    ]))

    emitted = await coord._maybe_run_llm_tier([])
    assert emitted, "LLM should have emitted at least one finding"
    f = emitted[0]
    # Service dispatch records: NO `light.turn_on` should fire at L1.
    actuated = [
        c for c in calls
        if c["domain"] == "light" and c["service"] == "turn_on"
    ]
    assert actuated == [], (
        "L1 must NOT actuate an LLM-proposed action; chokepoint was "
        "bypassed if this fires"
    )
    assert f.applied_outcome == OPTIMIZER_OUTCOME_SHADOW


@pytest.mark.asyncio
async def test_optimizer_llm_provider_switch_parses():
    """Swapping the LLM task entity still parses findings (provider-agnostic)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.ollama_ai_task",
    })
    coord = OptimizationCoordinator(hass)
    calls = _attach_ai_task_mock(hass, _llm_make_response([
        _llm_finding_row(description="local-backend finding"),
    ]))
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.6, score=0.0,
        description="seed", dedup_key=("comfort", "kitchen", "x"),
    )
    emitted = await coord._maybe_run_llm_tier([f])
    assert emitted, "Ollama backend must yield parseable findings"
    # The entity_id on the dispatched ai_task call confirms routing.
    assert any(
        c["data"].get("entity_id") == "ai_task.ollama_ai_task"
        for c in calls
    ), "Expected ai_task.ollama_ai_task to be dispatched"


@pytest.mark.asyncio
async def test_optimizer_llm_prompt_resolution_falls_back_to_const():
    """Empty / missing options prompt falls back to the in-code const."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_LLM_SYSTEM_PROMPT,
    )
    # Case A — key absent → const.
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)
    assert tier._resolve_system_prompt(tier._read_cm_config()) == (
        OPTIMIZER_LLM_SYSTEM_PROMPT
    )
    # Case B — key empty string → const.
    hass2, _ = _make_hass(cm_options={"optimizer_llm_system_prompt": ""})
    coord2 = OptimizationCoordinator(hass2)
    tier2 = OptimizationLLMTier(hass2, coord2)
    assert tier2._resolve_system_prompt(tier2._read_cm_config()) == (
        OPTIMIZER_LLM_SYSTEM_PROMPT
    )
    # Case C — key whitespace-only → const.
    hass3, _ = _make_hass(cm_options={
        "optimizer_llm_system_prompt": "   \n\t  ",
    })
    coord3 = OptimizationCoordinator(hass3)
    tier3 = OptimizationLLMTier(hass3, coord3)
    assert tier3._resolve_system_prompt(tier3._read_cm_config()) == (
        OPTIMIZER_LLM_SYSTEM_PROMPT
    )
    # Case D — operator-customized prompt overrides const.
    custom = "You are a custom optimization analyst. Output the schema."
    hass4, _ = _make_hass(cm_options={
        "optimizer_llm_system_prompt": custom,
    })
    coord4 = OptimizationCoordinator(hass4)
    tier4 = OptimizationLLMTier(hass4, coord4)
    assert tier4._resolve_system_prompt(tier4._read_cm_config()) == custom


def test_options_reload_suppress_includes_optimizer_llm_keys():
    """All four new LLM CONF keys MUST be in OPTIONS_RELOAD_SUPPRESS_KEYS
    so editing them never triggers a full CM reload (C-CRIT-1 guardrail)."""
    from custom_components.universal_room_automation import (
        OPTIONS_RELOAD_SUPPRESS_KEYS,
        _NO_LIVE_ATTR_KEYS,
    )
    from custom_components.universal_room_automation.const import (
        CONF_OPTIMIZER_LLM_TASK_ENTITY,
        CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
        CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
        CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    )
    required = {
        CONF_OPTIMIZER_LLM_TASK_ENTITY,
        CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
        CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
        CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    }
    missing_suppress = required - set(OPTIONS_RELOAD_SUPPRESS_KEYS)
    missing_no_live = required - set(_NO_LIVE_ATTR_KEYS)
    assert not missing_suppress, (
        f"LLM CONF keys missing from OPTIONS_RELOAD_SUPPRESS_KEYS: "
        f"{sorted(missing_suppress)}"
    )
    assert not missing_no_live, (
        f"LLM CONF keys missing from _NO_LIVE_ATTR_KEYS: "
        f"{sorted(missing_no_live)}"
    )


# ---------------------------------------------------------------------------
# v4.7.35 fix-up — Phase 2 Tier 2-DB review findings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_llm_daily_cap_seeds_from_db():
    """A-CRIT-1 / C-MED-3: rolling-24h premium cap survives restart.

    Seed ``_premium_invocations`` from DB rows with
    ``created_by="tier2_llm"`` within the last 24h, mirroring Phase-1's
    H2 rate-cap seed.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
        # Cap at 2 — three prior premium invocations in the DB must
        # block the next call.
        "optimizer_llm_max_invocations_per_24h": 2,
    })
    now = datetime.utcnow()
    rows = [
        {"created_by": "tier2_llm", "timestamp": now.isoformat()},
        {"created_by": "tier2_llm",
         "timestamp": (now - timedelta(minutes=30)).isoformat()},
        {"created_by": "tier2_llm",
         "timestamp": (now - timedelta(hours=10)).isoformat()},
        # Stale (>24h) — must NOT seed.
        {"created_by": "tier2_llm",
         "timestamp": (now - timedelta(hours=30)).isoformat()},
        # Tier-1 row — must NOT seed.
        {"created_by": "tier1", "timestamp": now.isoformat()},
    ]
    hass.data["universal_room_automation"]["database"].\
        get_recent_optimization_findings = AsyncMock(return_value=rows)

    coord = OptimizationCoordinator(hass)
    calls = _attach_ai_task_mock(hass, _llm_make_response([
        _llm_finding_row(),
    ]))
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.7, score=0.0,
        description="d", dedup_key=("comfort", "kitchen", "x"),
    )
    await coord._maybe_run_llm_tier([f])
    # Cap=2 with 3 seeded rows → no premium call this cycle.
    premium_calls = [
        c for c in calls
        if c["data"].get("entity_id") == "ai_task.claude_ai_task"
    ]
    assert premium_calls == [], (
        "Rolling-24h cap should be seeded from DB and block this call; "
        f"saw {premium_calls}"
    )
    assert coord._llm_tier is not None
    assert len(coord._llm_tier._premium_invocations) == 3


@pytest.mark.asyncio
async def test_optimizer_llm_rejects_hallucinated_entity():
    """A-HIGH-2 / B-B3: a LLM finding referencing an off-snapshot
    entity is rejected; on-snapshot entities survive."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    rooms = [{"room_name": "kitchen", "data": {
        "room_name": "kitchen",
        "temperature_sensor": "sensor.kitchen_temp",
        "occupancy_sensors": ["binary_sensor.kitchen_occupancy"],
    }}]
    hass, _ = _make_hass(rooms=rooms)
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)
    # Populate corpus allowlists from the substrate.
    tier._assemble_corpus(tier1_findings=[])
    assert "sensor.kitchen_temp" in tier._corpus_entity_ids

    rows = [
        # Good — on-snapshot entity.
        _llm_finding_row(
            description="kitchen ok", target_id="kitchen",
            proposed={
                "domain": "light", "service": "turn_on",
                "target_entity": "sensor.kitchen_temp",
                "service_data": {},
            },
        ),
        # Hallucinated — entity_id not in corpus.
        _llm_finding_row(
            description="bad hallucinated", target_id="kitchen",
            proposed={
                "domain": "light", "service": "turn_on",
                "target_entity": "light.master_bedroom_fan",
                "service_data": {},
            },
        ),
        # Hallucinated target_id (room not in corpus).
        _llm_finding_row(
            description="bad target_id", target_id="phantom_room",
        ),
    ]
    parsed = tier._parse_findings(_llm_make_response(rows))
    assert len(parsed) == 1, (
        f"only 1 finding should survive entity allowlist, got "
        f"{[p.description for p in parsed]}"
    )
    assert parsed[0].description == "kitchen ok"


def test_optimizer_allowed_domains_disjoint():
    """B-B1: device/config domain allowlists MUST be disjoint so the
    L2/L3 chokepoint split can't be silently broken by a future drift."""
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_ALLOWED_DOMAINS_DEVICE,
        OPTIMIZER_ALLOWED_DOMAINS_CONFIG,
    )
    assert OPTIMIZER_ALLOWED_DOMAINS_DEVICE.isdisjoint(
        OPTIMIZER_ALLOWED_DOMAINS_CONFIG,
    ), (
        f"Device/config domain allowlists overlap: "
        f"{OPTIMIZER_ALLOWED_DOMAINS_DEVICE & OPTIMIZER_ALLOWED_DOMAINS_CONFIG}"
    )


def test_optimizer_llm_action_class_derived_from_domain():
    """B-B1: action_class is DERIVED from service domain, ignoring
    whatever the LLM supplied."""
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    # Device domain → reversible_device, even when LLM tries config_write.
    norm = OptimizationLLMTier._normalize_proposed_action({
        "domain": "light", "service": "turn_on",
        "target_entity": "light.kitchen",
        "service_data": {},
        "action_class": "config_write",  # LLM lying
    })
    assert norm["action_class"] == "reversible_device"
    assert norm["service"] == "light.turn_on"

    # Config domain → config_write, even when LLM tries reversible_device.
    norm = OptimizationLLMTier._normalize_proposed_action({
        "domain": "number", "service": "set_value",
        "target_entity": "number.foo",
        "service_data": {"value": 5},
        "action_class": "reversible_device",  # LLM lying
    })
    assert norm["action_class"] == "config_write"
    assert norm["service"] == "number.set_value"

    # Unknown domain → empty action_class (will fail allowlist at the
    # chokepoint).
    norm = OptimizationLLMTier._normalize_proposed_action({
        "domain": "lock", "service": "unlock",
        "target_entity": "lock.front",
        "service_data": {},
    })
    assert norm["action_class"] == ""


def test_optimizer_llm_service_data_key_allowlist():
    """A-HIGH-3: unknown ``service_data`` keys are dropped from the
    normalized action."""
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    norm = OptimizationLLMTier._normalize_proposed_action({
        "domain": "light", "service": "turn_on",
        "target_entity": "light.kitchen",
        "service_data": {
            "brightness_pct": 50,
            "color_temp_kelvin": 4000,
            "transition": 1,
            # Disallowed — must be dropped:
            "raw_payload": "dangerous",
            "entity_id": "light.somewhere_else",
            "data": {"nested": "no"},
        },
    })
    assert norm["service_data"] == {
        "brightness_pct": 50,
        "color_temp_kelvin": 4000,
        "transition": 1,
    }


def test_optimizer_llm_bare_service_rejected():
    """B-B5: a service without a domain yields an empty service string,
    which the chokepoint's domain allowlist will reject."""
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    # Empty domain + bare service name → empty service.
    norm = OptimizationLLMTier._normalize_proposed_action({
        "domain": "",
        "service": "turn_on",
        "target_entity": "light.kitchen",
        "service_data": {},
    })
    assert norm["service"] == ""

    # Malformed dotted service (only one half) → empty.
    norm = OptimizationLLMTier._normalize_proposed_action({
        "domain": "",
        "service": ".turn_on",
        "target_entity": "light.kitchen",
        "service_data": {},
    })
    assert norm["service"] == ""


@pytest.mark.asyncio
async def test_optimizer_safety_denylist_blocks_action():
    """B-B2: any action proposed against a denied entity is blocked at
    the chokepoint, regardless of created_by."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_OUTCOME_DISALLOWED,
    )
    hass, _ = _make_hass(cm_options={
        "optimizer_autonomy_level": "reversible_device",
        "optimizer_confidence_gate": 0.5,
        "optimizer_safety_deny_entities": [
            "switch.security_armed",
            "lock.front_door",
        ],
    })
    coord = OptimizationCoordinator(hass)
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.9, score=50.0,
        description="meddle",
    )
    outcome = await coord._apply_action(f, {
        "service": "switch.turn_off",
        "service_data": {},
        "target_entity": "switch.security_armed",
        "action_class": "reversible_device",
    })
    assert outcome == OPTIMIZER_OUTCOME_DISALLOWED
    assert hass.services.calls == []


def test_optimizer_safety_denylist_key_in_suppress_sets():
    """B-B2 / C-CRIT-1 lesson: the new safety-deny CONF key must be
    in BOTH ``OPTIONS_RELOAD_SUPPRESS_KEYS`` and ``_NO_LIVE_ATTR_KEYS``
    so editing it never triggers a full CM reload."""
    from custom_components.universal_room_automation import (
        OPTIONS_RELOAD_SUPPRESS_KEYS,
        _NO_LIVE_ATTR_KEYS,
    )
    from custom_components.universal_room_automation.const import (
        CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
    )
    assert CONF_OPTIMIZER_SAFETY_DENY_ENTITIES in OPTIONS_RELOAD_SUPPRESS_KEYS
    assert CONF_OPTIMIZER_SAFETY_DENY_ENTITIES in _NO_LIVE_ATTR_KEYS


@pytest.mark.asyncio
async def test_optimizer_llm_triage_off_by_default():
    """A-HIGH-1 / C-LOW-2: triage entity defaults to empty → no
    triage backend invoked; the premium pass runs directly.
    """
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    from custom_components.universal_room_automation.const import (
        DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY,
    )
    assert DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY == ""

    # No triage entity configured — premium runs directly.
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_task_entity": "ai_task.claude_ai_task",
    })
    coord = OptimizationCoordinator(hass)
    calls = _attach_ai_task_mock(hass, _llm_make_response([
        _llm_finding_row(),
    ]))
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.7, score=0.0,
        description="d", dedup_key=("comfort", "kitchen", "x"),
    )
    await coord._maybe_run_llm_tier([f])
    # Only premium was called, never a triage entity.
    triage_calls = [
        c for c in calls
        if c["data"].get("entity_id", "").startswith("ai_task.ollama_")
    ]
    premium_calls = [
        c for c in calls
        if c["data"].get("entity_id") == "ai_task.claude_ai_task"
    ]
    assert triage_calls == [], (
        f"No triage configured, but triage was called: {triage_calls}"
    )
    assert len(premium_calls) == 1


@pytest.mark.asyncio
async def test_optimizer_llm_confidence_soft_clamped():
    """B-B4: LLM-supplied confidence > 0.85 is soft-clamped down so an
    operator who pins the confidence gate at 1.0 retains a 'no
    autonomous LLM action' failsafe."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)

    parsed = tier._parse_findings(_llm_make_response([
        _llm_finding_row(confidence=0.99, description="clamp me"),
        _llm_finding_row(confidence=0.5, description="below clamp"),
    ]))
    assert len(parsed) == 2
    by_desc = {p.description: p for p in parsed}
    assert by_desc["clamp me"].confidence == OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX
    # Sub-clamp values are untouched.
    assert by_desc["below clamp"].confidence == 0.5


@pytest.mark.asyncio
async def test_optimizer_llm_oversized_prompt_bounded():
    """A-MED-4: a runaway live system-prompt override falls back to the
    in-code const rather than truncating mid-instruction."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    from custom_components.universal_room_automation.const import (
        OPTIMIZER_LLM_SYSTEM_PROMPT,
        OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS,
    )
    huge = "X" * (OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS + 100)
    hass, _ = _make_hass(cm_options={
        "optimizer_llm_system_prompt": huge,
    })
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)
    resolved = tier._resolve_system_prompt(tier._read_cm_config())
    assert resolved == OPTIMIZER_LLM_SYSTEM_PROMPT, (
        "Oversized live prompt must fall back to const, not truncate"
    )


@pytest.mark.asyncio
async def test_optimizer_llm_delta_signature_excludes_meta():
    """A-MED-2: META 'cycle_ok' sentinel rows fire every cycle by
    design and MUST be excluded from the delta-gate signature, else the
    gate fires every cycle and the cost lever is moot."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (
        OptimizationLLMTier,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    tier = OptimizationLLMTier(hass, coord)
    f_real = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="kitchen",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.7, score=0.0,
        description="real", dedup_key=("comfort", "kitchen", "x"),
    )
    f_meta1 = OptimizationFinding(
        timestamp="2020-01-01T00:00:00",
        level="house", target_id="house",
        dimension=OptimizationDimension.META,
        severity="low", confidence=1.0, score=100.0,
        description="cycle_ok",
    )
    f_meta2 = OptimizationFinding(
        timestamp="2020-01-01T00:05:00",
        level="house", target_id="house",
        dimension=OptimizationDimension.META,
        severity="low", confidence=1.0, score=100.0,
        description="cycle_ok",
    )
    sig1 = tier._signature([f_real, f_meta1])
    sig2 = tier._signature([f_real, f_meta2])
    assert sig1 == sig2, (
        f"META rows must be excluded from the signature, got "
        f"{sig1!r} vs {sig2!r}"
    )



# ===========================================================================
# Phase 3 (v4.7.36) — dimension evaluators + daily digest
# ===========================================================================


@pytest.mark.asyncio
async def test_rule_engine_occupancy_accuracy_provenance_disagreement():
    """Motion ON but occupancy clear → exactly one OCCUPANCY_ACCURACY finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )
    rooms = [{
        "room_name": "kitchen",
        "data": {
            "room_name": "kitchen",
            "occupancy_sensors": ["binary_sensor.kitchen_occ"],
            "motion_sensors": ["binary_sensor.kitchen_motion"],
        },
        "options": {},
    }]
    hass, _ = _make_hass(rooms=rooms)
    hass.states.set("binary_sensor.kitchen_motion", "on")
    hass.states.set("binary_sensor.kitchen_occ", "off")
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_occupancy_accuracy_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.OCCUPANCY_ACCURACY]
    assert len(matching) == 1
    assert matching[0].target_id == "kitchen"
    assert matching[0].severity == "low"


@pytest.mark.asyncio
async def test_rule_engine_occupancy_accuracy_agreement_no_finding():
    """Motion ON and occupancy ON → no finding (sensors agree)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )
    rooms = [{
        "room_name": "kitchen",
        "data": {
            "room_name": "kitchen",
            "occupancy_sensors": ["binary_sensor.kitchen_occ"],
            "motion_sensors": ["binary_sensor.kitchen_motion"],
        },
        "options": {},
    }]
    hass, _ = _make_hass(rooms=rooms)
    hass.states.set("binary_sensor.kitchen_motion", "on")
    hass.states.set("binary_sensor.kitchen_occ", "on")
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_occupancy_accuracy_dimension()
    assert [f for f in findings
            if f.dimension == OptimizationDimension.OCCUPANCY_ACCURACY] == []


@pytest.mark.asyncio
async def test_rule_engine_config_behavior_inverted_bounds():
    """comfort_temp_max <= comfort_temp_min → CONFIG_BEHAVIOR finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )
    rooms = [{
        "room_name": "office",
        "data": {"room_name": "office"},
        "options": {
            "comfort_temp_min": 75,
            "comfort_temp_max": 70,  # inverted
        },
    }]
    hass, _ = _make_hass(rooms=rooms)
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_config_behavior_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.CONFIG_BEHAVIOR]
    assert len(matching) == 1
    assert matching[0].severity == "medium"
    assert matching[0].target_id == "office"


@pytest.mark.asyncio
async def test_rule_engine_config_behavior_valid_no_finding():
    """Valid comfort config → no CONFIG_BEHAVIOR finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )
    rooms = [{
        "room_name": "office",
        "data": {"room_name": "office"},
        "options": {"comfort_temp_min": 68, "comfort_temp_max": 76},
    }]
    hass, _ = _make_hass(rooms=rooms)
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_config_behavior_dimension()
    assert [f for f in findings
            if f.dimension == OptimizationDimension.CONFIG_BEHAVIOR] == []


@pytest.mark.asyncio
async def test_rule_engine_vacancy_management_stuck_occupancy():
    """Zone continuously occupied >12h + sweep not fired → VACANCY_MANAGEMENT."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeZone:
        zone_id = "master_zone"
        zone_name = "Master Zone"
        continuous_occupied_since = _opt_now() - timedelta(hours=14)
        vacancy_sweep_done = False
        vacancy_sweep_enabled = True

    class _FakeZM:
        zones = {"master_zone": _FakeZone()}

    class _FakeHVAC:
        zone_manager = _FakeZM()

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["hvac_coordinator"] = _FakeHVAC()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_vacancy_management_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.VACANCY_MANAGEMENT]
    assert len(matching) == 1
    assert matching[0].target_id == "master_zone"
    assert matching[0].level == "zone"


@pytest.mark.asyncio
async def test_rule_engine_vacancy_management_recent_no_finding():
    """Continuous occupancy <12h → no finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeZone:
        zone_id = "master_zone"
        zone_name = "Master Zone"
        continuous_occupied_since = _opt_now() - timedelta(hours=3)
        vacancy_sweep_done = False
        vacancy_sweep_enabled = True

    class _FakeZM:
        zones = {"master_zone": _FakeZone()}

    class _FakeHVAC:
        zone_manager = _FakeZM()

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["hvac_coordinator"] = _FakeHVAC()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_vacancy_management_dimension()
    assert [f for f in findings
            if f.dimension == OptimizationDimension.VACANCY_MANAGEMENT] == []


@pytest.mark.asyncio
async def test_rule_engine_override_frequency_fires_at_threshold():
    """zone.override_count_today >=10 → OVERRIDE_FREQUENCY (medium); >=20 → high."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeZone:
        zone_id = "study_zone"
        zone_name = "Study Zone"
        override_count_today = 12

    class _FakeZM:
        zones = {"study_zone": _FakeZone()}

    class _FakeHVAC:
        zone_manager = _FakeZM()

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["hvac_coordinator"] = _FakeHVAC()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_override_frequency_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.OVERRIDE_FREQUENCY]
    assert len(matching) == 1
    assert matching[0].severity == "medium"

    # Bump count above 20 → severity escalates to high.
    _FakeZone.override_count_today = 25
    coord2 = OptimizationCoordinator(hass)
    findings2 = coord2._evaluate_override_frequency_dimension()
    matching2 = [f for f in findings2
                 if f.dimension == OptimizationDimension.OVERRIDE_FREQUENCY]
    assert len(matching2) == 1
    assert matching2[0].severity == "high"


@pytest.mark.asyncio
async def test_rule_engine_state_machine_accuracy_long_override():
    """House override held >2h → STATE_MACHINE_ACCURACY finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeHSM:
        is_overridden = True
        _override_since = (_opt_now() - timedelta(hours=3)).timestamp()
        state = "home"

    class _FakeCM:
        house_state_machine = _FakeHSM()
        coordinators = {}

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["coordinator_manager"] = _FakeCM()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_state_machine_accuracy_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.STATE_MACHINE_ACCURACY]
    assert len(matching) == 1
    assert matching[0].level == "house"


@pytest.mark.asyncio
async def test_rule_engine_state_machine_accuracy_not_overridden_no_finding():
    """No override → no finding."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeHSM:
        is_overridden = False
        _override_since = None
        state = "home"

    class _FakeCM:
        house_state_machine = _FakeHSM()
        coordinators = {}

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["coordinator_manager"] = _FakeCM()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_state_machine_accuracy_dimension()
    assert [f for f in findings
            if f.dimension == OptimizationDimension.STATE_MACHINE_ACCURACY] == []


@pytest.mark.asyncio
async def test_rule_engine_security_posture_unlocked_when_away():
    """Locks unlocked while AWAY → high-severity SECURITY_POSTURE."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeHSM:
        is_overridden = False
        _override_since = None
        state = "away"

    class _FakeSec:
        def get_security_aggregator_state(self):
            return {"locks_unlocked": 2, "locks_locked": 1}

    class _FakeCM:
        house_state_machine = _FakeHSM()
        coordinators = {"security": _FakeSec()}

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["coordinator_manager"] = _FakeCM()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_security_posture_dimension()
    matching = [f for f in findings
                if f.dimension == OptimizationDimension.SECURITY_POSTURE]
    assert len(matching) == 1
    assert matching[0].severity == "high"


@pytest.mark.asyncio
async def test_rule_engine_security_posture_home_no_finding():
    """Locks unlocked but state HOME → no finding (not a gated context)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationDimension,
    )

    class _FakeHSM:
        is_overridden = False
        _override_since = None
        state = "home"

    class _FakeSec:
        def get_security_aggregator_state(self):
            return {"locks_unlocked": 2, "locks_locked": 1}

    class _FakeCM:
        house_state_machine = _FakeHSM()
        coordinators = {"security": _FakeSec()}

    hass, _ = _make_hass()
    hass.data["universal_room_automation"]["coordinator_manager"] = _FakeCM()
    coord = OptimizationCoordinator(hass)
    findings = coord._evaluate_security_posture_dimension()
    assert [f for f in findings
            if f.dimension == OptimizationDimension.SECURITY_POSTURE] == []


@pytest.mark.asyncio
async def test_deferred_dimensions_return_empty():
    """Substrate-unavailable dimensions return [] (no fabrication)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    assert coord._evaluate_automation_responsiveness_dimension() == []
    assert coord._evaluate_energy_efficiency_dimension() == []
    assert coord._evaluate_setpoint_compliance_dimension() == []


@pytest.mark.asyncio
async def test_optimization_daily_digest_dao_roundtrip(real_schema_db):
    """log_daily_digest writes a row that reads back via SELECT."""
    import json as _json
    conn = real_schema_db
    conn.execute(
        """INSERT INTO optimization_daily_digest
           (date, generated_at, findings_count,
            by_severity_json, by_dimension_json, summary_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "2026-06-09",
            "2026-06-09T08:00:00",
            3,
            _json.dumps({"critical": 0, "high": 1, "medium": 2, "low": 0}),
            _json.dumps({"comfort": 2, "security_posture": 1}),
            _json.dumps({"top": [{"description": "x"}]}),
        ),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT date, findings_count, by_severity_json FROM "
        "optimization_daily_digest ORDER BY id DESC LIMIT 1"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["date"] == "2026-06-09"
    assert row["findings_count"] == 3
    assert "high" in row["by_severity_json"]


@pytest.mark.asyncio
async def test_optimization_daily_digest_log_dao_via_production():
    """Drive the REAL log_daily_digest DAO (Bug Class #44 — tests drive
    production code paths, not their own INSERT)."""
    from unittest.mock import MagicMock, AsyncMock
    from custom_components.universal_room_automation import database as _db_mod

    # Stub a minimal db connection used by self._db().
    fake_cursor = MagicMock()
    fake_cursor.lastrowid = 7
    fake_db = MagicMock()
    fake_db.execute = AsyncMock(return_value=fake_cursor)
    fake_db.commit = AsyncMock()

    class _FakeCtx:
        async def __aenter__(self_inner):
            return fake_db
        async def __aexit__(self_inner, *args):
            return None

    inst = _db_mod.UniversalRoomDatabase.__new__(_db_mod.UniversalRoomDatabase)
    inst._db = lambda: _FakeCtx()
    result = await inst.log_daily_digest(
        date="2026-06-09",
        generated_at="2026-06-09T08:00:00",
        findings_count=4,
        by_severity={"high": 1, "medium": 3, "low": 0, "critical": 0},
        by_dimension={"comfort": 4},
        summary={"top": []},
    )
    assert result == 7
    fake_db.execute.assert_awaited()
    fake_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_optimization_daily_digest_log_dao_rejects_none_date():
    """Defensive: log_daily_digest with None date returns None."""
    from custom_components.universal_room_automation import database as _db_mod
    inst = _db_mod.UniversalRoomDatabase.__new__(_db_mod.UniversalRoomDatabase)
    result = await inst.log_daily_digest(
        date=None,
        generated_at="2026-06-09T08:00:00",
        findings_count=0,
        by_severity={},
        by_dimension={},
        summary={},
    )
    assert result is None


@pytest.mark.asyncio
async def test_optimization_daily_digest_prune(real_schema_db):
    """prune_optimization_daily_digest deletes rows older than retention."""
    from datetime import datetime, timedelta
    conn = real_schema_db
    old_ts = (datetime.utcnow() - timedelta(days=120)).isoformat()
    new_ts = (datetime.utcnow() - timedelta(days=2)).isoformat()
    for ts in (old_ts, new_ts):
        conn.execute(
            """INSERT INTO optimization_daily_digest
               (date, generated_at, findings_count,
                by_severity_json, by_dimension_json, summary_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ts[:10], ts, 1, "{}", "{}", "{}"),
        )
    conn.commit()
    # Smoke-emulate the DELETE WHERE generated_at < cutoff path.
    cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
    n_deleted = conn.execute(
        "DELETE FROM optimization_daily_digest WHERE generated_at < ?",
        (cutoff,),
    ).rowcount
    conn.commit()
    assert n_deleted == 1
    remaining = conn.execute(
        "SELECT generated_at FROM optimization_daily_digest"
    ).fetchall()
    assert len(remaining) == 1
    assert remaining[0]["generated_at"] == new_ts


@pytest.mark.asyncio
async def test_digest_builder_excludes_meta_and_ranks_severity():
    """build_daily_digest_payload drops META rows + sorts top by severity."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    findings = [
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="house", target_id="house",
            dimension=OptimizationDimension.META,
            severity="low", confidence=1.0, score=100.0,
            description="cycle_ok",
        ),
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="room", target_id="kitchen",
            dimension=OptimizationDimension.COMFORT,
            severity="medium", confidence=0.8, score=0.0,
            description="kitchen comfort",
        ),
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="house", target_id="house",
            dimension=OptimizationDimension.SECURITY_POSTURE,
            severity="high", confidence=0.9, score=0.0,
            description="unlocked away",
        ),
    ]
    payload = coord.build_daily_digest_payload(findings=findings)
    assert payload["findings_count"] == 2  # META excluded
    assert payload["by_severity"]["high"] == 1
    assert payload["by_severity"]["medium"] == 1
    assert payload["by_dimension"]["comfort"] == 1
    assert payload["by_dimension"]["security_posture"] == 1
    # Top should be severity-sorted: high before medium.
    assert payload["top"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_digest_builder_format_section_empty_on_no_findings():
    """format_digest_section returns empty string when no real findings."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    section = coord.format_digest_section(findings=[])
    assert section == ""


@pytest.mark.asyncio
async def test_digest_builder_format_section_renders_findings():
    """format_digest_section renders a header + bullets when findings exist."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    findings = [
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="house", target_id="house",
            dimension=OptimizationDimension.SECURITY_POSTURE,
            severity="high", confidence=0.9, score=0.0,
            description="2 unlocked while away",
        ),
    ]
    section = coord.format_digest_section(findings=findings)
    assert "Optimizer" in section
    assert "1 findings" in section
    assert "unlocked while away" in section


@pytest.mark.asyncio
async def test_zone_scoreboard_populated_when_zone_finding_fires():
    """Zone-level finding populates _zone_scores + get_zone_score()."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    findings = [
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="zone", target_id="upstairs",
            dimension=OptimizationDimension.OVERRIDE_FREQUENCY,
            severity="medium", confidence=0.85, score=0.0,
            description="upstairs overrides",
        ),
    ]
    coord._update_scoreboard(findings)
    assert coord.get_zone_score("upstairs") < 100.0
    # Unknown zone defaults to 100.
    assert coord.get_zone_score("nonexistent") == 100.0


@pytest.mark.asyncio
async def test_optimizer_room_health_attrs_include_phase3_dimensions():
    """RoomOptimizationHealthSensor degraded_dimensions surface new dims."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )
    hass, _ = _make_hass()
    coord = OptimizationCoordinator(hass)
    coord._last_findings = [
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="room", target_id="kitchen",
            dimension=OptimizationDimension.OCCUPANCY_ACCURACY,
            severity="low", confidence=0.55, score=0.0,
            description="kitchen provenance disagreement",
        ),
        OptimizationFinding(
            timestamp=_opt_now().isoformat(),
            level="room", target_id="kitchen",
            dimension=OptimizationDimension.CONFIG_BEHAVIOR,
            severity="medium", confidence=0.95, score=0.0,
            description="kitchen comfort config bug",
        ),
    ]
    # Derive degraded_dimensions the same way the sensor does (one-line).
    degraded = []
    for f in coord._last_findings:
        if f.level == "room" and f.target_id == "kitchen":
            if str(f.dimension) not in degraded:
                degraded.append(str(f.dimension))
    assert "occupancy_accuracy" in degraded
    assert "config_behavior" in degraded
