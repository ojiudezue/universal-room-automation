"""NM Cycle A (2026-07-20) — shared knob lookup helper.

The Cycle A noise-reduction knobs land as DEFAULTS in const.py with
matching CONF_* keys reserved. Config-flow UI + reload-suppression +
live-apply setters are Cycle A-2 (separate plan). Until then, coordinator
code reads knob values through :func:`nm_cycle_a_knob`, which returns any
operator override present on the CoordinatorManager options dict and falls
back to the DEFAULT_*.

This keeps the read-path future-proof: when Cycle A-2 lands the UI, no
call-site edits are needed — the same helper picks up the persisted option.

Never raises — a mis-typed override falls back to the default with a
DEBUG log. Deliberately does NOT cache: options edits are infrequent and
the CM dict lookup is O(1); caching would need reload-suppression wiring
that also lands in Cycle A-2.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
)

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


def nm_cycle_a_knob(hass: HomeAssistant, conf_key: str, default: T) -> T:
    """Return operator override for `conf_key` from the CM options, else `default`.

    Reads the first ENTRY_TYPE_COORDINATOR_MANAGER config entry's merged
    (data | options) dict. If the CM entry is not yet present (early boot),
    returns `default`. Never raises.

    The return type is coerced to `type(default)` when possible — a stray
    string on a numeric knob falls back to the default with a DEBUG log
    rather than propagating a TypeError into the safety pipeline.
    """
    try:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                continue
            merged: dict[str, Any] = {**entry.data, **entry.options}
            if conf_key not in merged:
                return default
            raw = merged[conf_key]
            if isinstance(default, bool):
                if isinstance(raw, bool):
                    return raw  # type: ignore[return-value]
                if isinstance(raw, str):
                    return (raw.strip().lower() in {"true", "1", "yes", "on"})  # type: ignore[return-value]
                return default
            if isinstance(default, int) and not isinstance(default, bool):
                return int(raw)  # type: ignore[return-value]
            if isinstance(default, float):
                return float(raw)  # type: ignore[return-value]
            if isinstance(default, (tuple, list, frozenset, set)):
                if isinstance(raw, (list, tuple, set, frozenset)):
                    return type(default)(raw)  # type: ignore[return-value]
                return default
            return raw  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "nm_cycle_a_knob(%s): lookup failed, using default %r",
            conf_key, default, exc_info=True,
        )
    return default
