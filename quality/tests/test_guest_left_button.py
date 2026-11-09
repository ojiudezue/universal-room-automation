"""GUEST-MODE-SPLIT-VISITORS-1 — "Guest left" button (operator 2026-11-09).

Press -> PresenceCoordinator.async_guest_left: clear the stay latch, leave
GUEST through the normal transition path (trigger ``guest_left_button``, S9
exit hold skipped once), record the press (RAM + HA Store), and refuse
re-entry until a qualifying night that STARTS after the press (no re-entry
grace from a button exit). Real walk over the real DB (producer harness);
the HA Store is replaced by an in-memory fake shared across "restarts".
"""
from __future__ import annotations

import importlib
from datetime import date, datetime, timedelta, timezone

import pytest

import guest_split_harness as H
import test_guest_stay_producer as P
from test_guest_split_gate import DAY, _world
from test_guest_stay_producer import proc_tz  # noqa: F401 (fixture)

HS = H.HS
UTC = timezone.utc


class _FakeStore:
    def __init__(self, shared):
        self.shared = shared

    async def async_load(self):
        return self.shared.get("data")

    async def async_save(self, data):
        self.shared["data"] = dict(data)


@pytest.fixture
def store(monkeypatch):
    shared = {}
    monkeypatch.setattr(H.PR.PresenceCoordinator, "_guest_left_store",
                        lambda self: _FakeStore(shared))
    return shared


def _stay_db(tmp_path, first=date(2026, 11, 1), nights=3):
    db = P._make_db(tmp_path)
    P._entry_night(db, first)
    for i in range(1, nights):
        P.occupy_fraction(db, P.E1, first + timedelta(days=i), 0.5)
    return db


def press(coord, when_utc):
    H.run(coord.async_guest_left(when_utc))


# --- press -> exits GUEST now -------------------------------------------------

def test_press_exits_guest_now(monkeypatch, store, caplog):
    """GUEST with the latch on: one press leaves GUEST on the press's own tick
    (no 300 s S9 hold) via transition(trigger="guest_left_button"); the press
    time is persisted."""
    w, clock = _world(monkeypatch, state=HS.GUEST, at=DAY, stay=True)
    assert w.tick() == HS.GUEST
    triggers = []
    real = w.sm.transition

    def _spy(new_state, trigger=""):
        triggers.append((new_state, trigger))
        return real(new_state, trigger=trigger)

    w.sm.transition = _spy
    with caplog.at_level("INFO"):
        press(w.coord, DAY)
    assert w.sm.state == HS.HOME_DAY
    assert triggers == [(HS.HOME_DAY, "guest_left_button")]
    assert w.coord._guest_stay_active is False
    assert w.coord._guest_left_at == DAY
    assert store["data"] == {"pressed_at": "2026-11-10T14:00:00+00:00"}
    assert any("guest_left_button" in r.getMessage() for r in caplog.records)
    assert w.coord._guest_left_exit_now is False      # one-shot


# --- the walk after a press -----------------------------------------------------

def test_walk_does_not_relatch_old_nights(monkeypatch, tmp_path, proc_tz, store):
    """3-night stay on; press 11-04 09:00 local. A re-walk the same morning
    and the next morning's walk (night 11-04 empty) stay off: the nights that
    started before the press never re-latch."""
    proc_tz("UTC")
    db = _stay_db(tmp_path)
    c = P.coord_with(monkeypatch, db)
    assert P.walk(c, P.at(2026, 11, 4)) is True
    press(c, P.at(2026, 11, 4, 9).astimezone(UTC))
    assert P.walk(c, P.at(2026, 11, 4, 10)) is False
    assert P.walk(c, P.at(2026, 11, 5)) is False


def test_new_night_and_day_after_press_reenters(monkeypatch, tmp_path, proc_tz,
                                                store):
    """After the press, a new entry-qualified night (night 11-04 with its day
    11-04 10:00-22:00, both after the 09:00 press) re-enters."""
    proc_tz("UTC")
    db = _stay_db(tmp_path)
    c = P.coord_with(monkeypatch, db)
    press(c, P.at(2026, 11, 4, 9).astimezone(UTC))
    P._entry_night(db, date(2026, 11, 4))
    assert P.walk(c, P.at(2026, 11, 5)) is True


def test_button_exit_gets_no_grace(monkeypatch, tmp_path, proc_tz, store):
    """A stay ended by empty nights opens the 7-day re-entry grace; a press
    afterwards cancels it: a lone night after the press (no day) does NOT
    re-enter. Without the press it would."""
    proc_tz("UTC")
    db = _stay_db(tmp_path, first=date(2026, 10, 28))   # 10-28..10-30
    # nights 10-31 and 11-01 empty -> ended by empty nights (grace open)
    P.occupy_fraction(db, P.E2, date(2026, 11, 2), 0.5)  # lone night, no day
    c = P.coord_with(monkeypatch, db)
    assert P.walk(c, P.at(2026, 11, 3)) is True          # grace re-entry
    c2 = P.coord_with(monkeypatch, db)
    press(c2, P.at(2026, 11, 2, 9).astimezone(UTC))
    assert P.walk(c2, P.at(2026, 11, 3)) is False


def test_restart_does_not_relatch(monkeypatch, tmp_path, proc_tz, store):
    """Press on one coordinator; a fresh coordinator (restart) reads the
    persisted press and its walk stays off."""
    proc_tz("UTC")
    db = _stay_db(tmp_path)
    c1 = P.coord_with(monkeypatch, db)
    press(c1, P.at(2026, 11, 4, 9).astimezone(UTC))
    c2 = P.coord_with(monkeypatch, db)
    assert c2._guest_left_at is None
    assert P.walk(c2, P.at(2026, 11, 4, 10)) is False
    assert c2._guest_left_at == P.at(2026, 11, 4, 9).astimezone(UTC)


def test_press_during_a_night_does_not_count_that_night(monkeypatch, tmp_path,
                                                       proc_tz, store):
    """Press at 23:00 inside night 11-04 (which qualifies with its day): that
    night STARTED before the press, so it cannot re-enter; the next walk is
    off."""
    proc_tz("UTC")
    db = P._make_db(tmp_path)
    P._entry_night(db, date(2026, 11, 4))
    c = P.coord_with(monkeypatch, db)
    press(c, P.at(2026, 11, 4, 23).astimezone(UTC))
    assert P.walk(c, P.at(2026, 11, 5)) is False


# --- the entity ------------------------------------------------------------------

def test_button_entity_wires_to_presence(monkeypatch):
    """button.ura_presence_coordinator_guest_left: unique id, plain label,
    Presence Coordinator device, press -> async_guest_left."""
    BT = importlib.import_module(f"{H._PKG}.button")
    called = []

    class _Pres:
        async def async_guest_left(self):
            called.append(True)

    hass = H.MagicMock()
    hass.data = {H.DOMAIN: {"coordinator_manager": H.MagicMock(
        coordinators={"presence": _Pres()})}}
    b = BT.GuestLeftButton(hass, H.MagicMock())
    assert b.unique_id == "universal_room_automation_guest_left"
    assert b.name == "Guest left"
    assert b.device_info["identifiers"] == {("universal_room_automation",
                                             "presence_coordinator")}
    assert b.available is True
    H.run(b.async_press())
    assert called == [True]
