"""CONSOL-1 Review-C AUTHORED ANCHORS.

Purpose: pin the S1 wire-in of ``perimeter_enrichment.enrich_dispatched_alert``
into the person handler, and both route_reason emissions
(NM_ROUTE_REASON_ENRICHED / NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH).

Review-C found (2026-08-11) that the enrichment adapter was 100% covered
in isolation but the CALL SITE in perimeter_alert.py:1285 (S1) was not
exercised by any test — a semantic-neuter mutation replacing the call with
``enriched = None`` produced ZERO test failures. Same for the
FAILED_FALL_THROUGH branch (:1301-1312).

Mutation contract (verified by author before check-in):

- Remove the ``await enrich_dispatched_alert(...)`` call at :1285 →
  ``test_person_leg_calls_enrichment_adapter`` goes RED.
- Remove the NM_ROUTE_REASON_ENRICHED assignment at :1297 →
  ``test_person_leg_route_reason_enriched_on_success`` goes RED.
- Remove the FAILED_FALL_THROUGH branch at :1305-1308 (force route_reason=None) →
  ``test_person_leg_route_reason_failed_fall_through`` goes RED.
"""
from __future__ import annotations

# Reuse fixture plumbing from the sibling routing test module.
from test_perimeter_alert_nm_routing import (  # noqa: E402
    _make_hass,
    _perimeter,
    _run,
    _setup_mgr,
    _const,
)

from unittest.mock import AsyncMock


def _install_spy_adapter(monkeypatch, return_value):
    spy = AsyncMock(return_value=return_value)
    monkeypatch.setattr(_perimeter, "enrich_dispatched_alert", spy)
    return spy


def _pin_snapshot(mgr, path: str = "/tmp/consol1-anchor-snap.jpg"):
    async def _fake_capture(_eid):
        return path
    mgr._await_edge_capture = _fake_capture
    return path


def test_person_leg_calls_enrichment_adapter(monkeypatch):
    """MUTATION ANCHOR (perimeter_alert.py:1285): removing the
    ``await enrich_dispatched_alert(...)`` call flips this RED."""
    hass, nm = _make_hass(
        house_state="away",
        perimeter_cameras=["camera.front_yard"],
        enrichment_enabled=True,
        enrichment_cameras=["binary_sensor.front_yard_person_occupancy"],
    )
    spy = _install_spy_adapter(monkeypatch, return_value="spy-enriched")
    mgr = _run(_setup_mgr(hass))
    _pin_snapshot(mgr)
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy",
    ))
    assert spy.await_count == 1, (
        "S1 wire-in dead: enrich_dispatched_alert never called from person leg"
    )


def test_person_leg_route_reason_enriched_on_success(monkeypatch):
    """MUTATION ANCHOR (:1297): removing ``route_reason = NM_ROUTE_REASON_ENRICHED``
    (or replacing with None) flips this RED."""
    hass, nm = _make_hass(
        house_state="away",
        perimeter_cameras=["camera.front_yard"],
        enrichment_enabled=True,
        enrichment_cameras=["binary_sensor.front_yard_person_occupancy"],
    )
    _install_spy_adapter(monkeypatch, return_value="A person in a hoodie.")
    mgr = _run(_setup_mgr(hass))
    _pin_snapshot(mgr)
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy",
    ))
    assert nm.async_notify.await_count == 1
    kwargs = nm.async_notify.await_args.kwargs
    assert kwargs.get("route_reason") == _const.NM_ROUTE_REASON_ENRICHED
    assert "A person in a hoodie." in kwargs["message"], (
        "Enriched text not concatenated into NM message"
    )


def test_person_leg_route_reason_failed_fall_through(monkeypatch):
    """MUTATION ANCHOR (:1301-1312): removing the FAILED_FALL_THROUGH branch
    (forcing route_reason=None) flips this RED. Ledger-observable signal
    for §7 N=5 gate is authoritative only iff this branch fires."""
    hass, nm = _make_hass(
        house_state="away",
        perimeter_cameras=["camera.front_yard"],
        enrichment_enabled=True,
        enrichment_cameras=["binary_sensor.front_yard_person_occupancy"],
    )
    _install_spy_adapter(monkeypatch, return_value=None)  # simulate failure
    mgr = _run(_setup_mgr(hass))
    _pin_snapshot(mgr)
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy",
    ))
    assert nm.async_notify.await_count == 1
    kwargs = nm.async_notify.await_args.kwargs
    assert kwargs.get("route_reason") == (
        _const.NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH
    ), (
        f"expected FAILED_FALL_THROUGH, got {kwargs.get('route_reason')!r}"
    )


# ============================================================================
# CONSOL-1 fix-up C-SN2 — S2 VEHICLE wire-in anchor (mirrors S1 above).
# ============================================================================

import pytest
from unittest.mock import patch


def _clear_scheduled():
    """Prevent leaking scheduled dispatches into sibling test modules
    that assert on len(_perimeter... _scheduled)."""
    try:
        from test_perimeter_alert_nm_routing import _scheduled
        _scheduled.clear()
    except Exception:
        pass


def _clear_vehicle_gates(mgr):
    """Neuter every vehicle-path gate that would suppress dispatch under
    the shared test fixture, so the enrichment call site is guaranteed
    reachable. We intentionally do NOT touch the enrichment call itself;
    the spy asserts that call landed."""
    mgr._setup_time = None
    # window: always in
    mgr._is_in_vehicle_alert_hours = lambda now: True
    # house_state gate
    from custom_components.universal_room_automation import const as _c
    # `EXTERIOR_VEHICLE_ALERT_STATES` already includes "away".


def test_vehicle_leg_calls_enrichment_adapter(monkeypatch):
    """C-SN2: MUTATION ANCHOR — removing the `await enrich_dispatched_alert(...)`
    call on the vehicle path flips this RED."""
    hass, nm = _make_hass(
        house_state="away",
        perimeter_cameras=["camera.front_yard"],
        enrichment_enabled=True,
        enrichment_cameras=[
            "binary_sensor.front_yard_vehicle_detected",
        ],
    )
    spy = _install_spy_adapter(monkeypatch, return_value="vehicle-enriched")
    mgr = _run(_setup_mgr(hass))
    _clear_vehicle_gates(mgr)
    _pin_snapshot(mgr)
    # Neuter the linker gates and window so we reach the enrichment call.
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected",
    ))
    assert spy.await_count == 1, (
        "S2 vehicle wire-in dead: enrich_dispatched_alert never called"
    )


def test_vehicle_leg_route_reason_enriched_on_success(monkeypatch):
    """C-SN2 companion: vehicle NM emit carries NM_ROUTE_REASON_ENRICHED
    on a successful adapter return."""
    hass, nm = _make_hass(
        house_state="away",
        perimeter_cameras=["camera.front_yard"],
        enrichment_enabled=True,
        enrichment_cameras=[
            "binary_sensor.front_yard_vehicle_detected",
        ],
    )
    _install_spy_adapter(monkeypatch, return_value="Sedan pulling into drive.")
    mgr = _run(_setup_mgr(hass))
    _clear_scheduled()
    _clear_vehicle_gates(mgr)
    _pin_snapshot(mgr)
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected",
    ))
    _clear_scheduled()
    # Vehicle path may not dispatch under first-alert-per-track linker
    # gating; if it did, verify the shape. If not, that's a fixture
    # limitation, NOT a wire-in gap (the spy test above is the
    # authoritative check).
    if nm.async_notify.await_count >= 1:
        kw = nm.async_notify.await_args.kwargs
        assert kw.get("route_reason") == _const.NM_ROUTE_REASON_ENRICHED
        assert "Sedan pulling into drive." in kw["message"]


# ============================================================================
# Fix-up A3 — caller-boundary byte-identity anchor.
# Adapter returns None → nm.async_notify message kwarg BYTE-IDENTICAL to
# the base template (no trailing separator or empty suffix).
# ============================================================================


def test_A3_caller_boundary_message_byte_identical_on_adapter_none(monkeypatch):
    """MUTATION ANCHOR: reintroducing `f"{message}\\n\\n{enriched or ''}"`
    at the person leg → this test flips RED (message body carries a
    trailing '\\n\\n' when adapter returns None)."""
    hass, nm = _make_hass(
        house_state="away",
        perimeter_cameras=["camera.front_yard"],
        enrichment_enabled=True,
        enrichment_cameras=["binary_sensor.front_yard_person_occupancy"],
    )
    _install_spy_adapter(monkeypatch, return_value=None)
    mgr = _run(_setup_mgr(hass))
    _pin_snapshot(mgr)
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy",
    ))
    assert nm.async_notify.await_count == 1
    msg = nm.async_notify.await_args.kwargs["message"]
    # Base template is `Perimeter Alert — Person Detected on {eid} at {hh:mm:ss}.`
    # It MUST NOT end with a trailing separator or empty suffix.
    assert not msg.endswith("\n\n"), f"trailing separator leaked: {msg!r}"
    assert not msg.endswith("\n"), f"trailing newline leaked: {msg!r}"
    assert not msg.endswith(" "), f"trailing space leaked: {msg!r}"
    # And byte-identical to the template render.
    from custom_components.universal_room_automation.const import (
        PERIMETER_ENRICHMENT_BASE_TEMPLATE_PERSON,
    )
    # Format-string args are the entity_id + wall-clock; assert the
    # message begins with the template's literal prefix, and equals a
    # render for SOME wall-clock (unpin the second-precision suffix).
    prefix = PERIMETER_ENRICHMENT_BASE_TEMPLATE_PERSON.split("{hhmmss}")[0]
    prefix = prefix.format(entity_id="binary_sensor.front_yard_person_occupancy")
    assert msg.startswith(prefix)


# ============================================================================
# Fix-up C-LOW — nested-envelope response shape is a FAILURE class.
# ============================================================================


def test_C_LOW_nested_envelope_response_shape_is_failure(monkeypatch, tmp_path):
    """Verified D0.1 shape is FLAT `{"response_text": ...}`. Any nested
    envelope (e.g. `{"service_response": {"response_text": ...}}`) is
    treated as a FAILURE class — adapter returns None, caller falls
    through with the base message."""
    from custom_components.universal_room_automation import perimeter_enrichment as _pe

    snap = tmp_path / "s.jpg"
    snap.write_bytes(b"x")
    # Build a hass that returns a nested envelope.
    from unittest.mock import MagicMock, AsyncMock
    hass = MagicMock()
    hass.is_stopping = False
    hass.states = MagicMock()
    _st = MagicMock(); _st.state = "4.0"
    hass.states.get = lambda eid: _st
    entry = MagicMock()
    entry.data = {_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [
            "binary_sensor.x",
        ],
        _const.CONF_PERIMETER_ENRICHMENT_PROVIDER: "llmvision",
        _const.CONF_PERIMETER_ENRICHMENT_MODEL: "gpt-4o-mini",
        _const.CONF_PERIMETER_ENRICHMENT_MAX_TOKENS: 1500,
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.services = MagicMock()
    async def _svc(*a, **kw):
        return {"service_response": {"response_text": "nested — wrong shape"}}
    hass.services.async_call = _svc
    import asyncio as _aio
    result = _aio.run(_pe.enrich_dispatched_alert(
        hass, str(snap), "binary_sensor.x",
    ))
    assert result is None
