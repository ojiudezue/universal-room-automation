"""Interior vision core (VISION-INTERIOR-SIGHTINGS-1; plan
``docs/planning/PLANNING_vision_interior_sightings.md`` §6.1, §7, §9.D1, §9.D5).

HA-free and pure: record arithmetic, member liveness classes, the one
placement per resident slug, and the cumulative path windows of the
time-lapse. The ONE F4 unnamed ingest and every store live on
``person_sighting.PersonSightingProducer`` (``_emit_unnamed``); this module
returns plain field mappings and never constructs a record type, writes a
store or sends a channel (layer guard R7 / R6).

Ship 1 builds no model call (``InteriorVisionSampler`` arrives with the
vision ships). Nothing here names a person from an image: ``named`` is only
the BLE residents and the named interior face sightings handed in.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Mapping

# Member liveness classes (plan §7).
LIVE = "live"
HELD = "held"
RELEASED = "released"
NO_READING = "no_reading"
LOST = "lost"
# Streaming, but its count is stuck: the census watchdog discounts it
# (review D-M3). Never LIVE, so its reading never reaches a record.
STUCK = "stuck"
# Order used to report a group with no LIVE member (most informative first).
_NOT_LIVE_ORDER = (HELD, RELEASED, STUCK, NO_READING)

# Record statuses, in precedence order (plan §9.D1).
STATUS_MISSING = "missing"
STATUS_UNNAMED_PRESENT = "unnamed_present"
STATUS_CONFIRMED = "confirmed"
STATUS_BLE_UNCONFIRMED = "ble_unconfirmed"
STATUS_EMPTY = "empty"

PROVENANCE_NVR = "nvr"
PROVENANCE_VISION = "vision"
PROVENANCE_AGREE = "agree"

NAMED_SOURCE_BLE = "ble"
NAMED_SOURCE_FACE = "face"

_UNREADY = frozenset({"unavailable", "unknown"})


def member_liveness(view: str | None, state_value: str | None, *, stuck: bool = False) -> str:
    """One member entity's class this tick (plan §7). ``view`` is the ship 3b
    ``entity_stream_view(hass, eid, census=True)`` answer; ``state_value`` the
    entity's HA state (None = no state); ``stuck`` = the census discounts the
    entity this tick (``area_evidence()["discounted"]``). LIVE needs no view,
    not stuck, AND a real state."""
    if view == HELD:
        return HELD
    if view == RELEASED:
        return RELEASED
    if stuck:
        return STUCK
    if state_value is None or state_value in _UNREADY:
        return NO_READING
    return LIVE


def group_bodies_nvr(
    members: Iterable[str], liveness: Mapping[str, str],
    by_entity: Mapping[str, Any],
) -> int | None:
    """Max over LIVE members of that member's own last reading (plan §7).
    A held / released / no-reading member is never read (its frozen value
    never reaches a record). None = no LIVE member with a reading."""
    best: int | None = None
    for eid in members:
        if liveness.get(eid) != LIVE:
            continue
        raw = by_entity.get(eid)
        if raw is None:
            continue
        try:
            val = max(0, int(raw))
        except (TypeError, ValueError):
            continue
        best = val if best is None else max(best, val)
    return best


def group_liveness(
    members: Iterable[str], liveness: Mapping[str, str], physical_dead: bool | None,
    has_reading: bool,
) -> str:
    """The record's ``liveness`` field: ``live`` when a LIVE member carries a
    reading, else ``lost`` when every paired NVR lost the camera (ship 3b
    ``physical_camera_dead``), else the most informative member class."""
    if has_reading:
        return LIVE
    if physical_dead is True:
        return LOST
    classes = {liveness.get(eid, NO_READING) for eid in members}
    for cls in _NOT_LIVE_ORDER:
        if cls in classes:
            return cls
    return NO_READING


def place_named(
    ble_rooms: Mapping[str, str],
    face_rooms: Iterable[tuple[str, str, float]],
    now: float, fresh_s: float,
) -> dict[str, tuple[str, str]]:
    """ONE placement per resident slug (plan §9.D4 (e), closure N5): the BLE
    ACTIVE room when BLE places the slug anywhere, else the room of its
    NEWEST interior face sighting younger than ``fresh_s``. Returns
    ``{slug: (room, source)}``. ``ble_rooms`` = ``{slug: room}``;
    ``face_rooms`` = ``(slug, room, ts)``."""
    out: dict[str, tuple[str, str]] = {
        slug: (room, NAMED_SOURCE_BLE) for slug, room in ble_rooms.items() if slug and room
    }
    newest: dict[str, tuple[float, str]] = {}
    for slug, room, ts in face_rooms:
        if not slug or not room or slug in out:
            continue
        try:
            age = float(now) - float(ts)
        except (TypeError, ValueError):
            continue
        if age > float(fresh_s) or age < -1.0:
            continue
        prev = newest.get(slug)
        if prev is None or float(ts) > prev[0]:
            newest[slug] = (float(ts), room)
    for slug, (_ts, room) in newest.items():
        out[slug] = (room, NAMED_SOURCE_FACE)
    return out


def build_room_records(
    groups: Iterable[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    liveness: Mapping[str, str],
    named_by_room: Mapping[str, Mapping[str, str]],
    vision: Mapping[str, int],
    now: float,
) -> tuple[dict[str, Any], ...]:
    """One field mapping per covered group (plan §9.D1). The producer turns
    each into a frozen ``RoomSighting`` inside ``_emit_unnamed`` (the record
    owner). ``groups``: mappings with ``group_key``, ``room``, ``area_id``,
    ``members``, ``physical_dead`` and optional ``entered_via``.
    ``evidence``: ``PersonCensus.area_evidence()`` (``by_entity`` read only).
    ``named_by_room``: ``{room: {slug: source}}`` from ``place_named``.
    ``vision``: ``{group_key: people}`` of VALID vision counts (empty in ship
    1); a vision count replaces, never adds to, the NVR count."""
    by_entity = (evidence or {}).get("by_entity") or {}
    census_as_of = (evidence or {}).get("as_of")
    out: list[dict[str, Any]] = []
    for g in groups:
        key = g["group_key"]
        members = tuple(g.get("members") or ())
        nvr = group_bodies_nvr(members, liveness, by_entity)
        live = group_liveness(members, liveness, g.get("physical_dead"), nvr is not None)
        vis = vision.get(key) if nvr is not None else None
        if nvr is None:
            bodies, source, provenance = None, None, None
        elif vis is not None:
            bodies = int(vis)
            source = PROVENANCE_VISION
            provenance = PROVENANCE_AGREE if int(vis) == nvr else PROVENANCE_VISION
        else:
            bodies, source, provenance = nvr, PROVENANCE_NVR, PROVENANCE_NVR
        named_map = dict(named_by_room.get(g.get("room"), {}) or {})
        named = tuple(sorted(named_map))
        named_sources = tuple(sorted(named_map.items()))
        unnamed = None if bodies is None else max(0, bodies - len(named))
        if bodies is None:
            status = STATUS_MISSING
        elif unnamed >= 1:
            status = STATUS_UNNAMED_PRESENT
        elif bodies >= 1:
            status = STATUS_CONFIRMED
        elif any(src == NAMED_SOURCE_BLE for src in named_map.values()):
            status = STATUS_BLE_UNCONFIRMED
        else:
            status = STATUS_EMPTY
        out.append({
            "room": g.get("room"), "area_id": g.get("area_id"), "group_key": key,
            "bodies": bodies, "bodies_nvr": nvr,
            "bodies_vision": None if vis is None else int(vis),
            "bodies_source": source, "named": named, "named_sources": named_sources,
            "unnamed": unnamed, "status": status, "provenance": provenance,
            "liveness": live, "entered_via": g.get("entered_via"),
            "census_as_of": census_as_of, "as_of": float(now),
        })
    return tuple(out)


def chain_windows(
    edges: Iterable[Any], root: str, entry_ts: float,
    first_on: Mapping[str, Iterable[float]], max_hops: int,
) -> dict[str, dict[str, Any]]:
    """Cumulative path windows from the door (plan §9.D5, closure N6).

    ``edges``: inward ``interior_paths.PathEdge`` (``from_key``, ``to_key``,
    ``window_s``). The window of node v over edge (u -> v) opens at ``t_u``
    and closes at ``t_u + window_s``; ``t_u`` = u's first on-edge inside its
    own window (the door: ``entry_ts``), else u's cumulative bound (the
    window close), so the chain continues past a camera that missed the
    entrant. Breadth-first to ``max_hops``; a node reached by several parents
    at the same depth takes the union of their windows. ``first_on``: node key
    -> on-edge timestamps. Returns ``{node: {open, close, depth, first_on}}``
    (the door excluded)."""
    adj: dict[str, list[Any]] = {}
    for e in edges:
        adj.setdefault(e.from_key, []).append(e)
    out: dict[str, dict[str, Any]] = {}
    t_of: dict[str, float] = {root: float(entry_ts)}
    frontier = [root]
    depth = 0
    while frontier and depth < max(0, int(max_hops)):
        depth += 1
        nxt: dict[str, dict[str, Any]] = {}
        for u in frontier:
            for e in adj.get(u, ()):
                v = e.to_key
                if v == root or v in out:
                    continue
                lo = t_of[u]
                hi = t_of[u] + float(e.window_s)
                cur = nxt.get(v)
                if cur is None:
                    nxt[v] = {"open": lo, "close": hi, "depth": depth}
                else:
                    cur["open"] = min(cur["open"], lo)
                    cur["close"] = max(cur["close"], hi)
        for v, w in nxt.items():
            seen = sorted(t for t in (first_on.get(v) or ()) if w["open"] <= t <= w["close"])
            w["first_on"] = seen[0] if seen else None
            t_of[v] = seen[0] if seen else w["close"]
            out[v] = w
        frontier = sorted(nxt)
    return out


class OnEdgeRing:
    """Bounded ring of ``(ts, group_key)`` person-sensor on-edges (D1
    listener, read by D5). O(1) append."""

    def __init__(self, maxlen: int) -> None:
        self._ring: deque = deque(maxlen=max(1, int(maxlen)))

    def append(self, ts: float, group_key: str) -> None:
        self._ring.append((float(ts), group_key))

    def by_group_since(self, t: float) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for ts, key in self._ring:
            if ts >= t:
                out.setdefault(key, []).append(ts)
        return out

    def __len__(self) -> int:
        return len(self._ring)
