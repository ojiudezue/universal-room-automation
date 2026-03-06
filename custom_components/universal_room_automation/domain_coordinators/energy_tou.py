"""TOU (Time-of-Use) rate engine for Energy Coordinator.

Resolves current season, TOU period, and import/export rates based on
the PEC Interconnect TOU rate schedule.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .energy_const import PEC_FIXED_CHARGES, PEC_TOU_RATES

_LOGGER = logging.getLogger(__name__)


class TOURateEngine:
    """Resolves TOU season, period, and rates from a rate table.

    The rate table defaults to PEC 2026 but can be overridden via config.
    """

    def __init__(self, rate_table: dict | None = None) -> None:
        """Initialize with optional rate table override."""
        self._rates = rate_table or PEC_TOU_RATES
        self._fixed = PEC_FIXED_CHARGES
        self._last_period: str | None = None

    def get_season(self, now: datetime | None = None) -> str:
        """Return the current TOU season: summer, shoulder, or winter."""
        if now is None:
            now = dt_util.now()
        month = now.month
        for season_name, season_data in self._rates.items():
            if month in season_data["months"]:
                return season_name
        return "shoulder"

    def get_current_period(self, now: datetime | None = None) -> str:
        """Return the current TOU period: off_peak, mid_peak, or peak."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        hour = now.hour
        season_data = self._rates[season]
        for period_name, period_data in season_data["periods"].items():
            for start, end in period_data["hours"]:
                if start <= hour < end:
                    return period_name
        return "off_peak"

    def get_current_rate(self, now: datetime | None = None) -> float:
        """Return the current import rate in $/kWh (base power charge only)."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        period = self.get_current_period(now)
        return self._rates[season]["periods"][period]["import_rate"]

    def get_export_rate(self, now: datetime | None = None) -> float:
        """Return the current export credit rate in $/kWh."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        period = self.get_current_period(now)
        return self._rates[season]["periods"][period]["export_rate"]

    def get_effective_import_rate(self, now: datetime | None = None) -> float:
        """Return effective import cost: base power + delivery + transmission."""
        base = self.get_current_rate(now)
        return base + self._fixed["delivery_per_kwh"] + self._fixed["transmission_per_kwh"]

    def get_next_transition(self, now: datetime | None = None) -> dict[str, Any]:
        """Return info about the next TOU period transition.

        Returns dict with: next_period, hours_until, transition_hour
        """
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        current_period = self.get_current_period(now)
        current_hour = now.hour

        # Build sorted list of transition hours for today's season
        transitions: list[tuple[int, str]] = []
        for period_name, period_data in self._rates[season]["periods"].items():
            for start, _end in period_data["hours"]:
                transitions.append((start, period_name))
        transitions.sort()

        # Find the next transition after current hour
        for t_hour, t_period in transitions:
            if t_hour > current_hour and t_period != current_period:
                return {
                    "next_period": t_period,
                    "hours_until": t_hour - current_hour,
                    "transition_hour": t_hour,
                }

        # Wrap to next day's first different period
        for t_hour, t_period in transitions:
            if t_period != current_period:
                return {
                    "next_period": t_period,
                    "hours_until": (24 - current_hour) + t_hour,
                    "transition_hour": t_hour,
                }

        return {"next_period": "off_peak", "hours_until": 24, "transition_hour": 0}

    def check_period_transition(self, now: datetime | None = None) -> str | None:
        """Check if TOU period has changed since last check.

        Returns the new period name if changed, None otherwise.
        """
        current = self.get_current_period(now)
        if self._last_period is not None and current != self._last_period:
            old = self._last_period
            self._last_period = current
            _LOGGER.info("TOU period transition: %s -> %s", old, current)
            return current
        self._last_period = current
        return None

    def get_period_info(self, now: datetime | None = None) -> dict[str, Any]:
        """Return comprehensive info about current TOU state."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        period = self.get_current_period(now)
        return {
            "season": season,
            "period": period,
            "import_rate": self.get_current_rate(now),
            "export_rate": self.get_export_rate(now),
            "effective_import_rate": self.get_effective_import_rate(now),
            "fixed_charges": self._fixed,
            "next_transition": self.get_next_transition(now),
        }
