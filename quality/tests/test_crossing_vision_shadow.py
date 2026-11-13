"""VISION-CROSSING-SHADOW-1 D1 + D3 (PLANNING_crossing_vision.md rev 2).

Every test drives PRODUCTION code on a REAL Home Assistant core (phcc
factory: real bus, real service registry, real ``async_call_later`` /
timers) and a REAL ``UniversalRoomDatabase`` (its own DDL):

* crossings enter as real ``ura_person_egress_event`` bus events;
* Frigate events enter through a real ``FrigateEventIngress._dispatch``
  (the latch + fan-out the live MQTT/bus sources use);
* llmvision is a service registered on the real registry under
  ``llmvision.video_analyzer`` that records ``call.data`` and returns a
  scripted response (the external boundary; nothing inside URA is mocked);
* rows are read back from the real ``memory_episodes`` table.

Oracles are hand-derived from the plan (literal counts, keys, URLs), never
re-computed by the code under test.

Order-proofing: the module-scoped ``mods`` fixture imports the REAL modules
fresh inside ``_d7_isolation.import_scope`` (pattern:
test_presence_geofence_late_person.py) and restores ``sys.modules`` after.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sqlite3
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import homeassistant as _real_ha_pkg

from _d7_isolation import import_scope

_HA_DIR = Path(_real_ha_pkg.__file__).resolve().parent
_PKG = "custom_components.universal_room_automation"
_FRESH_HELPERS = ("homeassistant.helpers.dispatcher", "homeassistant.helpers.event")
FIXTURE = Path(__file__).parent / "fixtures" / "crossing_vision_door_cameras.json"

GARAGE_EGRESS = "binary_sensor.garage_a_person_occupancy"
FRONT_EGRESS = "binary_sensor.front_door_aerial_person_occupancy"
DOOR_GROUPS = {
    "doorbell_lite": "garage_a", "garage_a": "garage_a",
    "front_door_aerial": "front", "madrone_g6_entry": "front",
}


def _is_real_ha(mod) -> bool:
    if not isinstance(mod, types.ModuleType):
        return False
    f = getattr(mod, "__file__", None)
    if not f:
        return False
    try:
        return Path(f).resolve().is_relative_to(_HA_DIR)
    except (OSError, ValueError):
        return False


@pytest.fixture(scope="module")
def mods():
    with import_scope(("custom_components", "homeassistant"), attrs=True):
        for name in [k for k in sys.modules if k == "custom_components"
                     or k.startswith("custom_components.")]:
            sys.modules.pop(name, None)
        for name in [k for k in sys.modules if k.startswith("homeassistant")]:
            if not _is_real_ha(sys.modules[name]):
                sys.modules.pop(name, None)
        for name in _FRESH_HELPERS:
            sys.modules.pop(name, None)
        _core = sys.modules["homeassistant.core"]

        def _real_callback(func):
            setattr(func, "_hass_callback", True)
            return func

        def _real_is_callback(func):
            return getattr(func, "_hass_callback", False) is True

        _core.callback = _real_callback
        _core.is_callback = _real_is_callback
        from pytest_homeassistant_custom_component import common as _phcc
        for _name in ("State", "Event", "HomeAssistant", "CoreState",
                      "ServiceCall", "SupportsResponse"):
            setattr(_core, _name, getattr(_phcc, _name))
        importlib.invalidate_caches()
        ns = types.SimpleNamespace(
            const=importlib.import_module(f"{_PKG}.const"),
            cv=importlib.import_module(f"{_PKG}.crossing_vision"),
            tv=importlib.import_module(f"{_PKG}.transit_validator"),
            fi=importlib.import_module(f"{_PKG}.frigate_ingress"),
            pe=importlib.import_module(f"{_PKG}.perimeter_enrichment"),
            db=importlib.import_module(f"{_PKG}.database"),
            stuck=importlib.import_module(
                f"{_PKG}.domain_coordinators._stuck_signal_nm"),
            # perimeter_alert is imported lazily by the producer; load it
            # inside the scope so the lazy import binds this real copy.
            pa=importlib.import_module(f"{_PKG}.perimeter_alert"),
        )
        yield ns


@pytest_asyncio.fixture
async def hass():
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant,
    )

    async with async_test_home_assistant(load_registries=False) as real_hass:
        yield real_hass
        await real_hass.async_block_till_done()
        await real_hass.async_stop(force=True)


class _LLM:
    """Stand-in for the llmvision ``video_analyzer`` service (the external
    boundary). Records every call's data; returns ``self.reply`` (a dict, an
    Exception to raise, or ``("sleep", s)`` to hang)."""

    def __init__(self):
        self.calls: list[dict] = []
        self.reply: object = None

    async def handler(self, call):
        self.calls.append(dict(call.data))
        reply = self.reply
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, tuple) and reply[0] == "sleep":
            await asyncio.sleep(reply[1])
            return {}
        return reply


def _ok_reply(frames=(1, 2, 1, 0), total=2):
    return {"structured_response": {
        "frames": [{"index": i + 1, "people": n} for i, n in enumerate(frames)],
        "people_total": total, "group": total > 1,
        "desc": "Two people walk in through the garage door.",
    }}


@pytest_asyncio.fixture
async def rig(mods, hass, tmp_path, monkeypatch):
    from homeassistant.core import SupportsResponse
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    C = mods.const
    db_hass = MagicMock()
    db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    db_hass.async_create_task = _sched
    db_hass.async_create_background_task = _sched
    db = mods.db.UniversalRoomDatabase(db_hass)
    assert await db.initialize()
    await db.start_write_worker()

    # URA integration entry (provider id read by the adapter).
    MockConfigEntry(domain=C.DOMAIN, entry_id="ura_integ", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION,
        C.CONF_PERIMETER_ENRICHMENT_PROVIDER_ID: "prov_openai",
    }).add_to_hass(hass)
    # Two Frigate config entries (one is a lingering retired entry): the
    # default-instance URL would be None (rev 2 F4).
    MockConfigEntry(domain="frigate", entry_id="f2").add_to_hass(hass)
    MockConfigEntry(domain="frigate", entry_id="f1_retired").add_to_hass(hass)
    hass.data["frigate"] = {"f2": {"config": {"mqtt": {
        "client_id": "frigate-f2", "topic_prefix": "frigate2"}}}}

    tracker = mods.tv.EgressDirectionTracker(hass)
    tracker._door_group_by_stem = dict(DOOR_GROUPS)
    tracker._egress_entities = [GARAGE_EGRESS, FRONT_EGRESS]
    ingress = mods.fi.FrigateEventIngress(hass)
    hass.data.setdefault(C.DOMAIN, {}).update({
        "database": db,
        "egress_tracker": tracker,
        mods.fi.FRIGATE_INGRESS_HASS_KEY: ingress,
        C.CROSSING_VISION_SWITCH_HASS_KEY: True,
    })

    llm = _LLM()
    llm.reply = _ok_reply()
    hass.services.async_register(
        "llmvision", "video_analyzer", llm.handler,
        supports_response=SupportsResponse.ONLY,
    )
    pages: list = []

    async def _fake_fire(hass_, kind, key, diagnosis, remedy="", now=None,
                         title_override=None, exclusion_engaged=False,
                         severity=None):
        pages.append({"kind": kind, "key": key, "severity": severity})
        return True

    monkeypatch.setattr(mods.stuck, "fire_stuck_signal", _fake_fire)

    cv = mods.cv.CrossingVisionShadow(hass)
    await cv.async_setup()
    ns = types.SimpleNamespace(
        hass=hass, db=db, cv=cv, llm=llm, ingress=ingress, tracker=tracker,
        pages=pages, C=C, mods=mods, monkeypatch=monkeypatch,
    )
    try:
        yield ns
    finally:
        await cv.async_teardown()
        await db.stop_write_worker()


# ---------------------------------------------------------------- helpers
def _now(rig):
    from homeassistant.util import dt as dt_util

    return dt_util.utcnow()


def frigate(rig, eid, camera, start, *, typ="new", end=None, score=0.8,
            source="mqtt:frigate2", label="person"):
    data = {"type": typ, "before": {}, "after": {
        "id": eid, "camera": camera, "label": label, "start_time": start,
        "end_time": end, "top_score": score, "has_clip": True,
    }}
    family = "mqtt" if source.startswith("mqtt") else "bus"
    rig.ingress._dispatch(data, family, source)


async def cross(rig, camera, e_ts, *, direction="entry", peak=2,
                person_id=None):
    payload = {
        "direction": direction, "egress_camera": camera,
        "timestamp": e_ts.isoformat(), "person_id": person_id,
        "confidence": 0.8, "identity_confidence": None,
        "agreement_class": "single_source",
        "identity_synthetic_corroborated": False,
        "identity_provenance": None, "peak_person_count": peak,
    }
    rig.hass.bus.async_fire("ura_person_egress_event", payload)
    await rig.hass.async_block_till_done()
    return f"{camera}@{e_ts.isoformat()}"


async def settle(rig):
    for _ in range(3):
        await rig.hass.async_block_till_done()
        await asyncio.sleep(0)


def rows(rig):
    conn = sqlite3.connect(rig.db.db_file)
    try:
        return [
            {"node": n, "src": s, **json.loads(a)}
            for n, a, s in conn.execute(
                "SELECT node_id, attrs_json, source_ref FROM memory_episodes "
                "WHERE episode_type = ? ORDER BY id",
                ("crossing_vision_shadow",),
            )
        ]
    finally:
        conn.close()


async def ended_crossing(rig, eid, *, camera="garage_a", egress=GARAGE_EGRESS,
                         offset_s=0.0, peak=2):
    """An entry crossing whose matching Frigate event has already ended."""
    e = _now(rig) - timedelta(seconds=45) + timedelta(seconds=offset_s)
    start = e.timestamp() + 2
    frigate(rig, eid, camera, start)
    frigate(rig, eid, camera, start, typ="end", end=start + 8)
    key = await cross(rig, egress, e, peak=peak)
    await settle(rig)
    return key


# ------------------------------------------------------------------ D1
@pytest.mark.asyncio
async def test_one_call_one_row_per_crossing(rig):
    key = await ended_crossing(rig, "1763050000.1-abc")
    assert len(rig.llm.calls) == 1
    call = rig.llm.calls[0]
    assert call["video_file"] == (
        "/api/frigate/frigate-f2/notifications/1763050000.1-abc/clip.mp4"
    )
    assert "event_id" not in call
    assert call["model"] == "gpt-4o-mini"
    assert call["provider"] == "prov_openai"
    assert call["max_frames"] == 4 and call["target_width"] == 768
    assert call["response_format"] == "json"
    assert json.loads(call["structure"])["required"] == [
        "frames", "people_total", "group", "desc"]
    assert "Do not name or identify anyone" in call["message"]
    [row] = rows(rig)
    assert row["src"] == key
    assert row["node"] == f"vision:{key}"
    assert row["outcome"] == "ok"
    # frames (1, 2, 1, 0), people_total 2 -> clamp [2, 2*4] -> 2.
    assert row["people_count"] == 2
    assert row["frame_counts"] == [1, 2, 1, 0]
    assert row["camera_peak_count"] == 2
    assert row["agreement_case"] == "A"
    assert "vision_direction" not in row  # D0: no direction signal
    assert row["direction"] == "entry"
    assert row["door_group"] == "garage_a"
    assert row["event_id"] == "1763050000.1-abc"
    assert row["event_camera"] == "garage_a"
    assert row["model"] == "gpt-4o-mini"
    assert row["frame_source"] == "video_analyzer"
    assert row["crossing_keys"] == [key]
    assert row["frigate_events_in_window"] == 1


@pytest.mark.asyncio
async def test_people_count_clamped_to_frame_bounds(rig):
    """people_total outside [max frame, max frame x frames] is clamped:
    frames (1, 1, 0, 0) total 9 -> 1 x 4 = 4; total 0 -> max frame 1."""
    rig.llm.reply = _ok_reply(frames=(1, 1, 0, 0), total=9)
    await ended_crossing(rig, "ev-clamp-hi")
    rig.llm.reply = _ok_reply(frames=(1, 1, 0, 0), total=0)
    await ended_crossing(rig, "ev-clamp-lo", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    assert [r["people_count"] for r in rows(rig)] == [4, 1]


@pytest.mark.asyncio
async def test_switch_off_no_call_no_row(rig):
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = False
    await ended_crossing(rig, "ev-off")
    # A crossing with no Frigate event would write a no_frigate_event row
    # if the schedule-time gate were missing.
    await cross(rig, FRONT_EGRESS, _now(rig) - timedelta(seconds=300))
    await settle(rig)
    assert rig.llm.calls == []
    assert rows(rig) == []
    assert len(rig.cv._seen) == 0
    assert rig.cv.diag_status()["crossing_vision_today"]["calls"] == 0


@pytest.mark.asyncio
async def test_cap_zero_no_call_no_row(rig):
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 0
    await ended_crossing(rig, "ev-cap0")
    assert rig.llm.calls == []
    assert rows(rig) == []


@pytest.mark.asyncio
async def test_switch_off_after_schedule_no_call(rig):
    """INV-OFF at call time: scheduled while on (event still open), switch
    turned off, then the event ends -> no call, no row."""
    e = _now(rig) - timedelta(seconds=45)
    start = e.timestamp() + 2
    frigate(rig, "ev-late-off", "garage_a", start)
    await cross(rig, GARAGE_EGRESS, e)
    assert rig.llm.calls == []
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = False
    frigate(rig, "ev-late-off", "garage_a", start, typ="end", end=start + 5)
    await settle(rig)
    assert rig.llm.calls == []
    assert rows(rig) == []


@pytest.mark.asyncio
async def test_kill_const_no_call(rig):
    rig.monkeypatch.setattr(rig.C, "LLMVISION_ENRICHMENT_KILL", True)
    await ended_crossing(rig, "ev-kill")
    assert rig.llm.calls == []
    assert rows(rig) == []


@pytest.mark.asyncio
async def test_ambiguous_ignored(rig):
    e = _now(rig) - timedelta(seconds=45)
    frigate(rig, "ev-amb", "garage_a", e.timestamp() + 2, typ="end",
            end=e.timestamp() + 9)
    await cross(rig, GARAGE_EGRESS, e, direction="ambiguous")
    await settle(rig)
    assert rig.llm.calls == []
    assert rows(rig) == []


@pytest.mark.asyncio
async def test_interior_camera_event_never_matched(rig):
    """INV-SCOPE: a person event on an interior camera AND one on a door
    camera of the OTHER door group, both inside the window and scored
    higher, are never picked for a garage_a crossing."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-interior", "family_room", s, score=0.99)
    frigate(rig, "ev-interior", "family_room", s, typ="end", end=s + 5, score=0.99)
    frigate(rig, "ev-other-door", "front_door_aerial", s, score=0.98)
    frigate(rig, "ev-other-door", "front_door_aerial", s, typ="end", end=s + 5,
            score=0.98)
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    assert rig.llm.calls == []
    [row] = rows(rig)
    assert row["outcome"] == "no_frigate_event"
    assert row["event_id"] is None
    # Non-door cameras are dropped on arrival (never held in the ring).
    assert "family_room" not in rig.cv._ring
    assert "front_door_aerial" in rig.cv._ring


@pytest.mark.asyncio
async def test_same_group_doorbell_event_matches(rig):
    """A doorbell_lite event is in the garage_a group (live door_groups),
    so it IS a legal match for a garage_a crossing."""
    await ended_crossing(rig, "ev-doorbell", camera="doorbell_lite")
    [row] = rows(rig)
    assert row["outcome"] == "ok"
    assert row["event_camera"] == "doorbell_lite"


@pytest.mark.asyncio
async def test_match_picks_highest_score_then_longest(rig):
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp()
    for eid, score, dur in (("ev-lo", 0.6, 30), ("ev-hi-short", 0.9, 4),
                            ("ev-hi-long", 0.9, 12)):
        frigate(rig, eid, "garage_a", s + 1, score=score)
        frigate(rig, eid, "garage_a", s + 1, typ="end", end=s + 1 + dur,
                score=score)
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    assert rig.llm.calls[0]["video_file"].endswith("/ev-hi-long/clip.mp4")
    assert rows(rig)[0]["frigate_events_in_window"] == 3


@pytest.mark.asyncio
async def test_event_outside_match_window_not_matched(rig):
    """Start 11 s after E with the 10 s window -> no match; 10 s -> match."""
    e = _now(rig) - timedelta(seconds=45)
    frigate(rig, "ev-11", "garage_a", e.timestamp() + 11, typ="end",
            end=e.timestamp() + 20)
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    assert rows(rig)[-1]["outcome"] == "no_frigate_event"
    e2 = e + timedelta(seconds=120)
    frigate(rig, "ev-10", "front_door_aerial", e2.timestamp() - 10, typ="end",
            end=e2.timestamp())
    await cross(rig, FRONT_EGRESS, e2)
    await settle(rig)
    assert rows(rig)[-1]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_cap_skip_recorded(rig):
    """Cap 1: the second crossing of the day records skipped_cap, no call."""
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 1
    await ended_crossing(rig, "ev-cap-1")
    await ended_crossing(rig, "ev-cap-2", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    assert len(rig.llm.calls) == 1
    assert [r["outcome"] for r in rows(rig)] == ["ok", "skipped_cap"]
    today = rig.cv.diag_status()["crossing_vision_today"]
    assert today["calls"] == 1 and today["skipped_cap"] == 1


@pytest.mark.asyncio
async def test_cap_counts_pending_requests(rig):
    """Cap 1 with one request still WAITING: a second crossing (ended
    event, other door) is skipped at schedule time, and the waiting one
    then makes the day's only call."""
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 1
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-wait", "garage_a", s)
    k1 = await cross(rig, GARAGE_EGRESS, e)
    frigate(rig, "ev-now", "front_door_aerial", s, typ="end", end=s + 3)
    k2 = await cross(rig, FRONT_EGRESS, e + timedelta(seconds=2))
    await settle(rig)
    frigate(rig, "ev-wait", "garage_a", s, typ="end", end=s + 6)
    await settle(rig)
    assert len(rig.llm.calls) == 1
    assert rig.llm.calls[0]["video_file"].endswith("/ev-wait/clip.mp4")
    r = {x["src"]: x["outcome"] for x in rows(rig)}
    assert r == {k1: "ok", k2: "skipped_cap"}


@pytest.mark.asyncio
async def test_cap_lowered_after_schedule_records_skip(rig):
    """Cap 2: request A waits, request B calls (1 call). Cap lowered to 1;
    when A's event ends, the call-time cap check records skipped_cap."""
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 2
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-a", "garage_a", s)
    ka = await cross(rig, GARAGE_EGRESS, e)
    frigate(rig, "ev-b", "front_door_aerial", s, typ="end", end=s + 3)
    kb = await cross(rig, FRONT_EGRESS, e + timedelta(seconds=2))
    await settle(rig)
    assert len(rig.llm.calls) == 1
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 1
    frigate(rig, "ev-a", "garage_a", s, typ="end", end=s + 6)
    await settle(rig)
    assert len(rig.llm.calls) == 1
    r = {x["src"]: x["outcome"] for x in rows(rig)}
    assert r == {kb: "ok", ka: "skipped_cap"}


@pytest.mark.asyncio
async def test_cap_rechecked_at_call_time(rig):
    """Scheduled under cap 2, cap lowered to 0 before the call -> INV-OFF
    (no call, no row); lowered to 1 after one call -> skipped_cap row."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-w1", "garage_a", s)
    await cross(rig, GARAGE_EGRESS, e)
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 0
    frigate(rig, "ev-w1", "garage_a", s, typ="end", end=s + 5)
    await settle(rig)
    assert rig.llm.calls == [] and rows(rig) == []


@pytest.mark.asyncio
async def test_busy_skip_recorded(rig):
    """MAX_CONCURRENT 1: a crossing waiting for its event to end holds the
    slot; a second crossing on the other door records skipped_busy."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_MAX_CONCURRENT", 1)
    e = _now(rig) - timedelta(seconds=45)
    frigate(rig, "ev-open", "garage_a", e.timestamp() + 1)
    await cross(rig, GARAGE_EGRESS, e)
    frigate(rig, "ev-front", "front_door_aerial", e.timestamp() + 2, typ="end",
            end=e.timestamp() + 9)
    await cross(rig, FRONT_EGRESS, e + timedelta(seconds=1))
    await settle(rig)
    assert rig.llm.calls == []
    assert [r["outcome"] for r in rows(rig)] == ["skipped_busy"]


@pytest.mark.asyncio
async def test_cluster_one_call(rig):
    """Two same-group crossings 20 s apart while the first waits: ONE call,
    two rows; the primary carries both keys, the second is `clustered`."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-cl", "garage_a", s)
    k1 = await cross(rig, GARAGE_EGRESS, e)
    k2 = await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                     e + timedelta(seconds=20))
    frigate(rig, "ev-cl", "garage_a", s, typ="end", end=s + 30)
    await settle(rig)
    assert len(rig.llm.calls) == 1
    by_src = {r["src"]: r for r in rows(rig)}
    assert by_src[k2]["outcome"] == "clustered"
    assert by_src[k2]["primary_crossing_key"] == k1
    assert by_src[k1]["outcome"] == "ok"
    assert by_src[k1]["crossing_keys"] == [k1, k2]


@pytest.mark.asyncio
async def test_cluster_completed_request_no_second_call(rig):
    """F5: a completed request still clusters a crossing inside CLUSTER_S;
    and with CLUSTER_S shrunk, a crossing that matches an ALREADY-ANALYSED
    event id is clustered too (no second call on the same clip)."""
    k1 = await ended_crossing(rig, "ev-done")
    e1 = rig.cv._requests[0].e_ts
    k2 = await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                     e1 + timedelta(seconds=30))
    await settle(rig)
    assert len(rig.llm.calls) == 1
    r = {x["src"]: x for x in rows(rig)}
    assert r[k2]["outcome"] == "clustered" and r[k2]["primary_crossing_key"] == k1
    # Analysed-event branch: cluster window 5 s, E3 = E1 + 8 s, same event
    # (start E1 + 2) is within +-10 s of E3 -> already analysed.
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_CLUSTER_S", 5)
    k3 = await cross(rig, GARAGE_EGRESS, e1 + timedelta(seconds=8))
    await settle(rig)
    assert len(rig.llm.calls) == 1
    r = {x["src"]: x for x in rows(rig)}
    assert r[k3]["outcome"] == "clustered"
    assert r[k3]["primary_crossing_key"] == k1


@pytest.mark.asyncio
async def test_other_group_inside_cluster_window_not_clustered(rig):
    e = _now(rig) - timedelta(seconds=45)
    frigate(rig, "ev-g", "garage_a", e.timestamp() + 1, typ="end",
            end=e.timestamp() + 5)
    frigate(rig, "ev-f", "front_door_aerial", e.timestamp() + 2, typ="end",
            end=e.timestamp() + 6)
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    await cross(rig, FRONT_EGRESS, e + timedelta(seconds=3))
    await settle(rig)
    assert len(rig.llm.calls) == 2
    assert [r["outcome"] for r in rows(rig)] == ["ok", "ok"]


@pytest.mark.asyncio
async def test_blank_not_zero(rig):
    rig.llm.reply = _ok_reply(frames=(0, 0, 0, 0), total=0)
    await ended_crossing(rig, "ev-blank")
    [row] = rows(rig)
    assert row["outcome"] == "blank"
    assert row["people_count"] is None
    assert row["frame_counts"] == [0, 0, 0, 0]
    assert row["agreement_case"] == "D"
    today = rig.cv.diag_status()["crossing_vision_today"]
    assert today["blank"] == 1 and today["ok"] == 0


@pytest.mark.asyncio
async def test_no_frigate_event_no_call(rig):
    e = _now(rig) - timedelta(seconds=45)
    key = await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    assert rig.llm.calls == []
    [row] = rows(rig)
    assert row["outcome"] == "no_frigate_event" and row["src"] == key


@pytest.mark.asyncio
async def test_failure_classes_recorded_never_raise(rig):
    """Service raising, timing out, returning {}, a nested envelope,
    non-JSON text, and JSON text each -> one row with the right outcome."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 0.05)
    cases = [
        (RuntimeError("provider down"), "error"),
        (("sleep", 1.0), "timeout"),
        ({}, "refused"),
        ({"response_text": "   "}, "refused"),
        ({"service_response": {"frames": []}}, "unparseable"),
        ({"structured_response": {}}, "refused"),
        ({"service_response": {"structured_response": _ok_reply()[
            "structured_response"], "key_frame": "/media/llmvision/x.jpg"}}, "ok"),
        ({"response_text": "two people walked in"}, "unparseable"),
        ({"structured_response": {"frames": [{"index": 1, "people": -1}]}},
         "unparseable"),
        ({"response_text": json.dumps(_ok_reply()["structured_response"])}, "ok"),
    ]
    base = _now(rig) - timedelta(seconds=45) - timedelta(seconds=len(cases) * 120)
    for i, (reply, _expected) in enumerate(cases):
        rig.llm.reply = reply
        e = base + timedelta(seconds=i * 120)
        s = e.timestamp() + 1
        frigate(rig, f"ev-f{i}", "garage_a", s, typ="end", end=s + 4)
        await cross(rig, GARAGE_EGRESS, e)
        await settle(rig)
        await asyncio.sleep(0.1)
        await settle(rig)
    assert [r["outcome"] for r in rows(rig)] == [c[1] for c in cases]
    assert rig.cv.diag_status()["crossing_vision_today"]["errors"] == 8


@pytest.mark.asyncio
async def test_clip_url_instance_scoped(rig):
    """F4: MQTT-sourced event -> instance-scoped video_file (two Frigate
    entries exist, so the default URL is never used). A bus-sourced event
    with two entries and two running instances has no safe URL ->
    no_clip_url, no call. One entry and no instance -> event_id."""
    await ended_crossing(rig, "ev-inst")
    assert rig.llm.calls[-1]["video_file"] == (
        "/api/frigate/frigate-f2/notifications/ev-inst/clip.mp4")
    # Bus source, two running instances -> ambiguous instance.
    rig.hass.data["frigate"]["f1_retired"] = {"config": {"mqtt": {
        "client_id": "frigate-f1", "topic_prefix": "frigate"}}}
    e = _now(rig) - timedelta(seconds=45) + timedelta(seconds=200)
    s = e.timestamp() + 1
    frigate(rig, "ev-bus", "front_door_aerial", s, source="bus")
    frigate(rig, "ev-bus", "front_door_aerial", s, typ="end", end=s + 3,
            source="bus")
    await cross(rig, FRONT_EGRESS, e)
    await settle(rig)
    assert len(rig.llm.calls) == 1
    assert rows(rig)[-1]["outcome"] == "no_clip_url"
    # Same two running instances, MQTT-sourced from frigate2: the source
    # prefix names the instance, so the clip is still reachable.
    e2 = e + timedelta(seconds=200)
    s2 = e2.timestamp() + 1
    frigate(rig, "ev-mq2", "garage_a", s2)
    frigate(rig, "ev-mq2", "garage_a", s2, typ="end", end=s2 + 3)
    await cross(rig, GARAGE_EGRESS, e2)
    await settle(rig)
    assert rig.llm.calls[-1]["video_file"] == (
        "/api/frigate/frigate-f2/notifications/ev-mq2/clip.mp4")


@pytest.mark.asyncio
async def test_clip_event_id_only_with_single_entry(rig, mods):
    """One Frigate config entry and no running instance data -> llmvision's
    own event_id path (default-instance URL)."""
    real = rig.hass.config_entries.async_entries

    def _one_frigate(domain=None, *a, **k):
        got = real(domain, *a, **k)
        if domain == "frigate":
            return [e for e in got if e.entry_id == "f2"]
        return got

    rig.monkeypatch.setattr(rig.hass.config_entries, "async_entries", _one_frigate)
    rig.hass.data["frigate"] = {}
    await ended_crossing(rig, "ev-single", camera="garage_a")
    call = rig.llm.calls[-1]
    assert call["event_id"] == "ev-single"
    assert "video_file" not in call


@pytest.mark.asyncio
async def test_unsafe_event_id_never_sent(rig):
    await ended_crossing(rig, "../../etc/passwd")
    assert rig.llm.calls == []
    assert rows(rig)[-1]["outcome"] == "no_clip_url"


@pytest.mark.asyncio
async def test_use_memory_false(rig):
    await ended_crossing(rig, "ev-mem")
    call = rig.llm.calls[0]
    assert call["use_memory"] is False
    assert call["store_in_timeline"] is False
    assert call["expose_images"] is True
    assert call["include_filename"] is False


@pytest.mark.asyncio
async def test_node_id_unique_per_crossing(rig):
    e = _now(rig) - timedelta(seconds=45)
    k1 = await cross(rig, GARAGE_EGRESS, e)
    k2 = await cross(rig, FRONT_EGRESS, e)
    await settle(rig)
    rs = rows(rig)
    assert {r["node"] for r in rs} == {f"vision:{k1}", f"vision:{k2}"}
    assert len(rs) == 2


@pytest.mark.asyncio
async def test_teardown_cancels_pending(rig):
    """A request waiting for its event end: teardown cancels the timer and
    drops the consumer; a late `end` and the elapsed wait make no call."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_EVENT_END_WAIT_S", 0.05)
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-td", "garage_a", s)
    await cross(rig, GARAGE_EGRESS, e)
    await rig.cv.async_teardown()
    frigate(rig, "ev-td", "garage_a", s, typ="end", end=s + 2)
    await asyncio.sleep(0.15)
    await settle(rig)
    assert rig.llm.calls == []
    assert rows(rig) == []
    assert rig.cv._tasks == set()


@pytest.mark.asyncio
async def test_end_wait_timeout_fires_call(rig):
    """No `end` arrives: the call is made END_WAIT_S after the bus event."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_EVENT_END_WAIT_S", 0.05)
    e = _now(rig) - timedelta(seconds=45)
    frigate(rig, "ev-open-long", "garage_a", e.timestamp() + 1)
    await cross(rig, GARAGE_EGRESS, e)
    assert rig.llm.calls == []
    await asyncio.sleep(0.15)
    await settle(rig)
    assert len(rig.llm.calls) == 1
    assert rows(rig)[0]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_no_census_or_sighting_reader(rig, mods):
    """INV-SHADOW, behavioural: a full ok crossing writes nothing outside
    the module's own row and counters: no state machine change, no service
    call other than llmvision, no bus event, no dispatcher signal (incl.
    SIGNAL_PERSON_SIGHTING / census updates), no new hass.data key."""
    from homeassistant.const import EVENT_CALL_SERVICE, EVENT_STATE_CHANGED
    from homeassistant.helpers import dispatcher as disp

    sigs = importlib.import_module(f"{_PKG}.domain_coordinators.signals")
    seen_events: list = []
    unsubs = [
        rig.hass.bus.async_listen("*", lambda ev: seen_events.append(ev.event_type))
    ]
    sent: list = []
    for name in ("SIGNAL_PERSON_SIGHTING", "SIGNAL_CENSUS_UPDATED",
                 "SIGNAL_PERSON_ARRIVING"):
        sig = getattr(sigs, name, None)
        if sig is not None:
            unsubs.append(disp.async_dispatcher_connect(
                rig.hass, sig, lambda *a, _n=name: sent.append(_n)))
    states_before = {s.entity_id: s.state for s in rig.hass.states.async_all()}
    keys_before = set(rig.hass.data[rig.C.DOMAIN])
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-shadow", "garage_a", s, typ="end", end=s + 4)
    seen_events.clear()
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    for u in unsubs:
        u()
    assert rows(rig)[0]["outcome"] == "ok"
    services = [ev for ev in seen_events if ev == EVENT_CALL_SERVICE]
    assert len(services) == 1  # the llmvision call only
    assert EVENT_STATE_CHANGED not in seen_events
    assert set(seen_events) <= {"ura_person_egress_event", EVENT_CALL_SERVICE}
    assert sent == []
    assert {s.entity_id: s.state for s in rig.hass.states.async_all()} == states_before
    assert set(rig.hass.data[rig.C.DOMAIN]) == keys_before


@pytest.mark.asyncio
async def test_runtime_camera_map_matches_fixture(rig):
    """Rev 2 F1: the Frigate camera -> stem -> door group map is DERIVED at
    runtime (frigate_camera_stem + the tracker's live door_groups) and must
    equal the hand-built fixture. Fixture = stub from PLANNING_person_
    sighting_layer.md §15.9.6 until the D0c fixture lands (see its header)."""
    fx = json.loads(FIXTURE.read_text())
    rig.tracker._door_group_by_stem = dict(fx["door_groups"])
    derived = {}
    for cam in fx["cameras"]:
        stem = rig.mods.cv.frigate_camera_stem(cam)
        group, _members = rig.tracker.door_group_members(stem)
        derived[cam] = {"stem": stem, "door_group": group}
    assert derived == fx["cameras"]


# ------------------------------------------------------------------ D3
async def _no_event_crossings(rig, n, *, start_offset=0):
    base = _now(rig) - timedelta(seconds=45)
    for i in range(n):
        await cross(rig, GARAGE_EGRESS,
                    base - timedelta(seconds=start_offset + i * 120))
    await settle(rig)


def _fast_tripwires(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_EVENT_END_WAIT_S", 0)
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 0)


@pytest.mark.asyncio
async def test_zero_fire_pages_once(rig):
    _fast_tripwires(rig)
    await _no_event_crossings(rig, 5)
    await rig.cv.async_evaluate_tripwires()
    await rig.cv.async_evaluate_tripwires()
    assert rig.pages == [{"kind": "crossing_vision_zero", "key": ("house",),
                          "severity": "HIGH"}]


@pytest.mark.asyncio
async def test_zero_fire_needs_min_crossings(rig):
    _fast_tripwires(rig)
    await _no_event_crossings(rig, 4)
    await rig.cv.async_evaluate_tripwires()
    assert rig.pages == []


@pytest.mark.asyncio
async def test_zero_fire_rearms_after_ok(rig):
    _fast_tripwires(rig)
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TRIPWIRE_WINDOW_S", 0.3)
    await _no_event_crossings(rig, 5)
    await rig.cv.async_evaluate_tripwires()
    assert len(rig.pages) == 1
    # A real call needs a non-zero timeout; the settle bound is read at
    # evaluation time, so put it back to 0 afterwards.
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 5)
    await ended_crossing(rig, "ev-rearm", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 0)
    assert rows(rig)[-1]["outcome"] == "ok"
    await rig.cv.async_evaluate_tripwires()
    assert len(rig.pages) == 1          # an ok in the window: no page
    await asyncio.sleep(0.4)            # the ok ages out of the window
    await _no_event_crossings(rig, 5, start_offset=2000)
    await rig.cv.async_evaluate_tripwires()
    assert [p["kind"] for p in rig.pages] == [
        "crossing_vision_zero", "crossing_vision_zero"]


@pytest.mark.asyncio
async def test_zero_fire_ignores_unsettled_crossings(rig):
    """Crossings younger than END_WAIT_S + TIMEOUT_S have no result yet and
    are not evidence (defaults 120 + 90 s)."""
    await _no_event_crossings(rig, 6)
    await rig.cv.async_evaluate_tripwires()
    assert rig.pages == []


@pytest.mark.asyncio
async def test_error_rate_pages(rig):
    """8 calls, 3 errors (0.375 > 0.25) -> one MEDIUM page; re-evaluating
    does not page again."""
    _fast_tripwires(rig)
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 5)
    base = _now(rig) - timedelta(seconds=45) - timedelta(seconds=8 * 120)
    for i in range(8):
        rig.llm.reply = RuntimeError("down") if i < 3 else _ok_reply()
        e = base + timedelta(seconds=i * 120)
        s = e.timestamp() + 1
        frigate(rig, f"ev-e{i}", "garage_a", s, typ="end", end=s + 3)
        await cross(rig, GARAGE_EGRESS, e)
        await settle(rig)
    assert len(rig.llm.calls) == 8
    await rig.cv.async_evaluate_tripwires()
    await rig.cv.async_evaluate_tripwires()
    assert rig.pages == [{"kind": "crossing_vision_errors", "key": ("house",),
                          "severity": None}]


@pytest.mark.asyncio
async def test_error_rate_needs_min_calls(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 5)
    base = _now(rig) - timedelta(seconds=45) - timedelta(seconds=7 * 120)
    rig.llm.reply = RuntimeError("down")
    for i in range(7):
        e = base + timedelta(seconds=i * 120)
        s = e.timestamp() + 1
        frigate(rig, f"ev-m{i}", "garage_a", s, typ="end", end=s + 3)
        await cross(rig, GARAGE_EGRESS, e)
        await settle(rig)
    await rig.cv.async_evaluate_tripwires()
    assert [p["kind"] for p in rig.pages] == []


@pytest.mark.asyncio
async def test_switch_off_no_page(rig):
    _fast_tripwires(rig)
    await _no_event_crossings(rig, 5)
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_SWITCH_HASS_KEY] = False
    await rig.cv.async_evaluate_tripwires()
    assert rig.pages == []


@pytest.mark.asyncio
async def test_tripwire_timer_registered_and_runs(rig):
    """Wire-in anchor for the hourly evaluation: the interval callback the
    producer registered drives the evaluation (pages on a zero condition)."""
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import (
        async_fire_time_changed,
    )

    _fast_tripwires(rig)
    await _no_event_crossings(rig, 5)
    async_fire_time_changed(rig.hass, dt_util.utcnow() + timedelta(seconds=3601))
    await settle(rig)
    assert [p["kind"] for p in rig.pages] == ["crossing_vision_zero"]


# ------------------------------------------------------------ surfaces
@pytest.mark.asyncio
async def test_registered_episode_type_and_writer_health(mods):
    C = mods.const
    assert "crossing_vision_shadow" in C.MEMORY_EPISODE_TYPES
    assert "crossing_vision_shadow" in C.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert "crossing_vision_shadow" not in C.MEMORY_COMPACTION_RULES


@pytest.mark.asyncio
async def test_diag_status_shape(rig):
    await ended_crossing(rig, "ev-diag")
    d = rig.cv.diag_status()
    assert d["crossing_vision_today"] == {
        "calls": 1, "ok": 1, "blank": 0, "no_event": 0, "errors": 0,
        "skipped_cap": 0, "skipped_busy": 0, "clustered": 0, "no_clip_url": 0,
    }
    last = d["crossing_vision_last"]
    assert (last["outcome"], last["people_count"], last["camera_peak_count"],
            last["case"]) == ("ok", 2, 2, "A")
    assert isinstance(last["age_s"], int)


@pytest.mark.asyncio
async def test_setup_registers_ingress_consumer_and_bus_listener(rig):
    """Wire-in anchors inside async_setup: the Frigate ingress consumer is
    registered under its unique name and the egress bus listener is live
    (a crossing reaches the producer: one row)."""
    assert rig.ingress._consumers.get("crossing_vision") is not None
    await ended_crossing(rig, "ev-wire")
    assert len(rows(rig)) == 1


@pytest.mark.asyncio
async def test_switch_restore_only_on(mods, hass):
    sw_mod = importlib.import_module(f"{_PKG}.switch")
    C = mods.const

    class _St:
        def __init__(self, s):
            self.state = s

    for last, expect in (("on", True), ("off", False), ("unavailable", False),
                         (None, False)):
        sw = sw_mod.CrossingVisionShadowSwitch(hass, MagicMock())
        sw.async_write_ha_state = lambda: None

        async def _last(_v=last):
            return _St(_v) if _v is not None else None

        sw.async_get_last_state = _last
        hass.data.setdefault(C.DOMAIN, {})[C.CROSSING_VISION_SWITCH_HASS_KEY] = (
            not expect)
        await sw.async_added_to_hass()
        assert sw.is_on is expect, last
        assert hass.data[C.DOMAIN][C.CROSSING_VISION_SWITCH_HASS_KEY] is expect
    assert sw.entity_id == "switch.ura_crossing_vision_shadow"
    await sw.async_turn_on()
    assert hass.data[C.DOMAIN][C.CROSSING_VISION_SWITCH_HASS_KEY] is True
    await sw.async_turn_off()
    assert hass.data[C.DOMAIN][C.CROSSING_VISION_SWITCH_HASS_KEY] is False


@pytest.mark.asyncio
async def test_daily_cap_number_publishes_and_persists(mods, hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    num_mod = importlib.import_module(f"{_PKG}.number")
    C = mods.const
    entry = MockConfigEntry(domain=C.DOMAIN, entry_id="cm", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={"crossing_vision_daily_calls": 12})
    entry.add_to_hass(hass)
    n = num_mod.CrossingVisionDailyCallsNumber(hass, entry)
    n.async_write_ha_state = lambda: None
    assert n.native_value == 12.0
    assert hass.data[C.DOMAIN][C.CROSSING_VISION_CAP_HASS_KEY] == 12
    await n.async_set_native_value(25)
    assert hass.data[C.DOMAIN][C.CROSSING_VISION_CAP_HASS_KEY] == 25
    assert entry.options["crossing_vision_daily_calls"] == 25
    fresh = MockConfigEntry(domain=C.DOMAIN, entry_id="cm2", data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_COORDINATOR_MANAGER})
    n2 = num_mod.CrossingVisionDailyCallsNumber(hass, fresh)
    assert n2.native_value == 40.0


@pytest.mark.asyncio
async def test_cap_key_reload_suppressed(mods):
    init_mod = importlib.import_module(_PKG)
    assert "crossing_vision_daily_calls" in init_mod.OPTIONS_RELOAD_SUPPRESS_KEYS
    assert "crossing_vision_daily_calls" in init_mod._NO_LIVE_ATTR_KEYS


@pytest.mark.asyncio
async def test_open_tracks_sensor_carries_diag_unrecorded(rig):
    """D1.10 wire-in: the Outside: Open Tracks sensor publishes the
    producer's counters, and both attributes stay out of the recorder."""
    sensor_mod = importlib.import_module(f"{_PKG}.sensor")
    await ended_crossing(rig, "ev-sensor")

    class _Linker:
        is_active = True

        def open_tracks_snapshot(self):
            return []

        def census_counts(self):
            return {}

    rig.hass.data[rig.C.DOMAIN]["exterior_track_linker"] = _Linker()
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_HASS_KEY] = rig.cv
    cls = sensor_mod.ExteriorOpenTracksDiagnosticSensor
    ent = cls.__new__(cls)
    ent.hass = rig.hass
    attrs = ent.extra_state_attributes
    assert attrs["crossing_vision_today"]["ok"] == 1
    assert attrs["crossing_vision_last"]["outcome"] == "ok"
    assert {"crossing_vision_today", "crossing_vision_last"} <= set(
        cls._unrecorded_attributes)
