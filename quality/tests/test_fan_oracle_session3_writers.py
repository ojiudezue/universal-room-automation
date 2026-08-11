"""FAN-LAYER-1 Session 3 — W11 (safety-stop) + W12 (pre-arrival ON) oracle wraps.

The two NEW consult sites the plan calls out:

  * W11 ``hvac._stop_all_fans_safety`` — per-fan emission wrapped in
    ``oracle.actuate(..., safety=True)``. Under safety=True the oracle
    ALWAYS returns ALLOW and logs the pre-safety verdict at WARNING
    (per PLAN §7.4 + §1 safety carve-out).
  * W12 ``hvac_predict._activate_zone_fans`` — per-fan emission wrapped
    in ``oracle.actuate(..., direction="on")``. DEFERs under a live
    manual-OFF cooldown (per PLAN §7.4 W12 rationale — operator turned
    the fan off recently, cool-down window unexpired).

Rather than fake up the full HVACCoordinator / HVACPredictor fabric
(which pulls in every HA subsystem via imports), these tests exercise
the oracle-side invariants that the production wraps depend on plus a
source-grep check that the wraps ARE present at the two sites. Any
regression that strips the wrap will fail the source-grep test; any
regression that breaks the oracle safety/defer semantics will fail
the oracle-side tests. Both classes of mutation are caught.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

import _provenance_harness  # noqa: F401

from custom_components.universal_room_automation.const import (
    FAN_TRIGGER_HVAC_PREARRIVAL_ON,
    FAN_TRIGGER_SAFETY_STOP,
)
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E501
    FanDecisionSnapshot,
    FanPolicyOracle,
)


ROOM = "Bedroom"
FAN = "fan.bedroom"

_REPO = Path(__file__).resolve().parents[2]
_HVAC_PY = _REPO / "custom_components" / "universal_room_automation" / "domain_coordinators" / "hvac.py"
_HVAC_PREDICT_PY = _REPO / "custom_components" / "universal_room_automation" / "domain_coordinators" / "hvac_predict.py"


# ---------------------------------------------------------------------------
# Oracle-side invariants the two wraps depend on
# ---------------------------------------------------------------------------

def test_safety_true_allows_off_even_when_manual_on_hold_live():
    """W11 invariant: safety=True overrides a live manual-ON hold."""
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 11, 12, 0, 0)
    oracle._get_record(ROOM).manual_on_hold_until = now + timedelta(hours=1)  # noqa: SLF001
    snap = FanDecisionSnapshot(
        now=now, sleep_state="unknown", sleep_axis=None,
        house_state="day", is_hvac_managing=True,
        entities=(FAN,), observed_any_on=True,
    )
    verdict = oracle.may_turn_off(
        ROOM, FAN_TRIGGER_SAFETY_STOP, snap, safety=True,
    )
    assert verdict.is_allow, (
        "safety=True MUST always ALLOW; safety > policy > preference "
        "per PLAN §1 + §7.4 W11"
    )


def test_prearrival_on_defers_under_manual_off_cooldown():
    """W12 invariant: pre-arrival ON DEFERs under a live manual-OFF cooldown."""
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 11, 12, 0, 0)
    oracle._get_record(ROOM).manual_off_cooldown_until = now + timedelta(hours=1)  # noqa: SLF001
    snap = FanDecisionSnapshot(
        now=now, sleep_state="unknown", sleep_axis=None,
        house_state="day", is_hvac_managing=True,
        entities=(FAN,), observed_any_on=False,
    )
    verdict = oracle.may_turn_on(
        ROOM, FAN_TRIGGER_HVAC_PREARRIVAL_ON, snap,
    )
    assert verdict.is_defer and verdict.reason == "manual_off_cooldown"


def test_prearrival_on_allows_when_cooldown_expired():
    """W12 symmetric: no live cooldown → ALLOW."""
    oracle = FanPolicyOracle()
    now = datetime(2026, 8, 11, 12, 0, 0)
    oracle._get_record(ROOM).manual_off_cooldown_until = now - timedelta(hours=1)  # noqa: SLF001
    snap = FanDecisionSnapshot(
        now=now, sleep_state="unknown", sleep_axis=None,
        house_state="day", is_hvac_managing=True,
        entities=(FAN,), observed_any_on=False,
    )
    verdict = oracle.may_turn_on(
        ROOM, FAN_TRIGGER_HVAC_PREARRIVAL_ON, snap,
    )
    assert verdict.is_allow


# ---------------------------------------------------------------------------
# Source-presence checks — the wraps ARE in the production paths
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# C-LOW-1 fix-up (2026-08-11): the two source-presence tests
# (test_safety_stop_source_wraps_in_oracle_actuate,
#  test_prearrival_on_source_wraps_in_oracle_actuate) have been DELETED.
# They're superseded by the behavioral tests in
# quality/tests/test_fan_oracle_w11_w12_behavioral.py which drive the
# real _stop_all_fans_safety / _activate_zone_fans code paths through
# a services.async_call recorder + a seeded oracle ledger. Behavioral
# tests catch a strictly larger set of regressions than source-grep
# (they close C-HIGH-1 / C-HIGH-2, and the same drills that used to
# anchor here — MUT3-1..MUT3-5, MUT-STOP — anchor the behavioral tests
# instead).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Adjacency audit — must be clean (M1 acceptance)
# ---------------------------------------------------------------------------

def test_fan_adjacency_audit_clean_after_session_3():
    """PLAN §9-C M1 acceptance: audit returns zero adjacency violations."""
    import sys
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from quality.tools.audit_fan_adjacency import run_audit
    findings = run_audit()
    assert findings == [], "\n  ".join(str(f) for f in findings)
