"""Shared cover-ownership check.

Covers whose ``device_class`` is ``garage`` or ``gate`` are owned by the
Security coordinator (see ``domain_coordinators/security.py`` for the
sole legitimate ``cover.close_cover`` writers). Neither the room-tier
cover automation (``automation.py``) nor the HVAC solar-gain cover
manager (``domain_coordinators/hvac_covers.py``) may open/close them.

This module is the single source of truth for that check so:
  * ``automation._get_available_covers`` filters them out at the room
    tier (entry, exit, timed-open, timed-close, sleep-block paths),
  * ``automation._send_covers_with_verify`` filters again at the choke
    point (defence in depth against any future direct-write caller),
  * ``hvac_covers._is_garage_cover`` delegates here (previously
    garage-only; now also excludes ``gate``).

Rung: module constant (safety rule, no operator knob per
ROOM-COVERS-NO-GARAGE-DOOR-GUARD-1: "no config knob (safety rule, rung 1)").
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

# ``device_class`` values that mean "Security owns this cover".
SECURITY_OWNED_COVER_DEVICE_CLASSES: frozenset[str] = frozenset({"garage", "gate"})


def _registry_device_class(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return the entity registry's device_class for ``entity_id`` (or None).

    Reads ``device_class`` first, then falls back to ``original_device_class``
    (the integration-declared value that survives when the user hasn't set an
    override). All lookups are guarded.
    """
    try:
        registry = er.async_get(hass)
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug(
            "_registry_device_class: entity_registry.async_get failed",
            exc_info=True,
        )
        return None
    if registry is None:
        return None
    try:
        entry = registry.async_get(entity_id)
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug(
            "_registry_device_class: registry.async_get failed for %s",
            entity_id, exc_info=True,
        )
        return None
    if entry is None:
        return None
    return getattr(entry, "device_class", None) or getattr(
        entry, "original_device_class", None
    )


def is_security_owned_cover_by_registry(hass: HomeAssistant, entity_id: str) -> bool:
    """Registry-only variant of ``is_security_owned_cover``.

    Used at the room-tier ``_send_covers_with_verify`` choke point so the
    guard does NOT perform a ``hass.states.get`` (which would be a
    redundant read against a stale in-flight state and, in the
    scripted-state test shim, would perturb the verify-loop's state
    sequence). ``device_class`` is a static, integration-declared
    attribute — registry is the correct source at the defence-in-depth
    site. Live callers first pass through
    :func:`is_security_owned_cover` in ``_get_available_covers`` which
    also consults state attributes.
    """
    return _registry_device_class(hass, entity_id) in SECURITY_OWNED_COVER_DEVICE_CLASSES


def is_security_owned_cover(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True if ``entity_id`` is a garage/gate cover.

    Reads ``device_class`` from the live state's attributes first, then
    falls back to the entity registry (``device_class`` /
    ``original_device_class``) when the state is missing or the
    attribute isn't set — an entity that is currently ``unavailable``
    still needs to be guarded, because URA schedules the write and the
    entity may come back before dispatch.

    Both reads are guarded — a broken state/registry MUST NOT crash the
    caller's write path. On any failure we return False (fail open on
    the check → the caller's other guards, including the state-availability
    filter, still apply). Live callers (``_get_available_covers``) log
    once per (room, cover) when a skip fires; that log is the ledger.
    """
    try:
        state = hass.states.get(entity_id)
    except Exception:  # pragma: no cover - defensive
        _LOGGER.debug(
            "is_security_owned_cover: hass.states.get failed for %s",
            entity_id, exc_info=True,
        )
        state = None

    if state is not None:
        try:
            attrs = state.attributes or {}
            dc = attrs.get("device_class")
            if dc in SECURITY_OWNED_COVER_DEVICE_CLASSES:
                return True
            if dc is not None:
                # A non-garage/gate device_class is authoritative — no
                # need to consult the registry.
                return False
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug(
                "is_security_owned_cover: state.attributes read failed for %s",
                entity_id, exc_info=True,
            )

    # Fallback: entity registry.
    return _registry_device_class(hass, entity_id) in SECURITY_OWNED_COVER_DEVICE_CLASSES
