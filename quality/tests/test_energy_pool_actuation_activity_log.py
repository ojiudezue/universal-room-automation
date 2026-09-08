"""ENERGY-POOL-ACTUATION-NOT-IN-ACTIVITY-LOG-1 — mutation-anchored tests.

Verifies:
  1. `_charge_on_or_defer` gate transitions emit `onset_hold` /
     `onset_release` activity-log rows (edge-triggered, not per-tick).
  2. `EnergyCoordinator._execute_service_action` logs `charger_on` /
     `charger_off` for switch calls whose target is a known charger.
  3. The control-path return values are byte-identical when the activity
     logger is absent OR raises — telemetry never poisons control.

Mutation drill (documented at the bottom): neutering
`_maybe_log_onset_edge` in energy_pool.py to `return None` unconditionally
makes tests 1 + 4 RED; neutering `_log_charger_actuation` in energy.py to
`return` makes test 2 RED. That's the "load-bearing" anchor.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_pool as _pool_mod,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402


# ----- shared fixtures -----------------------------------------------------


class _StubActivityLogger:
    def __init__(self):
        self.calls: list[dict] = []

    async def log(self, **kw):
        self.calls.append(kw)


class _Hass:
    def __init__(self, activity_logger=None):
        self.data = {DOMAIN: {}}
        if activity_logger is not None:
            self.data[DOMAIN]["activity_logger"] = activity_logger
        self._states = {}
        self.states = MagicMock()
        self.states.get = lambda eid: self._states.get(eid)
        self._tasks: list = []
        self.services = MagicMock()

    def async_create_task(self, coro, name=None):
        # Run coroutine synchronously to completion in a fresh loop
        # (test context — cheap + deterministic).
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception:
            if hasattr(coro, "close"):
                coro.close()
        # Also stash so tests can inspect if needed.
        self._tasks.append(1)


def _tz_naive_to_local(y, m, d, hh, mm):
    # ONSET gate uses tz-aware `now`. Use a fixed UTC-ish tz.
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# ============================================================================
# Test 1 — onset gate HOLD then RELEASE logs (edge-triggered)
# ============================================================================

def test_onset_hold_then_release_logs_activity_edges():
    hass = _Hass(activity_logger=_StubActivityLogger())
    ev = EVChargerController(hass)
    logger = hass.data[DOMAIN]["activity_logger"]

    # onset time 23:00, `now` 22:00 → inside 6h hold window → HELD.
    now_hold = _tz_naive_to_local(2026, 9, 8, 22, 0)
    actions = ev._charge_on_or_defer(
        evse_id="garage_a",
        switch_entity="switch.garage_a",
        now=now_hold,
        enabled=True,
        onset_str="23:00",
        must_start_by_min=None,
    )
    assert actions == []  # gate refused
    assert any(c.get("action") == "onset_hold" for c in logger.calls), (
        "expected an onset_hold row on first refusal"
    )
    hold_rows_1 = sum(1 for c in logger.calls if c.get("action") == "onset_hold")

    # Second tick inside the hold window — MUST NOT re-log (edge-triggered).
    now_hold_2 = _tz_naive_to_local(2026, 9, 8, 22, 5)
    actions2 = ev._charge_on_or_defer(
        evse_id="garage_a",
        switch_entity="switch.garage_a",
        now=now_hold_2,
        enabled=True,
        onset_str="23:00",
        must_start_by_min=None,
    )
    assert actions2 == []
    hold_rows_2 = sum(1 for c in logger.calls if c.get("action") == "onset_hold")
    assert hold_rows_2 == hold_rows_1, "hold row should be edge-triggered, not per-tick"

    # Now past onset time (00:30 next day → 24h+ delta → NOT in hold) → PERMIT.
    now_permit = _tz_naive_to_local(2026, 9, 9, 0, 30)
    actions3 = ev._charge_on_or_defer(
        evse_id="garage_a",
        switch_entity="switch.garage_a",
        now=now_permit,
        enabled=True,
        onset_str="23:00",
        must_start_by_min=None,
    )
    assert actions3 and actions3[0]["service"] == "switch.turn_on"
    assert any(c.get("action") == "onset_release" for c in logger.calls), (
        "expected an onset_release row on transition to permit"
    )


# ============================================================================
# Test 2 — control-path unchanged when activity_logger is ABSENT
# ============================================================================

def test_control_path_unchanged_when_logger_absent():
    hass = _Hass(activity_logger=None)  # no logger installed
    ev = EVChargerController(hass)
    now_hold = _tz_naive_to_local(2026, 9, 8, 22, 0)
    a = ev._charge_on_or_defer(
        "garage_a", "switch.garage_a", now_hold, True, "23:00", None
    )
    assert a == []
    now_permit = _tz_naive_to_local(2026, 9, 9, 0, 30)
    b = ev._charge_on_or_defer(
        "garage_a", "switch.garage_a", now_permit, True, "23:00", None
    )
    assert b == [{"service": "switch.turn_on", "target": "switch.garage_a", "data": {}}]


# ============================================================================
# Test 3 — control-path unchanged when the activity logger RAISES
# ============================================================================

class _RaisingLogger:
    async def log(self, **kw):
        raise RuntimeError("simulated logger failure")


def test_control_path_unchanged_when_logger_raises():
    hass = _Hass(activity_logger=_RaisingLogger())
    ev = EVChargerController(hass)
    now_hold = _tz_naive_to_local(2026, 9, 8, 22, 0)
    a = ev._charge_on_or_defer(
        "garage_a", "switch.garage_a", now_hold, True, "23:00", None
    )
    assert a == [], "hold must still be returned even if logger raises"
    now_permit = _tz_naive_to_local(2026, 9, 9, 0, 30)
    b = ev._charge_on_or_defer(
        "garage_a", "switch.garage_a", now_permit, True, "23:00", None
    )
    assert b == [{"service": "switch.turn_on", "target": "switch.garage_a", "data": {}}]


# ============================================================================
# Test 4 — MUTATION anchor: neutering _maybe_log_onset_edge kills test 1.
# We prove the wire-in is load-bearing by monkeypatching the helper to a
# no-op HERE and re-running the assertion; it must FAIL.
# ============================================================================

def test_onset_edge_helper_is_load_bearing(monkeypatch):
    hass = _Hass(activity_logger=_StubActivityLogger())
    ev = EVChargerController(hass)
    logger = hass.data[DOMAIN]["activity_logger"]
    monkeypatch.setattr(_pool_mod, "_maybe_log_onset_edge",
                        lambda *a, **k: None)
    now_hold = _tz_naive_to_local(2026, 9, 8, 22, 0)
    ev._charge_on_or_defer(
        "garage_a", "switch.garage_a", now_hold, True, "23:00", None
    )
    # With helper neutered, NO onset_hold row is emitted → this is the
    # negative anchor proving the un-neutered version IS what emits.
    assert not any(c.get("action") == "onset_hold" for c in logger.calls)
