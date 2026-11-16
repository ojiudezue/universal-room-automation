"""Interior vision core (VISION-INTERIOR-SIGHTINGS-1; plan
``docs/planning/PLANNING_vision_interior_sightings.md`` §6.1, §7, §9.D1, §9.D5).

HA-free and pure: record arithmetic, member liveness classes, the one
placement per resident slug, and the cumulative path windows of the
time-lapse. The ONE F4 unnamed ingest and every store live on
``person_sighting.PersonSightingProducer`` (``_emit_unnamed``); this module
returns plain field mappings and never constructs a record type, writes a
store or sends a channel (layer guard R7 / R6).

Ship 1 builds no model call. Ship 2 (§9.D3, describe on demand) adds the
pure describe helpers (schema, prompt, parse, name scrub, reply text, access
and budget rules), the frame-source interface (§8) and
``InteriorVisionSampler``, the layer member that makes the model calls and
hands every result to the producer through a callback (it owns no
person-awareness store and sends no channel). Nothing here names a person
from an image: ``named`` is only the BLE residents and the named interior
face sightings handed in, and every description string is scrubbed of the
tracked residents' names (INV-IV-NO-NAME).
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

_LOGGER = logging.getLogger(__name__)

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


# =====================================================================
# Ship 2 (plan §9.D3): describe on demand. Pure helpers first.
# =====================================================================
DESCRIBE_OK = "ok"
DESCRIBE_ERROR = "error"
DESCRIBE_TIMEOUT = "timeout"
DESCRIBE_UNPARSED = "unparsed"

# Budget refusal reasons (INV-IV-OFF); every one means no call.
SKIP_SWITCH_OFF = "switch_off"
SKIP_KILL = "kill"
SKIP_CAP = "cap_reached"
SKIP_COST_CAP = "cost_cap_reached"
SKIP_RESERVED = "reserved_for_describe"
SKIP_REHYDRATING = "rehydrating"
# Every model-call outcome writes one row; the restart rehydrate counts them.
CALL_OUTCOMES = (DESCRIBE_OK, DESCRIBE_ERROR, DESCRIBE_TIMEOUT, DESCRIBE_UNPARSED)
# Every staged still starts with this (the setup sweep deletes only these).
STAGE_PREFIX = "iv_"
PURPOSE_DESCRIBE = "describe"
PURPOSE_SAMPLING = "sampling"

_ACTIVITY = {
    "type": "object",
    "properties": {"what": {"type": "string"}, "where_in_room": {"type": "string"}},
    "required": ["what", "where_in_room"], "additionalProperties": False,
}
_AFFECT = {
    "type": "object",
    "properties": {"mood": {"type": "string"}, "energy": {"type": "string"}},
    "required": ["mood", "energy"], "additionalProperties": False,
}

# The D0(g) pilot prompt (scripts/grading/make_interior_pilot.py), which the
# operator graded 14/16 useful. It forbids names. `{views}` is empty for one
# image and explains the dewarped views otherwise (one person may show in
# both views: count each person once).
_DESCRIBE_PROMPT = (
    "This is one still frame from a camera inside a shared room of a house ({room}).{views} "
    "Describe what is happening right now. people: how many people are visible (0 if none). "
    "activities: one entry per thing being done, with what it is and where in the room. "
    "context: one short sentence about the scene.{affect} confidence: 0 to 1. Never name "
    "anyone or guess who they are; say 'a person', 'an adult' or 'a child'. Do not describe "
    "anything you cannot see. If no one is visible, people is 0 and activities{affect_empty} "
    "are empty."
)
_VIEWS_TEXT = (
    " The {n} images are flat views cut from ONE fisheye camera, so the same person can "
    "appear in more than one view: count each person once."
)
_AFFECT_TEXT = (
    " affect: for each visible person, their apparent mood and energy (observational only)."
)


def describe_structure(include_affect: bool) -> str:
    """The §9.D3 JSON schema (llmvision ``structure``), affect only when on."""
    props: dict[str, Any] = {
        "people": {"type": "integer", "minimum": 0},
        "activities": {"type": "array", "items": _ACTIVITY},
        "context": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    required = ["people", "activities", "context", "confidence"]
    if include_affect:
        props["affect"] = {"type": "array", "items": _AFFECT}
        required.append("affect")
    return json.dumps({"type": "object", "properties": props, "required": required,
                       "additionalProperties": False}, separators=(",", ":"))


def describe_prompt(room: str, n_views: int, include_affect: bool) -> str:
    return _DESCRIBE_PROMPT.format(
        room=room,
        views=_VIEWS_TEXT.format(n=int(n_views)) if int(n_views) > 1 else "",
        affect=_AFFECT_TEXT if include_affect else "",
        affect_empty=" and affect" if include_affect else "",
    )


def response_payload(result: Any) -> dict | None:
    """The model's JSON object from an llmvision service response
    (``structured_response`` for ``response_format: json``, else
    ``response_text``; also inside a REST ``service_response`` envelope).
    None = nothing parseable."""
    if not isinstance(result, Mapping):
        return None
    if isinstance(result.get("service_response"), Mapping):
        result = result["service_response"]
    for key in ("structured_response", "response_text"):
        val = result.get(key)
        if isinstance(val, Mapping):
            return dict(val)
        if isinstance(val, str) and val.strip():
            try:
                parsed = json.loads(val)
            except ValueError:
                continue
            if isinstance(parsed, Mapping):
                return dict(parsed)
    return None


def scrub_names(text: Any, names: Iterable[str]) -> tuple[str, int]:
    """Replace every tracked name (whole word, any case; ``_`` / space
    variants) with "a person". Returns (text, replacements)."""
    out = "" if text is None else str(text)
    total = 0
    for name in sorted({str(n).strip() for n in names if n and str(n).strip()},
                       key=len, reverse=True):
        variants = {name, name.replace("_", " "), name.replace(" ", "_")}
        for v in sorted(variants, key=len, reverse=True):
            pat = re.compile(r"(?<![\w])" + re.escape(v) + r"(?![\w])", re.IGNORECASE)
            out, n = pat.subn("a person", out)
            total += n
    return out, total


def parse_description(payload: Mapping[str, Any] | None, names: Iterable[str],
                      include_affect: bool) -> tuple[dict[str, Any] | None, int]:
    """Validated, name-scrubbed description fields, or (None, 0) when the
    payload is unusable. ``affect`` is () when not requested (never
    stored), else a tuple of (mood, energy)."""
    if not isinstance(payload, Mapping):
        return None, 0
    names = list(names)
    scrubbed = 0
    try:
        people = payload.get("people")
        people = None if people is None or isinstance(people, bool) else max(0, int(people))
    except (TypeError, ValueError):
        people = None
    acts: list[tuple[str, str]] = []
    for a in payload.get("activities") or ():
        if not isinstance(a, Mapping):
            continue
        what, n1 = scrub_names(a.get("what"), names)
        where, n2 = scrub_names(a.get("where_in_room"), names)
        scrubbed += n1 + n2
        if what:
            acts.append((what, where))
    context, n3 = scrub_names(payload.get("context"), names)
    scrubbed += n3
    try:
        conf = payload.get("confidence")
        conf = None if conf is None else min(1.0, max(0.0, float(conf)))
    except (TypeError, ValueError):
        conf = None
    affect: list[tuple[str, str]] = []
    if include_affect:
        for a in payload.get("affect") or ():
            if not isinstance(a, Mapping):
                continue
            mood, n4 = scrub_names(a.get("mood"), names)
            energy, n5 = scrub_names(a.get("energy"), names)
            scrubbed += n4 + n5
            affect.append((mood, energy))
    if people is None and not acts and not context:
        return None, scrubbed
    return {"people": people, "activities": tuple(acts), "context": context,
            "confidence": conf, "affect": tuple(affect)}, scrubbed


def format_description_reply(desc: Any, include_affect: bool, header: str = "") -> str:
    """The NM reply text for one description (closure N7: the ONE place a
    reply may carry affect, and only when ``include_affect``). ``desc`` is a
    ``RoomDescription`` or its field mapping."""
    get = desc.get if isinstance(desc, Mapping) else (lambda k, d=None: getattr(desc, k, d))
    room = get("room") or "the room"
    people = get("people")
    parts = [header.strip()] if header and header.strip() else []
    if people is None:
        parts.append(f"{room}: people unclear.")
    else:
        parts.append(f"{room}: {people} {'person' if people == 1 else 'people'}.")
    for what, where in get("activities") or ():
        parts.append(f"{what} ({where})." if where else f"{what}.")
    ctx = get("context")
    if ctx:
        parts.append(str(ctx).rstrip(".") + ".")
    if include_affect:
        aff = [f"{m}/{e}" for m, e in (get("affect") or ())]
        if aff:
            parts.append("Mood: " + ", ".join(aff) + ".")
    return " ".join(p for p in parts if p)


def describe_access(mode: str | None, requester: str | None,
                    operators: Iterable[str], residents: Iterable[str],
                    affect_enabled: bool) -> tuple[bool, bool]:
    """Q2 (plan §1a): (allowed, include_affect) for one NM requester. An
    unresolved requester is never allowed. Affect only for
    ``operator_affect`` with an operator asking (and the affect knob on)."""
    if not requester:
        return False, False
    ops = {o for o in operators if o}
    mode = mode or "operator"
    if mode in ("operator", "operator_affect"):
        allowed = requester in ops
    elif mode == "residents":
        allowed = requester in {r for r in residents if r}
    elif mode == "any_resolved":
        allowed = True
    else:
        allowed = requester in ops
    affect = bool(allowed and affect_enabled and mode == "operator_affect" and requester in ops)
    return allowed, affect


def budget_skip(*, switch_on: bool, kill: bool, cap: int, cost_cap: float,
                calls_today: int, cost_today: float, est_cost: float,
                reserved: int, purpose: str) -> str | None:
    """None when one more call is allowed, else the skip reason
    (INV-IV-OFF; closure N9 describe reserve)."""
    if not switch_on:
        return SKIP_SWITCH_OFF
    if kill:
        return SKIP_KILL
    if cap <= 0 or calls_today >= cap:
        return SKIP_CAP
    if cost_cap <= 0 or cost_today + est_cost > cost_cap + 1e-12:
        return SKIP_COST_CAP
    if purpose != PURPOSE_DESCRIBE and reserved > 0:
        share = cost_cap * min(1.0, reserved / cap)
        if calls_today >= cap - reserved or cost_today + est_cost > cost_cap - share + 1e-12:
            return SKIP_RESERVED
    return None


@dataclass(frozen=True)
class FrameSource:
    """Plan §8 frame-source interface: ``still`` (llmvision ``image_analyzer``
    over camera entities and/or URA-staged local files) or ``clip``
    (``video_analyzer`` on a Frigate event clip)."""

    kind: str
    group_key: str
    entities: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    video_file: str | None = None
    event_id: str | None = None


async def call_model(hass: Any, frame_source: FrameSource, prompt: str, structure: str, *,
                     model: str, max_tokens: int, target_width: int, timeout_s: float,
                     provider: str | None) -> dict[str, Any] | None:
    """The ONE llmvision route of interior vision (plan §8). Privacy flags
    (``store_in_timeline`` / ``use_memory`` False) are forced in the
    adapters; ``expose_images`` is always False here. None = no call
    (kill, nothing to send)."""
    from . import perimeter_enrichment as _pe  # noqa: PLC0415

    if frame_source.kind == "clip":
        return await _pe.analyze_crossing_frames(
            hass, frame_source.event_id, video_file=frame_source.video_file, model=model,
            max_frames=1, target_width=target_width, timeout_s=timeout_s,
            structure=structure, prompt=prompt, expose_images=False,
            provider=provider, max_tokens=max_tokens,
        )
    return await _pe.analyze_crossing_images(
        hass, image_entities=list(frame_source.entities), model=model,
        target_width=target_width, timeout_s=timeout_s, structure=structure,
        prompt=prompt, expose_images=False, provider=provider, max_tokens=max_tokens,
        image_files=list(frame_source.files),
    )


# =====================================================================
# InteriorVisionSampler: the layer member that makes the calls.
# =====================================================================
class InteriorVisionSampler:
    """Owned by ``PersonSightingProducer`` (plan §6.1). Holds the daily call
    and cost counters, the call tasks and the trip-wire state; hands each
    finished description to the producer through ``emit`` (the producer's
    one unnamed ingest). Every call re-reads the switch, the kill constant
    and both caps at call time (INV-IV-OFF). The counters are rehydrated at
    setup from today's ``interior_description`` rows (``async_rehydrate``,
    the crossing-vision P3-D5 pattern, ``CrossingVisionShadow._rehydrate_cap``),
    so a restart does not reset the daily budget."""

    def __init__(self, hass: Any, *, now_fn: Callable[[], float],
                 emit: Callable[[dict], Any], log_row: Callable[..., None],
                 fire: Callable[[str, str, str, str], None],
                 names_fn: Callable[[], list[str]],
                 provider_fn: Callable[[], str | None]) -> None:
        from . import const as _c  # noqa: PLC0415

        self.hass = hass
        self._now = now_fn
        self._emit = emit
        self._log_row = log_row
        self._fire = fire
        self._names = names_fn
        self._provider = provider_fn
        self.calls_today = 0
        self.cost_today = 0.0
        self._day: Any = None
        self.counters: Counter = Counter()
        self.skips: Counter = Counter()
        self.tasks: set = set()
        self.torn_down = False
        # Restart-durable budget: True from setup until today's rows are
        # counted (P3-D5 pattern); describe refuses meanwhile.
        self.cap_hold = False
        self.rehydrate_state = "not_started"
        self._triggers: deque = deque()
        self._calls: deque = deque()
        self._errors: deque = deque()
        self._latencies: deque = deque(maxlen=max(1, int(_c.INTERIOR_VISION_LATENCY_RING)))
        self._zero_latched = False
        self._errors_latched = False
        self._frames_left_latched = False

    # ------------------------------------------------------------- gates
    def _const(self) -> Any:
        from . import const as _c  # noqa: PLC0415

        return _c

    def _data(self) -> Mapping[str, Any]:
        try:
            d = self.hass.data.get(self._const().DOMAIN, {})
        except Exception:  # noqa: BLE001
            return {}
        return d if isinstance(d, Mapping) else {}

    def switch_on(self) -> bool:
        """``switch.ura_interior_vision``: the stored value the switch
        publishes, else its options-flow default (same rule as the
        switch's ``is_on``)."""
        c = self._const()
        val = self._data().get(c.INTERIOR_VISION_SWITCH_HASS_KEY)
        if val is not None:
            return bool(val)
        try:
            for ce in self.hass.config_entries.async_entries(c.DOMAIN):
                if ce.data.get(c.CONF_ENTRY_TYPE) == c.ENTRY_TYPE_INTEGRATION:
                    merged = {**ce.data, **ce.options}
                    return bool(merged.get(c.CONF_INTERIOR_VISION_ENABLED,
                                           c.DEFAULT_INTERIOR_VISION_ENABLED))
        except Exception:  # noqa: BLE001
            pass
        return bool(c.DEFAULT_INTERIOR_VISION_ENABLED)

    def daily_cap(self) -> int:
        c = self._const()
        raw = self._data().get(c.INTERIOR_VISION_CAP_HASS_KEY)
        try:
            return max(0, int(raw if raw is not None else c.INTERIOR_VISION_DAILY_CALLS))
        except (TypeError, ValueError):
            return max(0, int(c.INTERIOR_VISION_DAILY_CALLS))

    def cost_cap(self) -> float:
        c = self._const()
        raw = self._data().get(c.INTERIOR_VISION_COST_HASS_KEY)
        try:
            return max(0.0, float(raw if raw is not None else c.INTERIOR_VISION_DAILY_COST_USD))
        except (TypeError, ValueError):
            return max(0.0, float(c.INTERIOR_VISION_DAILY_COST_USD))

    def _local_day(self, now: float) -> Any:
        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        return dt_util.as_local(dt_util.utc_from_timestamp(float(now))).date()

    def _roll_day(self, now: float) -> None:
        day = self._local_day(now)
        if day != self._day:
            if self._day is not None and self.rehydrate_state == "failed":
                # A failed rehydrate holds the budget until local midnight.
                self.cap_hold = False
            self._day = day
            self.calls_today = 0
            self.cost_today = 0.0

    def budget_skip(self, purpose: str, now: float | None = None) -> str | None:
        c = self._const()
        self._roll_day(self._now() if now is None else now)
        if self.cap_hold:
            return SKIP_REHYDRATING
        return budget_skip(
            switch_on=self.switch_on(), kill=bool(c.LLMVISION_ENRICHMENT_KILL),
            cap=self.daily_cap(), cost_cap=self.cost_cap(), calls_today=self.calls_today,
            cost_today=self.cost_today, est_cost=float(c.INTERIOR_VISION_EST_COST_PER_CALL),
            reserved=int(c.INTERIOR_DESCRIBE_RESERVED_CALLS), purpose=purpose,
        )

    # ---------------------------------------------------- rehydrate (P3-D5)
    async def async_rehydrate(self, *, retry: bool = True) -> None:
        """Set today's counters from today's ``interior_description`` rows
        (one per model call, every outcome). One try bounded by
        ``INTERIOR_VISION_CAP_REHYDRATE_TIMEOUT_S``, one retry after
        ``_RETRY_S``; both failing holds the budget until local midnight and
        pages LOW ``interior_vision_cap_rehydrate_failed``. Reuses
        ``Database.count_memory_episodes_by_type_ended_between`` (P3-D5)."""
        import asyncio  # noqa: PLC0415
        from datetime import timedelta  # noqa: PLC0415

        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        c = self._const()
        self.cap_hold = True
        self.rehydrate_state = "pending"
        for attempt in range(2 if retry else 1):
            if attempt:
                await asyncio.sleep(float(c.INTERIOR_VISION_CAP_REHYDRATE_RETRY_S))
            if self.torn_down:
                return
            self._roll_day(self._now())
            day = self._day
            database = self._data().get("database")
            try:
                if database is None:
                    raise RuntimeError("no database")
                start = dt_util.as_utc(dt_util.start_of_local_day(day))
                end = dt_util.as_utc(dt_util.start_of_local_day(day + timedelta(days=1)))
                count, ok = await asyncio.wait_for(
                    database.count_memory_episodes_by_type_ended_between(
                        c.INTERIOR_DESCRIPTION_EPISODE_TYPE, start.isoformat(),
                        end.isoformat(), CALL_OUTCOMES),
                    timeout=float(c.INTERIOR_VISION_CAP_REHYDRATE_TIMEOUT_S))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                count, ok = 0, False
            if self.torn_down:
                return
            if ok:
                self._roll_day(self._now())
                if self._day == day:
                    self.calls_today = max(self.calls_today, int(count))
                    self.cost_today = max(
                        self.cost_today, int(count) * float(c.INTERIOR_VISION_EST_COST_PER_CALL))
                self.cap_hold = False
                self.rehydrate_state = "ok"
                return
        self.rehydrate_state = "failed"
        self.counters["rehydrate_failed"] += 1
        self._fire("interior_vision_cap_rehydrate_failed",
                   "Interior vision could not count today's calls after a restart (two "
                   "tries); describe is off until local midnight.",
                   "Check the URA database (memory_episodes reads).", "LOW")

    # ---------------------------------------------------------- describe
    def describe(self, group: Mapping[str, Any], *, room: str, still_live: bool,
                 dewarp_views: Sequence[Sequence[float]] | None, record_affect: bool,
                 reply_affect: bool, requester: str | None, reason: str, header: str,
                 reply: Callable[[str], Any] | None) -> str:
        """Start one description of ``room``'s group. Returns the immediate
        reply ("" = scheduled; the answer goes to ``reply`` when ready).
        No call (and no frame fetch) on any refusal. ``record_affect``: ask
        for and store affect (the knob); ``reply_affect``: the reply may
        carry it (Q2 ``operator_affect`` with the operator asking only)."""
        c = self._const()
        now = self._now()
        self.counters["describe_requests"] += 1
        self._triggers.append(now)
        try:
            return self._describe(group, now=now, room=room, still_live=still_live,
                                  dewarp_views=dewarp_views, record_affect=record_affect,
                                  reply_affect=reply_affect,
                                  requester=requester, reason=reason, header=header,
                                  reply=reply, c=c)
        finally:
            self.check_tripwires(now)

    def _describe(self, group, *, now, room, still_live, dewarp_views, record_affect,
                  reply_affect,
                  requester, reason, header, reply, c) -> str:
        if self.torn_down:
            # Never "" (= scheduled) on a dead sampler (review B-L5).
            self.skips["torn_down"] += 1
            return "Interior vision is not running."
        skip = self.budget_skip(PURPOSE_DESCRIBE, now)
        if skip is not None:
            self.skips[skip] += 1
            if skip in (SKIP_SWITCH_OFF, SKIP_KILL):
                return "Interior vision is off."
            if skip == SKIP_REHYDRATING:
                return "Interior vision is starting up; try again in a minute."
            return "Interior vision limit reached today."
        still = group.get("still_source")
        if not still:
            self.skips["no_still_source"] += 1
            return f"No camera picture available for {room}."
        if not still_live:
            self.skips["still_source_not_live"] += 1
            return f"The {room} camera is not available right now."
        # Reserve the call before any await (two quick requests cannot both
        # pass a cap of one).
        self.calls_today += 1
        self.cost_today += float(c.INTERIOR_VISION_EST_COST_PER_CALL)
        coro = self._run(group, room=room, still=str(still), dewarp_views=dewarp_views,
                         record_affect=record_affect, reply_affect=reply_affect,
                         requester=requester, reason=reason,
                         header=header, reply=reply, t0=now)
        try:
            task = self.hass.async_create_background_task(coro, "ura_interior_describe")
        except Exception:  # noqa: BLE001
            coro.close()
            self.counters["task_errors"] += 1
            return f"Couldn't describe {room} right now."
        self.tasks.add(task)
        try:
            task.add_done_callback(self.tasks.discard)
        except Exception:  # noqa: BLE001
            pass
        return ""

    async def _run(self, group, *, room, still, dewarp_views, record_affect, reply_affect,
                   requester,
                   reason, header, reply, t0) -> None:
        import asyncio  # noqa: PLC0415
        import uuid  # noqa: PLC0415

        c = self._const()
        files: list[str] = []
        status = DESCRIBE_ERROR
        fields: dict[str, Any] | None = None
        scrubbed = 0
        dewarped = False
        n_views = 1
        # Staged-file prefix chosen BEFORE any await (reviews A-L3 / B-L1,
        # A-L5): unique per call, and on any exit (cancel included) every
        # file with it is deleted after the write job has finished.
        prefix = f"{STAGE_PREFIX}{uuid.uuid4().hex}"
        writes: list = []
        try:
            entities: tuple[str, ...] = (still,)
            if dewarp_views:
                try:
                    files = await self._stage_dewarped(still, dewarp_views, prefix, writes)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    self.counters["dewarp_failed"] += 1
                    _LOGGER.debug("interior vision: dewarp failed, raw still", exc_info=True)
                    files = []
                if files:
                    entities, dewarped, n_views = (), True, len(files)
                    self.counters["dewarped_calls"] += 1
            fs = FrameSource("still", str(group.get("group_key")), entities, tuple(files))
            self._calls.append(self._now())
            self.counters["calls"] += 1
            result = await call_model(
                self.hass, fs, describe_prompt(room, n_views, record_affect),
                describe_structure(record_affect),
                model=str(c.CROSSING_VISION_MODEL), max_tokens=int(c.CROSSING_VISION_MAX_TOKENS),
                target_width=int(c.CROSSING_VISION_TARGET_WIDTH),
                timeout_s=float(c.INTERIOR_VISION_CALL_TIMEOUT_S), provider=self._provider(),
            )
            if result is None:
                status = DESCRIBE_ERROR
            elif result.get("status") == "response":
                fields, scrubbed = parse_description(
                    response_payload(result.get("result")), self._names(), record_affect)
                status = DESCRIBE_OK if fields is not None else DESCRIBE_UNPARSED
            elif result.get("status") == "timeout":
                status = DESCRIBE_TIMEOUT
            else:
                status = DESCRIBE_ERROR
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            status = DESCRIBE_ERROR
            _LOGGER.debug("interior vision: describe failed", exc_info=True)
        finally:
            if dewarp_views:
                if writes:
                    # A cancel can land while the write job runs in the
                    # executor: wait for it, then delete by prefix.
                    await asyncio.wait(writes)
                await self._unstage(prefix)
        now = self._now()
        latency = max(0.0, now - float(t0))
        self._latencies.append(latency)
        self.counters[f"outcome_{status}"] += 1
        self.counters["description_name_scrubbed"] += scrubbed
        if status != DESCRIBE_OK:
            self._errors.append(now)
        record = None
        if fields is not None:
            fields.update(room=room, group_key=str(group.get("group_key")), ts=now,
                          requested_by=requester, reason=reason, views=n_views,
                          dewarped=dewarped, names_scrubbed=scrubbed,
                          latency_s=round(latency, 2), model=str(c.CROSSING_VISION_MODEL))
            record = self._emit(fields)
        try:
            # One row per model call, every outcome: the restart rehydrate
            # counts these (review B-L2).
            self._log_row(record, {
                "outcome": status, "room": room, "group_key": str(group.get("group_key")),
                "reason": reason, "views": n_views, "dewarped": dewarped,
                "latency_s": round(latency, 2), "model": str(c.CROSSING_VISION_MODEL),
            })
        except Exception:  # noqa: BLE001
            _LOGGER.debug("interior vision: description row failed", exc_info=True)
        self.check_tripwires(now)
        if reply is None:
            return
        text = (format_description_reply(record if record is not None else fields,
                                         reply_affect, header)
                if fields is not None else f"Couldn't describe {room} right now.")
        try:
            res = reply(text)
            if hasattr(res, "__await__"):
                await res
        except Exception:  # noqa: BLE001
            self.counters["reply_errors"] += 1
            _LOGGER.debug("interior vision: reply failed", exc_info=True)

    # ------------------------------------------------------ frames (§8)
    def stage_dir(self) -> str:
        import os  # noqa: PLC0415

        return os.path.join(self.hass.config.config_dir, self._const().INTERIOR_STAGE_SUBDIR)

    async def _stage_dewarped(self, still: str, views: Sequence[Sequence[float]],
                              prefix: str, writes: list) -> list[str]:
        """Fetch the still through HA's camera component, cut the flat views
        in the executor and stage them as local files for llmvision, named
        ``<prefix>_<i>.jpg``. The write job is appended to ``writes`` before
        it is awaited so the caller can wait for it after a cancel."""
        from homeassistant.components import camera as _cam  # noqa: PLC0415

        from . import interior_dewarp as _dw  # noqa: PLC0415

        c = self._const()
        image = await _cam.async_get_image(
            self.hass, still, timeout=int(c.INTERIOR_VISION_STILL_TIMEOUT_S))
        jpegs = await self.hass.async_add_executor_job(
            lambda: _dw.dewarp_jpeg(
                image.content, views, in_fov_deg=float(c.INTERIOR_DEWARP_IN_FOV_DEG),
                out_fov_deg=float(c.INTERIOR_DEWARP_OUT_FOV_DEG),
                out_px=int(c.INTERIOR_DEWARP_OUT_PX),
                quality=int(c.INTERIOR_DEWARP_JPEG_QUALITY)))
        fut = self.hass.async_add_executor_job(
            _write_stage, self.stage_dir(), prefix, list(jpegs))
        writes.append(fut)
        # Shielded: a task cancel must not cancel this future (the thread
        # keeps writing either way); the caller waits for it, then deletes.
        import asyncio  # noqa: PLC0415

        return await asyncio.shield(fut)

    async def _unstage(self, prefix: str) -> None:
        try:
            left = await self.hass.async_add_executor_job(
                _remove_prefix, self.stage_dir(), prefix)
        except Exception:  # noqa: BLE001
            left = [prefix]
        if left:
            self.counters["frames_left"] += len(left)
            self._page_frames_left(left)

    async def async_sweep_stage(self) -> None:
        """Setup discharge: a still left by a restart or crash mid-call is
        deleted (counted ``frames_deleted``); one that cannot be deleted pages."""
        try:
            deleted, left = await self.hass.async_add_executor_job(
                _sweep_dir, self.stage_dir())
        except Exception:  # noqa: BLE001
            return
        self.counters["frames_deleted"] += deleted
        if left:
            self.counters["frames_left"] += len(left)
            self._page_frames_left(left)

    def _page_frames_left(self, left: Sequence[str]) -> None:
        c = self._const()
        if not c.INTERIOR_FRAMES_LEFT_CHECK_ENABLED or self._frames_left_latched:
            return
        self._frames_left_latched = True
        self._fire("interior_frames_left",
                   f"{len(left)} interior vision still(s) could not be deleted after the call",
                   f"Delete the files under {c.INTERIOR_STAGE_SUBDIR} and check the folder's "
                   "permissions.", "HIGH")

    # -------------------------------------------------------- trip-wires
    def check_tripwires(self, now: float) -> None:
        c = self._const()
        window = float(c.INTERIOR_ZERO_WINDOW_H) * 3600.0
        for dq in (self._triggers, self._calls, self._errors):
            while dq and dq[0] < now - window:
                dq.popleft()
        if self._calls:
            self._zero_latched = False
        min_trig = int(c.INTERIOR_VISION_ZERO_MIN_TRIGGERS)
        if (min_trig > 0 and not self._zero_latched and not self._calls
                and len(self._triggers) >= min_trig and self.switch_on()
                and self.daily_cap() > 0 and self.cost_cap() > 0):
            self._zero_latched = True
            self._fire("interior_vision_zero_calls",
                       f"{len(self._triggers)} interior vision requests in "
                       f"{float(c.INTERIOR_ZERO_WINDOW_H):g} h and no model call",
                       "Check the interior camera still sources (Frigate member live) "
                       "and the llmvision provider.", "HIGH")
        n = len(self._calls)
        rate_max = float(c.INTERIOR_VISION_ERROR_RATE_MAX)
        if n >= max(1, int(c.INTERIOR_VISION_ERRORS_MIN_CALLS)) and rate_max <= 1.0:
            rate = len(self._errors) / n
            if rate > rate_max and not self._errors_latched:
                self._errors_latched = True
                self._fire("interior_vision_errors",
                           f"Interior vision: {len(self._errors)} of {n} calls failed in "
                           f"{float(c.INTERIOR_ZERO_WINDOW_H):g} h",
                           "Check the llmvision provider and the camera stills.", "MEDIUM")
            elif rate <= rate_max:
                self._errors_latched = False

    def teardown(self) -> None:
        self.torn_down = True
        for task in list(self.tasks):
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass
        self.tasks.clear()

    def diagnostics(self) -> dict[str, Any]:
        lat = sorted(self._latencies)
        p90 = lat[min(len(lat) - 1, int(0.9 * len(lat)))] if lat else None
        return {
            "switch_on": self.switch_on(), "calls_today": self.calls_today,
            "cost_today_est": round(self.cost_today, 4), "daily_cap": self.daily_cap(),
            "cost_cap": self.cost_cap(), "rehydrate": self.rehydrate_state,
            "skips_by_reason": dict(sorted(self.skips.items())),
            "counters": dict(sorted(self.counters.items())),
            "latency_p90_s": p90, "tasks": len(self.tasks),
        }


def _write_stage(folder: str, prefix: str, jpegs: list[bytes]) -> list[str]:
    import os  # noqa: PLC0415

    os.makedirs(folder, exist_ok=True)
    out = []
    try:
        for i, data in enumerate(jpegs):
            path = os.path.join(folder, f"{prefix}_{i}.jpg")
            with open(path, "wb") as fh:
                fh.write(data)
            out.append(path)
    except Exception:
        _remove_files(out)
        raise
    return out


def _remove_files(paths: Sequence[str]) -> list[str]:
    """Delete each path; return those still present."""
    import os  # noqa: PLC0415

    left = []
    for p in paths:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except OSError:
            left.append(p)
    return left


def _remove_prefix(folder: str, prefix: str) -> list[str]:
    """Delete every staged file of one call (``<prefix>_*``); return the
    ones still present."""
    import os  # noqa: PLC0415

    if not os.path.isdir(folder):
        return []
    return _remove_files([os.path.join(folder, n) for n in os.listdir(folder)
                          if n.startswith(prefix + "_")])


def _sweep_dir(folder: str) -> tuple[int, list[str]]:
    import os  # noqa: PLC0415

    if not os.path.isdir(folder):
        return 0, []
    paths = [os.path.join(folder, n) for n in os.listdir(folder) if n.startswith(STAGE_PREFIX)]
    left = _remove_files(paths)
    return len(paths) - len(left), left
