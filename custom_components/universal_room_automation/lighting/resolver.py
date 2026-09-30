"""Room lighting set resolver (Slice A — additive, zero-behaviour-change).

`effective_entry_set(cfg, is_sleep_hours)` returns the list of light-domain
entity_ids the entry path would turn ON for this room right now, matching
today's live derivation at:

  * `automation.py:_control_lights_entry` (:1000-1064)
      - sleep hours + night_lights present → night lights only
      - otherwise                          → CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS
  * `actuator_reconciler.py` entry-action path (:748-813) — same union

`effective_exit_set(cfg)` returns the list of light-domain entity_ids the
exit / vacancy path would turn OFF, matching today's live union at:

  * `automation.py:_control_lights_exit` (:1079-1082)
  * `actuator_reconciler.py:109` (`_LIGHT_KEYS = (CONF_LIGHTS, CONF_NIGHT_LIGHTS)`)

Later slices extend this module (never re-derive inline). Order is
preserved because HA services accept the list as given and dashboards
render it in order. Duplicates are removed while preserving first
occurrence — matches today's exit path (see line 1081 `if e not in regular`).

This module has NO Home Assistant imports so it can be unit-tested
without the full HA harness. It reads only string keys from a plain
dict-like ``cfg``.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..const import (
    CONF_LIGHTS,
    CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY,
    CONF_LIGHTS_ON_ENTRY,
    CONF_LIGHTS_ON_ENTRY_DARK_ONLY,
    CONF_NIGHT_LIGHTS,
)


def _dedup_preserving_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for e in items:
        if e in seen:
            continue
        seen.add(e)
        out.append(e)
    return out


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    # single-string fallback (defensive; today's config-flow saves lists)
    return [str(value)]


def effective_entry_set(
    cfg: dict,
    is_sleep_hours: bool,
    is_dark: bool | None = None,
) -> list[str]:
    """Return the entities entry should turn ON for this room right now.

    Args:
        cfg: room config dict (``self.config`` in automation.py, ``options``
            in the reconciler path).
        is_sleep_hours: value of ``RoomAutomation.is_sleep_mode_active()``.
        is_dark: current dark state. Only consulted when the room has
            ``CONF_LIGHTS_ON_ENTRY_DARK_ONLY`` set — those entries are
            removed when ``is_dark is False`` (explicitly False, not
            None). ``None`` preserves today's "always include" behaviour.

    Slice B' (v5.103.28): when ``CONF_LIGHTS_ON_ENTRY`` is set on the
    room, the entry set is exactly that list (intersected with sleep
    semantics + dark-only carve-out). ABSENT ⇒ today's
    ``CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`` union.
    """
    lights = _as_list(cfg.get(CONF_LIGHTS))
    night = _as_list(cfg.get(CONF_NIGHT_LIGHTS))
    on_entry = _as_list(cfg.get(CONF_LIGHTS_ON_ENTRY))
    dark_only = set(_as_list(cfg.get(CONF_LIGHTS_ON_ENTRY_DARK_ONLY)))

    if is_sleep_hours and night:
        # matches automation.py:1023-1027 — night lights only
        return _dedup_preserving_order(night)

    if on_entry:
        # Slice B' explicit picker: honour operator's on-entry list.
        base = on_entry
    else:
        # ABSENT ⇒ today: union, LIGHTS first
        base = lights + night

    if dark_only and is_dark is False:
        base = [e for e in base if e not in dark_only]

    return _dedup_preserving_order(base)


def effective_exit_set(cfg: dict) -> list[str]:
    """Return the entities the vacancy / exit path should turn OFF.

    Matches today's unconditional union at ``automation.py:1079-1082`` and
    ``actuator_reconciler.py:109``. Sleep gating is intentionally NOT
    applied here — night lights are treated like any occupancy light on
    vacancy per the NIGHT-LIGHT-NO-OFF-PATH-1 rule (operator ruling
    2026-09-01, cited at automation.py:1072-1077).
    """
    lights = _as_list(cfg.get(CONF_LIGHTS))
    night = _as_list(cfg.get(CONF_NIGHT_LIGHTS))
    leave_on = set(_as_list(cfg.get(CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY)))
    union = _dedup_preserving_order(lights + night)
    if leave_on:
        # Slice B' (v5.103.28): carve out leave-on-when-empty entries.
        # ABSENT ⇒ today's unconditional union. Applies to hand-switched
        # lights too — see plan Vacancy rule.
        return [e for e in union if e not in leave_on]
    return union
