"""VISION-CROSSING-SHADOW-1 D2 (PLANNING_crossing_vision.md rev 2 §5 D2):
``peak_person_count`` on ``ura_person_egress_event`` (INV-ADDITIVE).

Every test drives PRODUCTION code: a REAL ``EgressDirectionTracker`` and a
REAL ``PersonCensus``; crossings enter through ``_on_egress_state_change``
(the 45 s ``async_call_later`` callback is captured and fired, i.e. time is
advanced into ``_resolve_direction``); rows land in a REAL
``UniversalRoomDatabase`` (its own DDL, its own write path). Rig copied from
test_egress_outcome_log.py.

Oracles are hand-derived (literal sample values written into the buffer,
literal key lists), never re-computed by the code under test.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import transit_validator as tv
from custom_components.universal_room_automation.camera_census import PersonCensus
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 13, 18, 0, 0, tzinfo=UTC)
FRONT = "binary_sensor.front_door_person_occupancy"
FOYER = "binary_sensor.foyer_person_occupancy"


class _StubCameraManager:
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


class _Clock:
    def __init__(self, t):
        self.t = t

    def now(self, *a, **k):
        return self.t

    def utcnow(self):
        return self.t


@pytest_asyncio.fixture
async def rig(tmp_path, monkeypatch):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    db_hass = MagicMock()
    db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    db_hass.async_create_task = _sched
    db_hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(db_hass)
    assert await db.initialize()
    await db.start_write_worker()

    hass = make_hass()
    states: dict = {}
    hass.states.get = lambda eid: states.get(eid)
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": ["person.oji_udezue"],
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: True,
        ura_const.CONF_DOOR_GROUPS: {"front_door": "front", "garage_a": "garage_a"},
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.async_create_task = _sched
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    census._resolve_ble_legs = lambda ts, direction: []
    census._resolve_face_legs = lambda stem: []
    hass.data = {ura_const.DOMAIN: {"census": census, "database": db}}
    fired: list = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda topic, payload: fired.append((topic, payload))

    clock = _Clock(NOW)
    monkeypatch.setattr(tv.dt_util, "now", clock.now)
    monkeypatch.setattr(tv.dt_util, "utcnow", clock.utcnow)
    scheduled: list = []

    def _call_later(_hass, delay, cb):
        scheduled.append((delay, cb))
        return lambda: None

    monkeypatch.setattr(
        sys.modules["homeassistant.helpers.event"], "async_call_later", _call_later,
    )
    tracker = EgressDirectionTracker(hass)
    tracker._load_door_config()
    tracker._get_interior_cameras_near = lambda cam: [FOYER]
    ns = SimpleNamespace(
        db=db, hass=hass, tracker=tracker, fired=fired, clock=clock,
        scheduled=scheduled,
    )
    try:
        yield ns
    finally:
        await db.stop_write_worker()


def _ev(entity_id, value="on"):
    return SimpleNamespace(data={
        "new_state": SimpleNamespace(entity_id=entity_id, state=value),
        "old_state": SimpleNamespace(entity_id=entity_id, state="off"),
    })


async def _cross(rig, egress, *, interior_after_s=2):
    at = rig.clock.t
    rig.tracker._on_egress_state_change(_ev(egress))
    delay, cb = rig.scheduled[-1]
    if interior_after_s is not None:
        rig.clock.t = at + timedelta(seconds=interior_after_s)
        rig.tracker._on_interior_state_change(_ev(FOYER))
    rig.clock.t = at + timedelta(seconds=delay)
    await cb(rig.clock.t)
    await asyncio.sleep(0)
    for t in list(rig.tracker._outcome_log_tasks):
        await t
    return at


async def _flush(db):
    # log_entry_exit_event goes through the write queue; wait for it.
    for _ in range(50):
        if db._write_queue.empty():
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)


def _db_peaks(db):
    conn = sqlite3.connect(db.db_file)
    try:
        return [
            r[0] for r in conn.execute(
                "SELECT peak_person_count FROM person_entry_exit_events ORDER BY id"
            )
        ]
    finally:
        conn.close()


def _egress_payloads(rig):
    return [p for topic, p in rig.fired if topic == "ura_person_egress_event"]


@pytest.mark.asyncio
async def test_bus_and_db_peak_identical(rig):
    """Entry crossing with a buffered count of 2 inside the window: the bus
    key and the DB column both read 2 (hand-written sample)."""
    rig.tracker._peak_count_buffer["front_door"] = deque(
        [(NOW + timedelta(seconds=3), 2)]
    )
    await _cross(rig, FRONT)
    await _flush(rig.db)
    [payload] = _egress_payloads(rig)
    assert payload["direction"] == "entry"
    assert payload["peak_person_count"] == 2
    assert _db_peaks(rig.db) == [2]


@pytest.mark.asyncio
async def test_sampler_called_once_both_sinks_first_value(rig, monkeypatch):
    """Rev 2 F10 discriminator: a sampler stub returning a different value on
    each call. Exactly one call; both the bus and the DB carry the FIRST
    value (3), never the second (7)."""
    values = iter([3, 7, 11])
    calls: list = []

    def _stub(stem, ts):
        calls.append((stem, ts))
        return next(values)

    monkeypatch.setattr(rig.tracker, "_sample_peak_person_count", _stub)
    at = await _cross(rig, FRONT)
    await _flush(rig.db)
    assert calls == [("front_door", at)]
    [payload] = _egress_payloads(rig)
    assert payload["peak_person_count"] == 3
    assert _db_peaks(rig.db) == [3]


@pytest.mark.asyncio
async def test_ambiguous_peak_none_no_sample(rig, monkeypatch):
    """Ambiguous crossing: the key is present and None, the sampler is never
    called, no DB row (develop wrote none)."""
    calls: list = []
    monkeypatch.setattr(
        rig.tracker, "_sample_peak_person_count",
        lambda stem, ts: calls.append(stem) or 5,
    )
    await _cross(rig, FRONT, interior_after_s=None)
    await _flush(rig.db)
    [payload] = _egress_payloads(rig)
    assert payload["direction"] == "ambiguous"
    assert "peak_person_count" in payload
    assert payload["peak_person_count"] is None
    assert calls == []
    assert _db_peaks(rig.db) == []


@pytest.mark.asyncio
async def test_sampler_exception_none_both(rig, monkeypatch):
    """A raising sampler keeps today's behaviour: None on the bus, NULL in
    the DB, and the row is still written."""
    def _boom(stem, ts):
        raise RuntimeError("sampler down")

    monkeypatch.setattr(rig.tracker, "_sample_peak_person_count", _boom)
    await _cross(rig, FRONT)
    await _flush(rig.db)
    [payload] = _egress_payloads(rig)
    assert payload["peak_person_count"] is None
    assert _db_peaks(rig.db) == [None]


@pytest.mark.asyncio
async def test_existing_bus_keys_unchanged(rig):
    """Golden of the payload: every pre-existing key with its hand-derived
    value for a no-face, single-platform entry crossing, plus exactly one
    new key."""
    await _cross(rig, FRONT)
    [payload] = _egress_payloads(rig)
    assert payload == {
        "direction": "entry",
        "egress_camera": FRONT,
        "timestamp": NOW.isoformat(),
        "person_id": None,
        # direction resolved + one platform fired -> 0.8 (develop rule).
        "confidence": 0.8,
        "identity_confidence": None,
        # No leg at all -> the resolver's single-source class
        # (const.CENSUS_AGREEMENT_SINGLE, develop value).
        "agreement_class": "single_source",
        "identity_synthetic_corroborated": False,
        "identity_provenance": None,
        "peak_person_count": None,
    }


@pytest.mark.asyncio
async def test_door_group_members_and_door_camera_stems(rig):
    """D1 public getters: group members by stem (a stem with no group is a
    group of one) and the door-camera stem set."""
    tr = rig.tracker
    assert tr.door_group_members("front_door") == ("front", frozenset({"front_door"}))
    assert tr.door_group_members("porch") == (None, frozenset({"porch"}))
    assert tr.door_group_members(None) == (None, frozenset())
    tr._door_group_by_stem = {
        "doorbell_lite": "garage_a", "garage_a": "garage_a",
        "front_door_aerial": "front", "madrone_g6_entry": "front",
    }
    assert tr.door_group_members("garage_a") == (
        "garage_a", frozenset({"garage_a", "doorbell_lite"}),
    )
    tr._egress_entities = ["binary_sensor.garage_b_person_detected"]
    assert tr.door_camera_stems() == frozenset({
        "doorbell_lite", "garage_a", "front_door_aerial", "madrone_g6_entry",
        "garage_b",
    })
