"""R7.1 rider — attain_reason projection MIRRORS the decision.

I-NE3 mirrors-decision: `attain_reason` MUST carry
`projected_soc_at_boundary` and `horizon_min` derived from the SAME
`ProjectionResult` the decision consumed. If the reason string ever
prints a value not sourced from the same primitive call, the sensor
can display stale text (the "153% < 80%" class from the 07-15 event).

Two behavioural anchors, executed against the coordinator surface:

  1. `test_attain_entry_reason_horizon_matches_stored_mirror` — after
     `_should_attain_peak_buffer` fires, `_get_attainability_decision`
     builds a reason string that includes a "projection horizon N min"
     token whose N equals `self._attain_projection_horizon_min` (the
     mirror written from the ProjectionResult).

  2. `test_attain_entry_reason_horizon_reflects_primitive_source` — if
     the mirror field is overwritten before the decision call, the
     reason string reflects the OVERWRITE (proving the reason reads the
     mirror, not `mins`). Locks the source of the reason to the
     stored primitive-mirror field.

Discipline: no expected value is computed by calling
`_get_attainability_decision` on the unit under test. The invariant is
"reason token = mirror value" — asserted via string search.

Also anchors the A-LOW-1 primitive change: `mins=None` now blind-returns.
"""
from __future__ import annotations

import re

from test_arbitrage_solar_attainability_ladder import (  # noqa: F401
    _ANCHOR,
    _BSOC,
    _build_strategy,
    _seed_rate,
)


_HORIZON_RE = re.compile(r"projection horizon (\d+) min")


def test_attain_entry_reason_horizon_matches_stored_mirror():
    """The reason string's horizon token equals the stored mirror field."""
    strat, hass = _build_strategy(
        soc=80, peak_buffer_target=90, solcast_today="30",
    )
    next_soc = _seed_rate(strat, _ANCHOR, start_soc=80.0, rate_pct_per_h=10.0)
    hass.set_state(_BSOC, f"{next_soc:.4f}")
    _, projected, rate, mins = strat._should_attain_peak_buffer(
        soc=next_soc, now=_ANCHOR, tou_period="off_peak",
    )
    assert projected is not None, "predicate must return a projection"
    mirror = strat._attain_projection_horizon_min
    assert mirror is not None, (
        "R7.1: entry site must store _attain_projection_horizon_min "
        "from the primitive result"
    )
    # Now drive the decision builder and inspect the reason string.
    decision = strat._get_attainability_decision(
        soc=next_soc, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=projected, rate=rate, mins=mins,
        tou_period="off_peak",
    )
    reason = decision.get("reason", "")
    m = _HORIZON_RE.search(reason)
    assert m is not None, (
        f"R7.1: reason must carry 'projection horizon N min' — got {reason!r}"
    )
    assert int(m.group(1)) == int(round(mirror)), (
        f"R7.1 I-NE3: reason horizon {m.group(1)} != mirror {mirror}"
    )


def test_attain_entry_reason_horizon_reflects_primitive_source():
    """Overwrite the mirror; reason must reflect the overwrite, not `mins`.

    This proves the reason string is sourced from the stored primitive
    mirror, not re-derived from `mins`. If someone accidentally rewired
    the reason to read `mins` directly, this test fails.
    """
    strat, hass = _build_strategy(
        soc=80, peak_buffer_target=90, solcast_today="30",
    )
    next_soc = _seed_rate(strat, _ANCHOR, start_soc=80.0, rate_pct_per_h=10.0)
    hass.set_state(_BSOC, f"{next_soc:.4f}")
    _, projected, rate, mins = strat._should_attain_peak_buffer(
        soc=next_soc, now=_ANCHOR, tou_period="off_peak",
    )
    # Deliberately overwrite the mirror to a SENTINEL that could not have
    # come from `mins`.
    sentinel = 4242.0
    strat._attain_projection_horizon_min = sentinel
    decision = strat._get_attainability_decision(
        soc=next_soc, now=_ANCHOR,
        target_day_class="normal", tomorrow_class="normal",
        current_mode=None, season="summer",
        projected=projected, rate=rate, mins=mins,
        tou_period="off_peak",
    )
    reason = decision.get("reason", "")
    m = _HORIZON_RE.search(reason)
    assert m is not None, f"no horizon token in reason: {reason!r}"
    assert int(m.group(1)) == int(sentinel), (
        f"R7.1: reason horizon must mirror the stored primitive field "
        f"(sentinel {sentinel}); got {m.group(1)} — reason is reading "
        f"`mins` instead of the mirror"
    )


def test_projector_mins_none_is_blind_fail_closed():
    """A-LOW-1: primitive with mins=None returns blind, not zero-horizon.

    Pre-R7 sites raised TypeError on None arithmetic; the initial R7
    primitive silently returned zero-horizon (lost fail-loud signal).
    R7.1 restores fail-closed semantics.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy_projector import (  # noqa: E501
        EnergyProjector,
    )
    got = EnergyProjector.project_soc_at_boundary(
        soc=50.0, rate_pct_per_h=5.0, mins=None,
        solar_surplus_pct=1.0, source="test",
        bound_to_solar_horizon=False,
    )
    assert got.blind is True
    assert got.soc_pct is None
    assert got.raw_soc_pct is None
