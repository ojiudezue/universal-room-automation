"""PERIMETER-ALERT-NAME-PERSON-1 (Wave-1 consumer #2, 2026-09-06).

Pins the identity-annotation contract on the perimeter person alert.

INVARIANT (falsifiable): the recognized identity ONLY mutates the alert
message TEXT — severity is byte-identical to the un-named path. Neuter
target for RED-on-mutation: perimeter_alert.py wire-in block
"PERIMETER-ALERT-NAME-PERSON-1" (removing the block leaves message
unchanged for the named-face case).

Test cases:
  T1  named face conf=None      -> annotated + severity unchanged
  T2  named face conf>=0.75     -> annotated + severity unchanged
  T3  named face conf<0.75      -> NOT annotated
  T4  no legs (empty)           -> NOT annotated
  T5  census absent             -> NOT annotated, severity unchanged
  T6  resolver raises           -> NOT annotated, no exception raised
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

# Reuse the sibling module's HA-stub / package-plumbing / manager loader —
# importing it wires up all the fake `homeassistant.*` modules and the
# perimeter_alert import chain exactly once.
from test_perimeter_alert_nm_routing import (  # noqa: E402
    Severity,
    _make_hass,
    _perimeter,
    _run,
    _setup_mgr,
)


# ---- helpers ----------------------------------------------------------------


class _FakeLeg:
    """Duck-types camera_census.FaceLeg (only fields the consumer reads)."""

    def __init__(self, canonical_slug, confidence, last_changed=None):
        self.canonical_slug = canonical_slug
        self.confidence = confidence
        self.last_changed = last_changed


def _install_census(hass, legs=None, raise_exc: Exception | None = None):
    census = MagicMock()
    if raise_exc is not None:
        def _boom(_stem):
            raise raise_exc
        census._resolve_face_legs = _boom
    else:
        census._resolve_face_legs = lambda _stem: list(legs or [])
    hass.data[_perimeter.DOMAIN]["census"] = census
    return census


def _last_call_kwargs(nm):
    assert nm.async_notify.await_count == 1
    return nm.async_notify.await_args.kwargs


def _severity_baseline(house_state="away"):
    """Byte-identical severity for the un-annotated (no-census) path."""
    hass, nm = _make_hass(house_state=house_state)
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    return _last_call_kwargs(nm)["severity"]


# ---- tests ------------------------------------------------------------------


def test_named_face_no_confidence_annotates_and_severity_unchanged():
    """T1: Frigate-style leg (conf=None, already floored at 0.60 in the
    resolver) → message gets the name; severity byte-identical."""
    baseline = _severity_baseline("away")

    hass, nm = _make_hass(house_state="away")
    _install_census(hass, legs=[_FakeLeg("oji_udezue", None)])
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    # ANCHOR: name in message body
    assert "Oji Udezue" in kw["message"], kw["message"]
    assert "Identified:" in kw["message"]
    # ANCHOR (safety invariant): severity byte-identical to un-annotated path
    assert kw["severity"] == baseline


def test_named_face_high_confidence_annotates_and_severity_unchanged():
    """T2: Protect-style leg carrying explicit conf>=0.75 → annotated;
    severity unchanged."""
    baseline = _severity_baseline("away")

    hass, nm = _make_hass(house_state="away")
    _install_census(hass, legs=[_FakeLeg("jaya", 0.92)])
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Jaya" in kw["message"]
    assert kw["severity"] == baseline


def test_low_confidence_named_face_not_annotated():
    """T3: conf below the 0.75 card threshold → no annotation. Severity
    still identical to baseline."""
    baseline = _severity_baseline("away")

    hass, nm = _make_hass(house_state="away")
    _install_census(hass, legs=[_FakeLeg("someone", 0.55)])
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Identified:" not in kw["message"]
    assert kw["severity"] == baseline


def test_no_face_legs_not_annotated():
    """T4: face-suppressed / drill / outage — resolver returns [] →
    anonymous 'Person Detected' preserved."""
    baseline = _severity_baseline("away")

    hass, nm = _make_hass(house_state="away")
    _install_census(hass, legs=[])
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Identified:" not in kw["message"]
    assert "Person Detected" in kw["message"] or "Person track" in kw["message"]
    assert kw["severity"] == baseline


def test_no_census_wired_no_annotation_and_no_error():
    """T5: census entirely absent from hass.data → best-effort fall-through,
    no annotation, no raise, severity intact."""
    baseline = _severity_baseline("away")

    hass, nm = _make_hass(house_state="away")
    # (deliberately do NOT call _install_census)
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Identified:" not in kw["message"]
    assert kw["severity"] == baseline


def test_resolver_exception_swallowed_message_intact():
    """T6: _resolve_face_legs raises → try/except swallows, message stays
    the pre-annotation form, severity intact. Guards the 'never escalate'
    fail-safe path."""
    baseline = _severity_baseline("away")

    hass, nm = _make_hass(house_state="away")
    _install_census(hass, raise_exc=RuntimeError("simulated resolver blowup"))
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Identified:" not in kw["message"]
    assert kw["severity"] == baseline


def test_stale_face_leg_not_annotated():
    """T7 (MEDIUM-1 fix): a named leg whose last_changed is older than the
    latch TTL must NOT annotate — a latched name from hours ago cannot label
    a fresh perimeter alert. RED-on-neuter: removing the freshness gate lets
    the stale name through and 'Identified:' reappears."""
    from datetime import datetime, timedelta, timezone
    from custom_components.universal_room_automation.const import (
        FACE_NAME_LATCH_TTL_S,
    )

    baseline = _severity_baseline("away")
    stale_ts = datetime.now(timezone.utc) - timedelta(
        seconds=FACE_NAME_LATCH_TTL_S + 120
    )
    hass, nm = _make_hass(house_state="away")
    _install_census(
        hass, legs=[_FakeLeg("oji_udezue", None, last_changed=stale_ts)]
    )
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Identified:" not in kw["message"], kw["message"]
    assert kw["severity"] == baseline


def test_fresh_face_leg_still_annotates():
    """T8: control for T7 — a leg with a FRESH last_changed still annotates,
    proving the gate drops only stale legs, not all timestamped legs."""
    from datetime import datetime, timezone

    baseline = _severity_baseline("away")
    fresh_ts = datetime.now(timezone.utc)
    hass, nm = _make_hass(house_state="away")
    _install_census(
        hass, legs=[_FakeLeg("jaya", None, last_changed=fresh_ts)]
    )
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    kw = _last_call_kwargs(nm)
    assert "Jaya" in kw["message"], kw["message"]
    assert "Identified:" in kw["message"]
    assert kw["severity"] == baseline
