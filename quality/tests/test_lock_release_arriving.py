"""LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 (plan PLANNING_lock_release_on_arriving.md rev 3).

House-state ARRIVING is body evidence with no identity (presence.infer moves
AWAY -> ARRIVING on census_count > 0 or any zone occupied). HOUSE-STATE step 1a
(PLANNING_house_state_axes_step1.md rev 3, INV-LOCK) retired the ARRIVING taint:
with the garage lockout ON, an engaged episode never releases on a
``house_state:*`` / ``boot_recheck`` trigger, except WAKING (sleep-like) and an
operator trigger (``override_set`` / ``override_clear``). The episode's
``_episode_saw_empty`` flag is a page condition only. Real arrivals release
through the resident person edge (S1), which is unchanged.

Every test drives the REAL LockRegimeController and the REAL
SecurityCoordinator house-state bridge (``_on_house_state_changed_signal``)
through the injected fake clock / timers / trackers of ``_lockout_harness``,
and asserts on the recorded ``lock.unlock`` stream and regime state. No test
assigns ``_episode_saw_empty`` / ``engage_seq``
directly (plan §7, F17); seams are a patched ``_edge_decision`` return or a
neutered call. Times and bounds are hardcoded literals, never imported
constants.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from _lockout_harness import TZ, settle
from test_sc_garage_lockout import (
    BOOT_0200,
    EZ,
    KIOSK,
    LOCK_A,
    LOCK_B,
    NIGHT,
    OJI,
    DictStore,
    const,
    make_rig,
    options,
)

JAYA = "person.jaya"
ZIRI = "person.ziri"
FIXTURE = (
    pathlib.Path(__file__).resolve().parent
    / "fixtures"
    / "lock_arriving_house_edges_2026_11.json"
)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


async def hs(rig, new: str, *, old: str | None = None, trigger: str = "t") -> None:
    """A house-state edge through the REAL SC bridge with an explicit
    old_state / trigger (presence's payload shape)."""
    if old is None:
        old = rig.mgr.house_state
    rig.mgr.house_state = new
    rig.sc._on_house_state_changed_signal(
        {"old_state": old, "new_state": new, "trigger": trigger, "confidence": 1.0}
    )
    await settle()


def snap(rig) -> dict:
    return rig.regime.snapshot()


async def tainted_sleep_episode(rig) -> None:
    """SLEEP engage, then a false AWAY and a body-only ARRIVING."""
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.edge("away")
    await rig.edge("arriving")


def stale_home(rig, pid: str, src: str, age_s: float = 4119.0) -> None:
    """The person reads home from a source tracker that did not change at the
    edge (the suspicious-arrival hold shape)."""
    rig.w.seed(src, "home", {"source_type": "gps"},
               last_changed=rig.w.now - timedelta(seconds=age_s))
    rig.w.set_state(pid, "home", {"source": src})


# ============================================================================
# D1 — a tainted episode never releases on house-state edges
# ============================================================================


@pytest.mark.asyncio
async def test_body_only_arriving_does_not_release_sleep():
    rig = await make_rig()
    await tainted_sleep_episode(rig)
    assert rig.unlocks() == []
    assert rig.regime.reason == "sleep"
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    assert rig.regime.last_action["trigger"] == "house_state:arriving"
    assert rig.regime._backstop_unsub is not None  # backstop still scheduled
    s = snap(rig)
    assert s["lock_regime_episode_saw_empty"] is True
    assert s["lock_regime_house_edges_ignored"] == 1


@pytest.mark.asyncio
async def test_arriving_then_home_star_chain_holds_until_backstop():
    rig = await make_rig()
    await tainted_sleep_episode(rig)
    await rig.edge("home_night")
    await rig.w.advance(3600)
    await rig.edge("home_evening")
    await rig.edge("home_day")
    assert rig.unlocks() == []
    assert rig.regime.reason == "sleep"
    assert snap(rig)["lock_regime_house_edges_ignored"] == 4
    # Morning backstop (sleep_end 06:00 + 60 min) releases once.
    await rig.w.advance(
        (datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"
    assert rig.regime.reason == "none"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
async def test_person_release_keeps_taint_later_home_star_held():
    """F1 discriminator: the resident's edge unlocks, the taint survives, and a
    HOME_* edge 2 h later is still held (the episode is not ended)."""
    rig = await make_rig()
    await tainted_sleep_episode(rig)
    await rig.w.advance(45)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "person:person.ezinne"
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    rig.w.calls.clear()
    await rig.w.advance(2 * 3600)
    await rig.edge("home_night")
    assert rig.w.calls == []
    assert rig.regime.reason == "sleep"
    assert rig.regime.last_action["action"] == "house_edge_ignored"


@pytest.mark.asyncio
async def test_vacation_tainted_home_edges_never_release():
    """Discriminates 'release merely delayed': 6 h of HOME_* edges after a
    body-only ARRIVING in a VACATION episode release nothing."""
    rig = await make_rig(house="away")
    await rig.edge("vacation")
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.edge("arriving")
    for new in ("home_day", "home_evening", "home_night") * 2:
        await rig.w.advance(3600)
        await rig.edge(new)
    assert rig.unlocks() == []
    assert rig.regime.reason == "vacation"


@pytest.mark.asyncio
async def test_real_arrival_edge_before_arriving_releases():
    """16 of 17 recent real arrivals: the tracker edge leads ARRIVING."""
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.w.advance(35)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "person:person.ezinne"
    await rig.edge("arriving")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_real_arrival_edge_after_arriving_releases_8632_shape():
    """Edge 8632: ARRIVING led Ezinne's GPS edge by 45 s."""
    rig = await make_rig()
    await tainted_sleep_episode(rig)
    assert rig.unlocks() == []
    await rig.w.advance(45)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "person:person.ezinne"


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["edge_first", "arriving_first"])
async def test_real_arrival_with_stale_source_hold_releases_after_hold(order):
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("away")
    if order == "arriving_first":
        await rig.edge("arriving")
    stale_home(rig, EZ, "device_tracker.ez_ipad")
    await settle()
    assert rig.unlocks() == []  # held 5 s
    if order == "edge_first":
        await rig.edge("arriving")
    await rig.w.advance(4.9)
    assert rig.unlocks() == []
    await rig.w.advance(0.2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "person:person.ezinne"


@pytest.mark.asyncio
async def test_named_zone_to_home_releases():
    rig = await make_rig()
    await rig.person(EZ, "work")
    await tainted_sleep_episode(rig)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_boot_settle_suppressed_arriving_old_state_taints():
    """H2: boot settle swallowed the ARRIVING edge; the first edge the regime
    sees is arriving -> home_night. old_state alone taints it."""
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("away")
    rig.mgr.house_state = "arriving"  # dispatch suppressed
    await rig.edge("home_night")
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    assert rig.regime.reason == "sleep"
    assert snap(rig)["lock_regime_episode_saw_empty"] is True


@pytest.mark.asyncio
async def test_boot_rebuild_away_locked_taints():
    """_boot_rebuild: a lock found locked while the house reads away is an
    excursion; with no ARRIVING edge ever seen, a later HOME_* at the boot
    recheck is held."""
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig.regime.reason == "boot_unknown"
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    rig.mgr.house_state = "home_night"  # silent change, no edge
    await rig.w.advance(121)
    assert rig.unlocks() == []
    assert rig.regime.last_action["decision"] == "house_edge_ignored"


@pytest.mark.asyncio
async def test_boot_rebuild_away_then_arriving_home_night_edge_held():
    """Plan D1 H2 AC: restart with house away + lockout locked; a dispatched
    arriving -> home_night edge (no ARRIVING edge seen) -> house_edge_ignored;
    the boot recheck at 120 s -> house_edge_ignored; 0 unlocks."""
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig.w.advance(30)
    await hs(rig, "home_night", old="arriving")
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    await rig.w.advance(91)
    assert rig.regime.last_action["decision"] == "house_edge_ignored"
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_boot_recheck_arriving_never_releases_even_resident_home():
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         persons={EZ: "home", OJI: "home"})
    rig.mgr.house_state = "arriving"
    await rig.w.advance(121)
    assert rig.unlocks() == []
    assert rig.regime.last_action["decision"] == "house_edge_ignored"
    assert rig.regime.last_action["arrival_since_setup"] is False


@pytest.mark.asyncio
async def test_boot_recheck_arriving_taints_later_home_star_held():
    """H1 / F5: the house was awake at boot (no rebuild taint) and reads
    ARRIVING at the recheck; the recheck taints (and persists it), so a HOME_*
    seen only after a second restart is still held."""
    store = DictStore()
    opts = options(security_lockout_engage_on_guest_sleep=False)
    rig = await make_rig(start=BOOT_0200, house="home_night", lockouts="locked",
                         past_boot=False, store=store, opts=opts)
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    rig.mgr.house_state = "arriving"  # boot settle swallowed the edges
    await rig.w.advance(121)
    assert rig.regime.last_action["decision"] == "house_edge_ignored"
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    assert store.data["garage_episode_saw_empty"] is True
    rig2 = await make_rig(start=BOOT_0200 + timedelta(minutes=10), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)), opts=opts)
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"


@pytest.mark.asyncio
@pytest.mark.parametrize("house", ["sleep", "vacation"])
async def test_boot_recheck_sleep_vacation_rebuild_clears_taint(house):
    """_on_boot_recheck turning BOOT_UNKNOWN into SLEEP / VACATION starts that
    episode: the boot-away taint ends."""
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    rig.mgr.house_state = house
    await rig.w.advance(121)
    assert rig.regime.reason == house
    assert snap(rig)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("house", ["sleep", "vacation"])
async def test_boot_rebuild_sleep_vacation_clears_restored_taint(house):
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    assert store.data["garage_episode_saw_empty"] is True
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house=house,
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    assert rig2.regime.reason == house
    assert snap(rig2)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
async def test_taint_persisted_across_restart_two_rigs():
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    assert store.data["garage_episode_saw_empty"] is True
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    # Fix-up D-H1: the persisted engage reason is rebuilt (was boot_unknown).
    assert rig2.regime.reason == "sleep"
    assert snap(rig2)["lock_regime_episode_saw_empty"] is True
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"


@pytest.mark.asyncio
async def test_manual_unlock_memory_survives_arriving():
    store = DictStore()
    rig = await make_rig(store=store)
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unlocked")  # human unlock
    assert rig.regime.manual_unlock_reason == "sleep"
    await rig.edge("away")
    await rig.edge("arriving")
    assert rig.regime.manual_unlock_reason == "sleep"
    await rig.edge("home_night")  # tainted HOME_*
    assert rig.regime.manual_unlock_reason == "sleep"
    assert store.data["garage_manual_unlock"] == "sleep"


@pytest.mark.asyncio
async def test_manual_unlock_memory_survives_tainted_boot_recheck():
    store = DictStore()
    rig1 = await make_rig(store=store)
    await rig1.edge("sleep")
    rig1.w.set_state(LOCK_A, "unlocked")
    await rig1.edge("away")
    await rig1.edge("arriving")
    assert store.data["garage_manual_unlock"] == "sleep"

    def hook(w):
        w.seed(LOCK_A, "unlocked")

    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)), seed_hook=hook)
    await rig2.w.advance(121)
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"
    assert rig2.regime.manual_unlock_reason == "sleep"


@pytest.mark.asyncio
async def test_guest_clock_clears_taint():
    """M3 stale-flag repro: VACATION -> ARRIVING -> HOME_DAY -> GUEST, the
    guest clock engages GUEST_NIGHT (new episode, saw-empty cleared). Step 1a:
    next morning's default-trigger HOME_DAY is ignored; the backstop releases."""
    rig = await make_rig(start=datetime(2026, 11, 7, 20, 0, tzinfo=TZ), house="away",
                         opts=options(security_lockout_engage_on_guest_sleep=True))
    await rig.edge("vacation")
    await rig.edge("arriving")
    await rig.edge("home_day")
    await rig.edge("guest")
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    await rig.w.advance(
        (datetime(2026, 11, 7, 22, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.regime.reason == "guest_night"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    assert rig.unlocks() == []
    await rig.w.advance(
        (datetime(2026, 11, 8, 6, 30, tzinfo=TZ) - rig.w.now).total_seconds())
    await rig.edge("home_day")
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    await rig.w.advance(
        (datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"


async def _site_sc_disable(rig):
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    await rig.regime.async_release_if_disabled()


async def _site_hazard(rig):
    rig.regime.on_hazard()
    await settle()


async def _site_kill_switch(rig):
    rig.regime.on_kill_switch_changed(False)
    await settle()


async def _site_after_release(rig):
    await rig.edge("waking")  # house_state:waking release -> _after_release


async def _site_vacation_arrival(rig):
    await rig.person(EZ, "home")


@pytest.mark.asyncio
@pytest.mark.parametrize("site", [
    "sc_disable", "hazard", "kill_switch", "after_release", "vacation_arrival",
])
async def test_every_reason_none_site_clears_flags(site):
    store = DictStore()
    if site == "vacation_arrival":
        rig = await make_rig(house="away", store=store)
        await rig.edge("vacation")
        await rig.edge("arriving")
    else:
        rig = await make_rig(store=store)
        await tainted_sleep_episode(rig)
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    assert store.data["garage_episode_saw_empty"] is True
    await {
        "sc_disable": _site_sc_disable,
        "hazard": _site_hazard,
        "kill_switch": _site_kill_switch,
        "after_release": _site_after_release,
        "vacation_arrival": _site_vacation_arrival,
    }[site](rig)
    assert rig.regime.reason == "none"
    s = snap(rig)
    assert s["lock_regime_episode_saw_empty"] is False
    assert store.data["garage_episode_saw_empty"] is False
    assert "garage_arrival_taint" not in store.data


@pytest.mark.asyncio
async def test_boot_guest_night_rebuild_keeps_taint():
    """R2-1 repro: GUEST_NIGHT episode, GUEST -> AWAY -> ARRIVING (saw-empty)
    -> HOME_NIGHT (guest_yield_hold); restart; the boot recheck rebuilds
    GUEST_NIGHT and keeps the flag; next morning HOME_DAY is ignored."""
    store = DictStore()
    rig1 = await make_rig(store=store,
                          opts=options(security_lockout_engage_on_guest_sleep=True))
    await rig1.edge("guest")
    assert rig1.regime.reason == "guest_night"
    assert rig1.locks() == [LOCK_A, LOCK_B]
    await rig1.edge("away")
    await rig1.edge("arriving")
    await rig1.edge("home_night")
    assert rig1.regime.last_action["action"] == "guest_yield_hold"
    rig2 = await make_rig(start=datetime(2026, 11, 8, 1, 0, tzinfo=TZ), house="home_night",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)),
                          opts=options(security_lockout_engage_on_guest_sleep=True))
    await rig2.w.advance(121)
    assert rig2.regime.reason == "guest_night"
    s = snap(rig2)
    assert s["lock_regime_episode_saw_empty"] is True
    await rig2.w.advance(
        (datetime(2026, 11, 8, 6, 30, tzinfo=TZ) - rig2.w.now).total_seconds())
    await rig2.edge("home_day")
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["action"] == "house_edge_ignored"


@pytest.mark.asyncio
async def test_boot_nothing_locked_clears_stale_taint():
    """R2-4 repro: SLEEP episode that saw an empty house, resident person
    release (flag kept), restart with nothing locked -> flag cleared; the
    operator hand-locks; restart with house home_day -> step 1a (delta L2):
    the boot recheck ignores the awake house (house_edge_ignored), the morning
    backstop owns the release."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    await rig1.person(EZ, "home")
    assert rig1.unlocks() == [LOCK_A, LOCK_B]
    assert store.data["garage_episode_saw_empty"] is True
    store2 = DictStore(dict(store.data))
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_night",
                          lockouts="unlocked", past_boot=False, store=store2,
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig2)["lock_regime_episode_saw_empty"] is False
    assert store2.data["garage_episode_saw_empty"] is False
    rig3 = await make_rig(start=BOOT_0200 + timedelta(days=1, minutes=30),
                          house="home_day", lockouts="locked", past_boot=False,
                          store=DictStore(dict(store2.data)),
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig3)["lock_regime_episode_saw_empty"] is False
    await rig3.w.advance(121)
    assert rig3.unlocks() == []
    assert rig3.regime.last_action["decision"] == "house_edge_ignored"


@pytest.mark.asyncio
async def test_override_set_bypasses_taint():
    rig = await make_rig()
    await tainted_sleep_episode(rig)
    await hs(rig, "home_day", trigger="override_set")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "house_state:home_day"
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_override_set_arriving_releases_without_taint():
    rig = await make_rig()
    await rig.edge("sleep")
    await rig.edge("away")
    await hs(rig, "arriving", trigger="override_set")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "house_state:arriving"
    s = snap(rig)
    assert rig.regime.reason == "none"
    assert s["lock_regime_episode_saw_empty"] is False  # episode ended
    assert s["lock_regime_house_edges_ignored"] == 0


@pytest.mark.asyncio
async def test_reason_none_arriving_no_unlock():
    """F19: reason NONE + lockouts locked by hand + ARRIVING -> 0 unlocks."""
    rig = await make_rig(house="away")
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    assert rig.regime.reason == "none"
    await rig.edge("arriving")
    assert rig.unlocks() == []
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    assert snap(rig)["lock_regime_house_edges_ignored"] == 0


@pytest.mark.asyncio
async def test_guest_yield_hold_unchanged_with_taint():
    rig = await make_rig(opts=options(security_lockout_engage_on_guest_sleep=True))
    await rig.edge("guest")
    await rig.edge("away")
    await rig.edge("arriving")
    await rig.edge("home_night")
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "guest_yield_hold"
    assert rig.regime.reason == "guest_night"


@pytest.mark.asyncio
async def test_override_guest_night_to_home_night_from_arriving_no_taint():
    """C-2 (step 1a delta M2 flips it): an override GUEST-night -> HOME_NIGHT
    edge whose old_state is arriving is still evidence the house was empty, so
    ``_episode_saw_empty`` is set (not gated on operator; it only pages). The
    edge itself is guest_yield_hold, no release."""
    rig = await make_rig(opts=options(security_lockout_engage_on_guest_sleep=True))
    await rig.edge("guest")
    assert rig.regime.reason == "guest_night"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    await hs(rig, "home_night", old="arriving", trigger="override_set")
    assert rig.regime.last_action["action"] == "guest_yield_hold"
    assert rig.unlocks() == []
    assert snap(rig)["lock_regime_episode_saw_empty"] is True


# ----------------------------------------------------------------------------
# Replays (F21): audit §7 (a) and (b) through the real regime
# ----------------------------------------------------------------------------


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _collect_releases(rig) -> list[tuple[str, list[str]]]:
    """Observe (trigger, written) of every garage release record."""
    seen: list[tuple[str, list[str]]] = []
    real = rig.regime._record

    def spy(action, *, trigger, written, extra=None, policy="garage_lockout"):
        if action == "release" and policy == "garage_lockout":
            seen.append((trigger, list(written)))
        return real(action, trigger=trigger, written=written, extra=extra, policy=policy)

    rig.regime._record = spy
    return seen


async def _replay_house(rig, edges, *, skip=frozenset()) -> None:
    for _id, utc, old, new in edges:
        if new in skip:
            continue
        target = _utc(utc).astimezone(TZ)
        if target > rig.w.now:
            await rig.w.advance((target - rig.w.now).total_seconds())
        await hs(rig, new, old=old)


@pytest.mark.asyncio
@pytest.mark.parametrize("cluster", ["cluster_a", "cluster_8623"])
async def test_replay_body_only_cluster_zero_house_releases(cluster):
    """Audit §7 (a): the 10-14..10-18 body-only cluster and edge 8623.

    Pass 1 (forced worst case): the lockout engaged for VACATION and every
    away / arriving / home_* / guest edge of the cluster replayed -> 0 unlocks.
    Pass 2 (as recorded, every edge incl. sleep / waking): no release on a
    house_state:arriving / home_* / guest trigger; WAKING (after a SLEEP
    engage) and the backstop are the only house-side releases."""
    fx = json.loads(FIXTURE.read_text())
    edges = fx[cluster]
    first = _utc(edges[0][1]).astimezone(TZ) - timedelta(minutes=20)

    rig = await make_rig(start=first, house="away")
    seen = _collect_releases(rig)
    await rig.edge("vacation")
    assert rig.locks() == [LOCK_A, LOCK_B]
    # From the first AWAY edge on (an untainted HOME_* before any excursion
    # would be an ordinary end of the VACATION episode).
    k = next(i for i, e in enumerate(edges) if e[3] == "away")
    await _replay_house(rig, edges[k:], skip={"sleep", "waking", "vacation"})
    assert rig.unlocks() == []
    assert [t for t, w in seen if w] == []
    assert rig.regime.reason == "vacation"

    rig2 = await make_rig(start=first, house=edges[0][2])
    seen2 = _collect_releases(rig2)
    await _replay_house(rig2, edges)
    triggers = {t for t, w in seen2 if w}
    assert triggers <= {"house_state:waking", "backstop"}, triggers
    if cluster == "cluster_a":
        assert rig2.locks()  # the nightly SLEEP engages really happened


@pytest.mark.asyncio
async def test_replay_real_arrivals_release_by_person():
    """Audit §7 (b): the 17 exact real arrivals 8545-8632, each replayed in an
    engaged (VACATION) episode with the residents' measured tracker lags
    (negative = edge before ARRIVING). Each releases by person:* within 60 s
    of ARRIVING, never by a house-state trigger."""
    fx = json.loads(FIXTURE.read_text())
    for arr in fx["real_b"]:
        t_arr = _utc(arr["arriving_utc"]).astimezone(TZ)
        t_next = _utc(arr["next_utc"]).astimezone(TZ)
        events = [(t_arr, "house", "arriving"), (t_next, "house", arr["next_state"])]
        for person, lag in arr["resident_edges"]:
            events.append((t_arr + timedelta(seconds=lag), "person", f"person.{person}"))
        events.sort(key=lambda e: e[0])
        start = min(e[0] for e in events) - timedelta(minutes=30)
        residents = {f"person.{p}": "not_home" for p, _ in arr["resident_edges"]}
        residents.setdefault(EZ, "not_home")
        residents.setdefault(OJI, "not_home")
        rig = await make_rig(start=start, house="away", persons=residents)
        seen = _collect_releases(rig)
        await rig.edge("vacation")
        assert rig.locks() == [LOCK_A, LOCK_B], arr["id"]
        await rig.edge("away")
        unlock_at = None
        for when, kind, what in events:
            if when > rig.w.now:
                await rig.w.advance((when - rig.w.now).total_seconds())
            if kind == "house":
                await hs(rig, what)
            else:
                await rig.person(what, "home")
            if unlock_at is None and rig.unlocks():
                unlock_at = rig.w.now
        written = [(t, w) for t, w in seen if w]
        assert len(written) == 1, (arr["id"], written)
        assert written[0][0].startswith("person:"), (arr["id"], written)
        assert unlock_at is not None
        assert (unlock_at - t_arr).total_seconds() <= 60, arr["id"]


# ============================================================================
# §8 config extremes / combinations (D1 rows)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", [0, 60])
@pytest.mark.parametrize("order", ["edge_first", "arriving_first"])
async def test_extreme_hold_0_and_60_inv_real(hold, order):
    rig = await make_rig(opts=options(garage_lockout_arrival_hold_s=hold))
    await rig.edge("sleep")
    await rig.edge("away")
    if order == "arriving_first":
        await rig.edge("arriving")
    stale_home(rig, EZ, "device_tracker.ez_ipad")
    await settle()
    if hold == 0:
        assert rig.unlocks() == [LOCK_A, LOCK_B]  # at the edge
        assert rig.regime.last_action["trigger"] == "person:person.ezinne"
        if order == "edge_first":
            await rig.edge("arriving")
            assert rig.unlocks() == [LOCK_A, LOCK_B]
        return
    if order == "edge_first":
        await rig.edge("arriving")
    await rig.w.advance(59.9)
    assert rig.unlocks() == []
    await rig.w.advance(0.2)
    assert rig.unlocks() == [LOCK_A, LOCK_B]  # at edge + 60 s
    assert rig.regime.last_action["trigger"] == "person:person.ezinne"


@pytest.mark.asyncio
async def test_extreme_everyone_excluded_sleep_backstop_only():
    rig = await make_rig(opts=options(
        security_lockout_excluded_persons=[EZ, OJI, "person.wall_kiosk"]))
    await tainted_sleep_episode(rig)
    await rig.edge("home_night")
    await rig.person(EZ, "home")
    assert rig.unlocks() == []
    await rig.w.advance(
        (datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"


@pytest.mark.asyncio
async def test_extreme_everyone_excluded_vacation_only_switch_releases():
    """L5: VACATION has no backstop; with no residents nothing releases a
    tainted episode until the kill switch (or hazard / override)."""
    rig = await make_rig(house="away", opts=options(
        security_lockout_excluded_persons=[EZ, OJI, "person.wall_kiosk"]))
    await rig.edge("vacation")
    await rig.edge("arriving")
    await rig.person(EZ, "home")
    for new in ("home_day", "home_evening", "home_night"):
        await rig.w.advance(12 * 3600)
        await rig.edge(new)
    assert rig.unlocks() == []
    rig.regime.on_kill_switch_changed(False)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_extreme_vacation_chain_released_by_waking_after_sleep():
    """F12b: VACATION -> ARRIVING -> HOME_* (held) -> SLEEP (new episode) ->
    WAKING releases."""
    rig = await make_rig(start=datetime(2026, 11, 7, 18, 0, tzinfo=TZ), house="away")
    await rig.edge("vacation")
    await rig.edge("arriving")
    await rig.edge("home_evening")
    await rig.edge("home_night")
    assert rig.unlocks() == []
    await rig.w.advance(
        (datetime(2026, 11, 7, 23, 30, tzinfo=TZ) - rig.w.now).total_seconds())
    await rig.edge("sleep")
    assert rig.regime.reason == "sleep"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    await rig.w.advance(
        (datetime(2026, 11, 8, 6, 10, tzinfo=TZ) - rig.w.now).total_seconds())
    await rig.edge("waking")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "house_state:waking"


@pytest.mark.asyncio
async def test_extreme_boot_unknown_arriving_held_backstop_releases():
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig.regime.reason == "boot_unknown"
    await rig.edge("arriving")
    await rig.edge("home_night")
    assert rig.unlocks() == []
    await rig.w.advance(
        (datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"


@pytest.mark.asyncio
async def test_extreme_kill_switch_off_in_tainted_episode_releases_once():
    rig = await make_rig()
    await tainted_sleep_episode(rig)
    rig.regime.on_kill_switch_changed(False)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "none"
    assert snap(rig)["lock_regime_episode_saw_empty"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [0, 900, 7200])
async def test_extreme_reengage_delay_after_night_person_release_then_arriving(delay):
    rig = await make_rig(opts=options(garage_lockout_reengage_delay_s=delay))
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.edge("arriving")
    assert snap(rig)["lock_regime_episode_saw_empty"] is True
    if delay == 0:
        assert rig.regime._reengage_unsub is None
        return
    assert rig.regime._reengage_unsub is not None  # ARRIVING did not cancel it
    await rig.w.advance(delay - 1)
    assert rig.regime._reengage_unsub is not None
    await rig.w.advance(2)
    assert rig.locks() == [LOCK_A, LOCK_B]  # only the original engage
    assert rig.regime.last_action["action"] == "reengage_abandoned"
    assert rig.regime.last_action["why"] == "house_not_sleep"
    assert snap(rig)["lock_regime_episode_saw_empty"] is True


@pytest.mark.asyncio
async def test_extreme_arriving_away_flap_x5_then_resident_edge():
    rig = await make_rig()
    await rig.edge("sleep")
    for _ in range(5):
        await rig.edge("away")
        await rig.w.advance(30)
        await rig.edge("arriving")
        await rig.w.advance(60)
    assert rig.unlocks() == []
    assert snap(rig)["lock_regime_house_edges_ignored"] == 5
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


# ============================================================================
# D3 — trip-wire: an unlock on a house-state trigger in a tainted episode pages
# ============================================================================


class FakeNM:
    def __init__(self):
        self.sent: list[dict] = []

    async def async_notify(self, **kw):
        self.sent.append(kw)

    def of(self, hazard_type: str) -> list[dict]:
        return [k for k in self.sent if k.get("hazard_type") == hazard_type]


def install_nm(rig) -> FakeNM:
    nm = FakeNM()
    rig.w.hass.data[const.DOMAIN]["notification_manager"] = nm
    return nm


def bypass_gate(monkeypatch, rig, *houses: str) -> None:
    """Seam (plan §7, F17): _edge_decision mutated back to 'release' for the
    named house states; everything else is the real decision."""
    real = rig.regime._edge_decision

    def patched(new, cfg, *, operator=False):
        if new in houses:
            return "release", None
        return real(new, cfg, operator=operator)

    monkeypatch.setattr(rig.regime, "_edge_decision", patched)


UNCORR = "lock_release_uncorroborated"


@pytest.mark.asyncio
async def test_tripwire_fires_on_house_state_unlock_when_gate_bypassed(monkeypatch):
    rig = await make_rig()
    nm = install_nm(rig)
    bypass_gate(monkeypatch, rig, "arriving")
    await tainted_sleep_episode(rig)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]  # observes, never blocks
    pages = nm.of(UNCORR)
    assert len(pages) == 1
    assert int(pages[0]["severity"]) == 3  # Severity.HIGH
    assert pages[0]["location"] == "garage_lockout:house_state"
    assert "house_state:arriving" in pages[0]["message"]
    assert "sleep" in pages[0]["message"]
    assert "away -> arriving" in pages[0]["message"]
    assert snap(rig)["lock_regime_uncorroborated_releases"] == 1


@pytest.mark.asyncio
async def test_tripwire_silent_on_real_arrival_chain():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    await rig.edge("arriving")
    await rig.edge("home_night")
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert nm.sent == []
    assert snap(rig)["lock_regime_uncorroborated_releases"] == 0


@pytest.mark.asyncio
async def test_tripwire_silent_when_nothing_written(monkeypatch):
    rig = await make_rig()
    nm = install_nm(rig)
    bypass_gate(monkeypatch, rig, "arriving")
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unlocked")  # human unlocks both
    rig.w.set_state(LOCK_B, "unlocked")
    await rig.edge("away")
    await rig.edge("arriving")
    await settle()
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "release"
    assert nm.of(UNCORR) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boot_house", ["arriving", "home_day"])
async def test_tripwire_covers_boot_recheck_channel_two_rigs(monkeypatch, boot_house):
    """Boot channel: rig 2 boots with the boot house_edge_ignored mutated to a
    release -> one page (step 1a: the trip-wire reads only the trigger and the
    operator flag, never an episode flag or ``_edge_decision``)."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house=boot_house,
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    nm = install_nm(rig2)
    bypass_gate(monkeypatch, rig2, boot_house)
    await rig2.w.advance(121)
    assert rig2.unlocks() == [LOCK_A, LOCK_B]
    assert rig2.regime.last_action["trigger"] == "boot_recheck"
    pages = nm.of(UNCORR)
    assert len(pages) == 1
    assert "boot_recheck" in pages[0]["message"]


@pytest.mark.asyncio
async def test_tripwire_waking_and_override_exempt():
    rig = await make_rig()
    nm = install_nm(rig)
    await tainted_sleep_episode(rig)
    await rig.edge("waking")  # saw flag set, WAKING exempt
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert nm.of(UNCORR) == []

    rig2 = await make_rig()
    nm2 = install_nm(rig2)
    await tainted_sleep_episode(rig2)
    await hs(rig2, "home_day", trigger="override_set")
    await settle()
    assert rig2.unlocks() == [LOCK_A, LOCK_B]
    assert nm2.of(UNCORR) == []


@pytest.mark.asyncio
async def test_tripwire_disabled_by_constant(monkeypatch):
    monkeypatch.setattr(const, "LOCK_RELEASE_UNCORROBORATED_TRIPWIRE_ENABLED", False)
    rig = await make_rig()
    nm = install_nm(rig)
    await tainted_sleep_episode(rig)  # D1 unaffected: held
    assert rig.unlocks() == []
    bypass_gate(monkeypatch, rig, "home_night")
    await rig.edge("home_night")
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert nm.of(UNCORR) == []
    assert snap(rig)["lock_regime_uncorroborated_releases"] == 0


@pytest.mark.asyncio
async def test_tripwire_silent_on_untainted_house_state_release():
    """Step 1a: a default-trigger HOME_* edge in an episode that never saw an
    empty house is ignored (no release, no page); an operator override_clear
    HOME_* edge releases and must not page (operator conjunct)."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("home_day")
    await settle()
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    await hs(rig, "home_day", trigger="override_clear")
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "house_state:home_day"
    assert nm.of(UNCORR) == []


# ============================================================================
# D4 — trip-wire: a resident arrived (or came back uncounted), lockout locked
# ============================================================================

AFTER = "lockout_locked_after_arrival"
UNCOUNTED = "lockout_locked_resident_uncounted_return"
FAILED = "lockout_release_failed"


def neuter_s1(monkeypatch, rig) -> None:
    """Seam: the S1 person release call does nothing (only person:* triggers)."""
    real = rig.regime._release

    def patched(trigger, **kw):
        if trigger.startswith("person:"):
            return None
        return real(trigger, **kw)

    monkeypatch.setattr(rig.regime, "_release", patched)


async def departure_unseen(rig, pid: str) -> None:
    """A real home reading (so _last_real = home, not restored), then the phone
    drops to unavailable: the departure is never seen."""
    await rig.person(pid, "home")
    await rig.w.advance(120)  # any D4a check from this edge resolves
    await rig.person(pid, "unavailable")


@pytest.mark.asyncio
async def test_still_locked_after_arrival_pages(monkeypatch):
    rig = await make_rig()
    nm = install_nm(rig)
    neuter_s1(monkeypatch, rig)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == []
    await rig.w.advance(89.9)
    assert nm.of(AFTER) == []
    await rig.w.advance(0.2)
    pages = nm.of(AFTER)
    assert sorted(p["location"] for p in pages) == [
        f"garage_lockout:still_locked:{LOCK_A}", f"garage_lockout:still_locked:{LOCK_B}"]
    assert all(int(p["severity"]) == 3 for p in pages)
    assert "person.ezinne" in pages[0]["title"]
    assert snap(rig)["lock_regime_still_locked_pages"] == 2


@pytest.mark.asyncio
async def test_still_locked_silent_after_unlock():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(91)
    assert nm.sent == []


@pytest.mark.asyncio
async def test_still_locked_silent_after_later_engage():
    """F2 repro: reason NONE, lockouts unlocked, resident edge at T; a SLEEP
    engage at T+30 locks -> no page at T+90 (we locked them)."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.person(EZ, "home")
    await rig.w.advance(30)
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.w.advance(61)
    assert nm.of(AFTER) == []


@pytest.mark.asyncio
async def test_still_locked_engage_seq_guard_without_last_changed():
    """engage_seq alone (no usable State.last_changed on the lock): our own
    engage after the arrival silences the check."""
    rig = await make_rig()
    nm = install_nm(rig)
    rig.w.apply_service_state = False

    def land_without_stamp(domain, service, eid):
        if domain == "lock" and service == "lock":
            rig.w.seed(eid, "locked")  # last_changed None

    rig.w.call_hooks.append(land_without_stamp)
    await rig.person(EZ, "home")
    await rig.w.advance(30)
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.w.advance(61)
    assert nm.of(AFTER) == []


@pytest.mark.asyncio
async def test_still_locked_not_silenced_by_second_resident_release():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.person(OJI, "not_home")
    await rig.edge("away")
    rig.sc.enabled = False  # S1 cannot unlock (SC not alive)
    await rig.person(EZ, "home")  # T
    await rig.w.advance(30)
    await rig.person(OJI, "home")  # T+30, a second resident
    await rig.w.advance(61)  # T+91
    assert rig.unlocks() == []
    assert len(nm.of(AFTER)) == 2  # EZ's check fired: one page per lock


@pytest.mark.asyncio
async def test_still_locked_one_page_per_lock_two_residents():
    """R2-7: two residents in one car, S1 cannot unlock -> one page per lock,
    not per resident; a later D4b check in the same engage episode for the
    same lock does not page again."""
    rig = await make_rig(persons={EZ: "not_home", OJI: "home", JAYA: "not_home"})
    nm = install_nm(rig)
    await rig.person(OJI, "not_home")
    await departure_unseen(rig, JAYA)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.sc.enabled = False
    await rig.person(EZ, "home")
    await rig.w.advance(1)
    await rig.person(OJI, "home")
    await rig.w.advance(120)
    assert len(nm.of(AFTER)) == 2
    assert sorted(p["location"] for p in nm.of(AFTER)) == [
        f"garage_lockout:still_locked:{LOCK_A}", f"garage_lockout:still_locked:{LOCK_B}"]
    await rig.person(JAYA, "home")  # D4b, same engage episode
    assert snap(rig)["lock_regime_uncounted_returns"] == 1
    await rig.w.advance(91)
    assert nm.of(UNCOUNTED) == []
    assert snap(rig)["lock_regime_still_locked_pages"] == 2


@pytest.mark.asyncio
async def test_still_locked_dedups_release_failed_nm():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.w.apply_service_state = False  # unlocks never land
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert sorted(p["location"] for p in nm.of(FAILED)) == [
        f"garage:{LOCK_A}", f"garage:{LOCK_B}"]
    assert nm.of(AFTER) == []


@pytest.mark.asyncio
async def test_still_locked_skips_human_relock_in_window():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(40)
    rig.w.set_state(LOCK_A, "locked")  # a human re-locks, not URA
    await rig.w.advance(51)
    assert nm.of(AFTER) == []


@pytest.mark.asyncio
async def test_still_locked_never_left_locked_pages(monkeypatch):
    """The R2-7 counterpart: the lock never left `locked` -> one page per lock."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.sc.enabled = False
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert len(nm.of(AFTER)) == 2


@pytest.mark.asyncio
async def test_uncounted_return_pages_when_house_away():
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")  # unavailable -> home, rejected (_last_real home)
    assert rig.unlocks() == []
    assert rig.regime.last_action["action"] == "arrival_uncounted"
    await rig.w.advance(89.9)
    assert nm.of(UNCOUNTED) == []
    await rig.w.advance(0.2)
    pages = nm.of(UNCOUNTED)
    assert len(pages) == 2
    assert "may be locked out" in pages[0]["title"]
    assert snap(rig)["lock_regime_uncounted_returns"] == 1


@pytest.mark.asyncio
async def test_uncounted_return_silent_when_house_home_untainted():
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    rig.mgr.house_state = "home_night"  # no edge: engaged, untainted, awake read
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert nm.sent == []
    assert snap(rig)["lock_regime_uncounted_returns"] == 0


@pytest.mark.asyncio
async def test_uncounted_return_pages_late_reconnect_tainted_home():
    """R2-3: the phone rejoins after ARRIVING has advanced to HOME_*."""
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await tainted_sleep_episode(rig)
    await rig.edge("home_night")
    assert rig.mgr.house_state == "home_night"
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert len(nm.of(UNCOUNTED)) == 2


@pytest.mark.asyncio
async def test_uncounted_return_silent_when_reason_none():
    rig = await make_rig(house="away")
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    rig.w.set_state(LOCK_A, "locked")
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert nm.sent == []
    assert snap(rig)["lock_regime_uncounted_returns"] == 0


@pytest.mark.asyncio
async def test_uncounted_page_disabled_by_constant(monkeypatch):
    monkeypatch.setattr(const, "LOCK_RELEASE_UNCOUNTED_RETURN_PAGE_ENABLED", False)
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert nm.of(UNCOUNTED) == []
    assert snap(rig)["lock_regime_uncounted_returns"] == 0
    # D4a unaffected.
    neuter_s1(monkeypatch, rig)
    await rig.person(OJI, "not_home")
    await rig.person(OJI, "home")
    await rig.w.advance(91)
    assert len(nm.of(AFTER)) == 2


@pytest.mark.asyncio
async def test_still_locked_cancelled_on_teardown(monkeypatch):
    rig = await make_rig()
    nm = install_nm(rig)
    neuter_s1(monkeypatch, rig)
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    pending = [t for t in rig.w.live_timers() if t["delay"] == 90.0]
    assert len(pending) == 1
    await rig.regime.async_teardown()
    assert pending[0]["cancelled"] is True
    await rig.w.advance(91)
    assert nm.of(AFTER) == []


@pytest.mark.asyncio
async def test_still_locked_window_zero_disables(monkeypatch):
    monkeypatch.setattr(const, "LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S", 0)
    rig = await make_rig()
    nm = install_nm(rig)
    neuter_s1(monkeypatch, rig)
    await departure_unseen(rig, OJI)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    await rig.person(OJI, "home")
    await rig.w.advance(3600)
    assert nm.sent == []
    assert snap(rig)["lock_regime_uncounted_returns"] == 0
    assert rig.regime._still_locked_unsubs == {}


def test_still_locked_bound_exceeds_readback_chain():
    """F3 / H3b: the page waits out the read-back chain plus >= 30 s for two
    blocking unlock calls (a cross-constant invariant, so constants are read)."""
    assert (
        const.LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S
        - const.GARAGE_LOCKOUT_READBACK_S * (const.GARAGE_LOCKOUT_READBACK_RETRIES + 1)
        >= 30
    )


@pytest.mark.asyncio
async def test_still_locked_anchor_after_hold(monkeypatch):
    """§8: hold = 60 (Number max): the check is anchored at the S1 call
    (edge + 60), so it fires at edge + 150, not edge + 90."""
    rig = await make_rig(opts=options(garage_lockout_arrival_hold_s=60))
    nm = install_nm(rig)
    neuter_s1(monkeypatch, rig)
    await rig.edge("sleep")
    await rig.edge("away")
    stale_home(rig, EZ, "device_tracker.ez_ipad")
    await settle()
    await rig.w.advance(149.9)
    assert nm.of(AFTER) == []
    await rig.w.advance(0.2)
    assert len(nm.of(AFTER)) == 2


@pytest.mark.asyncio
async def test_everyone_excluded_trip_wires_silent():
    rig = await make_rig(opts=options(
        security_lockout_excluded_persons=[EZ, OJI, "person.wall_kiosk"]))
    nm = install_nm(rig)
    await tainted_sleep_episode(rig)
    await rig.person(EZ, "home")
    await rig.w.advance(3600)
    assert nm.sent == []


@pytest.mark.asyncio
async def test_uncounted_return_silent_when_kill_switch_off():
    """Kill switch read live (an options edit with no switch callback):
    no D4b record, no page."""
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = False
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert nm.sent == []
    assert snap(rig)["lock_regime_uncounted_returns"] == 0


@pytest.mark.asyncio
async def test_still_locked_silent_when_kill_switch_off_at_fire(monkeypatch):
    rig = await make_rig()
    nm = install_nm(rig)
    neuter_s1(monkeypatch, rig)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    rig.w.cm_entry.options["security_garage_lockout_enabled"] = False
    await rig.w.advance(91)
    assert nm.of(AFTER) == []


@pytest.mark.asyncio
async def test_still_locked_reschedule_cancels_prior_check(monkeypatch):
    """A second edge for the same person replaces its pending check (one
    handle per person; no orphan timer that teardown could not cancel)."""
    rig = await make_rig()
    neuter_s1(monkeypatch, rig)
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    await rig.w.advance(10)
    await rig.person(EZ, "not_home")
    await rig.person(EZ, "home")
    live = [t for t in rig.w.live_timers() if t["delay"] == 90.0]
    assert len(live) == 1


# ============================================================================
# Fix-up round (reviews A / B / D): v_lock_release_arriving_{A,B,D}.md
# ============================================================================

BOOT_GAP = "lockout_locked_boot_gap_return"


# --- A-1 / B-H1 / D-M1: an availability return is not a human re-lock -------


@pytest.mark.asyncio
async def test_still_locked_pages_lock_unavailable_at_arrival_back_locked():
    """A-1 / D-M1 repro: LOCK_A unavailable at the S1 call (skipped), back
    `locked` at +20 s -> one page for LOCK_A at +90 s (was silenced by the
    last_changed > anchor skip)."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unavailable")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_B]
    await rig.w.advance(20)
    rig.w.set_state(LOCK_A, "locked")
    await rig.w.advance(69.9)
    assert nm.of(AFTER) == []
    await rig.w.advance(0.2)
    pages = nm.of(AFTER)
    assert [p["location"] for p in pages] == [f"garage_lockout:still_locked:{LOCK_A}"]
    assert "still reads locked" in pages[0]["message"]


@pytest.mark.asyncio
async def test_still_locked_tainted_home_night_lock_back_after_30s():
    """B-H1 repro: tainted SLEEP episode, LOCK_A unavailable, Ezinne home
    (S1 unlocks LOCK_B only), +30 s LOCK_A reads locked, HOME_NIGHT held,
    +90 s -> one page for LOCK_A."""
    rig = await make_rig()
    nm = install_nm(rig)
    await tainted_sleep_episode(rig)
    rig.w.set_state(LOCK_A, "unavailable")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_B]
    await rig.w.advance(30)
    rig.w.set_state(LOCK_A, "locked")
    await rig.edge("home_night")
    assert rig.regime.last_action["action"] == "house_edge_ignored"
    await rig.w.advance(61)
    assert [p["location"] for p in nm.of(AFTER)] == [
        f"garage_lockout:still_locked:{LOCK_A}"]


@pytest.mark.asyncio
async def test_still_locked_unavailable_at_timer_rechecked_then_pages_locked():
    """B-H1 second shape: still unavailable at +90 s (no page yet, one
    re-check), back `locked` at +120 s -> page at the +180 s re-check."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unavailable")
    await rig.edge("away")
    await rig.person(EZ, "home")
    await rig.w.advance(91)
    assert nm.of(AFTER) == []
    await rig.w.advance(29)
    rig.w.set_state(LOCK_A, "locked")
    await rig.w.advance(59.8)
    assert nm.of(AFTER) == []
    await rig.w.advance(0.4)
    pages = nm.of(AFTER)
    assert [p["location"] for p in pages] == [f"garage_lockout:still_locked:{LOCK_A}"]
    assert "still reads locked" in pages[0]["message"]


@pytest.mark.asyncio
async def test_still_locked_unavailable_through_recheck_pages_unreadable():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unavailable")
    await rig.edge("away")
    await rig.person(EZ, "home")
    await rig.w.advance(181)
    pages = nm.of(AFTER)
    assert [p["location"] for p in pages] == [f"garage_lockout:still_locked:{LOCK_A}"]
    assert "unreadable" in pages[0]["title"]
    assert int(pages[0]["severity"]) == 3
    await rig.w.advance(600)
    assert len(nm.of(AFTER)) == 1  # one re-check, one page


@pytest.mark.asyncio
async def test_still_locked_unavailable_then_unlocked_silent():
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    rig.w.set_state(LOCK_A, "unavailable")
    await rig.edge("away")
    await rig.person(EZ, "home")
    await rig.w.advance(100)
    rig.w.set_state(LOCK_A, "unlocked")  # opener came back unlocked
    await rig.w.advance(100)
    assert nm.sent == []


@pytest.mark.asyncio
async def test_still_locked_readback_unavailable_then_locked_pages():
    """D-M1 second shape: the unlock is issued, the lock drops to unavailable
    (the read-back treats that as success), then returns `locked`."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.w.apply_service_state = False

    def drop(domain, service, eid):
        if domain == "lock" and service == "unlock" and eid == LOCK_A:
            rig.w.set_state(LOCK_A, "unavailable")

    rig.w.call_hooks.append(drop)
    rig.w.call_hooks.append(
        lambda d, s, e: rig.w.set_state(e, "unlocked")
        if d == "lock" and s == "unlock" and e == LOCK_B else None)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(25)  # read-back at +20 s saw unavailable
    assert nm.of(FAILED) == []
    rig.w.set_state(LOCK_A, "locked")
    await rig.w.advance(66)
    assert [p["location"] for p in nm.of(AFTER)] == [
        f"garage_lockout:still_locked:{LOCK_A}"]


@pytest.mark.asyncio
async def test_still_locked_skips_relock_via_locking():
    """A real re-lock that passes through `locking` is still skipped."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(40)
    rig.w.set_state(LOCK_A, "locking")
    rig.w.set_state(LOCK_A, "locked")
    await rig.w.advance(51)
    assert nm.of(AFTER) == []


# --- B-L1: phone flaps do not postpone the page ------------------------------


@pytest.mark.asyncio
async def test_still_locked_flaps_after_counted_arrival_do_not_postpone():
    """B-L1 repro: counted arrival (S1 cannot unlock), then 4 flaps 60 s
    apart. The arrival check pages at +90 s with arrival wording; the flaps'
    uncounted check never adds a page with the wrong text."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("away")
    rig.sc.enabled = False
    await rig.person(EZ, "home")  # T
    await rig.w.advance(60)
    await rig.person(EZ, "unavailable")
    await rig.person(EZ, "home")  # flap 1, T+60 (uncounted)
    assert snap(rig)["lock_regime_uncounted_returns"] == 1
    await rig.w.advance(31)  # T+91
    pages = nm.of(AFTER)
    assert len(pages) == 2
    assert all(p["title"].startswith("Garage still locked after") for p in pages)
    for _ in range(3):
        await rig.w.advance(29)
        await rig.person(EZ, "unavailable")
        await rig.person(EZ, "home")
    await rig.w.advance(400)
    assert nm.of(UNCOUNTED) == []
    assert snap(rig)["lock_regime_still_locked_pages"] == 2


@pytest.mark.asyncio
async def test_uncounted_flaps_keep_earliest_check():
    """B-L1, same kind: 4 uncounted returns 60 s apart -> the page lands 90 s
    after the FIRST one, with the uncounted wording."""
    rig = await make_rig()
    nm = install_nm(rig)
    await departure_unseen(rig, EZ)
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")  # T, uncounted
    for _ in range(3):
        await rig.w.advance(60)
        await rig.person(EZ, "unavailable")
        await rig.person(EZ, "home")
    # now T+180; the first check was due at T+90
    pages = nm.of(UNCOUNTED)
    assert len(pages) == 2
    assert all("may be locked out" in p["title"] for p in pages)
    assert nm.of(AFTER) == []


# --- A-2 / D-L1: the boot recheck reading WAKING is exempt from D3 -----------


@pytest.mark.asyncio
async def test_boot_recheck_waking_release_kept_no_tripwire():
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    assert store.data["garage_episode_saw_empty"] is True
    rig2 = await make_rig(start=datetime(2026, 11, 8, 6, 10, tzinfo=TZ), house="waking",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    nm = install_nm(rig2)
    await rig2.w.advance(121)
    assert rig2.unlocks() == [LOCK_A, LOCK_B]
    assert rig2.regime.last_action["trigger"] == "boot_recheck"
    assert nm.of(UNCORR) == []
    assert snap(rig2)["lock_regime_uncorroborated_releases"] == 0


# --- A-3: kill switch off at boot clears a restored taint ---------------------


@pytest.mark.asyncio
async def test_boot_kill_switch_off_clears_restored_taint():
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    assert store.data["garage_episode_saw_empty"] is True
    store2 = DictStore(dict(store.data))
    await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                   lockouts="locked", past_boot=False, store=store2,
                   opts=options(security_garage_lockout_enabled=False))
    assert store2.data["garage_episode_saw_empty"] is False
    rig3 = await make_rig(start=BOOT_0200 + timedelta(days=1, minutes=30),
                          house="home_day", lockouts="locked", past_boot=False,
                          store=DictStore(dict(store2.data)),
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig3)["lock_regime_episode_saw_empty"] is False
    await rig3.w.advance(121)
    # Step 1a delta L2: an awake house at the recheck is ignored (backstop).
    assert rig3.unlocks() == []
    assert rig3.regime.last_action["decision"] == "house_edge_ignored"


# --- D-L2: a return during a restart is paged, never released ----------------


async def _gap_rigs(*, boot_house="away", recheck_house="arriving",
                    persons=None, opts=None, away_edge=True):
    store = DictStore()
    rig1 = await make_rig(store=store, opts=opts)
    await rig1.edge("sleep")
    await rig1.person(OJI, "not_home")
    if away_edge:
        await rig1.edge("away")
    rig2 = await make_rig(start=datetime(2026, 11, 8, 1, 40, tzinfo=TZ), house=boot_house,
                          lockouts="locked", past_boot=False,
                          persons=persons or {EZ: "home", OJI: "not_home"},
                          store=DictStore(dict(store.data)), opts=opts)
    nm = install_nm(rig2)
    rig2.mgr.house_state = recheck_house
    return rig2, nm


@pytest.mark.asyncio
async def test_boot_gap_return_pages_never_releases():
    rig, nm = await _gap_rigs()
    await rig.w.advance(121)
    assert rig.unlocks() == []
    assert rig.regime.last_action["decision"] == "house_edge_ignored"
    assert rig.regime.last_action["boot_gap_paged"] == [LOCK_A, LOCK_B]
    pages = nm.of(BOOT_GAP)
    assert sorted(p["location"] for p in pages) == [
        f"garage_lockout:still_locked:{LOCK_A}", f"garage_lockout:still_locked:{LOCK_B}"]
    assert all(int(p["severity"]) == 3 for p in pages)
    assert "person.ezinne" in pages[0]["title"]


@pytest.mark.asyncio
async def test_boot_gap_return_pages_when_house_still_away():
    rig, nm = await _gap_rigs(recheck_house="away")
    await rig.w.advance(121)
    assert rig.regime.last_action["decision"] == "no_change"
    assert len(nm.of(BOOT_GAP)) == 2


@pytest.mark.asyncio
async def test_boot_gap_silent_when_restored_house_not_away():
    """Step 1a delta M3 split: restored house home_day and an episode that
    never saw an empty house (no AWAY edge before the restart, house awake at
    the recheck) -> silent; the same restored house with the persisted
    saw-empty flag -> pages."""
    rig, nm = await _gap_rigs(boot_house="home_day", recheck_house="home_day",
                              away_edge=False)
    assert snap(rig)["lock_regime_episode_saw_empty"] is False
    await rig.w.advance(121)
    assert rig.regime.last_action["decision"] == "house_edge_ignored"
    assert nm.of(BOOT_GAP) == []
    rig2, nm2 = await _gap_rigs(boot_house="home_day", recheck_house="home_day")
    assert snap(rig2)["lock_regime_episode_saw_empty"] is True
    await rig2.w.advance(121)
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"
    assert len(nm2.of(BOOT_GAP)) == 2


@pytest.mark.asyncio
async def test_boot_gap_silent_when_no_resident_home():
    rig, nm = await _gap_rigs(persons={EZ: "not_home", OJI: "not_home"})
    await rig.w.advance(121)
    assert nm.of(BOOT_GAP) == []
    assert snap(rig)["lock_regime_still_locked_pages"] == 0
    assert rig.regime._still_locked_paged == {}


@pytest.mark.asyncio
async def test_boot_gap_silent_when_only_excluded_person_home():
    rig, nm = await _gap_rigs(persons={EZ: "not_home", OJI: "not_home", KIOSK: "home"})
    await rig.w.advance(121)
    assert nm.of(BOOT_GAP) == []
    assert snap(rig)["lock_regime_still_locked_pages"] == 0
    assert rig.regime._still_locked_paged == {}


@pytest.mark.asyncio
async def test_boot_gap_reads_exclusion_list_live():
    """An options edit after setup that excludes the only home person stops
    the page (exclusions are read live, not from the setup resident set)."""
    rig, nm = await _gap_rigs()
    rig.w.cm_entry.options["security_lockout_excluded_persons"] = [KIOSK, EZ]
    await rig.w.advance(121)
    assert rig.regime.last_action["decision"] == "house_edge_ignored"
    assert nm.of(BOOT_GAP) == []


@pytest.mark.asyncio
async def test_boot_gap_silent_when_house_sleep_at_recheck():
    rig, nm = await _gap_rigs(recheck_house="sleep")
    await rig.w.advance(121)
    assert rig.regime.reason == "sleep"
    assert nm.of(BOOT_GAP) == []


@pytest.mark.asyncio
async def test_boot_gap_silent_when_reason_none_at_recheck():
    rig, nm = await _gap_rigs(recheck_house="away")
    rig.regime.on_hazard()  # reason NONE inside the boot window
    await settle()
    await rig.w.advance(25)  # the hazard unlocks land and read back
    rig.w.set_state(LOCK_A, "locked")  # hand-locked again
    rig.w.set_state(LOCK_B, "locked")
    await rig.w.advance(96)
    assert rig.regime.last_action["action"] == "boot_recheck"
    assert rig.regime.last_action["locked"] == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "none"
    assert nm.of(BOOT_GAP) == []


@pytest.mark.asyncio
async def test_boot_gap_disabled_by_constant(monkeypatch):
    monkeypatch.setattr(const, "LOCK_RELEASE_BOOT_GAP_RETURN_PAGE_ENABLED", False)
    rig, nm = await _gap_rigs()
    await rig.w.advance(121)
    assert nm.of(BOOT_GAP) == []


@pytest.mark.asyncio
async def test_boot_gap_silent_when_release_failed_already_paged():
    """A boot-window arrival whose unlock never lands already paged
    lockout_release_failed; no second page at the recheck."""
    rig, nm = await _gap_rigs(persons={EZ: "not_home", OJI: "not_home"})
    rig.w.apply_service_state = False
    await rig.w.advance(10)
    await rig.person(EZ, "home")  # boot-window arrival counts, S1 issues unlocks
    await rig.w.advance(111)
    assert len(nm.of(FAILED)) == 2
    assert nm.of(BOOT_GAP) == []


@pytest.mark.asyncio
async def test_boot_gap_silent_while_unlock_in_flight():
    rig, nm = await _gap_rigs(persons={EZ: "not_home", OJI: "not_home"})
    rig.w.apply_service_state = False
    await rig.w.advance(115)
    await rig.person(EZ, "home")  # unlock in flight at the 120 s recheck
    await rig.w.advance(6)
    assert rig.regime.last_action["action"] == "boot_recheck"
    assert nm.of(BOOT_GAP) == []


# --- D-H1: a restart never degrades a VACATION lock to boot_unknown ----------


@pytest.mark.asyncio
async def test_vacation_lock_survives_daytime_restart_after_away():
    store = DictStore()
    day = datetime(2026, 11, 7, 14, 0, tzinfo=TZ)
    rig1 = await make_rig(start=day, house="home_day", store=store,
                          persons={EZ: "home", OJI: "home"})
    await hs(rig1, "vacation", trigger="override_set")
    assert rig1.regime.reason == "vacation"
    assert rig1.locks() == [LOCK_A, LOCK_B]
    await rig1.person(EZ, "not_home")
    await rig1.person(OJI, "not_home")
    await rig1.edge("away")  # override cleared by the inferred AWAY
    assert rig1.regime.reason == "vacation"
    assert store.data["garage_reason"] == "vacation"
    rig2 = await make_rig(start=day + timedelta(days=1), house="away",
                          lockouts="locked", past_boot=False,
                          persons={EZ: "not_home", OJI: "not_home"},
                          store=DictStore(dict(store.data)))
    assert rig2.regime.reason == "vacation"
    await rig2.w.advance(3600)
    assert rig2.unlocks() == []
    assert rig2.regime.reason == "vacation"
    assert rig2.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_restored_vacation_converts_to_sleep_at_recheck():
    """Parity with boot_unknown: a store-rebuilt reason is provisional, so a
    house reading SLEEP at the recheck rebuilds SLEEP (WAKING releases)."""
    store = DictStore()
    day = datetime(2026, 11, 7, 14, 0, tzinfo=TZ)
    rig1 = await make_rig(start=day, house="home_day", store=store)
    await hs(rig1, "vacation", trigger="override_set")
    await rig1.edge("away")
    rig2 = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="away",
                          lockouts="locked", past_boot=False,
                          persons={EZ: "not_home", OJI: "not_home"},
                          store=DictStore(dict(store.data)))
    rig2.mgr.house_state = "sleep"
    await rig2.w.advance(121)
    assert rig2.regime.reason == "sleep"
    # The recheck re-engaged through _set_engage_reason: a backstop exists
    # (a VACATION rebuild has none).
    assert rig2.regime._backstop_unsub is not None
    await rig2.edge("waking")
    assert rig2.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_restored_sleep_untainted_home_releases_at_recheck():
    """Parity with boot_unknown, step 1a delta L2: a store-rebuilt SLEEP lock
    with the house awake is NOT released at the boot recheck (a restored awake
    state is body evidence); the morning backstop releases it."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await rig1.edge("sleep")
    assert store.data["garage_reason"] == "sleep"
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)),
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig2.regime.reason == "sleep"
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"
    await rig2.w.advance(
        (datetime(2026, 11, 9, 7, 0, 1, tzinfo=TZ) - rig2.w.now).total_seconds())
    assert rig2.unlocks() == [LOCK_A, LOCK_B]
    assert rig2.regime.last_action["trigger"] == "backstop"


@pytest.mark.asyncio
async def test_reason_none_persisted_after_release():
    store = DictStore()
    rig = await make_rig(store=store)
    await rig.edge("sleep")
    assert store.data["garage_reason"] == "sleep"
    await rig.edge("waking")
    assert store.data["garage_reason"] == "none"
    rig2 = await make_rig(start=datetime(2026, 11, 8, 23, 0, tzinfo=TZ), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    assert rig2.regime.reason == "boot_unknown"


@pytest.mark.asyncio
async def test_still_locked_check_from_older_engage_is_replaced(monkeypatch):
    """B-L1 boundary: a pending check from an OLDER engage_seq (silenced at
    fire) is replaced by a later arrival's check, which pages."""
    rig = await make_rig()
    nm = install_nm(rig)
    neuter_s1(monkeypatch, rig)
    await rig.person(EZ, "home")  # T, reason NONE, lockouts unlocked
    await rig.w.advance(30)
    await rig.edge("sleep")  # T+30: we lock (engage_seq bumps)
    assert rig.locks() == [LOCK_A, LOCK_B]
    await rig.w.advance(10)
    await rig.person(EZ, "not_home")
    await rig.person(EZ, "home")  # T+40, S1 (neutered) -> new check
    await rig.w.advance(89.9)
    assert nm.of(AFTER) == []
    await rig.w.advance(0.2)
    assert len(nm.of(AFTER)) == 2


@pytest.mark.asyncio
async def test_boot_gap_dedups_with_still_locked_page(monkeypatch):
    """A boot-window arrival whose S1 did nothing already paged D4a at +90 s;
    the boot recheck does not page the same lock again."""
    rig, nm = await _gap_rigs(persons={EZ: "not_home", OJI: "not_home"})
    neuter_s1(monkeypatch, rig)
    await rig.w.advance(10)
    await rig.person(EZ, "home")
    await rig.w.advance(111)
    assert len(nm.of(AFTER)) == 2
    assert nm.of(BOOT_GAP) == []
    assert rig.regime.last_action["action"] == "boot_recheck"


@pytest.mark.asyncio
async def test_restored_reason_confirmed_by_boot_window_engage_not_provisional():
    """Parity with boot_unknown: a boot-window SLEEP edge confirms the reason,
    so a silent HOME_DAY at the recheck does not release (as for a
    boot_unknown lock whose reason a boot-window edge rebuilt)."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await rig1.edge("sleep")
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                          lockouts="locked", past_boot=False,
                          persons={EZ: "not_home", OJI: "not_home"},
                          store=DictStore(dict(store.data)),
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig2.regime.reason == "sleep"
    await rig2.w.advance(30)
    await rig2.edge("sleep")  # boot-window edge: rebuild only
    rig2.mgr.house_state = "home_day"  # silent
    await rig2.w.advance(91)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"


@pytest.mark.asyncio
async def test_restored_sleep_home_night_guest_window_held_as_guest_night():
    """Parity with boot_unknown (INV-LOCK-1): a store-rebuilt lock found in a
    home_night sleep window with the guest toggle on is held as GUEST_NIGHT."""
    store = DictStore()
    opts = options(security_lockout_engage_on_guest_sleep=True)
    rig1 = await make_rig(store=store, opts=opts)
    await rig1.edge("sleep")
    rig2 = await make_rig(start=datetime(2026, 11, 8, 1, 0, tzinfo=TZ), house="home_night",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)), opts=opts)
    assert rig2.regime.reason == "sleep"
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.reason == "guest_night"
    assert rig2.regime.last_action["decision"] == "guest_yield_hold"


@pytest.mark.asyncio
async def test_restored_reason_manual_unlock_remembered_rebuilds_episode():
    """Parity with boot_unknown: a remembered manual unlock at the recheck
    rebuilds the episode through _set_engage_reason (boot-away flag ends)."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await rig1.edge("sleep")
    rig1.w.set_state(LOCK_A, "unlocked")  # a human unlocks one lockout
    assert store.data["garage_manual_unlock"] == "sleep"

    def one_unlocked(w):
        w.seed(LOCK_A, "unlocked")

    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="away",
                          lockouts="locked", past_boot=False, seed_hook=one_unlocked,
                          persons={EZ: "not_home", OJI: "not_home"},
                          store=DictStore(dict(store.data)))
    assert rig2.regime.reason == "sleep"
    assert snap(rig2)["lock_regime_episode_saw_empty"] is True  # boot-away flag
    rig2.mgr.house_state = "sleep"
    await rig2.w.advance(121)
    assert rig2.regime.last_action["decision"] == "manual_unlock_remembered"
    assert rig2.locks() == []
    assert snap(rig2)["lock_regime_episode_saw_empty"] is False
