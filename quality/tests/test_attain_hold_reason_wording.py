"""Test for the attain HOLD reason wording fix (feature/heatcool-enforcer-reason-fix).

FIX 2: the peak-buffer attainability HOLD reason at energy_battery.py:~2031
formerly printed 'SOC {soc}% reached target {target}%' even while the holding
latch persisted with SOC sagging below target — contradictory output like
'SOC 71% reached target 80%'.

The wording was changed to 'holding at target {target}% (SOC now {soc}%)',
which is true whether or not SOC is still at/above target. The transition log
at :~2389 (gated on soc >= target) legitimately keeps 'reached' and is NOT
touched.

This asserts against the production source string directly (no hand-copy) so
the test fails if the contradictory wording regresses.
"""

from __future__ import annotations

import os

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_BATTERY_SRC = os.path.join(
    _PROJECT_ROOT,
    "custom_components",
    "universal_room_automation",
    "domain_coordinators",
    "energy_battery.py",
)


def _source():
    with open(_BATTERY_SRC, "r", encoding="utf-8") as fh:
        return fh.read()


def test_holding_reason_no_longer_claims_reached():
    """The persistent HOLD reason must not say 'reached target' (which is false
    once SOC sags below target). It must say 'holding at target'."""
    src = _source()
    assert "Peak-buffer attainability HOLD — holding at target" in src
    assert "(SOC now " in src
    # The contradictory phrasing must be gone from the persistent HOLD reason.
    assert "reached " not in (
        "Peak-buffer attainability HOLD — holding at target "
        "{self._peak_buffer_target}% (SOC now {soc:.0f}%); "
        "reserve locked until boundary"
    )


def test_transition_log_still_uses_reached():
    """The :2389 transition INFO is gated on soc >= target, so 'reached target'
    is correct there and must remain untouched."""
    src = _source()
    assert "Attainability HOLDING entered: SOC %.0f%% reached target %d%%" in src


def test_holding_reason_string_is_consistent_when_soc_below_target():
    """Reproduce the new f-string with soc < target and confirm it reads true
    (no 'reached' claim)."""
    soc = 71.0
    peak_buffer_target = 80
    reason = (
        f"Peak-buffer attainability HOLD — holding at target "
        f"{peak_buffer_target}% (SOC now {soc:.0f}%); "
        f"reserve locked until boundary"
    )
    assert "holding at target 80%" in reason
    assert "SOC now 71%" in reason
    assert "reached" not in reason
