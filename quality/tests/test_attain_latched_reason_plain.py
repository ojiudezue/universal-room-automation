"""EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1 (part 1) — attain reason text.

Live 2026-09-28 11:01-12:46 CDT the battery strategy reason read
"projected SOC 129% < target 80%" (and 147%-191%) while attain was latched
and grid-charging. The latched continuation re-projects with the observed
rate, which now includes attain's own grid charge, and never compares the
projection to the target (the latch ends only when SOC reaches the target).
The decision was right; the text stated a comparison that was false.

Invariant: the reason never says "projected X% < target T%" unless X < T.
While latched it says plainly what is happening.
"""
from __future__ import annotations

import re

from test_arbitrage_solar_attainability_ladder import (  # noqa: F401
    _ANCHOR,
    _BSOC,
    _build_strategy,
    _seed_rate,
)

from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E501
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
)

_LT_RE = re.compile(r"projected SOC (\d+)% < target (\d+)%")


def _assert_no_false_less_than(reason: str) -> None:
    m = _LT_RE.search(reason)
    if m is not None:
        assert int(m.group(1)) < int(m.group(2)), (
            f"reason claims projected < target but it is not: {reason!r}"
        )


def _latched_charging(soc_start: float, rate: float, target: int):
    strat, hass = _build_strategy(
        soc=soc_start, peak_buffer_target=target, solcast_today="30",
    )
    strat._attain_reboot_recovered = True
    strat._attain_state = "charging"
    strat._attain_cfg_observed_on = True
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "on")
    next_soc = _seed_rate(strat, _ANCHOR, start_soc=soc_start, rate_pct_per_h=rate)
    hass.set_state(_BSOC, f"{next_soc:.4f}")
    return strat, next_soc


def test_latched_reason_is_plain_and_never_claims_false_comparison():
    """Live shape: latched grid charge, +40 %/h, SOC 72 < target 80."""
    strat, soc = _latched_charging(soc_start=62.0, rate=40.0, target=80)
    assert soc < 80
    result = strat.determine_mode("off_peak", "summer", now=_ANCHOR)
    reason = result.get("reason", "")
    # Sanity: the raw projection really is >= target here (the live defect).
    assert strat._attain_projected_soc is not None
    assert strat._attain_projected_soc >= 80
    _assert_no_false_less_than(reason)
    assert "projected SOC" not in reason, reason
    assert "Charging the battery from the grid to 80% before " in reason, reason
    assert f"(now {soc:.0f}%)" in reason, reason
    # Decision unchanged: still grid-charging toward the target.
    assert result.get("arbitrage_active") is True


def test_decision_builder_never_prints_false_less_than_even_unlatched():
    """Defensive: projected >= target on a non-latched call -> plain text."""
    strat, _ = _build_strategy(soc=72, peak_buffer_target=80)
    decision = strat._get_attainability_decision(
        soc=72.0, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=129.0, rate=39.7, mins=103,
        tou_period="off_peak",
    )
    reason = decision.get("reason", "")
    _assert_no_false_less_than(reason)
    assert "Charging the battery from the grid to 80% before " in reason
    assert "(now 72%)" in reason


def test_entry_reason_keeps_projection_when_comparison_is_true():
    """Entry tick: projection really is below target -> keep the detail."""
    strat, _ = _build_strategy(soc=72, peak_buffer_target=80)
    strat._attain_projection_horizon_min = 103.0
    decision = strat._get_attainability_decision(
        soc=72.0, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=75.0, rate=1.0, mins=103,
        tou_period="off_peak",
    )
    reason = decision.get("reason", "")
    assert "projected SOC 75% < target 80%" in reason, reason



def test_latched_builder_plain_even_when_projection_below_target():
    """latched=True: plain text even if the projection happens to be below
    target — the latch did not re-compare, so do not claim it did."""
    strat, _ = _build_strategy(soc=72, peak_buffer_target=80)
    decision = strat._get_attainability_decision(
        soc=72.0, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=75.0, rate=1.0, mins=103,
        tou_period="off_peak", latched=True,
    )
    reason = decision.get("reason", "")
    assert "projected SOC" not in reason, reason
    assert "Charging the battery from the grid to 80% before " in reason
    assert "(now 72%)" in reason


def test_latched_continuation_passes_latched_true(monkeypatch):
    """Wire-in anchor: the latched CHARGING continuation in determine_mode
    calls the reason builder with latched=True. (A latched tick with the
    projection below target is not reachable in this harness — the rung
    ladder pre-empts — so the call-site kwarg is anchored directly.)"""
    strat, _ = _latched_charging(soc_start=62.0, rate=40.0, target=80)
    seen = []
    real = strat._get_attainability_decision

    def _spy(*args, **kwargs):
        seen.append(kwargs.get("latched", False))
        return real(*args, **kwargs)

    monkeypatch.setattr(strat, "_get_attainability_decision", _spy)
    strat.determine_mode("off_peak", "summer", now=_ANCHOR)
    assert seen == [True], seen


def test_rounded_projection_equal_to_target_uses_plain_text():
    """LOW-3: 79.6 prints as '80%' — must not read '80% < target 80%'."""
    strat, _ = _build_strategy(soc=72, peak_buffer_target=80)
    decision = strat._get_attainability_decision(
        soc=72.0, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=79.6, rate=1.0, mins=103,
        tou_period="off_peak",
    )
    reason = decision.get("reason", "")
    _assert_no_false_less_than(reason)
    assert "80% < target 80%" not in reason, reason
    assert "Charging the battery from the grid to 80% before " in reason


def test_plain_text_keeps_stage_note():
    """LOW-2: the plain wording keeps the mid_peak stage note."""
    strat, _ = _build_strategy(soc=72, peak_buffer_target=80)
    decision = strat._get_attainability_decision(
        soc=72.0, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=129.0, rate=39.7, mins=103,
        tou_period="off_peak", stage_note="mid_peak→peak coverage",
        latched=True,
    )
    reason = decision.get("reason", "")
    assert "Charging the battery from the grid to 80%" in reason, reason
    assert "(mid_peak→peak coverage)" in reason, reason
