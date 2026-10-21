"""Side-find fixes on the occupancy dwell branch.

1. get_occupancy_time_today: callers passed the room NAME (table keyed by
   entry_id) and it summed event_type='occupied' rows the writer never emits
   (writer: 'entry' / 'exit'); it always returned 0.
2. get_occupancy_percentage: compared a LOCAL dt_util.now() cutoff with
   naive-UTC stored timestamps, and summed exit-row `duration` (seconds since
   last motion, not the episode length).
3. (same call sites) get_uncomfortable_minutes_today: room NAME key and a UTC
   midnight.

Real UniversalRoomDatabase.initialize() builds the schema. Clock: Chicago,
now = Wed 2026-09-16 10:00 CDT = 15:00Z; local midnight = 05:00Z.
Oracles are hand-computed seconds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util import dt as dt_util

from occ_dwell_helpers import default_tz, make_real_db, seed

UTC = timezone.utc
EV = ("INSERT INTO occupancy_events (room_id, timestamp, event_type, "
      "trigger_source, duration) VALUES (?, ?, ?, ?, ?)")


def _clock(tz):
    now_local = datetime(2026, 9, 16, 10, 0, tzinfo=tz)
    return (patch.object(dt_util, "now",
                         side_effect=lambda tz_=None: now_local
                         if tz_ is None else now_local.astimezone(tz_)),
            patch.object(dt_util, "utcnow",
                         return_value=now_local.astimezone(UTC)))


@pytest.mark.asyncio
async def test_occupancy_time_today_pairs_entry_exit_from_local_midnight(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, EV, [
        # straddles local midnight (05:00Z): counts 05:00-05:30 = 1800 s
        ("E1", "2026-09-16T04:30:00.000000", "entry", "motion", None),
        ("E1", "2026-09-16T05:30:00.000000", "exit", None, 99999),
        # closed 08:00-08:10 = 600 s (exit duration column is ignored)
        ("E1", "2026-09-16T08:00:00.000000", "entry", "motion", None),
        ("E1", "2026-09-16T08:10:00.000000", "exit", None, 5),
        # open since 14:00Z, now 15:00Z = 3600 s
        ("E1", "2026-09-16T14:00:00.000000", "entry", "motion", None),
        # another room, and the name key: must not count
        ("E2", "2026-09-16T08:00:00.000000", "entry", "motion", None),
        ("Kitchen", "2026-09-16T08:00:00.000000", "occupied", None, 7200),
    ])
    with default_tz("America/Chicago") as tz:
        p_now, p_utc = _clock(tz)
        with p_now, p_utc:
            assert await db.get_occupancy_time_today("E1") == 1800 + 600 + 3600
            # the legacy shape (name key, 'occupied' event) no longer counts
            assert await db.get_occupancy_time_today("Kitchen") == 0


@pytest.mark.asyncio
async def test_occupancy_percentage_uses_utc_window(tmp_path):
    """days=1 -> window [2026-09-15 15:00Z, 2026-09-16 15:00Z). An episode
    12:00Z-16:00Z on the 20th overlaps it by one hour = 3600/86400 = 4.1667%.
    The old local cutoff ('2026-09-15T10:00' as text) admitted the 12:00Z
    entry and its exit-row duration instead."""
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, EV, [
        ("E1", "2026-09-15T12:00:00.000000", "entry", "motion", None),
        ("E1", "2026-09-15T16:00:00.000000", "exit", None, 60),
    ])
    with default_tz("America/Chicago") as tz:
        p_now, p_utc = _clock(tz)
        with p_now, p_utc:
            pct = await db.get_occupancy_percentage("E1", days=1)
    assert pct == pytest.approx(3600 / 86400 * 100)


@pytest.mark.asyncio
async def test_occupancy_percentage_none_without_evidence(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, EV, [("E1", "2026-09-01T12:00:00", "exit", None, 60)])
    with default_tz("America/Chicago") as tz:
        p_now, p_utc = _clock(tz)
        with p_now, p_utc:
            assert await db.get_occupancy_percentage("E1", days=1) is None


@pytest.mark.asyncio
async def test_uncomfortable_minutes_local_midnight(tmp_path):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, "INSERT INTO environmental_data (room_id, timestamp, temperature, "
             "humidity, occupied) VALUES (?, ?, ?, ?, ?)", [
        ("E1", "2026-09-16T04:30:00", 85.0, 45.0, 1),  # yesterday local
        ("E1", "2026-09-16T06:00:00", 85.0, 45.0, 1),  # today, hot
        ("E1", "2026-09-16T06:05:00", 72.0, 45.0, 1),  # today, comfortable
    ])
    with default_tz("America/Chicago") as tz:
        p_now, p_utc = _clock(tz)
        with p_now, p_utc:
            assert await db.get_uncomfortable_minutes_today("E1") == 5


# ---------------------------------------------------------------------------
# Call-site anchors: each sensor passes the entry_id (not the room name).
# ---------------------------------------------------------------------------


def _sensor(cls, db):
    from custom_components.universal_room_automation.const import DOMAIN

    coord = SimpleNamespace(
        entry=SimpleNamespace(entry_id="E1", data={"room_name": "Kitchen"}),
        data={}, last_update_success=True,
    )
    s = cls.__new__(cls)
    s.coordinator = coord
    s.hass = SimpleNamespace(data={DOMAIN: {"database": db}})
    s._cached_value = None
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("cls_name", [
    "OccupancyPercentageTodaySensor",
    "TimeOccupiedTodaySensor",
    "AvgTimeToComfortSensor",
])
async def test_sensor_call_sites_pass_entry_id_for_occupancy_time(cls_name):
    from custom_components.universal_room_automation import sensor as sensor_mod

    db = SimpleNamespace(
        get_occupancy_time_today=AsyncMock(return_value=3600),
        get_uncomfortable_minutes_today=AsyncMock(return_value=6),
    )
    s = _sensor(getattr(sensor_mod, cls_name), db)
    await s.async_update()
    db.get_occupancy_time_today.assert_awaited_once_with("E1")


@pytest.mark.asyncio
@pytest.mark.parametrize("cls_name", [
    "TimeUncomfortableTodaySensor",
    "AvgTimeToComfortSensor",
])
async def test_sensor_call_sites_pass_entry_id_for_uncomfortable(cls_name):
    from custom_components.universal_room_automation import sensor as sensor_mod

    db = SimpleNamespace(
        get_occupancy_time_today=AsyncMock(return_value=3600),
        get_uncomfortable_minutes_today=AsyncMock(return_value=6),
    )
    s = _sensor(getattr(sensor_mod, cls_name), db)
    await s.async_update()
    db.get_uncomfortable_minutes_today.assert_awaited_once_with("E1")


# ---------------------------------------------------------------------------
# The four "today" sensors now refresh from the coordinator update,
# throttled (TODAY_SENSOR_REFRESH_S = 300) and quantized.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
from datetime import timedelta  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

T0 = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)


def _live(cls_name, db):
    from custom_components.universal_room_automation import sensor as sensor_mod

    s = _sensor(getattr(sensor_mod, cls_name), db)
    tasks = []

    def _create_task(coro, *a, **k):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t

    s.hass.async_create_task = _create_task
    s.async_write_ha_state = MagicMock()
    s._tasks = tasks
    return s


def _update(s, at):
    from custom_components.universal_room_automation import sensor as sensor_mod

    with patch.object(sensor_mod.dt_util, "utcnow", return_value=at):
        s._handle_coordinator_update()


def _db(occ_secs=4020, unc=17):
    return SimpleNamespace(
        get_occupancy_time_today=AsyncMock(return_value=occ_secs),
        get_uncomfortable_minutes_today=AsyncMock(return_value=unc),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cls_name", [
    "OccupancyPercentageTodaySensor", "TimeOccupiedTodaySensor",
    "TimeUncomfortableTodaySensor", "AvgTimeToComfortSensor",
])
async def test_today_sensor_refreshes_on_coordinator_update(cls_name):
    db = _db()
    s = _live(cls_name, db)
    _update(s, T0)
    await asyncio.gather(*s._tasks)
    assert db.get_occupancy_time_today.await_count + \
        db.get_uncomfortable_minutes_today.await_count >= 1
    assert s.native_value is not None
    # one write from the base callback, one after the refresh lands
    assert s.async_write_ha_state.call_count == 2


@pytest.mark.asyncio
async def test_today_sensor_throttle_boundary():
    db = _db()
    s = _live("TimeOccupiedTodaySensor", db)
    _update(s, T0)
    await asyncio.gather(*s._tasks)
    _update(s, T0 + timedelta(seconds=30))
    _update(s, T0 + timedelta(seconds=299))
    await asyncio.gather(*s._tasks)
    assert db.get_occupancy_time_today.await_count == 1
    _update(s, T0 + timedelta(seconds=300))
    await asyncio.gather(*s._tasks)
    assert db.get_occupancy_time_today.await_count == 2


@pytest.mark.asyncio
async def test_today_sensor_no_overlapping_refresh():
    gate = asyncio.Event()

    async def _slow(_eid):
        await gate.wait()
        return 600

    db = SimpleNamespace(get_occupancy_time_today=AsyncMock(side_effect=_slow))
    s = _live("TimeOccupiedTodaySensor", db)
    _update(s, T0)
    await asyncio.sleep(0)
    _update(s, T0 + timedelta(seconds=900))  # due, but one is in flight
    assert len(s._tasks) == 1
    gate.set()
    await asyncio.gather(*s._tasks)


@pytest.mark.asyncio
async def test_today_minutes_quantized():
    # 4020 s = 67 min -> 65 (5-min quantum); 17 uncomfortable -> 15
    s = _live("TimeOccupiedTodaySensor", _db())
    _update(s, T0)
    await asyncio.gather(*s._tasks)
    assert s.native_value == 65
    s2 = _live("TimeUncomfortableTodaySensor", _db())
    _update(s2, T0)
    await asyncio.gather(*s2._tasks)
    assert s2.native_value == 15


@pytest.mark.asyncio
async def test_today_pct_quantized():
    from custom_components.universal_room_automation import sensor as sensor_mod

    # local now 10:00 -> 36000 s elapsed; 15000 s occupied = 41.67% -> 42
    s = _live("OccupancyPercentageTodaySensor", _db(occ_secs=15000))
    with default_tz("America/Chicago") as tz:
        with patch.object(sensor_mod.dt_util, "now",
                          return_value=datetime(2026, 9, 16, 10, 0, tzinfo=tz)):
            _update(s, T0)
            await asyncio.gather(*s._tasks)
    assert s.native_value == 42


@pytest.mark.asyncio
async def test_today_remove_cancels_refresh():
    gate = asyncio.Event()

    async def _slow(_eid):
        await gate.wait()
        return 600

    db = SimpleNamespace(get_occupancy_time_today=AsyncMock(side_effect=_slow))
    s = _live("TimeOccupiedTodaySensor", db)
    _update(s, T0)
    await asyncio.sleep(0)
    task = s._tasks[0]
    with patch("homeassistant.helpers.update_coordinator.CoordinatorEntity."
               "async_will_remove_from_hass", AsyncMock()):
        await s.async_will_remove_from_hass()
    await asyncio.sleep(0)
    assert task.cancelled()



# ---------------------------------------------------------------------------
# Review A: missing exit rows must not become phantom occupancy.
# Clock: now 15:00Z (10:00 CDT), local midnight 05:00Z, OCC_EPISODE_MAX_S
# 12 h. Oracles are hand-computed seconds.
# ---------------------------------------------------------------------------


async def _today(tmp_path, rows):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, EV, rows)
    with default_tz("America/Chicago") as tz:
        p_now, p_utc = _clock(tz)
        with p_now, p_utc:
            return await db.get_occupancy_time_today("E1")


async def _pct(tmp_path, rows, days):
    db = make_real_db(tmp_path)
    assert await db.initialize()
    seed(db, EV, rows)
    with default_tz("America/Chicago") as tz:
        p_now, p_utc = _clock(tz)
        with p_now, p_utc:
            return await db.get_occupancy_percentage("E1", days=days)


@pytest.mark.asyncio
async def test_weeks_old_dangling_entry_counts_nothing(tmp_path):
    assert await _today(tmp_path, [
        ("E1", "2026-09-01T12:00:00", "entry", "motion", None),
    ]) == 0


@pytest.mark.asyncio
async def test_episode_capped_at_max(tmp_path):
    # entry 00:00Z, never exited: counts 05:00 -> 12:00 (cap) = 25200
    assert await _today(tmp_path, [
        ("E1", "2026-09-16T00:00:00", "entry", "motion", None),
    ]) == 25200


@pytest.mark.asyncio
async def test_entry_entry_closes_at_next_entry_or_cap(tmp_path):
    # open 00:30Z (cap 12:30) -> 05:00-12:30 = 27000; new entry 13:00,
    # exit 13:10 = 600. A reader that ignores the second entry counts 27000.
    assert await _today(tmp_path, [
        ("E1", "2026-09-16T00:30:00", "entry", "motion", None),
        ("E1", "2026-09-16T13:00:00", "entry", "motion", None),
        ("E1", "2026-09-16T13:10:00", "exit", None, None),
    ]) == 27600


@pytest.mark.asyncio
async def test_latest_prior_event_wins(tmp_path):
    # prior entry 02:00, prior exit 03:00: the LATEST prior event (exit)
    # decides, so nothing is open at midnight. Plus 06:00-06:10 = 600.
    assert await _today(tmp_path, [
        ("E1", "2026-09-16T02:00:00", "entry", "motion", None),
        ("E1", "2026-09-16T03:00:00", "exit", None, 5),
        ("E1", "2026-09-16T06:00:00", "entry", "motion", None),
        ("E1", "2026-09-16T06:10:00", "exit", None, 5),
    ]) == 600


@pytest.mark.asyncio
async def test_event_exactly_at_window_start_is_in_window(tmp_path):
    assert await _today(tmp_path, [
        ("E1", "2026-09-16T05:00:00", "entry", "motion", None),
        ("E1", "2026-09-16T06:00:00", "exit", None, 5),
    ]) == 3600


@pytest.mark.asyncio
async def test_foreign_event_type_ignored(tmp_path):
    assert await _today(tmp_path, [
        ("E1", "2026-09-16T06:00:00", "entry", "motion", None),
        ("E1", "2026-09-16T06:30:00", "occupied", None, 7200),
        ("E1", "2026-09-16T07:00:00", "exit", None, 5),
    ]) == 3600


@pytest.mark.asyncio
async def test_pct_in_window_event_is_evidence(tmp_path):
    # only an exit in the window (nothing open): 0 %, not None
    assert await _pct(tmp_path, [
        ("E1", "2026-09-16T06:00:00", "exit", None, 5),
    ], days=1) == 0.0


@pytest.mark.asyncio
async def test_pct_open_at_start_without_window_events(tmp_path):
    # window [09-15 15:00Z, 09-16 15:00Z); entry 09-15 13:00Z never exits:
    # capped at 09-16 01:00Z -> 10 h inside the window = 10/24
    assert await _pct(tmp_path, [
        ("E1", "2026-09-15T13:00:00", "entry", "motion", None),
    ], days=1) == pytest.approx(10 / 24 * 100)


@pytest.mark.asyncio
async def test_pct_multi_day_window(tmp_path):
    # days=3 -> [09-13 15:00Z, 09-16 15:00Z). In: 09-14 10:00-12:00 (2 h).
    # Out: 09-12 10:00-12:00.  2 h / 72 h.
    assert await _pct(tmp_path, [
        ("E1", "2026-09-12T10:00:00", "entry", "motion", None),
        ("E1", "2026-09-12T12:00:00", "exit", None, 5),
        ("E1", "2026-09-14T10:00:00", "entry", "motion", None),
        ("E1", "2026-09-14T12:00:00", "exit", None, 5),
    ], days=3) == pytest.approx(2 / 72 * 100)


# Producer: the exit row is always written on the occupied->vacant edge.


async def _edge(tmp_path, *, was, now_occ, last_motion):
    from occ_dwell_helpers import fetch

    from custom_components.universal_room_automation import coordinator as cmod
    from custom_components.universal_room_automation.const import (
        STATE_OCCUPANCY_SOURCE, STATE_OCCUPIED,
    )

    db = make_real_db(tmp_path)
    assert await db.initialize()
    await db.start_write_worker()
    try:
        c = cmod.UniversalRoomCoordinator.__new__(cmod.UniversalRoomCoordinator)
        c.entry = SimpleNamespace(entry_id="E1", data={})
        c._last_motion_time = last_motion
        now = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)
        await c._async_log_occupancy_edge(
            db, {STATE_OCCUPIED: now_occ, STATE_OCCUPANCY_SOURCE: "motion"},
            was, now,
        )
    finally:
        await db.stop_write_worker()
    return fetch(db, "SELECT event_type, trigger_source, duration "
                     "FROM occupancy_events WHERE room_id='E1'")


@pytest.mark.asyncio
async def test_exit_row_written_without_motion_stamp(tmp_path):
    rows = await _edge(tmp_path, was=True, now_occ=False, last_motion=None)
    assert rows == [("exit", None, None)]


@pytest.mark.asyncio
async def test_exit_row_with_motion_stamp_keeps_duration(tmp_path):
    lm = datetime(2026, 9, 16, 14, 55, tzinfo=UTC)
    rows = await _edge(tmp_path, was=True, now_occ=False, last_motion=lm)
    assert rows == [("exit", None, 300)]


@pytest.mark.asyncio
async def test_entry_row_written_on_rising_edge(tmp_path):
    assert await _edge(tmp_path, was=False, now_occ=True, last_motion=None) \
        == [("entry", "motion", None)]


@pytest.mark.asyncio
async def test_no_row_without_edge(tmp_path):
    assert await _edge(tmp_path, was=True, now_occ=True, last_motion=None) == []


# G12: Avg Time To Comfort quantized.


@pytest.mark.asyncio
async def test_avg_time_to_comfort_quantized():
    # 60 occupied min, 17 uncomfortable: round(17/60*30) = 8 -> 5
    s = _live("AvgTimeToComfortSensor", _db(occ_secs=3600, unc=17))
    _update(s, T0)
    await asyncio.gather(*s._tasks)
    assert s.native_value == 5


# Fan-recheck release: sets _last_occupied_state False out of band, so the
# next tick sees no edge. The release itself writes the exit row (once).


async def _release(tmp_path, *, was_occupied):
    from occ_dwell_helpers import fetch

    from custom_components.universal_room_automation import coordinator as cmod
    from custom_components.universal_room_automation.const import (
        DOMAIN, STATE_OCCUPIED,
    )

    db = make_real_db(tmp_path)
    assert await db.initialize()
    await db.start_write_worker()
    tasks = []

    def _bg(hass, coro, name, **_kw):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t

    try:
        c = cmod.UniversalRoomCoordinator.__new__(cmod.UniversalRoomCoordinator)
        c.hass = SimpleNamespace(data={DOMAIN: {"database": db}})
        c.entry = SimpleNamespace(entry_id="E1", data={"room_name": "Kitchen"},
                                  async_create_background_task=_bg)
        c.data = {STATE_OCCUPIED: was_occupied}
        c._last_motion_time = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)
        c._became_occupied_time = None
        c._ble_only_hold_since = None
        c._last_occupied_state = was_occupied
        c._hvac_evidence_active = True
        c.apply_fan_recheck_release()
        await asyncio.gather(*tasks)
        # the next tick's edge logic, with was_occupied = _last_occupied_state
        await c._async_log_occupancy_edge(
            db, {STATE_OCCUPIED: False}, c._last_occupied_state,
            datetime(2026, 9, 16, 15, 0, tzinfo=UTC),
        )
    finally:
        await db.stop_write_worker()
    return fetch(db, "SELECT event_type, duration FROM occupancy_events "
                     "WHERE room_id='E1'")


@pytest.mark.asyncio
async def test_fan_recheck_release_writes_one_exit_row(tmp_path):
    assert await _release(tmp_path, was_occupied=True) == [("exit", None)]


@pytest.mark.asyncio
async def test_fan_recheck_release_when_vacant_writes_nothing(tmp_path):
    assert await _release(tmp_path, was_occupied=False) == []
