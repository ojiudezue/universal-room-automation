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
    DEFAULT_NET_POWER_ENTITY,
    DEFAULT_SOLAR_PRODUCTION_ENTITY,
    PEC_FIXED_CHARGES,
)
from .energy_tou import TOURateEngine

_LOGGER = logging.getLogger(__name__)


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
        self._net_power_entity = net_power_entity or DEFAULT_NET_POWER_ENTITY
        self._solar_entity = solar_entity or DEFAULT_SOLAR_PRODUCTION_ENTITY
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

        # Fallback: Envoy net power entity
        state = self.hass.states.get(self._net_power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

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
