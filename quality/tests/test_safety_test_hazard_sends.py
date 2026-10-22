"""SAFETY-TEST-HAZARD-SENDS-NOTHING-1.

handle_test_hazard must route a TEST page through the same dispatch a real
hazard uses (CoordinatorManager._execute_action -> NotificationManager
.async_notify) with NO response actions and no _active_hazards entry.
"""

import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

# test_safety_coordinator installs the HA module stubs this file relies on.
from test_safety_coordinator import make_hass  # noqa: F401

from custom_components.universal_room_automation.const import DOMAIN
from custom_components.universal_room_automation.domain_coordinators.safety import (
    SafetyCoordinator,
    HazardType,
    Hazard,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Severity,
)
from custom_components.universal_room_automation.domain_coordinators.manager import (
    CoordinatorManager,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)


class _CapturingNM:
    """Fake NM whose async_notify binds to the REAL signature."""

    def __init__(self):
        self.calls = []
        self._sig = inspect.signature(NotificationManager.async_notify)

    async def async_notify(self, *args, **kwargs):
        bound = self._sig.bind(self, *args, **kwargs)
        bound.apply_defaults()
        args_d = dict(bound.arguments)
        args_d.pop("self")
        self.calls.append(args_d)


def _setup():
    hass = make_hass()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    manager = CoordinatorManager(hass)
    nm = _CapturingNM()
    manager._notification_manager = nm
    hass.data[DOMAIN] = {"coordinator_manager": manager}
    coord = SafetyCoordinator(hass)
    return hass, coord, nm


@pytest.mark.asyncio
async def test_test_hazard_critical_reaches_nm_with_real_shape():
    hass, coord, nm = _setup()
    await coord.handle_test_hazard("smoke", "Kitchen", "critical")
    assert len(nm.calls) == 1
    c = nm.calls[0]
    assert c["coordinator_id"] == "safety"
    assert c["severity"] is Severity.CRITICAL
    assert c["hazard_type"] == "smoke"
    assert c["location"] == "Kitchen"
    assert c["title"].startswith("TEST")
    assert "TEST" in c["message"]


@pytest.mark.asyncio
async def test_test_hazard_severity_honoured_each_level():
    for sev_str, sev in (("high", Severity.HIGH), ("medium", Severity.MEDIUM),
                         ("low", Severity.LOW)):
        hass, coord, nm = _setup()
        await coord.handle_test_hazard("water_leak", "Basement", sev_str)
        assert len(nm.calls) == 1
        assert nm.calls[0]["severity"] is sev


@pytest.mark.asyncio
async def test_test_hazard_takes_no_response_actions_or_state():
    hass, coord, nm = _setup()
    sent = []
    import custom_components.universal_room_automation.domain_coordinators.safety as safety_mod  # noqa: E501
    for name in ("_critical_response", "_high_response",
                 "_medium_response", "_low_response"):
        setattr(coord, name, lambda h, _n=name: sent.append(_n) or [])
    await coord.handle_test_hazard("smoke", "Kitchen", "critical")
    assert sent == []
    hass.services.async_call.assert_not_awaited()  # no valve/lights/HVAC
    assert len(coord.active_hazards) == 0
    assert coord._alerts_sent_24h == 0
    assert coord._hazards_detected_24h == 0
    assert len(nm.calls) == 1
    del safety_mod


@pytest.mark.asyncio
async def test_test_hazard_does_not_suppress_real_page():
    """A test page must not stamp the real deduplicator's key."""
    hass, coord, nm = _setup()
    await coord.handle_test_hazard("smoke", "Kitchen", "critical")
    real = Hazard(
        type=HazardType.SMOKE, severity=Severity.CRITICAL, confidence=1.0,
        location="Kitchen", sensor_id="binary_sensor.smoke", value="on",
        threshold="on", detected_at=None, message="smoke",
    )
    assert coord._deduplicator.should_alert(real) is True


@pytest.mark.asyncio
async def test_test_hazard_no_manager_does_not_raise():
    hass = make_hass()
    coord = SafetyCoordinator(hass)
    await coord.handle_test_hazard("smoke", "Kitchen", "critical")
