"""HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 — pre-arrival stand-down + arrival pre-heat.

Plan: docs/planning/PLANNING_hvac_precool_standdown_and_seasons.md rev 4
(D1 cool stand-down, D1b master-OFF filter, D1c energy gate-OFF filter, D2
arrival pre-heat, D3 leg/mode table, D4 status attrs).

Invariants under test (plan §2):
  INV-SD-COOL  no pre-arrival pre-cool begins while T <= effective_high + margin.
  INV-SD-HEAT  no pre-arrival pre-heat begins unless T < effective_low - margin
               (T None / mode not heat_cool -> no write).
  INV-ONE-LEG  no pass writes both legs.
  INV-LIFECYCLE every S13_pre_arrival borrow ends by the S12_pre_arrival paths.
  INV-NO-RELEASE-WRITE switch-28 OFF writes nothing to a zone with no borrow.

Drives the REAL coordinator / predictor / excursion primitive (W1-B harness).
Oracles are hand-derived literals from the plan's arithmetic (§0.2), never
re-computed from the code under test; boundaries are literals.
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402


@pytest.fixture(autouse=True)
def _entity_registry_not_loaded(monkeypatch):
    """Pin the alone-run registry-miss behaviour (see part_b)."""
    from homeassistant.helpers import entity_registry as er

    def _not_loaded(hass):
        raise KeyError("entity registry not loaded on the StubHass")

    monkeypatch.setattr(er, "async_get", _not_loaded)


Z1, E1 = "zone_1", "climate.test_zone_1"
Z2, E2 = "zone_2", "climate.test_zone_2"
# Seasonal (cool, heat) profiles, hand-typed. WINTER = SEASONAL_DEFAULTS
# winter (Home 72/70, Away 78/60); SUMMER = summer defaults (Home 77/70).
WINTER = {"home": (72.0, 70.0), "away": (78.0, 60.0), "sleep": (70.0, 68.0)}
SUMMER = {"home": (77.0, 70.0), "away": (82.0, 60.0), "sleep": (76.0, 70.0)}


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    m = H.load_real()
    yield m
    m["hvac_excursion"]._test_clear_leases()
    m["hvac_setpoint"]._test_clear_ura_setpoints()


@pytest.fixture
def expected_lingering_timers():
    return True


class FakeScheduler:
    def __init__(self):
        self.pending: list[list] = []

    def __call__(self, hass, delay, cb):
        rec = [float(delay), cb, False]
        self.pending.append(rec)

        def _cancel():
            rec[2] = True
        return _cancel

    def live(self):
        return [r for r in self.pending if not r[2]]


class PersistDB(H.FakeDB):
    """Excursion persistence that persists (boot-audit) + records events."""

    def __init__(self):
        super().__init__()
        self.state: dict[str, dict] = {}
        self.events: list[dict] = []
        self.save_hook = None

    async def save_excursion_row(self, row):
        self.state[row["zone_id"]] = dict(row)
        if self.save_hook is not None:
            hook, self.save_hook = self.save_hook, None
            await hook(row)

    async def clear_excursion_row(self, zone_id):
        self.state.pop(zone_id, None)

    async def get_all_excursion_rows(self):
        return [dict(r) for r in self.state.values()]

    async def log_excursion_event(self, **kw):
        self.events.append(dict(kw))


def _setup(mods, monkeypatch, *, seasonal=WINTER, low=60.0, high=78.0, temp=74.0,
           mode="heat_cool", floor=74.0, house_state="home_night", zones=(Z2,)):
    coord, hass = H.make_coord(mods)
    coord._house_state = house_state
    coord._zone_intelligence_enabled = True
    coord._boot_settle_done = True
    coord._zone_state_store = H.FakeStore()
    mods["hvac_setpoint"]._test_clear_ura_setpoints()
    pm = coord._preset_manager
    monkeypatch.setattr(pm, "get_seasonal_setpoints",
                        lambda p, season=None: seasonal.get(p))
    pm._current_season = "winter"
    sched = FakeScheduler()
    for m in ("hvac_override", "hvac_predict", "hvac"):
        monkeypatch.setattr(mods[m], "async_call_later", sched)
    db = PersistDB()
    mods["hvac_excursion"]._test_bind(hass=hass, db=db)
    coord._override_arrester.enabled = True
    coord._predictor._solar_bank_floor = floor
    for zid in zones:
        z = coord.zone_manager.zones[zid]
        z.target_temp_low, z.target_temp_high, z.preset_mode = low, high, "away"
        z.current_temperature = temp
        z.hvac_mode = mode
        H.set_climate(hass, z.climate_entity, preset_mode="away", hold_activity="away",
                      low=low, high=high, state=mode or "heat_cool",
                      extra={"current_temperature": temp})
        _occ(mods, coord, zid)
    return coord, hass, db, sched


def _occ(mods, coord, zid, *, lighting=False, hvac=False, temp=None):
    RC = mods["hvac_zones"].RoomCondition
    coord.zone_manager.zones[zid].room_conditions = [
        RC(room_name=f"r_{zid}", occupied=lighting, hvac_occupied=hvac, temperature=temp)]


def _cool_rows(hass, mods):
    return [r for r in H.climate_write_rows(hass, mods, "S12_pre_cool")
            if r.get("reason") == "pre_arrival"]


def _heat_rows(hass, mods):
    return [r for r in H.climate_write_rows(hass, mods, "S13_pre_heat")
            if r.get("reason") == "pre_arrival"]


def _tok(coord, zid=Z2):
    return (getattr(coord._predictor, "_banking_excursion_tokens", {}) or {}).get(zid)


def _rows(mods, zid=Z2):
    ex = mods["hvac_excursion"]
    t = ex.live_token_for(zid)
    return [] if t is None else [t]


async def _pass(coord, hass, zid=Z2, *, add=True, house_state="home_night",
                when=datetime(2026, 1, 15, 17, 30)):
    if add:
        coord._pre_arrival_zones.add(zid)
        coord._pre_arrival_start[zid] = datetime.now(timezone.utc)
    await coord._predictor._check_pre_conditioning(
        None, house_state, when,
        pre_arrival_zones=set(coord._pre_arrival_zones),
        zone_intelligence_enabled=True)
    await H.drain(hass)


def _skips(coord, zid=Z2):
    return [s for s in coord._predictor._last_prearrival_skips if s["zone"] == zid]


def _standdown_rows(hass, mods):
    return hass.data[mods["const"].DOMAIN]["activity_logger"].actions("pre_arrival_standdown")


def _install_cm(hass, mods, *, pre_cond=True, energy_on=True):
    DOMAIN = mods["const"].DOMAIN
    hv = MagicMock()
    hv.pre_conditioning_enabled = pre_cond
    en = MagicMock()
    en.energy_precool_enabled = energy_on
    en.energy_precool_offset = -3.0
    en.energy_precool_scope = "whole_house"
    hass.data[DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": hv, "energy": en})


async def _fire(hass, arr, ev):
    arr._handle_climate_change(ev)
    await H.drain(hass, rounds=6)


def _ev(ent, old, new):
    return H.make_event(ent, old_preset=old[0], new_preset=new[0],
                        old_low=old[1], old_high=old[2],
                        new_low=new[1], new_high=new[2])


def _arrive_setup(coord):
    coord._pre_arrival_enabled = True
    coord._pre_arrival_sources = ["ble"]
    coord._person_zone_map = {"person.jaya": [Z2]}
    coord._async_decision_cycle = AsyncMock()


# ==========================================================================
# D1 — cool stand-down (summer: Home 77 -> effective_high 75, floor 74)
# ==========================================================================


def _summer(mods, monkeypatch, temp, **kw):
    kw.setdefault("low", 60.0)
    kw.setdefault("high", 82.0)
    return _setup(mods, monkeypatch, seasonal=SUMMER, temp=temp, **kw)


@pytest.mark.asyncio
async def test_cool_standdown_at_target_skips_borrow_and_write(mods, monkeypatch):
    """T 75 == effective_high 75 -> no begin (no excursion row, no event),
    no funnel call. A compare placed after begin_excursion leaves a row."""
    coord, hass, db, _ = _summer(mods, monkeypatch, 75.0)
    await _pass(coord, hass)
    assert _cool_rows(hass, mods) == []
    assert H.temp_writes(hass, E2) == []
    assert _rows(mods) == [] and db.events == [] and db.state == {}
    assert _tok(coord) is None
    assert [(s["leg"], s["reason"], s["effective_high"]) for s in _skips(coord)
            if s["leg"] == "cool"] == [("cool", "cool_standdown", 75.0)]


@pytest.mark.asyncio
async def test_cool_standdown_below_target_skips(mods, monkeypatch):
    coord, hass, db, _ = _summer(mods, monkeypatch, 74.0)
    await _pass(coord, hass)
    assert _cool_rows(hass, mods) == [] and db.state == {}


@pytest.mark.asyncio
async def test_cool_above_target_writes_legacy(mods, monkeypatch):
    coord, hass, db, _ = _summer(mods, monkeypatch, 76.0)
    await _pass(coord, hass)
    rows = _cool_rows(hass, mods)
    assert [r["values_after"]["target_temp_high"] for r in rows] == [75.0]
    assert _tok(coord).caller_site == "S12_pre_arrival"


@pytest.mark.asyncio
async def test_cool_uses_thermostat_reading_not_room_average(mods, monkeypatch):
    """Rooms read 73 (avg_temperature 73), thermostat reads 76 -> writes."""
    coord, hass, db, _ = _summer(mods, monkeypatch, 76.0)
    _occ(mods, coord, Z2, temp=73.0)
    assert coord.zone_manager.zones[Z2].avg_temperature == 73.0
    await _pass(coord, hass)
    assert len(_cool_rows(hass, mods)) == 1


@pytest.mark.parametrize("temp", [None, "unknown"])
@pytest.mark.asyncio
async def test_cool_none_temperature_fails_open(mods, monkeypatch, temp):
    coord, hass, db, _ = _summer(mods, monkeypatch, 74.0)
    coord.zone_manager.zones[Z2].current_temperature = temp
    await _pass(coord, hass)
    assert [r["values_after"]["target_temp_high"] for r in _cool_rows(hass, mods)] == [75.0]
    assert ("cool", "no_temp") in {(s["leg"], s["reason"]) for s in _skips(coord)}


@pytest.mark.asyncio
async def test_cool_reevaluates_next_tick_when_zone_warms(mods, monkeypatch):
    coord, hass, db, _ = _summer(mods, monkeypatch, 75.0)
    await _pass(coord, hass)
    assert _cool_rows(hass, mods) == []
    coord.zone_manager.zones[Z2].current_temperature = 77.0
    await _pass(coord, hass)
    assert [r["values_after"]["target_temp_high"] for r in _cool_rows(hass, mods)] == [75.0]


@pytest.mark.asyncio
async def test_energy_precool_unaffected(mods, monkeypatch):
    """INV-NOOP: the energy caller writes with T far below its target."""
    coord, hass, db, _ = _summer(mods, monkeypatch, 60.0)
    z = coord.zone_manager.zones[Z2]
    out = await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    rows = H.climate_write_rows(hass, mods, "S12_pre_cool")
    assert [(r["reason"], r["values_after"]["target_temp_high"]) for r in rows] == [
        ("energy_precool", 79.0)]
    assert out == "began" and _skips(coord) == []


@pytest.mark.asyncio
async def test_margin_widens_standdown(mods, monkeypatch):
    """Margin 1: T 76 <= 75 + 1 stands down (writes with margin 0)."""
    monkeypatch.setattr(mods["hvac_predict"], "PRE_ARRIVAL_STANDDOWN_MARGIN_F", 1.0)
    coord, hass, db, _ = _summer(mods, monkeypatch, 76.0)
    await _pass(coord, hass)
    assert _cool_rows(hass, mods) == []
    coord.zone_manager.zones[Z2].current_temperature = 77.0
    await _pass(coord, hass)
    assert len(_cool_rows(hass, mods)) == 1


@pytest.mark.asyncio
async def test_cool_kill_const_false_is_legacy(mods, monkeypatch):
    monkeypatch.setattr(mods["hvac_predict"], "PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED", False)
    coord, hass, db, _ = _summer(mods, monkeypatch, 70.0)
    await _pass(coord, hass)
    assert [r["values_after"]["target_temp_high"] for r in _cool_rows(hass, mods)] == [75.0]


# ==========================================================================
# D1b — switch-28 OFF writes nothing to a zone with no borrow
# ==========================================================================


@pytest.mark.asyncio
async def test_master_off_release_skips_zone_without_borrow(mods, monkeypatch):
    coord, hass, db, _ = _summer(mods, monkeypatch, 75.0)
    _install_cm(hass, mods, pre_cond=True, energy_on=False)
    await _pass(coord, hass)
    assert Z2 in coord._predictor._last_pre_conditioning_zones and _tok(coord) is None
    _install_cm(hass, mods, pre_cond=False, energy_on=False)
    n = len(hass.services.calls)
    await _pass(coord, hass, add=False)
    assert hass.services.calls[n:] == []


@pytest.mark.asyncio
async def test_master_off_release_keeps_banked_zone(mods, monkeypatch):
    """A live energy banking token is still released (banking_release)."""
    coord, hass, db, _ = _summer(mods, monkeypatch, 80.0)
    _install_cm(hass, mods, pre_cond=True, energy_on=False)
    pred = coord._predictor
    await pred._execute_zone_pre_cool(coord.zone_manager.zones[Z2], offset=-3.0,
                                      reason="energy_precool")
    tok = _tok(coord)
    pred._last_pre_conditioning_zones = {Z2}
    pred._last_pre_conditioning_gate_enabled = True
    _install_cm(hass, mods, pre_cond=False, energy_on=False)
    await pred._check_pre_conditioning(None, "home_night", datetime(2026, 7, 1, 11, 0),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "banking_release"
    assert H.preset_writes(hass, E2, "away")


@pytest.mark.asyncio
async def test_master_off_release_keeps_zone_with_token_but_no_live_row(mods, monkeypatch):
    """A banking token whose registry row is gone (stale) is still released,
    so the token is closed rather than left in the dict."""
    coord, hass, db, _ = _summer(mods, monkeypatch, 80.0)
    pred = coord._predictor
    await pred._execute_zone_pre_cool(coord.zone_manager.zones[Z2], offset=-3.0,
                                      reason="energy_precool")
    tok = _tok(coord)
    mods["hvac_excursion"]._rows.pop(Z2)
    assert not mods["hvac_excursion"].is_borrow_active(Z2)
    pred._last_pre_conditioning_zones = {Z2}
    pred._last_pre_conditioning_gate_enabled = True
    _install_cm(hass, mods, pre_cond=False, energy_on=False)
    await pred._check_pre_conditioning(None, "home_night", datetime(2026, 7, 1, 11, 0),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert Z2 not in pred._banking_excursion_tokens
    assert tok.returned


@pytest.mark.asyncio
async def test_master_off_release_keeps_preheat_zone(mods, monkeypatch):
    """An energy pre-heat zone (a `_preheat_excursion_tokens` entry, no banking
    token) is still released."""
    coord, hass, db, _ = _summer(mods, monkeypatch, 80.0)
    pred = coord._predictor
    pred._preheat_excursion_tokens = {Z2: SimpleNamespace(returned=False)}
    pred._last_pre_conditioning_zones = {Z2}
    pred._last_pre_conditioning_gate_enabled = True
    released: list = []

    async def _rel(zone_ids, *, trigger="banking_release"):
        released.append((set(zone_ids), trigger))
    monkeypatch.setattr(pred, "_release_banked_zones", _rel)
    _install_cm(hass, mods, pre_cond=False, energy_on=False)
    await pred._check_pre_conditioning(None, "home_night", datetime(2026, 7, 1, 11, 0),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    assert released == [({Z2}, "banking_release")]


# ==========================================================================
# D1c — energy pre-cool gate OFF leaves a pre-arrival borrow alone (R5)
# ==========================================================================


@pytest.mark.parametrize("leg", ["cool", "heat"])
@pytest.mark.asyncio
async def test_energy_precool_gate_off_leaves_prearrival_borrow(mods, monkeypatch, leg):
    if leg == "cool":
        coord, hass, db, _ = _summer(mods, monkeypatch, 80.0)
        site = "S12_pre_arrival"
    else:
        coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
        site = "S13_pre_arrival"
    _arrive_setup(coord)
    pred = coord._predictor
    pred._first_eval_done = True
    # Pass 1: energy pre-cool off -> the pre-arrival leg begins.
    _install_cm(hass, mods, pre_cond=True, energy_on=False)
    await _pass(coord, hass, when=datetime(2026, 7, 1, 10, 55))
    tok = _tok(coord)
    assert tok.caller_site == site
    # Pass 2: energy pre-cool on -> visits Z2, is refused, still tracks it.
    _install_cm(hass, mods, pre_cond=True, energy_on=True)
    monkeypatch.setattr(pred, "_should_energy_precool", lambda c, n: True)
    await _pass(coord, hass, add=False, when=datetime(2026, 7, 1, 11, 0))
    assert _tok(coord) is tok
    assert Z2 in pred._last_precool_zones      # visited, refused, still tracked
    _install_cm(hass, mods, pre_cond=True, energy_on=False)
    n = len(hass.services.calls)
    await _pass(coord, hass, add=False, when=datetime(2026, 7, 1, 11, 5))
    assert tok.returned is False and _tok(coord) is tok
    assert Z2 in coord._pre_arrival_zones
    # No release, no second begin on Z2 (zones 1/3 hold energy tokens and
    # are released as today).
    assert [c for c in hass.services.calls[n:] if c[2].get("entity_id") == E2] == []
    assert len(_cool_rows(hass, mods)) + len(_heat_rows(hass, mods)) == 1


@pytest.mark.asyncio
async def test_energy_precool_gate_off_releases_energy_token(mods, monkeypatch):
    coord, hass, db, _ = _summer(mods, monkeypatch, 80.0)
    pred = coord._predictor
    pred._first_eval_done = True
    _install_cm(hass, mods, pre_cond=True, energy_on=True)
    monkeypatch.setattr(pred, "_should_energy_precool", lambda c, n: True)
    await pred._check_pre_conditioning(None, "home_day", datetime(2026, 7, 1, 11, 0),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    tok = _tok(coord)
    assert tok.caller_site == "S12_pre_cool"
    _install_cm(hass, mods, pre_cond=True, energy_on=False)
    await pred._check_pre_conditioning(None, "home_day", datetime(2026, 7, 1, 11, 5),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "banking_release"


# ==========================================================================
# D2 — arrival pre-heat (winter: Home 72/70 -> effective_low 72, high 74)
# ==========================================================================


@pytest.mark.asyncio
async def test_preheat_below_target_begins_and_writes(mods, monkeypatch):
    """T 69, Home heat 70, live 60-78 -> BANKING S13_pre_arrival, write 72/78."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=69.0)
    await _pass(coord, hass)
    rows = _heat_rows(hass, mods)
    assert [(r["values_after"]["target_temp_low"], r["values_after"]["target_temp_high"])
            for r in rows] == [(72.0, 78.0)]
    tok = _tok(coord)
    assert tok.caller_site == "S13_pre_arrival"
    assert tok.kind == mods["hvac_excursion"].EXCURSION_KIND.BANKING
    assert rows[0]["excursion_id"] == tok.excursion_id
    assert (tok.pre_target_low, tok.pre_target_high) == (70.0, 72.0)
    assert _cool_rows(hass, mods) == []
    assert int(coord._predictor._preheat_writes_today) == 1


@pytest.mark.asyncio
async def test_preheat_at_target_stands_down(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=72.0)
    await _pass(coord, hass)
    assert _heat_rows(hass, mods) == [] and db.state == {}
    assert ("heat", "heat_standdown") in {(s["leg"], s["reason"]) for s in _skips(coord)}


@pytest.mark.parametrize("temp,writes", [(65.0, True), (71.0, True), (72.0, False)])
@pytest.mark.asyncio
async def test_preheat_compares_effective_low_not_live_low(mods, monkeypatch, temp, writes):
    """Live low is 60: a compare against it (or `<=` the wrong way) would stand
    T 65 down; against effective_low 72 it writes 72."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=temp)
    await _pass(coord, hass)
    vals = [r["values_after"]["target_temp_low"] for r in _heat_rows(hass, mods)]
    assert vals == ([72.0] if writes else [])


@pytest.mark.parametrize("temp", [None, "unavailable"])
@pytest.mark.asyncio
async def test_preheat_none_temperature_fails_closed(mods, monkeypatch, temp):
    """The heat leg alone (in a pass the cool leg fails OPEN on None and
    begins first): no begin, zero funnel calls."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    z = coord.zone_manager.zones[Z2]
    z.current_temperature = temp
    n = len(hass.services.calls)
    out = await coord._predictor._execute_zone_pre_heat_arrival(z)
    await H.drain(hass)
    assert out == "no_temp"
    assert hass.services.calls[n:] == [] and db.state == {} and db.events == []
    assert ("heat", "no_temp") in {(s["leg"], s["reason"]) for s in _skips(coord)}


@pytest.mark.asyncio
async def test_preheat_deadband_cap(mods, monkeypatch):
    """Live high 73, Home 76/72 -> effective_low = 73 - 2 = 71 (not 74)."""
    seasonal = {**WINTER, "home": (76.0, 72.0)}
    coord, hass, db, _ = _setup(mods, monkeypatch, seasonal=seasonal, high=73.0, temp=65.0)
    await _pass(coord, hass)
    assert [r["values_after"]["target_temp_low"] for r in _heat_rows(hass, mods)] == [71.0]


@pytest.mark.asyncio
async def test_preheat_capped_at_arrival_cool_narrow_gap(mods, monkeypatch):
    """Winter Home 73/72 (gap 1), live 60-78, T 70 -> effective_low 73 (capped
    at Home cool), not 74."""
    seasonal = {**WINTER, "home": (73.0, 72.0)}
    coord, hass, db, _ = _setup(mods, monkeypatch, seasonal=seasonal, temp=70.0)
    await _pass(coord, hass)
    assert [r["values_after"]["target_temp_low"] for r in _heat_rows(hass, mods)] == [73.0]


@pytest.mark.asyncio
async def test_preheat_band_inverted_floor_65_no_write(mods, monkeypatch):
    """Floor 65, winter defaults, Away 78/60: effective_high 70 < effective_low
    72. T 69: cool stands down, heat skips band_inverted, zero heat writes."""
    coord, hass, db, _ = _setup(mods, monkeypatch, floor=65.0, temp=69.0)
    await _pass(coord, hass)
    assert _heat_rows(hass, mods) == [] and _cool_rows(hass, mods) == []
    reasons = {(s["leg"], s["reason"]) for s in _skips(coord)}
    assert ("cool", "cool_standdown") in reasons and ("heat", "band_inverted") in reasons
    inv = [s for s in _skips(coord) if s["reason"] == "band_inverted"][0]
    assert (inv["effective_low"], inv["effective_high"]) == (72.0, 70.0)


@pytest.mark.asyncio
async def test_cool_floor_65_winter_unchanged(mods, monkeypatch):
    """Pinned pre-existing (INV-NOOP, not endorsed; card
    HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1): floor 65, T 71 -> cool writes 70."""
    coord, hass, db, _ = _setup(mods, monkeypatch, floor=65.0, temp=71.0)
    await _pass(coord, hass)
    assert [r["values_after"]["target_temp_high"] for r in _cool_rows(hass, mods)] == [70.0]
    assert _heat_rows(hass, mods) == []


@pytest.mark.asyncio
async def test_preheat_skipped_when_cool_leg_began(mods, monkeypatch):
    """INV-ONE-LEG: the cool leg begins (T 80 > 74) -> the heat leg is not
    evaluated in that pass (no heat skip entry at all)."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=80.0)
    await _pass(coord, hass)
    assert len(_cool_rows(hass, mods)) == 1 and _heat_rows(hass, mods) == []
    assert [s for s in _skips(coord) if s["leg"] == "heat"] == []


@pytest.mark.asyncio
async def test_preheat_respects_foreign_borrow(mods, monkeypatch):
    """A live COMPROMISE row -> neither leg writes."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=Z2, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=900,
                      pre_preset="manual", site="S3_compromise")
    await _pass(coord, hass)
    z = coord.zone_manager.zones[Z2]
    out = await coord._predictor._execute_zone_pre_heat_arrival(z)
    await H.drain(hass)
    assert out == "foreign_borrow"
    assert _heat_rows(hass, mods) == [] and _cool_rows(hass, mods) == []


@pytest.mark.asyncio
async def test_preheat_ends_on_arrival_presets_only(mods, monkeypatch):
    """C1: HVAC arrival ends the heat borrow `pre_arrival_arrived` with a
    presets-only pin of the snapshot and no further setpoint write."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    await _pass(coord, hass)
    tok = _tok(coord)
    _occ(mods, coord, Z2, lighting=True, hvac=True)
    n_temp = len(H.temp_writes(hass, E2))
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert reasons == {Z2: "arrived"}
    await coord._async_end_pre_arrival_borrows(reasons)
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_arrived"
    assert H.preset_writes(hass, E2, "away")
    assert len(H.temp_writes(hass, E2)) == n_temp
    assert Z2 not in coord._predictor._banking_excursion_tokens


@pytest.mark.asyncio
async def test_preheat_max_age_spends_episode(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    _arrive_setup(coord)
    await _pass(coord, hass)
    tok = _tok(coord)
    coord._pre_arrival_window_minutes = 20
    ex = mods["hvac_excursion"]
    frozen = 1_900_000_000.0
    monkeypatch.setattr(ex, "_now", lambda: frozen)
    tok.started_ts = frozen - 20 * 60
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok._return_outcome.trigger == "pre_arrival_max_age"
    assert Z2 in coord._pre_arrival_spent and Z2 not in coord._pre_arrival_zones
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 not in coord._pre_arrival_zones
    await _pass(coord, hass, add=False)
    assert len(_heat_rows(hass, mods)) == 1


async def _begin_heat_then_person(mods, monkeypatch, house_state="home_night"):
    coord, hass, db, sched = _setup(mods, monkeypatch, temp=65.0, house_state=house_state)
    await _pass(coord, hass, house_state=house_state)
    tok = _tok(coord)
    assert tok.caller_site == "S13_pre_arrival"
    arr = coord._override_arrester
    arr.unsuppress(E2)
    await _fire(hass, arr, _ev(E2, ("manual", 72.0, 78.0), ("manual", 66.0, 78.0)))
    return coord, hass, db, sched, tok


@pytest.mark.parametrize("house_state,expected", [("home_night", "home"), ("sleep", "sleep")])
@pytest.mark.asyncio
async def test_preheat_interrupt_uses_arrival_reference(mods, monkeypatch, house_state, expected):
    """C4: a person ends the heat borrow -> human_interrupt, no write, latch,
    reference = the ARRIVAL preset (never the `away` snapshot)."""
    coord, hass, db, sched, tok = await _begin_heat_then_person(mods, monkeypatch, house_state)
    assert tok.returned and tok._return_outcome.trigger == "human_interrupt"
    assert tok._return_outcome.restore_ok is None
    assert coord._override_arrester.interrupt_latched(E2)
    rows = hass.data[mods["const"].DOMAIN]["activity_logger"].actions("override_detected")
    d = rows[-1]["details"]
    assert d["reference_preset"] == expected


@pytest.mark.asyncio
async def test_preheat_interrupt_spends_episode(mods, monkeypatch):
    """C3: the interrupted heat borrow clears the zone as `interrupted` and
    spends the arrival episode."""
    coord, hass, db, sched, tok = await _begin_heat_then_person(mods, monkeypatch)
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert reasons == {Z2: "interrupted"}
    assert Z2 in coord._pre_arrival_spent


@pytest.mark.asyncio
async def test_preheat_interrupt_inside_begin_spends_episode(mods, monkeypatch):
    """W4 (M1 exit): a person's change lands inside `begin_excursion`'s DB
    save for the heat leg -> no heat write, the row closes `human_interrupt`,
    and the arrival episode is spent (the token was never stored)."""
    import asyncio
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    arr = coord._override_arrester

    async def _hook(row):
        arr._handle_climate_change(_ev(E2, ("away", 60.0, 78.0), ("manual", 60.0, 71.0)))
        await asyncio.sleep(0)
    db.save_hook = _hook
    await _pass(coord, hass)
    await H.drain(hass, rounds=6)
    assert _heat_rows(hass, mods) == []
    assert db.events and db.events[-1]["trigger"] == "human_interrupt"
    assert Z2 not in coord._pre_arrival_zones and Z2 in coord._pre_arrival_spent


@pytest.mark.asyncio
async def test_preheat_master_off_is_pre_arrival_inactive(mods, monkeypatch):
    """C2: switch 28 OFF ends the heat borrow `pre_arrival_inactive` and
    spends the episode."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    await _pass(coord, hass)
    tok = _tok(coord)
    _install_cm(hass, mods, pre_cond=False)
    await _pass(coord, hass, add=False)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_inactive"
    assert Z2 in coord._pre_arrival_spent


@pytest.mark.asyncio
async def test_preheat_zi_off_is_pre_arrival_inactive(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    await _pass(coord, hass)
    tok = _tok(coord)
    coord._zone_intelligence_enabled = False
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_inactive"


@pytest.mark.asyncio
async def test_preheat_boot_audit_releases_row(mods, monkeypatch):
    """A restart with the heat row live: the boot audit releases it
    `stale_boot_release` (BANKING), pinning the snapshot preset."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    await _pass(coord, hass)
    assert db.state[Z2]["caller_site"] == "S13_pre_arrival"
    ex = mods["hvac_excursion"]
    ex._test_clear_leases()
    n = len(H.preset_writes(hass, E2, "away"))
    await ex.async_startup_excursion_audit(hass, coord)
    await H.drain(hass)
    assert Z2 not in db.state
    assert any(e.get("trigger") == "stale_boot_release" for e in db.events)
    assert len(H.preset_writes(hass, E2, "away")) == n + 1


@pytest.mark.asyncio
async def test_energy_preheat_refused_over_prearrival_heat(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    await _pass(coord, hass)
    _occ(mods, coord, Z2, hvac=True)
    await coord._predictor._execute_pre_heat()
    await H.drain(hass)
    energy = [r for r in H.climate_write_rows(hass, mods, "S13_pre_heat")
              if r.get("reason") == "pre_heat"]
    assert energy == []
    assert Z2 not in getattr(coord._predictor, "_preheat_excursion_tokens", {})


@pytest.mark.asyncio
async def test_preheat_kill_const_false_never_writes(mods, monkeypatch):
    monkeypatch.setattr(mods["hvac_predict"], "PRE_ARRIVAL_PREHEAT_ENABLED", False)
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=60.0)
    await _pass(coord, hass)
    assert _heat_rows(hass, mods) == [] and db.state == {}


@pytest.mark.asyncio
async def test_preheat_deferred_write_two_passes_one_begin(mods, monkeypatch):
    """M3 bound: a comfort-delay gate defers the heat write; each pass begins
    at most ONE heat borrow, which the CM releases (two passes -> two
    begin/release pairs, no write, no token)."""
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=65.0)
    monkeypatch.setattr(coord._override_arrester, "comfort_delay_active", lambda z: True)
    await _pass(coord, hass)
    await _pass(coord, hass)
    ev = [e for e in db.events if e.get("site") == "S13_pre_arrival"]
    assert len(ev) == 2
    assert _heat_rows(hass, mods) == [] and _tok(coord) is None


# --- the stand-down activity row (L1 rule + membership key) ---------------


@pytest.mark.asyncio
async def test_one_standdown_row_per_membership(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=73.0)
    await _pass(coord, hass)
    await _pass(coord, hass)
    rows = _standdown_rows(hass, mods)
    assert len(rows) == 1
    d = rows[0]["details"]
    assert (d["T"], d["effective_low"], d["effective_high"], d["margin"], d["hvac_mode"]) == (
        73.0, 72.0, 74.0, 0.0, "heat_cool")
    assert int(coord._predictor._prearrival_standdowns_today) == 1
    coord._pre_arrival_zones.discard(Z2)
    await _pass(coord, hass, add=False)
    await _pass(coord, hass)
    assert len(_standdown_rows(hass, mods)) == 2


@pytest.mark.parametrize("case,kw,row", [
    # cool stand-down (T 74 <= 75) + heat setpoint skip (72 <= live low 72)
    ("cool_sd_heat_setpoint", dict(seasonal=SUMMER, low=72.0, high=82.0, temp=74.0), True),
    # both setpoint skips (live 72/75)
    ("both_setpoint", dict(seasonal=SUMMER, low=72.0, high=75.0, temp=74.0), False),
    # cool no_temp -> legacy write began -> no row
    ("cool_no_temp_began", dict(seasonal=SUMMER, low=60.0, high=82.0, temp=None), False),
    # cool setpoint skip (74 >= live 74) + heat stand-down (T 73 >= 72)
    ("cool_setpoint_heat_sd", dict(low=60.0, high=74.0, temp=73.0), True),
    # both legs mode-excluded
    ("both_mode_excluded", dict(mode="off", temp=73.0), False),
    # cool stand-down (T 65 <= 74) + heat began -> no row (its rows exist)
    ("cool_sd_heat_began", dict(temp=65.0), False),
])
@pytest.mark.asyncio
async def test_standdown_row_rule_table(mods, monkeypatch, case, kw, row):
    coord, hass, db, _ = _setup(mods, monkeypatch, **kw)
    await _pass(coord, hass)
    assert len(_standdown_rows(hass, mods)) == (1 if row else 0), case


# ==========================================================================
# D3 — leg/mode table
# ==========================================================================


@pytest.mark.parametrize("mode,temp,cool_writes,heat_writes", [
    ("heat", 80.0, False, False),
    ("heat", 65.0, False, False),
    ("cool", 65.0, False, False),
    ("cool", 80.0, True, False),
    ("off", 80.0, False, False),
    ("off", 65.0, False, False),
    ("auto", 65.0, False, False),
    ("heat_cool", 80.0, True, False),
    ("heat_cool", 65.0, False, True),
])
@pytest.mark.asyncio
async def test_leg_mode_table(mods, monkeypatch, mode, temp, cool_writes, heat_writes):
    coord, hass, db, _ = _setup(mods, monkeypatch, mode=mode, temp=temp)
    await _pass(coord, hass)
    assert bool(_cool_rows(hass, mods)) is cool_writes
    assert bool(_heat_rows(hass, mods)) is heat_writes


@pytest.mark.parametrize("mode", ["", "unknown"])
@pytest.mark.asyncio
async def test_unreadable_mode_cool_open_heat_closed(mods, monkeypatch, mode):
    coord, hass, db, _ = _setup(mods, monkeypatch, mode="heat_cool", temp=80.0)
    coord.zone_manager.zones[Z2].hvac_mode = mode
    await _pass(coord, hass)
    assert len(_cool_rows(hass, mods)) == 1          # cool fails open
    coord2, hass2, db2, _ = _setup(mods, monkeypatch, mode="heat_cool", temp=65.0)
    coord2.zone_manager.zones[Z2].hvac_mode = mode
    await _pass(coord2, hass2)
    assert _heat_rows(hass2, mods) == []              # heat fails closed
    assert ("heat", "mode_unreadable") in {(s["leg"], s["reason"]) for s in _skips(coord2)}


# ==========================================================================
# D4 — status sensor attrs
# ==========================================================================


@pytest.mark.asyncio
async def test_status_sensor_exposes_prearrival_attrs(mods, monkeypatch):
    from custom_components.universal_room_automation import sensor as sensor_mod
    coord, hass, db, _ = _setup(mods, monkeypatch, temp=73.0)
    await _pass(coord, hass)
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": coord})
    ent = sensor_mod.HVACPreArrivalDiagnosticSensor(hass, hass.config_entries._entries[0])
    a = ent.extra_state_attributes
    assert a["prearrival_standdowns_today"] == 1
    assert a["precool_writes_today"] == 0 and a["preheat_writes_today"] == 0
    assert {(s["leg"], s["reason"]) for s in a["prearrival_skips"]} == {
        ("cool", "cool_standdown"), ("heat", "heat_standdown")}


# ==========================================================================
# §4.3 lint — no raw S12_PRE_ARRIVAL_SITE equality comparison remains
# ==========================================================================


def test_no_raw_s12_prearrival_site_comparisons():
    """Every 'is this a pre-arrival borrow' reader tests membership in
    PRE_ARRIVAL_CALLER_SITES (plan §4.3). AST: no ==/!= Compare in
    domain_coordinators/ with S12_PRE_ARRIVAL_SITE (or an import alias of it)
    or the literal 'S12_pre_arrival' as an operand."""
    root = Path(__file__).resolve().parents[2] / "custom_components" / \
        "universal_room_automation" / "domain_coordinators"
    offenders = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text())
        names = {"S12_PRE_ARRIVAL_SITE"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "S12_PRE_ARRIVAL_SITE" and a.asname:
                        names.add(a.asname)

        def _is_site(n):
            if isinstance(n, ast.Name) and n.id in names:
                return True
            if isinstance(n, ast.Attribute) and n.attr == "S12_PRE_ARRIVAL_SITE":
                return True
            return isinstance(n, ast.Constant) and n.value == "S12_pre_arrival"
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops
            ):
                if any(_is_site(x) for x in [node.left, *node.comparators]):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
