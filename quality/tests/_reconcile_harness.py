"""Shared harness for the Reconcile-on-Return (v5.8.0, D2) test modules.

Mocks the homeassistant layer so ``actuator_reconciler.py`` imports cleanly,
and provides light fakes for a coordinator, hass, config entry, and state.

The reconciler module reads only ``homeassistant.core`` (callback) and
``homeassistant.helpers.event`` (async_track_state_change_event /
async_call_later) plus the URA const module — all mocked below.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from collections import deque
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    # Give every stub a __path__ so it stays a *package* — a bare ModuleType
    # without __path__ makes "import name.sub" fail with "not a package",
    # which was leaking into other test modules in the full-suite run.
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

# Capture registered timers so tests can fire them deterministically.
CALL_LATER_CAPTURES: list = []
TRACK_CAPTURES: list = []


def _fake_call_later(hass, delay, cb):
    unsub = MagicMock()
    CALL_LATER_CAPTURES.append({"delay": delay, "cb": cb, "unsub": unsub})
    return unsub


def _fake_track(hass, entities, cb):
    unsub = MagicMock()
    TRACK_CAPTURES.append({"entities": list(entities), "cb": cb, "unsub": unsub})
    return unsub


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _fake_track,
        "async_call_later": _fake_call_later,
        "async_track_time_interval": lambda hass, cb, interval: MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: MagicMock(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        existing = sys.modules.get(_name)
        if existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for k, v in _attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Register the real package tree as a lightweight namespace stub, using
# setdefault so we NEVER clobber a package another test module already
# imported first (that clobber caused sys.modules cross-contamination in the
# full-suite run). We spec-load only const + actuator_reconciler directly,
# NEVER triggering the package __init__.py (which imports un-mocked HA
# components). Mirrors the _provenance_harness pattern.
_cc_path = os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [_cc_path]
    sys.modules["custom_components"] = _cc

_ura_path = os.path.join(_cc_path, "universal_room_automation")
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura


def _spec_load(modname, filename):
    full = f"custom_components.universal_room_automation.{modname}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_ura_path, filename),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


_const_mod = _spec_load("const", "const.py")
actuator_reconciler = _spec_load("actuator_reconciler", "actuator_reconciler.py")

# Force the capturing fakes ONTO the reconciler module namespace, regardless of
# what another test harness left in sys.modules at import time. The reconciler
# binds these at module top via `from homeassistant.helpers.event import ...`,
# so patching the module attributes is the authoritative override for tests.
actuator_reconciler.async_track_state_change_event = _fake_track
actuator_reconciler.async_call_later = _fake_call_later

ActuatorReconciler = actuator_reconciler.ActuatorReconciler
DesiredState = actuator_reconciler.DesiredState


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeState:
    def __init__(self, entity_id, state, attributes=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        self.last_changed = datetime.now(timezone.utc)


class FakeStates:
    def __init__(self):
        self._states: dict = {}
        self.calls: list = []

    def set(self, entity_id, state, attributes=None):
        self._states[entity_id] = FakeState(entity_id, state, attributes)

    def get(self, entity_id):
        return self._states.get(entity_id)

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data)))


class FakeServices:
    def __init__(self, sink):
        self._sink = sink

    async def async_call(self, domain, service, data, blocking=False):
        self._sink.append((domain, service, dict(data)))


class FakeHass:
    def __init__(self):
        self.data: dict = {"universal_room_automation": {}}
        self.states = FakeStates()
        self.service_calls: list = []
        self.services = FakeServices(self.service_calls)
        self._tasks: list = []

    def async_create_task(self, coro):
        # Run the coroutine to completion synchronously for tests.
        import asyncio

        try:
            asyncio.get_event_loop().run_until_complete(coro)
        except RuntimeError:
            # If a loop is running, schedule; tests use run_until_complete so
            # this branch is rarely hit.
            self._tasks.append(coro)


class FakeEntry:
    def __init__(self, data=None, options=None, entry_id="entry_test"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id


class FakeAutomation:
    """Minimal RoomAutomation stand-in for the resolver."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self._sleep = False
        self._hvac_managing = False
        self.service_calls: list = []

    def is_sleep_mode_active(self):
        return self._sleep

    def is_dark(self, illuminance):
        if illuminance is None:
            return False
        threshold = self.config.get("illuminance_threshold", 20)
        return illuminance < threshold

    def _is_hvac_managing_fans(self):
        return self._hvac_managing

    async def _safe_service_call(self, domain, service, data, blocking=False):
        self.service_calls.append((domain, service, dict(data)))


class FakeCoordinator:
    def __init__(self, hass, data=None, options=None, coordinator_data=None):
        self.hass = hass
        self.entry = FakeEntry(data=data or {}, options=options or {})
        self.data = coordinator_data if coordinator_data is not None else {}
        self._skip_first_automation = False
        self._boot_settle_done = True
        self._switch_states: dict = {}
        self.automation = FakeAutomation(hass, {**self.entry.data, **self.entry.options})
        self.last_actions: list = []

    # Mirror the real coordinator surface the reconciler consults.
    def _is_automation_enabled(self):
        manual = self._switch_states.get("manual_mode")
        if manual is True:
            return False
        auto = self._switch_states.get("automation")
        return True if auto is None else auto

    def _get_room_switch_state(self, suffix):
        return self._switch_states.get(suffix)

    def set_last_action(self, action_type, description, entity=None):
        self.last_actions.append((action_type, description, entity))


def make_env(room_name="Bedroom", data=None, options=None, coordinator_data=None):
    """Return (hass, coordinator, reconciler) with sane defaults."""
    CALL_LATER_CAPTURES.clear()
    TRACK_CAPTURES.clear()
    hass = FakeHass()
    base = {"room_name": room_name}
    base.update(data or {})
    coord = FakeCoordinator(
        hass, data=base, options=options or {},
        coordinator_data=coordinator_data,
    )
    reconciler = ActuatorReconciler(coord)
    # D-HIGH clause-3 grace leak fix: the reconciler now applies an implicit
    # post-boot grace window for RECONCILE_POST_BOOT_GRACE_SECONDS after
    # construction (covers the reload path). Neutralize that implicit grace for
    # the default test env by back-dating construction, so guard-specific tests
    # exercise the guard under test rather than the boot grace. Tests that
    # explicitly want the grace active call note_boot_settle_released() or set
    # _created_monotonic themselves.
    reconciler._created_monotonic = reconciler._now() - 1_000_000.0
    coord._actuator_reconciler = reconciler
    return hass, coord, reconciler


def make_event(entity_id, old, new):
    """Build a state-change event dict shape (event.data.get(...))."""
    ev = MagicMock()
    old_state = FakeState(entity_id, old) if old is not None else None
    new_state = FakeState(entity_id, new) if new is not None else None
    ev.data = {
        "entity_id": entity_id,
        "old_state": old_state,
        "new_state": new_state,
    }
    return ev


def fire_available(reconciler, entity_id, hass, prior="unavailable", new="on"):
    """Simulate an unavailable->available edge for entity_id.

    Sets the live state to ``new`` and dispatches through the handler.
    """
    hass.states.set(entity_id, new)
    reconciler._handle_state_change(make_event(entity_id, prior, new))


def run_pending_coalesce(hass):
    """Fire every captured async_call_later coalesce timer (deepest first)."""
    import asyncio

    # Iterate a copy because firing may register more timers.
    for cap in list(CALL_LATER_CAPTURES):
        cb = cap["cb"]
        CALL_LATER_CAPTURES.remove(cap)
        cb(None)
    # Drain any tasks the callback scheduled.
    for coro in list(hass._tasks):
        hass._tasks.remove(coro)
        asyncio.get_event_loop().run_until_complete(coro)
