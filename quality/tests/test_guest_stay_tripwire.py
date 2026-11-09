"""GUEST-MODE-SPLIT-VISITORS-1 D4 — trip-wire: stay latch held too long.

Plan: docs/planning/PLANNING_guest_mode_split_2026_11.md rev 4 §D4.

One HIGH stuck-signal NM (kind guest_stay_long, key ("house",)) when the stay
latch has been on more than GUEST_STAY_LONG_NM_DAYS days counted from the
DB-walk `since`. Once per stay, re-armed when the latch drops, 0 = off.
Boundaries are hardcoded literals (28 d = 2419200 s).
"""
from __future__ import annotations

import importlib
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import guest_split_harness as H
import test_guest_stay_producer as P
from test_guest_stay_producer import proc_tz  # noqa: F401 (fixture)

HS = H.HS
UTC = timezone.utc
SINCE = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)


@pytest.fixture
def fired(monkeypatch):
    out = []
    mod = importlib.import_module(f"{H._PKG}.domain_coordinators._stuck_signal_nm")

    async def _fake(hass, kind, key, diagnosis, remedy="", **kw):
        out.append({"kind": kind, "key": key, "diagnosis": diagnosis,
                    "remedy": remedy, **kw})
        return True

    monkeypatch.setattr(mod, "fire_stuck_signal", _fake)
    return out


def _coord(monkeypatch, *, active=True, since=SINCE):
    H.install_clock(monkeypatch, datetime(2026, 11, 3, 14, tzinfo=UTC))
    w = H.World(monkeypatch, state=HS.HOME_DAY)

    w.pending = []

    def _sched(coro, *a, **k):
        if getattr(coro, "__qualname__", "").endswith("_fake"):
            w.pending.append(coro)
        else:
            coro.close()
        return MagicMock()

    w.hass.async_create_task = _sched
    w.coord._guest_stay_active = active
    w.coord._guest_stay_since = since
    w.coord._guest_stay_basis = [
        {"night": "2026-10-28", "room": "Guest Bedroom 1", "fraction": 0.61,
         "qualifies": True}]
    return w


def drain(w):
    while w.pending:
        H.run(w.pending.pop(0))


def chk(w, now_utc):
    w.coord._check_guest_stay_long(now_utc)
    drain(w)


def test_fires_once(monkeypatch, fired):
    w = _coord(monkeypatch)
    chk(w, SINCE + timedelta(seconds=2419200))  # = 28 d
    assert fired == []
    chk(w, SINCE + timedelta(seconds=2419201))
    assert len(fired) == 1
    f = fired[0]
    assert f["kind"] == "guest_stay_long" and f["key"] == ("house",)
    assert f["severity"] == "HIGH"
    assert "Guest Bedroom 1" in f["diagnosis"] and "0.61" in f["diagnosis"]
    assert "Guest Detection" in f["remedy"]
    chk(w, SINCE + timedelta(days=40))
    assert len(fired) == 1


def test_zero_disables(monkeypatch, fired):
    monkeypatch.setattr(H.CONST, "GUEST_STAY_LONG_NM_DAYS", 0)
    w = _coord(monkeypatch)
    chk(w, SINCE + timedelta(days=400))
    assert fired == []


def test_rearms_after_stay(monkeypatch, fired):
    w = _coord(monkeypatch)
    chk(w, SINCE + timedelta(days=29))
    assert len(fired) == 1
    w.coord._guest_stay_active = False
    w.coord._guest_stay_since = None
    chk(w, SINCE + timedelta(days=30))
    assert w.coord._guest_stay_long_nm_fired is False
    new_since = SINCE + timedelta(days=60)
    w.coord._guest_stay_active = True
    w.coord._guest_stay_since = new_since
    chk(w, new_since + timedelta(days=29))
    assert len(fired) == 2


def test_tick_calls_tripwire(monkeypatch, fired):
    """Wire-in: _run_inference calls the trip-wire (clock 2026-11-03 14:00Z
    is 33 days after SINCE)."""
    w = _coord(monkeypatch)
    w.tick()
    drain(w)
    assert [f["kind"] for f in fired] == ["guest_stay_long"]


def _stay_db(tmp_path, nights):
    db = P._make_db(tmp_path)
    d = date(2026, 9, 1)
    for _ in range(nights):
        P.occupy_fraction(db, P.E1, d, 0.5)
        d += timedelta(days=1)
    return db


def test_since_survives_restart(monkeypatch, tmp_path, proc_tz):
    """`since` comes from the DB walk: a fresh coordinator walking the same
    DB 10 days later reports the same since (the window end of night 09-02,
    06:00 CDT = 11:00Z on 09-03)."""
    proc_tz("UTC")
    db = _stay_db(tmp_path, 30)
    c1 = P.coord_with(monkeypatch, db)
    P.walk(c1, P.at(2026, 9, 10))
    c2 = P.coord_with(monkeypatch, db)
    P.walk(c2, P.at(2026, 9, 20))
    assert c1._guest_stay_since == c2._guest_stay_since \
        == datetime(2026, 9, 3, 11, 0, tzinfo=UTC)


def test_fires_on_stay_longer_than_bound(monkeypatch, tmp_path, proc_tz, fired):
    """A 30-night stay (nights 09-01..09-30) through the REAL walk each
    morning at 07:00 CDT, bound 28: since = 09-03 11:00Z; 28 d later =
    10-01 11:00Z = 06:00 CDT, so the 10-01 07:00 check fires, 09-30 does not.
    With a walk shorter than the bound, since is re-dated and it never fires."""
    proc_tz("UTC")
    db = _stay_db(tmp_path, 30)
    c = P.coord_with(monkeypatch, db)

    pending = []

    def _sched(coro, *a, **k):
        if getattr(coro, "__qualname__", "").endswith("_fake"):
            pending.append(coro)
        else:
            coro.close()
        return MagicMock()

    c.hass.async_create_task = _sched
    fired_on = []
    day = date(2026, 9, 2)
    while day <= date(2026, 10, 2):
        now = P.at(day.year, day.month, day.day)
        P.walk(c, now)
        before = len(fired)
        c._check_guest_stay_long(now.astimezone(UTC))
        while pending:
            H.run(pending.pop(0))
        if len(fired) > before:
            fired_on.append(day)
        day += timedelta(days=1)
    assert fired_on == [date(2026, 10, 1)]
