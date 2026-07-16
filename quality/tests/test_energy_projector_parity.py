"""R7 — EnergyProjector byte-identical parity vs pre-R7 inline expressions.

Filed 2026-07-16 per PLANNING_net_energy_program_R1_R7_R2.md R7 §Scope#3
("byte-identical no-op path"). Each pre-R7 call site had one specific
inline projection expression; the primitive MUST reproduce each one
exactly across a grid of inputs.

**Test-authority discipline (R1 Review-C-1 lesson):** the "expected"
values are computed by INDEPENDENT REIMPLEMENTATION of the pre-R7
arithmetic INSIDE THIS TEST FILE — not by calling the primitive itself.
That reimplementation is the anchor; a bug in the primitive cannot hide
behind a self-referential expected value.

**Sites covered:**
  - rung0 (solar-bounded, extra_rate=0)
  - rung1_counterfactual (solar-bounded, extra_rate=-assumed_ev_pct)
  - rung1_entry (solar-bounded, extra_rate=+ev_load_pct_per_h)
  - attain_entry (NOT solar-bounded, extra_rate=0, RAW value consumed)
  - attain_hold_current (NOT solar-bounded, extra_rate=0, RAW value consumed)

Under the kill-switch fallback (R7_USE_UNIFIED_PROJECTOR=False) the
sites use the inline path; under TRUE they use the primitive. The
per-site tests in the existing ladder / attain suites already lock the
call-site behavior — this file locks the primitive's arithmetic in
isolation.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The projector module is PURE (no HA imports), but the parent package's
# __init__.py imports Home Assistant. Load the module file directly to
# sidestep the package init.
_ROOT = Path(__file__).resolve().parents[2]
_PROJECTOR_PATH = (
    _ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "energy_projector.py"
)
_spec = importlib.util.spec_from_file_location(
    "_ura_energy_projector_under_test", _PROJECTOR_PATH,
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_ura_energy_projector_under_test"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
EnergyProjector = _mod.EnergyProjector
ProjectionResult = _mod.ProjectionResult


_NOW = datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Independent reimplementations of the five pre-R7 inline expressions.
# These are copied VERBATIM from the pre-R7 source (see energy_battery.py
# git tag pre-review-vX.Y.Z-R7 lines 1762, 1789, 1859, 2767, 3441). Do NOT
# rewrite them to look like the primitive — they are the byte-identical
# anchor.
# --------------------------------------------------------------------------

def _inline_rung0(soc, rate, mins, solar_surplus, now, sunset):
    """Reimplements energy_battery.py:1747-1764 (pre-R7)."""
    if sunset is not None and sunset > now:
        solar_mins_remaining = max(0.0, (sunset - now).total_seconds() / 60.0)
    else:
        solar_mins_remaining = 0.0
    effective_rate_mins = min(float(mins), solar_mins_remaining)
    rate_hours = effective_rate_mins / 60.0
    raw = soc + rate * rate_hours + solar_surplus
    clamped = max(0.0, min(100.0, raw))
    return raw, clamped


def _inline_rung1_cf(soc, rate, mins, solar_surplus, now, sunset, assumed_ev_pct):
    """Reimplements energy_battery.py:1789 (pre-R7)."""
    if sunset is not None and sunset > now:
        solar_mins_remaining = max(0.0, (sunset - now).total_seconds() / 60.0)
    else:
        solar_mins_remaining = 0.0
    effective_rate_mins = min(float(mins), solar_mins_remaining)
    rate_hours = effective_rate_mins / 60.0
    raw = soc + (rate - assumed_ev_pct) * rate_hours + solar_surplus
    clamped = max(0.0, min(100.0, raw))
    return raw, clamped


def _inline_rung1_entry(soc, rate, mins, solar_surplus, now, sunset, ev_load_pct):
    """Reimplements energy_battery.py:1859 (pre-R7)."""
    if sunset is not None and sunset > now:
        solar_mins_remaining = max(0.0, (sunset - now).total_seconds() / 60.0)
    else:
        solar_mins_remaining = 0.0
    effective_rate_mins = min(float(mins), solar_mins_remaining)
    rate_hours = effective_rate_mins / 60.0
    raw = soc + (rate + ev_load_pct) * rate_hours + solar_surplus
    clamped = max(0.0, min(100.0, raw))
    return raw, clamped


def _inline_attain_entry(soc, rate, mins, solar_surplus):
    """Reimplements energy_battery.py:2767 (pre-R7). No solar-bound, no clamp."""
    return soc + (mins / 60.0) * rate + solar_surplus


def _inline_attain_hold_current(soc, rate, mins, solar_surplus):
    """Reimplements energy_battery.py:3441-3444 (pre-R7). No bound, no clamp."""
    if soc is None or rate is None:
        return None
    return soc + (mins / 60.0) * rate + solar_surplus


# --------------------------------------------------------------------------
# Grid of legal-config inputs. Chosen to exercise:
#   - typical daytime charging (soc mid-band, positive rate, sunset ahead)
#   - clamp-high (raw > 100)
#   - clamp-low (raw < 0, deep discharge)
#   - solar bound BINDS (mins > solar_mins_remaining, e.g., overnight)
#   - solar bound does NOT bind (mins < solar_mins_remaining, midday)
#   - sunset already past (bound collapses to 0)
# --------------------------------------------------------------------------

_GRID = [
    # (soc, rate_pct_h, mins, surplus, sunset_offset_min)
    (50.0, 10.0, 60,  5.0,  180),   # midday, bound does not bind
    (50.0, 10.0, 600, 5.0,  180),   # overnight-like, bound BINDS
    (95.0, 20.0, 60,  10.0, 180),   # clamp high
    (5.0,  -30.0, 60, 0.0,  180),   # clamp low
    (50.0, 15.0, 120, 3.0,  0),     # sunset now → solar_mins = 0 → rate_hours=0
    (50.0, 15.0, 120, 3.0,  -60),   # sunset past → bound collapses to 0
    (50.0, 0.0, 120, 8.0,   180),   # zero rate, only surplus contributes
    (73.4, 5.7, 47,  1.3,   200),   # non-round numbers
]


def test_rung0_parity_matches_inline():
    """Primitive rung0 output equals pre-R7 inline arithmetic on the grid."""
    for soc, rate, mins, surplus, sunset_off in _GRID:
        sunset = _NOW + timedelta(minutes=sunset_off)
        exp_raw, exp_clamped = _inline_rung0(soc, rate, mins, surplus, _NOW, sunset)
        got: ProjectionResult = EnergyProjector.project_soc_at_boundary(
            soc=soc, rate_pct_per_h=rate, mins=mins,
            solar_surplus_pct=surplus, source="rung0",
            bound_to_solar_horizon=True, now=_NOW, sunset_dt=sunset,
            extra_rate_pct_per_h=0.0,
        )
        assert got.raw_soc_pct == exp_raw, (
            f"rung0 raw mismatch soc={soc} rate={rate} mins={mins}: "
            f"got={got.raw_soc_pct} exp={exp_raw}"
        )
        assert got.soc_pct == exp_clamped, (
            f"rung0 clamp mismatch: got={got.soc_pct} exp={exp_clamped}"
        )
        assert got.blind is False


def test_rung1_counterfactual_parity():
    """Rung-1 counterfactual: extra_rate = -assumed_ev_pct."""
    assumed_ev_pct_vals = [0.0, 5.0, 35.0, 100.0]
    for soc, rate, mins, surplus, sunset_off in _GRID:
        sunset = _NOW + timedelta(minutes=sunset_off)
        for assumed in assumed_ev_pct_vals:
            exp_raw, exp_clamped = _inline_rung1_cf(
                soc, rate, mins, surplus, _NOW, sunset, assumed,
            )
            got = EnergyProjector.project_soc_at_boundary(
                soc=soc, rate_pct_per_h=rate, mins=mins,
                solar_surplus_pct=surplus, source="rung1_counterfactual",
                bound_to_solar_horizon=True, now=_NOW, sunset_dt=sunset,
                extra_rate_pct_per_h=-assumed,
            )
            assert got.raw_soc_pct == exp_raw, (
                f"cf raw mismatch (assumed={assumed}): {got.raw_soc_pct} vs {exp_raw}"
            )
            assert got.soc_pct == exp_clamped


def test_rung1_entry_parity():
    """Rung-1 ENTRY: extra_rate = +ev_load_pct_per_h."""
    ev_load_vals = [1.0, 5.0, 35.0]
    for soc, rate, mins, surplus, sunset_off in _GRID:
        sunset = _NOW + timedelta(minutes=sunset_off)
        for ev in ev_load_vals:
            exp_raw, exp_clamped = _inline_rung1_entry(
                soc, rate, mins, surplus, _NOW, sunset, ev,
            )
            got = EnergyProjector.project_soc_at_boundary(
                soc=soc, rate_pct_per_h=rate, mins=mins,
                solar_surplus_pct=surplus, source="rung1_entry",
                bound_to_solar_horizon=True, now=_NOW, sunset_dt=sunset,
                extra_rate_pct_per_h=ev,
            )
            assert got.raw_soc_pct == exp_raw
            assert got.soc_pct == exp_clamped


def test_attain_entry_parity_not_solar_bounded_no_clamp():
    """Attain entry: full-mins horizon, RAW value consumed by caller."""
    for soc, rate, mins, surplus, _sunset_off in _GRID:
        exp = _inline_attain_entry(soc, rate, mins, surplus)
        got = EnergyProjector.project_soc_at_boundary(
            soc=soc, rate_pct_per_h=rate, mins=mins,
            solar_surplus_pct=surplus, source="attain_entry",
            bound_to_solar_horizon=False,
        )
        # Caller consumes raw_soc_pct (not clamped) — see energy_battery.py:2767
        # pre-R7. Primitive still exposes clamped for observability parity.
        assert got.raw_soc_pct == exp, (
            f"attain_entry raw mismatch: {got.raw_soc_pct} vs {exp}"
        )
        # horizon must equal full mins (no bound applied)
        assert got.horizon_min == float(mins)


def test_attain_hold_current_parity():
    """Attain hold-current: same shape as attain_entry."""
    for soc, rate, mins, surplus, _sunset_off in _GRID:
        exp = _inline_attain_hold_current(soc, rate, mins, surplus)
        got = EnergyProjector.project_soc_at_boundary(
            soc=soc, rate_pct_per_h=rate, mins=mins,
            solar_surplus_pct=surplus, source="attain_hold_current",
            bound_to_solar_horizon=False,
        )
        assert got.raw_soc_pct == exp


def test_blind_hold_soc_none_returns_none():
    """I-BH1/2: soc=None → blind=True, soc_pct=None."""
    got = EnergyProjector.project_soc_at_boundary(
        soc=None, rate_pct_per_h=10.0, mins=60,
        solar_surplus_pct=5.0, source="rung0",
        bound_to_solar_horizon=True, now=_NOW,
        sunset_dt=_NOW + timedelta(hours=3),
    )
    assert got.blind is True
    assert got.soc_pct is None
    assert got.raw_soc_pct is None


def test_blind_hold_rate_none_returns_none():
    """I-BH1/2: rate=None → blind=True, soc_pct=None."""
    got = EnergyProjector.project_soc_at_boundary(
        soc=50.0, rate_pct_per_h=None, mins=60,
        solar_surplus_pct=5.0, source="attain_entry",
        bound_to_solar_horizon=False,
    )
    assert got.blind is True
    assert got.soc_pct is None


def test_solar_bound_missing_now_sunset_collapses_to_zero():
    """Rung path with sunset=None → solar_mins_remaining = 0 → rate_hours=0."""
    got = EnergyProjector.project_soc_at_boundary(
        soc=50.0, rate_pct_per_h=20.0, mins=120,
        solar_surplus_pct=3.0, source="rung0",
        bound_to_solar_horizon=True, now=_NOW, sunset_dt=None,
    )
    # rate term collapses; only soc + surplus contributes
    assert got.raw_soc_pct == 50.0 + 3.0
    assert got.horizon_min == 0.0


def test_source_field_propagates():
    """ProjectionResult.source echoes the caller's tag (observability)."""
    for tag in ("rung0", "rung1_counterfactual", "rung1_entry",
                "attain_entry", "attain_hold_current"):
        got = EnergyProjector.project_soc_at_boundary(
            soc=50.0, rate_pct_per_h=10.0, mins=60,
            solar_surplus_pct=5.0, source=tag,
            bound_to_solar_horizon=False,
        )
        assert got.source == tag
