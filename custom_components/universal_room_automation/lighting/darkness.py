"""Darkness fallback for entry-lighting decisions (Slice B).

Called by ``RoomAutomation.is_dark`` when the primary lux reading is
None (no sensor configured, or sensor state is `unavailable` /
`unknown`). Order per ``PLANNING_room_dialog_cleanup_and_lighting_roles.md``
§D1 (:191-196):

1. Borrowed lux source (`CONF_LIGHT_DARK_LUX_SOURCE`) if set AND its
   state is a usable number — compare to `CONF_ILLUMINANCE_THRESHOLD`.
2. Sun-position fallback: `sun.sun` attribute ``elevation`` strictly
   less than ``SUN_DARK_ELEVATION_DEG`` (default -6 civil dusk).
3. Otherwise False — preserves today's `is_dark(None) == False`.

Freshness (R2-3) is availability-only: a sensor in state
`unavailable` / `unknown` is skipped. `last_updated` age is NEVER
consulted — a dark night can legitimately hold a fresh 0 for hours.

Per-room kill switch: `CONF_LIGHT_DARK_USE_SUN_FALLBACK`, default TRUE
per operator P0 ruling. Setting it False on a room preserves today's
behaviour for that room.

All external reads are guarded — a bad state, missing entity, or
exception falls through to False (fail-safe: rooms without a working
darkness signal do NOT auto-light).
"""
from __future__ import annotations

import logging
from typing import Any

from ..const import (
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_DARK_LUX_SOURCE,
    CONF_LIGHT_DARK_USE_SUN_FALLBACK,
    SUN_DARK_ELEVATION_DEG,
)

_LOGGER = logging.getLogger(__name__)

_UNUSABLE_STATES = ("unavailable", "unknown", None, "")


def _read_lux(hass: Any, entity_id: str) -> float | None:
    """Read a lux sensor's state as a float, or None if unusable."""
    if hass is None or not entity_id:
        return None
    try:
        state = hass.states.get(entity_id)
    except Exception:  # noqa: BLE001
        return None
    if state is None:
        return None
    if state.state in _UNUSABLE_STATES:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _read_sun_elevation(hass: Any) -> float | None:
    """Read `sun.sun` elevation attribute; None if unavailable."""
    if hass is None:
        return None
    try:
        state = hass.states.get("sun.sun")
    except Exception:  # noqa: BLE001
        return None
    if state is None or state.state in _UNUSABLE_STATES:
        return None
    try:
        elev = state.attributes.get("elevation")
        if elev is None:
            return None
        return float(elev)
    except (TypeError, ValueError, AttributeError):
        return None


def is_dark_fallback(cfg: dict, hass: Any) -> bool:
    """Return True iff the room should be treated as dark right now,
    given that the primary lux read did not resolve.

    Ordering matches the plan:
      1. Borrowed lux (CONF_LIGHT_DARK_LUX_SOURCE)
      2. Sun fallback (CONF_LIGHT_DARK_USE_SUN_FALLBACK, default TRUE)
      3. False
    """
    try:
        threshold = cfg.get(CONF_ILLUMINANCE_THRESHOLD, 20)
        # 1. Borrowed lux
        borrow = cfg.get(CONF_LIGHT_DARK_LUX_SOURCE)
        if borrow:
            lux = _read_lux(hass, borrow)
            if lux is not None:
                return lux < threshold
        # 2. Sun fallback (kill switch default TRUE)
        use_sun = cfg.get(CONF_LIGHT_DARK_USE_SUN_FALLBACK, True)
        if not use_sun:
            return False
        elev = _read_sun_elevation(hass)
        if elev is None:
            return False
        return elev < SUN_DARK_ELEVATION_DEG
    except Exception:  # noqa: BLE001 — fail-safe: do not auto-light on error
        _LOGGER.debug("is_dark_fallback failed for cfg keys=%s",
                      list(cfg.keys()) if hasattr(cfg, "keys") else "?",
                      exc_info=True)
        return False
