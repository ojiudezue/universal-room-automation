"""Billing and cost tracking for Energy Coordinator.

Sub-Cycle E4: Real-time cost awareness, bill cycle tracking, bill prediction.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_const import (
    DEFAULT_BILL_CYCLE_START_DAY,
    PEAK_AVOIDANCE_MIN_SERVED_KW,
    PEC_FIXED_CHARGES,
)
from .energy_tou import TOURateEngine
from ..const import (
    CONF_ELECTRICITY_RATE,
    DEFAULT_ELECTRICITY_RATE,
)

_LOGGER = logging.getLogger(__name__)


def _get_effective_rate_kwh(
    hass: HomeAssistant,
    *,
    room_entry=None,
) -> tuple[float, str]:
    """Return (rate_$/kWh, source) — EC TOU when configured, static fallback otherwise.

    Resolution order:
    1. EC's current_effective_rate (TOU-aware)  → (rate, "ec_tou")
    2. Room entry's CONF_ELECTRICITY_RATE override (if room_entry given) → (rate, "static_config")
    3. Global integration CONF_ELECTRICITY_RATE  → (rate, "static_config")
    4. DEFAULT_ELECTRICITY_RATE                  → (rate, "static_config")

    v4.6.8: Centralises every cost-rate lookup so the magic 0.1 fallback is
    eliminated and TOU awareness reaches all cost sensors automatically.
    Never raises — always returns a usable float.
    """
    from ..const import DOMAIN

    # 1. Try Energy Coordinator's live TOU rate.
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is not None:
            ec = manager.coordinators.get("energy")
            if ec is not None:
                rate = ec.current_effective_rate
                if rate is not None and isinstance(rate, (int, float)) and rate > 0:
                    return float(rate), "ec_tou"
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("rate helper tier 1 (EC TOU) failed: %s", exc)

    # 2. Room-level static override.
    if room_entry is not None:
        try:
            room_rate = room_entry.options.get(
                CONF_ELECTRICITY_RATE,
                room_entry.data.get(CONF_ELECTRICITY_RATE),
            )
            if room_rate is not None:
                return float(room_rate), "static_config"
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("rate helper tier 2 (room override) failed: %s", exc)

    # 3. Global integration entry static rate. Read the canonical slot:
    # __init__.py stores the integration entry directly at hass.data[DOMAIN]["integration"]
    # (a ConfigEntry — NOT wrapped in a dict). v4.6.8 fix: prior loop assumed
    # dict-shaped values and never matched, silently falling through to step 4.
    try:
        integration_entry = hass.data.get(DOMAIN, {}).get("integration")
        if integration_entry is not None:
            global_rate = integration_entry.options.get(
                CONF_ELECTRICITY_RATE,
                integration_entry.data.get(CONF_ELECTRICITY_RATE),
            )
            if global_rate is not None:
                return float(global_rate), "static_config"
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("rate helper tier 3 (global integration) failed: %s", exc)

    # 4. Hardcoded module-level default (never 0.1).
    return DEFAULT_ELECTRICITY_RATE, "static_config"


class CostTracker:
    """Tracks energy costs by TOU period, daily, and per billing cycle.

    Accumulates cost each decision cycle by reading current power and
    multiplying by the effective rate for the time elapsed.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        tou_engine: TOURateEngine,
        bill_cycle_day: int = DEFAULT_BILL_CYCLE_START_DAY,
        net_power_entity: str | None = None,
        solar_entity: str | None = None,
        grid_import_entity: str | None = None,
        grid_export_entity: str | None = None,
    ) -> None:
        """Initialize cost tracker.

        v4.2.0: Optional direct grid import/export sensors (e.g., Emporia mains).
        When configured, these are preferred over derived net_power values.
        """
        self.hass = hass
        self._tou = tou_engine
        self._bill_cycle_day = bill_cycle_day
        # v4.3.1: no production fallback. Envoy validation gate (v4.2.29) ensures
        # these are populated when EC is enabled; if they are None, downstream
        # methods (_get_net_power, etc.) handle gracefully via state.get(None).
        self._net_power_entity = net_power_entity
        self._solar_entity = solar_entity
        self._grid_import_entity = grid_import_entity
        self._grid_export_entity = grid_export_entity

        # Daily accumulators (reset at midnight)
        self._cost_today: float = 0.0
        self._import_kwh_today: float = 0.0
        self._import_cost_today: float = 0.0
        self._export_kwh_today: float = 0.0
        self._export_credit_today: float = 0.0
        self._last_date: str = ""

        # Billing cycle accumulators (reset on cycle day)
        self._cost_this_cycle: float = 0.0
        self._import_kwh_cycle: float = 0.0
        self._export_kwh_cycle: float = 0.0
        self._cycle_start_date: str = ""
        self._days_in_cycle: int = 0

        # Bill prediction
        self._predicted_bill: float | None = None
        self._last_accumulate_time: float | None = None

    def _get_net_power(self) -> float | None:
        """Get net power in kW (positive=importing, negative=exporting).

        v4.2.0: Prefers direct grid import/export sensors when configured.
        Falls back to net_power entity (Envoy) otherwise.
        Both paths normalize to kW for consistent accumulation.
        """
        # Prefer direct grid sensors (e.g., Emporia mains_from_grid / mains_to_grid)
        if self._grid_import_entity and self._grid_export_entity:
            import_state = self.hass.states.get(self._grid_import_entity)
            export_state = self.hass.states.get(self._grid_export_entity)
            if (
                import_state and import_state.state not in ("unknown", "unavailable")
                and export_state and export_state.state not in ("unknown", "unavailable")
            ):
                try:
                    grid_import = float(import_state.state)
                    grid_export = float(export_state.state)
                    net = grid_import - grid_export  # positive=importing
                    # Normalize to kW (accumulate() expects kW).
                    # Emporia reports W, Envoy reports kW.
                    uom = import_state.attributes.get("unit_of_measurement", "")
                    if uom in ("W", "w"):
                        net /= 1000.0
                    return net
                except (ValueError, TypeError):
                    pass  # Fall through to net_power

        # Fallback: Envoy net power entity (None if not configured — v4.3.1)
        # v4.5.0 unit-consistency: normalize to kW. Pre-v4.5.0 this path
        # returned the raw entity value; the docstring + accumulate()'s
        # `kW × hours = kWh` math assumed Envoy reports kW. Newer Envoy
        # firmware can report W — without normalization that produces
        # 1000× bill predictions. Same bug class as v4.3.4 battery_power_w.
        if self._net_power_entity is None:
            return None
        state = self.hass.states.get(self._net_power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("W", "w"):
            value /= 1000.0
        # If uom is "kW", value is already kW — pass through.
        return value

    def get_yesterday_totals(self) -> dict[str, float] | None:
        """Return yesterday's daily totals if we have them (before reset).

        Must be called BEFORE accumulate() on date change to capture
        the previous day's data before it's wiped.
        """
        if not self._last_date or self._last_date == dt_util.now().date().isoformat():
            return None  # No date change yet or same day
        return {
            "date": self._last_date,
            "import_kwh": round(self._import_kwh_today, 4),
            "export_kwh": round(self._export_kwh_today, 4),
            "import_cost": round(self._import_cost_today, 4),
            "export_credit": round(self._export_credit_today, 4),
            "net_cost": round(self._cost_today, 4),
        }

    def accumulate(self) -> None:
        """Accumulate cost based on current power readings.

        Called each decision cycle (~5 minutes). Uses elapsed time
        to calculate energy consumed/produced since last call.
        """
        import time
        now_ts = time.time()
        now = dt_util.now()
        today = now.date().isoformat()

        # Reset daily counters if date changed
        if today != self._last_date:
            self._cost_today = 0.0
            self._import_kwh_today = 0.0
            self._import_cost_today = 0.0
            self._export_kwh_today = 0.0
            self._export_credit_today = 0.0
            self._last_date = today

        # Reset cycle counters if we passed the cycle day
        self._check_cycle_reset(now)

        # Calculate energy since last accumulation
        if self._last_accumulate_time is None:
            self._last_accumulate_time = now_ts
            return

        elapsed_hours = (now_ts - self._last_accumulate_time) / 3600.0
        self._last_accumulate_time = now_ts

        if elapsed_hours <= 0 or elapsed_hours > 1:
            return  # Skip unreasonable intervals

        net_power = self._get_net_power()
        if net_power is None:
            return

        # net_power > 0 = importing from grid
        # net_power < 0 = exporting to grid
        # Envoy reports net power in kW, so kW * hours = kWh directly
        energy_kwh = abs(net_power) * elapsed_hours

        if net_power > 0:
            # Importing
            effective_rate = self._tou.get_effective_import_rate(now)
            cost = energy_kwh * effective_rate
            self._import_kwh_today += energy_kwh
            self._import_cost_today += cost
            self._cost_today += cost
            self._import_kwh_cycle += energy_kwh
            self._cost_this_cycle += cost
        else:
            # Exporting
            export_rate = self._tou.get_export_rate(now)
            credit = energy_kwh * export_rate
            self._export_kwh_today += energy_kwh
            self._export_credit_today += credit
            self._cost_today -= credit
            self._export_kwh_cycle += energy_kwh
            self._cost_this_cycle -= credit

        # Update bill prediction
        self._update_prediction(now)

    def _check_cycle_reset(self, now: datetime) -> None:
        """Reset billing cycle accumulators if we passed the cycle start day."""
        cycle_date = self._get_cycle_start(now)
        cycle_key = cycle_date.isoformat()

        if cycle_key != self._cycle_start_date:
            self._cycle_start_date = cycle_key
            self._cost_this_cycle = 0.0
            self._import_kwh_cycle = 0.0
            self._export_kwh_cycle = 0.0
            self._db_days_in_cycle = 0
            _LOGGER.info("Billing cycle reset: new cycle started %s", cycle_key)

        self._days_in_cycle = (now.date() - cycle_date).days

    def _get_cycle_start(self, now: datetime) -> date:
        """Get the start date of the current billing cycle."""
        day = self._bill_cycle_day
        if now.day >= day:
            return now.date().replace(day=day)
        # Before cycle day this month — cycle started last month
        first_of_month = now.date().replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        try:
            return last_month.replace(day=day)
        except ValueError:
            # Cycle day doesn't exist in last month (e.g., 31st in Feb)
            return last_month

    def update_from_db(self, db_cycle_data: dict) -> None:
        """Update cycle accumulators from DB data on startup.

        Called once after coordinator starts, to restore cycle totals
        that would otherwise be lost on HA restart.
        Must set _cycle_start_date so _check_cycle_reset() doesn't wipe.
        """
        db_days = db_cycle_data.get("days", 0)
        if db_days > 0:
            self._import_kwh_cycle = db_cycle_data.get("import_kwh", 0)
            self._export_kwh_cycle = db_cycle_data.get("export_kwh", 0)
            self._cost_this_cycle = db_cycle_data.get("net_cost", 0)
            self._db_days_in_cycle = db_days
            # Set cycle start so _check_cycle_reset() recognizes this cycle
            self._cycle_start_date = self._get_cycle_start(
                dt_util.now()
            ).isoformat()
            _LOGGER.info(
                "Restored billing cycle from DB: %d days, $%.2f net cost",
                db_days, self._cost_this_cycle,
            )

    def restore_daily(self, snapshot: dict[str, Any]) -> None:
        """Restore today's billing accumulators from midnight snapshot.

        Called on startup to recover partial-day billing that would
        otherwise be lost on HA restart. Only restores if the snapshot
        date matches today.
        """
        snapshot_date = snapshot.get("snapshot_date", "")
        today = dt_util.now().date().isoformat()
        if snapshot_date != today:
            _LOGGER.debug(
                "Midnight snapshot date %s != today %s, skipping billing restore",
                snapshot_date, today,
            )
            return

        self._import_kwh_today = snapshot.get("import_kwh_today", 0)
        self._export_kwh_today = snapshot.get("export_kwh_today", 0)
        self._import_cost_today = snapshot.get("import_cost_today", 0)
        self._export_credit_today = snapshot.get("export_credit_today", 0)
        self._cost_today = snapshot.get("net_cost_today", 0)
        self._last_date = today
        _LOGGER.info(
            "Restored daily billing: import=%.3f kWh, export=%.3f kWh, cost=$%.4f",
            self._import_kwh_today, self._export_kwh_today, self._cost_today,
        )

    def _update_prediction(self, now: datetime) -> None:
        """Update bill prediction.

        Uses DB day count if available (survives restarts), else in-memory.
        Shows prediction after 7+ days of data in current cycle.
        """
        effective_days = getattr(self, "_db_days_in_cycle", 0) or self._days_in_cycle
        if effective_days < 7:
            self._predicted_bill = None
            self._prediction_label = f"Learning ({effective_days} days)"
            return

        self._prediction_label = None

        # Estimate total cycle days (~30)
        cycle_start = self._get_cycle_start(now)
        next_month = cycle_start.month + 1
        next_year = cycle_start.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        try:
            cycle_end = cycle_start.replace(year=next_year, month=next_month)
        except ValueError:
            cycle_end = cycle_start + timedelta(days=30)
        total_days = (cycle_end - cycle_start).days or 30

        # Linear extrapolation + fixed charges
        daily_rate = self._cost_this_cycle / max(effective_days, 1)
        projected_variable = daily_rate * total_days
        fixed = PEC_FIXED_CHARGES["service_availability"]
        self._predicted_bill = round(projected_variable + fixed, 2)

    @property
    def cost_today(self) -> float:
        """Net cost today (import cost - export credit)."""
        return round(self._cost_today, 4)

    @property
    def cost_this_cycle(self) -> float:
        """Net cost so far in billing cycle."""
        return round(self._cost_this_cycle, 4)

    @property
    def import_kwh_cycle(self) -> float:
        """Total grid import kWh this billing cycle."""
        return round(self._import_kwh_cycle, 2)

    @property
    def predicted_bill(self) -> float | None:
        """Predicted monthly bill (available after 7 days)."""
        return self._predicted_bill

    @property
    def current_effective_rate(self) -> float:
        """Current effective import rate including delivery and transmission."""
        return self._tou.get_effective_import_rate()

    @property
    def prediction_label(self) -> str | None:
        """Learning label shown while < 7 days of data."""
        return getattr(self, "_prediction_label", None)

    def get_status(self) -> dict[str, Any]:
        """Return billing status for sensors."""
        return {
            "cost_today": self.cost_today,
            "import_kwh_today": round(self._import_kwh_today, 3),
            "import_cost_today": round(self._import_cost_today, 4),
            "export_kwh_today": round(self._export_kwh_today, 3),
            "export_credit_today": round(self._export_credit_today, 4),
            "cost_this_cycle": self.cost_this_cycle,
            "import_kwh_cycle": round(self._import_kwh_cycle, 3),
            "export_kwh_cycle": round(self._export_kwh_cycle, 3),
            "days_in_cycle": self._days_in_cycle,
            "cycle_start_date": self._cycle_start_date,
            "predicted_bill": self.predicted_bill,
            "prediction_label": self.prediction_label,
            "current_effective_rate": round(self.current_effective_rate, 6),
        }


# ============================================================================
# Energy Savings Unification (cycle #7) — peak-avoidance accumulator
# ============================================================================
# Design (see docs/planning/PLANNING_energy_savings_unification.md §D1 RE-SITE):
#
#   served_locally_kW = max(0, solar + battery_discharge - battery_charge - grid_export)
#   credit_$ = served_locally_kW × Δh × get_effective_import_rate(now)
#
# Double-count guard (operator decision #4): battery-discharged kWh already
# get their off-peak-to-displaced delta booked by arbitrage. To avoid double
# credit, the battery portion of served_locally during displaced-rate periods
# (peak / mid_peak) is credited at only `max(0, effective_rate - displaced_rate)`
# per kWh; the solar portion is credited at the full effective_rate.
#
# This class is intentionally isolated from CostTracker so a fault here cannot
# touch `cost_today` / `cost_this_cycle` (the shared billing hot-path). It is
# also independent of any specific entity plumbing — the caller passes in a
# snapshot each tick, which makes it directly unit-testable end-to-end.

_DISPLACED_PERIODS = ("peak", "mid_peak")


class PeakAvoidanceTracker:
    """Tick-level accumulator for peak-avoidance $ and kWh-avoided.

    Reset semantics mirror CostTracker (local midnight for today; the
    `_check_cycle_reset` logic for billing_cycle via the same
    `_get_cycle_start` shape).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        bill_cycle_day: int = DEFAULT_BILL_CYCLE_START_DAY,
    ) -> None:
        self.hass = hass
        self._bill_cycle_day = bill_cycle_day

        # Per-scope accumulators (all reset on their scope boundary).
        self._pa_today: float = 0.0
        self._pa_cycle: float = 0.0
        self._kwh_avoided_today: float = 0.0
        self._kwh_avoided_cycle: float = 0.0
        # Lifetime "since baseline" — cumulative from cutover. The lifetime
        # sensor renders `baseline + this` so a DB prune of the source
        # arbitrage_cycles rows cannot silently shrink the lifetime number.
        self._pa_lifetime_delta: float = 0.0
        self._kwh_avoided_lifetime_delta: float = 0.0

        self._last_date: str = ""
        self._cycle_start_date: str = ""
        self._last_accumulate_ts: float | None = None
        # B-HIGH-1/2 (fix-up): tracks the local-date on which the
        # lifetime delta was last rolled into the persisted baseline row.
        # See pop_lifetime_delta_for_rollup().
        self._last_lifetime_rollup_date: str = ""

    # -- reset scaffolding (mirrors CostTracker._check_cycle_reset shape) --

    def _get_cycle_start(self, now: datetime) -> date:
        day = self._bill_cycle_day
        if now.day >= day:
            return now.date().replace(day=day)
        first_of_month = now.date().replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        try:
            return last_month.replace(day=day)
        except ValueError:
            return last_month

    def _maybe_reset(self, now: datetime) -> None:
        today = now.date().isoformat()
        if today != self._last_date:
            self._pa_today = 0.0
            self._kwh_avoided_today = 0.0
            self._last_date = today
        cycle_key = self._get_cycle_start(now).isoformat()
        if cycle_key != self._cycle_start_date:
            self._pa_cycle = 0.0
            self._kwh_avoided_cycle = 0.0
            self._cycle_start_date = cycle_key
            _LOGGER.info(
                "Peak-avoidance billing cycle reset: new cycle started %s",
                cycle_key,
            )

    # -- core accumulator --------------------------------------------------

    def accumulate(
        self,
        *,
        now: datetime,
        solar_kw: float | None,
        battery_power_kw: float | None,  # + charging, - discharging
        net_import_kw: float | None,  # + importing, - exporting
        effective_rate: float,
        displaced_rate: float,
        period: str | None,
    ) -> None:
        """Accumulate one tick of peak-avoidance value.

        All inputs are already in kW / $/kWh. Guarded — a bad input silently
        skips this tick rather than propagating any exception up into the
        decision cycle.
        """
        # Derive elapsed from the passed-in `now` (test-friendly — a fake
        # clock is threaded through by advancing `now`). Production always
        # supplies dt_util.now(); a None `now` is treated as a no-op tick
        # (mirrors the net_import guard below — never fabricate time).
        # LOW-1 (fix-up): removed the wall-clock fallback branch (dead;
        # never exercised in production and would have inflated elapsed
        # across a restart).
        if now is None:
            return
        now_ts = now.timestamp()
        self._maybe_reset(now)

        if self._last_accumulate_ts is None:
            self._last_accumulate_ts = now_ts
            return
        elapsed_h = (now_ts - self._last_accumulate_ts) / 3600.0
        self._last_accumulate_ts = now_ts
        if elapsed_h <= 0 or elapsed_h > 1:
            return

        try:
            solar_kw = max(0.0, float(solar_kw or 0.0))
            bp = float(battery_power_kw) if battery_power_kw is not None else 0.0
            discharge_kw = max(0.0, -bp)
            charge_kw = max(0.0, bp)
            # A-HIGH-1 (fix-up): mirror CostTracker.accumulate's None-guard
            # (energy_billing.py ~:244-246). Treating unknown grid flow as 0
            # would credit real EXPORT as served-locally during Envoy blind
            # windows (up to 50% over-credit). Skip the tick instead.
            if net_import_kw is None:
                return
            net = float(net_import_kw)
            export_kw = max(0.0, -net)

            served_kw = max(
                0.0,
                solar_kw + discharge_kw - charge_kw - export_kw,
            )
            if served_kw < PEAK_AVOIDANCE_MIN_SERVED_KW:
                return

            # Attribute the served-locally kW between battery-discharge and
            # solar. Battery gets attributed first (bounded by discharge_kw)
            # because that's the portion the double-count guard applies to.
            battery_served_kw = min(served_kw, discharge_kw)
            solar_served_kw = served_kw - battery_served_kw

            rate = float(effective_rate or 0.0)
            if period in _DISPLACED_PERIODS:
                # Decision #4 guard: arbitrage-discharged kWh already booked
                # the (displaced - off_peak) delta. Credit only the residual
                # (effective_rate - displaced_rate), clamped >= 0.
                battery_credit_per_kwh = max(
                    0.0, rate - float(displaced_rate or 0.0)
                )
            else:
                battery_credit_per_kwh = rate

            energy_kwh = served_kw * elapsed_h
            battery_energy_kwh = battery_served_kw * elapsed_h
            solar_energy_kwh = solar_served_kw * elapsed_h

            credit = (
                solar_energy_kwh * rate
                + battery_energy_kwh * battery_credit_per_kwh
            )
            if credit < 0:
                return  # defensive — should never happen with the clamps

            self._pa_today += credit
            self._pa_cycle += credit
            self._pa_lifetime_delta += credit
            self._kwh_avoided_today += energy_kwh
            self._kwh_avoided_cycle += energy_kwh
            self._kwh_avoided_lifetime_delta += energy_kwh
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("PeakAvoidanceTracker.accumulate skipped: %s", exc)

    # -- read-side ---------------------------------------------------------

    @property
    def peak_avoidance_today(self) -> float:
        return round(self._pa_today, 4)

    @property
    def peak_avoidance_cycle(self) -> float:
        return round(self._pa_cycle, 4)

    @property
    def peak_avoidance_lifetime_delta(self) -> float:
        return round(self._pa_lifetime_delta, 4)

    @property
    def kwh_avoided_today(self) -> float:
        return round(self._kwh_avoided_today, 4)

    @property
    def kwh_avoided_cycle(self) -> float:
        return round(self._kwh_avoided_cycle, 4)

    @property
    def kwh_avoided_lifetime_delta(self) -> float:
        return round(self._kwh_avoided_lifetime_delta, 4)

    METHODOLOGY: str = (
        "Peak-avoidance counterfactual: for each decision tick, credit "
        "served_locally_kW × Δh × effective_import_rate(now), where "
        "served_locally = max(0, solar + battery_discharge - battery_charge "
        "- grid_export). Double-count guard: during peak/mid_peak, the "
        "battery-served portion is credited only at max(0, effective_rate - "
        "displaced_rate) since arbitrage already booked the "
        "(displaced - off_peak) delta on that kWh. Ticks below "
        f"{PEAK_AVOIDANCE_MIN_SERVED_KW} kW served-locally are ignored as "
        "noise floor. Display-only; not billing-grade."
    )

    # -- restart persistence (mirrors CostTracker.restore_daily idiom) -----
    #
    # B-HIGH-1 / B-HIGH-2 (fix-up): without these, every HA restart wiped
    # peak_avoidance_today/_cycle and the lifetime_delta -> lifetime sensor
    # dropped to just the baseline row. Snapshot save+restore mirrors the
    # CostTracker daily/cycle idiom (energy_billing.py:325-351 +
    # :304-324); lifetime is preserved via pop_lifetime_delta_for_rollup()
    # which the coordinator writes into the savings_lifetime_baseline row
    # once/day at local midnight (writes = 2/day, not per-tick — respects
    # v5.2.1 write-flood lesson).

    def snapshot_state(self) -> dict[str, Any]:
        """Return an opaque snapshot dict for persistence."""
        return {
            "snapshot_date": self._last_date,
            "cycle_start_date": self._cycle_start_date,
            "pa_today": round(self._pa_today, 6),
            "pa_cycle": round(self._pa_cycle, 6),
            "kwh_avoided_today": round(self._kwh_avoided_today, 6),
            "kwh_avoided_cycle": round(self._kwh_avoided_cycle, 6),
            "pa_lifetime_delta": round(self._pa_lifetime_delta, 6),
            "kwh_avoided_lifetime_delta": round(
                self._kwh_avoided_lifetime_delta, 6
            ),
            "last_lifetime_rollup_date": self._last_lifetime_rollup_date,
        }

    def restore_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        """Restore PA accumulators from a prior snapshot.

        `today`/`cycle` are only restored if their scope key matches current
        wall-time scope (so a stale snapshot from a prior day/cycle doesn't
        contaminate current-scope numbers). `lifetime_delta` is always
        restored — it's monotonic between midnight rollups.
        """
        if not snapshot:
            return
        try:
            now = dt_util.now()
            today = now.date().isoformat()
            cycle_key = self._get_cycle_start(now).isoformat()

            snap_date = snapshot.get("snapshot_date") or ""
            snap_cycle = snapshot.get("cycle_start_date") or ""

            if snap_date == today:
                self._pa_today = float(snapshot.get("pa_today", 0.0) or 0.0)
                self._kwh_avoided_today = float(
                    snapshot.get("kwh_avoided_today", 0.0) or 0.0
                )
                self._last_date = today
            if snap_cycle == cycle_key:
                self._pa_cycle = float(snapshot.get("pa_cycle", 0.0) or 0.0)
                self._kwh_avoided_cycle = float(
                    snapshot.get("kwh_avoided_cycle", 0.0) or 0.0
                )
                self._cycle_start_date = cycle_key

            # Lifetime delta is always restored (monotonic between midnight
            # rollups; coordinator will fold it into the baseline row on
            # the next local-midnight boundary).
            self._pa_lifetime_delta = float(
                snapshot.get("pa_lifetime_delta", 0.0) or 0.0
            )
            self._kwh_avoided_lifetime_delta = float(
                snapshot.get("kwh_avoided_lifetime_delta", 0.0) or 0.0
            )
            self._last_lifetime_rollup_date = (
                snapshot.get("last_lifetime_rollup_date") or ""
            )
            _LOGGER.info(
                "Restored peak-avoidance snapshot: today=$%.4f cycle=$%.4f "
                "lifetime_delta=$%.4f",
                self._pa_today, self._pa_cycle, self._pa_lifetime_delta,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PeakAvoidanceTracker.restore_snapshot failed", exc_info=True
            )

    def pop_lifetime_delta_for_rollup(
        self, today_iso: str
    ) -> tuple[float, float] | None:
        """Return (usd_delta, kwh_delta) once per local-date, else None.

        Called by the coordinator at local-midnight snapshot time. If a
        rollup has already been done for `today_iso`, returns None (idempotent
        — enforces the 2-writes/day cap even if called on the per-3-cycle
        cadence). On success, zeros the in-RAM deltas so the lifetime sensor
        continues to render `baseline + delta` monotonically.
        """
        if not today_iso or today_iso == self._last_lifetime_rollup_date:
            return None
        usd = self._pa_lifetime_delta
        kwh = self._kwh_avoided_lifetime_delta
        if usd <= 0.0 and kwh <= 0.0:
            # Nothing to roll — still mark date to avoid re-checking every
            # cycle for the rest of the day.
            self._last_lifetime_rollup_date = today_iso
            return None
        self._pa_lifetime_delta = 0.0
        self._kwh_avoided_lifetime_delta = 0.0
        self._last_lifetime_rollup_date = today_iso
        return (usd, kwh)

    def get_status(self) -> dict[str, Any]:
        return {
            "peak_avoidance_today": self.peak_avoidance_today,
            "peak_avoidance_cycle": self.peak_avoidance_cycle,
            "peak_avoidance_lifetime_delta": self.peak_avoidance_lifetime_delta,
            "kwh_avoided_today": self.kwh_avoided_today,
            "kwh_avoided_cycle": self.kwh_avoided_cycle,
            "kwh_avoided_lifetime_delta": self.kwh_avoided_lifetime_delta,
            "methodology": self.METHODOLOGY,
        }
