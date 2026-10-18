"""SECURITY-REFIRE-INTRUSION-KEY-1.

Security emits hazard_type="intruder" (unknown-person + ALERT_HIGH entry) but
SecurityCoordinator.is_hazard_active only accepted "intrusion"/"entry_alert"/
"unknown_person", so the NM post-cooldown re-fire (_re_evaluate_hazard) never
re-paged an acknowledged intruder alert while the intrusion continued.

Drives the REAL NotificationManager._re_evaluate_hazard against a REAL
SecurityCoordinator.is_hazard_active (bare instance; the method reads only
``_active_alert``).
"""
from __future__ import annotations

# Same stub universe as test_safety_nm_refire (order matters).
import test_notification_manager as _tnm  # noqa: F401
import test_safety_coordinator  # noqa: F401

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.universal_room_automation.domain_coordinators import (
    security as security_mod,
)

nm_mod = _tnm._nm_mod
AlertState = nm_mod.AlertState


def _security(active: bool):
    c = security_mod.SecurityCoordinator.__new__(security_mod.SecurityCoordinator)
    c._active_alert = active
    return c


def _nm(monkeypatch, security):
    hass = _tnm._make_hass()
    hass.data[_tnm.DOMAIN]["database"] = AsyncMock()
    hass.data[_tnm.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"security": security}
    )
    nm = nm_mod.NotificationManager(hass, _tnm._make_config())
    monkeypatch.setattr(nm_mod, "async_dispatcher_send", lambda *a, **k: None)
    calls: list[dict] = []

    async def _notify(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(nm, "async_notify", _notify)
    return nm, calls


def _arm(nm, hazard_type, location="property"):
    nm._alert_state = AlertState.RE_EVALUATE
    nm._active_alert_data = {
        "coordinator_id": "security",
        "hazard_type": hazard_type,
        "location": location,
        "title": "Security alert",
        "message": "Unknown person detected — all doors locked",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["property", "lock.front_door"])
async def test_nm_refires_intruder_while_security_alert_active(monkeypatch, location):
    nm, calls = _nm(monkeypatch, _security(True))
    _arm(nm, "intruder", location)
    await nm._re_evaluate_hazard()
    assert len(calls) == 1, calls
    assert calls[0]["hazard_type"] == "intruder"
    assert calls[0]["location"] == location
    assert calls[0]["severity"].name == "CRITICAL"


@pytest.mark.asyncio
async def test_nm_no_refire_intruder_when_security_alert_cleared(monkeypatch):
    nm, calls = _nm(monkeypatch, _security(False))
    _arm(nm, "intruder")
    await nm._re_evaluate_hazard()
    assert calls == []
    assert nm._alert_state == AlertState.IDLE
    assert nm._active_alert_data is None


def test_security_is_hazard_active_accepted_types():
    on, off = _security(True), _security(False)
    for t in ("intruder", "intrusion", "entry_alert", "unknown_person"):
        assert on.is_hazard_active(t, "property") is True, t
        assert off.is_hazard_active(t, "property") is False, t
    # MEDIUM / informational types must not escalate to a CRITICAL re-fire.
    for t in ("investigate", "security_state_change", "smoke", ""):
        assert on.is_hazard_active(t, "property") is False, t
