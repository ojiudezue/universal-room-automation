"""EVSE Drain-Precedence — Session A skeleton tests.

Scope of this file:
    - transition-table correctness (INDEPENDENTLY ANCHORED — the expected
      legal set is HAND-WRITTEN here, then diffed against the machine's
      exported view via `is_legal_transition`, so a machine bug cannot
      pass by matching itself),
    - KV round-trip (to_dict / from_dict / JSON),
    - restore expiry guards (must_start_by passed / max-duration exceeded
      / missing deadline → all reject the transition),
    - injected clock (no wall-clock coupling — v5.17.1 _FrozenClock lesson).

Session B will add tests for the eval math, actuation, reserve-floor
composition, and the reversion sweep.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

# The state-machine module + its `energy_const` dep are pure Python (no
# `homeassistant` imports at module scope) but importing them via the
# normal package path drags in `custom_components/universal_room_automation/
# __init__.py` which DOES import homeassistant. Sidestep by loading both
# files directly via importlib and stitching a synthetic package. Mirrors
# the same "avoid HA bootstrap for pure-logic tests" pattern used by the
# coordinator test files, but without the MagicMock stack (we don't need
# it — nothing under test touches HA).
_HERE = os.path.dirname(os.path.abspath(__file__))
_DC_DIR = os.path.abspath(os.path.join(
    _HERE, "..", "..",
    "custom_components", "universal_room_automation", "domain_coordinators",
))


def _load(mod_name: str, path: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# `energy_const.py` has some HA-typed defaults inside functions but no
# module-level HA imports; safe to load standalone.
_const = _load(
    "_dp_energy_const_shim",
    os.path.join(_DC_DIR, "energy_const.py"),
)
# The state-machine module imports from `.energy_const` — pre-register
# under the relative name it expects. We attach it as a submodule of a
# synthetic parent package.
_pkg = type(sys)("_dp_pkg_shim")
_pkg.__path__ = [_DC_DIR]
sys.modules["_dp_pkg_shim"] = _pkg
sys.modules["_dp_pkg_shim.energy_const"] = _const

# Rewrite the drain-precedence module's relative import to hit our shim.
_dp_src_path = os.path.join(_DC_DIR, "energy_drain_precedence.py")
with open(_dp_src_path, "r") as _f:
    _dp_src = _f.read()
_dp_src = _dp_src.replace("from .energy_const", "from _dp_pkg_shim.energy_const")
_dp_mod = type(sys)("_dp_pkg_shim.energy_drain_precedence")
_dp_mod.__file__ = _dp_src_path
sys.modules["_dp_pkg_shim.energy_drain_precedence"] = _dp_mod
exec(compile(_dp_src, _dp_src_path, "exec"), _dp_mod.__dict__)

dp = _dp_mod
DPState = _dp_mod.DPState
DrainPrecedenceState = _dp_mod.DrainPrecedenceState
compute_must_start_by = _dp_mod.compute_must_start_by
is_legal_transition = _dp_mod.is_legal_transition
restore_from_blob = _dp_mod.restore_from_blob
serialize_for_kv = _dp_mod.serialize_for_kv
try_transition = _dp_mod.try_transition


# --------------------------------------------------------------------------
# Frozen clock — inject; NEVER couple state-machine tests to wall clock.
# --------------------------------------------------------------------------
class _FrozenClock:
    def __init__(self, dt: datetime) -> None:
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt

    def advance(self, **kwargs) -> None:
        self.dt = self.dt + timedelta(**kwargs)


def _tz_now(hour: int = 22) -> datetime:
    """A stable tz-aware anchor for tests."""
    return datetime(2026, 7, 17, hour, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Transition table — independently anchored.
# --------------------------------------------------------------------------

# HAND-WRITTEN expected legal set (from plan §141-158). If the machine's
# `_LEGAL_TRANSITIONS` diverges from this, tests fail.
_EXPECTED_LEGAL: frozenset[tuple[DPState, DPState]] = frozenset({
    (DPState.HOLD_ONLY, DPState.HOLD_ONLY),
    (DPState.HOLD_ONLY, DPState.HOLD_PRE_EVAL),
    (DPState.HOLD_PRE_EVAL, DPState.HOLD_PRE_EVAL),
    (DPState.HOLD_PRE_EVAL, DPState.EVAL_TRANSITION),
    (DPState.HOLD_PRE_EVAL, DPState.HOLD_ONLY),
    (DPState.EVAL_TRANSITION, DPState.TRANSITIONED),
    (DPState.EVAL_TRANSITION, DPState.HOLD_ONLY),
    (DPState.TRANSITIONED, DPState.TRANSITIONED),
    (DPState.TRANSITIONED, DPState.HOLD_ONLY),
    (DPState.TRANSITIONED, DPState.MUST_START_FORCED),
    (DPState.MUST_START_FORCED, DPState.HOLD_ONLY),
})


def test_legal_transition_table_matches_independent_anchor():
    """Every (src → dst) pair the machine claims legal must appear in the
    HAND-WRITTEN expected set, and vice versa. Two independent lists;
    identical iff both correct."""
    all_pairs = {
        (a, b) for a in DPState for b in DPState
    }
    machine_legal = {p for p in all_pairs if is_legal_transition(*p)}
    assert machine_legal == _EXPECTED_LEGAL


@pytest.mark.parametrize("src,dst", sorted(_EXPECTED_LEGAL, key=lambda p: (p[0].value, p[1].value)))
def test_legal_transitions_accepted(src: DPState, dst: DPState):
    clock = _FrozenClock(_tz_now())
    carrier = DrainPrecedenceState(state=src)
    assert try_transition(carrier, dst, now_provider=clock) is True
    assert carrier.state == dst


def test_illegal_transitions_rejected():
    """Any pair NOT in the expected legal set must be refused, with the
    carrier's state unchanged."""
    clock = _FrozenClock(_tz_now())
    illegal = [
        (a, b)
        for a in DPState for b in DPState
        if (a, b) not in _EXPECTED_LEGAL
    ]
    assert illegal, "sanity: there must be some illegal pairs"
    for src, dst in illegal:
        carrier = DrainPrecedenceState(state=src)
        assert try_transition(carrier, dst, now_provider=clock) is False
        assert carrier.state == src, f"illegal {src}→{dst} mutated state"


def test_transition_stamps_since_and_bookkeeping_fields():
    """HOLD_ONLY→HOLD_PRE_EVAL sets hold_started_at; →TRANSITIONED sets
    transitioned_at; →HOLD_ONLY clears both."""
    clock = _FrozenClock(_tz_now(hour=22))
    carrier = DrainPrecedenceState()
    assert try_transition(carrier, DPState.HOLD_PRE_EVAL, now_provider=clock)
    assert carrier.hold_started_at == clock.dt
    assert carrier.since == clock.dt

    clock.advance(minutes=10)
    assert try_transition(carrier, DPState.EVAL_TRANSITION, now_provider=clock)
    assert carrier.since == clock.dt

    clock.advance(seconds=1)
    assert try_transition(carrier, DPState.TRANSITIONED, now_provider=clock)
    assert carrier.transitioned_at == clock.dt

    clock.advance(hours=2)
    assert try_transition(carrier, DPState.HOLD_ONLY, now_provider=clock)
    assert carrier.hold_started_at is None
    assert carrier.transitioned_at is None
    assert carrier.must_start_by_dt is None


# --------------------------------------------------------------------------
# compute_must_start_by
# --------------------------------------------------------------------------

def test_must_start_by_before_todays_target_returns_today():
    now = datetime(2026, 7, 17, 0, 30, tzinfo=timezone.utc)
    got = compute_must_start_by(now, minutes_past_midnight=3 * 60)
    assert got == datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)


def test_must_start_by_after_todays_target_returns_tomorrow():
    now = datetime(2026, 7, 17, 5, 0, tzinfo=timezone.utc)
    got = compute_must_start_by(now, minutes_past_midnight=3 * 60)
    assert got == datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)


def test_must_start_by_exactly_at_target_returns_tomorrow():
    """`now >= today_target` → tomorrow (edge)."""
    now = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    got = compute_must_start_by(now, minutes_past_midnight=3 * 60)
    assert got == datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# KV round-trip
# --------------------------------------------------------------------------

def test_kv_round_trip_transitioned_state():
    """A fully populated TRANSITIONED carrier survives serialize →
    JSON string → parse → from_dict identity."""
    now = _tz_now(hour=22)
    original = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        since=now,
        hold_started_at=now - timedelta(minutes=10),
        transitioned_at=now,
        must_start_by_dt=now + timedelta(hours=5),
        last_eval_at=now,
        last_eval_snapshot={
            "soc": 60,
            "drain_hours": 1.8,
            "charge_hours": 1.9,
            "fits": True,
        },
    )
    raw = serialize_for_kv(original)
    # JSON-decodable
    blob = json.loads(raw)
    assert blob["schema_version"] == 1
    round_tripped = DrainPrecedenceState.from_dict(blob)
    assert round_tripped == original


def test_kv_round_trip_hold_only_default():
    """Default carrier round-trips."""
    original = DrainPrecedenceState()
    raw = serialize_for_kv(original)
    round_tripped = DrainPrecedenceState.from_dict(json.loads(raw))
    assert round_tripped == original


def test_kv_schema_version_mismatch_rejected():
    """`from_dict` with the wrong schema version raises."""
    with pytest.raises(ValueError):
        DrainPrecedenceState.from_dict({"schema_version": 999, "state": "hold_only"})


def test_kv_unknown_state_coerces_to_hold_only():
    """Forward-compat: unknown state string → coerced to HOLD_ONLY, not crash."""
    blob = {
        "schema_version": 1,
        "state": "some_future_state",
        "since": None,
        "hold_started_at": None,
        "transitioned_at": None,
        "must_start_by_dt": None,
        "last_eval_at": None,
        "last_eval_snapshot": {},
    }
    got = DrainPrecedenceState.from_dict(blob)
    assert got.state == DPState.HOLD_ONLY


# --------------------------------------------------------------------------
# Restore expiry guard — the load-bearing INV-DP2 protection at restart.
# --------------------------------------------------------------------------

def test_restore_empty_blob_returns_hold_only():
    clock = _FrozenClock(_tz_now())
    assert restore_from_blob(None, now_provider=clock).state == DPState.HOLD_ONLY
    assert restore_from_blob("", now_provider=clock).state == DPState.HOLD_ONLY


def test_restore_unparseable_returns_hold_only():
    clock = _FrozenClock(_tz_now())
    got = restore_from_blob("{not json", now_provider=clock)
    assert got.state == DPState.HOLD_ONLY


def test_restore_transitioned_within_deadline_accepted():
    """A TRANSITIONED blob whose must_start_by_dt is still in the future
    AND transitioned_at is within DP_TRANSITION_MAX_DURATION_H is restored."""
    now = _tz_now(hour=1)  # 01:00 UTC
    carrier = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        since=now - timedelta(minutes=5),
        transitioned_at=now - timedelta(minutes=5),
        must_start_by_dt=now + timedelta(hours=2),
    )
    raw = serialize_for_kv(carrier)
    clock = _FrozenClock(now)
    restored = restore_from_blob(raw, now_provider=clock)
    assert restored.state == DPState.TRANSITIONED
    assert restored.must_start_by_dt == carrier.must_start_by_dt


def test_restore_transitioned_past_must_start_by_rejected():
    """If must_start_by_dt has already passed at restore-now, the machine
    MUST fall back to HOLD_ONLY (INV-DP2). This is the load-bearing guard
    Session B's tick loop depends on to avoid resurrecting an out-of-window
    paused-EVSE state after a crash-restart."""
    original_now = _tz_now(hour=1)
    carrier = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        since=original_now,
        transitioned_at=original_now,
        must_start_by_dt=original_now + timedelta(hours=2),
    )
    raw = serialize_for_kv(carrier)
    # Restart clock is 4h later — past the 03:00 deadline.
    restart_clock = _FrozenClock(original_now + timedelta(hours=4))
    restored = restore_from_blob(raw, now_provider=restart_clock)
    assert restored.state == DPState.HOLD_ONLY
    assert restored.transitioned_at is None


def test_restore_transitioned_missing_must_start_by_rejected():
    carrier = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        transitioned_at=_tz_now(),
        must_start_by_dt=None,
    )
    raw = serialize_for_kv(carrier)
    restored = restore_from_blob(raw, now_provider=_FrozenClock(_tz_now()))
    assert restored.state == DPState.HOLD_ONLY


def test_restore_transitioned_beyond_max_duration_rejected():
    """INV-DP1 belt-and-suspenders: even if must_start_by is somehow in the
    future, a transition older than DP_TRANSITION_MAX_DURATION_H is
    rejected (paranoia against wall-clock drift on the deadline field)."""
    original_now = _tz_now(hour=22)
    carrier = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        since=original_now,
        # 20h old — way past DP_TRANSITION_MAX_DURATION_H (8h)
        transitioned_at=original_now - timedelta(hours=20),
        # deadline artificially far in the future
        must_start_by_dt=original_now + timedelta(hours=10),
    )
    raw = serialize_for_kv(carrier)
    restored = restore_from_blob(raw, now_provider=_FrozenClock(original_now))
    assert restored.state == DPState.HOLD_ONLY


def test_restore_hold_pre_eval_always_accepted():
    """HOLD_PRE_EVAL is idle; no expiry math applies."""
    carrier = DrainPrecedenceState(
        state=DPState.HOLD_PRE_EVAL,
        hold_started_at=_tz_now() - timedelta(hours=999),
    )
    raw = serialize_for_kv(carrier)
    restored = restore_from_blob(raw, now_provider=_FrozenClock(_tz_now()))
    assert restored.state == DPState.HOLD_PRE_EVAL


# --------------------------------------------------------------------------
# Observability attr surface
# --------------------------------------------------------------------------

def test_to_attrs_contains_required_keys():
    """The attr block Session B mounts on the diagnostics sensor must
    contain the plan's D1 acceptance criteria fields."""
    now = _tz_now()
    carrier = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        since=now,
        transitioned_at=now,
        must_start_by_dt=now + timedelta(hours=5),
        last_eval_at=now,
        last_eval_snapshot={"soc": 60},
    )
    attrs = carrier.to_attrs()
    for k in (
        "state", "since", "hold_started_at", "transitioned_at",
        "must_start_by_dt", "last_eval_at", "last_eval_snapshot",
    ):
        assert k in attrs
    assert attrs["state"] == "transitioned"
    assert attrs["last_eval_snapshot"] == {"soc": 60}
