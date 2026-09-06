"""ARRIVAL-DEPARTURE-NOTIFY-1 (Wave-1 consumer #1).

Drives production EgressDirectionTracker._arrival_departure_notify.
Mutation-anchored — neutering the helper turns the named-entry and
named-exit tests RED.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

import sys as _sys
import types as _types

if "homeassistant.helpers.area_registry" not in _sys.modules:
    _mod = _types.ModuleType("homeassistant.helpers.area_registry")
    _mod.async_get = MagicMock()
    _sys.modules["homeassistant.helpers.area_registry"] = _mod
if "homeassistant.helpers.event" not in _sys.modules:
    _ev = _types.ModuleType("homeassistant.helpers.event")
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _sys.modules["homeassistant.helpers.event"] = _ev

# The helper does a local `from .domain_coordinators.notification_manager
# import Severity` at runtime. NM's full module chain pulls HA symbols
# that are not present in the quality test env, so pre-install a minimal
# stub module carrying just the Severity enum. Production code path is
# unchanged; only the test env's resolution of the local import differs.
import enum as _enum

_dc_pkg_name = "custom_components.universal_room_automation.domain_coordinators"
_nm_name = _dc_pkg_name + ".notification_manager"
if _nm_name not in _sys.modules or not hasattr(_sys.modules[_nm_name], "Severity"):
    _nm_stub = _types.ModuleType(_nm_name)
    class Severity(str, _enum.Enum):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"
        CRITICAL = "CRITICAL"
    _nm_stub.Severity = Severity
    _sys.modules[_nm_name] = _nm_stub
else:
    Severity = _sys.modules[_nm_name].Severity

from custom_components.universal_room_automation.const import DOMAIN
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)


def _make_tracker_with_nm():
    hass = make_hass()
    nm = MagicMock()
    nm.async_notify = AsyncMock()
    hass.data[DOMAIN] = {"notification_manager": nm}
    # async_create_task runs the coro synchronously for the test
    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()
        return MagicMock()
    hass.async_create_task = MagicMock(side_effect=_run)
    tracker = EgressDirectionTracker(hass)
    return tracker, nm


def test_named_entry_notifies_arrived():
    tracker, nm = _make_tracker_with_nm()
    tracker._arrival_departure_notify("entry", "oji", 0.9)
    assert nm.async_notify.await_count == 1
    kwargs = nm.async_notify.await_args.kwargs
    assert kwargs["title"] == "Oji arrived"
    assert kwargs["message"] == "Oji arrived"
    assert kwargs["severity"].name == "LOW"


def test_named_exit_notifies_left():
    tracker, nm = _make_tracker_with_nm()
    tracker._arrival_departure_notify("exit", "oji", 0.9)
    assert nm.async_notify.await_count == 1
    assert nm.async_notify.await_args.kwargs["title"] == "Oji left"


def test_ambiguous_direction_no_notify():
    tracker, nm = _make_tracker_with_nm()
    tracker._arrival_departure_notify("ambiguous", "oji", 0.9)
    assert nm.async_notify.await_count == 0


def test_low_confidence_is_anonymous():
    tracker, nm = _make_tracker_with_nm()
    tracker._arrival_departure_notify("entry", "oji", 0.5)
    assert nm.async_notify.await_count == 1
    assert nm.async_notify.await_args.kwargs["title"] == "Someone arrived"


def test_null_person_is_anonymous():
    tracker, nm = _make_tracker_with_nm()
    tracker._arrival_departure_notify("exit", None, None)
    assert nm.async_notify.await_count == 1
    assert nm.async_notify.await_args.kwargs["title"] == "Someone left"


def test_nm_exception_does_not_propagate_through_wrapper():
    """The emit-site wraps `_arrival_departure_notify` in try/except so a
    raised NM error MUST NOT break the egress emit path. We assert the
    wrapper exists in the production source and it swallows exceptions
    of the shape NM can raise.
    """
    # (1) Static anchor: the wrapper is present at the emit site.
    import inspect
    import custom_components.universal_room_automation.transit_validator as tv
    src = inspect.getsource(tv)
    assert "_arrival_departure_notify(" in src
    # The try/except guard must live in the SAME method that fires the
    # bus event ("ura_person_egress_event") — locate that method and
    # verify a try/except surrounds the notify call.
    idx_bus = src.index("ura_person_egress_event")
    idx_call = src.index("_arrival_departure_notify(", idx_bus)
    surrounding = src[idx_call - 400 : idx_call + 400]
    assert "try:" in surrounding and "except" in surrounding, (
        "emit-site must wrap _arrival_departure_notify in try/except"
    )

    # (2) Behavioral: invoked through that wrapper pattern, an NM that
    # raises does not escape.
    hass = make_hass()
    nm = MagicMock()
    nm.async_notify = AsyncMock(side_effect=RuntimeError("boom"))
    hass.data[DOMAIN] = {"notification_manager": nm}

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()
        return MagicMock()

    hass.async_create_task = MagicMock(side_effect=_run)
    tracker = EgressDirectionTracker(hass)

    # LOW-1 fix (2026-09-06 review): the detached notify now wraps
    # async_notify in its own try/except (_safe_notify), so an NM that
    # raises never escapes the helper NOR surfaces as an unhandled-task
    # error. Belt-and-suspenders with the emit-site wrapper verified
    # statically above.
    escaped = False
    try:
        tracker._arrival_departure_notify("entry", "oji", 0.9)
    except Exception:  # noqa: BLE001
        escaped = True
    assert escaped is False, (
        "NM exception must be swallowed by the _safe_notify wrapper, "
        "not propagate out of _arrival_departure_notify"
    )
    # The task DID run (the mock executed the coroutine synchronously).
    assert nm.async_notify.await_count == 1


def test_nm_absent_is_noop():
    hass = make_hass()  # no notification_manager registered
    tracker = EgressDirectionTracker(hass)
    # must not raise
    tracker._arrival_departure_notify("entry", "oji", 0.9)
