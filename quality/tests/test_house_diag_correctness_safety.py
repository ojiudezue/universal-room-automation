"""HOUSE-DIAG-CORRECTNESS (audit 2026-10-25 H7): safety diagnostics
``sensors_available`` must count configured sensors with a real live state,
not echo ``sensors_monitored``. Drives the real SafetyCoordinator.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import test_safety_coordinator  # noqa: F401  (installs HA stubs)
from test_safety_coordinator import make_hass

from custom_components.universal_room_automation.domain_coordinators.safety import (
    SafetyCoordinator,
)


def _coord():
    hass = make_hass()
    live = {
        "binary_sensor.smoke_ok": "off",
        "binary_sensor.smoke_dead": "unavailable",
        "binary_sensor.leak_unknown": "unknown",
        "sensor.temp_ok": "21.5",
        # sensor.leak_missing: configured id with no state object at all
    }
    hass.states.get = lambda eid: (
        MagicMock(state=live[eid]) if eid in live else None
    )
    coord = SafetyCoordinator(hass)
    for eid in ("binary_sensor.smoke_ok", "binary_sensor.smoke_dead",
                "binary_sensor.leak_unknown"):
        coord._binary_sensors[eid] = MagicMock()
    for eid in ("sensor.temp_ok", "sensor.leak_missing"):
        coord._numeric_sensors[eid] = MagicMock()
    return coord


def test_count_available_reads_live_state():
    coord = _coord()
    assert coord.sensors_monitored == 5
    assert coord.count_available_sensors() == 2  # smoke_ok + temp_ok


def test_diagnostics_status_degraded_when_any_dead():
    assert _coord().get_diagnostics_status() == "degraded"


def test_all_live_is_healthy():
    coord = _coord()
    coord.hass.states.get = lambda eid: MagicMock(state="off")
    assert coord.count_available_sensors() == 5
    assert coord.get_diagnostics_status() == "healthy"
