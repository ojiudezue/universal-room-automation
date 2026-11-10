"""GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 Phase 1 — lock regime behavioural tests.

Plan: docs/planning/PLANNING_sc_garage_remote_lockout.md rev 5 + Q-G1 (a).
Every test drives REAL production code (security_lock_regime.py and the
SecurityCoordinator wire-ins) and asserts on the recorded
``hass.services.async_call`` stream. No source greps (Bug Class #62). Clock,
timers and state trackers are injected fakes (see _lockout_harness), so no
global HA state is touched and nothing leaks between tests.

Oracles are literal: times are hand-written wall-clock datetimes; boundary
values are hardcoded (never imported from const) so a constant mutation
moves the code, not the test.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from _lockout_harness import TZ, World, load, settle

const = load("const")
R = load("domain_coordinators.security_lock_regime")
sec = load("domain_coordinators.security")

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
COVER_A = "cover.konnected_f0f5bd523b00_garage_door"
COVER_B = "cover.ratgdov25i_dbfe2a_door"
DOOR_LOCK = "lock.doorlock_kwikset_zwave_frontentry"
EZ = "person.ezinne"
OJI = "person.oji_udezue"
KIOSK = "person.wall_kiosk"
EZ_DIST = "sensor.madronehaos_ezinne_distance"

NIGHT = datetime(2026, 11, 7, 23, 0, 0, tzinfo=TZ)


def options(**over):
    opts = {
        "security_garage_lockout_enabled": True,
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_lock_entities": [DOOR_LOCK],
        "security_garage_entities": [COVER_A, COVER_B],
        "security_lockout_excluded_persons": [KIOSK],
        "security_lockout_distance_sensors": [EZ_DIST],
        "security_coordinator_enabled": True,
        "sleep_start_hour": 22,
        "sleep_end_hour": 6,
    }
    opts.update(over)
    return opts


class Rig:
    """One house: world + SecurityCoordinator + its lock regime."""

    def __init__(self, world: World, sc, regime, mgr) -> None:
        self.w = world
        self.sc = sc
        self.regime = regime
        self.mgr = mgr

    async def edge(self, new: str) -> None:
        old = self.mgr.house_state
        self.mgr.house_state = new
        # Through the REAL SC bridge (wire-in anchor).
        self.sc._on_house_state_changed_signal(
            {"old_state": old, "new_state": new, "trigger": "t", "confidence": 1.0}
        )
        await settle()

    async def person(self, pid: str, state: str) -> None:
        self.w.set_state(pid, state)
        await settle()

    def locks(self) -> list[str]:
        return self.w.locks_called("lock")

    def unlocks(self) -> list[str]:
        return self.w.locks_called("unlock")


async def make_rig(
    *,
    start: datetime = NIGHT,
    house: str = "home_night",
    opts: dict | None = None,
    lockouts: str = "unlocked",
    persons: dict | None = None,
    past_boot: bool = True,
    store=None,
    seed_hook=None,
) -> Rig:
    w = World(start, opts if opts is not None else options(),
              entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    hass = w.hass
    mgr = SimpleNamespace(house_state=house)
    hass.data[const.DOMAIN] = {"coordinator_manager": mgr}
    for ent in (LOCK_A, LOCK_B):
        w.seed(ent, lockouts)
    w.seed(DOOR_LOCK, "locked")
    for cov in (COVER_A, COVER_B):
        w.seed(cov, "closed", {"device_class": "garage"})
    for pid, st in (persons or {EZ: "not_home", OJI: "home", KIOSK: "unknown"}).items():
        # Review A H1: HA's person restore writes a FRESH State, so every
        # person's last_changed is the boot time (components/person
        # __init__.py:464-468). Never an older value.
        w.seed(pid, st, last_changed=start)
    w.seed(EZ_DIST, "30000", {"unit_of_measurement": "ft"})
    if seed_hook is not None:
        seed_hook(w)
    sc = sec.SecurityCoordinator(
        hass, lock_entities=[DOOR_LOCK], garage_entities=[COVER_A, COVER_B]
    )
    regime = R.LockRegimeController(
        hass, sc,
        now=w.clock, call_later=w.call_later, track_state=w.track_state,
        track_added_domain=w.track_added, track_removed_domain=w.track_removed,
        store=store,
    )
    sc._lock_regime = regime
    await regime.async_setup()
    rig = Rig(w, sc, regime, mgr)
    if past_boot:
        await w.advance(601)
        w.calls.clear()
    return rig


# ============================================================================
# LOCK-BOOT-RECHECK-ENGAGE-1 — the boot recheck re-asks "locked now?"
# ============================================================================

BOOT_0200 = datetime(2026, 11, 8, 2, 0, tzinfo=TZ)


@pytest.mark.asyncio
async def test_boot_recheck_engages_sleep_with_lockouts_unlocked():
    rig = await make_rig(start=BOOT_0200, house="sleep", past_boot=False)
    await rig.w.advance(119)
    assert rig.locks() == []
    await rig.w.advance(2)  # 120 s recheck fires
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "boot_recheck"
    assert rig.regime.reason == "sleep"
    # Backstop scheduled exactly as the sleep edge does: 07:00 releases.
    await rig.w.advance((datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_recheck_releases_boot_unknown_lock_in_awake_house():
    rig = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig.regime.reason == "boot_unknown"
    await rig.w.advance(119)
    assert rig.unlocks() == []
    await rig.w.advance(2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["action"] == "release"
    assert rig.regime.last_action["trigger"] == "boot_recheck"
    assert rig.regime.reason == "none"
    assert rig.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_boot_recheck_releases_boot_unknown_lock_when_arriving():
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False)
    rig.mgr.house_state = "arriving"  # restore lands late, no signal
    await rig.w.advance(121)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_recheck_sleep_already_locked_no_command():
    rig = await make_rig(start=BOOT_0200, house="sleep", lockouts="locked",
                         past_boot=False)
    await rig.w.advance(121)
    assert rig.w.calls == []
    assert rig.regime.last_action["action"] == "boot_recheck"
    assert rig.regime.last_action["decision"] == "already_locked"


@pytest.mark.asyncio
async def test_boot_recheck_awake_and_unlocked_no_command():
    rig = await make_rig(start=datetime(2026, 11, 8, 9, 30, tzinfo=TZ), house="home_day",
                         past_boot=False)
    await rig.w.advance(121)
    assert rig.w.calls == []
    assert rig.regime.last_action["action"] == "boot_recheck"
    assert rig.regime.last_action["decision"] == "no_change"


@pytest.mark.asyncio
@pytest.mark.parametrize("house", [None, "unknown", "unavailable"])
async def test_boot_recheck_house_unknown_does_nothing(house):
    rig = await make_rig(start=BOOT_0200, house="sleep", past_boot=False)
    rig.mgr.house_state = house
    await rig.w.advance(121)
    assert rig.w.calls == []
    assert rig.regime.last_action.get("action") != "boot_recheck"


@pytest.mark.asyncio
async def test_boot_recheck_house_unknown_with_boot_unknown_lock_no_release():
    rig = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    rig.mgr.house_state = "unavailable"
    await rig.w.advance(121)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_boot_recheck_kill_switch_off_does_nothing():
    rig = await make_rig(start=BOOT_0200, house="sleep", past_boot=False,
                         opts=options(security_garage_lockout_enabled=False))
    await rig.w.advance(121)
    assert rig.w.calls == []
    assert rig.regime.last_action == {}
    assert rig.regime.reason == "none"
    assert rig.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_boot_recheck_kill_switch_off_boot_unknown_lock_not_released():
    rig = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                         past_boot=False,
                         opts=options(security_garage_lockout_enabled=False,
                                      security_lockout_engage_on_guest_sleep=False))
    await rig.w.advance(121)
    assert rig.w.calls == []


@pytest.mark.asyncio
async def test_boot_recheck_guest_yield_hold_respected():
    """INV-LOCK-1: a lock found at boot in a home_night sleep window with the
    guest toggle ON may be the guest-night lock after the yield: held, then
    released by the next home_day edge like any guest-night lock."""
    rig = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                         past_boot=False)
    await rig.w.advance(121)
    assert rig.unlocks() == []
    assert rig.regime.reason == "guest_night"
    assert rig.regime.last_action["decision"] == "guest_yield_hold"
    await rig.edge("home_day")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_recheck_guest_in_window_engages_guest_night():
    rig = await make_rig(start=BOOT_0200, house="guest", past_boot=False)
    await rig.w.advance(121)
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "guest_night"


@pytest.mark.asyncio
async def test_boot_recheck_arrival_in_boot_window_suppresses_engage():
    rig = await make_rig(start=BOOT_0200, house="sleep", past_boot=False)
    await rig.w.advance(60)
    await rig.person(EZ, "home")  # not_home -> home: a counted arrival
    await rig.w.advance(61)  # recheck at 120 s
    assert rig.locks() == []
    assert rig.regime.last_action["decision"] == "arrival_suppressed"


@pytest.mark.asyncio
async def test_boot_recheck_rebuilt_sleep_reason_not_released_by_recheck():
    """Release at the recheck is only for a BOOT_UNKNOWN lock; a lock rebuilt
    as SLEEP is left to the real edges / backstop."""
    rig = await make_rig(start=BOOT_0200, house="sleep", lockouts="locked",
                         past_boot=False)
    rig.mgr.house_state = "home_night"  # silent change, no edge
    await rig.w.advance(121)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_boot_recheck_boot_unknown_but_already_unlocked_no_release():
    rig = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    rig.w.set_state(LOCK_A, "unlocked")
    rig.w.set_state(LOCK_B, "unlocked")
    await rig.w.advance(121)
    assert rig.w.calls == []
    assert rig.regime.last_action["decision"] == "no_change"


@pytest.mark.asyncio
async def test_boot_recheck_sleep_at_0900_unlocked_no_engage():
    """Review A HIGH: SLEEP still read at 09:00 (no wake edge), past the
    07:00 backstop: no catch-up lock (would hold all day)."""
    rig = await make_rig(start=datetime(2026, 11, 8, 9, 0, tzinfo=TZ), house="sleep",
                         past_boot=False)
    await rig.w.advance(121)
    assert rig.locks() == []
    assert rig.regime.last_action["decision"] == "past_backstop_no_catchup"
    assert rig.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_boot_recheck_sleep_at_0900_locked_stays_unlocked_after_backstop():
    rig = await make_rig(start=datetime(2026, 11, 8, 9, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False)
    await rig.w.advance(0)  # immediate backstop releases
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(121)
    assert rig.locks() == []
    assert rig.regime.last_action["decision"] == "past_backstop_no_catchup"


@pytest.mark.asyncio
async def test_boot_recheck_sleep_at_0630_after_window_no_engage():
    """Sleep window 22-06: 06:30 is outside it (backstop 07:00 not yet due)."""
    rig = await make_rig(start=datetime(2026, 11, 8, 6, 30, tzinfo=TZ), house="sleep",
                         past_boot=False)
    await rig.w.advance(121)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_boot_recheck_vacation_unlocked_no_catchup():
    rig = await make_rig(start=BOOT_0200, house="vacation", past_boot=False)
    await rig.w.advance(121)
    assert rig.locks() == []
    assert rig.regime.last_action["decision"] == "vacation_no_catchup"


# ============================================================================
# D2 — engage / release on house state (INV-4, INV-5, INV-6)
# ============================================================================


@pytest.mark.asyncio
async def test_sleep_engages_both():
    rig = await make_rig()
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "sleep"


@pytest.mark.asyncio
async def test_vacation_engages_both():
    rig = await make_rig(house="away")
    await rig.edge("vacation")
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_away_never_engages():
    rig = await make_rig()
    await rig.edge("away")
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_regime_runs_with_auto_follow_off():
    """Feed sits before the auto-follow return (security.py bridge)."""
    rig = await make_rig()
    assert rig.sc._auto_follow_house_state is False
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_no_engage_when_disabled():
    rig = await make_rig(opts=options(security_garage_lockout_enabled=False))
    await rig.edge("sleep")
    assert rig.w.calls == []


@pytest.mark.asyncio
async def test_lockout_switch_reads_options_absent_is_off():
    opts = options()
    del opts["security_garage_lockout_enabled"]
    rig = await make_rig(opts=opts)
    assert rig.regime.kill_switch_on() is False
    await rig.edge("sleep")
    assert rig.w.calls == []


@pytest.mark.asyncio
async def test_observation_mode_records_would_engage():
    rig = await make_rig()
    rig.sc.observation_mode = True
    await rig.edge("sleep")
    assert rig.locks() == []
    assert rig.regime.last_action["action"] == "would_engage"


@pytest.mark.asyncio
async def test_wake_releases_sleep_engaged():
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("waking")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_override_sleep_to_home_releases():
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("home_day")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_arriving_releases():
    rig = await make_rig(house="away")
    await rig.edge("vacation")
    await rig.edge("arriving")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_sleep_to_away_keeps_reason_backstop_releases():
    rig = await make_rig()
    await rig.edge("sleep")  # 23:10:01
    await rig.edge("away")
    assert rig.regime.reason == "sleep"
    assert rig.unlocks() == []
    # 07:00 = sleep_end 06 + 60 min backstop.
    await rig.w.advance((datetime(2026, 11, 8, 6, 59, 59, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == []
    await rig.w.advance(2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_backstop_releases_stuck_sleep():
    rig = await make_rig()
    await rig.edge("sleep")
    target = datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ)
    await rig.w.advance((target - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_backstop_reads_cm_sleep_end_hour():
    """sleep_end_hour = 5, backstop 0 -> release at exactly 05:00."""
    rig = await make_rig(opts=options(sleep_end_hour=5, garage_lockout_morning_backstop_min=0))
    await rig.edge("sleep")
    await rig.w.advance((datetime(2026, 11, 8, 4, 59, 59, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == []
    await rig.w.advance(2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_backstop_default_when_cm_unset():
    """CM keys unset -> const defaults (end 06) + 60 min -> 07:00."""
    opts = options()
    del opts["sleep_end_hour"]
    del opts["sleep_start_hour"]
    rig = await make_rig(opts=opts, start=datetime(2026, 11, 7, 23, 30, tzinfo=TZ))
    await rig.edge("sleep")
    await rig.w.advance((datetime(2026, 11, 8, 6, 59, 59, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == []
    await rig.w.advance(2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_vacation_not_released_by_backstop():
    rig = await make_rig(house="away")
    await rig.edge("vacation")
    await rig.w.advance(36 * 3600)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_vacation_not_released_by_wake():
    rig = await make_rig(house="away")
    await rig.edge("vacation")
    await rig.edge("waking")
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_manual_unlock_not_reasserted():
    """Edge-only: an operator unlock mid-SLEEP is not re-locked by any timer."""
    rig = await make_rig()
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unlocked")
    rig.w.calls.clear()
    await rig.w.advance(3 * 3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_kill_switch_on_mid_sleep_no_engage():
    rig = await make_rig(opts=options(security_garage_lockout_enabled=False), house="sleep")
    await rig.edge("sleep")
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = True
    rig.regime.on_kill_switch_changed(True)
    await rig.w.advance(1800)
    assert rig.locks() == []


# ---- Q-G1 option (a): GUEST in sleep hours --------------------------------


@pytest.mark.asyncio
async def test_guest_in_sleep_window_engages_when_toggle_on():
    rig = await make_rig()  # 23:10 local, window 22-06, toggle default ON
    await rig.edge("guest")
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "guest_night"


@pytest.mark.asyncio
async def test_guest_outside_sleep_window_inert():
    rig = await make_rig(start=datetime(2026, 11, 7, 19, 0, tzinfo=TZ))
    await rig.edge("guest")  # 19:10 local, outside 22-06
    assert rig.locks() == []
    # Edge site itself is inert (not merely dropped later by the predicate).
    assert rig.regime.reason == "none"
    assert rig.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_guest_night_toggle_off_inert():
    rig = await make_rig(opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig.edge("guest")
    assert rig.locks() == []
    assert rig.regime.reason == "none"
    assert rig.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_guest_night_does_not_engage_when_toggle_off():
    """Plan's GUEST-inert baseline test name, under toggle OFF."""
    rig = await make_rig(opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig.edge("guest")
    await rig.w.advance(4 * 3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_guest_already_set_at_sleep_start_engages_by_clock():
    rig = await make_rig(start=datetime(2026, 11, 7, 20, 0, tzinfo=TZ))
    await rig.edge("guest")  # 20:10, outside the window: inert
    assert rig.locks() == []
    await rig.w.advance((datetime(2026, 11, 7, 21, 59, 59, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.locks() == []
    await rig.w.advance(2)  # 22:00 clock
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "guest_clock"


@pytest.mark.asyncio
async def test_guest_clock_does_nothing_if_house_not_guest():
    rig = await make_rig(start=datetime(2026, 11, 7, 20, 0, tzinfo=TZ), house="home_evening")
    await rig.w.advance(2.5 * 3600)
    assert rig.locks() == []
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_guest_exit_to_home_releases_guest_night():
    """A GUEST -> HOME_DAY / HOME_EVENING exit releases as before. (GUEST ->
    HOME_NIGHT inside the window is now HELD: INV-LOCK-1 tests below.)"""
    for home in ("home_day", "home_evening"):
        rig = await make_rig()
        await rig.edge("guest")
        await rig.edge(home)
        assert rig.unlocks() == [LOCK_A, LOCK_B], home
        assert rig.regime.reason == "none"


# ---- INV-LOCK-1 (GUEST-MODE-SPLIT rev 5, build review B-M1) ---------------
# Plan PLANNING_guest_mode_split_2026_11.md §2.5 / §3.3 / D3. The presence
# night yield takes GUEST -> HOME_NIGHT ~5 min after the 22:00 guest-night
# clock locked; the lock must be written ONCE at the clock and not unlocked
# by the yield. Times are hand-written wall clock (window 22 -> 06).

GUEST_EVE = datetime(2026, 11, 7, 21, 40, 0, tzinfo=TZ)   # +601 s boot = 21:50:01


async def _to(rig, hh, mm, day=7):
    target = datetime(2026, 11, day, hh, mm, 0, tzinfo=TZ)
    await rig.w.advance((target - rig.w.now).total_seconds())


@pytest.mark.asyncio
async def test_lock_once_at_guest_clock_no_unlock_on_yield():
    rig = await make_rig(start=GUEST_EVE, house="guest")
    await _to(rig, 21, 59)
    assert rig.locks() == []
    await _to(rig, 22, 0)                         # guest-night clock
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "guest_night"
    await _to(rig, 22, 5)
    await rig.edge("home_night")                  # the night yield
    assert rig.unlocks() == []
    assert rig.regime.reason == "guest_night"
    assert rig.regime.last_action["action"] == "guest_yield_hold"
    assert rig.regime.last_action["trigger"] == "house_state:home_night"
    await _to(rig, 22, 7)
    await rig.edge("sleep")
    assert rig.regime.reason == "sleep"
    assert rig.locks() == [LOCK_A, LOCK_B]        # no second lock write
    await _to(rig, 6, 0, day=8)
    await rig.edge("waking")
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.unlocks() == [LOCK_A, LOCK_B]      # one unlock, in the morning
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_lock_held_if_home_night_until_morning():
    """GUEST -> HOME_NIGHT at 22:05 and the house never reaches SLEEP: still
    held overnight, released at HOME_DAY (06:00, before the 07:00 backstop)."""
    rig = await make_rig(start=GUEST_EVE, house="guest")
    await _to(rig, 22, 0)
    await _to(rig, 22, 5)
    await rig.edge("home_night")
    await _to(rig, 5, 59, day=8)
    assert rig.unlocks() == []
    assert rig.regime.reason == "guest_night"
    await _to(rig, 6, 0, day=8)
    await rig.edge("home_day")
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_lock_toggle_off_unchanged():
    """Toggle off: no 22:00 engage, the yield edge is inert, SLEEP engages
    once (pre-change behaviour)."""
    rig = await make_rig(start=GUEST_EVE, house="guest",
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    await _to(rig, 22, 0)
    assert rig.locks() == []
    await _to(rig, 22, 5)
    await rig.edge("home_night")
    assert rig.w.calls == []
    assert rig.regime.last_action is None or \
        rig.regime.last_action.get("action") != "guest_yield_hold"
    await _to(rig, 22, 7)
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_manual_sleep_to_home_night_in_window_releases():
    """Review C M3: reason SLEEP (not guest_night) + an override to
    HOME_NIGHT inside the sleep window releases as before; the yield hold
    is for guest_night only."""
    rig = await make_rig()                        # 23:10, in window
    await rig.edge("sleep")
    assert rig.regime.reason == "sleep"
    await rig.edge("home_night")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_guest_night_home_night_outside_window_releases():
    """HOME_NIGHT with reason guest_night OUTSIDE the sleep window (cannot
    come from inference; forced) releases as before."""
    rig = await make_rig()
    await rig.edge("guest")                       # 23:10, engages guest_night
    await _to(rig, 6, 30, day=8)                  # past 06:00, before backstop
    assert rig.regime.reason == "guest_night"
    await rig.edge("home_night")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_guest_clears_then_sleep_engages():
    rig = await make_rig(start=datetime(2026, 11, 7, 19, 0, tzinfo=TZ))
    await rig.edge("guest")
    await rig.edge("home_night")
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_guest_night_backstop_releases():
    rig = await make_rig()
    await rig.edge("guest")
    await rig.w.advance((datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]


# ============================================================================
# Boot / restart (H1, M1, INV-4, INV-5)
# ============================================================================


@pytest.mark.asyncio
async def test_boot_never_engages_before_the_recheck():
    """Boot itself never engages (M1); the 120 s recheck is the one catch-up
    (LOCK-BOOT-RECHECK-ENGAGE-1, anchored below)."""
    rig = await make_rig(house="sleep", past_boot=False)
    await rig.w.advance(119)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_boot_window_sleep_edge_rebuilds_reason_only():
    rig = await make_rig(past_boot=False)
    await rig.w.advance(119)
    await rig.edge("sleep")
    assert rig.locks() == []
    assert rig.regime.reason == "sleep"


@pytest.mark.asyncio
async def test_sleep_edge_after_boot_window_engages():
    rig = await make_rig(past_boot=False)
    await rig.w.advance(121)
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_settle_override_vacation_does_not_engage():
    """VACATION, lockout manually unlocked, restart, boot-settle replay."""
    rig = await make_rig(house="away", past_boot=False)
    await rig.w.advance(45)
    await rig.edge("vacation")  # trigger override_set, inside the window
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_restart_mid_sleep_backstop_still_releases():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False)
    assert rig.regime.reason == "sleep"
    await rig.w.advance((datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_restart_mid_sleep_wake_releases():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked")
    await rig.edge("waking")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_restart_vacation_restored_holds_at_0700():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="vacation",
                         lockouts="locked", past_boot=False)
    assert rig.regime.reason == "vacation"
    await rig.w.advance(8 * 3600)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_restart_unknown_state_treated_as_sleep():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="home_night",
                         lockouts="locked", past_boot=False)
    assert rig.regime.reason == "boot_unknown"
    await rig.edge("waking")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_restart_late_house_state_restore_upgrades_reason():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="away",
                         lockouts="locked", past_boot=False)
    assert rig.regime.reason == "boot_unknown"
    rig.mgr.house_state = "vacation"  # restore lands after SC setup, no signal
    await rig.w.advance(121)
    assert rig.regime.reason == "vacation"
    await rig.w.advance(8 * 3600)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_restart_daytime_with_stale_night_lock_releases_now():
    rig = await make_rig(start=datetime(2026, 11, 8, 9, 30, tzinfo=TZ), house="home_day",
                         lockouts="locked", past_boot=False)
    await settle()
    await rig.w.advance(0)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_restart_resident_restored_home_stays_engaged():
    """Review A H1: engaged for SLEEP, HA restarts at 02:00, residents
    restore `home` with last_changed = boot time -> stays engaged, reason
    sleep, released only at the morning backstop."""
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False,
                         persons={EZ: "home", OJI: "home", KIOSK: "unknown"})
    await rig.w.advance(700)
    assert rig.unlocks() == []
    assert rig.regime.reason == "sleep"
    await rig.w.advance((datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_early_sleep_override_before_sleep_start_holds_until_morning():
    """Review A M1: SLEEP override at 22:30 with sleep_start 23."""
    rig = await make_rig(start=datetime(2026, 11, 7, 22, 20, tzinfo=TZ),
                         opts=options(sleep_start_hour=23))
    await rig.edge("sleep")  # 22:30:01
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.w.advance(60)  # 22:31
    assert rig.unlocks() == []
    await rig.w.advance((datetime(2026, 11, 8, 6, 59, 59, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == []
    await rig.w.advance(2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_backstop_delay_dst_fall_back():
    """Review A L3: 2026-11-01 02:00 CDT -> 01:00 CST (America/Chicago).
    SLEEP engage 23:00 CDT Oct 31 (04:00Z) -> 07:00 CST Nov 1 (13:00Z) is
    8 wall hours but 9 real hours (32400 s); a wall-clock subtraction of
    aware datetimes gives 28800."""
    from zoneinfo import ZoneInfo

    chicago = ZoneInfo("America/Chicago")
    rig = await make_rig()
    rig.w.now = datetime(2026, 10, 31, 23, 0, tzinfo=chicago)
    cfg = rig.regime._cfg()
    assert rig.regime._backstop_delay_s(cfg) == 32400.0
    # Same-night branch: 00:30 CDT Nov 1 (05:30Z) -> 07:00 CST (13:00Z) =
    # 7.5 real hours (27000 s); wall subtraction gives 23400.
    rig.w.now = datetime(2026, 11, 1, 0, 30, tzinfo=chicago)
    assert rig.regime._backstop_delay_s(cfg) == 27000.0
    # Spring forward: 2027-03-14 02:00 CST -> 03:00 CDT. 23:00 Mar 13 ->
    # 07:00 CDT is 7 real hours.
    rig.w.now = datetime(2027, 3, 13, 23, 0, tzinfo=chicago)
    assert rig.regime._backstop_delay_s(cfg) == 25200.0
    # Guest clock across fall back: 23:00 Oct 31 -> 22:00 Nov 1 is 23 wall
    # hours but 24 real hours.
    rig.w.now = datetime(2026, 10, 31, 23, 0, tzinfo=chicago)
    assert rig.regime._seconds_until_hour(22) == 86400.0


@pytest.mark.asyncio
async def test_kill_switch_boot_off_no_write():
    rig = await make_rig(opts=options(security_garage_lockout_enabled=False),
                         lockouts="locked", house="sleep", past_boot=False)
    await rig.w.advance(9 * 3600)
    assert rig.w.calls == []


# ============================================================================
# D3 — arrival release (P1, P2, P5) + re-engage (INV-2, INV-3)
# ============================================================================


@pytest.mark.asyncio
async def test_release_while_disarmed():
    rig = await make_rig()
    assert rig.sc.armed_state == sec.ArmedState.DISARMED
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_release_under_sc_observation():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.sc.observation_mode = True
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_manually_locked_lockout_released_by_arrival():
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_arrival_from_named_zone_releases():
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "Work")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_arrival_from_unavailable_releases():
    """Real not_home held > 15 min, then unavailable, then home."""
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(16 * 60)
    await rig.person(EZ, "unavailable")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_unavailable_blip_after_real_away_releases():
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(15 * 60 + 1)
    await rig.person(EZ, "unknown")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_unknown_blip_while_home_no_release():
    rig = await make_rig(lockouts="locked")
    await rig.person(OJI, "Work")
    await rig.person(OJI, "home")  # real transition seen: blip rule applies
    await rig.w.advance(3600)
    rig.w.set_state(LOCK_A, "locked")  # re-locked (e.g. manually)
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    await rig.person(OJI, "unknown")
    await rig.person(OJI, "home")
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_blip_rule_applies_after_real_transition_seen():
    """not_home for 14 min only (< 15) then a blip: no release."""
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(14 * 60)
    await rig.person(EZ, "unknown")
    await rig.person(EZ, "home")
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_restart_restore_then_unknown_then_home_releases():
    """M-2: restore not_home, unknown at start, home at T+40 s -> unlock."""
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False,
                         persons={OJI: "home", KIOSK: "unknown"})
    rig.w.set_state(EZ, "not_home")  # old_state None: restore write
    await rig.w.advance(10)
    await rig.person(EZ, "unknown")
    await rig.w.advance(30)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


class _PersistedEz:
    """Resident store that already knows Ezinne, so her restore write (old
    state None) reaches the regime's by-id listener, as in HA after a
    restart (subscription by id precedes the entity)."""

    async def async_load(self):
        return {"residents": [EZ]}

    def async_delay_save(self, fn, delay):
        pass


@pytest.mark.asyncio
async def test_restored_state_counts_after_boot_window():
    """M-2 (ii): no real transition since setup -> blip edge still counts.

    Restored `not_home` only 700 s old: the blip rule (>= 15 min real away)
    would reject this edge; only the restored flag admits it."""
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False,
                         persons={OJI: "home", KIOSK: "unknown"}, store=_PersistedEz())
    rig.w.set_state(EZ, "not_home")  # restore
    assert rig.regime._last_real[EZ][2] is True
    await rig.w.advance(700)  # beyond the 600 s boot arrival window
    rig.w.calls.clear()
    await rig.person(EZ, "unknown")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_window_blip_from_restored_home_releases():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False,
                         persons={OJI: "home", KIOSK: "unknown"})
    rig.w.set_state(EZ, "home")  # restored home
    await rig.person(EZ, "unknown")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_old_state_none_not_an_arrival():
    rig = await make_rig(lockouts="locked", persons={OJI: "home", KIOSK: "unknown"})
    rig.w.set_state(EZ, "home")  # entity added (old None)
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_excluded_person_never_releases():
    rig = await make_rig(lockouts="locked")
    await rig.person(KIOSK, "not_home")
    await rig.person(KIOSK, "home")
    rig.sc._handle_person_arriving_signal({"person_entity": KIOSK})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_arriving_signal_branch_above_observation_return():
    rig = await make_rig(lockouts="locked")
    rig.sc.observation_mode = True
    rig.sc._handle_person_arriving_signal({"person_entity": EZ, "source": "ble"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_interior_camera_face_for_resident_home_does_not_release():
    """Review A M2: Oji home all night (real transition seen), an interior
    zone camera recognises him at 02:00 -> SIGNAL_PERSON_ARRIVING
    source camera_face -> no release."""
    rig = await make_rig(lockouts="locked")
    await rig.person(OJI, "Work")
    await rig.person(OJI, "home")
    await rig.w.advance(3 * 3600)
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    rig.sc._handle_person_arriving_signal({"person_entity": OJI, "source": "camera_face"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_camera_face_after_real_absence_without_arrival_edge_does_not_release():
    """LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 (was ..._releases before
    2026-11-08): really away, but a face with no independent arrival edge
    (the 10-24 Jaya-labelled-as-Oji shape) no longer unlocks. The
    corroborated variants live in test_lock_face_arrival_corroboration.py."""
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(16 * 60)
    rig.sc._handle_person_arriving_signal({"person_entity": EZ, "source": "camera_face"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_arriving_signal_short_absence_does_not_release():
    """< 15 min real away: not an arrival (same H3a rule as P1 blips)."""
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(14 * 60)
    rig.sc._handle_person_arriving_signal({"person_entity": EZ, "source": "ble"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_excluded_persons_proximity_sensor_does_not_release():
    """Review A L1: an excluded person's distance sensor maps to that person
    (live map) and is then filtered out, instead of releasing as None."""
    kiosk_dist = "sensor.madronehaos_wall_kiosk_distance"
    rig = await make_rig(lockouts="locked", opts=options(
        security_lockout_distance_sensors=[EZ_DIST, kiosk_dist]))
    rig.w.set_state(kiosk_dist, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(kiosk_dist, "100", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_unexcluded_resident_proximity_enters_releasing_set():
    """Review A L1: a person excluded at setup, un-excluded live, still maps
    -> enters releasing_set, so the re-engage waits for them (INV-3)."""
    kiosk_dist = "sensor.madronehaos_wall_kiosk_distance"
    rig = await make_rig(opts=options(
        security_lockout_distance_sensors=[EZ_DIST, kiosk_dist]))
    await rig.edge("sleep")
    rig.w.cm_entry.options["security_lockout_excluded_persons"] = []
    rig.w.set_state(kiosk_dist, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(kiosk_dist, "2600", {"unit_of_measurement": "ft"})  # ~792 m
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert KIOSK in rig.regime.releasing_set
    rig.w.calls.clear()
    await rig.w.advance(901)
    assert rig.locks() == []  # kiosk still en route


@pytest.mark.asyncio
async def test_engage_inflight_cleared_after_lock_landed():
    """Review A L2: after a lock lands, a later manual unlock + release must
    not send a redundant unlock to an unlocked lockout."""
    rig = await make_rig()
    await rig.edge("sleep")  # locks land (apply_service_state)
    rig.w.set_state(LOCK_A, "unlocked")  # operator unlocks by hand
    rig.w.calls.clear()
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_B]


@pytest.mark.asyncio
async def test_engage_inflight_expires_after_readback_window():
    """A lock command the opener never applied stops counting as in flight."""
    rig = await make_rig()
    rig.w.apply_service_state = False
    await rig.edge("sleep")  # lock issued, state stays unlocked
    await rig.w.advance(21)
    rig.w.calls.clear()
    await rig.person(EZ, "home")
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_arriving_signal_releases_when_sc_handler_disabled_flag():
    """P2 sits above `if not self._enabled` too."""
    rig = await make_rig(lockouts="locked")
    rig.sc._enabled = False
    rig.sc._handle_person_arriving_signal({"person_entity": EZ})
    await settle()
    # SC itself disabled -> regime refuses non-forced writes (sc_alive False).
    assert rig.unlocks() == []
    rig.sc._enabled = True
    rig.sc._handle_person_arriving_signal({"person_entity": EZ})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_resident_listener_survives_empty_person_snapshot():
    """No person.* at setup: a person added later still releases."""
    rig = await make_rig(lockouts="locked", persons={})
    rig.w.set_state(EZ, "not_home")  # added
    await settle()
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_person_added_at_runtime_releases_without_reload():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state("person.new", "not_home")
    await settle()
    await rig.person("person.new", "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_person_removed_at_runtime_stops_release():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ, None)  # removed
    await settle()
    # A stray listener (if not cancelled) would see these.
    rig.w.hass.states._s[EZ] = None  # noqa: SLF001
    rig.w.hass.states._s.pop(EZ)
    for rec in rig.w.listeners:
        if rec["active"] and EZ in rec["ids"]:
            raise AssertionError("listener for a removed person still active")
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_resident_set_persisted_and_restored():
    class Store:
        def __init__(self, data):
            self.data = data
            self.saved = None

        async def async_load(self):
            return self.data

        def async_delay_save(self, fn, delay):
            self.saved = fn()

    store = Store({"residents": ["person.ziri"]})
    rig = await make_rig(lockouts="locked", store=store)
    assert "person.ziri" in store.saved["residents"]
    assert KIOSK not in store.saved["residents"]
    # person.ziri has no state yet but already has a listener.
    rig.w.seed("person.ziri", "not_home")
    rig.w.set_state("person.ziri", "Work")
    await rig.person("person.ziri", "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_persisted_resident_not_yet_loaded_still_subscribed():
    class Store:
        async def async_load(self):
            return {"residents": ["person.jaya"]}

        def async_delay_save(self, fn, delay):
            pass

    rig = await make_rig(lockouts="locked", store=Store())
    assert any("person.jaya" in rec["ids"] for rec in rig.w.listeners if rec["active"])


@pytest.mark.asyncio
async def test_missing_resident_warns():
    class Store:
        async def async_load(self):
            return {"residents": ["person.jaya"]}

        def async_delay_save(self, fn, delay):
            pass

    rig = await make_rig(lockouts="locked", store=Store())
    assert rig.regime.missing_residents == ["person.jaya"]


@pytest.mark.asyncio
async def test_resident_store_load_failure_still_subscribes():
    class Store:
        async def async_load(self):
            raise ValueError("corrupt")

        def async_delay_save(self, fn, delay):
            pass

    rig = await make_rig(lockouts="locked", store=Store())
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


# ---- P5 proximity -----------------------------------------------------------


@pytest.mark.asyncio
async def test_proximity_crossing_releases():
    """R = 1500 m; 6000 ft -> 3000 ft (914 m). A no-conversion build fails."""
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == f"proximity:{EZ_DIST}"


@pytest.mark.asyncio
async def test_proximity_survives_unit_conversion_module_swap(monkeypatch):
    """Suite polluter (test_zone_safety_alert._install_aggregation_mocks)
    replaces homeassistant.util.unit_conversion with a TemperatureConverter-
    only stub at run time. The regime binds DistanceConverter at import."""
    import sys
    import types

    stub = types.ModuleType("homeassistant.util.unit_conversion")
    monkeypatch.setitem(sys.modules, "homeassistant.util.unit_conversion", stub)
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_unexcluded_person_releases_without_reload():
    """Excluded-persons edits apply live (key is reload-suppressed)."""
    rig = await make_rig(lockouts="locked")
    await rig.person(KIOSK, "not_home")
    await rig.person(KIOSK, "home")
    assert rig.unlocks() == []
    rig.w.cm_entry.options["security_lockout_excluded_persons"] = []
    await rig.person(KIOSK, "not_home")
    await rig.person(KIOSK, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_distance_sensor_unit_ft_converted():
    """6000 ft (1829 m) -> 5000 ft (1524 m): both outside 1500 m."""
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "5000", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_proximity_unit_km_converted():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "2", {"unit_of_measurement": "km"})
    rig.w.set_state(EZ_DIST, "1.4", {"unit_of_measurement": "km"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_proximity_first_reading_after_unknown_not_a_crossing():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "unknown", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "100", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_proximity_unknown_no_signal():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "unavailable", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_proximity_unknown_unit_no_signal():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "furlong"})
    rig.w.set_state(EZ_DIST, "1", {"unit_of_measurement": "furlong"})
    await settle()
    assert rig.unlocks() == []
    assert R.distance_to_metres("1", "furlong") is None
    assert round(R.distance_to_metres("3000", "ft"), 1) == 914.4


@pytest.mark.asyncio
async def test_proximity_radius_zero_disables_p5():
    rig = await make_rig(lockouts="locked", opts=options(garage_lockout_approach_radius_m=0))
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "100", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []


# ---- multi-trigger + re-engage ------------------------------------------------


@pytest.mark.asyncio
async def test_multi_trigger_arrival_single_unlock():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.w.apply_service_state = False  # opener slow: still reads locked
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})  # P5
    rig.sc._handle_person_arriving_signal({"person_entity": EZ})  # P2
    rig.w.set_state(EZ, "home")  # P1
    await settle()
    assert sorted(rig.unlocks()) == [LOCK_A, LOCK_B]
    reengages = [t for t in rig.w.live_timers() if t["cb"] == rig.regime._on_reengage_timer]
    assert len(reengages) == 1


@pytest.mark.asyncio
async def test_reengage_after_settled_arrival():
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    rig.w.calls.clear()
    await rig.w.advance(899)
    assert rig.locks() == []
    await rig.w.advance(2)
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_reengage_superseded_by_second_arrival():
    rig = await make_rig(persons={EZ: "not_home", OJI: "not_home", KIOSK: "unknown"})
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    await rig.w.advance(600)
    await rig.person(OJI, "home")
    rig.w.calls.clear()
    await rig.w.advance(400)  # 1000 s after the first: first timer superseded
    assert rig.locks() == []
    await rig.w.advance(510)
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_reengage_waits_for_proximity_released_resident():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})  # 914 m
    await settle()
    rig.w.calls.clear()
    rig.w.set_state(EZ_DIST, "2624", {"unit_of_measurement": "ft"})  # ~800 m
    await rig.w.advance(901)
    assert rig.locks() == []  # still en route
    await rig.person(EZ, "home")
    rig.w.calls.clear()
    await rig.w.advance(901)
    # The home edge was itself an arrival: it rescheduled; after 900 s, lock.
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_reengage_abandoned_after_max_wait():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})
    await settle()
    rig.w.calls.clear()
    await rig.w.advance(3601)
    assert rig.locks() == []
    assert rig.regime.last_action["action"] == "reengage_abandoned"
    assert rig.regime.last_action["why"] == "max_wait"


@pytest.mark.asyncio
async def test_reengage_retry_past_sleep_end_abandons():
    rig = await make_rig(start=datetime(2026, 11, 8, 5, 30, tzinfo=TZ), house="sleep")
    await rig.edge("sleep")  # 05:40 (inside the boot window? no: past_boot)
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})  # 05:40
    await settle()
    rig.w.calls.clear()
    await rig.w.advance(901)  # 05:55: not settled -> retry
    assert rig.locks() == []
    rig.w.set_state(EZ, "home")  # settled at 05:56 but also an arrival edge
    await settle()
    rig.w.calls.clear()
    await rig.w.advance(901)  # 06:11 > sleep_end: abandon
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_reengage_blocked_by_open_door():
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    rig.w.set_state(COVER_A, "open")
    rig.w.calls.clear()
    await rig.w.advance(901)
    assert rig.locks() == []
    rig.w.set_state(COVER_A, "closed")
    await rig.w.advance(901)
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_person_reload_keeps_en_route_resident_blocking_reengage():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})
    await settle()
    rig.w.set_state(EZ, None)  # person reload: removed
    rig.w.calls.clear()
    await rig.w.advance(901)
    assert rig.locks() == []
    assert rig.regime.releasing_set[EZ]["removed"] is True


@pytest.mark.asyncio
async def test_vacation_arrival_releases_no_reengage():
    rig = await make_rig(house="away")
    await rig.edge("vacation")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    rig.w.calls.clear()
    await rig.w.advance(4 * 3600)
    assert rig.locks() == []
    assert rig.regime.reason == "none"


# ============================================================================
# H-1 — write-time engage predicate (INV-2 rev 5)
# ============================================================================


@pytest.mark.asyncio
async def test_engage_intent_dropped_if_release_after_queue():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})  # task spawned, not run
    rig.regime.on_person_arriving({"person_entity": EZ})  # 50 ms later: release
    await settle()
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_engage_intent_dropped_if_kill_switch_off_after_queue():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = False
    await settle()
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_engage_intent_dropped_if_house_left_sleep_before_batch():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})
    rig.mgr.house_state = "waking"
    await settle()
    assert rig.locks() == []
    assert rig.regime.last_action["why"] == "house_left_sleep"


@pytest.mark.asyncio
async def test_guest_engage_dropped_if_house_left_guest_before_write():
    rig = await make_rig()
    rig.mgr.house_state = "guest"
    rig.regime.on_house_state_changed({"new_state": "guest"})
    rig.mgr.house_state = "home_night"  # guest gate cleared before the write
    await settle()
    assert rig.locks() == []
    assert rig.regime.last_action["why"] == "guest_night_ended"


@pytest.mark.asyncio
async def test_engage_lands_when_no_release_intervened():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})
    await settle()
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_engage_dropped_when_release_inflight():
    rig = await make_rig(lockouts="locked")
    rig.w.apply_service_state = False
    rig.regime._release_inflight.add(LOCK_A)
    rig.w.set_state(LOCK_A, "unlocked")
    rig.w.set_state(LOCK_B, "unlocked")
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})
    await settle()
    assert rig.locks() == [LOCK_B]


@pytest.mark.asyncio
async def test_engage_under_sc_observation_logs_would_engage_no_call():
    rig = await make_rig()
    rig.sc.observation_mode = True
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})
    await settle()
    assert rig.w.calls == []
    assert rig.regime.last_action["action"] == "would_engage"


@pytest.mark.asyncio
async def test_engage_check_and_call_have_no_await_between():
    """Every await reachable in the engage task fires a release when it yields.

    The lock call for LOCK_A yields (hook fires an arrival); the release must
    then (a) unlock LOCK_A although it still reads `unlocked` (lock in
    flight) and (b) stop LOCK_B's lock, because LOCK_B's predicate is
    re-evaluated after the yield. A build that checks once for both, or
    logs between check and call, records a lock after the unlock.
    """
    rig = await make_rig()
    rig.w.apply_service_state = False
    fired = {"n": 0}

    def hook(domain, service, eid):
        if service == "lock" and fired["n"] == 0:
            fired["n"] += 1
            rig.regime.on_person_arriving({"person_entity": EZ})

    rig.w.call_hooks.append(hook)
    rig.mgr.house_state = "sleep"
    rig.regime.on_house_state_changed({"new_state": "sleep"})
    await settle()
    seq = [(c[1], c[2]) for c in rig.w.calls if c[0] == "lock"]
    assert seq == [("lock", LOCK_A), ("unlock", LOCK_A)]


@pytest.mark.asyncio
async def test_release_between_evaluate_and_execute_no_lock_survives():
    """Real CoordinatorManager batch; a lower-priority coordinator's evaluate()
    awaits and fires the arrival mid-batch. No lock.lock may follow the
    unlock (rev 5 H-1)."""
    man = load("domain_coordinators.manager")
    base = load("domain_coordinators.base")
    rig = await make_rig()

    class Mgr(man.CoordinatorManager):
        house_state = "home_night"

    mgr = Mgr(rig.w.hass)
    mgr._running = True
    rig.w.hass.data[const.DOMAIN]["coordinator_manager"] = mgr
    rig.mgr = mgr

    class Slow(base.BaseCoordinator):
        async def async_setup(self):
            pass

        async def async_teardown(self):
            pass

        async def evaluate(self, intents, context):
            await asyncio.sleep(0)
            rig.w.set_state(EZ, "home")  # arrival mid-batch
            await asyncio.sleep(0)
            return []

    slow = Slow(rig.w.hass, coordinator_id="slow", name="slow", priority=10)
    mgr._coordinators = {"security": rig.sc, "slow": slow}
    mgr.house_state = "sleep"
    rig.sc._on_house_state_changed_signal({"new_state": "sleep"})
    mgr._intent_queue.append(base.Intent(source="tick", coordinator_id="slow"))
    await mgr._async_process_batch()
    await settle()
    seq = [(c[1], c[2]) for c in rig.w.calls if c[0] == "lock"]
    last_unlock = max(i for i, s in enumerate(seq) if s[0] == "unlock")
    assert all(s[0] != "lock" for s in seq[last_unlock + 1:]), seq
    assert rig.w.hass.states.get(LOCK_A).state == "unlocked"
    assert rig.w.hass.states.get(LOCK_B).state == "unlocked"


@pytest.mark.asyncio
async def test_no_yield_between_engage_check_and_call():
    """A release scheduled for the very next loop turn must not be overtaken
    by a stale lock: check and call happen in one uninterrupted step, so the
    release runs AFTER both locks and unlocks them (in flight)."""
    rig = await make_rig()
    rig.w.apply_service_state = False
    rig.mgr.house_state = "sleep"
    loop = asyncio.get_event_loop()
    rig.regime.on_house_state_changed({"new_state": "sleep"})  # task queued
    loop.call_soon(rig.regime.on_person_arriving, {"person_entity": EZ})
    await settle()
    seq = [(c[1], c[2]) for c in rig.w.calls if c[0] == "lock"]
    first_unlock = min((i for i, s in enumerate(seq) if s[0] == "unlock"), default=None)
    assert first_unlock is not None, seq
    assert all(s[0] == "unlock" for s in seq[first_unlock:]), seq
    assert sorted(s[1] for s in seq[first_unlock:]) == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_window_blip_after_real_transition_releases():
    """M-2 (i): inside the boot window even a short-away blip edge counts."""
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="sleep",
                         lockouts="locked", past_boot=False)
    await rig.person(EZ, "Work")
    await rig.w.advance(30)
    await rig.person(EZ, "unknown")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_sc_async_setup_builds_lock_regime(monkeypatch):
    """Wire-in anchor for SecurityCoordinator.async_setup -> regime setup."""
    w = World(NIGHT, options(), entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    mgr = SimpleNamespace(house_state="home_night")
    w.hass.data[const.DOMAIN] = {"coordinator_manager": mgr}
    for ent in (LOCK_A, LOCK_B):
        w.seed(ent, "unlocked")
    w.seed(EZ, "not_home")

    class Injected(R.LockRegimeController):
        def __init__(self, hass, security, store=None):
            super().__init__(
                hass, security, now=w.clock, call_later=w.call_later,
                track_state=w.track_state, track_added_domain=w.track_added,
                track_removed_domain=w.track_removed, store=None,
            )

    monkeypatch.setattr(R, "LockRegimeController", Injected)
    monkeypatch.setattr(sec, "async_track_state_change_event", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(sec, "async_track_time_interval", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(sec, "async_dispatcher_connect", lambda *a, **k: (lambda: None))
    sc = sec.SecurityCoordinator(w.hass, garage_entities=[COVER_A, COVER_B])
    await sc.async_setup()
    assert isinstance(sc.lock_regime, Injected)
    await w.advance(601)
    mgr.house_state = "sleep"
    sc._on_house_state_changed_signal({"new_state": "sleep"})
    await settle()
    assert w.locks_called("lock") == [LOCK_A, LOCK_B]
    await sc.async_teardown()


# ============================================================================
# D4 — fail-safes: kill switch, hazard, read-back, teardown, timers
# ============================================================================


@pytest.mark.asyncio
async def test_kill_switch_off_releases_both():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = False
    rig.regime.on_kill_switch_changed(False)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_kill_switch_off_release_not_suppressed_by_observation():
    rig = await make_rig(lockouts="locked")
    rig.sc.observation_mode = True
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = False
    rig.regime.on_kill_switch_changed(False)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_kill_switch_off_skips_unavailable():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(LOCK_B, "unavailable")
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = False
    rig.regime.on_kill_switch_changed(False)
    await settle()
    assert rig.unlocks() == [LOCK_A]


@pytest.mark.asyncio
async def test_kill_switch_entity_off_edge_calls_release():
    """The switch entity's OFF write is the wire-in for the kill edge."""
    sw = load("switch")
    rig = await make_rig(lockouts="locked")
    mgr = SimpleNamespace(house_state="home_night", coordinators={"security": rig.sc})
    rig.w.hass.data[const.DOMAIN]["coordinator_manager"] = mgr
    rig.mgr = mgr
    switches = sw._build_security_lockout_switches(rig.w.hass, rig.w.cm_entry)
    kill = switches[0]
    kill.async_write_ha_state = lambda: None
    assert kill.entity_id == "switch.ura_security_coordinator_garage_lockout"
    assert kill.is_on is True
    await kill.async_turn_off()
    await settle()
    assert rig.w.cm_entry.options["security_garage_lockout_enabled"] is False
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_guest_switch_off_does_not_release():
    sw = load("switch")
    rig = await make_rig(lockouts="locked")
    mgr = SimpleNamespace(house_state="home_night", coordinators={"security": rig.sc})
    rig.w.hass.data[const.DOMAIN]["coordinator_manager"] = mgr
    guest = sw._build_security_lockout_switches(rig.w.hass, rig.w.cm_entry)[1]
    guest.async_write_ha_state = lambda: None
    assert guest.is_on is True  # absent key = default ON
    await guest.async_turn_off()
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_hazard_under_observation_releases_lockouts_not_door_locks():
    rig = await make_rig(
        lockouts="locked", opts=options(security_on_hazard_unlock_egress=True)
    )
    rig.sc.observation_mode = True
    rig.sc._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
    await settle()
    assert sorted(rig.unlocks()) == [LOCK_A, LOCK_B]
    assert DOOR_LOCK not in rig.unlocks()


@pytest.mark.asyncio
async def test_hazard_without_egress_config_no_release():
    rig = await make_rig(lockouts="locked")
    rig.sc._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_hazard_non_critical_no_release():
    rig = await make_rig(
        lockouts="locked", opts=options(security_on_hazard_unlock_egress=True)
    )
    rig.sc._handle_safety_hazard({"hazard_type": "smoke", "severity": "high"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_readback_retry_then_high_nm():
    rig = await make_rig(lockouts="locked")
    notes = []

    class NM:
        async def async_notify(self, **kw):
            notes.append(kw)

    rig.w.hass.data[const.DOMAIN]["notification_manager"] = NM()
    rig.w.apply_service_state = False  # opener ignores unlock
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(19)
    assert notes == [] and len(rig.unlocks()) == 2
    await rig.w.advance(2)  # 20 s read-back: one retry each
    assert sorted(rig.unlocks()) == [LOCK_A, LOCK_A, LOCK_B, LOCK_B]
    await rig.w.advance(21)
    assert len(notes) == 2
    assert {n["severity"].name for n in notes} == {"HIGH"}


@pytest.mark.asyncio
async def test_release_inflight_latch_clears_after_readback():
    rig = await make_rig(lockouts="locked")
    await rig.person(EZ, "home")
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B}
    await rig.w.advance(21)
    assert rig.regime._release_inflight == set()


@pytest.mark.asyncio
async def test_regime_never_emits_cover_service():
    """INV-1 / INV-1B for the regime: drive every trigger, record services."""
    rig = await make_rig(opts=options(security_on_hazard_unlock_egress=True))
    rig.w.set_state(COVER_A, "open")
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "100", {"unit_of_measurement": "ft"})
    rig.sc._handle_person_arriving_signal({"person_entity": OJI})
    await rig.w.advance(3 * 3600)
    await rig.edge("waking")
    await rig.edge("vacation")
    await rig.edge("arriving")
    await rig.edge("guest")
    rig.sc._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
    rig.regime.on_kill_switch_changed(False)
    await rig.w.advance(36 * 3600)
    await settle()
    domains = {c[0] for c in rig.w.calls}
    assert domains == {"lock"}  # no cover.* service from any path driven
    assert set(rig.w.locks_called("lock")) <= {LOCK_A, LOCK_B}
    # The only non-lockout write is the pre-existing hazard egress unlock.
    assert set(rig.w.locks_called("unlock")) - {LOCK_A, LOCK_B} <= {DOOR_LOCK}


@pytest.mark.asyncio
async def test_teardown_cancels_regime_timers():
    rig = await make_rig(past_boot=False)
    await rig.w.advance(200)
    await rig.edge("sleep")
    await rig.person(EZ, "home")  # re-engage timer + read-backs
    assert rig.w.live_timers()
    await rig.sc.async_teardown()
    assert rig.regime._backstop_unsub is None
    assert rig.regime._reengage_unsub is None
    assert rig.regime._boot_recheck_unsub is None
    assert rig.regime._guest_clock_unsub is None
    assert rig.regime._readback_unsubs == {}
    assert rig.w.live_timers() == []
    assert not any(rec["active"] for rec in rig.w.listeners)
    rig.w.calls.clear()
    await rig.w.advance(48 * 3600)
    rig.w.set_state(EZ, "not_home")
    rig.w.set_state(EZ, "home")
    await settle()
    assert rig.w.calls == []


async def _drive_switch_disable(rig):
    """Real CoordinatorEnabledSwitch.async_turn_off -> reload -> manager stop."""
    sw = load("switch")
    man = load("domain_coordinators.manager")
    integ = SimpleNamespace(data={"entry_type": const.ENTRY_TYPE_INTEGRATION},
                            options={}, entry_id="integration")
    rig.w.extra_entries.append(integ)
    mgr = man.CoordinatorManager(rig.w.hass)
    mgr._coordinators = {"security": rig.sc}
    order = []
    orig = rig.sc.async_teardown

    async def traced():
        await orig()
        order.append(("teardown_end", len(rig.w.calls)))

    rig.sc.async_teardown = traced

    async def reload(entry_id):
        assert entry_id == "integration"
        await mgr.async_stop()

    rig.w.on_reload = reload
    switch = sw.CoordinatorEnabledSwitch(
        rig.w.hass, rig.w.cm_entry, coordinator_id="security",
        conf_key=const.CONF_SECURITY_ENABLED, name="Security Coordinator",
        icon="mdi:shield-lock", device_id="security_coordinator",
        device_name="URA: Security Coordinator", device_model="Security Coordinator",
    )
    await switch.async_turn_off()
    return order


@pytest.mark.asyncio
async def test_sc_switch_off_releases_before_reload():
    rig = await make_rig(lockouts="locked")
    order = await _drive_switch_disable(rig)
    unlocks = [c for c in rig.w.calls if c[:2] == ("lock", "unlock")]
    assert [c[2] for c in unlocks] == [LOCK_A, LOCK_B]
    assert all(c[3] is True for c in unlocks)  # blocking inside teardown
    assert order == [("teardown_end", 2)]  # unlocks happened before teardown ended


@pytest.mark.asyncio
async def test_sc_teardown_restart_does_not_release():
    rig = await make_rig(lockouts="locked")
    await rig.sc.async_teardown()  # options still say enabled
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_sc_teardown_reads_live_cm_entry_not_setup_snapshot():
    rig = await make_rig(lockouts="locked")
    rig.w.cm_entry.options = {**rig.w.cm_entry.options, "security_coordinator_enabled": False}
    await rig.sc.async_teardown()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_sc_teardown_no_release_when_kill_switch_off():
    rig = await make_rig(lockouts="locked", opts=options(security_garage_lockout_enabled=False))
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    await rig.sc.async_teardown()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_sc_teardown_release_timeout_does_not_block_unload(monkeypatch):
    """A dead opener (call never returns) cannot stall unload; NM attempted."""
    rig = await make_rig(lockouts="locked")
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    notes = []

    class NM:
        async def async_notify(self, **kw):
            notes.append(kw)

    rig.w.hass.data[const.DOMAIN]["notification_manager"] = NM()
    gate = asyncio.Event()

    async def hang(domain, service, data, blocking=False, **kw):
        rig.w.calls.append((domain, service, data.get("entity_id"), blocking))
        await gate.wait()

    rig.w.hass.services.async_call = hang
    # Scoped: the private-package const only (restored by monkeypatch).
    monkeypatch.setattr(const, "GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S", 0.01)
    await asyncio.wait_for(rig.sc.async_teardown(), 2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert len(notes) == 2
    assert rig.regime._torn_down is True


# ============================================================================
# Review B fix-ups
# ============================================================================

_LOOP_CALLBACKS = (
    "_on_person_event", "_on_person_added", "_on_person_removed",
    "_on_distance_event", "_on_lockout_event", "_on_backstop",
    "_on_reengage_timer", "_on_boot_recheck", "_on_guest_clock", "_on_readback",
)


@pytest.mark.asyncio
async def test_every_registered_regime_callback_is_a_loop_callback():
    """B-C1 anchor: enumerate what the regime hands to timers / trackers
    across a full night and assert HA types each as a Callback job (the
    harness also asserts this at every registration)."""
    from homeassistant.core import HassJob, HassJobType

    rig = await make_rig(past_boot=False)
    await rig.w.advance(601)  # boot recheck + window
    await rig.edge("sleep")  # backstop
    await rig.person(EZ, "home")  # P1 -> unlock -> read-back + re-engage
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    await settle()
    names = set()
    for cb in rig.w.registered:
        assert HassJob(cb).job_type == HassJobType.Callback, cb
        target = cb.func if hasattr(cb, "func") else cb
        names.add(getattr(target, "__name__", repr(target)))
    expected = set(_LOOP_CALLBACKS)
    assert expected <= names, expected - names
    for name in _LOOP_CALLBACKS:
        assert HassJob(getattr(rig.regime, name)).job_type == HassJobType.Callback, name


@pytest.mark.asyncio
async def test_failed_spawn_never_poisons_release_latch():
    """B-M2: async_create_task raising during a release must not leave the
    lockout in _release_inflight; the next release still unlocks."""
    rig = await make_rig(lockouts="locked")
    real = rig.w.hass.async_create_task
    boom = {"left": 1}

    def flaky(coro, *a, **k):
        if boom["left"] and asyncio.iscoroutine(coro) and coro.__name__ == "_async_unlock":
            boom["left"] -= 1
            raise RuntimeError("loop closing")
        return real(coro, *a, **k)

    rig.w.hass.async_create_task = flaky
    rig.sc._handle_person_arriving_signal({"person_entity": EZ})
    await settle()
    assert LOCK_A not in rig.regime._release_inflight
    rig.w.calls.clear()
    await rig.edge("arriving")
    assert LOCK_A in rig.unlocks()


@pytest.mark.asyncio
async def test_reload_mid_unlock_still_releases():
    """B-M1: an arrival unlock in flight, then an SC reload (teardown) -> the
    unlock completes; the lockout ends released."""
    rig = await make_rig(lockouts="locked")
    gate = asyncio.Event()
    orig = rig.w.hass.services.async_call

    async def slow(domain, service, data, blocking=False, **kw):
        if service == "unlock":
            await gate.wait()
        await orig(domain, service, data, blocking=blocking, **kw)

    rig.w.hass.services.async_call = slow
    await rig.person(EZ, "home")  # unlock tasks now awaiting the opener
    teardown = asyncio.ensure_future(rig.sc.async_teardown())
    await settle()
    gate.set()
    await asyncio.wait_for(teardown, 2)
    assert rig.w.hass.states.get(LOCK_A).state == "unlocked"
    assert rig.w.hass.states.get(LOCK_B).state == "unlocked"


@pytest.mark.asyncio
async def test_failure_notifications_name_each_lockout():
    """B-L1: NM dedups on coordinator:title:location, so the location must
    carry the entity or a second failed lockout is never named."""
    rig = await make_rig(lockouts="locked")
    notes = []

    class NM:
        async def async_notify(self, **kw):
            notes.append(kw)

    rig.w.hass.data[const.DOMAIN]["notification_manager"] = NM()
    rig.w.apply_service_state = False
    await rig.person(EZ, "home")
    await rig.w.advance(45)
    keys = {(n["coordinator_id"], n["title"], n["location"]) for n in notes}
    assert len(keys) == 2
    assert {n["location"] for n in notes} == {f"garage:{LOCK_A}", f"garage:{LOCK_B}"}


@pytest.mark.asyncio
async def test_corrupt_resident_store_shape_ignored():
    """B-L3: a string where a list belongs must not become per-char ids."""
    class Store:
        async def async_load(self):
            return {"residents": "person.ziri"}

        def async_delay_save(self, fn, delay):
            pass

    rig = await make_rig(lockouts="locked", store=Store())
    subscribed = set().union(*(rec["ids"] for rec in rig.w.listeners))
    assert "p" not in subscribed and "person.ziri" not in subscribed
    assert EZ in subscribed  # live persons still subscribed


# ============================================================================
# D1 — config surface
# ============================================================================


def test_lockout_entities_overlap_rejected():
    assert R.lockout_overlap([DOOR_LOCK, LOCK_A], [LOCK_A, LOCK_B]) == [LOCK_A]
    assert R.lockout_overlap([DOOR_LOCK], [LOCK_A, LOCK_B]) == []
    assert R.lockout_overlap(DOOR_LOCK, DOOR_LOCK) == [DOOR_LOCK]


@pytest.mark.asyncio
async def test_lockout_config_roundtrip():
    """Options-flow step: overlap -> error; clean save -> keys persisted."""
    cf = load("config_flow")

    class Flow(cf.UniversalRoomAutomationOptionsFlow if hasattr(
            cf, "UniversalRoomAutomationOptionsFlow") else object):
        pass

    step = None
    for name in dir(cf):
        obj = getattr(cf, name)
        if isinstance(obj, type) and hasattr(obj, "async_step_coordinator_security"):
            step = obj.async_step_coordinator_security
            break
    assert step is not None
    fake = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"a": 1}),
        _get_current=lambda k, d=None: d,
        async_create_entry=lambda title, data: {"type": "create_entry", "data": data},
        async_show_form=lambda step_id, data_schema, errors=None: {
            "type": "form", "errors": errors, "schema": data_schema},
    )
    bad = await step(fake, {
        "security_lock_entities": [DOOR_LOCK, LOCK_A],
        "security_lockout_entities": [LOCK_A, LOCK_B],
    })
    assert bad["type"] == "form"
    assert bad["errors"] == {"security_lockout_entities": "lockout_overlaps_locks"}
    good = await step(fake, {
        "security_lock_entities": [DOOR_LOCK],
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_lockout_excluded_persons": [KIOSK],
        "security_lockout_distance_sensors": [EZ_DIST],
    })
    assert good["type"] == "create_entry"
    assert good["data"]["security_lockout_entities"] == [LOCK_A, LOCK_B]
    assert good["data"]["a"] == 1
    form = await step(fake, None)
    keys = {str(k) for k in form["schema"].schema}
    assert {"security_lockout_entities", "security_lockout_excluded_persons",
            "security_lockout_distance_sensors", "security_lockout_approach_zone"} <= keys


def test_live_keys_in_reload_suppress_and_no_live_attr_sets():
    init = load("__init__")
    for key in (
        const.CONF_SECURITY_GARAGE_LOCKOUT_ENABLED,
        const.CONF_SECURITY_LOCKOUT_ENGAGE_ON_GUEST_SLEEP,
        const.CONF_SECURITY_LOCKOUT_EXCLUDED_PERSONS,
        const.CONF_GARAGE_LOCKOUT_APPROACH_RADIUS_M,
        const.CONF_GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN,
        const.CONF_GARAGE_LOCKOUT_REENGAGE_DELAY_S,
    ):
        assert key in init.OPTIONS_RELOAD_SUPPRESS_KEYS, key
        assert key in init._NO_LIVE_ATTR_KEYS, key


def test_lockout_numbers_read_options():
    num = load("number")
    entry = SimpleNamespace(data={}, options={"garage_lockout_approach_radius_m": 800})
    ents = num._build_security_lockout_numbers(None, entry)
    by_id = {e.entity_id: e for e in ents}
    assert by_id["number.ura_garage_lockout_approach_radius"].native_value == 800.0
    assert by_id["number.ura_garage_lockout_morning_backstop"].native_value == 60.0
    assert by_id["number.ura_garage_lockout_reengage_delay"].native_value == 900.0


@pytest.mark.asyncio
async def test_number_knob_read_live_by_regime():
    rig = await make_rig(opts=options(garage_lockout_reengage_delay_s=0))
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    rig.w.calls.clear()
    await rig.w.advance(3600)
    assert rig.locks() == []  # 0 = never re-engage


# ============================================================================
# D5 — diagnostics + arming path byte-identical
# ============================================================================


@pytest.mark.asyncio
async def test_snapshot_attributes():
    rig = await make_rig()
    await rig.edge("sleep")
    snap = rig.regime.snapshot()
    assert snap["lock_regime_garage_lockout_enabled"] is True
    assert snap["lock_regime_garage_lockout_reason"] == "sleep"
    assert snap["lock_regime_garage_lockout_last_action"]["action"] == "engage"


@pytest.mark.asyncio
async def test_arming_path_unchanged_byte_identical():
    """Auto-follow ON SLEEP edge: the queued intent and evaluate() output are
    the same with the lock regime wired in and without it."""

    async def run(with_regime: bool):
        rig = await make_rig(opts=options(security_garage_lockout_enabled=with_regime))
        queued = []
        rig.mgr.queue_intent = queued.append
        rig.sc._auto_follow_house_state = True
        if not with_regime:
            rig.sc._lock_regime = None
        rig.sc._on_house_state_changed_signal({"new_state": "sleep"})
        await settle()
        actions = await rig.sc.evaluate(queued, {})
        return (
            [(i.source, i.data, i.coordinator_id) for i in queued],
            [type(a).__name__ for a in actions],
            rig.sc._pending_house_state,
            rig.sc.armed_state,
        )

    assert await run(True) == await run(False)
