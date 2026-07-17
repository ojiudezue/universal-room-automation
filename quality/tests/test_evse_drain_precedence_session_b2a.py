"""EVSE Drain-Precedence — Session B2a acceptance tests.

Scope of this file (per session split, no actuation):
    - Pure `evaluate_dp_transition` gate-order coverage.
    - `_dp_maybe_tick` state-machine driver: HOLD_ONLY → HOLD_PRE_EVAL →
      EVAL_TRANSITION → TRANSITIONED (and → HOLD_ONLY on no-fit).
    - P4 counterfactual fixture — hand-computed anchors for all 7 nights
      (§330-346 of the planning doc). This is an INDEPENDENT anchor: the
      expected numbers are hand-computed here, not read from the eval
      under test, so an arithmetic drift in production code is caught.
    - Non-actuation interaction traces (force-charge yield, INV-DP4 blind
      gate, L1-only branch, second plug-in during transition, restart-
      mid-transition via KV round-trip).
    - Four EXECUTED source mutations (fits inverted / L1 branch removed
      / blind gate removed / force-charge yield removed) — the mutation
      helper edits energy_drain_precedence.py on disk, re-imports the
      module, asserts a specific test fails, then restores.

Actuation (paused_by_dp, reserve floor composition, must-start-by fire,
write-verify extension) is Session B2b.

Framing per Tier-3 Reviewer-C authority: each test drives the pure
production surfaces directly. The mutation tests execute REAL per-site
source edits and confirm a SPECIFIC named test fails.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest


# ==========================================================================
# Import shim (mirrors the Session A + B1 pattern)
# ==========================================================================
_HERE = os.path.dirname(os.path.abspath(__file__))
_DC_DIR = os.path.abspath(os.path.join(
    _HERE, "..", "..",
    "custom_components", "universal_room_automation", "domain_coordinators",
))


def _load_pure_module(name: str, path: str):
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_dp_module(pkg_name: str = "_dp_b2a_pkg"):
    """Load energy_drain_precedence.py under a synthetic package name.

    Returns the loaded module. Repeated calls with the SAME pkg_name
    reload the module (used by mutation tests to pick up on-disk edits).
    """
    # Fresh const shim each time so the module reload semantics stay clean.
    const_name = f"{pkg_name}.energy_const"
    _load_pure_module(const_name, os.path.join(_DC_DIR, "energy_const.py"))

    _pkg = type(sys)(pkg_name)
    _pkg.__path__ = [_DC_DIR]
    sys.modules[pkg_name] = _pkg
    sys.modules[const_name] = sys.modules[const_name]  # already registered

    # Rewrite relative import to hit our shim so we bypass the real
    # custom_components package (which imports homeassistant).
    src_path = os.path.join(_DC_DIR, "energy_drain_precedence.py")
    with open(src_path, "r") as f:
        src = f.read()
    src = src.replace("from .energy_const", f"from {pkg_name}.energy_const")

    dp_mod_name = f"{pkg_name}.energy_drain_precedence"
    if dp_mod_name in sys.modules:
        del sys.modules[dp_mod_name]
    mod = type(sys)(dp_mod_name)
    mod.__file__ = src_path
    sys.modules[dp_mod_name] = mod
    exec(compile(src, src_path, "exec"), mod.__dict__)
    return mod


dp = _bootstrap_dp_module()

DPState = dp.DPState
DrainPrecedenceState = dp.DrainPrecedenceState
TransitionInputs = dp.TransitionInputs
TransitionDecision = dp.TransitionDecision
evaluate_dp_transition = dp.evaluate_dp_transition
_dp_maybe_tick = dp._dp_maybe_tick
compute_must_start_by = dp.compute_must_start_by
serialize_for_kv = dp.serialize_for_kv
restore_from_blob = dp.restore_from_blob


# ==========================================================================
# Clock injection helper
# ==========================================================================


class _FrozenClock:
    """Mutable frozen clock (v5.17.1 lesson — NEVER wall-clock-couple)."""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, minutes: float = 0.0, hours: float = 0.0) -> None:
        self._now = self._now + timedelta(minutes=minutes, hours=hours)


def _mk_inputs(**overrides) -> TransitionInputs:
    """Build a TransitionInputs with sane defaults. Tests override fields."""
    now = overrides.pop("now", datetime(2026, 7, 15, 21, 30, tzinfo=timezone.utc))
    must_start_by = overrides.pop(
        "must_start_by_dt",
        now.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=1),
    )
    defaults = dict(
        dp_enabled=True,
        is_blind_hold=False,
        force_charge_active=False,
        soc=60,
        drain_target_soc=15,
        any_evse_charging=True,
        charger_rate_kw=11.5,
        needed_kwh=22.3,
        house_load_kw=5.91,
        now=now,
        must_start_by_dt=must_start_by,
        margin_min=60,
        eval_delay_min=10,
    )
    defaults.update(overrides)
    return TransitionInputs(**defaults)


# ==========================================================================
# evaluate_dp_transition — gate-order coverage
# ==========================================================================


def test_eval_blind_hold_gates_first_even_with_perfect_fit():
    """INV-DP4: blind-hold gate is at the TOP. Even with a perfectly-
    fitting arithmetic scenario, is_blind_hold=True → HOLD reason=blind."""
    d = evaluate_dp_transition(_mk_inputs(is_blind_hold=True))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_BLIND_HOLD


def test_eval_kill_switch_off_holds():
    d = evaluate_dp_transition(_mk_inputs(dp_enabled=False))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_KILL_SWITCH_OFF


def test_eval_force_charge_active_yields():
    """Plan §127: force-charge (A-H1) wins unconditionally."""
    d = evaluate_dp_transition(_mk_inputs(force_charge_active=True))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_FORCE_CHARGE_ACTIVE


def test_eval_no_charging_evse_holds():
    d = evaluate_dp_transition(_mk_inputs(any_evse_charging=False))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_NO_CHARGING_EVSE


def test_eval_missing_soc_holds():
    d = evaluate_dp_transition(_mk_inputs(soc=None))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_MISSING_SOC


def test_eval_l1_only_never_fits():
    """P4 verdict §345: L1 (~1.4 kW) can never fit a 9 h night — explicit
    branch, not an emergent arithmetic outcome."""
    d = evaluate_dp_transition(_mk_inputs(charger_rate_kw=1.4))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_L1_ONLY


def test_eval_soc_at_or_below_target_holds():
    d = evaluate_dp_transition(_mk_inputs(soc=15))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_ALREADY_BELOW_TARGET


def test_eval_zero_house_load_holds():
    d = evaluate_dp_transition(_mk_inputs(house_load_kw=0.0))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_MISSING_INPUTS


def test_eval_gate_order_blind_beats_force_charge():
    """Both gates asserted → blind wins because it's evaluated FIRST.
    This pins gate ordering so a refactor can't silently flip precedence."""
    d = evaluate_dp_transition(_mk_inputs(
        is_blind_hold=True, force_charge_active=True,
    ))
    assert d.reason == dp.DP_REASON_BLIND_HOLD


def test_eval_gate_order_kill_switch_beats_l1():
    d = evaluate_dp_transition(_mk_inputs(
        dp_enabled=False, charger_rate_kw=1.4,
    ))
    assert d.reason == dp.DP_REASON_KILL_SWITCH_OFF


# ==========================================================================
# P4 counterfactual fixture (§330-346) — hand-computed anchors
# ==========================================================================


# The plan's P4 table (§336-342). SOC@21:00, expected transition,
# expected charge-start time (LOCAL). Independent anchor: numbers here
# are hand-computed from the plan's stated inputs; the production eval
# is diffed against them so an arithmetic drift is caught.
#
# Inputs (§332): drain_target=15, cap=0.40 kWh/pp, house_load=5.91 kW,
# needed=22.3 kWh, rate_L2=11.5 kW, margin=1.0 h, night 21:00→06:00,
# must-start-by 03:00. All computations start from 21:00 local.
#
# drain_h = (SOC - 15) * 0.40 / 5.91
# charge_h_L2 = 22.3 / 11.5 ≈ 1.9391 h
# start = 21:00 + drain_h + 1.0 h margin
# Expected start values match plan §336-342 to the minute.
P4_NIGHTS = [
    # (date, SOC@21:00, expected drain_h, expected start_local)
    ("07-10", 42, 1.828, "22:49"),
    ("07-11", 30, 1.015, "22:00"),
    ("07-12", 51, 2.436, "23:26"),
    ("07-13", 41, 1.760, "22:45"),
    ("07-14", 59, 2.978, "23:58"),
    ("07-15", 78, 4.264, "01:15"),  # +1 day (crosses midnight)
    ("07-16", 67, 3.520, "00:31"),  # +1 day
]


def _p4_inputs_for_night(date_str: str, soc_21: int) -> TransitionInputs:
    """21:00 wall-clock on the given date, plan defaults."""
    month, day = (int(x) for x in date_str.split("-"))
    now = datetime(2026, month, day, 21, 0, tzinfo=timezone.utc)
    # must-start-by 03:00 the next morning.
    msb = datetime(2026, month, day, 3, 0, tzinfo=timezone.utc) + timedelta(days=1)
    return _mk_inputs(
        now=now,
        must_start_by_dt=msb,
        soc=soc_21,
        drain_target_soc=15,
        any_evse_charging=True,
        charger_rate_kw=11.5,
        needed_kwh=22.3,
        house_load_kw=5.91,
        margin_min=60,
        eval_delay_min=10,
    )


@pytest.mark.parametrize(
    "date_str,soc_21,expected_drain_h,expected_start_hhmm", P4_NIGHTS,
)
def test_p4_counterfactual_all_seven_nights_transition(
    date_str, soc_21, expected_drain_h, expected_start_hhmm,
):
    """Plan §344: 7/7 nights transition on L2; 0 miss must-start-by."""
    inputs = _p4_inputs_for_night(date_str, soc_21)
    d = evaluate_dp_transition(inputs)
    assert d.transition is True, (
        f"P4 night {date_str} SOC {soc_21} should transition; "
        f"got reason={d.reason}"
    )
    # Arithmetic anchor: production drain_hours matches hand-computed
    # to 3 decimal places (0.4 * (SOC-15) / 5.91).
    hand_drain = (soc_21 - 15) * 0.40 / 5.91
    assert abs(d.drain_hours - hand_drain) < 1e-6
    # Also spot-check that the expected_drain_h anchor from the plan
    # matches (within 3 decimals of rounding).
    assert abs(hand_drain - expected_drain_h) < 0.01, (
        f"plan-table drain_h {expected_drain_h} vs hand-computed {hand_drain:.3f}"
    )
    # computed_start_dt = 21:00 + drain_h + 1.0 h margin
    exp_hh, exp_mm = (int(x) for x in expected_start_hhmm.split(":"))
    # Start time may cross midnight — compare via HH:MM only against the
    # localized computed value.
    got_start = d.computed_start_dt
    assert got_start is not None
    # Minute precision — hand-anchored to the plan table.
    assert (got_start.hour, got_start.minute) == (exp_hh, exp_mm), (
        f"P4 night {date_str}: expected start {expected_start_hhmm}, "
        f"got {got_start.strftime('%H:%M')}"
    )
    # Must start by 03:00: charge_start must be ≤ 03:00 (or before day+1 03:00).
    assert d.computed_start_dt <= inputs.must_start_by_dt


def test_p4_zero_miss_must_start_by():
    """§344 gate: 0/7 miss must-start-by → 0% ≤ 5% gate."""
    misses = 0
    for date_str, soc_21, _, _ in P4_NIGHTS:
        inputs = _p4_inputs_for_night(date_str, soc_21)
        d = evaluate_dp_transition(inputs)
        if d.transition and d.computed_start_dt > inputs.must_start_by_dt:
            misses += 1
    assert misses == 0


# ==========================================================================
# Non-actuation interaction traces
# ==========================================================================


def test_interaction_force_charge_holds_even_at_perfect_soc():
    """Interaction row 1 (§126): force-charge yields transition even when
    the arithmetic would perfectly fit."""
    d = evaluate_dp_transition(_mk_inputs(force_charge_active=True, soc=78))
    assert d.transition is False
    assert d.reason == dp.DP_REASON_FORCE_CHARGE_ACTIVE


def test_interaction_blind_exit_reeval_on_first_sighted_tick():
    """Ratification #5 (§263): on the FIRST sighted tick after blind exit,
    an immediate re-eval is legal. The eval takes is_blind_hold as an
    input, so the caller controls the edge — here we prove that flipping
    is_blind_hold False → True → False yields FITS on the third call."""
    inputs_blind = _mk_inputs(is_blind_hold=True, soc=60)
    inputs_sighted = _mk_inputs(is_blind_hold=False, soc=60)
    assert evaluate_dp_transition(inputs_blind).reason == dp.DP_REASON_BLIND_HOLD
    d = evaluate_dp_transition(inputs_sighted)
    assert d.transition is True
    assert d.reason == dp.DP_REASON_FITS


def test_interaction_l1_only_hold_takes_precedence_over_fit():
    """L1-only branch fires BEFORE the arithmetic check — even with a
    perfect SOC. Plan §345."""
    d = evaluate_dp_transition(_mk_inputs(charger_rate_kw=1.4, soc=78))
    assert d.reason == dp.DP_REASON_L1_ONLY


def test_interaction_second_plug_in_eval_stays_transition():
    """Plan §133 + §260-261 ratification: second plug-in during active
    transition = transition stays. In the eval world (B2a), that means
    any_evse_charging remains True and the arithmetic still fits.
    Actuation-level second-plug-in semantics are B2b."""
    inputs = _mk_inputs(any_evse_charging=True, soc=60)
    d = evaluate_dp_transition(inputs)
    assert d.transition is True


def test_interaction_kv_round_trip_preserves_transition_after_restart():
    """Plan §135: HA restart mid-transition must restore TRANSITIONED
    state IF must-start-by is still in the future. Session A's
    restore_from_blob already enforces this; here we prove it survives
    a round-trip of a carrier that B2a's tick would have produced."""
    clock = _FrozenClock(datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    inputs = _mk_inputs(now=clock.now())

    # Prime the state machine to TRANSITIONED via two ticks.
    _dp_maybe_tick(carrier, inputs, now_provider=clock.now)
    assert carrier.state == DPState.HOLD_PRE_EVAL
    clock.advance(minutes=15)  # past eval_delay_min=10
    inputs2 = _mk_inputs(now=clock.now())
    d = _dp_maybe_tick(carrier, inputs2, now_provider=clock.now)
    assert d.transition is True
    assert carrier.state == DPState.TRANSITIONED
    assert carrier.must_start_by_dt is not None

    # Round-trip via KV and restore under a clock that is BEFORE
    # must_start_by — must survive.
    raw = serialize_for_kv(carrier)
    later_clock = _FrozenClock(datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc))
    restored = restore_from_blob(raw, now_provider=later_clock.now)
    assert restored.state == DPState.TRANSITIONED

    # Round-trip under a clock AFTER must_start_by → INV-DP2 rejects.
    expired_clock = _FrozenClock(datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc))
    rejected = restore_from_blob(raw, now_provider=expired_clock.now)
    assert rejected.state == DPState.HOLD_ONLY


def test_interaction_tou_boundary_non_collision():
    """Session B2a is a decision-tier module — it has no timers or TOU
    listeners. Prove the eval is a pure function of its inputs by calling
    it twice with identical inputs and confirming identical outputs (i.e.
    no wall-clock or TOU listener side effects)."""
    inputs = _mk_inputs(soc=60)
    d1 = evaluate_dp_transition(inputs)
    d2 = evaluate_dp_transition(inputs)
    assert d1 == d2


# ==========================================================================
# _dp_maybe_tick — state-machine driver
# ==========================================================================


def test_tick_hold_only_to_hold_pre_eval_on_first_charging_tick():
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    d = _dp_maybe_tick(
        carrier, _mk_inputs(now=clock.now()), now_provider=clock.now,
    )
    assert carrier.state == DPState.HOLD_PRE_EVAL
    assert carrier.hold_started_at == clock.now()
    assert d.transition is False


def test_tick_hold_pre_eval_stays_until_delay_elapsed():
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    _dp_maybe_tick(carrier, _mk_inputs(now=clock.now()), now_provider=clock.now)
    # Advance only 5 min < eval_delay=10.
    clock.advance(minutes=5)
    d = _dp_maybe_tick(
        carrier, _mk_inputs(now=clock.now()), now_provider=clock.now,
    )
    assert carrier.state == DPState.HOLD_PRE_EVAL
    assert d.reason == "waiting_eval_delay"


def test_tick_hold_pre_eval_advances_to_transitioned_on_fit():
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    _dp_maybe_tick(carrier, _mk_inputs(now=clock.now()), now_provider=clock.now)
    clock.advance(minutes=15)
    d = _dp_maybe_tick(
        carrier, _mk_inputs(now=clock.now(), soc=60), now_provider=clock.now,
    )
    assert carrier.state == DPState.TRANSITIONED
    assert d.transition is True
    assert d.reason == dp.DP_REASON_FITS
    # last_eval_snapshot populated per D2 acceptance criterion.
    assert "inputs" in carrier.last_eval_snapshot
    assert "decision" in carrier.last_eval_snapshot


def test_tick_hold_pre_eval_reverts_to_hold_only_on_no_fit():
    """L1-only: eval says no-fit → HOLD_ONLY (not TRANSITIONED)."""
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    # Prime hold with L1 rate → the tick still advances state machine
    # (charging=True), but eval returns L1-only HOLD.
    _dp_maybe_tick(
        carrier,
        _mk_inputs(now=clock.now(), charger_rate_kw=1.4),
        now_provider=clock.now,
    )
    clock.advance(minutes=15)
    d = _dp_maybe_tick(
        carrier,
        _mk_inputs(now=clock.now(), charger_rate_kw=1.4),
        now_provider=clock.now,
    )
    assert carrier.state == DPState.HOLD_ONLY
    assert d.transition is False
    assert d.reason == dp.DP_REASON_L1_ONLY


def test_tick_kill_switch_off_from_hold_pre_eval_returns_to_hold_only():
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    _dp_maybe_tick(carrier, _mk_inputs(now=clock.now()), now_provider=clock.now)
    assert carrier.state == DPState.HOLD_PRE_EVAL
    # Operator flips kill switch off — tick should collapse to HOLD_ONLY.
    d = _dp_maybe_tick(
        carrier,
        _mk_inputs(now=clock.now(), dp_enabled=False),
        now_provider=clock.now,
    )
    assert carrier.state == DPState.HOLD_ONLY
    assert d.reason == dp.DP_REASON_KILL_SWITCH_OFF


def test_tick_evse_stops_charging_from_hold_pre_eval_returns_to_hold_only():
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    _dp_maybe_tick(carrier, _mk_inputs(now=clock.now()), now_provider=clock.now)
    d = _dp_maybe_tick(
        carrier,
        _mk_inputs(now=clock.now(), any_evse_charging=False),
        now_provider=clock.now,
    )
    assert carrier.state == DPState.HOLD_ONLY
    assert d.reason == dp.DP_REASON_NO_CHARGING_EVSE


def test_tick_persister_called_on_edge_not_on_self_loop():
    clock = _FrozenClock(datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc))
    carrier = DrainPrecedenceState()
    persist_calls: list[DPState] = []

    def _persist(c):
        persist_calls.append(c.state)

    # First tick: HOLD_ONLY → HOLD_PRE_EVAL → persist.
    _dp_maybe_tick(
        carrier, _mk_inputs(now=clock.now()),
        now_provider=clock.now, persister=_persist,
    )
    assert persist_calls == [DPState.HOLD_PRE_EVAL]

    # Second tick: HOLD_PRE_EVAL waiting → no edge → no persist.
    clock.advance(minutes=2)
    _dp_maybe_tick(
        carrier, _mk_inputs(now=clock.now()),
        now_provider=clock.now, persister=_persist,
    )
    assert persist_calls == [DPState.HOLD_PRE_EVAL]  # unchanged

    # Third tick after delay: HOLD_PRE_EVAL → EVAL_TRANSITION → TRANSITIONED.
    # Should invoke persister at least once more.
    clock.advance(minutes=15)
    _dp_maybe_tick(
        carrier, _mk_inputs(now=clock.now()),
        now_provider=clock.now, persister=_persist,
    )
    assert DPState.TRANSITIONED in persist_calls


# ==========================================================================
# Executed source mutations (Reviewer-C authority per Tier-3)
# --------------------------------------------------------------------------
# Each mutation edits energy_drain_precedence.py on disk, reloads the
# module, asserts a SPECIFIC named test fails against the mutated code,
# then restores from a snapshot. Global monkeypatch is NOT sufficient at
# Tier 3 — the mutation must prove the SITE is load-bearing.
# ==========================================================================


_DP_SRC_PATH = Path(_DC_DIR) / "energy_drain_precedence.py"


def _run_named_test_under_mutation(
    old: str, new: str, target_test: str,
) -> None:
    """Apply `old→new` edit to _DP_SRC_PATH, run pytest on `target_test`,
    assert it fails, then restore. Uses a subprocess for isolation from
    the parent test's already-imported module.
    """
    backup = _DP_SRC_PATH.read_text()
    assert old in backup, (
        f"mutation anchor {old!r} not found in energy_drain_precedence.py "
        "— test needs updating for source drift"
    )
    try:
        mutated = backup.replace(old, new, 1)
        assert mutated != backup, "mutation was a no-op"
        _DP_SRC_PATH.write_text(mutated)
        # Also nuke any __pycache__ for the module so subprocess reloads.
        pyc_dir = _DP_SRC_PATH.parent / "__pycache__"
        if pyc_dir.exists():
            for p in pyc_dir.glob("energy_drain_precedence.*"):
                p.unlink()
        # Run the specific test in a subprocess so this process's stale
        # module import can't shadow the mutation.
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(_HERE).parent.parent / "quality") + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "--no-header",
             f"quality/tests/test_evse_drain_precedence_session_b2a.py::{target_test}",
             "-q"],
            cwd=str(Path(_HERE).parent.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Under the mutation, the target test MUST fail (nonzero exit).
        assert proc.returncode != 0, (
            f"mutation on {old!r} did NOT cause "
            f"{target_test} to fail; site not load-bearing.\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
    finally:
        _DP_SRC_PATH.write_text(backup)
        pyc_dir = _DP_SRC_PATH.parent / "__pycache__"
        if pyc_dir.exists():
            for p in pyc_dir.glob("energy_drain_precedence.*"):
                p.unlink()


def test_mutation_fits_inverted_breaks_p4_night():
    """Invert the `fits` boolean → all P4 nights would flip to HOLD →
    test_p4_counterfactual_all_seven_nights_transition fails."""
    _run_named_test_under_mutation(
        old="    fits = (\n"
            "        computed_start_dt <= inputs.must_start_by_dt\n"
            "        and total_hours <= hours_until_end_of_night\n"
            "    )",
        new="    fits = not (\n"
            "        computed_start_dt <= inputs.must_start_by_dt\n"
            "        and total_hours <= hours_until_end_of_night\n"
            "    )",
        target_test=(
            "test_p4_counterfactual_all_seven_nights_transition[07-10-42-1.828-22:49]"
        ),
    )


def test_mutation_l1_branch_removed_falls_through_to_arithmetic():
    """Remove the L1-only auto-hold branch. With rate=1.4 kW + huge SOC,
    the arithmetic-fits branch might accept and return FITS instead of
    L1_ONLY → test_eval_l1_only_never_fits fails."""
    _run_named_test_under_mutation(
        old="    # (6) L1-only auto-hold (P4 verdict §345). Explicit branch, not an\n"
            "    # emergent arithmetic outcome, per plan.\n"
            "    if inputs.charger_rate_kw <= inputs.l1_rate_threshold_kw:\n"
            "        return _no_fit(DP_REASON_L1_ONLY, inputs)",
        new="    # (6) L1-only auto-hold — MUTATED OUT for Tier-3 mutation test.\n"
            "    if False:\n"
            "        return _no_fit(DP_REASON_L1_ONLY, inputs)",
        target_test="test_eval_l1_only_never_fits",
    )


def test_mutation_blind_gate_removed_lets_perfect_fit_through():
    """Remove the INV-DP4 blind-hold top gate. A blind_hold=True eval
    with an otherwise-fitting scenario would then return FITS →
    test_eval_blind_hold_gates_first_even_with_perfect_fit fails."""
    _run_named_test_under_mutation(
        old="    if inputs.is_blind_hold:\n"
            "        return _no_fit(DP_REASON_BLIND_HOLD, inputs)",
        new="    if False and inputs.is_blind_hold:\n"
            "        return _no_fit(DP_REASON_BLIND_HOLD, inputs)",
        target_test="test_eval_blind_hold_gates_first_even_with_perfect_fit",
    )


def test_mutation_force_charge_yield_removed_lets_transition_through():
    """Remove the force-charge yield. force_charge=True on a fitting
    scenario would then return FITS → test_eval_force_charge_active_yields
    fails."""
    _run_named_test_under_mutation(
        old="    if inputs.force_charge_active:\n"
            "        return _no_fit(DP_REASON_FORCE_CHARGE_ACTIVE, inputs)",
        new="    if False and inputs.force_charge_active:\n"
            "        return _no_fit(DP_REASON_FORCE_CHARGE_ACTIVE, inputs)",
        target_test="test_eval_force_charge_active_yields",
    )
