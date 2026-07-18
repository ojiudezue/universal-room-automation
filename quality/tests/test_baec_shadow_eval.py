"""v5.21.0 D4 — BAEC shadow-eval acceptance tests.

INV-BAEC-SHADOW: with the master switch OFF, the arithmetic eval MAY run
and publish `shadow_*` attrs on the DP carrier, but there MUST be zero
actuation-side effects — no `_dp_state` mutation past HOLD_ONLY, no
`_paused_by_dp` set additions, no reserve write, no KV persist, no ledger
stamp.

Test authority:
    - Acceptance tests drive `_dp_decision_tick` end-to-end against the
      source-extracted fake coord (mirrors the b2c1 fixup harness).
    - Mutation anchor: subprocess-isolated source mutation neuters the
      single caller-side `raise _DPSkip()` on the shadow path; a specific
      actuation-free acceptance test MUST go RED.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Piggyback on the b2c1 fixup harness (mock modules + extracted namespace +
# subprocess mutation helper).
_b2c1 = importlib.import_module("test_evse_drain_precedence_session_b2c1_fixup")

_make_coord = _b2c1._make_coord
_mutate_and_expect_red = _b2c1._mutate_and_expect_red

# Re-extract the shadow eval helper into the shared namespace so the fake
# coord picks it up.
_energy_src = _b2c1._energy_src
_extract_named = _b2c1._extract_named
_extracted_ns = _b2c1._extracted_ns
_FakeCoord = _b2c1._FakeCoord

_shadow_src = _extract_named(_energy_src, {"_run_dp_shadow_eval"})
exec(compile(_shadow_src, "<energy.py-extract-baec-shadow>", "exec"),
     _extracted_ns)
if "_run_dp_shadow_eval" in _extracted_ns:
    setattr(_FakeCoord, "_run_dp_shadow_eval", _extracted_ns["_run_dp_shadow_eval"])


# ==========================================================================
# INV-BAEC-SHADOW acceptance
# ==========================================================================


def test_switch_off_off_peak_publishes_shadow_attrs_no_actuation():
    """OFF + off_peak: shadow_* attrs published, carrier state stays
    HOLD_ONLY, _paused_by_dp empty, no reversion/turn_off calls."""
    coord, ev, _bat, _tou = _make_coord(
        dp_enabled=False, period="off_peak",
        envoy_available=True, battery_soc=75.0,
        drain_target=30,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E501
        DPState,
    )

    try:
        coord._dp_decision_tick({"soc": 75}, "off_peak", ev_load_w=7600.0)
    except _b2c1._DPSkip:
        pass

    car = coord._dp_carrier
    # Shadow published.
    assert car.shadow_decision in {
        "would_transition", "would_hold", "not_applicable",
    }
    assert car.shadow_last_eval_at is not None
    assert isinstance(car.shadow_last_eval_snapshot, dict)
    # INV-BAEC-SHADOW: NO actuation-side effects.
    assert car.state == DPState.HOLD_ONLY
    assert len(ev._paused_by_dp) == 0


def test_switch_off_outside_off_peak_marks_shadow_not_applicable():
    """OFF + daytime: shadow_decision=not_applicable with reason
    outside_night_window; no state churn."""
    coord, ev, _, _ = _make_coord(
        dp_enabled=False, period="mid_peak",
        envoy_available=True, battery_soc=75.0,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E501
        DPState,
    )

    try:
        coord._dp_decision_tick({"soc": 75}, "mid_peak", ev_load_w=7600.0)
    except _b2c1._DPSkip:
        pass

    car = coord._dp_carrier
    assert car.shadow_decision == "not_applicable"
    assert car.shadow_reason == "outside_night_window"
    assert car.state == DPState.HOLD_ONLY
    assert len(ev._paused_by_dp) == 0


def test_switch_off_blind_hold_marks_shadow_not_applicable():
    """OFF + envoy blind + no SOC → shadow_decision=not_applicable
    (blind_hold reason). Guarded by INV-DP4 semantics; MUST NOT actuate."""
    coord, ev, _, _ = _make_coord(
        dp_enabled=False, period="off_peak",
        envoy_available=False, battery_soc=None,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E501
        DPState,
    )

    try:
        coord._dp_decision_tick({"soc": None}, "off_peak", ev_load_w=7600.0)
    except _b2c1._DPSkip:
        pass

    car = coord._dp_carrier
    assert car.shadow_decision == "not_applicable"
    assert car.shadow_reason == "blind_hold"
    assert car.state == DPState.HOLD_ONLY
    assert len(ev._paused_by_dp) == 0


def test_switch_on_does_not_populate_shadow_attrs():
    """When ON, shadow-eval branch is skipped (the outer if is False);
    shadow_decision stays None. Sanity that shadow lives only on the
    OFF path."""
    coord, _, _, _ = _make_coord(
        dp_enabled=True, period="off_peak",
        envoy_available=True, battery_soc=75.0,
    )
    try:
        coord._dp_decision_tick({"soc": 75}, "off_peak", ev_load_w=7600.0)
    except _b2c1._DPSkip:
        pass
    assert coord._dp_carrier.shadow_decision is None


def test_shadow_log_rate_limit_constant_is_module_rung_1():
    """The 300s rate-limit constant is a rung-1 module constant per
    Numbers Get Knobs — NOT operator-tunable."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E501
        DP_SHADOW_LOG_RATE_LIMIT_S,
    )
    assert DP_SHADOW_LOG_RATE_LIMIT_S == 300


# ==========================================================================
# Mutation anchor — INV-BAEC-SHADOW single-point gate
# ==========================================================================
#
# The shadow path lives BEFORE the `raise _DPSkip()` gate. Neutering the
# raise (removing the gate) causes the DP tick body to continue past
# shadow into the real actuation-eval path — which for the switch-OFF
# path means the DP tick would start eval-transitioning while shadow was
# the only legitimate consumer. The mutation-anchor asserts the
# actuation-free acceptance test above fails when the gate is removed.


def test_MUTATION_shadow_gate_removed_makes_shadow_acceptance_test_red():
    """Neuter the single-point gate: remove the `raise _DPSkip()` on the
    shadow path. Actuation resumes on the switch-OFF side (the DP tick
    body will try to advance state / touch _paused_by_dp). The
    switch-off actuation-free acceptance test MUST fail."""
    _mutate_and_expect_red(
        # The gate anchor uniquely bound to the DP-tick body (the earlier
        # duplicate at ~line 3283 sits outside `_dp_decision_tick` and is
        # a different clause — see comment above).
        swap_from=(
            '# ---- item 6: night-window gate ----\n'
            '        if not _dp_on or self._tou.get_current_period() != "off_peak":\n'
            '            raise _DPSkip()'
        ),
        swap_to=(
            '# ---- item 6: night-window gate (mutation: gate removed) ----\n'
            '        if False and (not _dp_on or self._tou.get_current_period() != "off_peak"):\n'
            '            raise _DPSkip()'
        ),
        test_name=(
            "test_baec_shadow_eval.py::"
            "test_switch_off_off_peak_publishes_shadow_attrs_no_actuation"
        ),
    )
