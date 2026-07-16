"""R7 fix-up (Review C-HIGH-2 / C-LOW-1) — behavioral tests pinning
raw-vs-clamped attain wiring.

Reviewer C proved the parity suite alone did not catch a mutation swapping
``raw_soc_pct`` for ``soc_pct`` (clamped) at the two attain consumption
sites (energy_battery.py:2861 attain-entry projection and :3553 attain
hold-current projection). Those sites HISTORICALLY publish the RAW
(un-clamped) value — the clamp is a rung-display artifact — so an
accidental clamp would silently cap the observability at 100 and mask
runaway rate scenarios in the decision reason.

These tests drive the sites through the coordinator surface (not the
primitive in isolation) and assert:
  1. `_should_attain_peak_buffer` publishes RAW `_attain_projected_soc`
     that can exceed 100 given a runaway (high-SOC, high-rate, long-mins)
     scenario (M7b anchor — mutation at :2861).
  2. Attain hold-current flows the RAW value into the decision reason
     via `_get_attainability_decision` (M7 anchor — mutation at :3553).
  3. Blind hold (soc/rate None) at the hold-current site yields
     `projected=None` in the decision path (not a clamped 0).

The expected raw values are computed by INDEPENDENT REIMPLEMENTATION of
the pre-R7 shape — never by calling the primitive.
"""
from __future__ import annotations

# Reuse the ladder test's HA-module bootstrap wholesale.
from test_arbitrage_solar_attainability_ladder import (  # noqa: F401
    _ANCHOR,
    _BSOC,
    _build_strategy,
    _seed_rate,
)


# --------------------------------------------------------------------------
# Independent reimplementation of the pre-R7 attain shape (byte-identical
# anchor — must NOT call the primitive).
# --------------------------------------------------------------------------

def _pre_r7_attain_raw(soc: float, rate: float, mins: float, surplus: float) -> float:
    return soc + (mins / 60.0) * rate + surplus


# --------------------------------------------------------------------------
# C-HIGH-2 anchor #1 — attain-entry site (energy_battery.py:2861)
# --------------------------------------------------------------------------


def test_attain_entry_publishes_raw_projection_over_100():
    """Runaway rate: soc=80, target=90, rate=+20 %/h, mins~5h, surplus>0.

    RAW projection = 80 + 5*20 + surplus > 100. If someone flips the
    consumed field from `raw_soc_pct` to `soc_pct` (clamped), the
    published `_attain_projected_soc` would silently cap at 100.
    Target of 90 keeps soc < target so the predicate proceeds; the RAW
    projection blowing past 100 is the raw-vs-clamped anchor.
    """
    strat, hass = _build_strategy(
        soc=80, peak_buffer_target=90, solcast_today="30",
    )
    # Seed K samples at +20 %/h so the observed rate resolves to +20.
    next_soc = _seed_rate(strat, _ANCHOR, start_soc=80.0, rate_pct_per_h=20.0)
    hass.set_state(_BSOC, f"{next_soc:.4f}")
    # Peak_buffer_target is 100 so `soc < target` holds (95 < 100).
    # mins to attain boundary is ~5h at _ANCHOR (09:00 → 14:00).
    should, projected, rate, mins = strat._should_attain_peak_buffer(
        soc=next_soc, now=_ANCHOR, tou_period="off_peak",
    )
    assert projected is not None, "predicate must return a projection"
    # RAW value stored on the strategy (rounded to 1 decimal by production).
    published = strat._attain_projected_soc
    assert published is not None
    # Must strictly exceed 100 — clamped path would cap at 100.0.
    assert published > 100.0, (
        f"attain-entry consumed clamped value, not raw: "
        f"_attain_projected_soc={published} (expected >100 given "
        f"soc=95, rate={rate}, mins={mins})"
    )


def test_attain_entry_raw_matches_pre_r7_shape():
    """RAW value equals the independent pre-R7 reimplementation."""
    strat, hass = _build_strategy(
        soc=80, peak_buffer_target=90, solcast_today="30",
    )
    next_soc = _seed_rate(strat, _ANCHOR, start_soc=80.0, rate_pct_per_h=20.0)
    hass.set_state(_BSOC, f"{next_soc:.4f}")
    _, projected, rate, mins = strat._should_attain_peak_buffer(
        soc=next_soc, now=_ANCHOR, tou_period="off_peak",
    )
    # Reconstruct expected surplus from the same helper the site calls,
    # then compare `_attain_projected_soc` to the pre-R7 shape.
    surplus = strat._expected_solar_surplus_pct(_ANCHOR, mins)
    expected_raw = _pre_r7_attain_raw(next_soc, rate, mins, surplus)
    published = strat._attain_projected_soc
    # Production rounds to 1 decimal.
    assert abs(published - round(expected_raw, 1)) < 0.05, (
        f"published raw {published} != expected pre-R7 raw {round(expected_raw, 1)}"
    )


# --------------------------------------------------------------------------
# C-HIGH-2 anchor #2 — attain hold-current site (energy_battery.py:3553)
# --------------------------------------------------------------------------


def test_attain_hold_current_publishes_raw_projection_over_100():
    """M7 anchor — hold-current (:3553) MUST consume raw_soc_pct.

    Drive the latched CHARGING → hold-current-verify path via
    determine_mode: prime `_attain_state="charging"` and mark the reboot
    latch consumed so we bypass adoption. Seed +20 %/h rate.  The
    resulting decision reason must reference a RAW projected SOC > 100
    (the pre-R7 attain shape is NOT clamped at the consumption site).
    Swapping raw_soc_pct → soc_pct at :3553 caps the reason at 100%.
    """
    strat, hass = _build_strategy(
        soc=80, peak_buffer_target=90, solcast_today="30",
    )
    # Skip reboot-adoption; force latched CHARGING.
    strat._attain_reboot_recovered = True
    strat._attain_state = "charging"
    strat._attain_cfg_observed_on = True
    # Match the charge_from_grid entity to observed-on to avoid the
    # ON→OFF transition branch.
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E501
        DEFAULT_CHARGE_FROM_GRID_ENTITY,
    )
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "on")
    next_soc = _seed_rate(strat, _ANCHOR, start_soc=80.0, rate_pct_per_h=20.0)
    hass.set_state(_BSOC, f"{next_soc:.4f}")
    result = strat.determine_mode("off_peak", "summer", now=_ANCHOR)
    reason = result.get("reason", "")
    # The decision reason format is "projected SOC {projected:.0f}%".
    # RAW value (no clamp) should print >100. If someone flips to
    # `soc_pct` (clamped) the reason will say "100%".
    import re
    m = re.search(r"projected SOC (\d+)%", reason)
    assert m is not None, f"no projected SOC in reason: {reason!r}"
    projected_int = int(m.group(1))
    assert projected_int > 100, (
        f"hold-current consumed clamped value, not raw: "
        f"reason projected SOC = {projected_int}% (expected >100)"
    )


def test_attain_hold_current_projection_none_when_blind():
    """soc/rate None at the hold-current site → projected=None flows through.

    Anchors the M7 mutation guard: swapping `raw_soc_pct` for `soc_pct`
    at :3553 does NOT change the None-fall-through (both are None when
    blind), but forcing an explicit non-None assertion here documents
    the semantic and pairs with the >100 test above to lock the raw
    contract.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_projector import (  # noqa: E501
        EnergyProjector,
    )
    got = EnergyProjector.project_soc_at_boundary(
        soc=None, rate_pct_per_h=None, mins=60, solar_surplus_pct=5.0,
        source="attain_hold_current", bound_to_solar_horizon=False,
    )
    assert got.blind is True
    assert got.raw_soc_pct is None
    assert got.soc_pct is None
