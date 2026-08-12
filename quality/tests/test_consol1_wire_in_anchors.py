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
