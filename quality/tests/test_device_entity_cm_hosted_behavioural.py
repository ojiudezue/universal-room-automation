"""Behavioural tests for the FIX-6 / FIX-7 / FIX-10 CM-hosted coroutines
in aggregation.py — actually EXECUTE the coroutines rather than
source-grep them (per orchestrator independent-verification round on
2026-09-03; the previous source-anchor tests were hollow — a bare
`return` at the top of the coroutine left every assert GREEN).

Harness reuses the pattern proven by
`quality/tests/test_guest_count_dedup_migrate.py` — `_provenance_harness`
+ a couple of extra stubs — which is enough to import
`custom_components.universal_room_automation.aggregation` +
`.binary_sensor` + `.sensor` end-to-end.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — side effects (HA stubs)
from _provenance_harness import make_hass

# ---------------------------------------------------------------------------
# Extra stubs the harness doesn't cover (mirrors test_guest_count_dedup_migrate).
# ---------------------------------------------------------------------------
if "homeassistant.helpers.restore_state" not in sys.modules:
    _rs = types.ModuleType("homeassistant.helpers.restore_state")

    class _RestoreEntity:  # noqa: D401
        """Stub RestoreEntity."""

    _rs.RestoreEntity = _RestoreEntity
    sys.modules["homeassistant.helpers.restore_state"] = _rs

import homeassistant.helpers.update_coordinator as _uc  # type: ignore  # noqa: E402
if not hasattr(_uc, "CoordinatorEntity"):
    class _CoordinatorEntityMeta(type):
        def __getitem__(cls, item):
            return cls

    class _CoordinatorEntity(metaclass=_CoordinatorEntityMeta):  # noqa: D401
        """Stub CoordinatorEntity."""

        def __init__(self, *a, **kw):
            pass

    _uc.CoordinatorEntity = _CoordinatorEntity
if not hasattr(_uc, "DataUpdateCoordinator"):
    _uc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
if not hasattr(_uc, "UpdateFailed"):
    _uc.UpdateFailed = Exception

# Stub homeassistant.config_entries.ConfigEntryState so
# `_integration_entry_is_loaded` can compare against LOADED.
import homeassistant.config_entries as _ce  # noqa: E402
if not hasattr(_ce, "ConfigEntryState"):
    class _ConfigEntryState:
        LOADED = "loaded"
        NOT_LOADED = "not_loaded"

    _ce.ConfigEntryState = _ConfigEntryState

# Stub homeassistant.helpers.start.async_at_started — we'll monkeypatch
# per-test to capture the deferred callback.
if "homeassistant.helpers.start" not in sys.modules:
    _st = types.ModuleType("homeassistant.helpers.start")

    def _async_at_started_default(hass, cb):
        return lambda: None  # returns unsub

    _st.async_at_started = _async_at_started_default
    sys.modules["homeassistant.helpers.start"] = _st

# Import the modules-under-test.
from custom_components.universal_room_automation import (  # noqa: E402
    aggregation as agg_mod,
)
from custom_components.universal_room_automation import (  # noqa: E402
    binary_sensor as bs_mod,
)
from custom_components.universal_room_automation import (  # noqa: E402
    sensor as sensor_mod,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_TRACKED_PERSONS,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
)




@pytest.fixture(autouse=True)
def _fresh_event_loop():
    """Ensure each test has a valid event loop (other tests may close it)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

# ---------------------------------------------------------------------------
# Fake config-entry + fake async_add_entities + fake event helpers.
# ---------------------------------------------------------------------------


class _FakeEntry:
    """Minimal ConfigEntry-shaped fake supporting async_on_unload."""

    def __init__(self, entry_type: str, entry_id: str, data: dict | None = None):
        self.data = {CONF_ENTRY_TYPE: entry_type, **(data or {})}
        self.options = {}
        self.entry_id = entry_id
        self.state = _ce.ConfigEntryState.LOADED
        self._unload_callbacks: list = []

    def async_on_unload(self, cb):
        self._unload_callbacks.append(cb)


def _make_add_entities():
    """Return (fake_add, added_list) — fake_add appends the batch to added_list."""
    added: list = []

    def _fake_add(entities, *args, **kwargs):
        added.append(list(entities))

    return _fake_add, added


def _patch_async_at_started(monkeypatch, capture):
    """Install an async_at_started that captures the callback into capture['cb'].

    Looks up the module fresh via sys.modules (some test-suite modules replace
    the module object entirely, so a cached reference goes stale)."""
    def _at_started(hass, cb):
        capture["cb"] = cb
        capture["calls"] = capture.get("calls", 0) + 1
        return lambda: None

    import sys as _s
    mod = _s.modules.get("homeassistant.helpers.start")
    assert mod is not None, "helpers.start module missing"
    monkeypatch.setattr(mod, "async_at_started", _at_started, raising=False)


def _patch_async_call_later(monkeypatch, capture):
    """Install an async_call_later that captures scheduled retries.

    Looks up the module fresh via sys.modules for the same reason as above."""
    def _call_later(hass, delay, cb):
        capture.setdefault("scheduled", []).append((delay, cb))
        return lambda: None

    import sys as _s
    mod = _s.modules.get("homeassistant.helpers.event")
    assert mod is not None, "helpers.event module missing"
    monkeypatch.setattr(mod, "async_call_later", _call_later, raising=False)


# ---------------------------------------------------------------------------
# FIX-6 (behavioural) — CM-hosted sensor setup registers the House pair
# under the CM entry.
# ---------------------------------------------------------------------------


def test_fix6_cm_hosted_sensors_registers_house_pair_under_cm_entry():
    """Actually EXECUTES async_setup_cm_hosted_aggregation_sensors and
    asserts phase-1 registers exactly the two House-level sensor classes
    (constructed with the CM entry). A `return` at the top of the
    coroutine leaves `added` empty -> RED.
    """
    hass = make_hass()
    cm_entry = _FakeEntry(ENTRY_TYPE_COORDINATOR_MANAGER, "cm_entry_id")
    fake_add, added = _make_add_entities()

    _run(
        agg_mod.async_setup_cm_hosted_aggregation_sensors(hass, cm_entry, fake_add)
    )

    # Phase 1 registered exactly one batch of 2 entities.
    assert added, (
        "FIX-6 behavioural: async_setup_cm_hosted_aggregation_sensors did "
        "NOT call async_add_entities — coroutine body may be neutered"
    )
    phase1 = added[0]
    assert len(phase1) == 2, (
        f"FIX-6 behavioural: phase-1 should register 2 House sensors, got "
        f"{len(phase1)}: {[type(e).__name__ for e in phase1]}"
    )
    kinds = {type(e).__name__ for e in phase1}
    assert kinds == {"HouseNextRoomAccuracySensor", "HouseRoutineStatusSensor"}, (
        f"FIX-6 behavioural: phase-1 registered wrong classes: {kinds}"
    )
    # Each must be an INSTANCE of the sensor.py-defined class (identity check).
    for e in phase1:
        assert isinstance(e, (
            sensor_mod.HouseNextRoomAccuracySensor,
            sensor_mod.HouseRoutineStatusSensor,
        )), f"FIX-6 behavioural: phase-1 entity is wrong type: {type(e)}"


def test_fix6_cm_hosted_sensors_early_return_on_wrong_entry_type():
    """If the entry is not the CM entry, the coroutine must not register."""
    hass = make_hass()
    non_cm_entry = _FakeEntry(ENTRY_TYPE_INTEGRATION, "int_entry_id")
    fake_add, added = _make_add_entities()

    _run(
        agg_mod.async_setup_cm_hosted_aggregation_sensors(hass, non_cm_entry, fake_add)
    )
    assert added == [], "coroutine must early-return on non-CM entry"


# ---------------------------------------------------------------------------
# FIX-6 (behavioural) — CM-hosted BINARY coroutine registers the CORRECT
# SafetyAlert/SecurityAlert classes (binary_sensor.py-defined, NOT
# aggregation.py's Whole-House pair with the same names). This is the
# behavioural anchor for CRITICAL-B1.
# ---------------------------------------------------------------------------


def test_fix6_cm_hosted_binaries_are_binary_sensor_module_classes():
    """B1 behavioural: the CM binary coroutine must construct the
    binary_sensor.py-defined pair (which has coordinator-device
    unique_ids). Constructing the aggregation.py Whole-House pair would
    re-open the split-ownership bug.
    """
    hass = make_hass()
    cm_entry = _FakeEntry(ENTRY_TYPE_COORDINATOR_MANAGER, "cm_entry_id")
    fake_add, added = _make_add_entities()

    _run(
        agg_mod.async_setup_cm_hosted_aggregation_binary_sensors(
            hass, cm_entry, fake_add
        )
    )
    assert added, (
        "FIX-6 behavioural: CM binary coroutine did NOT call "
        "async_add_entities — body may be neutered"
    )
    batch = added[0]
    assert len(batch) == 2, (
        f"CM binary coroutine should register 2 entities, got {len(batch)}"
    )
    # Each entity must be an INSTANCE of the binary_sensor.py class, NOT
    # aggregation.py's same-named Whole-House class.
    for e in batch:
        assert isinstance(e, (
            bs_mod.SafetyAlertBinarySensor, bs_mod.SecurityAlertBinarySensor,
        )), (
            f"CRITICAL-B1 regression: CM binary entity is not the "
            f"binary_sensor.py class — got {type(e).__module__}.{type(e).__name__}"
        )
        assert not isinstance(e, (
            agg_mod.SafetyAlertBinarySensor, agg_mod.SecurityAlertBinarySensor,
        )), (
            f"CRITICAL-B1 regression: CM binary entity is the aggregation.py "
            f"Whole-House class (wrong ownership) — {type(e).__module__}.{type(e).__name__}"
        )


# ---------------------------------------------------------------------------
# FIX-7 (behavioural) — exactly-once guard: invoking the deferred
# per-person callback TWICE registers phase-2 only ONCE.
# ---------------------------------------------------------------------------


def _fake_person_coordinator():
    pc = MagicMock()
    pc.data = {}
    return pc


def test_fix7_deferred_per_person_registers_once_when_invoked_twice(monkeypatch):
    """Directly drive the deferred callback captured from async_at_started
    twice. FIX-7 guard flips `done` -> True on first success, so the
    second invocation MUST be a no-op (no additional async_add_entities
    call). A neuter that removes the done-guard OR the done-flip makes
    fake_add fire twice and this test RED.
    """
    hass = make_hass()
    integration_entry = _FakeEntry(
        ENTRY_TYPE_INTEGRATION, "int_entry_id",
        data={CONF_TRACKED_PERSONS: ["person.alice", "person.bob"]},
    )
    integration_entry.state = _ce.ConfigEntryState.LOADED

    # hass.config_entries.async_entries returns the INTEGRATION entry so
    # _resolve_integration_entry can find it.
    hass.config_entries.async_entries = MagicMock(return_value=[integration_entry])
    # person_coordinator present -> phase 2 will actually register.
    hass.data.setdefault(DOMAIN, {})["person_coordinator"] = _fake_person_coordinator()

    cm_entry = _FakeEntry(ENTRY_TYPE_COORDINATOR_MANAGER, "cm_entry_id")
    fake_add, added = _make_add_entities()

    at_start = {}
    _patch_async_at_started(monkeypatch, at_start)

    _run(
        agg_mod.async_setup_cm_hosted_aggregation_sensors(hass, cm_entry, fake_add)
    )

    # Phase 1 fired synchronously (batch 0). Phase 2 callback captured.
    assert "cb" in at_start, "async_at_started callback not captured"
    assert len(added) == 1, "unexpected extra registration before deferred fire"

    # Fire the deferred callback TWICE.
    _run(at_start["cb"]())
    n_after_first = len(added)
    _run(at_start["cb"]())
    n_after_second = len(added)

    # Phase 2 batch registered on first fire (2 persons * 2 sensor kinds = 4).
    assert n_after_first == 2, (
        f"FIX-7 behavioural: first deferred fire should add phase-2 batch, "
        f"total registrations {n_after_first}"
    )
    phase2_batch = added[1]
    assert len(phase2_batch) == 4, (
        f"FIX-7: phase-2 batch should have 4 entities (2 persons * 2 kinds), got {len(phase2_batch)}"
    )
    kinds = sorted(type(e).__name__ for e in phase2_batch)
    assert kinds == [
        "PersonNextRoomAccuracySensor", "PersonNextRoomAccuracySensor",
        "PersonRoutineStatusSensor", "PersonRoutineStatusSensor",
    ], f"FIX-7: phase-2 wrong classes: {kinds}"

    # Second deferred fire is a NO-OP (done-guard held).
    assert n_after_second == n_after_first, (
        f"FIX-7 behavioural: second deferred fire re-registered "
        f"({n_after_second} batches vs {n_after_first} after first) — "
        f"the double-add is the _2 mint mechanism"
    )


# ---------------------------------------------------------------------------
# FIX-10 (behavioural) — retry re-arms when prereqs missing; on eventual
# success, phase-2 registers.
# ---------------------------------------------------------------------------


def test_fix10_deferred_retry_when_person_coordinator_absent_then_registers(monkeypatch):
    """FIX-10 behavioural: with INTEGRATION LOADED but person_coordinator
    ABSENT at HA-started, the deferred branch must SCHEDULE a retry via
    async_call_later (not silently give up). When the retry re-fires
    after person_coordinator is set, phase-2 registers the 4
    per-person sensors.

    Neutering the retry-scheduling (falling back to the old one-shot
    early-return) leaves nothing in `_scheduled` and no phase-2 batch,
    turning this RED.
    """
    hass = make_hass()
    integration_entry = _FakeEntry(
        ENTRY_TYPE_INTEGRATION, "int_entry_id",
        data={CONF_TRACKED_PERSONS: ["person.alice", "person.bob"]},
    )
    integration_entry.state = _ce.ConfigEntryState.LOADED
    hass.config_entries.async_entries = MagicMock(return_value=[integration_entry])
    # person_coordinator NOT set yet — first fire must retry.
    hass.data.setdefault(DOMAIN, {}).pop("person_coordinator", None)

    cm_entry = _FakeEntry(ENTRY_TYPE_COORDINATOR_MANAGER, "cm_entry_id")
    fake_add, added = _make_add_entities()

    at_start = {}
    call_later = {}
    _patch_async_at_started(monkeypatch, at_start)
    _patch_async_call_later(monkeypatch, call_later)

    _run(
        agg_mod.async_setup_cm_hosted_aggregation_sensors(hass, cm_entry, fake_add)
    )
    # Phase-1 fired.
    assert len(added) == 1
    assert "cb" in at_start

    # First deferred fire: person_coordinator missing -> retry scheduled.
    _run(at_start["cb"]())
    assert call_later.get("scheduled"), (
        "FIX-10 behavioural: deferred branch did NOT schedule an "
        "async_call_later retry when person_coordinator was absent"
    )
    delay, retry_cb = call_later["scheduled"][0]
    assert delay > 0, "FIX-10: retry delay must be positive"
    # No phase-2 batch yet.
    assert len(added) == 1

    # Now set person_coordinator and fire the retry -> phase-2 registers.
    hass.data[DOMAIN]["person_coordinator"] = _fake_person_coordinator()
    _run(retry_cb())
    assert len(added) == 2, (
        "FIX-10 behavioural: retry callback did not register phase-2 after "
        "prereqs became available"
    )
    phase2 = added[1]
    kinds = sorted(type(e).__name__ for e in phase2)
    assert kinds == [
        "PersonNextRoomAccuracySensor", "PersonNextRoomAccuracySensor",
        "PersonRoutineStatusSensor", "PersonRoutineStatusSensor",
    ], f"FIX-10 phase-2 wrong classes: {kinds}"

    # Handle registered on cm_entry for unload safety.
    assert cm_entry._unload_callbacks, (
        "FIX-10 behavioural: retry handle not registered with "
        "cm_entry.async_on_unload — leak on reload"
    )


def test_fix10_deferred_gives_up_after_max_retries(monkeypatch):
    """FIX-10 boundedness: retry loop must respect a max-attempts cap so
    a permanent prereq-miss doesn't schedule forever. After the cap, no
    further async_call_later handles are added and no phase-2 batch
    fires.
    """
    hass = make_hass()
    integration_entry = _FakeEntry(
        ENTRY_TYPE_INTEGRATION, "int_entry_id",
        data={CONF_TRACKED_PERSONS: ["person.alice"]},
    )
    integration_entry.state = _ce.ConfigEntryState.LOADED
    hass.config_entries.async_entries = MagicMock(return_value=[integration_entry])
    # person_coordinator stays absent for the ENTIRE test.
    hass.data.setdefault(DOMAIN, {}).pop("person_coordinator", None)

    cm_entry = _FakeEntry(ENTRY_TYPE_COORDINATOR_MANAGER, "cm_entry_id")
    fake_add, added = _make_add_entities()

    at_start = {}
    call_later = {}
    _patch_async_at_started(monkeypatch, at_start)
    _patch_async_call_later(monkeypatch, call_later)

    _run(
        agg_mod.async_setup_cm_hosted_aggregation_sensors(hass, cm_entry, fake_add)
    )
    # Drive up to a safe upper bound of retry firings (must eventually
    # stop scheduling more).
    for _ in range(20):
        cb = at_start["cb"]
        _run(cb())
        # If retry scheduled, drain it too (drives the next cb).
        while call_later.get("scheduled"):
            _delay, next_cb = call_later["scheduled"].pop(0)
            _run(next_cb())

    # After the cap, no phase-2 batch was ever registered.
    assert len(added) == 1, (
        "FIX-10 boundedness: phase-2 registered somehow — test setup wrong "
        "(person_coordinator should never be present)"
    )
    # And the retry chain terminated (`_scheduled` empty).
    assert not call_later.get("scheduled"), (
        "FIX-10 boundedness: retry chain did not terminate after max attempts"
    )
