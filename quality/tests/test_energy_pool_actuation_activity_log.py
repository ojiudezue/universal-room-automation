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
        # Test-context executor: prefer the currently-running loop if
        # any (H1 applier tests drive us from inside run_until_complete);
        # otherwise fall back to a fresh throwaway loop.
        try:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop is not None and loop.is_running():
                task = loop.create_task(coro)
                self._tasks.append(task)
                return task
            fresh = asyncio.new_event_loop()
            try:
                fresh.run_until_complete(coro)
            finally:
                fresh.close()
        except Exception:
            if hasattr(coro, "close"):
                try: coro.close()
                except Exception: pass
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


# ============================================================================
# H1 anchor — applier logs charger_on ONCE across repeated idempotent turn_on
# ticks (off-peak ensure-on re-issues every decision tick per Bug Class #43).
# RED if per-actuation edge cache is removed.
# ============================================================================

class _NoOpDict(dict):
    """Dict that never remembers a set — get() always returns None."""
    def get(self, k, default=None):
        return default
    def __setitem__(self, k, v):
        return None


def _make_energy_coord_stub_for_actuation():
    """Bind _execute_service_action + _log_charger_actuation onto a
    stub that carries just the attributes those methods touch, without
    constructing the full EnergyCoordinator (heavy HA wiring)."""
    import types as _types
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as _e,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        EVChargerController,
        SmartPlugController,
    )

    hass = _Hass(activity_logger=_StubActivityLogger())

    async def _async_call(domain, svc, data, blocking=False):
        return None
    hass.services.async_call = _async_call

    ev = EVChargerController(hass)
    plugs = SmartPlugController(
        hass,
        plug_entities=["switch.plug_a"],
        plug_config={"switch.plug_a": {}},
    )

    holder = _types.SimpleNamespace(hass=hass, _ev=ev, _smart_plugs=plugs)
    holder._execute_service_action = (
        _e.EnergyCoordinator._execute_service_action.__get__(holder, type(holder))
    )
    holder._log_charger_actuation = (
        _e.EnergyCoordinator._log_charger_actuation.__get__(holder, type(holder))
    )
    return holder


def test_h1_charger_on_edge_cached_across_repeated_ticks():
    import asyncio
    holder = _make_energy_coord_stub_for_actuation()
    logger = holder.hass.data[DOMAIN]["activity_logger"]

    spec = {"service": "switch.turn_on", "target": "switch.garage_a",
            "data": {}}
    loop = asyncio.new_event_loop()
    try:
        for _ in range(5):  # 5 idempotent ticks — off-peak ensure-on pattern
            loop.run_until_complete(holder._execute_service_action(spec))
    finally:
        loop.close()

    charger_on_rows = [c for c in logger.calls if c.get("action") == "charger_on"]
    assert len(charger_on_rows) == 1, (
        f"expected exactly one charger_on row across repeated turn_on "
        f"ticks; got {len(charger_on_rows)} "
        f"(H1 write-flood regression — edge cache missing/broken)"
    )

    spec_off = {"service": "switch.turn_off", "target": "switch.garage_a",
                "data": {}}
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(holder._execute_service_action(spec_off))
    finally:
        loop.close()
    charger_off_rows = [c for c in logger.calls if c.get("action") == "charger_off"]
    assert len(charger_off_rows) == 1


def test_h1_edge_cache_is_load_bearing():
    """Mutation anchor for H1: neuter the cache and prove per-tick
    flooding returns."""
    import asyncio
    holder = _make_energy_coord_stub_for_actuation()
    logger = holder.hass.data[DOMAIN]["activity_logger"]
    holder._charger_actuation_log_state = _NoOpDict()

    spec = {"service": "switch.turn_on", "target": "switch.garage_a", "data": {}}
    loop = asyncio.new_event_loop()
    try:
        for _ in range(3):
            loop.run_until_complete(holder._execute_service_action(spec))
    finally:
        loop.close()
    rows = [c for c in logger.calls if c.get("action") == "charger_on"]
    assert len(rows) == 3, (
        "with cache neutered, expected 3 rows across 3 ticks — proves "
        "the real cache is load-bearing"
    )


# ============================================================================
# H2 anchor — bypass_onset=True must NOT emit an ensure_on edge row, so an
# interleave of gated (hold) and bypass calls does NOT thrash the cache.
# RED if the bypass branch resumes logging permit rows.
# ============================================================================

def test_h2_bypass_onset_does_not_emit_ensure_on_edge():
    hass = _Hass(activity_logger=_StubActivityLogger())
    ev = EVChargerController(hass)
    logger = hass.data[DOMAIN]["activity_logger"]

    now_hold = _tz_naive_to_local(2026, 9, 8, 22, 0)
    for _ in range(5):
        # Gated call → hold (edge-logs once, then suppressed)
        ev._charge_on_or_defer(
            "garage_a", "switch.garage_a", now_hold, True, "23:00", None,
        )
        # Bypass call → emits turn_on but MUST NOT log an ensure_on edge
        acts = ev._charge_on_or_defer(
            "garage_a", "switch.garage_a", now_hold, True, "23:00", None,
            bypass_onset=True,
        )
        assert acts and acts[0]["service"] == "switch.turn_on"

    hold_rows = [c for c in logger.calls if c.get("action") == "onset_hold"]
    permit_ensure_on = [
        c for c in logger.calls
        if c.get("action") == "onset_release"
        and "leg=ensure_on" in c.get("description", "")
    ]
    assert len(hold_rows) == 1, (
        f"cache thrash regression — expected 1 onset_hold row across 5 "
        f"interleaved ticks; got {len(hold_rows)}"
    )
    assert permit_ensure_on == [], (
        f"H2 regression — bypass_onset=True must not emit ensure_on "
        f"permit edge rows; got {permit_ensure_on}"
    )
