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
            # Platforms used by the surface tests, imported inside the scope
            # so a stale or stubbed copy left in sys.modules by an earlier
            # file can never be picked up at test time (the order-dependent
            # test_switch_restore_only_on failure in the full run).
            switch=importlib.import_module(f"{_PKG}.switch"),
            number=importlib.import_module(f"{_PKG}.number"),
            sensor=importlib.import_module(f"{_PKG}.sensor"),
            init=importlib.import_module(_PKG),
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
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    return f"{camera}@{e_ts.isoformat()}"


async def settle(rig):
    for _ in range(3):
        await rig.hass.async_block_till_done(wait_background_tasks=True)
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
    assert call["model"] == "gpt-6-luna"
    assert call["provider"] == "01M7B731T26P2HXVW77AQR62PP"
    assert call["max_tokens"] == 1500
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
    assert row["model"] == "gpt-6-luna"
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
    assert len(rows(rig)) == 2  # M16: exactly one row per crossing


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
    sw_mod = mods.switch
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

    num_mod = mods.number
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
    init_mod = mods.init
    assert "crossing_vision_daily_calls" in init_mod.OPTIONS_RELOAD_SUPPRESS_KEYS
    assert "crossing_vision_daily_calls" in init_mod._NO_LIVE_ATTR_KEYS


@pytest.mark.asyncio
async def test_open_tracks_sensor_carries_diag_unrecorded(rig):
    """D1.10 wire-in: the Outside: Open Tracks sensor publishes the
    producer's counters, and both attributes stay out of the recorder."""
    sensor_mod = rig.mods.sensor
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


# ===================================================================
# Fix-up round (Review C must-fix + reviews A/B). Each test names the
# Review C mutation id(s) it kills.
# ===================================================================
def fire_cross_nowait(rig, camera, e_ts, *, direction="entry", peak=2):
    """Fire a crossing WITHOUT async_block_till_done (used while an
    in-flight call or row write must stay in flight)."""
    rig.hass.bus.async_fire("ura_person_egress_event", {
        "direction": direction, "egress_camera": camera,
        "timestamp": e_ts.isoformat(), "person_id": None,
        "identity_provenance": None, "peak_person_count": peak,
    })
    return f"{camera}@{e_ts.isoformat()}"


async def spin(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


# ---------------------------------------------------- wiring (M120/M122)
@pytest.mark.asyncio
async def test_setup_publishes_producer_and_teardown_awaits(mods, hass):
    """M120 / M119 / M121 / M122: the REAL module entrypoints. Setup
    publishes the producer under CROSSING_VISION_HASS_KEY with its bus
    listener and Frigate consumer live; a second setup (partial reload)
    tears the first down; teardown pops the key AND awaits the producer's
    own teardown (listener and consumer gone)."""
    C, cvm = mods.const, mods.cv
    ingress = mods.fi.FrigateEventIngress(hass)
    hass.data.setdefault(C.DOMAIN, {})[mods.fi.FRIGATE_INGRESS_HASS_KEY] = ingress
    base = hass.bus.async_listeners().get("ura_person_egress_event", 0)

    await cvm.async_setup_crossing_vision(hass)
    cv1 = hass.data[C.DOMAIN].get("crossing_vision")
    assert isinstance(cv1, cvm.CrossingVisionShadow)
    assert ingress._consumers.get("crossing_vision") is not None
    assert hass.bus.async_listeners().get("ura_person_egress_event", 0) == base + 1

    await cvm.async_setup_crossing_vision(hass)
    cv2 = hass.data[C.DOMAIN].get("crossing_vision")
    assert cv2 is not cv1
    assert cv1._torn_down is True
    assert hass.bus.async_listeners().get("ura_person_egress_event", 0) == base + 1

    await cvm.async_teardown_crossing_vision(hass)
    assert "crossing_vision" not in hass.data[C.DOMAIN]
    assert cv2._torn_down is True
    assert ingress._consumers.get("crossing_vision") is None
    assert hass.bus.async_listeners().get("ura_person_egress_event", 0) == base


@pytest.mark.asyncio
async def test_setup_failure_unsubscribes_bus_listener(mods, hass, monkeypatch):
    """Review B3: the Frigate consumer registration raises after the bus
    listener was added -> no producer published and no leaked listener."""
    C, cvm = mods.const, mods.cv
    hass.data.setdefault(C.DOMAIN, {})
    base = hass.bus.async_listeners().get("ura_person_egress_event", 0)

    def _boom(*_a, **_k):
        raise RuntimeError("consumer registration failed")

    monkeypatch.setattr(mods.fi, "register_frigate_consumer", _boom)
    await cvm.async_setup_crossing_vision(hass)
    assert "crossing_vision" not in hass.data[C.DOMAIN]
    assert hass.bus.async_listeners().get("ura_person_egress_event", 0) == base


# ------------------------------------------------ platforms (S06 / N01)
def _cm_entry(mods, hass, entry_id="cm_plat"):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    C = mods.const
    e = MockConfigEntry(domain=C.DOMAIN, entry_id=entry_id, data={
        C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_COORDINATOR_MANAGER})
    e.add_to_hass(hass)
    return e


@pytest.mark.asyncio
async def test_switch_platform_registers_crossing_vision_switch(mods, hass):
    """S06: the REAL switch.async_setup_entry for the CM entry yields the
    crossing-vision shadow switch."""
    added: list = []
    await mods.switch.async_setup_entry(
        hass, _cm_entry(mods, hass), lambda ents, *a, **k: added.extend(ents))
    hits = [e for e in added
            if type(e).__name__ == "CrossingVisionShadowSwitch"]
    assert len(hits) == 1
    assert hits[0].entity_id == "switch.ura_crossing_vision_shadow"


@pytest.mark.asyncio
async def test_number_platform_registers_daily_calls_number(mods, hass):
    """N01: the REAL number.async_setup_entry for the CM entry yields the
    daily-cap Number, which publishes the cap key."""
    added: list = []
    await mods.number.async_setup_entry(
        hass, _cm_entry(mods, hass), lambda ents, *a, **k: added.extend(ents))
    hits = [e for e in added
            if type(e).__name__ == "CrossingVisionDailyCallsNumber"]
    assert len(hits) == 1
    assert hass.data[mods.const.DOMAIN][
        mods.const.CROSSING_VISION_CAP_HASS_KEY] == 40


# ------------------------------------------------------ INV-OFF (M04)
@pytest.mark.asyncio
async def test_switch_key_absent_means_off(rig):
    """M04: boot-before-restore (switch key not yet published) = OFF: no
    call, no row, no trip-wire sample."""
    rig.hass.data[rig.C.DOMAIN].pop(rig.C.CROSSING_VISION_SWITCH_HASS_KEY)
    await ended_crossing(rig, "ev-nokey")
    await cross(rig, FRONT_EGRESS, _now(rig) - timedelta(seconds=300))
    await settle(rig)
    assert rig.llm.calls == []
    assert rows(rig) == []
    assert len(rig.cv._seen) == 0


# -------------------------------------------------- day roll (M91/M92/M09)
@pytest.mark.asyncio
async def test_daily_cap_resets_at_local_midnight(rig):
    """Cap 1: one call, the next crossing is skipped_cap; after the local
    date rolls, the next crossing (schedule-time gate on the egress path)
    makes a call again."""
    from homeassistant.util import dt as real_dt

    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 1
    await ended_crossing(rig, "ev-d1")
    await ended_crossing(rig, "ev-d2", camera="front_door_aerial",
                         egress=FRONT_EGRESS)
    assert len(rig.llm.calls) == 1

    shim = types.SimpleNamespace(
        now=lambda *a, **k: real_dt.now(*a, **k) + timedelta(days=1),
        utcnow=real_dt.utcnow,
        parse_datetime=real_dt.parse_datetime,
    )
    rig.monkeypatch.setattr(rig.mods.cv, "dt_util", shim)
    await ended_crossing(rig, "ev-d3", offset_s=300)
    assert len(rig.llm.calls) == 2
    assert [r["outcome"] for r in rows(rig)] == ["ok", "skipped_cap", "ok"]


# --------------------------------------------- cap double count (A1/B4)
@pytest.mark.asyncio
async def test_cap_does_not_double_count_in_flight_call(rig):
    """Cap 2 with one call IN FLIGHT: a second crossing (other door, event
    ended) is still allowed its call (1 made + 0 waiting < 2)."""
    rig.hass.data[rig.C.DOMAIN][rig.C.CROSSING_VISION_CAP_HASS_KEY] = 2
    rig.llm.reply = ("sleep", 0.3)
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-if1", "garage_a", s, typ="end", end=s + 3)
    fire_cross_nowait(rig, GARAGE_EGRESS, e)
    for _ in range(50):
        await asyncio.sleep(0)
        if rig.llm.calls:
            break
    assert len(rig.llm.calls) == 1
    rig.llm.reply = _ok_reply()
    frigate(rig, "ev-if2", "front_door_aerial", s, typ="end", end=s + 3)
    k2 = fire_cross_nowait(rig, FRONT_EGRESS, e + timedelta(seconds=2))
    await asyncio.sleep(0.4)
    await settle(rig)
    assert len(rig.llm.calls) == 2
    assert {r["src"]: r["outcome"] for r in rows(rig)}[k2] == "ok"


# ------------------------------------------------ cluster / bounds
@pytest.mark.asyncio
async def test_cluster_join_writes_exactly_one_row(rig):
    """M16: a crossing that joins an open request gets ONE clustered row
    (no fall-through to a second join or a match)."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-cl1", "garage_a", s)
    k1 = await cross(rig, GARAGE_EGRESS, e)
    k2 = await cross(rig, "binary_sensor.doorbell_lite_person_occupancy",
                     e + timedelta(seconds=20))
    frigate(rig, "ev-cl1", "garage_a", s, typ="end", end=s + 30)
    await settle(rig)
    srcs = [r["src"] for r in rows(rig)]
    assert sorted(srcs) == sorted([k1, k2])
    assert len(srcs) == 2


@pytest.mark.asyncio
async def test_ring_bounded_per_camera(rig):
    """M35: the per-camera ring keeps the newest EVENT_RING events."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_EVENT_RING", 2)
    s = _now(rig).timestamp()
    for i in range(3):
        frigate(rig, f"ev-r{i}", "garage_a", s + i)
    assert list(rig.cv._ring["garage_a"]) == ["ev-r1", "ev-r2"]


@pytest.mark.asyncio
async def test_done_request_pruned_after_horizon(rig):
    """M45: a done request older than 2 x CLUSTER_S (120 s) is pruned when
    the next crossing arrives."""
    await ended_crossing(rig, "ev-p1")
    assert len(rig.cv._requests) == 1
    await ended_crossing(rig, "ev-p2", camera="front_door_aerial",
                         egress=FRONT_EGRESS, offset_s=200)
    assert [r.event["id"] for r in rig.cv._requests] == ["ev-p2"]


@pytest.mark.asyncio
async def test_waiting_request_never_pruned(rig):
    """M46: a WAITING request older than the horizon is kept (only done
    ones are pruned) and still makes its call when the event ends."""
    e = _now(rig) - timedelta(seconds=245)
    s = e.timestamp() + 1
    frigate(rig, "ev-w-old", "garage_a", s)
    await cross(rig, GARAGE_EGRESS, e)
    await cross(rig, FRONT_EGRESS, e + timedelta(seconds=200))
    await settle(rig)
    assert [r.status for r in rig.cv._requests] == ["waiting"]
    frigate(rig, "ev-w-old", "garage_a", s, typ="end", end=s + 5)
    await settle(rig)
    assert len(rig.llm.calls) == 1


@pytest.mark.asyncio
async def test_non_person_event_never_enters_ring(rig):
    """M32: a car event on a door camera is not held or matched."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-car", "garage_a", s, label="car")
    frigate(rig, "ev-car", "garage_a", s, typ="end", end=s + 4, label="car")
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    assert "ev-car" not in rig.cv._ring.get("garage_a", {})
    assert rig.llm.calls == []
    assert rows(rig)[0]["outcome"] == "no_frigate_event"


# ------------------------------------------------ URL safety (M73/M74/F02)
@pytest.mark.asyncio
async def test_unsafe_instance_id_never_sent(rig):
    """M73: an instance id that is not a safe path token -> no_clip_url."""
    rig.hass.data["frigate"]["f2"]["config"]["mqtt"]["client_id"] = "../evil"
    await ended_crossing(rig, "ev-badinst")
    assert rig.llm.calls == []
    assert rows(rig)[-1]["outcome"] == "no_clip_url"


@pytest.mark.asyncio
async def test_single_running_instance_fallback(rig):
    """M74: a bus-sourced event (no instance) with exactly ONE running
    Frigate instance uses that instance, even with two config entries."""
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-bus1", "garage_a", s, source="bus")
    frigate(rig, "ev-bus1", "garage_a", s, typ="end", end=s + 3, source="bus")
    await cross(rig, GARAGE_EGRESS, e)
    await settle(rig)
    assert rig.llm.calls[-1]["video_file"] == (
        "/api/frigate/frigate-f2/notifications/ev-bus1/clip.mp4")


@pytest.mark.asyncio
async def test_discover_instance_ids_normalises(mods, hass):
    """F01 / F02 / F03 / F04: keyed by the stripped topic prefix without a
    trailing '/', client_id stripped, blank client_id skipped, any error ->
    {} (never a partial map)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    fi = mods.fi
    for eid in ("fa", "fb", "fc"):
        MockConfigEntry(domain="frigate", entry_id=eid).add_to_hass(hass)
    hass.data["frigate"] = {
        "fa": {"config": {"mqtt": {"client_id": " frigate-a ",
                                    "topic_prefix": " frigate2/ "}}},
        "fb": {"config": {"mqtt": {"client_id": "   ", "topic_prefix": "x"}}},
    }
    assert fi.discover_frigate_instance_ids(hass) == {"frigate2": "frigate-a"}

    class _Boom(dict):
        def get(self, key, default=None):
            if key == "fb":
                raise RuntimeError("bad runtime")
            return super().get(key, default)

    hass.data["frigate"] = _Boom(hass.data["frigate"])
    assert fi.discover_frigate_instance_ids(hass) == {}


# --------------------------------------------- agreement case (P18/M83)
def test_agreement_case_pins(mods):
    ac = mods.cv.agreement_case
    assert ac(2, 2) == "A"
    assert ac(3, 2) == "B"   # vision higher
    assert ac(2, 3) == "C"   # camera higher
    assert ac(None, 2) == "D" and ac(2, None) == "D"


@pytest.mark.asyncio
async def test_row_agreement_case_vision_vs_camera(rig):
    """M83: row label uses (vision, camera) order: vision 2 vs camera 1 ->
    B; vision 2 vs camera 3 -> C."""
    await ended_crossing(rig, "ev-ab", peak=1)
    await ended_crossing(rig, "ev-ac", camera="front_door_aerial",
                         egress=FRONT_EGRESS, peak=3)
    assert [r["agreement_case"] for r in rows(rig)] == ["B", "C"]


# ------------------------------------- trip-wire classes (M102/M105/P06)
@pytest.mark.asyncio
async def test_error_rate_counts_timeout_unparseable_refused(rig):
    """M102: timeout + unparseable + refused (no plain 'error') out of 8
    calls (3/8 > 0.25) page the error trip-wire."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TIMEOUT_S", 0.05)
    replies = [("sleep", 1.0), {"response_text": "two people"}, {}] + [
        _ok_reply()] * 5
    base = _now(rig) - timedelta(seconds=45) - timedelta(seconds=8 * 120)
    for i, reply in enumerate(replies):
        rig.llm.reply = reply
        e = base + timedelta(seconds=i * 120)
        s = e.timestamp() + 1
        frigate(rig, f"ev-x{i}", "garage_a", s, typ="end", end=s + 3)
        await cross(rig, GARAGE_EGRESS, e)
        await settle(rig)
        await asyncio.sleep(0.1)
        await settle(rig)
    assert [r["outcome"] for r in rows(rig)][:3] == [
        "timeout", "unparseable", "refused"]
    await rig.cv.async_evaluate_tripwires()
    assert [p["kind"] for p in rig.pages] == ["crossing_vision_errors"]


@pytest.mark.asyncio
async def test_error_page_rearms_when_rate_recovers(rig):
    """M105: once the rate drops back under the bar the latch clears, so a
    later bad spell pages again."""
    cv, now = rig.cv, rig.cv._epoch()
    bad = [(now, "error")] * 3 + [(now, "ok")] * 5
    cv._calls.extend(bad)
    await cv.async_evaluate_tripwires()
    cv._calls.clear()
    cv._calls.extend([(now, "ok")] * 8)
    await cv.async_evaluate_tripwires()
    cv._calls.clear()
    cv._calls.extend(bad)
    await cv.async_evaluate_tripwires()
    assert [p["kind"] for p in rig.pages] == [
        "crossing_vision_errors", "crossing_vision_errors"]


def test_parse_shapes_pinned(mods):
    """P06 / P07 / P13 / P14 / P15: frames not a list or missing ->
    unparseable (a counted failure, never blank); a non-mapping frame or a
    bool people value -> unparseable; group must be a bool; desc is cut to
    desc_max."""
    p = mods.cv.parse_vision_response

    def sr(**kw):
        body = {"frames": [{"index": 1, "people": 1}], "people_total": 1,
                "group": False, "desc": "abcdefgh"}
        body.update(kw)
        return {"structured_response": body}

    assert p(sr(frames="x"), 200)["outcome"] == "unparseable"
    assert p({"structured_response": {"people_total": 1}}, 200)["outcome"] == (
        "unparseable")
    assert p(sr(frames=[3]), 200)["outcome"] == "unparseable"
    assert p(sr(frames=[{"index": 1, "people": True}]), 200)["outcome"] == (
        "unparseable")
    assert p(sr(group="yes"), 200)["group"] is None
    assert p(sr(), 5)["desc"] == "abcde"


# -------------------------------------- teardown in flight (M115/M118/M81)
@pytest.mark.asyncio
async def test_teardown_cancels_in_flight_call(rig):
    """M118 / M115: the in-flight llmvision call is a tracked task, and
    teardown gathers then cancels it (bounded); no row afterwards."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TEARDOWN_GATHER_S", 0.05)
    rig.llm.reply = ("sleep", 30)
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-fly", "garage_a", s, typ="end", end=s + 3)
    fire_cross_nowait(rig, GARAGE_EGRESS, e)
    for _ in range(50):
        await asyncio.sleep(0)
        if rig.llm.calls:
            break
    assert len(rig.llm.calls) == 1
    tasks = set(rig.cv._tasks)
    assert len(tasks) == 1
    await rig.cv.async_teardown()
    await spin()
    assert all(t.done() for t in tasks)
    assert rows(rig) == []


@pytest.mark.asyncio
async def test_row_write_is_tracked_and_cancelled_at_teardown(rig):
    """M81: the row write is a tracked task, so an unload with a write
    still in flight cancels it instead of leaking it."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TEARDOWN_GATHER_S", 0.05)
    gate = asyncio.Event()

    async def _slow_write(**_kw):
        await gate.wait()

    rig.monkeypatch.setattr(rig.db, "log_memory_episode", _slow_write)
    fire_cross_nowait(rig, GARAGE_EGRESS, _now(rig) - timedelta(seconds=45))
    await spin()
    tasks = set(rig.cv._tasks)
    assert len(tasks) == 1
    await rig.cv.async_teardown()
    await spin()
    assert all(t.done() for t in tasks)


# ------------------------------------------- call arguments (M68/K14/A6)
@pytest.mark.asyncio
async def test_call_arguments_timeout_provider_tokens(rig):
    """M68 / K14: timeout_s handed to the adapter is 90 s (plan F6: above
    llmvision's own 60 s request timeout). Model wiring: provider is the
    operator's "OpenAI Madrone Vision" entry and model gpt-6-luna. A6: the
    crossing max_tokens (1500) does not follow the perimeter option."""
    seen: list = []
    real = rig.mods.pe.analyze_crossing_frames

    async def _spy(*a, **kw):
        seen.append(kw)
        return await real(*a, **kw)

    rig.monkeypatch.setattr(rig.mods.pe, "analyze_crossing_frames", _spy)
    for entry in rig.hass.config_entries.async_entries(rig.C.DOMAIN):
        rig.hass.config_entries.async_update_entry(entry, options={
            rig.C.CONF_PERIMETER_ENRICHMENT_MAX_TOKENS: 50})
    await ended_crossing(rig, "ev-args")
    [kw] = seen
    assert kw["timeout_s"] == 90.0
    assert kw["timeout_s"] > 60
    assert kw["provider"] == "01M7B731T26P2HXVW77AQR62PP"
    assert kw["model"] == "gpt-6-luna"
    call = rig.llm.calls[0]
    assert call["provider"] == "01M7B731T26P2HXVW77AQR62PP"
    assert call["max_tokens"] == 1500


@pytest.mark.asyncio
async def test_empty_provider_const_falls_back_to_perimeter_provider(rig):
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_PROVIDER_ID", "")
    await ended_crossing(rig, "ev-prov")
    assert rig.llm.calls[0]["provider"] == "prov_openai"


# --------------------------------------------- writer health (K03)
@pytest.mark.asyncio
async def test_writer_health_absence_exempt_during_vacation(rig):
    """K03: zero crossing-vision rows over a week the house was away for
    the whole window is not paged (absence-exempt), through the real
    writer-health check on the real DB."""
    from datetime import datetime, timezone

    ts = (datetime.now(timezone.utc) - timedelta(days=10)).replace(
        tzinfo=None).isoformat()
    conn = sqlite3.connect(rig.db.db_file)
    try:
        conn.execute(
            "INSERT INTO house_state_log (timestamp, state, confidence) "
            "VALUES (?, 'away', 1.0)", (ts,))
        conn.commit()
    finally:
        conn.close()
    stats = await rig.db.run_memory_writer_health_check(triggered_by="manual")
    assert "crossing_vision_shadow" in stats["absence_suppressed_types"]


@pytest.mark.asyncio
async def test_call_is_background_task(rig):
    """Review B2: the llmvision call runs as a background task, so an HA
    stop (which waits on ordinary tasks) is not held for up to TIMEOUT_S by
    an in-flight call. hass.async_block_till_done() without background
    tasks returns while the call is still in flight."""
    rig.monkeypatch.setattr(rig.C, "CROSSING_VISION_TEARDOWN_GATHER_S", 0.05)
    rig.llm.reply = ("sleep", 30)
    e = _now(rig) - timedelta(seconds=45)
    s = e.timestamp() + 1
    frigate(rig, "ev-bg", "garage_a", s, typ="end", end=s + 3)
    fire_cross_nowait(rig, GARAGE_EGRESS, e)
    await spin()
    assert len(rig.llm.calls) == 1
    await asyncio.wait_for(rig.hass.async_block_till_done(), timeout=2)
    assert rows(rig) == []
    await rig.cv.async_teardown()
