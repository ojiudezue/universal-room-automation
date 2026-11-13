"""HOUSE-STATE step 1a, review fix-up (A-H1/B-H1/D HIGH-1, A-M1, A-M2, B-L1,
C-1, C-2, C-3, D LOW-2).

Every test drives the real method that contains the fixed site; times,
windows and expected values are hardcoded literals. The resident fixtures use
the live install's ``tracked_persons`` shape (display names, two-word names
included), never entity ids.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_residency_wiring import (
    EZ,
    EZ_NAME,
    KIOSK,
    OJI,
    OJI_NAME,
    T_SETUP,
    State,
    _coord,
    _FakeDB,
    _feed,
    _registry,
)

from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation.domain_coordinators.residency import (
    ResidencyTracker,
)
from custom_components.universal_room_automation.person_coordinator import (
    PersonTrackingCoordinator,
)

# Post-boot-window time (boot window is 600 s).
T = T_SETUP + 5000.0


# ============================================================================
# A-H1 / B-H1 / D HIGH-1: display-name tracked_persons
# ============================================================================


@pytest.mark.asyncio
async def test_display_name_resident_writes_record_and_row():
    db = _FakeDB()
    _hass, coord, _st = _coord(tracked=["Oji Udezue", "Ezinne"], db=db)
    _feed(coord, "person.oji_udezue", "not_home", "home", T)
    _feed(coord, "person.ezinne", "home", "not_home", T + 100)
    recs = list(coord._residency.recent)
    assert [(r.kind, r.person, r.resident_set_resolved) for r in recs] == [
        ("arrival", "person.oji_udezue", True),
        ("departure", "person.ezinne", True),
    ]
    await coord.async_teardown()
    assert [(r["episode_type"], r["node_id"]) for r in db.rows] == [
        ("person_arrival", "oji_udezue"), ("person_departure", "ezinne")]
    rec = coord.get_recent_resident_arrival(300, now_ts=T + 10)
    assert rec is not None and rec.person == "person.oji_udezue"


@pytest.mark.asyncio
async def test_display_name_residents_home_two_word_name():
    """get_residents_home with names: the exact-match state lookup (no HA
    lowercase fallback in this fake) finds person.oji_udezue."""
    states = {OJI: State(OJI, "home"), EZ: State(EZ, "home"),
              KIOSK: State(KIOSK, "home")}
    _hass, coord, st = _coord(tracked=[OJI_NAME, EZ_NAME], states=states)
    assert coord.get_residents_home() == frozenset({OJI, EZ})
    assert coord.get_residents_home_count() == 2


@pytest.mark.asyncio
async def test_display_name_ble_overrule_matches_in_residents_home():
    """The REAL ``PersonTrackingCoordinator.effective_person_state`` compares
    ``person.{name.lower().replace(' ', '_')}`` against the id it is given
    (person_coordinator.py, pre-existing comparison). With the normalised
    resident id a BLE-overruled GPS home is excluded; the other resident
    stays home."""
    states = {OJI: State(OJI, "home"), EZ: State(EZ, "home")}
    hass, coord, st = _coord(states=states)

    pc = SimpleNamespace(
        hass=hass,
        tracked_persons=[OJI_NAME, EZ_NAME],
        _gps_home_overruled=frozenset({OJI_NAME}),
        _ble_leads_enabled=lambda: True,
        get_person_location=lambda name: "away" if name == OJI_NAME else "home",
    )
    pc.effective_person_state = (
        lambda pid: PersonTrackingCoordinator.effective_person_state(pc, pid))
    hass.data[C.DOMAIN]["person_coordinator"] = pc
    assert coord.get_residents_home() == frozenset({EZ})
    pc._gps_home_overruled = frozenset()
    assert coord.get_residents_home() == frozenset({OJI, EZ})


@pytest.mark.asyncio
async def test_entity_id_entries_kept_as_is():
    _hass, coord, _st = _coord(tracked=["person.oji_udezue", "Ezinne Udezue"])
    assert coord._residency_residents() == frozenset({OJI, EZ})


# ============================================================================
# A-M1: an arrival followed by the same person's departure is not evidence
# ============================================================================


def _tracker():
    return ResidencyTracker(
        lambda: frozenset({OJI, EZ}), setup_ts=0.0, boot_window_s=600.0,
        min_away_s=900.0, recent_events=16)


def test_recent_arrival_skips_arrival_with_later_departure():
    tr = _tracker()
    tr.on_event(OJI, "home", "not_home", 10000.0)
    tr.on_event(OJI, "not_home", "home", 10030.0)
    assert tr.recent_arrival(300.0, 10040.0).edge_ts == 10030.0
    tr.on_event(OJI, "home", "not_home", 10045.0)
    assert tr.recent_arrival(300.0, 10200.0) is None


def test_recent_arrival_other_person_departure_does_not_suppress():
    tr = _tracker()
    tr.on_event(OJI, "not_home", "home", 10030.0)
    tr.on_event(EZ, "home", "not_home", 10045.0)
    rec = tr.recent_arrival(300.0, 10200.0)
    assert rec is not None and rec.person == OJI


@pytest.mark.asyncio
async def test_recent_arrival_bounce_through_presence_getter():
    _hass, coord, _st = _coord()
    _feed(coord, OJI, "not_home", "home", T)
    _feed(coord, OJI, "home", "not_home", T + 15)
    assert coord.get_recent_resident_arrival(300, now_ts=T + 100) is None
    _feed(coord, OJI, "not_home", "home", T + 30)
    rec = coord.get_recent_resident_arrival(300, now_ts=T + 100)
    assert rec is not None and rec.edge_ts == T + 30


# ============================================================================
# A-M2: one row per edge through the REAL database (no 60 s type window)
# ============================================================================


async def _real_db(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

    def _sched(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    db = UniversalRoomDatabase(hass)
    assert await db.initialize()
    await db.start_write_worker()
    return db


@pytest.mark.asyncio
async def test_arrival_departure_arrival_in_60s_keeps_three_rows(tmp_path):
    db = await _real_db(tmp_path)
    try:
        _hass, coord, _st = _coord(db=db)
        _feed(coord, OJI, "not_home", "home", T)
        _feed(coord, OJI, "home", "not_home", T + 20)
        _feed(coord, OJI, "not_home", "home", T + 40)
        await coord.async_teardown()
        rows = await db.read_memory_episodes("oji_udezue")
        assert sorted(r["episode_type"] for r in rows) == [
            "person_arrival", "person_arrival", "person_departure"]
        # The per-edge source_ref still dedups a replay of the same edge.
        rec = coord._residency.recent[0]
        coord._residency_torn_down = False
        coord._persist_residency_event(rec)
        await coord._async_teardown_residency()
        assert len(await db.read_memory_episodes("oji_udezue")) == 3
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_window_dedup_default_unchanged_for_existing_callers(tmp_path):
    db = await _real_db(tmp_path)
    try:
        first = await db.log_memory_episode(
            node_id="room:study_a", episode_type="occupancy_phantom")
        second = await db.log_memory_episode(
            node_id="room:study_a", episode_type="occupancy_phantom")
        assert first is not None and second is None
    finally:
        await db.stop_write_worker()


# ============================================================================
# B-L1: residency flag first, gather after every cancel
# ============================================================================


@pytest.mark.asyncio
async def test_teardown_gathers_rows_after_cancels(monkeypatch):
    """The gated row is released only by the listener cancel; with the
    gather at the end it completes (row written), with the gather first it
    would time out and be cancelled."""
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as PR,
    )
    monkeypatch.setattr(PR._ura_const, "RESIDENCY_LOG_TEARDOWN_TIMEOUT_S", 0.3)
    gate = asyncio.Event()
    db = _FakeDB(gate)
    _hass, coord, _st = _coord(db=db)
    _feed(coord, OJI, "not_home", "home", T)
    real_cancel = coord._cancel_listeners
    seen = {}

    def cancel_spy():
        seen["flag"] = coord._residency_torn_down
        # A late event mid-teardown must not schedule a new row.
        _feed(coord, OJI, "home", "not_home", T + 10)
        seen["tasks"] = len([t for t in coord._residency_log_tasks if not t.done()])
        gate.set()
        real_cancel()

    coord._cancel_listeners = cancel_spy
    await coord.async_teardown()
    assert seen == {"flag": True, "tasks": 1}
    assert [r["episode_type"] for r in db.rows] == ["person_arrival"]


# ============================================================================
# C-1: binary_sensor.ura_house_occupied through get_house_occupancy()
# ============================================================================


_OCCUPIED = {
    "away": False, "vacation": False, "arriving": True, "home_day": True,
    "home_evening": True, "home_night": True, "sleep": True, "waking": True,
    "guest": True,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", sorted(_OCCUPIED))
async def test_house_occupied_binary_sensor_via_getter(state):
    from custom_components.universal_room_automation import binary_sensor as bs
    from custom_components.universal_room_automation.domain_coordinators.house_state import (
        HouseState,
    )

    hass, coord, _st = _coord()
    hass.data[C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        house_state=HouseState(state), coordinators={"presence": coord})
    assert coord.get_house_occupancy() == (
        "occupied" if _OCCUPIED[state] else "empty")
    sensor = bs.HouseOccupiedBinarySensor(hass, MagicMock())
    assert sensor.is_on is _OCCUPIED[state]


@pytest.mark.asyncio
async def test_house_occupied_binary_sensor_reads_presence_getter():
    """The sensor consumes the getter (not a parallel house-state read)."""
    from custom_components.universal_room_automation import binary_sensor as bs
    from custom_components.universal_room_automation.domain_coordinators.house_state import (
        HouseState,
    )

    hass, coord, _st = _coord()
    hass.data[C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        house_state=HouseState("home_day"), coordinators={"presence": coord})
    coord.get_house_occupancy = lambda: "empty"
    assert bs.HouseOccupiedBinarySensor(hass, MagicMock()).is_on is False


# ============================================================================
# C-3: ResidentsHomeSensor state + attributes
# ============================================================================


@pytest.mark.asyncio
async def test_residents_home_sensor_value_and_attrs(monkeypatch):
    from custom_components.universal_room_automation import sensor as sen

    ez_plb = "binary_sensor.ura_ezinne_udezue_phone_left_behind"
    _registry(monkeypatch, {
        f"{C.DOMAIN}_person_ezinne_udezue_phone_left_behind": ez_plb})
    hass, coord, st = _coord()
    hass.data[C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        house_state="home_day", coordinators={"presence": coord})
    sensor = sen.ResidentsHomeSensor(hass, MagicMock())
    st[EZ] = State(EZ, "not_home")
    _feed(coord, OJI, "not_home", "home", T)
    st[OJI] = State(OJI, "home")
    assert sensor.native_value == 1
    attrs = sensor.extra_state_attributes
    assert attrs["residents"] == ["oji_udezue"]
    assert attrs["persons"]["oji_udezue"]["home"] is True
    assert attrs["persons"]["oji_udezue"]["arrived_at"] == T
    assert attrs["last_arrival"]["person"] == OJI
    assert attrs["last_departure"] is None
    assert attrs["phone_left_behind_excluded"] == []
    # Ezinne home with her phone left behind: counted out, listed excluded.
    st[EZ] = State(EZ, "home")
    st[ez_plb] = State(ez_plb, "on")
    assert sensor.native_value == 1
    attrs = sensor.extra_state_attributes
    assert attrs["residents"] == ["oji_udezue"]
    assert attrs["phone_left_behind_excluded"] == ["ezinne_udezue"]
    st[ez_plb] = State(ez_plb, "off")
    assert sensor.native_value == 2
    # No presence coordinator -> None / {}.
    hass.data[C.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        house_state="home_day", coordinators={})
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}
