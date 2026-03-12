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
    Supports loading from a JSON file at /config/universal_room_automation/tou_rates.json.
    """

    # Normalize period names from JSON to internal names used by determine_mode()
    _PERIOD_ALIASES: dict[str, str] = {
        "on_peak": "peak",
        "on-peak": "peak",
        "onpeak": "peak",
        "off-peak": "off_peak",
        "offpeak": "off_peak",
        "mid-peak": "mid_peak",
        "midpeak": "mid_peak",
    }
    _VALID_PERIODS = {"peak", "mid_peak", "off_peak"}

    def __init__(
        self,
        rate_table: dict | None = None,
        fixed_charges: dict | None = None,
        rate_source: str = "built-in PEC 2026",
    ) -> None:
        """Initialize with optional rate table override."""
        self._rates = rate_table or PEC_TOU_RATES
        self._fixed = fixed_charges or PEC_FIXED_CHARGES
        self._last_period: str | None = None
        self._rate_file_loaded: bool = rate_table is not None
        self._rate_source: str = rate_source

    @classmethod
    def from_json_file(cls, config_dir: str, filename: str) -> "TOURateEngine":
        """Load TOU rates from a JSON file.

        Expected format: see docs/plans/ENERGY_COORDINATOR_PLAN.md section 11.5
        Falls back to PEC defaults if file not found or invalid.
        """
        import json
        from pathlib import Path

        filepath = Path(config_dir) / filename
        if not filepath.exists():
            _LOGGER.debug("TOU rate file not found at %s, using PEC defaults", filepath)
            return cls()

        try:
            data = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Failed to load TOU rate file %s: %s — using PEC defaults", filepath, exc)
            return cls()

        # Convert JSON format to internal rate table format
        try:
            rate_table = {}
            for season_name, season_data in data.get("seasons", {}).items():
                periods = {}
                for period_name, period_data in season_data.get("periods", {}).items():
                    # Normalize period names (e.g. "on_peak" → "peak")
                    internal_name = cls._PERIOD_ALIASES.get(period_name, period_name)
                    hours = [tuple(h) for h in period_data.get("hours", [])]
                    # Support separate import/export rates; fall back to
                    # symmetric "rate" field for backward compat.
                    symmetric_rate = period_data.get("rate", 0.0)
                    import_rate = period_data.get("import_rate", symmetric_rate)
                    export_rate = period_data.get("export_rate", symmetric_rate)
                    if internal_name not in cls._VALID_PERIODS:
                        _LOGGER.warning(
                            "Unknown TOU period '%s' (from '%s') in %s season %s — ignored",
                            internal_name, period_name, filepath, season_name,
                        )
                        continue
                    periods[internal_name] = {
                        "hours": hours,
                        "import_rate": import_rate,
                        "export_rate": export_rate,
                    }
                # off_peak is required — get_current_period() falls back to it
                if "off_peak" not in periods:
                    _LOGGER.error(
                        "TOU rate file %s missing required 'off_peak' period in season '%s' "
                        "— falling back to PEC defaults",
                        filepath, season_name,
                    )
                    return cls()
                rate_table[season_name] = {
                    "months": season_data.get("months", []),
                    "periods": periods,
                }

            fixed = data.get("fixed_charges", {})
            fixed_charges = {
                "service_availability": fixed.get("service_availability_monthly", 32.50),
                "delivery_per_kwh": fixed.get("delivery_per_kwh", 0.022546),
                "transmission_per_kwh": fixed.get("transmission_per_kwh", 0.019930),
            }

            utility = data.get("utility", "unknown")
            effective = data.get("effective_date", "unknown")
            rate_source = f"{filename} ({utility}, effective {effective})"

            _LOGGER.info(
                "Loaded TOU rates from %s (utility: %s, effective: %s)",
                filepath, utility, effective,
            )
            return cls(
                rate_table=rate_table,
                fixed_charges=fixed_charges,
                rate_source=rate_source,
            )
        except Exception:
            _LOGGER.exception("Failed to parse TOU rate file %s — using PEC defaults", filepath)
            return cls()

    @property
    def rate_source(self) -> str:
        """Return the source of TOU rates (file path or 'built-in PEC 2026')."""
        return self._rate_source

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
            "rate_source": self._rate_source,
        }
