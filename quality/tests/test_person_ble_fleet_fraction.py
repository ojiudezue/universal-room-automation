"""PERSON-BLE-WINS-OVER-STALE-GPS-1 residual — BLE-leads fleet fraction (D2).

Plan: docs/planning/PLANNING_ble_rearm_and_fleet_fraction.md rev 2 §2.2-2.5.

I-D2 (rev 2): the fleet latch can be healthy only when active proxies >= F,
F = max(3, ceil(0.5 x R)) if the ring holds a slot from a completed prior
local day within the last 7 days, else 30 (store missing / corrupt, first
deploy, total entity missing, only today's slot). R >= every numeric total
read in the retained days, including totals from before the last restart.

Every test drives the REAL PersonTrackingCoordinator (the `env` fixture from
test_person_gps_assistive: real constructor, fake hass, scoped clock /
registry / listener factory) and, for the load site, the REAL
`_async_start_person_coordinator` in __init__.py. Oracles are hand-derived
literals (31 = ceil(0.5 x 62), 4 = ceil(0.5 x 8), 3 = abs min).
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant.helpers.frame")

from test_person_gps_assistive import (  # noqa: E402,F401  (fixtures)
    OJI, PROXY, T0, _St, _arm, _bermuda_branch, _real_modules, _row, _tick,
    _tuple_1024, env,
)

TOTAL = "sensor.bermuda_global_total_proxy_count"
TODAY = T0.date()


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


class _Reg2:
    """Registry fake resolving BOTH Bermuda counts by unique_id."""

    def __init__(self, active=PROXY, total=TOTAL):
        self.active = active
        self.total = total

    def async_get_entity_id(self, domain, platform, unique_id):
        if (domain, platform) != ("sensor", "bermuda"):
            return None
        return {
            "BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT": self.active,
            "BERMUDA_GLOBAL_PROXY_COUNT": self.total,
        }.get(unique_id)


class _Store:
    def __init__(self, payload=None, raises=False):
        self.payload = payload
        self.raises = raises
        self.saves: list = []

    async def async_load(self):
        if self.raises:
            raise ValueError("corrupt")
        return self.payload

    def async_delay_save(self, fn, delay):
        self.saves.append((fn(), delay))


@pytest.fixture
def fx(env, monkeypatch):
    reg = _Reg2()
    monkeypatch.setattr(env.pc.er, "async_get", lambda _h: reg)
    store = _Store()
    env.coord._fleet_store = store
    return SimpleNamespace(env=env, coord=env.coord, hass=env.hass, reg=reg,
                           store=store, clock=env.clock)


def _load(fx, ring=None, raises=False):
    fx.store.payload = {"ring": ring} if ring is not None else None
    fx.store.raises = raises
    asyncio.run(fx.coord.async_load_fleet_memory())


def _counts(fx, active, total):
    if active is not None:
        fx.hass.set(PROXY, str(active))
    if total is not None:
        fx.hass.set(TOTAL, str(total))


def _upkeep(fx):
    """One per-tick fleet upkeep (the call `_async_update_data` makes)."""
    fx.coord._ensure_proxy_listener(fx.clock.t)


# ---------------------------------------------------------------------------
# Cold memory (MEDIUM-1) and fallbacks
# ---------------------------------------------------------------------------


def test_cold_memory_uses_legacy_floor_during_outage(fx):
    """No store, restart mid-outage (total 20, active 18): F = 30, unhealthy
    — develop's answer. A same-day R would have armed at F = 10."""
    _load(fx)
    _counts(fx, 18, 20)
    _upkeep(fx)
    assert fx.coord._effective_floor == 30
    assert fx.coord._fleet_healthy_since is None
    # Only today's slot exists: still cold even after more reads today.
    fx.clock.t = T0 + timedelta(hours=3)
    _counts(fx, 29, 62)
    _upkeep(fx)
    assert fx.coord._fleet_memory == [(_d(0), 62)]
    assert fx.coord._effective_floor == 30
    assert fx.coord._fleet_healthy_since is None


@pytest.mark.parametrize("raises,ring", [
    (True, None),
    (False, [["not-a-date", 62]]),
    (False, [[_d(1), "sixty"]]),
])
def test_corrupt_store_uses_legacy_floor(fx, raises, ring):
    _load(fx, ring=ring, raises=raises)
    _counts(fx, 30, 62)
    _upkeep(fx)
    assert fx.coord._effective_floor == 30
    assert fx.coord._fleet_memory == [(_d(0), 62)]


def test_unknown_fleet_falls_back_to_legacy_30(fx):
    """Total entity missing -> legacy 30 even with a warm ring; total entity
    present but unavailable -> ring still counts (R from memory)."""
    _load(fx, ring=[[_d(1), 62]])
    fx.reg.total = None
    _counts(fx, 30, None)
    _upkeep(fx)
    assert fx.coord._effective_floor == 30
    assert fx.coord._fleet_healthy_since == T0
    fx.reg.total = TOTAL
    fx.hass.set(TOTAL, "unavailable")
    _upkeep(fx)
    assert fx.coord._effective_floor == 31
    assert fx.coord._fleet_healthy_since is None
    assert fx.coord._fleet_memory == [(_d(1), 62)]   # never lowered/added


# ---------------------------------------------------------------------------
# Fractional floor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("active,healthy", [(30, False), (31, True), (32, True)])
def test_floor_is_fraction_of_remembered_high_water(fx, active, healthy):
    _load(fx, ring=[[_d(1), 62]])
    _counts(fx, active, 62)
    _upkeep(fx)
    assert fx.coord._effective_floor == 31
    assert (fx.coord._fleet_healthy_since is not None) is healthy


def test_shrinking_total_does_not_lower_floor(fx):
    """Outage: total shrinks to 34 with active 33 -> F stays 31 (healthy);
    active 30 -> unhealthy (develop's fixed 30 would arm)."""
    _load(fx, ring=[[_d(1), 62]])
    _counts(fx, 33, 34)
    _upkeep(fx)
    assert fx.coord._effective_floor == 31
    assert fx.coord._fleet_healthy_since is not None
    _counts(fx, 30, 34)
    _upkeep(fx)
    assert fx.coord._fleet_healthy_since is None
    assert fx.coord._fleet_memory == [(_d(1), 62), (_d(0), 34)]


def test_restart_restores_ring_from_store(fx):
    """Store holds 62 from yesterday; first tick after restart reads 25."""
    _load(fx, ring=[[_d(1), 62]])
    assert fx.coord._fleet_memory == [(_d(1), 62)]
    _counts(fx, 24, 25)
    _upkeep(fx)
    assert fx.coord._effective_floor == 31


@pytest.mark.parametrize("active,healthy", [(2, False), (3, True)])
def test_abs_min_floor_for_small_fleet(fx, active, healthy):
    """Ring 4 -> ceil(2) = 2 -> abs min 3 wins."""
    _load(fx, ring=[[_d(1), 4]])
    _counts(fx, active, 4)
    _upkeep(fx)
    assert fx.coord._effective_floor == 3
    assert (fx.coord._fleet_healthy_since is not None) is healthy


def test_small_house_fleet_arms_where_develop_never_did(fx):
    """Multi-home case: ring 8, active 5 -> F = 4, arms after 360 s; the
    legacy 30 never arms such a fleet."""
    _load(fx, ring=[[_d(1), 8]])
    _counts(fx, 5, 8)
    _upkeep(fx)
    assert fx.coord._effective_floor == 4
    fx.clock.t = T0 + timedelta(seconds=360)
    _upkeep(fx)
    assert fx.coord._fleet_armed(fx.clock.t) is True


# ---------------------------------------------------------------------------
# Ring maintenance
# ---------------------------------------------------------------------------


def test_ring_prunes_by_date_after_downtime(fx):
    """LOW-1: HA was down 10 days; the only slots are older than 7 days.
    They must age out -> cold memory -> legacy 30 (not 31 off stale 62)."""
    _load(fx, ring=[[_d(10), 62], [_d(9), 62]])
    _counts(fx, 30, 20)
    _upkeep(fx)
    assert fx.coord._effective_floor == 30
    assert fx.coord._fleet_memory == [(_d(0), 20)]


def test_future_dated_slot_dropped(fx):
    """Clock stepped back (or a slot written under a wrong date): a slot
    dated after today is not a 'completed prior day' and is dropped."""
    _load(fx, ring=[[(TODAY + timedelta(days=1)).isoformat(), 62]])
    _counts(fx, 30, 20)
    _upkeep(fx)
    assert fx.coord._effective_floor == 30
    assert fx.coord._fleet_memory == [(_d(0), 20)]


def test_ring_prunes_on_tick_across_day_rollover(fx):
    """Pruning also runs per tick (process up across midnights)."""
    _load(fx, ring=[[_d(6), 80], [_d(1), 62]])
    _counts(fx, 40, 62)
    _upkeep(fx)
    assert fx.coord._effective_floor == 40          # 80 retained (6 days)
    fx.clock.t = T0 + timedelta(days=1)             # 80 slot now 7 days old
    _upkeep(fx)
    assert fx.coord._effective_floor == 31
    assert all(d != _d(6) for d, _ in fx.coord._fleet_memory)


@pytest.mark.parametrize("age,floor", [(6, 40), (7, 31), (8, 31)])
def test_ring_ages_out_after_memory_days(fx, age, floor):
    """A removed proxy stops counting: a slot `age` days old is kept iff
    age <= 6 (today + 6 previous days = 7 local days)."""
    _load(fx, ring=[[_d(age), 80], [_d(1), 62]])
    _counts(fx, 40, 62)
    _upkeep(fx)
    assert fx.coord._effective_floor == floor


def test_store_written_only_on_slot_change(fx):
    _load(fx, ring=[[_d(1), 62]])
    _counts(fx, 40, 60)
    _upkeep(fx)                                     # new today slot
    assert len(fx.store.saves) == 1
    payload, delay = fx.store.saves[0]
    assert payload == {"ring": [[_d(1), 62], [_d(0), 60]]}
    assert delay == 60
    _upkeep(fx)                                     # same total
    _counts(fx, 40, 55)
    _upkeep(fx)                                     # lower total
    fx.hass.set(TOTAL, "unknown")
    _upkeep(fx)                                     # non-numeric
    assert len(fx.store.saves) == 1
    _counts(fx, 40, 61)
    _upkeep(fx)                                     # higher total
    assert len(fx.store.saves) == 2
    assert fx.store.saves[1][0] == {"ring": [[_d(1), 62], [_d(0), 61]]}


# ---------------------------------------------------------------------------
# Listener / tick agreement and the decision path
# ---------------------------------------------------------------------------


def test_listener_and_tick_share_cached_floor(fx):
    _load(fx, ring=[[_d(1), 62]])
    _counts(fx, 40, 62)
    _upkeep(fx)
    assert len(fx.env.track.subs) == 1
    _ids, cb = fx.env.track.subs[0]
    cb(SimpleNamespace(data={"new_state": _St("30")}))
    assert fx.coord._fleet_healthy_since is None
    fx.clock.t = T0 + timedelta(seconds=10)
    cb(SimpleNamespace(data={"new_state": _St("31")}))
    assert fx.coord._fleet_healthy_since == T0 + timedelta(seconds=10)


def test_overrule_decision_uses_fractional_floor(fx):
    """Full `_async_update_data`: the 10-24 tuple with active 30, armed.
    Develop (fixed 30) overrules GPS -> away; warm R = 62 -> F = 31 -> no
    overrule -> home. Same tuple, active 31 -> away."""
    _load(fx, ring=[[_d(1), 62]])
    _tuple_1024(fx.hass, proxy="30")
    fx.hass.set(TOTAL, "62")
    _bermuda_branch(fx.coord, fx.hass)
    _arm(fx.env, seconds=10_000)
    assert _row(_tick(fx.coord))["location"] == "home"
    _tuple_1024(fx.hass, proxy="31")
    _arm(fx.env, seconds=10_000)
    assert _row(_tick(fx.coord))["location"] == "away"


def test_overrule_decision_cold_memory_is_legacy(fx):
    """Cold memory: active 30 + fixed floor 30 -> away (develop identical)."""
    _load(fx)
    _tuple_1024(fx.hass, proxy="30")
    fx.hass.set(TOTAL, "62")
    _bermuda_branch(fx.coord, fx.hass)
    _arm(fx.env, seconds=10_000)
    assert _row(_tick(fx.coord))["location"] == "away"
    assert fx.coord._effective_floor == 30


# ---------------------------------------------------------------------------
# Load site (MEDIUM-2): __init__._async_start_person_coordinator
# ---------------------------------------------------------------------------


def test_first_refresh_sees_restored_ring(fx, monkeypatch):
    """The real start helper restores the ring BEFORE the first refresh, so
    the first tick already computes F = 31 from yesterday's 62."""
    init_mod = importlib.import_module("custom_components.universal_room_automation")
    fx.store.payload = {"ring": [[_d(1), 62]]}
    _tuple_1024(fx.hass, proxy="30")
    fx.hass.set(TOTAL, "25")
    _bermuda_branch(fx.coord, fx.hass)
    seen = {}

    async def _first_refresh():
        fx.coord.data = await fx.coord._async_update_data()
        seen["floor"] = fx.coord._effective_floor

    fx.coord.async_config_entry_first_refresh = _first_refresh
    monkeypatch.setattr(init_mod, "PersonTrackingCoordinator",
                        lambda hass, entry: fx.coord)
    got = asyncio.run(init_mod._async_start_person_coordinator(
        fx.hass, fx.env.entry,
    ))
    assert got is fx.coord
    assert seen["floor"] == 31
    assert fx.coord._fleet_memory[0] == (_d(1), 62)
