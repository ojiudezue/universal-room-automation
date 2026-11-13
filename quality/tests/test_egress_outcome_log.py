"""FACE-ARRIVAL-REBUILD-1 D8a (plan rev 11 §9 D8a, §9A step 2): the persisted
egress outcome log.

Every test drives PRODUCTION code: a REAL ``PersonCensus`` and a REAL
``EgressDirectionTracker``; crossings enter through
``_on_egress_state_change`` (the 45 s ``async_call_later`` callback is captured
and fired, i.e. time is advanced into ``_resolve_direction``), and rows land in
a REAL ``UniversalRoomDatabase`` (its own DDL, its own write queue). Face legs
are injected at ``census._resolve_face_legs`` (the producer's input seam, as the
existing d2b tests do); nothing stamps a resolution or a row by hand.

Oracles are hand-derived from the plan, never re-computed by the code under
test.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import transit_validator as tv
from custom_components.universal_room_automation.camera_census import (
    FaceLeg,
    PersonCensus,
)
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 12, 18, 0, 0, tzinfo=UTC)
EPISODE = "egress_identity_outcome"


class _StubCameraManager:
    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


def _leg(stem, slug, last_changed, *, device="dev", synthetic=False):
    leg = FaceLeg(
        entity_id=f"sensor.{stem}_last_recognized_face",
        engine="frigate",
        device_id=f"{device}_{stem}",
        base_stem=stem,
        canonical_slug=slug,
        last_changed=last_changed,
        confidence=None,
    )
    return replace(leg, synthetic=True) if synthetic else leg


def _state(value):
    return SimpleNamespace(state=value, last_changed=NOW, attributes={})


class _Clock:
    """`dt_util.now` / `utcnow` for the tracker + census under test."""

    def __init__(self, t):
        self.t = t

    def now(self, *a, **k):
        return self.t

    def utcnow(self):
        return self.t


@pytest_asyncio.fixture
async def rig(tmp_path, monkeypatch):
    """Real DB + real census + real tracker; returns a namespace."""
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
        "tracked_persons": ["person.oji_udezue", "person.jaya"],
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: True,
        # Two door groups so two crossings 10 s apart are NOT the same
        # dedup key (DOOR_STEM_DEDUP_S = 30, review L2).
        ura_const.CONF_DOOR_GROUPS: {"front_door": "front", "garage_a": "garage_a"},
    }
    hass.config_entries.async_entries.return_value = [entry]
    hass.async_create_task = _sched
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    census._resolve_ble_legs = lambda ts, direction: []
    legs: dict = {}
    census._resolve_face_legs = lambda stem: list(legs.get(stem, []))
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
        sys.modules["homeassistant.helpers.event"], "async_call_later",
        _call_later,
    )

    tracker = EgressDirectionTracker(hass)
    tracker._load_door_config()
    tracker._get_interior_cameras_near = lambda cam: [
        "binary_sensor.foyer_person_occupancy",
    ]
    ns = SimpleNamespace(
        db=db, hass=hass, census=census, tracker=tracker, legs=legs,
        states=states, fired=fired, clock=clock, scheduled=scheduled,
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


async def _cross(rig, egress, *, interior_after_s=2, at=None):
    """One crossing through the production entry point; fires the captured
    45 s callback (time advanced) and lets the logger task finish."""
    at = at or rig.clock.t
    rig.clock.t = at
    before = len(rig.scheduled)
    rig.tracker._on_egress_state_change(_ev(egress))
    assert len(rig.scheduled) == before + 1
    delay, cb = rig.scheduled[-1]
    assert delay == EgressDirectionTracker.ENTRY_WINDOW_SECONDS
    if interior_after_s is not None:
        rig.clock.t = at + timedelta(seconds=interior_after_s)
        rig.tracker._on_interior_state_change(
            _ev("binary_sensor.foyer_person_occupancy"),
        )
    rig.clock.t = at + timedelta(seconds=delay)
    await cb(rig.clock.t)
    await asyncio.sleep(0)
    for t in list(rig.tracker._outcome_log_tasks):
        await t


def _rows(db):
    conn = sqlite3.connect(db.db_file)
    try:
        return [
            (node, json.loads(attrs), src)
            for node, attrs, src in conn.execute(
                "SELECT node_id, attrs_json, source_ref FROM memory_episodes "
                "WHERE episode_type = ? ORDER BY id", (EPISODE,),
            )
        ]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Wire-in anchor: one row per resolution, every return path
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_resolution_persists_one_row_switch_off(rig):
    """No-legs, ambiguous, attached, vetoed, census_unavailable and
    resolver_error crossings each persist EXACTLY one row, with the label
    hand-derived from the plan (INV-LOG). Phase 1 has no direction-aware
    switch; this is the switch-off shape."""
    # 1. no legs, entry (interior fires after) -> no_leg
    await _cross(rig, "binary_sensor.front_door_person_occupancy")
    # 2. no interior event -> direction ambiguous
    rig.clock.t = NOW + timedelta(minutes=5)
    await _cross(rig, "binary_sensor.garage_a_person_occupancy", interior_after_s=None)
    # 3. single fresh face leg on the egress camera, person home -> attached
    t3 = NOW + timedelta(minutes=10)
    rig.legs["front_door"] = [_leg("front_door", "oji_udezue", t3 + timedelta(seconds=5))]
    rig.states["person.oji_udezue"] = _state("home")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t3)
    # 4. same, person not_home -> vetoed
    t4 = NOW + timedelta(minutes=15)
    rig.legs["front_door"] = [_leg("front_door", "jaya", t4 + timedelta(seconds=5))]
    rig.states["person.jaya"] = _state("not_home")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t4)
    # 5. census gone -> census_unavailable
    t5 = NOW + timedelta(minutes=20)
    census = rig.hass.data[ura_const.DOMAIN].pop("census")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t5)
    # 6. census whose kill-switch read raises -> resolver_error
    t6 = NOW + timedelta(minutes=25)
    broken = MagicMock()
    broken._is_egress_identity_enabled.side_effect = RuntimeError("boom")
    rig.hass.data[ura_const.DOMAIN]["census"] = broken
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t6)
    rig.hass.data[ura_const.DOMAIN]["census"] = census

    rows = _rows(rig.db)
    assert [r[1]["outcome"] for r in rows] == [
        "no_leg", "direction_ambiguous", "attached", "vetoed",
        "census_unavailable", "resolver_error",
    ]
    assert [r[1]["direction"] for r in rows] == [
        "entry", "ambiguous", "entry", "entry", "entry", "entry",
    ]
    # One bus event per crossing too (the log adds a row, nothing else).
    assert len([f for f in rig.fired if f[0] == "ura_person_egress_event"]) == 6
    # node_id / source_ref are per crossing (no two rows share them).
    assert len({r[0] for r in rows}) == 6
    assert len({r[2] for r in rows}) == 6


@pytest.mark.asyncio
async def test_vetoed_row_carries_slug_tier_synthetic(rig):
    """A vetoed two-camera crossing whose 0.9 needs the synthetic latch leg:
    the row names the vetoed slug, tier 0.9, synthetic True, raw state
    not_home. The bus/DB stay anonymous (unchanged veto)."""
    t = NOW
    rig.legs["front_door"] = [_leg("front_door", "jaya", t + timedelta(seconds=3))]
    rig.legs["foyer"] = [_leg("foyer", "jaya", t + timedelta(seconds=4), synthetic=True)]
    rig.states["person.jaya"] = _state("not_home")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t)
    (_node, attrs, _src), = _rows(rig.db)
    assert attrs["outcome"] == "vetoed"
    assert attrs["slug"] == "jaya"
    assert attrs["tier"] == 0.9
    assert attrs["synthetic"] is True
    assert attrs["person_state"] == "not_home"
    payload = rig.fired[-1][1]
    assert payload["person_id"] is None
    assert payload["identity_confidence"] is None


@pytest.mark.asyncio
async def test_two_crossings_both_persist(rig):
    """Two crossings on DIFFERENT door groups 10 s apart both persist (a
    constant node_id would let the 60 s (node, type) dedup drop the second)."""
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=NOW)
    await _cross(
        rig, "binary_sensor.garage_a_person_occupancy",
        at=NOW + timedelta(seconds=10),
    )
    rows = _rows(rig.db)
    assert len(rows) == 2
    assert rows[0][1]["egress_camera"] == "binary_sensor.front_door_person_occupancy"
    assert rows[1][1]["egress_camera"] == "binary_sensor.garage_a_person_occupancy"


@pytest.mark.asyncio
async def test_persist_kill_switch(rig, monkeypatch):
    """EGRESS_OUTCOME_LOG_PERSIST False -> no row; the crossing still fires
    its bus event (the switch gates the row only)."""
    monkeypatch.setattr(tv, "EGRESS_OUTCOME_LOG_PERSIST", False)
    await _cross(rig, "binary_sensor.front_door_person_occupancy")
    assert _rows(rig.db) == []
    assert rig.fired and rig.fired[-1][0] == "ura_person_egress_event"


@pytest.mark.asyncio
async def test_vetoed_path_no_boost_no_synthetic_stash(rig):
    """A vetoed 0.75 (two engines, one camera) crossing appends NO boost-ledger
    entry and a vetoed synthetic 0.9 crossing leaves the bus
    identity_synthetic_corroborated False (develop behaviour; a side-effecting
    tier helper on the veto path would change both)."""
    rig.states["person.jaya"] = _state("not_home")
    t = NOW
    rig.legs["front_door"] = [
        _leg("front_door", "jaya", t + timedelta(seconds=3), device="a"),
        _leg("front_door", "jaya", t + timedelta(seconds=4), device="b"),
    ]
    boost_before = len(rig.census._egress_identity_boost_events)
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t)
    assert len(rig.census._egress_identity_boost_events) == boost_before
    assert _rows(rig.db)[-1][1]["tier"] == 0.75

    t2 = NOW + timedelta(minutes=5)
    rig.legs["front_door"] = [_leg("front_door", "jaya", t2 + timedelta(seconds=3))]
    rig.legs["foyer"] = [_leg("foyer", "jaya", t2 + timedelta(seconds=4), synthetic=True)]
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t2)
    assert rig.fired[-1][1]["identity_synthetic_corroborated"] is False
    assert _rows(rig.db)[-1][1]["synthetic"] is True


@pytest.mark.asyncio
async def test_logger_task_gathered_at_teardown(rig):
    """A write still in flight when the tracker tears down is awaited (bounded)
    by async_teardown, so the row lands before the DB worker stops."""
    real = rig.db.log_memory_episode
    gate = asyncio.Event()

    async def _slow(**kw):
        await gate.wait()
        return await real(**kw)

    rig.db.log_memory_episode = _slow
    rig.tracker._on_egress_state_change(_ev("binary_sensor.front_door_person_occupancy"))
    _d, cb = rig.scheduled[-1]
    await cb(NOW)
    assert rig.tracker._outcome_log_tasks, "logger task must be tracked"
    asyncio.get_running_loop().call_later(0.05, gate.set)
    await rig.tracker.async_teardown()
    assert len(_rows(rig.db)) == 1
    assert not rig.tracker._outcome_log_tasks


@pytest.mark.asyncio
async def test_no_row_after_teardown(rig):
    """A `_delayed_resolve` scheduled before teardown and firing after it
    writes no row (`_torn_down` latch, review L3)."""
    rig.tracker._on_egress_state_change(_ev("binary_sensor.front_door_person_occupancy"))
    _d, cb = rig.scheduled[-1]
    await rig.tracker.async_teardown()
    await cb(NOW + timedelta(seconds=45))
    await asyncio.sleep(0)
    assert not rig.tracker._outcome_log_tasks
    assert _rows(rig.db) == []


def test_registered_for_writer_health_unless_persist_off():
    """The type is registered (else log_memory_episode rejects it) and in the
    writer-health checked set; with the persist switch off it must be exempt."""
    assert EPISODE == ura_const.EGRESS_OUTCOME_EPISODE_TYPE
    assert EPISODE in ura_const.MEMORY_EPISODE_TYPES
    assert EPISODE in ura_const.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert (
        ura_const.EGRESS_OUTCOME_LOG_PERSIST
        or EPISODE in ura_const.MEMORY_WRITER_HEALTH_EXEMPT_TYPES
    )


@pytest.mark.asyncio
async def test_resolution_carries_provenance(rig):
    """The bus `identity_provenance` comes from THIS call's resolution: with a
    stale last-attach stash that still says `ble` (its write fails), a
    face-only attach is published `face`; an unnamed crossing publishes None."""

    class _StaleStash:
        def __get__(self, obj, objtype=None):
            return {"provenance": "ble", "person": "jaya"}

        def __set__(self, obj, value):
            raise RuntimeError("stash write failed")

    cls = type("_StaleCensus", (PersonCensus,), {"_egress_identity_last_attach": _StaleStash()})
    rig.census.__class__ = cls
    t = NOW
    rig.legs["front_door"] = [_leg("front_door", "oji_udezue", t + timedelta(seconds=3))]
    rig.states["person.oji_udezue"] = _state("home")
    await _cross(rig, "binary_sensor.front_door_person_occupancy", at=t)
    payload = rig.fired[-1][1]
    assert payload["person_id"] == "oji_udezue"
    assert payload["identity_provenance"] == "face"
    assert _rows(rig.db)[-1][1]["provenance"] == "face"

    rig.legs["front_door"] = []
    await _cross(
        rig, "binary_sensor.garage_a_person_occupancy",
        at=NOW + timedelta(minutes=5),
    )
    assert rig.fired[-1][1]["person_id"] is None
    assert rig.fired[-1][1]["identity_provenance"] is None
