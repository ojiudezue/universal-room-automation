"""DP-OBSERVABILITY-1 — presentation-only sensor attrs (no decision-logic
changes). Cycle spec: `sensor.ura_energy_coordinator_ev_charging_plan`
misread on 2026-08-11 as "charging blocked" when hold_only is the
RESTING state, plus a 4-day-old last_eval_snapshot rendered as if
current.

Scope of this file:
    - `to_attrs(now=...)` shape tests for the new attrs
      (`eval_age_min`, `state_meaning`, `must_start_by_expired`,
      `must_start_by_dt`-when-past → None with `must_start_by_dt_raw`
      preserved).
    - Backwards-compat: `to_attrs()` with no arg preserves prior shape
      (existing test in test_energy_drain_precedence_state_machine.py
      keeps passing).
    - Byte-identity guard: eval + tick decision path (`evaluate_dp_transition`,
      `_dp_maybe_tick`) is untouched by this cycle — mutating the source
      of any new observability attr must NOT change the eval outputs.

The module loader mirrors test_energy_drain_precedence_state_machine.py
(HA-free load via a synthetic package shim).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest


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


_const = _load(
    "_dp_obs1_energy_const",
    os.path.join(_DC_DIR, "energy_const.py"),
)
_pkg = type(sys)("_dp_obs1_pkg")
_pkg.__path__ = [_DC_DIR]
sys.modules["_dp_obs1_pkg"] = _pkg
sys.modules["_dp_obs1_pkg.energy_const"] = _const

_dp_src_path = os.path.join(_DC_DIR, "energy_drain_precedence.py")
with open(_dp_src_path, "r") as _f:
    _dp_src = _f.read()
_dp_src = _dp_src.replace(
    "from .energy_const", "from _dp_obs1_pkg.energy_const"
)
_dp_mod = type(sys)("_dp_obs1_pkg.energy_drain_precedence")
_dp_mod.__file__ = _dp_src_path
sys.modules["_dp_obs1_pkg.energy_drain_precedence"] = _dp_mod
exec(compile(_dp_src, _dp_src_path, "exec"), _dp_mod.__dict__)

dp = _dp_mod
DPState = _dp_mod.DPState
DrainPrecedenceState = _dp_mod.DrainPrecedenceState


def _tz_now() -> datetime:
    return datetime(2026, 8, 11, 22, 0, 0, tzinfo=timezone.utc)


# ==========================================================================
# D3: state_meaning present for every state
# ==========================================================================


def test_state_meaning_present_for_every_dp_state():
    """Every DPState value has a `state_meaning` entry — no unmapped state
    can slip through and render as None on the sensor. Guards against the
    2026-08-11 misread where an operator had no in-attrs clue what
    `hold_only` semantically means."""
    for st in DPState:
        c = DrainPrecedenceState(state=st)
        attrs = c.to_attrs(now=_tz_now())
        assert attrs["state_meaning"] is not None, (
            f"state_meaning missing for {st.value}"
        )
        assert isinstance(attrs["state_meaning"], str)
        assert len(attrs["state_meaning"]) > 0


def test_hold_only_state_meaning_conveys_resting_not_blocked():
    """The 2026-08-11 misread: hold_only was read as 'charging blocked'.
    The one-line meaning MUST convey that hold_only is a RESTING state."""
    c = DrainPrecedenceState(state=DPState.HOLD_ONLY)
    attrs = c.to_attrs(now=_tz_now())
    meaning = attrs["state_meaning"].lower()
    assert "resting" in meaning
    assert "off-peak" in meaning or "off_peak" in meaning


# ==========================================================================
# D1: eval_age_min
# ==========================================================================


def test_eval_age_min_none_when_never_evaluated():
    c = DrainPrecedenceState(state=DPState.HOLD_ONLY)
    attrs = c.to_attrs(now=_tz_now())
    assert attrs["eval_age_min"] is None


def test_eval_age_min_computes_minutes_since_last_eval():
    now = _tz_now()
    c = DrainPrecedenceState(
        state=DPState.HOLD_ONLY, last_eval_at=now - timedelta(minutes=42),
    )
    attrs = c.to_attrs(now=now)
    assert attrs["eval_age_min"] == pytest.approx(42.0, abs=0.01)


def test_eval_age_min_stale_matches_2026_08_11_misdiagnosis():
    """4-day-old last_eval_at (the 2026-08-11 misread scenario) surfaces
    as a large positive number, making staleness explicit rather than
    presenting the snapshot as if fresh."""
    now = _tz_now()
    c = DrainPrecedenceState(
        state=DPState.HOLD_ONLY,
        last_eval_at=now - timedelta(days=4),
        last_eval_snapshot={"decision": {"reason": "does_not_fit"}},
    )
    attrs = c.to_attrs(now=now)
    assert attrs["eval_age_min"] == pytest.approx(4 * 24 * 60, abs=0.1)


def test_eval_age_min_omitted_when_no_now_supplied_backcompat():
    """`to_attrs()` without a clock returns eval_age_min=None so existing
    tests (`test_energy_drain_precedence_state_machine.test_to_attrs_
    contains_d1_acceptance_criteria_fields`) keep passing."""
    now = _tz_now()
    c = DrainPrecedenceState(last_eval_at=now - timedelta(minutes=5))
    attrs = c.to_attrs()
    assert attrs["eval_age_min"] is None


# ==========================================================================
# D2: must_start_by_dt shape when in past
# ==========================================================================


def test_must_start_by_rendered_none_when_expired_with_flag():
    """An expired must_start_by_dt renders as None (can't be misread as
    a current plan) with `must_start_by_expired: true` and the raw ISO
    value preserved in `must_start_by_dt_raw`."""
    now = _tz_now()
    past = now - timedelta(hours=6)
    c = DrainPrecedenceState(
        state=DPState.HOLD_ONLY, must_start_by_dt=past,
    )
    attrs = c.to_attrs(now=now)
    assert attrs["must_start_by_dt"] is None
    assert attrs["must_start_by_expired"] is True
    assert attrs["must_start_by_dt_raw"] == past.isoformat()


def test_must_start_by_rendered_iso_when_future():
    now = _tz_now()
    future = now + timedelta(hours=5)
    c = DrainPrecedenceState(
        state=DPState.TRANSITIONED, must_start_by_dt=future,
    )
    attrs = c.to_attrs(now=now)
    assert attrs["must_start_by_dt"] == future.isoformat()
    assert attrs["must_start_by_expired"] is False
    assert attrs["must_start_by_dt_raw"] == future.isoformat()


def test_must_start_by_none_all_shapes_when_unset():
    now = _tz_now()
    c = DrainPrecedenceState(state=DPState.HOLD_ONLY, must_start_by_dt=None)
    attrs = c.to_attrs(now=now)
    assert attrs["must_start_by_dt"] is None
    assert attrs["must_start_by_dt_raw"] is None
    assert attrs["must_start_by_expired"] is False


def test_must_start_by_expired_false_when_no_now_backcompat():
    now = _tz_now()
    past = now - timedelta(hours=6)
    c = DrainPrecedenceState(must_start_by_dt=past)
    attrs = c.to_attrs()
    # Without a clock we can't determine expiry — surface raw shape,
    # never claim expired without evidence.
    assert attrs["must_start_by_expired"] is False
    assert attrs["must_start_by_dt"] == past.isoformat()


# ==========================================================================
# Byte-identity guard: decision path untouched
# ==========================================================================


def test_evaluate_dp_transition_unchanged_by_observability_cycle():
    """The eval function must produce identical decisions before/after
    this cycle. We rebuild TransitionInputs matching the b2a fixture and
    diff every field on the returned TransitionDecision against expected
    values captured from the pre-cycle codepath."""
    TransitionInputs = dp.TransitionInputs
    now = datetime(2026, 7, 15, 21, 30, tzinfo=timezone.utc)
    inputs = TransitionInputs(
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
        must_start_by_dt=(
            now.replace(hour=3, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        ),
        margin_min=60,
        eval_delay_min=10,
    )
    d = dp.evaluate_dp_transition(inputs)
    # These values come from the pre-cycle behavior. If this test fails
    # after DP-OBSERVABILITY-1, the cycle violated its byte-identity
    # invariant on the decision path.
    assert d.reason == dp.DP_REASON_FITS
    assert d.transition is True
    assert d.drain_hours == pytest.approx(
        (60 - 15) * 0.40 / 5.91, abs=1e-6
    )
    assert d.charge_hours == pytest.approx(22.3 / 11.5, abs=1e-6)
    assert d.margin_hours == pytest.approx(1.0, abs=1e-6)


def test_dp_maybe_tick_unchanged_hold_only_arm_edge():
    """HOLD_ONLY + charging + enabled → arms HOLD_PRE_EVAL. Byte-identity
    check: this transition must fire regardless of observability cycle."""
    TransitionInputs = dp.TransitionInputs
    now = _tz_now()
    inputs = TransitionInputs(
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
        must_start_by_dt=now + timedelta(hours=5),
        margin_min=60,
        eval_delay_min=10,
    )
    carrier = DrainPrecedenceState(state=DPState.HOLD_ONLY)
    dp._dp_maybe_tick(carrier, inputs, now_provider=lambda: now)
    assert carrier.state == DPState.HOLD_PRE_EVAL


# ==========================================================================
# get_status recompute cadence — pause_reason_human timestamp
# ==========================================================================
# The get_status test lives here rather than in energy_pool tests because
# it's part of the DP-OBSERVABILITY-1 acceptance surface (D5). We use a
# minimal in-place stub — the reasons_computed_at attr is a pure product
# of the get_status call site.


def test_reasons_computed_at_present_in_ev_charging_status_shape():
    """D5: `pause_reason_human` recomputes per get_status() call; the new
    `reasons_computed_at` ISO timestamp attr surfaces that recompute so
    an operator can distinguish 'no reason' from 'stale reason'. This
    test grep-asserts the emit site in energy_pool.py (the loaded module
    is HA-coupled; we verify at source level)."""
    ep_path = os.path.join(_DC_DIR, "energy_pool.py")
    with open(ep_path, "r") as f:
        src = f.read()
    assert 'status["reasons_computed_at"] = now_local.isoformat()' in src, (
        "D5 site missing — reasons_computed_at must be emitted from "
        "get_status alongside pause_reason_human"
    )
    # Sanity: the emit is inside get_status, positioned AFTER the
    # pause_reason_human assignment (so operators reading it see the
    # timestamp of the reasons they were just given).
    pr_idx = src.rfind('status["pause_reason_human"] = pause_reason_human')
    rc_idx = src.find('status["reasons_computed_at"] = now_local.isoformat()')
    assert pr_idx != -1 and rc_idx != -1
    assert rc_idx > pr_idx


# ==========================================================================
# Sensor eval_gate site verification
# ==========================================================================


def test_eval_gate_reasons_enumerate_the_gate_inputs():
    """D4: the sensor's `_compute_eval_gate` returns stable identifiers
    for each reason the eval isn't running right now. Source-grep the
    identifier set so a refactor that renames one is caught."""
    sensor_path = os.path.abspath(os.path.join(
        _HERE, "..", "..",
        "custom_components", "universal_room_automation", "sensor.py",
    ))
    with open(sensor_path, "r") as f:
        src = f.read()
    assert "def _compute_eval_gate(" in src
    for token in (
        '"dp_disabled"',
        '"not_off_peak"',
        '"no_evse_charging"',
        '"waiting_eval_delay"',
        '"eligible"',
    ):
        assert token in src, f"eval_gate reason token missing: {token}"
    # The gate must consult the SAME inputs energy.py's decision gate
    # reads — confirm by name so a rename in energy.py surfaces here.
    assert "is_dp_enabled" in src
    assert "get_current_period" in src
    assert "_is_any_evse_charging" in src
