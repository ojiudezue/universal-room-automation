"""VISION-CROSSING-SHADOW-1: crossing vision, shadow only (Phase 1, D1 + D3).

Plan: docs/planning/PLANNING_crossing_vision.md rev 2 (plan review
docs/reviews/plan-review/PLAN_crossing_vision_review.md, F1-F13).

For every entry/exit crossing (``ura_person_egress_event``) on a door camera,
call llmvision ``video_analyzer`` once on the clip of the matching Frigate
person event, ask for a structured per-frame people count, and write one
``memory_episodes`` row (``crossing_vision_shadow``) with the vision count
beside the camera count the transit validator sampled (D2 bus key).

INV-SHADOW: nothing decides on this. The module's only writes are its own
rows, its own counters / diagnostic attributes, llmvision's own media files
(llmvision creates them) and its own ``fire_stuck_signal`` pages. Readers:
the Outside: Open Tracks diagnostic attributes, the weekly scorer script, the
trip-wires below, and the generic pre-existing memory readers (status counts,
``memory_query``, writer health). No compaction rule exists for the type.

INV-OFF: switch off (``hass.data[DOMAIN][CROSSING_VISION_SWITCH_HASS_KEY]``),
``LLMVISION_ENRICHMENT_KILL`` True, or a daily cap of 0 = no service call,
no Frigate media request, no row. The gates are read when a crossing is
scheduled AND again when the call is about to be made.

INV-SCOPE: a crossing only ever matches a Frigate event on a camera whose
stem is in the crossing's configured door group (a stem with no group is a
group of one). Calls per local day <= the cap; requests waiting or calling
<= ``CROSSING_VISION_MAX_CONCURRENT``; nothing queues beyond them (counted
skip).

INV-BLANK: all-zero (or absent) per-frame counts = ``outcome = blank`` with
``people_count`` None, never a count of 0. No matched event =
``no_frigate_event`` and no call.

Knobs: const.py ``CROSSING_VISION_*`` (plan §6). Rung-1 constants are read
from the ``const`` module at use time (``_c.X``) so a reviewed change takes
effect without touching this file.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import const as _c
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

EGRESS_EVENT = "ura_person_egress_event"
FRIGATE_CONSUMER_NAME = "crossing_vision"

# Outcome vocabulary (row attr ``outcome``).
OUTCOME_OK = "ok"
OUTCOME_BLANK = "blank"
OUTCOME_UNPARSEABLE = "unparseable"
OUTCOME_ERROR = "error"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_REFUSED = "refused"
OUTCOME_NO_EVENT = "no_frigate_event"
OUTCOME_NO_CLIP_URL = "no_clip_url"
OUTCOME_CLUSTERED = "clustered"
OUTCOME_SKIPPED_CAP = "skipped_cap"
OUTCOME_SKIPPED_BUSY = "skipped_busy"

# Call outcomes that count as failures for the error-rate trip-wire.
FAILED_CALL_OUTCOMES = frozenset({
    OUTCOME_ERROR, OUTCOME_TIMEOUT, OUTCOME_UNPARSEABLE, OUTCOME_REFUSED,
})

# §15.7 agreement cases, computed on counts (never on guests).
CASE_AGREE = "A"
CASE_VISION_HIGHER = "B"
CASE_CAMERA_HIGHER = "C"
CASE_ONE_MISSING = "D"

FRAME_SOURCE_VIDEO = "video_analyzer"

# Structured-output schema (OpenAI strict mode: every property required,
# additionalProperties false at every object level).
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "people": {"type": "integer"},
                },
                "required": ["index", "people"],
                "additionalProperties": False,
            },
        },
        "people_total": {"type": "integer"},
        "group": {"type": "boolean"},
        "desc": {"type": "string"},
    },
    "required": ["frames", "people_total", "group", "desc"],
    "additionalProperties": False,
}
RESPONSE_STRUCTURE = json.dumps(RESPONSE_SCHEMA, separators=(",", ":"))

PROMPT = (
    "These are frames, in time order, from a camera at a door of a house. "
    "For each frame give its 1-based index and how many people are visible "
    "in that frame (0 if none). people_total is how many distinct people "
    "appear across all frames. group is true if more than one "
    "person crosses together. desc is one short sentence about what happens. "
    "Do not name or identify anyone."
)


# ---------------------------------------------------------------------------
# Pure helpers (no HA)
# ---------------------------------------------------------------------------
def agreement_case(vision: int | None, camera: int | None) -> str:
    """§15.7 case on counts: A agree, B vision higher, C camera higher, D one
    side missing."""
    if vision is None or camera is None:
        return CASE_ONE_MISSING
    if vision == camera:
        return CASE_AGREE
    return CASE_VISION_HIGHER if vision > camera else CASE_CAMERA_HIGHER


def _as_nonneg_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def parse_vision_response(result: Any, desc_max: int) -> dict[str, Any]:
    """Classify an llmvision ``video_analyzer`` response.

    llmvision (1.7.1 ``providers.py`` result assembly) returns
    ``{"structured_response": {...}}`` and DROPS ``response_text`` when the
    provider supports structured output and the text parsed as JSON; it
    returns ``{"response_text": "<text>"}`` otherwise. Both are accepted.

    Returns ``{"outcome", "people_count", "frame_counts", "group", "desc"}``
    (no direction field: D0 found no usable direction signal, so the
    producer neither asks for nor records one). Outcomes: ok / blank (INV-BLANK) / unparseable /
    refused (empty text or an empty dict).
    """
    out: dict[str, Any] = {
        "outcome": OUTCOME_UNPARSEABLE,
        "people_count": None,
        "frame_counts": None,
        "group": None,
        "desc": None,
    }
    if not isinstance(result, Mapping):
        return out
    # D0 (AUDIT_crossing_vision_d0_2026_11_13): the response may arrive
    # wrapped as {"service_response": {"structured_response": ...,
    # "key_frame": ...}} with NO response_text; unwrap one level.
    inner = result.get("service_response")
    if isinstance(inner, Mapping) and (
        "structured_response" in inner or "response_text" in inner
        or not inner
    ):
        result = inner
    parsed: Any = None
    structured = result.get("structured_response")
    if "structured_response" in result and not structured:
        out["outcome"] = OUTCOME_REFUSED
        return out
    if isinstance(structured, Mapping):
        parsed = structured
    elif "response_text" in result:
        text = result.get("response_text")
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            out["outcome"] = OUTCOME_REFUSED
            return out
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return out
    elif not result:
        out["outcome"] = OUTCOME_REFUSED
        return out
    else:
        return out
    if not isinstance(parsed, Mapping):
        return out
    frames = parsed.get("frames")
    if not isinstance(frames, list):
        return out
    counts: list[int] = []
    for fr in frames:
        if not isinstance(fr, Mapping):
            return out
        n = _as_nonneg_int(fr.get("people"))
        if n is None:
            return out
        counts.append(n)
    grp = parsed.get("group")
    out["group"] = grp if isinstance(grp, bool) else None
    desc = parsed.get("desc")
    out["desc"] = desc[: max(0, int(desc_max))] if isinstance(desc, str) else None
    out["frame_counts"] = counts
    peak = max(counts) if counts else 0
    if peak <= 0:
        # INV-BLANK: never a count of 0.
        out["outcome"] = OUTCOME_BLANK
        return out
    total = _as_nonneg_int(parsed.get("people_total"))
    upper = peak * len(counts)
    if total is None:
        total = peak
    out["people_count"] = min(max(total, peak), upper)
    out["outcome"] = OUTCOME_OK
    return out


def frigate_camera_stem(camera: str) -> str | None:
    """Frigate ``after.camera`` -> camera stem, through the SAME normaliser
    the transit validator applies to its count-sensor stems (plan rev 2 F1:
    derived at runtime, never a hard-coded name map)."""
    if not isinstance(camera, str) or not camera.strip():
        return None
    from .transit_validator import EgressDirectionTracker  # noqa: PLC0415

    return EgressDirectionTracker._extract_camera_stem(
        f"sensor.{camera.strip()}_person_count"
    )


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------
@dataclass
class _Request:
    key: str
    group_key: str
    door_group: str | None
    members_stems: frozenset[str]
    e_ts: datetime
    event: dict[str, Any]
    crossing: dict[str, Any]
    crossing_keys: list[str] = field(default_factory=list)
    status: str = "waiting"  # waiting -> calling -> done
    unsub_timer: Callable[[], None] | None = None


class CrossingVisionShadow:
    """Shadow producer. One instance per integration entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._torn_down = False
        self._unsubs: list[Callable[[], None]] = []
        self._tasks: set[asyncio.Task] = set()
        # stem -> OrderedDict(event_id -> entry), bounded per camera.
        self._ring: dict[str, OrderedDict[str, dict[str, Any]]] = {}
        self._waiting_by_event: dict[str, _Request] = {}
        self._requests: deque[_Request] = deque()
        self._stem_cache: dict[str, str | None] = {}
        # Daily cap (RAM, reset at local midnight; plan rev 2 F7).
        self._day: Any = None
        self._calls_today = 0
        self._today: dict[str, int] = {}
        self._last: dict[str, Any] | None = None
        # Trip-wire windows: (epoch_s, kind) samples, pruned to the window.
        self._seen: deque[float] = deque()
        self._calls: deque[tuple[float, str]] = deque()
        self._zero_latched = False
        self._errors_latched = False
        self._roll_day()

    # ---- gates ----------------------------------------------------------
    def _domain_data(self) -> Mapping[str, Any]:
        try:
            data = self.hass.data.get(DOMAIN, {})
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, Mapping) else {}

    def switch_on(self) -> bool:
        return bool(self._domain_data().get(_c.CROSSING_VISION_SWITCH_HASS_KEY, False))

    def daily_cap(self) -> int:
        raw = self._domain_data().get(_c.CROSSING_VISION_CAP_HASS_KEY)
        try:
            cap = int(raw) if raw is not None else int(_c.CROSSING_VISION_DAILY_CALLS)
        except (TypeError, ValueError):
            cap = int(_c.CROSSING_VISION_DAILY_CALLS)
        return max(0, cap)

    def _enabled(self) -> bool:
        """INV-OFF: switch on AND kill const False AND cap > 0."""
        return (
            self.switch_on()
            and not bool(_c.LLMVISION_ENRICHMENT_KILL)
            and self.daily_cap() > 0
        )

    def _pending(self) -> int:
        return sum(1 for r in self._requests if r.status in ("waiting", "calling"))

    def _waiting(self) -> int:
        return sum(1 for r in self._requests if r.status == "waiting")

    # ---- lifecycle ------------------------------------------------------
    async def async_setup(self) -> None:
        from homeassistant.helpers.event import (  # noqa: PLC0415
            async_track_time_interval,
        )

        from .frigate_ingress import register_frigate_consumer  # noqa: PLC0415

        self._unsubs.append(
            self.hass.bus.async_listen(EGRESS_EVENT, self._on_egress_event)
        )
        self._unsubs.append(
            register_frigate_consumer(
                self.hass, FRIGATE_CONSUMER_NAME, self._on_frigate_event,
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._on_tripwire_tick,
                timedelta(seconds=int(_c.CROSSING_VISION_TRIPWIRE_EVAL_S)),
            )
        )

    async def async_teardown(self) -> None:
        """Latch first, then unsubscribe, cancel timers, gather in-flight
        tasks with a bound (the transit_validator outcome-log pattern)."""
        self._torn_down = True
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()
        for req in list(self._requests):
            if req.unsub_timer is not None:
                try:
                    req.unsub_timer()
                except Exception:  # noqa: BLE001
                    pass
                req.unsub_timer = None
        self._waiting_by_event.clear()
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=float(_c.CROSSING_VISION_TEARDOWN_GATHER_S),
                )
            except Exception:  # noqa: BLE001 — bounded; never block unload
                for t in pending:
                    if not t.done():
                        t.cancel()
        self._tasks.clear()

    def _spawn(self, coro: Any, *, background: bool = False) -> None:
        """Track a task for the bounded teardown gather. ``background`` (the
        llmvision call, review B2) uses a background task so an HA stop does
        not wait up to TIMEOUT_S on it; row writes stay ordinary tasks."""
        if self._torn_down:
            coro.close()
            return
        try:
            if background:
                task = self.hass.async_create_background_task(
                    coro, "crossing_vision_run",
                )
            else:
                task = self.hass.async_create_task(coro)
        except Exception:  # noqa: BLE001
            coro.close()
            _LOGGER.debug("crossing_vision: task create failed", exc_info=True)
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- day / counters -------------------------------------------------
    def _roll_day(self) -> None:
        day = dt_util.now().date()
        if day != self._day:
            self._day = day
            self._calls_today = 0
            self._today = {
                "calls": 0, "ok": 0, "blank": 0, "no_event": 0, "errors": 0,
                "skipped_cap": 0, "skipped_busy": 0, "clustered": 0,
                "no_clip_url": 0,
            }

    def _count(self, outcome: str) -> None:
        key = {
            OUTCOME_OK: "ok",
            OUTCOME_BLANK: "blank",
            OUTCOME_NO_EVENT: "no_event",
            OUTCOME_SKIPPED_CAP: "skipped_cap",
            OUTCOME_SKIPPED_BUSY: "skipped_busy",
            OUTCOME_CLUSTERED: "clustered",
            OUTCOME_NO_CLIP_URL: "no_clip_url",
        }.get(outcome)
        if key is None and outcome in FAILED_CALL_OUTCOMES:
            key = "errors"
        if key is not None:
            self._today[key] = self._today.get(key, 0) + 1

    @staticmethod
    def _epoch() -> float:
        return dt_util.utcnow().timestamp()

    # ---- Frigate ring ---------------------------------------------------
    def _stem_for_camera(self, camera: str) -> str | None:
        if camera not in self._stem_cache:
            try:
                self._stem_cache[camera] = frigate_camera_stem(camera)
            except Exception:  # noqa: BLE001
                self._stem_cache[camera] = None
        return self._stem_cache[camera]

    def _tracker(self) -> Any:
        return self._domain_data().get("egress_tracker")

    def _door_stems(self) -> frozenset[str]:
        tr = self._tracker()
        if tr is None:
            return frozenset()
        try:
            return tr.door_camera_stems()
        except Exception:  # noqa: BLE001
            return frozenset()

    @staticmethod
    def _instance_from_source(hass: HomeAssistant, source: str) -> str | None:
        if not isinstance(source, str) or not source.startswith("mqtt:"):
            return None
        from .frigate_ingress import discover_frigate_instance_ids  # noqa: PLC0415

        return discover_frigate_instance_ids(hass).get(source[len("mqtt:"):])

    @callback
    def _on_frigate_event(self, data: Mapping[str, Any], source: str) -> None:
        """Ingress consumer (sync, no await). Keeps a bounded ring of door-
        camera person events; an ``end`` for a waited event fires its call."""
        if self._torn_down:
            return
        after = data.get("after") if isinstance(data, Mapping) else None
        if not isinstance(after, Mapping):
            return
        if after.get("label") != "person":
            return
        event_id = after.get("id")
        camera = after.get("camera")
        if not event_id or not isinstance(camera, str):
            return
        stem = self._stem_for_camera(camera)
        if not stem or stem not in self._door_stems():
            return
        try:
            start = float(after.get("start_time"))
        except (TypeError, ValueError):
            return
        ring = self._ring.setdefault(stem, OrderedDict())
        eid = str(event_id)
        entry = ring.get(eid)
        if entry is None:
            entry = {
                "id": eid, "camera": camera, "stem": stem, "start": start,
                "end": None, "top_score": 0.0, "has_clip": False,
                "instance": None, "analysed_by": None,
            }
            ring[eid] = entry
            while len(ring) > max(1, int(_c.CROSSING_VISION_EVENT_RING)):
                ring.popitem(last=False)
        try:
            entry["top_score"] = max(
                float(entry["top_score"]), float(after.get("top_score") or 0.0)
            )
        except (TypeError, ValueError):
            pass
        if after.get("has_clip"):
            entry["has_clip"] = True
        end = after.get("end_time")
        if end is not None:
            try:
                entry["end"] = float(end)
            except (TypeError, ValueError):
                pass
        if entry["instance"] is None:
            try:
                entry["instance"] = self._instance_from_source(self.hass, source)
            except Exception:  # noqa: BLE001
                entry["instance"] = None
        if data.get("type") == "end" and entry["end"] is None:
            entry["end"] = self._epoch()
        if entry["end"] is not None:
            req = self._waiting_by_event.get(eid)
            if req is not None and req.status == "waiting":
                self._fire_request(req)

    # ---- crossing trigger -----------------------------------------------
    @callback
    def _on_egress_event(self, event: Event) -> None:
        if self._torn_down:
            return
        data = event.data if isinstance(event.data, Mapping) else {}
        direction = data.get("direction")
        if direction not in ("entry", "exit"):
            return
        self._roll_day()
        # INV-OFF: no row, no call while off (and no trip-wire sample).
        if not self._enabled():
            return
        camera = data.get("egress_camera")
        ts_raw = data.get("timestamp")
        if not isinstance(camera, str) or not isinstance(ts_raw, str):
            return
        e_ts = dt_util.parse_datetime(ts_raw)
        if e_ts is None:
            return
        crossing_key = f"{camera}@{ts_raw}"
        self._seen.append(self._epoch())

        from .transit_validator import EgressDirectionTracker  # noqa: PLC0415

        stem = EgressDirectionTracker._extract_camera_stem(camera)
        tr = self._tracker()
        door_group: str | None = None
        members: frozenset[str] = frozenset({stem}) if stem else frozenset()
        if tr is not None and stem:
            try:
                door_group, members = tr.door_group_members(stem)
            except Exception:  # noqa: BLE001
                door_group, members = None, frozenset({stem})
        group_key = f"group:{door_group}" if door_group else f"stem:{stem}"
        e_epoch = e_ts.timestamp()
        crossing = {
            "crossing_key": crossing_key,
            "direction": direction,
            "door_group": door_group,
            "camera_peak_count": _as_nonneg_int(data.get("peak_person_count")),
            "person_id": data.get("person_id"),
            "identity_provenance": data.get("identity_provenance"),
            "frigate_events_in_window": self._events_in_window(members, e_epoch),
            "e_ts": e_ts,
        }
        self._prune_requests(e_epoch)

        # 1. Cluster: any request (open or completed) of this door group
        #    within CLUSTER_S of E.
        cluster_s = float(_c.CROSSING_VISION_CLUSTER_S)
        for req in self._requests:
            if req.group_key == group_key and abs(
                req.e_ts.timestamp() - e_epoch
            ) <= cluster_s:
                self._join_cluster(req, crossing)
                return

        # 2. Match a Frigate person event on a door-group camera.
        match = self._match_event(members, e_epoch)
        if match is None:
            self._record(crossing, OUTCOME_NO_EVENT)
            return
        prior = match.get("analysed_by")
        if prior is not None:
            primary = next((r for r in self._requests if r.key == prior), None)
            if primary is not None:
                self._join_cluster(primary, crossing)
            else:
                self._record(crossing, OUTCOME_CLUSTERED, primary_crossing_key=prior,
                             event=match)
            return

        # 3. Schedule-time gates (cap, concurrency). Off was handled above.
        #    A `calling` request is already in _calls_today, so only the
        #    `waiting` ones are added (reviews A1/B4: no double count).
        if self._calls_today + self._waiting() >= self.daily_cap():
            self._record(crossing, OUTCOME_SKIPPED_CAP, event=match)
            return
        if self._pending() >= max(0, int(_c.CROSSING_VISION_MAX_CONCURRENT)):
            self._record(crossing, OUTCOME_SKIPPED_BUSY, event=match)
            return

        req = _Request(
            key=crossing_key, group_key=group_key, door_group=door_group,
            members_stems=members, e_ts=e_ts, event=match, crossing=crossing,
            crossing_keys=[crossing_key],
        )
        match["analysed_by"] = crossing_key
        self._requests.append(req)
        if match.get("end") is not None:
            self._fire_request(req)
            return
        self._waiting_by_event[match["id"]] = req
        from homeassistant.helpers.event import async_call_later  # noqa: PLC0415

        @callback
        def _timeout(_now: Any) -> None:
            req.unsub_timer = None
            if req.status == "waiting":
                self._fire_request(req)

        req.unsub_timer = async_call_later(
            self.hass, float(_c.CROSSING_VISION_EVENT_END_WAIT_S), _timeout,
        )

    def _join_cluster(self, primary: _Request, crossing: dict[str, Any]) -> None:
        if crossing["crossing_key"] not in primary.crossing_keys:
            primary.crossing_keys.append(crossing["crossing_key"])
        self._record(
            crossing, OUTCOME_CLUSTERED,
            primary_crossing_key=primary.key, event=primary.event,
        )

    def _events_in_window(self, members: frozenset[str], e_epoch: float) -> int:
        lo = e_epoch - float(_c.CROSSING_VISION_EVENT_MATCH_S)
        hi = e_epoch + float(_c.EGRESS_ENTRY_WINDOW_SECONDS)
        ids: set[str] = set()
        for stem in members:
            for ev in (self._ring.get(stem) or {}).values():
                if lo <= ev["start"] <= hi:
                    ids.add(ev["id"])
        return len(ids)

    def _match_event(
        self, members: frozenset[str], e_epoch: float,
    ) -> dict[str, Any] | None:
        """Highest ``top_score`` person event on a door-group camera whose
        start lies in [E - MATCH_S, E + MATCH_S]; tie -> longest."""
        window = float(_c.CROSSING_VISION_EVENT_MATCH_S)
        now = self._epoch()
        best: dict[str, Any] | None = None
        best_key: tuple[float, float] | None = None
        for stem in members:
            for ev in (self._ring.get(stem) or {}).values():
                if abs(ev["start"] - e_epoch) > window:
                    continue
                dur = (ev["end"] if ev["end"] is not None else now) - ev["start"]
                k = (float(ev["top_score"]), float(dur))
                if best_key is None or k > best_key:
                    best, best_key = ev, k
        return best

    def _prune_requests(self, e_epoch: float) -> None:
        horizon = float(_c.CROSSING_VISION_CLUSTER_S) * 2
        while (
            self._requests
            and self._requests[0].status == "done"
            and e_epoch - self._requests[0].e_ts.timestamp() > horizon
        ):
            self._requests.popleft()

    # ---- call -----------------------------------------------------------
    def _fire_request(self, req: _Request) -> None:
        if req.unsub_timer is not None:
            try:
                req.unsub_timer()
            except Exception:  # noqa: BLE001
                pass
            req.unsub_timer = None
        self._waiting_by_event.pop(req.event.get("id"), None)
        if req.status != "waiting":
            return
        req.status = "calling"
        self._spawn(self._run(req), background=True)

    def _provider_id(self) -> str | None:
        """The llmvision entry id to send as ``provider``: the rung-1
        ``CROSSING_VISION_PROVIDER_ID`` only when that id is an llmvision
        config entry on THIS install (portability: another house has other
        entry ids); otherwise None, and the adapter falls back to the
        perimeter's provider."""
        pid = str(_c.CROSSING_VISION_PROVIDER_ID or "").strip()
        if not pid:
            return None
        try:
            entry = self.hass.config_entries.async_get_entry(pid)
        except Exception:  # noqa: BLE001
            return None
        if entry is None or getattr(entry, "domain", None) != "llmvision":
            return None
        return pid

    def _clip_reference(self, ev: Mapping[str, Any]) -> tuple[str | None, str | None]:
        """Return (video_file, event_id) per plan rev 2 F4; (None, None) when
        no safe reference exists."""
        from .frigate_ingress import discover_frigate_instance_ids  # noqa: PLC0415
        from .perimeter_alert import _sanitize_snapshot_token  # noqa: PLC0415

        eid = str(ev.get("id") or "")
        if not eid or _sanitize_snapshot_token(eid) != eid:
            return None, None
        instance = ev.get("instance")
        if not instance:
            ids = set(discover_frigate_instance_ids(self.hass).values())
            if len(ids) == 1:
                instance = next(iter(ids))
        if instance:
            inst = str(instance)
            if _sanitize_snapshot_token(inst) != inst:
                return None, None
            return f"/api/frigate/{inst}/notifications/{eid}/clip.mp4", None
        try:
            n_entries = len(self.hass.config_entries.async_entries("frigate") or [])
        except Exception:  # noqa: BLE001
            n_entries = 0
        if n_entries == 1:
            return None, eid
        return None, None

    async def _run(self, req: _Request) -> None:
        from .perimeter_enrichment import (  # noqa: PLC0415
            CROSSING_CALL_RESPONSE,
            CROSSING_CALL_TIMEOUT,
            analyze_crossing_frames,
        )

        try:
            self._roll_day()
            # INV-OFF re-read at call time: switch / kill / cap 0 -> no call,
            # no row.
            if self._torn_down or not self._enabled():
                return
            if self._calls_today >= self.daily_cap():
                self._record(req.crossing, OUTCOME_SKIPPED_CAP, event=req.event,
                             crossing_keys=req.crossing_keys)
                return
            video_file, event_id = self._clip_reference(req.event)
            if video_file is None and event_id is None:
                self._record(req.crossing, OUTCOME_NO_CLIP_URL, event=req.event,
                             crossing_keys=req.crossing_keys)
                return
            self._calls_today += 1
            self._today["calls"] = self._today.get("calls", 0) + 1
            started = self._epoch()
            reply = await analyze_crossing_frames(
                self.hass,
                event_id or req.event.get("id"),
                video_file=video_file,
                model=str(_c.CROSSING_VISION_MODEL),
                max_frames=int(_c.CROSSING_VISION_MAX_FRAMES),
                target_width=int(_c.CROSSING_VISION_TARGET_WIDTH),
                timeout_s=float(_c.CROSSING_VISION_TIMEOUT_S),
                structure=RESPONSE_STRUCTURE,
                prompt=PROMPT,
                expose_images=bool(_c.CROSSING_VISION_KEEP_FRAMES),
                provider=self._provider_id(),
                max_tokens=int(_c.CROSSING_VISION_MAX_TOKENS),
            )
            latency = round(self._epoch() - started, 2)
            if reply is None:
                # Kill set between the gate and the call: no call was made.
                self._calls_today -= 1
                self._today["calls"] -= 1
                return
            status = reply.get("status")
            if status == CROSSING_CALL_RESPONSE:
                parsed = parse_vision_response(
                    reply.get("result"), int(_c.CROSSING_VISION_DESC_MAX_CHARS),
                )
            elif status == CROSSING_CALL_TIMEOUT:
                parsed = {"outcome": OUTCOME_TIMEOUT}
            else:
                parsed = {"outcome": OUTCOME_ERROR}
            outcome = parsed["outcome"]
            self._calls.append((self._epoch(), outcome))
            if outcome == OUTCOME_OK:
                self._zero_latched = False
            self._record(
                req.crossing, outcome, event=req.event,
                crossing_keys=req.crossing_keys, vision=parsed,
                latency_s=latency,
                frame_source=FRAME_SOURCE_VIDEO,
            )
        except Exception:  # noqa: BLE001 — shadow: never raise
            _LOGGER.debug("crossing_vision: run failed", exc_info=True)
        finally:
            req.status = "done"

    # ---- record ---------------------------------------------------------
    def _record(
        self,
        crossing: Mapping[str, Any],
        outcome: str,
        *,
        event: Mapping[str, Any] | None = None,
        primary_crossing_key: str | None = None,
        crossing_keys: list[str] | None = None,
        vision: Mapping[str, Any] | None = None,
        latency_s: float | None = None,
        frame_source: str | None = None,
    ) -> None:
        """One ``memory_episodes`` row for this crossing (tracked task) plus
        the RAM counters / last-row diagnostics."""
        self._count(outcome)
        vision = vision or {}
        people = vision.get("people_count")
        camera_peak = crossing.get("camera_peak_count")
        ts_iso = crossing["crossing_key"].split("@", 1)[1]
        desc = vision.get("desc")
        attrs = {
            "outcome": outcome,
            "crossing_keys": list(crossing_keys) if crossing_keys else [
                crossing["crossing_key"]
            ],
            "primary_crossing_key": primary_crossing_key,
            "door_group": crossing.get("door_group"),
            "direction": crossing.get("direction"),
            "people_count": people,
            "frame_counts": vision.get("frame_counts"),
            "group": vision.get("group"),
            "desc": desc,
            "camera_peak_count": camera_peak,
            "frigate_events_in_window": crossing.get("frigate_events_in_window"),
            "event_id": (event or {}).get("id"),
            "event_camera": (event or {}).get("camera"),
            "model": str(_c.CROSSING_VISION_MODEL) if frame_source else None,
            "frame_source": frame_source,
            "latency_s": latency_s,
            "person_id": crossing.get("person_id"),
            "identity_provenance": crossing.get("identity_provenance"),
            "agreement_case": agreement_case(people, camera_peak),
        }
        self._last = {
            "outcome": outcome,
            "people_count": people,
            "camera_peak_count": camera_peak,
            "case": attrs["agreement_case"],
            "at": dt_util.utcnow().isoformat(),
        }
        if self._torn_down:
            return
        database = self._domain_data().get("database")
        if database is None:
            return
        crossing_key = crossing["crossing_key"]

        async def _write() -> None:
            try:
                await database.log_memory_episode(
                    node_id=f"vision:{crossing_key}",
                    episode_type=_c.CROSSING_VISION_EPISODE_TYPE,
                    attrs=attrs,
                    source_ref=crossing_key,
                    started_at=ts_iso,
                    ended_at=dt_util.utcnow().isoformat(),
                    dedup_source_ref=False,
                )
            except Exception:  # noqa: BLE001 — observational only
                _LOGGER.debug("crossing_vision row write failed", exc_info=True)

        self._spawn(_write())

    # ---- trip-wires (D3) ------------------------------------------------
    @callback
    def _on_tripwire_tick(self, _now: Any) -> None:
        self._spawn(self.async_evaluate_tripwires())

    async def async_evaluate_tripwires(self) -> None:
        """Zero-ok (HIGH) and error-rate (MEDIUM) pages, RAM-latched.

        Zero-ok re-arms when an ``ok`` arrives; the error page re-arms when
        the error rate is back under the bar. Silent while the switch is
        off. ``fire_stuck_signal`` adds its own once-per-day dedup.
        """
        if self._torn_down or not self.switch_on():
            return
        from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
            fire_stuck_signal,
        )

        now = self._epoch()
        window = float(_c.CROSSING_VISION_TRIPWIRE_WINDOW_S)
        while self._seen and now - self._seen[0] > window:
            self._seen.popleft()
        while self._calls and now - self._calls[0][0] > window:
            self._calls.popleft()
        # Crossings too recent to have a result yet are not evidence.
        settle = float(_c.CROSSING_VISION_EVENT_END_WAIT_S) + float(
            _c.CROSSING_VISION_TIMEOUT_S
        )
        seen = sum(1 for t in self._seen if now - t >= settle)
        ok = sum(1 for _t, o in self._calls if o == OUTCOME_OK)
        if (
            not self._zero_latched
            and seen >= int(_c.CROSSING_VISION_ZERO_MIN_CROSSINGS)
            and ok == 0
        ):
            self._zero_latched = True
            await fire_stuck_signal(
                self.hass,
                "crossing_vision_zero",
                ("house",),
                f"Crossing vision (shadow) saw {seen} door crossings in the "
                f"last {int(window // 3600)} h and got no usable count back.",
                remedy=(
                    "Check the llmvision OpenAI entry and the Frigate clip "
                    "proxy; the Outside: Open Tracks attributes "
                    "crossing_vision_today / crossing_vision_last show the "
                    "outcomes."
                ),
                severity="HIGH",
            )
        calls = len(self._calls)
        failed = sum(1 for _t, o in self._calls if o in FAILED_CALL_OUTCOMES)
        over = (
            calls >= int(_c.CROSSING_VISION_ERROR_MIN_CALLS)
            and failed / calls > float(_c.CROSSING_VISION_ERROR_RATE_MAX)
        )
        if not over:
            self._errors_latched = False
        elif not self._errors_latched:
            self._errors_latched = True
            await fire_stuck_signal(
                self.hass,
                "crossing_vision_errors",
                ("house",),
                f"Crossing vision (shadow): {failed} of {calls} calls in the "
                f"last {int(window // 3600)} h failed (error, timeout, "
                f"refused or unparseable).",
                remedy="See crossing_vision_last on Outside: Open Tracks.",
            )

    # ---- diagnostics ----------------------------------------------------
    def diag_status(self) -> dict[str, Any]:
        """Display-only attributes for the Outside: Open Tracks sensor."""
        self._roll_day()
        last = dict(self._last) if self._last else None
        if last is not None:
            try:
                at = dt_util.parse_datetime(str(last.get("at")))
                last["age_s"] = (
                    int((dt_util.utcnow() - at).total_seconds()) if at else None
                )
            except Exception:  # noqa: BLE001
                last["age_s"] = None
        return {
            "crossing_vision_today": dict(self._today),
            "crossing_vision_last": last,
        }


# ---------------------------------------------------------------------------
# Integration-entry wiring
# ---------------------------------------------------------------------------
async def async_setup_crossing_vision(hass: HomeAssistant) -> None:
    """Create the producer (integration entry setup, after the Frigate
    ingress and the exterior track linker). A prior instance (partial reload)
    is torn down first. Any failure leaves the key absent; nothing else
    depends on it."""
    await async_teardown_crossing_vision(hass)
    cv: CrossingVisionShadow | None = None
    try:
        cv = CrossingVisionShadow(hass)
        await cv.async_setup()
        hass.data.setdefault(DOMAIN, {})[_c.CROSSING_VISION_HASS_KEY] = cv
    except Exception:  # noqa: BLE001
        # Review B3: a partial setup (bus listener registered, consumer or
        # interval failed) must not leak the listener for the process life.
        if cv is not None:
            try:
                await cv.async_teardown()
            except Exception:  # noqa: BLE001
                pass
        _LOGGER.error("Crossing vision shadow setup failed", exc_info=True)


async def async_teardown_crossing_vision(hass: HomeAssistant) -> None:
    """Pop and tear down the producer (safe if absent). Called from the
    integration entry unload BEFORE the Frigate ingress teardown."""
    try:
        cv = hass.data.get(DOMAIN, {}).pop(_c.CROSSING_VISION_HASS_KEY, None)
    except Exception:  # noqa: BLE001
        return
    if cv is None:
        return
    try:
        await cv.async_teardown()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Crossing vision teardown raised", exc_info=True)
