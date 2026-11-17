"""Crossing vision Phase 3: P3-D2 (crossing-centred frames, 8 frames) and
P3-D3 (watch every crossing; record vision's count AND direction behind
INV-DIR-GATE; G3 attributes; sampled stability repeats; trip-wires;
pipeline_version). docs/planning/PLANNING_crossing_vision.md P3-D2 / P3-D3.

Same REAL rig as test_crossing_vision_shadow (real HA core, bus, timers,
dispatcher, service registry, a real UniversalRoomDatabase, the real
EgressDirectionTracker as the F3 owner / G3 primitive; llmvision is a
service on the real registry: the external boundary). This file's fixture
sets the production default route (``recording_window``) back on; the
shared rig pins the legacy event-clip route for the older files.

Oracles are literal values from the plan (BEFORE 5 s, AFTER 15 s, LAG 10 s,
8 frames, rate 0.2 over sha1, budget 15, pipeline version 3), never
re-computed by the code under test.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import types
from datetime import timedelta

import pytest
import pytest_asyncio

from test_crossing_vision_shadow import (  # noqa: F401 - fixture + helper reuse
    FRONT_EGRESS,
    GARAGE_EGRESS,
    _now,
    frigate,
    hass,
    mods,
    rig,
    settle,
)
from test_crossing_ledger_wiring import ensure_substrate, make_known, terms  # noqa: E402

_PKG = "custom_components.universal_room_automation"
DOORBELL_EGRESS = "binary_sensor.doorbell_lite_person_occupancy"


# ----------------------------------------------------------------- rig
class _LLM2:
    """llmvision ``video_analyzer`` stand-in with per-call replies and an
    in-flight high-water mark. ``reply`` is a dict, an Exception, or a
    callable(call_index, data) -> dict; ``delay`` holds each call open."""

    def __init__(self):
        self.calls: list[dict] = []
        self.reply: object = None
        self.delay = 0.0
        self.inflight = 0
        self.max_inflight = 0
        self.gate: asyncio.Event | None = None
        # call index -> event the call waits on (hold one specific call open)
        self.hold: dict[int, asyncio.Event] = {}

    async def handler(self, call):
        data = dict(call.data)
        idx = len(self.calls)
        self.calls.append(data)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if idx in self.hold:
                await self.hold[idx].wait()
            if self.delay:
                await asyncio.sleep(self.delay)
            reply = self.reply
            if isinstance(reply, BaseException):
                raise reply
            if isinstance(reply, tuple) and reply[0] == "sleep":
                await asyncio.sleep(reply[1])
                return {}
            if callable(reply):
                return reply(idx, data)
            return reply
        finally:
            self.inflight -= 1


def reply_ok(frames=(1, 2, 1, 0), total=2, **extra):
    body = {
        "frames": [{"index": i + 1, "people": n} for i, n in enumerate(frames)],
        "people_total": total, "group": total > 1, "desc": "People at the door.",
    }
    body.update(extra)
    return {"structured_response": body}


@pytest_asyncio.fixture
async def vrig(rig):
    from homeassistant.core import SupportsResponse

    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_FRAME_ROUTE", "recording_window")
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 0)
    llm = _LLM2()
    llm.reply = reply_ok(direction="in", direction_confidence="high")
    rig.hass.services.async_register(
        "llmvision", "video_analyzer", llm.handler,
        supports_response=SupportsResponse.ONLY,
    )
    rig.llm = llm
    signals = importlib.import_module(f"{_PKG}.domain_coordinators.signals")
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    rig.amended = []
    unsub = async_dispatcher_connect(
        rig.hass, signals.SIGNAL_EGRESS_RECORD_AMENDED,
        lambda payload: rig.amended.append(dict(payload)),
    )
    try:
        yield rig
    finally:
        unsub()


def whole_e(rig, back_s):
    """A crossing time with whole seconds (literal URL oracles)."""
    return _now(rig).replace(microsecond=0) - timedelta(seconds=back_s)


def ring_record(rig, camera, e, direction):
    """The tracker's own F3 record for a crossing (what _resolve_direction
    stores before the bus fire)."""
    rec = rig.mods.tv.CrossingRecord(
        camera=camera, direction=direction, ts=e, person_id=None,
        provenance=None, confidence=0.8, identity_confidence=None,
        source_ref=f"egress:{camera}:{e.isoformat()}",
    )
    rig.tracker._record_crossing(rec)
    return rec.source_ref


async def bus(rig, camera, e, *, direction="entry", peak=2, record=True):
    if record:
        ring_record(rig, camera, e, direction)
    rig.hass.bus.async_fire("ura_person_egress_event", {
        "direction": direction, "egress_camera": camera,
        "timestamp": e.isoformat(), "person_id": None, "confidence": 0.8,
        "identity_confidence": None, "agreement_class": "single_source",
        "identity_synthetic_corroborated": False, "identity_provenance": None,
        "peak_person_count": None if direction == "ambiguous" else peak,
    })
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    return f"{camera}@{e.isoformat()}"


def ended_event(rig, eid, camera, start, length=8.0, source="mqtt:frigate2"):
    frigate(rig, eid, camera, start, source=source)
    frigate(rig, eid, camera, start, typ="end", end=start + length, source=source)


def all_rows(rig):
    conn = sqlite3.connect(rig.db.db_file)
    try:
        return [
            {"node": n, "src": s, **json.loads(a)}
            for n, a, s in conn.execute(
                "SELECT node_id, attrs_json, source_ref FROM memory_episodes "
                "WHERE episode_type = ? ORDER BY id", ("crossing_vision_shadow",),
            )
        ]
    finally:
        conn.close()


def primary_rows(rig):
    return [r for r in all_rows(rig) if r.get("call_kind") != "repeat"]


def applied(rig):
    return [(t["direction"], t["n"], t["term_source"]) for t in terms(rig)
            if t["applied"]]


async def flush(rig):
    rig.cv._on_ledger_eval(None)
    await settle(rig)


# ============================================================ P3-D2
@pytest.mark.asyncio
async def test_recording_window_url_centred_on_crossing(vrig):
    """URL = [E - 5, E + 15] on the matched event's camera; the event
    started 3 s BEFORE E, so a window from the event start would differ."""
    e = whole_e(vrig, 60)
    E = int(e.timestamp())
    ended_event(vrig, "ev-w1", "garage_a", e.timestamp() - 3)
    await bus(vrig, GARAGE_EGRESS, e)
    [call] = vrig.llm.calls
    assert call["video_file"] == (
        f"/api/frigate/frigate-f2/recording/garage_a/start/{E - 5}/end/{E + 15}"
    )
    assert "event_id" not in call
    [row] = primary_rows(vrig)
    assert (row["frame_route"], row["frames_requested"]) == ("recording_window", 8)


@pytest.mark.asyncio
async def test_recording_url_camera_from_event_payload(vrig):
    """Crossing on the garage_a egress; the only person event is on
    doorbell_lite (same door group): the URL names doorbell_lite (the event
    payload's camera), never the egress stem."""
    e = whole_e(vrig, 60)
    E = int(e.timestamp())
    ended_event(vrig, "ev-db", "doorbell_lite", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    [call] = vrig.llm.calls
    assert call["video_file"] == (
        f"/api/frigate/frigate-f2/recording/doorbell_lite/start/{E - 5}/end/{E + 15}"
    )


@pytest.mark.asyncio
async def test_frame_window_stays_in_door_group(vrig):
    """A higher-scoring person event on the FRONT group's camera at the same
    moment is never the garage crossing's frame source (INV-SCOPE)."""
    e = whole_e(vrig, 60)
    frigate(vrig, "ev-front", "front_door_aerial", e.timestamp() + 1, score=0.99)
    ended_event(vrig, "ev-garage", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    [call] = vrig.llm.calls
    assert "/recording/garage_a/" in call["video_file"]
    [row] = primary_rows(vrig)
    assert row["event_camera"] == "garage_a"


@pytest.mark.asyncio
async def test_crossing_call_uses_eight_frames(vrig):
    ended_event(vrig, "ev-8", "garage_a", whole_e(vrig, 60).timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, whole_e(vrig, 60))
    [call] = vrig.llm.calls
    assert call["max_frames"] == 8
    assert call["max_tokens"] == 4000


@pytest.mark.asyncio
async def test_ambiguous_crossing_uses_eight_frames(vrig):
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-a8", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    [call] = vrig.llm.calls
    assert call["max_frames"] == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["recording_window", "event_clip"])
async def test_long_event_never_event_clip_when_window_available(vrig, route):
    """A 90 s event (> LONG_EVENT_S 60) uses the window on BOTH knob values."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_FRAME_ROUTE", route)
    e = whole_e(vrig, 200)
    E = int(e.timestamp())
    ended_event(vrig, "ev-long", "garage_a", e.timestamp() - 2, length=90)
    await bus(vrig, GARAGE_EGRESS, e)
    [call] = vrig.llm.calls
    assert call["video_file"] == (
        f"/api/frigate/frigate-f2/recording/garage_a/start/{E - 5}/end/{E + 15}"
    )
    [row] = primary_rows(vrig)
    assert row["frame_route"] == "recording_window"


@pytest.mark.asyncio
async def test_long_event_uses_clip_only_when_window_unavailable(vrig):
    """Event-clip knob, long event, window NOT complete yet at call time
    (fired by the event end before E + 25): the one call uses the clip and
    the row says event_clip_long."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_FRAME_ROUTE", "event_clip")
    e = whole_e(vrig, 0) - timedelta(seconds=5)
    ended_event(vrig, "ev-lc", "garage_a", e.timestamp() - 5, length=84)
    await bus(vrig, GARAGE_EGRESS, e)
    [call] = vrig.llm.calls
    assert call["video_file"] == "/api/frigate/frigate-f2/notifications/ev-lc/clip.mp4"
    [row] = primary_rows(vrig)
    assert row["frame_route"] == "event_clip_long"


@pytest.mark.asyncio
async def test_precall_route_failure_uses_event_clip_one_call(vrig):
    """Window end not reachable inside the outer bound (EVENT_END_WAIT_S 10
    here; the bus event lands 5 s after E, window ready at E + 25): the
    single call uses the event clip after the event end."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_EVENT_END_WAIT_S", 10)
    e = whole_e(vrig, 0) - timedelta(seconds=5)
    ended_event(vrig, "ev-pc", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    await settle(vrig)
    [call] = vrig.llm.calls
    assert call["video_file"] == "/api/frigate/frigate-f2/notifications/ev-pc/clip.mp4"
    [row] = primary_rows(vrig)
    assert (row["outcome"], row["frame_route"]) == ("ok", "event_clip")


@pytest.mark.asyncio
async def test_precall_no_instance_uses_event_clip(vrig):
    """No window target (instance / camera not resolvable; forced here at
    the resolver): the request takes the event-clip route, so it WAITS for
    the event end (no call on an incomplete clip at E + 25), then makes the
    one call on the clip."""
    vrig.monkeypatch.setattr(
        vrig.cv, "_window_target", lambda ev: None,
    )
    e = whole_e(vrig, 60)
    start = e.timestamp() + 1
    frigate(vrig, "ev-ni", "garage_a", start)
    await bus(vrig, GARAGE_EGRESS, e)
    assert vrig.llm.calls == []
    frigate(vrig, "ev-ni", "garage_a", start, typ="end", end=start + 8)
    await settle(vrig)
    [call] = vrig.llm.calls
    assert call["video_file"].endswith("/notifications/ev-ni/clip.mp4")


@pytest.mark.asyncio
async def test_fetch_failure_is_error_row_no_second_call(vrig):
    vrig.llm.reply = RuntimeError("fetch failed: 404 recording")
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-ff", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    await settle(vrig)
    assert len(vrig.llm.calls) == 1
    [row] = primary_rows(vrig)
    assert row["outcome"] == "error"
    assert row["error"] == "fetch failed: 404 recording"


@pytest.mark.asyncio
async def test_timeout_row_no_second_call(vrig):
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_TIMEOUT_S", 0.05)
    vrig.llm.reply = ("sleep", 1.0)
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-to", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    await asyncio.sleep(0.1)
    await settle(vrig)
    assert len(vrig.llm.calls) == 1
    [row] = primary_rows(vrig)
    assert row["outcome"] == "timeout"


@pytest.mark.asyncio
async def test_window_route_fires_once_at_e_plus_25_event_open(vrig):
    """E = now, event OPEN: nothing at +24 s, one call by +26 s; the event's
    later `end` fires nothing more (one call per request)."""
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    e = whole_e(vrig, 0)
    start = e.timestamp() - 2
    frigate(vrig, "ev-open", "garage_a", start)
    await bus(vrig, GARAGE_EGRESS, e)
    # An early `end` (before E + 25) must not fire the window request.
    frigate(vrig, "ev-open", "garage_a", start, typ="end", end=start + 6)
    await settle(vrig)
    assert vrig.llm.calls == []
    async_fire_time_changed(vrig.hass, e + timedelta(seconds=24))
    await settle(vrig)
    assert vrig.llm.calls == []
    async_fire_time_changed(vrig.hass, e + timedelta(seconds=26))
    await settle(vrig)
    assert len(vrig.llm.calls) == 1
    frigate(vrig, "ev-open", "garage_a", start, typ="end", end=start + 30)
    async_fire_time_changed(vrig.hass, e + timedelta(seconds=200))
    await settle(vrig)
    assert len(vrig.llm.calls) == 1


@pytest.mark.asyncio
async def test_interior_caller_frames_unchanged(vrig):
    """Interior clip callers keep their own frame count (1)."""
    iv = importlib.import_module(f"{_PKG}.interior_vision")
    fs = iv.FrameSource(kind="clip", group_key="g", video_file="/x/clip.mp4")
    await iv.call_model(vrig.hass, fs, "p", "{}", model="m", max_tokens=10,
                        target_width=100, timeout_s=5, provider=None)
    [call] = vrig.llm.calls
    assert call["max_frames"] == 1


@pytest.mark.asyncio
async def test_term_n_is_vision_count_not_max_with_peak(vrig):
    """Vision 2, camera peak 4: the term is the vision count (2), not max."""
    await make_known(vrig, R=0)
    vrig.llm.reply = reply_ok(frames=(1, 2, 1, 0), total=2, direction="in")
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-n", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, peak=4)
    await flush(vrig)
    assert applied(vrig) == [("entry", 2, "vision")]


# ============================================================ P3-D3
@pytest.mark.asyncio
async def test_ambiguous_crossing_gets_row_and_call(vrig):
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-amb", "garage_a", e.timestamp() + 1)
    key = await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    assert len(vrig.llm.calls) == 1
    [row] = primary_rows(vrig)
    assert (row["src"], row["outcome"], row["direction"]) == (key, "ok", "ambiguous")
    assert (row["vision_direction"], row["vision_direction_confidence"]) == ("in", "high")
    assert row["direction_agreement"] == "vision_only"
    assert vrig.cv.diag_status()["crossing_vision_today"]["ambiguous"] == 1
    # The zero-ok trip-wire's sample stays entry/exit only.
    assert len(vrig.cv._seen) == 0 and len(vrig.cv._amb_seen) == 1


@pytest.mark.asyncio
async def test_ambiguous_row_peak_none(vrig):
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-ap", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    [row] = primary_rows(vrig)
    assert row["camera_peak_count"] is None


async def _watch_scenario(rig, *, with_ambiguous):
    """Entry + exit (+ optionally two ambiguous) crossings; returns the
    observable outputs with keys made relative."""
    await make_known(rig, R=1)
    base = whole_e(rig, 900)
    out_keys = {}
    ended_event(rig, "ev-s1", "garage_a", base.timestamp() + 1)
    out_keys[await bus(rig, GARAGE_EGRESS, base)] = "k1"
    if with_ambiguous:
        ended_event(rig, "ev-s2", "front_door_aerial", base.timestamp() + 101)
        await bus(rig, FRONT_EGRESS, base + timedelta(seconds=100), direction="ambiguous")
        await bus(rig, FRONT_EGRESS, base + timedelta(seconds=300), direction="ambiguous")
    ended_event(rig, "ev-s3", "front_door_aerial", base.timestamp() + 401)
    out_keys[await bus(rig, FRONT_EGRESS, base + timedelta(seconds=400),
                       direction="exit", peak=1)] = "k3"
    await flush(rig)
    rows = [(out_keys.get(r["src"]), r["outcome"], r["people_count"])
            for r in primary_rows(rig)]
    today = rig.cv.diag_status()["crossing_vision_today"]
    return {
        "rows": rows, "terms": applied(rig), "L": rig.cv._ledger.L,
        "calls": len(rig.llm.calls), "today": today,
        "seen": len(rig.cv._seen), "amended": len(rig.amended),
    }


@pytest.mark.asyncio
async def test_watch_ambiguous_off_restores_skip(vrig):
    """WATCH_AMBIGUOUS False: ambiguous crossings leave NO trace, so a run
    with two ambiguous crossings equals a run with none (byte-identical
    outputs: rows, terms, L, calls, counters, trip-wire samples)."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_WATCH_AMBIGUOUS", False)
    got = await _watch_scenario(vrig, with_ambiguous=True)
    assert got["rows"] == [("k1", "ok", 2), ("k3", "ok", 2)]
    assert got["terms"] == [("entry", 2, "vision"), ("exit", 2, "vision")]
    assert got["calls"] == 2 and got["seen"] == 2
    assert got["today"]["ambiguous"] == 0
    assert len(vrig.cv._amb_seen) == 0 and len(vrig.cv._amb_rows) == 0


@pytest.mark.asyncio
async def test_watch_ambiguous_off_equals_no_ambiguous(rig):
    """The same scenario WITHOUT ambiguous crossings gives the identical
    outputs (the other side of the byte-identity check above)."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_FRAME_ROUTE", "recording_window")
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_WATCH_AMBIGUOUS", False)
    from homeassistant.core import SupportsResponse

    llm = _LLM2()
    llm.reply = reply_ok(direction="in", direction_confidence="high")
    rig.hass.services.async_register("llmvision", "video_analyzer", llm.handler,
                                     supports_response=SupportsResponse.ONLY)
    rig.llm = llm
    rig.amended = []
    got = await _watch_scenario(rig, with_ambiguous=False)
    assert got["rows"] == [("k1", "ok", 2), ("k3", "ok", 2)]
    assert got["terms"] == [("entry", 2, "vision"), ("exit", 2, "vision")]
    assert got["calls"] == 2 and got["seen"] == 2
    assert got["today"]["ambiguous"] == 0


@pytest.mark.asyncio
async def test_ambiguous_request_never_adopts_resolved_member(vrig):
    """Ambiguous A analysed event X; entry B 20 s later on the same event
    (X starts 10 s after A: inside the +-10 s match of both): B opens its
    OWN request, own call, own vision term (counted ambiguous_shared_event)."""
    await make_known(vrig, R=0)
    vrig.llm.reply = lambda i, d: reply_ok(frames=(1, 3, 1, 0), total=3) if i else \
        reply_ok(frames=(1, 1, 1, 0), total=1)
    e = whole_e(vrig, 120)
    ended_event(vrig, "ev-x", "garage_a", e.timestamp() + 10, length=40)
    ka = await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    kb = await bus(vrig, GARAGE_EGRESS, e + timedelta(seconds=20), peak=1)
    await flush(vrig)
    assert len(vrig.llm.calls) == 2
    got = {r["src"]: r for r in primary_rows(vrig)}
    assert got[kb]["outcome"] == "ok" and got[kb]["crossing_keys"] == [kb]
    assert got[ka]["crossing_keys"] == [ka]
    assert applied(vrig) == [("entry", 3, "vision")]
    assert vrig.cv.diag_status()["crossing_vision_today"]["ambiguous_shared_event"] == 1


@pytest.mark.asyncio
async def test_ambiguous_shared_event_outside_cluster_window(vrig):
    """CLUSTER_S 5 (< the 20 s two +-10 s matches can span): the entry
    crossing misses the cluster test and reaches the analysed-event test,
    which must still give it its own request and call."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_CLUSTER_S", 5)
    await make_known(vrig, R=0)
    e = whole_e(vrig, 120)
    ended_event(vrig, "ev-sh", "garage_a", e.timestamp() + 10, length=40)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    kb = await bus(vrig, GARAGE_EGRESS, e + timedelta(seconds=20), peak=1)
    await flush(vrig)
    assert len(vrig.llm.calls) == 2
    got = {r["src"]: r["outcome"] for r in primary_rows(vrig)}
    assert got[kb] == "ok"
    assert applied(vrig) == [("entry", 2, "vision")]


@pytest.mark.asyncio
async def test_ambiguous_primary_late_joiner_no_double_term(vrig):
    """B1 repro: ambiguous A, entry B (inside A's cluster), entry C late:
    exactly one entry term."""
    await make_known(vrig, R=0)
    vrig.llm.reply = reply_ok(frames=(1, 2, 1, 0), total=2)
    e = whole_e(vrig, 120)
    ended_event(vrig, "ev-b1", "garage_a", e.timestamp() + 3, length=40)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    await bus(vrig, GARAGE_EGRESS, e + timedelta(seconds=10), peak=1)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=40), peak=1)
    await flush(vrig)
    assert applied(vrig) == [("entry", 2, "vision")]
    assert vrig.cv._ledger.L == 2


@pytest.mark.asyncio
async def test_late_joiner_after_mixed_cluster_uses_primary_term_direction(vrig):
    """P3-D3 step 3, mixed cluster (entry primary + folded exit -> one
    camera term each): a late ENTRY is counted by the primary's term (no
    term); a late EXIT gets its own camera term."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_FRAME_ROUTE", "event_clip")
    await make_known(vrig, R=0)
    e = whole_e(vrig, 200)
    s = e.timestamp() + 1
    frigate(vrig, "ev-mx", "garage_a", s)
    await bus(vrig, GARAGE_EGRESS, e, peak=2)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=10), direction="exit", peak=1)
    frigate(vrig, "ev-mx", "garage_a", s, typ="end", end=s + 20)
    await settle(vrig)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=40), peak=3)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=50), direction="exit", peak=1)
    await flush(vrig)
    assert sorted(applied(vrig)) == [("entry", 2, "camera"), ("exit", 1, "camera"),
                                     ("exit", 1, "camera")]


@pytest.mark.asyncio
async def test_ambiguous_member_in_cluster_no_term_under_tracker(vrig):
    """An ambiguous crossing joining an entry request adds no term; an
    ambiguous crossing alone yields no term."""
    await make_known(vrig, R=0)
    e = whole_e(vrig, 600)
    ended_event(vrig, "ev-c1", "garage_a", e.timestamp() + 1, length=30)
    await bus(vrig, GARAGE_EGRESS, e, peak=1)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=20), direction="ambiguous")
    ended_event(vrig, "ev-c2", "front_door_aerial", e.timestamp() + 301)
    await bus(vrig, FRONT_EGRESS, e + timedelta(seconds=300), direction="ambiguous")
    await flush(vrig)
    assert applied(vrig) == [("entry", 2, "vision")]
    assert vrig.cv._ledger.L == 2


@pytest.mark.asyncio
async def test_vision_direction_parsed_and_unclear_default(vrig):
    parse = vrig.mods.cv.parse_vision_response
    base = reply_ok()["structured_response"]
    assert parse({"structured_response": {**base, "direction": "out"}}, 200)["direction"] == "out"
    assert parse({"structured_response": base}, 200)["direction"] == "unclear"
    assert parse({"response_text": "not json"}, 200)["direction"] is None
    vrig.llm.reply = reply_ok()
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-u", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    [row] = primary_rows(vrig)
    assert row["vision_direction"] == "unclear"
    assert row["direction_agreement"] == "unclear"


@pytest.mark.asyncio
async def test_direction_fields_optional_never_change_outcome(vrig):
    parse = vrig.mods.cv.parse_vision_response
    base = reply_ok(frames=(1, 3, 2, 0), total=3)["structured_response"]
    variants = [
        {}, {"direction": None}, {"direction": "sideways"}, {"direction": 7},
        {"direction": ["in"]}, {"direction_confidence": "certain"},
        {"direction": "in", "direction_confidence": None},
        {"direction": "out", "direction_confidence": "low"},
    ]
    seen = set()
    for extra in variants:
        got = parse({"structured_response": {**base, **extra}}, 200)
        seen.add((got["outcome"], got["people_count"], tuple(got["frame_counts"])))
        assert got["direction"] in ("in", "out", "passing", "unclear")
        assert got["direction_confidence"] in ("high", "medium", "low", None)
    assert seen == {("ok", 3, (1, 3, 2, 0))}
    blank = reply_ok(frames=(0, 0, 0, 0), total=0)["structured_response"]
    for extra in variants:
        got = parse({"structured_response": {**blank, **extra}}, 200)
        assert (got["outcome"], got["people_count"]) == ("blank", None)


@pytest.mark.asyncio
async def test_direction_confidence_recorded(vrig):
    vrig.llm.reply = reply_ok(direction="out", direction_confidence="medium")
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-dc", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, direction="exit")
    [row] = primary_rows(vrig)
    assert (row["vision_direction"], row["vision_direction_confidence"]) == ("out", "medium")
    assert row["direction_agreement"] == "agree"


@pytest.mark.asyncio
async def test_direction_agreement_cases(vrig):
    agree = vrig.mods.cv.direction_agreement
    assert agree("entry", "in", True) == "agree"
    assert agree("exit", "in", True) == "disagree"
    assert agree("ambiguous", "out", True) == "vision_only"
    assert agree("entry", "passing", True) == "unclear"
    assert agree("entry", "in", False) == "not_analysed"
    # Production: one disagreeing crossing and one failed call.
    vrig.llm.reply = reply_ok(direction="out")
    e = whole_e(vrig, 600)
    ended_event(vrig, "ev-dis", "garage_a", e.timestamp() + 1)
    k1 = await bus(vrig, GARAGE_EGRESS, e)
    vrig.llm.reply = RuntimeError("boom")
    ended_event(vrig, "ev-na", "front_door_aerial", e.timestamp() + 301)
    k2 = await bus(vrig, FRONT_EGRESS, e + timedelta(seconds=300))
    got = {r["src"]: r["direction_agreement"] for r in primary_rows(vrig)}
    assert got == {k1: "disagree", k2: "not_analysed"}


@pytest.mark.asyncio
async def test_g3_amend_once_per_crossing_key(vrig):
    """Primary + folded member amended at the outcome; a late joiner
    amended at its join; every key exactly once, role vision_direction."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_FRAME_ROUTE", "event_clip")
    e = whole_e(vrig, 120)
    s = e.timestamp() + 1
    frigate(vrig, "ev-g3", "garage_a", s)
    await bus(vrig, GARAGE_EGRESS, e)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=10))
    frigate(vrig, "ev-g3", "garage_a", s, typ="end", end=s + 20)
    await settle(vrig)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=40), direction="exit")
    # The same late crossing delivered twice: still one amend for its key.
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=40), direction="exit",
              record=False)
    await settle(vrig)
    refs = [p["source_ref"] for p in vrig.amended]
    assert sorted(refs) == sorted([
        f"egress:{GARAGE_EGRESS}:{e.isoformat()}",
        f"egress:{DOORBELL_EGRESS}:{(e + timedelta(seconds=10)).isoformat()}",
        f"egress:{DOORBELL_EGRESS}:{(e + timedelta(seconds=40)).isoformat()}",
    ])
    assert {p["role"] for p in vrig.amended} == {"vision_direction"}
    inherited = {p["source_ref"]: p["member_inherited"] for p in vrig.amended}
    assert inherited[f"egress:{GARAGE_EGRESS}:{e.isoformat()}"] is False
    late = vrig.tracker.get_crossing(
        f"egress:{DOORBELL_EGRESS}:{(e + timedelta(seconds=40)).isoformat()}")
    assert (late.vision_direction, late.direction_agreement) == ("in", "disagree")


@pytest.mark.asyncio
async def test_g3_source_ref_from_bus_fields(vrig):
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-sr", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    rec = vrig.tracker.get_crossing(f"egress:{GARAGE_EGRESS}:{e.isoformat()}")
    assert (rec.vision_direction, rec.vision_people_count,
            rec.direction_agreement, rec.vision_direction_confidence) == (
        "in", 2, "agree", "high")
    assert vrig.amended[0]["egress_camera"] == GARAGE_EGRESS


@pytest.mark.asyncio
async def test_g3_never_sets_direction(vrig):
    """Vision says `out` on an ambiguous crossing: the record's tracker
    direction stays `ambiguous`; the bus / DB direction are never touched."""
    vrig.llm.reply = reply_ok(direction="out", direction_confidence="high")
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-nd", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    rec = vrig.tracker.get_crossing(f"egress:{GARAGE_EGRESS}:{e.isoformat()}")
    assert rec.direction == "ambiguous"
    assert rec.vision_direction == "out"
    assert vrig.cv.diag_status()["crossing_vision_today"]["vision_amend_failed"] == 0


@pytest.mark.asyncio
async def test_amend_failure_counted_never_raises(vrig):
    await make_known(vrig, R=0)

    def _boom(*a, **k):
        raise RuntimeError("ring gone")

    vrig.monkeypatch.setattr(vrig.tracker, "attach_crossing_attribute", _boom)
    e = whole_e(vrig, 60)
    ended_event(vrig, "ev-af", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    await flush(vrig)
    assert vrig.cv.diag_status()["crossing_vision_today"]["vision_amend_failed"] == 1
    [row] = primary_rows(vrig)
    assert row["outcome"] == "ok"
    assert applied(vrig) == [("entry", 2, "vision")]


@pytest.mark.asyncio
async def test_amended_signal_ignored_by_exit_backfill_readers(vrig):
    """The two exit-backfill display readers act on role exit_backfilled
    only: a vision_direction notice schedules no re-read."""
    sensor = vrig.mods.sensor
    for cls in (sensor.PersonsExitedTodaySensor, sensor.LastPersonExitSensor):
        tasks = []

        async def _reread():
            return None

        fake = types.SimpleNamespace(
            hass=types.SimpleNamespace(
                async_create_task=lambda c, *a, **k: (tasks.append(c), c.close())),
            _async_reread_exits=_reread, _async_reread_last_exit=_reread,
        )
        cls._handle_exit_backfilled(fake, {"role": "vision_direction",
                                           "source_ref": "egress:x:y"})
        assert tasks == []
        cls._handle_exit_backfilled(fake, {"role": "exit_backfilled"})
        assert len(tasks) == 1


# ---------------------------------------------------------------- repeats
@pytest.mark.asyncio
async def test_repeat_selection_stable_across_processes(vrig):
    """Selection is sha1-based: the literal buckets below were computed
    offline in another process; a per-process salted hash() cannot match."""
    sel = vrig.mods.cv.repeat_selected
    literal = {
        "binary_sensor.garage_a_person_occupancy@2026-11-17T10:00:00+00:00": 295,
        "binary_sensor.front_door_aerial_person_occupancy@2026-11-17T10:00:00+00:00": 21,
        "a": 759, "b": 598, "crossing-1": 899, "crossing-2": 535,
        "x1": 346, "x2": 571, "x3": 170, "x4": 356,
    }
    for key, bucket in literal.items():
        assert sel(key, 0.2) is (bucket < 200), key
        assert sel(key, 1.0) is True
        assert sel(key, 0) is False


async def _three_crossings(rig):
    e = whole_e(rig, 900)
    for i, (eid, cam, egress) in enumerate((
        ("ev-r1", "garage_a", GARAGE_EGRESS),
        ("ev-r2", "front_door_aerial", FRONT_EGRESS),
        ("ev-r3", "garage_a", GARAGE_EGRESS),
    )):
        t = e + timedelta(seconds=200 * i)
        ended_event(rig, eid, cam, t.timestamp() + 1)
        await bus(rig, egress, t, peak=1)
        await settle(rig)
    await flush(rig)


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [0, 0.2, 1.0])
async def test_repeat_never_spends_primary_cap(vrig, rate):
    """Cap 2: primary outcomes and terms identical at rate 0, 0.2 and 1.0."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", rate)
    vrig.hass.data[vrig.C.DOMAIN][vrig.C.CROSSING_VISION_CAP_HASS_KEY] = 2
    await make_known(vrig, R=0)
    await _three_crossings(vrig)
    assert [r["outcome"] for r in primary_rows(vrig)] == ["ok", "ok", "skipped_cap"]
    assert applied(vrig) == [("entry", 2, "vision"), ("entry", 2, "vision"),
                             ("entry", 1, "camera")]
    assert vrig.cv._calls_today == 2
    repeats = [r for r in all_rows(vrig) if r.get("call_kind") == "repeat"]
    assert len(repeats) == (2 if rate == 1.0 else vrig.cv._repeats_today)
    if rate == 1.0:
        assert vrig.cv._repeats_today == 2


@pytest.mark.asyncio
async def test_repeat_waits_for_free_slot_never_busies_primary(vrig):
    """MAX_CONCURRENT 1. A repeat holds the slot (gated); a primary arrives:
    it is NOT skipped_busy, it waits, then calls; never 2 calls at once."""
    from test_crossing_vision_shadow import fire_cross_nowait

    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_MAX_CONCURRENT", 1)
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    held = asyncio.Event()
    vrig.llm.hold[1] = held  # call 1 = P1's repeat
    e = whole_e(vrig, 900)
    ended_event(vrig, "ev-p1", "garage_a", e.timestamp() + 1)
    ring_record(vrig, GARAGE_EGRESS, e, "entry")
    k1 = fire_cross_nowait(vrig, GARAGE_EGRESS, e)
    for _ in range(200):
        await asyncio.sleep(0)
        if len(vrig.llm.calls) == 2:
            break
    assert len(vrig.llm.calls) == 2 and vrig.cv._repeat_running is True
    # P2 arrives while the repeat holds the only slot.
    e2 = e + timedelta(seconds=300)
    ended_event(vrig, "ev-p2", "front_door_aerial", e2.timestamp() + 1)
    ring_record(vrig, FRONT_EGRESS, e2, "entry")
    k2 = fire_cross_nowait(vrig, FRONT_EGRESS, e2)
    for _ in range(100):
        await asyncio.sleep(0)
    assert vrig.cv._pending_primaries() == 1   # accepted, not skipped_busy
    assert len(vrig.llm.calls) == 2           # waiting for the repeat
    assert vrig.llm.inflight == 1
    held.set()
    await settle(vrig)
    got = {r["src"]: r["outcome"] for r in primary_rows(vrig)}
    assert got == {k1: "ok", k2: "ok"}
    assert vrig.llm.max_inflight == 1
    # P2's own repeat ran after it (budget 15): 4 calls, never 2 at once.
    assert len(vrig.llm.calls) == 4


@pytest.mark.asyncio
async def test_repeat_row_identity_and_readers(vrig):
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.llm.reply = lambda i, d: reply_ok(direction="out" if i else "in")
    e = whole_e(vrig, 600)
    ended_event(vrig, "ev-id", "garage_a", e.timestamp() + 1)
    key = await bus(vrig, GARAGE_EGRESS, e)
    await settle(vrig)
    rows = all_rows(vrig)
    prim = [r for r in rows if r["call_kind"] == "primary"]
    rep = [r for r in rows if r["call_kind"] == "repeat"]
    assert len(prim) == 1 and len(rep) == 1
    assert rep[0]["node"] == f"vision-repeat:{key}" and rep[0]["src"] == key
    assert rep[0]["vision_direction"] == "out"
    assert vrig.llm.calls[0]["video_file"] == vrig.llm.calls[1]["video_file"]
    assert vrig.llm.calls[0]["max_frames"] == vrig.llm.calls[1]["max_frames"] == 8
    # Trip-wire / display readers see the primary only.
    assert len(vrig.cv._calls) == 1 and len(vrig.cv._dir_ok) == 1
    assert vrig.cv.diag_status()["crossing_vision_today"]["calls"] == 1
    assert vrig.cv.diag_status()["crossing_vision_today"]["repeats"] == 1
    # G3 was amended from the PRIMARY only (`in`), never from the repeat.
    rec = vrig.tracker.get_crossing(f"egress:{GARAGE_EGRESS}:{e.isoformat()}")
    assert rec.vision_direction == "in"
    assert len(vrig.amended) == 1
    # Rehydrate: primaries and repeats counted apart after a restart.
    await vrig.cv.async_teardown()
    cv2 = vrig.mods.cv.CrossingVisionShadow(vrig.hass)
    vrig.cv = cv2
    await cv2.async_setup()
    await cv2._cap_rehydrate_task
    assert (cv2._calls_today, cv2._repeats_today) == (1, 1)


@pytest.mark.asyncio
async def test_repeat_budget_rehydrated_and_enforced(vrig):
    """Budget 1: after one repeat today (restart in between), no more."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX", 1)
    e = whole_e(vrig, 900)
    ended_event(vrig, "ev-b1x", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    await settle(vrig)
    await vrig.cv.async_teardown()
    cv2 = vrig.mods.cv.CrossingVisionShadow(vrig.hass)
    vrig.cv = cv2
    await cv2.async_setup()
    await cv2._cap_rehydrate_task
    ended_event(vrig, "ev-b2x", "front_door_aerial", e.timestamp() + 301)
    await bus(vrig, FRONT_EGRESS, e + timedelta(seconds=300))
    await settle(vrig)
    reps = [r for r in all_rows(vrig) if r.get("call_kind") == "repeat"]
    assert len(reps) == 1 and len(vrig.llm.calls) == 3


@pytest.mark.asyncio
async def test_repeat_budget_rechecked_when_the_repeat_starts(vrig):
    """Budget 1, two primaries whose calls overlap: both outcomes land with
    0 repeats spent, so two repeats are queued; only ONE may run."""
    from test_crossing_vision_shadow import fire_cross_nowait

    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX", 1)
    gate = asyncio.Event()
    vrig.llm.gate = gate
    e = whole_e(vrig, 900)
    for i, (cam, egress) in enumerate((("garage_a", GARAGE_EGRESS),
                                       ("front_door_aerial", FRONT_EGRESS))):
        t = e + timedelta(seconds=200 * i)
        ended_event(vrig, f"ev-bb{i}", cam, t.timestamp() + 1)
        ring_record(vrig, egress, t, "entry")
        fire_cross_nowait(vrig, egress, t)
    for _ in range(100):
        await asyncio.sleep(0)
    assert len(vrig.llm.calls) == 2  # both primaries in flight
    gate.set()
    await settle(vrig)
    reps = [r for r in all_rows(vrig) if r.get("call_kind") == "repeat"]
    assert len(reps) == 1 and len(vrig.llm.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("knob, value", [
    ("CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX", 0),
    ("CROSSING_VISION_DIRECTION_REPEAT_RATE", 0),
])
async def test_repeat_off_extremes(vrig, knob, value):
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.monkeypatch.setattr(vrig.C, knob, value)
    e = whole_e(vrig, 600)
    ended_event(vrig, "ev-off", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e)
    await settle(vrig)
    assert len(vrig.llm.calls) == 1
    assert [r.get("call_kind") for r in all_rows(vrig)] == ["primary"]


@pytest.mark.asyncio
async def test_max_concurrent_zero_no_primary_no_repeat(vrig):
    """MAX_CONCURRENT 0 (in-flight bound 0): every primary skipped_busy, no
    repeat ever (rate 1.0)."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_MAX_CONCURRENT", 0)
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    e = whole_e(vrig, 600)
    ended_event(vrig, "ev-mc0", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    await settle(vrig)
    assert vrig.llm.calls == []
    assert [r["outcome"] for r in all_rows(vrig)] == ["skipped_busy"]


@pytest.mark.asyncio
async def test_cap_zero_no_call_with_ambiguous_and_repeats(vrig):
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.hass.data[vrig.C.DOMAIN][vrig.C.CROSSING_VISION_CAP_HASS_KEY] = 0
    e = whole_e(vrig, 600)
    ended_event(vrig, "ev-c0", "garage_a", e.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, e, direction="ambiguous")
    await bus(vrig, GARAGE_EGRESS, e + timedelta(seconds=200))
    await settle(vrig)
    assert vrig.llm.calls == [] and all_rows(vrig) == []
    assert vrig.amended == []


@pytest.mark.asyncio
async def test_repeat_task_cancelled_on_teardown(vrig):
    """A repeat waiting for a free slot (a primary is pending) is cancelled
    by teardown; no repeat call is ever made."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    e = whole_e(vrig, 900)
    ended_event(vrig, "ev-t1", "garage_a", e.timestamp() + 1)
    # A second crossing whose request stays WAITING (window not ready).
    e2 = whole_e(vrig, 0)
    frigate(vrig, "ev-t2", "front_door_aerial", e2.timestamp() + 1)
    await bus(vrig, FRONT_EGRESS, e2)
    from test_crossing_vision_shadow import fire_cross_nowait

    ring_record(vrig, GARAGE_EGRESS, e, "entry")
    fire_cross_nowait(vrig, GARAGE_EGRESS, e)
    for _ in range(200):
        await asyncio.sleep(0)
        if vrig.cv._repeat_tasks:
            break
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(vrig.cv._repeat_tasks) == 1
    [task] = list(vrig.cv._repeat_tasks)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await vrig.cv.async_teardown()
    # Cancelled / woken at once, not left to the 5 s gather bound.
    assert loop.time() - t0 < 1.0
    assert task.done()
    assert len(vrig.llm.calls) == 1
    assert [r for r in all_rows(vrig) if r.get("call_kind") == "repeat"] == []


# ------------------------------------------------------------- trip-wires
@pytest.mark.asyncio
async def test_direction_zero_pages_once(vrig):
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_ZERO_MIN_OK", 3)
    vrig.llm.reply = reply_ok(direction="unclear")
    e = whole_e(vrig, 3000)
    for i in range(3):
        t = e + timedelta(seconds=300 * i)
        ended_event(vrig, f"ev-dz{i}", "garage_a", t.timestamp() + 1)
        await bus(vrig, GARAGE_EGRESS, t)
    await vrig.cv.async_evaluate_tripwires()
    await vrig.cv.async_evaluate_tripwires()
    pages = [p for p in vrig.pages if p["kind"] == "crossing_vision_direction_zero"]
    assert pages == [{"kind": "crossing_vision_direction_zero", "key": ("house",),
                      "severity": "MEDIUM"}]
    # A directional ok re-arms; then a fresh all-unclear window pages again.
    vrig.llm.reply = reply_ok(direction="in")
    t = e + timedelta(seconds=1200)
    ended_event(vrig, "ev-dz-in", "garage_a", t.timestamp() + 1)
    await bus(vrig, GARAGE_EGRESS, t)
    await vrig.cv.async_evaluate_tripwires()
    assert vrig.cv._direction_zero_latched is False


@pytest.mark.asyncio
async def test_direction_zero_below_bar_silent(vrig):
    """Bar 3 with 2 unclear oks: no page (boundary, literal)."""
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_ZERO_MIN_OK", 3)
    vrig.llm.reply = reply_ok(direction="unclear")
    e = whole_e(vrig, 3000)
    for i in range(2):
        t = e + timedelta(seconds=300 * i)
        ended_event(vrig, f"ev-db{i}", "garage_a", t.timestamp() + 1)
        await bus(vrig, GARAGE_EGRESS, t)
    await vrig.cv.async_evaluate_tripwires()
    assert not [p for p in vrig.pages if p["kind"] == "crossing_vision_direction_zero"]


@pytest.mark.asyncio
async def test_ambiguous_zero_counts_bus_events(vrig):
    """5 ambiguous bus events with NO row (row writer dropped): one MEDIUM
    page; with rows: silent."""
    vrig.monkeypatch.setattr(vrig.cv, "_record", lambda *a, **k: None)
    e = whole_e(vrig, 6000)
    for i in range(5):
        await bus(vrig, GARAGE_EGRESS, e + timedelta(seconds=400 * i),
                  direction="ambiguous")
    # Settle: age the bus samples past EVENT_END_WAIT_S + TIMEOUT_S (210 s).
    vrig.cv._amb_seen = type(vrig.cv._amb_seen)(
        [t - 1000 for t in vrig.cv._amb_seen], maxlen=4096)
    await vrig.cv.async_evaluate_tripwires()
    await vrig.cv.async_evaluate_tripwires()
    pages = [p for p in vrig.pages if p["kind"] == "crossing_vision_ambiguous_zero"]
    assert pages == [{"kind": "crossing_vision_ambiguous_zero", "key": ("house",),
                      "severity": "MEDIUM"}]


@pytest.mark.asyncio
async def test_ambiguous_zero_silent_with_rows(vrig):
    e = whole_e(vrig, 6000)
    for i in range(5):
        await bus(vrig, GARAGE_EGRESS, e + timedelta(seconds=400 * i),
                  direction="ambiguous")
    vrig.cv._amb_seen = type(vrig.cv._amb_seen)(
        [t - 1000 for t in vrig.cv._amb_seen], maxlen=4096)
    assert len(all_rows(vrig)) == 5  # no_frigate_event rows, direction ambiguous
    await vrig.cv.async_evaluate_tripwires()
    assert not [p for p in vrig.pages if p["kind"] == "crossing_vision_ambiguous_zero"]


# ---------------------------------------------------------- pipeline / rows
@pytest.mark.asyncio
async def test_pipeline_version_on_every_row(vrig):
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.hass.data[vrig.C.DOMAIN][vrig.C.CROSSING_VISION_CAP_HASS_KEY] = 1
    e = whole_e(vrig, 1200)
    ended_event(vrig, "ev-pv1", "garage_a", e.timestamp() + 1, length=40)
    await bus(vrig, GARAGE_EGRESS, e)                                   # ok
    await settle(vrig)
    await bus(vrig, DOORBELL_EGRESS, e + timedelta(seconds=20))          # clustered
    await bus(vrig, FRONT_EGRESS, e + timedelta(seconds=300))            # no event
    ended_event(vrig, "ev-pv2", "front_door_aerial", e.timestamp() + 601)
    await bus(vrig, FRONT_EGRESS, e + timedelta(seconds=600))            # cap
    await settle(vrig)
    rows = all_rows(vrig)
    kinds = sorted((r.get("call_kind"), r["outcome"]) for r in rows)
    assert kinds == sorted([("primary", "ok"), ("repeat", "ok"),
                            ("primary", "clustered"), ("primary", "no_frigate_event"),
                            ("primary", "skipped_cap")])
    assert {r["pipeline_version"] for r in rows} == {3}


# -------------------------------------------------- burst (11-16 yard walker)
@pytest.mark.asyncio
async def test_yard_walker_burst_cap_and_inflight_hold(vrig):
    """26 ambiguous crossings (the 11-16 burst) fired without waiting, each
    on its own Frigate event, calls held open: in flight never above
    MAX_CONCURRENT (2), calls never above the cap (10), nothing queued
    (every crossing has exactly one row), repeats on at rate 1.0 inside
    their own budget (3) and still within the in-flight bound."""
    from test_crossing_vision_shadow import fire_cross_nowait

    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", 1.0)
    vrig.monkeypatch.setattr(vrig.C, "CROSSING_VISION_DIRECTION_REPEAT_DAILY_MAX", 3)
    vrig.hass.data[vrig.C.DOMAIN][vrig.C.CROSSING_VISION_CAP_HASS_KEY] = 10
    vrig.llm.delay = 0.05
    e = whole_e(vrig, 3000)
    keys = []
    for i in range(26):
        t = e + timedelta(seconds=70 * i)
        cam, egress = (("garage_a", GARAGE_EGRESS) if i % 2 == 0
                       else ("front_door_aerial", FRONT_EGRESS))
        ended_event(vrig, f"ev-burst{i}", cam, t.timestamp() + 1)
        ring_record(vrig, egress, t, "ambiguous")
        vrig.hass.bus.async_fire("ura_person_egress_event", {
            "direction": "ambiguous", "egress_camera": egress,
            "timestamp": t.isoformat(), "person_id": None,
            "identity_provenance": None, "peak_person_count": None,
        })
        keys.append(f"{egress}@{t.isoformat()}")
        await asyncio.sleep(0)
        assert vrig.cv._pending() <= 2
    for _ in range(200):
        await vrig.hass.async_block_till_done(wait_background_tasks=True)
        if not vrig.cv._repeat_tasks and vrig.cv._pending() == 0:
            break
        await asyncio.sleep(0.05)
    await settle(vrig)
    prim = primary_rows(vrig)
    assert sorted(r["src"] for r in prim) == sorted(keys)  # one row each
    n_primary_calls = sum(1 for r in prim if r["outcome"] == "ok")
    assert n_primary_calls <= 10
    assert vrig.cv._calls_today == n_primary_calls
    assert vrig.llm.max_inflight <= 2
    reps = [r for r in all_rows(vrig) if r.get("call_kind") == "repeat"]
    assert len(reps) <= 3
    assert len(vrig.llm.calls) == n_primary_calls + len(reps)
    outcomes = {r["outcome"] for r in prim}
    assert outcomes <= {"ok", "skipped_busy", "skipped_cap"}


# ------------------------------------------------- INV-DIR-GATE metamorphic
_DIR_VARIANTS = [
    {}, {"direction": None, "direction_confidence": None},
    {"direction": "in", "direction_confidence": "high"},
    {"direction": "out", "direction_confidence": "low"},
    {"direction": "passing"}, {"direction": "sideways", "direction_confidence": 9},
    {"direction": ["out"]},
]


async def _gate_run(rig, variant, repeat_rate):
    """One full scenario on a FRESH producer (same hass + DB). Returns the
    term stream, L, guest_vis and primary outcomes with relative keys."""
    if rig.cv is not None:
        await rig.cv.async_teardown()
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_DIRECTION_REPEAT_RATE", repeat_rate)
    cv = rig.mods.cv.CrossingVisionShadow(rig.hass)
    rig.cv = cv
    await cv.async_setup()
    await cv._cap_rehydrate_task
    # A fresh day for every run (earlier runs' rows share the DB).
    cv._calls_today = 0
    cv._repeats_today = 0
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 6
    ensure_substrate(rig)
    cv._ledger.empty_reset_s = 0
    cv.census_tick(resident_term=1, camera_bodies=0, camera_input_dark=False)
    cv._on_ledger_eval(None)
    cv._ledger.empty_reset_s = 10 ** 9
    cv._ledger.last_anchor_ts -= 7200
    stream = []
    real_apply = cv._ledger.apply_term

    def _spy(**kw):
        stream.append((kw["direction"], kw["n"], kw["term_source"], kw["crossing_key"]))
        return real_apply(**kw)

    rig.monkeypatch.setattr(cv._ledger, "apply_term", _spy)
    outcomes = []
    real_record = cv._record

    def _rec(crossing, outcome, **kw):
        outcomes.append((crossing["crossing_key"], outcome))
        return real_record(crossing, outcome, **kw)

    rig.monkeypatch.setattr(cv, "_record", _rec)
    rig.llm.reply = lambda i, d: reply_ok(frames=(1, 2, 2, 0), total=2, **variant)
    base = whole_e(rig, 2400)
    tag = f"{repeat_rate}-{id(variant)}"
    seq = [
        # (offset s, egress, event cam or None, direction, peak)
        (0, GARAGE_EGRESS, "garage_a", "entry", 1),
        (10, DOORBELL_EGRESS, None, "ambiguous", None),      # joins (amb)
        (45, DOORBELL_EGRESS, None, "exit", 1),              # late joiner
        (300, FRONT_EGRESS, "front_door_aerial", "ambiguous", None),
        (320, FRONT_EGRESS, None, "entry", 2),               # own request
        (350, FRONT_EGRESS, None, "entry", 1),               # late joiner
        (700, GARAGE_EGRESS, None, "exit", 1),               # no event
        (1000, FRONT_EGRESS, "front_door_aerial", "exit", 1),
        (1200, GARAGE_EGRESS, "garage_a", "entry", 3),
        (1400, FRONT_EGRESS, "front_door_aerial", "ambiguous", None),
        (1600, GARAGE_EGRESS, "garage_a", "exit", 2),        # cap reached
    ]
    rel = {}
    for i, (off, egress, cam, direction, peak) in enumerate(seq):
        t = base + timedelta(seconds=off)
        if cam is not None:
            ended_event(rig, f"ev-g{tag}-{i}", cam, t.timestamp() + 1, length=50)
        rel[await bus(rig, egress, t, direction=direction, peak=peak)] = i
        await settle(rig)
    cv._on_ledger_eval(None)
    await settle(rig)
    return {
        "terms": [(d, n, s, rel.get(k)) for d, n, s, k in stream],
        "L": cv._ledger.L, "guest": cv._ledger.guest_vis(),
        "outcomes": [(rel.get(k), o) for k, o in outcomes],
        "calls_today": cv._calls_today,
    }


@pytest.mark.asyncio
async def test_inv_dir_gate_metamorphic(vrig):
    """INV-DIR-GATE: permuting vision_direction / confidence over valid,
    invalid and missing values, and toggling repeats, leaves the term
    stream, L, guest_vis, every primary outcome and the cap count identical
    (production path: bus -> _on_egress_event -> llmvision stub -> term ->
    real CrossingLedger)."""
    golden = None
    for repeat_rate in (0, 1.0):
        for variant in _DIR_VARIANTS:
            got = await _gate_run(vrig, variant, repeat_rate)
            if golden is None:
                golden = got
                # Hand-derived anchors on the golden run.
                assert ("entry", 2, "vision", 0) in got["terms"]
                assert not [t for t in got["terms"] if t[3] in (1, 3, 9)]
            assert got == golden, (variant, repeat_rate)
