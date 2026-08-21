"""RECORDER-BLOAT-LOGFLOOD-1 (2026-08-21) — edge-triggered notify latch
for the "duty-cycle stuck — NOTIFY-ONLY" WARNING.

Extracted from ``coordinator.py`` so tests can drive the real
production helpers without the full HA import graph. The pre-cycle
behaviour re-announced a persistent stuck state every tick per sensor
(3565 hits in 5h across two sensors in a single production window);
these helpers convert that to edge-triggered:

  * WARN once on entry into the notify-only stuck set;
  * INFO on the release edge (re-arms the latch for a future re-engage).

Detection is unchanged — only the announcement cadence. The current
notify-only set is exposed on ``sensor.<room>_unavailable_entities``
as ``dutycycle_stuck_notify`` (sensor.py) so operators still see the
condition without grepping historical logs.
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def notify_warn_on_enter(
    active: set[str], sensor: str, room_name: str,
    logger: logging.Logger | None = None,
) -> bool:
    """Emit the NOTIFY-ONLY WARNING iff ``sensor`` is entering ``active``.

    Returns True (and warns) on the edge; False (silent) while the sensor
    remains in ``active`` on subsequent ticks. Mutates ``active`` in place.
    """
    log = logger or _LOGGER
    if sensor in active:
        return False
    active.add(sensor)
    log.warning(
        "Room %s: Sensor %s duty-cycle stuck (on-ratio exceeded over "
        "rolling window) — NOTIFY-ONLY, not excluded from occupancy",
        room_name, sensor,
    )
    return True


def notify_release(
    active: set[str], current_notify: set[str], room_name: str,
    logger: logging.Logger | None = None,
) -> set[str]:
    """Release-edge scan: sensors in ``active`` but not in ``current_notify``
    have recovered this tick. Drop them from ``active`` (in place) and
    emit the paired INFO so a subsequent re-engage warns again
    (suppression-needs-discharge).

    Returns the released set.
    """
    log = logger or _LOGGER
    released = active - current_notify
    for s in released:
        active.discard(s)
        log.info(
            "Room %s: Sensor %s duty-cycle stuck condition released "
            "(no longer on-ratio-stuck this tick)",
            room_name, s,
        )
    return released
