"""Room classification — derived read-model accessor (Option C).

ROOM-CLASSIFICATION-CONSISTENCY-1, D-C1.

Presents a room's classification (function / flags / outdoor / infrastructure)
as a single projection over existing config surfaces. No state, no dispatch,
no writes. Every field is derived at read time from the SAME producers the
real consumers already read from — this accessor is purely additive and does
NOT modify any existing classification consumer.

Sources (see docs/planning/PLANNING_room_classification_option_c.md):
- function : ``{**data, **options}[CONF_ROOM_TYPE]`` (options-wins merge).
- flags    : the subset of {guest, wet, shared} whose CONF_* keys are truthy
             on the merged dict. Same keys the real consumers read:
             CONF_ROOM_IS_GUEST_ROOM, CONF_WET_ROOM, CONF_SHARED_SPACE.
- outdoor  : ``zone_of(room) in outdoor_zone_names_snapshot(hass)`` where
             ``zone_of = {**data, **options}.get(CONF_ZONE)`` — options-wins,
             matches the safety authority at safety.py:1319-1322.
             REUSES the module-level ``outdoor_zone_names_snapshot`` from
             ``domain_coordinators/safety.py`` (NOT the coercion at
             ``safety.py:1319``). Discriminating: this returns ``outdoor=True``
             for the Patio even when the SafetyCoordinator is absent from
             ``hass.data``.
- infrastructure : ``getattr(coord, "_infrastructure_room", room_type ==
             "infrastructure")`` via ``hass.data[DOMAIN][entry.entry_id]``.
             This is the collapsed representation the real consumers read
             (aggregation.py:3522/3539/3589/...); the switch writes through
             to it (switch.py:5137/5142). Boot fallback: if the coordinator
             is not yet in ``hass.data``, fall back to ``room_type ==
             "infrastructure"``.

Cache: REUSES the ``hass.data[DOMAIN]["_outdoor_zones_cache"]`` set populated
and invalidated by ``ZoneSafetyAlertSensor._invalidate_zone_configured_cache``
on ``SIGNAL_ZM_ZONES_UPDATED`` (aggregation.py:4621-4649). A second consumer
inherits that single staleness point — acceptable and documented in the plan.
If the cache is missing (e.g. before the aggregation sensor has run) this
accessor populates it via ``outdoor_zone_names_snapshot(hass)``.
"""

from __future__ import annotations

import logging
from typing import Any

from .const import (
    CONF_ROOM_IS_GUEST_ROOM,
    CONF_ROOM_TYPE,
    CONF_SHARED_SPACE,
    CONF_WET_ROOM,
    CONF_ZONE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _get_outdoor_zones(hass) -> set[str]:
    """Return the set of outdoor zone names, using the shared hass.data cache.

    Reuses ``hass.data[DOMAIN]["_outdoor_zones_cache"]`` populated (and
    invalidated on SIGNAL_ZM_ZONES_UPDATED) by
    ``ZoneSafetyAlertSensor._invalidate_zone_configured_cache``
    (aggregation.py:4641). Fresh-scans via ``outdoor_zone_names_snapshot``
    on cache miss. Fails open (empty set) on any error.
    """
    try:
        bag = hass.data.get(DOMAIN, {})
        cached = bag.get("_outdoor_zones_cache")
        if cached is not None:
            return cached
        # Cache miss: fresh-scan but DO NOT write the cache. This accessor is
        # a pure READER of a cache owned+invalidated by ZoneSafetyAlertSensor
        # (aggregation.py:4641, SIGNAL_ZM_ZONES_UPDATED). If a room-sensor read
        # seeded the cache before any zone existed, a later outdoor-zone add
        # would leave the safety consumer reading a stale empty set until
        # restart (review M1). The aggregation sensor fills it correctly at
        # boot; we just fresh-scan in the gap. Import lazily to avoid cycles.
        from .domain_coordinators.safety import outdoor_zone_names_snapshot
        return outdoor_zone_names_snapshot(hass)
    except Exception:  # noqa: BLE001 — fail-open, this is a diagnostic
        _LOGGER.debug(
            "room_classification: outdoor-zone cache read failed; "
            "returning empty set (fail-open)",
            exc_info=True,
        )
        return set()


def get_room_classification(hass, room_entry) -> dict[str, Any]:
    """Return the unified read-only classification for a room config entry.

    Args:
        hass: HomeAssistant instance.
        room_entry: a room ConfigEntry (ENTRY_TYPE_ROOM).

    Returns:
        ``{"function": str, "flags": list[str], "outdoor": bool,
        "infrastructure": bool}``. Every field derived from the SAME
        producers real consumers read (see module docstring). No dispatch,
        no writes, no coercion.

    Fails open to the empty-default dict on ANY error — this feeds a room
    sensor's extra_state_attributes, which must never raise (an escape would
    blank every OTHER attribute on that sensor, not just classification;
    review L1).
    """
    try:
        return _compute_room_classification(hass, room_entry)
    except Exception:  # noqa: BLE001 — fail-open, this is a display diagnostic
        _LOGGER.debug(
            "room_classification: get_room_classification failed; "
            "returning empty default (fail-open)",
            exc_info=True,
        )
        return {"function": "", "flags": [], "outdoor": False,
                "infrastructure": False}


def _compute_room_classification(hass, room_entry) -> dict[str, Any]:
    """Inner computation for :func:`get_room_classification` (may raise)."""
    # Merged config: options-wins (matches config_flow.py:435 and the safety
    # authority at safety.py:1319-1322). data-first (aggregation.py:745) is
    # inverted / Bug Class #14 and NOT the model here.
    try:
        merged: dict[str, Any] = {**room_entry.data, **room_entry.options}
    except Exception:  # noqa: BLE001
        merged = {}

    function = merged.get(CONF_ROOM_TYPE) or ""

    flags: list[str] = []
    if merged.get(CONF_ROOM_IS_GUEST_ROOM):
        flags.append("guest")
    if merged.get(CONF_WET_ROOM):
        flags.append("wet")
    if merged.get(CONF_SHARED_SPACE):
        flags.append("shared")

    # Outdoor = the room's zone is in the outdoor-zone set.
    zone_of = merged.get(CONF_ZONE)
    if zone_of:
        outdoor = zone_of in _get_outdoor_zones(hass)
    else:
        outdoor = False

    # Infrastructure — read the coordinator's collapsed representation, not
    # the switch state. Boot fallback: room_type == "infrastructure".
    infrastructure = function == "infrastructure"
    try:
        entry_id = getattr(room_entry, "entry_id", None)
        if entry_id:
            coord = hass.data.get(DOMAIN, {}).get(entry_id)
            if coord is not None:
                infrastructure = bool(
                    getattr(coord, "_infrastructure_room", infrastructure)
                )
    except Exception:  # noqa: BLE001 — fail-safe to the room_type fallback
        _LOGGER.debug(
            "room_classification: infrastructure lookup failed; "
            "falling back to room_type==infrastructure",
            exc_info=True,
        )

    return {
        "function": function,
        "flags": flags,
        "outdoor": bool(outdoor),
        "infrastructure": bool(infrastructure),
    }
