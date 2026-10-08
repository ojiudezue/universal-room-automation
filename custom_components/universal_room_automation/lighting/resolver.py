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
    CONF_LIGHT_CAPABILITIES,
    CONF_LIGHT_EVENING_BRIGHTNESS_PCT,
    CONF_LIGHT_EVENING_COLOR_KELVIN,
    CONF_LIGHT_SCENE_DAY,
    CONF_LIGHT_SCENE_EVENING,
    CONF_LIGHT_SCENE_SLEEP,
    CONF_LIGHTS,
    CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY,
    CONF_LIGHTS_ON_ENTRY,
    CONF_LIGHTS_ON_ENTRY_DARK_ONLY,
    CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
    CONF_NIGHT_LIGHT_DAY_COLOR,
    CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS,
    CONF_NIGHT_LIGHT_EVENING_COLOR,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHT_SLEEP_COLOR,
    CONF_NIGHT_LIGHTS,
    DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_DAY_COLOR,
    DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    DEFAULT_NIGHT_LIGHT_SLEEP_COLOR,
    LIGHT_CAPABILITY_BASIC,
    LIGHT_CAPABILITY_BRIGHTNESS,
    LIGHT_CAPABILITY_FULL,
    LIGHT_SLOT_DAY,
    LIGHT_SLOT_EVENING,
    LIGHT_SLOT_SLEEP,
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
    night_lights_by_day: bool | None = None,
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

    # NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3, R3-H1): the by-day "stop"
    # — when the room is explicitly BRIGHT (``is_dark is False``) AND
    # the operator did not opt in to by-day night lights, drop night-
    # light members from the main entry turn-on set. Night lights are
    # then driven ONLY by the dedicated night-light sub-branch (which
    # here returns no opinion). Membership in CONF_NIGHT_LIGHTS wins
    # over an explicit CONF_LIGHTS_ON_ENTRY: the picker cannot force a
    # night light on by day — the by-day boolean does.
    #
    # ``is_dark is None`` (caller did not evaluate darkness, e.g. the
    # equivalence tests and the sleep-only path) preserves the pre-
    # cycle union — callers that WANT the by-day strip must supply the
    # bool. Runtime callers always supply bool (True / False) via
    # ``automation.is_dark(illuminance)``.
    if (
        night
        and is_dark is False
        and not bool(night_lights_by_day)
    ):
        night_set = set(night)
        base = [e for e in base if e not in night_set]

    return _dedup_preserving_order(base)


def night_light_turn_on_params(
    cfg: dict,
    mode: str,
    *,
    include_transition: bool = False,
) -> dict:
    """Build the turn-on service params for a night light in ``mode``.

    Shared by canonical ``_turn_on_night_lights`` and the reconciler
    ``_resolve_light`` night-light sub-rule so both controllers assert
    identical brightness / colour (R3-M2).

    ``mode`` is one of ``"sleep"``, ``"day"``, ``"evening"``. Evening
    overrides fall back to day defaults when the operator did not set
    them. Only brightness is included when capability is
    BRIGHTNESS-only; color_temp_kelvin is added for FULL.
    """
    if mode == "sleep":
        brightness = cfg.get(
            CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
            DEFAULT_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
        )
        color_temp = cfg.get(
            CONF_NIGHT_LIGHT_SLEEP_COLOR,
            DEFAULT_NIGHT_LIGHT_SLEEP_COLOR,
        )
    elif mode == "evening":
        ov = slot_night_light_overrides(cfg, LIGHT_SLOT_EVENING)
        brightness = ov.get(
            "brightness",
            cfg.get(
                CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
                DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
            ),
        )
        color_temp = ov.get(
            "color",
            cfg.get(
                CONF_NIGHT_LIGHT_DAY_COLOR,
                DEFAULT_NIGHT_LIGHT_DAY_COLOR,
            ),
        )
    else:  # "day"
        brightness = cfg.get(
            CONF_NIGHT_LIGHT_DAY_BRIGHTNESS,
            DEFAULT_NIGHT_LIGHT_DAY_BRIGHTNESS,
        )
        color_temp = cfg.get(
            CONF_NIGHT_LIGHT_DAY_COLOR,
            DEFAULT_NIGHT_LIGHT_DAY_COLOR,
        )

    out: dict = {}
    # Review fix (R3-M2): default to BASIC so canonical and reconciler
    # agree when CONF_LIGHT_CAPABILITIES is unset. BASIC adds no params.
    capability = cfg.get(CONF_LIGHT_CAPABILITIES, LIGHT_CAPABILITY_BASIC)
    if capability in (LIGHT_CAPABILITY_BRIGHTNESS, LIGHT_CAPABILITY_FULL):
        out["brightness_pct"] = brightness
    if capability == LIGHT_CAPABILITY_FULL:
        out["color_temp_kelvin"] = color_temp
    if include_transition:
        from ..const import CONF_LIGHT_TRANSITION_ON
        out["transition"] = cfg.get(CONF_LIGHT_TRANSITION_ON, 1)
    return out


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


# ---------------------------------------------------------------------------
# Slice E (v5.103.29) — time-of-day slots (Day / Evening / Sleep).
#
# Slot boundaries reuse existing URA time notions — no new timers, no clock
# reads inside this module. The caller supplies ``is_sleep_hours`` (from
# ``RoomAutomation.is_sleep_mode_active()``) and ``is_dark`` (from
# ``RoomAutomation.is_dark()``), both already injectable in tests.
# ---------------------------------------------------------------------------

_SCENE_KEY_BY_SLOT = {
    LIGHT_SLOT_DAY: CONF_LIGHT_SCENE_DAY,
    LIGHT_SLOT_EVENING: CONF_LIGHT_SCENE_EVENING,
    LIGHT_SLOT_SLEEP: CONF_LIGHT_SCENE_SLEEP,
}


def resolve_slot(is_sleep_hours: bool, is_dark: bool | None) -> str:
    """Return the current time-of-day slot for this room.

    * ``sleep``   — ``is_sleep_hours`` True (Slice D precedence: per-room
      sleep clock OR HouseState=="sleep").
    * ``evening`` — not sleep AND ``is_dark is True`` (dark but awake).
    * ``day``     — otherwise (sun up, or is_dark unknown / False).
    """
    if is_sleep_hours:
        return LIGHT_SLOT_SLEEP
    if is_dark is True:
        return LIGHT_SLOT_EVENING
    return LIGHT_SLOT_DAY


def slot_scene(cfg: dict, slot: str) -> str | None:
    """Return the operator-configured scene entity_id for this slot, or None.

    Absent / empty ⇒ None (per-light brightness/colour path is used).
    """
    key = _SCENE_KEY_BY_SLOT.get(slot)
    if not key:
        return None
    value = cfg.get(key)
    if not value or not isinstance(value, str):
        return None
    return value


def slot_regular_light_overrides(cfg: dict, slot: str) -> dict:
    """Return ``{brightness_pct?, color_kelvin?}`` overrides for regular lights.

    Only the Evening slot has NEW keys in Slice E. Absent evening keys ⇒
    empty dict, so the caller keeps today's ``CONF_LIGHT_BRIGHTNESS_PCT``
    default and adds no color. Day and Sleep return ``{}`` unconditionally
    (today's behaviour — regular lights have no per-slot settings).
    """
    if slot != LIGHT_SLOT_EVENING:
        return {}
    out: dict = {}
    b = cfg.get(CONF_LIGHT_EVENING_BRIGHTNESS_PCT)
    if b is not None:
        try:
            out["brightness_pct"] = int(b)
        except (TypeError, ValueError):
            pass
    c = cfg.get(CONF_LIGHT_EVENING_COLOR_KELVIN)
    if c is not None:
        try:
            out["color_kelvin"] = int(c)
        except (TypeError, ValueError):
            pass
    return out


def slot_night_light_overrides(cfg: dict, slot: str) -> dict:
    """Return ``{brightness?, color?}`` overrides for night lights.

    Only the Evening slot has NEW keys. Day / Sleep return ``{}`` and the
    caller uses today's ``CONF_NIGHT_LIGHT_DAY_*`` / ``_SLEEP_*`` defaults
    (byte-identical to pre-Slice-E behaviour).
    """
    if slot != LIGHT_SLOT_EVENING:
        return {}
    out: dict = {}
    b = cfg.get(CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS)
    if b is not None:
        try:
            out["brightness"] = int(b)
        except (TypeError, ValueError):
            pass
    c = cfg.get(CONF_NIGHT_LIGHT_EVENING_COLOR)
    if c is not None:
        try:
            out["color"] = int(c)
        except (TypeError, ValueError):
            pass
    return out
