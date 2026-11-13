"""HOUSE-STATE-FIRST-PRINCIPLES-1 step 1a D4 (PLANNING_house_state_axes_step1.md rev 3).

INV-LOCK: with the garage lockout ON, no release whose trigger is
``house_state:*`` or ``boot_recheck`` writes an unlock or ends the episode,
unless the edge's new state (or the restored house at the boot recheck) is
``waking`` with a sleep-like reason, or the edge's trigger is an operator
trigger (``override_set`` / ``override_clear``). The decision is a function of
(new_state, reason, trigger) alone; ``_episode_saw_empty`` only pages.

Every test drives the REAL LockRegimeController through the REAL SC
house-state bridge (``_lockout_harness`` fake clock / timers / trackers) and
asserts on the recorded ``lock.unlock`` stream, NM pages and regime state.
Times are hardcoded wall-clock literals (sleep window 22 -> 06, backstop
06:00 + 60 min = 07:00), never imported constants.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest

from _lockout_harness import TZ, settle
from test_lock_release_arriving import (
    BOOT_GAP,
    UNCORR,
    UNCOUNTED,
    departure_unseen,
    hs,
    install_nm,
    snap,
)
from test_sc_garage_lockout import (
    BOOT_0200,
    EZ,
    LOCK_A,
    LOCK_B,
    OJI,
    DictStore,
    make_rig,
    options,
)


async def _to(rig, day: int, hh: int, mm: int, ss: int = 0) -> None:
    target = datetime(2026, 11, day, hh, mm, ss, tzinfo=TZ)
    await rig.w.advance((target - rig.w.now).total_seconds())


# ============================================================================
# A9 / A11: no non-operator house-edge release; an ignored edge keeps the episode
# ============================================================================


@pytest.mark.asyncio
async def test_body_only_chain_no_release_without_any_flag():
    """SLEEP engaged; SLEEP -> AWAY -> ARRIVING -> HOME_NIGHT -> HOME_DAY with
    no person edge -> 0 unlocks, then exactly one backstop release; the
    trip-wire stays silent (no house-state release wrote anything)."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]
    for new in ("away", "arriving", "home_night", "home_day"):
        await rig.w.advance(300)
        await rig.edge(new)
    assert rig.unlocks() == []
    assert rig.regime.reason == "sleep"
    assert snap(rig)["lock_regime_house_edges_ignored"] == 3
    await _to(rig, 8, 7, 0, 1)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"
    assert rig.regime.reason == "none"
    assert nm.of(UNCORR) == []


@pytest.mark.asyncio
async def test_never_empty_episode_home_edge_no_release():
    """Discriminates "a flag still holds it": a BOOT_UNKNOWN lock rebuilt in
    the evening (house home_night, never empty, ``_episode_saw_empty`` False)
    and a default-trigger HOME_DAY edge -> 0 unlocks (the lock-release branch
    released it: no taint)."""
    rig = await make_rig(start=datetime(2026, 11, 7, 23, 30, tzinfo=TZ),
                         house="home_night", lockouts="locked",
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig.regime.reason == "boot_unknown"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    await rig.edge("home_day")
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
async def test_default_trigger_home_edge_does_not_release():
    """Rig default trigger ``"t"``, reason sleep, HOME_DAY -> 0 unlocks,
    house_edges_ignored 1, the manual-unlock memory and backstop kept."""
    store = DictStore()
    rig = await make_rig(store=store)
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unlocked")  # a human unlocks one lockout
    assert rig.regime.manual_unlock_reason == "sleep"
    await rig.edge("home_day")
    assert rig.unlocks() == []
    assert rig.regime.reason == "sleep"
    assert snap(rig)["lock_regime_house_edges_ignored"] == 1
    rec = rig.regime.last_action
    assert rec["action"] == "house_edge_ignored"
    assert rec["trigger"] == "house_state:home_day"
    assert rec["edge_trigger"] == "t"
    assert rec["old_state"] == "sleep"
    assert rig.regime.manual_unlock_reason == "sleep"
    assert store.data["garage_manual_unlock"] == "sleep"
    assert rig.regime._backstop_unsub is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["override_set", "override_clear"])
@pytest.mark.parametrize("new", ["home_day", "home_night", "arriving"])
async def test_operator_triggers_release(trigger, new):
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.w.advance(60)
    await hs(rig, new, trigger=trigger)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == f"house_state:{new}"
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["override_set", "override_clear"])
async def test_operator_trigger_reason_none_no_unlock(trigger):
    """Delta L2: with reason NONE every house edge is `none` (an operator
    ARRIVING / HOME_* no longer unlocks a hand lock)."""
    rig = await make_rig(house="away")
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    assert rig.regime.reason == "none"
    await hs(rig, "arriving", trigger=trigger)
    await hs(rig, "home_day", trigger=trigger)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_waking_releases_sleep_like_and_not_vacation():
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("waking")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    rig2 = await make_rig(house="away")
    await rig2.edge("vacation")
    await rig2.edge("waking")
    assert rig2.unlocks() == []
    assert rig2.regime.reason == "vacation"


# ============================================================================
# Boot recheck
# ============================================================================


@pytest.mark.asyncio
async def test_boot_recheck_waking_releases_no_page():
    rig = await make_rig(start=datetime(2026, 11, 8, 6, 10, tzinfo=TZ), house="waking",
                         lockouts="locked", past_boot=False)
    nm = install_nm(rig)
    await rig.w.advance(121)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "boot_recheck"
    assert nm.of(UNCORR) == []
    assert nm.of(BOOT_GAP) == []


@pytest.mark.asyncio
async def test_boot_recheck_home_ignored_keeps_manual_memory():
    store = DictStore()
    rig1 = await make_rig(store=store)
    await rig1.edge("sleep")
    rig1.w.set_state(LOCK_A, "unlocked")
    assert store.data["garage_manual_unlock"] == "sleep"

    def hook(w):
        w.seed(LOCK_A, "unlocked")

    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)), seed_hook=hook,
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"
    assert rig2.regime.manual_unlock_reason == "sleep"


@pytest.mark.asyncio
@pytest.mark.parametrize(("boot_house", "decision"), [
    ("away", "no_change"),
    ("arriving", "house_edge_ignored"),
])
async def test_boot_gap_page_on_house_edge_ignored(boot_house, decision):
    """INV-PAGE (a): restored house away (decision no_change) or arriving with
    reason sleep (decision house_edge_ignored), a resident restored home, the
    lockouts locked -> one boot_gap page per lockout, no release."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await rig1.edge("sleep")
    rig2 = await make_rig(start=datetime(2026, 11, 8, 1, 40, tzinfo=TZ),
                          house=boot_house, lockouts="locked", past_boot=False,
                          persons={EZ: "home", OJI: "not_home"},
                          store=DictStore(dict(store.data)))
    nm = install_nm(rig2)
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == decision
    assert sorted(p["location"] for p in nm.of(BOOT_GAP)) == [
        f"garage_lockout:still_locked:{LOCK_A}", f"garage_lockout:still_locked:{LOCK_B}"]


@pytest.mark.asyncio
async def test_boot_gap_page_on_saw_empty_vacation():
    """Delta M3: VACATION engaged; vacation -> away (saw-empty); body
    arriving -> home_day ignored; restart with the house restored home_day
    and a resident restored home -> recheck house_edge_ignored and one
    boot_gap page per lockout. The same restart with the flag False -> none."""
    day = datetime(2026, 11, 7, 14, 0, tzinfo=TZ)
    store = DictStore()
    rig1 = await make_rig(start=day, house="away", store=store,
                          persons={EZ: "not_home", OJI: "not_home"})
    await rig1.edge("vacation")
    assert rig1.locks() == [LOCK_A, LOCK_B]
    assert snap(rig1)["lock_regime_episode_saw_empty"] is False
    await rig1.edge("away")
    assert snap(rig1)["lock_regime_episode_saw_empty"] is True
    await rig1.edge("arriving")
    await rig1.edge("home_day")
    assert rig1.unlocks() == []
    assert store.data["garage_episode_saw_empty"] is True
    rig2 = await make_rig(start=day + timedelta(hours=3), house="home_day",
                          lockouts="locked", past_boot=False,
                          persons={EZ: "home", OJI: "not_home"},
                          store=DictStore(dict(store.data)))
    nm = install_nm(rig2)
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.reason == "vacation"
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"
    assert len(nm.of(BOOT_GAP)) == 2
    # Discriminator: the flag cleared in the store -> no page.
    data = dict(store.data)
    data["garage_episode_saw_empty"] = False
    rig3 = await make_rig(start=day + timedelta(hours=3), house="home_day",
                          lockouts="locked", past_boot=False,
                          persons={EZ: "home", OJI: "not_home"},
                          store=DictStore(data))
    nm3 = install_nm(rig3)
    await rig3.w.advance(121)
    assert rig3.regime.last_action["decision"] == "house_edge_ignored"
    assert nm3.of(BOOT_GAP) == []


# ============================================================================
# _episode_saw_empty: writers, store migration, page readers (A13 / A21)
# ============================================================================


@pytest.mark.asyncio
async def test_saw_empty_set_on_away_edge():
    store = DictStore()
    rig = await make_rig(store=store)
    await rig.edge("sleep")
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    await rig.edge("away")
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    assert store.data["garage_episode_saw_empty"] is True
    # reason NONE: an away edge sets nothing.
    rig2 = await make_rig(house="home_day")
    await rig2.edge("away")
    assert snap(rig2)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("old", ["arriving", "vacation", "away"])
async def test_saw_empty_set_on_arriving_or_vacation_old_state(old):
    """Delta M2 (discriminates "AWAY edge only"): reason sleep, the empty edge
    lost; the first edge seen has the empty state only on its OLD side ->
    flag set; a rejected ``unavailable -> home`` then pages."""
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    rig.mgr.house_state = old  # the dispatch was suppressed
    await rig.edge("home_night")
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    assert rig.mgr.house_state == "home_night"
    await rig.person(EZ, "home")  # unavailable -> home, rejected
    assert rig.unlocks() == []
    await rig.w.advance(91)
    assert len(nm.of(UNCOUNTED)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("boot_house", ["away", "arriving"])
async def test_saw_empty_set_at_boot_and_recheck(boot_house):
    # _boot_rebuild: restored house empty with a lockout locked.
    rig = await make_rig(start=BOOT_0200, house=boot_house, lockouts="locked",
                         past_boot=False)
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    # _boot_recheck_regime: house awake at boot (no rebuild flag), empty at
    # the recheck.
    rig2 = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                          past_boot=False,
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig2)["lock_regime_episode_saw_empty"] is False
    rig2.mgr.house_state = boot_house
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert snap(rig2)["lock_regime_episode_saw_empty"] is True


@pytest.mark.asyncio
async def test_saw_empty_store_migration_from_taint():
    """A legacy store ``garage_arrival_taint: True`` maps to the page flag
    (never a release) and the two legacy keys are absent from the next save."""
    legacy = {
        "residents": [EZ, OJI],
        "garage_reason": "sleep",
        "garage_arrival_taint": True,
        "garage_episode_saw_arriving": True,
        "garage_manual_unlock": None,
    }
    store = DictStore(dict(legacy))
    rig = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_night",
                         lockouts="locked", past_boot=False, store=store,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    await rig.w.advance(121)
    assert rig.unlocks() == []
    saved = rig.regime._store_payload()
    assert saved["garage_episode_saw_empty"] is True
    assert "garage_arrival_taint" not in saved
    assert "garage_episode_saw_arriving" not in saved
    # A legacy False taint and no new key -> False.
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_night",
                          lockouts="locked", past_boot=False,
                          store=DictStore({**legacy, "garage_arrival_taint": False}),
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig2)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
async def test_uncounted_page_needs_saw_empty_or_empty_house():
    """INV-PAGE (b): AWAY edge seen, house now home_night, a resident
    ``unavailable -> home`` rejected -> one page per lockout; an episode that
    never saw an empty house, house home_night -> no page."""
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.mgr.house_state = "home_night"  # no edge: awake read
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert len(nm.of(UNCOUNTED)) == 2
    rig2 = await make_rig()
    nm2 = install_nm(rig2)
    await departure_unseen(rig2, EZ)
    await rig2.edge("sleep")
    await rig2.edge("home_night")  # ignored, never empty
    await rig2.person(EZ, "home")
    await rig2.w.advance(91)
    assert nm2.of(UNCOUNTED) == []


# ============================================================================
# A14 trip-wire independence / L3 operator kwarg
# ============================================================================


@pytest.mark.asyncio
async def test_tripwire_independent_of_edge_decision(monkeypatch):
    """The trip-wire never consults ``_edge_decision``: with the decision
    itself mutated to release a default-trigger HOME_* edge, the release
    happens AND one HIGH page fires. WAKING, an operator edge and a person
    release page nothing."""
    rig = await make_rig()
    nm = install_nm(rig)
    real = rig.regime._edge_decision

    def patched(new, cfg, *, operator=False):
        if new == "home_day":
            return "release", None
        return real(new, cfg, operator=operator)

    monkeypatch.setattr(rig.regime, "_edge_decision", patched)
    await rig.edge("sleep")
    await rig.edge("home_day")
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    pages = nm.of(UNCORR)
    assert len(pages) == 1
    assert int(pages[0]["severity"]) == 3
    assert "house_state:home_day" in pages[0]["message"]
    assert snap(rig)["lock_regime_uncorroborated_releases"] == 1

    for exempt in ("waking", "operator", "person"):
        rig2 = await make_rig()
        nm2 = install_nm(rig2)
        await rig2.edge("sleep")
        if exempt == "waking":
            await rig2.edge("waking")
        elif exempt == "operator":
            await rig2.edge("home_day", trigger="override_set")
        else:
            await rig2.edge("away")
            await rig2.person(EZ, "home")
        await settle()
        assert rig2.unlocks() == [LOCK_A, LOCK_B], exempt
        assert nm2.of(UNCORR) == [], exempt


@pytest.mark.asyncio
async def test_release_operator_kwarg_threaded():
    """L3: ``_release`` takes ``operator`` (no ``override``); an
    ``override_clear`` edge release passes operator=True through to the
    trip-wire (no page)."""
    rig = await make_rig()
    sig = inspect.signature(rig.regime._release)
    assert "operator" in sig.parameters
    assert "override" not in sig.parameters
    assert "operator" in inspect.signature(rig.regime._edge_decision).parameters
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("home_day", trigger="override_clear")
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert nm.of(UNCORR) == []
    assert snap(rig)["lock_regime_uncorroborated_releases"] == 0


# ============================================================================
# Guest-night rule-OFF morning, M1 discharge (A23)
# ============================================================================


@pytest.mark.asyncio
async def test_guest_night_rule_off_morning_backstop():
    """GUEST -> HOME_DAY in the morning with reason guest_night (reachable only
    with the stay rule kill switch OFF) is ignored; the backstop releases."""
    rig = await make_rig()
    await rig.edge("guest")  # 23:10, guest_night engage
    assert rig.regime.reason == "guest_night"
    await _to(rig, 8, 6, 20)
    await rig.edge("home_day")
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    await _to(rig, 8, 6, 59, 59)
    assert rig.unlocks() == []
    await _to(rig, 8, 7, 0, 1)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"


@pytest.mark.asyncio
async def test_arrival_outside_window_keeps_backstop_ends_episode():
    """Delta M1 refuted, discharge pinned: reason sleep (window 22 -> 06,
    backstop 60 min); a manual unlock at 05:00 (memory sleep); SLEEP -> AWAY
    at 06:00; a resident ``not_home -> home`` S1 release at 06:30 (outside the
    window) leaves the backstop armed; the 07:00 backstop sets reason NONE and
    clears the memory; a restart at 22:59 with SLEEP in the boot window
    decides ``engage`` (not ``manual_unlock_remembered``)."""
    store = DictStore()
    rig = await make_rig(store=store)
    await rig.edge("sleep")
    await _to(rig, 8, 5, 0)
    rig.w.set_state(LOCK_A, "unlocked")
    assert rig.regime.manual_unlock_reason == "sleep"
    await _to(rig, 8, 6, 0)
    await rig.edge("away")
    await _to(rig, 8, 6, 30)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_B]
    assert rig.regime.last_action["trigger"] == "person:person.ezinne"
    assert rig.regime._backstop_unsub is not None
    assert rig.regime.reason == "sleep"
    await _to(rig, 8, 7, 0, 1)
    assert rig.regime.reason == "none"
    assert rig.regime.manual_unlock_reason is None
    assert store.data["garage_manual_unlock"] is None
    rig2 = await make_rig(start=datetime(2026, 11, 8, 22, 59, tzinfo=TZ), house="sleep",
                          past_boot=False, store=DictStore(dict(store.data)))
    decisions: list = []
    real = rig2.regime._record

    def spy(action, *, trigger, written, extra=None, policy="garage_lockout"):
        if action == "boot_recheck":
            decisions.append((extra or {}).get("decision"))
        return real(action, trigger=trigger, written=written, extra=extra, policy=policy)

    rig2.regime._record = spy
    await rig2.w.advance(121)
    assert decisions == ["engage"]
    assert rig2.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_vacation_armed_while_home_held_until_sleep():
    """Config extreme (Q9): VACATION selected while the family is home
    engages at selection; the override-clearing default-trigger HOME_* edge
    is ignored; the next SLEEP converts the reason and WAKING releases."""
    rig = await make_rig(start=datetime(2026, 11, 7, 14, 0, tzinfo=TZ), house="home_day",
                         persons={EZ: "home", OJI: "home"})
    await hs(rig, "vacation", trigger="override_set")
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.edge("home_day")  # inference clears the override
    assert rig.unlocks() == []
    assert rig.regime.reason == "vacation"
    await _to(rig, 7, 23, 30)
    await rig.edge("sleep")
    assert rig.regime.reason == "sleep"
    await _to(rig, 8, 6, 10)
    await rig.edge("waking")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
