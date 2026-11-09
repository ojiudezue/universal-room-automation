"""GUEST-MODE-SPLIT-VISITORS-1 D3 — GUEST from the night-stay latch.

Plan: docs/planning/PLANNING_guest_mode_split_2026_11.md rev 4 §2.3, §2.5, D3.

Invariants under test:
  INV-STAY-1  rule ON: GUEST is entered from HOME_* only on a tick where the
              stay latch is on AND guest detection is on; the 30-min room
              gate alone never enters.
  INV-STAY-2  rule ON: a non-overridden GUEST does not hold past the first
              tick at or after sleep_start + the S9 guest-exit persistence
              (300 s), then SLEEP after the HOME_NIGHT dwell.
  INV-STAY-3  rule OFF: guest_armed / guest_reason / confidence / infer()
              result / final state / gate call counts are identical to the
              golden generated on the base tree (develop @ f8cbcba4, code ==
              4b52c262) BEFORE this change.

Every test drives the REAL PresenceCoordinator._run_inference (real gates,
real HouseStateMachine). The stay latch is set on the coordinator field here
(its one writer, the DB walk, is tested in test_guest_stay_producer.py).
Clock: local zone = UTC so wall-clock literals are the oracle.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import guest_split_harness as H

HS = H.HS
GOLDEN = Path(__file__).parent / "fixtures" / "guest_split_golden_base.json"


def _world(monkeypatch, *, state, at, stay=False, room_min=None, switch=True):
    clock = H.install_clock(monkeypatch, at)
    w = H.World(monkeypatch, state=state)
    w.coord._guest_detection_enabled = switch
    w.coord._guest_stay_active = stay
    if stay:
        w.coord._guest_stay_basis = [
            {"night": "2026-11-08", "room": H.GB1, "fraction": 0.6,
             "qualifies": True},
            {"night": "2026-11-09", "room": H.GB1, "fraction": 0.7,
             "qualifies": True},
        ]
    w.guest_room(room_min)
    return w, clock


DAY = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)


# --- INV-STAY-1 ------------------------------------------------------------

@pytest.mark.parametrize("state", [HS.HOME_DAY, HS.HOME_EVENING, HS.HOME_NIGHT])
@pytest.mark.parametrize("room", [True, False])
@pytest.mark.parametrize("stay", [True, False])
@pytest.mark.parametrize("switch", [True, False])
def test_entry_matrix(monkeypatch, state, room, stay, switch):
    """GUEST proposed iff stay AND switch, from every HOME_* state, at an
    hour outside the sleep window (20:00 local, window 22 -> 6)."""
    at = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
    w, _ = _world(monkeypatch, state=state, at=at, stay=stay,
                  room_min=45 if room else None, switch=switch)
    final = w.tick()
    armed, proposal = w.infer_calls[-1]
    expect_guest = stay and switch
    assert armed is expect_guest
    assert (final == HS.GUEST) is expect_guest
    assert (proposal == HS.GUEST) is expect_guest


def test_room_alone_never_enters(monkeypatch):
    """The 10-17 shape with no stay: 45 min unknown in a guest room at 16:06,
    house HOME_DAY -> house stays HOME_DAY, reason guest_room:<room>,
    visitors_present on with legs.room. (A build that ORs the room gate into
    entry goes GUEST here.)"""
    at = datetime(2026, 11, 10, 16, 6, tzinfo=timezone.utc)
    w, _ = _world(monkeypatch, state=HS.HOME_DAY, at=at, room_min=45)
    assert w.tick() == HS.HOME_DAY
    assert w.coord._guest_reason == f"guest_room:{H.GB1}"
    assert w.coord._visitors_present is True
    assert w.coord._visitors_legs["room"] is True


def test_guest_reason_night_stay(monkeypatch):
    """Same 16:06 shape with the stay latch on: GUEST, reason
    night_stay:<qualifying rooms> (before guest_room:)."""
    at = datetime(2026, 11, 10, 16, 6, tzinfo=timezone.utc)
    w, _ = _world(monkeypatch, state=HS.HOME_DAY, at=at, stay=True,
                  room_min=45)
    assert w.tick() == HS.GUEST
    assert w.coord._guest_reason == f"night_stay:{H.GB1}"


def test_switch_off_blocks_stay(monkeypatch):
    """Guest detection OFF masks the latch: no entry, and an existing GUEST
    exits (stay masked)."""
    w, _ = _world(monkeypatch, state=HS.HOME_DAY, at=DAY, stay=True,
                  switch=False)
    assert w.tick() == HS.HOME_DAY
    assert w.infer_calls[-1][0] is False
    assert w.coord._guest_reason == "none"
    w2, clock = _world(monkeypatch, state=HS.GUEST, at=DAY, stay=True,
                       switch=False)
    w2.tick()                       # exit proposed, S9 quiet clock starts
    clock.advance(300)
    assert w2.tick() == HS.HOME_DAY


# --- INV-STAY-2 (night yield) ----------------------------------------------

def _tick_until(w, clock, until, step=30):
    trace = []
    while clock.t < until:
        trace.append((clock.t, w.tick()))
        clock.advance(step)
    return trace


def test_night_yield_exits_to_home_night(monkeypatch):
    """GUEST + stay at 21:58 -> still GUEST through 22:04:30 (S9 persistence
    300 s from the 22:00 proposal), HOME_NIGHT at 22:05:00, SLEEP at 22:07:00
    (HOME_NIGHT dwell 120 s)."""
    at = datetime(2026, 11, 10, 21, 58, tzinfo=timezone.utc)
    w, clock = _world(monkeypatch, state=HS.GUEST, at=at, stay=True)
    trace = dict(_tick_until(
        w, clock, datetime(2026, 11, 10, 22, 8, tzinfo=timezone.utc)))
    t = lambda h, m, s=0: datetime(2026, 11, 10, h, m, s, tzinfo=timezone.utc)  # noqa: E731
    assert trace[t(21, 59, 30)] == HS.GUEST
    assert trace[t(22, 4, 30)] == HS.GUEST
    assert trace[t(22, 5, 0)] == HS.HOME_NIGHT
    assert trace[t(22, 6, 30)] == HS.HOME_NIGHT
    assert trace[t(22, 7, 0)] == HS.SLEEP


def test_guest_exit_veto_bound(monkeypatch):
    """INV-STAY-2 bound measured: the first non-GUEST tick is at
    sleep_start + 300 s exactly (30 s ticks aligned to 22:00)."""
    at = datetime(2026, 11, 10, 21, 59, 30, tzinfo=timezone.utc)
    w, clock = _world(monkeypatch, state=HS.GUEST, at=at, stay=True)
    trace = _tick_until(w, clock,
                        datetime(2026, 11, 10, 22, 10, tzinfo=timezone.utc))
    first_exit = next(ts for ts, st in trace if st != HS.GUEST)
    assert first_exit == datetime(2026, 11, 10, 22, 5, 0, tzinfo=timezone.utc)


def test_morning_reentry(monkeypatch):
    """Stay on. SLEEP 05:00-05:59: never GUEST (the sleep branch wins; the
    pre-existing SLEEP -> WAKING sustained gate is not this cycle's). From
    WAKING at 06:00: WAKING -> HOME_DAY (WAKING dwell 60 s) -> GUEST (HOME_DAY
    dwell 120 s): HOME_DAY at 06:00:00, GUEST at 06:02:00."""
    at = datetime(2026, 11, 11, 5, 0, tzinfo=timezone.utc)
    w, clock = _world(monkeypatch, state=HS.SLEEP, at=at, stay=True)
    trace = _tick_until(w, clock,
                        datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc))
    assert {st for _ts, st in trace} == {HS.SLEEP}
    w2, clock2 = _world(monkeypatch, state=HS.WAKING,
                        at=datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc),
                        stay=True)
    trace2 = dict(_tick_until(
        w2, clock2, datetime(2026, 11, 11, 6, 5, tzinfo=timezone.utc)))
    t = lambda h, m, s=0: datetime(2026, 11, 11, h, m, s, tzinfo=timezone.utc)  # noqa: E731
    assert trace2[t(6, 0)] == HS.HOME_DAY
    assert trace2[t(6, 1, 30)] == HS.HOME_DAY
    assert trace2[t(6, 2)] == HS.GUEST


def test_restored_guest_without_stay_exits(monkeypatch):
    """A GUEST restored at boot with the latch off (and the 30-min room gate
    armed, which no longer holds GUEST) exits after the S9 persistence."""
    w, clock = _world(monkeypatch, state=HS.GUEST, at=DAY, stay=False,
                      room_min=45)
    assert w.tick() == HS.GUEST
    clock.advance(300)
    assert w.tick() == HS.HOME_DAY


def test_away_then_return_reenters(monkeypatch):
    """GUEST -> AWAY (everyone out) keeps the latch; after ARRIVING ->
    HOME_DAY the house re-enters GUEST."""
    w, clock = _world(monkeypatch, state=HS.HOME_DAY, at=DAY, stay=True)
    w.sm.force_state(HS.AWAY)
    w.sm._state_since = clock.t - timedelta(hours=1)
    assert w.coord._guest_stay_active is True
    w.sm.force_state(HS.HOME_DAY)
    w.sm._state_since = clock.t - timedelta(hours=1)
    assert w.tick() == HS.GUEST


def test_const_read_at_call_time(monkeypatch):
    """The kill switch is read as a module attribute at call time: flipping
    it on a live coordinator flips the composition on the next tick."""
    w, clock = _world(monkeypatch, state=HS.HOME_DAY, at=DAY, stay=False,
                      room_min=45)
    assert w.tick() == HS.HOME_DAY
    monkeypatch.setattr(H.CONST, "GUEST_NIGHT_STAY_RULE_ENABLED", False)
    clock.advance(30)
    assert w.tick() == HS.GUEST


def test_compose_helper_table(monkeypatch):
    """_compose_guest_gate full table (rule ON) incl. the GUEST sleep-hour
    yield and non-home states."""
    w, _ = _world(monkeypatch, state=HS.HOME_DAY, at=DAY)
    c = w.coord._compose_guest_gate
    for st in (HS.HOME_DAY, HS.HOME_EVENING, HS.HOME_NIGHT):
        for sh in (True, False):
            assert c(st, room=True, stay=False, sleep_hour=sh) is False
            assert c(st, room=False, stay=True, sleep_hour=sh) is True
    assert c(HS.GUEST, room=True, stay=True, sleep_hour=False) is True
    assert c(HS.GUEST, room=True, stay=True, sleep_hour=True) is False
    assert c(HS.GUEST, room=True, stay=False, sleep_hour=False) is False
    for st in (HS.SLEEP, HS.AWAY, HS.WAKING, HS.ARRIVING):
        assert c(st, room=True, stay=True, sleep_hour=False) is False
    monkeypatch.setattr(H.CONST, "GUEST_NIGHT_STAY_RULE_ENABLED", False)
    assert c(HS.HOME_DAY, room=True, stay=False, sleep_hour=False) is True
    assert c(HS.GUEST, room=False, stay=True, sleep_hour=False) is False


def test_config_extremes(monkeypatch):
    """Non-wrapping house sleep window 1 -> 6: GUEST + stay at 00:59 holds,
    at 01:00 the yield proposes HOME_NIGHT."""
    at = datetime(2026, 11, 11, 0, 59, tzinfo=timezone.utc)
    w, clock = _world(monkeypatch, state=HS.GUEST, at=at, stay=True)
    w.coord._inference_engine.sleep_start_hour = 1
    w.coord._inference_engine.sleep_end_hour = 6
    assert w.tick() == HS.GUEST
    assert w.infer_calls[-1][0] is True
    clock.advance(60)
    w.tick()
    assert w.infer_calls[-1][0] is False
    assert w.infer_calls[-1][1] == HS.HOME_NIGHT


# --- INV-STAY-3 / INV-VIS-1 (golden from the base tree) --------------------

def test_kill_switch_byte_identical(monkeypatch):
    """Rule OFF: 200 seeded tuples match the base-tree golden field by field
    (guest_armed, proposal, final, guest_reason, confidence, gate calls)."""
    golden = json.loads(GOLDEN.read_text())["rows"]
    assert len(golden) == 200
    for row in golden:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(H.CONST, "GUEST_NIGHT_STAY_RULE_ENABLED", False)
            got = H.run_tuple(mp, tuple(row["tuple"]))
        assert got == row, row["tuple"]
