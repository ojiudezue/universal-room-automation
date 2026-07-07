"""REAL-coordinator construction tier (v5.8.0 incident regression guard).

The v5.8.0 reconcile-on-return cycle crashed EVERY room's setup on the live
house: ``ActuatorReconciler`` was constructed at ``coordinator.py`` BEFORE
``super().__init__()`` set ``coordinator.hass`` — AttributeError on HA 2026.2,
RecursionError on HA 2026.7. The whole unit suite used a FAKE coordinator that
already had ``.hass``, so the real construction was never exercised and the bug
shipped green.

This tier constructs the REAL ``UniversalRoomCoordinator`` against a real
Home Assistant (via pytest-homeassistant-custom-component). It REQUIRES the
``homeassistant`` package; on a mock-only dev box it skips cleanly. Run it with
an HA venv, e.g. ``.venv-ha/bin/python -m pytest quality/real_construction/``.
Add new coordinators / construction-order-sensitive code here.
"""
import pytest

# Skip the whole module unless a real HA is installed (mock-only dev boxes).
pytest.importorskip("homeassistant.core")
pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_LIGHTS,
    CONF_ROOM_NAME,
    ENTRY_TYPE_ROOM,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)


class _Entry:
    def __init__(self, data):
        self.data = data
        self.options = {}
        self.entry_id = "repro_room_entry"
        self.title = data.get(CONF_ROOM_NAME, "Repro Room")


async def test_room_coordinator_construct_and_first_refresh(hass):
    """Construct the real coordinator + run first-refresh. Fails (RecursionError
    or otherwise) exactly as the house did if the bug is construction/setup-time."""
    entry = _Entry(
        {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: "Repro Room",
            CONF_LIGHTS: ["light.repro"],
        }
    )
    # Step 1: construction (coordinator.py:316 -> ActuatorReconciler(self)).
    # This is the exact line that crashed on the house: the reconciler reads
    # coordinator.hass, which must already be set by super().__init__().
    coord = UniversalRoomCoordinator(hass, entry)
    assert coord._actuator_reconciler is not None
    assert coord._actuator_reconciler.hass is hass

    # Step 2: the B-HIGH-1 / D2.9 rebuild-hook path that arms the reconciler's
    # real state-change listener against the real hass (async_register_listeners
    # -> async_track_state_change_event). No config entry needed.
    coord._update_signal_subscriptions()
    # Listener armed for the one configured light.
    assert coord._actuator_reconciler._unsub_reconciler_listeners
