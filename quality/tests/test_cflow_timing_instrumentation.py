"""Tests for CONFIG-FLOW-SLOW-ONBOARDING-1 timing instrumentation.

Verifies:
    1. The class decorator preserves the original method name (so HA's
       ``getattr(flow, f'async_step_{step_id}')`` dispatch in
       homeassistant/data_entry_flow.py:483 still resolves).
    2. Calling a wrapped async_step_* logs both an ENTER and an EXIT
       record with the ``CFLOW-TIMING:`` prefix.
    3. Auto-detect helper wrapping accumulates per-step counters that
       are reset at each step entry and reported at each step exit.
"""

from __future__ import annotations

import asyncio
import logging

import pytest  # noqa: F401


def _run(coro):
    """Run a coroutine on a fresh loop that is set as current.

    ``asyncio.run`` closes the loop and clears ``get_event_loop`` state,
    which trips the ``pytest_homeassistant_custom_component`` fixture
    ``enable_event_loop_debug`` on the NEXT test setup. Setting the loop
    as current before we close it keeps HA's policy happy.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())

from custom_components.universal_room_automation._cflow_timing import (
    instrument_flow,
)


def _make_fake_flow_cls():
    """Build a fresh flow-like class each call so decorator state is not shared."""

    async def async_step_foo(self, user_input=None):
        self._get_area_entities("area_1", "sensor")
        self._rank_area_candidates("area_1")
        return {"type": "form", "step_id": "foo"}

    async def async_step_bar(self, user_input=None):
        return {"type": "form", "step_id": "bar"}

    def _get_area_entities(self, area_id, domain, device_class=None):
        return []

    def _rank_area_candidates(self, area_id, *args, **kwargs):
        return []

    return type(
        "FakeFlow",
        (),
        {
            "async_step_foo": async_step_foo,
            "async_step_bar": async_step_bar,
            "_get_area_entities": _get_area_entities,
            "_rank_area_candidates": _rank_area_candidates,
        },
    )


def test_decorator_preserves_step_names_for_ha_dispatch():
    Wrapped = instrument_flow(_make_fake_flow_cls())
    inst = Wrapped()

    # HA calls getattr(flow, f"async_step_{step_id}") — must resolve.
    assert hasattr(inst, "async_step_foo")
    assert hasattr(inst, "async_step_bar")
    assert inst.async_step_foo.__name__ == "async_step_foo"
    assert inst.async_step_bar.__name__ == "async_step_bar"


def test_wrapped_step_logs_enter_and_exit(caplog):
    Wrapped = instrument_flow(_make_fake_flow_cls())
    inst = Wrapped()

    caplog.set_level(logging.WARNING, logger="custom_components.universal_room_automation._cflow_timing")
    _run(inst.async_step_foo(None))

    msgs = [r.getMessage() for r in caplog.records if "CFLOW-TIMING" in r.getMessage()]
    assert any("ENTER" in m and "async_step_foo" in m for m in msgs), msgs
    assert any("EXIT" in m and "async_step_foo" in m for m in msgs), msgs


def test_autodetect_counters_reported_on_exit(caplog):
    Wrapped = instrument_flow(_make_fake_flow_cls())
    inst = Wrapped()

    caplog.set_level(logging.WARNING, logger="custom_components.universal_room_automation._cflow_timing")
    _run(inst.async_step_foo(None))

    exit_msgs = [
        r.getMessage()
        for r in caplog.records
        if "CFLOW-TIMING: EXIT" in r.getMessage() and "async_step_foo" in r.getMessage()
    ]
    assert exit_msgs, "no EXIT log emitted"
    # async_step_foo calls each helper exactly once.
    assert "autodetect_calls=2" in exit_msgs[-1], exit_msgs[-1]

    # Second step calls no helpers -> counter must reset at entry.
    caplog.clear()
    _run(inst.async_step_bar(None))
    exit_msgs = [
        r.getMessage()
        for r in caplog.records
        if "CFLOW-TIMING: EXIT" in r.getMessage() and "async_step_bar" in r.getMessage()
    ]
    assert exit_msgs
    assert "autodetect_calls=0" in exit_msgs[-1], exit_msgs[-1]


def test_decorator_is_idempotent():
    cls = _make_fake_flow_cls()
    once = instrument_flow(cls)
    twice = instrument_flow(cls)
    assert once is twice
    # Only wrapped ONCE (no double ENTER/EXIT).
    assert once.async_step_foo.__wrapped__.__name__ == "async_step_foo"
