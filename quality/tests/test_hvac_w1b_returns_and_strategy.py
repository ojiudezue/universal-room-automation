"""HVAC W1-B D2.4 presets-only returns (5 sites), D1/D5 strategy layer,
D2a/D2.5 `last_sent` no-op, N5 S11/S13 fixes, D4/D4a constants + clamp.

C1: every URA borrow return emits ZERO `set_temperature` EXCEPT for a
HUMAN_MANUAL snapshot (`manual` / None / ""), whose reason is prefixed
`human_manual_`. Each of the five sites is driven through its enclosing
production method with a NAMED snapshot and a MANUAL snapshot.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    """Real HA timers (arrester grace / TAO pre-warn / nudge eval) are armed
    by the production paths under test; the leak detector cancels + warns
    instead of failing (phcc opt-in)."""
    return True


ZONE = "zone_1"
ENT = "climate.test_zone_1"


class _RampDB(H.FakeDB):
    """FakeDB + the AC-ramp DAO surface the S8/S9 paths read."""

    def __init__(self, in_flight=None, excursion_rows=None):
        super().__init__()
        self._in_flight = in_flight or {}
        self._ex_rows = excursion_rows or []
        self.ramp_events: list[dict] = []

    async def get_ac_reset_state(self, zone_id):
        return {"in_flight_nudge_original_target": self._in_flight.get(zone_id),
                "soft_nudge_count": 0}

    async def clear_ac_in_flight_nudge(self, zone_id):
        self._in_flight.pop(zone_id, None)

    async def log_ac_ramp_event(self, **kw):
        self.ramp_events.append(kw)

    async def get_zones_with_in_flight_nudge(self):
        return [{"zone_id": z, "original_target": t, "nudged_target": t + 1.5,
                 "started_ts": (H.local_now() - timedelta(minutes=30)).isoformat(),
                 "duration_s": 120} for z, t in self._in_flight.items()]

    async def get_all_excursion_rows(self):
        return list(self._ex_rows)

    async def save_ac_reset_state(self, state):
        return None

    async def update_ac_ramp_restore_settled(self, **kw):
        return None


def _setup(mods, *, snapshot_preset):
    coord, hass = H.make_coord(mods)
    arr = coord._override_arrester
    z = coord.zone_manager.zones[ZONE]
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
    return coord, hass, arr, z


def _s1_rows_temp(hass, mods, site):
    return [r for r in H.climate_write_rows(hass, mods, site) if r["verb"] == "set_temperature"]


# ---- site 1: S6 nudge restore ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("snap,expect_temp", [("sleep", False), ("manual", True), ("", True)])
async def test_S6_nudge_restore_presets_only(mods, snap, expect_temp):
    coord, hass, arr, z = _setup(mods, snapshot_preset=snap)
    ex = mods["hvac_excursion"]
    tok = ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=120)
    tok.pre_preset = snap or None
    arr._nudge_excursion_tokens[ZONE] = tok
    if snap:
        arr._nudge_pre_preset[ZONE] = snap
    await arr._restore_after_nudge(z, original_target=76.0)
    await H.drain(hass)
    temps = H.temp_writes(hass, ENT)
    assert bool(temps) is expect_temp
    if expect_temp:
        assert _s1_rows_temp(hass, mods, "S6_nudge_restore_setpoint")[0]["reason"].startswith("human_manual_")
    else:
        assert H.preset_writes(hass, ENT, "sleep"), "named snapshot restored by the preset pin"
    ex._test_clear_leases()


@pytest.mark.asyncio
async def test_S6_snapshot_source_is_the_token(mods):
    """A-L1: ONE snapshot source — when a token exists, BOTH the HUMAN_MANUAL
    decision and the S7 pin read the token's `pre_preset`, not the RAM map."""
    coord, hass, arr, z = _setup(mods, snapshot_preset="sleep")
    ex = mods["hvac_excursion"]
    tok = ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=120)
    tok.pre_preset = "sleep"
    arr._nudge_excursion_tokens[ZONE] = tok
    arr._nudge_pre_preset[ZONE] = "home"  # stale RAM copy disagrees
    await arr._restore_after_nudge(z, original_target=76.0)
    await H.drain(hass)
    assert H.temp_writes(hass, ENT) == []
    assert H.preset_writes(hass, ENT, "sleep") and not H.preset_writes(hass, ENT, "home")
    ex._test_clear_leases()


# ---- site 2: S8 cancel nudge ---------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("snap,expect_temp", [("home", False), ("manual", True)])
async def test_S8_cancel_nudge_presets_only(mods, snap, expect_temp):
    coord, hass, arr, z = _setup(mods, snapshot_preset=snap)
    arr._db = _RampDB(in_flight={ZONE: 76.0})
    ex = mods["hvac_excursion"]
    tok = ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=120)
    tok.pre_preset = snap
    arr._nudge_excursion_tokens[ZONE] = tok
    await arr.cancel_nudge(ZONE)
    await H.drain(hass)
    assert bool(H.temp_writes(hass, ENT)) is expect_temp
    if expect_temp:
        assert _s1_rows_temp(hass, mods, "S8_cancel_nudge_restore")[0]["reason"] == "human_manual_cancel_nudge_restore"
    assert H.preset_writes(hass, ENT, snap)
    ex._test_clear_leases()


# ---- site 3: S9 startup ramp audit -----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("snap,expect_temp", [("home", False), ("manual", True)])
async def test_S9_startup_ramp_audit_presets_only(mods, snap, expect_temp):
    coord, hass, arr, z = _setup(mods, snapshot_preset=snap)
    arr._db = _RampDB(
        in_flight={ZONE: 76.0},
        excursion_rows=[{"zone_id": ZONE, "kind": "nudge", "pre_preset": snap}],
    )
    # zone currently at the nudged value so the "operator re-set" guard passes
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual", high=77.5)
    await arr.async_startup_ramp_audit()
    await H.drain(hass)
    assert bool(H.temp_writes(hass, ENT)) is expect_temp
    if expect_temp:
        assert _s1_rows_temp(hass, mods, "S9_startup_ramp_audit_restore")[0]["reason"] == "human_manual_startup_ramp_audit_restore"
    assert H.preset_writes(hass, ENT, snap)


# ---- site 4: S11 banking release ---------------------------------------------------


async def _bank(mods, *, snap):
    coord, hass, arr, z = _setup(mods, snapshot_preset=snap)
    pr = coord._predictor
    ex = mods["hvac_excursion"]
    H.set_climate(hass, ENT, preset_mode=snap, hold_activity=snap)
    tok = await ex.begin_excursion(
        hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND.BANKING,
        duration_s=None, site="S12_pre_cool",
    )
    assert tok is not None and tok.pre_preset == snap
    pr._banking_excursion_tokens = {ZONE: tok}
    # CPR D3c: the release baseline is the house-state preset's configured
    # range (the emitted-range map seed it used is retired).
    coord._house_state = "home_day"
    return coord, hass, arr, z, pr, ex, tok


@pytest.mark.asyncio
@pytest.mark.parametrize("snap,expect_temp", [("home", False), ("manual", True)])
async def test_S11_banking_release_presets_only(mods, snap, expect_temp):
    coord, hass, arr, z, pr, ex, tok = await _bank(mods, snap=snap)
    await pr._release_banked_zones({ZONE})
    await H.drain(hass)
    assert bool(H.temp_writes(hass, ENT)) is expect_temp
    if expect_temp:
        assert _s1_rows_temp(hass, mods, "S11_release_banked")[0]["reason"] == "human_manual_banking_release"
    else:
        assert H.preset_writes(hass, ENT, "home")
    assert ZONE not in ex._rows, "return_excursion cleared the row"
    ex._test_clear_leases()


# CPR Batch C D3c: `test_S11_release_seeds_last_emitted_when_entry_missing`
# is retired with the map it pinned (it was already red on develop: the
# fallback low is the configured heat since v5.103.22, not `cool - 7`).
# Replacement: test_hvac_cpr_batch_c.py::
# test_s11_baseline_uses_preset_resolved_after_map_retirement.


@pytest.mark.asyncio
async def test_S11_comfort_gate_covers_the_preset_write(mods):
    """N5: `_s11_gate` (True=DEFER) gates the preset half too."""
    coord, hass, arr, z, pr, ex, tok = await _bank(mods, snap="home")
    arr.comfort_delay_active = lambda zid: True
    await pr._release_banked_zones({ZONE})
    await H.drain(hass)
    assert H.preset_writes(hass, ENT) == [] and H.temp_writes(hass, ENT) == []
    ex._test_clear_leases()


@pytest.mark.asyncio
async def test_S11_self_exclusion_via_excursion_id_for(mods):
    """N5: our OWN banking row is not a foreign borrow (release proceeds);
    a DIFFERENT live row on the zone makes the release stand down."""
    coord, hass, arr, z, pr, ex, tok = await _bank(mods, snap="home")
    # (a) own row -> proceeds
    assert ex.excursion_id_for(ZONE) == tok.excursion_id
    await pr._release_banked_zones({ZONE})
    await H.drain(hass)
    assert H.preset_writes(hass, ENT, "home")
    # (b) foreign row -> stands down
    coord, hass, arr, z, pr, ex, tok = await _bank(mods, snap="home")
    ex._rows[ZONE] = ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.PREHEAT, duration_s=600)
    pr._banking_excursion_tokens = {ZONE: tok}
    outcomes = []
    real_return = ex.return_excursion

    async def _spy_return(t, **kw):
        outcomes.append(kw)
        return await real_return(t, **kw)
    ex.return_excursion = _spy_return
    try:
        await pr._release_banked_zones({ZONE})
    finally:
        ex.return_excursion = real_return
    await H.drain(hass)
    assert H.preset_writes(hass, ENT) == [] and H.temp_writes(hass, ENT) == []
    assert outcomes and outcomes[0]["restore_ok"] is False
    assert outcomes[0]["trigger_detail"].startswith("s11_release_skipped_foreign_borrow:")
    ex._test_clear_leases()


# ---- site 5: S13 preheat return -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("snap,expect_temp", [("home", False), ("manual", True)])
async def test_S13_preheat_return_presets_only(mods, snap, expect_temp):
    coord, hass, arr, z = _setup(mods, snapshot_preset=snap)
    pr = coord._predictor
    ex = mods["hvac_excursion"]
    H.set_climate(hass, ENT, preset_mode=snap, hold_activity=snap, high=76.0, low=68.0)
    tok = await ex.begin_excursion(
        hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND.PREHEAT,
        excursion_low=70.0, excursion_high=76.0, duration_s=600, site="S13_pre_heat",
    )
    pr._preheat_excursion_tokens = {ZONE: tok}
    pr._preheat_return_timers = {ZONE: lambda: None}
    pr._pre_conditioning_zones.add(ZONE)
    await pr._return_preheat(ZONE)
    await H.drain(hass)
    assert bool(H.temp_writes(hass, ENT)) is expect_temp
    if expect_temp:
        assert _s1_rows_temp(hass, mods, "S13_preheat_return")[0]["reason"] == "human_manual_preheat_boundary"
    else:
        assert H.preset_writes(hass, ENT, "home")
    assert ZONE not in pr._pre_conditioning_zones and ZONE not in ex._rows
    ex._test_clear_leases()


# ---- D51: kill switch retired — every kind always records ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["nudge", "compromise", "banking", "preheat", "egress_pause"])
async def test_begin_excursion_always_records_for_every_kind(mods, kind):
    """D51 (operator): the excursion kill switch is retired — there is no
    switch to consult, `begin_excursion` records a row for EVERY kind, and
    gate (e) sees it (the M3 no-row cases are gone)."""
    coord, hass = H.make_coord(mods)
    ex = mods["hvac_excursion"]
    assert not hasattr(ex, "set_kill_switch_enabled") and not hasattr(ex, "is_kill_switch_enabled")
    assert not hasattr(coord, "excursion_primitive_enabled")
    tok = await ex.begin_excursion(
        hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND(kind),
        duration_s=600 if kind != "egress_pause" else None, site="t",
    )
    assert tok is not None and ex.is_borrow_active(ZONE) is True
    assert coord.preset_manager.manual_guard_verdict(ZONE)["gate_snapshot"]["e_source"] == "row"
    ex._test_clear_leases()


# ---- D1 / D5 strategy layer -----------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_no_op_returns_skipped(mods):
    S = mods["hvac_strategy"]
    coord, hass = H.make_coord(mods)
    H.set_climate(hass, ENT, preset_mode="home", hold_activity="home")
    st = S.GenericStrategy()
    r1 = await st.hold_preset(hass, ENT, "home", zone_id=ZONE, reason="t", site="T")
    assert r1.status is S.WriteStatus.APPLIED
    assert len(H.preset_writes(hass, ENT)) == 1
    r2 = await st.hold_preset(hass, ENT, "home", zone_id=ZONE, reason="t", site="T")
    assert r2.status is S.WriteStatus.SKIPPED_ALREADY_CORRECT
    assert len(H.preset_writes(hass, ENT)) == 1, "no-op = ZERO service calls"
    # observed divergence clears the record -> writes again
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
    r3 = await st.hold_preset(hass, ENT, "home", zone_id=ZONE, reason="t", site="T")
    assert r3.status is S.WriteStatus.APPLIED


@pytest.mark.asyncio
async def test_strategy_no_op_requires_both_halves(mods):
    """last_sent matches but the observation does NOT -> write (no no-op)."""
    S = mods["hvac_strategy"]
    coord, hass = H.make_coord(mods)
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
    st = S.GenericStrategy()
    st._record_sent(ENT, "set_preset_mode", "home")
    r = await st.hold_preset(hass, ENT, "home", zone_id=ZONE, reason="t", site="T")
    assert r.status is S.WriteStatus.APPLIED


@pytest.mark.asyncio
async def test_returns_still_emit_resume_then_pin_via_needs_resume_first(mods):
    S = mods["hvac_strategy"]
    coord, hass = H.make_coord(mods)
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
    r = await S.CarrierStrategy().hold_preset(hass, ENT, "home", zone_id=ZONE, reason="t", site="T")
    assert r.status is S.WriteStatus.APPLIED
    presets = [c[2]["preset_mode"] for c in H.preset_writes(hass, ENT)]
    assert presets == ["resume", "home"], "resume-then-pin is still the funnel's job"


def test_last_sent_lives_in_strategy_not_funnel(mods):
    """D2.5 (M5): the funnel carries NO `last_sent` / no-op machinery."""
    src = Path(mods["hvac_setpoint"].__file__).read_text()
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    assert "last_sent" not in names | attrs
    assert "SKIPPED_ALREADY_CORRECT" not in src
    assert hasattr(mods["hvac_strategy"].GenericStrategy, "last_sent")


def test_strategy_dispatch_by_registry_platform_and_cache(mods, monkeypatch):
    S = mods["hvac_strategy"]
    S._test_reset_cache()
    plat = {"climate.a": "ha_carrier", "climate.b": "ha_carrier", "climate.c": "nest", "climate.d": None}
    monkeypatch.setattr(S, "_entity_platform", lambda hass, eid: plat[eid])
    a = S.strategy_for(None, "climate.a")
    b = S.strategy_for(None, "climate.b")
    assert isinstance(a, S.CarrierStrategy) and a is b, "one instance per BRAND"
    c = S.strategy_for(None, "climate.c")
    assert type(c) is S.GenericStrategy and c.platform == "nest"
    d1 = S.strategy_for(None, "climate.d")
    d2 = S.strategy_for(None, "climate.d")
    assert type(d1) is S.GenericStrategy and d1 is not d2, "registry miss is NOT cached"
    assert set(S._STRATEGY_BY_PLATFORM) == {"ha_carrier", "nest"}


@pytest.mark.asyncio
async def test_generic_default_no_presets_fallback(mods):
    S = mods["hvac_strategy"]
    coord, hass = H.make_coord(mods)
    H.set_climate(hass, ENT, preset_mode=None, preset_modes=())
    r = await S.GenericStrategy().hold_preset(hass, ENT, "home", zone_id=ZONE, reason="t", site="T")
    assert r.status is S.WriteStatus.FAILED and r.reason == "no_presets_supported"
    assert H.preset_writes(hass, ENT) == []


def test_human_manual_snapshot_classifier(mods):
    S = mods["hvac_strategy"]
    c, g = S.CarrierStrategy(), S.GenericStrategy()
    for v in (None, "", "manual"):
        assert c.is_human_manual_snapshot(v) is True and g.is_human_manual_snapshot(v) is True
    assert c.is_human_manual_snapshot("home") is False
    assert g.is_human_manual_snapshot("home") is False
    assert g.is_human_manual_snapshot("home", preset_modes=()) is True
    assert c.is_human_manual_snapshot("home", preset_modes=()) is False


def test_write_result_truthiness_is_banned(mods):
    S = mods["hvac_strategy"]
    with pytest.raises(TypeError):
        bool(S.WriteResult(S.WriteStatus.APPLIED))


# ---- D4 / D4a ---------------------------------------------------------------------------


def test_read_hvac_compromise_minutes_clamps_stored_20_to_15(mods):
    C = mods["hvac_const"]
    key = C.CONF_HVAC_COMPROMISE_MINUTES
    assert C._read_hvac_compromise_minutes({key: 20}) == 15
    assert C._read_hvac_compromise_minutes({key: 15}) == 15
    assert C._read_hvac_compromise_minutes({key: 10}) == 10
    assert C._read_hvac_compromise_minutes({key: 3}) == 5      # A-L4 floor
    assert C._read_hvac_compromise_minutes({key: 5}) == 5
    assert C._read_hvac_compromise_minutes({}) == 15
    assert C._read_hvac_compromise_minutes({key: "junk"}) == 15
    assert C.clamp_hvac_compromise_minutes(120) == 15 and C.clamp_hvac_compromise_minutes(0) == 5
    assert C.DEFAULT_COMPROMISE_MINUTES == 15 and C.HVAC_COMPROMISE_MINUTES_MAX == 15
    assert C.S1_RECLAIM_RATE_LIMIT_N == 3 and C.S1_RECLAIM_RATE_WINDOW_S == 1800


def test_coordinator_constructor_clamps_compromise_minutes(mods):
    """C-2 wire-in anchor: the setup path constructs HVACCoordinator with
    the options value; the CONSTRUCTOR clamps to [5, 15] for every caller
    and pushes the clamped value into the arrester."""
    from runtime_harness import build_smoke_hass
    for given, expect in ((20, 15), (3, 5), (10, 10)):
        coord = mods["hvac"].HVACCoordinator(build_smoke_hass(zones_count=3), compromise_minutes=given)
        assert coord._override_arrester._compromise_minutes == expect


def test_coordinator_and_arrester_defaults_are_15(mods):
    import inspect
    assert inspect.signature(mods["hvac"].HVACCoordinator.__init__).parameters["compromise_minutes"].default == 15
    assert inspect.signature(mods["hvac_override"].OverrideArrester.__init__).parameters["compromise_minutes"].default == 15


def test_config_flow_hvac_compromise_minutes_max_is_15(mods):
    """UI schema pin (no runtime driver for a vol schema): the NumberSelector
    bound to `vol.Optional(CONF_HVAC_COMPROMISE_MINUTES, ...)` has max=15."""
    src = Path(mods["hvac_setpoint"].__file__).resolve().parents[1] / "config_flow.py"
    tree = ast.parse(src.read_text())
    maxes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Call) and k.args
                    and isinstance(k.args[0], ast.Name)
                    and k.args[0].id == "CONF_HVAC_COMPROMISE_MINUTES"):
                continue
            for c in ast.walk(v):
                if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "NumberSelectorConfig":
                    maxes.append({kw.arg: getattr(kw.value, "value", None) for kw in c.keywords}.get("max"))
    assert maxes and all(m == 15 for m in maxes), maxes
