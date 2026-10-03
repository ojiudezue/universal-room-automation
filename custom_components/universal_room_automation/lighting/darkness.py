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
    CONF_OUTDOOR_DARK_LUX,
    CONF_OUTDOOR_LIGHT_SENSOR,
    DEFAULT_OUTDOOR_DARK_LUX,
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


def _integration_options(hass: Any) -> dict:
    """Return the URA integration entry's merged data+options, or {}.

    The outdoor-light knobs live at integration level (Global Sensors
    options step). Room-scope darkness code needs to reach up to read
    them. Fail-safe: any exception ⇒ {} (falls through to sun tier).
    """
    if hass is None:
        return {}
    try:
        from ..const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_INTEGRATION
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                return {**entry.data, **entry.options}
    except Exception:  # noqa: BLE001
        return {}
    return {}


def discover_outdoor_illuminance_suggestion(hass: Any) -> str | None:
    """Return the first enabled `illuminance`-platform entity_id, or None.

    Used by the Global Sensors form as the SUGGESTED value for
    CONF_OUTDOOR_LIGHT_SENSOR when unset. Not consumed by the runtime
    darkness fallback — the runtime reads ONLY the configured field.
    """
    if hass is None:
        return None
    try:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        for entry in registry.entities.values():
            try:
                if entry.platform != "illuminance":
                    continue
                if entry.disabled_by is not None:
                    continue
                return entry.entity_id
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return None
    return None


def is_dark_fallback(cfg: dict, hass: Any) -> bool:
    """Return True iff the room should be treated as dark right now,
    given that the primary lux read did not resolve.

    Ordering (v5.103.28 Slice B' REV 2.4):
      1. Borrowed lux (CONF_LIGHT_DARK_LUX_SOURCE) — room-scale threshold.
      2. Outdoor illuminance (auto-discovered from HA `illuminance`
         integration) — compared against OUTDOOR_DARK_LUX (module const,
         400). Gated by CONF_LIGHT_DARK_USE_SUN_FALLBACK (renamed:
         "Use outdoor light when there's no room sensor").
      3. Sun elevation < SUN_DARK_ELEVATION_DEG — only when no outdoor
         illuminance sensor exists. Same kill-switch as tier 3.
      4. False — preserves today's `is_dark(None) == False`.

    Availability-only freshness for all sensor reads.
    """
    try:
        threshold = cfg.get(CONF_ILLUMINANCE_THRESHOLD, 20)
        # 1. Borrowed lux (room-scale threshold)
        borrow = cfg.get(CONF_LIGHT_DARK_LUX_SOURCE)
        if borrow:
            lux = _read_lux(hass, borrow)
            if lux is not None:
                return lux < threshold
        # Kill switch disables tiers 3 AND 4 (outdoor + sun).
        use_outdoor = cfg.get(CONF_LIGHT_DARK_USE_SUN_FALLBACK, True)
        if not use_outdoor:
            return False
        # 2. Outdoor illuminance (configured at integration level; visible
        # in Global Sensors). No silent auto-discovery: unset ⇒ skip to sun.
        integration = _integration_options(hass)
        outdoor_eid = integration.get(CONF_OUTDOOR_LIGHT_SENSOR)
        outdoor_threshold = float(
            integration.get(CONF_OUTDOOR_DARK_LUX, DEFAULT_OUTDOOR_DARK_LUX)
        )
        if outdoor_eid:
            outdoor_lux = _read_lux(hass, outdoor_eid)
            if outdoor_lux is not None:
                return outdoor_lux < outdoor_threshold
            # outdoor sensor unavailable/unknown → fall through to sun.
        # 3. Sun elevation (only reached when no outdoor sensor
        # configured OR its state was unavailable).
        elev = _read_sun_elevation(hass)
        if elev is None:
            return False
        return elev < SUN_DARK_ELEVATION_DEG
    except Exception:  # noqa: BLE001 — fail-safe: do not auto-light on error
        _LOGGER.debug("is_dark_fallback failed for cfg keys=%s",
                      list(cfg.keys()) if hasattr(cfg, "keys") else "?",
                      exc_info=True)
        return False
