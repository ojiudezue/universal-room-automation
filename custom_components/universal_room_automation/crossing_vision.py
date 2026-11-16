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
import re
from collections import Counter, OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import const as _c
from . import crossing_ledger as _cl
from .const import DOMAIN
from .domain_coordinators import camera_stream_health as _csh

_LOGGER = logging.getLogger(__name__)

# Pseudo-holder returned by ``_held_inputs`` while no Tier-1 map is
# available (no substrate, torn down, or its getter failed): the empty-house
# anchor is blocked, because unknown is not empty (ruling Q2).
TIER1_MAP_UNAVAILABLE = "tier1_map_unavailable"

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

# P3-D5: the outcomes of a MADE llmvision call (one row each, ``ended_at`` =
# call time). The restart rehydration counts exactly these.
CALL_OUTCOMES = (
    OUTCOME_OK, OUTCOME_BLANK, OUTCOME_ERROR, OUTCOME_TIMEOUT,
    OUTCOME_UNPARSEABLE, OUTCOME_REFUSED,
)

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
# Review D-L3: secrets an llmvision error text can carry (a request URL's
# `key=` query value, an `sk-` style API key, a bearer token).
_SECRET_PATTERNS = (
    (re.compile(r"(key=)[^&\s]*", re.IGNORECASE), r"\1[redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]+"), "sk-[redacted]"),
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1[redacted]"),
)


def scrub_error_text(text: str) -> str:
    """Redact secrets from an error text before it is stored (P3-D1)."""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


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
    # P2-D3 ledger: every member crossing (primary first) and whether the
    # request's ledger term(s) were applied (exactly once per request).
    members: list[dict[str, Any]] = field(default_factory=list)
    term_done: bool = False


def vision_provider_id(hass: Any) -> str | None:
    """The llmvision entry id to send as ``provider`` (P2-D1, read fresh;
    also used by interior vision, VISION-INTERIOR-SIGHTINGS-1 ship 2): the
    rung-2 option ``CONF_CROSSING_VISION_PROVIDER_ID`` when set; when empty,
    the rung-1 install default ``CROSSING_VISION_PROVIDER_ID`` (review
    A-HIGH-3). Either id is used only when it is an llmvision config entry
    on THIS install (portability); otherwise None, and the adapter falls
    back to the perimeter's provider."""
    from .perimeter_enrichment import _get_integration_config  # noqa: PLC0415

    try:
        raw = _get_integration_config(hass).get(_c.CONF_CROSSING_VISION_PROVIDER_ID)
    except Exception:  # noqa: BLE001
        raw = None
    pid = str(raw or "").strip() or str(_c.CROSSING_VISION_PROVIDER_ID or "").strip()
    if not pid:
        return None
    try:
        entry = hass.config_entries.async_get_entry(pid)
    except Exception:  # noqa: BLE001
        return None
    if entry is None or getattr(entry, "domain", None) != "llmvision":
        return None
    return pid


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
        # Daily cap (reset at local midnight; plan rev 2 F7). P3-D5: from
        # setup until today's call rows are counted, the counter sits AT the
        # cap (``_cap_hold``); a failed rehydration keeps it there until the
        # next local midnight (``_roll_day`` clears it).
        self._day: Any = None
        self._calls_today = 0
        self._cap_hold = False
        self._cap_rehydrate_task: asyncio.Task | None = None
        self._cap_rehydrate_state = "not_started"
        self._cap_rehydrate_failed = 0
        self._today: dict[str, int] = {}
        self._last: dict[str, Any] | None = None
        # Trip-wire windows: (epoch_s, kind) samples, pruned to the window.
        self._seen: deque[float] = deque()
        self._calls: deque[tuple[float, str]] = deque()
        self._zero_latched = False
        self._errors_latched = False
        # P2-D2/D3: the house crossing ledger (RAM; boot = unknown, a
        # restart never restores known). Knobs read once here (rung 1).
        self._ledger = _cl.CrossingLedger(
            empty_reset_s=float(_c.CROSSING_VISION_LEDGER_EMPTY_RESET_S),
            eval_s=float(_c.CROSSING_VISION_LEDGER_EVAL_S),
            reconcile_lead_s=float(_c.CROSSING_VISION_LEDGER_RECONCILE_LEAD_S),
            reconcile_lag_s=float(_c.CROSSING_VISION_LEDGER_RECONCILE_LAG_S),
            reconcile_delay_s=float(_c.CROSSING_VISION_TIMEOUT_S)
            + float(_c.CROSSING_VISION_EVENT_END_WAIT_S),
            arrival_before_s=float(_c.CROSSING_VISION_GO_ARRIVAL_WINDOW_BEFORE_S),
            arrival_after_s=float(_c.CROSSING_VISION_GO_ARRIVAL_WINDOW_AFTER_S),
            stuck_s=float(_c.CROSSING_VISION_LEDGER_STUCK_S),
            anchor_zero_s=float(_c.CROSSING_VISION_LEDGER_ANCHOR_ZERO_S),
            setup_ts=self._epoch(),
            anchor_needs_no_hold=bool(_c.CROSSING_VISION_LEDGER_ANCHOR_NEEDS_NO_HOLD),
        )
        self._ledger_events: list[_cl.LedgerEvent] = []
        # P2-D3 held inputs: RAM last-known-good map (entity -> "on"/"off",
        # never persisted) and the holders seen since the last anchor (for
        # the anchor-zero page; dead ones named first).
        self._last_good: dict[str, str] = {}
        self._holder_counts: Counter[str] = Counter()
        self._holder_dead: set[str] = set()
        # Tier-1 entities that never existed in HA (no registry entry, no
        # state): ignored for the held set, shown on the diagnostics, one
        # WARNING per entity per lifetime.
        self._tier1_missing_now: tuple[str, ...] = ()
        self._tier1_missing_logged: set[str] = set()
        # P3-D8: live `on` inputs that did not hold the last sample because
        # their room excludes them as stuck (diagnostics + anchor-zero page).
        self._held_ignored_stuck: tuple[str, ...] = ()
        self._ledger_was_enabled = False
        self._ledger_day: Any = None
        self._reconcile_timers: dict[str, Callable[[], None]] = {}
        # CD3 trip-wires (RAM, a restart starts them empty).
        # Per-crossing count disagreement (agreement case B / C on an `ok`
        # row): (epoch, door group) samples, latched per group.
        self._disagree: deque[tuple[float, str]] = deque(maxlen=4096)
        self._disagree_latched: set[str] = set()
        # F-LEAD regression inputs measurable from the ledger now: bar a
        # (independent anchor residues) and bar e (known share of samples).
        self._anchor_residues: deque[tuple[float, int]] = deque(maxlen=4096)
        self._known_samples: deque[tuple[float, bool]] = deque(maxlen=40320)
        self._flead_latched = False
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

    def _calls_counted(self) -> int:
        """Calls counted against today's cap. While the setup rehydration
        has not landed (or failed twice today) the counter reads the cap
        (P3-D5): no call is made, crossings are recorded ``skipped_cap``."""
        if self._cap_hold:
            return max(self._calls_today, self.daily_cap())
        return self._calls_today

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
        # P2-D3 ledger feeds: the anchor sampler, Tier-1 room rising edges
        # (the substrate's single-writer dispatch) and resident departures
        # (the residency producer's records). All unsubscribed in teardown.
        from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
            async_dispatcher_connect,
        )

        from .domain_coordinators.signals import (  # noqa: PLC0415
            SIGNAL_SUBSTRATE_KIND_CHANGED,
        )

        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._on_ledger_eval,
                timedelta(seconds=max(1, int(_c.CROSSING_VISION_LEDGER_EVAL_S))),
            )
        )
        self._unsubs.append(
            async_dispatcher_connect(
                self.hass, SIGNAL_SUBSTRATE_KIND_CHANGED, self._on_substrate_edge,
            )
        )
        # Ship 3a D2: the F1 edge subscription (G1), all kinds, so every
        # residency record is delivered at the same time and in the same order
        # as the former raw SIGNAL_RESIDENCY_EVENT connect.
        from .domain_coordinators.residency import (  # noqa: PLC0415
            EDGE_KINDS,
            subscribe_person_edges,
        )

        self._unsubs.append(
            subscribe_person_edges(self.hass, self._on_residency_event, kinds=EDGE_KINDS)
        )
        # P3-D5: the bus listener above is live NOW with the counter at the
        # cap; today's call rows are counted in a tracked background task.
        self._cap_hold = True
        self._cap_rehydrate_state = "pending"
        try:
            task = self.hass.async_create_background_task(
                self._rehydrate_cap(), "crossing_vision_cap_rehydrate",
            )
        except Exception:  # noqa: BLE001 - counter stays at the cap today
            _LOGGER.debug("crossing_vision: rehydrate task failed", exc_info=True)
            self._cap_rehydrate_state = "failed"
            self._cap_rehydrate_failed += 1
        else:
            self._cap_rehydrate_task = task
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def async_teardown(self) -> None:
        """Latch first, then unsubscribe, cancel timers, gather in-flight
        tasks with a bound (the transit_validator outcome-log pattern).
        Buffered ledger rows are handed to a tracked write first, so the
        bounded gather covers them."""
        self._flush_ledger_events()
        self._torn_down = True
        task = self._cap_rehydrate_task
        if task is not None and not task.done():
            task.cancel()
        for unsub in list(self._reconcile_timers.values()):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._reconcile_timers.clear()
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
            # P3-D5: a new local day ends any cap hold. This process has run
            # since before midnight, so no earlier process made a call today;
            # a rehydration still pending for the OLD day is discarded (it
            # applies only to the day it counted).
            self._cap_hold = False
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
        # P2-D3: and the ledger goes unknown (no term).
        if not self._enabled():
            self._ledger_disabled()
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
        member = {
            "crossing_key": crossing_key, "direction": direction,
            "camera_peak_count": crossing["camera_peak_count"], "e_ts": e_epoch,
        }
        self._prune_requests(e_epoch)

        # 1. Cluster: any request (open or completed) of this door group
        #    within CLUSTER_S of E.
        cluster_s = float(_c.CROSSING_VISION_CLUSTER_S)
        for req in self._requests:
            if req.group_key == group_key and abs(
                req.e_ts.timestamp() - e_epoch
            ) <= cluster_s:
                self._join_cluster(req, crossing, member)
                return

        # 2. Match a Frigate person event on a door-group camera.
        match = self._match_event(members, e_epoch)
        if match is None:
            self._record(crossing, OUTCOME_NO_EVENT)
            self._ledger_terms([member], OUTCOME_NO_EVENT, None)
            return
        prior = match.get("analysed_by")
        if prior is not None:
            primary = next((r for r in self._requests if r.key == prior), None)
            if primary is not None:
                self._join_cluster(primary, crossing, member)
            else:
                self._record(crossing, OUTCOME_CLUSTERED, primary_crossing_key=prior,
                             event=match)
                # The primary left the request ring: this member's own
                # camera term (its primary's term was already applied).
                self._ledger_terms([member], OUTCOME_CLUSTERED, None)
            return

        # 3. Schedule-time gates (cap, concurrency). Off was handled above.
        #    A `calling` request is already in _calls_today, so only the
        #    `waiting` ones are added (reviews A1/B4: no double count).
        if self._calls_counted() + self._waiting() >= self.daily_cap():
            self._record(crossing, OUTCOME_SKIPPED_CAP, event=match)
            self._ledger_terms([member], OUTCOME_SKIPPED_CAP, None)
            return
        if self._pending() >= max(0, int(_c.CROSSING_VISION_MAX_CONCURRENT)):
            self._record(crossing, OUTCOME_SKIPPED_BUSY, event=match)
            self._ledger_terms([member], OUTCOME_SKIPPED_BUSY, None)
            return

        req = _Request(
            key=crossing_key, group_key=group_key, door_group=door_group,
            members_stems=members, e_ts=e_ts, event=match, crossing=crossing,
            crossing_keys=[crossing_key], members=[member],
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

    def _join_cluster(
        self, primary: _Request, crossing: dict[str, Any],
        member: dict[str, Any] | None = None,
    ) -> None:
        if crossing["crossing_key"] not in primary.crossing_keys:
            primary.crossing_keys.append(crossing["crossing_key"])
        self._record(
            crossing, OUTCOME_CLUSTERED,
            primary_crossing_key=primary.key, event=primary.event,
        )
        if member is None:
            return
        if not primary.term_done:
            # Folded into the primary's term(s) when its outcome lands.
            primary.members.append(member)
            return
        # Late joiner (the primary's term is already applied): same
        # direction = counted by the primary's count, no term; a different
        # direction gets its own camera term.
        prim_dir = primary.members[0]["direction"] if primary.members else None
        if member["direction"] != prim_dir:
            self._ledger_terms([member], OUTCOME_CLUSTERED, None)

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
        """The llmvision entry id to send as ``provider`` (P2-D1, read
        fresh): the rung-2 option ``CONF_CROSSING_VISION_PROVIDER_ID`` when
        set; when empty, the rung-1 install default
        ``CROSSING_VISION_PROVIDER_ID`` (review A-HIGH-3). Either id is used
        only when it is an llmvision config entry on THIS install
        (portability: another house has other entry ids); otherwise None,
        and the adapter falls back to the perimeter's provider."""
        return vision_provider_id(self.hass)

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
            # no row (P2-D3: no term, ledger unknown).
            if self._torn_down or not self._enabled():
                req.term_done = True
                if not self._torn_down:
                    self._ledger_disabled()
                return
            if self._calls_counted() >= self.daily_cap():
                self._record(req.crossing, OUTCOME_SKIPPED_CAP, event=req.event,
                             crossing_keys=req.crossing_keys)
                self._request_terms(req, OUTCOME_SKIPPED_CAP, None)
                return
            video_file, event_id = self._clip_reference(req.event)
            if video_file is None and event_id is None:
                self._record(req.crossing, OUTCOME_NO_CLIP_URL, event=req.event,
                             crossing_keys=req.crossing_keys)
                self._request_terms(req, OUTCOME_NO_CLIP_URL, None)
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
                req.term_done = True
                self._ledger_disabled()
                return
            status = reply.get("status")
            if status == CROSSING_CALL_RESPONSE:
                parsed = parse_vision_response(
                    reply.get("result"), int(_c.CROSSING_VISION_DESC_MAX_CHARS),
                )
            elif status == CROSSING_CALL_TIMEOUT:
                parsed = {"outcome": OUTCOME_TIMEOUT}
            else:
                # P3-D1: keep llmvision's error text for the row.
                parsed = {"outcome": OUTCOME_ERROR, "error": reply.get("error")}
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
            self._request_terms(req, outcome, parsed.get("people_count"))
        except Exception:  # noqa: BLE001 — shadow: never raise
            _LOGGER.debug("crossing_vision: run failed", exc_info=True)
        finally:
            req.status = "done"
            # Any path that recorded no term (an unexpected exception, a
            # cancel) still gives the crossing its camera term.
            if not req.term_done and not self._torn_down:
                try:
                    self._request_terms(req, OUTCOME_ERROR, None)
                except Exception:  # noqa: BLE001
                    req.term_done = True

    # ---- cap rehydration (P3-D5) -----------------------------------------
    async def _count_today_calls(self, day: Any) -> tuple[int, bool]:
        """Today's call rows (by ``ended_at`` = call time) over the local
        day ``day`` as UTC bounds rendered like the writer's ``ended_at``."""
        database = self._domain_data().get("database")
        if database is None:
            return 0, False
        start = dt_util.as_utc(dt_util.start_of_local_day(day))
        end = dt_util.as_utc(dt_util.start_of_local_day(day + timedelta(days=1)))
        return await database.count_memory_episodes_by_type_ended_between(
            _c.CROSSING_VISION_EPISODE_TYPE, start.isoformat(), end.isoformat(),
            CALL_OUTCOMES,
        )

    async def _rehydrate_cap(self) -> None:
        """Set the counter from today's call rows: one try bounded by
        ``CAP_REHYDRATE_TIMEOUT_S``, one retry after ``_RETRY_S``. Both
        failing: the counter stays at the cap until local midnight, counted
        and paged LOW. Cancelled by teardown."""
        timeout = float(_c.CROSSING_VISION_CAP_REHYDRATE_TIMEOUT_S)
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(float(_c.CROSSING_VISION_CAP_REHYDRATE_RETRY_S))
            if self._torn_down:
                return
            self._roll_day()
            day = self._day
            try:
                count, ok = await asyncio.wait_for(
                    self._count_today_calls(day), timeout=timeout,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - timeout or read error
                count, ok = 0, False
            if self._torn_down:
                return
            if ok:
                self._roll_day()
                if self._day == day:
                    self._calls_today = max(self._calls_today, int(count))
                    self._today["calls"] = max(
                        self._today.get("calls", 0), int(count),
                    )
                    self._cap_hold = False
                self._cap_rehydrate_state = "ok"
                return
        self._cap_rehydrate_state = "failed"
        self._cap_rehydrate_failed += 1
        from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
            fire_stuck_signal,
        )

        await fire_stuck_signal(
            self.hass,
            "crossing_vision_cap_rehydrate_failed",
            ("house",),
            "Crossing vision could not count today's calls after a restart "
            "(two tries); no vision calls until local midnight.",
            remedy=(
                "Check the URA database (memory_episodes reads). Crossings are "
                "still recorded as skipped_cap; the cap resets at midnight."
            ),
            severity="LOW",
        )

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
        if outcome == OUTCOME_ERROR:
            # P3-D1: error rows only (no key on any other row).
            err = vision.get("error")
            attrs["error"] = (
                scrub_error_text(str(err))[
                    : max(0, int(_c.CROSSING_VISION_ERROR_TEXT_MAX_CHARS))
                ]
                if err is not None else None
            )
        if outcome == OUTCOME_OK and attrs["agreement_case"] in (
            CASE_VISION_HIGHER, CASE_CAMERA_HIGHER,
        ):
            group = crossing.get("door_group") or crossing["crossing_key"].split("@", 1)[0]
            self._disagree.append((self._epoch(), str(group)))
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

    # ---- ledger (P2-D3) --------------------------------------------------
    # The ledger reaches F2 ONLY through ``census_tick`` (INV-SHADOW): the
    # census calls it once per evaluation and owns F2. Every other output
    # here is a ``crossing_vision_ledger`` row, a diagnostic attribute or a
    # trip-wire page.
    def _ledger_disabled(self) -> None:
        """Switch off / kill / cap 0: the ledger goes unknown (INV-OFF)."""
        if not self.switch_on():
            reason = "switch_off"
        elif bool(_c.LLMVISION_ENRICHMENT_KILL):
            reason = "kill"
        else:
            reason = "cap_zero"
        if (
            self._ledger.state != _cl.STATE_UNKNOWN
            or self._ledger.unknown_reason != reason
        ):
            self._ledger.set_unknown(reason)
        self._ledger_was_enabled = False

    def _ledger_enabled_now(self) -> bool:
        """Gate every ledger feed on the producer gates (re-read each call).
        Disabled -> unknown; the enable edge restarts the anchor-zero clock."""
        if not self._enabled():
            self._ledger_disabled()
            return False
        if not self._ledger_was_enabled:
            self._ledger_was_enabled = True
            self._ledger.rebase(self._epoch())
            self._holder_counts.clear()
            self._holder_dead.clear()
        return True

    @staticmethod
    def _ledger_fallback() -> str:
        fb = str(_c.CROSSING_VISION_LEDGER_FALLBACK)
        return fb if fb in (_cl.FALLBACK_CAMERA, _cl.FALLBACK_SKIP) else _cl.FALLBACK_CAMERA

    def _ledger_terms(
        self, members: list[dict[str, Any]], outcome: str | None, people: Any,
    ) -> None:
        """Apply the term(s) for these member crossings (P2-D2 3)."""
        if self._torn_down or not self._ledger_enabled_now():
            return
        now = self._epoch()
        for t in _cl.cluster_terms(members, outcome, people, self._ledger_fallback()):
            ev = self._ledger.apply_term(
                direction=t["direction"], n=t["n"], term_source=t["term_source"],
                crossing_key=t["crossing_key"], e_ts=t["e_ts"], now=now,
            )
            if ev is not None:
                self._ledger_events.append(ev)

    def _request_terms(self, req: _Request, outcome: str | None, people: Any) -> None:
        """A request's term(s), exactly once, with all its cluster members."""
        if req.term_done:
            return
        req.term_done = True
        self._ledger_terms(list(req.members), outcome, people)

    def census_tick(
        self, *, resident_term: Any, camera_bodies: Any, camera_input_dark: Any,
    ) -> tuple[int | None, bool]:
        """The ONE F2 hand-off (called by ``PersonCensus`` once per
        evaluation): ``(guest_vis | None, healthy)``. Off / torn down ->
        ``(None, False)`` (case D at the census)."""
        if self._torn_down or not self._ledger_enabled_now():
            return None, False
        result = self._ledger.census_tick(
            self._epoch(), resident_term, camera_bodies, camera_input_dark,
        )
        # Arrival-floor lifts (P2-D2 step 4): one ledger row each, written
        # with the next eval tick's batch.
        self._ledger_events.extend(self._ledger.drain_events())
        return result

    @property
    def ledger_state(self) -> str:
        return self._ledger.state

    def vision_status(self, healthy: bool) -> str:
        """Awareness-entity attribute: switch_off / unknown_ledger / dark / ok."""
        if not self._enabled():
            return "switch_off"
        if self._ledger.state != _cl.STATE_KNOWN:
            return "unknown_ledger"
        if not healthy:
            return "dark"
        return "ok"

    def _held_inputs(self) -> tuple[set[str], set[str]]:
        """The held Tier-1 inputs this sample (P2-D2 step 2): every entity
        in the substrate's Tier-1 map, its ``hass.states`` reading, the RAM
        last-known-good map, and the camera input stream health view
        (contract G7: ``camera_stream_health.entity_stream_view``, whose input
        route is ``input_stream_view`` and whose fallback is the input's own
        camera). Any non-None view (HELD or RELEASED) marks the input
        stream-dead; RELEASED is never "off" for the anchor
        (INV-MISSING-NOT-ZERO). Returns ``(held, dead_held)``.

        No substrate (or its getter fails) -> no Tier-1 map -> the anchor is
        BLOCKED: unknown is not empty (planner ruling Q2). The pseudo-holder
        ``TIER1_MAP_UNAVAILABLE`` is returned as held (and dead, so the
        anchor-zero page names it first). A live substrate with an empty map
        is an available map with nothing to hold.

        A Tier-1 entity with no entity-registry entry AND no state never
        existed in HA (e.g. a stale config entry left after a device rename):
        it is ignored for the held set, listed on the diagnostics
        (``tier1_not_in_registry``) and logged once per entity. A registry
        read error ignores nothing."""
        data = self._domain_data()
        substrate = data.get("occupancy_substrate")
        eids: Any = None
        if substrate is not None and not getattr(substrate, "_is_torn_down", False):
            try:
                eids = frozenset(substrate.tier1_entity_ids())
            except Exception:  # noqa: BLE001
                eids = None
        if eids is None:
            self._tier1_missing_now = ()
            self._held_ignored_stuck = ()
            return {TIER1_MAP_UNAVAILABLE}, {TIER1_MAP_UNAVAILABLE}
        try:
            from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

            registry = er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            registry = None
        missing: list[str] = []
        readings: dict[str, tuple[Any, Any]] = {}
        ignore_stuck = bool(_c.CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK)
        stuck_ignored: set[str] = set()
        for eid in eids:
            try:
                st = self.hass.states.get(eid)
            except Exception:  # noqa: BLE001
                st = None
            if st is None and registry is not None:
                try:
                    never_existed = registry.async_get(eid) is None
                except Exception:  # noqa: BLE001
                    never_existed = False
                if never_existed:
                    missing.append(str(eid))
                    if str(eid) not in self._tier1_missing_logged:
                        self._tier1_missing_logged.add(str(eid))
                        _LOGGER.warning(
                            "crossing ledger: Tier-1 input %s is not in the "
                            "entity registry and has no state; ignored for the "
                            "empty-house anchor (fix the room's sensor list)",
                            eid,
                        )
                    continue
            state = getattr(st, "state", None) if st is not None else None
            try:
                view = _csh.entity_stream_view(self.hass, str(eid))
            except Exception:  # noqa: BLE001 - no opinion
                view = None
            readings[str(eid)] = (state, True if view is not None else None)
            # P3-D8: a LIVE `on` input (no stream view) that its room
            # excludes as stuck does not hold. A dead input (non on/off state
            # or any stream view) is never released here: it holds.
            if ignore_stuck and state == "on" and view is None:
                try:
                    if _csh.input_room_stuck_excluded(self.hass, str(eid)):
                        stuck_ignored.add(str(eid))
                except Exception:  # noqa: BLE001 - no opinion: it holds
                    pass
        self._tier1_missing_now = tuple(sorted(missing))
        self._held_ignored_stuck = tuple(sorted(stuck_ignored))
        # classify_held still sees the ignored inputs, so their `on` stays
        # the last known-good reading (if they later go dead, they hold).
        held, dead_held = _cl.classify_held(readings, self._last_good)
        return held - stuck_ignored, dead_held - stuck_ignored

    def _holders_text(self) -> str:
        """The holders seen most since the last anchor, dead ones first."""
        if not self._holder_counts:
            return ""
        ranked = sorted(
            self._holder_counts.items(),
            key=lambda kv: (kv[0] not in self._holder_dead, -kv[1], kv[0]),
        )
        names = [
            f"{eid} (dead)" if eid in self._holder_dead else eid
            for eid, _n in ranked[:5]
        ]
        return ", ".join(names)

    @callback
    def _on_substrate_edge(self, room_name: Any, kind: Any, new_state: Any) -> None:
        """Tier-1 room rising edge (OccupancySubstrate single-writer
        dispatch): catches a pulse shorter than the eval interval. Levels
        reach the anchor as the held set (``_held_inputs``)."""
        del room_name, kind
        if self._torn_down or new_state is not True:
            return
        self._ledger.note_rising_edge(self._epoch())

    @callback
    def _on_residency_event(self, record: Any) -> None:
        """A resident departure edge -> one tracked reconcile timer per
        person (superseded per person, cancelled in teardown; a restart
        drops pending)."""
        from .domain_coordinators.residency import KIND_DEPARTURE  # noqa: PLC0415

        if self._torn_down or getattr(record, "kind", None) != KIND_DEPARTURE:
            return
        if not self._ledger_enabled_now():
            return
        try:
            person = str(record.person)
            t_e = float(record.edge_ts)
        except (AttributeError, TypeError, ValueError):
            return
        old = self._reconcile_timers.pop(person, None)
        if old is not None:
            try:
                old()
            except Exception:  # noqa: BLE001
                pass
        due = self._ledger.note_departure(person, t_e)
        if due is None:
            return
        from homeassistant.helpers.event import async_call_later  # noqa: PLC0415

        @callback
        def _judge(_now: Any) -> None:
            self._reconcile_timers.pop(person, None)
            if self._torn_down:
                return
            ev = self._ledger.judge_reconcile(person, self._epoch())
            if ev is not None:
                self._ledger_events.append(ev)

        self._reconcile_timers[person] = async_call_later(
            self.hass, max(0.0, due - self._epoch()), _judge,
        )

    def _roll_ledger_day(self) -> None:
        day = dt_util.now().date()
        if day != self._ledger_day:
            if self._ledger_day is not None:
                self._ledger.reset_daily_counters()
            self._ledger_day = day

    @callback
    def _on_ledger_eval(self, _now: Any) -> None:
        """Anchor sample + ledger trip-wires + one batched row write."""
        if self._torn_down:
            return
        try:
            self._roll_ledger_day()
            if self._ledger_enabled_now():
                now = self._epoch()
                held, dead_held = self._held_inputs()
                self._holder_counts.update(held)
                self._holder_dead |= dead_held
                evs = self._ledger.evaluate(now, held)
                self._ledger_events.extend(evs)
                for ev in evs:
                    if ev.kind == _cl.KIND_ANCHOR:
                        self._holder_counts.clear()
                        self._holder_dead.clear()
                    if ev.kind == _cl.KIND_ANCHOR and ev.independent and ev.residue is not None:
                        self._anchor_residues.append((now, int(ev.residue)))
                self._known_samples.append((now, self._ledger.state == _cl.STATE_KNOWN))
                if self._ledger.stuck_due(now):
                    self._spawn(self._page_ledger_stuck())
                if self._ledger.anchor_zero_due(now):
                    self._spawn(self._page_ledger_anchor_zero())
        except Exception:  # noqa: BLE001 — shadow: never raise
            _LOGGER.debug("crossing_vision: ledger eval failed", exc_info=True)
        self._flush_ledger_events()

    def _flush_ledger_events(self) -> None:
        """Batched write: every buffered ledger event in ONE tracked task
        (one ``crossing_vision_ledger`` row each)."""
        if self._torn_down or not self._ledger_events:
            return
        events, self._ledger_events = self._ledger_events, []
        database = self._domain_data().get("database")
        if database is None:
            return

        def _iso(ts: Any) -> str | None:
            try:
                return dt_util.utc_from_timestamp(float(ts)).isoformat()
            except (TypeError, ValueError):
                return None

        async def _write() -> None:
            for ev in events:
                ref = ev.crossing_key or ev.person or ""
                try:
                    await database.log_memory_episode(
                        node_id=f"ledger:{ev.kind}:{ref}@{ev.at}",
                        episode_type=_c.CROSSING_VISION_LEDGER_EPISODE_TYPE,
                        attrs=ev.as_dict(),
                        source_ref=ev.crossing_key,
                        started_at=_iso(ev.e_ts if ev.e_ts is not None else ev.at),
                        ended_at=_iso(ev.at),
                        dedup_source_ref=False,
                        window_dedup=False,
                    )
                except Exception:  # noqa: BLE001 — observational only
                    _LOGGER.debug("crossing_vision ledger row failed", exc_info=True)

        self._spawn(_write())

    async def _page_ledger_stuck(self) -> None:
        from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
            fire_stuck_signal,
        )

        hours = int(float(_c.CROSSING_VISION_LEDGER_STUCK_S) // 3600)
        await fire_stuck_signal(
            self.hass,
            "crossing_ledger_stuck",
            ("house",),
            f"Crossing ledger has counted extra people (guests {self._ledger.guest_vis()}) "
            f"for {hours} h while every camera saw nobody and no room sensor fired.",
            remedy=(
                "The empty-house anchor is blocked (an entry-term stream or a "
                "missed exit). See crossing_ledger on Outside: Open Tracks; "
                "turning the crossing vision switch off and on resets it."
            ),
            severity="HIGH",
        )

    async def _page_ledger_anchor_zero(self) -> None:
        from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
            fire_stuck_signal,
        )

        hours = int(float(_c.CROSSING_VISION_LEDGER_ANCHOR_ZERO_S) // 3600)
        holders = self._holders_text()
        held_txt = (
            f" Inputs holding it: {holders}." if holders else ""
        )
        if self._held_ignored_stuck:
            held_txt += (
                " Ignored as stuck (room-excluded): "
                f"{', '.join(self._held_ignored_stuck[:5])}."
            )
        await fire_stuck_signal(
            self.hass,
            "crossing_ledger_anchor_zero",
            ("house",),
            f"Crossing ledger: no empty-house anchor in {hours} h, so its "
            f"count can drift.{held_txt}",
            remedy=(
                "Normal while someone is always home. A dead input is faulty "
                "equipment: fix it first. Otherwise check the interior "
                "camera counts and the room sensors named."
            ),
            severity="LOW",
        )

    def ledger_diag(self) -> dict[str, Any]:
        snap = self._ledger.snapshot()
        last = snap.get("last_anchor")
        if last is not None:
            try:
                snap["last_anchor"] = dt_util.utc_from_timestamp(float(last)).isoformat()
            except (TypeError, ValueError):
                snap["last_anchor"] = None
        snap["tier1_not_in_registry"] = list(self._tier1_missing_now)
        snap["tier1_not_in_registry_count"] = len(self._tier1_missing_now)
        snap["held_ignored_stuck"] = list(self._held_ignored_stuck)
        snap["held_ignored_stuck_count"] = len(self._held_ignored_stuck)
        return snap

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
        await self._evaluate_disagree(now)
        await self._evaluate_flead_regression(now)

    async def _evaluate_disagree(self, now: float) -> None:
        """CD3 ``crossing_vision_disagree``: vision and camera disagree on the
        count (case B or C) at least DISAGREE_PERSIST_N times on one door
        group in the window -> one page per group, re-armed when the group's
        count falls back under the bar. PERSIST_N 0 = off."""
        from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
            fire_stuck_signal,
        )

        bar = int(_c.CROSSING_VISION_DISAGREE_PERSIST_N)
        window = float(_c.CROSSING_VISION_DISAGREE_WINDOW_S)
        while self._disagree and now - self._disagree[0][0] > window:
            self._disagree.popleft()
        if bar <= 0:
            return
        counts: dict[str, int] = {}
        for _t, group in self._disagree:
            counts[group] = counts.get(group, 0) + 1
        for group in list(self._disagree_latched):
            if counts.get(group, 0) < bar:
                self._disagree_latched.discard(group)
        for group, n in sorted(counts.items()):
            if n < bar or group in self._disagree_latched:
                continue
            self._disagree_latched.add(group)
            await fire_stuck_signal(
                self.hass,
                "crossing_vision_disagree",
                (group,),
                f"Crossing vision and the camera count disagreed on {n} "
                f"crossings at door {group} in the last "
                f"{int(window // 3600)} h.",
                remedy=(
                    "Check the door camera's person count and the Frigate "
                    "event match; crossing_vision_last shows the latest case."
                ),
                # MEDIUM reaches no channel under the live NM config
                # (_stuck_signal_nm.py:178-182; review B-M1).
                severity="HIGH",
            )

    def flead_regression(self, now: float) -> list[str]:
        """CD3: the F-LEAD numbers measurable from the ledger in RAM that
        are below their bar over CROSSING_VISION_GO_REGRESSION_DAYS: bar a
        (drift, independent anchors) and bar e (known share). Bars b, d and
        the graded numbers need the scorer / grading (P2-D6 / P2-D10)."""
        window = float(_c.CROSSING_VISION_GO_REGRESSION_DAYS) * 86400.0
        while self._anchor_residues and now - self._anchor_residues[0][0] > window:
            self._anchor_residues.popleft()
        while self._known_samples and now - self._known_samples[0][0] > window:
            self._known_samples.popleft()
        failing: list[str] = []
        residues = [res for _t, res in self._anchor_residues]
        if len(residues) >= int(_c.CROSSING_VISION_GO_MIN_ANCHORS):
            zero_share = sum(1 for x in residues if x == 0) / len(residues)
            if zero_share < float(_c.CROSSING_VISION_GO_DRIFT_ZERO_SHARE) or any(
                abs(x) > int(_c.CROSSING_VISION_GO_DRIFT_MAX_ABS) for x in residues
            ):
                failing.append("a_drift")
        span_needed = float(_c.CROSSING_VISION_GO_WINDOW_DAYS) * 86400.0
        if self._known_samples and now - self._known_samples[0][0] >= span_needed:
            known = sum(1 for _t, k in self._known_samples if k)
            if known / len(self._known_samples) < float(_c.CROSSING_VISION_GO_KNOWN_SHARE_MIN):
                failing.append("e_known")
        return failing

    async def _evaluate_flead_regression(self, now: float) -> None:
        """After F-LEAD only: a regressed bar pages ONCE (HIGH, "revert
        F-LEAD"); re-armed when every measurable bar holds again."""
        if not bool(_c.CROSSING_VISION_AWARENESS_VISION_LEADS):
            self._flead_latched = False
            return
        failing = self.flead_regression(now)
        if not failing:
            self._flead_latched = False
            return
        if self._flead_latched:
            return
        self._flead_latched = True
        from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
            fire_stuck_signal,
        )

        await fire_stuck_signal(
            self.hass,
            "crossing_vision_flead_regression",
            ("house",),
            "Vision now leads the census awareness count, and its ledger bars "
            f"regressed ({', '.join(failing)}) over the last "
            f"{int(_c.CROSSING_VISION_GO_REGRESSION_DAYS)} days.",
            remedy=(
                "Revert F-LEAD: turn off switch.ura_crossing_vision_census_"
                "authority now (seconds), then set "
                "CROSSING_VISION_AWARENESS_VISION_LEADS back to False."
            ),
            severity="HIGH",
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
            "crossing_vision_cap_rehydrate": {
                "state": self._cap_rehydrate_state,
                "cap_hold": self._cap_hold,
                "cap_rehydrate_failed": self._cap_rehydrate_failed,
            },
            "crossing_ledger": self.ledger_diag(),
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
