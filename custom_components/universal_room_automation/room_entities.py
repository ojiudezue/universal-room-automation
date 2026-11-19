"""Resolve a room's own URA entity through the entity registry.

ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 (plan
``docs/planning/PLANNING_room_occupied_registry_resolve.md`` rev 3).

Every URA room entity is registered under unique_id
``f"{entry_id}_{key}"`` (``entity.py`` ``UniversalRoomEntity``). Its
entity_id is assigned by HA from the device name plus the entity name, so it
can NOT be derived from the room name (double prefix on new rooms, operator
renames: Foyer -> ``binary_sensor.foyer_foyer_occupied``, Media ->
``binary_sensor.media_room_occupied``). Readers ask here instead of
formatting ``f"binary_sensor.{slug}_occupied"``.

INV-RE: a reader gets exactly
``entity_registry.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{key}")``
or None. A miss returns None (the reader's existing unavailable path) and is
COUNTED; it never yields a built id. No cache: the registry is a dict and
follows renames.

Two counters, both process-lifetime:
- ``room_entity_resolve_misses``: registry misses (and ambiguous slug maps).
  Steady state 0. A miss that happens after the boot window pages once per
  local day through ``fire_stuck_signal`` (kind ``room_entity_unresolved``).
- ``room_entity_name_fallback_reads``: the logged, counted last-resort
  name-built reads kept by rule "only proven code should supersede correct
  code" (fan_veto, the room-switch resolver, the override switch helper, NM
  co2/tvoc). Never pages.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .const import (
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    RESIDENT_RETURN_BOOT_WINDOW_S,
)

_LOGGER = logging.getLogger(__name__)

# Trip-wire kind for fire_stuck_signal.
ROOM_ENTITY_UNRESOLVED_KIND = "room_entity_unresolved"

# (entry_id or name or "slug_ambiguous:<slug>", key) -> count
room_entity_resolve_misses: dict[tuple[str, str], int] = {}
# (entry_id or name, key) -> count
room_entity_name_fallback_reads: dict[tuple[str, str], int] = {}

# Consecutive misses per (entry_id, key): WARN once, on the second
# consecutive miss (first-refresh race rule of coordinator.py
# _resolve_room_switch_entity_id).
_consecutive_misses: dict[tuple[str, str], int] = {}

# Boot reference: monotonic time of the first resolver call in this
# process (the integration's first refresh). Misses inside
# RESIDENT_RETURN_BOOT_WINDOW_S of it never page.
_first_call_monotonic: float | None = None
# Local date (ISO) of the last page, so a persistent miss does not create
# a task per tick (fire_stuck_signal latches per day too).
_last_page_day: str | None = None


def reset_counters() -> None:
    """Clear every counter and latch (tests, diagnostics)."""
    global _first_call_monotonic, _last_page_day
    room_entity_resolve_misses.clear()
    room_entity_name_fallback_reads.clear()
    _consecutive_misses.clear()
    _first_call_monotonic = None
    _last_page_day = None


def _registry(hass: Any) -> Any:
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    return er.async_get(hass)


def _note_first_call() -> None:
    global _first_call_monotonic
    if _first_call_monotonic is None:
        _first_call_monotonic = time.monotonic()


def _local_day() -> str:
    try:
        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        return dt_util.now().date().isoformat()
    except Exception:  # noqa: BLE001
        return time.strftime("%Y-%m-%d")


def _maybe_page(hass: Any, miss_key: tuple[str, str]) -> None:
    global _last_page_day
    if _first_call_monotonic is None:
        return
    if time.monotonic() - _first_call_monotonic < RESIDENT_RETURN_BOOT_WINDOW_S:
        return
    day = _local_day()
    if _last_page_day == day:
        return
    _last_page_day = day
    try:
        total = sum(room_entity_resolve_misses.values())
        diagnosis = (
            f"{total} room entity lookups missed the entity registry "
            f"(first: {miss_key[0]} / {miss_key[1]}). A URA room "
            "reader is blind for that room until the entity exists."
        )
        hass.async_create_task(_page_once(hass, day, diagnosis))
    except Exception:  # noqa: BLE001 — a trip-wire never breaks a reader
        _LOGGER.debug("room_entities: trip-wire dispatch failed", exc_info=True)


# Persisted page latch (review B-LOW): the RAM latch above resets on every
# restart, so a restart storm on one day would page again each boot. The
# day of the last page is kept in a tiny HA Store (same pattern as
# music_following's volume store) and checked before paging.
PAGE_LATCH_STORE_KEY = f"{DOMAIN}.room_entity_page_latch"


def _store(hass: Any) -> Any:
    from homeassistant.helpers.storage import Store  # noqa: PLC0415

    return Store(hass, 1, PAGE_LATCH_STORE_KEY)


async def _page_once(hass: Any, day: str, diagnosis: str) -> bool:
    """Send the trip-wire NM unless one was already sent on ``day``
    (persisted across restarts). Returns True when it paged."""
    try:
        store = _store(hass)
        data = await store.async_load() or {}
        if data.get("day") == day:
            return False
        await store.async_save({"day": day})
    except Exception:  # noqa: BLE001 — storage failure falls back to RAM latch
        _LOGGER.debug("room_entities: page latch store failed", exc_info=True)
    from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
        fire_stuck_signal,
    )

    await fire_stuck_signal(
        hass,
        ROOM_ENTITY_UNRESOLVED_KIND,
        ("total",),
        diagnosis,
        remedy="Reload the room entry, or check the entity registry.",
        severity="HIGH",
    )
    return True


def _count_miss(hass: Any, miss_key: tuple[str, str]) -> None:
    room_entity_resolve_misses[miss_key] = (
        room_entity_resolve_misses.get(miss_key, 0) + 1
    )
    n = _consecutive_misses.get(miss_key, 0) + 1
    _consecutive_misses[miss_key] = n
    if n == 2:
        _LOGGER.warning(
            "room_entity_resolve: no registry entity for %s / %s "
            "(unique_id %s_%s); reader treats it as unavailable",
            miss_key[0], miss_key[1], miss_key[0], miss_key[1],
        )
    _maybe_page(hass, miss_key)


def note_name_fallback_read(owner: str, key: str, entity_id: str) -> None:
    """Count + DEBUG-log one name-built last-resort read (never pages)."""
    k = (str(owner), str(key))
    room_entity_name_fallback_reads[k] = (
        room_entity_name_fallback_reads.get(k, 0) + 1
    )
    _LOGGER.debug(
        "room_entities: name-built fallback read %s for %s / %s",
        entity_id, owner, key,
    )


def resolve_room_entity_id(
    hass: Any, entry_id: str | None, domain: str, key: str,
) -> str | None:
    """Return the registry entity_id of room ``entry_id``'s ``key``, or None.

    One registry lookup by unique_id ``f"{entry_id}_{key}"``. Never raises,
    never builds an id. A miss (incl. no ``entry_id``) is counted.
    """
    _note_first_call()
    miss_key = (str(entry_id or ""), str(key))
    if not entry_id:
        _count_miss(hass, miss_key)
        return None
    try:
        resolved = _registry(hass).async_get_entity_id(
            domain, DOMAIN, f"{entry_id}_{key}",
        )
    except Exception:  # noqa: BLE001 — registry hiccup reads as a miss
        resolved = None
    if isinstance(resolved, str) and resolved:
        _consecutive_misses.pop(miss_key, None)
        return resolved
    _count_miss(hass, miss_key)
    return None


def _room_entries(hass: Any) -> list[Any]:
    try:
        return [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if (e.data or {}).get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        ]
    except Exception:  # noqa: BLE001
        return []


def _room_name_of(entry: Any) -> str:
    merged = {**(entry.data or {}), **(entry.options or {})}
    return str(merged.get(CONF_ROOM_NAME) or "")


def room_entry_id_for_name(hass: Any, room_name: str) -> str | None:
    """Entry id of the room whose merged data+options room_name == ``room_name``.

    Exact match only; ``title`` is never matched. None when no room matches.
    Not counted here: the caller's resolve (or fallback) counts.
    """
    if not room_name:
        return None
    for entry in _room_entries(hass):
        if _room_name_of(entry) == room_name:
            return entry.entry_id
    return None


def room_entry_id_for_slug(hass: Any, slug: str) -> str | None:
    """Entry id of the room whose ``memory_facade._slugify(room_name)`` == slug.

    Tie rule: two or more rooms slugging alike -> None and one counted miss
    keyed ``("slug_ambiguous:<slug>", "*")``; never the first match.
    """
    return _entry_for_slug(hass, slug)[0]


def _entry_for_slug(hass: Any, slug: str) -> tuple[str | None, bool]:
    """(entry_id, handled). handled=True when a tie was counted."""
    if not slug:
        return None, False
    from .memory_facade import _slugify  # noqa: PLC0415

    matches = [
        e.entry_id for e in _room_entries(hass)
        if _slugify(_room_name_of(e)) == slug
    ]
    if len(matches) == 1:
        return matches[0], False
    if len(matches) > 1:
        _note_first_call()
        _count_miss(hass, (f"slug_ambiguous:{slug}", "*"))
        return None, True
    return None, False


def resolve_room_entity_id_for_slug(
    hass: Any, slug: str, domain: str, key: str,
) -> str | None:
    """Memory node slug -> entry -> registry id (R3/R4). None on any miss."""
    entry_id, tie_counted = _entry_for_slug(hass, slug)
    if entry_id is None:
        if not tie_counted:
            _note_first_call()
            _count_miss(hass, (f"slug:{slug}", str(key)))
        return None
    return resolve_room_entity_id(hass, entry_id, domain, key)


def misses_summary(top: int = 5) -> dict[str, Any]:
    """Display shape for the house-status health block."""
    items = sorted(
        room_entity_resolve_misses.items(), key=lambda kv: kv[1], reverse=True,
    )
    return {
        "room_entity_resolve_misses": sum(room_entity_resolve_misses.values()),
        "room_entity_resolve_misses_top": [
            f"{k[0]}/{k[1]}={v}" for k, v in items[:top]
        ],
        "room_entity_name_fallback_reads": sum(
            room_entity_name_fallback_reads.values()
        ),
    }
