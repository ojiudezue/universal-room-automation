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

# Entities for energy accumulation (from HA Energy dashboard)
DEFAULT_GRID_IMPORT_ENERGY = "sensor.envoy_202428004328_lifetime_energy_consumption"
DEFAULT_GRID_EXPORT_ENERGY = "sensor.envoy_202428004328_lifetime_energy_production"


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
    ) -> None:
        """Initialize cost tracker."""
        self.hass = hass
        self._tou = tou_engine
        self._bill_cycle_day = bill_cycle_day
        self._net_power_entity = net_power_entity or DEFAULT_NET_POWER_ENTITY
        self._solar_entity = solar_entity or DEFAULT_SOLAR_PRODUCTION_ENTITY

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
        """Get net power in watts (positive=importing, negative=exporting)."""
        state = self.hass.states.get(self._net_power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

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
        energy_kwh = abs(net_power) / 1000.0 * elapsed_hours

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

    def _update_prediction(self, now: datetime) -> None:
        """Update bill prediction after 7+ days of cycle data."""
        if self._days_in_cycle < 7:
            self._predicted_bill = None
            return

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
        daily_rate = self._cost_this_cycle / max(self._days_in_cycle, 1)
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
            "current_effective_rate": round(self.current_effective_rate, 6),
        }
