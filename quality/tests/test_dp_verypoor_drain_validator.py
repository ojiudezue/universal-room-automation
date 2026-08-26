"""DP-VERYPOOR-DRAIN-VALIDATOR-1: `set_offpeak_drain` must accept `very_poor`.

Bug: the live-update validator for off-peak drain targets accepted only the
four-quality set {excellent, good, moderate, poor}. The classifier can return
`very_poor`, `_drain_targets` carries a `very_poor` slot, and the DP path is
load-bearing on that slot. Rejecting `very_poor` at the setter meant no
runtime caller could ever update it — a silent no-op.

This test drives the REAL `EnergyCoordinator.set_offpeak_drain` method body
against a minimal fixture that provides `_battery._drain_targets` and a
no-op ladder check, then asserts the `very_poor` write landed.

Mutation drill (manually verified in the build): remove `"very_poor"` from
the `valid` set at `set_offpeak_drain` and this test goes RED (the setter
returns early on the "invalid quality" warning and the dict is unchanged).
"""
from __future__ import annotations

# Piggyback on a sibling test's HA bootstrap (setdefault-based).
from test_arbitrage_completed_chunk_hold_precedence import (  # noqa: F401
    _mock_module,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (  # noqa: E402
    EnergyCoordinator,
)


class _FakeBattery:
    def __init__(self) -> None:
        # Shape mirrors BatteryStrategy._drain_targets (energy_battery.py:465).
        self._drain_targets: dict[str, int] = {
            "excellent": 20,
            "good": 30,
            "moderate": 40,
            "poor": 50,
            "very_poor": 55,
        }
        self._peak_buffer_target = 80
        self.reserve_soc = 20


class _ECFixture:
    """Minimal fixture that satisfies the read surface of `set_offpeak_drain`."""

    def __init__(self) -> None:
        self._battery = _FakeBattery()

    def _check_threshold_ladder(self) -> None:  # no-op; ladder tested elsewhere
        return None


def test_set_offpeak_drain_accepts_very_poor_and_updates_drain_target():
    fx = _ECFixture()

    # Drive the REAL production method body (unbound-method invocation so we
    # exercise the exact code path any live caller would hit).
    EnergyCoordinator.set_offpeak_drain(fx, "very_poor", 17)

    assert fx._battery._drain_targets["very_poor"] == 17, (
        "set_offpeak_drain('very_poor', ...) must land in _drain_targets — "
        "if the validator rejects 'very_poor' the slot stays at its seeded "
        "value and DP has no runtime knob for very-poor forecast nights."
    )


def test_set_offpeak_drain_still_rejects_unknown_quality():
    """Guardrail: widening the set to include very_poor must not accept junk."""
    fx = _ECFixture()
    seeded = dict(fx._battery._drain_targets)

    EnergyCoordinator.set_offpeak_drain(fx, "catastrophic", 99)

    assert fx._battery._drain_targets == seeded, (
        "Unknown quality strings must be rejected without mutating the dict."
    )
