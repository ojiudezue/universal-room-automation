"""Shared "independent ARRIVAL edge" helpers (LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1).

Extracted from the v5.107.0 PERIMETER-FP D10.5 face+non-face rule
(``perimeter_alert._nonface_agrees`` / ``_on_person_arrival_event`` /
``_area_of_entity``) so the SC lock regime applies the SAME arrival-edge rule
to ``camera_face`` arrivals instead of a second hand-rolled copy.

An arrival edge for a person is either:
  * person tracker: a LIVE ``not_home -> home`` edge of ``person.<slug>``
    (``old_state`` None = HA restore, never an arrival; ``unavailable`` /
    ``unknown`` / named zone -> home never count); or
  * Bermuda: PersonCoordinator moved the person (``previous_location !=
    location``) INTO one of a caller-supplied set of areas.
Both ignore transitions before ``boot_end`` (HA restore stamps
``last_changed`` at boot) and count only within ``window_s`` of ``at_ts``.

Pure except ``area_slug_of_entity`` (lazy HA registry imports). The window
and boot-exclusion VALUES stay with each caller (they read their own rung-1
constants), so a caller's knob is never moved by another caller.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

from .perimeter_fp_gates import zone_slug

SOURCE_PERSON_TRACKER = "person_tracker"
SOURCE_BLE = "ble"


def live_arrival_slug(event_data: Mapping[str, Any]) -> str | None:
    """Slug of a LIVE ``not_home -> home`` person edge, else None."""
    new = event_data.get("new_state")
    old = event_data.get("old_state")
    if new is None or old is None:
        return None
    if getattr(new, "state", None) != "home" or getattr(old, "state", None) != "not_home":
        return None
    slug = str(event_data.get("entity_id", "")).replace("person.", "").lower()
    return slug or None


def edge_in_window(ts: float | None, at_ts: float, window_s: float, boot_end: float) -> bool:
    """An edge at ``ts`` counts: after the boot exclusion, within the window."""
    return ts is not None and ts >= boot_end and abs(at_ts - ts) <= window_s


def bermuda_arrival_into(
    pc_data: Mapping[str, Any],
    slug: str,
    areas: set[str],
    at_ts: float,
    window_s: float,
    boot_end: float,
) -> bool:
    """PersonCoordinator moved ``slug`` INTO one of ``areas`` in the window."""
    for name, rec in pc_data.items():
        if str(name).lower().replace(" ", "_") != slug or not isinstance(rec, dict):
            continue
        if rec.get("method") != "bermuda" or not areas:
            continue
        here = {zone_slug(rec.get("location")), zone_slug(rec.get("bermuda_area"))}
        moved = zone_slug(rec.get("previous_location")) != zone_slug(rec.get("location"))
        lc = rec.get("last_changed")
        lc_ts = lc.timestamp() if isinstance(lc, datetime) else None
        if moved and (here & areas) and edge_in_window(lc_ts, at_ts, window_s, boot_end):
            return True
    return False


# Review A MED-1 (v5.107.4): PersonCoordinator overwrites previous_location on
# every tick, so a Bermuda move is visible in its data for ONE update (~30 s).
# A stamp ring, fed from a PersonCoordinator listener, keeps each move for the
# whole window on either side of a face. Bounded per person (rung 1).
BERMUDA_MOVE_STAMPS_PER_PERSON = 8


def record_bermuda_moves(
    pc_data: Mapping[str, Any],
    stamps: dict[str, list[tuple[frozenset[str], float]]],
) -> set[str]:
    """Stamp every Bermuda room MOVE visible in ``pc_data`` as
    (areas it moved into, last_changed ts). Same move test as
    ``bermuda_arrival_into``. A move already stamped (same ts) is not
    re-added. Returns the slugs that got a NEW stamp."""
    fresh: set[str] = set()
    for name, rec in pc_data.items():
        if not isinstance(rec, dict) or rec.get("method") != "bermuda":
            continue
        if zone_slug(rec.get("previous_location")) == zone_slug(rec.get("location")):
            continue
        lc = rec.get("last_changed")
        if not isinstance(lc, datetime):
            continue
        ts = lc.timestamp()
        slug = str(name).lower().replace(" ", "_")
        ring = stamps.setdefault(slug, [])
        if any(t == ts for _a, t in ring):
            continue
        here = frozenset(
            {zone_slug(rec.get("location")), zone_slug(rec.get("bermuda_area"))} - {""})
        ring.append((here, ts))
        del ring[:-BERMUDA_MOVE_STAMPS_PER_PERSON]
        fresh.add(slug)
    return fresh


def stamped_bermuda_arrival(
    stamps: Mapping[str, list[tuple[frozenset[str], float]]],
    slug: str,
    areas: set[str],
    at_ts: float,
    window_s: float,
    boot_end: float,
) -> bool:
    """A stamped move of ``slug`` INTO ``areas`` within the window (either
    side of ``at_ts``) and after the boot exclusion."""
    if not areas:
        return False
    return any(
        (here & areas) and edge_in_window(ts, at_ts, window_s, boot_end)
        for here, ts in stamps.get(slug, ())
    )


def nonface_arrival_source(
    *,
    slug: str,
    at_ts: float,
    window_s: float,
    boot_end: float,
    tracker_arrivals: Mapping[str, float],
    pc_data_fn: Callable[[], Mapping[str, Any] | None],
    areas_fn: Callable[[], set[str]],
    bermuda_moves: Mapping[str, list[tuple[frozenset[str], float]]] | None = None,
) -> str | None:
    """Source name of an independent arrival edge for ``slug``, or None.

    ``window_s <= 0`` disables (None). The tracker leg is checked first;
    the Bermuda leg's inputs are resolved lazily and any error there means
    "no Bermuda arrival" (fail-closed: no corroboration). ``bermuda_moves``
    (stamp ring, optional): also accept a stamped move; None = the live
    PersonCoordinator data only (perimeter D10.5, unchanged).
    """
    if window_s <= 0:
        return None
    if edge_in_window(tracker_arrivals.get(slug), at_ts, window_s, boot_end):
        return SOURCE_PERSON_TRACKER
    try:
        areas = areas_fn()
        if bermuda_moves is not None and stamped_bermuda_arrival(
                bermuda_moves, slug, areas, at_ts, window_s, boot_end):
            return SOURCE_BLE
        data = pc_data_fn() or {}
        if bermuda_arrival_into(data, slug, areas, at_ts, window_s, boot_end):
            return SOURCE_BLE
    except Exception:  # noqa: BLE001
        pass
    return None


def area_slug_of_entity(hass: Any, entity_id: str) -> str:
    """HA area name (slugged) of an entity via entity/device registry."""
    try:
        from homeassistant.helpers import (  # noqa: PLC0415
            area_registry as ar, device_registry as dr, entity_registry as er,
        )
        ent = er.async_get(hass).async_get(entity_id)
        area_id = getattr(ent, "area_id", None)
        if not area_id and getattr(ent, "device_id", None):
            dev = dr.async_get(hass).async_get(ent.device_id)
            area_id = getattr(dev, "area_id", None)
        if not area_id:
            return ""
        area = ar.async_get(hass).async_get_area(area_id)
        return zone_slug(getattr(area, "name", None) or area_id)
    except Exception:  # noqa: BLE001
        return ""


def door_entry_areas(egress_tracker: Any, area_of: Callable[[str], str]) -> set[str]:
    """Areas where a person ARRIVES at the house: every egress camera's own
    area plus the areas of the explicitly configured door-interior
    neighbours (CONF_DOOR_INTERIOR_NEIGHBOURS). ``egress_tracker`` is the
    EgressDirectionTracker (hass.data[DOMAIN]["egress_tracker"]), NOT the
    TransitValidator (LOCK-ENTRY-AREAS-WRONG-OBJECT-1). No tracker or no
    egress config -> empty set (the Bermuda leg then never corroborates)."""
    out: set[str] = set()
    if egress_tracker is None:
        return out
    ents = list(getattr(egress_tracker, "_egress_entities", None) or [])
    nb = getattr(egress_tracker, "_interior_neighbours_by_group", None) or {}
    for cams in nb.values():
        ents.extend(cams or [])
    for e in ents:
        a = area_of(str(e))
        if a:
            out.add(a)
    out.discard("")
    return out
