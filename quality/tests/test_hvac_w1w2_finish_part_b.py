"""HVAC W1/W2 finish — PART B: the pre-arrival borrow's lifetime.

Plan: docs/planning/PLANNING_hvac_w1_w2_finish.md REV 2, D3 / D4 / D5.

Falsifiable invariant (plan §B.1):

INV-B  For every borrow with caller_site `S12_pre_arrival` on zone Z:
         1. exactly ONE S12 `set_temperature` carries its id, with
            target_temp_high = max(baseline_high + PRE_ARRIVAL_PRECOOL_OFFSET_F,
            floor)  (no ratchet across repeated triggers);
         2. it ends with a trigger in {pre_arrival_arrived, pre_arrival_timeout,
            pre_arrival_interrupted, pre_arrival_inactive, pre_arrival_max_age,
            human_interrupt} — carve-outs stale_boot_release (restart) and
            the CM s12_banking_wire_failed release — NEVER `lease_expiry`;
         3. it ends in the first FULL pass, or the first fast run scoped to
            Z, that removes Z from the set, finds pre-arrival inactive, or
            finds the borrow >= the window old — BEFORE S1 in that pass;
         4. no S12 / S13 write lands on Z while another borrow row is live.

Knob 35 `Pre-Arrival Window (min)` (5-110) interacts with the 7200 s
EXCURSION_LEASE_MAX_S backstop — tested at both extremes.

Drives the REAL coordinator / predictor / excursion primitive (W1-B
harness). Boundary values are hardcoded literals, never the imported
constant.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402

Z1, E1 = "zone_1", "climate.test_zone_1"
Z2, E2 = "zone_2", "climate.test_zone_2"
SEASONAL = {"home": (76.0, 70.0), "away": (80.0, 68.0), "sleep": (76.0, 70.0)}


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
    # Leave no residue in module-global registries for later files.
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


class EventDB(H.FakeDB):
    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    async def log_excursion_event(self, **kw):
        self.events.append(dict(kw))


def _setup(mods, monkeypatch, *, zones=(Z2,), house_state="home_night", seasonal=SEASONAL):
    coord, hass = H.make_coord(mods)
    coord._house_state = house_state
    coord._zone_intelligence_enabled = True
    coord._boot_settle_done = True
    coord._zone_state_store = H.FakeStore()
    mods["hvac_setpoint"]._test_clear_ura_setpoints()
    pm = coord._preset_manager
    monkeypatch.setattr(pm, "get_seasonal_setpoints",
                        lambda p, season=None: seasonal.get(p))
    pm._current_season = "summer"
    sched = FakeScheduler()
    for m in ("hvac_override", "hvac_predict", "hvac"):
        monkeypatch.setattr(mods[m], "async_call_later", sched)
    db = EventDB()
    mods["hvac_excursion"]._test_bind(hass=hass, db=db)
    for zid in zones:
        z = coord.zone_manager.zones[zid]
        z.target_temp_low, z.target_temp_high, z.preset_mode = 68.0, 80.0, "away"
        H.set_climate(hass, z.climate_entity, preset_mode="away",
                      hold_activity="away", low=68.0, high=80.0)
        _occ(mods, coord, zid)
    return coord, hass, db, sched


def _occ(mods, coord, zid, *, lighting=False, hvac=False):
    RC = mods["hvac_zones"].RoomCondition
    coord.zone_manager.zones[zid].room_conditions = [
        RC(room_name=f"r_{zid}", occupied=lighting, hvac_occupied=hvac)]


def _s12(hass, mods):
    return H.climate_write_rows(hass, mods, "S12_pre_cool")


async def _pre_arrival(coord, hass, zid=Z2):
    coord._pre_arrival_zones.add(zid)
    coord._pre_arrival_start[zid] = datetime.now(timezone.utc)
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 3, 51),
        pre_arrival_zones=set(coord._pre_arrival_zones),
        zone_intelligence_enabled=True)
    await H.drain(hass)


def _tok(coord, zid=Z2):
    return getattr(coord._predictor, "_banking_excursion_tokens", {}).get(zid)


FROZEN = 1_900_000_000.0


def _age(mods, tok, seconds, monkeypatch=None):
    """Age the token by exactly ``seconds``; with ``monkeypatch`` the
    excursion clock is frozen so boundary tests are exact."""
    ex = mods["hvac_excursion"]
    if monkeypatch is not None:
        monkeypatch.setattr(ex, "_now", lambda: FROZEN)
        tok.started_ts = FROZEN - float(seconds)
    else:
        tok.started_ts = ex._now() - float(seconds)


# ==========================================================================
# D4 — one write, from the baseline
# ==========================================================================


@pytest.mark.parametrize("status_lag", [False, True])
@pytest.mark.asyncio
async def test_pre_arrival_single_write_across_three_triggers(mods, monkeypatch, status_lag):
    """With `status_lag` the zone keeps reading away 80 (the STATUS feed
    lags the hold, §5 / C22): the value would be identical each time, so
    only the no-second-begin guard keeps it to ONE write under the id."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    for _ in range(3):
        await _pre_arrival(coord, hass)
        z = coord.zone_manager.zones[Z2]
        if not status_lag:
            z.target_temp_high = 74.0   # the zone now reads the pre-cool value
    rows = _s12(hass, mods)
    assert len(rows) == 1
    assert rows[0]["values_after"]["target_temp_high"] == 74.0
    tok = _tok(coord)
    assert tok.caller_site == "S12_pre_arrival" and rows[0]["excursion_id"] == tok.excursion_id
    assert rows[0]["reason"] == "pre_arrival"


@pytest.mark.asyncio
async def test_pre_arrival_value_from_baseline_not_live(mods, monkeypatch):
    """Baseline (the arrival preset's configured 69/77 — CPR D3c: the
    retired emitted-range map no longer feeds it) - 2 = 75; the live-based
    value would be 80 - 2 = 78."""
    seasonal = {**SEASONAL, "home": (77.0, 69.0), "sleep": (77.0, 69.0)}
    coord, hass, db, _ = _setup(mods, monkeypatch, seasonal=seasonal)
    await _pre_arrival(coord, hass)
    assert [r["values_after"]["target_temp_high"] for r in _s12(hass, mods)] == [75.0]


@pytest.mark.asyncio
async def test_pre_arrival_floor_kept(mods, monkeypatch):
    """Baseline 73 - 2 = 71 is below the 72 F floor -> 72."""
    seasonal = {**SEASONAL, "home": (73.0, 68.0), "sleep": (73.0, 68.0)}
    coord, hass, db, _ = _setup(mods, monkeypatch, seasonal=seasonal)
    await _pre_arrival(coord, hass)
    assert [r["values_after"]["target_temp_high"] for r in _s12(hass, mods)] == [72.0]


@pytest.mark.asyncio
async def test_pre_arrival_never_warms_the_zone(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    coord.zone_manager.zones[Z2].target_temp_high = 73.0   # already cooler than 74
    await _pre_arrival(coord, hass)
    assert _s12(hass, mods) == [] and _tok(coord) is None


@pytest.mark.asyncio
async def test_pre_arrival_baseline_none_no_write(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, seasonal={})
    await _pre_arrival(coord, hass)
    assert _s12(hass, mods) == []
    assert mods["hvac_excursion"].live_token_for(Z2) is None


@pytest.mark.asyncio
async def test_precool_floor_reads_runtime_solar_bank_floor(mods, monkeypatch):
    """Converted from a source grep (test_v4510): the floor is the RUNTIME
    `_solar_bank_floor` (68 here), not the 72 F module constant."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    pred = coord._predictor
    pred._solar_bank_floor = 68.0
    z = coord.zone_manager.zones[Z2]
    z.target_temp_high, z.target_temp_low = 78.0, 60.0
    await pred._execute_zone_pre_cool(z, offset=-20.0, reason="energy_precool")
    await H.drain(hass)
    assert [r["values_after"]["target_temp_high"] for r in _s12(hass, mods)] == [68.0]


# ==========================================================================
# D4b — never write over another borrow (S12 and S13)
# ==========================================================================


@pytest.mark.asyncio
async def test_s12_never_writes_over_foreign_row(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=Z2, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=900,
                      pre_preset="manual", site="S3_compromise")
    z = coord.zone_manager.zones[Z2]
    z.target_temp_high = 78.0
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    assert _s12(hass, mods) == []


@pytest.mark.asyncio
async def test_s13_never_writes_over_foreign_row(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch, zones=(Z1, Z2))
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=Z2, kind=ex.EXCURSION_KIND.NUDGE, duration_s=120,
                      pre_preset="home", site="S5_nudge_start")
    for zid in coord.zone_manager.zones:
        _occ(mods, coord, zid, hvac=(zid == Z2))
    await coord._predictor._execute_pre_heat()
    await H.drain(hass)
    assert H.climate_write_rows(hass, mods, "S13_pre_heat") == []
    assert Z2 not in getattr(coord._predictor, "_preheat_return_timers", {})


@pytest.mark.asyncio
async def test_energy_precool_own_row_behaviour_unchanged(mods, monkeypatch):
    """S12 energy pre-cool re-writing on its OWN row (the energy ratchet is
    a non-goal, carded HVAC-ENERGY-PRECOOL-RATCHET-1): unchanged."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    z = coord.zone_manager.zones[Z2]
    z.target_temp_high = 80.0
    pred = coord._predictor
    await pred._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    z.target_temp_high = 77.0
    await pred._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    rows = _s12(hass, mods)
    assert [r["values_after"]["target_temp_high"] for r in rows] == [77.0, 74.0]
    assert _tok(coord).caller_site == "S12_pre_cool"


@pytest.mark.asyncio
async def test_s12_stale_own_token_does_not_license_foreign_row(mods, monkeypatch):
    """D4b conjunct `same id`: the path's token map still holds an OLD
    S12_pre_cool token, but the live row is a DIFFERENT borrow -> no write."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    ex = mods["hvac_excursion"]
    old = ex._test_seed_row(zone_id=Z2, kind=ex.EXCURSION_KIND.BANKING, duration_s=None,
                            pre_preset="away", site="S12_pre_cool")
    ex._rows.pop(Z2)
    coord._predictor._banking_excursion_tokens = {Z2: old}
    live = ex._test_seed_row(zone_id=Z2, kind=ex.EXCURSION_KIND.BANKING, duration_s=None,
                             pre_preset="away", site="S12_pre_cool")
    live.excursion_id = "banking:zone_2:other"
    z = coord.zone_manager.zones[Z2]
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    assert _s12(hass, mods) == []


@pytest.mark.asyncio
async def test_reconciliation_ignores_energy_precool_borrows(mods, monkeypatch):
    """Only S12_pre_arrival borrows are ended by D3; an energy pre-cool on a
    zone outside the pre-arrival set keeps running."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    z = coord.zone_manager.zones[Z2]
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    tok = _tok(coord)
    assert tok.caller_site == "S12_pre_cool"
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok.returned is False


@pytest.mark.asyncio
async def test_energy_precool_does_not_write_over_pre_arrival_row(mods, monkeypatch):
    """The pre-arrival row is not the ENERGY path's own row (same id but a
    different caller_site): no energy write over it."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    z = coord.zone_manager.zones[Z2]
    z.target_temp_high = 74.0
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    await H.drain(hass)
    assert len(_s12(hass, mods)) == 1


# ==========================================================================
# D3 — end conditions
# ==========================================================================


def _heavy(coord):
    return [
        patch.object(coord.zone_manager, "update_all_zones"),
        patch.object(coord.zone_manager, "update_room_conditions"),
        patch.object(coord, "_drain_hvac_degraded_room_events", new=AsyncMock()),
        patch.object(coord, "_check_carrier_freshness", new=AsyncMock()),
        patch.object(coord._egress_manager, "async_tick", new=AsyncMock()),
        patch.object(coord._override_arrester, "check_ac_reset", new=AsyncMock()),
        patch.object(coord._fan_controller, "update", new=AsyncMock()),
        patch.object(coord._cover_controller, "update", new=AsyncMock()),
        patch.object(coord._predictor, "update", new=AsyncMock()),
        patch.object(coord, "_record_anomaly_observations", new=AsyncMock()),
        patch.object(coord, "async_save_zone_state", new=AsyncMock()),
        patch.object(coord, "_emit_and_reset_short_cycles", new=AsyncMock()),
    ]


@pytest.mark.asyncio
async def test_pre_arrival_ends_on_hvac_arrival_before_s1(mods, monkeypatch):
    """Full pass: arrival (HVAC occupancy) -> the borrow's snapshot preset is
    pinned BEFORE S1 runs in the same pass (order: pin, then S1)."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._startup_audit_done = True
    _occ(mods, coord, Z2, lighting=True, hvac=True)
    seen_at_s1: list[int] = []

    async def _s1(*a, **k):
        seen_at_s1.append(len(H.preset_writes(hass, E2, "away")))
        return False
    ps = _heavy(coord) + [patch.object(coord, "_apply_house_state_presets", new=_s1)]
    for p in ps:
        p.start()
    try:
        await coord._run_decision_cycle()
    finally:
        for p in ps:
            p.stop()
    await H.drain(hass)
    assert seen_at_s1 == [1]
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_arrived"
    assert Z2 not in coord._pre_arrival_zones


@pytest.mark.asyncio
async def test_pre_arrival_runs_in_observation_mode(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._startup_audit_done = True
    coord._observation_mode = True
    _occ(mods, coord, Z2, lighting=True, hvac=True)
    ps = _heavy(coord) + [patch.object(coord, "_apply_house_state_presets", new=AsyncMock())]
    for p in ps:
        p.start()
    try:
        await coord._run_decision_cycle()
    finally:
        for p in ps:
            p.stop()
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_arrived"


@pytest.mark.parametrize("minutes,elapsed_s,ends", [
    (20, 20 * 60 + 60, True),
    (20, 20 * 60 - 60, False),
])
@pytest.mark.asyncio
async def test_pre_arrival_ends_on_timeout_knob(mods, monkeypatch, minutes, elapsed_s, ends):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._pre_arrival_window_minutes = minutes
    now = datetime.now(timezone.utc)
    coord._pre_arrival_start[Z2] = now - timedelta(seconds=elapsed_s)
    reasons = coord._expire_pre_arrival_zones(now)
    await coord._async_end_pre_arrival_borrows(reasons)
    await H.drain(hass)
    assert tok.returned is ends
    if ends:
        assert tok._return_outcome.trigger == "pre_arrival_timeout"
        assert H.preset_writes(hass, E2, "away")


@pytest.mark.parametrize("age_s,ends", [(30 * 60, True), (30 * 60 - 1, False)])
@pytest.mark.asyncio
async def test_pre_arrival_max_age_with_repeated_triggers(mods, monkeypatch, age_s, ends):
    """M5: triggers keep resetting the pre-arrival clock (the zone stays in
    the set) — the BORROW's own start bounds it at the window (30 min)."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._pre_arrival_window_minutes = 30
    _age(mods, tok, age_s, monkeypatch)
    coord._pre_arrival_start[Z2] = datetime.now(timezone.utc)   # a fresh trigger
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert reasons == {}
    await coord._async_end_pre_arrival_borrows(reasons)
    await H.drain(hass)
    assert tok.returned is ends
    if ends:
        assert tok._return_outcome.trigger == "pre_arrival_max_age"
        assert Z2 not in coord._pre_arrival_zones
    else:
        assert Z2 in coord._pre_arrival_zones


@pytest.mark.parametrize("window,age_s,ends", [
    (110, 110 * 60, True),     # 6600 s < 7200 s lease cap
    (110, 110 * 60 - 1, False),
    (5, 5 * 60, True),
    (5, 5 * 60 - 1, False),
])
@pytest.mark.asyncio
async def test_knob_extremes_end_before_lease_sweep(mods, monkeypatch, window, age_s, ends):
    """Config extremes of knob 35 vs EXCURSION_LEASE_MAX_S (7200 s): the
    reconciliation ends the borrow at the window; the lease sweep, run at
    the same instant, has nothing stale to release (never `lease_expiry`)."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._pre_arrival_window_minutes = window
    _age(mods, tok, age_s, monkeypatch)
    ex = mods["hvac_excursion"]
    assert await ex._auto_release_sweep(coord) == 0
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok.returned is ends
    if ends:
        assert tok._return_outcome.trigger == "pre_arrival_max_age"
    assert not [e for e in db.events if e["trigger"] == "lease_expiry"]


@pytest.mark.parametrize("raw,clamped", [(0, 5), (4, 5), (200, 110), (111, 110),
                                        (30, 30), ("bad", 30)])
def test_pre_arrival_window_clamp(mods, raw, clamped):
    assert mods["hvac_const"].clamp_hvac_pre_arrival_window_minutes(raw) == clamped


def test_pre_arrival_window_clamped_in_constructor(mods):
    HVAC = mods["hvac"].HVACCoordinator
    from runtime_harness import build_smoke_hass
    c = HVAC(build_smoke_hass(), pre_arrival_window_minutes=500)
    assert c._pre_arrival_window_minutes == 110
    assert c._pre_arrival_window_s() == 6600.0


@pytest.mark.asyncio
async def test_hallway_lighting_does_not_end_pre_arrival(mods, monkeypatch):
    """P4: a hallway crossing (lighting occupied, HVAC not) must not end it."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    _occ(mods, coord, Z2, lighting=True, hvac=False)
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert reasons == {} and Z2 in coord._pre_arrival_zones


@pytest.mark.asyncio
async def test_zi_off_ends_pre_arrival_borrows(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._zone_intelligence_enabled = False
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_inactive"


@pytest.mark.asyncio
async def test_interrupted_zone_cleared_and_fans_left_on(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    await mods["hvac_excursion"].return_excursion(tok, trigger="human_interrupt", restore_ok=None)
    defan = []
    monkeypatch.setattr(coord, "_deactivate_zone_fans", AsyncMock(side_effect=lambda z: defan.append(z)))
    n = len(hass.services.calls)
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert reasons == {Z2: "interrupted"}
    await coord._async_end_pre_arrival_borrows(reasons)
    await H.drain(hass)
    assert hass.services.calls[n:] == [] and defan == []
    assert Z2 not in coord._predictor._banking_excursion_tokens


@pytest.mark.asyncio
async def test_fast_run_ends_only_its_zone(mods, monkeypatch):
    """M10: a fast run for Z2 ends Z2's pre-arrival borrow before its S1 and
    leaves Z1 untouched; the next full pass ends Z1 before its S1."""
    coord, hass, db, _ = _setup(mods, monkeypatch, zones=(Z1, Z2))
    await _pre_arrival(coord, hass, Z1)
    await _pre_arrival(coord, hass, Z2)
    t1, t2 = _tok(coord, Z1), _tok(coord, Z2)
    for zid in (Z1, Z2):
        _occ(mods, coord, zid, lighting=True, hvac=True)
    # Z1 is ALSO end-eligible (aged past the window) — only the zone scope
    # of the fast run keeps it untouched.
    t1.started_ts = mods["hvac_excursion"]._now() - 31 * 60
    coord._fast_path_enabled = True
    ps = [patch.object(coord.zone_manager, "update_room_conditions"),
          patch.object(coord, "_apply_house_state_presets", new=AsyncMock(return_value=False))]
    for p in ps:
        p.start()
    try:
        await coord._async_zone_fast_run(Z2, "fast_entry")
    finally:
        for p in ps:
            p.stop()
    await H.drain(hass)
    assert t2.returned and t2._return_outcome.trigger == "pre_arrival_arrived"
    assert t1.returned is False and Z1 in coord._pre_arrival_zones
    reasons = coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    await coord._async_end_pre_arrival_borrows(reasons)
    await H.drain(hass)
    assert t1.returned and t1._return_outcome.trigger == "pre_arrival_arrived"


@pytest.mark.asyncio
async def test_pre_arrival_release_is_presets_only(mods, monkeypatch):
    """(CPR D3c: the emitted-range map this used to guard is retired.) The
    pre-arrival end restores the snapshot preset and writes no setpoints."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    n_s12 = len(_s12(hass, mods))
    coord._pre_arrival_zones.discard(Z2)
    await coord._async_end_pre_arrival_borrows({Z2: "arrived"})
    await H.drain(hass)
    assert H.preset_writes(hass, E2, "away")
    assert len(_s12(hass, mods)) == n_s12


# ==========================================================================
# D5 — knob 35
# ==========================================================================


def test_pre_arrival_window_on_hvac_settings_form(mods):
    """Knob 35 is a field of the HVAC settings step with the persisted value
    as its default, 5..110 min, step 5 (knob-52 precedent, M6)."""
    import asyncio as _aio
    from types import SimpleNamespace
    from custom_components.universal_room_automation import config_flow as _cf
    from test_hvac_vacancy_hold_ui_defaults import _walk_schema
    entry = SimpleNamespace(entry_id="cm", options={"hvac_pre_arrival_window_minutes": 45}, data={})
    flow = _cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = MagicMock()
    flow.hass.states.async_all.return_value = []
    flow.hass.states.get.return_value = None
    result = _aio.new_event_loop().run_until_complete(
        flow.async_step_coordinator_hvac_settings(user_input=None)
    )
    found = None
    for marker, value in _walk_schema(result["data_schema"]):
        if getattr(marker, "schema", None) == "hvac_pre_arrival_window_minutes":
            found = (marker, value)
    assert found is not None, "knob 35 missing from the HVAC settings form"
    marker, value = found
    d = marker.default
    assert (d() if callable(d) else d) == 45
    cfg = value.config
    assert (cfg["min"], cfg["max"], cfg["step"], cfg["unit_of_measurement"]) == (5, 110, 5, "min")


@pytest.mark.asyncio
async def test_pre_arrival_window_knob_live_and_persisted(mods, monkeypatch):
    """The Number entity pushes the live attr BEFORE the options writeback,
    and the expiry reads the live value (20 min), not the 30 min default."""
    from custom_components.universal_room_automation import number as number_mod
    coord, hass, db, _ = _setup(mods, monkeypatch)
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": coord})
    entry = hass.config_entries._entries[0]
    entry.options = {}
    n = number_mod.PreArrivalWindowMinutesNumber(hass, entry)
    assert n.name == "35 · Pre-Arrival Window (min)"
    assert n.unique_id == f"{mods['const'].DOMAIN}_hvac_pre_arrival_window_minutes"
    assert (n.native_min_value, n.native_max_value, n.native_step) == (5, 110, 5)
    assert n.native_value == 30
    n.async_write_ha_state = lambda: None
    await n.async_set_native_value(20)
    assert coord._pre_arrival_window_minutes == 20
    assert entry.options["hvac_pre_arrival_window_minutes"] == 20
    await n.async_set_native_value(500)
    assert coord._pre_arrival_window_minutes == 110
    await n.async_set_native_value(20)
    # The expiry uses 20: a trigger 21 min old times out.
    await _pre_arrival(coord, hass)
    now = datetime.now(timezone.utc)
    coord._pre_arrival_start[Z2] = now - timedelta(minutes=21)
    assert coord._expire_pre_arrival_zones(now) == {Z2: "timeout"}


# ==========================================================================
# Fix-up round 1 (reviews A / B / C / D)
# ==========================================================================


@pytest.mark.asyncio
async def test_max_age_end_turns_pre_arrival_fans_off(mods, monkeypatch):
    """A-M1: the max-age end deactivates the zone's pre-arrival fans exactly
    like the timeout branch."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    defan: list = []
    monkeypatch.setattr(coord, "_deactivate_zone_fans",
                        AsyncMock(side_effect=lambda z: defan.append(z.zone_id)))
    _age(mods, tok, 31 * 60, monkeypatch)
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok._return_outcome.trigger == "pre_arrival_max_age"
    assert defan == [Z2]


@pytest.mark.asyncio
async def test_pre_arrival_release_refreshes_zone_preset_before_s1(mods, monkeypatch):
    """F2: after the arrival release pins the snapshot preset, the zone's
    `preset_mode` is refreshed from the entity BEFORE S1 reads it."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    coord._startup_audit_done = True
    z = coord.zone_manager.zones[Z2]
    z.preset_mode = "manual"
    H.set_climate(hass, E2, preset_mode="manual", hold_activity="manual", low=68.0, high=74.0)
    real_call = hass.services.async_call

    async def _apply(domain, service, data=None, blocking=False, **kw):
        await real_call(domain, service, data, blocking=blocking, **kw)
        if service == "set_preset_mode" and data.get("preset_mode") not in ("resume",):
            H.set_climate(hass, data["entity_id"], preset_mode=data["preset_mode"],
                          hold_activity=data["preset_mode"], low=68.0, high=80.0)
    monkeypatch.setattr(hass.services, "async_call", _apply)
    _occ(mods, coord, Z2, lighting=True, hvac=True)
    seen: list = []

    async def _s1(*a, **k):
        seen.append(coord.zone_manager.zones[Z2].preset_mode)
        return False
    from unittest.mock import patch as _p
    ps = [
        _p.object(coord.zone_manager, "update_all_zones"),
        _p.object(coord.zone_manager, "update_room_conditions"),
        _p.object(coord, "_drain_hvac_degraded_room_events", new=AsyncMock()),
        _p.object(coord, "_check_carrier_freshness", new=AsyncMock()),
        _p.object(coord._egress_manager, "async_tick", new=AsyncMock()),
        _p.object(coord._override_arrester, "check_ac_reset", new=AsyncMock()),
        _p.object(coord._fan_controller, "update", new=AsyncMock()),
        _p.object(coord._cover_controller, "update", new=AsyncMock()),
        _p.object(coord._predictor, "update", new=AsyncMock()),
        _p.object(coord, "_record_anomaly_observations", new=AsyncMock()),
        _p.object(coord, "async_save_zone_state", new=AsyncMock()),
        _p.object(coord, "_emit_and_reset_short_cycles", new=AsyncMock()),
        _p.object(coord, "_apply_house_state_presets", new=_s1),
    ]
    for p in ps:
        p.start()
    try:
        await coord._run_decision_cycle()
    finally:
        for p in ps:
            p.stop()
    assert seen == ["away"]


def _install_cm(hass, mods, *, pre_cond=True, energy_on=True):
    DOMAIN = mods["const"].DOMAIN
    hv = MagicMock(); hv.pre_conditioning_enabled = pre_cond
    en = MagicMock(); en.energy_precool_enabled = energy_on
    en.energy_precool_offset = -3.0; en.energy_precool_scope = "whole_house"
    hass.data[DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": hv, "energy": en})


@pytest.mark.asyncio
async def test_s11_skips_person_latched_zone(mods, monkeypatch):
    """D-L1: S11 never writes over a person-latched zone; the row closes as
    `human_interrupt` with no restore attempted."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    z = coord.zone_manager.zones[Z2]
    await coord._predictor._execute_zone_pre_cool(z, offset=-3.0, reason="energy_precool")
    tok = _tok(coord)
    coord._override_arrester._interrupt_latch.add(E2)
    n = len(hass.services.calls)
    await coord._predictor._release_banked_zones({Z2})
    await H.drain(hass)
    assert hass.services.calls[n:] == []
    assert tok.returned and tok._return_outcome.trigger == "human_interrupt"
    assert tok._return_outcome.restore_ok is None


@pytest.mark.asyncio
async def test_orphan_reconciliation_skips_person_latched_zone(mods, monkeypatch):
    """D-L1: the post-restart orphan release (gate OFF, live high below the
    baseline) also skips a latched zone (it routes through S11)."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _install_cm(hass, mods, energy_on=False)
    pred = coord._predictor
    pred._first_eval_done = False
    z = coord.zone_manager.zones[Z2]
    z.target_temp_high = 72.0                       # below home 76 - 0.5
    coord._override_arrester._interrupt_latch.add(E2)
    await pred._check_pre_conditioning(None, "home_night", datetime(2026, 9, 28, 12, 0),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert H.preset_writes(hass, E2) == [] and H.temp_writes(hass, E2) == []


@pytest.mark.asyncio
async def test_latched_zone_not_tracked_as_precool_zone(mods, monkeypatch):
    """D-L2: an energy pre-cool pass does not re-add a person-latched zone to
    the pre-cool tracking sets."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _install_cm(hass, mods, energy_on=True)
    pred = coord._predictor
    pred._first_eval_done = True
    monkeypatch.setattr(pred, "_should_energy_precool", lambda c, n: True)
    coord._override_arrester._interrupt_latch.add(E2)
    await pred._check_pre_conditioning(None, "home_day", datetime(2026, 6, 11, 11, 0),
                                       pre_arrival_zones=set(), zone_intelligence_enabled=True)
    assert Z2 not in pred._last_precool_zones
    assert Z2 not in pred._energy_precool_zones
    assert Z2 not in pred._pre_conditioning_zones
    assert "zone_1" in pred._last_precool_zones      # unlatched zones still tracked


@pytest.mark.asyncio
async def test_latched_zone_not_tracked_in_pre_arrival_branch(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    coord._override_arrester._interrupt_latch.add(E2)
    coord._pre_arrival_zones.add(Z2)
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 3, 51), pre_arrival_zones={Z2},
        zone_intelligence_enabled=True)
    assert Z2 not in coord._predictor._pre_conditioning_zones


@pytest.mark.asyncio
async def test_hvac_disabled_ends_pre_arrival_borrow_inactive(mods, monkeypatch):
    """D-L4: HVAC coordinator switched off mid pre-arrival -> the borrow ends
    as `pre_arrival_inactive` on the next tick, never `lease_expiry`."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._enabled = False
    await coord._async_decision_cycle()
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_inactive"


@pytest.mark.asyncio
async def test_zone_removed_mid_borrow_returns_token(mods, monkeypatch):
    """D-L4: the zone vanished while its pre-arrival borrow was live — the
    release closes the row instead of skipping it forever."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    del coord.zone_manager._zones[Z2]
    coord._pre_arrival_zones.discard(Z2)
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.detail == "s11_zone_removed"
    assert Z2 not in coord._predictor._banking_excursion_tokens


@pytest.mark.asyncio
async def test_release_without_baseline_returns_token(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    monkeypatch.setattr(coord._predictor, "_resolve_baseline_range", lambda z: None)
    coord._pre_arrival_zones.discard(Z2)
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.detail == "s11_no_baseline"


def _arrive_setup(coord):
    coord._pre_arrival_enabled = True
    coord._pre_arrival_sources = ["ble"]
    coord._person_zone_map = {"person.jaya": [Z2]}
    coord._async_decision_cycle = AsyncMock()


@pytest.mark.asyncio
async def test_max_age_then_repeat_trigger_does_not_rebegin(mods, monkeypatch):
    """D-L5: after a max-age end, a repeat trigger inside the window neither
    re-adds the zone nor begins a second pre-cool."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _arrive_setup(coord)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    _age(mods, tok, 31 * 60, monkeypatch)
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok._return_outcome.trigger == "pre_arrival_max_age"
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 not in coord._pre_arrival_zones
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 40),
        pre_arrival_zones=set(coord._pre_arrival_zones), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert len(_s12(hass, mods)) == 1


@pytest.mark.asyncio
async def test_spent_episode_ends_after_a_window_of_silence(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _arrive_setup(coord)
    coord._pre_arrival_spent[Z2] = datetime.now(timezone.utc) - timedelta(minutes=31)
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 in coord._pre_arrival_zones and Z2 not in coord._pre_arrival_spent


@pytest.mark.asyncio
async def test_spent_episode_ends_on_arrival(mods, monkeypatch):
    coord, hass, db, _ = _setup(mods, monkeypatch)
    coord._pre_arrival_spent[Z2] = datetime.now(timezone.utc)
    _occ(mods, coord, Z2, lighting=True, hvac=True)
    coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert Z2 not in coord._pre_arrival_spent


@pytest.mark.asyncio
async def test_zi_off_on_within_window_does_not_rebegin(mods, monkeypatch):
    """D-L5 (rewritten fix-up 2 — the old version was hollow: it never fired
    a new trigger). ZI off ends the borrow as inactive and SPENDS the arrival
    episode; ZI back on inside the window, then a REAL repeat arrival
    trigger: the zone is not re-added and no second pre-cool is written."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _arrive_setup(coord)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    coord._zone_intelligence_enabled = False
    await coord._async_end_pre_arrival_borrows({})
    await H.drain(hass)
    assert tok._return_outcome.trigger == "pre_arrival_inactive"
    coord._zone_intelligence_enabled = True
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 not in coord._pre_arrival_zones
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 10),
        pre_arrival_zones=set(coord._pre_arrival_zones), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert len(_s12(hass, mods)) == 1


@pytest.mark.asyncio
async def test_master_off_ends_pre_arrival_with_inactive_trigger(mods, monkeypatch):
    """D-L7: pre-conditioning master OFF ends a pre-arrival borrow with an
    INV-B.2 trigger (CPR D3c: no throttle map exists any more)."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    _install_cm(hass, mods, pre_cond=False)
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 10),
        pre_arrival_zones={Z2}, zone_intelligence_enabled=True)
    await H.drain(hass)
    assert tok.returned and tok._return_outcome.trigger == "pre_arrival_inactive"


@pytest.mark.asyncio
async def test_spent_episode_pruned_after_a_window_without_trigger(mods, monkeypatch):
    """D-L5 discharge on the pass side: a spent episode with no trigger for a
    whole window ends at the next expiry pass."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    coord._pre_arrival_spent[Z2] = datetime.now(timezone.utc) - timedelta(minutes=31)
    coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert Z2 not in coord._pre_arrival_spent
    coord._pre_arrival_spent[Z2] = datetime.now(timezone.utc) - timedelta(minutes=29)
    coord._expire_pre_arrival_zones(datetime.now(timezone.utc))
    assert Z2 in coord._pre_arrival_spent


# ==========================================================================
# Fix-up round 2
# ==========================================================================


def _freeze_hvac_clock(mods, monkeypatch, t):
    from homeassistant.util import dt as real_dt
    monkeypatch.setattr(real_dt, "utcnow", lambda: t)


@pytest.mark.asyncio
async def test_spent_episode_refreshed_by_repeat_trigger(mods, monkeypatch):
    """Re-review C-2: max-age end at T0; a repeat trigger at T0+25 min
    REFRESHES the spent episode; at T0+35 min it is still spent (only 10 min
    since the last trigger) and a further trigger does not re-add the zone.
    Without the refresh the episode would have lapsed at T0+30."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _arrive_setup(coord)
    t0 = datetime(2026, 9, 28, 22, 0, tzinfo=timezone.utc)
    coord._pre_arrival_spent[Z2] = t0                       # max-age end at T0
    _freeze_hvac_clock(mods, monkeypatch, t0 + timedelta(minutes=25))
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 not in coord._pre_arrival_zones
    t35 = t0 + timedelta(minutes=35)
    _freeze_hvac_clock(mods, monkeypatch, t35)
    coord._expire_pre_arrival_zones(t35)
    assert Z2 in coord._pre_arrival_spent
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 not in coord._pre_arrival_zones


def test_pre_arrival_window_number_registered_for_cm(mods):
    """Re-review C-3: the Coordinator Manager's `number.async_setup_entry`
    actually yields the knob-35 entity."""
    import asyncio as _aio
    from custom_components.universal_room_automation import number as number_mod
    from runtime_harness import StubConfigEntry
    coord, hass = H.make_coord(mods)
    hass.data[mods["const"].DOMAIN]["coordinator_manager"] = MagicMock(coordinators={"hvac": coord})
    entry = StubConfigEntry(entry_id="cm", entry_type=mods["const"].ENTRY_TYPE_COORDINATOR_MANAGER)
    added: list = []
    _aio.new_event_loop().run_until_complete(
        number_mod.async_setup_entry(hass, entry, lambda ents, *a, **k: added.extend(ents)))
    assert any(type(e).__name__ == "PreArrivalWindowMinutesNumber" for e in added)


@pytest.mark.asyncio
async def test_master_off_on_within_window_does_not_rebegin(mods, monkeypatch):
    """N3: master OFF ends the pre-arrival borrow and spends the episode;
    master back ON inside the window + a REAL repeat trigger -> no second
    pre-cool."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _arrive_setup(coord)
    await _pre_arrival(coord, hass)
    tok = _tok(coord)
    _install_cm(hass, mods, pre_cond=False)
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 10),
        pre_arrival_zones=set(coord._pre_arrival_zones), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert tok._return_outcome.trigger == "pre_arrival_inactive"
    assert Z2 not in coord._pre_arrival_zones
    _install_cm(hass, mods, pre_cond=True, energy_on=False)
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    await coord._predictor._check_pre_conditioning(
        None, "home_night", datetime(2026, 9, 28, 22, 12),
        pre_arrival_zones=set(coord._pre_arrival_zones), zone_intelligence_enabled=True)
    await H.drain(hass)
    assert len(_s12(hass, mods)) == 1


# ==========================================================================
# Fix-up round 3
# ==========================================================================


@pytest.mark.asyncio
async def test_spent_episode_keyed_by_last_trigger_not_spend_time(mods, monkeypatch):
    """C-L1: the spent episode is keyed by the LAST TRIGGER (`start`), not
    the spend time. Trigger at T0 (window 30 min), the episode is spent at
    T0+20 (an interrupt well after the trigger), a new trigger at T0+40 —
    after start+window (T0+30) but before spend+window (T0+50) — begins a
    new pre-arrival."""
    coord, hass, db, _ = _setup(mods, monkeypatch)
    _arrive_setup(coord)
    t0 = datetime(2026, 9, 28, 22, 0, tzinfo=timezone.utc)
    _freeze_hvac_clock(mods, monkeypatch, t0)
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 in coord._pre_arrival_zones
    _freeze_hvac_clock(mods, monkeypatch, t0 + timedelta(minutes=20))
    coord._spend_pre_arrival_episode(Z2)
    assert Z2 not in coord._pre_arrival_zones
    _freeze_hvac_clock(mods, monkeypatch, t0 + timedelta(minutes=40))
    coord._handle_person_arriving({"person_entity": "person.jaya", "source": "ble"})
    assert Z2 in coord._pre_arrival_zones
