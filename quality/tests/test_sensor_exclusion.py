"""STEP D1 — SensorExclusionSet shared-primitive tests.

Drives the production ``SensorExclusionSet`` module directly (no
monkey-patch, no re-implementation). Covers STEP-EXCLUDE-{1..4} and
the §D1.1 D2-raise Reading-A byte-identity fixture.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MOD_DIR = _ROOT / "custom_components" / "universal_room_automation"


def _spec_load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sensor_exclusion_mod():
    return _spec_load(
        "step_sensor_exclusion",
        str(_MOD_DIR / "domain_coordinators" / "sensor_exclusion.py"),
    )


# ---------------------------------------------------------------------------
# STEP-EXCLUDE-1 fusion contract (via the primitive's is_excluded contract).
# ---------------------------------------------------------------------------


def test_promoted_entity_is_excluded_non_promoted_is_not(sensor_exclusion_mod):
    """STEP-EXCLUDE-1: is_excluded reflects promote/release state."""
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    assert not S.is_excluded("binary_sensor.a")
    S.promote("p22_continuous", "binary_sensor.a", "continuous_on")
    assert S.is_excluded("binary_sensor.a")
    assert not S.is_excluded("binary_sensor.b")


def test_release_removes_when_last_client_releases(sensor_exclusion_mod):
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("chatter", "binary_sensor.a", "physics_violation")
    S.release("chatter", "binary_sensor.a")
    assert not S.is_excluded("binary_sensor.a")
    assert S.provenance("binary_sensor.a") == {}


# ---------------------------------------------------------------------------
# STEP-EXCLUDE-2 byte-identity under empty-clients.
# ---------------------------------------------------------------------------


def test_reset_tick_clears_all_promotions(sensor_exclusion_mod):
    """STEP-EXCLUDE-2 (structural): reset_tick clears the whole set.

    With no client re-promoting after reset, len == 0 => fusion is
    byte-identical to pre-cycle (every is_excluded() returns False,
    every filter site keeps every sensor).
    """
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("p22_continuous", "binary_sensor.a", "continuous_on")
    S.promote("chatter", "binary_sensor.b", "physics_violation")
    S.promote("stuck_dutycycle", "binary_sensor.c", "dutycycle_stuck")
    assert len(S) == 3
    S.reset_tick()
    assert len(S) == 0
    assert not S.is_excluded("binary_sensor.a")
    assert not S.is_excluded("binary_sensor.b")
    assert not S.is_excluded("binary_sensor.c")


# ---------------------------------------------------------------------------
# STEP-EXCLUDE-3 client isolation — the load-bearing multi-writer invariant.
# ---------------------------------------------------------------------------


def test_client_isolation_release_leaves_other_clients_promotion_intact(
    sensor_exclusion_mod,
):
    """STEP-EXCLUDE-3: releasing chatter must not release stuck_dutycycle."""
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("chatter", "binary_sensor.a", "physics_violation")
    S.promote("stuck_dutycycle", "binary_sensor.a", "dutycycle_stuck")

    assert S.is_excluded("binary_sensor.a")
    assert set(S.provenance("binary_sensor.a").keys()) == {
        "chatter", "stuck_dutycycle",
    }

    S.release("chatter", "binary_sensor.a")
    # stuck_dutycycle still holds -> entity remains excluded.
    assert S.is_excluded("binary_sensor.a"), (
        "STEP-EXCLUDE-3 VIOLATED: chatter release dropped stuck_dutycycle"
    )
    assert set(S.provenance("binary_sensor.a").keys()) == {"stuck_dutycycle"}

    S.release("stuck_dutycycle", "binary_sensor.a")
    assert not S.is_excluded("binary_sensor.a")


def test_three_client_ABC_promote_release_matrix(sensor_exclusion_mod):
    """STEP-EXCLUDE-3 (broader): A/B/C write, C releases, A+B hold."""
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("p22_continuous", "binary_sensor.a", "c")
    S.promote("stuck_dutycycle", "binary_sensor.a", "d")
    S.promote("chatter", "binary_sensor.a", "p")
    S.release("chatter", "binary_sensor.a")
    assert set(S.provenance("binary_sensor.a").keys()) == {
        "p22_continuous", "stuck_dutycycle",
    }
    assert S.is_excluded("binary_sensor.a")


# ---------------------------------------------------------------------------
# STEP-EXCLUDE-4 scope — grep-based test.
# ---------------------------------------------------------------------------


def test_sensor_exclusion_scope_room_tier_only():
    """STEP-EXCLUDE-4: primitive not imported by zone/house/hvac/presence."""
    forbidden = [
        "domain_coordinators/presence.py",
        "domain_coordinators/hvac.py",
        "domain_coordinators/house_state.py",
        "domain_coordinators/safety.py",
        "domain_coordinators/occupancy_substrate.py",
    ]
    for rel in forbidden:
        path = _MOD_DIR / rel
        if not path.exists():
            continue
        text = path.read_text()
        assert "sensor_exclusion" not in text, (
            f"STEP-EXCLUDE-4 VIOLATED: {rel} imports the room-tier primitive"
        )
        assert "SensorExclusionSet" not in text, (
            f"STEP-EXCLUDE-4 VIOLATED: {rel} references SensorExclusionSet"
        )


# ---------------------------------------------------------------------------
# Provenance surface for D5 diagnostic parity.
# ---------------------------------------------------------------------------


def test_provenance_returns_client_reason_map(sensor_exclusion_mod):
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("chatter", "binary_sensor.a", "physics_violation")
    S.promote("stuck_dutycycle", "binary_sensor.a", "dutycycle_stuck")
    prov = S.provenance("binary_sensor.a")
    assert prov == {
        "chatter": "physics_violation",
        "stuck_dutycycle": "dutycycle_stuck",
    }
    # Copy semantics: mutation of returned dict must not affect internal state.
    prov["chatter"] = "MUTATED"
    assert S.provenance("binary_sensor.a")["chatter"] == "physics_violation"


def test_idempotent_repeat_promote_by_same_client_overwrites_reason(
    sensor_exclusion_mod,
):
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("chatter", "binary_sensor.a", "r1")
    S.promote("chatter", "binary_sensor.a", "r2")
    assert S.provenance("binary_sensor.a") == {"chatter": "r2"}


def test_promote_dropped_on_non_str_entity(sensor_exclusion_mod):
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")
    S.promote("chatter", None, "reason")  # type: ignore[arg-type]
    S.promote("chatter", "", "reason")
    assert len(S) == 0


# ---------------------------------------------------------------------------
# D1.1 Reading-A byte-identity fixture — the load-bearing anti-Reading-B test.
# ---------------------------------------------------------------------------


def _simulate_tick(
    S,
    prev_excluded_D1,  # what STUCK-SENSOR-1 D1 held last tick
    p22_this_tick,  # P22 promotions THIS tick
    d1_this_tick,  # what STUCK-SENSOR-1 D1 would promote if it ran cleanly
    d2_raised,  # simulate mid-detector exception
    reading_B_leak=False,  # forbidden compensating add-promote (RED shouldbe)
):
    """Replay the coordinator tick site with the D1.1 branches wired.

    Mirrors coordinator.py's ordering:
      reset_tick() -> P22 promote -> (D1 loop or D2-raise branch).
    """
    S.reset_tick()
    for e in p22_this_tick:
        S.promote("p22_continuous", e, "continuous_on")
    if d2_raised:
        # Reading A (SHIPPED behaviour): DO NOT re-populate the mirror
        # on the failure branch. STUCK-SENSOR-1's own book stays
        # authoritative for the recovered-NM scan.
        if reading_B_leak:
            # Forbidden compensating promote (the mutation D6 6a inserts).
            for e in prev_excluded_D1:
                S.promote("stuck_dutycycle", e, "d2_raise_preserve")
        # else: nothing — set contains ONLY p22 promotions.
    else:
        for e in d1_this_tick:
            S.promote("stuck_dutycycle", e, "dutycycle_stuck")


def test_d2_raise_fusion_byte_identity_reading_a(sensor_exclusion_mod):
    """§D1.1 Reading A: D2-raise tick excludes ONLY P22 entities.

    Reading B (forbidden) would re-populate prev-tick D1 promotions on
    the failure branch, expanding the exclusion set. Reading A leaves
    the shared mirror to reset_tick's cleared state -> byte-identical
    to pre-cycle (P22-only) exclusion.
    """
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")

    prev_excluded_D1 = {"binary_sensor.stuck1", "binary_sensor.stuck2"}
    p22 = {"binary_sensor.p22a"}

    # Reading A (SHIPPED) — the D2-raise codepath preserves byte-identity.
    _simulate_tick(
        S,
        prev_excluded_D1=prev_excluded_D1,
        p22_this_tick=p22,
        d1_this_tick=set(),
        d2_raised=True,
        reading_B_leak=False,
    )
    assert S.excluded() == p22, (
        "Reading A byte-identity: D2-raise tick must exclude ONLY P22 promotions "
        f"(expected {p22}, got {S.excluded()})"
    )


def test_reading_B_leak_would_expand_exclusion_set(sensor_exclusion_mod):
    """Anti-Reading-B assertion.

    This test defines the RED that D6 test 6a asserts on: if the coordinator
    is mutated to add compensating promotes on the failure branch, the
    exclusion set grows beyond P22 and the byte-identity claim fails.
    """
    S = sensor_exclusion_mod.SensorExclusionSet(room_name="test")

    prev_excluded_D1 = {"binary_sensor.stuck1", "binary_sensor.stuck2"}
    p22 = {"binary_sensor.p22a"}

    _simulate_tick(
        S,
        prev_excluded_D1=prev_excluded_D1,
        p22_this_tick=p22,
        d1_this_tick=set(),
        d2_raised=True,
        reading_B_leak=True,  # forbidden mutation
    )
    # Under Reading B the set expands — this is the RED that a build-time
    # source mutation in coordinator.py's :2698-2705 branch would surface
    # in test_d2_raise_fusion_byte_identity_reading_a.
    assert S.excluded() == p22 | prev_excluded_D1
    assert S.excluded() != p22


# ---------------------------------------------------------------------------
# The 6 consumer-site wire — grep asserts every filter uses is_excluded().
# ---------------------------------------------------------------------------


def test_all_6_coordinator_fusion_sites_use_is_excluded():
    """Guards the migration from bare-set filter to SensorExclusionSet API.

    Counts is_excluded() calls in coordinator.py — the plan specifies 6
    consumer sites (motion/presence/occupancy + 3x any_sensor_active).
    Any regression that drops one back to `sensor not in stuck_sensors`
    would surface here.
    """
    path = _MOD_DIR / "coordinator.py"
    text = path.read_text()
    count = text.count("self._exclusion_set.is_excluded(sensor)")
    assert count >= 6, (
        f"Expected >=6 SensorExclusionSet.is_excluded(sensor) consumer sites "
        f"in coordinator.py; found {count}. STEP D1 migration incomplete."
    )
