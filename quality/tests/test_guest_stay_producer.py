"""GUEST-MODE-SPLIT-VISITORS-1 D2 — night-stay producer (URA DB -> latch).

Plan: docs/planning/PLANNING_guest_mode_split_2026_11.md rev 4 §2.1-§2.3, D2.

The REAL UniversalRoomDatabase (alias package) builds its schema in a temp
file; rows are seeded in the writers' own clocks:
  * occupancy_events.timestamp: naive UTC isoformat ("...T...", utcnow());
  * person_visits.entry_time/exit_time: naive PROCESS-LOCAL in the sqlite3
    default-adapter shape "YYYY-MM-DD HH:MM:SS" (writer datetime.now()).
The walk is the REAL PresenceCoordinator._refresh_guest_stay. House sleep
window 22 -> 6, America/Chicago. Oracles are hand-derived literals.

Replay fixture (plan §5.2/§5.3): per-night guest-room fractions of the October
stay; required day list: latch active 09-29 .. 10-18, off 10-19 .. 11-08.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import guest_split_harness as H

HS = H.HS
CHI = ZoneInfo("America/Chicago")
UTC = timezone.utc
GB1, GB2 = "Guest Bedroom 1", "Guest Bedroom 2"
E1, E2 = "E_GB1", "E_GB2"
OCC = ("INSERT INTO occupancy_events (room_id, timestamp, event_type, "
       "trigger_source, duration) VALUES (?, ?, ?, ?, ?)")
VIS = ("INSERT INTO person_visits (person_id, room_id, entry_time, exit_time, "
       "confidence, detection_method) VALUES (?, ?, ?, ?, ?, ?)")


# --- fixtures ----------------------------------------------------------------

@pytest.fixture
def proc_tz():
    """Set the PROCESS time zone (what datetime.now() uses) for a test and
    restore it."""
    prev = os.environ.get("TZ")

    def _set(name):
        os.environ["TZ"] = name
        time.tzset()

    yield _set
    if prev is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = prev
    time.tzset()


def _make_db(tmp_path):
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(str(tmp_path), *parts)
    hass.is_stopping = False
    hass.data = {}

    def _schedule(coro, name=None, **_kw):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule
    hass.async_create_task = _schedule
    db = H.DB.UniversalRoomDatabase(hass)
    assert H.run(db.initialize())
    return db


def _seed(db, sql, rows):
    conn = sqlite3.connect(db.db_file)
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def _utc_iso(aware):
    return aware.astimezone(UTC).replace(tzinfo=None).isoformat(
        timespec="microseconds")


def occupy(db, entry_id, start_local, seconds):
    """One entry/exit pair in the occupancy writer's clock (naive UTC)."""
    _seed(db, OCC, [
        (entry_id, _utc_iso(start_local), "entry", "motion", None),
        (entry_id, _utc_iso(start_local + timedelta(seconds=seconds)),
         "exit", None, 0),
    ])


def visit(db, room_name, start_local, end_local):
    """A person_visits row in the writer's clock: naive PROCESS-local."""
    def _proc(x):
        return datetime.fromtimestamp(x.timestamp()).isoformat(sep=" ")
    _seed(db, VIS, [("oji", room_name, _proc(start_local), _proc(end_local),
                     0.9, "bermuda")])


def night_start(d):
    return datetime(d.year, d.month, d.day, 22, tzinfo=CHI)


def night_len(d):
    """Real elapsed seconds of the 22 -> 06 night of local date d (oracle:
    zoneinfo arithmetic, independent of the code under test)."""
    n = d + timedelta(days=1)
    end = datetime(n.year, n.month, n.day, 6, tzinfo=CHI)
    return (end.astimezone(UTC) - night_start(d).astimezone(UTC)).total_seconds()


def occupy_fraction(db, entry_id, d, frac):
    if frac > 0:
        occupy(db, entry_id, night_start(d), frac * night_len(d))


def coord_with(monkeypatch, db, rooms=((GB1, E1), (GB2, E2)),
               start=22, end=6):
    H.install_clock(monkeypatch, datetime(2026, 11, 9, 12, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.HOME_DAY, sleep_start=start,
                sleep_end=end)
    w.hass.data[H.DOMAIN]["database"] = db
    w.coord._guest_room_entry_ids = dict(rooms)
    return w.coord


def walk(coord, now_local):
    H.run(coord._refresh_guest_stay(now_local, run_inference=False))
    return coord._guest_stay_active


def at(y, m, d, hh=7, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=CHI)


# --- the replay fixture --------------------------------------------------------

STAY = [0.72, 0.66, 0.82, 0.65, 0.50, 0.36, 0.58, 0.14, 0.51, 0.30, 0.60,
        0.25, 0.37, 0.15, 0.25, 0.37, 0.0, 0.0, 0.57, 0.0, 0.0]   # 09-27..10-17


def test_replay_fixture_day_list(monkeypatch, tmp_path, proc_tz):
    proc_tz("UTC")
    db = _make_db(tmp_path)
    d = date(2026, 9, 27)
    for f in STAY:
        occupy_fraction(db, E1, d, f)
        d += timedelta(days=1)
    d = date(2026, 10, 18)
    while d <= date(2026, 11, 1):
        occupy_fraction(db, E2, d, 0.02)
        d += timedelta(days=1)
    coord = coord_with(monkeypatch, db)
    active = []
    day = date(2026, 9, 27)
    while day <= date(2026, 11, 9):
        if walk(coord, at(day.year, day.month, day.day)):
            active.append(day)
        day += timedelta(days=1)
    expected = [date(2026, 9, 29) + timedelta(days=i) for i in range(20)]
    assert active == expected
    assert expected[-1] == date(2026, 10, 18)


def test_occupied_seconds_unchanged(tmp_path):
    """The extraction keeps _occupied_seconds_between's sum (hand oracle)."""
    db = _make_db(tmp_path)
    _seed(db, OCC, [
        ("R", "2026-09-16T09:00:00.000000", "entry", "m", None),   # look-back
        ("R", "2026-09-16T10:30:00.000000", "exit", None, 5),      # 1800
        ("R", "2026-09-16T11:00:00.000000", "entry", "m", None),
        ("R", "2026-09-16T11:10:00.000000", "entry", "m", None),   # 600
        ("R", "2026-09-16T11:40:00.000000", "exit", None, 5),      # 1800
        ("R", "2026-09-16T19:00:00.000000", "entry", "m", None),   # 3600 open
        ("C", "2026-09-17T00:00:00.000000", "entry", "m", None),   # capped
    ])

    async def _q(room, a, b):
        async with db._db_read() as conn:
            return await db._occupied_seconds_between(conn, room, a, b)

    assert H.run(_q("R", datetime(2026, 9, 16, 10), datetime(2026, 9, 16, 20))) \
        == (7800.0, True)
    # cap OCC_EPISODE_MAX_S 43200 from the 00:00 entry -> ends 12:00
    assert H.run(_q("C", datetime(2026, 9, 17, 10), datetime(2026, 9, 17, 14))) \
        == (7200.0, True)
    assert H.run(_q("Z", datetime(2026, 9, 17, 10), datetime(2026, 9, 17, 14))) \
        == (0.0, False)


NIGHT = date(2026, 11, 3)   # CST: 22:00 = 04:00Z 11-04, 06:00 = 12:00Z


def _resident_case(monkeypatch, tmp_path):
    """Returns (fractions, stored person_visits strings)."""
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(NIGHT), 8 * 3600)
    visit(db, GB1, datetime(2026, 11, 3, 23, tzinfo=CHI),
          datetime(2026, 11, 4, 1, tzinfo=CHI))
    windows = [(night_start(NIGHT), datetime(2026, 11, 4, 6, tzinfo=CHI))]
    conn = sqlite3.connect(db.db_file)
    try:
        stored = conn.execute(
            "SELECT entry_time, exit_time FROM person_visits").fetchall()
    finally:
        conn.close()
    return H.run(db.get_guest_room_night_fractions(E1, GB1, windows, 120)), stored


def test_resident_subtraction(monkeypatch, tmp_path, proc_tz):
    """8 h occupied, resident 23:00-01:00 padded 120 s each side:
    (28800 - 7440) / 28800."""
    proc_tz("UTC")
    [(frac, had)], _ = _resident_case(monkeypatch, tmp_path)
    assert had is True
    assert frac == pytest.approx(21360 / 28800)


def test_person_visits_clock_utc_host(monkeypatch, tmp_path, proc_tz):
    """HAOS shape: process TZ UTC, rows read 05:00 / 07:00. Read as LOCAL
    (the get_closed_person_visits docstring) they would fall at 05:00-07:00
    CST, outside the night (fraction 1.0)."""
    proc_tz("UTC")
    [(frac, _)], stored = _resident_case(monkeypatch, tmp_path)
    assert stored == [("2026-11-04 05:00:00", "2026-11-04 07:00:00")]
    assert frac == pytest.approx(21360 / 28800)


def test_person_visits_clock_local_host(monkeypatch, tmp_path, proc_tz):
    """Process TZ = local (America/Chicago): rows read 23:00 / 01:00. Read as
    UTC they would fall at 17:00-19:00 CST, outside the night (fraction 1.0)."""
    proc_tz("America/Chicago")
    [(frac, _)], stored = _resident_case(monkeypatch, tmp_path)
    assert stored == [("2026-11-03 23:00:00", "2026-11-04 01:00:00")]
    assert frac == pytest.approx(21360 / 28800)


def test_naive_utc_bounds(monkeypatch, tmp_path):
    """The occupancy reader gets NAIVE UTC bounds (a tz-aware bound would
    serialise with +00:00 against naive stored rows)."""
    db = _make_db(tmp_path)
    seen = []
    real = H.DB.UniversalRoomDatabase._occupied_episodes_between

    async def _spy(self, conn, room_id, a, b):
        seen.append((a, b))
        return await real(self, conn, room_id, a, b)

    monkeypatch.setattr(H.DB.UniversalRoomDatabase,
                        "_occupied_episodes_between", _spy)
    windows = [(night_start(NIGHT), datetime(2026, 11, 4, 6, tzinfo=CHI))]
    H.run(db.get_guest_room_night_fractions(E1, GB1, windows, 120))
    assert seen == [(datetime(2026, 11, 4, 4, 0), datetime(2026, 11, 4, 12, 0))]
    assert all("+" not in x.isoformat() for x in seen[0])


def _two_nights(tmp_path):
    db = _make_db(tmp_path)
    occupy_fraction(db, E1, date(2026, 11, 1), 0.5)
    occupy_fraction(db, E1, date(2026, 11, 2), 0.5)
    return db


def test_restart_determinism(monkeypatch, tmp_path, proc_tz):
    proc_tz("UTC")
    db = _two_nights(tmp_path)
    c1 = coord_with(monkeypatch, db)
    assert walk(c1, at(2026, 11, 3, 6, 1)) is True
    snap = (c1._guest_stay_active, c1._guest_stay_since, c1._guest_stay_basis,
            c1._guest_stay_evaluated_for)
    c2 = coord_with(monkeypatch, db)
    walk(c2, at(2026, 11, 3, 14, 0))
    assert (c2._guest_stay_active, c2._guest_stay_since, c2._guest_stay_basis,
            c2._guest_stay_evaluated_for) == snap
    assert snap[1] == datetime(2026, 11, 3, 12, 0, tzinfo=UTC)   # 06:00 CST
    assert [b["night"] for b in snap[2]] == [
        "2026-10-31", "2026-11-01", "2026-11-02"]
    c3 = coord_with(monkeypatch, db)
    assert walk(c3, at(2026, 11, 3, 5, 59)) is False
    assert c3._guest_stay_evaluated_for == date(2026, 11, 2)


def test_window_end_boundary(monkeypatch, tmp_path, proc_tz):
    proc_tz("UTC")
    db = _two_nights(tmp_path)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 3, 5, 59, 59)) is False
    assert walk(c, at(2026, 11, 3, 6, 0, 0)) is True
    assert c._guest_stay_evaluated_for == date(2026, 11, 3)


def test_dst_nights(monkeypatch, tmp_path, proc_tz):
    proc_tz("UTC")
    fall = H.PR.guest_night_window(date(2026, 10, 31), 22, 6, CHI)
    spring = H.PR.guest_night_window(date(2027, 3, 13), 22, 6, CHI)
    # Elapsed (UTC) length; same-tzinfo aware subtraction would be wall-clock.
    elapsed = lambda w: (w[1].astimezone(UTC) - w[0].astimezone(UTC)).total_seconds()  # noqa: E731
    assert elapsed(fall) == 9 * 3600
    assert elapsed(spring) == 7 * 3600
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(date(2026, 10, 31)), 9 * 3600)
    [(frac, had)] = H.run(db.get_guest_room_night_fractions(
        E1, GB1, [fall], 120))
    assert frac == pytest.approx(1.0) and had is True


def test_one_night_never_enters(monkeypatch, tmp_path, proc_tz):
    """09-15 shape: one 15 h GB2 night -> off; a second qualifying night ->
    on."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E2, datetime(2026, 9, 15, 16, tzinfo=CHI), 15 * 3600)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 9, 16)) is False
    assert walk(c, at(2026, 9, 17)) is False
    occupy_fraction(db, E2, date(2026, 9, 16), 0.3)
    assert walk(c, at(2026, 9, 17)) is True


def test_daytime_never_counts(monkeypatch, tmp_path, proc_tz):
    """6 h afternoon naps two days running: no night time -> off."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E1, datetime(2026, 11, 1, 12, tzinfo=CHI), 6 * 3600)
    occupy(db, E1, datetime(2026, 11, 2, 12, tzinfo=CHI), 6 * 3600)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 3)) is False
    assert all(b["fraction"] == 0.0 for b in c._guest_stay_basis)


def test_db_error_fails_off(monkeypatch, tmp_path):
    class _Boom:
        async def get_guest_room_night_fractions(self, *a, **k):
            raise RuntimeError("db locked")

    c = coord_with(monkeypatch, _Boom())
    c._guest_stay_active = True
    assert walk(c, at(2026, 11, 3)) is False
    assert c._guest_stay_basis == {"error": "db locked"}
    assert c._guest_stay_since is None
    assert c._guest_stay_evaluated_for == date(2026, 11, 3)


def test_non_wrapping_window(monkeypatch, tmp_path, proc_tz):
    """Sleep window 1 -> 6: night N = [N+1 01:00, N+1 06:00)."""
    proc_tz("UTC")
    w = H.PR.guest_night_window(date(2026, 11, 3), 1, 6, CHI)
    assert w == (datetime(2026, 11, 4, 1, tzinfo=CHI),
                 datetime(2026, 11, 4, 6, tzinfo=CHI))
    db = _make_db(tmp_path)
    occupy(db, E1, datetime(2026, 11, 3, 1, tzinfo=CHI), 5 * 3600)
    occupy(db, E1, datetime(2026, 11, 4, 1, tzinfo=CHI), 5 * 3600)
    c = coord_with(monkeypatch, db, start=1, end=6)
    assert walk(c, at(2026, 11, 4, 6, 0)) is True
    assert [b["fraction"] for b in c._guest_stay_basis][-2:] == [1.0, 1.0]


@pytest.mark.parametrize(
    "frac_min,entry,lookback,fracs,expect",
    [
        (0.0, 2, 3, [0.0, 0.01, 0.01], True),    # F=0: any occupied time
        (1.0, 2, 3, [0.99, 0.99, 0.99], False),  # F=1: only full nights
        (0.25, 1, 3, [0.0, 0.0, 0.3], True),     # K=1
        (0.25, 3, 3, [0.3, 0.0, 0.3], False),    # K=L
        (0.25, 2, 1, [0.3, 0.3, 0.3], True),     # L=1 (K clamped to 1)
        (0.25, 2, 7, [0.3, 0.0, 0.3], True),     # L=7
    ],
)
def test_config_extremes_walk(monkeypatch, tmp_path, proc_tz, frac_min,
                              entry, lookback, fracs, expect):
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_NIGHT_MIN_FRACTION", frac_min)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_ENTRY_NIGHTS", entry)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_LOOKBACK_NIGHTS", lookback)
    db = _make_db(tmp_path)
    d = date(2026, 10, 31)
    for f in fracs:
        occupy_fraction(db, E1, d, f)
        d += timedelta(days=1)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 3)) is expect


@pytest.mark.parametrize("replay,long_days,lookback,span", [
    (35, 28, 3, 37),     # defaults: 35 + 3 - 1
    (3, 0, 3, 5),        # replay = L minimum
    (1, 0, 3, 5),        # clamped up to L
    (10, 28, 3, 33),     # clamped up to D4 bound + L = 31
    (30, 0, 3, 32),
])
def test_replay_clamp(monkeypatch, tmp_path, replay, long_days, lookback, span):
    monkeypatch.setattr(H.CONST, "GUEST_STAY_REPLAY_NIGHTS", replay)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_LONG_NM_DAYS", long_days)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_LOOKBACK_NIGHTS", lookback)
    seen = []

    class _Spy:
        async def get_guest_room_night_fractions(self, eid, room, windows, pad):
            seen.append(len(windows))
            return [(0.0, False)] * len(windows)

    c = coord_with(monkeypatch, _Spy(), rooms=((GB1, E1),))
    walk(c, at(2026, 11, 3))
    assert seen == [span]


# --- S11 / setup wire-ins and teardown -------------------------------------

def test_tick_schedules_walk_once(monkeypatch, tmp_path):
    """_run_inference schedules ONE walk when the last completed night is
    not evaluated; not again while one is pending; not once evaluated."""
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.HOME_DAY)
    w.hass.data[H.DOMAIN]["database"] = object()
    scheduled = []

    def _sched(coro, *a, **k):
        name = getattr(coro, "__qualname__", "")
        coro.close()
        if name.endswith("_refresh_guest_stay"):
            fut = MagicMock()
            fut.done.return_value = False
            scheduled.append(fut)
            return fut
        return MagicMock()

    w.hass.async_create_task = _sched
    w.tick()
    assert len(scheduled) == 1
    w.tick()
    assert len(scheduled) == 1          # pending -> not again
    scheduled[0].done.return_value = True
    w.coord._guest_stay_evaluated_for = date(2026, 11, 3)
    w.tick()
    assert len(scheduled) == 1          # already evaluated
    w.coord._guest_stay_evaluated_for = date(2026, 11, 2)
    w.tick()
    assert len(scheduled) == 2


def test_tick_no_walk_when_rule_off(monkeypatch):
    monkeypatch.setattr(H.CONST, "GUEST_NIGHT_STAY_RULE_ENABLED", False)
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.HOME_DAY)
    w.hass.data[H.DOMAIN]["database"] = object()
    names = []

    def _sched(coro, *a, **k):
        names.append(getattr(coro, "__qualname__", ""))
        coro.close()
        return MagicMock()

    w.hass.async_create_task = _sched
    w.tick()
    assert not [n for n in names if n.endswith("_refresh_guest_stay")]


def test_setup_kicks_walk(monkeypatch):
    """async_setup schedules the first walk when the DB is reachable."""
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    monkeypatch.setattr(H.PR, "async_track_time_interval",
                        lambda *a, **k: MagicMock())
    names = []

    def _sched(coro, *a, **k):
        names.append(getattr(coro, "__qualname__", ""))
        coro.close()
        return MagicMock()

    hass = MagicMock()
    hass.data = {H.DOMAIN: {"database": object()}}
    hass.config_entries.async_entries = lambda domain=None: []
    hass.async_create_task = _sched
    hass.async_create_background_task = _sched
    hass.is_running = True
    coord = H.PR.PresenceCoordinator(hass)
    asyncio.run(coord.async_setup())
    assert [n for n in names if n.endswith("_refresh_guest_stay")] == [
        "PresenceCoordinator._refresh_guest_stay"]


def test_task_cancelled_on_teardown(monkeypatch):
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.HOME_DAY)

    class _Slow:
        async def get_guest_room_night_fractions(self, *a, **k):
            await asyncio.sleep(3600)

    w.hass.data[H.DOMAIN]["database"] = _Slow()
    w.coord._guest_room_entry_ids = {GB1: E1}

    async def _drive():
        loop = asyncio.get_running_loop()
        w.hass.async_create_task = lambda coro, *a, **k: loop.create_task(coro)
        assert w.coord._maybe_schedule_guest_stay_refresh() is True
        task = w.coord._guest_stay_task
        await asyncio.sleep(0)
        assert w.coord._maybe_schedule_guest_stay_refresh() is False
        await w.coord.async_teardown()
        await asyncio.sleep(0)
        return task

    task = H.run(_drive())
    assert task.cancelled()
    assert w.coord._guest_stay_task is None


# --- S12 / S13 -----------------------------------------------------------------

def test_discover_records_entry_id(monkeypatch):
    """_discover_guest_rooms records {room_name: entry_id} for every flagged
    room (the walk reads occupancy_events by entry_id), including a room
    whose occupied entity is not registered; unflagged rooms are skipped."""
    import sys
    import types

    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.HOME_DAY)

    def _entry(eid, name, guest):
        e = MagicMock()
        e.entry_id = eid
        e.data = {H.CONST.CONF_ENTRY_TYPE: H.CONST.ENTRY_TYPE_ROOM,
                  H.CONST.CONF_ROOM_NAME: name}
        e.options = {H.CONST.CONF_ROOM_IS_GUEST_ROOM: guest}
        return e

    entries = [_entry("E_GB1", GB1, True), _entry("E_GB2", GB2, True),
               _entry("E_K", "Kitchen", False)]
    w.hass.config_entries.async_entries = lambda domain=None: entries
    registered = {"E_GB1_occupied": "binary_sensor.gb1_occupied"}
    reg = types.SimpleNamespace(
        async_get_entity_id=lambda d, p, uid: registered.get(uid))
    er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
    er_mod.async_get = lambda hass: reg
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry",
                        er_mod)
    helpers = sys.modules.get("homeassistant.helpers")
    if helpers is not None:
        monkeypatch.setattr(helpers, "entity_registry", er_mod, raising=False)
    monkeypatch.setattr(H.PR, "async_track_state_change_event",
                        lambda *a, **k: (lambda: None))
    w.coord._discover_guest_rooms()
    assert w.coord._guest_room_entry_ids == {GB1: "E_GB1", GB2: "E_GB2"}


def test_house_state_sensor_publishes_stay(monkeypatch):
    """S13: guest_stay_active / guest_stay_since (ISO) / guest_stay_basis on
    the house-state sensor attributes."""
    import importlib

    SE = importlib.import_module(f"{H._PKG}.sensor")
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.GUEST)
    basis = [{"night": "2026-11-02", "room": GB1, "fraction": 0.5,
              "qualifies": True}]
    w.coord._guest_stay_active = True
    w.coord._guest_stay_since = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    w.coord._guest_stay_basis = basis
    s = object.__new__(SE.PresenceHouseStateSensor)
    s.hass = w.hass
    attrs = s.extra_state_attributes
    assert attrs["guest_stay_active"] is True
    assert attrs["guest_stay_since"] == "2026-11-03T12:00:00+00:00"
    assert attrs["guest_stay_basis"] == basis
    w.coord._guest_stay_basis = {"error": "db locked"}
    w.coord._guest_stay_since = None
    attrs = s.extra_state_attributes
    assert attrs["guest_stay_basis"] == {"error": "db locked"}
    assert attrs["guest_stay_since"] is None
