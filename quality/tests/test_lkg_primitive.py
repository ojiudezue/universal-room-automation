"""LKG wave 1 D1 — generic ``LkgValue`` primitive tests.

Covers:
  * Bounds parity vs the shipped ``SOCEnvelope.compute`` over a dense age
    grid (byte-identical). This is the behavior-freeze contract for D1.
  * Tier crossover boundaries (fresh / lkg_bounded / lkg_stale / expired).
  * to_blob / from_blob round-trip (None-safe, tz-aware promotion).
  * ``SOCEnvelope.__module__`` invariance (matches the C-HIGH-1 shim in
    ``test_blind_window_evse_guard.py``).
  * Mutation anchor witness — patching ``LkgValue.envelope`` to lie about
    the lower bound breaks the shipped envelope path (proving the primitive
    is load-bearing, not a dead parallel path).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# Bootstrap HA mocks the same way the guard suite does.
import test_energy_load_shedding_correctness  # noqa: F401

from custom_components.universal_room_automation.lkg import LkgValue
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    BATTERY_CAPACITY_KWH,
    BATTERY_MAX_CHARGE_KW,
    BATTERY_MAX_DISCHARGE_KW,
    DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S,
    soc_bounds,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    SOCEnvelope,
)


_UTC = timezone.utc
_MAX_AGE = float(DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S)


def _mk_lv(value: float, age_s: float) -> LkgValue:
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=_UTC)
    at = now - timedelta(seconds=age_s)
    bf = soc_bounds(
        BATTERY_CAPACITY_KWH,
        BATTERY_MAX_CHARGE_KW,
        BATTERY_MAX_DISCHARGE_KW,
        _MAX_AGE,
    )
    return LkgValue(value=value, at=at, source="test", bounds_fn=bf), now


# ---------------------------------------------------------------------------
# Bounds parity — SOCEnvelope.compute vs LkgValue.envelope over a dense grid.
# ---------------------------------------------------------------------------
def test_bounds_parity_across_age_grid():
    env = SOCEnvelope(
        capacity_kwh=BATTERY_CAPACITY_KWH,
        max_charge_kw=BATTERY_MAX_CHARGE_KW,
        max_discharge_kw=BATTERY_MAX_DISCHARGE_KW,
    )
    for lkg in (0.0, 5.0, 47.5, 80.0, 100.0):
        # 200 evenly-spaced points from 0 to just under max_age.
        for i in range(0, 200):
            age = i * (_MAX_AGE / 200.0)
            shim = env.compute(lkg, age, _MAX_AGE)
            lv, now = _mk_lv(lkg, age)
            lo, hi, tier = lv.envelope(now)
            assert shim is not None, f"shim None at age={age}"
            assert tier != "expired"
            # Byte-identical arithmetic — same order of operations.
            assert shim[0] == lo
            assert shim[1] == hi


def test_expired_boundary_matches_shipped():
    env = SOCEnvelope(
        capacity_kwh=BATTERY_CAPACITY_KWH,
        max_charge_kw=BATTERY_MAX_CHARGE_KW,
        max_discharge_kw=BATTERY_MAX_DISCHARGE_KW,
    )
    # At max_age exactly, shipped returned a bounded pair (only strict > was None).
    assert env.compute(50.0, _MAX_AGE, _MAX_AGE) is not None
    # Beyond max_age, shipped returned None.
    assert env.compute(50.0, _MAX_AGE + 1.0, _MAX_AGE) is None


def test_tier_crossovers():
    # fresh <60s, lkg_bounded <600s, lkg_stale <max, expired >=max
    for age, expected in ((0, "fresh"), (59.9, "fresh"),
                          (60, "lkg_bounded"), (599.9, "lkg_bounded"),
                          (600, "lkg_stale"), (_MAX_AGE - 1, "lkg_stale")):
        lv, now = _mk_lv(50.0, age)
        _, _, tier = lv.envelope(now)
        assert tier == expected, f"age={age} tier={tier} expected={expected}"
    lv, now = _mk_lv(50.0, _MAX_AGE + 10)
    _, _, tier = lv.envelope(now)
    assert tier == "expired"


# ---------------------------------------------------------------------------
# Persistence round-trip.
# ---------------------------------------------------------------------------
def test_to_blob_from_blob_round_trip():
    stamp = datetime(2026, 7, 23, 8, 30, 0, tzinfo=_UTC)
    lv = LkgValue(value=42.0, at=stamp, source="envoy")
    blob = lv.to_blob()
    assert blob == {"value": 42.0, "at_iso": stamp.isoformat(), "source": "envoy"}
    restored = LkgValue.from_blob(blob)
    assert restored is not None
    assert restored.value == 42.0
    assert restored.at == stamp
    assert restored.source == "envoy"


def test_from_blob_none_safe():
    assert LkgValue.from_blob(None) is None
    assert LkgValue.from_blob({}) is None
    assert LkgValue.from_blob({"value": None, "at_iso": "2026-07-23T00:00:00+00:00"}) is None
    assert LkgValue.from_blob({"value": "not-a-number", "at_iso": "x"}) is None
    assert LkgValue.from_blob({"value": 1.0}) is None  # missing at_iso
    assert LkgValue.from_blob({"value": 1.0, "at_iso": "not-a-date"}) is None


def test_from_blob_promotes_tz_naive_to_utc():
    # tz-naive ISO must be promoted to UTC (matches shipped restore behavior).
    lv = LkgValue.from_blob({"value": 10.0, "at_iso": "2026-07-23T00:00:00"})
    assert lv is not None
    assert lv.at.tzinfo is not None


# ---------------------------------------------------------------------------
# SOCEnvelope.__module__ invariance — the C-HIGH-1 shim in the guard suite.
# ---------------------------------------------------------------------------
def test_soc_envelope_module_is_energy_battery():
    assert SOCEnvelope.__module__ == (
        "custom_components.universal_room_automation."
        "domain_coordinators.energy_battery"
    )


# ---------------------------------------------------------------------------
# Mutation anchor witness — patch LkgValue.envelope to a lying lower bound;
# the shim's compute() must observe the lie. Proves the primitive is
# load-bearing on the shipped SOC envelope path.
# ---------------------------------------------------------------------------
def test_mutation_envelope_lower_bound_is_load_bearing(monkeypatch):
    real_envelope = LkgValue.envelope

    def _lying_envelope(self, now):
        lo, hi, tier = real_envelope(self, now)
        return (lo + 25.0, hi, tier)  # lift lower bound by 25 pp

    monkeypatch.setattr(LkgValue, "envelope", _lying_envelope)
    env = SOCEnvelope(
        capacity_kwh=BATTERY_CAPACITY_KWH,
        max_charge_kw=BATTERY_MAX_CHARGE_KW,
        max_discharge_kw=BATTERY_MAX_DISCHARGE_KW,
    )
    # Bounded age, small widening → mutated lo should be ~25pp above the
    # honest lower bound. If the shim were NOT delegating, the mutation
    # would be invisible.
    lo, hi = env.compute(50.0, 300.0, _MAX_AGE)
    # Honest lower bound at age=300s: 50 - (30.72*300)/(36*40) = 50 - 6.4 = 43.6
    # Mutated should be ~68.6
    assert lo == pytest.approx(68.6, abs=1e-6)
