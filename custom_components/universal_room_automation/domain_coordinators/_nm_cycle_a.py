"""NM Cycle A (2026-07-20) — shared knob lookup helper.

The Cycle A noise-reduction knobs land as DEFAULTS in const.py with
matching CONF_* keys. NM Cycle A-2 (2026-07-20) promoted them to
rung-2 options-flow fields (see `config_flow.py` step
`async_step_coordinator_notifications_volume`) and added an update
listener that invokes :func:`invalidate_knob_cache` on every CM
options-update so cached knob values are re-read from `entry.options`
on the next call.

Cache design (A-2, B-LOW-1 resolution):
  - Process-wide module-level dict, keyed by CONF_ key.
  - Total-flush per options-update event — per-key invalidation deferred
    (operator ruling 2026-07-20). Keeps the correctness proof trivial.
  - Never raises. A mis-typed override falls back to the default with a
    DEBUG log; the cache stores the coerced default in that case.

Cache-key assumption (A-2 fix-up 2026-07-20, deferred item B2):
  - The cache is keyed by conf_key only — NOT by hass instance. This is
    safe under the operator's SINGLE-CoordinatorManager deployment model
    (one URA install per HA). If a multi-CM future emerges, the cache
    must be re-keyed by ``(hass, conf_key)``.
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

# Process-wide cache. Values are whatever `nm_cycle_a_knob` last returned
# for a given conf_key (already coerced to type(default)). Total-flushed
# by `invalidate_knob_cache()` on every CM options-update.
_KNOB_CACHE: dict[str, Any] = {}


def invalidate_knob_cache(conf_key: str | None = None) -> None:
    """Flush cached NM Cycle A knob values.

    NM Cycle A-2 B-LOW-1: called from the CM options-update listener BEFORE
    `_apply_in_place`, unconditionally per invocation, so the next
    `nm_cycle_a_knob` call after apply reads fresh from `entry.options`.

    `conf_key=None` (default) flushes the entire cache — operator ruling
    2026-07-20: total-flush is the correctness-first choice. Per-key
    invalidation is a Cycle-B+ optimization if profiling ever demands it.
    """
    if conf_key is None:
        _KNOB_CACHE.clear()
    else:
        _KNOB_CACHE.pop(conf_key, None)


def nm_cycle_a_knob(hass: HomeAssistant, conf_key: str, default: T) -> T:
    """Return operator override for `conf_key` from the CM options, else `default`.

    Reads the first ENTRY_TYPE_COORDINATOR_MANAGER config entry's merged
    (data | options) dict. If the CM entry is not yet present (early boot),
    returns `default`. Never raises.

    The return type is coerced to `type(default)` when possible — a stray
    string on a numeric knob falls back to the default with a DEBUG log
    rather than propagating a TypeError into the safety pipeline.

    Cached process-wide; :func:`invalidate_knob_cache` flushes on options
    update.
    """
    if conf_key in _KNOB_CACHE:
        return _KNOB_CACHE[conf_key]  # type: ignore[return-value]
    value: Any = default
    try:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                continue
            merged: dict[str, Any] = {**entry.data, **entry.options}
            if conf_key not in merged:
                value = default
                break
            raw = merged[conf_key]
            if isinstance(default, bool):
                if isinstance(raw, bool):
                    value = raw
                elif isinstance(raw, str):
                    value = raw.strip().lower() in {"true", "1", "yes", "on"}
                else:
                    value = default
            elif isinstance(default, int) and not isinstance(default, bool):
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    value = default
            elif isinstance(default, float):
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    value = default
            elif isinstance(default, (tuple, list, frozenset, set)):
                if isinstance(raw, (list, tuple, set, frozenset)):
                    value = type(default)(raw)
                else:
                    value = default
            else:
                value = raw
            break
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "nm_cycle_a_knob(%s): lookup failed, using default %r",
            conf_key, default, exc_info=True,
        )
        value = default
    _KNOB_CACHE[conf_key] = value
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# NM Cycle A-2 fix-up (C-HIGH-2 / C-HIGH-3, 2026-07-20)
# ---------------------------------------------------------------------------
#
# The optimizer HIGH-defer allowlist gate lives in
# ``optimization.py::_notify_if_severe``. Two behavioral properties need
# mutation-anchored coverage:
#
#   * Case + Enum-value normalization (C-HIGH-2). The read side must lower
#     BOTH the allowlist entries and the finding's ``dimension`` (unwrapping
#     ``.value`` if it's an Enum), so a persisted lowercase allowlist matches
#     an Enum-valued dimension.
#   * The defer gate itself (C-HIGH-3): a HIGH finding whose dimension is
#     NOT in the allowlist must be deferred (helper returns True); a HIGH
#     finding whose dimension IS in the allowlist must page NM (helper
#     returns False).
#
# Extracting the two helpers into this module makes both behaviors
# testable directly against the production path — no need to construct
# an OptimizationCoordinator instance in tests.


def high_finding_allowlisted(hass: HomeAssistant, finding: Any) -> bool:
    """Return True if the finding's ``dimension`` is in the CM-options NM allowlist.

    Both sides are normalized to lowercased strings; the finding's
    ``dimension`` may be an Enum (``.value`` is unwrapped), a str, or None.
    None-dimension is treated as "not allowlisted" (empty string never
    matches a non-empty allowlist entry).
    """
    from ..const import (
        CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
        DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
    )
    allowlist_raw = nm_cycle_a_knob(
        hass,
        CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
        DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
    )
    allowlist = frozenset(str(x).lower() for x in (allowlist_raw or ()))
    dim = getattr(finding, "dimension", None)
    dim_val = getattr(dim, "value", dim)
    dim_str = str(dim_val).lower() if dim_val is not None else ""
    return dim_str in allowlist


def should_defer_high_to_digest(hass: HomeAssistant, finding: Any) -> bool:
    """Return True iff the caller should DEFER this finding to the daily digest.

    A finding is deferred iff its severity is ``"high"`` AND its
    ``dimension`` is not in the allowlist. CRITICAL findings are never
    deferred here (caller keeps them on the immediate-page path).
    """
    severity = getattr(finding, "severity", None)
    if severity != "high":
        return False
    return not high_finding_allowlisted(hass, finding)
