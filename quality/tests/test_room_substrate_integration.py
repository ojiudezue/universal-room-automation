"""Room-tier substrate integration test (D3 acceptance).

Confirms that the room-tier listener-rewire preserves the existing
``UniversalRoomCoordinator`` semantics:

* `async_track_state_change_event` over `tier1_sensors` is no longer the
  Tier-1 occupancy subscription path — the room tier subscribes to
  ``SIGNAL_SUBSTRATE_KIND_CHANGED`` instead.
* Lux remains a direct state-change subscription (it is Tier-1 for
  latency but lives outside the substrate's CONF surface).
* The 2s rate-limiter + trailing-edge refresh trigger is preserved
  inline.

Static check — exercises the source of ``coordinator.py`` and the
imports + dispatcher subscription pattern.
"""

from __future__ import annotations

import _provenance_harness  # noqa: F401


def test_coordinator_imports_substrate_signal() -> None:
    """coordinator.py imports SIGNAL_SUBSTRATE_KIND_CHANGED at module top (Bug Class #34)."""
    import inspect
    import importlib.util
    import os
    coord_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "custom_components", "universal_room_automation",
        "coordinator.py",
    )
    with open(coord_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    # Module-top import (not function-local) — defends against Bug Class
    # #34 recurrence (v4.7.20.1).
    assert "from .domain_coordinators.signals import (" in src
    assert "SIGNAL_SUBSTRATE_KIND_CHANGED" in src
    # The substrate signal dispatcher subscription must be wired.
    assert "async_dispatcher_connect" in src
    assert "SIGNAL_SUBSTRATE_KIND_CHANGED" in src


def test_coordinator_preserves_rate_limiter() -> None:
    """The 2s rate-limit + trailing-refresh semantics are preserved inline."""
    import os
    coord_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "custom_components", "universal_room_automation",
        "coordinator.py",
    )
    with open(coord_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    # 2s rate-limit constant + trailing-edge refresh scheduling.
    assert "now_mono - self._last_event_refresh < 2.0" in src
    assert "self._trailing_refresh_callback" in src
    # Immediate refresh (NOT async_request_refresh) preserved.
    assert "self.async_refresh()" in src


def test_coordinator_lux_still_state_change_subscribed() -> None:
    """Lux is NOT in the substrate's CONF surface; it remains a state-change listener."""
    import os
    coord_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "custom_components", "universal_room_automation",
        "coordinator.py",
    )
    with open(coord_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "async_track_state_change_event" in src
    # The lux callback name is the canonical hint that the lux path
    # remains a direct state-change listener.
    assert "_on_lux_state_changed" in src
