"""GUEST-MODE-SPLIT-VISITORS-1 D2 — night-stay producer (URA DB -> latch).

Plan: docs/planning/PLANNING_guest_mode_split_2026_11.md rev 5 §2.1-§2.3, D2,
§13.

The REAL UniversalRoomDatabase (alias package) builds its schema in a temp
file; rows are seeded in the writers' own clocks:
  * occupancy_events.timestamp: naive UTC isoformat ("...T...", utcnow());
  * person_visits.entry_time/exit_time: naive PROCESS-local in the sqlite3
    default-adapter shape "YYYY-MM-DD HH:MM:SS" (writer datetime.now()).
The walk is the REAL PresenceCoordinator._refresh_guest_stay. House sleep
window 22 -> 6, America/Chicago. Oracles are hand-derived literals.

Replay fixture (plan §5.4): fixtures/guest_stay_r5_replay.json holds the D0
per-night AND per-day (10:00 -> 22:00) fractions of GB1/GB2 for 08-24..11-08;
the expected day lists are the plan's (computed by the independent replay
script r5_pick.py), not re-derived here.
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


def day_start(d):
    return datetime(d.year, d.month, d.day, 10, tzinfo=CHI)


def day_len(d):
    """Real elapsed seconds of local d 10:00 -> 22:00 (oracle: zoneinfo)."""
    return (night_start(d).astimezone(UTC)
            - day_start(d).astimezone(UTC)).total_seconds()


def occupy_day(db, entry_id, d, frac):
    """Occupy the rev 5 day window (d 10:00 -> 22:00) for this share."""
    if frac > 0:
        occupy(db, entry_id, day_start(d), frac * day_len(d))


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

_FIX = os.path.join(os.path.dirname(__file__), "fixtures",
                    "guest_stay_r5_replay.json")
_ROOM_ENTRY = {"GB1": E1, "GB2": E2}


def _replay_active_days(monkeypatch, tmp_path):
    import json

    with open(_FIX, encoding="utf-8") as fh:
        nights = json.load(fh)["nights"]
    db = _make_db(tmp_path)
    for iso, rooms in nights.items():
        d = date.fromisoformat(iso)
        for room, v in rooms.items():
            occupy_fraction(db, _ROOM_ENTRY[room], d, v["night"])
            occupy_day(db, _ROOM_ENTRY[room], d, v["day"])
    coord = coord_with(monkeypatch, db)
    active = []
    day = date(2026, 8, 25)
    while day <= date(2026, 11, 9):
        if walk(coord, at(day.year, day.month, day.day)):
            active.append(day)
        day += timedelta(days=1)
    return active


def _span(a, b):
    out, d = [], a
    while d <= b:
        out.append(d)
        d += timedelta(days=1)
    return out


def _rev5_list(k):
    if k == 1:
        return (_span(date(2026, 8, 25), date(2026, 9, 2))
                + _span(date(2026, 9, 6), date(2026, 9, 8))
                + _span(date(2026, 9, 10), date(2026, 9, 12))
                + _span(date(2026, 9, 16), date(2026, 9, 18))
                + _span(date(2026, 9, 28), date(2026, 10, 18)))
    return (_span(date(2026, 8, 26), date(2026, 9, 2))
            + _span(date(2026, 9, 6), date(2026, 9, 8))
            + _span(date(2026, 9, 30), date(2026, 10, 18)))


def test_replay_fixture_day_list(monkeypatch, tmp_path, proc_tz):
    """Rev 6 defaults + operator exit cap 2 (K=1, day 0.10 from 10:00, day
    before night, exit min(2, n) empty nights). Stay caught 09-28 (day 2);
    the empty nights 10-13 / 10-14 end it, so the last day is 10-14 (17 of
    21 stay days); one-night visits (09-10, 09-16) held 1 day; off
    10-19..11-08."""
    proc_tz("UTC")
    expected = (_span(date(2026, 8, 25), date(2026, 9, 1))
                + _span(date(2026, 9, 6), date(2026, 9, 7))
                + [date(2026, 9, 10), date(2026, 9, 16)]
                + _span(date(2026, 9, 28), date(2026, 10, 14)))
    assert _replay_active_days(monkeypatch, tmp_path) == expected


def test_replay_fixture_day_list_entry_nights_2(monkeypatch, tmp_path, proc_tz):
    """GUEST_STAY_ENTRY_NIGHTS 2 (rev 6 exit, cap 2): single-night entries
    vanish, the stay runs 09-30..10-14, 08-25 becomes 08-26."""
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_ENTRY_NIGHTS", 2)
    expected = (_span(date(2026, 8, 26), date(2026, 9, 1))
                + _span(date(2026, 9, 6), date(2026, 9, 7))
                + _span(date(2026, 9, 30), date(2026, 10, 14)))
    assert _replay_active_days(monkeypatch, tmp_path) == expected


@pytest.mark.parametrize("k", [1, 2])
def test_replay_fixture_day_list_fixed_exit(monkeypatch, tmp_path, proc_tz, k):
    """GUEST_STAY_EXIT_SCALES_WITH_STAY False: the rev 5 lists exactly
    (INV-STAY-4 (iv), byte-identical fixed exit on the real fixture)."""
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_EXIT_SCALES_WITH_STAY", False)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_ENTRY_NIGHTS", k)
    assert _replay_active_days(monkeypatch, tmp_path) == _rev5_list(k)


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
    occupy_day(db, E1, date(2026, 11, 2), 0.5)
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
    # rev 5: night 11-02 (with its day) enters; window end 11-03 06:00 CST
    assert snap[1] == datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
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


def _one_night(monkeypatch, tmp_path, night_room, night_frac, day_room,
               day_frac, night=date(2026, 9, 15)):
    db = _make_db(tmp_path)
    occupy_fraction(db, night_room, night, night_frac)
    occupy_day(db, day_room, night, day_frac)
    return db


def test_one_night_with_day_enters(monkeypatch, tmp_path, proc_tz):
    """09-15 shape: GB2 night 0.95 with GB2 day 0.38 -> on the next morning
    (operator 2026-11-09: one night with a sustained day is legit)."""
    proc_tz("UTC")
    db = _one_night(monkeypatch, tmp_path, E2, 0.95, E2, 0.38)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 9, 15)) is False      # night not yet completed
    assert walk(c, at(2026, 9, 16)) is True
    last = c._guest_stay_basis[-1]
    assert last["night"] == "2026-09-15" and last["room"] == GB2
    assert last["fraction"] == pytest.approx(0.95, abs=1e-3)
    assert last["day_fraction"] == pytest.approx(0.38, abs=1e-3)
    assert last["qualifies"] is True and last["entry_qualified"] is True
    # rev 6: a one-night stay (n = 1) ends after ONE empty night
    assert [walk(c, at(2026, 9, d)) for d in (17, 18)] == [False, False]
    assert c._guest_stay_since is None          # review C L4: cleared on exit


def test_entry_nights_2_blocks_single_night(monkeypatch, tmp_path, proc_tz):
    """Same 09-15 shape at GUEST_STAY_ENTRY_NIGHTS 2 -> never on; a second
    qualifying night (with its day) -> on."""
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_ENTRY_NIGHTS", 2)
    db = _one_night(monkeypatch, tmp_path, E2, 0.95, E2, 0.38)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 9, 16)) is False
    assert walk(c, at(2026, 9, 17)) is False
    occupy_fraction(db, E2, date(2026, 9, 16), 0.3)
    occupy_day(db, E2, date(2026, 9, 16), 0.2)
    assert walk(c, at(2026, 9, 17)) is True


def test_one_night_without_day_never_enters(monkeypatch, tmp_path, proc_tz):
    """09-04 shape: GB2 night 0.51, GB2 day 0.02 -> off (a build that skipped
    the day test gives on)."""
    proc_tz("UTC")
    db = _one_night(monkeypatch, tmp_path, E2, 0.51, E2, 0.02,
                    night=date(2026, 9, 4))
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 9, 5)) is False
    last = c._guest_stay_basis[-1]
    assert last["qualifies"] is True and last["entry_qualified"] is False


def test_day_and_night_same_room(monkeypatch, tmp_path, proc_tz):
    """Day 0.60 in GB1 + night 0.72 in GB2 -> off (the day must be in the
    SAME room as the night); both in GB2 -> on."""
    proc_tz("UTC")
    db = _one_night(monkeypatch, tmp_path, E2, 0.72, E1, 0.60,
                    night=date(2026, 9, 27))
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 9, 28)) is False
    occupy_day(db, E2, date(2026, 9, 27), 0.21)
    assert walk(c, at(2026, 9, 28)) is True


def test_day_after_night_knob(monkeypatch, tmp_path, proc_tz):
    """Night 11-01 0.5 with no day before it, day 11-02 0.5 after it.
    Day-before (default) -> never on. GUEST_STAY_DAY_BEFORE_NIGHT False ->
    on at the walk after night 11-02 (one day later), not at 11-02."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy_fraction(db, E1, date(2026, 11, 1), 0.5)
    occupy_day(db, E1, date(2026, 11, 2), 0.5)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 2)) is False
    assert walk(c, at(2026, 11, 3)) is False
    monkeypatch.setattr(H.CONST, "GUEST_STAY_DAY_BEFORE_NIGHT", False)
    c2 = coord_with(monkeypatch, db)
    assert walk(c2, at(2026, 11, 2)) is False
    assert walk(c2, at(2026, 11, 3)) is True


def test_day_window_bounds(monkeypatch, proc_tz):
    """guest_day_window: local wall clock, ends at the night start, >= 1 h."""
    proc_tz("UTC")
    gdw = H.PR.guest_day_window
    n = date(2026, 11, 3)
    # live 22 -> 6, H 10: N 10:00 -> N 22:00 (12 h)
    assert gdw(n, 22, 6, 10, CHI) == (datetime(2026, 11, 3, 10, tzinfo=CHI),
                                       datetime(2026, 11, 3, 22, tzinfo=CHI))
    # non-wrapping 1 -> 6, H 10: N 10:00 -> N+1 01:00
    assert gdw(n, 1, 6, 10, CHI) == (datetime(2026, 11, 3, 10, tzinfo=CHI),
                                      datetime(2026, 11, 4, 1, tzinfo=CHI))
    # H >= sleep start (and H 21 = exactly 1 h): clamped to the 1 h before
    for h in (21, 22, 23):
        assert gdw(n, 22, 6, h, CHI) == (
            datetime(2026, 11, 3, 21, tzinfo=CHI),
            datetime(2026, 11, 3, 22, tzinfo=CHI)), h
    # non-wrapping with H 23: N 23:00 -> N+1 01:00 (2 h, no clamp)
    assert gdw(n, 1, 6, 23, CHI) == (datetime(2026, 11, 3, 23, tzinfo=CHI),
                                      datetime(2026, 11, 4, 1, tzinfo=CHI))
    # out-of-range hour clamps to 23
    assert gdw(n, 1, 6, 30, CHI)[0] == datetime(2026, 11, 3, 23, tzinfo=CHI)
    # DST fall-back day, H 0: 11-01 00:00 CDT -> 22:00 CST = 23 h real
    s, e = gdw(date(2026, 11, 1), 22, 6, 0, CHI)
    assert (e.astimezone(UTC) - s.astimezone(UTC)).total_seconds() == 23 * 3600
    # DST spring-forward day, H 0: 03-14 00:00 CST -> 22:00 CDT = 21 h real
    s, e = gdw(date(2027, 3, 14), 22, 6, 0, CHI)
    assert (e.astimezone(UTC) - s.astimezone(UTC)).total_seconds() == 21 * 3600


def test_day_resident_subtraction(monkeypatch, tmp_path, proc_tz):
    """A resident BLE visit covering the whole day in GB1 removes the day
    (a build that subtracted residents from nights only gives on)."""
    proc_tz("UTC")
    db = _one_night(monkeypatch, tmp_path, E1, 0.5, E1, 0.9,
                    night=date(2026, 11, 3))
    visit(db, GB1, datetime(2026, 11, 3, 9, tzinfo=CHI),
          datetime(2026, 11, 3, 21, 58, tzinfo=CHI))   # + 120 s pad = 22:00
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 4)) is False
    last = c._guest_stay_basis[-1]
    assert last["day_fraction"] == pytest.approx(0.0)
    assert last["fraction"] == pytest.approx(0.5, abs=1e-3)


def test_day_windows_one_read_per_room(monkeypatch, tmp_path):
    """Nights + days go through ONE span call per room (2 x span windows):
    nights first, then the matching day windows."""
    calls, pads = [], []

    class _Spy:
        async def get_guest_room_night_fractions(self, eid, room, windows, pad):
            calls.append((eid, list(windows)))
            pads.append(pad)
            return [(0.0, False)] * len(windows)

    c = coord_with(monkeypatch, _Spy())
    walk(c, at(2026, 11, 4))
    assert [eid for eid, _ in calls] == [E1, E2]
    # Review C M6: the producer wires the resident pad (GUEST_KNOWN_STICKY_S
    # = 120 s) into the read; literal oracle.
    assert pads == [120, 120]
    wins = calls[0][1]
    assert len(wins) == 2 * 37
    assert wins[36] == (datetime(2026, 11, 3, 22, tzinfo=CHI),
                        datetime(2026, 11, 4, 6, tzinfo=CHI))
    assert wins[73] == (datetime(2026, 11, 3, 10, tzinfo=CHI),
                        datetime(2026, 11, 3, 22, tzinfo=CHI))


def test_open_resident_visit_runs_to_window_end(monkeypatch, tmp_path,
                                               proc_tz):
    """Review A-L1: an open visit (exit_time NULL) from 23:00 is subtracted
    to the window end: kept 22:00 -> 22:58 = 3480 s of 28800."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(NIGHT), 8 * 3600)
    _seed(db, VIS, [("oji", GB1, datetime.fromtimestamp(
        datetime(2026, 11, 3, 23, tzinfo=CHI).timestamp()).isoformat(sep=" "),
        None, 0.9, "bermuda")])
    windows = [(night_start(NIGHT), datetime(2026, 11, 4, 6, tzinfo=CHI))]
    [(frac, had)] = H.run(db.get_guest_room_night_fractions(
        E1, GB1, windows, 120))
    assert frac == pytest.approx(3480 / 28800)
    assert had is True


def test_resident_only_night_is_not_evidence(monkeypatch, tmp_path, proc_tz):
    """Review A-L2: a night occupied only while a resident is there gives
    (0.0, False), so it cannot qualify even at GUEST_NIGHT_MIN_FRACTION 0."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(NIGHT), 8 * 3600)
    visit(db, GB1, datetime(2026, 11, 3, 21, tzinfo=CHI),
          datetime(2026, 11, 4, 7, tzinfo=CHI))
    windows = [(night_start(NIGHT), datetime(2026, 11, 4, 6, tzinfo=CHI))]
    assert H.run(db.get_guest_room_night_fractions(
        E1, GB1, windows, 120)) == [(0.0, False)]
    monkeypatch.setattr(H.CONST, "GUEST_NIGHT_MIN_FRACTION", 0.0)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_DAY_MIN_FRACTION", 0.0)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 4)) is False
    assert c._guest_stay_basis[-1]["qualifies"] is False


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
    """Fresh boot (no successful walk yet) + DB error: latch off even if it
    read on, basis {"error"}, and the night is NOT stamped evaluated (review
    A-M1 / B-M2); a retry is due 900 s later."""
    class _Boom:
        async def get_guest_room_night_fractions(self, *a, **k):
            raise RuntimeError("db locked")

    c = coord_with(monkeypatch, _Boom())
    c._guest_stay_active = True
    assert walk(c, at(2026, 11, 3)) is False
    assert c._guest_stay_basis == {"error": "db locked"}
    assert c._guest_stay_since is None
    assert c._guest_stay_evaluated_for is None
    assert c._guest_stay_retry_at == at(2026, 11, 3, 7, 15)


def test_db_error_keeps_prior_latch(monkeypatch, tmp_path, proc_tz):
    """Coordinator decision 2026-11-09: after a successful walk, a DB error
    KEEPS the latch (and since / basis) until the retry; not stamped."""
    proc_tz("UTC")
    real = _one_night(monkeypatch, tmp_path, E1, 0.5, E1, 0.5,
                      night=date(2026, 11, 2))
    c = coord_with(monkeypatch, real, rooms=((GB1, E1),))
    assert walk(c, at(2026, 11, 3)) is True
    snap = (c._guest_stay_since, c._guest_stay_basis)

    class _Boom:
        async def get_guest_room_night_fractions(self, *a, **k):
            raise RuntimeError("db locked")

    c.hass.data[H.DOMAIN]["database"] = _Boom()
    assert walk(c, at(2026, 11, 4)) is True
    assert (c._guest_stay_since, c._guest_stay_basis) == snap
    assert c._guest_stay_evaluated_for == date(2026, 11, 3)
    assert c._guest_stay_retry_at == at(2026, 11, 4, 7, 15)


def test_db_error_then_success_same_day(monkeypatch, tmp_path, proc_tz):
    """Error at 07:00 -> no re-schedule at 07:14:59 (backoff), re-scheduled
    at 07:15:00; that walk succeeds -> latch on the same morning."""
    proc_tz("UTC")
    real = _one_night(monkeypatch, tmp_path, E1, 0.5, E1, 0.5,
                      night=date(2026, 11, 2))

    class _Flaky:
        fails = 1

        async def get_guest_room_night_fractions(self, *a, **k):
            if _Flaky.fails:
                _Flaky.fails -= 1
                raise RuntimeError("database is locked")
            return await real.get_guest_room_night_fractions(*a, **k)

    c = coord_with(monkeypatch, _Flaky(), rooms=((GB1, E1),))
    scheduled = []

    def _sched(coro, *a, **k):
        scheduled.append(coro)
        return MagicMock(done=MagicMock(return_value=True))

    c.hass.async_create_task = _sched
    assert c._maybe_schedule_guest_stay_refresh(at(2026, 11, 3, 7, 0)) is True
    coro = scheduled.pop()
    coro.close()
    walk(c, at(2026, 11, 3, 7, 0))
    assert c._guest_stay_active is False
    assert c._maybe_schedule_guest_stay_refresh(at(2026, 11, 3, 7, 14, 59)) is False
    assert scheduled == []
    assert c._maybe_schedule_guest_stay_refresh(at(2026, 11, 3, 7, 15, 0)) is True
    coro = scheduled.pop()
    coro.close()
    assert walk(c, at(2026, 11, 3, 7, 15, 0)) is True
    assert c._guest_stay_evaluated_for == date(2026, 11, 3)
    assert c._guest_stay_retry_at is None


def test_non_wrapping_window(monkeypatch, tmp_path, proc_tz):
    """Sleep window 1 -> 6: night N = [N+1 01:00, N+1 06:00)."""
    proc_tz("UTC")
    w = H.PR.guest_night_window(date(2026, 11, 3), 1, 6, CHI)
    assert w == (datetime(2026, 11, 4, 1, tzinfo=CHI),
                 datetime(2026, 11, 4, 6, tzinfo=CHI))
    db = _make_db(tmp_path)
    occupy(db, E1, datetime(2026, 11, 3, 1, tzinfo=CHI), 5 * 3600)
    occupy(db, E1, datetime(2026, 11, 4, 1, tzinfo=CHI), 5 * 3600)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_DAY_MIN_FRACTION", 0.0)
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
    monkeypatch.setattr(H.CONST, "GUEST_STAY_DAY_MIN_FRACTION", 0.0)
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
    assert seen == [2 * span]   # nights + their day windows


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
    # Review B-L1: the cancelled walk never stamped the night, the DB is
    # still there, yet a tick during/after teardown schedules nothing.
    assert w.coord._guest_stay_evaluated_for is None
    w.hass.async_create_task = MagicMock()
    assert w.coord._maybe_schedule_guest_stay_refresh() is False
    w.hass.async_create_task.assert_not_called()


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
    # Review B-L2 / A-L4: a re-discovery (room flagged / un-flagged without
    # a reload) clears the evaluated night so the next tick re-walks.
    w.coord._guest_stay_evaluated_for = date(2026, 11, 3)
    w.coord._guest_stay_retry_at = datetime(2026, 11, 3, 15, tzinfo=UTC)
    w.coord._discover_guest_rooms()
    assert w.coord._guest_room_entry_ids == {GB1: "E_GB1", GB2: "E_GB2"}
    assert w.coord._guest_stay_evaluated_for is None
    assert w.coord._guest_stay_retry_at is None
    # Review C M5: GB2 un-flagged mid-stay drops out of the walk's room map.
    entries[1].options = {H.CONST.CONF_ROOM_IS_GUEST_ROOM: False}
    w.coord._discover_guest_rooms()
    assert w.coord._guest_room_entry_ids == {GB1: "E_GB1"}


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


# --- Review C (test authority) -------------------------------------------------

BND = date(2026, 11, 3)   # CST: night 8 h = 28800 s, day 10:00-22:00 = 43200 s


@pytest.mark.parametrize("night_s,expect", [
    (7200, True),     # exactly 0.25 enters (>=)
    (7171, False),    # 0.249 does not
])
def test_night_threshold_boundary(monkeypatch, tmp_path, proc_tz,
                                  night_s, expect):
    """M1: GUEST_NIGHT_MIN_FRACTION 0.25 pinned at the edge (literals)."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(BND), night_s)
    occupy_day(db, E1, BND, 0.5)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 4)) is expect


def test_night_threshold_above_edge(monkeypatch, tmp_path, proc_tz):
    """M1: 0.26 enters (pins the constant from above: 0.30 would refuse)."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(BND), 7488)    # 0.26
    occupy_day(db, E1, BND, 0.5)
    assert walk(coord_with(monkeypatch, db), at(2026, 11, 4)) is True


@pytest.mark.parametrize("day_s,expect", [
    (4320, True),     # exactly 0.10 enters (>=)
    (4277, False),    # 0.099 does not
    (4752, True),     # 0.11 enters (0.15 would refuse)
])
def test_day_threshold_boundary(monkeypatch, tmp_path, proc_tz, day_s, expect):
    """M1: GUEST_STAY_DAY_MIN_FRACTION 0.10 pinned on both sides."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy_fraction(db, E1, BND, 0.5)
    occupy(db, E1, day_start(BND), day_s)
    assert walk(coord_with(monkeypatch, db), at(2026, 11, 4)) is expect


def test_day_after_variant_same_room(monkeypatch, tmp_path, proc_tz):
    """M2: with GUEST_STAY_DAY_BEFORE_NIGHT False, night 11-01 in GB1 + day
    11-02 in GB2 -> off; the same day in GB1 -> on."""
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_DAY_BEFORE_NIGHT", False)
    db = _make_db(tmp_path)
    occupy_fraction(db, E1, date(2026, 11, 1), 0.5)
    occupy_day(db, E2, date(2026, 11, 2), 0.5)
    assert walk(coord_with(monkeypatch, db), at(2026, 11, 3)) is False
    occupy_day(db, E1, date(2026, 11, 2), 0.5)
    assert walk(coord_with(monkeypatch, db), at(2026, 11, 3)) is True


def test_two_db_errors_keep_latch(monkeypatch, tmp_path, proc_tz):
    """M4: success, error, error -> the latch is still on (a DB outage spans
    several 15-min retries)."""
    proc_tz("UTC")
    real = _one_night(monkeypatch, tmp_path, E1, 0.5, E1, 0.5,
                      night=date(2026, 11, 2))
    c = coord_with(monkeypatch, real, rooms=((GB1, E1),))
    assert walk(c, at(2026, 11, 3)) is True

    class _Boom:
        async def get_guest_room_night_fractions(self, *a, **k):
            raise RuntimeError("db locked")

    c.hass.data[H.DOMAIN]["database"] = _Boom()
    assert walk(c, at(2026, 11, 4, 7, 0)) is True
    assert walk(c, at(2026, 11, 4, 7, 15)) is True
    assert c._guest_stay_retry_at == at(2026, 11, 4, 7, 30)


def test_zero_length_window(monkeypatch, tmp_path):
    """L1: a zero-length window (sleep start == end) reads (0.0, False), no
    ZeroDivisionError."""
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(BND), 3600)
    w = (night_start(BND), night_start(BND))
    assert H.run(db.get_guest_room_night_fractions(E1, GB1, [w], 120)) \
        == [(0.0, False)]


def test_malformed_person_visits_rows(monkeypatch, tmp_path, proc_tz):
    """L2: an unparseable row is skipped (not raised); a row with exit before
    entry is a point visit (pad only): 8 h night, point at 23:00 padded
    120 s each side -> (28800 - 240) / 28800."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy(db, E1, night_start(NIGHT), 8 * 3600)

    def _p(x):
        return datetime.fromtimestamp(x.timestamp()).isoformat(sep=" ")
    _seed(db, VIS, [
        ("oji", GB1, "2026-11-04 01:00:00garbage", None, 0.9, "bermuda"),
        ("oji", GB1, _p(datetime(2026, 11, 3, 23, tzinfo=CHI)),
         _p(datetime(2026, 11, 3, 22, 30, tzinfo=CHI)), 0.9, "bermuda"),
    ])
    windows = [(night_start(NIGHT), datetime(2026, 11, 4, 6, tzinfo=CHI))]
    [(frac, had)] = H.run(db.get_guest_room_night_fractions(
        E1, GB1, windows, 120))
    assert frac == pytest.approx((28800 - 240) / 28800)
    assert had is True


def test_stay_rooms_lists_qualifying_only(monkeypatch):
    """L6: night_stay:<rooms> / the D4 diagnosis list only qualifying rooms."""
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC), tz=CHI)
    w = H.World(monkeypatch, state=HS.HOME_DAY)
    w.coord._guest_stay_basis = [
        {"night": "2026-11-01", "room": GB2, "fraction": 0.02,
         "qualifies": False},
        {"night": "2026-11-02", "room": GB1, "fraction": 0.5,
         "qualifies": True},
    ]
    assert w.coord._guest_stay_rooms() == GB1


# --- Rev 6: exit scaled to the stay (plan §2.3, §14, INV-STAY-4) ----------------

def _entry_night(db, d, room=E1):
    occupy_fraction(db, room, d, 0.5)
    occupy_day(db, room, d, 0.5)


def _days(c, dates):
    return [walk(c, at(d.year, d.month, d.day)) for d in dates]


def test_one_night_visit_exits_after_one_empty_night(monkeypatch, tmp_path,
                                                     proc_tz):
    """One entry-qualified night (0.9 / day 0.38), then empty: on the morning
    after, off the morning after the first empty night (rev 5: on until the
    third)."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy_fraction(db, E2, date(2026, 11, 1), 0.9)
    occupy_day(db, E2, date(2026, 11, 1), 0.38)
    c = coord_with(monkeypatch, db)
    assert _days(c, [date(2026, 11, 2), date(2026, 11, 3)]) == [True, False]
    assert c._guest_stay_since is None


def test_two_night_visit_exits_after_two(monkeypatch, tmp_path, proc_tz):
    proc_tz("UTC")
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 11, 1))
    occupy_fraction(db, E1, date(2026, 11, 2), 0.5)
    c = coord_with(monkeypatch, db)
    assert _days(c, [date(2026, 11, d) for d in (3, 4, 5)]) == [True, True, False]


def test_long_stay_ends_after_two_empty_nights(monkeypatch, tmp_path, proc_tz):
    """Operator cap (2026-11-09): 5 qualifying nights then 2 empty -> off the
    morning after the second empty night (10-13/10-14 shape). One empty
    night is held."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 10, 1))
    for d in (2, 3, 4, 5, 8):
        occupy_fraction(db, E1, date(2026, 10, d), 0.5)
    c = coord_with(monkeypatch, db)
    got = _days(c, [date(2026, 10, d) for d in range(2, 10)])
    #      10-02..10-06 on (1 empty at 10-07 morning), 10-08 off, 10-09 off
    #      (night 10-08 qualifies but has no day: no re-entry)
    assert got == [True] * 6 + [False, False]


@pytest.mark.parametrize("cap,expect", [(2, False), (3, True), (1, False)])
def test_exit_cap_knob(monkeypatch, tmp_path, proc_tz, cap, expect):
    """GUEST_STAY_EXIT_MAX_NIGHTS: a 5-night stay after 2 empty nights is off
    at cap 2 (default), still on at cap 3; cap 1 -> off after 1."""
    proc_tz("UTC")
    if cap != 2:
        monkeypatch.setattr(H.CONST, "GUEST_STAY_EXIT_MAX_NIGHTS", cap)
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 10, 1))
    for d in (2, 3, 4, 5):
        occupy_fraction(db, E1, date(2026, 10, d), 0.5)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 10, 8)) is expect      # nights 10-06, 10-07 empty
    if cap == 1:
        assert walk(c, at(2026, 10, 7)) is False   # one empty night


def test_exit_cap_above_lookback_safe(monkeypatch, tmp_path, proc_tz):
    """Cap 5 > lookback 3: no slice underflow; a 5-night stay holds 4 empty
    nights and ends after the 5th."""
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_EXIT_MAX_NIGHTS", 5)
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 10, 1))
    for d in (2, 3, 4, 5):
        occupy_fraction(db, E1, date(2026, 10, d), 0.5)
    c = coord_with(monkeypatch, db)
    assert _days(c, [date(2026, 10, d) for d in (10, 11)]) == [True, False]


def test_exit_count_starts_at_entry_q(monkeypatch, tmp_path, proc_tz):
    """09-04 / 09-05 shape: night 1 qualifies with day 0.02 (not entry), night
    2 entry-qualified -> n starts at 2 -> off after 2 empty nights, not 1."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    occupy_fraction(db, E2, date(2026, 9, 4), 0.51)
    occupy_day(db, E2, date(2026, 9, 4), 0.02)
    occupy_fraction(db, E2, date(2026, 9, 5), 0.51)
    occupy_day(db, E2, date(2026, 9, 5), 0.24)
    c = coord_with(monkeypatch, db)
    assert _days(c, [date(2026, 9, d) for d in (5, 6, 7, 8)]) == \
        [False, True, True, False]


def test_exit_never_on_entry_night(monkeypatch, tmp_path, proc_tz):
    """Lookback 1, scaled: the entry night itself never exits."""
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_LOOKBACK_NIGHTS", 1)
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 11, 1))
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, 2)) is True


def test_exit_count_resets_on_reentry(monkeypatch, tmp_path, proc_tz):
    """A 4-night stay, 2 empty (off at the cap), then a one-night entry, then
    empty -> off after ONE empty night (the old stay's count is not carried
    over; a carried n would hold to the cap, 2)."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 10, 1))
    for d in (2, 3, 4):
        occupy_fraction(db, E1, date(2026, 10, d), 0.5)
    _entry_night(db, date(2026, 10, 8))
    c = coord_with(monkeypatch, db)
    got = _days(c, [date(2026, 10, d) for d in range(5, 11)])
    #      10-05 T, 10-06 T, 10-07 off (cap 2), 10-08 off, 10-09 re-entry,
    #      10-10 off
    assert got == [True, True, False, False, True, False]


def test_exit_scaled_restart_between_empty_nights(monkeypatch, tmp_path,
                                                  proc_tz):
    """2-night visit then empty: fresh coordinators (restart) on the mornings
    after the first and the second empty night agree with a continuous run."""
    proc_tz("UTC")
    db = _make_db(tmp_path)
    _entry_night(db, date(2026, 11, 1))
    occupy_fraction(db, E1, date(2026, 11, 2), 0.5)
    cont = coord_with(monkeypatch, db)
    run = _days(cont, [date(2026, 11, d) for d in (3, 4, 5)])
    fresh = [walk(coord_with(monkeypatch, db), at(2026, 11, d)) for d in (4, 5)]
    assert run == [True, True, False]
    assert fresh == run[1:]


@pytest.mark.parametrize("lookback,scaled,quals,check_day,expect", [
    (1, True, [1], 3, False),          # L 1: one night, 1 empty -> off
    (7, True, [1, 2], 4, True),        # L 7, n 2: 1 empty -> still on
    (7, True, [1, 2], 5, False),       # L 7, n 2: off after 2 empty, not 7
    (3, False, [1], 4, True),          # knob off, n 1: on after 2 empty (rev 5)
])
def test_config_extremes_exit(monkeypatch, tmp_path, proc_tz, lookback,
                              scaled, quals, check_day, expect):
    proc_tz("UTC")
    monkeypatch.setattr(H.CONST, "GUEST_STAY_DAY_MIN_FRACTION", 0.0)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_LOOKBACK_NIGHTS", lookback)
    monkeypatch.setattr(H.CONST, "GUEST_STAY_EXIT_SCALES_WITH_STAY", scaled)
    db = _make_db(tmp_path)
    for d in quals:
        occupy_fraction(db, E1, date(2026, 11, d), 0.5)
    c = coord_with(monkeypatch, db)
    assert walk(c, at(2026, 11, check_day)) is expect
