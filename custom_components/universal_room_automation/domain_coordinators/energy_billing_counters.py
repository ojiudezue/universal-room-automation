"""Emporia daily-counter accrual tracker (PLANNING_ec_billing_emporia_counters).

Sole mutator of counter state. CostTracker reads via ``last_net_kw()`` and
delegates kWh accrual to ``tick()``. Two independent legs — import and
export — are tracked, with value-drop-only reset detection, elapsed-scaled
jump cap, TOU-boundary pro-ration, and a stuck-counter detector.

Rules of the road:
- Tracker holds last counter values + last-tick wall-clock + last cached kW.
- A value drop (new < last - RESET_EPSILON_KWH) is treated as a daily reset;
  the delta is reset-to-current (not reset-to-zero) so a mid-day reset at
  k kWh does not credit k kWh of extra accrual.
- The per-tick kWh delta is capped at MAX_COUNTER_KW_PLAUSIBLE * elapsed_h.
  Jumps above the cap are LOGGED and truncated; the leftover is dropped
  (safety over completeness: a 500 kWh single-tick spike is Emporia noise,
  not real energy).
- Pro-ration across TOU-period boundaries is done via
  ``TOURateEngine.get_next_period_change_dt(now)``.
- ``last_net_kw()`` returns the kW inferred at the most recent tick as the
  net = import_kw - export_kw. Returns None if the cached value is older
  than ``DEFAULT_NET_POWER_MAX_AGE_S`` (REV 4 D6 LOW-1).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_const import (
    COUNTER_NET_POWER_MAX_AGE_S,
    COUNTER_STUCK_WINDOW_S,
    MAX_COUNTER_KW_PLAUSIBLE,
    RESET_EPSILON_KWH,
)
from .energy_tou import TOURateEngine

_LOGGER = logging.getLogger(__name__)


class CounterAccrualTracker:
    """Per-leg accrual tracker driven by Emporia daily kWh counters."""

    def __init__(
        self,
        hass: HomeAssistant,
        tou_engine: TOURateEngine,
        import_entity: str | None = None,
        export_entity: str | None = None,
    ) -> None:
        self.hass = hass
        self._tou = tou_engine
        self._import_entity = import_entity
        self._export_entity = export_entity

        # Per-leg state: last observed counter value + wall-clock timestamp
        # when it was observed. _last_tick_time is per-leg so a stale leg
        # does not freeze the other.
        self._import_last: float | None = None
        self._export_last: float | None = None
        self._import_last_ts: float | None = None
        self._export_last_ts: float | None = None

        # Last-tick cached net kW + its stamp (for D6 _get_net_power).
        self._last_net_kw: float | None = None
        self._last_net_kw_ts: float | None = None

        # Stuck detector: track the time a leg last ADVANCED (saw a +delta).
        self._import_last_advance_ts: float | None = None
        self._export_last_advance_ts: float | None = None

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Serialise state for midnight snapshot persistence."""
        return {
            "counter_import_last": self._import_last,
            "counter_export_last": self._export_last,
        }

    def restore(
        self,
        import_last: float | None,
        export_last: float | None,
        snapshot_ts: float | None = None,
    ) -> None:
        """Restore baselines from the midnight snapshot row.

        REV 4 D5 LOW-2 + B-L3: this is called BEFORE the date-mismatch
        early return in ``CostTracker.restore_daily`` so a restart
        spanning midnight does not lose the post-midnight energy.

        B-L3 (REV 4 review fix-up): the caller passes `snapshot_ts` so
        the first tick after restore has a real elapsed window (and
        therefore a real cap) instead of accepting an uncapped delta
        over an unbounded gap. Without the stamp, a restart gap of hours
        collapsed to a single uncapped single-rate book.
        """
        if import_last is not None:
            self._import_last = float(import_last)
            if snapshot_ts is not None and self._import_last_ts is None:
                self._import_last_ts = float(snapshot_ts)
        if export_last is not None:
            self._export_last = float(export_last)
            if snapshot_ts is not None and self._export_last_ts is None:
                self._export_last_ts = float(snapshot_ts)

    # ------------------------------------------------------------------
    # Read-side
    # ------------------------------------------------------------------

    def last_net_kw(self) -> float | None:
        """Last tick's inferred net kW, or None if stale.

        REV 4 D6 LOW-1: returns None once the cache is older than
        ``DEFAULT_NET_POWER_MAX_AGE_S``; otherwise peak-avoidance reads
        a frozen kW for the whole counter-staleness window.
        """
        if self._last_net_kw is None or self._last_net_kw_ts is None:
            return None
        age = time.time() - self._last_net_kw_ts
        # Cadence-aware: Emporia daily counters update ~every 15 min, so a
        # 3-min Envoy-tuned staleness bound would freeze peak-avoidance
        # inputs during normal operation. See COUNTER_NET_POWER_MAX_AGE_S.
        if age > COUNTER_NET_POWER_MAX_AGE_S:
            return None
        return self._last_net_kw

    # ------------------------------------------------------------------
    # Core tick
    # ------------------------------------------------------------------

    def _read_counter(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        try:
            state = self.hass.states.get(entity_id)
        except Exception:  # noqa: BLE001
            return None
        if state is None or state.state in ("unknown", "unavailable", None):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _leg_delta(
        self,
        current: float | None,
        last: float | None,
        window_s: float | None,
        *,
        leg_name: str,
    ) -> float:
        """Return accepted kWh delta for one leg, bounded by `window_s`.

        A-HIGH (2026-10-09 fix-up): the cap window MUST be the ADVANCE
        window — the time since the counter last ADVANCED (or since first
        observation) — NOT the time since the last tick. A 15-min Emporia
        cadence has 2 silent 5-min ticks followed by one advancing tick;
        capping the advance at `MAX_COUNTER_KW_PLAUSIBLE × 5min` truncates
        every real reading. Caller passes `window_s` computed from
        `prior_advance_ts or prior_obs_ts`.

        A-HIGH-1 (REV 4): a value-drop RESET books `current` (bounded)
        rather than 0 — the midnight-reset case.
        """
        if current is None:
            return 0.0
        if last is None:
            # First observation: seed baseline, no accrual.
            return 0.0
        if current < last - RESET_EPSILON_KWH:
            # Daily reset — counter zeroed since last tick; `current` is
            # the new day's accrual-to-now, bounded by advance-window cap.
            _LOGGER.info(
                "Counter reset detected on %s (last=%.3f current=%.3f) — "
                "booking current as post-reset accrual.",
                leg_name, last, current,
            )
            booked = max(0.0, current)
            if window_s is not None and window_s > 0:
                elapsed_h = max(0.0, window_s / 3600.0)
                cap = MAX_COUNTER_KW_PLAUSIBLE * elapsed_h
                if cap > 0 and booked > cap:
                    _LOGGER.warning(
                        "Reset-day accrual on %s capped: raw=%.3f cap=%.3f",
                        leg_name, booked, cap,
                    )
                    booked = cap
            return booked
        raw_delta = max(0.0, current - last)
        if window_s is None or window_s <= 0:
            # No elapsed stamp; accept delta without a cap (first tick after
            # restart with a restored baseline).
            return raw_delta
        elapsed_h = max(0.0, window_s / 3600.0)
        cap = MAX_COUNTER_KW_PLAUSIBLE * elapsed_h
        if raw_delta > cap and cap > 0:
            _LOGGER.warning(
                "Counter jump on %s exceeds cap: raw=%.3f cap=%.3f (window_h=%.3f)",
                leg_name, raw_delta, cap, elapsed_h,
            )
            return cap
        return raw_delta

    def tick(
        self,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Advance both legs; return {'import_kwh','export_kwh','slices'} or None.

        'slices' is a list of (period_name, import_kwh, export_kwh) pro-rated
        across TOU boundaries covered by the elapsed window. If either leg
        has no accepted delta the entry is 0.0 on that side. Returns None
        if neither leg produced a delta AND we had no baseline (nothing to do).
        """
        if now is None:
            now = dt_util.now()
        now_ts = now.timestamp()
        imp = self._read_counter(self._import_entity)
        exp = self._read_counter(self._export_entity)

        # A-HIGH (2026-10-09): per-leg ADVANCE window — the time this
        # tick's delta actually represents. Prefer the last ADVANCE stamp
        # (so a 15-min accrual seen on an advancing tick is scored at
        # 15min / 3 ≈ 4 kW, not the 5-min inter-tick / 12 kW). Fall back
        # to the first-observation stamp when the leg has not yet advanced
        # (restore + first real tick path).
        def _window_s(adv_ts: float | None, obs_ts: float | None) -> float | None:
            base = adv_ts if adv_ts is not None else obs_ts
            if base is None:
                return None
            w = now_ts - base
            return w if w > 0 else None

        imp_window_s = _window_s(
            self._import_last_advance_ts, self._import_last_ts
        )
        exp_window_s = _window_s(
            self._export_last_advance_ts, self._export_last_ts
        )

        # Compute deltas BEFORE updating state so we keep the previous ts.
        imp_delta = self._leg_delta(
            imp, self._import_last, imp_window_s, leg_name="import",
        )
        exp_delta = self._leg_delta(
            exp, self._export_last, exp_window_s, leg_name="export",
        )

        # A-MED-1 + A-HIGH-caveat-1 (2026-10-09): PER-LEG ADVANCE-window
        # pro-ration. The slices represent kWh accrued OVER the advance
        # window (not since the last silent tick). `leg_window_s` is the
        # same honest window used by the cap and the kW derivation.
        def _slice_leg(delta: float, leg_window_s: float | None):
            """Return (slices_for_leg, window_h). Slices are tuples of
            (period, imp_kwh, exp_kwh, slice_start_dt) with only this
            leg's energy populated; the opposite leg's energy is 0.0."""
            if delta <= 0 or leg_window_s is None or leg_window_s <= 0:
                return [], 0.0
            total_s = leg_window_s
            start_ts = now_ts - total_s
            cursor = datetime.fromtimestamp(start_ts, tz=now.tzinfo)
            end = now
            out: list[tuple[str, float, float, datetime]] = []
            while cursor < end:
                try:
                    period = self._tou.get_current_period(cursor)
                except Exception:  # noqa: BLE001
                    period = "unknown"
                try:
                    boundary = self._tou.get_next_period_change_dt(cursor)
                except Exception:  # noqa: BLE001
                    boundary = None
                if boundary is None or boundary >= end:
                    slice_end = end
                else:
                    slice_end = boundary
                frac = max(
                    0.0,
                    (slice_end.timestamp() - cursor.timestamp()) / total_s,
                )
                out.append((period, delta * frac, 0.0, cursor))
                cursor = slice_end
            return out, total_s / 3600.0

        imp_slices_raw, imp_elapsed_h = _slice_leg(imp_delta, imp_window_s)
        exp_slices_raw, exp_elapsed_h = _slice_leg(exp_delta, exp_window_s)
        # Distinct per-leg slices concatenated. CostTracker.accumulate
        # iterates and prices each at the slice start time via the
        # shared TOU engine (by reference).
        slices: list[tuple[str, float, float, datetime]] = []
        for p, imp_kwh, _z, dt_ in imp_slices_raw:
            slices.append((p, imp_kwh, 0.0, dt_))
        for p, exp_kwh_wrong_slot, _z, dt_ in exp_slices_raw:
            # _slice_leg put the leg's energy in the imp field (slot 1);
            # for export slices the real energy belongs in slot 2.
            slices.append((p, 0.0, exp_kwh_wrong_slot, dt_))

        # If the baseline was first-observed on this tick (both legs had
        # last_ts=None entering), produce a single "now" slice so a
        # first-real tick's accrual (reset path) is priced at `now`.
        if not slices and (imp_delta > 0 or exp_delta > 0):
            try:
                period = self._tou.get_current_period(now)
            except Exception:  # noqa: BLE001
                period = "unknown"
            slices.append((period, imp_delta, exp_delta, now))

        # A-HIGH (2026-10-09): detect ADVANCE before mutating per-leg state
        # — needed for the honest kW derivation below.
        imp_real_read = imp is not None
        exp_real_read = exp is not None
        imp_advanced = (
            imp_real_read
            and self._import_last is not None
            and imp > self._import_last + RESET_EPSILON_KWH
        )
        exp_advanced = (
            exp_real_read
            and self._export_last is not None
            and exp > self._export_last + RESET_EPSILON_KWH
        )
        # Also treat a value-drop reset as a producing event for the kW
        # refresh denominator (post-reset delta is bookable energy).
        imp_reset = (
            imp_real_read
            and self._import_last is not None
            and imp < self._import_last - RESET_EPSILON_KWH
        )
        exp_reset = (
            exp_real_read
            and self._export_last is not None
            and exp < self._export_last - RESET_EPSILON_KWH
        )

        # A-HIGH (2026-10-09): refresh _last_net_kw ONLY on an ADVANCE
        # tick (or reset), and derive each leg's kW from ITS OWN advance
        # window — never from the inter-tick elapsed. On a silent tick
        # (delta == 0 on both legs) leave the cache alone; `last_net_kw()`
        # expires it after COUNTER_NET_POWER_MAX_AGE_S honestly.
        if imp_advanced or exp_advanced or imp_reset or exp_reset:
            imp_kw = 0.0
            exp_kw = 0.0
            if (
                (imp_advanced or imp_reset)
                and imp_window_s is not None and imp_window_s > 0
            ):
                imp_kw = imp_delta / (imp_window_s / 3600.0)
            if (
                (exp_advanced or exp_reset)
                and exp_window_s is not None and exp_window_s > 0
            ):
                exp_kw = exp_delta / (exp_window_s / 3600.0)
            self._last_net_kw = imp_kw - exp_kw
            self._last_net_kw_ts = now_ts

        # Update per-leg state. A-HIGH (2026-10-09): `_last_ts` only
        # advances on first observation OR on an advance/reset — a silent
        # tick (counter value unchanged, Emporia between 15-min polls)
        # must NOT rewrite `_last_ts`, or the cap window and the
        # advance-fallback both collapse to the EC-tick interval. This
        # also fixes staleness_s() semantics: "stale" now means
        # "no advance seen in N seconds", not "no tick observed".
        if imp_real_read:
            if imp_advanced or imp_reset:
                self._import_last_advance_ts = now_ts
                self._import_last_ts = now_ts
            elif self._import_last is None:
                self._import_last_ts = now_ts  # first-observation seed
            self._import_last = imp
        if exp_real_read:
            if exp_advanced or exp_reset:
                self._export_last_advance_ts = now_ts
                self._export_last_ts = now_ts
            elif self._export_last is None:
                self._export_last_ts = now_ts
            self._export_last = exp

        if imp_delta == 0.0 and exp_delta == 0.0 and not slices:
            return None
        return {
            "import_kwh": imp_delta,
            "export_kwh": exp_delta,
            "slices": slices,
        }

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def is_stuck(self, now_ts: float | None = None) -> bool:
        """True if BOTH legs have not advanced within COUNTER_STUCK_WINDOW_S."""
        if now_ts is None:
            now_ts = time.time()
        def _stuck(ts: float | None) -> bool:
            return ts is None or (now_ts - ts) > COUNTER_STUCK_WINDOW_S
        return _stuck(self._import_last_advance_ts) and _stuck(
            self._export_last_advance_ts
        )

    def staleness_s(self, now_ts: float | None = None) -> float | None:
        """Age in seconds since the newer of the two legs last ticked."""
        if now_ts is None:
            now_ts = time.time()
        candidates = [t for t in (self._import_last_ts, self._export_last_ts) if t is not None]
        if not candidates:
            return None
        return now_ts - max(candidates)
