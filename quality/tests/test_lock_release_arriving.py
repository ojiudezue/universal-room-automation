"""LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 (plan PLANNING_lock_release_on_arriving.md rev 3).

House-state ARRIVING is body evidence with no identity (presence.infer moves
AWAY -> ARRIVING on census_count > 0 or any zone occupied). INV-ARR: with the
garage lockout ON, an engaged episode that has seen ARRIVING (the taint) never
releases on a ``house_state:*`` / ``boot_recheck`` trigger, except WAKING and
an operator ``override_set`` edge. Real arrivals release through the resident
person edge (S1), which is unchanged.

Every test drives the REAL LockRegimeController and the REAL
SecurityCoordinator house-state bridge (``_on_house_state_changed_signal``)
through the injected fake clock / timers / trackers of ``_lockout_harness``,
and asserts on the recorded ``lock.unlock`` stream and regime state. No test
assigns ``_arrival_taint`` / ``_episode_saw_arriving`` / ``engage_seq``
directly (plan §7, F17); seams are a patched ``_edge_decision`` return or a
neutered call. Times and bounds are hardcoded literals, never imported
constants.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from _lockout_harness import TZ, settle
from test_sc_garage_lockout import (
    BOOT_0200,
    EZ,
    LOCK_A,
    LOCK_B,
    NIGHT,
    OJI,
    DictStore,
    R,
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
    assert rig.regime.last_action["action"] == "arriving_hold"
    assert rig.regime.last_action["trigger"] == "house_state:arriving"
    assert rig.regime._backstop_unsub is not None  # backstop still scheduled
    s = snap(rig)
    assert s["lock_regime_arriving_taint"] is True
    assert s["lock_regime_episode_saw_arriving"] is True
    assert s["lock_regime_arriving_holds"] == 1


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
    assert snap(rig)["lock_regime_arriving_holds"] == 4
    # Morning backstop (sleep_end 06:00 + 60 min) releases once.
    await rig.w.advance(
        (datetime(2026, 11, 8, 7, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "backstop"
    assert rig.regime.reason == "none"
    assert snap(rig)["lock_regime_arriving_taint"] is False


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
    assert snap(rig)["lock_regime_arriving_taint"] is True
    rig.w.calls.clear()
    await rig.w.advance(2 * 3600)
    await rig.edge("home_night")
    assert rig.w.calls == []
    assert rig.regime.reason == "sleep"
    assert rig.regime.last_action["action"] == "arriving_hold"


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
    assert rig.regime.last_action["action"] == "arriving_hold"
    assert rig.regime.reason == "sleep"


@pytest.mark.asyncio
async def test_boot_rebuild_away_locked_taints():
    """_boot_rebuild: a lock found locked while the house reads away is an
    excursion; with no ARRIVING edge ever seen, a later HOME_* at the boot
    recheck is held."""
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert rig.regime.reason == "boot_unknown"
    assert snap(rig)["lock_regime_arriving_taint"] is True
    rig.mgr.house_state = "home_night"  # silent change, no edge
    await rig.w.advance(121)
    assert rig.unlocks() == []
    assert rig.regime.last_action["decision"] == "arriving_hold"


@pytest.mark.asyncio
async def test_boot_rebuild_away_then_arriving_home_night_edge_held():
    """Plan D1 H2 AC: restart with house away + lockout locked; a dispatched
    arriving -> home_night edge (no ARRIVING edge seen) -> arriving_hold; the
    boot recheck at 120 s -> arriving_hold; 0 unlocks."""
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig.w.advance(30)
    await hs(rig, "home_night", old="arriving")
    assert rig.regime.last_action["action"] == "arriving_hold"
    await rig.w.advance(91)
    assert rig.regime.last_action["decision"] == "arriving_hold"
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_boot_recheck_arriving_never_releases_even_resident_home():
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         persons={EZ: "home", OJI: "home"})
    rig.mgr.house_state = "arriving"
    await rig.w.advance(121)
    assert rig.unlocks() == []
    assert rig.regime.last_action["decision"] == "arriving_hold"
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
    assert snap(rig)["lock_regime_arriving_taint"] is False
    rig.mgr.house_state = "arriving"  # boot settle swallowed the edges
    await rig.w.advance(121)
    assert rig.regime.last_action["decision"] == "arriving_hold"
    assert snap(rig)["lock_regime_episode_saw_arriving"] is True
    assert store.data["garage_arrival_taint"] is True
    rig2 = await make_rig(start=BOOT_0200 + timedelta(minutes=10), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)), opts=opts)
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "arriving_hold"


@pytest.mark.asyncio
@pytest.mark.parametrize("house", ["sleep", "vacation"])
async def test_boot_recheck_sleep_vacation_rebuild_clears_taint(house):
    """_on_boot_recheck turning BOOT_UNKNOWN into SLEEP / VACATION starts that
    episode: the boot-away taint ends."""
    rig = await make_rig(start=BOOT_0200, house="away", lockouts="locked",
                         past_boot=False,
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig)["lock_regime_arriving_taint"] is True
    rig.mgr.house_state = house
    await rig.w.advance(121)
    assert rig.regime.reason == house
    assert snap(rig)["lock_regime_arriving_taint"] is False
    assert snap(rig)["lock_regime_episode_saw_arriving"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("house", ["sleep", "vacation"])
async def test_boot_rebuild_sleep_vacation_clears_restored_taint(house):
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    assert store.data["garage_arrival_taint"] is True
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house=house,
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    assert rig2.regime.reason == house
    assert snap(rig2)["lock_regime_arriving_taint"] is False
    assert snap(rig2)["lock_regime_episode_saw_arriving"] is False


@pytest.mark.asyncio
async def test_taint_persisted_across_restart_two_rigs():
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    assert store.data["garage_arrival_taint"] is True
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_day",
                          lockouts="locked", past_boot=False,
                          store=DictStore(dict(store.data)))
    assert rig2.regime.reason == "boot_unknown"
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "arriving_hold"


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
    assert rig2.regime.last_action["decision"] == "arriving_hold"
    assert rig2.regime.manual_unlock_reason == "sleep"


@pytest.mark.asyncio
async def test_guest_clock_clears_taint():
    """M3 stale-taint repro: VACATION -> ARRIVING -> HOME_DAY -> GUEST, the
    guest clock engages GUEST_NIGHT (new episode, taint cleared); next morning
    HOME_DAY releases."""
    rig = await make_rig(start=datetime(2026, 11, 7, 20, 0, tzinfo=TZ), house="away",
                         opts=options(security_lockout_engage_on_guest_sleep=True))
    await rig.edge("vacation")
    await rig.edge("arriving")
    await rig.edge("home_day")
    await rig.edge("guest")
    assert snap(rig)["lock_regime_arriving_taint"] is True
    await rig.w.advance(
        (datetime(2026, 11, 7, 22, 0, 1, tzinfo=TZ) - rig.w.now).total_seconds())
    assert rig.regime.reason == "guest_night"
    assert snap(rig)["lock_regime_arriving_taint"] is False
    assert rig.unlocks() == []
    await rig.w.advance(
        (datetime(2026, 11, 8, 6, 30, tzinfo=TZ) - rig.w.now).total_seconds())
    await rig.edge("home_day")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == "house_state:home_day"


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
    assert snap(rig)["lock_regime_arriving_taint"] is True
    assert store.data["garage_arrival_taint"] is True
    await {
        "sc_disable": _site_sc_disable,
        "hazard": _site_hazard,
        "kill_switch": _site_kill_switch,
        "after_release": _site_after_release,
        "vacation_arrival": _site_vacation_arrival,
    }[site](rig)
    assert rig.regime.reason == "none"
    s = snap(rig)
    assert s["lock_regime_arriving_taint"] is False
    assert s["lock_regime_episode_saw_arriving"] is False
    assert store.data["garage_arrival_taint"] is False
    assert store.data["garage_episode_saw_arriving"] is False


def _reason_writes() -> list[tuple[str, str, bool]]:
    """(enclosing function, assigned constant/name, followed by the clear
    helper) for every ``self.reason = ...`` in the production module."""
    src_path = pathlib.Path(R.__file__)
    tree = ast.parse(src_path.read_text())
    out: list[tuple[str, str, bool]] = []

    def walk_body(fn_name: str, body: list[ast.stmt]) -> None:
        for i, stmt in enumerate(body):
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Attribute)
                and stmt.targets[0].attr == "reason"
                and isinstance(stmt.targets[0].value, ast.Name)
                and stmt.targets[0].value.id == "self"
            ):
                val = stmt.value
                name = val.id if isinstance(val, ast.Name) else ast.dump(val)
                nxt = body[i + 1] if i + 1 < len(body) else None
                followed = (
                    isinstance(nxt, ast.Expr)
                    and isinstance(nxt.value, ast.Call)
                    and isinstance(nxt.value.func, ast.Attribute)
                    and nxt.value.func.attr == "_end_episode_arrival_flags"
                )
                out.append((fn_name, name, followed))
            for field in ("body", "orelse", "finalbody", "handlers"):
                sub = getattr(stmt, field, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    walk_body(fn_name, sub)
                elif isinstance(sub, list):
                    for h in sub:
                        if isinstance(h, ast.ExceptHandler):
                            walk_body(fn_name, h.body)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_body(node.name, node.body)
    return out


def test_reason_assignments_structurally_guarded():
    """Secondary refactor guard (Bug Class #53; the behaviour is pinned by
    the parametrised clear-site test and the R2-1 / R2-4 repros). Every
    ``self.reason =`` write is inside _set_engage_reason, immediately followed
    by _end_episode_arrival_flags(), or on the deliberate no-clear allowlist
    (keyed by function + constant, not line numbers)."""
    allow = {
        ("_boot_rebuild", "REASON_BOOT_UNKNOWN"),
        ("_boot_recheck_regime", "REASON_GUEST_NIGHT"),
    }
    writes = _reason_writes()
    assert len(writes) == 12, writes  # a new write must be classified here
    for fn, name, followed in writes:
        if fn == "_set_engage_reason":
            continue
        if (fn, name) in allow:
            assert not followed, f"allowlisted no-clear write {fn}:{name} gained the clear"
            continue
        assert followed, f"self.reason = {name} in {fn} does not end the ARRIVING taint"


@pytest.mark.asyncio
async def test_boot_guest_night_rebuild_keeps_taint():
    """R2-1 repro: GUEST_NIGHT episode, GUEST -> AWAY -> ARRIVING (taint) ->
    HOME_NIGHT (guest_yield_hold); restart; the boot recheck rebuilds
    GUEST_NIGHT and keeps the taint; next morning HOME_DAY is held."""
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
    assert s["lock_regime_arriving_taint"] is True
    assert s["lock_regime_episode_saw_arriving"] is True
    await rig2.w.advance(
        (datetime(2026, 11, 8, 6, 30, tzinfo=TZ) - rig2.w.now).total_seconds())
    await rig2.edge("home_day")
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["action"] == "arriving_hold"


@pytest.mark.asyncio
async def test_boot_nothing_locked_clears_stale_taint():
    """R2-4 repro: tainted SLEEP episode, resident person release (taint
    kept), restart with nothing locked -> flags cleared; the operator
    hand-locks; restart with house home_day -> the boot recheck releases as
    today (not arriving_hold)."""
    store = DictStore()
    rig1 = await make_rig(store=store)
    await tainted_sleep_episode(rig1)
    await rig1.person(EZ, "home")
    assert rig1.unlocks() == [LOCK_A, LOCK_B]
    assert store.data["garage_arrival_taint"] is True
    store2 = DictStore(dict(store.data))
    rig2 = await make_rig(start=BOOT_0200 + timedelta(days=1), house="home_night",
                          lockouts="unlocked", past_boot=False, store=store2,
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    assert snap(rig2)["lock_regime_arriving_taint"] is False
    assert store2.data["garage_arrival_taint"] is False
    assert store2.data["garage_episode_saw_arriving"] is False
    rig3 = await make_rig(start=BOOT_0200 + timedelta(days=1, minutes=30),
                          house="home_day", lockouts="locked", past_boot=False,
                          store=DictStore(dict(store2.data)),
                          opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig3.w.advance(121)
    assert rig3.unlocks() == [LOCK_A, LOCK_B]
    assert rig3.regime.last_action["trigger"] == "boot_recheck"


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
    assert s["lock_regime_arriving_taint"] is False
    assert s["lock_regime_episode_saw_arriving"] is False
    assert s["lock_regime_arriving_holds"] == 0


@pytest.mark.asyncio
async def test_reason_none_arriving_no_unlock():
    """F19: reason NONE + lockouts locked by hand + ARRIVING -> 0 unlocks."""
    rig = await make_rig(house="away")
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    assert rig.regime.reason == "none"
    await rig.edge("arriving")
    assert rig.unlocks() == []
    assert snap(rig)["lock_regime_arriving_taint"] is False


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
    assert snap(rig)["lock_regime_arriving_taint"] is False
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
    assert snap(rig)["lock_regime_arriving_taint"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [0, 900, 7200])
async def test_extreme_reengage_delay_after_night_person_release_then_arriving(delay):
    rig = await make_rig(opts=options(garage_lockout_reengage_delay_s=delay))
    await rig.edge("sleep")
    await rig.edge("away")
    await rig.person(EZ, "home")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.edge("arriving")
    assert snap(rig)["lock_regime_arriving_taint"] is True
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
    assert snap(rig)["lock_regime_arriving_taint"] is True


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
    assert snap(rig)["lock_regime_arriving_holds"] == 5
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

    def patched(new, cfg, *, override=False):
        if new in houses:
            return "release", None
        return real(new, cfg, override=override)

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
    """Boot channel: the saw flag survives a restart (store) and is also set by
    the boot paths. rig 2 boots with the D1 boot arriving_hold mutated to a
    release -> one page. ``home_day`` relies on the persisted saw flag alone."""
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
    """A HOME_* release in an episode that never saw ARRIVING is today's
    behaviour and must not page (saw flag conjunct)."""
    rig = await make_rig()
    nm = install_nm(rig)
    await rig.edge("sleep")
    await rig.edge("home_day")
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
