"""Shared BLE corroboration helpers for fan-noise mitigation cycles.

Extracted from presence.py:2787-2818 (zone-tier v4.7.20 gate) so the new
room-tier fan-recheck mechanism can call the same H2 carve-out logic without
duplicating it. Behavior is unchanged from the zone-tier inlined version.

`_phone_trustworthy` returns True (fail-OPEN) whenever the
`PersonPhoneLeftBehindSensor` for a person is missing / unknown / unavailable.
A phone-left-behind person (sensor == "on") returns False — that person must
not count as "BLE present" when evaluating L1 / L2.

Fail-OPEN matters: a left-behind phone reads "person home via BLE" to the
person tracker, but the corroboration ladder must treat that as NO BLE
evidence (else the gate / pause would be wrongly vetoed).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN

if TYPE_CHECKING:
    from ..person_coordinator import PersonTrackingCoordinator

_LOGGER = logging.getLogger(__name__)
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})


def phone_trustworthy(hass: HomeAssistant, person_name: str) -> bool:
    """Return False iff PersonPhoneLeftBehindSensor for this person is "on".

    Fail-OPEN: missing sensor / entity_registry failure / unknown / unavailable
    all return True. Mirrors presence.py:2787-2808 verbatim.
    """
    person_slug = (person_name or "").lower().replace(" ", "_")
    if not person_slug:
        return True
    unique_id = f"{DOMAIN}_person_{person_slug}_phone_left_behind"
    entity_id: Optional[str] = None
    try:
        entity_reg = er.async_get(hass)
    except Exception:  # noqa: BLE001 — fail-OPEN
        entity_reg = None
    if entity_reg is not None:
        try:
            entity_id = entity_reg.async_get_entity_id(
                "binary_sensor", DOMAIN, unique_id,
            )
        except Exception:  # noqa: BLE001 — fail-OPEN
            entity_id = None
    if entity_id is None:
        return True
    try:
        state = hass.states.get(entity_id)
    except Exception:  # noqa: BLE001 — fail-OPEN
        return True
    if state is None or state.state in _UNAVAILABLE_STATES:
        return True
    return state.state != "on"


def trustworthy_persons_in_room(
    hass: HomeAssistant,
    person_coord: "PersonTrackingCoordinator | None",
    room: str,
) -> List[str]:
    """Return persons in room whose phone is trustworthy (H2 carve-out)."""
    if person_coord is None or not room:
        return []
    try:
        raw = person_coord.get_persons_in_room(room) or []
    except Exception:  # noqa: BLE001 — defensive
        return []
    return [p for p in raw if phone_trustworthy(hass, p)]


def trustworthy_persons_in_zone(
    hass: HomeAssistant,
    person_coord: "PersonTrackingCoordinator | None",
    zone_rooms: List[str],
) -> List[str]:
    """Return persons in the zone whose phone is trustworthy."""
    if person_coord is None or not zone_rooms:
        return []
    try:
        raw = person_coord.get_persons_in_zone(zone_rooms) or []
    except Exception:  # noqa: BLE001 — defensive
        return []
    return [p for p in raw if phone_trustworthy(hass, p)]
