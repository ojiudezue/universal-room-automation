"""Tests for XCORR-1: burst-demotion for isolated single-camera alerts.

Cycle: docs/planning/AUDIT_xcorr_engine_corroboration_probe.md (revised design).

Invariants under test:
  * The FIRST alert from a camera is ALWAYS full severity (sacred).
  * The Nth (N >= PERIMETER_BURST_MIN_ALERTS) alert from the SAME camera
    within PERIMETER_BURST_WINDOW_S is DEMOTED to LOW iff:
      (a) no sibling-engine corroboration on that camera,
      (b) no adjacent-camera activity per the linker,
      (c) we are inside the deep-night alert-hours window
          (when PERIMETER_BURST_NIGHT_ONLY is True).
  * Demote NEVER silences: severity floors at LOW.
  * Kill switch (PERIMETER_BURST_DEMOTE_ENABLED=False) → byte-identical
    to today's behavior.

Test-authority discipline: we reuse the module-level bootstrap in the
sibling ``test_perimeter_alert_nm_routing.py`` (same _perimeter binding,
same MockHass, same clock guard). Tests drive
``_async_handle_perimeter_trigger`` (the production entry point that
contains the burst-demote CALL site) and additionally drive the outer
``_on_perimeter_event`` for an end-to-end wiring pin.

Mutation drills covered:
  * ``test_MUTATION_burst_callee_load_bearing`` — patch
    ``_evaluate_burst_demotion`` to always return (False, {...}) and
    confirm the second-alert test would go RED (proves the CALLEE
    is load-bearing at the wire site — drill #2).
  * ``test_MUTATION_burst_call_removed_load_bearing`` — patch
    ``_record_burst_alert`` to a no-op so the count denominator never
    increments; confirms the Nth-alert history feed is load-bearing
    (drill #1 for the recording site).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

# Bootstrap the perimeter module via the sibling test's module-level
# plumbing (stubs homeassistant.*, loads perimeter_alert, pins the
# scheduler + clock). This gives us the same _perimeter binding the
# production tests use — no divergent import graph.
from test_perimeter_alert_nm_routing import (  # noqa: E402
    _const,
    _perimeter,
    _make_hass,
    _setup_mgr,
    _run,
    Severity,
    PerimeterAlertManager,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

FRONT = "binary_sensor.front_yard_person_occupancy"
CAM_KEY = "front_yard"


def _fresh_mgr(**hass_kw) -> tuple[PerimeterAlertManager, MagicMock]:
    hass, nm = _make_hass(house_state="away", **hass_kw)
    mgr = _run(_setup_mgr(hass))
    # Tag the current sensor's engine so sibling-corroboration semantics
    # match production (leg_fire records engine tags at rising-edge time).
    mgr._sensor_engine[FRONT] = "frigate"
    return mgr, nm


def _fire_and_clear_cooldown(mgr) -> None:
    """Fire one alert then drop cooldown + in-flight so the next call
    reaches the burst-demote block."""
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    mgr._last_alert.clear()
    mgr._dispatch_in_flight.clear()


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------

def test_xcorr1_first_alert_never_demoted():
    mgr, nm = _fresh_mgr()
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    assert nm.async_notify.await_count == 1
    kwargs = nm.async_notify.await_args.kwargs
    # Independently-authored expected value: house_state=="away" → CRITICAL
    # via the severity map. If burst-demote mis-fires on the first alert,
    # this would drop to LOW.
    assert kwargs["severity"] == Severity.CRITICAL, (
        "first alert must fire at full severity (sacred invariant)"
    )
    # Decision surface: first_alert reason, not demoted.
    decision = mgr._last_burst_decision.get(CAM_KEY)
    assert decision is not None
    assert decision["demoted"] is False
    assert decision["reason"] == "first_alert"
    assert decision["prior_alerts_in_window"] == 0


def test_xcorr1_second_alert_demoted_when_all_conditions_met():
    mgr, nm = _fresh_mgr()
    _fire_and_clear_cooldown(mgr)
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    assert nm.async_notify.await_count == 2
    # Second dispatch severity is LOW (demoted from CRITICAL, floored).
    second = nm.async_notify.await_args_list[1].kwargs
    assert second["severity"] == Severity.LOW, (
        "second isolated night-time alert must demote to LOW"
    )
    decision = mgr._last_burst_decision[CAM_KEY]
    assert decision["demoted"] is True
    assert decision["reason"] == "burst_isolated"
    assert decision["prior_alerts_in_window"] == 1
    assert decision["sibling_corroborated"] is False
    assert decision["adjacent_activity"] is False


def test_xcorr1_second_alert_not_demoted_when_sibling_corroborated():
    mgr, nm = _fresh_mgr()
    _fire_and_clear_cooldown(mgr)
    # Seed a sibling-engine fire on the SAME camera within the SOLE_FIRE
    # window — this must veto demotion.
    now = _perimeter.dt_util.now()
    mgr._recent_fires.setdefault(CAM_KEY, []).append(("protect", now))
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    assert nm.async_notify.await_count == 2
    second = nm.async_notify.await_args_list[1].kwargs
    assert second["severity"] == Severity.CRITICAL, (
        "sibling-engine corroboration on the same camera must veto demotion"
    )
    decision = mgr._last_burst_decision[CAM_KEY]
    assert decision["demoted"] is False
    assert decision["reason"] == "sibling_corroborated"
    assert decision["sibling_corroborated"] is True


def test_xcorr1_second_alert_not_demoted_when_adjacent_camera_active():
    mgr, nm = _fresh_mgr()
    # Install a stub linker that reports adjacent activity.
    linker = MagicMock()
    linker.has_recent_adjacent_activity = MagicMock(return_value=True)
    mgr.hass.data[_const.DOMAIN]["exterior_track_linker"] = linker
    _fire_and_clear_cooldown(mgr)
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    assert nm.async_notify.await_count == 2
    second = nm.async_notify.await_args_list[1].kwargs
    assert second["severity"] == Severity.CRITICAL, (
        "adjacent-camera activity must veto demotion"
    )
    decision = mgr._last_burst_decision[CAM_KEY]
    assert decision["demoted"] is False
    assert decision["reason"] == "adjacent_activity"
    assert decision["adjacent_activity"] is True
    # And the linker was actually consulted with the collapsed camera key.
    call = linker.has_recent_adjacent_activity.call_args
    assert call.args[0] == CAM_KEY


def test_xcorr1_night_only_gate_blocks_demotion_outside_hours(monkeypatch):
    # Alert-hours window START=0, END=0 = full day in _is_in_alert_hours,
    # so we must override to a narrow window AND pin the clock outside it.
    mgr, nm = _fresh_mgr()
    # Narrow the alert window to a 1-hour slot; then pin clock outside.
    for entry in mgr.hass.config_entries.async_entries():
        entry.options[_const.CONF_PERIMETER_VEHICLE_HOURS_START] = 1
        entry.options[_const.CONF_PERIMETER_VEHICLE_HOURS_END] = 2
    # Pin dt_util.now to hour 10 (outside 1-2 window).
    fixed = _perimeter.dt_util.now().replace(hour=10, minute=0, second=0)
    monkeypatch.setattr(_perimeter.dt_util, "now", lambda: fixed)
    # Outside alert-hours → the OUTER dispatch guard drops the first
    # trigger entirely; that same guard would drop the second trigger,
    # so to isolate the burst-demote night-only gate we bypass the
    # outer guard by populating history and calling the helper directly.
    # (The wiring test above is what pins the CALL from the entry point;
    # this test pins the night-only CONDITION on the CALLEE.)
    mgr._recent_alerts_by_camera[CAM_KEY] = [fixed - timedelta(seconds=60)]
    should_demote, decision = mgr._evaluate_burst_demotion(
        CAM_KEY, FRONT, fixed,
    )
    assert should_demote is False
    assert decision["reason"] == "outside_night_window"
    assert decision["in_alert_hours"] is False


def test_xcorr1_kill_switch_false_is_byte_identical(monkeypatch):
    # Kill switch False → decision must return (False, {"reason": "disabled"})
    # and severity flow through untouched even after N alerts.
    monkeypatch.setattr(_perimeter, "PERIMETER_BURST_DEMOTE_ENABLED", False)
    mgr, nm = _fresh_mgr()
    _fire_and_clear_cooldown(mgr)
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    assert nm.async_notify.await_count == 2
    for call in nm.async_notify.await_args_list:
        assert call.kwargs["severity"] == Severity.CRITICAL
    decision = mgr._last_burst_decision[CAM_KEY]
    assert decision["demoted"] is False
    assert decision["reason"] == "disabled"


# ---------------------------------------------------------------------------
# Wiring test — drive the OUTER entry point (_on_perimeter_event → task)
# ---------------------------------------------------------------------------

def _make_state_change_event(entity_id: str, new_val: str, old_val) -> MagicMock:
    ev = MagicMock()
    new_state = MagicMock()
    new_state.state = new_val
    new_state.attributes = {}
    if old_val is None:
        old_state = None
    else:
        old_state = MagicMock()
        old_state.state = old_val
        old_state.attributes = {}
    ev.data = {
        "entity_id": entity_id,
        "new_state": new_state,
        "old_state": old_state,
    }
    return ev


def test_xcorr1_wiring_via_on_perimeter_event_end_to_end():
    """End-to-end pin: drive the OUTER entry point and confirm demotion
    surfaces at the NM boundary.

    Guards against the failure mode where the CALL to
    ``_evaluate_burst_demotion`` is removed from
    ``_async_handle_perimeter_trigger`` — a helper-only test would stay
    green. Here we push through ``_on_perimeter_event`` which schedules
    the async task; we then await the pending task to reach the notify.
    """
    mgr, nm = _fresh_mgr()
    # Bypass the boot-settle gate so rising edges fire immediately.
    mgr._setup_time = None
    # Real async_create_task on the current loop so the scheduled coroutine
    # actually runs (MockHass's async_create_task is a MagicMock by default).
    async def _drive() -> None:
        collected: list = []

        def _create_task(coro):
            t = asyncio.ensure_future(coro)
            collected.append(t)
            return t

        mgr.hass.async_create_task = _create_task

        # First rising edge → dispatches at CRITICAL (first-is-sacred).
        mgr._on_perimeter_event(
            _make_state_change_event(FRONT, "on", "off")
        )
        await asyncio.gather(*collected)
        collected.clear()

        # Clear cooldown so the second rising edge reaches the burst block.
        mgr._last_alert.clear()
        mgr._dispatch_in_flight.clear()

        mgr._on_perimeter_event(
            _make_state_change_event(FRONT, "on", "off")
        )
        await asyncio.gather(*collected)

    asyncio.run(_drive())
    assert nm.async_notify.await_count == 2
    # Independently-authored expected values: 1st CRITICAL, 2nd LOW.
    assert nm.async_notify.await_args_list[0].kwargs["severity"] == Severity.CRITICAL
    assert nm.async_notify.await_args_list[1].kwargs["severity"] == Severity.LOW


# ---------------------------------------------------------------------------
# Mutation drills (Bug Class #62 — test-authority anchor)
# ---------------------------------------------------------------------------

def test_MUTATION_burst_callee_load_bearing():
    """Neuter the callee: force _evaluate_burst_demotion → (False, {...}).

    Under this mutation, ``test_xcorr1_second_alert_demoted_when_all_
    conditions_met`` would go RED because the second severity would stay
    CRITICAL. This test proves the CALLEE is load-bearing at the wire
    site.
    """
    orig = PerimeterAlertManager._evaluate_burst_demotion
    try:
        PerimeterAlertManager._evaluate_burst_demotion = (
            lambda self, ck, eid, now: (False, {"reason": "neutered"})
        )
        mgr, nm = _fresh_mgr()
        _fire_and_clear_cooldown(mgr)
        _run(mgr._async_handle_perimeter_trigger(FRONT))
        # With demotion neutered, second severity stays CRITICAL.
        second = nm.async_notify.await_args_list[1].kwargs
        assert second["severity"] == Severity.CRITICAL, (
            "with burst-demote neutered, second severity must NOT drop"
        )
    finally:
        PerimeterAlertManager._evaluate_burst_demotion = orig
    # Restore proof: real callee resumes demotion.
    mgr, nm = _fresh_mgr()
    _fire_and_clear_cooldown(mgr)
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    assert nm.async_notify.await_args_list[1].kwargs["severity"] == Severity.LOW


def test_MUTATION_burst_call_removed_load_bearing():
    """Neuter the recording site: force _record_burst_alert → no-op.

    Under this mutation, no prior-alert timestamps ever land in
    ``_recent_alerts_by_camera``, so the burst-count denominator stays 0
    and the second alert is treated as a first alert (NOT demoted).
    This test proves the recording CALL inside _do_dispatch is
    load-bearing.
    """
    orig = PerimeterAlertManager._record_burst_alert
    try:
        PerimeterAlertManager._record_burst_alert = (
            lambda self, ck, now: None
        )
        mgr, nm = _fresh_mgr()
        _fire_and_clear_cooldown(mgr)
        _run(mgr._async_handle_perimeter_trigger(FRONT))
        # Without recording, second alert stays CRITICAL because
        # prior_alerts_in_window == 0 → reason == "first_alert".
        second = nm.async_notify.await_args_list[1].kwargs
        assert second["severity"] == Severity.CRITICAL
        decision = mgr._last_burst_decision[CAM_KEY]
        assert decision["reason"] == "first_alert"
    finally:
        PerimeterAlertManager._record_burst_alert = orig


# ---------------------------------------------------------------------------
# Observability surface
# ---------------------------------------------------------------------------

def test_xcorr1_burst_demotion_stats_surface():
    mgr, nm = _fresh_mgr()
    _fire_and_clear_cooldown(mgr)
    _run(mgr._async_handle_perimeter_trigger(FRONT))
    stats = mgr.burst_demotion_stats()
    assert CAM_KEY in stats
    entry = stats[CAM_KEY]
    assert entry["alerts_in_window"] == 2
    assert entry["window_s"] == _perimeter.PERIMETER_BURST_WINDOW_S
    last = entry["last_decision"]
    assert last["demoted"] is True
    assert last["reason"] == "burst_isolated"
    assert last["severity_before"] == "CRITICAL"
    assert last["severity_after"] == "LOW"


# ---------------------------------------------------------------------------
# Linker adjacency helper — direct unit coverage
# ---------------------------------------------------------------------------

def test_linker_has_recent_adjacent_activity_returns_true_when_neighbor_open():
    # Load the linker module against the same stubs the perimeter test
    # bootstrap installed. Use module loader directly (avoid re-import
    # cost by reusing sys.modules if present).
    import os, sys, importlib.util
    ura_path = os.path.dirname(_perimeter.__file__)
    name = "custom_components.universal_room_automation.exterior_track_linker"
    if name in sys.modules:
        linker_mod = sys.modules[name]
    else:
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(ura_path, "exterior_track_linker.py"),
        )
        linker_mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = linker_mod
        spec.loader.exec_module(linker_mod)
    ExteriorTrackLinker = linker_mod.ExteriorTrackLinker
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    linker = ExteriorTrackLinker(hass)
    # Declare adjacency A <-> B (auto-symmetrized in ctor is a for-loop
    # over the module dict; here we override at runtime).
    linker.set_adjacency({"cam_a": ["cam_b"]})
    # Observe an event on cam_b → opens a track with last hop on cam_b.
    now = _perimeter.dt_util.now()
    linker.observe(camera="cam_b", label="person",
                   event_id=None, score=0.0, sub_label=None, now=now)
    # Neighbor of cam_a is cam_b → active within window → True.
    assert linker.has_recent_adjacent_activity("cam_a", 300.0, now) is True
    # A camera with no neighbors → False.
    assert linker.has_recent_adjacent_activity("cam_lonely", 300.0, now) is False
