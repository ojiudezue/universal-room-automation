"""HVAC W1-B §5.P1 — S1 manual-guard replacement (Alt A, four gates).

Drives the REAL `HVACCoordinator._apply_house_state_presets` (the S1
decision site) on the smoke StubHass with a zone that reads `manual`, and
asserts the preset WRITE / DEFERRAL against the ledger rows and the wire.

Invariant under test (plan REV 7 §0):
  C-P1A  no gate armed -> S1 leaves manual within ONE tick;
  C-P1B  any gate armed -> ZERO S1 preset writes on a manual zone;
  C2(ii) vacancy bypass refuses under (a/b) and (e);
  C-P1D  every manual write-through carries manual_class in
         {sub_delta_human, zero_delta_ura}; no NM;
  §5.P3  S1 suppresses kind="preset"; §5.P5 reclaim-rate NM; D2.1 same-tick.

Each gate has its OWN test (conditions of the compound rule count
separately) so a per-site source mutation reds a specific name.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import timedelta

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


def _manual_zone(mods, *, house_state="home_day", zi=False):
    coord, hass = H.make_coord(mods)
    coord._house_state = house_state
    coord._zone_intelligence_enabled = zi
    z = coord.zone_manager.zones[ZONE]
    z.preset_mode = "manual"
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
    # Sibling zones already at the target so only ZONE is under test.
    for other in ("zone_2", "zone_3"):
        coord.zone_manager.zones[other].preset_mode = "home"
    return coord, hass, z


async def _tick(coord, hass):
    await coord._apply_house_state_presets()
    await H.drain(hass)


def _ledger(hass, mods):
    return hass.data[mods["const"].DOMAIN]["activity_logger"]


def _deferred(hass, mods):
    return [r for r in _ledger(hass, mods).actions("preset_change_deferred") if r.get("zone") == ZONE]


def _changes(hass, mods):
    return [r for r in _ledger(hass, mods).actions("preset_change") if r.get("zone") == ZONE]


# --------------------------------------------------------------------------
# C-P1A: no gate -> reclaim in one tick
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s1_reclaims_manual_when_no_gate_armed(mods):
    coord, hass, z = _manual_zone(mods)
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1, "S1 must take the zone out of manual"
    assert _deferred(hass, mods) == []
    rows = _changes(hass, mods)
    assert len(rows) == 1
    d = rows[0]["details"]
    assert d["manual_class"] == "zero_delta_ura"
    snap = d["gate_snapshot"]
    assert (snap["a_b"], snap["c"], snap["d"], snap["e"]) == (False, False, False, False)


@pytest.mark.asyncio
async def test_s1_site_string_is_S1_reason_ladder(mods):
    coord, hass, z = _manual_zone(mods)
    await _tick(coord, hass)
    sites = {r["site"] for r in H.climate_write_rows(hass, mods)}
    assert any(s.startswith("S1_reason_ladder") for s in sites), sites


@pytest.mark.asyncio
async def test_s1_manual_write_through_sets_preset_kind_suppression(mods):
    coord, hass, z = _manual_zone(mods)
    await _tick(coord, hass)
    assert coord._override_arrester._suppress_kind.get(ENT) == "preset"


@pytest.mark.asyncio
async def test_s1_not_manual_benign_no_op_writes_nothing_and_records_nothing(mods):
    coord, hass, z = _manual_zone(mods)
    z.preset_mode = "home"  # already at target
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    assert _deferred(hass, mods) == []
    assert _changes(hass, mods) == []


@pytest.mark.asyncio
async def test_s1_routes_through_strategy_no_op(mods):
    """D1/C5 wire-in anchor: S1 writes THROUGH `Strategy.hold_preset`. With
    the strategy's `last_sent` already `home` and the live entity observed at
    `home`, S1 (whose ZoneState copy still says manual) issues ZERO service
    calls and records no preset_change — a direct funnel call would write."""
    coord, hass, z = _manual_zone(mods)
    S = mods["hvac_strategy"]
    H.set_climate(hass, ENT, preset_mode="home", hold_activity="home")
    S._test_reset_cache()
    st = S.strategy_for(hass, ENT)  # registry miss -> fresh generic, uncached
    # Make the miss deterministic for the S1 call: cache a generic under a
    # fake platform so S1 gets the SAME instance we pre-seed.
    S._STRATEGY_BY_PLATFORM["stub"] = st
    orig = S._entity_platform
    S._entity_platform = lambda hass_, eid: "stub"
    try:
        st._record_sent(ENT, "set_preset_mode", "home")
        await _tick(coord, hass)
    finally:
        S._entity_platform = orig
        S._test_reset_cache()
    assert H.preset_writes(hass, ENT) == [], "strategy no-op must suppress the wire call"
    assert _changes(hass, mods) == []


# --------------------------------------------------------------------------
# gate (a/b) person-protected hold
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["tao", "immune"])
async def test_gate_a_b_via_corrective_writes_suppressed(mods, how):
    coord, hass, z = _manual_zone(mods)
    arr = coord._override_arrester
    if how == "tao":
        arr.set_temp_arrester_override(True)
    else:
        arr._stamp_immune_hold(ZONE, "u1", "Oji", "person.oji")
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    rows = _deferred(hass, mods)
    assert len(rows) == 1
    assert rows[0]["details"]["reason"] == "person_protected_hold"
    assert rows[0]["details"]["gate_snapshot"]["a_b"] is True
    assert rows[0]["details"]["wanted"] == "home"


@pytest.mark.asyncio
async def test_person_protected_hold_sunset_s1_reclaims_next_tick(mods):
    """§5.P4 problem 4 closed-by-A: the sunset drops gate (a/b) and the
    NEXT tick reclaims — no extra machinery."""
    coord, hass, z = _manual_zone(mods)
    arr = coord._override_arrester
    arr._stamp_immune_hold(ZONE, "u1", "Oji", "person.oji")
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    # Age the hold past the 4 h ceiling (hardcoded literal) and sweep.
    arr._immune_holds[ZONE]["started_ts"] = H.local_now() - timedelta(seconds=14401)
    assert arr.sunset_immune_holds("max_age_or_boundary") == 1
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1


# --------------------------------------------------------------------------
# gate (c) arrester window: comfort-delay / grace / compromise (NOT _override_active)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("src", ["comfort_delay", "grace_timer", "compromise_timer"])
async def test_gate_c_comfort_delay_grace_compromise(mods, src):
    coord, hass, z = _manual_zone(mods)
    arr = coord._override_arrester
    if src == "comfort_delay":
        arr._comfort_delay_timers[ZONE] = lambda: None
        arr._comfort_delay_meta[ZONE] = {"zone_id": ZONE}
        z.room_conditions = [mods["hvac_zones"].RoomCondition(
            room_name="r", occupied=True, hvac_occupied=True,
        )]
    elif src == "grace_timer":
        arr._grace_timers[ZONE] = lambda: None
    else:
        arr._compromise_timers[ZONE] = lambda: None
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    rows = _deferred(hass, mods)
    assert len(rows) == 1
    assert rows[0]["details"]["reason"] == "arrester_active_window"
    assert rows[0]["details"]["gate_snapshot"]["c_source"] == src


@pytest.mark.asyncio
async def test_gate_c_does_not_leak_under_compromise_early_return(mods):
    """M1 discriminator: `_override_active` alone (the flag the compromise
    early-return at hvac_override.py:3366-3372 leaves True) must NOT arm
    gate (c). Only a live timer / grant does."""
    coord, hass, z = _manual_zone(mods)
    coord._override_arrester._override_active[ZONE] = True
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1
    assert _deferred(hass, mods) == []


# --------------------------------------------------------------------------
# gate (d) arrester disabled (passive)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_d_arrester_disabled_passive(mods):
    coord, hass, z = _manual_zone(mods)
    coord._override_arrester.enabled = False
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    rows = _deferred(hass, mods)
    assert rows[0]["details"]["reason"] == "arrester_disabled_passive"
    assert rows[0]["details"]["gate_snapshot"]["d"] is True


@pytest.mark.asyncio
async def test_gate_d_reload_window(mods):
    """M10: before SIGNAL_HVAC_COORDINATOR_READY the arrester's `enabled`
    IS the options value it was constructed with (no restore has landed),
    so a coordinator built with arrester_enabled=False refuses on its very
    first tick; one built with True reclaims."""
    from runtime_harness import build_smoke_hass
    for opt, expect_write in ((False, False), (True, True)):
        hass = build_smoke_hass(zones_count=3)
        coord = mods["hvac"].HVACCoordinator(hass, arrester_enabled=opt)
        zs = mods["hvac_zones"].ZoneState(
            zone_id=ZONE, zone_name="Z", climate_entity=ENT, rooms=[],
        )
        zs.preset_mode = "manual"
        zs.target_temp_high = 76.0
        zs.target_temp_low = 68.0
        coord.zone_manager._zones[ZONE] = zs
        H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual")
        H.install_ledger(hass, mods)
        mods["hvac_excursion"]._test_clear_leases()
        coord._house_state = "home_day"
        coord._zone_intelligence_enabled = False
        await _tick(coord, hass)
        assert bool(H.preset_writes(hass, ENT, "home")) is expect_write


# --------------------------------------------------------------------------
# gate (e) live borrow — row for all five kinds + every no-row fallback
# --------------------------------------------------------------------------

_KINDS = ["nudge", "compromise", "banking", "preheat", "egress_pause"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", _KINDS)
async def test_gate_e_row_covers_all_five_kinds(mods, kind):
    coord, hass, z = _manual_zone(mods)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(
        zone_id=ZONE, kind=ex.EXCURSION_KIND(kind), duration_s=600,
    )
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    rows = _deferred(hass, mods)
    assert rows[0]["details"]["reason"] == "active_borrow"
    assert rows[0]["details"]["gate_snapshot"]["e_source"] == "row"
    # Discharge: clear the row -> next tick reclaims.
    ex._test_clear_leases()
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1


@pytest.mark.parametrize("src", [
    "nudge_token", "nudge_restore_timer", "nudge_in_flight",
    "banking_token", "banking_precool_zone", "preheat_token",
    "preheat_return_timer", "egress_token", "egress_paused",
])
def test_gate_e_all_fallbacks_without_a_row(mods, src):
    """Kill switch OFF / begin rejected: NO row, but each kind's in-flight
    state still arms gate (e) (pure verdict, no wire)."""
    coord, hass, z = _manual_zone(mods)
    pm = coord.preset_manager
    arr = coord._override_arrester
    pr = coord._predictor
    eg = coord._egress_manager
    tok = type("T", (), {"excursion_id": "x", "pre_preset": "home"})()
    if src == "nudge_token":
        arr._nudge_excursion_tokens[ZONE] = tok
    elif src == "nudge_restore_timer":
        arr._nudge_restore_timers[ZONE] = lambda: None
    elif src == "nudge_in_flight":
        arr._nudge_in_flight.add(ZONE)
    elif src == "banking_token":
        pr._banking_excursion_tokens = {ZONE: tok}
    elif src == "banking_precool_zone":
        pr._last_precool_zones = {ZONE}
    elif src == "preheat_token":
        pr._preheat_excursion_tokens = {ZONE: tok}
    elif src == "preheat_return_timer":
        pr._preheat_return_timers = {ZONE: lambda: None}
    elif src == "egress_token":
        eg._egress_excursion_tokens = {ZONE: tok}
    elif src == "egress_paused":
        eg._paused_by_egress[ZONE] = {"mode": "heat_cool", "preset": "home"}
    v = pm.manual_guard_verdict(ZONE)
    assert v["refused"] is True
    assert v["gate_snapshot"]["e"] is True
    assert v["gate_snapshot"]["e_source"] == src
    assert pm.should_change_preset("manual", "home", zone_id=ZONE) is False


def test_gate_e_compromise_timer_is_both_c_and_e(mods):
    coord, hass, z = _manual_zone(mods)
    coord._override_arrester._compromise_timers[ZONE] = lambda: None
    v = coord.preset_manager.manual_guard_verdict(ZONE)
    assert v["gate_snapshot"]["c"] is True and v["gate_snapshot"]["e"] is True
    assert v["reason"] == "arrester_active_window"


def test_gate_e_pure_read_no_side_effects(mods):
    """`is_borrow_active` on a STALE row returns False and leaves the row
    in place (no reap, no NM, no DB clear) — unlike `_row_present_and_fresh`."""
    ex = mods["hvac_excursion"]
    ex._test_clear_leases()
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=60)
    ex._rows[ZONE].started_ts = ex._now() - 1000  # stale by far
    fired = []
    ex._fire_stale_row_nm = lambda *a, **k: fired.append(a)  # would be called by a reap
    assert ex.is_borrow_active(ZONE) is False
    assert ex.excursion_id_for(ZONE) is None
    assert ZONE in ex._rows, "pure read must not reap"
    assert fired == []
    ex._test_clear_leases()


def test_preset_manager_arrester_none_fails_closed(mods):
    pm = mods["hvac_preset"].PresetManager(hass=None)
    assert pm.should_change_preset("manual", "home", zone_id=ZONE) is False
    assert pm.last_manual_verdict(ZONE)["reason"] == "arrester_not_wired"
    assert pm.should_change_preset("away", "home", zone_id=ZONE) is True
    assert pm.should_change_preset("home", "home", zone_id=ZONE) is False


def test_should_change_preset_manual_without_zone_id_fails_closed(mods):
    coord, hass, z = _manual_zone(mods)
    assert coord.preset_manager.should_change_preset("manual", "home") is False


# --------------------------------------------------------------------------
# vacancy / runtime bypass (M3, N9b)
# --------------------------------------------------------------------------


async def _bypass_zone(mods):
    coord, hass, z = _manual_zone(mods, house_state="away", zi=True)
    z.runtime_exceeded = True
    return coord, hass, z


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["tao", "borrow", "none", "c_only"])
async def test_vacancy_bypass_defers_under_borrow_and_tao(mods, gate):
    coord, hass, z = await _bypass_zone(mods)
    arr = coord._override_arrester
    if gate == "tao":
        arr.set_temp_arrester_override(True)
    elif gate == "borrow":
        ex = mods["hvac_excursion"]
        ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=600)
    elif gate == "c_only":
        arr._grace_timers[ZONE] = lambda: None
    await _tick(coord, hass)
    writes = H.preset_writes(hass, ENT, "away")
    rows = _deferred(hass, mods)
    if gate in ("tao", "borrow"):
        assert writes == [], f"bypass must refuse under {gate}"
        expect = {
            "tao": "vacancy_bypass_deferred:person_protected_hold",
            "borrow": "vacancy_bypass_deferred:active_borrow",
        }[gate]
        assert rows and rows[0]["details"]["reason"] == expect
    else:
        assert len(writes) >= 1, "bypass proceeds when only (c)/(nothing) is armed"
        assert rows == []


# --------------------------------------------------------------------------
# P2 classifier — manual_class in the S1 preset_change row; no NM
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("delta,coast,expect", [
    (0.5, False, "sub_delta_human"),
    (None, False, "zero_delta_ura"),
    (1.5, True, "sub_delta_human"),   # coast widens to < 2 F
    (1.5, False, "zero_delta_ura"),   # not sub-delta without coast
    (2.5, True, "zero_delta_ura"),
])
async def test_manual_class_from_last_detection(mods, delta, coast, expect):
    coord, hass, z = _manual_zone(mods)
    arr = coord._override_arrester
    if delta is not None:
        arr._last_detection[ENT] = {
            "delta_f": delta, "coast": coast, "gated_reason": None,
            "old_preset": "home", "new_preset": "manual", "zone_id": ZONE, "ts": None,
        }
    await _tick(coord, hass)
    rows = _changes(hass, mods)
    assert rows and rows[0]["details"]["manual_class"] == expect
    # reason ladder untouched
    assert rows[0]["details"]["reason"] == "house_state_transition"


@pytest.mark.asyncio
async def test_no_nm_fires_on_sub_delta_reclaim(mods):
    coord, hass, z = _manual_zone(mods)
    coord._override_arrester._last_detection[ENT] = {"delta_f": 0.5, "coast": False}
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1
    assert hass.data[mods["const"].DOMAIN]["notification_manager"].notes == []


# --------------------------------------------------------------------------
# deferral ledger — behavioural replacements for the lockout source-greps
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deferral_is_edge_triggered_not_per_tick(mods):
    coord, hass, z = _manual_zone(mods)
    coord._override_arrester.set_temp_arrester_override(True)
    await _tick(coord, hass)
    await _tick(coord, hass)
    await _tick(coord, hass)
    assert len(_deferred(hass, mods)) == 1
    assert coord._preset_deferrals_today.value == 1
    assert coord._preset_deferrals_by_gate == {"person_protected_hold": 1}


@pytest.mark.asyncio
async def test_deferral_episode_has_a_discharge(mods):
    coord, hass, z = _manual_zone(mods)
    coord._override_arrester.set_temp_arrester_override(True)
    await _tick(coord, hass)
    # zone leaves manual -> episode ends
    z.preset_mode = "home"
    await _tick(coord, hass)
    assert ZONE not in coord._preset_lockout_since
    # re-enters manual -> a NEW episode row
    z.preset_mode = "manual"
    await _tick(coord, hass)
    assert len(_deferred(hass, mods)) == 2


def test_daily_counter_declares_its_restart_reason(mods):
    coord, hass, z = _manual_zone(mods)
    c = coord._preset_deferrals_today
    assert c.name == "hvac.preset_deferrals_today"
    assert c.persist is False
    assert c.reason


# --------------------------------------------------------------------------
# §5.P5 reclaim-rate trip-wire
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s1_reclaim_rate_nm_fires_at_N_plus_1(mods):
    coord, hass, z = _manual_zone(mods)
    nm = hass.data[mods["const"].DOMAIN]["notification_manager"]
    for _ in range(3):  # N = 3 (hardcoded literal)
        coord._note_s1_reclaim(ZONE, "Zone 1", "house_state_transition")
    await H.drain(hass)
    assert nm.notes == []
    coord._note_s1_reclaim(ZONE, "Zone 1", "house_state_transition")
    await H.drain(hass)
    assert len(nm.notes) == 1
    assert nm.notes[0]["hazard_type"] == "s1_reclaim_rate_high"
    # latched: a 5th inside the window does not re-notify
    coord._note_s1_reclaim(ZONE, "Zone 1", "house_state_transition")
    await H.drain(hass)
    assert len(nm.notes) == 1


@pytest.mark.asyncio
async def test_s1_reclaim_rate_nm_discharges_after_window(mods):
    coord, hass, z = _manual_zone(mods)
    nm = hass.data[mods["const"].DOMAIN]["notification_manager"]
    for _ in range(4):
        coord._note_s1_reclaim(ZONE, "Zone 1", "r")
    await H.drain(hass)
    assert ZONE in coord._s1_reclaim_rate_latched
    # age every stamp past the 30-min window (hardcoded literal 1801 s)
    coord._s1_reclaim_ts[ZONE] = [t - 1801 for t in coord._s1_reclaim_ts[ZONE]]
    coord._note_s1_reclaim(ZONE, "Zone 1", "r")
    assert ZONE not in coord._s1_reclaim_rate_latched
    # and a fresh burst notifies again
    for _ in range(4):
        coord._note_s1_reclaim(ZONE, "Zone 1", "r")
    await H.drain(hass)
    assert len(nm.notes) == 2


@pytest.mark.asyncio
async def test_s1_reclaim_rate_wired_from_manual_write_through(mods):
    """Wire-in anchor: the S1 write path CALLS the trip-wire (not just the
    helper)."""
    coord, hass, z = _manual_zone(mods)
    await _tick(coord, hass)
    assert ZONE in coord._s1_reclaim_ts and len(coord._s1_reclaim_ts[ZONE]) == 1


# --------------------------------------------------------------------------
# D2.1 same-tick nudge-start skip
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_tick_s1_write_marks_zone_and_nudge_skips(mods):
    coord, hass, z = _manual_zone(mods)
    await _tick(coord, hass)
    assert ZONE in coord._zones_written_this_cycle
    arr = coord._override_arrester
    called = []

    async def _fake_nudge(zone, kwh, triggered_by="auto"):
        called.append(zone.zone_id)
    arr._perform_soft_nudge = _fake_nudge
    await arr._handle_overshoot_detected(z, 2.5, H.local_now(), 12.0)
    assert called == [], "nudge must be skipped on a zone S1 wrote this tick"
    # Other zones are not affected.
    z2 = coord.zone_manager.zones["zone_2"]
    await arr._handle_overshoot_detected(z2, 2.5, H.local_now(), 12.0)
    assert called == ["zone_2"]


@pytest.mark.asyncio
async def test_same_tick_set_resets_at_cycle_entry(mods):
    coord, hass, z = _manual_zone(mods)
    coord._zones_written_this_cycle = {ZONE, "zone_2"}
    # Enter the decision cycle; observation mode so no preset/AC work runs.
    coord._observation_mode = True
    coord._startup_audit_done = True
    try:
        await coord._run_decision_cycle()
    except Exception:  # noqa: BLE001 — downstream smoke collaborators may raise; reset is at ENTRY
        pass
    assert coord._zones_written_this_cycle == set()


# --------------------------------------------------------------------------
# Config extremes (Tier-3): knobs interacting mid-borrow
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extreme_arrester_off_mid_borrow_then_row_clears(mods):
    coord, hass, z = _manual_zone(mods)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=900)
    coord._override_arrester.enabled = False  # flipped OFF mid-borrow
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    d = _deferred(hass, mods)[0]["details"]
    assert d["reason"] == "arrester_disabled_passive"
    assert d["gate_snapshot"]["e"] is True and d["gate_snapshot"]["d"] is True
    ex._test_clear_leases()
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == [], "passive arrester still holds after the borrow ends"


@pytest.mark.asyncio
async def test_extreme_tao_on_mid_nudge_then_off(mods):
    coord, hass, z = _manual_zone(mods)
    arr = coord._override_arrester
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=120)
    arr._nudge_restore_timers[ZONE] = lambda: None
    arr.set_temp_arrester_override(True)
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    assert _deferred(hass, mods)[0]["details"]["reason"] == "person_protected_hold"
    arr.set_temp_arrester_override(False)
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == [], "nudge still live -> gate (e) holds"
    ex._test_clear_leases()
    arr._nudge_restore_timers.pop(ZONE)
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1


@pytest.mark.asyncio
async def test_extreme_immune_sunset_mid_borrow(mods):
    coord, hass, z = _manual_zone(mods)
    arr = coord._override_arrester
    ex = mods["hvac_excursion"]
    arr._stamp_immune_hold(ZONE, "u", "Oji", "person.oji")
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.BANKING, duration_s=None)
    await _tick(coord, hass)
    assert _deferred(hass, mods)[0]["details"]["reason"] == "person_protected_hold"
    arr._immune_holds[ZONE]["started_ts"] = H.local_now() - timedelta(seconds=14401)
    arr.sunset_immune_holds("max_age_or_boundary")
    z.preset_mode = "home"; await _tick(coord, hass); z.preset_mode = "manual"  # new episode
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    assert _deferred(hass, mods)[-1]["details"]["reason"] == "active_borrow"


@pytest.mark.asyncio
async def test_extreme_nudge_longer_than_compromise_row_bounds_gate(mods):
    """A NUDGE row (duration 20 min) outlives the 15-min compromise
    ceiling: gate (e) is bounded by the ROW's own stale_ts, not by the
    compromise knob."""
    coord, hass, z = _manual_zone(mods)
    ex = mods["hvac_excursion"]
    ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.NUDGE, duration_s=1200)
    tok = ex._rows[ZONE]
    # 16 min in: past the compromise ceiling, still inside the row window
    tok.started_ts = ex._now() - 16 * 60
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    # 20 min + 30 s slack + 1 s: row stale -> reclaim
    tok.started_ts = ex._now() - (1200 + 30 + 1)
    await _tick(coord, hass)
    assert len(H.preset_writes(hass, ENT, "home")) >= 1
    ex._test_clear_leases()
