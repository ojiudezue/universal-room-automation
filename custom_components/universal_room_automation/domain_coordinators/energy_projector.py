"""EnergyProjector — R7 unified SOC-at-boundary projection primitive.

Filed 2026-07-16 per docs/planning/PLANNING_net_energy_program_R1_R7_R2.md
(R7 — Projection unification). The goal is I-NE3: every consumer that
answers "battery SOC at boundary T given current SOC, observed rate, and
expected solar surplus" MUST call the SAME primitive so ladder / attain /
observability cannot diverge (Bug Class #53 at projection scale — the
2026-07-15 11:20 ladder-vs-attain divergence is the live evidence).

The primitive is a **byte-identical refactor** on the no-op path. On any
existing legal-config input it MUST return exactly the value each pre-R7
call site returned. This is enforced by:
  1. Parity tests (`test_energy_projector_parity.py`) that compute both
     the old inline expression and the primitive output across a grid of
     inputs and assert equality.
  2. A grep-singleton CI test (`test_energy_projector_grep_singleton.py`)
     that scans `energy_battery.py` for the banned inline projection
     pattern; any hit outside `energy_projector.py` fails the suite.

Preserved v5.17.4 semantics (I-AH1):
  - Additive surplus shape: `soc + rate_effective * hours + solar_surplus`.
  - Solar-horizon rate bound (rung-only): `effective_rate_mins = min(mins,
    solar_mins_remaining)` where solar_mins_remaining is (sunset - now)
    clamped ≥ 0. Attain sites do NOT bound — they extrapolate over the
    full `mins` horizon (they run in a TOU-boundary context, not a
    solar-attain context).
  - Display clamp: `max(0.0, min(100.0, raw_projected))`.

Blind-hold (I-BH1/2, I-D3): if `soc` or `rate` is None the primitive
returns `ProjectionResult(soc_pct=None, blind=True, ...)`. Callers must
handle `None` fail-closed — they already do this at their existing
guards (soc is None / rate is None short-circuits before reaching the
projection line), so the primitive's `None` return is a belt-and-braces
mirror, not a new gate.

Numbers Get Knobs: the kill-switch constant `R7_USE_UNIFIED_PROJECTOR`
lives in `energy_const.py` at the module-constant rung (code-review-only
governance — not operator-tunable).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final


@dataclass(frozen=True)
class ProjectionResult:
    """Frozen record of one SOC-at-boundary projection.

    Attributes:
        soc_pct: Clamped [0, 100] projected SOC at the boundary, or None
            under blind-hold (soc/rate unavailable).
        raw_soc_pct: Pre-clamp value (useful for observability + parity
            tests). None when blind.
        source: Diagnostic tag identifying which call site produced this
            (e.g. 'rung0', 'rung1_counterfactual', 'attain_entry',
            'attain_hold_current').
        horizon_min: Minutes used for the rate term. For rung sites this
            is solar-bounded; for attain sites this is the raw `mins` to
            boundary.
        rate_pct_per_h: The rate term used (post any `extra_rate_pct`
            adjustment).
        surplus_pct: The expected solar surplus term added.
        blind: True iff soc or rate was None at entry (fail-closed sentinel).
    """

    soc_pct: float | None
    raw_soc_pct: float | None
    source: str
    horizon_min: float
    rate_pct_per_h: float | None
    surplus_pct: float
    blind: bool


# Solar-surplus threshold below which surplus is treated as "collapsed"
# for observability (mirrors ARB_LADDER_SOLAR_NEGLIGIBLE_PCT_PER_H's role
# at call sites; NOT applied inside the primitive — call sites still own
# their own no-solar guards. Documented here for readers).
_SOLAR_NEGLIGIBLE_DOC: Final[float] = 0.5


class EnergyProjector:
    """Owner of the one true SOC-at-boundary projection expression.

    Instance-free by design: `project_soc_at_boundary` is a pure
    function. Wrapped in a class only so the primitive has a stable
    grep-anchor name for the singleton CI test.
    """

    @staticmethod
    def project_soc_at_boundary(
        *,
        soc: float | None,
        rate_pct_per_h: float | None,
        mins: float | None,
        solar_surplus_pct: float,
        source: str,
        bound_to_solar_horizon: bool,
        now: datetime | None = None,
        sunset_dt: datetime | None = None,
        extra_rate_pct_per_h: float = 0.0,
    ) -> ProjectionResult:
        """Project SOC at boundary T using the additive-surplus shape.

        Expression (byte-identical to v5.17.4 inline sites):

            effective_rate = rate + extra_rate_pct_per_h
            if bound_to_solar_horizon:
                solar_mins = max(0, (sunset_dt - now).total_seconds() / 60)
                rate_mins = min(mins, solar_mins)
            else:
                rate_mins = mins
            raw = soc + effective_rate * (rate_mins / 60) + solar_surplus
            clamped = max(0, min(100, raw))

        Blind-hold: soc is None OR rate is None → returns blind=True.

        Args:
            soc: Current SOC in %. None → blind fail-closed.
            rate_pct_per_h: Observed net charge rate in %/h. None → blind.
            mins: Minutes to boundary (T - now). None or ≤0 → zero-horizon
                result (raw = soc + surplus).
            solar_surplus_pct: Pre-computed expected solar surplus %SOC
                over the caller's solar window. Owned by call site.
            source: Diagnostic string for the ProjectionResult.
            bound_to_solar_horizon: True for rung sites (v5.17.4 bound);
                False for attain sites (extrapolate full boundary horizon).
            now / sunset_dt: Required iff bound_to_solar_horizon is True.
                If either is None the bound collapses to 0 (matches the
                rung site's `except Exception: sunset_today = None` path).
            extra_rate_pct_per_h: Additive adjustment to the rate term.
                Used by rung-1 counterfactual (`-assumed_ev_pct`) and
                rung-1 entry (`+ev_load_pct_per_h`). Zero elsewhere.

        Returns:
            ProjectionResult. When blind, soc_pct/raw_soc_pct are None
            and blind=True; callers MUST handle this fail-closed.
        """
        if soc is None or rate_pct_per_h is None:
            return ProjectionResult(
                soc_pct=None,
                raw_soc_pct=None,
                source=source,
                horizon_min=0.0,
                rate_pct_per_h=rate_pct_per_h,
                surplus_pct=solar_surplus_pct,
                blind=True,
            )

        effective_rate = float(rate_pct_per_h) + float(extra_rate_pct_per_h)

        if mins is None:
            rate_mins = 0.0
        elif bound_to_solar_horizon:
            if sunset_dt is not None and now is not None and sunset_dt > now:
                solar_mins_remaining = max(
                    0.0, (sunset_dt - now).total_seconds() / 60.0,
                )
            else:
                solar_mins_remaining = 0.0
            rate_mins = min(float(mins), solar_mins_remaining)
        else:
            rate_mins = float(mins)

        rate_hours = rate_mins / 60.0
        raw = float(soc) + effective_rate * rate_hours + float(solar_surplus_pct)
        clamped = max(0.0, min(100.0, raw))

        return ProjectionResult(
            soc_pct=clamped,
            raw_soc_pct=raw,
            source=source,
            horizon_min=rate_mins,
            rate_pct_per_h=effective_rate,
            surplus_pct=float(solar_surplus_pct),
            blind=False,
        )
