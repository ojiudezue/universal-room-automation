"""v4.5.19 — TransitionDetector listener-leak fix.

## Bug

`TransitionDetector.async_init` at `transitions.py:74` called
`hass.bus.async_listen(...)` and DISCARDED the unsubscribe callable.
The integration unload path at `__init__.py:2266-2268` only did
`del hass.data[DOMAIN]["transition_detector"]` — never tore down the
listener. Every URA reload (options-flow save, manual reload, etc.)
left the previous `_on_location_change` bound on the bus.

After N reloads, N+1 listeners fired per `ura_person_location_change`
event → N+1 calls to `_log_transition` → N+1 INSERTs into
room_transitions for one logical transition. Byte-identical duplicates
because all listeners received the same `event.data` payload.

## Impact (verified live, 2026-05-12 CDT)

- 11,284 / 134,569 = 8.4% byte-identical duplicate rows in
  room_transitions
- `same_second_distinct=0` (v4.5.18 metric) confirmed they are TRUE
  duplicates, not legitimate multi-step transitions
- `_build_priors_from_transitions` aggregates counts WITHOUT timestamp
  dedup, so duplicates inflated Bayesian priors over time. Periods with
  more accumulated reloads carry more weight than older periods
  — biasing predictions toward recent transitions

This is "rock solid prediction" relevant — first real prediction-quality
bug found this session.

## Fix

1. `transitions.py` — capture `async_listen` and `async_track_time_interval`
   return values into `self._unsub_bus` and `self._unsub_cleanup`
2. Add `async def async_teardown(self)` method that calls each unsub
3. `__init__.py` unload path — call `await transition_det.async_teardown()`
   BEFORE deleting from hass.data. Also fix a latent ordering bug
   (Bayesian listener removal was running AFTER `del`, so it always
   saw None — dead code path).

Tests below cover:
- The unsub captures (init wiring)
- The teardown releases both registrations
- Idempotency of teardown
- The unload-order fix (Bayesian listener removal before del)
- AST regression guards against accidental revert
"""

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def transitions_src() -> str:
    with open(
        "custom_components/universal_room_automation/transitions.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def init_src() -> str:
    with open(
        "custom_components/universal_room_automation/__init__.py"
    ) as f:
        return f.read()


# ===========================================================================
# AST + source-grep regression guards
# ===========================================================================


def test_async_listen_return_captured(transitions_src: str):
    """The bus.async_listen return value MUST be captured. The pre-v4.5.19
    code discarded it, causing the listener leak. Catches accidental revert.
    """
    # The new shape has `self._unsub_bus = self.hass.bus.async_listen(...)`
    assert "self._unsub_bus = self.hass.bus.async_listen(" in transitions_src, (
        "v4.5.19: bus.async_listen return value must be captured into "
        "self._unsub_bus. If reverted to bare `self.hass.bus.async_listen(...)`, "
        "the listener-leak bug returns."
    )


def test_async_track_time_interval_return_captured(transitions_src: str):
    """Same for the cleanup-timer registration — was also discarded
    pre-v4.5.19 (separate but parallel leak).
    """
    assert "self._unsub_cleanup = async_track_time_interval(" in transitions_src


def test_async_teardown_method_exists(transitions_src: str):
    """The teardown method is the release path. Must exist and call
    both unsub callables.
    """
    assert "async def async_teardown(self)" in transitions_src
    # Method body should reference both unsub fields
    start = transitions_src.find("async def async_teardown(self)")
    assert start >= 0
    next_def = transitions_src.find("\n    def ", start + 100)
    next_async = transitions_src.find("\n    async def ", start + 100)
    candidates = [c for c in (next_def, next_async) if c > 0]
    end = min(candidates) if candidates else start + 3000
    body = transitions_src[start:end]
    assert "self._unsub_bus" in body
    assert "self._unsub_cleanup" in body


def test_async_teardown_clears_unsub_handles(transitions_src: str):
    """After teardown, both handles must be None so the call is
    idempotent (safe to call multiple times during chaotic unload).
    """
    start = transitions_src.find("async def async_teardown(self)")
    assert start >= 0
    # End at the next def / async def line (or class boundary)
    next_def = transitions_src.find("\n    def ", start + 100)
    next_async = transitions_src.find("\n    async def ", start + 100)
    candidates = [c for c in (next_def, next_async) if c > 0]
    end = min(candidates) if candidates else start + 3000
    body = transitions_src[start:end]
    # Both handles set to None after release
    assert "self._unsub_bus = None" in body
    assert "self._unsub_cleanup = None" in body


def test_init_declares_unsub_handles(transitions_src: str):
    """The handles must be declared in __init__ so they exist BEFORE
    async_init runs. Defensive: a caller that calls teardown before
    async_init shouldn't AttributeError.
    """
    init_start = transitions_src.find("def __init__(\n        self,")
    if init_start < 0:
        init_start = transitions_src.find("def __init__(")
    assert init_start >= 0
    end = transitions_src.find("async def async_init", init_start)
    body = transitions_src[init_start:end]
    assert "self._unsub_bus" in body, (
        "__init__ must declare self._unsub_bus = None for defensive teardown"
    )
    assert "self._unsub_cleanup" in body


def test_unload_calls_teardown_before_del(init_src: str):
    """The integration unload path must call async_teardown BEFORE
    deleting the transition_detector from hass.data. Otherwise the
    teardown either runs against a stale reference or doesn't run at all.
    """
    # The new code calls async_teardown then enters the dict deletion loop
    teardown_idx = init_src.find("transition_det.async_teardown()")
    assert teardown_idx >= 0, (
        "Unload path must call transition_det.async_teardown(). "
        "v4.5.19 fix is missing or reverted."
    )
    # The deletion loop comes after
    del_idx = init_src.find(
        'for key in ["transition_detector", "pattern_learner"',
        teardown_idx,
    )
    assert del_idx > teardown_idx, (
        "async_teardown call must come BEFORE the dict deletion loop. "
        "Otherwise teardown runs against a stale (already-deleted) handle."
    )


def test_unload_bayesian_listener_removal_before_del(init_src: str):
    """Latent ordering bug fix: pre-v4.5.19, the Bayesian listener
    removal at __init__.py:2270-2277 ran AFTER the del at 2266-2268.
    `hass.data[DOMAIN].get("transition_detector")` returned None so
    `transition_det._listeners.remove(...)` never ran — dead code.
    v4.5.19 reorders so the listener removal runs before del.
    """
    bayes_idx = init_src.find(
        'bayesian_listener = hass.data[DOMAIN].pop("bayesian_transition_listener"'
    )
    assert bayes_idx >= 0
    del_idx = init_src.find(
        'for key in ["transition_detector", "pattern_learner"',
        bayes_idx - 200,  # search a bit before in case order is different
    )
    # del_idx might be before or after bayes_idx, but the bayesian
    # listener removal block (and its transition_det.get call) must
    # come BEFORE the deletion loop in current code.
    assert del_idx > bayes_idx, (
        "v4.5.19 reorders: Bayesian listener removal must come BEFORE "
        "the transition_detector del. Pre-v4.5.19 ordering had it after, "
        "making the .remove() call a no-op."
    )


def test_teardown_exception_handling_uses_warning(transitions_src: str):
    """Teardown failures must be logged at WARNING with traceback, NOT
    silently swallowed at debug — matches the v4.5.16 anti-swallow pattern.
    """
    start = transitions_src.find("async def async_teardown(self)")
    assert start >= 0
    # End at the next def / async def line (or class boundary)
    next_def = transitions_src.find("\n    def ", start + 100)
    next_async = transitions_src.find("\n    async def ", start + 100)
    candidates = [c for c in (next_def, next_async) if c > 0]
    end = min(candidates) if candidates else start + 3000
    body = transitions_src[start:end]
    assert "_LOGGER.warning" in body
    assert "exc_info=True" in body
    assert "_LOGGER.debug" not in body, (
        "v4.5.19 teardown must not use debug-level exception handling — "
        "that's the v4.5.17 anti-pattern."
    )


# ===========================================================================
# Behavior test — stub HA, instantiate TransitionDetector, verify lifecycle
# ===========================================================================


def _load_transition_detector():
    """Load TransitionDetector via importlib, stubbing minimal HA surface."""
    if "ura_v4519_transitions" in sys.modules:
        return sys.modules["ura_v4519_transitions"].TransitionDetector

    # Additive stubs — extend existing if other test loaders set them
    # first. Each branch ensures the specific attribute we need exists.
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")
        sys.modules["homeassistant"].__path__ = []
    if "homeassistant.core" not in sys.modules:
        sys.modules["homeassistant.core"] = types.ModuleType("homeassistant.core")
    ha_core = sys.modules["homeassistant.core"]
    if not hasattr(ha_core, "HomeAssistant"):
        ha_core.HomeAssistant = type("HomeAssistant", (), {})
    if not hasattr(ha_core, "Event"):
        ha_core.Event = type("Event", (), {})
    if not hasattr(ha_core, "callback"):
        ha_core.callback = lambda f: f

    if "homeassistant.util" not in sys.modules:
        sys.modules["homeassistant.util"] = types.ModuleType("homeassistant.util")
        sys.modules["homeassistant.util"].__path__ = []
    if "homeassistant.util.dt" not in sys.modules:
        ha_util_dt = types.ModuleType("homeassistant.util.dt")
        from datetime import datetime, timezone
        ha_util_dt.now = lambda: datetime.now()
        ha_util_dt.utcnow = lambda: datetime.now(timezone.utc)
        sys.modules["homeassistant.util.dt"] = ha_util_dt

    if "homeassistant.helpers" not in sys.modules:
        ha_helpers = types.ModuleType("homeassistant.helpers")
        ha_helpers.__path__ = []
        sys.modules["homeassistant.helpers"] = ha_helpers
    if "homeassistant.helpers.event" not in sys.modules:
        sys.modules["homeassistant.helpers.event"] = types.ModuleType(
            "homeassistant.helpers.event"
        )
    ha_helpers_event = sys.modules["homeassistant.helpers.event"]
    if not hasattr(ha_helpers_event, "async_track_time_interval"):
        ha_helpers_event.async_track_time_interval = lambda *a, **kw: (
            lambda: None
        )
    if not hasattr(ha_helpers_event, "async_call_later"):
        ha_helpers_event.async_call_later = lambda *a, **kw: None

    pkg = types.ModuleType("ura_v4519_pkg"); pkg.__path__ = []
    const = types.ModuleType("ura_v4519_pkg.const")
    const.PING_PONG_WINDOW_SECONDS = 30
    sys.modules["ura_v4519_pkg"] = pkg
    sys.modules["ura_v4519_pkg.const"] = const

    root = Path(__file__).resolve().parents[2]
    src = root / "custom_components" / "universal_room_automation" / \
        "transitions.py"
    spec = importlib.util.spec_from_file_location(
        "ura_v4519_pkg.transitions", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ura_v4519_pkg.transitions"] = mod
    mod.__package__ = "ura_v4519_pkg"
    spec.loader.exec_module(mod)
    sys.modules["ura_v4519_transitions"] = mod
    return mod.TransitionDetector


class _StubBus:
    def __init__(self):
        self.listeners: list = []

    def async_listen(self, event_type, callback):
        # Return an unsubscribe callable that removes this listener
        listener_id = (event_type, callback)
        self.listeners.append(listener_id)

        def unsub():
            if listener_id in self.listeners:
                self.listeners.remove(listener_id)
        return unsub


class _StubHass:
    def __init__(self):
        self.bus = _StubBus()


# Patch async_track_time_interval to return a counting unsub
_cleanup_unsub_calls = {"count": 0}


def _stub_async_track_time_interval(hass, callback, interval):
    def unsub():
        _cleanup_unsub_calls["count"] += 1
    return unsub


@pytest.mark.asyncio
async def test_async_init_registers_then_teardown_releases():
    """End-to-end: init → assert listener registered; teardown →
    assert listener released. Mirrors the actual reload sequence.
    """
    TransitionDetector = _load_transition_detector()
    # Override the imported async_track_time_interval inside the module
    mod = sys.modules["ura_v4519_transitions"]
    mod.async_track_time_interval = _stub_async_track_time_interval

    hass = _StubHass()
    detector = TransitionDetector(hass, person_coordinator=None, database=None)
    assert detector._unsub_bus is None, "Before async_init, no subscription"
    assert detector._unsub_cleanup is None
    assert len(hass.bus.listeners) == 0

    await detector.async_init()
    assert len(hass.bus.listeners) == 1, "After async_init, one listener"
    assert detector._unsub_bus is not None
    assert detector._unsub_cleanup is not None

    await detector.async_teardown()
    assert len(hass.bus.listeners) == 0, "After teardown, listener released"
    assert detector._unsub_bus is None, "Handle cleared post-teardown"
    assert detector._unsub_cleanup is None


@pytest.mark.asyncio
async def test_teardown_idempotent():
    """Calling teardown twice must not error (safe under chaotic unload)."""
    TransitionDetector = _load_transition_detector()
    mod = sys.modules["ura_v4519_transitions"]
    mod.async_track_time_interval = _stub_async_track_time_interval

    hass = _StubHass()
    detector = TransitionDetector(hass, person_coordinator=None, database=None)
    await detector.async_init()
    await detector.async_teardown()
    # Second call should be a no-op, not raise
    await detector.async_teardown()
    assert detector._unsub_bus is None
    assert detector._unsub_cleanup is None


@pytest.mark.asyncio
async def test_reload_simulation_no_listener_leak():
    """The canonical bug: simulate N reload cycles. After each cycle,
    listener count must return to 0 (or stay at N for current generation
    only). Without v4.5.19 fix, count would grow unboundedly.
    """
    TransitionDetector = _load_transition_detector()
    mod = sys.modules["ura_v4519_transitions"]
    mod.async_track_time_interval = _stub_async_track_time_interval

    hass = _StubHass()
    for cycle in range(5):
        detector = TransitionDetector(
            hass, person_coordinator=None, database=None,
        )
        await detector.async_init()
        assert len(hass.bus.listeners) == 1, (
            f"Cycle {cycle}: should have exactly 1 listener active "
            "(this cycle's detector). Pre-v4.5.19 would show N+1."
        )
        await detector.async_teardown()
        assert len(hass.bus.listeners) == 0, (
            f"Cycle {cycle}: should have 0 listeners after teardown. "
            "Pre-v4.5.19 would have N (the leak)."
        )


# Asyncio test marker — register with pytest-asyncio if available
def pytest_collection_modifyitems(items):
    pass  # placeholder; pytest.mark.asyncio handles via plugin
