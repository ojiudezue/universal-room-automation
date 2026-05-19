"""v4.6.13 — Coordinator telemetry constants for Dashboard v5.0 Diagnostics tab.

Defines the UI→emit-label mapping that rolls up activity_log rows under the
five UI coordinators surfaced on the dashboard. Adjusting the mapping is a
one-file change with no sensor-class touch.

Source of truth — five UI coordinators (P6 dashboard prototype):
    presence, hvac, energy, safety, security

`transit` and `room` emit labels (transitions.py / automation.py / coordinator.py)
are sourced from room-level occupancy detection — semantically part of the
presence subsystem from the user's perspective.

`compliance` and `notification` emit-labels are intentionally NOT mapped.
They are meta-events; rolling them up would double-count.
"""
from __future__ import annotations

from typing import Final


# UI coordinator name → tuple of emit-labels rolled up under it.
# Used by v4.6.13 D1, D2, D3, D5 to filter activity_log / compliance_log rows.
COORDINATOR_EMIT_LABELS: Final[dict[str, tuple[str, ...]]] = {
    "presence": ("presence", "transit", "room"),
    "hvac": ("hvac",),
    "energy": ("energy",),
    "safety": ("safety",),
    "security": ("security",),
}


# Ordered list for deterministic sensor registration order.
UI_COORDINATORS: Final[tuple[str, ...]] = (
    "presence",
    "hvac",
    "energy",
    "safety",
    "security",
)


# Polling intervals for the time-based refresh sensors.
OVERRIDE_FREQUENCY_REFRESH_S: Final[int] = 300  # 5 minutes (D2)
COMPLIANCE_RATE_REFRESH_S: Final[int] = 1800  # 30 minutes (D3)
DB_SIZE_REFRESH_S: Final[int] = 300  # 5 minutes (D4)

# Windows
OVERRIDE_FREQUENCY_WINDOW_HOURS: Final[int] = 24  # D2 last-24h window
COMPLIANCE_RATE_WINDOW_DAYS: Final[int] = 7  # D3 7-day window
