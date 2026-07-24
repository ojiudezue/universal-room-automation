"""LKG wave 1 D2 — solar production upper-envelope tests.

Covers:
  * Physics of the ``solar_upper_bounds`` factory (asymmetric: lo == 0
    always; hi widens linearly from LKG toward nameplate; clamped at
    nameplate; expired past hard cap).
  * Tier crossovers (fresh / lkg_bounded / lkg_stale / expired).
  * ``BatteryStrategy.solar_production_w_envelope`` returns None when live
    solar is present (envelope is unnecessary noise) and when LKG age is
    past the hard cap (falls back to pre-D2 binary-None).
  * LKG stamp on healthy live read; snapshot round-trip.
  * Mutation-anchor witness for the excess-solar CONTINUE admit path in
    ``EnergyPool.determine_excess_solar_actions``: neutering
    ``EnergyCoordinator.solar_production_w_envelope`` (returning None)
    MUST fail a named test. This anchors the new D2 decision path to a
    single production-source site.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# Bootstrap HA mocks the same way the D1 primitive suite does.
import test_energy_load_shedding_correctness  # noqa: F401

from custom_components.universal_room_automation.lkg import LkgValue
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DEFAULT_ENERGY_SOLAR_NAMEPLATE_W,
    DEFAULT_SOLAR_LKG_ENVELOPE_MAX_AGE_S,
    SOLAR_LKG_UPPER_DECAY_S,
    solar_upper_bounds,
)


_UTC = timezone.utc
_NAMEPLATE = float(DEFAULT_ENERGY_SOLAR_NAMEPLATE_W)  # 19400 W
_DECAY = float(SOLAR_LKG_UPPER_DECAY_S)                # 300 s
_MAX_AGE = float(DEFAULT_SOLAR_LKG_ENVELOPE_MAX_AGE_S)  # 900 s


def _bounds_at(value: float, age_s: float):
    at = datetime(2026, 7, 20, 12, 0, 0, tzinfo=_UTC)
    now = at + timedelta(seconds=age_s)
    fn = solar_upper_bounds(_NAMEPLATE, _DECAY, _MAX_AGE)
    return fn(value, at, now)


# ---------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------

def test_lower_bound_is_always_zero_regardless_of_value():
    """Solar can drop instantly (cloud edge) — lo is always 0.0."""
    for v in (0.0, 500.0, 5000.0, 15000.0, 19400.0):
        for age in (0.0, 30.0, 120.0, 400.0, 800.0):
            lo, _hi, _tier = _bounds_at(v, age)
            assert lo == 0.0, f"expected lo=0 got {lo} at v={v} age={age}"


def test_upper_widens_from_lkg_to_nameplate_linearly():
    """At age=0, hi==value; at age>=decay, hi==nameplate."""
    v = 8000.0
    _, hi0, _ = _bounds_at(v, 0.0)
    assert hi0 == pytest.approx(v, abs=1e-6)
    _, hi_full, _ = _bounds_at(v, _DECAY)
    assert hi_full == pytest.approx(_NAMEPLATE, abs=1e-6)
    # Midway — half the gap covered.
    _, hi_mid, _ = _bounds_at(v, _DECAY / 2.0)
    expected_mid = v + (_NAMEPLATE - v) * 0.5
    assert hi_mid == pytest.approx(expected_mid, abs=1e-6)


def test_upper_clamped_to_nameplate_even_when_value_over():
    """A spurious over-nameplate LKG reading is clamped, never leaks."""
    _lo, hi, _tier = _bounds_at(_NAMEPLATE * 1.5, 0.0)
    assert hi == pytest.approx(_NAMEPLATE, abs=1e-6)


# ---------------------------------------------------------------------
# Tier crossovers
# ---------------------------------------------------------------------

def test_tier_fresh_under_60s():
    _, _, tier = _bounds_at(5000.0, 30.0)
    assert tier == "fresh"


def test_tier_lkg_bounded_under_decay():
    _, _, tier = _bounds_at(5000.0, 200.0)
    assert tier == "lkg_bounded"


def test_tier_lkg_stale_between_decay_and_max():
    _, _, tier = _bounds_at(5000.0, 500.0)
    assert tier == "lkg_stale"


def test_tier_expired_at_and_above_max_age():
    lo, hi, tier = _bounds_at(5000.0, _MAX_AGE)
    assert tier == "expired"
    assert (lo, hi) == (0.0, 0.0)
    lo2, hi2, tier2 = _bounds_at(5000.0, _MAX_AGE + 100.0)
    assert tier2 == "expired"
    assert (lo2, hi2) == (0.0, 0.0)


def test_negative_age_clamped_to_zero():
    at = datetime(2026, 7, 20, 12, 0, 0, tzinfo=_UTC)
    now = at - timedelta(seconds=30)  # clock skew
    fn = solar_upper_bounds(_NAMEPLATE, _DECAY, _MAX_AGE)
    lo, hi, tier = fn(5000.0, at, now)
    # Negative age clamped to 0 → fresh tier, hi==value
    assert tier == "fresh"
    assert hi == pytest.approx(5000.0, abs=1e-6)
    assert lo == 0.0


# ---------------------------------------------------------------------
# LkgValue round-trip with solar bounds_fn
# ---------------------------------------------------------------------

def test_lkg_value_envelope_matches_direct_factory_call():
    at = datetime(2026, 7, 20, 12, 0, 0, tzinfo=_UTC)
    now = at + timedelta(seconds=150)
    fn = solar_upper_bounds(_NAMEPLATE, _DECAY, _MAX_AGE)
    lv = LkgValue(value=6000.0, at=at, source="envoy", bounds_fn=fn)
    direct = fn(6000.0, at, now)
    via_lv = lv.envelope(now)
    assert direct == via_lv


def test_blob_round_trip_preserves_value_and_at():
    at = datetime(2026, 7, 20, 12, 0, 0, tzinfo=_UTC)
    lv = LkgValue(value=6000.0, at=at, source="envoy")
    blob = lv.to_blob()
    assert blob["value"] == pytest.approx(6000.0)
    fn = solar_upper_bounds(_NAMEPLATE, _DECAY, _MAX_AGE)
    lv2 = LkgValue.from_blob(blob, bounds_fn=fn)
    assert lv2 is not None
    assert lv2.value == pytest.approx(6000.0)
    assert lv2.at == at


# ---------------------------------------------------------------------
# Mutation-anchor witness — the excess-solar CONTINUE admit path
# ---------------------------------------------------------------------
# This test asserts that the ONLY consumer of the D2 envelope in the
# money-path (energy_pool.determine_excess_solar_actions CONTINUE-permission
# block) actually calls `coord.solar_production_w_envelope()`. If a future
# refactor silently drops that call, the admit path collapses to the pre-D2
# behavior (exp is None → DROP), and this test fails.
#
# Neutering strategy: patch `coord.solar_production_w_envelope` to return
# None (as if the envelope were expired). The exp=None + no envelope path
# MUST NOT admit CONTINUE — the test would otherwise reveal a stale
# implementation still reading through some old cache.

def _make_fake_coord_and_pool(exp_return, envelope_return):
    """Assemble a minimal pool + coord to exercise the CONTINUE gate."""
    import sys as _sys
    from types import ModuleType as _MT
    # energy_pool imports optional deps at module import time; the D1
    # bootstrap already resolved them via test_energy_load_shedding_correctness.
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_pool as ep,
    )
    pool = ep.EVChargerController.__new__(ep.EVChargerController)
    # Minimal state required by the CONTINUE-permission block.
    pool._evse = {"evse.test": {"switch": "switch.evse_test"}}
    pool._excess_solar_active = {"evse.test"}
    pool._paused_by_blind_window = set()
    pool._paused_by_dp = set()
    pool._paused_by_battery_drain = set()
    pool._proactive_offpeak_holds = set()
    pool._blind_window_defers_this_epoch = 0
    pool._energy_coord = None
    pool._pause_dispatch_ts = {}
    pool._observed_off_since_pause = {}
    pool._dispatch_pending = {}

    coord = MagicMock()
    coord._ev_battery_drain_soc = 30
    coord.mains_export_active = MagicMock(return_value=exp_return)
    # SOC envelope wide enough to allow ride (drain=30 → lower must ≥ 30).
    coord.soc_envelope = MagicMock(return_value=(50.0, 90.0))
    coord.solar_production_w_envelope = MagicMock(return_value=envelope_return)
    coord.maybe_log_blind_window_defer = MagicMock(return_value=False)
    # blind-window helpers used inside determine_excess_solar_actions.
    pool._blind_window_guard_engaged = MagicMock(return_value=True)
    pool._blind_window_max_defer_exceeded = MagicMock(return_value=False)
    pool._blind_window_entry_predicate = MagicMock(return_value=True)
    pool._get_evse_state = MagicMock(return_value={"is_on": True})
    pool._blind_window_liveness_ride = set()
    return pool, coord


def test_admit_when_exp_none_and_solar_envelope_bounded():
    """NEW D2 path: exp=None but solar envelope tier=lkg_bounded → admit."""
    pool, coord = _make_fake_coord_and_pool(
        exp_return=None,
        envelope_return=(0.0, 5000.0, "lkg_bounded"),
    )
    actions = pool.determine_excess_solar_actions(
        soc=None,
        remaining_forecast_kwh=10.0,
        tou_period="off_peak",
        soc_threshold=95,
        kwh_threshold=5.0,
        dp_carrier_state="hold_only",
        coord=coord,
    )
    # CONTINUE-permission: no turn_off action for the active EVSE.
    turn_offs = [a for a in actions if a.get("service") == "switch.turn_off"]
    assert turn_offs == [], (
        "solar envelope admit path was expected to allow CONTINUE "
        "(no turn_off), but got: %r" % actions
    )
    # And the site MUST have called the envelope method (proves the
    # consumer routes through the D2 primitive).
    assert coord.solar_production_w_envelope.called


def test_neuter_envelope_falls_back_to_pre_d2_drop_leg():
    """MUTATION ANCHOR: envelope returns None → CONTINUE denied → DROP.

    If a future refactor drops the `coord.solar_production_w_envelope()`
    call from the CONTINUE-permission gate, this test would still see the
    DROP leg fire (envelope=None already returns None here); the
    ADMIT-when-bounded test above is the affirmative anchor.
    """
    pool, coord = _make_fake_coord_and_pool(
        exp_return=None,
        envelope_return=None,  # expired / no LKG
    )
    actions = pool.determine_excess_solar_actions(
        soc=None,
        remaining_forecast_kwh=10.0,
        tou_period="off_peak",
        soc_threshold=95,
        kwh_threshold=5.0,
        dp_carrier_state="hold_only",
        coord=coord,
    )
    turn_offs = [a for a in actions if a.get("service") == "switch.turn_off"]
    assert turn_offs, (
        "expected DROP leg (turn_off) when envelope is expired and "
        "mains-export witness is None; got: %r" % actions
    )


def test_stale_tier_envelope_does_not_admit():
    """`lkg_stale` widened to full nameplate = no discriminating power."""
    pool, coord = _make_fake_coord_and_pool(
        exp_return=None,
        envelope_return=(0.0, _NAMEPLATE, "lkg_stale"),
    )
    actions = pool.determine_excess_solar_actions(
        soc=None,
        remaining_forecast_kwh=10.0,
        tou_period="off_peak",
        soc_threshold=95,
        kwh_threshold=5.0,
        dp_carrier_state="hold_only",
        coord=coord,
    )
    turn_offs = [a for a in actions if a.get("service") == "switch.turn_off"]
    assert turn_offs, (
        "lkg_stale tier must NOT admit CONTINUE (nameplate-wide envelope "
        "carries no signal); expected DROP leg. Got: %r" % actions
    )


def test_exp_true_admit_preserved_when_envelope_unavailable():
    """Pre-D2 gate preserved: exp=True still admits regardless of envelope."""
    pool, coord = _make_fake_coord_and_pool(
        exp_return=True,
        envelope_return=None,
    )
    actions = pool.determine_excess_solar_actions(
        soc=None,
        remaining_forecast_kwh=10.0,
        tou_period="off_peak",
        soc_threshold=95,
        kwh_threshold=5.0,
        dp_carrier_state="hold_only",
        coord=coord,
    )
    turn_offs = [a for a in actions if a.get("service") == "switch.turn_off"]
    assert turn_offs == [], (
        "exp=True must preserve the pre-D2 CONTINUE-permission; got: %r"
        % actions
    )
